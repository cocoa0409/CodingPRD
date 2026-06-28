"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "Setup failed" errors rather than confusing assertion failures. Each
fixture builds all of its preconditions from scratch via PRD-declared endpoints,
because the harness restarts the server (empty DB) before every test.

Identity threading: AccountHolder and Inspector are entity_backed roles, so any
ownership-gated call uses make_account_holder_headers(account_id) /
make_inspector_headers(inspector_id) with the real entity id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_account_payload, create_vehicle_payload, create_fee_schedule_payload,
    create_inspector_payload, create_order_payload, create_assignment_payload,
    create_report_payload, create_photo_payload, create_history_record_payload,
    create_recall_payload, create_dispute_payload,
)
from .test_users import (
    TEST_USERS, make_account_holder_headers, make_inspector_headers,
)

OPS = TEST_USERS["ops_admin_headers"]


# ---------------------------------------------------------------------------
# Clock control
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str):
    """Set the server logical clock. Returns nothing (output is null)."""
    api_client.set_clock(to_iso8601, OPS)


# ---------------------------------------------------------------------------
# Tier 1: Reference-data creators
# ---------------------------------------------------------------------------
def create_fee_schedule(**overrides) -> dict:
    return get_success_data(api_client.create_fee_schedule(create_fee_schedule_payload(**overrides), OPS))


def create_account(**overrides) -> dict:
    return get_success_data(api_client.create_account(create_account_payload(**overrides), OPS))


def create_vehicle(**overrides) -> dict:
    return get_success_data(api_client.create_vehicle(create_vehicle_payload(**overrides), OPS))


def create_inspector(**overrides) -> dict:
    return get_success_data(api_client.create_inspector(create_inspector_payload(**overrides), OPS))


def create_recall(year, make, model, **overrides) -> dict:
    return get_success_data(api_client.create_recall(create_recall_payload(year, make, model, **overrides), OPS))


def add_history_record(vehicle_id, record_type, event_date, **overrides) -> dict:
    return get_success_data(api_client.add_history_record(
        vehicle_id, create_history_record_payload(record_type, event_date, **overrides), OPS))


def create_draft_order(account, vehicle, fee_schedule, **overrides) -> dict:
    """Create a DRAFT order owned by `account`. Returns the order."""
    payload = create_order_payload(account["id"], vehicle["id"], fee_schedule["id"], **overrides)
    return get_success_data(api_client.create_order(payload, make_account_holder_headers(account["id"])))


# ---------------------------------------------------------------------------
# Tier 2: Common reference-data bundle
# ---------------------------------------------------------------------------
def setup_reference_data(fee_overrides=None, account_overrides=None,
                         vehicle_overrides=None, inspector_overrides=None):
    """Create one fee schedule, account, vehicle, and inspector.

    Returns (fee_schedule, account, vehicle, inspector).
    """
    fs = create_fee_schedule(**(fee_overrides or {}))
    acct = create_account(**(account_overrides or {}))
    veh = create_vehicle(**(vehicle_overrides or {}))
    insp = create_inspector(**(inspector_overrides or {}))
    return fs, acct, veh, insp


# ---------------------------------------------------------------------------
# Tier 3: Dispatch / report lifecycle shortcuts
# ---------------------------------------------------------------------------
def offer_assignment(order, inspector, **overrides) -> dict:
    """Offer (create) a dispatch assignment for `order` to `inspector`.

    Uses the order's current version as expected_order_version unless overridden.
    Returns the OFFERED assignment.
    """
    expected_version = overrides.pop("expected_order_version", order["version"])
    payload = create_assignment_payload(order["id"], inspector["id"], expected_version, **overrides)
    return get_success_data(api_client.create_assignment(payload, OPS))


def offer_and_accept(order, inspector, **overrides):
    """Offer an assignment and have the inspector accept it (order -> DISPATCHED).

    Returns (assignment_after_accept, refreshed_order).
    """
    asg = offer_assignment(order, inspector, **overrides)
    accepted = get_success_data(
        api_client.accept_assignment(asg["id"], make_inspector_headers(inspector["id"])))
    refreshed_order = get_success_data(api_client.get_order(order["id"], OPS))
    return accepted, refreshed_order


def create_dispatched_order(account, vehicle, fee_schedule, inspector,
                            order_overrides=None, asg_overrides=None):
    """DRAFT order -> offer -> accept (DISPATCHED). Returns (order, assignment)."""
    order = create_draft_order(account, vehicle, fee_schedule, **(order_overrides or {}))
    asg, order = offer_and_accept(order, inspector, **(asg_overrides or {}))
    return order, asg


