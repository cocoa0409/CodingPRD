"""Requests that sit exactly on an inclusive limit and are let through, requests
carrying several defects at once and answered by the highest-precedence rule, and the
references whose relationship — not existence — is what fails."""

from test_helpers import (
    ApiErrorId,
    assert_blackout_window,
    assert_complaint,
    assert_hotel,
    assert_member,
    assert_purchase,
    assert_redemption,
    collect_all,
    factories as fac,
    fixtures as fx,
    make_admin_headers,
    make_care_agent_headers,
    make_hotel_owner_headers,
    make_member_headers,
    validate_error,
    validate_success,
    NON_EXISTENT_UUID,
)


# ----------------------------------------------------------------------
# Scenario builders
# ----------------------------------------------------------------------
def _boundary_bay_at_every_inclusive_limit(api):
    """A property enrolled with the maximum fee percentage, the minimum room count and a
    zero daily rate, and one guest funded with exactly the price of a two-night award."""
    hotel = validate_success(
        api.create_hotel(
            fac.create_hotel_payload(
                name="Boundary Bay Hotel",
                brand_code="BBH",
                market_tier="URBAN",
                program_fee_pct=0.20,
                rooms_count=1,
                trailing_12m_occupancy_pct=1.0,
                trailing_12m_adr_cents=0,
            ),
            make_admin_headers(),
        ),
        201,
    )
    hotel_id = hotel["id"]
    rate_plan = fx.add_rate_plan(api, hotel_id, rate_code="BAR", rate_category="TRANSIENT")
    fx.activate_hotel(api, hotel_id)
    pricing = fx.publish_pricing(
        api,
        hotel_id,
        season="STANDARD",
        window_start_date="2026-01-01",
        window_end_date="2026-12-31",
        points_per_night=20_000,
        cash_copay_cents=0,
        min_tier_required="BASE",
        award_allotment_per_night=2,
    )
    funded = fx.member_funded_by_purchase(
        api,
        40_000,
        email="bb1@example.com",
        full_name="Vera Ionescu",
        enrollment_date="2026-01-07",
    )
    return {
        "hotel": hotel,
        "rate_plan": rate_plan,
        "pricing": pricing,
        "member": funded["member"],
        "member_headers": funded["member_headers"],
    }


def _priority_alpha_active_and_bravo_still_onboarding(api):
    """One trading property, one property still in onboarding with its own rate plan, and
    a guest who could stay at either."""
    alpha = fx.create_active_hotel(
        api,
        rate_code="BAR",
        rate_category="TRANSIENT",
        name="Priority Alpha",
        brand_code="PRA",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=100,
        trailing_12m_occupancy_pct=0.82,
        trailing_12m_adr_cents=30_000,
    )
    bravo = fx.create_onboarding_hotel(
        api,
        name="Priority Bravo",
        brand_code="PRB",
        market_tier="SELECT",
        program_fee_pct=0.03,
        rooms_count=50,
        trailing_12m_occupancy_pct=0.60,
        trailing_12m_adr_cents=9_000,
    )
    bravo_plan = fx.add_rate_plan(
        api, bravo["id"], rate_code="BAR", rate_category="TRANSIENT"
    )
    member = fx.enroll_member(
        api,
        email="pr1@example.com",
        full_name="Iva Bogdan",
        enrollment_date="2026-02-14",
    )
    return {
        "alpha": alpha["hotel"],
        "alpha_plan": alpha["rate_plan"],
        "bravo": bravo,
        "bravo_plan": bravo_plan,
        "member": member,
    }


