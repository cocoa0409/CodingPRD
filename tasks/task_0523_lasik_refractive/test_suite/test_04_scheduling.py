"""Suite booking constraints: temporal overlap, capacity caps, resource
availability, slot well-formedness, funding precondition, and OCC.

Translates queue-A difficulty instances under resource_temporal_overlap and
optimistic_concurrency, plus queue-B corner instances that reject a booking.
"""
from test_helpers import (
    validate_success, validate_error, TEST_USERS, ApiErrorId,
)
from test_helpers import fixtures as fx

COORD = TEST_USERS["coordinator_headers"]


# ---------------------------------------------------------------------------
# resource_temporal_overlap
# ---------------------------------------------------------------------------
def test_suite_conflict_within_turnaround_buffer(api):
    """PRD §3.5: "the new interval, extended by the suite's
    `turnaround_buffer_minutes` cleaning gap after it ends, must not overlap any
    other active booking on the same suite, else `ERR_SUITE_TIME_CONFLICT`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/suite_overlap_within_turnaround_buffer
    """
    pkg = fx.create_package()
    suite = fx.create_suite(turnaround_buffer_minutes=15)
    surg_a = fx.create_surgeon()
    surg_b = fx.create_surgeon(full_name="Dr B")
    od = fx.create_optometrist()
    # Blocker occupies 09:00-10:00 on the suite with a different surgeon.
    fx.setup_blocker_booking(
        suite_id=suite["id"], surgeon_id=surg_a["id"], package_id=pkg["id"],
        optometrist_id=od["id"],
        slot_start="2026-06-01T09:00:00Z", slot_end="2026-06-01T10:00:00Z",
    )
    case, _ = fx.create_planned_case(pkg["id"], od["id"], surg_b["id"])
    fx.fund_case_in_full(case["id"], pkg["base_price_cents"])
    case = validate_success(api.get_case(case["id"], COORD))  # funding bumped version
    # New slot 10:10-11:00: buffer extends existing to 10:15, so it collides.
    resp = api.create_booking(case["id"], {
        "suite_id": suite["id"], "surgeon_id": surg_b["id"],
        "slot_start": "2026-06-01T10:10:00Z", "slot_end": "2026-06-01T11:00:00Z",
        "expected_case_version": case["version"],
    }, COORD)
    validate_error(resp, ApiErrorId.ERR_SUITE_TIME_CONFLICT)


def test_suite_conflict_leaves_case_planned(api):
    """PRD §3.5: "the new interval, extended by the suite's
    `turnaround_buffer_minutes` cleaning gap after it ends, must not overlap any
    other active booking on the same suite, else `ERR_SUITE_TIME_CONFLICT`
    (HTTP 409)."
    PRD §3.5: "A successful booking is created with status `ACTIVE`, the case
    advances to `SCHEDULED`".

    Design: Difficulty/resource_temporal_overlap/suite_overlap_within_turnaround_buffer
    """
    pkg = fx.create_package()
    suite = fx.create_suite(turnaround_buffer_minutes=15)
    surg_a = fx.create_surgeon()
    surg_b = fx.create_surgeon(full_name="Dr B")
    od = fx.create_optometrist()
    fx.setup_blocker_booking(
        suite_id=suite["id"], surgeon_id=surg_a["id"], package_id=pkg["id"],
        optometrist_id=od["id"],
        slot_start="2026-06-01T09:00:00Z", slot_end="2026-06-01T10:00:00Z",
    )
    case, _ = fx.create_planned_case(pkg["id"], od["id"], surg_b["id"])
    fx.fund_case_in_full(case["id"], pkg["base_price_cents"])
    case = validate_success(api.get_case(case["id"], COORD))  # funding bumped version
    api.create_booking(case["id"], {
        "suite_id": suite["id"], "surgeon_id": surg_b["id"],
        "slot_start": "2026-06-01T10:10:00Z", "slot_end": "2026-06-01T11:00:00Z",
        "expected_case_version": case["version"],
    }, COORD)
    # Rejected booking must not have advanced the clinical axis.
    still = validate_success(api.get_case(case["id"], COORD))
    assert still["clinical_status"] == "PLANNED"


def test_surgeon_conflict_bare_overlap_no_buffer(api):
    """PRD §3.5: "The surgeon's schedule must also stay clear, but with no
    buffer: the bare new interval must not overlap any other active booking of
    the same surgeon, else `ERR_SURGEON_TIME_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/surgeon_bare_overlap_no_buffer
    """
    pkg = fx.create_package()
    suite1 = fx.create_suite()
    suite2 = fx.create_suite(name="S2")
    surg = fx.create_surgeon()
    od = fx.create_optometrist()
    # Blocker: surgeon booked 09:00-10:00 on suite1.
    fx.setup_blocker_booking(
        suite_id=suite1["id"], surgeon_id=surg["id"], package_id=pkg["id"],
        optometrist_id=od["id"],
        slot_start="2026-06-01T09:00:00Z", slot_end="2026-06-01T10:00:00Z",
    )
    case, _ = fx.create_planned_case(pkg["id"], od["id"], surg["id"])
    fx.fund_case_in_full(case["id"], pkg["base_price_cents"])
    case = validate_success(api.get_case(case["id"], COORD))  # funding bumped version
    # 09:30-10:30 on suite2 (different suite) overlaps the surgeon's interval.
    resp = api.create_booking(case["id"], {
        "suite_id": suite2["id"], "surgeon_id": surg["id"],
        "slot_start": "2026-06-01T09:30:00Z", "slot_end": "2026-06-01T10:30:00Z",
        "expected_case_version": case["version"],
    }, COORD)
    validate_error(resp, ApiErrorId.ERR_SURGEON_TIME_CONFLICT)


