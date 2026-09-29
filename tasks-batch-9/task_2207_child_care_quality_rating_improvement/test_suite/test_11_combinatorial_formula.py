"""Formulas whose answer depends on combining several inputs in a pinned order.

Every scenario here couples the credential compliance percentage, the observation
composite, the per-domain block-minimum table and the money rounding order, so the
expected number can only be reproduced by evaluating the PRD formulas in the order
the PRD pins them.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    accept_grant,
    adjudicate_expenditure,
    award_cycle,
    build_rating_spine,
    credential_specs,
    offer_grant,
    set_clock,
    submit_expenditure,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


# --- Mode (a): nested min() over a sequentially folded block gate ------------

#: LEARNING_ENVIRONMENT and STAFF_QUALIFICATIONS clear block 1 comfortably, while
#: FAMILY_PARTNERSHIP carries a block minimum of 18 that its verified 17 points miss.
DOMAINS_A = [
    {
        "domain_code": "LEARNING_ENVIRONMENT",
        "block_level": 1,
        "max_points": 40,
        "block_min_points": 20,
        "weight": 0.30,
        "observation_linked": True,
        "min_composite_for_block": 4.00,
    },
    {
        "domain_code": "STAFF_QUALIFICATIONS",
        "block_level": 1,
        "max_points": 30,
        "block_min_points": 15,
        "weight": 0.25,
        "observation_linked": False,
    },
    {
        "domain_code": "FAMILY_PARTNERSHIP",
        "block_level": 2,
        "max_points": 20,
        "block_min_points": 18,
        "weight": 0.20,
        "observation_linked": False,
    },
    {
        "domain_code": "ADMINISTRATION",
        "block_level": 2,
        "max_points": 20,
        "block_min_points": 10,
        "weight": 0.15,
        "observation_linked": False,
    },
    {
        "domain_code": "CHILD_ASSESSMENT",
        "block_level": 3,
        "max_points": 10,
        "block_min_points": 6,
        "weight": 0.10,
        "observation_linked": False,
    },
]

CLAIMED_A = {
    "LEARNING_ENVIRONMENT": 38,
    "STAFF_QUALIFICATIONS": 30,
    "FAMILY_PARTNERSHIP": 17,
    "ADMINISTRATION": 20,
    "CHILD_ASSESSMENT": 10,
}
VERIFIED_A = {
    "LEARNING_ENVIRONMENT": 38,
    "STAFF_QUALIFICATIONS": 29,
    "FAMILY_PARTNERSHIP": 17,
    "ADMINISTRATION": 20,
    "CHILD_ASSESSMENT": 10,
}


def _credentials_a():
    """Qualifying fte 1.00 + 4.00 + 4.60 = 9.60 against an active_staff_fte of 10.00."""
    specs = [
        {
            "role_type": "DIRECTOR",
            "credential_level": 4,
            "fte": 1.00,
            "expires_on": "2028-07-15",
        }
    ]
    specs += credential_specs(4.00, "LEAD_TEACHER", 3, expires_on="2028-07-15")
    specs += credential_specs(4.60, "ASSISTANT", 1, expires_on="2028-07-15")
    return specs


def _spine_a(stop_at="AWARDED"):
    """Two reliable observers, every subscale at 6.0, credential compliance 96.00."""
    return build_rating_spine(
        stop_at=stop_at,
        domains=DOMAINS_A,
        provider_overrides={
            "legal_name": "Blocked Ladder Academy",
            "license_number": "LIC-2207-D",
            "county_code": "KNG",
            "region_code": "URBAN",
            "licensed_capacity": 120,
            "active_staff_fte": 10.00,
            "weekly_onsite_cap_hours": 24.0,
        },
        credentials=_credentials_a(),
        claimed=CLAIMED_A,
        verified=VERIFIED_A,
        raw_score=6.0,
        with_secondary=True,
        window_start="2026-08-12T08:00:00Z",
        window_end="2026-08-12T12:00:00Z",
        enrol_clock="2026-08-10T00:00:00Z",
        cycle_clock="2026-08-10T00:00:00Z",
        award_clock="2026-08-13T00:00:00Z",
    )


def test_block_two_shortfall_collapses_the_fold_and_caps_tier_five_points_at_tier_two(api):
    """PRD §3.5: "For each block level 1, 2, and 3 the system marks `block_clearance` as
    `CLEARED` when every domain belonging to that block satisfies two conditions — its
    awarded points are at least that domain's `block_min_points`, and either the domain is
    not observation-linked, or the cycle has a non-null observation composite that is at
    least that domain's `min_composite_for_block` — and marks it `NOT_CLEARED` when any
    domain in the block fails either condition."
    PRD §3.5: "The blocks are then folded sequentially: `highest_block_cleared` is 0 when
    block 1 is `NOT_CLEARED`, and otherwise the largest number K from 1 to 3 such that
    blocks 1 through K are all `CLEARED`. Clearing block 3 while block 2 remains
    `NOT_CLEARED` therefore still leaves `highest_block_cleared` at 1."
    PRD §3.5: "Each level of block clearance implies a tier ceiling: clearing no blocks
    caps the rating at tier 1, clearing block 1 caps it at tier 2, clearing blocks 1 and 2
    caps it at tier 4, and clearing all three permits tier 5. The `awarded_tier` is the
    smaller of `points_tier` and that ceiling."

    Design: Difficulty/combinatorial_formula/mode_a_nested_min_over_sequential_block_fold
    """
    cycle = _spine_a("AWARDED")["cycle"]

    assert cycle["weighted_total"] == pytest.approx(96.17, abs=0.005), (
        f"weighted_total must be 96.17, got {cycle['weighted_total']}"
    )
    assert cycle["points_tier"] == 5, (
        f"a weighted total of 96.17 is points_tier 5, got {cycle['points_tier']}"
    )
    block = {str(k): v for k, v in cycle["block_clearance"].items()}
    assert block["1"] == "CLEARED", f"block 1 must be CLEARED, got {block['1']}"
    assert block["2"] == "NOT_CLEARED", (
        f"FAMILY_PARTNERSHIP is 17 points against a block minimum of 18, so block 2 must "
        f"be NOT_CLEARED, got {block['2']}"
    )
    assert block["3"] == "CLEARED", f"block 3 must be CLEARED, got {block['3']}"
    assert cycle["highest_block_cleared"] == 1, (
        f"block 3 cleared while block 2 is NOT_CLEARED still folds to 1, got "
        f"{cycle['highest_block_cleared']}"
    )
    assert cycle["awarded_tier"] == 2, (
        f"awarded_tier is min(points_tier 5, ceiling 2) == 2, got {cycle['awarded_tier']}"
    )
    assert cycle["status"] == "AWARDED"


def test_nested_min_award_derives_each_domain_point_entry_from_its_own_rule(api):
    """PRD §3.5: "once a composite exists, the domain's points are instead derived from it
    by multiplying the domain's `max_points` by an observation fraction and rounding half up
    to a whole integer. That fraction is 1.00 when the composite is at least 6.00, 0.80 when
    it is at least 5.00, 0.60 when it is at least 4.00, 0.40 when it is at least 3.00, and
    0.20 otherwise."
    PRD §3.5: "For the `STAFF_QUALIFICATIONS` domain, the credited number is capped: the cap
    is the domain's `max_points` multiplied by a credential fraction and rounded half up to a
    whole integer, and the awarded points are the smaller of the credited number and that
    cap. The credential fraction is 1.00 when `credential_compliance_pct` is at least 95.00,
    0.80 when it is at least 85.00, 0.60 when it is at least 70.00, 0.40 when it is at least
    55.00, and 0.20 otherwise."
    PRD §3.5: "For every other domain the awarded points are simply the credited number."

    Design: Difficulty/combinatorial_formula/mode_a_nested_min_over_sequential_block_fold
    """
    ctx = _spine_a("AWARDED")
    cycle = ctx["cycle"]

    assert cycle["observation_composite"] == pytest.approx(6.00, abs=0.005), (
        f"six lead scores of 6.0 average to 6.00, got {cycle['observation_composite']}"
    )
    assert cycle["reliability_pct"] == pytest.approx(100.00, abs=0.005), (
        f"all six subscales matched, so reliability_pct is 100.00, got "
        f"{cycle['reliability_pct']}"
    )
    provider = validate_success(api.get_provider(ctx["provider"]["id"], ADMIN))
    assert provider["credential_compliance_pct"] == pytest.approx(96.00, abs=0.005), (
        f"qualifying fte 9.60 over active_staff_fte 10.00 is 96.00, got "
        f"{provider['credential_compliance_pct']}"
    )

    points = cycle["domain_points"]
    assert points["LEARNING_ENVIRONMENT"] == 40, (
        f"40 max_points times the 1.00 observation fraction is 40, not the verified 38; "
        f"got {points['LEARNING_ENVIRONMENT']}"
    )
    assert points["STAFF_QUALIFICATIONS"] == 29, (
        f"min(verified 29, cap 30) is 29, got {points['STAFF_QUALIFICATIONS']}"
    )
    assert points["FAMILY_PARTNERSHIP"] == 17
    assert points["ADMINISTRATION"] == 20
    assert points["CHILD_ASSESSMENT"] == 10


def test_tier_two_award_writes_the_twenty_four_month_validity_window(api):
    """PRD §3.5: "On a fresh award the `effective_date` is the first day of the month after
    the award date at midnight UTC with three fractional digits of zero."
    PRD §3.5: "`validity_months` is 36 when `awarded_tier` is at least 4 and 24 otherwise.
    The `expires_on` instant is the `effective_date` advanced by that many calendar months
    and then pulled back by one day, at 23:59:59.999 UTC; because the effective date is
    always the first day of a month, month addition never needs day clamping.
    `rerating_window_opens_on` is the expiry date minus 90 calendar days at midnight UTC —
    the earliest date on which a re-rating cycle may be opened."

    Design: Difficulty/combinatorial_formula/mode_a_nested_min_over_sequential_block_fold
    """
    cycle = _spine_a("AWARDED")["cycle"]

    assert cycle["awarded_tier"] == 2
    assert cycle["validity_months"] == 24, (
        f"awarded_tier 2 is below 4, so validity_months is 24, got "
        f"{cycle['validity_months']}"
    )
    assert cycle["effective_date"] == "2026-09-01T00:00:00.000Z", (
        f"awarded on 2026-08-13, so effective_date is 2026-09-01T00:00:00.000Z, got "
        f"{cycle['effective_date']}"
    )
    assert cycle["expires_on"] == "2028-08-31T23:59:59.999Z", (
        f"2026-09-01 plus 24 months less one day, got {cycle['expires_on']}"
    )
    assert cycle["rerating_window_opens_on"] == "2028-06-02T00:00:00.000Z", (
        f"2028-08-31 minus 90 days, got {cycle['rerating_window_opens_on']}"
    )


# --- Mode (b): pinned rounding before the three-way minimum ------------------

DOMAINS_B = [
    {
        "domain_code": "LEARNING_ENVIRONMENT",
        "block_level": 1,
        "max_points": 40,
        "block_min_points": 12,
        "weight": 0.30,
        "observation_linked": True,
        "min_composite_for_block": 3.00,
    },
    {
        "domain_code": "STAFF_QUALIFICATIONS",
        "block_level": 1,
        "max_points": 30,
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
        "max_points": 20,
        "block_min_points": 8,
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

CLAIMED_B = {
    "LEARNING_ENVIRONMENT": 18,
    "STAFF_QUALIFICATIONS": 16,
    "FAMILY_PARTNERSHIP": 11,
    "ADMINISTRATION": 10,
    "CHILD_ASSESSMENT": 6,
}
VERIFIED_B = {
    "LEARNING_ENVIRONMENT": 18,
    "STAFF_QUALIFICATIONS": 14,
    "FAMILY_PARTNERSHIP": 10,
    "ADMINISTRATION": 9,
    "CHILD_ASSESSMENT": 5,
}

#: Three of the four lines have a gross entitlement landing exactly on a half cent:
#: 12345 * 0.90 == 11110.5, 22222 * 0.75 == 16666.5 and 9999 * 0.50 == 4999.5.
EXPENDITURES_B = [
    ("EQUIPMENT", 12345, "2026-09-02"),
    ("PROF_DEV", 30000, "2026-09-03"),
    ("FACILITY", 22222, "2026-09-04"),
    ("ADMIN", 9999, "2026-09-05"),
]


def _credentials_b():
    """Qualifying fte 1.00 + 2.50 + 3.00 = 6.50 against an active_staff_fte of 10.00."""
    specs = [
        {
            "role_type": "DIRECTOR",
            "credential_level": 4,
            "fte": 1.00,
            "expires_on": "2028-06-30",
        }
    ]
    specs += credential_specs(2.50, "LEAD_TEACHER", 3, expires_on="2028-06-30")
    specs += credential_specs(3.00, "ASSISTANT", 1, expires_on="2028-06-30")
    return specs


def _grant_b_with_four_approved_lines():
    """Tier-2 active provider, an OPEN 1,000,000 cent grant and four APPROVED lines."""
    ctx = build_rating_spine(
        stop_at="ACTIVE",
        domains=DOMAINS_B,
        provider_overrides={
            "legal_name": "Half Cent Family Care",
            "license_number": "LIC-2207-E",
            "county_code": "PRC",
            "region_code": "URBAN",
            "licensed_capacity": 50,
            "active_staff_fte": 10.00,
            "weekly_onsite_cap_hours": 20.0,
        },
        credentials=_credentials_b(),
        claimed=CLAIMED_B,
        verified=VERIFIED_B,
        raw_score=3.5,
        window_start="2026-08-12T09:00:00Z",
        window_end="2026-08-12T12:00:00Z",
        enrol_clock="2026-08-10T00:00:00Z",
        cycle_clock="2026-08-10T00:00:00Z",
        award_clock="2026-08-13T00:00:00Z",
        activation_clock="2026-09-01T00:00:00Z",
    )
    set_clock("2026-09-06T00:00:00Z")
    grant = offer_grant(
        ctx["provider"]["id"], ctx["cycle"]["id"], 1_000_000, "2026-12-31"
    )
    grant = accept_grant(ctx["provider"]["id"], grant["id"])
    lines = {}
    for category, amount, invoice_date in EXPENDITURES_B:
        line = submit_expenditure(
            ctx["provider"]["id"], grant["id"], category, amount, invoice_date
        )
        lines[category] = adjudicate_expenditure(line["id"], "APPROVE")
    return ctx, grant, lines


def test_reimbursement_rounds_each_gross_to_whole_cents_before_the_three_way_minimum(api):
    """PRD §3.8: "Its gross entitlement is its `amount_cents` multiplied by the match rate
    for its category — 0.90 for `EQUIPMENT`, 1.00 for `PROF_DEV`, 0.75 for `FACILITY`, and
    0.50 for `ADMIN` — rounded half up to whole cents. Its category room is that category's
    ceiling minus that category's running total, and its grant room is the
    `awarded_amount_cents` minus the grant-level running total. The line's
    `reimbursable_cents` is the smallest of the gross entitlement, the category room, and the
    grant room, floored at zero so it can never be negative; its `disallowed_cents` is its
    `amount_cents` minus its `reimbursable_cents`; and the line moves to `REIMBURSED`."

    Design: Difficulty/combinatorial_formula/mode_b_pinned_round_before_min_in_grant_waterfall
    """
    _ctx, grant, lines = _grant_b_with_four_approved_lines()
    validate_success(api.reimburse_grant(grant["id"], ADMIN))

    expected = {
        "EQUIPMENT": (11111, 1234),
        "PROF_DEV": (30000, 0),
        "FACILITY": (16667, 5555),
        "ADMIN": (5000, 4999),
    }
    for category, (reimbursable, disallowed) in expected.items():
        line = validate_success(
            api.get_grant_expenditure(lines[category]["id"], ADMIN)
        )
        assert line["reimbursable_cents"] == reimbursable, (
            f"{category} reimbursable_cents must be {reimbursable}, got "
            f"{line['reimbursable_cents']}"
        )
        assert line["disallowed_cents"] == disallowed, (
            f"{category} disallowed_cents must be {disallowed}, got "
            f"{line['disallowed_cents']}"
        )
        assert line["status"] == "REIMBURSED", (
            f"{category} line must move to REIMBURSED, got {line['status']}"
        )


def test_reimbursed_total_is_the_sum_of_rounded_lines_and_never_re_rounded(api):
    """PRD §3.8: "The rounding order here is pinned: each line's gross is rounded to whole
    cents before the three-way minimum is taken, and the per-line reimbursable values are
    summed afterwards without any further rounding — summing unrounded gross amounts and
    rounding the total instead is forbidden and produces a different answer."
    PRD §3.8: "When the run finishes, the grant's `reimbursed_cents` becomes the grant-level
    running total, `committed_cents` decreases by the total `amount_cents` of the lines just
    processed, `available_cents` is recomputed as `awarded_amount_cents` minus
    `committed_cents` minus `reimbursed_cents`, `category_spend_cents` is updated, and the
    grant's `version` increments by 1."

    Design: Difficulty/combinatorial_formula/mode_b_pinned_round_before_min_in_grant_waterfall
    """
    _ctx, grant, _lines = _grant_b_with_four_approved_lines()
    reimbursed = validate_success(api.reimburse_grant(grant["id"], ADMIN))

    assert reimbursed["reimbursed_cents"] == 62778, (
        f"11111 + 30000 + 16667 + 5000 == 62778; rounding the summed unrounded grosses "
        f"would yield 62777, got {reimbursed['reimbursed_cents']}"
    )
    assert reimbursed["reimbursed_cents"] != 62777
    assert reimbursed["committed_cents"] == 0, (
        f"all four lines left SUBMITTED, so committed_cents returns to 0, got "
        f"{reimbursed['committed_cents']}"
    )
    assert reimbursed["available_cents"] == 937_222, (
        f"1000000 - 0 - 62778 == 937222, got {reimbursed['available_cents']}"
    )
    assert reimbursed["status"] == "OPEN"


def test_tier_two_award_precedes_the_grant_offer_that_the_waterfall_settles(api):
    """PRD §3.5: "From that total alone comes `points_tier`: 5 when the weighted total is at
    least 85.00, 4 when it is at least 70.00, 3 when it is at least 55.00, 2 when it is at
    least 40.00, and 1 otherwise."
    PRD §3.5: "For the `STAFF_QUALIFICATIONS` domain, the credited number is capped: the cap
    is the domain's `max_points` multiplied by a credential fraction and rounded half up to a
    whole integer, and the awarded points are the smaller of the credited number and that
    cap."

    Design: Difficulty/combinatorial_formula/mode_b_pinned_round_before_min_in_grant_waterfall
    """
    ctx, _grant, _lines = _grant_b_with_four_approved_lines()
    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))

    assert cycle["observation_composite"] == pytest.approx(3.50, abs=0.005)
    assert cycle["domain_points"]["LEARNING_ENVIRONMENT"] == 16, (
        f"40 max_points times the 0.40 observation fraction is 16, got "
        f"{cycle['domain_points']['LEARNING_ENVIRONMENT']}"
    )
    assert cycle["domain_points"]["STAFF_QUALIFICATIONS"] == 12, (
        f"min(verified 14, cap 12) is 12 at credential compliance 65.00, got "
        f"{cycle['domain_points']['STAFF_QUALIFICATIONS']}"
    )
    assert cycle["weighted_total"] == pytest.approx(43.75, abs=0.005), (
        f"weighted_total must be 43.75, got {cycle['weighted_total']}"
    )
    assert cycle["points_tier"] == 2
    assert cycle["awarded_tier"] == 2, (
        f"awarded_tier must be 2, got {cycle['awarded_tier']}"
    )


# --- Mode (c): pinned order compliance -> cap -> tier -> tier-keyed gate ------

DOMAINS_C = [
    {
        "domain_code": "LEARNING_ENVIRONMENT",
        "block_level": 1,
        "max_points": 40,
        "block_min_points": 20,
        "weight": 0.30,
        "observation_linked": True,
        "min_composite_for_block": 4.00,
    },
    {
        "domain_code": "STAFF_QUALIFICATIONS",
        "block_level": 1,
        "max_points": 30,
        "block_min_points": 15,
        "weight": 0.25,
        "observation_linked": False,
    },
    {
        "domain_code": "FAMILY_PARTNERSHIP",
        "block_level": 2,
        "max_points": 20,
        "block_min_points": 10,
        "weight": 0.20,
        "observation_linked": False,
    },
    {
        "domain_code": "ADMINISTRATION",
        "block_level": 2,
        "max_points": 20,
        "block_min_points": 6,
        "weight": 0.15,
        "observation_linked": False,
    },
    {
        "domain_code": "CHILD_ASSESSMENT",
        "block_level": 3,
        "max_points": 10,
        "block_min_points": 5,
        "weight": 0.10,
        "observation_linked": False,
    },
]

CLAIMED_C = {
    "LEARNING_ENVIRONMENT": 20,
    "STAFF_QUALIFICATIONS": 26,
    "FAMILY_PARTNERSHIP": 12,
    "ADMINISTRATION": 8,
    "CHILD_ASSESSMENT": 6,
}
VERIFIED_C = {
    "LEARNING_ENVIRONMENT": 24,
    "STAFF_QUALIFICATIONS": 30,
    "FAMILY_PARTNERSHIP": 12,
    "ADMINISTRATION": 8,
    "CHILD_ASSESSMENT": 6,
}


def _credentials_c():
    """The DIRECTOR's 1.00 fte lapses on 2026-08-20; the other 8.50 fte runs to 2028."""
    specs = [
        {
            "role_type": "DIRECTOR",
            "credential_level": 4,
            "fte": 1.00,
            "expires_on": "2026-08-20",
        }
    ]
    specs += credential_specs(4.50, "LEAD_TEACHER", 3, expires_on="2028-06-30")
    specs += credential_specs(4.00, "ASSISTANT", 1, expires_on="2028-06-30")
    return specs


