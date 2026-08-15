"""Corner queue: endpoint behavior, pagination envelope, error envelope,
conditional actions, clock default (PRD §2.2, §2.3, §2.4, §3.3, §3.5, §3.6).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, CLOCK_DEFAULT_ISO, assert_same_instant,
    TEST_USERS,
    create_member, create_policy, set_clock,
    intake_case, triage_case, begin_review, create_in_review_case,
    decide_grievance_from_in_review, create_and_send_decision_notification,
    setup_notified_case,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
ANALYST = TEST_USERS["case_analyst_headers"]
MD = TEST_USERS["medical_director_headers"]
MSR = TEST_USERS["member_services_rep_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
CLAIMS = TEST_USERS["claims_processor_headers"]


def test_case_list_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return. If
    not provided, it defaults to 10, with a minimum of 1 and a maximum of
    100. The `offset` parameter specifies the number of items to skip and
    defaults to 0."
PRD §2.3: "Paginated list responses include the following fields in the `meta` object
    of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/endpoints/case_list_pagination_envelope
    """
    member = create_member("MBR-EP1", full_name="Page Test", program="MEDICARE")
    set_clock("2026-08-01T00:00:00Z")
    intake_case(member["id"], case_kind="GRIEVANCE")
    # Advance the clock between intakes so the duplicate-intake guard's
    # one-hour look-back does not fire (PRD §3.2).
    set_clock("2026-08-01T02:00:00Z")
    intake_case(member["id"], case_kind="GRIEVANCE")
    set_clock("2026-08-01T04:00:00Z")
    intake_case(member["id"], case_kind="GRIEVANCE")
    page, meta = validate_paginated(api.list_cases(
        COMPLIANCE, params={"member_id": member["id"], "limit": 2,
                            "offset": 0}))
    assert len(page) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    page2, meta2 = validate_paginated(api.list_cases(
        COMPLIANCE, params={"member_id": member["id"], "limit": 2,
                            "offset": 2}))
    assert len(page2) == 1
    assert meta2["has_more"] is False


def test_case_events_reverse_reachability_chronological(api):
    """PRD §3.9: "The log replays in `occurred_at` ascending order with `created_at`
    ascending as the tie-break, and accepts an `event_type` filter."
PRD §3.3: "The server stamps `acknowledged_at`, computes `resolution_due_at`, appends
    a `NOTE` event whose `body` reads `TRIAGED`, and increments the case's
    `version`."

    Design: Corner/endpoints/case_events_reverse_reachability_and_order
    """
    member = create_member("MBR-EP2", full_name="Ev Order", program="MEDICARE")
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock(CLOCK_DEFAULT_ISO)
    case = triage_case(intake_case(member["id"], case_kind="GRIEVANCE")["id"])
    get_success_data(api.append_case_event(
        case["id"], {"event_type": "NOTE", "body": "second"}, ANALYST),
        expected_status=201)
    get_success_data(api.append_case_event(
        case["id"], {"event_type": "NOTE", "body": "third"}, ANALYST),
        expected_status=201)
    events = get_success_data(api.list_case_events(case["id"], COMPLIANCE))
    bodies = [e["body"] for e in events]
    assert bodies[0] == "TRIAGED", "The triage NOTE is appended at triage time"
    assert bodies[-1] == "third"
    assert "second" in bodies


def test_ire_referral_rejected_for_grievance(api):
    """PRD §3.6: "A `ComplianceOfficer` forwards a `NOTIFIED` case to the IRE by supplying
    the `ire_organization_code` of the contracted independent review
    organization — but only for an `APPEAL` whose `decision_outcome` is
    not `FULLY_FAVORABLE`, since fully favorable outcomes leave nothing to
    dispute externally, and only within 72 hours of `decided_at`; a
    forwarding attempted after that window is rejected with
    `ERR_IRE_WINDOW_MISSED`."
PRD §2.8: "Fifth, transition validity: if the requested action is not declared from
    the resource's current state, the request is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/endpoints/conditional_action_ire_only_for_adverse_appeals
    """
    member = create_member("MBR-EP3", full_name="Cond Act", program="MEDICARE")
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock(CLOCK_DEFAULT_ISO)
    case = setup_notified_case(member["id"], case_kind="GRIEVANCE",
                               decision_outcome="UNFAVORABLE")
    # A GRIEVANCE never satisfies the APPEAL-only referral precondition.
    validate_error(
        api.create_ire_referral(case["id"], {"ire_organization_code": "IRE-X"},
                                COMPLIANCE),
        ApiErrorId.ERR_INVALID_STATE)


