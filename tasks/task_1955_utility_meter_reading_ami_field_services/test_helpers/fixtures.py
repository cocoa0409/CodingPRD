"""Composite setup helpers for multi-step test prerequisites.

The harness restarts the API server before every test, so each helper builds
its preconditions from scratch using only PRD-declared endpoints. Setup calls
use get_success_data() (lenient) so failures surface as clear "Setup failed"
errors rather than confusing assertion failures deep inside a test.

Identity threading: FieldTechnician is entity-backed — every ownership-gated
call (route start/complete, stop reads, mark-no-read, skip-hazard, work-order
start/complete) is made with make_field_technician_headers(tech["id"]).
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    ami_read_payload,
    assign_route_payload,
    capture_read_payload,
    confirm_theft_payload,
    create_billing_period_payload,
    create_field_technician_payload,
    create_hazard_flag_payload,
    create_investigation_payload,
    create_meter_payload,
    create_ops_snapshot_payload,
    create_replacement_campaign_payload,
    create_route_payload,
    create_service_account_payload,
    create_work_order_payload,
    dispatch_work_order_payload,
    enroll_payload,
    install_meter_payload,
    mark_no_read_payload,
    set_clock_payload,
    skip_hazard_payload,
)
from .test_users import (
    TEST_USERS,
    make_field_technician_headers,
    make_investigator_headers,
)

ADMIN = TEST_USERS["meter_ops_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_liaison_headers"]
INVESTIGATOR = TEST_USERS["investigator_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-call happy-path helpers
# ---------------------------------------------------------------------------

def set_logical_clock(to_iso8601: str):
    """Drive the logical clock (PRD 2.4). Returns the 200 data payload."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN))


def create_technician(display_name: str = "Fixture Tech") -> dict:
    return get_success_data(
        api_client.create_field_technician(
            create_field_technician_payload(display_name=display_name), ADMIN
        ),
        201,
    )


def create_account(
    account_number: str,
    billing_cycle_code: str,
    service_address: str = "1 Fixture Way",
    estimation_method=None,
) -> dict:
    overrides = {}
    if estimation_method is not None:
        overrides["estimation_method"] = estimation_method
    return get_success_data(
        api_client.create_service_account(
            create_service_account_payload(
                account_number=account_number,
                service_address=service_address,
                billing_cycle_code=billing_cycle_code,
                **overrides,
            ),
            ADMIN,
        ),
        201,
    )


def create_meter(serial_number: str, meter_type: str = "HANDHELD") -> dict:
    return get_success_data(
        api_client.create_meter(
            create_meter_payload(serial_number=serial_number, meter_type=meter_type), ADMIN
        ),
        201,
    )


def install_meter_at_account(meter_id: str, account_id: str) -> dict:
    return get_success_data(
        api_client.install_meter(meter_id, install_meter_payload(account_id), ADMIN), 200
    )


def ingest_ami_read(meter_id: str, read_value: int, read_at: str) -> dict:
    """AMI head-end ingestion; the created AMI_REMOTE read is auto-validated."""
    return get_success_data(
        api_client.ingest_ami_read(meter_id, ami_read_payload(read_value, read_at), ADMIN),
        201,
    )


def create_billing_period(
    cycle_code: str,
    period_start_date: str,
    period_end_date: str,
    read_window_open_date: str,
    read_window_close_date: str,
    bill_run_date: str,
) -> dict:
    return get_success_data(
        api_client.create_billing_cycle_period(
            create_billing_period_payload(
                cycle_code=cycle_code,
                period_start_date=period_start_date,
                period_end_date=period_end_date,
                read_window_open_date=read_window_open_date,
                read_window_close_date=read_window_close_date,
                bill_run_date=bill_run_date,
            ),
            ADMIN,
        ),
        201,
    )


def open_period_window(period_id: str) -> dict:
    return get_success_data(api_client.open_read_window(period_id, BILLING), 200)


def close_period_window(period_id: str) -> dict:
    return get_success_data(api_client.close_read_window(period_id, BILLING), 200)


def finalize_period_billing(period_id: str) -> dict:
    return get_success_data(api_client.finalize_billing(period_id, BILLING), 200)


def close_billing_period(period_id: str) -> dict:
    return get_success_data(api_client.close_billing_period(period_id, BILLING), 200)


def create_route(
    period_id: str,
    scheduled_date: str,
    route_shift: str = "AM",
    two_person_crew=None,
) -> dict:
    overrides = {}
    if two_person_crew is not None:
        overrides["two_person_crew"] = two_person_crew
    return get_success_data(
        api_client.create_route(
            create_route_payload(
                period_id,
                scheduled_date=scheduled_date,
                route_shift=route_shift,
                **overrides,
            ),
            DISPATCHER,
        ),
        201,
    )


