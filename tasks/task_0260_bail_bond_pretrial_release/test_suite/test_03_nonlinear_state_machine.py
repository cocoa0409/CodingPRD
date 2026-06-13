"""Non-linear state machine: the cyclic forfeiture/recovery/reinstate loop and
the parallel coverage_status x settlement_status axes on a bond.
"""
from test_helpers import (
    validate_success,
    setup_active_surety_bond, setup_recovery_open_bond,
    TEST_USERS,
)

OFFICER = TEST_USERS["compliance_officer_headers"]


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/forfeiture_proceeding_recovery_reinstate_cycle
# ---------------------------------------------------------------------------
def test_reinstate_sets_proceeding_reinstated(api):
    """PRD 3.6: "a `ComplianceOfficer` reinstates the bond, advancing the
    proceeding `RECOVERY_OPEN → REINSTATED` and cascading the bond
    `FORFEITED → ACTIVE`."

    Design: Difficulty/non_linear_state_machine/forfeiture_proceeding_recovery_reinstate_cycle
    """
    scen = setup_recovery_open_bond(bail_amount_cents=1_000_000, liability_share_cents=1_000_000)
    proc = validate_success(api.reinstate(scen["def_id"], scen["proc_id"], OFFICER))
    assert proc["status"] == "REINSTATED", proc["status"]


def test_reinstate_cascades_bond_back_to_active(api):
    """PRD 3.6: "If recovery succeeds in time, a `ComplianceOfficer` reinstates the
    bond, advancing the proceeding `RECOVERY_OPEN → REINSTATED` and cascading the
    bond `FORFEITED → ACTIVE`."

    Design: Difficulty/non_linear_state_machine/forfeiture_proceeding_recovery_reinstate_cycle
    """
    scen = setup_recovery_open_bond(bail_amount_cents=1_000_000, liability_share_cents=1_000_000)
    validate_success(api.reinstate(scen["def_id"], scen["proc_id"], OFFICER))
    bond = validate_success(api.get_bond(scen["bond_id"], OFFICER))
    assert bond["coverage_status"] == "ACTIVE", bond["coverage_status"]


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/bond_parallel_coverage_and_settlement_dimensions
# ---------------------------------------------------------------------------
def test_activation_moves_both_axes(api):
    """PRD 3.2: "The pivotal transition is activation by the posting `BondsAgent`,
    which advances the bond `DRAFT → ACTIVE`."
    PRD 3.2: "The system stamps `posted_at` to the current system clock, recomputes
    `premium_cents` and `required_collateral_cents`, and sets `settlement_status` to
    `PREMIUM_COLLECTED`."

    Coverage reaches ACTIVE while settlement reaches PREMIUM_COLLECTED — independent
    axes advancing in the one activation request.

    Design: Difficulty/non_linear_state_machine/bond_parallel_coverage_and_settlement_dimensions
    """
    scen = setup_active_surety_bond(bail_amount_cents=1_000_000, liability_share_cents=1_000_000)
    bond = scen["bond"]
    assert bond["coverage_status"] == "ACTIVE", bond["coverage_status"]
    assert bond["settlement_status"] == "PREMIUM_COLLECTED", bond["settlement_status"]


def test_exoneration_moves_both_axes_independently(api):
    """PRD 3.7: "A `ComplianceOfficer` exonerates a bond, advancing it
    `ACTIVE → EXONERATED`."
    PRD 3.7: "Exoneration sets the bond's `settlement_status` to
    `COLLATERAL_REFUNDED`."

    Coverage reaches EXONERATED while settlement reaches COLLATERAL_REFUNDED — two
    independent axes.

    Design: Difficulty/non_linear_state_machine/bond_parallel_coverage_and_settlement_dimensions
    """
    scen = setup_active_surety_bond(bail_amount_cents=1_000_000, liability_share_cents=1_000_000)
    exon = validate_success(api.exonerate_bond(scen["def_id"], scen["bond_id"], OFFICER))
    assert exon["coverage_status"] == "EXONERATED", exon["coverage_status"]
    assert exon["settlement_status"] == "COLLATERAL_REFUNDED", exon["settlement_status"]
