"""The order-time compliance battery.

One non-mutating evaluation shared by `POST /orders/{id}/submit` and
`GET /orders/{id}/compliance-evaluation`. Cross-tier ordering follows the
validation-precedence ladder of PRD section 2.7:

    45 policy resolution
    50 jurisdiction permissibility  (per class: prohibition, dry, permit)
    56 purchaser eligibility        (attestation, block, preverification, age)
    60 temporal admissibility       (scheduled instant, then restricted hours)
    70 quantity ceilings            (per order, then rolling window)
"""
from decimal import Decimal

from db import db, now
from services.calc import (
    ZERO2,
    compute_exposure,
    compute_restriction_types,
    newest_valid_identity_check,
    permissibility_error,
    resolve_types_policies,
    window_units_consumed,
)
from util import (
    completed_years,
    dec,
    in_window,
    local_date,
    local_minute,
    parse_date,
    parse_dt,
    rhu,
)


def evaluate_order(order):
    """Replay the battery without mutating anything. Returns a fact bundle."""
    customer = db.customers.get(order["customer_id"])
    jurisdiction = db.jurisdictions.get(order["delivery_jurisdiction_id"])
    partner = db.partners.get(order["delivery_partner_id"])
    scheduled = parse_dt(order["scheduled_delivery_at"])
    offset = jurisdiction["utc_offset_minutes"]
    clock = now()

    rtypes = compute_restriction_types(order)
    check = newest_valid_identity_check(order["customer_id"])

    facts = {
        "restriction_types": rtypes,
        "applied_policy_ids": [],
        "type_policies": [],
        "missing_policy_type": None,
        "per_type": [],
        "line_units": {},
        "provisional_total": ZERO2,
        "window_total": ZERO2,
        "local_minute": local_minute(scheduled, offset),
        "in_window": True,
        "purchaser_age_years": None,
        "min_age_required": None,
        "identity_result": check["result"] if check else "NONE",
        "identity_check": check,
        "route": None,
        "error": None,
        "customer": customer,
        "jurisdiction": jurisdiction,
        "partner": partner,
    }

    # ---- Unrestricted shortcut: bypasses the whole battery (PRD 3.3) -------
    if not rtypes:
        facts["route"] = "AUTO_CLEARED"
        return facts

    # ---- resolve the governing policies ----------------------------------
    local_delivery_date = local_date(scheduled, offset)
    resolved, missing = resolve_types_policies(order, rtypes, scheduled)
    facts["type_policies"] = resolved
    facts["missing_policy_type"] = missing
    facts["applied_policy_ids"] = [p["id"] for _, p in resolved]
    if resolved:
        facts["min_age_required"] = max(p["min_age_years"] for _, p in resolved)

    # ---- exposure, rolling window, hours (computed for the read model) ----
    total, per_type, line_units = compute_exposure(order, resolved, use_snapshot=True)
    facts["provisional_total"] = total
    facts["per_type"] = per_type
    facts["line_units"] = line_units
    window_total = Decimal("0")
    for entry in per_type:
        consumed = window_units_consumed(order, entry["restriction_type"], entry["policy"])
        entry["window_units_consumed"] = consumed
        window_total += consumed
    facts["window_total"] = rhu(window_total, 2)
    facts["in_window"] = all(
        in_window(facts["local_minute"], p["delivery_window_start_minute"], p["delivery_window_end_minute"])
        for _, p in resolved
    ) if resolved else True

    # ---- purchaser age against the delivery-local calendar date ----------
    verified_dob = parse_date(check["verified_dob"]) if (check and check.get("verified_dob")) else None
    if verified_dob is not None:
        facts["purchaser_age_years"] = completed_years(verified_dob, local_delivery_date)

    # ---- objections, in strictly ascending tier order --------------------
    facts["error"] = _first_error(order, facts, clock)
    if facts["error"] is None:
        facts["route"] = _route(facts["identity_result"])
    return facts


def _route(identity_result):
    if identity_result == "MATCH":
        return "PREVERIFIED"
    if identity_result == "PARTIAL":
        return "PENDING_COMPLIANCE_REVIEW"
    if identity_result == "NO_MATCH":
        return "COMPLIANCE_BLOCKED"
    return None


def _first_error(order, facts, clock):
    # tier 11 (priority 45) -- policy resolution
    if facts["missing_policy_type"] is not None:
        return "ERR_NO_EFFECTIVE_POLICY"

    # tier 12 (priority 50) -- jurisdiction permissibility
    permissibility = permissibility_error(facts["jurisdiction"], facts["type_policies"])
    if permissibility is not None:
        return permissibility

    # tier 15 (priority 56) -- purchaser eligibility, fixed sub-order
    customer = facts["customer"]
    if customer["attestation_state"] != "ATTESTED":
        return "ERR_ATTESTATION_REQUIRED"
    blocked_until = parse_dt(customer["blocked_until"]) if customer.get("blocked_until") else None
    if blocked_until is not None and blocked_until > clock:
        return "ERR_CUSTOMER_DELIVERY_BLOCKED"
    if facts["identity_check"] is None:
        return "ERR_IDENTITY_PREVERIFICATION_REQUIRED"
    age = facts["purchaser_age_years"]
    if age is None or age < facts["min_age_required"]:
        return "ERR_PURCHASER_UNDERAGE"

    # tier 17 (priority 60) -- temporal admissibility
    scheduled = parse_dt(order["scheduled_delivery_at"])
    if scheduled <= clock:
        return "ERR_SCHEDULED_TIME_IN_PAST"
    if not facts["in_window"]:
        return "ERR_OUTSIDE_RESTRICTED_HOURS"

    # tier 20 (priority 70) -- quantity ceilings, per restriction class
    for entry in facts["per_type"]:
        policy = entry["policy"]
        exposure = entry["exposure"]
        if exposure > dec(policy["max_units_per_order"]):
            return "ERR_ORDER_UNIT_LIMIT_EXCEEDED"
        consumed = entry.get("window_units_consumed", ZERO2)
        if exposure + consumed > dec(policy["max_units_per_window"]):
            return "ERR_WINDOW_UNIT_LIMIT_EXCEEDED"
    return None
