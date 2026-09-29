"""
Compensating actions that undo an accepted decision without breaking a conserved total.

Two different conserved quantities are put through the same shape of test. Money: the
allocations plus the unfunded gap always equal the approved remedy's funding need, even
though rescinding one grant lets a lower-priority programme grow by more than nothing and
less than the amount released. Weight: the four obligation buckets always partition the
protection's total weight, even though voiding a certification moves weight backwards
between them. In both cases a derived by-product — the local match, the compliance figure
— is deliberately not conserved.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    REVIEWER_ALPHA,
    REVIEWER_BETA,
    add_award,
    add_tax_credit_award,
    assert_fields,
    assert_funding_conservation,
    assert_number,
    assert_weight_conservation,
    certify_obligation,
    decide_award,
    funding_decision_payload,
    impose_obligation,
    run_sweep,
    set_clock,
    stage_approved,
    stage_assessed,
    stage_bind,
    stage_quote,
    stage_two_awards_granted,
    void_certification,
)

# ─── funding_rescind_conserves_total_funding_need_cents ─────────────────────────

FUNDING_NEED_CENTS = 118043177

GRANT_ALLOCATION_CENTS = 23842210
TAX_CREDIT_ALLOCATION_CENTS = 22636409
REVITALIZATION_ALLOCATION_CENTS = 55361124
GROUNDWATER_CLAMPED_CENTS = 16203434
GROUNDWATER_RELEASED_CENTS = 18610003

MATCH_BEFORE_CENTS = 11114726
MATCH_AFTER_CENTS = 5698942
GAP_AFTER_CENTS = 52954555


def _four_awarded_programmes(api):
    """
    An approved remedy with a bound cap and four funding programmes all awarded.

    The third programme takes the whole excavation and disposal base, which starves the
    fourth: its allocation is clamped by the running remainder rather than by its own
    share cap, and that is the figure the rescission has to release.
    """
    world = stage_approved(api)
    stage_quote(world)
    stage_bind(world)
    stage_two_awards_granted(world)

    revitalization = add_award(
        world,
        program_code="OH-CLEAN-REVITALIZATION-GRANT",
        program_priority=3,
        max_award_cents=80000000,
        max_share_pct=1.00,
        match_requirement_pct=0.10,
        eligible_cost_categories=["EXCAVATION_DISPOSAL"],
    )
    groundwater = add_tax_credit_award(
        world,
        program_code="OH-GROUNDWATER-CREDIT",
        program_priority=4,
        max_award_cents=80000000,
        max_share_pct=1.00,
        match_requirement_pct=0.05,
        eligible_cost_categories=["GW_TREATMENT"],
    )
    revitalization = decide_award(world, revitalization, "AWARD")
    groundwater = decide_award(world, groundwater, "AWARD")
    return world, revitalization, groundwater


def _rescind(world, award):
    """Withdraw one already-awarded programme."""
    return world.api.decide_funding_award(
        award["id"],
        funding_decision_payload(
            decision="RESCIND", decision_note="Programme appropriation withdrawn."
        ),
        REVIEWER_ALPHA,
    )


def _allocation_pairs(assembly):
    """The assembly's allocations as ordered (award, amount) pairs."""
    return [
        (entry["funding_award_id"], entry["allocated_cents"])
        for entry in assembly["allocations"]
    ]


def test_the_four_programmes_fill_the_whole_need_before_the_rescission(api):
    """
    The waterfall is visited in priority order and the fourth gets only the remainder.

    "The application's `allocated_cents` is then the smallest of three quantities: its own
    `max_award_cents` ceiling, that share cap, and the running remainder."

    Design: Difficulty/compensating_invariant/funding_rescind_conserves_total_funding_need_cents
    """
    world, revitalization, groundwater = _four_awarded_programmes(api)

    before = world.read_funding_assembly()
    assert_fields(
        before,
        total_funding_need_cents=FUNDING_NEED_CENTS,
        unfunded_gap_cents=0,
        local_match_required_cents=MATCH_BEFORE_CENTS,
    )
    assert _allocation_pairs(before) == [
        (world.awards[0]["id"], GRANT_ALLOCATION_CENTS),
        (world.awards[1]["id"], TAX_CREDIT_ALLOCATION_CENTS),
        (revitalization["id"], REVITALIZATION_ALLOCATION_CENTS),
        (groundwater["id"], GROUNDWATER_CLAMPED_CENTS),
    ]
    assert_funding_conservation(before)


