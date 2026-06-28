"""Entity-shape, endpoint-behavior, and RBAC claims: location defaults, member
system fields, append-only add-on shape, listing pagination, sweep-driven pack
expiry, series materialization waterfall, and role/ownership enforcement.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    fixtures,
    factories,
    assert_no_version_fields,
    make_member_headers,
    make_flexologist_headers,
    make_front_desk_headers,
    make_studio_manager_headers,
    NON_EXISTENT_UUID,
)

FD = make_front_desk_headers()
SM = make_studio_manager_headers()


# ===========================================================================
# entities
# ===========================================================================

class TestEntityShapes:
    def test_create_location_applies_defaults(self, api):
        """PRD §3.1: "an `open_minute_of_day` (default 540, i.e., 09:00 UTC, inclusive) and a `close_minute_of_day` (default 1260, i.e., 21:00 UTC, exclusive) ... a `flexologist_buffer_minutes` (default 15, at least 0) ... a `no_show_fee_cents` (default 5000, at least 0) flat penalty ... and a `cancel_window_hours` (default 12, at least 0)".
        PRD §3.1: "A location's `status` begins `OPEN`; closing it transitions `status` to `CLOSED`, after which new bookings at that location are blocked."

        Design: Corner/entities/create_location_returns_defaults
        """
        loc = validate_success(api.create_location({"name": "Defaults"}, SM),
                               expected_status=201)
        assert loc["status"] == "OPEN"
        assert loc["no_show_fee_cents"] == 5000
        assert loc["cancel_window_hours"] == 12
        assert loc["flexologist_buffer_minutes"] == 15

    def test_get_unknown_member_not_found(self, api):
        """PRD §2.5: "a path id that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404) before any deeper lookup or body validation runs."

        Design: Corner/entities/get_member_not_found_404
        """
        validate_error(api.get_member(NON_EXISTENT_UUID, FD), ApiErrorId.ERR_NOT_FOUND.value)

    def test_create_service_missing_kind_rejected(self, api):
        """PRD §2.2 / §5: malformed requests with a missing required field are
        ERR_VALIDATION (400). PRD §3.1 lists a service's required `kind` of
        ASSISTED_STRETCH, RECOVERY, or INTRO.
        PRD §2.3: "is a malformed request and is rejected with `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/create_service_missing_required_field
        """
        loc = fixtures.create_location(name="L")
        validate_error(api.create_service(
            {"location_id": loc["id"], "name": "Bad", "duration_minutes": 50,
             "credit_cost": 1, "list_price_cents": 6000}, SM),
            ApiErrorId.ERR_VALIDATION.value)

    def test_create_service_invalid_enum_kind_rejected(self, api):
        """PRD §3.1: a service carries "a `kind` of `ASSISTED_STRETCH`, `RECOVERY`, or `INTRO`, a `duration_minutes` greater than zero". A kind outside that set is a malformed request.
        PRD §2.3: "is a malformed request and is rejected with `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/create_service_invalid_enum_kind
        """
        loc = fixtures.create_location(name="L2")
        validate_error(api.create_service(
            {"location_id": loc["id"], "name": "X", "kind": "MASSAGE",
             "duration_minutes": 50, "credit_cost": 1, "list_price_cents": 6000}, SM),
            ApiErrorId.ERR_VALIDATION.value)

    def test_member_system_fields_generated(self, api):
        """PRD §3.2: "At registration the member's `status` is `ACTIVE`, `intro_completed` is false, `mobility_tier` is null, and `strike_score` is 0."

        Design: Corner/entities/member_system_fields_generated
        """
        loc = fixtures.create_location(name="L3")
        mem = validate_success(api.create_member(
            {"home_location_id": loc["id"], "full_name": "New", "email": "new@x.com"}, FD),
            expected_status=201)
        assert mem["intro_completed"] is False
        assert mem["strike_score"] == 0
        assert mem["mobility_tier"] is None
        assert mem["status"] == "ACTIVE"

    def test_addon_has_no_version_field(self, api):
        """PRD §2.4: "Three resources are leaner: `AddOn`, `NoShowEvent`, and `ClockState` carry only `id` and `created_at` — they have no `updated_at` and no `version` field, and those fields must be absent from their representations."
        PRD §3.5: "An `AddOn` is created with `voided` false".

        Design: Corner/entities/addon_immutable_no_version_field
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440)
        loc, flex, table, mem = s["loc"], s["flex"], s["table"], s["member"]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=1, list_price_cents=6000)
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        bk = fixtures.create_booking(mem["id"], loc["id"], svc["id"], flex["id"], table,
                                     "2026-04-20T10:00:00Z", "CREDIT_PACK", pack["id"])
        addon = validate_success(api.add_addon(
            bk["id"], factories.create_addon_payload(kind="PERCUSSION", price_cents=1500), FD),
            expected_status=201)
        assert addon["voided"] is False
        assert addon["kind"] == "PERCUSSION"
        assert_no_version_fields(addon)


