"""Composite setup helpers.

Every helper builds its preconditions from scratch through the documented
endpoints, because each test starts against an empty database. Setup calls use
the lenient ``get_success_data`` validator so a broken precondition reads as a
setup failure rather than as a confusing assertion failure inside a test.
"""

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .api_client import api_client
from .test_users import (
    DUAL_ROLE_OPERATOR_ID,
    INSPECTOR_ONE_ID,
    OFFICER_CERTIFIER_ID,
    OFFICER_SIGNER_ID,
    TEST_USERS,
    make_casing_inspector_headers,
    make_compliance_officer_headers,
    make_fleet_manager_headers,
    make_tire_technician_headers,
)

ADMIN = TEST_USERS["dealer_admin_headers"]
TECH = TEST_USERS["tire_technician_headers"]
INSPECTOR = TEST_USERS["casing_inspector_headers"]
SCHEDULER = TEST_USERS["plant_scheduler_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]
DISPATCHER = TEST_USERS["dispatch_coordinator_headers"]


# ==========================================================================
# Primitive creators
# ==========================================================================

def create_location(**overrides) -> dict:
    return get_success_data(
        api_client.create_service_location(f.service_location_payload(**overrides), ADMIN)
    )


def create_fleet(location_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_fleet_account(
            f.fleet_account_payload(location_id, **overrides), ADMIN
        )
    )


def create_agreement(fleet_id: str, activate: bool = True, **overrides) -> dict:
    agreement = get_success_data(
        api_client.create_national_agreement(
            f.national_agreement_payload(fleet_id, **overrides), ADMIN
        )
    )
    if activate:
        agreement = get_success_data(
            api_client.activate_national_agreement(agreement["id"], {}, ADMIN)
        )
    return agreement


def create_policy(fleet_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_tire_policy(fleet_id, f.tire_policy_payload(**overrides), ADMIN)
    )


def create_vehicle(fleet_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_vehicle(fleet_id, f.vehicle_payload(**overrides), ADMIN)
    )


def create_technician(location_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_technician(location_id, f.technician_payload(**overrides), ADMIN)
    )


def create_retread_line(location_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_retread_line(
            location_id, f.retread_line_payload(**overrides), ADMIN
        )
    )


def create_casing(fleet_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_casing(f.casing_payload(fleet_id, **overrides), ADMIN)
    )


def create_tire_asset(fleet_id: str, casing_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_tire_asset(
            f.tire_asset_payload(fleet_id, casing_id, **overrides), ADMIN
        )
    )


def create_manifest(location_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_scrap_manifest(
            location_id, f.scrap_manifest_payload(**overrides), OFFICER
        )
    )


def set_clock(current_utc: str) -> dict:
    """Move the server's logical UTC clock."""
    return get_success_data(api_client.set_clock(f.clock_payload(current_utc), ADMIN))


def suspend_fleet(fleet_id: str, reason: str = "Past due balance") -> dict:
    return get_success_data(
        api_client.set_fleet_account_status(
            fleet_id, f.fleet_status_payload("SUSPENDED", reason), ADMIN
        )
    )


def reinstate_fleet(fleet_id: str, reason: str = "Payment received") -> dict:
    return get_success_data(
        api_client.set_fleet_account_status(
            fleet_id, f.fleet_status_payload("ACTIVE", reason), ADMIN
        )
    )


def take_line_down(line_id: str) -> dict:
    return get_success_data(
        api_client.set_retread_line_status(
            line_id, f.retread_line_status_payload("DOWN"), ADMIN
        )
    )


def return_line_to_service(line_id: str) -> dict:
    return get_success_data(
        api_client.set_retread_line_status(
            line_id, f.retread_line_status_payload("AVAILABLE"), ADMIN
        )
    )


def set_technician_off_duty(technician_id: str) -> dict:
    return get_success_data(
        api_client.set_technician_status(
            technician_id, f.technician_status_payload("OFF_DUTY"), ADMIN
        )
    )


def set_technician_available(technician_id: str) -> dict:
    return get_success_data(
        api_client.set_technician_status(
            technician_id, f.technician_status_payload("AVAILABLE"), ADMIN
        )
    )


# ==========================================================================
# Readers (side-effect verification)
# ==========================================================================

def read_location(location_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_service_location(location_id, headers or ADMIN))


def read_fleet(fleet_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_fleet_account(fleet_id, headers or ADMIN))


def read_agreement(agreement_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_national_agreement(agreement_id, headers or ADMIN)
    )


def read_policy(policy_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_tire_policy(policy_id, headers or ADMIN))


def read_vehicle(vehicle_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_vehicle(vehicle_id, headers or ADMIN))


def read_casing(casing_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_casing(casing_id, headers or ADMIN))


def read_tire_asset(asset_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_tire_asset(asset_id, headers or ADMIN))


def read_line(line_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_retread_line(line_id, headers or ADMIN))


def read_job(job_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_retread_job(job_id, headers or ADMIN))


def read_technician(technician_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_technician(technician_id, headers or ADMIN))


def read_call(call_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_road_service_call(call_id, headers or ADMIN))


def read_manifest(manifest_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_scrap_manifest(manifest_id, headers or ADMIN))


def read_invoice(invoice_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_cross_location_invoice(invoice_id, headers or ADMIN)
    )


def list_ledger(fleet_id: str, headers=None, **filters) -> list:
    params = {"fleet_account_id": fleet_id, "limit": 100}
    params.update(filters)
    data, _meta = validate_paginated(
        api_client.list_casing_credit_entries(headers or ADMIN, params=params)
    )
    return data


def list_casing_ledger(casing_id: str, headers=None) -> list:
    data, _meta = validate_paginated(
        api_client.list_casing_credit_entries(
            headers or ADMIN, params={"casing_id": casing_id, "limit": 100}
        )
    )
    return data


def list_surveys_for(asset_id: str, headers=None):
    return validate_paginated(
        api_client.list_tire_surveys(
            headers or ADMIN, params={"tire_asset_id": asset_id, "limit": 100}
        )
    )


def list_assets_for_casing(casing_id: str, headers=None) -> list:
    data, _meta = validate_paginated(
        api_client.list_tire_assets(
            headers or ADMIN, params={"casing_id": casing_id, "limit": 100}
        )
    )
    return data


def count_invoices(fleet_id: str, headers=None) -> int:
    _data, meta = validate_paginated(
        api_client.list_cross_location_invoices(
            headers or ADMIN, params={"fleet_account_id": fleet_id}
        )
    )
    return meta["total_count"]


def count_jobs_for_casing(casing_id: str, headers=None) -> int:
    _data, meta = validate_paginated(
        api_client.list_retread_jobs(headers or ADMIN, params={"casing_id": casing_id})
    )
    return meta["total_count"]


# ==========================================================================
# Tier 1: state progression on a single entity
# ==========================================================================

def collect_casing(casing_id: str, location_id: str) -> dict:
    """Advance a casing ON_WHEEL -> COLLECTED into a location's holding area."""
    return get_success_data(
        api_client.collect_casing(
            casing_id, f.collect_casing_payload(location_id), TECH
        )
    )


def inspect_casing(
    casing_id: str,
    grade: str,
    expected_casing_version: int,
    inspector_user_id: str = INSPECTOR_ONE_ID,
) -> dict:
    """Record an inspection grade under an explicit inspector identifier."""
    return get_success_data(
        api_client.inspect_casing(
            casing_id,
            f.inspect_casing_payload(grade, expected_casing_version),
            make_casing_inspector_headers(inspector_user_id),
        )
    )


def create_collected_casing(fleet_id: str, location_id: str, **overrides) -> dict:
    """Register a casing and collect it. Returns the COLLECTED casing."""
    casing = create_casing(fleet_id, **overrides)
    return collect_casing(casing["id"], location_id)


def create_inspected_casing(
    fleet_id: str,
    location_id: str,
    grade: str = "B",
    inspector_user_id: str = INSPECTOR_ONE_ID,
    **overrides,
) -> dict:
    """Register, collect and grade a casing. Returns the INSPECTED casing."""
    collected = create_collected_casing(fleet_id, location_id, **overrides)
    return inspect_casing(
        collected["id"], grade, collected["version"], inspector_user_id
    )


def create_condemned_casing(
    fleet_id: str,
    location_id: str,
    inspector_user_id: str = INSPECTOR_ONE_ID,
    **overrides,
) -> dict:
    """Register, collect and grade REJECT. Returns a REJECTED casing that never
    accrued any credit."""
    collected = create_collected_casing(fleet_id, location_id, **overrides)
    return inspect_casing(
        collected["id"], "REJECT", collected["version"], inspector_user_id
    )


def create_condemned_casing_with_credit(
    fleet_id: str,
    location_id: str,
    grade: str = "B",
    inspector_user_id: str = INSPECTOR_ONE_ID,
    **overrides,
) -> dict:
    """Grade a casing, then condemn it. The accrued credit stays standing on the
    fleet balance until destruction is certified."""
    inspected = create_inspected_casing(
        fleet_id, location_id, grade, inspector_user_id, **overrides
    )
    return get_success_data(
        api_client.reject_casing(
            inspected["id"],
            f.reject_casing_payload(),
            make_casing_inspector_headers(inspector_user_id),
        )
    )


def create_mounted_asset(
    fleet_id: str,
    casing_id: str,
    vehicle_id: str,
    mounted_at: str = "2026-08-02T08:00:00Z",
    odometer_at_mount: int = 100000,
    tread_depth_at_mount_32nds: int = 24,
    position: str = "DRIVE",
    **asset_overrides,
) -> dict:
    """Register a tire asset and mount it. Returns the MOUNTED asset."""
    asset = create_tire_asset(fleet_id, casing_id, **asset_overrides)
    return get_success_data(
        api_client.mount_tire_asset(
            asset["id"],
            f.mount_payload(
                vehicle_id,
                mounted_at,
                odometer_at_mount,
                tread_depth_at_mount_32nds,
                position,
            ),
            TECH,
        )
    )


def record_survey(
    asset_id: str,
    surveyed_at: str,
    pressure_psi: float,
    tread_depth_32nds: int,
    odometer_miles: int,
    technician_id: str = None,
) -> dict:
    headers = make_tire_technician_headers(technician_id) if technician_id else TECH
    return get_success_data(
        api_client.create_tire_survey(
            asset_id,
            f.survey_payload(
                surveyed_at, pressure_psi, tread_depth_32nds, odometer_miles
            ),
            headers,
        )
    )


# ==========================================================================
# Tier 2: the fleet program hierarchy
# ==========================================================================

def setup_fleet_program(
    with_agreement: bool = False,
    activate_agreement: bool = True,
    agreement_overrides: dict = None,
    policy_overrides: dict = None,
    location_overrides: dict = None,
    fleet_overrides: dict = None,
    with_policy: bool = True,
) -> dict:
    """One location, one fleet, its governing DRIVE policy and optionally a
    national agreement.

    Returns a dict with keys ``location``, ``fleet``, ``policy`` and
    ``agreement`` (the last two may be ``None``).
    """
    location = create_location(**(location_overrides or {}))
    fleet = create_fleet(location["id"], **(fleet_overrides or {}))
    agreement = None
    if with_agreement:
        agreement = create_agreement(
            fleet["id"], activate=activate_agreement, **(agreement_overrides or {})
        )
    policy = None
    if with_policy:
        policy = create_policy(fleet["id"], **(policy_overrides or {}))
    return {
        "location": location,
        "fleet": fleet,
        "policy": policy,
        "agreement": agreement,
    }


def setup_national_account_program(
    tier_discount_pct: float = 0.125,
    casing_credit_rate_cents: int = 15000,
    **agreement_overrides,
) -> dict:
    """A NATIONAL_ACCOUNT / CROSS_LOCATION fleet with an ACTIVE agreement."""
    overrides = {
        "tier_discount_pct": tier_discount_pct,
        "casing_credit_rate_cents": casing_credit_rate_cents,
    }
    overrides.update(agreement_overrides)
    return setup_fleet_program(
        with_agreement=True,
        agreement_overrides=overrides,
        fleet_overrides={
            "account_type": "NATIONAL_ACCOUNT",
            "billing_mode": "CROSS_LOCATION",
        },
    )


def setup_plant_program(
    line_count: int = 1,
    cure_cooldown_minutes: int = None,
    with_agreement: bool = False,
    agreement_overrides: dict = None,
    policy_overrides: dict = None,
) -> dict:
    """A fleet program plus ``line_count`` retread production lines.

    Returns the program dict with an extra ``lines`` list.
    """
    program = setup_fleet_program(
        with_agreement=with_agreement,
        agreement_overrides=agreement_overrides,
        policy_overrides=policy_overrides,
        location_overrides={"is_retread_plant": True},
    )
    line_overrides = {}
    if cure_cooldown_minutes is not None:
        line_overrides["cure_cooldown_minutes"] = cure_cooldown_minutes
    program["lines"] = [
        create_retread_line(program["location"]["id"], **line_overrides)
        for _ in range(line_count)
    ]
    program["line"] = program["lines"][0]
    return program


# ==========================================================================
# Tier 3: retread job lifecycle shortcuts
# ==========================================================================

def schedule_retread_job(
    casing_id: str,
    line_id: str,
    scheduled_start_at: str = "2026-08-20T08:00:00Z",
    scheduled_end_at: str = "2026-08-20T12:00:00Z",
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_retread_job(
            f.retread_job_payload(
                casing_id, line_id, scheduled_start_at, scheduled_end_at, **overrides
            ),
            SCHEDULER,
        )
    )


def setup_scheduled_job(
    grade: str = "B",
    retread_count: int = 0,
    scheduled_start_at: str = "2026-08-20T08:00:00Z",
    scheduled_end_at: str = "2026-08-20T12:00:00Z",
    with_agreement: bool = False,
    agreement_overrides: dict = None,
    policy_overrides: dict = None,
    cure_cooldown_minutes: int = None,
    inspector_user_id: str = INSPECTOR_ONE_ID,
) -> dict:
    """A graded casing booked onto an AVAILABLE line.

    Returns the plant program dict plus ``casing`` and ``job``.
    """
    program = setup_plant_program(
        line_count=1,
        cure_cooldown_minutes=cure_cooldown_minutes,
        with_agreement=with_agreement,
        agreement_overrides=agreement_overrides,
        policy_overrides=policy_overrides,
    )
    casing = create_inspected_casing(
        program["fleet"]["id"],
        program["location"]["id"],
        grade=grade,
        inspector_user_id=inspector_user_id,
        retread_count=retread_count,
    )
    program["casing"] = casing
    program["job"] = schedule_retread_job(
        casing["id"], program["line"]["id"], scheduled_start_at, scheduled_end_at
    )
    return program


def start_job(job_id: str, started_at: str = "2026-08-20T08:00:00Z") -> dict:
    return get_success_data(
        api_client.start_retread_job(job_id, f.start_job_payload(started_at), SCHEDULER)
    )


def setup_job_in_production(
    started_at: str = "2026-08-20T08:00:00Z", **kwargs
) -> dict:
    """A retread job walked all the way to IN_PRODUCTION."""
    program = setup_scheduled_job(**kwargs)
    program["job"] = start_job(program["job"]["id"], started_at)
    return program


def complete_job(
    job_id: str,
    completed_at: str = "2026-08-20T11:00:00Z",
    cost_basis_cents: int = 28000,
) -> dict:
    return get_success_data(
        api_client.complete_retread_job(
            job_id, f.complete_job_payload(completed_at, cost_basis_cents), SCHEDULER
        )
    )


def fail_cure(job_id: str, failure_reason: str, **overrides) -> dict:
    return get_success_data(
        api_client.fail_cure_retread_job(
            job_id, f.fail_cure_payload(failure_reason, **overrides), SCHEDULER
        )
    )


def setup_failed_cure_job(failure_reason: str = "CURE_DEFECT", **kwargs) -> dict:
    """A retread job walked to FAILED_CURE under the requested failure reason."""
    program = setup_job_in_production(**kwargs)
    program["job"] = fail_cure(program["job"]["id"], failure_reason)
    return program


# ==========================================================================
# Tier 4: accumulation and threshold targeting
# ==========================================================================

def setup_line_with_occupied_slot(
    incumbent_start: str = "2026-08-20T08:00:00Z",
    incumbent_end: str = "2026-08-20T12:00:00Z",
    line_count: int = 1,
    cure_cooldown_minutes: int = None,
    grade: str = "B",
) -> dict:
    """A line already carrying one SCHEDULED job, so the next booking has to
    clear the incumbent's slot plus the line's cure cooldown.

    Returns the plant program dict plus ``incumbent_casing`` and
    ``incumbent_job``.
    """
    program = setup_plant_program(
        line_count=line_count, cure_cooldown_minutes=cure_cooldown_minutes
    )
    incumbent_casing = create_inspected_casing(
        program["fleet"]["id"], program["location"]["id"], grade=grade
    )
    program["incumbent_casing"] = incumbent_casing
    program["incumbent_job"] = schedule_retread_job(
        incumbent_casing["id"], program["line"]["id"], incumbent_start, incumbent_end
    )
    return program


def accrue_casing_credit(
    fleet_id: str,
    location_id: str,
    grade: str = "B",
    retread_count: int = 0,
    inspector_user_id: str = INSPECTOR_ONE_ID,
    **casing_overrides,
) -> dict:
    """Grade one casing so the fleet carries a known credit balance."""
    return create_inspected_casing(
        fleet_id,
        location_id,
        grade=grade,
        inspector_user_id=inspector_user_id,
        retread_count=retread_count,
        **casing_overrides,
    )


# ==========================================================================
# Tier 3b: the road service ladder
# ==========================================================================

def open_call(
    fleet_id: str,
    vehicle_id: str,
    location_id: str,
    reported_at: str,
    priority: str = "NORMAL",
    headers=None,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_road_service_call(
            f.road_service_call_payload(
                fleet_id, vehicle_id, location_id, reported_at, priority, **overrides
            ),
            headers or DISPATCHER,
        )
    )


def dispatch_call(
    call_id: str, dispatched_at: str, dispatch_miles: int, technician_id: str = None
) -> dict:
    payload = f.dispatch_payload(dispatched_at, dispatch_miles)
    if technician_id is not None:
        payload["technician_id"] = technician_id
    return get_success_data(
        api_client.dispatch_road_service_call(call_id, payload, DISPATCHER)
    )


def arrive_call(call_id: str, arrived_at: str, technician_id: str) -> dict:
    return get_success_data(
        api_client.arrive_road_service_call(
            call_id,
            f.arrive_payload(arrived_at),
            make_tire_technician_headers(technician_id),
        )
    )


def complete_call(
    call_id: str, closed_at: str, labor_hours: float, technician_id: str, **overrides
) -> dict:
    return get_success_data(
        api_client.complete_road_service_call(
            call_id,
            f.complete_call_payload(closed_at, labor_hours, **overrides),
            make_tire_technician_headers(technician_id),
        )
    )


def run_completed_call(
    fleet_id: str,
    vehicle_id: str,
    location_id: str,
    technician_id: str,
    reported_at: str,
    dispatched_at: str,
    arrived_at: str,
    closed_at: str,
    labor_hours: float,
    dispatch_miles: int,
    priority: str = "NORMAL",
    **complete_overrides,
) -> dict:
    """Walk one call from OPEN through DISPATCHED and ON_SITE to COMPLETED."""
    call = open_call(fleet_id, vehicle_id, location_id, reported_at, priority)
    dispatch_call(call["id"], dispatched_at, dispatch_miles, technician_id)
    arrive_call(call["id"], arrived_at, technician_id)
    return complete_call(
        call["id"], closed_at, labor_hours, technician_id, **complete_overrides
    )


# The two reusable billable lines. Under a NORMAL daytime call with no
# surcharge and a met commitment, the base charge of 9500 cents plus the
# standard labour rate and the mileage charge give a stable per-line figure:
#   0.25 h and 2 miles  -> 9500 + 2750 + 570  = 12820 cents
#   0.50 h and 4 miles  -> 9500 + 5500 + 1140 = 16140 cents
SMALL_LINE_CENTS = 12820
LARGE_LINE_CENTS = 16140


def setup_billable_call(
    program: dict,
    technician_id: str = None,
    labor_hours: float = 0.25,
    dispatch_miles: int = 2,
    reported_at: str = "2026-08-05T13:00:00Z",
    dispatched_at: str = "2026-08-05T13:05:00Z",
    arrived_at: str = "2026-08-05T13:30:00Z",
    closed_at: str = "2026-08-05T14:00:00Z",
    priority: str = "NORMAL",
    vehicle_id: str = None,
    **complete_overrides,
) -> dict:
    """One COMPLETED, UNBILLED call ready to be rolled into an invoice."""
    if technician_id is None:
        technician_id = create_technician(program["location"]["id"])["id"]
    if vehicle_id is None:
        vehicle_id = create_vehicle(program["fleet"]["id"])["id"]
    return run_completed_call(
        program["fleet"]["id"],
        vehicle_id,
        program["location"]["id"],
        technician_id,
        reported_at,
        dispatched_at,
        arrived_at,
        closed_at,
        labor_hours,
        dispatch_miles,
        priority,
        **complete_overrides,
    )


def setup_two_billable_calls(program: dict) -> list:
    """Two COMPLETED NORMAL calls worth 12820 and 16140 cents respectively."""
    technician = create_technician(program["location"]["id"])
    first = setup_billable_call(
        program,
        technician_id=technician["id"],
        labor_hours=0.25,
        dispatch_miles=2,
        reported_at="2026-08-05T13:00:00Z",
        dispatched_at="2026-08-05T13:05:00Z",
        arrived_at="2026-08-05T13:30:00Z",
        closed_at="2026-08-05T14:00:00Z",
    )
    second = setup_billable_call(
        program,
        technician_id=technician["id"],
        labor_hours=0.5,
        dispatch_miles=4,
        reported_at="2026-08-06T13:00:00Z",
        dispatched_at="2026-08-06T13:05:00Z",
        arrived_at="2026-08-06T13:30:00Z",
        closed_at="2026-08-06T14:00:00Z",
    )
    return [first, second]


# ==========================================================================
# Tier 5: billing and terminal states
# ==========================================================================

def create_invoice(
    fleet_id: str,
    billing_period_start: str = "2026-08-01",
    billing_period_end: str = "2026-08-31",
    expected_fleet_account_version: int = None,
    headers=None,
) -> dict:
    if expected_fleet_account_version is None:
        expected_fleet_account_version = read_fleet(fleet_id, CLERK)["version"]
    return get_success_data(
        api_client.create_cross_location_invoice(
            f.invoice_payload(
                fleet_id,
                billing_period_start,
                billing_period_end,
                expected_fleet_account_version,
            ),
            headers or CLERK,
        )
    )


def submit_invoice(invoice_id: str) -> dict:
    return get_success_data(
        api_client.submit_cross_location_invoice(invoice_id, {}, CLERK)
    )


def settle_invoice(invoice_id: str, paid_amount_cents: int) -> dict:
    return get_success_data(
        api_client.settle_cross_location_invoice(
            invoice_id, f.settle_invoice_payload(paid_amount_cents), CLERK
        )
    )


def dispute_invoice(invoice_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.dispute_cross_location_invoice(
            invoice_id, f.dispute_invoice_payload(), headers or CLERK
        )
    )


def setup_open_invoice(
    tier_discount_pct: float = 0.125,
    casing_credit_rate_cents: int = 15000,
    credit_grade: str = None,
    line_count: int = 1,
) -> dict:
    """A national account with billable work rolled into one OPEN invoice.

    Returns the program dict plus ``calls``, ``credit_casing`` and ``invoice``.
    """
    program = setup_national_account_program(
        tier_discount_pct=tier_discount_pct,
        casing_credit_rate_cents=casing_credit_rate_cents,
    )
    if line_count == 2:
        program["calls"] = setup_two_billable_calls(program)
    else:
        program["calls"] = [setup_billable_call(program)]
    program["credit_casing"] = None
    if credit_grade is not None:
        program["credit_casing"] = accrue_casing_credit(
            program["fleet"]["id"], program["location"]["id"], grade=credit_grade
        )
    program["invoice"] = create_invoice(program["fleet"]["id"])
    return program


def setup_submitted_invoice(**kwargs) -> dict:
    """The same rollup walked one step further, to SUBMITTED, which is where the
    credit is actually consumed."""
    program = setup_open_invoice(**kwargs)
    program["invoice"] = submit_invoice(program["invoice"]["id"])
    return program


# ==========================================================================
# Scrap compliance lifecycle
# ==========================================================================

def add_manifest_line(manifest_id: str, casing_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.add_scrap_manifest_line(
            manifest_id, f.manifest_line_payload(casing_id), headers or OFFICER
        )
    )


def sign_manifest(
    manifest_id: str,
    signed_at: str = "2026-08-10T09:00:00Z",
    officer_user_id: str = OFFICER_SIGNER_ID,
) -> dict:
    return get_success_data(
        api_client.sign_scrap_manifest(
            manifest_id,
            f.sign_manifest_payload(signed_at),
            make_compliance_officer_headers(officer_user_id),
        )
    )


def transport_manifest(
    manifest_id: str,
    transported_at: str = "2026-08-10T12:00:00Z",
    officer_user_id: str = OFFICER_SIGNER_ID,
) -> dict:
    return get_success_data(
        api_client.transport_scrap_manifest(
            manifest_id,
            f.transport_manifest_payload(transported_at),
            make_compliance_officer_headers(officer_user_id),
        )
    )


def certify_destruction(
    manifest_id: str,
    certified_at: str = "2026-08-11T09:00:00Z",
    officer_user_id: str = OFFICER_CERTIFIER_ID,
) -> dict:
    return get_success_data(
        api_client.certify_scrap_manifest_destruction(
            manifest_id,
            f.certify_destruction_payload(certified_at),
            make_compliance_officer_headers(officer_user_id),
        )
    )


def void_manifest(manifest_id: str, officer_user_id: str = OFFICER_SIGNER_ID) -> dict:
    return get_success_data(
        api_client.void_scrap_manifest(
            manifest_id,
            f.void_manifest_payload(),
            make_compliance_officer_headers(officer_user_id),
        )
    )


def setup_manifest_with_condemned_casings(
    casing_specs=None,
    hauler_capacity_lbs: int = 500,
    grade: str = "B",
    with_agreement: bool = False,
    agreement_overrides: dict = None,
    inspector_user_id: str = INSPECTOR_ONE_ID,
) -> dict:
    """A DRAFT manifest listing condemned casings that still carry credit.

    ``casing_specs`` is a list of ``scrap_weight_lbs`` values, one per casing.
    Returns the program dict plus ``manifest`` and ``casings``.
    """
    if casing_specs is None:
        casing_specs = [125]
    program = setup_fleet_program(
        with_agreement=with_agreement, agreement_overrides=agreement_overrides
    )
    program["manifest"] = create_manifest(
        program["location"]["id"], hauler_capacity_lbs=hauler_capacity_lbs
    )
    casings = []
    for weight in casing_specs:
        casing = create_condemned_casing_with_credit(
            program["fleet"]["id"],
            program["location"]["id"],
            grade=grade,
            inspector_user_id=inspector_user_id,
            scrap_weight_lbs=weight,
        )
        add_manifest_line(program["manifest"]["id"], casing["id"])
        casings.append(casing)
    program["casings"] = casings
    program["manifest"] = read_manifest(program["manifest"]["id"])
    return program


def setup_transported_manifest(**kwargs) -> dict:
    """A manifest signed by ``officer-signer`` and already picked up, so the
    next step is destruction certification by a second officer."""
    program = setup_manifest_with_condemned_casings(**kwargs)
    sign_manifest(program["manifest"]["id"], officer_user_id=OFFICER_SIGNER_ID)
    program["manifest"] = transport_manifest(
        program["manifest"]["id"], officer_user_id=OFFICER_SIGNER_ID
    )
    return program


# ==========================================================================
# Cost-per-mile scenarios
# ==========================================================================

def setup_cost_per_mile_asset(
    cost_basis_cents: int = 50000,
    mount_odometer: int = 100000,
    mount_tread_32nds: int = 24,
    survey_odometer: int = 160000,
    survey_tread_32nds: int = 15,
    survey_pressure_psi: float = 100,
    surveyed_at: str = "2026-08-15T09:00:00Z",
) -> dict:
    """One mounted, surveyed asset with a usable wear signal.

    Returns the program dict plus ``vehicle``, ``casing``, ``asset`` and
    ``survey``.
    """
    program = setup_fleet_program()
    vehicle = create_vehicle(
        program["fleet"]["id"], current_odometer_miles=mount_odometer
    )
    casing = create_casing(program["fleet"]["id"])
    asset = create_mounted_asset(
        program["fleet"]["id"],
        casing["id"],
        vehicle["id"],
        mounted_at="2026-08-02T08:00:00Z",
        odometer_at_mount=mount_odometer,
        tread_depth_at_mount_32nds=mount_tread_32nds,
        cost_basis_cents=cost_basis_cents,
    )
    survey = record_survey(
        asset["id"],
        surveyed_at,
        survey_pressure_psi,
        survey_tread_32nds,
        survey_odometer,
    )
    program.update(
        {"vehicle": vehicle, "casing": casing, "asset": asset, "survey": survey}
    )
    return program


# ==========================================================================
# Convenience: identity-threaded header builders bound to a program
# ==========================================================================

def fleet_manager_headers_for(program: dict) -> dict:
    """Headers for the FleetManager of the program's fleet account."""
    return make_fleet_manager_headers(program["fleet"]["id"])


def inspector_headers(user_id: str = INSPECTOR_ONE_ID) -> dict:
    return make_casing_inspector_headers(user_id)


def officer_headers(user_id: str = OFFICER_SIGNER_ID) -> dict:
    return make_compliance_officer_headers(user_id)


DUAL_OFFICER_INSPECTOR_ID = DUAL_ROLE_OPERATOR_ID
