"""One entity's operation blocked by the state of a different, non-acting entity.

In each scenario the acting resource is perfectly well-formed and in a legal state;
what refuses the request is a sibling row — a staff credential, an appeal, or the
other observer named on the visit.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    approve_claim,
    build_rating_spine,
    file_appeal,
    make_admin_headers,
    make_observer_headers,
    make_provider_headers,
    make_reviewer_headers,
    pay_claim,
    set_clock,
    submit_claim,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]

#: Weights 0.30/0.25/0.20/0.15/0.10; LEARNING_ENVIRONMENT is the observation-linked
#: domain and needs a composite of at least 4.00 to clear block 1.
RURAL_DOMAINS = [
    {
        "domain_code": "LEARNING_ENVIRONMENT",
        "block_level": 1,
        "max_points": 30,
        "block_min_points": 12,
        "weight": 0.30,
        "observation_linked": True,
        "min_composite_for_block": 4.00,
    },
    {
        "domain_code": "STAFF_QUALIFICATIONS",
        "block_level": 1,
        "max_points": 25,
        "block_min_points": 10,
        "weight": 0.25,
        "observation_linked": False,
    },
    {
        "domain_code": "FAMILY_PARTNERSHIP",
        "block_level": 2,
        "max_points": 20,
        "block_min_points": 8,
        "weight": 0.20,
        "observation_linked": False,
    },
    {
        "domain_code": "ADMINISTRATION",
        "block_level": 2,
        "max_points": 15,
        "block_min_points": 6,
        "weight": 0.15,
        "observation_linked": False,
    },
    {
        "domain_code": "CHILD_ASSESSMENT",
        "block_level": 3,
        "max_points": 10,
        "block_min_points": 4,
        "weight": 0.10,
        "observation_linked": False,
    },
]

RURAL_POINTS = {
    "LEARNING_ENVIRONMENT": 26,
    "STAFF_QUALIFICATIONS": 22,
    "FAMILY_PARTNERSHIP": 16,
    "ADMINISTRATION": 12,
    "CHILD_ASSESSMENT": 8,
}

#: Lead averages 35/6 = 5.83; the secondary differs by more than 1.0 only on
#: PROGRAM_STRUCTURE, leaving five of six subscales matched at 83.33.
LEAD_SCORES = {
    "SPACE_FURNISHINGS": 6.0,
    "PERSONAL_CARE": 6.0,
    "LANGUAGE_REASONING": 6.0,
    "ACTIVITIES": 6.0,
    "INTERACTION": 6.0,
    "PROGRAM_STRUCTURE": 5.0,
}
SECONDARY_SCORES = {
    "SPACE_FURNISHINGS": 6.0,
    "PERSONAL_CARE": 6.0,
    "LANGUAGE_REASONING": 6.0,
    "ACTIVITIES": 5.0,
    "INTERACTION": 7.0,
    "PROGRAM_STRUCTURE": 3.0,
}

TIER_FOUR_POINTS = {
    "LEARNING_ENVIRONMENT": 24,
    "STAFF_QUALIFICATIONS": 20,
    "FAMILY_PARTNERSHIP": 16,
    "ADMINISTRATION": 12,
    "CHILD_ASSESSMENT": 8,
}


def _rural_spine(stop_at, legal_name, credentials, **overrides):
    """Rural provider on 2.00 declared fte, two reliable observers, composite 5.83."""
    params = {
        "stop_at": stop_at,
        "domains": RURAL_DOMAINS,
        "provider_overrides": {
            "legal_name": legal_name,
            "county_code": "MARION",
            "region_code": "RURAL",
            "licensed_capacity": 60,
            "active_staff_fte": 2.00,
            "weekly_onsite_cap_hours": 12.0,
        },
        "credentials": credentials,
        "claimed": RURAL_POINTS,
        "verified": RURAL_POINTS,
        "with_secondary": True,
        "lead_per_subscale": LEAD_SCORES,
        "secondary_per_subscale": SECONDARY_SCORES,
        "window_start": "2026-08-05T09:00:00Z",
        "window_end": "2026-08-05T13:00:00Z",
    }
    params.update(overrides)
    return build_rating_spine(**params)


def _observer_row(api, observer_id):
    observers, _meta = validate_paginated(api.list_observers(ADMIN))
    matches = [row for row in observers if row["id"] == observer_id]
    assert matches, f"observer {observer_id} must be listable"
    return matches[0]


# --- 1. a PENDING staff credential blocks the cycle award --------------------

TWO_VERIFIED_CREDENTIALS = [
    {"role_type": "DIRECTOR", "credential_level": 5, "fte": 1.00,
     "registry_status": "VERIFIED", "expires_on": "2027-12-31"},
    {"role_type": "LEAD_TEACHER", "credential_level": 3, "fte": 0.80,
     "registry_status": "VERIFIED", "expires_on": "2027-12-31"},
]


def test_a_pending_staff_credential_blocks_the_award_until_the_registry_answers(api):
    """PRD §3.5: "Second, registry completeness: no staff credential of the provider whose
    `employment_status` is `ACTIVE` may sit in `UNLINKED` or `PENDING` — every active staff
    record must be resolved against the professional development registry, whether resolved to
    `VERIFIED` or to `EXPIRED` — and a violation is `ERR_CREDENTIAL_REGISTRY_UNLINKED` with
    HTTP 422."
    PRD §3.2: "The numerator is the sum of the `fte` values of the provider's staff credential
    records that satisfy all four of these conditions at once: the record belongs to that
    provider, its `employment_status` is `ACTIVE`, its `registry_status` is `VERIFIED`, its
    `expires_on` is on or after the logical clock date, and its `credential_level` is at least
    the minimum for its `role_type`."
    PRD §3.2: "Records that are `UNLINKED`, `PENDING`, or `EXPIRED` contribute nothing, and
    `SEPARATED` records are excluded from the numerator but never from the denominator."

    Design: Difficulty/cross_entity_state_dependency/staff_credential_registry_state_gates_rating_cycle_award
    """
    ctx = _rural_spine(
        "OBSERVATION_FINALIZED",
        "Kestrel Learning Center",
        TWO_VERIFIED_CREDENTIALS + [
            {"role_type": "LEAD_TEACHER", "credential_level": 3, "fte": 0.20,
             "registry_status": "PENDING"},
        ],
    )
    provider_id = ctx["provider"]["id"]
    before = validate_success(api.get_provider(provider_id, ADMIN))
    assert before["credential_compliance_pct"] == pytest.approx(90.00, abs=0.005), (
        "only the two VERIFIED records (1.00 + 0.80) count toward the 2.00 denominator, "
        f"got {before['credential_compliance_pct']}"
    )
    assert ctx["cycle"]["observation_composite"] == pytest.approx(5.83, abs=0.005)

    set_clock("2026-08-10T00:00:00Z")
    refused = api.award_cycle(
        ctx["cycle"]["id"], {"score_variant": "FINAL"}, make_admin_headers("admin-k-001")
    )
    validate_error(refused, "ERR_CREDENTIAL_REGISTRY_UNLINKED", 422)
    held = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert held["status"] == "OBSERVATION_FINALIZED"
    assert held["awarded_tier"] is None
    assert held["weighted_total"] is None
    assert held["awarded_on"] is None

    pending, _meta = validate_paginated(
        api.list_staff_credentials(
            ADMIN, params={"provider_id": provider_id, "registry_status": "PENDING"}
        )
    )
    assert len(pending) == 1, f"exactly one record must be PENDING, got {pending}"

    # Resolving the record to EXPIRED satisfies registry completeness without adding
    # anything to the compliance numerator.
    resolved = validate_success(
        api.registry_link(
            pending[0]["id"],
            {"registry_status": "EXPIRED", "verified_on": "2025-06-01",
             "expires_on": "2026-06-30"},
            ADMIN,
        )
    )
    assert resolved["registry_status"] == "EXPIRED"
    after = validate_success(api.get_provider(provider_id, ADMIN))
    assert after["credential_compliance_pct"] == pytest.approx(90.00, abs=0.005), (
        "an EXPIRED record contributes nothing, so compliance must be unmoved at 90.00, "
        f"got {after['credential_compliance_pct']}"
    )

    awarded = validate_success(
        api.award_cycle(
            ctx["cycle"]["id"], {"score_variant": "FINAL"}, make_admin_headers("admin-k-001")
        )
    )
    assert awarded["status"] == "AWARDED"
    assert awarded["domain_points"] == TIER_FOUR_POINTS
    assert awarded["weighted_total"] == pytest.approx(80.00, abs=0.005), (
        f"weighted_total must be 80.00, got {awarded['weighted_total']}"
    )
    assert awarded["points_tier"] == 4
    assert awarded["highest_block_cleared"] == 3
    assert awarded["awarded_tier"] == 4
    assert awarded["awarded_by_user_id"] == "admin-k-001"
    assert awarded["validity_months"] == 36
    assert awarded["effective_date"] == "2026-09-01T00:00:00.000Z"
    assert awarded["expires_on"] == "2029-08-31T23:59:59.999Z"
    assert awarded["rerating_window_opens_on"] == "2029-06-02T00:00:00.000Z"


# --- 2. a freshly filed appeal blocks the reconciliation payment -------------


def test_a_second_filed_appeal_blocks_the_reconciliation_payment_of_a_flagged_claim(api):
    """PRD §3.7: "From `RECONCILE_REQUIRED` — where a claim lands when a sustained appeal
    changed the tier under which it was originally paid — payment additionally requires the
    provider's `current_tier` to be non-null at payment time and requires that no appeal of the
    claim's cycle be sitting in `FILED`, `UNDER_REVIEW`, or `INFO_REQUESTED`."
    PRD §3.6: "In the second hop, caused by the tier change, every subsidy claim of that
    provider in `PAID` whose service month starts inside the cycle's validity window moves
    `PAID → RECONCILE_REQUIRED`. In the third hop, caused by each of those claims being
    flagged, the provider's `reimbursement_adjustment_cents` changes by the difference between
    what the claim would be worth under the reconciled variant and what was actually paid."
    PRD §3.6: "A provider may withdraw its own appeal from `FILED`, `UNDER_REVIEW`, or
    `INFO_REQUESTED`; withdrawal moves the appeal to `WITHDRAWN`, stamps `decided_on`, and
    returns the cycle to `ACTIVE` with publication restored exactly as on a denial."
    PRD §3.7: "A reconciled payment rewrites `reimbursement_cents` under the reconciled variant
    and returns the provider's `reimbursement_adjustment_cents` to its pre-cascade value, so the
    pair of flagging-then-repaying leaves that conserved balance unchanged."

    Design: Difficulty/cross_entity_state_dependency/open_appeal_state_gates_subsidy_claim_reconciliation_payment
    """
    ctx = _rural_spine(
        "PUBLISHED",
        "Larkspur Family Child Care",
        TWO_VERIFIED_CREDENTIALS,
        award_clock="2026-08-10T00:00:00Z",
        activation_clock="2026-09-05T00:00:00Z",
    )
    provider_id = ctx["provider"]["id"]
    cycle_id = ctx["cycle"]["id"]
    assert ctx["cycle"]["awarded_tier"] == 4
    assert ctx["cycle"]["publication_status"] == "PUBLISHED"

    claim = submit_claim(provider_id, "2026-09", infant=100, toddler=200, preschool=300)
    assert claim["base_amount_cents"] == 2_170_000, (
        f"100x4500 + 200x3800 + 300x3200 is 2170000, got {claim['base_amount_cents']}"
    )
    approve_claim(claim["id"], variant="INTERIM")
    paid = pay_claim(claim["id"])
    assert paid["status"] == "PAID"
    assert paid["reimbursement_cents"] == 3_046_680, (
        "tier 4 pays at 1.30 and RURAL at 1.08, giving 631800 + 1067040 + 1347840, "
        f"got {paid['reimbursement_cents']}"
    )

    set_clock("2026-09-08T00:00:00Z")
    first = file_appeal(provider_id, cycle_id, "SCORING_ERROR",
                        "Composite understated by a keying error.")
    reviewer = make_reviewer_headers("reviewer-l-904")
    validate_success(api.appeal_review_action(first["id"], {"action": "START"}, reviewer))
    validate_success(
        api.appeal_review_action(
            first["id"],
            {"action": "SUSTAIN", "adjusted_tier": 5, "note": "Tier corrected to 5."},
            reviewer,
        )
    )
    flagged = validate_success(api.get_subsidy_claim(claim["id"], ADMIN))
    assert flagged["status"] == "RECONCILE_REQUIRED"

    # A second, still-FILED appeal is the only thing standing between the flagged claim
    # and its reconciliation payment.
    second = file_appeal(provider_id, cycle_id, "PROCEDURAL",
                         "Notice of the corrected award was not served.")
    assert second["status"] == "FILED"

    blocked = api.pay_claim(claim["id"], ADMIN)
    validate_error(blocked, "ERR_OPEN_APPEAL_BLOCKS_ACTION", 409)
    unpaid = validate_success(api.get_subsidy_claim(claim["id"], ADMIN))
    assert unpaid["status"] == "RECONCILE_REQUIRED"
    assert unpaid["reimbursement_cents"] == 3_046_680, (
        f"the refused payment must not rewrite the amount, got {unpaid['reimbursement_cents']}"
    )
    assert unpaid["tier_multiplier_applied"] == pytest.approx(1.3000, abs=0.00005)
    assert unpaid["variant_applied"] == "INTERIM"
    assert unpaid["paid_on"] == paid["paid_on"]
    mid = validate_success(api.get_provider(provider_id, ADMIN))
    assert mid["reimbursement_adjustment_cents"] == 468_720, (
        "the cascade recorded 3515400 - 3046680 as owed to the provider, "
        f"got {mid['reimbursement_adjustment_cents']}"
    )

    withdrawn = validate_success(
        api.appeal_provider_action(
            second["id"],
            {"action": "WITHDRAW", "narrative": "Notice located; appeal withdrawn."},
            make_provider_headers(provider_id),
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"
    restored = validate_success(api.get_rating_cycle(cycle_id, ADMIN))
    assert restored["status"] == "ACTIVE"
    assert restored["publication_status"] == "PUBLISHED"
    untouched = validate_success(api.get_subsidy_claim(claim["id"], ADMIN))
    assert untouched["status"] == "RECONCILE_REQUIRED", (
        "withdrawing the appeal must not itself settle the claim"
    )

    repaid = validate_success(api.pay_claim(claim["id"], ADMIN))
    assert repaid["status"] == "PAID"
    assert repaid["variant_applied"] == "RECONCILED"
    assert repaid["tier_multiplier_applied"] == pytest.approx(1.5000, abs=0.00005), (
        "all 30 calendar days of 2026-09 sit at awarded_tier 5, so the day-weighted "
        f"multiplier is 1.5000, got {repaid['tier_multiplier_applied']}"
    )
    assert repaid["base_amount_cents"] == 2_170_000
    assert repaid["reimbursement_cents"] == 3_515_400, (
        f"tier 5 at 1.50 with the RURAL 1.08 factor gives 3515400, "
        f"got {repaid['reimbursement_cents']}"
    )
    final = validate_success(api.get_provider(provider_id, ADMIN))
    assert final["reimbursement_adjustment_cents"] == 0, (
        "the flag-then-repay pair must return the conserved balance to its pre-cascade 0, "
        f"got {final['reimbursement_adjustment_cents']}"
    )


# --- 3. the non-acting secondary observer blocks both scoring and finalizing --


def test_a_lapsed_secondary_observer_blocks_finalization_and_the_leads_own_rescore(api):
    """PRD §3.4: "The reliability rule requires that every observer named on the visit be in
    `RELIABLE` standing with a `reliability_certified_until` date on or after the calendar date
    of `window_start`; a `LAPSED`, `RETIRED`, or `PROVISIONAL` observer, or one whose
    certification ends before the visit begins, is refused with `ERR_OBSERVER_NOT_RELIABLE` and
    HTTP 422. That same rule is re-checked at score submission and again at finalization, so an
    observer whose certification lapses mid-cycle cannot slip a number into the record."
    PRD §3.4: "A certify decision whose `anchor_agreement_pct` is below 85.00 moves the observer
    to `LAPSED` and clears `reliability_certified_until` to null."
    PRD §3.4: "A certify decision whose `anchor_agreement_pct` is at least 85.00 moves the
    observer to `RELIABLE`, storing the agreement figure and writing
    `reliability_certified_until` — the inclusive last date on which that observer's scores are
    admissible."

    Design: Difficulty/cross_entity_state_dependency/observer_reliability_state_gates_observation_visit_finalization_and_scoring
    """
    ctx = _rural_spine("RELIABILITY_CHECK", "Meadowbrook Learning Center",
                       TWO_VERIFIED_CREDENTIALS)
    visit_id = ctx["visit"]["id"]
    lead_id = ctx["lead"]["id"]
    secondary_id = ctx["secondary"]["id"]
    assert ctx["visit"]["composite"] == pytest.approx(5.83, abs=0.005)
    assert ctx["visit"]["reliability_pct"] == pytest.approx(83.33, abs=0.005)

    degraded = validate_success(
        api.certify_observer(
            secondary_id, {"decision": "CERTIFY", "anchor_agreement_pct": 82.00}, ADMIN
        )
    )
    assert degraded["status"] == "LAPSED", (
        f"an anchor agreement of 82.00 is below 85.00, got status {degraded['status']}"
    )
    assert degraded["anchor_agreement_pct"] == pytest.approx(82.00, abs=0.005)
    assert degraded["reliability_certified_until"] is None
    assert _observer_row(api, lead_id)["status"] == "RELIABLE", (
        "the lead observer must be untouched by the secondary's anchor check"
    )

    blocked_finalize = api.finalize_visit(visit_id, ADMIN)
    validate_error(blocked_finalize, "ERR_OBSERVER_NOT_RELIABLE", 422)
    held_visit = validate_success(api.get_observation_visit(visit_id, ADMIN))
    assert held_visit["status"] == "RELIABILITY_CHECK"
    assert held_visit["finalized_on"] is None
    assert validate_success(
        api.get_rating_cycle(ctx["cycle"]["id"], ADMIN)
    )["status"] == "OBSERVATION_SCHEDULED"

    # The acting observer here is the still-RELIABLE lead, yet the rule tests every
    # observer the visit names, so the rescore is refused too.
    blocked_rescore = api.submit_score(
        visit_id,
        {"subscale_code": "PROGRAM_STRUCTURE", "raw_score": 6.0},
        make_observer_headers(lead_id),
    )
    validate_error(blocked_rescore, "ERR_OBSERVER_NOT_RELIABLE", 422)
    after_refusal = validate_success(api.get_observation_visit(visit_id, ADMIN))
    assert after_refusal["rescore_count"] == 0, (
        f"a refused submission must not count as a rescore, got {after_refusal['rescore_count']}"
    )
    assert after_refusal["composite"] == pytest.approx(5.83, abs=0.005)
    assert after_refusal["reliability_pct"] == pytest.approx(83.33, abs=0.005)
    current, _meta = validate_paginated(
        api.list_observation_scores(
            ADMIN,
            params={
                "observation_visit_id": visit_id,
                "observer_id": lead_id,
                "subscale_code": "PROGRAM_STRUCTURE",
                "is_current": True,
            },
        )
    )
    assert len(current) == 1
    assert current[0]["attempt_no"] == 1, (
        f"no replacement row may exist, got attempt_no {current[0]['attempt_no']}"
    )
    assert current[0]["raw_score"] == pytest.approx(5.0, abs=0.005)

    recertified = validate_success(
        api.certify_observer(
            secondary_id,
            {"decision": "CERTIFY", "anchor_agreement_pct": 88.00,
             "certified_until": "2027-06-30"},
            ADMIN,
        )
    )
    assert recertified["status"] == "RELIABLE"
    assert recertified["anchor_agreement_pct"] == pytest.approx(88.00, abs=0.005)
    assert recertified["reliability_certified_until"] == "2027-06-30"

    # Byte-identical to the refused finalize; only the sibling observer changed.
    finalized = validate_success(api.finalize_visit(visit_id, ADMIN))
    assert finalized["status"] == "FINALIZED"
    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["status"] == "OBSERVATION_FINALIZED"
    assert cycle["observation_composite"] == pytest.approx(5.83, abs=0.005)
    assert cycle["reliability_pct"] == pytest.approx(83.33, abs=0.005)

    set_clock("2026-08-10T00:00:00Z")
    awarded = validate_success(
        api.award_cycle(
            cycle["id"], {"score_variant": "FINAL"}, make_admin_headers("admin-m-001")
        )
    )
    assert awarded["domain_points"] == TIER_FOUR_POINTS
    assert awarded["weighted_total"] == pytest.approx(80.00, abs=0.005)
    assert awarded["points_tier"] == 4
    assert awarded["highest_block_cleared"] == 3
    assert awarded["awarded_tier"] == 4
    assert awarded["score_variant"] == "FINAL"
    assert awarded["validity_months"] == 36
    assert awarded["effective_date"] == "2026-09-01T00:00:00.000Z"
    assert awarded["expires_on"] == "2029-08-31T23:59:59.999Z"
