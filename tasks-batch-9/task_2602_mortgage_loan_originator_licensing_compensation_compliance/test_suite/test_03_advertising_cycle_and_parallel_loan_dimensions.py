"""State machines that do not run in a straight line.

Advertising copy loops back through DRAFT on its way to PUBLISHED, and a loan
carries two state dimensions that advance on their own schedules. Both are
pinned here transition by transition.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp

from test_helpers.fixtures import (
    close_loan,
    draft_advertisement,
    get_loan,
    get_originator,
    lock_loan,
    payoff_loan,
    publish_advertisement,
    review_advertisement,
    revise_advertisement,
    run_reconciliation,
    set_clock,
    setup_authorized_originator,
    setup_originator_with_plan,
    sole_record_for_loan,
    submit_advertisement,
    take_loan,
)
from test_helpers.test_users import OFFICER_USER_ID

_NON_COMPLIANT_COPY = (
    "Refinance today with no closing cost and keep more of your money every month."
)
_COMPLIANT_COPY = "Refinance today with no closing cost at 6.50% APR; terms apply."

# --- local scenario builders ------------------------------------------------


def _draft_undisclosed_web_advertisement(api):
    """WEB copy that discloses nothing and carries the trigger phrase without APR."""
    context = setup_authorized_originator(api)
    advertisement = draft_advertisement(
        api,
        context["originator"]["id"],
        medium="WEB",
        content_text=_NON_COMPLIANT_COPY,
        target_state_codes=[context["state_code"]],
        disclosed_nmls_ids=[],
        disclosed_license_numbers=[],
    )
    context["advertisement"] = advertisement
    return context


def _reject_the_first_submission(api, context):
    """Carry the copy through submission to REJECTED, the state a revision starts from."""
    advertisement_id = context["advertisement"]["id"]
    submitted = submit_advertisement(api, advertisement_id, context["originator"]["id"])
    rejected = review_advertisement(api, advertisement_id, "REJECT")
    return submitted, rejected


def _revise_with_full_disclosure(api, context):
    """Replace the copy and both disclosure lists so the next inspection is clean."""
    return revise_advertisement(
        api,
        context["advertisement"]["id"],
        context["originator"]["id"],
        _COMPLIANT_COPY,
        disclosed_nmls_ids=[context["originator"]["nmls_unique_id"]],
        disclosed_license_numbers=[context["license"]["license_number"]],
    )


def _build_par_rate_loan_at_lock(api):
    """A locked loan priced at par under a 200-basis-point plan with no volume tier."""
    context = setup_originator_with_plan(
        api,
        plan_overrides={
            "base_basis_points": 200,
            "min_fee_cents": 100_000,
            "max_fee_cents": 900_000,
            "volume_tier_enabled": False,
            "concession_absorption_enabled": False,
        },
        license_overrides={
            "expiration_date": "2028-01-31T00:00:00Z",
            "renewal_window_opens_at": "2027-11-01T00:00:00Z",
        },
    )
    originator_id = context["originator"]["id"]
    taken = take_loan(
        api,
        originator_id,
        state_code=context["state_code"],
        requested_amount_cents=20_000_000,
        par_rate_bps=650,
    )
    locked = lock_loan(
        api, taken["id"], originator_id, note_rate_bps=650, locked_amount_cents=20_000_000
    )
    context["taken_loan"] = taken
    context["loan"] = locked
    return context


def _close_at_par(api, loan_id):
    """Close the loan with a single lender-paid leg equal to its computed commission."""
    return close_loan(
        api,
        loan_id,
        funded_amount_cents=20_000_000,
        funded_at="2026-09-01T00:00:00Z",
        lender_paid_comp_cents=400_000,
        borrower_paid_comp_cents=0,
    )


# --- DRAFT -> SUBMITTED -> REJECTED -> DRAFT -> SUBMITTED -> APPROVED -> PUBLISHED


def test_first_submission_stores_three_deduplicated_sorted_findings(api):
    """PRD §3.8: "When the originator's `nmls_unique_id` does not appear among the entries of
    `disclosed_nmls_ids`, the finding `MISSING_NMLS_ID` is produced."
    PRD §3.8: "If the licence exists but its `license_number` does not appear among the entries
    of `disclosed_license_numbers`, the finding is `MISSING_LICENSE_NUMBER_` immediately
    followed by that state code."
    PRD §3.8: "When the `medium` is `WEB` or `SOCIAL`, and the `content_text` contains the
    trigger phrase `no closing cost` matched without regard to letter case, and the
    `content_text` does **not** contain `APR` matched with regard to letter case, the finding
    `TRIGGER_TERM_WITHOUT_APR` is produced."
    PRD §3.8: "The assembled finding list is de-duplicated and then sorted in ascending string
    order before being stored, so `disclosure_findings` is always deterministic."

    Design: Difficulty/non_linear_state_machine/advertisement_reject_revise_resubmit_approve_cycle
    """
    context = _draft_undisclosed_web_advertisement(api)

    assert context["advertisement"]["status"] == "DRAFT"
    assert context["advertisement"]["disclosure_findings"] == []
    assert context["advertisement"]["reviewed_by_user_id"] is None
    assert context["advertisement"]["published_at"] is None

    submitted, rejected = _reject_the_first_submission(api, context)

    assert submitted["status"] == "SUBMITTED"
    assert submitted["disclosure_findings"] == [
        "MISSING_LICENSE_NUMBER_CA",
        "MISSING_NMLS_ID",
        "TRIGGER_TERM_WITHOUT_APR",
    ], f"findings must be exactly these three in ascending order: {submitted['disclosure_findings']}"

    assert rejected["status"] == "REJECTED"
    assert rejected["reviewed_by_user_id"] == OFFICER_USER_ID
    assert rejected["published_at"] is None


def test_revision_returns_to_draft_clearing_findings_and_the_reviewer(api):
    """PRD §3.8: "the revision requires the acting `X-User-ID` to be the advertisement's
    `originator_id`, clears `disclosure_findings` back to an empty list — the inspection will
    run again at the next submission — and resets `reviewed_by_user_id` to null."
    PRD §3.8: "The `REJECTED → DRAFT → SUBMITTED` loop is unbounded: an advertisement may go
    round it as many times as it takes."

    Design: Difficulty/non_linear_state_machine/advertisement_reject_revise_resubmit_approve_cycle
    """
    context = _draft_undisclosed_web_advertisement(api)
    _reject_the_first_submission(api, context)

    revised = _revise_with_full_disclosure(api, context)

    assert revised["status"] == "DRAFT", "a rejected advertisement is revised, never re-drafted"
    assert revised["disclosure_findings"] == []
    assert revised["reviewed_by_user_id"] is None
    assert revised["content_text"] == _COMPLIANT_COPY

    resubmitted = submit_advertisement(
        api, context["advertisement"]["id"], context["originator"]["id"]
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["disclosure_findings"] == [], (
        "the re-run inspection finds nothing: the NMLS id and the CA licence number are now "
        f"disclosed and the copy carries APR: {resubmitted['disclosure_findings']}"
    )


def test_second_pass_reaches_published_after_exactly_six_mutations(api):
    """PRD §3.8: "**Approval** advances the advertisement `SUBMITTED → APPROVED` and requires
    that `disclosure_findings` is empty after that recomputation"
    PRD §3.8: "On success `published_at` is stamped from the logical clock."
    PRD §2.5: "Every resource in this system except the audit trail additionally carries an
    `updated_at` timestamp in the same format, refreshed on every mutation of that row, and a
    `version` integer that starts at `1` when the row is created and increments by exactly one
    on every mutation of that row."

    Design: Difficulty/non_linear_state_machine/advertisement_reject_revise_resubmit_approve_cycle
    """
    context = _draft_undisclosed_web_advertisement(api)
    advertisement_id = context["advertisement"]["id"]
    version_at_draft = context["advertisement"]["version"]

    _reject_the_first_submission(api, context)
    _revise_with_full_disclosure(api, context)
    submit_advertisement(api, advertisement_id, context["originator"]["id"])

    approved = review_advertisement(api, advertisement_id, "APPROVE")
    assert approved["status"] == "APPROVED"
    assert approved["reviewed_by_user_id"] == OFFICER_USER_ID
    assert approved["published_at"] is None

    published = publish_advertisement(api, advertisement_id, context["originator"]["id"])
    assert published["status"] == "PUBLISHED"
    assert published["disclosure_findings"] == []
    assert is_iso8601_timestamp(published["published_at"])
    assert published["published_at"].startswith("2026-08-01T00:00:00"), (
        f"published_at is stamped from the logical clock: {published['published_at']}"
    )
    assert published["version"] == version_at_draft + 6, (
        "six writes reached the row: submission, rejection, revision, resubmission, approval "
        f"and publication: {published['version']} != {version_at_draft + 6}"
    )


# --- status and compensation_status advance independently -------------------


def test_taking_and_locking_move_only_the_origination_dimension(api):
    """PRD §3.4: "The `status` field tracks origination and moves through `TAKEN`, `LOCKED`,
    `CLOSED` and `PAID_OFF`, with `WITHDRAWN` as its only terminal state."
    PRD §3.4: "A successfully taken application stamps `application_taken_at` from the logical
    clock — this is the instant the authority window check was evaluated against, and it is
    recorded so that a later examination can reconstruct the decision — and initialises `status`
    to `TAKEN`, `compensation_status` to `NOT_APPLICABLE` and `authority_flag` to `VERIFIED`."
    PRD §3.4: "The lock leaves `compensation_status` untouched, since the two dimensions are
    independent, and increments the loan's `version` by one."

    Design: Difficulty/non_linear_state_machine/loan_status_and_compensation_status_advance_independently
    """
    context = _build_par_rate_loan_at_lock(api)

    assert context["taken_loan"]["status"] == "TAKEN"
    assert context["taken_loan"]["compensation_status"] == "NOT_APPLICABLE"
    assert context["taken_loan"]["authority_flag"] == "VERIFIED"

    assert context["loan"]["status"] == "LOCKED"
    assert context["loan"]["compensation_status"] == "NOT_APPLICABLE", (
        "locking the rate does not start the compensation dimension"
    )
    assert context["loan"]["locked_amount_cents"] == 20_000_000
    assert context["loan"]["note_rate_bps"] == 650
    assert context["loan"]["version"] == context["taken_loan"]["version"] + 1


def test_closing_then_reconciling_moves_only_the_compensation_dimension(api):
    """PRD §3.4: "The two advance independently: a loan can be `PAID_OFF` while its
    compensation is still `PENDING`, and its compensation can be `RECONCILED` while its
    `status` is still `CLOSED`."
    PRD §3.5: "**Branch A — authority intact.** When `authority_flag` reads `VERIFIED`,
    `compensation_status` is set to `ACCRUED` and exactly one ledger line is created for the
    loan with `variant` `PROVISIONAL`, computed as described below."
    PRD §3.7: "The owning loan's `compensation_status` advances `ACCRUED → RECONCILED` in step."

    Design: Difficulty/non_linear_state_machine/loan_status_and_compensation_status_advance_independently
    """
    context = _build_par_rate_loan_at_lock(api)
    loan_id = context["loan"]["id"]

    closed = _close_at_par(api, loan_id)
    assert closed["status"] == "CLOSED"
    assert closed["compensation_status"] == "ACCRUED"
    assert sole_record_for_loan(api, loan_id)["accrued_cents"] == 400_000, (
        "20,000,000 cents at 200 basis points is 400,000 cents"
    )

    run = run_reconciliation(api, context["originator"]["id"])
    assert run["reconciled_count"] == 1
    assert run["total_final_cents"] == 400_000
    assert run["total_delta_cents"] == 0

    loan = get_loan(api, loan_id)
    assert loan["status"] == "CLOSED", (
        "reconciliation is a compensation event and never touches the origination dimension"
    )
    assert loan["compensation_status"] == "RECONCILED"


def test_late_payoff_moves_only_the_origination_dimension(api):
    """PRD §3.7: "A `days_held` of ninety days or fewer sets `recapture_pct` to one hundred
    percent; a `days_held` above ninety but no more than one hundred and eighty days sets it to
    fifty percent; anything longer sets `recapture_pct` to zero."
    PRD §3.7: "When a reconciled line does exist and `recapture_pct` comes out greater than
    zero, posting the payoff drives a **five-hop cascade**"
    PRD §3.4: "The two advance independently: a loan can be `PAID_OFF` while its compensation
    is still `PENDING`, and its compensation can be `RECONCILED` while its `status` is still
    `CLOSED`."

    Design: Difficulty/non_linear_state_machine/loan_status_and_compensation_status_advance_independently
    """
    context = _build_par_rate_loan_at_lock(api)
    loan_id = context["loan"]["id"]
    _close_at_par(api, loan_id)
    run_reconciliation(api, context["originator"]["id"])

    set_clock(api, "2027-04-01T00:00:00Z")
    paid_off = payoff_loan(api, loan_id, "2027-04-01T00:00:00Z")

    assert paid_off["status"] == "PAID_OFF"
    assert paid_off["compensation_status"] == "RECONCILED", (
        "212 days is beyond the outer window, so no recapture cascade fires"
    )
    assert paid_off["payoff_date"].startswith("2027-04-01T00:00:00")

    record = sole_record_for_loan(api, loan_id)
    assert record["status"] == "RECONCILED"
    assert record["days_held"] == 212, (
        "2026-09-01 to 2027-04-01 is 212 whole days: got {}".format(record["days_held"])
    )
    assert record["recapture_pct"] == 0
    assert record["clawback_cents"] == 0
    assert record["paid_cents"] == 400_000

    originator = get_originator(api, context["originator"]["id"])
    assert originator["lifetime_accrued_cents"] == 400_000
    assert originator["lifetime_clawed_back_cents"] == 0
    assert originator["net_compensation_cents"] == 400_000
    assert originator["exposure_score"] == 0
    assert originator["monitoring_status"] == "STANDARD"
