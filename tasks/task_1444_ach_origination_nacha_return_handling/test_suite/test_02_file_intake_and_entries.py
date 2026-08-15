"""File intake validation, entries-append atomicity/OCC, listing, consistency."""
from test_helpers import (
    ApiErrorId,
    append_entries_payload,
    create_ach_file_payload,
    create_active_originator,
    create_warehoused_file,
    define_cutoff_window,
    define_next_day_window,
    define_same_day_1_window,
    entry_payload,
    make_originator_headers,
    read_file,
    set_clock,
    setup_standard_environment,
    cancel_file_ok,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_file_intake_missing_sec_code_rejected(api, operations_headers):
    """PRD 2.6: "Required fields must be present, enum values must be in range
    (an unknown return code or NOC code fails here), `amount_cents` must be
    greater than zero, and date and time fields must be well-formed `YYYY-MM-DD`
    or `HH:MM` values; violations yield `ERR_INVALID_REQUEST`."

    Design: Corner/entities/file_create_missing_sec_code_returns_invalid_request
    """
    org = create_active_originator("Req Co", ["CCD"], exposure_limit_cents=1_000_000)
    set_clock("2026-08-03T09:00:00Z")

    payload = create_ach_file_payload("CCD", "NEXT_DAY", "2026-08-03")
    del payload["sec_code"]
    res = api.create_ach_file(payload, make_originator_headers(org["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_effective_date_window_boundaries(api, operations_headers):
    """PRD 3.3: "The effective date must be a banking day no earlier than today
    and no later than the date two banking days ahead — otherwise
    `ERR_EFFECTIVE_DATE_WINDOW`."
    PRD 2.4: "A **banking day** is any Monday through Friday; there is no
    holiday table."

    Design: Corner/calculations/effective_date_weekend_and_beyond_window_rejected
    """
    define_next_day_window()
    org = create_active_originator("Bank Co", ["CCD"])
    set_clock("2026-08-03T09:00:00Z")  # Monday; window is [08-03, 08-05]
    headers = make_originator_headers(org["id"])

    # Saturday 2026-08-08 is not a banking day.
    res = api.create_ach_file(
        create_ach_file_payload("CCD", "NEXT_DAY", "2026-08-08"), headers)
    validate_error(res, ApiErrorId.ERR_EFFECTIVE_DATE_WINDOW, expected_status=422)

    # 2026-08-06 is three banking days ahead — beyond the +2 window.
    res = api.create_ach_file(
        create_ach_file_payload("CCD", "NEXT_DAY", "2026-08-06"), headers)
    validate_error(res, ApiErrorId.ERR_EFFECTIVE_DATE_WINDOW, expected_status=422)

    # 2026-08-05 is exactly +2 banking days — admitted (inclusive boundary).
    ok = api.create_ach_file(
        create_ach_file_payload("CCD", "NEXT_DAY", "2026-08-05"), headers)
    created = validate_success(ok, 201)
    assert created["effective_date"] == "2026-08-05"
    assert created["status"] == "WAREHOUSED"


def test_intake_without_matching_window_rejected(api, operations_headers):
    """PRD 3.3: "A CutoffWindow row must exist for the requested kind; if none
    does, intake fails with `ERR_NO_ELIGIBLE_WINDOW`."

    Design: Corner/validations/append_with_undefined_window_kind_returns_no_eligible_window
    """
    define_next_day_window()  # only NEXT_DAY exists; no SAME_DAY_3 row
    org = create_active_originator("Win3 Co", ["CCD"])
    set_clock("2026-08-03T10:00:00Z")

    res = api.create_ach_file(
        create_ach_file_payload("CCD", "SAME_DAY_3", "2026-08-03"),
        make_originator_headers(org["id"]))
    validate_error(res, ApiErrorId.ERR_NO_ELIGIBLE_WINDOW, expected_status=422)


def test_bulk_append_atomic_on_mixed_validity(api, operations_headers):
    """PRD 3.3: "The append is atomic: if any entry is rejected, no entry from
    the batch is persisted."
    PRD 3.3: "If the file's `requested_window_kind` is one of the same-day kinds
    and any incoming entry's `amount_cents` exceeds $1,000,000.00, the append is
    rejected with `ERR_SAME_DAY_INELIGIBLE` — an entry of exactly $1,000,000.00
    is eligible."

    Design: Corner/endpoints/bulk_append_is_atomic_on_mixed_validity
    """
    define_same_day_1_window()
    define_next_day_window()
    org = create_active_originator("Bulk Co", ["CCD"],
                                   exposure_limit_cents=1_000_000_000)
    set_clock("2026-08-03T10:00:00Z")
    ach_file = create_warehoused_file(org, "CCD", "SAME_DAY_1", "2026-08-03")
    version_before = ach_file["version"]

    res = api.append_entries(
        ach_file["id"],
        append_entries_payload(ach_file["version"], [
            entry_payload("DEBIT", 1_000, "bk-1"),
            entry_payload("DEBIT", 100_000_001, "bk-2"),
        ]),
        make_originator_headers(org["id"]))
    validate_error(res, ApiErrorId.ERR_SAME_DAY_INELIGIBLE, expected_status=422)

    after = read_file(ach_file["id"])
    assert after["entry_count"] == 0, "atomic reject: no entry persisted"
    assert after["total_amount_cents"] == 0
    assert after["version"] == version_before, \
        "a rejected append must not bump the file version"


def test_stale_file_version_on_append_rejected(api, operations_headers):
    """PRD 2.7: "Because every successful entries-append legitimately mutates
    the file (totals and the quoted fee are recomputed, and `version`
    increments), a client appending against a version it has not observed is
    stale and is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/stale_file_version_on_entries_append_returns_412
    """
    org = setup_standard_environment("Occ2 Co")
    ach_file = create_warehoused_file(org, "CCD", "NEXT_DAY", "2026-08-03")
    stale_version = ach_file["version"]
    headers = make_originator_headers(org["id"])

    appended = validate_success(api.append_entries(
        ach_file["id"],
        append_entries_payload(stale_version,
                               [entry_payload("DEBIT", 100_000, "oc-1")]),
        headers), 200)

    res = api.append_entries(
        ach_file["id"],
        append_entries_payload(stale_version,
                               [entry_payload("DEBIT", 50_000, "oc-2")]),
        headers)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    after_reject = read_file(ach_file["id"])
    assert after_reject["entry_count"] == 1, "rejected append is atomic"

    retried = validate_success(api.append_entries(
        ach_file["id"],
        append_entries_payload(appended["version"],
                               [entry_payload("DEBIT", 50_000, "oc-2")]),
        headers), 200)
    assert retried["entry_count"] == 2
    assert retried["total_amount_cents"] == 150_000
    # NEXT_DAY card 60/200/100, no discount, no large-entry surcharge.
    assert retried["quoted_fee_cents"] == 320


def test_append_recompute_visible_immediately(api, operations_headers):
    """PRD 3.3: "The file's `version` increments by one; `entry_count` and
    `total_amount_cents` are recomputed as the count and the `amount_cents` sum
    over all of the file's entries in every status — figures that only ever
    grow, since cancelled or returned entries still count; and
    `quoted_fee_cents` is recomputed under the `requested_window_kind` rate
    card, failing with `ERR_NO_ELIGIBLE_WINDOW` if that window row is missing."
    PRD 2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    Design: Corner/consistency_model/immediate_visibility_after_append
    """
    org = setup_standard_environment("Imm2 Co")
    ach_file = create_warehoused_file(org, "CCD", "NEXT_DAY", "2026-08-03")

    res = api.append_entries(
        ach_file["id"],
        append_entries_payload(ach_file["version"], [
            entry_payload("DEBIT", 1_000, "im-1"),
            entry_payload("DEBIT", 2_000, "im-2"),
        ]),
        make_originator_headers(org["id"]))
    body = res.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert body["meta"]["api_request_id"].startswith("req_")

    appended = validate_success(res, 200)
    assert appended["entry_count"] == 2
    assert appended["total_amount_cents"] == 3_000
    # 200 file fee + 60 + 60 per-entry on the NEXT_DAY card, discount 0.
    assert appended["quoted_fee_cents"] == 320
    assert appended["version"] == ach_file["version"] + 1

    reread = read_file(ach_file["id"])
    assert reread["entry_count"] == appended["entry_count"]
    assert reread["total_amount_cents"] == appended["total_amount_cents"]
    assert reread["quoted_fee_cents"] == appended["quoted_fee_cents"]
    assert reread["version"] == appended["version"]


def test_file_list_pagination_and_status_filter(api, operations_headers):
    """PRD 3.3: "Files may be listed with optional `originator_id`, `status`,
    and `settlement_batch_id` filters plus the standard `limit` and `offset`
    pagination parameters."
    PRD 2.3: "Unless otherwise specified, all list endpoints return resources
    sorted by their creation timestamp in ascending order — that is, by
    `created_at` ascending, which is insertion order; `id` is never used for
    ordering."

    Design: Corner/entities/file_list_pagination_and_status_filter
    """
    org = setup_standard_environment("Page Co", exposure_limit_cents=1_000_000,
                                     clock="2026-08-03T09:00:00Z")
    file_a = create_warehoused_file(org, "CCD", "NEXT_DAY", "2026-08-03")
    file_b = create_warehoused_file(org, "CCD", "NEXT_DAY", "2026-08-03")
    cancel_file_ok(file_b["id"], org["id"])

    page, meta = validate_paginated(api.list_ach_files(
        operations_headers, params={"originator_id": org["id"], "limit": 1}))
    assert meta["total_count"] == 2
    assert len(page) == 1
    assert meta["has_more"] is True
    assert page[0]["id"] == file_a["id"], "created_at ascending insertion order"

    cancelled, meta_c = validate_paginated(api.list_ach_files(
        operations_headers,
        params={"originator_id": org["id"], "status": "CANCELLED"}))
    assert [f["id"] for f in cancelled] == [file_b["id"]]
    assert meta_c["total_count"] == 1

    warehoused, meta_w = validate_paginated(api.list_ach_files(
        operations_headers,
        params={"originator_id": org["id"], "status": "WAREHOUSED"}))
    assert [f["id"] for f in warehoused] == [file_a["id"]]
    assert meta_w["total_count"] == 1
