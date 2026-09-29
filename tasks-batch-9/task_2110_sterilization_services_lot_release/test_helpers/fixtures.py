"""Composite setup helpers.

Every test starts against an empty database, so each helper builds its own
preconditions from scratch using only the endpoints the PRD declares. Setup
calls use the lenient validator so a broken precondition surfaces as a setup
failure rather than as a confusing assertion inside a test.
"""

import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK, TEST_DEFAULTS
from .factories import (
    create_adverse_event_payload,
    create_chamber_payload,
    create_cycle_payload,
    create_customer_payload,
    create_dose_audit_payload,
    create_indicator_payload,
    create_load_position_payload,
    create_lot_payload,
    create_permit_payload,
    create_product_payload,
    create_qualification_payload,
    create_recipe_payload,
    create_residual_test_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_rep_headers,
    make_cycle_operator_headers,
    make_dosimetry_analyst_headers,
    make_quality_release_officer_headers,
)

_SERIAL_SEQ = itertools.count(1)

ADMIN = TEST_USERS["regulatory_admin_headers"]
OPERATOR_ID = TEST_DEFAULTS["OPERATOR_USER_ID"]
ANALYST_ID = TEST_DEFAULTS["ANALYST_USER_ID"]
OFFICER_ID = TEST_DEFAULTS["OFFICER_USER_ID"]


def operator(user_id: str = OPERATOR_ID) -> dict:
    return make_cycle_operator_headers(user_id)


def analyst(user_id: str = ANALYST_ID) -> dict:
    return make_dosimetry_analyst_headers(user_id)


def officer(user_id: str = OFFICER_ID) -> dict:
    return make_quality_release_officer_headers(user_id)


# ============================================================ primitives ===
def set_clock(to_iso8601: str) -> None:
    get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_customer(**overrides) -> dict:
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), ADMIN)
    )


def create_product(customer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_product(create_product_payload(customer_id, **overrides), ADMIN)
    )


def create_permit(**overrides) -> dict:
    return get_success_data(
        api_client.create_permit(create_permit_payload(**overrides), ADMIN)
    )


def create_chamber(permit_id: str, modality: str = "GAMMA", **overrides) -> dict:
    return get_success_data(
        api_client.create_chamber(
            create_chamber_payload(permit_id, modality, **overrides), ADMIN
        )
    )


def create_recipe(modality: str = "GAMMA", approved: bool = True, **overrides) -> dict:
    recipe = get_success_data(
        api_client.create_recipe(create_recipe_payload(modality, **overrides), ADMIN)
    )
    if approved:
        recipe = get_success_data(api_client.approve_recipe(recipe["id"], ADMIN))
    return recipe


def create_qualification(product_id: str, recipe_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_qualification(
            create_qualification_payload(product_id, recipe_id, **overrides), ADMIN
        )
    )


def record_dose_audit(qualification_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_dose_audit(
            qualification_id, create_dose_audit_payload(**overrides), ADMIN
        )
    )


def create_qualified_qualification(
    product_id: str,
    recipe_id: str,
    positives: int = 0,
    performed_at: str = TEST_DEFAULTS["AUDIT_PERFORMED_AT"],
    **overrides,
) -> dict:
    """Open a qualification and drive it out of PENDING with one dose audit."""
    qualification = create_qualification(product_id, recipe_id, **overrides)
    record_dose_audit(
        qualification["id"], performed_at=performed_at, positives=positives
    )
    return get_qualification(qualification["id"])


def create_lot(customer_id: str, product_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_lot(
            create_lot_payload(customer_id, product_id, **overrides),
            make_customer_rep_headers(customer_id),
        )
    )


def create_cycle(chamber_id: str, recipe_id: str, operator_user_id: str = OPERATOR_ID, **overrides) -> dict:
    return get_success_data(
        api_client.create_cycle(
            create_cycle_payload(chamber_id, recipe_id, **overrides),
            operator(operator_user_id),
        )
    )


def add_load_position(
    cycle_id: str,
    lot_id: str,
    expected_cycle_version: int = None,
    operator_user_id: str = OPERATOR_ID,
    **overrides,
) -> dict:
    """Place a lot into a load-map slot, reading the parent cycle's current
    version as the optimistic handle unless one was supplied."""
    headers = operator(operator_user_id)
    if expected_cycle_version is None:
        expected_cycle_version = get_success_data(
            api_client.get_cycle(cycle_id, headers)
        )["version"]
    return get_success_data(
        api_client.create_load_position(
            cycle_id,
            create_load_position_payload(lot_id, expected_cycle_version, **overrides),
            headers,
        )
    )


