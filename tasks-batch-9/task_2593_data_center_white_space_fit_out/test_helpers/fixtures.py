"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints,
because each test starts against an empty database. Setup calls use the lenient
`get_success_data` validator so a broken precondition reports as a setup failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS, USER_IDS
from .test_users import TEST_USERS, make_tenant_representative_headers

FP = TEST_USERS["facility_planner_headers"]
EC = TEST_USERS["electrical_contractor_headers"]
MC = TEST_USERS["mechanical_contractor_headers"]
CA = TEST_USERS["commissioning_agent_headers"]
WA = TEST_USERS["witness_authority_headers"]
CM = TEST_USERS["change_manager_headers"]
CM2 = TEST_USERS["change_manager_2_headers"]
OM = TEST_USERS["operations_manager_headers"]
SA = TEST_USERS["security_administrator_headers"]

TENANT_REP = make_tenant_representative_headers


# ==========================================================================
# Tier 0: single-step helpers
# ==========================================================================
def set_clock(instant: str, headers=None) -> dict:
    return get_success_data(
        api_client.set_clock({"current_utc": instant}, headers or FP)
    )


def create_hall(code: str, **overrides) -> dict:
    payload = {
        "name": overrides.pop("name", f"White Space {code}"),
        "code": code,
        "tenant_mode": overrides.pop("tenant_mode", "SINGLE_TENANT"),
        "design_kw_capacity": overrides.pop(
            "design_kw_capacity", TEST_DEFAULTS["HALL_DESIGN_KW"]
        ),
        "gross_area_sqm": overrides.pop(
            "gross_area_sqm", TEST_DEFAULTS["HALL_GROSS_AREA_SQM"]
        ),
        "cooling_redundancy": overrides.pop("cooling_redundancy", "N"),
        "planned_rack_count": overrides.pop(
            "planned_rack_count", TEST_DEFAULTS["HALL_PLANNED_RACK_COUNT"]
        ),
    }
    payload.update(overrides)
    return get_success_data(api_client.create_hall(payload, FP))


def create_tenant(code: str, **overrides) -> dict:
    payload = {
        "name": overrides.pop("name", f"Tenant {code}"),
        "code": code,
        "contracted_kw": overrides.pop(
            "contracted_kw", TEST_DEFAULTS["TENANT_CONTRACTED_KW"]
        ),
        "contract_start_date": overrides.pop(
            "contract_start_date", TEST_DEFAULTS["TENANT_CONTRACT_START"]
        ),
    }
    payload.update(overrides)
    return get_success_data(api_client.create_tenant(payload, FP))


def create_pdu(hall_id: str, name: str, feed_side: str, rated_kw=None, **overrides):
    payload = {
        "hall_id": hall_id,
        "name": name,
        "feed_side": feed_side,
        "rated_kw": TEST_DEFAULTS["PDU_RATED_KW"] if rated_kw is None else rated_kw,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_pdu(payload, EC))


def commission_pdu(pdu_id: str, measured_derate_factor: float = 1.00) -> dict:
    return get_success_data(
        api_client.patch_pdu(
            pdu_id, {"measured_derate_factor": measured_derate_factor}, EC
        )
    )


def create_busway(
    pdu_id: str,
    name: str,
    rated_amps: int = None,
    voltage_v: int = None,
    redundancy_topology: str = "N_PLUS_1",
    **overrides,
) -> dict:
    payload = {
        "pdu_id": pdu_id,
        "name": name,
        "rated_amps": TEST_DEFAULTS["BUSWAY_RATED_AMPS"]
        if rated_amps is None
        else rated_amps,
        "voltage_v": TEST_DEFAULTS["BUSWAY_VOLTAGE_V"]
        if voltage_v is None
        else voltage_v,
        "redundancy_topology": redundancy_topology,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_busway(payload, EC))


def energize_busway(busway_id: str) -> dict:
    return get_success_data(api_client.energize_busway(busway_id, EC))


def create_zone(hall_id: str, label: str = "CA-1", **overrides) -> dict:
    payload = {
        "hall_id": hall_id,
        "label": label,
        "zone_type": overrides.pop("zone_type", "COLD_AISLE"),
        "containment_kind": overrides.pop("containment_kind", "RIGID_ROOF"),
        "target_leakage_pct": overrides.pop(
            "target_leakage_pct", TEST_DEFAULTS["ZONE_TARGET_LEAKAGE_PCT"]
        ),
        "design_static_pressure_pa": overrides.pop(
            "design_static_pressure_pa",
            TEST_DEFAULTS["ZONE_DESIGN_STATIC_PRESSURE_PA"],
        ),
    }
    payload.update(overrides)
    return get_success_data(api_client.create_containment_zone(payload, MC))


def leakage_test(
    zone_id: str,
    measured_leakage_pct: float = 5.00,
    measured_static_pressure_pa: float = 20.0,
) -> dict:
    return get_success_data(
        api_client.leakage_test(
            zone_id,
            {
                "measured_leakage_pct": measured_leakage_pct,
                "measured_static_pressure_pa": measured_static_pressure_pa,
            },
            MC,
        )
    )


def remediate_zone(zone_id: str, remediation_note: str = "reseal the roof") -> dict:
    return get_success_data(
        api_client.remediate_zone(zone_id, {"remediation_note": remediation_note}, MC)
    )


def create_cooling_unit(hall_id: str, name: str = "CU-1", **overrides) -> dict:
    payload = {
        "hall_id": hall_id,
        "name": name,
        "rated_sensible_kw": overrides.pop(
            "rated_sensible_kw", TEST_DEFAULTS["CU_RATED_SENSIBLE_KW"]
        ),
        "design_airflow_cfm": overrides.pop(
            "design_airflow_cfm", TEST_DEFAULTS["CU_DESIGN_AIRFLOW_CFM"]
        ),
        "supply_delta_t_f": overrides.pop(
            "supply_delta_t_f", TEST_DEFAULTS["CU_SUPPLY_DELTA_T_F"]
        ),
        "redundancy_role": overrides.pop("redundancy_role", "PRIMARY"),
    }
    payload.update(overrides)
    return get_success_data(api_client.create_cooling_unit(payload, MC))


def commission_cooling_unit(unit_id: str, measured_airflow_cfm: int) -> dict:
    return get_success_data(
        api_client.commission_cooling_unit(
            unit_id, {"measured_airflow_cfm": measured_airflow_cfm}, MC
        )
    )


def place_unit_in_service(unit_id: str) -> dict:
    return get_success_data(api_client.place_cooling_unit_in_service(unit_id, MC))


def create_cage(hall_id: str, tenant_id: str, label: str = "CG-1", **overrides) -> dict:
    payload = {
        "hall_id": hall_id,
        "tenant_id": tenant_id,
        "label": label,
        "perimeter_length_m": overrides.pop(
            "perimeter_length_m", TEST_DEFAULTS["CAGE_PERIMETER_M"]
        ),
    }
    payload.update(overrides)
    return get_success_data(api_client.create_cage(payload, SA))


def create_camera(cage_id: str, label: str, covered_length_m: float) -> dict:
    return get_success_data(
        api_client.create_security_device(
            {
                "cage_id": cage_id,
                "device_type": "CAMERA",
                "label": label,
                "covered_length_m": covered_length_m,
            },
            SA,
        )
    )


def create_card_reader(cage_id: str, label: str, reader_zone_label: str) -> dict:
    return get_success_data(
        api_client.create_security_device(
            {
                "cage_id": cage_id,
                "device_type": "CARD_READER",
                "label": label,
                "reader_zone_label": reader_zone_label,
            },
            SA,
        )
    )


def commission_device(device_id: str) -> dict:
    return get_success_data(api_client.commission_security_device(device_id, SA))


def create_rack(
    hall_id: str,
    containment_zone_id: str,
    grid_row: str = "A",
    grid_col: int = 1,
    design_kw: float = None,
    **overrides,
) -> dict:
    payload = {
        "hall_id": hall_id,
        "containment_zone_id": containment_zone_id,
        "grid_row": grid_row,
        "grid_col": grid_col,
        "design_kw": TEST_DEFAULTS["RACK_DESIGN_KW"] if design_kw is None else design_kw,
        "u_height": overrides.pop("u_height", TEST_DEFAULTS["RACK_U_HEIGHT"]),
        "required_feed_count": overrides.pop("required_feed_count", 2),
    }
    payload.update(overrides)
    return get_success_data(api_client.create_rack(payload, FP))


