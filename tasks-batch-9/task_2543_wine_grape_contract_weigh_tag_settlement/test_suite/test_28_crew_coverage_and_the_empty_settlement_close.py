"""Two rules that are only correct if the right row is consulted. A sampling crew's territory is
matched against the producer that farms the block — a hop away through the block — and not
against the block's own appellation; and a close with nothing delivered is stopped by the
missing settlement line rather than by either of the weigh-tag guards, which hold vacuously.
"""
from test_helpers import (
    CLERK,
    COORDINATOR,
    MANAGER,
    ApiErrorId,
    accept_contract,
    create_allocation,
    create_block,
    create_contract,
    create_crew,
    create_grower,
    create_quality_spec,
    create_sampling_visit_payload,
    list_settlement_lines,
    move_clock,
    offer_contract,
    read_contract,
    read_crew,
    single_installment_plan,
    validate_error,
    validate_paginated,
    validate_success,
)

SETUP_AT = "2026-08-20T08:00:00Z"
FIELD_WINDOW = ("2026-08-20T09:00:00Z", "2026-08-20T11:00:00Z")

PRODUCER = {
    "name": "Ridgeline Vineyards",
    "license_number": "PL-44821",
    "region_code": "NAPA-NORTH",
}
BLOCK = {
    "block_code": "B-12",
    "varietal": "CABERNET_SAUVIGNON",
    "acres": 20.000,
    "expected_yield_tons_per_acre": 2.000,
    "ava_code": "NAPA-VALLEY",
}
SPEC = {
    "spec_code": "CAB-STD-2026",
    "min_brix_accept": 20.0,
    "brix_bonus_start": 24.0,
    "brix_penalty_start": 22.0,
    "rot_rejection_pct": 8.0,
    "min_brix_pick_call": 21.0,
}


# --- The crew's territory is the producer's region, reached through the block ------------


def _one_producer_and_two_crews() -> dict:
    """A NAPA-NORTH producer with an allocated block, one crew that covers that territory and
    one that covers a different one. The contract is left in DRAFT, which sampling permits."""
    move_clock(SETUP_AT)
    ctx = {"grower": create_grower(**PRODUCER)}
    ctx["block"] = create_block(ctx["grower"]["id"], **BLOCK)
    ctx["spec"] = create_quality_spec(**SPEC)
    ctx["local_crew"] = create_crew(
        crew_code="SC-NAPA", region_code="NAPA-NORTH", max_concurrent_visits=2
    )
    ctx["foreign_crew"] = create_crew(
        crew_code="SC-SONOMA", region_code="SONOMA-COAST", max_concurrent_visits=2
    )
    ctx["contract"] = create_contract(
        ctx["grower"]["id"],
        ctx["spec"]["id"],
        contract_code="GC-CREW-REGION",
        contract_basis="TONNAGE",
        committed_tons=40.000,
        base_price_per_ton_cents=450000,
        over_delivery_policy="ACCEPT_AT_CONTRACT",
        term_start_vintage=2026,
        term_end_vintage=2027,
        installment_plan=single_installment_plan(),
    )
    create_allocation(ctx["contract"]["id"], ctx["block"]["id"])
    return ctx


def _a_visit(api, ctx: dict, crew_key: str):
    """A booking request that is legal in every respect except the crew's coverage."""
    return api.create_sampling_visit(
        create_sampling_visit_payload(
            ctx["contract"]["id"],
            ctx["block"]["id"],
            ctx[crew_key]["id"],
            FIELD_WINDOW[0],
            FIELD_WINDOW[1],
        ),
        COORDINATOR,
    )


def test_a_crew_from_another_territory_may_not_sample_this_block(api):
    """The crew is idle, the window is free and the block is allocated, so only the territory
    can be the reason — and the refusal is the 422 rather than the 409s ranked above it.

    PRD: "The crew must cover the right territory: its `region_code` must equal the
    `region_code` of the producer that farms the sampled block, and a mismatch is refused with
    `ERR_CREW_REGION_MISMATCH` and HTTP 422."

    Design: Corner/validations/sampling_crew_must_cover_the_producers_region
    """
    ctx = _one_producer_and_two_crews()

    validate_error(
        _a_visit(api, ctx, "foreign_crew"),
        ApiErrorId.ERR_CREW_REGION_MISMATCH.value,
        422,
    )


