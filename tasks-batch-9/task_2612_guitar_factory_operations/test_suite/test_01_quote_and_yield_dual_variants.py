"""
The two quote totals on a build order, and the two yield figures on a tonewood
lot: in both pairs the same row carries a forward-looking figure and a
backward-looking one that must disagree at the same instant.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers import test_users as U

VINE = {
    "option_code": "INL-VINE",
    "option_group": "INLAY",
    "upcharge_cents": 130000,
    "complexity_class": "ARTISAN",
    "lead_time_days": 45,
    "incompatible_option_codes": ["INL-DOT"],
}
BRAZILIAN_TOP = {
    "option_code": "TOP-BRZ",
    "option_group": "TOP_WOOD",
    "upcharge_cents": 95000,
    "complexity_class": "MASTER",
    "lead_time_days": 30,
    "requires_finish_system": "NITRO",
}


def one_selected_one_pending(api):
    """
    An endorsing artist's custom order at 480000 cents carrying an approved
    artisan inlay and a master top wood still awaiting approval, confirmed with
    200000 cents on deposit so the configuration may be frozen.
    """
    env = X.build_clock(api)
    env["optA"] = F.create_option(api, dict(VINE))["id"]
    env["optB"] = F.create_option(api, dict(BRAZILIAN_TOP))["id"]
    order = F.create_order(api, F.order_payload(
        order_code="ORD-001", model_code="OM45", base_price_cents=480000,
        is_custom_shop=True, artist_tier="ENDORSER", finish_system="NITRO",
        promised_date="2026-10-01T00:00:00Z"), U.COORDINATOR_HEADERS)
    env["bo1"] = order["id"]
    env["sel1"] = F.create_selection(api, env["bo1"], env["optA"],
                                     order["version"], quantity=1,
                                     headers=U.COORDINATOR_HEADERS)["id"]
    F.approve_selection(api, env["sel1"], U.COORDINATOR_2_HEADERS)
    X.read_order_version(api, env, "bo1", "bo_v2")
    env["sel2"] = F.create_selection(api, env["bo1"], env["optB"], env["bo_v2"],
                                     quantity=1,
                                     headers=U.COORDINATOR_HEADERS)["id"]
    F.confirm_order(api, env["bo1"], 200000, U.COORDINATOR_HEADERS)
    return env


def test_locking_the_configuration_leaves_two_different_quote_totals_on_one_order(api):
    """
    The order carries a forward-looking total over the live catalog and a
    backward-looking total over the frozen locked lines, and the two must land
    on different figures at the same instant.

    PRD: "The provisional lines are 175500 and 166250, a subtotal of 341750, a
    pre-discount amount of 821750, a surcharge of 98610, an artist discount of
    34175, and a `provisional_quote_total_cents` of 886185."

    Design: Difficulty/dual_variant_calc/quote_provisional_vs_binding_diverge_on_three_axes
    """
    env = one_selected_one_pending(api)

    before = validate_success(
        api.get_build_order(env["bo1"], U.COORDINATOR_HEADERS))
    assert before["provisional_quote_total_cents"] == 886185
    assert before["binding_quote_total_cents"] is None

    locked = validate_success(
        api.lock_options(env["bo1"], U.COORDINATOR_HEADERS))
    assert locked["commercial_status"] == "OPTIONS_LOCKED"
    assert locked["provisional_quote_total_cents"] == 886185
    assert locked["binding_quote_total_cents"] == 716610


def test_the_force_rejected_option_keeps_its_line_but_leaves_the_binding_set(api):
    """
    Freezing the configuration locks the approved line at the catalog price it
    is holding and throws the unapproved one out without a locked price, which
    is the mechanism that makes the two totals differ.

    PRD: "Every selection still in status `PENDING_APPROVAL` is force-rejected,
    moving `PENDING_APPROVAL → REJECTED` with its `locked_upcharge_cents` left
    null so that it never enters the binding input set at all — which is
    precisely how the two quote variants come to differ."

    Design: Difficulty/dual_variant_calc/quote_provisional_vs_binding_diverge_on_three_axes
    """
    env = one_selected_one_pending(api)
    F.lock_options(api, env["bo1"], U.COORDINATOR_HEADERS)

    approved = validate_success(
        api.get_option_selection(env["sel1"], U.COORDINATOR_HEADERS))
    assert approved["status"] == "LOCKED"
    assert approved["locked_upcharge_cents"] == 130000
    assert approved["line_total_cents"] == 175500

    dropped = validate_success(
        api.get_option_selection(env["sel2"], U.COORDINATOR_HEADERS))
    assert dropped["status"] == "REJECTED"
    assert dropped["locked_upcharge_cents"] is None
    assert dropped["line_total_cents"] == 166250


def two_cuts_off_a_dried_rosewood_lot(api):
    """
    A hundred board feet of protected rosewood received wet at 12.0 percent,
    attested, dried to 7.0 percent, released, and sawn into a 30.00 board-foot
    billet, with the lot's fresh version read back for the second cut.
    """
    env = X.build_released_lot(api, species_code="EAST_INDIAN_ROSEWOOD",
                               cites_appendix="APPENDIX_II")
    X.build_billet(api, env, board_feet=30.00)
    X.read_lot_version(api, env)
    return env


def test_the_two_yield_figures_read_different_moisture_and_charge_kerf_differently(api):
    """
    The receipt-time projection is discounted by the wet reading the wood
    arrived at, while the realised figure uses the current dry reading, whose
    shrinkage clamps to nothing.

    PRD: "The nominal projection uses a shrinkage allowance of four percentage
    points above target times 45, or 180 basis points, giving 100.00 multiplied
    by 9790 divided by 10000, which is 97.90."

    Design: Difficulty/dual_variant_calc/lot_yield_nominal_vs_actual_diverge_on_moisture_kerf_and_input_set
    """
    env = two_cuts_off_a_dried_rosewood_lot(api)

    created = validate_success(api.create_billet({
        "billet_code": "BLT-002", "lot_id": env["lot1"], "board_feet": 25.00,
        "grade": "AA", "expected_tonewood_lot_version": env["lot_v2"],
    }, U.MACHINIST_HEADERS), 201)
    assert created["billet_code"] == "BLT-002"

    lot = validate_success(api.get_tonewood_lot(env["lot1"], U.MACHINIST_HEADERS))
    assert lot["nominal_yield_board_feet"] == 97.90
    assert lot["actual_yield_board_feet"] == 55.00
    assert lot["status"] == "RELEASED"


def test_kerf_is_charged_per_cut_while_the_projection_assumes_one_whole_lot_allowance(api):
    """
    Two cuts leave two separate sawdust charges on the ledger, an order of
    magnitude more loss than the single whole-lot allowance the receipt-time
    projection assumed.

    PRD: "Following the same 100.00-board-foot lot through two cuts of 30.00 and
    25.00 board feet makes the ledger legible: the kerf charges are 0.90 and
    0.75, so `board_feet_kerf_loss` reaches 1.65, `board_feet_unassigned`
    reaches 55.00, and `board_feet_available` falls to 43.35."

    Design: Difficulty/dual_variant_calc/lot_yield_nominal_vs_actual_diverge_on_moisture_kerf_and_input_set
    """
    env = two_cuts_off_a_dried_rosewood_lot(api)
    F.create_billet(api, env["lot1"], env["lot_v2"], billet_code="BLT-002",
                    board_feet=25.00, grade="AA")

    lot = validate_success(api.get_tonewood_lot(env["lot1"], U.MACHINIST_HEADERS))
    assert lot["board_feet_kerf_loss"] == 1.65
    assert lot["board_feet_unassigned"] == 55.00
    assert lot["board_feet_available"] == 43.35
