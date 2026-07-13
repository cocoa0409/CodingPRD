"""Core CRUD, creation validation, not-found, invalid-state transitions,
list filtering, and pagination bounds."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    set_clock,
    create_marina,
    create_berth,
    create_boater,
    create_vessel,
    apply_permit,
    setup_active_permit,
    setup_offered_permit,
    create_marina_payload,
    get_permit,
)

HARBOR = TEST_USERS["harbormaster_headers"]


def test_create_marina_returns_201_with_zeroed_counters(api):
    """PRD §3.1: "A newly created marina begins with all six occupancy counters at
    zero."

    Design: Corner/entities/create_marina_returns_201_with_zeroed_counters
    """
    data = validate_success(
        api.create_marina(
            create_marina_payload(name="New Marina", liveaboard_cap=3), HARBOR
        ),
        expected_status=201,
    )
    assert data["available_slip_count"] == 0
    assert data["occupied_slip_count"] == 0
    assert data["liveaboard_count"] == 0
    assert data["waitlist_length"] == 0


def test_marina_negative_liveaboard_cap_rejected(api):
    """PRD §3.1: "The `liveaboard_cap` must be zero or greater — a negative cap is
    rejected with `ERR_LIVEABOARD_CAP_NEGATIVE` (HTTP 400)"

    Design: Corner/entities/marina_negative_liveaboard_cap_returns_400
    """
    validate_error(
        api.create_marina(create_marina_payload(liveaboard_cap=-1), HARBOR),
        ApiErrorId.ERR_LIVEABOARD_CAP_NEGATIVE,
    )


def test_marina_invalid_date_range_rejected(api):
    """PRD §3.1: "the season must be well-formed, so a `season_end_date` earlier
    than `season_start_date` is rejected with `ERR_INVALID_DATE_RANGE` (HTTP 400)."

    Design: Corner/entities/marina_invalid_date_range_returns_400
    """
    validate_error(
        api.create_marina(
            create_marina_payload(season_start_date="2026-10-31", season_end_date="2026-05-01"),
            HARBOR,
        ),
        ApiErrorId.ERR_INVALID_DATE_RANGE,
    )


def test_create_boater_missing_residency_rejected(api):
    """PRD §2.9: "Malformed bodies, missing required fields, and invalid enum
    values are rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_boater_missing_required_field_returns_400
    """
    validate_error(
        api.create_boater({"full_name": "No Res", "email": "nores@example.com"}, HARBOR),
        ApiErrorId.ERR_VALIDATION,
    )


def test_get_missing_permit_returns_not_found(api):
    """PRD §2.8: "The system validates every path and body reference — `marina_id`,
    `boater_id`, `vessel_id`, `berth_id`, `round_id`, `invoice_id`, `permit_id`,
    and the like — in left-to-right order, and rejects the request with
    `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an
    existing resource."

    Design: Corner/entities/get_permit_not_found_returns_404
    """
    validate_error(
        api.get_permit(NON_EXISTENT_UUID, HARBOR),
        ApiErrorId.ERR_NOT_FOUND,
    )


def test_cancel_active_permit_returns_invalid_state(api):
    """PRD §2.9: "Fifth, the target resource's state is checked against the state
    machine for the requested transition, yielding `ERR_INVALID_STATE` (HTTP 409)
    when the resource is not in a legal from-state."
    PRD §3.3: "The applicant may withdraw a `WAITLISTED` permit, which moves it to
    the terminal `CANCELLED` state and lowers `waitlist_length` by one."

    Design: Corner/state_machines/cancel_active_permit_returns_invalid_state
    """
    b = setup_active_permit(api, clock="2026-05-15T00:00:00Z", vessel_overrides={"length_ft": 30})
    validate_error(api.cancel_permit(b["permit"]["id"], HARBOR), ApiErrorId.ERR_INVALID_STATE)
    assert get_permit(api, b["permit"]["id"])["status"] == "ACTIVE"


def test_revoke_waitlisted_permit_returns_not_active(api):
    """PRD §3.5: "Revocation, transfer, and reassignment all require the permit to
    be in the appropriate `ACTIVE` or `SUSPENDED` posture; attempting them on a
    permit that is not in the required state is rejected with `ERR_PERMIT_NOT_ACTIVE`
    (HTTP 409)."

    Design: Corner/state_machines/revoke_waitlisted_permit_returns_not_active
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    marina = create_marina(api)  # no berths -> application cannot be offered
    boater = create_boater(api)
    vessel = create_vessel(api, boater["id"], length_ft=30)
    permit = apply_permit(api, marina["id"], boater["id"], vessel["id"])
    assert permit["status"] == "WAITLISTED"
    validate_error(api.revoke_permit(permit["id"], HARBOR), ApiErrorId.ERR_PERMIT_NOT_ACTIVE)
    assert get_permit(api, permit["id"])["status"] == "WAITLISTED"


def test_list_permits_filtered_by_boater(api):
    """PRD §3.3: "Permits can be listed and filtered by `marina_id`, `boater_id`,
    `vessel_id`, `berth_id`, and `status`."

    Design: Corner/endpoints/list_permits_filtered_by_boater_id
    """
    b = setup_offered_permit(api, clock="2026-05-01T00:00:00Z")
    boater_id = b["boater"]["id"]
    data, meta = validate_paginated(api.list_permits(HARBOR, params={"boater_id": boater_id}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == b["permit"]["id"]


def test_list_berths_invalid_limit_rejected(api):
    """PRD §2.3: "A `limit` outside 1 through 100, or a negative `offset`, is
    rejected with `ERR_PAGINATION_INVALID` (HTTP 400)."

    Design: Corner/endpoints/list_berths_pagination_invalid_limit_returns_400
    """
    marina = create_marina(api)
    create_berth(api, marina["id"])
    validate_error(
        api.list_berths(HARBOR, params={"marina_id": marina["id"], "limit": 0}),
        ApiErrorId.ERR_PAGINATION_INVALID,
    )
