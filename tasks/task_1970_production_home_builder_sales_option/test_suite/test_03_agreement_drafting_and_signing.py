"""Purchase-agreement drafting (OCC, in-community references, earnest floor) and
the sign transition's side-effect bundle (PRD §2.9, §2.10, §3.3)."""
from test_helpers import (
    ApiErrorId,
    CANONICAL_ESTIMATED_CLOSE_PADDED,
    CANONICAL_ESTIMATED_CLOSE_STANDARD,
    CANONICAL_PROVISIONAL_TOTAL_CENTS,
    CANONICAL_RELEASE_PRICE_CENTS,
    TEST_USERS,
    api_client,
    assert_construction_milestone,
    assert_instant_equals,
    assert_purchase_agreement,
    create_agreement_payload,
    create_community,
    create_plan,
    make_buyer_headers,
    register_buyer,
    reserve_lot,
    setup_draft_agreement,
    setup_released_scenario,
    setup_reserved_scenario,
    setup_signed_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECTOR = TEST_USERS["sales_director_headers"]
AGENT = TEST_USERS["sales_agent_headers"]
MANAGER = TEST_USERS["construction_manager_headers"]


def test_agreement_create_on_released_lot_rejected():
    """PRD §3.3: "The agreement must be in `DRAFT` (else
    `ERR_AGREEMENT_INVALID_STATE`), the acting buyer must equal the agreement's
    `buyer_id` (else `ERR_NOT_RESOURCE_OWNER`), the community must be `SELLING`
    (else `ERR_COMMUNITY_NOT_SELLING`), and the referenced lot must be in
    `RESERVED` with its `reserved_buyer_id` equal to the agreement's
    `buyer_id` (else `ERR_LOT_NOT_RESERVED_BY_BUYER`)."
    PRD §4: "Create a `DRAFT` purchase agreement against a reserved lot;
    OCC-guarded on the lot's version" — the reserved-lot precondition guards
    the drafting endpoint.

    Design: Difficulty/cross_entity_state_dependency/agreement_create_requires_lot_reserved_by_buyer
    """
    bundle = setup_released_scenario()
    lot = bundle["lot"]
    buyer = bundle["buyer"]

    resp = api_client.create_agreement(
        create_agreement_payload(
            buyer_id=buyer["id"], lot_id=lot["id"],
            plan_id=bundle["plan"]["id"],
            expected_lot_version=lot["version"],
        ),
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_RESERVED_BY_BUYER)

    after = validate_success(api_client.get_lot(lot["id"], AGENT), 200)
    assert after["version"] == lot["version"], (
        "a rejected create must not advance the lot's version"
    )


def test_agreement_create_when_lot_reserved_by_other_buyer_rejected():
    """PRD §3.3: "The agreement must be in `DRAFT` (else
    `ERR_AGREEMENT_INVALID_STATE`), the acting buyer must equal the agreement's
    `buyer_id` (else `ERR_NOT_RESOURCE_OWNER`), the community must be `SELLING`
    (else `ERR_COMMUNITY_NOT_SELLING`), and the referenced lot must be in
    `RESERVED` with its `reserved_buyer_id` equal to the agreement's
    `buyer_id` (else `ERR_LOT_NOT_RESERVED_BY_BUYER`)."
    PRD §4: "Create a `DRAFT` purchase agreement against a reserved lot;
    OCC-guarded on the lot's version" — the reserved-lot precondition guards
    the drafting endpoint.

    Design: Difficulty/cross_entity_state_dependency/agreement_create_requires_lot_reserved_by_buyer
    """
    bundle = setup_reserved_scenario()
    lot = bundle["lot"]
    ben = register_buyer(full_name="Ben Buyer", email="ben@example.com")

    resp = api_client.create_agreement(
        create_agreement_payload(
            buyer_id=ben["id"], lot_id=lot["id"],
            plan_id=bundle["plan"]["id"],
            expected_lot_version=bundle["lot_version"],
        ),
        AGENT,
    )
    # reserved_buyer_id (Bea) != agreement buyer (Ben)
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_RESERVED_BY_BUYER)


