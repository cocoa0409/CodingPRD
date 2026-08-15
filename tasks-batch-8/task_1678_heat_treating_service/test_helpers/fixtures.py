"""Composite setup helpers for multi-step test prerequisites.

Every fixture builds its preconditions from scratch via PRD-declared
endpoints (the harness restarts the server before every test, so each test
starts against an empty database). Segregation-of-duties identities are
threaded deliberately: inspections are recorded by qe-1 and dispositions are
decided by qe-2 (PRD §3.7). All helpers use get_success_data() so a setup
failure surfaces as a clear "Setup failed" error rather than a confusing
assertion failure deep in a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_assignment_payload,
    create_audit_package_payload,
    create_customer_payload,
    create_furnace_payload,
    create_inspection_payload,
    create_load_batch_payload,
    create_pyrometry_payload,
    create_recipe_payload,
    create_thermocouple_payload,
    create_work_order_payload,
)
from .test_users import TEST_USERS

CSR = TEST_USERS["customer_service_rep"]
SCHED = TEST_USERS["shop_scheduler"]
OPERATOR = TEST_USERS["furnace_operator"]
CALTECH = TEST_USERS["calibration_tech"]
QE = TEST_USERS["quality_engineer"]  # qe-1 — inspection recorder
QE2 = TEST_USERS["quality_engineer_2"]  # qe-2 — disposition decider
AUDITOR = TEST_USERS["nadcap_auditor"]

PASS_READINGS = [40, 42, 41]  # avg 41.0, inside the default [38, 44] band
FAIL_READINGS = [50, 50]  # avg 50.0, above the default hardness_max_hrc 44


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str, headers=None):
    """Advance the server logical clock."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, headers or CSR)
    )


# ---------------------------------------------------------------------------
# Tier 1: customers, recipes, furnaces
# ---------------------------------------------------------------------------

def create_customer(**overrides) -> dict:
    """Create a customer account. Returns the CustomerAccount."""
    return get_success_data(
        api_client.create_customer_account(create_customer_payload(**overrides), CSR)
    )


def get_customer(customer_id: str) -> dict:
    return get_success_data(api_client.get_customer_account(customer_id, CSR))


def create_approved_recipe(creator=None, **overrides) -> dict:
    """Create a recipe and approve it (DRAFT -> APPROVED). Returns the recipe."""
    creator = creator or QE
    recipe = get_success_data(
        api_client.create_furnace_recipe(create_recipe_payload(**overrides), creator)
    )
    return get_success_data(api_client.approve_furnace_recipe(recipe["id"], creator))


def create_furnace(**overrides) -> dict:
    """Register a furnace (no pyrometry history -> UNQUALIFIED)."""
    return get_success_data(
        api_client.create_furnace(create_furnace_payload(**overrides), SCHED)
    )


def get_furnace(furnace_id: str) -> dict:
    return get_success_data(api_client.get_furnace(furnace_id, SCHED))


def record_pyrometry(furnace_id, record_type="TUS",
                     performed_at="2026-08-01T00:00:00Z", result="PASS",
                     **overrides) -> dict:
    """Record a TUS or instrument calibration."""
    return get_success_data(
        api_client.create_pyrometry_record(
            create_pyrometry_payload(
                furnace_id, record_type=record_type, performed_at=performed_at,
                result=result, **overrides
            ),
            CALTECH,
        )
    )


def qualify_furnace(furnace_id, performed_at="2026-08-01T00:00:00Z") -> tuple:
    """Record a PASS TUS and a PASS instrument calibration at `performed_at`,
    bringing the furnace to QUALIFIED. Returns (tus_record, cal_record)."""
    tus = record_pyrometry(furnace_id, "TUS", performed_at=performed_at, result="PASS")
    cal = record_pyrometry(
        furnace_id, "INSTRUMENT_CALIBRATION", performed_at=performed_at, result="PASS"
    )
    return tus, cal


# ---------------------------------------------------------------------------
# Tier 2: work orders, loads, assignments
# ---------------------------------------------------------------------------

def create_work_order(customer_id, recipe_id, **overrides) -> dict:
    """Receive a work order (RECEIVED / PENDING_TEST)."""
    return get_success_data(
        api_client.create_work_order(
            create_work_order_payload(customer_id, recipe_id, **overrides), CSR
        )
    )


def get_work_order(work_order_id: str) -> dict:
    return get_success_data(api_client.get_work_order(work_order_id, CSR))


