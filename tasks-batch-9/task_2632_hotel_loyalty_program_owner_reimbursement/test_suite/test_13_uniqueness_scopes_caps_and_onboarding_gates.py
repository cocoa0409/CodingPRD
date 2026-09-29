"""Collision rules whose scope is the parent rather than the programme, the running
counter that closes a property's denial allowance, the precondition that lives two
entities away from the request, and the two refusals surrounding one activation."""

from test_helpers import (
    ApiErrorId,
    assert_batch,
    assert_complaint,
    assert_delivery,
    assert_hotel,
    assert_member,
    assert_stay,
    collect_all,
    factories as fac,
    fixtures as fx,
    make_admin_headers,
    make_care_agent_headers,
    make_hotel_owner_headers,
    make_member_headers,
    read_entity,
    validate_error,
    validate_success,
)


# ----------------------------------------------------------------------
# Scenario builders
# ----------------------------------------------------------------------
def _windowline_with_one_standard_row_for_the_first_half(api):
    """A resort whose only published price covers the first six months of the year."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR",
        rate_category="TRANSIENT",
        name="Windowline Resort",
        brand_code="WLR",
        market_tier="RESORT",
        program_fee_pct=0.06,
        rooms_count=120,
        trailing_12m_occupancy_pct=0.78,
        trailing_12m_adr_cents=36_000,
    )
    bundle["incumbent"] = fx.publish_pricing(
        api,
        bundle["hotel"]["id"],
        season="STANDARD",
        window_start_date="2026-01-01",
        window_end_date="2026-06-30",
        points_per_night=20_000,
        cash_copay_cents=0,
        min_tier_required="BASE",
        award_allotment_per_night=2,
    )
    return bundle


def _publish(api, hotel_id, **overrides):
    """Publish one award price window and hand back the raw response."""
    return api.create_redemption_pricing(
        hotel_id,
        fac.create_redemption_pricing_payload(**overrides),
        make_admin_headers(),
    )


def _unique_pair_with_one_open_june_batch(api):
    """Two trading properties, the first carrying a `BAR` plan and an open June batch, the
    second carrying a corporate plan only."""
    alpha = fx.create_active_hotel(
        api,
        rate_code="BAR",
        rate_category="TRANSIENT",
        name="Unique Alpha",
        brand_code="UNA",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=100,
        trailing_12m_occupancy_pct=0.82,
        trailing_12m_adr_cents=30_000,
    )
    bravo = fx.create_active_hotel(
        api,
        rate_code="CORP",
        rate_category="CORPORATE_NEGOTIATED",
        name="Unique Bravo",
        brand_code="UNB",
        market_tier="SELECT",
        program_fee_pct=0.04,
        rooms_count=60,
        trailing_12m_occupancy_pct=0.70,
        trailing_12m_adr_cents=12_000,
    )
    june = fx.open_batch(api, alpha["hotel"]["id"], "2026-06")
    return {
        "alpha": alpha["hotel"],
        "alpha_plan": alpha["rate_plan"],
        "bravo": bravo["hotel"],
        "bravo_plan": bravo["rate_plan"],
        "june": june,
    }


def _denialcap_tower_with_two_stays_of_obligations(api):
    """A property whose guest reached the top tier on a fifty-night stay, then took two
    more stays that each synthesised the full obligation set."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR",
        rate_category="TRANSIENT",
        name="Denialcap Tower",
        brand_code="DCT",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=200,
        trailing_12m_occupancy_pct=0.82,
        trailing_12m_adr_cents=30_000,
    )
    hotel_id = bundle["hotel"]["id"]
    plan_id = bundle["rate_plan"]["id"]
    member = fx.enroll_member(
        api, email="dc1@example.com", full_name="Halvard Ness", enrollment_date="2026-01-02"
    )
    member_id = member["id"]
    long_stay = fx.posted_stay(
        api, hotel_id, member_id, plan_id, "2026-01-01", "2026-02-20", 500_000
    )
    second = fx.posted_stay(
        api, hotel_id, member_id, plan_id, "2026-03-01", "2026-03-04", 60_000
    )
    third = fx.posted_stay(
        api, hotel_id, member_id, plan_id, "2026-04-01", "2026-04-03", 40_000
    )

    bundle["member"] = member
    bundle["long_stay"] = long_stay
    bundle["second_stay"] = second
    bundle["third_stay"] = third
    bundle["second_obligations"] = {
        row["benefit_type"]: row for row in fx.obligations_for_stay(api, second["id"])
    }
    bundle["third_obligations"] = {
        row["benefit_type"]: row for row in fx.obligations_for_stay(api, third["id"])
    }
    return bundle


