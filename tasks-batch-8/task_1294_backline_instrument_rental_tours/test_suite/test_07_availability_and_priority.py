"""Temporal-overlap semantics (half-open adjacency, transit buffer) and
validation-priority pairs."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    add_stop, add_rider_line, get_reservation,
    create_source_payload,
    setup_overlap_unit, setup_transit_buffer_scene, setup_state_fiscal_scene,
    setup_sod_scene,
    api_client, TEST_USERS, build_user_headers,
)

OPS = TEST_USERS["ops_manager_headers"]
TM = TEST_USERS["tour_manager_headers"]
LC = TEST_USERS["logistics_headers"]
WT = TEST_USERS["warehouse_tech_headers"]


def test_adjacent_window_succeeds(api):
    """PRD §3.3: "a conflict is any reservation in `SOURCED`, `DISPATCHED`, or
    `DELIVERED` whose half-open window overlaps the requested one (windows that
    merely touch, an existing reservation ending exactly when the requested one
    begins, do not conflict)".
    The existing reservation ends 2026-08-15 and the new window starts
    2026-08-15: adjacent half-open windows do not conflict, so the same unit is
    sourced again.

    Design: Difficulty/resource_temporal_overlap/gear_unit_halfopen_adjacency_vs_overlap
    """
    ctx = setup_overlap_unit()
    stop2 = add_stop(ctx["tour"]["id"], city_code="LAX", venue_date="2026-08-16T00:00:00Z",
                     load_in_ts="2026-08-16T10:00:00Z")
    line2 = add_rider_line(stop2["id"], ctx["model"]["id"])

    reservation = validate_success(api.source_rider_line(
        line2["id"], create_source_payload(
            origin_city_code="LAX", dest_city_code="LAX",
            start_date="2026-08-15T00:00:00Z", end_date="2026-08-20T00:00:00Z"), LC))
    assert reservation["status"] == "SOURCED"
    assert reservation["gear_unit_id"] == ctx["unit"]["id"]


def test_overlapping_window_fails(api):
    """PRD §3.3: "a conflict is any reservation in `SOURCED`, `DISPATCHED`, or
    `DELIVERED` whose half-open window overlaps the requested one (windows that
    merely touch, an existing reservation ending exactly when the requested one
    begins, do not conflict)".
    PRD §2.11: "8. Availability — a window overlap or transit-buffer collision
    with no eligible vendor fallback fails with `ERR_GEAR_UNAVAILABLE` (HTTP
    409)."
    A window starting 2026-08-14 overlaps the existing [2026-08-10,
    2026-08-15) reservation, and with a single unit and no vendor the source
    fails.

    Design: Difficulty/resource_temporal_overlap/gear_unit_halfopen_adjacency_vs_overlap
    """
    ctx = setup_overlap_unit()
    stop2 = add_stop(ctx["tour"]["id"], city_code="LAX", venue_date="2026-08-16T00:00:00Z",
                     load_in_ts="2026-08-16T10:00:00Z")
    line2 = add_rider_line(stop2["id"], ctx["model"]["id"])
    validate_success(api.source_rider_line(
        line2["id"], create_source_payload(
            origin_city_code="LAX", dest_city_code="LAX",
            start_date="2026-08-15T00:00:00Z", end_date="2026-08-20T00:00:00Z"), LC))

    stop3 = add_stop(ctx["tour"]["id"], city_code="LAX", venue_date="2026-08-18T00:00:00Z",
                     load_in_ts="2026-08-18T10:00:00Z")
    line3 = add_rider_line(stop3["id"], ctx["model"]["id"])
    resp = api.source_rider_line(
        line3["id"], create_source_payload(
            origin_city_code="LAX", dest_city_code="LAX",
            start_date="2026-08-14T00:00:00Z", end_date="2026-08-20T00:00:00Z"), LC)
    validate_error(resp, ApiErrorId.ERR_GEAR_UNAVAILABLE)


def test_transit_buffer_collision(api):
    """PRD §3.3: "A unit whose `home_city_code` differs from the stop's city
    needs a one-day transit buffer, so its effective window begins one day
    earlier than requested."
    The LAX-based unit is reserved [2026-08-10, 2026-08-15); a New York window
    starting 2026-08-15 shifts to an effective start of 2026-08-14 and
    collides, so the source fails.

    Design: Difficulty/resource_temporal_overlap/cross_city_transit_buffer_overlap_semantics
    """
    ctx = setup_transit_buffer_scene()
    line2 = add_rider_line(ctx["stop_nyc"]["id"], ctx["model"]["id"])
    resp = api.source_rider_line(
        line2["id"], create_source_payload(
            origin_city_code="LAX", dest_city_code="NYC",
            start_date="2026-08-15T00:00:00Z", end_date="2026-08-18T00:00:00Z"), LC)
    validate_error(resp, ApiErrorId.ERR_GEAR_UNAVAILABLE)


def test_transit_buffer_shifted_window_succeeds(api):
    """PRD §3.3: "A unit whose `home_city_code` differs from the stop's city
    needs a one-day transit buffer, so its effective window begins one day
    earlier than requested."
    PRD §2.5: "All rental-window arithmetic treats a window as a half-open
    interval: the start date is included, the end date is excluded, and two
    windows that merely touch — one ending exactly when the other begins — do
    not overlap."
    Starting one day later (2026-08-16) shifts the effective start to
    2026-08-15, which merely touches the existing reservation's end — no
    conflict, and the source succeeds.

    Design: Difficulty/resource_temporal_overlap/cross_city_transit_buffer_overlap_semantics
    """
    ctx = setup_transit_buffer_scene()
    line2 = add_rider_line(ctx["stop_nyc"]["id"], ctx["model"]["id"])
    reservation = validate_success(api.source_rider_line(
        line2["id"], create_source_payload(
            origin_city_code="LAX", dest_city_code="NYC",
            start_date="2026-08-16T00:00:00Z", end_date="2026-08-19T00:00:00Z"), LC))
    assert reservation["status"] == "SOURCED"
    assert reservation["gear_unit_id"] == ctx["unit"]["id"]


def test_state_beats_fiscal_on_source(api):
    """PRD §2.11: "Beyond path resolution, every request walks a fixed sequence
    of gates, and the first gate that fails determines the error returned".
    PRD §2.11: "4. State legality — a target whose current state does not permit
    the requested transition fails with `ERR_INVALID_STATE` (HTTP 409)."
    PRD §2.11: "14. Deposit headroom — an artist balance that cannot cover the
    hold fails with `ERR_DEPOSIT_INSUFFICIENT` (HTTP 402)."
    The line is CANCELLED (gate 4) and the balance-0 artist could not cover the
    55000 hold (gate 14); state legality fires first.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_source
    """
    ctx = setup_state_fiscal_scene(cancel_line=True)
    resp = api.source_rider_line(ctx["line"]["id"], create_source_payload(
        origin_city_code="LAX", dest_city_code="LAX",
        start_date="2026-08-09T00:00:00Z", end_date="2026-08-11T00:00:00Z"), LC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_fiscal_fires_in_isolation_on_source(api):
    """PRD §2.11: "14. Deposit headroom — an artist balance that cannot cover
    the hold fails with `ERR_DEPOSIT_INSUFFICIENT` (HTTP 402)."
    PRD §2.7: "The ledger is never allowed to dip below zero: if an artist's
    balance — after accounting for the deposits currently held across that
    artist's reservations — cannot cover a new hold, the operation that would
    create the hold is rejected with `ERR_DEPOSIT_INSUFFICIENT` (HTTP 402)."
    Same scene but with the line still REQUESTED: only the fiscal gate can
    fail, so it surfaces.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_source
    """
    ctx = setup_state_fiscal_scene(cancel_line=False)
    resp = api.source_rider_line(ctx["line"]["id"], create_source_payload(
        origin_city_code="LAX", dest_city_code="LAX",
        start_date="2026-08-09T00:00:00Z", end_date="2026-08-11T00:00:00Z"), LC)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_INSUFFICIENT)


def test_sod_fires_despite_suspended_vendor(api):
    """PRD §3.7: "Assessment is an `OpsManager` act, and the filer may not
    assess their own claim: when the acting user's `X-User-ID` matches the
    claim's `filed_by_user_id`, the assessment is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §2.11: "6. Segregation of duties — on damage assessment only, an
    assessor who originally filed the claim fails with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    A vendor suspension in the scene changes nothing: the filer-as-assessor
    attempt is rejected.

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_on_damage_assess
    """
    ctx = setup_sod_scene()
    filer_as_ops = build_user_headers(ctx["filer_id"], "OpsManager")
    resp = api.assess_damage_claim(ctx["claim"]["id"], filer_as_ops)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


def test_clean_assess_by_other_ops_user_succeeds(api, ops_manager_b_headers):
    """PRD §3.7: "Assessment moves the claim from `FILED` to `ASSESSED`".
    PRD §3.7: "when the acting user's `X-User-ID` matches the claim's
    `filed_by_user_id`, the assessment is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    An assessor whose id differs from the filer's passes the segregation gate.

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_on_damage_assess
    """
    ctx = setup_sod_scene()
    assert ops_manager_b_headers["X-User-ID"] != ctx["filer_id"]
    assessed = validate_success(api.assess_damage_claim(ctx["claim"]["id"],
                                                        ops_manager_b_headers))
    assert assessed["status"] == "ASSESSED"
