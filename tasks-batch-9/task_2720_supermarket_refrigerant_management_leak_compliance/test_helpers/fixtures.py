"""
Composite state builders.

Every builder drives the API through the endpoints of §4 only; there is no back
door into the store. Builders use `get_success_data()` so that a broken setup
step fails with the server's own error identifier rather than a downstream
KeyError.

The harness restarts the server before each test, so every builder starts from
an empty database and returns a plain dict of the identifiers, entity snapshots
and version tokens the test needs.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as F
from .test_users import (
    COMPLIANCE_MANAGER_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    REGULATOR_HEADERS,
    make_technician_headers,
)
from .types import (
    DETECTION_MANUAL_INSPECTION,
    PLAN_DECISION_APPROVE,
    PLAN_DECISION_REJECT,
    PLAN_RETIRE,
    REPORT_DECISION_ACCEPT,
    REPORT_DECISION_REJECT,
    RESULT_FAIL,
    RESULT_PASS,
    SERVICE_ADD_REFRIGERANT,
)

# ─── Tier 0: single-call primitives ───────────────────────────────────


def set_clock(api, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock (§2.4) and return `current_utc` / `previous_utc`."""
    return get_success_data(
        api.set_clock(F.clock_payload(current_utc), PLATFORM_ADMIN_HEADERS)
    )


def create_store(api, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_store(F.store_payload(**overrides), COMPLIANCE_MANAGER_HEADERS)
    )


def create_second_store(api, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_store(F.second_store_payload(**overrides), COMPLIANCE_MANAGER_HEADERS)
    )


def create_r404a(api, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_refrigerant_type(F.r404a_payload(**overrides), COMPLIANCE_MANAGER_HEADERS)
    )


def create_r448a(api, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_refrigerant_type(F.r448a_payload(**overrides), COMPLIANCE_MANAGER_HEADERS)
    )


def create_r245fa(api, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_refrigerant_type(F.r245fa_payload(**overrides), COMPLIANCE_MANAGER_HEADERS)
    )


def create_r290(api, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_refrigerant_type(F.r290_payload(**overrides), COMPLIANCE_MANAGER_HEADERS)
    )


def create_system(api, store_id: str, refrigerant_type_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_system(
            F.system_payload(store_id, refrigerant_type_id, **overrides),
            COMPLIANCE_MANAGER_HEADERS,
        )
    )


def create_empty_system(api, store_id: str, refrigerant_type_id: str, **overrides) -> Dict[str, Any]:
    """A 60.0 lb regulated system commissioned with no charge in it."""
    return get_success_data(
        api.create_system(
            F.empty_system_payload(store_id, refrigerant_type_id, **overrides),
            COMPLIANCE_MANAGER_HEADERS,
        )
    )


def create_technician(api, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_technician(F.technician_payload(**overrides), COMPLIANCE_MANAGER_HEADERS)
    )


def create_second_technician(api, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_technician(
            F.second_technician_payload(**overrides), COMPLIANCE_MANAGER_HEADERS
        )
    )


def create_equipment(api, store_id: str, technician_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_recovery_equipment(
            F.recovery_equipment_payload(store_id, technician_id, **overrides),
            COMPLIANCE_MANAGER_HEADERS,
        )
    )


def create_cylinder(api, store_id: str, refrigerant_type_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_cylinder(
            F.cylinder_payload(store_id, refrigerant_type_id, **overrides),
            COMPLIANCE_MANAGER_HEADERS,
        )
    )


def system_version(api, system_id: str) -> int:
    """Read the system's current `version`, as §2.8 requires before a write."""
    return get_success_data(api.get_system(system_id, COMPLIANCE_MANAGER_HEADERS))["version"]


def get_system(api, system_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_system(system_id, COMPLIANCE_MANAGER_HEADERS))


def get_store(api, store_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_store(store_id, COMPLIANCE_MANAGER_HEADERS))


def get_cylinder(api, cylinder_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_cylinder(cylinder_id, COMPLIANCE_MANAGER_HEADERS))


def get_leak_event(api, leak_event_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_leak_event(leak_event_id, COMPLIANCE_MANAGER_HEADERS))


def get_plan(api, plan_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_retrofit_plan(plan_id, COMPLIANCE_MANAGER_HEADERS))


def get_inspection(api, inspection_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_inspection(inspection_id, COMPLIANCE_MANAGER_HEADERS))


def get_extension_request(api, extension_request_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_extension_request(extension_request_id, COMPLIANCE_MANAGER_HEADERS)
    )