def test_agreement_create_plan_from_other_community_rejected():
    """PRD §3.3: "The deal must also stay inside one community: the referenced
    plan must belong to the same community as the lot (else
    `ERR_PLAN_NOT_IN_COMMUNITY`, HTTP 422), and the `elevation_name` must
    appear among the plan's `elevations` entries (else
    `ERR_ELEVATION_NOT_AVAILABLE`, HTTP 422)."

    Design: Corner/validations/agreement_create_plan_from_other_community_rejected
    """
    bundle = setup_reserved_scenario()
    other = create_community(name="Aspen Grove")
    other_plan = create_plan(
        other["id"], plan_name="Aspen", base_price_cents=30_000_000,
        elevations=[{"name": "A", "price_cents": 0}],
    )

    resp = api_client.create_agreement(
        create_agreement_payload(
            buyer_id=bundle["buyer"]["id"], lot_id=bundle["lot"]["id"],
            plan_id=other_plan["id"], elevation_name="A",
            expected_lot_version=bundle["lot_version"],
        ),
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_IN_COMMUNITY, 422)


def test_agreement_create_unknown_elevation_rejected():
    """PRD §3.3: "The deal must also stay inside one community: the referenced
    plan must belong to the same community as the lot (else
    `ERR_PLAN_NOT_IN_COMMUNITY`, HTTP 422), and the `elevation_name` must
    appear among the plan's `elevations` entries (else
    `ERR_ELEVATION_NOT_AVAILABLE`, HTTP 422)."

    Design: Corner/validations/agreement_create_unknown_elevation_rejected
    """
    bundle = setup_reserved_scenario()
    resp = api_client.create_agreement(
        create_agreement_payload(
            buyer_id=bundle["buyer"]["id"], lot_id=bundle["lot"]["id"],
            plan_id=bundle["plan"]["id"], elevation_name="Z",
            expected_lot_version=bundle["lot_version"],
        ),
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_ELEVATION_NOT_AVAILABLE, 422)


def test_agreement_create_earnest_below_minimum_rejected():
    """PRD §3.3: "Earnest money must meet the trust minimum of $1,000 — a
    deposit below that floor is rejected with `ERR_EARNEST_BELOW_MINIMUM`
    (HTTP 402)."

    Design: Corner/validations/agreement_create_earnest_below_minimum_rejected
    """
    bundle = setup_reserved_scenario()
    resp = api_client.create_agreement(
        create_agreement_payload(
            buyer_id=bundle["buyer"]["id"], lot_id=bundle["lot"]["id"],
            plan_id=bundle["plan"]["id"],
            earnest_money_deposited_cents=50_000,
            expected_lot_version=bundle["lot_version"],
        ),
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_EARNEST_BELOW_MINIMUM, 402)


def test_occ_stale_lot_version_on_agreement_create():
    """PRD §2.9: "If the lot's current `version` has advanced past that value —
    for instance because another writer reserved the lot or released a
    reservation after the client priced the deal — the create is rejected with
    `ERR_STALE_LOT_VERSION` (HTTP 412), forcing a re-read before the contract
    is drafted."
    PRD §3.3: "Linking the agreement marks the lot: the lot's `version`
    increments by 1 at creation even though its status does not yet change."

    Design: Corner/complexity_layers/occ_stale_lot_version_on_agreement_create
    """
    bundle = setup_released_scenario()
    lot = bundle["lot"]
    buyer = bundle["buyer"]
    lot_v_release = lot["version"]
    reserved = reserve_lot(lot["id"], buyer["id"])
    assert reserved["version"] > lot_v_release, "reserve advanced the version"

    stale = api_client.create_agreement(
        create_agreement_payload(
            buyer_id=buyer["id"], lot_id=lot["id"],
            plan_id=bundle["plan"]["id"],
            expected_lot_version=lot_v_release,
        ),
        AGENT,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_LOT_VERSION, 412)

    _data, meta = validate_paginated(api_client.list_agreements(AGENT))
    assert meta["total_count"] == 0, "no agreement persisted from the stale create"

    fresh = api_client.create_agreement(
        create_agreement_payload(
            buyer_id=buyer["id"], lot_id=lot["id"],
            plan_id=bundle["plan"]["id"],
            expected_lot_version=reserved["version"],
        ),
        AGENT,
    )
    agreement = validate_success(fresh, 201)
    assert agreement["status"] == "DRAFT"

    after = validate_success(api_client.get_lot(lot["id"], AGENT), 200)
    assert after["version"] == reserved["version"] + 1, (
        "the successful create's linkage marker increments the lot version once"
    )


