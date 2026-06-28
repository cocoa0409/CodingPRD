"""Application lifecycle: the protest branch fork/rejoin, the license renewal
cycle, and the invalid/terminal transition guards.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_applicant_headers,
    make_examiner_headers,
    ApiErrorId,
    setup_reference_data,
    create_submitted_application,
    setup_issued_license,
    setup_application_in_protest_period_with_filed_protest,
    setup_application_in_protest_hearing,
    schedule_hearing,
)

DIRECTOR = TEST_USERS["director_headers"]
EXAMINER = TEST_USERS["examiner_headers"]


# ─── Queue A: non_linear_state_machine ────────────────────────────────────
def test_protest_period_forks_to_protest_hearing_on_schedule(api):
    """PRD §3.5: "An `AdjudicationOfficer` schedules a hearing for a protest that
    is `FILED` while its application is in `PROTEST_PERIOD`; this moves the protest
    from `FILED` to `SCHEDULED`, creates a `Hearing` in `PENDING` whose identifier
    is recorded on the protest as `hearing_id`, and moves the application from
    `PROTEST_PERIOD` to `PROTEST_HEARING` — the fork distinct from `APPROVED`."

    Design: Difficulty/non_linear_state_machine/application_branch_fork_protest_period_to_approved_or_hearing
    """
    ref, app, protest = setup_application_in_protest_period_with_filed_protest(
        grounds="OVER_CONCENTRATION")
    scheduled = validate_success(api.schedule_hearing(
        protest["id"],
        {"room_code": "RM-1", "starts_at": "2026-01-10T09:00:00Z",
         "ends_at": "2026-01-10T11:00:00Z"},
        TEST_USERS["adjudication_officer_headers"]))
    assert scheduled["status"] == "SCHEDULED", f"protest status {scheduled['status']}"
    assert scheduled["hearing_id"], "hearing_id must be recorded on the protest"
    app_after = get_success_data(api.get_application(app["id"], DIRECTOR))
    assert app_after["status"] == "PROTEST_HEARING", (
        f"expected application PROTEST_HEARING, got {app_after['status']}"
    )


def test_protest_period_forks_to_approved_when_no_protest(api):
    """PRD §3.5: "If no protest stands in the way, a `Director` approves the
    application, advancing it from `PROTEST_PERIOD` to `APPROVED`."
    PRD §3.5: "the protest window must have fully elapsed — the current clock
    instant must be greater than or equal to `protest_period_ends_at`"

    The other fork from PROTEST_PERIOD: with no protest and the window elapsed,
    approve advances to APPROVED.

    Design: Difficulty/non_linear_state_machine/application_branch_fork_protest_period_to_approved_or_hearing
    """
    ref, app = create_submitted_application()
    from test_helpers import advance_to_protest_period
    advance_to_protest_period(ref, app)
    get_success_data(api.set_clock("2026-02-01T00:00:00Z", DIRECTOR))
    approved = validate_success(api.approve_application(app["id"], DIRECTOR))
    assert approved["status"] == "APPROVED", f"expected APPROVED, got {approved['status']}"


def test_license_renewal_cycle_active_to_renewal_due_to_active_twice(api):
    """PRD §3.8: "When the clock reaches `renewal_window_opens_at`, a re-evaluation
    flips an `ACTIVE` license to `RENEWAL_DUE` ... From `RENEWAL_DUE` the
    `Applicant` renews, returning the license to `ACTIVE`."
    PRD §3.8: "and `renewal_count` increments by one."

    The same license traverses ACTIVE -> RENEWAL_DUE -> ACTIVE twice;
    renewal_count climbs 0 -> 1 -> 2, proving the cycle is re-traversable.

    Design: Difficulty/non_linear_state_machine/license_renewal_cycle_active_to_renewal_due_to_active
    """
    bundle = setup_issued_license()
    lic_id = bundle["license"]["id"]
    owner = make_applicant_headers(bundle["ref"]["owner_id"])
    # First renewal: term [2026-02-01, 2027-02-01], window opens 2026-12-03.
    get_success_data(api.set_clock("2026-12-15T00:00:00Z", DIRECTOR))
    get_success_data(api.check_renewal_window(lic_id, EXAMINER))
    r1 = validate_success(api.renew_license(lic_id, {"renewal_fee_paid_cents": 100000}, owner))
    assert r1["renewal_count"] == 1
    # Second renewal: new term ends 2028-02-01, window opens 2027-12-03.
    get_success_data(api.set_clock("2027-12-15T00:00:00Z", DIRECTOR))
    get_success_data(api.check_renewal_window(lic_id, EXAMINER))
    r2 = validate_success(api.renew_license(lic_id, {"renewal_fee_paid_cents": 100000}, owner))
    assert r2["status"] == "ACTIVE", f"expected ACTIVE, got {r2['status']}"
    assert r2["renewal_count"] == 2, f"expected renewal_count 2, got {r2['renewal_count']}"


# ─── Queue B: state_machines ──────────────────────────────────────────────
def test_withdraw_draft_application_succeeds_no_slot_released(api):
    """PRD §3.2: "While in `DRAFT` it may be abandoned, transitioning straight to
    `WITHDRAWN`."

    A DRAFT application (never submitted, holding no quota slot) withdraws to
    WITHDRAWN with quota_slot_held false.

    Design: Corner/state_machines/withdraw_application_from_draft_succeeds
    """
    ref = setup_reference_data()
    owner = make_applicant_headers(ref["owner_id"])
    app = get_success_data(api.create_application(
        {"applicant_id": ref["owner_id"], "premise_id": ref["premise"]["id"],
         "license_class_code": "ON_47"}, owner))
    withdrawn = validate_success(api.withdraw_application(app["id"], owner))
    assert withdrawn["status"] == "WITHDRAWN", f"got {withdrawn['status']}"
    assert withdrawn["quota_slot_held"] is False


def test_begin_review_from_draft_returns_invalid_state(api):
    """PRD §2.8: "Whether the target is in a state from which the requested
    transition is defined is checked fourth, failing with `ERR_INVALID_STATE`
    (409)."
    PRD §3.4: "Once an application is `SUBMITTED`, a `LicensingExaminer` begins
    review, advancing it to `UNDER_REVIEW`."

    begin-review on a DRAFT (not SUBMITTED) application -> ERR_INVALID_STATE.

    Design: Corner/state_machines/begin_review_from_draft_returns_invalid_state
    """
    ref = setup_reference_data()
    owner = make_applicant_headers(ref["owner_id"])
    app = get_success_data(api.create_application(
        {"applicant_id": ref["owner_id"], "premise_id": ref["premise"]["id"],
         "license_class_code": "ON_47"}, owner))
    resp = api.begin_review(app["id"], EXAMINER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_withdraw_already_withdrawn_application_returns_invalid_state(api):
    """PRD §2.8: "Whether the target is in a state from which the requested
    transition is defined is checked fourth, failing with `ERR_INVALID_STATE`
    (409)."
    PRD §3.5: "The three terminal application states are `ISSUED`, `DENIED`, and
    `WITHDRAWN`."

    A second withdraw on an already-WITHDRAWN (terminal) application ->
    ERR_INVALID_STATE.

    Design: Corner/state_machines/withdraw_already_withdrawn_application_returns_invalid_state
    """
    ref = setup_reference_data()
    owner = make_applicant_headers(ref["owner_id"])
    app = get_success_data(api.create_application(
        {"applicant_id": ref["owner_id"], "premise_id": ref["premise"]["id"],
         "license_class_code": "ON_47"}, owner))
    get_success_data(api.withdraw_application(app["id"], owner))
    resp = api.withdraw_application(app["id"], owner)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_overrule_hearing_returns_application_to_protest_period(api):
    """PRD §3.5: "A `PROTEST_OVERRULED` outcome moves the hearing to
    `PROTEST_OVERRULED`, marks the protest `OVERRULED`, and returns the
    application from `PROTEST_HEARING` back to `PROTEST_PERIOD` so the `Director`
    may proceed to approve — the branch rejoin."

    Design: Corner/state_machines/overrule_hearing_returns_application_to_protest_period_branch_rejoin
    """
    ref, app, protest, hearing_id = setup_application_in_protest_hearing(
        grounds="MORAL_CHARACTER", room_code="RM-2",
        starts_at="2026-01-08T09:00:00Z", ends_at="2026-01-08T10:00:00Z")
    get_success_data(api.set_clock("2026-01-08T09:30:00Z", DIRECTOR))
    rendered = validate_success(api.render_hearing(
        hearing_id, {"outcome": "PROTEST_OVERRULED"},
        TEST_USERS["adjudication_officer_headers"]))
    assert rendered["outcome"] == "PROTEST_OVERRULED"
    protest_after = get_success_data(api.get_protest(protest["id"], DIRECTOR))
    assert protest_after["status"] == "OVERRULED", f"got {protest_after['status']}"
    app_after = get_success_data(api.get_application(app["id"], DIRECTOR))
    assert app_after["status"] == "PROTEST_PERIOD", f"got {app_after['status']}"
    assert app_after["quota_slot_held"] is True, "quota slot retained on rejoin"


def test_new_application_status_draft_system_minted(api):
    """PRD §3.2: "A freshly created application sits in `DRAFT` with no fee, no
    checks, and no quota reservation."
    PRD §2.4: "an integer `version` that begins at 1 on creation"

    POST /license-applications yields status DRAFT, version 1, fee_paid_cents 0,
    regardless of client input.

    Design: Corner/entities/application_id_is_system_minted_input_id_ignored
    """
    ref = setup_reference_data()
    owner = make_applicant_headers(ref["owner_id"])
    app = validate_success(api.create_application(
        {"applicant_id": ref["owner_id"], "premise_id": ref["premise"]["id"],
         "license_class_code": "ON_47"}, owner), expected_status=201)
    assert app["status"] == "DRAFT", f"expected DRAFT, got {app['status']}"
    assert app["version"] == 1, f"expected version 1, got {app['version']}"
    assert app["fee_paid_cents"] == 0, f"expected fee_paid_cents 0, got {app['fee_paid_cents']}"
