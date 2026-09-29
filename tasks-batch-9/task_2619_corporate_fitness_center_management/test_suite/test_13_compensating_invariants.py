"""Compensating adjustments on the conserved counters (PRD §2.9).

Two ledgers are exercised here, each with a forward operation and its
compensating undo:

* a member's ``incentive_points_balance`` against their surviving ``COUNTED``
  participation records, compensated when a mis-scan is voided; and
* a contract's ``ytd_billed_cents`` against its ``ISSUED``/``PAID`` invoices,
  compensated when the client disputes an invoice and re-established when the
  operator rebills and re-issues it.

Every mutation is followed by a re-check of the identity itself, not merely of
the expected integer, so an implementation that stores a drifting counter fails
even when a single arithmetic step happens to agree.
"""
from prd_bench_local_runner.testing import (
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS, api_client
from test_helpers import fixtures as scenarios
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_committed_minutes_invariant,
    assert_eligible_member_count_invariant,
    assert_incentive_points_invariant,
    assert_monthly_invoice,
    assert_ytd_billed_invariant,
)

ADMIN = TEST_USERS["operator_admin_headers"]

SESSION_ONE_START = "2026-08-05T12:00:00Z"
SESSION_ONE_END = "2026-08-05T12:55:00Z"
SESSION_TWO_START = "2026-08-06T12:00:00Z"
SESSION_TWO_END = "2026-08-06T12:55:00Z"

# One 55-minute LEAD assignment at 4700 cents/hour is paid 70 minutes, so its
# labor cost is 5483 cents; with 4517 cents of program supply the cost-plus base
# is exactly 10000 cents.
BILLING_DIRECT_SUPPLY_CENTS = 4517
BILLING_LABOR_CENTS = 5483
BILLING_MARKUP_CENTS = 1200
BILLING_NET_CENTS = 11200
BILLING_PERIOD_MONTH = "2026-08"
BILLING_CLOSE_INSTANT = "2026-08-31T00:00:00Z"


# ==========================================================================
# Private composite setups
# ==========================================================================
def _read_participation(record_id: str, headers=None) -> dict:
    return validate_success(
        api_client.get_participation_record(record_id, headers or ADMIN)
    )


def _member_records(member_id: str, status: str = None) -> list:
    params = {"member_id": member_id, "limit": 100}
    if status:
        params["status"] = status
    items, _meta = validate_paginated(
        api_client.list_participation_records(ADMIN, params=params)
    )
    return items


def _contract_invoices(contract_id: str, status: str = None) -> list:
    params = {"contract_id": contract_id, "limit": 100}
    if status:
        params["status"] = status
    items, _meta = validate_paginated(
        api_client.list_monthly_invoices(ADMIN, params=params)
    )
    return items


def _contract_members(contract_id: str) -> list:
    items, _meta = validate_paginated(
        api_client.list_members(ADMIN, params={"contract_id": contract_id, "limit": 100})
    )
    return items


def _staff_assignments(staff_member_id: str) -> list:
    items, _meta = validate_paginated(
        api_client.list_staff_assignments(
            ADMIN, params={"staff_member_id": staff_member_id, "limit": 100}
        )
    )
    return items


def _setup_two_counted_check_ins() -> dict:
    """One EMPLOYEE member checked in to two sessions on consecutive days.

    Each check-in awards the base 10 points: only one distinct prior day is on
    file when the second one lands, so no streak bonus is earned, and the weekly
    ceiling of 60 leaves ample headroom.  The first session is completed and the
    second is left in progress, so the two records sit on sessions in different
    statuses and both are voidable.
    """
    scenario = scenarios.setup_active_program()
    member = scenarios.setup_ready_member(scenario)

    session_one = scenarios.schedule_session(
        scenario,
        scheduled_start_utc=SESSION_ONE_START,
        scheduled_end_utc=SESSION_ONE_END,
        forecast_attendance=3,
        direct_supply_cost_cents=0,
    )
    session_two = scenarios.schedule_session(
        scenario,
        scheduled_start_utc=SESSION_TWO_START,
        scheduled_end_utc=SESSION_TWO_END,
        forecast_attendance=3,
        direct_supply_cost_cents=0,
    )
    scenarios.staff_session(scenario, session_one["id"])
    scenarios.staff_session(scenario, session_two["id"])

    scenarios.start_session(scenario, session_one["id"], clock_at=SESSION_ONE_START)
    first_record = scenarios.check_in(scenario, member["id"], session_one["id"])
    scenarios.complete_session(scenario, session_one["id"])

    scenarios.start_session(scenario, session_two["id"], clock_at=SESSION_TWO_START)
    second_record = scenarios.check_in(scenario, member["id"], session_two["id"])

    return {
        "scenario": scenario,
        "member_id": member["id"],
        "session_one_id": session_one["id"],
        "session_two_id": session_two["id"],
        "first_record": first_record,
        "second_record": second_record,
    }


