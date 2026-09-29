"""The fixed order in which an award booking may be refused: which gate speaks
first when a request fails several tests at once."""

from test_helpers import (
    ApiErrorId,
    assert_blackout_window,
    assert_fund,
    assert_hotel,
    assert_member,
    assert_redemption,
    assert_stay,
    collect_all,
    factories as fac,
    fixtures as fx,
    make_admin_headers,
    make_member_headers,
    validate_error,
    validate_success,
)


# ----------------------------------------------------------------------
# Scenario builders
# ----------------------------------------------------------------------
def _harbour_point_still_onboarding(api):
    """A resort that has published a rate plan and an award price but has never been
    activated, and a member who holds no points at all."""
    hotel = fx.create_onboarding_hotel(
        api,
        name="Harbour Point Resort",
        brand_code="HBP",
        market_tier="RESORT",
        program_fee_pct=0.045,
        rooms_count=190,
        trailing_12m_occupancy_pct=0.71,
        trailing_12m_adr_cents=34_000,
    )
    fx.add_rate_plan(api, hotel["id"], rate_code="BAR-ONB", rate_category="TRANSIENT")
    fx.publish_standard_pricing(
        api,
        hotel["id"],
        points_per_night=40_000,
        cash_copay_cents=0,
        min_tier_required="BASE",
        award_allotment_per_night=3,
    )
    member = fx.enroll_member(api)

    return {
        "hotel": hotel,
        "member": member,
        "member_headers": make_member_headers(member["id"]),
    }


def _copper_lake_blacked_out_and_gold_gated(api):
    """A resort selling only GOLD-and-above award inventory, with an eleven-day
    all-seasons blackout across the middle of September, and a BASE member who can
    easily afford the room."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR-CPL",
        rate_category="TRANSIENT",
        name="Copper Lake Resort",
        brand_code="CPL",
        market_tier="RESORT",
        program_fee_pct=0.05,
        rooms_count=175,
        trailing_12m_occupancy_pct=0.69,
        trailing_12m_adr_cents=36_000,
    )
    hotel_id = bundle["hotel"]["id"]
    fx.publish_standard_pricing(
        api,
        hotel_id,
        points_per_night=40_000,
        cash_copay_cents=0,
        min_tier_required="GOLD",
        award_allotment_per_night=3,
    )
    window = fx.create_active_blackout(
        api, hotel_id, "2026-09-10", "2026-09-20", scope="ALL_REDEMPTIONS"
    )
    member = fx.member_with_goodwill_points(api, 100_000)

    bundle["blackout"] = window
    bundle["member"] = member
    bundle["member_headers"] = make_member_headers(member["id"])
    return bundle


def _ironclad_delinquent_with_peak_and_standard_windows(api):
    """A delinquent convention property publishing both a year-long standard window
    and a late-December peak window, and a guest holding 360,000 earned points."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="GRP-ICC",
        rate_category="GROUP",
        name="Ironclad Convention Centre",
        brand_code="ICC",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=500,
        trailing_12m_occupancy_pct=0.90,
        trailing_12m_adr_cents=20_000,
    )
    hotel_id = bundle["hotel"]["id"]
    fx.publish_pricing(
        api,
        hotel_id,
        season="STANDARD",
        window_start_date="2026-01-01",
        window_end_date="2026-12-31",
        points_per_night=40_000,
        cash_copay_cents=0,
        min_tier_required="BASE",
        award_allotment_per_night=3,
    )
    fx.publish_pricing(
        api,
        hotel_id,
        season="PEAK",
        window_start_date="2026-12-20",
        window_end_date="2026-12-31",
        points_per_night=60_000,
        cash_copay_cents=2_500,
        min_tier_required="BASE",
        award_allotment_per_night=3,
    )
    fx.member_funded_by_purchase(api, 200_000, channel="DIRECT_PURCHASE")

    guest = fx.enroll_member(api)
    group_stay = fx.posted_stay(
        api,
        hotel_id,
        guest["id"],
        bundle["rate_plan"]["id"],
        "2026-06-01",
        "2026-06-11",
        6_000_000,
    )

    bundle["guest"] = guest
    bundle["guest_headers"] = make_member_headers(guest["id"])
    bundle["group_stay"] = group_stay
    return bundle


