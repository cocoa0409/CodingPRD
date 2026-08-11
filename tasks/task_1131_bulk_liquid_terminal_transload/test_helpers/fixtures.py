"""Composite setup helpers (PRD §3 workflows).

Every helper builds preconditions from scratch using only PRD-declared
endpoints: the harness restarts the server before every test, so each test
starts against an empty database with the logical clock at its default.

Ownership threading: CustomerRep calls always use make_customer_rep_headers
with the real Customer.id; segregation-sensitive steps (gauge recording,
sample result recording, custody certification) take explicit user ids.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import DEFAULTS
from .factories import (
    create_allocation_payload,
    create_customer_payload,
    create_gauge_ticket_payload,
    create_lease_payload,
    create_movement_payload,
    create_permit_payload,
    create_record_result_payload,
    create_sample_payload,
    create_statement_payload,
    create_tank_payload,
    create_terminal_resource_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_rep_headers,
    make_gauger_headers,
    make_inspector_headers,
    make_manager_headers,
)

MANAGER = TEST_USERS["terminal_manager_headers"]
OPERATOR = TEST_USERS["terminal_operator_headers"]
SCHEDULER = TEST_USERS["scheduler_headers"]
GAUGER = TEST_USERS["gauger_headers"]
INSPECTOR = TEST_USERS["quality_inspector_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]


def _ok(resp, what: str):
    try:
        return get_success_data(resp)
    except AssertionError as exc:
        raise AssertionError(f"Setup failed at step '{what}': {exc}") from exc


# ---------------------------------------------------------------------------
# Tier 0: single-entity creation
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the logical clock (TerminalManager only)."""
    return _ok(api_client.set_clock(to_iso8601, MANAGER), f"set_clock({to_iso8601})")


def create_customer(name="Test Customer", contact_email="ops@example.com") -> dict:
    resp = api_client.create_customer(create_customer_payload(name=name, contact_email=contact_email), MANAGER)
    return _ok(resp, "create_customer")


def create_tank(product_grade="DIESEL", capacity_bbl=DEFAULTS["TANK_CAPACITY_BBL"],
                heel_bbl=0, tank_code=None, **extra) -> dict:
    payload = create_tank_payload(product_grade=product_grade, capacity_bbl=capacity_bbl,
                                  heel_bbl=heel_bbl, **extra)
    if tank_code is not None:
        payload["tank_code"] = tank_code
    return _ok(api_client.create_tank(payload, OPERATOR), "create_tank")


def create_resource(resource_type="DOCK", resource_code=None, **extra) -> dict:
    payload = create_terminal_resource_payload(resource_type=resource_type, **extra)
    if resource_code is not None:
        payload["resource_code"] = resource_code
    return _ok(api_client.create_terminal_resource(payload, OPERATOR), "create_terminal_resource")


def create_lease(customer_id, **overrides) -> dict:
    """Create a DRAFT lease as the owning CustomerRep (ownership-gated call)."""
    payload = create_lease_payload(customer_id, **overrides)
    resp = api_client.create_lease_agreement(payload, make_customer_rep_headers(customer_id))
    return _ok(resp, "create_lease")


def create_allocation(lease_id, tank_id, allocated_bbl=DEFAULTS["ALLOCATED_BBL"],
                      period_start=DEFAULTS["PERIOD_START"],
                      period_end=DEFAULTS["PERIOD_END"]) -> dict:
    payload = create_allocation_payload(tank_id, allocated_bbl=allocated_bbl,
                                        period_start=period_start, period_end=period_end)
    return _ok(api_client.create_tank_allocation(lease_id, payload, OPERATOR), "create_allocation")


def activate_allocation(allocation_id) -> dict:
    return _ok(api_client.activate_tank_allocation(allocation_id, OPERATOR), "activate_allocation")


def release_allocation(allocation_id) -> dict:
    return _ok(api_client.release_tank_allocation(allocation_id, OPERATOR), "release_allocation")


def activate_lease(lease_id) -> dict:
    return _ok(api_client.activate_lease(lease_id, MANAGER), "activate_lease")


def suspend_lease(lease_id) -> dict:
    return _ok(api_client.suspend_lease(lease_id, MANAGER), "suspend_lease")


def reactivate_lease(lease_id) -> dict:
    return _ok(api_client.reactivate_lease(lease_id, MANAGER), "reactivate_lease")