def _setup_cost_plus_draft_invoice() -> dict:
    """An ACTIVE cost-plus contract with one completed August session and a
    DRAFT invoice for August whose net amount is exactly 11200 cents."""
    scenario = scenarios.setup_active_program()
    session = scenarios.schedule_session(
        scenario,
        scheduled_start_utc=SESSION_ONE_START,
        scheduled_end_utc=SESSION_ONE_END,
        forecast_attendance=3,
        direct_supply_cost_cents=BILLING_DIRECT_SUPPLY_CENTS,
    )
    assignment = scenarios.staff_session(scenario, session["id"])
    scenarios.start_session(scenario, session["id"], clock_at=SESSION_ONE_START)
    scenarios.complete_session(scenario, session["id"])

    scenarios.set_clock(BILLING_CLOSE_INSTANT)
    invoice = scenarios.draft_invoice(scenario, period_month=BILLING_PERIOD_MONTH)
    return {
        "scenario": scenario,
        "contract_id": scenario["contract_id"],
        "session_id": session["id"],
        "assignment_id": assignment["id"],
        "invoice_id": invoice["id"],
        "invoice": invoice,
    }


# ==========================================================================
# The incentive-point ledger
# ==========================================================================
def test_void_earlier_participation_record_restores_incentive_points_balance(api):
    """PRD §3.7: "Its effects are **compensating**: the member's
    `incentive_points_balance` is reduced by exactly the `points_awarded` stored
    on that record, restoring the invariant that a member's balance always
    equals the sum of `points_awarded` across their surviving `COUNTED`
    records; the session's `actual_attendance` and the offering's
    `counted_participation_total` are each reduced by 1; and both attainment
    percentages are recomputed."

    PRD §2.9: "A member's `incentive_points_balance` always equals the sum of
    `points_awarded` across that member's participation records still in
    `COUNTED` status."

    PRD §3.7: "The `points_awarded`, `points_capped`, and
    `streak_bonus_applied` values already written on the voided record are left
    exactly as they are — voiding does **not** retroactively re-open the weekly
    cap for records that were written earlier in the week."

    Design: Difficulty/compensating_invariant/void_participation_restores_incentive_points_balance
    """
    world = _setup_two_counted_check_ins()
    scenario = world["scenario"]
    member_id = world["member_id"]

    first = world["first_record"]
    second = world["second_record"]
    assert first["points_awarded"] == 10, (
        f"expected the base award of 10 points on the first check-in, got "
        f"{first['points_awarded']}"
    )
    assert second["points_awarded"] == 10, (
        f"expected the base award of 10 points on the second check-in, got "
        f"{second['points_awarded']}"
    )
    for record in (first, second):
        assert record["streak_bonus_applied"] is False, (
            "only one distinct prior day is on file, so no streak bonus is earned"
        )
        assert record["points_capped"] is False, (
            "the weekly ceiling of 60 points leaves ample headroom for a 10-point award"
        )

    member = scenarios.read_member(member_id)
    assert member["incentive_points_balance"] == 20, (
        f"expected a balance of 20 from two 10-point check-ins, got "
        f"{member['incentive_points_balance']}"
    )
    assert_incentive_points_invariant(member, _member_records(member_id))

    scenarios.void_participation(
        scenario, first["id"], void_reason="Badge scanned for the wrong member"
    )

    voided = _read_participation(first["id"])
    assert voided["status"] == "VOIDED", (
        f"expected the voided record to read VOIDED, got {voided['status']}"
    )
    assert voided["points_awarded"] == 10, (
        f"the award must stay written on the voided row, got {voided['points_awarded']}"
    )

    member = scenarios.read_member(member_id)
    assert member["incentive_points_balance"] == 10, (
        f"expected a balance of 10 — exactly the surviving COUNTED row — got "
        f"{member['incentive_points_balance']} after the void"
    )
    assert_incentive_points_invariant(member, _member_records(member_id))

    survivor = _read_participation(second["id"])
    assert survivor["status"] == "COUNTED", (
        f"the surviving record must stay COUNTED, got {survivor['status']}"
    )
    assert survivor["points_awarded"] == 10, (
        f"the surviving record's award must be untouched, got "
        f"{survivor['points_awarded']}"
    )

    session_one = scenarios.read_session(world["session_one_id"])
    session_two = scenarios.read_session(world["session_two_id"])
    assert session_one["actual_attendance"] == 0, (
        f"the voided check-in's session must drop to 0 attendance, got "
        f"{session_one['actual_attendance']}"
    )
    assert session_two["actual_attendance"] == 1, (
        f"the untouched session must keep its single attendance, got "
        f"{session_two['actual_attendance']}"
    )

    offering = scenarios.read_offering(scenario["offering_id"])
    assert offering["counted_participation_total"] == 1, (
        f"expected counted_participation_total of 1 after the void, got "
        f"{offering['counted_participation_total']}"
    )


