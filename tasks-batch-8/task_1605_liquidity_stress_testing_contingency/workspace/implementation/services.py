"""Business logic: calculations (SCAFFOLD 1.3) and cascading side effects."""
from datetime import timedelta

from db import mint_id, store
from errors import (
    ApiError,
    ERR_DEESCALATION_BLOCKED,
    ERR_FORBIDDEN,
)
from helpers import fmt_dt, new_event, now_iso, touch

POSTURE_ORD = {"NORMAL": 0, "HEIGHTENED": 1, "SEVERE": 2, "CRISIS": 3}
ORD_POSTURE = {v: k for k, v in POSTURE_ORD.items()}
HAIRCUT_BPS = {"LEVEL_1": 0, "LEVEL_2A": 1500, "LEVEL_2B": 2500}
LEVEL2_CLASSES = ("LEVEL_2A", "LEVEL_2B")
WHOLESALE_CHANNELS = {"WHOLESALE_UNSECURED", "WHOLESALE_SECURED", "BROKERED"}


# ---------------------------------------------------------------------------
# hqla_adjusted_value: floor per asset BEFORE summing (order pinned).
# ---------------------------------------------------------------------------
def hqla_adjusted_total(addon_bps):
    """STRESS/BASELINE adjusted total over UNENCUMBERED assets.

    addon_bps applies only to LEVEL_2A/LEVEL_2B (0 for the BASELINE variant).
    Returns (total_cents, asset_count).
    """
    total = 0
    count = 0
    for a in store.assets.values():
        if a["encumbrance_status"] != "UNENCUMBERED":
            continue
        hc = HAIRCUT_BPS[a["asset_class"]]
        if a["asset_class"] in LEVEL2_CLASSES:
            hc += addon_bps
        total += a["market_value_cents"] * (10000 - hc) // 10000
        count += 1
    return total, count


def asset_adjusted_value(asset, addon_bps):
    hc = HAIRCUT_BPS[asset["asset_class"]]
    if asset["asset_class"] in LEVEL2_CLASSES:
        hc += addon_bps
    return asset["market_value_cents"] * (10000 - hc) // 10000


# ---------------------------------------------------------------------------
# borrowing_power: pinned evaluation order.
#   (1) pledged total over ACTIVE pledges
#   (2) collateral_cap = floor(pledged * advance_rate_bps / 10000)
#   (3) power = max(0, min(total_capacity, collateral_cap) - drawn)
# Suspension rule evaluated after any recompute.
# ---------------------------------------------------------------------------
def recompute_line(line):
    pledged = sum(
        p["pledged_value_cents"]
        for p in store.pledges.values()
        if p["line_id"] == line["id"] and p["status"] == "ACTIVE"
    )
    line["pledged_value_cents"] = pledged
    collateral_cap = pledged * line["advance_rate_bps"] // 10000
    cap = min(line["total_capacity_cents"], collateral_cap)
    line["borrowing_power_cents"] = max(0, cap - line["drawn_cents"])
    if line["drawn_cents"] > cap and line["status"] == "ACTIVE":
        # Auto-suspension cascade (caller touches the line once).
        line["status"] = "SUSPENDED"
        block_line_actions(line)


def block_line_actions(line):
    for a in store.actions.values():
        if (
            a["line_id"] == line["id"]
            and a["kind"] == "LINE_DRAWDOWN"
            and a["status"] in ("PENDING", "READY")
        ):
            a["status"] = "BLOCKED"
            touch(a)


def wake_line_actions(line):
    for a in store.actions.values():
        if a["line_id"] == line["id"] and a["status"] == "BLOCKED":
            pb = store.playbooks.get(a["playbook_id"])
            if pb is not None and pb["status"] in ("ACTIVATED", "EXECUTING"):
                a["status"] = "READY"
            else:
                a["status"] = "PENDING"
            touch(a)


# ---------------------------------------------------------------------------
# breach_detection: strict boundaries, dedupe on non-REMEDIATED breaches.
# ---------------------------------------------------------------------------
def detect_breaches(subjects, observed_by_subject, source_type, source_id,
                    ewi_metric_id=None):
    created = 0
    for lim in store.limits.values():
        if lim["subject"] not in subjects:
            continue
        if lim["subject"] == "EWI_METRIC" and lim["ewi_metric_id"] != ewi_metric_id:
            continue
        observed = observed_by_subject[lim["subject"]]
        if lim["direction"] == "ABOVE_BREACHES":
            breached = observed > lim["limit_value"]
        else:
            breached = observed < lim["limit_value"]
        if not breached:
            continue
        dupe = any(
            b["limit_id"] == lim["id"]
            and b["status"] in ("OPEN", "ACKNOWLEDGED", "ESCALATED")
            for b in store.breaches.values()
        )
        if dupe:
            continue
        br = {
            "id": mint_id(),
            "limit_id": lim["id"],
            "subject": lim["subject"],
            "detected_value": observed,
            "limit_value": lim["limit_value"],
            "status": "OPEN",
            "source_type": source_type,
            "source_id": source_id,
            "acknowledged_by_user_id": None,
            "remediated_by_user_id": None,
            "remediation_note": None,
        }
        ent = new_event({})
        br["created_at"] = ent["created_at"]
        br["_seq"] = ent["_seq"]
        # LimitBreach is versioned (common_fields: true)
        br["updated_at"] = br["created_at"]
        br["version"] = 1
        store.breaches[br["id"]] = br
        created += 1
    return created


# ---------------------------------------------------------------------------
# posture_evaluation: threshold algorithm with auto/manual variants.
# ---------------------------------------------------------------------------
def current_posture_level():
    if not store.posture_snapshots:
        return "NORMAL"
    snap = max(store.posture_snapshots.values(), key=lambda s: s["snapshot_seq"])
    return snap["level"]


def band_counts():
    red = sum(1 for m in store.metrics.values() if m["current_band"] == "RED")
    amber = sum(1 for m in store.metrics.values() if m["current_band"] == "AMBER")
    open_breaches = sum(1 for b in store.breaches.values() if b["status"] == "OPEN")
    return red, amber, open_breaches


def append_posture_evaluation(trigger, user_id, role=None):
    red, amber, open_breaches = band_counts()
    cur = current_posture_level()
    if red >= 2:
        raw = "CRISIS"
    elif red >= 1:
        raw = "SEVERE"
    elif amber >= 3 or open_breaches >= 2:
        raw = "HEIGHTENED"
    else:
        raw = "NORMAL"

    if trigger == "READING_AUTO":
        # Auto path can only escalate.
        new = raw if POSTURE_ORD[raw] > POSTURE_ORD[cur] else cur
    else:
        if POSTURE_ORD[raw] >= POSTURE_ORD[cur]:
            new = raw
        else:
            # De-escalation: committee only, clean reds/breaches, one step.
            if role != "LiquidityCommittee":
                raise ApiError(
                    ERR_FORBIDDEN, 403,
                    "Posture de-escalation requires the LiquidityCommittee role.")
            if red != 0 or open_breaches != 0:
                raise ApiError(
                    ERR_DEESCALATION_BLOCKED, 409,
                    "Posture de-escalation requires red_count == 0 and "
                    "open_breach_count == 0.")
            new = ORD_POSTURE[POSTURE_ORD[cur] - 1]

    store.posture_seq += 1
    snap = new_event({
        "id": mint_id(),
        "snapshot_seq": store.posture_seq,
        "level": new,
        "prior_level": cur,
        "red_count": red,
        "amber_count": amber,
        "open_breach_count": open_breaches,
        "trigger": trigger,
        "evaluated_by_user_id": user_id,
    })
    store.posture_snapshots[snap["id"]] = snap

    # Entering SEVERE/CRISIS from a strictly lower level escalates OPEN breaches.
    if new in ("SEVERE", "CRISIS") and POSTURE_ORD[new] > POSTURE_ORD[cur]:
        for b in store.breaches.values():
            if b["status"] == "OPEN":
                b["status"] = "ESCALATED"
                touch(b)
    return snap


# ---------------------------------------------------------------------------
# funding_concentration
# ---------------------------------------------------------------------------
def funding_concentration():
    total = sum(fs["balance_cents"] for fs in store.funding_sources.values())
    wholesale = sum(
        fs["balance_cents"]
        for fs in store.funding_sources.values()
        if fs["channel"] in WHOLESALE_CHANNELS
    )
    wholesale_bps = 0 if total == 0 else wholesale * 10000 // total
    by_cp = {}
    for fs in store.funding_sources.values():
        by_cp[fs["counterparty_name"]] = by_cp.get(fs["counterparty_name"], 0) + fs["balance_cents"]
    if total == 0 or not by_cp:
        return total, wholesale_bps, 0, None
    shares = {c: v * 10000 // total for c, v in by_cp.items()}
    top_bps = max(shares.values())
    # Tie-break: counterparty_name ASC (lexicographic).
    top_name = min(c for c, s in shares.items() if s == top_bps)
    return total, wholesale_bps, top_bps, top_name


# ---------------------------------------------------------------------------
# projection_cash_flow
# ---------------------------------------------------------------------------
def compute_projection(run, scenario):
    horizon = run["horizon_days"]
    outflows = [0] * (horizon + 1)  # 1-based day index
    if run["model_variant"] == "CONTRACTUAL":
        for fs in store.funding_sources.values():
            m = fs["matures_in_days"]
            if m is not None and 1 <= m <= horizon:
                outflows[m] += fs["balance_cents"]
    else:  # BEHAVIORAL
        renewal = scenario["wholesale_renewal_pct"]
        runoff = scenario["deposit_runoff_pct"]
        for fs in store.funding_sources.values():
            if fs["channel"] in WHOLESALE_CHANNELS:
                m = fs["matures_in_days"]
                if m is not None and 1 <= m <= horizon:
                    outflows[m] += fs["balance_cents"] * (100 - renewal) // 100
            elif fs["channel"] == "RETAIL_DEPOSIT":
                # Linear runoff over the horizon, floor per source per day.
                per_day = fs["balance_cents"] * runoff // 100 // horizon
                if per_day:
                    for d in range(1, horizon + 1):
                        outflows[d] += per_day
    hqla_available, _ = hqla_adjusted_total(scenario["level2_addon_bps"])
    cumulative = 0
    survival = horizon
    for d in range(1, horizon + 1):
        cumulative -= outflows[d]
        if cumulative + hqla_available < 0:
            survival = d
            break
    total_outflows = sum(outflows)
    return {
        "total_inflows_cents": 0,
        "total_outflows_cents": total_outflows,
        "net_cumulative_gap_cents": -total_outflows,
        "hqla_available_cents": hqla_available,
        "survival_days": survival,
    }


# ---------------------------------------------------------------------------
# capacity_test
# ---------------------------------------------------------------------------
def capacity_test(playbook):
    actions = [a for a in store.actions.values() if a["playbook_id"] == playbook["id"]]
    scenario = store.scenarios.get(playbook["scenario_id"])
    addon = scenario["level2_addon_bps"] if scenario else 0

    failures = []
    total_estimated = 0
    total_realizable = 0
    per_line_est = {}

    for a in actions:
        est = a["estimated_proceeds_cents"]
        if a["kind"] == "ASSET_SALE":
            asset = store.assets.get(a["asset_id"])
            if asset is not None and asset["encumbrance_status"] == "UNENCUMBERED":
                cap = asset_adjusted_value(asset, addon)
            else:
                cap = 0
        else:  # LINE_DRAWDOWN
            line = store.lines.get(a["line_id"])
            cap = line["borrowing_power_cents"] if line is not None and line["status"] == "ACTIVE" else 0
            per_line_est[a["line_id"]] = per_line_est.get(a["line_id"], 0) + est
        if cap < est:
            failures.append({
                "action_id": a["id"],
                "reason": "ACTION_CAPACITY_INSUFFICIENT",
                "estimated_proceeds_cents": est,
                "realizable_cents": cap,
            })
        total_estimated += est
        total_realizable += min(est, cap)

    for line_id, summed in per_line_est.items():
        line = store.lines.get(line_id)
        power = line["borrowing_power_cents"] if line is not None else 0
        if summed > power:
            failures.append({
                "line_id": line_id,
                "reason": "LINE_AGGREGATE_EXCEEDS_BORROWING_POWER",
                "estimated_proceeds_cents": summed,
                "borrowing_power_cents": power,
            })

    if total_estimated < playbook["target_capacity_cents"]:
        failures.append({
            "reason": "TARGET_CAPACITY_NOT_MET",
            "total_estimated_cents": total_estimated,
            "target_capacity_cents": playbook["target_capacity_cents"],
        })

    return {
        "result": "PASSED" if not failures else "FAILED",
        "total_estimated_cents": total_estimated,
        "total_realizable_cents": total_realizable,
        "failures": failures,
    }


# ---------------------------------------------------------------------------
# Current subject value, re-evaluated at breach remediate time.
# ---------------------------------------------------------------------------
def current_subject_value(breach):
    subject = breach["subject"]
    if subject == "EWI_METRIC":
        lim = store.limits.get(breach["limit_id"])
        metric = store.metrics.get(lim["ewi_metric_id"]) if lim else None
        if metric is None:
            return breach["detected_value"]
        readings = [r for r in store.readings.values() if r["metric_id"] == metric["id"]]
        if not readings:
            return breach["detected_value"]
        latest = max(readings, key=lambda r: (r["_observed_dt"], r["_seq"]))
        return latest["value"]
    if subject == "WHOLESALE_RELIANCE_PCT":
        return funding_concentration()[1]
    if subject == "TOP_COUNTERPARTY_PCT":
        return funding_concentration()[2]
    if subject == "SURVIVAL_DAYS":
        finals = [r for r in store.runs.values() if r["status"] == "FINALIZED"]
        if not finals:
            return breach["detected_value"]
        latest = max(finals, key=lambda r: r.get("_final_seq", 0))
        return latest["survival_days"]
    if subject == "INTRADAY_NET_POSITION":
        if not store.intraday_snapshots:
            return breach["detected_value"]
        latest = max(
            store.intraday_snapshots.values(),
            key=lambda s: (s["_snapshot_dt"], s["_seq"]))
        return latest["net_position_cents"]
    return breach["detected_value"]


def within_limit(direction, value, limit_value):
    if direction == "ABOVE_BREACHES":
        return value <= limit_value
    return value >= limit_value


# ---------------------------------------------------------------------------
# Reading cadence / settlement helpers
# ---------------------------------------------------------------------------
def reading_due(last_dt, interval_hours, new_dt):
    return new_dt >= last_dt + timedelta(hours=interval_hours)
