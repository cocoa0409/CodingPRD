"""State-machine corners: invalid transitions, precondition enforcement,
terminal-state lockdown, initial state, and the permit-final close cascade.

Queue B (state_machines section).
"""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, get_success_data,
    TEST_USERS, ApiErrorId,
    create_estimator_payload, create_job_payload, create_estimate_payload,
    create_line_item_payload, create_inspection_payload, complete_inspection_payload,
    create_crew, create_crew_assignment_payload,
    setup_estimated_job, setup_contracted_job, setup_in_production_job,
)

FA = TEST_USERS["field_adjuster_headers"]
EST = TEST_USERS["estimator_headers"]
PM = TEST_USERS["production_manager_headers"]

SHINGLE_10 = [{"trade": "SHINGLE", "squares": 10, "unit_price_cents": 10000, "waste_factor_pct": 0.10}]


def _estimator_id(api):
    return get_success_data(api.create_estimator(create_estimator_payload(), EST))["id"]


def _fresh_job(api):
    return get_success_data(api.create_job(
        create_job_payload(assigned_estimator_id=_estimator_id(api)), FA))["id"]


class TestInvalidTransitions:
    def test_finalize_already_finalized_estimate_rejected(self, api):
        """PRD §2.9: "(7) whether the target resource is in a state from which
        the requested transition is defined, else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/finalize_already_finalized_estimate_invalid_state
        """
        job_id = _fresh_job(api)
        est = get_success_data(api.create_estimate(
            create_estimate_payload(job_id=job_id, source_kind="FIELD"), EST))
        api.add_line_item(est["id"], create_line_item_payload(), EST)
        api.finalize_estimate(est["id"], EST)
        validate_error(api.finalize_estimate(est["id"], EST),
                       ApiErrorId.ERR_INVALID_STATE.value)

    def test_lose_contracted_job_rejected(self, api):
        """PRD §3.1: "At any point before a contract is bound — that is, while
        the job is in `LEAD`, `INSPECTED`, or `ESTIMATED` — a `FieldAdjuster`
        may abandon the lead, moving the job to the terminal `LOST` status."

        Design: Corner/state_machines/lose_a_completed_job_invalid_state
        """
        job_id, _ = setup_contracted_job(line_items=SHINGLE_10)
        validate_error(api.lose_job(job_id, {"lost_reason": "too late"}, FA),
                       ApiErrorId.ERR_INVALID_STATE.value)

    def test_contract_already_contracted_job_rejected(self, api):
        """PRD §3.3: "A job may be contracted only once: if the job already has a
        bound estimate, the request is rejected with `ERR_ALREADY_CONTRACTED`."
        PRD §2.9: "(7) whether the target resource is in a state from which the
        requested transition is defined, else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/contract_twice_already_contracted
        """
        # PRD orders the state check (7) ahead of the business check that yields
        # ERR_ALREADY_CONTRACTED, but does not commit to which pre-empts on a
        # second contract of a CONTRACTED job; either rejection is PRD-faithful.
        job_id, est = setup_estimated_job(line_items=SHINGLE_10)
        validate_success(api.contract_job(job_id, {"estimate_id": est["id"]}, EST))
        validate_error_is_one_of(
            api.contract_job(job_id, {"estimate_id": est["id"]}, EST),
            [ApiErrorId.ERR_INVALID_STATE.value, ApiErrorId.ERR_ALREADY_CONTRACTED.value])


