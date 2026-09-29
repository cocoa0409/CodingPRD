"""
Depth-four causal chains: a second failed verification that reaches a store's
penalty exposure, and a retrofit completion that walks the same chain backwards.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_instant,
    assert_instant_is_none,
    assert_penalty_exposure,
    assert_store_posture,
    assert_system_axes,
)
from test_helpers.test_users import (
    COMPLIANCE_MANAGER_HEADERS,
    make_technician_headers,
)
from test_helpers.types import (
    ATTEMPT_FAILED_VERIFICATION,
    CERT_TYPE_II,
    EVENT_RETROFIT_MANDATED,
    EVENT_VERIFIED_CLOSED,
    PLAN_COMPLETED,
    POSTURE_AT_RISK,
    POSTURE_COMPLIANT,
    POSTURE_NON_COMPLIANT,
    RESULT_FAIL,
    SEQUENCE_INITIAL,
    SERVICE_RETROFIT_CONVERSION,
    STATE_COMPLIANT,
    STATE_RETROFIT_MANDATED,
)


def _one_failure_with_live_inspection(api):
    """
    A 20.0 lb top-up opens a leak event and takes the store to AT_RISK; a
    regulator then opens an inspection carrying two one-day MINOR citations
    while that posture holds, so it is priced at the 1.25 multiplier. The clock
    then moves to 2026-08-08 and one repair attempt fails its verification
    before a second attempt is filed, leaving the event in VERIFICATION_PENDING
    with one failure already counted.
    """
    env = X.leak_event_env(api)
    env["inspection"] = X.open_inspection(api, env["store_id"])
    env["inspection_id"] = env["inspection"]["id"]

    X.set_clock(api, "2026-08-08T00:00:00Z")
    attempt1 = X.file_repair_attempt(
        api,
        env["event_id"],
        env["system_id"],
        env["tech1_id"],
        env["eq1_id"],
        "2026-08-05T09:00:00Z",
        repair_method_code="BRAZE_JOINT",
    )
    X.file_verification_test(
        api,
        env["event_id"],
        attempt1["id"],
        env["tech2_id"],
        "2026-08-06T09:00:00Z",
        result=RESULT_FAIL,
        measured_leak_rate_pct=18.5,
    )
    attempt2 = X.file_repair_attempt(
        api,
        env["event_id"],
        env["system_id"],
        env["tech1_id"],
        env["eq1_id"],
        "2026-08-07T09:00:00Z",
        repair_method_code="REPLACE_VALVE",
    )
    env["attempt1_id"] = attempt1["id"]
    env["attempt2_id"] = attempt2["id"]
    return env


def test_second_failure_prices_the_inspection_at_the_at_risk_multiplier_first(api):
    """
    The inspection opened while the store is only AT_RISK is priced at 1.25,
    which is the state the escalation later has to move away from.

    Design: Difficulty/transitive_cascade/second_failed_verification_cascades_event_system_store_and_penalty
    """
    env = _one_failure_with_live_inspection(api)

    inspection = X.get_inspection(api, env["inspection_id"])
    assert_penalty_exposure(
        inspection, penalty_exposure_usd=688.88, chronic_multiplier_applied=1.25
    )
    assert_store_posture(
        X.get_store(api, env["store_id"]),
        compliance_status=POSTURE_AT_RISK,
        penalty_exposure_total_usd=688.88,
    )


def test_second_failure_cascades_event_system_store_and_penalty_exposure(api):
    """
    The second FAIL touches only the test row and the leak event, yet the event
    reaching RETROFIT_MANDATED drags the system, the system drags the store, and
    the store's new posture re-prices the live inspection at 1.50.

    Design: Difficulty/transitive_cascade/second_failed_verification_cascades_event_system_store_and_penalty
    """
    env = _one_failure_with_live_inspection(api)

    test2 = validate_success(
        api.create_verification_test(
            F.verification_test_payload(
                env["event_id"],
                env["attempt2_id"],
                env["tech2_id"],
                "2026-08-07T13:00:00Z",
                test_method_code="ELECTRONIC_DETECTOR",
                result=RESULT_FAIL,
                measured_leak_rate_pct=17.9,
            ),
            make_technician_headers(env["tech2_id"]),
        ),
        expected_status=201,
    )
    assert test2["test_sequence"] == SEQUENCE_INITIAL
    assert test2["result"] == RESULT_FAIL

    event = X.get_leak_event(api, env["event_id"])
    assert event["status"] == EVENT_RETROFIT_MANDATED
    assert event["failed_verification_count"] == 2

    system = X.get_system(api, env["system_id"])
    assert_system_axes(system, compliance_state=STATE_RETROFIT_MANDATED)
    assert_instant(system["retrofit_due_on"], "2026-11-06T00:00:00Z", "retrofit_due_on")

    store = X.get_store(api, env["store_id"])
    assert_store_posture(
        store,
        compliance_status=POSTURE_NON_COMPLIANT,
        mandated_retrofit_count=1,
        chronic_leaker_flag=True,
        open_leak_event_count=1,
        overdue_leak_event_count=0,
        penalty_exposure_total_usd=826.66,
    )

    assert_penalty_exposure(
        X.get_inspection(api, env["inspection_id"]),
        penalty_exposure_usd=826.66,
        chronic_multiplier_applied=1.50,
    )

    assert (
        X.get_repair_attempt(api, env["attempt2_id"])["outcome"]
        == ATTEMPT_FAILED_VERIFICATION
    )


def _mandated_system_ready_to_convert(api):
    """
    The mandated system of the escalating cascade, plus an APPROVED R-448A
    retrofit plan, the RETROFIT_CONVERSION record that documents the work (which
    bubbles the plan to IN_PROGRESS), and a fresh inspection opened while the
    store is NON_COMPLIANT so it is priced at the 1.50 multiplier.
    """
    env = X.retrofit_mandated_env(api, with_r448a=True)

    env["version_before_conversion"] = None
    plan = X.file_retrofit_plan(
        api, env["system_id"], target_refrigerant_type_id=env["rt448_id"]
    )
    env["plan_id"] = plan["id"]
    env["plan_at_creation"] = plan
    X.submit_plan(api, env["plan_id"])
    X.approve_plan(api, env["plan_id"])

    env["version_before_conversion"] = X.system_version(api, env["system_id"])
    conversion = X.file_service_record(
        api,
        env["system_id"],
        env["tech1_id"],
        env["eq1_id"],
        env["version_before_conversion"],
        service_type=SERVICE_RETROFIT_CONVERSION,
        performed_at="2026-08-07T20:00:00Z",
        duration_minutes=240,
        refrigerant_added_lbs=F.OMIT,
    )
    env["conversion_id"] = conversion["id"]

    env["inspection"] = X.open_inspection(api, env["store_id"])
    env["inspection_id"] = env["inspection"]["id"]
    return env


def test_retrofit_completion_starts_from_a_mandated_and_fully_priced_store(api):
    """
    The plan is mandated because the system it names is already under a retrofit
    mandate, and the inspection opened against the NON_COMPLIANT store is priced
    at 826.66 before any de-escalation happens.

    Design: Difficulty/transitive_cascade/retrofit_completion_cascades_deescalation_down_to_penalty_reprice
    """
    env = _mandated_system_ready_to_convert(api)

    assert env["plan_at_creation"]["mandated"] is True
    assert_penalty_exposure(
        X.get_inspection(api, env["inspection_id"]),
        penalty_exposure_usd=826.66,
        chronic_multiplier_applied=1.50,
    )


def test_retrofit_completion_cascades_de_escalation_down_to_the_penalty_reprice(api):
    """
    Completing the plan re-points the chemistry and clears the mandate, which is
    the only reason the mandated event may close, which is the only reason the
    store drops to COMPLIANT, which is the only reason the live inspection is
    re-priced downward at the 1.00 multiplier.

    Design: Difficulty/transitive_cascade/retrofit_completion_cascades_deescalation_down_to_penalty_reprice
    """
    env = _mandated_system_ready_to_convert(api)

    completed = validate_success(
        api.complete_retrofit_plan(
            env["plan_id"],
            F.plan_completion_payload(env["conversion_id"]),
            COMPLIANCE_MANAGER_HEADERS,
        )
    )
    assert completed["status"] == PLAN_COMPLETED
    assert_instant(completed["completed_at"], "2026-08-08T00:00:00Z", "completed_at")

    system = X.get_system(api, env["system_id"])
    assert system["refrigerant_type_id"] == env["rt448_id"]
    assert_system_axes(system, compliance_state=STATE_COMPLIANT)
    assert_instant_is_none(system["retrofit_due_on"], "retrofit_due_on")
    assert_instant(
        system["leak_rate_baseline_at"], "2026-08-08T00:00:00Z", "leak_rate_baseline_at"
    )
    assert system["required_certification_type"] == CERT_TYPE_II
    assert system["exceedance_count_12mo"] == 1
    assert system["version"] == env["version_before_conversion"] + 2

    event = X.get_leak_event(api, env["event_id"])
    assert event["status"] == EVENT_VERIFIED_CLOSED
    assert_instant(event["closed_at"], "2026-08-08T00:00:00Z", "closed_at")

    store = X.get_store(api, env["store_id"])
    assert_store_posture(
        store,
        compliance_status=POSTURE_COMPLIANT,
        mandated_retrofit_count=0,
        chronic_leaker_flag=False,
        open_leak_event_count=0,
        penalty_exposure_total_usd=551.10,
    )

    assert_penalty_exposure(
        X.get_inspection(api, env["inspection_id"]),
        penalty_exposure_usd=551.10,
        chronic_multiplier_applied=1.00,
    )
