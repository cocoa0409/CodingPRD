"""Annual reporting from draft to submission, and the sample gate that precedes it."""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    MANAGER_HEADERS,
    MANAGER_ONE,
    MANAGER_TWO,
    MANAGER_TWO_HEADERS,
    OPERATIONS_HEADERS,
    OPERATIONS_ONE,
    OPERATIONS_TWO_HEADERS,
)

CERTIFICATION_STATEMENT = (
    "I certify under penalty of law that this report is true, accurate and complete."
)


def _certify(report_id, headers, statement=CERTIFICATION_STATEMENT):
    return api_client.certify_annual_report(
        report_id, factories.certify_report_payload(certification_statement=statement), headers
    )


def _submit(report_id):
    return api_client.submit_annual_report(report_id, MANAGER_TWO_HEADERS)


def _compile(report_id, expected_version):
    return api_client.compile_annual_report(
        report_id, factories.compile_report_payload(expected_version), MANAGER_HEADERS
    )


def _read_sample(outfall_id):
    """Read the single wet-weather sample back through the outfall's collection."""
    samples, _ = validate_paginated(
        api_client.list_outfall_observations(
            outfall_id, MANAGER_HEADERS, {"observation_type": "WET_WEATHER_SAMPLE"}
        )
    )
    return samples[0]


