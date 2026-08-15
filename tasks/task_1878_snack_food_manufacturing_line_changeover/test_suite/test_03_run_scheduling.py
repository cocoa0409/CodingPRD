"""Run scheduling: initial state, OCC on the line version, process-line
compatibility, schedule overlap with the allergen cleaning buffer, run listing,
and immediate read-after-write visibility."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_run,
    create_dairy_product,
    create_line,
    create_plain_product,
    create_run_payload,
    get_line,
    get_line_version,
    get_success_data,
    schedule_run,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]


class TestRunCreateContract:
    def test_run_create_initial_state_and_no_spurious_changeover(self, api):
        """PRD §3.2: "A successfully created run starts life with
        `execution_status` `SCHEDULED` and `quality_status` `PENDING`, and its
        creation increments the line's `version`."
        PRD §3.2: "When scheduling produces a requirement other than `NONE`,
        the system auto-creates a Changeover on the line in `REQUIRED` status
        aimed at the new product"

        Design: Corner/state_machines/run_create_initial_state_and_no_spurious_changeover
        """
        product = create_plain_product()
        line = create_line()
        resp = api.create_run(
            create_run_payload(line["id"], product["id"], line["version"]), PM,
        )
        run = validate_success(resp, 201)
        assert_run(run)
        assert run["execution_status"] == "SCHEDULED"
        assert run["quality_status"] == "PENDING"
        # requirement NONE on a fresh line -> no changeover is auto-created
        changeovers, meta = validate_paginated(api.list_changeovers(PM))
        assert changeovers == [] and meta["total_count"] == 0

    def test_run_create_body_fk_product_not_found(self, api):
        """PRD §2.9: "Resource existence: path parameters are resolved left to
        right, and then body foreign-key fields — `line_id`, `product_id`,
        `run_id`, `fryer_oil_id`, `promo_window_id`, `agreement_id`,
        `co_manufacturer_id`, `to_product_id` — are resolved."

        Design: Corner/validations/run_create_body_fk_product_not_found
        """
        line = create_line()
        resp = api.create_run(
            create_run_payload(line["id"], NON_EXISTENT_UUID, line["version"]),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND, 404)
        runs, meta = validate_paginated(api.list_runs(PM))
        assert runs == [] and meta["total_count"] == 0
        assert get_line_version(line["id"]) == line["version"], (
            "a rejected create must not mutate the line"
        )

    def test_fryer_product_on_oven_line_rejected(self, api):
        """PRD §3.2: "a `FRYER` product can only be scheduled on a line whose
        `line_type` is `FRYER` or `BOTH`, and an `OVEN` product only on `OVEN`
        or `BOTH`; any other pairing is rejected with
        `ERR_PROCESS_LINE_MISMATCH`."

        Design: Corner/validations/fryer_product_on_oven_line_rejected
        """
        product = create_plain_product()  # FRYER product
        line = create_line(name="Oven Line", line_type="OVEN",
                           oil_capacity_gallons=50)
        resp = api.create_run(
            create_run_payload(line["id"], product["id"], line["version"]), PM,
        )
        validate_error(resp, ApiErrorId.ERR_PROCESS_LINE_MISMATCH, 422)
        runs, meta = validate_paginated(api.list_runs(PM))
        assert runs == [] and meta["total_count"] == 0
        assert get_line_version(line["id"]) == line["version"]


class TestRunCreateOcc:
    def test_occ_run_create_stale_line_version(self, api):
        """PRD §2.7: "If another writer has advanced the line's version since
        that observation — for example through another run creation or through
        a run completion that rewrote the line's current allergen profile — the
        client's scheduling basis is stale even when the new run's own payload
        is independently valid, and the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_run_create_stale_line_version
        """
        product = create_plain_product()
        line = create_line()
        observed_v = line["version"]
        first = api.create_run(
            create_run_payload(line["id"], product["id"], observed_v,
                               scheduled_start="2026-08-02T08:00:00Z",
                               scheduled_end="2026-08-02T10:00:00Z"), PM,
        )
        validate_success(first, 201)
        # the first create advanced the line's version; replaying the stale
        # observation must be rejected even though the payload is valid
        stale = api.create_run(
            create_run_payload(line["id"], product["id"], observed_v,
                               scheduled_start="2026-08-03T08:00:00Z",
                               scheduled_end="2026-08-03T10:00:00Z"), PM,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)
        runs, meta = validate_paginated(api.list_runs(PM))
        assert meta["total_count"] == 1, "the stale create must not persist"
        assert get_line(line["id"])["version"] == observed_v + 1


class TestRunListingAndConsistency:
    def test_list_filter_by_execution_status(self, api):
        """PRD §3.2: "the run list accepts `line_id`, `product_id`, and
        `execution_status` filters alongside `limit` and `offset`"
        PRD §3.5: "A `PlantManager` may cancel a run that has not started
        producing — `execution_status` `SCHEDULED` or `HELD` — moving it to
        `CANCELLED`."

        Design: Corner/endpoints/list_filter_by_execution_status
        """
        product = create_plain_product()
        line = create_line()
        run1 = schedule_run(line["id"], product["id"],
                            start="2026-08-02T08:00:00Z",
                            end="2026-08-02T10:00:00Z")
        run2 = schedule_run(line["id"], product["id"],
                            start="2026-08-03T08:00:00Z",
                            end="2026-08-03T10:00:00Z")
        get_success_data(api.cancel_run(run2["id"], PM))

        cancelled, meta = validate_paginated(
            api.list_runs(PM, {"execution_status": "CANCELLED"}))
        assert [r["id"] for r in cancelled] == [run2["id"]]
        assert meta["total_count"] == 1
        scheduled, meta = validate_paginated(
            api.list_runs(PM, {"execution_status": "SCHEDULED"}))
        assert [r["id"] for r in scheduled] == [run1["id"]]
        assert meta["total_count"] == 1

    def test_immediate_read_after_write_visibility(self, api):
        """PRD §2.5: "`version` (integer): a system-managed integer that
        increments by one on every mutation, again including automatic cascades
        and derived-field recomputation."
        PRD §3.2: "A successfully created run starts life with
        `execution_status` `SCHEDULED` and `quality_status` `PENDING`, and its
        creation increments the line's `version`."

        Design: Corner/consistency_model/immediate_read_after_write_visibility
        """
        product = create_plain_product()
        line = create_line()
        observed_v = line["version"]
        run = get_success_data(api.create_run(
            create_run_payload(line["id"], product["id"], observed_v), PM))
        # the very next reads observe the create's side effects: no lag
        assert get_line(line["id"])["version"] == observed_v + 1
        runs, meta = validate_paginated(api.list_runs(PM))
        assert meta["total_count"] == 1
        assert runs[0]["id"] == run["id"]
        assert runs[0]["execution_status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Schedule overlap: half-open intervals with the allergen cleaning buffer
# ---------------------------------------------------------------------------

def _three_products_and_line():
    p_dairy_cheese = create_dairy_product(name="Cheese Puffs")
    p_dairy_spicy = create_dairy_product(name="Spicy Cheese Puffs",
                                         flavor_group="SPICY")
    p_plain = create_plain_product()
    line = create_line()  # default buffers: full wash 120, dry clean 30
    return p_dairy_cheese, p_dairy_spicy, p_plain, line


def _try_schedule(line_id, product_id, start, end):
    """Attempt a run create at the line's currently observed version."""
    line_v = get_line_version(line_id)
    return api_client.create_run(
        create_run_payload(line_id, product_id, line_v,
                           scheduled_start=start, scheduled_end=end), PM)


