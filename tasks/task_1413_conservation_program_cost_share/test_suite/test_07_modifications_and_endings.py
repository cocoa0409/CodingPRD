"""Contract modifications (extend/add/drop), OCC guards, completion, termination."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equal,
    assert_pool_invariants,
    build_contract,
    close_program,
    get_contract,
    get_item,
    get_pool,
    issue_advance,
    list_demands,
    make_applicant_headers,
    obligate,
    register_applicant,
    run_ranking,
    set_clock,
    setup_disbursed_request,
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


def _request_extension(ctx, item_id, new_deadline):
    return api_client.request_modification(
        ctx["contract"]["id"],
        {
            "kind": "EXTEND_DEADLINE",
            "practice_item_id": item_id,
            "new_deadline": new_deadline,
        },
        make_applicant_headers(ctx["applicant"]["id"]),
    )


def test_modification_cycle_reject_then_reapprove(api):
    """PRD §3.8: "a successfully lodged request swings the contract from
    `OBLIGATED` to `MODIFICATION_PENDING`, incrementing the contract's
    `version`" and "Either approval or rejection returns the contract to
    `OBLIGATED` and increments the contract's `version`; rejection additionally
    marks the modification `REJECTED`." and "an extension rewrites the item's
    `implementation_deadline` to `new_deadline` and increments the item's
    `version`".

    Design: Difficulty/non_linear_state_machine/contract_modification_cycle_obligated_roundtrip
    """
    ctx = setup_obligated_contract()
    contract_id = ctx["contract"]["id"]
    item_id = ctx["item"]["id"]

    # Hop 1: request swings the contract into review.
    mod1 = validate_success(
        _request_extension(ctx, item_id, "2027-06-01T00:00:00Z"), 201
    )
    assert mod1["status"] == "REQUESTED"
    assert get_contract(contract_id)["status"] == "MODIFICATION_PENDING"

    # Hop 2: rejection returns the contract to OBLIGATED.
    v = get_contract(contract_id)["version"]
    rejected = validate_success(
        api.reject_modification(mod1["id"], {"expected_contract_version": v}, ADMIN), 200
    )
    assert rejected["status"] == "REJECTED"
    assert get_contract(contract_id)["status"] == "OBLIGATED"

    # Hop 3: the cycle is traversable again — request once more and approve.
    mod2 = validate_success(
        _request_extension(ctx, item_id, "2027-06-01T00:00:00Z"), 201
    )
    v2 = get_contract(contract_id)["version"]
    approved = validate_success(
        api.approve_modification(mod2["id"], {"expected_contract_version": v2}, ADMIN),
        200,
    )
    assert approved["status"] == "APPROVED"
    assert get_contract(contract_id)["status"] == "OBLIGATED"

    item = get_item(item_id)
    assert_instant_equal(
        item["implementation_deadline"], "2027-06-01T00:00:00Z",
        "extended implementation_deadline",
    )


def test_modification_cycle_version_ratchet(api):
    """PRD §2.4: "`version` is a system-managed integer that increments by one
    on every mutation of the resource". PRD §3.8: "a successfully lodged
    request swings the contract from `OBLIGATED` to `MODIFICATION_PENDING`,
    incrementing the contract's `version`" and "Either approval or rejection
    returns the contract to `OBLIGATED` and increments the contract's
    `version`; rejection additionally marks the modification `REJECTED`."

    Design: Difficulty/non_linear_state_machine/contract_modification_cycle_obligated_roundtrip
    """
    ctx = setup_obligated_contract()
    contract_id = ctx["contract"]["id"]
    item_id = ctx["item"]["id"]

    v_obligated = get_contract(contract_id)["version"]

    mod1 = validate_success(
        _request_extension(ctx, item_id, "2027-06-01T00:00:00Z"), 201
    )
    v_pending = get_contract(contract_id)["version"]
    assert v_pending == v_obligated + 1, "request bumps the contract version"

    validate_success(
        api.reject_modification(mod1["id"], {"expected_contract_version": v_pending}, ADMIN),
        200,
    )
    v_rejected = get_contract(contract_id)["version"]
    assert v_rejected == v_pending + 1, "rejection bumps the contract version"

    mod2 = validate_success(
        _request_extension(ctx, item_id, "2027-06-01T00:00:00Z"), 201
    )
    v_pending2 = get_contract(contract_id)["version"]
    assert v_pending2 == v_rejected + 1, "second request bumps again"

    validate_success(
        api.approve_modification(mod2["id"], {"expected_contract_version": v_pending2}, ADMIN),
        200,
    )
    v_final = get_contract(contract_id)["version"]
    assert v_final == v_pending2 + 1, "approval bumps the contract version"


def test_modification_approve_stale_version_rejected(api):
    """PRD §2.10: "If the contract's current `version` has advanced since that
    observation — for example because a payment disbursement landed between the
    modification request and its adjudication — the approval is rejected with
    `ERR_STALE_CONTRACT_VERSION` (HTTP 412). A second approval attempt carrying
    the pre-disbursement version fails even though the modification is still
    `REQUESTED` and the contract still `MODIFICATION_PENDING`."

    Design: Corner/cross_cutting_layers/occ_modification_approve_stale_rejected
    """
    ctx = setup_obligated_contract()
    contract_id = ctx["contract"]["id"]
    item_id = ctx["item"]["id"]

    # Version observed before the modification request is lodged.
    v_pre_request = ctx["contract"]["version"]

    mod = validate_success(
        _request_extension(ctx, item_id, "2027-06-01T00:00:00Z"), 201
    )
    v_current = get_contract(contract_id)["version"]
    assert v_current == v_pre_request + 1, (
        "the modification request itself bumped the contract version"
    )

    # Approving against the pre-request (stale) version is refused.
    stale = api.approve_modification(
        mod["id"], {"expected_contract_version": v_pre_request}, ADMIN
    )
    validate_error(stale, ApiErrorId.ERR_STALE_CONTRACT_VERSION)

    # Re-reading and re-issuing with the observed version succeeds.
    approved = validate_success(
        api.approve_modification(
            mod["id"], {"expected_contract_version": v_current}, ADMIN
        ),
        200,
    )
    assert approved["status"] == "APPROVED"


def test_extension_boundary_ladder(api):
    """PRD §3.8: "For `EXTEND_DEADLINE`, the target item's `certification_status`
    must be `PLANNED`, `INSTALLED`, or `CERTIFICATION_FAILED`
    (`ERR_ITEM_NOT_EXTENDABLE`, HTTP 409), and the requested `new_deadline`
    must fall strictly after the item's current `implementation_deadline` and
    no more than 365 days beyond it (`ERR_EXTENSION_TOO_LONG`, HTTP 422). A
    request that fails validation leaves the contract in `OBLIGATED` — the
    swing to `MODIFICATION_PENDING` happens only for a well-formed request."
    PRD §3.8: "the clock must not have passed the item's current deadline
    (`ERR_EXTENSION_WINDOW_CLOSED`, HTTP 409 — reachable precisely because the
    sweep froze during review)". PRD §3.5: "but never while the item's contract
    is under modification review, a freeze that keeps the extension-window rule
    of §3.8 meaningful at approval time".

    Design: Corner/validations/extension_boundary_ladder
    """
    # Two OBLIGATED contracts for one applicant, FENCE 500 each (150000 each).
    ctx = setup_open_program()
    applicant = register_applicant(parcel_ids=("P-100", "P-101"))
    apps = []
    for parcel, points in (("P-100", 30), ("P-101", 20)):
        ctx = setup_screened_application(
            ctx, applicant=applicant, parcel_id=parcel, planned=(("FENCE", 500),),
            self_reported_answers={"SOIL_HEALTH": points},
            verified_answers={"SOIL_HEALTH": points},
        )
        apps.append(ctx["application"])
    close_program(ctx["program"]["id"])
    run_ranking(ctx["program"]["id"])

    ctx = build_contract(ctx, apps[0]["id"], items=(("FENCE", 500),))
    contract_a, item_a = ctx["contract"], ctx["item"]
    obligate(contract_a["id"])
    ctx = build_contract(ctx, apps[1]["id"], items=(("FENCE", 500),))
    contract_b, item_b = ctx["contract"], ctx["item"]
    obligate(contract_b["id"])

    applicant_headers = make_applicant_headers(applicant["id"])

    # Rung 1: deadline + 366 days (2027-03-01 + 365d = 2028-02-29; +366 =
    # 2028-03-01) is too long and is rejected at request time.
    too_long = api.request_modification(
        contract_a["id"],
        {
            "kind": "EXTEND_DEADLINE",
            "practice_item_id": item_a["id"],
            "new_deadline": "2028-03-01T00:00:00Z",
        },
        applicant_headers,
    )
    validate_error(too_long, ApiErrorId.ERR_EXTENSION_TOO_LONG)
    assert get_contract(contract_a["id"])["status"] == "OBLIGATED", (
        "a failed request leaves the contract OBLIGATED"
    )

    # Rung 2: exactly +365 days is allowed.
    mod_a = validate_success(
        api.request_modification(
            contract_a["id"],
            {
                "kind": "EXTEND_DEADLINE",
                "practice_item_id": item_a["id"],
                "new_deadline": "2028-02-29T00:00:00Z",
            },
            applicant_headers,
        ),
        201,
    )
    v_a = get_contract(contract_a["id"])["version"]
    approved = validate_success(
        api.approve_modification(mod_a["id"], {"expected_contract_version": v_a}, ADMIN),
        200,
    )
    assert approved["status"] == "APPROVED"
    item_a_after = get_item(item_a["id"])
    assert_instant_equal(
        item_a_after["implementation_deadline"], "2028-02-29T00:00:00Z",
        "extended deadline",
    )

    # Rung 3: contract B under review when its item's deadline passes — the
    # expiry sweep is frozen, so the item is still PLANNED, and the approve-time
    # temporal check fires instead.
    mod_b = validate_success(
        api.request_modification(
            contract_b["id"],
            {
                "kind": "EXTEND_DEADLINE",
                "practice_item_id": item_b["id"],
                "new_deadline": "2027-06-01T00:00:00Z",
            },
            applicant_headers,
        ),
        201,
    )
    set_clock("2027-03-02T00:00:00Z")
    assert get_item(item_b["id"])["certification_status"] == "PLANNED", (
        "expiry sweep is frozen while the contract is under modification review"
    )
    v_b = get_contract(contract_b["id"])["version"]
    closed = api.approve_modification(
        mod_b["id"], {"expected_contract_version": v_b}, ADMIN
    )
    validate_error(closed, ApiErrorId.ERR_EXTENSION_WINDOW_CLOSED)


def test_drop_practice_cancels_item_and_restores_contract(api):
    """PRD §3.8: "a drop cancels the item (`CANCELLED`), releases its remaining
    obligation — the scheduled amount less the advance net outstanding — back
    to the pool's available balance". PRD §3.8: "Either approval or rejection
    returns the contract to `OBLIGATED` and increments the contract's
    `version`". PRD §3.4: "the contract's `obligated_amount_cents` is
    recomputed as the sum of `scheduled_amount_cents` over its non-terminal
    items".

    Design: Difficulty/transitive_cascade/drop_practice_modification_cascade
    """
    ctx = setup_obligated_contract(
        rates=(
            ("FENCE", "FOOT", 300, 360, 10),
            ("COVER_CROP", "ACRE", 15000, 18000, 5),
        ),
        planned=(("FENCE", 1000), ("COVER_CROP", 10)),
        items=(("FENCE", 1000), ("COVER_CROP", 10)),
    )
    fence_item, crop_item = ctx["items"]
    contract_id = ctx["contract"]["id"]

    mod = validate_success(
        api.request_modification(
            contract_id,
            {"kind": "DROP_PRACTICE", "practice_item_id": crop_item["id"]},
            make_applicant_headers(ctx["applicant"]["id"]),
        ),
        201,
    )
    v = get_contract(contract_id)["version"]
    approved = validate_success(
        api.approve_modification(mod["id"], {"expected_contract_version": v}, ADMIN),
        200,
    )
    assert approved["status"] == "APPROVED"

    # Hop 1: the dropped item is cancelled.
    assert get_item(crop_item["id"])["certification_status"] == "CANCELLED"
    assert get_item(fence_item["id"])["certification_status"] == "PLANNED"

    contract = get_contract(contract_id)
    assert contract["status"] == "OBLIGATED"
    # Contract total recomputed over non-terminal items only.
    assert contract["obligated_amount_cents"] == 300000


def test_drop_practice_releases_pool_obligation(api):
    """PRD §3.8: "a drop cancels the item (`CANCELLED`), releases its remaining
    obligation — the scheduled amount less the advance net outstanding — back
    to the pool's available balance". PRD §2.8: "release — through item
    cancellation, item expiry, contract termination, an approved drop-practice
    modification, or contract completion — moves them back."

    Design: Difficulty/transitive_cascade/drop_practice_modification_cascade
    """
    ctx = setup_obligated_contract(
        rates=(
            ("FENCE", "FOOT", 300, 360, 10),
            ("COVER_CROP", "ACRE", 15000, 18000, 5),
        ),
        planned=(("FENCE", 1000), ("COVER_CROP", 10)),
        items=(("FENCE", 1000), ("COVER_CROP", 10)),
    )
    crop_item = ctx["items"][1]
    contract_id = ctx["contract"]["id"]

    pool_before = get_pool(ctx["pool"]["id"])
    assert pool_before["obligated_cents"] == 450000
    assert pool_before["available_cents"] == 550000

    mod = validate_success(
        api.request_modification(
            contract_id,
            {"kind": "DROP_PRACTICE", "practice_item_id": crop_item["id"]},
            make_applicant_headers(ctx["applicant"]["id"]),
        ),
        201,
    )
    v = get_contract(contract_id)["version"]
    validate_success(
        api.approve_modification(mod["id"], {"expected_contract_version": v}, ADMIN),
        200,
    )

    # Hop 2 (caused by the cancellation): the 150000 reservation returns.
    pool = get_pool(ctx["pool"]["id"])
    assert pool["obligated_cents"] == 300000
    assert pool["available_cents"] == 700000
    assert_pool_invariants(pool)


def test_contract_complete_happy_path(api):
    """PRD §3.8: "Completion moves an `OBLIGATED` contract to `COMPLETED` and
    demands a clean ledger, checked under the ladder of §2.6" and "On
    completion the contract's `version` increments and any residual obligation
    still held for the contract is released back to the pool, obligated falling
    and available rising by the same amount." PRD §3.7: "Within the pool,
    `obligated_cents` falls by the item's `scheduled_amount_cents` less the
    advance amount already issued against the item, while `paid_cents` grows by
    the newly disbursed cash".

    Design: Corner/state_machines/contract_complete_happy_path
    """
    ctx = setup_disbursed_request(certified_quantity=900, documented_cost_cents=400000)
    # computed = min(900 x 300, 400000) = 270000, disbursed in full (no advance).
    assert ctx["request"]["disbursed_amount_cents"] == 270000

    completed = validate_success(
        api.complete_contract(ctx["contract"]["id"], ADMIN), 200
    )
    assert completed["status"] == "COMPLETED"

    pool = get_pool(ctx["pool"]["id"])
    assert pool["obligated_cents"] == 0, "disbursement released the full schedule"
    assert pool["paid_cents"] == 270000
    assert pool["available_cents"] == 730000
    assert_pool_invariants(pool)


def test_termination_cascade_releases_and_escalates(api):
    """PRD §3.8: "The termination then cascades: every item in `PLANNED`,
    `INSTALLED`, or `CERTIFICATION_FAILED` moves to `CANCELLED`, and each
    cancellation releases its remaining pool obligation back to available;
    every advance with money still outstanding is forced to `RETURN_DUE` with
    its `expenditure_due_date` reset to the current clock, its later escalation
    sweep spawning the recoupment demand". PRD §3.8: "A paid demand restores
    the pool, reducing `paid_cents` by the recovered amount; moves the linked
    item from `RECOUPMENT_PENDING` to `RECOUPED`, the payment dimension's
    terminal state; and, when the demand was born of an advance, increments
    that advance's `returned_cents`, zeroes its outstanding balance, and closes
    the advance."

    Design: Corner/cross_cutting_layers/termination_cascade_releases_and_escalates
    """
    ctx = setup_hu_contract_with_advance(100000)
    contract_id = ctx["contract"]["id"]
    item_id = ctx["item"]["id"]
    advance_id = ctx["advance"]["id"]

    set_clock("2026-09-15T00:00:00Z")
    terminated = validate_success(api.terminate_contract(contract_id, ADMIN), 200)
    assert terminated["status"] == "TERMINATED"

    # Hop 1: the PLANNED item is cancelled.
    assert get_item(item_id)["certification_status"] == "CANCELLED"

    # Hop 2: the outstanding advance is forced to RETURN_DUE, due at once.
    advance = api.get_advance(advance_id, ADMIN)
    advance = validate_success(advance, 200)
    assert advance["status"] == "RETURN_DUE"
    assert_instant_equal(
        advance["expenditure_due_date"], "2026-09-15T00:00:00Z",
        "forced expenditure_due_date",
    )

    # The cancellation releases scheduled 360000 less advance net 100000.
    pool = get_pool(ctx["pool"]["id"])
    assert pool["obligated_cents"] == 0
    assert pool["paid_cents"] == 100000
    assert pool["available_cents"] == 400000
    assert_pool_invariants(pool)

    # Hop 3: thirty days past the forced due date, the advance escalates and
    # spawns a recoupment demand for the outstanding amount.
    set_clock("2026-10-16T00:00:00Z")
    advance = validate_success(api.get_advance(advance_id, ADMIN), 200)
    assert advance["status"] == "ESCALATED"
    demands = list_demands(advance_payment_id=advance_id)
    assert len(demands) == 1
    assert demands[0]["amount_cents"] == 100000
    assert demands[0]["status"] == "DEMANDED"

    paid = validate_success(
        api.pay_recoupment_demand(
            demands[0]["id"], {"amount_cents": 100000},
            make_applicant_headers(ctx["applicant"]["id"]),
        ),
        200,
    )
    assert paid["status"] == "PAID"

    advance = validate_success(api.get_advance(advance_id, ADMIN), 200)
    assert advance["status"] == "CLOSED"
    assert advance["returned_cents"] == 100000

    pool = get_pool(ctx["pool"]["id"])
    assert pool["paid_cents"] == 0
    assert pool["available_cents"] == 500000
    assert_pool_invariants(pool)
