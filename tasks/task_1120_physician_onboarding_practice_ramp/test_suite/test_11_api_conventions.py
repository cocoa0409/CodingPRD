"""API-wide conventions: error envelope shape, the resource-specific 404
catalogue, pagination envelope, reverse FK reachability, auth-header
requirement, immediate read-after-write, and the fixed clock default."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    create_physician, create_case, create_offer, extend_offer,
    create_credential_item, create_active_mentor, create_mentorship,
    record_check_in, get_case, set_clock, run_epoch,
    create_physician_payload, create_offer_payload,
)

RECRUITER = TEST_USERS["recruiter_headers"]
DIRECTOR = TEST_USERS["onboarding_director_headers"]
CS1 = TEST_USERS["credentialing_specialist_headers"]


def test_error_envelope_shape_on_not_found(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this standard envelope format"
    PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

    Design: Corner/errors/error_envelope_shape_on_not_found
    """
    resp = api.get_offer(NON_EXISTENT_UUID, DIRECTOR)
    error_data = validate_error(resp, ApiErrorId.ERR_OFFER_NOT_FOUND)
    assert resp.status_code == 404
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(error_data["message"], str) and error_data["message"], (
        "error responses carry a human-readable message"
    )
    assert body["meta"].get("api_request_id"), "meta carries api_request_id"
    assert body["meta"].get("api_request_timestamp"), "meta carries api_request_timestamp"


def test_per_resource_not_found_sweep(api):
    """PRD §2.10: "The catalogue is resource-specific: `ERR_PHYSICIAN_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_CREDENTIAL_ITEM_NOT_FOUND`, `ERR_TRAINING_PLAN_NOT_FOUND`, `ERR_TRAINING_MODULE_NOT_FOUND`, `ERR_SCHEDULE_TEMPLATE_NOT_FOUND`, `ERR_PANEL_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_CAMPAIGN_EVENT_NOT_FOUND`, `ERR_GUARANTEE_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`, `ERR_MENTORSHIP_NOT_FOUND`, and `ERR_SNAPSHOT_NOT_FOUND`, all HTTP 404."

    Design: Corner/errors/per_resource_not_found_sweep
    """
    checks = [
        (api.get_physician, ApiErrorId.ERR_PHYSICIAN_NOT_FOUND),
        (api.get_onboarding_case, ApiErrorId.ERR_CASE_NOT_FOUND),
        (api.get_credential_item, ApiErrorId.ERR_CREDENTIAL_ITEM_NOT_FOUND),
        (api.get_training_plan, ApiErrorId.ERR_TRAINING_PLAN_NOT_FOUND),
        (api.get_training_module, ApiErrorId.ERR_TRAINING_MODULE_NOT_FOUND),
        (api.get_schedule_template, ApiErrorId.ERR_SCHEDULE_TEMPLATE_NOT_FOUND),
        (api.get_panel, ApiErrorId.ERR_PANEL_NOT_FOUND),
        (api.get_referral_campaign, ApiErrorId.ERR_CAMPAIGN_NOT_FOUND),
        (api.get_campaign_event, ApiErrorId.ERR_CAMPAIGN_EVENT_NOT_FOUND),
        (api.get_income_guarantee, ApiErrorId.ERR_GUARANTEE_NOT_FOUND),
        (api.get_ramp_milestone, ApiErrorId.ERR_MILESTONE_NOT_FOUND),
        (api.get_mentorship_assignment, ApiErrorId.ERR_MENTORSHIP_NOT_FOUND),
        (api.get_retention_snapshot, ApiErrorId.ERR_SNAPSHOT_NOT_FOUND),
    ]
    for getter, error_id in checks:
        resp = getter(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, error_id)
        assert resp.status_code == 404, f"{error_id} must be HTTP 404, got {resp.status_code}"


