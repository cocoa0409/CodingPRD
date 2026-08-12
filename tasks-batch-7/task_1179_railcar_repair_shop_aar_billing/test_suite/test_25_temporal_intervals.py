"""Interval semantics: half-open slot windows versus closed price windows."""
from test_helpers import (
    ApiErrorId, TEST_USERS, add_car_with_inspection, add_price_entry, api_client,
    authorize_current_wo, build_work_order, create_price_master_entry_payload,
    create_slot, make_repair_foreman_headers, setup_shop_ctx, submit_current_wo,
    validate_error, validate_paginated, validate_success,
)

ADMIN = TEST_USERS["shop_admin"]
FOREMAN = "foreman-1"

_THREE_HOSE_DEFECTS = [
    {"aar_defect_code": "AAR-1204", "defect_group": "AIR_HOSE",
     "cause_code": "WEAR", "severity": "MAJOR", "location": "A-end"},
    {"aar_defect_code": "AAR-1205", "defect_group": "AIR_HOSE",
     "cause_code": "WEAR", "severity": "MAJOR", "location": "B-end"},
    {"aar_defect_code": "AAR-1206", "defect_group": "AIR_HOSE",
     "cause_code": "WEAR", "severity": "MAJOR", "location": "mid"},
]


def _three_authorized_orders() -> dict:
    ctx = setup_shop_ctx(clock="2026-05-01T08:00:00Z")
    add_price_entry(ctx)
    add_car_with_inspection(ctx, car_number="1616", defects=_THREE_HOSE_DEFECTS)
    slot_a = create_slot(ctx["shop"]["id"], starts_at="2026-05-02T08:00:00Z",
                         ends_at="2026-05-02T12:00:00Z")
    slot_b = create_slot(ctx["shop"]["id"], starts_at="2026-05-02T12:00:00Z",
                         ends_at="2026-05-02T16:00:00Z")
    slot_c = create_slot(ctx["shop"]["id"], starts_at="2026-05-02T11:00:00Z",
                         ends_at="2026-05-02T13:00:00Z")
    ctx["slots"] = {"a": slot_a, "b": slot_b, "c": slot_c}
    wos = []
    for i in range(3):
        build_work_order(ctx, lines=[{"job_code": "J-AIR-HOSE", "defect_index": i}])
        submit_current_wo(ctx)
        authorize_current_wo(ctx)
        wos.append(ctx["wo"]["id"])
    ctx["wos"] = wos
    # First order reserves slot A (08:00-12:00).
    validate_success(api_client.assign_slot(wos[0], {"slot_id": slot_a["id"]},
                                            make_repair_foreman_headers(FOREMAN)))
    return ctx


def test_half_open_adjacency_is_not_an_overlap():
    """PRD §3.5: "its half-open window must not overlap any other slot on the
    same stall that is `RESERVED` or `OCCUPIED` — overlap is evaluated on
    half-open intervals, so a window ending exactly when another begins is
    adjacency, not overlap, and is allowed".

    Design: Difficulty/resource_temporal_overlap/slot_half_open_adjacency_allowed_overlap_rejected
    """
    ctx = _three_authorized_orders()
    # Slot B starts exactly when reserved slot A ends (12:00 == 12:00).
    assigned = validate_success(api_client.assign_slot(
        ctx["wos"][1], {"slot_id": ctx["slots"]["b"]["id"]},
        make_repair_foreman_headers(FOREMAN)))
    assert assigned["exec_status"] == "SHOP_QUEUED", "adjacent windows reserve cleanly"
    slot_b = validate_success(api_client.get_shop_slot(ctx["slots"]["b"]["id"], ADMIN))
    assert slot_b["status"] == "RESERVED"
    assert slot_b["reserved_work_order_id"] == ctx["wos"][1]


