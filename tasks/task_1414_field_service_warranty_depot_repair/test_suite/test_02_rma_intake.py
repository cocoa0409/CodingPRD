"""RMA opening, authorization gates, receiving, cancellation, OCC on draft edit."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_rma,
    authorize_rma,
    create_customer,
    create_draft_rma,
    create_model,
    create_rma_payload,
    create_unit,
    get_rma,
    list_notifications,
    make_customer_headers,
    setup_authorized_rma,
    setup_draft_rma,
    setup_received_rma,
    validate_error,
    validate_success,
)


def test_rma_creation_unit_customer_mismatch_rejected(api):
    """PRD §3.2: "The referenced unit must belong to the payload customer; a
    unit owned by someone else is rejected with `ERR_UNIT_CUSTOMER_MISMATCH`."

    Design: Corner/entities/rma_creation_unit_customer_mismatch_rejected
    """
    model = create_model()
    cust_a = create_customer()
    cust_b = create_customer()
    unit = create_unit(model["id"], cust_a["id"])
    res = api.create_rma(
        create_rma_payload(cust_b["id"], unit["id"], reported_issue="wrong owner"),
        TEST_USERS["intake_agent_headers"])
    validate_error(res, ApiErrorId.ERR_UNIT_CUSTOMER_MISMATCH)
    assert res.status_code == 422


def test_rma_get_not_found_returns_404(api):
    """PRD §2.8: "Fourth, existence of path identifiers, resolved left to right
    along the URL: identifiers such as `customerId`, `modelId`, `unitId`,
    `partId`, `bayId`, `loanerUnitId`, `rmaId`, `quoteId`, `reservationId`,
    `escalationId`, `repairLineId`, and the bare `id` used on nested quote and
    notification listings are checked in the order they appear, and the first
    identifier that does not resolve short-circuits the request with its own 404
    — respectively `ERR_CUSTOMER_NOT_FOUND`, `ERR_MODEL_NOT_FOUND`,
    `ERR_UNIT_NOT_FOUND`, `ERR_PART_NOT_FOUND`, `ERR_FAILURE_CODE_NOT_FOUND`,
    `ERR_BAY_NOT_FOUND`, `ERR_LOANER_UNIT_NOT_FOUND`, `ERR_RMA_NOT_FOUND`,
    `ERR_QUOTE_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`,
    `ERR_ESCALATION_NOT_FOUND`, or `ERR_REPAIR_LINE_NOT_FOUND`."

    Design: Corner/entities/rma_get_not_found_returns_404
    """
    create_customer()  # non-empty DB
    res = api.get_rma(NON_EXISTENT_UUID, TEST_USERS["intake_agent_headers"])
    validate_error(res, ApiErrorId.ERR_RMA_NOT_FOUND)
    assert res.status_code == 404


def test_path_not_found_quote_reservation_escalation_line(api):
    """PRD §2.8: "the first identifier that does not resolve short-circuits the
    request with its own 404 — respectively `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_MODEL_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_PART_NOT_FOUND`,
    `ERR_FAILURE_CODE_NOT_FOUND`, `ERR_BAY_NOT_FOUND`,
    `ERR_LOANER_UNIT_NOT_FOUND`, `ERR_RMA_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`,
    `ERR_RESERVATION_NOT_FOUND`, `ERR_ESCALATION_NOT_FOUND`, or
    `ERR_REPAIR_LINE_NOT_FOUND`."

    Design: Corner/errors/path_not_found_quote_reservation_escalation_line
    """
    create_customer()  # non-empty DB
    r1 = api.get_quote(NON_EXISTENT_UUID, TEST_USERS["depot_technician_headers"])
    validate_error(r1, ApiErrorId.ERR_QUOTE_NOT_FOUND)
    assert r1.status_code == 404

    r2 = api.get_loaner_reservation(NON_EXISTENT_UUID, TEST_USERS["intake_agent_headers"])
    validate_error(r2, ApiErrorId.ERR_RESERVATION_NOT_FOUND)
    assert r2.status_code == 404

    r3 = api.acknowledge_escalation(NON_EXISTENT_UUID,
                                    TEST_USERS["engineering_lead_headers"])
    validate_error(r3, ApiErrorId.ERR_ESCALATION_NOT_FOUND)
    assert r3.status_code == 404

    r4 = api.reverse_repair_line(NON_EXISTENT_UUID,
                                 TEST_USERS["depot_technician_headers"])
    validate_error(r4, ApiErrorId.ERR_REPAIR_LINE_NOT_FOUND)
    assert r4.status_code == 404


def test_customer_reading_other_customers_rma_forbidden(api):
    """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of
    the acting `Customer`; ownership checks on any resource that references a
    `Customer` compare the resource's customer linkage — the `customer_id`
    carried on a unit or an RMA, or the owning chain behind a quote, a loaner
    reservation, or a notification — to `X-User-ID`, and a mismatch is rejected
    with `ERR_NOT_OWNER` (HTTP 403)."

    Design: Corner/rbac/customer_reading_other_customers_rma_forbidden
    """
    ctx = setup_draft_rma()
    cust_b = create_customer()
    res = api.get_rma(ctx["rma"]["id"], make_customer_headers(cust_b["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_OWNER)
    assert res.status_code == 403


def test_rma_initial_state_is_draft(api):
    """PRD §3.2: "The RMA is born in `DRAFT` status and is assigned a human
    reference `rma_number` of the form RMA- followed by a zero-padded sequence."
    PRD §3.2: "optionally a `service_option` of `STANDARD`, `LOANER`, or
    `ADVANCE_EXCHANGE` (defaulting to `STANDARD`)"

    Design: Corner/state_machines/rma_initial_state_is_draft
    """
    model = create_model()
    customer = create_customer()
    unit = create_unit(model["id"], customer["id"])
    res = api.create_rma(create_rma_payload(customer["id"], unit["id"]),
                         TEST_USERS["intake_agent_headers"])
    rma = validate_success(res, 201)
    assert_rma(rma)
    assert rma["status"] == "DRAFT", f"new RMA must be DRAFT, got {rma['status']}"
    assert rma["rma_number"].startswith("RMA-"), (
        f"rma_number must carry the RMA- prefix, got {rma['rma_number']}")
    assert rma["service_option"] == "STANDARD", (
        f"default service_option must be STANDARD, got {rma['service_option']}")


def test_customer_cannot_authorize_rma(api):
    """PRD §2.1: "A request whose role is recognized but not listed among the
    roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."
    PRD §4: POST /depot/rmas/{rmaId}/authorize is authorized for IntakeAgent
    only.

    Design: Corner/rbac/customer_cannot_authorize_rma
    """
    ctx = setup_draft_rma()
    res = api.authorize_rma(ctx["rma"]["id"],
                            make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)
    assert res.status_code == 403
    assert get_rma(ctx["rma"]["id"])["status"] == "DRAFT"


def test_authorize_second_open_rma_per_unit_rejected(api):
    """PRD §3.2: "Authorization is refused with `ERR_UNIT_HAS_OPEN_RMA` when any
    other RMA for the same unit sits in a non-terminal state — that is, any
    state other than `CLOSED`, `SCRAPPED`, or `CANCELLED`."

    Design: Corner/validations/authorize_second_open_rma_per_unit_rejected
    """
    ctx = setup_authorized_rma()
    rma2 = create_draft_rma(ctx["customer"]["id"], ctx["unit"]["id"],
                            reported_issue="second")
    blocked = api.authorize_rma(rma2["id"], TEST_USERS["intake_agent_headers"])
    validate_error(blocked, ApiErrorId.ERR_UNIT_HAS_OPEN_RMA)
    assert blocked.status_code == 409

    # Cancelling the first RMA moves it to a terminal state and unblocks.
    validate_success(api.cancel_rma(ctx["rma"]["id"], TEST_USERS["intake_agent_headers"]), 200)
    authorized = authorize_rma(rma2["id"])
    assert authorized["status"] == "AUTHORIZED"


def test_receive_on_draft_rejected_invalid_state(api):
    """PRD §3.3: "Receipt moves the RMA from `AUTHORIZED` to `RECEIVED`, pins
    `received_at` from the logical clock — this is the SLA anchor from which
    turnaround is measured — and emits a `RECEIVED` notification."
    PRD §2.8: "Sixth, state-machine legality — whether the target entity is in a
    state permitting the requested transition — yielding the matching error
    among `ERR_INVALID_RMA_STATE`, `ERR_INVALID_QUOTE_STATE`,
    `ERR_INVALID_RESERVATION_STATE`, `ERR_INVALID_LOANER_STATE`,
    `ERR_INVALID_ESCALATION_STATE`, and `ERR_INVALID_LINE_STATE`."

    Design: Corner/state_machines/receive_on_draft_rejected_invalid_state
    """
    ctx = setup_draft_rma()
    res = api.receive_rma(ctx["rma"]["id"],
                          {"serial_number": ctx["unit"]["serial_number"]},
                          TEST_USERS["intake_agent_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_RMA_STATE)
    assert res.status_code == 409
    after = get_rma(ctx["rma"]["id"])
    assert after["status"] == "DRAFT"
    assert after["received_at"] is None, "received_at must not be pinned by a rejected receive"


def test_receive_serial_mismatch_rejected(api):
    """PRD §3.3: "When the physical unit arrives, an `IntakeAgent` records
    receipt with a payload `serial_number` that must equal the registered serial
    of the RMA's unit; a mismatch is rejected with `ERR_SERIAL_MISMATCH`."

    Design: Corner/validations/receive_serial_mismatch_rejected
    """
    ctx = setup_authorized_rma()
    res = api.receive_rma(ctx["rma"]["id"], {"serial_number": "SN-WRONG"},
                          TEST_USERS["intake_agent_headers"])
    validate_error(res, ApiErrorId.ERR_SERIAL_MISMATCH)
    assert res.status_code == 409
    assert get_rma(ctx["rma"]["id"])["status"] == "AUTHORIZED"


def test_cancel_on_cancelled_terminal_lockdown(api):
    """PRD §3.2: "Cancellation is available to the owning `Customer` or an
    `IntakeAgent` while the RMA is in `DRAFT` or `AUTHORIZED`."
    PRD §2.8: "Sixth, state-machine legality — whether the target entity is in a
    state permitting the requested transition — yielding the matching error
    among `ERR_INVALID_RMA_STATE` ..."

    Design: Corner/state_machines/cancel_on_cancelled_terminal_lockdown
    """
    ctx = setup_draft_rma()
    cancelled = validate_success(
        api.cancel_rma(ctx["rma"]["id"], TEST_USERS["intake_agent_headers"]), 200)
    assert cancelled["status"] == "CANCELLED"
    res = api.cancel_rma(ctx["rma"]["id"], TEST_USERS["intake_agent_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_RMA_STATE)
    assert res.status_code == 409
    assert get_rma(ctx["rma"]["id"])["status"] == "CANCELLED"


def test_notification_event_created_on_authorize(api):
    """PRD §3.2: "Authorization also pins the `provisional_estimate_cents` to
    the model's `flat_rate_repair_cents`, records `authorized_at` from the
    logical clock, and emits an `RMA_AUTHORIZED` notification."
    PRD §2.10: "Every customer-visible milestone writes an immutable
    `NotificationEvent` carrying the `rma_id` it concerns, an `event_type`, the
    `recipient` — the customer's `email` address captured at event time — and
    the rendered `message` text."

    Design: Corner/entities/notification_event_created_on_authorize
    """
    ctx = setup_draft_rma()
    authorize_rma(ctx["rma"]["id"])
    events = list_notifications(ctx["rma"]["id"])
    assert len(events) == 1, f"exactly one notification must exist after authorize, got {len(events)}"
    assert events[0]["event_type"] == "RMA_AUTHORIZED"
    assert events[0]["recipient"] == ctx["customer"]["email"]
    assert events[0]["rma_id"] == ctx["rma"]["id"]


def test_immediate_consistency_same_response_and_reread(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.2: "The computed basis end is pinned as `warranty_end_date_used`, and
    the RMA's `coverage_path` is pinned to `IN_WARRANTY` when the clock date is
    on or before that end — eligibility is inclusive of the final warranty day —
    and to `OUT_OF_WARRANTY` otherwise."

    Design: Corner/consistency_model/immediate_consistency_same_response_and_reread
    """
    ctx = setup_draft_rma()
    res = api.authorize_rma(ctx["rma"]["id"], TEST_USERS["intake_agent_headers"])
    authorized = validate_success(res, 200)
    assert authorized["status"] == "AUTHORIZED"
    assert authorized["coverage_path"] == "IN_WARRANTY"
    assert authorized["provisional_estimate_cents"] == 15000, (
        "provisional estimate must be the model flat rate 15000, got "
        f"{authorized['provisional_estimate_cents']}")

    reread = get_rma(ctx["rma"]["id"])
    assert reread["status"] == authorized["status"] == "AUTHORIZED"
    assert reread["coverage_path"] == authorized["coverage_path"] == "IN_WARRANTY"
    # purchase_date 2026-01-01 + 365 standard warranty days = 2027-01-01
    assert reread["warranty_end_date_used"][:10] == "2027-01-01"


