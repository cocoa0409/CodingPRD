"""Lifecycle transitions, guarded windows and terminal-state lockdown.

The server is relaunched with an empty store before every test, so each test
builds its own preconditions through the API, drives exactly one declared
transition, and reads the affected rows back to confirm the transition's own
side effects — including the rows a cascade reached that the caller never named.
"""
from datetime import datetime

from prd_bench_local_runner.testing import (
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

from test_helpers import factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_advertisement,
    assert_examination_inquiry,
    assert_license_registration,
    assert_loan_application,
    assert_pricing_exception,
    assert_sponsorship_transfer,
)
from test_helpers.constants import CLOCK_STARTUP_INSTANT
from test_helpers.fixtures import (
    create_originator,
    draft_advertisement,
    file_response,
    get_license,
    get_originator,
    license_status_action,
    log_inquiry,
    relinquish_sponsorship,
    request_pricing_exception,
    set_clock,
    setup_authorized_originator,
    setup_locked_loan,
)
from test_helpers.test_users import (
    analyst_headers,
    examiner_headers,
    make_originator_headers,
    officer_headers,
)


def _instant(value):
    """Parse an ISO 8601 UTC instant so two renderings of one instant compare equal."""
    assert value is not None, "expected an ISO 8601 instant, found null"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_taken_application_starts_in_taken_with_not_applicable_compensation(api):
    """PRD 3.4: "A successfully taken application stamps `application_taken_at` from the
    logical clock — this is the instant the authority window check was evaluated against,
    and it is recorded so that a later examination can reconstruct the decision — and
    initialises `status` to `TAKEN`, `compensation_status` to `NOT_APPLICABLE` and
    `authority_flag` to `VERIFIED`."
    PRD 3.4: "Its `note_rate_bps` and `locked_amount_cents` read null while the loan is
    `TAKEN`; its `funded_amount_cents`, `funded_at`, `payoff_date` and `closed_unit_index`
    read null until the loan closes or pays off; its `compensation_plan_id` reads null until
    close; and its `lender_paid_comp_cents`, `borrower_paid_comp_cents`,
    `file_quality_score` and `hours_worked_pct` all read `0` until they are reported at
    close."
    PRD 2.5: "a `version` integer that starts at `1` when the row is created and increments
    by exactly one on every mutation of that row."

    Design: Corner/state_machines/loan_application_starts_in_taken_with_not_applicable_compensation
    """
    context = setup_authorized_originator(api)
    originator = context["originator"]
    payload = factories.build_loan_application(
        originator["id"], state_code=context["state_code"]
    )

    response = api.create_loan_application(payload, make_originator_headers(originator["id"]))

    loan = validate_success(response, 201)
    assert_loan_application(loan)
    assert loan["status"] == "TAKEN", f"a fresh application must read TAKEN: {loan['status']}"
    assert loan["compensation_status"] == "NOT_APPLICABLE", (
        f"the compensation dimension must start NOT_APPLICABLE: {loan['compensation_status']}"
    )
    assert loan["authority_flag"] == "VERIFIED", (
        f"intake passed the authority check, so authority_flag is VERIFIED: {loan['authority_flag']}"
    )
    assert loan["note_rate_bps"] is None, "note_rate_bps reads null while the loan is TAKEN"
    assert loan["locked_amount_cents"] is None, (
        "locked_amount_cents reads null while the loan is TAKEN"
    )
    assert loan["funded_amount_cents"] is None, "funded_amount_cents reads null until close"
    assert loan["funded_at"] is None, "funded_at reads null until close"
    assert loan["payoff_date"] is None, "payoff_date reads null until a payoff is posted"
    assert loan["closed_unit_index"] is None, "closed_unit_index is null until the loan closes"
    assert loan["compensation_plan_id"] is None, "compensation_plan_id reads null until close"
    assert loan["lender_paid_comp_cents"] == 0, "lender_paid_comp_cents reads 0 before close"
    assert loan["borrower_paid_comp_cents"] == 0, "borrower_paid_comp_cents reads 0 before close"
    assert loan["file_quality_score"] == 0, "file_quality_score reads 0 before close"
    assert loan["hours_worked_pct"] == 0, "hours_worked_pct reads 0 before close"
    assert loan["version"] == 1, f"a freshly created row is at version 1: {loan['version']}"
    assert _instant(loan["application_taken_at"]) == _instant(CLOCK_STARTUP_INSTANT), (
        "application_taken_at is stamped from the logical clock: "
        f"{loan['application_taken_at']}"
    )


