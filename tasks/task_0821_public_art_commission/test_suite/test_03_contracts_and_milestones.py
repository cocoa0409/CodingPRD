"""Fabrication contracts, milestone scheduling and payment, and the completion cascade."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, ApiErrorId,
    make_contract_payload, make_milestone_schedule_payload,
    make_artist_headers, assert_payment_invariant,
    setup_awarded_commission, setup_contracted_commission,
    setup_active_contract_with_artwork, schedule_milestones,
)

ADMIN = TEST_USERS["program_admin_headers"]


def test_contract_amount_exceeds_allocation_rejected(api):
    """PRD §3.2: "the `contract_amount_cents` (greater than zero) must not exceed
    the commission's `allocation_cents` — a larger amount is rejected with
    `ERR_CONTRACT_EXCEEDS_ALLOCATION` (HTTP 422)."

    Design: Corner/validations/contract_amount_exceeds_allocation_rejected
    """
    ctx = setup_awarded_commission(api, allocation_cents=500000, proposed_budget_cents=450000)
    resp = api.create_contract(
        ctx["commission"]["id"], make_contract_payload(ctx["submission"]["id"], 600000), ADMIN)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_EXCEEDS_ALLOCATION.value, 422)


def test_milestone_pct_sum_not_one_rejected(api):
    """PRD §3.5: "The supplied `pct` values across the contract must sum to exactly
    1.0, or the schedule is rejected with `ERR_MILESTONE_PCT_SUM` (HTTP 422)."

    Design: Corner/validations/milestone_pct_sum_not_one_rejected
    """
    ctx = setup_contracted_commission(api, allocation_cents=1000000, contract_amount_cents=1000000)
    milestones = [{"sequence": 1, "title": "A", "pct": 0.5},
                  {"sequence": 2, "title": "B", "pct": 0.4}]
    resp = api.schedule_milestones(
        ctx["contract"]["id"],
        make_milestone_schedule_payload(milestones, ctx["contract"]["version"]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_MILESTONE_PCT_SUM.value, 422)


def test_milestone_amounts_use_pinned_rounding(api):
    """PRD §3.5: "for every milestone except the one with the highest sequence, set
    its `amount_cents` to `contract_amount_cents` multiplied by that milestone's
    `pct`, rounded half-up to whole cents, and accumulate a running total; the
    highest-sequence milestone then takes exactly `contract_amount_cents` minus
    that running total, so the milestone amounts sum precisely to the contract
    amount and the final line absorbs the rounding remainder."

    Design: Difficulty/combinatorial_formula/milestone_rounding_order_remainder
    """
    ctx = setup_contracted_commission(api, allocation_cents=1500000, contract_amount_cents=1000001)
    milestones = [{"sequence": 1, "title": "Design", "pct": 0.3333},
                  {"sequence": 2, "title": "Fabrication", "pct": 0.3333},
                  {"sequence": 3, "title": "Delivery", "pct": 0.3334}]
    data = validate_success(api.schedule_milestones(
        ctx["contract"]["id"],
        make_milestone_schedule_payload(milestones, ctx["contract"]["version"]), ADMIN), 201)
    by_seq = {m["sequence"]: m for m in data}
    # contract_amount_cents = 1000001; pct 0.3333 -> 1000001 * 0.3333 = 333300.3333 -> 333300
    assert by_seq[1]["amount_cents"] == 333300
    assert by_seq[2]["amount_cents"] == 333300
    # highest sequence absorbs the remainder: 1000001 - 333300 - 333300 = 333401
    # (its natural 1000001 * 0.3334 = 333400.3334 -> 333400, so it absorbs +1)
    assert by_seq[3]["amount_cents"] == 333401


def test_final_milestone_absorbs_rounding_remainder(api):
    """PRD §3.5: "for every milestone except the one with the highest sequence, set
    its `amount_cents` to `contract_amount_cents` multiplied by that milestone's
    `pct`, rounded half-up to whole cents, and accumulate a running total; the
    highest-sequence milestone then takes exactly `contract_amount_cents` minus
    that running total, so the milestone amounts sum precisely to the contract
    amount and the final line absorbs the rounding remainder."

    Design: Difficulty/combinatorial_formula/milestone_rounding_order_remainder
    """
    ctx = setup_contracted_commission(api, allocation_cents=1500000, contract_amount_cents=1000001)
    milestones = [{"sequence": 1, "title": "Design", "pct": 0.3333},
                  {"sequence": 2, "title": "Fabrication", "pct": 0.3333},
                  {"sequence": 3, "title": "Delivery", "pct": 0.3334}]
    data = validate_success(api.schedule_milestones(
        ctx["contract"]["id"],
        make_milestone_schedule_payload(milestones, ctx["contract"]["version"]), ADMIN), 201)
    by_seq = {m["sequence"]: m for m in data}
    assert sum(m["amount_cents"] for m in data) == 1000001
    # 1000001 - 333300 - 333300 = 333401 (final line absorbs the rounding remainder)
    assert by_seq[3]["amount_cents"] == 333401


def test_list_contract_milestones_reverse_lookup(api):
    """PRD §3.5: "Each milestone starts in status `PENDING`. Scheduling increments
    the contract's `version` by one. A contract's milestones can be listed."

    Design: Corner/endpoints/list_contract_milestones_reverse_lookup
    """
    ctx = setup_contracted_commission(api, allocation_cents=1000000, contract_amount_cents=1000000)
    schedule_milestones(api, ctx["contract"]["id"],
                        [{"sequence": 1, "title": "A", "pct": 0.5},
                         {"sequence": 2, "title": "B", "pct": 0.5}])
    data = validate_success(api.list_milestones(ctx["contract"]["id"], ADMIN), 200)
    assert len(data) == 2


def test_stale_contract_version_on_milestone_schedule_rejected(api):
    """PRD §2.6: "If the contract's current `version` has advanced beyond that
    value — because another writer already scheduled a milestone set and bumped the
    contract's `version` — the schedule is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_contract_version_on_milestone_schedule
    """
    ctx = setup_contracted_commission(api, allocation_cents=1000000, contract_amount_cents=1000000)
    stale_version = ctx["contract"]["version"]
    validate_success(api.schedule_milestones(
        ctx["contract"]["id"],
        make_milestone_schedule_payload([{"sequence": 1, "title": "Full", "pct": 1.0}],
                                        stale_version), ADMIN), 201)
    resp = api.schedule_milestones(
        ctx["contract"]["id"],
        make_milestone_schedule_payload([{"sequence": 1, "title": "Redo", "pct": 1.0}],
                                        stale_version), ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


def test_milestone_submit_blocked_when_contract_draft(api):
    """PRD §3.5: "the owner moves a milestone `PENDING → SUBMITTED`, provided the
    milestone is `PENDING` and its parent contract is `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/milestone_submit_requires_contract_active
    """
    ctx = setup_contracted_commission(api, allocation_cents=1000000, contract_amount_cents=1000000)
    milestones = schedule_milestones(
        api, ctx["contract"]["id"], [{"sequence": 1, "title": "Full", "pct": 1.0}])
    m_id = milestones[0]["id"]
    resp = api.submit_milestone(m_id, make_artist_headers(ctx["artist"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_milestone_stays_pending_when_submit_rejected(api):
    """PRD §3.5: "the owner moves a milestone `PENDING → SUBMITTED`, provided the
    milestone is `PENDING` and its parent contract is `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/milestone_submit_requires_contract_active
    """
    ctx = setup_contracted_commission(api, allocation_cents=1000000, contract_amount_cents=1000000)
    milestones = schedule_milestones(
        api, ctx["contract"]["id"], [{"sequence": 1, "title": "Full", "pct": 1.0}])
    m_id = milestones[0]["id"]
    api.submit_milestone(m_id, make_artist_headers(ctx["artist"]["id"]))
    listed = get_success_data(api.list_milestones(ctx["contract"]["id"], ADMIN))
    assert listed[0]["status"] == "PENDING"


def test_milestone_payment_triggers_full_cascade(api):
    """PRD §3.5: "If, after a milestone is paid, the contract's `paid_cents` equals
    its `contract_amount_cents`, the contract transitions `ACTIVE → COMPLETED`;
    that completion transitions the linked artwork (the one whose `contract_id` is
    this contract) `FABRICATION → FABRICATED`; and the artwork reaching
    `FABRICATED` transitions the parent commission (reached via the contract's
    `commission_id`) `CONTRACTED → FULFILLED`."

    Design: Difficulty/transitive_cascade/milestone_pay_fabrication_fulfillment_cascade
    """
    ctx = setup_active_contract_with_artwork(
        api, allocation_cents=1000000, contract_amount_cents=1000000,
        milestones=[{"sequence": 1, "title": "Full", "pct": 1.0}])
    m_id = ctx["milestones"][0]["id"]
    validate_success(api.submit_milestone(m_id, make_artist_headers(ctx["artist"]["id"])), 200)
    milestone = validate_success(api.approve_milestone(m_id, ADMIN), 200)
    assert milestone["status"] == "PAID"
    contract = get_success_data(api.get_contract(ctx["contract"]["id"], ADMIN))
    assert contract["paid_cents"] == 1000000
    assert contract["status"] == "COMPLETED"
    artwork = get_success_data(api.get_artwork(ctx["artwork"]["id"], ADMIN))
    assert artwork["location_status"] == "FABRICATED"
    commission = get_success_data(api.get_commission(ctx["commission"]["id"], ADMIN))
    assert commission["status"] == "FULFILLED"


def test_final_payment_completes_contract_and_fabricates_artwork(api):
    """PRD §3.5: "a `SUBMITTED` milestone whose contract is `ACTIVE` transitions
    `SUBMITTED → PAID`, and the contract's `paid_cents` increases by that
    milestone's `amount_cents` while `remaining_cents` decreases by the same
    amount."

    Design: Difficulty/transitive_cascade/milestone_pay_fabrication_fulfillment_cascade
    """
    ctx = setup_active_contract_with_artwork(
        api, allocation_cents=1000000, contract_amount_cents=1000000,
        milestones=[{"sequence": 1, "title": "Full", "pct": 1.0}])
    m_id = ctx["milestones"][0]["id"]
    validate_success(api.submit_milestone(m_id, make_artist_headers(ctx["artist"]["id"])), 200)
    validate_success(api.approve_milestone(m_id, ADMIN), 200)
    contract = get_success_data(api.get_contract(ctx["contract"]["id"], ADMIN))
    assert contract["status"] == "COMPLETED"
    assert contract["remaining_cents"] == 0
    assert_payment_invariant(contract)
    artwork = get_success_data(api.get_artwork(ctx["artwork"]["id"], ADMIN))
    assert artwork["location_status"] == "FABRICATED"
