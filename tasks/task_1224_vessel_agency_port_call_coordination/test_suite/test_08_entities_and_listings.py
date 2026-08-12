"""Entity creation defaults, not-found, computed-field server ownership,
required-field shape checks, enum validation, and list pagination."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    is_valid_uuid, is_iso8601_timestamp, NON_EXISTENT_UUID,
    ApiErrorId,
    set_clock, create_principal, create_port_call, create_vendor,
    create_purchase_order,
    make_agency_ops_headers, make_agency_admin_headers, make_agency_finance_headers,
    make_port_authority_headers,
)
from test_helpers.api_client import api_client


# ---------------------------------------------------------------------------
# Queue B: entities / principal_creation_defaults
# ---------------------------------------------------------------------------

def test_principal_creation_defaults(api):
    """PRD §3.1: "New principals start `ACTIVE`"; PRD §2.4: every resource
    carries "`id` ... formatted as a UUID", "`created_at` ... ISO 8601
    timestamp in UTC with three fractional digits", "`version` (integer)".
    PRD §4: "Operations that create new resources return a `201 Created`
    status code."

    Design: Corner/entities/principal_creation_defaults
    """
    resp = api_client.create_principal(
        {"name": "Apex Shipping", "contact_email": "ops@apex.example",
         "credit_limit_cents": 5000000},
        make_agency_admin_headers())
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE", "default applied"
    assert is_valid_uuid(data["id"])
    assert data["version"] == 1
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])


# ---------------------------------------------------------------------------
# Queue B: entities / principal_not_found
# ---------------------------------------------------------------------------

def test_principal_not_found(api):
    """PRD §2.7: "every identifier in the URL path is resolved left to right;
    the first identifier that does not resolve to an existing resource yields
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/principal_not_found
    """
    resp = api_client.get_principal(NON_EXISTENT_UUID, make_agency_ops_headers())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# ---------------------------------------------------------------------------
# Queue B: entities / port_call_computed_fields_input_ignored
# ---------------------------------------------------------------------------

def test_port_call_computed_fields_input_ignored(api):
    """PRD §3.1: "The new call starts in `ops_status` `NOMINATED`. At creation
    the system derives `alongside_days_estimated` — the hours between `eta`
    and `etd` divided by twenty-four, rounded up to a whole number of days,
    with a minimum of one day."

    Design: Corner/entities/port_call_computed_fields_input_ignored
    """
    principal = create_principal(name="Apex", credit_limit_cents=0)
    resp = api_client.create_port_call(
        {"principal_id": principal["id"], "vessel_name": "SS Rye",
         "imo_number": "9000020", "vessel_gt": 5000, "flag_state": "PA",
         "port_code": "NODUE", "eta": "2026-06-01T10:00:00Z",
         "etd": "2026-06-03T11:00:00Z", "cargo_description": "general",
         "ops_status": "SAILED", "alongside_days_estimated": 99},
        make_agency_ops_headers("ops-1"))
    data = validate_success(resp, expected_status=201)
    assert data["ops_status"] == "NOMINATED", "client-supplied ops_status ignored"
    # 49h -> ceil(49/24) = 3
    assert data["alongside_days_estimated"] == 3, "computed server-side, not 99"


# ---------------------------------------------------------------------------
# Queue B: entities / port_call_missing_required_eta_returns_400
# ---------------------------------------------------------------------------

def test_port_call_missing_required_eta_returns_400(api):
    """PRD §2.7: "13. **Request shape** — required fields present, enum values
    valid, and numeric ranges respected (`vessel_gt` greater than zero,
    monetary amounts positive where required, `quantity` at least one);
    otherwise `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1 lists `eta` among the fields an agent supplies at nomination.

    Design: Corner/entities/port_call_missing_required_eta_returns_400
    """
    principal = create_principal(name="Apex", credit_limit_cents=0)
    resp = api_client.create_port_call(
        {"principal_id": principal["id"], "vessel_name": "SS Rye",
         "imo_number": "9000020", "vessel_gt": 5000, "flag_state": "PA",
         "port_code": "NODUE", "etd": "2026-06-03T10:00:00Z",
         "cargo_description": "general"},
        make_agency_ops_headers("ops-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ---------------------------------------------------------------------------
# Queue B: entities / notification_invalid_enum_rejected
# ---------------------------------------------------------------------------

def test_notification_invalid_enum_rejected(api):
    """PRD §3.2: an Authority Notification carries "an `authority_type` of
    `PORT_STATE_CONTROL`, `IMMIGRATION`, `CUSTOMS`, or `HARBOR_MASTER`";
    PRD §2.7 stage 13: "enum values valid ... otherwise `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/notification_invalid_enum_rejected
    """
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    resp = api_client.create_authority_notification(
        {"port_call_id": pc["id"], "authority_type": "POLICE", "payload_summary": "x"},
        make_agency_ops_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ---------------------------------------------------------------------------
# Queue B: entities / port_call_listing_pagination
# ---------------------------------------------------------------------------

def test_port_call_listing_pagination(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items
    to return. If not provided, it defaults to 10"; "Paginated list responses
    include the following fields in the `meta` object of the response
    envelope: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §3.1: "port-call listings accept `principal_id`, `ops_status`, and
    `port_code` filters."

    Design: Corner/entities/port_call_listing_pagination
    """
    principal = create_principal(name="Apex", credit_limit_cents=0)
    for i in range(3):
        create_port_call(principal["id"], vessel_name=f"V{i+1}",
                         imo_number=f"900010{i+1}")
    data, meta = validate_paginated(api_client.list_port_calls(
        make_agency_ops_headers(),
        params={"principal_id": principal["id"], "limit": 2, "offset": 0}))
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    data2, meta2 = validate_paginated(api_client.list_port_calls(
        make_agency_ops_headers(),
        params={"principal_id": principal["id"], "limit": 2, "offset": 2}))
    assert len(data2) == 1
    assert meta2["has_more"] is False


