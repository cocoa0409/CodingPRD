"""Auth headers, RBAC denials, ownership scoping, pagination, envelope, FK lists."""
from test_helpers import (
    ApiErrorId,
    CHEM,
    EHS,
    MGR,
    NON_EXISTENT_UUID,
    OP,
    QC,
    add_line_item,
    create_bath,
    create_customer,
    create_manifest,
    get_success_data,
    make_customer_headers,
    titrate_bath,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_bath_payload,
    create_discharge_permit_payload,
    create_work_order_payload,
)
from test_helpers.test_users import build_user_headers, make_ehs_officer_headers


def test_missing_auth_header_returns_400():
    """PRD §2.1: "A request missing either header, or carrying a role outside this
    declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
    (HTTP 400)."
    PRD §2.8: "All requests pass through a fixed twelve-tier validation cascade, and a
    request fails at the earliest tier that rejects it — earlier tiers mask later
    ones." (auth is tier 1; existence is tier 4)

    Design: Corner/validations/missing_auth_header_returns_400
    """
    # No role header at all — auth outranks existence, so not a 404.
    resp = api_client.get_bath(NON_EXISTENT_UUID, headers={"X-User-ID": "u-1"})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_role_not_listed_returns_403():
    """PRD §2.1: "A request whose role is not authorized for the target endpoint is
    rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §3.2: "A `ShopManager` commissions a **PlatingBath**" (creation is manager-only).

    Design: Corner/validations/role_not_listed_returns_403
    """
    resp = api_client.create_bath(create_bath_payload(bath_code="ANO-Z"), OP)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_customer_cannot_read_other_customer_order():
    """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the
    acting `Customer` record; ownership checks on any resource that references a
    customer compare the resource's `customer_id` field to `X-User-ID`, and a mismatch
    is rejected with `ERR_RESOURCE_NOT_OWNED` (HTTP 403)."

    Design: Corner/validations/customer_cannot_read_other_customer_order
    """
    ca = create_customer(company_name="A Co")
    cb = create_customer(company_name="B Co")
    wb = get_success_data(api_client.create_work_order(
        create_work_order_payload(customer_id=cb["id"], part_number="PN-B",
                                  part_count=5, surface_area_dm2_per_part=2.0,
                                  thickness_spec_min_um=10.0, thickness_spec_max_um=14.0),
        make_customer_headers(cb["id"]),
    ))
    resp = api_client.get_work_order(wb["id"], make_customer_headers(ca["id"]))
    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_OWNED)


def test_customer_list_scoped_to_own_records():
    """PRD §2.8 tier 3: "the caller may only reach resources whose `customer_id`
    equals `X-User-ID`, and a work order creation body must name the caller's own id"
    PRD §3.1: "Customer-role callers browsing the customer list see only their own
    record."
    PRD §3.4: "`Customer` callers are always scoped to their own orders, on the list,
    the detail, and every child collection."

    Design: Corner/validations/customer_list_scoped_to_own_records
    """
    ca = create_customer(company_name="A2 Co")
    cb = create_customer(company_name="B2 Co")
    for pn in ("PN-A1", "PN-A2"):
        get_success_data(api_client.create_work_order(
            create_work_order_payload(customer_id=ca["id"], part_number=pn,
                                      part_count=5, surface_area_dm2_per_part=2.0,
                                      thickness_spec_min_um=10.0,
                                      thickness_spec_max_um=14.0),
            MGR,
        ))
    get_success_data(api_client.create_work_order(
        create_work_order_payload(customer_id=cb["id"], part_number="PN-B1",
                                  part_count=5, surface_area_dm2_per_part=2.0,
                                  thickness_spec_min_um=10.0,
                                  thickness_spec_max_um=14.0),
        MGR,
    ))
    # Work order list scoped to the caller's own orders.
    data, meta = validate_paginated(
        api_client.list_work_orders(make_customer_headers(ca["id"]))
    )
    assert len(data) == 2
    assert meta["total_count"] == 2
    assert all(row["customer_id"] == ca["id"] for row in data)
    # Customer list scoped to the caller's own record.
    custs, meta_c = validate_paginated(
        api_client.list_customers(make_customer_headers(ca["id"]))
    )
    assert len(custs) == 1
    assert custs[0]["id"] == ca["id"]