def test_the_rescission_zeroes_its_own_award_and_releases_the_clamped_one(api):
    """
    The compensating action re-runs the waterfall instead of handing the money over.

    "A `RESCIND` is a compensating action available only from `AWARDED`: it sets this
    award's `allocated_cents` to zero, moves it to the terminal `RESCINDED`, and re-derives
    the remaining awarded applications so the conserved total still holds."

    Design: Difficulty/compensating_invariant/funding_rescind_conserves_total_funding_need_cents
    """
    world, revitalization, groundwater = _four_awarded_programmes(api)
    grant_version = world.read_award(world.awards[0])["version"]
    credit_version = world.read_award(world.awards[1])["version"]
    groundwater_version = world.read_award(groundwater)["version"]

    rescinded = get_success_data(_rescind(world, revitalization))
    assert_fields(rescinded, status="RESCINDED", allocated_cents=0)

    assert_fields(
        world.read_award(groundwater),
        status="AWARDED",
        allocated_cents=GROUNDWATER_RELEASED_CENTS,
        version=groundwater_version + 1,
    )
    assert_fields(
        world.read_award(world.awards[0]),
        status="AWARDED",
        allocated_cents=GRANT_ALLOCATION_CENTS,
        version=grant_version,
    )
    assert_fields(
        world.read_award(world.awards[1]),
        status="AWARDED",
        allocated_cents=TAX_CREDIT_ALLOCATION_CENTS,
        version=credit_version,
    )


def test_the_need_is_conserved_across_the_rescission_and_the_match_is_not(api):
    """
    The gap absorbs exactly what the re-derivation could not place.

    "Second, in the funding assembly, the sum of every awarded application's
    `allocated_cents` plus the residual `unfunded_gap_cents` always equals the approved
    plan's `total_funding_need_cents`."

    Design: Difficulty/compensating_invariant/funding_rescind_conserves_total_funding_need_cents
    """
    world, revitalization, groundwater = _four_awarded_programmes(api)
    _rescind(world, revitalization)

    after = world.read_funding_assembly()
    assert_fields(
        after,
        total_funding_need_cents=FUNDING_NEED_CENTS,
        unfunded_gap_cents=GAP_AFTER_CENTS,
        local_match_required_cents=MATCH_AFTER_CENTS,
    )
    assert _allocation_pairs(after) == [
        (world.awards[0]["id"], GRANT_ALLOCATION_CENTS),
        (world.awards[1]["id"], TAX_CREDIT_ALLOCATION_CENTS),
        (groundwater["id"], GROUNDWATER_RELEASED_CENTS),
    ]
    assert_funding_conservation(after)


# ─── void_certification_conserves_obligation_weight_total ────────────────────────

WEIGHTED_DUTIES = (
    ("REASONABLE_STEPS", "Maintain fencing, signage and stormwater controls.", "2027-06-30"),
    (
        "LAND_USE_RESTRICTION_COMPLIANCE",
        "Comply with the recorded environmental covenant.",
        "2027-06-30",
    ),
    (
        "INSTITUTIONAL_CONTROL_MAINTENANCE",
        "Inspect and maintain the sub-slab depressurisation system.",
        "2027-02-05",
    ),
    ("ACCESS_AND_COOPERATION", "Provide agency access on 48 hours notice.", "2027-02-05"),
    ("NOTIFICATION", "Report newly discovered releases within 10 days.", "2027-02-05"),
)

VOIDED_DUTY = "INSTITUTIONAL_CONTROL_MAINTENANCE"
VOID_REASON = "Inspection log did not support the filed certification."

TOTAL_WEIGHT = 20
CERTIFIED_PCT = "0.8500"
RESTORED_PCT = "0.7500"