def remove_load_position(cycle_id: str, position_id: str, operator_user_id: str = OPERATOR_ID):
    return api_client.delete_load_position(
        cycle_id, position_id, operator(operator_user_id)
    )


def place_indicator(position_id: str, operator_user_id: str = OPERATOR_ID, **overrides) -> dict:
    return get_success_data(
        api_client.create_indicator(
            position_id, create_indicator_payload(**overrides), operator(operator_user_id)
        )
    )


def place_required_indicators(
    position_id: str, recipe: dict, prefix: str = None, operator_user_id: str = OPERATOR_ID
) -> dict:
    """Place exactly the indicator census the recipe demands into one slot.

    `serial_code` is unique across the whole facility (PRD 2.7 step 6), so the
    default prefix is minted fresh on every call: a test that walks two cycles
    through this helper must not collide on D-MIN-1.
    """
    if prefix is None:
        prefix = "D%d" % next(_SERIAL_SEQ)
    placed = {"min_zone": [], "routine": [], "biological": []}
    for i in range(recipe["required_min_zone_dosimeters"]):
        placed["min_zone"].append(
            place_indicator(
                position_id,
                operator_user_id,
                indicator_type="DOSIMETER",
                placement_zone="MIN_DOSE",
                serial_code=f"{prefix}-MIN-{i + 1}",
            )
        )
    for i in range(recipe["required_routine_dosimeters"]):
        placed["routine"].append(
            place_indicator(
                position_id,
                operator_user_id,
                indicator_type="DOSIMETER",
                placement_zone="ROUTINE",
                serial_code=f"{prefix}-RT-{i + 1}",
            )
        )
    for i in range(recipe["required_biological_indicators"]):
        placed["biological"].append(
            place_indicator(
                position_id,
                operator_user_id,
                indicator_type="BIOLOGICAL",
                placement_zone="ROUTINE",
                serial_code=f"{prefix}-BI-{i + 1}",
                spore_population=1000000,
            )
        )
    return placed


def sign_ready(cycle_id: str, operator_user_id: str = OPERATOR_ID) -> dict:
    return get_success_data(api_client.ready_cycle(cycle_id, operator(operator_user_id)))


def start_cycle(cycle_id: str, operator_user_id: str = OPERATOR_ID) -> dict:
    return get_success_data(api_client.start_cycle(cycle_id, operator(operator_user_id)))


def complete_cycle(cycle_id: str, operator_user_id: str = OPERATOR_ID) -> dict:
    return get_success_data(api_client.complete_cycle(cycle_id, operator(operator_user_id)))


def abort_cycle(cycle_id: str, reason: str = "chamber pressure alarm during dwell",
                operator_user_id: str = OPERATOR_ID) -> dict:
    return get_success_data(
        api_client.abort_cycle(cycle_id, {"reason": reason}, operator(operator_user_id))
    )


def record_reading(
    indicator_id: str,
    measured_dose_kgy: float = None,
    bi_result: str = None,
    analyst_user_id: str = ANALYST_ID,
) -> dict:
    payload = {}
    if measured_dose_kgy is not None:
        payload["measured_dose_kgy"] = measured_dose_kgy
    if bi_result is not None:
        payload["bi_result"] = bi_result
    return get_success_data(
        api_client.record_reading(indicator_id, payload, analyst(analyst_user_id))
    )


def close_dosimetry(cycle_id: str, analyst_user_id: str = ANALYST_ID) -> dict:
    return get_success_data(
        api_client.dosimetry_close(cycle_id, analyst(analyst_user_id))
    )


def release_lot(lot_id: str, release_mode: str = "PARAMETRIC",
                officer_user_id: str = OFFICER_ID) -> dict:
    return get_success_data(
        api_client.release_lot(
            lot_id, {"release_mode": release_mode}, officer(officer_user_id)
        )
    )


def open_aeration_record(lot_id: str, operator_user_id: str = OPERATOR_ID) -> dict:
    return get_success_data(
        api_client.create_aeration_record(lot_id, operator(operator_user_id))
    )


def record_residual_test(
    record_id: str, eto_residual_ppm: float, ech_residual_ppm: float,
    analyst_user_id: str = ANALYST_ID,
) -> dict:
    return get_success_data(
        api_client.record_residual_test(
            record_id,
            create_residual_test_payload(
                eto_residual_ppm=eto_residual_ppm, ech_residual_ppm=ech_residual_ppm
            ),
            analyst(analyst_user_id),
        )
    )


