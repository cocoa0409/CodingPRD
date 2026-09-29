"""ChargeItem list pagination, the item-specific not-found code and the enum schema check."""
from test_helpers import (
    api_client, validate_error, validate_paginated, factories, ApiErrorId,
    setup_base, create_item, set_clock, NON_EXISTENT_UUID,
    ANALYST,
)


def _setup(revenue_code_overrides=None):
    set_clock("2026-09-01T00:00:00Z")
    return setup_base(
        facility_overrides={
            "name": "Mercy General", "cms_certification_number": "CCN-2193-MERCY",
            "rounding_mode": "NEAREST_CENT",
        },
        revenue_code_overrides=revenue_code_overrides or {
            "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
            "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
            "pricing_class": "PROCEDURE", "status": "ACTIVE",
        },
        department_overrides={
            "name": "Cardiac Cath Lab", "cost_center_code": "CC-4100",
            "allowed_revenue_code_values": [],
        },
    )


def test_the_listing_window_reports_total_count_and_has_more():
    """PRD §2.3: "Every list endpoint accepts two optional query parameters, `limit` and
    `offset`. The `limit` parameter defaults to 10 when omitted, may be no smaller than 1, and
    may be no larger than 100."
    PRD §2.3: "The four pagination fields — `limit`, `offset`, `total_count` and `has_more` —
    appear inside `meta` on list responses. `total_count` is the number of records matching the
    filters before pagination is applied, and `has_more` is true when records remain beyond the
    current window."
    PRD §2.3: "Unless a specific endpoint's narrative in §3 pins a different order, list results
    are sorted by `created_at` ascending."

    Design: Corner/entities/charge_item_listing_paginates_with_total_count_and_has_more
    """
    base = _setup()
    for cdm in ("CDM-1001", "CDM-1002", "CDM-1003"):
        create_item(base, cdm_number=cdm, code_type="CDM_INTERNAL", code_value=None,
                    effective_from="2026-09-01T00:00:00Z")

    first_page, meta = validate_paginated(
        api_client.list_charge_items(
            ANALYST, params={"facility_id": base["facility"]["id"], "limit": 2, "offset": 0}
        )
    )
    assert len(first_page) == 2
    assert meta["total_count"] == 3, "the count of matching rows before the window is applied"
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert [row["cdm_number"] for row in first_page] == ["CDM-1001", "CDM-1002"], (
        "the default order is created_at ascending"
    )

    second_page, meta = validate_paginated(
        api_client.list_charge_items(
            ANALYST, params={"facility_id": base["facility"]["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(second_page) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False, "nothing remains beyond this window"
    assert meta["offset"] == 2
    assert second_page[0]["cdm_number"] == "CDM-1003"


def test_an_unknown_charge_item_id_in_the_path_gets_the_item_specific_not_found_code():
    """PRD §2.9: "5. `charge_item_id` in the path resolves — `ERR_CHARGE_ITEM_NOT_FOUND` (404)."
    PRD §2.9: "9. `file_id` resolves to a `TransparencyFile`, `analysis_id` to a
    `PriceChangeImpactAnalysis`, `price_rule_id` to a `PriceRule`, `payer_contract_id` to a
    `PayerContract`, `department_id` to a `Department` and `revenue_code_id` to a `RevenueCode` —
    `ERR_GOVERNANCE_RESOURCE_NOT_FOUND` (404)."

    Design: Corner/entities/charge_item_path_id_not_found_returns_err_charge_item_not_found
    """
    _setup()
    resp = api_client.get_charge_item(NON_EXISTENT_UUID, ANALYST)
    validate_error(resp, ApiErrorId.ERR_CHARGE_ITEM_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"
    assert (resp.json().get("data") or {}).get("error_id") != (
        ApiErrorId.ERR_GOVERNANCE_RESOURCE_NOT_FOUND.value
    ), "charge items have their own rank-5 code, distinct from the rank-9 generic one"


def test_an_illegal_code_type_enum_member_fails_the_schema_check_first():
    """PRD §2.9: "11. Payload schema conformance — `ERR_VALIDATION` (422). This covers required
    fields being present, enum members being legal, integers being non-negative, `quantity` being
    at least 1, `justification` being at least 10 characters long, datetimes being well-formed ISO
    8601 UTC"
    PRD §2.9: "23–31. Business referential integrity, in this order:
    `ERR_REVENUE_CODE_MAPPING_INVALID` (422), `ERR_DEPARTMENT_REVENUE_CODE_NOT_ALLOWED` (422),"
    PRD §3.3: "a `code_type` of `CPT`, `HCPCS`, `REV_ONLY` or `CDM_INTERNAL`"

    Design: Corner/entities/charge_item_creation_invalid_enum_code_type_rejected
    """
    base = _setup(revenue_code_overrides={
        "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
        "allowed_code_types": ["CPT"], "pricing_class": "PROCEDURE", "status": "ACTIVE",
    })
    resp = api_client.create_charge_item(
        factories.create_charge_item_payload(
            base["facility"]["id"], base["department"]["id"], base["revenue_code"]["id"],
            cdm_number="CDM-3001", description="BAD ENUM ITEM", code_type="J_CODE",
            code_value=None, cost_basis_cents=4000, medicare_rate_cents=1000,
            market_p75_cents=90000, effective_from="2026-09-01T00:00:00Z",
        ),
        ANALYST,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)
    assert (resp.json().get("data") or {}).get("error_id") != (
        ApiErrorId.ERR_REVENUE_CODE_MAPPING_INVALID.value
    ), (
        "the revenue code allows only CPT, so the rank-23 mapping rule would also have fired; "
        "the rank-11 schema check must mask it"
    )

    rows, meta = validate_paginated(
        api_client.list_charge_items(
            ANALYST, params={"facility_id": base["facility"]["id"], "cdm_number": "CDM-3001"}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []
