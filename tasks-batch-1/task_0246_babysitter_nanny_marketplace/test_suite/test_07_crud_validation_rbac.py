"""Entity creation defaults, not-found, required-field validation, computed
fields, booking-creation business validations (rate floor, recurrence, interval,
posting mismatch), list pagination, and RBAC (peer-role exclusivity, auth).

Translates corner instances under entities, validations, endpoints, and rbac.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    set_clock, create_family, create_caregiver, create_open_posting,
    NON_EXISTENT_UUID, make_family_headers, make_caregiver_headers, TEST_USERS,
    build_user_headers,
)

ADMIN = TEST_USERS["admin_headers"]


class TestEntityCreation:
    """Corner entities: caregiver defaults, family default tier, computed fields."""

    def test_create_caregiver_returns_201_with_defaults(self, api):
        """PRD §3.1: "A newly registered caregiver starts with
        `background_check_tier` of `NONE`, `verification_status` of `NONE`, and
        `availability_status` of `OFFLINE`."

        (The PRD does not pin the initial `version` value in prose — "begins at
        its initial value" — so it is not asserted here.)

        Design: Corner/entities/create_caregiver_returns_201_with_defaults
        """
        set_clock("2026-03-01T00:00:00Z")
        res = api.create_caregiver(
            {"full_name": "Ava", "email": "ava@x.com", "hourly_rate_floor_cents": 1800}, ADMIN)
        cg = validate_success(res, 201)
        assert cg["background_check_tier"] == "NONE"
        assert cg["verification_status"] == "NONE"
        assert cg["availability_status"] == "OFFLINE"

    def test_family_create_default_required_tier_basic(self, api):
        """PRD §3.1: "A family may declare a `required_tier` ... when omitted it
        defaults to `BASIC`."
        PRD §3.1: "A family may also open its wallet with an initial
        `wallet_balance_cents` (defaulting to 0 and never negative). On
        registration ... its `escrow_available_cents` equals its
        `wallet_balance_cents`."

        Design: Corner/entities/family_create_default_required_tier_basic
        """
        set_clock("2026-03-01T00:00:00Z")
        res = api.create_family(
            {"display_name": "Def", "email": "def@x.com", "num_children": 1}, ADMIN)
        fam = validate_success(res, 201)
        assert fam["required_tier"] == "BASIC"
        assert fam["wallet_balance_cents"] == 0
        assert fam["escrow_available_cents"] == 0

    def test_caregiver_rating_computed_fields_start_empty(self, api):
        """PRD §3.1: "their reputation fields `rating_avg` (0 when there are no
        published reviews) and `rating_count` begin empty."
        PRD §3.1: "Their computed earnings fields — `pending_earnings_cents`,
        `lifetime_paid_cents` — ... begin empty."

        Design: Corner/entities/caregiver_rating_computed_fields_ignore_input
        """
        set_clock("2026-03-01T00:00:00Z")
        res = api.create_caregiver(
            {"full_name": "Cal", "email": "cal@x.com", "hourly_rate_floor_cents": 1500}, ADMIN)
        cg = validate_success(res, 201)
        assert cg["rating_avg"] == 0
        assert cg["rating_count"] == 0
        assert cg["pending_earnings_cents"] == 0


class TestNotFoundAndRequiredFields:
    """Corner entities: not-found, missing required field."""

    def test_get_caregiver_nonexistent_returns_not_found(self, api):
        """PRD §2.9: "The first missing reference yields `ERR_NOT_FOUND` before any
        business rule is evaluated."

        Design: Corner/entities/get_caregiver_nonexistent_returns_not_found
        """
        set_clock("2026-03-01T00:00:00Z")
        res = api.get_caregiver(NON_EXISTENT_UUID, ADMIN)
        validate_error(res, "ERR_NOT_FOUND")

    def test_create_booking_missing_required_field_returns_validation(self, api):
        """PRD §2.10: "Body well-formedness (`ERR_VALIDATION`) is the final
        catch-all when a required field is missing or ill-typed".
        PRD §3.4: "together with an `agreed_rate_cents` (the hourly rate proposed
        in this round), a `scheduled_start` and `scheduled_end` for the first
        session window".

        Omitting scheduled_end → 400 ERR_VALIDATION.

        Design: Corner/entities/create_booking_missing_required_field_returns_validation
        """
        set_clock("2026-03-01T00:00:00Z")
        fam = create_family(wallet_balance_cents=50000, num_children=1,
                            required_tier="BASIC", email="rq@x.com")
        cg = create_caregiver(hourly_rate_floor_cents=1500, email="rqcg@x.com")
        posting = create_open_posting(fam["id"], care_type="ONE_TIME",
                                      family_pay_rate_cents=2000, required_tier="BASIC")
        res = api.create_booking(
            {"family_id": fam["id"], "caregiver_id": cg["id"], "job_posting_id": posting["id"],
             "agreed_rate_cents": 2000, "scheduled_start": "2026-03-20T08:00:00Z"},
            make_family_headers(fam["id"]))
        validate_error(res, "ERR_VALIDATION")


class TestBookingCreationValidations:
    """Corner validations: rate floor, recurrence shape, interval, posting mismatch."""

    def test_offer_rate_below_floor_rejected(self, api):
        """PRD §3.4: "The proposed `agreed_rate_cents` must be at least the
        caregiver's `hourly_rate_floor_cents`, else `ERR_RATE_BELOW_FLOOR`."

        Caregiver floor 1500; offer 1400 → 422 ERR_RATE_BELOW_FLOOR.

        Design: Corner/validations/offer_rate_below_floor_rejected
        """
        set_clock("2026-03-01T00:00:00Z")
        fam = create_family(wallet_balance_cents=50000, num_children=1,
                            required_tier="BASIC", email="fl@x.com")
        cg = create_caregiver(hourly_rate_floor_cents=1500, email="flcg@x.com")
        posting = create_open_posting(fam["id"], care_type="ONE_TIME",
                                      family_pay_rate_cents=2000, required_tier="BASIC")
        res = api.create_booking(
            {"family_id": fam["id"], "caregiver_id": cg["id"], "job_posting_id": posting["id"],
             "agreed_rate_cents": 1400, "scheduled_start": "2026-03-20T08:00:00Z",
             "scheduled_end": "2026-03-20T12:00:00Z", "recurrence_count": 1},
            make_family_headers(fam["id"]))
        validate_error(res, "ERR_RATE_BELOW_FLOOR")

    def test_recurrence_count_invalid_for_one_time(self, api):
        """PRD §3.4: "The `recurrence_count` must match the posting's care type: it
        must equal 1 for a `ONE_TIME` posting and must be at least 2 for a
        `RECURRING` posting (defaulting to 1), else `ERR_RECURRENCE_INVALID`."

        ONE_TIME posting with recurrence_count=3 → 422 ERR_RECURRENCE_INVALID.

        Design: Corner/validations/recurrence_count_invalid_for_one_time
        """
        set_clock("2026-03-01T00:00:00Z")
        fam = create_family(wallet_balance_cents=50000, num_children=1,
                            required_tier="BASIC", email="rc@x.com")
        cg = create_caregiver(hourly_rate_floor_cents=1500, email="rccg@x.com")
        posting = create_open_posting(fam["id"], care_type="ONE_TIME",
                                      family_pay_rate_cents=2000, required_tier="BASIC")
        res = api.create_booking(
            {"family_id": fam["id"], "caregiver_id": cg["id"], "job_posting_id": posting["id"],
             "agreed_rate_cents": 2000, "scheduled_start": "2026-03-20T08:00:00Z",
             "scheduled_end": "2026-03-20T12:00:00Z", "recurrence_count": 3},
            make_family_headers(fam["id"]))
        validate_error(res, "ERR_RECURRENCE_INVALID")

    def test_invalid_interval_end_before_start_rejected(self, api):
        """PRD §3.4: "The `scheduled_end` must be strictly after the
        `scheduled_start`, else `ERR_INVALID_INTERVAL`."

        scheduled_end before scheduled_start → 422 ERR_INVALID_INTERVAL.

        Design: Corner/validations/invalid_interval_end_before_start_rejected
        """
        set_clock("2026-03-01T00:00:00Z")
        fam = create_family(wallet_balance_cents=50000, num_children=1,
                            required_tier="BASIC", email="iv@x.com")
        cg = create_caregiver(hourly_rate_floor_cents=1500, email="ivcg@x.com")
        posting = create_open_posting(fam["id"], care_type="ONE_TIME",
                                      family_pay_rate_cents=2000, required_tier="BASIC")
        res = api.create_booking(
            {"family_id": fam["id"], "caregiver_id": cg["id"], "job_posting_id": posting["id"],
             "agreed_rate_cents": 2000, "scheduled_start": "2026-03-20T14:00:00Z",
             "scheduled_end": "2026-03-20T08:00:00Z", "recurrence_count": 1},
            make_family_headers(fam["id"]))
        validate_error(res, "ERR_INVALID_INTERVAL")

    def test_booking_posting_mismatch_rejected(self, api):
        """PRD §3.4: "the posting's `family_id` must equal the booking's
        `family_id` and the posting must currently be `OPEN`, else
        `ERR_POSTING_MISMATCH`."

        Family B books against Family A's posting → 422 ERR_POSTING_MISMATCH.

        Design: Corner/validations/booking_posting_mismatch_rejected
        """
        set_clock("2026-03-01T00:00:00Z")
        fam_a = create_family(wallet_balance_cents=50000, num_children=1,
                              required_tier="BASIC", email="fa@x.com")
        fam_b = create_family(wallet_balance_cents=50000, num_children=1,
                              required_tier="BASIC", email="fb@x.com")
        cg = create_caregiver(hourly_rate_floor_cents=1500, email="uma@x.com")
        posting = create_open_posting(fam_a["id"], care_type="ONE_TIME",
                                      family_pay_rate_cents=2000, required_tier="BASIC")
        res = api.create_booking(
            {"family_id": fam_b["id"], "caregiver_id": cg["id"], "job_posting_id": posting["id"],
             "agreed_rate_cents": 2000, "scheduled_start": "2026-03-20T08:00:00Z",
             "scheduled_end": "2026-03-20T12:00:00Z", "recurrence_count": 1},
            make_family_headers(fam_b["id"]))
        validate_error(res, "ERR_POSTING_MISMATCH")


class TestListPagination:
    """Corner endpoints: bookings list pagination envelope."""

    def test_list_bookings_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned ...
        Every list response carries the pagination fields `limit`, `offset`,
        `total_count`, and `has_more` inside the `meta` object of the envelope."

        Two OFFERED bookings; limit=1 → 1 item, total_count 2, has_more true.

        Design: Corner/endpoints/list_bookings_pagination_envelope
        """
        set_clock("2026-03-01T00:00:00Z")
        fam = create_family(wallet_balance_cents=100000, num_children=1,
                            required_tier="BASIC", email="pg@x.com")
        cg1 = create_caregiver(hourly_rate_floor_cents=1500, email="vee@x.com")
        cg2 = create_caregiver(hourly_rate_floor_cents=1500, email="wyn@x.com")
        p1 = create_open_posting(fam["id"], care_type="ONE_TIME",
                                 family_pay_rate_cents=2000, required_tier="BASIC", title="Pa")
        p2 = create_open_posting(fam["id"], care_type="ONE_TIME",
                                 family_pay_rate_cents=2000, required_tier="BASIC", title="Pb")
        for cg, p, day in [(cg1, p1, 20), (cg2, p2, 21)]:
            get_success_data(api.create_booking(
                {"family_id": fam["id"], "caregiver_id": cg["id"], "job_posting_id": p["id"],
                 "agreed_rate_cents": 2000, "scheduled_start": f"2026-03-{day}T08:00:00Z",
                 "scheduled_end": f"2026-03-{day}T12:00:00Z", "recurrence_count": 1},
                make_family_headers(fam["id"])))
        data, meta = validate_paginated(api.list_bookings(
            make_family_headers(fam["id"]), params={"family_id": fam["id"], "limit": 1, "offset": 0}))
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True