def reserve_feed(
    rack_id: str,
    busway_id: str,
    feed_side: str,
    requested_kw: float = None,
    breaker_amps: int = None,
) -> dict:
    payload = {
        "rack_id": rack_id,
        "busway_id": busway_id,
        "feed_side": feed_side,
        "requested_kw": TEST_DEFAULTS["FEED_REQUESTED_KW"]
        if requested_kw is None
        else requested_kw,
        "breaker_amps": TEST_DEFAULTS["FEED_BREAKER_AMPS"]
        if breaker_amps is None
        else breaker_amps,
    }
    return get_success_data(api_client.create_rack_feed(payload, EC))


def release_feed(feed_id: str) -> dict:
    return get_success_data(api_client.delete_rack_feed(feed_id, EC))


def install_rack(rack_id: str, asset_tag: str = None) -> dict:
    payload = {} if asset_tag is None else {"asset_tag": asset_tag}
    return get_success_data(api_client.install_rack(rack_id, payload, FP))


def tag_rack(rack_id: str, asset_tag: str) -> dict:
    return get_success_data(api_client.patch_rack(rack_id, {"asset_tag": asset_tag}, FP))


def power_on_rack(rack_id: str) -> dict:
    return get_success_data(api_client.power_on_rack(rack_id, EC))


def advance_phase(hall_id: str, target_status: str) -> dict:
    return get_success_data(
        api_client.advance_hall_phase(hall_id, {"target_status": target_status}, FP)
    )


def read_hall(hall_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_hall(hall_id, headers or FP))


def read_hall_version(hall_id: str) -> int:
    return read_hall(hall_id)["version"]


def read_capacity_summary(hall_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_capacity_summary(hall_id, headers or FP))


def read_cage(cage_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_cage(cage_id, headers or FP))


def read_cage_version(cage_id: str) -> int:
    return read_cage(cage_id)["version"]


def read_rack(rack_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_rack(rack_id, headers or FP))


def read_busway(busway_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_busway(busway_id, headers or FP))


def read_feed(feed_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_rack_feed(feed_id, headers or FP))


def read_zone(zone_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_containment_zone(zone_id, headers or FP))


def read_cooling_unit(unit_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_cooling_unit(unit_id, headers or FP))


def read_package(package_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_commissioning_package(package_id, headers or FP)
    )


def read_mop(mop_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_mop(mop_id, headers or FP))


def read_packet(packet_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_release_packet(packet_id, headers or FP))


def read_pdu(pdu_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_pdu(pdu_id, headers or FP))


def read_device(device_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_security_device(device_id, headers or FP))


def read_load_bank_test(test_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_load_bank_test(test_id, headers or FP))