def _spine_c():
    """Single-observer spine finalized on 2026-08-06 while compliance is still 95.00."""
    return build_rating_spine(
        stop_at="OBSERVATION_FINALIZED",
        domains=DOMAINS_C,
        provider_overrides={
            "legal_name": "Lapsing Director Preschool",
            "license_number": "LIC-2207-F",
            "county_code": "WHT",
            "region_code": "URBAN",
            "licensed_capacity": 70,
            "active_staff_fte": 10.00,
            "weekly_onsite_cap_hours": 18.0,
        },
        credentials=_credentials_c(),
        claimed=CLAIMED_C,
        verified=VERIFIED_C,
        raw_score=5.0,
        window_start="2026-08-06T09:00:00Z",
        window_end="2026-08-06T12:00:00Z",
        enrol_clock="2026-08-05T00:00:00Z",
        cycle_clock="2026-08-05T00:00:00Z",
    )


def test_award_recomputes_compliance_before_capping_staff_qualifications(api):
    """PRD §3.2: "The numerator is the sum of the `fte` values of the provider's staff
    credential records that satisfy all four of these conditions at once: the record belongs
    to that provider, its `employment_status` is `ACTIVE`, its `registry_status` is
    `VERIFIED`, its `expires_on` is on or after the logical clock date, and its
    `credential_level` is at least the minimum for its `role_type`."
    PRD §3.5: "All five domains must be present, and the provider's compliance percentage is
    always recomputed in the same request rather than read from a stale stored value."
    PRD §3.5: "For the `STAFF_QUALIFICATIONS` domain, the credited number is capped: the cap
    is the domain's `max_points` multiplied by a credential fraction and rounded half up to a
    whole integer, and the awarded points are the smaller of the credited number and that
    cap. The credential fraction is 1.00 when `credential_compliance_pct` is at least 95.00,
    0.80 when it is at least 85.00, 0.60 when it is at least 70.00, 0.40 when it is at least
    55.00, and 0.20 otherwise."

    Design: Difficulty/combinatorial_formula/mode_c_pinned_order_compliance_points_tier_then_tier_keyed_gate
    """
    ctx = _spine_c()
    finalized = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert finalized["observation_composite"] == pytest.approx(5.00, abs=0.005)
    assert finalized["domain_points"]["STAFF_QUALIFICATIONS"] == 30, (
        f"while the DIRECTOR credential is still unexpired compliance is 95.00, so the cap "
        f"is 30 and min(verified 30, cap 30) is 30, got "
        f"{finalized['domain_points']['STAFF_QUALIFICATIONS']}"
    )

    set_clock("2026-08-25T00:00:00Z")
    awarded = award_cycle(ctx["cycle"]["id"], "FINAL")

    provider = validate_success(api.get_provider(ctx["provider"]["id"], ADMIN))
    assert provider["credential_compliance_pct"] == pytest.approx(85.00, abs=0.005), (
        f"the DIRECTOR's 1.00 fte lapsed on 2026-08-20, leaving 8.50 over 10.00 == 85.00, "
        f"got {provider['credential_compliance_pct']}"
    )
    assert awarded["domain_points"]["STAFF_QUALIFICATIONS"] == 24, (
        f"the recomputed 85.00 gives credential fraction 0.80 and cap 24, so the award is "
        f"min(verified 30, cap 24) == 24, got "
        f"{awarded['domain_points']['STAFF_QUALIFICATIONS']}"
    )
    assert awarded["domain_points"]["LEARNING_ENVIRONMENT"] == 32
    assert awarded["weighted_total"] == pytest.approx(68.00, abs=0.005), (
        f"weighted_total must be 68.00; the stale cap of 30 would have produced 73.00, got "
        f"{awarded['weighted_total']}"
    )
    assert awarded["points_tier"] == 3, (
        f"68.00 is at least 55.00 and below 70.00, so points_tier is 3, got "
        f"{awarded['points_tier']}"
    )


