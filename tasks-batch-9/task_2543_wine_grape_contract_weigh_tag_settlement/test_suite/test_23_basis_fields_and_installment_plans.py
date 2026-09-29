"""The two structural shape rules that need more context than a single field. Which tonnage
field a contract may carry is decided by its declared commercial basis, and the payment
schedule template has to be internally consistent before any money exists to distribute.
"""
from test_helpers import (
    MANAGER,
    ApiErrorId,
    create_block,
    create_grower,
    create_quality_spec,
    move_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_PINNED_AT = "2026-08-01T00:00:00Z"

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
ONE_HUNDRED_PCT = [
    {"installment_no": 1, "pct_of_settlement": 100.0, "due_offset_days": 30, "lien_protected": True}
]


def _a_reference_book() -> dict:
    """One producer, one block and one specification, with the clock pinned."""
    move_clock(CLOCK_PINNED_AT)
    ctx = {"grower": create_grower(**PRODUCER)}
    ctx["block"] = create_block(ctx["grower"]["id"], **BLOCK)
    ctx["spec"] = create_quality_spec(spec_code="CAB-STD-2026", min_brix_pick_call=21.0)
    return ctx


def _contract_payload(ctx: dict, contract_code: str, **fields) -> dict:
    """A contract create body carrying only what the probe needs, so nothing outside the rule
    under test can be blamed for the refusal."""
    payload = {
        "grower_id": ctx["grower"]["id"],
        "quality_spec_id": ctx["spec"]["id"],
        "contract_code": contract_code,
        "base_price_per_ton_cents": 450000,
        "over_delivery_policy": "ACCEPT_AT_CONTRACT",
        "term_start_vintage": 2026,
        "term_end_vintage": 2026,
        "installment_plan": ONE_HUNDRED_PCT,
    }
    payload.update(fields)
    return payload


# --- The basis decides which tonnage field is admissible ------------------------------


def _both_parents_created(api) -> dict:
    """One ACREAGE parent and one TONNAGE parent, each legal on its own basis, standing ready
    for the allocation probes."""
    ctx = _a_reference_book()
    ctx["acreage_contract"] = validate_success(
        api.create_grape_contract(
            _contract_payload(
                ctx,
                "GC-ACREAGE-PARENT",
                contract_basis="ACREAGE",
                contracted_yield_tons_per_acre=2.500,
            ),
            MANAGER,
        ),
        201,
    )
    ctx["tonnage_contract"] = validate_success(
        api.create_grape_contract(
            _contract_payload(
                ctx, "GC-TONNAGE-PARENT", contract_basis="TONNAGE", committed_tons=40.000
            ),
            MANAGER,
        ),
        201,
    )
    return ctx


def test_a_tonnage_contract_without_its_committed_tonnage_is_refused(api):
    """The requiring half of the rule: the basis names a field the body has to carry.

    PRD: "`contract_basis` is one of `TONNAGE`, `ACREAGE` or `BLOCK`, and it decides which
    tonnage field the request must carry: a `TONNAGE` contract requires `committed_tons` and
    must not carry `contracted_yield_tons_per_acre`; an `ACREAGE` contract requires
    `contracted_yield_tons_per_acre` and must not carry `committed_tons`; a `BLOCK` contract
    must carry neither."

    Design: Corner/validations/basis_conditional_field_rules_reject_mismatched_payloads_422
    """
    ctx = _both_parents_created(api)

    validate_error(
        api.create_grape_contract(
            _contract_payload(ctx, "GC-P9-A", contract_basis="TONNAGE"), MANAGER
        ),
        ApiErrorId.ERR_BASIS_FIELD_MISMATCH.value,
        422,
    )


def test_a_tonnage_contract_carrying_the_acreage_yield_as_well_is_refused(api):
    """The forbidding half: the required field is present, so only the surplus one can be the
    reason — a stray yield figure on a tonnage deal is refused rather than ignored.

    PRD: "Supplying or omitting either field inconsistently with the declared basis is refused
    with `ERR_BASIS_FIELD_MISMATCH` and HTTP 422."

    Design: Corner/validations/basis_conditional_field_rules_reject_mismatched_payloads_422
    """
    ctx = _both_parents_created(api)

    validate_error(
        api.create_grape_contract(
            _contract_payload(
                ctx,
                "GC-P9-B",
                contract_basis="TONNAGE",
                committed_tons=40.000,
                contracted_yield_tons_per_acre=2.500,
            ),
            MANAGER,
        ),
        ApiErrorId.ERR_BASIS_FIELD_MISMATCH.value,
        422,
    )


def test_an_acreage_contract_carrying_committed_tonnage_is_refused(api):
    """The mirror image, and the one that matters most: a stray committed tonnage on an acreage
    deal is exactly the field an implementation would otherwise derive a cap from.

    PRD: "an `ACREAGE` contract requires `contracted_yield_tons_per_acre` and must not carry
    `committed_tons`"

    Design: Corner/validations/basis_conditional_field_rules_reject_mismatched_payloads_422
    """
    ctx = _both_parents_created(api)

    validate_error(
        api.create_grape_contract(
            _contract_payload(
                ctx,
                "GC-P9-C",
                contract_basis="ACREAGE",
                committed_tons=40.000,
                contracted_yield_tons_per_acre=2.500,
            ),
            MANAGER,
        ),
        ApiErrorId.ERR_BASIS_FIELD_MISMATCH.value,
        422,
    )


def test_a_block_contract_may_carry_no_tonnage_field_at_all(api):
    """The block basis takes its ceilings from the blocks themselves, so either field is a
    contradiction.

    PRD: "a `BLOCK` contract must carry neither."

    Design: Corner/validations/basis_conditional_field_rules_reject_mismatched_payloads_422
    """
    ctx = _both_parents_created(api)

    validate_error(
        api.create_grape_contract(
            _contract_payload(ctx, "GC-P9-D", contract_basis="BLOCK", committed_tons=40.000),
            MANAGER,
        ),
        ApiErrorId.ERR_BASIS_FIELD_MISMATCH.value,
        422,
    )


def test_an_allocation_on_an_acreage_parent_must_state_its_acreage(api):
    """The same rule reaches across into the child row, and the parent's basis — not the
    allocation's own body — decides what is required.

    PRD: "A block allocation is authored by the `GrowerRelationsManager` and carries a
    `contract_id`, a `block_id`, and — only on an `ACREAGE`-basis contract — `allocated_acres`,
    a positive number with at most 3 decimals that may not exceed the block's own `acres`."

    Design: Corner/validations/basis_conditional_field_rules_reject_mismatched_payloads_422
    """
    ctx = _both_parents_created(api)

    validate_error(
        api.create_allocation(
            {"contract_id": ctx["acreage_contract"]["id"], "block_id": ctx["block"]["id"]},
            MANAGER,
        ),
        ApiErrorId.ERR_BASIS_FIELD_MISMATCH.value,
        422,
    )


def test_an_allocation_on_a_tonnage_parent_may_not_state_an_acreage(api):
    """And the forbidding half on the child row: the acreage figure is inadmissible wherever
    the parent is not an acreage deal.

    PRD: "On a `TONNAGE` or `BLOCK` contract, `allocated_acres` must be absent; supplying it
    there, or omitting it on an `ACREAGE` contract, is the same `ERR_BASIS_FIELD_MISMATCH`."

    Design: Corner/validations/basis_conditional_field_rules_reject_mismatched_payloads_422
    """
    ctx = _both_parents_created(api)

    validate_error(
        api.create_allocation(
            {
                "contract_id": ctx["tonnage_contract"]["id"],
                "block_id": ctx["block"]["id"],
                "allocated_acres": 10.500,
            },
            MANAGER,
        ),
        ApiErrorId.ERR_BASIS_FIELD_MISMATCH.value,
        422,
    )


def test_none_of_the_six_mismatched_payloads_created_a_row(api):
    """A refusal at rank 9 is a refusal outright: only the two legal parents exist and no block
    was ever committed.

    PRD: "When a single request violates several rules, exactly one error comes back, and which
    one is fully determined."

    Design: Corner/validations/basis_conditional_field_rules_reject_mismatched_payloads_422
    """
    ctx = _both_parents_created(api)
    for payload in (
        _contract_payload(ctx, "GC-P9-A", contract_basis="TONNAGE"),
        _contract_payload(ctx, "GC-P9-D", contract_basis="BLOCK", committed_tons=40.000),
    ):
        api.create_grape_contract(payload, MANAGER)
    api.create_allocation(
        {"contract_id": ctx["acreage_contract"]["id"], "block_id": ctx["block"]["id"]}, MANAGER
    )

    _, contracts = validate_paginated(api.list_grape_contracts(MANAGER))
    assert contracts["total_count"] == 2
    _, allocations = validate_paginated(api.list_allocations(MANAGER))
    assert allocations["total_count"] == 0


# --- The payment schedule template must add up ----------------------------------------


SEVEN_ELEMENTS = [
    {"installment_no": 1, "pct_of_settlement": 20.0, "due_offset_days": 10, "lien_protected": True},
    {"installment_no": 2, "pct_of_settlement": 20.0, "due_offset_days": 20, "lien_protected": True},
    {"installment_no": 3, "pct_of_settlement": 20.0, "due_offset_days": 30, "lien_protected": True},
    {"installment_no": 4, "pct_of_settlement": 20.0, "due_offset_days": 40, "lien_protected": True},
    {"installment_no": 5, "pct_of_settlement": 10.0, "due_offset_days": 50, "lien_protected": True},
    {"installment_no": 6, "pct_of_settlement": 5.0, "due_offset_days": 60, "lien_protected": True},
    {"installment_no": 7, "pct_of_settlement": 5.0, "due_offset_days": 70, "lien_protected": True},
]
NUMBERED_WITH_A_GAP = [
    {"installment_no": 1, "pct_of_settlement": 50.0, "due_offset_days": 30, "lien_protected": True},
    {"installment_no": 3, "pct_of_settlement": 50.0, "due_offset_days": 60, "lien_protected": True},
]
NUMBERED_TWICE = [
    {"installment_no": 1, "pct_of_settlement": 50.0, "due_offset_days": 30, "lien_protected": True},
    {"installment_no": 1, "pct_of_settlement": 50.0, "due_offset_days": 60, "lien_protected": True},
]
A_ZERO_SHARE = [
    {"installment_no": 1, "pct_of_settlement": 100.0, "due_offset_days": 30, "lien_protected": True},
    {"installment_no": 2, "pct_of_settlement": 0.0, "due_offset_days": 60, "lien_protected": True},
]
ONE_TENTH_SHORT = [
    {"installment_no": 1, "pct_of_settlement": 50.0, "due_offset_days": 30, "lien_protected": True},
    {"installment_no": 2, "pct_of_settlement": 49.9, "due_offset_days": 60, "lien_protected": True},
]
AWKWARD_BUT_EXACT = [
    {"installment_no": 1, "pct_of_settlement": 33.4, "due_offset_days": 30, "lien_protected": True},
    {"installment_no": 2, "pct_of_settlement": 33.3, "due_offset_days": 60, "lien_protected": True},
    {"installment_no": 3, "pct_of_settlement": 33.3, "due_offset_days": 90, "lien_protected": False},
]


def _a_plan_probe(api, ctx: dict, contract_code: str, installment_plan: list):
    """A contract create that is legal in every respect except its payment schedule."""
    return api.create_grape_contract(
        _contract_payload(
            ctx,
            contract_code,
            contract_basis="TONNAGE",
            committed_tons=40.000,
            installment_plan=installment_plan,
        ),
        MANAGER,
    )


def test_a_plan_with_no_elements_at_all_is_refused(api):
    """The schedule is mandatory in substance as well as in form: an empty array is below the
    one-element floor.

    PRD: "`installment_plan` is mandatory and is the payment schedule template. It is an ordered
    array of 1 to 6 elements, each element carrying an integer `installment_no`, a number
    `pct_of_settlement`, an integer `due_offset_days` and a boolean `lien_protected`."

    Design: Corner/validations/malformed_installment_plans_are_rejected_422
    """
    ctx = _a_reference_book()

    validate_error(
        _a_plan_probe(api, ctx, "GC-P10-A", []),
        ApiErrorId.ERR_INVALID_INSTALLMENT_PLAN.value,
        422,
    )


def test_a_seventh_installment_pushes_the_plan_over_the_ceiling(api):
    """Six is the ceiling, and the seven shares still sum to exactly 100.0 — so only the
    cardinality can be the reason.

    PRD: "A plan with zero or more than six elements, gapped or repeated numbering, a
    non-positive percentage, or percentages that miss 100.0 is refused with
    `ERR_INVALID_INSTALLMENT_PLAN` and HTTP 422."

    Design: Corner/validations/malformed_installment_plans_are_rejected_422
    """
    ctx = _a_reference_book()
    assert sum(row["pct_of_settlement"] for row in SEVEN_ELEMENTS) == 100.0

    validate_error(
        _a_plan_probe(api, ctx, "GC-P10-B", SEVEN_ELEMENTS),
        ApiErrorId.ERR_INVALID_INSTALLMENT_PLAN.value,
        422,
    )


def test_numbering_that_skips_a_value_is_refused(api):
    """The numbering is an exact sequence, not merely an increasing one, because the close walks
    it in ascending order and hands the residual to the last number.

    PRD: "The `installment_no` values must be exactly 1 through *n* with no gaps and no
    repeats, every `pct_of_settlement` must be strictly greater than 0, and the
    `pct_of_settlement` values must sum to exactly 100.0."

    Design: Corner/validations/malformed_installment_plans_are_rejected_422
    """
    ctx = _a_reference_book()

    validate_error(
        _a_plan_probe(api, ctx, "GC-P10-C", NUMBERED_WITH_A_GAP),
        ApiErrorId.ERR_INVALID_INSTALLMENT_PLAN.value,
        422,
    )


def test_numbering_that_repeats_a_value_is_refused(api):
    """Two rows claiming to be the first installment would leave the residual with nowhere
    unambiguous to land.

    PRD: "The `installment_no` values must be exactly 1 through *n* with no gaps and no
    repeats, every `pct_of_settlement` must be strictly greater than 0, and the
    `pct_of_settlement` values must sum to exactly 100.0."

    Design: Corner/validations/malformed_installment_plans_are_rejected_422
    """
    ctx = _a_reference_book()

    validate_error(
        _a_plan_probe(api, ctx, "GC-P10-D", NUMBERED_TWICE),
        ApiErrorId.ERR_INVALID_INSTALLMENT_PLAN.value,
        422,
    )


def test_a_share_of_zero_is_refused_even_though_the_sum_is_right(api):
    """The shares are strictly positive, so a placeholder row of nothing is inadmissible even
    when the total still reaches 100.0.

    PRD: "The `installment_no` values must be exactly 1 through *n* with no gaps and no
    repeats, every `pct_of_settlement` must be strictly greater than 0, and the
    `pct_of_settlement` values must sum to exactly 100.0."

    Design: Corner/validations/malformed_installment_plans_are_rejected_422
    """
    ctx = _a_reference_book()
    assert sum(row["pct_of_settlement"] for row in A_ZERO_SHARE) == 100.0

    validate_error(
        _a_plan_probe(api, ctx, "GC-P10-E", A_ZERO_SHARE),
        ApiErrorId.ERR_INVALID_INSTALLMENT_PLAN.value,
        422,
    )


def test_a_tenth_of_a_percent_short_of_the_whole_is_refused(api):
    """No tolerance band is granted around 100.0, which is what keeps the settlement's
    money-conservation provable.

    PRD: "A plan with zero or more than six elements, gapped or repeated numbering, a
    non-positive percentage, or percentages that miss 100.0 is refused with
    `ERR_INVALID_INSTALLMENT_PLAN` and HTTP 422."

    Design: Corner/validations/malformed_installment_plans_are_rejected_422
    """
    ctx = _a_reference_book()

    validate_error(
        _a_plan_probe(api, ctx, "GC-P10-F", ONE_TENTH_SHORT),
        ApiErrorId.ERR_INVALID_INSTALLMENT_PLAN.value,
        422,
    )


def test_an_awkward_split_that_lands_exactly_on_the_whole_is_accepted(api):
    """33.4 plus 33.3 plus 33.3 is exactly 100.0, so the rule tests the total and not the
    tidiness of the shares — and the elements are copied through verbatim.

    PRD: "one installment row is created for each element of `installment_plan`, copying
    `installment_no`, `pct_of_settlement`, `due_offset_days` and `lien_protected` verbatim,
    each starting in status `PENDING_SETTLEMENT` with `planned_amount_cents` 0 and
    `paid_amount_cents` 0."

    Design: Corner/validations/malformed_installment_plans_are_rejected_422
    """
    ctx = _a_reference_book()

    accepted = validate_success(
        _a_plan_probe(api, ctx, "GC-P10-OK", AWKWARD_BUT_EXACT), 201
    )
    assert accepted["contract_code"] == "GC-P10-OK"
    assert accepted["lifecycle_status"] == "DRAFT"


def test_only_the_one_valid_plan_left_a_contract_behind(api):
    """Six malformed schedules and one exact one: the ledger of agreements holds a single row.

    PRD: "A plan with zero or more than six elements, gapped or repeated numbering, a
    non-positive percentage, or percentages that miss 100.0 is refused with
    `ERR_INVALID_INSTALLMENT_PLAN` and HTTP 422."

    Design: Corner/validations/malformed_installment_plans_are_rejected_422
    """
    ctx = _a_reference_book()
    for code, plan in (
        ("GC-P10-A", []),
        ("GC-P10-B", SEVEN_ELEMENTS),
        ("GC-P10-C", NUMBERED_WITH_A_GAP),
        ("GC-P10-D", NUMBERED_TWICE),
        ("GC-P10-E", A_ZERO_SHARE),
        ("GC-P10-F", ONE_TENTH_SHORT),
    ):
        _a_plan_probe(api, ctx, code, plan)
    _a_plan_probe(api, ctx, "GC-P10-OK", AWKWARD_BUT_EXACT)

    _, meta = validate_paginated(api.list_grape_contracts(MANAGER))
    assert meta["total_count"] == 1
