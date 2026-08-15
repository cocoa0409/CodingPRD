"""Activity-record creation: computed fields, FK resolution, validation
gauntlet order, unit consistency, and list pagination."""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, assert_activity_record,
    create_activity_record_payload, make_collecting_cycle, make_cycle,
    make_factor, make_site, submit_record, validate_error, validate_paginated,
    validate_success,
)


def _site_factor_cycle(year=2026, factor_window=None):
    site = make_site()
    factor_kwargs = {}
    if factor_window:
        factor_kwargs["valid_from"], factor_kwargs["valid_to"] = factor_window
    factor = make_factor(**factor_kwargs)
    cycle = make_collecting_cycle(reporting_year=year)
    return site, factor, cycle


def test_record_create_ignores_client_supplied_tco2e(api, steward_headers):
    """PRD §3.3: "A new record enters `SUBMITTED`, with the creator's
    `X-User-ID` captured as `submitted_by_user_id`; `reviewed_by_user_id`,
    `reject_reason`, `factor_value_snapshot`, and `tco2e` all stay null until
    later workflow steps."

    Design: Corner/entities/record_create_computed_tco2e_input_ignored
    """
    site, factor, cycle = _site_factor_cycle()
    payload = create_activity_record_payload(
        cycle["id"], site["id"], factor["id"], quantity=10,
    )
    payload["tco2e"] = 999  # computed at approval; a client value must be ignored
    resp = api.create_activity_record(payload, steward_headers)
    data = validate_success(resp, 201)
    assert_activity_record(data)
    assert data["status"] == "SUBMITTED"
    assert data.get("tco2e") is None, (
        "tco2e is computed at approval; the client-supplied 999 must be ignored"
    )
    fetched = validate_success(api.get_activity_record(data["id"], steward_headers))
    assert fetched.get("tco2e") is None
    assert fetched.get("factor_value_snapshot") is None