def create_load(furnace_id, recipe_id, **overrides) -> dict:
    """Create a BUILDING load batch."""
    return get_success_data(
        api_client.create_load_batch(
            create_load_batch_payload(furnace_id, recipe_id, **overrides), SCHED
        )
    )


def get_load(load_batch_id: str) -> dict:
    return get_success_data(api_client.get_load_batch(load_batch_id, SCHED))


def assign_order(load_batch_id, work_order_id, expected_version=None) -> dict:
    """Assign a work order to a load, reading the load's current version when
    expected_version is not supplied (OCC field, PRD §2.9)."""
    if expected_version is None:
        expected_version = get_load(load_batch_id)["version"]
    return get_success_data(
        api_client.create_load_assignment(
            load_batch_id,
            create_assignment_payload(work_order_id, expected_version),
            SCHED,
        )
    )


def unassign_order(load_batch_id, assignment_id, expected_version=None) -> dict:
    """Remove an assignment, reading the load's current version when needed."""
    if expected_version is None:
        expected_version = get_load(load_batch_id)["version"]
    return get_success_data(
        api_client.unassign_load_assignment(
            load_batch_id,
            assignment_id,
            {"expected_load_batch_version": expected_version},
            SCHED,
        )
    )


def get_assignment(assignment_id: str) -> dict:
    return get_success_data(api_client.get_load_assignment(assignment_id, SCHED))


# ---------------------------------------------------------------------------
# Tier 3: run lifecycle
# ---------------------------------------------------------------------------

def release_load(load_batch_id) -> dict:
    return get_success_data(api_client.release_load_batch(load_batch_id, SCHED))


def start_run(load_batch_id) -> dict:
    return get_success_data(api_client.start_run_load_batch(load_batch_id, OPERATOR))


def add_reading(load_batch_id, temp_f=1650, channel="LOAD_TC_1",
                recorded_at="2026-08-02T10:00:00Z") -> dict:
    """Append a thermocouple reading to a RUNNING load."""
    return get_success_data(
        api_client.create_thermocouple_reading(
            create_thermocouple_payload(
                load_batch_id, channel=channel, recorded_at=recorded_at, temp_f=temp_f
            ),
            OPERATOR,
        )
    )


def complete_run(load_batch_id) -> dict:
    return get_success_data(api_client.complete_run_load_batch(load_batch_id, OPERATOR))


def abort_run(load_batch_id) -> dict:
    return get_success_data(api_client.abort_load_batch(load_batch_id, OPERATOR))


def run_load_to_completed(load_batch_id, readings=None) -> dict:
    """Release -> start-run -> optional thermocouple readings -> complete-run.
    Returns the COMPLETED load."""
    release_load(load_batch_id)
    start_run(load_batch_id)
    for reading in (readings or []):
        add_reading(load_batch_id, **reading)
    return complete_run(load_batch_id)


# ---------------------------------------------------------------------------
# Tier 4: composite shop scenarios
# ---------------------------------------------------------------------------

def setup_shop(qualified=True, customer_overrides=None, recipe_overrides=None,
               furnace_overrides=None, pyrometry_performed_at="2026-08-01T00:00:00Z"):
    """Customer + APPROVED recipe + furnace (QUALIFIED when `qualified`).
    Returns {"customer", "recipe", "furnace"}."""
    customer = create_customer(**(customer_overrides or {}))
    recipe = create_approved_recipe(**(recipe_overrides or {}))
    furnace = create_furnace(**(furnace_overrides or {}))
    if qualified:
        qualify_furnace(furnace["id"], performed_at=pyrometry_performed_at)
    return {"customer": customer, "recipe": recipe, "furnace": furnace}


def process_order_to_processed(shop=None, order_overrides=None, load_overrides=None,
                               readings=None, **shop_kwargs) -> dict:
    """Full chain: shop -> RECEIVED order -> BUILDING load -> assign ->
    release -> start-run -> complete-run. The order ends PROCESSED with its
    energy surcharge settled. Returns {"shop", "order", "load", "assignment"}."""
    shop = shop or setup_shop(**shop_kwargs)
    order = create_work_order(
        shop["customer"]["id"], shop["recipe"]["id"], **(order_overrides or {})
    )
    load = create_load(shop["furnace"]["id"], shop["recipe"]["id"],
                       **(load_overrides or {}))
    assignment = assign_order(load["id"], order["id"])
    load = run_load_to_completed(load["id"], readings=readings)
    return {
        "shop": shop,
        "order": get_work_order(order["id"]),
        "load": load,
        "assignment": assignment,
    }


