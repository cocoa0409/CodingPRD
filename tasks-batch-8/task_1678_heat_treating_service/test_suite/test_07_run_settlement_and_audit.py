"""Run completion and abort branches, thermocouple excursion assessment,
energy-surcharge rounding order, and Nadcap audit evidence packages
(PRD §3.6, §3.9)."""
from test_helpers import (
    DEFAULT_CLOCK_ISO,
    ApiErrorId,
    TEST_USERS,
    abort_run,
    add_reading,
    assert_instant_equals,
    assign_order,
    create_audit_package,
    create_load,
    create_work_order,
    get_assignment,
    get_audit_package,
    get_work_order,
    process_order_to_processed,
    record_pyrometry,
    release_load,
    run_load_to_completed,
    setup_shop,
    start_run,
    validate_error,
    validate_success,
)

CSR = TEST_USERS["customer_service_rep"]
SCHED = TEST_USERS["shop_scheduler"]
OPERATOR = TEST_USERS["furnace_operator"]
QE = TEST_USERS["quality_engineer"]
AUDITOR = TEST_USERS["nadcap_auditor"]


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine /
# load_batch_complete_vs_abort_divergent_branches
# ---------------------------------------------------------------------------

def test_load_batch_complete_vs_abort_divergent_branches(api):
    """PRD §3.6: "Completing the run requires `RUNNING`
    (`ERR_LOAD_NOT_RUNNING`). The load becomes `COMPLETED` with `completed_at`
    stamped from the logical clock, and completion triggers two settlements."
    PRD §3.6: "Second, energy-surcharge settlement: every `ACTIVE`
    assignment's work order moves from `IN_PROCESS` to `PROCESSED` and
    receives its `energy_surcharge_cents`, computed at 133 cents per pound of
    that order's `received_weight_lb` and rounded half-up to whole cents per
    order line."
    PRD §3.6: "Aborting a run likewise requires `RUNNING`
    (`ERR_LOAD_NOT_RUNNING`). The load moves to `ABORTED`, every `ACTIVE`
    assignment flips to `REMOVED`, each affected work order returns from
    `IN_PROCESS` to `RECEIVED`, and `total_weight_lb` is recomputed — to zero,
    since no assignments remain `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/load_batch_complete_vs_abort_divergent_branches
    """
    shop = setup_shop()
    order_a = create_work_order(shop["customer"]["id"], shop["recipe"]["id"])
    order_b = create_work_order(shop["customer"]["id"], shop["recipe"]["id"])

    # Branch 1: load A runs to COMPLETED.
    load_a = create_load(
        shop["furnace"]["id"], shop["recipe"]["id"],
        scheduled_start_at="2026-08-02T08:00:00Z",
        scheduled_end_at="2026-08-02T12:00:00Z",
    )
    assign_order(load_a["id"], order_a["id"])
    completed = run_load_to_completed(load_a["id"])
    assert completed["status"] == "COMPLETED"
    assert completed["completed_at"] is not None
    wo_a = get_work_order(order_a["id"])
    assert wo_a["processing_status"] == "PROCESSED"
    assert wo_a["energy_surcharge_cents"] == 13300, (
        f"133 cents/lb x 100 lb = 13300, got {wo_a['energy_surcharge_cents']}"
    )

    # Branch 2: load B is aborted mid-run.
    load_b = create_load(
        shop["furnace"]["id"], shop["recipe"]["id"],
        scheduled_start_at="2026-08-02T13:00:00Z",
        scheduled_end_at="2026-08-02T17:00:00Z",
    )
    assignment_b = assign_order(load_b["id"], order_b["id"])
    release_load(load_b["id"])
    start_run(load_b["id"])
    assert get_work_order(order_b["id"])["processing_status"] == "IN_PROCESS"

    aborted = abort_run(load_b["id"])
    assert aborted["status"] == "ABORTED"
    assert aborted["total_weight_lb"] == 0, (
        f"abort recomputes the weight to zero, got {aborted['total_weight_lb']}"
    )
    assert get_assignment(assignment_b["id"])["status"] == "REMOVED"
    wo_b = get_work_order(order_b["id"])
    assert wo_b["processing_status"] == "RECEIVED", (
        "the abort branch reverts the order to RECEIVED instead of "
        f"processing it, got {wo_b['processing_status']}"
    )
    assert wo_b["energy_surcharge_cents"] is None


