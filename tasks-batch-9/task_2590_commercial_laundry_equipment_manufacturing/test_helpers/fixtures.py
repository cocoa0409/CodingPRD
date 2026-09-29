"""Composite setup builders and pytest fixtures.

The harness restarts the API and empties the database before every single test,
so nothing here may assume pre-existing rows: every precondition is rebuilt from
scratch through the endpoints the PRD declares. Setup calls go through
``get_success_data`` so a broken precondition fails loudly and is never confused
with the behaviour under test.

The builders are plain functions so a test can parameterise them; the pytest
fixtures at the bottom wrap the most frequently reused states.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .test_users import (
    CHANNEL_MANAGER,
    COMPLIANCE_OFFICER,
    DOSSIER_PREPARER,
    ENERGY_REVIEWER,
    PLANT_MANAGER,
    PRODUCT_ENGINEER,
    TRAINING_ADMIN,
    WARRANTY_ANALYST,
    WATER_REVIEWER,
    make_distributor_headers,
    make_quality_inspector_headers,
    make_technician_headers,
)

# ─── The standard floor timeline (all inside the default logical clock day) ─
DRUM_START = "2026-08-01T08:00:00Z"
DRUM_END = "2026-08-01T09:00:00Z"
BEARING_START = "2026-08-01T09:00:00Z"
BEARING_END = "2026-08-01T10:00:00Z"
CONTROL_START = "2026-08-01T10:00:00Z"
CONTROL_END = "2026-08-01T11:00:00Z"
IN_SPEC_PRELOAD_304 = 24.00
CERT_EXPIRY = "2027-06-30T00:00:00Z"


# ─── Tier 1: single rows ──────────────────────────────────────────────────
def make_model(api, **overrides) -> dict:
    """Register one ON_PREMISES machine model in DRAFT."""
    return get_success_data(
        api.create_machine_model(f.machine_model_payload(**overrides), PRODUCT_ENGINEER)
    )


def make_vended_model(api, **overrides) -> dict:
    return get_success_data(
        api.create_machine_model(f.vended_model_payload(**overrides), PRODUCT_ENGINEER)
    )


def make_tunnel_model(api, **overrides) -> dict:
    return get_success_data(
        api.create_machine_model(f.tunnel_model_payload(**overrides), PRODUCT_ENGINEER)
    )


def make_rebate_program(api, **overrides) -> dict:
    return get_success_data(
        api.create_rebate_program(
            f.rebate_program_payload(**overrides), COMPLIANCE_OFFICER
        )
    )


def make_dossier(api, model_id: str, **overrides) -> dict:
    """Open a dossier prepared by the segregated preparer identity."""
    return get_success_data(
        api.create_certification_dossier(
            model_id, f.dossier_payload(**overrides), DOSSIER_PREPARER
        )
    )


def approve_both_dimensions(api, dossier_id: str) -> dict:
    """Two distinct reviewers approve ENERGY then WATER, certifying the dossier."""
    get_success_data(
        api.create_dossier_review(
            dossier_id, f.review_payload("ENERGY", "APPROVE"), ENERGY_REVIEWER
        )
    )
    return get_success_data(
        api.create_dossier_review(
            dossier_id, f.review_payload("WATER", "APPROVE"), WATER_REVIEWER
        )
    )


def make_certified_model(api, **overrides) -> dict:
    """A model driven to CERTIFIED through a two-dimension dossier review."""
    model = make_model(api, **overrides)
    dossier = make_dossier(api, model["id"])
    dossier = approve_both_dimensions(api, dossier["id"])
    model = get_success_data(api.get_machine_model(model["id"], PRODUCT_ENGINEER))
    return {"model": model, "dossier": dossier}


def make_released_model(api, **overrides) -> dict:
    """A CERTIFIED model advanced to RELEASED by its product engineer."""
    env = make_certified_model(api, **overrides)
    env["model"] = get_success_data(
        api.machine_model_lifecycle_action(
            env["model"]["id"], f.lifecycle_action_payload("RELEASE"), PRODUCT_ENGINEER
        )
    )
    return env


def make_station(api, **overrides) -> dict:
    return get_success_data(
        api.create_assembly_station(f.assembly_station_payload(**overrides), PLANT_MANAGER)
    )


def make_three_stations(api) -> dict:
    """One station per station type, with the three changeover buffers used by
    the standard floor timeline."""
    return {
        "drum": make_station(
            api,
            station_code="DRUM-01",
            station_type="DRUM_FAB",
            changeover_buffer_minutes=30,
        ),
        "bearing": make_station(
            api,
            station_code="BRG-01",
            station_type="BEARING_INSTALL",
            changeover_buffer_minutes=15,
        ),
        "control": make_station(
            api,
            station_code="CTL-01",
            station_type="CONTROL_INTEGRATION",
            changeover_buffer_minutes=10,
        ),
    }


def make_technician(api, **overrides) -> dict:
    return get_success_data(
        api.create_technician(f.technician_payload(**overrides), TRAINING_ADMIN)
    )


def grant_scopes(api, technician_id: str, scopes: list, **overrides) -> dict:
    return get_success_data(
        api.create_certification_action(
            technician_id,
            f.grant_payload(scopes=scopes, **overrides),
            TRAINING_ADMIN,
        )
    )


def make_certified_technician(api, scopes: list, **overrides) -> dict:
    """A technician registered and then granted the given certification scopes."""
    technician = make_technician(api, **overrides)
    return grant_scopes(api, technician["id"], scopes)


def make_floor_technician(api, employee_code: str = "T-100", **overrides) -> dict:
    """A factory technician holding all three floor scopes."""
    return make_certified_technician(
        api,
        ["DRUM_FAB", "BEARING_INSTALL", "CONTROL_INTEGRATION"],
        employee_code=employee_code,
        full_name="Ann Ito",
        employer="FACTORY",
        **overrides,
    )


def make_qa_inspector(api, employee_code: str = "T-900", **overrides) -> dict:
    """A factory technician holding QA_SIGNOFF and nothing else, so the
    inspector never worked a station on the units they sign off."""
    return make_certified_technician(
        api,
        ["QA_SIGNOFF"],
        employee_code=employee_code,
        full_name="Ken Ono",
        employer="FACTORY",
        **overrides,
    )


# ─── Tier 2: the assembly floor ───────────────────────────────────────────
def make_build_order(api, model_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_build_order(f.build_order_payload(model_id, **overrides), PLANT_MANAGER)
    )


def release_build(api, build_order_id: str) -> dict:
    return get_success_data(api.release_to_floor(build_order_id, PLANT_MANAGER))


def log_station_pass(
    api,
    build_order_id: str,
    station: dict,
    technician_id: str,
    started_at: str,
    completed_at: str,
    **overrides,
) -> dict:
    """Record one PASS station log as the technician who performed the work."""
    payload = f.station_log_payload(
        station["id"],
        station["station_type"],
        started_at,
        completed_at,
        "PASS",
        **overrides,
    )
    return get_success_data(
        api.create_station_log(
            build_order_id, payload, make_technician_headers(technician_id)
        )
    )


def walk_build_to_qa_hold(
    api,
    build_order_id: str,
    stations: dict,
    technician_id: str,
    drum_start: str = DRUM_START,
    drum_end: str = DRUM_END,
    bearing_start: str = BEARING_START,
    bearing_end: str = BEARING_END,
    control_start: str = CONTROL_START,
    control_end: str = CONTROL_END,
    preload: float = IN_SPEC_PRELOAD_304,
) -> dict:
    """Drive a released unit through all three stations so it lands in QA_HOLD."""
    logs = {
        "drum": log_station_pass(
            api, build_order_id, stations["drum"], technician_id, drum_start, drum_end
        ),
        "bearing": log_station_pass(
            api,
            build_order_id,
            stations["bearing"],
            technician_id,
            bearing_start,
            bearing_end,
            bearing_preload_micron=preload,
        ),
        "control": log_station_pass(
            api,
            build_order_id,
            stations["control"],
            technician_id,
            control_start,
            control_end,
        ),
    }
    return logs


def make_floor_environment(api, model_overrides=None, certified_only: bool = True) -> dict:
    """A certified model, three stations, an all-scope floor technician and a
    QA inspector who has never worked a station."""
    overrides = model_overrides or {}
    env = (
        make_certified_model(api, **overrides)
        if certified_only
        else make_released_model(api, **overrides)
    )
    env["stations"] = make_three_stations(api)
    env["technician"] = make_floor_technician(api)
    env["inspector"] = make_qa_inspector(api)
    return env


def make_unit_in_qa_hold(api, env: dict, serial_number: str = "SN-0001", **overrides) -> dict:
    """Add one unit to an existing floor environment and drive it to QA_HOLD."""
    build = make_build_order(api, env["model"]["id"], serial_number=serial_number, **overrides)
    release_build(api, build["id"])
    logs = walk_build_to_qa_hold(
        api, build["id"], env["stations"], env["technician"]["id"]
    )
    build = get_success_data(api.get_build_order(build["id"], PLANT_MANAGER))
    return {"build": build, "logs": logs}


def make_accepted_unit(api, env: dict, serial_number: str = "SN-0001") -> dict:
    """Drive one unit all the way to ACCEPTED with rework_count 0."""
    unit = make_unit_in_qa_hold(api, env, serial_number=serial_number)
    unit["build"] = get_success_data(
        api.qa_signoff(
            unit["build"]["id"],
            f.qa_signoff_payload("APPROVE"),
            make_quality_inspector_headers(env["inspector"]["id"]),
        )
    )
    return unit


# ─── Tier 3: the distributor channel ──────────────────────────────────────
def make_distributor(api, **overrides) -> dict:
    return get_success_data(
        api.create_distributor(f.distributor_payload(**overrides), CHANNEL_MANAGER)
    )


def make_distributor_technician(
    api, distributor_id: str, employee_code: str, full_name: str = "Rosa Diaz"
) -> dict:
    return make_technician(
        api,
        employee_code=employee_code,
        full_name=full_name,
        employer="DISTRIBUTOR",
        distributor_id=distributor_id,
    )


def record_training(
    api,
    distributor_id: str,
    technician_id: str,
    training_module: str,
    completed_on: str = "2026-07-20",
) -> dict:
    return get_success_data(
        api.create_training_completion(
            distributor_id,
            f.training_completion_payload(
                technician_id, training_module, completed_on
            ),
            TRAINING_ADMIN,
        )
    )


def make_pending_distributor(api, **overrides) -> dict:
    """A distributor in PENDING_TRAINING with two technicians on its roster and
    no training recorded yet."""
    distributor = make_distributor(api, **overrides)
    first = make_distributor_technician(api, distributor["id"], "T-201", "Rosa Diaz")
    second = make_distributor_technician(api, distributor["id"], "T-202", "Sam Poe")
    return {
        "distributor": distributor,
        "technicians": [first, second],
        "headers": make_distributor_headers(distributor["id"]),
    }


def make_authorized_distributor(api, **overrides) -> dict:
    """Two distinct technicians covering INSTALLATION and PAYMENT_SYSTEMS, which
    is what moves the distributor to AUTHORIZED."""
    env = make_pending_distributor(api, **overrides)
    record_training(
        api, env["distributor"]["id"], env["technicians"][0]["id"], "INSTALLATION",
        "2026-07-20",
    )
    env["distributor"] = record_training(
        api, env["distributor"]["id"], env["technicians"][1]["id"], "PAYMENT_SYSTEMS",
        "2026-07-21",
    )
    return env


def make_service_technician(api, env: dict, scopes=None) -> dict:
    """Certify the distributor's first technician for field diagnostics."""
    scopes = scopes or ["DIAGNOSTICS_TOOL"]
    env["technicians"][0] = grant_scopes(api, env["technicians"][0]["id"], scopes)
    return env["technicians"][0]


