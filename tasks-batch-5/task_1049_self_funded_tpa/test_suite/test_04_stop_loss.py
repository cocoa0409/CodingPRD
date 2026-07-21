"""Stop-loss policies, lasers, specific cascade, and aggregate settlement."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_plan, create_provider, create_member,
    create_policy, create_active_policy, create_laser,
    submit_claim, adjudicate_claim, create_adjudicated_claim,
    create_fund_account, deposit, create_check_run, release_check_run,
    set_clock,
)

ADMIN = TEST_USERS["tpa_admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---- dual_variant_calc: aggregate settlement PAID vs INCURRED basis --------
def test_aggregate_settlement_incurred_basis_recognizes_reimbursement(api):
    """PRD 3.7: "On an `INCURRED` basis, the qualifying claims are those in `ADJUDICATED`
    or `PAID` status whose `service_date` falls within the policy period, inclusive of both
    the `effective_date` and the `expiry_date` — regardless of when they were paid."
    PRD 3.7: "Otherwise the system creates an `AGGREGATE` stop-loss reimbursement for the new
    aggregate amount, recording the settlement `contract_basis` (`PAID` or `INCURRED`) in its
    `basis_note` and leaving its `claim_id` and `member_id` unset, increments the policy's
    `total_aggregate_reimbursed_cents` by the new amount, and moves the policy `ACTIVE → SETTLED`."

    Design: Difficulty/dual_variant_calc/aggregate_stop_loss_paid_basis_vs_incurred_basis
    """
    plan = create_plan(sponsor_name="PlanA", sponsor_tax_id="50-0000001")
    prov = create_provider(name="Hospital", tax_id="44-4444444", npi="3333333333",
                           in_network=True, ppo_discount_pct=0.40)
    pol = create_active_policy(plan["id"], contract_basis="INCURRED",
                               effective_date="2026-01-01", expiry_date="2026-07-01",
                               specific_deductible_cents=100000000,
                               aggregate_attachment_cents=5000000)
    member = create_member(plan["id"], first_name="Al", last_name="A")
    set_clock("2026-06-15T00:00:00Z")
    submit_and_adjudicate = create_adjudicated_claim(
        member["id"], prov["id"], service_date="2026-06-01",
        billed_lines=[{"billed_cents": 10000000}])  # plan_paid 5500000
    reimb = validate_success(api.settle_aggregate(pol["id"], AUDITOR), expected_status=201)
    assert reimb["amount_cents"] == 500000, (
        f"INCURRED aggregate net 5500000 over attachment 5000000 -> 500000, got {reimb['amount_cents']}")
    assert reimb["reimbursement_type"] == "AGGREGATE"
    policy = validate_success(api.get_stop_loss_policy(pol["id"], ADMIN))
    assert policy["total_aggregate_reimbursed_cents"] == 500000
    assert submit_and_adjudicate["plan_paid_cents"] == 5500000


def test_aggregate_settlement_paid_basis_excludes_runout_claim(api):
    """PRD 3.7: "On a `PAID` basis, the qualifying claims are only those in `PAID` status
    whose `paid_at` falls within that same inclusive window — so a run-out claim paid after
    the period's expiry is excluded."
    PRD 3.7: "If the new aggregate amount is zero or negative — the attachment has not been
    exceeded net of prior recoveries — settlement is rejected with `ERR_AGGREGATE_NOT_REACHED`
    (HTTP 422)."

    Design: Difficulty/dual_variant_calc/aggregate_stop_loss_paid_basis_vs_incurred_basis
    """
    plan = create_plan(sponsor_name="PlanB", sponsor_tax_id="50-0000002")
    prov = create_provider(name="Hospital", tax_id="44-4444444", npi="3333333333",
                           in_network=True, ppo_discount_pct=0.40)
    pol = create_active_policy(plan["id"], contract_basis="PAID",
                               effective_date="2026-01-01", expiry_date="2026-07-01",
                               specific_deductible_cents=100000000,
                               aggregate_attachment_cents=5000000)
    member = create_member(plan["id"], first_name="Bo", last_name="B")
    claim = create_adjudicated_claim(member["id"], prov["id"], service_date="2026-06-01",
                                     billed_lines=[{"billed_cents": 10000000}])
    fund = create_fund_account(plan["id"])
    fund = deposit(fund["id"], 5500000)
    cr = create_check_run(fund["id"], [claim["id"]])
    set_clock("2026-08-01T00:00:00Z")  # paid after expiry 2026-07-01 -> excluded on PAID basis
    release_check_run(cr["id"], fund["version"])
    resp = api.settle_aggregate(pol["id"], AUDITOR)
    validate_error(resp, ApiErrorId.ERR_AGGREGATE_NOT_REACHED.value)


# ---- transitive_cascade: adjudicate -> accumulator -> specific reimbursement
def _setup_specific_cascade(api):
    plan = create_plan()
    prov = create_provider(name="Hospital", tax_id="44-4444444", npi="3333333333",
                           in_network=True, ppo_discount_pct=0.40)
    member = create_member(plan["id"], first_name="Sam", last_name="H")
    pol = create_active_policy(plan["id"], contract_basis="PAID",
                               effective_date="2026-01-01", expiry_date="2027-01-01",
                               specific_deductible_cents=5000000,
                               aggregate_attachment_cents=100000000)
    claim = create_adjudicated_claim(member["id"], prov["id"], service_date="2026-04-01",
                                     billed_lines=[{"billed_cents": 10000000}])
    return plan, prov, member, pol, claim


def test_adjudicate_cascade_updates_member_plan_paid_ytd(api):
    """PRD 3.4: "Adjudication then advances the member's accumulators: `deductible_met_cents`
    increases by `deductible_applied_cents`, `oop_met_cents` increases by
    `member_responsibility_cents`, and `member_plan_paid_ytd_cents` increases by `plan_paid_cents`."

    Design: Difficulty/transitive_cascade/adjudicate_cascades_member_accumulator_to_specific_reimbursement_depth3
    """
    _plan, _prov, member, _pol, claim = _setup_specific_cascade(api)
    cdata = validate_success(api.get_claim(claim["id"], ADMIN))
    assert cdata["plan_paid_cents"] == 5500000
    mdata = validate_success(api.get_member(member["id"], ADMIN))
    assert mdata["member_plan_paid_ytd_cents"] == 5500000


def test_adjudicate_cascade_creates_specific_reimbursement(api):
    """PRD 3.5: "Only when the new reimbursement is strictly greater than 0 does the cascade
    create a `SPECIFIC` stop-loss reimbursement for the amount of the new reimbursement, tagged
    with the originating `claim_id` and `member_id`; it then adds that amount to both the
    member's `spec_reimbursed_cents` and the policy's `total_specific_reimbursed_cents`."

    Design: Difficulty/transitive_cascade/adjudicate_cascades_member_accumulator_to_specific_reimbursement_depth3
    """
    _plan, _prov, _member, pol, claim = _setup_specific_cascade(api)
    resp = api.list_reimbursements(AUDITOR, params={"claim_id": claim["id"]})
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, f"expected exactly 1 reimbursement, got {len(data)}"
    assert data[0]["reimbursement_type"] == "SPECIFIC"
    assert data[0]["amount_cents"] == 500000
    policy = validate_success(api.get_stop_loss_policy(pol["id"], ADMIN))
    assert policy["total_specific_reimbursed_cents"] == 500000


# ---- cross_entity_state_dependency: laser requires ACTIVE policy -----------
def test_laser_on_draft_policy_returns_policy_not_active(api):
    """PRD 3.3: "A laser may only be carved on a policy that is currently `ACTIVE`; carving
    against a `DRAFT` or `SETTLED` policy is rejected with `ERR_POLICY_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/laser_create_requires_active_stop_loss_policy
    """
    plan = create_plan()
    member = create_member(plan["id"], first_name="Sam", last_name="H")
    pol = create_policy(plan["id"], specific_deductible_cents=5000000,
                        aggregate_attachment_cents=100000000)  # left DRAFT
    resp = api.create_laser({
        "stop_loss_policy_id": pol["id"], "member_id": member["id"],
        "laser_deductible_cents": 10000000,
        "effective_date": "2026-01-01", "expiry_date": "2026-12-31",
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_POLICY_NOT_ACTIVE.value)


def test_laser_on_active_policy_succeeds(api):
    """PRD 3.3: "A laser may only be carved on a policy that is currently `ACTIVE`; carving
    against a `DRAFT` or `SETTLED` policy is rejected with `ERR_POLICY_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/laser_create_requires_active_stop_loss_policy
    """
    plan = create_plan()
    member = create_member(plan["id"], first_name="Sam", last_name="H")
    pol = create_active_policy(plan["id"], specific_deductible_cents=5000000,
                               aggregate_attachment_cents=100000000)
    resp = api.create_laser({
        "stop_loss_policy_id": pol["id"], "member_id": member["id"],
        "laser_deductible_cents": 10000000,
        "effective_date": "2026-01-01", "expiry_date": "2026-12-31",
    }, ADMIN)
    validate_success(resp, expected_status=201)


# ---- resource_temporal_overlap: stop-loss policy periods (half-open) -------
def test_policy_period_overlap_rejected(api):
    """PRD 3.3: "two policies conflict when these half-open intervals overlap, but adjacency is
    allowed — one policy's `expiry_date` may equal the next policy's `effective_date`."
    PRD 3.3: "A conflicting activation is rejected with `ERR_POLICY_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/stop_loss_policy_period_overlap_half_open_adjacency_allowed
    """
    plan = create_plan()
    create_active_policy(plan["id"], effective_date="2026-01-01", expiry_date="2026-12-31",
                         specific_deductible_cents=5000000, aggregate_attachment_cents=100000000)
    pol_b = create_policy(plan["id"], effective_date="2026-06-01", expiry_date="2027-01-01",
                          specific_deductible_cents=5000000, aggregate_attachment_cents=100000000)
    resp = api.activate_stop_loss_policy(pol_b["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_POLICY_PERIOD_OVERLAP.value)


def test_policy_period_adjacency_allowed(api):
    """PRD 3.3: "The period is treated as the half-open interval running from `effective_date`
    inclusive up to but not including `expiry_date`; two policies conflict when these half-open
    intervals overlap, but adjacency is allowed — one policy's `expiry_date` may equal the next
    policy's `effective_date`."

    Design: Difficulty/resource_temporal_overlap/stop_loss_policy_period_overlap_half_open_adjacency_allowed
    """
    plan = create_plan()
    create_active_policy(plan["id"], effective_date="2026-01-01", expiry_date="2026-12-31",
                         specific_deductible_cents=5000000, aggregate_attachment_cents=100000000)
    pol_c = create_policy(plan["id"], effective_date="2026-12-31", expiry_date="2027-06-30",
                          specific_deductible_cents=5000000, aggregate_attachment_cents=100000000)
    data = validate_success(api.activate_stop_loss_policy(pol_c["id"], ADMIN))
    assert data["status"] == "ACTIVE", f"adjacent policy must activate, got {data['status']}"


# ---- resource_temporal_overlap: laser windows (closed, touching rejected) --
def test_laser_window_touching_endpoint_rejected(api):
    """PRD 3.3: "here the window is treated as a closed interval from `effective_date` through
    `expiry_date` inclusive, and even touching endpoints conflict — the new laser's
    `effective_date` must be strictly greater than the prior laser's `expiry_date`, otherwise
    the request is rejected with `ERR_LASER_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/laser_window_overlap_closed_touching_rejected
    """
    plan = create_plan()
    member = create_member(plan["id"], first_name="Sam", last_name="H")
    pol = create_active_policy(plan["id"], specific_deductible_cents=5000000,
                               aggregate_attachment_cents=100000000)
    create_laser(pol["id"], member["id"], laser_deductible_cents=10000000,
                 effective_date="2026-01-01", expiry_date="2026-06-30")
    resp = api.create_laser({
        "stop_loss_policy_id": pol["id"], "member_id": member["id"],
        "laser_deductible_cents": 12000000,
        "effective_date": "2026-06-30", "expiry_date": "2026-12-31",
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_LASER_WINDOW_OVERLAP.value)


def test_laser_window_strictly_after_prior_expiry_allowed(api):
    """PRD 3.3: "the new laser's `effective_date` must be strictly greater than the prior
    laser's `expiry_date`, otherwise the request is rejected with `ERR_LASER_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/laser_window_overlap_closed_touching_rejected
    """
    plan = create_plan()
    member = create_member(plan["id"], first_name="Sam", last_name="H")
    pol = create_active_policy(plan["id"], specific_deductible_cents=5000000,
                               aggregate_attachment_cents=100000000)
    create_laser(pol["id"], member["id"], laser_deductible_cents=10000000,
                 effective_date="2026-01-01", expiry_date="2026-06-30")
    resp = api.create_laser({
        "stop_loss_policy_id": pol["id"], "member_id": member["id"],
        "laser_deductible_cents": 12000000,
        "effective_date": "2026-07-01", "expiry_date": "2026-12-31",  # 07-01 > 06-30 strictly
    }, ADMIN)
    validate_success(resp, expected_status=201)


# ---- Corner instances ------------------------------------------------------
def test_activate_already_active_policy_returns_invalid_state(api):
    """PRD 3.3: "Activating a policy is only permitted from `DRAFT`, and enforces that its
    period does not overlap any other `ACTIVE` policy on the same plan."
    PRD 2.7: "a target entity in the wrong state yields `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/activate_already_active_policy_returns_invalid_state
    """
    plan = create_plan()
    pol = create_active_policy(plan["id"], specific_deductible_cents=5000000,
                               aggregate_attachment_cents=100000000)
    resp = api.activate_stop_loss_policy(pol["id"], ADMIN)  # second activation
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_laser_member_from_other_plan_returns_mismatch(api):
    """PRD 3.3: "The laser's member must belong to the same plan as the laser's policy; a
    mismatch is rejected with `ERR_LASER_MEMBER_MISMATCH` (HTTP 422)."

    Design: Corner/validations/laser_member_from_other_plan_returns_mismatch
    """
    plan_a = create_plan(sponsor_name="PlanA", sponsor_tax_id="50-0000001")
    pol_a = create_active_policy(plan_a["id"], specific_deductible_cents=5000000,
                                 aggregate_attachment_cents=100000000)
    plan_b = create_plan(sponsor_name="PlanB", sponsor_tax_id="50-0000002")
    mem_b = create_member(plan_b["id"], first_name="Bo", last_name="B")
    resp = api.create_laser({
        "stop_loss_policy_id": pol_a["id"], "member_id": mem_b["id"],
        "laser_deductible_cents": 10000000,
        "effective_date": "2026-01-01", "expiry_date": "2026-12-31",
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_LASER_MEMBER_MISMATCH.value)


def test_list_reimbursements_by_policy_returns_specific(api):
    """PRD 3.5: "Reimbursements may be listed and filtered by `stop_loss_policy_id` and/or
    `claim_id`."

    Design: Corner/endpoints/list_reimbursements_by_policy_reverse_reachability
    """
    _plan, _prov, _member, pol, _claim = _setup_specific_cascade(api)
    resp = api.list_reimbursements(AUDITOR, params={"stop_loss_policy_id": pol["id"]})
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, f"expected exactly 1 reimbursement, got {len(data)}"
    assert data[0]["reimbursement_type"] == "SPECIFIC"
    assert data[0]["amount_cents"] == 500000
