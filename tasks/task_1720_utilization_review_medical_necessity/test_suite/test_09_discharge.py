"""Discharge: the PROVISIONAL-to-FINAL two-midnight variant switch, the
closure cascade over authorizations and escalations, and terminal lockdown
(PRD §2.8, §3.9)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_avoidable_day,
    assert_utilization_case,
    discharge_case,
    discharge_payload,
    get_auth,
    get_case,
    list_escalations,
    setup_case,
    setup_submitted_auth,
    validate_error,
    validate_success,
)

NURSE = TEST_USERS["ur_nurse_headers"]


class TestTwoMidnightVariants:
    def test_two_midnight_provisional_benchmark_at_creation(self, api):
        """PRD §2.8: "At case creation, the **PROVISIONAL** variant runs: `expected_midnight_count` is computed from `admit_at` and the physician-documented `expected_discharge_at`, `two_midnight_benchmark_met` is evaluated against that count, and `benchmark_basis` is set to `PROVISIONAL`."
        PRD §2.8: "`actual_midnight_count` remains null until discharge."

        Design: Difficulty/dual_variant_calc/two_midnight_provisional_vs_final
        """
        ctx = setup_case(patient_mrn="MRN-DV1")
        case = ctx["case"]
        assert_utilization_case(case)
        # Expected stay 2026-08-01 -> 2026-08-03 crosses two date boundaries.
        assert case["expected_midnight_count"] == 2
        assert case["two_midnight_benchmark_met"] == "MET"
        assert case["benchmark_basis"] == "PROVISIONAL"
        assert case.get("actual_midnight_count") is None

    def test_two_midnight_final_benchmark_after_discharge(self, api):
        """PRD §2.8: "At discharge, the **FINAL** variant runs: `actual_midnight_count` is computed from `admit_at` and the actual `discharge_at`, the benchmark is re-evaluated against that count, and `benchmark_basis` flips to `FINAL`."
        PRD §2.8: "A stay documented as two midnights can therefore end `NOT_MET` in the final accounting when actual discharge occurs earlier than expected, and the two variants genuinely differ whenever the expected and actual discharge dates differ."

        Design: Difficulty/dual_variant_calc/two_midnight_provisional_vs_final
        """
        ctx = setup_case(patient_mrn="MRN-DV1B")
        # Discharge one day earlier than documented: 2026-08-01 -> 2026-08-02.
        discharged = validate_success(api.discharge_case(
            ctx["case"]["id"], discharge_payload("2026-08-02T09:00:00Z"),
            NURSE))
        assert discharged["actual_midnight_count"] == 1
        assert discharged["two_midnight_benchmark_met"] == "NOT_MET", (
            "the FINAL variant re-evaluates on actual dates and flips the "
            "benchmark the PROVISIONAL variant had set to MET")
        assert discharged["benchmark_basis"] == "FINAL"
        assert discharged["review_status"] == "CLOSED"


class TestClosureCascade:
    def test_discharge_cascade_withdraws_and_resolves(self, api):
        """PRD §3.9: "Discharge fires a coordinated closure cascade in a single request: the FINAL two-midnight variant of §2.8 runs (`actual_midnight_count` computed, `two_midnight_benchmark_met` re-evaluated, `benchmark_basis` set to `FINAL`); `review_status` moves to `CLOSED`; every authorization request still in `SUBMITTED` or `PENDED` is withdrawn (`AUTH_WITHDRAWN` for each); every escalation case still `OPEN` or `ACKNOWLEDGED` is resolved with `resolution_note` set to `auto: case discharged`; the case `version` increments; and `CASE_DISCHARGED` is appended."

        Design: Corner/endpoints/discharge_cascade_withdraws_and_resolves
        """
        ctx = setup_submitted_auth(plan_class="COMMERCIAL",
                                   name="Commercial PPO", patient_mrn="MRN-DC1")
        case_id = ctx["case"]["id"]
        add_avoidable_day(case_id, "2026-08-02", "PLACEMENT_DELAY", 3)
        add_avoidable_day(case_id, "2026-08-03", "TRANSPORT_DELAY", 2)
        escalation = list_escalations(case_id)[0]
        assert escalation["status"] == "OPEN"

        discharged = discharge_case(case_id, "2026-08-04T09:00:00Z")
        assert discharged["review_status"] == "CLOSED"
        # 2026-08-01 -> 2026-08-04 crosses three calendar-date boundaries.
        assert discharged["actual_midnight_count"] == 3
        assert discharged["two_midnight_benchmark_met"] == "MET"
        assert discharged["benchmark_basis"] == "FINAL"

        assert get_auth(ctx["auth"]["id"])["status"] == "WITHDRAWN", (
            "the closure cascade withdraws the still-SUBMITTED request")

        resolved = list_escalations(case_id)[0]
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution_note"] == "auto: case discharged"

    def test_discharge_terminal_lockdown(self, api):
        """PRD §3.9: "Discharge is a `URNurse` action carrying the actual `discharge_at` timestamp, valid from any non-`CLOSED` review status — `INTAKE`, `ADMISSION_REVIEWED`, or `MONITORING`; repeating discharge against an already-closed case fails state-machine legality with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/discharge_terminal_lockdown
        """
        ctx = setup_case(patient_mrn="MRN-TERM")
        discharge_case(ctx["case"]["id"], "2026-08-03T09:00:00Z")

        resp = api.discharge_case(ctx["case"]["id"],
                                  discharge_payload("2026-08-03T09:00:00Z"),
                                  NURSE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_case(ctx["case"]["id"])["review_status"] == "CLOSED"
