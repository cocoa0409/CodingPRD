"""Enrollment gating, withdraw cascades, and validation-priority conflicts.

Difficulty queue: transitive_cascade (withdraw depth-3), cross_entity_state_dependency,
priority_pair_validation_conflict. Corner queue: committed_count reconciliation.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_guardian_headers, make_director_headers,
    ApiErrorId,
    setup_enrolling_session, setup_enrolling_session_with_staffed_cabin,
    setup_submitted_application, setup_deposit_paid_application,
    setup_bunked_application, flag_health_form,
    api_client,
)


# ===========================================================================
# Difficulty / transitive_cascade — withdraw(ENROLLED) depth-3
# ===========================================================================
def test_withdraw_enrolled_cascades_occupancy_staffable_and_posture():
    """PRD §3.6: "Withdrawing an `ENROLLED` application is permitted only when the
    session is not `RUNNING` (otherwise `ERR_SESSION_RUNNING_NO_WITHDRAW`); it
    reverses all `APPLIED` payments to `REVERSED`, moves the payment axis to
    `REFUND_DUE`, decrements both `enrolled_count` and `committed_count`, decrements
    the cabin's `occupied_bunks`, recomputes the cabin's `is_staffable` and clears the
    `cabin_id`, drops all `BOOKED` activity enrollments (each freeing a seat), and
    recomputes the session's `ratio_posture`."
    PRD §3.2: "If no cabin in the session holds any camper, the posture is
    `UNDERSTAFFED`, since an empty session cannot be started."

    Design: Difficulty/transitive_cascade/withdraw_enrolled_cascades_occupancy_staffable_posture_depth3
    """
    env = setup_enrolling_session_with_staffed_cabin(
        camp_overrides={"deposit_cents": 25_000, "counselor_camper_ratio": 6},
        num_counselors=1,
    )
    # full lifecycle to ENROLLED (clears health internally)
    gc = setup_bunked_application(env, deposit_cents=25_000, email="wd1@x.com", clear_health=True)
    director = make_director_headers()
    app_id = gc["application"]["id"]
    get_success_data(api_client.enroll_application(app_id, director))
    g_headers = make_guardian_headers(gc["guardian"]["id"])

    # session still ENROLLING (not RUNNING) -> withdraw permitted
    withdrawn = validate_success(api_client.withdraw_application(app_id, g_headers))
    assert withdrawn["enroll_status"] == "WITHDRAWN", withdrawn["enroll_status"]

    cabin = validate_success(api_client.get_cabin(env["cabin"]["id"], director))
    assert cabin["occupied_bunks"] == 0, cabin["occupied_bunks"]
    assert cabin["is_staffable"] is True, cabin["is_staffable"]  # 0 campers => trivially staffable

    session = validate_success(api_client.get_session(env["session"]["id"], director))
    assert session["ratio_posture"] == "UNDERSTAFFED", session["ratio_posture"]


def test_withdraw_deposit_paid_frees_cabin_occupancy_cascade():
    """PRD §3.6: "Withdrawing a `DEPOSIT_PAID` application reverses every `APPLIED`
    payment on the application to `REVERSED` and moves the payment axis to
    `REFUND_DUE`; if a `cabin_id` is set, the cabin's `occupied_bunks` is decremented,
    its `is_staffable` recomputed, and the `cabin_id` cleared".

    Design: Difficulty/transitive_cascade/withdraw_enrolled_cascades_occupancy_staffable_posture_depth3
    """
    env = setup_enrolling_session_with_staffed_cabin(
        camp_overrides={"deposit_cents": 25_000, "counselor_camper_ratio": 6},
        num_counselors=1,
    )
    gc = setup_bunked_application(env, deposit_cents=25_000, email="wd2@x.com")
    director = make_director_headers()
    cabin_before = validate_success(api_client.get_cabin(env["cabin"]["id"], director))
    assert cabin_before["occupied_bunks"] == 1, cabin_before["occupied_bunks"]

    g_headers = make_guardian_headers(gc["guardian"]["id"])
    withdrawn = validate_success(api_client.withdraw_application(gc["application"]["id"], g_headers))
    assert withdrawn["payment_status"] == "REFUND_DUE", withdrawn["payment_status"]

    cabin_after = validate_success(api_client.get_cabin(env["cabin"]["id"], director))
    assert cabin_after["occupied_bunks"] == 0, cabin_after["occupied_bunks"]
    assert cabin_after["is_staffable"] is True


# ===========================================================================
# Difficulty / cross_entity_state_dependency
# ===========================================================================
def test_enroll_blocked_when_camper_health_not_cleared():
    """PRD §3.6: "the camper's `health_status` must be exactly `CLEARED` (otherwise
    `ERR_HEALTH_NOT_CLEARED`)".

    Design: Difficulty/cross_entity_state_dependency/enroll_blocked_when_camper_health_not_cleared
    """
    env = setup_enrolling_session_with_staffed_cabin(
        camp_overrides={"deposit_cents": 25_000, "counselor_camper_ratio": 6},
        num_counselors=1,
    )
    # camper submitted health form but never CLEARED (health_status == PENDING)
    gc = setup_bunked_application(env, deposit_cents=25_000, email="he1@x.com", clear_health=False)
    director = make_director_headers()
    resp = api_client.enroll_application(gc["application"]["id"], director)
    validate_error(resp, ApiErrorId.ERR_HEALTH_NOT_CLEARED.value)


def test_enroll_with_flagged_camper_health_rejected_not_cleared():
    """PRD §3.6: "the camper's `health_status` must be exactly `CLEARED` (otherwise
    `ERR_HEALTH_NOT_CLEARED`)".
    PRD §3.3: "Flagging instead moves the form to `FLAGGED`, sets the camper's
    `health_status` to `FLAGGED`".

    Design: Difficulty/cross_entity_state_dependency/enroll_blocked_when_camper_health_not_cleared
    """
    env = setup_enrolling_session_with_staffed_cabin(
        camp_overrides={"deposit_cents": 25_000, "counselor_camper_ratio": 6},
        num_counselors=1,
    )
    gc = setup_bunked_application(env, deposit_cents=25_000, email="he3@x.com", clear_health=False)
    # nurse flags the form so health_status becomes FLAGGED (still not CLEARED)
    flag_health_form(gc["health_form"]["id"])
    director = make_director_headers()
    resp = api_client.enroll_application(gc["application"]["id"], director)
    validate_error(resp, ApiErrorId.ERR_HEALTH_NOT_CLEARED.value)


def test_enroll_blocked_when_target_cabin_understaffed():
    """PRD §3.6: "the target cabin must be `is_staffable` true after counting this
    camper (otherwise `ERR_CABIN_UNDERSTAFFED`)".

    Design: Difficulty/cross_entity_state_dependency/enroll_blocked_when_target_cabin_understaffed
    """
    # cabin has NO staff -> is_staffable false once camper counted; camper IS cleared
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000,
                                                  "counselor_camper_ratio": 6})
    gc = setup_bunked_application(env, deposit_cents=25_000, email="cu1@x.com", clear_health=True)
    director = make_director_headers()
    resp = api_client.enroll_application(gc["application"]["id"], director)
    validate_error(resp, ApiErrorId.ERR_CABIN_UNDERSTAFFED.value)


def test_enroll_blocked_when_only_cit_half_weight_below_required():
    """PRD §3.6: "the target cabin must be `is_staffable` true after counting this
    camper (otherwise `ERR_CABIN_UNDERSTAFFED`)".
    PRD §3.2: "a `CIT` contributes 5 when the camp's `cit_counts_as_half` flag is true
    or 10 when that flag is false."

    Design: Difficulty/cross_entity_state_dependency/enroll_blocked_when_target_cabin_understaffed
    """
    # cabin staffed only by a single CIT (weight 5); 1 camper requires weight 10 -> understaffed
    env = setup_enrolling_session(
        camp_overrides={"deposit_cents": 25_000, "counselor_camper_ratio": 6,
                        "cit_counts_as_half": True},
    )
    director = make_director_headers()
    cit = get_success_data(api_client.create_staff(
        env["camp"]["id"], {"full_name": "CIT Only", "role_kind": "CIT",
                            "is_background_cleared": True}, director))
    get_success_data(api_client.create_cabin_assignment(
        {"cabin_id": env["cabin"]["id"], "staff_member_id": cit["id"]}, director))
    gc = setup_bunked_application(env, deposit_cents=25_000, email="rd1@x.com", clear_health=True)
    resp = api_client.enroll_application(gc["application"]["id"], director)
    validate_error(resp, ApiErrorId.ERR_CABIN_UNDERSTAFFED.value)


# ===========================================================================
# Difficulty / priority_pair_validation_conflict
# ===========================================================================
def test_pay_deposit_invalid_state_beats_deposit_amount_mismatch():
    """PRD §3.10: the validation order lists "whether the target resource is in a valid
    state for the requested transition (`ERR_INVALID_STATE`)" before "the fiscal
    constraints — deposit amount matching, aid not exceeding tuition, and canteen
    no-overdraft (`ERR_DEPOSIT_AMOUNT_MISMATCH`, `ERR_AID_EXCEEDS_TUITION`, `ERR_CANTEEN_INSUFFICIENT_FUNDS`)".

    Design: Difficulty/priority_pair_validation_conflict/pay_deposit_invalid_state_beats_deposit_amount_mismatch
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000})
    # already DEPOSIT_PAID
    gc = setup_deposit_paid_application(env, deposit_cents=25_000, email="ps1@x.com")
    g_headers = make_guardian_headers(gc["guardian"]["id"])
    # wrong state (already paid) AND wrong amount -> ERR_INVALID_STATE wins (p6 < p11)
    resp = api_client.pay_deposit(gc["application"]["id"], {"amount_cents": 99_999}, g_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_pay_deposit_on_withdrawn_with_wrong_amount_reports_invalid_state():
    """PRD §3.10: the order lists "whether the target resource is in a valid state for
    the requested transition (`ERR_INVALID_STATE`)" before "the fiscal constraints —
    deposit amount matching, aid not exceeding tuition, and canteen no-overdraft
    (`ERR_DEPOSIT_AMOUNT_MISMATCH`, `ERR_AID_EXCEEDS_TUITION`, `ERR_CANTEEN_INSUFFICIENT_FUNDS`)".

    Design: Difficulty/priority_pair_validation_conflict/pay_deposit_invalid_state_beats_deposit_amount_mismatch
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000})
    gc = setup_submitted_application(env, email="ps2@x.com")  # OFFERED
    g_headers = make_guardian_headers(gc["guardian"]["id"])
    # withdraw -> terminal WITHDRAWN, then pay-deposit with wrong amount
    get_success_data(api_client.withdraw_application(gc["application"]["id"], g_headers))
    resp = api_client.pay_deposit(gc["application"]["id"], {"amount_cents": 12_345}, g_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_enroll_health_not_cleared_beats_cabin_understaffed():
    """PRD §3.10: the validation order runs "the health and infirmary safety gates —
    EpiPen-required on submit and clear, cleared-required before enroll,
    swim-test-cleared for waterfront offerings (`ERR_EPIPEN_REQUIRED`,
    `ERR_HEALTH_NOT_CLEARED`, `ERR_SWIM_TEST_REQUIRED`)" before "the eligibility and
    matching constraints — cabin gender and age band fit at submit, gender and age fit
    at bunk assignment, staffing ratio, and staff background clearance
    (`ERR_NO_ELIGIBLE_CABIN`, `ERR_CABIN_GENDER_MISMATCH`, `ERR_CABIN_AGE_MISMATCH`,
    `ERR_CABIN_UNDERSTAFFED`, `ERR_STAFF_NOT_CLEARED`)".

    Design: Difficulty/priority_pair_validation_conflict/enroll_health_not_cleared_beats_cabin_understaffed
    """
    # cabin has no staff (would be understaffed) AND camper health PENDING (not cleared)
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000,
                                                  "counselor_camper_ratio": 6})
    gc = setup_bunked_application(env, deposit_cents=25_000, email="he2@x.com", clear_health=False)
    director = make_director_headers()
    resp = api_client.enroll_application(gc["application"]["id"], director)
    # health gate (p7) fires before understaffed gate (p8)
    validate_error(resp, ApiErrorId.ERR_HEALTH_NOT_CLEARED.value)


def test_enroll_flagged_health_and_understaffed_reports_health_first():
    """PRD §3.10: the order lists "the health and infirmary safety gates —
    EpiPen-required on submit and clear, cleared-required before enroll,
    swim-test-cleared for waterfront offerings" before "the eligibility and matching
    constraints — cabin gender and age band fit at submit, gender and age fit at bunk
    assignment, staffing ratio, and staff background clearance".

    Design: Difficulty/priority_pair_validation_conflict/enroll_health_not_cleared_beats_cabin_understaffed
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000,
                                                  "counselor_camper_ratio": 6})
    # bunked, health PENDING, cabin has no staff (understaffed once counted)
    gc = setup_bunked_application(env, deposit_cents=25_000, email="he4@x.com", clear_health=False)
    flag_health_form(gc["health_form"]["id"])  # health_status FLAGGED, still not cleared
    director = make_director_headers()
    resp = api_client.enroll_application(gc["application"]["id"], director)
    validate_error(resp, ApiErrorId.ERR_HEALTH_NOT_CLEARED.value)


# ===========================================================================
# Corner / cross_cutting_complexity_layers — derived field reconciliation
# ===========================================================================
def test_committed_count_reconciles_to_zero_after_withdraw():
    """PRD §3.4: "The `committed_count` is the number of applications for the session
    whose enrollment is `OFFERED`, `DEPOSIT_PAID`, or `ENROLLED` — that is, all
    applications currently holding a seat against capacity."
    PRD §3.6: "Withdrawing an `OFFERED` application simply decrements
    `committed_count`, freeing a seat."

    Design: Corner/cross_cutting_complexity_layers/derived_field_session_committed_count_reconciles_on_offer_and_withdraw
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000})
    gc = setup_submitted_application(env, email="cc1@x.com")
    director = make_director_headers()
    s1 = validate_success(api_client.get_session(env["session"]["id"], director))
    assert s1["committed_count"] == 1, s1["committed_count"]

    g_headers = make_guardian_headers(gc["guardian"]["id"])
    get_success_data(api_client.withdraw_application(gc["application"]["id"], g_headers))
    s2 = validate_success(api_client.get_session(env["session"]["id"], director))
    assert s2["committed_count"] == 0, s2["committed_count"]
    assert s2["waitlist_length"] == 0, s2["waitlist_length"]