def create_report_for(order, assignment, **report_overrides) -> dict:
    """Create a DRAFT report for a dispatched order (order -> IN_PROGRESS).

    Authored by the inspector who holds the assignment.
    """
    insp_headers = make_inspector_headers(assignment["inspector_id"])
    payload = create_report_payload(order["id"], assignment["id"], **report_overrides)
    return get_success_data(api_client.create_report(payload, insp_headers))


def add_photo(report, inspector_id, **photo_overrides) -> dict:
    return get_success_data(api_client.add_report_photo(
        report["id"], create_photo_payload(**photo_overrides), make_inspector_headers(inspector_id)))


def submit_report(report, inspector_id) -> dict:
    return get_success_data(api_client.submit_report(report["id"], make_inspector_headers(inspector_id)))


def create_reported_order(account, vehicle, fee_schedule, inspector,
                          order_overrides=None, asg_overrides=None, report_overrides=None):
    """Walk an order all the way to REPORTED with a SUBMITTED report.

    Returns (order_after_report, assignment, report).
    """
    order, asg = create_dispatched_order(
        account, vehicle, fee_schedule, inspector,
        order_overrides=order_overrides, asg_overrides=asg_overrides)
    report = create_report_for(order, asg, **(report_overrides or {}))
    submit_report(report, inspector["id"])
    refreshed_report = get_success_data(api_client.get_report(report["id"], OPS))
    refreshed_order = get_success_data(api_client.get_order(order["id"], OPS))
    return refreshed_order, asg, refreshed_report


def compile_vin_report(order) -> dict:
    return get_success_data(api_client.create_vin_report({"order_id": order["id"]}, OPS))


def pay_order(order, account_id) -> dict:
    return get_success_data(api_client.pay_order(order["id"], make_account_holder_headers(account_id)))


def invoice_order(order) -> dict:
    return get_success_data(api_client.invoice_order(order["id"], OPS))


def deliver_order(order) -> dict:
    return get_success_data(api_client.deliver_order(order["id"], OPS))


# ---------------------------------------------------------------------------
# Tier 4: Full delivered-order lifecycles (the fee / dispute scenarios)
# ---------------------------------------------------------------------------
def setup_delivered_order(account_overrides=None, fee_overrides=None,
                          order_overrides=None, asg_overrides=None,
                          report_overrides=None,
                          ordered_at=None, delivered_at=None,
                          pay=True, invoice=False, compile_vin=None,
                          inspector_overrides=None):
    """Build a fully DELIVERED order, controlling the clock for late/on-time.

    Sequence: [set clock to ordered_at] -> reference data -> order -> dispatch ->
    accept -> report -> submit -> [vin report if include_vin_history] ->
    [pay or invoice] -> [advance clock to delivered_at] -> deliver.

    Returns dict with keys: fee_schedule, account, vehicle, inspector, order,
    assignment, report, delivered_order.
    """
    fee_overrides = fee_overrides or {}
    account_overrides = account_overrides or {}
    order_overrides = order_overrides or {}
    inspector_overrides = inspector_overrides or {}

    if ordered_at is not None:
        set_clock(ordered_at)

    fs = create_fee_schedule(**fee_overrides)
    acct = create_account(**account_overrides)
    veh = create_vehicle()
    insp = create_inspector(**inspector_overrides)

    order, asg, report = create_reported_order(
        acct, veh, fs, insp,
        order_overrides=order_overrides, asg_overrides=asg_overrides,
        report_overrides=report_overrides)

    include_vin = order_overrides.get("include_vin_history", False)
    if compile_vin is None:
        compile_vin = include_vin
    if compile_vin:
        compile_vin_report(order)

    if invoice:
        invoice_order(order)
    elif pay:
        pay_order(order, acct["id"])

    if delivered_at is not None:
        set_clock(delivered_at)

    delivered = deliver_order(order)
    return {
        "fee_schedule": fs, "account": acct, "vehicle": veh, "inspector": insp,
        "order": order, "assignment": asg, "report": report,
        "delivered_order": delivered,
    }


def setup_dispute(reason, claimed_cents, account_id, order, report,
                  start_review=True):
    """File a dispute on a delivered order; optionally move it to UNDER_REVIEW.

    Returns the dispute (after start-review if requested).
    """
    payload = create_dispute_payload(order["id"], report["id"], reason, claimed_cents)
    dispute = get_success_data(api_client.create_dispute(payload, make_account_holder_headers(account_id)))
    if start_review:
        dispute = get_success_data(api_client.start_review_dispute(dispute["id"], OPS))
    return dispute
