"""What a create returns, what a read gives back, which omitted inputs fall back to
a declared default, and which malformed or dangling references are refused."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_append_only_entity_shape,
    assert_created_and_updated_match,
    assert_fund,
    assert_hotel,
    assert_hotel_counters_zero,
    assert_ledger_entry,
    assert_member,
    assert_member_counters_zero,
    assert_purchase,
    assert_stay,
    assert_versioned_entity_shape,
    collect_all,
    factories as fac,
    fixtures as fx,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_admin_headers,
    make_auditor_headers,
    make_care_agent_headers,
    read_entity,
    validate_error,
    validate_paginated,
    validate_success,
)


# ----------------------------------------------------------------------
# Scenario builders
# ----------------------------------------------------------------------
def _three_properties_left_in_onboarding(api):
    """Three enrolled properties in three different market tiers, none activated."""
    alpha = fx.create_onboarding_hotel(
        api,
        name="Alpha House",
        brand_code="ALP",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=100,
        trailing_12m_occupancy_pct=0.80,
        trailing_12m_adr_cents=20_000,
    )
    bravo = fx.create_onboarding_hotel(
        api,
        name="Bravo Lodge",
        brand_code="BRV",
        market_tier="RESORT",
        program_fee_pct=0.06,
        rooms_count=120,
        trailing_12m_occupancy_pct=0.81,
        trailing_12m_adr_cents=25_000,
    )
    charlie = fx.create_onboarding_hotel(
        api,
        name="Charlie Inn",
        brand_code="CHR",
        market_tier="SELECT",
        program_fee_pct=0.04,
        rooms_count=80,
        trailing_12m_occupancy_pct=0.79,
        trailing_12m_adr_cents=15_000,
    )
    return {"alpha": alpha, "bravo": bravo, "charlie": charlie}


def _defaults_court_ready_for_captures(api):
    """An ACTIVE property with one transient rate plan, with the logical clock parked
    at a mid-morning instant on the fifth of August."""
    fx.set_clock(api, "2026-08-05T09:30:00Z")
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR",
        rate_category="TRANSIENT",
        name="Defaults Court",
        brand_code="DFC",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=110,
        trailing_12m_occupancy_pct=0.82,
        trailing_12m_adr_cents=30_000,
    )
    return bundle


def _computed_arms_with_a_silver_guest(api):
    """A guest lifted to SILVER by one posted ten-night transient stay, at a property
    assessing a five-percent programme fee."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR",
        rate_category="TRANSIENT",
        name="Computed Arms",
        brand_code="CMP",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=140,
        trailing_12m_occupancy_pct=0.82,
        trailing_12m_adr_cents=30_000,
    )
    member = fx.enroll_member(api, full_name="Rasmus Holm", enrollment_date="2026-01-05")
    first = fx.capture_stay(
        api,
        bundle["hotel"]["id"],
        member["id"],
        bundle["rate_plan"]["id"],
        "2026-07-01",
        "2026-07-11",
        100_000,
    )
    fx.post_stay(api, first["id"])

    bundle["member"] = member
    bundle["first_stay"] = first
    return bundle


def _constraint_hall_ready_for_refusals(api):
    """An ACTIVE property with a single transient rate plan and one BASE member, used
    only as a landing place for deliberately malformed requests."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR",
        rate_category="TRANSIENT",
        name="Constraint Hall",
        brand_code="CNH",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=130,
        trailing_12m_occupancy_pct=0.82,
        trailing_12m_adr_cents=30_000,
    )
    bundle["member"] = fx.enroll_member(api, full_name="Nour Bakri")
    return bundle


def _member_funded_by_one_settled_direct_purchase(api):
    """A member holding twenty thousand points that arrived as a settled direct
    purchase, which is exactly one ledger row."""
    funded = fx.member_funded_by_purchase(api, 20_000, channel="DIRECT_PURCHASE")
    return funded


# ----------------------------------------------------------------------
# Property enrolment
# ----------------------------------------------------------------------
class TestPropertyEnrolmentBody:
    def test_a_newly_enrolled_property_carries_every_counter_at_zero(self, api):
        """Enrolment answers 201 with a body whose five running counters are all zero,
        whose status is the onboarding posture and whose exit reason is still null.

        PRD: "A newly enrolled property lands in `ONBOARDING` with
        `fee_ledger_balance_cents`, `reimbursement_owed_cents`,
        `benefit_recovery_owed_cents`, `benefit_denial_count` and
        `blackout_days_used_current_year` all at 0, `termination_reason` null, and
        `version` at 1."

        Design: Corner/entities/hotel_create_returns_201_with_onboarding_status_and_zero_counters
        """
        response = api.create_hotel(
            fac.create_hotel_payload(
                name="Northgate Plaza",
                brand_code="NGP",
                market_tier="URBAN",
                program_fee_pct=0.05,
                rooms_count=180,
                trailing_12m_occupancy_pct=0.82,
                trailing_12m_adr_cents=30_000,
            ),
            make_admin_headers(),
        )

        hotel = validate_success(response, 201)
        assert response.json()["response_type"] == "object", (
            "a single resource answers with an object envelope"
        )
        assert_hotel(hotel, status="ONBOARDING", version=1)
        assert_hotel_counters_zero(hotel)
        assert hotel["termination_reason"] is None, (
            f"termination_reason should start null, got {hotel['termination_reason']}"
        )

    def test_the_seven_supplied_inputs_are_stored_exactly_as_sent(self, api):
        """Every declared input of the enrolment payload is echoed back unchanged, and
        the envelope carries the two request-identifying meta fields.

        PRD: "A `ProgramAdministrator` enrols a property by supplying its `name` (a
        non-empty trade name of 1 to 120 characters), its `brand_code` (exactly three
        uppercase letters identifying the chain the property flies), its `market_tier`
        — one of `URBAN`, `RESORT` or `SELECT`, which is the key that later decides the
        peak redemption surcharge — its `program_fee_pct`, its `rooms_count` of
        sellable inventory, and the two trailing-twelve-month performance figures
        `trailing_12m_occupancy_pct` and `trailing_12m_adr_cents`."

        Design: Corner/entities/hotel_create_returns_201_with_onboarding_status_and_zero_counters
        """
        response = api.create_hotel(
            fac.create_hotel_payload(
                name="Northgate Plaza",
                brand_code="NGP",
                market_tier="URBAN",
                program_fee_pct=0.05,
                rooms_count=180,
                trailing_12m_occupancy_pct=0.82,
                trailing_12m_adr_cents=30_000,
            ),
            make_admin_headers(),
        )

        hotel = validate_success(response, 201)
        assert hotel["name"] == "Northgate Plaza", hotel["name"]
        assert hotel["brand_code"] == "NGP", hotel["brand_code"]
        assert hotel["market_tier"] == "URBAN", hotel["market_tier"]
        assert abs(hotel["program_fee_pct"] - 0.05) < 1e-9, hotel["program_fee_pct"]
        assert hotel["rooms_count"] == 180, hotel["rooms_count"]
        assert abs(hotel["trailing_12m_occupancy_pct"] - 0.82) < 1e-9, (
            hotel["trailing_12m_occupancy_pct"]
        )
        assert hotel["trailing_12m_adr_cents"] == 30_000, hotel["trailing_12m_adr_cents"]
        meta = response.json()["meta"]
        assert meta["api_request_id"].startswith("req_"), meta["api_request_id"]
        assert is_iso8601_timestamp(meta["api_request_timestamp"]), (
            meta["api_request_timestamp"]
        )
        assert_versioned_entity_shape(hotel)


# ----------------------------------------------------------------------
# Member enrolment, read back
# ----------------------------------------------------------------------
class TestMemberEnrolmentRow:
    def test_the_read_returns_exactly_what_enrolment_stored(self, api):
        """A care agent enrols the member and an administrator reads the row back: the
        same address, display name and enrolment date, at the entry tier.

        PRD: "A new member starts at `elite_tier` `BASE` with `qualifying_nights_ytd`,
        `qualifying_revenue_cents_ytd`, `point_balance`, `lifetime_points_earned` and
        `points_purchased_current_year` all at 0."

        Design: Corner/entities/member_read_returns_the_stored_enrollment_row
        """
        created = validate_success(
            api.create_member(
                fac.create_member_payload(
                    email="rt1@example.com",
                    full_name="Ines Vidal",
                    enrollment_date="2026-01-05",
                ),
                make_care_agent_headers("care-rt-01"),
            ),
            201,
        )

        member = read_entity(api.get_member, created["id"], make_admin_headers())

        assert member["email"] == "rt1@example.com", member["email"]
        assert member["full_name"] == "Ines Vidal", member["full_name"]
        assert member["enrollment_date"] == "2026-01-05", member["enrollment_date"]
        assert_member_counters_zero(member)
        assert_member(member, elite_tier="BASE", version=1)

    def test_the_enrolment_row_carries_the_mutable_common_fields(self, api):
        """A member is a versioned resource, so the row carries both timestamps and a
        version that opens at one.

        PRD: "Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp
        in the same format that is refreshed on every mutation, and `version`, an
        integer that starts at 1 when the row is created and increments by exactly 1 on
        every mutation of that row."

        Design: Corner/entities/member_read_returns_the_stored_enrollment_row
        """
        created = validate_success(
            api.create_member(
                fac.create_member_payload(
                    email="rt2@example.com",
                    full_name="Ines Vidal",
                    enrollment_date="2026-01-05",
                ),
                make_care_agent_headers("care-rt-01"),
            ),
            201,
        )

        member = read_entity(api.get_member, created["id"], make_admin_headers())

        assert_versioned_entity_shape(member)
        assert_created_and_updated_match(member)


# ----------------------------------------------------------------------
# Paging and filtering the property collection
# ----------------------------------------------------------------------
class TestPropertyCollectionPaging:
    def test_a_two_row_window_walks_the_three_properties(self, api):
        """The first window returns two of three rows and advertises more; the second
        window returns the remaining row and closes the walk.

        PRD: "The `meta` object of every list response carries `limit`, `offset`,
        `total_count` and `has_more`."

        Design: Corner/entities/hotel_list_paginates_with_total_count_and_has_more
        """
        _three_properties_left_in_onboarding(api)
        admin = make_admin_headers()

        first_rows, first_meta = validate_paginated(
            api.list_hotels(admin, {"limit": 2, "offset": 0})
        )
        second_rows, second_meta = validate_paginated(
            api.list_hotels(admin, {"limit": 2, "offset": 2})
        )

        assert len(first_rows) == 2, f"expected two rows in the first window, got {len(first_rows)}"
        assert first_meta["total_count"] == 3, first_meta["total_count"]
        assert first_meta["has_more"] is True, "two of three rows leaves more to fetch"
        assert first_meta["limit"] == 2 and first_meta["offset"] == 0, first_meta
        assert len(second_rows) == 1, f"expected one row in the second window, got {len(second_rows)}"
        assert second_meta["total_count"] == 3, second_meta["total_count"]
        assert second_meta["has_more"] is False, "the third row closes the collection"
        assert second_meta["offset"] == 2, second_meta["offset"]
        walked = [row["id"] for row in first_rows] + [row["id"] for row in second_rows]
        assert len(set(walked)) == 3, f"the two windows must not overlap, got {walked}"

    def test_two_equality_filters_narrow_the_collection_to_one_row(self, api):
        """An auditor asking for onboarding resort properties gets exactly the resort,
        and the untouched page size reports the declared default.

        PRD: "The property collection filters on `status` and `market_tier`."

        Design: Corner/entities/hotel_list_paginates_with_total_count_and_has_more
        """
        bundle = _three_properties_left_in_onboarding(api)

        rows, meta = validate_paginated(
            api.list_hotels(
                make_auditor_headers(),
                {"status": "ONBOARDING", "market_tier": "RESORT"},
            )
        )

        assert len(rows) == 1, f"only Bravo Lodge is an onboarding resort, got {len(rows)}"
        assert rows[0]["id"] == bundle["bravo"]["id"], rows[0]["name"]
        assert rows[0]["market_tier"] == "RESORT", rows[0]["market_tier"]
        assert meta["total_count"] == 1, meta["total_count"]
        assert meta["has_more"] is False, meta["has_more"]
        assert meta["limit"] == 10, (
            f"an omitted page size falls back to the declared default of ten, got {meta['limit']}"
        )
        assert meta["offset"] == 0, meta["offset"]


# ----------------------------------------------------------------------
# Dangling identifiers
# ----------------------------------------------------------------------
class TestUnknownIdentifiersAreEntitySpecific:
    def test_each_of_the_twelve_single_reads_names_its_own_entity(self, api):
        """Twelve reads of an identifier that exists in no collection answer with twelve
        different error identifiers, so the caller learns which reference failed.

        PRD: "**Existence** of every identifier, resolved left to right along the path
        and then across body foreign keys, yielding `ERR_HOTEL_NOT_FOUND`,
        `ERR_RATE_PLAN_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_STAY_NOT_FOUND`,
        `ERR_REDEMPTION_NOT_FOUND`, `ERR_DELIVERY_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`,
        `ERR_BLACKOUT_WINDOW_NOT_FOUND`, `ERR_PARTNER_NOT_FOUND`,
        `ERR_PURCHASE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND` or
        `ERR_PRICING_ROW_NOT_FOUND` respectively."

        Design: Corner/entities/unknown_identifiers_return_entity_specific_not_found_errors
        """
        admin = make_admin_headers()
        probes = (
            (api.get_hotel, ApiErrorId.ERR_HOTEL_NOT_FOUND),
            (api.get_rate_plan, ApiErrorId.ERR_RATE_PLAN_NOT_FOUND),
            (api.get_member, ApiErrorId.ERR_MEMBER_NOT_FOUND),
            (api.get_stay, ApiErrorId.ERR_STAY_NOT_FOUND),
            (api.get_redemption, ApiErrorId.ERR_REDEMPTION_NOT_FOUND),
            (api.get_benefit_delivery, ApiErrorId.ERR_DELIVERY_NOT_FOUND),
            (api.get_reimbursement_batch, ApiErrorId.ERR_BATCH_NOT_FOUND),
            (api.get_blackout_window, ApiErrorId.ERR_BLACKOUT_WINDOW_NOT_FOUND),
            (api.get_partner, ApiErrorId.ERR_PARTNER_NOT_FOUND),
            (api.get_point_purchase, ApiErrorId.ERR_PURCHASE_NOT_FOUND),
            (api.get_complaint, ApiErrorId.ERR_COMPLAINT_NOT_FOUND),
            (api.get_redemption_pricing, ApiErrorId.ERR_PRICING_ROW_NOT_FOUND),
        )

        seen = []
        for read_call, expected in probes:
            response = read_call(NON_EXISTENT_UUID, admin)
            validate_error(response, expected.value)
            body = response.json()
            assert body["response_type"] == "error", body["response_type"]
            assert body["data"]["message"], (
                f"{expected.value} must carry a human-readable message"
            )
            seen.append(body["data"]["error_id"])

        assert len(set(seen)) == 12, (
            f"the twelve reads must not share an error identifier, got {sorted(set(seen))}"
        )


# ----------------------------------------------------------------------
# A required field left out
# ----------------------------------------------------------------------
class TestMissingRequiredFieldsAreRefused:
    def test_enrolment_without_the_fee_percentage_is_refused_and_stores_nothing(self, api):
        """The programme fee percentage is a declared required input, so its absence is
        a shape failure and no property row survives.

        PRD: "**Request shape** — every field the endpoint declares required must be
        present and of the declared type, and every enum-valued field must carry a value
        from that field's declared set, else `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/hotel_create_missing_program_fee_pct_returns_invalid_request
        """
        payload = fac.create_hotel_payload(name="Faulty Fields Inn", brand_code="FFI")
        payload.pop("program_fee_pct")

        response = api.create_hotel(payload, make_admin_headers())

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
        assert collect_all(api.list_hotels, make_admin_headers()) == [], (
            "a shape failure must not leave a property behind"
        )

    def test_member_enrolment_without_an_address_is_refused_and_stores_nothing(self, api):
        """The electronic address is the one input a member cannot be created without.

        PRD: "A `ProgramAdministrator` or a `MemberCareAgent` creates a member from an
        `email` — which must be globally unique across the programme and must contain an
        at-sign — a `full_name` for display, and an optional `enrollment_date` in
        `YYYY-MM-DD` form."

        Design: Corner/entities/hotel_create_missing_program_fee_pct_returns_invalid_request
        """
        payload = fac.create_member_payload(full_name="Nameless Guest")
        payload.pop("email")

        response = api.create_member(payload, make_admin_headers())

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
        assert collect_all(api.list_members, make_admin_headers()) == [], (
            "a shape failure must not leave a member behind"
        )


# ----------------------------------------------------------------------
# Declared defaults for omitted optional inputs
# ----------------------------------------------------------------------
class TestOmittedOptionalInputsTakeTheirDefaults:
    def test_an_omitted_enrolment_date_takes_the_date_part_of_the_logical_clock(self, api):
        """With the clock parked mid-morning on the fifth of August, a member enrolled
        without a date stores that calendar day, not a null and not the host's date.

        PRD: "When `enrollment_date` is omitted it defaults to the logical clock's
        current date, meaning the date part of the current logical UTC timestamp."

        Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
        """
        _defaults_court_ready_for_captures(api)
        payload = fac.create_member_payload(email="df1@example.com", full_name="Kaia Berg")
        payload.pop("enrollment_date")

        member = validate_success(api.create_member(payload, make_admin_headers()), 201)

        assert member["enrollment_date"] == "2026-08-05", (
            f"expected the clock's calendar day, got {member['enrollment_date']}"
        )

    def test_an_omitted_incidental_revenue_stores_zero_without_touching_room_revenue(
        self, api
    ):
        """Food and beverage revenue is optional; leaving it out stores zero and the
        room-only figure arrives untouched.

        PRD: "`incidental_revenue_cents` — food, beverage and everything else — is
        optional, defaults to 0, and never earns a point nor attracts a cent of
        programme fee under any rate category."

        Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
        """
        bundle = _defaults_court_ready_for_captures(api)
        member = fx.enroll_member(api, email="df2@example.com", full_name="Kaia Berg")

        stay = validate_success(
            api.create_stay(
                fac.create_stay_payload(
                    member["id"],
                    bundle["hotel"]["id"],
                    bundle["rate_plan"]["id"],
                    checkin_date="2026-07-01",
                    checkout_date="2026-07-03",
                    room_revenue_cents=50_000,
                ),
                make_admin_headers(),
            ),
            201,
        )

        assert stay["incidental_revenue_cents"] == 0, (
            f"an omitted incidental figure defaults to zero, got {stay['incidental_revenue_cents']}"
        )
        assert stay["room_revenue_cents"] == 50_000, stay["room_revenue_cents"]

    def test_a_direct_purchase_without_a_partner_stores_a_null_partner(self, api):
        """A partner reference is not merely optional on the direct channel, it is
        required to be absent, so the stored field is null.

        PRD: "The channel and the partner reference must agree exactly: `partner_id`
        must be present when the channel is `PARTNER_SALE` and absent for both
        `CO_BRAND_CARD` and `DIRECT_PURCHASE`, else `ERR_PARTNER_CHANNEL_MISMATCH` — a
        partner reference on a direct purchase is as much an error as a missing one on a
        partner sale."

        Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
        """
        _defaults_court_ready_for_captures(api)
        member = fx.enroll_member(api, email="df3@example.com", full_name="Kaia Berg")

        purchase = validate_success(
            api.create_point_purchase(
                fac.create_point_purchase_payload(
                    member["id"], points_quantity=20_000, channel="DIRECT_PURCHASE"
                ),
                make_admin_headers(),
            ),
            201,
        )

        assert purchase["partner_id"] is None, (
            f"a direct purchase carries no partner, got {purchase['partner_id']}"
        )
        assert_purchase(purchase, channel="DIRECT_PURCHASE", points_quantity=20_000)

    def test_the_untouched_fund_reports_the_declared_breakage_assumption(self, api):
        """Nobody has restated the assumption, so the singleton still reports the value
        it exists with from server start.

        PRD: "The programme fund is a singleton resource that exists from server start
        with `cash_balance_cents` of 0, `breakage_rate_pct` of 0.20, `outstanding_points`
        of 0, `point_liability_cents` of 0, a `solvency_ratio` of 999.0000 and a `status`
        of `HEALTHY`."

        Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
        """
        _defaults_court_ready_for_captures(api)

        fund = fx.read_fund(api)

        assert abs(fund["breakage_rate_pct"] - 0.2) < 1e-9, (
            f"the default breakage assumption is 0.20, got {fund['breakage_rate_pct']}"
        )
        assert_fund(fund, cash_cents=0, outstanding_points=0, liability_cents=0)


# ----------------------------------------------------------------------
# Fields the server derives from the request and the guest
# ----------------------------------------------------------------------
class TestNightsAndTierSnapshotAreDerivedAtCreation:
    def test_the_night_count_comes_from_the_two_dates_and_the_tier_from_the_guest(
        self, api
    ):
        """A twelfth-to-fifteenth stay is three nights on the half-open interval, and
        the guest is already SILVER when the row is written.

        PRD: "On creation, the system computes `nights` as the number of days from
        `checkin_date` to `checkout_date` — a half-open interval that includes the
        arrival date and excludes the departure date, so a stay arriving on the tenth and
        departing on the twelfth is two nights — and snapshots the guest's current
        `elite_tier` into `tier_at_checkin`."

        Design: Corner/entities/stay_nights_and_tier_at_checkin_are_computed_from_the_request_and_the_member
        """
        bundle = _computed_arms_with_a_silver_guest(api)
        assert_member(
            fx.read_member(api, bundle["member"]["id"]),
            elite_tier="SILVER",
            qualifying_nights=10,
        )

        second = validate_success(
            api.create_stay(
                fac.create_stay_payload(
                    bundle["member"]["id"],
                    bundle["hotel"]["id"],
                    bundle["rate_plan"]["id"],
                    checkin_date="2026-07-12",
                    checkout_date="2026-07-15",
                    room_revenue_cents=60_000,
                ),
                make_admin_headers(),
            ),
            201,
        )

        assert_stay(second, nights=3, tier_at_checkin="SILVER", status="PENDING_POSTING")
        assert_stay(
            fx.read_stay(api, bundle["first_stay"]["id"]),
            nights=10,
            tier_at_checkin="BASE",
        )

    def test_creation_awards_nothing_and_moves_no_fee_ledger(self, api):
        """The award and fee fields of a freshly captured stay are all zero, and the
        property's arrears are still exactly what the first posting put there.

        PRD: "The stay lands in `PENDING_POSTING` with `base_points_awarded`,
        `bonus_points_awarded` and `program_fee_assessed_cents` at 0,
        `bonus_multiplier_applied` at 0.00, and `dispute_reason` and `void_reason` both
        null."

        Design: Corner/entities/stay_nights_and_tier_at_checkin_are_computed_from_the_request_and_the_member
        """
        bundle = _computed_arms_with_a_silver_guest(api)

        second = validate_success(
            api.create_stay(
                fac.create_stay_payload(
                    bundle["member"]["id"],
                    bundle["hotel"]["id"],
                    bundle["rate_plan"]["id"],
                    checkin_date="2026-07-12",
                    checkout_date="2026-07-15",
                    room_revenue_cents=60_000,
                ),
                make_admin_headers(),
            ),
            201,
        )

        assert_stay(
            second,
            base_points=0,
            bonus_points=0,
            fee_cents=0,
            bonus_multiplier=0.0,
            room_revenue_cents=60_000,
        )
        assert_hotel(fx.read_hotel(api, bundle["hotel"]["id"]), fee_ledger_cents=5_000)


# ----------------------------------------------------------------------
# Fields the server stamps without being asked
# ----------------------------------------------------------------------
class TestServerStampedIdentifiersAndTimestamps:
    def test_the_capture_request_carries_no_identifier_yet_the_row_has_one(self, api):
        """The client sends only references, dates and revenue; the identifier, the two
        timestamps and the opening version are all minted server-side.

        PRD: "Every resource the API returns carries a server-minted `id`: a UUID string
        with no type prefix and no embedded meaning."

        Design: Corner/entities/stay_identifiers_and_timestamps_are_stamped_by_the_server
        """
        fx.set_clock(api, "2026-08-04T08:00:00Z")
        bundle = fx.create_active_hotel(
            api,
            rate_code="BAR",
            rate_category="TRANSIENT",
            name="Stamped Suites",
            brand_code="STS",
            market_tier="URBAN",
            program_fee_pct=0.05,
            rooms_count=95,
            trailing_12m_occupancy_pct=0.82,
            trailing_12m_adr_cents=30_000,
        )
        member = fx.enroll_member(
            api, email="sf1@example.com", full_name="Teodor Marek",
            enrollment_date="2026-03-03",
        )
        payload = fac.create_stay_payload(
            member["id"],
            bundle["hotel"]["id"],
            bundle["rate_plan"]["id"],
            checkin_date="2026-07-20",
            checkout_date="2026-07-22",
            room_revenue_cents=40_000,
        )
        assert "id" not in payload and "version" not in payload, (
            "the capture request must not carry system fields"
        )

        stay = validate_success(api.create_stay(payload, make_admin_headers()), 201)

        assert is_valid_uuid(stay["id"]), f"expected a bare UUID, got {stay['id']}"
        assert_versioned_entity_shape(stay)
        assert_created_and_updated_match(stay)
        assert stay["version"] == 1, stay["version"]

    def test_the_status_and_the_two_narrative_fields_are_set_by_the_server(self, api):
        """Nothing in the payload speaks about status or reasons, yet the row opens in
        the pending posture with both narrative fields null.

        PRD: "and `version`, an integer that starts at 1 when the row is created and
        increments by exactly 1 on every mutation of that row."

        Design: Corner/entities/stay_identifiers_and_timestamps_are_stamped_by_the_server
        """
        fx.set_clock(api, "2026-08-04T08:00:00Z")
        bundle = fx.create_active_hotel(
            api,
            rate_code="BAR",
            rate_category="TRANSIENT",
            name="Stamped Suites",
            brand_code="STS",
            market_tier="URBAN",
        )
        member = fx.enroll_member(
            api, email="sf2@example.com", full_name="Teodor Marek",
            enrollment_date="2026-03-03",
        )

        stay = validate_success(
            api.create_stay(
                fac.create_stay_payload(
                    member["id"],
                    bundle["hotel"]["id"],
                    bundle["rate_plan"]["id"],
                    checkin_date="2026-07-20",
                    checkout_date="2026-07-22",
                    room_revenue_cents=40_000,
                ),
                make_admin_headers(),
            ),
            201,
        )

        assert_stay(stay, status="PENDING_POSTING", version=1)
        assert stay["dispute_reason"] is None, stay["dispute_reason"]
        assert stay["void_reason"] is None, stay["void_reason"]
        assert is_iso8601_timestamp(stay["created_at"]), stay["created_at"]
        assert is_iso8601_timestamp(stay["updated_at"]), stay["updated_at"]


# ----------------------------------------------------------------------
# Enum, range and date-order refusals
# ----------------------------------------------------------------------
class TestShapeRangeAndDateOrderRefusals:
    def test_a_rate_category_outside_the_declared_set_is_a_shape_failure(self, api):
        """PACKAGE is not one of the six commercial families, so the request never
        reaches the range or ordering checks.

        PRD: "Either a `ProgramAdministrator` or the property's own `HotelOwner`
        registers a rate plan by supplying a `rate_code` of 1 to 16 characters —
        something like `BAR` or `CORP01` — and a `rate_category` drawn from `TRANSIENT`,
        `CORPORATE_NEGOTIATED`, `GROUP`, `OPAQUE_WHOLESALE`, `EMPLOYEE_COMP` and
        `AWARD`."

        Design: Corner/entities/enum_range_and_date_order_constraints_are_refused_at_their_own_priorities
        """
        bundle = _constraint_hall_ready_for_refusals(api)

        response = api.create_rate_plan(
            bundle["hotel"]["id"],
            fac.create_rate_plan_payload(rate_code="PKG", rate_category="PACKAGE"),
            make_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
        assert response.status_code == 400, response.status_code
        rows, meta = validate_paginated(
            api.list_rate_plans(
                make_admin_headers(), {"hotel_id": bundle["hotel"]["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            f"the refused registration left the property with one rate plan, got {meta['total_count']}"
        )
        assert rows[0]["rate_category"] == "TRANSIENT", rows[0]["rate_category"]

    def test_a_fee_percentage_above_the_ceiling_is_a_range_failure(self, api):
        """A quarter is above the declared ceiling of a fifth, which is a quantity
        violation rather than a shape one and carries the unprocessable status.

        PRD: "`program_fee_pct` must lie between 0.0 and 0.20 inclusive with at most four
        decimal places"

        Design: Corner/entities/enum_range_and_date_order_constraints_are_refused_at_their_own_priorities
        """
        _constraint_hall_ready_for_refusals(api)

        response = api.create_hotel(
            fac.create_hotel_payload(
                name="Overpriced Fee Inn",
                brand_code="OFI",
                market_tier="URBAN",
                program_fee_pct=0.25,
                rooms_count=100,
                trailing_12m_occupancy_pct=0.80,
                trailing_12m_adr_cents=20_000,
            ),
            make_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_AMOUNT_OUT_OF_RANGE.value)
        assert response.status_code == 422, response.status_code

    def test_a_departure_before_the_arrival_is_a_date_order_failure(self, api):
        """The two dates are individually well-formed, so the refusal is about their
        order rather than their shape.

        PRD: "**Date-range sanity** — a paid stay's and an award booking's
        `checkout_date` must be strictly after its `checkin_date`, and a blackout
        window's `end_date` and an award price window's `window_end_date` must fall on or
        after their respective start dates."

        Design: Corner/entities/enum_range_and_date_order_constraints_are_refused_at_their_own_priorities
        """
        bundle = _constraint_hall_ready_for_refusals(api)

        response = api.create_stay(
            fac.create_stay_payload(
                bundle["member"]["id"],
                bundle["hotel"]["id"],
                bundle["rate_plan"]["id"],
                checkin_date="2026-07-10",
                checkout_date="2026-07-05",
                room_revenue_cents=40_000,
            ),
            make_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_INVALID_DATE_RANGE.value)
        assert response.status_code == 422, response.status_code

    def test_negative_room_revenue_is_a_range_failure_and_persists_no_stay(self, api):
        """Room revenue has a floor of zero, and the refusal leaves the stay collection
        empty.

        PRD: "**Quantity ranges** — `room_revenue_cents` and `incidental_revenue_cents`
        must be at least 0"

        Design: Corner/entities/enum_range_and_date_order_constraints_are_refused_at_their_own_priorities
        """
        bundle = _constraint_hall_ready_for_refusals(api)

        response = api.create_stay(
            fac.create_stay_payload(
                bundle["member"]["id"],
                bundle["hotel"]["id"],
                bundle["rate_plan"]["id"],
                checkin_date="2026-07-10",
                checkout_date="2026-07-12",
                room_revenue_cents=-500,
            ),
            make_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_AMOUNT_OUT_OF_RANGE.value)
        assert response.status_code == 422, response.status_code
        assert collect_all(api.list_stays, make_admin_headers()) == [], (
            "a range failure must not leave a stay behind"
        )


# ----------------------------------------------------------------------
# The append-only ledger
# ----------------------------------------------------------------------
class TestLedgerEntriesAreAppendOnly:
    def test_the_settled_purchase_writes_exactly_one_entry_naming_its_source(self, api):
        """One direct purchase settles into one entry whose only source reference is the
        purchase, at the snapshotted unit cost.

        PRD: "Every entry also snapshots `liability_unit_cost_cents_per_1000`, which is
        always 600."

        Design: Corner/entities/point_ledger_entry_exposes_no_version_and_no_write_endpoint
        """
        funded = _member_funded_by_one_settled_direct_purchase(api)
        member_id = funded["member"]["id"]

        rows, meta = validate_paginated(
            api.list_ledger_entries(make_auditor_headers(), {"member_id": member_id})
        )

        assert meta["total_count"] == 1, (
            f"one settled direct purchase is one entry, got {meta['total_count']}"
        )
        assert_ledger_entry(
            rows[0],
            entry_type="PURCHASE",
            points=20_000,
            member_id=member_id,
            source_purchase_id=funded["purchase"]["id"],
            liability_unit_cost=600,
        )
        assert rows[0]["source_stay_id"] is None, rows[0]["source_stay_id"]
        assert rows[0]["source_redemption_id"] is None, rows[0]["source_redemption_id"]
        assert rows[0]["reversal_of_entry_id"] is None, rows[0]["reversal_of_entry_id"]

    def test_the_entry_carries_no_version_and_no_updated_timestamp(self, api):
        """An entry is a record of a decision already made, so the two mutation-tracking
        fields are absent from its representation, and the single read agrees with the
        list.

        PRD: "Three resources are append-only records of a decision already made and
        therefore carry **only** `id` and `created_at` — both `updated_at` and `version`
        are absent from their representations entirely."

        Design: Corner/entities/point_ledger_entry_exposes_no_version_and_no_write_endpoint
        """
        funded = _member_funded_by_one_settled_direct_purchase(api)
        auditor = make_auditor_headers()
        listed, _ = validate_paginated(
            api.list_ledger_entries(auditor, {"member_id": funded["member"]["id"]})
        )

        single = read_entity(api.get_ledger_entry, listed[0]["id"], auditor)

        assert_append_only_entity_shape(single)
        assert "version" not in single, "an append-only row exposes no version"
        assert "updated_at" not in single, "an append-only row exposes no updated_at"
        assert single == listed[0], (
            "the single read and the filtered list must return the same body"
        )


# ----------------------------------------------------------------------
# Body foreign keys on a flat topology
# ----------------------------------------------------------------------
class TestBodyForeignKeysAreResolvedLikePathIdentifiers:
    def test_an_unknown_guest_reference_reports_the_member_not_found(self, api):
        """The guest is named in the body rather than the path, and it resolves the same
        way and yields the same 404.

        PRD: "Identifier resolution also covers foreign keys arriving in a request body:
        a body-supplied `hotel_id`, `member_id`, `rate_plan_id`, `partner_id` or
        `related_delivery_id` is resolved the same way and yields the same 404."

        Design: Corner/entities/stay_create_with_unknown_body_foreign_keys_is_refused
        """
        bundle = fx.create_active_hotel(
            api,
            rate_code="BAR",
            rate_category="TRANSIENT",
            name="Flatkey Court",
            brand_code="FKC",
            market_tier="URBAN",
        )

        response = api.create_stay(
            fac.create_stay_payload(
                NON_EXISTENT_UUID,
                bundle["hotel"]["id"],
                bundle["rate_plan"]["id"],
                checkin_date="2026-07-01",
                checkout_date="2026-07-03",
                room_revenue_cents=40_000,
            ),
            make_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_MEMBER_NOT_FOUND.value)
        assert collect_all(api.list_stays, make_admin_headers()) == [], (
            "a dangling body reference leaves no stay behind"
        )

    def test_an_unknown_rate_plan_reference_reports_the_rate_plan_not_found(self, api):
        """The commercial terms are also a body reference, and an unknown one is
        distinguished from an unknown guest by its own error identifier.

        PRD: "The payload names the guest through `member_id`, the property through
        `hotel_id`, the commercial terms through `rate_plan_id`, and the dates through
        `checkin_date` and `checkout_date`."

        Design: Corner/entities/stay_create_with_unknown_body_foreign_keys_is_refused
        """
        bundle = fx.create_active_hotel(
            api,
            rate_code="BAR",
            rate_category="TRANSIENT",
            name="Flatkey Court",
            brand_code="FKC",
            market_tier="URBAN",
        )
        member = fx.enroll_member(
            api, email="fk1@example.com", full_name="Sanna Aalto",
            enrollment_date="2026-02-10",
        )

        response = api.create_stay(
            fac.create_stay_payload(
                member["id"],
                bundle["hotel"]["id"],
                NON_EXISTENT_UUID,
                checkin_date="2026-07-01",
                checkout_date="2026-07-03",
                room_revenue_cents=40_000,
            ),
            make_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_RATE_PLAN_NOT_FOUND.value)
        _, meta = validate_paginated(api.list_stays(make_admin_headers()))
        assert meta["total_count"] == 0, (
            f"no stay survives a dangling rate-plan reference, got {meta['total_count']}"
        )