# ----------------------------------------------------------------------
# The status gate outranks the balance test.
# ----------------------------------------------------------------------
class TestOnboardingStatusMasksInsufficientPoints:
    def test_the_status_gate_speaks_before_the_members_empty_balance_does(self, api):
        """The member could not have afforded the room either way, but the property is
        not open for award business yet and that is the answer.

        PRD: "Booking an award stay and opening a reimbursement batch require status
        either `ACTIVE` or `FEE_DELINQUENT`, refusing only `ONBOARDING` and
        `TERMINATED`"

        Design: Difficulty/priority_pair_validation_conflict/onboarding_property_masks_insufficient_points_and_unmasks_after_activation
        """
        bundle = _harbour_point_still_onboarding(api)
        assert_member(bundle["member"], point_balance=0)

        response = api.create_redemption(
            fac.create_redemption_payload(
                bundle["member"]["id"],
                bundle["hotel"]["id"],
                bundle["hotel"]["version"],
                checkin_date="2026-09-10",
                checkout_date="2026-09-12",
            ),
            bundle["member_headers"],
        )

        validate_error(response, ApiErrorId.ERR_HOTEL_NOT_ACTIVE.value)

    def test_activation_unmasks_the_balance_test_underneath(self, api):
        """The identical request against the now-active property reaches the fiscal
        gate and reports the shortfall.

        PRD: "Then the member's `point_balance` must be at least the computed
        `points_charged`, else `ERR_INSUFFICIENT_POINTS`."

        Design: Difficulty/priority_pair_validation_conflict/onboarding_property_masks_insufficient_points_and_unmasks_after_activation
        """
        bundle = _harbour_point_still_onboarding(api)
        activated = fx.activate_hotel(api, bundle["hotel"]["id"])

        response = api.create_redemption(
            fac.create_redemption_payload(
                bundle["member"]["id"],
                bundle["hotel"]["id"],
                activated["version"],
                checkin_date="2026-09-10",
                checkout_date="2026-09-12",
            ),
            bundle["member_headers"],
        )

        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_POINTS.value)

    def test_activation_is_the_only_thing_that_moved_the_property_version(self, api):
        """A refused booking bumps nothing; only the successful activation does.

        PRD: "Activation is the administrator-only step that moves a property
        `ONBOARDING → ACTIVE` and opens it for paid-stay capture and award
        redemption."

        Design: Difficulty/priority_pair_validation_conflict/onboarding_property_masks_insufficient_points_and_unmasks_after_activation
        """
        bundle = _harbour_point_still_onboarding(api)
        hotel_id = bundle["hotel"]["id"]
        opening_version = bundle["hotel"]["version"]

        api.create_redemption(
            fac.create_redemption_payload(
                bundle["member"]["id"], hotel_id, opening_version,
                checkin_date="2026-09-10", checkout_date="2026-09-12",
            ),
            bundle["member_headers"],
        )
        activated = fx.activate_hotel(api, hotel_id)
        api.create_redemption(
            fac.create_redemption_payload(
                bundle["member"]["id"], hotel_id, activated["version"],
                checkin_date="2026-09-10", checkout_date="2026-09-12",
            ),
            bundle["member_headers"],
        )

        assert fx.hotel_version(api, hotel_id) == opening_version + 1, (
            "activation alone accounts for the version movement"
        )
        assert_hotel(fx.read_hotel(api, hotel_id), status="ACTIVE")

    def test_neither_refusal_left_a_booking_or_a_ledger_entry_behind(self, api):
        """Both refusals happen before anything is written, so the programme's books
        are empty afterwards.

        PRD: "A `REDEEM` ledger entry is written carrying the negation of
        `points_charged` with `source_redemption_id` naming the booking, the member's
        `point_balance` falls by that amount, the property's `version` increments by
        one, and the fund's `point_liability_cents`, `solvency_ratio` and `status` are
        recomputed."

        Design: Difficulty/priority_pair_validation_conflict/onboarding_property_masks_insufficient_points_and_unmasks_after_activation
        """
        bundle = _harbour_point_still_onboarding(api)
        hotel_id = bundle["hotel"]["id"]
        admin = make_admin_headers()

        api.create_redemption(
            fac.create_redemption_payload(
                bundle["member"]["id"], hotel_id, bundle["hotel"]["version"],
                checkin_date="2026-09-10", checkout_date="2026-09-12",
            ),
            bundle["member_headers"],
        )
        activated = fx.activate_hotel(api, hotel_id)
        api.create_redemption(
            fac.create_redemption_payload(
                bundle["member"]["id"], hotel_id, activated["version"],
                checkin_date="2026-09-10", checkout_date="2026-09-12",
            ),
            bundle["member_headers"],
        )

        assert collect_all(api.list_redemptions, admin) == [], (
            "a refused booking creates no award booking row"
        )
        assert collect_all(api.list_ledger_entries, admin) == [], (
            "a refused booking writes no ledger entry"
        )
        assert_member(fx.read_member(api, bundle["member"]["id"]), point_balance=0)