def _parentcheck_pair_with_one_guests_obligation(api):
    """Two trading properties, a guest carrying one elite obligation of his own, and a
    second guest with no history at all."""
    alpha = fx.create_active_hotel(
        api,
        rate_code="BAR",
        rate_category="TRANSIENT",
        name="Parentcheck Alpha",
        brand_code="PCA",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=100,
        trailing_12m_occupancy_pct=0.82,
        trailing_12m_adr_cents=30_000,
    )
    bravo = fx.create_active_hotel(
        api,
        rate_code="BAR",
        rate_category="TRANSIENT",
        name="Parentcheck Bravo",
        brand_code="PCB",
        market_tier="RESORT",
        program_fee_pct=0.06,
        rooms_count=90,
        trailing_12m_occupancy_pct=0.80,
        trailing_12m_adr_cents=35_000,
    )
    first = fx.enroll_member(
        api, email="pc1@example.com", full_name="Member One", enrollment_date="2026-01-12"
    )
    second = fx.enroll_member(
        api, email="pc2@example.com", full_name="Member Two", enrollment_date="2026-01-13"
    )
    alpha_id = alpha["hotel"]["id"]
    alpha_plan_id = alpha["rate_plan"]["id"]
    fx.posted_stay(
        api, alpha_id, first["id"], alpha_plan_id, "2026-06-01", "2026-06-11", 100_000
    )
    second_stay = fx.posted_stay(
        api, alpha_id, first["id"], alpha_plan_id, "2026-06-15", "2026-06-17", 40_000
    )
    obligation = fx.obligation_of_type(api, second_stay["id"], "UPGRADE")

    return {
        "alpha": alpha["hotel"],
        "alpha_plan": alpha["rate_plan"],
        "bravo": bravo["hotel"],
        "bravo_plan": bravo["rate_plan"],
        "first": first,
        "second": second,
        "obligation": obligation,
    }