def test_surgeon_back_to_back_no_overlap_allowed(api):
    """PRD §3.5: "a `slot_start` and `slot_end` (ISO 8601 UTC instants describing
    the half-open operating interval that starts at `slot_start` and ends just
    before `slot_end`)".
    PRD §3.5: "The surgeon's schedule must also stay clear, but with no buffer:
    the bare new interval must not overlap any other active booking of the same
    surgeon, else `ERR_SURGEON_TIME_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/surgeon_bare_overlap_no_buffer
    """
    pkg = fx.create_package()
    suite1 = fx.create_suite()
    suite2 = fx.create_suite(name="S2")
    surg = fx.create_surgeon()
    od = fx.create_optometrist()
    fx.setup_blocker_booking(
        suite_id=suite1["id"], surgeon_id=surg["id"], package_id=pkg["id"],
        optometrist_id=od["id"],
        slot_start="2026-06-01T09:00:00Z", slot_end="2026-06-01T10:00:00Z",
    )
    case, _ = fx.create_planned_case(pkg["id"], od["id"], surg["id"])
    fx.fund_case_in_full(case["id"], pkg["base_price_cents"])
    case = validate_success(api.get_case(case["id"], COORD))  # funding bumped version
    # Back-to-back 10:00-11:00: half-open [09:00,10:00) and [10:00,11:00) do not
    # overlap and no surgeon buffer applies, so the booking succeeds.
    booking = validate_success(api.create_booking(case["id"], {
        "suite_id": suite2["id"], "surgeon_id": surg["id"],
        "slot_start": "2026-06-01T10:00:00Z", "slot_end": "2026-06-01T11:00:00Z",
        "expected_case_version": case["version"],
    }, COORD), expected_status=201)
    assert booking["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# queue-B booking corner instances
# ---------------------------------------------------------------------------
def test_booking_invalid_slot_end_not_after_start(api):
    """PRD §3.5: "The slot interval must be well-formed: `slot_end` must be
    strictly after `slot_start`, else `ERR_INVALID_SLOT` (HTTP 422)."

    Design: Corner/validations/booking_invalid_slot_end_not_after_start
    """
    cfg = fx.setup_config()
    case, _ = fx.create_planned_case(cfg["package"]["id"], cfg["optometrist"]["id"], cfg["surgeon"]["id"])
    fx.fund_case_in_full(case["id"], cfg["package"]["base_price_cents"])
    case = validate_success(api.get_case(case["id"], COORD))  # funding bumped version
    resp = api.create_booking(case["id"], {
        "suite_id": cfg["suite"]["id"], "surgeon_id": cfg["surgeon"]["id"],
        "slot_start": "2026-06-01T09:00:00Z", "slot_end": "2026-06-01T09:00:00Z",
        "expected_case_version": case["version"],
    }, COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_SLOT)


def test_booking_suite_daily_cap_exceeded(api):
    """PRD §3.5: "the number of active bookings on that suite for the UTC
    calendar day of `slot_start` must not exceed the suite's `daily_case_cap`,
    else `ERR_SUITE_DAILY_CAP` (HTTP 409)".

    Design: Corner/validations/booking_suite_daily_cap_exceeded
    """
    pkg = fx.create_package()
    suite = fx.create_suite(daily_case_cap=1)
    surg_a = fx.create_surgeon()
    surg_b = fx.create_surgeon(full_name="Dr B")
    od = fx.create_optometrist()
    fx.setup_blocker_booking(
        suite_id=suite["id"], surgeon_id=surg_a["id"], package_id=pkg["id"],
        optometrist_id=od["id"],
        slot_start="2026-06-01T09:00:00Z", slot_end="2026-06-01T10:00:00Z",
    )
    case, _ = fx.create_planned_case(pkg["id"], od["id"], surg_b["id"])
    fx.fund_case_in_full(case["id"], pkg["base_price_cents"])
    case = validate_success(api.get_case(case["id"], COORD))  # funding bumped version
    # Second booking same suite, same day, non-overlapping (14:00-15:00), diff surgeon.
    resp = api.create_booking(case["id"], {
        "suite_id": suite["id"], "surgeon_id": surg_b["id"],
        "slot_start": "2026-06-01T14:00:00Z", "slot_end": "2026-06-01T15:00:00Z",
        "expected_case_version": case["version"],
    }, COORD)
    validate_error(resp, ApiErrorId.ERR_SUITE_DAILY_CAP)


def test_booking_surgeon_daily_cap_exceeded(api):
    """PRD §3.5: "the number of active bookings for that surgeon on the same UTC
    day must not exceed the surgeon's `max_daily_cases`, else
    `ERR_SURGEON_DAILY_CAP` (HTTP 409)."

    Design: Corner/validations/booking_surgeon_daily_cap_exceeded
    """
    pkg = fx.create_package()
    suite1 = fx.create_suite()
    suite2 = fx.create_suite(name="S2")
    surg = fx.create_surgeon(max_daily_cases=1)
    od = fx.create_optometrist()
    fx.setup_blocker_booking(
        suite_id=suite1["id"], surgeon_id=surg["id"], package_id=pkg["id"],
        optometrist_id=od["id"],
        slot_start="2026-06-01T09:00:00Z", slot_end="2026-06-01T10:00:00Z",
    )
    case, _ = fx.create_planned_case(pkg["id"], od["id"], surg["id"])
    fx.fund_case_in_full(case["id"], pkg["base_price_cents"])
    case = validate_success(api.get_case(case["id"], COORD))  # funding bumped version
    # Second booking same surgeon, same day, different suite, non-overlapping.
    resp = api.create_booking(case["id"], {
        "suite_id": suite2["id"], "surgeon_id": surg["id"],
        "slot_start": "2026-06-01T14:00:00Z", "slot_end": "2026-06-01T15:00:00Z",
        "expected_case_version": case["version"],
    }, COORD)
    validate_error(resp, ApiErrorId.ERR_SURGEON_DAILY_CAP)


def test_booking_suite_in_maintenance_resource_unavailable(api):
    """PRD §3.5: "Both resources must be available: the suite's `status` must be
    `OPEN` and the surgeon's `accepting` flag must be true, else
    `ERR_RESOURCE_UNAVAILABLE` (HTTP 409)."

    Design: Corner/validations/booking_resource_unavailable_suite_maintenance
    """
    cfg = fx.setup_config()
    suite = fx.create_suite(status="MAINTENANCE")
    case, _ = fx.create_planned_case(cfg["package"]["id"], cfg["optometrist"]["id"], cfg["surgeon"]["id"])
    fx.fund_case_in_full(case["id"], cfg["package"]["base_price_cents"])
    case = validate_success(api.get_case(case["id"], COORD))  # funding bumped version
    resp = api.create_booking(case["id"], {
        "suite_id": suite["id"], "surgeon_id": cfg["surgeon"]["id"],
        "slot_start": "2026-06-01T09:00:00Z", "slot_end": "2026-06-01T10:00:00Z",
        "expected_case_version": case["version"],
    }, COORD)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_UNAVAILABLE)


