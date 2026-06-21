"""Transitive cascade chain tests (PRD §2.6, §3.4 — clock→OVERDUE→Lien→
SUSPENDED; PRD §3.5 — Violation UPHELD→ACTIVE rollup→UNDER_REVIEW)."""
from test_helpers import (
    bootstrap_assessment_overdue_by_clock,
    bootstrap_violation_in_contested,
    get_property,
    list_liens_for_property,
    validate_success,
)
from test_helpers.test_users import make_board_secretary_headers


# ─────────────────────────────────────────────────────────────────────────────
# Rule 4 instance 1: clock advance → late fee → lien filed → property suspended
# ─────────────────────────────────────────────────────────────────────────────

def test_clock_advance_cascades_late_fee_then_files_lien_then_suspends(api):
    """PRD §3.4: "After the late-fee recomputation and the property-balance
    refresh, if `account_balance_cents` on the owning property is at least
    the community's `lien_threshold_cents` and no `FILED` `Lien` already
    exists on that property, the system files a `Lien` in the same atomic
    step. The new lien's `principal_at_filing_cents` is snapshotted from
    the property's then-current `account_balance_cents` at filing, its
    `filed_at` is stamped with `current_utc`, and its `status` is `FILED`.
    The same atomic step refreshes the property's `compliance_posture` to
    `SUSPENDED`."

    Setup: lien_threshold=250000, single SPECIAL assessment principal=250000
    due 2026-01-01. Clock advances to 2026-02-01: cycles=2,
    per_cycle=2500+floor(250000*1000/10000)=2500+25000=27500,
    late_fee=55000, outstanding=305000 → balance=305000 ≥ 250000 →
    Lien FILED and posture → SUSPENDED.

    Design: Difficulty/transitive_cascade/clock_advance_to_lien_to_property_suspension_depth_3
    """
    _community, _owner, prop, assessment = bootstrap_assessment_overdue_by_clock(
        community_name="LienVille",
        owner_email="d@x.com",
        owner_name="D",
        unit_label="U-4",
        principal_cents=250000,
        due_date="2026-01-01T00:00:00Z",
        advance_to="2026-02-01T00:00:00Z",
        kind="SPECIAL",
        lien_threshold_cents=250000,
    )
    assert assessment["status"] == "OVERDUE"
    assert assessment["late_fee_cents"] == 55000, (
        f"late_fee must be 55000 (2 cycles × (2500+25000)), "
        f"got {assessment['late_fee_cents']}"
    )
    prop_after = get_property(prop["id"])
    assert prop_after["account_balance_cents"] == 305000, (
        f"balance must be 305000 (principal 250000 + late fee 55000), "
        f"got {prop_after['account_balance_cents']}"
    )
    assert prop_after["compliance_posture"] == "SUSPENDED", (
        f"posture must be SUSPENDED after lien cascade, "
        f"got {prop_after['compliance_posture']}"
    )
    liens = list_liens_for_property(prop["id"])
    filed = [le for le in liens if le["status"] == "FILED"]
    assert len(filed) == 1, (
        f"exactly one FILED lien expected after cascade, got {len(filed)}"
    )
    assert filed[0]["principal_at_filing_cents"] == 305000, (
        f"lien snapshot must be 305000, got {filed[0]['principal_at_filing_cents']}"
    )


