"""Certification depends on a field of the parent term, not on the report itself."""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories, fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_report_invalidated
from test_helpers.test_users import MANAGER_TWO, MANAGER_TWO_HEADERS


class TestCertificationIsGatedByTheTermPosture:
    """A flawless COMPILED report cannot be certified under a NON_COMPLIANT term."""

    @pytest.fixture
    def non_compliant_program(self):
        """Two BEHIND measures, and a 2026 report already compiled by mgr-01."""
        program = fx.setup_active_program()
        education_id = program["measures"]["PUBLIC_EDUCATION"]["id"]
        monitoring_id = program["measures"]["MONITORING"]["id"]
        fx.report_progress(education_id, 3)
        fx.report_progress(monitoring_id, 1)
        report = fx.setup_compiled_report(program["term_id"], "2026-01-01", "2026-12-31")
        return {
            "term_id": program["term_id"],
            "education_id": education_id,
            "monitoring_id": monitoring_id,
            "report": report,
        }

    def test_01_two_behind_measures_make_the_posture_non_compliant(
        self, non_compliant_program
    ):
        """25.00 percent on two measures is two BEHIND bands, not two gates.

        PRD: "If `behind_measure_count` is two or more, or if `behind_measure_count`
        is at least one while `exceeding_outfall_count` is also at least one,
        `compliance_posture` becomes `NON_COMPLIANT`."

        Design: Difficulty/cross_entity_state_dependency/report_certification_blocked_by_permit_term_posture
        """
        education = fx.read_measure(non_compliant_program["education_id"])
        monitoring = fx.read_measure(non_compliant_program["monitoring_id"])
        for measure, label in ((education, "public education"), (monitoring, "monitoring")):
            assert measure["attainment_pct"] == pytest.approx(25.00, abs=0.01), (
                f"the {label} measure sits at a quarter of its goal"
            )
            assert measure["goal_status"] == "BEHIND", (
                f"the {label} measure is below the 75.00 percent band"
            )

        term = fx.read_term(non_compliant_program["term_id"])
        assert term["behind_measure_count"] == 2, "two measures are behind"
        assert term["compliance_posture"] == "NON_COMPLIANT", (
            "two behind measures make the posture non compliant"
        )

    def test_02_certification_is_refused_although_the_report_is_flawless(
        self, non_compliant_program
    ):
        """The report is COMPILED and the certifier is not the compiler.

        PRD: "The certifying manager supplies the `certification_statement`, must
        not be the `compiled_by_user_id` that compiled the report — otherwise
        `ERR_SAME_USER_CERTIFICATION` — and may not certify at all while the term's
        `compliance_posture` is `NON_COMPLIANT`, which is refused with
        `ERR_POSTURE_NON_COMPLIANT`."

        Design: Difficulty/cross_entity_state_dependency/report_certification_blocked_by_permit_term_posture
        """
        report = non_compliant_program["report"]
        assert report["status"] == "COMPILED", "the report's own state is legal"
        assert report["compiled_by_user_id"] != MANAGER_TWO, (
            "the certifying manager is not the compiling manager"
        )

        response = api_client.certify_annual_report(
            report["id"], factories.certify_report_payload(), MANAGER_TWO_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_POSTURE_NON_COMPLIANT.value, 422)

    def test_03_the_refused_certification_writes_nothing(self, non_compliant_program):
        """The report stays COMPILED with its certification fields empty.

        PRD: "Certification stamps `certified_at` and records `certified_by_user_id`
        and the statement."

        Design: Difficulty/cross_entity_state_dependency/report_certification_blocked_by_permit_term_posture
        """
        api_client.certify_annual_report(
            non_compliant_program["report"]["id"],
            factories.certify_report_payload(),
            MANAGER_TWO_HEADERS,
        )

        report = fx.read_report(non_compliant_program["report"]["id"])
        assert report["status"] == "COMPILED", "the refused call left the status"
        assert report["certified_at"] is None, "nothing was stamped"
        assert report["certified_by_user_id"] is None, "no certifier was recorded"
        assert report["certification_statement"] is None, "no statement was stored"
        assert report["invalidation_count"] == 0, "no cascade ran"

    def test_04_repairing_a_measure_lifts_the_posture_and_reopens_the_report(
        self, non_compliant_program
    ):
        """The same cascade that clears the gate knocks the report back to DRAFT.

        PRD: "When one of these events changes either the term's
        `compliance_posture` or its `total_assessed_penalty_cents`, **and** the
        triggering event's own timestamp falls inside the closed reporting window of
        a report of that term whose `status` is `COMPILED` or `CERTIFIED`, that
        report is driven back to `DRAFT`."

        Design: Difficulty/cross_entity_state_dependency/report_certification_blocked_by_permit_term_posture
        """
        fx.report_progress(non_compliant_program["education_id"], 12)

        education = fx.read_measure(non_compliant_program["education_id"])
        assert education["attainment_pct"] == pytest.approx(100.00, abs=0.01), (
            "12 of 12 is full attainment"
        )
        assert education["goal_status"] == "MET", "the repaired measure is met"

        term = fx.read_term(non_compliant_program["term_id"])
        assert term["behind_measure_count"] == 1, "only monitoring remains behind"
        assert term["compliance_posture"] == "AT_RISK", (
            "one behind measure leaves the term at risk"
        )

        report = fx.read_report(non_compliant_program["report"]["id"])
        assert_report_invalidated(report, "POSTURE_CHANGED", 1)

    def test_05_certification_now_fails_on_the_report_state_instead(
        self, non_compliant_program
    ):
        """Lifting the posture exchanges one refusal for another.

        PRD: "Certification moves the report from `COMPILED` to `CERTIFIED` and is
        available only from `COMPILED`, otherwise `ERR_REPORT_NOT_COMPILED`."

        Design: Difficulty/cross_entity_state_dependency/report_certification_blocked_by_permit_term_posture
        """
        fx.report_progress(non_compliant_program["education_id"], 12)

        response = api_client.certify_annual_report(
            non_compliant_program["report"]["id"],
            factories.certify_report_payload(),
            MANAGER_TWO_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_REPORT_NOT_COMPILED.value, 409)

    def test_06_a_fresh_compile_against_the_newer_version_unblocks_certification(
        self, non_compliant_program
    ):
        """Recompiled under an AT_RISK posture, the report certifies.

        PRD: "Until then, any of the five invalidating events of §2.8 can push a
        `COMPILED` or `CERTIFIED` report back to `DRAFT`, incrementing
        `invalidation_count` and recording `invalidated_reason` as
        `POSTURE_CHANGED` or `PENALTY_LEDGER_CHANGED`, forcing a fresh compile
        against the term's newer `version` before the report can be certified and
        submitted again."

        Design: Difficulty/cross_entity_state_dependency/report_certification_blocked_by_permit_term_posture
        """
        fx.report_progress(non_compliant_program["education_id"], 12)

        recompiled = fx.compile_report(
            non_compliant_program["report"]["id"], non_compliant_program["term_id"]
        )
        assert recompiled["status"] == "COMPILED", "the fresh compile succeeds"
        assert recompiled["invalidation_count"] == 1, (
            "the earlier invalidation is still recorded"
        )

        certified = validate_success(
            api_client.certify_annual_report(
                non_compliant_program["report"]["id"],
                factories.certify_report_payload(),
                MANAGER_TWO_HEADERS,
            )
        )

        assert certified["status"] == "CERTIFIED", "an AT_RISK posture does not block"
        assert certified["certified_by_user_id"] == MANAGER_TWO, (
            "the second manager is recorded as the certifier"
        )
        assert certified["certified_at"] is not None, "certification stamps its instant"