def test_void_latest_participation_record_restores_incentive_points_balance(api):
    """PRD §3.7: "Its effects are **compensating**: the member's
    `incentive_points_balance` is reduced by exactly the `points_awarded` stored
    on that record, restoring the invariant that a member's balance always
    equals the sum of `points_awarded` across their surviving `COUNTED`
    records; the session's `actual_attendance` and the offering's
    `counted_participation_total` are each reduced by 1; and both attainment
    percentages are recomputed."

    PRD §3.7: "Voiding requires the record to be in `COUNTED` status and the
    session to be in `IN_PROGRESS`, `COMPLETED`, `CANCELLED_NO_COVER`,
    `CANCELLED_CLIENT`, or `CANCELLED_FACILITY`; the record moves to `VOIDED`,
    which is terminal."

    Design: Difficulty/compensating_invariant/void_participation_restores_incentive_points_balance
    """
    world = _setup_two_counted_check_ins()
    scenario = world["scenario"]
    member_id = world["member_id"]
    first = world["first_record"]
    second = world["second_record"]

    member = scenarios.read_member(member_id)
    assert member["incentive_points_balance"] == 20, (
        f"expected a balance of 20 before any void, got "
        f"{member['incentive_points_balance']}"
    )

    # The later record sits on the session that is still IN_PROGRESS, so the
    # compensation runs in the opposite arrival order from the first scenario.
    scenarios.void_participation(
        scenario, second["id"], void_reason="Member left before the class began"
    )

    member = scenarios.read_member(member_id)
    assert member["incentive_points_balance"] == 10, (
        f"expected a balance of 10 after voiding the later check-in, got "
        f"{member['incentive_points_balance']}"
    )
    assert_incentive_points_invariant(member, _member_records(member_id))

    voided = _read_participation(second["id"])
    assert voided["status"] == "VOIDED", (
        f"expected VOIDED on the record voided from an IN_PROGRESS session, got "
        f"{voided['status']}"
    )
    assert voided["points_awarded"] == 10, (
        f"the award must stay written on the voided row, got {voided['points_awarded']}"
    )

    survivor = _read_participation(first["id"])
    assert survivor["status"] == "COUNTED", (
        f"the earlier record must stay COUNTED, got {survivor['status']}"
    )

    session_one = scenarios.read_session(world["session_one_id"])
    session_two = scenarios.read_session(world["session_two_id"])
    assert session_one["actual_attendance"] == 1, (
        f"the completed session keeps its single attendance, got "
        f"{session_one['actual_attendance']}"
    )
    assert session_two["actual_attendance"] == 0, (
        f"the in-progress session must drop to 0 attendance, got "
        f"{session_two['actual_attendance']}"
    )

    offering = scenarios.read_offering(scenario["offering_id"])
    assert offering["counted_participation_total"] == 1, (
        f"expected counted_participation_total of 1 after the void, got "
        f"{offering['counted_participation_total']}"
    )