def _waiverline_with_an_escalated_denial(api):
    """A property whose guest reached the second tier, then had one upgrade refused,
    complained, was turned down and escalated."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR",
        rate_category="TRANSIENT",
        name="Waiverline Inn",
        brand_code="WVI",
        market_tier="SELECT",
        program_fee_pct=0.05,
        rooms_count=80,
        trailing_12m_occupancy_pct=0.72,
        trailing_12m_adr_cents=16_000,
    )
    hotel_id = bundle["hotel"]["id"]
    plan_id = bundle["rate_plan"]["id"]
    member = fx.enroll_member(
        api, email="wv1@example.com", full_name="Rosalind Kerr", enrollment_date="2026-01-04"
    )
    member_id = member["id"]
    fx.posted_stay(api, hotel_id, member_id, plan_id, "2026-05-01", "2026-05-11", 100_000)
    disputed_stay = fx.posted_stay(
        api, hotel_id, member_id, plan_id, "2026-06-01", "2026-06-03", 30_000
    )
    obligations = fx.obligations_for_stay(api, disputed_stay["id"])
    obligation = obligations[0]
    fx.deny_obligation(
        api,
        obligation["id"],
        reason="Hotel sold out of upgrade rooms.",
        headers=make_hotel_owner_headers(hotel_id),
    )
    member_headers = make_member_headers(member_id)
    complaint = validate_success(
        api.create_complaint(
            fac.create_complaint_payload(
                member_id,
                subject_type="BENEFIT_DENIAL",
                description="My upgrade was refused on arrival.",
                related_delivery_id=obligation["id"],
            ),
            member_headers,
        ),
        201,
    )
    care = make_care_agent_headers("care-wv-01")
    fx.review_complaint(api, complaint["id"], headers=care)
    resolved = fx.resolve_complaint(
        api,
        complaint["id"],
        resolution="Denial upheld: the property was sold out.",
        headers=care,
    )
    escalated = fx.escalate_complaint(api, complaint["id"], headers=member_headers)

    bundle["member"] = member
    bundle["member_headers"] = member_headers
    bundle["stay"] = disputed_stay
    bundle["obligation"] = obligation
    bundle["obligations"] = obligations
    bundle["complaint"] = complaint
    bundle["resolved"] = resolved
    bundle["escalated"] = escalated
    return bundle


def _onboard_house_without_a_rate_plan(api):
    """A property enrolled and nothing else — syntactically complete, commercially
    empty."""
    return fx.create_onboarding_hotel(
        api,
        name="Onboard House",
        brand_code="OBH",
        market_tier="SELECT",
        program_fee_pct=0.04,
        rooms_count=40,
        trailing_12m_occupancy_pct=0.55,
        trailing_12m_adr_cents=11_000,
    )


# ----------------------------------------------------------------------
# Award price windows: the collision scope is the property and the season.
# ----------------------------------------------------------------------
class TestPricingWindowsCollideWithinASeasonAndIgnoreEachOtherAcrossSeasons:
    def test_a_window_opening_on_the_incumbents_last_day_collides(self, api):
        """The new window shares exactly one calendar day with the incumbent, and one day
        is enough because both bounds are inclusive.

        PRD: "Two windows of the same property and the same season may not overlap in
        their inclusive date ranges; an attempt is refused with
        `ERR_PRICING_WINDOW_OVERLAP`."

        Design: Corner/validations/pricing_windows_collide_within_a_season_and_ignore_each_other_across_seasons
        """
        bundle = _windowline_with_one_standard_row_for_the_first_half(api)

        response = _publish(
            api,
            bundle["hotel"]["id"],
            season="STANDARD",
            window_start_date="2026-06-30",
            window_end_date="2026-07-31",
            points_per_night=22_000,
            cash_copay_cents=0,
            min_tier_required="BASE",
            award_allotment_per_night=2,
        )

        validate_error(response, ApiErrorId.ERR_PRICING_WINDOW_OVERLAP)

    def test_the_collision_is_symmetric_at_the_head_of_the_incumbent(self, api):
        """A window that runs out of the previous year and ends on the incumbent's opening
        day is refused just as firmly as one that starts on its closing day.

        PRD: "Two windows of the same property and the same season may not overlap in
        their inclusive date ranges; an attempt is refused with
        `ERR_PRICING_WINDOW_OVERLAP`."

        Design: Corner/validations/pricing_windows_collide_within_a_season_and_ignore_each_other_across_seasons
        """
        bundle = _windowline_with_one_standard_row_for_the_first_half(api)

        response = _publish(
            api,
            bundle["hotel"]["id"],
            season="STANDARD",
            window_start_date="2025-12-01",
            window_end_date="2026-01-01",
            points_per_night=18_000,
            cash_copay_cents=0,
            min_tier_required="BASE",
            award_allotment_per_night=2,
        )

        validate_error(response, ApiErrorId.ERR_PRICING_WINDOW_OVERLAP)

    def test_a_reversed_window_is_refused_on_its_dates_before_any_overlap_scan(self, api):
        """August the thirty-first through August the first overlaps nothing at all, so the
        only rule it can break is the one about the order of its own dates.

        PRD: "a blackout window's `end_date` and an award price window's
        `window_end_date` must fall on or after their respective start dates. A violation
        yields `ERR_INVALID_DATE_RANGE` (HTTP 422) and applies to paid-stay capture, award
        booking, blackout drafting and award price publication."

        Design: Corner/validations/pricing_windows_collide_within_a_season_and_ignore_each_other_across_seasons
        """
        bundle = _windowline_with_one_standard_row_for_the_first_half(api)

        response = _publish(
            api,
            bundle["hotel"]["id"],
            season="STANDARD",
            window_start_date="2026-08-31",
            window_end_date="2026-08-01",
            points_per_night=18_000,
            cash_copay_cents=0,
            min_tier_required="BASE",
            award_allotment_per_night=2,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_DATE_RANGE)

    def test_a_peak_window_may_sit_wholly_inside_the_standard_window(self, api):
        """The March peak row is swallowed whole by the January-to-June standard row, and
        that is the configuration the resolver exists to handle.

        PRD: "A standard window and a peak window covering the same dates, by contrast, is
        the normal configuration"

        Design: Corner/validations/pricing_windows_collide_within_a_season_and_ignore_each_other_across_seasons
        """
        bundle = _windowline_with_one_standard_row_for_the_first_half(api)

        peak = validate_success(
            _publish(
                api,
                bundle["hotel"]["id"],
                season="PEAK",
                window_start_date="2026-03-01",
                window_end_date="2026-03-15",
                points_per_night=30_000,
                cash_copay_cents=5_000,
                min_tier_required="GOLD",
                award_allotment_per_night=1,
            ),
            201,
        )

        assert peak["season"] == "PEAK", (
            f"the published row records season {peak['season']}, not PEAK"
        )
        assert peak["points_per_night"] == 30_000, (
            "the peak row keeps its own nightly price"
        )
        assert peak["min_tier_required"] == "GOLD", (
            "the peak row keeps its own tier gate"
        )

    def test_a_window_starting_the_day_after_the_incumbent_ends_is_accepted(self, api):
        """July the first is the first day the incumbent does not cover, so the abutting
        window shares nothing and is published.

        PRD: "Two windows of the same property and the same season may not overlap in
        their inclusive date ranges; an attempt is refused with
        `ERR_PRICING_WINDOW_OVERLAP`."

        Design: Corner/validations/pricing_windows_collide_within_a_season_and_ignore_each_other_across_seasons
        """
        bundle = _windowline_with_one_standard_row_for_the_first_half(api)

        abutting = validate_success(
            _publish(
                api,
                bundle["hotel"]["id"],
                season="STANDARD",
                window_start_date="2026-07-01",
                window_end_date="2026-07-31",
                points_per_night=22_000,
                cash_copay_cents=0,
                min_tier_required="BASE",
                award_allotment_per_night=2,
            ),
            201,
        )

        assert abutting["window_start_date"] == "2026-07-01", (
            "the abutting row opens the day after the incumbent closes"
        )
        assert abutting["season"] == "STANDARD", (
            "the abutting row is in the same season as the incumbent"
        )

    def test_once_one_peak_row_exists_a_second_peak_row_can_collide_with_it(self, api):
        """The peak season has its own collision space: the first peak row is welcome
        inside the standard row, and the second one sharing March the fifteenth is not.

        PRD: "Two windows of the same property and the same season may not overlap in
        their inclusive date ranges; an attempt is refused with
        `ERR_PRICING_WINDOW_OVERLAP`."

        Design: Corner/validations/pricing_windows_collide_within_a_season_and_ignore_each_other_across_seasons
        """
        bundle = _windowline_with_one_standard_row_for_the_first_half(api)
        hotel_id = bundle["hotel"]["id"]
        validate_success(
            _publish(
                api,
                hotel_id,
                season="PEAK",
                window_start_date="2026-03-01",
                window_end_date="2026-03-15",
                points_per_night=30_000,
                cash_copay_cents=5_000,
                min_tier_required="GOLD",
                award_allotment_per_night=1,
            ),
            201,
        )
        validate_success(
            _publish(
                api,
                hotel_id,
                season="STANDARD",
                window_start_date="2026-07-01",
                window_end_date="2026-07-31",
                points_per_night=22_000,
                cash_copay_cents=0,
                min_tier_required="BASE",
                award_allotment_per_night=2,
            ),
            201,
        )

        response = _publish(
            api,
            hotel_id,
            season="PEAK",
            window_start_date="2026-03-15",
            window_end_date="2026-03-20",
            points_per_night=31_000,
            cash_copay_cents=5_000,
            min_tier_required="GOLD",
            award_allotment_per_night=1,
        )

        validate_error(response, ApiErrorId.ERR_PRICING_WINDOW_OVERLAP)
        rows = collect_all(
            api.list_redemption_pricing, make_admin_headers(), hotel_id=hotel_id
        )
        assert len(rows) == 3, (
            "the property should hold the incumbent standard row, the peak row and the "
            f"abutting standard row, got {len(rows)} rows"
        )

# ----------------------------------------------------------------------
# Uniqueness scopes: inside one property, not across the programme.
# ----------------------------------------------------------------------
class TestUniquenessIsScopedToTheParentNotToTheProgram:
    def test_the_same_rate_code_twice_at_one_property_is_refused(self, api):
        """A second `BAR` plan is filed under a different rate category, and the category
        does not make the code a new one.

        PRD: "The `rate_code` must be unique within the property; a repeat is refused with
        `ERR_DUPLICATE_RATE_CODE`."

        Design: Corner/validations/uniqueness_is_scoped_to_the_parent_not_to_the_program
        """
        bundle = _unique_pair_with_one_open_june_batch(api)
        alpha_id = bundle["alpha"]["id"]

        response = api.create_rate_plan(
            alpha_id,
            fac.create_rate_plan_payload(rate_code="BAR", rate_category="GROUP"),
            make_hotel_owner_headers(alpha_id),
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_RATE_CODE)

    def test_the_same_rate_code_at_the_next_property_is_a_different_scope(self, api):
        """`BAR` is already taken at the first property and entirely free at the second,
        because the uniqueness window is the property and not the programme.

        PRD: "The `rate_code` must be unique within the property; a repeat is refused with
        `ERR_DUPLICATE_RATE_CODE`."

        Design: Corner/validations/uniqueness_is_scoped_to_the_parent_not_to_the_program
        """
        bundle = _unique_pair_with_one_open_june_batch(api)

        twin = validate_success(
            api.create_rate_plan(
                bundle["bravo"]["id"],
                fac.create_rate_plan_payload(rate_code="BAR", rate_category="TRANSIENT"),
                make_admin_headers(),
            ),
            201,
        )

        assert twin["rate_code"] == "BAR", (
            f"the second property's new plan records code {twin['rate_code']}, not BAR"
        )
        assert twin["hotel_id"] == bundle["bravo"]["id"], (
            "the new plan belongs to the second property"
        )

    def test_a_second_batch_for_the_same_month_and_property_is_refused(self, api):
        """June is already open at the first property, and the incumbent is untouched by
        the refusal.

        PRD: "No other batch for the same property and the same `period_month` may exist
        in `OPEN`, `RELEASED` or `APPROVED`, else `ERR_DUPLICATE_BATCH_PERIOD`"

        Design: Corner/validations/uniqueness_is_scoped_to_the_parent_not_to_the_program
        """
        bundle = _unique_pair_with_one_open_june_batch(api)
        alpha_id = bundle["alpha"]["id"]

        response = api.create_reimbursement_batch(
            fac.create_reimbursement_batch_payload(alpha_id, "2026-06"),
            make_hotel_owner_headers(alpha_id),
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_BATCH_PERIOD)
        assert_batch(fx.read_batch(api, bundle["june"]["id"]), status="OPEN")

    def test_another_month_here_and_the_same_month_there_are_both_free(self, api):
        """Only the pair of property and period is reserved, so July at the first property
        and June at the second both open without complaint.

        PRD: "No other batch for the same property and the same `period_month` may exist
        in `OPEN`, `RELEASED` or `APPROVED`, else `ERR_DUPLICATE_BATCH_PERIOD`"

        Design: Corner/validations/uniqueness_is_scoped_to_the_parent_not_to_the_program
        """
        bundle = _unique_pair_with_one_open_june_batch(api)
        alpha_id = bundle["alpha"]["id"]
        bravo_id = bundle["bravo"]["id"]

        july_here = fx.open_batch(api, alpha_id, "2026-07")
        june_there = fx.open_batch(api, bravo_id, "2026-06")
        validate_success(
            api.create_rate_plan(
                bravo_id,
                fac.create_rate_plan_payload(rate_code="BAR", rate_category="TRANSIENT"),
                make_admin_headers(),
            ),
            201,
        )

        assert_batch(july_here, status="OPEN", item_count=0, net_payable_cents=0)
        assert_batch(june_there, status="OPEN", item_count=0, net_payable_cents=0)
        batches = collect_all(api.list_reimbursement_batches, make_admin_headers())
        assert len(batches) == 3, (
            f"expected the June and July batches here and June there, got {len(batches)}"
        )
        plans = collect_all(api.list_rate_plans, make_admin_headers())
        assert len(plans) == 3, (
            f"expected one plan at the first property and two at the second, got {len(plans)}"
        )

# ----------------------------------------------------------------------
# The denial allowance is a running counter on the property.
# ----------------------------------------------------------------------
def _exhaust_the_denial_allowance(api, bundle):
    """Refuse all three of the second stay's obligations, the last one as the programme."""
    hotel_id = bundle["hotel"]["id"]
    owner = make_hotel_owner_headers(hotel_id)
    obligations = bundle["second_obligations"]
    first = fx.deny_obligation(
        api,
        obligations["UPGRADE"]["id"],
        reason="No suite inventory that week.",
        headers=owner,
    )
    second = fx.deny_obligation(
        api,
        obligations["BREAKFAST"]["id"],
        reason="Restaurant closed for refurbishment.",
        headers=owner,
    )
    third = fx.deny_obligation(
        api,
        obligations["LATE_CHECKOUT"]["id"],
        reason="Arrival compression the following morning.",
        headers=make_admin_headers(),
    )
    return [first, second, third]


