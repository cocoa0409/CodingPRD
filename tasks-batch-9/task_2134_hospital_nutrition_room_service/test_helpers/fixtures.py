"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only -- the database is empty at the start of each test. Setup calls
use the lenient success validator so a broken precondition surfaces as a clear
"setup step failed" message rather than as a confusing assertion later on.
"""
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .factories import (
    assess_consult_payload,
    create_consult_payload,
    create_diet_order_payload,
    create_diet_rule_payload,
    create_dinner_period_payload,
    create_meal_order_payload,
    create_meal_period_payload,
    create_menu_item_payload,
    create_patient_payload,
    create_procedure_hold_payload,
    create_supplement_order_payload,
    create_survey_payload,
    create_ward_payload,
    line,
)
from .test_users import (
    DIETITIAN_1,
    DIETITIAN_2,
    PHYSICIAN_1,
    TEST_USERS,
    TRAY_AIDE_1,
    TRAY_AIDE_2,
    make_dietitian_headers,
    make_physician_headers,
    make_tray_aide_headers,
)

MANAGER = TEST_USERS["nutrition_manager_headers"]
CLERK = TEST_USERS["diet_clerk_headers"]
PHYSICIAN = TEST_USERS["physician_headers"]
DIETITIAN = TEST_USERS["dietitian_headers"]
AIDE = TEST_USERS["tray_aide_headers"]
AIDE_2 = TEST_USERS["tray_aide_2_headers"]

DEFAULT_CLOCK = "2026-08-02T09:00:00Z"


# --- Primitives --------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the server's logical UTC clock."""
    return get_success_data(api.set_clock(to_iso8601, MANAGER))


def new_ward(**overrides) -> dict:
    return get_success_data(api.create_ward(create_ward_payload(**overrides), MANAGER))


def new_patient(ward_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_patient(create_patient_payload(ward_id, **overrides), CLERK)
    )


def new_diet_rule(spec_key: str = "REGULAR_STD", **overrides) -> dict:
    return get_success_data(
        api.create_diet_rule(create_diet_rule_payload(spec_key, **overrides), DIETITIAN)
    )


def new_menu_item(spec_key: str = "SOU-BRO", **overrides) -> dict:
    return get_success_data(
        api.create_menu_item(create_menu_item_payload(spec_key, **overrides), MANAGER)
    )


def new_menu_items(spec_keys: Iterable[str]) -> Dict[str, dict]:
    """Publish several catalogue items; returns {item_code: menu item}."""
    return {key: new_menu_item(key) for key in spec_keys}


def new_meal_period(ward_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_meal_period(create_meal_period_payload(ward_id, **overrides), MANAGER)
    )


def new_dinner_period(ward_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_meal_period(create_dinner_period_payload(ward_id, **overrides), MANAGER)
    )


def lock_forecast(period_id: str, variant: str = "CENSUS_BASED") -> dict:
    return get_success_data(api.lock_forecast(period_id, variant, MANAGER))


def open_service(period_id: str) -> dict:
    return get_success_data(api.open_service(period_id, MANAGER))


def lock_and_open(period_id: str, variant: str = "CENSUS_BASED") -> dict:
    lock_forecast(period_id, variant)
    return open_service(period_id)


def close_period(period_id: str) -> dict:
    return get_success_data(api.close_meal_period(period_id, MANAGER))


def read_diet_order(order_id: str) -> dict:
    return get_success_data(api.get_diet_order(order_id, CLERK))


def diet_order_version(order_id: str) -> int:
    return read_diet_order(order_id)["version"]


def read_meal_order(order_id: str) -> dict:
    return get_success_data(api.get_meal_order(order_id, CLERK))


def read_meal_period(period_id: str) -> dict:
    return get_success_data(api.get_meal_period(period_id, MANAGER))


def read_patient(patient_id: str) -> dict:
    return get_success_data(api.get_patient(patient_id, CLERK))


def read_ward(ward_id: str) -> dict:
    return get_success_data(api.get_ward(ward_id, MANAGER))


def read_consult(consult_id: str) -> dict:
    return get_success_data(api.get_consult(consult_id, DIETITIAN))


def read_supplement_order(order_id: str) -> dict:
    return get_success_data(api.get_supplement_order(order_id, DIETITIAN))


def read_procedure_hold(hold_id: str) -> dict:
    return get_success_data(api.get_procedure_hold(hold_id, PHYSICIAN))


def lines_of(meal_order_id: str) -> List[dict]:
    """Tray lines of one meal order, in the order the listing returns them."""
    body = api.list_meal_order_lines(CLERK, params={"meal_order_id": meal_order_id})
    return get_success_data(body)


