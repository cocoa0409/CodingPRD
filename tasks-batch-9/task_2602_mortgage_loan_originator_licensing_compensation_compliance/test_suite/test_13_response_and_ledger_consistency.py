"""Immediate consistency: a mutating response and the reads that follow it agree.

The contract is read-your-writes with no settling step. What a close returns is
already what a subsequent read returns, the ledger line it wrote is already
listable, and every identifier the nightly sweep reports is already confirmable
by a direct read of that row.
"""
from datetime import datetime

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.assertions import (
    assert_compensation_record,
    assert_investigation,
    assert_license_registration,
    assert_loan_application,
    assert_originator,
    assert_sponsorship_transfer,
)
from test_helpers.fixtures import (
    close_loan,
    get_license,
    get_loan,
    get_originator,
    lock_loan,
    run_sweep,
    set_clock,
    setup_authorized_originator,
    setup_locked_loan,
    take_loan,
)
from test_helpers.test_users import analyst_headers, officer_headers

FUNDED_CENTS = 5_000_000
EXPECTED_COMMISSION_CENTS = 52_500
SWEEP_INSTANT = "2026-08-16T00:00:00Z"


def _instant(value):
    """Parse an ISO 8601 UTC instant so two renderings of one instant compare equal."""
    assert value is not None, "expected an ISO 8601 instant, found null"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _setup_close_ready_loan(api):
    """A CA loan locked at 5,000,000 cents under a flat 105 bps plan.

    The plan disables the volume tier and concession absorption, so the whole
    commission is 5,000,000 x 105 / 10,000 = 52,500 cents inside a 0 to
    5,000,000 cent fee band.
    """
    return setup_locked_loan(
        api,
        loan_overrides={"requested_amount_cents": FUNDED_CENTS},
        lock_overrides={"locked_amount_cents": FUNDED_CENTS},
        plan_overrides={
            "base_basis_points": 105,
            "min_fee_cents": 0,
            "max_fee_cents": FUNDED_CENTS,
            "volume_tier_enabled": False,
            "concession_absorption_enabled": False,
        },
    )


def _close(api, loan_id):
    """Close the file reporting 52,500 cents of lender-paid compensation."""
    return close_loan(
        api,
        loan_id,
        funded_amount_cents=FUNDED_CENTS,
        lender_paid_comp_cents=EXPECTED_COMMISSION_CENTS,
        borrower_paid_comp_cents=0,
    )


def _setup_lapsing_license_with_locked_loan(api):
    """A CA licence expiring 2026-08-15 whose originator holds one LOCKED CA loan.

    Sponsored from before the clock instant, so the file is takeable and lockable
    now and the sweep of 2026-08-16 has both a sponsorship to close and a loan to
    suspend.
    """
    context = setup_authorized_originator(
        api,
        sponsorship_effective_at="2026-07-01T00:00:00Z",
        license_overrides={
            "expiration_date": "2026-08-15T00:00:00Z",
            "renewal_window_opens_at": "2026-08-01T00:00:00Z",
        },
    )
    originator_id = context["originator"]["id"]
    loan = take_loan(
        api,
        originator_id,
        state_code=context["state_code"],
        requested_amount_cents=FUNDED_CENTS,
    )
    context["loan"] = lock_loan(
        api, loan["id"], originator_id, locked_amount_cents=FUNDED_CENTS
    )
    assert context["loan"]["authority_flag"] == "VERIFIED", (
        f"the lock re-verified authority: {context['loan']['authority_flag']}"
    )
    return context