def get_route_stops(route_id: str) -> list:
    data, _meta = validate_paginated(api_client.list_route_stops(route_id, DISPATCHER))
    return data


def assign_route_to(route_id: str, technician_id: str) -> dict:
    return get_success_data(
        api_client.assign_route(route_id, assign_route_payload(technician_id), DISPATCHER),
        200,
    )


def start_route_as(route_id: str, technician_id: str) -> dict:
    return get_success_data(
        api_client.start_route(route_id, make_field_technician_headers(technician_id)), 200
    )


def complete_route_as(route_id: str, technician_id: str) -> dict:
    return get_success_data(
        api_client.complete_route(route_id, make_field_technician_headers(technician_id)), 200
    )


def capture_read_as_tech(
    stop_id: str,
    meter_id: str,
    read_value: int,
    read_at: str,
    expected_route_stop_version: int,
    technician_id: str,
    tamper_indication=None,
) -> dict:
    """Happy-path field capture by the assigned technician. Returns the MeterRead."""
    overrides = {}
    if tamper_indication is not None:
        overrides["tamper_indication"] = tamper_indication
    return get_success_data(
        api_client.capture_read(
            stop_id,
            capture_read_payload(
                meter_id,
                read_value,
                read_at,
                expected_route_stop_version,
                **overrides,
            ),
            make_field_technician_headers(technician_id),
        ),
        201,
    )


def mark_stop_no_read_as(stop_id: str, technician_id: str, reason: str = "NO_ACCESS") -> dict:
    return get_success_data(
        api_client.mark_no_read(
            stop_id,
            mark_no_read_payload(reason),
            make_field_technician_headers(technician_id),
        ),
        200,
    )


def skip_stop_for_hazard_as(stop_id: str, hazard_flag_id: str, technician_id: str) -> dict:
    return get_success_data(
        api_client.skip_hazard(
            stop_id,
            skip_hazard_payload(hazard_flag_id),
            make_field_technician_headers(technician_id),
        ),
        200,
    )


def generate_estimate_for_stop(stop_id: str) -> dict:
    return get_success_data(api_client.generate_estimate(stop_id, BILLING), 201)


def validate_meter_read(read_id: str) -> dict:
    return get_success_data(api_client.validate_read(read_id, BILLING), 200)


def report_hazard(
    service_account_id: str,
    technician_id: str,
    hazard_type: str = "DOG",
    severity: str = "HIGH",
) -> dict:
    return get_success_data(
        api_client.report_hazard_flag(
            create_hazard_flag_payload(
                service_account_id, hazard_type=hazard_type, severity=severity
            ),
            make_field_technician_headers(technician_id),
        ),
        201,
    )


def run_ops_snapshot(snapshot_at: str) -> dict:
    return get_success_data(
        api_client.create_ops_snapshot(create_ops_snapshot_payload(snapshot_at), ADMIN),
        201,
    )


def create_field_work_order(
    work_order_type: str,
    service_account_id: str,
    scheduled_date: str = "2026-08-10",
    work_shift: str = "AM",
    **refs,
) -> dict:
    return get_success_data(
        api_client.create_work_order(
            create_work_order_payload(
                work_order_type,
                service_account_id,
                scheduled_date=scheduled_date,
                work_shift=work_shift,
                **refs,
            ),
            DISPATCHER,
        ),
        201,
    )


def dispatch_order_to(work_order_id: str, technician_id: str) -> dict:
    return get_success_data(
        api_client.dispatch_work_order(
            work_order_id, dispatch_work_order_payload(technician_id), DISPATCHER
        ),
        200,
    )


def start_order_as(work_order_id: str, technician_id: str) -> dict:
    return get_success_data(
        api_client.start_work_order(work_order_id, make_field_technician_headers(technician_id)),
        200,
    )


def open_investigation(
    service_account_id: str,
    meter_id: str,
    indication_type: str = "TAMPER_FLAG",
    opened_by: str = "inv-fixture-1",
) -> dict:
    return get_success_data(
        api_client.create_investigation(
            create_investigation_payload(
                service_account_id, meter_id, indication_type=indication_type
            ),
            make_investigator_headers(opened_by),
        ),
        201,
    )


def advance_investigation_to_pending_disposition(investigation_id: str, user_id: str) -> dict:
    """OPEN -> EVIDENCE_GATHERING -> PENDING_DISPOSITION."""
    headers = make_investigator_headers(user_id)
    get_success_data(api_client.begin_evidence(investigation_id, headers), 200)
    return get_success_data(api_client.submit_disposition(investigation_id, headers), 200)


