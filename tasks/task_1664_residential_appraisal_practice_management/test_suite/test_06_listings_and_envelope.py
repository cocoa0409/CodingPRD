"""Listing / pagination / response-envelope claims (PRD 2.2, 2.3, and the
per-entity filter sentences of PRD 3)."""
from test_helpers import (
    UNKNOWN_UUID,
    ApiErrorId,
    add_locked_comp,
    create_appraiser,
    create_client,
    create_comparable,
    create_complaint,
    create_fee_schedule,
    create_membership,
    create_order,
    create_revision_request,
    create_trainee,
    make_clientuser_headers,
    scope_order,
    set_clock,
    setup_assigned_order,
    setup_delivered_order,
    setup_order_in_analysis,
    validate_error,
    validate_paginated,
    validate_success,
    create_appointment as create_appointment_fx,
)
from test_helpers import ADMIN, COMPLIANCE


def test_clients_list_pagination_envelope(api):
    """PRD 2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
    parameter sets how many items are skipped and defaults to 0."
    PRD 2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the response envelope."

    Design: Corner/endpoints/clients_list_pagination_envelope
    """
    set_clock("2026-08-01T00:00:00Z")
    for name in ("C1", "C2", "C3"):
        create_client(name=name)

    page1, meta1 = validate_paginated(
        api.list_clients(ADMIN, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_clients(ADMIN, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["has_more"] is False


def test_orders_list_status_filter(api):
    """PRD 3.3: "Orders can be listed filtered by `client_id`,
    `assigned_appraiser_id`, or `status`."

    Design: Corner/endpoints/orders_list_status_filter
    """
    set_clock("2026-08-01T00:00:00Z")
    client = create_client()
    order1 = create_order(client["id"], property_address="1 St")
    order2 = create_order(client["id"], property_address="2 St")
    scope_order(order2["id"])

    data, meta = validate_paginated(
        api.list_orders(ADMIN, params={"status": "RECEIVED"})
    )
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["id"] == order1["id"]


def test_response_envelope_shape_on_success_and_error(api):
    """PRD 2.2: "The `response_type` is either "object" for a single resource
    or "array" for a list of resources."
    PRD 2.2: "The `data` field contains the resource object or an array of
    resource objects."
    PRD 2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD 2.2: "The `message` provides a human-readable explanation of what
    went wrong."

    Design: Corner/endpoints/response_envelope_shape_on_success_and_error
    """
    created = api.create_client(create_client_payload_for_envelope(), ADMIN)
    body = created.json()
    assert created.status_code == 201
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    for field in ("id", "created_at", "version"):
        assert field in body["data"]

    error = api.get_client(UNKNOWN_UUID, ADMIN)
    err_body = error.json()
    assert error.status_code == 404
    assert err_body["response_type"] == "error"
    assert err_body["data"]["error_id"] == "ERR_CLIENT_NOT_FOUND"
    assert isinstance(err_body["data"]["message"], str)
    assert err_body["data"]["message"].strip()


def create_client_payload_for_envelope():
    from test_helpers import create_client_payload

    return create_client_payload()


def test_appraisers_list_supervisor_id_filter(api):
    """PRD 3.2: "The roster list accepts `license_level`, `status`, and
    `supervisor_id` filters."

    Design: Corner/endpoints/appraisers_list_supervisor_id_filter
    """
    set_clock("2026-08-01T00:00:00Z")
    supervisor = create_appraiser(
        full_name="Sara Supervisor", license_number="CR-1"
    )
    trainee = create_trainee(supervisor["id"], full_name="Tina Trainee")
    create_appraiser(full_name="Andy Other", license_level="LICENSED",
                     license_number="LA-9")

    data, meta = validate_paginated(
        api.list_appraisers(ADMIN, params={"supervisor_id": supervisor["id"]})
    )
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["id"] == trainee["id"]


def test_fee_schedules_list_client_filter(api):
    """PRD 3.1: "Schedules can be listed filtered by `client_id` or
    `complexity_tier`."

    Design: Corner/endpoints/fee_schedules_list_client_filter
    """
    set_clock("2026-08-01T00:00:00Z")
    client_c = create_client(name="C")
    fs_c = create_fee_schedule(client_c["id"])
    client_d = create_client(name="D")
    create_fee_schedule(client_d["id"], base_fee_cents=50000)

    data, meta = validate_paginated(
        api.list_fee_schedules(ADMIN, params={"client_id": client_c["id"]})
    )
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["id"] == fs_c["id"]


def test_appointments_list_order_filter(api):
    """PRD 3.4: "Appointments can be listed filtered by `order_id`,
    `appraiser_id`, or `status`."

    Design: Corner/endpoints/appointments_list_order_filter
    """
    ctx = setup_assigned_order(desktop=False, order_overrides={"requested_turn_days": 14})
    appointment = create_appointment_fx(
        ctx["order"]["id"],
        ctx["appraiser"]["id"],
        "2026-08-02T09:00:00Z",
        "2026-08-02T10:00:00Z",
    )

    data, meta = validate_paginated(
        api.list_appointments(ADMIN, params={"order_id": ctx["order"]["id"]})
    )
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["id"] == appointment["id"]


def test_comparables_list_order_filter(api):
    """PRD 3.5: "The list view filters by `order_id` or `status`."

    Design: Corner/endpoints/comparables_list_order_filter
    """
    ctx = setup_order_in_analysis()
    comp = create_comparable(ctx["order"]["id"], ctx["appraiser"]["id"])

    data, meta = validate_paginated(
        api.list_comparables(ADMIN, params={"order_id": ctx["order"]["id"]})
    )
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["id"] == comp["id"]


def test_delivered_order_related_lists_filter(api):
    """PRD 3.6: "Reports can be listed filtered by `order_id`, `status`,
    `signing_appraiser_id`, `co_signer_appraiser_id`, or `reviewer_id`."
    PRD 3.7: "Revision requests can be listed filtered by `order_id` or
    `status`."
    PRD 3.8: "Complaints can be listed filtered by `order_id`,
    `respondent_appraiser_id`, or `status`."

    Design: Corner/endpoints/delivered_order_related_lists_filter
    """
    ctx = setup_delivered_order()
    rr = create_revision_request(ctx["order"]["id"], ctx["client"]["id"])
    complaint = create_complaint(ctx["order"]["id"], ctx["appraiser"]["id"])

    reports, meta_r = validate_paginated(
        api.list_reports(ADMIN, params={"order_id": ctx["order"]["id"]})
    )
    assert meta_r["total_count"] == 1
    assert reports[0]["id"] == ctx["report"]["id"]

    revisions, meta_v = validate_paginated(
        api.list_revision_requests(ADMIN, params={"order_id": ctx["order"]["id"]})
    )
    assert meta_v["total_count"] == 1
    assert revisions[0]["id"] == rr["id"]

    complaints, meta_c = validate_paginated(
        api.list_complaints(COMPLIANCE, params={"order_id": ctx["order"]["id"]})
    )
    assert meta_c["total_count"] == 1
    assert complaints[0]["id"] == complaint["id"]


def test_error_envelope_contains_error_id_and_message(api):
    """PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the specific
    error."
    PRD 2.2: "The `message` provides a human-readable explanation of what went wrong."
    PRD 2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/errors/error_envelope_contains_error_id_and_message
    """
    error = api.get_client(UNKNOWN_UUID, ADMIN)
    body = error.json()
    assert error.status_code == 404
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_CLIENT_NOT_FOUND"
    assert isinstance(body["data"]["message"], str)
    assert len(body["data"]["message"].strip()) > 0
