"""State-machine compliance tests: initial states, guarded and invalid transitions,
terminal-state lockdown, the two independent letter dimensions, the aggregate closure
condition, cross-entity bubble-ups and the abandonment fan-out.

Each test builds every precondition it needs through the API, because the harness
restarts the server and empties the registry before every individual test.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_field,
    assert_money_equals,
    assert_null,
    find_by_id,
)
from test_helpers.constants import DEFAULT_CLOCK_ISO
from test_helpers.test_users import (
    CHARITIES_REGULATOR,
    DILIGENCE_LEAD,
    DILIGENCE_LEAD_2,
    INTEGRATION_MANAGER,
    PLATFORM_ADMIN,
    TRUST_COUNSEL,
    make_strategy_officer_headers,
)


def _letter(api, deal_id, letter_id):
    """Re-read one letter of intent through its deal-scoped list."""
    rows, _ = validate_paginated(api.list_deal_letters_of_intent(deal_id, PLATFORM_ADMIN))
    row = find_by_id(rows, letter_id)
    assert row is not None, f"letter {letter_id} must still be listed under deal {deal_id}"
    return row


def _finding(api, deal_id, finding_id):
    """Re-read one diligence finding through its deal-scoped list."""
    rows, _ = validate_paginated(api.list_deal_diligence_requests(deal_id, PLATFORM_ADMIN))
    row = find_by_id(rows, finding_id)
    assert row is not None, f"finding {finding_id} must still be listed under deal {deal_id}"
    return row


def _approval(api, deal_id, approval_id):
    """Re-read one board resolution through its deal-scoped list."""
    rows, _ = validate_paginated(api.list_deal_board_approvals(deal_id, PLATFORM_ADMIN))
    row = find_by_id(rows, approval_id)
    assert row is not None, f"approval {approval_id} must still be listed under deal {deal_id}"
    return row


def _filing(api, deal_id, filing_id):
    """Re-read one attorney-general filing through its deal-scoped list."""
    rows, _ = validate_paginated(api.list_deal_ag_filings(deal_id, PLATFORM_ADMIN))
    row = find_by_id(rows, filing_id)
    assert row is not None, f"filing {filing_id} must still be listed under deal {deal_id}"
    return row


def test_new_deal_opens_exploratory_in_round_one_with_zeroed_ledgers(api):
    """A newly opened deal starts EXPLORATORY in round 1 with every derived ledger at zero.

    PRD 3.2 states that a newly opened deal is EXPLORATORY, with round_no at 1,
    combined_board_seats and reserved_seat_pool at 0, unrestricted_transfer_value_cents
    at 0, unresolved_restricted_fund_count at 0, restricted_asset_posture at
    NOT_ASSESSED, structure_type null, abandonment_reason null and version at 1.
    ag_review_required is fixed at creation, and is true when either party's state_code
    is one of CA, NY, MA, IL or WA; both parties here are incorporated in CA.

    Design: Corner/state_machines/restructuring_initial_state_is_exploratory_with_round_one
    """
    ctx = fx.setup_two_orgs(api)
    payload = f.restructuring_payload(
        ctx["org_a"]["id"], ctx["org_b"]["id"], confidentiality_tier="RESTRICTED"
    )
    deal = validate_success(
        api.create_restructuring(payload, make_strategy_officer_headers(ctx["org_a"]["id"])), 201
    )

    assert_field(deal, "status", "EXPLORATORY")
    assert_field(deal, "round_no", 1)
    assert_field(deal, "version", 1)
    assert_null(deal, "structure_type")
    assert_null(deal, "abandonment_reason")
    assert_field(deal, "combined_board_seats", 0)
    assert_field(deal, "reserved_seat_pool", 0)
    assert_money_equals(
        deal["unrestricted_transfer_value_cents"], 0, "unrestricted_transfer_value_cents"
    )
    assert_field(deal, "unresolved_restricted_fund_count", 0)
    assert_field(deal, "restricted_asset_posture", "NOT_ASSESSED")
    assert_field(deal, "ag_review_required", True)
    assert_field(deal, "confidentiality_tier", "RESTRICTED")


def test_letter_execution_seeds_the_reserved_seat_pool_and_opens_diligence(api):
    """Countersigning an ISSUED letter opens diligence and seeds the deal's seat ledger.

    PRD 3.3 states that on success the letter moves ISSUED to EXECUTED, records
    executed_at from the logical clock, and keeps exclusivity_status at ACTIVE for the
    remaining life of the deal; in the same request the deal advances LOI_NEGOTIATION to
    DILIGENCE, copies the letter's combined_board_seats into its own, and seeds
    reserved_seat_pool to that same number, with both versions rising by one. PRD 3.3
    also fixes the closed window: exclusivity_end_date is the start advanced by
    exclusivity_days minus one calendar day, and expires_at renders that date at
    00:00:00.000Z, so a 60-day window opened on 2026-08-01 ends on 2026-09-29.

    Design: Corner/state_machines/letter_execution_seeds_the_reserved_seat_pool_and_opens_diligence
    """
    ctx = fx.setup_deal_loi_negotiation(api)
    letter = validate_success(
        api.execute_letter_of_intent(
            ctx["loi"]["id"],
            f.execute_payload(executed_note="Countersigned by the target board chair"),
            make_strategy_officer_headers(ctx["org_b"]["id"]),
        )
    )

    assert_field(letter, "status", "EXECUTED")
    assert_field(letter, "exclusivity_status", "ACTIVE")
    assert_field(letter, "executed_at", DEFAULT_CLOCK_ISO)
    assert_field(letter, "exclusivity_end_date", "2026-09-29")
    assert_field(letter, "expires_at", "2026-09-29T00:00:00.000Z")
    assert_field(letter, "version", 2)

    deal = fx.read_deal(api, ctx["deal"]["id"])
    assert_field(deal, "status", "DILIGENCE")
    assert_field(deal, "combined_board_seats", 15)
    assert_field(deal, "reserved_seat_pool", 15)


def test_second_execution_of_the_same_letter_is_refused_as_invalid_letter_state(api):
    """An already EXECUTED letter cannot be countersigned twice.

    PRD 3.3 admits execution only against an ISSUED letter, and PRD 2.7 rule 17 refuses a
    request whose LetterOfIntent.status does not permit the operation with
    ERR_INVALID_LETTER_STATE. The refusal must leave the letter and the deal exactly as
    the first execution left them, so executed_at is not restamped and reserved_seat_pool
    is not seeded a second time.

    Design: Corner/state_machines/second_execute_of_the_same_letter_is_refused_as_invalid_letter_state
    """
    ctx = fx.setup_deal_diligence(api)
    deal_id = ctx["deal"]["id"]

    validate_error(
        api.execute_letter_of_intent(
            ctx["loi"]["id"],
            f.execute_payload(),
            make_strategy_officer_headers(ctx["org_b"]["id"]),
        ),
        "ERR_INVALID_LETTER_STATE",
        409,
    )

    letter = _letter(api, deal_id, ctx["loi"]["id"])
    assert_field(letter, "status", "EXECUTED")
    assert_field(letter, "exclusivity_status", "ACTIVE")
    assert_field(letter, "executed_at", DEFAULT_CLOCK_ISO)
    assert_field(letter, "version", 2)

    deal = fx.read_deal(api, deal_id)
    assert_field(deal, "status", "DILIGENCE")
    assert_field(deal, "combined_board_seats", 15)
    assert_field(deal, "reserved_seat_pool", 15)


def test_judicially_retained_fund_refuses_both_transfer_and_unwind(api):
    """A fund the court refused to release is terminal: neither transfer nor unwind moves it.

    PRD 3.6 states that on a DENIED court answer the fund moves PETITION_FILED to
    RETAINED, which is terminal, with transferable_amount_cents at 0 and
    retained_amount_cents set to the whole fund value; a RETAINED fund counts as resolved
    and no longer blocks. PRD 2.7 rule 18 refuses both transfer and unwind against such a
    row with ERR_INVALID_FUND_STATE, and on transfer that rule explicitly covers the two
    already-final dispositions rather than deferring to the missing-authority rule.

    Design: Corner/state_machines/retained_fund_locks_out_both_transfer_and_unwind
    """
    ctx = fx.setup_deal_structure_selected(api)
    deal_id = ctx["deal"]["id"]
    fund = fx.create_fund(
        api,
        ctx["org_a"]["id"],
        fund_name="Ellsworth Legacy Fund",
        fund_type="TEMP_RESTRICTED",
        principal_cents=50000000,
        accumulated_appreciation_cents=12000000,
        historic_dollar_value_cents=0,
        restriction_purpose_code="TU-TUTORING",
        restriction_conflict=True,
        donor_of_record_reachable=False,
    )
    validate_success(
        api.file_petition(
            fund["id"],
            f.file_petition_payload(
                petition_basis="DONOR_UNREACHABLE", court_docket_no="ALA-2026-PR-0417"
            ),
            TRUST_COUNSEL,
        )
    )
    denial = f.court_decision_payload("DENIED")
    denial.pop("modified_purpose_code")
    fund = validate_success(api.record_court_decision(fund["id"], denial, TRUST_COUNSEL))
    assert_field(fund, "transfer_status", "RETAINED")

    validate_error(
        api.transfer_restricted_fund(
            fund["id"], f.transfer_payload(deal_id, "JUDICIAL_MODIFICATION"), TRUST_COUNSEL
        ),
        "ERR_INVALID_FUND_STATE",
        409,
    )
    validate_error(
        api.unwind_restricted_fund(fund["id"], f.unwind_payload(), TRUST_COUNSEL),
        "ERR_INVALID_FUND_STATE",
        409,
    )

    fund = validate_success(api.get_restricted_fund(fund["id"], TRUST_COUNSEL))
    assert_field(fund, "transfer_status", "RETAINED")
    assert_field(fund, "court_decision", "DENIED")
    assert_field(fund, "unwind_count", 0)
    assert_money_equals(fund["transferable_amount_cents"], 0, "transferable_amount_cents")
    assert_money_equals(fund["transferred_amount_cents"], 0, "transferred_amount_cents")
    assert_money_equals(fund["retained_amount_cents"], 62000000, "retained_amount_cents")
    assert_null(fund, "transferred_to_org_id")
    assert_null(fund, "transfer_restructuring_id")

    org_a = validate_success(api.get_organization(ctx["org_a"]["id"], PLATFORM_ADMIN))
    org_b = validate_success(api.get_organization(ctx["org_b"]["id"], PLATFORM_ADMIN))
    assert_money_equals(org_a["restricted_corpus_cents"], 62000000, "restricted_corpus_cents")
    assert_money_equals(org_b["restricted_corpus_cents"], 0, "restricted_corpus_cents")

    deal = fx.read_deal(api, deal_id)
    assert_field(deal, "unresolved_restricted_fund_count", 0)
    assert_field(deal, "restricted_asset_posture", "CLEARED")


def test_clearing_a_finding_that_was_never_responded_to_is_refused(api):
    """Clearance is admitted only from RESPONDED, and works once the answer is on record.

    PRD 3.4 states that a DiligenceLead whose X-User-ID differs from the finding's
    raised_by_user_id clears a RESPONDED finding with a clearance_note, and that all four
    finding actions share one status guard: clear requires RESPONDED, so an OPEN row is
    refused with ERR_INVALID_DILIGENCE_STATE (PRD 2.7 rule 22). Once the counterparty has
    answered, the same clearance succeeds, records cleared_by_user_id as the acting user,
    and re-evaluates the deal's closure condition — with every finding CLEARED the deal
    advances DILIGENCE to DILIGENCE_CLOSED.

    Design: Corner/state_machines/clearing_a_finding_that_was_never_responded_to_is_refused
    """
    ctx = fx.setup_deal_diligence(api)
    deal_id = ctx["deal"]["id"]
    finding = validate_success(
        api.create_diligence_request(
            f.diligence_request_payload(
                deal_id,
                workstream="CONTRACTS",
                severity="MEDIUM",
                summary="Facility lease lacks an assignment clause",
                exposure_cents=1500000,
            ),
            DILIGENCE_LEAD,
        ),
        201,
    )
    assert_field(finding, "status", "OPEN")

    validate_error(
        api.clear_diligence_request(finding["id"], f.diligence_clear_payload(), DILIGENCE_LEAD_2),
        "ERR_INVALID_DILIGENCE_STATE",
        409,
    )
    unchanged = _finding(api, deal_id, finding["id"])
    assert_field(unchanged, "status", "OPEN")
    assert_field(unchanged, "version", 1)
    assert_null(unchanged, "cleared_by_user_id")
    assert_field(fx.read_deal(api, deal_id), "status", "DILIGENCE")

    responded = validate_success(
        api.respond_diligence_request(
            finding["id"],
            f.diligence_respond_payload(),
            make_strategy_officer_headers(ctx["org_a"]["id"]),
        )
    )
    assert_field(responded, "status", "RESPONDED")

    cleared = validate_success(
        api.clear_diligence_request(finding["id"], f.diligence_clear_payload(), DILIGENCE_LEAD_2)
    )
    assert_field(cleared, "status", "CLEARED")
    assert_field(cleared, "cleared_by_user_id", "dl-002")
    assert_field(cleared, "version", 3)
    assert_field(fx.read_deal(api, deal_id), "status", "DILIGENCE_CLOSED")


def test_letter_counter_by_the_issuing_party_is_refused_then_the_target_succeeds(api):
    """Countering belongs to the target organization alone, and leaves exclusivity untouched.

    PRD 3.3 states that countering is the target organization's move, and PRD 2.7 rule 13
    refuses the other party with ERR_NOT_DEAL_PARTY where a workflow names one specific
    party. On the target's counter the letter moves ISSUED to COUNTERED, records
    countered_by_party and increments counter_round_count, while PRD 3.3 stresses that the
    two dimensions evolve without regard for one another: a counter flips status while
    exclusivity_status remains ACTIVE, and the deal stays in LOI_NEGOTIATION.

    Design: Corner/state_machines/letter_counter_by_the_issuing_party_is_refused_then_the_target_succeeds
    """
    ctx = fx.setup_deal_loi_negotiation(api)
    deal_id = ctx["deal"]["id"]

    validate_error(
        api.counter_letter_of_intent(
            ctx["loi"]["id"], f.counter_payload(), make_strategy_officer_headers(ctx["org_a"]["id"])
        ),
        "ERR_NOT_DEAL_PARTY",
        403,
    )
    unchanged = _letter(api, deal_id, ctx["loi"]["id"])
    assert_field(unchanged, "status", "ISSUED")
    assert_field(unchanged, "counter_round_count", 0)
    assert_null(unchanged, "countered_by_party")
    assert_field(unchanged, "version", 1)

    countered = validate_success(
        api.counter_letter_of_intent(
            ctx["loi"]["id"], f.counter_payload(), make_strategy_officer_headers(ctx["org_b"]["id"])
        )
    )
    assert_field(countered, "status", "COUNTERED")
    assert_field(countered, "countered_by_party", "TARGET")
    assert_field(countered, "counter_round_count", 1)
    assert_field(countered, "exclusivity_status", "ACTIVE")
    assert_field(countered, "version", 2)
    assert_field(fx.read_deal(api, deal_id), "status", "LOI_NEGOTIATION")


def test_abandonment_cascades_to_letters_approvals_tasks_and_transferred_funds(api):
    """Abandoning a deal dismantles its live records across all four child collections.

    PRD 3.9 states that the acting officer's abandonment_reason is stored alongside the new
    ABANDONED status, and that abandonment then dismantles the deal's live records: every
    letter in ISSUED, COUNTERED or EXECUTED becomes WITHDRAWN with exclusivity_status
    RELEASED; every board approval in RECORDED or CERTIFIED becomes SUPERSEDED, returning
    its allocated_seats to reserved_seat_pool, zeroing its own allocated_seats and
    resetting governance_seats to 0 on that party; every task in PLANNED, HELD or
    IN_PROGRESS becomes CANCELLED; and every restricted fund of this deal in TRANSFERRED is
    unwound exactly as a deliberate unwind would unwind it, with the conditional return
    state, the restored pair corpus, unwind_count increased and transferable_amount_cents
    left intact. The deal's version rises by one.

    Design: Corner/state_machines/abandon_cascades_to_letters_approvals_tasks_and_transferred_funds
    """
    ctx = fx.setup_deal_regulatory_review(api)
    deal_id = ctx["deal"]["id"]
    fund = fx.setup_fund_consent_granted(api, ctx["org_a"]["id"])
    fund = fx.transfer_fund(api, fund["id"], deal_id, "DONOR_CONSENT")
    assert_field(fund, "transfer_status", "TRANSFERRED")
    task = fx.create_task(
        api,
        deal_id,
        workstream="STAFFING",
        crew_code="CREW-HR",
        title="Map duplicate development roles",
        planned_start_date="2026-09-01",
        planned_end_date="2026-09-10",
    )
    assert_field(task, "status", "PLANNED")
    version_before = fx.deal_version(api, deal_id)

    deal = validate_success(
        api.abandon(
            deal_id,
            f.abandon_payload(abandonment_reason="Target board withdrew from the transaction"),
            make_strategy_officer_headers(ctx["org_a"]["id"]),
        )
    )
    assert_field(deal, "status", "ABANDONED")
    assert_field(deal, "abandonment_reason", "Target board withdrew from the transaction")
    assert_field(deal, "version", version_before + 1)
    assert_field(deal, "reserved_seat_pool", 15)
    assert_field(deal, "combined_board_seats", 15)

    letter = _letter(api, deal_id, ctx["loi"]["id"])
    assert_field(letter, "status", "WITHDRAWN")
    assert_field(letter, "exclusivity_status", "RELEASED")

    for key in ("approval_initiator", "approval_target"):
        approval = _approval(api, deal_id, ctx[key]["id"])
        assert_field(approval, "status", "SUPERSEDED")
        assert_field(approval, "allocated_seats", 0)

    assert_field(
        validate_success(api.get_integration_task(task["id"], PLATFORM_ADMIN)), "status", "CANCELLED"
    )

    fund = validate_success(api.get_restricted_fund(fund["id"], TRUST_COUNSEL))
    assert_field(fund, "transfer_status", "CONSENT_GRANTED")
    assert_field(fund, "unwind_count", 1)
    assert_null(fund, "transferred_to_org_id")
    assert_null(fund, "transfer_restructuring_id")
    assert_null(fund, "transfer_basis")
    assert_money_equals(fund["transferred_amount_cents"], 0, "transferred_amount_cents")
    assert_money_equals(fund["retained_amount_cents"], 0, "retained_amount_cents")
    assert_money_equals(fund["transferable_amount_cents"], 62000000, "transferable_amount_cents")

    org_a = validate_success(api.get_organization(ctx["org_a"]["id"], PLATFORM_ADMIN))
    org_b = validate_success(api.get_organization(ctx["org_b"]["id"], PLATFORM_ADMIN))
    assert_field(org_a, "governance_seats", 0)
    assert_field(org_b, "governance_seats", 0)
    assert_money_equals(org_a["restricted_corpus_cents"], 62000000, "restricted_corpus_cents")
    assert_money_equals(org_b["restricted_corpus_cents"], 0, "restricted_corpus_cents")

    deal = fx.read_deal(api, deal_id)
    assert_field(deal, "unresolved_restricted_fund_count", 1)
    assert_field(deal, "restricted_asset_posture", "RESTRICTED_PENDING")


def test_sweep_expires_the_exclusivity_dimension_without_touching_negotiation_status(api):
    """An elapsed confidentiality window expires while the negotiation status is left alone.

    PRD 3.9 states that the sweep expires elapsed confidentiality windows: every letter
    whose exclusivity_status is ACTIVE and whose exclusivity_end_date now falls strictly
    before the calendar date of the clock has exclusivity_status set to EXPIRED with its
    negotiation status left completely untouched, and the response reports the affected
    identifiers under expired_exclusivity_letter_of_intent_ids. PRD 3.3 confirms the two
    dimensions on the row evolve without regard for one another. A 60-day window opened on
    2026-08-01 ends on 2026-09-29, so a clock reading 2026-09-30 expires it.

    Design: Corner/state_machines/sweep_expires_the_exclusivity_dimension_without_touching_negotiation_status
    """
    ctx = fx.setup_deal_diligence(api)
    deal_id = ctx["deal"]["id"]
    clock = fx.set_clock(api, "2026-09-30T00:00:00Z")
    assert_field(clock, "previous_utc", DEFAULT_CLOCK_ISO)
    assert_field(clock, "current_utc", "2026-09-30T00:00:00.000Z")

    sweep = fx.run_sweep(api)
    assert_field(sweep, "swept_at", "2026-09-30T00:00:00.000Z")
    assert sweep["expired_exclusivity_letter_of_intent_ids"] == [ctx["loi"]["id"]], (
        "the executed letter's elapsed window must be reported as expired"
    )
    assert sweep["lapsed_letter_of_intent_ids"] == [], "an EXECUTED letter is never lapsed"
    assert sweep["deemed_approved_filing_ids"] == [], "no filing exists to deem approved"

    letter = _letter(api, deal_id, ctx["loi"]["id"])
    assert_field(letter, "status", "EXECUTED")
    assert_field(letter, "exclusivity_status", "EXPIRED")
    assert_field(letter, "executed_at", DEFAULT_CLOCK_ISO)

    deal = fx.read_deal(api, deal_id)
    assert_field(deal, "status", "DILIGENCE")
    assert_field(deal, "reserved_seat_pool", 15)


def test_sweep_lapses_an_issued_letter_at_the_exact_expiry_instant(api):
    """A letter still ISSUED lapses the moment the clock reaches its expires_at.

    PRD 3.9 states that the sweep lapses stale letters: every letter in ISSUED or COUNTERED
    whose expires_at the clock has reached or passed becomes LAPSED with exclusivity_status
    set to RELEASED, and reports it under lapsed_letter_of_intent_ids. The boundary is
    inclusive, so a window ending 2026-09-29 — rendered by PRD 3.3 as an expires_at of
    2026-09-29T00:00:00.000Z — lapses at a clock reading of exactly that instant, while the
    strictly-before calendar-date test for expiring the window is not yet satisfied.

    Design: Corner/state_machines/sweep_lapses_an_issued_letter_at_the_exact_expiry_instant
    """
    ctx = fx.setup_deal_loi_negotiation(api)
    deal_id = ctx["deal"]["id"]
    assert_field(ctx["loi"], "expires_at", "2026-09-29T00:00:00.000Z")
    fx.set_clock(api, "2026-09-29T00:00:00Z")

    sweep = fx.run_sweep(api)
    assert sweep["lapsed_letter_of_intent_ids"] == [ctx["loi"]["id"]], (
        "an ISSUED letter must lapse once the clock reaches its expires_at"
    )
    assert sweep["expired_exclusivity_letter_of_intent_ids"] == [], (
        "the end date is not strictly before the clock's calendar date"
    )
    assert sweep["deemed_approved_filing_ids"] == [], "no filing exists to deem approved"

    letter = _letter(api, deal_id, ctx["loi"]["id"])
    assert_field(letter, "status", "LAPSED")
    assert_field(letter, "exclusivity_status", "RELEASED")
    assert_field(letter, "version", 2)

    deal = fx.read_deal(api, deal_id)
    assert_field(deal, "status", "LOI_NEGOTIATION")
    assert_field(deal, "reserved_seat_pool", 0)


def test_deemed_approval_by_silence_releases_the_deal_into_integration(api):
    """An unanswered filing is approved by silence at its deadline and releases the deal.

    PRD 3.7 states that where the logical clock has reached or passed a SUBMITTED filing's
    review_deadline_at — the comparison being inclusive at the exact instant — the sweep
    moves it SUBMITTED to DEEMED_APPROVED, stamps decision_recorded_at, and releases the
    deal REGULATORY_REVIEW to INTEGRATION exactly as an express approval would; PRD 3.9
    reports the affected identifiers under deemed_approved_filing_ids. PRD 3.7 also fixes
    the deadline: a recited asset value of five million dollars or more forces an
    APPROVAL_PETITION, whose statutory_waiting_days starts at forty-five calendar days, and
    review_deadline_at is submitted_at advanced by that many days.

    Design: Corner/state_machines/ag_deemed_approval_bubbles_the_deal_into_integration
    """
    ctx = fx.setup_deal_diligence_closed(api)
    ctx = fx.setup_deal_structure_selected(
        api, ctx, unrestricted_transfer_value_cents=500000000
    )
    ctx = fx.setup_deal_board_approval(api, ctx)
    ctx = fx.setup_deal_regulatory_review(api, ctx)
    deal_id = ctx["deal"]["id"]
    assert_field(ctx["deal"], "status", "REGULATORY_REVIEW")

    filing = validate_success(
        api.create_ag_filing(
            f.ag_filing_payload(
                deal_id, filing_type="APPROVAL_PETITION", legal_costs_cents=10000000
            ),
            TRUST_COUNSEL,
        ),
        201,
    )
    assert_field(filing, "status", "SUBMITTED")
    assert_money_equals(
        filing["transferred_charitable_asset_value_cents"],
        500000000,
        "transferred_charitable_asset_value_cents",
    )
    assert_money_equals(
        filing["provisional_consideration_cents"], 510000000, "provisional_consideration_cents"
    )
    assert_money_equals(filing["ag_filing_fee_cents"], 150000, "ag_filing_fee_cents")
    assert_money_equals(filing["closing_costs_cents"], 10150000, "closing_costs_cents")
    assert_money_equals(
        filing["total_consideration_cents"], 510150000, "total_consideration_cents"
    )
    assert_field(filing, "statutory_waiting_days", 45)
    assert_field(filing, "submitted_at", DEFAULT_CLOCK_ISO)
    assert_field(filing, "review_deadline_at", "2026-09-15T00:00:00.000Z")

    fx.set_clock(api, "2026-09-15T00:00:00Z")
    sweep = fx.run_sweep(api)
    assert sweep["deemed_approved_filing_ids"] == [filing["id"]], (
        "the unanswered filing must be deemed approved at its deadline instant"
    )

    filing = _filing(api, deal_id, filing["id"])
    assert_field(filing, "status", "DEEMED_APPROVED")
    assert_field(filing, "decision_recorded_at", "2026-09-15T00:00:00.000Z")
    assert_field(fx.read_deal(api, deal_id), "status", "INTEGRATION")


def test_diligence_closes_only_once_every_finding_is_terminal(api):
    """Diligence closes on the aggregate condition, never on the first cleared finding.

    PRD 3.4 states that closing diligence is an aggregate condition rather than an explicit
    action: whenever any finding of a deal in DILIGENCE is mutated, the deal is re-examined,
    and if it has at least one finding and every one of them is either CLEARED or WAIVED the
    deal advances DILIGENCE to DILIGENCE_CLOSED with its version rising by one. With two
    findings open, clearing only the first must leave the deal in DILIGENCE.

    Design: Corner/state_machines/diligence_closure_bubbles_up_only_when_every_finding_is_terminal
    """
    ctx = fx.setup_deal_diligence(api)
    deal_id = ctx["deal"]["id"]
    officer = make_strategy_officer_headers(ctx["org_a"]["id"])
    first = validate_success(
        api.create_diligence_request(
            f.diligence_request_payload(
                deal_id,
                workstream="FINANCE",
                severity="MEDIUM",
                summary="Grant revenue recognised in the wrong period",
                exposure_cents=1500000,
            ),
            DILIGENCE_LEAD,
        ),
        201,
    )
    second = validate_success(
        api.create_diligence_request(
            f.diligence_request_payload(
                deal_id,
                workstream="CONTRACTS",
                severity="LOW",
                summary="Facility lease lacks an assignment clause",
                exposure_cents=400000,
            ),
            DILIGENCE_LEAD,
        ),
        201,
    )

    validate_success(
        api.respond_diligence_request(first["id"], f.diligence_respond_payload(), officer)
    )
    cleared_first = validate_success(
        api.clear_diligence_request(first["id"], f.diligence_clear_payload(), DILIGENCE_LEAD_2)
    )
    assert_field(cleared_first, "status", "CLEARED")
    assert_field(fx.read_deal(api, deal_id), "status", "DILIGENCE")

    validate_success(
        api.respond_diligence_request(second["id"], f.diligence_respond_payload(), officer)
    )
    cleared_second = validate_success(
        api.clear_diligence_request(second["id"], f.diligence_clear_payload(), DILIGENCE_LEAD_2)
    )
    assert_field(cleared_second, "status", "CLEARED")
    assert_field(fx.read_deal(api, deal_id), "status", "DILIGENCE_CLOSED")


def test_integration_task_start_is_guarded_by_the_deal_reaching_integration(api):
    """A task may be planned early but may not start until the deal reaches INTEGRATION.

    PRD 3.8 states that starting a task requires the task to be PLANNED and then, in ladder
    order, that the deal must have reached INTEGRATION, else ERR_INVALID_DEAL_STATE —
    planning may run early, but execution may not. On success the task moves PLANNED to
    IN_PROGRESS and stamps started_at from the logical clock. PRD 3.7 supplies the release:
    an express APPROVED decision on the deal's filing moves it SUBMITTED to APPROVED and
    releases the deal REGULATORY_REVIEW to INTEGRATION, after which the same start succeeds.

    Design: Corner/state_machines/integration_task_start_is_guarded_by_the_deal_reaching_integration
    """
    ctx = fx.setup_deal_regulatory_review(api)
    deal_id = ctx["deal"]["id"]
    assert_field(ctx["deal"], "status", "REGULATORY_REVIEW")
    task = fx.create_task(
        api,
        deal_id,
        workstream="STAFFING",
        crew_code="CREW-IT",
        title="Migrate payroll onto the surviving platform",
        planned_start_date="2026-09-01",
        planned_end_date="2026-09-08",
    )
    assert_field(task, "status", "PLANNED")
    assert_null(task, "held_reason")

    validate_error(
        api.start_integration_task(task["id"], f.start_task_payload(), INTEGRATION_MANAGER),
        "ERR_INVALID_DEAL_STATE",
        409,
    )
    blocked = validate_success(api.get_integration_task(task["id"], PLATFORM_ADMIN))
    assert_field(blocked, "status", "PLANNED")
    assert_null(blocked, "started_at")

    filing = validate_success(
        api.create_ag_filing(
            f.ag_filing_payload(deal_id, filing_type="NOTICE", legal_costs_cents=1000000),
            TRUST_COUNSEL,
        ),
        201,
    )
    assert_field(filing, "statutory_waiting_days", 20)
    assert_field(filing, "review_deadline_at", "2026-08-21T00:00:00.000Z")
    approved = validate_success(
        api.record_ag_decision(filing["id"], f.ag_decision_payload("APPROVED"), CHARITIES_REGULATOR)
    )
    assert_field(approved, "status", "APPROVED")
    assert_field(fx.read_deal(api, deal_id), "status", "INTEGRATION")

    started = validate_success(
        api.start_integration_task(task["id"], f.start_task_payload(), INTEGRATION_MANAGER)
    )
    assert_field(started, "status", "IN_PROGRESS")
    assert_field(started, "started_at", DEFAULT_CLOCK_ISO)
