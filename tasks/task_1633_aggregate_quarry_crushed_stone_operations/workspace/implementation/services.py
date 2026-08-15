"""Shared business services: posture derivation, cascades, sweeps, calculations."""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from core import logical_now, logical_now_iso, logical_today, new_uuid, touch
from db import db
from errors import err_invalid_request


def D(value):
    """Decimal from JSON numeric input without float artifacts."""
    if isinstance(value, bool):
        raise err_invalid_request("Boolean is not a valid number")
    return Decimal(str(value))


def q(value, places):
    """Quantize with ROUND_HALF_UP."""
    return Decimal(str(value)).quantize(
        Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP
    )


def to_float(dec):
    return float(dec)


def parse_iso_date(value):
    """Parse YYYY-MM-DD string to date, or raise ERR_INVALID_REQUEST."""
    if not isinstance(value, str):
        raise err_invalid_request("Expected a date string (YYYY-MM-DD)")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise err_invalid_request("Invalid date format; expected YYYY-MM-DD")


def parse_iso_datetime(value):
    """Parse ISO 8601 datetime to aware datetime (UTC assumed if naive)."""
    from datetime import timezone

    if not isinstance(value, str):
        raise err_invalid_request("Expected an ISO 8601 datetime string")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        raise err_invalid_request("Invalid datetime format")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


from datetime import datetime  # noqa: E402  (kept local to avoid circular noise)


# ---------------------------------------------------------------------------
# Site posture derivation (pinned order) + cascades
# ---------------------------------------------------------------------------

def recompute_site(site_id):
    """Pinned evaluation order: (1) disturbed_acres, (2) bond_required/posted,
    (3) bond_adequacy, (4) posture; then hold/resume cascades on posture change.
    Every touched resource gets its own updated_at + version bump.
    """
    site = db.sites[site_id]
    old_posture = site["posture"]

    # (1) disturbed acres: benches in RELEASED, ON_HOLD, MINED_OUT, RECLAMATION_IN_PROGRESS
    full_statuses = {"RELEASED", "ON_HOLD", "MINED_OUT"}
    half_status = "RECLAMATION_IN_PROGRESS"
    disturbed = Decimal("0")
    required = Decimal("0")
    for bench in db.benches.values():
        if bench["site_id"] != site_id:
            continue
        acres = D(bench["acreage"])
        if bench["status"] in full_statuses:
            disturbed += acres
            required += acres * D(site["bond_rate_per_acre_usd"])
        elif bench["status"] == half_status:
            disturbed += acres
            required += acres * D(site["bond_rate_per_acre_usd"]) * Decimal("0.5")

    site["disturbed_acres"] = to_float(q(disturbed, 1))
    site["bond_required_usd"] = to_float(q(required, 2))

    # (2) bond_posted_usd
    posted = Decimal("0")
    for bond in db.reclamation_bonds.values():
        if bond["site_id"] != site_id:
            continue
        if bond["status"] in ("POSTED", "PARTIALLY_RELEASED"):
            posted += D(bond["amount_usd"]) - D(bond["released_usd"])
    site["bond_posted_usd"] = to_float(q(posted, 2))

    # (3) adequacy
    site["bond_adequacy"] = (
        "ADEQUATE" if D(site["bond_posted_usd"]) >= D(site["bond_required_usd"]) else "DEFICIENT"
    )

    # (4) posture
    today = logical_today()
    suspended = False
    any_issued = False
    for citation in db.msha_citations.values():
        if citation["status"] != "ISSUED":
            continue
        inspection = db.msha_inspections.get(citation["msha_inspection_id"])
        if not inspection or inspection["site_id"] != site_id:
            continue
        any_issued = True
        if citation.get("s_and_s") and parse_iso_date(citation["abatement_due_on"]) < today:
            suspended = True
    if suspended:
        site["posture"] = "SUSPENDED"
    elif site["bond_adequacy"] == "DEFICIENT" or any_issued:
        site["posture"] = "RESTRICTED"
    else:
        site["posture"] = "OPERATING"

    new_posture = site["posture"]

    # Cascades
    if old_posture != "SUSPENDED" and new_posture == "SUSPENDED":
        # Entering SUSPENDED: hold RELEASED benches (sentinel reason) and their live shot plans
        for bench in db.benches.values():
            if bench["site_id"] == site_id and bench["status"] == "RELEASED":
                bench["status"] = "ON_HOLD"
                bench["hold_reason"] = "MSHA_SUSPENSION"
                touch(bench)
                for plan in db.shot_plans.values():
                    if plan["bench_id"] == bench["id"] and plan["status"] in (
                        "APPROVED",
                        "DRILLING",
                        "DRILLED",
                        "LOADED",
                    ):
                        plan["hold_return_state"] = plan["status"]
                        plan["status"] = "ON_HOLD"
                        touch(plan)
    elif old_posture == "SUSPENDED" and new_posture in ("OPERATING", "RESTRICTED"):
        # Leaving SUSPENDED: auto-release only MSHA_SUSPENSION holds
        for bench in db.benches.values():
            if (
                bench["site_id"] == site_id
                and bench["status"] == "ON_HOLD"
                and bench.get("hold_reason") == "MSHA_SUSPENSION"
            ):
                bench["status"] = "RELEASED"
                bench["hold_reason"] = None
                touch(bench)
                for plan in db.shot_plans.values():
                    if plan["bench_id"] == bench["id"] and plan["status"] == "ON_HOLD":
                        plan["status"] = plan.get("hold_return_state") or "APPROVED"
                        plan["hold_return_state"] = None
                        touch(plan)

    touch(site)
    return site


