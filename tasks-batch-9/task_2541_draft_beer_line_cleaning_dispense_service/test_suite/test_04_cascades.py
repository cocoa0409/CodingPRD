"""One write that reaches records the request never named."""

from test_helpers import (
    AbandonReason,
    AccountStatus,
    BillingMode,
    ComplianceFlag,
    ComplianceResult,
    ContractStatus,
    FundingStatus,
    LineStatus,
    RecordStatus,
    SuspendedReason,
    WorkStatus,
    assert_program_ledger,
    fixtures,
)

TWO_LINE_LAYOUT = (
    {
        "line_number": 1,
        "run_length_feet": 32,
        "vertical_rise_feet": 4,
        "inner_diameter_inches": 0.375,
        "beer_style_group": "ALE",
        "average_daily_throughput_liters": 12.0,
    },
    {
        "line_number": 2,
        "run_length_feet": 32,
        "vertical_rise_feet": 4,
        "inner_diameter_inches": 0.375,
        "beer_style_group": "LAGER",
        "average_daily_throughput_liters": 10.0,
    },
)

#: 0.20 L of 45.0 per cent stock in a 7 L batch achieves only 1.286 per cent.
UNDER_DOSED_CYCLE = {
    "chemical_type": "CAUSTIC",
    "contact_minutes": 30,
    "recirculation_temp_f": 96.0,
    "concentrate_liters_used": 0.20,
}


def _threshold_venue(api):
    """A two-line venue on a brewer programme, with one job open and one still booked."""
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    program = fixtures.create_brewer_program(
        api,
        brewer_name="Southside Brewing",
        funded_scope="CLEANING_ONLY",
        co_pay_bps=0,
        funding_cap_cents=100000,
    )
    ground = fixtures.setup_started_visit(
        api,
        venue_name="Threshold Tavern",
        contracted_line_count=2,
        brewer_program_id=program["id"],
        lines=TWO_LINE_LAYOUT,
    )
    ground["program"] = program
    ground["later_visit"] = fixtures.book_visit(
        api,
        ground["account"]["id"],
        ground["technician"]["id"],
        scheduled_date="2026-08-12",
        scheduled_start_minute=540,
        scheduled_end_minute=660,
    )
    return ground


def test_an_under_dosed_cycle_takes_the_line_out_and_suspends_the_venue(api):
    """PRD §3.4: "Hop two recomputes the owning account's
    `lines_out_of_service_count` and applies the compliance threshold: when twice that
    count is greater than or equal to the active contract's `contracted_line_count`, the
    account advances `ACTIVE → SUSPENDED` with `suspended_reason` set to
    `LINE_COMPLIANCE_THRESHOLD`."
    PRD §3.4: "The doubling is integer arithmetic rather than a fractional ratio, so on a
    four-line contract two lines out of service suspends the venue while one does not."

    Design: Difficulty/transitive_cascade/failed_cycle_takes_line_out_then_suspends_account_contract_and_abandons_scheduled_visit
    """
    ground = _threshold_venue(api)

    cycle = fixtures.log_cleaning_cycle(
        api,
        ground["visit"]["id"],
        ground["lines"][0]["id"],
        ground["lot"]["id"],
        ground["technician"]["id"],
        **UNDER_DOSED_CYCLE,
    )

    assert cycle["effective_active_pct"] == 1.286
    assert cycle["required_contact_minutes"] == 30
    assert cycle["compliance_result"] == ComplianceResult.FAIL_CONCENTRATION
    assert cycle["record_status"] == RecordStatus.POSTED

    first_line = fixtures.read_line(api, ground["lines"][0]["id"])
    assert first_line["status"] == LineStatus.OUT_OF_SERVICE
    assert first_line["compliance_flag"] == ComplianceFlag.NON_COMPLIANT
    assert first_line["last_chemical_type"] == "CAUSTIC", (
        "a failed caustic circulation still counts as caustic for alternation"
    )
    assert first_line["last_cleaned_at"] is None
    second_line = fixtures.read_line(api, ground["lines"][1]["id"])
    assert second_line["status"] == LineStatus.IN_SERVICE

    account = fixtures.read_account(api, ground["account"]["id"])
    assert account["lines_out_of_service_count"] == 1
    assert account["status"] == AccountStatus.SUSPENDED, (
        "one line out of a two-line contract already meets the doubled threshold"
    )
    assert account["suspended_reason"] == SuspendedReason.LINE_COMPLIANCE_THRESHOLD