# ─── Tier 4: parts, claims and quotes ─────────────────────────────────────
def make_service_part(api, **overrides) -> dict:
    return get_success_data(
        api.create_service_part(f.service_part_payload(**overrides), PRODUCT_ENGINEER)
    )


def adjust_stock(api, part_id: str, delta_qty: int, reason: str = "RECEIPT") -> dict:
    return get_success_data(
        api.create_stock_adjustment(
            part_id, f.stock_adjustment_payload(delta_qty, reason), PLANT_MANAGER
        )
    )


def make_stocked_part(api, on_hand_qty: int = 3, **overrides) -> dict:
    """A part created at zero stock and then received up to on_hand_qty."""
    part = make_service_part(api, **overrides)
    if on_hand_qty:
        part = adjust_stock(api, part["id"], on_hand_qty)
    return part


def read_part_version(api, part_id: str) -> int:
    """Read the part version the analyst will present as the OCC token."""
    part = get_success_data(api.get_service_part(part_id, WARRANTY_ANALYST))
    return part["version"]


def make_claim(
    api,
    build_order_id: str,
    part_id: str,
    distributor_env: dict,
    technician_id: str,
    **overrides,
) -> dict:
    """File a claim as the owning distributor identity."""
    payload = f.warranty_claim_payload(
        build_order_id,
        part_id,
        distributor_env["distributor"]["id"],
        technician_id,
        **overrides,
    )
    return get_success_data(api.create_warranty_claim(payload, distributor_env["headers"]))


