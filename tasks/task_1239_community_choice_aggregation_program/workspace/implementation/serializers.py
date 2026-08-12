"""Per-entity serializers. Only scaffold-declared fields are exposed."""

from util import num_out


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def _append_only(rec):
    return {"id": rec["id"], "created_at": rec["created_at"]}


def ser_authority(a):
    out = _common(a)
    out.update({
        "display_name": a["display_name"],
        "utility_territory_code": a["utility_territory_code"],
        "er_balancing_authority": a["er_balancing_authority"],
        "rate_setting_policy": a["rate_setting_policy"],
        "discount_floor_bps": a["discount_floor_bps"],
        "rps_target_pct": num_out(a["rps_target_pct"]),
        "bad_debt_trueup_cap_pct": num_out(a["bad_debt_trueup_cap_pct"]),
        "climate_reserve_balance_cents": a["climate_reserve_balance_cents"],
        "status": a["status"],
    })
    return out


def ser_account(r):
    out = _common(r)
    out.update({
        "utility_account_number": r["utility_account_number"],
        "service_class": r["service_class"],
        "annual_kwh_estimate": r["annual_kwh_estimate"],
        "annual_peak_kw": num_out(r["annual_peak_kw"]),
        "da_eligible": r["da_eligible"],
        "enrollment_state": r["enrollment_state"],
        "product_election": r["product_election"],
        "current_enrollment_notice_id": r["current_enrollment_notice_id"],
        "vintage_year": r["vintage_year"],
        "cumulative_billed_cents": r["cumulative_billed_cents"],
        "cumulative_remitted_cents": r["cumulative_remitted_cents"],
        "uncollectible_flag": r["uncollectible_flag"],
    })
    return out


def ser_notice(r):
    out = _common(r)
    out.update({
        "wave_label": r["wave_label"],
        "notice_mailed_on": r["notice_mailed_on"],
        "opt_out_deadline": r["opt_out_deadline"],
        "enrollment_effective_on": r["enrollment_effective_on"],
        "status": r["status"],
        "target_service_classes": list(r["target_service_classes"]),
        "account_count_noticed": r["account_count_noticed"],
        "account_count_opted_out": r["account_count_opted_out"],
        "account_count_enrolled": r["account_count_enrolled"],
    })
    return out


def ser_opt_out(r):
    out = _append_only(r)
    out.update({
        "service_account_id": r["service_account_id"],
        "enrollment_notice_id": r["enrollment_notice_id"],
        "election_type": r["election_type"],
        "received_at": r["received_at"],
        "channel": r["channel"],
        "reversal_of_request_id": r["reversal_of_request_id"],
    })
    return out


def ser_product(r):
    out = _common(r)
    out.update({
        "product_code": r["product_code"],
        "election_key": r["election_key"],
        "renewable_pct": num_out(r["renewable_pct"]),
        "status": r["status"],
        "is_default": r["is_default"],
    })
    return out


def ser_schedule(r):
    out = _common(r)
    out.update({
        "product_id": r["product_id"],
        "period_start": r["period_start"],
        "period_end": r["period_end"],
        "energy_rate_cents_per_kwh": num_out(r["energy_rate_cents_per_kwh"]),
        "pcia_rate_cents_per_kwh": num_out(r["pcia_rate_cents_per_kwh"]),
        "incumbent_benchmark_rate_cents_per_kwh": num_out(r["incumbent_benchmark_rate_cents_per_kwh"]),
        "comparison_margin_bps": r["comparison_margin_bps"],
        "status": r["status"],
        "adopted_by": r["adopted_by"],
        "proposed_by": r["proposed_by"],
    })
    return out


def ser_contract(r):
    out = _common(r)
    out.update({
        "counterparty": r["counterparty"],
        "contract_type": r["contract_type"],
        "delivery_start": r["delivery_start"],
        "delivery_end": r["delivery_end"],
        "capacity_mw": num_out(r["capacity_mw"]),
        "total_mwh": num_out(r["total_mwh"]),
        "price_dollars_per_mwh": num_out(r["price_dollars_per_mwh"]),
        "rps_eligible_pct": num_out(r["rps_eligible_pct"]),
        "vintage_year": r["vintage_year"],
        "status": r["status"],
        "termination_fee_cents": r["termination_fee_cents"],
    })
    return out


def ser_forecast(r):
    out = _append_only(r)
    out.update({
        "snapshot_label": r["snapshot_label"],
        "forecast_variant": r["forecast_variant"],
        "as_of": r["as_of"],
        "period_year": r["period_year"],
        "total_energy_mwh": num_out(r["total_energy_mwh"]),
        "coincident_peak_mw": num_out(r["coincident_peak_mw"]),
        "ra_requirement_mw": num_out(r["ra_requirement_mw"]),
        "coverage_gap_mwh": num_out(r["coverage_gap_mwh"]),
    })
    return out


def ser_extract(r):
    out = _common(r)
    out.update({
        "billing_month": r["billing_month"],
        "status": r["status"],
        "submitted_on": r["submitted_on"],
        "line_count": r["line_count"],
        "total_billed_cents": r["total_billed_cents"],
        "total_pcia_collected_cents": r["total_pcia_collected_cents"],
    })
    return out


def ser_line(r):
    out = _append_only(r)
    out.update({
        "billing_extract_id": r["billing_extract_id"],
        "service_account_id": r["service_account_id"],
        "usage_kwh": r["usage_kwh"],
        "generation_charge_cents": r["generation_charge_cents"],
        "pcia_charge_cents": r["pcia_charge_cents"],
        "product_election_at_billing": r["product_election_at_billing"],
    })
    return out


def ser_remittance(r):
    out = _common(r)
    out.update({
        "remittance_period": r["remittance_period"],
        "gross_remittance_cents": r["gross_remittance_cents"],
        "utility_fee_bps": r["utility_fee_bps"],
        "net_remittance_cents": r["net_remittance_cents"],
        "applied_cents": r["applied_cents"],
        "status": r["status"],
    })
    return out


def ser_pool(r):
    out = _common(r)
    out.update({
        "pool_period": r["pool_period"],
        "status": r["status"],
        "written_off_cents": r["written_off_cents"],
        "billed_generation_cents": r["billed_generation_cents"],
        "cca_share_cents": r["cca_share_cents"],
        "utility_share_cents": r["utility_share_cents"],
        "reserve_draw_cents": r["reserve_draw_cents"],
        "expensed_cents": r["expensed_cents"],
    })
    return out


def ser_filing(r):
    out = _common(r)
    out.update({
        "filing_type": r["filing_type"],
        "compliance_year": r["compliance_year"],
        "rps_actual_pct": num_out(r["rps_actual_pct"]) if r["rps_actual_pct"] is not None else None,
        "rps_shortfall_mwh": r["rps_shortfall_mwh"],
        "status": r["status"],
        "prepared_by": r["prepared_by"],
        "reviewed_by": r["reviewed_by"],
        "revision_count": r["revision_count"],
    })
    return out


def ser_rec(r):
    out = _append_only(r)
    out.update({
        "compliance_filing_id": r["compliance_filing_id"],
        "supply_contract_id": r["supply_contract_id"],
        "retired_mwh": num_out(r["retired_mwh"]),
        "retirement_serial": r["retirement_serial"],
        "retired_on": r["retired_on"],
    })
    return out