# ----------------------------------------------------------------------
# The blackout outranks the tier gate at the same HTTP status.
# ----------------------------------------------------------------------
class TestBlackoutMasksTheTierGate:
    def test_a_blacked_out_arrival_reports_the_calendar_not_the_tier(self, api):
        """The member ranks below the window's minimum too, but the blackout is
        checked first and the two refusals share an HTTP status, so only the error
        identifier distinguishes them.

        PRD: "Then no `ACTIVE` blackout window of the property may cover any night of
        the half-open stay interval, else `ERR_BLACKOUT_DATE_UNAVAILABLE`"

        Design: Difficulty/priority_pair_validation_conflict/blackout_date_masks_tier_below_inventory_minimum_at_equal_http_status
        """
        bundle = _copper_lake_blacked_out_and_gold_gated(api)
        assert_blackout_window(
            bundle["blackout"], status="ACTIVE", day_count=11, scope="ALL_REDEMPTIONS"
        )
        assert_member(bundle["member"], elite_tier="BASE", point_balance=100_000)

        response = api.create_redemption(
            fac.create_redemption_payload(
                bundle["member"]["id"],
                bundle["hotel"]["id"],
                fx.hotel_version(api, bundle["hotel"]["id"]),
                checkin_date="2026-09-12",
                checkout_date="2026-09-14",
            ),
            bundle["member_headers"],
        )

        validate_error(response, ApiErrorId.ERR_BLACKOUT_DATE_UNAVAILABLE.value)

    def test_moving_clear_of_the_blackout_surfaces_the_tier_gate(self, api):
        """Outside the blacked-out dates the same BASE member meets the window's
        minimum tier and is refused on rank.

        PRD: "Then the tier gate: the member's `elite_tier` must rank at or above the
        selected window's `min_tier_required`, on the ranking `BASE` below `SILVER`
        below `GOLD` below `PLATINUM`, else `ERR_TIER_BELOW_INVENTORY_MINIMUM`."

        Design: Difficulty/priority_pair_validation_conflict/blackout_date_masks_tier_below_inventory_minimum_at_equal_http_status
        """
        bundle = _copper_lake_blacked_out_and_gold_gated(api)

        response = api.create_redemption(
            fac.create_redemption_payload(
                bundle["member"]["id"],
                bundle["hotel"]["id"],
                fx.hotel_version(api, bundle["hotel"]["id"]),
                checkin_date="2026-09-25",
                checkout_date="2026-09-27",
            ),
            bundle["member_headers"],
        )

        validate_error(response, ApiErrorId.ERR_TIER_BELOW_INVENTORY_MINIMUM.value)

    def test_neither_refusal_moved_the_balance_or_the_property(self, api):
        """Both gates sit above every write, so the member's points and the property's
        version are exactly as they were.

        PRD: "Once the price window is resolved and the price computed, the remaining
        checks run in a fixed order and the first failure is the response."

        Design: Difficulty/priority_pair_validation_conflict/blackout_date_masks_tier_below_inventory_minimum_at_equal_http_status
        """
        bundle = _copper_lake_blacked_out_and_gold_gated(api)
        hotel_id = bundle["hotel"]["id"]
        version_before = fx.hotel_version(api, hotel_id)

        for checkin, checkout in (("2026-09-12", "2026-09-14"), ("2026-09-25", "2026-09-27")):
            api.create_redemption(
                fac.create_redemption_payload(
                    bundle["member"]["id"], hotel_id, version_before,
                    checkin_date=checkin, checkout_date=checkout,
                ),
                bundle["member_headers"],
            )

        assert_member(
            fx.read_member(api, bundle["member"]["id"]), point_balance=100_000
        )
        assert fx.hotel_version(api, hotel_id) == version_before, (
            "a refused booking does not bump the property's version"
        )
        assert collect_all(api.list_redemptions, make_admin_headers()) == [], (
            "neither refusal created an award booking row"
        )