class TestScheduleOverlapBuffers:
    def test_half_open_adjacency_and_dry_clean_buffer(self, api):
        """PRD §3.2: "Runs on the same line occupy half-open intervals: a run
        occupies its `scheduled_start` up to but not including its
        `scheduled_end`, and any intersection with a sibling run's interval is
        rejected with `ERR_SCHEDULE_OVERLAP`."
        PRD §3.2: "whenever the changeover matrix below demands cleaning
        between two consecutive runs A then B on the same line, B's
        `scheduled_start` must fall no earlier than A's `scheduled_end` plus
        the applicable buffer — `cleaning_minutes_full_wash` for a full wash,
        `cleaning_minutes_dry` for a dry clean — and a violation is likewise
        rejected with `ERR_SCHEDULE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/run_schedule_half_open_with_allergen_buffer
        """
        p1, p2, _p3, line = _three_products_and_line()
        # runA: DAIRY/CHEESE product, 08:00-10:00
        run_a = schedule_run(line["id"], p1["id"],
                             start="2026-08-03T08:00:00Z",
                             end="2026-08-03T10:00:00Z")
        assert run_a["execution_status"] == "SCHEDULED"
        # runB: same product, starting exactly at A's end — half-open
        # adjacency with requirement NONE is legal (no buffer)
        run_b = schedule_run(line["id"], p1["id"],
                             start="2026-08-03T10:00:00Z",
                             end="2026-08-03T12:00:00Z")
        assert run_b["execution_status"] == "SCHEDULED"
        # runC: same allergens, flavor CHEESE -> SPICY is DRY_CLEAN (30 min);
        # 12:00 is earlier than 12:00 + 30 min
        resp = _try_schedule(line["id"], p2["id"],
                             "2026-08-03T12:00:00Z", "2026-08-03T14:00:00Z")
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_OVERLAP, 409)
        # exactly at end + dry buffer is legal
        run_c = schedule_run(line["id"], p2["id"],
                             start="2026-08-03T12:30:00Z",
                             end="2026-08-03T14:30:00Z")
        assert run_c["execution_status"] == "SCHEDULED"

    def test_full_wash_buffer_boundary(self, api):
        """PRD §3.2: "whenever the changeover matrix below demands cleaning
        between two consecutive runs A then B on the same line, B's
        `scheduled_start` must fall no earlier than A's `scheduled_end` plus
        the applicable buffer — `cleaning_minutes_full_wash` for a full wash,
        `cleaning_minutes_dry` for a dry clean — and a violation is likewise
        rejected with `ERR_SCHEDULE_OVERLAP`."
        PRD §3.2: "If the line's current allergen set contains any allergen
        absent from the target product's set — that is, any allergen would be
        removed by the switch — the required level is `FULL_WASH`."

        Design: Difficulty/resource_temporal_overlap/run_schedule_half_open_with_allergen_buffer
        """
        p1, p2, p3, line = _three_products_and_line()
        schedule_run(line["id"], p1["id"],
                     start="2026-08-03T08:00:00Z", end="2026-08-03T10:00:00Z")
        schedule_run(line["id"], p1["id"],
                     start="2026-08-03T10:00:00Z", end="2026-08-03T12:00:00Z")
        schedule_run(line["id"], p2["id"],
                     start="2026-08-03T12:30:00Z", end="2026-08-03T14:30:00Z")
        # runD: DAIRY removal -> FULL_WASH (120 min); 14:30 is earlier than
        # 14:30 + 120 min
        resp = _try_schedule(line["id"], p3["id"],
                             "2026-08-03T14:30:00Z", "2026-08-03T16:30:00Z")
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_OVERLAP, 409)
        # exactly at end + full-wash buffer is legal
        run_d = schedule_run(line["id"], p3["id"],
                             start="2026-08-03T16:30:00Z",
                             end="2026-08-03T18:30:00Z")
        assert run_d["execution_status"] == "SCHEDULED"
