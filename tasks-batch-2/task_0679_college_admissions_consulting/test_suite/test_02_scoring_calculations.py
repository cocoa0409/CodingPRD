"""Difficulty queue: profile_strength rounding-order, admit_probability non-linear
combination, and the school-classification numeric boundary at 0.60.

Literal expected values are copied from the design index; never recomputed.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    make_counselor_headers,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f


# ==========================================================================
# combinatorial_formula / admit_probability_nonlinear_three_inputs
# ==========================================================================
def test_admit_probability_combines_three_inputs_nonlinearly(api):
    """PRD §3.4: "The raw probability is the `admit_rate` multiplied by the
    multiplier, plus the strength bonus."
    PRD §3.4: "when the gap is 100 or more the multiplier is 1.6"
    PRD §3.4: "A strength bonus is the student's `profile_strength` minus 50,
    divided by 100, then multiplied by 0.3, which ranges from −0.15 to +0.15
    around a profile strength of 50."
    PRD §3.4: "The stored `admit_probability` is that raw value clamped to be no
    less than 0.0 and no more than 1.0, then rounded half up to four decimal
    places."

    Design: Difficulty/combinatorial_formula/admit_probability_nonlinear_three_inputs
    """
    # gpa 3.5 (gpa_c 35.0), sat 1400 (sat_c 25.0) => academics 60.0;
    # one tier-3 activity 2h x 20wk => 2*20/100*0.4 = 0.16 resume => profile_strength 60.16.
    counselor, student = fx.setup_onboarded_student(
        student_overrides={"gpa": 3.5, "sat_total": 1400},
        activity_overrides={"hours_per_week": 2, "weeks_per_year": 20, "tier": 3, "category": "ARTS"},
    )
    ch = make_counselor_headers(counselor["id"])
    assert student["profile_strength"] == 60.16, (
        f"profile_strength should be 60.16; got {student['profile_strength']}"
    )
    # admit_rate 0.40, median_sat 1300, sat 1400 => gap +100 => mult 1.6;
    # strength_bonus = (60.16-50)/100*0.3 = 0.03048; raw = 0.40*1.6 + 0.03048 = 0.67048 -> 0.6705
    item = validate_success(
        api.create_school_list_item(
            f.create_school_list_item_payload(
                student["id"], school_name="Match U", admit_rate=0.40, median_sat=1300
            ),
            ch,
        ),
        expected_status=201,
    )
    assert item["admit_probability"] == 0.6705, (
        f"admit_probability should be 0.6705; got {item['admit_probability']}"
    )
    assert item["classification"] == "SAFETY"


def test_admit_probability_gap_plus_100_uses_high_multiplier(api):
    """PRD §3.4: "A multiplier is then chosen from the gap: when the gap is 100 or
    more the multiplier is 1.6"
    PRD §3.4: "The raw probability is the `admit_rate` multiplied by the
    multiplier, plus the strength bonus."

    Design: Difficulty/combinatorial_formula/admit_probability_nonlinear_three_inputs
    """
    counselor, student = fx.setup_onboarded_student(
        student_overrides={"gpa": 3.5, "sat_total": 1400},
        activity_overrides={"hours_per_week": 2, "weeks_per_year": 20, "tier": 3, "category": "ARTS"},
    )
    ch = make_counselor_headers(counselor["id"])
    # sat 1400 vs median 1300 => gap +100 => mult 1.6; profile_strength 60.16 => bonus 0.03048;
    # raw = 0.40*1.6 + 0.03048 = 0.67048 -> 0.6705, a non-linear combination of three inputs.
    item = validate_success(
        api.create_school_list_item(
            f.create_school_list_item_payload(
                student["id"], school_name="Gap U", admit_rate=0.40, median_sat=1300
            ),
            ch,
        ),
        expected_status=201,
    )
    assert item["admit_probability"] == 0.6705


def test_profile_strength_round_then_sum_order(api):
    """PRD §3.1: "Rounding order is pinned: the academic subtotal is rounded half
    up to two decimal places, the résumé subtotal is rounded half up to two
    decimal places, the two rounded subtotals are added, and that sum is rounded
    half up to two decimal places to produce `profile_strength`."
    PRD §3.1: "Each activity contributes its `hours_per_week` multiplied by its
    `weeks_per_year`, divided by 100, then multiplied by a tier weight — 1.0 for
    tier 1, 0.7 for tier 2, 0.4 for tier 3, and 0.2 for tier 4."

    Design: Difficulty/combinatorial_formula/profile_strength_round_then_sum_order
    """
    # gpa 3.8 => gpa_c 38.0; sat 1400 => sat_c 25.0; academics 63.0.
    # tier1 10x40 => 4.0; tier2 5x30 => 5*30/100*0.7 = 1.05; resume 5.05 => total 68.05.
    counselor, student = fx.setup_counselor_and_student(
        student_overrides={"gpa": 3.8, "sat_total": 1400}
    )
    ch = make_counselor_headers(counselor["id"])
    get_success_data(
        api_client.create_activity(
            f.create_activity_payload(
                student["id"], title="Lab", category="ACADEMIC",
                hours_per_week=10, weeks_per_year=40, tier=1,
            ),
            ch,
        )
    )
    get_success_data(
        api_client.create_activity(
            f.create_activity_payload(
                student["id"], title="Band", category="ARTS",
                hours_per_week=5, weeks_per_year=30, tier=2,
            ),
            ch,
        )
    )
    onboarded = validate_success(api.transition_student(student["id"], {"to_status": "ONBOARDED"}, ch))
    assert onboarded["profile_strength"] == 68.05, (
        f"round-then-sum should yield 68.05; got {onboarded['profile_strength']}"
    )
    assert onboarded["intake_status"] == "ONBOARDED"


def test_profile_strength_caps_resume_subtotal_at_thirty(api):
    """PRD §3.1: "These per-activity contributions are summed across every
    `ActivityEntry` for the student (the résumé has no status filter, so all
    entries count), and the résumé subtotal is the lesser of that sum and 30."
    PRD §3.1: "Rounding order is pinned: the academic subtotal is rounded half up
    to two decimal places, the résumé subtotal is rounded half up to two decimal
    places, the two rounded subtotals are added, and that sum is rounded half up
    to two decimal places to produce `profile_strength`."

    Design: Difficulty/combinatorial_formula/profile_strength_round_then_sum_order
    """
    # gpa 3.8 => gpa_c 38.0; sat 1400 => sat_c 25.0; academics 63.0.
    # tier1 10x40 => 4.0; tier2 5x30 => 1.05; resume 5.05; total 63.0 + 5.05 = 68.05.
    counselor, student = fx.setup_counselor_and_student(
        student_overrides={"gpa": 3.8, "sat_total": 1400}
    )
    ch = make_counselor_headers(counselor["id"])
    get_success_data(
        api_client.create_activity(
            f.create_activity_payload(student["id"], title="Lab", category="ACADEMIC",
                                      hours_per_week=10, weeks_per_year=40, tier=1),
            ch,
        )
    )
    get_success_data(
        api_client.create_activity(
            f.create_activity_payload(student["id"], title="Band", category="ARTS",
                                      hours_per_week=5, weeks_per_year=30, tier=2),
            ch,
        )
    )
    onboarded = validate_success(api.transition_student(student["id"], {"to_status": "ONBOARDED"}, ch))
    # resume 5.05 is below the 30 cap, so the pinned round-then-sum gives 68.05.
    assert onboarded["profile_strength"] == 68.05


# ==========================================================================
# boundary_precision_check / classification_safety_at_exactly_060
# ==========================================================================
def test_classification_safety_at_exactly_060(api):
    """PRD §3.2: "is derived from the four-decimal `admit_probability`: if it is
    0.60 or greater the item is a `SAFETY`; if it is strictly below 0.20 it is a
    `REACH`; otherwise — that is, from 0.20 up to but not including 0.60 — it is a
    `TARGET`."

    Design: Difficulty/boundary_precision_check/classification_safety_at_exactly_060
    """
    # gpa 3.0 => gpa_c 30.0; sat 1200 => sat_c 20.0; academics 50.0; zero-hours activity => resume 0.
    counselor, student = fx.setup_onboarded_student(
        student_overrides={"gpa": 3.0, "sat_total": 1200},
        activity_overrides={"hours_per_week": 0, "weeks_per_year": 0, "tier": 4, "category": "SERVICE"},
    )
    ch = make_counselor_headers(counselor["id"])
    assert student["profile_strength"] == 50.0, (
        f"profile_strength should be exactly 50.0; got {student['profile_strength']}"
    )
    # admit_rate 0.60, median_sat 1200, sat 1200 => gap 0 => mult 1.0; strength_bonus 0 => raw 0.6000.
    item = validate_success(
        api.create_school_list_item(
            f.create_school_list_item_payload(
                student["id"], school_name="Edge U", admit_rate=0.60, median_sat=1200
            ),
            ch,
        ),
        expected_status=201,
    )
    assert item["admit_probability"] == 0.6, (
        f"admit_probability should be exactly 0.6; got {item['admit_probability']}"
    )
    assert item["classification"] == "SAFETY", (
        f"0.60 is the inclusive boundary -> SAFETY, not TARGET; got {item['classification']}"
    )


def test_classification_safety_boundary_is_inclusive_not_target(api):
    """PRD §3.2: "if it is 0.60 or greater the item is a `SAFETY`; if it is
    strictly below 0.20 it is a `REACH`; otherwise — that is, from 0.20 up to but
    not including 0.60 — it is a `TARGET`."

    Design: Difficulty/boundary_precision_check/classification_safety_at_exactly_060
    """
    counselor, student = fx.setup_onboarded_student(
        student_overrides={"gpa": 3.0, "sat_total": 1200},
        activity_overrides={"hours_per_week": 0, "weeks_per_year": 0, "tier": 4, "category": "SERVICE"},
    )
    ch = make_counselor_headers(counselor["id"])
    item = validate_success(
        api.create_school_list_item(
            f.create_school_list_item_payload(
                student["id"], school_name="Edge U", admit_rate=0.60, median_sat=1200
            ),
            ch,
        ),
        expected_status=201,
    )
    # The boundary value 0.60 must NOT classify as TARGET (which is < 0.60).
    assert item["classification"] != "TARGET"
    assert item["classification"] == "SAFETY"