# ----------------------------------------------------------------------
# Peak inventory is withheld while standard inventory still sells.
# ----------------------------------------------------------------------
class TestPeakWithheldWhileStandardStillBooks:
    def test_the_delinquent_property_loses_its_peak_inventory_specifically(self, api):
        """The peak window governs a 22 December arrival, and arrears close it - a
        refusal that outranks the impaired-fund test sitting further down the order.

        PRD: "Then, if the resolved season is `PEAK`, the property must not be
        `FEE_DELINQUENT`, else `ERR_PEAK_INVENTORY_WITHHELD`: peak inventory
        specifically is withheld from properties in arrears."

        Design: Difficulty/cross_entity_state_dependency/peak_award_inventory_withheld_from_a_delinquent_property_while_standard_still_books
        """
        bundle = _ironclad_delinquent_with_peak_and_standard_windows(api)
        assert_stay(
            fx.read_stay(api, bundle["group_stay"]["id"]),
            status="POSTED_QUALIFYING",
            base_points=360_000,
            fee_cents=300_000,
            nights=10,
        )
        assert_hotel(
            fx.read_hotel(api, bundle["hotel"]["id"]),
            status="FEE_DELINQUENT",
            fee_ledger_cents=300_000,
        )
        assert_fund(fx.read_fund(api), status="WATCH", solvency_ratio=0.8185)

        response = api.create_redemption(
            fac.create_redemption_payload(
                bundle["guest"]["id"],
                bundle["hotel"]["id"],
                fx.hotel_version(api, bundle["hotel"]["id"]),
                checkin_date="2026-12-22",
                checkout_date="2026-12-24",
            ),
            bundle["guest_headers"],
        )

        validate_error(response, ApiErrorId.ERR_PEAK_INVENTORY_WITHHELD.value)

    def test_the_refused_peak_booking_moved_nothing(self, api):
        """A guest who could easily afford the peak price is turned away without a
        point leaving the balance.

        PRD: "A peak booking at a delinquent property whose member cannot afford it
        reports `ERR_PEAK_INVENTORY_WITHHELD`, not `ERR_INSUFFICIENT_POINTS`."

        Design: Difficulty/cross_entity_state_dependency/peak_award_inventory_withheld_from_a_delinquent_property_while_standard_still_books
        """
        bundle = _ironclad_delinquent_with_peak_and_standard_windows(api)
        hotel_id = bundle["hotel"]["id"]
        version_before = fx.hotel_version(api, hotel_id)

        api.create_redemption(
            fac.create_redemption_payload(
                bundle["guest"]["id"], hotel_id, version_before,
                checkin_date="2026-12-22", checkout_date="2026-12-24",
            ),
            bundle["guest_headers"],
        )

        assert_member(fx.read_member(api, bundle["guest"]["id"]), point_balance=360_000)
        assert fx.hotel_version(api, hotel_id) == version_before, (
            "the refusal left the property's version alone"
        )
        assert_hotel(fx.read_hotel(api, hotel_id), status="FEE_DELINQUENT")

    def test_standard_inventory_still_sells_at_the_same_delinquent_property(self, api):
        """Ten days earlier the standard window governs, and delinquency does not
        touch standard award business.

        PRD: "Delinquency withdraws peak award inventory program-side, while standard
        bookings and reimbursement batching continue unchanged."

        Design: Difficulty/cross_entity_state_dependency/peak_award_inventory_withheld_from_a_delinquent_property_while_standard_still_books
        """
        bundle = _ironclad_delinquent_with_peak_and_standard_windows(api)
        hotel_id = bundle["hotel"]["id"]
        version_before = fx.hotel_version(api, hotel_id)

        response = api.create_redemption(
            fac.create_redemption_payload(
                bundle["guest"]["id"], hotel_id, version_before,
                checkin_date="2026-12-10", checkout_date="2026-12-12",
            ),
            bundle["guest_headers"],
        )

        booking = validate_success(response, 201)
        assert_redemption(
            booking,
            fulfillment_status="HELD",
            season="STANDARD",
            points_per_night=40_000,
            cash_copay_cents=0,
            points_charged=80_000,
            nights=2,
        )
        assert_member(fx.read_member(api, bundle["guest"]["id"]), point_balance=280_000)
        assert_hotel(fx.read_hotel(api, hotel_id), status="FEE_DELINQUENT")

    def test_the_accepted_booking_bumps_the_property_version_by_exactly_one(self, api):
        """A successful award booking is a write against the property, so its version
        moves - once.

        PRD: "the property's `version` increments by one, and the fund's
        `point_liability_cents`, `solvency_ratio` and `status` are recomputed."

        Design: Difficulty/cross_entity_state_dependency/peak_award_inventory_withheld_from_a_delinquent_property_while_standard_still_books
        """
        bundle = _ironclad_delinquent_with_peak_and_standard_windows(api)
        hotel_id = bundle["hotel"]["id"]
        version_before = fx.hotel_version(api, hotel_id)

        fx.book_award(
            api,
            bundle["guest"]["id"],
            hotel_id,
            "2026-12-10",
            "2026-12-12",
            headers=bundle["guest_headers"],
            expected_hotel_version=version_before,
        )

        assert fx.hotel_version(api, hotel_id) == version_before + 1, (
            "an accepted booking bumps the property's version by exactly one"
        )