class TestReportTriggersEachGuardTheirOwnStatus:
    """Certify, submit and compile each name the status they came from."""

    @pytest.fixture
    def draft_report(self, active_program):
        """One DRAFT report covering the whole term of an activated program."""
        report = fx.create_report(active_program["term_id"], "2026-01-01", "2026-12-31")
        return {"term_id": active_program["term_id"], "report": report}

    def test_01_certifying_a_draft_report_names_the_compiled_status(self, draft_report):
        """Certification has one legal source status, and DRAFT is not it.

        PRD: "Certification moves the report from `COMPILED` to `CERTIFIED` and is
        available only from `COMPILED`, otherwise `ERR_REPORT_NOT_COMPILED`."

        Design: Corner/state_machines/report_lifecycle_triggers_each_guard_their_own_status
        """
        response = _certify(draft_report["report"]["id"], MANAGER_TWO_HEADERS, "Premature")

        validate_error(response, ApiErrorId.ERR_REPORT_NOT_COMPILED.value, 409)

        report = fx.read_report(draft_report["report"]["id"])
        assert report["status"] == "DRAFT", "the refused certification moved nothing"
        assert report["certified_at"] is None, "nothing was stamped"
        assert report["certification_statement"] is None, "no statement was stored"

    def test_02_submitting_a_draft_report_names_the_certified_status(self, draft_report):
        """Submission reaches past compilation and still names its own source.

        PRD: "Submission moves the report from `CERTIFIED` to `SUBMITTED` and is
        available only from `CERTIFIED`, otherwise `ERR_REPORT_NOT_CERTIFIED`."

        Design: Corner/state_machines/report_lifecycle_triggers_each_guard_their_own_status
        """
        response = _submit(draft_report["report"]["id"])

        validate_error(response, ApiErrorId.ERR_REPORT_NOT_CERTIFIED.value, 409)

        report = fx.read_report(draft_report["report"]["id"])
        assert report["status"] == "DRAFT", "the refused submission moved nothing"
        assert report["submitted_at"] is None, "nothing was stamped"

    def test_03_compilation_stamps_the_report_and_bumps_the_term(self, draft_report):
        """The one accepted trigger from DRAFT, and the version it leaves behind.

        PRD: "Compilation stamps `compiled_at` from the logical clock, records the
        acting manager as `compiled_by_user_id`, sets the term's `last_compiled_at` to
        the same instant, and increments the term's `version` by one — which is why a
        second compile must be prepared against the newer version."

        Design: Corner/state_machines/report_lifecycle_triggers_each_guard_their_own_status
        """
        term_id = draft_report["term_id"]
        version_before = fx.term_version(term_id)
        assert version_before == 2, (
            f"creation and activation leave the term at version 2, got {version_before}"
        )

        compiled = validate_success(
            _compile(draft_report["report"]["id"], version_before)
        )

        assert compiled["status"] == "COMPILED", "the report freezes"
        assert compiled["compiled_at"] == "2026-08-01T00:00:00Z", (
            "the compile instant is stamped from the logical clock"
        )
        assert compiled["compiled_by_user_id"] == MANAGER_ONE, "the compiler is recorded"

        term = fx.read_term(term_id)
        assert term["last_compiled_at"] == "2026-08-01T00:00:00Z", (
            "the term carries the same instant"
        )
        assert term["version"] == 3, (
            f"compilation increments the term's version to 3, got {term['version']}"
        )

    def test_04_submitting_a_compiled_report_still_names_the_certified_status(
        self, draft_report
    ):
        """One rung short of certification is still one rung short.

        PRD: "Submission moves the report from `CERTIFIED` to `SUBMITTED` and is
        available only from `CERTIFIED`, otherwise `ERR_REPORT_NOT_CERTIFIED`."

        Design: Corner/state_machines/report_lifecycle_triggers_each_guard_their_own_status
        """
        report_id = draft_report["report"]["id"]
        validate_success(_compile(report_id, fx.term_version(draft_report["term_id"])))

        response = _submit(report_id)

        validate_error(response, ApiErrorId.ERR_REPORT_NOT_CERTIFIED.value, 409)

        report = fx.read_report(report_id)
        assert report["status"] == "COMPILED", "the refused submission moved nothing"
        assert report["submitted_at"] is None, "nothing was stamped"

    def test_05_a_second_compile_against_the_fresh_version_reports_the_state(
        self, draft_report
    ):
        """The concurrency check clears first, so the state error is the one seen.

        PRD: "It is available only from `DRAFT`, otherwise `ERR_REPORT_NOT_DRAFT`; it
        requires the owning term to be `ACTIVE`; it requires `expected_permit_term_version`
        to match the term's current `version` as described in §2.6" And: "**Optimistic
        concurrency.** The version guards of §2.6 fire here, before any state or business
        rule, so that a stale writer is told it is stale rather than told its business
        intent is wrong."

        Design: Corner/state_machines/report_lifecycle_triggers_each_guard_their_own_status
        """
        term_id = draft_report["term_id"]
        report_id = draft_report["report"]["id"]
        validate_success(_compile(report_id, fx.term_version(term_id)))
        fresh_version = fx.term_version(term_id)
        assert fresh_version == 3, (
            f"the first compile advanced the term to version 3, got {fresh_version}"
        )

        response = _compile(report_id, fresh_version)

        validate_error(response, ApiErrorId.ERR_REPORT_NOT_DRAFT.value, 409)

        term = fx.read_term(term_id)
        assert term["version"] == 3, "the refused compile bumped nothing"

    def test_06_an_idle_program_freezes_a_zero_index_and_no_goals_met(self, draft_report):
        """Nothing was ever reported, so the weighted mean is zero.

        PRD: "Those contributions are summed, the `weight` values of the same measures
        are summed, and the index is the first sum divided by the second, rounded to 2
        decimal places exactly once at the end; rounding each measure's contribution
        before the division drifts from the specified value." And:
        "`measurable_goals_met_count` counts the term's `ACTIVE` control measures whose
        `goal_status` is `MET` at compile time."

        Design: Corner/state_machines/report_lifecycle_triggers_each_guard_their_own_status
        """
        compiled = validate_success(
            _compile(draft_report["report"]["id"], fx.term_version(draft_report["term_id"]))
        )

        assert compiled["compliance_index"] == pytest.approx(0.00, abs=0.01), (
            f"no measure reported progress, got {compiled['compliance_index']}"
        )
        assert compiled["measurable_goals_met_count"] == 0, (
            "every measure is still PENDING, so none is MET"
        )


class TestCertificationNeedsASecondOfficialAndAClosingWindow:
    """Segregation of duties, then the ninetieth day and the day after it."""

    @pytest.fixture
    def compiled_report(self, active_program):
        """A report compiled by the first manager over the 2026 calendar year."""
        report = fx.setup_compiled_report(
            active_program["term_id"], "2026-01-01", "2026-12-31"
        )
        return {"term_id": active_program["term_id"], "report": report}

    def test_07_the_compiler_may_not_certify_its_own_report(self, compiled_report):
        """The manager who froze the numbers cannot also attest to them.

        PRD: "The certifying manager supplies the `certification_statement`, must not be
        the `compiled_by_user_id` that compiled the report — otherwise
        `ERR_SAME_USER_CERTIFICATION` — and may not certify at all while the term's
        `compliance_posture` is `NON_COMPLIANT`, which is refused with
        `ERR_POSTURE_NON_COMPLIANT`."

        Design: Corner/state_machines/certification_requires_a_second_official_and_submission_closes_after_ninety_days
        """
        assert compiled_report["report"]["compiled_by_user_id"] == MANAGER_ONE, (
            "the first manager compiled the report"
        )

        response = _certify(
            compiled_report["report"]["id"],
            MANAGER_HEADERS,
            "I certify under penalty of law.",
        )

        validate_error(response, ApiErrorId.ERR_SAME_USER_CERTIFICATION.value, 409)

        report = fx.read_report(compiled_report["report"]["id"])
        assert report["status"] == "COMPILED", "the refused certification moved nothing"
        assert report["certified_at"] is None, "nothing was stamped"
        assert report["certified_by_user_id"] is None, "no certifier was recorded"

    def test_08_a_second_manager_certifies_and_the_statement_is_stored(
        self, compiled_report
    ):
        """A different official signs, and the words are kept as supplied.

        PRD: "Certification stamps `certified_at` and records `certified_by_user_id` and
        the statement."

        Design: Corner/state_machines/certification_requires_a_second_official_and_submission_closes_after_ninety_days
        """
        certified = validate_success(
            _certify(compiled_report["report"]["id"], MANAGER_TWO_HEADERS)
        )

        assert certified["status"] == "CERTIFIED", "the report is certified"
        assert certified["certified_by_user_id"] == MANAGER_TWO, (
            "the second manager is recorded as the certifier"
        )
        assert certified["certification_statement"] == CERTIFICATION_STATEMENT, (
            "the statement is stored verbatim"
        )
        assert certified["certified_at"] == "2026-08-01T00:00:00Z", (
            "the certification instant comes from the logical clock"
        )

    def test_09_submission_is_refused_the_day_after_the_window_closes(
        self, compiled_report
    ):
        """One day past ninety and the filing is too late.

        PRD: "It must happen no later than 90 days after `reporting_period_end`; past
        that the window has closed and the request is refused with
        `ERR_REPORT_SUBMISSION_WINDOW_CLOSED`."

        Design: Corner/state_machines/certification_requires_a_second_official_and_submission_closes_after_ninety_days
        """
        report_id = compiled_report["report"]["id"]
        validate_success(_certify(report_id, MANAGER_TWO_HEADERS))
        fx.set_clock("2027-04-01T00:00:00Z")

        response = _submit(report_id)

        validate_error(
            response, ApiErrorId.ERR_REPORT_SUBMISSION_WINDOW_CLOSED.value, 409
        )

        report = fx.read_report(report_id)
        assert report["status"] == "CERTIFIED", "the refused submission moved nothing"
        assert report["submitted_at"] is None, "nothing was stamped"

    def test_10_submission_on_the_ninetieth_day_is_accepted(self, compiled_report):
        """The last day of the window belongs to the window.

        PRD: "It must happen no later than 90 days after `reporting_period_end`; past
        that the window has closed and the request is refused with
        `ERR_REPORT_SUBMISSION_WINDOW_CLOSED`." And: "A reporting window is closed on
        both ends and covers whole days: it begins at 00:00:00Z on
        `reporting_period_start` and ends at 23:59:59Z on `reporting_period_end`."

        Design: Corner/state_machines/certification_requires_a_second_official_and_submission_closes_after_ninety_days
        """
        report_id = compiled_report["report"]["id"]
        validate_success(_certify(report_id, MANAGER_TWO_HEADERS))
        fx.set_clock("2027-03-31T23:59:59Z")

        submitted = validate_success(_submit(report_id))

        assert submitted["status"] == "SUBMITTED", "the ninetieth day is still inside"
        assert submitted["submitted_at"] == "2027-03-31T23:59:59Z", (
            "the submission instant comes from the logical clock"
        )

    def test_11_a_submitted_report_is_the_end_of_the_line(self, compiled_report):
        """Terminal means terminal, whichever trigger is tried.

        PRD: "`SUBMITTED` is terminal."

        Design: Corner/state_machines/certification_requires_a_second_official_and_submission_closes_after_ninety_days
        """
        report_id = compiled_report["report"]["id"]
        validate_success(_certify(report_id, MANAGER_TWO_HEADERS))
        fx.set_clock("2027-03-31T23:59:59Z")
        validate_success(_submit(report_id))

        validate_error(_submit(report_id), ApiErrorId.ERR_REPORT_NOT_CERTIFIED.value, 409)

        report = fx.read_report(report_id)
        assert report["status"] == "SUBMITTED", "the terminal status holds"
        assert report["submitted_at"] == "2027-03-31T23:59:59Z", (
            "the stored instant was not rewritten"
        )


