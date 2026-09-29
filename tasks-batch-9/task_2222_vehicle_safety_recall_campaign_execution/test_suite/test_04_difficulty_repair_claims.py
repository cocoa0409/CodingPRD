"""
Repair claim submission: the provisional arithmetic's rounding order, and three
precedence questions the ordered validation chain of PRD §2.7 settles.
"""

from test_helpers import (
    AllocationStatus,
    ApiErrorId,
    ClaimStatus,
    DealerStatus,
    OutreachChannel,
    OutreachOutcome,
    VehicleRemedyStatus,
    assert_repair_claim,
    factories as f,
    fixtures as fx,
    get_success_data,
    make_dealer_service_manager_headers,
    read_list,
    validate_error,
    validate_success,
)
from test_helpers.test_users import CLAIMS_AUDITOR, OPERATIONS_MANAGER, SAFETY_ENGINEER_1

HARBOR_AUTO_GROUP = {
    "dealer_code": "D-NE-02",
    "name": "Harbor Auto Group",
    "region_code": "NE",
    "labor_rate_per_hour": 152.30,
    "monthly_repair_capacity": 40,
}


def _row_ready_for_a_claim(api, requested_qty=1, dealer=None):
    """A released campaign with one NE owner and a dealer holding kits."""
    state = fx.campaign_with_allocation(api, requested_qty=requested_qty, dealer=dealer)
    row = fx.find_affected_vehicle(api, state["campaign_id"], state["vehicle_id"])
    state["affected_vehicle"] = row
    state["affected_vehicle_id"] = row["id"]
    return state


def test_provisional_amount_rounds_each_component_before_summing(api):
    """
    Both components land on a half cent — 1.55 hours at 152.30 is 236.065 and
    three kits at 21.90 plus handling is 75.555 — so rounding each component
    first yields 32363 cents, not the 32362 that summing raw products gives.

    PRD §2.11: "Every derived money amount is computed component by component,
    with **each component rounded to two decimal places, half up, before the
    components are summed**; the sum is then itself rounded to two decimal places,
    half up, and only then converted to integer cents by multiplying by 100 and
    rounding to the nearest whole cent."

    PRD §3.7: "The parts component is the dealer's full reported
    `parts_used_qty` multiplied by the remedy part's `unit_cost`, then increased
    by a fifteen percent parts-handling markup — that is, multiplied by one plus
    fifteen hundredths — and rounded to two decimal places."

    Design: Difficulty/combinatorial_formula/claim_provisional_component_rounding_order_mode_b
    """
    state = _row_ready_for_a_claim(api, requested_qty=3, dealer=HARBOR_AUTO_GROUP)

    response = api.create_repair_claim(
        f.repair_claim_payload(
            state["affected_vehicle_id"],
            state["dealer_id"],
            state["labor_operation_id"],
            repair_date="2026-08-03",
            claimed_labor_hours=1.55,
            parts_used_qty=3,
        ),
        make_dealer_service_manager_headers(state["dealer_id"]),
    )
    claim = validate_success(response, 201)
    assert_repair_claim(claim)

    assert claim["provisional_amount_cents"] == 32363
    assert claim["provisional_amount_cents"] != 32362, (
        "236.065 + 75.555 + 12.00 rounded once is the wrong order"
    )


