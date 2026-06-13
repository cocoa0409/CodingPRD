"""Entity-level claims: project creation, required fields, not-found,
field defaults, immutability, computed fields, referential resolution.

Translates Corner/entities instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_customer, create_project,
    create_project_payload, create_line_item_payload,
    setup_priced_estimate,
    assert_project, assert_customer,
)

PM = TEST_USERS["project_manager_headers"]
EST = TEST_USERS["estimator_headers"]


def test_create_project_returns_201_with_system_fields(api):
    """PRD §3.1: "A fresh project starts in `DRAFT` status with a `contract_total` of 0.00, a `permit_clearance` of `PENDING`, an `active_estimate_id` of null, and `draws_paid_total` and `balance_due` both at zero."
    PRD §4: "Operations that create a new, stand-alone resource or add a new resource to a collection return `201 Created`."
    PRD §2.4: "a `version`, an integer that begins at its initial value and increments by one with each mutation."

    Design: Corner/entities/create_project_returns_201_with_system_fields
    """
    cust = create_customer(hoa_governed=False)
    resp = api.create_project(
        create_project_payload(cust["id"], site_address="1 Create", job_type="FENCE"), PM)
    proj = validate_success(resp, expected_status=201)
    assert_project(proj)
    assert proj["status"] == "DRAFT"
    assert proj["contract_total"] == 0.00
    assert proj["permit_clearance"] == "PENDING"
    assert proj["version"] == 1


def test_create_project_missing_job_type_returns_invalid_request(api):
    """PRD §3.1: "supplying the `customer_id` of the owner, a free-text `site_address` for the build location, and a `job_type` chosen from `FENCE`, `DECK`, or `FENCE_AND_DECK`."
    PRD §2.9: "Required-field presence and enum-domain checks follow, yielding `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_project_missing_job_type_returns_invalid_request
    """
    cust = create_customer()
    payload = {"customer_id": cust["id"], "site_address": "2 NoType"}
    resp = api.create_project(payload, PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_project_nonexistent_returns_not_found(api):
    """PRD §2.6: "The first identifier in the path that does not resolve to an existing resource produces `ERR_NOT_FOUND`, and a child is only ever considered within the scope of its already-validated parent."

    Design: Corner/entities/get_project_nonexistent_returns_not_found
    """
    resp = api.get_project("00000000-0000-4000-8000-000000000000", PM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_lineitem_default_accessory_and_slope_applied(api):
    """PRD §3.2: "An optional `accessory` (`NONE`, `SINGLE_GATE`, `DOUBLE_GATE`, or `STAIR_SET`, defaulting to `NONE`) adds a flat per-line charge, and an optional `grade_slope_pct` (defaulting to 0) records the terrain grade."
    PRD §3.2: "cedar privacy fencing runs 42.50 per foot" — a 100ft CEDAR/PRIVACY
    line with no accessory and no slope prices to 42.50*100 = 4250.00.

    Design: Corner/entities/lineitem_default_accessory_and_slope_applied
    """
    cust = create_customer()
    proj = create_project(cust["id"], job_type="FENCE")
    est = get_success_data(api.create_estimate(proj["id"], {}, EST))
    li = get_success_data(api.create_line_item(
        create_line_item_payload(est["id"], work_type="FENCE", material="CEDAR",
                                 style="PRIVACY", quantity_units=100), EST))
    get_success_data(api.price_estimate(proj["id"], est["id"], EST))
    li_after = get_success_data(api.get_line_item(li["id"], EST))
    assert li_after["accessory"] == "NONE"
    assert li_after["grade_slope_pct"] == 0
    assert li_after["line_material_cost"] == 4250.00


def test_estimate_tax_rate_default_applied(api):
    """PRD §3.2: "optionally overriding the material tax rate via `tax_rate_pct` (a percent applied per line, defaulting to 7.25)."

    Design: Corner/entities/estimate_tax_rate_default_applied
    """
    cust = create_customer()
    proj = create_project(cust["id"], job_type="FENCE")
    est = get_success_data(api.create_estimate(proj["id"], {}, EST))
    assert est["tax_rate_pct"] == 7.25


def test_customer_immutable_no_version_field(api):
    """PRD §2.4: "The `Customer` resource is the sole exception: it is an immutable identity record. A `Customer` carries only `id` and `created_at`. It has no `updated_at` field and no `version` field, because once created it is never modified."

    Design: Corner/entities/customer_immutable_no_version_field
    """
    cust = create_customer(hoa_governed=True)
    resp = api.get_customer(cust["id"], PM)
    data = validate_success(resp, expected_status=200)
    assert_customer(data)
    assert data["hoa_governed"] is True
    assert "version" not in data, "immutable Customer must not carry a version field"
    assert "updated_at" not in data, "immutable Customer must not carry an updated_at field"


def test_project_balance_due_computed_field(api):
    """PRD §3.8: "its `balance_due` (the `contract_total` minus `draws_paid_total`)."
    PRD §3.3: "sets the project's `active_estimate_id` to this estimate and its `contract_total` to the estimate's `contract_total`" — with no draws paid, balance_due equals the contract total 21605.04.

    Design: Corner/entities/project_balance_due_computed_field
    """
    ctx = setup_priced_estimate()
    pid = ctx["project"]["id"]
    get_success_data(api.accept_estimate(pid, ctx["estimate"]["id"], ctx["customer_headers"]))
    proj = get_success_data(api.get_project(pid, PM))
    assert proj["contract_total"] == 21605.04
    assert proj["draws_paid_total"] == 0.00
    assert proj["balance_due"] == 21605.04


def test_create_project_unresolvable_customer_returns_reference_not_found(api):
    """PRD §3.1: "The `customer_id` must resolve to an existing `Customer`, or the creation fails with `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/entities/create_project_unresolvable_customer_returns_reference_not_found
    """
    payload = create_project_payload(
        "00000000-0000-4000-8000-000000000999", site_address="6 NoCust", job_type="FENCE")
    resp = api.create_project(payload, PM)
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)