def test_the_suspension_drags_the_contract_and_clears_only_the_booked_visit(api):
    """PRD §3.4: "Hop three is the suspension's own cascade: every visit on that account
    still `SCHEDULED` advances to `ABANDONED` with `abandon_reason` `ACCOUNT_SUSPENDED`,
    processed by ascending `scheduled_date`, then ascending `scheduled_start_minute`,
    then ascending `created_at`, and every contract on that account still `ACTIVE`
    advances to `SUSPENDED`, processed in ascending `created_at` order."
    PRD §3.1: "Moving an `ACTIVE` contract to `SUSPENDED` requires it to be `ACTIVE` and
    sets the account's `billing_mode` to `DIRECT_BILL`."

    Design: Difficulty/transitive_cascade/failed_cycle_takes_line_out_then_suspends_account_contract_and_abandons_scheduled_visit
    """
    ground = _threshold_venue(api)
    assert ground["contract"]["funding_status"] == FundingStatus.BREWER_FUNDED
    assert fixtures.read_account(api, ground["account"]["id"])["billing_mode"] == (
        BillingMode.PROGRAM_BILL
    )

    fixtures.log_cleaning_cycle(
        api,
        ground["visit"]["id"],
        ground["lines"][0]["id"],
        ground["lot"]["id"],
        ground["technician"]["id"],
        **UNDER_DOSED_CYCLE,
    )

    contract = fixtures.read_contract(api, ground["contract"]["id"])
    assert contract["status"] == ContractStatus.SUSPENDED
    assert contract["funding_status"] == FundingStatus.BREWER_FUNDED, (
        "the suspension moves the contract's status, not its funding arrangement"
    )
    account = fixtures.read_account(api, ground["account"]["id"])
    assert account["billing_mode"] == BillingMode.DIRECT_BILL

    booked = fixtures.read_visit(api, ground["later_visit"]["id"])
    assert booked["work_status"] == WorkStatus.ABANDONED
    assert booked["abandon_reason"] == AbandonReason.ACCOUNT_SUSPENDED

    open_job = fixtures.read_visit(api, ground["visit"]["id"])
    assert open_job["work_status"] == WorkStatus.IN_PROGRESS, (
        "the job that carried the failing cycle is left on the floor"
    )
    assert open_job["abandon_reason"] == AbandonReason.NONE
    assert_program_ledger(
        fixtures.read_program(api, ground["program"]["id"]), 0, 100000, "ACTIVE"
    )


def _two_venues_on_one_programme(api):
    """Two unrelated venues funded by the same 8000-cent programme; only one has work."""
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    program = fixtures.create_brewer_program(
        api,
        brewer_name="Southside Brewing",
        funded_scope="CLEANING_AND_PARTS",
        co_pay_bps=2000,
        funding_cap_cents=8000,
    )
    worked = fixtures.setup_three_line_visit_with_work(
        api, venue_name="Harbor Taproom", brewer_program_id=program["id"]
    )
    idle = fixtures.onboard_venue(
        api,
        venue_name="Dockside Cantina",
        access_window=(600, 1200),
        cleaning_frequency_days=14,
        contracted_line_count=2,
        per_line_rate_cents=3000,
        visit_base_fee_cents=5000,
        brewer_program_id=program["id"],
        lines=(),
    )
    return program, worked, idle


