"""Entity projections.  Always run against the live row, after any mutation."""

from . import clock
from .store import DB


def _common(row, out):
    out["id"] = row["id"]
    out["created_at"] = row["created_at"]
    if "version" in row:
        out["updated_at"] = row["updated_at"]
        out["version"] = row["version"]
    return out


# ---------------------------------------------------------------- derived ----

def credit_balance_cents(member_id):
    """Sum of remaining_cents over ACTIVE / PARTIALLY_CONSUMED grants whose
    expires_at the clock has not yet reached."""
    now = clock.now()
    total = 0
    for grant in DB.credit_grants.values():
        if grant["member_id"] != member_id:
            continue
        if grant["status"] not in ("ACTIVE", "PARTIALLY_CONSUMED"):
            continue
        expires = clock.parse(grant["expires_at"])
        if expires is not None and now >= expires:
            continue
        total += grant["remaining_cents"]
    return total


def is_coordinator(member_id):
    for dp in DB.drop_points.values():
        if dp.get("coordinator_member_id") == member_id:
            return True
    return False


def exception_state(cycle):
    """NOT_STARTED before received_at, OPEN inside the half-open window,
    CLOSED at or after exception_deadline_at."""
    if not cycle.get("received_at"):
        return "NOT_STARTED"
    now = clock.now()
    start = clock.parse(cycle["received_at"])
    end = clock.parse(cycle["exception_deadline_at"])
    if now < start:
        return "NOT_STARTED"
    if now < end:
        return "OPEN"
    return "CLOSED"


# ------------------------------------------------------------ projections ----

def member(row):
    out = {
        "email": row["email"],
        "full_name": row["full_name"],
        "tier": row["tier"],
        "tier_rank": row["tier_rank"],
        "discount_pct": row["discount_pct"],
        "status": row["status"],
        "home_drop_point_id": row["home_drop_point_id"],
        "dues_paid_through": row["dues_paid_through"],
        "dues_grace_until": row["dues_grace_until"],
        "lifetime_dues_paid_cents": row["lifetime_dues_paid_cents"],
        "credit_balance_cents": credit_balance_cents(row["id"]),
        "is_coordinator": is_coordinator(row["id"]),
    }
    return _common(row, out)


def route(row):
    out = {
        "code": row["code"],
        "name": row["name"],
        "reefer_slots": row["reefer_slots"],
        "route_minimum_cents": row["route_minimum_cents"],
        "max_pallets": row["max_pallets"],
        "cold_capable": row["reefer_slots"] > 0,
    }
    return _common(row, out)


def drop_point(row):
    out = {
        "route_id": row["route_id"],
        "name": row["name"],
        "coordinator_member_id": row["coordinator_member_id"],
        "drop_minimum_cents": row["drop_minimum_cents"],
    }
    return _common(row, out)


def item(row):
    out = {
        "sku": row["sku"],
        "name": row["name"],
        "temp_class": row["temp_class"],
        "case_pack_units": row["case_pack_units"],
        "unit_weight_grams": row["unit_weight_grams"],
        "unit_cube_cm3": row["unit_cube_cm3"],
        "split_allowed": row["split_allowed"],
        "remainder_policy": row["remainder_policy"],
        "status": row["status"],
    }
    return _common(row, out)


def price_version(row):
    out = {
        "item_id": row["item_id"],
        "effective_from": row["effective_from"],
        "case_price_cents": row["case_price_cents"],
        "split_unit_base_cents": row["split_unit_base_cents"],
    }
    return _common(row, out)


def cycle(row):
    out = {
        "code": row["code"],
        "opens_at": row["opens_at"],
        "cutoff_at": row["cutoff_at"],
        "status": row["status"],
        "locked_at": row["locked_at"],
        "received_at": row["received_at"],
        "exception_deadline_at": row["exception_deadline_at"],
        "exception_state": exception_state(row),
    }
    return _common(row, out)


