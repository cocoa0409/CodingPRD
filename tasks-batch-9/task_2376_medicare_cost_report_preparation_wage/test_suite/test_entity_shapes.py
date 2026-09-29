"""Entity field contracts: what a create echoes, what the server mints itself,
what a read exposes, and how a malformed or dangling reference is refused."""

from test_helpers import (
    ANALYST_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_cost_center,
    assert_cost_report,
    assert_money_equals,
    assert_provider,
    assert_resident,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    cost_center_payload,
    provider_payload,
    resident_payload,
    rotation_assignment_payload,
)
from test_helpers.fixtures import (
    CENTER_ROUTINE,
    add_cost_center,
    add_mapped_tb_line,
    create_cost_report,
    create_other_provider,
    new_scenario,
    read_cost_center,
    read_cost_report,
    role_headers_for,
    set_clock,
)

UNKNOWN_COST_REPORT_ID = "00000000-0000-0000-0000-0000000000aa"


def test_provider_registration_echoes_every_declared_field(api):
    """Registering Mercy General returns the six supplied inputs unchanged and the
    server-maintained approved period count at 0.

    PRD 3.1: "A hospital enters the system as a **Provider**, registered by a `SystemAdmin` with its CMS certification number `ccn` (exactly six characters, digits only, and unique across all providers), its legal `name` (between 1 and 200 characters), and the `cbsa_code` of its labor market area (exactly five characters, digits only) which is what groups it for wage index purposes."

    PRD 3.1: "Two fields are never supplied: `approved_interim_period_count`, which the server maintains as the count of that provider's interim rate requests in `APPROVED` status and which starts at 0, and the provider's own `version`."

    Design: Corner/entities/provider_creation_returns_all_declared_fields
    """
    set_clock(api)

    provider = validate_success(
        api.create_provider(provider_payload(), SYSTEM_ADMIN_HEADERS), 201
    )

    assert_provider(provider)
    assert provider["ccn"] == "450123"
    assert provider["name"] == "Mercy General Hospital"
    assert provider["cbsa_code"] == "19100"
    assert provider["teaching_status"] == "TEACHING"
    assert provider["fte_cap"] == 2.00
    assert_money_equals(
        provider["current_interim_rate_cents"], 900000, "current_interim_rate_cents"
    )
    assert provider["approved_interim_period_count"] == 0


def test_a_fresh_cost_report_reads_back_its_zeroed_derived_figures(api):
    """A newly opened report reads DRAFT / NOT_STARTED / NOT_RUN with a
    2026-11-30 deadline and every derived figure still at zero.

    PRD 3.1: "At creation the server stamps `status` to `DRAFT`, `wage_data_status` to `NOT_STARTED`, `allocation_status` to `NOT_RUN`, and computes the `filing_deadline`."

    PRD 3.1: "All the derived cost and full-time-equivalent figures start at zero: `total_direct_cost_cents`, `unmapped_tb_total_cents`, `total_allowable_cost_cents` and `allowable_cost_per_discharge_cents` at 0, `cost_to_charge_ratio` at 0.000000, `unweighted_fte_days_total` at 0.0000, `unweighted_fte_total`, `capped_unweighted_fte`, `weighted_fte_total` and `rolling_average_fte` at 0.00, `amendment_count` at 0, and `filed_at` at null."

    Design: Corner/entities/cost_report_retrieval_returns_stored_and_derived_fields
    """
    scenario = new_scenario(api)

    report = read_cost_report(api, scenario)

    assert_cost_report(report)
    assert report["provider_id"] == scenario["provider_id"]
    assert report["fiscal_year_begin"] == "2025-07-01"
    assert report["fiscal_year_end"] == "2026-06-30"
    assert report["status"] == "DRAFT"
    assert report["wage_data_status"] == "NOT_STARTED"
    assert report["allocation_status"] == "NOT_RUN"
    assert report["filing_deadline"] == "2026-11-30"
    assert_money_equals(report["total_direct_cost_cents"], 0, "total_direct_cost_cents")
    assert_money_equals(report["unmapped_tb_total_cents"], 0, "unmapped_tb_total_cents")
    assert_money_equals(
        report["total_allowable_cost_cents"], 0, "total_allowable_cost_cents"
    )
    assert_money_equals(
        report["allowable_cost_per_discharge_cents"],
        0,
        "allowable_cost_per_discharge_cents",
    )
    assert report["cost_to_charge_ratio"] == 0.000000
    assert report["amendment_count"] == 0
    assert report["filed_at"] is None


