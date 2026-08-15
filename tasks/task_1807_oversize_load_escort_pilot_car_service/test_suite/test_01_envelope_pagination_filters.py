"""Envelope shape, pagination defaults/bounds, list filtering and ordering."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    register_carrier,
    register_escort,
    setup_booked_job,
    offer_assignment,
    setup_en_route_one_position_job,
    open_delay,
    close_delay,
    set_clock,
    api_client,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_success_and_error_envelope_shape(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.3: "Every paginated list response carries the pagination fields `limit`,
    `offset`, `total_count`, and `has_more` inside the `meta` object of the
    response envelope."

    Design: Corner/endpoints/response_envelope_shape
    """
    register_carrier(500000, "Envelope Co")

    resp = api.list_carriers(DISPATCHER)
    body = resp.json()
    assert "api_request_id" in body["meta"], "meta.api_request_id must be present"
    assert "api_request_timestamp" in body["meta"], "meta.api_request_timestamp must be present"
    rows, meta = validate_paginated(resp)
    assert body["response_type"] == "array"
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert len(rows) == 1

    err_resp = api.get_carrier("00000000-0000-0000-0000-0000000000c9", DISPATCHER)
    err_data = validate_error(err_resp, ApiErrorId.ERR_CARRIER_NOT_FOUND)
    err_body = err_resp.json()
    assert err_body["response_type"] == "error"
    assert err_data["error_id"] == "ERR_CARRIER_NOT_FOUND"
    assert isinstance(err_data["message"], str) and err_data["message"], (
        "error envelope must carry a non-empty message"
    )


def test_pagination_defaults_and_bounds(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned: it
    defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
    parameter skips a number of items from the start of the result set and
    defaults to 0."

    Design: Corner/cross_cutting_layers/pagination_defaults_and_bounds
    """
    for i in range(1, 13):
        register_carrier(100000, f"C{i:02d}")

    rows, meta = validate_paginated(api.list_carriers(DISPATCHER))
    assert len(rows) == 10, "default page must hold 10 rows"
    assert meta["total_count"] == 12
    assert meta["has_more"] is True

    rows2, meta2 = validate_paginated(api.list_carriers(DISPATCHER, params={"offset": 10}))
    assert len(rows2) == 2
    assert meta2["total_count"] == 12
    assert meta2["has_more"] is False

    # In-range explicit limit caps the page size (PRD §2.3 verbatim).
    # NOTE: the scaffold corner design's "limit 0/101 are out-of-range 400s"
    # consequence is not rendered anywhere in PRD.md prose (§2.3 names the range
    # but no rejection; §2.11's pipeline is scoped to mutating requests), so no
    # out-of-range assertion is made here — both reject and clamp are
    # PRD-consistent readings.
    rows3, meta3 = validate_paginated(api.list_carriers(DISPATCHER, params={"limit": 5}))
    assert len(rows3) == 5, "an explicit in-range limit caps the page size"
    assert meta3["limit"] == 5
    assert meta3["total_count"] == 12
    assert meta3["has_more"] is True


def test_escort_filter_by_state_code_membership_and_assignment_filters(api):
    """PRD §3.1: "The escort roster listing supports filtering by `state_code`
    (only escorts certified for that state are returned) and by `escort_status`,
    in addition to `limit` and `offset`."
    PRD §3.5: "a global assignment listing can be filtered by `escort_id`,
    `leg_id`, or `assignment_status`."

    Design: Corner/cross_cutting_layers/filter_and_list_composition
    """
    carrier = register_carrier(10_000_000, "FA")
    esc_tx = register_escort(("TX",), "TX only")
    set_clock("2026-08-01T00:01:00Z")
    register_escort(("OK",), "OK only")
    set_clock("2026-08-01T00:02:00Z")
    esc_both = register_escort(("TX", "OK"), "Both")

    bundle = setup_booked_job(carrier)
    asg = offer_assignment(bundle["leg"]["id"], "REAR", esc_tx["id"])

    rows, meta = validate_paginated(api.list_escorts(DISPATCHER, params={"state_code": "TX"}))
    ids = [r["id"] for r in rows]
    assert ids == [esc_tx["id"], esc_both["id"]], (
        f"state_code=TX must match arrays containing TX, got {ids}"
    )
    assert meta["total_count"] == 2

    rows_ks, meta_ks = validate_paginated(api.list_escorts(DISPATCHER, params={"state_code": "KS"}))
    assert rows_ks == [] and meta_ks["total_count"] == 0

    rows_off, _ = validate_paginated(
        api.list_assignments(
            DISPATCHER, params={"escort_id": esc_tx["id"], "assignment_status": "OFFERED"}
        )
    )
    assert [r["id"] for r in rows_off] == [asg["id"]]

    rows_dec, meta_dec = validate_paginated(
        api.list_assignments(
            DISPATCHER, params={"escort_id": esc_tx["id"], "assignment_status": "DECLINED"}
        )
    )
    assert rows_dec == [] and meta_dec["total_count"] == 0


def test_delay_events_listed_in_created_at_order(api):
    """PRD §2.3: "Unless otherwise specified, list endpoints return rows ordered
    by `created_at` in ascending order, so the first element of `data` is
    deterministic."

    Design: Corner/endpoints/list_ordering_created_at
    """
    bundle = setup_en_route_one_position_job(escort_name="Rider O")
    job_id = bundle["job"]["id"]

    set_clock("2026-08-10T10:00:00Z")
    d1 = open_delay(job_id, "WEATHER", "2026-08-10T10:00:00Z")
    set_clock("2026-08-10T10:15:00Z")
    d1 = close_delay(d1["id"])
    set_clock("2026-08-10T11:00:00Z")
    d2 = open_delay(job_id, "CURFEW_HOLD", "2026-08-10T11:00:00Z")
    set_clock("2026-08-10T11:15:00Z")
    d2 = close_delay(d2["id"])

    rows, meta = validate_paginated(api.list_job_delay_events(job_id, DISPATCHER))
    assert [r["id"] for r in rows] == [d1["id"], d2["id"]], (
        "delay events must come back in created_at ascending order"
    )
    assert rows[0]["raw_minutes"] == 15 and rows[0]["billable_minutes"] == 0
    assert rows[0]["standby_amount_cents"] == 0
    assert rows[1]["raw_minutes"] == 15 and rows[1]["billable_minutes"] == 0
    assert rows[1]["standby_amount_cents"] == 0
