"""RBAC: exclusive operations reject callers whose role is not permitted."""

from test_helpers import (
    FACILITIES_MANAGER,
    FINANCE_ADMIN,
    SCHEDULER,
    SERVICE_COORDINATOR,
    ApiErrorId,
    advance_term_to_scheduling,
    approve_event,
    create_event,
    create_order,
    create_run,
    create_term,
    find_invoice_for_event,
    get_event,
    get_invoice,
    get_order,
    get_run,
    make_org_requester_headers,
    setup_org_room,
    validate_error,
)


def test_exclusive_operations_reject_the_wrong_role(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the
    target endpoint is rejected with `ERR_FORBIDDEN`."
    PRD §2.1: "The system recognizes five distinct roles: `OrgRequester`,
    `Scheduler`, `ServiceCoordinator`, `FacilitiesManager`, and `FinanceAdmin`."

    Design: Corner/rbac/cross_role_exclusive_ops_forbidden
    """
    # A SCHEDULING term holding a DRAFT run for the finalize denial.
    term = create_term()
    advance_term_to_scheduling(term["id"])
    run = create_run(term["id"])

    # Event dated 2026-12-20 — after the term's 2026-12-15 end, so the priority
    # window never interferes with the approval path below.
    scn = setup_org_room(room_overrides={"capacity": 30})
    event = create_event(
        scn.org, scn.room["id"], title="E", expected_attendance=5,
        start_at="2026-12-20T14:00:00Z", end_at="2026-12-20T15:00:00Z",
    )
    requester = make_org_requester_headers(scn.org["id"])

    # 1. OrgRequester cannot approve (Scheduler-only).
    denied_approve = api.approve_event(event["id"], requester)
    validate_error(denied_approve, ApiErrorId.ERR_FORBIDDEN)

    # 2. ServiceCoordinator cannot create rooms (FacilitiesManager-only).
    denied_room = api.create_room(
        {
            "name": "RBAC-2",
            "building_code": "RB",
            "capacity": 10,
            "internal_hourly_rate_cents": 1000,
            "student_hourly_rate_cents": 500,
            "external_hourly_rate_cents": 2000,
        },
        SERVICE_COORDINATOR,
    )
    validate_error(denied_room, ApiErrorId.ERR_FORBIDDEN)

    # The legitimate approval proceeds; the event spans no term dates.
    approved = approve_event(event["id"])
    assert approved["status"] == "APPROVED"

    order = create_order(
        event["id"], scn.org, category="AV", quantity=1,
        service_start_at="2026-12-20T13:30:00Z",
        service_end_at="2026-12-20T15:30:00Z",
    )

    # 3. Scheduler cannot quote (ServiceCoordinator-only).
    denied_quote = api.quote_service_order(
        order["id"], {"unit_cost_cents": 1000}, SCHEDULER
    )
    validate_error(denied_quote, ApiErrorId.ERR_FORBIDDEN)

    invoice = find_invoice_for_event(event["id"])

    # 4. FacilitiesManager cannot waive (FinanceAdmin-only).
    denied_waive = api.waive_invoice(
        invoice["id"], {"amount_cents": 100, "reason": "x"}, FACILITIES_MANAGER
    )
    validate_error(denied_waive, ApiErrorId.ERR_FORBIDDEN)

    # 5. FinanceAdmin cannot finalize (Scheduler-only).
    denied_finalize = api.finalize_scheduling_run(run["id"], FINANCE_ADMIN)
    validate_error(denied_finalize, ApiErrorId.ERR_FORBIDDEN)

    # Nothing moved: each denial left the target untouched.
    assert get_event(event["id"])["status"] == "APPROVED"
    assert get_order(order["id"])["status"] == "REQUESTED"
    assert get_run(run["id"])["status"] == "DRAFT"
    assert get_invoice(invoice["id"])["waived_cents"] == 0