def get_meter(meter_id: str) -> dict:
    return get_success_data(api_client.get_meter(meter_id, ADMIN), 200)


def get_account(account_id: str) -> dict:
    return get_success_data(api_client.get_service_account(account_id, ADMIN), 200)


def get_stop(stop_id: str) -> dict:
    return get_success_data(api_client.get_route_stop(stop_id, DISPATCHER), 200)


def get_route(route_id: str) -> dict:
    return get_success_data(api_client.get_route(route_id, DISPATCHER), 200)


def get_read(read_id: str) -> dict:
    return get_success_data(api_client.get_read(read_id, BILLING), 200)


def get_work_order(work_order_id: str) -> dict:
    return get_success_data(api_client.get_work_order(work_order_id, DISPATCHER), 200)


def get_investigation(investigation_id: str) -> dict:
    return get_success_data(api_client.get_investigation(investigation_id, INVESTIGATOR), 200)


def get_campaign(campaign_id: str) -> dict:
    return get_success_data(api_client.get_replacement_campaign(campaign_id, ADMIN), 200)


def get_enrollment(enrollment_id: str) -> dict:
    return get_success_data(api_client.get_campaign_enrollment(enrollment_id, ADMIN), 200)


def get_hazard_flag(flag_id: str) -> dict:
    return get_success_data(api_client.get_hazard_flag(flag_id, DISPATCHER), 200)


def get_period(period_id: str) -> dict:
    return get_success_data(api_client.get_billing_cycle_period(period_id, ADMIN), 200)


# ---------------------------------------------------------------------------
# Tier 1/2: account+meter and period+route composites
# ---------------------------------------------------------------------------

def setup_account_with_installed_meter(
    account_number: str,
    cycle_code: str,
    meter_type: str = "HANDHELD",
    serial_number: str = None,
    estimation_method=None,
    service_address: str = "1 Fixture Way",
) -> tuple:
    """Create an ACTIVE account and an IN_SERVICE meter installed on it.

    Returns (account, meter).
    """
    account = create_account(
        account_number,
        cycle_code,
        service_address=service_address,
        estimation_method=estimation_method,
    )
    meter = create_meter(serial_number or f"{account_number}-M", meter_type)
    install_meter_at_account(meter["id"], account["id"])
    return get_account(account["id"]), get_meter(meter["id"])


def setup_open_period_with_route(
    cycle_code: str,
    period_start_date: str,
    period_end_date: str,
    read_window_open_date: str,
    read_window_close_date: str,
    bill_run_date: str,
    scheduled_date: str,
    route_shift: str = "AM",
    two_person_crew=None,
    open_clock=None,
) -> tuple:
    """Create a period, open its read window (optionally after moving the
    logical clock to open_clock), then create a route inside the window.

    Returns (period, route).
    """
    period = create_billing_period(
        cycle_code,
        period_start_date,
        period_end_date,
        read_window_open_date,
        read_window_close_date,
        bill_run_date,
    )
    if open_clock is not None:
        set_logical_clock(open_clock)
    open_period_window(period["id"])
    route = create_route(
        period["id"],
        scheduled_date,
        route_shift=route_shift,
        two_person_crew=two_person_crew,
    )
    return period, route


def setup_in_progress_route(
    cycle_code: str,
    period_start_date: str,
    period_end_date: str,
    read_window_open_date: str,
    read_window_close_date: str,
    bill_run_date: str,
    scheduled_date: str,
    route_shift: str = "AM",
    two_person_crew=None,
    open_clock=None,
    tech_name: str = "Route Tech",
) -> tuple:
    """Period + route + assigned ACTIVE technician + route started.

    Returns (period, route, stops, tech). Stops are the route's generated
    RouteStops in sequence order.
    """
    tech = create_technician(tech_name)
    period, route = setup_open_period_with_route(
        cycle_code,
        period_start_date,
        period_end_date,
        read_window_open_date,
        read_window_close_date,
        bill_run_date,
        scheduled_date,
        route_shift=route_shift,
        two_person_crew=two_person_crew,
        open_clock=open_clock,
    )
    stops = get_route_stops(route["id"])
    assign_route_to(route["id"], tech["id"])
    start_route_as(route["id"], tech["id"])
    return period, get_route(route["id"]), stops, tech


# ---------------------------------------------------------------------------
# Tier 4: AMI comms degradation / failure targeting
# ---------------------------------------------------------------------------

