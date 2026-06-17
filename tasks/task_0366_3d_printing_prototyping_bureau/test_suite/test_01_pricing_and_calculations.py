"""Pricing, printability scoring, and quantity/conservation calculations.

Covers:
  Difficulty/combinatorial_formula/pricing_per_part_round_then_multiply
  Difficulty/combinatorial_formula/rush_tier_nonlinear_surcharge
  Corner/calculations/printability_score_printable_100
  Corner/calculations/printability_nonmanifold_hard_gate_rejected
  Corner/calculations/run_grams_rounding_half_up
  Corner/calculations/standard_order_no_rush_surcharge
  Corner/entities/spool_computed_grams_remaining_on_create
  Corner/state_machines/flagged_override_promotes_to_printable
"""
from test_helpers import (
    validate_success, get_success_data, api_client,
    setup_catalogue, setup_order_with_line, add_line, quote_order,
    upload_and_check_file, upload_file, create_spool,
    create_print_file_payload, create_spool_payload,
    make_customer_headers, FILE_A, FILE_B, TEST_USERS,
)

QA = TEST_USERS["qa_reviewer_headers"]
ADMIN = TEST_USERS["bureau_admin_headers"]


def test_per_part_rounded_before_multiply_then_setup_added(api):
    """PRD §3.3: "Critically, the per-part amount is rounded first and only then
    multiplied: `line_total_cents` is `per_part_cents` multiplied by `quantity`,
    plus the material's `setup_fee_cents` added once."
    PRD §3.3: "`per_part_cents` is the sum of material cost and machine cost
    rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/pricing_per_part_round_then_multiply
    """
    env = setup_catalogue(with_spool=False)
    f = upload_file(env["bureau"]["id"], env["customer"]["id"], geometry=FILE_A)
    order = get_success_data(api.create_order(
        {"bureau_id": env["bureau"]["id"], "customer_id": env["customer"]["id"]},
        env["cust_headers"]))
    res = api.create_order_line(
        {"order_id": order["id"], "print_file_id": f["id"],
         "material_id": env["material"]["id"], "layer_height_mm": 0.05, "quantity": 3},
        env["cust_headers"])
    line = validate_success(res, 201)
    # layer_count ceil(60/0.05)=1200; print_seconds 8400; print_minutes ceil(140)=140
    assert line["print_minutes"] == 140, f"print_minutes {line['print_minutes']}"
    # per_part round_half_up(8.40*35 + 140*12) = round_half_up(294 + 1680) = 1974
    assert line["per_part_cents"] == 1974, f"per_part_cents {line['per_part_cents']}"
    # line_total = 1974*3 + 2500 = 8422 (round-per-part-then-sum, not sum-then-round)
    assert line["line_total_cents"] == 8422, f"line_total_cents {line['line_total_cents']}"


def test_print_minutes_layer_count_ceiling(api):
    """PRD §3.3: "the layer count is the part height `bbox_z_mm` divided by the
    chosen `layer_height_mm`, rounded up to a whole number of layers; multiplying
    the layer count by 7 seconds per layer gives the print time in seconds;
    dividing that by 60 and rounding up to a whole number gives `print_minutes`
    per part."

    Design: Difficulty/combinatorial_formula/pricing_per_part_round_then_multiply
    """
    env = setup_catalogue(with_spool=False)
    f = upload_file(env["bureau"]["id"], env["customer"]["id"], geometry=FILE_A)
    order = get_success_data(api.create_order(
        {"bureau_id": env["bureau"]["id"], "customer_id": env["customer"]["id"]},
        env["cust_headers"]))
    # File A bbox_z 60, layer 0.05 -> 1200 layers -> 8400s -> ceil(140.0)=140
    res = api.create_order_line(
        {"order_id": order["id"], "print_file_id": f["id"],
         "material_id": env["material"]["id"], "layer_height_mm": 0.05, "quantity": 1},
        env["cust_headers"])
    line = validate_success(res, 201)
    assert line["print_minutes"] == 140