def terminate_lease(lease_id) -> dict:
    return _ok(api_client.terminate_lease(lease_id, MANAGER), "terminate_lease")


def get_lease(lease_id) -> dict:
    return _ok(api_client.get_lease_agreement(lease_id, MANAGER), "get_lease")


def get_tank(tank_id) -> dict:
    return _ok(api_client.get_tank(tank_id, MANAGER), "get_tank")


def get_movement(movement_id) -> dict:
    return _ok(api_client.get_movement(movement_id, SCHEDULER), "get_movement")


def create_statement(lease_id, period=DEFAULTS["STATEMENT_PERIOD"]) -> dict:
    return _ok(api_client.create_monthly_statement(lease_id, create_statement_payload(period), CLERK),
               "create_statement")


# ---------------------------------------------------------------------------
# Tier 1: lease with one ACTIVE allocation (lease DRAFT or ACTIVE)
# ---------------------------------------------------------------------------

def setup_lease_with_allocation(product_grade="DIESEL",
                                capacity_bbl=DEFAULTS["TANK_CAPACITY_BBL"],
                                heel_bbl=0,
                                allocated_bbl=DEFAULTS["ALLOCATED_BBL"],
                                lease_overrides=None,
                                tank_overrides=None,
                                activate_lease_flag=True,
                                customer_name="Scenario Customer") -> dict:
    """Customer + tank + DRAFT lease + one allocation walked to ACTIVE;
    optionally activates the lease. Returns a bundle dict."""
    customer = create_customer(name=customer_name, contact_email=f"{customer_name.replace(' ', '.').lower()}@example.com")
    tank = create_tank(product_grade=product_grade, capacity_bbl=capacity_bbl,
                       heel_bbl=heel_bbl, **(tank_overrides or {}))
    lease = create_lease(customer["id"], product_grade=product_grade, **(lease_overrides or {}))
    allocation = create_allocation(lease["id"], tank["id"], allocated_bbl=allocated_bbl)
    allocation = activate_allocation(allocation["id"])
    if activate_lease_flag:
        lease = activate_lease(lease["id"])
    else:
        lease = get_lease(lease["id"])
    return {"customer": customer, "tank": tank, "lease": lease, "allocation": allocation}


# ---------------------------------------------------------------------------
# Tier 2: movements through the lifecycle
# ---------------------------------------------------------------------------

def nominate_movement(lease_id, tank_id, declared_volume_bbl=DEFAULTS["DECLARED_VOLUME_BBL"],
                      mode="VESSEL", direction="RECEIPT", product_grade="DIESEL",
                      window_start=DEFAULTS["WINDOW_START"],
                      window_end=DEFAULTS["WINDOW_END"]) -> dict:
    payload = create_movement_payload(
        lease_id, tank_id, declared_volume_bbl=declared_volume_bbl, mode=mode,
        direction=direction, product_grade=product_grade,
        window_start=window_start, window_end=window_end)
    return _ok(api_client.create_movement(payload, SCHEDULER), "nominate_movement")


def schedule_movement(movement_id, resource_id) -> dict:
    return _ok(api_client.schedule_movement(movement_id, {"resource_id": resource_id}, SCHEDULER),
               "schedule_movement")


def record_gauge(movement_id, ticket_type, observed_volume_bbl, observed_temp_f=60,
                 observed_at="2026-05-10T08:05:00Z", gauger_id="gauger-1") -> dict:
    payload = create_gauge_ticket_payload(ticket_type=ticket_type,
                                          observed_volume_bbl=observed_volume_bbl,
                                          observed_temp_f=observed_temp_f,
                                          observed_at=observed_at)
    return _ok(api_client.create_gauge_ticket(movement_id, payload, make_gauger_headers(gauger_id)),
               f"record_gauge({ticket_type})")


