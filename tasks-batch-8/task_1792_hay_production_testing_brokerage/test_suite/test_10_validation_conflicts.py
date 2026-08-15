"""Validation priority conflicts, half-open window overlap, duplicate-key
constraints, authentication ordering, and suspended-principal guards.

Covers PRD §2.6 (validation order), §2.1 (authentication), and §3.1/§3.3
(uniqueness and temporal rules).
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_cutting,
    create_freight_lane,
    create_grower,
    create_market_index,
    make_grower_headers,
    setup_scheduled_cutting,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId

ADMIN = TEST_USERS["admin_headers"]
OPS = TEST_USERS["ops_headers"]


# ===========================================================================
# priority_pair_validation_conflict / window_overlap_beats_duplicate_number
# ===========================================================================

class TestWindowOverlapBeatsDuplicateNumber:
    def _setup_existing_cutting(self):
        """Cutting #1 on window [2026-06-10, 2026-06-20)."""
        return setup_scheduled_cutting(
            field_overrides={"forage_type": "GRASS"},
            cutting_overrides={
                "planned_window_start": "2026-06-10",
                "planned_window_end": "2026-06-20",
            },
        )

    def _double_violation_payload(self, field_id):
        """Cutting #1 again on [2026-06-15, 2026-06-25): collides on number
        AND overlaps the existing window."""
        return {
            "field_id": field_id, "cutting_number": 1, "season_year": 2026,
            "planned_window_start": "2026-06-15",
            "planned_window_end": "2026-06-25",
        }

    def test_temporal_error_beats_uniqueness_error(self, api):
        """PRD §2.6: "Validations run in a strict priority order, and the
        first failing rule — the lowest priority number — wins the response."
        PRD §2.6 places business temporal rules (`ERR_FIELD_WINDOW_OVERLAP`,
        ...) at priority 8, ahead of business constraints
        (`ERR_DUPLICATE_CUTTING_NUMBER`, ...) at priority 10.

        A create that violates both reports the temporal error.

        Design: Difficulty/priority_pair_validation_conflict/window_overlap_beats_duplicate_number
        """
        grower, field, _cutting = self._setup_existing_cutting()
        resp = api_client.create_cutting(
            self._double_violation_payload(field["id"]),
            make_grower_headers(grower["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FIELD_WINDOW_OVERLAP)

    def test_rejected_double_violation_persists_nothing(self, api):
        """PRD §3.1: "a new cutting's planned window must not overlap any
        non-abandoned cutting on the same field in the same season ... while
        any true overlap is rejected with `ERR_FIELD_WINDOW_OVERLAP`"; a
        rejected creation creates nothing, so the field still lists exactly
        one cutting.

        Design: Difficulty/priority_pair_validation_conflict/window_overlap_beats_duplicate_number
        """
        grower, field, _cutting = self._setup_existing_cutting()
        resp = api_client.create_cutting(
            self._double_violation_payload(field["id"]),
            make_grower_headers(grower["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FIELD_WINDOW_OVERLAP)
        cuttings, meta = validate_paginated(
            api_client.list_cuttings(ADMIN, params={"field_id": field["id"]})
        )
        assert meta["total_count"] == 1
        assert len(cuttings) == 1


# ===========================================================================
# resource_temporal_overlap / cutting_window_half_open_overlap
# ===========================================================================

class TestCuttingWindowHalfOpenOverlap:
    def _setup_existing_cutting(self):
        return setup_scheduled_cutting(
            field_overrides={"forage_type": "GRASS"},
            cutting_overrides={
                "planned_window_start": "2026-06-10",
                "planned_window_end": "2026-06-20",
            },
        )

    def test_adjacent_window_allowed(self, api):
        """PRD §3.1: "windows are treated as half-open intervals — inclusive
        of the start, exclusive of the end — so back-to-back windows where
        the previous window's end equals the next window's start are
        permitted".

        [2026-06-20, 2026-07-01) touches the existing [2026-06-10,
        2026-06-20) only at the boundary date and schedules cleanly.

        Design: Difficulty/resource_temporal_overlap/cutting_window_half_open_overlap
        """
        grower, field, _cutting = self._setup_existing_cutting()
        adjacent = create_cutting(
            field["id"], grower["id"], cutting_number=2,
            planned_window_start="2026-06-20", planned_window_end="2026-07-01",
        )
        assert adjacent["status"] == "SCHEDULED"

    def test_one_day_overlap_rejected(self, api):
        """PRD §3.1: "back-to-back windows where the previous window's end
        equals the next window's start are permitted, while any true overlap
        is rejected with `ERR_FIELD_WINDOW_OVERLAP`."

        [2026-06-19, 2026-06-28) shares the day 2026-06-19 with the existing
        window and is rejected.

        Design: Difficulty/resource_temporal_overlap/cutting_window_half_open_overlap
        """
        grower, field, _cutting = self._setup_existing_cutting()
        resp = api_client.create_cutting(
            {
                "field_id": field["id"], "cutting_number": 3,
                "season_year": 2026,
                "planned_window_start": "2026-06-19",
                "planned_window_end": "2026-06-28",
            },
            make_grower_headers(grower["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FIELD_WINDOW_OVERLAP)


# ===========================================================================
# Corner/validations / duplicate market index and freight lane
# ===========================================================================

def test_duplicate_market_index_rejected(api):
    """PRD §3.3: "The triple of region, forage type, and effective date is
    unique; a duplicate posting is rejected with
    `ERR_DUPLICATE_MARKET_INDEX`."

    Design: Corner/validations/duplicate_market_index_rejected
    """
    create_market_index()
    resp = api_client.create_market_index(
        {
            "region_code": "OR-WILLAMETTE", "forage_type": "ALFALFA",
            "effective_date": "2026-05-01", "price_per_ton_cents": 21000,
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_MARKET_INDEX)


def test_duplicate_freight_lane_rejected(api):
    """PRD §3.3: "the ordered pair must be unique, with duplicates rejected
    as `ERR_DUPLICATE_FREIGHT_LANE`".

    Design: Corner/validations/duplicate_freight_lane_rejected
    """
    create_freight_lane()
    resp = api_client.create_freight_lane(
        {
            "origin_region_code": "OR-WILLAMETTE",
            "dest_region_code": "CA-NORTH", "distance_miles": 430,
            "rate_per_mile_cents": 360, "min_charge_cents": 95000,
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_FREIGHT_LANE)


# ===========================================================================
# Corner/validations / authentication
# ===========================================================================

def test_unauthenticated_request_rejected(api):
    """PRD §2.1: "A request whose headers are missing, or whose `X-User-Role`
    value is not one of these five declared roles, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/unauthenticated_request_rejected
    """
    resp = api_client.get_grower(NON_EXISTENT_UUID, headers=None)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_auth_priority_beats_not_found(api):
    """PRD §2.6: "the first failing rule — the lowest priority number — wins
    the response", with authentication at priority 1 ahead of resource
    existence at priority 4.

    A request that is both unauthenticated AND targets a missing quote
    reports the auth error, not 404.

    Design: Corner/validations/auth_priority_beats_not_found
    """
    resp = api_client.get_quote(NON_EXISTENT_UUID, headers=None)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


# ===========================================================================
# Corner/validations / suspended_grower_cannot_add_field
# ===========================================================================

def test_suspended_grower_cannot_add_field(api):
    """PRD §3.1: "creation is refused with `ERR_GROWER_SUSPENDED` when the
    referenced grower is no longer `ACTIVE`".

    Even a PlatformAdmin cannot add a field to a suspended grower.

    Design: Corner/validations/suspended_grower_cannot_add_field
    """
    grower = create_grower(name="Grower T")
    validate_success(api_client.suspend_grower(grower["id"], ADMIN))
    resp = api_client.create_field(
        {
            "grower_id": grower["id"], "name": "Field T", "acres": 12.0,
            "forage_type": "GRASS",
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_GROWER_SUSPENDED)


# ===========================================================================
# Corner/validations / grower_double_suspend_invalid_state
# ===========================================================================

def test_grower_double_suspend_invalid_state(api):
    """PRD §3.1: "A `PlatformAdmin` may suspend an `ACTIVE` grower —
    attempting the suspension from any other state is rejected with
    `ERR_INVALID_STATE`".

    Design: Corner/validations/grower_double_suspend_invalid_state
    """
    grower = create_grower(name="Grower AC")
    validate_success(api_client.suspend_grower(grower["id"], ADMIN))
    resp = api_client.suspend_grower(grower["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