def test_submitted_claim_reserves_a_unit_without_consuming_it(api):
    """
    Submission leaves the claim SUBMITTED with no audited amount, records the
    dealer's holding as its `parts_allocation_id`, and counts against the labor
    operation without burning a kit.

    PRD §3.7: "Submission also sets `is_repeat_repair` to true when the
    affected-vehicle row already carried at least one `APPROVED` claim at the
    moment of submission and false otherwise, increments the labor operation's
    `claim_count`, and leaves the claim in status `SUBMITTED` with
    `final_amount_cents`, `audit_note` and `reversal_reason` unset."

    PRD §3.7: "the server ranks candidates by `created_at` ascending so the
    oldest holding drains first, breaking a tie on identical `created_at` by
    preferring the larger `allocated_qty`, and records the first candidate as the
    claim's `parts_allocation_id`."

    Design: Difficulty/combinatorial_formula/claim_provisional_component_rounding_order_mode_b
    """
    state = _row_ready_for_a_claim(api, requested_qty=3, dealer=HARBOR_AUTO_GROUP)

    claim = validate_success(
        api.create_repair_claim(
            f.repair_claim_payload(
                state["affected_vehicle_id"],
                state["dealer_id"],
                state["labor_operation_id"],
                repair_date="2026-08-03",
                claimed_labor_hours=1.55,
                parts_used_qty=3,
            ),
            make_dealer_service_manager_headers(state["dealer_id"]),
        ),
        201,
    )

    assert claim["status"] == ClaimStatus.SUBMITTED
    assert claim["final_amount_cents"] is None
    assert claim["parts_allocation_id"] == state["allocation_id"]

    ops, _ = read_list(
        api.list_labor_operations(state["campaign_id"], SAFETY_ENGINEER_1), expected_total=1
    )
    assert ops[0]["claim_count"] == 1

    allocation = get_success_data(
        api.get_parts_allocation(state["allocation_id"], OPERATIONS_MANAGER)
    )
    assert allocation["consumed_qty"] == 0


def _unreachable_row(api):
    """A row driven to UNREACHABLE by a single BAD_ADDRESS outreach attempt."""
    state = _row_ready_for_a_claim(api)
    fx.log_outreach(
        api,
        state["affected_vehicle_id"],
        channel=OutreachChannel.MAIL,
        outcome=OutreachOutcome.BAD_ADDRESS,
        note="Notice returned undeliverable",
    )
    return state


def test_unrepairable_row_outranks_the_labor_hours_cap(api):
    """
    A claim naming an UNREACHABLE row and also billing 2.50 hours against a 1.10
    flat-rate operation violates two rules; the state gate answers first.

    PRD §3.7: "the row must be repairable for a claim, which means its
    `remedy_status` is `UNREPAIRED`, `SCHEDULED` or `REMEDIED` — a row in
    `UNREACHABLE` or `REMOVED_FROM_POPULATION` is rejected with
    `ERR_VEHICLE_NOT_REPAIRABLE`."

    PRD §2.7: "Validation across the whole API is a single ordered chain, and the
    ordering is normative because many requests violate more than one rule at
    once."

    Design: Difficulty/priority_pair_validation_conflict/claim_state_beats_fiscal_returns_vehicle_not_repairable
    """
    state = _unreachable_row(api)

    response = api.create_repair_claim(
        f.repair_claim_payload(
            state["affected_vehicle_id"],
            state["dealer_id"],
            state["labor_operation_id"],
            repair_date="2026-08-03",
            claimed_labor_hours=2.50,
            parts_used_qty=1,
        ),
        make_dealer_service_manager_headers(state["dealer_id"]),
    )
    validate_error(response, ApiErrorId.VEHICLE_NOT_REPAIRABLE, 409)