def test_voiding_both_participation_records_drains_incentive_points_balance_to_zero(api):
    """PRD §2.9: "A member's `incentive_points_balance` always equals the sum of
    `points_awarded` across that member's participation records still in
    `COUNTED` status."

    PRD §3.4: "`counted_participation_total` is the number of participation
    records in `COUNTED` status across all of the offering's sessions,
    incremented on every check-in and decremented on every void."

    PRD §2.9: "A staff member's `committed_minutes_current_period` always equals
    the sum of `paid_minutes` across that person's assignments in `ASSIGNED`,
    `CONFIRMED`, or `COMPLETED` status."

    PRD §2.9: "A contract's `eligible_member_count` always equals the number of
    that contract's members whose `eligibility_status` is `ELIGIBLE`."

    Design: Difficulty/compensating_invariant/void_participation_restores_incentive_points_balance
    """
    world = _setup_two_counted_check_ins()
    scenario = world["scenario"]
    member_id = world["member_id"]
    contract_id = scenario["contract_id"]
    instructor_id = scenario["instructor_id"]

    # Void the later record first, then the earlier one: the ledger must land on
    # the sum of the surviving COUNTED rows after each individual compensation.
    scenarios.void_participation(
        scenario, world["second_record"]["id"], void_reason="Wrong class selected"
    )
    member = scenarios.read_member(member_id)
    assert member["incentive_points_balance"] == 10, (
        f"expected a balance of 10 after the first of two voids, got "
        f"{member['incentive_points_balance']}"
    )
    assert_incentive_points_invariant(member, _member_records(member_id))

    scenarios.void_participation(
        scenario, world["first_record"]["id"], void_reason="Duplicate desk entry"
    )
    member = scenarios.read_member(member_id)
    assert member["incentive_points_balance"] == 0, (
        f"expected a balance of 0 once every awarding row is voided, got "
        f"{member['incentive_points_balance']}"
    )
    assert_incentive_points_invariant(member, _member_records(member_id))

    counted = _member_records(member_id, status="COUNTED")
    assert counted == [], (
        f"expected no surviving COUNTED record for the member, got {len(counted)}"
    )
    voided = _member_records(member_id, status="VOIDED")
    assert len(voided) == 2, (
        f"both voided rows must remain readable as history, got {len(voided)}"
    )
    assert sum(record["points_awarded"] for record in voided) == 20, (
        "the awards already written on the voided rows must be left exactly as they are"
    )

    for session_id in (world["session_one_id"], world["session_two_id"]):
        session = scenarios.read_session(session_id)
        assert session["actual_attendance"] == 0, (
            f"session {session_id} must report 0 attendance after its check-in was "
            f"voided, got {session['actual_attendance']}"
        )

    offering = scenarios.read_offering(scenario["offering_id"])
    assert offering["counted_participation_total"] == 0, (
        f"expected counted_participation_total of 0 after both voids, got "
        f"{offering['counted_participation_total']}"
    )

    # The participation compensation moves no other conserved counter.
    contract = scenarios.read_contract(contract_id)
    assert_eligible_member_count_invariant(contract, _contract_members(contract_id))
    assert contract["eligible_member_count"] == 1, (
        f"voiding participation must leave the verified population alone, got "
        f"eligible_member_count {contract['eligible_member_count']}"
    )
    instructor = scenarios.read_staff(instructor_id)
    assert_committed_minutes_invariant(instructor, _staff_assignments(instructor_id))