def report_adverse_event(lot_id: str, expected_lot_version: int = None,
                         reporter_headers: dict = None, **overrides) -> dict:
    headers = reporter_headers or officer()
    if expected_lot_version is None:
        expected_lot_version = get_success_data(
            api_client.get_lot(lot_id, headers)
        )["version"]
    return get_success_data(
        api_client.create_adverse_event(
            lot_id, create_adverse_event_payload(expected_lot_version, **overrides), headers
        )
    )


def disposition_adverse_event(event_id: str, disposition: str,
                              officer_user_id: str = OFFICER_ID) -> dict:
    return get_success_data(
        api_client.disposition_adverse_event(
            event_id, {"disposition": disposition}, officer(officer_user_id)
        )
    )


def set_chamber_status(chamber_id: str, status: str) -> dict:
    return get_success_data(
        api_client.set_chamber_status(chamber_id, {"status": status}, ADMIN)
    )


def set_permit_status(permit_id: str, status: str) -> dict:
    return get_success_data(
        api_client.set_permit_status(permit_id, {"status": status}, ADMIN)
    )


def set_customer_status(customer_id: str, status: str) -> dict:
    return get_success_data(
        api_client.set_customer_status(customer_id, {"status": status}, ADMIN)
    )


# ============================================================== readers ====
def get_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_lot(lot_id, ADMIN))


def get_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.get_cycle(cycle_id, operator()))


def get_permit(permit_id: str) -> dict:
    return get_success_data(api_client.get_permit(permit_id, ADMIN))


def get_chamber(chamber_id: str) -> dict:
    return get_success_data(api_client.get_chamber(chamber_id, ADMIN))


def get_customer(customer_id: str) -> dict:
    return get_success_data(api_client.get_customer(customer_id, ADMIN))


def get_product(product_id: str) -> dict:
    return get_success_data(api_client.get_product(product_id, ADMIN))


def get_recipe(recipe_id: str) -> dict:
    return get_success_data(api_client.get_recipe(recipe_id, ADMIN))


def get_qualification(qualification_id: str) -> dict:
    return get_success_data(api_client.get_qualification(qualification_id, ADMIN))


def get_load_position(position_id: str) -> dict:
    return get_success_data(api_client.get_load_position(position_id, operator()))


def list_positions_of_cycle(cycle_id: str) -> list:
    body = api_client.list_load_positions(operator(), params={"cycle_id": cycle_id}).json()
    return body["data"]


def fetch_indicator(position_id: str, indicator_id: str) -> dict:
    body = api_client.list_indicators(position_id, operator()).json()
    for row in body["data"]:
        if row["id"] == indicator_id:
            return row
    raise AssertionError(f"indicator {indicator_id} not found in slot {position_id}")


def fetch_aeration_record(lot_id: str, record_id: str) -> dict:
    body = api_client.list_aeration_records(lot_id, operator()).json()
    for row in body["data"]:
        if row["id"] == record_id:
            return row
    raise AssertionError(f"aeration record {record_id} not found on lot {lot_id}")


def fetch_adverse_event(lot_id: str, event_id: str) -> dict:
    body = api_client.list_adverse_events(lot_id, officer()).json()
    for row in body["data"]:
        if row["id"] == event_id:
            return row
    raise AssertionError(f"adverse event {event_id} not found on lot {lot_id}")


# =========================================================== composites ====
def setup_reference_data(
    modality: str = "GAMMA",
    clock: str = DEFAULT_CLOCK,
    customer_overrides: dict = None,
    product_overrides: dict = None,
    permit_overrides: dict = None,
    chamber_overrides: dict = None,
    recipe_overrides: dict = None,
    qualification_overrides: dict = None,
    audit_positives: int = 0,
    audit_performed_at: str = TEST_DEFAULTS["AUDIT_PERFORMED_AT"],
    qualify: bool = True,
) -> dict:
    """Customer + product + permit + chamber + approved recipe + a
    qualification carried out of PENDING by one dose audit."""
    if clock:
        set_clock(clock)
    customer = create_customer(**(customer_overrides or {}))
    product = create_product(customer["id"], **(product_overrides or {}))
    permit = create_permit(**(permit_overrides or {}))
    chamber = create_chamber(permit["id"], modality, **(chamber_overrides or {}))
    recipe = create_recipe(modality, **(recipe_overrides or {}))
    if qualify:
        qualification = create_qualified_qualification(
            product["id"],
            recipe["id"],
            positives=audit_positives,
            performed_at=audit_performed_at,
            **(qualification_overrides or {}),
        )
    else:
        qualification = create_qualification(
            product["id"], recipe["id"], **(qualification_overrides or {})
        )
    return {
        "customer": customer,
        "product": product,
        "permit": permit,
        "chamber": chamber,
        "recipe": recipe,
        "qualification": qualification,
    }