def test_claim_refused_on_the_state_gate_writes_nothing(api):
    """
    Nothing survives the refusal: no claim row, no labor-operation count, no
    consumed unit, and the outreach outcome still stands.

    PRD §2.7: "**State gates**, in this precedence: campaign state
    (`ERR_INVALID_CAMPAIGN_STATE`), wave state (`ERR_WAVE_INVALID_STATE`), claim
    state (`ERR_CLAIM_INVALID_STATE`), reimbursement state
    (`ERR_REIMBURSEMENT_INVALID_STATE`), allocation state
    (`ERR_ALLOCATION_INVALID_STATE`), affected-vehicle repairability
    (`ERR_VEHICLE_NOT_REPAIRABLE`)."

    PRD §3.8: "A row in `UNREPAIRED` becomes `UNREACHABLE` either immediately,
    when the new attempt's `outcome` is `BAD_ADDRESS`, or on accumulation, when
    the row's attempt count reaches three and every one of those attempts ended
    in `NO_RESPONSE`, `BAD_ADDRESS` or `OWNER_REFUSED`".

    Design: Difficulty/priority_pair_validation_conflict/claim_state_beats_fiscal_returns_vehicle_not_repairable
    """
    state = _unreachable_row(api)
    validate_error(
        api.create_repair_claim(
            f.repair_claim_payload(
                state["affected_vehicle_id"],
                state["dealer_id"],
                state["labor_operation_id"],
                repair_date="2026-08-03",
                claimed_labor_hours=2.50,
                parts_used_qty=1,
            ),
            make_dealer_service_manager_headers(state["dealer_id"]),
        ),
        ApiErrorId.VEHICLE_NOT_REPAIRABLE,
        409,
    )

    read_list(
        api.list_repair_claims(
            CLAIMS_AUDITOR, {"affected_vehicle_id": state["affected_vehicle_id"]}
        ),
        expected_total=0,
    )

    row = get_success_data(
        api.get_affected_vehicle(state["affected_vehicle_id"], OPERATIONS_MANAGER)
    )
    assert row["remedy_status"] == VehicleRemedyStatus.UNREACHABLE

    ops, _ = read_list(
        api.list_labor_operations(state["campaign_id"], SAFETY_ENGINEER_1), expected_total=1
    )
    assert ops[0]["claim_count"] == 0

    allocation = get_success_data(
        api.get_parts_allocation(state["allocation_id"], OPERATIONS_MANAGER)
    )
    assert allocation["consumed_qty"] == 0


def test_labor_operation_effectivity_outranks_the_repair_date_rule(api):
    """
    A 2026-07-20 repair date is both outside the labor operation's 2026-08-01
    window and before the 2026-08-03 remedy release; the referential band answers
    before the temporal band.

    PRD §3.7: "The referenced labor operation's closed effective window must
    contain the `repair_date`, or the claim is rejected with
    `ERR_LABOR_OP_NOT_EFFECTIVE`."

    PRD §2.7: "**Referential consistency**, in this precedence: labor-operation
    effectivity (`ERR_LABOR_OP_NOT_EFFECTIVE`), vehicle-in-population
    (`ERR_VEHICLE_NOT_IN_POPULATION`), cross-campaign mixing
    (`ERR_PART_CAMPAIGN_MISMATCH`), dealer participation
    (`ERR_DEALER_SUSPENDED`)."

    Design: Difficulty/priority_pair_validation_conflict/claim_referential_beats_temporal_returns_labor_op_not_effective
    """
    state = _row_ready_for_a_claim(api)

    response = api.create_repair_claim(
        f.repair_claim_payload(
            state["affected_vehicle_id"],
            state["dealer_id"],
            state["labor_operation_id"],
            repair_date="2026-07-20",
            claimed_labor_hours=1.00,
            parts_used_qty=1,
        ),
        make_dealer_service_manager_headers(state["dealer_id"]),
    )
    validate_error(response, ApiErrorId.LABOR_OP_NOT_EFFECTIVE, 422)


def test_claim_refused_on_effectivity_leaves_the_row_unrepaired(api):
    """
    The refusal persists no claim, does not touch the labor operation's count,
    and leaves the owner's row awaiting repair.

    PRD §2.7: "**Temporal rules**, in this precedence: date-range sanity
    (`ERR_INVALID_DATE_RANGE`), population-rule overlap
    (`ERR_POPULATION_RULE_OVERLAP`), labor-operation window conflict
    (`ERR_LABOR_OP_WINDOW_CONFLICT`), wave mailing separation
    (`ERR_WAVE_MAILING_TOO_CLOSE`), mail-date reached
    (`ERR_WAVE_MAIL_DATE_NOT_REACHED`), repair date versus remedy release
    (`ERR_REPAIR_DATE_BEFORE_REMEDY`), reimbursement window
    (`ERR_REIMBURSEMENT_WINDOW_CLOSED`)."

    PRD §3.5: "Each labor operation reports `claim_count`, the number of repair
    claims currently referencing it in status `SUBMITTED` or `APPROVED`."

    Design: Difficulty/priority_pair_validation_conflict/claim_referential_beats_temporal_returns_labor_op_not_effective
    """
    state = _row_ready_for_a_claim(api)
    validate_error(
        api.create_repair_claim(
            f.repair_claim_payload(
                state["affected_vehicle_id"],
                state["dealer_id"],
                state["labor_operation_id"],
                repair_date="2026-07-20",
                claimed_labor_hours=1.00,
                parts_used_qty=1,
            ),
            make_dealer_service_manager_headers(state["dealer_id"]),
        ),
        ApiErrorId.LABOR_OP_NOT_EFFECTIVE,
        422,
    )

    read_list(
        api.list_repair_claims(CLAIMS_AUDITOR, {"campaign_id": state["campaign_id"]}),
        expected_total=0,
    )

    ops, _ = read_list(
        api.list_labor_operations(state["campaign_id"], SAFETY_ENGINEER_1), expected_total=1
    )
    assert ops[0]["claim_count"] == 0

    row = get_success_data(
        api.get_affected_vehicle(state["affected_vehicle_id"], OPERATIONS_MANAGER)
    )
    assert row["remedy_status"] == VehicleRemedyStatus.UNREPAIRED