def test_close_response_already_carries_the_closed_and_accrued_dimensions(api):
    """PRD 3.5: "On success the loan's origination dimension advances `LOCKED → CLOSED`."
    PRD 3.5: "When `authority_flag` reads `VERIFIED`, `compensation_status` is set to `ACCRUED`
    and exactly one ledger line is created for the loan with `variant` `PROVISIONAL`, computed
    as described below."
    PRD 3.4: "It reads `VERIFIED` while the authority window check passed at
    `application_taken_at` and has not since been invalidated, `SUSPENDED` after an
    authority-lapse cascade has reached the loan, and `UNAUTHORIZED` once an unlicensed-activity
    investigation on that loan has been substantiated."
    The close response is therefore authoritative on both dimensions, and the read that follows
    it must agree field for field with no settling step.

    Design: Corner/consistency_model/close_response_already_carries_the_accrued_status_and_the_ledger_line
    """
    context = _setup_close_ready_loan(api)

    closed = _close(api, context["loan"]["id"])

    assert_loan_application(closed)
    assert closed["status"] == "CLOSED", (
        f"the close response already shows the advanced dimension: {closed['status']}"
    )
    assert closed["compensation_status"] == "ACCRUED", (
        "authority was intact, so the compensation dimension is ACCRUED in the same response: "
        f"{closed['compensation_status']}"
    )
    assert closed["funded_amount_cents"] == FUNDED_CENTS, (
        f"the reported funded amount is echoed: {closed['funded_amount_cents']}"
    )
    assert closed["authority_flag"] == "VERIFIED", (
        f"nothing invalidated the authority behind the file: {closed['authority_flag']}"
    )

    read = get_loan(api, context["loan"]["id"])
    for field in (
        "id",
        "version",
        "status",
        "compensation_status",
        "authority_flag",
        "funded_amount_cents",
        "funded_at",
        "closed_unit_index",
        "compensation_plan_id",
        "lender_paid_comp_cents",
        "borrower_paid_comp_cents",
        "file_quality_score",
        "hours_worked_pct",
    ):
        assert read[field] == closed[field], (
            f"the follow-up read disagrees with the close response on {field}: "
            f"{read[field]} != {closed[field]}"
        )


def test_the_provisional_ledger_line_is_listable_in_the_very_next_request(api):
    """PRD 3.5: "Every provisional line is created with `variant` `PROVISIONAL` and `status`
    `ACCRUED`, and it copies the loan's `loan_application_id`, the originator's `originator_id`
    and the pinned `compensation_plan_id` onto itself; none of those three is client-supplied."
    PRD 3.5: "When the governing plan's `volume_tier_enabled` is false the adder is zero and
    nothing further is evaluated."
    PRD 3.5: "A line's `paid_cents` reads `0` while its `status` is `ACCRUED` and equals its
    `accrued_cents` once the line reaches `RECONCILED`; `clawback_cents` reads `0` unless the
    line has been clawed back; and `days_held` and `recapture_pct` both read null until a payoff
    is recorded against the loan."
    PRD 2.3: "Successful list responses carry four pagination fields in the `meta` object:
    `limit` and `offset` echoing the effective values used, `total_count` giving the number of
    rows matching the filters before paging, and `has_more` indicating whether any matching rows
    remain beyond this page."

    Design: Corner/consistency_model/close_response_already_carries_the_accrued_status_and_the_ledger_line
    """
    context = _setup_close_ready_loan(api)
    loan_id = context["loan"]["id"]

    _close(api, loan_id)

    records, meta = validate_paginated(
        api.list_compensation_records(
            officer_headers(), params={"loan_application_id": loan_id}
        )
    )
    assert meta["total_count"] == 1, (
        f"the close wrote exactly one ledger line and it is already listable: {meta}"
    )
    assert len(records) == 1, f"expected one ledger line on the page, found {len(records)}"
    record = records[0]
    assert_compensation_record(record)
    assert record["loan_application_id"] == loan_id, (
        f"the line copies its loan: {record['loan_application_id']} != {loan_id}"
    )
    assert record["originator_id"] == context["originator"]["id"], (
        f"the line copies its originator: {record['originator_id']}"
    )
    assert record["compensation_plan_id"] == context["plan"]["id"], (
        f"the line copies the pinned plan: {record['compensation_plan_id']}"
    )
    assert record["variant"] == "PROVISIONAL", f"variant: {record['variant']}"
    assert record["status"] == "ACCRUED", f"status: {record['status']}"
    assert record["tier_bps_adder"] == 0, (
        f"the tier is disabled on this plan: {record['tier_bps_adder']}"
    )
    assert record["base_comp_cents"] == EXPECTED_COMMISSION_CENTS, (
        f"105 bps on 5,000,000 cents is 52,500 cents: {record['base_comp_cents']}"
    )
    assert record["comp_impact_cents"] == 0, (
        f"no approved pricing exception touches this file: {record['comp_impact_cents']}"
    )
    assert record["accrued_cents"] == EXPECTED_COMMISSION_CENTS, (
        f"accrued_cents is base less impact: {record['accrued_cents']}"
    )
    assert record["paid_cents"] == 0, (
        f"paid_cents reads 0 while the line is ACCRUED: {record['paid_cents']}"
    )
    assert record["clawback_cents"] == 0, f"clawback_cents: {record['clawback_cents']}"
    assert record["days_held"] is None, f"days_held reads null before payoff: {record['days_held']}"
    assert record["recapture_pct"] is None, (
        f"recapture_pct reads null before payoff: {record['recapture_pct']}"
    )
    assert record["reconciled_at"] is None, (
        f"reconciled_at is stamped only by reconciliation: {record['reconciled_at']}"
    )


