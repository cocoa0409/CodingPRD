"""Injury reports and the workers' compensation lifecycle."""
from test_helpers import (
    ApiErrorId,
    assert_injury_report,
    assert_instant,
    create_exposure_case,
    create_injury,
    create_injury_payload,
    get_case_pep,
    get_injury,
    register_employee,
    set_clock,
    start_pep,
    transition_injury,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestWcAppealCycle:
    def test_deny_appeal_loop_reenters_denied(self, api):
        """PRD §3.8: "A denied report may move from `WC_DENIED` to `APPEALED`,
        and the deny-and-appeal loop between `WC_DENIED` and `APPEALED` may
        repeat without bound."

        Design: Difficulty/non_linear_state_machine/injury_report_wc_appeal_cycle
        """
        emp = register_employee("E-NL2", full_name="Cy Cle",
                                job_category="HOUSEKEEPING", department="EVS")
        injury = create_injury(emp["id"], injury_type="FALL",
                               injury_datetime="2026-07-15T14:00:00Z")
        submitted = transition_injury(injury["id"], "WC_SUBMITTED")
        claim = submitted["wc_claim_number"]
        assert claim == "WC-000001", "first submission in an empty system"
        assert_injury_report(submitted)

        transition_injury(injury["id"], "WC_DENIED")
        transition_injury(injury["id"], "APPEALED")
        second_denial = transition_injury(injury["id"], "WC_DENIED")
        assert second_denial["status"] == "WC_DENIED", (
            "the loop re-enters WC_DENIED after an appeal — it is not one-shot"
        )
        assert second_denial["wc_claim_number"] == claim, (
            "the claim number stays fixed across the deny/appeal cycle"
        )

    def test_appeal_then_accepted_terminal_with_stable_claim(self, api):
        """PRD §3.8: "From either `WC_SUBMITTED` or `APPEALED`, the report may
        move to `WC_ACCEPTED` — the terminal accepted outcome — or to
        `WC_DENIED`." and "An injury is recordable when its `injury_type` is
        `NEEDLESTICK`; or when it is linked to an exposure case whose
        `risk_classification` is `HIGH`; or when it is linked to an exposure
        case that has a prophylaxis regimen in `STARTED` or `COMPLETED`."

        Design: Difficulty/non_linear_state_machine/injury_report_wc_appeal_cycle
        """
        emp = register_employee("E-NL2B", full_name="Cy Cle Two",
                                job_category="HOUSEKEEPING", department="EVS")
        injury = create_injury(emp["id"], injury_type="FALL",
                               injury_datetime="2026-07-15T14:00:00Z")
        # FALL with no linked exposure case satisfies no recordable branch.
        assert injury["osha_recordable"] is False

        submitted = transition_injury(injury["id"], "WC_SUBMITTED")
        claim = submitted["wc_claim_number"]
        transition_injury(injury["id"], "WC_DENIED")
        transition_injury(injury["id"], "APPEALED")
        accepted = transition_injury(injury["id"], "WC_ACCEPTED")

        assert accepted["status"] == "WC_ACCEPTED"
        assert accepted["wc_claim_number"] == claim
        assert accepted["osha_recordable"] is False


class TestClaimNumberSequence:
    def test_claim_numbers_follow_submission_order_not_filing_order(self, api):
        """PRD §3.8: "the literal prefix `WC-` followed by a six-digit,
        zero-padded sequence number counting submission transitions in their
        order of occurrence across the system, starting from one."

        Design: Corner/calculations/wc_claim_number_sequence
        """
        emp_a = register_employee("E-CL7A", full_name="Claim One")
        emp_b = register_employee("E-CL7B", full_name="Claim Two",
                                  job_category="TECH", department="LAB")
        inj_a = create_injury(emp_a["id"], injury_type="FALL",
                              injury_datetime="2026-07-10T09:00:00Z")
        inj_b = create_injury(emp_b["id"], injury_type="LIFT",
                              injury_datetime="2026-07-11T09:00:00Z")

        # inj_b was filed second but submitted first.
        sub_b = transition_injury(inj_b["id"], "WC_SUBMITTED")
        sub_a = transition_injury(inj_a["id"], "WC_SUBMITTED")
        assert sub_b["wc_claim_number"] == "WC-000001"
        assert sub_a["wc_claim_number"] == "WC-000002"


class TestOshaRecordableRecompute:
    def test_recordable_recomputed_on_pep_start(self, api, safety_headers,
                                                physician_headers):
        """PRD §3.8: "An injury is recordable when its `injury_type` is
        `NEEDLESTICK`; or when it is linked to an exposure case whose
        `risk_classification` is `HIGH`; or when it is linked to an exposure
        case that has a prophylaxis regimen in `STARTED` or `COMPLETED`. The
        determination is recomputed on linkage events — including a prophylaxis
        start or completion on the linked case — so a report's flag can change
        as the clinical picture develops."

        Design: Corner/calculations/osha_recordable_recompute_on_pep_start
        """
        emp = register_employee("E-CL5", full_name="Osha Rec", department="ED")
        # MUCOUS_MEMBRANE + BLOOD with unknown source -> MEDIUM (not HIGH).
        case = create_exposure_case(
            emp["id"], exposure_type="MUCOUS_MEMBRANE",
            exposure_datetime="2026-07-30T10:00:00Z",
            source_known=False, body_fluid="BLOOD",
        )
        assert case["risk_classification"] == "MEDIUM"

        injury = create_injury(emp["id"], injury_type="SPLASH",
                               injury_datetime="2026-07-30T10:00:00Z",
                               exposure_case_id=case["id"])
        assert injury["osha_recordable"] is False, (
            "SPLASH, MEDIUM case, no regimen started: not recordable at filing"
        )

        set_clock("2026-08-01T12:00:00Z")
        pep = get_case_pep(case["id"])
        start_pep(pep["id"], "2026-08-01T12:00:00Z")

        after = get_injury(injury["id"])
        assert after["osha_recordable"] is True, (
            "a prophylaxis start on the linked case recomputes the flag to true"
        )


class TestInjuryTemporalGate:
    def test_future_injury_datetime_rejected(self, api, safety_headers):
        """PRD §3.8: "the `injury_datetime`, which must not be after the
        current logical time (`ERR_COMPLETION_OUT_OF_RANGE`)."

        Design: Corner/validations/injury_future_datetime_rejected
        """
        emp = register_employee("E-V6", full_name="Fut Inj", job_category="TECH",
                                department="LAB")
        resp = api.create_injury_report(
            emp["id"],
            create_injury_payload(injury_type="FALL",
                                  injury_datetime="2026-09-01T00:00:00Z"),
            safety_headers,
        )
        validate_error(resp, ApiErrorId.ERR_COMPLETION_OUT_OF_RANGE)

        injuries = api.list_injury_reports(
            safety_headers, params={"employee_id": emp["id"]}
        )
        data, meta = validate_paginated(injuries)
        assert meta["total_count"] == 0 and data == []
