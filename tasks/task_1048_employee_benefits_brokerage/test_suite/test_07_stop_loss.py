"""Wellness and stop-loss recovery: strict attachment threshold and wellness credit."""
from test_helpers import validate_success, TEST_USERS
from test_helpers import fixtures as fx

CONSULTANT = TEST_USERS["consultant_headers"]


# ===========================================================================
# Difficulty / boundary_precision_check — strict attachment threshold
# ===========================================================================
def test_reimbursement_zero_at_exact_attachment_point(api):
    """PRD §3.8: "The reimbursed_cents is the greater of zero and the cumulative claims
    minus the attachment point; the attachment threshold is strict, so cumulative claims
    exactly equal to the attachment point yield zero reimbursement, and reimbursement accrues
    only on the excess strictly above it."

    Design: Difficulty/boundary_precision_check/stop_loss_attachment_strict_boundary
    """
    client = fx.create_client(legal_name="Lambda Co", industry="MANUFACTURING")
    sl = fx.create_stop_loss(client["id"], attachment_point_cents=5_000_000,
                             wellness_credit_pct=0.05)
    fx.record_claim(sl["id"], 4_999_999)
    result = validate_success(api.record_claim(sl["id"], {"claim_amount_cents": 1}, CONSULTANT))
    assert result["cumulative_claims_cents"] == 5_000_000
    assert result["reimbursed_cents"] == 0


def test_reimbursement_accrues_one_cent_above_attachment(api):
    """PRD §3.8: "The reimbursed_cents is the greater of zero and the cumulative claims
    minus the attachment point; the attachment threshold is strict, so cumulative claims
    exactly equal to the attachment point yield zero reimbursement, and reimbursement accrues
    only on the excess strictly above it."

    Design: Difficulty/boundary_precision_check/stop_loss_attachment_strict_boundary
    """
    client = fx.create_client(legal_name="Lambda Co", industry="MANUFACTURING")
    sl = fx.create_stop_loss(client["id"], attachment_point_cents=5_000_000,
                             wellness_credit_pct=0.05)
    fx.record_claim(sl["id"], 4_999_999)
    fx.record_claim(sl["id"], 1)  # cumulative exactly 5,000,000
    result = validate_success(api.record_claim(sl["id"], {"claim_amount_cents": 1}, CONSULTANT))
    assert result["cumulative_claims_cents"] == 5_000_001
    assert result["reimbursed_cents"] == 1


# ===========================================================================
# Corner / cross_cutting — wellness credit below attachment
# ===========================================================================
def test_wellness_credit_computed_below_attachment(api):
    """PRD §3.8: "The wellness_credit_cents is the wellness-credit fraction multiplied by
    the cumulative claims, rounded half-up to whole cents. The total_recovery_cents is the
    sum of reimbursed_cents and wellness_credit_cents."

    Design: Corner/cross_cutting_complexity_layers/stop_loss_wellness_credit_computed
    """
    client = fx.create_client(legal_name="Wellness Co", industry="MANUFACTURING")
    sl = fx.create_stop_loss(client["id"], attachment_point_cents=5_000_000,
                             wellness_credit_pct=0.05)
    result = validate_success(api.record_claim(
        sl["id"], {"claim_amount_cents": 1_000_000}, CONSULTANT))
    assert result["reimbursed_cents"] == 0
    assert result["wellness_credit_cents"] == 50_000
    assert result["total_recovery_cents"] == 50_000