def test_the_originator_roll_ups_moved_in_the_same_request_that_closed_the_loan(api):
    """PRD 3.5: "Either way the close recomputes the originator's `lifetime_accrued_cents` and
    `net_compensation_cents`, recomputes the originator's `exposure_score` and
    `monitoring_status` as §3.7 describes, and increments both the originator's `version` and the
    loan's `version` by one."
    PRD 2.11: "An originator's `lifetime_accrued_cents` is at all times the sum of
    `accrued_cents` over every one of that originator's ledger lines in any status,
    `lifetime_clawed_back_cents` is at all times the sum of `clawback_cents` over the same set,
    and `net_compensation_cents` is at all times exactly `lifetime_accrued_cents` less
    `lifetime_clawed_back_cents` — it is a derived balance and is never written directly."

    Design: Corner/consistency_model/close_response_already_carries_the_accrued_status_and_the_ledger_line
    """
    context = _setup_close_ready_loan(api)
    originator_id = context["originator"]["id"]
    before = get_originator(api, originator_id)
    assert before["lifetime_accrued_cents"] == 0, (
        f"nothing has accrued before the close: {before['lifetime_accrued_cents']}"
    )

    _close(api, context["loan"]["id"])

    after = get_originator(api, originator_id)
    assert_originator(after)
    assert after["lifetime_accrued_cents"] == EXPECTED_COMMISSION_CENTS, (
        "the roll-up is the sum over the single ledger line the close wrote: "
        f"{after['lifetime_accrued_cents']}"
    )
    assert after["lifetime_clawed_back_cents"] == 0, (
        f"nothing has been clawed back: {after['lifetime_clawed_back_cents']}"
    )
    assert after["net_compensation_cents"] == EXPECTED_COMMISSION_CENTS, (
        f"the derived balance is accrued less clawed back: {after['net_compensation_cents']}"
    )
    assert after["version"] == before["version"] + 1, (
        f"the close increments the originator's version by one: "
        f"{after['version']} != {before['version'] + 1}"
    )


