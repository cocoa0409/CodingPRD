"""The annual redetermination lifecycle (self-loop, finalize, cascades) and the
appeal / fair-hearing workflow (segregation of duties, overturn reinstatement,
terminal lockdowns, and the validation-priority conflicts).
"""
from test_helpers import (
    api_client as api,
    TEST_USERS,
    get_success_data, validate_success, validate_error, ApiErrorId,
    make_caseworker_headers, make_hearing_officer_headers,
    setup_in_redetermination, setup_terminated_enrollment,
    setup_heard_appeal, setup_renewed_redetermination,
    create_redetermination_payload,
)

CW = TEST_USERS["caseworker_headers"]
APP = TEST_USERS["applicant_headers"]
HO = TEST_USERS["hearing_officer_headers"]


# ===========================================================================
# Queue A — non_linear_state_machine (redetermination self-loop)
# ===========================================================================
def test_redetermination_self_loop_info_requested():
    """PRD §3.8: "The first such request advances `redet_status` from `INITIATED`
    to `INFO_REQUESTED`; a further request while already `INFO_REQUESTED` is a
    self-loop that keeps the status at `INFO_REQUESTED`. Each request — whether
    the first transition or a self-loop — increases `info_request_count` by one".

    Design: Difficulty/non_linear_state_machine/redetermination_self_loop_info_requested
    """
    hh, app, enr, redet, _det = setup_in_redetermination(state="CA", make_ineligible=False)
    api.request_info(redet["id"], CW)        # INITIATED -> INFO_REQUESTED (count 1)
    second = validate_success(api.request_info(redet["id"], CW))  # self-loop (count 2)
    assert second["redet_status"] == "INFO_REQUESTED"
    assert second["info_request_count"] == 2


def test_info_request_count_increments_on_first_request():
    """PRD §3.8: "so the count records how many times information was requested
    over the life of the redetermination."

    Design: Difficulty/non_linear_state_machine/redetermination_self_loop_info_requested
    """
    hh, app, enr, redet, _det = setup_in_redetermination(state="CA", make_ineligible=False)
    first = validate_success(api.request_info(redet["id"], CW))
    assert first["redet_status"] == "INFO_REQUESTED"
    assert first["info_request_count"] == 1


# ===========================================================================
# Queue A — transitive_cascade (terminate -> ledger debit)
# ===========================================================================
def test_redet_terminate_cascades_enrollment_terminate_then_ledger_debit():
    """PRD §3.8: "A successful termination sets `redet_status` to `TERMINATED`
    and cascades the parent enrollment from `IN_REDETERMINATION` to `TERMINATED`,
    which in turn debits the household's `covered_member_months` by the
    enrollment's `member_months` and decrements `active_enrollment_count` by one."

    Design: Difficulty/transitive_cascade/redet_terminate_cascades_enrollment_terminate_then_ledger_debit
    """
    hh, app, enr, redet, _det = setup_in_redetermination(
        state="CA", make_ineligible=True, second_member=True)
    # Pre-termination ledger: size 2 -> member_months 24.
    finalized = validate_success(api.finalize_redetermination(
        redet["id"], {"target_status": "TERMINATED"}, CW))
    assert finalized["redet_status"] == "TERMINATED"
    enr_after = validate_success(api.get_enrollment(enr["id"], CW))
    assert enr_after["coverage_status"] == "TERMINATED"
    hh_after = validate_success(api.get_household(hh["id"], CW))
    assert hh_after["covered_member_months"] == 0
    assert hh_after["active_enrollment_count"] == 0


def test_terminate_cascade_debits_member_months():
    """PRD §3.8: "which in turn debits the household's `covered_member_months` by
    the enrollment's `member_months` and decrements `active_enrollment_count` by
    one."

    Design: Difficulty/transitive_cascade/redet_terminate_cascades_enrollment_terminate_then_ledger_debit
    """
    hh, app, enr, redet, _det = setup_in_redetermination(
        state="CA", make_ineligible=True, second_member=True)
    before = validate_success(api.get_household(hh["id"], CW))
    assert before["covered_member_months"] == 24
    api.finalize_redetermination(redet["id"], {"target_status": "TERMINATED"}, CW)
    after = validate_success(api.get_household(hh["id"], CW))
    assert after["covered_member_months"] == 0
    assert after["active_enrollment_count"] == 0