def test_cost_report_listing_reports_the_prewindow_count_and_has_more(api):
    """With two reports under one provider a one-row window reports total_count 2
    and has_more true, and the second window closes it out.

    PRD 2.3: "The response envelope's `meta` object carries `limit`, `offset`, `total_count` (the number of rows matching the filter before the window is applied) and `has_more` (whether rows remain beyond the current window)."

    Design: Corner/entities/cost_report_listing_is_paginated_with_total_count_and_has_more
    """
    scenario = new_scenario(api)
    create_cost_report(
        api,
        scenario["provider_id"],
        fiscal_year_begin="2024-07-01",
        fiscal_year_end="2025-06-30",
    )

    first_page, first_meta = validate_paginated(
        api.list_cost_reports(
            scenario["manager"],
            {"provider_id": scenario["provider_id"], "limit": 1, "offset": 0},
        )
    )
    assert len(first_page) == 1
    assert first_meta["limit"] == 1
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 2
    assert first_meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api.list_cost_reports(
            scenario["manager"],
            {"provider_id": scenario["provider_id"], "limit": 1, "offset": 1},
        )
    )
    assert len(second_page) == 1
    assert second_meta["offset"] == 1
    assert second_meta["total_count"] == 2
    assert second_meta["has_more"] is False
    assert second_page[0]["id"] != first_page[0]["id"]


def test_reading_an_unknown_cost_center_uses_the_cost_center_code(api):
    """A cost center identifier that resolves to nothing answers with the
    per-entity 404 for cost centers.

    PRD 2.10: "The per-entity 404 codes are `ERR_PROVIDER_NOT_FOUND`, `ERR_COST_REPORT_NOT_FOUND`, `ERR_COST_CENTER_NOT_FOUND`, `ERR_TRIAL_BALANCE_LINE_NOT_FOUND`, `ERR_WORKPAPER_ENTRY_NOT_FOUND`, `ERR_STEPDOWN_RUN_NOT_FOUND`, `ERR_WAGE_INDEX_SUBMISSION_NOT_FOUND`, `ERR_OCC_MIX_RESPONSE_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`, `ERR_ROTATION_ASSIGNMENT_NOT_FOUND`, `ERR_UCC_DATA_SET_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_AUDIT_ADJUSTMENT_NOT_FOUND`, `ERR_APPEAL_CASE_NOT_FOUND` and `ERR_INTERIM_RATE_REQUEST_NOT_FOUND`."

    Design: Corner/entities/get_cost_center_with_unknown_id_returns_not_found
    """
    scenario = new_scenario(api)
    add_cost_center(api, scenario, "cc_routine", CENTER_ROUTINE)

    response = api.get_cost_center(NON_EXISTENT_UUID, scenario["analyst"])

    validate_error(response, ApiErrorId.ERR_COST_CENTER_NOT_FOUND.value, 404)


