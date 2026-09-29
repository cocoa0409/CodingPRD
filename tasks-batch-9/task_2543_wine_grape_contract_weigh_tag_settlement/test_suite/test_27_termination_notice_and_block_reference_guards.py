"""The notice a producer is owed before an agreement ends, and the three ways a block can fail
to be the right block. The notice period is the contract's own term rather than a house
constant, and a block that belongs to somebody else, has been retired, or was never committed
to the contract is refused before any work is scheduled against it.
"""
from test_helpers import (
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
    move_clock,
    offer_contract,
    read_contract,
    single_installment_plan,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_PINNED_AT = "2026-08-01T00:00:00Z"

# Ninety days after the pinned clock is 2026-10-30T00:00:00Z; sixty days after it is
# 2026-09-30T00:00:00Z. Each probe sits one second on either side of its own contract's floor.
ONE_SECOND_SHORT_OF_NINETY_DAYS = "2026-10-29T23:59:59Z"
EXACTLY_NINETY_DAYS = "2026-10-30T00:00:00Z"
ONE_SECOND_SHORT_OF_SIXTY_DAYS = "2026-09-29T23:59:59Z"
EXACTLY_SIXTY_DAYS = "2026-09-30T00:00:00Z"

A_SHORTER_NOTICE_PERIOD = 60

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


# --- The notice period is a contract term, not a house constant -------------------------


def _two_active_contracts_with_different_notice_periods() -> dict:
    """One producer, one block, and two ACTIVE agreements over it — one on the house default
    notice period and one that negotiated a shorter one."""
    move_clock(CLOCK_PINNED_AT)
    ctx = {"grower": create_grower(**PRODUCER)}
    ctx["block"] = create_block(ctx["grower"]["id"], **BLOCK)
    ctx["spec"] = create_quality_spec(**SPEC)

    for key, code, extra in (
        ("default_notice", "GC-TERM-DEFAULT", {}),
        ("shorter_notice", "GC-TERM-SIXTY", {"termination_notice_days": A_SHORTER_NOTICE_PERIOD}),
    ):
        contract = create_contract(
            ctx["grower"]["id"],
            ctx["spec"]["id"],
            contract_code=code,
            contract_basis="TONNAGE",
            committed_tons=40.000,
            base_price_per_ton_cents=450000,
            over_delivery_policy="ACCEPT_AT_CONTRACT",
            term_start_vintage=2026,
            term_end_vintage=2028,
            installment_plan=single_installment_plan(),
            **extra,
        )
        create_allocation(contract["id"], ctx["block"]["id"])
        offer_contract(contract["id"])
        ctx[key] = accept_contract(contract["id"], ctx["grower"]["id"])
    return ctx


def _serve_notice(api, contract_id: str, effective_at: str, reason: str):
    return api.serve_termination_notice(
        contract_id, {"effective_at": effective_at, "reason": reason}, MANAGER
    )


def test_a_notice_one_second_short_of_the_default_period_is_refused(api):
    """Eighty-nine days and change is not ninety days, and the floor is not rounded in the
    winery's favour.

    PRD: "The notice must be long enough — `effective_at` must be at or after the logical clock
    plus `termination_notice_days` days, else `ERR_TERMINATION_NOTICE_TOO_SHORT` with HTTP 422"

    Design: Corner/validations/termination_notice_shorter_than_the_contractual_period_is_refused
    """
    ctx = _two_active_contracts_with_different_notice_periods()

    validate_error(
        _serve_notice(
            api,
            ctx["default_notice"]["id"],
            ONE_SECOND_SHORT_OF_NINETY_DAYS,
            "89 days and change",
        ),
        ApiErrorId.ERR_TERMINATION_NOTICE_TOO_SHORT.value,
        422,
    )


def test_the_period_compared_against_is_each_contracts_own(api):
    """The same instant that is far too early for the default agreement is also too early for
    the sixty-day one by one second — so the comparison is per-contract, and an implementation
    that hard-codes ninety days would have accepted this.

    PRD: "`termination_notice_days` defaults to 90, must be at least 1, and does double duty: it
    is both the minimum notice a termination requires and the width of the renewal window."

    Design: Corner/validations/termination_notice_shorter_than_the_contractual_period_is_refused
    """
    ctx = _two_active_contracts_with_different_notice_periods()
    assert ctx["shorter_notice"]["termination_notice_days"] == A_SHORTER_NOTICE_PERIOD

    validate_error(
        _serve_notice(
            api,
            ctx["shorter_notice"]["id"],
            ONE_SECOND_SHORT_OF_SIXTY_DAYS,
            "59 days and change",
        ),
        ApiErrorId.ERR_TERMINATION_NOTICE_TOO_SHORT.value,
        422,
    )


def test_exactly_the_negotiated_period_is_accepted(api):
    """At or after means the boundary is admitted: sixty days to the second ends the shorter
    agreement, and the renewal dimension is closed in the same breath.

    PRD: "The notice stores `termination_effective_at` from the `effective_at` input, sets
    `renewal_status` to `NOT_RENEWING`, and clears the harvest"

    Design: Corner/validations/termination_notice_shorter_than_the_contractual_period_is_refused
    """
    ctx = _two_active_contracts_with_different_notice_periods()

    served = validate_success(
        _serve_notice(api, ctx["shorter_notice"]["id"], EXACTLY_SIXTY_DAYS, "exactly 60 days")
    )
    assert served["lifecycle_status"] == "TERMINATION_PENDING"
    assert served["renewal_status"] == "NOT_RENEWING"
    assert served["termination_effective_at"] == EXACTLY_SIXTY_DAYS


def test_exactly_the_default_period_is_accepted_too(api):
    """The same inclusive boundary on the other contract, ninety days out.

    PRD: "Serving notice of termination is a `GrowerRelationsManager` action carrying
    `effective_at` and an optional `reason`; it drives the lifecycle `ACTIVE →
    TERMINATION_PENDING`."

    Design: Corner/validations/termination_notice_shorter_than_the_contractual_period_is_refused
    """
    ctx = _two_active_contracts_with_different_notice_periods()

    served = validate_success(
        _serve_notice(api, ctx["default_notice"]["id"], EXACTLY_NINETY_DAYS, "exactly 90 days")
    )
    assert served["lifecycle_status"] == "TERMINATION_PENDING"
    assert served["termination_effective_at"] == EXACTLY_NINETY_DAYS


def test_neither_refused_notice_left_a_mark_on_its_contract(api):
    """A refusal at rank 40 writes nothing: both agreements are still running and neither has an
    effective date on file.

    PRD: "When the clock later reaches or passes `termination_effective_at`, the contract
    transitions `TERMINATION_PENDING → TERMINATED`, which is terminal."

    Design: Corner/validations/termination_notice_shorter_than_the_contractual_period_is_refused
    """
    ctx = _two_active_contracts_with_different_notice_periods()
    _serve_notice(api, ctx["default_notice"]["id"], ONE_SECOND_SHORT_OF_NINETY_DAYS, "too short")
    _serve_notice(api, ctx["shorter_notice"]["id"], ONE_SECOND_SHORT_OF_SIXTY_DAYS, "too short")

    for key in ("default_notice", "shorter_notice"):
        contract = read_contract(ctx[key]["id"])
        assert contract["lifecycle_status"] == "ACTIVE"
        assert contract["termination_effective_at"] is None


# --- Three ways a block can be the wrong block -----------------------------------------


SETUP_AT = "2026-08-20T08:00:00Z"
SAMPLING_WINDOW = ("2026-08-20T09:00:00Z", "2026-08-20T11:00:00Z")

A_NEIGHBOURING_PRODUCER = {
    "name": "Stonegate Ranch",
    "license_number": "PL-44822",
    "region_code": "SONOMA-COAST",
}
AN_UNALLOCATED_BLOCK = {
    "block_code": "B-13",
    "varietal": "MERLOT",
    "acres": 8.000,
    "expected_yield_tons_per_acre": 2.500,
    "ava_code": "NAPA-VALLEY",
}
A_RETIRED_BLOCK = {
    "block_code": "B-99",
    "varietal": "ZINFANDEL",
    "acres": 4.000,
    "expected_yield_tons_per_acre": 2.000,
    "ava_code": "NAPA-VALLEY",
    "status": "RETIRED",
}
A_NEIGHBOURS_BLOCK = {
    "block_code": "BX-1",
    "varietal": "PINOT_NOIR",
    "acres": 10.000,
    "expected_yield_tons_per_acre": 1.800,
    "ava_code": "RUSSIAN-RIVER",
}


def _one_contract_and_four_blocks() -> dict:
    """An ACTIVE contract with exactly one block committed to it, alongside a second block of the
    same producer that was never committed, a retired block, and a neighbour's block."""
    move_clock(SETUP_AT)
    ctx = {
        "grower": create_grower(**PRODUCER),
        "neighbour": create_grower(**A_NEIGHBOURING_PRODUCER),
    }
    ctx["allocated_block"] = create_block(ctx["grower"]["id"], **BLOCK)
    ctx["unallocated_block"] = create_block(ctx["grower"]["id"], **AN_UNALLOCATED_BLOCK)
    ctx["retired_block"] = create_block(ctx["grower"]["id"], **A_RETIRED_BLOCK)
    ctx["foreign_block"] = create_block(ctx["neighbour"]["id"], **A_NEIGHBOURS_BLOCK)
    ctx["spec"] = create_quality_spec(**SPEC)
    ctx["crew"] = create_crew(crew_code="SC-1", region_code="NAPA-NORTH", max_concurrent_visits=2)

    contract = create_contract(
        ctx["grower"]["id"],
        ctx["spec"]["id"],
        contract_code="GC-BLOCK-GUARD",
        contract_basis="TONNAGE",
        committed_tons=40.000,
        base_price_per_ton_cents=450000,
        over_delivery_policy="ACCEPT_AT_CONTRACT",
        term_start_vintage=2026,
        term_end_vintage=2027,
        installment_plan=single_installment_plan(),
    )
    ctx["allocation"] = create_allocation(contract["id"], ctx["allocated_block"]["id"])
    offer_contract(contract["id"])
    ctx["contract"] = accept_contract(contract["id"], ctx["grower"]["id"])
    return ctx


def test_a_neighbours_block_cannot_be_committed_to_this_contract(api):
    """The block exists and is perfectly healthy, but it is farmed by somebody who is not party
    to this agreement.

    PRD: "The block must belong to the contract's producer and must not be retired — a block
    whose `grower_id` differs from the contract's `grower_id`, or whose `status` is `RETIRED`, is
    refused with `ERR_BLOCK_GROWER_MISMATCH` and HTTP 409."

    Design: Corner/validations/block_reference_guards_reject_unallocated_and_foreign_blocks
    """
    ctx = _one_contract_and_four_blocks()

    validate_error(
        api.create_allocation(
            {"contract_id": ctx["contract"]["id"], "block_id": ctx["foreign_block"]["id"]},
            MANAGER,
        ),
        ApiErrorId.ERR_BLOCK_GROWER_MISMATCH.value,
        409,
    )


def test_the_producers_own_retired_block_is_refused_the_same_way(api):
    """Ownership is not the only half of the rule: a pulled-out block of the right producer is
    refused under the same identifier, so the two conditions really are one guard.

    PRD: "An optional `status` defaults to `ACTIVE`, the alternative being `RETIRED`."

    Design: Corner/validations/block_reference_guards_reject_unallocated_and_foreign_blocks
    """
    ctx = _one_contract_and_four_blocks()
    assert ctx["retired_block"]["status"] == "RETIRED"
    assert ctx["retired_block"]["grower_id"] == ctx["grower"]["id"]

    validate_error(
        api.create_allocation(
            {"contract_id": ctx["contract"]["id"], "block_id": ctx["retired_block"]["id"]},
            MANAGER,
        ),
        ApiErrorId.ERR_BLOCK_GROWER_MISMATCH.value,
        409,
    )


def test_field_work_cannot_be_scheduled_on_a_block_the_contract_never_committed(api):
    """The second block belongs to the right producer and is entirely active, so only the missing
    allocation row can be the reason the crew is turned away.

    PRD: "The block must be allocated to that contract — the contract-and-block pair must already
    have an allocation row — or the booking is refused with `ERR_BLOCK_NOT_ALLOCATED` and HTTP
    409."

    Design: Corner/validations/block_reference_guards_reject_unallocated_and_foreign_blocks
    """
    ctx = _one_contract_and_four_blocks()

    validate_error(
        api.create_sampling_visit(
            create_sampling_visit_payload(
                ctx["contract"]["id"],
                ctx["unallocated_block"]["id"],
                ctx["crew"]["id"],
                SAMPLING_WINDOW[0],
                SAMPLING_WINDOW[1],
            ),
            COORDINATOR,
        ),
        ApiErrorId.ERR_BLOCK_NOT_ALLOCATED.value,
        409,
    )


def test_none_of_the_refused_references_joined_the_contract(api):
    """Walking the contract's side of the many-to-many finds the one block that was legitimately
    committed and nothing else.

    PRD: "Allocations are listed with the optional filters `contract_id` and `block_id`, which is
    how either side of the many-to-many between contracts and blocks is walked."

    Design: Corner/validations/block_reference_guards_reject_unallocated_and_foreign_blocks
    """
    ctx = _one_contract_and_four_blocks()
    for block_key in ("foreign_block", "retired_block"):
        api.create_allocation(
            {"contract_id": ctx["contract"]["id"], "block_id": ctx[block_key]["id"]}, MANAGER
        )

    rows, meta = validate_paginated(
        api.list_allocations(MANAGER, params={"contract_id": ctx["contract"]["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["block_id"] == ctx["allocated_block"]["id"]
