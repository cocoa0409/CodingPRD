"""
The sanction schedule and the fork it leads to.

The first half pins the one-pass escalation arithmetic: points always come from the
base tier while the effective tier climbs, and the penalty amount is derived from the
escalated tier and then capped. The second half pins the fork itself — a served case
either becomes a civil money penalty, leaving the store trading, or a
disqualification, terminating it and cascading — and shows the two branches
converging on ``CLOSED`` with the case points credited exactly once.
"""

from test_helpers import (
    INVESTIGATOR_HEADERS,
    INVESTIGATOR_ONE,
    SUPERVISOR_HEADERS,
    assert_field_values,
    assert_monitoring_visit,
    assert_peer_group,
    assert_sanction_case,
    assert_sanction_schedule,
    assert_vendor,
    factories,
    fixtures,
    get_success_data,
    make_vendor_operator_headers,
    validate_success,
)


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------


def _authorized_small_grocery_vendor(api):
    """
    One AUTHORIZED small grocery whose average monthly redemption is 120,000 cents.

    The vendor has no paid claim history, so authorization sets
    ``avg_monthly_redemption_cents`` from the self-reported figure; that number is the
    base of every civil money penalty computed below.
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    bundle = fixtures.bootstrap_catalogue(
        api,
        peer_group_overrides={
            "code": "PG-SMALL-C",
            "store_type": "SMALL_GROCERY",
            "min_monthly_redemption_cents": 0,
            "max_monthly_redemption_cents": 999_999,
            "mar_method": "LOWEST_HALF_AVG",
            "competitive_allowance_pct": 0.05,
            "min_submissions_for_ceiling": 3,
            "min_stock_multiplier": 1.0,
        },
    )
    accepted = fixtures.vendor_with_accepted_price(
        api,
        bundle["milk_item"]["id"],
        bundle["cycle"]["id"],
        store_name="Hotel Corner Store",
        store_type="SMALL_GROCERY",
        reported_monthly_redemption_cents=120_000,
    )
    bundle["vendor"] = fixtures.authorize_vendor(api, accepted["vendor"]["id"])
    bundle["submission"] = accepted["submission"]
    return bundle


def _open_case(api, vendor_id, violation_code):
    """Open a sanction case against the vendor's current version."""
    vendor = fixtures.get_vendor(api, vendor_id)
    return validate_success(
        api.create_sanction_case(
            factories.sanction_case_payload(
                vendor_id, vendor["version"], violation_code=violation_code
            ),
            INVESTIGATOR_HEADERS,
        ),
        201,
    )


def _elected_and_closed_first_case(api, vendor_id, cmp_payment_cents):
    """Take one CLASS_C case all the way through the penalty branch to CLOSED."""
    case = fixtures.open_sanction_case(
        api,
        vendor_id,
        fixtures.get_vendor(api, vendor_id)["version"],
        violation_code="CLASS_C",
    )
    fixtures.serve_notice(api, case["id"])
    fixtures.elect_cmp(api, case["id"], vendor_id)
    return fixtures.close_case(api, case["id"], cmp_payment_cents=cmp_payment_cents)


