"""
State-machine corners: entry states, duplicate declarations, terminal lockdown,
non-idempotent retirement, cylinder and equipment cycles, undeclared transitions
and the observable field effects of each legal move.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_INVALID_STATE_TRANSITION,
    ERR_LEAK_EVENT_TERMINAL,
    ERR_OPEN_LEAK_EVENT_EXISTS,
    ERR_RECOVERY_EQUIPMENT_NOT_CERTIFIED,
    ERR_SYSTEM_RETIRED,
)
from test_helpers.assertions import (
    assert_extension_budget,
    assert_instant,
    assert_instant_is_none,
    assert_leak_event_schedule,
    assert_mass,
    assert_mass_conserved,
    assert_money,
    assert_penalty_exposure,
    assert_store_posture,
    assert_sweep_report,
    assert_system_axes,
    assert_system_charge,
)
from test_helpers.test_users import (
    COMPLIANCE_MANAGER_HEADERS,
    REGULATOR_HEADERS,
    make_store_manager_headers,
    make_technician_headers,
)
from test_helpers.types import (
    ATTEMPT_VERIFIED,
    DISPOSITION_RECLAIMED,
    DISPOSITION_RECOVERED,
    DISPOSITION_SENT_FOR_RECLAIM,
    DISPOSITION_VIRGIN,
    EQUIPMENT_CERTIFIED,
    EQUIPMENT_VERIFICATION_OVERDUE,
    EVENT_OPEN,
    EVENT_VERIFIED_CLOSED,
    INSPECTION_ESCALATED,
    INSPECTION_OPEN,
    INSPECTION_RESPONDED,
    PLAN_DRAFT,
    PLAN_SUPERSEDED,
    POSTURE_AT_RISK,
    POSTURE_COMPLIANT,
    REPORT_DECISION_ACCEPT,
    REPORT_DRAFT,
    RESULT_PASS,
    SEQUENCE_FOLLOWUP,
    SEQUENCE_INITIAL,
    SERVICE_RECOVER_REFRIGERANT,
    STATE_COMPLIANT,
    STATE_LEAK_OPEN,
    STATE_RETIRED_EXEMPT,
    SYSTEM_RETIRED,
    TECHNICIAN_ACTIVE,
    TECHNICIAN_SUSPENDED,
)


def test_manual_leak_event_enters_open_with_its_whole_schedule_stamped(api):
    """
    A manual declaration enters at the open state with both repair deadlines
    stamped from the detection instant, no verification deadline yet, and the whole
    extension budget untouched.

    Design: Corner/state_machines/manual_leak_event_starts_open_with_stamped_deadline_schedule
    """
    env = X.empty_system_env(api)

    event = validate_success(
        api.create_leak_event(
            F.leak_event_payload(env["system_id"]), COMPLIANCE_MANAGER_HEADERS
        ),
        expected_status=201,
    )

    assert event["status"] == EVENT_OPEN
    assert_leak_event_schedule(
        event,
        initial_repair_deadline="2026-08-31T00:00:00Z",
        repair_deadline="2026-08-31T00:00:00Z",
    )
    assert_instant_is_none(event["verification_deadline"], "verification_deadline")
    assert_instant_is_none(
        event["last_repair_completed_at"], "last_repair_completed_at"
    )
    assert_extension_budget(event, granted_total=0, remaining=30)
    assert event["repair_attempt_count"] == 0
    assert event["failed_verification_count"] == 0
    assert event["late_repair_flag"] is False
    assert_money(event["threshold_pct_applied"], 20.0, "threshold_pct_applied")
    assert_money(
        event["leak_rate_pct_at_detection"], 0.0, "leak_rate_pct_at_detection"
    )
    assert event["triggering_service_record_id"] is None

    system = X.get_system(api, env["system_id"])
    assert_system_axes(system, compliance_state=STATE_LEAK_OPEN)
    assert system["exceedance_count_12mo"] == 1
    assert_store_posture(
        X.get_store(api, env["store_id"]),
        open_leak_event_count=1,
        compliance_status=POSTURE_AT_RISK,
    )


def test_a_second_manual_declaration_on_the_same_system_is_a_conflict(api):
    """
    The duplicate is neither a second event nor a silent success, so the store's
    open count cannot be double-counted.

    Design: Corner/state_machines/second_manual_leak_event_on_same_system_cannot_be_declared_twice
    """
    env = X.manual_event_env(api)

    validate_error(
        api.create_leak_event(
            F.leak_event_payload(env["system_id"]), REGULATOR_HEADERS
        ),
        ERR_OPEN_LEAK_EVENT_EXISTS,
        409,
    )

    listing = X.list_leak_events(api, system_id=env["system_id"])
    assert listing["meta"]["total_count"] == 1
    assert listing["data"][0]["id"] == env["event_id"]

    assert X.get_system(api, env["system_id"])["exceedance_count_12mo"] == 1
    assert_store_posture(
        X.get_store(api, env["store_id"]),
        open_leak_event_count=1,
        compliance_status=POSTURE_AT_RISK,
    )


def test_a_closed_leak_event_is_terminal_and_takes_no_further_repair(api):
    """
    Walking the event through repair, an initial pass and a follow-up pass closes
    it for good: a further attempt is refused, the attempt that earned the closure
    is marked verified, and the system falls back to compliant on a re-based leak
    rate.

    Design: Corner/state_machines/verified_closed_leak_event_is_terminal_and_rejects_further_repair
    """
    env = X.manual_event_env(api)
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
    test1 = X.file_verification_test(
        api,
        env["event_id"],
        attempt1["id"],
        env["tech2_id"],
        "2026-08-07T10:00:00Z",
        test_method_code="PRESSURE_DECAY",
        result=RESULT_PASS,
        measured_leak_rate_pct=0.0,
    )
    test2 = X.file_verification_test(
        api,
        env["event_id"],
        attempt1["id"],
        env["tech2_id"],
        "2026-08-07T11:00:00Z",
        test_method_code="ELECTRONIC_DETECTOR",
        result=RESULT_PASS,
        measured_leak_rate_pct=0.0,
    )
    assert test1["test_sequence"] == SEQUENCE_INITIAL
    assert test2["test_sequence"] == SEQUENCE_FOLLOWUP

    validate_error(
        api.create_repair_attempt(
            F.repair_attempt_payload(
                env["event_id"],
                env["system_id"],
                env["tech1_id"],
                env["eq1_id"],
                "2026-08-07T09:00:00Z",
                repair_method_code="REPLACE_VALVE",
            ),
            make_technician_headers(env["tech1_id"]),
        ),
        ERR_LEAK_EVENT_TERMINAL,
        409,
    )

    event = X.get_leak_event(api, env["event_id"])
    assert event["status"] == EVENT_VERIFIED_CLOSED
    assert_instant(event["closed_at"], "2026-08-08T00:00:00Z", "closed_at")
    assert event["repair_attempt_count"] == 1
    assert X.get_repair_attempt(api, attempt1["id"])["outcome"] == ATTEMPT_VERIFIED

    system = X.get_system(api, env["system_id"])
    assert_system_axes(system, compliance_state=STATE_COMPLIANT)
    assert_instant(
        system["leak_rate_baseline_at"], "2026-08-07T11:00:00Z", "leak_rate_baseline_at"
    )
    assert_store_posture(
        X.get_store(api, env["store_id"]),
        open_leak_event_count=0,
        compliance_status=POSTURE_COMPLIANT,
    )


def test_retirement_is_not_idempotent_and_the_aggregates_drop_once(api):
    """
    The first retirement stamps the retirement instant and forces the exempt
    posture; the identical second call is refused, and the store's regulated
    aggregates fall exactly once.

    Design: Corner/state_machines/retiring_an_already_retired_system_is_rejected
    """
    env = X.empty_system_env(api)

    retired = X.retire_system(
        api, env["system_id"], retirement_reason_code="END_OF_LIFE"
    )
    assert_system_axes(
        retired,
        operational_status=SYSTEM_RETIRED,
        compliance_state=STATE_RETIRED_EXEMPT,
    )
    assert_instant(retired["retired_on"], "2026-08-01T00:00:00Z", "retired_on")
    assert retired["replaced_by_system_id"] is None

    validate_error(
        api.retire_system(
            env["system_id"],
            F.retirement_payload(retirement_reason_code="END_OF_LIFE"),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        ERR_SYSTEM_RETIRED,
        409,
    )

    assert_store_posture(
        X.get_store(api, env["store_id"]),
        regulated_system_count=0,
        total_regulated_charge_lbs=0.0,
        compliance_status=POSTURE_COMPLIANT,
    )


def test_a_recovery_moves_the_cylinder_from_virgin_to_recovered(api):
    """
    One write moves mass out of the system and into the cylinder: the fill limit is
    the derived four fifths of the nominal capacity, the disposition flips, and the
    store's four buckets still total what they did before.

    Design: Corner/state_machines/recovering_refrigerant_moves_cylinder_from_virgin_to_recovered
    """
    env = X.base_env(
        api,
        with_second_technician=False,
        cylinder_overrides={"initial_contents_lbs": 0.0},
    )

    assert_mass(env["cyl1"]["fill_limit_lbs"], 40.0, "fill_limit_lbs")
    assert_mass(env["cyl1"]["current_contents_lbs"], 0.0, "current_contents_lbs")
    assert env["cyl1"]["disposition"] == DISPOSITION_VIRGIN
    assert_mass(
        env["cyl1"]["shipped_for_reclaim_lbs"], 0.0, "shipped_for_reclaim_lbs"
    )

    validate_success(
        api.create_service_record(
            F.service_record_payload(
                env["system_id"],
                env["tech1_id"],
                env["eq1_id"],
                X.system_version(api, env["system_id"]),
                cylinder_id=env["cyl1_id"],
                service_type=SERVICE_RECOVER_REFRIGERANT,
                refrigerant_added_lbs=F.OMIT,
                refrigerant_recovered_lbs=30.0,
                performed_at="2026-08-01T00:00:00Z",
                duration_minutes=60,
            ),
            make_technician_headers(env["tech1_id"]),
        ),
        expected_status=201,
    )

    cylinder = X.get_cylinder(api, env["cyl1_id"])
    assert_mass(cylinder["current_contents_lbs"], 30.0, "current_contents_lbs")
    assert cylinder["disposition"] == DISPOSITION_RECOVERED

    system = X.get_system(api, env["system_id"])
    assert_system_charge(system, current_charge_lbs=50.0, leak_rate_pct=0.0)
    assert system["version"] == 2
    assert X.list_leak_events(api, system_id=env["system_id"])["meta"]["total_count"] == 0

    assert_mass_conserved(
        [system], [cylinder], X.get_store(api, env["store_id"]), 80.0
    )


def test_reclaim_shipment_and_certification_only_move_mass_between_buckets(api):
    """
    Shipment empties the cylinder's contents into its shipped bucket and the
    certification returns the reclaimed mass, leaving the reclaimer's residue
    behind — so contents plus shipped is constant and nothing is written off.

    Design: Corner/state_machines/reclaim_shipment_then_certification_conserves_mass_with_residue
    """
    env = X.base_env(
        api,
        with_second_technician=False,
        cylinder_overrides={"initial_contents_lbs": 0.0},
    )
    X.file_service_record(
        api,
        env["system_id"],
        env["tech1_id"],
        env["eq1_id"],
        cylinder_id=env["cyl1_id"],
        service_type=SERVICE_RECOVER_REFRIGERANT,
        refrigerant_added_lbs=F.OMIT,
        refrigerant_recovered_lbs=30.0,
        performed_at="2026-08-01T00:00:00Z",
        duration_minutes=60,
    )

    shipped = validate_success(
        api.ship_for_reclaim(
            env["cyl1_id"],
            F.reclaim_shipment_payload(reclaimer_name="Cascade Reclaim LLC"),
            COMPLIANCE_MANAGER_HEADERS,
        )
    )
    assert shipped["disposition"] == DISPOSITION_SENT_FOR_RECLAIM
    assert_mass(shipped["current_contents_lbs"], 0.0, "current_contents_lbs")
    assert_mass(shipped["shipped_for_reclaim_lbs"], 30.0, "shipped_for_reclaim_lbs")
    assert_instant(shipped["shipped_on"], "2026-08-01T00:00:00Z", "shipped_on")
    assert shipped["reclaimer_name"] == "Cascade Reclaim LLC"
    assert_mass(
        float(shipped["current_contents_lbs"]) + float(shipped["shipped_for_reclaim_lbs"]),
        30.0,
        "contents plus shipped",
    )

    certified = validate_success(
        api.certify_reclaim(
            env["cyl1_id"],
            F.reclaim_certification_payload(28.5, "2026-08-01T00:00:00Z"),
            COMPLIANCE_MANAGER_HEADERS,
        )
    )
    assert certified["disposition"] == DISPOSITION_RECLAIMED
    assert_mass(certified["current_contents_lbs"], 28.5, "current_contents_lbs")
    assert_mass(certified["shipped_for_reclaim_lbs"], 1.5, "shipped_for_reclaim_lbs")
    assert certified["reclaim_certificate_number"] == "RC-2026-0001"
    assert certified["purity_verified"] is True
    assert_mass(certified["reclaimed_quantity_lbs"], 28.5, "reclaimed_quantity_lbs")
    assert_instant(
        certified["reclaim_issued_on"], "2026-08-01T00:00:00Z", "reclaim_issued_on"
    )
    assert_mass(
        float(certified["current_contents_lbs"])
        + float(certified["shipped_for_reclaim_lbs"]),
        30.0,
        "contents plus shipped",
    )

    store = X.get_store(api, env["store_id"])
    assert_mass_conserved(
        [X.get_system(api, env["system_id"])], [certified], store, 80.0
    )
    assert_mass(store["vented_loss_lbs"], 0.0, "vented_loss_lbs")


def test_equipment_sweeps_to_overdue_and_reverification_restores_it(api):
    """
    The machine has no terminal state: the annual-verification sweep pushes it out
    of certification, which blocks all service work, and a fresh verification cycles
    it straight back with its verification date advanced.

    Design: Corner/state_machines/equipment_sweeps_to_verification_overdue_then_reverification_restores_it
    """
    env = X.base_env(api, with_second_technician=False)
    assert env["eq1"]["status"] == EQUIPMENT_CERTIFIED

    X.set_clock(api, "2027-07-01T00:00:00Z")
    report = X.run_sweep(api)
    assert env["eq1_id"] in report["overdue_equipment_ids"]
    assert (
        X.get_equipment(api, env["eq1_id"])["status"] == EQUIPMENT_VERIFICATION_OVERDUE
    )

    validate_error(
        api.create_service_record(
            F.service_record_payload(
                env["system_id"],
                env["tech1_id"],
                env["eq1_id"],
                X.system_version(api, env["system_id"]),
                cylinder_id=env["cyl1_id"],
                refrigerant_added_lbs=5.0,
                performed_at="2027-07-01T00:00:00Z",
                duration_minutes=60,
            ),
            make_technician_headers(env["tech1_id"]),
        ),
        ERR_RECOVERY_EQUIPMENT_NOT_CERTIFIED,
        422,
    )
    assert_system_charge(X.get_system(api, env["system_id"]), current_charge_lbs=80.0)

    verified = validate_success(
        api.verify_recovery_equipment(
            env["eq1_id"],
            F.equipment_verification_payload("2027-07-01T00:00:00Z"),
            COMPLIANCE_MANAGER_HEADERS,
        )
    )
    assert verified["status"] == EQUIPMENT_CERTIFIED
    assert_instant(
        verified["last_verification_on"], "2027-07-01T00:00:00Z", "last_verification_on"
    )


def test_accepting_a_draft_report_is_not_a_declared_transition(api):
    """
    A draft filing has exactly one way out — submission — so a regulator's
    acceptance is refused even though the role is right, and the filing keeps its
    untouched submission counters.

    Design: Corner/state_machines/deciding_a_draft_regulatory_report_is_not_a_declared_transition
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    store = X.create_store(api)
    report = validate_success(
        api.create_regulatory_report(
            F.regulatory_report_payload(
                store["id"],
                period_start="2026-01-01T00:00:00Z",
                period_end="2026-06-30T00:00:00Z",
            ),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        expected_status=201,
    )

    validate_error(
        api.decide_regulatory_report(
            report["id"],
            F.report_decision_payload(REPORT_DECISION_ACCEPT),
            REGULATOR_HEADERS,
        ),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )

    stored = X.get_report(api, report["id"])
    assert stored["status"] == REPORT_DRAFT
    assert_instant_is_none(stored["submitted_at"], "submitted_at")
    assert stored["submission_count"] == 0
    assert_instant_is_none(stored["decided_at"], "decided_at")
    assert_instant(stored["due_on"], "2026-08-29T00:00:00Z", "due_on")
    assert stored["days_late"] == 0
    assert_money(
        stored["late_filing_assessment_usd"], 0.00, "late_filing_assessment_usd"
    )


def test_an_escalated_inspection_keeps_its_escalation_after_a_late_response(api):
    """
    The sweep escalates the unanswered inspection, and the store's later response
    moves it on without erasing the escalation stamp; the exposure keeps the
    compliant multiplier throughout.

    Design: Corner/state_machines/inspection_escalates_on_sweep_then_late_response_retains_escalation
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    store = X.create_store(api)
    inspection = X.open_inspection(
        api,
        store["id"],
        citations=[F.citation("608-LEAK-REC")],
        inspector_name="Inspector Vale",
    )
    assert_instant(
        inspection["response_deadline"], "2026-08-31T00:00:00Z", "response_deadline"
    )
    assert inspection["status"] == INSPECTION_OPEN
    assert_penalty_exposure(
        inspection,
        penalty_exposure_usd=275.55,
        chronic_multiplier_applied=1.00,
        capped=False,
    )

    X.set_clock(api, "2026-09-05T00:00:00Z")
    report = X.run_sweep(api, store_id=store["id"])
    assert_sweep_report(report, escalated_inspections=[inspection["id"]])

    escalated = X.get_inspection(api, inspection["id"])
    assert escalated["status"] == INSPECTION_ESCALATED
    assert_instant(escalated["escalated_at"], "2026-09-05T00:00:00Z", "escalated_at")

    responded = validate_success(
        api.respond_to_inspection(
            inspection["id"],
            F.inspection_response_payload(
                response_summary="All records corrected and filed with the agency.",
                corrective_action_code="RECORDS_CORRECTED",
            ),
            make_store_manager_headers(store["id"]),
        )
    )
    assert responded["status"] == INSPECTION_RESPONDED
    assert_instant(responded["responded_at"], "2026-09-05T00:00:00Z", "responded_at")
    assert_instant(responded["escalated_at"], "2026-09-05T00:00:00Z", "escalated_at")
    assert responded["corrective_action_code"] == "RECORDS_CORRECTED"
    assert_penalty_exposure(responded, penalty_exposure_usd=275.55)
    assert_store_posture(
        X.get_store(api, store["id"]), penalty_exposure_total_usd=275.55
    )


def test_a_newer_plan_supersedes_the_draft_and_locks_it_out_of_submission(api):
    """
    The second plan supersedes only the earlier draft and itself stays a draft; the
    superseded row can never be submitted again, and both rows carry the same
    computed compatibility.

    Design: Corner/state_machines/filing_a_newer_plan_supersedes_the_draft_and_locks_it_out_of_submission
    """
    env = X.base_env(api, with_r448a=True, with_second_technician=False)

    plan1 = X.file_retrofit_plan(
        api,
        env["system_id"],
        target_refrigerant_type_id=env["rt448_id"],
        due_on="2026-12-01T00:00:00Z",
        estimated_cost_usd=50000.00,
    )
    plan2 = X.file_retrofit_plan(
        api,
        env["system_id"],
        target_refrigerant_type_id=env["rt448_id"],
        due_on="2027-01-15T00:00:00Z",
        estimated_cost_usd=61000.00,
    )

    assert X.get_plan(api, plan1["id"])["status"] == PLAN_SUPERSEDED
    stored2 = X.get_plan(api, plan2["id"])
    assert stored2["status"] == PLAN_DRAFT
    assert stored2["submission_count"] == 0
    assert_instant_is_none(stored2["submitted_at"], "submitted_at")

    for plan in (X.get_plan(api, plan1["id"]), stored2):
        assert_money(plan["compatibility_score"], 84.1, "compatibility_score")
        assert plan["compatibility_result"] == "COMPATIBLE"
        assert_money(plan["gwp_reduction_pct"], 64.6, "gwp_reduction_pct")
        assert plan["mandated"] is False

    validate_error(
        api.submit_retrofit_plan(
            plan1["id"],
            F.plan_submission_payload(
                submission_note="Attempting to submit the superseded plan."
            ),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )
    assert X.get_plan(api, plan1["id"])["submission_count"] == 0


def test_technician_suspension_and_reinstatement_are_both_real_transitions(api):
    """
    Suspension records its reason and reinstatement clears it back to nothing, while
    suspending an already suspended technician is refused rather than treated as a
    no-op.

    Design: Corner/state_machines/technician_suspension_then_reinstatement_clears_the_reason_code
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    technician = X.create_technician(api)
    assert technician["status"] == TECHNICIAN_ACTIVE
    assert technician["suspension_reason_code"] is None
    assert technician["repair_attempt_count"] == 0

    suspended = X.suspend_technician(
        api, technician["id"], "RECOVERY_PROCEDURE_VIOLATION"
    )
    assert suspended["status"] == TECHNICIAN_SUSPENDED
    assert suspended["suspension_reason_code"] == "RECOVERY_PROCEDURE_VIOLATION"

    validate_error(
        api.change_technician_status(
            technician["id"],
            F.technician_status_change_payload(
                TECHNICIAN_SUSPENDED, "RECOVERY_PROCEDURE_VIOLATION"
            ),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )

    reinstated = X.reinstate_technician(
        api, technician["id"], "RETRAINING_COMPLETED"
    )
    assert reinstated["status"] == TECHNICIAN_ACTIVE
    assert reinstated["suspension_reason_code"] is None
