"""Donor receipt dual-variant tests (queue A: dual_variant_calc)."""
from test_helpers import (
    api_client, validate_success,
    make_donor, make_bike, triage_bike,
    TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]


def _three_bike_donor(receipt_method: str = "FLAT_SCHEDULE"):
    """Donor with ROAD/B, KIDS/A, BMX/D all triaged at default clock."""
    d = make_donor(display_name="D One", donor_type="INDIVIDUAL",
                   email="d1@x.org", receipt_method=receipt_method)
    b1 = make_bike(d["id"], serial_number="SN-R1", bike_type="ROAD", wheel_size_inches=27)
    triage_bike(b1["id"], "B", False)
    b2 = make_bike(d["id"], serial_number="SN-K1", bike_type="KIDS", wheel_size_inches=20)
    triage_bike(b2["id"], "A", False)
    b3 = make_bike(d["id"], serial_number="SN-X1", bike_type="BMX", wheel_size_inches=20)
    triage_bike(b3["id"], "D", True)
    return d


def test_donor_receipt_flat_schedule_variant_totals():
    """PRD §3.14: "Under the flat schedule, each bike contributes by grade: `A`
    15000 cents, `B` 9000, `C` 4000, `D` 1000, regardless of bike type." and
    "Under the comparable-value variant, a grade-`A`, `B`, or `C` bike contributes
    60 percent of its pricing base scaled by the grade multiplier — the same
    base-by-type and grade factors used for sales — rounded half up to whole
    cents; a grade-`D` bike contributes 10 percent of its pricing base, rounded
    half up."

    Design: Difficulty/dual_variant_calc/donor_receipt_flat_vs_fmv_diverge
    """
    d = _three_bike_donor("FLAT_SCHEDULE")
    data = validate_success(
        api_client.get_donor_receipt(d["id"], COORD, params={"year": 2026})
    )
    assert data["bike_count"] == 3
    # flat: B 9000 + A 15000 + D 1000
    assert data["flat_total_cents"] == 25000
    # fmv: round(12000*0.8*0.6)=5760 + round(4000*1.0*0.6)=2400 + round(6000*0.10)=600
    assert data["fmv_total_cents"] == 8760


def test_donor_receipt_method_selected_effective_variant():
    """PRD §3.14: "The receipt response reports the `donor_id`, the `year`, the
    counted `bike_count`, both totals (`flat_total_cents` and `fmv_total_cents`),
    the donor's `receipt_method`, and the `effective_total_cents` — the flat total
    when the method is `FLAT_SCHEDULE`, the comparable total when it is
    `FMV_COMPARABLE`."

    Design: Difficulty/dual_variant_calc/donor_receipt_flat_vs_fmv_diverge
    """
    d = _three_bike_donor("FLAT_SCHEDULE")
    data = validate_success(
        api_client.get_donor_receipt(d["id"], COORD, params={"year": 2026})
    )
    assert data["receipt_method"] == "FLAT_SCHEDULE"
    assert data["effective_total_cents"] == 25000
    assert data["flat_total_cents"] != data["fmv_total_cents"]
