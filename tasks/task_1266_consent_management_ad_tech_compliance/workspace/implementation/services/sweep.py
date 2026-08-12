"""Regulatory sweep services: penalty exposure computation, the escalation
cascade, and property posture maintenance."""
from decimal import Decimal, ROUND_HALF_UP

from db import store, now_iso, touch
from clock import get_now
from services.consent import parse_dt

HIGH_BASE_CENTS = 250000
MEDIUM_BASE_CENTS = 77777
DAILY_RATE = Decimal("0.05")
DAY_CAP = 30


def compute_penalty_exposure(property_id, escalated_at):
    """sweep_penalty_exposure_cents: per CONFIRMED_VIOLATION finding of the
    property (joined through its scan), round_half_up FIRST, then sum."""
    scan_to_property = {
        sid: s.get("property_id") for sid, s in store["tag_audit_scans"].items()
    }
    total = 0
    for finding in store["tracker_findings"].values():
        if finding.get("status") != "CONFIRMED_VIOLATION":
            continue
        if scan_to_property.get(finding.get("scan_id")) != property_id:
            continue
        created = parse_dt(finding.get("created_at"))
        if created is None:
            days_open = 0
        else:
            days_open = int((escalated_at - created).total_seconds() // 86400)
            if days_open < 0:
                days_open = 0
        days_capped = min(days_open, DAY_CAP)
        base = HIGH_BASE_CENTS if finding.get("severity") == "HIGH" else MEDIUM_BASE_CENTS
        raw = Decimal(base) * (Decimal(1) + DAILY_RATE * Decimal(days_capped))
        per_finding = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        total += per_finding
    return total


def escalate_sweep(sweep):
    """Full escalation cascade (each hop caused by the previous):
    stamp + penalty -> posture FROZEN -> PUBLISHED configs SUPPRESSED ->
    their ENABLED tag rules DISABLED."""
    now = get_now()
    sweep["status"] = "ESCALATED"
    sweep["escalated_at"] = now_iso()
    sweep["penalty_exposure_cents"] = compute_penalty_exposure(
        sweep.get("property_id"), now
    )
    touch(sweep)

    prop = store["properties"].get(sweep.get("property_id"))
    if prop is None:
        return
    # Cascade link 1: posture -> FROZEN (version bumps on the flip)
    if prop.get("posture") != "FROZEN":
        prop["posture"] = "FROZEN"
        touch(prop)
    # Cascade link 2: every PUBLISHED config of the property -> SUPPRESSED
    for cfg in list(store["banner_configs"].values()):
        if cfg.get("property_id") == prop.get("id") and cfg.get("status") == "PUBLISHED":
            cfg["status"] = "SUPPRESSED"
            touch(cfg)
            # Cascade link 3: each suppressed config's ENABLED rules -> DISABLED
            for rule in list(store["tag_rules"].values()):
                if (
                    rule.get("banner_config_id") == cfg.get("id")
                    and rule.get("status") == "ENABLED"
                ):
                    rule["status"] = "DISABLED"
                    touch(rule)


def recompute_posture(property_id):
    """Posture is FROZEN while any sweep of the property is ESCALATED.
    Flips back to NORMAL (with property touch) when the last one closes."""
    prop = store["properties"].get(property_id)
    if prop is None:
        return
    any_escalated = any(
        s.get("property_id") == property_id and s.get("status") == "ESCALATED"
        for s in store["regulatory_sweeps"].values()
    )
    desired = "FROZEN" if any_escalated else "NORMAL"
    if prop.get("posture") != desired:
        prop["posture"] = desired
        touch(prop)