# ===========================================================================
# Queue A — transitive_cascade (appeal overturn -> reinstate -> re-credit)
# ===========================================================================
def test_appeal_overturn_cascades_enrollment_reinstate_then_ledger_recredit():
    """PRD §3.9: "A successful overturn cascades the linked enrollment from
    `TERMINATED` back to `ACTIVE`, re-crediting the household's
    `covered_member_months` by the enrollment's `member_months` and incrementing
    `active_enrollment_count` by one."

    Design: Difficulty/transitive_cascade/appeal_overturn_cascades_enrollment_reinstate_then_ledger_recredit
    """
    hh, enr, redet, appeal = setup_heard_appeal(state="CA", cw_id="cw-1", ho_id="ho-9")
    ho = make_hearing_officer_headers("ho-9")
    ruled = validate_success(api.rule_appeal(appeal["id"], {"target_status": "OVERTURNED"}, ho))
    assert ruled["appeal_status"] == "OVERTURNED"
    enr_after = validate_success(api.get_enrollment(enr["id"], CW))
    assert enr_after["coverage_status"] == "ACTIVE"
    hh_after = validate_success(api.get_household(hh["id"], CW))
    assert hh_after["covered_member_months"] == 24
    assert hh_after["active_enrollment_count"] == 1


def test_overturn_recredits_active_enrollment_count():
    """PRD §3.9: "re-crediting the household's `covered_member_months` by the
    enrollment's `member_months` and incrementing `active_enrollment_count` by
    one."

    Design: Difficulty/transitive_cascade/appeal_overturn_cascades_enrollment_reinstate_then_ledger_recredit
    """
    hh, enr, redet, appeal = setup_heard_appeal(state="CA", cw_id="cw-2", ho_id="ho-8")
    before = validate_success(api.get_household(hh["id"], CW))
    assert before["active_enrollment_count"] == 0
    ho = make_hearing_officer_headers("ho-8")
    api.rule_appeal(appeal["id"], {"target_status": "OVERTURNED"}, ho)
    after = validate_success(api.get_household(hh["id"], CW))
    assert after["active_enrollment_count"] == 1


# ===========================================================================
# Queue A — priority_pair_validation_conflict
# ===========================================================================
def test_state_invalid_beats_continuous_coverage_lock():
    """PRD §2.9: "Only after these four universal gates pass does the system
    evaluate the state, concurrency, and business rules specific to each
    endpoint, in the priority order detailed in §3."
    PRD §3.8: "A redetermination that has been terminated and then has an appeal
    filed against it moves automatically from `TERMINATED` to `PENDING_APPEAL`."

    A RENEWED (terminal) redetermination finalized again to TERMINATED fails the
    generic state check (ERR_INVALID_STATE) before the continuous-coverage check.

    Design: Difficulty/priority_pair_validation_conflict/state_invalid_beats_continuous_coverage_lock
    """
    # State has continuous_coverage_active=true; redetermination already RENEWED.
    hh, app, enr, redet = setup_renewed_redetermination(
        state="CA", continuous_coverage_active=True)
    resp = api.finalize_redetermination(redet["id"], {"target_status": "TERMINATED"}, CW)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_state_invalid_on_renewed_finalize_leaves_enrollment_active():
    """PRD §3.8: "A successful renewal sets `redet_status` to `RENEWED` and
    cascades the parent enrollment from `IN_REDETERMINATION` back to `ACTIVE`."

    The rejected re-finalize (ERR_INVALID_STATE wins over the coverage-lock check)
    must not move the already-ACTIVE enrollment.

    Design: Difficulty/priority_pair_validation_conflict/state_invalid_beats_continuous_coverage_lock
    """
    hh, app, enr, redet = setup_renewed_redetermination(
        state="CA", continuous_coverage_active=True)
    resp = api.finalize_redetermination(redet["id"], {"target_status": "TERMINATED"}, CW)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    enr_after = validate_success(api.get_enrollment(enr["id"], CW))
    assert enr_after["coverage_status"] == "ACTIVE"


def test_existence_beats_segregation_of_duties():
    """PRD §2.9: "Existence of all path and body foreign-key resources is checked
    third, left to right, yielding `ERR_NOT_FOUND`."

    Hearing a non-existent appeal fails the existence check before the
    segregation-of-duties business rule.

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_segregation_of_duties
    """
    ho = make_hearing_officer_headers("ho-9")
    resp = api.hear_appeal("00000000-0000-4000-8000-000000000000", ho)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_hear_missing_appeal_not_found_regardless_of_officer_identity():
    """PRD §2.9: "Existence of all path and body foreign-key resources is checked
    third, left to right, yielding `ERR_NOT_FOUND`. ... Only after these four
    universal gates pass does the system evaluate the state, concurrency, and
    business rules specific to each endpoint".

    Even when the acting officer id would collide with a caseworker (the
    segregation trigger), a missing appeal still yields ERR_NOT_FOUND — existence
    is gated before the business segregation rule.

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_segregation_of_duties
    """
    ho = make_hearing_officer_headers("cw-1")  # would be the SoD collision id
    resp = api.hear_appeal("00000000-0000-4000-8000-0000000000aa", ho)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Queue A — cross_entity_state_dependency (continuous coverage lock)