# ==========================================================================
# Tier 1/2: hall skeletons
# ==========================================================================
def setup_planning_hall(
    code: str,
    *,
    tenant_mode: str = "SINGLE_TENANT",
    design_kw_capacity: float = None,
    cooling_redundancy: str = "N",
    pdu_rated_kw: float = None,
    derate_a: float = 1.00,
    derate_b: float = 1.00,
    commission_pdus: bool = True,
    busway_amps: int = None,
    busway_voltage: int = None,
    busway_topology: str = "N_PLUS_1",
    with_busway_b: bool = True,
    with_cooling_unit: bool = True,
    cu_rated_sensible_kw: float = None,
    cu_design_airflow_cfm: int = None,
    cu_supply_delta_t_f: float = None,
    zone_target_leakage_pct: float = None,
    zone_design_static_pressure_pa: float = None,
    reset_clock: bool = True,
    clock: str = None,
    **hall_overrides,
) -> dict:
    """Hall in PLANNING with the electrical and mechanical skeleton in place:
    PDU-A1 and PDU-B1 (commissioned by default), BW-A1 (and BW-B1), zone CA-1 and
    optionally CU-1. Returns a context dict keyed by role name."""
    if reset_clock:
        set_clock(clock or TEST_DEFAULTS["CLOCK_START"])

    hall = create_hall(
        code,
        tenant_mode=tenant_mode,
        design_kw_capacity=design_kw_capacity
        if design_kw_capacity is not None
        else TEST_DEFAULTS["HALL_DESIGN_KW"],
        cooling_redundancy=cooling_redundancy,
        **hall_overrides,
    )
    ctx = {"hall": hall, "hall_id": hall["id"]}

    pdu_a = create_pdu(hall["id"], "PDU-A1", "A", rated_kw=pdu_rated_kw)
    pdu_b = create_pdu(hall["id"], "PDU-B1", "B", rated_kw=pdu_rated_kw)
    ctx["pdu_a"], ctx["pdu_b"] = pdu_a, pdu_b

    if commission_pdus:
        ctx["pdu_a"] = commission_pdu(pdu_a["id"], derate_a)
        ctx["pdu_b"] = commission_pdu(pdu_b["id"], derate_b)

    ctx["bw_a"] = create_busway(
        pdu_a["id"],
        "BW-A1",
        rated_amps=busway_amps,
        voltage_v=busway_voltage,
        redundancy_topology=busway_topology,
    )
    if with_busway_b:
        ctx["bw_b"] = create_busway(
            pdu_b["id"],
            "BW-B1",
            rated_amps=busway_amps,
            voltage_v=busway_voltage,
            redundancy_topology=busway_topology,
        )

    zone_kwargs = {}
    if zone_target_leakage_pct is not None:
        zone_kwargs["target_leakage_pct"] = zone_target_leakage_pct
    if zone_design_static_pressure_pa is not None:
        zone_kwargs["design_static_pressure_pa"] = zone_design_static_pressure_pa
    ctx["zone"] = create_zone(hall["id"], "CA-1", **zone_kwargs)
    ctx["zone_id"] = ctx["zone"]["id"]

    if with_cooling_unit:
        cu_kwargs = {}
        if cu_rated_sensible_kw is not None:
            cu_kwargs["rated_sensible_kw"] = cu_rated_sensible_kw
        if cu_design_airflow_cfm is not None:
            cu_kwargs["design_airflow_cfm"] = cu_design_airflow_cfm
        if cu_supply_delta_t_f is not None:
            cu_kwargs["supply_delta_t_f"] = cu_supply_delta_t_f
        ctx["cu_1"] = create_cooling_unit(hall["id"], "CU-1", **cu_kwargs)
    return ctx


def setup_fit_out_hall(code: str, *, energize: bool = True, **kwargs) -> dict:
    """Planning skeleton advanced to FIT_OUT with both busways energised."""
    ctx = setup_planning_hall(code, **kwargs)
    advance_phase(ctx["hall_id"], "FIT_OUT")
    if energize:
        ctx["bw_a"] = energize_busway(ctx["bw_a"]["id"])
        if "bw_b" in ctx:
            ctx["bw_b"] = energize_busway(ctx["bw_b"]["id"])
    ctx["hall"] = read_hall(ctx["hall_id"])
    return ctx


def prove_zone_and_cooling(
    ctx: dict,
    *,
    measured_leakage_pct: float = 5.00,
    measured_static_pressure_pa: float = None,
    measured_airflow_cfm: int = None,
) -> dict:
    """Bring zone CA-1 to PASS and CU-1 to IN_SERVICE."""
    pressure = (
        ctx["zone"]["design_static_pressure_pa"]
        if measured_static_pressure_pa is None
        else measured_static_pressure_pa
    )
    ctx["zone"] = leakage_test(ctx["zone_id"], measured_leakage_pct, pressure)
    if "cu_1" in ctx:
        airflow = (
            ctx["cu_1"]["design_airflow_cfm"]
            if measured_airflow_cfm is None
            else measured_airflow_cfm
        )
        commission_cooling_unit(ctx["cu_1"]["id"], airflow)
        ctx["cu_1"] = place_unit_in_service(ctx["cu_1"]["id"])
    return ctx


def add_powered_rack(
    ctx: dict,
    *,
    grid_row: str = "A",
    grid_col: int = 1,
    design_kw: float = None,
    asset_tag: str = "AT-0001",
    feed_kw: float = None,
    breaker_amps: int = None,
    key: str = "rack_1",
    **rack_overrides,
) -> dict:
    """Place a rack, reserve its two feeds, install it and power it on."""
    rack = create_rack(
        ctx["hall_id"],
        ctx["zone_id"],
        grid_row,
        grid_col,
        design_kw=design_kw,
        **rack_overrides,
    )
    ctx[key] = rack
    ctx[key + "_feed_a"] = reserve_feed(
        rack["id"], ctx["bw_a"]["id"], "A", feed_kw, breaker_amps
    )
    ctx[key + "_feed_b"] = reserve_feed(
        rack["id"], ctx["bw_b"]["id"], "B", feed_kw, breaker_amps
    )
    install_rack(rack["id"], asset_tag)
    ctx[key] = power_on_rack(rack["id"])
    return ctx


