"""Lease term half-open overlap, response envelope shape, pagination, and
request-shape error mapping."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_charge,
    create_charge_payload,
    create_lease,
    create_lease_payload,
    create_property_payload,
    create_tenant_payload,
    setup_property_tenant_lease,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["property_manager_headers"]
AGENT = TEST_USERS["leasing_agent_headers"]


def test_lease_term_half_open_adjacency_allowed(api):
    """PRD 3.1: "Activating a lease — moving it from `DRAFT` to `ACTIVE` — is
    permitted only when its `term_end_date` is still in the future and no other
    `ACTIVE` lease on the same property and unit label has a term that intersects it;
    because terms are half-open, two leases whose terms merely touch, one ending on the
    day the next begins, do not conflict, while a genuine intersection is rejected with
    `ERR_LEASE_TERM_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/lease_term_half_open_overlap_on_unit
    """
    ctx = setup_property_tenant_lease()
    lease_b = create_lease(
        ctx["property"]["id"], ctx["tenant"]["id"], unit_label="101",
        term_start_date="2027-07-31", term_end_date="2028-07-30",
    )
    activated = validate_success(api.transition_lease(lease_b["id"], {"action": "ACTIVATE"}, PM))
    assert activated["status"] == "ACTIVE", (
        "Adjacent half-open terms (start 2027-07-31 == incumbent end 2027-07-31) do not conflict"
    )


def test_lease_term_half_open_intersection_rejected(api):
    """PRD 3.1: "Activating a lease — moving it from `DRAFT` to `ACTIVE` — is
    permitted only when its `term_end_date` is still in the future and no other
    `ACTIVE` lease on the same property and unit label has a term that intersects it;
    because terms are half-open, two leases whose terms merely touch, one ending on the
    day the next begins, do not conflict, while a genuine intersection is rejected with
    `ERR_LEASE_TERM_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/lease_term_half_open_overlap_on_unit
    """
    ctx = setup_property_tenant_lease()
    lease_c = create_lease(
        ctx["property"]["id"], ctx["tenant"]["id"], unit_label="101",
        term_start_date="2027-07-30", term_end_date="2028-07-29",
    )
    response = api.transition_lease(lease_c["id"], {"action": "ACTIVATE"}, PM)
    validate_error(response, ApiErrorId.ERR_LEASE_TERM_OVERLAP)


def test_response_envelope_and_error_shape(api):
    """PRD 2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."
    PRD 2.2: "The `response_type` is either "object" for a single resource or "array"
    for a list of resources."
    PRD 2.9 rule 4: "Foreign keys supplied in the request body — `property_id`,
    `primary_tenant_id`, `lease_id`, `tenant_id`, and every element of `charge_ids` —
    must reference existing resources; otherwise `ERR_NOT_FOUND`."

    Design: Corner/endpoints/response_envelope_and_error_shape
    """
    prop = validate_success(api.create_property(create_property_payload(), PM), 201)
    response = api.create_tenant(create_tenant_payload(), AGENT)
    body = response.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str) and body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str) and body["meta"]["api_request_timestamp"]
    tenant = body["data"]
    assert isinstance(tenant["id"], str) and tenant["id"]

    err_response = api.create_lease(
        create_lease_payload(NON_EXISTENT_UUID, tenant["id"]), PM
    )
    err_body = err_response.json()
    assert err_body["response_type"] == "error"
    validate_error(err_response, ApiErrorId.ERR_NOT_FOUND)


def test_charges_list_pagination_limit_offset(api):
    """PRD 2.3: "The `limit` parameter specifies the maximum number of items to
    return; when not provided it defaults to 10, and it accepts a minimum of 1 and a
    maximum of 100. The `offset` parameter specifies how many items to skip and
    defaults to 0."
    PRD 2.3: "List responses carry the following pagination fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/charges_list_pagination_limit_offset
    """
    ctx = setup_property_tenant_lease(activate=False)
    lease_id = ctx["lease"]["id"]
    add_charge(lease_id, amount_cents=200000)
    for i in range(11):
        add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=1000 + i)

    data1, meta1 = validate_paginated(api.list_charges(lease_id, PM))
    assert len(data1) == 10, f"Default limit 10 must return the first 10 of 12, got {len(data1)}"
    assert meta1["total_count"] == 12
    assert meta1["has_more"] is True

    data2, meta2 = validate_paginated(api.list_charges(lease_id, PM, params={"offset": 10}))
    assert len(data2) == 2
    assert meta2["total_count"] == 12
    assert meta2["has_more"] is False


def test_transition_unknown_action_rejected(api):
    """PRD 2.9 rule 18: "Required fields are present, enum values are valid,
    identifiers are well-formed, no undeclared fields appear in the payload, and an
    adjusted amount accompanies an adjusted dispute outcome within its permitted range;
    otherwise `ERR_INVALID_REQUEST`."
    PRD 3.1: "Lifecycle changes throughout the system are requested through a
    transition payload whose `action` field names the requested move; for a lease the
    actions are `ACTIVATE` and `MOVE_OUT`, the latter carrying the `move_out_date`
    described in §3.9."

    Design: Corner/endpoints/transition_unknown_action_rejected
    """
    ctx = setup_property_tenant_lease(activate=False)
    lease_id = ctx["lease"]["id"]

    response = api.transition_lease(lease_id, {"action": "EXPLODE"}, PM)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    from test_helpers import get_lease
    assert get_lease(lease_id)["status"] == "DRAFT"
