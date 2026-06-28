"""Grade-in calculation: pinned dockage-then-shrink evaluation order and threshold edges.

Queue A (Difficulty) — combinatorial_formula (mode_a).
Queue B (Corner) — calculations (grade_in below base moisture).
"""
import pytest

from test_helpers import validate_success, TEST_USERS
import test_helpers.fixtures as fx

CLERK = TEST_USERS["grade_clerk_headers"]


def test_grade_in_nonlinear_dockage_then_shrink_bushels(api):
    """PRD §3.2: "the `clean_weight_lbs` is the net weight minus those dockage pounds —
    **dockage is removed first**." PRD §3.2: "Moisture shrink is then applied to the
    already-dockage-reduced clean weight: the dry weight in pounds is the clean weight
    multiplied by the quantity (1 minus the commodity's shrink percent per point divided
    by 100, that result multiplied by the moisture points) — **shrink is applied after
    dockage**, on the clean weight. The `net_dry_bushels` are that dry weight divided by
    the test weight per bushel, rounded to 4 decimal places."

    Design: Difficulty/combinatorial_formula/grade_in_nonlinear_dockage_then_shrink_mode_a
    """
    commodity = fx.create_commodity()
    member = fx.create_member(name="Carl Farm")
    ticket = fx.create_weighed_ticket(
        member["id"], commodity["id"],
        gross_weight_lbs=58000, tare_weight_lbs=18000, moisture_pct=18.0, dockage_pct=1.5,
        deposit_account_type="DELAYED_PRICE",
    )
    graded = fx.grade_ticket(ticket["id"])
    assert graded["net_weight_lbs"] == 40000
    assert graded["clean_weight_lbs"] == 39400.0, (
        f"dockage 600 lbs removed first, got {graded['clean_weight_lbs']}"
    )
    assert graded["moisture_points"] == 3.0
    assert graded["wet_bushels"] == pytest.approx(703.5714, abs=1e-4)
    assert graded["net_dry_bushels"] == pytest.approx(674.0214, abs=1e-4)


def test_grade_in_nonlinear_drying_charge(api):
    """PRD §3.2: "The `drying_charge_dollars` are the net dry bushels multiplied by the
    moisture points, multiplied by the commodity's drying cents per point per bushel,
    divided by 100, rounded to 2 decimal places."

    Design: Difficulty/combinatorial_formula/grade_in_nonlinear_dockage_then_shrink_mode_a
    """
    commodity = fx.create_commodity()
    member = fx.create_member(name="Carl2 Farm")
    ticket = fx.create_weighed_ticket(
        member["id"], commodity["id"],
        gross_weight_lbs=58000, tare_weight_lbs=18000, moisture_pct=18.0, dockage_pct=1.5,
        deposit_account_type="DELAYED_PRICE",
    )
    graded = fx.grade_ticket(ticket["id"])
    # 674.0214 * 3.0 * 4 / 100 = 80.88
    assert graded["drying_charge_dollars"] == pytest.approx(80.88, abs=0.01)


def test_grade_in_below_base_moisture_no_shrink_no_drying(api):
    """PRD §3.2: "The `moisture_points` are the measured moisture percent minus the
    commodity's base moisture, but never less than zero (at or below base moisture,
    moisture points are 0, so neither shrink nor drying applies)."

    Design: Corner/calculations/grade_in_below_base_moisture_no_shrink_no_drying
    """
    commodity = fx.create_commodity()
    member = fx.create_member(name="EE Farm")
    ticket = fx.create_weighed_ticket(
        member["id"], commodity["id"],
        gross_weight_lbs=72000, tare_weight_lbs=16000, moisture_pct=15.0, dockage_pct=0,
        deposit_account_type="DELAYED_PRICE",
    )
    graded = fx.grade_ticket(ticket["id"])
    assert graded["moisture_points"] == 0.0
    assert graded["wet_bushels"] == pytest.approx(1000.0, abs=1e-4)
    assert graded["net_dry_bushels"] == pytest.approx(1000.0, abs=1e-4)
    assert graded["drying_charge_dollars"] == pytest.approx(0.00, abs=0.01)