def route_run(row):
    out = {
        "cycle_id": row["cycle_id"],
        "route_id": row["route_id"],
        "status": row["status"],
        "aggregated_subtotal_cents": row["aggregated_subtotal_cents"],
        "supplier_invoice_cents": row["supplier_invoice_cents"],
        "freight_cents": row["freight_cents"],
        "invoice_recorded_by_user_id": row["invoice_recorded_by_user_id"],
        "cold_pallet_count": row["cold_pallet_count"],
        "dry_pallet_count": row["dry_pallet_count"],
        "reefer_slots_used": row["reefer_slots_used"],
        "reefer_surcharge_cents": row["reefer_surcharge_cents"],
        "received_subtotal_cents": row["received_subtotal_cents"],
    }
    return _common(row, out)


def drop_run(row):
    out = {
        "cycle_id": row["cycle_id"],
        "drop_point_id": row["drop_point_id"],
        "route_run_id": row["route_run_id"],
        "coordinator_member_id": row["coordinator_member_id"],
        "merged_into_drop_run_id": row["merged_into_drop_run_id"],
        "status": row["status"],
        "subtotal_cents": row["subtotal_cents"],
        "discounted_subtotal_cents": row["discounted_subtotal_cents"],
        "received_subtotal_cents": row["received_subtotal_cents"],
        "verified_volunteer_hours": row["verified_volunteer_hours"],
        "volunteer_obligation_met": row["volunteer_obligation_met"],
        "freight_alloc_cents": row["freight_alloc_cents"],
        "reefer_alloc_cents": row["reefer_alloc_cents"],
        "rollforward_count": row["rollforward_count"],
    }
    return _common(row, out)


def member_order(row):
    out = {
        "member_id": row["member_id"],
        "drop_run_id": row["drop_run_id"],
        "status": row["status"],
        "payment_status": row["payment_status"],
        "gross_cents": row["gross_cents"],
        "split_fee_cents": row["split_fee_cents"],
        "tier_discount_cents": row["tier_discount_cents"],
        "freight_alloc_cents": row["freight_alloc_cents"],
        "reefer_alloc_cents": row["reefer_alloc_cents"],
        "pre_credit_total_cents": row["pre_credit_total_cents"],
        "credit_applied_cents": row["credit_applied_cents"],
        "actual_total_cents": row["actual_total_cents"],
        "estimated_total_cents": row["estimated_total_cents"],
        "authorized_amount_cents": row["authorized_amount_cents"],
        "captured_cents": row["captured_cents"],
        "refunded_cents": row["refunded_cents"],
    }
    return _common(row, out)


def order_line(row):
    out = {
        "member_order_id": row["member_order_id"],
        "item_id": row["item_id"],
        "qty_units": row["qty_units"],
        "rollover_opt_in": row["rollover_opt_in"],
        "substitution_pref": row["substitution_pref"],
        "rolled_from_order_line_id": row["rolled_from_order_line_id"],
        "status": row["status"],
        "bound_case_price_cents": row["bound_case_price_cents"],
        "unit_price_cents": row["unit_price_cents"],
        "is_split_unit": row["is_split_unit"],
        "split_fee_per_unit_cents": row["split_fee_per_unit_cents"],
        "confirmed_units": row["confirmed_units"],
        "allocated_units": row["allocated_units"],
        "short_units": row["short_units"],
        "allocation_remainder_rank": row["allocation_remainder_rank"],
        "line_gross_cents": row["line_gross_cents"],
    }
    return _common(row, out)


def case_aggregate(row):
    out = {
        "route_run_id": row["route_run_id"],
        "item_id": row["item_id"],
        "overage_order_line_id": row["overage_order_line_id"],
        "requested_units": row["requested_units"],
        "cases_ordered": row["cases_ordered"],
        "covered_units": row["covered_units"],
        "remainder_units": row["remainder_units"],
        "overage_units": row["overage_units"],
        "dropped_units": row["dropped_units"],
        "policy_applied": row["policy_applied"],
        "case_price_cents": row["case_price_cents"],
        "units_received": row["units_received"],
    }
    return _common(row, out)


def receipt_line(row):
    out = {
        "route_run_id": row["route_run_id"],
        "case_aggregate_id": row["case_aggregate_id"],
        "substitute_item_id": row["substitute_item_id"],
        "cases_received": row["cases_received"],
        "substitute_case_price_cents": row["substitute_case_price_cents"],
        "units_received": row["units_received"],
        "recorded_by_user_id": row["recorded_by_user_id"],
    }
    return _common(row, out)


