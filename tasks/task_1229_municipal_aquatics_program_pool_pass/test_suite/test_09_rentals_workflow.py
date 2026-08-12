"""Facility rental workflow: exclusive-use overlap, validation priority,
terminal-state lockdown, and the OCC guard on approval (PRD §2.7, §3.7)."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    TEST_USERS, ApiErrorId,
    assert_rental,
    create_rental_payload, create_admission_payload,
    make_facility, make_season, make_pass_holder, make_rental,
    make_admission, approve_rental, set_clock, facility_version,
    get_facility, make_passholder_headers,
)

MANAGER = TEST_USERS["manager_headers"]
GATE = TEST_USERS["gate_headers"]


def _two_holders():
    a = make_pass_holder(full_name="A", date_of_birth="1990-01-01T00:00:00Z")
    b = make_pass_holder(full_name="B", date_of_birth="1990-01-01T00:00:00Z")
    return a, b


def test_rental_overlap_takes_priority_over_capacity(api):
    """PRD §2.10: "11. Rental does not overlap another approved or checked-in
    rental at the same facility (`ERR_RENTAL_OVERLAP`)."
    PRD §2.10: "19. Rental capacity and lane exclusivity
    (`ERR_RENTAL_CAPACITY`)."
    PRD §2.10: "When several rules could reject the same request, they are
    evaluated in a fixed priority order so the rejection a client sees is
    stable".

    Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_fiscal_rental_approve
    """
    facility = make_facility(max_bather_capacity=20, lap_lane_count=2)
    a, b = _two_holders()
    set_clock("2026-07-20T00:00:00Z")
    r1 = make_rental(
        facility["id"], a["id"],
        party_size=10,
        start_datetime="2026-08-01T14:00:00Z",
        end_datetime="2026-08-01T16:00:00Z",
    )
    approve_rental(r1["id"], facility["id"])
    # Overlaps r1 AND exceeds capacity (50 > 20): overlap must be reported.
    r2 = make_rental(
        facility["id"], b["id"],
        party_size=50,
        start_datetime="2026-08-01T15:00:00Z",
        end_datetime="2026-08-01T17:00:00Z",
    )
    fv = facility_version(facility["id"])
    resp = api.approve_rental(
        r2["id"], {"expected_facility_version": fv}, MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_RENTAL_OVERLAP)
    r2_after = validate_success(api.get_rental(r2["id"], MANAGER))
    assert r2_after["status"] == "REQUESTED"


def test_rental_capacity_rejected_without_overlap(api):
    """PRD §3.7: "Beyond the version check, approval requires the facility to
    be `OPEN` or `RESTRICTED`, the `party_size` not to exceed
    `max_bather_capacity`, and the rental window not to overlap any other
    `APPROVED` or `CHECKED_IN` rental at the same facility".
    PRD §2.10: "19. Rental capacity and lane exclusivity
    (`ERR_RENTAL_CAPACITY`)."

    Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_fiscal_rental_approve
    """
    facility = make_facility(max_bather_capacity=20, lap_lane_count=2)
    a, b = _two_holders()
    set_clock("2026-07-20T00:00:00Z")
    r1 = make_rental(
        facility["id"], a["id"],
        party_size=10,
        start_datetime="2026-08-01T14:00:00Z",
        end_datetime="2026-08-01T16:00:00Z",
    )
    approve_rental(r1["id"], facility["id"])
    # Exceeds capacity (50 > 20) but on a non-overlapping day.
    r2 = make_rental(
        facility["id"], b["id"],
        party_size=50,
        start_datetime="2026-08-02T15:00:00Z",
        end_datetime="2026-08-02T17:00:00Z",
    )
    fv = facility_version(facility["id"])
    resp = api.approve_rental(
        r2["id"], {"expected_facility_version": fv}, MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_RENTAL_CAPACITY)
    r2_after = validate_success(api.get_rental(r2["id"], MANAGER))
    assert r2_after["status"] == "REQUESTED"


def test_rental_approve_rejected_for_overlapping_window(api):
    """PRD §3.7: "Beyond the version check, approval requires the facility to
    be `OPEN` or `RESTRICTED`, the `party_size` not to exceed
    `max_bather_capacity`, and the rental window not to overlap any other
    `APPROVED` or `CHECKED_IN` rental at the same facility — rentals are
    whole-facility exclusive (`ERR_RENTAL_OVERLAP`)."

    Design: Difficulty/resource_temporal_overlap/rental_exclusive_use_strict_overlap
    """
    facility = make_facility(max_bather_capacity=100, lap_lane_count=0)
    a, b = _two_holders()
    set_clock("2026-07-25T00:00:00Z")
    r1 = make_rental(
        facility["id"], a["id"],
        party_size=10,
        start_datetime="2026-08-10T14:00:00Z",
        end_datetime="2026-08-10T16:00:00Z",
    )
    approve_rental(r1["id"], facility["id"])
    # Overlaps r1 by one minute (15:59 < 16:00).
    r3 = make_rental(
        facility["id"], b["id"],
        party_size=10,
        start_datetime="2026-08-10T15:59:00Z",
        end_datetime="2026-08-10T18:00:00Z",
    )
    fv = facility_version(facility["id"])
    resp = api.approve_rental(
        r3["id"], {"expected_facility_version": fv}, MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_RENTAL_OVERLAP)
    r3_after = validate_success(api.get_rental(r3["id"], MANAGER))
    assert r3_after["status"] == "REQUESTED"


def test_rental_overlap_rejected_against_checked_in_rental(api):
    """PRD §3.7: "the rental window not to overlap any other `APPROVED` or
    `CHECKED_IN` rental at the same facility — rentals are whole-facility
    exclusive (`ERR_RENTAL_OVERLAP`)."

    Design: Difficulty/resource_temporal_overlap/rental_exclusive_use_strict_overlap
    """
    facility = make_facility(max_bather_capacity=100, lap_lane_count=0)
    a, b = _two_holders()
    set_clock("2026-07-25T00:00:00Z")
    r1 = make_rental(
        facility["id"], a["id"],
        party_size=10,
        start_datetime="2026-08-10T14:00:00Z",
        end_datetime="2026-08-10T16:00:00Z",
    )
    approve_rental(r1["id"], facility["id"])
    # Move r1 into CHECKED_IN inside its window.
    set_clock("2026-08-10T14:30:00Z")
    get_success_data(api.check_in_rental(r1["id"], GATE))
    r2 = make_rental(
        facility["id"], b["id"],
        party_size=10,
        start_datetime="2026-08-10T15:00:00Z",
        end_datetime="2026-08-10T17:00:00Z",
    )
    fv = facility_version(facility["id"])
    resp = api.approve_rental(
        r2["id"], {"expected_facility_version": fv}, MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_RENTAL_OVERLAP)
    r2_after = validate_success(api.get_rental(r2["id"], MANAGER))
    assert r2_after["status"] == "REQUESTED"


def test_rental_cancel_from_completed_returns_invalid_state(api):
    """PRD §3.7: "Either the patron or a manager may cancel a `REQUESTED` or
    `APPROVED` rental."
    PRD §2.10: "6. Target resource's current state permits the requested
    transition (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/rental_cancel_from_completed_returns_invalid_state
    """
    facility = make_facility(max_bather_capacity=100, lap_lane_count=0)
    holder = make_pass_holder(
        full_name="R", date_of_birth="1985-01-01T00:00:00Z"
    )
    set_clock("2026-07-01T00:00:00Z")
    rental = make_rental(
        facility["id"], holder["id"],
        party_size=5,
        start_datetime="2026-07-10T14:00:00Z",
        end_datetime="2026-07-10T16:00:00Z",
    )
    approve_rental(rental["id"], facility["id"])
    set_clock("2026-07-10T14:00:00Z")
    get_success_data(api.check_in_rental(rental["id"], GATE))
    set_clock("2026-07-10T16:00:00Z")
    completed = validate_success(api.check_out_rental(rental["id"], GATE))
    assert completed["status"] == "COMPLETED"
    resp = api.cancel_rental(rental["id"], make_passholder_headers(holder["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_rental(rental["id"], MANAGER))
    assert after["status"] == "COMPLETED"


def test_forbidden_role_approve_rental_returns_403(api):
    """PRD §2.1: "A request whose role is well-formed but not permitted for
    the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "| POST | `/rentals/{id}/approve` | Approve a FacilityRental
    (validates exclusive use and OCC) | AquaticsManager |".

    Design: Corner/validations/forbidden_role_approve_rental_returns_403
    """
    facility = make_facility(max_bather_capacity=100, lap_lane_count=0)
    holder = make_pass_holder()
    set_clock("2026-07-01T00:00:00Z")
    rental = make_rental(
        facility["id"], holder["id"],
        party_size=5,
        start_datetime="2026-08-01T14:00:00Z",
        end_datetime="2026-08-01T16:00:00Z",
    )
    fv = facility_version(facility["id"])
    resp = api.approve_rental(
        rental["id"], {"expected_facility_version": fv},
        make_passholder_headers(holder["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_occ_stale_version_rental_approve_returns_412(api):
    """PRD §2.7: "Approving a facility rental requires the request body to
    include `expected_facility_version`, carrying the client's last observed
    `version` of the `Facility` the rental belongs to. If the facility's
    current `version` has advanced past that value — for example because a
    chemistry reading pushed the facility into `CLOSED_CHEMISTRY`, or a
    recent gate entry bumped `required_lifeguard_count` — the approval is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/validations/occ_stale_version_rental_approve_returns_412
    """
    facility = make_facility(max_bather_capacity=100, lap_lane_count=0)
    make_season(facility["id"])
    holder = make_pass_holder()
    set_clock("2026-07-01T00:00:00Z")
    rental = make_rental(
        facility["id"], holder["id"],
        party_size=5,
        start_datetime="2026-08-01T14:00:00Z",
        end_datetime="2026-08-01T16:00:00Z",
    )
    stale_fv = facility_version(facility["id"])
    # A gate entry mutates the facility's derived counters and advances its
    # version (PRD §2.4), making the client's observed version stale.
    admission = make_admission(
        facility["id"], holder["id"], "2026-07-01T00:00:00Z"
    )
    get_success_data(api.enter_admission(admission["id"], GATE))
    resp = api.approve_rental(
        rental["id"], {"expected_facility_version": stale_fv}, MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    after = validate_success(api.get_rental(rental["id"], MANAGER))
    assert after["status"] == "REQUESTED"