def test_rush_surcharge_expedite_rounded_once_at_order_level(api):
    """PRD §3.3: "a `STANDARD` order adds 0 percent, an `EXPEDITE` order adds 30
    percent, and a `RUSH` order adds 75 percent. The `rush_surcharge_cents` is the
    base multiplied by the rush percentage divided by 100, rounded half up to
    whole cents exactly once at this order level (never per line). The
    `grand_total_cents` is the base plus the rush surcharge."
    PRD §3.4: "Attaching a task recomputes its line's `finishing_total_cents`,
    which is the sum of that line's finishing-task `addon_cents` values multiplied
    by the line's `quantity`, and then recomputes the order totals."

    Design: Difficulty/combinatorial_formula/rush_tier_nonlinear_surcharge
    """
    env = setup_order_with_line(geometry=FILE_A, layer_height_mm=0.05, quantity=3,
                                lead_tier="EXPEDITE", check_file=True)
    # finishing SUPPORT_REMOVAL(500) + DYE_BLACK(800) per part * qty 3 = 3900
    api_client.create_finishing_task(
        {"order_line_id": env["line"]["id"], "kind": "SUPPORT_REMOVAL",
         "addon_cents": 500, "station_start_min": 0, "station_duration_min": 10},
        TEST_USERS["operator_headers"])
    api_client.create_finishing_task(
        {"order_line_id": env["line"]["id"], "kind": "DYE_BLACK",
         "addon_cents": 800, "station_start_min": 100, "station_duration_min": 20},
        TEST_USERS["operator_headers"])
    quoted = quote_order(env)
    assert quoted["parts_subtotal_cents"] == 8422
    assert quoted["finishing_subtotal_cents"] == 3900, quoted["finishing_subtotal_cents"]
    # base 12322; rush round_half_up(12322*30/100)=round_half_up(3696.6)=3697
    assert quoted["rush_surcharge_cents"] == 3697, quoted["rush_surcharge_cents"]
    assert quoted["grand_total_cents"] == 16019, quoted["grand_total_cents"]


def test_rush_surcharge_rush_tier_75_percent(api):
    """PRD §3.3: "a `STANDARD` order adds 0 percent, an `EXPEDITE` order adds 30
    percent, and a `RUSH` order adds 75 percent. The `rush_surcharge_cents` is the
    base multiplied by the rush percentage divided by 100, rounded half up to
    whole cents exactly once at this order level (never per line). The
    `grand_total_cents` is the base plus the rush surcharge."

    Design: Difficulty/combinatorial_formula/rush_tier_nonlinear_surcharge
    """
    # RUSH tier (75%) over a single line A (8422, no finishing).
    env = setup_order_with_line(geometry=FILE_A, layer_height_mm=0.05, quantity=3,
                                lead_tier="RUSH", check_file=True)
    quoted = quote_order(env)
    assert quoted["parts_subtotal_cents"] == 8422
    assert quoted["finishing_subtotal_cents"] == 0
    # base 8422; rush round_half_up(8422*75/100)=round_half_up(6316.5)=6317
    assert quoted["rush_surcharge_cents"] == 6317, quoted["rush_surcharge_cents"]
    assert quoted["grand_total_cents"] == 14739, quoted["grand_total_cents"]


def test_standard_lead_tier_no_rush_surcharge(api):
    """PRD §3.3: "a `STANDARD` order adds 0 percent, an `EXPEDITE` order adds 30
    percent, and a `RUSH` order adds 75 percent."
    PRD §3.3: "The `grand_total_cents` is the base plus the rush surcharge."

    Design: Corner/calculations/standard_order_no_rush_surcharge
    """
    env = setup_order_with_line(geometry=FILE_B, layer_height_mm=0.10, quantity=1,
                                lead_tier="STANDARD", check_file=True)
    quoted = quote_order(env)
    assert quoted["rush_surcharge_cents"] == 0
    # line B total 2928, no finishing, STANDARD -> grand 2928
    assert quoted["grand_total_cents"] == 2928, quoted["grand_total_cents"]


