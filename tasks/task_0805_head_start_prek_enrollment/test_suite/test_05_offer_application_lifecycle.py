"""Offer and application lifecycle: the waitlist<->offer cycle, offer-state guards,
expiry, and ownership (PRD §3.3, §3.4, §3.5, §2.1).

Depth coverage for the non-linear WAITLISTED->OFFERED->WAITLISTED->OFFERED cycle;
breadth coverage for accept-not-pending, accept-after-expiry, not-owner, and the
invalid pre-verify/pre-waitlist transitions.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_family_headers,
    setup_offered_application, setup_active_enrollment,
    create_program, create_cohort, create_family, create_application,
    run_selection, cohort_version, set_clock,
)

ES = TEST_USERS["enrollment_specialist_headers"]
PA = TEST_USERS["program_admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / application_waitlist_offer_waitlist_cycle
# ---------------------------------------------------------------------------
def test_decline_returns_application_to_waitlist(api):
    """PRD §3.5: "Declining an offer, also a `Family` action, advances the offer from
    `PENDING` to `DECLINED` and returns the application from `OFFERED` to `WAITLISTED`,
    so the application re-enters the waitlist pool".

    Design: Difficulty/non_linear_state_machine/application_waitlist_offer_waitlist_cycle
    """
    b = setup_offered_application()
    offer = validate_success(
        api.decline_offer(b["offer"]["id"], make_family_headers(b["family"]["id"])))
    assert offer["status"] == "DECLINED"
    app = validate_success(api.get_application(b["application"]["id"], ES))
    assert app["status"] == "WAITLISTED"


def test_reselection_reoffers_after_decline(api):
    """PRD §3.4: "For each selected application the system creates an `Offer` in `PENDING`
    status, stamps its `offered_at` with the current clock and its `offer_expires_at` at
    `offered_at` advanced by the fixed offer window of `OFFER_WINDOW_DAYS` days, and
    advances the application from `WAITLISTED` to `OFFERED`."

    Design: Difficulty/non_linear_state_machine/application_waitlist_offer_waitlist_cycle
    """
    b = setup_offered_application()
    api.decline_offer(b["offer"]["id"], make_family_headers(b["family"]["id"]))
    run_selection(b["cohort"]["id"])
    app = validate_success(api.get_application(b["application"]["id"], ES))
    assert app["status"] == "OFFERED"


# ---------------------------------------------------------------------------
# Corner: state_machines / accept_twice_second_returns_offer_not_pending
# ---------------------------------------------------------------------------
def test_accept_already_accepted_offer_returns_not_pending(api):
    """PRD §3.5: "Acceptance requires the offer to be `PENDING`; an accept or decline
    against a non-pending offer is rejected with `ERR_OFFER_NOT_PENDING`."

    Design: Corner/state_machines/accept_twice_second_returns_offer_not_pending
    """
    b = setup_active_enrollment()  # offer already ACCEPTED
    version = cohort_version(b["cohort"]["id"])
    resp = api.accept_offer(
        b["offer"]["id"], {"expected_cohort_version": version},
        make_family_headers(b["family"]["id"]))
    validate_error(resp, ApiErrorId.ERR_OFFER_NOT_PENDING)


# ---------------------------------------------------------------------------
# Corner: validations / accept_after_expiry_returns_offer_expired
# ---------------------------------------------------------------------------
def test_accept_after_expiry_returns_offer_expired(api):
    """PRD §3.5: "Acceptance also requires the current clock to be strictly before
    `offer_expires_at`; at or after that instant the acceptance is rejected with
    `ERR_OFFER_EXPIRED`."

    Design: Corner/validations/accept_after_expiry_returns_offer_expired
    """
    b = setup_offered_application()
    version = cohort_version(b["cohort"]["id"])
    # Drive expiry off the offer's own offer_expires_at rather than a hardcoded
    # window length: PRD leaves OFFER_WINDOW_DAYS numerically unspecified, so at
    # (or after) that returned instant the acceptance must be rejected.
    set_clock(b["offer"]["offer_expires_at"])
    resp = api.accept_offer(
        b["offer"]["id"], {"expected_cohort_version": version},
        make_family_headers(b["family"]["id"]))
    validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED)


# ---------------------------------------------------------------------------
# Corner: rbac / family_accepting_other_familys_offer_returns_not_owner
# ---------------------------------------------------------------------------
def test_family_accepting_other_familys_offer_returns_not_owner(api):
    """PRD §2.1: "If a `Family` acts on an application, offer, or enrollment that its
    household does not own, the request is rejected with `ERR_NOT_OWNER`."

    Design: Corner/rbac/family_accepting_other_familys_offer_returns_not_owner
    """
    b = setup_offered_application()  # offer owned by family B
    other_family = create_family(guardian_name="A", household_size=4,
                                 annual_income_cents=1400000, categorical_eligibility="SNAP")
    version = cohort_version(b["cohort"]["id"])
    resp = api.accept_offer(
        b["offer"]["id"], {"expected_cohort_version": version},
        make_family_headers(other_family["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_OWNER)


# ---------------------------------------------------------------------------
# Corner: state_machines / waitlist_from_draft_returns_not_eligible
# ---------------------------------------------------------------------------
def _draft_application():
    program = create_program()
    cohort = create_cohort(program["id"])
    family = create_family(categorical_eligibility="TANF")
    return create_application(program["id"], cohort["id"], family["id"], child_dob="2022-01-10")


def test_waitlist_on_draft_returns_not_eligible(api):
    """PRD §3.4: "Waitlisting requires the application to be in `ELIGIBLE`; otherwise it
    is rejected with `ERR_APPLICATION_NOT_ELIGIBLE`."

    Design: Corner/state_machines/waitlist_from_draft_returns_not_eligible
    """
    app = _draft_application()
    resp = api.waitlist_application(app["id"], ES)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_ELIGIBLE)


def test_verify_on_draft_returns_not_submitted(api):
    """PRD §3.3: "Verifying eligibility, an action reserved to an `EnrollmentSpecialist`,
    is permitted only when the application is in `SUBMITTED`; otherwise it is rejected
    with `ERR_APPLICATION_NOT_SUBMITTED`."

    Design: Corner/state_machines/verify_from_draft_returns_not_submitted
    """
    app = _draft_application()
    resp = api.verify_eligibility(app["id"], {"verified_income_cents": 800000}, ES)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_SUBMITTED)