def test_the_covering_crew_is_booked_on_the_same_window(api):
    """Identical request, different crew: the visit is created, and it is created against a
    contract that has never been offered — sampling is deliberately available that early.

    PRD: "The contract must be in `DRAFT`, `OFFERED` or `ACTIVE`; anything else is
    `ERR_CONTRACT_STATE_INVALID`."

    Design: Corner/validations/sampling_crew_must_cover_the_producers_region
    """
    ctx = _one_producer_and_two_crews()
    assert ctx["contract"]["lifecycle_status"] == "DRAFT"

    visit = validate_success(_a_visit(api, ctx, "local_crew"), 201)
    assert visit["status"] == "SCHEDULED"
    assert visit["crew_id"] == ctx["local_crew"]["id"]


def test_the_comparison_is_against_the_producer_and_not_the_blocks_appellation(api):
    """The accepted crew covers NAPA-NORTH while the block it samples is in NAPA-VALLEY, so a
    comparison against the block's own appellation would have refused this booking; the
    territory is read from the producer that farms the block.

    PRD: "The `region_code` is not decoration: it is what a sampling crew's coverage is matched
    against later."

    Design: Corner/validations/sampling_crew_must_cover_the_producers_region
    """
    ctx = _one_producer_and_two_crews()
    assert ctx["block"]["ava_code"] != ctx["local_crew"]["region_code"]
    assert ctx["grower"]["region_code"] == ctx["local_crew"]["region_code"]

    visit = validate_success(_a_visit(api, ctx, "local_crew"), 201)
    assert visit["block_id"] == ctx["block"]["id"]


def test_the_refused_crew_was_never_occupied(api):
    """The visit listing is the crew's diary, and the crew from the other territory has nothing
    in it.

    PRD: "Visits are listed with the optional filters `contract_id`, `block_id`, `crew_id`,
    `status` and `maturity_flag`."

    Design: Corner/validations/sampling_crew_must_cover_the_producers_region
    """
    ctx = _one_producer_and_two_crews()
    _a_visit(api, ctx, "foreign_crew")
    _a_visit(api, ctx, "local_crew")

    _, foreign = validate_paginated(
        api.list_sampling_visits(COORDINATOR, params={"crew_id": ctx["foreign_crew"]["id"]})
    )
    assert foreign["total_count"] == 0
    _, local = validate_paginated(
        api.list_sampling_visits(COORDINATOR, params={"crew_id": ctx["local_crew"]["id"]})
    )
    assert local["total_count"] == 1


def test_only_the_accepted_booking_moved_a_crews_derived_count(api):
    """Each crew's own occupancy figure tells the same story as the listing.

    PRD: "A crew also exposes a derived `scheduled_visit_count`, the number of its visits that
    are either still scheduled or already completed."

    Design: Corner/validations/sampling_crew_must_cover_the_producers_region
    """
    ctx = _one_producer_and_two_crews()
    _a_visit(api, ctx, "foreign_crew")
    _a_visit(api, ctx, "local_crew")

    assert read_crew(ctx["local_crew"]["id"])["scheduled_visit_count"] == 1
    assert read_crew(ctx["foreign_crew"]["id"])["scheduled_visit_count"] == 0


# --- A close with nothing to settle ------------------------------------------------------


def _an_active_contract_that_never_took_a_load() -> dict:
    """An ACTIVE contract with one allocation and not a single weigh tag behind it."""
    move_clock(SETUP_AT)
    ctx = {"grower": create_grower(**PRODUCER)}
    ctx["block"] = create_block(ctx["grower"]["id"], **BLOCK)
    ctx["spec"] = create_quality_spec(**SPEC)
    contract = create_contract(
        ctx["grower"]["id"],
        ctx["spec"]["id"],
        contract_code="GC-EMPTY-CLOSE",
        contract_basis="TONNAGE",
        committed_tons=40.000,
        base_price_per_ton_cents=450000,
        over_delivery_policy="ACCEPT_AT_CONTRACT",
        term_start_vintage=2026,
        term_end_vintage=2026,
        installment_plan=single_installment_plan(),
    )
    create_allocation(contract["id"], ctx["block"]["id"])
    offer_contract(contract["id"])
    ctx["contract"] = accept_contract(contract["id"], ctx["grower"]["id"])
    return ctx