# ===========================================================================
def test_redet_terminate_requires_state_continuous_coverage_inactive():
    """PRD §3.8: "it additionally requires that the parent enrollment's governing
    state rule not have `continuous_coverage_active` set to true; while that
    freeze is in force the termination is blocked with
    `ERR_CONTINUOUS_COVERAGE_LOCK`."

    Design: Difficulty/cross_entity_state_dependency/redet_terminate_requires_state_continuous_coverage_inactive
    """
    hh, app, enr, redet, _det = setup_in_redetermination(
        state="CA", make_ineligible=True, continuous_coverage_active=True)
    resp = api.finalize_redetermination(redet["id"], {"target_status": "TERMINATED"}, CW)
    validate_error(resp, ApiErrorId.ERR_CONTINUOUS_COVERAGE_LOCK.value)
    still = validate_success(api.get_enrollment(enr["id"], CW))
    assert still["coverage_status"] == "IN_REDETERMINATION"


def test_continuous_coverage_lock_preserves_household_ledger():
    """PRD §3.8: "while that freeze is in force the termination is blocked with
    `ERR_CONTINUOUS_COVERAGE_LOCK`."

    Because the termination is blocked, no ledger debit fires — the household's
    covered_member_months and active_enrollment_count are untouched.

    Design: Difficulty/cross_entity_state_dependency/redet_terminate_requires_state_continuous_coverage_inactive
    """
    hh, app, enr, redet, _det = setup_in_redetermination(
        state="CA", make_ineligible=True, second_member=True, continuous_coverage_active=True)
    before = validate_success(api.get_household(hh["id"], CW))
    resp = api.finalize_redetermination(redet["id"], {"target_status": "TERMINATED"}, CW)
    validate_error(resp, ApiErrorId.ERR_CONTINUOUS_COVERAGE_LOCK.value)
    after = validate_success(api.get_household(hh["id"], CW))
    # size-2 enrollment stays in coverage: 24 member-months, count 1, unchanged.
    assert after["covered_member_months"] == before["covered_member_months"] == 24
    assert after["active_enrollment_count"] == before["active_enrollment_count"] == 1


# ===========================================================================
# Queue A — resource_temporal_overlap (half-open redetermination window)
# ===========================================================================
def test_redetermination_half_open_window_overlap_rejected():
    """PRD §3.8: "Finally, the new window must not intersect the half-open window
    of any prior redetermination for the same enrollment, including ones that
    have already reached `RENEWED`; an overlapping window is rejected with
    `ERR_REDETERMINATION_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/redetermination_half_open_window_overlap_rejected
    """
    # First redetermination over [2026-11-01, 2026-12-15) finalized RENEWED;
    # enrollment back to ACTIVE so the in-progress error does not pre-empt.
    hh, app, enr, redet = setup_renewed_redetermination(state="CA")
    enr_v2 = validate_success(api.get_enrollment(enr["id"], CW))["version"]
    # Reuse a fresh determination for the second window.
    det2 = get_success_data(api.run_determination(app["id"], CW))
    resp = api.create_redetermination(
        create_redetermination_payload(
            enr["id"], det2["id"], enr_v2,
            window_open="2026-12-01T00:00:00Z", window_close="2026-12-31T00:00:00Z"),
        CW)
    validate_error(resp, ApiErrorId.ERR_REDETERMINATION_WINDOW_OVERLAP.value)


def test_redetermination_adjacent_half_open_window_allowed():
    """PRD §3.8: "the redetermination window as `window_open` (an inclusive ISO
    8601 UTC start) and `window_close` (an exclusive ISO 8601 UTC end, so the
    window is the half-open interval from `window_open` up to but not including
    `window_close`)".
    PRD §3.8: "the new window must not intersect the half-open window of any prior
    redetermination for the same enrollment".

    A second window whose open equals the prior window's (exclusive) close shares
    no point with it under half-open semantics, so the create succeeds.

    Design: Difficulty/resource_temporal_overlap/redetermination_half_open_window_overlap_rejected
    """
    hh, app, enr, redet = setup_renewed_redetermination(state="CA")
    enr_v2 = validate_success(api.get_enrollment(enr["id"], CW))["version"]
    det2 = get_success_data(api.run_determination(app["id"], CW))
    # Prior window was [2026-11-01, 2026-12-15); this opens exactly at 2026-12-15.
    created = validate_success(api.create_redetermination(
        create_redetermination_payload(
            enr["id"], det2["id"], enr_v2,
            window_open="2026-12-15T00:00:00Z", window_close="2026-12-31T00:00:00Z"),
        CW), 201)
    assert created["redet_status"] == "INITIATED"


