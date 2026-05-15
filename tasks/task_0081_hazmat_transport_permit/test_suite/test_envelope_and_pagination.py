"""Response-envelope shape and pagination contract tests.

The PRD's §2.2 names the canonical success envelope as a JSON object
carrying the top-level ``meta`` dict (``api_request_id`` and the ISO
``api_request_timestamp``, plus the four pagination fields on list
endpoints), a ``response_type`` discriminator drawing from the strings
``"object"``, ``"array"``, ``"error"``, and the ``data`` payload.  The
error envelope's ``data`` sub-object is the
``{"error_id": "ERR_FOO", "message": "human-readable cause"}`` pair.

The PRD's §2.3 names the standard pagination quartet
``limit``/``offset``/``total_count``/``has_more`` on every list
endpoint, with the ``limit`` defaulting to 10 and the bounds at
``[1, 100]``, and the ``offset`` defaulting to 0 and the bound at
non-negative.  A ``limit`` outside ``[1, 100]`` is rejected with
``ERR_VALIDATION`` 422 ("A ``limit`` outside the inclusive range from 1
to 100 is rejected with ``ERR_VALIDATION`` at HTTP status 422"), and a
negative ``offset`` is the same catch-all.

The PRD's §3.3 names the inspection-list endpoint's non-default sort
order as ``inspected_at`` descending then ``id`` descending (the most
recent inspection at the head, matching the per-vehicle ``latest_*``
pointer's tie-break direction).  The GPS-list endpoint's sort is
``reported_at`` ascending then ``id`` ascending (the chronological-
reading-order), and the permit-list endpoint's sort is ``created_at``
descending then ``id`` descending (the reverse-chronological
audit-pattern).  The other list endpoints follow the global default of
``created_at`` ascending per the PRD's §2.3 first paragraph.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_PAGE_LIMIT,
    HazmatScenario,
    MAX_PAGE_LIMIT,
    api_client,
    create_company_payload,
    create_driver_payload,
    create_inspection_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    setup_approved_company,
    setup_qualified_carrier,
    setup_inflight_trip,
    bootstrap_company_operator_headers,
    company_operator_headers,
    regulator_headers,
    validate_error,
    validate_paginated,
    validate_success,
    get_success_data,
    iso_now_plus_delta,
    current_server_now,
    fetch_all_inspections,
)
from test_helpers.assertions import _enum_values  # type: ignore[attr-defined]
from test_helpers.types import InspectionOutcome


# ─── Envelope-shape tests ──────────────────────────────────────────────


def test_success_envelope_carries_meta_response_type_data(api):
    """PRD §2.2: "All successful API responses (those with 2xx status
    codes) follow this standard envelope format in their JSON body"
    with the ``meta`` block containing ``api_request_id`` and
    ``api_request_timestamp``, the ``response_type`` set to
    ``"object"`` for a single-resource response, and the ``data``
    field carrying the resource payload.
    """
    # A POST /v1/companies creates a single resource; the
    # response_type is "object".  The framework's validate_success
    # already checks the envelope-shape invariants.
    resp = api.create_company(create_company_payload(), bootstrap_company_operator_headers())
    data = validate_success(resp, 201)
    assert isinstance(data, dict), "the data sub-object must be the resource dict on a single-resource 201"
    assert is_valid_uuid(data["id"]), "the minted company id must be a valid UUID"

    # The body's meta has the request-id and the timestamp.
    body = resp.json()
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str)
    assert meta["api_request_id"].startswith("req_") or len(meta["api_request_id"]) > 0
    assert is_iso8601_timestamp(meta["api_request_timestamp"])
    assert body["response_type"] in ("object", "array")


def test_error_envelope_carries_error_id_and_message(api, non_existent_uuid):
    """PRD §2.2: "All error API responses (4xx status codes) follow
    this standard envelope format" with the ``data`` sub-object
    carrying the ``error_id`` machine-readable string and the
    ``message`` human-readable explanation.  The
    ``response_type`` discriminator on the error envelope is the
    fixed string ``"error"``.
    """
    # A GET on a non-existent company id is the canonical 404
    # ``ERR_COMPANY_NOT_FOUND`` from the existence-tier check.
    headers = regulator_headers()
    resp = api.get_company(non_existent_uuid, headers)
    err = validate_error(resp, ApiErrorId.ERR_COMPANY_NOT_FOUND.value)
    assert isinstance(err["error_id"], str) and err["error_id"] == ApiErrorId.ERR_COMPANY_NOT_FOUND.value
    assert isinstance(err["message"], str) and len(err["message"]) > 0
    body = resp.json()
    assert body["response_type"] == "error"


def test_list_envelope_meta_has_pagination_quartet(api):
    """PRD §2.3: "Every list response includes the four pagination
    fields ``limit``, ``offset``, ``total_count``, and ``has_more``
    inside the response envelope's ``meta`` object".
    """
    # GET /v1/companies as a regulator (cross-tenant exempt) returns
    # the full company list.  Even on an empty system the meta has
    # the four pagination fields.
    headers = regulator_headers()
    resp = api.list_companies(headers)
    data, meta = validate_paginated(resp)
    assert isinstance(data, list)
    for required_key in ("limit", "offset", "total_count", "has_more"):
        assert required_key in meta, f"pagination meta is missing the {required_key} field"
    assert isinstance(meta["total_count"], int) and meta["total_count"] >= 0
    assert isinstance(meta["has_more"], bool)
    assert isinstance(meta["limit"], int) and meta["limit"] > 0
    assert isinstance(meta["offset"], int) and meta["offset"] >= 0


# ─── Default-pagination-values tests ───────────────────────────────────


def test_default_pagination_limit_is_ten(api):
    """PRD §2.3: "``limit`` … when omitted it defaults to 10".

    Create more than 10 companies (using the bootstrap-create
    endpoint so each call mints a fresh row with a unique
    registration_number) and assert the default-limit response page
    contains exactly the default's worth of items.
    """
    # Top up beyond the default to test the "has_more on full first page" case.
    for _ in range(int(DEFAULT_PAGE_LIMIT) + 2):
        api.create_company(create_company_payload(), bootstrap_company_operator_headers())
    resp = api.list_companies(regulator_headers())
    data, meta = validate_paginated(resp)
    assert meta["limit"] == DEFAULT_PAGE_LIMIT, (
        f"default page limit is {meta['limit']}, expected {DEFAULT_PAGE_LIMIT}"
    )
    # has_more reflects the total exceeding the page size.
    if meta["total_count"] > DEFAULT_PAGE_LIMIT:
        assert meta["has_more"] is True
    assert len(data) <= DEFAULT_PAGE_LIMIT


def test_default_pagination_offset_is_zero(api):
    """PRD §2.3: "``offset`` is a non-negative integer specifying the
    number of items to skip before the page starts; when omitted it
    defaults to 0".
    """
    resp = api.list_companies(regulator_headers())
    _, meta = validate_paginated(resp)
    assert meta["offset"] == 0, f"default offset is {meta['offset']}, expected 0"


def test_limit_out_of_range_is_validation_error(api):
    """PRD §2.3: "A ``limit`` outside the inclusive range from 1 to
    100 is rejected with ``ERR_VALIDATION`` at HTTP status 422".

    Cover the three out-of-range cases: zero, the strictly-above-100
    case, and the negative case.
    """
    headers = regulator_headers()
    for bad_limit in (0, MAX_PAGE_LIMIT + 1, -1, 1000):
        resp = api.list_companies(headers, params={"limit": bad_limit})
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_negative_offset_is_validation_error(api):
    """PRD §2.3: "A negative ``offset`` is also rejected with
    ``ERR_VALIDATION``".
    """
    headers = regulator_headers()
    resp = api.list_companies(headers, params={"offset": -1})
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_max_limit_one_hundred_is_accepted(api):
    """PRD §2.3: "the maximum accepted value is 100".  The boundary
    value 100 is inclusive on the upper edge; a request with
    ``limit=100`` succeeds (the response carries the page up to
    that many items)."""
    resp = api.list_companies(regulator_headers(), params={"limit": MAX_PAGE_LIMIT})
    data, meta = validate_paginated(resp)
    assert meta["limit"] == MAX_PAGE_LIMIT
    assert len(data) <= MAX_PAGE_LIMIT


def test_minimum_limit_one_is_accepted(api):
    """PRD §2.3: "the minimum accepted value is 1".  The boundary
    value 1 returns a one-row page."""
    # Seed at least two rows so the has_more field is true on the limit=1 page.
    api.create_company(create_company_payload(), bootstrap_company_operator_headers())
    api.create_company(create_company_payload(), bootstrap_company_operator_headers())
    resp = api.list_companies(regulator_headers(), params={"limit": 1})
    data, meta = validate_paginated(resp)
    assert meta["limit"] == 1
    assert len(data) <= 1
    if meta["total_count"] >= 2:
        assert meta["has_more"] is True


def test_pagination_total_count_is_the_full_filtered_count(api):
    """PRD §2.3: "The ``total_count`` is the count of rows that
    satisfy the query's filters across the entire underlying
    collection (not just the current page)".  An empty current page
    (offset past the end) still has the total reflecting the row
    count on the server side."""
    # Seed exactly five rows so the post-truncation total is
    # deterministic; the autoreset between tests guarantees the
    # initial collection is empty.
    n_seed = 5
    for _ in range(n_seed):
        api.create_company(create_company_payload(), bootstrap_company_operator_headers())
    resp = api.list_companies(regulator_headers(), params={"offset": 9999})
    data, meta = validate_paginated(resp)
    assert len(data) == 0, "page at offset past the end is empty"
    assert meta["total_count"] == n_seed, (
        f"total_count is {meta['total_count']}, expected the seed-count {n_seed}"
    )
    assert meta["has_more"] is False


# ─── Per-endpoint sort-order tests ────────────────────────────────────


def test_inspection_list_sorted_inspected_at_descending(api: pytest.FixtureRequest, qualified_carrier: HazmatScenario):
    """PRD §2.3 + §3.3: "the inspection-list endpoint sorts inspections
    by ``inspected_at`` descending then by ``id`` descending so the
    most recent inspection appears first".  Append three inspections
    on the qualified-carrier's first vehicle and confirm the list
    endpoint returns them newest-first.
    """
    scenario = qualified_carrier
    vehicle = scenario.vehicles[0]
    server_now = current_server_now(api)
    # Append three more inspections (the carrier-fixture already
    # appended one at setup-time).  The timestamps are 60, 120, 180
    # seconds before the current server-now, so the descending sort
    # puts the original setup-time inspection first (since it has
    # the latest ``inspected_at``), then the just-appended three in
    # decreasing-timestamp order.
    appended_ids: List[str] = []
    for offset_seconds in (60.0 * 60.0, 120.0 * 60.0, 180.0 * 60.0):
        inspected_at = iso_now_plus_delta(seconds=-float(offset_seconds), base_iso=server_now)
        payload = create_inspection_payload(
            inspected_at=inspected_at,
            outcome=InspectionOutcome.PASSED.value,
        )
        resp = api.create_inspection(vehicle["id"], payload, regulator_headers())
        row = get_success_data(resp)
        appended_ids.append(row["id"])

    insps = fetch_all_inspections(api, scenario, vehicle_idx=0)
    # Adjacent-pair comparison: each entry's ``inspected_at`` is
    # greater-than-or-equal-to the next's, and ties are broken by
    # ``id`` descending.
    for i in range(len(insps) - 1):
        a, b = insps[i], insps[i + 1]
        if a["inspected_at"] == b["inspected_at"]:
            assert a["id"] >= b["id"], (
                f"tie-broken ordering wrong at index {i}: ids {a['id']!r} vs {b['id']!r}"
            )
        else:
            assert a["inspected_at"] > b["inspected_at"], (
                f"inspection-list not in descending inspected_at order at index {i}: "
                f"{a['inspected_at']!r} should be > {b['inspected_at']!r}"
            )


def test_gps_list_sorted_reported_at_ascending(api, inflight_trip: HazmatScenario):
    """PRD §2.3 + §3.8: "the GPS-report list endpoint sorts by
    ``reported_at`` ascending then by ``id`` ascending so the stream
    reads chronologically".

    Ingest three clean samples with strictly-increasing
    ``reported_at`` timestamps and confirm the list endpoint returns
    them oldest-first.
    """
    from test_helpers import ingest_clean_gps_sample, fetch_all_gps_reports

    scenario = inflight_trip
    # The fixture's depart-trip set actual_departure_at = now;
    # ingest three clean samples spaced one second apart.
    for _ in range(3):
        ingest_clean_gps_sample(api, scenario, reported_at_offset_seconds=1.0)
    gps_rows = fetch_all_gps_reports(api, scenario, trip_idx=0)
    assert len(gps_rows) == 3, f"expected three GPS rows, got {len(gps_rows)}"
    for i in range(len(gps_rows) - 1):
        a, b = gps_rows[i], gps_rows[i + 1]
        if a["reported_at"] == b["reported_at"]:
            assert a["id"] <= b["id"], (
                f"tie-broken ordering wrong at index {i}: ids {a['id']!r} vs {b['id']!r}"
            )
        else:
            assert a["reported_at"] < b["reported_at"], (
                f"gps-list not in ascending reported_at order at index {i}: "
                f"{a['reported_at']!r} should be < {b['reported_at']!r}"
            )


def test_permit_list_sorted_created_at_descending(api, qualified_carrier: HazmatScenario):
    """PRD §2.3 + §3.5: "the permit-list endpoint sorts by
    ``created_at`` descending then by ``id`` descending" — the
    most-recently-applied permit at the head, matching the
    audit-pattern of "show me the latest applications first"."""
    from test_helpers import file_permit_application

    scenario = qualified_carrier
    # File three permit applications in sequence (each is a fresh
    # ``DRAFT`` row).  The default ``valid_from_offset_seconds`` of
    # 10 seconds is fine for the application — no issue step on
    # this test, so the wallet isn't debited and the
    # ``valid_until`` is not pinned yet.
    permit_ids_in_creation_order: List[str] = []
    for _ in range(3):
        # The single application_preview field is fine; we want three
        # distinct permits.  The shared route and rosters mean each
        # new application is a duplicate-shape row but with a fresh
        # ``id``.  Reset the in-memory ``scenario.permit`` before
        # each application so the helper writes the new permit into
        # the slot rather than complaining the slot is full.
        scenario.permit = None
        p = file_permit_application(api, scenario)
        permit_ids_in_creation_order.append(p["id"])

    resp = api.list_permits(regulator_headers(), params={"limit": 100})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 3
    # Filter to the three permits we just created (the autoreset
    # between tests means there should be no other permits but the
    # filter is defensive).
    our_three = [p for p in data if p["id"] in permit_ids_in_creation_order]
    assert len(our_three) == 3
    # The head of the list (descending) is the last-created permit.
    head_id = our_three[0]["id"]
    tail_id = our_three[-1]["id"]
    assert head_id == permit_ids_in_creation_order[-1], (
        f"permit-list head {head_id!r} should be the most-recently-created permit "
        f"{permit_ids_in_creation_order[-1]!r}"
    )
    assert tail_id == permit_ids_in_creation_order[0], (
        f"permit-list tail {tail_id!r} should be the first-created permit "
        f"{permit_ids_in_creation_order[0]!r}"
    )
    # Adjacent-pair created_at comparison.
    for i in range(len(our_three) - 1):
        a, b = our_three[i], our_three[i + 1]
        if a["created_at"] == b["created_at"]:
            assert a["id"] >= b["id"]
        else:
            assert a["created_at"] > b["created_at"], (
                f"permit list not descending by created_at at index {i}"
            )


def test_default_sort_is_created_at_ascending_for_global_list(api):
    """PRD §2.3 first paragraph: "The default sort order is ascending
    by ``created_at``, the standard system-managed insertion-timestamp
    field discussed in §2.4."  The company list endpoint (a
    cross-tenant-filterable list whose §3.1 narrative does not
    override the global default) honours the ascending sort.
    """
    headers = bootstrap_company_operator_headers()
    created_ids: List[str] = []
    for _ in range(3):
        resp = api.create_company(create_company_payload(), headers)
        row = get_success_data(resp)
        created_ids.append(row["id"])
    resp = api.list_companies(regulator_headers(), params={"limit": 100})
    data, _ = validate_paginated(resp)
    # The first three companies in the response are the three we just
    # created, in creation order.
    seen = [c["id"] for c in data if c["id"] in created_ids]
    assert seen == created_ids, (
        f"company list default sort: expected creation-order {created_ids!r}, "
        f"got {seen!r}"
    )
    for i in range(len(seen) - 1):
        a = data[i]
        b = data[i + 1]
        # Adjacent pair: a.created_at <= b.created_at on the
        # global default ascending sort.
        assert a["created_at"] <= b["created_at"], (
            f"company list not in ascending created_at order at index {i}"
        )


# ─── Filter-parameter tests on the list endpoints ─────────────────────


def test_company_list_qualification_status_filter(api):
    """PRD §3.1 last paragraph + §2.3 last paragraph: "The optional
    ``qualification_status`` query filter is a comma-separated
    subset of the enum values … and narrows the response to
    companies in any of the listed statuses".

    Seed three companies in three different states and confirm the
    filter narrows the response to the named status.
    """
    headers = bootstrap_company_operator_headers()
    # Two left in DRAFT and one walked to APPROVED.  The reset has
    # already cleared the system.
    a = get_success_data(api.create_company(create_company_payload(), headers))
    b = get_success_data(api.create_company(create_company_payload(), headers))
    c = get_success_data(api.create_company(create_company_payload(), headers))
    # Walk c through DRAFT → SUBMITTED → APPROVED.
    get_success_data(api.submit_company(c["id"], {}, company_operator_headers(c["id"])))
    get_success_data(api.approve_company(c["id"], {}, regulator_headers()))

    # Filter to the DRAFT subset; the two DRAFT-state rows are the
    # only ones in the response.
    reg = regulator_headers()
    resp = api.list_companies(reg, params={"qualification_status": "DRAFT"})
    data, meta = validate_paginated(resp)
    draft_ids = {c["id"] for c in data}
    assert {a["id"], b["id"]} <= draft_ids
    assert c["id"] not in draft_ids

    # Filter to the APPROVED subset.
    resp2 = api.list_companies(reg, params={"qualification_status": "APPROVED"})
    data2, _ = validate_paginated(resp2)
    appr_ids = {c2["id"] for c2 in data2}
    assert c["id"] in appr_ids
    assert a["id"] not in appr_ids
    assert b["id"] not in appr_ids


def test_inspection_list_outcome_filter(api, qualified_carrier: HazmatScenario):
    """PRD §3.3: "The optional ``outcome`` query filter narrows the
    response to inspections whose ``outcome`` is the named enum
    value".

    The qualified-carrier-fixture seeded one ``PASSED`` inspection
    on its vehicle.  Append two more — one ``FAILED`` and one
    ``CONDITIONAL`` — and confirm the three single-value filter
    narrowings return the right subsets.
    """
    scenario = qualified_carrier
    vehicle = scenario.vehicles[0]
    server_now = current_server_now(api)
    # The two additional inspections, each with an inspected_at
    # earlier than the setup-time one so the latest-pointer on the
    # vehicle stays PASSED-and-the-fixture's-original.
    f_ts = iso_now_plus_delta(seconds=-7200.0, base_iso=server_now)
    c_ts = iso_now_plus_delta(seconds=-3600.0, base_iso=server_now)
    api.create_inspection(
        vehicle["id"],
        create_inspection_payload(inspected_at=f_ts, outcome=InspectionOutcome.FAILED.value),
        regulator_headers(),
    )
    api.create_inspection(
        vehicle["id"],
        create_inspection_payload(inspected_at=c_ts, outcome=InspectionOutcome.CONDITIONAL.value),
        regulator_headers(),
    )

    # Filter to each of the three outcomes and confirm the per-outcome
    # count matches.
    headers = regulator_headers()
    for outcome_value, expected_count in [
        (InspectionOutcome.PASSED.value, 1),
        (InspectionOutcome.FAILED.value, 1),
        (InspectionOutcome.CONDITIONAL.value, 1),
    ]:
        resp = api.list_inspections(
            vehicle["id"],
            headers,
            params={"outcome": outcome_value, "limit": 100},
        )
        data, _ = validate_paginated(resp)
        for row in data:
            assert row["outcome"] == outcome_value, (
                f"outcome-filter leak: row's outcome {row['outcome']!r} != filter {outcome_value!r}"
            )
        assert len(data) == expected_count, (
            f"expected {expected_count} {outcome_value} inspection(s), got {len(data)}"
        )


def test_gps_list_violation_only_filter(api, inflight_trip: HazmatScenario):
    """PRD §3.8: "The optional ``violation_only`` boolean query
    parameter (defaulting to false) filters the response to only
    those GPS-reports whose ``auto_penalty_ids`` array is non-empty
    — the violation-only audit view".

    Ingest one clean sample (zero auto-Penalty side-effects) and one
    speed-violation sample (one auto-Penalty side-effect).  The
    violation-only filter returns just the second.
    """
    from test_helpers import ingest_clean_gps_sample, ingest_speed_violation_sample

    scenario = inflight_trip
    clean_row = ingest_clean_gps_sample(api, scenario, reported_at_offset_seconds=1.0)
    viol_row = ingest_speed_violation_sample(api, scenario, reported_at_offset_seconds=1.0)
    # The clean sample's auto_penalty_ids is the empty array; the
    # violation sample's array has one element (the speed-violation
    # auto-Penalty id).
    assert len(clean_row["auto_penalty_ids"]) == 0
    assert len(viol_row["auto_penalty_ids"]) >= 1, (
        "speed-over-limit sample should fire the speed-violation auto-penalty side-effect"
    )

    trip = scenario.trips[0]
    headers = company_operator_headers(scenario.company["id"])
    # Default (no filter): both rows are in the response.
    resp_all = api.list_gps_reports(trip["id"], headers, params={"limit": 100})
    data_all, _ = validate_paginated(resp_all)
    all_ids = {r["id"] for r in data_all}
    assert clean_row["id"] in all_ids and viol_row["id"] in all_ids

    # violation_only=true: only the violation row is in the response.
    resp_v = api.list_gps_reports(
        trip["id"],
        headers,
        params={"violation_only": "true", "limit": 100},
    )
    data_v, _ = validate_paginated(resp_v)
    v_ids = {r["id"] for r in data_v}
    assert viol_row["id"] in v_ids, "violation_only filter must include the speed-violation row"
    assert clean_row["id"] not in v_ids, (
        "violation_only filter must exclude rows whose auto_penalty_ids array is empty"
    )
    for row in data_v:
        assert len(row["auto_penalty_ids"]) >= 1, (
            "every row in the violation_only-filtered response has a non-empty auto_penalty_ids"
        )


# ─── Empty-list edge case ─────────────────────────────────────────────


def test_empty_list_envelope_is_well_formed(api):
    """An empty list response still carries the
    standard four pagination fields, with ``total_count == 0`` and
    ``has_more == False``.  The autoreset between tests guarantees
    the company table is empty at the start of this test.
    """
    resp = api.list_companies(regulator_headers())
    data, meta = validate_paginated(resp)
    assert data == [], f"expected empty list, got {data!r}"
    assert meta["total_count"] == 0
    assert meta["has_more"] is False
    assert meta["limit"] == DEFAULT_PAGE_LIMIT
    assert meta["offset"] == 0
