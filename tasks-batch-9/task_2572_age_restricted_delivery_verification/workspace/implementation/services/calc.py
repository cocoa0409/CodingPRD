"""Calculations 1, 5, 7 and 8 plus the order-time compliance battery.

  * order_restricted_unit_exposure   (double rounding: per line, then on the sum)
  * identity_prevalidation_confidence
  * delivery_permissibility_evaluation
  * customer_window_units_consumed
"""
from datetime import timedelta
from decimal import Decimal

from db import (
    IDENTITY_DOB_MISMATCH_PENALTY,
    IDENTITY_MATCH_BAND,
    IDENTITY_PARTIAL_BAND,
    IDENTITY_SIGNAL_ORDER,
    IDENTITY_SIGNAL_WEIGHTS,
    db,
    now,
    sort_key,
)
from util import dec, in_window, local_date, local_minute, parse_date, parse_dt, rhu, completed_years

ZERO2 = Decimal("0.00")


# ---------------------------------------------------------------------------
# helpers over the store
# ---------------------------------------------------------------------------
def order_lines_of(order):
    rows = [l for l in db.order_lines.values() if l["order_id"] == order["id"]]
    rows.sort(key=sort_key)
    return rows


def compute_restriction_types(order):
    """Distinct non-NONE restriction classes over INCLUDED lines, sorted ascending."""
    found = set()
    for line in order_lines_of(order):
        if line["line_state"] != "INCLUDED":
            continue
        product = db.products.get(line["product_id"])
        if product is None:
            continue
        if product["restriction_type"] != "NONE":
            found.add(product["restriction_type"])
    return sorted(found)


def resolve_policy(jurisdiction_id, restriction_type, on_date):
    """The single policy whose closed-closed effective period contains `on_date`."""
    for policy in db.policies.values():
        if policy["jurisdiction_id"] != jurisdiction_id:
            continue
        if policy["restriction_type"] != restriction_type:
            continue
        start = parse_date(policy["effective_from"])
        end = parse_date(policy["effective_to"])
        if start <= on_date <= end:
            return policy
    return None


def resolve_order_policies(order, instant):
    """Returns (ordered [(rtype, policy)], first_unresolved_rtype_or_None)."""
    jurisdiction = db.jurisdictions.get(order["delivery_jurisdiction_id"])
    offset = jurisdiction["utc_offset_minutes"] if jurisdiction else 0
    on_date = local_date(instant, offset)
    resolved = []
    for rtype in order["restriction_types"]:
        policy = resolve_policy(order["delivery_jurisdiction_id"], rtype, on_date)
        if policy is None:
            return resolved, rtype
        resolved.append((rtype, policy))
    return resolved, None


def resolve_types_policies(order, rtypes, instant):
    """Same as resolve_order_policies but over an explicit restriction-class list."""
    jurisdiction = db.jurisdictions.get(order["delivery_jurisdiction_id"])
    offset = jurisdiction["utc_offset_minutes"] if jurisdiction else 0
    on_date = local_date(instant, offset)
    resolved = []
    for rtype in rtypes:
        policy = resolve_policy(order["delivery_jurisdiction_id"], rtype, on_date)
        if policy is None:
            return resolved, rtype
        resolved.append((rtype, policy))
    return resolved, None


def effective_policies_for_attempt(order, instant):
    """Policies governing an in-flight attempt; falls back to the ids pinned at submit."""
    resolved, missing = resolve_order_policies(order, instant)
    if missing is None:
        return [p for _, p in resolved]
    have = set(rt for rt, _ in resolved)
    out = [p for _, p in resolved]
    for policy_id in order["applied_policy_ids"]:
        policy = db.policies.get(policy_id)
        if policy is not None and policy["restriction_type"] not in have:
            out.append(policy)
    return out


