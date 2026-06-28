"""Multi-hop cascades (cancel -> recapture -> treaty; settle -> loss -> suspend) and
conserved-quantity invariants (cession+recapture; investigate+deny).

Covers difficulty queue (A) rules transitive_cascade and compensating_invariant, plus the
corner queue (B) endpoint/consistency exposure-reconciliation instances.
"""
import pytest
from test_helpers import (
    validate_success,
    get_success_data,
    create_cession_payload,
    setup_active_bond,
    setup_active_cession,
    setup_investigating_claim,
    setup_filed_claim,
    create_principal_with_indemnity,
    create_program,
    create_treaty,
    UW,
    CE,
)


# ─── transitive_cascade: cancel -> recapture -> treaty + program (depth 3) ─────

def test_cancel_cascades_recapture_treaty_and_releases_program(api):
    """PRD §3.5: "cancellation decrements the program's `aggregate_committed_cents` by this
    bond's `net_retained_cents` measured before any recapture, then drives every `ACTIVE`
    cession on the bond to `RECAPTURED`, decrementing each affected treaty's
    `ceded_committed_cents` by that cession's ceded amount; finally the bond moves to
    `CANCELLED`."

    Design: Difficulty/transitive_cascade/bond_cancel_cascades_recapture_treaty_and_program_depth3
    """
    prog = create_program(name="P7")
    treaty = create_treaty(name="T7", cession_pct_bps=3000, treaty_capacity_cents=10_000_000)
    prin, _ = create_principal_with_indemnity(
        legal_name="Zeta", credit_score=760, working_capital_cents=5_000_000
    )
    _, bond, treaty, cession = setup_active_cession(
        program=prog, treaty=treaty,
        bond=setup_active_bond(
            program=prog, principal=prin,
            app_overrides={"bond_type": "BID", "requested_penal_sum_cents": 12_000_000,
                           "term_months": 12},
        )[3],
    )
    # cession = 30% of 12M = 3,600,000.
    assert cession["ceded_penal_sum_cents"] == 3_600_000

    res = api.cancel_bond(bond["id"], {"cancel_mode": "PRO_RATA"}, UW)
    cancelled = validate_success(res, 200)
    assert cancelled["status"] == "CANCELLED"
    # B: cession recaptured (caused by cancel).
    cession_after = validate_success(api.get_cession(cession["id"], UW), 200)
    assert cession_after["status"] == "RECAPTURED"
    # C: treaty ceded released to 0 (caused by recapture).
    treaty_after = validate_success(api.get_treaty(treaty["id"], UW), 200)
    assert treaty_after["ceded_committed_cents"] == 0
    # Program net_retained released before recapture -> committed back to 0.
    prog_after = validate_success(api.get_program(prog["id"], UW), 200)
    assert prog_after["aggregate_committed_cents"] == 0


def test_settle_pay_cascades_incurred_loss_then_program_suspend(api):
    """PRD §3.7: "After the bond's loss is recomputed, the loss cascade reaches the program:
    the program's cumulative incurred loss, the sum of `incurred_loss_cents` over all the
    program's bonds, is recomputed, and if that total is at or above the program's
    `loss_alert_threshold_cents`, the program is driven to `SUSPENDED` as the terminal hop of
    the settlement".

    Design: Difficulty/transitive_cascade/claim_settle_pay_cascades_incurred_loss_then_program_suspend_depth3
    """
    prog = create_program(name="P8", aggregate_limit_cents=50_000_000,
                          loss_alert_threshold_cents=2_000_000)
    prin, _ = create_principal_with_indemnity(
        legal_name="Eta", credit_score=700, working_capital_cents=1_000_000
    )
    _, bond, claim = setup_investigating_claim(
        program=prog,
        bond=setup_active_bond(
            program=prog, principal=prin,
            app_overrides={"bond_type": "PERFORMANCE",
                           "requested_penal_sum_cents": 3_000_000, "term_months": 12},
        )[3],
        claim_overrides={"claimant_name": "Obligee Y", "demand_cents": 5_000_000,
                         "reserve_cents": 4_500_000},
        investigate_reserve=4_500_000,
    )
    res = api.settle_claim(
        claim["id"], {"outcome": "PAY", "paid_loss_cents": 2_900_000, "salvage_cents": 0}, CE
    )
    settled = validate_success(res, 200)
    assert settled["status"] == "PAID"
    # B: bond incurred loss = paid 2,900,000 net of 0 salvage.
    bond_after = validate_success(api.get_bond(bond["id"], UW), 200)
    assert bond_after["incurred_loss_cents"] == 2_900_000
    # C: cumulative loss 2,900,000 >= threshold 2,000,000 -> program SUSPENDED.
    prog_after = validate_success(api.get_program(prog["id"], UW), 200)
    assert prog_after["status"] == "SUSPENDED"


