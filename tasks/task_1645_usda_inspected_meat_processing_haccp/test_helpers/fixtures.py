"""Composite setup helpers.

Each helper builds its preconditions from scratch through the public API
(the server restarts before every test, so nothing carries over). Helpers
use the lenient ``get_success_data`` validator so setup failures surface as
clear "Setup failed" errors. An "env" is a dict carrying the composite
scenario's resources: plant, plan, ccp, shift, day.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DAY_CLOCK_ISO,
    INSPECTOR_1,
    LAB_ANALYST_1,
    PRODUCTION_DATE,
    QA_MANAGER_1,
    QA_MANAGER_2,
    QA_TECH_1,
    SHIFT_END_ISO,
    SHIFT_START_ISO,
)
from .factories import (
    chill_complete_payload,
    complete_fabrication_payload,
    corrective_action_payload,
    create_ccp_payload,
    create_finished_lot_payload,
    create_haccp_plan_payload,
    create_inspector_shift_payload,
    create_label_approval_payload,
    create_plant_payload,
    create_production_day_payload,
    create_recall_exercise_payload,
    cut_record_payload,
    harvest_payload,
    humane_audit_payload,
    log_temperature_payload,
    observation_payload,
    pathogen_sample_payload,
    receive_lot_payload,
    release_hold_payload,
    report_result_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_inspector_headers,
    make_lab_analyst_headers,
    make_production_manager_headers,
    make_qa_manager_headers,
    make_qa_tech_headers,
)

ADMIN = TEST_USERS["plant_admin_headers"]
QA = TEST_USERS["qa_manager_headers"]
TECH = TEST_USERS["qa_tech_headers"]
LAB = TEST_USERS["lab_analyst_headers"]
PROD = TEST_USERS["production_manager_headers"]


# --- Tier 1: single-resource builders ----------------------------------------


def create_plant(establishment_number: str = "EST-1645-BASE",
                 cooler_capacity_lbs: float = 10000.0, **overrides) -> dict:
    payload = create_plant_payload(
        establishment_number=establishment_number,
        cooler_capacity_lbs=cooler_capacity_lbs,
        **overrides,
    )
    return get_success_data(api_client.create_plant(payload, ADMIN))


def create_draft_plan(plant_id: str, process_type: str = "RAW_GROUND") -> dict:
    return get_success_data(
        api_client.create_haccp_plan(
            plant_id, create_haccp_plan_payload(process_type=process_type), QA
        )
    )


def add_ccp(plan_id: str, **overrides) -> dict:
    payload = create_ccp_payload(**overrides)
    # Optional critical limits: None means "unset" — omit the key entirely.
    payload = {k: v for k, v in payload.items() if v is not None}
    return get_success_data(api_client.create_ccp(plan_id, payload, QA))


def submit_plan(plan_id: str) -> dict:
    return get_success_data(api_client.submit_haccp_plan(plan_id, QA))


def approve_plan(plan_id: str, inspector_id: str = INSPECTOR_1) -> dict:
    return get_success_data(
        api_client.approve_haccp_plan(plan_id, make_inspector_headers(inspector_id))
    )


def activate_plan(plan_id: str) -> dict:
    return get_success_data(api_client.activate_haccp_plan(plan_id, QA))


def create_effective_plan(plant_id: str, process_type: str = "RAW_GROUND",
                          ccp_overrides: dict = None,
                          inspector_id: str = INSPECTOR_1):
    """Plan + one CCP walked DRAFT -> SUBMITTED -> APPROVED -> EFFECTIVE.

    Returns (plan, ccp).
    """
    plan = create_draft_plan(plant_id, process_type=process_type)
    ccp = add_ccp(plan["id"], **(ccp_overrides or {}))
    submit_plan(plan["id"])
    approve_plan(plan["id"], inspector_id=inspector_id)
    plan = activate_plan(plan["id"])
    return plan, ccp


def schedule_shift(plant_id: str, inspector_id: str = INSPECTOR_1,
                   scheduled_start: str = SHIFT_START_ISO,
                   scheduled_end: str = SHIFT_END_ISO) -> dict:
    payload = create_inspector_shift_payload(
        inspector_user_id=inspector_id,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
    )
    return get_success_data(api_client.create_inspector_shift(plant_id, payload, ADMIN))


def set_clock(to_iso8601: str = DAY_CLOCK_ISO) -> dict:
    return get_success_data(
        api_client.set_clock(set_clock_payload(to_iso8601=to_iso8601), ADMIN)
    )


def check_in_shift(shift_id: str, inspector_id: str = INSPECTOR_1) -> dict:
    return get_success_data(
        api_client.check_in_shift(shift_id, make_inspector_headers(inspector_id))
    )


def plan_production_day(plant_id: str, production_date: str = PRODUCTION_DATE,
                        process_type: str = "RAW_GROUND") -> dict:
    payload = create_production_day_payload(
        production_date=production_date, process_type=process_type
    )
    return get_success_data(api_client.create_production_day(plant_id, payload, PROD))


def open_day(day_id: str) -> dict:
    return get_success_data(api_client.open_production_day(day_id, PROD))


# --- Tier 2: composite environment -------------------------------------------


def setup_open_day(establishment_number: str = "EST-1645-BASE",
                   process_type: str = "RAW_GROUND",
                   production_date: str = PRODUCTION_DATE,
                   clock: str = DAY_CLOCK_ISO,
                   inspector_id: str = INSPECTOR_1,
                   cooler_capacity_lbs: float = 10000.0,
                   ccp_overrides: dict = None,
                   shift_start: str = SHIFT_START_ISO,
                   shift_end: str = SHIFT_END_ISO) -> dict:
    """Plant + EFFECTIVE plan with one CCP + ON_PREMISE inspector + OPEN day.

    Returns env dict with keys: plant, plan, ccp, shift, day.
    """
    plant = create_plant(establishment_number=establishment_number,
                         cooler_capacity_lbs=cooler_capacity_lbs)
    plan, ccp = create_effective_plan(
        plant["id"], process_type=process_type, ccp_overrides=ccp_overrides,
        inspector_id=inspector_id,
    )
    shift = schedule_shift(plant["id"], inspector_id=inspector_id,
                           scheduled_start=shift_start, scheduled_end=shift_end)
    set_clock(clock)
    check_in_shift(shift["id"], inspector_id=inspector_id)
    day = plan_production_day(plant["id"], production_date=production_date,
                              process_type=process_type)
    day = open_day(day["id"])
    return {"plant": plant, "plan": plan, "ccp": ccp, "shift": shift, "day": day}


# --- Tier 3: lot lifecycle ----------------------------------------------------


def receive_lot(day_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.receive_lot(day_id, receive_lot_payload(**overrides), PROD)
    )


def walk_lot_to_chilled(lot_id: str, inspector_id: str = INSPECTOR_1,
                        hot: float = 1030.0, cold: float = 1000.0) -> dict:
    """RECEIVED -> CLEARED -> HARVESTED -> CHILLED. Returns the chilled lot."""
    get_success_data(
        api_client.pass_ante_mortem(lot_id, make_inspector_headers(inspector_id))
    )
    get_success_data(api_client.harvest_lot(lot_id, harvest_payload(
        hot_carcass_weight_lbs=hot), PROD))
    return get_success_data(
        api_client.chill_complete_lot(lot_id, chill_complete_payload(
            cold_carcass_weight_lbs=cold), PROD)
    )


def record_cuts(lot_id: str, cuts) -> list:
    """Record (primal_type, weight_lbs) cut lines against a FABRICATING lot."""
    records = []
    for primal, weight in cuts:
        records.append(get_success_data(api_client.create_cut_record(
            lot_id, cut_record_payload(primal_type=primal, weight_lbs=weight), PROD,
        )))
    return records


def setup_fabricating_lot(env: dict = None, hot: float = 1030.0,
                          cold: float = 1000.0,
                          cuts=(("CHUCK", 600.0),),
                          lot_overrides: dict = None, **env_kwargs):
    """OPEN day + lot walked to FABRICATING with the given cut lines recorded.

    Returns (env, lot, cut_records).
    """
    if env is None:
        env = setup_open_day(**env_kwargs)
    lot = receive_lot(env["day"]["id"], **(lot_overrides or {}))
    walk_lot_to_chilled(lot["id"], inspector_id=env["shift"]["inspector_user_id"],
                        hot=hot, cold=cold)
    get_success_data(api_client.fabricate_lot(lot["id"], PROD))
    records = record_cuts(lot["id"], cuts)
    lot = get_success_data(api_client.get_lot(lot["id"], PROD))
    return env, lot, records


def setup_fabricated_lot(env: dict = None, hot: float = 1030.0,
                         cold: float = 1000.0, cuts=(("CHUCK", 600.0),),
                         trim_waste_lbs: float = 400.0, **env_kwargs):
    """OPEN day + lot walked to FABRICATED. Returns (env, lot)."""
    env, lot, _records = setup_fabricating_lot(
        env=env, hot=hot, cold=cold, cuts=cuts, **env_kwargs
    )
    lot = get_success_data(api_client.complete_fabrication(
        lot["id"], complete_fabrication_payload(trim_waste_lbs=trim_waste_lbs), PROD,
    ))
    return env, lot


# --- Tier 4: labels, finished lots, deviations, samples -----------------------


def create_approved_label(plant_id: str, product_name: str = "Ground Beef 80/20",
                          formulation_version: int = 1,
                          inspector_id: str = INSPECTOR_1, **overrides) -> dict:
    label = get_success_data(api_client.create_label_approval(
        plant_id,
        create_label_approval_payload(
            product_name=product_name,
            formulation_version=formulation_version,
            **overrides,
        ),
        QA,
    ))
    get_success_data(api_client.submit_label_approval(label["id"], QA))
    return get_success_data(
        api_client.approve_label_approval(
            label["id"], make_inspector_headers(inspector_id)
        )
    )


def pack_finished_lot(day_id: str, lot_id: str, label_id: str,
                      units_produced: int = 10, unit_weight_lbs: float = 10.0,
                      shelf_life_days: int = 10) -> dict:
    payload = create_finished_lot_payload(
        source_lot_id=lot_id,
        label_approval_id=label_id,
        units_produced=units_produced,
        unit_weight_lbs=unit_weight_lbs,
        shelf_life_days=shelf_life_days,
    )
    return get_success_data(api_client.create_finished_lot(day_id, payload, PROD))


def setup_finished_lot(env: dict = None, units_produced: int = 10,
                       unit_weight_lbs: float = 10.0, shelf_life_days: int = 10,
                       **fab_kwargs):
    """FABRICATED lot + APPROVED label + one PRODUCED finished lot.

    Returns (env, lot, label, finished_lot).
    """
    env, lot = setup_fabricated_lot(env=env, **fab_kwargs)
    label = create_approved_label(env["plant"]["id"])
    fl = pack_finished_lot(env["day"]["id"], lot["id"], label["id"],
                           units_produced=units_produced,
                           unit_weight_lbs=unit_weight_lbs,
                           shelf_life_days=shelf_life_days)
    return env, lot, label, fl


def record_observation(ccp_id: str, observed_value_f: float,
                       monitor_id: str = QA_TECH_1) -> dict:
    return get_success_data(api_client.record_observation(
        ccp_id, observation_payload(observed_value_f=observed_value_f),
        make_qa_tech_headers(monitor_id),
    ))


def setup_deviation(env: dict = None, observed_value_f: float = 41.0,
                    monitor_id: str = QA_TECH_1, **env_kwargs):
    """OPEN day (default CCP max 40.0) + one out-of-limit observation.

    Returns (env, observation, deviation_id).
    """
    if env is None:
        env = setup_open_day(**env_kwargs)
    obs = record_observation(env["ccp"]["id"], observed_value_f,
                             monitor_id=monitor_id)
    assert obs.get("deviation_id"), "Setup failed: out-of-limit observation " \
        f"did not spawn a deviation: {obs}"
    return env, obs, obs["deviation_id"]


def resolve_deviation(deviation_id: str, action_by: str = QA_MANAGER_1,
                      verify_by: str = QA_MANAGER_2) -> dict:
    """OPEN -> ACTION_LOGGED -> VERIFIED with segregated operators."""
    get_success_data(api_client.log_corrective_action(
        deviation_id, corrective_action_payload(), make_qa_manager_headers(action_by),
    ))
    return get_success_data(
        api_client.verify_deviation(deviation_id, make_qa_manager_headers(verify_by))
    )


def collect_sample(lot_id: str, collector_id: str = QA_TECH_1, **overrides) -> dict:
    return get_success_data(api_client.collect_pathogen_sample(
        lot_id, pathogen_sample_payload(**overrides),
        make_qa_tech_headers(collector_id),
    ))


def report_sample(sample_id: str, result: str,
                  lab_id: str = LAB_ANALYST_1) -> dict:
    return get_success_data(api_client.report_sample_result(
        sample_id, report_result_payload(result=result),
        make_lab_analyst_headers(lab_id),
    ))


def setup_held_lot(env: dict = None, lot: dict = None, **fab_kwargs):
    """Lot driven to HELD by a POSITIVE sample. Returns (env, lot, sample)."""
    if env is None:
        env, lot = setup_fabricated_lot(**fab_kwargs)
    sample = collect_sample(lot["id"])
    report_sample(sample["id"], "POSITIVE")
    lot = get_success_data(api_client.get_lot(lot["id"], PROD))
    assert lot["status"] == "HELD", f"Setup failed: lot not HELD: {lot}"
    return env, lot, sample


# --- Tier 5: noncompliance / recall -------------------------------------------


def create_humane_audit(plant_id: str, day_id: str,
                        auditor_id: str = INSPECTOR_1, **overrides) -> dict:
    payload = humane_audit_payload(production_day_id=day_id, **overrides)
    return get_success_data(
        api_client.create_humane_audit(
            plant_id, payload, make_inspector_headers(auditor_id)
        )
    )


def setup_suspended_plant_via_humane_failure(
        establishment_number: str = "EST-1645-HUM",
        auditor_id: str = INSPECTOR_1, **env_kwargs):
    """EFFECTIVE SLAUGHTER plan + OPEN day + FAILED humane audit.

    Returns (env, audit, nr_id) with the plant SUSPENDED and the day
    SUSPENDED by the noncompliance cascade.
    """
    env = setup_open_day(
        establishment_number=establishment_number,
        process_type="SLAUGHTER",
        ccp_overrides={
            "ccp_code": "CCP-1S",
            "description": "Scald water",
            "critical_limit_min_f": 140.0,
            "critical_limit_max_f": None,
        },
        **env_kwargs,
    )
    audit = create_humane_audit(
        env["plant"]["id"], env["day"]["id"], auditor_id=auditor_id,
        stunning_efficacy_pct=97.0, slips_falls_pct=2.0, vocalization_pct=5.0,
    )
    assert audit["outcome"] == "FAILED", f"Setup failed: audit not FAILED: {audit}"
    return env, audit, audit["noncompliance_record_id"]


def setup_recall_exercise(establishment_number: str = "EST-1645-RCL",
                          units_produced: int = 100, unit_weight_lbs: float = 10.0,
                          shelf_life_days: int = 10, scope: str = "FULL",
                          **fab_kwargs):
    """PRODUCED finished lot + INITIATED recall exercise against it.

    Returns (env, lot, label, finished_lot, exercise).
    """
    env, lot, label, fl = setup_finished_lot(
        establishment_number=establishment_number,
        units_produced=units_produced,
        unit_weight_lbs=unit_weight_lbs,
        shelf_life_days=shelf_life_days,
        **fab_kwargs,
    )
    exercise = get_success_data(api_client.create_recall_exercise(
        env["plant"]["id"],
        create_recall_exercise_payload(
            target_finished_lot_id=fl["id"], scope=scope,
        ),
        ADMIN,
    ))
    return env, lot, label, fl, exercise


def log_temperature(fl_id: str, temp_f: float) -> dict:
    return get_success_data(
        api_client.log_temperature(fl_id, log_temperature_payload(temp_f=temp_f), PROD)
    )