def test_occ_patch_stale_version(api):
    """PRD §2.7: "Three write operations are guarded by optimistic concurrency
    control against the parent RMA: editing a draft RMA, creating a revised
    quote for an RMA, and recording a parts-consumption line on an RMA. Each of
    these requests must carry `expected_rma_version`, a non-optional input
    holding the `version` of the `ServiceRMA` the client last observed. If the
    supplied value does not match the RMA's current `version` — because another
    write has advanced the version since the client last read it — the request
    is rejected with `ERR_STALE_RMA_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/occ_patch_stale_version
    """
    ctx = setup_draft_rma()
    v0 = ctx["rma"]["version"]

    first = api.patch_rma(ctx["rma"]["id"],
                          {"reported_issue": "updated text",
                           "expected_rma_version": v0},
                          TEST_USERS["intake_agent_headers"])
    patched = validate_success(first, 200)
    assert patched["version"] == v0 + 1, (
        f"successful edit must bump the version by one: {v0} -> {patched['version']}")
    assert patched["reported_issue"] == "updated text"

    replay = api.patch_rma(ctx["rma"]["id"],
                           {"reported_issue": "third text",
                            "expected_rma_version": v0},
                           TEST_USERS["intake_agent_headers"])
    validate_error(replay, ApiErrorId.ERR_STALE_RMA_VERSION)
    assert replay.status_code == 412
    assert get_rma(ctx["rma"]["id"])["reported_issue"] == "updated text", (
        "the rejected replay must not apply its edit")
