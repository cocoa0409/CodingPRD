"""Injury-case state machine and treatment-plan lifecycle."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    record_status_entry,
    setup_closed_case,
    setup_open_case,
    create_active_plan,
    validate_error,
    validate_success,
)


class TestCaseTransitions:
    def test_start_rehab_from_open_succeeds(self, api, medical_staff_headers):
        """PRD §3.3: "Starting rehabilitation transitions the case from `OPEN`
        to `REHAB`. The transition requires the case to be `OPEN` (otherwise
        `ERR_CASE_NOT_OPEN`) and at least one `is_current` daily status entry
        to exist for the case (otherwise `ERR_NO_STATUS_ENTRY`)."

        Design: Corner/state_machines/start_rehab_from_open_succeeds
        """
        sc = setup_open_case()
        record_status_entry(sc["case"]["id"], "2026-08-01", designation="OUT")
        resp = api.start_rehab(sc["case"]["id"], medical_staff_headers)
        case = validate_success(resp)
        assert case["status"] == "REHAB", (
            f"OPEN case with a status entry must transition to REHAB, got {case['status']}"
        )

    def test_close_from_open_rejected(self, api, medical_staff_headers):
        """PRD §3.5: "Closing a case requires it to be `CLEARED` (otherwise
        `ERR_CASE_NOT_CLEARED`), with no treatment plan in `ACTIVE` or
        `SUSPENDED` (otherwise `ERR_PLAN_STILL_ACTIVE`) and no claim in
        `DRAFT`, `SUBMITTED`, or `APPEALED` (otherwise `ERR_CLAIMS_OPEN`)."

        Design: Corner/state_machines/close_from_open_rejected_invalid_state
        """
        sc = setup_open_case()
        resp = api.close_case(sc["case"]["id"], medical_staff_headers)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_CLEARED)
        case = get_success_data(api.get_injury_case(sc["case"]["id"], medical_staff_headers))
        assert case["status"] == "OPEN", "rejected close must not mutate case state"

    def test_closed_case_rejects_further_transitions(self, api, medical_staff_headers):
        """PRD §3.3: "Starting rehabilitation transitions the case from `OPEN`
        to `REHAB`. The transition requires the case to be `OPEN` (otherwise
        `ERR_CASE_NOT_OPEN`) and at least one `is_current` daily status entry
        to exist for the case (otherwise `ERR_NO_STATUS_ENTRY`)."

        Design: Corner/state_machines/terminal_state_lockdown_closed_case
        """
        sc = setup_closed_case()
        assert sc["case"]["status"] == "CLOSED"
        resp = api.start_rehab(sc["case"]["id"], medical_staff_headers)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_OPEN)


class TestTreatmentPlanLifecycle:
    def test_plan_suspend_resume_cycle(self, api, medical_staff_headers):
        """PRD §3.3: "An `ACTIVE` plan may be suspended, which records the
        request body `reason` into `suspension_reason`, and a `SUSPENDED` plan
        may be resumed, which clears `suspension_reason`."

        Design: Corner/state_machines/treatment_plan_suspend_resume_cycle
        """
        sc = setup_open_case()
        plan = create_active_plan(sc["case"]["id"])
        assert plan["status"] == "ACTIVE"

        suspended = validate_success(
            api.suspend_plan(plan["id"], {"reason": "illness"}, medical_staff_headers)
        )
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "illness", (
            "suspend must record the request body reason into suspension_reason"
        )

        resumed = validate_success(api.resume_plan(plan["id"], medical_staff_headers))
        assert resumed["status"] == "ACTIVE"
        assert resumed.get("suspension_reason") is None, (
            "resume must clear suspension_reason"
        )


class TestAvailabilityTierAcrossCases:
    def test_tier_is_worst_contribution_across_open_cases(self, api, medical_staff_headers):
        """PRD §3.7: "The athlete's tier is the most restrictive contribution
        across all candidate cases, with severity order `OUT` more restrictive
        than `LIMITED`, which is more restrictive than `MODIFIED`, which is
        more restrictive than `FULL`."
        PRD §3.7: "An `OPEN` case forces the contribution to at least
        `LIMITED` — never `FULL`."

        Design: Corner/calculations/availability_tier_worst_case_across_cases
        """
        sc = setup_open_case(clock="2026-08-03T00:00:00Z", occurred_on="2026-08-02")
        case2 = get_success_data(
            api.create_injury_case(
                {
                    "athlete_id": sc["athlete"]["id"],
                    "diagnosis_code_id": sc["diagnosis_code"]["id"],
                    "occurred_on": "2026-08-02",
                    "surface": "TURF",
                    "mechanism": "NON_CONTACT",
                },
                medical_staff_headers,
            )
        )
        record_status_entry(sc["case"]["id"], "2026-08-03", designation="OUT",
                            functional_test_score=30)
        record_status_entry(case2["id"], "2026-08-03", designation="MODIFIED",
                            symptom_free=True, functional_test_score=70)
        athlete = get_success_data(api.get_athlete(sc["athlete"]["id"], medical_staff_headers))
        assert athlete["availability_tier"] == "OUT", (
            "worst contribution across cases (OUT beats MODIFIED-floored-to-LIMITED) "
            f"must win, got {athlete['availability_tier']}"
        )
