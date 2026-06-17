"""Dual-variant calculations: reprint cost (FORWARD vs CHRONOLOGICAL) and
machine utilization (COMMITTED vs ACTIVE).

Covers:
  Difficulty/dual_variant_calc/reprint_forward_vs_chronological_file_defect
  Difficulty/dual_variant_calc/utilization_committed_vs_active
"""
from test_helpers import (
    validate_success, get_success_data, api_client,
    setup_confirmed_order, setup_run_failed, adjudicate_run, get_reprint_line,
    create_run, refresh_order, refresh_customer, refresh_machine,
    FILE_A, FILE_B, TEST_USERS,
)

OPERATOR = TEST_USERS["operator_headers"]
QA = TEST_USERS["qa_reviewer_headers"]


def test_reprint_forward_charges_full_line_then_chronological_finalizes_file_defect(api):
    """PRD §3.7: "A provisional reprint charge is applied immediately under the
    forward-looking attribution variant: the customer is billed the full original
    `line_total_cents` of the failed line as a reprint estimate."
    PRD §3.7: "When the cause is a customer fault — `FILE_DEFECT` or
    `CUSTOMER_CHANGE` — the final charge is the material portion plus half of the
    machine portion: the material portion is the failed line's `volume_cm3`
    multiplied by `material_rate_cents_per_cm3`, rounded half up to whole cents and
    then multiplied by the failed line's `quantity`; the machine portion is the
    failed line's per-part `print_minutes` multiplied by `machine_rate_cents_per_min`
    multiplied by `quantity`; and the final charge is the material portion plus the
    machine portion multiplied by one half and rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/reprint_forward_vs_chronological_file_defect
    """
    env = setup_run_failed("FILE_DEFECT", geometry=FILE_B, layer_height_mm=0.10,
                           quantity=1, duration_min=24, spool_grams=1000)
    # FORWARD: original line 2928 + full reprint estimate 2928 = 5856
    order_forward = refresh_order(env)
    assert order_forward["grand_total_cents"] == 5856, order_forward["grand_total_cents"]

    adjudicate_run(env, start_min=30, duration_min=24)
    reprint = get_reprint_line(env)
    assert reprint is not None, "reprint line should exist"
    # CHRONOLOGICAL FILE_DEFECT: material_portion round_half_up(4.00*35)*1 = 140;
    # machine_portion 24*12*1 = 288; final = 140 + round_half_up(144) = 284
    assert reprint["line_total_cents"] == 284, reprint["line_total_cents"]

    order_final = refresh_order(env)
    # original 2928 + reprint final 284 = 3212
    assert order_final["grand_total_cents"] == 3212, order_final["grand_total_cents"]

    customer = refresh_customer(env)
    assert customer["escrow_held_cents"] == 3212, customer["escrow_held_cents"]
    assert customer["wallet_balance_cents"] == 4996788, customer["wallet_balance_cents"]


def test_reprint_chronological_bureau_fault_zero_charge(api):
    """PRD §3.7: "When the cause is a bureau fault — `MACHINE_FAULT` or
    `OPERATOR_ERROR` — the final reprint charge is zero, because the bureau
    absorbs the cost."
    PRD §3.7: "The reconciliation delta is the final chronological charge minus
    the provisional forward charge that was applied at fail time. That delta is
    applied to the order totals and to the customer ledger".

    Design: Difficulty/dual_variant_calc/reprint_forward_vs_chronological_file_defect
    """
    env = setup_run_failed("MACHINE_FAULT", geometry=FILE_B, layer_height_mm=0.10,
                           quantity=1, duration_min=24, spool_grams=1000)
    # FORWARD: 2928 + 2928 = 5856
    assert refresh_order(env)["grand_total_cents"] == 5856
    adjudicate_run(env, start_min=30, duration_min=24)
    reprint = get_reprint_line(env)
    # bureau fault -> final reprint charge 0
    assert reprint["line_total_cents"] == 0, reprint["line_total_cents"]
    order_final = refresh_order(env)
    # original 2928 + reprint 0 = 2928 (forward 2928 fully refunded)
    assert order_final["grand_total_cents"] == 2928, order_final["grand_total_cents"]
    customer = refresh_customer(env)
    assert customer["escrow_held_cents"] == 2928
    assert customer["wallet_balance_cents"] == 5000000 - 2928


def test_utilization_committed_counts_queued_active_counts_printing(api):
    """PRD §2.7: "the committed view, `scheduled_minutes`, sums `duration_min` over
    the machine's runs that are `QUEUED` or `PRINTING` — every job that holds a
    slot, whether or not it is physically running — and `utilization_pct` is
    `scheduled_minutes` divided by the bureau's `shift_capacity_minutes`, multiplied
    by 100, rounded half up to a whole percent. The active view, `active_minutes`,
    sums `duration_min` over only the runs that are `PRINTING`, and
    `active_utilization_pct` is `active_minutes` divided by `shift_capacity_minutes`,
    multiplied by 100, rounded half up to a whole percent."

    Design: Difficulty/dual_variant_calc/utilization_committed_vs_active
    """
    env = setup_confirmed_order(geometry=FILE_A, layer_height_mm=0.05, quantity=3,
                                spool_grams=1000, shift_capacity_minutes=480)
    run_x = create_run(env, start_min=0, duration_min=140)
    create_run(env, start_min=200, duration_min=60)

    before = refresh_machine(env)
    # both QUEUED: committed 200/480 -> round_half_up(41.66)=42; active 0
    assert before["utilization_pct"] == 42, before["utilization_pct"]
    assert before["active_utilization_pct"] == 0, before["active_utilization_pct"]

    get_success_data(api_client.start_print_run(run_x["id"], OPERATOR))
    after = refresh_machine(env)
    # committed unchanged (still 200/480 -> 42); active now 140/480 -> round_half_up(29.16)=29
    assert after["utilization_pct"] == 42, after["utilization_pct"]
    assert after["active_utilization_pct"] == 29, after["active_utilization_pct"]


def test_utilization_committed_rises_on_schedule_before_start(api):
    """PRD §2.7: "The committed figure rises the moment a run is scheduled; the
    active figure rises only when a run actually starts."

    Design: Difficulty/dual_variant_calc/utilization_committed_vs_active
    """
    env = setup_confirmed_order(geometry=FILE_A, layer_height_mm=0.05, quantity=3,
                                spool_grams=1000, shift_capacity_minutes=480)
    create_run(env, start_min=0, duration_min=140)
    m = refresh_machine(env)
    # scheduled (QUEUED) run raises committed but not active
    assert m["utilization_pct"] == 29, m["utilization_pct"]  # round_half_up(140/480*100)=29
    assert m["active_utilization_pct"] == 0, m["active_utilization_pct"]