def drive_movement_to_completed(movement_id, resource_id,
                                opening_volume=0, closing_volume=100,
                                open_temp=60, close_temp=60,
                                arrive_clock="2026-05-10T08:00:00Z",
                                complete_clock="2026-05-10T10:05:00Z",
                                open_observed_at="2026-05-10T08:05:00Z",
                                close_observed_at="2026-05-10T10:00:00Z",
                                gauger_id="gauger-1") -> dict:
    """schedule -> clock -> arrive -> OPENING gauge -> start -> CLOSING gauge
    -> clock -> complete. Returns the COMPLETED movement."""
    schedule_movement(movement_id, resource_id)
    return drive_scheduled_movement_to_completed(
        movement_id, opening_volume=opening_volume, closing_volume=closing_volume,
        open_temp=open_temp, close_temp=close_temp,
        arrive_clock=arrive_clock, complete_clock=complete_clock,
        open_observed_at=open_observed_at, close_observed_at=close_observed_at,
        gauger_id=gauger_id)


def drive_scheduled_movement_to_completed(movement_id,
                                          opening_volume=0, closing_volume=100,
                                          open_temp=60, close_temp=60,
                                          arrive_clock="2026-05-10T08:00:00Z",
                                          complete_clock="2026-05-10T10:05:00Z",
                                          open_observed_at="2026-05-10T08:05:00Z",
                                          close_observed_at="2026-05-10T10:00:00Z",
                                          gauger_id="gauger-1") -> dict:
    """Same as drive_movement_to_completed but for an already-SCHEDULED
    movement (use when the schedule response itself was under assertion)."""
    set_clock(arrive_clock)
    _ok(api_client.arrive_movement(movement_id, SCHEDULER), "arrive_movement")
    record_gauge(movement_id, "OPENING", opening_volume, observed_temp_f=open_temp,
                 observed_at=open_observed_at, gauger_id=gauger_id)
    _ok(api_client.start_movement(movement_id, SCHEDULER), "start_movement")
    record_gauge(movement_id, "CLOSING", closing_volume, observed_temp_f=close_temp,
                 observed_at=close_observed_at, gauger_id=gauger_id)
    set_clock(complete_clock)
    resp = api_client.complete_movement(movement_id, SCHEDULER)
    return _ok(resp, "complete_movement")


def collect_sample(movement_id, sample_type="INLINE", collector_id="qi-1") -> dict:
    return _ok(api_client.create_quality_sample(
        movement_id, create_sample_payload(sample_type=sample_type),
        make_inspector_headers(collector_id)), "collect_sample")


def record_sample_result(sample_id, lab_result="PASSED", specific_gravity=0.85,
                         recorder_id="qi-2") -> dict:
    payload = create_record_result_payload(lab_result=lab_result, specific_gravity=specific_gravity)
    return _ok(api_client.record_sample_result(sample_id, payload, make_inspector_headers(recorder_id)),
               "record_sample_result")


def get_movement_custody_transfer(movement_id) -> dict:
    data, _meta = validate_paginated(api_client.list_movement_custody_transfers(movement_id, MANAGER))
    assert len(data) == 1, f"Expected exactly one custody transfer for movement {movement_id}"
    return data[0]


def certify_transfer(ct_id, certifier_id="tm-1") -> dict:
    return _ok(api_client.certify_custody_transfer(ct_id, make_manager_headers(certifier_id)),
               "certify_transfer")


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_completed_movement(declared_volume_bbl=100, opening_volume=0, closing_volume=100,
                             open_temp=60, close_temp=60,
                             product_grade="DIESEL", mode="VESSEL", resource_type="DOCK",
                             capacity_bbl=DEFAULTS["TANK_CAPACITY_BBL"], heel_bbl=0,
                             allocated_bbl=DEFAULTS["ALLOCATED_BBL"],
                             lease_overrides=None, tank_overrides=None,
                             window_start=DEFAULTS["WINDOW_START"],
                             window_end=DEFAULTS["WINDOW_END"],
                             arrive_clock="2026-05-10T08:00:00Z",
                             complete_clock="2026-05-10T10:05:00Z",
                             open_observed_at="2026-05-10T08:05:00Z",
                             close_observed_at="2026-05-10T10:00:00Z",
                             gauger_id="gauger-1",
                             statement_period=None,
                             customer_name="Scenario Customer") -> dict:
    """ACTIVE lease/allocation + resource + movement driven to COMPLETED with a
    PROVISIONAL custody transfer. Optionally pre-creates an OPEN statement."""
    bundle = setup_lease_with_allocation(
        product_grade=product_grade, capacity_bbl=capacity_bbl, heel_bbl=heel_bbl,
        allocated_bbl=allocated_bbl, lease_overrides=lease_overrides,
        tank_overrides=tank_overrides, customer_name=customer_name)
    if statement_period is not None:
        bundle["statement"] = create_statement(bundle["lease"]["id"], statement_period)
    bundle["resource"] = create_resource(resource_type=resource_type)
    movement = nominate_movement(
        bundle["lease"]["id"], bundle["tank"]["id"],
        declared_volume_bbl=declared_volume_bbl, mode=mode, product_grade=product_grade,
        window_start=window_start, window_end=window_end)
    movement = drive_movement_to_completed(
        movement["id"], bundle["resource"]["id"],
        opening_volume=opening_volume, closing_volume=closing_volume,
        open_temp=open_temp, close_temp=close_temp,
        arrive_clock=arrive_clock, complete_clock=complete_clock,
        open_observed_at=open_observed_at, close_observed_at=close_observed_at,
        gauger_id=gauger_id)
    bundle["movement"] = movement
    bundle["custody"] = get_movement_custody_transfer(movement["id"])
    return bundle


