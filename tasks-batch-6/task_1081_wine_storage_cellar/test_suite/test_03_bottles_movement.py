"""Bottle deposits, drink-window derivation, and movement-request lifecycle guards."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    setup_active_member_with_locker, store_bottle, open_consignment,
    create_intake_request, schedule_maintenance,
    create_bottle_payload, make_cellar_member_headers,
)

MGR = TEST_USERS["cellar_manager_headers"]
BROKER = TEST_USERS["auction_broker_headers"]


# --------------------------------------------------------------------------- #
# Queue A — boundary_precision_check / drink_window_year_inclusive_boundary
# --------------------------------------------------------------------------- #
def test_drink_window_equal_start_year_is_in_window(api):
    """PRD §3.3: "otherwise — including the boundary years where the current year equals
    the start year or the end year — the status is `IN_WINDOW`."

    Design: Difficulty/boundary_precision_check/drink_window_year_inclusive_boundary
    """
    member, locker = setup_active_member_with_locker(
        api, size_tier="MEDIUM", climate_zone="RED", capacity=3, tier="RESERVE"
    )
    bottle = store_bottle(
        api, locker["id"], member["id"], wine_name="Just Ready",
        drink_window_start_year=2026, drink_window_end_year=2040, provenance_status="DOCUMENTED",
    )
    b = validate_success(api.get_bottle(bottle["id"], MGR))
    assert b["drink_window_status"] == "IN_WINDOW", (
        f"year == start_year is inclusive IN_WINDOW, got {b['drink_window_status']}"
    )


def test_list_succeeds_at_inclusive_drink_window_boundary(api):
    """PRD §3.7: "its drink window must be open — a bottle whose `drink_window_status` is
    `TOO_YOUNG` is refused with `ERR_DRINK_WINDOW_NOT_OPEN`. Listing moves the consignment
    from `DRAFT` to `LISTED` and transitions the bottle from `STORED` to `CONSIGNED`."

    Design: Difficulty/boundary_precision_check/drink_window_year_inclusive_boundary
    """
    member, locker = setup_active_member_with_locker(
        api, size_tier="MEDIUM", climate_zone="RED", capacity=3, tier="RESERVE"
    )
    bottle = store_bottle(
        api, locker["id"], member["id"], wine_name="Just Ready",
        drink_window_start_year=2026, drink_window_end_year=2040, provenance_status="DOCUMENTED",
    )
    cn = open_consignment(api, member["id"], bottle["id"], reserve_price_cents=2_000_000)
    listed = validate_success(api.list_consignment(cn["id"], BROKER))
    assert listed["status"] == "LISTED", (
        f"list should succeed at inclusive boundary, got {listed['status']}"
    )


# --------------------------------------------------------------------------- #
# Queue B — calculations / drink_window_past_peak_computed
# --------------------------------------------------------------------------- #
def test_drink_window_past_peak_computed(api):
    """PRD §3.3: "when the current year is later than `drink_window_end_year` the status
    is `PAST_PEAK`".

    Design: Corner/calculations/drink_window_past_peak_computed
    """
    member, locker = setup_active_member_with_locker(
        api, size_tier="SMALL", climate_zone="RED", capacity=2, tier="STANDARD"
    )
    bottle = store_bottle(
        api, locker["id"], member["id"], wine_name="Over Hill", vintage_year=2005,
        drink_window_start_year=2010, drink_window_end_year=2020,
    )
    b = validate_success(api.get_bottle(bottle["id"], MGR))
    assert b["drink_window_status"] == "PAST_PEAK", (
        f"year > end_year is PAST_PEAK, got {b['drink_window_status']}"
    )


# --------------------------------------------------------------------------- #
# Queue B — state_machines / approve_after_reject_returns_invalid_state
# --------------------------------------------------------------------------- #
def test_approve_after_reject_returns_invalid_state(api):
    """PRD §3.3: "Rejection moves a `REQUESTED` request to `REJECTED`".
    PRD §2.9: "on state-transition endpoints, a resource that is not in a legal state for
    the requested transition yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/approve_after_reject_returns_invalid_state
    """
    member, locker = setup_active_member_with_locker(
        api, size_tier="LARGE", climate_zone="RED", capacity=5, tier="RESERVE"
    )
    mr = create_intake_request(api, member["id"], locker["id"], quantity=2)
    validate_success(api.reject_movement_request(mr["id"], MGR))
    validate_error(api.approve_movement_request(mr["id"], MGR), ApiErrorId.ERR_INVALID_STATE.value)


# --------------------------------------------------------------------------- #
# Queue B — errors / approve_movement_on_maintenance_locker_returns_in_maintenance
# --------------------------------------------------------------------------- #
def test_approve_movement_on_maintenance_locker_returns_in_maintenance(api):
    """PRD §3.3: "Approval moves a request from `REQUESTED` to `APPROVED`, but only when
    the requesting member is `ACTIVE` — otherwise `ERR_MEMBER_NOT_ACTIVE` — and the locker
    is not `FROZEN`, `MAINTENANCE`, or `RETIRED` — otherwise `ERR_LOCKER_IN_MAINTENANCE`."

    Design: Corner/errors/approve_movement_on_maintenance_locker_returns_in_maintenance
    """
    member, locker = setup_active_member_with_locker(
        api, size_tier="LARGE", climate_zone="RED", capacity=5, tier="RESERVE"
    )
    mr = create_intake_request(api, member["id"], locker["id"], quantity=2)
    window = schedule_maintenance(
        api, locker["id"], "2026-07-01T10:00:00Z", "2026-07-01T12:00:00Z", reason="compressor"
    )
    validate_success(api.activate_maintenance_window(window["id"], MGR))  # locker -> MAINTENANCE
    validate_error(
        api.approve_movement_request(mr["id"], MGR), ApiErrorId.ERR_LOCKER_IN_MAINTENANCE.value
    )


# --------------------------------------------------------------------------- #
# Queue B — entities / bottle_create_missing_required_field_returns_validation
# --------------------------------------------------------------------------- #
def test_bottle_create_missing_wine_name_returns_validation(api):
    """PRD §3.3: "The deposit names the target `locker_id` and describes the wine: its
    `wine_name` (producer and cuvée label), `vintage_year`, `varietal`, and `format_ml`".
    PRD §2.9: "on write endpoints, a missing required field, an illegal enum value, or an
    integer outside its stated constraint yields `ERR_VALIDATION`."

    Design: Corner/entities/bottle_create_missing_required_field_returns_validation
    """
    member, locker = setup_active_member_with_locker(
        api, size_tier="SMALL", climate_zone="RED", capacity=2, tier="STANDARD"
    )
    payload = create_bottle_payload(locker_id=locker["id"])
    payload.pop("wine_name")
    validate_error(
        api.create_bottle(payload, make_cellar_member_headers(member["id"])),
        ApiErrorId.ERR_VALIDATION.value,
    )
