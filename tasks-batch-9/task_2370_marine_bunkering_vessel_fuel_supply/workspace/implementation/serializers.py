"""Resource representations. Decimals become JSON numbers, datetimes ISO 8601."""

from response import fmt_dt
from services import calc
from validation import as_float


def _common(rec, versioned=True):
    out = {"id": rec["id"], "created_at": fmt_dt(rec["created_at"])}
    if versioned:
        out["updated_at"] = fmt_dt(rec["updated_at"])
        out["version"] = rec["version"]
    return out


def port(rec):
    out = _common(rec)
    out.update(
        {
            "port_code": rec["port_code"],
            "name": rec["name"],
            "eca_zone": rec["eca_zone"],
            "eca_sulfur_limit_pct": as_float(rec["eca_sulfur_limit_pct"]),
            "notice_lead_hours": rec["notice_lead_hours"],
            "concurrent_ops_capacity": rec["concurrent_ops_capacity"],
            "spill_response_tier": rec["spill_response_tier"],
        }
    )
    return out


def fuel_grade(rec):
    out = _common(rec)
    out.update(
        {
            "grade_code": rec["grade_code"],
            "max_sulfur_pct": as_float(rec["max_sulfur_pct"]),
            "eca_permitted": rec["eca_permitted"],
            "test_tolerance_pct": as_float(rec["test_tolerance_pct"]),
            "index_code": rec["index_code"],
            "base_barging_rate_usd_per_mt": as_float(rec["base_barging_rate_usd_per_mt"]),
            "min_barging_fee_usd": as_float(rec["min_barging_fee_usd"]),
            "cross_contamination_group": rec["cross_contamination_group"],
        }
    )
    return out


def index_quote(rec):
    # PRD 2.5: an IndexQuote is immutable and carries neither updated_at nor version.
    out = _common(rec, versioned=False)
    out.update(
        {
            "grade_id": rec["grade_id"],
            "quote_date": fmt_dt(rec["quote_date"]),
            "price_usd_per_mt": as_float(rec["price_usd_per_mt"]),
            "source": rec["source"],
        }
    )
    return out


def customer(rec):
    out = _common(rec)
    out.update(
        {
            "name": rec["name"],
            "credit_limit_usd": as_float(rec["credit_limit_usd"]),
            "payment_terms_days": rec["payment_terms_days"],
            "settlement_basis": rec["settlement_basis"],
            "outstanding_balance_usd": as_float(rec["outstanding_balance_usd"]),
            "conservative_exposure_usd": as_float(rec["conservative_exposure_usd"]),
            "available_credit_usd": as_float(rec["available_credit_usd"]),
            "open_commitment_count": rec["open_commitment_count"],
            "credit_status": rec["credit_status"],
        }
    )
    return out


def delivery_asset(rec):
    out = _common(rec)
    out.update(
        {
            "name": rec["name"],
            "asset_type": rec["asset_type"],
            "capacity_mt": as_float(rec["capacity_mt"]),
            "home_port_id": rec["home_port_id"],
            "boom_certified": rec["boom_certified"],
            "segregated_tanks": rec["segregated_tanks"],
            "turnaround_buffer_minutes": rec["turnaround_buffer_minutes"],
            "last_grade_id": rec["last_grade_id"],
            "status": rec["status"],
            "committed_quantity_mt": as_float(rec["committed_quantity_mt"]),
            "compliance_score": as_float(rec["compliance_score"]),
        }
    )
    return out


def nomination(rec):
    out = _common(rec)
    out.update(
        {
            "customer_id": rec["customer_id"],
            "port_id": rec["port_id"],
            "grade_id": rec["grade_id"],
            "vessel_imo": rec["vessel_imo"],
            "vessel_name": rec["vessel_name"],
            "scrubber_fitted": rec["scrubber_fitted"],
            "nominated_quantity_mt": as_float(rec["nominated_quantity_mt"]),
            "window_start": fmt_dt(rec["window_start"]),
            "window_end": fmt_dt(rec["window_end"]),
            "delivery_mode": rec["delivery_mode"],
            "declared_sulfur_pct": as_float(rec["declared_sulfur_pct"]),
            "eca_documentation_ref": rec["eca_documentation_ref"],
            "fulfillment_status": rec["fulfillment_status"],
            "compliance_status": rec["compliance_status"],
            "compliance_reviewer_user_id": rec["compliance_reviewer_user_id"],
        }
    )
    return out


