"""Claim state machine: reverse/re-adjudicate cycle, eligibility, segregation,
invalid transitions, and claim listing."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID, make_examiner_headers,
    create_plan, create_provider, create_member,
    submit_claim, adjudicate_claim, terminate_member,
)

ADMIN = TEST_USERS["tpa_admin_headers"]
EX1 = make_examiner_headers("ex-1")
EX2 = make_examiner_headers("ex-2")


# ---- non_linear_state_machine: reverse -> re-adjudicate cycle --------------
def _setup_adjudicated_then_cycle(api):
    plan = create_plan()  # ded 100000
    prov = create_provider(in_network=True, ppo_discount_pct=0.40)
    member = create_member(plan["id"])
    claim = submit_claim(member["id"], prov["id"], billed_lines=[{"billed_cents": 100000}])
    adjudicate_claim(claim["id"])           # ded_met -> 60000
    api.reverse_claim(claim["id"], EX1)     # ADJUDICATED -> REVERSED, ded_met -> 0
    adjudicate_claim(claim["id"])           # REVERSED -> ADJUDICATED, ded_met -> 60000
    return member, claim


def test_reverse_then_readjudicate_returns_to_adjudicated(api):
    """PRD 3.5: "A `REVERSED` claim may be re-adjudicated (`REVERSED → ADJUDICATED`)
    under the same eligibility, run-out, and duplicate guards, re-running the full
    repricing, cost-share, accumulator, and specific-stop-loss cascade."

    Design: Difficulty/non_linear_state_machine/claim_reverse_then_readjudicate_cycle
    """
    _member, claim = _setup_adjudicated_then_cycle(api)
    data = validate_success(api.get_claim(claim["id"], ADMIN))
    assert data["status"] == "ADJUDICATED", (
        f"after reverse->re-adjudicate the claim is ADJUDICATED, got {data['status']}")


def test_reverse_then_readjudicate_restores_deductible(api):
    """PRD 3.4: "Adjudication then advances the member's accumulators: `deductible_met_cents`
    increases by `deductible_applied_cents`, `oop_met_cents` increases by
    `member_responsibility_cents`, and `member_plan_paid_ytd_cents` increases by `plan_paid_cents`."
    PRD 3.5: "Reversal is fully compensating: it decrements the member's `deductible_met_cents`
    by the claim's `deductible_applied_cents`, its `oop_met_cents` by the
    `member_responsibility_cents`, and its `member_plan_paid_ytd_cents` by the `plan_paid_cents`."

    Design: Difficulty/non_linear_state_machine/claim_reverse_then_readjudicate_cycle
    """
    member, _claim = _setup_adjudicated_then_cycle(api)
    data = validate_success(api.get_member(member["id"], ADMIN))
    assert data["deductible_met_cents"] == 60000, (
        f"deductible_met restored to 60000 after the round trip, got {data['deductible_met_cents']}")


# ---- cross_entity_state_dependency: member eligibility ---------------------
def _setup_terminated_member_claim(api):
    plan = create_plan()
    prov = create_provider(in_network=True, ppo_discount_pct=0.40)
    member = create_member(plan["id"])
    terminate_member(member["id"], "2026-05-31")
    claim = submit_claim(member["id"], prov["id"], service_date="2026-06-15",
                         billed_lines=[{"billed_cents": 100000}])
    return claim


def test_adjudicate_terminated_member_returns_not_eligible(api):
    """PRD 3.4: "The member must be `ACTIVE` and the `service_date` must fall on or after
    the member's `coverage_effective_date` and, when a `coverage_term_date` is set, on or
    before it (an open-ended coverage imposes no upper bound); otherwise the claim is
    rejected with `ERR_MEMBER_NOT_ELIGIBLE` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/adjudicate_requires_member_active_and_in_coverage
    """
    claim = _setup_terminated_member_claim(api)
    resp = api.adjudicate_claim(claim["id"], EX1)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ELIGIBLE.value)


def test_adjudicate_ineligible_leaves_claim_submitted(api):
    """PRD 3.4: "otherwise the claim is rejected with `ERR_MEMBER_NOT_ELIGIBLE` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/adjudicate_requires_member_active_and_in_coverage
    """
    claim = _setup_terminated_member_claim(api)
    api.adjudicate_claim(claim["id"], EX1)
    data = validate_success(api.get_claim(claim["id"], ADMIN))
    assert data["status"] == "SUBMITTED", (
        f"a rejected adjudication leaves the claim SUBMITTED, got {data['status']}")


# ---- compensating_invariant: accumulator conservation on reverse -----------
def _setup_adjudicated_then_reversed(api):
    plan = create_plan()  # ded 100000, oop 500000
    prov = create_provider(in_network=True, ppo_discount_pct=0.40)
    member = create_member(plan["id"])
    claim = submit_claim(member["id"], prov["id"], billed_lines=[{"billed_cents": 100000}])
    adjudicate_claim(claim["id"])         # ded_met 60000, oop_met 60000, plan_paid_ytd 0
    api.reverse_claim(claim["id"], EX1)   # all accumulators back to 0
    return member, claim


def test_accumulator_conservation_reset_after_reverse(api):
    """PRD 3.5: "Reversal is fully compensating: it decrements the member's
    `deductible_met_cents` by the claim's `deductible_applied_cents`, its `oop_met_cents`
    by the `member_responsibility_cents`, and its `member_plan_paid_ytd_cents` by the
    `plan_paid_cents`."

    Design: Difficulty/compensating_invariant/accumulator_conservation_on_adjudicate_then_reverse
    """
    member, _claim = _setup_adjudicated_then_reversed(api)
    data = validate_success(api.get_member(member["id"], ADMIN))
    assert data["deductible_met_cents"] == 0
    assert data["oop_met_cents"] == 0
    assert data["member_plan_paid_ytd_cents"] == 0


def test_reverse_sets_claim_reversed(api):
    """PRD 3.5: "An `ADJUDICATED` claim may be **reversed** by a `ClaimsExaminer` — for
    example, to correct an error — moving it `ADJUDICATED → REVERSED`."

    Design: Difficulty/compensating_invariant/accumulator_conservation_on_adjudicate_then_reverse
    """
    _member, claim = _setup_adjudicated_then_reversed(api)
    data = validate_success(api.get_claim(claim["id"], ADMIN))
    assert data["status"] == "REVERSED", f"claim must be REVERSED, got {data['status']}"


# ---- Corner: invalid transitions -------------------------------------------
def test_adjudicate_denied_claim_returns_invalid_state(api):
    """PRD 3.4: "A claim may be **denied** from either `SUBMITTED` or `PENDED`, moving it
    to the terminal `DENIED` state and recording the supplied `denial_reason`."
    PRD 2.7: "a target entity in the wrong state yields `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/adjudicate_denied_claim_returns_invalid_state
    """
    plan = create_plan()
    prov = create_provider(in_network=True, ppo_discount_pct=0.40)
    member = create_member(plan["id"])
    claim = submit_claim(member["id"], prov["id"], billed_lines=[{"billed_cents": 100000}])
    validate_success(api.deny_claim(claim["id"], {"denial_reason": "NOT_COVERED"}, EX1))
    resp = api.adjudicate_claim(claim["id"], EX1)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_reverse_submitted_claim_returns_invalid_state(api):
    """PRD 3.5: "Reversal is only allowed from `ADJUDICATED`; a claim that has already been
    paid must first have its payment undone by voiding its check-run, and a reverse attempted
    on any other state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/reverse_submitted_claim_returns_invalid_state
    """
    plan = create_plan()
    prov = create_provider(in_network=True, ppo_discount_pct=0.40)
    member = create_member(plan["id"])
    claim = submit_claim(member["id"], prov["id"], billed_lines=[{"billed_cents": 100000}])
    resp = api.reverse_claim(claim["id"], EX1)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_segregation_same_examiner_pend_then_adjudicate_returns_forbidden(api):
    """PRD 3.4: "When adjudicating a `PENDED` claim, the acting examiner's `X-User-ID` must
    differ from the `pended_by_user_id` recorded when it was pended; if the same user
    attempts both, the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/validations/segregation_same_examiner_pend_then_adjudicate_returns_forbidden
    """
    plan = create_plan()
    prov = create_provider(in_network=True, ppo_discount_pct=0.40)
    member = create_member(plan["id"])
    claim = submit_claim(member["id"], prov["id"], examiner_id="ex-1",
                         billed_lines=[{"billed_cents": 100000}])
    validate_success(api.pend_claim(claim["id"], EX1))
    resp = api.adjudicate_claim(claim["id"], EX1)  # same examiner ex-1
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    data = validate_success(api.get_claim(claim["id"], ADMIN))
    assert data["status"] == "PENDED", f"claim stays PENDED after rejection, got {data['status']}"


def test_get_claim_nonexistent_returns_not_found(api):
    """PRD 2.7: "every resource referenced by a path identifier or a request-body foreign
    key exists (see the not-found codes below)." Existence codes include `ERR_CLAIM_NOT_FOUND`.

    Design: Corner/entities/get_claim_nonexistent_returns_not_found
    """
    resp = api.get_claim(NON_EXISTENT_UUID, TEST_USERS["claims_examiner_headers"])
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FOUND.value)


def test_claim_create_provider_not_found_returns_404(api):
    """PRD 2.7: "submitting a claim that names a non-existent member fails with
    `ERR_MEMBER_NOT_FOUND`, and generating a 1099 for a non-existent provider fails with
    `ERR_PROVIDER_NOT_FOUND`."

    Design: Corner/validations/claim_create_provider_not_found_returns_404
    """
    plan = create_plan()
    member = create_member(plan["id"])
    resp = api.create_claim({
        "member_id": member["id"], "provider_id": NON_EXISTENT_UUID,
        "service_date": "2026-03-01", "billed_lines": [{"billed_cents": 100000}],
    }, EX1)
    validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_FOUND.value)


def test_list_claims_by_member_returns_paginated_envelope(api):
    """PRD 3.4: "Claims may be listed and filtered by `member_id`, `provider_id`, and/or
    `status`."
    PRD 2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more`
    in the `meta` object of the envelope."

    Design: Corner/entities/list_claims_by_member_pagination_envelope
    """
    plan = create_plan()
    prov = create_provider(in_network=True, ppo_discount_pct=0.40)
    member = create_member(plan["id"])
    submit_claim(member["id"], prov["id"], service_date="2026-03-01",
                 billed_lines=[{"billed_cents": 100000}])
    submit_claim(member["id"], prov["id"], service_date="2026-03-02",
                 billed_lines=[{"billed_cents": 100000}])
    resp = api.list_claims(EX1, params={"member_id": member["id"]})
    data, meta = validate_paginated(resp)
    assert len(data) == 2, f"expected 2 claims, got {len(data)}"
    assert meta["total_count"] == 2, f"total_count expected 2, got {meta['total_count']}"
    assert meta["has_more"] is False, f"has_more expected False, got {meta['has_more']}"