def setup_commissioning_hall(
    code: str,
    *,
    rack_design_kw: float = None,
    rack_feed_kw: float = None,
    rack_asset_tag: str = "AT-0001",
    measured_leakage_pct: float = 5.00,
    measured_airflow_cfm: int = None,
    **kwargs,
) -> dict:
    """The canonical build: FIT_OUT hall, zone at PASS, CU-1 IN_SERVICE, one POWERED
    rack on two feeds, hall advanced to COMMISSIONING."""
    ctx = setup_fit_out_hall(code, **kwargs)
    prove_zone_and_cooling(
        ctx,
        measured_leakage_pct=measured_leakage_pct,
        measured_airflow_cfm=measured_airflow_cfm,
    )
    add_powered_rack(
        ctx,
        design_kw=rack_design_kw,
        asset_tag=rack_asset_tag,
        feed_kw=rack_feed_kw,
    )
    advance_phase(ctx["hall_id"], "COMMISSIONING")
    ctx["hall"] = read_hall(ctx["hall_id"])
    return ctx


# ==========================================================================
# Tier 3: commissioning package lifecycles
# ==========================================================================
def create_package(
    hall_id: str,
    level: str,
    title: str = None,
    target_load_kw: float = 10.00,
    expected_hall_version: int = None,
    headers=None,
) -> dict:
    version = (
        read_hall_version(hall_id)
        if expected_hall_version is None
        else expected_hall_version
    )
    payload = {
        "hall_id": hall_id,
        "level": level,
        "title": title or f"{level} integrated systems test",
        "target_load_kw": target_load_kw,
        "expected_hall_version": version,
    }
    return get_success_data(
        api_client.create_commissioning_package(payload, headers or CA)
    )


def approve_script(package_id: str, script_revision: int = 1) -> dict:
    return get_success_data(
        api_client.approve_script(package_id, {"script_revision": script_revision}, CA)
    )


def execute_script(package_id: str, user_id: str = None) -> dict:
    headers = (
        CA
        if user_id is None
        else {**CA, "X-User-ID": user_id}
    )
    return get_success_data(api_client.execute_script(package_id, headers))


def witness_package(
    package_id: str, decision: str = "WITNESSED", user_id: str = None, note: str = None
) -> dict:
    headers = WA if user_id is None else {**WA, "X-User-ID": user_id}
    payload = {"decision": decision}
    if note is not None:
        payload["witness_note"] = note
    return get_success_data(api_client.witness_package(package_id, payload, headers))


def schedule_load_bank(
    package_id: str,
    target_kw: float = 10.00,
    window_start: str = "2026-08-05T02:00:00Z",
    window_end: str = "2026-08-05T06:00:00Z",
    step_pct_sequence=None,
) -> dict:
    payload = {
        "package_id": package_id,
        "target_kw": target_kw,
        "window_start": window_start,
        "window_end": window_end,
        "step_pct_sequence": step_pct_sequence or [25, 50, 75, 100],
    }
    return get_success_data(api_client.create_load_bank_test(payload, CA))


def start_load_bank(test_id: str) -> dict:
    return get_success_data(api_client.start_load_bank_test(test_id, CA))


def complete_load_bank(
    test_id: str, measured_kw: float, measured_return_delta_t_f: float
) -> dict:
    return get_success_data(
        api_client.complete_load_bank_test(
            test_id,
            {
                "measured_kw": measured_kw,
                "measured_return_delta_t_f": measured_return_delta_t_f,
            },
            CA,
        )
    )


def abort_load_bank(test_id: str, abort_reason: str = "aborted for setup") -> dict:
    return get_success_data(
        api_client.abort_load_bank_test(test_id, {"abort_reason": abort_reason}, CA)
    )


