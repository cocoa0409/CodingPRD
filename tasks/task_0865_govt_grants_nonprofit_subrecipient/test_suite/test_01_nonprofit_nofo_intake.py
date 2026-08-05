"""Nonprofit registration, NOFO creation/validation, and intake gating."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    NON_EXISTENT_UUID,
    assert_nonprofit,
    create_nofo_payload,
    create_nonprofit_payload,
    make_program_officer_headers,
    make_subrecipient_headers,
    create_nonprofit,
    create_nofo,
    create_draft_application,
)


def test_nonprofit_registration_generates_system_fields(api):
    """PRD §3.1: "the new organization starts with cumulative_federal_expenditures_cents
    at 0 and a null latest_risk_tier."
    PRD §2.4: "an integer version that starts at 1 and increments by one on every mutation
    of that resource."

    Design: Corner/entities/nonprofit_system_fields_generated
    """
    res = api.create_nonprofit(
        create_nonprofit_payload(legal_name="Sys Org"), make_program_officer_headers()
    )
    np = validate_success(res, 201)
    assert_nonprofit(np)
    assert np["cumulative_federal_expenditures_cents"] == 0
    assert np["version"] == 1
    assert np["latest_risk_tier"] is None


def test_nofo_missing_total_pool_rejected(api):
    """PRD §3.1: "Publishing a Notice of Funding Opportunity records the opportunity's title,
    its cfda_number assistance-listing number, the total_pool_cents available to award, the
    max_award_cents ceiling on any single award, the indirect_cost_cap_pct capping the
    negotiated indirect rate any subaward under this opportunity may use, and the intake window
    bounded by open_date and close_date."

    Design: Corner/entities/nofo_create_missing_required_returns_validation
    """
    payload = create_nofo_payload()
    del payload["total_pool_cents"]
    res = api.create_nofo(payload, make_program_officer_headers())
    validate_error(res, "ERR_VALIDATION")


def test_get_unknown_subaward_returns_not_found(api):
    """PRD §2.5: "the server validates path identifiers strictly left to right and rejects
    at the first identifier that does not resolve, returning the not-found error specific to
    that resource type: ... ERR_SUBAWARD_NOT_FOUND ... each with HTTP 404."

    Design: Corner/entities/get_subaward_not_found_returns_404
    """
    res = api.get_subaward(NON_EXISTENT_UUID, make_program_officer_headers())
    validate_error(res, "ERR_SUBAWARD_NOT_FOUND")


def test_submit_new_application_after_intake_closed_rejected(api):
    """PRD §3.2: "the parent opportunity's intake_status must be OPEN at this first submission,
    or the request is rejected with ERR_INTAKE_CLOSED."

    Design: Corner/state_machines/cancel_intake_then_new_application_returns_intake_closed
    """
    np = create_nonprofit(legal_name="Intake Org")
    nofo = create_nofo()
    app = create_draft_application(nofo["id"], np["id"])
    validate_success(api.close_intake(nofo["id"], make_program_officer_headers()), 200)

    res = api.submit_application(app["id"], make_subrecipient_headers(np["id"]))
    validate_error(res, "ERR_INTAKE_CLOSED")
