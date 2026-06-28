"""Parallel state axes, health-form revision loop, aid revoke revert, intake
promotion, and terminal/invalid-state lockdowns.

Difficulty queue: non_linear_state_machine. Corner queue: state_machines section.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_guardian_headers, make_director_headers,
    ApiErrorId,
    setup_enrolling_session, setup_enrolling_session_with_staffed_cabin,
    setup_submitted_application,
    register_guardian, make_camper, make_health_form, submit_health_form,
    flag_health_form, request_aid, approve_aid, make_activity, book_activity,
    api_client,
)


# ===========================================================================
# Difficulty / non_linear_state_machine
# ===========================================================================
def test_pay_deposit_advances_both_enroll_and_payment_axes():
    """PRD §3.6: "Paying a deposit on an `OFFERED` application moves it to
    `DEPOSIT_PAID`".
    PRD §3.6: "A successful deposit creates a `Payment` of kind `DEPOSIT` in
    `APPLIED` status, sets `deposit_paid_cents` to the camp's deposit amount, moves
    the payment axis to `DEPOSIT_SETTLED`, and recomputes both balances."

    Design: Difficulty/non_linear_state_machine/application_parallel_enroll_and_payment_axes
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000})
    gc = setup_submitted_application(env, email="px1@x.com")
    assert gc["application"]["enroll_status"] == "OFFERED"
    assert gc["application"]["payment_status"] == "DEPOSIT_DUE"
    g_headers = make_guardian_headers(gc["guardian"]["id"])

    data = validate_success(api_client.pay_deposit(
        gc["application"]["id"], {"amount_cents": 25_000}, g_headers))
    assert data["enroll_status"] == "DEPOSIT_PAID", data["enroll_status"]
    assert data["payment_status"] == "DEPOSIT_SETTLED", data["payment_status"]


