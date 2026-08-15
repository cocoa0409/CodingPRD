"""Payment request pipeline, sampling gate, segregation, and revocation cascade."""
from test_helpers import (
    ApiErrorId,
    add_item,
    assert_instant_equal,
    assert_pool_invariants,
    certify,
    close_program,
    create_contract_for,
    create_request,
    get_item,
    get_pool,
    get_request,
    install,
    list_obligations_for_item,
    make_applicant_headers,
    make_payment_officer_headers,
    make_planner_headers,
    make_qa_headers,
    obligate,
    open_spot_check,
    record_spot_result,
    register_applicant,
    review_request,
    approve_request,
    run_ranking,
    set_clock,
    setup_certified_item,
    setup_disbursed_request,
    setup_obligated_contract,
    setup_open_program,
    setup_screened_application,
    TEST_USERS,
    api_client,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
PLANNER = TEST_USERS["planner_headers"]
PLANNER2 = TEST_USERS["planner2_headers"]
PO = TEST_USERS["po_headers"]
QA = TEST_USERS["qa_headers"]
QA2 = TEST_USERS["qa2_headers"]


# ---------------------------------------------------------------------------
# Payment request <-> item certification dependency
# ---------------------------------------------------------------------------

def test_payment_request_rejected_while_item_only_installed(api):
    """PRD §3.7: "The item must be `CERTIFIED` (`ERR_ITEM_NOT_CERTIFIED`,
    HTTP 409), the contract must be `OBLIGATED` (`ERR_CONTRACT_NOT_PAYABLE`),
    and the item must have no other payment request in flight".

    Design: Difficulty/cross_entity_state_dependency/payment_request_requires_item_certified
    """
    ctx = setup_obligated_contract()
    install(ctx["item"]["id"], ctx["applicant"]["id"])

    resp = api.create_payment_request(
        {
            "contract_id": ctx["contract"]["id"],
            "practice_item_id": ctx["item"]["id"],
            "documented_cost_cents": 350000,
            "documentation_refs": ["r1"],
        },
        make_applicant_headers(ctx["applicant"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ITEM_NOT_CERTIFIED)


def test_payment_request_computes_amount_after_certification(api):
    """PRD §3.7: "The item must be `CERTIFIED` (`ERR_ITEM_NOT_CERTIFIED`,
    HTTP 409)". PRD §3.7: "The `computed_amount_cents` is the smaller of two
    figures: the item's `certified_quantity` multiplied by its snapshotted
    `applicable_rate_cents`, rounded half-up to whole cents; and the producer's
    `documented_cost_cents`."

    Design: Difficulty/cross_entity_state_dependency/payment_request_requires_item_certified
    """
    ctx = setup_obligated_contract()
    install(ctx["item"]["id"], ctx["applicant"]["id"])
    certify(ctx["item"]["id"], 1000)

    request = create_request(
        ctx["contract"]["id"], ctx["item"]["id"], ctx["applicant"]["id"],
        documented_cost_cents=350000,
    )
    # min(round_half_up(1000 * 300), 350000) = 300000.
    assert request["computed_amount_cents"] == 300000


# ---------------------------------------------------------------------------
# Dual-variant money: scheduled estimate vs certified final
# ---------------------------------------------------------------------------

def test_scheduled_estimate_uses_planned_quantity_and_hu_snapshot(api):
    """PRD §3.4: "The item's `scheduled_amount_cents` is then its
    `planned_quantity` multiplied by the snapshotted rate, rounded half-up to
    whole cents." and "snapshots the item's `applicable_rate_cents`: the
    schedule's `hu_rate_cents` if and only if the contract's applicant is
    historically underserved at the moment of item creation, otherwise
    `standard_rate_cents`."

    Design: Difficulty/dual_variant_calc/scheduled_vs_certified_payment_divergence
    """
    ctx = setup_obligated_contract(
        pools=(("HU_LIMITED_RESOURCE", 500000),),
        hu_category="LIMITED_RESOURCE",
        parcel_ids=("P-200",),
        legal_name="H U",
    )
    item = ctx["item"]
    assert item["applicable_rate_cents"] == 360, "HU rate snapshot frozen on the item"
    # scheduled_estimate: 1000 ft x 360 = 360000.
    assert item["scheduled_amount_cents"] == 360000


def test_certified_payment_uses_certified_quantity_and_doc_cap(api):
    """PRD §3.7: "The `computed_amount_cents` is the smaller of two figures:
    the item's `certified_quantity` multiplied by its snapshotted
    `applicable_rate_cents`, rounded half-up to whole cents; and the producer's
    `documented_cost_cents`."

    Design: Difficulty/dual_variant_calc/scheduled_vs_certified_payment_divergence
    """
    ctx = setup_obligated_contract(
        pools=(("HU_LIMITED_RESOURCE", 500000),),
        hu_category="LIMITED_RESOURCE",
        parcel_ids=("P-200",),
        legal_name="H U",
    )
    install(ctx["item"]["id"], ctx["applicant"]["id"])
    certify(ctx["item"]["id"], 900)
    request = create_request(
        ctx["contract"]["id"], ctx["item"]["id"], ctx["applicant"]["id"],
        documented_cost_cents=400000,
    )
    # certified_final: min(round_half_up(900 * 360), 400000) = 324000.
    assert request["computed_amount_cents"] == 324000
    assert request["computed_amount_cents"] != ctx["item"]["scheduled_amount_cents"], (
        "scheduled estimate (360000) and certified final (324000) diverge on one item"
    )


def test_documented_cost_cap_binds(api):
    """PRD §3.7: "The `computed_amount_cents` is the smaller of two figures:
    the item's `certified_quantity` multiplied by its snapshotted
    `applicable_rate_cents`, rounded half-up to whole cents; and the producer's
    `documented_cost_cents`."

    Design: Difficulty/combinatorial_formula/certified_payment_documented_cap_min_interaction
    """
    ctx = setup_certified_item(certified_quantity=900)
    request = create_request(
        ctx["contract"]["id"], ctx["item"]["id"], ctx["applicant"]["id"],
        documented_cost_cents=200000,
    )
    # min(round(900 * 300) = 270000, 200000) = 200000: the documented cap binds.
    assert request["computed_amount_cents"] == 200000


def test_rate_product_binds_when_documented_cost_higher(api):
    """PRD §3.7: "The `computed_amount_cents` is the smaller of two figures:
    the item's `certified_quantity` multiplied by its snapshotted
    `applicable_rate_cents`, rounded half-up to whole cents; and the producer's
    `documented_cost_cents`."

    Design: Difficulty/combinatorial_formula/certified_payment_documented_cap_min_interaction
    """
    ctx = setup_certified_item(certified_quantity=900)
    request = create_request(
        ctx["contract"]["id"], ctx["item"]["id"], ctx["applicant"]["id"],
        documented_cost_cents=400000,
    )
    # min(round(900 * 300) = 270000, 400000) = 270000: the rate product binds.
    assert request["computed_amount_cents"] == 270000


# ---------------------------------------------------------------------------
# Pipeline state guards and input validation
# ---------------------------------------------------------------------------

def test_disburse_under_review_rejected(api):
    """PRD §3.7: "Disbursement converts an `APPROVED` request into cash — any
    other state meets `ERR_REQUEST_NOT_APPROVED` (HTTP 409)".

    Design: Corner/state_machines/disburse_under_review_request_rejected
    """
    ctx = setup_certified_item(certified_quantity=1000)
    request = create_request(
        ctx["contract"]["id"], ctx["item"]["id"], ctx["applicant"]["id"],
        documented_cost_cents=300000,
    )
    review_request(request["id"])

    resp = api.disburse_payment_request(request["id"], PO)
    validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_APPROVED)

    pool = get_pool(ctx["pool"]["id"])
    assert pool["paid_cents"] == 0, "no partial effects from a rejected disbursement"
    assert pool["obligated_cents"] == 300000


def test_documentation_empty_rejected(api):
    """PRD §3.7: "`documentation_refs`, the receipt and photo references that
    must number at least one (an empty list is rejected with
    `ERR_DOCUMENTATION_INCOMPLETE`, HTTP 422)."

    Design: Corner/validations/documentation_empty_rejected
    """
    ctx = setup_certified_item(certified_quantity=1000)
    resp = api.create_payment_request(
        {
            "contract_id": ctx["contract"]["id"],
            "practice_item_id": ctx["item"]["id"],
            "documented_cost_cents": 300000,
            "documentation_refs": [],
        },
        make_applicant_headers(ctx["applicant"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DOCUMENTATION_INCOMPLETE)


def test_duplicate_active_payment_request_rejected(api):
    """PRD §3.7: "the item must have no other payment request in flight — any
    existing request in `SUBMITTED`, `UNDER_REVIEW`, `APPROVED`, or `DISBURSED`
    blocks creation with `ERR_PAYMENT_REQUEST_ACTIVE` (HTTP 409)." PRD §3.7:
    "receives a `sequence_number`: one plus the count of all payment requests
    already existing for that program, regardless of status, assigned in
    creation order starting from 1."

    Design: Corner/validations/duplicate_active_payment_request_rejected
    """
    ctx = setup_certified_item(certified_quantity=1000)
    applicant_id = ctx["applicant"]["id"]
    first = create_request(ctx["contract"]["id"], ctx["item"]["id"], applicant_id,
                           documented_cost_cents=300000)

    dup = api.create_payment_request(
        {
            "contract_id": ctx["contract"]["id"],
            "practice_item_id": ctx["item"]["id"],
            "documented_cost_cents": 299999,
            "documentation_refs": ["r2"],
        },
        make_applicant_headers(applicant_id),
    )
    validate_error(dup, ApiErrorId.ERR_PAYMENT_REQUEST_ACTIVE)

    # REJECTED is terminal, not active: a fresh request succeeds afterwards.
    review_request(first["id"])
    validate_success(api.reject_payment_request(first["id"], PO), 200)
    second = create_request(ctx["contract"]["id"], ctx["item"]["id"], applicant_id,
                            documented_cost_cents=299999, documentation_refs=("r2",))
    assert second["sequence_number"] == 2, "sequence numbers are never reused"


# ---------------------------------------------------------------------------
# Sampling gate
# ---------------------------------------------------------------------------

def test_sampling_modulus_boundary_and_gate(api):
    """PRD §3.7: "The `sampled` flag is set when the sequence number is an
    exact multiple of the program's `spot_check_modulus` — under the default
    modulus of five, requests numbered 5, 10, 15, and so on are sampled, while
    requests 4 and 6 are not — and a sampled request may not be disbursed until
    a spot check gates it through." PRD §3.7: "If the request was `sampled`, a
    spot check linked to this very request and standing in `PASSED` must exist;
    a pending or failed check satisfies nothing, and the disbursement is
    rejected with `ERR_SPOT_CHECK_REQUIRED` (HTTP 409)."

    Design: Corner/calculations/spot_check_sampling_modulus_boundary
    """
    ctx = _setup_four_practice_program(api)
    applicant_id = ctx["applicant"]["id"]
    item_ids = [item["id"] for item in ctx["items"]]
    quantities = [100, 10, 1, 5]
    for item_id, qty in zip(item_ids, quantities):
        install(item_id, applicant_id)
        certify(item_id, qty)

    documented = [30000, 150000, 250000, 20000]
    requests = [
        create_request(ctx["contract"]["id"], item_id, applicant_id, documented_cost)
        for item_id, documented_cost in zip(item_ids, documented)
    ]
    # Boundary: with modulus 3 only sequence 3 is sampled (1, 2, 4 are not).
    assert requests[0]["sequence_number"] == 1 and requests[0]["sampled"] is False
    assert requests[1]["sampled"] is False
    assert requests[2]["sequence_number"] == 3 and requests[2]["sampled"] is True
    assert requests[3]["sampled"] is False

    # Non-sampled request disburses with no spot check at all.
    review_request(requests[0]["id"])
    approve_request(requests[0]["id"])
    d1 = disburse_and_assert(requests[0]["id"])
    assert d1["status"] == "DISBURSED"

    # Sampled request is blocked until a linked PASSED spot check exists.
    review_request(requests[2]["id"])
    approve_request(requests[2]["id"])
    blocked = api.disburse_payment_request(requests[2]["id"], PO)
    validate_error(blocked, ApiErrorId.ERR_SPOT_CHECK_REQUIRED)

    spot_check = open_spot_check(
        ctx["contract"]["id"], item_ids[2], payment_request_id=requests[2]["id"]
    )
    record_spot_result(spot_check["id"], "PASS")
    disbursed = disburse_and_assert(requests[2]["id"])
    assert disbursed["status"] == "DISBURSED"
    assert disbursed["disbursed_amount_cents"] == 250000


def _setup_four_practice_program(api):
    from test_helpers import build_contract
    ctx = setup_open_program(
        spot_check_modulus=3,
        rates=(
            ("FENCE", "FOOT", 300, 360, 10),
            ("COVER_CROP", "ACRE", 15000, 18000, 5),
            ("WATERING_FACILITY", "EACH", 250000, 300000, 10),
            ("NUTRIENT_MANAGEMENT", "ACRE", 4000, 4800, 1),
        ),
    )
    ctx = setup_screened_application(
        ctx,
        planned=(
            ("FENCE", 100),
            ("COVER_CROP", 10),
            ("WATERING_FACILITY", 1),
            ("NUTRIENT_MANAGEMENT", 5),
        ),
    )
    close_program(ctx["program"]["id"])
    run_ranking(ctx["program"]["id"])
    ctx = build_contract(
        ctx, ctx["application"]["id"],
        items=(
            ("FENCE", 100),
            ("COVER_CROP", 10),
            ("WATERING_FACILITY", 1),
            ("NUTRIENT_MANAGEMENT", 5),
        ),
    )
    ctx["contract"] = obligate(ctx["contract"]["id"])
    return ctx


def disburse_and_assert(request_id):
    resp = api_client.disburse_payment_request(request_id, PO)
    assert resp.status_code == 200, f"disburse failed: {resp.status_code}: {resp.text}"
    return validate_success(resp, 200)


# ---------------------------------------------------------------------------
# Priority: safety gate vs certification freshness
# ---------------------------------------------------------------------------

def _setup_sampled_and_stale(api):
    """Two contracts, each with a FENCE 100 item certified at 2026-10-01.
    R1 (sequence 1, modulus 2 -> not sampled) is DISBURSED. R2 (sequence 2 ->
    sampled, no spot check) is APPROVED. Clock then moves to 2027-10-02, one
    day past the 365-day freshness window."""
    from test_helpers import build_contract
    ctx = setup_open_program(spot_check_modulus=2)
    applicant = register_applicant(parcel_ids=("P-100", "P-101"))
    ctx = setup_screened_application(
        ctx, applicant=applicant, parcel_id="P-100", planned=(("FENCE", 100),),
        self_reported_answers={"SOIL_HEALTH": 30},
        verified_answers={"SOIL_HEALTH": 30},
    )
    app_a = ctx["application"]
    ctx = setup_screened_application(
        ctx, applicant=applicant, parcel_id="P-101", planned=(("FENCE", 100),),
        self_reported_answers={"SOIL_HEALTH": 20},
        verified_answers={"SOIL_HEALTH": 20},
    )
    app_b = ctx["application"]
    close_program(ctx["program"]["id"])
    run_ranking(ctx["program"]["id"])

    contracts = {}
    items = {}
    for key, app in (("a", app_a), ("b", app_b)):
        ctx = build_contract(ctx, app["id"], items=(("FENCE", 100, "2027-12-01T00:00:00Z"),))
        contracts[key] = ctx["contract"]
        items[key] = ctx["item"]
        obligate(ctx["contract"]["id"])

    set_clock("2026-10-01T00:00:00Z")
    for key in ("a", "b"):
        install(items[key]["id"], applicant["id"])
        certify(items[key]["id"], 100)

    r1 = create_request(contracts["a"]["id"], items["a"]["id"], applicant["id"],
                        documented_cost_cents=30000)
    review_request(r1["id"])
    approve_request(r1["id"])
    d1 = disburse_and_assert(r1["id"])
    assert d1["status"] == "DISBURSED"

    r2 = create_request(contracts["b"]["id"], items["b"]["id"], applicant["id"],
                        documented_cost_cents=30000)
    review_request(r2["id"])
    approve_request(r2["id"])

    set_clock("2027-10-02T00:00:00Z")
    return ctx, contracts, items, r1, r2


def test_sampled_stale_disburse_reports_spot_check_gate(api):
    """PRD §3.7: "If the request was `sampled`, a spot check linked to this
    very request and standing in `PASSED` must exist; a pending or failed check
    satisfies nothing, and the disbursement is rejected with
    `ERR_SPOT_CHECK_REQUIRED` (HTTP 409)." PRD §2.6: "A request that fails both
    a state check and a fiscal check therefore reports the state error, and so
    on down the ladder; lower rungs are evaluated only when every higher rung
    has passed." (Ladder: the spot-check gate is item 7; clock-dependent rules
    are item 9.)

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_on_sampled_stale_disburse
    """
    _, _, _, r1, r2 = _setup_sampled_and_stale(api)
    assert r1["sequence_number"] == 1 and r1["sampled"] is False
    assert r2["sequence_number"] == 2 and r2["sampled"] is True, (
        "modulus 2 samples every second request"
    )

    resp = api.disburse_payment_request(r2["id"], PO)
    validate_error(resp, ApiErrorId.ERR_SPOT_CHECK_REQUIRED)


def test_spot_check_gate_precedes_certification_freshness(api):
    """PRD §2.6 lists, in order: "7. The sampled-request spot-check gate at
    disbursement — `ERR_SPOT_CHECK_REQUIRED`." then "9. Clock-dependent rules —
    the submission window, implementation deadlines, extension windows, and
    certification freshness, evaluated on the submission, installation-report,
    certification, modification, and disbursement workflows." and "A request
    that fails both a state check and a fiscal check therefore reports the
    state error, and so on down the ladder; lower rungs are evaluated only when
    every higher rung has passed." PRD §3.7: "the disbursement must occur at or
    before the instant exactly 365 days after the item's `certified_at`; a
    later attempt fails with `ERR_CERTIFICATION_STALE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_on_sampled_stale_disburse
    """
    ctx, contracts, items, _, r2 = _setup_sampled_and_stale(api)

    # The sweep left both items CERTIFIED (deadline 2027-12-01 not breached),
    # so exactly two disbursement gates fail for R2: sampled-without-PASS and
    # certification older than 365 days (certified 2026-10-01, disbursing
    # 2027-10-02).
    assert get_item(items["a"]["id"])["certification_status"] == "CERTIFIED"
    assert get_item(items["b"]["id"])["certification_status"] == "CERTIFIED"

    resp = api.disburse_payment_request(r2["id"], PO)
    error = validate_error(resp, ApiErrorId.ERR_SPOT_CHECK_REQUIRED)
    assert error["error_id"] != "ERR_CERTIFICATION_STALE", (
        "the safety gate (item 7) reports before the temporal gate (item 9)"
    )


# ---------------------------------------------------------------------------
# Spot check state machine and segregation
# ---------------------------------------------------------------------------

def test_spot_check_terminal_lockdown(api):
    """PRD §3.7: "Recording the result belongs to the same officer who opened
    the check: the actor must equal `inspector_user_id`
    (`ERR_INSPECTOR_MISMATCH`, HTTP 403), must differ from the item's certifier
    (`ERR_SEGREGATION_OF_DUTIES`), and the check must still be `PENDING`
    (`ERR_SPOT_CHECK_NOT_PENDING`, HTTP 409)."

    Design: Corner/state_machines/spot_check_terminal_lockdown
    """
    ctx = setup_certified_item(certified_quantity=1000)
    spot_check = open_spot_check(ctx["contract"]["id"], ctx["item"]["id"])
    passed = record_spot_result(spot_check["id"], "PASS")
    assert passed["status"] == "PASSED"

    replay = api.record_spot_check_result(spot_check["id"], {"result": "PASS"}, QA)
    validate_error(replay, ApiErrorId.ERR_SPOT_CHECK_NOT_PENDING)


def test_planner_cannot_disburse(api):
    """PRD §2.1: "Each write endpoint admits a fixed set of roles (§4); a
    request whose role is not among them is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)." PRD §4: the disburse endpoint admits
    only PaymentOfficer.

    Design: Corner/rbac/planner_cannot_disburse_payment
    """
    ctx = setup_certified_item(certified_quantity=1000)
    request = create_request(ctx["contract"]["id"], ctx["item"]["id"],
                             ctx["applicant"]["id"], documented_cost_cents=300000)
    review_request(request["id"])
    approve_request(request["id"])

    resp = api.disburse_payment_request(request["id"], PLANNER2)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_approve_by_certifier_segregation_rejected(api):
    """PRD §2.11: "The payment officer who approves a payment request must not
    be the planner who certified the underlying practice item: the approver's
    `X-User-ID` is compared to the item's `certified_by_user_id`, and a match
    is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/segregation_approve_by_certifier_rejected
    """
    ctx = setup_certified_item(certified_quantity=1000)
    request = create_request(ctx["contract"]["id"], ctx["item"]["id"],
                             ctx["applicant"]["id"], documented_cost_cents=300000)
    review_request(request["id"])

    # A payment officer who IS the certifying planner (planner-1) is rejected.
    resp = api.approve_payment_request(
        request["id"], make_payment_officer_headers("planner-1")
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    approved = validate_success(api.approve_payment_request(request["id"], PO), 200)
    assert approved["status"] == "APPROVED"


def test_spot_check_result_by_certifier_segregation_rejected(api):
    """PRD §2.11: "The quality-assurance officer recording a spot-check result
    must likewise differ from the certifying planner — a match again yields
    `ERR_SEGREGATION_OF_DUTIES` — and must additionally be the same officer who
    opened the check: the actor's `X-User-ID` must equal the spot check's
    `inspector_user_id`, or the recording is rejected with
    `ERR_INSPECTOR_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/segregation_spot_checker_is_certifier_rejected
    """
    ctx = setup_certified_item(certified_quantity=1000)
    # The QA officer opening the check is the same person who certified.
    spot_check = open_spot_check(
        ctx["contract"]["id"], ctx["item"]["id"], qa_user="planner-1"
    )
    resp = api.record_spot_check_result(
        spot_check["id"], {"result": "PASS"}, make_qa_headers("planner-1")
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


def test_spot_check_inspector_mismatch_rejected(api):
    """PRD §2.11: "the actor's `X-User-ID` must equal the spot check's
    `inspector_user_id`, or the recording is rejected with
    `ERR_INSPECTOR_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/spot_check_inspector_mismatch_rejected
    """
    ctx = setup_certified_item(certified_quantity=1000)
    spot_check = open_spot_check(ctx["contract"]["id"], ctx["item"]["id"], qa_user="qa-1")
    # qa-2 is neither the inspector (qa-1) nor the certifier (planner-1).
    resp = api.record_spot_check_result(spot_check["id"], {"result": "PASS"}, QA2)
    validate_error(resp, ApiErrorId.ERR_INSPECTOR_MISMATCH)


# ---------------------------------------------------------------------------
# Revocation cascade
# ---------------------------------------------------------------------------

def _setup_disbursed_then_fail(api):
    """DISBURSED request (300000), then a FAIL spot check at 2026-10-05."""
    ctx = setup_disbursed_request(
        certified_quantity=1000, documented_cost_cents=350000, spot_check_modulus=5
    )
    request = ctx["request"]
    assert request["sequence_number"] == 1
    assert request["sampled"] is False, "first request is not sampled with modulus 5"

    set_clock("2026-10-05T00:00:00Z")
    spot_check = open_spot_check(
        ctx["contract"]["id"], ctx["item"]["id"], payment_request_id=request["id"]
    )
    failed = record_spot_result(
        spot_check["id"], "FAIL", failure_reason="practice not to spec"
    )
    assert failed["status"] == "FAILED"
    return ctx, request


def test_spot_check_fail_revokes_disbursed_request(api):
    """PRD §3.7: "When the linked request has already been `DISBURSED`, the
    failure fires a four-hop revocation cascade: the request itself moves from
    `DISBURSED` to `REVOKED`; the item's certification collapses from
    `CERTIFIED` to `CERTIFICATION_REVOKED` while its payment dimension falls
    from `PAID` to `RECOUPMENT_PENDING`, with the item's `version`
    incrementing; the item's maintenance obligation is voided, moving to
    `VOID`; and a recoupment demand is created for the revoked request's full
    `computed_amount_cents`, due thirty days out and linked through
    `payment_request_id`."

    Design: Difficulty/transitive_cascade/spot_check_failure_revocation_cascade
    """
    ctx, request = _setup_disbursed_then_fail(api)

    revoked = get_request(request["id"])
    assert revoked["status"] == "REVOKED", "hop 1: request revoked"

    item = get_item(ctx["item"]["id"])
    assert item["certification_status"] == "CERTIFICATION_REVOKED"
    assert item["payment_status"] == "RECOUPMENT_PENDING", "hop 2: item collapsed"

    obligations = list_obligations_for_item(ctx["item"]["id"])
    assert obligations[0]["status"] == "VOID", "hop 3: obligation voided"

    from test_helpers import list_demands
    demands = list_demands(payment_request_id=request["id"])
    assert len(demands) == 1, "hop 4: one demand created"
    demand = demands[0]
    assert demand["amount_cents"] == 300000, "demand carries computed_amount_cents"
    assert demand["status"] == "DEMANDED"
    # Failure clock 2026-10-05 + 30 days.
    assert_instant_equal(demand["due_date"], "2026-11-04T00:00:00Z", "demand due_date")


def test_revoked_funds_return_only_on_demand_payment(api):
    """PRD §3.7: "Critically, the pool's funds are not restored at revocation
    time — they come back only when the producer pays the demand (§3.8)." PRD
    §3.8: "A paid demand restores the pool, reducing `paid_cents` by the
    recovered amount; moves the linked item from `RECOUPMENT_PENDING` to
    `RECOUPED`, the payment dimension's terminal state".

    Design: Difficulty/transitive_cascade/spot_check_failure_revocation_cascade
    """
    ctx, request = _setup_disbursed_then_fail(api)

    pool = get_pool(ctx["pool"]["id"])
    assert pool["paid_cents"] == 300000, "cascade itself restores nothing"
    assert pool["obligated_cents"] == 0
    assert pool["available_cents"] == 700000
    assert_pool_invariants(pool)

    from test_helpers import list_demands
    demand = list_demands(payment_request_id=request["id"])[0]
    paid = validate_success(
        api.pay_recoupment_demand(
            demand["id"], {"amount_cents": 300000},
            make_applicant_headers(ctx["applicant"]["id"]),
        ),
        200,
    )
    assert paid["status"] == "PAID"

    item = get_item(ctx["item"]["id"])
    assert item["payment_status"] == "RECOUPED"

    pool_after = get_pool(ctx["pool"]["id"])
    assert pool_after["paid_cents"] == 0
    assert pool_after["available_cents"] == 1000000
    assert_pool_invariants(pool_after)