# ---------------------------------------------------------------------------
# Calculation 1 -- order_restricted_unit_exposure
# ---------------------------------------------------------------------------
def compute_exposure(order, type_policies, use_snapshot, included_states=("INCLUDED",)):
    """Rounds twice: once per line, once on the sum of already-rounded line values.

    `use_snapshot` selects the PROVISIONAL_AT_SUBMIT variant (units_per_item_snapshot);
    False selects FINAL_AT_HANDOVER, which reads the live product figure.
    """
    lines = order_lines_of(order)
    per_type = []
    line_units = {}
    total = Decimal("0")
    for rtype, policy in type_policies:
        subtotal = Decimal("0")
        scale = dec(policy["unit_scale_factor"])
        for line in lines:
            product = db.products.get(line["product_id"])
            if product is None or product["restriction_type"] != rtype:
                continue
            if line["line_state"] not in included_states:
                continue
            units = line["units_per_item_snapshot"] if use_snapshot else product["restricted_units_per_item"]
            raw = Decimal(line["quantity"]) * dec(units) * scale
            rounded = rhu(raw, 2)
            line_units[line["id"]] = rounded
            subtotal += rounded
        class_total = rhu(subtotal, 2)
        per_type.append({"restriction_type": rtype, "policy": policy, "exposure": class_total})
        total += class_total
    return rhu(total, 2), per_type, line_units


# ---------------------------------------------------------------------------
# Calculation 8 -- customer_window_units_consumed
# ---------------------------------------------------------------------------
def window_units_consumed(order, rtype, policy):
    anchor = parse_dt(order["scheduled_delivery_at"])
    if anchor is None:
        return ZERO2
    window_start = anchor - timedelta(days=policy["rolling_window_days"])
    rows = []
    for other in db.orders.values():
        if other["id"] == order["id"]:
            continue
        if other["customer_id"] != order["customer_id"]:
            continue
        if other["fulfillment_state"] != "DELIVERED":
            continue
        if not other.get("delivered_at"):
            continue
        if rtype not in other["restriction_types"]:
            continue
        delivered = parse_dt(other["delivered_at"])
        if delivered is None:
            continue
        if delivered >= window_start and delivered < anchor:
            rows.append((delivered, other))
    rows.sort(key=lambda pair: (pair[0], pair[1]["created_at"], pair[1]["_seq"]))
    total = Decimal("0")
    for _, other in rows:
        value = other.get("final_restricted_units")
        if value is not None:
            total += dec(value)
    return rhu(total, 2)


# ---------------------------------------------------------------------------
# Calculation 5 -- identity_prevalidation_confidence
# ---------------------------------------------------------------------------
def identity_confidence(signals, provided_dob, source_dob):
    matched = {}
    for signal in signals:
        if signal["matched"]:
            matched[signal["source_type"]] = True
    total = Decimal("0")
    for key in IDENTITY_SIGNAL_ORDER:
        if matched.get(key):
            total += IDENTITY_SIGNAL_WEIGHTS[key]
    confidence = rhu(total, 4)
    if provided_dob != source_dob and matched.get("GOVERNMENT_ID_DB"):
        confidence = rhu(confidence - IDENTITY_DOB_MISMATCH_PENALTY, 4)
        if confidence < 0:
            confidence = Decimal("0.0000")
    if confidence >= IDENTITY_MATCH_BAND:
        result = "MATCH"
        verified_dob = source_dob
    elif confidence >= IDENTITY_PARTIAL_BAND:
        result = "PARTIAL"
        verified_dob = provided_dob
    else:
        result = "NO_MATCH"
        verified_dob = None
    return confidence, result, verified_dob


def newest_valid_identity_check(customer_id):
    rows = [c for c in db.identity_checks.values()
            if c["customer_id"] == customer_id and c["status"] == "VALID"]
    if not rows:
        return None
    rows.sort(key=sort_key)
    return rows[-1]


# ---------------------------------------------------------------------------
# Calculation 7 -- delivery_permissibility_evaluation
# ---------------------------------------------------------------------------
def permissibility_error(jurisdiction, type_policies):
    """PROHIBITED, then dry status, then permit posture -- per restriction class."""
    for rtype, policy in type_policies:
        if policy["permissibility"] == "PROHIBITED":
            return "ERR_DELIVERY_PROHIBITED_IN_JURISDICTION"
        if rtype == "ALCOHOL" and jurisdiction["dry_status"] == "DRY":
            return "ERR_DRY_JURISDICTION_PROHIBITED"
        if jurisdiction["dry_status"] == "DAMP" and policy["permissibility"] != "PERMIT_REQUIRED":
            return "ERR_PERMIT_REQUIRED"
    return None


def window_error(jurisdiction, type_policies, instant):
    minute = local_minute(instant, jurisdiction["utc_offset_minutes"])
    for _, policy in type_policies:
        if not in_window(minute, policy["delivery_window_start_minute"], policy["delivery_window_end_minute"]):
            return "ERR_OUTSIDE_RESTRICTED_HOURS"
    return None