def test_renewal_request_moves_active_license_to_renewal_pending_and_keeps_authority(api):
    """PRD 3.2: "A `LicensingAnalyst` opens the cycle by filing a renewal request, advancing
    the licence `ACTIVE → RENEWAL_PENDING`."
    PRD 3.2: "Filing the request recomputes `ce_hours_applied` and `ce_satisfied` using
    `CALENDAR_YEAR_ATTRIBUTION`, and it deliberately leaves `authorized_state_codes`
    unchanged, because `RENEWAL_PENDING` counts as an authorising status exactly as `ACTIVE`
    does."
    PRD 2.8: "and by the computed authority read, which reports `originator_id`, the instant
    it evaluated as `as_of`, the resulting `authorized_state_codes`, and the originator's
    `employment_status`."

    Design: Corner/state_machines/renewal_request_moves_active_license_to_renewal_pending
    """
    context = setup_authorized_originator(api)
    licence_before = context["license"]
    originator_id = context["originator"]["id"]
    set_clock(api, "2026-11-15T00:00:00Z")

    response = api.create_renewal_request(licence_before["id"], analyst_headers())

    licence = validate_success(response, 200)
    assert_license_registration(licence)
    assert licence["status"] == "RENEWAL_PENDING", (
        f"a filed renewal request advances ACTIVE -> RENEWAL_PENDING: {licence['status']}"
    )
    assert licence["ce_hours_applied"] == 0, (
        f"no credits were filed, so the recomputed total is 0: {licence['ce_hours_applied']}"
    )
    assert licence["ce_satisfied"] is False, (
        f"zero hours cannot satisfy the requirement: {licence['ce_satisfied']}"
    )
    assert _instant(licence["expiration_date"]) == _instant(licence_before["expiration_date"]), (
        "the request does not roll the expiry forward: "
        f"{licence['expiration_date']} != {licence_before['expiration_date']}"
    )
    assert _instant(licence["authority_effective_at"]) == _instant(
        licence_before["authority_effective_at"]
    ), "authority never lapsed, so authority_effective_at is untouched by the request"

    authority = validate_success(
        api.get_originator_authority(originator_id, analyst_headers()), 200
    )
    assert authority["originator_id"] == originator_id
    assert authority["authorized_state_codes"] == [context["state_code"]], (
        "RENEWAL_PENDING authorises exactly as ACTIVE does: "
        f"{authority['authorized_state_codes']}"
    )
    assert _instant(authority["as_of"]) == _instant("2026-11-15T00:00:00Z"), (
        f"the read evaluates at the current logical clock instant: {authority['as_of']}"
    )
    assert authority["employment_status"] == "EMPLOYED"


def test_renewal_request_before_window_opens_is_rejected_and_leaves_license_active(api):
    """PRD 3.2: "This requires the licence to be `ACTIVE` and the logical clock instant to
    fall at or after `renewal_window_opens_at` and strictly before `expiration_date`; an
    attempt outside that window is rejected with `ERR_RENEWAL_WINDOW_CLOSED` (HTTP 422)."

    Design: Corner/state_machines/renewal_request_before_window_opens_returns_renewal_window_closed
    """
    context = setup_authorized_originator(api)
    licence_id = context["license"]["id"]
    assert _instant(context["license"]["renewal_window_opens_at"]) == _instant(
        "2026-11-01T00:00:00Z"
    ), "the filed renewal window is the one this test steps just short of"
    set_clock(api, "2026-10-31T00:00:00Z")

    response = api.create_renewal_request(licence_id, analyst_headers())

    validate_error(response, ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED.value)
    licence = get_license(api, licence_id)
    assert licence["status"] == "ACTIVE", (
        f"the rejected request applied no transition: {licence['status']}"
    )