def test_aborted_load_is_terminal_and_order_reassignable(api):
    """PRD §3.6: "Aborting a run likewise requires `RUNNING`
    (`ERR_LOAD_NOT_RUNNING`). The load moves to `ABORTED`, every `ACTIVE`
    assignment flips to `REMOVED`, each affected work order returns from
    `IN_PROCESS` to `RECEIVED`, and `total_weight_lb` is recomputed — to zero,
    since no assignments remain `ACTIVE`. Both `COMPLETED` and `ABORTED` are
    terminal for the batch."
    PRD §3.5: "The order's `processing_status` must be `RECEIVED` or
    `AWAITING_RETREAT` (`ERR_WORK_ORDER_NOT_ASSIGNABLE`, HTTP 409), and the
    order's `recipe_id` must equal the load's `recipe_id`
    (`ERR_RECIPE_MISMATCH`, HTTP 422)."

    Design: Difficulty/non_linear_state_machine/load_batch_complete_vs_abort_divergent_branches
    """
    shop = setup_shop()
    order = create_work_order(shop["customer"]["id"], shop["recipe"]["id"])
    load = create_load(shop["furnace"]["id"], shop["recipe"]["id"])
    assign_order(load["id"], order["id"])
    release_load(load["id"])
    start_run(load["id"])
    abort_run(load["id"])

    # ABORTED is terminal: completing it is rejected.
    res = api.complete_run_load_batch(load["id"], OPERATOR)
    validate_error(res, ApiErrorId.ERR_LOAD_NOT_RUNNING.value)

    # The reverted order (RECEIVED) can join a fresh load.
    order_now = get_work_order(order["id"])
    assert order_now["processing_status"] == "RECEIVED"
    load2 = create_load(
        shop["furnace"]["id"], shop["recipe"]["id"],
        scheduled_start_at="2026-08-03T08:00:00Z",
        scheduled_end_at="2026-08-03T12:00:00Z",
    )
    assignment = assign_order(load2["id"], order["id"])
    assert assignment["status"] == "ACTIVE"
    assert get_work_order(order["id"])["processing_status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Corner: calculations / tc_excursion_tolerance_boundary
# ---------------------------------------------------------------------------

def test_tc_excursion_tolerance_boundary(api):
    """PRD §3.6: "First, thermocouple excursion assessment: `out_of_spec` is
    set to `true` if and only if at least one of the load's readings deviates
    from the recipe's `soak_temp_f` by more than `soak_tolerance_f` in either
    direction — a reading exactly at the tolerance band edge is within
    tolerance."

    Design: Corner/calculations/tc_excursion_tolerance_boundary
    """
    shop = setup_shop()  # soak 1650 +/- 10
    order_a = create_work_order(shop["customer"]["id"], shop["recipe"]["id"])
    order_b = create_work_order(shop["customer"]["id"], shop["recipe"]["id"])

    load_a = create_load(
        shop["furnace"]["id"], shop["recipe"]["id"],
        scheduled_start_at="2026-08-02T08:00:00Z",
        scheduled_end_at="2026-08-02T12:00:00Z",
    )
    assign_order(load_a["id"], order_a["id"])
    release_load(load_a["id"])
    start_run(load_a["id"])
    add_reading(load_a["id"], temp_f=1665)  # |1665 - 1650| = 15 > 10
    complete = validate_success(api.complete_run_load_batch(load_a["id"], OPERATOR), 200)
    assert complete["out_of_spec"] is True, "15 degrees beyond tolerance"

    load_b = create_load(
        shop["furnace"]["id"], shop["recipe"]["id"],
        scheduled_start_at="2026-08-03T08:00:00Z",
        scheduled_end_at="2026-08-03T12:00:00Z",
    )
    assign_order(load_b["id"], order_b["id"])
    release_load(load_b["id"])
    start_run(load_b["id"])
    add_reading(load_b["id"], temp_f=1660, recorded_at="2026-08-03T10:00:00Z")
    clean = validate_success(api.complete_run_load_batch(load_b["id"], OPERATOR), 200)
    assert clean["out_of_spec"] is False, (
        "a reading exactly at the band edge (1650 + 10) is within tolerance"
    )


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / energy_surcharge_round_per_order_then_sum
# ---------------------------------------------------------------------------

def test_energy_surcharge_round_per_order_then_sum(api):
    """PRD §3.6: "Second, energy-surcharge settlement: every `ACTIVE`
    assignment's work order moves from `IN_PROCESS` to `PROCESSED` and
    receives its `energy_surcharge_cents`, computed at 133 cents per pound of
    that order's `received_weight_lb` and rounded half-up to whole cents per
    order line. The load's `total_energy_surcharge_cents` is then the sum of
    those per-order rounded amounts. The rounding order is pinned: each order
    line is rounded first and the rounded values are summed — summing raw
    values and rounding once at the end produces different cents and is
    non-conformant."

    Design: Difficulty/combinatorial_formula/energy_surcharge_round_per_order_then_sum
    """
    shop = setup_shop()
    order_1 = create_work_order(
        shop["customer"]["id"], shop["recipe"]["id"], received_weight_lb=10.005
    )
    order_2 = create_work_order(
        shop["customer"]["id"], shop["recipe"]["id"], received_weight_lb=20.005
    )
    load = create_load(shop["furnace"]["id"], shop["recipe"]["id"])
    assign_order(load["id"], order_1["id"])
    assign_order(load["id"], order_2["id"])
    completed = run_load_to_completed(load["id"])

    wo_1 = get_work_order(order_1["id"])
    wo_2 = get_work_order(order_2["id"])
    assert wo_1["energy_surcharge_cents"] == 1331, (
        f"round_half_up(133 x 10.005 = 1330.665) = 1331, got "
        f"{wo_1['energy_surcharge_cents']}"
    )
    assert wo_2["energy_surcharge_cents"] == 2661, (
        f"round_half_up(133 x 20.005 = 2660.665) = 2661, got "
        f"{wo_2['energy_surcharge_cents']}"
    )
    assert completed["total_energy_surcharge_cents"] == 3992, (
        "per-line rounded sum 1331 + 2661 = 3992; rounding the raw sum "
        f"(3991.33) once would yield 3991, got "
        f"{completed['total_energy_surcharge_cents']}"
    )


def test_energy_surcharge_half_up_per_order(api):
    """PRD §3.6: "Second, energy-surcharge settlement: every `ACTIVE`
    assignment's work order moves from `IN_PROCESS` to `PROCESSED` and
    receives its `energy_surcharge_cents`, computed at 133 cents per pound of
    that order's `received_weight_lb` and rounded half-up to whole cents per
    order line."
    PRD §2.6: "Money is integer cents everywhere: quoted and final surcharges,
    energy surcharges, liability payouts, and exposure totals are whole-cent
    integers, and every rounding step called out in this document uses the
    round-half-up method."

    Design: Difficulty/combinatorial_formula/energy_surcharge_round_per_order_then_sum
    """
    # 133 x 1.5 = 199.5 exactly: round-half-up must produce 200.
    bundle = process_order_to_processed(order_overrides={"received_weight_lb": 1.5})
    assert bundle["order"]["processing_status"] == "PROCESSED"
    assert bundle["order"]["energy_surcharge_cents"] == 200, (
        f"round_half_up(199.5) = 200, got "
        f"{bundle['order']['energy_surcharge_cents']}"
    )
    assert bundle["load"]["total_energy_surcharge_cents"] == 200


# ---------------------------------------------------------------------------
# Corner: state_machines / audit_package_with_unfinished_load_rejected
# ---------------------------------------------------------------------------

def test_audit_package_with_unfinished_load_rejected(api):
    """PRD §3.9: "Every listed load must be `COMPLETED` on that furnace; a
    load in any other status, or completed on a different furnace, fails
    compilation with `ERR_LOAD_NOT_COMPLETED` (HTTP 409)."

    Design: Corner/state_machines/audit_package_with_unfinished_load_rejected
    """
    shop = setup_shop()
    order = create_work_order(shop["customer"]["id"], shop["recipe"]["id"])
    load = create_load(shop["furnace"]["id"], shop["recipe"]["id"])
    assign_order(load["id"], order["id"])
    release_load(load["id"])
    start_run(load["id"])  # RUNNING, not COMPLETED

    res = api.create_audit_package(
        {"furnace_id": shop["furnace"]["id"], "load_batch_ids": [load["id"]]},
        QE,
    )
    validate_error(res, ApiErrorId.ERR_LOAD_NOT_COMPLETED.value)


# ---------------------------------------------------------------------------
# Corner: state_machines / issued_package_locked_and_manifest_frozen
# ---------------------------------------------------------------------------

def test_issued_package_locked_and_manifest_frozen(api):
    """PRD §3.9: "At creation the server computes the `evidence_manifest` —
    an object with `load_batch_ids`, `pyrometry_record_ids`, and
    `thermocouple_reading_counts` — bundling the listed loads, the furnace's
    pyrometry records whose `performed_at` is on or before the latest listed
    load's `completed_at`, and per-load thermocouple reading counts."
    PRD §3.9: "a `NadcapAuditor` issues a package that is still in `DRAFT`
    (any other status fails with `ERR_PACKAGE_NOT_DRAFT`, HTTP 409). Issuance
    stamps `issued_at` from the logical clock, freezes the
    `evidence_manifest` immutable thereafter, and moves the package to
    `ISSUED`, which is terminal and locked."

    Design: Corner/state_machines/issued_package_locked_and_manifest_frozen
    """
    shop = setup_shop()
    furnace = shop["furnace"]
    pyro_ids = {
        r["id"]
        for r in validate_success(
            api.list_pyrometry_records(SCHED, params={"furnace_id": furnace["id"]}),
            200,
        )
    }
    assert len(pyro_ids) == 2

    order = create_work_order(shop["customer"]["id"], shop["recipe"]["id"])
    load = create_load(furnace["id"], shop["recipe"]["id"])
    assign_order(load["id"], order["id"])
    release_load(load["id"])
    start_run(load["id"])
    add_reading(load["id"], temp_f=1650)
    validate_success(api.complete_run_load_batch(load["id"], OPERATOR), 200)

    package = create_audit_package(furnace["id"], [load["id"]])
    assert package["status"] == "DRAFT"
    assert package.get("issued_at") is None
    manifest = package["evidence_manifest"]
    assert manifest["load_batch_ids"] == [load["id"]]
    assert set(manifest["pyrometry_record_ids"]) == pyro_ids

    issued = validate_success(api.issue_audit_package(package["id"], AUDITOR), 200)
    assert issued["status"] == "ISSUED"

    # Terminal: a second issue is rejected.
    res = api.issue_audit_package(package["id"], AUDITOR)
    validate_error(res, ApiErrorId.ERR_PACKAGE_NOT_DRAFT.value)

    # The manifest is frozen: later pyrometry evidence is not absorbed.
    record_pyrometry(
        furnace["id"], "TUS", performed_at="2026-08-10T00:00:00Z", result="PASS"
    )
    locked = get_audit_package(package["id"])
    assert locked["status"] == "ISSUED"
    assert_instant_equals(locked["issued_at"], DEFAULT_CLOCK_ISO, "issued_at")
    assert set(locked["evidence_manifest"]["pyrometry_record_ids"]) == pyro_ids, (
        "the 2026-08-10 record must not enter the ISSUED package's manifest"
    )
    assert locked["evidence_manifest"]["load_batch_ids"] == [load["id"]]


# ---------------------------------------------------------------------------
# Corner: rbac / audit_package_compile_issue_role_separation
# ---------------------------------------------------------------------------

def test_audit_package_compile_issue_role_separation(api):
    """PRD §3.9: "Issuance is the auditor's act, segregated from compilation
    by role: a `NadcapAuditor` issues a package that is still in `DRAFT` (any
    other status fails with `ERR_PACKAGE_NOT_DRAFT`, HTTP 409)."
    PRD §2.1: "A role attempting an operation reserved for another role is
    rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/audit_package_compile_issue_role_separation
    """
    bundle = process_order_to_processed()
    package = create_audit_package(
        bundle["shop"]["furnace"]["id"], [bundle["load"]["id"]]
    )
    assert package["status"] == "DRAFT"

    # The compiling QualityEngineer cannot issue.
    res = api.issue_audit_package(package["id"], QE)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)
    assert get_audit_package(package["id"])["status"] == "DRAFT"

    # The NadcapAuditor issues it.
    issued = validate_success(api.issue_audit_package(package["id"], AUDITOR), 200)
    assert issued["status"] == "ISSUED"