def _suspended_dealer_holding_a_kit(api):
    """A dealer suspended after its allocation landed."""
    state = _row_ready_for_a_claim(api)
    state["dealer"] = fx.suspend_dealer(
        api,
        state["dealer_id"],
        suspension_reason="Warranty claim irregularities under review",
    )
    return state


def test_suspended_dealer_cannot_claim_against_the_kits_it_still_holds(api):
    """
    Suspension does not take the dealer's allocation away, but it does block any
    new claim naming that dealer.

    PRD §3.5: "A dealer's `status` starts `ACTIVE` and can be moved to
    `SUSPENDED` with a `suspension_reason`; a suspended dealer keeps its existing
    allocations, but new allocations, new appointments and new repair claims
    naming it are all refused with `ERR_DEALER_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/repair_claim_blocked_by_suspended_dealer_state
    """
    state = _suspended_dealer_holding_a_kit(api)
    assert state["dealer"]["status"] == DealerStatus.SUSPENDED

    response = api.create_repair_claim(
        f.repair_claim_payload(
            state["affected_vehicle_id"],
            state["dealer_id"],
            state["labor_operation_id"],
            repair_date="2026-08-03",
            claimed_labor_hours=1.25,
            parts_used_qty=1,
        ),
        make_dealer_service_manager_headers(state["dealer_id"]),
    )
    validate_error(response, ApiErrorId.DEALER_SUSPENDED, 409)


def test_suspension_refusal_leaves_the_allocation_and_the_row_intact(api):
    """
    No claim is recorded for the suspended dealer, its holding stays ALLOCATED
    with nothing consumed, and the owner's row is still awaiting repair.

    PRD §3.5: "a suspended dealer keeps its existing allocations, but new
    allocations, new appointments and new repair claims naming it are all refused
    with `ERR_DEALER_SUSPENDED`."

    PRD §2.9: "Every mutation touching a remedy part, an allocation or a repair
    claim must leave the equality intact."

    Design: Difficulty/cross_entity_state_dependency/repair_claim_blocked_by_suspended_dealer_state
    """
    state = _suspended_dealer_holding_a_kit(api)
    validate_error(
        api.create_repair_claim(
            f.repair_claim_payload(
                state["affected_vehicle_id"],
                state["dealer_id"],
                state["labor_operation_id"],
                repair_date="2026-08-03",
                claimed_labor_hours=1.25,
                parts_used_qty=1,
            ),
            make_dealer_service_manager_headers(state["dealer_id"]),
        ),
        ApiErrorId.DEALER_SUSPENDED,
        409,
    )

    read_list(
        api.list_repair_claims(CLAIMS_AUDITOR, {"dealer_id": state["dealer_id"]}),
        expected_total=0,
    )

    allocation = get_success_data(
        api.get_parts_allocation(state["allocation_id"], OPERATIONS_MANAGER)
    )
    assert allocation["status"] == AllocationStatus.ALLOCATED
    assert allocation["consumed_qty"] == 0

    row = get_success_data(
        api.get_affected_vehicle(state["affected_vehicle_id"], OPERATIONS_MANAGER)
    )
    assert row["remedy_status"] == VehicleRemedyStatus.UNREPAIRED