def test_withdrawing_a_locked_loan_cascades_its_submitted_pricing_exception(api):
    """PRD 3.4: "Withdrawal cascades to pricing: every pricing exception on that loan whose
    `status` is `SUBMITTED` moves to `WITHDRAWN` as well, and the loan's
    `compensation_status` is set to `NOT_APPLICABLE`."
    PRD 3.6: "A filed exception starts in `SUBMITTED` with `comp_impact_cents` at `0`,
    `requested_by_user_id` stamped from the filing originator's `X-User-ID`, and
    `decided_by_user_id`, `second_decided_by_user_id`, `decided_at` and `decision_note` all
    null."

    Design: Corner/state_machines/withdraw_loan_cascades_submitted_pricing_exception_to_withdrawn
    """
    context = setup_locked_loan(api)
    originator_id = context["originator"]["id"]
    loan_id = context["loan"]["id"]
    exception = request_pricing_exception(
        api,
        loan_id,
        originator_id,
        requested_rate_bps=620,
        concession_cents=150_000,
    )
    assert exception["status"] == "SUBMITTED", (
        f"a filed exception starts in SUBMITTED: {exception['status']}"
    )
    assert exception["requires_second_approval"] is False, (
        "the originator is under STANDARD supervision when the exception is filed"
    )
    assert exception["comp_impact_cents"] == 0

    response = api.withdraw_loan_application(loan_id, make_originator_headers(originator_id))

    loan = validate_success(response, 200)
    assert_loan_application(loan)
    assert loan["status"] == "WITHDRAWN", (
        f"withdrawal is available from LOCKED: {loan['status']}"
    )
    assert loan["compensation_status"] == "NOT_APPLICABLE", (
        f"withdrawal resets the compensation dimension: {loan['compensation_status']}"
    )

    after = validate_success(api.get_pricing_exception(exception["id"], officer_headers()), 200)
    assert_pricing_exception(after)
    assert after["status"] == "WITHDRAWN", (
        f"the loan's SUBMITTED exception is cascaded to WITHDRAWN: {after['status']}"
    )
    assert after["comp_impact_cents"] == 0, (
        f"a withdrawn exception never touches compensation: {after['comp_impact_cents']}"
    )


def test_info_request_extends_the_response_deadline_by_fourteen_days(api):
    """PRD 3.9: "While `response_round_count` is fewer than three, the inquiry advances
    `RESPONSE_SUBMITTED → INFO_REQUESTED` and its `response_due_at` is reset to the logical
    clock instant plus fourteen days, opening a new response round."
    PRD 3.9: "Every entry into `RESPONSE_SUBMITTED` increments `response_round_count` by one
    — including the cyclic re-entries described next — and stamps `last_response_at` from the
    logical clock."

    Design: Corner/state_machines/info_request_extends_response_deadline_by_fourteen_days
    """
    inquiry = log_inquiry(api, state_code="CA", response_due_at="2026-09-01T00:00:00Z")
    assert _instant(inquiry["opened_at"]) == _instant(CLOCK_STARTUP_INSTANT)
    set_clock(api, "2026-08-05T00:00:00Z")
    round_one = file_response(api, inquiry["id"])
    assert round_one["status"] == "RESPONSE_SUBMITTED", (
        f"the first response advances OPEN -> RESPONSE_SUBMITTED: {round_one['status']}"
    )
    assert round_one["response_round_count"] == 1, (
        f"the first entry into RESPONSE_SUBMITTED counts one round: {round_one}"
    )
    assert _instant(round_one["last_response_at"]) == _instant("2026-08-05T00:00:00Z")
    set_clock(api, "2026-08-06T00:00:00Z")

    response = api.create_examination_info_request(
        inquiry["id"], factories.build_examination_info_request(), examiner_headers()
    )

    requested = validate_success(response, 200)
    assert_examination_inquiry(requested)
    assert requested["status"] == "INFO_REQUESTED", (
        f"below the round limit the inquiry moves to INFO_REQUESTED: {requested['status']}"
    )
    assert _instant(requested["response_due_at"]) == _instant("2026-08-20T00:00:00Z"), (
        "the deadline is reset to the clock instant plus fourteen days: "
        f"{requested['response_due_at']}"
    )
    assert requested["response_round_count"] == 1, (
        f"an info request is not a response round: {requested['response_round_count']}"
    )
    assert requested["escalation_reason"] is None, (
        f"the inquiry has not escalated: {requested['escalation_reason']}"
    )

    round_two = file_response(api, inquiry["id"])
    assert round_two["status"] == "RESPONSE_SUBMITTED", (
        f"the cycle re-enters RESPONSE_SUBMITTED: {round_two['status']}"
    )
    assert round_two["response_round_count"] == 2, (
        f"the cyclic re-entry raises the round count to 2: {round_two['response_round_count']}"
    )
    assert _instant(round_two["last_response_at"]) == _instant("2026-08-06T00:00:00Z")