def get_repair_attempt(api, repair_attempt_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_repair_attempt(repair_attempt_id, COMPLIANCE_MANAGER_HEADERS)
    )


def get_service_record(api, service_record_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_service_record(service_record_id, COMPLIANCE_MANAGER_HEADERS)
    )


def get_report(api, report_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_regulatory_report(report_id, COMPLIANCE_MANAGER_HEADERS)
    )


def get_equipment(api, equipment_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_recovery_equipment(equipment_id, COMPLIANCE_MANAGER_HEADERS)
    )


def get_technician(api, technician_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_technician(technician_id, COMPLIANCE_MANAGER_HEADERS)
    )


def get_verification_test(api, verification_test_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_verification_test(verification_test_id, COMPLIANCE_MANAGER_HEADERS)
    )


def list_leak_events(api, **params) -> Dict[str, Any]:
    """Return the full paginated body so both `data` and `meta` are available."""
    response = api.list_leak_events(COMPLIANCE_MANAGER_HEADERS, params or None)
    return response.json()


def leak_events_of(api, system_id: str) -> List[Dict[str, Any]]:
    return list_leak_events(api, system_id=system_id)["data"]


def run_sweep(api, **params) -> Dict[str, Any]:
    return get_success_data(
        api.run_compliance_sweep(F.compliance_run_payload(**params), PLATFORM_ADMIN_HEADERS)
    )


# ─── Tier 0: writes that need an identity or a version token ──────────


