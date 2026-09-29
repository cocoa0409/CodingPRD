"""Resource serialisation.  Computed fields are evaluated fresh on every read."""

import calc
import store


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def branch(rec):
    out = _common(rec)
    out.update({
        "code": rec["code"],
        "name": rec["name"],
        "region": rec["region"],
        "yard_capacity": rec["yard_capacity"],
        "peak_season_start_date": rec["peak_season_start_date"],
        "peak_season_end_date": rec["peak_season_end_date"],
        "lease_reserve_pct": rec["lease_reserve_pct"],
        "on_hand_count": calc.branch_on_hand_count(rec["id"]),
        "serviceable_available_count": calc.branch_serviceable_available_count(rec["id"]),
    })
    return out


def trailer_type(rec):
    out = _common(rec)
    out.update({
        "code": rec["code"],
        "description": rec["description"],
        "base_daily_rate_cents": rec["base_daily_rate_cents"],
        "base_monthly_rate_cents": rec["base_monthly_rate_cents"],
        "residual_floor_cents": rec["residual_floor_cents"],
        "dot_inspection_interval_days": rec["dot_inspection_interval_days"],
        "pm_interval_miles": rec["pm_interval_miles"],
        "required_physical_damage_limit_cents": rec["required_physical_damage_limit_cents"],
    })
    return out


def trailer(rec):
    out = _common(rec)
    out.update({
        "unit_number": rec["unit_number"],
        "trailer_type_id": rec["trailer_type_id"],
        "home_branch_id": rec["home_branch_id"],
        "current_branch_id": rec["current_branch_id"],
        "availability_status": rec["availability_status"],
        "service_status": calc.trailer_service_status(rec),
        "hub_miles": rec["hub_miles"],
        "last_pm_hub_miles": rec["last_pm_hub_miles"],
        "last_dot_inspection_date": rec["last_dot_inspection_date"],
        "dot_expires_on": rec["dot_expires_on"],
        "last_dot_passed": rec["last_dot_passed"],
        "last_damage_repair_at": rec.get("last_damage_repair_at"),
        "damage_points": calc.trailer_damage_points(rec),
        "acquisition_cost_cents": rec["acquisition_cost_cents"],
        "in_service_date": rec["in_service_date"],
        "net_book_value_cents": calc.trailer_net_book_value(rec),
        "retired_reason": rec.get("retired_reason"),
    })
    return out


def customer(rec):
    out = _common(rec)
    out.update({
        "legal_name": rec["legal_name"],
        "dot_number": rec["dot_number"],
        "credit_tier": rec["credit_tier"],
        "credit_limit_cents": rec["credit_limit_cents"],
        "outstanding_chargeback_cents": calc.outstanding_chargeback_cents(rec["id"]),
    })
    return out


def certificate_status(rec):
    """Lazy ACTIVE -> EXPIRED evaluation against the logical clock."""
    if rec["status"] == "ACTIVE":
        expiry = store.parse_date(rec["expiry_date"])
        if expiry is not None and store.clock_date() > expiry:
            return "EXPIRED"
    return rec["status"]


def certificate(rec):
    out = _common(rec)
    out.update({
        "customer_id": rec["customer_id"],
        "carrier_name": rec["carrier_name"],
        "policy_number": rec["policy_number"],
        "physical_damage_limit_cents": rec["physical_damage_limit_cents"],
        "liability_limit_cents": rec["liability_limit_cents"],
        "effective_date": rec["effective_date"],
        "expiry_date": rec["expiry_date"],
        "status": certificate_status(rec),
        "revoked_reason": rec.get("revoked_reason"),
    })
    return out


def rate_card(rec):
    out = _common(rec)
    out.update({
        "branch_id": rec["branch_id"],
        "trailer_type_id": rec["trailer_type_id"],
        "product": rec["product"],
        "daily_rate_cents": rec["daily_rate_cents"],
        "monthly_rate_cents": rec["monthly_rate_cents"],
        "peak_uplift_pct": rec["peak_uplift_pct"],
        "mileage_included_per_month": rec["mileage_included_per_month"],
        "excess_mileage_rate_cents_per_mile": rec["excess_mileage_rate_cents_per_mile"],
        "effective_date": rec["effective_date"],
        "status": rec["status"],
    })
    return out


def allocated_unit_count(agreement_id):
    n = 0
    for u in store.agreement_units.values():
        if u["agreement_id"] == agreement_id and u["status"] in ("ALLOCATED", "OUT", "RETURNED", "SETTLED"):
            n += 1
    return n


