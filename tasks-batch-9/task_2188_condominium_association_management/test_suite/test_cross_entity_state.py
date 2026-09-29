"""Transitions gated by state that lives on a *different* row.

Filing suit reads the approval dimension of a special assessment that names this
claim, and the dependency runs backwards afterwards; starting work reads the
serviceability of the element the order names.  Both gates are probed with
near-miss neighbours that satisfy every other condition.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_instant_equals,
    read_claim,
    read_contract,
    read_element,
    read_special_assessment,
    read_work_order,
)
from test_helpers.fixtures import (
    add_contract,
    add_element,
    add_work_order,
    adjust_claim,
    award_and_activate_contract,
    approve_special_assessment,
    build_board,
    build_two_owner_board,
    convene,
    create_association,
    notice_meeting,
    open_special_assessment,
    patch_association,
    report_claim,
    schedule_meeting,
    set_clock,
)
from test_helpers.test_users import ADJUSTER_HEADERS, ATTORNEY_HEADERS, MANAGER_HEADERS


# ======================================================================
# (InsuranceClaim, SpecialAssessment): suit needs an APPROVED funder
# ======================================================================
def _bayline(api: ApiClient):
    """A tendered defect claim, plus a second defect claim to host a decoy funder.

    The tendered claim has already absorbed its deductible, so its adjustment
    dimension is settled and only the funding gate can stand between it and
    ``IN_LITIGATION``.
    """
    ctx = create_association(api, legal_name="Bayline Condominium Association")
    patch_association(ctx, operating_cash_cents=5_000_000)
    build_two_owner_board(ctx)
    add_element(
        ctx,
        "garage",
        name="Parking Garage Deck",
        element_class="GARAGE",
        replacement_cost_cents=9_000_000,
        useful_life_years=30,
        effective_age_years=10,
    )
    claim1 = report_claim(
        ctx,
        "A",
        "garage",
        loss_type="CONSTRUCTION_DEFECT",
        loss_at="2026-06-15T00:00:00Z",
        gross_damage_cents=4_800_000,
        within_unit_boundary_cents=400_000,
        affected_unit_ids=[ctx.units["A"]],
    )
    adjust_claim(ctx, claim1["id"], "ASSOCIATION")
    tendered = get_success_data(
        ctx.api.set_litigation_stage(claim1["id"], {"stage": "TENDERED"}, ATTORNEY_HEADERS)
    )
    claim2 = report_claim(
        ctx,
        "B",
        "garage",
        loss_type="CONSTRUCTION_DEFECT",
        loss_at="2026-06-20T00:00:00Z",
        gross_damage_cents=100_000,
        within_unit_boundary_cents=0,
        affected_unit_ids=[ctx.units["B"]],
    )
    # A ballot may only be opened on an assessment naming a claim whose
    # litigation_status is TENDERED or IN_LITIGATION (PRD 3.4), so the decoy
    # matter has to be tendered too.  DENY is the adjustment branch that moves
    # no association cash, keeping claim1's absorbed deductible observable.
    adjust_claim(ctx, claim2["id"], "DENY")
    claim2 = get_success_data(
        ctx.api.set_litigation_stage(claim2["id"], {"stage": "TENDERED"}, ATTORNEY_HEADERS)
    )
    return ctx, tendered, claim2


def test_tendered_claim_baseline_has_settled_its_adjustment_dimension(
    api: ApiClient,
) -> None:
    """The deductible is already absorbed, so nothing but funding is outstanding.

    PRD 3.7: "`ASSOCIATION` moves the claim to `ADJUSTED_ASSOCIATION` and requires
    `common_element_damage_cents` to be greater than 0. It sets
    `association_absorbed_cents` to the lesser of
    `master_policy_deductible_cents` and `association_deductible_cap_cents`, sets
    `owner_chargeback_cents` to 0, leaves `deductible_allocation` empty, reduces
    the association's `operating_cash_cents` by `association_absorbed_cents` with
    `Association.version` advancing by 1, and — when `element_id` is set and that
    element's `status` is `SERVICEABLE` — drives the element to `IMPAIRED` with
    `CommonElement.version` advancing by 1."

    Design: Difficulty/cross_entity_state_dependency/claim_in_litigation_requires_approved_funding_assessment_on_that_same_claim
    """
    ctx, tendered, _ = _bayline(api)

    assert tendered["adjustment_status"] == "ADJUSTED_ASSOCIATION"
    assert tendered["litigation_status"] == "TENDERED"
    assert tendered["disclosure_required"] is True
    assert tendered["association_absorbed_cents"] == 1_000_000
    association = ctx.association()
    assert association["operating_cash_cents"] == 4_000_000
    assert association["reserve_designated_cents"] == 0


def test_a_balloting_funder_does_not_authorize_filing_suit(api: ApiClient) -> None:
    """An open ballot is not an approval, so the suit is refused.

    PRD 3.7: "Moving `TENDERED → IN_LITIGATION` requires `litigation_status` to be
    `TENDERED` and requires that some special assessment exist whose
    `funding_claim_id` is this claim and whose `approval_status` is `APPROVED` —
    suit may not be filed until the owners have funded it — failing which the
    response is `ERR_LITIGATION_FUNDING_MISSING`; the only effect is that
    `InsuranceClaim.version` advances by 1."

    Design: Difficulty/cross_entity_state_dependency/claim_in_litigation_requires_approved_funding_assessment_on_that_same_claim
    """
    ctx, tendered, _ = _bayline(api)
    sa1 = open_special_assessment(
        ctx,
        total_amount_cents=2_000_000,
        installment_count=4,
        purpose="Defect litigation reserve (claim1)",
        funding_claim_id=tendered["id"],
    )
    assert sa1["approval_status"] == "BALLOTING"

    validate_error(
        api.set_litigation_stage(
            tendered["id"], {"stage": "IN_LITIGATION"}, ATTORNEY_HEADERS
        ),
        "ERR_LITIGATION_FUNDING_MISSING",
        expected_status=409,
    )

    reread = read_claim(api, tendered["id"], ADJUSTER_HEADERS)
    assert reread["litigation_status"] == "TENDERED"
    assert reread["disclosure_required"] is True


def test_an_approved_funder_on_a_different_claim_does_not_authorize_suit(
    api: ApiClient,
) -> None:
    """The funder must name *this* claim; a sibling defect matter will not do.

    PRD 3.7: "Moving `TENDERED → IN_LITIGATION` requires `litigation_status` to be
    `TENDERED` and requires that some special assessment exist whose
    `funding_claim_id` is this claim and whose `approval_status` is `APPROVED` —
    suit may not be filed until the owners have funded it — failing which the
    response is `ERR_LITIGATION_FUNDING_MISSING`; the only effect is that
    `InsuranceClaim.version` advances by 1."

    Design: Difficulty/cross_entity_state_dependency/claim_in_litigation_requires_approved_funding_assessment_on_that_same_claim
    """
    ctx, tendered, claim2 = _bayline(api)

    decoy = approve_special_assessment(
        ctx,
        total_amount_cents=500_000,
        installment_count=2,
        purpose="Defect litigation reserve (claim2)",
        funding_claim_id=claim2["id"],
    )
    assert decoy["approval_status"] == "APPROVED"
    assert ctx.association()["reserve_designated_cents"] == 500_000

    validate_error(
        api.set_litigation_stage(
            tendered["id"], {"stage": "IN_LITIGATION"}, ATTORNEY_HEADERS
        ),
        "ERR_LITIGATION_FUNDING_MISSING",
    )


def test_a_failed_funder_on_the_right_claim_does_not_authorize_suit(
    api: ApiClient,
) -> None:
    """A tallied but failed ballot on this very claim is still not an approval.

    PRD 3.4: "With the default two-thirds-plus threshold of 6667 basis points, a
    yes share of exactly 6667 approves and 6666 fails."

    A single YES from the 6000 basis point unit falls short, so the funder lands
    in `FAILED` and the guard -- which reads `approval_status` -- still refuses.

    Design: Difficulty/cross_entity_state_dependency/claim_in_litigation_requires_approved_funding_assessment_on_that_same_claim
    """
    ctx, tendered, _ = _bayline(api)

    failed = approve_special_assessment(
        ctx,
        total_amount_cents=2_000_000,
        installment_count=4,
        purpose="Defect litigation reserve (claim1)",
        funding_claim_id=tendered["id"],
        ballots=(("oa", "A", "YES"),),
    )
    assert failed["approval_status"] == "FAILED"
    assert failed["eligible_weight_bp"] == 10_000
    assert failed["yes_weight_bp"] == 6_000
    assert ctx.association()["reserve_designated_cents"] == 0

    validate_error(
        api.set_litigation_stage(
            tendered["id"], {"stage": "IN_LITIGATION"}, ATTORNEY_HEADERS
        ),
        "ERR_LITIGATION_FUNDING_MISSING",
    )


def test_an_approved_funder_on_this_claim_authorizes_filing_suit(
    api: ApiClient,
) -> None:
    """With the owners' money voted, the litigation dimension advances alone.

    PRD 3.7: "The `litigation_status` dimension runs over `NONE`, `TENDERED`,
    `IN_LITIGATION`, and `RESOLVED`, starting at `NONE`, and evolves entirely
    independently — a claim can be settled for adjustment purposes while its suit
    is still tendered, and a claim can be in litigation while its adjustment is
    denied."

    Design: Difficulty/cross_entity_state_dependency/claim_in_litigation_requires_approved_funding_assessment_on_that_same_claim
    """
    ctx, tendered, _ = _bayline(api)
    funder = approve_special_assessment(
        ctx,
        total_amount_cents=2_000_000,
        installment_count=4,
        purpose="Defect litigation reserve (claim1)",
        funding_claim_id=tendered["id"],
    )
    assert funder["approval_status"] == "APPROVED"

    in_suit = validate_success(
        api.set_litigation_stage(
            tendered["id"], {"stage": "IN_LITIGATION"}, ATTORNEY_HEADERS
        )
    )

    assert in_suit["litigation_status"] == "IN_LITIGATION"
    assert in_suit["adjustment_status"] == "ADJUSTED_ASSOCIATION"
    assert in_suit["disclosure_required"] is True
    assert ctx.association()["reserve_designated_cents"] == 2_000_000


def test_a_live_suit_blocks_rescission_of_its_own_funder_only(
    api: ApiClient,
) -> None:
    """The dependency runs backwards: funded litigation cannot be defunded.

    PRD 3.4: "It is blocked when `funding_claim_id` is set and that claim's
    `litigation_status` is `IN_LITIGATION` — a live suit cannot be defunded — in
    which case the response is `ERR_LITIGATION_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/claim_in_litigation_requires_approved_funding_assessment_on_that_same_claim
    """
    ctx, tendered, claim2 = _bayline(api)
    funder = approve_special_assessment(
        ctx,
        total_amount_cents=2_000_000,
        installment_count=4,
        purpose="Defect litigation reserve (claim1)",
        funding_claim_id=tendered["id"],
    )
    decoy = approve_special_assessment(
        ctx,
        total_amount_cents=500_000,
        installment_count=2,
        purpose="Defect litigation reserve (claim2)",
        funding_claim_id=claim2["id"],
    )
    get_success_data(
        api.set_litigation_stage(
            tendered["id"], {"stage": "IN_LITIGATION"}, ATTORNEY_HEADERS
        )
    )
    assert ctx.association()["reserve_designated_cents"] == 2_500_000

    validate_error(
        api.rescind_special_assessment(funder["id"], ctx.director("d1")),
        "ERR_LITIGATION_ACTIVE",
        expected_status=409,
    )
    assert (
        read_special_assessment(api, funder["id"], MANAGER_HEADERS)["approval_status"]
        == "APPROVED"
    )

    released = validate_success(
        api.rescind_special_assessment(decoy["id"], ctx.director("d1"))
    )
    assert released["approval_status"] == "RESCINDED"
    assert released["funding_status"] == "REFUNDED"
    assert ctx.association()["reserve_designated_cents"] == 2_000_000


def test_resolving_the_suit_unblocks_the_funder_rescission(api: ApiClient) -> None:
    """Once the matter is resolved the designation can be released again.

    PRD 3.7: "Moving `IN_LITIGATION → RESOLVED` requires `litigation_status` to be
    `IN_LITIGATION`, sets `disclosure_required` back to false so future
    certificates stop disclosing the matter, and advances `InsuranceClaim.version`
    by 1."

    Design: Difficulty/cross_entity_state_dependency/claim_in_litigation_requires_approved_funding_assessment_on_that_same_claim
    """
    ctx, tendered, _ = _bayline(api)
    funder = approve_special_assessment(
        ctx,
        total_amount_cents=2_000_000,
        installment_count=4,
        purpose="Defect litigation reserve (claim1)",
        funding_claim_id=tendered["id"],
    )
    get_success_data(
        api.set_litigation_stage(
            tendered["id"], {"stage": "IN_LITIGATION"}, ATTORNEY_HEADERS
        )
    )

    resolved = validate_success(
        api.set_litigation_stage(tendered["id"], {"stage": "RESOLVED"}, ATTORNEY_HEADERS)
    )
    assert resolved["litigation_status"] == "RESOLVED"
    assert resolved["disclosure_required"] is False

    rescinded = validate_success(
        api.rescind_special_assessment(funder["id"], ctx.director("d1"))
    )
    assert rescinded["approval_status"] == "RESCINDED"
    assert ctx.association()["reserve_designated_cents"] == 0


# ======================================================================
# (MaintenanceWorkOrder, CommonElement): only DECOMMISSIONED blocks a start
# ======================================================================
def _rowan_mill(api: ApiClient):
    """A scheduled order at exactly its window start, on a decommissioned element.

    A second contract is left in `DRAFT` on the same element so the identical
    element state can be shown blocking a different endpoint.
    """
    ctx = create_association(api, legal_name="Rowan Mill Condominium Association")
    patch_association(ctx, operating_cash_cents=2_000_000)
    build_board(ctx)
    add_element(
        ctx,
        "roof",
        name="Main Roof Membrane",
        element_class="ROOF",
        replacement_cost_cents=9_000_000,
        useful_life_years=30,
        effective_age_years=10,
    )
    add_contract(
        ctx,
        "ct1",
        "roof",
        vendor_name="Meridian Roofing LLC",
        contract_cap_cents=5_000_000,
        insurance_cert_expires_at="2027-06-01T00:00:00Z",
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2027-06-01T00:00:00Z",
    )
    schedule_meeting(
        ctx,
        "mtg_ca",
        ["CONTRACT_AWARD"],
        "2026-09-10T18:00:00Z",
        "2026-09-10T21:00:00Z",
    )
    notice_meeting(ctx, "mtg_ca")
    set_clock(api, "2026-09-10T18:00:00Z")
    convene(ctx, "mtg_ca", ("d1", "d2", "tr"))
    award_and_activate_contract(ctx, "ct1", "mtg_ca")
    order = add_work_order(
        ctx,
        "ct1",
        "roof",
        scope="Membrane seam repair",
        window_start="2026-10-05T08:00:00Z",
        window_end="2026-10-07T18:00:00Z",
        estimated_cost_cents=1_200_000,
    )
    add_contract(
        ctx,
        "ct2",
        "roof",
        vendor_name="Second Roofing Co",
        contract_cap_cents=800_000,
        insurance_cert_expires_at="2027-06-01T00:00:00Z",
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2027-06-01T00:00:00Z",
    )
    set_clock(api, "2026-10-05T08:00:00Z")
    get_success_data(
        ctx.api.update_common_element(
            ctx.elements["roof"], {"status": "DECOMMISSIONED"}, MANAGER_HEADERS
        )
    )
    return ctx, order


def test_decommissioned_element_baseline_leaves_everything_else_ready(
    api: ApiClient,
) -> None:
    """Only the element's serviceability is wrong; every other gate is satisfied.

    PRD 3.6: "Serviceability is tracked in `status`, which runs through
    `SERVICEABLE`, `IMPAIRED`, `OUT_OF_SERVICE`, and `DECOMMISSIONED` and starts
    at `SERVICEABLE`."

    Design: Difficulty/cross_entity_state_dependency/work_order_start_gated_by_common_element_status_decommissioned_only
    """
    ctx, order = _rowan_mill(api)

    element = read_element(api, ctx.elements["roof"], MANAGER_HEADERS)
    assert element["status"] == "DECOMMISSIONED"
    assert element["version"] == 2
    contract = read_contract(api, ctx.contracts["ct1"], MANAGER_HEADERS)
    assert contract["status"] == "ACTIVE"
    assert contract["pinned_element_version"] == 1
    assert contract["committed_cents"] == 1_200_000
    scheduled = read_work_order(api, order["id"], MANAGER_HEADERS)
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["encumbered_cents"] == 1_200_000
    assert_instant_equals(scheduled["window_start"], "2026-10-05T08:00:00Z")


def test_a_decommissioned_element_blocks_the_start_of_its_work_order(
    api: ApiClient,
) -> None:
    """The blocking state lives on the element, not on the order or its contract.

    PRD 3.6: "From `SCHEDULED` the requirements are that the contract's `status`
    be `ACTIVE`, that the contract's `insurance_cert_expires_at` be strictly after
    the order's `window_end` (a certificate that lapses mid-outage is refused with
    `ERR_VENDOR_INSURANCE_LAPSED`), that the element's `status` not be
    `DECOMMISSIONED`, and that the logical clock have reached `window_start` — an
    early start is refused with `ERR_WINDOW_NOT_STARTED`."

    The clock sits exactly on `window_start`, which satisfies the inclusive lower
    bound, and the certificate outlives the window, so neither temporal gate nor
    the insurance gate can be the refusal.

    Design: Difficulty/cross_entity_state_dependency/work_order_start_gated_by_common_element_status_decommissioned_only
    """
    ctx, order = _rowan_mill(api)

    validate_error(
        ctx.api.start_work_order(order["id"], MANAGER_HEADERS),
        "ERR_ELEMENT_NOT_SERVICEABLE",
        expected_status=409,
    )

    reread = read_work_order(api, order["id"], MANAGER_HEADERS)
    assert reread["status"] == "SCHEDULED"
    assert reread["encumbered_cents"] == 1_200_000
    assert read_element(api, ctx.elements["roof"], MANAGER_HEADERS)["version"] == 2


def test_the_same_element_state_blocks_an_unrelated_contract_submission(
    api: ApiClient,
) -> None:
    """One element state reaches two endpoints on two different entities.

    PRD 3.6: "Three term conditions apply: `effective_from` must be strictly
    before `effective_to`, and `insurance_cert_expires_at` must be at or after
    `effective_to` so that the certificate covers the whole term — either failure
    yields `ERR_CONTRACT_TERM_INVALID` — and the covered element's `status` must
    not be `DECOMMISSIONED`, failing which the response is
    `ERR_ELEMENT_NOT_SERVICEABLE`."

    Design: Difficulty/cross_entity_state_dependency/work_order_start_gated_by_common_element_status_decommissioned_only
    """
    ctx, _ = _rowan_mill(api)

    validate_error(
        ctx.api.submit_contract(ctx.contracts["ct2"], MANAGER_HEADERS),
        "ERR_ELEMENT_NOT_SERVICEABLE",
        expected_status=409,
    )
    assert (
        read_contract(api, ctx.contracts["ct2"], MANAGER_HEADERS)["status"] == "DRAFT"
    )


def test_an_impaired_element_does_not_block_the_start(api: ApiClient) -> None:
    """The gate names exactly one forbidden value, so IMPAIRED work goes ahead.

    PRD 3.6: "Both legs set `hold_reason` to `NONE` and drive the element's
    `status` to `OUT_OF_SERVICE` when the element's `is_life_safety` is true and to
    `IMPAIRED` otherwise, advancing `CommonElement.version` by 1, and both advance
    `MaintenanceWorkOrder.version` by 1."

    A `ROOF` is not a life-safety component, so the started order leaves the
    element `IMPAIRED` and its version at 4 -- 2 from the two revisions, one more
    for the start.

    Design: Difficulty/cross_entity_state_dependency/work_order_start_gated_by_common_element_status_decommissioned_only
    """
    ctx, order = _rowan_mill(api)
    impaired = get_success_data(
        ctx.api.update_common_element(
            ctx.elements["roof"], {"status": "IMPAIRED"}, MANAGER_HEADERS
        )
    )
    assert impaired["version"] == 3
    assert impaired["is_life_safety"] is False

    started = validate_success(ctx.api.start_work_order(order["id"], MANAGER_HEADERS))

    assert started["status"] == "IN_PROGRESS"
    assert started["hold_reason"] == "NONE"
    element = read_element(api, ctx.elements["roof"], MANAGER_HEADERS)
    assert element["status"] == "IMPAIRED"
    assert element["version"] == 4


def test_a_stale_pinned_element_version_does_not_reach_the_start_endpoint(
    api: ApiClient,
) -> None:
    """The award pin guards activation and reinstatement, not work starting.

    PRD 2.9: "20. The board's award is still valid because
    `CommonElement.version` equals `pinned_element_version` -- otherwise
    `ERR_ELEMENT_SPEC_CHANGED`, on contract activation and reinstatement."

    Design: Difficulty/cross_entity_state_dependency/work_order_start_gated_by_common_element_status_decommissioned_only
    """
    ctx, order = _rowan_mill(api)
    get_success_data(
        ctx.api.update_common_element(
            ctx.elements["roof"], {"status": "IMPAIRED"}, MANAGER_HEADERS
        )
    )
    contract = read_contract(api, ctx.contracts["ct1"], MANAGER_HEADERS)
    assert contract["pinned_element_version"] == 1
    assert read_element(api, ctx.elements["roof"], MANAGER_HEADERS)["version"] == 3

    started = validate_success(ctx.api.start_work_order(order["id"], MANAGER_HEADERS))

    assert started["status"] == "IN_PROGRESS"


def test_a_serviceable_element_is_not_enough_when_the_contract_is_suspended(
    api: ApiClient,
) -> None:
    """The element gate and the contract gate are independent requirements.

    PRD 3.6: "From `ON_HOLD` the requirements are that the contract's `status` be
    `ACTIVE`, so an order held for `CONTRACT_SUSPENDED` cannot be resumed while
    its contract remains suspended, and that the element's `status` not be
    `DECOMMISSIONED`."

    Design: Difficulty/cross_entity_state_dependency/work_order_start_gated_by_common_element_status_decommissioned_only
    """
    ctx, order = _rowan_mill(api)
    get_success_data(
        ctx.api.update_common_element(
            ctx.elements["roof"], {"status": "IMPAIRED"}, MANAGER_HEADERS
        )
    )
    get_success_data(ctx.api.start_work_order(order["id"], MANAGER_HEADERS))
    get_success_data(
        ctx.api.suspend_contract(
            ctx.contracts["ct1"], {"suspension_reason": "PERFORMANCE"}, MANAGER_HEADERS
        )
    )
    held = read_work_order(api, order["id"], MANAGER_HEADERS)
    assert held["status"] == "ON_HOLD"
    assert held["hold_reason"] == "CONTRACT_SUSPENDED"

    validate_error_is_one_of(
        ctx.api.start_work_order(order["id"], MANAGER_HEADERS),
        ["ERR_INVALID_CONTRACT_STATE", "ERR_INVALID_WORK_ORDER_STATE"],
    )

    reread = read_work_order(api, order["id"], MANAGER_HEADERS)
    assert reread["status"] == "ON_HOLD"
    assert reread["hold_reason"] == "CONTRACT_SUSPENDED"
    assert reread["encumbered_cents"] == 1_200_000
