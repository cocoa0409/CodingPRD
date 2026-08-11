"""Dues pricing variants, chapter-share rounding, increase-notice gap boundary,
schedule overlap, supersession, leap-year proration.

Covers Queue A difficulty instances:
- dual_variant_calc/dues_amount_anniversary_vs_calendar_prorated
- combinatorial_formula/chapter_share_nested_rounding_order_pinned
- boundary_precision_check/increase_notice_gap_exactly_at_threshold_allowed
- resource_temporal_overlap/dues_schedule_half_open_interval_overlap
- priority_pair_validation_conflict/state_vs_business_temporal_publish_overlapping_schedule

Covers Queue B corner instances:
- calculations/calendar_proration_leap_year_denominator
- calculations/schedule_superseded_when_newer_published
- state_machines/dues_schedule_initial_state_is_draft
- errors/error_schedule_overlap_triggered
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_category,
    create_chapter,
    create_cycle_policy,
    create_published_schedule,
    create_draft_schedule,
    create_member,
    get_initial_invoice,
    set_clock,
    advance_clock_and_run,
    make_member_headers,
    TEST_USERS,
)

DUES_ADMIN = TEST_USERS["dues_admin_headers"]


# =====================================================================
# Queue A — dual_variant_calc/dues_amount_anniversary_vs_calendar_prorated
# =====================================================================

class TestDualVariantDuesAmount:
    def test_anniversary_bills_full_base_amount(self, api):
        """PRD §3.4: "When the cycle policy's mode is ANNIVERSARY, the invoice always
        bills the full base: amount_cents is the schedule's annual_amount_cents regardless
        of when in the year the join or renewal occurs."

        Design: Difficulty/dual_variant_calc/dues_amount_anniversary_vs_calendar_prorated
        """
        cat = create_category(code="PROF_ACTIVE", name="Professional Active")
        ch = create_chapter(code="CH_WEST", name="West Chapter")
        pol_ann = create_cycle_policy(code="POLICY_ANN", mode="ANNIVERSARY",
                                       calendar_anchor_month=1, calendar_anchor_day=1,
                                       proration_method="NONE")
        create_published_schedule(cat["id"], effective_from="2026-01-01T00:00:00Z",
                                   annual_amount_cents=120000, chapter_share_bps=2000,
                                   increase_notice_days=60)
        m_ann = create_member(cat["id"], ch["id"], pol_ann["id"],
                              email="ann@x.com", joined_at="2026-05-01T00:00:00Z")
        inv = get_initial_invoice(m_ann["id"], make_member_headers(m_ann["id"]))
        assert inv["amount_cents"] == 120000, (
            f"ANNIVERSARY mode must bill full base; got {inv['amount_cents']}"
        )

    def test_calendar_pro_rata_daily_prorates_by_days_remaining(self, api):
        """PRD §3.4: "Under PRO_RATA_DAILY, days_remaining is the integer number of days
        from period_start to period_end, and days_in_year is 366 when period_start falls
        in a leap year and 365 otherwise; amount_cents is the base annual_amount_cents
        multiplied by days_remaining, divided by days_in_year, and the result rounded
        half-up to a whole cent."

        2026 is non-leap; 2026-05-01 to 2026-12-31 = 244 days;
        round_half_up(120000 * 244 / 365) = 80219.

        Design: Difficulty/dual_variant_calc/dues_amount_anniversary_vs_calendar_prorated
        """
        cat = create_category(code="PROF_ACTIVE", name="Professional Active")
        ch = create_chapter(code="CH_WEST", name="West Chapter")
        pol_cal = create_cycle_policy(code="POLICY_CAL", mode="CALENDAR",
                                       calendar_anchor_month=12, calendar_anchor_day=31,
                                       proration_method="PRO_RATA_DAILY")
        create_published_schedule(cat["id"], effective_from="2026-01-01T00:00:00Z",
                                   annual_amount_cents=120000, chapter_share_bps=2000,
                                   increase_notice_days=60)
        m_cal = create_member(cat["id"], ch["id"], pol_cal["id"],
                              email="cal@x.com", joined_at="2026-05-01T00:00:00Z")
        inv = get_initial_invoice(m_cal["id"], make_member_headers(m_cal["id"]))
        assert inv["amount_cents"] == 80219, (
            f"CALENDAR/PRO_RATA_DAILY 2026-05-01 -> 2026-12-31 = 244 days; "
            f"round_half_up(120000*244/365) = 80219; got {inv['amount_cents']}"
        )


# =====================================================================
# Queue A — combinatorial_formula/chapter_share_nested_rounding_order_pinned
# =====================================================================

class TestChapterShareRoundingOrder:
    def test_chapter_share_computed_first_then_national_residual(self, api):
        """PRD §3.5: "The chapter-share ledger accrues chapter_share_cents to the
        member's home_chapter_id, computed as the invoice's amount_cents multiplied by
        the schedule's chapter_share_bps, divided by 10000, rounded half-up to a whole
        cent; the national share is the residual, amount_cents minus chapter_share_cents.
        The chapter share is computed first and the national share derived by subtraction
        — the rounding order is binding."

        round_half_up(120001 * 3333 / 10000) = round_half_up(39996.3333) = 39996.

        Design: Difficulty/combinatorial_formula/chapter_share_nested_rounding_order_pinned
        """
        cat = create_category(code="PROF", name="P")
        ch = create_chapter(code="CH", name="C")
        pol = create_cycle_policy(code="POLICY", mode="ANNIVERSARY",
                                   calendar_anchor_month=1, calendar_anchor_day=1,
                                   proration_method="NONE")
        create_published_schedule(cat["id"], effective_from="2026-01-01T00:00:00Z",
                                   annual_amount_cents=120001, chapter_share_bps=3333,
                                   increase_notice_days=60)
        m = create_member(cat["id"], ch["id"], pol["id"], email="m@x.com")
        mh = make_member_headers(m["id"])
        inv = get_initial_invoice(m["id"], mh)
        resp = api_client.submit_payment(inv["id"],
                                          {"payment_method_token": "tok_v",
                                           "simulated_outcome": "SUCCEEDED"},
                                          mh)
        validate_success(resp, expected_status=201)
        settled = get_success_data(api_client.get_dues_invoice(inv["id"],
                                                                TEST_USERS["membership_admin_headers"]))
        assert settled["chapter_share_cents"] == 39996, (
            f"chapter_share_cents must be round_half_up(120001*3333/10000)=39996; "
            f"got {settled['chapter_share_cents']}"
        )

    def test_national_share_is_residual_after_chapter_share(self, api):
        """PRD §3.5: "the national share is the residual, amount_cents minus
        chapter_share_cents. The chapter share is computed first and the national share
        derived by subtraction — the rounding order is binding."

        amount=120001, chapter_share=39996 -> national_share = 80005. Verify
        conservation: chapter_share + national == amount.

        Design: Difficulty/combinatorial_formula/chapter_share_nested_rounding_order_pinned
        """
        cat = create_category(code="PROF", name="P")
        ch = create_chapter(code="CH", name="C")
        pol = create_cycle_policy(code="POLICY", mode="ANNIVERSARY",
                                   calendar_anchor_month=1, calendar_anchor_day=1,
                                   proration_method="NONE")
        create_published_schedule(cat["id"], effective_from="2026-01-01T00:00:00Z",
                                   annual_amount_cents=120001, chapter_share_bps=3333,
                                   increase_notice_days=60)
        m = create_member(cat["id"], ch["id"], pol["id"], email="m@x.com")
        mh = make_member_headers(m["id"])
        inv = get_initial_invoice(m["id"], mh)
        resp = api_client.submit_payment(inv["id"],
                                          {"payment_method_token": "tok_v",
                                           "simulated_outcome": "SUCCEEDED"},
                                          mh)
        validate_success(resp, expected_status=201)
        settled = get_success_data(api_client.get_dues_invoice(inv["id"],
                                                                TEST_USERS["membership_admin_headers"]))
        national_share = settled["amount_cents"] - settled["chapter_share_cents"]
        assert settled["amount_cents"] == 120001
        assert settled["chapter_share_cents"] == 39996
        assert national_share == 80005, (
            f"national_share residual must equal 120001-39996=80005; got {national_share}"
        )


# =====================================================================
# Queue A — boundary_precision_check/increase_notice_gap_exactly_at_threshold_allowed
# =====================================================================

class TestIncreaseNoticeGapBoundary:
    def _base_setup(self):
        cat = create_category(code="PROF", name="P")
        create_published_schedule(cat["id"], effective_from="2026-01-01T00:00:00Z",
                                   annual_amount_cents=120000, chapter_share_bps=2000,
                                   increase_notice_days=60)
        return cat

    def test_gap_exactly_at_threshold_allowed(self, api):
        """PRD §3.2: "the gap between that notice's noticed_at and the new schedule's
        effective_from must be at least increase_notice_days — a gap strictly less than
        increase_notice_days is rejected with ERR_INCREASE_NOTICE_GAP. The boundary is
        inclusive: a gap exactly equal to increase_notice_days is allowed."

        Notice on 2026-07-01, effective_from=2026-08-30 -> gap = 60 days (== required 60).

        Design: Difficulty/boundary_precision_check/increase_notice_gap_exactly_at_threshold_allowed
        """
        cat = self._base_setup()
        s2 = create_draft_schedule(cat["id"], effective_from="2026-08-30T00:00:00Z",
                                    annual_amount_cents=130000, chapter_share_bps=2000,
                                    increase_notice_days=60)
        set_clock("2026-07-01T00:00:00Z")
        notice_resp = api_client.create_increase_notice(s2["id"], DUES_ADMIN)
        validate_success(notice_resp, expected_status=201)
        publish_resp = api_client.publish_dues_schedule(s2["id"], DUES_ADMIN)
        published = validate_success(publish_resp, expected_status=200)
        assert published["status"] == "PUBLISHED"

    def test_gap_one_day_under_threshold_rejected(self, api):
        """PRD §3.2: "a gap strictly less than increase_notice_days is rejected with
        ERR_INCREASE_NOTICE_GAP."

        Notice on 2026-07-17, effective_from=2026-09-15 -> gap = 60 days but notice
        observed at 2026-07-18 makes the gap 59 days; simpler: notice on 2026-07-18
        with effective_from=2026-09-15 -> gap=59 < required 60.

        Design: Difficulty/boundary_precision_check/increase_notice_gap_exactly_at_threshold_allowed
        """
        cat = self._base_setup()
        s3 = create_draft_schedule(cat["id"], effective_from="2026-09-15T00:00:00Z",
                                    annual_amount_cents=135000, chapter_share_bps=2000,
                                    increase_notice_days=60)
        set_clock("2026-07-18T00:00:00Z")
        notice_resp = api_client.create_increase_notice(s3["id"], DUES_ADMIN)
        validate_success(notice_resp, expected_status=201)
        publish_resp = api_client.publish_dues_schedule(s3["id"], DUES_ADMIN)
        validate_error(publish_resp, ApiErrorId.ERR_INCREASE_NOTICE_GAP)


# =====================================================================
# Queue A — resource_temporal_overlap/dues_schedule_half_open_interval_overlap
# Queue B — errors/error_schedule_overlap_triggered
# =====================================================================

class TestScheduleHalfOpenOverlap:
    def test_back_to_back_schedules_no_overlap_allowed(self, api):
        """PRD §3.2: "the [effective_from, effective_to) interval of a schedule being
        created or published must not overlap the interval of any other PUBLISHED
        schedule for the same category_id; an overlap is rejected with
        ERR_SCHEDULE_OVERLAP."

        S1=[2026-01-01, 2027-01-01), S2=[2027-01-01, null) — adjacent at the
        half-open boundary, no overlap.

        Design: Difficulty/resource_temporal_overlap/dues_schedule_half_open_interval_overlap
        """
        cat = create_category(code="PROF", name="P")
        create_published_schedule(cat["id"],
                                   effective_from="2026-01-01T00:00:00Z",
                                   effective_to="2027-01-01T00:00:00Z",
                                   annual_amount_cents=120000, chapter_share_bps=2000,
                                   increase_notice_days=60)
        s2 = create_draft_schedule(cat["id"], effective_from="2027-01-01T00:00:00Z",
                                    effective_to=None, annual_amount_cents=125000,
                                    chapter_share_bps=2000, increase_notice_days=60)
        # notice required since amount rises
        notice_resp = api_client.create_increase_notice(s2["id"], DUES_ADMIN)
        validate_success(notice_resp, expected_status=201)
        publish_resp = api_client.publish_dues_schedule(s2["id"], DUES_ADMIN)
        published = validate_success(publish_resp, expected_status=200)
        assert published["status"] == "PUBLISHED"

    def test_one_day_overlap_rejected(self, api):
        """PRD §3.2: "the [effective_from, effective_to) interval of a schedule being
        created or published must not overlap the interval of any other PUBLISHED
        schedule for the same category_id; an overlap is rejected with
        ERR_SCHEDULE_OVERLAP."

        S1=[2026-01-01, 2027-01-01), S3=[2026-12-31, null) — 1-day overlap.

        Design: Difficulty/resource_temporal_overlap/dues_schedule_half_open_interval_overlap
        """
        cat = create_category(code="PROF", name="P")
        create_published_schedule(cat["id"],
                                   effective_from="2026-01-01T00:00:00Z",
                                   effective_to="2027-01-01T00:00:00Z",
                                   annual_amount_cents=120000, chapter_share_bps=2000,
                                   increase_notice_days=60)
        s3 = create_draft_schedule(cat["id"], effective_from="2026-12-31T00:00:00Z",
                                    effective_to=None, annual_amount_cents=125000,
                                    chapter_share_bps=2000, increase_notice_days=60)
        notice_resp = api_client.create_increase_notice(s3["id"], DUES_ADMIN)
        validate_success(notice_resp, expected_status=201)
        publish_resp = api_client.publish_dues_schedule(s3["id"], DUES_ADMIN)
        validate_error(publish_resp, ApiErrorId.ERR_SCHEDULE_OVERLAP)

    def test_overlapping_interval_publish_rejected_corner(self, api):
        """PRD §3.2: "the [effective_from, effective_to) interval of a schedule being
        created or published must not overlap the interval of any other PUBLISHED
        schedule for the same category_id; an overlap is rejected with
        ERR_SCHEDULE_OVERLAP."

        S1=[2026-01-01, 2027-01-01) PUBLISHED; S2=[2026-06-01, 2027-06-01) DRAFT.
        Publishing S2 overlaps S1.

        Design: Corner/errors/error_schedule_overlap_triggered
        """
        cat = create_category(code="PROF", name="P")
        create_published_schedule(cat["id"],
                                   effective_from="2026-01-01T00:00:00Z",
                                   effective_to="2027-01-01T00:00:00Z",
                                   annual_amount_cents=120000, chapter_share_bps=2000,
                                   increase_notice_days=60)
        s2 = create_draft_schedule(cat["id"], effective_from="2026-06-01T00:00:00Z",
                                    effective_to="2027-06-01T00:00:00Z",
                                    annual_amount_cents=125000, chapter_share_bps=2000,
                                    increase_notice_days=60)
        publish_resp = api_client.publish_dues_schedule(s2["id"], DUES_ADMIN)
        validate_error(publish_resp, ApiErrorId.ERR_SCHEDULE_OVERLAP)


# =====================================================================
# Queue A — priority_pair_validation_conflict/state_vs_business_temporal_publish_overlapping_schedule
# =====================================================================

class TestPublishPriorityPairConflict:
    def test_publish_already_published_returns_invalid_state(self, api):
        """PRD §2.5: "The order is: ... (6) target state permits the requested
        transition — failures yield ERR_INVALID_STATE; ... (8) schedule-overlap check —
        failures yield ERR_SCHEDULE_OVERLAP; ... When more than one rule could fire on
        the same request, the lower-numbered rule wins."

        Publishing an already-PUBLISHED schedule fails the state check (priority 6)
        before any temporal check (priority 8) can fire.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_publish_overlapping_schedule
        """
        cat = create_category(code="PROF", name="P")
        s1 = create_published_schedule(cat["id"],
                                        effective_from="2026-01-01T00:00:00Z",
                                        annual_amount_cents=120000,
                                        chapter_share_bps=2000, increase_notice_days=60)
        # S2 exists in DRAFT to ensure the temporal domain is populated
        create_draft_schedule(cat["id"], effective_from="2026-06-01T00:00:00Z",
                               annual_amount_cents=130000, chapter_share_bps=2000,
                               increase_notice_days=60)
        resp = api_client.publish_dues_schedule(s1["id"], DUES_ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_publish_overlapping_draft_returns_schedule_overlap(self, api):
        """PRD §2.5: "(8) schedule-overlap check — failures yield ERR_SCHEDULE_OVERLAP."

        S2 is DRAFT (state-check passes) but overlaps S1 PUBLISHED — only the
        temporal check fires, surfacing ERR_SCHEDULE_OVERLAP.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_publish_overlapping_schedule
        """
        cat = create_category(code="PROF", name="P")
        create_published_schedule(cat["id"],
                                   effective_from="2026-01-01T00:00:00Z",
                                   effective_to="2027-01-01T00:00:00Z",
                                   annual_amount_cents=120000, chapter_share_bps=2000,
                                   increase_notice_days=60)
        s2 = create_draft_schedule(cat["id"], effective_from="2026-06-01T00:00:00Z",
                                    effective_to="2027-06-01T00:00:00Z",
                                    annual_amount_cents=130000, chapter_share_bps=2000,
                                    increase_notice_days=60)
        # Notice sent so the increase-notice check doesn't interfere
        notice_resp = api_client.create_increase_notice(s2["id"], DUES_ADMIN)
        validate_success(notice_resp, expected_status=201)
        resp = api_client.publish_dues_schedule(s2["id"], DUES_ADMIN)
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_OVERLAP)


# =====================================================================
# Queue B — calculations/calendar_proration_leap_year_denominator
# =====================================================================

def test_calendar_proration_leap_year_uses_366(api):
    """PRD §3.4: "Under PRO_RATA_DAILY, days_remaining is the integer number of days
    from period_start to period_end, and days_in_year is 366 when period_start falls
    in a leap year and 365 otherwise; amount_cents is the base annual_amount_cents
    multiplied by days_remaining, divided by days_in_year, and the result rounded
    half-up to a whole cent."

    2028 is leap. 2028-02-01 -> 2028-12-31 = 334 days.
    round_half_up(120000 * 334 / 366) = round_half_up(109508.1967) = 109508.

    Design: Corner/calculations/calendar_proration_leap_year_denominator
    """
    cat = create_category(code="PROF", name="P")
    ch = create_chapter(code="CH", name="C")
    pol = create_cycle_policy(code="POLICY_CAL", mode="CALENDAR",
                               calendar_anchor_month=12, calendar_anchor_day=31,
                               proration_method="PRO_RATA_DAILY")
    create_published_schedule(cat["id"], effective_from="2028-01-01T00:00:00Z",
                               annual_amount_cents=120000, chapter_share_bps=2000,
                               increase_notice_days=60)
    set_clock("2028-02-01T00:00:00Z")
    m = create_member(cat["id"], ch["id"], pol["id"], email="m@x.com",
                      joined_at="2028-02-01T00:00:00Z")
    inv = get_initial_invoice(m["id"], make_member_headers(m["id"]))
    assert inv["amount_cents"] == 109508, (
        f"Leap-year pro-rata: round_half_up(120000*334/366)=109508; got {inv['amount_cents']}"
    )


# =====================================================================
# Queue B — calculations/schedule_superseded_when_newer_published
# =====================================================================

def test_prior_published_schedule_superseded_on_newer_publish(api):
    """PRD §3.2: "At the moment of publication, any previously PUBLISHED schedule for
    the same category transitions to SUPERSEDED at the new schedule's effective_from."

    Design: Corner/calculations/schedule_superseded_when_newer_published
    """
    cat = create_category(code="PROF", name="P")
    s1 = create_published_schedule(cat["id"],
                                    effective_from="2026-01-01T00:00:00Z",
                                    effective_to="2026-07-01T00:00:00Z",
                                    annual_amount_cents=120000, chapter_share_bps=2000,
                                    increase_notice_days=60)
    s2 = create_draft_schedule(cat["id"], effective_from="2026-07-01T00:00:00Z",
                                annual_amount_cents=130000, chapter_share_bps=2000,
                                increase_notice_days=60)
    set_clock("2026-04-30T00:00:00Z")
    notice_resp = api_client.create_increase_notice(s2["id"], DUES_ADMIN)
    validate_success(notice_resp, expected_status=201)
    publish_resp = api_client.publish_dues_schedule(s2["id"], DUES_ADMIN)
    validate_success(publish_resp, expected_status=200)
    s1_after = get_success_data(api_client.get_dues_schedule(s1["id"], DUES_ADMIN))
    s2_after = get_success_data(api_client.get_dues_schedule(s2["id"], DUES_ADMIN))
    assert s1_after["status"] == "SUPERSEDED"
    assert s2_after["status"] == "PUBLISHED"


# =====================================================================
# Queue B — state_machines/dues_schedule_initial_state_is_draft
# =====================================================================

def test_new_schedule_born_in_draft(api):
    """PRD §3.2: "A new schedule is born in DRAFT."

    Design: Corner/state_machines/dues_schedule_initial_state_is_draft
    """
    cat = create_category(code="PROF", name="P")
    s = create_draft_schedule(cat["id"])
    assert s["status"] == "DRAFT"