def build_cycle_scenario(
    stage: str = "closed",
    modality: str = "GAMMA",
    env: dict = None,
    lot_overrides: dict = None,
    cycle_overrides: dict = None,
    pallet_count: int = 2,
    position_zone: str = "MIN_DOSE",
    min_zone_dose: float = 28.50,
    routine_dose: float = 30.00,
    max_zone_dose: float = 30.00,
    bi_result: str = "NEGATIVE",
    operator_user_id: str = OPERATOR_ID,
    analyst_user_id: str = ANALYST_ID,
    place_indicators: bool = True,
    **reference_kwargs,
):
    """Walk one lot and one cycle to `stage`.

    Stages, in order: planned, loading, ready, running, completed, review
    (every indicator read, cycle in DOSIMETRY_REVIEW) and closed (dosimetry
    closed). Returns the reference data plus lot, cycle, position and the
    indicators placed in that position.
    """
    stages = ["planned", "loading", "ready", "running", "completed", "review", "closed"]
    assert stage in stages, f"unknown stage {stage}"
    reached = stages.index(stage)

    env = dict(env or setup_reference_data(modality=modality, **reference_kwargs))
    lot = create_lot(env["customer"]["id"], env["product"]["id"], **(lot_overrides or {}))
    cycle_kwargs = dict(cycle_overrides or {})
    if modality == "ETO" and "raw_eto_charge_kg" not in cycle_kwargs:
        cycle_kwargs["raw_eto_charge_kg"] = 100.0
    cycle = create_cycle(
        env["chamber"]["id"], env["recipe"]["id"], operator_user_id, **cycle_kwargs
    )
    env.update({"lot": lot, "cycle": cycle, "position": None, "indicators": None})
    if reached < stages.index("loading"):
        return env

    position = add_load_position(
        cycle["id"],
        lot["id"],
        operator_user_id=operator_user_id,
        pallet_count=pallet_count,
        zone=position_zone,
    )
    env["position"] = position
    indicators = (
        place_required_indicators(position["id"], env["recipe"], operator_user_id=operator_user_id)
        if place_indicators
        else {"min_zone": [], "routine": [], "biological": []}
    )
    env["indicators"] = indicators
    if reached < stages.index("ready"):
        return env

    sign_ready(cycle["id"], operator_user_id)
    if reached < stages.index("running"):
        return env

    start_cycle(cycle["id"], operator_user_id)
    if reached < stages.index("completed"):
        return env

    complete_cycle(cycle["id"], operator_user_id)
    if reached < stages.index("review"):
        return env

    for indicator in indicators["min_zone"]:
        record_reading(indicator["id"], measured_dose_kgy=min_zone_dose,
                       analyst_user_id=analyst_user_id)
    for indicator in indicators["routine"]:
        record_reading(indicator["id"], measured_dose_kgy=routine_dose,
                       analyst_user_id=analyst_user_id)
    for indicator in indicators["biological"]:
        record_reading(indicator["id"], bi_result=bi_result, analyst_user_id=analyst_user_id)
    if reached < stages.index("closed"):
        return env

    close_dosimetry(cycle["id"], analyst_user_id)
    env["cycle"] = get_cycle(cycle["id"])
    env["lot"] = get_lot(lot["id"])
    return env


def setup_quarantined_lot(**kwargs) -> dict:
    """A lot carried all the way to QUARANTINE behind a DOSE_CONFORMING
    cycle - the state every release test starts from."""
    return build_cycle_scenario(stage="closed", **kwargs)


def setup_released_lot(release_mode: str = "PARAMETRIC",
                       officer_user_id: str = OFFICER_ID, **kwargs) -> dict:
    env = setup_quarantined_lot(**kwargs)
    release_lot(env["lot"]["id"], release_mode, officer_user_id)
    env["lot"] = get_lot(env["lot"]["id"])
    return env


def setup_aerating_lot(clock_at_open: str = "2026-08-12T08:00:00Z", **kwargs) -> dict:
    """An EtO lot in QUARANTINE / AERATING with an open aeration record."""
    kwargs.setdefault("modality", "ETO")
    kwargs.setdefault("product_overrides", {"requires_aeration": True})
    env = setup_quarantined_lot(**kwargs)
    if clock_at_open:
        set_clock(clock_at_open)
    env["aeration_record"] = open_aeration_record(env["lot"]["id"])
    env["lot"] = get_lot(env["lot"]["id"])
    return env
