"""Historically underserved advances: caps, cardinality, returns, sweeps."""
from test_helpers import (
    ApiErrorId,
    assert_advance_invariants,
    assert_instant_equal,
    assert_pool_invariants,
    build_contract,
    certify,
    close_program,
    create_request,
    get_advance,
    get_contract,
    get_item,
    get_pool,
    install,
    issue_advance,
    list_demands,
    make_applicant_headers,
    obligate,
    register_applicant,
    review_request,
    approve_request,
    run_ranking,
    set_clock,
    setup_hu_contract_with_advance,
    setup_obligated_contract,
    setup_open_program,
    setup_screened_application,
    TEST_USERS,
    api_client,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
PO = TEST_USERS["po_headers"]


def _setup_two_hu_contracts(api):
    """HU LIMITED_RESOURCE applicant with two SELECTED FENCE-1000 contracts,
    both OBLIGATED against a 1000000 HU pool (scheduled 360000 each)."""
    ctx = setup_open_program(
        pools=(("HU_LIMITED_RESOURCE", 1000000),), advance_cap_pct=0.5
    )
    applicant = register_applicant(
        legal_name="H U", hu_category="LIMITED_RESOURCE",
        parcel_ids=("P-200", "P-201"),
    )
    apps = []
    for parcel, points in (("P-200", 30), ("P-201", 20)):
        ctx = setup_screened_application(
            ctx, applicant=applicant, parcel_id=parcel, planned=(("FENCE", 1000),),
            self_reported_answers={"SOIL_HEALTH": points},
            verified_answers={"SOIL_HEALTH": points},
        )
        apps.append(ctx["application"])
    close_program(ctx["program"]["id"])
    run_ranking(ctx["program"]["id"])
    contracts = []
    for app in apps:
        ctx = build_contract(ctx, app["id"], items=(("FENCE", 1000),))
        ctx["contract"] = obligate(ctx["contract"]["id"])
        contracts.append((ctx["contract"], ctx["item"]))
    return ctx, applicant, contracts


def test_advance_exact_cap_succeeds(api):
    """PRD §3.6: "the requested `issued_cents` must be at least 1 cent and no
    greater than the advance cap: the program's `advance_cap_pct` multiplied by
    the item's `scheduled_amount_cents`, rounded half-up to whole cents — half
    the scheduled amount under the default cap. An advance of exactly the cap
    succeeds; one cent more is rejected with `ERR_ADVANCE_CAP_EXCEEDED`
    (HTTP 422)." and "The advance records `issued_at` as the current clock
    instant, computes its `expenditure_due_date` as exactly 90 days later".

    Design: Difficulty/boundary_precision_check/advance_cap_exact_50pct_boundary
    """
    ctx, applicant, contracts = _setup_two_hu_contracts(api)
    contract, item = contracts[0]

    advance = issue_advance(contract["id"], item["id"], 180000)
    # round_half_up(0.5 * 360000) = 180000: the exact cap succeeds.
    assert advance["status"] == "ISSUED"
    assert advance["outstanding_cents"] == 180000
    assert_advance_invariants(advance)
    # Issued at the startup clock 2026-08-01; due exactly 90 days later.
    assert_instant_equal(
        advance["expenditure_due_date"], "2026-10-30T00:00:00Z", "expenditure_due_date"
    )

    pool = get_pool(ctx["pool"]["id"])
    assert pool["paid_cents"] == 180000
    assert_pool_invariants(pool)


def test_advance_one_cent_over_cap_rejected(api):
    """PRD §3.6: "the requested `issued_cents` must be at least 1 cent and no
    greater than the advance cap: the program's `advance_cap_pct` multiplied by
    the item's `scheduled_amount_cents`, rounded half-up to whole cents — half
    the scheduled amount under the default cap. An advance of exactly the cap
    succeeds; one cent more is rejected with `ERR_ADVANCE_CAP_EXCEEDED`
    (HTTP 422)."

    Design: Difficulty/boundary_precision_check/advance_cap_exact_50pct_boundary
    """
    _, _, contracts = _setup_two_hu_contracts(api)
    contract, item = contracts[1]

    resp = api.issue_advance(
        contract["id"],
        {"practice_item_id": item["id"], "issued_cents": 180001},
        PO,
    )
    validate_error(resp, ApiErrorId.ERR_ADVANCE_CAP_EXCEEDED)


def test_advance_cap_rounds_half_up(api):
    """PRD §3.6: "the requested `issued_cents` must be at least 1 cent and no
    greater than the advance cap: the program's `advance_cap_pct` multiplied by
    the item's `scheduled_amount_cents`, rounded half-up to whole cents".
    PRD §2.9: "Every multiplication that produces a monetary amount — a
    scheduled item amount, an estimated obligation line, an advance cap, a
    certified payment amount — rounds half-up to whole cents at the point the
    amount is computed (a fraction of one-half cent or greater rounds up)".

    Design: Corner/calculations/advance_cap_rounding_half_up
    """
    ctx = setup_obligated_contract(
        pools=(("HU_BEGINNING_FARMER", 500000),),
        rates=(("COVER_CROP", "ACRE", 15000, 18001, 5),),
        hu_category="BEGINNING_FARMER",
        parcel_ids=("P-200",),
        planned=(("COVER_CROP", 3),),
        items=(("COVER_CROP", 3),),
    )
    item = ctx["item"]
    # 3 ac x 18001 = 54003; cap = round_half_up(0.5 * 54003) = 27002.
    assert item["scheduled_amount_cents"] == 54003

    advance = issue_advance(ctx["contract"]["id"], item["id"], 27002)
    assert advance["status"] == "ISSUED"
    assert advance["outstanding_cents"] == 27002
    assert_advance_invariants(advance)


def test_advance_non_hu_rejected(api):
    """PRD §3.6: "The applicant must be historically underserved
    (`ERR_NOT_HISTORICALLY_UNDERSERVED`, HTTP 422)."

    Design: Corner/validations/advance_non_hu_rejected
    """
    ctx = setup_obligated_contract()
    resp = api.issue_advance(
        ctx["contract"]["id"],
        {"practice_item_id": ctx["item"]["id"], "issued_cents": 1000},
        PO,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_HISTORICALLY_UNDERSERVED)


def test_advance_cardinality_rules(api):
    """PRD §3.6: "The item must never have had an advance before, in any status
    (`ERR_ADVANCE_ALREADY_ISSUED`, HTTP 409), and no advance anywhere on the
    contract may still have money outstanding (`ERR_ADVANCE_OUTSTANDING`,
    HTTP 409)."

    Design: Corner/validations/advance_cardinality_rules_rejected
    """
    ctx = setup_obligated_contract(
        pools=(("HU_LIMITED_RESOURCE", 500000),),
        hu_category="LIMITED_RESOURCE",
        parcel_ids=("P-200",),
        planned=(("FENCE", 1000),),
        items=(("FENCE", 500), ("FENCE", 500)),
    )
    item1, item2 = ctx["items"]
    applicant_id = ctx["applicant"]["id"]

    # Each item scheduled 500 x 360 = 180000; cap is 90000 each.
    advance1 = issue_advance(ctx["contract"]["id"], item1["id"], 90000)
    assert advance1["status"] == "ISSUED"

    # Contract-level rule: one outstanding advance at a time.
    blocked = api.issue_advance(
        ctx["contract"]["id"],
        {"practice_item_id": item2["id"], "issued_cents": 1000},
        PO,
    )
    validate_error(blocked, ApiErrorId.ERR_ADVANCE_OUTSTANDING)

    returned = validate_success(
        api.return_advance(
            advance1["id"], {"amount_cents": 90000},
            make_applicant_headers(applicant_id),
        ),
        200,
    )
    assert returned["status"] == "CLOSED"

    # Item-level rule: once-ever, even after the first advance is CLOSED.
    replay = api.issue_advance(
        ctx["contract"]["id"],
        {"practice_item_id": item1["id"], "issued_cents": 1000},
        PO,
    )
    validate_error(replay, ApiErrorId.ERR_ADVANCE_ALREADY_ISSUED)

    # The other item remains advanceable at exactly its cap.
    advance2 = issue_advance(ctx["contract"]["id"], item2["id"], 90000)
    assert advance2["status"] == "ISSUED"


def test_advance_return_amount_mismatch_rejected(api):
    """PRD §3.6: "The producer who will not spend the advance returns it,
    paying back exactly the outstanding amount in a single `amount_cents`
    payment — any other figure is rejected with `ERR_RETURN_AMOUNT_MISMATCH`
    (HTTP 422) — from either `ISSUED` or `RETURN_DUE` (any other state yields
    `ERR_ADVANCE_NOT_RETURNABLE`, HTTP 409)."

    Design: Corner/validations/advance_return_amount_mismatch_rejected
    """
    ctx = setup_hu_contract_with_advance(180000)
    advance = ctx["advance"]
    applicant_id = ctx["applicant"]["id"]

    wrong = api.return_advance(
        advance["id"], {"amount_cents": 179999}, make_applicant_headers(applicant_id)
    )
    validate_error(wrong, ApiErrorId.ERR_RETURN_AMOUNT_MISMATCH)

    exact = validate_success(
        api.return_advance(
            advance["id"], {"amount_cents": 180000},
            make_applicant_headers(applicant_id),
        ),
        200,
    )
    assert exact["status"] == "CLOSED"
    assert exact["returned_cents"] == 180000
    assert_advance_invariants(exact)


def test_advance_issue_moves_pool_funds(api):
    """PRD §3.6: "Issuance moves the issued amount within the pool from
    obligated to paid — `obligated_cents` falls by `issued_cents` and
    `paid_cents` rises by the same amount — and moves the item's payment
    dimension from `UNPAID` to `ADVANCE_HELD`." PRD §3.6: "Three accounting
    fields are bound by a standing invariant: the issued amount always equals
    the sum of the applied, returned, and outstanding portions."

    Design: Difficulty/compensating_invariant/advance_issue_return_neutralizes_pool_paid
    """
    ctx = setup_obligated_contract(
        pools=(("HU_LIMITED_RESOURCE", 500000),),
        hu_category="LIMITED_RESOURCE", parcel_ids=("P-200",),
    )
    pool0 = get_pool(ctx["pool"]["id"])
    assert pool0["obligated_cents"] == 360000
    assert pool0["paid_cents"] == 0
    assert pool0["available_cents"] == 140000

    advance = issue_advance(ctx["contract"]["id"], ctx["item"]["id"], 180000)
    assert advance["outstanding_cents"] == 180000
    assert_advance_invariants(advance)

    pool1 = get_pool(ctx["pool"]["id"])
    assert pool1["obligated_cents"] == 180000
    assert pool1["paid_cents"] == 180000
    assert pool1["available_cents"] == 140000
    assert_pool_invariants(pool1)


def test_advance_full_return_restores_pool(api):
    """PRD §3.6: "A full return increments `returned_cents` by the amount,
    drives the outstanding balance to zero, closes the advance (`CLOSED`, its
    terminal state), and restores the pool by reducing `paid_cents` by the
    returned amount; across an issue-and-full-return pair the pool's paid
    balance is unchanged net-net."

    Design: Difficulty/compensating_invariant/advance_issue_return_neutralizes_pool_paid
    """
    ctx = setup_hu_contract_with_advance(180000)
    pool0 = get_pool(ctx["pool"]["id"])
    assert pool0["paid_cents"] == 180000

    returned = validate_success(
        api.return_advance(
            ctx["advance"]["id"], {"amount_cents": 180000},
            make_applicant_headers(ctx["applicant"]["id"]),
        ),
        200,
    )
    assert returned["status"] == "CLOSED"
    assert returned["outstanding_cents"] == 0
    assert_advance_invariants(returned)

    pool = get_pool(ctx["pool"]["id"])
    assert pool["paid_cents"] == 0, "the issue/return pair is exactly neutral"
    assert pool["obligated_cents"] == 360000
    assert pool["available_cents"] == 140000
    assert_pool_invariants(pool)


def test_advance_moves_only_payment_dimension(api):
    """PRD §3.4: "New items begin `PLANNED` on the certification dimension and
    `UNPAID` on the payment dimension — two parallel status dimensions carried
    on the same row". PRD §3.6: "moves the item's payment dimension from
    `UNPAID` to `ADVANCE_HELD`."

    Design: Difficulty/non_linear_state_machine/practice_item_parallel_dimensions_evolve_independently
    """
    ctx = setup_hu_contract_with_advance(180000)
    item = get_item(ctx["item"]["id"])
    # Advance issuance moved the payment dimension only.
    assert item["certification_status"] == "PLANNED"
    assert item["payment_status"] == "ADVANCE_HELD"

    install(ctx["item"]["id"], ctx["applicant"]["id"])
    certify(ctx["item"]["id"], 900)
    item = get_item(ctx["item"]["id"])
    # Certification moved the certification dimension only.
    assert item["certification_status"] == "CERTIFIED"
    assert item["payment_status"] == "ADVANCE_HELD"


def test_disbursement_joins_payment_dimensions(api):
    """PRD §3.7: "The `advance_offset_cents` is the smaller of the computed
    amount and the outstanding balance of the item's advance, or zero when no
    advance exists; the `disbursed_amount_cents` is the computed amount minus
    that offset." and "The advance, when one exists, absorbs the offset into
    `applied_cents`; if that zeroes its outstanding balance the advance moves
    to `CLOSED`, otherwise it moves to `RETURN_DUE` with its
    `expenditure_due_date` reset to the current clock. The item's payment
    dimension moves to `PAID` — from `UNPAID` when no advance was outstanding,
    from `ADVANCE_HELD` when one was".

    Design: Difficulty/non_linear_state_machine/practice_item_parallel_dimensions_evolve_independently
    """
    ctx = setup_hu_contract_with_advance(180000)
    install(ctx["item"]["id"], ctx["applicant"]["id"])
    certify(ctx["item"]["id"], 900)
    request = create_request(
        ctx["contract"]["id"], ctx["item"]["id"], ctx["applicant"]["id"],
        documented_cost_cents=400000,
    )
    review_request(request["id"])
    approve_request(request["id"])
    disbursed = validate_success(api.disburse_payment_request(request["id"], PO), 200)

    # computed = min(900 x 360, 400000) = 324000; offset = min(324000, 180000).
    assert disbursed["advance_offset_cents"] == 180000
    assert disbursed["disbursed_amount_cents"] == 144000

    item = get_item(ctx["item"]["id"])
    assert item["certification_status"] == "CERTIFIED"
    assert item["payment_status"] == "PAID", "disbursement joins the two dimensions"

    advance = get_advance(ctx["advance"]["id"])
    assert advance["applied_cents"] == 180000
    assert advance["outstanding_cents"] == 0
    assert advance["status"] == "CLOSED"
    assert_advance_invariants(advance)


def _setup_paid_with_residual_advance(api):
    """HU contract: advance 180000, certify 100, documented 100000 ->
    computed 36000, offset 36000, advance left with outstanding 144000."""
    ctx = setup_hu_contract_with_advance(180000)
    install(ctx["item"]["id"], ctx["applicant"]["id"])
    certify(ctx["item"]["id"], 100)
    request = create_request(
        ctx["contract"]["id"], ctx["item"]["id"], ctx["applicant"]["id"],
        documented_cost_cents=100000,
    )
    assert request["computed_amount_cents"] == 360000 // 10  # min(100*360, 100000)
    review_request(request["id"])
    approve_request(request["id"])
    disbursed = validate_success(api.disburse_payment_request(request["id"], PO), 200)
    assert disbursed["advance_offset_cents"] == 36000
    assert disbursed["disbursed_amount_cents"] == 0
    ctx["request"] = disbursed
    return ctx


def test_complete_blocked_by_outstanding_advance(api):
    """PRD §3.8: "every practice item must be terminal — either `CERTIFIED`
    with its payment dimension in `PAID` or `RECOUPED`, or else `CANCELLED` or
    `EXPIRED` — otherwise `ERR_ITEMS_NOT_FINAL` (HTTP 409); no advance of the
    contract may stand in `ISSUED`, `RETURN_DUE`, or `ESCALATED`
    (`ERR_ADVANCE_OUTSTANDING`)". PRD §3.7: "if that zeroes its outstanding
    balance the advance moves to `CLOSED`, otherwise it moves to `RETURN_DUE`
    with its `expenditure_due_date` reset to the current clock."

    Design: Difficulty/cross_entity_state_dependency/contract_complete_blocked_by_outstanding_advance
    """
    ctx = _setup_paid_with_residual_advance(api)

    advance = get_advance(ctx["advance"]["id"])
    assert advance["status"] == "RETURN_DUE", (
        "a residual outstanding balance after disbursement forces RETURN_DUE"
    )
    assert advance["outstanding_cents"] == 144000

    resp = api.complete_contract(ctx["contract"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_ADVANCE_OUTSTANDING)


def test_complete_succeeds_after_advance_return(api):
    """PRD §3.8: "no advance of the contract may stand in `ISSUED`,
    `RETURN_DUE`, or `ESCALATED` (`ERR_ADVANCE_OUTSTANDING`)" and "Completion
    moves an `OBLIGATED` contract to `COMPLETED` and demands a clean ledger".
    PRD §2.8: "the conservation invariant holds at all times: the allocated
    amount always equals the sum of the available, obligated, and paid
    balances."

    Design: Difficulty/cross_entity_state_dependency/contract_complete_blocked_by_outstanding_advance
    """
    ctx = _setup_paid_with_residual_advance(api)

    returned = validate_success(
        api.return_advance(
            ctx["advance"]["id"], {"amount_cents": 144000},
            make_applicant_headers(ctx["applicant"]["id"]),
        ),
        200,
    )
    assert returned["status"] == "CLOSED"

    completed = validate_success(api.complete_contract(ctx["contract"]["id"], ADMIN), 200)
    assert completed["status"] == "COMPLETED"

    pool = get_pool(ctx["pool"]["id"])
    # paid = 180000 issued - 144000 returned = 36000; obligation fully settled.
    assert pool["obligated_cents"] == 0
    assert pool["paid_cents"] == 36000
    assert pool["available_cents"] == 464000
    assert_pool_invariants(pool)


def test_advance_due_sweep_boundary_and_escalation(api):
    """PRD §3.6: "The sweep of §2.7 moves an advance from `ISSUED` to
    `RETURN_DUE` once the clock passes `expenditure_due_date` with money still
    outstanding". PRD §3.6: "From `RETURN_DUE`, a second sweep fires once the
    clock passes thirty days beyond the due date with funds still outstanding:
    the advance moves to `ESCALATED` and the system spawns a **Recoupment
    Demand** for the outstanding amount, linking it through `advance_payment_id`
    and setting its `due_date` thirty days out." PRD §3.8: "Payment is the
    producer's action and must cover exactly the demand's `amount_cents` in a
    single `amount_cents` payment — any other figure is rejected with
    `ERR_REPAYMENT_AMOUNT_MISMATCH` (HTTP 422)" and "when the demand was born
    of an advance, increments that advance's `returned_cents`, zeroes its
    outstanding balance, and closes the advance."

    Design: Corner/cross_cutting_layers/advance_due_sweep_boundary_and_escalation
    """
    ctx = setup_hu_contract_with_advance(180000)
    advance = ctx["advance"]
    # Issued at the startup clock 2026-08-01; due exactly 90 days later.
    assert_instant_equal(
        advance["expenditure_due_date"], "2026-10-30T00:00:00Z", "expenditure_due_date"
    )

    # At exactly the due date the clock has not passed it: still ISSUED.
    set_clock("2026-10-30T00:00:00Z")
    assert get_advance(advance["id"])["status"] == "ISSUED"

    # One second past the due date: RETURN_DUE.
    set_clock("2026-10-30T00:00:01Z")
    assert get_advance(advance["id"])["status"] == "RETURN_DUE"

    # Thirty days beyond the due date plus one second: ESCALATED + demand.
    set_clock("2026-11-29T00:00:01Z")
    assert get_advance(advance["id"])["status"] == "ESCALATED"
    demands = list_demands(advance_payment_id=advance["id"])
    assert len(demands) == 1
    demand = demands[0]
    assert demand["amount_cents"] == 180000
    assert demand["status"] == "DEMANDED"
    assert_instant_equal(
        demand["due_date"], "2026-12-29T00:00:01Z", "demand due_date"
    )

    applicant_id = ctx["applicant"]["id"]
    wrong = api.pay_recoupment_demand(
        demand["id"], {"amount_cents": 179999}, make_applicant_headers(applicant_id)
    )
    validate_error(wrong, ApiErrorId.ERR_REPAYMENT_AMOUNT_MISMATCH)

    paid = validate_success(
        api.pay_recoupment_demand(
            demand["id"], {"amount_cents": 180000}, make_applicant_headers(applicant_id)
        ),
        200,
    )
    assert paid["status"] == "PAID"
    settled = get_advance(advance["id"])
    assert settled["status"] == "CLOSED"
    assert_advance_invariants(settled)

    pool = get_pool(ctx["pool"]["id"])
    assert pool["paid_cents"] == 0
    assert_pool_invariants(pool)