def test_grievance_decided_directly_from_in_review(api):
    """PRD §3.5: "The non-clinical door: a `CaseAnalyst` decides a case directly from
    `IN_REVIEW`, which is permitted only when the `case_kind` is
    `GRIEVANCE` — an organization determination or appeal decided without
    clinical review is rejected with `ERR_CLINICAL_REVIEW_REQUIRED`."

    Design: Corner/endpoints/grievance_decide_nonclinical_path_allowed
    """
    member = create_member("MBR-EP4", full_name="Grv Direct",
                           program="MEDICARE")
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock(CLOCK_DEFAULT_ISO)
    case = create_in_review_case(member["id"], case_kind="GRIEVANCE")
    data = validate_success(api.decide_case(
        case["id"], {"decision_outcome": "UNFAVORABLE"}, ANALYST))
    assert data["status"] == "DECIDED"
    assert data["decision_outcome"] == "UNFAVORABLE"


def test_clock_default_is_pinned_startup_value(api):
    """PRD §2.4: "Before any operator call to the clock-setting capability, the logical
    clock reads exactly `2026-08-01T00:00:00Z`; this is the mandatory
    startup default, and the clock never falls back to wall-clock time
    thereafter."
PRD §3.2: "The server stamps `received_at` at intake, sets `status` to `RECEIVED`,
    and increments the member's `open_case_count` by one."

    Design: Corner/endpoints/clock_default_is_pinned_startup_value
    """
    member = create_member("MBR-EP5", full_name="Clock Def", program="MEDICARE")
    # No set_current_utc call: intake stamps received_at at the pinned default.
    data = validate_success(api.create_case(
        {"member_id": member["id"], "case_kind": "GRIEVANCE"}, INTAKE),
        expected_status=201)
    assert_same_instant(data["received_at"], "2026-08-01T00:00:00Z")


def test_duplicate_snapshot_rejected(api):
    """PRD §3.9: "The uniqueness scope is the pair of `report_period` and `case_id`:
    re-running a snapshot that would recapture a pair already recorded is
    rejected with `ERR_DUPLICATE_SNAPSHOT` (HTTP 409)."

    Design: Corner/errors/error_duplicate_snapshot_covered
    """
    member = create_member("MBR-ER1", full_name="Dup Snap", program="MEDICARE")
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock(CLOCK_DEFAULT_ISO)
    case = create_in_review_case(member["id"], case_kind="GRIEVANCE")
    decide_grievance_from_in_review(case["id"], decision_outcome="UNFAVORABLE")
    get_success_data(api.create_audit_snapshot({"report_period": "2026-08"},
                                               COMPLIANCE),
                     expected_status=201)
    validate_error(api.create_audit_snapshot({"report_period": "2026-08"},
                                             COMPLIANCE),
                   ApiErrorId.ERR_DUPLICATE_SNAPSHOT)


def test_error_envelope_shape_on_failure(api):
    """PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."
PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."
PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/errors/error_envelope_shape_on_failure
    """
    # Member creation is PlatformAdmin-only; IntakeSpecialist gets 403.
    response = api.create_member(
        {"member_ref": "MBR-ER3", "full_name": "Env Shape",
         "program": "MEDICARE"}, INTAKE)
    error_data = validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)
    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)
    assert isinstance(error_data["message"], str) and error_data["message"].strip()


def test_triage_response_carries_mutation_immediately(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will
    return the created or updated resource object in the data field."
PRD §3.3: "The server stamps `acknowledged_at`, computes `resolution_due_at`, appends
    a `NOTE` event whose `body` reads `TRIAGED`, and increments the case's
    `version`."

    Design: Corner/consistency_model/immediate_consistency_mutation_visible_in_same_response
    """
    member = create_member("MBR-CM1", full_name="Immediate", program="MEDICARE")
    provider_resp = validate_success(api.create_provider(
        {"npi": "4433221100", "legal_name": "Imm Clinic",
         "contract_status": "CONTRACTED", "w9_on_file": True}, ADMIN),
        expected_status=201)
    create_policy("MEDICARE", "APPEAL", "STANDARD", resolution_hours=168,
                  extension_hours=0, effectuation_hours=72)
    set_clock(CLOCK_DEFAULT_ISO)
    case = intake_case(member["id"], case_kind="APPEAL",
                       provider_id=provider_resp["id"])
    data = validate_success(api.triage_case(case["id"], INTAKE))
    # The mutation is observable in the triage response body itself.
    assert data["status"] == "TRIAGED"
    assert_same_instant(data["resolution_due_at"], "2026-08-08T00:00:00Z")
