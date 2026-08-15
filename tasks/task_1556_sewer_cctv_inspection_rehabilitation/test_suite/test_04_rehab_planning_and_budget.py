"""Rehab planning: method compatibility, plan uniqueness, budget ledger, OCC guards."""
from test_helpers import (
    ApiErrorId,
    add_defects,
    add_line_item,
    approve_plan,
    create_district,
    create_open_cycle,
    create_plan,
    create_segment,
    create_technician,
    create_work_order,
    drive_inspection_to_coding,
    get_district,
    get_plan,
    get_segment,
    make_coder_headers,
    propose_plan,
    schedule_inspection,
    set_clock,
    setup_certified_segment,
    setup_plan_with_work_order,
    submit_for_qa,
    validate_error,
    validate_success,
    TEST_USERS,
)

ENGINEER = TEST_USERS["engineer_headers"]


def test_plan_propose_rejected_until_basis_certified(api):
    """PRD §3.4: "The basis inspection must be `CERTIFIED`
    (`ERR_BASIS_NOT_CERTIFIED`), and the chosen method must be compatible with the
    segment's certified grades (`ERR_METHOD_INCOMPATIBLE`):"

    Design: Difficulty/cross_entity_state_dependency/plan_propose_gated_on_inspection_certified
    """
    set_clock("2026-08-10T00:00:00Z")
    district = create_district(name="D-XD2", ii_reduction_target_pct=25, budget_cents=100000000)
    coder = create_technician(["CODER"])
    create_technician(["QA_REVIEWER"])
    cycle = create_open_cycle(district["id"])
    segment = create_segment(district["id"], segment_ref="MH-31->MH-32")
    inspection = schedule_inspection(segment["id"], cycle["id"], coder["id"])
    drive_inspection_to_coding(inspection["id"], coder["id"])
    add_defects(inspection["id"], coder["id"],
                [{"pacp_code": "CRK", "family": "STRUCTURAL", "grade": 3,
                  "distance_m": 10, "clock_position": 6}])
    submit_for_qa(inspection["id"], coder["id"])  # QA_REVIEW, not CERTIFIED

    plan = create_plan(segment["id"], inspection["id"], "SPOT_REPAIR")
    resp = api.propose_plan(plan["id"], ENGINEER)
    validate_error(resp, ApiErrorId.ERR_BASIS_NOT_CERTIFIED)


def test_plan_propose_succeeds_after_certification(api):
    """PRD §3.4: "The basis inspection must be `CERTIFIED`
    (`ERR_BASIS_NOT_CERTIFIED`), and the chosen method must be compatible with the
    segment's certified grades (`ERR_METHOD_INCOMPATIBLE`):"

    Design: Difficulty/cross_entity_state_dependency/plan_propose_gated_on_inspection_certified
    """
    ctx = setup_certified_segment()  # grade-3 structural point defect, CERTIFIED
    plan = create_plan(ctx["segment"]["id"], ctx["inspection"]["id"], "SPOT_REPAIR")
    resp = api.propose_plan(plan["id"], ENGINEER)
    data = validate_success(resp, 200)
    assert data["status"] == "PROPOSED"


def test_method_incompatible_spot_repair_on_grade5(api):
    """PRD §3.4: "`SPOT_REPAIR` is allowed only when the segment's `structural_grade`
    is at most 3 and the basis inspection contains exactly one or two structural
    observations graded 3 or worse — spot repair is a surgical technique, not a
    systemic one."

    Design: Corner/validations/method_incompatible_spot_repair_on_grade5
    """
    ctx = setup_certified_segment(defects=[
        {"pacp_code": "B", "family": "STRUCTURAL", "grade": 5,
         "distance_m": 10, "clock_position": 12}
    ])
    assert ctx["segment"]["structural_grade"] == 5
    plan = create_plan(ctx["segment"]["id"], ctx["inspection"]["id"], "SPOT_REPAIR")
    resp = api.propose_plan(plan["id"], ENGINEER)
    validate_error(resp, ApiErrorId.ERR_METHOD_INCOMPATIBLE)


def test_cipp_lining_on_brick_material_rejected(api):
    """PRD §3.4: "`CIPP_LINING` requires a `structural_grade` of at least 2 and a
    segment `material` other than `BRICK`; liners cannot be cured inside brick."

    Design: Corner/validations/cipp_lining_on_brick_material_rejected
    """
    ctx = setup_certified_segment(
        material="BRICK",
        defects=[{"pacp_code": "CRK", "family": "STRUCTURAL", "grade": 2,
                  "distance_m": 10, "clock_position": 6}],
    )
    assert ctx["segment"]["structural_grade"] == 2  # grade-eligible, material is not
    plan = create_plan(ctx["segment"]["id"], ctx["inspection"]["id"], "CIPP_LINING")
    resp = api.propose_plan(plan["id"], ENGINEER)
    validate_error(resp, ApiErrorId.ERR_METHOD_INCOMPATIBLE)