def test_second_void_of_a_participation_record_does_not_double_compensate_points(api):
    """PRD §3.7: "Voiding requires the record to be in `COUNTED` status and the
    session to be in `IN_PROGRESS`, `COMPLETED`, `CANCELLED_NO_COVER`,
    `CANCELLED_CLIENT`, or `CANCELLED_FACILITY`; the record moves to `VOIDED`,
    which is terminal."

    PRD §2.9: "A member's `incentive_points_balance` always equals the sum of
    `points_awarded` across that member's participation records still in
    `COUNTED` status."

    Design: Difficulty/compensating_invariant/void_participation_restores_incentive_points_balance
    """
    world = _setup_two_counted_check_ins()
    scenario = world["scenario"]
    member_id = world["member_id"]
    record_id = world["first_record"]["id"]

    scenarios.void_participation(scenario, record_id, void_reason="Mis-scan at the desk")
    member = scenarios.read_member(member_id)
    assert member["incentive_points_balance"] == 10, (
        f"expected a balance of 10 after the single void, got "
        f"{member['incentive_points_balance']}"
    )

    # VOIDED is terminal, so the record admits no second compensation.
    response = api_client.void_participation_record(
        record_id, {"void_reason": "Voided again by mistake"}, scenario["manager_headers"]
    )
    validate_error_is_one_of(
        response,
        [
            ApiErrorId.ERR_TERMINAL_STATE.value,
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        ],
    )

    member = scenarios.read_member(member_id)
    assert member["incentive_points_balance"] == 10, (
        f"a refused second void must not compensate again — expected 10, got "
        f"{member['incentive_points_balance']}"
    )
    assert_incentive_points_invariant(member, _member_records(member_id))

    still_voided = _read_participation(record_id)
    assert still_voided["status"] == "VOIDED", (
        f"the record must still read VOIDED after the refused retry, got "
        f"{still_voided['status']}"
    )
    assert still_voided["points_awarded"] == 10, (
        f"the award on the voided row must be unchanged, got "
        f"{still_voided['points_awarded']}"
    )

    session_one = scenarios.read_session(world["session_one_id"])
    assert session_one["actual_attendance"] == 0, (
        f"the refused retry must not decrement actual_attendance twice, got "
        f"{session_one['actual_attendance']}"
    )
    offering = scenarios.read_offering(scenario["offering_id"])
    assert offering["counted_participation_total"] == 1, (
        f"the refused retry must not decrement counted_participation_total twice, got "
        f"{offering['counted_participation_total']}"
    )


