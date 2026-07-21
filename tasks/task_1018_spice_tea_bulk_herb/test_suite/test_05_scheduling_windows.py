"""Production-line window overlap, station cleaning buffer, window validity, allergen sets."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_line_with_two_batches, setup_station_with_two_runs,
    new_product, new_production_line, new_labeling_station,
    TEST_USERS,
)

PROD = TEST_USERS["production_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ---- resource_temporal_overlap / production_line_window_overlap_half_open ----

def test_overlapping_batch_on_same_line_rejected(api):
    """PRD §3.3: "A batch occupies its line exclusively for that window: if the requested
    window overlaps another batch already scheduled on the same line, the batch is rejected
    with `ERR_LINE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/production_line_window_overlap_half_open
    """
    ctx = setup_line_with_two_batches(api)
    payload = {
        "blend_product_id": ctx["chai"]["id"],
        "production_line_id": ctx["line"]["id"],
        "target_output_grams": 100,
        "scheduled_start": "2026-07-10T09:00:00Z",
        "scheduled_end": "2026-07-10T11:00:00Z",  # overlaps batch1 [08:00,10:00)
    }
    resp = api.create_batch(payload, PROD)
    validate_error(resp, ApiErrorId.ERR_LINE_WINDOW_CONFLICT.value)


def test_abutting_batch_on_same_line_accepted(api):
    """PRD §3.3: "Because the window is half-open, two batches that merely abut — one ending
    exactly when the next begins — do not conflict."

    Design: Difficulty/resource_temporal_overlap/production_line_window_overlap_half_open
    """
    # setup creates batch1 [08:00,10:00) and batch3 [10:00,12:00): batch3 abuts batch1's end.
    ctx = setup_line_with_two_batches(api)
    batch3 = validate_success(api.get_batch(ctx["batch3"]["id"], ADMIN))
    assert batch3["status"] == "PLANNED", batch3["status"]
    assert batch3["scheduled_start"].startswith("2026-07-10T10:00:00")


# ---- resource_temporal_overlap / labeling_station_cleaning_buffer ----

def test_tin_run_within_cleaning_buffer_rejected(api):
    """PRD §3.4: "A tin run scheduled such that its window falls within thirty minutes of
    another run on the same station — closer than a half-hour gap on either side — is
    rejected with `ERR_STATION_BUFFER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/labeling_station_cleaning_buffer
    """
    ctx = setup_station_with_two_runs(api)
    payload = {
        "labeling_station_id": ctx["station"]["id"],
        "product_ids": [ctx["cham"]["id"]],
        "scheduled_start": "2026-07-10T09:15:00Z",  # only 15 min after run1's 09:00 end
        "scheduled_end": "2026-07-10T10:00:00Z",
    }
    resp = api.create_tin_run(payload, PROD)
    validate_error(resp, ApiErrorId.ERR_STATION_BUFFER_CONFLICT.value)


def test_tin_run_with_full_buffer_gap_accepted(api):
    """PRD §3.4: "Unlike production lines, a labeling station requires a **cleaning buffer
    of thirty minutes** between consecutive runs to prevent allergen cross-contamination."

    Design: Difficulty/resource_temporal_overlap/labeling_station_cleaning_buffer
    """
    # setup creates run1 [08:00,09:00) and run3 [09:30,10:00): exactly a 30-min gap, accepted.
    ctx = setup_station_with_two_runs(api)
    run3 = validate_success(api.get_tin_run(ctx["run3"]["id"], ADMIN))
    assert run3["labeling_station_id"] == ctx["station"]["id"], run3["labeling_station_id"]
    assert run3["scheduled_start"].startswith("2026-07-10T09:30:00")


# ---- Corner / validations / batch_window_invalid ----

def test_batch_with_start_not_before_end_rejected(api):
    """PRD §3.3: "The window is half-open — start inclusive, end exclusive — and its start
    must be strictly before its end, or the batch is rejected with `ERR_WINDOW_INVALID`."

    Design: Corner/validations/corner_batch_window_invalid
    """
    chai = new_product(api, name="Almond Chai Blend", category="TEA", kind="BLEND",
                       unit_price_cents_per_gram=7.2, tare_default_grams=5)
    line = new_production_line(api)
    payload = {
        "blend_product_id": chai["id"],
        "production_line_id": line["id"],
        "target_output_grams": 100,
        "scheduled_start": "2026-07-10T10:00:00Z",
        "scheduled_end": "2026-07-10T10:00:00Z",  # start == end
    }
    resp = api.create_batch(payload, PROD)
    validate_error(resp, ApiErrorId.ERR_WINDOW_INVALID.value)


# ---- Corner / calculations / tin_run_allergen_set_union ----

def test_tin_run_allergen_set_is_union_of_products(api):
    """PRD §3.4: "the system computes the run's `allergen_set` — the union of the effective
    allergens across every product in `product_ids`, with a blend's allergens resolved from
    its components as described in §3.1 — which drives the cross-contamination labeling and
    the cleaning requirement."

    Design: Corner/calculations/corner_tin_run_allergen_set_union
    """
    sa = new_product(api, name="Sweet Almond Bits", category="HERB",
                     unit_price_cents_per_gram=5.0, tare_default_grams=5,
                     allergen_tags=["TREE_NUTS"])
    cham = new_product(api, name="Chamomile", category="HERB", unit_price_cents_per_gram=2.5)
    station = new_labeling_station(api)
    payload = {
        "labeling_station_id": station["id"],
        "product_ids": [sa["id"], cham["id"]],
        "scheduled_start": "2026-07-10T08:00:00Z",
        "scheduled_end": "2026-07-10T09:00:00Z",
    }
    run = validate_success(api.create_tin_run(payload, PROD), expected_status=201)
    assert "TREE_NUTS" in run["allergen_set"], run["allergen_set"]
