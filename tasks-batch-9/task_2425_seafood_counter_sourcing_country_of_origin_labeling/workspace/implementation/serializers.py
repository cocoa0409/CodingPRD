"""Entity serializers.  Field sets follow SCAFFOLD 1.1 exactly.

Species and IceBedReading are exceptions to the common-field rule (PRD 2.4):
they carry only `id` and `created_at` -- never `updated_at` or `version`.
"""

from common import iso, num


def _common(record):
    return {
        "id": record["id"],
        "created_at": iso(record["created_at"]),
        "updated_at": iso(record["updated_at"]),
        "version": record["version"],
    }


def counter(record):
    data = {
        "store_number": record["store_number"],
        "department_name": record["department_name"],
        "case_slot_count": record["case_slot_count"],
        "posture": record["posture"],
        "open_excursion_count": record["open_excursion_count"],
        "violation_points": record["violation_points"],
        "verification_cycle_index": record["verification_cycle_index"],
        "last_cycle_required_samples": record["last_cycle_required_samples"],
        "last_cycle_max_supplier_risk_index": num(
            record["last_cycle_max_supplier_risk_index"], 2
        ),
        "shrink_gross_cents": record["shrink_gross_cents"],
        "shrink_net_cents": record["shrink_net_cents"],
        "recovered_conversion_cents": record["recovered_conversion_cents"],
    }
    data.update(_common(record))
    return data


def supplier(record):
    data = {
        "name": record["name"],
        "permit_number": record["permit_number"],
        "status": record["status"],
        "lifetime_sample_count": record["lifetime_sample_count"],
        "lifetime_mismatch_count": record["lifetime_mismatch_count"],
        "substitution_risk_index_rolling": num(record["substitution_risk_index_rolling"], 2),
        "substitution_risk_index_lifetime": num(record["substitution_risk_index_lifetime"], 2),
        "chargeback_assessed_total_cents": record["chargeback_assessed_total_cents"],
        "chargeback_outstanding_cents": record["chargeback_outstanding_cents"],
        "chargeback_settled_cents": record["chargeback_settled_cents"],
        "chargeback_reversed_cents": record["chargeback_reversed_cents"],
    }
    data.update(_common(record))
    return data


def species(record):
    return {
        "id": record["id"],
        "market_name": record["market_name"],
        "scientific_name": record["scientific_name"],
        "acceptable_market_names": list(record["acceptable_market_names"]),
        "simp_covered": record["simp_covered"],
        "high_risk_substitution": record["high_risk_substitution"],
        "sustainability_program_eligible": record["sustainability_program_eligible"],
        "created_at": iso(record["created_at"]),
    }


def lot(record):
    data = {
        "counter_id": record["counter_id"],
        "supplier_id": record["supplier_id"],
        "species_id": record["species_id"],
        "lot_code": record["lot_code"],
        "harvest_method": record["harvest_method"],
        "production_method": record["production_method"],
        "origin_country_code": record["origin_country_code"],
        "processing_country_code": record["processing_country_code"],
        "previously_frozen": record["previously_frozen"],
        "fresh_claim": record["fresh_claim"],
        "received_weight_kg": num(record["received_weight_kg"], 3),
        "remaining_weight_kg": num(record["remaining_weight_kg"], 3),
        "unit_cost_cents_per_kg": record["unit_cost_cents_per_kg"],
        "retail_price_cents_per_kg": record["retail_price_cents_per_kg"],
        "cooked_retail_price_cents_per_kg": record["cooked_retail_price_cents_per_kg"],
        "case_slot": record["case_slot"],
        "cased_at": iso(record["cased_at"]),
        "vacated_at": iso(record["vacated_at"]),
        "received_at": iso(record["received_at"]),
        "intake_status": record["intake_status"],
        "label_status": record["label_status"],
        "chargeback_status": record["chargeback_status"],
        "chargeback_assessed_cents": record["chargeback_assessed_cents"],
    }
    data.update(_common(record))
    return data


def case_label(record):
    data = {
        "lot_id": record["lot_id"],
        "certification_id": record["certification_id"],
        "display_market_name": record["display_market_name"],
        "origin_statement": record["origin_statement"],
        "production_method_statement": record["production_method_statement"],
        "frozen_disclosure_statement": record["frozen_disclosure_statement"],
        "sustainability_claim_text": record["sustainability_claim_text"],
        "status": record["status"],
        "withdraw_reason": record["withdraw_reason"],
        "published_at": iso(record["published_at"]),
        "withdrawn_at": iso(record["withdrawn_at"]),
    }
    data.update(_common(record))
    return data