# ==========================================================================
# The fiscal ledger
# ==========================================================================
def test_invoice_issue_and_dispute_conserve_contract_ytd_billed(api):
    """PRD §3.9: "**Issuing** moves the invoice `DRAFT → ISSUED`, stamps
    `issued_at`, and adds `net_amount_cents` to the contract's
    `ytd_billed_cents`."

    PRD §3.9: "It moves the invoice `ISSUED → DISPUTED`, stamps `disputed_at`,
    and **compensates** the ledger by subtracting `net_amount_cents` back out of
    the contract's `ytd_billed_cents`."

    PRD §2.9: "A contract's `ytd_billed_cents` always equals the sum of
    `net_amount_cents` across that contract's invoices in `ISSUED` or `PAID`
    status."

    Design: Difficulty/compensating_invariant/invoice_dispute_reverses_contract_ytd_billed
    """
    world = _setup_cost_plus_draft_invoice()
    scenario = world["scenario"]
    contract_id = world["contract_id"]
    invoice_id = world["invoice_id"]

    draft = scenarios.read_invoice(invoice_id)
    assert_monthly_invoice(draft)
    assert draft["status"] == "DRAFT", (
        f"a freshly drafted invoice must be DRAFT, got {draft['status']}"
    )
    assert draft["labor_subtotal_cents"] == BILLING_LABOR_CENTS, (
        f"expected labor_subtotal_cents {BILLING_LABOR_CENTS} from one 70-minute LEAD "
        f"assignment at 4700 cents/hour, got {draft['labor_subtotal_cents']}"
    )
    assert draft["program_direct_cost_cents"] == BILLING_DIRECT_SUPPLY_CENTS, (
        f"expected program_direct_cost_cents {BILLING_DIRECT_SUPPLY_CENTS}, got "
        f"{draft['program_direct_cost_cents']}"
    )
    assert draft["admin_markup_cents"] == BILLING_MARKUP_CENTS, (
        f"a base of 10000 cents takes the 12 percent tier, so expected "
        f"{BILLING_MARKUP_CENTS}, got {draft['admin_markup_cents']}"
    )
    assert draft["volume_credit_cents"] == 0, (
        f"a gross of {BILLING_NET_CENTS} earns no volume credit, got "
        f"{draft['volume_credit_cents']}"
    )
    assert draft["downtime_credit_cents"] == 0, (
        f"no asset went out of service, so expected 0, got "
        f"{draft['downtime_credit_cents']}"
    )
    assert draft["coverage_penalty_cents"] == 0, (
        f"a cost-plus contract never accrues a coverage penalty, got "
        f"{draft['coverage_penalty_cents']}"
    )
    assert draft["gross_amount_cents"] == BILLING_NET_CENTS, (
        f"expected gross_amount_cents {BILLING_NET_CENTS}, got "
        f"{draft['gross_amount_cents']}"
    )
    assert draft["net_amount_cents"] == BILLING_NET_CENTS, (
        f"expected net_amount_cents {BILLING_NET_CENTS}, got "
        f"{draft['net_amount_cents']}"
    )
    assert draft["nte_capped"] is False, (
        "an annual ceiling of 5000000 cents leaves ample headroom, so nte_capped is false"
    )

    contract = scenarios.read_contract(contract_id)
    assert contract["ytd_billed_cents"] == 0, (
        f"a DRAFT was never billed, so ytd_billed_cents must stay 0, got "
        f"{contract['ytd_billed_cents']}"
    )
    assert_ytd_billed_invariant(contract, _contract_invoices(contract_id))

    issued = scenarios.issue_invoice(invoice_id)
    assert issued["status"] == "ISSUED", (
        f"expected ISSUED after the issue, got {issued['status']}"
    )
    assert issued["issued_at"] is not None, "issuing must stamp issued_at"
    assert issued["issued_at"][:19] == BILLING_CLOSE_INSTANT[:19], (
        f"issued_at must carry the logical clock instant {BILLING_CLOSE_INSTANT}, got "
        f"{issued['issued_at']}"
    )

    contract = scenarios.read_contract(contract_id)
    assert contract["ytd_billed_cents"] == BILLING_NET_CENTS, (
        f"issuing must add net_amount_cents to the ledger — expected "
        f"{BILLING_NET_CENTS}, got {contract['ytd_billed_cents']}"
    )
    assert_ytd_billed_invariant(contract, _contract_invoices(contract_id))

    disputed = scenarios.dispute_invoice(
        scenario, invoice_id, reason="August staffing hours are under review"
    )
    assert disputed["status"] == "DISPUTED", (
        f"expected DISPUTED after the dispute, got {disputed['status']}"
    )
    assert disputed["disputed_at"] is not None, "disputing must stamp disputed_at"
    assert disputed["disputed_at"][:19] == BILLING_CLOSE_INSTANT[:19], (
        f"disputed_at must carry the logical clock instant {BILLING_CLOSE_INSTANT}, got "
        f"{disputed['disputed_at']}"
    )

    contract = scenarios.read_contract(contract_id)
    assert contract["ytd_billed_cents"] == 0, (
        f"the compensation must restore the exact pre-issue value of 0, got "
        f"{contract['ytd_billed_cents']}"
    )
    assert_ytd_billed_invariant(contract, _contract_invoices(contract_id))

    # The disputed invoice is history, not a deletion: it still carries its money.
    history = scenarios.read_invoice(invoice_id)
    assert history["status"] == "DISPUTED", (
        f"the disputed invoice must remain readable as DISPUTED, got "
        f"{history['status']}"
    )
    assert history["net_amount_cents"] == BILLING_NET_CENTS, (
        f"the disputed invoice keeps its net amount of {BILLING_NET_CENTS}, got "
        f"{history['net_amount_cents']}"
    )
    listed = _contract_invoices(contract_id, status="DISPUTED")
    assert [item["id"] for item in listed] == [invoice_id], (
        "the disputed invoice must still be discoverable in the contract's invoice list"
    )


