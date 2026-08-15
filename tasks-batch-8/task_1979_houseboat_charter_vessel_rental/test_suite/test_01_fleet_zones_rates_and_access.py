"""Fleet onboarding, season-rate windows, renter qualification, and the
authentication / role / ownership gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_booking,
    assert_renter,
    assert_vessel,
    cancel_booking_payload,
    confirm_booking,
    create_booking,
    create_qualified_renter,
    create_season_rate,
    create_vessel,
    get_booking,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    register_renter,
    setup_confirmed_booking,
    setup_fleet_with_rate,
    submit_certificate,
    validate_error,
    validate_success,
    verify_certificate,
)

FM = TEST_USERS["fleet_manager_headers"]
DS = TEST_USERS["dock_staff_headers"]
MECH = TEST_USERS["mechanic_headers"]
RENTER_FALLBACK = TEST_USERS["renter_headers"]


class TestFleetOnboarding:
    def test_vessel_creation_sets_initial_state(self, api):
        """PRD §3.1: "A new vessel starts `AVAILABLE`."
        PRD §2.5: "`id` (string): a unique, server-minted identifier formatted
        as a UUID, with no type prefix."
        PRD §2.5: "`created_at` (string): an ISO 8601 UTC timestamp with three
        fractional digits recording when the resource was created."

        Design: Corner/entities/vessel_creation_sets_initial_state
        """
        resp = api.create_vessel(
            {
                "name": "Compact Zero",
                "size_class": "COMPACT_36",
                "berth_count": 6,
                "home_marina": "Wahweap",
                "fuel_tank_capacity_gallons": 150,
            },
            FM,
        )
        vessel = validate_success(resp, 201)
        assert_vessel(vessel)
        assert vessel["status"] == "AVAILABLE", (
            f"new vessel must start AVAILABLE, got {vessel['status']}"
        )
        assert is_valid_uuid(vessel["id"]), "id must be a UUID with no type prefix"
        assert is_iso8601_timestamp(vessel["created_at"])
        assert is_iso8601_timestamp(vessel["updated_at"])
        assert isinstance(vessel["version"], int), "version is a system-managed integer"

    def test_season_rate_overlap_rejected(self, api):
        """PRD §3.1: "Because rate windows are closed intervals, two windows of
        the same `size_class` may not overlap at all, not even by sharing a
        single edge date; an overlapping submission is rejected with
        `ERR_SEASON_RATE_OVERLAP`."

        Design: Corner/validations/season_rate_overlap_rejected
        """
        create_season_rate(size_class="COMPACT_36", season="PEAK",
                           start_date="2026-06-01", end_date="2026-08-31",
                           nightly_rate_cents=45000, weekly_discount_pct=10)

        # Same size_class, touching at the shared edge date 2026-08-31.
        resp = api.create_season_rate(
            {
                "size_class": "COMPACT_36",
                "season": "SHOULDER",
                "start_date": "2026-08-31",
                "end_date": "2026-10-31",
                "nightly_rate_cents": 32000,
                "weekly_discount_pct": 10,
            },
            FM,
        )
        validate_error(resp, ApiErrorId.ERR_SEASON_RATE_OVERLAP)

        # A different size class may reuse the identical window.
        resp = api.create_season_rate(
            {
                "size_class": "STANDARD_44",
                "season": "PEAK",
                "start_date": "2026-06-01",
                "end_date": "2026-08-31",
                "nightly_rate_cents": 65000,
                "weekly_discount_pct": 10,
            },
            FM,
        )
        other = validate_success(resp, 201)
        assert other["size_class"] == "STANDARD_44"


class TestAccessGates:
    def test_booking_create_missing_auth_returns_unauthenticated(self, api):
        """PRD §2.1: "A request with missing headers or an undeclared role is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/booking_create_missing_auth_returns_unauthenticated
        """
        resp = api.create_booking(
            {
                "vessel_id": "550e8400-e29b-41d4-a716-446655440000",
                "renter_id": "550e8400-e29b-41d4-a716-446655440001",
                "start_date": "2026-08-20",
                "end_date": "2026-08-22",
                "party_size": 2,
            },
            headers=None,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_renter_cannot_create_vessel(self, api):
        """PRD §2.1: "A request whose role is not listed among the roles
        authorized for the target endpoint is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."
        PRD §4 endpoint table: "POST | `/vessels` | Register a vessel in the
        fleet | FleetManager".

        Design: Corner/rbac/renter_cannot_create_vessel
        """
        resp = api.create_vessel(
            {
                "name": "Sneaky",
                "size_class": "COMPACT_36",
                "berth_count": 6,
                "home_marina": "Wahweap",
                "fuel_tank_capacity_gallons": 150,
            },
            RENTER_FALLBACK,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_renter_cannot_cancel_foreign_booking(self, api):
        """PRD §2.1: "a renter may create a booking only with their own
        `renter_id`, and may confirm, modify, cancel, submit an itinerary for,
        sign orientation items on, or report incidents on their own bookings
        only."
        PRD §2.1: "A violation of this ownership rule is rejected with
        `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/rbac/renter_cannot_cancel_foreign_booking
        """
        ctx = setup_confirmed_booking(
            start_date="2026-09-01", end_date="2026-09-04",
            rates=[("PEAK", "2026-06-01", "2026-10-31", 45000, 10)],
            renter_name="Own Er", renter_email="own@x.com")
        booking = ctx["booking"]

        # A second, unrelated renter attempts the cancel carrying the booking's
        # current version — the ownership rule fires before any OCC check.
        _, stranger_headers, _ = create_qualified_renter(
            full_name="Sneak Er", email="sneak@x.com", cert_number="CERT-9001")
        resp = api.cancel_booking(
            booking["id"],
            cancel_booking_payload(booking["version"]),
            stranger_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)

        after = get_booking(booking["id"])
        assert_booking(after)
        assert after["status"] == "CONFIRMED", (
            f"foreign cancel must not change the booking, got {after['status']}"
        )

    def test_mechanic_cannot_settle_booking(self, api):
        """PRD §2.1: "A request whose role is not listed among the roles
        authorized for the target endpoint is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."
        PRD §4 endpoint table: "POST | `/bookings/{id}/settle` | Finalize
        settlement: charge lines, deposit waterfall, refunds | DockStaff".

        Design: Corner/rbac/mechanic_cannot_settle_booking
        """
        vessel = setup_fleet_with_rate()
        renter, headers, _ = create_qualified_renter(
            full_name="Mec Han", email="mech@x.com", cert_number="CERT-9002")
        booking = create_booking(vessel["id"], renter, headers,
                                 start_date="2026-08-20", end_date="2026-08-22")

        resp = api.settle_booking(booking["id"], MECH)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


class TestRenterQualification:
    def test_renter_qualifies_on_certificate_verify(self, api):
        """PRD §3.3: "A new renter's `qualification_status` starts at
        `UNVERIFIED`, with `risk_score_lifetime` and `risk_score_rolling_24m`
        both at 0 and a `deposit_multiplier` of 1.0."
        PRD §3.3: "The first verification lifts an `UNVERIFIED` renter to
        `QUALIFIED`; a fresh verification likewise restores a `SUSPENDED`
        renter."

        Design: Corner/entities/renter_qualifies_on_certificate_verify
        """
        renter, headers = register_renter(full_name="Qua Lify", email="qua@x.com",
                                          date_of_birth="1990-01-04")
        assert_renter(renter)
        assert renter["qualification_status"] == "UNVERIFIED"
        assert renter["risk_score_lifetime"] == 0
        assert renter["risk_score_rolling_24m"] == 0
        assert renter["deposit_multiplier"] == 1.0

        cert = submit_certificate(renter, headers, cert_number="C-1302",
                                  issuing_authority="STATE",
                                  issued_on="2026-01-15", expires_on="2027-06-30")
        assert cert["status"] == "SUBMITTED", (
            f"certificate must start SUBMITTED, got {cert['status']}"
        )

        cert = verify_certificate(cert["id"])
        assert cert["status"] == "VERIFIED"

        profile = get_success_data(api.get_renter(renter["id"], FM))
        assert profile["qualification_status"] == "QUALIFIED", (
            "verification of a certificate covering the current date lifts the "
            f"renter to QUALIFIED, got {profile['qualification_status']}"
        )