def run_passing_load_bank(
    package_id: str,
    *,
    target_kw: float = 10.00,
    window_start: str = "2026-08-05T02:00:00Z",
    window_end: str = "2026-08-05T06:00:00Z",
    clock_inside: str = "2026-08-05T03:00:00Z",
    measured_kw: float = None,
    measured_return_delta_t_f: float = 12.0,
) -> dict:
    """Schedule, start and complete one PASSing load bank run on an approved script."""
    run = schedule_load_bank(package_id, target_kw, window_start, window_end)
    set_clock(clock_inside)
    start_load_bank(run["id"])
    return complete_load_bank(
        run["id"],
        target_kw if measured_kw is None else measured_kw,
        measured_return_delta_t_f,
    )


def certify_package(
    hall_id: str,
    level: str,
    *,
    target_load_kw: float = 10.00,
    script_revision: int = 1,
    with_load_bank: bool = True,
    window_start: str = "2026-08-05T02:00:00Z",
    window_end: str = "2026-08-05T06:00:00Z",
    clock_inside: str = "2026-08-05T03:00:00Z",
    executor: str = None,
    witness: str = None,
) -> dict:
    """Open a package, approve its script, run its load bank when the level demands
    one, execute the script and witness it. Returns the certified package."""
    package = create_package(hall_id, level, target_load_kw=target_load_kw)
    approve_script(package["id"], script_revision)
    if with_load_bank and level in ("L4", "L5"):
        run_passing_load_bank(
            package["id"],
            target_kw=target_load_kw,
            window_start=window_start,
            window_end=window_end,
            clock_inside=clock_inside,
        )
    execute_script(package["id"], executor or USER_IDS["COMMISSIONING_AGENT"])
    return witness_package(
        package["id"], "WITNESSED", witness or USER_IDS["WITNESS_AUTHORITY"]
    )


def setup_live_hall(code: str, **kwargs) -> dict:
    """Drive a hall all the way to LIVE by certifying an L4 and then an L5 package,
    which is the only path the phase ladder offers into LIVE."""
    ctx = setup_commissioning_hall(code, **kwargs)
    ctx["pkg_l4"] = certify_package(
        ctx["hall_id"],
        "L4",
        window_start="2026-08-05T02:00:00Z",
        window_end="2026-08-05T06:00:00Z",
        clock_inside="2026-08-05T03:00:00Z",
    )
    ctx["pkg_l5"] = certify_package(
        ctx["hall_id"],
        "L5",
        window_start="2026-08-06T02:00:00Z",
        window_end="2026-08-06T06:00:00Z",
        clock_inside="2026-08-06T03:00:00Z",
    )
    ctx["hall"] = read_hall(ctx["hall_id"])
    return ctx


# ==========================================================================
# Tier 3: cages and security devices
# ==========================================================================
def setup_secured_cage(
    hall_id: str,
    tenant_id: str,
    *,
    label: str = "CG-1",
    perimeter_length_m: float = 40.0,
    camera_coverage_m: float = 38.0,
    reader_zones=("Z-N", "Z-S"),
    **cage_overrides,
) -> dict:
    """Cage with one commissioned camera and one commissioned reader per distinct
    zone, which is what drives it FIT_OUT -> SECURED."""
    cage = create_cage(
        hall_id,
        tenant_id,
        label,
        perimeter_length_m=perimeter_length_m,
        **cage_overrides,
    )
    cam = create_camera(cage["id"], "CAM-1", camera_coverage_m)
    commission_device(cam["id"])
    readers = []
    for index, zone in enumerate(reader_zones, start=1):
        reader = create_card_reader(cage["id"], f"RD-{index}", zone)
        commission_device(reader["id"])
        readers.append(reader)
    return {
        "cage": read_cage(cage["id"]),
        "cage_id": cage["id"],
        "camera": cam,
        "readers": readers,
    }


# ==========================================================================
# Tier 3: methods of procedure
# ==========================================================================
def create_mop(
    hall_id: str,
    target_resource_type: str,
    target_resource_id: str,
    *,
    title: str = "Planned works",
    risk_class: str = "LOW",
    backout_plan: str = "restore the prior configuration",
    window_start: str = "2026-08-10T02:00:00Z",
    window_end: str = "2026-08-10T06:00:00Z",
    role_headers=None,
    author_user_id: str = None,
) -> dict:
    headers = role_headers or EC
    if author_user_id:
        headers = {**headers, "X-User-ID": author_user_id}
    payload = {
        "hall_id": hall_id,
        "target_resource_type": target_resource_type,
        "target_resource_id": target_resource_id,
        "title": title,
        "risk_class": risk_class,
        "backout_plan": backout_plan,
        "window_start": window_start,
        "window_end": window_end,
    }
    return get_success_data(api_client.create_mop(payload, headers))