def test_invoice_rebill_and_reissue_return_ytd_billed_to_the_same_amount(api):
    """PRD §3.9: "**Rebilling** is the operator's answer: it moves the invoice
    `DISPUTED → DRAFT`, increases `rebill_count` by 1, clears `issued_at` back to
    null, and recomputes every money component from current period data under the
    **pinned** `fee_structure_snapshot`."

    PRD §3.9: "**Issuing** moves the invoice `DRAFT → ISSUED`, stamps
    `issued_at`, and adds `net_amount_cents` to the contract's
    `ytd_billed_cents`."

    PRD §2.9: "A contract's `ytd_billed_cents` always equals the sum of
    `net_amount_cents` across that contract's invoices in `ISSUED` or `PAID`
    status."

    Design: Difficulty/compensating_invariant/invoice_dispute_reverses_contract_ytd_billed
    """
    world = _setup_cost_plus_draft_invoice()
    scenario = world["scenario"]
    contract_id = world["contract_id"]
    invoice_id = world["invoice_id"]

    scenarios.issue_invoice(invoice_id)
    scenarios.dispute_invoice(
        scenario, invoice_id, reason="August staffing hours are under review"
    )

    rebilled = validate_success(api_client.rebill_invoice(invoice_id, ADMIN))
    assert rebilled["status"] == "DRAFT", (
        f"rebilling returns the invoice to DRAFT, got {rebilled['status']}"
    )
    assert rebilled["rebill_count"] == 1, (
        f"expected rebill_count 1 after one lap, got {rebilled['rebill_count']}"
    )
    assert rebilled["issued_at"] is None, (
        f"rebilling clears issued_at back to null, got {rebilled['issued_at']}"
    )
    assert rebilled["net_amount_cents"] == BILLING_NET_CENTS, (
        f"the period data is unchanged, so the recomputation reproduces "
        f"{BILLING_NET_CENTS}, got {rebilled['net_amount_cents']}"
    )
    assert rebilled["fee_structure_snapshot"] == "COST_PLUS", (
        f"the pinned fee structure must survive the rebill, got "
        f"{rebilled['fee_structure_snapshot']}"
    )

    contract = scenarios.read_contract(contract_id)
    assert contract["ytd_billed_cents"] == 0, (
        f"a DRAFT is not billed, so the ledger stays at 0 after the rebill, got "
        f"{contract['ytd_billed_cents']}"
    )
    assert_ytd_billed_invariant(contract, _contract_invoices(contract_id))

    reissued = scenarios.issue_invoice(invoice_id)
    assert reissued["status"] == "ISSUED", (
        f"expected ISSUED after the second issue, got {reissued['status']}"
    )
    assert reissued["rebill_count"] == 1, (
        f"re-issuing must not disturb rebill_count, got {reissued['rebill_count']}"
    )

    contract = scenarios.read_contract(contract_id)
    assert contract["ytd_billed_cents"] == BILLING_NET_CENTS, (
        f"the same amount is billed again, not doubled — expected "
        f"{BILLING_NET_CENTS}, got {contract['ytd_billed_cents']}"
    )
    assert_ytd_billed_invariant(contract, _contract_invoices(contract_id))


def test_invoice_payment_leaves_ytd_billed_at_the_issued_amount(api):
    """PRD §3.9: "**Paying** is again the client's move, optionally recording a
    `payment_reference` for their own reconciliation; it moves the invoice
    `ISSUED → PAID`, stamps `paid_at`, and leaves `ytd_billed_cents` untouched,
    because issuing already counted it."

    PRD §2.9: "A contract's `ytd_billed_cents` always equals the sum of
    `net_amount_cents` across that contract's invoices in `ISSUED` or `PAID`
    status."

    Design: Difficulty/compensating_invariant/invoice_dispute_reverses_contract_ytd_billed
    """
    world = _setup_cost_plus_draft_invoice()
    scenario = world["scenario"]
    contract_id = world["contract_id"]
    invoice_id = world["invoice_id"]

    scenarios.issue_invoice(invoice_id)
    scenarios.dispute_invoice(
        scenario, invoice_id, reason="August staffing hours are under review"
    )
    validate_success(api_client.rebill_invoice(invoice_id, ADMIN))
    scenarios.issue_invoice(invoice_id)

    contract = scenarios.read_contract(contract_id)
    assert contract["ytd_billed_cents"] == BILLING_NET_CENTS, (
        f"expected {BILLING_NET_CENTS} billed before the payment, got "
        f"{contract['ytd_billed_cents']}"
    )

    paid = validate_success(
        api_client.pay_invoice(
            invoice_id, {"payment_reference": "ACH-88213"}, scenario["sponsor_headers"]
        )
    )
    assert paid["status"] == "PAID", (
        f"expected PAID after the payment, got {paid['status']}"
    )
    assert paid["paid_at"] is not None, "paying must stamp paid_at"
    assert paid["net_amount_cents"] == BILLING_NET_CENTS, (
        f"the payment must not restate the amount, got {paid['net_amount_cents']}"
    )

    contract = scenarios.read_contract(contract_id)
    assert contract["ytd_billed_cents"] == BILLING_NET_CENTS, (
        f"payment adds nothing on top of the issue — expected {BILLING_NET_CENTS}, "
        f"got {contract['ytd_billed_cents']}"
    )
    assert_ytd_billed_invariant(contract, _contract_invoices(contract_id))

    paid_invoices = _contract_invoices(contract_id, status="PAID")
    assert sum(item["net_amount_cents"] for item in paid_invoices) == BILLING_NET_CENTS, (
        f"the PAID invoices must sum to the contract's ledger of "
        f"{BILLING_NET_CENTS} cents"
    )


