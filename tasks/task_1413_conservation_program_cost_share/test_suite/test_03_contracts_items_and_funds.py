"""Contract drafting, item referential checks, obligation rounding, and pool funds."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_item,
    assert_contract,
    assert_pool_invariants,
    build_contract,
    create_contract_for,
    get_contract,
    get_item,
    get_pool,
    make_applicant_headers,
    obligate,
    patch_practice_item_payload,
    register_applicant,
    run_ranking,
    close_program,
    setup_obligated_contract,
    setup_open_program,
    setup_screened_application,
    setup_selected_application,
    api_client,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_missing_resources_return_typed_not_found(api):
    """PRD §2.5: "The not-found family comprises `ERR_PROGRAM_NOT_FOUND`,
    `ERR_POOL_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`,
    `ERR_CONTRACT_NOT_FOUND`, `ERR_PRACTICE_ITEM_NOT_FOUND`,
    `ERR_PAYMENT_REQUEST_NOT_FOUND`, `ERR_ADVANCE_PAYMENT_NOT_FOUND`,
    `ERR_MODIFICATION_NOT_FOUND`, `ERR_SPOT_CHECK_NOT_FOUND`,
    `ERR_MAINTENANCE_OBLIGATION_NOT_FOUND`, and `ERR_RECOUPMENT_DEMAND_NOT_FOUND`,
    each carrying HTTP 404."

    Design: Corner/entities/missing_resources_return_typed_not_found
    """
    cases = [
        (api.get_contract(NON_EXISTENT_UUID, ADMIN), ApiErrorId.ERR_CONTRACT_NOT_FOUND),
        (api.get_pool(NON_EXISTENT_UUID, ADMIN), ApiErrorId.ERR_POOL_NOT_FOUND),
        (api.get_application(NON_EXISTENT_UUID, ADMIN), ApiErrorId.ERR_APPLICATION_NOT_FOUND),
        (
            api.get_recoupment_demand(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_RECOUPMENT_DEMAND_NOT_FOUND,
        ),
    ]
    for resp, error_id in cases:
        validate_error(resp, error_id)


def test_item_practice_and_quantity_referential_checks(api):
    """PRD §3.4: "the practice code must appear among the application's
    `planned_practices` — otherwise `ERR_PRACTICE_NOT_IN_APPLICATION`
    (HTTP 422) — and the planned quantity must not exceed the quantity planned
    for that code in the application — otherwise
    `ERR_QUANTITY_EXCEEDS_APPLICATION` (HTTP 422)."

    Design: Corner/validations/item_practice_and_quantity_referential_checks
    """
    ctx = setup_selected_application(
        rates=(
            ("FENCE", "FOOT", 300, 360, 10),
            ("COVER_CROP", "ACRE", 15000, 18000, 5),
        ),
        planned=(("FENCE", 1000),),
    )
    contract = create_contract_for(ctx["application"]["id"])

    wrong_code = api.add_practice_item(
        contract["id"],
        {
            "practice_code": "COVER_CROP",
            "planned_quantity": 5,
            "implementation_deadline": "2027-03-01T00:00:00Z",
        },
        TEST_USERS["planner_headers"],
    )
    validate_error(wrong_code, ApiErrorId.ERR_PRACTICE_NOT_IN_APPLICATION)

    over_qty = api.add_practice_item(
        contract["id"],
        {
            "practice_code": "FENCE",
            "planned_quantity": 1001,
            "implementation_deadline": "2027-03-01T00:00:00Z",
        },
        TEST_USERS["planner_headers"],
    )
    validate_error(over_qty, ApiErrorId.ERR_QUANTITY_EXCEEDS_APPLICATION)


def test_item_patch_stale_version_rejected(api):
    """PRD §2.10: "Editing a practice item's `planned_quantity` or
    `implementation_deadline` while its contract is still in drafting requires
    `expected_item_version` equal to the item's current `version`. An edit
    carrying an older version — meaning another edit has already landed,
    silently changing `scheduled_amount_cents` — is rejected with
    `ERR_STALE_ITEM_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_item_patch_stale_rejected
    """
    ctx = setup_selected_application()
    ctx = build_contract(ctx, ctx["application"]["id"], items=(("FENCE", 1000),))
    item = ctx["item"]
    observed_version = item["version"]

    first = validate_success(
        api.patch_practice_item(
            item["id"],
            patch_practice_item_payload(observed_version, planned_quantity=500),
            TEST_USERS["planner_headers"],
        ),
        200,
    )
    assert first["version"] == observed_version + 1
    assert first["scheduled_amount_cents"] == 150000, (
        "scheduled_amount_cents recomputed on patch: 500 x 300"
    )

    replay = api.patch_practice_item(
        item["id"],
        patch_practice_item_payload(observed_version, planned_quantity=400),
        TEST_USERS["planner_headers"],
    )
    validate_error(replay, ApiErrorId.ERR_STALE_ITEM_VERSION)


def test_per_item_rounding_sums_without_re_rounding(api):
    """PRD §3.4: "The per-item rounding happens inside each scheduled amount
    and the contract total is never re-rounded: the contract figure is a sum of
    rounded line values rather than the rounding of an unrounded sum, and the
    two can differ when a quantity-rate product lands on a fraction of a cent."

    Design: Difficulty/combinatorial_formula/obligated_amount_per_item_rounding_order
    """
    ctx = setup_selected_application(
        rates=(("COVER_CROP", "ACRE", 15001, 15001, 5),),
        planned=(("COVER_CROP", 5.0),),
    )
    ctx = build_contract(
        ctx, ctx["application"]["id"],
        items=(("COVER_CROP", 2.5), ("COVER_CROP", 2.5)),
    )
    item1, item2 = ctx["items"]
    # round_half_up(2.5 * 15001) = round_half_up(37502.5) = 37503 per item.
    assert item1["scheduled_amount_cents"] == 37503
    assert item2["scheduled_amount_cents"] == 37503

    contract = obligate(ctx["contract"]["id"])
    # Sum of per-item rounded values: 37503 + 37503 = 75006 (never 75005).
    assert contract["obligated_amount_cents"] == 75006, (
        f"contract total must be the sum of rounded line values, got {contract['obligated_amount_cents']}"
    )


def test_estimate_vs_obligation_one_cent_divergence(api):
    """PRD §3.3: "`estimated_obligation_cents` sums the planned practices, each
    priced as its quantity multiplied by the applicable rate — the schedule's
    `hu_rate_cents` when the applicant is historically underserved,
    `standard_rate_cents` otherwise — with each practice line rounded half-up
    to whole cents before the lines are summed, never the reverse." PRD §3.4:
    "The per-item rounding happens inside each scheduled amount and the
    contract total is never re-rounded: the contract figure is a sum of rounded
    line values rather than the rounding of an unrounded sum, and the two can
    differ when a quantity-rate product lands on a fraction of a cent."

    Design: Difficulty/combinatorial_formula/obligated_amount_per_item_rounding_order
    """
    ctx = setup_selected_application(
        rates=(("COVER_CROP", "ACRE", 15001, 15001, 5),),
        planned=(("COVER_CROP", 5.0),),
    )
    # Single estimate line: round_half_up(5.0 * 15001) = 75005.
    assert ctx["application"]["estimated_obligation_cents"] == 75005

    ctx = build_contract(
        ctx, ctx["application"]["id"],
        items=(("COVER_CROP", 2.5), ("COVER_CROP", 2.5)),
    )
    contract = obligate(ctx["contract"]["id"])
    assert contract["obligated_amount_cents"] == 75006
    assert contract["obligated_amount_cents"] != ctx["application"]["estimated_obligation_cents"], (
        "estimate (single line) and obligation (two lines) legitimately differ by 1 cent"
    )

    pool = get_pool(ctx["pool"]["id"])
    assert pool["obligated_cents"] == 75006, "pool reserves the contract figure"
    assert_pool_invariants(pool)


def _setup_two_contracts_leaving_10000(api):
    """Pool 400000; contract A obligates 300000, contract B obligates 90000."""
    ctx = setup_open_program(pools=(("GENERAL", 400000),))
    specs = [
        ("A One", "P-100", 1000, 30),
        ("B Two", "P-101", 300, 20),
    ]
    contracts = []
    for name, parcel, qty, points in specs:
        applicant = register_applicant(legal_name=name, parcel_ids=(parcel,))
        ctx = setup_screened_application(
            ctx, applicant=applicant, planned=(("FENCE", qty),),
            self_reported_answers={"SOIL_HEALTH": points},
            verified_answers={"SOIL_HEALTH": points},
        )
        contracts.append((ctx["application"]["id"], qty))
    close_program(ctx["program"]["id"])
    run_ranking(ctx["program"]["id"])
    obligated = []
    for app_id, qty in contracts:
        contract = create_contract_for(app_id)
        add_item(contract["id"], "FENCE", qty)
        obligated.append(obligate(contract["id"]))
    return ctx, obligated


def test_second_obligate_reports_state_error_not_fiscal(api):
    """PRD §3.4: "Obligation is the `ProgramAdmin`'s act of reserving funds,
    moving the contract from `DRAFT` to `OBLIGATED` — and a second obligation
    attempt likewise meets `ERR_CONTRACT_NOT_DRAFT`." PRD §2.6: "A request that
    fails both a state check and a fiscal check therefore reports the state
    error, and so on down the ladder; lower rungs are evaluated only when every
    higher rung has passed."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_second_obligate
    """
    ctx, obligated = _setup_two_contracts_leaving_10000(api)
    contract_a = obligated[0]

    resp = api.obligate_contract(contract_a["id"], ADMIN)
    error = validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_DRAFT)
    assert error["error_id"] != ApiErrorId.ERR_POOL_INSUFFICIENT_FUNDS
    assert error["error_id"] != "ERR_POOL_INSUFFICIENT_FUNDS"


def test_pool_residual_after_two_obligations_proves_fiscal_would_fail(api):
    """PRD §3.4: "its `obligated_amount_cents` must be no greater than the
    contract pool's `available_cents` (`ERR_POOL_INSUFFICIENT_FUNDS`,
    HTTP 402) — an obligation that exactly consumes the available balance
    succeeds." PRD §2.6: "A request that fails both a state check and a fiscal
    check therefore reports the state error, and so on down the ladder; lower
    rungs are evaluated only when every higher rung has passed."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_second_obligate
    """
    ctx, obligated = _setup_two_contracts_leaving_10000(api)
    pool = get_pool(ctx["pool"]["id"])
    # 400000 - 300000 - 90000 = 10000 remaining: the fiscal check WOULD fail
    # for a fresh 300000 obligation, which is what makes the dual failure real.
    assert pool["available_cents"] == 10000
    assert pool["obligated_cents"] == 390000
    assert_pool_invariants(pool)

    resp = api.obligate_contract(obligated[0]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_DRAFT)
    # The rejected transition leaves the pool untouched.
    pool_after = get_pool(ctx["pool"]["id"])
    assert pool_after["available_cents"] == 10000
    assert pool_after["obligated_cents"] == 390000


def test_obligate_exact_fit_succeeds(api):
    """PRD §3.4: "its `obligated_amount_cents` must be no greater than the
    contract pool's `available_cents` (`ERR_POOL_INSUFFICIENT_FUNDS`,
    HTTP 402) — an obligation that exactly consumes the available balance
    succeeds."

    Design: Difficulty/boundary_precision_check/pool_exact_fit_obligation_boundary
    """
    ctx = setup_obligated_contract(
        pools=(("HU_LIMITED_RESOURCE", 360000),),
        hu_category="LIMITED_RESOURCE",
        parcel_ids=("P-200",),
        legal_name="H U",
    )
    assert ctx["contract"]["status"] == "OBLIGATED"
    # HU snapshot: 1000 ft x 360 = 360000 exactly consumes the 360000 pool.
    assert ctx["contract"]["obligated_amount_cents"] == 360000
    pool = get_pool(ctx["pool"]["id"])
    assert pool["obligated_cents"] == 360000
    assert pool["available_cents"] == 0
    assert_pool_invariants(pool)


def test_add_practice_exact_fit_and_over_by_one_cent(api):
    """PRD §3.8: "For `ADD_PRACTICE`, the new item's scheduled amount must fit
    the pool's `available_cents` (`ERR_POOL_INSUFFICIENT_FUNDS`)." PRD §3.4:
    "its `obligated_amount_cents` must be no greater than the contract pool's
    `available_cents` (`ERR_POOL_INSUFFICIENT_FUNDS`, HTTP 402) — an obligation
    that exactly consumes the available balance succeeds."

    Design: Difficulty/boundary_precision_check/pool_exact_fit_obligation_boundary
    """
    # Standard (non-HU) applicant; pool 450000; FENCE 1000 obligates 300000.
    ctx = setup_open_program(
        state_code="NE",
        pools=(("GENERAL", 450000),),
        rates=(
            ("FENCE", "FOOT", 300, 360, 10),
            ("COVER_CROP", "ACRE", 15000, 18000, 5),
        ),
    )
    applicant = register_applicant(legal_name="B Two", parcel_ids=("P-201",))
    ctx = setup_screened_application(
        ctx, applicant=applicant, parcel_id="P-201", planned=(("FENCE", 1000),),
        self_reported_answers={"SOIL_HEALTH": 30},
        verified_answers={"SOIL_HEALTH": 30},
    )
    close_program(ctx["program"]["id"])
    run_ranking(ctx["program"]["id"])
    ctx = build_contract(ctx, ctx["application"]["id"], items=(("FENCE", 1000),))
    contract = obligate(ctx["contract"]["id"])
    assert contract["status"] == "OBLIGATED"
    pool = get_pool(ctx["pool"]["id"])
    assert pool["available_cents"] == 150000

    # ADD_PRACTICE exact fit: COVER_CROP 10 ac x 15000 = 150000 == 150000.
    mod1 = validate_success(
        api.request_modification(
            contract["id"],
            {
                "kind": "ADD_PRACTICE",
                "new_practice_code": "COVER_CROP",
                "new_quantity": 10,
                "new_deadline": "2027-03-01T00:00:00Z",
            },
            make_applicant_headers(applicant["id"]),
        ),
        201,
    )
    v1 = get_contract(contract["id"])["version"]
    approved = validate_success(
        api.approve_modification(mod1["id"], {"expected_contract_version": v1}, ADMIN),
        200,
    )
    assert approved["status"] == "APPROVED"
    pool = get_pool(ctx["pool"]["id"])
    assert pool["available_cents"] == 0, "exact-fit addition drains availability"
    assert_pool_invariants(pool)

    # Over by the smallest quantum: FENCE 1 ft = 300 > 0 available.
    mod2 = validate_success(
        api.request_modification(
            contract["id"],
            {
                "kind": "ADD_PRACTICE",
                "new_practice_code": "FENCE",
                "new_quantity": 1,
                "new_deadline": "2027-03-01T00:00:00Z",
            },
            make_applicant_headers(applicant["id"]),
        ),
        201,
    )
    v2 = get_contract(contract["id"])["version"]
    rejected = api.approve_modification(
        mod2["id"], {"expected_contract_version": v2}, ADMIN
    )
    validate_error(rejected, ApiErrorId.ERR_POOL_INSUFFICIENT_FUNDS)
    # Failed approval is atomic: contract stays under review, mod stays open.
    contract_after = get_contract(contract["id"])
    assert contract_after["status"] == "MODIFICATION_PENDING"
    mod2_after = validate_success(api.get_modification(mod2["id"], ADMIN), 200)
    assert mod2_after["status"] == "REQUESTED"


def test_pool_conservation_obligate(api):
    """PRD §2.8: "The derived `available_cents` equals `allocated_cents` minus
    `obligated_cents` minus `paid_cents`, and the conservation invariant holds
    at all times: the allocated amount always equals the sum of the available,
    obligated, and paid balances." PRD §2.8: "Obligation of a contract moves
    funds from available to obligated".

    Design: Difficulty/compensating_invariant/pool_trichotomy_conservation_obligate_then_terminate
    """
    ctx = setup_obligated_contract(
        rates=(
            ("FENCE", "FOOT", 300, 360, 10),
            ("COVER_CROP", "ACRE", 15000, 18000, 5),
        ),
        planned=(("FENCE", 1000), ("COVER_CROP", 10)),
        items=(("FENCE", 1000), ("COVER_CROP", 10)),
    )
    pool = get_pool(ctx["pool"]["id"])
    # 300000 (FENCE) + 150000 (COVER_CROP) = 450000 obligated of 1000000.
    assert pool["obligated_cents"] == 450000
    assert pool["paid_cents"] == 0
    assert pool["available_cents"] == 550000
    assert_pool_invariants(pool)


def test_pool_conservation_restored_by_termination(api):
    """PRD §2.8: "release — through item cancellation, item expiry, contract
    termination, an approved drop-practice modification, or contract
    completion — moves them back." PRD §3.8: "every item in `PLANNED`,
    `INSTALLED`, or `CERTIFICATION_FAILED` moves to `CANCELLED`, and each
    cancellation releases its remaining pool obligation back to available".

    Design: Difficulty/compensating_invariant/pool_trichotomy_conservation_obligate_then_terminate
    """
    ctx = setup_obligated_contract(
        rates=(
            ("FENCE", "FOOT", 300, 360, 10),
            ("COVER_CROP", "ACRE", 15000, 18000, 5),
        ),
        planned=(("FENCE", 1000), ("COVER_CROP", 10)),
        items=(("FENCE", 1000), ("COVER_CROP", 10)),
    )
    terminated = validate_success(
        api.terminate_contract(ctx["contract"]["id"], ADMIN), 200
    )
    assert_contract(terminated)
    assert terminated["status"] == "TERMINATED"

    item = get_item(ctx["items"][0]["id"])
    assert item["certification_status"] == "CANCELLED"

    # Compensating action returns every bucket to its pre-obligation value.
    pool = get_pool(ctx["pool"]["id"])
    assert pool["obligated_cents"] == 0
    assert pool["paid_cents"] == 0
    assert pool["available_cents"] == 1000000
    assert_pool_invariants(pool)