def test_printability_score_full_100_printable(api):
    """PRD §3.2: "The manifold component contributes 40 points when `is_manifold`
    is true and 0 otherwise. The fit component contributes 30 points when the file
    fits the available build envelope and 0 otherwise". And: "if the score is at
    least 70 the file becomes `PRINTABLE`".

    Design: Corner/calculations/printability_score_printable_100
    """
    env = setup_catalogue(with_spool=False)
    checked = upload_and_check_file(env["bureau"]["id"], env["customer"]["id"],
                                    env["material"]["id"], geometry=FILE_A)
    assert checked["printability_score"] == 100, checked["printability_score"]
    assert checked["status"] == "PRINTABLE"


def test_nonmanifold_hard_gate_forces_rejected(api):
    """PRD §3.2: "if `is_manifold` is false, the file is forced to `REJECTED`
    regardless of the numeric score — the manifold gate takes precedence over
    everything."

    Design: Corner/calculations/printability_nonmanifold_hard_gate_rejected
    """
    env = setup_catalogue(with_spool=False)
    # fits + wall + overhang = 60, but non-manifold -> REJECTED, not FLAGGED
    geo = dict(FILE_A)
    geo["is_manifold"] = False
    checked = upload_and_check_file(env["bureau"]["id"], env["customer"]["id"],
                                    env["material"]["id"], geometry=geo)
    assert checked["printability_score"] == 60, checked["printability_score"]
    assert checked["status"] == "REJECTED"


def test_run_grams_round_half_up(api):
    """PRD §3.6: "the system computes `run_grams` as the file's `volume_cm3`
    multiplied by the material's `density_g_per_cm3` multiplied by the line's
    `quantity`, rounded half up to whole grams".

    Design: Corner/calculations/run_grams_rounding_half_up
    """
    from test_helpers import setup_confirmed_order, create_run
    env = setup_confirmed_order(geometry=FILE_A, layer_height_mm=0.05, quantity=3,
                                spool_grams=1000)
    run = create_run(env, duration_min=140)
    # round_half_up(8.40 * 1.10 * 3) = round_half_up(27.72) = 28
    assert run["run_grams"] == 28, run["run_grams"]


def test_spool_grams_remaining_computed_on_create(api):
    """PRD §3.1: "on load, `grams_committed` and `grams_consumed` are zero,
    `grams_remaining` equals `grams_total`, and the spool is `LOADED`."

    Design: Corner/entities/spool_computed_grams_remaining_on_create
    """
    env = setup_catalogue(with_spool=False, with_machine=False)
    res = api.create_spool(
        create_spool_payload(env["bureau"]["id"], env["material"]["id"], grams_total=250),
        ADMIN)
    spool = validate_success(res, 201)
    assert spool["grams_remaining"] == 250
    assert spool["grams_committed"] == 0
    assert spool["grams_consumed"] == 0
    assert spool["status"] == "LOADED"


def test_flagged_file_override_promotes_to_printable(api):
    """PRD §3.2: "a `QAReviewer` may override a `FLAGGED` file, accepting it for
    production despite a sub-70 score; the override is only permitted while the
    file is `FLAGGED` and moves it to `PRINTABLE`."

    Design: Corner/state_machines/flagged_override_promotes_to_printable
    """
    env = setup_catalogue(with_spool=False)
    # bbox 200 (> max build 185 -> fits 0) + overhang 90 (> 45 -> 0): score 40+20 = 60 -> FLAGGED
    geo = {"volume_cm3": 4.00, "bbox_x_mm": 200, "bbox_y_mm": 20, "bbox_z_mm": 20,
           "min_wall_mm": 1.0, "max_overhang_deg": 90, "is_manifold": True}
    checked = upload_and_check_file(env["bureau"]["id"], env["customer"]["id"],
                                    env["material"]["id"], geometry=geo)
    assert checked["printability_score"] == 60, checked["printability_score"]
    assert checked["status"] == "FLAGGED"
    res = api.override_print_file(checked["id"], QA)
    overridden = validate_success(res, 200)
    assert overridden["status"] == "PRINTABLE"
