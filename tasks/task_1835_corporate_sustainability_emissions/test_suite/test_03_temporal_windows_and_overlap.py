"""Interval semantics: half-open activity periods, closed factor windows,
the record reporting-year window, and the instrument vintage window."""
from test_helpers import (
    ApiErrorId, create_activity_record_payload, create_emission_factor_payload,
    create_instrument_payload, make_collecting_cycle, make_factor, make_site,
    submit_record, validate_error, validate_success,
)


def test_record_period_outside_cycle_year_returns_error(api, steward_headers):
    """PRD §3.3: "After the generic authentication, authorization, existence,
    and request-shape tiers of §2.10, the activity window must lie fully
    inside the cycle's reporting year — on or after midnight UTC on January 1
    of the `reporting_year` and before midnight UTC on January 1 of the
    following year — or the create fails with
    `ERR_PERIOD_OUTSIDE_CYCLE_YEAR`."

    Design: Corner/validations/record_period_outside_cycle_year_returns_error
    """
    site = make_site()
    # Factor window spans 2025-2026 so only the cycle-year rule can fail.
    factor = make_factor(valid_from="2025-01-01T00:00:00Z", valid_to="2026-12-31T23:59:59Z")
    cycle = make_collecting_cycle(reporting_year=2026)
    resp = api.create_activity_record(
        create_activity_record_payload(
            cycle["id"], site["id"], factor["id"],
            quantity=10, period_start="2025-06-01T00:00:00Z",
            period_end="2025-07-01T00:00:00Z",
        ),
        steward_headers,
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_OUTSIDE_CYCLE_YEAR, 422)


def test_activity_periods_overlap_rejected_and_adjacency_allowed(api, steward_headers):
    """PRD §3.3: "Next, the new record's half-open period must not intersect
    the period of any other record for the same `site_id` and `activity_type`
    in `SUBMITTED`, `UNDER_REVIEW`, or `APPROVED` status; because the
    intervals are half-open, periods that merely touch at a boundary instant
    are allowed, while a true intersection yields `ERR_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/activity_periods_half_open_overlap_and_adjacency
    """
    site = make_site()
    factor = make_factor()
    cycle = make_collecting_cycle()
    first = submit_record(
        cycle["id"], site["id"], factor["id"], quantity=10,
        period_start="2026-01-01T00:00:00Z", period_end="2026-03-01T00:00:00Z",
    )
    assert first["status"] == "SUBMITTED"

    overlapping = api.create_activity_record(
        create_activity_record_payload(
            cycle["id"], site["id"], factor["id"], quantity=10,
            period_start="2026-02-01T00:00:00Z", period_end="2026-04-01T00:00:00Z",
        ),
        steward_headers,
    )
    validate_error(overlapping, ApiErrorId.ERR_PERIOD_OVERLAP, 409)

    adjacent = api.create_activity_record(
        create_activity_record_payload(
            cycle["id"], site["id"], factor["id"], quantity=10,
            period_start="2026-03-01T00:00:00Z", period_end="2026-05-01T00:00:00Z",
        ),
        steward_headers,
    )
    adj_data = validate_success(adjacent, 201)
    assert adj_data["status"] == "SUBMITTED", (
        "start == existing period_end shares no instant of the half-open window"
    )


def test_activity_periods_overlap_scoped_to_site_and_activity_type(api, steward_headers):
    """PRD §3.3: "Next, the new record's half-open period must not intersect
    the period of any other record for the same `site_id` and `activity_type`
    in `SUBMITTED`, `UNDER_REVIEW`, or `APPROVED` status; because the
    intervals are half-open, periods that merely touch at a boundary instant
    are allowed, while a true intersection yields `ERR_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/activity_periods_half_open_overlap_and_adjacency
    """
    site = make_site()
    other_site = make_site(name="Annex")
    fuel_factor = make_factor()
    grid_factor = make_factor(
        scope_category="SCOPE2_GRID", region_code="CA", unit="MWh",
        value_tco2e_per_unit=0.4,
    )
    cycle = make_collecting_cycle()
    submit_record(
        cycle["id"], site["id"], fuel_factor["id"], quantity=10,
        period_start="2026-01-01T00:00:00Z", period_end="2026-03-01T00:00:00Z",
    )

    # Same window, same site, but a different activity_type: allowed.
    other_type = api.create_activity_record(
        create_activity_record_payload(
            cycle["id"], site["id"], grid_factor["id"],
            activity_type="ELECTRICITY", quantity=10, unit="MWh",
            period_start="2026-01-01T00:00:00Z", period_end="2026-03-01T00:00:00Z",
        ),
        steward_headers,
    )
    validate_success(other_type, 201)

    # Same window, same activity_type, but a different site: allowed.
    other_site_resp = api.create_activity_record(
        create_activity_record_payload(
            cycle["id"], other_site["id"], fuel_factor["id"], quantity=10,
            period_start="2026-01-01T00:00:00Z", period_end="2026-03-01T00:00:00Z",
        ),
        steward_headers,
    )
    validate_success(other_site_resp, 201)