def submit_mop(mop_id: str, author_user_id: str = None, role_headers=None) -> dict:
    headers = role_headers or EC
    if author_user_id:
        headers = {**headers, "X-User-ID": author_user_id}
    return get_success_data(api_client.submit_mop(mop_id, headers))


def approve_mop(
    mop_id: str,
    *,
    role_headers=None,
    user_id: str = None,
    decision: str = "APPROVE",
    comment: str = "approved",
) -> dict:
    headers = role_headers or CM
    if user_id:
        headers = {**headers, "X-User-ID": user_id}
    payload = {"decision": decision, "comment": comment}
    return get_success_data(api_client.create_mop_approval(mop_id, payload, headers))


def revise_mop(mop_id: str, author_user_id: str = None, **fields) -> dict:
    headers = EC if author_user_id is None else {**EC, "X-User-ID": author_user_id}
    return get_success_data(api_client.revise_mop(mop_id, fields, headers))


def schedule_mop(mop_id: str, tenant_notified_ids=None) -> dict:
    payload = {}
    if tenant_notified_ids is not None:
        payload["tenant_notified_ids"] = tenant_notified_ids
    return get_success_data(api_client.schedule_mop(mop_id, payload, CM))


def execute_mop(mop_id: str, author_user_id: str = None, role_headers=None) -> dict:
    headers = role_headers or EC
    if author_user_id:
        headers = {**headers, "X-User-ID": author_user_id}
    return get_success_data(api_client.execute_mop(mop_id, headers))


def close_mop(mop_id: str, author_user_id: str = None, note: str = "work complete"):
    headers = EC if author_user_id is None else {**EC, "X-User-ID": author_user_id}
    return get_success_data(api_client.close_mop(mop_id, {"closeout_note": note}, headers))


def back_out_mop(mop_id: str, author_user_id: str = None, note: str = "abandoned"):
    headers = EC if author_user_id is None else {**EC, "X-User-ID": author_user_id}
    return get_success_data(
        api_client.back_out_mop(mop_id, {"backout_note": note}, headers)
    )


def approve_mop_to_quorum(mop_id: str, risk_class: str = "LOW") -> dict:
    """Record enough distinct-identity, distinct-role APPROVE votes to bring an
    UNDER_REVIEW MOP to APPROVED."""
    result = approve_mop(
        mop_id, role_headers=CM, user_id=USER_IDS["CHANGE_MANAGER"]
    )
    if risk_class == "HIGH":
        result = approve_mop(
            mop_id, role_headers=OM, user_id=USER_IDS["OPERATIONS_MANAGER"]
        )
    return result


def setup_scheduled_mop(
    hall_id: str,
    target_resource_type: str,
    target_resource_id: str,
    *,
    risk_class: str = "LOW",
    window_start: str = "2026-08-05T02:00:00Z",
    window_end: str = "2026-08-05T06:00:00Z",
    author_user_id: str = None,
    role_headers=None,
    tenant_notified_ids=None,
    title: str = "Planned works",
) -> dict:
    """Draft -> submit -> approve to quorum -> schedule."""
    author = author_user_id or USER_IDS["ELECTRICAL_CONTRACTOR"]
    mop = create_mop(
        hall_id,
        target_resource_type,
        target_resource_id,
        title=title,
        risk_class=risk_class,
        window_start=window_start,
        window_end=window_end,
        role_headers=role_headers,
        author_user_id=author,
    )
    submit_mop(mop["id"], author, role_headers=role_headers)
    approve_mop_to_quorum(mop["id"], risk_class)
    return schedule_mop(mop["id"], tenant_notified_ids)