def _prereq_palace_priced_for_september_only(api):
    """A property whose only award price window covers September, one airline partner and
    one funded guest."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR",
        rate_category="TRANSIENT",
        name="Prereq Palace",
        brand_code="PQP",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=100,
        trailing_12m_occupancy_pct=0.82,
        trailing_12m_adr_cents=30_000,
    )
    hotel_id = bundle["hotel"]["id"]
    fx.publish_pricing(
        api,
        hotel_id,
        season="STANDARD",
        window_start_date="2026-09-01",
        window_end_date="2026-09-30",
        points_per_night=20_000,
        cash_copay_cents=0,
        min_tier_required="BASE",
        award_allotment_per_night=2,
    )
    partner = fx.create_partner(
        api,
        name="Northline Air",
        partner_type="AIRLINE",
        points_cost_per_1000_cents=900,
        monthly_cap_points=500_000,
    )
    funded = fx.member_funded_by_purchase(
        api,
        40_000,
        email="pq1@example.com",
        full_name="Sofia Marchetti",
        enrollment_date="2026-01-18",
    )
    bundle["partner"] = partner
    bundle["member"] = funded["member"]
    bundle["member_headers"] = funded["member_headers"]
    return bundle


def _capped_buyer_with_a_narrow_partner(api):
    """A retail partner capped at fifty thousand points a month, and a guest who has
    already bought one hundred and ninety thousand points this year."""
    partner = fx.create_partner(
        api,
        name="Grocerway Rewards",
        partner_type="RETAIL",
        points_cost_per_1000_cents=1_000,
        monthly_cap_points=50_000,
    )
    member = fx.enroll_member(
        api, email="cap1@example.com", full_name="Bruno Feld", enrollment_date="2026-01-21"
    )
    member_id = member["id"]
    fx.settled_purchase(api, member_id, 100_000)
    second = fx.settled_purchase(api, member_id, 90_000)

    return {
        "partner": partner,
        "member": member,
        "second_purchase": second,
    }


# ----------------------------------------------------------------------
# Four inclusive limits, four accepted requests.
# ----------------------------------------------------------------------
class TestValuesSittingExactlyOnTheirLimitsAreAccepted:
    def test_a_property_enrols_at_the_top_of_the_fee_range(self, api):
        """Twenty percent is the ceiling of the permitted fee range and is accepted, as
        are the smallest legal room count and a zero daily rate.

        PRD: "`program_fee_pct` must lie between 0.0 and 0.20 inclusive with at most four
        decimal places"

        Design: Corner/validations/values_sitting_exactly_on_their_limits_are_accepted
        """
        bundle = _boundary_bay_at_every_inclusive_limit(api)

        hotel = bundle["hotel"]
        assert hotel["program_fee_pct"] == 0.20, (
            f"the fee percentage should be the 0.20 ceiling, got {hotel['program_fee_pct']}"
        )
        assert hotel["rooms_count"] == 1, f"one room is legal, got {hotel['rooms_count']}"
        assert hotel["trailing_12m_adr_cents"] == 0, (
            f"a zero daily rate is legal, got {hotel['trailing_12m_adr_cents']}"
        )
        assert_hotel(hotel, status="ONBOARDING")

    def test_exactly_one_thousand_points_is_a_legal_lot(self, api):
        """A single thousand-point lot is the smallest purchase the programme sells, and
        it prices at one list block.

        PRD: "The `points_quantity` must be a multiple of 1,000 and at least 1,000."

        Design: Corner/validations/values_sitting_exactly_on_their_limits_are_accepted
        """
        bundle = _boundary_bay_at_every_inclusive_limit(api)

        purchase = validate_success(
            api.create_point_purchase(
                fac.create_point_purchase_payload(
                    bundle["member"]["id"], points_quantity=1_000
                ),
                make_admin_headers(),
            ),
            201,
        )

        assert_purchase(
            purchase, status="PENDING", points_quantity=1_000, cash_due_cents=1_250
        )

    def test_a_sixty_day_window_counts_both_of_its_endpoints(self, api):
        """January, February and the first of March make sixty days once both ends are
        counted.

        PRD: "its `day_count` is computed inclusively on both endpoints: the number of
        days from `start_date` to `end_date` plus one, so a window running from the first
        through the fifth of a month has a `day_count` of 5"

        Design: Corner/validations/values_sitting_exactly_on_their_limits_are_accepted
        """
        bundle = _boundary_bay_at_every_inclusive_limit(api)
        hotel_id = bundle["hotel"]["id"]

        window = fx.draft_blackout(
            api,
            hotel_id,
            "2026-01-01",
            "2026-03-01",
            scope="ALL_REDEMPTIONS",
            headers=make_hotel_owner_headers(hotel_id),
        )

        assert_blackout_window(window, status="DRAFT", day_count=60)

    def test_sixty_days_against_a_sixty_day_allowance_is_accepted(self, api):
        """The allowance rule refuses only what exceeds sixty days, so a window that
        consumes the whole allowance exactly still activates.

        PRD: "Third, the property's `blackout_days_used_current_year` plus this window's
        `day_count` must not exceed 60 days in the logical clock's calendar year, else
        `ERR_BLACKOUT_ANNUAL_CAP_EXCEEDED`."

        Design: Corner/validations/values_sitting_exactly_on_their_limits_are_accepted
        """
        bundle = _boundary_bay_at_every_inclusive_limit(api)
        hotel_id = bundle["hotel"]["id"]
        window = fx.draft_blackout(api, hotel_id, "2026-01-01", "2026-03-01")

        activated = fx.activate_blackout(api, window["id"])

        assert_blackout_window(activated, status="ACTIVE", day_count=60)
        assert_hotel(fx.read_hotel(api, hotel_id), blackout_days_used=60)

    def test_a_booking_may_spend_the_whole_balance(self, api):
        """Two nights at twenty thousand points is exactly what the guest holds, and the
        sufficiency test is an at-least comparison rather than a strict one.

        PRD: "Then the member's `point_balance` must be at least the computed
        `points_charged`, else `ERR_INSUFFICIENT_POINTS`."

        Design: Corner/validations/values_sitting_exactly_on_their_limits_are_accepted
        """
        bundle = _boundary_bay_at_every_inclusive_limit(api)

        booking = fx.book_award(
            api,
            bundle["member"]["id"],
            bundle["hotel"]["id"],
            "2026-07-10",
            "2026-07-12",
            headers=bundle["member_headers"],
        )

        assert_redemption(
            booking,
            fulfillment_status="HELD",
            season="STANDARD",
            points_charged=40_000,
            nights=2,
        )
        assert_member(fx.read_member(api, bundle["member"]["id"]), point_balance=0)


# ----------------------------------------------------------------------
# Several defects at once, one answer.
# ----------------------------------------------------------------------
class TestExistenceChecksOutrankShapeStateAndOwnershipChecks:
    def test_an_unknown_property_is_reported_before_the_bad_dates_and_amount(self, api):
        """The request also reverses its dates and carries negative revenue, and none of
        that is reached.

        PRD: "**Existence** of every identifier, resolved left to right along the path and
        then across body foreign keys"

        Design: Corner/validations/existence_checks_outrank_shape_state_and_ownership_checks
        """
        bundle = _priority_alpha_active_and_bravo_still_onboarding(api)

        response = api.create_stay(
            fac.create_stay_payload(
                bundle["member"]["id"],
                NON_EXISTENT_UUID,
                bundle["alpha_plan"]["id"],
                checkin_date="2026-07-10",
                checkout_date="2026-07-05",
                room_revenue_cents=-900,
            ),
            make_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_HOTEL_NOT_FOUND.value)

    def test_an_unknown_guest_is_reported_before_the_propertys_status(self, api):
        """The named property is still onboarding, but the missing guest is found first.

        PRD: "existence always precedes any check that reads a resource's contents."

        Design: Corner/validations/existence_checks_outrank_shape_state_and_ownership_checks
        """
        bundle = _priority_alpha_active_and_bravo_still_onboarding(api)

        response = api.create_stay(
            fac.create_stay_payload(
                NON_EXISTENT_UUID,
                bundle["bravo"]["id"],
                bundle["bravo_plan"]["id"],
                checkin_date="2026-07-01",
                checkout_date="2026-07-03",
                room_revenue_cents=40_000,
            ),
            make_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_MEMBER_NOT_FOUND.value)

    def test_reversed_dates_are_reported_before_the_propertys_status(self, api):
        """With both identifiers resolving, the shape of the date range is still checked
        ahead of whether the property may trade.

        PRD: "A violation yields `ERR_INVALID_DATE_RANGE` (HTTP 422) and applies to
        paid-stay capture, award booking, blackout drafting and award price publication."

        Design: Corner/validations/existence_checks_outrank_shape_state_and_ownership_checks
        """
        bundle = _priority_alpha_active_and_bravo_still_onboarding(api)

        response = api.create_stay(
            fac.create_stay_payload(
                bundle["member"]["id"],
                bundle["bravo"]["id"],
                bundle["bravo_plan"]["id"],
                checkin_date="2026-07-10",
                checkout_date="2026-07-05",
                room_revenue_cents=40_000,
            ),
            make_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_INVALID_DATE_RANGE.value)

    def test_an_onboarding_property_surfaces_once_nothing_above_it_is_broken(self, api):
        """A clean request against a property that has not opened for trade finally
        reports the status.

        PRD: "Paid stays enter the system already ended or in progress, captured by a
        `ProgramAdministrator` or by the hosting property's `HotelOwner` at a property
        whose status is exactly `ACTIVE`."

        Design: Corner/validations/existence_checks_outrank_shape_state_and_ownership_checks
        """
        bundle = _priority_alpha_active_and_bravo_still_onboarding(api)

        response = api.create_stay(
            fac.create_stay_payload(
                bundle["member"]["id"],
                bundle["bravo"]["id"],
                bundle["bravo_plan"]["id"],
                checkin_date="2026-07-01",
                checkout_date="2026-07-03",
                room_revenue_cents=40_000,
            ),
            make_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_HOTEL_NOT_ACTIVE.value)

    def test_the_referential_check_is_what_remains_at_a_trading_property(self, api):
        """The dates are sane and the property is active, so the borrowed rate plan is the
        only defect left.

        PRD: "The referenced rate plan must belong to the same property as the stay; a
        rate plan from a different property is refused with
        `ERR_RATE_PLAN_HOTEL_MISMATCH`."

        Design: Corner/validations/existence_checks_outrank_shape_state_and_ownership_checks
        """
        bundle = _priority_alpha_active_and_bravo_still_onboarding(api)

        response = api.create_stay(
            fac.create_stay_payload(
                bundle["member"]["id"],
                bundle["alpha"]["id"],
                bundle["bravo_plan"]["id"],
                checkin_date="2026-07-01",
                checkout_date="2026-07-03",
                room_revenue_cents=40_000,
            ),
            make_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_RATE_PLAN_HOTEL_MISMATCH.value)

    def test_none_of_the_five_refusals_left_a_row_behind(self, api):
        """Every one of the refused captures was rejected before anything was written.

        PRD: "Across the whole API, checks are evaluated in a fixed precedence so that a
        request failing several rules always reports the same one."

        Design: Corner/validations/existence_checks_outrank_shape_state_and_ownership_checks
        """
        bundle = _priority_alpha_active_and_bravo_still_onboarding(api)
        admin = make_admin_headers()
        member_id = bundle["member"]["id"]
        attempts = [
            (member_id, NON_EXISTENT_UUID, bundle["alpha_plan"]["id"], "2026-07-05", -900),
            (NON_EXISTENT_UUID, bundle["bravo"]["id"], bundle["bravo_plan"]["id"], "2026-07-03", 40_000),
            (member_id, bundle["bravo"]["id"], bundle["bravo_plan"]["id"], "2026-07-05", 40_000),
            (member_id, bundle["bravo"]["id"], bundle["bravo_plan"]["id"], "2026-07-03", 40_000),
            (member_id, bundle["alpha"]["id"], bundle["bravo_plan"]["id"], "2026-07-03", 40_000),
        ]

        for guest, hotel_id, plan_id, checkout, revenue in attempts:
            response = api.create_stay(
                fac.create_stay_payload(
                    guest,
                    hotel_id,
                    plan_id,
                    checkin_date="2026-07-01" if checkout == "2026-07-03" else "2026-07-10",
                    checkout_date=checkout,
                    room_revenue_cents=revenue,
                ),
                admin,
            )
            assert response.status_code >= 400, (
                f"expected a refusal, got {response.status_code}"
            )

        assert collect_all(api.list_stays, admin) == [], (
            "no stay row should exist after five refused captures"
        )


# ----------------------------------------------------------------------
# The rows exist; the relationship is what fails.
# ----------------------------------------------------------------------
class TestReferencedRowsMustBelongToTheParentNamedInTheRequest:
    def test_a_rate_plan_filed_at_another_property_cannot_price_this_stay(self, api):
        """Both the property and the rate plan exist, so nothing is missing — the plan
        simply belongs to the wrong property.

        PRD: "The referenced rate plan must belong to the same property as the stay; a
        rate plan from a different property is refused with
        `ERR_RATE_PLAN_HOTEL_MISMATCH`."

        Design: Corner/validations/referenced_rows_must_belong_to_the_parent_named_in_the_request
        """
        bundle = _parentcheck_pair_with_one_guests_obligation(api)

        response = api.create_stay(
            fac.create_stay_payload(
                bundle["second"]["id"],
                bundle["alpha"]["id"],
                bundle["bravo_plan"]["id"],
                checkin_date="2026-07-01",
                checkout_date="2026-07-03",
                room_revenue_cents=40_000,
            ),
            make_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_RATE_PLAN_HOTEL_MISMATCH.value)

    def test_a_guest_cannot_complain_about_another_guests_obligation(self, api):
        """The obligation exists and is perfectly valid; it simply hangs off a stay that
        belongs to somebody else.

        PRD: "When the subject is a benefit denial the `related_delivery_id` must be
        supplied and must name an elite benefit obligation whose originating stay belongs
        to the complaining member, else `ERR_DELIVERY_MEMBER_MISMATCH`; for the other two
        subjects the field stays null."

        Design: Corner/validations/referenced_rows_must_belong_to_the_parent_named_in_the_request
        """
        bundle = _parentcheck_pair_with_one_guests_obligation(api)
        stranger_id = bundle["second"]["id"]

        response = api.create_complaint(
            fac.create_complaint_payload(
                stranger_id,
                subject_type="BENEFIT_DENIAL",
                description="I want this upgrade reviewed.",
                related_delivery_id=bundle["obligation"]["id"],
            ),
            make_member_headers(stranger_id),
        )

        validate_error(response, ApiErrorId.ERR_DELIVERY_MEMBER_MISMATCH.value)

    def test_the_same_obligation_is_acceptable_to_its_own_guest(self, api):
        """Filed by the guest whose stay produced it, the identical reference is accepted
        and the complaint opens.

        PRD: "The complaint opens in `OPEN` with `info_request_count` and
        `goodwill_points_granted` both 0, and `resolution` and `adjudication_outcome` both
        null."

        Design: Corner/validations/referenced_rows_must_belong_to_the_parent_named_in_the_request
        """
        bundle = _parentcheck_pair_with_one_guests_obligation(api)
        owner_id = bundle["first"]["id"]

        complaint = validate_success(
            api.create_complaint(
                fac.create_complaint_payload(
                    owner_id,
                    subject_type="BENEFIT_DENIAL",
                    description="My own upgrade, please review.",
                    related_delivery_id=bundle["obligation"]["id"],
                ),
                make_member_headers(owner_id),
            ),
            201,
        )

        assert_complaint(
            complaint,
            status="OPEN",
            subject_type="BENEFIT_DENIAL",
            related_delivery_id=bundle["obligation"]["id"],
            info_request_count=0,
            goodwill_points_granted=0,
        )
        assert len(collect_all(api.list_complaints, make_admin_headers())) == 1, (
            "only the accepted complaint should exist"
        )


# ----------------------------------------------------------------------
# Channel and pricing prerequisites run before any price.
# ----------------------------------------------------------------------
class TestChannelAndPricingPrerequisitesAreCheckedBeforeAnythingIsPriced:
    def test_a_partner_sale_without_a_partner_is_refused(self, api):
        """The partner reference is compulsory on the wholesale channel.

        PRD: "The channel and the partner reference must agree exactly: `partner_id` must
        be present when the channel is `PARTNER_SALE` and absent for both
        `CO_BRAND_CARD` and `DIRECT_PURCHASE`, else `ERR_PARTNER_CHANNEL_MISMATCH` — a
        partner reference on a direct purchase is as much an error as a missing one on a
        partner sale."

        Design: Corner/validations/channel_and_pricing_prerequisites_are_checked_before_anything_is_priced
        """
        bundle = _prereq_palace_priced_for_september_only(api)

        response = api.create_point_purchase(
            fac.create_point_purchase_payload(
                bundle["member"]["id"], points_quantity=10_000, channel="PARTNER_SALE"
            ),
            make_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_PARTNER_CHANNEL_MISMATCH.value)

    def test_a_direct_purchase_naming_a_partner_is_refused_the_same_way(self, api):
        """The partner exists and is valid; it is simply not allowed on a direct sale, and
        the surplus reference fails the same rule as a missing one.

        PRD: "The channel and the partner reference must agree exactly: `partner_id` must
        be present when the channel is `PARTNER_SALE` and absent for both
        `CO_BRAND_CARD` and `DIRECT_PURCHASE`, else `ERR_PARTNER_CHANNEL_MISMATCH` — a
        partner reference on a direct purchase is as much an error as a missing one on a
        partner sale."

        Design: Corner/validations/channel_and_pricing_prerequisites_are_checked_before_anything_is_priced
        """
        bundle = _prereq_palace_priced_for_september_only(api)

        response = api.create_point_purchase(
            fac.create_point_purchase_payload(
                bundle["member"]["id"],
                points_quantity=10_000,
                channel="DIRECT_PURCHASE",
                partner_id=bundle["partner"]["id"],
            ),
            make_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_PARTNER_CHANNEL_MISMATCH.value)

    def test_a_matching_partner_sale_is_priced_at_the_partners_own_list(self, api):
        """Ten lots at the partner's nine-hundred-cent list price is 9,000 cents, with no
        volume discount at that size.

        PRD: "The list price per thousand points is the referenced partner's
        `points_cost_per_1000_cents` for a `PARTNER_SALE`, and a flat 1,250 cents for both
        other channels."

        Design: Corner/validations/channel_and_pricing_prerequisites_are_checked_before_anything_is_priced
        """
        bundle = _prereq_palace_priced_for_september_only(api)
        partner_id = bundle["partner"]["id"]

        purchase = fx.record_purchase(
            api,
            bundle["member"]["id"],
            10_000,
            channel="PARTNER_SALE",
            partner_id=partner_id,
        )

        assert_purchase(
            purchase,
            status="PENDING",
            channel="PARTNER_SALE",
            cash_due_cents=9_000,
            volume_discount_pct=0.0,
        )
        assert purchase["partner_id"] == partner_id, (
            "the accepted sale records the partner it was priced against"
        )

    def test_an_arrival_no_window_covers_is_refused_before_any_price(self, api):
        """The first of October is one day past the only window on file, so the request
        never reaches an inventory or balance check.

        PRD: "An empty candidate set is refused with `ERR_NO_REDEMPTION_PRICING`. The
        winning row is then snapshotted onto the booking"

        Design: Corner/validations/channel_and_pricing_prerequisites_are_checked_before_anything_is_priced
        """
        bundle = _prereq_palace_priced_for_september_only(api)

        response = api.create_redemption(
            fac.create_redemption_payload(
                bundle["member"]["id"],
                bundle["hotel"]["id"],
                fx.hotel_version(api, bundle["hotel"]["id"]),
                checkin_date="2026-10-01",
                checkout_date="2026-10-03",
            ),
            make_care_agent_headers("care-pq-01"),
        )

        validate_error(response, ApiErrorId.ERR_NO_REDEMPTION_PRICING.value)

    def test_selection_keys_on_the_arrival_so_an_october_departure_is_fine(self, api):
        """A thirtieth-of-September arrival is inside the window even though the guest
        leaves in October.

        PRD: "the `checkout_date` plays no part in selection, so a booking that straddles
        two windows is priced entirely by the window containing its arrival."

        Design: Corner/validations/channel_and_pricing_prerequisites_are_checked_before_anything_is_priced
        """
        bundle = _prereq_palace_priced_for_september_only(api)

        booking = validate_success(
            api.create_redemption(
                fac.create_redemption_payload(
                    bundle["member"]["id"],
                    bundle["hotel"]["id"],
                    fx.hotel_version(api, bundle["hotel"]["id"]),
                    checkin_date="2026-09-30",
                    checkout_date="2026-10-02",
                ),
                make_care_agent_headers("care-pq-01"),
            ),
            201,
        )

        assert_redemption(
            booking,
            fulfillment_status="HELD",
            season="STANDARD",
            points_charged=40_000,
            nights=2,
        )

    def test_a_pending_partner_sale_already_consumes_the_partners_volume(self, api):
        """Nothing has settled, and the partner's monthly volume is nevertheless committed
        so the cap cannot be defeated by leaving the sale open.

        PRD: "The `points_quantity` is nevertheless added to the member's
        `points_purchased_current_year` and, for a partner sale, to the partner's
        `purchased_points_mtd`, so both caps are consumed by the pending purchase and
        cannot be defeated by leaving purchases unsettled."

        Design: Corner/validations/channel_and_pricing_prerequisites_are_checked_before_anything_is_priced
        """
        bundle = _prereq_palace_priced_for_september_only(api)
        partner_id = bundle["partner"]["id"]
        purchase = fx.record_purchase(
            api,
            bundle["member"]["id"],
            10_000,
            channel="PARTNER_SALE",
            partner_id=partner_id,
        )

        partner = validate_success(api.get_partner(partner_id, make_admin_headers()))

        assert_purchase(purchase, status="PENDING")
        assert partner["purchased_points_mtd"] == 10_000, (
            "the pending partner sale should already have consumed 10000 of the monthly "
            f"volume, got {partner['purchased_points_mtd']}"
        )
        assert_member(
            fx.read_member(api, bundle["member"]["id"]),
            points_purchased_current_year=50_000,
        )


# ----------------------------------------------------------------------
# Two ceilings breached at once, one answer.
# ----------------------------------------------------------------------
class TestPartnerMonthlyCapMasksTheMembersAnnualPurchaseCap:
    def test_the_guest_has_already_committed_most_of_the_annual_allowance(self, api):
        """Two settled sales of one hundred thousand and ninety thousand points leave ten
        thousand of the annual allowance unused.

        PRD: "The `points_quantity` is nevertheless added to the member's
        `points_purchased_current_year` and, for a partner sale, to the partner's
        `purchased_points_mtd`, so both caps are consumed by the pending purchase and
        cannot be defeated by leaving purchases unsettled."

        Design: Corner/validations/partner_monthly_cap_masks_the_members_annual_purchase_cap
        """
        bundle = _capped_buyer_with_a_narrow_partner(api)

        assert_purchase(bundle["second_purchase"], status="SETTLED", points_quantity=90_000)
        assert_member(
            fx.read_member(api, bundle["member"]["id"]),
            points_purchased_current_year=190_000,
            point_balance=190_000,
        )

    def test_the_partner_ceiling_is_the_one_reported(self, api):
        """Sixty thousand points breaches the partner's fifty-thousand monthly ceiling and
        the guest's annual allowance at once, and the partner rule answers.

        PRD: "And for a `PARTNER_SALE` only, the partner's `purchased_points_mtd` plus
        `points_quantity` must not exceed that partner's `monthly_cap_points`, else
        `ERR_PARTNER_MONTHLY_CAP_EXCEEDED`."

        Design: Corner/validations/partner_monthly_cap_masks_the_members_annual_purchase_cap
        """
        bundle = _capped_buyer_with_a_narrow_partner(api)

        response = api.create_point_purchase(
            fac.create_point_purchase_payload(
                bundle["member"]["id"],
                points_quantity=60_000,
                channel="PARTNER_SALE",
                partner_id=bundle["partner"]["id"],
            ),
            make_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_PARTNER_MONTHLY_CAP_EXCEEDED.value)

    def test_removing_the_partner_unmasks_the_annual_allowance(self, api):
        """With no partner in the request only the guest's own ceiling remains, and it is
        reported as the funding refusal it is.

        PRD: "The member's `points_purchased_current_year` plus the requested
        `points_quantity` must not exceed 200,000, else `ERR_PURCHASE_CAP_EXCEEDED`"

        Design: Corner/validations/partner_monthly_cap_masks_the_members_annual_purchase_cap
        """
        bundle = _capped_buyer_with_a_narrow_partner(api)

        response = api.create_point_purchase(
            fac.create_point_purchase_payload(
                bundle["member"]["id"], points_quantity=60_000, channel="DIRECT_PURCHASE"
            ),
            make_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_PURCHASE_CAP_EXCEEDED.value)

    def test_a_sale_that_fits_both_ceilings_is_accepted_and_priced(self, api):
        """Ten thousand points fits the last of the annual allowance and the partner's
        monthly room, and prices at the partner's own list.

        PRD: "**Constraint satisfaction** — award inventory, tier gating, annual blackout
        cap, uniqueness rules, batch period uniqueness, batch item availability and
        partner monthly cap."

        Design: Corner/validations/partner_monthly_cap_masks_the_members_annual_purchase_cap
        """
        bundle = _capped_buyer_with_a_narrow_partner(api)
        partner_id = bundle["partner"]["id"]

        purchase = fx.record_purchase(
            api,
            bundle["member"]["id"],
            10_000,
            channel="PARTNER_SALE",
            partner_id=partner_id,
        )

        assert_purchase(
            purchase, status="PENDING", cash_due_cents=10_000, volume_discount_pct=0.0
        )
        partner = validate_success(api.get_partner(partner_id, make_admin_headers()))
        assert partner["purchased_points_mtd"] == 10_000, (
            f"the partner has now sold 10000 points, got {partner['purchased_points_mtd']}"
        )
        assert_member(
            fx.read_member(api, bundle["member"]["id"]),
            points_purchased_current_year=200_000,
        )