def test_submit_routes_offered_with_payment_axis_deposit_due():
    """PRD §3.4: "If the session's `committed_count` is below `capacity`, a seat is
    available and the application is auto-routed to `OFFERED`".
    PRD §3.4: "When a submitted application is routed to `OFFERED`, the system sets
    `offer_expires_at` to the current clock plus the camp's `deposit_grace_days`, and
    the payment axis moves to `DEPOSIT_DUE` with the estimated balance recomputed."

    Design: Difficulty/non_linear_state_machine/application_parallel_enroll_and_payment_axes
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000})
    gc = setup_submitted_application(env, email="px2@x.com")
    # the two axes are observable independently on the same row after submit
    assert gc["application"]["enroll_status"] == "OFFERED", gc["application"]["enroll_status"]
    assert gc["application"]["payment_status"] == "DEPOSIT_DUE", gc["application"]["payment_status"]


def test_healthform_flagged_then_resubmit_returns_to_submitted_and_pending():
    """PRD §3.3: "A flagged form is corrected and resubmitted by the guardian,
    re-entering `SUBMITTED` and returning the camper to `PENDING` for re-review."
    PRD §3.3: "A successful submit sets the camper's `health_status` to `PENDING`."

    Design: Difficulty/non_linear_state_machine/healthform_flagged_resubmit_revision_cycle
    """
    guardian = register_guardian(email="hfr1@x.com")
    g_id = guardian["id"]
    camper = make_camper(g_id, full_name="Camper Five", age=9, gender="GIRL")
    hf = make_health_form(g_id, camper["id"])
    submit_health_form(g_id, hf["id"])
    flag_health_form(hf["id"], review_note="missing immunization record")

    # resubmit a FLAGGED form
    data = validate_success(api_client.submit_health_form(hf["id"], make_guardian_headers(g_id)))
    assert data["status"] == "SUBMITTED", data["status"]

    camper_after = validate_success(api_client.get_camper(camper["id"], make_director_headers()))
    assert camper_after["health_status"] == "PENDING", camper_after["health_status"]


def test_healthform_revision_loop_via_clear_after_resubmit():
    """PRD §3.3: "A flagged form is corrected and resubmitted by the guardian,
    re-entering `SUBMITTED` and returning the camper to `PENDING` for re-review."
    PRD §3.3: "Flagging instead moves the form to `FLAGGED`, sets the camper's
    `health_status` to `FLAGGED`, records the `review_note`, and carries no
    preconditions."

    Design: Difficulty/non_linear_state_machine/healthform_flagged_resubmit_revision_cycle
    """
    guardian = register_guardian(email="hfr2@x.com")
    g_id = guardian["id"]
    camper = make_camper(g_id, full_name="Camper Loop", age=10, gender="BOY")
    hf = make_health_form(g_id, camper["id"])
    submit_health_form(g_id, hf["id"])
    flagged = flag_health_form(hf["id"], review_note="needs revision")
    assert flagged["status"] == "FLAGGED"
    camper_flagged = validate_success(api_client.get_camper(camper["id"], make_director_headers()))
    assert camper_flagged["health_status"] == "FLAGGED"

    resubmitted = validate_success(api_client.submit_health_form(hf["id"], make_guardian_headers(g_id)))
    assert resubmitted["status"] == "SUBMITTED", resubmitted["status"]


# ===========================================================================
# Corner / state_machines
# ===========================================================================
def test_open_enrollment_with_no_cabins_rejected():
    """PRD §3.1: "Opening enrollment moves a session from `PLANNING` to `ENROLLING`;
    it requires that the session already have at least one cabin (otherwise
    `ERR_NO_CABINS`) and that `expected_session_version` match".

    Design: Corner/state_machines/open_enrollment_with_no_cabins_returns_no_cabins
    """
    director = make_director_headers()
    camp = get_success_data(api_client.create_camp({"name": "C"}, director))
    sess = get_success_data(api_client.create_session(
        camp["id"], {"name": "S", "starts_on": "2026-07-01T00:00:00Z",
                     "ends_on": "2026-07-14T00:00:00Z",
                     "visiting_day_on": "2026-07-07T00:00:00Z", "capacity": 10}, director))
    resp = api_client.open_enrollment(sess["id"], {"expected_session_version": sess["version"]}, director)
    validate_error(resp, ApiErrorId.ERR_NO_CABINS.value)


def test_session_start_before_starts_on_rejected():
    """PRD §3.1: "Starting a session moves it from `ENROLLING` to `RUNNING`: it
    requires that the logical clock have reached or passed `starts_on` (otherwise
    `ERR_SESSION_NOT_STARTED`)".

    Design: Corner/state_machines/session_start_before_starts_on_returns_not_started
    """
    env = setup_enrolling_session()  # clock 2026-04-01, starts_on 2026-07-01
    director = make_director_headers()
    resp = api_client.start_session(
        env["session"]["id"], {"expected_session_version": env["session"]["version"]}, director)
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_STARTED.value)


def test_drop_already_dropped_enrollment_rejected():
    """PRD §3.8: "Dropping a booking moves it from `BOOKED` to `DROPPED` and
    decrements the offering's `seats_taken`."
    PRD §2.5 / §3.10: "whether the target resource is in a valid state for the
    requested transition (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/drop_already_dropped_enrollment_returns_invalid_state
    """
    env = setup_enrolling_session()
    offering = make_activity(env["session"]["id"], name="Crafts", slot_day=1,
                             starts_minute=60, ends_minute=120, seat_capacity=5)
    gc = setup_submitted_application(env, email="dd1@x.com")
    g_id = gc["guardian"]["id"]
    ae = book_activity(g_id, offering["id"], gc["application"]["id"])
    get_success_data(api_client.drop_activity_enrollment(ae["id"], make_guardian_headers(g_id)))

    resp = api_client.drop_activity_enrollment(ae["id"], make_guardian_headers(g_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_submit_health_form_with_allergy_no_epipen_rejected():
    """PRD §3.3: "if `has_life_threatening_allergy` is true, then `epipen_on_file`
    must also be true, or the submit is refused with `ERR_EPIPEN_REQUIRED`."

    Design: Corner/state_machines/health_clear_with_allergy_no_epipen_returns_epipen_required
    """
    guardian = register_guardian(email="ep1@x.com")
    g_id = guardian["id"]
    camper = make_camper(g_id, full_name="Kid", age=10, gender="GIRL")
    hf = make_health_form(g_id, camper["id"],
                          has_life_threatening_allergy=True, epipen_on_file=False)
    resp = api_client.submit_health_form(hf["id"], make_guardian_headers(g_id))
    validate_error(resp, ApiErrorId.ERR_EPIPEN_REQUIRED.value)


# DELETED: test_aid_revoke_reverts_paid_in_full_to_balance_due
# PRD §3.7 (PRD.md line 186) is internally contradictory and does NOT uniquely
# determine the outcome (STEP 1b — ERROR PRECEDENCE / contradictory-precondition
# collapse). The same sentence states BOTH:
#   (a) "Revoking an approved award ... is permitted only when the application's
#       payment axis is not PAID_IN_FULL (otherwise ERR_INVALID_STATE)."
#   (b) "... if the resulting balance is now greater than zero while the payment
#       axis stood at PAID_IN_FULL — reverts the payment axis to BALANCE_DUE."
# Clause (a) makes clause (b)'s trigger ("while the payment axis stood at
# PAID_IN_FULL") unreachable. Two divergent PRD-faithful implementations both
# satisfy a cited sentence: (A) honor the explicit error-id-bearing precondition
# and return ERR_INVALID_STATE on a PAID_IN_FULL revoke (the natural reading of a
# binding precondition gate), vs (B) allow the revoke and revert to BALANCE_DUE.
# Per the cardinal rule, a test the PRD does not uniquely determine must be
# deleted. Scaffold rule that drove generation:
# Corner/state_machines/aid_revoke_reverts_paid_in_full_to_balance_due.


def test_run_intake_promotes_earliest_waitlisted_into_freed_seat():
    """PRD §3.4: "while `committed_count` remains below `capacity`, the system
    promotes the earliest-submitted waitlisted application — ordered by `submitted_at`
    ascending, breaking ties by earliest `created_at` — from `WAITLISTED` to
    `OFFERED`".
    PRD §3.6: "Withdrawing an `OFFERED` application simply decrements
    `committed_count`, freeing a seat."

    Design: Corner/state_machines/run_intake_promotes_earliest_waitlisted_into_freed_seat
    """
    env = setup_enrolling_session(
        camp_overrides={"deposit_cents": 25_000},
        session_overrides={"capacity": 1},
    )
    # App A submitted first -> OFFERED; App B submitted second -> WAITLISTED.
    gc_a = setup_submitted_application(env, email="wa@x.com")
    assert gc_a["application"]["enroll_status"] == "OFFERED"
    gc_b = setup_submitted_application(env, email="wb@x.com")
    assert gc_b["application"]["enroll_status"] == "WAITLISTED"

    # withdraw A (frees the only seat), then run intake
    g_a = make_guardian_headers(gc_a["guardian"]["id"])
    get_success_data(api_client.withdraw_application(gc_a["application"]["id"], g_a))
    director = make_director_headers()
    session_after = validate_success(api_client.run_intake(env["session"]["id"], director))

    app_b = validate_success(api_client.get_application(
        gc_b["application"]["id"], make_guardian_headers(gc_b["guardian"]["id"])))
    assert app_b["enroll_status"] == "OFFERED", app_b["enroll_status"]
    assert session_after["waitlist_length"] == 0, session_after["waitlist_length"]
    assert session_after["committed_count"] == 1, session_after["committed_count"]


def test_terminal_withdrawn_application_cannot_pay_deposit():
    """PRD §3.6: "A withdrawn application is terminal."
    PRD §3.10: "whether the target resource is in a valid state for the requested
    transition (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/terminal_withdrawn_application_cannot_pay_deposit
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000})
    gc = setup_submitted_application(env, email="tw1@x.com")
    g_headers = make_guardian_headers(gc["guardian"]["id"])
    get_success_data(api_client.withdraw_application(gc["application"]["id"], g_headers))

    resp = api_client.pay_deposit(gc["application"]["id"], {"amount_cents": 25_000}, g_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
