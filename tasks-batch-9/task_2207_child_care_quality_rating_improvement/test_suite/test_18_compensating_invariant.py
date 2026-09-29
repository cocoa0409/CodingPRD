"""Conserved quantities across a forward action and its compensating action.

Three different ledgers are exercised: grant funds, the coaching hours budget, and the
provider's signed subsidy adjustment. In each case the pair of operations must leave the
identity balanced on both sides with zero drift.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    adjudicate_expenditure,
    api_client,
    approve_claim,
    build_rating_spine,
    file_appeal,
    make_coach_headers,
    make_provider_headers,
    make_reviewer_headers,
    pay_claim,
    publish_cycle,
    run_expiry_run,
    schedule_session,
    set_clock,
    setup_active_allocation,
    setup_open_grant,
    start_appeal_review,
    submit_claim,
    submit_expenditure,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]

#: Five equally weighted domains, every block minimum at 1 point.
EQUAL_WEIGHT_DOMAINS = [
    {
        "domain_code": "FAMILY_PARTNERSHIP",
        "block_level": 1,
        "max_points": 20,
        "block_min_points": 1,
        "weight": 0.20,
        "observation_linked": False,
    },
    {
        "domain_code": "ADMINISTRATION",
        "block_level": 1,
        "max_points": 20,
        "block_min_points": 1,
        "weight": 0.20,
        "observation_linked": False,
    },
    {
        "domain_code": "STAFF_QUALIFICATIONS",
        "block_level": 2,
        "max_points": 20,
        "block_min_points": 1,
        "weight": 0.20,
        "observation_linked": False,
    },
    {
        "domain_code": "LEARNING_ENVIRONMENT",
        "block_level": 2,
        "max_points": 20,
        "block_min_points": 1,
        "weight": 0.20,
        "observation_linked": True,
        "min_composite_for_block": 3.00,
    },
    {
        "domain_code": "CHILD_ASSESSMENT",
        "block_level": 3,
        "max_points": 20,
        "block_min_points": 1,
        "weight": 0.20,
        "observation_linked": False,
    },
]

#: Verified points behind a tier-1 award: with no credentials the STAFF_QUALIFICATIONS cap
#: collapses to 4 and the observation composite of 4.00 fixes LEARNING_ENVIRONMENT at 12,
#: giving a weighted total of 37.00.
TIER_ONE_POINTS = {
    "LEARNING_ENVIRONMENT": 10,
    "STAFF_QUALIFICATIONS": 16,
    "FAMILY_PARTNERSHIP": 8,
    "ADMINISTRATION": 6,
    "CHILD_ASSESSMENT": 7,
}

#: Verified points behind the tier-2 award used by the subsidy scenario.
TIER_TWO_POINTS = {
    "LEARNING_ENVIRONMENT": 10,
    "STAFF_QUALIFICATIONS": 16,
    "FAMILY_PARTNERSHIP": 10,
    "ADMINISTRATION": 10,
    "CHILD_ASSESSMENT": 10,
}

#: Four VERIFIED records of 1.00 fte each against a declared 5.00 active staff fte, all
#: meeting their role minimum, so credential_compliance_pct is exactly 80.00.
FOUR_VERIFIED_CREDENTIALS = [
    {"role_type": "DIRECTOR", "credential_level": 5, "fte": 1.00,
     "registry_status": "VERIFIED", "expires_on": "2028-12-31"},
    {"role_type": "LEAD_TEACHER", "credential_level": 4, "fte": 1.00,
     "registry_status": "VERIFIED", "expires_on": "2028-12-31"},
    {"role_type": "LEAD_TEACHER", "credential_level": 3, "fte": 1.00,
     "registry_status": "VERIFIED", "expires_on": "2028-12-31"},
    {"role_type": "ASSISTANT", "credential_level": 2, "fte": 1.00,
     "registry_status": "VERIFIED", "expires_on": "2028-12-31"},
]


def _tier_one_active_spine(legal_name):
    """Provider ACTIVE at current_tier 1 with the clock left at 2026-09-01."""
    return build_rating_spine(
        stop_at="ACTIVE",
        domains=EQUAL_WEIGHT_DOMAINS,
        provider_overrides={
            "legal_name": legal_name,
            "county_code": "C001",
            "region_code": "URBAN",
            "licensed_capacity": 60,
            "active_staff_fte": 12.00,
            "weekly_onsite_cap_hours": 12.0,
        },
        credentials=[],
        claimed=TIER_ONE_POINTS,
        verified=TIER_ONE_POINTS,
        raw_score=4.0,
        award_clock="2026-08-11T00:00:00Z",
        activation_clock="2026-09-01T00:00:00Z",
    )


def test_a_submitted_then_rejected_expenditure_leaves_the_grant_ledger_identical(api):
    """PRD §3.8: "An accepted submission creates the line in `SUBMITTED` with
    `reimbursable_cents` and `disallowed_cents` at 0, adds its amount to `committed_cents`,
    subtracts it from `available_cents`, adds it to that category's entry in
    `category_spend_cents`, and increments the grant's `version` by 1."
    PRD §3.8: "Rejection moves the line `SUBMITTED → REJECTED` and unwinds the commitment
    exactly: `committed_cents` decreases by the line's `amount_cents`, `available_cents`
    increases by the same amount, and that category's `category_spend_cents` entry decreases by
    the same amount, so a submit-then-reject pair leaves the grant's ledger identity intact with
    zero drift."
    PRD §3.8: "Rejection also drives the compliance dimension: a first rejection moves it
    `COMPLIANT → UNDER_REVIEW`, a second rejection on the same grant moves it
    `UNDER_REVIEW → FINDING_ISSUED`, and a rejection against a grant already `REMEDIATED` moves
    it back `REMEDIATED → UNDER_REVIEW`, making the compliance axis cyclic."
    PRD §3.8: "Approval moves the line `SUBMITTED → APPROVED` and changes no money counter,
    because the funds stay committed."

    Design: Difficulty/compensating_invariant/grant_funds_conserved_across_submit_then_reject
    """
    ctx = _tier_one_active_spine("Grant Funds Center")
    assert ctx["cycle"]["weighted_total"] == pytest.approx(37.00, abs=0.005)
    assert ctx["cycle"]["awarded_tier"] == 1
    provider_id = ctx["provider"]["id"]

    _ctx, grant = setup_open_grant(
        spine=ctx, awarded_amount_cents=1_000_000, spend_deadline="2027-06-30"
    )
    assert grant["status"] == "OPEN"
    assert grant["compliance_status"] == "COMPLIANT"
    assert grant["awarded_amount_cents"] == 1_000_000
    assert grant["available_cents"] == 1_000_000
    assert grant["committed_cents"] == 0
    assert grant["reimbursed_cents"] == 0

    # One PROF_DEV line, approved and reimbursed at the 1.00 match rate. Its 100,000 cents
    # sit well inside both the 300,000-cent PROF_DEV ceiling and the grant room, so the
    # waterfall pays it in full and it must stay untouched by everything that follows.
    reimbursed_line = submit_expenditure(
        provider_id, grant["id"], "PROF_DEV", 100_000, "2026-09-05"
    )
    adjudicate_expenditure(reimbursed_line["id"], "APPROVE")
    validate_success(api.reimburse_grant(grant["id"], ADMIN))

    baseline = validate_success(api.get_improvement_grant(grant["id"], ADMIN))
    assert baseline["committed_cents"] == 0
    assert baseline["reimbursed_cents"] == 100_000
    assert baseline["available_cents"] == 900_000
    assert baseline["category_spend_cents"]["EQUIPMENT"] == 0

    # Forward action: commit 250,000 cents of equipment spending.
    grant_version = baseline["version"]
    submitted = validate_success(
        api.create_expenditure(
            grant["id"],
            {
                "category": "EQUIPMENT",
                "amount_cents": 250_000,
                "invoice_date": "2026-09-20",
                "expected_grant_version": grant_version,
            },
            make_provider_headers(provider_id),
        ),
        201,
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["reimbursable_cents"] == 0
    assert submitted["disallowed_cents"] == 0

    committed_state = validate_success(api.get_improvement_grant(grant["id"], ADMIN))
    assert committed_state["committed_cents"] == 250_000
    assert committed_state["reimbursed_cents"] == 100_000
    assert committed_state["available_cents"] == 650_000
    assert committed_state["category_spend_cents"]["EQUIPMENT"] == 250_000
    assert (
        committed_state["committed_cents"]
        + committed_state["reimbursed_cents"]
        + committed_state["available_cents"]
    ) == 1_000_000, "250000 + 100000 + 650000 must still equal the awarded amount"

    # Compensating action: reject the line.
    adjudicate_expenditure(submitted["id"], "REJECT", note="ineligible equipment")

    restored = validate_success(api.get_improvement_grant(grant["id"], ADMIN))
    assert restored["committed_cents"] == 0
    assert restored["reimbursed_cents"] == 100_000
    assert restored["available_cents"] == 900_000
    assert (
        restored["committed_cents"]
        + restored["reimbursed_cents"]
        + restored["available_cents"]
    ) == 1_000_000
    assert restored["awarded_amount_cents"] == 1_000_000
    assert restored["category_spend_cents"]["EQUIPMENT"] == 0
    assert restored["compliance_status"] == "UNDER_REVIEW"
    assert restored["status"] == "OPEN", (
        "the two state dimensions are independent, so a rejection never freezes the grant"
    )

    kept = validate_success(api.get_grant_expenditure(reimbursed_line["id"], ADMIN))
    assert kept["status"] == "REIMBURSED"
    assert kept["reimbursable_cents"] == 100_000
    assert kept["disallowed_cents"] == 0

    rejected = validate_success(api.get_grant_expenditure(submitted["id"], ADMIN))
    assert rejected["status"] == "REJECTED"
    assert rejected["reimbursable_cents"] == 0
    assert rejected["disallowed_cents"] == 0

    lines, _meta = validate_paginated(
        api.list_grant_expenditures(ADMIN, params={"improvement_grant_id": grant["id"]})
    )
    assert len(lines) == 2, f"both lines must remain readable, got {len(lines)}"


def test_a_scheduled_then_cancelled_session_leaves_the_hours_ledger_identical(api):
    """PRD §3.9: "An accepted session is created in `SCHEDULED`, adds its hours to the
    allocation's `scheduled_hours`, and subtracts them from the allocation's `remaining_hours`."
    PRD §3.9: "The session moves `SCHEDULED → DELIVERED`; the allocation's `scheduled_hours`
    decreases by the session's scheduled hours, its `delivered_hours` increases by the hours
    actually delivered, and its `remaining_hours` is recomputed as `allocated_hours` minus
    `scheduled_hours` minus `delivered_hours`."
    PRD §3.9: "the session moves `SCHEDULED → CANCELLED`, the allocation's `scheduled_hours`
    decreases and its `remaining_hours` increases by the session's scheduled hours, and both the
    closed interval and the weekly capacity that session had consumed under its `iso_week_key`
    are released. A schedule-then-cancel pair therefore leaves the allocation's hours ledger
    exactly as it was."
    PRD §3.9: "Completion is logged by the coach with a `delivered_hours` figure, which must be
    greater than zero and no greater than the session's own `scheduled_hours` plus half an hour
    of tolerance."

    Design: Difficulty/compensating_invariant/coaching_hours_conserved_across_schedule_then_cancel
    """
    ctx = _tier_one_active_spine("Coaching Hours Center")
    assert ctx["cycle"]["awarded_tier"] == 1

    _ctx, allocation = setup_active_allocation(
        spine=ctx,
        funding_source="STATE_BASE",
        funding_grant_id=None,
        period_start="2026-09-01",
        period_end="2026-12-31",
        allocated_hours=12.0,
        hourly_rate_cents=9_000,
    )
    assert allocation["status"] == "ACTIVE"
    assert allocation["base_hours_cost_cents"] == 108_000
    assert allocation["admin_fee_cents"] == 9_720
    assert allocation["total_cost_cents"] == 117_720
    assert allocation["spend_cap_cents"] == 500_000

    # A 3.0-hour booking delivered at 3.5 hours: the half-hour overrun is inside tolerance
    # and is permanently consumed, never returned to remaining_hours.
    delivered_session = schedule_session(
        allocation["id"], "2026-09-14T09:00:00Z", "2026-09-14T12:00:00Z"
    )
    validate_success(
        api.complete_coaching_session(
            delivered_session["id"], {"delivered_hours": 3.5}, make_coach_headers()
        )
    )
    settled = validate_success(api.get_coaching_session(delivered_session["id"], ADMIN))
    assert settled["status"] == "DELIVERED"
    assert float(settled["scheduled_hours"]) == pytest.approx(3.0, abs=0.05)
    assert float(settled["delivered_hours"]) == pytest.approx(3.5, abs=0.05)

    baseline = validate_success(api.get_coaching_allocation(allocation["id"], ADMIN))
    assert float(baseline["scheduled_hours"]) == pytest.approx(0.0, abs=0.05)
    assert float(baseline["delivered_hours"]) == pytest.approx(3.5, abs=0.05)
    assert float(baseline["remaining_hours"]) == pytest.approx(8.5, abs=0.05)

    # Forward action: book 4.0 more hours.
    booked = validate_success(
        api.create_coaching_session(
            allocation["id"],
            {"scheduled_start": "2026-09-15T09:00:00Z", "scheduled_end": "2026-09-15T13:00:00Z"},
            make_coach_headers(),
        ),
        201,
    )
    assert booked["status"] == "SCHEDULED"
    assert float(booked["scheduled_hours"]) == pytest.approx(4.0, abs=0.05)

    committed = validate_success(api.get_coaching_allocation(allocation["id"], ADMIN))
    assert float(committed["scheduled_hours"]) == pytest.approx(4.0, abs=0.05)
    assert float(committed["delivered_hours"]) == pytest.approx(3.5, abs=0.05)
    assert float(committed["remaining_hours"]) == pytest.approx(4.5, abs=0.05)
    assert (
        float(committed["scheduled_hours"])
        + float(committed["delivered_hours"])
        + float(committed["remaining_hours"])
    ) == pytest.approx(12.0, abs=0.05), "4.0 + 3.5 + 4.5 must equal allocated_hours"

    # Compensating action: cancel it.
    validate_success(
        api.cancel_coaching_session(
            booked["id"], make_coach_headers(), payload={"reason": "provider closure"}
        )
    )
    assert validate_success(api.get_coaching_session(booked["id"], ADMIN))["status"] == "CANCELLED"

    restored = validate_success(api.get_coaching_allocation(allocation["id"], ADMIN))
    assert float(restored["scheduled_hours"]) == pytest.approx(0.0, abs=0.05)
    assert float(restored["delivered_hours"]) == pytest.approx(3.5, abs=0.05)
    assert float(restored["remaining_hours"]) == pytest.approx(8.5, abs=0.05)
    assert float(restored["allocated_hours"]) == pytest.approx(12.0, abs=0.05)
    assert (
        float(restored["scheduled_hours"])
        + float(restored["delivered_hours"])
        + float(restored["remaining_hours"])
    ) == pytest.approx(12.0, abs=0.05), "0.0 + 3.5 + 8.5 must equal allocated_hours"
    assert restored["total_cost_cents"] == 117_720, (
        "scheduling and cancelling never touch the money side of the allocation"
    )
    assert restored["status"] == "ACTIVE"


def test_a_sustained_appeal_parks_a_subsidy_delta_the_reconciled_payment_returns_to_zero(api):
    """PRD §3.6: "In the second hop, caused by the tier change, every subsidy claim of that
    provider in `PAID` whose service month starts inside the cycle's validity window moves
    `PAID → RECONCILE_REQUIRED`. In the third hop, caused by each of those claims being flagged,
    the provider's `reimbursement_adjustment_cents` changes by the difference between what the
    claim would be worth under the reconciled variant and what was actually paid."
    PRD §3.7: "A reconciled payment rewrites `reimbursement_cents` under the reconciled variant
    and returns the provider's `reimbursement_adjustment_cents` to its pre-cascade value, so the
    pair of flagging-then-repaying leaves that conserved balance unchanged."
    PRD §3.7: "Under the **interim** variant a single multiplier is used for the whole month,
    taken from the tier in force on the first calendar day of the service month, so a mid-month
    tier change is ignored; that value is rounded half up to four decimal places and stored as
    `tier_multiplier_applied`."
    PRD §3.7: "Under the **reconciled** variant the multiplier is day-weighted: the system adds
    up the tier multiplier for each calendar day of the service month, divides that sum by the
    number of calendar days in the month, and rounds half up to four decimal places."

    Design: Difficulty/compensating_invariant/subsidy_adjustment_conserved_across_interim_then_reconciled_pay
    """
    ctx = build_rating_spine(
        stop_at="ACTIVE",
        domains=EQUAL_WEIGHT_DOMAINS,
        provider_overrides={
            "legal_name": "Rural Subsidy Center",
            "county_code": "C003",
            "region_code": "RURAL",
            "licensed_capacity": 60,
            "active_staff_fte": 5.00,
            "weekly_onsite_cap_hours": 12.0,
        },
        credentials=FOUR_VERIFIED_CREDENTIALS,
        claimed=TIER_TWO_POINTS,
        verified=TIER_TWO_POINTS,
        raw_score=4.0,
        award_clock="2026-08-25T00:00:00Z",
        activation_clock="2026-09-01T00:00:00Z",
    )
    provider_id = ctx["provider"]["id"]
    cycle_id = ctx["cycle"]["id"]

    compliance = validate_success(api.get_provider(provider_id, ADMIN))
    assert compliance["credential_compliance_pct"] == pytest.approx(80.00, abs=0.005), (
        "four verified 1.00-fte records against a declared 5.00 fte is exactly 80.00 percent"
    )

    awarded = validate_success(api.get_rating_cycle(cycle_id, ADMIN))
    assert awarded["domain_points"] == {
        "LEARNING_ENVIRONMENT": 12,
        "STAFF_QUALIFICATIONS": 12,
        "FAMILY_PARTNERSHIP": 10,
        "ADMINISTRATION": 10,
        "CHILD_ASSESSMENT": 10,
    }
    assert awarded["weighted_total"] == pytest.approx(54.00, abs=0.005)
    assert awarded["points_tier"] == 2
    assert awarded["highest_block_cleared"] == 3
    assert awarded["awarded_tier"] == 2
    assert awarded["effective_date"] == "2026-09-01T00:00:00.000Z"
    assert awarded["expires_on"] == "2028-08-31T23:59:59.999Z"
    assert awarded["status"] == "ACTIVE"

    # The claim's approval requires the cycle to be ACTIVE and PUBLISHED, and publication
    # cannot happen before the award date plus ten days (2026-09-04).
    set_clock("2026-09-20T00:00:00Z")
    published = publish_cycle(cycle_id)
    assert published["publication_status"] == "PUBLISHED"

    claim = submit_claim(provider_id, "2026-09", infant=20, toddler=15, preschool=40)
    assert claim["base_amount_cents"] == 275_000
    claim = approve_claim(claim["id"], "INTERIM")
    claim = pay_claim(claim["id"])

    paid = validate_success(api.get_subsidy_claim(claim["id"], ADMIN))
    assert paid["status"] == "PAID"
    assert paid["variant_applied"] == "INTERIM"
    assert float(paid["tier_multiplier_applied"]) == pytest.approx(1.0500, abs=0.00005)
    assert paid["base_amount_cents"] == 275_000
    assert paid["reimbursement_cents"] == 311_850
    assert validate_success(api.get_provider(provider_id, ADMIN))[
        "reimbursement_adjustment_cents"
    ] == 0

    set_clock("2026-09-22T00:00:00Z")
    appeal = file_appeal(provider_id, cycle_id, "SCORING_ERROR",
                        "Observation subscales were mis-transcribed.")
    appeal = start_appeal_review(appeal["id"], "reviewer_1")
    assert appeal["status"] == "UNDER_REVIEW"

    # Forward action: the sustained appeal restates the tier downward, which flags the paid
    # claim and parks the restatement on the provider's signed adjustment.
    sustained = validate_success(
        api.appeal_review_action(
            appeal["id"],
            {"action": "SUSTAIN", "adjusted_tier": 1, "note": "tier corrected downward"},
            make_reviewer_headers("reviewer_1"),
        )
    )
    assert sustained["status"] == "SUSTAINED"

    adjusted_cycle = validate_success(api.get_rating_cycle(cycle_id, ADMIN))
    assert adjusted_cycle["awarded_tier"] == 1
    assert adjusted_cycle["appeal_adjusted"] is True
    assert adjusted_cycle["effective_date"] == "2026-09-01T00:00:00.000Z"
    assert adjusted_cycle["expires_on"] == "2028-08-31T23:59:59.999Z"
    assert adjusted_cycle["publication_status"] == "UNPUBLISHED"

    flagged = validate_success(api.get_subsidy_claim(claim["id"], ADMIN))
    assert flagged["status"] == "RECONCILE_REQUIRED"
    assert validate_success(api.get_provider(provider_id, ADMIN))[
        "reimbursement_adjustment_cents"
    ] == -14_850, "297000 payable under the reconciled variant minus 311850 already paid"

    run_expiry_run()
    reactivated = validate_success(api.get_rating_cycle(cycle_id, ADMIN))
    assert reactivated["status"] == "ACTIVE"
    assert validate_success(api.get_provider(provider_id, ADMIN))["current_tier"] == 1

    # Compensating action: pay the reconciled amount.
    pay_claim(claim["id"])

    settled = validate_success(api.get_subsidy_claim(claim["id"], ADMIN))
    assert settled["status"] == "PAID"
    assert settled["variant_applied"] == "RECONCILED"
    assert float(settled["tier_multiplier_applied"]) == pytest.approx(1.0000, abs=0.00005)
    assert settled["base_amount_cents"] == 275_000
    assert settled["reimbursement_cents"] == 297_000
    assert validate_success(api.get_provider(provider_id, ADMIN))[
        "reimbursement_adjustment_cents"
    ] == 0, "the parked delta of -14850 must be released with zero drift"
