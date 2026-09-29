"""Conference-level derivations (PRD sections 2.10 and 3.3)."""

import calc


def derive_reserve_posture(conference):
    """Re-run the posture derivation in place; the caller owns the version bump."""
    target, posture, funded_ratio_bps = calc.reserve_posture(
        conference["approved_operating_expense_cents"],
        conference["reserve_balance_cents"],
    )
    conference["reserve_target_cents"] = target
    conference["reserve_posture"] = posture
    conference["funded_ratio_bps"] = funded_ratio_bps