# ─── compensating_invariant: cession then recapture conserves penal sum ────────

def test_cession_then_recapture_conserves_total_penal_sum(api):
    """PRD §3.5: "Recapture decrements the treaty's `ceded_committed_cents` by the cession's
    ceded amount, recomputes the bond's `ceded_penal_sum_cents` so its `net_retained_cents`
    rises, raises the program's `aggregate_committed_cents` by that rise in retained exposure,
    and moves the cession to `RECAPTURED`, which is terminal. Recapture conserves total penal
    sum: it simply returns retained exposure to the program and frees the treaty capacity the
    cession had been holding."

    Design: Difficulty/compensating_invariant/cession_then_recapture_conserves_total_penal_sum
    """
    prog = create_program(name="P17")
    treaty = create_treaty(name="T17", cession_pct_bps=3000, treaty_capacity_cents=10_000_000)
    prin, _ = create_principal_with_indemnity(
        legal_name="Pi", credit_score=760, working_capital_cents=5_000_000
    )
    _, bond, treaty, cession = setup_active_cession(
        program=prog, treaty=treaty,
        bond=setup_active_bond(
            program=prog, principal=prin,
            app_overrides={"bond_type": "BID", "requested_penal_sum_cents": 12_000_000,
                           "term_months": 12},
        )[3],
    )
    # After cession: net_retained 8,400,000; program committed 8,400,000; treaty ceded 3,600,000.
    bond_mid = validate_success(api.get_bond(bond["id"], UW), 200)
    assert bond_mid["net_retained_cents"] == 8_400_000
    prog_mid = validate_success(api.get_program(prog["id"], UW), 200)
    assert prog_mid["aggregate_committed_cents"] == 8_400_000
    treaty_mid = validate_success(api.get_treaty(treaty["id"], UW), 200)
    assert treaty_mid["ceded_committed_cents"] == 3_600_000
    assert prog_mid["aggregate_committed_cents"] + treaty_mid["ceded_committed_cents"] == 12_000_000

    res = api.recapture_cession(cession["id"], UW)
    recaptured = validate_success(res, 200)
    assert recaptured["status"] == "RECAPTURED"
    # After recapture: net_retained back to 12,000,000; program 12,000,000; treaty 0.
    bond_after = validate_success(api.get_bond(bond["id"], UW), 200)
    assert bond_after["net_retained_cents"] == 12_000_000
    prog_after = validate_success(api.get_program(prog["id"], UW), 200)
    assert prog_after["aggregate_committed_cents"] == 12_000_000
    treaty_after = validate_success(api.get_treaty(treaty["id"], UW), 200)
    assert treaty_after["ceded_committed_cents"] == 0
    assert prog_after["aggregate_committed_cents"] + treaty_after["ceded_committed_cents"] == 12_000_000