def test_a_cost_center_missing_its_worksheet_code_is_a_schema_failure(api):
    """Omitting the required `code` is refused at the schema band and no cost
    center row appears under the report.

    PRD 2.10: "**Schema** — the payload parses, every required input field is present, and every field satisfies its declared type, enum membership, numeric range and decimal-place constraint, else `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/cost_center_without_code_is_rejected
    """
    scenario = new_scenario(api)
    payload = cost_center_payload(statistics={"SQUARE_FEET": 3000})
    payload.pop("code")

    response = api.create_cost_center(
        scenario["report_id"], payload, scenario["analyst"]
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    centers, meta = validate_paginated(
        api.list_report_cost_centers(scenario["report_id"], scenario["analyst"])
    )
    assert meta["total_count"] == 0
    assert centers == []


def test_a_resident_registered_without_an_irp_status_is_within_irp(api):
    """The optional initial-residency-period flag defaults to WITHIN_IRP and the
    resident starts with no assigned FTE days.

    PRD 3.6: "A `ReimbursementAnalyst` registers a **Resident** under a provider identified by `provider_id`, supplying `full_name` and the approved GME `program` name, plus an optional `irp_status` of `WITHIN_IRP` or `BEYOND_IRP` defaulting to `WITHIN_IRP`."

    Design: Corner/entities/resident_irp_status_defaults_to_within_irp
    """
    scenario = new_scenario(api)
    payload = resident_payload(full_name="Dana Ito")
    assert "irp_status" not in payload

    resident = validate_success(
        api.create_resident(scenario["provider_id"], payload, scenario["analyst"]), 201
    )

    assert_resident(resident)
    assert resident["provider_id"] == scenario["provider_id"]
    assert resident["full_name"] == "Dana Ito"
    assert resident["irp_status"] == "WITHIN_IRP"
    assert resident["assigned_fte_days"] == 0.0000
    assert resident["program"] == "Internal Medicine"


def test_direct_cost_is_the_sum_over_that_centers_mapped_ledger_lines(api):
    """Two mapped lines of 100000000 and 200000000 aggregate to 300000000 on the
    receiving center with nothing spilling into the later waterfall columns.

    PRD 3.3: "For each cost center of the report, `direct_cost_cents` becomes the sum of `amount_cents` over the report's trial balance lines whose `mapped_cost_center_id` is that center and whose `status` is `MAPPED`."

    Design: Corner/entities/cost_center_direct_cost_cents_is_computed_from_mapped_ledger_lines
    """
    scenario = new_scenario(api)
    add_cost_center(
        api, scenario, "cc_routine", {**CENTER_ROUTINE, "statistics": {"SQUARE_FEET": 3000}}
    )
    add_mapped_tb_line(api, scenario, "6200", "Nursing salaries", 100000000, "cc_routine")

    add_mapped_tb_line(api, scenario, "6250", "Nursing supplies", 200000000, "cc_routine")

    center = read_cost_center(api, scenario, scenario["cc_routine"])
    assert_cost_center(center)
    assert_money_equals(center["direct_cost_cents"], 300000000, "direct_cost_cents")
    assert_money_equals(
        center["reclassified_amount_cents"], 0, "reclassified_amount_cents"
    )
    assert_money_equals(center["adjustment_amount_cents"], 0, "adjustment_amount_cents")
    assert_money_equals(
        center["post_reclass_direct_cost_cents"],
        300000000,
        "post_reclass_direct_cost_cents",
    )
    assert_money_equals(
        center["post_adjustment_cost_cents"], 300000000, "post_adjustment_cost_cents"
    )

    report = read_cost_report(api, scenario)
    assert_money_equals(
        report["total_direct_cost_cents"], 300000000, "total_direct_cost_cents"
    )
    assert_money_equals(report["unmapped_tb_total_cents"], 0, "unmapped_tb_total_cents")


def test_client_supplied_identity_and_version_fields_are_discarded(api):
    """A registration body carrying its own id, timestamps and version has all
    four ignored in favour of server-minted values.

    PRD 2.4: "**`id`** (string): a server-minted UUID. It carries no type prefix and is never supplied by the client."

    PRD 2.4: "**`version`** (integer): a monotonically increasing counter that begins at 1 and increments by one on every mutation of the row."

    Design: Corner/entities/provider_system_fields_are_server_generated_with_client_input_ignored
    """
    set_clock(api)

    provider = validate_success(
        api.create_provider(
            provider_payload(
                id="11111111-1111-1111-1111-111111111111",
                created_at="1999-01-01T00:00:00Z",
                updated_at="1999-01-01T00:00:00Z",
                version=99,
            ),
            SYSTEM_ADMIN_HEADERS,
        ),
        201,
    )

    assert_provider(provider)
    assert provider["id"] != "11111111-1111-1111-1111-111111111111"
    assert provider["created_at"] != "1999-01-01T00:00:00Z"
    assert provider["updated_at"] != "1999-01-01T00:00:00Z"
    assert provider["version"] != 99
    assert provider["version"] == 1
    assert provider["ccn"] == "450123"


def test_a_center_type_outside_the_declared_four_is_rejected(api):
    """OVERHEAD is not one of the four worksheet A center types, so the creation
    is refused and the report keeps no centers.

    PRD 3.2: "A center is created with a worksheet line `code` (exactly five characters, digits only, and unique within the report — a reused code is rejected with `ERR_COST_CENTER_CODE_DUPLICATE`), a human-readable `name`, and a `center_type` of `GENERAL_SERVICE`, `ANCILLARY`, `ROUTINE` or `NONREIMBURSABLE`."

    Design: Corner/entities/cost_center_center_type_outside_enum_is_rejected
    """
    scenario = new_scenario(api)

    response = api.create_cost_center(
        scenario["report_id"],
        cost_center_payload(
            center_type="OVERHEAD", statistics={"SQUARE_FEET": 3000}
        ),
        scenario["analyst"],
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    centers, meta = validate_paginated(
        api.list_report_cost_centers(scenario["report_id"], scenario["analyst"])
    )
    assert meta["total_count"] == 0
    assert centers == []


def test_a_child_under_an_unknown_parent_report_fails_on_the_parent(api):
    """The leading path identifier decides the 404, so a well-formed cost center
    body under a nonexistent report never gets inspected.

    PRD 2.10: "When a path contains more than one identifier, identifiers are resolved strictly left to right, and the first one that does not resolve decides the 404."

    Design: Corner/entities/cost_center_under_unknown_cost_report_returns_not_found
    """
    new_scenario(api)

    response = api.create_cost_center(
        UNKNOWN_COST_REPORT_ID,
        cost_center_payload(statistics={"SQUARE_FEET": 3000}),
        ANALYST_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_COST_REPORT_NOT_FOUND.value, 404)


def test_a_rotation_site_owned_by_another_provider_is_refused(api):
    """The rotation site exists, but it hangs off a second hospital's report, so
    the assignment is rejected on ownership and nothing is counted.

    PRD 3.6: "The rotation site's cost center must belong to a cost report of the *resident's own* provider, else `ERR_COST_CENTER_FOREIGN_TO_PROVIDER`."

    Design: Corner/entities/rotation_assignment_to_a_foreign_providers_cost_center_is_rejected
    """
    scenario = new_scenario(api)
    resident = validate_success(
        api.create_resident(
            scenario["provider_id"],
            resident_payload(full_name="Dana Ito", irp_status="WITHIN_IRP"),
            scenario["analyst"],
        ),
        201,
    )

    other_provider = create_other_provider(api)
    other_report = create_cost_report(api, other_provider["id"])
    other_headers = role_headers_for(other_provider["id"])
    foreign_center = validate_success(
        api.create_cost_center(
            other_report["id"],
            cost_center_payload(statistics={"SQUARE_FEET": 3000}),
            other_headers["analyst"],
        ),
        201,
    )

    response = api.create_rotation_assignment(
        resident["id"],
        rotation_assignment_payload(foreign_center["id"]),
        scenario["analyst"],
    )

    validate_error(response, ApiErrorId.ERR_COST_CENTER_FOREIGN_TO_PROVIDER.value, 422)

    reread_resident = validate_success(
        api.get_resident(resident["id"], scenario["analyst"])
    )
    assert reread_resident["assigned_fte_days"] == 0.0000

    reread_other_report = validate_success(
        api.get_cost_report(other_report["id"], other_headers["manager"])
    )
    assert reread_other_report["unweighted_fte_days_total"] == 0.0000