# --- Tier 1: diet order state progression ------------------------------------

def draft_diet_order(
    patient_id: str,
    primary_diet_rule_id: str,
    physician_user_id: str = PHYSICIAN_1,
    **overrides,
) -> dict:
    """Create a DRAFT diet order stamped with the given opaque prescriber id."""
    return get_success_data(
        api.create_diet_order(
            create_diet_order_payload(patient_id, primary_diet_rule_id, **overrides),
            make_physician_headers(physician_user_id),
        )
    )


def submit_diet_order(order_id: str, physician_user_id: str = PHYSICIAN_1) -> dict:
    return get_success_data(
        api.submit_diet_order(order_id, make_physician_headers(physician_user_id))
    )


def cosign_diet_order(order_id: str, dietitian_user_id: str = DIETITIAN_1) -> dict:
    return get_success_data(
        api.cosign_diet_order(order_id, make_dietitian_headers(dietitian_user_id))
    )


def create_active_diet_order(
    patient_id: str,
    primary_diet_rule_id: str,
    physician_user_id: str = PHYSICIAN_1,
    dietitian_user_id: str = DIETITIAN_1,
    **overrides,
) -> dict:
    """Draft, submit and cosign a diet order so it reaches ACTIVE.

    Assumes the primary rule requires a dietitian cosign, which is the default
    for a published therapeutic diet rule.
    """
    order = draft_diet_order(
        patient_id, primary_diet_rule_id, physician_user_id, **overrides
    )
    submit_diet_order(order["id"], physician_user_id)
    return cosign_diet_order(order["id"], dietitian_user_id)


def create_pending_cosign_diet_order(
    patient_id: str,
    primary_diet_rule_id: str,
    physician_user_id: str = PHYSICIAN_1,
    **overrides,
) -> dict:
    order = draft_diet_order(
        patient_id, primary_diet_rule_id, physician_user_id, **overrides
    )
    return submit_diet_order(order["id"], physician_user_id)


# --- Tier 2: tray placement ---------------------------------------------------

def place_tray(
    patient_id: str,
    meal_period_id: str,
    diet_order_id: str,
    tray_lines: Sequence[dict],
    expected_diet_order_version: Optional[int] = None,
) -> dict:
    """Place a meal order, reading a fresh diet order version when none is given."""
    if expected_diet_order_version is None:
        expected_diet_order_version = diet_order_version(diet_order_id)
    return get_success_data(
        api.create_meal_order(
            create_meal_order_payload(
                patient_id,
                meal_period_id,
                diet_order_id,
                expected_diet_order_version,
                list(tray_lines),
            ),
            CLERK,
        )
    )


def validate_tray(meal_order_id: str) -> dict:
    return get_success_data(api.validate_meal_order(meal_order_id, CLERK))


def plate_tray(meal_order_id: str, aide_user_id: str = TRAY_AIDE_1) -> dict:
    """Walk a VALIDATED tray to PLATED."""
    headers = make_tray_aide_headers(aide_user_id)
    get_success_data(api.start_production(meal_order_id, headers))
    return get_success_data(api.plate_meal_order(meal_order_id, headers))


def pass_accuracy_check(
    meal_order_id: str, observed_line_count: int = 1, aide_user_id: str = TRAY_AIDE_1
) -> dict:
    return get_success_data(
        api.accuracy_check(
            meal_order_id,
            {"observed_line_count": observed_line_count},
            make_tray_aide_headers(aide_user_id),
        )
    )


def pass_temperature_check(
    meal_order_id: str,
    hot_probe_celsius: Optional[float] = 64.0,
    cold_probe_celsius: Optional[float] = None,
    aide_user_id: str = TRAY_AIDE_2,
) -> dict:
    payload = {}
    if hot_probe_celsius is not None:
        payload["hot_probe_celsius"] = hot_probe_celsius
    if cold_probe_celsius is not None:
        payload["cold_probe_celsius"] = cold_probe_celsius
    return get_success_data(
        api.temperature_check(meal_order_id, payload, make_tray_aide_headers(aide_user_id))
    )


def deliver_tray(meal_order_id: str, aide_user_id: str = TRAY_AIDE_1) -> dict:
    return get_success_data(
        api.deliver_meal_order(meal_order_id, make_tray_aide_headers(aide_user_id))
    )


# --- Tier 3: full room-service scenario --------------------------------------