def substitution_offer(row):
    out = {
        "order_line_id": row["order_line_id"],
        "receipt_line_id": row["receipt_line_id"],
        "substitute_item_id": row["substitute_item_id"],
        "offered_units": row["offered_units"],
        "original_unit_price_cents": row["original_unit_price_cents"],
        "offered_unit_price_cents": row["offered_unit_price_cents"],
        "within_tolerance": row["within_tolerance"],
        "respond_by": row["respond_by"],
        "status": row["status"],
    }
    return _common(row, out)


def pallet(row):
    out = {
        "route_run_id": row["route_run_id"],
        "temp_class": row["temp_class"],
        "sequence_index": row["sequence_index"],
        "weight_grams": row["weight_grams"],
        "cube_cm3": row["cube_cm3"],
        "unit_count": row["unit_count"],
        "requires_reefer": row["requires_reefer"],
        "status": row["status"],
    }
    return _common(row, out)


def payment(row):
    out = {
        "member_order_id": row["member_order_id"],
        "kind": row["kind"],
        "method": row["method"],
        "amount_cents": row["amount_cents"],
        "status": row["status"],
    }
    return _common(row, out)


def drop_reconciliation(row):
    out = {
        "drop_run_id": row["drop_run_id"],
        "member_charges_cents": row["member_charges_cents"],
        "supplier_cost_cents": row["supplier_cost_cents"],
        "freight_alloc_cents": row["freight_alloc_cents"],
        "reefer_alloc_cents": row["reefer_alloc_cents"],
        "commission_cents": row["commission_cents"],
        "club_margin_cents": row["club_margin_cents"],
        "variance_cents": row["variance_cents"],
        "prepared_by_user_id": row["prepared_by_user_id"],
        "posted_by_user_id": row["posted_by_user_id"],
        "posted_at": row["posted_at"],
        "status": row["status"],
    }
    return _common(row, out)


def commission_accrual(row):
    out = {
        "drop_run_id": row["drop_run_id"],
        "coordinator_member_id": row["coordinator_member_id"],
        "base_subtotal_cents": row["base_subtotal_cents"],
        "rate_applied": row["rate_applied"],
        "volunteer_multiplier_applied": row["volunteer_multiplier_applied"],
        "accrued_cents": row["accrued_cents"],
        "clawback_cents": row["clawback_cents"],
        "net_cents": row["net_cents"],
        "payout_mode": row["payout_mode"],
        "payout_value_cents": row["payout_value_cents"],
        "status": row["status"],
    }
    return _common(row, out)


def volunteer_shift(row):
    out = {
        "drop_run_id": row["drop_run_id"],
        "member_id": row["member_id"],
        "credit_grant_id": row["credit_grant_id"],
        "hours": row["hours"],
        "status": row["status"],
        "verified_by_user_id": row["verified_by_user_id"],
    }
    return _common(row, out)


def credit_grant(row):
    out = {
        "member_id": row["member_id"],
        "source_member_order_id": row["source_member_order_id"],
        "source": row["source"],
        "amount_cents": row["amount_cents"],
        "remaining_cents": row["remaining_cents"],
        "expires_at": row["expires_at"],
        "status": row["status"],
    }
    return _common(row, out)


BY_KIND = {
    "Member": member,
    "Route": route,
    "DropPoint": drop_point,
    "Item": item,
    "PriceVersion": price_version,
    "Cycle": cycle,
    "RouteRun": route_run,
    "DropRun": drop_run,
    "MemberOrder": member_order,
    "OrderLine": order_line,
    "CaseAggregate": case_aggregate,
    "ReceiptLine": receipt_line,
    "SubstitutionOffer": substitution_offer,
    "Pallet": pallet,
    "Payment": payment,
    "DropReconciliation": drop_reconciliation,
    "CommissionAccrual": commission_accrual,
    "VolunteerShift": volunteer_shift,
    "CreditGrant": credit_grant,
}


def project(row):
    return BY_KIND[row["_kind"]](row)


def project_all(rows):
    return [project(r) for r in rows]