def test_a_vintage_with_nothing_delivered_cannot_be_closed(api):
    """The crush pad is quiet in the most complete sense — there is nothing on it at all — and
    the close is still refused, because a quiet pad is not the same as a settled one.

    PRD: "And at least one settlement line of the contract must be in status `PROVISIONAL`, else
    there is nothing to settle and the close is refused with `ERR_NO_PROVISIONAL_LINES`."

    Design: Corner/validations/settlement_close_without_provisional_lines_is_refused
    """
    ctx = _an_active_contract_that_never_took_a_load()

    validate_error(
        api.close_settlement(ctx["contract"]["id"], MANAGER),
        ApiErrorId.ERR_NO_PROVISIONAL_LINES.value,
        409,
    )


def test_neither_weigh_tag_guard_could_have_spoken(api):
    """Both tag guards are satisfied vacuously: there is no untared load and no ungraded or
    contested one, because there is no line and no tag whatsoever — so the refusal above can
    only be the third guard.

    PRD: "No weigh tag reachable through the contract may still sit in `GROSS_CAPTURED` — an
    untared load on the pad blocks the close with `ERR_TAG_WEIGH_STATE_INVALID`. No weigh tag
    reachable through the contract may sit in `PENDING` or `DISPUTED` — an ungraded or contested
    load blocks the close with `ERR_TAG_NOT_DISPUTABLE`."

    Design: Corner/validations/settlement_close_without_provisional_lines_is_refused
    """
    ctx = _an_active_contract_that_never_took_a_load()
    assert list_settlement_lines(contract_id=ctx["contract"]["id"]) == []

    validate_error(
        api.close_settlement(ctx["contract"]["id"], MANAGER),
        ApiErrorId.ERR_NO_PROVISIONAL_LINES.value,
        409,
    )


def test_the_refused_close_left_the_contract_open_and_unsettled(api):
    """The lifecycle did not move and no money figure was invented for an empty vintage.

    PRD: "Until a close happens, `final_settlement_cents`, `prompt_pay_credit_cents`,
    `lien_holdback_cents` and `net_payable_cents` are all 0, `settlement_closed_at` is null, and
    every installment's `planned_amount_cents` and `due_at` are 0 and null respectively."

    Design: Corner/validations/settlement_close_without_provisional_lines_is_refused
    """
    ctx = _an_active_contract_that_never_took_a_load()
    api.close_settlement(ctx["contract"]["id"], MANAGER)

    contract = read_contract(ctx["contract"]["id"])
    assert contract["lifecycle_status"] == "ACTIVE"
    assert contract["settlement_closed_at"] is None
    assert contract["final_settlement_cents"] == 0
    assert contract["net_payable_cents"] == 0


def test_the_refused_close_scheduled_no_money(api):
    """The single installment materialised at acceptance is still waiting for a settlement that
    never happened, so nothing was distributed across it.

    PRD: "The close also stamps `settlement_closed_at` from the logical clock, flips every
    `PROVISIONAL` line to `FINAL`, transitions every installment `PENDING_SETTLEMENT →
    SCHEDULED`, recomputes the producer's `outstanding_lien_balance_cents`, and withdraws the
    harvest"

    Design: Corner/validations/settlement_close_without_provisional_lines_is_refused
    """
    ctx = _an_active_contract_that_never_took_a_load()
    api.close_settlement(ctx["contract"]["id"], MANAGER)

    rows, meta = validate_paginated(
        api.list_installments(CLERK, params={"contract_id": ctx["contract"]["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "PENDING_SETTLEMENT"
    assert rows[0]["planned_amount_cents"] == 0
    assert rows[0]["due_at"] is None
