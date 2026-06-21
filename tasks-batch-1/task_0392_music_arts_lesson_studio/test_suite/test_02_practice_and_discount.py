"""Student practice metrics and the family discount tier engine.

Covers the dual-variant practice score (raw total vs decay-weighted), the tiered
family-discount selection, the discount recomputation on enrollment transitions, and
the wallet-credit aggregation.
"""
import pytest

from test_helpers import (
    validate_success,
    get_success_data,
    TEST_USERS,
    create_student_payload,
    create_wallet_credit_payload,
    setup_roster,
    setup_family_with_active_enrollments,
    set_clock,
    make_instructor_headers,
)

ADMIN = TEST_USERS["studio_admin_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


# ===========================================================================
# Difficulty / dual_variant_calc / practice_weighted_vs_raw_diverge
# ===========================================================================
class TestPracticeWeightedVsRaw:
    def _setup_two_logs(self, api):
        studio, family, student, instructor, room = setup_roster()
        sid = studio["id"]
        set_clock(sid, "2026-02-01T00:00:00.000Z")
        instr_hdr = make_instructor_headers(instructor["id"])
        get_success_data(
            api.create_practice_log(
                sid, student["id"], {"minutes": 60, "logged_utc": "2026-01-22T00:00:00.000Z"}, instr_hdr
            )
        )
        final = get_success_data(
            api.create_practice_log(
                sid, student["id"], {"minutes": 120, "logged_utc": "2026-02-01T00:00:00.000Z"}, instr_hdr
            )
        )
        return sid, student, final

    def test_total_practice_minutes_is_undecayed_sum(self, api):
        """PRD 3.7: "The `total_practice_minutes` is the raw, undecayed sum of `minutes`
        over all of the student's practice logs."

        Design: Difficulty/dual_variant_calc/practice_weighted_vs_raw_diverge
        """
        sid, student, final = self._setup_two_logs(api)
        assert final["total_practice_minutes"] == 180  # 60 + 120

    def test_weighted_progress_score_decays_older_log(self, api):
        """PRD 3.7: "That log contributes its `minutes` multiplied by the decay base of
        0.95 raised to the power of the age in days. The weighted score is the sum of
        those contributions across all logs, divided by 60 to convert minutes to hours,
        rounded half up to two decimal places."

        Design: Difficulty/dual_variant_calc/practice_weighted_vs_raw_diverge
        """
        sid, student, final = self._setup_two_logs(api)
        # (60 * 0.95**10 + 120 * 0.95**0) / 60 = round_half_up(.., 2) = 2.60.
        assert final["weighted_progress_score"] == pytest.approx(2.60, abs=0.001)
        assert final["total_practice_minutes"] != final["weighted_progress_score"] * 60


# ===========================================================================
# Difficulty / combinatorial_formula / family_discount_tier_selection
# ===========================================================================
class TestFamilyDiscountTierSelection:
    def test_three_active_enrollments_select_010_tier(self, api):
        """PRD 3.4: "To select the fraction, the system considers every tier whose
        `min_active_enrollments` is less than or equal to the current active count and
        chooses the one with the greatest `min_active_enrollments` among them". PRD 3.4:
        "Under the default tiers, a family with no active enrollments or one active
        enrollment gets a fraction of 0, two active enrollments get 0.05, three get
        0.10, and four or more get 0.15."

        Design: Difficulty/combinatorial_formula/family_discount_tier_selection
        """
        studio, family, enrollments = setup_family_with_active_enrollments(3)
        assert family["active_enrollment_count"] == 3
        assert family["family_discount_pct"] == pytest.approx(0.10, abs=0.0001)

    def test_two_active_enrollments_select_005_tier(self, api):
        """PRD 3.4: "Under the default tiers, a family with no active enrollments or one
        active enrollment gets a fraction of 0, two active enrollments get 0.05, three
        get 0.10, and four or more get 0.15."

        Design: Difficulty/combinatorial_formula/family_discount_tier_selection
        """
        studio, family, enrollments = setup_family_with_active_enrollments(2)
        assert family["active_enrollment_count"] == 2
        assert family["family_discount_pct"] == pytest.approx(0.05, abs=0.0001)


# ===========================================================================
# Corner / cross_cutting_complexity_layers / derived_discount_reconciles_on_cancel
# ===========================================================================
def test_derived_discount_reconciles_on_cancel(api):
    """PRD 3.4: "The fraction is recomputed on any enrollment transition into or out
    of `ACTIVE`, which is why activation, freeze, resume, and cancellation each list a
    discount recomputation among their effects." PRD 3.2: "Cancellation moves
    `lifecycle_status → CANCELLED` ... and the family's `active_enrollment_count` and
    `family_discount_pct` are recomputed."

    Design: Corner/cross_cutting_complexity_layers/derived_discount_reconciles_on_cancel
    """
    studio, family, enrollments = setup_family_with_active_enrollments(2)
    sid = studio["id"]
    assert family["family_discount_pct"] == pytest.approx(0.05, abs=0.0001)

    validate_success(api.cancel_enrollment(sid, enrollments[1]["id"], ADMIN), 200)
    after = validate_success(api.get_family(sid, family["id"], ADMIN), 200)
    assert after["active_enrollment_count"] == 1
    assert after["family_discount_pct"] == pytest.approx(0.0, abs=0.0001)


# ===========================================================================
# Corner / calculations / family_wallet_credit_accumulates
# ===========================================================================
def test_family_wallet_credit_accumulates(api):
    """PRD 2.8: "A family's `wallet_balance_cents` is a conserved quantity: it equals
    the sum of all wallet credits, minus the sum of `amount_cents` over the family's
    `SUCCEEDED` payments, plus the sum of `amount_cents` over the family's `REFUNDED`
    payments." PRD 3.1: "Prepaid funds reach a family through a wallet credit carrying
    an `amount_cents` value, which is added to `wallet_balance_cents`".

    Design: Corner/calculations/family_wallet_credit_accumulates
    """
    studio, family, student, instructor, room = setup_roster()
    sid, fid = studio["id"], family["id"]
    get_success_data(api.credit_wallet(sid, fid, create_wallet_credit_payload(3000), BILLING))
    after = validate_success(
        api.credit_wallet(sid, fid, create_wallet_credit_payload(2000), BILLING), 201
    )
    assert after["wallet_balance_cents"] == 5000