def test_clock_advance_does_not_create_lien_when_balance_below_threshold(api):
    """PRD §3.4: "After the late-fee recomputation and the property-balance
    refresh, if `account_balance_cents` on the owning property is at least
    the community's `lien_threshold_cents` and no `FILED` `Lien` already
    exists on that property, the system files a `Lien` in the same atomic
    step."

    The contrapositive: when the cascaded balance does NOT reach
    `lien_threshold_cents`, no lien is filed and posture stays COMPLIANT.
    Setup: lien_threshold=250000, principal=10000 due 2026-01-01, clock
    advances to 2026-02-01. cycles=2 → late_fee = 2*(2500 + 1000) = 7000,
    outstanding = 17000 < 250000 → no lien fired.

    Design: Difficulty/transitive_cascade/clock_advance_to_lien_to_property_suspension_depth_3
    """
    _community, _owner, prop, assessment = bootstrap_assessment_overdue_by_clock(
        community_name="NoCascade",
        owner_email="nd@x.com",
        owner_name="ND",
        unit_label="ND-1",
        principal_cents=10000,
        due_date="2026-01-01T00:00:00Z",
        advance_to="2026-02-01T00:00:00Z",
        kind="REGULAR",
        regular_assessment_cents=10000,
        lien_threshold_cents=250000,
    )
    assert assessment["status"] == "OVERDUE"
    prop_after = get_property(prop["id"])
    assert prop_after["account_balance_cents"] < 250000, (
        f"balance must be < threshold for negative-cascade case, "
        f"got {prop_after['account_balance_cents']}"
    )
    assert prop_after["compliance_posture"] == "COMPLIANT", (
        f"posture must remain COMPLIANT, got {prop_after['compliance_posture']}"
    )
    assert list_liens_for_property(prop["id"]) == [], (
        "no lien should be filed when balance is below threshold"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Rule 4 instance 2: Violation CONTESTED→UPHELD cascades to UNDER_REVIEW
# ─────────────────────────────────────────────────────────────────────────────

def test_violation_upheld_promotes_active_and_posture_under_review(api):
    """PRD §3.5: "From `CONTESTED`, the `BoardSecretary` adjudicates:
    upholding moves the violation to the `UPHELD` lifecycle state and
    additionally promotes its compliance-rollup status to `ACTIVE`, which
    is the trigger for `compliance_posture` to read `UNDER_REVIEW` on the
    owning property unless a filed lien already pushes it to `SUSPENDED`."

    Setup: Violation in CONTESTED on a property with no liens (posture
    starts COMPLIANT). Uphold the violation → ACTIVE rollup → posture
    UNDER_REVIEW.

    Design: Difficulty/transitive_cascade/violation_uphold_to_active_to_property_under_review_depth_2
    """
    _community, _owner, prop, violation = bootstrap_violation_in_contested(
        community_name="Posture Ville", category="NOISE",
    )
    upheld = validate_success(
        api.uphold_violation(violation["id"], make_board_secretary_headers()),
        expected_status=200,
    )
    assert upheld["status"] in {"UPHELD", "ACTIVE"}, (
        f"upheld violation should report UPHELD or its synthetic ACTIVE rollup, "
        f"got {upheld['status']}"
    )
    prop_after = get_property(prop["id"])
    assert prop_after["compliance_posture"] == "UNDER_REVIEW", (
        f"posture must cascade to UNDER_REVIEW after UPHELD, "
        f"got {prop_after['compliance_posture']}"
    )


def test_dismissed_violation_does_not_set_posture_under_review(api):
    """PRD §3.5: "Dismissing moves the violation to `DISMISSED` (terminal)
    and refreshes the property's `compliance_posture`, which will revert
    to `COMPLIANT` if no other rolled-up active violations remain."

    Contrast case for the UPHELD cascade: a CONTESTED violation that is
    DISMISSED instead of UPHELD must NOT push the property to UNDER_REVIEW
    — the property reverts to COMPLIANT.

    Design: Difficulty/transitive_cascade/violation_uphold_to_active_to_property_under_review_depth_2
    """
    _community, _owner, prop, violation = bootstrap_violation_in_contested(
        community_name="Dismiss Ville", category="PARKING",
    )
    dismissed = validate_success(
        api.dismiss_violation(violation["id"], make_board_secretary_headers()),
        expected_status=200,
    )
    assert dismissed["status"] == "DISMISSED"
    prop_after = get_property(prop["id"])
    assert prop_after["compliance_posture"] == "COMPLIANT", (
        f"posture must revert to COMPLIANT after DISMISSED with no other "
        f"ACTIVE violations, got {prop_after['compliance_posture']}"
    )