def delivery_order(rec):
    out = _common(rec)
    out.update(
        {
            "nomination_id": rec["nomination_id"],
            "asset_id": rec["asset_id"],
            "planned_quantity_mt": as_float(rec["planned_quantity_mt"]),
            "slot_start": fmt_dt(rec["slot_start"]),
            "slot_end": fmt_dt(rec["slot_end"]),
            "logistics_status": rec["logistics_status"],
            "measurement_status": rec["measurement_status"],
            "barge_sounding_mt": as_float(rec["barge_sounding_mt"]),
            "vessel_sounding_mt": as_float(rec["vessel_sounding_mt"]),
            "meter_mt": as_float(rec["meter_mt"]),
            "surveyed_mt": as_float(rec["surveyed_mt"]),
            "agreed_quantity_mt": as_float(rec["agreed_quantity_mt"]),
            "measurement_basis": rec["measurement_basis"],
            "shortfall_mt": as_float(rec["shortfall_mt"]),
            "port_clearance_ref": rec["port_clearance_ref"],
            "cleared_at": fmt_dt(rec["cleared_at"]),
        }
    )
    return out


def bunker_delivery_note(rec):
    out = _common(rec)
    out.update(
        {
            "delivery_order_id": rec["delivery_order_id"],
            "bdn_number": rec["bdn_number"],
            "declared_sulfur_pct": as_float(rec["declared_sulfur_pct"]),
            "delivered_quantity_mt": as_float(rec["delivered_quantity_mt"]),
            "sample_seal_number": rec["sample_seal_number"],
            "sample_retention_until": fmt_dt(rec["sample_retention_until"]),
            "sample_custody_status": calc.sample_custody_status(rec),
            "sample_released_at": fmt_dt(rec["sample_released_at"]),
            "status": rec["status"],
            "issued_by_user_id": rec["issued_by_user_id"],
        }
    )
    return out


def quality_claim(rec):
    out = _common(rec)
    out.update(
        {
            "bdn_id": rec["bdn_id"],
            "customer_id": rec["customer_id"],
            "claimed_defect": rec["claimed_defect"],
            "affected_quantity_mt": as_float(rec["affected_quantity_mt"]),
            "quantity_basis_mt": as_float(rec["quantity_basis_mt"]),
            "replacement_price_usd_per_mt": as_float(rec["replacement_price_usd_per_mt"]),
            "status": rec["status"],
            "analysis_round": rec["analysis_round"],
            "remediation_type": rec["remediation_type"],
            "credit_usd": as_float(rec["credit_usd"]),
            "proposed_by_user_id": rec["proposed_by_user_id"],
            "accepted_by_user_id": rec["accepted_by_user_id"],
        }
    )
    return out


def lab_analysis(rec):
    out = _common(rec)
    out.update(
        {
            "claim_id": rec["claim_id"],
            "retest_of_analysis_id": rec["retest_of_analysis_id"],
            "lab_ref": rec["lab_ref"],
            "measured_sulfur_pct": as_float(rec["measured_sulfur_pct"]),
            "verdict": rec["verdict"],
            "exceedance_pct": as_float(rec["exceedance_pct"]),
            "round_index": rec["round_index"],
            "analyzed_by_user_id": rec["analyzed_by_user_id"],
        }
    )
    return out


def invoice(rec):
    out = _common(rec)
    out.update(
        {
            "delivery_order_id": rec["delivery_order_id"],
            "customer_id": rec["customer_id"],
            "pricing_date": fmt_dt(rec["pricing_date"]),
            "index_price_usd_per_mt": as_float(rec["index_price_usd_per_mt"]),
            "quantity_basis_mt": as_float(rec["quantity_basis_mt"]),
            "fuel_cost_usd": as_float(rec["fuel_cost_usd"]),
            "baf_pct": as_float(rec["baf_pct"]),
            "baf_usd": as_float(rec["baf_usd"]),
            "barging_fee_usd": as_float(rec["barging_fee_usd"]),
            "eca_surcharge_usd": as_float(rec["eca_surcharge_usd"]),
            "provisional_amount_usd": as_float(rec["provisional_amount_usd"]),
            "claim_credit_usd": as_float(rec["claim_credit_usd"]),
            "final_amount_usd": as_float(rec["final_amount_usd"]),
            "status": rec["status"],
            "issued_at": fmt_dt(rec["issued_at"]),
            "due_date": fmt_dt(rec["due_date"]),
        }
    )
    return out


def spill_incident(rec):
    out = _common(rec)
    out.update(
        {
            "delivery_order_id": rec["delivery_order_id"],
            "asset_id": rec["asset_id"],
            "port_id": rec["port_id"],
            "reported_at": fmt_dt(rec["reported_at"]),
            "volume_liters": as_float(rec["volume_liters"]),
            "boom_deployed": rec["boom_deployed"],
            "containment_confirmed": rec["containment_confirmed"],
            "severity": rec["severity"],
            "penalty_points": as_float(rec["penalty_points"]),
            "response_ref": rec["response_ref"],
            "status": rec["status"],
            "closed_at": fmt_dt(rec["closed_at"]),
        }
    )
    return out