def test_investigate_then_deny_conserves_bond_incurred_loss(api):
    """PRD §3.6: "The investigate call carries an updated `reserve_cents`, which replaces the
    claim's reserve, and the bond's `incurred_loss_cents` is recomputed to reflect the revised
    estimate."
    PRD §3.7: "When the `outcome` is to deny, the claim simply moves to `DENIED` and the
    bond's `incurred_loss_cents` is recomputed by removing this claim's reserve and adding
    nothing in its place."

    Design: Difficulty/compensating_invariant/claim_investigate_then_deny_conserves_bond_incurred_loss
    """
    prog = create_program(name="P18")
    prin, _ = create_principal_with_indemnity(
        legal_name="Rho", credit_score=700, working_capital_cents=1_000_000
    )
    _, bond, claim = setup_investigating_claim(
        program=prog,
        bond=setup_active_bond(
            program=prog, principal=prin,
            app_overrides={"bond_type": "PERFORMANCE",
                           "requested_penal_sum_cents": 5_000_000, "term_months": 12},
        )[3],
        claim_overrides={"claimant_name": "Obligee U", "demand_cents": 700_000,
                         "reserve_cents": 600_000},
        investigate_reserve=600_000,
    )
    # After investigate: incurred loss = reserve 600,000.
    bond_mid = validate_success(api.get_bond(bond["id"], UW), 200)
    assert bond_mid["incurred_loss_cents"] == 600_000

    res = api.settle_claim(claim["id"], {"outcome": "DENY"}, CE)
    denied = validate_success(res, 200)
    assert denied["status"] == "DENIED"
    # After deny: reserve removed, nothing added -> back to 0.
    bond_after = validate_success(api.get_bond(bond["id"], UW), 200)
    assert bond_after["incurred_loss_cents"] == 0


# ─── Second-angle difficulty tests (>=2 per instance) ─────────────────────────

def test_expire_cascades_recapture_treaty_and_releases_program(api):
    """PRD §3.5: "every `ACTIVE` cession on the bond is driven to `RECAPTURED` with the
    corresponding treaty `ceded_committed_cents` decrements; and the bond moves to `EXPIRED`."
    PRD §3.5: "the program's `aggregate_committed_cents` is decremented by the bond's
    `net_retained_cents` measured before recapture".

    Design: Difficulty/transitive_cascade/bond_cancel_cascades_recapture_treaty_and_program_depth3
    """
    prog = create_program(name="P7b")
    treaty = create_treaty(name="T7b", cession_pct_bps=3000, treaty_capacity_cents=10_000_000)
    prin, _ = create_principal_with_indemnity(
        legal_name="Zeta2", credit_score=760, working_capital_cents=5_000_000
    )
    _, bond, treaty, cession = setup_active_cession(
        program=prog, treaty=treaty,
        bond=setup_active_bond(
            program=prog, principal=prin,
            app_overrides={"bond_type": "BID", "requested_penal_sum_cents": 12_000_000,
                           "term_months": 12},
        )[3],
    )
    assert cession["ceded_penal_sum_cents"] == 3_600_000
    res = api.expire_bond(bond["id"], UW)
    expired = validate_success(res, 200)
    assert expired["status"] == "EXPIRED"
    cession_after = validate_success(api.get_cession(cession["id"], UW), 200)
    assert cession_after["status"] == "RECAPTURED"
    treaty_after = validate_success(api.get_treaty(treaty["id"], UW), 200)
    assert treaty_after["ceded_committed_cents"] == 0
    prog_after = validate_success(api.get_program(prog["id"], UW), 200)
    assert prog_after["aggregate_committed_cents"] == 0


