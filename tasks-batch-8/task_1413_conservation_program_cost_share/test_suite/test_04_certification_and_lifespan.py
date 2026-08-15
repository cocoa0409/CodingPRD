"""Installation/certification workflow, maintenance obligations, and expiry sweeps."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equal,
    assert_pool_invariants,
    certify,
    create_contract_for,
    get_item,
    get_pool,
    install,
    list_obligations_for_item,
    make_planner_headers,
    obligate,
    run_ranking,
    close_program,
    set_clock,
    setup_certified_item,
    setup_obligated_contract,
    setup_screened_application,
    setup_open_program,
    register_applicant,
    setup_selected_application,
    build_contract,
    fail_certification,
    api_client,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_certification_failure_retry_cycle(api):
    """PRD §3.5: "When an installation does not meet standards, the planner
    fails the certification, moving the item from `INSTALLED` to
    `CERTIFICATION_FAILED` and incrementing its `version`; the producer may
    then correct and report installation again, cycling back to `INSTALLED`."

    Design: Corner/state_machines/certification_failure_retry_cycle
    """
    ctx = setup_obligated_contract()
    item = ctx["item"]
    applicant_id = ctx["applicant"]["id"]

    s1 = install(item["id"], applicant_id)
    assert s1["certification_status"] == "INSTALLED"
    s2 = fail_certification(item["id"])
    assert s2["certification_status"] == "CERTIFICATION_FAILED"
    s3 = install(item["id"], applicant_id)
    assert s3["certification_status"] == "INSTALLED", "retry loop re-enters INSTALLED"
    s4 = certify(item["id"], 950)
    assert s4["certification_status"] == "CERTIFIED"
    assert s4["certified_quantity"] == 950


def test_certify_creates_maintenance_obligation(api):
    """PRD §3.5: "Successful certification records `certified_quantity`, the
    certifying planner's `X-User-ID` as `certified_by_user_id`, and the
    logical-clock instant as `certified_at`, increments the item's `version`,
    and opens a **Maintenance Obligation** — exactly one per certification.
    The obligation copies the item's `contract_id`, `practice_item_id`,
    `parcel_id`, and `practice_code`, takes `start_date` equal to
    `certified_at`, computes `end_date` as `certified_at` plus `lifespan_years`
    times 365 days, and begins in `ACTIVE`."

    Design: Corner/state_machines/certify_creates_maintenance_obligation
    """
    ctx = setup_obligated_contract(
        rates=(("COVER_CROP", "ACRE", 15000, 18000, 5),),
        planned=(("COVER_CROP", 10),),
        items=(("COVER_CROP", 10),),
    )
    item = install(ctx["item"]["id"], ctx["applicant"]["id"])
    set_clock("2026-10-01T00:00:00Z")
    certified = certify(item["id"], 10)
    assert certified["certification_status"] == "CERTIFIED"

    obligations = list_obligations_for_item(item["id"])
    assert len(obligations) == 1, "exactly one obligation per certification"
    obligation = obligations[0]
    assert obligation["status"] == "ACTIVE"
    assert_instant_equal(obligation["start_date"], "2026-10-01T00:00:00Z", "start_date")
    # 2026-10-01 + 5 * 365 days = 2031-09-30.
    assert_instant_equal(obligation["end_date"], "2031-09-30T00:00:00Z", "end_date")
    assert obligation["practice_code"] == "COVER_CROP"
    assert obligation["parcel_id"] == "P-100"
    assert obligation["contract_id"] == ctx["contract"]["id"]
    assert obligation["practice_item_id"] == item["id"]


def test_certify_quantity_boundaries(api):
    """PRD §3.5: "The certification payload carries `certified_quantity`, which
    must be at least 1 and no greater than the item's `planned_quantity`, or
    the certification fails with `ERR_CERTIFIED_QUANTITY_INVALID` (HTTP 422);
    until this moment the field remains unset."

    Design: Corner/validations/certify_quantity_boundaries
    """
    ctx = setup_obligated_contract()
    install(ctx["item"]["id"], ctx["applicant"]["id"])

    zero = api.certify_item(
        ctx["item"]["id"], {"certified_quantity": 0}, TEST_USERS["planner_headers"]
    )
    validate_error(zero, ApiErrorId.ERR_CERTIFIED_QUANTITY_INVALID)

    over = api.certify_item(
        ctx["item"]["id"], {"certified_quantity": 1001}, TEST_USERS["planner_headers"]
    )
    validate_error(over, ApiErrorId.ERR_CERTIFIED_QUANTITY_INVALID)

    exact = validate_success(
        api.certify_item(
            ctx["item"]["id"], {"certified_quantity": 1000}, TEST_USERS["planner_headers"]
        ),
        200,
    )
    assert exact["certification_status"] == "CERTIFIED", (
        "boundary inclusive: exactly planned_quantity certifies"
    )


def test_item_expiry_sweep_deadline_boundary(api):
    """PRD §3.5: "The expiry sweep of §2.7 moves an item from `PLANNED`,
    `INSTALLED`, or `CERTIFICATION_FAILED` to `EXPIRED` once the clock passes
    `implementation_deadline`". PRD §3.5: "Expiry releases the item's remaining
    pool obligation — its `scheduled_amount_cents` less the advance net
    outstanding on the item — returning those funds from obligated to
    available".

    Design: Corner/state_machines/item_expiry_sweep_deadline_boundary
    """
    ctx = setup_obligated_contract()
    item_id = ctx["item"]["id"]
    pool_before = get_pool(ctx["pool"]["id"])
    assert pool_before["obligated_cents"] == 300000

    # At exactly the deadline the clock has not passed it: no expiry.
    set_clock("2027-03-01T00:00:00Z")
    at_deadline = get_item(item_id)
    assert at_deadline["certification_status"] == "PLANNED", (
        "breach requires clock strictly past the deadline"
    )

    # One second later the item expires and releases its obligation.
    set_clock("2027-03-01T00:00:01Z")
    after = get_item(item_id)
    assert after["certification_status"] == "EXPIRED"
    pool_after = get_pool(ctx["pool"]["id"])
    assert pool_after["obligated_cents"] == 0
    assert pool_after["available_cents"] == 1000000
    assert_pool_invariants(pool_after)


def test_obligation_overlap_rejected(api):
    """PRD §3.5: "because each certification opens a multi-year maintenance
    obligation on the parcel, certification is blocked when another obligation
    on the same parcel and practice code is `ACTIVE` or `VIOLATION_REVIEW` and
    its `end_date` falls strictly after the new certification instant." and "a
    genuine overlap is rejected with `ERR_OBLIGATION_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/obligation_overlap_half_open_adjacency
    """
    # Two SELECTED applications on the SAME parcel, each planning COVER_CROP.
    ctx = setup_open_program(rates=(("COVER_CROP", "ACRE", 15000, 18000, 5),))
    applicant = register_applicant(parcel_ids=("P-300", "P-301"))
    ctx = setup_screened_application(
        ctx, applicant=applicant, parcel_id="P-300", planned=(("COVER_CROP", 10),),
        self_reported_answers={"SOIL_HEALTH": 30},
        verified_answers={"SOIL_HEALTH": 30},
    )
    app_a = ctx["application"]
    ctx = setup_screened_application(
        ctx, applicant=applicant, parcel_id="P-300", planned=(("COVER_CROP", 10),),
        self_reported_answers={"SOIL_HEALTH": 20},
        verified_answers={"SOIL_HEALTH": 20},
    )
    app_b = ctx["application"]
    close_program(ctx["program"]["id"])
    run_ranking(ctx["program"]["id"])

    contract_a = create_contract_for(app_a["id"])
    item_a = add_item_with_deadline(ctx, contract_a, "2027-03-01T00:00:00Z")
    obligate(contract_a["id"])
    contract_b = create_contract_for(app_b["id"])
    item_b = add_item_with_deadline(ctx, contract_b, "2032-06-01T00:00:00Z")
    obligate(contract_b["id"])

    set_clock("2026-10-01T00:00:00Z")
    install(item_a["id"], applicant["id"])
    certify(item_a["id"], 10)
    install(item_b["id"], applicant["id"])

    # Second certification one month into the first obligation's interval.
    set_clock("2026-11-01T00:00:00Z")
    resp = api.certify_item(
        item_b["id"], {"certified_quantity": 10}, TEST_USERS["planner_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_OBLIGATION_OVERLAP)


def test_obligation_adjacent_certification_allowed(api):
    """PRD §3.5: "Obligation intervals are half-open — an existing obligation
    whose `end_date` is exactly the new certification instant does not block —
    and a genuine overlap is rejected with `ERR_OBLIGATION_OVERLAP`
    (HTTP 409)." PRD §3.5: "the sweep of §2.7 marks the obligation `SATISFIED`
    once the clock reaches or passes `end_date` — at exactly `end_date` the
    obligation is already satisfied."

    Design: Difficulty/resource_temporal_overlap/obligation_overlap_half_open_adjacency
    """
    ctx = setup_open_program(rates=(("COVER_CROP", "ACRE", 15000, 18000, 5),))
    applicant = register_applicant(parcel_ids=("P-300", "P-301"))
    ctx = setup_screened_application(
        ctx, applicant=applicant, parcel_id="P-300", planned=(("COVER_CROP", 10),),
        self_reported_answers={"SOIL_HEALTH": 30},
        verified_answers={"SOIL_HEALTH": 30},
    )
    app_a = ctx["application"]
    ctx = setup_screened_application(
        ctx, applicant=applicant, parcel_id="P-300", planned=(("COVER_CROP", 10),),
        self_reported_answers={"SOIL_HEALTH": 20},
        verified_answers={"SOIL_HEALTH": 20},
    )
    app_b = ctx["application"]
    close_program(ctx["program"]["id"])
    run_ranking(ctx["program"]["id"])

    contract_a = create_contract_for(app_a["id"])
    item_a = add_item_with_deadline(ctx, contract_a, "2027-03-01T00:00:00Z")
    obligate(contract_a["id"])
    contract_b = create_contract_for(app_b["id"])
    item_b = add_item_with_deadline(ctx, contract_b, "2032-06-01T00:00:00Z")
    obligate(contract_b["id"])

    set_clock("2026-10-01T00:00:00Z")
    install(item_a["id"], applicant["id"])
    certify(item_a["id"], 10)
    install(item_b["id"], applicant["id"])

    # Advance to exactly the first obligation's end_date: 2026-10-01 + 5*365d.
    set_clock("2031-09-30T00:00:00Z")
    obl1 = list_obligations_for_item(item_a["id"])[0]
    assert_instant_equal(obl1["end_date"], "2031-09-30T00:00:00Z", "obligation 1 end")
    assert obl1["status"] == "SATISFIED", (
        "sweep marks the obligation SATISFIED once the clock reaches end_date"
    )

    # Certifying at exactly that instant is adjacent, not overlapping.
    certified = certify(item_b["id"], 10)
    assert certified["certification_status"] == "CERTIFIED"

    obl2 = list_obligations_for_item(item_b["id"])[0]
    assert obl2["status"] == "ACTIVE"
    # 2031-09-30 + 5*365 days = 2036-09-28.
    assert_instant_equal(obl2["end_date"], "2036-09-28T00:00:00Z", "obligation 2 end")


def add_item_with_deadline(ctx, contract, deadline, code="COVER_CROP", qty=10):
    from test_helpers import add_item
    return add_item(contract["id"], code, qty, deadline)


def test_immediate_read_after_write_visibility(api):
    """PRD §2.4: "Any mutation described in §3 — including side effects that
    land on a resource other than the one named in the request — refreshes
    that resource's `updated_at` and increments its `version`." PRD §2.7: "At
    server startup the logical clock reads exactly 2026-08-01T00:00:00Z, and
    the server never falls back to the host's wall clock."

    Design: Corner/consistency_model/immediate_read_after_write_visibility
    """
    ctx = setup_obligated_contract()
    # The obligate mutation is visible in the very next pool read.
    pool = get_pool(ctx["pool"]["id"])
    assert pool["obligated_cents"] == 300000
    assert pool["available_cents"] == 700000

    install(ctx["item"]["id"], ctx["applicant"]["id"])
    certified = certify(ctx["item"]["id"], 1000)
    assert certified["certification_status"] == "CERTIFIED"
    # No clock-set in this chain: certification stamps the startup clock.
    assert_instant_equal(certified["certified_at"], "2026-08-01T00:00:00Z", "certified_at")

    # The side-effect obligation row is visible immediately.
    obligations = list_obligations_for_item(ctx["item"]["id"])
    assert len(obligations) == 1
    assert obligations[0]["status"] == "ACTIVE"
