"""State-machine forks, GIA signature lifecycle, and invalid/terminal-state transitions.

Covers difficulty queue (A) rule non_linear_state_machine, plus the corner queue (B)
state_machines section.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_indemnity_agreement_payload,
    create_application_payload,
    setup_submitted_application,
    setup_active_bond,
    setup_filed_claim,
    create_principal,
    create_principal_with_indemnity,
    create_program,
    UW,
    CE,
)


# ─── non_linear_state_machine: BondApplication SUBMITTED fork ──────────────────

def test_submitted_application_refer_branch(api):
    """PRD §3.3: "Alternatively, the underwriter may refer the submitted application, moving
    it to `REFERRED` and handing authority to the senior tier; referral is valid only from
    `SUBMITTED`."

    Design: Difficulty/non_linear_state_machine/bond_application_branching_fork_submitted
    """
    prog = create_program(name="P5", referral_threshold_cents=25_000_000)
    prin, _ = create_principal_with_indemnity(
        legal_name="Delta", credit_score=700, working_capital_cents=1_000_000
    )
    _, _, app = setup_submitted_application(
        program=prog, principal=prin,
        app_overrides={"bond_type": "PERFORMANCE", "requested_penal_sum_cents": 5_000_000,
                       "term_months": 12},
    )
    res = api.refer_application(app["id"], UW)
    referred = validate_success(res, 200)
    assert referred["status"] == "REFERRED"


def test_submitted_application_approve_branch(api):
    """PRD §3.3: "A front-line underwriter may approve it directly, but only when the
    requested penal sum is strictly below the program's `referral_threshold_cents`".

    Design: Difficulty/non_linear_state_machine/bond_application_branching_fork_submitted
    """
    prog = create_program(name="P5b", referral_threshold_cents=25_000_000,
                          single_limit_cents=20_000_000)
    prin, _ = create_principal_with_indemnity(
        legal_name="Delta2", credit_score=700, working_capital_cents=1_000_000
    )
    _, _, app = setup_submitted_application(
        program=prog, principal=prin,
        app_overrides={"bond_type": "PERFORMANCE", "requested_penal_sum_cents": 5_000_000,
                       "term_months": 12},
    )
    res = api.approve_application(app["id"], UW)
    approved = validate_success(res, 200)
    assert approved["status"] == "APPROVED"


def test_submitted_application_decline_branch_records_reason(api):
    """PRD §3.3: "Either underwriter may decline instead: a decline is valid when the
    application is in either `SUBMITTED` or `REFERRED` status, records the supplied
    `decline_reason`, and moves the application to `DECLINED`".

    Design: Difficulty/non_linear_state_machine/bond_application_branching_fork_submitted
    """
    prog = create_program(name="P5c")
    prin, _ = create_principal_with_indemnity(
        legal_name="Delta3", credit_score=700, working_capital_cents=1_000_000
    )
    _, _, app = setup_submitted_application(
        program=prog, principal=prin,
        app_overrides={"bond_type": "PERFORMANCE", "requested_penal_sum_cents": 5_000_000,
                       "term_months": 12},
    )
    res = api.decline_application(app["id"], {"decline_reason": "CREDIT"}, UW)
    declined = validate_success(res, 200)
    assert declined["status"] == "DECLINED"
    assert declined["decline_reason"] == "CREDIT"


# ─── non_linear_state_machine: Bond ACTIVE divergent terminals ─────────────────

def test_active_bond_expire_branch_fully_earns_premium(api):
    """PRD §3.5: "On expiry the bond's `earned_premium_cents` is set equal to its full
    `written_premium_cents`, since a bond run to term is fully earned".

    Design: Difficulty/non_linear_state_machine/bond_branching_active_divergent_terminals
    """
    prog = create_program(name="P6")
    prin, _ = create_principal_with_indemnity(
        legal_name="Epsilon", credit_score=700, working_capital_cents=1_000_000
    )
    # STANDARD/PERFORMANCE penal 5M, no surcharge -> rate 225 -> written = 112500.
    _, _, _, bond = setup_active_bond(
        program=prog, principal=prin,
        app_overrides={"bond_type": "PERFORMANCE", "requested_penal_sum_cents": 5_000_000,
                       "term_months": 12},
    )
    assert bond["written_premium_cents"] == 112_500
    res = api.expire_bond(bond["id"], UW)
    expired = validate_success(res, 200)
    assert expired["status"] == "EXPIRED"
    assert expired["earned_premium_cents"] == 112_500


def test_active_bond_cancel_branch_reaches_cancelled(api):
    """PRD §3.5: "After computing earned premium, cancellation decrements the program's
    `aggregate_committed_cents` by this bond's `net_retained_cents` measured before any
    recapture, then drives every `ACTIVE` cession on the bond to `RECAPTURED` ... finally the
    bond moves to `CANCELLED`."

    Design: Difficulty/non_linear_state_machine/bond_branching_active_divergent_terminals
    """
    prog = create_program(name="P6b")
    prin, _ = create_principal_with_indemnity(
        legal_name="Epsilon2", credit_score=700, working_capital_cents=1_000_000
    )
    _, _, _, bond = setup_active_bond(
        program=prog, principal=prin,
        app_overrides={"bond_type": "PERFORMANCE", "requested_penal_sum_cents": 5_000_000,
                       "term_months": 12},
    )
    res = api.cancel_bond(bond["id"], {"cancel_mode": "PRO_RATA"}, UW)
    cancelled = validate_success(res, 200)
    assert cancelled["status"] == "CANCELLED"


# ─── Corner (B) state_machines ─────────────────────────────────────────────────

def test_double_issue_active_bond_rejected(api):
    """PRD §3.4: "issuing is valid only from `ISSUED`, with `ERR_INVALID_STATE` otherwise."

    Design: Corner/state_machines/bond_double_issue_from_active_returns_invalid_state
    """
    prog = create_program(name="SM1")
    prin, _ = create_principal_with_indemnity(
        legal_name="SMPrin1", credit_score=700, working_capital_cents=1_000_000
    )
    _, _, _, bond = setup_active_bond(
        program=prog, principal=prin,
        app_overrides={"bond_type": "PERFORMANCE", "requested_penal_sum_cents": 5_000_000,
                       "term_months": 12},
    )
    assert bond["status"] == "ACTIVE"
    res = api.issue_bond(bond["id"], UW)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_bond(bond["id"], UW), 200)
    assert after["status"] == "ACTIVE"


def test_settle_filed_claim_skipping_investigating_rejected(api):
    """PRD §3.7: "Settling is valid only while the claim is `INVESTIGATING` (otherwise
    `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/claim_settle_from_filed_skips_investigating_returns_invalid_state
    """
    prog = create_program(name="SM2")
    prin, _ = create_principal_with_indemnity(
        legal_name="SMPrin2", credit_score=700, working_capital_cents=1_000_000
    )
    _, bond, claim = setup_filed_claim(
        program=prog,
        bond=setup_active_bond(
            program=prog, principal=prin,
            app_overrides={"bond_type": "PERFORMANCE",
                           "requested_penal_sum_cents": 5_000_000, "term_months": 12},
        )[3],
        claim_overrides={"claimant_name": "Obligee SM2", "demand_cents": 100_000,
                         "reserve_cents": 100_000},
    )
    assert claim["status"] == "FILED"
    res = api.settle_claim(claim["id"], {"outcome": "PAY", "paid_loss_cents": 50_000}, CE)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_claim(claim["id"], CE), 200)
    assert after["status"] == "FILED"


def test_sign_executed_gia_rejected_terminal_lockdown(api):
    """PRD §3.2: "signing one that is not `PENDING` is rejected with `ERR_INVALID_STATE`."
    PRD §3.2: "Both `EXECUTED` and `VOIDED` are terminal."

    Design: Corner/state_machines/gia_terminal_lockdown_sign_after_executed
    """
    prin = create_principal(legal_name="SMPrin3", credit_score=700,
                            working_capital_cents=1_000_000)
    gia = get_success_data(
        api.create_indemnity_agreement(
            create_indemnity_agreement_payload(prin["id"], indemnitor_count=1,
                                               required_signature_count=1), UW
        )
    )
    gia = get_success_data(api.sign_indemnity_agreement(gia["id"], UW))
    assert gia["status"] == "EXECUTED"
    assert gia["collected_signature_count"] == 1
    res = api.sign_indemnity_agreement(gia["id"], UW)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_indemnity_agreement(gia["id"], UW), 200)
    assert after["status"] == "EXECUTED"
    assert after["collected_signature_count"] == 1


def test_gia_two_signatures_self_loop_then_execute(api):
    """PRD §3.2: "As long as collecting one more signature would still leave the running total
    short of `required_signature_count` — that is, while the count after this signature is
    strictly less than the required count — the agreement remains in `PENDING` and merely
    records the new tally. The signature that brings `collected_signature_count` up to exactly
    `required_signature_count` is the one that executes the agreement: it both increments the
    count to the required total and transitions the agreement to `EXECUTED`, and as a
    cross-entity effect it causes the referenced principal's `indemnity_on_file` to be
    recomputed to true."

    Design: Corner/state_machines/gia_self_loop_partial_signature_then_execute
    """
    prin = create_principal(legal_name="SMPrin4", credit_score=700,
                            working_capital_cents=1_000_000)
    gia = get_success_data(
        api.create_indemnity_agreement(
            create_indemnity_agreement_payload(prin["id"], indemnitor_count=2,
                                               required_signature_count=2), UW
        )
    )
    first = validate_success(api.sign_indemnity_agreement(gia["id"], UW), 200)
    assert first["status"] == "PENDING"
    assert first["collected_signature_count"] == 1
    second = validate_success(api.sign_indemnity_agreement(gia["id"], UW), 200)
    assert second["status"] == "EXECUTED"
    assert second["collected_signature_count"] == 2
    prin_after = validate_success(api.get_principal(prin["id"], UW), 200)
    assert prin_after["indemnity_on_file"] is True


def test_gia_three_signatures_two_self_loops_then_execute(api):
    """PRD §3.2: "As long as collecting one more signature would still leave the running total
    short of `required_signature_count` — that is, while the count after this signature is
    strictly less than the required count — the agreement remains in `PENDING` and merely
    records the new tally. The signature that brings `collected_signature_count` up to exactly
    `required_signature_count` is the one that executes the agreement: it both increments the
    count to the required total and transitions the agreement to `EXECUTED`, and as a
    cross-entity effect it causes the referenced principal's `indemnity_on_file` to be
    recomputed to true."

    Design: Corner/state_machines/gia_three_signatures_two_self_loops_then_execute
    """
    prin = create_principal(legal_name="ThreeSig", credit_score=700,
                            working_capital_cents=1_000_000)
    gia = get_success_data(
        api.create_indemnity_agreement(
            create_indemnity_agreement_payload(prin["id"], indemnitor_count=3,
                                               required_signature_count=3), UW
        )
    )
    s1 = validate_success(api.sign_indemnity_agreement(gia["id"], UW), 200)
    assert s1["status"] == "PENDING"
    assert s1["collected_signature_count"] == 1
    s2 = validate_success(api.sign_indemnity_agreement(gia["id"], UW), 200)
    assert s2["status"] == "PENDING"
    assert s2["collected_signature_count"] == 2
    s3 = validate_success(api.sign_indemnity_agreement(gia["id"], UW), 200)
    assert s3["status"] == "EXECUTED"
    assert s3["collected_signature_count"] == 3
    prin_after = validate_success(api.get_principal(prin["id"], UW), 200)
    assert prin_after["indemnity_on_file"] is True