def test_factor_windows_closed_touching_is_overlap(api, manager_headers):
    """PRD §3.1: "Two windows intersect whenever the candidate's `valid_from`
    is on or before the other factor's `valid_to` and the candidate's
    `valid_to` is on or after the other's `valid_from`; because both window
    ends are inclusive, windows that merely touch at a boundary instant still
    count as overlapping, and the publish is rejected with
    `ERR_FACTOR_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/factor_windows_closed_touching_is_overlap
    """
    make_factor(
        scope_category="SCOPE2_GRID", region_code="CA", unit="MWh",
        value_tco2e_per_unit=0.4, library_version=1,
        valid_from="2026-01-01T00:00:00Z", valid_to="2026-12-31T23:59:59Z",
    )
    touching = api.create_emission_factor(
        create_emission_factor_payload(
            scope_category="SCOPE2_GRID", region_code="CA", unit="MWh",
            value_tco2e_per_unit=0.41, library_version=2,
            valid_from="2026-12-31T23:59:59Z", valid_to="2027-12-31T23:59:59Z",
        ),
        manager_headers,
    )
    touching_id = validate_success(touching, 201)["id"]
    resp = api.transition_emission_factor(touching_id, {"to_state": "PUBLISHED"}, manager_headers)
    validate_error(resp, ApiErrorId.ERR_FACTOR_WINDOW_OVERLAP, 409)

    disjoint = api.create_emission_factor(
        create_emission_factor_payload(
            scope_category="SCOPE2_GRID", region_code="CA", unit="MWh",
            value_tco2e_per_unit=0.42, library_version=2,
            valid_from="2027-01-01T00:00:00Z", valid_to="2027-12-31T23:59:59Z",
        ),
        manager_headers,
    )
    disjoint_id = validate_success(disjoint, 201)["id"]
    published = api.transition_emission_factor(
        disjoint_id, {"to_state": "PUBLISHED"}, manager_headers
    )
    assert validate_success(published)["status"] == "PUBLISHED"


def test_factor_window_overlap_scoped_to_category_and_region(api, manager_headers):
    """PRD §3.1: "Publishing moves a factor from `DRAFT` to `PUBLISHED` and
    enforces library hygiene: among `PUBLISHED` factors sharing the same
    `scope_category` and `region_code`, the closed validity windows must be
    pairwise disjoint."

    Design: Difficulty/resource_temporal_overlap/factor_windows_closed_touching_is_overlap
    """
    make_factor(
        scope_category="SCOPE2_GRID", region_code="CA", unit="MWh",
        value_tco2e_per_unit=0.4,
        valid_from="2026-01-01T00:00:00Z", valid_to="2026-12-31T23:59:59Z",
    )
    # Same window but a different region_code: outside the disjointness scope.
    other_region = make_factor(
        scope_category="SCOPE2_GRID", region_code="TX", unit="MWh",
        value_tco2e_per_unit=0.6,
        valid_from="2026-01-01T00:00:00Z", valid_to="2026-12-31T23:59:59Z",
    )
    assert other_region["status"] == "PUBLISHED"

    # Same region_code but a different scope_category: also outside the scope.
    other_category = make_factor(
        scope_category="SCOPE2_RESIDUAL_MIX", region_code="CA", unit="MWh",
        value_tco2e_per_unit=0.5,
        valid_from="2026-01-01T00:00:00Z", valid_to="2026-12-31T23:59:59Z",
    )
    assert other_category["status"] == "PUBLISHED"


def test_instrument_vintage_window_boundary(api, manager_headers):
    """PRD §3.6: "The preconditions, in gauntlet order: the instrument must
    currently be `PROCURED` (`ERR_INVALID_STATE`); the target cycle must be
    collecting (`ERR_CYCLE_NOT_COLLECTING`); the `vintage_year` must be no
    earlier than three years before the cycle's `reporting_year` and no later
    than the `reporting_year` itself (`ERR_VINTAGE_INELIGIBLE`); and the
    target site must be `ACTIVE` (`ERR_SITE_INACTIVE`)."

    Design: Corner/validations/instrument_vintage_window_boundary
    """
    site = make_site()
    cycle = make_collecting_cycle(reporting_year=2026)
    resp_2022 = api.retire_instrument(
        validate_success(
            api.create_instrument(
                create_instrument_payload(serial_number="S-V22", technology="WIND",
                                          vintage_year=2022, quantity_mwh=10),
                manager_headers,
            ),
            201,
        )["id"],
        {"cycle_id": cycle["id"], "site_id": site["id"]},
        manager_headers,
    )
    validate_error(resp_2022, ApiErrorId.ERR_VINTAGE_INELIGIBLE, 422)

    # Vintage exactly three years before the reporting year is eligible.
    ok = api.retire_instrument(
        validate_success(
            api.create_instrument(
                create_instrument_payload(serial_number="S-V23", technology="WIND",
                                          vintage_year=2023, quantity_mwh=10),
                manager_headers,
            ),
            201,
        )["id"],
        {"cycle_id": cycle["id"], "site_id": site["id"]},
        manager_headers,
    )
    assert validate_success(ok)["status"] == "RETIRED", (
        "vintage 2023 == reporting_year - 3 is the inclusive lower boundary"
    )