def agreement(rec):
    out = _common(rec)
    out.update({
        "customer_id": rec["customer_id"],
        "branch_id": rec["branch_id"],
        "product": rec["product"],
        "trailer_type_id": rec["trailer_type_id"],
        "unit_count": rec["unit_count"],
        "start_date": rec["start_date"],
        "end_date": rec["end_date"],
        "term_months": rec.get("term_months"),
        "status": rec["status"],
        "rate_card_id": rec.get("rate_card_id"),
        "insurance_certificate_id": rec.get("insurance_certificate_id"),
        "underwriting_risk_score": rec.get("underwriting_risk_score"),
        "quoted_total_cents": rec.get("quoted_total_cents"),
        "final_total_cents": rec.get("final_total_cents"),
        "allocated_unit_count": allocated_unit_count(rec["id"]),
        "purchase_option_status": rec["purchase_option_status"],
        "purchase_option_price_cents": rec.get("purchase_option_price_cents"),
        "cancel_reason": rec.get("cancel_reason"),
    })
    return out


def agreement_unit(rec):
    out = _common(rec)
    out.update({
        "agreement_id": rec["agreement_id"],
        "trailer_id": rec["trailer_id"],
        "return_branch_id": rec.get("return_branch_id"),
        "status": rec["status"],
        "planned_start_date": rec["planned_start_date"],
        "planned_end_date": rec["planned_end_date"],
        "checkout_date": rec.get("checkout_date"),
        "return_date": rec.get("return_date"),
        "checkout_hub_miles": rec.get("checkout_hub_miles"),
        "return_hub_miles": rec.get("return_hub_miles"),
        "peak_days": rec.get("peak_days"),
        "excess_miles": rec.get("excess_miles"),
        "drop_charge_cents": rec.get("drop_charge_cents"),
        "line_charge_cents": rec.get("line_charge_cents"),
    })
    return out


def maintenance_event(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "trailer_id": rec["trailer_id"],
        "event_type": rec["event_type"],
        "performed_on": rec["performed_on"],
        "hub_miles_at_event": rec["hub_miles_at_event"],
        "cost_cents": rec["cost_cents"],
        "passed": rec.get("passed"),
        "inspector_user_id": rec["inspector_user_id"],
    }


def damage_assessment(rec):
    out = _common(rec)
    out.update({
        "agreement_unit_id": rec["agreement_unit_id"],
        "trailer_id": rec["trailer_id"],
        "supersedes_assessment_id": rec.get("supersedes_assessment_id"),
        "assessor_user_id": rec["assessor_user_id"],
        "line_items": rec["line_items"],
        "status": rec["status"],
        "assessed_amount_cents": rec.get("assessed_amount_cents"),
        "insured_portion_cents": rec.get("insured_portion_cents"),
        "customer_liable_cents": rec.get("customer_liable_cents"),
        "admin_fee_cents": rec.get("admin_fee_cents"),
        "damage_points": rec.get("damage_points"),
    })
    return out


def chargeback(rec):
    out = _common(rec)
    out.update({
        "damage_assessment_id": rec["damage_assessment_id"],
        "customer_id": rec["customer_id"],
        "amount_cents": rec["amount_cents"],
        "status": rec["status"],
        "approver_user_id": rec.get("approver_user_id"),
        "dispute_reason": rec.get("dispute_reason"),
        "waiver_reason": rec.get("waiver_reason"),
        "paid_amount_cents": rec.get("paid_amount_cents"),
    })
    return out


def relocation_order(rec):
    out = _common(rec)
    out.update({
        "trailer_id": rec["trailer_id"],
        "origin_branch_id": rec["origin_branch_id"],
        "destination_branch_id": rec["destination_branch_id"],
        "status": rec["status"],
        "planned_depart_date": rec["planned_depart_date"],
        "planned_arrive_date": rec["planned_arrive_date"],
        "planned_miles": rec["planned_miles"],
        "actual_miles": rec.get("actual_miles"),
        "deadhead_miles": rec.get("deadhead_miles"),
        "actual_arrive_date": rec.get("actual_arrive_date"),
        "estimated_cost_cents": rec.get("estimated_cost_cents"),
        "actual_cost_cents": rec.get("actual_cost_cents"),
        "reject_reason": rec.get("reject_reason"),
        "cancel_reason": rec.get("cancel_reason"),
    })
    return out