def test_settle_pay_below_threshold_does_not_suspend_program(api):
    """PRD §3.7: "the program's cumulative incurred loss, the sum of `incurred_loss_cents` over
    all the program's bonds, is recomputed, and if that total is at or above the program's
    `loss_alert_threshold_cents`, the program is driven to `SUSPENDED` as the terminal hop of
    the settlement".

    Design: Difficulty/transitive_cascade/claim_settle_pay_cascades_incurred_loss_then_program_suspend_depth3
    """
    # Loss-alert threshold high enough that the paid loss stays strictly below it.
    prog = create_program(name="P8b", aggregate_limit_cents=50_000_000,
                          loss_alert_threshold_cents=5_000_000)
    prin, _ = create_principal_with_indemnity(
        legal_name="Eta2", credit_score=700, working_capital_cents=1_000_000
    )
    _, bond, claim = setup_investigating_claim(
        program=prog,
        bond=setup_active_bond(
            program=prog, principal=prin,
            app_overrides={"bond_type": "PERFORMANCE",
                           "requested_penal_sum_cents": 5_000_000, "term_months": 12},
        )[3],
        claim_overrides={"claimant_name": "Obligee Y2", "demand_cents": 5_000_000,
                         "reserve_cents": 1_000_000},
        investigate_reserve=1_000_000,
    )
    res = api.settle_claim(
        claim["id"], {"outcome": "PAY", "paid_loss_cents": 1_000_000, "salvage_cents": 0}, CE
    )
    settled = validate_success(res, 200)
    assert settled["status"] == "PAID"
    bond_after = validate_success(api.get_bond(bond["id"], UW), 200)
    assert bond_after["incurred_loss_cents"] == 1_000_000
    # 1,000,000 < 5,000,000 threshold -> program stays OPEN.
    prog_after = validate_success(api.get_program(prog["id"], UW), 200)
    assert prog_after["status"] == "OPEN"


def test_cession_alone_partitions_penal_sum_invariant(api):
    """PRD §2.6: "A bond's own retained exposure is `net_retained_cents`, equal to its
    `penal_sum_cents` minus its `ceded_penal_sum_cents`, where `ceded_penal_sum_cents` is the
    sum of the ceded amounts over the bond's `ACTIVE` cessions."
    PRD §3.5: "the treaty's `ceded_committed_cents` rises by the ceded amount, the bond's
    `ceded_penal_sum_cents` rises and its `net_retained_cents` correspondingly falls, and the
    program's `aggregate_committed_cents` falls by the reduction in the bond's
    `net_retained_cents`."

    Design: Difficulty/compensating_invariant/cession_then_recapture_conserves_total_penal_sum
    """
    prog = create_program(name="P17b")
    treaty = create_treaty(name="T17b", cession_pct_bps=3000, treaty_capacity_cents=10_000_000)
    prin, _ = create_principal_with_indemnity(
        legal_name="Pi2", credit_score=760, working_capital_cents=5_000_000
    )
    _, bond, treaty, cession = setup_active_cession(
        program=prog, treaty=treaty,
        bond=setup_active_bond(
            program=prog, principal=prin,
            app_overrides={"bond_type": "BID", "requested_penal_sum_cents": 12_000_000,
                           "term_months": 12},
        )[3],
    )
    bond_after = validate_success(api.get_bond(bond["id"], UW), 200)
    prog_after = validate_success(api.get_program(prog["id"], UW), 200)
    treaty_after = validate_success(api.get_treaty(treaty["id"], UW), 200)
    # Partition invariant: program retained + treaty ceded == full penal sum.
    assert bond_after["net_retained_cents"] == 8_400_000
    assert prog_after["aggregate_committed_cents"] == 8_400_000
    assert treaty_after["ceded_committed_cents"] == 3_600_000
    assert (prog_after["aggregate_committed_cents"]
            + treaty_after["ceded_committed_cents"]) == 12_000_000