def drive_ami_meter_comms(meter_id: str, snapshot_ats: list) -> dict:
    """Run ops snapshots at the given instants (no AMI reads in between means
    each snapshot counts a missed day for every IN_SERVICE AMI meter)."""
    for at in snapshot_ats:
        run_ops_snapshot(at)
    return get_meter(meter_id)


def degrade_ami_meter(meter_id: str, first_snapshot: str, second_snapshot: str) -> dict:
    """Two consecutive missed snapshots leave an AMI meter DEGRADED (PRD 3.9
    step 2: a first miss moves COMMUNICATING -> DEGRADED, a second leaves it
    DEGRADED), which also makes the account eligible for route-stop generation
    (non-COMMUNICATING AMI endpoints are routed)."""
    return drive_ami_meter_comms(meter_id, [first_snapshot, second_snapshot])


def fail_ami_meter(
    meter_id: str,
    miss_snapshots: list,
) -> dict:
    """Drive an AMI meter to FAILED: three consecutive misses move it to
    NON_COMMUNICATING; once non_communicating_since is at least fourteen days
    before a later snapshot_at it flips to FAILED (boundary inclusive)."""
    return drive_ami_meter_comms(meter_id, miss_snapshots)


# ---------------------------------------------------------------------------
# Tier 3: estimation and campaign composites
# ---------------------------------------------------------------------------

def setup_ami_account_with_history(
    account_number: str,
    cycle_code: str,
    validated_reads: list,
    estimation_method=None,
    service_address: str = "1 History Way",
    degraded_snapshots=None,
) -> tuple:
    """AMI account + installed AMI meter + auto-validated AMI_REMOTE history.

    validated_reads: list of (read_value, read_at) ingested in order.
    degraded_snapshots: optional list of snapshot instants run AFTER ingestion
    (makes the meter non-COMMUNICATING so the account is routed).
    Returns (account, meter).
    """
    account, meter = setup_account_with_installed_meter(
        account_number,
        cycle_code,
        meter_type="AMI",
        estimation_method=estimation_method,
        service_address=service_address,
    )
    for value, at in validated_reads:
        ingest_ami_read(meter["id"], value, at)
    if degraded_snapshots:
        drive_ami_meter_comms(meter["id"], degraded_snapshots)
    return get_account(account["id"]), get_meter(meter["id"])


def setup_no_read_pending_stop(
    account_number: str,
    cycle_code: str,
    validated_reads: list,
    window_open: str,
    window_close: str,
    period_start: str,
    period_end: str,
    bill_run_date: str,
    scheduled_date: str,
    open_clock: str,
    estimation_method=None,
    degraded_snapshots=None,
) -> tuple:
    """AMI account with read history, meter degraded, period WINDOW_OPEN,
    route IN_PROGRESS, the account's stop marked NO_READ_PENDING.

    Returns (account, meter, period, route, stop, tech).
    """
    account, meter = setup_ami_account_with_history(
        account_number,
        cycle_code,
        validated_reads,
        estimation_method=estimation_method,
        degraded_snapshots=degraded_snapshots,
    )
    period, route, stops, tech = setup_in_progress_route(
        cycle_code,
        period_start,
        period_end,
        window_open,
        window_close,
        bill_run_date,
        scheduled_date,
        open_clock=open_clock,
    )
    stop = next(s for s in stops if s["service_account_id"] == account["id"])
    mark_stop_no_read_as(stop["id"], tech["id"])
    return account, meter, period, route, get_stop(stop["id"]), tech


def setup_failed_meter_in_open_campaign(
    account_number: str,
    cycle_code: str,
    miss_snapshots: list,
    campaign_name: str,
    quota: int,
    service_address: str = "1 Campaign Way",
) -> tuple:
    """AMI meter driven to FAILED, enrolled in an OPEN campaign; enrollment is
    WORK_ORDER_CREATED with its auto-created ENDPOINT_SWAP order.

    Returns (account, meter, campaign, enrollment).
    """
    account, meter = setup_account_with_installed_meter(
        account_number, cycle_code, meter_type="AMI", service_address=service_address
    )
    fail_ami_meter(meter["id"], miss_snapshots)
    campaign = get_success_data(
        api_client.create_replacement_campaign(
            create_replacement_campaign_payload(campaign_name=campaign_name, quota=quota),
            ADMIN,
        ),
        201,
    )
    get_success_data(api_client.open_campaign(campaign["id"], ADMIN), 200)
    enrollments = get_success_data(
        api_client.enroll_meters(campaign["id"], enroll_payload([meter["id"]]), ADMIN),
        201,
    )
    enrollment = enrollments[0]
    return account, get_meter(meter["id"]), get_campaign(campaign["id"]), enrollment