def test_publishing_a_draft_advertisement_is_an_invalid_state_transition(api):
    """PRD 2.9: "The target row's current state has an outgoing transition matching the
    requested action — otherwise `ERR_INVALID_STATE_TRANSITION`. This covers every
    non-terminal invalid-source case across all nine state machines and applies to every
    action endpoint."
    PRD 3.8: "Submitting the draft advances it `DRAFT → SUBMITTED` and requires the submitting
    `X-User-ID` to be the advertisement's own `originator_id`."
    PRD 3.8: "A new advertisement starts in `DRAFT` with an empty `disclosure_findings`, a
    null `reviewed_by_user_id` and a null `published_at`."

    Design: Corner/state_machines/publish_advertisement_from_draft_returns_invalid_state_transition
    """
    originator = create_originator(api)
    advertisement = draft_advertisement(
        api,
        originator["id"],
        medium="WEB",
        content_text=(
            "Refinance with our licensed team. NMLS "
            f"{originator['nmls_unique_id']}, California licence CA-DFPI-70001."
        ),
        target_state_codes=["CA"],
        disclosed_nmls_ids=[originator["nmls_unique_id"]],
        disclosed_license_numbers=["CA-DFPI-70001"],
    )
    assert advertisement["status"] == "DRAFT", (
        f"a new advertisement starts in DRAFT: {advertisement['status']}"
    )

    response = api.publish_advertisement(
        advertisement["id"], make_originator_headers(originator["id"])
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
    after = validate_success(api.get_advertisement(advertisement["id"], officer_headers()), 200)
    assert_advertisement(after)
    assert after["status"] == "DRAFT", (
        f"the rejected publish applied no transition: {after['status']}"
    )
    assert after["published_at"] is None, (
        f"published_at is stamped only on a successful publication: {after['published_at']}"
    )
    assert after["disclosure_findings"] == [], (
        f"findings are computed at submission, which never happened: {after['disclosure_findings']}"
    )


def test_surrender_action_on_a_revoked_license_is_locked_out_as_already_terminal(api):
    """PRD 3.1: "`SURRENDERED` and `REVOKED` are both terminal: a licence in either state
    accepts no further transition, and an attempt is rejected with `ERR_ALREADY_TERMINAL`."
    PRD 2.9: "The target row is not already in one of its state machine's terminal states —
    otherwise `ERR_ALREADY_TERMINAL`. This too applies to every action endpoint."
    PRD 3.1: "Because that sponsorship closed, the licence's
    `active_sponsoring_institution_code` and `active_sponsorship_effective_at` go null and the
    originator's `authorized_state_codes` is recomputed, losing that `state_code`."

    Design: Corner/state_machines/surrender_action_on_revoked_license_returns_already_terminal
    """
    context = setup_authorized_originator(api)
    licence_id = context["license"]["id"]
    revoked = license_status_action(
        api, licence_id, "REVOKE", note="State order 2026-118 revoked the licence."
    )
    assert revoked["status"] == "REVOKED", (
        f"revocation advances the licence to REVOKED: {revoked['status']}"
    )

    response = api.create_license_status_action(
        licence_id,
        factories.build_license_status_action(
            "SURRENDER", note="Attempted voluntary surrender after revocation."
        ),
        analyst_headers(),
    )

    validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL.value)
    licence = get_license(api, licence_id)
    assert licence["status"] == "REVOKED", (
        f"a terminal licence accepts no further transition: {licence['status']}"
    )
    originator = get_originator(api, context["originator"]["id"])
    assert originator["authorized_state_codes"] == [], (
        "the revocation cascade already emptied the authority set: "
        f"{originator['authorized_state_codes']}"
    )