def adjudicate_claim(api, claim_id: str, part_id: str, decision: str = "APPROVE", **overrides) -> dict:
    """Adjudicate with a freshly read part version so the OCC token is current."""
    payload = f.adjudicate_payload(
        read_part_version(api, part_id), decision, **overrides
    )
    return get_success_data(
        api.adjudicate_warranty_claim(claim_id, payload, WARRANTY_ANALYST)
    )


def make_warranty_environment(api, on_hand_qty: int = 3, part_overrides=None) -> dict:
    """The whole warranty precondition chain: a certified model with one
    ACCEPTED unit, an AUTHORIZED distributor whose technician is certified for
    field diagnostics, and a stocked service part."""
    env = make_floor_environment(api)
    unit = make_accepted_unit(api, env)
    channel = make_authorized_distributor(api)
    service_technician = make_service_technician(api, channel)
    part = make_stocked_part(api, on_hand_qty, **(part_overrides or {}))
    return {
        "model": env["model"],
        "dossier": env["dossier"],
        "stations": env["stations"],
        "technician": env["technician"],
        "inspector": env["inspector"],
        "build": unit["build"],
        "logs": unit["logs"],
        "distributor": channel["distributor"],
        "distributor_headers": channel["headers"],
        "distributor_technicians": channel["technicians"],
        "service_technician": service_technician,
        "channel": channel,
        "part": part,
    }