def test_sweep_manifest_license_and_sponsorship_ids_read_back_as_the_sweep_reported(api):
    """PRD 3.9: "First, every licence whose `status` is `ACTIVE` or `RENEWAL_PENDING` and whose
    `expiration_date` is at or before the logical clock instant moves to `EXPIRED` and runs the
    full five-hop authority-lapse cascade of §3.1 — relinquish the `ACTIVE` sponsorship with
    `relinquished_at` stamped from the clock, clear the licence's denormalised sponsorship fields
    and recompute `authorized_state_codes`, suspend the originator's `TAKEN` and `LOCKED` loans
    in that state by setting `authority_flag` to `SUSPENDED`, open one `CASCADE` investigation
    with `trigger_reason` `AUTHORITY_LAPSE` per suspended loan, and recompute
    `open_investigation_count`"
    PRD 3.9: "The sweep reports what it did so that a caller can verify the epoch advance without
    polling every collection: `swept_at` gives the instant it ran, and `expired_license_ids`,
    `relinquished_sponsorship_ids`, `suspended_loan_ids`, `opened_investigation_ids`,
    `escalated_inquiry_ids` and `unassigned_originator_ids` list the identifiers touched by each
    of the three sweeps."
    PRD 2.4: "Expiry is applied by the nightly compliance sweep described in §3.9, which the
    `PlatformAdmin` triggers; the sweep reports the instant it ran as `swept_at`."

    Design: Corner/consistency_model/sweep_response_ids_are_confirmable_by_the_immediately_following_reads
    """
    context = _setup_lapsing_license_with_locked_loan(api)
    license_id = context["license"]["id"]
    sponsorship_id = context["sponsorship"]["id"]
    set_clock(api, SWEEP_INSTANT)

    report = run_sweep(api)

    assert _instant(report["swept_at"]) == _instant(SWEEP_INSTANT), (
        f"swept_at is the logical clock instant the sweep ran at: {report['swept_at']}"
    )
    assert report["expired_license_ids"] == [license_id], (
        f"the one lapsed licence is named: {report['expired_license_ids']}"
    )
    assert report["relinquished_sponsorship_ids"] == [sponsorship_id], (
        f"hop one of the cascade is named: {report['relinquished_sponsorship_ids']}"
    )

    licence = get_license(api, license_id)
    assert_license_registration(licence)
    assert licence["status"] == "EXPIRED", (
        f"the licence named in expired_license_ids reads back EXPIRED: {licence['status']}"
    )
    assert licence["active_sponsoring_institution_code"] is None, (
        "the denormalised sponsorship fields are cleared: "
        f"{licence['active_sponsoring_institution_code']}"
    )
    assert licence["active_sponsorship_effective_at"] is None, (
        f"the denormalised interval start is cleared: {licence['active_sponsorship_effective_at']}"
    )

    sponsorship = validate_success(
        api.get_sponsorship_transfer(sponsorship_id, analyst_headers()), 200
    )
    assert_sponsorship_transfer(sponsorship)
    assert sponsorship["status"] == "RELINQUISHED", (
        "the sponsorship named in relinquished_sponsorship_ids reads back RELINQUISHED: "
        f"{sponsorship['status']}"
    )
    assert _instant(sponsorship["relinquished_at"]) == _instant(SWEEP_INSTANT), (
        f"relinquished_at is stamped from the clock: {sponsorship['relinquished_at']}"
    )


