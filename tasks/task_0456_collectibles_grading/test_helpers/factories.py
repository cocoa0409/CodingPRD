"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "SL_CODE": "EXPRESS",
    "TURNAROUND_DAYS": 2,
    "BASE_FEE": 5000,
    "MAX_DECLARED": 50000,
    "INSURANCE_BPS": 200,
    "GS_CODE": "CARD_10PT",
    "MAX_GRADE": 10,
    "AUTHENTIC_MIN": 1.0,
    "WEIGHT": 2500,
    "DECLARED_VALUE": 30000,
    "TITLE": "Test Card",
}


def create_customer_payload(**overrides) -> dict:
    defaults = {"email": "test@example.com", "full_name": "Test Customer"}
    defaults.update(overrides)
    return defaults


def create_service_level_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["SL_CODE"],
        "turnaround_business_days": DEFAULTS["TURNAROUND_DAYS"],
        "base_fee_cents": DEFAULTS["BASE_FEE"],
        "max_declared_value_cents": DEFAULTS["MAX_DECLARED"],
        "insurance_rate_bps": DEFAULTS["INSURANCE_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_grading_standard_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["GS_CODE"],
        "max_grade": DEFAULTS["MAX_GRADE"],
        "authentic_min_grade": DEFAULTS["AUTHENTIC_MIN"],
        "centering_weight_bps": DEFAULTS["WEIGHT"],
        "corners_weight_bps": DEFAULTS["WEIGHT"],
        "edges_weight_bps": DEFAULTS["WEIGHT"],
        "surface_weight_bps": DEFAULTS["WEIGHT"],
    }
    defaults.update(overrides)
    return defaults


def create_submission_payload(customer_id, service_level_id, **overrides) -> dict:
    defaults = {"customer_id": customer_id, "service_level_id": service_level_id}
    defaults.update(overrides)
    return defaults


def create_item_payload(grading_standard_id, **overrides) -> dict:
    defaults = {
        "grading_standard_id": grading_standard_id,
        "title": DEFAULTS["TITLE"],
        "declared_value_cents": DEFAULTS["DECLARED_VALUE"],
    }
    defaults.update(overrides)
    return defaults


def create_intake_payload(matches_declaration=True, **overrides) -> dict:
    defaults = {"condition_note": "ok", "matches_declaration": matches_declaration}
    defaults.update(overrides)
    return defaults


def create_grade_assessment_payload(grading_standard_id, centering=9, corners=9,
                                    edges=9, surface=9, **overrides) -> dict:
    defaults = {
        "grading_standard_id": grading_standard_id,
        "centering_subgrade": centering,
        "corners_subgrade": corners,
        "edges_subgrade": edges,
        "surface_subgrade": surface,
    }
    defaults.update(overrides)
    return defaults


def create_authentication_payload(verdict="GENUINE", **overrides) -> dict:
    defaults = {"verdict": verdict}
    defaults.update(overrides)
    return defaults


def create_encapsulate_payload(assessment_id, **overrides) -> dict:
    defaults = {"assessment_id": assessment_id}
    defaults.update(overrides)
    return defaults


def create_label_payload(population_report_id, **overrides) -> dict:
    defaults = {"population_report_id": population_report_id}
    defaults.update(overrides)
    return defaults


def create_regrade_request_payload(prior_slab_id, expected_item_version,
                                   reason="believe undergraded", **overrides) -> dict:
    defaults = {
        "prior_slab_id": prior_slab_id,
        "expected_item_version": expected_item_version,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(carrier="UPS", tracking_number="1Z999", **overrides) -> dict:
    defaults = {"carrier": carrier, "tracking_number": tracking_number}
    defaults.update(overrides)
    return defaults