def _setup_two_plans_same_segment(api):
    """District budget 500000; P1 SPOT_REPAIR approved (provisional 250000 +
    MOB_SMALL 150000 = 400000 committed); P2 proposed on the same segment.
    Approving P2 violates the uniqueness rule (P1 already APPROVED); the
    earlier check wins over any downstream fiscal evaluation."""
    ctx = setup_certified_segment(budget_cents=500000)
    crew = create_technician(["CREW_LEAD"])
    p1 = propose_plan(create_plan(ctx["segment"]["id"], ctx["inspection"]["id"], "SPOT_REPAIR")["id"])
    p1 = approve_plan(p1["id"])
    w1 = create_work_order(p1["id"], crew["id"])
    add_line_item(w1["id"], "SPOT-EA", 1, 250000)
    p2 = propose_plan(create_plan(ctx["segment"]["id"], ctx["inspection"]["id"], "SPOT_REPAIR")["id"])
    return ctx, p1, p2


def test_plan_conflict_precedes_budget_on_approve(api):
    """PRD §3.4: "First, uniqueness: the segment must have no other plan sitting in
    `PROPOSED`, `APPROVED`, or `EXECUTING` (`ERR_PLAN_CONFLICT`)."
    PRD §2.10: "The practical consequence: on a plan approval that would fail both an
    earlier business check and the budget ceiling, the client always sees the earlier
    error first; the fiscal check fires only when everything upstream of it has
    passed."
    Approving P2 fails uniqueness (P1 is APPROVED) and would also breach the budget
    (400000 + 350000 > 500000); the earlier check wins.

    Design: Difficulty/priority_pair_validation_conflict/constraint_vs_fiscal_plan_conflict_and_budget
    """
    _, _, p2 = _setup_two_plans_same_segment(api)
    current = get_plan(p2["id"])
    resp = api.approve_plan(p2["id"], {"expected_plan_version": current["version"]}, ENGINEER)
    validate_error(resp, ApiErrorId.ERR_PLAN_CONFLICT)


def test_failed_approve_leaves_plan_and_ledger_untouched(api):
    """PRD §3.4: "First, uniqueness: the segment must have no other plan sitting in
    `PROPOSED`, `APPROVED`, or `EXECUTING` (`ERR_PLAN_CONFLICT`)."
    PRD §2.10: "The practical consequence: on a plan approval that would fail both an
    earlier business check and the budget ceiling, the client always sees the earlier
    error first; the fiscal check fires only when everything upstream of it has
    passed."
    After the conflicted approval is rejected, P2 remains PROPOSED and the district
    ledger still holds exactly P1's commitment.

    Design: Difficulty/priority_pair_validation_conflict/constraint_vs_fiscal_plan_conflict_and_budget
    """
    ctx, _, p2 = _setup_two_plans_same_segment(api)
    current = get_plan(p2["id"])
    resp = api.approve_plan(p2["id"], {"expected_plan_version": current["version"]}, ENGINEER)
    validate_error(resp, ApiErrorId.ERR_PLAN_CONFLICT)
    assert get_plan(p2["id"])["status"] == "PROPOSED"
    assert get_district(ctx["district"]["id"])["budget_committed_cents"] == 400000


def test_error_budget_exceeded_on_approve(api):
    """PRD §3.4: "Third, always last, the fiscal ceiling: the plan's
    `provisional_total_cents` plus the district's `budget_committed_cents` must not
    exceed the district's `budget_cents`, or the approval fails with
    `ERR_BUDGET_EXCEEDED`."

    Design: Corner/errors/error_budget_exceeded_on_approve
    """
    # Budget 300000; one line 1 @ 250000 + MOB_SMALL 150000 -> provisional 400000.
    # Approve first so the work order can be issued (PRD §3.5), stage the line,
    # then reopen + re-propose so the plan carries that provisional total into a
    # fresh approval, where the fiscal ceiling fires.
    ctx = setup_plan_with_work_order(
        method="SPOT_REPAIR", lines=[("SPOT-EA", 1, 250000)], approve=True,
        cert_kwargs={"budget_cents": 300000},
    )
    validate_success(api.reopen_plan(ctx["plan"]["id"], ENGINEER), 200)
    validate_success(api.propose_plan(ctx["plan"]["id"], ENGINEER), 200)
    current = get_plan(ctx["plan"]["id"])
    assert current["provisional_total_cents"] == 400000
    resp = api.approve_plan(ctx["plan"]["id"], {"expected_plan_version": current["version"]}, ENGINEER)
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)


