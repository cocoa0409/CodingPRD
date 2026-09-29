"""Facility defaults and derived aggregates, plus the reference-data create-time refusals."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, factories, ApiErrorId,
    setup_base, create_priced_item, item_lifecycle, read_facility, set_clock,
    assert_facility, assert_facility_aggregate_invariants,
    NON_EXISTENT_UUID, ADMIN, ANALYST, APPROVER, APPROVER_USER_ID,
)


def test_a_minimal_facility_payload_materialises_every_declared_default():
    """PRD §3.1: "`rounding_mode` defaults to `NEAREST_DOLLAR` and may instead be `NEAREST_CENT`
    or `PSYCHOLOGICAL_99`; it controls the final rounding step of every gross-charge computation.
    `aggregate_markup_limit_bp` defaults to 40000 basis points — a facility-wide ceiling of four
    times cost. `volume_growth_bp` defaults to 10500 basis points, a projected annual volume
    growth of five percent, and is consulted only by the forward-projected impact variant.
    `impact_lookback_days` defaults to 90 days and is consulted only by the historical-replay
    impact variant. `duplicate_detection_mode` defaults to `STRICT_CODE` and may instead be
    `FUZZY_DESCRIPTION`; it selects which duplicate-scoring variant the cleanup workflow applies."
    PRD §3.1: "A newly created facility has `version` 1, all aggregates at 0,
    `chargemaster_posture` of `OPEN` and `transparency_status` of `NEEDS_REFRESH`;
    `published_transparency_file_id` is null."

    Design: Corner/entities/facility_defaults_applied_when_optional_configuration_omitted
    """
    set_clock("2026-09-01T00:00:00Z")
    facility = validate_success(
        api_client.create_facility(
            {"name": "Bare Config Hospital", "cms_certification_number": "CCN-0009"}, ADMIN
        ),
        201,
    )
    assert_facility(facility)
    assert facility["rounding_mode"] == "NEAREST_DOLLAR"
    assert facility["aggregate_markup_limit_bp"] == 40000
    assert facility["volume_growth_bp"] == 10500
    assert facility["impact_lookback_days"] == 90
    assert facility["duplicate_detection_mode"] == "STRICT_CODE"
    assert facility["chargemaster_posture"] == "OPEN"
    assert facility["transparency_status"] == "NEEDS_REFRESH"
    assert facility["active_item_count"] == 0
    assert facility["aggregate_gross_charge_cents"] == 0
    assert facility["aggregate_cost_basis_cents"] == 0
    assert facility["aggregate_markup_ratio_bp"] == 0
    assert facility["stale_price_item_count"] == 0
    assert facility["published_transparency_file_id"] is None
    assert facility["version"] == 1


def test_the_four_aggregates_are_derived_from_the_single_activated_item():
    """PRD §3.3: "On success `lifecycle_status` becomes `ACTIVE`; the facility's
    `active_item_count` increases by 1, its `aggregate_gross_charge_cents` increases by the item's
    `gross_charge_cents`, its `aggregate_cost_basis_cents` increases by the item's
    `cost_basis_cents`, `aggregate_markup_ratio_bp` is recomputed, `transparency_status` is set to
    `NEEDS_REFRESH`, `chargemaster_posture` is re-derived, and `Facility.version` advances by 1."
    PRD §2.11: "Aggregates in this system are always derived from persisted rows, never from
    projections."
    PRD §3.3: "On success `lifecycle_status` becomes `APPROVED` and `approved_by_user_id` records
    the approving `X-User-ID`."

    Design: Corner/entities/facility_computed_aggregates_reconcile_after_first_activation
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(
        facility_overrides={
            "name": "Mercy General", "cms_certification_number": "CCN-2193-MERCY",
            "rounding_mode": "NEAREST_CENT",
        },
        revenue_code_overrides={
            "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
            "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
            "pricing_class": "PROCEDURE", "status": "ACTIVE",
        },
        department_overrides={"name": "Cardiac Cath Lab", "cost_center_code": "CC-4100"},
        price_rule_overrides={"effective_from": "2026-01-01T00:00:00Z"},
    )
    item = create_priced_item(
        base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
        code_type="CPT", code_value="93458", cost_basis_cents=100000,
        medicare_rate_cents=50000, market_p75_cents=900000,
        effective_from="2026-09-01T00:00:00Z",
    )
    assert item["gross_charge_cents"] == 240000
    item_lifecycle(item["id"], "SUBMIT_FOR_REVIEW", ANALYST)
    approved = item_lifecycle(item["id"], "APPROVE", APPROVER)
    assert approved["approved_by_user_id"] == APPROVER_USER_ID

    activated = item_lifecycle(item["id"], "ACTIVATE", APPROVER)
    assert activated["lifecycle_status"] == "ACTIVE"

    facility = read_facility(base["facility"]["id"])
    assert facility["active_item_count"] == 1
    assert facility["aggregate_gross_charge_cents"] == 240000
    assert facility["aggregate_cost_basis_cents"] == 100000
    assert facility["aggregate_markup_ratio_bp"] == 24000, "240000 * 10000 / 100000"
    assert facility["stale_price_item_count"] == 0
    assert facility["transparency_status"] == "NEEDS_REFRESH"
    assert facility["chargemaster_posture"] == "OPEN"
    assert_facility_aggregate_invariants(facility)