def test_rbac_exclusive_denials_forbidden():
    """PRD §2.1: "A request whose role is not authorized for the target endpoint is
    rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §2.1: "A `ShopManager` is the hierarchical override — permitted on every
    endpoint and the sole actor for customer administration, fixture creation, bath
    creation, bath dump and renewal, late-state work order cancellation, and the
    logical clock — but remains bound by segregation of duties on manifest
    finalization like every other role."

    Design: Corner/rbac/rbac_exclusive_denials_forbidden
    """
    customer = create_customer(company_name="RBAC Co")
    wrb = get_success_data(api_client.create_work_order(
        create_work_order_payload(customer_id=customer["id"], part_number="PN-RB",
                                  part_count=5, surface_area_dm2_per_part=2.0,
                                  thickness_spec_min_um=10.0, thickness_spec_max_um=14.0),
        MGR,
    ))
    brb = create_bath(bath_code="ANO-RB", routing_modes_supported=["BARREL"])
    # Customer creating baths.
    e1 = api_client.create_bath(
        create_bath_payload(bath_code="ANO-RB2"), make_customer_headers(customer["id"])
    )
    validate_error(e1, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    # LabChemist recording an inspection.
    e2 = api_client.create_inspection(
        wrb["id"], {"thickness_readings_um": [12.0, 13.0, 14.0], "defect_type": "NONE"},
        CHEM,
    )
    validate_error(e2, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    # QCInspector recording a titration.
    e3 = api_client.create_titration(
        brb["id"],
        {"titrant_volume_ml": 50.0, "titrant_normality": 0.1, "sample_volume_ml": 49.0},
        QC,
    )
    validate_error(e3, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    # EHSOfficer preparing a work order.
    e4 = api_client.prepare_work_order(wrb["id"], {}, EHS)
    validate_error(e4, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    # LineOperator creating a discharge permit.
    e5 = api_client.create_discharge_permit(
        create_discharge_permit_payload(outfall_code="OUTFALL-RB"), OP
    )
    validate_error(e5, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    # ShopManager override performs the same prepare successfully.
    prepared = get_success_data(api_client.prepare_work_order(wrb["id"], {}, MGR))
    assert prepared["status"] == "READY_FOR_ROUTING"


def test_pagination_defaults_and_offset():
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults
    to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset`
    parameter states how many items to skip and defaults to 0."
    PRD §2.3: "Paginated list responses include the fields `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the response envelope."

    Design: Corner/endpoints/pagination_defaults_and_offset
    """
    customer = create_customer(company_name="Page Co")
    for i in range(12):
        get_success_data(api_client.create_work_order(
            create_work_order_payload(
                customer_id=customer["id"], part_number=f"PN-P{i + 1:02d}",
                part_count=1, surface_area_dm2_per_part=1.0,
                thickness_spec_min_um=10.0, thickness_spec_max_um=14.0,
            ),
            MGR,
        ))
    page1, meta1 = validate_paginated(
        api_client.list_work_orders(OP, params={"customer_id": customer["id"]})
    )
    assert len(page1) == 10
    assert meta1["total_count"] == 12
    assert meta1["has_more"] is True
    assert meta1["limit"] == 10
    assert meta1["offset"] == 0
    page2, meta2 = validate_paginated(
        api_client.list_work_orders(OP, params={"customer_id": customer["id"],
                                                "offset": 10})
    )
    assert len(page2) == 2
    assert meta2["total_count"] == 12
    assert meta2["has_more"] is False


def test_response_envelope_shape():
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array"
    for a list of resources."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/endpoints/response_envelope_shape
    """
    bath = create_bath(bath_code="ANO-ENV", routing_modes_supported=["BARREL"])
    # Detail response: object envelope.
    resp_detail = api_client.get_bath(bath["id"], CHEM)
    body = resp_detail.json()
    assert resp_detail.status_code == 200
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    # List response: array envelope.
    resp_list = api_client.list_titrations(bath["id"], CHEM)
    body_list = resp_list.json()
    assert body_list["response_type"] == "array"
    assert isinstance(body_list["data"], list)
    # Error response: error envelope with error_id and message.
    resp_err = api_client.get_bath(NON_EXISTENT_UUID, CHEM)
    body_err = resp_err.json()
    assert body_err["response_type"] == "error"
    assert body_err["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body_err["data"]["message"], str)
    assert len(body_err["data"]["message"].strip()) > 0


def test_fk_reverse_lists_resolvable():
    """PRD §3.2: "Titrations apply in arrival order — creation order — and the bath's
    titration history is listed in that same order."
    PRD §3.4: "The work order list supports the filters `customer_id`, `bath_id`,
    `fixture_id`, and `status`, letting staff trace every order a bath or fixture has
    touched"
    PRD §3.9: line items are listed per manifest (§4 "List a manifest's line items").

    Design: Corner/endpoints/fk_reverse_lists_resolvable
    """
    customer = create_customer(company_name="FK Co")
    bath = create_bath(bath_code="ANO-FK", routing_modes_supported=["BARREL"])
    tit = titrate_bath(bath["id"])
    wo = get_success_data(api_client.create_work_order(
        create_work_order_payload(customer_id=customer["id"], part_number="PN-FK",
                                  part_count=5, surface_area_dm2_per_part=2.0,
                                  thickness_spec_min_um=10.0, thickness_spec_max_um=14.0),
        make_customer_headers(customer["id"]),
    ))
    manifest = create_manifest(creator_user_id="ehs-fk", generator_epa_id="EPA-GEN-FK")
    li = add_line_item(manifest["id"], manifest["version"],
                       headers=make_ehs_officer_headers("ehs-fk"),
                       waste_code="D007", source_type="RINSE_CONCENTRATE",
                       description="Rinse", volume_liters=25)
    # The titration appears under the bath's titration list.
    tits, _m1 = validate_paginated(api_client.list_titrations(bath["id"], CHEM))
    assert len(tits) == 1
    assert tits[0]["id"] == tit["id"]
    assert tits[0]["bath_id"] == bath["id"]
    # The order appears under the customer filter.
    wos, _m2 = validate_paginated(
        api_client.list_work_orders(OP, params={"customer_id": customer["id"]})
    )
    assert len(wos) == 1
    assert wos[0]["id"] == wo["id"]
    # The line item appears under the manifest's line-item list (25 L x 1.2 = 30.0).
    lis, _m3 = validate_paginated(api_client.list_manifest_line_items(manifest["id"], EHS))
    assert len(lis) == 1
    assert lis[0]["id"] == li["id"]
    assert lis[0]["mass_kg"] == 30.0