# ---------------------------------------------------------------------------
# Stockpile helpers
# ---------------------------------------------------------------------------

def refresh_stockpile(pile):
    """Maintain available_tons = on_hand - reserved at 3-decimal precision."""
    on_hand = q(D(pile["on_hand_tons"]), 3)
    reserved = q(D(pile["reserved_tons"]), 3)
    pile["on_hand_tons"] = to_float(on_hand)
    pile["reserved_tons"] = to_float(reserved)
    pile["available_tons"] = to_float(q(on_hand - reserved, 3))


def reevaluate_quarantine(pile):
    """Latest confirmed, non-VOIDED test decides: max sampled_at, tie max created_at."""
    confirmed = [
        t
        for t in db.gradation_tests.values()
        if t["stockpile_id"] == pile["id"]
        and t["status"] == "CONFIRMED"
    ]
    if not confirmed:
        target = "OPEN"
    else:
        latest = max(confirmed, key=lambda t: (t["sampled_at"], t["created_at"]))
        target = "QUARANTINED" if latest["result"] == "FAIL" else "OPEN"
    if pile["status"] in ("OPEN", "QUARANTINED") and pile["status"] != target:
        pile["status"] = target
        touch(pile)


def allocation_sweep(pile):
    """Strict FIFO promotion of BACKORDERED orders of the same site+spec.
    Rank: created_at ASC, tie quantity_tons ASC, then customer_name ASC.
    Stop at first non-fitting order (no skipping).
    """
    if pile["status"] != "OPEN":
        return
    orders = [
        o
        for o in db.sales_orders.values()
        if o["status"] == "BACKORDERED"
        and o["site_id"] == pile["site_id"]
        and o["product_spec_id"] == pile["product_spec_id"]
    ]
    orders.sort(
        key=lambda o: (o["created_at"], D(o["quantity_tons"]), o["customer_name"])
    )
    for order in orders:
        refresh_stockpile(pile)
        if D(pile["available_tons"]) >= D(order["quantity_tons"]):
            order["status"] = "CONFIRMED"
            order["stockpile_id"] = pile["id"]
            pile["reserved_tons"] = to_float(
                q(D(pile["reserved_tons"]) + D(order["quantity_tons"]), 3)
            )
            refresh_stockpile(pile)
            touch(order)
            touch(pile)
        else:
            break


