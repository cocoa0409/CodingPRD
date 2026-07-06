"""Cooler storage: capacity boundaries, occupancy accounting, OCC, conservation."""
from test_helpers import (
    validate_success, validate_error,
    create_investigator, create_pathologist, create_cooler,
    set_clock, create_investigating_case,
    store_body, setup_certified_case_natural,
    make_investigator_headers,
    store_body_payload,
)


def test_cooler_full_at_capacity_boundary(api):
    """PRD §3.3: "The store is permitted only when that cooler is in service ... and only when
    it has a free slot, meaning its current occupied_slots is strictly less than its
    slot_capacity; a unit whose occupancy has reached capacity is full and rejects the store
    with ERR_COOLER_FULL (HTTP 409)."

    Design: Difficulty/boundary_precision_check/cooler_full_at_capacity_boundary
    """
    inv = create_investigator("Inv K")
    cooler = create_cooler(slot_capacity=1)
    case1, body1 = create_investigating_case(inv, case_type="NATURAL")
    store_body(inv, body1, cooler)  # occupied_slots -> 1 (== capacity)

    case2, body2 = create_investigating_case(inv, case_type="NATURAL")
    inv_headers = make_investigator_headers(inv["id"])
    fresh = validate_success(api.get_cooler_unit(cooler["id"], inv_headers), 200)
    res = api.store_body(
        body2["id"], store_body_payload(cooler["id"], fresh["version"]), inv_headers
    )
    validate_error(res, "ERR_COOLER_FULL", expected_status=409)


def test_cooler_aggregate_capacity_overlap_rejected(api):
    """PRD §3.3: "a unit whose occupancy has reached capacity is full and rejects the store
    with ERR_COOLER_FULL (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/cooler_aggregate_capacity_overlap
    """
    inv = create_investigator("Inv P")
    cooler = create_cooler(slot_capacity=2)
    case1, body1 = create_investigating_case(inv, case_type="NATURAL")
    store_body(inv, body1, cooler)
    case2, body2 = create_investigating_case(inv, case_type="NATURAL")
    store_body(inv, body2, cooler)  # occupied_slots -> 2 (== capacity)

    case3, body3 = create_investigating_case(inv, case_type="NATURAL")
    inv_headers = make_investigator_headers(inv["id"])
    fresh = validate_success(api.get_cooler_unit(cooler["id"], inv_headers), 200)
    res = api.store_body(
        body3["id"], store_body_payload(cooler["id"], fresh["version"]), inv_headers
    )
    validate_error(res, "ERR_COOLER_FULL", expected_status=409)


def test_store_out_of_service_cooler_rejected(api):
    """PRD §3.3: "The store is permitted only when that cooler is in service — a store into an
    out_of_service unit is rejected with ERR_COOLER_OUT_OF_SERVICE (HTTP 409)."

    Design: Corner/validations/cooler_out_of_service_rejects_store
    """
    inv = create_investigator("Inv CV1")
    cooler = create_cooler(slot_capacity=2, out_of_service=True)
    case, body = create_investigating_case(inv, case_type="NATURAL")

    inv_headers = make_investigator_headers(inv["id"])
    res = api.store_body(
        body["id"], store_body_payload(cooler["id"], cooler["version"]), inv_headers
    )
    validate_error(res, "ERR_COOLER_OUT_OF_SERVICE", expected_status=409)


def test_occupancy_report_two_bodies_body_days(api):
    """PRD §2.9: "For every body currently STORED in the unit, the system measures the elapsed
    time from that body's intake_at to the current logical-clock instant and charges one whole
    day for each started day — that is, the elapsed seconds divided by the number of seconds in
    a day (86,400), rounded up to the next whole day. A body whose elapsed time is exactly zero
    (intaken at the current instant) contributes zero days rather than one. The report sums
    these per-body day counts into total_body_days and reports the current occupied_slots
    alongside it."

    Design: Corner/calculations/cooler_occupancy_report_two_bodies
    """
    inv = create_investigator("Inv CC1")
    cooler = create_cooler(slot_capacity=3)
    inv_headers = make_investigator_headers(inv["id"])

    set_clock("2026-05-10T00:00:00Z")
    caseA, bodyA = create_investigating_case(inv, case_type="NATURAL")
    store_body(inv, bodyA, cooler)

    set_clock("2026-05-11T23:59:59Z")
    caseB, bodyB = create_investigating_case(inv, case_type="NATURAL")
    store_body(inv, bodyB, cooler)

    set_clock("2026-05-12T23:59:59Z")
    report = validate_success(api.cooler_occupancy_report(cooler["id"], inv_headers), 200)
    assert report["total_body_days"] == 4
    assert report["occupied_slots"] == 2


def test_store_then_release_conserves_cooler_occupancy(api):
    """PRD §3.3: "The chosen cooler's occupied_slots is recomputed upward by one and its
    version increments." PRD §3.3: "the former cooler's occupied_slots is recomputed downward
    by one and that cooler's version increments, as does the body's."

    Design: Difficulty/compensating_invariant/store_then_release_conserves_cooler_occupancy
    """
    inv = create_investigator("Inv Q")
    me = create_pathologist("ME Q", is_medical_examiner=True)
    cooler = create_cooler(slot_capacity=2)
    # Store, certify (clears release_blocked), then release.
    case, body = setup_certified_case_natural(inv, me, cooler=cooler)

    inv_headers = make_investigator_headers(inv["id"])
    released = validate_success(api.release_body(body["id"], inv_headers), 200)
    assert released["storage_status"] == "RELEASED"

    cooler_after = validate_success(api.get_cooler_unit(cooler["id"], inv_headers), 200)
    assert cooler_after["occupied_slots"] == 0


def test_store_stale_cooler_version_rejected(api):
    """PRD §2.5: "When an investigator stores a body into a cooler, the request must carry
    expected_cooler_version matching the current version of the target cooler unit. If another
    store or release against that cooler has advanced its version since the client last read
    it, a slot the client believed free may now be taken, so the stale store is rejected with
    ERR_STALE_VERSION (HTTP 412) before the write."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_cooler_version_on_store
    """
    inv = create_investigator("Inv CX1")
    cooler = create_cooler(slot_capacity=3)
    stale_version = cooler["version"]

    caseA, bodyA = create_investigating_case(inv, case_type="NATURAL")
    store_body(inv, bodyA, cooler)  # bumps cooler version past stale_version

    caseB, bodyB = create_investigating_case(inv, case_type="NATURAL")
    inv_headers = make_investigator_headers(inv["id"])
    res = api.store_body(
        bodyB["id"], store_body_payload(cooler["id"], stale_version), inv_headers
    )
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