def test_the_cap_runs_dry_inside_the_parts_bucket_and_exhausts_the_programme(api):
    """PRD §3.7: "That share is then clamped to whatever headroom is left after the
    buckets already filled, and never falls below zero. The clamp is applied per bucket
    against the **running** headroom, not once against the total, and the two are not the
    same: a cleaning bucket of 9186 and a parts bucket of 3195 at a `co_pay_bps` of 2000
    fund 7348 and 2556 under a roomy cap, but under a starting headroom of 8000 the
    cleaning bucket takes its full 7348 while the parts bucket is truncated to 652."
    PRD §3.7: "When `remaining_cents` reaches exactly zero the programme moves `ACTIVE →
    EXHAUSTED`, and that exhaustion cascades as described in §3.1 — every contract naming the
    programme whose status is `ACTIVE` or `SUSPENDED` recomputes its `funding_status` to
    `SELF_FUNDED`, processed in ascending `created_at` order, and each of those accounts
    recomputes its `billing_mode` to `DIRECT_BILL`."

    Design: Difficulty/transitive_cascade/settlement_exhausts_shared_brewer_program_and_reprices_two_unrelated_accounts
    """
    program, worked, _idle = _two_venues_on_one_programme(api)

    signed = fixtures.sign_visit(api, worked["visit"]["id"], worked["account"]["id"])

    assert signed["settled_charge_cents"] == 19881
    assert signed["cleaning_subtotal_cents"] == 9186
    assert signed["parts_charge_cents"] == 3195
    assert signed["brewer_funded_cents"] == 8000, (
        f"7348 of cleaning plus the 652 the cap had left is 8000, got {signed['brewer_funded_cents']}"
    )
    assert signed["account_due_cents"] == 11881
    assert signed["settlement_state"] == "SETTLED"
    assert_program_ledger(fixtures.read_program(api, program["id"]), 8000, 0, "EXHAUSTED")


def test_exhaustion_reprices_a_second_venue_that_never_had_a_visit(api):
    """PRD §3.7: "that exhaustion cascades as described in §3.1 — every contract naming
    the programme whose status is `ACTIVE` or `SUSPENDED` recomputes its `funding_status`
    to `SELF_FUNDED`, processed in ascending `created_at` order, and each of those
    accounts recomputes its `billing_mode` to `DIRECT_BILL`."
    PRD §3.7: "One venue's signature therefore changes the billing arrangement of every
    other venue on the same brewer's programme."

    Design: Difficulty/transitive_cascade/settlement_exhausts_shared_brewer_program_and_reprices_two_unrelated_accounts
    """
    program, worked, idle = _two_venues_on_one_programme(api)
    assert idle["contract"]["funding_status"] == FundingStatus.BREWER_FUNDED
    assert fixtures.read_account(api, idle["account"]["id"])["billing_mode"] == (
        BillingMode.PROGRAM_BILL
    )

    fixtures.sign_visit(api, worked["visit"]["id"], worked["account"]["id"])

    worked_contract = fixtures.read_contract(api, worked["contract"]["id"])
    assert worked_contract["funding_status"] == FundingStatus.SELF_FUNDED
    assert worked_contract["status"] == ContractStatus.ACTIVE, (
        "the funding recomputation does not disturb the contract's own lifecycle"
    )
    idle_contract = fixtures.read_contract(api, idle["contract"]["id"])
    assert idle_contract["funding_status"] == FundingStatus.SELF_FUNDED, (
        "the venue with no visit at all is repriced by someone else's signature"
    )
    assert idle_contract["status"] == ContractStatus.ACTIVE

    worked_account = fixtures.read_account(api, worked["account"]["id"])
    idle_account = fixtures.read_account(api, idle["account"]["id"])
    assert worked_account["billing_mode"] == BillingMode.DIRECT_BILL
    assert idle_account["billing_mode"] == BillingMode.DIRECT_BILL
    assert worked_account["status"] == AccountStatus.ACTIVE
    assert idle_account["status"] == AccountStatus.ACTIVE