def setup_tray_scenario(
    *,
    ward_overrides: Optional[dict] = None,
    rule_key: str = "REGULAR_STD",
    rule_overrides: Optional[dict] = None,
    patient_overrides: Optional[dict] = None,
    period_overrides: Optional[dict] = None,
    diet_order_overrides: Optional[dict] = None,
    menu_keys: Sequence[str] = ("SOU-BRO",),
    tray_lines: Optional[Sequence[Tuple[str, int]]] = None,
    clock: Optional[str] = DEFAULT_CLOCK,
    forecast_variant: Optional[str] = None,
    open_for_service: bool = False,
    place_order: bool = True,
    physician_user_id: str = PHYSICIAN_1,
    dietitian_user_id: str = DIETITIAN_1,
) -> dict:
    """Build the standard room-service preamble.

    Ward, therapeutic rule, menu catalogue, admitted patient, ACTIVE diet order,
    meal period (optionally forecast-locked and opened), clock, and a
    PENDING_VALIDATION tray. Returns a dict of every entity created.
    """
    ward = new_ward(**(ward_overrides or {}))
    rule = new_diet_rule(rule_key, **(rule_overrides or {}))
    menu = new_menu_items(menu_keys)
    patient = new_patient(ward["id"], **(patient_overrides or {}))
    diet_order = create_active_diet_order(
        patient["id"],
        rule["id"],
        physician_user_id,
        dietitian_user_id,
        **(diet_order_overrides or {}),
    )
    period = new_meal_period(ward["id"], **(period_overrides or {}))
    if forecast_variant:
        period = lock_forecast(period["id"], forecast_variant)
    if open_for_service:
        period = open_service(period["id"])
    if clock:
        set_clock(clock)

    meal_order = None
    if place_order:
        if tray_lines is None:
            first_key = list(menu.keys())[0]
            tray_lines = ((first_key, 1),)
        payload_lines = [line(menu[key]["id"], qty) for key, qty in tray_lines]
        meal_order = place_tray(
            patient["id"], period["id"], diet_order["id"], payload_lines
        )

    return {
        "ward": ward,
        "rule": rule,
        "menu": menu,
        "patient": patient,
        "diet_order": diet_order,
        "diet_order_version": diet_order["version"],
        "period": period,
        "meal_order": meal_order,
    }


def setup_validated_tray(**kwargs) -> dict:
    """Standard scenario with the tray walked through to VALIDATED."""
    scenario = setup_tray_scenario(**kwargs)
    scenario["meal_order"] = validate_tray(scenario["meal_order"]["id"])
    return scenario


def setup_plated_tray(**kwargs) -> dict:
    """Standard IN_SERVICE scenario with the tray PLATED and qa NOT_CHECKED."""
    kwargs.setdefault("forecast_variant", "CENSUS_BASED")
    kwargs.setdefault("open_for_service", True)
    scenario = setup_validated_tray(**kwargs)
    scenario["meal_order"] = plate_tray(scenario["meal_order"]["id"])
    return scenario


def setup_accuracy_passed_tray(observed_line_count: int = 1, **kwargs) -> dict:
    """PLATED tray whose accuracy check passed, recorded by the first aide."""
    scenario = setup_plated_tray(**kwargs)
    scenario["meal_order"] = pass_accuracy_check(
        scenario["meal_order"]["id"], observed_line_count, TRAY_AIDE_1
    )
    return scenario


def setup_temp_passed_tray(
    observed_line_count: int = 1,
    hot_probe_celsius: Optional[float] = 64.0,
    cold_probe_celsius: Optional[float] = None,
    **kwargs,
) -> dict:
    """PLATED tray whose quality dimension has reached TEMP_PASSED."""
    scenario = setup_accuracy_passed_tray(observed_line_count, **kwargs)
    scenario["meal_order"] = pass_temperature_check(
        scenario["meal_order"]["id"], hot_probe_celsius, cold_probe_celsius, TRAY_AIDE_2
    )
    return scenario


def setup_delivered_tray(
    deliver_at: str = "2026-08-02T12:00:00Z",
    observed_line_count: int = 1,
    hot_probe_celsius: Optional[float] = 64.0,
    cold_probe_celsius: Optional[float] = None,
    **kwargs,
) -> dict:
    """Full lifecycle through DELIVERED, delivered at the given logical instant."""
    scenario = setup_temp_passed_tray(
        observed_line_count, hot_probe_celsius, cold_probe_celsius, **kwargs
    )
    set_clock(deliver_at)
    scenario["meal_order"] = deliver_tray(scenario["meal_order"]["id"])
    return scenario