def test_sign_agreement_side_effects_snapshot_and_milestones():
    """PRD §3.3: "When signing succeeds, prices are snapshotted into
    `lot_price_snapshot_cents` (the lot's current `release_price_cents`),
    `plan_price_snapshot_cents` (the plan's `base_price_cents`), and
    `elevation_price_snapshot_cents` (the price of the chosen elevation
    entry)."
    PRD §3.3: "The `provisional_total_cents` is fixed at that moment as the sum
    of the three snapshots and never changes afterwards."
    PRD §3.3: "Contingency trackers are initialized:
    `financing_contingency_status` and `appraisal_contingency_status` start at
    `PENDING`, and `sale_of_home_contingency_status` starts at `PENDING` when
    `has_sale_of_home_contingency` is true or at `WAIVED` when it is false;
    each tracker later resolves to `CLEARED` or `WAIVED`."
    PRD §3.3: "Signing also builds the construction plan: five milestones are
    auto-created, one per build stage, numbered by `sequence_no` from 1 through
    5 in stage order, each with its planned duration from the stage calendar in
    `planned_duration_days`, each starting in `NOT_STARTED` status with
    `completed_at` and `buyer_notified_at` null."
    PRD §3.3: "Finally, the lot moves from `RESERVED` to `SOLD`, clearing
    `hold_expires_at` while retaining `reserved_buyer_id` as the purchaser
    record, and both the lot and the agreement increment their `version`."

    Design: Corner/endpoints/sign_agreement_side_effects_snapshot_and_milestones
    """
    bundle = setup_draft_agreement()
    agreement = bundle["agreement"]
    buyer = bundle["buyer"]
    assert agreement["current_stage"] == "NOT_STARTED", (
        "before sign the agreement has not entered construction tracking"
    )
    assert agreement["status"] == "DRAFT"
    assert agreement["options_total_cents"] == 0
    assert agreement["change_fees_total_cents"] == 0
    assert agreement["incentives_total_cents"] == 0
    assert agreement["warranty_status"] == "NONE"
    assert agreement["warranty_term_months"] == 0
    for nullable in ("final_total_cents", "refund_amount_cents",
                     "forfeited_amount_cents", "cancel_reason",
                     "warranty_enrolled_at"):
        assert agreement[nullable] is None, nullable

    signed = validate_success(
        api_client.sign_agreement(agreement["id"], make_buyer_headers(buyer["id"])),
        200,
    )
    assert_purchase_agreement(signed)
    assert signed["status"] == "PENDING_CONTINGENCIES"
    assert signed["current_stage"] == "PRE_CONSTRUCTION"
    assert signed["lot_price_snapshot_cents"] == CANONICAL_RELEASE_PRICE_CENTS
    assert signed["plan_price_snapshot_cents"] == 35_000_000
    assert signed["elevation_price_snapshot_cents"] == 250_000
    assert signed["provisional_total_cents"] == CANONICAL_PROVISIONAL_TOTAL_CENTS
    assert signed["financing_contingency_status"] == "PENDING"
    assert signed["appraisal_contingency_status"] == "PENDING"
    assert signed["sale_of_home_contingency_status"] == "WAIVED", (
        "has_sale_of_home_contingency false -> WAIVED at signing"
    )
    assert_instant_equals(
        signed["estimated_close_standard"], CANONICAL_ESTIMATED_CLOSE_STANDARD,
        "standard estimate",
    )
    assert_instant_equals(
        signed["estimated_close_padded"], CANONICAL_ESTIMATED_CLOSE_PADDED,
        "padded estimate",
    )
    assert signed["slippage_flag"] is False, (
        "padded 2027-01-06 is not later than outside 2027-03-01"
    )

    milestones, meta = validate_paginated(
        api_client.list_milestones(AGENT, params={"agreement_id": signed["id"]})
    )
    assert meta["total_count"] == 5
    expected_stages = ["PRE_CONSTRUCTION", "FOUNDATION", "FRAMING", "DRYWALL",
                       "FINAL_WALKTHROUGH"]
    expected_durations = [30, 21, 28, 35, 14]
    for idx, milestone in enumerate(milestones):
        assert_construction_milestone(milestone)
        assert milestone["sequence_no"] == idx + 1, "sequence_no 1..5 in stage order"
        assert milestone["stage"] == expected_stages[idx]
        assert milestone["planned_duration_days"] == expected_durations[idx]
        assert milestone["status"] == "NOT_STARTED"
        assert milestone["completed_at"] is None
        assert milestone["buyer_notified_at"] is None

    lot = validate_success(api_client.get_lot(bundle["lot"]["id"], AGENT), 200)
    assert lot["status"] == "SOLD"
    assert lot["hold_expires_at"] is None
    assert lot["reserved_buyer_id"] == buyer["id"], (
        "reserved_buyer_id retained as the purchaser record"
    )