def test_repeated_dispute_and_rebill_laps_conserve_ytd_billed(api):
    """PRD §3.9: "The `DRAFT → ISSUED → DISPUTED → DRAFT` cycle may repeat
    indefinitely, and the fiscal invariant of §2.9 — that `ytd_billed_cents`
    equals the sum of `net_amount_cents` over the contract's invoices in `ISSUED`
    and `PAID` status — holds after every lap, which is exactly what the paired
    increment on issue and decrement on dispute guarantee."

    PRD §3.9: "It moves the invoice `ISSUED → DISPUTED`, stamps `disputed_at`,
    and **compensates** the ledger by subtracting `net_amount_cents` back out of
    the contract's `ytd_billed_cents`."

    Design: Difficulty/compensating_invariant/invoice_dispute_reverses_contract_ytd_billed
    """
    world = _setup_cost_plus_draft_invoice()
    scenario = world["scenario"]
    contract_id = world["contract_id"]
    invoice_id = world["invoice_id"]

    for lap in range(1, 3):
        issued = scenarios.issue_invoice(invoice_id)
        assert issued["status"] == "ISSUED", (
            f"lap {lap}: expected ISSUED, got {issued['status']}"
        )
        contract = scenarios.read_contract(contract_id)
        assert contract["ytd_billed_cents"] == BILLING_NET_CENTS, (
            f"lap {lap}: expected {BILLING_NET_CENTS} billed after the issue, got "
            f"{contract['ytd_billed_cents']}"
        )
        assert_ytd_billed_invariant(contract, _contract_invoices(contract_id))

        disputed = scenarios.dispute_invoice(
            scenario, invoice_id, reason=f"Round {lap} of the staffing review"
        )
        assert disputed["status"] == "DISPUTED", (
            f"lap {lap}: expected DISPUTED, got {disputed['status']}"
        )
        contract = scenarios.read_contract(contract_id)
        assert contract["ytd_billed_cents"] == 0, (
            f"lap {lap}: the dispute must return the ledger to 0, got "
            f"{contract['ytd_billed_cents']}"
        )
        assert_ytd_billed_invariant(contract, _contract_invoices(contract_id))

        rebilled = validate_success(api_client.rebill_invoice(invoice_id, ADMIN))
        assert rebilled["rebill_count"] == lap, (
            f"lap {lap}: expected rebill_count {lap}, got {rebilled['rebill_count']}"
        )
        assert rebilled["net_amount_cents"] == BILLING_NET_CENTS, (
            f"lap {lap}: the recomputation reproduces {BILLING_NET_CENTS}, got "
            f"{rebilled['net_amount_cents']}"
        )
        contract = scenarios.read_contract(contract_id)
        assert contract["ytd_billed_cents"] == 0, (
            f"lap {lap}: a DRAFT is not billed, so the ledger stays 0, got "
            f"{contract['ytd_billed_cents']}"
        )
        assert_ytd_billed_invariant(contract, _contract_invoices(contract_id))

    # A third issue after two full laps still bills the amount exactly once.
    scenarios.issue_invoice(invoice_id)
    contract = scenarios.read_contract(contract_id)
    assert contract["ytd_billed_cents"] == BILLING_NET_CENTS, (
        f"after two dispute-and-rebill laps the ledger must read "
        f"{BILLING_NET_CENTS}, not a multiple of it, got "
        f"{contract['ytd_billed_cents']}"
    )
    assert_ytd_billed_invariant(contract, _contract_invoices(contract_id))
    final = scenarios.read_invoice(invoice_id)
    assert final["rebill_count"] == 2, (
        f"rebill_count must accumulate across laps — expected 2, got "
        f"{final['rebill_count']}"
    )