def test_record_create_with_unknown_site_returns_not_found(api, steward_headers):
    """PRD §2.10: "Existence — every path identifier and every body-supplied
    foreign key (`cycle_id`, `site_id`, `factor_id`, `activity_record_id`,
    `supersedes_evidence_id`) resolves to an existing resource:
    `ERR_NOT_FOUND`."

    Design: Corner/entities/record_create_with_unknown_site_returns_not_found
    """
    factor = make_factor()
    cycle = make_collecting_cycle()
    resp = api.create_activity_record(
        create_activity_record_payload(
            cycle["id"], NON_EXISTENT_UUID, factor["id"], quantity=10,
        ),
        steward_headers,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


def test_record_create_state_gate_beats_temporal_violation(api, steward_headers):
    """PRD §2.10: "Every request passes through an ordered validation
    gauntlet; when several checks would fail, the error returned belongs to
    the earliest applicable tier below." with "6. **State gates** ... for
    child mutations, the parent cycle sits in `DATA_COLLECTION` or
    `UNDER_REVIEW` (`ERR_CYCLE_NOT_COLLECTING`)" ordered before "9.
    **Temporal windows** — activity period inside the reporting year
    (`ERR_PERIOD_OUTSIDE_CYCLE_YEAR`, record creation)".

    Design: Difficulty/priority_pair_validation_conflict/create_record_state_beats_temporal
    """
    site = make_site()
    # Factor window covers mid-2025 so only the temporal tier could fail.
    factor = make_factor(valid_from="2025-01-01T00:00:00Z", valid_to="2026-12-31T23:59:59Z")
    cycle = make_cycle()  # left in DRAFT — never opened for collection
    resp = api.create_activity_record(
        create_activity_record_payload(
            cycle["id"], site["id"], factor["id"],
            quantity=10, period_start="2025-06-01T00:00:00Z",
            period_end="2025-07-01T00:00:00Z",
        ),
        steward_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_COLLECTING, 409)


def test_record_create_state_gate_beats_temporal_straddling_period(api, steward_headers):
    """PRD §2.10: "Every request passes through an ordered validation
    gauntlet; when several checks would fail, the error returned belongs to
    the earliest applicable tier below." with "6. **State gates** ... for
    child mutations, the parent cycle sits in `DATA_COLLECTION` or
    `UNDER_REVIEW` (`ERR_CYCLE_NOT_COLLECTING`)" ordered before "9.
    **Temporal windows** — activity period inside the reporting year
    (`ERR_PERIOD_OUTSIDE_CYCLE_YEAR`, record creation)".

    Design: Difficulty/priority_pair_validation_conflict/create_record_state_beats_temporal
    """
    site = make_site()
    factor = make_factor(valid_from="2025-01-01T00:00:00Z", valid_to="2027-12-31T23:59:59Z")
    cycle = make_cycle()  # DRAFT
    # A period straddling the 2026/2027 year boundary is also outside the
    # cycle year, yet the state gate must still win.
    resp = api.create_activity_record(
        create_activity_record_payload(
            cycle["id"], site["id"], factor["id"],
            quantity=10, period_start="2026-12-15T00:00:00Z",
            period_end="2027-01-15T00:00:00Z",
        ),
        steward_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_COLLECTING, 409)


def test_record_unit_mismatch_returns_error(api, steward_headers):
    """PRD §3.3: "Then unit consistency is enforced: the record's `unit` must
    equal the referenced factor's `unit`, and the `activity_type` must map to
    the factor's `scope_category` — `ELECTRICITY` pairs with `SCOPE2_GRID`,
    `STATIONARY_FUEL` with `SCOPE1_STATIONARY`, and `BUSINESS_TRAVEL` with
    `SCOPE3_TRAVEL` — with violations rejected as `ERR_UNIT_MISMATCH`."

    Design: Corner/validations/record_unit_mismatch_returns_error
    """
    site = make_site()
    factor = make_factor(
        scope_category="SCOPE2_GRID", region_code="CA", unit="MWh",
        value_tco2e_per_unit=0.4,
    )
    cycle = make_collecting_cycle()
    unit_mismatch = api.create_activity_record(
        create_activity_record_payload(
            cycle["id"], site["id"], factor["id"],
            activity_type="ELECTRICITY", quantity=10, unit="kWh",
        ),
        steward_headers,
    )
    validate_error(unit_mismatch, ApiErrorId.ERR_UNIT_MISMATCH, 422)

    category_mismatch = api.create_activity_record(
        create_activity_record_payload(
            cycle["id"], site["id"], factor["id"],
            activity_type="STATIONARY_FUEL", quantity=10, unit="MWh",
        ),
        steward_headers,
    )
    validate_error(category_mismatch, ApiErrorId.ERR_UNIT_MISMATCH, 422)


def test_record_create_with_draft_factor_returns_error(api, steward_headers):
    """PRD §3.3: "Finally, the referenced site must still be `ACTIVE`
    (`ERR_SITE_INACTIVE`), and the referenced factor must be `PUBLISHED` with
    a closed validity window that fully covers the record's period
    (`ERR_FACTOR_NOT_PUBLISHED`)."

    Design: Corner/validations/record_create_with_draft_factor_returns_error
    """
    site = make_site()
    factor = make_factor(publish=False)  # stays DRAFT
    cycle = make_collecting_cycle()
    resp = api.create_activity_record(
        create_activity_record_payload(cycle["id"], site["id"], factor["id"], quantity=10),
        steward_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FACTOR_NOT_PUBLISHED, 422)


def test_activity_records_list_paginates(api, manager_headers, steward_headers):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
    parameter skips a number of items and defaults to 0." and "Paginated list
    responses carry `limit`, `offset`, `total_count`, and `has_more` in the
    `meta` object of the envelope."

    Design: Corner/entities/activity_records_list_paginates
    """
    site, factor, cycle = _site_factor_cycle()
    periods = [
        ("2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z"),
        ("2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z"),
        ("2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z"),
    ]
    for qty, (start, end) in zip((1, 2, 3), periods):
        submit_record(
            cycle["id"], site["id"], factor["id"],
            quantity=qty, period_start=start, period_end=end,
        )

    page1, meta1 = validate_paginated(
        api.list_activity_records(
            manager_headers, params={"cycle_id": cycle["id"], "limit": 2, "offset": 0}
        )
    )
    assert len(page1) == 2, f"page 1 must hold exactly 2 records, got {len(page1)}"
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_activity_records(
            manager_headers, params={"cycle_id": cycle["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(page2) == 1, f"page 2 must hold exactly 1 record, got {len(page2)}"
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
