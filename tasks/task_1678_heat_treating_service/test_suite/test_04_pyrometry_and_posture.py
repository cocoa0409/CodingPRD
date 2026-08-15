"""Pyrometry records, furnace qualification posture derivation, the HOLD
parking cascade, and release-time validity-window containment (PRD §2.4,
§2.5, §2.7, §3.3, §3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_furnace,
    assert_instant_equals,
    assert_pyrometry_record,
    assign_order,
    create_furnace,
    create_load,
    create_work_order,
    get_furnace,
    get_load,
    record_pyrometry,
    set_clock,
    setup_shop,
    validate_error,
    validate_success,
)

CSR = TEST_USERS["customer_service_rep"]
SCHED = TEST_USERS["shop_scheduler"]
CALTECH = TEST_USERS["calibration_tech"]


# ---------------------------------------------------------------------------
# Corner: entities / pyrometry_record_immutable_no_version_field
# ---------------------------------------------------------------------------

def test_pyrometry_record_immutable_no_version_field(api):
    """PRD §2.4: "Three resources are append-only evidence records and carry
    a reduced property set: a PyrometryRecord, a LoadThermocoupleReading, and
    an InspectionTest each expose `id` and `created_at` only — both
    `updated_at` and `version` are absent, and no endpoint modifies or
    deletes them."
    PRD §3.3: "For surveys the interval depends on the furnace's class — 30
    days for `CLASS_1`, 60 days for `CLASS_2`, 90 days for `CLASS_3`, and 180
    days for `CLASS_5` — while instrument calibrations always run on a 90-day
    interval regardless of class."

    Design: Corner/entities/pyrometry_record_immutable_no_version_field
    """
    furnace = create_furnace()
    record = record_pyrometry(furnace["id"], "TUS",
                              performed_at="2026-08-01T00:00:00Z", result="PASS")
    assert_pyrometry_record(record)
    assert "version" not in record and "updated_at" not in record
    assert_instant_equals(
        record["next_due_at"], "2026-10-30T00:00:00Z",
        "CLASS_3 TUS next_due_at (performed 2026-08-01 + 90 days)",
    )
    fetched = validate_success(api.get_pyrometry_record(record["id"], CALTECH), 200)
    assert_pyrometry_record(fetched)


# ---------------------------------------------------------------------------
# Corner: calculations / pyrometry_next_due_intervals_per_class
# ---------------------------------------------------------------------------

def test_pyrometry_next_due_intervals_per_class(api):
    """PRD §3.3: "Each record's `next_due_at` is computed as `performed_at`
    plus an interval in whole days."
    PRD §3.3: "For surveys the interval depends on the furnace's class — 30
    days for `CLASS_1`, 60 days for `CLASS_2`, 90 days for `CLASS_3`, and 180
    days for `CLASS_5` — while instrument calibrations always run on a 90-day
    interval regardless of class."

    Design: Corner/calculations/pyrometry_next_due_intervals_per_class
    """
    furn_c1 = create_furnace(
        furnace_code="F-C1", furnace_class="CLASS_1", max_load_weight_lb=500
    )
    furn_c5 = create_furnace(
        furnace_code="F-C5", furnace_class="CLASS_5", max_load_weight_lb=2000
    )
    due_c1 = record_pyrometry(furn_c1["id"], "TUS")["next_due_at"]
    due_c5 = record_pyrometry(furn_c5["id"], "TUS")["next_due_at"]
    due_cal = record_pyrometry(
        furn_c5["id"], "INSTRUMENT_CALIBRATION", instrument_id="TC-CAL-1"
    )["next_due_at"]
    assert_instant_equals(due_c1, "2026-08-31T00:00:00Z", "CLASS_1 TUS (30d)")
    assert_instant_equals(due_c5, "2027-01-28T00:00:00Z", "CLASS_5 TUS (180d)")
    assert_instant_equals(
        due_cal, "2026-10-30T00:00:00Z", "calibration (flat 90d)"
    )


# ---------------------------------------------------------------------------
# Corner: calculations / furnace_posture_progression_and_overdue_precedence
# ---------------------------------------------------------------------------

def test_furnace_posture_progression_and_overdue_precedence(api):
    """PRD §3.3: "If the latest survey is missing or its `result` is `FAIL`,
    or the latest calibration is missing or `FAIL`, the furnace is
    `UNQUALIFIED`. Otherwise, if the latest survey's `next_due_at` is earlier
    than the logical clock, the posture is `SURVEY_OVERDUE`; otherwise, if the
    latest calibration's `next_due_at` is earlier than the clock, the posture
    is `CALIBRATION_OVERDUE`; otherwise the furnace is `QUALIFIED`."
    PRD §3.3: "Precedence is pinned top to bottom, so when survey and
    calibration are both overdue the furnace reports `SURVEY_OVERDUE`."
    PRD §3.2: "A freshly registered furnace has no pyrometry history, so its
    `qualification_status` computes to `UNQUALIFIED` and both
    `current_tus_due_at` and `current_calibration_due_at` are null."

    Design: Corner/calculations/furnace_posture_progression_and_overdue_precedence
    """
    furnace = create_furnace()  # CLASS_3
    assert furnace["qualification_status"] == "UNQUALIFIED"
    assert furnace.get("current_tus_due_at") is None
    assert furnace.get("current_calibration_due_at") is None

    record_pyrometry(furnace["id"], "TUS")
    assert get_furnace(furnace["id"])["qualification_status"] == "UNQUALIFIED", (
        "TUS only — calibration record still missing"
    )

    record_pyrometry(furnace["id"], "INSTRUMENT_CALIBRATION")
    qualified = get_furnace(furnace["id"])
    assert qualified["qualification_status"] == "QUALIFIED"
    assert_furnace(qualified)
    assert_instant_equals(
        qualified["current_tus_due_at"], "2026-10-30T00:00:00Z", "current_tus_due_at"
    )

    # Both records fall due 2026-10-30; at 2026-10-31 both are overdue and the
    # pinned precedence reports the survey breach.
    set_clock("2026-10-31T00:00:00Z")
    overdue = get_furnace(furnace["id"])
    assert overdue["qualification_status"] == "SURVEY_OVERDUE", (
        f"both intervals overdue -> SURVEY_OVERDUE precedence, got "
        f"{overdue['qualification_status']}"
    )


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / pyrometry_fail_hold_and_requalify_cascade
# ---------------------------------------------------------------------------

def test_pyrometry_fail_hold_and_requalify_cascade(api):
    """PRD §3.3: "The moment a posture recomputation moves a furnace out of
    `QUALIFIED`, whether from a failing record or simply from the logical
    clock passing a due date, every LoadBatch sitting in `BUILDING` on that
    furnace drops to `HOLD`; when the posture returns to `QUALIFIED`, each
    such `HOLD` load resumes `BUILDING`."
    PRD §3.3: "Loads already released or running are not retroactively
    parked — the posture gate instead bites at release and start-run time
    (§3.5, §3.6)."

    Design: Difficulty/transitive_cascade/pyrometry_fail_hold_and_requalify_cascade
    """
    shop = setup_shop()
    order = create_work_order(shop["customer"]["id"], shop["recipe"]["id"])
    load = create_load(shop["furnace"]["id"], shop["recipe"]["id"])
    assign_order(load["id"], order["id"])
    assert get_load(load["id"])["status"] == "BUILDING"

    # A FAIL survey becomes the latest TUS -> UNQUALIFIED -> load parked.
    record_pyrometry(
        shop["furnace"]["id"], "TUS", performed_at="2026-08-02T00:00:00Z",
        result="FAIL",
    )
    assert get_furnace(shop["furnace"]["id"])["qualification_status"] == "UNQUALIFIED"
    assert get_load(load["id"])["status"] == "HOLD", (
        "BUILDING load must drop to HOLD when the furnace leaves QUALIFIED"
    )

    # A later PASS survey restores QUALIFIED and the load resumes BUILDING.
    record_pyrometry(
        shop["furnace"]["id"], "TUS", performed_at="2026-08-05T00:00:00Z",
        result="PASS",
    )
    assert get_furnace(shop["furnace"]["id"])["qualification_status"] == "QUALIFIED"
    assert get_load(load["id"])["status"] == "BUILDING", (
        "HOLD load must resume BUILDING when the furnace returns to QUALIFIED"
    )


def test_clock_overdue_parks_building_load_and_requalify_restores(api):
    """PRD §3.3: "The moment a posture recomputation moves a furnace out of
    `QUALIFIED`, whether from a failing record or simply from the logical
    clock passing a due date, every LoadBatch sitting in `BUILDING` on that
    furnace drops to `HOLD`; when the posture returns to `QUALIFIED`, each
    such `HOLD` load resumes `BUILDING`."
    PRD §3.3: "Otherwise, if the latest survey's `next_due_at` is earlier than
    the logical clock, the posture is `SURVEY_OVERDUE`; otherwise, if the
    latest calibration's `next_due_at` is earlier than the clock, the posture
    is `CALIBRATION_OVERDUE`; otherwise the furnace is `QUALIFIED`."

    Design: Difficulty/transitive_cascade/pyrometry_fail_hold_and_requalify_cascade
    """
    shop = setup_shop()  # TUS + calibration performed 2026-08-01, due 2026-10-30
    order = create_work_order(shop["customer"]["id"], shop["recipe"]["id"])
    load = create_load(shop["furnace"]["id"], shop["recipe"]["id"])
    assign_order(load["id"], order["id"])

    # Clock passes both due dates with no new evidence: posture leaves
    # QUALIFIED and the BUILDING load is parked.
    set_clock("2026-10-31T00:00:00Z")
    assert get_furnace(shop["furnace"]["id"])["qualification_status"] == "SURVEY_OVERDUE"
    assert get_load(load["id"])["status"] == "HOLD"

    # A fresh survey alone still leaves calibration overdue.
    record_pyrometry(
        shop["furnace"]["id"], "TUS", performed_at="2026-11-01T00:00:00Z",
        result="PASS",
    )
    assert (
        get_furnace(shop["furnace"]["id"])["qualification_status"]
        == "CALIBRATION_OVERDUE"
    )
    assert get_load(load["id"])["status"] == "HOLD"

    # Fresh calibration restores QUALIFIED and the load resumes BUILDING.
    record_pyrometry(
        shop["furnace"]["id"], "INSTRUMENT_CALIBRATION",
        performed_at="2026-11-01T00:00:00Z", result="PASS",
    )
    assert get_furnace(shop["furnace"]["id"])["qualification_status"] == "QUALIFIED"
    assert get_load(load["id"])["status"] == "BUILDING"


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap /
# pyrometry_validity_containment_at_release
# ---------------------------------------------------------------------------

def test_pyrometry_validity_containment_at_release(api):
    """PRD §3.5: "The entire scheduled window must be contained in the
    pyrometry validity intervals: `scheduled_start_at` must fall on or after
    the most recent passing survey's `performed_at` and `scheduled_end_at`
    must fall before its `next_due_at`, and the same containment must hold
    against the most recent passing calibration's interval — otherwise the
    release fails with `ERR_PYROMETRY_WINDOW_VIOLATION` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/pyrometry_validity_containment_at_release
    """
    shop = setup_shop()
    furnace = shop["furnace"]
    # The shop fixture already qualified the furnace at 2026-08-01; a CLASS_3
    # TUS runs 90 days, so validity ends 2026-10-30T00:00:00Z.
    tus_records = validate_success(
        api.list_pyrometry_records(
            SCHED, params={"furnace_id": furnace["id"], "record_type": "TUS"}
        ),
        200,
    )
    assert_instant_equals(
        tus_records[0]["next_due_at"], "2026-10-30T00:00:00Z", "TUS next_due_at"
    )

    # Load X crosses the validity horizon: [10-29 08:00, 10-31 08:00].
    order_x = create_work_order(shop["customer"]["id"], shop["recipe"]["id"])
    load_x = create_load(
        furnace["id"], shop["recipe"]["id"],
        scheduled_start_at="2026-10-29T08:00:00Z",
        scheduled_end_at="2026-10-31T08:00:00Z",
    )
    assign_order(load_x["id"], order_x["id"])
    res = api.release_load_batch(load_x["id"], SCHED)
    validate_error(res, ApiErrorId.ERR_PYROMETRY_WINDOW_VIOLATION.value)
    assert get_load(load_x["id"])["status"] == "BUILDING"

    # Load Y [10-28 08:00, 10-29 08:00] is fully contained and releases.
    order_y = create_work_order(shop["customer"]["id"], shop["recipe"]["id"])
    load_y = create_load(
        furnace["id"], shop["recipe"]["id"],
        scheduled_start_at="2026-10-28T08:00:00Z",
        scheduled_end_at="2026-10-29T08:00:00Z",
    )
    assign_order(load_y["id"], order_y["id"])
    released = validate_success(api.release_load_batch(load_y["id"], SCHED), 200)
    assert released["status"] == "RELEASED"


def test_pyrometry_window_start_before_performed_rejected(api):
    """PRD §3.5: "The entire scheduled window must be contained in the
    pyrometry validity intervals: `scheduled_start_at` must fall on or after
    the most recent passing survey's `performed_at` and `scheduled_end_at`
    must fall before its `next_due_at`, and the same containment must hold
    against the most recent passing calibration's interval — otherwise the
    release fails with `ERR_PYROMETRY_WINDOW_VIOLATION` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/pyrometry_validity_containment_at_release
    """
    shop = setup_shop()  # validity starts at performed_at 2026-08-01T00:00:00Z
    furnace = shop["furnace"]

    # Window opens before the survey was performed: containment fails.
    order_a = create_work_order(shop["customer"]["id"], shop["recipe"]["id"])
    load_a = create_load(
        furnace["id"], shop["recipe"]["id"],
        scheduled_start_at="2026-07-31T20:00:00Z",
        scheduled_end_at="2026-08-02T08:00:00Z",
    )
    assign_order(load_a["id"], order_a["id"])
    res = api.release_load_batch(load_a["id"], SCHED)
    validate_error(res, ApiErrorId.ERR_PYROMETRY_WINDOW_VIOLATION.value)

    # A window opening exactly at performed_at is "on or after" and releases.
    order_b = create_work_order(shop["customer"]["id"], shop["recipe"]["id"])
    load_b = create_load(
        furnace["id"], shop["recipe"]["id"],
        scheduled_start_at="2026-08-01T00:00:00Z",
        scheduled_end_at="2026-08-02T12:00:00Z",
    )
    assign_order(load_b["id"], order_b["id"])
    released = validate_success(api.release_load_batch(load_b["id"], SCHED), 200)
    assert released["status"] == "RELEASED"