def ad_item(record):
    data = {
        "counter_id": record["counter_id"],
        "lot_id": record["lot_id"],
        "certification_id": record["certification_id"],
        "headline": record["headline"],
        "ad_start_at": iso(record["ad_start_at"]),
        "ad_end_at": iso(record["ad_end_at"]),
        "cool_statement": record["cool_statement"],
        "status": record["status"],
        "cool_review_status": record["cool_review_status"],
        "claim_review_status": record["claim_review_status"],
        "cool_reviewer_user_id": record["cool_reviewer_user_id"],
        "claim_reviewer_user_id": record["claim_reviewer_user_id"],
        "retract_reason": record["retract_reason"],
    }
    data.update(_common(record))
    return data


def reading(record):
    return {
        "id": record["id"],
        "counter_id": record["counter_id"],
        "case_slot": record["case_slot"],
        "reading_at": iso(record["reading_at"]),
        "temperature_c": num(record["temperature_c"], 1),
        "taken_by_user_id": record["taken_by_user_id"],
        "breach": record["breach"],
        "created_at": iso(record["created_at"]),
    }


def excursion(record):
    data = {
        "counter_id": record["counter_id"],
        "case_slot": record["case_slot"],
        "started_at": iso(record["started_at"]),
        "ended_at": iso(record["ended_at"]),
        "exposure_minutes": record["exposure_minutes"],
        "peak_temperature_c": num(record["peak_temperature_c"], 1),
        "severity": record["severity"],
        "status": record["status"],
        "resolution": record["resolution"],
        "resolution_note": record["resolution_note"],
    }
    data.update(_common(record))
    return data


def sample(record):
    data = {
        "lot_id": record["lot_id"],
        "observed_species_id": record["observed_species_id"],
        "sampled_weight_g": float(record["sampled_weight_g"]),
        "cycle_index": record["cycle_index"],
        "status": record["status"],
        "lab_reference": record["lab_reference"],
        "dispute_reason": record["dispute_reason"],
        "retest_count": record["retest_count"],
        "result_recorded_at": iso(record["result_recorded_at"]),
    }
    data.update(_common(record))
    return data


def simp_document(record):
    data = {
        "lot_id": record["lot_id"],
        "harvesting_vessel_name": record["harvesting_vessel_name"],
        "harvest_date": iso(record["harvest_date"]),
        "landing_date": iso(record["landing_date"]),
        "chain_of_custody_ref": record["chain_of_custody_ref"],
        "status": record["status"],
        "review_note": record["review_note"],
        "reviewed_at": iso(record["reviewed_at"]),
        "amendment_count": record["amendment_count"],
    }
    data.update(_common(record))
    return data


def certification(record):
    data = {
        "counter_id": record["counter_id"],
        "supplier_id": record["supplier_id"],
        "species_id": record["species_id"],
        "program_name": record["program_name"],
        "certificate_number": record["certificate_number"],
        "valid_from": iso(record["valid_from"]),
        "valid_until": iso(record["valid_until"]),
        "claim_text": record["claim_text"],
        "status": record["status"],
        "review_note": record["review_note"],
    }
    data.update(_common(record))
    return data


def shrink_event(record):
    data = {
        "lot_id": record["lot_id"],
        "reason": record["reason"],
        "shrink_weight_kg": num(record["shrink_weight_kg"], 3),
        "conversion_requested_kg": num(record["conversion_requested_kg"], 3),
        "approved_conversion_kg": num(record["approved_conversion_kg"], 3),
        "allowance_kg": num(record["allowance_kg"], 3),
        "cook_yield_kg": num(record["cook_yield_kg"], 3),
        "provisional_value_cents": record["provisional_value_cents"],
        "final_value_cents": record["final_value_cents"],
        "recovery_credit_cents": record["recovery_credit_cents"],
        "status": record["status"],
        "posted_at": iso(record["posted_at"]),
        "reversed_at": iso(record["reversed_at"]),
        "reversal_note": record["reversal_note"],
    }
    data.update(_common(record))
    return data


def violation(record):
    data = {
        "counter_id": record["counter_id"],
        "lot_id": record["lot_id"],
        "category": record["category"],
        "points": record["points"],
        "status": record["status"],
        "detail": record["detail"],
        "cure_note": record["cure_note"],
        "expunge_note": record["expunge_note"],
        "cured_at": iso(record["cured_at"]),
        "expunged_at": iso(record["expunged_at"]),
    }
    data.update(_common(record))
    return data
