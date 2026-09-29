"""The two optimistic-concurrency tokens, the cumulative balance that flips a posture on one cent, the derived ledger that is re-summed at three different life events, and the single posting that has to be visible in every read that follows it.

Nothing here is asserted from a design document: each expected figure is
recomputed from the property's own fee percentage, the rate plan's earn rate and
the fund's 600-cent unit cost, so a wrong rounding order or a stale read shows
up as an arithmetic mismatch rather than as a status mismatch.
"""

from test_helpers import (
    ApiErrorId,
    assert_fund,
    assert_hotel,
    assert_ledger_entry,
    assert_member,
    assert_redemption,
    assert_stay,
    entries_of_type,
    factories as fac,
    fixtures as fx,
    make_admin_headers,
    make_auditor_headers,
    make_care_agent_headers,
    make_hotel_owner_headers,
    make_member_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _versionlock_hotel_and_a_funded_member(api):
    """A property with one award price window and a member holding exactly one booking's worth of points.

    The allotment is a single room per night, so the booking that eventually
    succeeds consumes the whole night's inventory — which is itself a write on
    the property row and therefore moves the very version that guards it.
    """
    hotel = fx.create_onboarding_hotel(
        api,
        name="Versionlock Hotel",
        brand_code="VLH",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=100,
        trailing_12m_occupancy_pct=0.82,
        trailing_12m_adr_cents=30_000,
    )
    version_at_create = hotel["version"]
    fx.add_rate_plan(api, hotel["id"], rate_code="BAR", rate_category="TRANSIENT")
    activated = fx.activate_hotel(api, hotel["id"])
    fx.publish_pricing(
        api,
        hotel["id"],
        season="STANDARD",
        window_start_date="2026-09-01",
        window_end_date="2026-09-30",
        points_per_night=20_000,
        cash_copay_cents=0,
        min_tier_required="BASE",
        award_allotment_per_night=1,
    )
    member = fx.enroll_member(
        api,
        email="vl1@example.com",
        full_name="Sanne de Vries",
        enrollment_date="2026-02-16",
    )
    fx.settled_purchase(api, member["id"], 40_000, channel="DIRECT_PURCHASE")
    return {
        "hotel_id": hotel["id"],
        "version_at_create": version_at_create,
        "version_at_activation": activated["version"],
        "member_id": member["id"],
        "member_headers": make_member_headers(member["id"]),
        "owner_headers": make_hotel_owner_headers(hotel["id"]),
        "care_headers": make_care_agent_headers("care-vl-01"),
    }


def _a_member_with_a_settled_purchase(api):
    """One member funded by a settled purchase, which leaves the fund healthy enough for goodwill."""
    member = fx.enroll_member(
        api,
        email="mv1@example.com",
        full_name="Rafael Duarte",
        enrollment_date="2026-02-18",
    )
    fx.settled_purchase(api, member["id"], 20_000, channel="DIRECT_PURCHASE")
    return {
        "member_id": member["id"],
        "care_headers": make_care_agent_headers("care-mv-01"),
    }


def _threshold_grand_with_two_unposted_stays(api):
    """A property whose first stay assesses exactly the delinquency threshold, and a second worth one cent of fee.

    Both stays are captured before either is posted, so both snapshot a BASE
    guest and neither earns an elite bonus. The revenue figures are chosen so
    the fee arithmetic lands on 250,000 and then on 250,001.
    """
    bundle = fx.create_active_hotel(
        api,
        name="Threshold Grand",
        brand_code="THG",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=300,
        trailing_12m_occupancy_pct=0.85,
        trailing_12m_adr_cents=50_000,
    )
    hotel_id = bundle["hotel"]["id"]
    member = fx.enroll_member(
        api,
        email="th1@example.com",
        full_name="Camille Roux",
        enrollment_date="2026-02-20",
    )
    at_threshold = fx.capture_stay(
        api,
        hotel_id,
        member["id"],
        bundle["rate_plan"]["id"],
        "2026-06-01",
        "2026-06-02",
        5_000_000,
        headers=bundle["owner_headers"],
    )
    one_cent_more = fx.capture_stay(
        api,
        hotel_id,
        member["id"],
        bundle["rate_plan"]["id"],
        "2026-06-10",
        "2026-06-11",
        20,
        headers=bundle["owner_headers"],
    )
    return {
        "hotel_id": hotel_id,
        "member_id": member["id"],
        "member_headers": make_member_headers(member["id"]),
        "owner_headers": bundle["owner_headers"],
        "at_threshold_id": at_threshold["id"],
        "one_cent_more_id": one_cent_more["id"],
    }


def _reconcile_house_with_two_unposted_stays(api):
    """A property with two captured stays whose fees round in opposite directions."""
    bundle = fx.create_active_hotel(
        api,
        name="Reconcile House",
        brand_code="RCH",
        market_tier="SELECT",
        program_fee_pct=0.05,
        rooms_count=45,
        trailing_12m_occupancy_pct=0.66,
        trailing_12m_adr_cents=13_000,
    )
    hotel_id = bundle["hotel"]["id"]
    member = fx.enroll_member(
        api,
        email="rc1@example.com",
        full_name="Bea Lindqvist",
        enrollment_date="2026-02-22",
    )
    first = fx.capture_stay(
        api, hotel_id, member["id"], bundle["rate_plan"]["id"], "2026-05-01", "2026-05-03", 12_345
    )
    second = fx.capture_stay(
        api, hotel_id, member["id"], bundle["rate_plan"]["id"], "2026-05-10", "2026-05-13", 20_000
    )
    return {
        "hotel_id": hotel_id,
        "member_id": member["id"],
        "owner_headers": bundle["owner_headers"],
        "first_id": first["id"],
        "second_id": second["id"],
        "care_headers": make_care_agent_headers("care-rc-01"),
    }


def _immediate_inn_with_one_unposted_stay(api):
    """A funded member and one captured stay, so a single posting is the only write left to make."""
    bundle = fx.create_active_hotel(
        api,
        name="Immediate Inn",
        brand_code="IMI",
        market_tier="SELECT",
        program_fee_pct=0.05,
        rooms_count=60,
        trailing_12m_occupancy_pct=0.7,
        trailing_12m_adr_cents=15_000,
    )
    hotel_id = bundle["hotel"]["id"]
    member = fx.enroll_member(
        api,
        email="im1@example.com",
        full_name="Tomas Neruda",
        enrollment_date="2026-02-24",
    )
    purchase = fx.settled_purchase(api, member["id"], 20_000, channel="DIRECT_PURCHASE")
    stay = fx.capture_stay(
        api,
        hotel_id,
        member["id"],
        bundle["rate_plan"]["id"],
        "2026-04-01",
        "2026-04-03",
        12_345,
        headers=bundle["owner_headers"],
    )
    return {
        "hotel_id": hotel_id,
        "member_id": member["id"],
        "member_headers": make_member_headers(member["id"]),
        "owner_headers": bundle["owner_headers"],
        "purchase": purchase,
        "stay": stay,
    }


class TestAwardBookingRefusesAStaleHotelVersionAndAcceptsTheRefreshedOne:
    """The property row carries the pricing inputs, so a write to it invalidates a quote."""

    def test_a_performance_refresh_is_the_write_that_invalidates_the_version_just_read(
        self, api
    ):
        """The agent reads the property, the owner restates its performance, and the read the agent holds is now one behind.

        PRD: "Either a `ProgramAdministrator` or the property's `HotelOwner` may restate the property's performance by supplying fresh values for `trailing_12m_occupancy_pct` and `trailing_12m_adr_cents`, which overwrite the stored figures and increment the property's `version`."

        Design: Corner/cross-cutting complexity layers/award_booking_refuses_a_stale_hotel_version_and_accepts_the_refreshed_one
        """
        bundle = _versionlock_hotel_and_a_funded_member(api)
        assert bundle["version_at_create"] == 1, "a freshly registered property opens at version 1"
        assert (
            bundle["version_at_activation"] == 2
        ), "activation is a write on the property row and must move its version"
        as_read = validate_success(
            api.get_hotel(bundle["hotel_id"], bundle["care_headers"])
        )
        assert as_read["version"] == 2, "the care agent's read must see the activated version"
        refreshed = validate_success(
            api.refresh_hotel_performance(
                bundle["hotel_id"],
                fac.performance_refresh_payload(
                    trailing_12m_occupancy_pct=0.91, trailing_12m_adr_cents=34_000
                ),
                bundle["owner_headers"],
            )
        )
        assert refreshed["version"] == 3, "the refresh must increment the property's version"
        assert (
            refreshed["trailing_12m_occupancy_pct"] == 0.91
        ), "the submitted occupancy must overwrite the stored figure"
        assert (
            refreshed["trailing_12m_adr_cents"] == 34_000
        ), "the submitted average daily rate must overwrite the stored figure"

    def test_booking_against_the_superseded_version_is_refused(self, api):
        """The booking carries the version the member was handed, which the refresh has already moved past.

        PRD: "A request to book an award stay must carry `expected_hotel_version`, a required (never optional) field whose value is the `version` of the target property as the client last observed it. If `expected_hotel_version` does not equal that property's current `version`, the booking is rejected with `ERR_STALE_HOTEL_VERSION` (HTTP 412)."

        Design: Corner/cross-cutting complexity layers/award_booking_refuses_a_stale_hotel_version_and_accepts_the_refreshed_one
        """
        bundle = _versionlock_hotel_and_a_funded_member(api)
        stale_version = validate_success(
            api.get_hotel(bundle["hotel_id"], bundle["care_headers"])
        )["version"]
        validate_success(
            api.refresh_hotel_performance(
                bundle["hotel_id"],
                fac.performance_refresh_payload(
                    trailing_12m_occupancy_pct=0.91, trailing_12m_adr_cents=34_000
                ),
                bundle["owner_headers"],
            )
        )
        validate_error(
            api.create_redemption(
                fac.create_redemption_payload(
                    bundle["member_id"],
                    bundle["hotel_id"],
                    stale_version,
                    checkin_date="2026-09-10",
                    checkout_date="2026-09-12",
                ),
                bundle["member_headers"],
            ),
            ApiErrorId.ERR_STALE_HOTEL_VERSION,
        )

    def test_the_refused_booking_consumed_neither_points_nor_inventory(self, api):
        """Concurrency is the first check after pricing, so nothing downstream of it can have run.

        PRD: "Optimistic concurrency comes first: a mismatched `expected_hotel_version` is refused with `ERR_STALE_HOTEL_VERSION`."

        Design: Corner/cross-cutting complexity layers/award_booking_refuses_a_stale_hotel_version_and_accepts_the_refreshed_one
        """
        bundle = _versionlock_hotel_and_a_funded_member(api)
        stale_version = fx.hotel_version(api, bundle["hotel_id"])
        validate_success(
            api.refresh_hotel_performance(
                bundle["hotel_id"],
                fac.performance_refresh_payload(
                    trailing_12m_occupancy_pct=0.91, trailing_12m_adr_cents=34_000
                ),
                bundle["owner_headers"],
            )
        )
        api.create_redemption(
            fac.create_redemption_payload(
                bundle["member_id"],
                bundle["hotel_id"],
                stale_version,
                checkin_date="2026-09-10",
                checkout_date="2026-09-12",
            ),
            bundle["member_headers"],
        )
        assert_member(
            fx.read_member(api, bundle["member_id"]),
            point_balance=40_000,
            points_purchased_current_year=40_000,
        )
        _, meta = validate_paginated(
            api.list_redemptions(
                make_admin_headers(), params={"member_id": bundle["member_id"]}
            )
        )
        assert meta["total_count"] == 0, "a refused booking must not leave an award booking behind"

    def test_the_identical_booking_succeeds_once_the_version_is_re_read(self, api):
        """Nothing about the booking was illegal, so re-reading the row and resubmitting it works.

        PRD: "Note that this cannot be reduced to a state precondition — a second booking with a refreshed version is entirely legitimate business, because award inventory routinely permits more than one reservation on the same night."

        Design: Corner/cross-cutting complexity layers/award_booking_refuses_a_stale_hotel_version_and_accepts_the_refreshed_one
        """
        bundle = _versionlock_hotel_and_a_funded_member(api)
        stale_version = fx.hotel_version(api, bundle["hotel_id"])
        validate_success(
            api.refresh_hotel_performance(
                bundle["hotel_id"],
                fac.performance_refresh_payload(
                    trailing_12m_occupancy_pct=0.91, trailing_12m_adr_cents=34_000
                ),
                bundle["owner_headers"],
            )
        )
        api.create_redemption(
            fac.create_redemption_payload(
                bundle["member_id"],
                bundle["hotel_id"],
                stale_version,
                checkin_date="2026-09-10",
                checkout_date="2026-09-12",
            ),
            bundle["member_headers"],
        )
        fresh_version = validate_success(
            api.get_hotel(bundle["hotel_id"], bundle["care_headers"])
        )["version"]
        assert fresh_version == 3, "the re-read must hand back the version the refresh wrote"
        booked = validate_success(
            api.create_redemption(
                fac.create_redemption_payload(
                    bundle["member_id"],
                    bundle["hotel_id"],
                    fresh_version,
                    checkin_date="2026-09-10",
                    checkout_date="2026-09-12",
                ),
                bundle["member_headers"],
            ),
            expected_status=201,
        )
        assert_redemption(
            booked,
            fulfillment_status="HELD",
            reimbursement_status="NOT_DUE",
            points_charged=40_000,
            estimated_cents=0,
            settled_cents=0,
            season="STANDARD",
            points_per_night=20_000,
            award_allotment=1,
            cash_copay_cents=0,
            nights=2,
        )

    def test_consuming_the_award_room_is_itself_a_write_on_the_property(self, api):
        """The successful booking debits the member and moves the same version it had to match.

        PRD: "A `REDEEM` ledger entry is written carrying the negation of `points_charged` with `source_redemption_id` naming the booking, the member's `point_balance` falls by that amount, the property's `version` increments by one"

        Design: Corner/cross-cutting complexity layers/award_booking_refuses_a_stale_hotel_version_and_accepts_the_refreshed_one
        """
        bundle = _versionlock_hotel_and_a_funded_member(api)
        validate_success(
            api.refresh_hotel_performance(
                bundle["hotel_id"],
                fac.performance_refresh_payload(
                    trailing_12m_occupancy_pct=0.91, trailing_12m_adr_cents=34_000
                ),
                bundle["owner_headers"],
            )
        )
        booked = validate_success(
            api.create_redemption(
                fac.create_redemption_payload(
                    bundle["member_id"],
                    bundle["hotel_id"],
                    fx.hotel_version(api, bundle["hotel_id"]),
                    checkin_date="2026-09-10",
                    checkout_date="2026-09-12",
                ),
                bundle["member_headers"],
            ),
            expected_status=201,
        )
        assert (
            fx.hotel_version(api, bundle["hotel_id"]) == 4
        ), "holding the last award room must increment the property's version once more"
        assert_member(
            fx.read_member(api, bundle["member_id"]),
            point_balance=0,
            lifetime_points_earned=40_000,
        )
        rows, meta = validate_paginated(
            api.list_ledger_entries(
                make_admin_headers(), params={"member_id": bundle["member_id"]}
            )
        )
        assert meta["total_count"] == 2, "the purchase credit and the award debit must both exist"
        redeems = entries_of_type(rows, "REDEEM")
        assert len(redeems) == 1, "exactly one REDEEM entry must record the booking"
        assert_ledger_entry(
            redeems[0],
            entry_type="REDEEM",
            points=-40_000,
            member_id=bundle["member_id"],
            source_redemption_id=booked["id"],
            liability_unit_cost=600,
        )


class TestGoodwillAdjustmentRefusesAStaleMemberVersionAfterItsOwnFirstWrite:
    """The guarded endpoint is its own invalidator, so the token stops the duplicate."""

    def test_the_first_adjustment_carries_the_current_version_and_applies(self, api):
        """A grant read from the current version lands, and the response is the ledger entry it wrote.

        PRD: "On success a `GOODWILL` ledger entry is written carrying the signed `points` and the supplied `adjustment_reason`, the member's `point_balance` moves by that amount, the member's `version` increments, and the fund's valuation and posture are recomputed."

        Design: Corner/cross-cutting complexity layers/goodwill_adjustment_refuses_a_stale_member_version_after_its_own_first_write
        """
        bundle = _a_member_with_a_settled_purchase(api)
        as_read = validate_success(
            api.get_member(bundle["member_id"], bundle["care_headers"])
        )
        assert (
            as_read["point_balance"] == 20_000
        ), "the settled purchase must already be in the member's balance"
        entry = validate_success(
            api.create_point_adjustment(
                fac.point_adjustment_payload(
                    bundle["member_id"],
                    500,
                    as_read["version"],
                    adjustment_reason="Goodwill for a long check-in queue.",
                ),
                bundle["care_headers"],
            ),
            expected_status=201,
        )
        assert_ledger_entry(
            entry,
            entry_type="GOODWILL",
            points=500,
            member_id=bundle["member_id"],
            adjustment_reason="Goodwill for a long check-in queue.",
            liability_unit_cost=600,
        )

    def test_replaying_the_identical_payload_is_refused_on_the_version_alone(self, api):
        """Every field of the replay is legal; only the token the first write moved is wrong.

        PRD: "A request to write a point adjustment must carry `expected_member_version`, again a required field, whose value is the `version` of the target member as the operator last observed it. If `expected_member_version` does not equal that member's current `version`, the adjustment is rejected with `ERR_STALE_MEMBER_VERSION` (HTTP 412)."

        Design: Corner/cross-cutting complexity layers/goodwill_adjustment_refuses_a_stale_member_version_after_its_own_first_write
        """
        bundle = _a_member_with_a_settled_purchase(api)
        version_as_read = fx.member_version(api, bundle["member_id"])
        payload = fac.point_adjustment_payload(
            bundle["member_id"],
            500,
            version_as_read,
            adjustment_reason="Goodwill for a long check-in queue.",
        )
        validate_success(
            api.create_point_adjustment(payload, bundle["care_headers"]),
            expected_status=201,
        )
        validate_error(
            api.create_point_adjustment(payload, bundle["care_headers"]),
            ApiErrorId.ERR_STALE_MEMBER_VERSION,
        )

    def test_exactly_one_grant_landed_so_the_refused_replay_wrote_nothing(self, api):
        """A double credit would be invisible in the state machine, which is why the token is the only guard.

        PRD: "two goodwill grants of the same size to the same member are both perfectly legal, so the version mismatch is the only signal available that the operator was looking at a balance and a tier which have since moved."

        Design: Corner/cross-cutting complexity layers/goodwill_adjustment_refuses_a_stale_member_version_after_its_own_first_write
        """
        bundle = _a_member_with_a_settled_purchase(api)
        version_as_read = fx.member_version(api, bundle["member_id"])
        payload = fac.point_adjustment_payload(
            bundle["member_id"],
            500,
            version_as_read,
            adjustment_reason="Goodwill for a long check-in queue.",
        )
        validate_success(
            api.create_point_adjustment(payload, bundle["care_headers"]),
            expected_status=201,
        )
        api.create_point_adjustment(payload, bundle["care_headers"])
        after = validate_success(
            api.get_member(bundle["member_id"], bundle["care_headers"])
        )
        assert (
            after["version"] == version_as_read + 1
        ), "one accepted adjustment and one refused replay must move the version exactly once"
        assert_member(after, point_balance=20_500)
        rows, meta = validate_paginated(
            api.list_ledger_entries(
                make_admin_headers(),
                params={"member_id": bundle["member_id"], "entry_type": "GOODWILL"},
            )
        )
        assert meta["total_count"] == 1, "only one GOODWILL entry may exist"
        assert rows[0]["points"] == 500, "the single grant must carry the requested amount"

    def test_a_negative_adjustment_is_legal_on_a_freshly_read_version(self, api):
        """The signed field runs both ways, and the correction needs the version the first grant produced.

        PRD: "An administrator or a `MemberCareAgent` may move a member's balance directly, supplying `member_id`, a signed `points` value, an `adjustment_reason` and `expected_member_version`."

        Design: Corner/cross-cutting complexity layers/goodwill_adjustment_refuses_a_stale_member_version_after_its_own_first_write
        """
        bundle = _a_member_with_a_settled_purchase(api)
        first_version = fx.member_version(api, bundle["member_id"])
        validate_success(
            api.create_point_adjustment(
                fac.point_adjustment_payload(bundle["member_id"], 500, first_version),
                bundle["care_headers"],
            ),
            expected_status=201,
        )
        second_version = fx.member_version(api, bundle["member_id"])
        clawback = validate_success(
            api.create_point_adjustment(
                fac.point_adjustment_payload(
                    bundle["member_id"],
                    -200,
                    second_version,
                    adjustment_reason="Correcting an over-grant.",
                ),
                make_admin_headers("op-admin-mv"),
            ),
            expected_status=201,
        )
        assert_ledger_entry(
            clawback,
            entry_type="GOODWILL",
            points=-200,
            member_id=bundle["member_id"],
            adjustment_reason="Correcting an over-grant.",
        )
        final = validate_success(
            api.get_member(bundle["member_id"], bundle["care_headers"])
        )
        assert_member(final, point_balance=20_300)
        assert (
            final["version"] == second_version + 1
        ), "the accepted clawback must increment the member's version exactly once"

    def test_the_adjustment_response_is_a_ledger_entry_rather_than_the_member(self, api):
        """The body names the entry that was written, not the resource the payload addressed.

        PRD: "This is the only endpoint whose response body is a ledger entry rather than the resource named in the path."

        Design: Corner/cross-cutting complexity layers/goodwill_adjustment_refuses_a_stale_member_version_after_its_own_first_write
        """
        bundle = _a_member_with_a_settled_purchase(api)
        entry = validate_success(
            api.create_point_adjustment(
                fac.point_adjustment_payload(
                    bundle["member_id"], 500, fx.member_version(api, bundle["member_id"])
                ),
                bundle["care_headers"],
            ),
            expected_status=201,
        )
        assert entry["member_id"] == bundle["member_id"], "the entry must name the member it moved"
        assert entry["entry_type"] == "GOODWILL", "the entry must be typed as a goodwill movement"
        for member_only_field in ("point_balance", "elite_tier", "qualifying_nights_ytd"):
            assert member_only_field not in entry, (
                "the adjustment response must not be the member resource, but it carries "
                f"{member_only_field}"
            )


class TestFeeLedgerAtExactlyTheThresholdStaysActiveAndOneCentMoreDoesNot:
    """A strict greater-than on a cumulative balance, evaluated after posting and after adjustment."""

    def test_a_ledger_of_exactly_the_threshold_leaves_the_property_active(self, api):
        """The first posting lands the ledger on the threshold to the cent, and the comparison is strict.

        PRD: "if the property's recomputed `fee_ledger_balance_cents` is strictly greater than 250,000 cents — that is, above two thousand five hundred dollars of outstanding fee — the property moves `ACTIVE → FEE_DELINQUENT` and its `version` increments. The comparison is strictly greater-than: a balance of exactly 250,000 cents leaves the property `ACTIVE`."

        Design: Corner/cross-cutting complexity layers/fee_ledger_at_exactly_the_threshold_stays_active_and_one_cent_more_does_not
        """
        bundle = _threshold_grand_with_two_unposted_stays(api)
        posted = fx.post_stay(
            api, bundle["at_threshold_id"], headers=bundle["owner_headers"]
        )
        assert_stay(
            posted,
            status="POSTED_QUALIFYING",
            fee_cents=250_000,
            base_points=500_000,
            bonus_points=0,
            tier_at_checkin="BASE",
            nights=1,
        )
        assert_hotel(
            fx.read_hotel(api, bundle["hotel_id"]),
            status="ACTIVE",
            fee_ledger_cents=250_000,
        )

    def test_one_further_cent_of_fee_flips_the_property_into_delinquency(self, api):
        """A twenty-cent stay assesses a single cent, and that cent is the whole difference.

        PRD: "Per stay, the fee is the stay's `room_revenue_cents` multiplied by the property's `program_fee_pct`, rounded half up to the whole cent, and stored on the stay as `program_fee_assessed_cents`"

        Design: Corner/cross-cutting complexity layers/fee_ledger_at_exactly_the_threshold_stays_active_and_one_cent_more_does_not
        """
        bundle = _threshold_grand_with_two_unposted_stays(api)
        fx.post_stay(api, bundle["at_threshold_id"], headers=bundle["owner_headers"])
        second = fx.post_stay(
            api, bundle["one_cent_more_id"], headers=bundle["owner_headers"]
        )
        # Base earning is "the stay's `room_revenue_cents` multiplied by the rate
        # plan's `base_earn_rate_per_dollar`, divided by one hundred to convert cents
        # into whole dollars, with the result rounded **down** to a whole point", so a
        # twenty-cent night on the transient plan's ten points per dollar earns
        # 20 * 10 / 100 = 2 points, not none.
        assert_stay(second, status="POSTED_QUALIFYING", fee_cents=1, base_points=2, nights=1)
        assert_hotel(
            fx.read_hotel(api, bundle["hotel_id"]),
            status="FEE_DELINQUENT",
            fee_ledger_cents=250_001,
        )

    def test_the_adjustment_path_also_re_evaluates_the_trigger(self, api):
        """Restating the offending stay down to nothing moves the ledger by the fee delta.

        PRD: "The stay's `program_fee_assessed_cents` is recomputed on the revised revenue and the property's `fee_ledger_balance_cents` moves by the fee delta"

        Design: Corner/cross-cutting complexity layers/fee_ledger_at_exactly_the_threshold_stays_active_and_one_cent_more_does_not
        """
        bundle = _threshold_grand_with_two_unposted_stays(api)
        fx.post_stay(api, bundle["at_threshold_id"], headers=bundle["owner_headers"])
        fx.post_stay(api, bundle["one_cent_more_id"], headers=bundle["owner_headers"])
        disputed = validate_success(
            api.dispute_stay(
                bundle["one_cent_more_id"],
                fac.dispute_stay_payload(dispute_reason="Rate loaded with a stray cent."),
                bundle["member_headers"],
            )
        )
        assert disputed["status"] == "DISPUTED", "the member's dispute must open the stay for review"
        adjusted = fx.adjust_stay(api, bundle["one_cent_more_id"], room_revenue_cents=0)
        assert_stay(adjusted, status="ADJUSTED", fee_cents=0, base_points=0)
        assert_hotel(
            fx.read_hotel(api, bundle["hotel_id"]), fee_ledger_cents=250_000
        )
        assert_member(
            fx.read_member(api, bundle["member_id"]),
            point_balance=500_000,
        )

    def test_falling_back_to_the_threshold_does_not_restore_the_posture(self, api):
        """Delinquency is one-directional: only a settled batch brings a property back.

        PRD: "The reverse move happens only through settlement: at the end of a batch payment, if the property's `fee_ledger_balance_cents` after that settlement stands at or below zero, a property that was `FEE_DELINQUENT` returns to `ACTIVE` and its `version` increments again."

        Design: Corner/cross-cutting complexity layers/fee_ledger_at_exactly_the_threshold_stays_active_and_one_cent_more_does_not
        """
        bundle = _threshold_grand_with_two_unposted_stays(api)
        fx.post_stay(api, bundle["at_threshold_id"], headers=bundle["owner_headers"])
        fx.post_stay(api, bundle["one_cent_more_id"], headers=bundle["owner_headers"])
        fx.dispute_stay(
            api,
            bundle["one_cent_more_id"],
            reason="Rate loaded with a stray cent.",
            headers=bundle["member_headers"],
        )
        fx.adjust_stay(api, bundle["one_cent_more_id"], room_revenue_cents=0)
        assert_hotel(
            fx.read_hotel(api, bundle["hotel_id"]),
            status="FEE_DELINQUENT",
            fee_ledger_cents=250_000,
        )

    def test_a_delinquent_property_still_opens_a_reimbursement_batch(self, api):
        """Arrears are collected through the batch offset, so batching is not shut off.

        PRD: "Booking an award stay and opening a reimbursement batch require status either `ACTIVE` or `FEE_DELINQUENT`, refusing only `ONBOARDING` and `TERMINATED`"

        Design: Corner/cross-cutting complexity layers/fee_ledger_at_exactly_the_threshold_stays_active_and_one_cent_more_does_not
        """
        bundle = _threshold_grand_with_two_unposted_stays(api)
        fx.post_stay(api, bundle["at_threshold_id"], headers=bundle["owner_headers"])
        fx.post_stay(api, bundle["one_cent_more_id"], headers=bundle["owner_headers"])
        delinquent = fx.read_hotel(api, bundle["hotel_id"])
        assert (
            delinquent["status"] == "FEE_DELINQUENT"
        ), "the property must be delinquent before this check means anything"
        batch = validate_success(
            api.create_reimbursement_batch(
                fac.create_reimbursement_batch_payload(bundle["hotel_id"], "2026-06"),
                bundle["owner_headers"],
            ),
            expected_status=201,
        )
        assert batch["status"] == "OPEN", "a delinquent property must still be able to open a batch"
        assert (
            batch["hotel_id"] == bundle["hotel_id"]
        ), "the batch must belong to the delinquent property"


class TestHotelFeeLedgerReconcilesAfterCreateAdjustAndVoidOfItsSources:
    """The ledger is a sum over already-rounded per-stay figures, re-derived at three life events."""

    def test_two_postings_sum_the_already_rounded_per_stay_fees(self, api):
        """One fee rounds down and the other is exact, and the ledger is their sum rather than a re-rounded total.

        PRD: "The rounding order is pinned and it matters: round each stay's fee to the cent first, then add the rounded figures."

        Design: Corner/cross-cutting complexity layers/hotel_fee_ledger_reconciles_after_create_adjust_and_void_of_its_sources
        """
        bundle = _reconcile_house_with_two_unposted_stays(api)
        first = fx.post_stay(api, bundle["first_id"])
        second = fx.post_stay(api, bundle["second_id"])
        assert_stay(first, status="POSTED_QUALIFYING", fee_cents=617, base_points=1_234, nights=2)
        assert_stay(second, status="POSTED_QUALIFYING", fee_cents=1_000, base_points=2_000, nights=3)
        assert_hotel(
            fx.read_hotel(api, bundle["hotel_id"]),
            status="ACTIVE",
            fee_ledger_cents=1_617,
        )

    def test_a_disputed_stay_stays_in_the_population(self, api):
        """Disputing freezes the earnings but does not remove the stay from the fee sum.

        PRD: "The property's `fee_ledger_balance_cents` is then re-derived as the sum of the **already-rounded** per-stay figures across all of that property's stays whose `status` is one of `POSTED_QUALIFYING`, `POSTED_NON_QUALIFYING`, `DISPUTED` or `ADJUSTED`"

        Design: Corner/cross-cutting complexity layers/hotel_fee_ledger_reconciles_after_create_adjust_and_void_of_its_sources
        """
        bundle = _reconcile_house_with_two_unposted_stays(api)
        fx.post_stay(api, bundle["first_id"])
        fx.post_stay(api, bundle["second_id"])
        disputed = fx.dispute_stay(
            api,
            bundle["first_id"],
            reason="Guest challenged the room rate.",
            headers=bundle["care_headers"],
        )
        assert disputed["status"] == "DISPUTED", "the care agent's dispute must be accepted"
        assert_hotel(
            fx.read_hotel(api, bundle["hotel_id"]), fee_ledger_cents=1_617
        )

    def test_the_restated_stay_replaces_its_own_figure_in_the_sum(self, api):
        """Doubling the revenue rounds the fee the other way, and the new figure replaces the old before the sum.

        PRD: "An additional `EARN_BASE` ledger entry is written whose `points` is the new base award minus the old base award, and it is written only when that difference is non-zero."

        Design: Corner/cross-cutting complexity layers/hotel_fee_ledger_reconciles_after_create_adjust_and_void_of_its_sources
        """
        bundle = _reconcile_house_with_two_unposted_stays(api)
        fx.post_stay(api, bundle["first_id"])
        fx.post_stay(api, bundle["second_id"])
        fx.dispute_stay(
            api,
            bundle["first_id"],
            reason="Guest challenged the room rate.",
            headers=bundle["care_headers"],
        )
        adjusted = fx.adjust_stay(api, bundle["first_id"], room_revenue_cents=24_690)
        assert_stay(adjusted, status="ADJUSTED", fee_cents=1_235, base_points=2_469)
        assert_hotel(
            fx.read_hotel(api, bundle["hotel_id"]), fee_ledger_cents=2_235
        )

    def test_a_voided_stay_leaves_the_population_entirely(self, api):
        """The void credits its fee back, so the ledger keeps only the restated stay's figure.

        PRD: "the stay's `program_fee_assessed_cents` is credited back, so the property's `fee_ledger_balance_cents` falls by that amount as the stay leaves the fee-ledger's status filter set"

        Design: Corner/cross-cutting complexity layers/hotel_fee_ledger_reconciles_after_create_adjust_and_void_of_its_sources
        """
        bundle = _reconcile_house_with_two_unposted_stays(api)
        fx.post_stay(api, bundle["first_id"])
        fx.post_stay(api, bundle["second_id"])
        fx.dispute_stay(
            api,
            bundle["first_id"],
            reason="Guest challenged the room rate.",
            headers=bundle["care_headers"],
        )
        fx.adjust_stay(api, bundle["first_id"], room_revenue_cents=24_690)
        voided = fx.void_stay(api, bundle["second_id"], reason="Duplicate folio.")
        assert voided["status"] == "VOID", "the second stay must be voided"
        assert_hotel(
            fx.read_hotel(api, bundle["hotel_id"]), fee_ledger_cents=1_235
        )

    def test_the_member_balance_follows_the_same_three_events(self, api):
        """Every fee movement had a points counterpart, and the balance is the signed sum of all four entries.

        PRD: "stays in `PENDING_POSTING` and `VOID` are excluded, and there is no monthly window, the ledger spans all time"

        Design: Corner/cross-cutting complexity layers/hotel_fee_ledger_reconciles_after_create_adjust_and_void_of_its_sources
        """
        bundle = _reconcile_house_with_two_unposted_stays(api)
        fx.post_stay(api, bundle["first_id"])
        fx.post_stay(api, bundle["second_id"])
        fx.dispute_stay(
            api,
            bundle["first_id"],
            reason="Guest challenged the room rate.",
            headers=bundle["care_headers"],
        )
        fx.adjust_stay(api, bundle["first_id"], room_revenue_cents=24_690)
        fx.void_stay(api, bundle["second_id"], reason="Duplicate folio.")
        member = fx.read_member(api, bundle["member_id"])
        assert_member(member, point_balance=2_469, elite_tier="BASE")
        assert member["qualifying_nights_ytd"] == 0, (
            "an ADJUSTED stay and a VOID stay both sit outside the tier-counting set, so no "
            "qualifying night may remain"
        )
        rows, _ = validate_paginated(
            api.list_ledger_entries(
                make_admin_headers(), params={"member_id": bundle["member_id"]}
            )
        )
        assert sum(row["points"] for row in rows) == 2_469, (
            "the member's balance must equal the signed sum of every entry written across the "
            "posting, the adjustment and the void"
        )


class TestOnePostingIsAlreadyVisibleInEveryDerivedReadThatFollowsIt:
    """One write, then four reads: the member, the property, the fund and the ledger all move together."""

    def test_the_fund_before_the_posting_reflects_only_the_purchased_points(self, api):
        """The baseline is the settled purchase alone, and the stay is still waiting to be posted.

        PRD: "The `point_liability_cents` is that outstanding total, valued at 600 cents per thousand points, multiplied by one minus `breakage_rate_pct`, rounded half up to whole cents."

        Design: Corner/consistency model/one_posting_is_already_visible_in_every_derived_read_that_follows_it
        """
        bundle = _immediate_inn_with_one_unposted_stay(api)
        assert (
            bundle["stay"]["status"] == "PENDING_POSTING"
        ), "the captured stay must still be unposted at the baseline"
        assert_fund(
            fx.read_fund(api),
            cash_cents=25_000,
            outstanding_points=20_000,
            liability_cents=9_600,
            solvency_ratio=2.6042,
            status="HEALTHY",
            breakage_rate_pct=0.20,
        )

    def test_the_posting_response_already_carries_its_own_derived_figures(self, api):
        """The write's own body is the first derived read, and it is complete before any follow-up call.

        PRD: "`base_points_awarded` is the stay's `room_revenue_cents` multiplied by the rate plan's `base_earn_rate_per_dollar`, divided by one hundred to convert cents into whole dollars, with the result rounded **down** to a whole point."

        Design: Corner/consistency model/one_posting_is_already_visible_in_every_derived_read_that_follows_it
        """
        bundle = _immediate_inn_with_one_unposted_stay(api)
        posted = fx.post_stay(
            api, bundle["stay"]["id"], headers=bundle["owner_headers"]
        )
        assert_stay(
            posted,
            status="POSTED_QUALIFYING",
            base_points=1_234,
            bonus_points=0,
            fee_cents=617,
            tier_at_checkin="BASE",
            nights=2,
            room_revenue_cents=12_345,
        )

    def test_the_member_read_that_follows_the_posting_shows_the_new_balance(self, api):
        """No settling delay: the very next member read carries the awarded points and the counted nights.

        PRD: "the member's `point_balance` and `lifetime_points_earned` are recomputed. Because the stay has entered `POSTED_QUALIFYING`, the member's `qualifying_revenue_cents_ytd` is recomputed, and the member's `qualifying_nights_ytd` is recomputed as well whenever the stay's rate plan has `counts_toward_elite` true."

        Design: Corner/consistency model/one_posting_is_already_visible_in_every_derived_read_that_follows_it
        """
        bundle = _immediate_inn_with_one_unposted_stay(api)
        fx.post_stay(api, bundle["stay"]["id"], headers=bundle["owner_headers"])
        member = validate_success(
            api.get_member(bundle["member_id"], bundle["member_headers"])
        )
        assert_member(
            member,
            point_balance=21_234,
            lifetime_points_earned=21_234,
            qualifying_nights=2,
            elite_tier="BASE",
        )

    def test_the_property_read_that_follows_the_posting_shows_the_new_fee_ledger(self, api):
        """The same posting is visible on the other side of the transaction, as fee owed by the property.

        PRD: "The property's `fee_ledger_balance_cents` is then re-derived as the sum of the **already-rounded** per-stay figures across all of that property's stays whose `status` is one of `POSTED_QUALIFYING`, `POSTED_NON_QUALIFYING`, `DISPUTED` or `ADJUSTED`"

        Design: Corner/consistency model/one_posting_is_already_visible_in_every_derived_read_that_follows_it
        """
        bundle = _immediate_inn_with_one_unposted_stay(api)
        fx.post_stay(api, bundle["stay"]["id"], headers=bundle["owner_headers"])
        assert_hotel(
            validate_success(
                api.get_hotel(bundle["hotel_id"], bundle["owner_headers"])
            ),
            status="ACTIVE",
            fee_ledger_cents=617,
        )

    def test_the_fund_and_the_ledger_both_include_the_posting_immediately(self, api):
        """The liability is recomputed off the raised outstanding total, and the earning entry is already listable.

        PRD: "Its `outstanding_points` is the signed sum of `points` across **every** ledger entry of every member, with no status filter and no exclusion list"

        Design: Corner/consistency model/one_posting_is_already_visible_in_every_derived_read_that_follows_it
        """
        bundle = _immediate_inn_with_one_unposted_stay(api)
        fx.post_stay(api, bundle["stay"]["id"], headers=bundle["owner_headers"])
        assert_fund(
            validate_success(api.get_program_fund(make_auditor_headers("au-imi-1"))),
            cash_cents=25_000,
            outstanding_points=21_234,
            liability_cents=10_192,
            solvency_ratio=2.4529,
            status="HEALTHY",
        )
        rows, meta = validate_paginated(
            api.list_ledger_entries(
                make_admin_headers(), params={"member_id": bundle["member_id"]}
            )
        )
        assert meta["total_count"] == 2, (
            "the settled purchase and the posting must both be listable straight after the write, "
            f"got {meta['total_count']} entries"
        )
        assert_ledger_entry(
            entries_of_type(rows, "PURCHASE")[0],
            points=20_000,
            member_id=bundle["member_id"],
            source_purchase_id=bundle["purchase"]["id"],
        )
        assert_ledger_entry(
            entries_of_type(rows, "EARN_BASE")[0],
            points=1_234,
            member_id=bundle["member_id"],
            source_stay_id=bundle["stay"]["id"],
            liability_unit_cost=600,
        )

    def test_a_second_read_with_no_write_between_them_is_identical(self, api):
        """Reads are derived deterministically, so repeating one without an intervening write changes nothing.

        PRD: "That whole derivation re-runs from scratch at the end of every request that writes a ledger entry or moves programme cash, so the fund is never stale, and it can be re-derived on demand by an administrator or the `ProgramAuditor`, which also sets `last_revalued_at` to the clock's current instant and increments the fund's `version`."

        Design: Corner/consistency model/one_posting_is_already_visible_in_every_derived_read_that_follows_it
        """
        bundle = _immediate_inn_with_one_unposted_stay(api)
        fx.post_stay(api, bundle["stay"]["id"], headers=bundle["owner_headers"])
        first = fx.read_fund(api)
        second = fx.read_fund(api)
        for field in (
            "cash_balance_cents",
            "outstanding_points",
            "point_liability_cents",
            "solvency_ratio",
            "status",
            "breakage_rate_pct",
            "last_revalued_at",
        ):
            assert first[field] == second[field], (
                f"two fund reads with no write between them disagree on {field}: "
                f"{first[field]} then {second[field]}"
            )
        assert second["last_revalued_at"] is None, (
            "no revaluation was ever requested, so the timestamp must still be unset even "
            "though the derived figures have moved"
        )