class TestSampleAdjudicationGuardsTheStatusAndTheRecorder:
    """Two guards on one endpoint, and a screening that was never adjudicable."""

    @pytest.fixture
    def monitored_outfall(self):
        """OF-01 with one PENDING wet-weather sample and one dry-weather screening."""
        program = fx.setup_active_program(
            outfall_codes=("OF-01",),
            funding_target_cents=25000,
            outfall_overrides={
                "receiving_water": "Mill Creek",
                "drainage_area_acres": 45.00,
                "priority_tier": "HIGH",
                "baseline_concentration_mg_per_l": 0.45,
                "design_runoff_kl": 20000,
                "sweeping_capacity_lane_miles_per_month": 40.00,
            },
        )
        outfall = program["outfalls"]["OF-01"]
        sample = fx.record_sample(outfall["id"], "2026-07-20T09:00:00Z", 0.45, 40000.00)
        screening = fx.record_screening(
            outfall["id"], "2026-07-25T09:00:00Z", dry_weather_flow_present=False
        )
        return {"outfall": outfall, "sample": sample, "screening": screening}

    def test_12_the_recorder_may_not_adjudicate_the_sample_it_recorded(
        self, monitored_outfall
    ):
        """The supervisor who took the bottle cannot also sign it off.

        PRD: "The adjudicator must not be the `recorded_by_user_id` that recorded the
        observation, otherwise `ERR_SELF_VALIDATION_FORBIDDEN`."

        Design: Corner/state_machines/sample_validation_guards_both_the_pending_status_and_the_recorder
        """
        assert monitored_outfall["sample"]["recorded_by_user_id"] == OPERATIONS_ONE, (
            "the first supervisor recorded the sample"
        )

        response = api_client.validate_observation(
            monitored_outfall["sample"]["id"],
            factories.validate_observation_payload("VALIDATE"),
            OPERATIONS_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_SELF_VALIDATION_FORBIDDEN.value, 409)

        sample = _read_sample(monitored_outfall["outfall"]["id"])
        assert sample["validation_status"] == "PENDING", "the sample is still pending"
        assert sample["validated_at"] is None, "nothing was stamped"

    def test_13_a_second_supervisor_validates_without_touching_the_load(
        self, monitored_outfall
    ):
        """Adjudication decides admissibility, never the arithmetic.

        PRD: "`sample_load_lb` is the sample's `pollutant_concentration_mg_per_l`
        multiplied by its `runoff_volume_kl`, multiplied by the unit conversion factor
        0.00220462 pounds per milligram-per-litre-kilolitre, rounded to 4 decimal
        places." And: "Both decisions stamp `validated_at` from the logical clock:
        `VALIDATE` writes `VALIDATED` and admits the sample's `sample_load_lb` into both
        load variants, while `REJECT` writes `REJECTED`, excludes the load from every
        assessment, and thereby raises the count of samples the outfall is still
        projected to owe."

        Design: Corner/state_machines/sample_validation_guards_both_the_pending_status_and_the_recorder
        """
        assert monitored_outfall["sample"]["sample_load_lb"] == pytest.approx(
            39.6832, abs=0.00005
        ), "0.45 times 40000 times the conversion factor is 39.6832 pounds"

        validated = validate_success(
            api_client.validate_observation(
                monitored_outfall["sample"]["id"],
                factories.validate_observation_payload("VALIDATE"),
                OPERATIONS_TWO_HEADERS,
            )
        )

        assert validated["validation_status"] == "VALIDATED", "the sample is admitted"
        assert validated["validated_at"] == "2026-08-01T00:00:00Z", (
            "the decision instant comes from the logical clock"
        )
        assert validated["sample_load_lb"] == pytest.approx(39.6832, abs=0.00005), (
            f"the stored load is unchanged, got {validated['sample_load_lb']}"
        )

    def test_14_a_decided_sample_cannot_be_decided_again(self, monitored_outfall):
        """Even a manager with a different verdict arrives too late.

        PRD: "it applies only to a `WET_WEATHER_SAMPLE` whose `validation_status` is
        `PENDING`, and a dry-weather screening — permanently `NOT_APPLICABLE` — or an
        already-adjudicated sample is refused with `ERR_OBSERVATION_NOT_PENDING`."

        Design: Corner/state_machines/sample_validation_guards_both_the_pending_status_and_the_recorder
        """
        sample_id = monitored_outfall["sample"]["id"]
        validate_success(
            api_client.validate_observation(
                sample_id,
                factories.validate_observation_payload("VALIDATE"),
                OPERATIONS_TWO_HEADERS,
            )
        )

        response = api_client.validate_observation(
            sample_id, factories.validate_observation_payload("REJECT"), MANAGER_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_OBSERVATION_NOT_PENDING.value, 409)

        sample = _read_sample(monitored_outfall["outfall"]["id"])
        assert sample["validation_status"] == "VALIDATED", "the first verdict stands"

    def test_15_a_screening_was_never_adjudicable_in_the_first_place(
        self, monitored_outfall
    ):
        """A never-decided row and a twice-decided row share one error code.

        PRD: "Screenings are stored with `validation_status` `NOT_APPLICABLE` and a null
        `sample_load_lb`; samples are stored with a null `screening_result`, as described
        in §3.7."

        Design: Corner/state_machines/sample_validation_guards_both_the_pending_status_and_the_recorder
        """
        screening = monitored_outfall["screening"]
        assert screening["validation_status"] == "NOT_APPLICABLE", (
            "a screening is born outside the adjudication machine"
        )
        assert screening["sample_load_lb"] is None, "a screening carries no load"

        response = api_client.validate_observation(
            screening["id"],
            factories.validate_observation_payload("VALIDATE"),
            MANAGER_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_OBSERVATION_NOT_PENDING.value, 409)

        screenings, _ = validate_paginated(
            api_client.list_outfall_observations(
                monitored_outfall["outfall"]["id"],
                MANAGER_HEADERS,
                {"observation_type": "DRY_WEATHER_SCREENING"},
            )
        )
        assert screenings[0]["validation_status"] == "NOT_APPLICABLE", (
            "the refused decision changed nothing"
        )
        assert screenings[0]["validated_at"] is None, "nothing was stamped"