# ---------------------------------------------------------------------------
# Tier 5: inspection, disposition, liability
# ---------------------------------------------------------------------------

def record_inspection(work_order_id, readings=None, distortion=0.004,
                      recorder=None) -> dict:
    """Record an inspection test; default recorder is qe-1."""
    return get_success_data(
        api_client.create_inspection_test(
            create_inspection_payload(
                work_order_id,
                hardness_readings=readings if readings is not None else PASS_READINGS,
                measured_distortion_in=distortion,
            ),
            recorder or QE,
        )
    )


def list_disposition_cases(params=None, headers=None) -> list:
    return get_success_data(
        api_client.list_disposition_cases(headers or QE2, params=params)
    )


def get_disposition_case(case_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_disposition_case(case_id, headers or QE2))


def get_open_case_for_order(work_order_id) -> dict:
    """Return the single OPEN disposition case opened for a failed order."""
    cases = list_disposition_cases(
        params={"work_order_id": work_order_id, "status": "OPEN"}
    )
    assert isinstance(cases, list) and len(cases) == 1, (
        f"Setup failed: expected exactly one OPEN disposition case for order "
        f"{work_order_id}, got {cases}"
    )
    return cases[0]


def decide_case(case_id, decision, decider=None) -> dict:
    """Decide an OPEN case; default decider qe-2 differs from recorder qe-1."""
    return get_success_data(
        api_client.decide_disposition_case(
            case_id, {"decision": decision}, decider or QE2
        )
    )


def setup_failed_order(recipe_overrides=None, **process_kwargs) -> dict:
    """PROCESSED order failed at inspection: quality FAILED + one OPEN
    DispositionCase. Returns the process bundle plus "test" and "case"."""
    bundle = process_order_to_processed(
        recipe_overrides=recipe_overrides, **process_kwargs
    )
    test = record_inspection(bundle["order"]["id"], readings=FAIL_READINGS)
    case = get_open_case_for_order(bundle["order"]["id"])
    bundle["test"] = test
    bundle["case"] = case
    return bundle


def setup_scrapped_order(customer_overrides=None, recipe_overrides=None,
                         order_overrides=None, **process_kwargs) -> dict:
    """Failed order dispositioned SCRAP: order SCRAPPED, one PENDING
    LiabilityClaim. Returns the failed bundle plus "claim"."""
    bundle = setup_failed_order(
        customer_overrides=customer_overrides,
        recipe_overrides=recipe_overrides, order_overrides=order_overrides,
        **process_kwargs,
    )
    # A SCRAP decision requires a recorder/decider pair; fixtures default to
    # qe-1 recording and qe-2 deciding (PRD §3.7).
    decide_case(bundle["case"]["id"], "SCRAP")
    claims = get_success_data(
        api_client.list_liability_claims(
            CSR, params={"work_order_id": bundle["order"]["id"]}
        )
    )
    assert isinstance(claims, list) and len(claims) == 1, (
        f"Setup failed: expected exactly one liability claim for order "
        f"{bundle['order']['id']}, got {claims}"
    )
    bundle["claim"] = claims[0]
    bundle["order"] = get_work_order(bundle["order"]["id"])
    bundle["customer"] = get_customer(bundle["shop"]["customer"]["id"])
    return bundle


def retreat_order_once(bundle) -> dict:
    """Decide RE_TREAT on the bundle's OPEN case: order PROCESSED ->
    AWAITING_RETREAT, retreat_count 1, quality FAILED -> PENDING_TEST.
    Returns the refreshed order."""
    decide_case(bundle["case"]["id"], "RE_TREAT")
    return get_work_order(bundle["order"]["id"])


# ---------------------------------------------------------------------------
# Tier 6: audit packages
# ---------------------------------------------------------------------------

def create_audit_package(furnace_id, load_batch_ids, compiler=None) -> dict:
    """Compile a DRAFT audit package (QualityEngineer role)."""
    return get_success_data(
        api_client.create_audit_package(
            create_audit_package_payload(furnace_id, load_batch_ids),
            compiler or QE,
        )
    )


def get_audit_package(package_id: str) -> dict:
    return get_success_data(api_client.get_audit_package(package_id, AUDITOR))