def test_interior_intersection_is_an_overlap():
    """PRD §3.5: "a true overlap is rejected with `ERR_SLOT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/slot_half_open_adjacency_allowed_overlap_rejected
    """
    ctx = _three_authorized_orders()
    # Slot C (11:00-13:00) intersects reserved slot A's interior (08:00-12:00).
    resp = api_client.assign_slot(ctx["wos"][2], {"slot_id": ctx["slots"]["c"]["id"]},
                                  make_repair_foreman_headers(FOREMAN))
    validate_error(resp, ApiErrorId.ERR_SLOT_OVERLAP, expected_status=409)
    slot_c = validate_success(api_client.get_shop_slot(ctx["slots"]["c"]["id"], ADMIN))
    assert slot_c["status"] == "OPEN", "the rejected assign leaves slot C OPEN"


def test_price_window_overlap_rejected_but_tiling_allowed():
    """PRD §2.6: "For a given shop and `job_code`, the closed effective windows
    of two entries must never overlap; creating an entry whose window overlaps
    an existing entry for the same shop and job code is rejected with
    `ERR_PRICE_WINDOW_OVERLAP` (409)."

    Design: Difficulty/resource_temporal_overlap/price_master_closed_window_overlap_and_gap
    """
    ctx = setup_shop_ctx(clock="2026-05-01T08:00:00Z")
    add_price_entry(ctx, job_code="J-BRAKE-BEAM", description="Brake beam renewal H1",
                    labor_rate_cents_per_hour=10000, effective_from="2026-01-01",
                    effective_to="2026-06-30")
    resp = api_client.create_price_master_entry(
        create_price_master_entry_payload(
            ctx["shop"]["id"], job_code="J-BRAKE-BEAM",
            description="Overlapping H2 entry", labor_rate_cents_per_hour=11000,
            effective_from="2026-06-15", effective_to="2026-12-31"),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_PRICE_WINDOW_OVERLAP, expected_status=409)

    # Closed-window adjacency: 2026-07-01 begins the day after 2026-06-30 ends.
    tiling = validate_success(api_client.create_price_master_entry(
        create_price_master_entry_payload(
            ctx["shop"]["id"], job_code="J-BRAKE-BEAM",
            description="Tiling H2 entry", labor_rate_cents_per_hour=11000,
            effective_from="2026-07-01", effective_to="2026-12-31"),
        ADMIN), expected_status=201)
    assert tiling["job_code"] == "J-BRAKE-BEAM"


def test_price_master_gap_rejects_line_pricing():
    """PRD §2.6: "when no entry is effective at the required date, the
    operation that needed the price is rejected with `ERR_PRICE_MASTER_GAP`
    (422)."

    Design: Difficulty/resource_temporal_overlap/price_master_closed_window_overlap_and_gap
    """
    ctx = setup_shop_ctx(clock="2026-05-01T08:00:00Z")
    add_price_entry(ctx, job_code="J-BRAKE-BEAM", description="Brake beam renewal H1",
                    labor_rate_cents_per_hour=10000, effective_from="2026-01-01",
                    effective_to="2026-06-30")
    # This job's only window ended 2026-03-31 — pricing on 2026-05-01 finds a gap.
    add_price_entry(ctx, job_code="J-GAP-JOB", description="Seasonal job",
                    labor_rate_cents_per_hour=5000, mobile_labor_rate_cents_per_hour=6000,
                    standard_labor_hours=1.0, mobile_trip_surcharge_cents=10000,
                    mobile_eligible=True, effective_from="2026-01-01",
                    effective_to="2026-03-31")
    add_car_with_inspection(ctx, car_number="1717", defects=[{
        "aar_defect_code": "AAR-3100", "defect_group": "BRAKE_BEAM",
        "cause_code": "WEAR", "severity": "MAJOR", "location": "B-end"}])
    build_work_order(ctx, lines=[])
    resp = api_client.add_repair_line(
        ctx["wo"]["id"],
        {"defect_finding_id": ctx["defects"][0]["id"], "job_code": "J-GAP-JOB"},
        make_repair_foreman_headers(FOREMAN))
    validate_error(resp, ApiErrorId.ERR_PRICE_MASTER_GAP, expected_status=422)
    _data, meta = validate_paginated(
        api_client.list_repair_lines_of_work_order(ctx["wo"]["id"], ADMIN))
    assert meta["total_count"] == 0, "the rejected line is not persisted"
