"""Threshold boundaries, cross-entity gating, and capacity-collision limits.

Covers difficulty queue (A) rules boundary_precision_check, cross_entity_state_dependency, and
resource_temporal_overlap, plus the corner queue (B) validations section.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_indemnity_agreement_payload,
    create_application_payload,
    create_bond_payload,
    create_rider_payload,
    create_cession_payload,
    create_claim_payload,
    setup_submitted_application,
    setup_approved_application,
    setup_active_bond,
    setup_draft_rider,
    setup_filed_claim,
    create_principal,
    create_principal_with_indemnity,
    create_program,
    create_treaty,
    create_closed_treaty,
    create_suspended_program,
    UW,
    SR,
    CE,
)


# ─── boundary_precision_check: referral threshold inclusive on approve ─────────

def test_referral_threshold_at_boundary_requires_referral(api):
    """PRD §3.3: "a request at or above that threshold cannot be approved from the submitted
    stage and is rejected with `ERR_REFERRAL_REQUIRED`, forcing the referral path."

    Design: Difficulty/boundary_precision_check/referral_threshold_inclusive_boundary_on_approve
    """
    prog = create_program(name="P11", referral_threshold_cents=10_000_000,
                          single_limit_cents=20_000_000)
    prin, _ = create_principal_with_indemnity(
        legal_name="Kappa", credit_score=760, working_capital_cents=5_000_000
    )
    _, _, app = setup_submitted_application(
        program=prog, principal=prin,
        app_overrides={"bond_type": "BID", "requested_penal_sum_cents": 10_000_000,
                       "term_months": 12},
    )
    # penal 10,000,000 == threshold -> inclusive (>=) triggers referral required.
    res = api.approve_application(app["id"], UW)
    validate_error(res, "ERR_REFERRAL_REQUIRED")


def test_referral_threshold_just_below_approves_directly(api):
    """PRD §3.3: "A front-line underwriter may approve it directly, but only when the
    requested penal sum is strictly below the program's `referral_threshold_cents`".

    Design: Difficulty/boundary_precision_check/referral_threshold_inclusive_boundary_on_approve
    """
    prog = create_program(name="P11b", referral_threshold_cents=10_000_000,
                          single_limit_cents=20_000_000)
    prin, _ = create_principal_with_indemnity(
        legal_name="Kappa2", credit_score=760, working_capital_cents=5_000_000
    )
    _, _, app = setup_submitted_application(
        program=prog, principal=prin,
        app_overrides={"bond_type": "BID", "requested_penal_sum_cents": 9_999_999,
                       "term_months": 12},
    )
    # penal 9,999,999 strictly below 10,000,000 -> approves directly.
    res = api.approve_application(app["id"], UW)
    approved = validate_success(res, 200)
    assert approved["status"] == "APPROVED"


def test_incurred_loss_denied_only_claim_is_zero(api):
    """PRD §2.7: "and each `DENIED` claim contributes nothing."
    PRD §3.7: "a denied claim, like a paid one, no longer holds a reserve against the bond."

    Design: Difficulty/boundary_precision_check/incurred_loss_empty_claim_set_zero_on_bond
    """
    prog = create_program(name="P12")
    prin, _ = create_principal_with_indemnity(
        legal_name="Lambda", credit_score=700, working_capital_cents=1_000_000
    )
    _, _, _, bond = setup_active_bond(
        program=prog, principal=prin,
        app_overrides={"bond_type": "PERFORMANCE", "requested_penal_sum_cents": 5_000_000,
                       "term_months": 12},
    )
    claim = get_success_data(
        api.create_claim(
            create_claim_payload(bond["id"], claimant_name="Obligee W",
                                 demand_cents=800_000, reserve_cents=700_000), CE
        )
    )
    get_success_data(api.investigate_claim(claim["id"], {"reserve_cents": 700_000}, CE))
    settled = validate_success(api.settle_claim(claim["id"], {"outcome": "DENY"}, CE), 200)
    assert settled["status"] == "DENIED"
    bond_after = validate_success(api.get_bond(bond["id"], UW), 200)
    assert bond_after["incurred_loss_cents"] == 0


def test_incurred_loss_paid_zero_when_salvage_equals_paid(api):
    """PRD §2.7: "that net loss is the paid loss minus salvage, taken as `paid_loss_cents`
    minus `salvage_cents` but floored at zero so that salvage can never drive a single claim's
    contribution below zero".

    Design: Difficulty/boundary_precision_check/incurred_loss_empty_claim_set_zero_on_bond
    """
    prog = create_program(name="P12b")
    prin, _ = create_principal_with_indemnity(
        legal_name="Lambda2", credit_score=700, working_capital_cents=1_000_000
    )
    _, _, _, bond = setup_active_bond(
        program=prog, principal=prin,
        app_overrides={"bond_type": "PERFORMANCE", "requested_penal_sum_cents": 5_000_000,
                       "term_months": 12},
    )
    claim = get_success_data(
        api.create_claim(
            create_claim_payload(bond["id"], claimant_name="Obligee W2",
                                 demand_cents=800_000, reserve_cents=700_000), CE
        )
    )
    get_success_data(api.investigate_claim(claim["id"], {"reserve_cents": 700_000}, CE))
    # paid 300,000 minus salvage 300,000 = 0 (floored at zero), reserve removed.
    settled = validate_success(
        api.settle_claim(
            claim["id"],
            {"outcome": "PAY", "paid_loss_cents": 300_000, "salvage_cents": 300_000}, CE
        ),
        200,
    )
    assert settled["status"] == "PAID"
    bond_after = validate_success(api.get_bond(bond["id"], UW), 200)
    assert bond_after["incurred_loss_cents"] == 0


# ─── cross_entity_state_dependency: submit needs indemnity; cancel blocked by claim

def test_submit_requires_principal_indemnity_executed(api):
    """PRD §3.3: "the applicant principal must already have indemnity on file, meaning an
    `EXECUTED` GIA exists for it (otherwise `ERR_INDEMNITY_REQUIRED`)".

    Design: Difficulty/cross_entity_state_dependency/application_submit_requires_principal_indemnity_executed
    """
    prog = create_program(name="P13")
    prin = create_principal(legal_name="Mu", credit_score=700,
                            working_capital_cents=1_000_000)
    gia = get_success_data(
        api.create_indemnity_agreement(
            create_indemnity_agreement_payload(prin["id"], indemnitor_count=2,
                                               required_signature_count=2), UW
        )
    )
    # Only 1 of 2 signatures -> GIA still PENDING -> indemnity_on_file false.
    get_success_data(api.sign_indemnity_agreement(gia["id"], UW))
    prin_after = validate_success(api.get_principal(prin["id"], UW), 200)
    assert prin_after["indemnity_on_file"] is False

    app = get_success_data(
        api.create_application(
            create_application_payload(prin["id"], prog["id"], bond_type="PERFORMANCE",
                                       requested_penal_sum_cents=5_000_000, term_months=12), UW
        )
    )
    res = api.submit_application(app["id"], UW)
    validate_error(res, "ERR_INDEMNITY_REQUIRED")


def test_cancel_blocked_by_open_filed_claim(api):
    """PRD §3.5: "Cancellation is valid only while the bond is `ACTIVE` (otherwise
    `ERR_INVALID_STATE`) and only when the bond has no claim in `FILED` or `INVESTIGATING`
    (otherwise `ERR_OPEN_CLAIM_EXISTS`)."

    Design: Difficulty/cross_entity_state_dependency/bond_cancel_blocked_by_open_claim_on_bond
    """
    prog = create_program(name="P14")
    prin, _ = create_principal_with_indemnity(
        legal_name="Nu", credit_score=700, working_capital_cents=1_000_000
    )
    _, bond, claim = setup_filed_claim(
        program=prog,
        bond=setup_active_bond(
            program=prog, principal=prin,
            app_overrides={"bond_type": "PERFORMANCE",
                           "requested_penal_sum_cents": 5_000_000, "term_months": 12},
        )[3],
        claim_overrides={"claimant_name": "Obligee V", "demand_cents": 100_000,
                         "reserve_cents": 100_000},
    )
    assert claim["status"] == "FILED"
    res = api.cancel_bond(bond["id"], {"cancel_mode": "PRO_RATA"}, UW)
    validate_error(res, "ERR_OPEN_CLAIM_EXISTS")
    after = validate_success(api.get_bond(bond["id"], UW), 200)
    assert after["status"] == "ACTIVE"


def test_submit_succeeds_once_indemnity_executed(api):
    """PRD §3.3: "the applicant principal must already have indemnity on file, meaning an
    `EXECUTED` GIA exists for it (otherwise `ERR_INDEMNITY_REQUIRED`)".
    PRD §3.2: "The principal also carries an `indemnity_on_file` flag, which starts false and
    becomes true exactly when at least one `EXECUTED` indemnity agreement references the
    principal."

    Design: Difficulty/cross_entity_state_dependency/application_submit_requires_principal_indemnity_executed
    """
    prog = create_program(name="P13b")
    prin = create_principal(legal_name="Mu2", credit_score=700,
                            working_capital_cents=1_000_000)
    gia = get_success_data(
        api.create_indemnity_agreement(
            create_indemnity_agreement_payload(prin["id"], indemnitor_count=2,
                                               required_signature_count=2), UW
        )
    )
    # Collect both signatures -> GIA EXECUTED -> indemnity_on_file true.
    get_success_data(api.sign_indemnity_agreement(gia["id"], UW))
    get_success_data(api.sign_indemnity_agreement(gia["id"], UW))
    prin_after = validate_success(api.get_principal(prin["id"], UW), 200)
    assert prin_after["indemnity_on_file"] is True

    app = get_success_data(
        api.create_application(
            create_application_payload(prin["id"], prog["id"], bond_type="PERFORMANCE",
                                       requested_penal_sum_cents=5_000_000, term_months=12), UW
        )
    )
    submitted = validate_success(api.submit_application(app["id"], UW), 200)
    assert submitted["status"] == "SUBMITTED"


def test_cancel_blocked_by_investigating_claim(api):
    """PRD §3.5: "Cancellation is valid only while the bond is `ACTIVE` (otherwise
    `ERR_INVALID_STATE`) and only when the bond has no claim in `FILED` or `INVESTIGATING`
    (otherwise `ERR_OPEN_CLAIM_EXISTS`)."

    Design: Difficulty/cross_entity_state_dependency/bond_cancel_blocked_by_open_claim_on_bond
    """
    prog = create_program(name="P14b")
    prin, _ = create_principal_with_indemnity(
        legal_name="Nu2", credit_score=700, working_capital_cents=1_000_000
    )
    _, _, _, bond = setup_active_bond(
        program=prog, principal=prin,
        app_overrides={"bond_type": "PERFORMANCE", "requested_penal_sum_cents": 5_000_000,
                       "term_months": 12},
    )
    claim = get_success_data(
        api.create_claim(
            create_claim_payload(bond["id"], claimant_name="Obligee V2",
                                 demand_cents=100_000, reserve_cents=100_000), CE
        )
    )
    get_success_data(api.investigate_claim(claim["id"], {"reserve_cents": 100_000}, CE))
    res = api.cancel_bond(bond["id"], {"cancel_mode": "PRO_RATA"}, UW)
    validate_error(res, "ERR_OPEN_CLAIM_EXISTS")
    after = validate_success(api.get_bond(bond["id"], UW), 200)
    assert after["status"] == "ACTIVE"


# ─── resource_temporal_overlap: aggregate-capacity & treaty-capacity collisions ─

def test_bind_exceeding_aggregate_available_rejected(api):
    """PRD §3.4: "the requested penal sum must not exceed the program's
    `aggregate_available_cents`, or the bind is rejected with `ERR_AGGREGATE_LIMIT_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/program_aggregate_capacity_collision_net_retained
    """
    prog = create_program(name="P15", aggregate_limit_cents=10_000_000,
                          single_limit_cents=20_000_000, referral_threshold_cents=25_000_000)
    prin, _ = create_principal_with_indemnity(
        legal_name="Xi", credit_score=760, working_capital_cents=5_000_000
    )
    # First bond commits net_retained 8,000,000.
    setup_active_bond(
        program=prog, principal=prin,
        app_overrides={"bond_type": "BID", "requested_penal_sum_cents": 8_000_000,
                       "term_months": 12},
    )
    prog_before = validate_success(api.get_program(prog["id"], UW), 200)
    assert prog_before["aggregate_available_cents"] == 2_000_000

    # Second APPROVED application penal 3,000,000 (> 2,000,000 remaining).
    _, _, app2 = setup_submitted_application(
        program=prog, principal=prin,
        app_overrides={"bond_type": "BID", "requested_penal_sum_cents": 3_000_000,
                       "term_months": 12},
    )
    app2 = get_success_data(api.approve_application(app2["id"], UW))
    res = api.create_bond(create_bond_payload(app2["id"]), UW)
    validate_error(res, "ERR_AGGREGATE_LIMIT_EXCEEDED")


def test_cession_exceeding_treaty_capacity_rejected(api):
    """PRD §3.5: "A cession is rejected if the treaty is `CLOSED` (`ERR_TREATY_CLOSED`) or if
    the computed ceded amount would exceed the treaty's `ceded_available_cents`
    (`ERR_TREATY_CAPACITY_EXCEEDED`)."

    Design: Difficulty/resource_temporal_overlap/treaty_capacity_collision_gross_ceded
    """
    prog = create_program(name="P16")
    treaty = create_treaty(name="T16", cession_pct_bps=3000, treaty_capacity_cents=4_000_000)
    prin, _ = create_principal_with_indemnity(
        legal_name="Omicron", credit_score=760, working_capital_cents=5_000_000
    )
    _, _, _, bond1 = setup_active_bond(
        program=prog, principal=prin,
        app_overrides={"bond_type": "BID", "requested_penal_sum_cents": 12_000_000,
                       "term_months": 12},
    )
    _, _, _, bond2 = setup_active_bond(
        program=prog, principal=prin,
        app_overrides={"bond_type": "BID", "requested_penal_sum_cents": 12_000_000,
                       "term_months": 12},
    )
    # First cession: 30% of 12M = 3,600,000 (fits in 4,000,000).
    get_success_data(api.create_cession(create_cession_payload(bond1["id"], treaty["id"]), UW))
    treaty_mid = validate_success(api.get_treaty(treaty["id"], UW), 200)
    assert treaty_mid["ceded_committed_cents"] == 3_600_000
    assert treaty_mid["ceded_available_cents"] == 400_000
    # Second cession 3,600,000 would exceed remaining 400,000.
    res = api.create_cession(create_cession_payload(bond2["id"], treaty["id"]), UW)
    validate_error(res, "ERR_TREATY_CAPACITY_EXCEEDED")


def test_bind_fits_exactly_into_aggregate_available(api):
    """PRD §3.4: "the requested penal sum must not exceed the program's
    `aggregate_available_cents`, or the bind is rejected with `ERR_AGGREGATE_LIMIT_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/program_aggregate_capacity_collision_net_retained
    """
    prog = create_program(name="P15b", aggregate_limit_cents=10_000_000,
                          single_limit_cents=20_000_000, referral_threshold_cents=25_000_000)
    prin, _ = create_principal_with_indemnity(
        legal_name="Xi2", credit_score=760, working_capital_cents=5_000_000
    )
    setup_active_bond(
        program=prog, principal=prin,
        app_overrides={"bond_type": "BID", "requested_penal_sum_cents": 8_000_000,
                       "term_months": 12},
    )
    prog_before = validate_success(api.get_program(prog["id"], UW), 200)
    assert prog_before["aggregate_available_cents"] == 2_000_000
    # Second bond penal exactly 2,000,000 == remaining -> not exceeded, binds.
    _, _, app2 = setup_submitted_application(
        program=prog, principal=prin,
        app_overrides={"bond_type": "BID", "requested_penal_sum_cents": 2_000_000,
                       "term_months": 12},
    )
    app2 = get_success_data(api.approve_application(app2["id"], UW))
    bond2 = validate_success(api.create_bond(create_bond_payload(app2["id"]), UW), 201)
    assert bond2["status"] == "ISSUED"
    prog_after = validate_success(api.get_program(prog["id"], UW), 200)
    assert prog_after["aggregate_available_cents"] == 0


def test_cession_fits_exactly_into_treaty_capacity(api):
    """PRD §3.5: "A cession is rejected if the treaty is `CLOSED` (`ERR_TREATY_CLOSED`) or if
    the computed ceded amount would exceed the treaty's `ceded_available_cents`
    (`ERR_TREATY_CAPACITY_EXCEEDED`)."
    PRD §3.5: "The system computes the cession's `ceded_penal_sum_cents` at creation as the
    bond's `penal_sum_cents` multiplied by the treaty's `cession_pct_bps`, divided by 10000,
    rounded half up to whole cents."

    Design: Difficulty/resource_temporal_overlap/treaty_capacity_collision_gross_ceded
    """
    prog = create_program(name="P16b")
    # Treaty capacity exactly equal to the single cession (30% of 12M = 3,600,000).
    treaty = create_treaty(name="T16b", cession_pct_bps=3000, treaty_capacity_cents=3_600_000)
    prin, _ = create_principal_with_indemnity(
        legal_name="Omicron2", credit_score=760, working_capital_cents=5_000_000
    )
    _, _, _, bond = setup_active_bond(
        program=prog, principal=prin,
        app_overrides={"bond_type": "BID", "requested_penal_sum_cents": 12_000_000,
                       "term_months": 12},
    )
    cession = validate_success(
        api.create_cession(create_cession_payload(bond["id"], treaty["id"]), UW), 201
    )
    assert cession["ceded_penal_sum_cents"] == 3_600_000
    treaty_after = validate_success(api.get_treaty(treaty["id"], UW), 200)
    # ceded amount exactly fills capacity -> not exceeded.
    assert treaty_after["ceded_committed_cents"] == 3_600_000
    assert treaty_after["ceded_available_cents"] == 0


def test_submit_on_approved_application_rejected_invalid_state(api):
    """PRD §3.3: "Submission is gated by three preconditions evaluated together with the state
    check: the application must be `DRAFT` (otherwise `ERR_INVALID_STATE`)".
    PRD §2.12: "State legality is fifth and applies to every transition endpoint: the target
    resource must currently be in a state from which the requested transition is defined, or
    the request is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_referential_on_submit
    """
    prog = create_program(name="P9b")
    prin, _ = create_principal_with_indemnity(
        legal_name="Theta2", credit_score=700, working_capital_cents=1_000_000
    )
    # Advance the application all the way to APPROVED; the principal HAS indemnity on file, so
    # the referential check would pass — only the priority-5 state gate can fire on submit.
    _, _, app = setup_approved_application(
        program=prog, principal=prin,
        app_overrides={"bond_type": "PERFORMANCE", "requested_penal_sum_cents": 5_000_000,
                       "term_months": 12},
    )
    assert app["status"] == "APPROVED"
    res = api.submit_application(app["id"], UW)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Corner (B) validations ────────────────────────────────────────────────────

def test_single_limit_exceeded_on_rider_increase(api):
    """PRD §3.5: "for an `INCREASE` specifically, the bond's resulting penal sum — its current
    `penal_sum_cents` plus the `penal_sum_delta_cents` — must not exceed the program's
    `single_limit_cents` (otherwise `ERR_SINGLE_LIMIT_EXCEEDED`)".

    Design: Corner/validations/single_limit_exceeded_on_rider_increase
    """
    prog = create_program(name="V1", single_limit_cents=10_000_000,
                          referral_threshold_cents=15_000_000)
    prin, _ = create_principal_with_indemnity(
        legal_name="V1Prin", credit_score=760, working_capital_cents=5_000_000
    )
    _, bond, rider = setup_draft_rider(
        program=prog,
        bond=setup_active_bond(
            program=prog, principal=prin,
            app_overrides={"bond_type": "BID", "requested_penal_sum_cents": 10_000_000,
                           "term_months": 12},
        )[3],
        rider_overrides={"rider_type": "INCREASE", "penal_sum_delta_cents": 1},
    )
    # 10,000,000 + 1 = 10,000,001 > single_limit 10,000,000.
    res = api.apply_rider(rider["id"], UW)
    validate_error(res, "ERR_SINGLE_LIMIT_EXCEEDED")
    bond_after = validate_success(api.get_bond(bond["id"], UW), 200)
    assert bond_after["penal_sum_cents"] == 10_000_000


def test_program_suspended_blocks_submit(api):
    """PRD §3.1: "Once `SUSPENDED`, the program refuses new submit, approve, and bind
    activity, each such attempt returning `ERR_PROGRAM_SUSPENDED`."

    Design: Corner/validations/program_suspended_blocks_submit
    """
    prog = create_program(name="V2")
    prin, _ = create_principal_with_indemnity(
        legal_name="V2Prin", credit_score=700, working_capital_cents=1_000_000
    )
    app = get_success_data(
        api.create_application(
            create_application_payload(prin["id"], prog["id"], bond_type="PERFORMANCE",
                                       requested_penal_sum_cents=5_000_000, term_months=12), UW
        )
    )
    get_success_data(api.suspend_program(prog["id"], SR))
    res = api.submit_application(app["id"], UW)
    validate_error(res, "ERR_PROGRAM_SUSPENDED")
    after = validate_success(api.get_application(app["id"], UW), 200)
    assert after["status"] == "DRAFT"


def test_treaty_closed_blocks_cession(api):
    """PRD §3.1: "A `CLOSED` treaty refuses new cessions with `ERR_TREATY_CLOSED`, but
    cessions already `ACTIVE` against it are left untouched."

    Design: Corner/validations/treaty_closed_blocks_cession
    """
    prog = create_program(name="V3")
    treaty = create_closed_treaty(name="TV3", cession_pct_bps=2500,
                                  treaty_capacity_cents=10_000_000)
    prin, _ = create_principal_with_indemnity(
        legal_name="V3Prin", credit_score=760, working_capital_cents=5_000_000
    )
    _, _, _, bond = setup_active_bond(
        program=prog, principal=prin,
        app_overrides={"bond_type": "BID", "requested_penal_sum_cents": 8_000_000,
                       "term_months": 12},
    )
    res = api.create_cession(create_cession_payload(bond["id"], treaty["id"]), UW)
    validate_error(res, "ERR_TREATY_CLOSED")
    treaty_after = validate_success(api.get_treaty(treaty["id"], UW), 200)
    assert treaty_after["ceded_committed_cents"] == 0


def test_loss_exceeds_penal_sum_on_settle(api):
    """PRD §3.7: "the settle call must carry `paid_loss_cents`, and that amount must not exceed
    the bond's `penal_sum_cents`, or the settlement is rejected with
    `ERR_LOSS_EXCEEDS_PENAL_SUM`."

    Design: Corner/validations/loss_exceeds_penal_sum_on_settle
    """
    prog = create_program(name="V4")
    prin, _ = create_principal_with_indemnity(
        legal_name="V4Prin", credit_score=700, working_capital_cents=1_000_000
    )
    _, _, _, bond = setup_active_bond(
        program=prog, principal=prin,
        app_overrides={"bond_type": "PERFORMANCE", "requested_penal_sum_cents": 5_000_000,
                       "term_months": 12},
    )
    claim = get_success_data(
        api.create_claim(
            create_claim_payload(bond["id"], claimant_name="Obligee V4",
                                 demand_cents=6_000_000, reserve_cents=1_000_000), CE
        )
    )
    get_success_data(api.investigate_claim(claim["id"], {"reserve_cents": 1_000_000}, CE))
    # paid 6,000,000 > penal 5,000,000.
    res = api.settle_claim(claim["id"], {"outcome": "PAY", "paid_loss_cents": 6_000_000}, CE)
    validate_error(res, "ERR_LOSS_EXCEEDS_PENAL_SUM")
    after = validate_success(api.get_claim(claim["id"], CE), 200)
    assert after["status"] == "INVESTIGATING"


# ─── priority_pair_validation_conflict: state-vs-referential on submit ─────────

def test_second_submit_on_submitted_application_rejected_invalid_state(api):
    """PRD §2.12: "State legality is fifth and applies to every transition endpoint: the
    target resource must currently be in a state from which the requested transition is
    defined, or the request is rejected with `ERR_INVALID_STATE`."
    PRD §3.3: "Submission is gated by three preconditions evaluated together with the state
    check: the application must be `DRAFT` (otherwise `ERR_INVALID_STATE`)".

    Design: Difficulty/priority_pair_validation_conflict/state_vs_referential_on_submit
    """
    prog = create_program(name="P9")
    prin, _ = create_principal_with_indemnity(
        legal_name="Theta", credit_score=700, working_capital_cents=1_000_000
    )
    # First submit succeeds (indemnity on file); app is now SUBMITTED.
    _, _, app = setup_submitted_application(
        program=prog, principal=prin,
        app_overrides={"bond_type": "PERFORMANCE", "requested_penal_sum_cents": 5_000_000,
                       "term_months": 12},
    )
    assert app["status"] == "SUBMITTED"
    # Second submit: not DRAFT -> state check fails (only error that can fire here).
    res = api.submit_application(app["id"], UW)
    validate_error(res, "ERR_INVALID_STATE")