# ---------------------------------------------------------------------------
# Queue B: endpoints / po_list_filter_pagination
# ---------------------------------------------------------------------------

def test_po_list_filter_pagination(api):
    """PRD §3.4: "Order listings accept `port_call_id`, `vendor_id`,
    `da_line_id`, and `status` filters"; PRD §2.3: "Paginated list responses
    include ... `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/po_list_filter_pagination
    """
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc1 = create_port_call(principal["id"])
    pc2 = create_port_call(principal["id"], vessel_name="SS Owl", imo_number="9000021",
                           vessel_gt=4000, eta="2026-06-05T10:00:00Z",
                           etd="2026-06-06T10:00:00Z")
    vendor = create_vendor(name="ChandlerCo", categories=["PROVISIONS"],
                           contact_email="c@x.example")
    create_purchase_order(pc1["id"], vendor["id"], estimated_cents=5000)
    create_purchase_order(pc1["id"], vendor["id"], estimated_cents=6000)
    create_purchase_order(pc2["id"], vendor["id"], estimated_cents=7000,
                          needed_by="2026-06-05T09:00:00Z")
    data, meta = validate_paginated(api_client.list_purchase_orders(
        make_agency_finance_headers(),
        params={"port_call_id": pc1["id"], "status": "DRAFT", "limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert all(item["port_call_id"] == pc1["id"] and item["status"] == "DRAFT" for item in data)


# ---------------------------------------------------------------------------
# Queue B: endpoints / tariff_da_lines_reverse_lookup
# ---------------------------------------------------------------------------

def test_tariff_da_lines_reverse_lookup(api):
    """PRD §3.8: "When a `PUBLISHED` tariff exists for the call's `port_code`
    and the `PORT_DUES` component, creation also seeds a `PORT_DUES` line
    whose `source_type` is `TARIFF`, priced by the estimate variant of the
    port-dues calculation below, pinning that tariff on the line's
    `tariff_id`"; "a read capability lists, for any tariff, the account lines
    that pin that tariff version."

    Design: Corner/endpoints/tariff_da_lines_reverse_lookup
    """
    from test_helpers import create_da_for_call
    from test_helpers.factories import create_tariff_payload
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"], port_code="SINGA",
                          eta="2026-06-10T10:00:00Z", etd="2026-06-11T10:00:00Z")
    tariff = get_success_data(api_client.create_tariff(
        create_tariff_payload(gt_tiers=[{"gt_up_to": None, "rate_cents": 2.0}]),
        make_port_authority_headers()))
    da = create_da_for_call(pc)
    data, meta = validate_paginated(api_client.list_tariff_da_lines(
        tariff["id"], make_agency_ops_headers()))
    assert len(data) == 1
    line = data[0]
    assert line["tariff_id"] == tariff["id"]
    assert line["category"] == "PORT_DUES"
    assert line["source_type"] == "TARIFF"
    # 5000 GT * 2.0 * 1 day, daytime eta (10:00), hazmat false
    assert line["estimated_cents"] == 10000