class TestRbac:
    """Corner rbac: peer-role exclusivity and missing auth."""

    def test_family_cannot_confirm_booking(self, api):
        """PRD §2.1: "A request whose role is syntactically valid but is not
        permitted to perform the targeted operation ... is rejected with
        `ERR_FORBIDDEN`."

        Confirm is Caregiver-exclusive (PRD §4 authorizes only PlatformAdmin,
        Caregiver); a Family calling confirm → 403 ERR_FORBIDDEN.

        Design: Corner/rbac/family_cannot_confirm_booking_caregiver_exclusive
        """
        set_clock("2026-03-01T00:00:00Z")
        fam = create_family(wallet_balance_cents=100000, num_children=1,
                            required_tier="BASIC", email="rb@x.com")
        # cleared/available caregiver, but the FAMILY attempts the confirm.
        from test_helpers import create_cleared_available_caregiver
        cg = create_cleared_available_caregiver(tier="BASIC", email="rbcg@x.com")
        posting = create_open_posting(fam["id"], care_type="ONE_TIME",
                                      family_pay_rate_cents=2000, required_tier="BASIC")
        from test_helpers import offer_booking
        booking = offer_booking(fam["id"], cg["id"], posting["id"], agreed_rate_cents=2000,
                                scheduled_start="2026-03-20T08:00:00Z",
                                scheduled_end="2026-03-20T12:00:00Z")
        res = api.confirm_booking(booking["id"], make_family_headers(fam["id"]))
        validate_error(res, "ERR_FORBIDDEN")

    def test_caregiver_cannot_create_job_posting(self, api):
        """PRD §2.1: "A request whose role is syntactically valid but is not
        permitted to perform the targeted operation ... is rejected with
        `ERR_FORBIDDEN`."

        Creating a job posting is Family-exclusive (PRD §4 authorizes only
        PlatformAdmin, Family); a Caregiver calling it → 403 ERR_FORBIDDEN.

        Design: Corner/rbac/caregiver_cannot_create_job_posting_family_exclusive
        """
        set_clock("2026-03-01T00:00:00Z")
        fam = create_family(wallet_balance_cents=50000, num_children=1,
                            required_tier="BASIC", email="cp@x.com")
        cg = create_caregiver(hourly_rate_floor_cents=1500, email="yas@x.com")
        res = api.create_job_posting(
            {"family_id": fam["id"], "title": "Bad", "care_type": "ONE_TIME",
             "family_pay_rate_cents": 2000}, make_caregiver_headers(cg["id"]))
        validate_error(res, "ERR_FORBIDDEN")

    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request that omits either header, or supplies a malformed
        value, is rejected with `ERR_UNAUTHENTICATED`."

        A request with no X-User-Role / X-User-ID headers → 401
        ERR_UNAUTHENTICATED.

        Design: Corner/rbac/missing_auth_headers_unauthenticated
        """
        set_clock("2026-03-01T00:00:00Z")
        res = api.list_families({})
        validate_error(res, "ERR_UNAUTHENTICATED")