# ===========================================================================
# endpoints
# ===========================================================================

class TestEndpoints:
    def test_list_bookings_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps how many items are returned ... Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

        Member with three bookings (one completed intro + two future), limit=1 ->
        has_more=true, total_count=3.

        Design: Corner/endpoints/list_bookings_pagination_envelope
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440,
            n_tables=2)
        loc, flex, mem = s["loc"], s["flex"], s["member"]
        t1, t2 = s["tables"][0], s["tables"][1]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=1, list_price_cents=6000)
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        fixtures.create_booking(mem["id"], loc["id"], svc["id"], flex["id"], t1,
                                "2026-04-20T10:00:00Z", "CREDIT_PACK", pack["id"])
        fixtures.create_booking(mem["id"], loc["id"], svc["id"], flex["id"], t2,
                                "2026-04-21T10:00:00Z", "CREDIT_PACK", pack["id"])
        resp = api.list_bookings(FD, params={"member_id": mem["id"], "limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 3, f"expected 3, got {meta['total_count']}"
        assert meta["has_more"] is True
        assert len(data) == 1

    def test_sweep_marks_expired_credit_pack(self, api):
        """PRD §3.8: "When the sweep finds an `ACTIVE` or `DEPLETED` pack whose `expires_utc` is at or before the clock, it sets `status` to `EXPIRED`, a terminal state".

        Pack expires 2026-04-15; clock moved to 04-16; sweep -> EXPIRED.

        Design: Corner/endpoints/no_show_sweep_marks_expired_creditpack
        """
        fixtures.set_clock("2026-04-10T00:00:00Z")
        loc = fixtures.create_location(name="Ex")
        mem = fixtures.create_member(loc["id"], full_name="Exm", email="exm@x.com")
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=5,
                                           base_unit_price_cents=100,
                                           expires_utc="2026-04-15T00:00:00Z")
        fixtures.set_clock("2026-04-16T00:00:00Z")
        validate_success(api.no_show_sweep(SM))
        p = validate_success(api.get_credit_pack(pack["id"], FD))
        assert p["status"] == "EXPIRED"

    def test_series_waterfall_skips_on_insufficient_credits(self, api):
        """PRD §3.9: "If that occurrence would collide on its `table_id`, collide on its `flexologist_id`, or find the funding wallet's `available_credits` below the service's `credit_cost`, the occurrence is skipped and the waterfall continues to the next occurrence".
        PRD §3.9: "After the pass, `generated_count` holds the number of bookings actually created, `skipped_count` holds the number skipped".

        4 occurrences, wallet 5 credits, credit_cost 2: generate 2 (holds 4),
        skip last 2 (1 < 2). available_credits=1.

        Design: Corner/endpoints/series_activate_waterfall_skips_on_insufficient_credits
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-05-01T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440)
        loc, flex, table, mem = s["loc"], s["flex"], s["table"], s["member"]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=2, list_price_cents=6000)
        ship = fixtures.create_membership(mem["id"], loc["id"], tier="STARTER",
                                          monthly_fee_cents=5000, included_credits=5,
                                          rollover_cap=0)
        series = validate_success(api.create_recurring_series(
            factories.create_recurring_series_payload(
                mem["id"], loc["id"], svc["id"], flex["id"], table, "MEMBERSHIP", ship["id"],
                "2026-05-20T10:00:00Z", 7, 4), FD), expected_status=201)
        activated = validate_success(api.activate_recurring_series(series["id"], FD))
        assert activated["status"] == "ACTIVE"
        assert activated["generated_count"] == 2
        assert activated["skipped_count"] == 2
        m = validate_success(api.get_membership(ship["id"], FD))
        assert m["available_credits"] == 1


# ===========================================================================
# rbac
# ===========================================================================

class TestRbac:
    def test_member_cannot_create_location(self, api):
        """PRD §2.1: "When a recognized role attempts an operation it is not permitted to perform, or when an ownership check fails, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.1: "only a `StudioManager` may author it."

        Design: Corner/rbac/member_cannot_create_location
        """
        loc = fixtures.create_location(name="Seed")
        mem = fixtures.create_member(loc["id"], full_name="Mm", email="mm@x.com")
        validate_error(api.create_location({"name": "Hacked"}, make_member_headers(mem["id"])),
                       ApiErrorId.ERR_FORBIDDEN.value)

    def test_member_cannot_cancel_another_members_booking(self, api):
        """PRD §2.1: "a member may act only on their own memberships, credit packs, bookings, series, add-ons, and no-show events."
        PRD §2.1: "or when an ownership check fails, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Member A cancelling Member B's booking is denied; B's booking unchanged.

        Design: Corner/rbac/member_cannot_act_on_other_members_booking
        """
        fixtures.set_clock("2026-04-10T00:00:00Z")
        loc = fixtures.create_location(open_minute_of_day=0, close_minute_of_day=1440)
        flex = fixtures.create_flexologist(loc["id"], certified_intro=True)
        table = fixtures.create_table(loc["id"])
        svc_intro = fixtures.create_service(loc["id"], name="Intro", kind="INTRO",
                                            duration_minutes=25, credit_cost=0, list_price_cents=0)
        memA = fixtures.create_member(loc["id"], full_name="Aa", email="aa@x.com")
        memB = fixtures.create_member(loc["id"], full_name="Bb", email="bb@x.com")
        packB = fixtures.create_credit_pack(memB["id"], loc["id"], pack_credits=10,
                                            base_unit_price_cents=100)
        bkB = fixtures.create_booking(memB["id"], loc["id"], svc_intro["id"], flex["id"],
                                      table["id"], "2026-04-20T10:00:00Z", "CREDIT_PACK", packB["id"])
        validate_error(api.cancel_booking(bkB["id"], make_member_headers(memA["id"])),
                       ApiErrorId.ERR_FORBIDDEN.value)
        again = validate_success(api.get_booking(bkB["id"], FD))
        assert again["schedule_status"] == "REQUESTED"

    def test_unauthenticated_missing_role_header(self, api):
        """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the four recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/unauthenticated_missing_role_header
        """
        validate_error(api.list_locations({}), ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_flexologist_cannot_complete_others_booking(self, api):
        """PRD §2.1: "A flexologist may read and complete only those bookings whose `flexologist_id` equals `X-User-ID`, and may read their own flexologist record; ownership checks compare the booking's `flexologist_id` to `X-User-ID`."

        Booking assigned to FlexA; FlexB attempts complete -> ERR_FORBIDDEN;
        booking stays CONFIRMED.

        Design: Corner/rbac/flexologist_complete_only_assigned_booking
        """
        fixtures.set_clock("2026-04-10T00:00:00Z")
        loc = fixtures.create_location(open_minute_of_day=0, close_minute_of_day=1440)
        flexA = fixtures.create_flexologist(loc["id"], full_name="FlexA", certified_intro=True)
        flexB = fixtures.create_flexologist(loc["id"], full_name="FlexB", certified_intro=True)
        table = fixtures.create_table(loc["id"])
        svc_intro = fixtures.create_service(loc["id"], name="Intro", kind="INTRO",
                                            duration_minutes=25, credit_cost=0, list_price_cents=0)
        mem = fixtures.create_member(loc["id"], full_name="Fcm", email="fcm@x.com")
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        bk = fixtures.create_confirmed_booking(mem["id"], loc["id"], svc_intro["id"], flexA["id"],
                                               table["id"], "2026-04-11T08:00:00Z",
                                               "CREDIT_PACK", pack["id"])
        fixtures.set_clock("2026-04-11T08:30:00Z")
        validate_error(api.complete_booking(
            bk["id"], make_flexologist_headers(flexB["id"]),
            factories.intro_assessment_payload()),
            ApiErrorId.ERR_FORBIDDEN.value)
        again = validate_success(api.get_booking(bk["id"], FD))
        assert again["schedule_status"] == "CONFIRMED"