def test_sweep_manifest_loan_and_investigation_ids_read_back_suspended_and_open(api):
    """PRD 3.9: "First, every licence whose `status` is `ACTIVE` or `RENEWAL_PENDING` and whose
    `expiration_date` is at or before the logical clock instant moves to `EXPIRED` and runs the
    full five-hop authority-lapse cascade of §3.1 — relinquish the `ACTIVE` sponsorship with
    `relinquished_at` stamped from the clock, clear the licence's denormalised sponsorship fields
    and recompute `authorized_state_codes`, suspend the originator's `TAKEN` and `LOCKED` loans
    in that state by setting `authority_flag` to `SUSPENDED`, open one `CASCADE` investigation
    with `trigger_reason` `AUTHORITY_LAPSE` per suspended loan, and recompute
    `open_investigation_count`"
    PRD 3.9: "The authority-lapse cascade of §3.1 and the nightly sweep open them automatically,
    with `opened_by` set to `CASCADE` and `trigger_reason` forced to `AUTHORITY_LAPSE`."
    PRD 3.9: "Cascade-created investigations are discoverable only through the investigation
    list, filtered by `opened_by` or by the loan they name."

    Design: Corner/consistency_model/sweep_response_ids_are_confirmable_by_the_immediately_following_reads
    """
    context = _setup_lapsing_license_with_locked_loan(api)
    loan_id = context["loan"]["id"]
    set_clock(api, SWEEP_INSTANT)

    report = run_sweep(api)

    assert report["suspended_loan_ids"] == [loan_id], (
        f"the one live file in that state is named: {report['suspended_loan_ids']}"
    )
    loan = get_loan(api, loan_id)
    assert_loan_application(loan)
    assert loan["status"] == "LOCKED", (
        f"the cascade touches authority, not the origination dimension: {loan['status']}"
    )
    assert loan["authority_flag"] == "SUSPENDED", (
        f"the loan named in suspended_loan_ids reads back SUSPENDED: {loan['authority_flag']}"
    )
    assert loan["compensation_status"] == "NOT_APPLICABLE", (
        f"the compensation dimension is untouched by the lapse: {loan['compensation_status']}"
    )

    investigations, meta = validate_paginated(
        api.list_investigations(officer_headers(), params={"loan_application_id": loan_id})
    )
    assert meta["total_count"] == 1, (
        f"exactly one investigation is opened per suspended loan: {meta}"
    )
    investigation = investigations[0]
    assert_investigation(investigation)
    assert report["opened_investigation_ids"] == [investigation["id"]], (
        "the manifest names the investigation the very next read returns: "
        f"{report['opened_investigation_ids']} != [{investigation['id']}]"
    )
    assert investigation["status"] == "OPEN", f"status: {investigation['status']}"
    assert investigation["opened_by"] == "CASCADE", f"opened_by: {investigation['opened_by']}"
    assert investigation["trigger_reason"] == "AUTHORITY_LAPSE", (
        f"trigger_reason is forced by the cascade: {investigation['trigger_reason']}"
    )
    assert investigation["loan_application_id"] == loan_id, (
        f"the investigation names the suspended loan: {investigation['loan_application_id']}"
    )
    assert investigation["originator_id"] == context["originator"]["id"], (
        f"and its owning originator: {investigation['originator_id']}"
    )


def test_downstream_roll_ups_are_current_in_the_first_read_after_the_sweep(api):
    """PRD 3.9: "A manually opened investigation records `opened_by` as `MANUAL`, copies its
    `originator_id` from the named loan rather than accepting one from the caller, stamps
    `detected_at` from the logical clock, starts in `status` `OPEN`, and triggers a recompute of
    the originator's `open_investigation_count` — which at all times equals the number of that
    originator's investigations whose `status` is `OPEN` or `SUBSTANTIATED`."
    PRD 3.1: "The system stamps `relinquished_at` from the logical clock, clears the licence's
    `active_sponsoring_institution_code` and `active_sponsorship_effective_at` to null,
    increments the licence's `version` by one, recomputes the originator's
    `authorized_state_codes` — the state drops out, because an unsponsored licence confers no
    authority at all — and appends a `SPONSORSHIP_CHANGED` audit entry."
    PRD 3.9: "A sweep that finds nothing to do still succeeds, returning empty lists."

    Design: Corner/consistency_model/sweep_response_ids_are_confirmable_by_the_immediately_following_reads
    """
    context = _setup_lapsing_license_with_locked_loan(api)
    originator_id = context["originator"]["id"]
    set_clock(api, SWEEP_INSTANT)

    report = run_sweep(api)

    assert report["escalated_inquiry_ids"] == [], (
        f"no examination inquiry exists to escalate: {report['escalated_inquiry_ids']}"
    )
    assert report["unassigned_originator_ids"] == [], (
        f"no compensation plan assignment exists to lapse: {report['unassigned_originator_ids']}"
    )

    originator = get_originator(api, originator_id)
    assert_originator(originator)
    assert originator["open_investigation_count"] == 1, (
        "the single cascade investigation is counted in the first read after the sweep: "
        f"{originator['open_investigation_count']}"
    )
    assert originator["authorized_state_codes"] == [], (
        "the unsponsored, expired licence confers no authority at all: "
        f"{originator['authorized_state_codes']}"
    )

    authority = validate_success(
        api.get_originator_authority(originator_id, officer_headers()), 200
    )
    assert authority["authorized_state_codes"] == [], (
        f"the computed authority read agrees: {authority['authorized_state_codes']}"
    )
    assert _instant(authority["as_of"]) == _instant(SWEEP_INSTANT), (
        f"it evaluated the current logical clock instant: {authority['as_of']}"
    )
