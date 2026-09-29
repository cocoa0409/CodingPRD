"""Per-calendar-day batch window capacity: two overlapping batches are fine, a third is not."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, ApiErrorId,
    factories,
    set_clock, create_facility, create_department, create_batch, read_batch,
    read_department, read_facility,
    make_manager_headers,
)

MANAGER_ID = "dept_mgr_1"
MANAGER = make_manager_headers(MANAGER_ID)


def _setup():
    """One department carrying two INGESTED batches whose windows overlap on 08-05..08-07."""
    set_clock("2026-08-01T00:00:00Z")
    facility = create_facility(
        name="Capacity General", cms_certification_number="CCN-2193-C",
        rounding_mode="NEAREST_CENT", aggregate_markup_limit_bp=40000,
    )
    department = create_department(
        facility["id"], manager_user_id=MANAGER_ID,
        name="Respiratory Therapy", cost_center_code="CC-RT",
    )
    base = {"facility": facility, "department": department, "manager_headers": MANAGER}
    b1 = create_batch(base, window_start_date="2026-08-03T00:00:00Z",
                      window_end_date="2026-08-07T00:00:00Z")
    b2 = create_batch(base, window_start_date="2026-08-05T00:00:00Z",
                      window_end_date="2026-08-10T00:00:00Z")
    base["b1"] = b1
    base["b2"] = b2
    return base


def _batch_payload(s, start, end):
    return factories.create_charge_capture_batch_payload(
        s["facility"]["id"], s["department"]["id"],
        window_start_date=start, window_end_date=end,
    )


def test_a_third_batch_covering_an_already_doubly_covered_day_is_refused():
    """PRD §3.9: "And capacity is bounded per calendar day: no single day inside the new closed
    window may end up covered by more than two `ChargeCaptureBatch` rows of the same department
    whose `status` is anything other than `CLOSED`. A third overlapping batch on any one day is
    rejected with `ERR_BATCH_WINDOW_CAPACITY_EXCEEDED` (409)."
    PRD §2.5: "A batch covers a service date when `window_start_date` is at or before it and
    `window_end_date` is at or after it."
    PRD §3.9: "A new batch is created in `INGESTED` with `reconcile_pass_count` at 0 and every
    counter — `line_count`, `matched_line_count`, `exception_line_count`, `open_finding_count`,
    `total_expected_charge_cents`, `total_posted_charge_cents` — at 0, and
    `mean_line_variance_bp` null until the first reconciliation pass."

    Design: Difficulty/resource_temporal_overlap/resource_temporal_overlap__batch_window_aggregate_capacity_third_cover_on_single_day
    """
    s = _setup()
    assert read_department(s["department"]["id"])["capture_hold"] is False, (
        "the ingestion gate that must not fire here"
    )
    for batch in (s["b1"], s["b2"]):
        assert batch["status"] == "INGESTED"
        assert batch["reconcile_pass_count"] == 0
        assert batch["line_count"] == 0
        assert batch["matched_line_count"] == 0
        assert batch["exception_line_count"] == 0
        assert batch["open_finding_count"] == 0
        assert batch["total_expected_charge_cents"] == 0
        assert batch["total_posted_charge_cents"] == 0
        assert batch["mean_line_variance_bp"] is None

    # 2026-08-07 is already covered by both b1 [08-03, 08-07] and b2 [08-05, 08-10], so a
    # window touching it would take that one day to a third non-CLOSED cover.
    validate_error(
        api_client.create_charge_capture_batch(
            _batch_payload(s, "2026-08-07T00:00:00Z", "2026-08-08T00:00:00Z"), MANAGER
        ),
        ApiErrorId.ERR_BATCH_WINDOW_CAPACITY_EXCEEDED.value,
        409,
    )

    assert read_batch(s["b1"]["id"])["status"] == "INGESTED"
    assert read_batch(s["b2"]["id"])["status"] == "INGESTED"
    rows, _meta = validate_paginated(
        api_client.list_charge_capture_batches(
            MANAGER, params={"department_id": s["department"]["id"]}
        )
    )
    assert len(rows) == 2, f"the refused batch was never persisted: got {len(rows)} rows"


def test_a_third_batch_whose_every_day_is_at_most_singly_covered_is_accepted():
    """PRD §3.9: "no single day inside the new closed window may end up covered by more than two
    `ChargeCaptureBatch` rows of the same department whose `status` is anything other than
    `CLOSED`."
    PRD §3.9: "A `DepartmentManager` ingests a `ChargeCaptureBatch` covering a closed
    service-date window for one department, supplying `facility_id`, `department_id`,
    `window_start_date` and `window_end_date`."

    Design: Difficulty/resource_temporal_overlap/resource_temporal_overlap__batch_window_aggregate_capacity_third_cover_on_single_day
    """
    s = _setup()
    validate_error(
        api_client.create_charge_capture_batch(
            _batch_payload(s, "2026-08-07T00:00:00Z", "2026-08-08T00:00:00Z"), MANAGER
        ),
        ApiErrorId.ERR_BATCH_WINDOW_CAPACITY_EXCEEDED.value,
        409,
    )

    # 08-08 through 08-10 carry only b2, and 08-11/08-12 carry nothing, so every day of this
    # window ends at a cover of two at most.
    accepted = validate_success(
        api_client.create_charge_capture_batch(
            _batch_payload(s, "2026-08-08T00:00:00Z", "2026-08-12T00:00:00Z"), MANAGER
        ),
        201,
    )
    assert accepted["status"] == "INGESTED"
    assert accepted["window_start_date"].startswith("2026-08-08T00:00:00")
    assert accepted["window_end_date"].startswith("2026-08-12T00:00:00")
    assert accepted["department_id"] == s["department"]["id"]
    assert accepted["facility_id"] == s["facility"]["id"]
    assert accepted["mean_line_variance_bp"] is None

    rows, _meta = validate_paginated(
        api_client.list_charge_capture_batches(
            MANAGER, params={"department_id": s["department"]["id"]}
        )
    )
    assert len(rows) == 3, f"the two incumbents plus the accepted batch: got {len(rows)}"
    assert {r["status"] for r in rows} == {"INGESTED"}
    assert read_facility(s["facility"]["id"])["chargemaster_posture"] == "OPEN", (
        "capture batches never move the pricing posture"
    )
