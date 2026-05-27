"""Office-action examiner cycle: NON_FINAL → response → next OA returns
Application to OFFICE_ACTION_OUTSTANDING (cycle); NOTICE_OF_ALLOWANCE
withdraws the incumbent OUTSTANDING OA(s) and lands the application in
ALLOWED; the single-outstanding-OA-per-application invariant.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_applicant_headers,
    set_clock,
    setup_application_in_awaiting_examination,
    setup_application_with_outstanding_oa,
    issue_office_action, file_oa_response, get_application,
    create_office_action_payload,
)

EXAMINER = TEST_USERS["examiner_headers"]


# =============================================================================
# Difficulty / non_linear_state_machine / application_office_action_revision_cycle
# =============================================================================

def test_second_oa_after_response_re_enters_office_action_outstanding(api):
    """A second NON_FINAL OA issued after the applicant's first response
    advances the Application back to OFFICE_ACTION_OUTSTANDING (cycle); the
    first OA stays RESPONDED and the second is OUTSTANDING.

    PRD §3.6: "From `RESPONSE_FILED`, the examiner may issue another office
    action. The same creation endpoint is reused, the same action-type rules
    apply, and a new `OfficeAction` lands in `OUTSTANDING` while the
    application cycles back to `OFFICE_ACTION_OUTSTANDING`."

    Design: Difficulty/non_linear_state_machine/application_office_action_revision_cycle
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application, oa1 = setup_application_with_outstanding_oa(
        entity_size="LARGE", action_type="NON_FINAL",
    )
    file_oa_response(applicant, oa1["id"], extension_months_requested=0,
                     claim_amendment_count=10)

    oa2 = issue_office_action(application["id"], action_type="FINAL")

    oa1_after = validate_success(api.get_office_action(oa1["id"], EXAMINER), 200)
    oa2_after = validate_success(api.get_office_action(oa2["id"], EXAMINER), 200)
    app_after = get_application(application["id"], applicant)

    assert oa1_after["status"] == "RESPONDED", (
        f"First OA must remain RESPONDED, got {oa1_after['status']}"
    )
    assert oa2_after["status"] == "OUTSTANDING", (
        f"Second OA must be OUTSTANDING, got {oa2_after['status']}"
    )
    assert app_after["status"] == "OFFICE_ACTION_OUTSTANDING", (
        f"Application must cycle back to OFFICE_ACTION_OUTSTANDING, "
        f"got {app_after['status']}"
    )


def test_response_then_second_oa_application_version_bumps(api):
    """Cycle continuation: every transition (response, next OA) bumps the
    Application.version by 1.

    PRD §3.5: "A timely response transitions the parent office action from
    `OUTSTANDING` to `RESPONDED` (bumping `OfficeAction.version`) and the
    parent application from `OFFICE_ACTION_OUTSTANDING` to `RESPONSE_FILED`
    (bumping `Application.version`)."
    PRD §3.6: "From `RESPONSE_FILED`, the examiner may issue another office
    action. The same creation endpoint is reused, the same action-type rules
    apply, and a new `OfficeAction` lands in `OUTSTANDING` while the
    application cycles back to `OFFICE_ACTION_OUTSTANDING`."

    Design: Difficulty/non_linear_state_machine/application_office_action_revision_cycle
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application, oa1 = setup_application_with_outstanding_oa(
        entity_size="LARGE", action_type="NON_FINAL",
    )
    v_before_response = get_application(application["id"], applicant)["version"]

    file_oa_response(applicant, oa1["id"], extension_months_requested=0,
                     claim_amendment_count=10)
    v_after_response = get_application(application["id"], applicant)["version"]
    assert v_after_response > v_before_response, (
        f"Application.version must bump on response: was {v_before_response}, "
        f"now {v_after_response}"
    )

    issue_office_action(application["id"], action_type="FINAL")
    v_after_second_oa = get_application(application["id"], applicant)["version"]
    assert v_after_second_oa > v_after_response, (
        f"Application.version must bump on second OA: was {v_after_response}, "
        f"now {v_after_second_oa}"
    )


# =============================================================================
# Difficulty / non_linear_state_machine / office_action_branching_terminal_states
# =============================================================================

def test_noa_branch_withdraws_outstanding_responds_via_noa_pathway(api):
    """OUTSTANDING OA branches: the previously-responded OA stays RESPONDED,
    the still-OUTSTANDING OA is set to WITHDRAWN, and the NOTICE_OF_ALLOWANCE
    that triggers the branching is itself OUTSTANDING. Application lands ALLOWED.

    PRD §3.6: "A notice of allowance issued while the application is in
    `OFFICE_ACTION_OUTSTANDING` advances the application to `ALLOWED` and
    additionally sets every other `OUTSTANDING` office action on the same
    application to `WITHDRAWN` as a side effect, bumping the version of each
    office action that was withdrawn (excluding the notice itself, which
    remains the active allowance)."

    Design: Difficulty/non_linear_state_machine/office_action_branching_terminal_states
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application, oa_a = setup_application_with_outstanding_oa(
        entity_size="LARGE", action_type="NON_FINAL",
    )
    file_oa_response(applicant, oa_a["id"], extension_months_requested=0,
                     claim_amendment_count=10)
    oa_b = issue_office_action(application["id"], action_type="NON_FINAL")
    noa = issue_office_action(application["id"], action_type="NOTICE_OF_ALLOWANCE")

    oa_a_after = validate_success(api.get_office_action(oa_a["id"], EXAMINER), 200)
    oa_b_after = validate_success(api.get_office_action(oa_b["id"], EXAMINER), 200)
    noa_after = validate_success(api.get_office_action(noa["id"], EXAMINER), 200)
    app_after = get_application(application["id"], applicant)

    assert oa_a_after["status"] == "RESPONDED"
    assert oa_b_after["status"] == "WITHDRAWN", (
        f"The previously-OUTSTANDING OA must be WITHDRAWN by the NOA, "
        f"got {oa_b_after['status']}"
    )
    assert noa_after["status"] == "OUTSTANDING", (
        f"The NOA itself must remain OUTSTANDING (the active allowance), "
        f"got {noa_after['status']}"
    )
    assert app_after["status"] == "ALLOWED"