def test_investigate_revised_reserve_then_deny_returns_to_zero(api):
    """PRD §3.6: "The investigate call carries an updated `reserve_cents`, which replaces the
    claim's reserve, and the bond's `incurred_loss_cents` is recomputed to reflect the revised
    estimate."
    PRD §3.7: "When the `outcome` is to deny, the claim simply moves to `DENIED` and the
    bond's `incurred_loss_cents` is recomputed by removing this claim's reserve and adding
    nothing in its place."

    Design: Difficulty/compensating_invariant/claim_investigate_then_deny_conserves_bond_incurred_loss
    """
    prog = create_program(name="P18b")
    prin, _ = create_principal_with_indemnity(
        legal_name="Rho2", credit_score=700, working_capital_cents=1_000_000
    )
    _, _, _, bond = setup_active_bond(
        program=prog, principal=prin,
        app_overrides={"bond_type": "PERFORMANCE", "requested_penal_sum_cents": 5_000_000,
                       "term_months": 12},
    )
    claim = get_success_data(
        api.create_claim(
            {"bond_id": bond["id"], "claimant_name": "Obligee U2", "demand_cents": 900_000,
             "reserve_cents": 500_000}, CE
        )
    )
    # Investigate revises reserve up to 750,000.
    get_success_data(api.investigate_claim(claim["id"], {"reserve_cents": 750_000}, CE))
    bond_mid = validate_success(api.get_bond(bond["id"], UW), 200)
    assert bond_mid["incurred_loss_cents"] == 750_000
    # Deny removes the reserve; nothing added.
    denied = validate_success(api.settle_claim(claim["id"], {"outcome": "DENY"}, CE), 200)
    assert denied["status"] == "DENIED"
    bond_after = validate_success(api.get_bond(bond["id"], UW), 200)
    assert bond_after["incurred_loss_cents"] == 0


# ─── Corner (B): exposure reconciliation and immediate consistency ─────────────

def test_aggregate_available_reconciles_after_cession(api):
    """PRD §2.6: "The available figure, `aggregate_available_cents`, is the program's
    `aggregate_limit_cents` minus its `aggregate_committed_cents`."
    PRD §3.5: "the bond's `ceded_penal_sum_cents` rises and its `net_retained_cents`
    correspondingly falls, and the program's `aggregate_committed_cents` falls by the
    reduction in the bond's `net_retained_cents`."

    Design: Corner/cross_cutting_complexity_layers/derived_aggregate_available_reconciles_after_cession
    """
    prog = create_program(name="CC2", aggregate_limit_cents=50_000_000)
    treaty = create_treaty(name="TCC2", cession_pct_bps=2500, treaty_capacity_cents=10_000_000)
    prin, _ = create_principal_with_indemnity(
        legal_name="CC2Prin", credit_score=760, working_capital_cents=5_000_000
    )
    _, _, _, bond = setup_active_bond(
        program=prog, principal=prin,
        app_overrides={"bond_type": "BID", "requested_penal_sum_cents": 8_000_000,
                       "term_months": 12},
    )
    prog_before = validate_success(api.get_program(prog["id"], UW), 200)
    # Before cession: available = 50,000,000 - 8,000,000.
    assert prog_before["aggregate_available_cents"] == 42_000_000

    get_success_data(api.create_cession(create_cession_payload(bond["id"], treaty["id"]), UW))
    prog_after = validate_success(api.get_program(prog["id"], UW), 200)
    # After cession: net_retained dropped to 6,000,000 -> available = 50M - 6M.
    assert prog_after["aggregate_available_cents"] == 44_000_000


def test_bind_immediately_reflected_in_program_committed(api):
    """PRD §3.4: "As a cross-entity effect, the program's `aggregate_committed_cents` rises by
    the new bond's `net_retained_cents`, which at issuance equals the full penal sum since
    nothing is yet ceded."

    Design: Corner/consistency_model/immediate_consistency_bind_response_reflects_committed_exposure
    """
    prog = create_program(name="CM1")
    prin, _ = create_principal_with_indemnity(
        legal_name="CM1Prin", credit_score=700, working_capital_cents=1_000_000
    )
    # Bind (ISSUED, not yet issued/active) -> committed should already reflect penal sum.
    _, _, _, bond = setup_active_bond(  # active is a superset; committed includes ISSUED+ACTIVE
        program=prog, principal=prin,
        app_overrides={"bond_type": "PERFORMANCE", "requested_penal_sum_cents": 5_000_000,
                       "term_months": 12},
    )
    prog_after = validate_success(api.get_program(prog["id"], UW), 200)
    assert prog_after["aggregate_committed_cents"] == 5_000_000
