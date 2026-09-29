"""Endpoint surface and the error catalogue.

Covers the published endpoint behaviours of PRD §4 — the status code and empty
body of the single delete, the computed capacity-summary read of PRD §3.1, the
filtered and paginated list contract of PRD §2.3, the cross-reference that
execution stamps onto equipment lines in PRD §3.7 and the terminal rejection
disposition of PRD §3.5 — together with the resource-specific 404 codes and
resolution order of PRD §2.5 and the state-gate rejections of PRD §5.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_AMENDMENT_NOT_FOUND,
    ERR_ANALYSIS_NOT_FOUND,
    ERR_APPLICATION_NOT_FOUND,
    ERR_AUDIT_NOT_FOUND,
    ERR_COST_SHARE_NOT_FOUND,
    ERR_EQUIPMENT_LINE_NOT_FOUND,
    ERR_FINDING_NOT_FOUND,
    ERR_GROUND_LEASE_NOT_FOUND,
    ERR_GROUND_SPACE_UNAVAILABLE,
    ERR_INVALID_ANALYSIS_STATE,
    ERR_INVALID_COST_SHARE_STATE,
    ERR_INVALID_LEASE_STATE,
    ERR_INVALID_PROJECT_STATE,
    ERR_LANDLORD_NOT_FOUND,
    ERR_MLA_NOT_FOUND,
    ERR_PROJECT_NOT_FOUND,
    ERR_TENANT_NOT_FOUND,
    ERR_TOWER_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_amendment_axes,
    assert_analysis_outcome,
    assert_capacity_summary,
    assert_cents,
    assert_list_meta,
    assert_load_units,
    assert_tenant_ledger,
    assert_tower_capacity,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    ENGINEER_HEADERS,
)

# ─────────────────────────────────────────────────────────────────────────────
# Shared setup shapes
# ─────────────────────────────────────────────────────────────────────────────

# A single antenna line whose PRD §3.4 load ladder gives it exactly 500 load
# units: five units of 100 lbs with no wind area, mounted at 80 ft, so the
# elevation multiplier is 1.00 and (100 + 30 * 0) * 5 * 1.00 = 500.000.
_LINE_500_UNITS = {
    "equipment_type": "ANTENNA",
    "model_code": "AX-100",
    "quantity": 5,
    "unit_weight_lbs": 100,
    "wind_area_sqft": 0,
    "mount_elevation_ft": 80,
}

# A single antenna line worth exactly 60 load units: one unit of 60 lbs with no
# wind area at 80 ft, i.e. (60 + 30 * 0) * 1 * 1.00 = 60.000.
_LINE_60_UNITS = {
    "equipment_type": "ANTENNA",
    "model_code": "AX-60",
    "quantity": 1,
    "unit_weight_lbs": 60,
    "wind_area_sqft": 0,
    "mount_elevation_ft": 80,
}

_MLA_TERMS = {
    "base_monthly_rent_cents": 200000,
    "escalator_pct": 3.0,
    "initial_term_years": 10,
    "renewal_terms_count": 1,
    "expires_on": "2036-07-31",
}

_BAND_100_140 = {
    "requested_elevation_bottom_ft": 100,
    "requested_elevation_top_ft": 140,
    "requested_ground_space_sqft": 300,
}

_BAND_200_240 = {
    "requested_elevation_bottom_ft": 200,
    "requested_elevation_top_ft": 240,
    "requested_ground_space_sqft": 300,
}


def _quoted_project_on_near_capacity_tower(api, *, site_name, legal_name, carrier_code):
    """A PROPOSED reinforcement project behind a MODIFICATION_REQUIRED analysis.

    The tower is rated 1,000 load units with 900 already reserved as baseline, so
    per PRD §2.8 its ``reserved_load_pct`` of exactly 90.000 leaves the posture
    ``OPEN`` and a 60-unit application lands the analysis at 96.000 percent,
    which PRD §3.5 reads as ``MODIFICATION_REQUIRED`` and therefore quotable.
    """
    chain = fixtures.build_colocation_chain(
        api,
        stage="REVIEWED",
        with_ground_lease=False,
        tower_overrides={
            "site_name": site_name,
            "structure_type": "SELF_SUPPORT",
            "rated_capacity_load_units": 1000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 9000,
            "baseline_reserved_load_units": 900,
        },
        tenant_overrides={"legal_name": legal_name, "carrier_code": carrier_code},
        mla_overrides=dict(_MLA_TERMS),
        application_overrides=dict(_BAND_100_140),
        lines=[dict(_LINE_60_UNITS)],
        variant="PRELIMINARY",
    )
    assert_analysis_outcome(
        chain["analysis"],
        included_load_units=960.0,
        projected_loading_pct=96.000,
        result="MODIFICATION_REQUIRED",
        status="ISSUED",
    )
    quoted = fixtures.quoted_analysis_with_project(
        api,
        tower_id=chain["tower"]["id"],
        analysis_id=chain["analysis"]["id"],
        cost_cents=1_000_000,
        project_overrides={
            "construction_window_start_date": "2026-09-01",
            "construction_window_end_date": "2026-10-31",
            "allocation_basis": "PRO_RATA_LOAD",
        },
    )
    chain["analysis"] = quoted["analysis"]
    chain["project"] = quoted["project"]
    return chain


# ─────────────────────────────────────────────────────────────────────────────
# The published endpoint surface
# ─────────────────────────────────────────────────────────────────────────────


def test_removing_an_equipment_line_answers_no_content_and_reprices_the_schedule(api):
    """PRD §4: "The single delete operation returns `204 No Content` with no response body."

    PRD §3.4 adds that "Deletion returns no body and immediately recomputes the
    application's `total_load_units` from the surviving lines; the sibling lines'
    own `load_units` are unchanged." The deleted row is gone rather than hidden,
    so the filtered listing shrinks and reading it again is a 404 from the
    catalogue of PRD §2.5.

    Design: Corner/endpoints/standard_crud_delete_equipment_line_returns_204
    """
    tower = fixtures.new_tower(
        api,
        site_name="Delete Line Dell",
        structure_type="MONOPOLE",
        rated_capacity_load_units=9000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=300,
        ground_space_total_sqft=9000,
    )
    carrier = fixtures.carrier_with_active_lease(
        api,
        tenant_overrides={"legal_name": "Delete Line Electric", "carrier_code": "DLE"},
        mla_overrides=dict(_MLA_TERMS),
    )
    tenant, mla = carrier["tenant"], carrier["mla"]
    tenant_headers = carrier["tenant_headers"]
    application = fixtures.new_application(
        api,
        tower["id"],
        mla["id"],
        tenant["id"],
        requested_elevation_bottom_ft=80,
        requested_elevation_top_ft=140,
        requested_ground_space_sqft=300,
    )

    kept = fixtures.add_equipment_line(
        api,
        application["id"],
        tenant["id"],
        equipment_type="ANTENNA",
        model_code="DL-100",
        quantity=5,
        unit_weight_lbs=100,
        wind_area_sqft=0,
        mount_elevation_ft=80,
    )
    removed = fixtures.add_equipment_line(
        api,
        application["id"],
        tenant["id"],
        equipment_type="TMA",
        model_code="DL-50",
        quantity=1,
        unit_weight_lbs=50,
        wind_area_sqft=0,
        mount_elevation_ft=100,
    )
    # The 100 ft mount sits in the middle tier of the PRD §3.4 ladder: 50 * 1.25.
    assert_load_units(kept["load_units"], 500.0, "load_units")
    assert_load_units(removed["load_units"], 62.5, "load_units")

    deleted = api.delete_equipment_line(removed["id"], tenant_headers)
    assert deleted.status_code == 204, f"expected 204, got {deleted.status_code}"
    assert not deleted.content, f"204 must carry no response body, got {deleted.content!r}"

    rows, meta = validate_paginated(
        api.list_equipment_lines({"colocation_application_id": application["id"]}, ADMIN_HEADERS)
    )
    assert_list_meta(meta, total_count=1, has_more=False)
    assert [row["id"] for row in rows] == [kept["id"]]
    assert_load_units(rows[0]["load_units"], 500.0, "load_units")

    validate_error(
        api.get_equipment_line(removed["id"], ADMIN_HEADERS), ERR_EQUIPMENT_LINE_NOT_FOUND, 404
    )

    reread = fixtures.read_application(api, application["id"])
    assert_load_units(reread["total_load_units"], 500.0, "total_load_units")


def test_execution_stamps_the_installed_amendment_onto_every_equipment_line(api):
    """PRD §3.7: "Every equipment line of the amendment's application has its `installed_amendment_id` set to this amendment's identifier."

    PRD §3.4 says the same field "is null while the line is unbuilt and is set
    later when the line is carried onto an executed amendment", so the
    ``installed_amendment_id`` filter of the equipment-line listing answers
    nothing while the amendment is still `DRAFT` and answers the line only once
    the amendment reaches `EXECUTED`.

    Design: Corner/endpoints/cross_reference_link_equipment_lines_to_installed_amendment
    """
    chain = fixtures.build_colocation_chain(
        api,
        stage="PAPERED",
        tower_overrides={
            "site_name": "Cross Ref Ridge",
            "structure_type": "MONOPOLE",
            "rated_capacity_load_units": 9000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 9000,
        },
        landlord_overrides={
            "legal_name": "Cross Ref Land",
            "remit_contact_email": "ap@crossref.example",
            "w9_on_file": True,
        },
        lease_overrides={
            "base_monthly_rent_cents": 300000,
            "escalator_pct": 2.0,
            "commencement_date": "2020-06-01",
            "term_end_date": "2031-05-31",
            "renewal_option_count": 1,
            "renewal_term_years": 5,
            "buyout_price_cents": 9000000,
        },
        tenant_overrides={"legal_name": "Cross Ref Radio", "carrier_code": "XRF"},
        mla_overrides=dict(_MLA_TERMS),
        application_overrides=dict(_BAND_100_140),
        lines=[dict(_LINE_500_UNITS)],
        variant="PRELIMINARY",
    )
    amendment, line = chain["amendment"], chain["lines"][0]
    assert_amendment_axes(amendment, execution_status="DRAFT", billing_status="NOT_BILLING")

    rows, meta = validate_paginated(
        api.list_equipment_lines({"installed_amendment_id": amendment["id"]}, ADMIN_HEADERS)
    )
    assert_list_meta(meta, total_count=0, has_more=False)
    assert rows == [], "a DRAFT amendment has installed no equipment yet"

    executed = validate_success(
        api.execute_site_amendment(
            amendment["id"], factories.execute_payload(True), ADMIN_HEADERS
        ),
        200,
    )
    assert_amendment_axes(executed, execution_status="EXECUTED", billing_status="BILLING")
    assert_load_units(executed["reserved_load_units"], 500.0, "reserved_load_units")

    rows, meta = validate_paginated(
        api.list_equipment_lines({"installed_amendment_id": amendment["id"]}, ADMIN_HEADERS)
    )
    assert_list_meta(meta, total_count=1, has_more=False)
    assert [row["id"] for row in rows] == [line["id"]]
    assert_load_units(rows[0]["load_units"], 500.0, "load_units")
    assert rows[0]["installed_amendment_id"] == amendment["id"]

    assert (
        fixtures.read_equipment_line(api, line["id"])["installed_amendment_id"] == amendment["id"]
    )


def test_capacity_summary_reports_every_derived_counter_of_the_tower(api):
    """PRD §3.1: "There is also a dedicated computed read — a capacity summary for one tower — whose response is not a stored entity but an object with nine members: `tower_id`, `rated_capacity_load_units`, `reserved_load_units`, `reserved_load_pct`, `available_ground_space_sqft`, `capacity_posture`, `open_review_count`, `occupied_band_count` (the number of entries in `occupied_elevation_bands`) and `capacity_hold_application_count` (the number of applications on the tower currently sitting in `CAPACITY_HOLD`)."

    With one executed amendment holding 500 load units and 300 sqft on a tower
    rated 9,000 with 9,000 sqft of compound, the reconciliation of PRD §2.7 gives
    a reserved percentage of 5.556 and 8,700 sqft still available, while a second
    carrier's application under review contributes the only open review slot.

    Design: Corner/endpoints/computed_read_capacity_summary_reports_all_derived_counters
    """
    site = fixtures.site_with_ground_lease(
        api,
        tower_overrides={
            "site_name": "Capacity Summary Mesa",
            "structure_type": "MONOPOLE",
            "rated_capacity_load_units": 9000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 9000,
        },
        landlord_overrides={
            "legal_name": "Summary Mesa Land",
            "remit_contact_email": "ap@summarymesa.example",
            "w9_on_file": True,
        },
        lease_overrides={
            "base_monthly_rent_cents": 300000,
            "escalator_pct": 2.0,
            "commencement_date": "2020-06-01",
            "term_end_date": "2031-05-31",
            "renewal_option_count": 1,
            "renewal_term_years": 5,
            "buyout_price_cents": 9000000,
        },
    )
    tower = site["tower"]

    occupant = fixtures.add_carrier_to_site(
        api,
        site,
        stage="EXECUTED",
        tenant_overrides={"legal_name": "Summary Alpha", "carrier_code": "CSA"},
        mla_overrides=dict(_MLA_TERMS),
        application_overrides=dict(_BAND_100_140),
        lines=[dict(_LINE_500_UNITS)],
        variant="PRELIMINARY",
    )
    assert_amendment_axes(occupant["amendment"], execution_status="EXECUTED")

    reviewer = fixtures.add_carrier_to_site(
        api,
        site,
        stage="SUBMITTED",
        tenant_overrides={"legal_name": "Summary Bravo", "carrier_code": "CSB"},
        mla_overrides=dict(_MLA_TERMS),
        application_overrides=dict(_BAND_200_240),
        lines=[dict(_LINE_500_UNITS)],
    )
    assert reviewer["application"]["status"] == "UNDER_STRUCTURAL_REVIEW"

    summary = validate_success(
        api.get_capacity_summary(tower["id"], reviewer["tenant_headers"]), 200
    )
    assert summary["tower_id"] == tower["id"]
    assert_capacity_summary(
        summary,
        rated_capacity_load_units=9000,
        reserved_load_units=500.0,
        reserved_load_pct=5.556,
        available_ground_space_sqft=8700,
        capacity_posture="OPEN",
        open_review_count=1,
        occupied_band_count=1,
        capacity_hold_application_count=0,
    )


def test_application_listing_filters_by_status_and_pages_in_creation_order(api):
    """PRD §2.3: "Unless a specific endpoint states otherwise, list endpoints return their items sorted by `created_at` ascending."

    PRD §2.3 also requires that "Every list response includes `limit`, `offset`,
    `total_count` and `has_more` in the `meta` object of the envelope", so the
    status filter narrows `total_count` to the two applications actually under
    review and a `limit` of 1 walks them in creation order with `has_more`
    flipping to false on the last page.

    Design: Corner/endpoints/listing_applications_filters_by_status_with_stable_pagination
    """
    tower = fixtures.new_tower(
        api,
        site_name="List Filter Flat",
        structure_type="MONOPOLE",
        rated_capacity_load_units=9000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=300,
        ground_space_total_sqft=9000,
    )
    carrier = fixtures.carrier_with_active_lease(
        api,
        tenant_overrides={"legal_name": "List Filter Telecom", "carrier_code": "LST"},
        mla_overrides=dict(_MLA_TERMS),
    )
    tenant, mla = carrier["tenant"], carrier["mla"]

    bands = ((100, 140, "LF-100A"), (200, 240, "LF-100B"), (260, 290, "LF-100C"))
    applications = []
    for bottom, top, model_code in bands:
        application = fixtures.new_application(
            api,
            tower["id"],
            mla["id"],
            tenant["id"],
            requested_elevation_bottom_ft=bottom,
            requested_elevation_top_ft=top,
            requested_ground_space_sqft=100,
        )
        applications.append(application)
        if model_code != "LF-100C":
            fixtures.add_equipment_line(
                api,
                application["id"],
                tenant["id"],
                equipment_type="ANTENNA",
                model_code=model_code,
                quantity=1,
                unit_weight_lbs=100,
                wind_area_sqft=0,
                mount_elevation_ft=80,
            )
            fixtures.submit_application(api, application["id"], tenant["id"])

    first_page, meta = validate_paginated(
        api.list_colocation_applications(
            {
                "tower_id": tower["id"],
                "status": "UNDER_STRUCTURAL_REVIEW",
                "limit": 1,
                "offset": 0,
            },
            ADMIN_HEADERS,
        )
    )
    assert_list_meta(meta, limit=1, offset=0, total_count=2, has_more=True)
    assert [row["id"] for row in first_page] == [applications[0]["id"]]

    second_page, meta = validate_paginated(
        api.list_colocation_applications(
            {
                "tower_id": tower["id"],
                "status": "UNDER_STRUCTURAL_REVIEW",
                "limit": 1,
                "offset": 1,
            },
            ADMIN_HEADERS,
        )
    )
    assert_list_meta(meta, limit=1, offset=1, total_count=2, has_more=False)
    assert [row["id"] for row in second_page] == [applications[1]["id"]]

    drafts, meta = validate_paginated(
        api.list_colocation_applications(
            {"tower_id": tower["id"], "status": "DRAFT"}, ADMIN_HEADERS
        )
    )
    assert_list_meta(meta, total_count=1, has_more=False)
    assert [row["id"] for row in drafts] == [applications[2]["id"]]


def test_rejecting_an_application_under_review_frees_the_review_slot(api):
    """PRD §3.5: "Rejection by a `PortfolioAdmin` carries a `rejection_reason` and is available as `UNDER_STRUCTURAL_REVIEW → REJECTED` or `MODIFICATION_REQUIRED → REJECTED` with no further preconditions; when the application was in review, the tower's `open_review_count` is decremented by one, and when it was in `MODIFICATION_REQUIRED` no counter changes."

    A rejected application never reserved structure, so PRD §2.7 leaves
    `reserved_load_units` at the baseline and the posture ladder of PRD §2.8
    keeps the tower `OPEN` while the review slot returns to zero.

    Design: Corner/endpoints/action_endpoint_reject_application_records_reason_and_frees_review
    """
    chain = fixtures.build_colocation_chain(
        api,
        stage="SUBMITTED",
        with_ground_lease=False,
        tower_overrides={
            "site_name": "Reject Reason Ridge",
            "structure_type": "MONOPOLE",
            "rated_capacity_load_units": 9000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 9000,
        },
        tenant_overrides={"legal_name": "Reject Reason Radio", "carrier_code": "RJA"},
        mla_overrides=dict(_MLA_TERMS),
        application_overrides=dict(_BAND_100_140),
        lines=[dict(_LINE_500_UNITS)],
    )
    tower, application = chain["tower"], chain["application"]
    assert application["status"] == "UNDER_STRUCTURAL_REVIEW"

    rejected = validate_success(
        api.reject_colocation_application(
            application["id"],
            factories.reject_payload("Band already committed to a pending swap"),
            ADMIN_HEADERS,
        ),
        200,
    )
    assert rejected["status"] == "REJECTED"
    assert_load_units(rejected["total_load_units"], 500.0, "total_load_units")

    summary = fixtures.read_capacity_summary(api, tower["id"])
    assert_capacity_summary(
        summary,
        reserved_load_units=0.0,
        open_review_count=0,
        occupied_band_count=0,
        capacity_posture="OPEN",
    )


# ─────────────────────────────────────────────────────────────────────────────
# The error catalogue
# ─────────────────────────────────────────────────────────────────────────────


def test_unknown_body_foreign_keys_answer_their_own_404_in_declaration_order(api):
    """PRD §2.5: "A request that names both an unknown tower and an unknown landlord surfaces the tower error, because `tower_id` is listed first."

    PRD §2.5 also fixes the codes themselves: foreign keys "supplied in a request
    body are resolved after the path but before any business rule, and they are
    resolved in the order the fields are listed for that endpoint in §4's request
    contract", each answering with the 404 belonging to its own resource type.

    Design: Corner/errors/body_foreign_key_not_found_codes_rejected
    """
    tower = fixtures.new_tower(
        api,
        site_name="Foreign Key Fell",
        structure_type="MONOPOLE",
        rated_capacity_load_units=9000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=300,
        ground_space_total_sqft=9000,
    )
    tenant = fixtures.new_tenant(api, legal_name="Foreign Key Radio", carrier_code="FKR")
    tenant_headers = fixtures.make_tenant_headers(tenant["id"])

    lease_terms = {
        "base_monthly_rent_cents": 300000,
        "escalator_pct": 2.0,
        "commencement_date": "2020-06-01",
        "term_end_date": "2031-05-31",
        "renewal_option_count": 1,
        "renewal_term_years": 5,
        "buyout_price_cents": 9000000,
    }

    cases = [
        (
            lambda: api.create_ground_lease(
                factories.ground_lease_payload(tower["id"], NON_EXISTENT_UUID, **lease_terms),
                ADMIN_HEADERS,
            ),
            ERR_LANDLORD_NOT_FOUND,
        ),
        (
            lambda: api.create_ground_lease(
                factories.ground_lease_payload(
                    NON_EXISTENT_UUID, NON_EXISTENT_UUID, **lease_terms
                ),
                ADMIN_HEADERS,
            ),
            ERR_TOWER_NOT_FOUND,
        ),
        (
            lambda: api.create_master_lease_agreement(
                factories.master_lease_agreement_payload(NON_EXISTENT_UUID, **_MLA_TERMS),
                ADMIN_HEADERS,
            ),
            ERR_TENANT_NOT_FOUND,
        ),
        (
            lambda: api.create_colocation_application(
                factories.colocation_application_payload(
                    tower["id"], NON_EXISTENT_UUID, **_BAND_100_140
                ),
                tenant_headers,
            ),
            ERR_MLA_NOT_FOUND,
        ),
        (
            lambda: api.create_landlord_payment(
                factories.landlord_payment_payload(
                    NON_EXISTENT_UUID, "2026-04-01", "2026-04-30"
                ),
                ADMIN_HEADERS,
            ),
            ERR_GROUND_LEASE_NOT_FOUND,
        ),
        (
            lambda: api.create_structural_analysis(
                factories.structural_analysis_payload(NON_EXISTENT_UUID, 1, "PRELIMINARY"),
                ENGINEER_HEADERS,
            ),
            ERR_APPLICATION_NOT_FOUND,
        ),
        (
            lambda: api.create_modification_project(
                factories.modification_project_payload(
                    tower["id"],
                    NON_EXISTENT_UUID,
                    construction_window_start_date="2026-09-01",
                    construction_window_end_date="2026-10-31",
                    allocation_basis="PRO_RATA_LOAD",
                ),
                ENGINEER_HEADERS,
            ),
            ERR_ANALYSIS_NOT_FOUND,
        ),
    ]

    for call, expected_error in cases:
        validate_error(call(), expected_error, 404)


def test_unknown_path_resources_answer_their_own_404_left_to_right(api):
    """PRD §2.5: "A finding recorded under a non-existent audit fails with `ERR_AUDIT_NOT_FOUND` before the system considers anything about the finding itself."

    PRD §2.5 opens by requiring that when a path carries identifiers "the system
    resolves them strictly left to right and rejects on the first one that does
    not exist, with the 404 code belonging to that resource type", so each
    published path answers with its own resource-specific code rather than one
    generic not-found.

    Design: Corner/errors/path_resource_not_found_codes_rejected
    """
    cases = [
        (
            lambda: api.get_equipment_line(NON_EXISTENT_UUID, ADMIN_HEADERS),
            ERR_EQUIPMENT_LINE_NOT_FOUND,
        ),
        (
            lambda: api.get_site_amendment(NON_EXISTENT_UUID, ADMIN_HEADERS),
            ERR_AMENDMENT_NOT_FOUND,
        ),
        (
            lambda: api.get_modification_project(NON_EXISTENT_UUID, ADMIN_HEADERS),
            ERR_PROJECT_NOT_FOUND,
        ),
        (
            lambda: api.get_cost_share(NON_EXISTENT_UUID, ADMIN_HEADERS),
            ERR_COST_SHARE_NOT_FOUND,
        ),
        (
            lambda: api.get_audit_finding(NON_EXISTENT_UUID, AUDITOR_HEADERS),
            ERR_FINDING_NOT_FOUND,
        ),
        (
            lambda: api.create_audit_finding(
                NON_EXISTENT_UUID,
                factories.audit_finding_payload(
                    NON_EXISTENT_UUID,
                    description="Ghost cabinet",
                    observed_load_units=10,
                    installed_on_date="2026-07-01",
                    mount_elevation_ft=100,
                ),
                AUDITOR_HEADERS,
            ),
            ERR_AUDIT_NOT_FOUND,
        ),
        (lambda: api.get_tenant(NON_EXISTENT_UUID, ADMIN_HEADERS), ERR_TENANT_NOT_FOUND),
        (
            lambda: api.activate_master_lease_agreement(NON_EXISTENT_UUID, {}, ADMIN_HEADERS),
            ERR_MLA_NOT_FOUND,
        ),
        (
            lambda: api.get_ground_lease(NON_EXISTENT_UUID, ADMIN_HEADERS),
            ERR_GROUND_LEASE_NOT_FOUND,
        ),
        (
            lambda: api.get_capacity_summary(NON_EXISTENT_UUID, ADMIN_HEADERS),
            ERR_TOWER_NOT_FOUND,
        ),
        (
            lambda: api.issue_quotation(
                NON_EXISTENT_UUID, factories.quotation_payload(1000000), ENGINEER_HEADERS
            ),
            ERR_ANALYSIS_NOT_FOUND,
        ),
        (
            lambda: api.get_colocation_application(NON_EXISTENT_UUID, ADMIN_HEADERS),
            ERR_APPLICATION_NOT_FOUND,
        ),
    ]

    for call, expected_error in cases:
        validate_error(call(), expected_error, 404)


def test_a_second_quotation_on_an_already_quoted_analysis_is_refused(api):
    """PRD §3.5: "The quotation is only accepted on an analysis whose `status` is `ISSUED` and whose `result` is not `PASS`; otherwise the rejection is `ERR_INVALID_ANALYSIS_STATE`."

    Issuing the quotation "moves the analysis `ISSUED → QUOTED` and stamps
    `quoted_at` with the current logical clock instant", so the second attempt
    meets a `QUOTED` analysis and the originally quoted construction cost is left
    untouched rather than overwritten.

    Design: Corner/errors/second_quotation_on_quoted_analysis_rejected
    """
    chain = fixtures.build_colocation_chain(
        api,
        stage="REVIEWED",
        with_ground_lease=False,
        tower_overrides={
            "site_name": "Quote Twice Tor",
            "structure_type": "SELF_SUPPORT",
            "rated_capacity_load_units": 1000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 9000,
            "baseline_reserved_load_units": 900,
        },
        tenant_overrides={"legal_name": "Quote Twice Telecom", "carrier_code": "QTA"},
        mla_overrides=dict(_MLA_TERMS),
        application_overrides=dict(_BAND_100_140),
        lines=[dict(_LINE_60_UNITS)],
        variant="PRELIMINARY",
    )
    application, analysis = chain["application"], chain["analysis"]
    assert_analysis_outcome(
        analysis,
        included_load_units=960.0,
        projected_loading_pct=96.000,
        result="MODIFICATION_REQUIRED",
        status="ISSUED",
    )
    quoted = fixtures.quote_analysis(api, analysis["id"], 1_000_000)
    assert_analysis_outcome(quoted, status="QUOTED")

    validate_error(
        api.issue_quotation(
            analysis["id"], factories.quotation_payload(2_000_000), ENGINEER_HEADERS
        ),
        ERR_INVALID_ANALYSIS_STATE,
        409,
    )

    stored = fixtures.read_analysis(api, application["id"], analysis["id"])
    assert_analysis_outcome(stored, status="QUOTED", result="MODIFICATION_REQUIRED")
    assert_cents(
        stored["modification_construction_cost_cents"],
        1_000_000,
        "modification_construction_cost_cents",
    )
    # The clock has never been advanced, so it still stands at the PRD §2.4 cold
    # start of 2026-08-01T00:00:00Z where the first quotation was stamped.
    assert str(stored["quoted_at"]).startswith(
        "2026-08-01T00:00:00"
    ), f"quoted_at must record the first quotation instant, got {stored['quoted_at']!r}"


def test_exercising_a_renewal_on_an_active_lease_is_refused(api):
    """PRD §3.2: "Exercising the renewal then moves the lease `RENEWAL_NEGOTIATION → ACTIVE`, and again requires an unconsumed option."

    The transition is declared only out of `RENEWAL_NEGOTIATION`, and PRD §2.6
    evaluates that state gate at priority 10, ahead of the renewal-window and
    option-count gates at priorities 24 and 25, so an `ACTIVE` lease is refused
    with `ERR_INVALID_LEASE_STATE` and its term is not pushed out.

    Design: Corner/errors/renew_before_open_renewal_rejected
    """
    site = fixtures.site_with_ground_lease(
        api,
        tower_overrides={
            "site_name": "Renew Before Open",
            "structure_type": "MONOPOLE",
            "rated_capacity_load_units": 9000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 9000,
        },
        landlord_overrides={
            "legal_name": "Before Open Land",
            "remit_contact_email": "ap@beforeopen.example",
            "w9_on_file": True,
        },
        lease_overrides={
            "base_monthly_rent_cents": 300000,
            "escalator_pct": 2.0,
            "commencement_date": "2020-06-01",
            "term_end_date": "2031-05-31",
            "renewal_option_count": 1,
            "renewal_term_years": 5,
            "buyout_price_cents": 9000000,
        },
    )
    lease = site["ground_lease"]
    assert lease["status"] == "ACTIVE"

    validate_error(
        api.renew_ground_lease(lease["id"], {}, ADMIN_HEADERS), ERR_INVALID_LEASE_STATE, 409
    )

    reread = fixtures.read_ground_lease(api, lease["id"])
    assert reread["status"] == "ACTIVE"
    assert reread["renewals_exercised"] == 0
    assert str(reread["term_end_date"]).startswith(
        "2031-05-31"
    ), f"term_end_date must be untouched, got {reread['term_end_date']!r}"


def test_starting_construction_on_an_unfunded_project_is_refused(api):
    """PRD §3.6: "Starting construction moves the project `FUNDED → IN_CONSTRUCTION` and requires that the logical clock date has reached `construction_window_start_date`, that is, the clock date is at or after the window start."

    A project whose shares were never allocated is still `PROPOSED`, so PRD §2.6
    stops the request at its priority-10 state gate with
    `ERR_INVALID_PROJECT_STATE`; `allocated_cents` stays 0 and, because PRD §2.8
    freezes a tower only for a `FUNDED` or `IN_CONSTRUCTION` project, the posture
    stays `OPEN`.

    Design: Corner/errors/start_construction_on_proposed_project_rejected
    """
    chain = _quoted_project_on_near_capacity_tower(
        api,
        site_name="Start Construction Scarp",
        legal_name="Start Construction Cellular",
        carrier_code="SCP",
    )
    tower, project = chain["tower"], chain["project"]
    assert project["status"] == "PROPOSED"

    validate_error(
        api.start_construction(project["id"], {}, ENGINEER_HEADERS),
        ERR_INVALID_PROJECT_STATE,
        409,
    )

    reread = fixtures.read_project(api, project["id"])
    assert reread["status"] == "PROPOSED"
    assert_cents(reread["allocated_cents"], 0, "allocated_cents")

    tower_after = fixtures.read_tower(api, tower["id"])
    assert_tower_capacity(
        tower_after,
        reserved_load_units=900.0,
        reserved_load_pct=90.000,
        capacity_posture="OPEN",
    )


def test_accepting_an_already_billed_cost_share_a_second_time_is_refused(api):
    """PRD §3.6: "A carrier accepting its own share — permitted only while the share is `PENDING` and the parent project is `COST_ALLOCATED`, otherwise `ERR_INVALID_COST_SHARE_STATE` — moves the share `PENDING → ACCEPTED` and stamps `accepted_at` with the logical clock."

    The lone beneficiary's acceptance leaves no sibling `PENDING`, so the project
    joins `COST_ALLOCATED → FUNDED`, every `ACCEPTED` share moves to `BILLED`
    with the tenant's balance raised by its `share_cents`, and the tower's
    posture is recomputed to `FROZEN`. A repeat acceptance therefore meets a
    `BILLED` share and must not bill the 1,120,000-cent share twice.

    Design: Corner/errors/second_accept_on_billed_cost_share_rejected
    """
    chain = _quoted_project_on_near_capacity_tower(
        api,
        site_name="Accept Billed Bench",
        legal_name="Accept Billed Cellular",
        carrier_code="ACB",
    )
    tower, tenant, project = chain["tower"], chain["tenant"], chain["project"]

    fixtures.allocate_shares(api, project["id"])
    share = fixtures.share_for_tenant(api, project["id"], tenant["id"])
    # PRD §3.6 pipeline on a 1,000,000-cent quotation: a provisional 12 percent
    # fee of 120,000 puts the pre-discount total at 1,120,000, below the
    # 10,000,000-cent tier, so no discount applies and the total cost is
    # 1,000,000 + 120,000 = 1,120,000 carried by the single beneficiary.
    assert_cents(share["share_cents"], 1_120_000, "share_cents")
    fixtures.accept_share(api, share["id"], tenant["id"])

    validate_error(
        api.accept_cost_share(share["id"], {}, chain["tenant_headers"]),
        ERR_INVALID_COST_SHARE_STATE,
        409,
    )

    share_after = fixtures.read_cost_share(api, share["id"])
    assert share_after["status"] == "BILLED"
    assert_cents(share_after["share_cents"], 1_120_000, "share_cents")

    project_after = fixtures.read_project(api, project["id"])
    assert project_after["status"] == "FUNDED"
    assert_cents(project_after["allocated_cents"], 1_120_000, "allocated_cents")

    assert_tenant_ledger(
        fixtures.read_tenant(api, tenant["id"]),
        outstanding_balance_cents=1_120_000,
        credit_status="CURRENT",
    )
    assert_tower_capacity(fixtures.read_tower(api, tower["id"]), capacity_posture="FROZEN")


def test_second_execution_is_refused_when_the_compound_has_no_ground_space_left(api):
    """PRD §3.7: "**Ground space** is available when the tower's `available_ground_space_sqft` plus the superseded amendment's `ground_space_sqft` (zero when `supersedes_amendment_id` is null) is greater than or equal to this amendment's `ground_space_sqft`."

    The compound, not the structure, binds here: the first execution takes the
    tower's whole 300 sqft, so the second amendment — which clears the loading,
    clearance and band-separation gates of PRD §3.7 — is refused with
    `ERR_GROUND_SPACE_UNAVAILABLE` and stays in `DRAFT`, while PRD §2.8 leaves
    the tower `RESTRICTED` because `available_ground_space_sqft` of exactly 0 is
    itself restricting.

    Design: Corner/errors/ground_space_unavailable_on_second_execute_rejected
    """
    site = fixtures.site_with_ground_lease(
        api,
        tower_overrides={
            "site_name": "Ground Space Squeeze",
            "structure_type": "MONOPOLE",
            "rated_capacity_load_units": 9000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 300,
        },
        landlord_overrides={
            "legal_name": "Squeeze Land Trust",
            "remit_contact_email": "ap@squeezeland.example",
            "w9_on_file": True,
        },
        lease_overrides={
            "base_monthly_rent_cents": 300000,
            "escalator_pct": 2.0,
            "commencement_date": "2020-06-01",
            "term_end_date": "2031-05-31",
            "renewal_option_count": 1,
            "renewal_term_years": 5,
            "buyout_price_cents": 9000000,
        },
    )
    tower = site["tower"]

    first = fixtures.add_carrier_to_site(
        api,
        site,
        stage="APPROVED",
        tenant_overrides={"legal_name": "Squeeze Alpha", "carrier_code": "GSA"},
        mla_overrides=dict(_MLA_TERMS),
        application_overrides=dict(_BAND_100_140),
        lines=[dict(_LINE_500_UNITS)],
        variant="PRELIMINARY",
    )
    second = fixtures.add_carrier_to_site(
        api,
        site,
        stage="APPROVED",
        tenant_overrides={"legal_name": "Squeeze Bravo", "carrier_code": "GSB"},
        mla_overrides=dict(_MLA_TERMS),
        application_overrides=dict(_BAND_200_240),
        lines=[dict(_LINE_500_UNITS)],
        variant="PRELIMINARY",
    )

    amendment_terms = {
        "effective_date": "2026-08-01",
        "term_end_date": "2031-05-31",
        "base_monthly_rent_cents": 200000,
        "escalator_pct": 3.0,
    }
    first_amendment = fixtures.paper_amendment(
        api,
        first["mla"]["id"],
        tower["id"],
        first["application"]["id"],
        **amendment_terms,
    )
    second_amendment = fixtures.paper_amendment(
        api,
        second["mla"]["id"],
        tower["id"],
        second["application"]["id"],
        **amendment_terms,
    )
    fixtures.execute_amendment(api, first_amendment["id"], signature_received=True)

    validate_error(
        api.execute_site_amendment(
            second_amendment["id"], factories.execute_payload(True), ADMIN_HEADERS
        ),
        ERR_GROUND_SPACE_UNAVAILABLE,
        422,
    )

    assert_amendment_axes(
        fixtures.read_amendment(api, second_amendment["id"]),
        execution_status="DRAFT",
        billing_status="NOT_BILLING",
    )
    assert_amendment_axes(
        fixtures.read_amendment(api, first_amendment["id"]), execution_status="EXECUTED"
    )
    assert_tower_capacity(
        fixtures.read_tower(api, tower["id"]),
        reserved_ground_space_sqft=300,
        available_ground_space_sqft=0,
        reserved_load_units=500.0,
        reserved_load_pct=5.556,
        occupied_band_count=1,
        capacity_posture="RESTRICTED",
    )