def _a_certified_duty_inside_the_grace_window(api):
    """
    Five duties, three of them warned by the sweep, and the heaviest of those certified.

    The clock stands 26 days short of the three near deadlines, so the sweep puts them in
    the grace window and the certification of the weight-4 duty is exactly what lifts the
    protection back to the inclusive 0.85 edge.
    """
    world = stage_assessed(api)
    for category, description, due_date in WEIGHTED_DUTIES:
        world.obligations[category] = impose_obligation(
            world,
            obligation_category=category,
            description=description,
            due_date=due_date,
            recurrence_days=90,
        )
    set_clock(world.api, "2027-01-10T00:00:00Z")
    run_sweep(world, "2027-01-10")
    certify_obligation(world, world.obligations[VOIDED_DUTY])
    return world, world.obligations[VOIDED_DUTY]


def test_the_certification_moved_weight_from_the_warned_bucket_to_the_satisfied_one(api):
    """
    Four units of weight change bucket and the total is untouched by the move.

    "`current_weight`, `satisfied_weight`, `at_risk_weight` and `lapsed_weight` are the
    sums of the weights of the duties whose `status` is respectively `CURRENT`,
    `SATISFIED`, `AT_RISK` and `LAPSED`, and by construction those four always add up to
    `obligations_total_weight`."

    Design: Difficulty/compensating_invariant/void_certification_conserves_obligation_weight_total
    """
    world, duty = _a_certified_duty_inside_the_grace_window(api)

    assert_fields(
        world.read_obligation(duty),
        status="SATISFIED",
        prior_due_date="2027-02-05",
        due_date="2027-05-06",
        certification_count=1,
    )
    protection = world.read_protection()
    assert_fields(
        protection,
        obligations_total_weight=TOTAL_WEIGHT,
        current_weight=10,
        satisfied_weight=4,
        at_risk_weight=6,
        lapsed_weight=0,
        obligation_state="CURRENT",
        bfpp_status="ESTABLISHED",
    )
    assert_number(protection["compliance_pct"], CERTIFIED_PCT, "compliance_pct")
    assert_weight_conservation(protection)


def test_the_void_restores_the_closed_period_verbatim(api):
    """
    Every field the certification wrote is put back, and the landing state follows the clock.

    "The restoration is exact: `due_date` is restored verbatim from `prior_due_date`,
    `certified_at` is cleared, `prior_due_date` is set back to null, `certification_count`
    decrements by 1, and the protection's weight buckets and `compliance_pct` are
    recomputed to exactly the values they held before the certification was accepted."

    Design: Difficulty/compensating_invariant/void_certification_conserves_obligation_weight_total
    """
    world, duty = _a_certified_duty_inside_the_grace_window(api)
    certified = world.read_obligation(duty)

    voided = void_certification(world, duty, headers=REVIEWER_BETA, void_reason=VOID_REASON)
    assert_fields(
        voided,
        status="AT_RISK",
        due_date="2027-02-05",
        prior_due_date=None,
        certified_at=None,
        certification_count=0,
        version=certified["version"] + 1,
    )


def test_the_weight_total_holds_while_the_compliance_figure_falls_back(api):
    """
    The conserved quantity is the total; the derived percentage is free to move.

    "First, on a liability protection, the sum of `current_weight`, `satisfied_weight`,
    `at_risk_weight` and `lapsed_weight` always equals `obligations_total_weight`."

    Design: Difficulty/compensating_invariant/void_certification_conserves_obligation_weight_total
    """
    world, duty = _a_certified_duty_inside_the_grace_window(api)
    before = world.read_protection()

    void_certification(world, duty, headers=REVIEWER_BETA, void_reason=VOID_REASON)

    after = world.read_protection()
    assert_fields(
        after,
        obligations_total_weight=TOTAL_WEIGHT,
        current_weight=10,
        satisfied_weight=0,
        at_risk_weight=10,
        lapsed_weight=0,
        obligation_state="AT_RISK",
        bfpp_status="ESTABLISHED",
        version=before["version"] + 1,
    )
    assert_number(after["compliance_pct"], RESTORED_PCT, "compliance_pct")
    assert_weight_conservation(after)

    for category, _description, _due in WEIGHTED_DUTIES[:2]:
        assert_fields(world.read_obligation(world.obligations[category]), status="CURRENT")
    for category, _description, _due in WEIGHTED_DUTIES[2:]:
        assert_fields(world.read_obligation(world.obligations[category]), status="AT_RISK")
