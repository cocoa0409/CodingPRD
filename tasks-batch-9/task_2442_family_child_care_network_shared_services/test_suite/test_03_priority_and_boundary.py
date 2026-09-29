"""Error-precedence pairs and exact-threshold boundary arithmetic."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    NETWORK_ADMIN_HEADERS,
    ApiErrorId,
    accept_assignment,
    approve_food_claim,
    claim_line,
    create_claim,
    create_enrollment,
    create_substitute,
    contract_version,
    escalate_review,
    file_food_claim,
    meal_line,
    provider_with_contract,
    record_clearance,
    request_coverage,
    review_at_cap_rejected_twice,
    revenue_model,
    withdraw_enrollment,
)

# Local setup builders


def _billing_home(authorized_amount_cents=5000000, **contract_overrides):
    """An ACTIVE August home with two subsidy children and one private family."""
    overrides = {
        "daily_rate_cents": 4500,
        "contracted_slots": 4,
        "authorized_amount_cents": authorized_amount_cents,
        "period_start_on": "2026-08-01T00:00:00Z",
        "absence_rate_pct": 50,
    }
    overrides.update(contract_overrides)
    ctx = provider_with_contract(
        apply_overrides={"capacity_slots": 6, "fixed_monthly_cost_cents": 237000},
        agreement_overrides={"shared_services": ["ENROLLMENT", "BILLING"]},
        contract_overrides=overrides,
    )
    ctx["e1"] = create_enrollment(
        ctx["provider_id"],
        child_ref="CH-1",
        family_name="Alvarez",
        days_per_week=5,
        private_monthly_tuition_cents=0,
        subsidy_certified=True,
    )["id"]
    ctx["e2"] = create_enrollment(
        ctx["provider_id"],
        child_ref="CH-2",
        family_name="Brody",
        days_per_week=5,
        private_monthly_tuition_cents=0,
        subsidy_certified=True,
    )["id"]
    ctx["e3"] = create_enrollment(
        ctx["provider_id"],
        child_ref="CH-3",
        family_name="Cortez",
        days_per_week=5,
        private_monthly_tuition_cents=102000,
        subsidy_certified=False,
    )["id"]
    return ctx


def _held_over_authorization(ctx):
    """Draft a 153000-cent August claim, then freeze it with a quality escalation."""
    claim = create_claim(
        ctx["contract_id"],
        ctx["provider_id"],
        "2026-08",
        [claim_line(ctx["e1"], 18, 4), claim_line(ctx["e2"], 10, 2)],
        contract_version(ctx["contract_id"]),
    )
    review = review_at_cap_rejected_twice(
        ctx["provider_id"], ["QS-3", "QS-9"], "2026-08-31T00:00:00Z"
    )
    escalate_review(review["id"])
    return claim


def _confirmed_coverage():
    """An ACTIVE home whose one pool member is confirmed for 08:00-14:00 on 2026-08-10."""
    ctx = provider_with_contract(
        apply_overrides={"capacity_slots": 6, "fixed_monthly_cost_cents": 237000},
        agreement_overrides={"shared_services": ["SUBSTITUTE_POOL"]},
    )
    ctx["substitute_id"] = create_substitute(
        full_name="Rosa Nunez",
        credential_level="NONE",
        clearance_expires_on="2026-12-31T00:00:00Z",
        hourly_rate_cents=2000,
        service_county_tiers=["STANDARD"],
    )["id"]
    first = request_coverage(
        ctx["provider_id"],
        "2026-08-10T08:00:00Z",
        "2026-08-10T14:00:00Z",
        reason="ILLNESS",
        min_credential_level="NONE",
        requested_substitute_id=ctx["substitute_id"],
    )
    ctx["first_assignment"] = accept_assignment(first["id"], ctx["substitute_id"])
    return ctx


def _food_program_home():
    """An ACTIVE STANDARD-tier home with two subsidy and two private children."""
    ctx = provider_with_contract(
        apply_overrides={
            "county_tier": "STANDARD",
            "capacity_slots": 6,
            "fixed_monthly_cost_cents": 237000,
        },
        agreement_overrides={"shared_services": ["ENROLLMENT", "FOOD_PROGRAM"]},
        contract_overrides={
            "daily_rate_cents": 4500,
            "contracted_slots": 4,
            "authorized_amount_cents": 5000000,
            "period_start_on": "2026-08-01T00:00:00Z",
        },
    )
    for child_ref, family_name, tuition, subsidy in (
        ("CH-1", "Alvarez", 0, True),
        ("CH-2", "Brody", 0, True),
        ("CH-3", "Cortez", 102000, False),
        ("CH-4", "Dolan", 101000, False),
    ):
        create_enrollment(
            ctx["provider_id"],
            child_ref=child_ref,
            family_name=family_name,
            days_per_week=5,
            private_monthly_tuition_cents=tuition,
            subsidy_certified=subsidy,
        )
    return ctx


# priority_pair_validation_conflict


def test_held_claim_state_error_masks_the_suspended_contract_error(api):
    """A held claim on a suspended contract reports the claim's own state, not the contract's.

    Both preconditions are broken at once: the claim sits in HELD, which is not a source
    state of submission, and its contract sits in SUSPENDED_FOR_QUALITY. The own-entity
    state check runs first, so the caller learns `ERR_INVALID_CLAIM_STATE` with HTTP 409
    and never sees `ERR_CONTRACT_NOT_ACTIVE`.

    PRD: "When a single request violates several rules, exactly one error is returned: the
    checks below run in strict ascending priority order and the first failing check
    short-circuits, so a lower-numbered failure always masks a higher-numbered one."

    Design: Difficulty/priority_pair_validation_conflict/claim_submit_held_state_error_beats_authorization_exceeded_fiscal_error
    """
    ctx = _billing_home(authorized_amount_cents=100000)
    claim = _held_over_authorization(ctx)

    held = validate_success(api.get_claim(claim["id"], NETWORK_ADMIN_HEADERS))
    assert held["status"] == "HELD"
    contract = validate_success(api.get_contract(ctx["contract_id"], NETWORK_ADMIN_HEADERS))
    assert contract["status"] == "SUSPENDED_FOR_QUALITY"

    validate_error(
        api.submit_claim(claim["id"], None, ctx["headers"]),
        ApiErrorId.INVALID_CLAIM_STATE.value,
        409,
    )


def test_held_claim_state_error_masks_the_authorization_ceiling_error(api):
    """The same refusal also hides the 402 the fiscal ceiling would have raised.

    The two lines would value at 22 * 4500 == 99000 plus 12 * 4500 == 54000, a provisional
    total of 153000 against an authorized ceiling of only 100000. Fiscal capacity is the
    last check of all, so the state error wins and no money moves: the claim's provisional
    amount is still 0 and the contract's claimed amount is still 0.

    PRD: "**Fiscal capacity, checked last.** A contract must have at least one available
    slot before a subsidy slot is committed, returning `ERR_SUBSIDY_SLOTS_EXHAUSTED` (HTTP
    409); and at submission the contract's cumulative claimed amount plus this claim's
    provisional amount must not exceed the contract's authorized amount, returning
    `ERR_CONTRACT_AUTHORIZATION_EXCEEDED` (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/claim_submit_held_state_error_beats_authorization_exceeded_fiscal_error
    """
    ctx = _billing_home(authorized_amount_cents=100000)
    claim = _held_over_authorization(ctx)

    validate_error(
        api.submit_claim(claim["id"], None, ctx["headers"]),
        ApiErrorId.INVALID_CLAIM_STATE.value,
        409,
    )

    unmoved = validate_success(api.get_claim(claim["id"], NETWORK_ADMIN_HEADERS))
    assert unmoved["status"] == "HELD"
    assert unmoved["provisional_amount_cents"] == 0

    contract = validate_success(api.get_contract(ctx["contract_id"], NETWORK_ADMIN_HEADERS))
    assert contract["authorized_amount_cents"] == 100000
    assert contract["claimed_amount_cents"] == 0


def test_expired_clearance_masks_the_buffered_interval_conflict(api):
    """A lapsed clearance is reported before the overlap it also has with itself.

    The requested member is already confirmed for 08:00-14:00 that day, so a 13:00-17:00
    window overlaps them even before the travel buffer widens it. Their clearance has been
    shortened to 2026-08-05, which falls before the new window's `end_at`, and child safety
    is evaluated ahead of interval conflicts, so the answer is
    `ERR_SUBSTITUTE_CLEARANCE_EXPIRED` with HTTP 422 rather than the 409 conflict.

    PRD: "**Child safety and licensure.** Evaluated before any scheduling or fiscal
    arithmetic: the selected or requested substitute's `clearance_expires_on` must fall on
    or after the assignment's `end_at`, returning `ERR_SUBSTITUTE_CLEARANCE_EXPIRED` (HTTP
    422)"

    Design: Difficulty/priority_pair_validation_conflict/assignment_clearance_safety_error_beats_interval_overlap_temporal_error
    """
    ctx = _confirmed_coverage()
    shortened = record_clearance(
        ctx["substitute_id"], clearance_expires_on="2026-08-05T00:00:00Z"
    )
    assert shortened["clearance_expires_on"].startswith("2026-08-05")

    response = api.create_assignment(
        {
            "provider_id": ctx["provider_id"],
            "start_at": "2026-08-10T13:00:00Z",
            "end_at": "2026-08-10T17:00:00Z",
            "reason": "ILLNESS",
            "min_credential_level": "NONE",
            "requested_substitute_id": ctx["substitute_id"],
        },
        ctx["headers"],
    )
    validate_error(response, ApiErrorId.SUBSTITUTE_CLEARANCE_EXPIRED.value, 422)
    assert response.status_code != 409


def test_shortening_a_clearance_leaves_the_already_confirmed_assignment_alone(api):
    """The refused request creates nothing and the confirmed coverage is untouched.

    Shortening the clearance only removes the member from future selection, so the member
    still holds exactly one assignment and it is still CONFIRMED.

    PRD: "Suspending a member or shortening their clearance does **not** disturb
    assignments they have already confirmed; it only removes them from future selection."

    Design: Difficulty/priority_pair_validation_conflict/assignment_clearance_safety_error_beats_interval_overlap_temporal_error
    """
    ctx = _confirmed_coverage()
    record_clearance(ctx["substitute_id"], clearance_expires_on="2026-08-05T00:00:00Z")
    validate_error(
        api.create_assignment(
            {
                "provider_id": ctx["provider_id"],
                "start_at": "2026-08-10T13:00:00Z",
                "end_at": "2026-08-10T17:00:00Z",
                "reason": "ILLNESS",
                "min_credential_level": "NONE",
                "requested_substitute_id": ctx["substitute_id"],
            },
            ctx["headers"],
        ),
        ApiErrorId.SUBSTITUTE_CLEARANCE_EXPIRED.value,
        422,
    )

    _, meta = validate_paginated(
        api.list_substitute_assignments(ctx["substitute_id"], None, NETWORK_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 1

    unchanged = validate_success(
        api.get_assignment(ctx["first_assignment"]["id"], NETWORK_ADMIN_HEADERS)
    )
    assert unchanged["staffing_status"] == "CONFIRMED"


# boundary_precision_check


def test_margin_of_exactly_fifteen_percent_still_bands_as_sustainable(api):
    """A margin landing exactly on 0.1500 is SUSTAINABLE, because the floor is inclusive.

    Revenue is 2 * 4500 * 22 == 198000 subsidy plus 102000 private == 300000. The six
    percent network fee is 18000, so cost is 237000 + 18000 == 255000 and the margin is
    45000 / 300000 == 0.1500 exactly. Guidance needs ceil(237000 / 0.79) == 300000 of
    private revenue, less the 198000 subsidy component, over one private family: 102000.

    PRD: "`sustainability` is `SUSTAINABLE` when that margin is at least 0.1500, `THIN`
    when it is at least 0.0500 but below 0.1500, and `AT_RISK` below 0.0500."

    Design: Difficulty/boundary_precision_check/revenue_margin_sustainable_at_exact_fifteen_percent_boundary
    """
    ctx = _billing_home()

    model = revenue_model(ctx["provider_id"])
    assert model["monthly_revenue_cents"] == 300000
    assert model["network_fee_cents"] == 18000
    assert model["substitute_cost_cents"] == 0
    assert model["monthly_cost_cents"] == 255000
    assert float(model["margin_pct"]) == 0.1500
    assert model["sustainability"] == "SUSTAINABLE"
    assert model["recommended_private_tuition_cents"] == 102000


def test_one_thousand_cents_less_revenue_drops_the_band_to_thin(api):
    """Shaving 1000 cents off tuition moves the margin to 0.1474 and the band to THIN.

    Swapping the 102000 family for a 101000 one leaves revenue at 299000, a fee of 17940
    and a cost of 254940, so the margin is 44060 / 299000 == 0.147357... which rounds half
    up to 0.1474 — below the inclusive 0.1500 floor. The guidance figure is unmoved at
    102000, because it depends on fixed cost and the subsidy component rather than on what
    the family is currently paying.

    PRD: "Otherwise `margin_pct` is `monthly_revenue_cents` less `monthly_cost_cents`,
    divided by `monthly_revenue_cents`, rounded half up to four decimal places"

    Design: Difficulty/boundary_precision_check/revenue_margin_sustainable_at_exact_fifteen_percent_boundary
    """
    ctx = _billing_home()
    withdraw_enrollment(ctx["e3"], ctx["provider_id"], "2026-08-31T00:00:00Z")
    create_enrollment(
        ctx["provider_id"],
        child_ref="CH-4",
        family_name="Dolan",
        days_per_week=5,
        private_monthly_tuition_cents=101000,
        subsidy_certified=False,
    )

    model = revenue_model(ctx["provider_id"])
    assert model["private_component_cents"] == 101000
    assert model["monthly_revenue_cents"] == 299000
    assert model["network_fee_cents"] == 17940
    assert model["monthly_cost_cents"] == 254940
    assert float(model["margin_pct"]) == 0.1474
    assert model["sustainability"] == "THIN"
    assert model["recommended_private_tuition_cents"] == 102000


def test_subsidy_share_of_exactly_one_half_prices_the_food_claim_at_tier_one(api):
    """Two subsidy children out of four give a share of 0.5000, which reaches TIER_I.

    The threshold is inclusive, so the generous schedule applies: 187 per breakfast, 348
    per lunch and 100 per snack. The three meal lines earn 187 + 348 + 100 == 635, then
    187 + 348 == 535, then 2 * 348 + 100 == 796, for a claimed total of 1966 — well above
    the 1028 the TIER_II schedule would have produced.

    PRD: "`tier_applied` is then `TIER_I` when either the provider's `county_tier` is
    `HIGH_NEED` or the computed share is at least 0.5000, and `TIER_II` in every other
    case."

    Design: Difficulty/boundary_precision_check/food_program_tier_boundary_at_exact_fifty_percent_subsidy_enrollment_share
    """
    ctx = _food_program_home()

    claim = file_food_claim(
        ctx["provider_id"],
        "2026-08",
        [
            meal_line("CH-1", "2026-08-03T00:00:00Z", breakfasts=1, lunches=1, snacks=1),
            meal_line("CH-2", "2026-08-03T00:00:00Z", breakfasts=1, lunches=1, snacks=0),
            meal_line("CH-3", "2026-08-04T00:00:00Z", breakfasts=0, lunches=2, snacks=1),
        ],
    )
    assert claim["status"] == "SUBMITTED"
    assert float(claim["subsidy_enrollment_share"]) == 0.5000
    assert claim["tier_applied"] == "TIER_I"
    assert claim["claimed_amount_cents"] == 1966
    assert claim["claimed_amount_cents"] != 1028
    assert claim["reimbursed_amount_cents"] == 0
    assert claim["disallowed_child_refs"] == []


def test_disallowance_removes_lines_at_the_frozen_tier_without_re_tiering(api):
    """Disallowing the private child's meals reimburses 1170 and keeps TIER_I frozen.

    The disallowed line was worth 796 at the frozen TIER_I rates, so 1966 - 796 == 1170 is
    reimbursed. Removing that child would have left a subsidy share of two out of three,
    but the tier and the share stored at filing time do not move.

    PRD: "Disallowance removes lines; **it never re-tiers the claim**, even when removing
    those children would have flipped the subsidy share across the tier threshold."

    Design: Difficulty/boundary_precision_check/food_program_tier_boundary_at_exact_fifty_percent_subsidy_enrollment_share
    """
    ctx = _food_program_home()
    claim = file_food_claim(
        ctx["provider_id"],
        "2026-08",
        [
            meal_line("CH-1", "2026-08-03T00:00:00Z", breakfasts=1, lunches=1, snacks=1),
            meal_line("CH-2", "2026-08-03T00:00:00Z", breakfasts=1, lunches=1, snacks=0),
            meal_line("CH-3", "2026-08-04T00:00:00Z", breakfasts=0, lunches=2, snacks=1),
        ],
    )

    approved = approve_food_claim(claim["id"], disallowed_child_refs=["CH-3"])
    assert approved["status"] == "APPROVED_WITH_DISALLOWANCE"
    assert approved["reimbursed_amount_cents"] == 1170
    assert approved["claimed_amount_cents"] == 1966
    assert approved["disallowed_child_refs"] == ["CH-3"]
    assert approved["tier_applied"] == "TIER_I"
    assert float(approved["subsidy_enrollment_share"]) == 0.5000