# ---------------------------------------------------------------------------
# Scale certification
# ---------------------------------------------------------------------------

def recompute_scale_certification(scale):
    """certified_through = latest non-VOIDED PASS calibrated_on + 180 days;
    OUT_OF_SERVICE + null when none remains. Any non-VOIDED FAIL forces OUT_OF_SERVICE."""
    non_voided = [
        c
        for c in db.scale_calibrations.values()
        if c["scale_id"] == scale["id"] and c["status"] != "VOIDED"
    ]
    # Latest calibration event decides service state: a FAIL takes it out.
    passes = [c for c in non_voided if c["result"] == "PASS"]
    fails = [c for c in non_voided if c["result"] == "FAIL"]
    if fails:
        latest_event = max(non_voided, key=lambda c: (c["calibrated_on"], c["created_at"]))
        if latest_event["result"] == "FAIL":
            scale["status"] = "OUT_OF_SERVICE"
            # certification window still recomputed from remaining PASS records
            if passes:
                latest_pass = max(passes, key=lambda c: (c["calibrated_on"], c["created_at"]))
                scale["certified_through"] = (
                    parse_iso_date(latest_pass["calibrated_on"]) + timedelta(days=180)
                ).isoformat()
            else:
                scale["certified_through"] = None
            touch(scale)
            return
    if passes:
        latest_pass = max(passes, key=lambda c: (c["calibrated_on"], c["created_at"]))
        scale["status"] = "CERTIFIED"
        scale["certified_through"] = (
            parse_iso_date(latest_pass["calibrated_on"]) + timedelta(days=180)
        ).isoformat()
    else:
        scale["status"] = "OUT_OF_SERVICE"
        scale["certified_through"] = None
    touch(scale)


def scale_usable(scale):
    if scale["status"] != "CERTIFIED":
        return False
    if not scale.get("certified_through"):
        return False
    return parse_iso_date(scale["certified_through"]) >= logical_today()


# ---------------------------------------------------------------------------
# Pricing (delivered_price_quote)
# ---------------------------------------------------------------------------

def compute_quote(spec, zone, quantity_tons):
    qty = D(quantity_tons)
    base = D(spec["base_price_per_ton"])
    if qty <= 100:
        factor = Decimal("1.00")
    elif qty <= 1000:
        factor = Decimal("0.95")
    else:
        factor = Decimal("0.90")
    material = q(base * factor, 2)
    freight = q(D(zone["base_freight_per_ton"]), 2)
    subtotal = material + freight
    if spec["category"] == "RIPRAP":
        surcharge = Decimal("0.00")
    else:
        if subtotal < Decimal("20.00"):
            pct = Decimal("0.08")
        elif subtotal < Decimal("40.00"):
            pct = Decimal("0.12")
        else:
            pct = Decimal("0.15")
        surcharge = q(subtotal * pct, 2)
    unit = material + freight + surcharge
    total = q(unit * qty, 2)
    return {
        "quoted_material_per_ton": to_float(material),
        "quoted_freight_per_ton": to_float(freight),
        "quoted_surcharge_per_ton": to_float(surcharge),
        "quoted_unit_delivered_per_ton": to_float(unit),
        "quoted_total_usd": to_float(total),
    }


# ---------------------------------------------------------------------------
# Royalty helpers
# ---------------------------------------------------------------------------

def active_agreement_covering(site_id, on_date):
    """ACTIVE agreement with effective_from <= on_date and (effective_to null or > on_date)."""
    for ag in db.royalty_agreements.values():
        if ag["site_id"] != site_id or ag["status"] != "ACTIVE":
            continue
        if parse_iso_date(ag["effective_from"]) > on_date:
            continue
        if ag.get("effective_to") is not None and parse_iso_date(ag["effective_to"]) <= on_date:
            continue
        return ag
    return None


def ticket_date(ticket):
    """Date portion of the ticket's completed_at logical timestamp."""
    return parse_iso_datetime(ticket["completed_at"]).date()