def setup_certified_custody(specific_gravity=0.85, sample_type="INLINE",
                            collector_id="qi-1", recorder_id="qi-2",
                            certifier_id="tm-1", **scenario_kwargs) -> dict:
    """setup_completed_movement + PASSED sample + CERTIFIED custody transfer."""
    bundle = setup_completed_movement(**scenario_kwargs)
    bundle["sample"] = collect_sample(bundle["movement"]["id"], sample_type=sample_type,
                                      collector_id=collector_id)
    record_sample_result(bundle["sample"]["id"], lab_result="PASSED",
                         specific_gravity=specific_gravity, recorder_id=recorder_id)
    bundle["custody"] = certify_transfer(bundle["custody"]["id"], certifier_id=certifier_id)
    return bundle


# ---------------------------------------------------------------------------
# Tier 4: permits and vapor-control scenarios
# ---------------------------------------------------------------------------

def create_approved_permit(tank_id, permit_type="VAPOR_CONTROL",
                           valid_from="2026-05-10T00:00:00Z",
                           valid_until="2026-05-10T23:59:59Z") -> dict:
    permit = _ok(api_client.create_permit(
        create_permit_payload(tank_id, permit_type=permit_type,
                              valid_from=valid_from, valid_until=valid_until),
        OPERATOR), "create_permit")
    return _ok(api_client.approve_permit(permit["id"], MANAGER), "approve_permit")


def setup_vru_in_progress_movement(valid_from="2026-05-10T00:00:00Z",
                                   valid_until="2026-05-10T23:59:59Z",
                                   window_start="2026-05-10T08:00:00Z",
                                   window_end="2026-05-10T16:00:00Z",
                                   arrive_clock="2026-05-10T08:00:00Z",
                                   customer_name="Vapor Customer") -> dict:
    """VRU_REQUIRED GASOLINE tank with an APPROVED vapor permit; movement
    ARRIVED -> OPENING gauge -> IN_PROGRESS."""
    bundle = setup_lease_with_allocation(product_grade="GASOLINE",
                                         tank_overrides={"vapor_control_class": "VRU_REQUIRED"},
                                         customer_name=customer_name)
    bundle["permit"] = create_approved_permit(bundle["tank"]["id"], valid_from=valid_from,
                                              valid_until=valid_until)
    bundle["resource"] = create_resource("DOCK")
    movement = nominate_movement(bundle["lease"]["id"], bundle["tank"]["id"],
                                 product_grade="GASOLINE",
                                 window_start=window_start, window_end=window_end)
    schedule_movement(movement["id"], bundle["resource"]["id"])
    set_clock(arrive_clock)
    _ok(api_client.arrive_movement(movement["id"], SCHEDULER), "arrive_movement")
    record_gauge(movement["id"], "OPENING", 0)
    movement = _ok(api_client.start_movement(movement["id"], SCHEDULER), "start_movement")
    bundle["movement"] = movement
    return bundle


# ---------------------------------------------------------------------------
# Tier 5: amendments
# ---------------------------------------------------------------------------

def propose_amendment(lease_id, customer_id, expected_lease_version, **proposed) -> dict:
    payload = {"expected_lease_version": expected_lease_version}
    payload.update(proposed)
    return _ok(api_client.create_lease_amendment(
        lease_id, payload, make_customer_rep_headers(customer_id)), "propose_amendment")
