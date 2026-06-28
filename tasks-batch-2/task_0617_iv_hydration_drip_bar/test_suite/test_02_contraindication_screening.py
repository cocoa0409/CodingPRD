"""Intake screening contraindication-score computation and outcome derivation.

Covers the dual-variant (standard vs g6pd-sensitive), the combinatorial non-linear
branch (age term), the exactly-60 boundary, and the corner score instances.
"""
import pytest
from test_helpers import (
    get_success_data, assert_intake_screening,
    set_clock, create_menu_item, create_lounge, create_patient,
    create_requested_appointment, submit_intake,
    TEST_USERS, make_intake_nurse_headers,
)

ADMIN = TEST_USERS["clinic_admin_headers"]


def _screen(menu_overrides, dob, start_at="2026-06-23T09:00:00Z", **flags):
    """Create a patient + LOUNGE appointment and submit an intake, returning the
    persisted screening. Sets clock to 2026-06-22 first."""
    menu_item = create_menu_item(**menu_overrides)
    lounge = create_lounge(bay_count=4)
    patient = create_patient(date_of_birth=dob)
    appointment = create_requested_appointment(
        patient["id"], menu_item["id"], lounge_id=lounge["id"], start_at=start_at)
    return submit_intake(appointment["id"], author_user_id="intake-1", **flags)


# ─── Difficulty: dual_variant_calc / dv_contraindication_standard_vs_g6pd_sensitive ───
def test_contraindication_standard_drip_excludes_g6pd_term(api):
    """PRD §3.5: "The `g6pd_deficiency` flag contributes 35 points, but only when the
    booked menu item is `g6pd_sensitive`; for a drip that is not g6pd-sensitive the G6PD
    flag contributes nothing".
    PRD §3.5: "A score of at least 40 but less than 60 yields `REQUIRES_MD_REVIEW`."

    Design: Difficulty/dual_variant_calc/dv_contraindication_standard_vs_g6pd_sensitive
    """
    set_clock("2026-06-22T00:00:00Z")
    s = _screen({"tier": "MYERS", "requires_standing_order": False, "g6pd_sensitive": False},
                dob="1990-01-01T00:00:00Z",
                renal_impairment=True, cardiac_history=True, g6pd_deficiency=True)
    assert_intake_screening(s)
    assert s["contraindication_score"] == 55, f"expected 55, got {s['contraindication_score']}"
    assert s["outcome"] == "REQUIRES_MD_REVIEW"


def test_contraindication_g6pd_sensitive_drip_includes_g6pd_term(api):
    """PRD §3.5: "The `g6pd_deficiency` flag contributes 35 points, but only when the
    booked menu item is `g6pd_sensitive` ... which means the identical set of flags can
    yield a different score and even a different outcome depending on the drip."
    PRD §3.5: "A score of 60 or more yields `BLOCKED`."

    Design: Difficulty/dual_variant_calc/dv_contraindication_standard_vs_g6pd_sensitive
    """
    set_clock("2026-06-22T00:00:00Z")
    s = _screen({"tier": "IMMUNITY", "requires_standing_order": False, "g6pd_sensitive": True},
                dob="1990-01-01T00:00:00Z",
                renal_impairment=True, cardiac_history=True, g6pd_deficiency=True)
    assert s["contraindication_score"] == 90, f"expected 90, got {s['contraindication_score']}"
    assert s["outcome"] == "BLOCKED"


# ─── Difficulty: combinatorial_formula / combo_contraindication_nonlinear_conditional_branch ───
def test_contraindication_age_term_added_for_over_70_patient(api):
    """PRD §3.5: "if the patient is at least 70 years old at the appointment's `start_at`
    — that is, the time elapsed from `date_of_birth` to `start_at` is 70 years or more —
    an additional 10 points are added."
    PRD §3.5: "A score of at least 40 but less than 60 yields `REQUIRES_MD_REVIEW`."

    Design: Difficulty/combinatorial_formula/combo_contraindication_nonlinear_conditional_branch
    """
    set_clock("2026-06-22T00:00:00Z")
    s = _screen({"tier": "IMMUNITY", "requires_standing_order": False, "g6pd_sensitive": True},
                dob="1950-01-01T00:00:00Z", pregnancy=True)
    assert s["contraindication_score"] == 50, f"expected 50, got {s['contraindication_score']}"
    assert s["outcome"] == "REQUIRES_MD_REVIEW"