def setup_executing_mop(
    hall_id: str,
    target_resource_type: str,
    target_resource_id: str,
    *,
    risk_class: str = "LOW",
    window_start: str = "2026-08-05T02:00:00Z",
    window_end: str = "2026-08-05T06:00:00Z",
    clock_inside: str = "2026-08-05T02:30:00Z",
    author_user_id: str = None,
    role_headers=None,
    tenant_notified_ids=None,
) -> dict:
    """Draft -> submit -> approve -> schedule -> move the clock into the window ->
    execute. The MOP is left IN_EXECUTION with its cascade applied."""
    author = author_user_id or USER_IDS["ELECTRICAL_CONTRACTOR"]
    mop = setup_scheduled_mop(
        hall_id,
        target_resource_type,
        target_resource_id,
        risk_class=risk_class,
        window_start=window_start,
        window_end=window_end,
        author_user_id=author,
        role_headers=role_headers,
        tenant_notified_ids=tenant_notified_ids,
    )
    set_clock(clock_inside)
    return execute_mop(mop["id"], author, role_headers=role_headers)


# ==========================================================================
# Tier 5: release packets
# ==========================================================================
def create_packet(
    hall_id: str,
    cage_id: str,
    as_built_drawing_ref: str = "AB-0001",
    expected_cage_version: int = None,
) -> dict:
    version = (
        read_cage_version(cage_id)
        if expected_cage_version is None
        else expected_cage_version
    )
    payload = {
        "hall_id": hall_id,
        "cage_id": cage_id,
        "as_built_drawing_ref": as_built_drawing_ref,
        "expected_cage_version": version,
    }
    return get_success_data(api_client.create_release_packet(payload, CA))


def submit_packet(packet_id: str) -> dict:
    return get_success_data(api_client.submit_release_packet(packet_id, CA))


def accept_packet(packet_id: str, user_id: str = None) -> dict:
    headers = OM if user_id is None else {**OM, "X-User-ID": user_id}
    return get_success_data(api_client.accept_release_packet(packet_id, headers))


def reject_packet(packet_id: str, rejected_reason: str = "paperwork short") -> dict:
    return get_success_data(
        api_client.reject_release_packet(
            packet_id, {"rejected_reason": rejected_reason}, OM
        )
    )


def setup_submitted_packet(
    hall_id: str, cage_id: str, as_built_drawing_ref: str = "AB-0001"
) -> dict:
    packet = create_packet(hall_id, cage_id, as_built_drawing_ref)
    return submit_packet(packet["id"])


def setup_live_hall_with_caged_rack(
    code: str,
    *,
    tenant_code: str = "TN-CAGE",
    contracted_kw: float = 80.00,
    rack_design_kw: float = 15.00,
    rack_asset_tag: str = "AT-0001",
    cage_perimeter_m: float = 40.0,
    camera_coverage_m: float = 38.0,
    **kwargs,
) -> dict:
    """A LIVE hall whose single POWERED rack sits inside a SECURED tenant cage —
    the precondition every release-packet acceptance needs."""
    tenant = create_tenant(tenant_code, contracted_kw=contracted_kw)
    ctx = setup_fit_out_hall(code, **kwargs)
    ctx["tenant"] = tenant
    ctx["tenant_id"] = tenant["id"]
    cage_ctx = setup_secured_cage(
        ctx["hall_id"],
        tenant["id"],
        perimeter_length_m=cage_perimeter_m,
        camera_coverage_m=camera_coverage_m,
    )
    ctx.update(cage_ctx)
    prove_zone_and_cooling(ctx)
    add_powered_rack(
        ctx,
        design_kw=rack_design_kw,
        asset_tag=rack_asset_tag,
        cage_id=cage_ctx["cage_id"],
        tenant_id=tenant["id"],
    )
    advance_phase(ctx["hall_id"], "COMMISSIONING")
    ctx["pkg_l4"] = certify_package(
        ctx["hall_id"],
        "L4",
        window_start="2026-08-05T02:00:00Z",
        window_end="2026-08-05T06:00:00Z",
        clock_inside="2026-08-05T03:00:00Z",
    )
    ctx["pkg_l5"] = certify_package(
        ctx["hall_id"],
        "L5",
        window_start="2026-08-06T02:00:00Z",
        window_end="2026-08-06T06:00:00Z",
        clock_inside="2026-08-06T03:00:00Z",
    )
    ctx["hall"] = read_hall(ctx["hall_id"])
    ctx["cage"] = read_cage(cage_ctx["cage_id"])
    return ctx