class TestPreconditionEnforcement:
    def test_finalize_empty_estimate_rejected(self, api):
        """PRD §3.2: "Finalization is refused with `ERR_EMPTY_ESTIMATE` if the
        estimate has no line items."

        Design: Corner/state_machines/finalize_empty_estimate_rejected
        """
        job_id = _fresh_job(api)
        est = get_success_data(api.create_estimate(
            create_estimate_payload(job_id=job_id, source_kind="FIELD"), EST))
        validate_error(api.finalize_estimate(est["id"], EST),
                       ApiErrorId.ERR_EMPTY_ESTIMATE.value)

    def test_mark_inspected_without_passed_assessment_rejected(self, api):
        """PRD §3.1: "If no passed damage-assessment inspection exists for the
        job, the advance is rejected with `ERR_NO_PASSED_ASSESSMENT`."

        Design: Corner/state_machines/mark_inspected_without_passed_assessment
        """
        job_id = _fresh_job(api)
        validate_error(api.mark_job_inspected(job_id, FA),
                       ApiErrorId.ERR_NO_PASSED_ASSESSMENT.value)

    def test_damage_assessment_pass_requires_severity(self, api):
        """PRD §3.1: "When the inspection is a `DAMAGE_ASSESSMENT` being passed,
        the completing request must also record a `damage_severity` of `MINOR`,
        `MODERATE`, or `TOTAL_LOSS`; omitting it is rejected with
        `ERR_SEVERITY_REQUIRED` (HTTP 422)."

        Design: Corner/state_machines/damage_assessment_pass_requires_severity
        """
        job_id = _fresh_job(api)
        insp = get_success_data(api.create_inspection(create_inspection_payload(
            job_id=job_id, kind="DAMAGE_ASSESSMENT"), FA))
        validate_error(api.complete_inspection(
            insp["id"], complete_inspection_payload(outcome="PASS"), FA),
            ApiErrorId.ERR_SEVERITY_REQUIRED.value)


class TestInitialStateAndCascades:
    def test_new_inspection_starts_scheduled(self, api):
        """PRD §3.1: "A new inspection begins in `SCHEDULED` status."

        Design: Corner/state_machines/complete_inspection_initial_state
        """
        job_id = _fresh_job(api)
        data = validate_success(api.create_inspection(create_inspection_payload(
            job_id=job_id, kind="DAMAGE_ASSESSMENT"), FA), expected_status=201)
        assert data["status"] == "SCHEDULED"

    def test_permit_final_pass_closes_issued_permit(self, api):
        """PRD §3.1: "if the permit it references is currently `ISSUED`, that
        permit is automatically transitioned to `CLOSED` and its own `version`
        increments — the inspection's pass is what closes the permit."

        Design: Corner/state_machines/permit_final_pass_closes_permit_cross_entity
        """
        job_id, info = setup_in_production_job(line_items=SHINGLE_10)
        permit_id = info["permit"]["id"]
        pf = get_success_data(api.create_inspection(create_inspection_payload(
            job_id=job_id, kind="PERMIT_FINAL", permit_id=permit_id,
            scheduled_start="2026-07-10T08:00:00Z", scheduled_end="2026-07-10T12:00:00Z"), FA))
        data = validate_success(api.complete_inspection(
            pf["id"], complete_inspection_payload(outcome="PASS"), FA))
        assert data["status"] == "PASSED"
        permit = get_success_data(api.get_permit(permit_id, PM))
        assert permit["status"] == "CLOSED"

    def test_cancel_booked_crew_frees_its_window(self, api):
        """PRD §3.6: "A still-`BOOKED` assignment may instead be cancelled,
        moving it to `CANCELLED` and freeing its half-open window for
        re-booking."

        Design: Corner/state_machines/cancel_booked_crew_frees_window
        """
        job_id, _ = setup_in_production_job(line_items=SHINGLE_10)
        crew = create_crew(name="Crew Delta")
        ca1 = get_success_data(api.create_crew_assignment(create_crew_assignment_payload(
            job_id=job_id, crew_id=crew["id"],
            window_start="2026-07-01T08:00:00Z", window_end="2026-07-01T16:00:00Z"), PM))
        validate_success(api.cancel_crew_assignment(ca1["id"], PM))
        # The identical window can be re-booked once the first is cancelled.
        data = validate_success(api.create_crew_assignment(create_crew_assignment_payload(
            job_id=job_id, crew_id=crew["id"],
            window_start="2026-07-01T08:00:00Z", window_end="2026-07-01T16:00:00Z"), PM),
            expected_status=201)
        assert data["status"] == "BOOKED"