def test_occ_stale_plan_version_rejected(api):
    """PRD §2.9: "If the plan's current `version` has advanced past that value —
    because another engineer reopened or otherwise modified the plan in the meantime,
    legitimately changing its provisional total and the district's budget arithmetic —
    the approval is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is
    mutated."
    The client holds the creation-time version; the propose transition has already
    advanced the plan's version, so the approval is stale.

    Design: Corner/cross_cutting_layers/occ_stale_plan_version_rejected
    """
    ctx = setup_certified_segment()
    plan = create_plan(ctx["segment"]["id"], ctx["inspection"]["id"], "SPOT_REPAIR")
    stale_version = plan["version"]
    propose_plan(plan["id"])  # advances version past the client's captured value
    resp = api.approve_plan(plan["id"], {"expected_plan_version": stale_version}, ENGINEER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_occ_line_item_create_stale_work_order_version(api):
    """PRD §2.9: "Adding a line item to a work order likewise requires
    `expected_work_order_version`, the last observed `version` of the parent work
    order; a mismatch against the work order's current `version` is rejected with the
    same `ERR_STALE_VERSION` (HTTP 412), because provisional totals and the
    mobilization tier derive from line items and a stale writer would otherwise
    commit budget against out-of-date quantities."
    The first line-item create has already advanced the work order's version, so the
    reused creation-time version is stale on the second create.

    Design: Corner/cross_cutting_layers/occ_line_item_create_stale_work_order_version
    """
    ctx = setup_plan_with_work_order(method="SPOT_REPAIR", lines=None, approve=True)
    stale_version = ctx["work_order"]["version"]
    first = api.create_line_item(
        ctx["work_order"]["id"],
        {"pay_item_code": "SPOT-EA", "scheduled_qty": 1, "unit_price_cents": 250000,
         "expected_work_order_version": stale_version},
        ENGINEER,
    )
    validate_success(first, 201)
    resp = api.create_line_item(
        ctx["work_order"]["id"],
        {"pay_item_code": "EXC-CY", "scheduled_qty": 2, "unit_price_cents": 100000,
         "expected_work_order_version": stale_version},
        ENGINEER,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_budget_commit_on_approve(api):
    """PRD §3.4: "On success the district's `budget_committed_cents` increases by the
    plan's `provisional_total_cents` — the ledger sync — and the segment's
    `rehab_status` advances to `PLANNED`."
    One line 1 @ 250000 plus the MOB_SMALL fee 150000 commits 400000.

    Design: Difficulty/compensating_invariant/budget_commit_release_invariant_on_reopen
    """
    ctx = setup_plan_with_work_order(method="SPOT_REPAIR", lines=[("SPOT-EA", 1, 250000)],
                                     approve=True)
    district = get_district(ctx["district"]["id"])
    assert district["budget_committed_cents"] == 400000
    assert get_plan(ctx["plan"]["id"])["status"] == "APPROVED"
    assert get_segment(ctx["segment"]["id"])["rehab_status"] == "PLANNED"


def test_budget_release_on_reopen_restores_invariant(api):
    """PRD §3.4: "A successful reopen writes the compensating ledger entry: the
    district's `budget_committed_cents` decreases by the plan's
    `provisional_total_cents`, and the segment's `rehab_status` returns to `NONE`
    provided no other `APPROVED` or `EXECUTING` plan remains for it."
    Approve-then-reopen is compensating: the commitment ledger returns to exactly
    its pre-approval value with zero drift.

    Design: Difficulty/compensating_invariant/budget_commit_release_invariant_on_reopen
    """
    ctx = setup_plan_with_work_order(method="SPOT_REPAIR", lines=[("SPOT-EA", 1, 250000)],
                                     approve=True)
    assert get_district(ctx["district"]["id"])["budget_committed_cents"] == 400000
    resp = api.reopen_plan(ctx["plan"]["id"], ENGINEER)
    data = validate_success(resp, 200)
    assert data["status"] == "DRAFT"
    assert get_district(ctx["district"]["id"])["budget_committed_cents"] == 0
    assert get_segment(ctx["segment"]["id"])["rehab_status"] == "NONE"


def test_coder_cannot_approve_rehab_plan(api):
    """PRD §2.1: "A properly identified caller who attempts an operation their role
    is not permitted to perform is rejected with `ERR_UNAUTHORIZED` (HTTP 403); the
    per-endpoint role assignments are enumerated in §4."
    Plan approval is a DistrictEngineer operation (§4).

    Design: Corner/rbac/coder_cannot_approve_rehab_plan
    """
    ctx = setup_plan_with_work_order(method="SPOT_REPAIR", lines=None, approve=False)
    current = get_plan(ctx["plan"]["id"])
    resp = api.approve_plan(
        ctx["plan"]["id"], {"expected_plan_version": current["version"]},
        make_coder_headers(ctx["coder"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