def test_noa_withdrawn_oa_version_bumps_from_noa_side_effect(api):
    """A WITHDRAWN OA's version bumps when the NOA-supersede cascade fires
    (PRD §3.6 — "bumping the version of each office action that was withdrawn").

    PRD §3.6: "A notice of allowance issued while the application is in
    `OFFICE_ACTION_OUTSTANDING` advances the application to `ALLOWED` and
    additionally sets every other `OUTSTANDING` office action on the same
    application to `WITHDRAWN` as a side effect, bumping the version of each
    office action that was withdrawn (excluding the notice itself, which
    remains the active allowance)."

    Design: Difficulty/non_linear_state_machine/office_action_branching_terminal_states
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application, oa_b = setup_application_with_outstanding_oa(
        entity_size="LARGE", action_type="NON_FINAL",
    )
    v_before = oa_b["version"]

    issue_office_action(application["id"], action_type="NOTICE_OF_ALLOWANCE")

    oa_b_after = validate_success(api.get_office_action(oa_b["id"], EXAMINER), 200)
    assert oa_b_after["status"] == "WITHDRAWN"
    assert oa_b_after["version"] > v_before, (
        f"WITHDRAWN OA.version must bump (was {v_before}, now {oa_b_after['version']})"
    )


# =============================================================================
# Difficulty / resource_temporal_overlap / at_most_one_outstanding_oa_per_application_capacity_one
# =============================================================================

def test_second_non_final_oa_while_outstanding_rejected(api):
    """Issuing a second NON_FINAL OA while another OA is already OUTSTANDING
    is rejected with ERR_OFFICE_ACTION_ALREADY_OUTSTANDING; the incumbent
    OA's status is unchanged.

    PRD §3.4: "At most one office action with `status` of `OUTSTANDING` may
    exist per application at any time. An attempt to create a second
    non-allowance office action while another is already `OUTSTANDING` is
    rejected with `ERR_OFFICE_ACTION_ALREADY_OUTSTANDING`; the only office
    action that may be issued while another is `OUTSTANDING` is one whose
    action type is `NOTICE_OF_ALLOWANCE`, because the notice withdraws all
    other outstanding actions as a side effect."

    Design: Difficulty/resource_temporal_overlap/at_most_one_outstanding_oa_per_application_capacity_one
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application, oa1 = setup_application_with_outstanding_oa(
        entity_size="LARGE", action_type="NON_FINAL",
    )
    res = api.create_office_action(
        create_office_action_payload(application_id=application["id"],
                                     action_type="NON_FINAL"),
        EXAMINER,
    )
    validate_error(res, ApiErrorId.ERR_OFFICE_ACTION_ALREADY_OUTSTANDING.value)

    oa1_after = validate_success(api.get_office_action(oa1["id"], EXAMINER), 200)
    assert oa1_after["status"] == "OUTSTANDING", (
        f"Incumbent OA must remain OUTSTANDING after rejected second OA, "
        f"got {oa1_after['status']}"
    )


def test_noa_permitted_while_outstanding_supersedes_incumbent(api):
    """The only OA that may be issued while another is OUTSTANDING is a
    NOTICE_OF_ALLOWANCE — it withdraws the incumbent and lands ALLOWED.

    PRD §3.4: "At most one office action with `status` of `OUTSTANDING` may
    exist per application at any time. An attempt to create a second
    non-allowance office action while another is already `OUTSTANDING` is
    rejected with `ERR_OFFICE_ACTION_ALREADY_OUTSTANDING`; the only office
    action that may be issued while another is `OUTSTANDING` is one whose
    action type is `NOTICE_OF_ALLOWANCE`, because the notice withdraws all
    other outstanding actions as a side effect."

    Design: Difficulty/resource_temporal_overlap/at_most_one_outstanding_oa_per_application_capacity_one
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application, oa1 = setup_application_with_outstanding_oa(
        entity_size="LARGE", action_type="NON_FINAL",
    )
    noa = issue_office_action(application["id"], action_type="NOTICE_OF_ALLOWANCE")

    oa1_after = validate_success(api.get_office_action(oa1["id"], EXAMINER), 200)
    app_after = get_application(application["id"], applicant)
    assert oa1_after["status"] == "WITHDRAWN", (
        f"Incumbent must be WITHDRAWN by NOA, got {oa1_after['status']}"
    )
    assert app_after["status"] == "ALLOWED"
    assert noa["action_type"] == "NOTICE_OF_ALLOWANCE"
