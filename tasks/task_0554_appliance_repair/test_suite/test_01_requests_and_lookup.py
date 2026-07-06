"""Request/appliance CRUD, lookup, and creation-time computed defaults."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    assert_service_request, assert_appliance,
    create_service_request_payload, create_appliance_payload,
    create_customer, create_appliance, TEST_USERS, make_customer_headers,
    NON_EXISTENT_UUID,
)

ADMIN = TEST_USERS["service_admin_headers"]


def test_open_service_request_born_in_intake(api):
    """PRD §2.4: "A newly created service request is created with `status` `INTAKE`
    and `version` 1."

    Design: Corner/entities/create_service_request_returns_intake
    """
    cust = create_customer()
    app = create_appliance(cust["id"])
    res = api.create_service_request(
        create_service_request_payload(cust["id"], app["id"], reported_issue="won't cool"),
        make_customer_headers(cust["id"]))
    sr = validate_success(res, 201)
    # PRD §2.4 fixes only status and version at creation. `warranty_routing` is not
    # determined until diagnosis (PRD §3.3); PRD §2.4/§3.1 do not pin its INTAKE-stage
    # value, so assert_service_request()'s routing-enum check is not derivable here.
    assert sr["status"] == "INTAKE", f"expected INTAKE, got {sr['status']}"
    assert sr["version"] == 1, f"expected version 1, got {sr['version']}"


def test_get_nonexistent_service_request_returns_not_found(api):
    """PRD §2.8: "Read and action endpoints that address a specific resource by its `id`
    first confirm that the resource exists; a missing resource yields `ERR_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/entities/get_service_request_nonexistent_returns_not_found
    """
    res = api.get_service_request(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_open_request_missing_appliance_id_rejected(api):
    """PRD §2.1: "A request whose body is structurally malformed — a missing required field,
    an unrecognized enum value, or a dispatch window whose end is not strictly after its
    start — is rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_service_request_missing_required_appliance_id
    """
    cust = create_customer()
    payload = {"customer_id": cust["id"], "reported_issue": "x"}  # appliance_id omitted
    res = api.create_service_request(payload, ADMIN)
    validate_error(res, ApiErrorId.ERR_VALIDATION)


def test_new_appliance_defaults_to_clear_with_no_repairs(api):
    """PRD §2.6: "An appliance is `RECALLED` exactly when at least one `RecallNotice` whose
    `status` is `ACTIVE` matches the appliance on both `brand` and `model`; otherwise it is
    `CLEAR`."
    PRD §3.1: "A registered appliance exposes its computed `recall_status`, its
    `completed_repair_count` (the number of `COMPLETED` service requests that reference it),
    and its `health_score`."

    Design: Corner/entities/appliance_recall_status_defaults_clear
    """
    cust = create_customer()
    res = api.create_appliance(
        create_appliance_payload(cust["id"], brand="Kenmore", model="N20"), ADMIN)
    app = validate_success(res, 201)
    assert_appliance(app)
    assert app["recall_status"] == "CLEAR"
    assert app["completed_repair_count"] == 0


def test_list_appliances_filtered_by_customer(api):
    """PRD §3.1: "Appliances may be listed and filtered by `customer_id`".

    Design: Corner/entities/list_appliances_by_customer_fk_reverse
    """
    cust = create_customer()
    app = create_appliance(cust["id"], model="N30", serial_number="SN-N30")
    data, meta = validate_paginated(api.list_appliances(ADMIN, params={"customer_id": cust["id"]}))
    ids = [a["id"] for a in data]
    assert app["id"] in ids, "the customer's appliance must appear in the FK-reverse listing"
    assert all(a["customer_id"] == cust["id"] for a in data)