def _two_served_cases_across_the_fork(api):
    """
    Two AUTHORIZED vendors, each with a scheduled visit and a served sanction case.

    The cycle is closed and published so its submissions are outside the void
    cascade. Alpha Market carries a CLASS_C notice and Bravo Market a CLASS_B one,
    both served at 2026-08-01, so both election deadlines fall on 2026-08-16.
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    bundle = fixtures.two_authorized_vendors_setup(api)
    fixtures.publish_canonical_ceilings(api, bundle)

    bundle["visit_one"] = fixtures.schedule_visit(
        api, bundle["vendor"]["id"], "2026-08-20T00:00:00Z"
    )
    bundle["visit_two"] = fixtures.schedule_visit(
        api, bundle["vendor_two"]["id"], "2026-08-20T00:00:00Z"
    )

    vendor_one = fixtures.get_vendor(api, bundle["vendor"]["id"])
    case_a = fixtures.open_sanction_case(
        api, vendor_one["id"], vendor_one["version"], violation_code="CLASS_C"
    )
    bundle["case_a"] = fixtures.serve_notice(api, case_a["id"])

    vendor_two = fixtures.get_vendor(api, bundle["vendor_two"]["id"])
    case_b = fixtures.open_sanction_case(
        api, vendor_two["id"], vendor_two["version"], violation_code="CLASS_B"
    )
    bundle["case_b"] = fixtures.serve_notice(api, case_b["id"])
    return bundle


# ---------------------------------------------------------------------------
# The one-pass sanction schedule and its escalation
# ---------------------------------------------------------------------------


def test_first_class_c_case_is_tiered_from_its_own_base_tier(api):
    """
    With no prior history the schedule sits flat at the base tier of the violation class.

    "The `base_tier` comes from the violation class: `CLASS_A` is tier 4, `CLASS_B` is
    tier 3, `CLASS_C` is tier 2, and `CLASS_D` is tier 1." "The `case_points` come from
    the **base** tier and never from the effective one: tier 1 carries 1 point, tier 2
    carries 2, tier 3 carries 4, and tier 4 carries 8." "The
    `cumulative_points_at_open` snapshot is the sum of those same base-tier point
    values over the vendor's **other** sanction cases whose `status` is `CMP_ELECTED`,
    `DISQUALIFICATION_IMPOSED`, or `CLOSED`." "The escalation step is the number of
    escalation thresholds — there are two, at 4 points and at 8 points — that the
    snapshot plus this case's own `case_points` reaches or exceeds." "The
    `effective_tier` is the base tier plus that escalation step, capped at 4."
    "`cmp_permitted` is true for every violation class except `CLASS_A`, which may
    never be settled by money." "The new case
    begins in `status` `OPENED` with `resolution` `NONE`, `cmp_paid_cents` 0, and
    `notice_served_at`, `response_due_at`, and `dismissal_reason` null." "If no such
    claim exists, `avg_monthly_redemption_cents` falls back to the vendor's
    self-reported `reported_monthly_redemption_cents`."

    Design: Difficulty/combinatorial_formula/cmp_effective_tier_escalation_order_pinned
    """
    bundle = _authorized_small_grocery_vendor(api)
    assert_vendor(
        bundle["vendor"],
        authorization_status="AUTHORIZED",
        # no paid claim exists, so the self-reported volume stands in
        avg_monthly_redemption_cents=120_000,
        sanction_points=0,
    )

    case = _open_case(api, bundle["vendor"]["id"], "CLASS_C")

    assert_sanction_schedule(
        case,
        base_tier=2,
        case_points=2,
        cumulative_points_at_open=0,
        # 0 + 2 clears neither the 4-point nor the 8-point threshold
        effective_tier=2,
        disqualification_months=6,
        cmp_permitted=True,
        # tier 2 x 3 months on 120,000 -> round_half_up(120000 x 0.10 x 3) = 36,000
        cmp_amount_cents=36_000,
    )
    assert_sanction_case(
        case,
        status="OPENED",
        resolution="NONE",
        cmp_paid_cents=0,
        notice_served_at=None,
        response_due_at=None,
        dismissal_reason=None,
        opened_by_user_id=INVESTIGATOR_ONE,
        violation_code="CLASS_C",
    )


def test_electing_the_penalty_credits_no_points_and_keeps_the_vendor_trading(api):
    """
    The penalty branch defers its points and leaves the authorization untouched.

    "The `VendorOperator` itself elects to pay, moving the case
    `NOTICE_SERVED → CMP_ELECTED` and setting `resolution` to `CMP`." "Electing the
    penalty leaves the vendor's `authorization_status` untouched and its peer group
    `member_count` unchanged: the store keeps operating and owes `cmp_amount_cents`."
    "No sanction points are added at election."

    Design: Difficulty/combinatorial_formula/cmp_effective_tier_escalation_order_pinned
    """
    bundle = _authorized_small_grocery_vendor(api)
    vendor_id = bundle["vendor"]["id"]
    case = fixtures.open_sanction_case(
        api,
        vendor_id,
        fixtures.get_vendor(api, vendor_id)["version"],
        violation_code="CLASS_C",
    )
    fixtures.serve_notice(api, case["id"])

    elected = validate_success(
        api.elect_cmp(case["id"], None, make_vendor_operator_headers(vendor_id))
    )

    assert_sanction_case(
        elected,
        status="CMP_ELECTED",
        resolution="CMP",
        cmp_amount_cents=36_000,
        # the money is owed, not yet paid
        cmp_paid_cents=0,
    )
    assert_vendor(
        fixtures.get_vendor(api, vendor_id),
        authorization_status="AUTHORIZED",
        sanction_points=0,
        disqualified_until=None,
    )


def test_closing_the_penalty_branch_records_the_payment_and_credits_the_points(api):
    """
    Closure is where the penalty branch finally moves money and points.

    "Closing from `CMP_ELECTED` carries a `cmp_payment_cents` in the body, and the case
    may only close when `cmp_paid_cents` plus that payment reaches or exceeds
    `cmp_amount_cents`; a short payment is refused with `ERR_CMP_UNDERPAID`, while an
    exact or over-payment closes the case." "On success `cmp_paid_cents` is increased by
    `cmp_payment_cents` and the vendor's `sanction_points` rises by the case's
    `case_points` — the penalty branch adds its points only at closure." "Either way
    the case's `status` becomes `CLOSED`."

    Design: Difficulty/combinatorial_formula/cmp_effective_tier_escalation_order_pinned
    """
    bundle = _authorized_small_grocery_vendor(api)
    vendor_id = bundle["vendor"]["id"]
    case = fixtures.open_sanction_case(
        api,
        vendor_id,
        fixtures.get_vendor(api, vendor_id)["version"],
        violation_code="CLASS_C",
    )
    fixtures.serve_notice(api, case["id"])
    fixtures.elect_cmp(api, case["id"], vendor_id)

    closed = validate_success(
        api.close_sanction_case(
            case["id"], factories.cmp_close_payload(36_000), SUPERVISOR_HEADERS
        )
    )

    assert_sanction_case(
        closed, status="CLOSED", resolution="CMP", cmp_paid_cents=36_000
    )
    assert_vendor(
        fixtures.get_vendor(api, vendor_id),
        # the tier-2 base tier carries 2 points, credited once, at closure
        sanction_points=2,
        authorization_status="AUTHORIZED",
    )


def test_second_case_escalates_the_effective_tier_without_escalating_its_points(api):
    """
    The prior closed case raises the effective tier and the penalty, but not the points.

    "The `case_points` come from the **base** tier and never from the effective one:
    tier 1 carries 1 point, tier 2 carries 2, tier 3 carries 4, and tier 4 carries 8."
    "The `cumulative_points_at_open` snapshot is the sum of those same base-tier point
    values over the vendor's **other** sanction cases whose `status` is `CMP_ELECTED`,
    `DISQUALIFICATION_IMPOSED`, or `CLOSED`." "The `effective_tier` is the base tier
    plus that escalation step, capped at 4." "There is no second iteration:
    `case_points` is never recomputed from the effective tier."
    "`disqualification_months` is 0 at tier 1, 6 at tier 2, 12 at tier 3, and 36 at
    tier 4 — a tier-1 case therefore carries no disqualification at all." "The
    `cmp_amount_cents` is the vendor's `avg_monthly_redemption_cents` multiplied by the
    tier's monthly multiplier — 0.05 at tier 1, 0.10 at tier 2, 0.25 at tier 3, and
    0.50 at tier 4 — multiplied again by the tier's month count — 1 month at tier 1, 3
    at tier 2, 6 at tier 3, and 12 at tier 4 — then rounded half up to a whole cent, and
    finally capped: the penalty is the lesser of that rounded figure and 5,625,000
    cents, which is the statutory ceiling of fifty-six thousand two hundred fifty
    dollars."

    Design: Difficulty/combinatorial_formula/cmp_effective_tier_escalation_order_pinned
    """
    bundle = _authorized_small_grocery_vendor(api)
    vendor_id = bundle["vendor"]["id"]
    _elected_and_closed_first_case(api, vendor_id, 36_000)

    case = _open_case(api, vendor_id, "CLASS_C")

    assert_sanction_schedule(
        case,
        base_tier=2,
        # still the base tier's 2 points, not the escalated tier's 4
        case_points=2,
        cumulative_points_at_open=2,
        # 2 + 2 = 4 reaches the first threshold only, so 2 + 1
        effective_tier=3,
        disqualification_months=12,
        cmp_permitted=True,
        # tier 3 x 6 months on 120,000 -> round_half_up(120000 x 0.25 x 6) = 180,000
        cmp_amount_cents=180_000,
    )
    assert_vendor(
        fixtures.get_vendor(api, vendor_id),
        # opening a case credits nothing; the snapshot is read, not written
        sanction_points=2,
    )


# ---------------------------------------------------------------------------
# The fork: civil money penalty against disqualification
# ---------------------------------------------------------------------------


def test_penalty_election_leaves_the_vendor_and_its_membership_intact(api):
    """
    Branch A costs money and nothing else.

    "The `VendorOperator` itself elects to pay, moving the case
    `NOTICE_SERVED → CMP_ELECTED` and setting `resolution` to `CMP`." "Electing the
    penalty leaves the vendor's `authorization_status` untouched and its peer group
    `member_count` unchanged: the store keeps operating and owes `cmp_amount_cents`."
    "No sanction points are added at election."

    Design: Difficulty/non_linear_state_machine/sanction_case_forks_to_cmp_or_disqualification_with_divergent_effects
    """
    bundle = _two_served_cases_across_the_fork(api)
    vendor_id = bundle["vendor"]["id"]

    elected = validate_success(
        api.elect_cmp(
            bundle["case_a"]["id"], None, make_vendor_operator_headers(vendor_id)
        )
    )

    assert_sanction_case(elected, status="CMP_ELECTED", resolution="CMP", cmp_paid_cents=0)
    assert_sanction_schedule(
        elected,
        base_tier=2,
        case_points=2,
        cumulative_points_at_open=0,
        effective_tier=2,
        disqualification_months=6,
        cmp_permitted=True,
        # tier 2 x 3 months on 6,000,000 -> round_half_up(6000000 x 0.10 x 3) = 1,800,000
        cmp_amount_cents=1_800_000,
    )
    assert_vendor(
        fixtures.get_vendor(api, vendor_id),
        authorization_status="AUTHORIZED",
        disqualified_until=None,
        sanction_points=0,
    )
    assert_peer_group(
        fixtures.get_peer_group(api, bundle["peer_group"]["id"]), member_count=2
    )


def test_disqualification_terminates_the_vendor_and_cancels_only_its_own_visits(api):
    """
    Branch B ends the authorization, dates the bar, credits the points, and cascades per vendor.

    "A `VendorUnitSupervisor` or a `ComplianceInvestigator` imposes disqualification,
    moving the case `NOTICE_SERVED → DISQUALIFICATION_IMPOSED` and setting `resolution`
    to `DISQUALIFICATION`." "The vendor's own status may be `AUTHORIZED`,
    `REAUTH_PENDING`, or `SUSPENDED` at the time, and from any of those three it moves
    to `DISQUALIFIED` with the identical cascade" "`DISQUALIFIED` is terminal for the
    vendor." "`disqualified_until` is set to the logical clock plus
    `disqualification_months` calendar months." "`sanction_points` rises by the case's
    `case_points`." "Every MonitoringVisit of the vendor still in `SCHEDULED` moves to
    `CANCELLED` with `cancelled_reason` `VENDOR_DISQUALIFIED`." "Note that this
    suspension keys off `base_tier`, not `effective_tier`: a tier-3 violation escalated
    to effective tier 4 does not suspend on notice."

    Design: Difficulty/non_linear_state_machine/sanction_case_forks_to_cmp_or_disqualification_with_divergent_effects
    """
    bundle = _two_served_cases_across_the_fork(api)
    # a CLASS_B base tier of 3 does not suspend on notice, so the vendor is still authorized
    assert_vendor(
        fixtures.get_vendor(api, bundle["vendor_two"]["id"]),
        authorization_status="AUTHORIZED",
    )
    # one day past the 2026-08-16 election deadline
    fixtures.set_clock(api, "2026-08-17T00:00:00Z")

    imposed = validate_success(
        api.impose_disqualification(bundle["case_b"]["id"], None, SUPERVISOR_HEADERS)
    )

    assert_sanction_case(
        imposed, status="DISQUALIFICATION_IMPOSED", resolution="DISQUALIFICATION"
    )
    assert_sanction_schedule(
        imposed,
        base_tier=3,
        case_points=4,
        cumulative_points_at_open=0,
        # 0 + 4 reaches the first threshold, so 3 + 1
        effective_tier=4,
        disqualification_months=36,
        cmp_permitted=True,
        # tier 4 x 12 months on 7,000,000 -> round_half_up(7000000 x 0.50 x 12)
        # = 42,000,000, clamped to the statutory ceiling of 5,625,000
        cmp_amount_cents=5_625_000,
    )
    assert_vendor(
        fixtures.get_vendor(api, bundle["vendor_two"]["id"]),
        authorization_status="DISQUALIFIED",
        # 2026-08-17 plus 36 calendar months
        disqualified_until="2029-08-17T00:00:00.000Z",
        sanction_points=4,
    )

    assert_monitoring_visit(
        fixtures.get_visit(api, bundle["visit_two"]["id"]),
        status="CANCELLED",
        cancelled_reason="VENDOR_DISQUALIFIED",
    )
    assert_monitoring_visit(
        fixtures.get_visit(api, bundle["visit_one"]["id"]),
        status="SCHEDULED",
        cancelled_reason=None,
    )


def test_disqualification_spares_submissions_belonging_to_a_published_cycle(api):
    """
    The void cascade reaches only submissions whose price cycle is still open or closed.

    "Every PriceSubmission of the vendor whose `status` is `SUBMITTED` or `ACCEPTED`,
    and whose price cycle is `OPEN` or `CLOSED`, moves to `VOIDED` with `voided_reason`
    `VENDOR_DISQUALIFIED`." "Publishing moves a cycle `CLOSED → PUBLISHED` — again
    `ERR_INVALID_CYCLE_STATE` for any other status — stamps `published_at`, and performs
    three passes." "Comparing the two branches: branch A leaves the vendor operating,
    its peer group membership intact, its visits booked, and its submissions live, and
    adds no points until the case closes; branch B disqualifies the vendor, decrements
    the peer group, cancels the visits, voids the submissions, and adds the points
    immediately."

    Design: Difficulty/non_linear_state_machine/sanction_case_forks_to_cmp_or_disqualification_with_divergent_effects
    """
    bundle = _two_served_cases_across_the_fork(api)
    assert_field_values(
        fixtures.get_price_cycle(api, bundle["cycle"]["id"]), status="PUBLISHED"
    )
    fixtures.set_clock(api, "2026-08-17T00:00:00Z")

    validate_success(
        api.impose_disqualification(bundle["case_b"]["id"], None, SUPERVISOR_HEADERS)
    )

    assert_field_values(
        fixtures.get_price_submission(api, bundle["submission_two"]["id"]),
        status="ACCEPTED",
        voided_reason=None,
    )
    assert_field_values(
        fixtures.get_price_submission(api, bundle["submission"]["id"]),
        status="ACCEPTED",
        voided_reason=None,
    )


def test_both_fork_branches_converge_on_closed_with_points_credited_once(api):
    """
    Closure joins the two branches, one carrying a payment and one carrying none.

    "Either way the case's `status` becomes `CLOSED`." "On success `cmp_paid_cents` is
    increased by `cmp_payment_cents` and the vendor's `sanction_points` rises by the
    case's `case_points` — the penalty branch adds its points only at closure."
    "Closing from `DISQUALIFICATION_IMPOSED` needs no payment and moves no money; the
    vendor's `sanction_points` were already incremented when the disqualification was
    imposed and are emphatically not incremented a second time." "The vendor's peer
    group has its `member_count` decremented by one and its `version` incremented by
    one."

    Design: Difficulty/non_linear_state_machine/sanction_case_forks_to_cmp_or_disqualification_with_divergent_effects
    """
    bundle = _two_served_cases_across_the_fork(api)
    vendor_one_id = bundle["vendor"]["id"]
    vendor_two_id = bundle["vendor_two"]["id"]

    fixtures.elect_cmp(api, bundle["case_a"]["id"], vendor_one_id)
    fixtures.set_clock(api, "2026-08-17T00:00:00Z")
    get_success_data(
        api.impose_disqualification(bundle["case_b"]["id"], None, SUPERVISOR_HEADERS)
    )

    closed_penalty = validate_success(
        api.close_sanction_case(
            bundle["case_a"]["id"],
            factories.cmp_close_payload(1_800_000),
            SUPERVISOR_HEADERS,
        )
    )
    closed_disqualification = validate_success(
        api.close_sanction_case(bundle["case_b"]["id"], None, SUPERVISOR_HEADERS)
    )

    assert_sanction_case(
        closed_penalty, status="CLOSED", resolution="CMP", cmp_paid_cents=1_800_000
    )
    assert_sanction_case(
        closed_disqualification,
        status="CLOSED",
        resolution="DISQUALIFICATION",
        cmp_paid_cents=0,
    )
    assert_vendor(
        fixtures.get_vendor(api, vendor_one_id),
        authorization_status="AUTHORIZED",
        # the tier-2 base tier's 2 points, credited at closure
        sanction_points=2,
    )
    assert_vendor(
        fixtures.get_vendor(api, vendor_two_id),
        authorization_status="DISQUALIFIED",
        # the tier-3 base tier's 4 points, credited at imposition and not again
        sanction_points=4,
    )
    assert_peer_group(
        fixtures.get_peer_group(api, bundle["peer_group"]["id"]), member_count=1
    )
