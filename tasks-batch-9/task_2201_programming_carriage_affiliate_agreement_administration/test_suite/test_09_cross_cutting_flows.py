"""Flows that cross several layers of the carriage contract at once.

Optimistic concurrency on the parent agreement, filtered pagination over rights
windows, the pinned clock sweep, the settlement projection, and the immediacy of
every cascade — including the atomicity of a refusal.

Every test builds its own state from an empty database through PRD-declared
endpoints only.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_report,
    agreement_version,
    clock_payload,
    create_commitment,
    create_subscriber_report_payload,
    draft_invoice,
    earn_commitment,
    fetch_agreement,
    fetch_commitment,
    fetch_title,
    fetch_window,
    file_report,
    issue_invoice,
    make_distributor_liaison_headers,
    plan_window,
    read_clock,
    register_cleared_title,
    setup_cleared_window,
    setup_executed_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)

MERIDIAN = {
    "legal_name": "Meridian Broadband",
    "distributor_type": "CABLE_MSO",
    "rate_card_class": "CLASS_A",
    "total_subscribers": 1_500_000,
}
CLIFFSIDE = {
    "legal_name": "Cliffside Telco",
    "distributor_type": "TELCO",
    "rate_card_class": "CLASS_B",
    "total_subscribers": 200_000,
    "credit_limit_cents": 150_000_000,
}
TERMS = {
    "term_start_date": "2025-01-01T00:00:00Z",
    "term_end_date": "2028-12-31T00:00:00Z",
    "base_license_fee_cents_per_sub": 40.0000,
    "escalator_pct": 0.00,
    "penetration_floor_pct": 0.50,
    "committed_tier": "BASIC",
}
TERMS_ENDING_2026 = dict(TERMS, term_end_date="2026-12-31T00:00:00Z")

ACCOUNTANT = TEST_USERS["revenue_accountant_headers"]
ADMIN = TEST_USERS["network_admin_headers"]
RIGHTS = TEST_USERS["rights_administrator_headers"]


# ===========================================================================
# Optimistic concurrency on the parent agreement
# ===========================================================================
def test_report_filing_is_refused_on_a_stale_agreement_view(api):
    """PRD §2.7: "`POST /carriage/subscriber-reports` requires
    `expected_agreement_version`, carrying the client's last observed `version` of
    the `CarriageAgreement` named by `agreement_id`. If it does not equal that
    agreement's current `version`, the filing is rejected with
    `ERR_STALE_AGREEMENT_VERSION` (HTTP 412)."
    PRD §3.4: "A new report opens in `SUBMITTED` with `license_fee_due_cents` 0,
    `audit_adjustment_cents` 0, `invoice_id` null, `accepted_at` null and `version`
    1, and it increments the agreement's `version` by one."
    PRD §2.8: "The first rule that fails decides the response, and no side effect
    of the requested operation fires."

    Design: Corner/cross_cutting_complexity_layers/report_filing_rejects_a_stale_agreement_view
    """
    distributor, agreement = setup_executed_agreement(CLIFFSIDE, TERMS)
    liaison = make_distributor_liaison_headers(distributor["id"])
    stale_version = agreement["version"]

    file_report(
        agreement["id"],
        distributor["id"],
        period_month="2026-05",
        reported_subscribers=130_000,
        reported_tier="BASIC",
    )
    fresh_version = agreement_version(agreement["id"])
    assert fresh_version == stale_version + 1, (
        "filing a report increments the agreement's version by one, so the earlier "
        f"observation {stale_version} is now stale against {fresh_version}"
    )

    stale_payload = create_subscriber_report_payload(
        agreement["id"],
        stale_version,
        period_month="2026-06",
        reported_subscribers=130_000,
        reported_tier="BASIC",
    )
    validate_error(
        api.create_subscriber_report(stale_payload, liaison),
        ApiErrorId.ERR_STALE_AGREEMENT_VERSION.value,
        412,
    )

    _rows, meta = validate_paginated(
        api.list_subscriber_reports(
            ACCOUNTANT, params={"agreement_id": agreement["id"], "limit": 10}
        )
    )
    assert meta["total_count"] == 1, (
        "the refused filing must persist no report, leaving only the 2026-05 filing, "
        f"got total_count {meta['total_count']}"
    )
    assert agreement_version(agreement["id"]) == fresh_version, (
        "the refused filing must not advance the agreement, expected version "
        f"{fresh_version}"
    )

    out_of_term = create_subscriber_report_payload(
        agreement["id"],
        stale_version,
        period_month="2030-01",
        reported_subscribers=130_000,
        reported_tier="BASIC",
    )
    validate_error(
        api.create_subscriber_report(out_of_term, liaison),
        ApiErrorId.ERR_STALE_AGREEMENT_VERSION.value,
        412,
    )

    retry = create_subscriber_report_payload(
        agreement["id"],
        agreement_version(agreement["id"]),
        period_month="2026-06",
        reported_subscribers=130_000,
        reported_tier="BASIC",
    )
    filed = validate_success(api.create_subscriber_report(retry, liaison), 201)
    assert filed["status"] == "SUBMITTED", (
        f"the retry from a refreshed view must be accepted as SUBMITTED, got {filed['status']}"
    )
    assert filed["version"] == 1, f"a new report opens at version 1, got {filed['version']}"


# ===========================================================================
# Filtering happens before pagination
# ===========================================================================
def test_rights_window_listing_filters_before_it_paginates(api):
    """PRD §2.3: "`total_count` is the number of records matching the filter before
    pagination is applied, and `has_more` is true exactly when records remain
    beyond the current page."
    PRD §2.3: "Filter query parameters combine conjunctively: supplying both an
    agreement filter and a status filter returns only records satisfying both."
    PRD §2.3: "`limit` defaults to 10, may not be smaller than 1, and may not be
    larger than 100."
    PRD §2.3: "Results are ordered by `created_at` ascending unless a specific
    narrative states otherwise, and that ordering is stable across pages."

    Design: Corner/cross_cutting_complexity_layers/rights_window_listing_filters_before_it_paginates
    """
    _distributor, agreement = setup_executed_agreement(MERIDIAN, TERMS)
    title = register_cleared_title(
        title="Night Circuit", linear_premiere_at="2026-08-15T00:00:00Z"
    )
    linear_ids = [
        plan_window(
            agreement["id"],
            title["id"],
            platform="LINEAR",
            territory_code="US",
            window_start=start,
            window_end=end,
            exclusivity="NON_EXCLUSIVE",
        )["id"]
        for start, end in (
            ("2026-10-01T00:00:00Z", "2026-10-08T00:00:00Z"),
            ("2026-11-01T00:00:00Z", "2026-11-08T00:00:00Z"),
            ("2026-12-01T00:00:00Z", "2026-12-08T00:00:00Z"),
        )
    ]
    for start, end in (
        ("2026-10-01T00:00:00Z", "2026-10-15T00:00:00Z"),
        ("2026-11-01T00:00:00Z", "2026-11-15T00:00:00Z"),
    ):
        plan_window(
            agreement["id"],
            title["id"],
            platform="VOD",
            territory_code="US",
            window_start=start,
            window_end=end,
            exclusivity="NON_EXCLUSIVE",
        )

    base = {"agreement_id": agreement["id"]}

    _all_rows, all_meta = validate_paginated(
        api.list_rights_windows(RIGHTS, params=dict(base, limit=100))
    )
    assert all_meta["total_count"] == 5, (
        f"five windows were planned on the agreement, got total_count {all_meta['total_count']}"
    )
    assert all_meta["has_more"] is False, "a page of 100 leaves nothing beyond it"

    filtered, filtered_meta = validate_paginated(
        api.list_rights_windows(RIGHTS, params=dict(base, platform="LINEAR", limit=100))
    )
    assert filtered_meta["total_count"] == 3, (
        f"three of the five windows are LINEAR, got total_count {filtered_meta['total_count']}"
    )
    assert {row["id"] for row in filtered} == set(linear_ids), (
        "the LINEAR filter must return exactly the three LINEAR windows"
    )

    first_page, first_meta = validate_paginated(
        api.list_rights_windows(RIGHTS, params=dict(base, platform="LINEAR", limit=2, offset=0))
    )
    assert first_meta["total_count"] == 3, (
        f"total_count counts the filtered set before pagination, got {first_meta['total_count']}"
    )
    assert len(first_page) == 2, f"a limit of 2 returns two rows, got {len(first_page)}"
    assert first_meta["has_more"] is True, "one filtered row remains beyond the first page"

    second_page, second_meta = validate_paginated(
        api.list_rights_windows(RIGHTS, params=dict(base, platform="LINEAR", limit=2, offset=2))
    )
    assert second_meta["total_count"] == 3, (
        f"total_count is unaffected by offset, got {second_meta['total_count']}"
    )
    assert len(second_page) == 1, f"one filtered row is left on the second page, got {len(second_page)}"
    assert second_meta["has_more"] is False, "nothing remains beyond the second page"

    first_ids = [row["id"] for row in first_page]
    second_ids = [row["id"] for row in second_page]
    assert set(first_ids).isdisjoint(second_ids), "the two pages must not repeat a row"
    assert set(first_ids) | set(second_ids) == set(linear_ids), (
        "the two pages together must cover the filtered set exactly, with nothing skipped"
    )

    _vod, vod_meta = validate_paginated(
        api.list_rights_windows(
            RIGHTS, params=dict(base, platform="VOD", status="PLANNED", limit=100)
        )
    )
    assert vod_meta["total_count"] == 2, (
        f"platform and status compose conjunctively, got total_count {vod_meta['total_count']}"
    )

    empty, empty_meta = validate_paginated(
        api.list_rights_windows(
            RIGHTS, params=dict(base, platform="LINEAR", status="CLEARED", limit=100)
        )
    )
    assert empty_meta["total_count"] == 0, (
        f"no LINEAR window has been cleared, got total_count {empty_meta['total_count']}"
    )
    assert empty == [], f"an empty filtered set returns an empty array, got {empty}"
    assert empty_meta["has_more"] is False, "an empty set has nothing beyond it"

    default_rows, default_meta = validate_paginated(api.list_rights_windows(RIGHTS, params=base))
    assert default_meta["limit"] == 10, (
        f"limit defaults to 10 when unsupplied, got {default_meta['limit']}"
    )
    assert default_meta["offset"] == 0, (
        f"offset defaults to 0 when unsupplied, got {default_meta['offset']}"
    )
    assert default_meta["total_count"] == 5, (
        f"the unfiltered agreement still has five windows, got {default_meta['total_count']}"
    )
    assert len(default_rows) == 5, (
        f"the default page of 10 holds all five rows, got {len(default_rows)}"
    )


# ===========================================================================
# One clock advance, one sweep
# ===========================================================================
def test_clock_advance_sweeps_expiry_and_forfeiture_in_one_pass(api):
    """PRD §2.5: "A successful advance increments `set_count` by one and then runs
    a single sweep whose step order is pinned and observable:"
    PRD §2.5: "Rights windows in `CLEARED` or `ACTIVE` whose `window_end` is at or
    before `current_utc` move to `EXPIRED`."
    PRD §2.5: "Marketing commitments whose `performance_deadline` is strictly
    before `current_utc` and whose `remaining_cents` is still positive forfeit
    their remainder, processed in `performance_deadline` ascending, then
    `created_at` ascending."
    PRD §2.5: "Time may only move forward: a value less than or equal to the
    current logical time is rejected with `ERR_CLOCK_MUST_MOVE_FORWARD` (HTTP
    422)."
    PRD §3.6: "`cleared_window_count` is the number of that title's windows whose
    `status` is `CLEARED` or `ACTIVE`."

    Design: Corner/cross_cutting_complexity_layers/clock_advance_sweeps_expiry_and_forfeiture_in_one_pass
    """
    _distributor, agreement, title, window = setup_cleared_window(
        MERIDIAN,
        TERMS_ENDING_2026,
        {"title": "Night Circuit", "linear_premiere_at": "2026-08-15T00:00:00Z"},
        {
            "platform": "LINEAR",
            "territory_code": "US",
            "window_start": "2026-10-01T00:00:00Z",
            "window_end": "2026-10-08T00:00:00Z",
            "exclusivity": "NON_EXCLUSIVE",
        },
    )
    commitment = create_commitment(
        agreement["id"],
        commitment_type="COOP_ADVERTISING",
        committed_cents=1_000_000,
        performance_deadline="2026-10-01T00:00:00Z",
    )

    validate_success(api.set_clock(clock_payload("2027-02-01T00:00:00Z"), ADMIN))

    advanced = read_clock()["current_utc"]
    assert advanced.startswith("2027-02-01T00:00:00"), (
        f"the clock must now read the requested instant, got {advanced}"
    )

    swept_agreement = fetch_agreement(agreement["id"])
    assert swept_agreement["lifecycle_status"] == "EXPIRED", (
        "a term ending 2026-12-31 must expire on a move to 2027-02-01, got "
        f"{swept_agreement['lifecycle_status']}"
    )
    swept_window = fetch_window(window["id"])
    assert swept_window["status"] == "EXPIRED", (
        f"a cleared window whose end has passed must expire, got {swept_window['status']}"
    )
    swept_commitment = fetch_commitment(commitment["id"])
    assert swept_commitment["status"] == "FORFEITED", (
        f"an unearned commitment past its deadline must forfeit, got {swept_commitment['status']}"
    )
    assert swept_commitment["forfeited_cents"] == 1_000_000, (
        f"the whole remainder forfeits, got {swept_commitment['forfeited_cents']}"
    )
    assert swept_commitment["remaining_cents"] == 0, (
        f"forfeiture drives remaining_cents to 0, got {swept_commitment['remaining_cents']}"
    )
    assert swept_commitment["earned_cents"] == 0, (
        f"nothing was ever earned on the line, got {swept_commitment['earned_cents']}"
    )
    assert (
        swept_commitment["committed_cents"]
        == swept_commitment["earned_cents"]
        + swept_commitment["remaining_cents"]
        + swept_commitment["forfeited_cents"]
    ), "the conserved-quantity identity must still hold after forfeiture"
    swept_title = fetch_title(title["id"])
    assert swept_title["cleared_window_count"] == 0, (
        f"the expired window leaves no cleared window, got {swept_title['cleared_window_count']}"
    )
    assert swept_title["distribution_coverage_status"] == "UNDISTRIBUTED", (
        f"an empty platform set re-derives to UNDISTRIBUTED, got {swept_title['distribution_coverage_status']}"
    )

    validate_error(
        api.set_clock(clock_payload("2027-02-01T00:00:00Z"), ADMIN),
        ApiErrorId.ERR_CLOCK_MUST_MOVE_FORWARD.value,
        422,
    )
    validate_error(
        api.set_clock(clock_payload("2026-08-01T00:00:00Z"), ADMIN),
        ApiErrorId.ERR_CLOCK_MUST_MOVE_FORWARD.value,
        422,
    )
    assert read_clock()["current_utc"] == advanced, (
        f"a refused clock call must leave the clock at {advanced}"
    )


# ===========================================================================
# The settlement summary is a projection
# ===========================================================================
def test_settlement_summary_reconciles_against_its_component_rows(api):
    """PRD §3.8: "It reports the `agreement_id`; the agreement's stored
    `recognized_revenue_cents`; `accepted_report_fee_total_cents`, the sum of
    `license_fee_due_cents` across that agreement's reports in `ACCEPTED` or
    `AUDIT_ADJUSTED` status; `invoiced_gross_total_cents`, the sum of
    `gross_license_fee_cents` across that agreement's invoices other than those in
    `VOID`; `open_receivable_cents`, the sum of `net_due_cents` less `paid_cents`
    across that agreement's invoices in `ISSUED` or `PARTIALLY_PAID`; and four
    marketing roll-ups across the agreement's commitment lines —
    `marketing_committed_cents`, `marketing_earned_cents`,
    `marketing_remaining_cents` and `marketing_forfeited_cents`, each the sum of
    the corresponding per-line field."
    PRD §3.8: "It closes with two booleans: `marketing_conserved_identity_holds`,
    true when every one of those lines satisfies committed equals earned plus
    remaining plus forfeited, and `revenue_identity_holds`, true when
    `recognized_revenue_cents` equals `accepted_report_fee_total_cents`."

    Design: Corner/cross_cutting_complexity_layers/settlement_summary_reconciles_against_its_component_rows
    """
    distributor, agreement = setup_executed_agreement(CLIFFSIDE, TERMS)
    commitment = create_commitment(
        agreement["id"],
        commitment_type="COOP_ADVERTISING",
        committed_cents=1_000_000,
        performance_deadline="2026-12-01T00:00:00Z",
    )
    earn_commitment(commitment["id"], 400_000, proof_reference="COOP-2026-Q3")
    report = file_report(
        agreement["id"],
        distributor["id"],
        period_month="2026-06",
        reported_subscribers=130_000,
        reported_tier="BASIC",
    )
    accept_report(report["id"])

    summary = validate_success(api.get_settlement_summary(agreement["id"], ACCOUNTANT))

    assert summary["agreement_id"] == agreement["id"], "the summary names its agreement"
    assert summary["accepted_report_fee_total_cents"] == 5_200_000, (
        "one accepted 2026-06 report of 5200000 is the whole accepted total, got "
        f"{summary['accepted_report_fee_total_cents']}"
    )
    rows, _meta = validate_paginated(
        api.list_subscriber_reports(
            ACCOUNTANT, params={"agreement_id": agreement["id"], "status": "ACCEPTED", "limit": 100}
        )
    )
    assert summary["accepted_report_fee_total_cents"] == sum(
        row["license_fee_due_cents"] for row in rows
    ), "the accepted total must equal the sum over the accepted report rows"
    assert summary["recognized_revenue_cents"] == 5_200_000, (
        f"recognised revenue follows the accepted fee, got {summary['recognized_revenue_cents']}"
    )
    assert summary["recognized_revenue_cents"] == fetch_agreement(agreement["id"])[
        "recognized_revenue_cents"
    ], "the summary must never diverge from the agreement's own stored figure"
    assert summary["invoiced_gross_total_cents"] == 0, (
        f"nothing has been invoiced yet, got {summary['invoiced_gross_total_cents']}"
    )
    assert summary["open_receivable_cents"] == 0, (
        f"no invoice is issued, so no receivable is open, got {summary['open_receivable_cents']}"
    )
    assert summary["marketing_committed_cents"] == 1_000_000, (
        f"one commitment line of 1000000, got {summary['marketing_committed_cents']}"
    )
    assert summary["marketing_earned_cents"] == 400_000, (
        f"400000 of proof was accepted, got {summary['marketing_earned_cents']}"
    )
    assert summary["marketing_remaining_cents"] == 600_000, (
        f"600000 is still open to earn, got {summary['marketing_remaining_cents']}"
    )
    assert summary["marketing_forfeited_cents"] == 0, (
        f"no deadline has passed, got {summary['marketing_forfeited_cents']}"
    )
    assert summary["marketing_conserved_identity_holds"] is True, (
        "1000000 equals 400000 plus 600000 plus 0, so the conserved identity holds"
    )
    assert summary["revenue_identity_holds"] is True, (
        "recognised revenue equals the accepted report fee total, so the revenue identity holds"
    )

    second = validate_success(api.get_settlement_summary(agreement["id"], ACCOUNTANT))
    assert second == summary, (
        "a projection read twice with no intervening write must return the same values"
    )

    invoice = draft_invoice(distributor["id"], agreement["id"], "2026-06")
    issue_invoice(invoice["id"])

    after = validate_success(api.get_settlement_summary(agreement["id"], ACCOUNTANT))
    assert after["invoiced_gross_total_cents"] == 5_200_000, (
        f"the issued invoice's gross rolls up, got {after['invoiced_gross_total_cents']}"
    )
    assert after["open_receivable_cents"] == 4_800_000, (
        "5200000 gross less the 400000 co-op offset is a 4800000 open receivable, got "
        f"{after['open_receivable_cents']}"
    )
    assert after["marketing_earned_cents"] == 400_000, (
        f"billing an offset does not un-earn it, got {after['marketing_earned_cents']}"
    )
    assert after["marketing_remaining_cents"] == 600_000, (
        f"the remainder still stands at 600000, got {after['marketing_remaining_cents']}"
    )
    assert after["marketing_conserved_identity_holds"] is True, (
        "the conserved identity must still hold after issuance"
    )
    assert after["revenue_identity_holds"] is True, (
        "the revenue identity must still hold after issuance"
    )


# ===========================================================================
# Immediacy: cascades and refusals
# ===========================================================================
def test_every_cascade_is_visible_in_the_same_request(api):
    """PRD §2.9: "The rule is that every entity a cascade touches has its
    `updated_at` refreshed and its `version` incremented, exactly as if it had been
    addressed directly, and that cascades run to completion within the originating
    request — there is no deferred or eventual settlement anywhere in this system."
    PRD §3.5: "When `penetration_breach_count` reaches two while the agreement's
    `lifecycle_status` is `EXECUTED`, the agreement is automatically suspended with
    `suspension_reason` of `PENETRATION_BREACH`, dragging the rights-window and
    content-title cascade behind it."
    PRD §3.2: "Whichever route fires, the same cascade follows: every rights window
    of the agreement in `CLEARED` or `ACTIVE` moves to `BLOCKED` with
    `block_reason` of `AGREEMENT_SUSPENDED`, processed in `window_start` ascending
    then `created_at` ascending order, and every content title those windows
    belonged to re-derives `cleared_window_count` and
    `distribution_coverage_status`."
    PRD §3.4: "Under the **final** variant, stamped at acceptance into
    `billable_subscribers` and `license_fee_due_cents`, the billable count is the
    greater of `reported_subscribers` and the floor subscriber count."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_same_request
    """
    distributor, agreement, title, window = setup_cleared_window(
        CLIFFSIDE,
        TERMS,
        {"title": "Night Circuit", "linear_premiere_at": "2026-01-15T00:00:00Z"},
        {
            "platform": "LINEAR",
            "territory_code": "US",
            "window_start": "2026-10-01T00:00:00Z",
            "window_end": "2026-10-08T00:00:00Z",
            "exclusivity": "NON_EXCLUSIVE",
        },
    )
    first = file_report(
        agreement["id"],
        distributor["id"],
        period_month="2026-05",
        reported_subscribers=90_000,
        reported_tier="BASIC",
    )
    accept_report(first["id"])

    after_first = fetch_agreement(agreement["id"])
    assert after_first["penetration_breach_count"] == 1, (
        f"one non-compliant period is one breach, got {after_first['penetration_breach_count']}"
    )
    assert after_first["lifecycle_status"] == "EXECUTED", (
        f"a single breach is not yet enough to suspend, got {after_first['lifecycle_status']}"
    )

    second = file_report(
        agreement["id"],
        distributor["id"],
        period_month="2026-06",
        reported_subscribers=95_000,
        reported_tier="BASIC",
    )

    accepted = validate_success(
        api.review_subscriber_report(second["id"], {"action": "ACCEPT"}, ACCOUNTANT)
    )
    assert accepted["status"] == "ACCEPTED", (
        f"the second period is accepted, got {accepted['status']}"
    )
    assert accepted["license_fee_due_cents"] == 4_000_000, (
        "the billable count is the 100,000 floor rather than the reported 95,000, so the "
        f"fee is 4000000, got {accepted['license_fee_due_cents']}"
    )

    suspended = fetch_agreement(agreement["id"])
    assert suspended["lifecycle_status"] == "SUSPENDED", (
        "the first read after the breaching acceptance already shows SUSPENDED, got "
        f"{suspended['lifecycle_status']}"
    )
    assert suspended["suspension_reason"] == "PENETRATION_BREACH", (
        f"the automatic suspension records PENETRATION_BREACH, got {suspended['suspension_reason']}"
    )
    assert suspended["penetration_breach_count"] == 2, (
        f"two non-compliant periods are two breaches, got {suspended['penetration_breach_count']}"
    )

    blocked = fetch_window(window["id"])
    assert blocked["status"] == "BLOCKED", (
        f"the first read of the window already shows BLOCKED, got {blocked['status']}"
    )
    assert blocked["block_reason"] == "AGREEMENT_SUSPENDED", (
        f"the block records AGREEMENT_SUSPENDED, got {blocked['block_reason']}"
    )

    rederived = fetch_title(title["id"])
    assert rederived["cleared_window_count"] == 0, (
        f"the blocked window leaves no cleared window, got {rederived['cleared_window_count']}"
    )
    assert rederived["distribution_coverage_status"] == "UNDISTRIBUTED", (
        "an empty platform set re-derives to UNDISTRIBUTED, got "
        f"{rederived['distribution_coverage_status']}"
    )

    summary = validate_success(api.get_settlement_summary(agreement["id"], ACCOUNTANT))
    assert summary["recognized_revenue_cents"] == 8_000_000, (
        "both periods bill at the 100,000 floor, so 4000000 plus 4000000, got "
        f"{summary['recognized_revenue_cents']}"
    )
    assert summary["revenue_identity_holds"] is True, (
        "recognised revenue still equals the accepted report fee total in the same read window"
    )


def test_refused_writes_leave_no_partial_state(api):
    """PRD §3.6: "A `NON_EXCLUSIVE` grant tolerates non-exclusive company but not
    exclusive company. If any neighbour is itself `EXCLUSIVE`, the clearance is
    refused with `ERR_WINDOW_EXCLUSIVITY_CONFLICT`."
    PRD §3.6: "`cleared_window_count` is the number of that title's windows whose
    `status` is `CLEARED` or `ACTIVE`."
    PRD §3.6: "Clearing a window moves it `PLANNED → CLEARED`, increments the
    title's `cleared_window_count` by one and re-derives
    `distribution_coverage_status`."
    PRD §2.8: "The first rule that fails decides the response, and no side effect
    of the requested operation fires."

    Design: Corner/consistency_model/refused_writes_leave_no_partial_state
    """
    _distributor, agreement, title, incumbent = setup_cleared_window(
        MERIDIAN,
        TERMS,
        {"title": "Night Circuit", "linear_premiere_at": "2026-01-15T00:00:00Z"},
        {
            "platform": "LINEAR",
            "territory_code": "US",
            "window_start": "2026-10-01T00:00:00Z",
            "window_end": "2026-10-31T00:00:00Z",
            "exclusivity": "EXCLUSIVE",
        },
    )
    challenger = plan_window(
        agreement["id"],
        title["id"],
        platform="LINEAR",
        territory_code="US",
        window_start="2026-10-10T00:00:00Z",
        window_end="2026-10-20T00:00:00Z",
        exclusivity="NON_EXCLUSIVE",
    )
    challenger_version = challenger["version"]

    validate_error(
        api.rights_window_lifecycle(challenger["id"], {"action": "CLEAR"}, RIGHTS),
        ApiErrorId.ERR_WINDOW_EXCLUSIVITY_CONFLICT.value,
        409,
    )

    unchanged = fetch_window(challenger["id"])
    assert unchanged["status"] == "PLANNED", (
        f"the refused clearance must leave the window PLANNED, got {unchanged['status']}"
    )
    assert unchanged["version"] == challenger_version, (
        "a refused write increments nothing, so the window's version must stay at "
        f"{challenger_version}, got {unchanged['version']}"
    )

    counted = fetch_title(title["id"])
    assert counted["cleared_window_count"] == 1, (
        "only the exclusive incumbent counts as cleared, got "
        f"{counted['cleared_window_count']}"
    )
    assert counted["distribution_coverage_status"] == "LINEAR_ONLY", (
        "one cleared LINEAR window and nothing else re-derives to LINEAR_ONLY, got "
        f"{counted['distribution_coverage_status']}"
    )

    _rows, meta = validate_paginated(
        api.list_rights_windows(
            RIGHTS, params={"agreement_id": agreement["id"], "status": "CLEARED", "limit": 10}
        )
    )
    assert meta["total_count"] == 1, (
        f"exactly one window is CLEARED after the refusal, got total_count {meta['total_count']}"
    )

    undisturbed = fetch_window(incumbent["id"])
    assert undisturbed["status"] == "CLEARED", (
        f"the incumbent must be untouched by the attempt, got {undisturbed['status']}"
    )
    assert undisturbed["block_reason"] == "NONE", (
        f"the incumbent carries no block reason, got {undisturbed['block_reason']}"
    )