class TestFourthBenefitDenialAtTheSamePropertyIsRefused:
    def test_the_qualifying_stay_is_read_at_its_own_check_in(self, api):
        """Fifty nights arrive with the guest still unranked, and only the posting that
        follows lifts the guest to the top tier.

        PRD: "the number of days from `checkin_date` to `checkout_date` — a half-open
        interval that includes the arrival date and excludes the departure date, so a stay
        arriving on the tenth and departing on the twelfth is two nights — and snapshots
        the guest's current `elite_tier` into `tier_at_checkin`"

        Design: Corner/validations/fourth_benefit_denial_at_the_same_property_is_refused
        """
        bundle = _denialcap_tower_with_two_stays_of_obligations(api)

        assert_stay(bundle["long_stay"], nights=50, tier_at_checkin="BASE")
        assert_member(fx.read_member(api, bundle["member"]["id"]), elite_tier="PLATINUM")

    def test_three_denials_on_one_stay_exhaust_the_whole_allowance(self, api):
        """All three of the second stay's obligations are refused, and the property's
        counter reaches its ceiling on a single stay.

        PRD: "`DENIED`, `ESCALATED` and `DENIED_FINAL` are all inside the counted set,
        while `DELIVERED`, `WAIVED` and `OBLIGATED` are outside it."

        Design: Corner/validations/fourth_benefit_denial_at_the_same_property_is_refused
        """
        bundle = _denialcap_tower_with_two_stays_of_obligations(api)

        refusals = _exhaust_the_denial_allowance(api, bundle)

        for refusal in refusals:
            assert_delivery(refusal, status="DENIED", cost_recovery_cents=0)
        assert_hotel(
            fx.read_hotel(api, bundle["hotel"]["id"]),
            benefit_denial_count=3,
            benefit_recovery_owed_cents=0,
        )

    def test_the_fourth_denial_is_refused_even_on_a_later_stay(self, api):
        """The fourth refusal is a different benefit type on a different stay, and the
        counter does not care about either.

        PRD: "the property's `benefit_denial_count` must be below 3 before this denial is
        recorded, else `ERR_BENEFIT_DENIAL_LIMIT_EXCEEDED`"

        Design: Corner/validations/fourth_benefit_denial_at_the_same_property_is_refused
        """
        bundle = _denialcap_tower_with_two_stays_of_obligations(api)
        _exhaust_the_denial_allowance(api, bundle)
        hotel_id = bundle["hotel"]["id"]

        response = api.deny_benefit(
            bundle["third_obligations"]["UPGRADE"]["id"],
            fac.deny_benefit_payload(denial_reason="Still no suites."),
            make_hotel_owner_headers(hotel_id),
        )

        validate_error(response, ApiErrorId.ERR_BENEFIT_DENIAL_LIMIT_EXCEEDED)

    def test_the_ceiling_on_refusals_never_blocks_an_honoured_benefit(self, api):
        """The very obligation that could not be refused is honoured instead, and the
        property is paid fifteen percent of its average daily rate for it.

        PRD: "An `UPGRADE` recovers fifteen percent of the property's
        `trailing_12m_adr_cents` as read at delivery time, rounded half up to the cent and
        then capped at 9,000 cents"

        Design: Corner/validations/fourth_benefit_denial_at_the_same_property_is_refused
        """
        bundle = _denialcap_tower_with_two_stays_of_obligations(api)
        _exhaust_the_denial_allowance(api, bundle)
        hotel_id = bundle["hotel"]["id"]

        honoured = fx.deliver_obligation(
            api,
            bundle["third_obligations"]["UPGRADE"]["id"],
            headers=make_hotel_owner_headers(hotel_id),
        )

        assert_delivery(
            honoured,
            status="DELIVERED",
            benefit_type="UPGRADE",
            cost_recovery_cents=4_500,
        )

    def test_honouring_a_benefit_leaves_the_exhausted_counter_where_it_was(self, api):
        """A delivery is outside the counted set, so the count neither falls nor rises, and
        the third stay is left with its two untouched obligations.

        PRD: "`DENIED`, `ESCALATED` and `DENIED_FINAL` are all inside the counted set,
        while `DELIVERED`, `WAIVED` and `OBLIGATED` are outside it."

        Design: Corner/validations/fourth_benefit_denial_at_the_same_property_is_refused
        """
        bundle = _denialcap_tower_with_two_stays_of_obligations(api)
        _exhaust_the_denial_allowance(api, bundle)
        hotel_id = bundle["hotel"]["id"]
        fx.deliver_obligation(
            api,
            bundle["third_obligations"]["UPGRADE"]["id"],
            headers=make_hotel_owner_headers(hotel_id),
        )

        hotel = fx.read_hotel(api, hotel_id)

        assert_hotel(
            hotel, benefit_denial_count=3, benefit_recovery_owed_cents=4_500
        )
        outstanding = collect_all(
            api.list_benefit_deliveries, make_admin_headers(), status="OBLIGATED"
        )
        assert len(outstanding) == 2, (
            "only the third stay's breakfast and late checkout should still be owed, got "
            f"{len(outstanding)} outstanding obligations"
        )

# ----------------------------------------------------------------------
# The void cascade removes the very obligation the escalation argued about.
# ----------------------------------------------------------------------
class TestAdjudicationIsRefusedOnceTheStayVoidWaivedTheEscalatedDenial:
    def test_a_second_tier_stay_obligates_the_upgrade_alone(self, api):
        """The guest arrives at the second tier, so the property owes an upgrade and
        nothing else — one obligation is the whole dispute.

        PRD: "The entitlement matrix reads the stay's `tier_at_checkin`: `UPGRADE` is owed
        at `SILVER`, `GOLD` and `PLATINUM`; `BREAKFAST` is owed at `GOLD` and `PLATINUM`;
        `LATE_CHECKOUT` is owed at `PLATINUM` only; and a `BASE` guest is entitled to
        nothing at all."

        Design: Corner/validations/adjudication_is_refused_once_the_stay_void_waived_the_escalated_denial
        """
        bundle = _waiverline_with_an_escalated_denial(api)

        assert len(bundle["obligations"]) == 1, (
            "a second-tier stay should synthesise exactly one obligation, got "
            f"{len(bundle['obligations'])}"
        )
        assert bundle["obligation"]["benefit_type"] == "UPGRADE", (
            "the single obligation should be the upgrade, got "
            f"{bundle['obligation']['benefit_type']}"
        )
        assert_stay(bundle["stay"], status="POSTED_QUALIFYING", tier_at_checkin="SILVER")

    def test_the_escalation_carries_the_complaint_and_the_denial_together(self, api):
        """The upheld complaint moves on to adjudication and drags the refused obligation
        along with it, leaving the property's count where it was.

        PRD: "on success that obligation advances `DENIED → ESCALATED` and the property's
        `benefit_denial_count` is recomputed, which leaves the figure unchanged because
        `ESCALATED` remains inside the counted set."

        Design: Corner/validations/adjudication_is_refused_once_the_stay_void_waived_the_escalated_denial
        """
        bundle = _waiverline_with_an_escalated_denial(api)

        assert_complaint(bundle["resolved"], status="RESOLVED_UPHELD")
        assert_complaint(bundle["escalated"], status="ESCALATED")
        assert_delivery(
            read_entity(api.get_benefit_delivery, bundle["obligation"]["id"], make_admin_headers()),
            status="ESCALATED",
        )
        assert_hotel(fx.read_hotel(api, bundle["hotel"]["id"]), benefit_denial_count=1)

    def test_the_void_cascade_waives_an_escalated_obligation_too(self, api):
        """Voiding the stay takes the obligation with it even though the obligation had
        already left `OBLIGATED` for the escalation.

        PRD: "every elite benefit obligation whose `stay_id` names this very stay and whose
        `status` is `OBLIGATED` or `ESCALATED` moves to `WAIVED`, because an obligation
        cannot outlive the stay that created it and an escalated denial loses the fact
        pattern it was arguing about."

        Design: Corner/validations/adjudication_is_refused_once_the_stay_void_waived_the_escalated_denial
        """
        bundle = _waiverline_with_an_escalated_denial(api)

        voided = fx.void_stay(
            api,
            bundle["stay"]["id"],
            reason="Folio rebilled to a corporate master account.",
        )

        assert_stay(voided, status="VOID")
        assert_delivery(
            read_entity(api.get_benefit_delivery, bundle["obligation"]["id"], make_admin_headers()),
            status="WAIVED",
        )

    def test_adjudication_is_refused_because_no_live_denial_remains(self, api):
        """The complaint is legitimately escalated, and the obligation two entities away is
        not, which is the refusal the check exists for.

        PRD: "When the complaint's `subject_type` is `BENEFIT_DENIAL`, the named obligation
        must still be in `ESCALATED`, else `ERR_DELIVERY_NOT_ESCALATED`"

        Design: Corner/validations/adjudication_is_refused_once_the_stay_void_waived_the_escalated_denial
        """
        bundle = _waiverline_with_an_escalated_denial(api)
        fx.void_stay(
            api,
            bundle["stay"]["id"],
            reason="Folio rebilled to a corporate master account.",
        )

        response = api.adjudicate_complaint(
            bundle["complaint"]["id"],
            fac.adjudicate_complaint_payload(adjudication_outcome="DELIVERY_ORDERED"),
            make_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_DELIVERY_NOT_ESCALATED)

    def test_the_refused_adjudication_leaves_the_complaint_open_at_escalated(self, api):
        """Nothing about the complaint changes: it keeps the status it earned and is not
        quietly closed by the refusal.

        PRD: "A member complaint sitting in `ESCALATED` against a waived obligation keeps
        its own status, but its adjudication will now be refused with
        `ERR_DELIVERY_NOT_ESCALATED`"

        Design: Corner/validations/adjudication_is_refused_once_the_stay_void_waived_the_escalated_denial
        """
        bundle = _waiverline_with_an_escalated_denial(api)
        fx.void_stay(
            api,
            bundle["stay"]["id"],
            reason="Folio rebilled to a corporate master account.",
        )
        api.adjudicate_complaint(
            bundle["complaint"]["id"],
            fac.adjudicate_complaint_payload(adjudication_outcome="DELIVERY_ORDERED"),
            make_admin_headers(),
        )

        complaint = fx.read_complaint(api, bundle["complaint"]["id"])

        assert_complaint(complaint, status="ESCALATED", subject_type="BENEFIT_DENIAL")
        assert complaint["adjudication_outcome"] is None, (
            "the refused adjudication should have recorded no outcome, got "
            f"{complaint['adjudication_outcome']}"
        )

    def test_the_void_removed_only_the_two_nights_it_owned(self, api):
        """The guest keeps the ten nights of the earlier stay and therefore keeps the tier
        those nights bought.

        PRD: "the member's `point_balance`, `lifetime_points_earned`,
        `qualifying_revenue_cents_ytd` and `qualifying_nights_ytd` are all recomputed, and
        the recomputed night count re-derives the member's `elite_tier`, which may drop."

        Design: Corner/validations/adjudication_is_refused_once_the_stay_void_waived_the_escalated_denial
        """
        bundle = _waiverline_with_an_escalated_denial(api)
        fx.void_stay(
            api,
            bundle["stay"]["id"],
            reason="Folio rebilled to a corporate master account.",
        )

        member = fx.read_member(api, bundle["member"]["id"])

        assert_member(
            member,
            elite_tier="SILVER",
            qualifying_nights=10,
            qualifying_revenue_cents=100_000,
        )

    def test_the_waived_escalation_gives_the_property_its_denial_back(self, api):
        """`WAIVED` is outside the counted set, so the property that had one refusal on its
        record now has none.

        PRD: "Waiving an `ESCALATED` obligation recomputes the property's
        `benefit_denial_count`, and since `WAIVED` sits outside the counted set that figure
        falls by one."

        Design: Corner/validations/adjudication_is_refused_once_the_stay_void_waived_the_escalated_denial
        """
        bundle = _waiverline_with_an_escalated_denial(api)
        fx.void_stay(
            api,
            bundle["stay"]["id"],
            reason="Folio rebilled to a corporate master account.",
        )

        hotel = fx.read_hotel(api, bundle["hotel"]["id"])

        assert_hotel(hotel, benefit_denial_count=0, benefit_recovery_owed_cents=0)


