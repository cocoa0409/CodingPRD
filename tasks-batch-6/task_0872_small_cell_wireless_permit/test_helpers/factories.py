"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "COMPANY_NAME": "Acme Wireless",
    "CONTACT_EMAIL": "ops@acme.example",
    "SEGMENT_NAME": "Main St",
    "CORRIDOR_CODE": "C-1",
    "CONSTRUCTION_DATE": "2026-06-15T00:00:00Z",
}


def create_applicant_payload(**overrides) -> dict:
    payload = {
        "company_name": DEFAULTS["COMPANY_NAME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_support_structure_payload(
    structure_type="EXISTING_UTILITY", max_collocations=2, **overrides
) -> dict:
    payload = {
        "structure_type": structure_type,
        "max_collocations": max_collocations,
    }
    payload.update(overrides)
    return payload


def create_row_segment_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["SEGMENT_NAME"],
        "corridor_code": DEFAULTS["CORRIDOR_CODE"],
    }
    payload.update(overrides)
    return payload


def create_application_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


def create_node_payload(
    support_structure_id, row_segment_id,
    facility_type="COLLOCATION",
    proposed_construction_date=DEFAULTS["CONSTRUCTION_DATE"],
    **overrides,
) -> dict:
    payload = {
        "facility_type": facility_type,
        "support_structure_id": support_structure_id,
        "row_segment_id": row_segment_id,
        "proposed_construction_date": proposed_construction_date,
    }
    payload.update(overrides)
    return payload


def completeness_review_payload(complete=True, **overrides) -> dict:
    payload = {"complete": complete}
    payload.update(overrides)
    return payload


def design_review_payload(expected_support_structure_version, outcome="PASS", **overrides) -> dict:
    payload = {
        "outcome": outcome,
        "expected_support_structure_version": expected_support_structure_version,
    }
    payload.update(overrides)
    return payload


def aesthetic_review_payload(outcome="PASS", **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def inspection_payload(outcome="PASS", **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def payment_payload(amount_cents, expected_fee_invoice_version, **overrides) -> dict:
    payload = {
        "amount_cents": amount_cents,
        "expected_fee_invoice_version": expected_fee_invoice_version,
    }
    payload.update(overrides)
    return payload


def renew_payload(period_start, period_end, **overrides) -> dict:
    payload = {"period_start": period_start, "period_end": period_end}
    payload.update(overrides)
    return payload


def decision_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


def appeal_payload(grounds="applicant disputes the decision", **overrides) -> dict:
    payload = {"grounds": grounds}
    payload.update(overrides)
    return payload


def appeal_decision_payload(uphold, **overrides) -> dict:
    payload = {"uphold": uphold}
    payload.update(overrides)
    return payload
