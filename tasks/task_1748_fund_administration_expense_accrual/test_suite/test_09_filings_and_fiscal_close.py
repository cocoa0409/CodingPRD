"""Regulatory filing lifecycle, compliance gates, and the fiscal-year close."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_filing,
    base_kit,
    base_kit_with_final_nav,
    create_break,
    create_filing,
    create_fund,
    file_filing,
    set_logical_clock,
    submit_filing,
    make_compliance_officer_headers,
    make_fund_controller_headers,
    validate_error,
    validate_success,
)

CTRL = TEST_USERS["fund_controller_headers"]
ACCT = TEST_USERS["fund_accountant_headers"]


def test_filing_reaches_filed_twice_via_amendment_cycle(api):
    """PRD §3.9: "A filed report can later be amended: amending moves `FILED`
    to `AMENDED`, clears `approved_by_user_id`, and the amendment cycle
    re-enters at `PENDING_REVIEW` through a fresh submit-for-review."
    PRD §3.9: "Submitting for review — a `ComplianceOfficer` action available
    from `DRAFT` or `AMENDED` — moves the filing to `PENDING_REVIEW`."

    Design: Difficulty/non_linear_state_machine/regulatory_filing_amendment_cycle
    """
    set_logical_clock("2026-08-04T00:00:00Z")
    fund = create_fund()
    filing = create_filing(fund["id"], user_id="comp_1")
    assert filing["status"] == "DRAFT"

    assert submit_filing(filing["id"])["status"] == "PENDING_REVIEW"
    assert approve_filing(filing["id"])["status"] == "APPROVED"
    filed1 = file_filing(filing["id"])
    assert filed1["status"] == "FILED"

    amended = validate_success(
        api.amend_regulatory_filing(
            filing["id"], make_compliance_officer_headers("comp_1")
        ),
        200,
    )
    assert amended["status"] == "AMENDED"
    assert amended["approved_by_user_id"] is None

    assert submit_filing(filing["id"])["status"] == "PENDING_REVIEW"
    assert approve_filing(filing["id"])["status"] == "APPROVED"
    filed2 = file_filing(filing["id"])
    assert filed2["status"] == "FILED"


def test_filing_deadline_and_reapproval_approver(api):
    """PRD §3.9: "the system derives the `filing_deadline` as sixty days after
    `period_end` for `N_PORT`, `ANNUAL_REPORT`, and `SEMI_ANNUAL_REPORT`, and
    seventy-five days after for `N_CEN`."
    PRD §3.9: "stamps `filed_at` with the logical-clock timestamp, and
    recomputes `filed_after_deadline`, which is true exactly when the latest
    filing date falls strictly after the `filing_deadline`."
    PRD §3.9: "Approval sets `approved_by_user_id` and moves the filing to
    `APPROVED`."

    Design: Difficulty/non_linear_state_machine/regulatory_filing_amendment_cycle
    """
    set_logical_clock("2026-08-04T00:00:00Z")
    fund = create_fund()
    filing = create_filing(fund["id"], period_end="2026-07-31", user_id="comp_1")
    assert filing["filing_deadline"] == "2026-09-29"

    submit_filing(filing["id"])
    approve_filing(filing["id"])
    filed1 = file_filing(filing["id"])
    assert filed1["filed_after_deadline"] is False

    api.amend_regulatory_filing(filing["id"],
                                make_compliance_officer_headers("comp_1"))
    submit_filing(filing["id"])
    reapproved = approve_filing(filing["id"], user_id="ctl_1")
    assert reapproved["approved_by_user_id"] == "ctl_1"


def _escalated_break_setup(period_end):
    """Fund with an ESCALATED break and a PENDING_REVIEW filing."""
    # base_kit sets the clock to T_NAV (2026-08-04) itself; a second set to the
    # same instant would be a regression under PRD §2.4 (strictly forward).
    kit = base_kit(approve=False)
    brk = create_break(kit["fund"]["id"], kit["position"]["id"],
                       counterparty_quantity=900, break_type="BROKER_POSITION")
    set_logical_clock("2026-08-10T00:00:00Z")
    sweep = validate_success(api_client.escalate_overdue_breaks(CTRL), 200)
    filing = create_filing(kit["fund"]["id"], period_end=period_end,
                           user_id="comp_1")
    submit_filing(filing["id"])
    return kit, brk, sweep["escalated_count"], filing


def test_filing_approve_safety_gate_masks_temporal(api):
    """PRD §2.9: "Every request is validated in a fixed order, and the first
    failing check determines the error response — later checks never mask
    earlier ones."
    PRD §2.9: "8. Compliance gates — `ERR_BREAK_ESCALATED_BLOCKS` and
    `ERR_FISCAL_CLOSE_BLOCKED` (both HTTP 409)."
    PRD §2.9: "9. Temporal rules against the logical clock — the
    `ERR_PRICE_DATE_FUTURE`, `ERR_PERIOD_NOT_ENDED`,
    `ERR_DISTRIBUTION_NOT_PAYABLE`, `ERR_RECOUP_WINDOW_EXPIRED`, and
    `ERR_CLOCK_REGRESSION` family (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/filing_approve_safety_beats_temporal
    """
    # Both violations present: ESCALATED break AND period_end in the future.
    kit, brk, escalated_count, filing = _escalated_break_setup("2026-08-31")
    assert escalated_count == 1
    resp = api.approve_regulatory_filing(
        filing["id"], make_fund_controller_headers("ctl_1")
    )
    validate_error(resp, ApiErrorId.ERR_BREAK_ESCALATED_BLOCKS, 409)


def test_filing_approve_temporal_fires_once_safety_clears(api):
    """PRD §2.9: "Every request is validated in a fixed order, and the first
    failing check determines the error response — later checks never mask
    earlier ones."
    PRD §3.9: "the `period_end` must be strictly before the logical clock date
    (`ERR_PERIOD_NOT_ENDED`, HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/filing_approve_safety_beats_temporal
    """
    kit, brk, _, filing = _escalated_break_setup("2026-08-31")
    # Clear the safety gate; the temporal violation then surfaces alone.
    api.resolve_reconciliation_break(brk["id"], {"resolution_type": "NO_CHANGE"},
                                     CTRL)
    resp = api.approve_regulatory_filing(
        filing["id"], make_fund_controller_headers("ctl_1")
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_ENDED, 422)


def test_filing_approve_blocked_by_escalated_break(api):
    """PRD §3.9: "Approval is reserved to the `FundController` and carries
    three gates: the caller must differ from `prepared_by_user_id`
    (`ERR_SOD_VIOLATION`); no reconciliation break of the fund may stand
    `ESCALATED` (`ERR_BREAK_ESCALATED_BLOCKS`); and the `period_end` must be
    strictly before the logical clock date (`ERR_PERIOD_NOT_ENDED`,
    HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/filing_approve_blocked_by_escalated_break
    """
    kit, brk, escalated_count, filing = _escalated_break_setup("2026-07-31")
    assert escalated_count == 1
    resp = api.approve_regulatory_filing(
        filing["id"], make_fund_controller_headers("ctl_1")
    )
    validate_error(resp, ApiErrorId.ERR_BREAK_ESCALATED_BLOCKS, 409)


def test_filing_approve_unblocked_after_break_resolved(api):
    """PRD §3.8: "Escalation has teeth: while any break of a fund stands
    `ESCALATED`, approval and filing of that fund's regulatory filings are
    blocked with `ERR_BREAK_ESCALATED_BLOCKS` (HTTP 409), and the fiscal-year
    close refuses to run (§3.9)."
    PRD §3.8: "Resolution is a `FundController` action available from either
    `OPEN` or `ESCALATED`, moving the break to `RESOLVED` with a
    `resolution_type` of `NO_CHANGE` or `ADJUST_POSITION`."

    Design: Difficulty/cross_entity_state_dependency/filing_approve_blocked_by_escalated_break
    """
    kit, brk, _, filing = _escalated_break_setup("2026-07-31")
    resolved = validate_success(
        api.resolve_reconciliation_break(brk["id"],
                                         {"resolution_type": "NO_CHANGE"}, CTRL),
        200,
    )
    assert resolved["status"] == "RESOLVED"
    position = validate_success(api.get_position(kit["position"]["id"], CTRL), 200)
    assert position["quantity"] == 1000  # NO_CHANGE leaves the books standing
    approved = api.approve_regulatory_filing(
        filing["id"], make_fund_controller_headers("ctl_1")
    )
    assert validate_success(approved, 200)["status"] == "APPROVED"


def test_filing_period_not_ended_rejected(api):
    """PRD §3.9: "Approval is reserved to the `FundController` and carries
    three gates: the caller must differ from `prepared_by_user_id`
    (`ERR_SOD_VIOLATION`); no reconciliation break of the fund may stand
    `ESCALATED` (`ERR_BREAK_ESCALATED_BLOCKS`); and the `period_end` must be
    strictly before the logical clock date (`ERR_PERIOD_NOT_ENDED`,
    HTTP 422)."

    Design: Corner/validations/filing_period_not_ended_rejected
    """
    set_logical_clock("2026-08-04T00:00:00Z")
    fund = create_fund()
    filing = create_filing(fund["id"], period_end="2026-08-31", user_id="comp_1")
    submit_filing(filing["id"])
    resp = api.approve_regulatory_filing(
        filing["id"], make_fund_controller_headers("ctl_1")
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_ENDED, 422)


def test_controller_who_prepared_cannot_approve_filing(api):
    """PRD §2.7: "On each, the caller's `X-User-ID` must differ from the
    identifier of the user who prepared the resource — the accounting record's
    `created_by_user_id`, the invoice's `created_by_user_id`, or the filing's
    `prepared_by_user_id`. A caller who prepared the resource is rejected with
    `ERR_SOD_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/controller_who_prepared_cannot_approve_filing
    """
    set_logical_clock("2026-08-04T00:00:00Z")
    fund = create_fund()
    filing = create_filing(fund["id"], period_end="2026-07-31", user_id="comp_9")
    assert filing["prepared_by_user_id"] == "comp_9"
    submit_filing(filing["id"], user_id="comp_9")

    same_user = api.approve_regulatory_filing(
        filing["id"], make_fund_controller_headers("comp_9")
    )
    validate_error(same_user, ApiErrorId.ERR_SOD_VIOLATION, 403)

    other = api.approve_regulatory_filing(
        filing["id"], make_fund_controller_headers("ctl_1")
    )
    assert validate_success(other, 200)["status"] == "APPROVED"


def test_fiscal_close_blocked_by_open_break(api):
    """PRD §3.9: "Three blockers then stand in the way, each surfacing as
    `ERR_FISCAL_CLOSE_BLOCKED` (HTTP 409): every accounting record of the
    fund's classes falling in the fiscal year must be `FINAL`; no break of the
    fund may stand `OPEN` or `ESCALATED`; and every regulatory filing whose
    `period_end` lies in the fiscal year must be `FILED`."

    Design: Corner/validations/fiscal_close_blocked_by_open_break
    """
    kit = base_kit_with_final_nav()
    create_break(kit["fund"]["id"], kit["position"]["id"],
                 counterparty_quantity=900, break_type="BROKER_POSITION")
    set_logical_clock("2027-01-15T00:00:00Z")
    resp = api.close_fiscal_year(
        kit["fund"]["id"], {"fiscal_year_end_date": "2026-12-31"}, CTRL
    )
    validate_error(resp, ApiErrorId.ERR_FISCAL_CLOSE_BLOCKED, 409)


def test_reopen_after_fiscal_close_rejected(api):
    """PRD §3.9: "A successful close records the date in the fund's
    `last_closed_fiscal_year_end`, and from that moment the closed year's
    accounting records can no longer be reopened"
    PRD §3.6: "a record inside a closed year is rejected with
    `ERR_NAV_LOCKED_FISCAL_CLOSED` (HTTP 409)."

    Design: Corner/state_machines/reopen_after_fiscal_close_rejected
    """
    kit = base_kit_with_final_nav()
    set_logical_clock("2027-01-15T00:00:00Z")
    closed = validate_success(
        api.close_fiscal_year(
            kit["fund"]["id"], {"fiscal_year_end_date": "2026-12-31"}, CTRL
        ),
        200,
    )
    assert closed["last_closed_fiscal_year_end"] == "2026-12-31"

    resp = api.reopen_nav_record(kit["nav"]["id"], CTRL)
    validate_error(resp, ApiErrorId.ERR_NAV_LOCKED_FISCAL_CLOSED, 409)