def make_submitted_claim(api, env: dict, **overrides) -> dict:
    """One SUBMITTED claim against the environment's accepted unit and part."""
    return make_claim(
        api,
        env["build"]["id"],
        env["part"]["id"],
        env["channel"],
        env["service_technician"]["id"],
        **overrides,
    )


def make_quote(api, distributor_env: dict, **overrides) -> dict:
    return get_success_data(
        api.create_quote(
            f.quote_payload(distributor_env["distributor"]["id"], **overrides),
            distributor_env["headers"],
        )
    )


def read_quote_version(api, quote_id: str, distributor_env: dict) -> int:
    """Re-read the quote so the next line carries a current OCC token."""
    quote = get_success_data(api.get_quote(quote_id, distributor_env["headers"]))
    return quote["version"]


def add_quote_line(api, quote_id: str, distributor_env: dict, model_id: str, **overrides) -> dict:
    """Add one line, always presenting the quote's current version."""
    payload = f.quote_line_payload(
        model_id, read_quote_version(api, quote_id, distributor_env), **overrides
    )
    return get_success_data(
        api.create_quote_line(quote_id, payload, distributor_env["headers"])
    )


# ─── Tier 5: pytest fixtures over the reusable states ─────────────────────
@pytest.fixture
def model(api):
    """One ON_PREMISES machine model in DRAFT."""
    return make_model(api)


@pytest.fixture
def certified_model(api):
    """A model in CERTIFIED plus the dossier that certified it."""
    return make_certified_model(api)


@pytest.fixture
def released_model(api):
    """A model advanced all the way to RELEASED."""
    return make_released_model(api)


@pytest.fixture
def three_stations(api):
    """One assembly station per station type."""
    return make_three_stations(api)


@pytest.fixture
def floor_environment(api):
    """A certified model, three stations, a floor technician and a QA inspector."""
    return make_floor_environment(api)


@pytest.fixture
def unit_in_qa_hold(api, floor_environment):
    """One unit driven through all three stations into QA_HOLD."""
    unit = make_unit_in_qa_hold(api, floor_environment)
    return {**floor_environment, **unit}


@pytest.fixture
def accepted_unit(api, floor_environment):
    """One unit driven all the way to ACCEPTED with no rework."""
    unit = make_accepted_unit(api, floor_environment)
    return {**floor_environment, **unit}


@pytest.fixture
def pending_distributor(api):
    """A distributor in PENDING_TRAINING with two technicians and no training."""
    return make_pending_distributor(api)


@pytest.fixture
def authorized_distributor(api):
    """A distributor moved to AUTHORIZED by two distinct trained technicians."""
    return make_authorized_distributor(api)


@pytest.fixture
def warranty_environment(api):
    """The full claim precondition chain: accepted unit, authorised distributor,
    certified service technician and a stocked part."""
    return make_warranty_environment(api)


@pytest.fixture
def submitted_claim(api, warranty_environment):
    """One SUBMITTED warranty claim inside a complete warranty environment."""
    claim = make_submitted_claim(api, warranty_environment)
    return {**warranty_environment, "claim": claim}