def test_agreement_sign_twice_returns_invalid_state():
    """PRD §3.3: "The agreement must be in `DRAFT` (else
    `ERR_AGREEMENT_INVALID_STATE`), the acting buyer must equal the agreement's
    `buyer_id` (else `ERR_NOT_RESOURCE_OWNER`), the community must be `SELLING`
    (else `ERR_COMMUNITY_NOT_SELLING`), and the referenced lot must be in
    `RESERVED` with its `reserved_buyer_id` equal to the agreement's
    `buyer_id` (else `ERR_LOT_NOT_RESERVED_BY_BUYER`)."

    Design: Corner/state_machines/agreement_sign_twice_returns_invalid_state
    """
    bundle = setup_signed_agreement()
    buyer_headers = make_buyer_headers(bundle["buyer"]["id"])

    resp = api_client.sign_agreement(bundle["agreement"]["id"], buyer_headers)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_INVALID_STATE)

    after = validate_success(
        api_client.get_agreement(bundle["agreement"]["id"], AGENT), 200
    )
    assert after["status"] == "PENDING_CONTINGENCIES"


def test_buyer_cannot_sign_others_agreement():
    """PRD §3.3: "The agreement must be in `DRAFT` (else
    `ERR_AGREEMENT_INVALID_STATE`), the acting buyer must equal the agreement's
    `buyer_id` (else `ERR_NOT_RESOURCE_OWNER`), the community must be `SELLING`
    (else `ERR_COMMUNITY_NOT_SELLING`), and the referenced lot must be in
    `RESERVED` with its `reserved_buyer_id` equal to the agreement's
    `buyer_id` (else `ERR_LOT_NOT_RESERVED_BY_BUYER`)."
    PRD §2.1: "When `X-User-Role` is `Buyer`, `X-User-ID` is the `id` of the
    acting Buyer; ownership checks on any resource that references a Buyer — an
    agreement's `buyer_id`, a lot's `reserved_buyer_id`, or a reservation
    payload's `buyer_id` — compare that field to `X-User-ID`, and a mismatch is
    rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/buyer_cannot_sign_others_agreement
    """
    bundle = setup_draft_agreement()
    ben = register_buyer(full_name="Ben Buyer", email="ben@example.com")

    resp = api_client.sign_agreement(
        bundle["agreement"]["id"], make_buyer_headers(ben["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)

    after = validate_success(
        api_client.get_agreement(bundle["agreement"]["id"], AGENT), 200
    )
    assert after["status"] == "DRAFT"


def test_construction_manager_cannot_create_agreement():
    """PRD §2.1: "Even with valid headers, a caller whose role is not authorized
    for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: the create-agreement endpoint's authorized role is "SalesAgent".

    Design: Corner/rbac/construction_manager_cannot_create_agreement
    """
    bundle = setup_reserved_scenario()
    resp = api_client.create_agreement(
        create_agreement_payload(
            buyer_id=bundle["buyer"]["id"], lot_id=bundle["lot"]["id"],
            plan_id=bundle["plan"]["id"],
            expected_lot_version=bundle["lot_version"],
        ),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