# ---------------------------------------------------------------------------
# optimistic_concurrency
# ---------------------------------------------------------------------------
def test_booking_create_stale_case_version_rejected(api):
    """PRD §2.5: "When a suite booking is created for a case, the request must
    carry `expected_case_version` matching the case's current `version`. If the
    case's version has advanced since the client last read it ... the create is
    rejected with `ERR_STALE_CASE_VERSION` (HTTP 412)".

    Design: Corner/optimistic_concurrency/booking_create_stale_case_version_412
    """
    cfg = fx.setup_config()
    case, _ = fx.create_planned_case(cfg["package"]["id"], cfg["optometrist"]["id"], cfg["surgeon"]["id"])
    # Version the client last observed (before funding), which the caller will
    # supply as its stale guard.
    stale_version = case["version"]
    # Funding bumps the case version (PRD 2.4) while leaving the case in PLANNED
    # and making it funded, so the case satisfies every booking precondition
    # except the version guard. This isolates the OCC check: the only failing
    # condition is the stale version, so ERR_STALE_CASE_VERSION is unambiguous.
    fx.fund_case_in_full(case["id"], cfg["package"]["base_price_cents"])
    resp = api.create_booking(case["id"], {
        "suite_id": cfg["suite"]["id"], "surgeon_id": cfg["surgeon"]["id"],
        "slot_start": "2026-06-02T09:00:00Z", "slot_end": "2026-06-02T10:00:00Z",
        "expected_case_version": stale_version,
    }, COORD)
    validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION)


def test_cancel_stale_case_version_rejected(api):
    """PRD §2.5: "when a case is cancelled, the request must carry
    `expected_case_version` matching the case's current `version`; a mismatch is
    rejected with `ERR_STALE_CASE_VERSION` (HTTP 412)."

    Design: Corner/optimistic_concurrency/cancel_case_stale_version_412
    """
    cfg = fx.setup_config()
    case, _ = fx.create_planned_case(cfg["package"]["id"], cfg["optometrist"]["id"], cfg["surgeon"]["id"])
    fx.fund_case_in_full(case["id"], cfg["package"]["base_price_cents"])
    # Version the client last observed (post-funding, pre-booking).
    pre_booking_version = validate_success(api.get_case(case["id"], COORD))["version"]
    # Booking bumps the version; client still holds the pre-booking version.
    fx.create_booking(case["id"], cfg["suite"]["id"], cfg["surgeon"]["id"], pre_booking_version)
    resp = api.cancel_case(case["id"], {"expected_case_version": pre_booking_version}, COORD)
    validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION)