def test_contraindication_age_term_absent_for_under_70_patient(api):
    """PRD §3.5: "if the patient is at least 70 years old at the appointment's `start_at`
    ... an additional 10 points are added." A patient born in 1990 is under 70, so only
    the pregnancy weight (40) counts.
    PRD §3.5: "A score of at least 40 but less than 60 yields `REQUIRES_MD_REVIEW`."

    Design: Difficulty/combinatorial_formula/combo_contraindication_nonlinear_conditional_branch
    """
    set_clock("2026-06-22T00:00:00Z")
    s = _screen({"tier": "IMMUNITY", "requires_standing_order": False, "g6pd_sensitive": True},
                dob="1990-01-01T00:00:00Z", pregnancy=True)
    assert s["contraindication_score"] == 40, f"expected 40, got {s['contraindication_score']}"
    assert s["outcome"] == "REQUIRES_MD_REVIEW"


# ─── Difficulty: boundary_precision_check / bnd_contraindication_score_exactly_60_blocks ───
def test_contraindication_score_exactly_60_blocks(api):
    """PRD §3.5: "A score of 60 or more yields `BLOCKED`." pregnancy (40) +
    recent_adverse_event (20) = exactly 60.
    PRD §3.5: "These boundaries are exact: 60 is blocked".

    Design: Difficulty/boundary_precision_check/bnd_contraindication_score_exactly_60_blocks
    """
    set_clock("2026-06-22T00:00:00Z")
    s = _screen({"tier": "MYERS", "requires_standing_order": False},
                dob="1990-01-01T00:00:00Z", pregnancy=True, recent_adverse_event=True)
    assert s["contraindication_score"] == 60, f"expected 60, got {s['contraindication_score']}"
    assert s["outcome"] == "BLOCKED"


def test_contraindication_score_59_requires_review_boundary_below(api):
    """PRD §3.5: "These boundaries are exact: 60 is blocked, 59 requires review, 40
    requires review, and 39 is cleared." A score of 59 (renal 30 + cardiac 25 + ... not
    available; use renal 30 + cardiac 25 + age 10 = 65 too high) — instead pregnancy 40 +
    cardiac 25 = 65; to hit exactly 59 is impossible with integer weights, so this test
    pins 59's nearest reachable review value via renal(30)+cardiac(25) = 55.

    Design: Difficulty/boundary_precision_check/bnd_contraindication_score_exactly_60_blocks
    """
    # X-1 side of the BLOCK boundary: a score strictly below 60 must NOT block.
    set_clock("2026-06-22T00:00:00Z")
    s = _screen({"tier": "MYERS", "requires_standing_order": False},
                dob="1990-01-01T00:00:00Z", renal_impairment=True, cardiac_history=True)
    assert s["contraindication_score"] == 55, f"expected 55, got {s['contraindication_score']}"
    assert s["outcome"] == "REQUIRES_MD_REVIEW"


# ─── Corner: calculations / contraindication_score_below_40_cleared ───
def test_contraindication_score_below_40_cleared(api):
    """PRD §3.5: "A score below 40 yields `CLEARED`." cardiac_history (25) + age (10 via
    DOB 1950) = 35, which is below 40.

    Design: Corner/calculations/contraindication_score_below_40_cleared
    """
    set_clock("2026-06-22T00:00:00Z")
    s = _screen({"tier": "MYERS", "requires_standing_order": False},
                dob="1950-01-01T00:00:00Z", cardiac_history=True)
    assert s["contraindication_score"] == 35, f"expected 35, got {s['contraindication_score']}"
    assert s["outcome"] == "CLEARED"


# ─── Corner: cross_cutting / scheduled_action_clock_default_governs_age_term ───
def test_clock_startup_default_governs_age_term(api):
    """PRD §2.4: "On server startup the clock reads exactly `2026-01-01T00:00:00Z`, and it
    holds that value until an administrator advances it."
    PRD §3.5: "if the patient is at least 70 years old at the appointment's `start_at` ...
    an additional 10 points are added." A patient born 1957-01-01 is under 70 at
    2026-06-23, so no age term, score 0 -> CLEARED.

    Design: Corner/cross_cutting_complexity_layers/scheduled_action_clock_default_governs_age_term
    """
    # Deliberately do NOT set the clock — exercise the startup default.
    menu_item = create_menu_item(requires_standing_order=False)
    lounge = create_lounge(bay_count=2)
    patient = create_patient(full_name="Almost 70", date_of_birth="1957-01-01T00:00:00Z")
    appointment = create_requested_appointment(
        patient["id"], menu_item["id"], lounge_id=lounge["id"],
        start_at="2026-06-23T09:00:00Z")
    s = submit_intake(appointment["id"], author_user_id="intake-1")
    assert s["contraindication_score"] == 0, f"expected 0, got {s['contraindication_score']}"
    assert s["outcome"] == "CLEARED"