# --- Tier 4: procedure holds --------------------------------------------------

def new_procedure_hold(
    patient_id: str, physician_user_id: str = PHYSICIAN_1, **overrides
) -> dict:
    return get_success_data(
        api.create_procedure_hold(
            create_procedure_hold_payload(patient_id, **overrides),
            make_physician_headers(physician_user_id),
        )
    )


def activate_procedure_hold(hold_id: str, physician_user_id: str = PHYSICIAN_1) -> dict:
    return get_success_data(
        api.activate_procedure_hold(hold_id, make_physician_headers(physician_user_id))
    )


def put_patient_under_hold(
    patient_id: str,
    npo_kind: str = "NPO_STRICT",
    hold_start_at: str = "2026-08-02T06:00:00Z",
    hold_end_at: str = "2026-08-02T20:00:00Z",
    **overrides,
) -> dict:
    """Book and activate a hold so the patient's npo_status leaves NONE."""
    hold = new_procedure_hold(
        patient_id,
        npo_kind=npo_kind,
        hold_start_at=hold_start_at,
        hold_end_at=hold_end_at,
        **overrides,
    )
    return activate_procedure_hold(hold["id"])


# --- Tier 5: consults, supplements and surveys --------------------------------

def new_consult(
    patient_id: str, requester_headers: Optional[dict] = None, **overrides
) -> dict:
    return get_success_data(
        api.create_consult(
            create_consult_payload(patient_id, **overrides),
            requester_headers or PHYSICIAN,
        )
    )


def assign_consult(consult_id: str, dietitian_user_id: str = DIETITIAN_1) -> dict:
    return get_success_data(
        api.assign_consult(
            consult_id, dietitian_user_id, make_dietitian_headers(dietitian_user_id)
        )
    )


def assess_consult(
    consult_id: str, dietitian_user_id: str = DIETITIAN_1, **assessment
) -> dict:
    return get_success_data(
        api.assess_consult(
            consult_id,
            assess_consult_payload(**assessment),
            make_dietitian_headers(dietitian_user_id),
        )
    )


def sign_consult(consult_id: str, dietitian_user_id: str = DIETITIAN_1) -> dict:
    return get_success_data(
        api.sign_consult(consult_id, make_dietitian_headers(dietitian_user_id))
    )


def setup_assessed_consult(
    *,
    patient_overrides: Optional[dict] = None,
    requester_headers: Optional[dict] = None,
    consult_overrides: Optional[dict] = None,
    assessment: Optional[dict] = None,
    menu_keys: Sequence[str] = ("SUP-ORS",),
    dietitian_user_id: str = DIETITIAN_1,
) -> dict:
    """Ward + patient + menu item + consult walked to ASSESSED."""
    ward = new_ward()
    menu = new_menu_items(menu_keys)
    patient = new_patient(ward["id"], **(patient_overrides or {}))
    consult = new_consult(
        patient["id"], requester_headers, **(consult_overrides or {})
    )
    assign_consult(consult["id"], dietitian_user_id)
    consult = assess_consult(
        consult["id"], dietitian_user_id, **(assessment or {})
    )
    return {
        "ward": ward,
        "menu": menu,
        "patient": patient,
        "consult": consult,
    }


def setup_signed_consult(
    *, signer_user_id: str = DIETITIAN_1, **kwargs
) -> dict:
    """ASSESSED consult carried through to SIGNED by a second identifier."""
    scenario = setup_assessed_consult(**kwargs)
    scenario["consult"] = sign_consult(scenario["consult"]["id"], signer_user_id)
    return scenario


def new_supplement_order(
    consult_id: str,
    menu_item_id: str,
    doses_per_day: int = 2,
    expected_consult_version: Optional[int] = None,
    dietitian_user_id: str = DIETITIAN_1,
) -> dict:
    if expected_consult_version is None:
        expected_consult_version = read_consult(consult_id)["version"]
    return get_success_data(
        api.create_supplement_order(
            create_supplement_order_payload(
                consult_id, menu_item_id, expected_consult_version, doses_per_day
            ),
            make_dietitian_headers(dietitian_user_id),
        )
    )


def activate_supplement_order(order_id: str, dietitian_user_id: str = DIETITIAN_1) -> dict:
    return get_success_data(
        api.activate_supplement_order(order_id, make_dietitian_headers(dietitian_user_id))
    )


def new_survey(meal_order_id: str, headers: Optional[dict] = None, **scores) -> dict:
    return get_success_data(
        api.create_survey(create_survey_payload(meal_order_id, **scores), headers or AIDE)
    )