# ----------------------------------------------------------------------
# One activation endpoint, two refusals on either side of one success.
# ----------------------------------------------------------------------
class TestActivationIsRefusedUntilThePropertyHasARatePlan:
    def test_a_commercially_empty_property_cannot_be_activated(self, api):
        """The property is enrolled and syntactically complete, and the refusal leaves both
        its status and its version exactly as enrolment left them.

        PRD: "the property's status must be exactly `ONBOARDING`, so a second activation
        attempt on an already-active property is refused with `ERR_HOTEL_NOT_ACTIVE` rather
        than silently repeated; then at least one rate plan must belong to the property,
        failing which the request is refused with `ERR_HOTEL_ONBOARDING_INCOMPLETE`.
        Activation increments the property's `version`."

        Design: Corner/validations/activation_is_refused_until_the_property_has_a_rate_plan
        """
        hotel = _onboard_house_without_a_rate_plan(api)

        response = api.activate_hotel(hotel["id"], make_admin_headers())

        validate_error(response, ApiErrorId.ERR_HOTEL_ONBOARDING_INCOMPLETE)
        assert_hotel(fx.read_hotel(api, hotel["id"]), status="ONBOARDING", version=1)

    def test_one_rate_plan_of_any_category_makes_the_same_call_succeed(self, api):
        """Nothing about the request changes; the property simply has something to sell,
        and the successful activation bumps the version the refusal left alone.

        PRD: "the property's status must be exactly `ONBOARDING`, so a second activation
        attempt on an already-active property is refused with `ERR_HOTEL_NOT_ACTIVE` rather
        than silently repeated; then at least one rate plan must belong to the property,
        failing which the request is refused with `ERR_HOTEL_ONBOARDING_INCOMPLETE`.
        Activation increments the property's `version`."

        Design: Corner/validations/activation_is_refused_until_the_property_has_a_rate_plan
        """
        hotel = _onboard_house_without_a_rate_plan(api)
        api.activate_hotel(hotel["id"], make_admin_headers())
        plan = validate_success(
            api.create_rate_plan(
                hotel["id"],
                fac.create_rate_plan_payload(rate_code="BAR", rate_category="TRANSIENT"),
                make_hotel_owner_headers(hotel["id"]),
            ),
            201,
        )

        activated = validate_success(api.activate_hotel(hotel["id"], make_admin_headers()))

        assert plan["hotel_id"] == hotel["id"], (
            "the filed plan should belong to the property being activated"
        )
        assert_hotel(activated, status="ACTIVE", version=2)

    def test_activating_an_already_active_property_hits_the_state_rule_instead(self, api):
        """The rate plan is now in place, so the only rule left to break is the one about
        the status, and the second refusal leaves the row untouched.

        PRD: "the property's status must be exactly `ONBOARDING`, so a second activation
        attempt on an already-active property is refused with `ERR_HOTEL_NOT_ACTIVE` rather
        than silently repeated; then at least one rate plan must belong to the property,
        failing which the request is refused with `ERR_HOTEL_ONBOARDING_INCOMPLETE`.
        Activation increments the property's `version`."

        Design: Corner/validations/activation_is_refused_until_the_property_has_a_rate_plan
        """
        hotel = _onboard_house_without_a_rate_plan(api)
        validate_success(
            api.create_rate_plan(
                hotel["id"],
                fac.create_rate_plan_payload(rate_code="BAR", rate_category="TRANSIENT"),
                make_hotel_owner_headers(hotel["id"]),
            ),
            201,
        )
        validate_success(api.activate_hotel(hotel["id"], make_admin_headers()))

        response = api.activate_hotel(hotel["id"], make_admin_headers())

        validate_error(response, ApiErrorId.ERR_HOTEL_NOT_ACTIVE)
        assert_hotel(fx.read_hotel(api, hotel["id"]), status="ACTIVE", version=2)
