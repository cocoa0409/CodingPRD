"""Pinned arithmetic: the deadline chain, the rounding scales, the two metric
scopes, the priority ordering and the payment waterfall."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    EPOCH_CLOCK_UTC,
    ERR_EXTENSION_LIMIT_REACHED,
    ERR_PAYMENT_EXCEEDS_OUTSTANDING,
    PASS_CLEARANCES,
    add_zone,
    add_zones,
    advance_cycle,
    assert_2dp,
    assert_allocation,
    assert_cents,
    assert_cost_recovery,
    assert_end_of_day,
    assert_instant,
    assert_metrics,
    assert_notice_schedule,
    assert_posture,
    assert_risk,
    assert_zone_grade,
    community_metrics,
    complete_inspection,
    create_community,
    create_inspector,
    create_parcel,
    cycle_metrics,
    extreme_parcel_payload,
    failed_world,
    get_community,
    get_notice,
    get_order,
    get_parcel,
    ids_of,
    invoiced_world,
    list_notices,
    moderate_parcel_payload,
    notice_for_parcel,
    noticed_world,
    open_cycle,
    parcel_patch,
    parcel_payload,
    payment_payload,
    priority_queue,
    reason_payload,
    record_payment,
    schedule_inspection,
    serve_notice,
    set_clock,
    survival_payload,
    very_high_parcel_payload,
)
from test_helpers.test_users import PROGRAM_ADMIN_HEADERS


class TestCertifiedMailDeadlineChain:
    """Four steps, one instant: constructive service is what moves the date."""

    def test_a_certified_mail_major_citation_falls_due_on_2026_09_26(self, client):
        """Issued 2026-08-22 by certified mail, a MAJOR citation on a HIGH parcel is
        delivered 2026-08-27, allowed 30 days and due at the end of 2026-09-26.

        PRD: "measured_veg_points is the sum of the three zones' points values, and
        the rounding discipline here is pinned: each zone's points is already rounded
        to two decimals, and it is those rounded values that are added; the sum is
        then rounded half up to two decimals and capped at 100.00."

        PRD: "Where the notice was handed over in person or sent by email,
        delivered_at_utc equals issued_at_utc - service is instantaneous. Where it
        went by certified mail, the district takes constructive service to occur five
        days after issuance, so delivered_at_utc is issued_at_utc plus 5 days."

        PRD: "From there the severity of the finding sets the base allowance: a MINOR
        deficiency earns the owner 60 days, a MAJOR deficiency 30 days, and a
        CRITICAL deficiency only 14."

        PRD: "deadline_utc is then the calendar date reached by adding
        compliance_days days to delivered_at_utc, expressed at 23:59:59 UTC on that
        date - owners get the whole final day."

        PRD: "It opens in ISSUED with issued_at_utc stamped at the logical clock,
        extension_count at 0, and cleared_at_utc and void_reason both null."

        Design: Corner/calculations/certified_mail_major_notice_deadline_correct_result
        """
        world = noticed_world(
            client,
            scheduled_start_utc="2026-08-20T15:00:00Z",
            scheduled_end_utc="2026-08-20T17:00:00Z",
        )
        set_clock(client, "2026-08-22T00:00:00Z")
        zones = add_zones(
            client, world["inspection"]["id"], world["inspector"]["id"]
        )

        assert_zone_grade(zones["ZONE_0_EMBER"], 6.3, 1.3, 0.2063, "MINOR", 30.95)
        assert_zone_grade(zones["ZONE_1"], 37.5, 22.5, 0.6000, "MAJOR", 60.00)
        assert_zone_grade(zones["ZONE_2"], 125.0, 7.0, 0.0560, "MINOR", 3.36)

        completed = complete_inspection(
            client,
            world["inspection"]["id"],
            world["inspector"]["id"],
            result="FAIL",
            violation_notice_method="CERTIFIED_MAIL",
        )
        # 30.95 + 60.00 + 3.36, each per-zone value rounded before the sum.
        assert_2dp(completed["measured_veg_points"], 94.31)
        assert completed["max_deficiency_severity"] == "MAJOR"

        notice = notice_for_parcel(client, world["parcel"]["id"])
        assert notice["notice_method"] == "CERTIFIED_MAIL"
        assert_instant(notice["issued_at_utc"], "2026-08-22T00:00:00Z")
        assert_notice_schedule(
            notice,
            "MAJOR",
            "2026-08-27T00:00:00Z",
            30,
            "2026-09-26",
            status="ISSUED",
        )
        assert notice["extension_count"] == 0
        # Ignoring constructive service would have fallen due five days earlier.
        assert not str(notice["deadline_utc"]).startswith("2026-09-21")


class TestVeryHighCompression:
    """The worst hazard zone compresses the clock and inflates the score."""

    def test_a_critical_email_citation_on_a_very_high_parcel_grants_eleven_days(
        self, client
    ):
        """14 days times three quarters rounds up to 11, email delivers instantly,
        and the 1.30 multiplier carries the parcel from 72.15 to 80.72.

        PRD: "When the cited parcel's hazard_zone is VERY_HIGH, the base allowance is
        multiplied by three quarters and rounded up to a whole day, then floored at a
        statutory minimum of 7 days so that no owner is ever given less than a week -
        a CRITICAL finding on a VERY_HIGH parcel therefore yields 11 days (14
        multiplied by three quarters is 10.5, rounded up to 11), a MAJOR finding
        yields 23, and a MINOR finding yields 45."

        PRD: "From the weighted subtotal the system first subtracts the
        structure-hardening credit, and only then multiplies the difference by the
        hazard-zone multiplier - 1.00 for a MODERATE zone, 1.15 for HIGH, and 1.30
        for VERY_HIGH."

        PRD: "deficiency_severity then bands the ratio, with the upper edge of each
        band inclusive: a ratio of exactly 0.0000 is NONE, a ratio at or below 0.2500
        is MINOR, a ratio at or below 0.6000 is MAJOR, and anything larger is
        CRITICAL."

        PRD: "it replaces the self-reported vegetation subscore with the inspection's
        own measured_veg_points, and it computes a real hardening credit worth 4.00
        points for each structure-hardening element the inspector found compliant on
        that inspection, capped at 20.00 points however many elements were checked."

        Design: Corner/calculations/very_high_hazard_compression_constants_applied
        """
        world = noticed_world(
            client,
            parcel_payload=very_high_parcel_payload(),
            certification_level="WUI_SPECIALIST",
            scheduled_start_utc="2026-08-20T15:00:00Z",
            scheduled_end_utc="2026-08-20T17:00:00Z",
            notice_method="EMAIL",
        )
        # 55.50 weighted subtotal times the VERY_HIGH multiplier of 1.30.
        assert_risk(world["parcel"], 72.15, "HIGH", basis="INTAKE_PROVISIONAL")

        set_clock(client, "2026-08-22T00:00:00Z")
        inspection_id = world["inspection"]["id"]
        inspector_id = world["inspector"]["id"]
        add_zone(client, inspection_id, inspector_id, "ZONE_0_EMBER", 5.0)
        zone_one = add_zone(client, inspection_id, inspector_id, "ZONE_1", 14.0)
        add_zone(client, inspection_id, inspector_id, "ZONE_2", 118.0)

        # 23.5 / 37.5 is 0.626666..., just past the 0.6000 MAJOR edge.
        assert_zone_grade(zone_one, 37.5, 23.5, 0.6267, "CRITICAL", 62.67)

        completed = complete_inspection(
            client,
            inspection_id,
            inspector_id,
            result="FAIL",
            violation_notice_method="EMAIL",
        )
        assert_2dp(completed["measured_veg_points"], 96.98)
        assert completed["max_deficiency_severity"] == "CRITICAL"
        assert_2dp(completed["hardening_credit_points"], 0.00)

        notice = notice_for_parcel(client, world["parcel"]["id"])
        assert notice["notice_method"] == "EMAIL"
        assert_notice_schedule(
            notice,
            "CRITICAL",
            "2026-08-22T00:00:00Z",
            11,
            "2026-09-02",
            status="ISSUED",
        )
        assert notice["compliance_days"] != 10, "the compression rounds up, not down"
        assert notice["compliance_days"] != 7, "the seven-day floor does not bind here"

        # (18 + 0.30 * 96.98 + 11.25 + 3.75) * 1.30, nowhere near the clamp.
        assert_risk(
            get_parcel(client, world["parcel"]["id"]),
            80.72,
            "EXTREME",
            basis="POST_INSPECTION_VERIFIED",
        )


DAILY_WINDOWS = (
    ("2026-08-20T09:00:00Z", "2026-08-20T11:00:00Z"),
    ("2026-08-21T09:00:00Z", "2026-08-21T11:00:00Z"),
    ("2026-08-22T09:00:00Z", "2026-08-22T11:00:00Z"),
)


class TestMetricScopesDiverge:
    """One eligibility rule, two denominators, and only one of them is persisted."""

    def test_district_scope_and_community_scope_report_different_rates(self, client):
        """Three parcels give 33.33 percent at district scope and 50.00 percent at
        community scope, and the community row keeps the community figure.

        PRD: "compliant_parcel_count is the number of eligible parcels whose posture
        is COMPLIANT, eligible_parcel_count is the size of the eligible set, and
        compliance_rate_pct is one hundred times the compliant count divided by the
        eligible count, rounded half up to two decimals."

        PRD: "The district scope, served by the cycle metrics read, spans every
        parcel in the district including those whose community_id is null."

        PRD: "The community scope, served by the community metrics read and used at
        both the cycle-advance recomputation and the inspection-failure cascade,
        spans only the parcels whose community_id equals the target community; this
        is the value persisted to Community.compliance_rate_pct and the value
        compared against the 75.00 percent certification floor and the 60.00 percent
        lapse floor."

        PRD: "The community metrics read returns eligible_parcel_count,
        compliant_parcel_count, compliance_rate_pct and member_parcel_count, the last
        being the raw count of parcels carrying that community_id regardless of
        posture."

        PRD: "The district metrics read computes its numbers fresh at read time
        rather than serving stored values, and returns eligible_parcel_count,
        compliant_parcel_count, compliance_rate_pct, survived_compliant_pct,
        survived_noncompliant_pct, survival_delta_pp and the cycle's current epoch."

        Design: Corner/calculations/metrics_district_scope_diverges_from_community_scope
        """
        cycle = open_cycle(client)
        inspector = create_inspector(client)
        community = create_community(client)
        member_pass = create_parcel(
            client, parcel_payload(community_id=community["id"])
        )
        member_fail = create_parcel(
            client, parcel_payload(community_id=community["id"])
        )
        outsider = create_parcel(client)

        visits = {}
        for parcel, window in zip(
            (member_pass, outsider, member_fail), DAILY_WINDOWS
        ):
            inspection = schedule_inspection(
                client,
                parcel["id"],
                cycle["id"],
                inspector["id"],
                scheduled_start_utc=window[0],
                scheduled_end_utc=window[1],
            )
            visits[parcel["id"]] = serve_notice(client, inspection["id"])["id"]

        add_zones(
            client, visits[member_pass["id"]], inspector["id"], PASS_CLEARANCES
        )
        complete_inspection(
            client, visits[member_pass["id"]], inspector["id"], result="PASS"
        )
        for parcel in (outsider, member_fail):
            add_zones(client, visits[parcel["id"]], inspector["id"])
            complete_inspection(
                client, visits[parcel["id"]], inspector["id"], result="FAIL"
            )

        assert_posture(get_parcel(client, member_pass["id"]), "COMPLIANT")
        assert_posture(get_parcel(client, member_fail["id"]), "NON_COMPLIANT")
        assert_posture(get_parcel(client, outsider["id"]), "NON_COMPLIANT")

        # Community scope: only the two member parcels are in view.
        community_view = community_metrics(client, community["id"])
        assert_metrics(community_view, 2, 1, 50.00)
        assert community_view["member_parcel_count"] == 2

        # District scope: the community-less parcel joins the denominator.
        district = cycle_metrics(client, cycle["id"])
        assert_metrics(district, 3, 1, 33.33)
        assert district["survived_compliant_pct"] is None
        assert district["survived_noncompliant_pct"] is None
        assert district["survival_delta_pp"] is None
        assert district["epoch"] == 0, "metrics are computed on read, not at advance"

        # Only the community figure is written down.
        assert_2dp(get_community(client, community["id"])["compliance_rate_pct"], 50.00)


class TestZoneRoundingScales:
    """Two rounding depths in one row, both of them half-up."""

    def test_the_requirement_rounds_to_one_decimal_and_the_ratio_to_four(
        self, client
    ):
        """5 times 1.25 is 6.25 and must become 6.3; 1.4 divided by 6.3 is
        0.222222... and must become 0.2222.

        PRD: "That factor multiplies the zone's base requirement - 5 feet for the
        ember zone, 30 feet for zone one, and 100 feet for zone two - and the
        product, rounded half up to one decimal place, becomes
        required_clearance_ft."

        PRD: "deficit_ratio expresses that shortfall as a fraction of the requirement
        - the deficit divided by the required clearance, rounded half up to four
        decimal places."

        PRD: "The ratio is first scaled to a percentage by multiplying by 100 and
        weighted by the zone's importance - the ember zone carries a weight of 1.50
        because embers landing against the wall are what actually ignite houses, zone
        one carries 1.00, and zone two carries 0.60 - and that product is rounded
        half up to two decimals and capped at 100.00."

        PRD: "First it works out how much clearance the zone actually required,
        which depends on the parcel's slope: on gentle ground, where slope_pct is
        below 20, the slope factor is 1.00; on moderate ground, where slope_pct is at
        least 20 but below 40, the factor is 1.25; on steep ground, where slope_pct is
        40 or more, the factor is 1.50."

        Design: Corner/calculations/zone_clearance_and_ratio_precision_half_up
        """
        world = noticed_world(client, parcel_payload=moderate_parcel_payload())
        # slope_pct 20 sits on the 1.25 slope-factor edge, in the 1.00 hazard band.
        assert_risk(world["parcel"], 35.25, "MODERATE", basis="INTAKE_PROVISIONAL")

        inspection_id = world["inspection"]["id"]
        inspector_id = world["inspector"]["id"]
        ember = add_zone(client, inspection_id, inspector_id, "ZONE_0_EMBER", 4.9)
        assert_zone_grade(ember, 6.3, 1.4, 0.2222, "MINOR", 33.33)
        assert ember["required_clearance_ft"] != 6.2, "half-up, not truncation"
        assert ember["deficit_ratio"] != 0.2223

        one = add_zone(client, inspection_id, inspector_id, "ZONE_1", 40.0)
        two = add_zone(client, inspection_id, inspector_id, "ZONE_2", 130.0)
        assert_zone_grade(one, 37.5, 0.0, 0.0000, "NONE", 0.00)
        assert_zone_grade(two, 125.0, 0.0, 0.0000, "NONE", 0.00)

        completed = complete_inspection(
            client, inspection_id, inspector_id, result="FAIL"
        )
        assert_2dp(completed["measured_veg_points"], 33.33)
        # (12 + 0.30 * 33.33 + 11.25 + 0) * 1.00 is 33.249, half-up to 33.25.
        assert_risk(
            get_parcel(client, world["parcel"]["id"]),
            33.25,
            "LOW",
            basis="POST_INSPECTION_VERIFIED",
        )


class TestMetricEligibilityFilter:
    """Uninspected and exempt parcels leave the arithmetic entirely."""

    def test_pending_and_exempt_parcels_leave_both_halves_of_every_rate(self, client):
        """One compliant parcel among three gives 100.00 percent, not 33.33, and the
        survival correlation is filtered the same way.

        PRD: "A parcel is eligible when its compliance_status is COMPLIANT,
        NON_COMPLIANT or ABATEMENT_PENDING."

        PRD: "Parcels sitting in PENDING_INSPECTION or EXEMPT are excluded from both
        the numerator and the denominator - they are not counted as failures, they are
        simply not counted."

        PRD: "Setting exemption_flag to true has two immediate consequences beyond
        the flag itself: compliance_status becomes EXEMPT and
        inspection_priority_rank is cleared to null."

        PRD: "The correlation is computed over parcels that both carry a recorded
        structure_survival_outcome of SURVIVED or DESTROYED and are eligible by the
        posture rule above."

        PRD: "survival_delta_pp is the compliant survival percentage minus the
        non-compliant one, rounded half up to two decimals and expressed in
        percentage points, and it is null whenever either component is null."

        Design: Corner/calculations/district_metrics_exclude_pending_and_exempt_parcels
        """
        world = noticed_world(client)
        add_zones(
            client,
            world["inspection"]["id"],
            world["inspector"]["id"],
            PASS_CLEARANCES,
        )
        passed = complete_inspection(
            client, world["inspection"]["id"], world["inspector"]["id"], result="PASS"
        )
        assert passed["result"] == "PASS"
        assert_posture(get_parcel(client, world["parcel"]["id"]), "COMPLIANT")

        never_inspected = create_parcel(client)
        exempt = create_parcel(client)
        exempt = validate_success(
            client.update_parcel(
                exempt["id"],
                parcel_patch(exempt["version"], exemption_flag=True),
                headers=PROGRAM_ADMIN_HEADERS,
            )
        )
        assert_posture(exempt, "EXEMPT")
        assert exempt["inspection_priority_rank"] is None

        for parcel_id in (
            world["parcel"]["id"],
            never_inspected["id"],
            exempt["id"],
        ):
            validate_success(
                client.record_survival_outcome(
                    parcel_id, survival_payload("SURVIVED"), headers=PROGRAM_ADMIN_HEADERS
                )
            )

        assert_posture(
            get_parcel(client, never_inspected["id"]), "PENDING_INSPECTION"
        )
        # Stored, and still excluded: the filter reads compliance_status.
        assert (
            get_parcel(client, never_inspected["id"])["structure_survival_outcome"]
            == "SURVIVED"
        )

        district = cycle_metrics(client, world["cycle"]["id"])
        assert_metrics(district, 1, 1, 100.00)
        assert_2dp(district["survived_compliant_pct"], 100.00)
        assert district["survived_noncompliant_pct"] is None
        assert district["survival_delta_pp"] is None


class TestPriorityOrdering:
    """The ranking is a total order whose last tie-break is creation time."""

    def test_identical_scores_are_split_by_created_at_and_exempt_parcels_drop_out(
        self, client
    ):
        """Two identically scored HIGH parcels take ranks 2 and 3 in creation order,
        the clamped EXTREME parcel takes rank 1, and the exempt parcel is unranked.

        PRD: "The ranking considers only parcels whose exemption_flag is false; an
        exempt parcel is not ranked last, it is excluded from the ordering entirely
        and keeps inspection_priority_rank null."

        PRD: "The first key is the risk band, treated as an ordinal - EXTREME counts
        as 4, HIGH as 3, MODERATE as 2 and LOW as 1 - sorted from highest to lowest."

        PRD: "The fourth and final key breaks any remaining tie by created_at
        ascending, oldest parcel first - the parcel's id is never used as a
        tie-break."

        PRD: "Each candidate's inspection_priority_rank is its 1-based position in
        that ordering; ranks are consecutive integers starting at 1 with no gaps."

        PRD: "The product is then clamped so that it can never exceed 100.00, and the
        clamped value is rounded half up to two decimal places to give risk_score.
        Clamping happens before rounding, not after."

        PRD: "The priority queue returns the district's non-exempt parcels ordered by
        inspection_priority_rank ascending, so rank 1 - the parcel most urgently in
        need of a visit - appears first; it accepts limit and offset like any other
        list."

        Design: Corner/calculations/priority_queue_ranks_by_risk_then_created_at
        """
        cycle = open_cycle(client)
        extreme = create_parcel(client, extreme_parcel_payload())
        high_first = create_parcel(client)

        set_clock(client, "2026-08-02T00:00:00Z")
        high_second = create_parcel(client)
        moderate = create_parcel(client, moderate_parcel_payload())
        exempt = create_parcel(client)
        validate_success(
            client.update_parcel(
                exempt["id"],
                parcel_patch(exempt["version"], exemption_flag=True),
                headers=PROGRAM_ADMIN_HEADERS,
            )
        )

        # 91.00 weighted subtotal times 1.30 is 118.30, clamped before rounding.
        assert_risk(extreme, 100.00, "EXTREME", basis="INTAKE_PROVISIONAL")
        assert_instant(high_first["created_at"], EPOCH_CLOCK_UTC)
        assert_instant(high_second["created_at"], "2026-08-02T00:00:00Z")
        assert_risk(high_first, 63.83, "HIGH")
        assert_risk(high_second, 63.83, "HIGH")
        assert_risk(moderate, 35.25, "MODERATE")

        advanced = advance_cycle(client, cycle["id"])
        assert advanced["epoch"] == 1

        ranks = {
            key: get_parcel(client, parcel["id"])["inspection_priority_rank"]
            for key, parcel in (
                ("extreme", extreme),
                ("high_first", high_first),
                ("high_second", high_second),
                ("moderate", moderate),
                ("exempt", exempt),
            )
        }
        assert ranks["extreme"] == 1
        assert ranks["high_first"] == 2, "the earlier-created HIGH parcel ranks first"
        assert ranks["high_second"] == 3
        assert ranks["moderate"] == 4
        assert ranks["exempt"] is None, "an exempt parcel is excluded, not ranked 5"
        assert sorted(
            value for value in ranks.values() if value is not None
        ) == [1, 2, 3, 4], "ranks are dense consecutive integers"

        rows, meta = priority_queue(client, cycle["id"])
        assert meta["total_count"] == 4
        assert ids_of(rows) == [
            extreme["id"],
            high_first["id"],
            high_second["id"],
            moderate["id"],
        ]
        assert exempt["id"] not in ids_of(rows)


class TestPaymentWaterfall:
    """The buckets fill in a pinned order and the subsidy lands in the last one."""

    def test_a_partial_payment_fills_the_buckets_in_order_and_spills_into_disposal(
        self, client
    ):
        """60,000 cents fills overhead and mobilization in full, spills 6,824 into
        disposal and leaves labor untouched.

        PRD: "The bucket order is ADMIN_OVERHEAD first, then MOBILIZATION, then
        DISPOSAL, and LABOR last, and each bucket's capacity is the corresponding line
        amount - admin_overhead_cents, mobilization_line_cents, disposal_line_cents
        and labor_line_cents respectively."

        PRD: "The recoverable amount is poured into the buckets in that order, each
        filled to its capacity before the next receives anything; because
        total_recoverable_cents is smaller than the sum of the caps by exactly the
        subsidy, the subsidy shortfall lands entirely in the last bucket, LABOR."

        PRD: "Each recorded payment then consumes that filled allocation in the same
        bucket order, net of whatever earlier payments already consumed: for each
        bucket in turn, the payment contributes the lesser of what remains of the
        payment and what remains unpaid in that bucket."

        PRD: "The payment also records outstanding_after_cents, which is
        total_recoverable_cents minus the order's paid_cents as it stands immediately
        after this payment is applied."

        PRD: "The payment may not exceed the outstanding balance, that is
        total_recoverable_cents minus paid_cents, and an over-payment is refused with
        ERR_PAYMENT_EXCEEDS_OUTSTANDING."

        PRD: "When the order stands in INVOICED and the payment brings paid_cents to
        exactly total_recoverable_cents, the order moves INVOICED -> PAID."

        Design: Corner/calculations/payment_waterfall_fills_buckets_in_pinned_order
        """
        world = invoiced_world(client)
        order = world["order"]
        assert order["status"] == "INVOICED"
        # 13438 + 3738 + 4000 overhead per line, 190576 before the 0.20 subsidy.
        assert_cost_recovery(
            order,
            labor=107500,
            disposal=29900,
            mobilization=32000,
            overhead=21176,
            pre_subsidy_total=190576,
            subsidy_pct=0.20,
            subsidy=38115,
            total_recoverable=152461,
            recovery_basis="DISTRICT_CONTRACTED",
        )
        assert_end_of_day(order["invoice_due_utc"], "2026-11-20")

        first = record_payment(client, order["id"], 60000)
        assert_allocation(
            first, admin_overhead=21176, mobilization=32000, disposal=6824, labor=0
        )
        assert sum(first["allocation"].values()) == 60000
        assert_cents(first["outstanding_after_cents"], 92461)

        midway = get_order(client, order["id"])
        assert_cents(midway["paid_cents"], 60000)
        assert midway["status"] == "INVOICED", "a partial payment does not settle"

        # One cent more than the outstanding balance is refused outright.
        validate_error(
            client.record_payment(
                order["id"],
                payment_payload(92462),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_PAYMENT_EXCEEDS_OUTSTANDING,
            422,
        )
        assert_cents(get_order(client, order["id"])["paid_cents"], 60000)

        second = record_payment(client, order["id"], 92461)
        assert_allocation(
            second, admin_overhead=0, mobilization=0, disposal=23076, labor=69385
        )
        assert_cents(second["outstanding_after_cents"], 0)

        settled = get_order(client, order["id"])
        assert settled["status"] == "PAID"
        assert_cents(settled["paid_cents"], 152461)
        # LABOR absorbs the whole shortfall against its 107500 cap.
        assert_cents(21176 + 32000 + 29900 + 69385, 152461)


class TestExtensionMovesOneDeadline:
    """An extension edits the interval in place; it does not open a second one."""

    def test_the_single_deadline_moves_thirty_days_and_only_once(self, client):
        """2026-09-26 becomes 2026-10-26 while delivery and compliance_days stand
        still, and the second request is refused.

        PRD: "A granted extension moves the notice ISSUED -> EXTENDED, adds 30 whole
        days to deadline_utc while preserving the 23:59:59 UTC end-of-day form, and
        increments extension_count by 1."

        PRD: "And extension_count must still be below the ceiling of one extension
        per notice: as noted in section 2.9, an already-EXTENDED notice is an accepted
        target for the state gate and is refused further down the ladder with
        ERR_EXTENSION_LIMIT_REACHED, leaving deadline_utc and extension_count
        untouched."

        PRD: "At the next cycle advance, a notice standing in ISSUED or EXTENDED whose
        deadline_utc has passed transitions to OVERDUE - ISSUED -> OVERDUE and
        EXTENDED -> OVERDUE behave identically - and the cited parcel's
        compliance_status is set to NON_COMPLIANT, with both the notice's and the
        parcel's version advancing by 1."

        PRD: "The comparison that decides lateness is strict: a notice is past due
        only when deadline_utc is strictly earlier than the logical clock, so a clock
        reading exactly equal to deadline_utc is still inside the compliance window."

        Design: Corner/calculations/notice_extension_moves_the_single_deadline_in_place
        """
        world = failed_world(client, fail_at="2026-08-22T00:00:00Z")
        notice = world["notice"]
        assert_notice_schedule(
            notice, "MAJOR", "2026-08-27T00:00:00Z", 30, "2026-09-26", status="ISSUED"
        )

        extended = validate_success(
            client.extend_notice(
                notice["id"],
                headers=PROGRAM_ADMIN_HEADERS,
                payload=reason_payload(
                    "Contractor scheduling delay documented by the owner"
                ),
            )
        )
        assert extended["status"] == "EXTENDED"
        assert extended["extension_count"] == 1
        # The extension is added to the deadline, never to delivered_at_utc.
        assert_notice_schedule(
            extended, "MAJOR", "2026-08-27T00:00:00Z", 30, "2026-10-26"
        )

        _rows, meta = list_notices(client, parcel_id=world["parcel"]["id"])
        assert meta["total_count"] == 1, "no second notice and no second interval"

        validate_error(
            client.extend_notice(
                notice["id"],
                headers=PROGRAM_ADMIN_HEADERS,
                payload=reason_payload("One more week please"),
            ),
            ERR_EXTENSION_LIMIT_REACHED,
            409,
        )
        held = get_notice(client, notice["id"])
        assert held["extension_count"] == 1
        assert_end_of_day(held["deadline_utc"], "2026-10-26")

        # Inside the extended window an advance leaves the notice alone.
        set_clock(client, "2026-10-01T00:00:00Z")
        advance_cycle(client, world["cycle"]["id"])
        assert get_notice(client, notice["id"])["status"] == "EXTENDED"

        set_clock(client, "2026-10-27T00:00:00Z")
        advance_cycle(client, world["cycle"]["id"])
        assert get_notice(client, notice["id"])["status"] == "OVERDUE"
        assert_posture(get_parcel(client, world["parcel"]["id"]), "NON_COMPLIANT")
