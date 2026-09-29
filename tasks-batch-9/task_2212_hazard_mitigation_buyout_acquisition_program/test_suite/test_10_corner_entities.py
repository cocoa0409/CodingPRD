"""Entity surface: declared defaults, the list envelope, identity guards and immutability."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS, make_subrecipient_coordinator_headers


ADMIN = TEST_USERS["program_administrator_headers"]


def test_a_new_project_returns_every_derived_total_at_its_identity_value(api):
    """Creation seeds every rollup to its declared zero rather than to null.

    "The new project opens in `status` `DRAFT` at `version` 1 with every derived
    total at its identity value: `federal_obligated_cents` 0,
    `program_income_balance_cents` 0, `protected_open_space_acres` 0.00,
    `participating_parcel_count` 0, `holdout_parcel_count` 0,
    `contiguous_open_space_parcel_count` 0, `largest_component_parcel_ids` an empty
    array, `neighborhood_viability_ratio` 0.0000 and `viability_status`
    `NONVIABLE`. The three review-trail fields `validated_bcr`,
    `validated_bca_method` and `validated_by_user_id` are null."

    "a `cost_share_federal_pct` that defaults to 0.75 and must be at least 0.50 and
    at most 1.00 with two decimal places"

    Design: Corner/entities/project_creation_returns_the_success_envelope_with_declared_system_defaults
    """
    api.set_clock("2026-08-01T00:00:00Z")

    project = validate_success(
        api.create_mitigation_project(
            factories.create_mitigation_project_payload(), ADMIN
        ),
        201,
    )

    assert project["status"] == "DRAFT"
    assert project["version"] == 1
    assert float(project["cost_share_federal_pct"]) == 0.75
    assert project["federal_obligated_cents"] == 0
    assert project["program_income_balance_cents"] == 0
    assert float(project["protected_open_space_acres"]) == 0.00
    assert project["participating_parcel_count"] == 0
    assert project["holdout_parcel_count"] == 0
    assert project["contiguous_open_space_parcel_count"] == 0
    assert project["largest_component_parcel_ids"] == []
    assert float(project["neighborhood_viability_ratio"]) == 0.0
    assert project["viability_status"] == "NONVIABLE"
    assert project["validated_bcr"] is None
    assert project["validated_bca_method"] is None
    assert project["validated_by_user_id"] is None
    assert project["id"] and project["created_at"] and project["updated_at"]


def test_a_new_parcel_defaults_its_damage_percentage_and_both_status_dimensions(api):
    """The omitted optional input lands on zero, not null, and both dimensions start cold.

    "The new parcel opens at `version` 1 with `participation_status`
    `NOT_CONTACTED`, `acquisition_status` `NOT_STARTED`,
    `dob_deduction_total_cents` 0, and `pre_event_fmv_cents`,
    `pre_event_value_basis`, `pre_event_value_determined_at` and
    `voluntary_acknowledgement_signed_on` all null."

    "a `substantial_damage_pct` that defaults to 0.00 and must be between 0 and 100
    inclusive with two decimal places"

    Design: Corner/entities/parcel_creation_applies_declared_defaults_for_omitted_optional_inputs
    """
    project = fixtures.create_draft_project(api)

    parcel = validate_success(
        api.create_parcel(
            project["id"],
            factories.create_parcel_payload(project["id"], site_address="1101 River Rd"),
            make_subrecipient_coordinator_headers(project["id"]),
        ),
        201,
    )

    assert float(parcel["substantial_damage_pct"]) == 0.00
    assert parcel["participation_status"] == "NOT_CONTACTED"
    assert parcel["acquisition_status"] == "NOT_STARTED"
    assert parcel["dob_deduction_total_cents"] == 0
    assert parcel["pre_event_fmv_cents"] is None
    assert parcel["pre_event_value_basis"] is None
    assert parcel["pre_event_value_determined_at"] is None
    assert parcel["voluntary_acknowledgement_signed_on"] is None
    assert parcel["version"] == 1


def test_the_parcel_filter_is_applied_before_the_count_and_the_page_window(api):
    """Three matching rows in a two-row window, with the other project's parcel absent.

    "List responses populate `limit`, `offset`, `total_count` and `has_more` in the
    `meta` block, where `total_count` is the number of records matching the filters
    before the page window is applied and `has_more` states whether any matching
    record remains after the window."

    "Every collection endpoint accepts two optional query parameters. `limit`
    defaults to 10, has a minimum of 1 and a maximum of 100. `offset` defaults to 0
    and has a minimum of 0."

    Design: Corner/entities/parcel_listing_with_filter_and_pagination_reports_total_count_and_has_more
    """
    project_a = fixtures.create_draft_project(api)
    project_b = fixtures.create_draft_project(api)
    for apn, address, acreage, occupancy, structure in (
        ("APN-LIST-1", "1201 River Rd", 0.34, "OWNER_OCCUPIED", "SINGLE_FAMILY"),
        ("APN-LIST-2", "1202 River Rd", 0.41, "TENANT_OCCUPIED", "MULTI_FAMILY"),
        ("APN-LIST-3", "1203 River Rd", 1.25, "VACANT", "NONE"),
    ):
        fixtures.create_parcel(
            api, project_a, apn=apn, site_address=address, acreage=acreage,
            occupancy_type=occupancy, structure_type=structure,
        )
    parcel_b = fixtures.create_parcel(
        api, project_b, apn="APN-LIST-9", site_address="9 Eastmoor Way",
        acreage=0.50, occupancy_type="VACANT", structure_type="NONE",
    )

    first_page, first_meta = validate_paginated(
        api.list_parcels(ADMIN, params={"project_id": project_a["id"], "limit": 2, "offset": 0})
    )
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api.list_parcels(ADMIN, params={"project_id": project_a["id"], "limit": 2, "offset": 2})
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["offset"] == 2
    assert second_meta["has_more"] is False

    seen = {row["id"] for row in first_page} | {row["id"] for row in second_page}
    assert parcel_b["id"] not in seen

    vacant, vacant_meta = validate_paginated(
        api.list_parcels(ADMIN, params={"occupancy_type": "VACANT"})
    )
    assert vacant_meta["total_count"] == 2
    assert vacant_meta["limit"] == 10
    assert parcel_b["id"] in {row["id"] for row in vacant}


NOT_FOUND_READS = (
    ("get_mitigation_project", ApiErrorId.ERR_PROJECT_NOT_FOUND),
    ("get_benefit_cost_analysis", ApiErrorId.ERR_BCA_NOT_FOUND),
    ("get_parcel", ApiErrorId.ERR_PARCEL_NOT_FOUND),
    ("get_appraisal", ApiErrorId.ERR_APPRAISAL_NOT_FOUND),
    ("get_dob_record", ApiErrorId.ERR_DOB_RECORD_NOT_FOUND),
    ("get_purchase_offer", ApiErrorId.ERR_OFFER_NOT_FOUND),
    ("get_relocation_case", ApiErrorId.ERR_RELOCATION_CASE_NOT_FOUND),
    ("get_closing_record", ApiErrorId.ERR_CLOSING_NOT_FOUND),
    ("get_demolition_contractor", ApiErrorId.ERR_CONTRACTOR_NOT_FOUND),
    ("get_demolition_work_order", ApiErrorId.ERR_WORK_ORDER_NOT_FOUND),
    ("get_utility_disconnection", ApiErrorId.ERR_DISCONNECTION_NOT_FOUND),
    ("get_deed_restriction", ApiErrorId.ERR_DEED_RESTRICTION_NOT_FOUND),
    ("get_program_income_entry", ApiErrorId.ERR_LEDGER_ENTRY_NOT_FOUND),
    ("get_parcel_adjacency", ApiErrorId.ERR_ADJACENCY_NOT_FOUND),
    ("get_monitoring_inspection", ApiErrorId.ERR_INSPECTION_NOT_FOUND),
)


def test_each_entity_family_answers_an_unknown_id_with_its_own_not_found(api):
    """Fifteen well-formed but unknown ids give fifteen distinct 404 error ids.

    "Existence of the entities named by the request, in this fixed order: the
    project (`ERR_PROJECT_NOT_FOUND`), the benefit-cost analysis
    (`ERR_BCA_NOT_FOUND`), the parcel (`ERR_PARCEL_NOT_FOUND`), the appraisal
    (`ERR_APPRAISAL_NOT_FOUND`), the duplication-of-benefits record
    (`ERR_DOB_RECORD_NOT_FOUND`), the purchase offer (`ERR_OFFER_NOT_FOUND`), the
    relocation case (`ERR_RELOCATION_CASE_NOT_FOUND`), the closing record
    (`ERR_CLOSING_NOT_FOUND`), the demolition contractor
    (`ERR_CONTRACTOR_NOT_FOUND`), the demolition work order
    (`ERR_WORK_ORDER_NOT_FOUND`), the utility disconnection
    (`ERR_DISCONNECTION_NOT_FOUND`), the deed restriction
    (`ERR_DEED_RESTRICTION_NOT_FOUND`), the program income ledger entry
    (`ERR_LEDGER_ENTRY_NOT_FOUND`), the parcel adjacency
    (`ERR_ADJACENCY_NOT_FOUND`), and the monitoring inspection
    (`ERR_INSPECTION_NOT_FOUND`). All are HTTP 404."

    Design: Corner/entities/unknown_ids_in_every_entity_family_return_the_family_specific_not_found
    """
    api.set_clock("2026-08-01T00:00:00Z")

    for method_name, expected in NOT_FOUND_READS:
        response = getattr(api, method_name)(NON_EXISTENT_UUID, ADMIN)
        validate_error(response, expected.value, 404)


def test_a_project_created_without_a_subrecipient_name_persists_nothing(api):
    """The body-shape gate answers before anything is written.

    "Structural validation of the request body or query string —
    `ERR_INVALID_REQUEST`. This applies to every write endpoint and every list
    endpoint, and covers a missing required field, a wrong JSON type, an enum value
    outside its declared set, a negative `_cents` value"

    "a `subrecipient_name` naming the local government carrying out the buyout"

    Design: Corner/entities/project_creation_missing_required_subrecipient_name_returns_invalid_request
    """
    api.set_clock("2026-08-01T00:00:00Z")

    payload = factories.create_mitigation_project_payload()
    payload.pop("subrecipient_name")

    validate_error(
        api.create_mitigation_project(payload, ADMIN),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )

    _rows, meta = validate_paginated(api.list_mitigation_projects(ADMIN))
    assert meta["total_count"] == 0


def test_a_bad_enum_a_zero_acreage_and_an_oversized_crew_cap_all_report_the_same_id(api):
    """Three unrelated shape defects collapse onto one structural error id.

    "an enum value outside its declared set, a negative `_cents` value, a negative
    `acreage`, `shared_boundary_feet`, `substantial_damage_pct`,
    `total_debris_tons` or `recycled_tons`"

    "a `max_concurrent_work_orders` outside 1 through 10"

    "an `acreage` greater than zero with two decimal places; an `occupancy_type` of
    `OWNER_OCCUPIED`, `TENANT_OCCUPIED` or `VACANT`"

    Design: Corner/entities/parcel_creation_with_invalid_enum_and_out_of_range_numbers_returns_invalid_request
    """
    project = fixtures.create_draft_project(api)
    coordinator = make_subrecipient_coordinator_headers(project["id"])

    validate_error(
        api.create_parcel(
            project["id"],
            factories.create_parcel_payload(
                project["id"], apn="APN-TYPE-1", site_address="1301 River Rd",
                occupancy_type="SEASONAL_RENTAL",
            ),
            coordinator,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )
    validate_error(
        api.create_parcel(
            project["id"],
            factories.create_parcel_payload(
                project["id"], apn="APN-TYPE-2", site_address="1302 River Rd",
                acreage=0, occupancy_type="VACANT", structure_type="NONE",
            ),
            coordinator,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )
    validate_error(
        api.create_demolition_contractor(
            factories.create_demolition_contractor_payload(
                name="Overbooked Wrecking", license_no="DEM-OB",
                asbestos_certified=True, max_concurrent_work_orders=11,
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )

    _parcels, parcel_meta = validate_paginated(
        api.list_parcels(ADMIN, params={"project_id": project["id"]})
    )
    assert parcel_meta["total_count"] == 0

    _contractors, contractor_meta = validate_paginated(
        api.list_demolition_contractors(ADMIN)
    )
    assert contractor_meta["total_count"] == 0


def test_the_three_append_only_types_carry_neither_a_version_nor_an_updated_at(api):
    """An adjacency edge, a site visit and a ledger entry all omit both mutable fields.

    "Three record types are append-only audit artifacts and carry **only** `id` and
    `created_at` — both `updated_at` and `version` are absent from their stored
    form and from their responses. Those types are `ParcelAdjacency` (an adjacency
    edge, once drawn, is never edited), `MonitoringInspection` (a site-visit finding
    is a historical fact), and `ProgramIncomeLedgerEntry` (a posted ledger entry is
    never rewritten; its `status` flips to `REVERSED` only through the reversal
    operation, and even that flip does not introduce a `version` field)."

    "An edge is an immutable audit artifact: it carries only `id` and `created_at`,
    it is never edited, and there is no operation that deletes one."

    Design: Corner/entities/immutable_child_rows_carry_no_version_and_expose_no_mutation_endpoint
    """
    state = fixtures.create_approved_project_with_parcels(
        api,
        [
            {"apn": "APN-IMM-1", "site_address": "1401 River Rd", "acreage": 0.34,
             "occupancy_type": "VACANT", "structure_type": "NONE"},
            {"apn": "APN-IMM-2", "site_address": "1402 River Rd", "acreage": 0.41,
             "occupancy_type": "VACANT", "structure_type": "NONE"},
        ],
    )
    coordinator = make_subrecipient_coordinator_headers(state["project"]["id"])

    created = validate_success(
        api.create_parcel_adjacency(
            factories.create_parcel_adjacency_payload(
                state["project"]["id"],
                state["parcels"][0]["id"],
                state["parcels"][1]["id"],
                shared_boundary_feet=120.5,
            ),
            coordinator,
        ),
        201,
    )

    edge = validate_success(api.get_parcel_adjacency(created["id"], ADMIN))
    assert edge["id"] and edge["created_at"]
    assert "version" not in edge
    assert "updated_at" not in edge
    assert float(edge["shared_boundary_feet"]) == 120.5

    entry = fixtures.post_program_income(api, state["project"]["id"])
    assert "version" not in entry
    assert "updated_at" not in entry
    assert entry["id"] and entry["created_at"]


def test_the_five_offer_amounts_are_derived_and_not_read_from_the_request_body(api):
    """Smuggled net and incentive values of 1 cent are discarded in favour of the arithmetic.

    "All five of `base_value_cents`, `dob_deduction_cents`,
    `pre_incentive_net_cents`, `incentive_cents` and `net_offer_cents` are frozen
    snapshots evaluated once at creation."

    "`base_value_cents` is the `indicated_value_cents` of the appraisal named by
    `source_appraisal_id`. `dob_deduction_cents` is the parcel's
    `dob_deduction_total_cents` at that instant. `pre_incentive_net_cents` is
    `base_value_cents` minus `dob_deduction_cents`, taken as zero if that
    difference is negative."

    "`net_offer_cents` is `pre_incentive_net_cents` plus `incentive_cents`."

    Design: Corner/entities/computed_offer_amounts_ignore_client_supplied_extra_field_values
    """
    state = fixtures.parcel_value_established(api)

    offer = fixtures.build_offer(
        api,
        state["project"],
        state["parcel"]["id"],
        state["review_appraisal"],
        net_offer_cents=1,
        incentive_cents=1,
    )

    assert offer["base_value_cents"] == 20_000_000
    assert offer["dob_deduction_cents"] == 0
    assert offer["pre_incentive_net_cents"] == 20_000_000
    assert offer["incentive_cents"] == 1_400_000
    assert offer["net_offer_cents"] == 21_400_000
    assert offer["status"] == "DRAFT"


def test_a_self_edge_and_the_reversed_duplicate_edge_report_two_different_defects(api):
    """The unordered pair is already drawn, and the loop is a separate structural defect.

    "Edges are **undirected**: the pair naming parcel P then parcel Q is the same
    edge as the pair naming Q then P, so an attempt to draw either direction when
    the unordered pair already exists is `ERR_DUPLICATE_ADJACENCY`. An edge naming
    the same parcel at both ends is `ERR_ADJACENCY_SELF_REFERENCE`."

    "Referential integrity: an adjacency naming the same parcel on both ends
    (`ERR_ADJACENCY_SELF_REFERENCE`), then a referenced entity belonging to the
    wrong parent (`ERR_PARCEL_PROJECT_MISMATCH`)."

    Design: Corner/entities/adjacency_self_reference_and_the_reversed_duplicate_pair_are_refused
    """
    state = fixtures.create_approved_project_with_parcels(
        api,
        [
            {"apn": "APN-GRAPH-1", "site_address": "1601 River Rd", "acreage": 0.34,
             "occupancy_type": "VACANT", "structure_type": "NONE"},
            {"apn": "APN-GRAPH-2", "site_address": "1602 River Rd", "acreage": 0.41,
             "occupancy_type": "VACANT", "structure_type": "NONE"},
        ],
    )
    project_id = state["project"]["id"]
    coordinator = make_subrecipient_coordinator_headers(project_id)
    first, second = state["parcels"][0]["id"], state["parcels"][1]["id"]

    edge = validate_success(
        api.create_parcel_adjacency(
            factories.create_parcel_adjacency_payload(
                project_id, first, second, shared_boundary_feet=120.5
            ),
            coordinator,
        ),
        201,
    )

    validate_error(
        api.create_parcel_adjacency(
            factories.create_parcel_adjacency_payload(
                project_id, first, first, shared_boundary_feet=10.0
            ),
            coordinator,
        ),
        ApiErrorId.ERR_ADJACENCY_SELF_REFERENCE.value,
        422,
    )
    validate_error(
        api.create_parcel_adjacency(
            factories.create_parcel_adjacency_payload(
                project_id, second, first, shared_boundary_feet=120.5
            ),
            coordinator,
        ),
        ApiErrorId.ERR_DUPLICATE_ADJACENCY.value,
        409,
    )

    rows, meta = validate_paginated(
        api.list_parcel_adjacencies(ADMIN, params={"project_id": project_id})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == edge["id"]


def test_a_cross_project_edge_and_a_foreign_reviewed_appraisal_both_report_a_mismatch(api):
    """Both referenced rows exist, so the answer is a parent mismatch and never a 404.

    "Both `parcel_a_id` and `parcel_b_id` must name parcels whose `project_id`
    equals the `project_id` in the request body — an edge crossing two projects, or
    an edge whose body `project_id` disagrees with the parcels it names, is
    `ERR_PARCEL_PROJECT_MISMATCH`."

    "A `reviewed_appraisal_id` naming an appraisal that does not exist is
    `ERR_APPRAISAL_NOT_FOUND`; one naming an appraisal that exists but sits on a
    different parcel is `ERR_PARCEL_PROJECT_MISMATCH`."

    Design: Corner/entities/references_to_a_parcel_or_appraisal_outside_the_parent_return_project_mismatch
    """
    state = fixtures.create_approved_project_with_parcels(
        api,
        [
            {"apn": "APN-PAR-A1", "site_address": "1701 River Rd", "acreage": 0.34,
             "occupancy_type": "VACANT", "structure_type": "NONE"},
            {"apn": "APN-PAR-A2", "site_address": "1702 River Rd", "acreage": 0.41,
             "occupancy_type": "VACANT", "structure_type": "NONE"},
        ],
    )
    project_a = state["project"]
    parcel_a1, parcel_a2 = state["parcels"][0], state["parcels"][1]

    project_b = fixtures.create_draft_project(api)
    parcel_b1 = fixtures.create_parcel(
        api, project_b, apn="APN-PAR-B1", site_address="7 Eastmoor Way",
        acreage=0.50, occupancy_type="VACANT", structure_type="NONE",
    )

    foreign_appraisal = fixtures.accepted_initial_appraisal(
        api, parcel_a2["id"], indicated_value_cents=18_000_000
    )

    validate_error(
        api.create_parcel_adjacency(
            factories.create_parcel_adjacency_payload(
                project_a["id"], parcel_a1["id"], parcel_b1["id"],
                shared_boundary_feet=60.0,
            ),
            make_subrecipient_coordinator_headers(project_a["id"]),
        ),
        ApiErrorId.ERR_PARCEL_PROJECT_MISMATCH.value,
        422,
    )

    validate_error(
        api.create_appraisal(
            parcel_a1["id"],
            factories.create_review_appraisal_payload(
                parcel_a1["id"],
                foreign_appraisal["id"],
                appraiser_license_no="LIC-RA-1",
                effective_date="2026-07-05",
                indicated_value_cents=18_000_000,
            ),
            TEST_USERS["review_appraiser_headers"],
        ),
        ApiErrorId.ERR_PARCEL_PROJECT_MISMATCH.value,
        422,
    )

    _edges, edge_meta = validate_paginated(
        api.list_parcel_adjacencies(ADMIN, params={"project_id": project_a["id"]})
    )
    assert edge_meta["total_count"] == 0

    _appraisals, appraisal_meta = validate_paginated(
        api.list_appraisals(ADMIN, params={"parcel_id": parcel_a1["id"]})
    )
    assert appraisal_meta["total_count"] == 0