def file_service_record(
    api,
    system_id: str,
    technician_id: str,
    recovery_equipment_id: str,
    expected_system_version: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    """
    File a service record as the named technician. When no version token is
    supplied the system's current `version` is read first, which is what a
    client that has just refreshed its view would send.
    """
    version = (
        system_version(api, system_id)
        if expected_system_version is None
        else expected_system_version
    )
    payload = F.service_record_payload(
        system_id, technician_id, recovery_equipment_id, version, **overrides
    )
    return get_success_data(
        api.create_service_record(payload, make_technician_headers(technician_id))
    )


def declare_leak_event(api, system_id: str, **overrides) -> Dict[str, Any]:
    """Declare an event outside the leak-rate calculation (§3.4)."""
    return get_success_data(
        api.create_leak_event(
            F.leak_event_payload(system_id, **overrides), COMPLIANCE_MANAGER_HEADERS
        )
    )


def file_repair_attempt(
    api,
    leak_event_id: str,
    system_id: str,
    technician_id: str,
    recovery_equipment_id: str,
    repair_completed_at: str,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_repair_attempt(
            F.repair_attempt_payload(
                leak_event_id,
                system_id,
                technician_id,
                recovery_equipment_id,
                repair_completed_at,
                **overrides,
            ),
            make_technician_headers(technician_id),
        )
    )


def file_verification_test(
    api,
    leak_event_id: str,
    repair_attempt_id: str,
    technician_id: str,
    performed_at: str,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_verification_test(
            F.verification_test_payload(
                leak_event_id, repair_attempt_id, technician_id, performed_at, **overrides
            ),
            make_technician_headers(technician_id),
        )
    )


def open_inspection(api, store_id: str, citations=None, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_inspection(
            F.inspection_payload(store_id, citations, **overrides), REGULATOR_HEADERS
        )
    )


def file_extension_request(api, leak_event_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_extension_request(
            F.extension_request_payload(leak_event_id, **overrides),
            COMPLIANCE_MANAGER_HEADERS,
        )
    )


def approve_extension_request(
    api, extension_request_id: str, granted_days: int
) -> Dict[str, Any]:
    return get_success_data(
        api.decide_extension_request(
            extension_request_id,
            F.extension_decision_payload("APPROVE", granted_days=granted_days),
            REGULATOR_HEADERS,
        )
    )


def file_retrofit_plan(
    api, system_id: str, expected_system_version: Optional[int] = None, **overrides
) -> Dict[str, Any]:
    version = (
        system_version(api, system_id)
        if expected_system_version is None
        else expected_system_version
    )
    return get_success_data(
        api.create_retrofit_plan(
            F.retrofit_plan_payload(system_id, version, **overrides),
            COMPLIANCE_MANAGER_HEADERS,
        )
    )


def submit_plan(api, plan_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.submit_retrofit_plan(
            plan_id, F.plan_submission_payload(**overrides), COMPLIANCE_MANAGER_HEADERS
        )
    )


def approve_plan(api, plan_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.decide_retrofit_plan(
            plan_id, F.plan_decision_payload(PLAN_DECISION_APPROVE), REGULATOR_HEADERS
        )
    )


def reject_plan(api, plan_id: str, rejection_reason_code: str) -> Dict[str, Any]:
    """A rejected plan may be revised and resubmitted (§3.7)."""
    return get_success_data(
        api.decide_retrofit_plan(
            plan_id,
            F.plan_decision_payload(
                PLAN_DECISION_REJECT, rejection_reason_code=rejection_reason_code
            ),
            REGULATOR_HEADERS,
        )
    )


def submit_report(api, regulatory_report_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.submit_regulatory_report(
            regulatory_report_id,
            F.report_submission_payload(**overrides),
            COMPLIANCE_MANAGER_HEADERS,
        )
    )


def accept_report(api, regulatory_report_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.decide_regulatory_report(
            regulatory_report_id,
            F.report_decision_payload(REPORT_DECISION_ACCEPT),
            REGULATOR_HEADERS,
        )
    )


def reject_report(
    api, regulatory_report_id: str, rejection_reason_code: str
) -> Dict[str, Any]:
    """A rejected filing releases its period, so another may be filed over it."""
    return get_success_data(
        api.decide_regulatory_report(
            regulatory_report_id,
            F.report_decision_payload(
                REPORT_DECISION_REJECT, rejection_reason_code=rejection_reason_code
            ),
            REGULATOR_HEADERS,
        )
    )


def retire_system(api, system_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.retire_system(
            system_id, F.retirement_payload(**overrides), COMPLIANCE_MANAGER_HEADERS
        )
    )


def suspend_technician(api, technician_id: str, reason_code: str = "CERT_UNDER_REVIEW"):
    return get_success_data(
        api.change_technician_status(
            technician_id,
            F.technician_status_change_payload("SUSPENDED", reason_code),
            COMPLIANCE_MANAGER_HEADERS,
        )
    )


def reinstate_technician(api, technician_id: str, reason_code: str = "CERT_REVIEW_CLEARED"):
    return get_success_data(
        api.change_technician_status(
            technician_id,
            F.technician_status_change_payload("ACTIVE", reason_code),
            COMPLIANCE_MANAGER_HEADERS,
        )
    )


# ─── Tier 1: the commissioned store ──────────────────────────────────


def base_env(
    api,
    clock: str = "2026-08-01T00:00:00Z",
    with_r448a: bool = False,
    with_r245fa: bool = False,
    with_second_technician: bool = True,
    with_cylinder: bool = True,
    with_second_equipment: bool = False,
    system_overrides: Optional[Dict[str, Any]] = None,
    equipment_overrides: Optional[Dict[str, Any]] = None,
    cylinder_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    A commissioned store: Northgate Market with R-404A, one 100.0 lb commercial
    rack holding 80.0 lbs, a TYPE_II technician who does the repairs, a UNIVERSAL
    technician who does the verifications, one HIGH-pressure recovery machine
    verified 2026-06-01, and one 50.0 lb cylinder holding 40.0 lbs.

    The store's opening refrigerant mass is therefore 80.0 in the system plus
    40.0 in the cylinder, 120.0 lbs in total.
    """
    set_clock(api, clock)
    store = create_store(api)
    rt404 = create_r404a(api)
    env: Dict[str, Any] = {
        "clock": clock,
        "store": store,
        "store_id": store["id"],
        "rt404": rt404,
        "rt404_id": rt404["id"],
    }
    if with_r448a:
        rt448 = create_r448a(api)
        env["rt448"] = rt448
        env["rt448_id"] = rt448["id"]
    if with_r245fa:
        rt245 = create_r245fa(api)
        env["rt245"] = rt245
        env["rt245_id"] = rt245["id"]

    system = create_system(api, store["id"], rt404["id"], **(system_overrides or {}))
    env["system"] = system
    env["system_id"] = system["id"]

    tech1 = create_technician(api)
    env["tech1"] = tech1
    env["tech1_id"] = tech1["id"]
    if with_second_technician:
        tech2 = create_second_technician(api)
        env["tech2"] = tech2
        env["tech2_id"] = tech2["id"]

    eq1 = create_equipment(api, store["id"], tech1["id"], **(equipment_overrides or {}))
    env["eq1"] = eq1
    env["eq1_id"] = eq1["id"]
    if with_second_equipment:
        eq2 = create_equipment(api, store["id"], tech1["id"], equipment_serial="RM-9002")
        env["eq2"] = eq2
        env["eq2_id"] = eq2["id"]

    if with_cylinder:
        cyl1 = create_cylinder(api, store["id"], rt404["id"], **(cylinder_overrides or {}))
        env["cyl1"] = cyl1
        env["cyl1_id"] = cyl1["id"]
    return env


def empty_system_env(api, clock: str = "2026-08-01T00:00:00Z", **kwargs) -> Dict[str, Any]:
    """
    The same store with a 60.0 lb regulated system commissioned empty, installed
    2025-03-01. Its charge is already 0.0, which is what the retirement action
    and the manual-declaration scenarios need.
    """
    return base_env(
        api,
        clock=clock,
        system_overrides={
            "full_charge_lbs": 60.0,
            "initial_charge_lbs": 0.0,
            "installed_on": "2025-03-01T00:00:00Z",
        },
        **kwargs,
    )


# ─── Tier 2: an open leak event ──────────────────────────────────────


def leak_event_env(api, added_lbs: float = 20.0, **kwargs) -> Dict[str, Any]:
    """
    `base_env` plus a 20.0 lb top-up at the clock, which takes the rolling leak
    rate to exactly the 20.0 percent threshold and auto-opens a leak event.
    Returns the env with `record`, `event` and `event_id` added.

    The mass movement is non-zero, so the cylinder it is drawn from is named.
    """
    env = base_env(api, **kwargs)
    record = file_service_record(
        api,
        env["system_id"],
        env["tech1_id"],
        env["eq1_id"],
        service_type=SERVICE_ADD_REFRIGERANT,
        cylinder_id=env["cyl1_id"],
        refrigerant_added_lbs=added_lbs,
        performed_at=env["clock"],
        duration_minutes=120,
    )
    events = leak_events_of(api, env["system_id"])
    env["record"] = record
    env["record_id"] = record["id"]
    env["events"] = events
    if events:
        env["event"] = events[0]
        env["event_id"] = events[0]["id"]
    return env


def manual_event_env(api, clock: str = "2026-08-01T00:00:00Z", **kwargs) -> Dict[str, Any]:
    """
    An empty 60.0 lb system carrying one manually declared MANUAL_INSPECTION
    event detected at the clock, so its repair deadline is 30 days out and its
    whole 30-day extension budget is untouched.
    """
    env = empty_system_env(api, clock=clock, **kwargs)
    event = declare_leak_event(
        api, env["system_id"], detected_at=clock, detection_method=DETECTION_MANUAL_INSPECTION
    )
    env["event"] = event
    env["event_id"] = event["id"]
    return env


# ─── Tier 3: full-lifecycle shortcuts on a leak event ────────────────


def repaired_event_env(
    api,
    advance_clock_to: str = "2026-08-08T00:00:00Z",
    first_repair_at: str = "2026-08-05T09:00:00Z",
    **kwargs,
) -> Dict[str, Any]:
    """
    `leak_event_env` with the clock moved on a week and one repair attempt
    filed, so the event sits in VERIFICATION_PENDING awaiting its first test.
    """
    env = leak_event_env(api, **kwargs)
    set_clock(api, advance_clock_to)
    env["clock"] = advance_clock_to
    attempt1 = file_repair_attempt(
        api,
        env["event_id"],
        env["system_id"],
        env["tech1_id"],
        env["eq1_id"],
        first_repair_at,
        repair_method_code="BRAZE_JOINT",
    )
    env["attempt1"] = attempt1
    env["attempt1_id"] = attempt1["id"]
    return env


def verification_pending_after_one_failure_env(api, **kwargs) -> Dict[str, Any]:
    """
    The cyclic path of §3.5: attempt A1 fails its test, a second attempt A2 is
    filed, and the event re-enters VERIFICATION_PENDING with
    `failed_verification_count` at 1 and `repair_attempt_count` at 2.
    """
    env = repaired_event_env(api, **kwargs)
    test1 = file_verification_test(
        api,
        env["event_id"],
        env["attempt1_id"],
        env["tech2_id"],
        "2026-08-06T09:00:00Z",
        test_method_code="PRESSURE_DECAY",
        result=RESULT_FAIL,
        measured_leak_rate_pct=18.5,
    )
    attempt2 = file_repair_attempt(
        api,
        env["event_id"],
        env["system_id"],
        env["tech1_id"],
        env["eq1_id"],
        "2026-08-07T09:00:00Z",
        repair_method_code="REPLACE_VALVE",
    )
    env["test1"] = test1
    env["test1_id"] = test1["id"]
    env["attempt2"] = attempt2
    env["attempt2_id"] = attempt2["id"]
    return env


def retrofit_mandated_env(api, **kwargs) -> Dict[str, Any]:
    """
    The accumulation threshold of §3.5 reached: a second failed verification
    takes `failed_verification_count` to 2, which mandates a retrofit and drags
    the system and the store with it.
    """
    env = verification_pending_after_one_failure_env(api, **kwargs)
    test2 = file_verification_test(
        api,
        env["event_id"],
        env["attempt2_id"],
        env["tech2_id"],
        "2026-08-07T13:00:00Z",
        test_method_code="ELECTRONIC_DETECTOR",
        result=RESULT_FAIL,
        measured_leak_rate_pct=17.9,
    )
    env["test2"] = test2
    env["test2_id"] = test2["id"]
    return env


def followup_pending_env(api, **kwargs) -> Dict[str, Any]:
    """
    The two-stage verification of §3.5 half-done: the initial test passes, so the
    event moves to FOLLOWUP_PENDING with its deadline re-based on that test.
    """
    env = repaired_event_env(api, **kwargs)
    test1 = file_verification_test(
        api,
        env["event_id"],
        env["attempt1_id"],
        env["tech2_id"],
        "2026-08-06T09:00:00Z",
        test_method_code="PRESSURE_DECAY",
        result=RESULT_PASS,
        measured_leak_rate_pct=2.0,
    )
    env["test1"] = test1
    env["test1_id"] = test1["id"]
    return env


def verified_closed_env(api, followup_at: str = "2026-08-08T09:00:00Z", **kwargs) -> Dict[str, Any]:
    """
    A fully closed event: initial PASS then follow-up PASS, which is the only
    path to VERIFIED_CLOSED.
    """
    env = followup_pending_env(api, **kwargs)
    test2 = file_verification_test(
        api,
        env["event_id"],
        env["attempt1_id"],
        env["tech2_id"],
        followup_at,
        test_method_code="PRESSURE_DECAY",
        result=RESULT_PASS,
        measured_leak_rate_pct=1.5,
    )
    env["test2"] = test2
    env["test2_id"] = test2["id"]
    return env


# ─── Tier 4: retrofit plans and retirement ───────────────────────────


def draft_plan_env(api, **kwargs) -> Dict[str, Any]:
    """`base_env` with R-448A defined and one DRAFT RETROFIT plan to it."""
    env = base_env(api, with_r448a=True, **kwargs)
    plan = file_retrofit_plan(
        api, env["system_id"], target_refrigerant_type_id=env["rt448_id"]
    )
    env["plan"] = plan
    env["plan_id"] = plan["id"]
    return env


def approved_plan_env(api, **kwargs) -> Dict[str, Any]:
    """The same plan carried through submission and regulatory approval."""
    env = draft_plan_env(api, **kwargs)
    submit_plan(api, env["plan_id"])
    env["plan"] = approve_plan(api, env["plan_id"])
    return env


def retire_plan_env(api, clock: str = "2026-08-01T00:00:00Z", **kwargs) -> Dict[str, Any]:
    """
    An empty system carrying a manually declared event and a RETIRE plan, which
    is the escape hatch a blocked retirement needs. The plan is left SUBMITTED.
    """
    env = manual_event_env(api, clock=clock, **kwargs)
    plan = file_retrofit_plan(
        api,
        env["system_id"],
        plan_type=PLAN_RETIRE,
        due_on="2026-10-30T00:00:00Z",
        estimated_cost_usd=42000.00,
        target_refrigerant_type_id=F.OMIT,
    )
    submit_plan(api, plan["id"], submission_note=F.OMIT)
    env["plan"] = get_plan(api, plan["id"])
    env["plan_id"] = plan["id"]
    return env


def approved_extension_env(api, granted_days: int = 20, **kwargs) -> Dict[str, Any]:
    """
    A manually declared event with one approved 20-day extension, so its repair
    deadline has moved from 2026-08-31 to 2026-09-20 and 10 days remain.
    """
    env = manual_event_env(api, **kwargs)
    request = file_extension_request(api, env["event_id"])
    env["er1"] = approve_extension_request(api, request["id"], granted_days)
    env["er1_id"] = request["id"]
    env["er1_before"] = request["deadline_before"]
    return env
