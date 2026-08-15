"""Composite setup helpers.

Every fixture builds its preconditions from scratch against a freshly
restarted server, using only PRD-declared endpoints. Setup calls use the
lenient get_success_data() validator so failures surface as clear
"Setup failed" messages.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import (
    MUNICIPAL_TIER_RATES,
    TEST_DEFAULTS,
    UTILITY_TIER_RATES,
)
from .factories import (
    add_stop_payload,
    create_compliance_exception_payload,
    create_crew_payload,
    create_district_payload,
    create_outage_ticket_payload,
    create_pole_payload,
    create_program_payload,
    create_rate_schedule_payload,
    create_route_payload,
    create_savings_report_payload,
    create_salvage_batch_payload,
    create_tariff_account_payload,
    dispatch_ticket_payload,
    dispatch_work_order_payload,
    resolve_ticket_payload,
    submit_audit_payload,
)
from .test_users import (
    TEST_USERS,
    make_citizen_reporter_headers,
    make_field_supervisor_headers,
    make_program_manager_headers,
)

PM = TEST_USERS["program_manager_headers"]
PM2 = TEST_USERS["program_manager_2_headers"]
BA = TEST_USERS["billing_analyst_headers"]
CO = TEST_USERS["compliance_officer_headers"]
QA = TEST_USERS["qa_inspector_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 1: state progression primitives
# ---------------------------------------------------------------------------

def create_program(budget=None, rebate_cap=None, rebate_per_kwh=None, **overrides):
    """Create a DRAFT program. Returns the program dict."""
    payload_kwargs = {}
    if budget is not None:
        payload_kwargs["program_budget_cents"] = budget
    if rebate_cap is not None:
        payload_kwargs["fy_rebate_cap_cents"] = rebate_cap
    if rebate_per_kwh is not None:
        payload_kwargs["rebate_cents_per_kwh"] = rebate_per_kwh
    payload_kwargs.update(overrides)
    resp = api.create_program(create_program_payload(**payload_kwargs), PM)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: create_program -> {resp.text}"
    return data


def create_active_program(budget=None, rebate_cap=None, rebate_per_kwh=None, **overrides):
    """Create a program and activate it. Returns the ACTIVE program dict."""
    program = create_program(budget=budget, rebate_cap=rebate_cap,
                             rebate_per_kwh=rebate_per_kwh, **overrides)
    resp = api.activate_program(program["id"], PM)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: activate_program -> {resp.text}"
    return data


def get_program(program_id):
    resp = api.get_program(program_id, PM)
    assert resp.status_code == 200, f"Setup failed: get_program -> {resp.text}"
    return get_success_data(resp)


def create_district(program_id, zone="RESIDENTIAL", **overrides):
    resp = api.create_district(create_district_payload(program_id, zone=zone, **overrides), PM)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: create_district -> {resp.text}"
    return data


def get_district(district_id):
    resp = api.get_district(district_id, PM)
    assert resp.status_code == 200, f"Setup failed: get_district -> {resp.text}"
    return get_success_data(resp)


def create_crew(program_id, **overrides):
    resp = api.create_crew(create_crew_payload(program_id, **overrides), PM)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: create_crew -> {resp.text}"
    return data


def create_pole(district_id, **overrides):
    resp = api.create_pole(create_pole_payload(district_id, **overrides), PM)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: create_pole -> {resp.text}"
    return data


def get_pole(pole_id):
    resp = api.get_pole(pole_id, PM)
    assert resp.status_code == 200, f"Setup failed: get_pole -> {resp.text}"
    return get_success_data(resp)


def attest_pole_nameplate(pole_id):
    """UTILITY_OWNED pole SURVEYED -> AUDIT_CLEARED (BillingAnalyst)."""
    resp = api.attest_nameplate(pole_id, BA)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: attest_nameplate -> {resp.text}"
    return data


def get_audit(audit_id):
    resp = api.get_audit(audit_id, PM)
    assert resp.status_code == 200, f"Setup failed: get_audit -> {resp.text}"
    return get_success_data(resp)


def submit_and_accept_audit(pole_id, audited_wattage, crew_id):
    """MUNICIPAL pole: submit (FieldSupervisor = crew) then accept (ProgramManager).
    Returns the ACCEPTED audit dict."""
    pole = get_pole(pole_id)
    resp = api.submit_audit(
        pole_id,
        submit_audit_payload(pole["version"], audited_wattage=audited_wattage),
        make_field_supervisor_headers(crew_id),
    )
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: submit_audit -> {resp.text}"
    resp = api.accept_audit(data["id"], PM)
    accepted = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: accept_audit -> {resp.text}"
    return accepted


def clear_pole_for_scheduling(pole_id, crew_id, audited_wattage=None):
    """Bring a pole to AUDIT_CLEARED via the ownership-appropriate path."""
    pole = get_pole(pole_id)
    if pole["ownership_type"] == "UTILITY_OWNED":
        attest_pole_nameplate(pole_id)
    else:
        submit_and_accept_audit(
            pole_id,
            audited_wattage if audited_wattage is not None else pole["nameplate_wattage"],
            crew_id,
        )
    return get_pole(pole_id)


def create_route(district_id, crew_id, start="2026-08-03", end="2026-08-03",
                 traffic_control_required=False):
    resp = api.create_route(
        create_route_payload(
            district_id, crew_id,
            window_start_date=start, window_end_date=end,
            traffic_control_required=traffic_control_required,
        ),
        PM,
    )
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: create_route -> {resp.text}"
    return data


def add_stop(route_id, pole_id, sequence_number, difficulty_class="STANDARD"):
    resp = api.add_stop(
        route_id, add_stop_payload(pole_id, sequence_number, difficulty_class=difficulty_class), PM
    )
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: add_stop -> {resp.text}"
    return data


def release_route(route_id):
    resp = api.release_route(route_id, PM)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: release_route -> {resp.text}"
    return data


def list_work_orders_for_route(route_id):
    resp = api.list_work_orders(PM, params={"route_id": route_id, "limit": 100})
    data, _meta = resp.json()["data"], resp.json()["meta"]
    assert resp.status_code == 200, f"Setup failed: list_work_orders -> {resp.text}"
    return data


def get_work_order(work_order_id):
    resp = api.get_work_order(work_order_id, PM)
    assert resp.status_code == 200, f"Setup failed: get_work_order -> {resp.text}"
    return get_success_data(resp)


def get_stop(stop_id):
    resp = api.get_stop(stop_id, PM)
    assert resp.status_code == 200, f"Setup failed: get_stop -> {resp.text}"
    return get_success_data(resp)


def get_route(route_id):
    resp = api.get_route(route_id, PM)
    assert resp.status_code == 200, f"Setup failed: get_route -> {resp.text}"
    return get_success_data(resp)


def set_clock(to_iso8601):
    resp = api.set_clock(to_iso8601, PM)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: set_clock -> {resp.text}"
    return data


def dispatch_work_order(work_order_id, crew_id, wattage=None, cct=None, shielding=None):
    payload = dispatch_work_order_payload()
    if wattage is not None:
        payload["new_fixture_wattage"] = wattage
    if cct is not None:
        payload["new_cct_kelvin"] = cct
    if shielding is not None:
        payload["shielding"] = shielding
    resp = api.dispatch_work_order(work_order_id, payload, make_field_supervisor_headers(crew_id))
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: dispatch_work_order -> {resp.text}"
    return data


def complete_work_order(work_order_id, crew_id):
    resp = api.complete_work_order(work_order_id, make_field_supervisor_headers(crew_id))
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: complete_work_order -> {resp.text}"
    return data


def dispatch_and_complete(work_order_id, crew_id, wattage=None, cct=None, shielding=None):
    dispatch_work_order(work_order_id, crew_id, wattage=wattage, cct=cct, shielding=shielding)
    return complete_work_order(work_order_id, crew_id)


def qc_pass(work_order_id, qa_headers=None):
    resp = api.qc_pass_work_order(work_order_id, qa_headers or QA)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: qc_pass -> {resp.text}"
    return data


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy
# ---------------------------------------------------------------------------

def setup_program_district_crew(budget=None, zone="RESIDENTIAL", **crew_overrides):
    """ACTIVE program + one district + one crew. Returns (program, district, crew)."""
    program = create_active_program(budget=budget)
    district = create_district(program["id"], zone=zone)
    crew = create_crew(program["id"], **crew_overrides)
    return program, district, crew


def setup_cleared_pole(program, district, crew, pole_number=None,
                       ownership_type="UTILITY_OWNED", nameplate_wattage=None,
                       audited_wattage=None, fixture_class="COBRA_HEAD"):
    """Create a pole and bring it to AUDIT_CLEARED. Returns the cleared pole."""
    kwargs = {"ownership_type": ownership_type, "fixture_class": fixture_class}
    if pole_number is not None:
        kwargs["pole_number"] = pole_number
    if nameplate_wattage is not None:
        kwargs["nameplate_wattage"] = nameplate_wattage
    pole = create_pole(district["id"], **kwargs)
    return clear_pole_for_scheduling(pole["id"], crew["id"], audited_wattage=audited_wattage)


def setup_released_route(program, district, crew, poles, start="2026-08-03",
                         end="2026-08-03", traffic_control_required=False,
                         difficulties=None):
    """Create a route over the given (already AUDIT_CLEARED) poles, add one stop
    per pole in order, and release it. Returns (route, stops, work_orders)."""
    route = create_route(district["id"], crew["id"], start=start, end=end,
                         traffic_control_required=traffic_control_required)
    stops = []
    for i, pole in enumerate(poles):
        difficulty = difficulties[i] if difficulties else "STANDARD"
        stops.append(add_stop(route["id"], pole["id"], i + 1, difficulty_class=difficulty))
    release_route(route["id"])
    work_orders = list_work_orders_for_route(route["id"])
    return route, stops, work_orders


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_converted_pole(program, district, crew, pole_number=None,
                         ownership_type="UTILITY_OWNED", nameplate_wattage=250,
                         led_wattage=90, led_cct=None, shielding=None,
                         route_start="2026-08-03", route_end="2026-08-03",
                         fixture_class="COBRA_HEAD", complete_clock=None):
    """Drive one pole all the way through conversion completion (no QC).
    Returns (pole, route, stop, work_order)."""
    pole = setup_cleared_pole(
        program, district, crew, pole_number=pole_number,
        ownership_type=ownership_type, nameplate_wattage=nameplate_wattage,
        fixture_class=fixture_class,
    )
    route, stops, work_orders = setup_released_route(
        program, district, crew, [pole], start=route_start, end=route_end,
    )
    if complete_clock is not None:
        set_clock(complete_clock)
    if led_cct is None:
        led_cct = 2700 if district["zone"] in ("RESIDENTIAL", "RURAL", "DOWNTOWN") else 3000
    if shielding is None:
        shielding = "FULL_CUTOFF" if district["full_cutoff_required"] else "SEMI_CUTOFF"
    work_order = dispatch_and_complete(
        work_orders[0]["id"], crew["id"],
        wattage=led_wattage, cct=led_cct, shielding=shielding,
    )
    return get_pole(pole["id"]), get_route(route["id"]), stops[0], work_order


def setup_verified_pole(program, district, crew, **kwargs):
    """Converted pole with QC passed (pole VERIFIED). Returns (pole, route, stop, work_order)."""
    pole, route, stop, work_order = setup_converted_pole(program, district, crew, **kwargs)
    qc_pass(work_order["id"])
    return get_pole(pole["id"]), route, stop, get_work_order(work_order["id"])


def find_salvage_item_for_pole(pole_id):
    resp = api.list_salvage_items(PM, params={"pole_id": pole_id})
    assert resp.status_code == 200, f"Setup failed: list_salvage_items -> {resp.text}"
    items = resp.json()["data"]
    assert len(items) >= 1, f"Setup failed: no salvage item for pole {pole_id}"
    return items[0]


# ---------------------------------------------------------------------------
# Tier 4: tariff setup helpers
# ---------------------------------------------------------------------------

def setup_effective_rate_schedule(program_id, ownership_class, tier_rates=None,
                                  effective_from="2026-01-01", effective_until=None):
    """Create + file + activate a rate schedule. Returns the EFFECTIVE schedule."""
    rates = tier_rates
    if rates is None:
        rates = MUNICIPAL_TIER_RATES if ownership_class == "MUNICIPAL" else UTILITY_TIER_RATES
    payload = create_rate_schedule_payload(
        program_id, ownership_class=ownership_class,
        effective_from=effective_from, tier_rates=rates,
    )
    if effective_until is not None:
        payload["effective_until"] = effective_until
    resp = api.create_rate_schedule(payload, BA)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: create_rate_schedule -> {resp.text}"
    resp = api.file_rate_schedule(data["id"], BA)
    assert resp.status_code == 200, f"Setup failed: file_rate_schedule -> {resp.text}"
    resp = api.activate_rate_schedule(data["id"], BA)
    activated = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: activate_rate_schedule -> {resp.text}"
    return activated


def create_account(district_id, ownership_class, account_number=None):
    kwargs = {"ownership_class": ownership_class}
    if account_number is not None:
        kwargs["account_number"] = account_number
    resp = api.create_tariff_account(create_tariff_account_payload(district_id, **kwargs), BA)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: create_tariff_account -> {resp.text}"
    return data


def get_account(account_id):
    resp = api.get_tariff_account(account_id, BA)
    assert resp.status_code == 200, f"Setup failed: get_tariff_account -> {resp.text}"
    return get_success_data(resp)


def generate_lines(account_id):
    resp = api.generate_lines(account_id, BA)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: generate_lines -> {resp.text}"
    return data


def close_period(account_id):
    resp = api.close_period(account_id, BA)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: close_period -> {resp.text}"
    return data


def list_lines(account_id=None, pole_id=None, period=None, **extra):
    params = dict(extra)
    if account_id is not None:
        params["account_id"] = account_id
    if pole_id is not None:
        params["pole_id"] = pole_id
    if period is not None:
        params["period"] = period
    resp = api.list_billing_lines(BA, params=params)
    assert resp.status_code == 200, f"Setup failed: list_billing_lines -> {resp.text}"
    return resp.json()["data"]


# ---------------------------------------------------------------------------
# Tier 4b: outage tickets
# ---------------------------------------------------------------------------

def create_ticket(pole_id, reporter_user_id="citizen-1", **overrides):
    resp = api.create_outage_ticket(
        create_outage_ticket_payload(pole_id, **overrides),
        make_citizen_reporter_headers(reporter_user_id),
    )
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: create_outage_ticket -> {resp.text}"
    return data


def get_ticket(ticket_id):
    resp = api.get_outage_ticket(ticket_id, PM)
    assert resp.status_code == 200, f"Setup failed: get_outage_ticket -> {resp.text}"
    return get_success_data(resp)


def triage_and_dispatch_ticket(ticket_id, crew_id):
    resp = api.triage_ticket(ticket_id, PM)
    assert resp.status_code == 200, f"Setup failed: triage_ticket -> {resp.text}"
    resp = api.dispatch_ticket(ticket_id, dispatch_ticket_payload(crew_id), PM)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: dispatch_ticket -> {resp.text}"
    return data


def resolve_ticket(ticket_id, crew_id, resolution_code="LIGHT_OUT_FIXED"):
    resp = api.resolve_ticket(
        ticket_id,
        resolve_ticket_payload(resolution_code=resolution_code),
        make_field_supervisor_headers(crew_id),
    )
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: resolve_ticket -> {resp.text}"
    return data


def setup_resolved_ticket(program, district, crew, pole_id, reporter_user_id="citizen-1",
                          resolution_code="LIGHT_OUT_FIXED", **ticket_overrides):
    """Create -> triage -> dispatch -> resolve a ticket. Returns the RESOLVED ticket."""
    ticket = create_ticket(pole_id, reporter_user_id=reporter_user_id, **ticket_overrides)
    triage_and_dispatch_ticket(ticket["id"], crew["id"])
    return resolve_ticket(ticket["id"], crew["id"], resolution_code=resolution_code)


# ---------------------------------------------------------------------------
# Tier 5: savings reports / compliance exceptions / salvage
# ---------------------------------------------------------------------------

def create_report(program_id, period="2026-08", method="METERED_ACTUAL",
                  fiscal_year_label="FY2026", pm_user_id="pm-user-1"):
    """Create a savings report with a freshly read expected_program_version."""
    program = get_program(program_id)
    resp = api.create_savings_report(
        create_savings_report_payload(
            program_id, program["version"],
            period=period, method=method, fiscal_year_label=fiscal_year_label,
        ),
        make_program_manager_headers(pm_user_id),
    )
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: create_savings_report -> {resp.text}"
    return data


def submit_report(report_id, pm_user_id="pm-user-1"):
    resp = api.submit_savings_report(report_id, make_program_manager_headers(pm_user_id))
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: submit_savings_report -> {resp.text}"
    return data


def attest_report(report_id, auditor_user_id="auditor-1"):
    from .test_users import make_auditor_headers
    resp = api.attest_savings_report(report_id, make_auditor_headers(auditor_user_id))
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: attest_savings_report -> {resp.text}"
    return data


def get_report(report_id):
    resp = api.get_savings_report(report_id, PM)
    assert resp.status_code == 200, f"Setup failed: get_savings_report -> {resp.text}"
    return get_success_data(resp)


def create_exception(pole_id, exception_kind="CCT_WAIVER", valid_until="2027-01-01",
                     requested_cct_kelvin=5000):
    kwargs = {"exception_kind": exception_kind, "valid_until": valid_until}
    if exception_kind == "CCT_WAIVER":
        kwargs["requested_cct_kelvin"] = requested_cct_kelvin
    else:
        kwargs["requested_cct_kelvin"] = None
    resp = api.create_compliance_exception(
        create_compliance_exception_payload(pole_id, **kwargs), PM
    )
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: create_compliance_exception -> {resp.text}"
    return data


def create_batch(program_id, batch_label=None):
    kwargs = {}
    if batch_label is not None:
        kwargs["batch_label"] = batch_label
    resp = api.create_salvage_batch(create_salvage_batch_payload(program_id, **kwargs), PM)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: create_salvage_batch -> {resp.text}"
    return data


def get_batch(batch_id):
    resp = api.get_salvage_batch(batch_id, PM)
    assert resp.status_code == 200, f"Setup failed: get_salvage_batch -> {resp.text}"
    return get_success_data(resp)


def get_salvage_item(item_id):
    resp = api.get_salvage_item(item_id, PM)
    assert resp.status_code == 200, f"Setup failed: get_salvage_item -> {resp.text}"
    return get_success_data(resp)