def test_a_revenue_code_without_a_pricing_class_is_refused_and_never_persisted():
    """PRD §3.1: "Each `RevenueCode` row carries a four-digit UB-04 `code` string that is globally
    unique (for example `'0300'`), a human-readable `description`, a boolean `requires_hcpcs`, an
    `allowed_code_types` array drawn from the four values `CPT`, `HCPCS`, `REV_ONLY` and
    `CDM_INTERNAL`, a `pricing_class` of `SUPPLY`, `PHARMACY`, `PROCEDURE` or `ROOM_AND_BOARD`
    that forms part of the scope key used when selecting a price rule, and a `status` that
    defaults to `ACTIVE` and may be `RETIRED`."
    PRD §2.9: "11. Payload schema conformance — `ERR_VALIDATION` (422). This covers required
    fields being present, enum members being legal"

    Design: Corner/entities/revenue_code_creation_missing_required_pricing_class_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    validate_error(
        api_client.create_revenue_code(
            {
                "code": "0301", "description": "Lab Chemistry",
                "requires_hcpcs": False, "allowed_code_types": ["CPT"],
            },
            ADMIN,
        ),
        ApiErrorId.ERR_VALIDATION.value,
        422,
    )

    rows, _meta = validate_paginated(api_client.list_revenue_codes(ADMIN, params={"limit": 100}))
    assert "0301" not in [row["code"] for row in rows], (
        "the refused revenue code was never persisted"
    )


def test_a_department_body_facility_id_that_resolves_to_nothing_is_a_facility_not_found():
    """PRD §2.9: "4. `facility_id`, wherever it appears in a path or body, resolves to a
    `Facility` — `ERR_FACILITY_NOT_FOUND` (404)."
    PRD §2.9: "10. Body foreign keys resolve, checked left to right in this declaration order:
    `department_id`, then `revenue_code_id` or `proposed_revenue_code_id`, then `charge_item_id`,
    then `companion_required_item_id`, then `duplicate_of_item_id`, then
    `recovery_captured_charge_id` — `ERR_REFERENCED_RESOURCE_NOT_FOUND` (404)."
    PRD §3.1: "Departments sit under a facility. Each is created with `facility_id`, a `name` such
    as "Cardiac Cath Lab", a `cost_center_code` unique within the facility, the `manager_user_id`
    of the `DepartmentManager` entitled to act for it, and an optional
    `allowed_revenue_code_values` array of four-digit revenue-code strings."

    Design: Corner/entities/department_creation_with_unknown_facility_id_not_found
    """
    set_clock("2026-09-01T00:00:00Z")
    real_facility = validate_success(
        api_client.create_facility(factories.create_facility_payload(name="Mercy General"), ADMIN),
        201,
    )
    resp = api_client.create_department(
        {
            "facility_id": NON_EXISTENT_UUID, "name": "Orphan Dept",
            "cost_center_code": "CC-999", "manager_user_id": "mgr_orphan",
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_FACILITY_NOT_FOUND.value, 404)
    assert (resp.json().get("data") or {}).get("error_id") != (
        ApiErrorId.ERR_REFERENCED_RESOURCE_NOT_FOUND.value
    ), "facility_id has its own rank-4 code ahead of the rank-10 generic body-FK rule"

    rows, meta = validate_paginated(
        api_client.list_departments(ADMIN, params={"facility_id": real_facility["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []
