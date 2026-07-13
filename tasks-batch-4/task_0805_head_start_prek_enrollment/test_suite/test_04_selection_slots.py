"""Selection runs, slot-accounting cascades, conserved invariants, and OCC
(PRD §2.5, §2.6, §3.4, §3.5, §3.9).

Depth coverage for the accept/decline cascades into cohort accounting, the
cross-entity cohort-OPEN gate on selection, and the compensating filled/reserved
invariants; breadth coverage for the stale-version reject and disenroll
reconciliation.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_family_headers,
    setup_offered_application, setup_active_enrollment, setup_two_offered_applications,
    setup_program_and_cohort, add_waitlisted_applicant,
    create_program, create_cohort, create_family, create_application,
    submit_application, verify_application, run_selection, offer_id_for_application,
    accept_offer,
)

ES = TEST_USERS["enrollment_specialist_headers"]
PA = TEST_USERS["program_admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / accept_offer_cascade_to_cohort_accounting
# ---------------------------------------------------------------------------
def test_accept_drives_offer_accepted_and_application_enrolled(api):
    """PRD §3.5: "Accepting an offer advances it from `PENDING` to `ACCEPTED` and drives
    the associated application from `OFFERED` to `ENROLLED`."

    Design: Difficulty/transitive_cascade/accept_offer_cascade_to_cohort_accounting
    """
    b = setup_offered_application()
    offer = accept_offer(b["offer"]["id"], b["family"]["id"])
    assert offer["status"] == "ACCEPTED"
    app = validate_success(api.get_application(b["application"]["id"], ES))
    assert app["status"] == "ENROLLED"


def test_accept_raises_filled_and_lowers_reserved_slots(api):
    """PRD §3.5: "On a successful acceptance the system creates an `Enrollment` with
    `status` `ACTIVE` and `health_compliance_status` `PENDING`, stamps its `enrolled_at`
    with the current clock, records the enrollment's `application_id` and `cohort_id`,
    raises the cohort's `filled_slots` (recomputed, +1) and lowers its `reserved_slots`
    (recomputed, −1), and increments `AgeCohort.version` by one."

    Design: Difficulty/transitive_cascade/accept_offer_cascade_to_cohort_accounting
    """
    b = setup_offered_application()
    accept_offer(b["offer"]["id"], b["family"]["id"])
    cohort = validate_success(api.get_cohort(b["cohort"]["id"], PA))
    assert cohort["filled_slots"] == 1
    assert cohort["reserved_slots"] == 0


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / decline_offer_cascade_releases_reservation
# ---------------------------------------------------------------------------
def test_decline_drives_offer_declined_and_application_waitlisted(api):
    """PRD §3.5: "Declining an offer, also a `Family` action, advances the offer from
    `PENDING` to `DECLINED` and returns the application from `OFFERED` to `WAITLISTED`,
    so the application re-enters the waitlist pool; the cohort's `reserved_slots` is
    recomputed downward and `AgeCohort.version` increments by one."

    Design: Difficulty/transitive_cascade/decline_offer_cascade_releases_reservation
    """
    b = setup_offered_application()
    offer = validate_success(
        api.decline_offer(b["offer"]["id"], make_family_headers(b["family"]["id"])))
    assert offer["status"] == "DECLINED"
    app = validate_success(api.get_application(b["application"]["id"], ES))
    assert app["status"] == "WAITLISTED"


def test_decline_releases_reservation_back_to_available(api):
    """PRD §2.5: "Its `reserved_slots` is the count of `Offer` records for that cohort
    whose `status` is `PENDING`. Its `available_slots` is `funded_slots` minus
    `filled_slots` minus `reserved_slots`".

    Design: Difficulty/transitive_cascade/decline_offer_cascade_releases_reservation
    """
    b = setup_offered_application()
    api.decline_offer(b["offer"]["id"], make_family_headers(b["family"]["id"]))
    cohort = validate_success(api.get_cohort(b["cohort"]["id"], PA))
    assert cohort["reserved_slots"] == 0
    assert cohort["available_slots"] == 2


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / waitlisted_offer_gated_by_cohort_open
# ---------------------------------------------------------------------------
def _one_slot_cohort_with_two_waitlisted():
    program, cohort = setup_program_and_cohort(cohort_overrides={"funded_slots": 1})
    famC, appC = add_waitlisted_applicant(
        program, cohort,
        family_overrides={"guardian_name": "C", "household_size": 5,
                          "annual_income_cents": 1000000, "categorical_eligibility": "NONE",
                          "homeless_status": True},
        app_overrides={"child_first_name": "Ci", "child_last_name": "C",
                       "child_dob": "2022-03-05"},
        verified_income_cents=1000000)
    famB, appB = add_waitlisted_applicant(
        program, cohort,
        family_overrides={"guardian_name": "B", "household_size": 3,
                          "annual_income_cents": 800000, "categorical_eligibility": "TANF"},
        app_overrides={"child_first_name": "Bo", "child_last_name": "B",
                       "child_dob": "2022-01-10"},
        verified_income_cents=800000)
    run_selection(cohort["id"])  # reserves the single slot for the higher-ranked appC
    return program, cohort, appC, appB


def test_full_cohort_blocks_lower_ranked_from_offer(api):
    """PRD §3.4: "Selection proceeds only while the cohort's `selection_status` is `OPEN`
    (equivalently, while `available_slots` is greater than zero)."
    PRD §3.4: "The run ranks the eligible `WAITLISTED` pool by `priority_points` in
    descending order, breaking ties by earliest `submitted_at` and then by earliest
    `created_at`, and selects the top applications up to the number of currently
    available slots."

    Design: Difficulty/cross_entity_state_dependency/waitlisted_offer_gated_by_cohort_open
    """
    program, cohort, appC, appB = _one_slot_cohort_with_two_waitlisted()
    run_selection(cohort["id"])  # re-run: cohort is FULL, no new offer
    c_status = validate_success(api.get_application(appC["id"], ES))["status"]
    b_status = validate_success(api.get_application(appB["id"], ES))["status"]
    assert c_status == "OFFERED"
    assert b_status == "WAITLISTED"


def test_full_cohort_selection_status_is_full(api):
    """PRD §2.5: "When slot accounting drops `available_slots` to zero the cohort's
    `selection_status` becomes `FULL`, which blocks further selection; when a freed slot
    lifts `available_slots` back above zero the `selection_status` returns to `OPEN`."

    Design: Difficulty/cross_entity_state_dependency/waitlisted_offer_gated_by_cohort_open
    """
    program, cohort, appC, appB = _one_slot_cohort_with_two_waitlisted()
    run_selection(cohort["id"])
    data = validate_success(api.get_cohort(cohort["id"], PA))
    assert data["selection_status"] == "FULL"


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / filled_slots_conserved_across_accept_then_withdraw
# ---------------------------------------------------------------------------
def test_withdraw_enrollment_returns_filled_slots_to_zero(api):
    """PRD §3.9: "A `Family` (on its own household), an `EnrollmentSpecialist`, or a
    `ProgramAdmin` may withdraw an active enrollment, advancing it from `ACTIVE` to the
    terminal `WITHDRAWN` state; this also drives the enrollment's linked application
    (through `application_id`) to `WITHDRAWN`, lowers the cohort's `filled_slots`, and
    increments `AgeCohort.version` by one."

    Design: Difficulty/compensating_invariant/filled_slots_conserved_across_accept_then_withdraw
    """
    b = setup_active_enrollment()
    validate_success(api.withdraw_enrollment(b["enrollment"]["id"], PA))
    cohort = validate_success(api.get_cohort(b["cohort"]["id"], PA))
    assert cohort["filled_slots"] == 0


def test_withdraw_enrollment_restores_full_availability(api):
    """PRD §2.5: "Its `filled_slots` is the count of `Enrollment` records for that cohort
    whose `status` is `ACTIVE`."
    PRD §2.5: "Its `available_slots` is `funded_slots` minus `filled_slots` minus
    `reserved_slots`, and by construction of the accounting it is never negative."

    Design: Difficulty/compensating_invariant/filled_slots_conserved_across_accept_then_withdraw
    """
    b = setup_active_enrollment()
    api.withdraw_enrollment(b["enrollment"]["id"], PA)
    cohort = validate_success(api.get_cohort(b["cohort"]["id"], PA))
    assert cohort["available_slots"] == 2


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / reserved_slots_conserved_across_offer_then_decline
# ---------------------------------------------------------------------------
def test_decline_returns_reserved_slots_to_zero(api):
    """PRD §2.5: "Its `reserved_slots` is the count of `Offer` records for that cohort
    whose `status` is `PENDING`."
    PRD §3.5: "the cohort's `reserved_slots` is recomputed downward and
    `AgeCohort.version` increments by one."

    Design: Difficulty/compensating_invariant/reserved_slots_conserved_across_offer_then_decline
    """
    b = setup_offered_application()
    api.decline_offer(b["offer"]["id"], make_family_headers(b["family"]["id"]))
    cohort = validate_success(api.get_cohort(b["cohort"]["id"], PA))
    assert cohort["reserved_slots"] == 0


def test_decline_restores_full_availability(api):
    """PRD §2.5: "Its `available_slots` is `funded_slots` minus `filled_slots` minus
    `reserved_slots`, and by construction of the accounting it is never negative."

    Design: Difficulty/compensating_invariant/reserved_slots_conserved_across_offer_then_decline
    """
    b = setup_offered_application()
    api.decline_offer(b["offer"]["id"], make_family_headers(b["family"]["id"]))
    cohort = validate_success(api.get_cohort(b["cohort"]["id"], PA))
    assert cohort["available_slots"] == 2


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / run_selection_empty_eligible_pool_returns_error
# ---------------------------------------------------------------------------
def test_run_selection_no_applications_returns_no_eligible(api):
    """PRD §3.4: "The run requires at least one eligible `WAITLISTED` application in that
    cohort's pool; against an empty eligible pool it is rejected with
    `ERR_NO_ELIGIBLE_APPLICANTS`."

    Design: Difficulty/boundary_precision_check/run_selection_empty_eligible_pool_returns_error
    """
    program, cohort = setup_program_and_cohort(cohort_overrides={"funded_slots": 2})
    resp = api.run_selection(cohort["id"], PA)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_APPLICANTS)


def test_run_selection_only_eligible_not_waitlisted_returns_no_eligible(api):
    """PRD §3.4: "The run requires at least one eligible `WAITLISTED` application in that
    cohort's pool; against an empty eligible pool it is rejected with
    `ERR_NO_ELIGIBLE_APPLICANTS`."

    Design: Difficulty/boundary_precision_check/run_selection_empty_eligible_pool_returns_error
    """
    program, cohort = setup_program_and_cohort(cohort_overrides={"funded_slots": 2})
    family = create_family(categorical_eligibility="TANF")
    app = create_application(program["id"], cohort["id"], family["id"], child_dob="2022-01-10")
    submit_application(app["id"])
    verify_application(app["id"], 800000)  # ELIGIBLE but never waitlisted
    resp = api.run_selection(cohort["id"], PA)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_APPLICANTS)


# ---------------------------------------------------------------------------
# Corner: cross_cutting / offer_accept_stale_cohort_version_returns_412
# ---------------------------------------------------------------------------
def test_second_accept_with_stale_cohort_version_rejected(api):
    """PRD §2.6: "If `expected_cohort_version` does not equal the cohort's current
    `version` — because another writer has advanced it since the client last read the
    cohort, whether by committing another acceptance or by freeing a slot through a
    decline, expiry, or withdrawal — the acceptance is rejected with `ERR_STALE_VERSION`
    and HTTP status 412."

    Design: Corner/cross_cutting/offer_accept_stale_cohort_version_returns_412
    """
    b = setup_two_offered_applications(cohort_funded_slots=2)
    # First accept uses the pre-accept version and succeeds, bumping AgeCohort.version.
    accept_offer(b["offerB"], b["famB"]["id"], version=b["version_before"])
    # Second accept still carries the now-stale pre-accept version.
    resp = api.accept_offer(
        b["offerA"], {"expected_cohort_version": b["version_before"]},
        make_family_headers(b["famA"]["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


# ---------------------------------------------------------------------------
# Corner: cross_cutting / cohort_filled_slots_reconciled_after_disenroll
# ---------------------------------------------------------------------------
def test_disenroll_reconciles_filled_and_available_slots(api):
    """PRD §3.9: "A `ProgramAdmin` may administratively disenroll an active enrollment,
    optionally supplying a `reason`; disenrollment advances the enrollment from `ACTIVE`
    to the terminal `DISENROLLED` state, lowers the cohort's `filled_slots`, and
    increments `AgeCohort.version` by one."

    Design: Corner/cross_cutting/cohort_filled_slots_reconciled_after_disenroll
    """
    b = setup_active_enrollment()
    validate_success(api.disenroll(b["enrollment"]["id"], {"reason": "chronic_absence"}, PA))
    cohort = validate_success(api.get_cohort(b["cohort"]["id"], PA))
    assert cohort["filled_slots"] == 0
    assert cohort["available_slots"] == 2