def test_second_relinquish_of_the_same_sponsorship_does_not_restamp_the_interval(api):
    """PRD 3.1: "A sponsorship can also simply end. When an analyst relinquishes one directly,
    the row moves `ACTIVE → RELINQUISHED`; this requires that the row is still `ACTIVE` and
    that the owning licence's `status` is `ACTIVE`, `RENEWAL_PENDING` or `EXPIRED`."
    PRD 3.1: "The system stamps `relinquished_at` from the logical clock, clears the licence's
    `active_sponsoring_institution_code` and `active_sponsorship_effective_at` to null,
    increments the licence's `version` by one, recomputes the originator's
    `authorized_state_codes` — the state drops out, because an unsponsored licence confers no
    authority at all — and appends a `SPONSORSHIP_CHANGED` audit entry."
    PRD 2.9 fixes both the state-precondition rejection (`ERR_INVALID_STATE_TRANSITION`) and
    the terminal-state rejection (`ERR_ALREADY_TERMINAL`) at HTTP 409; the contract does not
    label `RELINQUISHED` a terminal state, so the already-relinquished row is accepted under
    either identifier while the interval itself is pinned exactly.

    Design: Corner/state_machines/second_relinquish_on_same_sponsorship_returns_already_terminal
    """
    context = setup_authorized_originator(api)
    sponsorship_id = context["sponsorship"]["id"]
    first = relinquish_sponsorship(api, sponsorship_id)
    assert first["status"] == "RELINQUISHED", (
        f"the first relinquish closes the interval: {first['status']}"
    )
    assert _instant(first["relinquished_at"]) == _instant(CLOCK_STARTUP_INSTANT), (
        f"relinquished_at is stamped from the logical clock: {first['relinquished_at']}"
    )

    response = api.relinquish_sponsorship_transfer(sponsorship_id, analyst_headers())

    assert response.status_code == 409, (
        f"a second relinquish is a 409 rejection: {response.status_code} {response.text}"
    )
    validate_error_is_one_of(
        response,
        [
            ApiErrorId.ERR_ALREADY_TERMINAL.value,
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        ],
    )
    after = validate_success(api.get_sponsorship_transfer(sponsorship_id, analyst_headers()), 200)
    assert_sponsorship_transfer(after)
    assert after["status"] == "RELINQUISHED", (
        f"the row stays where the first relinquish left it: {after['status']}"
    )
    assert _instant(after["relinquished_at"]) == _instant(CLOCK_STARTUP_INSTANT), (
        f"the rejected call must not re-stamp relinquished_at: {after['relinquished_at']}"
    )
    assert after["superseded_by_created_at"] is None, (
        "a directly relinquished row was never superseded: "
        f"{after['superseded_by_created_at']}"
    )
    originator = get_originator(api, context["originator"]["id"])
    assert originator["authorized_state_codes"] == [], (
        "an unsponsored licence confers no authority at all: "
        f"{originator['authorized_state_codes']}"
    )