# ===========================================================================
# Queue B — state_machines corner
# ===========================================================================
def test_terminal_renewed_redetermination_finalize_again_invalid_state():
    """PRD §3.8: "A successful renewal sets `redet_status` to `RENEWED` and
    cascades the parent enrollment from `IN_REDETERMINATION` back to `ACTIVE`."

    A RENEWED redetermination is terminal; finalizing it again is an undefined
    transition → ERR_INVALID_STATE.

    Design: Corner/state_machines/terminal_renewed_redetermination_finalize_again_invalid_state
    """
    hh, app, enr, redet = setup_renewed_redetermination(state="CA")
    resp = api.finalize_redetermination(redet["id"], {"target_status": "RENEWED"}, CW)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_redetermination_in_progress_blocks_second_open():
    """PRD §3.8: "if the target enrollment is already `IN_REDETERMINATION` —
    meaning a redetermination is already open for it — the request is rejected
    with the specific `ERR_REDETERMINATION_IN_PROGRESS` rather than the generic
    invalid-state error, and this specific check is evaluated before the generic
    one so the specific error wins."

    Design: Corner/state_machines/redetermination_in_progress_blocks_second_open
    """
    hh, app, enr, redet, det = setup_in_redetermination(state="CA", make_ineligible=False)
    enr_v2 = validate_success(api.get_enrollment(enr["id"], CW))["version"]
    resp = api.create_redetermination(
        create_redetermination_payload(
            enr["id"], det["id"], enr_v2,
            window_open="2026-12-20T00:00:00Z", window_close="2026-12-31T00:00:00Z"),
        CW)
    validate_error(resp, ApiErrorId.ERR_REDETERMINATION_IN_PROGRESS.value)


def test_rule_already_overturned_appeal_again_returns_invalid_state():
    """PRD §3.9: "A successful overturn cascades the linked enrollment from
    `TERMINATED` back to `ACTIVE`".

    Once an appeal is OVERTURNED (terminal) it cannot be ruled again → the
    transition is undefined and rejected with ERR_INVALID_STATE.

    Design: Corner/state_machines/rule_already_overturned_appeal_again_returns_invalid_state
    """
    hh, enr, redet, appeal = setup_heard_appeal(state="CA", cw_id="cw-aa", ho_id="ho-bb")
    ho = make_hearing_officer_headers("ho-bb")
    api.rule_appeal(appeal["id"], {"target_status": "OVERTURNED"}, ho)
    resp = api.rule_appeal(appeal["id"], {"target_status": "OVERTURNED"}, ho)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Queue B — validations corner (finalize RENEWED with ineligible determination)
# ===========================================================================
def test_finalize_renewed_with_ineligible_determination_returns_determination_ineligible():
    """PRD §3.8: "Finalizing to `RENEWED` requires that the redetermination's
    linked `new_determination_id` determination have a `decision` of `ELIGIBLE`;
    if it does not, the finalize is rejected with `ERR_DETERMINATION_INELIGIBLE`."

    Design: Corner/validations/finalize_renewed_with_ineligible_determination_returns_determination_ineligible
    """
    hh, app, enr, redet, _det = setup_in_redetermination(state="CA", make_ineligible=True)
    resp = api.finalize_redetermination(redet["id"], {"target_status": "RENEWED"}, CW)
    validate_error(resp, ApiErrorId.ERR_DETERMINATION_INELIGIBLE.value)


# ===========================================================================
# Queue B — errors corner (segregation of duties)
# ===========================================================================
def test_segregation_of_duties_same_user_hears_own_case():
    """PRD §3.9: "this is the segregation-of-duties checkpoint, because the acting
    hearing officer's `X-User-ID` must differ from the `assigned_caseworker_id`
    pinned on the underlying application — if they are the same person, the
    hearing is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/errors/segregation_of_duties_same_user_hears_own_case
    """
    # The same operator id "sod-1" claimed the application and now acts as HearingOfficer.
    hh, app, enr, redet = setup_terminated_enrollment(state="CA", cw_id="sod-1")
    enr_v2 = validate_success(api.get_enrollment(enr["id"], CW))["version"]
    appeal = get_success_data(api.create_appeal(
        {"enrollment_id": enr["id"], "redetermination_id": redet["id"],
         "expected_enrollment_version": enr_v2}, APP))
    sod = make_hearing_officer_headers("sod-1")
    api.schedule_appeal(appeal["id"], sod)
    resp = api.hear_appeal(appeal["id"], sod)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