def test_credential_items_list_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0."
    PRD §2.3: "The response `meta` object of a list endpoint carries `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/credential_items_list_pagination_envelope
    """
    physician = create_physician(full_name="Dr. Hal2", specialty="CARDIOLOGY")
    case = create_case(physician["id"])
    create_credential_item(case["id"], "STATE_LICENSE", document_ref="d1")
    create_credential_item(case["id"], "DEA_REGISTRATION", document_ref="d2")
    create_credential_item(case["id"], "BOARD_CERTIFICATION", document_ref="d3")

    resp = api.list_credential_items(
        CS1, params={"onboarding_case_id": case["id"], "limit": 2, "offset": 0}
    )
    page1, meta1 = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert resp.json()["meta"].get("api_request_id")

    resp = api.list_credential_items(
        CS1, params={"onboarding_case_id": case["id"], "limit": 2, "offset": 2}
    )
    page2, meta2 = validate_paginated(resp)
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_fk_reverse_reachability_both_forms(api):
    """PRD §3.2: "Offers can be listed with optional `onboarding_case_id` and `status` filters."
    PRD §3.9: "Check-ins of an assignment are listed in `day_marker` order."

    Design: Corner/endpoints/fk_reverse_reachability_both_forms
    """
    physician = create_physician(full_name="Dr. Irv")
    case = create_case(physician["id"])
    offer = create_offer(case)
    mentor = create_active_mentor()
    assignment = create_mentorship(case["id"], mentor["id"])
    record_check_in(assignment["id"], mentor["id"], "D30", "POSITIVE")
    record_check_in(assignment["id"], mentor["id"], "D90", "CONCERN")

    offers = get_success_data(
        api.list_offers(RECRUITER, params={"onboarding_case_id": case["id"]})
    )
    assert len(offers) == 1
    assert offers[0]["id"] == offer["id"]

    check_ins = get_success_data(api.list_check_ins(assignment["id"], DIRECTOR))
    assert [c["day_marker"] for c in check_ins] == ["D30", "D90"]


def test_create_physician_missing_auth_headers_returns_400(api):
    """PRD §2.1: "A request missing either header, or carrying a role the system does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/create_physician_missing_auth_headers_returns_400
    """
    resp = api.create_physician(
        create_physician_payload(
            full_name="Dr. No", specialty="PEDIATRICS",
            email="no@x.com", hire_type="NEW_GRAD",
        ),
        headers=None,
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    assert resp.status_code == 400
    assert resp.json()["response_type"] == "error"


def test_immediate_read_after_write_visibility(api):
    """PRD §3.2: "A new offer starts in `DRAFT` with `negotiation_round` 0, and its creation increments the case's `version`."
    PRD §2.7: "Each such reconciliation mutates the OnboardingCase itself: its `updated_at` refreshes and its `version` increments."

    Design: Corner/consistency_model/immediate_read_after_write_visibility
    """
    physician = create_physician(full_name="Dr. Ole")
    case = create_case(physician["id"])
    version_before = case["version"]

    data = validate_success(
        api.create_offer(create_offer_payload(case["id"], version_before), RECRUITER), 201
    )
    assert data["status"] == "DRAFT", "the create response itself carries the state"

    case_after = get_case(case["id"])
    assert case_after["version"] == version_before + 1, (
        "the create's side effect on the case version is visible immediately"
    )


def test_clock_default_is_fixed_startup_instant(api):
    """PRD §2.4: "The server maintains a logical clock whose startup default is exactly 2026-05-01T00:00:00Z and which never falls back to wall-clock time; every date and datetime comparison in the domain — offer expiry, credential expiry, start-date gates, reporting windows — reads this clock."
    PRD §2.4: "Second it expires offers still in `EXTENDED` or `COUNTERED` whose `expires_at` lies in the past."

    Design: Corner/consistency_model/clock_default_is_fixed_startup_instant
    """
    physician = create_physician(full_name="Dr. Peg")
    case = create_case(physician["id"])
    offer = create_offer(case, expires_at="2026-05-02T00:00:00Z")
    offer = extend_offer(offer["id"])
    assert offer["status"] == "EXTENDED"

    # At the startup default 2026-05-01T00:00:00Z the 2026-05-02 expiry is in
    # the future: the sweep touches nothing.
    sweep = run_epoch()
    assert sweep["expired_offer_ids"] == []

    set_clock("2026-05-03T00:00:00Z")
    sweep = run_epoch()
    assert offer["id"] in sweep["expired_offer_ids"]
    assert get_success_data(api.get_offer(offer["id"], RECRUITER))["status"] == "EXPIRED"
