"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PROVIDER_NPI": "1234567890",
    "PROVIDER_NAME": "Dr A",
    "PAYER_NAME": "Acme Health",
    "MEMBER_NUMBER": "M1",
    "PROCEDURE_CODE": "CPT-1",
    "EVIDENCE_URI": "s3://doc",
}


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "npi": DEFAULTS["PROVIDER_NPI"],
        "name": DEFAULTS["PROVIDER_NAME"],
        "specialty": "ONCOLOGY",
    }
    defaults.update(overrides)
    return defaults


def create_payer_payload(**overrides) -> dict:
    # standard_sla_hours and expedited_sla_hours are optional (PRD §3.1 defaults).
    defaults = {"name": DEFAULTS["PAYER_NAME"]}
    defaults.update(overrides)
    return defaults


def create_member_payload(payer_id, **overrides) -> dict:
    # coinsurance_rate is optional (PRD §3.1 default 0.2).
    defaults = {"payer_id": payer_id, "member_number": DEFAULTS["MEMBER_NUMBER"]}
    defaults.update(overrides)
    return defaults


def create_reviewer_payload(payer_id, **overrides) -> dict:
    # p2p_buffer_minutes is optional (PRD §3.1 default 0).
    defaults = {"payer_id": payer_id, "name": "Rev A", "specialty": "ONCOLOGY"}
    defaults.update(overrides)
    return defaults


def create_authorization_request_payload(member_id, provider_id, **overrides) -> dict:
    # is_expedited optional (default false); supersedes_request_id and
    # expected_authorizationrequest_version only on resubmissions.
    defaults = {
        "member_id": member_id,
        "provider_id": provider_id,
        "request_type": "DRUG",
        "procedure_code": DEFAULTS["PROCEDURE_CODE"],
        "requested_units": 1,
        "unit_cost_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_clinical_evidence_payload(request_id, **overrides) -> dict:
    defaults = {
        "request_id": request_id,
        "document_type": "CHART_NOTE",
        "line_item_cost_cents": 0,
        "uri": DEFAULTS["EVIDENCE_URI"],
    }
    defaults.update(overrides)
    return defaults


def create_review_decision_payload(request_id, reviewer_id, outcome, **overrides) -> dict:
    defaults = {"request_id": request_id, "reviewer_id": reviewer_id, "outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_peer_to_peer_session_payload(request_id, reviewer_id, slot_start, slot_end, **overrides) -> dict:
    defaults = {
        "request_id": request_id,
        "reviewer_id": reviewer_id,
        "slot_start": slot_start,
        "slot_end": slot_end,
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(request_id, **overrides) -> dict:
    defaults = {"request_id": request_id}
    defaults.update(overrides)
    return defaults