def test_compliance_floor_is_gated_on_the_awarded_tier_the_capped_run_produced(api):
    """PRD §3.5: "Third, the compliance floor: the provider's `credential_compliance_pct`
    must reach the minimum for the tier the determination just produced — measured against
    `awarded_tier`, not against `points_tier` — where tier 1 requires 0.00, tier 2 requires
    60.00, tier 3 requires 80.00, tier 4 requires 90.00, and tier 5 requires 95.00; a
    shortfall is `ERR_CREDENTIAL_COMPLIANCE_BELOW_MINIMUM` with HTTP 422."
    PRD §3.5: "`validity_months` is 36 when `awarded_tier` is at least 4 and 24 otherwise."

    Design: Difficulty/combinatorial_formula/mode_c_pinned_order_compliance_points_tier_then_tier_keyed_gate
    """
    ctx = _spine_c()
    set_clock("2026-08-25T00:00:00Z")
    awarded = award_cycle(ctx["cycle"]["id"], "FINAL")

    assert awarded["status"] == "AWARDED", (
        f"compliance 85.00 clears the 80.00 floor of awarded_tier 3, so the award stands, "
        f"got status {awarded['status']}"
    )
    assert awarded["highest_block_cleared"] == 3
    assert awarded["awarded_tier"] == 3, (
        f"awarded_tier is min(points_tier 3, ceiling 5) == 3, got {awarded['awarded_tier']}"
    )
    assert awarded["validity_months"] == 24, (
        f"awarded_tier 3 is below 4, so validity_months is 24, got "
        f"{awarded['validity_months']}"
    )
    assert awarded["effective_date"] == "2026-09-01T00:00:00.000Z"
    assert awarded["expires_on"] == "2028-08-31T23:59:59.999Z"
