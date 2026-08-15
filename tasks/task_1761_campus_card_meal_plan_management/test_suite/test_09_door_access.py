"""Door access: zones, grants, the pinned access decision selector, and lazy
expiry."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_grant,
    create_holder,
    create_provisional_card,
    create_verified_card,
    create_zone,
    get_success_data,
    make_cardholder_headers,
    report_card_lost,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

SECURITY = TEST_USERS["security_officer_headers"]
DOOR = TEST_USERS["door_controller_headers"]
ADMIN = TEST_USERS["card_office_admin_headers"]

TUESDAY_10AM = "2026-08-25T10:00:00Z"  # Tuesday, inside a 480-1080 window
WIDE_WINDOW = [{"day_of_week": "TUE", "start_minute": 480, "end_minute": 1080}]


def _record_attempt(api, card_id, zone_id):
    return validate_success(
        api.create_access_event({"card_id": card_id, "zone_id": zone_id}, DOOR),
        201)


class TestAccessDecisions:
    def test_access_denied_provisional_card(self, api):
        """PRD §3.8: "If the card's `is_provisional` is true, the attempt is
        `DENIED` with `deny_reason` `CARD_PROVISIONAL`."
        PRD §3.8: "The decision is **computed data, not an API error**"

        Design: Corner/calculations/access_denied_provisional_card
        """
        set_clock(TUESDAY_10AM)
        holder = create_holder(university_id="U91013", full_name="Hal Prov",
                               email="hal@x.edu", holder_type="STUDENT_RESIDENT",
                               housing_status="ON_CAMPUS")
        card = create_provisional_card(holder["id"])
        zone = create_zone(zone_code="Z-PROV", building="Dorm",
                           access_windows=WIDE_WINDOW)
        create_grant(card["id"], zone["id"])

        event = _record_attempt(api, card["id"], zone["id"])
        assert event["decision"] == "DENIED"
        assert event["deny_reason"] == "CARD_PROVISIONAL"
        assert event["grant_id"] is None

    def test_access_denied_insufficient_clearance(self, api):
        """PRD §3.8: "If the selected grant's `clearance` ordinal is below the
        zone's `security_level` ordinal, the attempt is `DENIED` with `deny_reason`
        `INSUFFICIENT_CLEARANCE`, with the `grant_id` recorded."

        Design: Corner/calculations/access_denied_insufficient_clearance
        """
        set_clock(TUESDAY_10AM)
        holder, card = _holder_with_verified_card("U91014", "Ida Clear",
                                                  "ida@x.edu")
        zone = create_zone(zone_code="Z-SEC", building="Server",
                           security_level="RESTRICTED", access_windows=WIDE_WINDOW)
        grant = create_grant(card["id"], zone["id"], clearance="STANDARD")

        event = _record_attempt(api, card["id"], zone["id"])
        assert event["decision"] == "DENIED"
        assert event["deny_reason"] == "INSUFFICIENT_CLEARANCE"
        assert event["grant_id"] == grant["id"]

    def test_access_denied_outside_schedule(self, api):
        """PRD §3.8: "If the attempt instant matches no access window — same
        `day_of_week`, and the minute of day from `start_minute` up to but not
        including `end_minute` — the attempt is `DENIED` with `deny_reason`
        `OUTSIDE_SCHEDULE`, with the `grant_id` recorded."

        Design: Corner/calculations/access_denied_outside_schedule
        """
        set_clock(TUESDAY_10AM)  # Tuesday attempt vs a Monday-only window
        holder, card = _holder_with_verified_card("U91015", "Jon Sched",
                                                  "jon@x.edu")
        zone = create_zone(zone_code="Z-SCH", building="Office",
                           security_level="ELEVATED",
                           access_windows=[{"day_of_week": "MON",
                                            "start_minute": 480,
                                            "end_minute": 1080}])
        grant = create_grant(card["id"], zone["id"], clearance="ELEVATED")

        event = _record_attempt(api, card["id"], zone["id"])
        assert event["decision"] == "DENIED"
        assert event["deny_reason"] == "OUTSIDE_SCHEDULE"
        assert event["grant_id"] == grant["id"]

    def test_access_denied_zone_decommissioned(self, api):
        """PRD §3.8: "Decommissioning moves a zone to `DECOMMISSIONED` and revokes
        every grant on the zone in `ACTIVE` or `SUSPENDED`."
        PRD §3.8: "If the zone is not `ACTIVE`, the attempt is `DENIED` with
        `deny_reason` `ZONE_DECOMMISSIONED`."

        Design: Corner/calculations/access_denied_zone_decommissioned
        """
        set_clock(TUESDAY_10AM)
        holder, card = _holder_with_verified_card("U91016", "Kat Dec",
                                                  "kat@x.edu")
        zone = create_zone(zone_code="Z-DEC", building="OldHall",
                           access_windows=WIDE_WINDOW)
        grant = create_grant(card["id"], zone["id"])
        get_success_data(api.decommission_door_zone(zone["id"], SECURITY))

        grant_now = get_success_data(api.get_access_grant(grant["id"], SECURITY))
        assert grant_now["status"] == "REVOKED"

        event = _record_attempt(api, card["id"], zone["id"])
        assert event["decision"] == "DENIED"
        assert event["deny_reason"] == "ZONE_DECOMMISSIONED"

    def test_frozen_card_door_attempt_denied_card_not_active(self, api):
        """PRD §3.8: "If the card's `lifecycle_status` is not `ACTIVE`, the
        attempt is `DENIED` with `deny_reason` `CARD_NOT_ACTIVE`"
        PRD §3.2: "Reporting moves the card `ACTIVE` → `LOST_FROZEN`, increments
        the card's `lost_or_stolen_report_count` by 1, and suspends every `ACTIVE`
        access grant on the card with `suspended_reason` `CARD_FROZEN`."

        Design: Corner/state_machines/frozen_card_door_attempt_denied_card_not_active
        """
        set_clock(TUESDAY_10AM)
        holder = create_holder(university_id="U96001", full_name="Kim Door",
                               email="kimd@x.edu", holder_type="STUDENT_RESIDENT",
                               housing_status="ON_CAMPUS")
        card = create_provisional_card(holder["id"])
        zone = create_zone(zone_code="Z-FRZ", building="Dorm",
                           access_windows=WIDE_WINDOW)
        grant = create_grant(card["id"], zone["id"])
        report_card_lost(card["id"], holder["id"])

        event = _record_attempt(api, card["id"], zone["id"])
        assert event["decision"] == "DENIED"
        assert event["deny_reason"] == "CARD_NOT_ACTIVE"

        grant_now = get_success_data(api.get_access_grant(grant["id"], SECURITY))
        assert grant_now["status"] == "SUSPENDED"
        assert grant_now["suspended_reason"] == "CARD_FROZEN"


class TestGrantLifecycle:
    def test_grant_lazy_expiry_and_suspended_cycle(self, api):
        """PRD §3.8: "Expiry is lazy from both `ACTIVE` and `SUSPENDED`: whenever
        an access attempt or grant action touches a grant whose `valid_until` has
        passed, it flips to `EXPIRED`."
        PRD §3.8: "Suspending an `ACTIVE` grant marks it `SUSPENDED` with
        `suspended_reason` `MANUAL`" and the candidate set takes grants "in
        `ACTIVE` status whose half-open validity contains the attempt instant", and
        "If the candidate set is empty, the attempt is `DENIED` with `deny_reason`
        `NO_ACTIVE_GRANT` and a null `grant_id`."

        Design: Corner/state_machines/grant_lazy_expiry_and_suspended_cycle
        """
        set_clock(TUESDAY_10AM)
        holder, card = _holder_with_verified_card("U90019", "Tom Grant",
                                                  "tom@x.edu")
        zx = create_zone(zone_code="Z-EXP", building="Lab",
                         access_windows=[{"day_of_week": "TUE", "start_minute": 480,
                                          "end_minute": 1080},
                                         {"day_of_week": "WED", "start_minute": 480,
                                          "end_minute": 1080}])
        zy = create_zone(zone_code="Z-CYC", building="Gym",
                         access_windows=WIDE_WINDOW)
        gx = create_grant(card["id"], zx["id"],
                          valid_until="2026-09-01T00:00:00Z")
        gy = create_grant(card["id"], zy["id"])

        get_success_data(api.suspend_access_grant(gy["id"], SECURITY))
        denied = _record_attempt(api, card["id"], zy["id"])
        assert denied["decision"] == "DENIED"
        assert denied["deny_reason"] == "NO_ACTIVE_GRANT"

        get_success_data(api.reinstate_access_grant(gy["id"], SECURITY))
        granted = _record_attempt(api, card["id"], zy["id"])
        assert granted["decision"] == "GRANTED"
        assert granted["grant_id"] == gy["id"]

        set_clock("2026-09-02T10:00:00Z")  # past gx.valid_until
        expired_attempt = _record_attempt(api, card["id"], zx["id"])
        assert expired_attempt["decision"] == "DENIED"
        assert expired_attempt["deny_reason"] == "NO_ACTIVE_GRANT"
        gx_now = get_success_data(api.get_access_grant(gx["id"], SECURITY))
        assert gx_now["status"] == "EXPIRED"

    def test_doorcontroller_cannot_manage_zones(self, api):
        """PRD §4: door-zone creation's authorized role list contains only
        SecurityOfficer. PRD §2.1: "If the headers are well-formed but the named
        role is not in the calling endpoint's authorized role list, the request is
        rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/rbac/doorcontroller_cannot_manage_zones
        """
        resp = api.create_door_zone(
            {"zone_code": "Z-DC", "building": "B", "security_level": "STANDARD",
             "access_windows": [{"day_of_week": "MON", "start_minute": 480,
                                 "end_minute": 1080}]}, DOOR)
        validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED)


class TestGrantOverlapSemantics:
    def test_grant_half_open_overlap_adjacency(self, api):
        """PRD §3.8: "Creating a grant whose interval intersects an existing
        `ACTIVE` or `SUSPENDED` grant on the same card and zone is rejected with
        `ERR_GRANT_OVERLAP`; because the intervals are half-open, adjacency — one
        grant ending exactly where another begins — is permitted."

        Design: Difficulty/resource_temporal_overlap/grant_half_open_overlap_adjacency
        """
        card, zone = _card_and_zone(api)
        adjacent = api.create_access_grant(
            card["id"],
            {"zone_id": zone["id"], "clearance": "STANDARD",
             "valid_from": "2026-10-01T00:00:00Z",
             "valid_until": "2026-11-01T00:00:00Z"}, SECURITY)
        created = validate_success(adjacent, 201)
        assert created["status"] == "ACTIVE"

    def test_grant_intersecting_existing_rejected(self, api):
        """PRD §3.8: "Creating a grant whose interval intersects an existing
        `ACTIVE` or `SUSPENDED` grant on the same card and zone is rejected with
        `ERR_GRANT_OVERLAP`; because the intervals are half-open, adjacency — one
        grant ending exactly where another begins — is permitted."

        Design: Difficulty/resource_temporal_overlap/grant_half_open_overlap_adjacency
        """
        card, zone = _card_and_zone(api)
        # Adjacent grant is permitted (valid_from == existing valid_until).
        validate_success(api.create_access_grant(
            card["id"],
            {"zone_id": zone["id"], "clearance": "STANDARD",
             "valid_from": "2026-10-01T00:00:00Z",
             "valid_until": "2026-11-01T00:00:00Z"}, SECURITY), 201)

        overlapping = api.create_access_grant(
            card["id"],
            {"zone_id": zone["id"], "clearance": "STANDARD",
             "valid_from": "2026-09-15T00:00:00Z",
             "valid_until": "2026-12-01T00:00:00Z"}, SECURITY)
        validate_error(overlapping, ApiErrorId.ERR_GRANT_OVERLAP)

        grants, _ = validate_paginated(
            api.list_access_grants(SECURITY, {"card_id": card["id"],
                                              "zone_id": zone["id"]}))
        assert len(grants) == 2


class TestGrantReinstateCardDependency:
    def test_grant_reinstate_requires_card_active(self, api):
        """PRD §3.8: "Reinstating a `SUSPENDED` grant requires the card's
        `lifecycle_status` to be `ACTIVE` (`ERR_CARD_NOT_ACTIVE` otherwise) and
        the clock to read earlier than the grant's `valid_until`"

        Design: Difficulty/cross_entity_state_dependency/grant_reinstate_requires_card_active
        """
        grant = _setup_suspended_by_lost_card(api)
        resp = api.reinstate_access_grant(grant["id"], SECURITY)
        validate_error(resp, ApiErrorId.ERR_CARD_NOT_ACTIVE)

    def test_grant_reinstate_rejection_leaves_grant_suspended(self, api):
        """PRD §3.2: "A lost card that turns up can be unfrozen by its owner:
        unfreezing moves `LOST_FROZEN` → `ACTIVE`, provided the holder's `status`
        is `ACTIVE` (otherwise `ERR_HOLDER_NOT_ACTIVE`), and restores every grant
        suspended with `suspended_reason` `CARD_FROZEN` back to `ACTIVE`."
        PRD §3.8: "Reinstating a `SUSPENDED` grant requires the card's
        `lifecycle_status` to be `ACTIVE` (`ERR_CARD_NOT_ACTIVE` otherwise)"

        Design: Difficulty/cross_entity_state_dependency/grant_reinstate_requires_card_active
        """
        grant = _setup_suspended_by_lost_card(api)
        api.reinstate_access_grant(grant["id"], SECURITY)
        still = get_success_data(api.get_access_grant(grant["id"], SECURITY))
        assert still["status"] == "SUSPENDED"
        assert still["suspended_reason"] == "CARD_FROZEN"


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------

def _holder_with_verified_card(university_id, full_name, email):
    holder = create_holder(university_id=university_id, full_name=full_name,
                           email=email, holder_type="STAFF",
                           housing_status="OFF_CAMPUS")
    card = create_verified_card(holder["id"])
    return holder, card


def _card_and_zone(api):
    """Provisional ACTIVE card plus zone GYM with an existing grant over
    [2026-09-01, 2026-10-01)."""
    set_clock(TUESDAY_10AM)
    holder = create_holder(university_id="U9001", full_name="Rae Resident",
                           email="rae@x.edu", holder_type="STUDENT_RESIDENT",
                           housing_status="ON_CAMPUS")
    card = create_provisional_card(holder["id"])
    zone = create_zone(zone_code="GYM", building="Athletics",
                       access_windows=[{"day_of_week": "MON", "start_minute": 360,
                                        "end_minute": 1320}])
    create_grant(card["id"], zone["id"],
                 valid_from="2026-09-01T00:00:00Z",
                 valid_until="2026-10-01T00:00:00Z")
    return card, zone


def _setup_suspended_by_lost_card(api):
    """Verified card + zone + ACTIVE grant, then the card is reported lost so the
    grant suspends with CARD_FROZEN."""
    set_clock(TUESDAY_10AM)
    holder = create_holder(university_id="U8002", full_name="Quinn Resident",
                           email="quinn@x.edu", holder_type="STUDENT_RESIDENT",
                           housing_status="ON_CAMPUS")
    card = create_verified_card(holder["id"])
    zone = create_zone(zone_code="LIB-X", building="Library",
                       access_windows=WIDE_WINDOW)
    grant = create_grant(card["id"], zone["id"])
    report_card_lost(card["id"], holder["id"])
    return grant
