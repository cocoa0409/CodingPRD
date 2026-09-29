"""The permit term machine and the two child inventories it retires."""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import SIX_MEASURE_CODES, STANDARD_MEASURE_SET
from test_helpers.test_users import (
    IDDE_HEADERS,
    MANAGER_HEADERS,
    OPERATIONS_HEADERS,
)


def _register(term_id, codes):
    """Register the named minimum control measures under a term."""
    measures = {}
    for code in codes:
        measures[code] = validate_success(
            api_client.create_control_measure(
                factories.control_measure_payload(
                    term_id, code, **dict(STANDARD_MEASURE_SET[code])
                ),
                MANAGER_HEADERS,
            ),
            201,
        )
    return measures


class TestNewRowsStartInTheirDeclaredStates:
    """Every dimension of every machine opens where the narrative says."""

    @pytest.fixture
    def one_of_each(self):
        """A DRAFT term with one measure, one outfall, one site, one control, one report."""
        term = fx.create_permit_term(funding_target_cents=25000)
        measure = _register(term["id"], ["PUBLIC_EDUCATION"])["PUBLIC_EDUCATION"]
        outfall = fx.create_outfall(
            term["id"],
            "OF-01",
            receiving_water="Mill Creek",
            drainage_area_acres=45.00,
            priority_tier="HIGH",
            baseline_concentration_mg_per_l=0.45,
            design_runoff_kl=20000,
            sweeping_capacity_lane_miles_per_month=40.00,
        )
        site = fx.create_site(
            term["id"],
            site_name="SITE-A",
            operator_name="Northgate Civil",
            disturbed_acres=2.50,
        )
        facility = fx.create_facility(
            site["id"],
            "PRIVATE",
            facility_type="WET_POND",
            design_capacity_cf=6000.00,
            service_area_acres=2.50,
        )
        report = fx.create_report(term["id"], "2026-01-01", "2026-12-31")
        return {
            "term": term,
            "measure": measure,
            "outfall": outfall,
            "site": site,
            "facility": facility,
            "report": report,
        }

    def test_01_the_term_measure_and_outfall_open_on_their_first_state(self, one_of_each):
        """One machine per row, and the outfall runs three dimensions at once.

        PRD: "A new measure starts with `status` `ACTIVE`, `goal_status` `PENDING`,
        `measurable_goal_actual` and `attainment_pct` at 0.00, `open_case_count`,
        `enforcement_count` and `swept_lane_miles_ytd` at their zero values, and
        `last_progress_reported_at` null." And: "A new outfall has `status` `ACTIVE`,
        `screening_status` `NOT_SCREENED`, `tmdl_status` `NOT_ASSESSED`, an empty
        `sweeping_runs` list, `swept_lane_miles_ytd` at 0.00, `screening_count` and
        `open_case_count` at 0, `last_screened_at` and `last_assessed_year` null, and
        `last_assessed_gross_load_lb`, `last_assessed_credit_lb` and
        `last_assessed_net_load_lb` at 0.00."

        Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
        """
        term = fx.read_term(one_of_each["term"]["id"])
        assert term["status"] == "DRAFT", "a term opens in DRAFT"

        measure = fx.read_measure(one_of_each["measure"]["id"])
        assert measure["status"] == "ACTIVE", "a measure opens ACTIVE"
        assert measure["goal_status"] == "PENDING", "its goal dimension opens PENDING"
        assert measure["attainment_pct"] == pytest.approx(0.00, abs=0.01), (
            "no progress has been reported"
        )
        assert measure["last_progress_reported_at"] is None, "nothing was reported"

        outfall = fx.read_outfall(one_of_each["outfall"]["id"])
        assert outfall["status"] == "ACTIVE", "an outfall opens ACTIVE"
        assert outfall["screening_status"] == "NOT_SCREENED", "it has not been screened"
        assert outfall["tmdl_status"] == "NOT_ASSESSED", "it has not been assessed"
        assert outfall["sweeping_runs"] == [], "no run has been appended"

    def test_02_the_site_facility_and_report_open_on_their_first_state(self, one_of_each):
        """The site's two dimensions start independently of one another.

        PRD: "`plan_status` tracks erosion and sediment control plan review through
        `SUBMITTED`, `ESC_REVIEW`, `RETURNED` and `APPROVED`, starting at `SUBMITTED`;
        it is cyclic through `RETURNED`. `field_status` tracks the physical condition
        of the site through `PRE_CONSTRUCTION`, `ACTIVE_DISTURBANCE`, `STOP_WORK` and
        `CLOSED`, starting at `PRE_CONSTRUCTION`, with `CLOSED` terminal." And: "a
        `PRIVATE` facility is created with `agreement_status` `PENDING` because a
        privately owned control must carry a recorded maintenance agreement. In both
        cases `credit_eligible` starts false, `inspection_interval_months`,
        `agreement_reference`, `agreement_recorded_at` and
        `last_inspection_finalized_at` start null, and `months_since_last_inspection`
        starts at 0." And: "A new report has `status` `DRAFT`, every statistic at its
        zero value, `invalidation_count` at 0, and `compiled_at`,
        `compiled_by_user_id`, `certified_at`, `certified_by_user_id`,
        `certification_statement`, `submitted_at` and `invalidated_reason` all null."

        Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
        """
        site = fx.read_site(one_of_each["site"]["id"])
        assert site["plan_status"] == "SUBMITTED", "plan review opens at SUBMITTED"
        assert site["field_status"] == "PRE_CONSTRUCTION", (
            "the field dimension opens before construction"
        )

        facility = fx.read_facility(one_of_each["facility"]["id"])
        assert facility["agreement_status"] == "PENDING", (
            "a privately owned control opens on the agreement track"
        )
        assert facility["credit_eligible"] is False, "eligibility is not granted at birth"

        report = fx.read_report(one_of_each["report"]["id"])
        assert report["status"] == "DRAFT", "a report opens in DRAFT"
        assert report["invalidation_count"] == 0, "nothing has invalidated it"
        assert report["compiled_at"] is None, "nothing has been compiled"


class TestActivationRequiresTheWholeMeasureSet:
    """Five measures is a shortfall; six is a gate that opens exactly once."""

    @pytest.fixture
    def five_measure_term(self):
        """A DRAFT term missing only the monitoring measure."""
        term = fx.create_permit_term(funding_target_cents=25000)
        measures = _register(term["id"], SIX_MEASURE_CODES[:-1])
        return {"term": term, "measures": measures}

    def test_03_a_shortfall_of_one_measure_refuses_activation(self, five_measure_term):
        """Five of six is an incomplete set, and the term does not move.

        PRD: "Moving a term from `DRAFT` to `ACTIVE` requires that all six
        `measure_code` values exist as control measures of that term with `status`
        `ACTIVE`, and, when `tmdl_applicable` is true, that at least one outfall of the
        term has `status` `ACTIVE`. Either shortfall is refused with
        `ERR_MEASURE_SET_INCOMPLETE`; an attempt to activate a term that is not in
        `DRAFT` is `ERR_PERMIT_TERM_NOT_ACTIVE`."

        Design: Corner/state_machines/activation_requires_the_whole_measure_set_and_is_not_repeatable
        """
        response = api_client.activate_permit_term(
            five_measure_term["term"]["id"], MANAGER_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_MEASURE_SET_INCOMPLETE.value, 422)

        term = fx.read_term(five_measure_term["term"]["id"])
        assert term["status"] == "DRAFT", "the refused activation left the term in DRAFT"
        assert term["version"] == 1, "a refused activation bumps no version"
        assert term["activated_at"] is None, "nothing was stamped"

    def test_04_registering_the_sixth_measure_opens_the_gate(self, five_measure_term):
        """The identical call succeeds once the set is complete.

        PRD: "A successful activation stamps `activated_at` from the logical clock,
        recomputes `compliance_posture`, `behind_measure_count` and
        `exceeding_outfall_count`, and increments the term's `version` by one."

        Design: Corner/state_machines/activation_requires_the_whole_measure_set_and_is_not_repeatable
        """
        _register(five_measure_term["term"]["id"], ["MONITORING"])

        activated = validate_success(
            api_client.activate_permit_term(
                five_measure_term["term"]["id"], MANAGER_HEADERS
            )
        )

        assert activated["status"] == "ACTIVE", "the complete set activates the term"
        assert activated["activated_at"] is not None, "activation stamps its instant"
        assert activated["version"] == 2, "activation is one mutation of the row"
        assert activated["compliance_posture"] == "COMPLIANT", (
            "six pending measures are not behind"
        )
        assert activated["behind_measure_count"] == 0, "no measure is behind"

    def test_05_activation_is_not_repeatable(self, five_measure_term):
        """A second activation has no legal source state.

        PRD: "an attempt to activate a term that is not in `DRAFT` is
        `ERR_PERMIT_TERM_NOT_ACTIVE`."

        Design: Corner/state_machines/activation_requires_the_whole_measure_set_and_is_not_repeatable
        """
        term_id = five_measure_term["term"]["id"]
        _register(term_id, ["MONITORING"])
        validate_success(api_client.activate_permit_term(term_id, MANAGER_HEADERS))

        response = api_client.activate_permit_term(term_id, MANAGER_HEADERS)

        validate_error(response, ApiErrorId.ERR_PERMIT_TERM_NOT_ACTIVE.value, 409)

        term = fx.read_term(term_id)
        assert term["version"] == 2, "the refused second activation bumped no version"
        assert term["status"] == "ACTIVE", "the term is still the activated row"

    def test_06_an_active_term_will_not_let_go_of_a_measure(self, five_measure_term):
        """The set must stay complete for as long as the term is ACTIVE.

        PRD: "A single control measure can also be retired on its own, but only once
        its owning term is no longer `ACTIVE`, because an `ACTIVE` term must carry all
        six minimum control measures at all times; retiring while the term is still
        `ACTIVE`, or acting on a measure that is already `RETIRED`, is refused with
        `ERR_MEASURE_RETIRED`."

        Design: Corner/state_machines/activation_requires_the_whole_measure_set_and_is_not_repeatable
        """
        term_id = five_measure_term["term"]["id"]
        monitoring = _register(term_id, ["MONITORING"])["MONITORING"]
        validate_success(api_client.activate_permit_term(term_id, MANAGER_HEADERS))

        response = api_client.retire_control_measure(monitoring["id"], MANAGER_HEADERS)

        validate_error(response, ApiErrorId.ERR_MEASURE_RETIRED.value, 409)

        measure = fx.read_measure(monitoring["id"])
        assert measure["status"] == "ACTIVE", "the refused retirement left the measure"


class TestTmdlTermsAlsoNeedAnOutfall:
    """The second activation clause is conditional on the allocation flag."""

    @pytest.fixture
    def tmdl_term_without_outfalls(self):
        """A phosphorus-allocation term with all six measures and an empty inventory."""
        term = fx.create_tmdl_permit_term(permit_number="MS4-2026-TMDL")
        measures = _register(term["id"], SIX_MEASURE_CODES)
        return {"term": term, "measures": measures}

    def test_07_a_complete_measure_set_is_not_enough_under_an_allocation(
        self, tmdl_term_without_outfalls
    ):
        """All six measures exist and activation is still refused.

        PRD: "Moving a term from `DRAFT` to `ACTIVE` requires that all six
        `measure_code` values exist as control measures of that term with `status`
        `ACTIVE`, and, when `tmdl_applicable` is true, that at least one outfall of the
        term has `status` `ACTIVE`."

        Design: Corner/state_machines/tmdl_terms_additionally_require_an_active_outfall_before_activation
        """
        assert tmdl_term_without_outfalls["term"]["tmdl_applicable"] is True, (
            "the term declares a waste load allocation"
        )
        _, meta = validate_paginated(
            api_client.list_term_outfalls(
                tmdl_term_without_outfalls["term"]["id"], MANAGER_HEADERS
            )
        )
        assert meta["total_count"] == 0, "the outfall inventory is empty"

        response = api_client.activate_permit_term(
            tmdl_term_without_outfalls["term"]["id"], MANAGER_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_MEASURE_SET_INCOMPLETE.value, 422)

    def test_08_one_active_outfall_satisfies_the_second_clause(
        self, tmdl_term_without_outfalls
    ):
        """Inventorying an outfall opens the gate without assessing anything.

        PRD: "A new outfall has `status` `ACTIVE`, `screening_status` `NOT_SCREENED`,
        `tmdl_status` `NOT_ASSESSED`, an empty `sweeping_runs` list,
        `swept_lane_miles_ytd` at 0.00, `screening_count` and `open_case_count` at 0,
        `last_screened_at` and `last_assessed_year` null, and
        `last_assessed_gross_load_lb`, `last_assessed_credit_lb` and
        `last_assessed_net_load_lb` at 0.00."

        Design: Corner/state_machines/tmdl_terms_additionally_require_an_active_outfall_before_activation
        """
        term_id = tmdl_term_without_outfalls["term"]["id"]
        outfall = fx.create_outfall(
            term_id,
            "OF-01",
            receiving_water="Mill Creek",
            drainage_area_acres=45.00,
            priority_tier="HIGH",
            baseline_concentration_mg_per_l=0.45,
            design_runoff_kl=20000,
        )

        activated = validate_success(
            api_client.activate_permit_term(term_id, MANAGER_HEADERS)
        )

        assert activated["status"] == "ACTIVE", "the allocation term activates"
        assert activated["version"] == 2, "activation is one mutation of the row"

        stored = fx.read_outfall(outfall["id"])
        assert stored["tmdl_status"] == "NOT_ASSESSED", (
            "activation performs no load assessment"
        )


class TestExpiryWaitsForTheEndAndTheLastOpenReport:
    """Two independent guards, then a cascade over both child inventories."""

    @pytest.fixture
    def program_with_open_report(self):
        """An ACTIVE 2026 term with one DRAFT report over the whole permit year."""
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
        report = fx.create_report(program["term_id"], "2026-01-01", "2026-12-31")
        return {
            "term_id": program["term_id"],
            "outfall": program["outfalls"]["OF-01"],
            "report": report,
        }

    @pytest.fixture
    def program_without_report(self):
        """The same ACTIVE 2026 term with no annual report open against it.

        The open-reports guard of §2.5 level 13 outranks the term-end guard of
        level 16, so the term-end rule can only be observed on a term that does
        not also carry an open report.
        """
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
        return {
            "term_id": program["term_id"],
            "outfall": program["outfalls"]["OF-01"],
        }

    def _close_the_report(self, context):
        fx.compile_report(context["report"]["id"], context["term_id"])
        fx.certify_report(context["report"]["id"])
        return validate_success(
            api_client.submit_annual_report(context["report"]["id"], MANAGER_HEADERS)
        )

    def test_09_expiry_is_refused_before_the_term_end(self, program_without_report):
        """August is not the end of a term that runs to December.

        PRD: "The reverse transition, `ACTIVE → EXPIRED`, is available to the same
        manager once the logical clock has reached or passed `term_end_date`; before
        that instant it is refused with `ERR_TERM_END_NOT_REACHED`."

        Design: Corner/state_machines/expiry_waits_for_the_term_end_and_the_last_open_report_then_retires_the_inventory
        """
        response = api_client.expire_permit_term(
            program_without_report["term_id"], MANAGER_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_TERM_END_NOT_REACHED.value, 409)

        term = fx.read_term(program_without_report["term_id"])
        assert term["status"] == "ACTIVE", "the refused expiry left the term ACTIVE"
        assert term["expired_at"] is None, "nothing was stamped"

    def test_10_an_open_report_blocks_expiry_after_the_term_end(
        self, program_with_open_report
    ):
        """The clock has passed the end and the dependent report still answers.

        PRD: "Expiry also requires that no annual report of the term is still in
        `DRAFT`, `COMPILED` or `CERTIFIED`; if one is, the request is refused with
        `ERR_OPEN_REPORTS_EXIST`."

        Design: Corner/state_machines/expiry_waits_for_the_term_end_and_the_last_open_report_then_retires_the_inventory
        """
        fx.set_clock("2027-01-02T00:00:00Z")

        response = api_client.expire_permit_term(
            program_with_open_report["term_id"], MANAGER_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_OPEN_REPORTS_EXIST.value, 409)

        report = fx.read_report(program_with_open_report["report"]["id"])
        assert report["status"] == "DRAFT", "the blocking report is still open"

    def test_11_a_submitted_report_releases_expiry_and_the_inventory_retires(
        self, program_with_open_report
    ):
        """Expiry cascades RETIRED onto all six measures and the outfall.

        PRD: "Expiry stamps `expired_at`, retires every control measure of the term
        still in `ACTIVE` and every outfall of the term still in `ACTIVE` — each
        retirement writes `RETIRED` into the child's `status`, leaves the measure's
        `goal_status` dimension untouched, and increments the child's `version` by one
        — and increments the term's own `version` by one."

        Design: Corner/state_machines/expiry_waits_for_the_term_end_and_the_last_open_report_then_retires_the_inventory
        """
        fx.set_clock("2027-01-02T00:00:00Z")
        submitted = self._close_the_report(program_with_open_report)
        assert submitted["status"] == "SUBMITTED", "the report reached its terminal state"

        expired = validate_success(
            api_client.expire_permit_term(
                program_with_open_report["term_id"], MANAGER_HEADERS
            )
        )
        assert expired["status"] == "EXPIRED", "the term expires once nothing is open"
        assert expired["expired_at"] == "2027-01-02T00:00:00Z", (
            "expiry stamps the logical clock instant"
        )

        _, meta = validate_paginated(
            api_client.list_term_control_measures(
                program_with_open_report["term_id"], MANAGER_HEADERS, {"status": "RETIRED"}
            )
        )
        assert meta["total_count"] == 6, (
            f"the cascade retires all six measures, got {meta['total_count']}"
        )

        outfall = fx.read_outfall(program_with_open_report["outfall"]["id"])
        assert outfall["status"] == "RETIRED", "the cascade retires the outfall too"
        assert outfall["version"] > program_with_open_report["outfall"]["version"], (
            "the retired child's version advanced"
        )

    def test_12_expired_is_terminal_and_activation_cannot_resurrect_it(
        self, program_with_open_report
    ):
        """There is no path out of EXPIRED.

        PRD: "`EXPIRED` is terminal."

        Design: Corner/state_machines/expiry_waits_for_the_term_end_and_the_last_open_report_then_retires_the_inventory
        """
        fx.set_clock("2027-01-02T00:00:00Z")
        self._close_the_report(program_with_open_report)
        validate_success(
            api_client.expire_permit_term(
                program_with_open_report["term_id"], MANAGER_HEADERS
            )
        )

        response = api_client.activate_permit_term(
            program_with_open_report["term_id"], MANAGER_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_PERMIT_TERM_NOT_ACTIVE.value, 409)

        term = fx.read_term(program_with_open_report["term_id"])
        assert term["status"] == "EXPIRED", "the refused activation changed nothing"


class TestRetiredMeasuresAreADeadEnd:
    """Retirement is legal in DRAFT, and then the row answers nothing.

    """

    @pytest.fixture
    def draft_measure_set(self):
        """A DRAFT term with all six measures, none retired."""
        term = fx.create_permit_term(funding_target_cents=25000)
        measures = _register(term["id"], SIX_MEASURE_CODES)
        return {"term": term, "measures": measures}

    def test_13_retirement_under_a_draft_term_leaves_the_posture_census_alone(
        self, draft_measure_set
    ):
        """A retired row is out of the census, not counted as behind.

        PRD: "Retirement removes the row from `behind_measure_count`, from the annual
        `measurable_goals_met_count` and from the compliance index, recomputes the
        term's `behind_measure_count` and `compliance_posture`, and increments the
        measure's `version` by one."

        Design: Corner/state_machines/retired_measures_reject_progress_and_break_activation
        """
        education = draft_measure_set["measures"]["PUBLIC_EDUCATION"]

        retired = validate_success(
            api_client.retire_control_measure(education["id"], MANAGER_HEADERS)
        )

        assert retired["status"] == "RETIRED", "a DRAFT term releases its measure"

        term = fx.read_term(draft_measure_set["term"]["id"])
        assert term["behind_measure_count"] == 0, (
            "a retired row is outside the posture census"
        )
        assert term["compliance_posture"] == "COMPLIANT", "the posture did not move"

    def test_14_a_retired_measure_rejects_progress_and_a_second_retirement(
        self, draft_measure_set
    ):
        """Neither reporting nor retiring again has any effect.

        PRD: "Reporting progress on a `RETIRED` measure is likewise
        `ERR_MEASURE_RETIRED`, and any operation naming a measure that does not exist
        is `ERR_CONTROL_MEASURE_NOT_FOUND`."

        Design: Corner/state_machines/retired_measures_reject_progress_and_break_activation
        """
        education = draft_measure_set["measures"]["PUBLIC_EDUCATION"]
        validate_success(
            api_client.retire_control_measure(education["id"], MANAGER_HEADERS)
        )

        progress = api_client.report_measure_progress(
            education["id"], factories.report_progress_payload(9), MANAGER_HEADERS
        )
        validate_error(progress, ApiErrorId.ERR_MEASURE_RETIRED.value, 409)

        again = api_client.retire_control_measure(education["id"], MANAGER_HEADERS)
        validate_error(again, ApiErrorId.ERR_MEASURE_RETIRED.value, 409)

        measure = fx.read_measure(education["id"])
        assert measure["measurable_goal_actual"] == pytest.approx(0.00, abs=0.01), (
            "the refused progress report wrote nothing"
        )
        assert measure["last_progress_reported_at"] is None, "nothing was stamped"

    def test_15_a_retired_measure_no_longer_satisfies_the_activation_precondition(
        self, draft_measure_set
    ):
        """Six rows exist, but only five of them are ACTIVE.

        PRD: "Moving a term from `DRAFT` to `ACTIVE` requires that all six
        `measure_code` values exist as control measures of that term with `status`
        `ACTIVE`, and, when `tmdl_applicable` is true, that at least one outfall of the
        term has `status` `ACTIVE`. Either shortfall is refused with
        `ERR_MEASURE_SET_INCOMPLETE`; an attempt to activate a term that is not in
        `DRAFT` is `ERR_PERMIT_TERM_NOT_ACTIVE`."

        Design: Corner/state_machines/retired_measures_reject_progress_and_break_activation
        """
        validate_success(
            api_client.retire_control_measure(
                draft_measure_set["measures"]["PUBLIC_EDUCATION"]["id"], MANAGER_HEADERS
            )
        )

        response = api_client.activate_permit_term(
            draft_measure_set["term"]["id"], MANAGER_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_MEASURE_SET_INCOMPLETE.value, 422)

        term = fx.read_term(draft_measure_set["term"]["id"])
        assert term["status"] == "DRAFT", "the term never activated"


class TestRetiredOutfallsRejectEveryFieldOperation:
    """The field surface closes; the history stays readable."""

    @pytest.fixture
    def screened_outfall(self):
        """An ACTIVE term whose OF-01 has one CLEAR screening and no cases."""
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
        fx.record_screening(
            outfall["id"],
            "2026-07-01T08:00:00Z",
            dry_weather_flow_present=False,
            indicator_bacteria_mpn=None,
            indicator_surfactant_mg_per_l=None,
            indicator_ammonia_mg_per_l=None,
        )
        return {"term_id": program["term_id"], "outfall": outfall}

    def test_16_retirement_succeeds_when_no_case_is_open(self, screened_outfall):
        """A clear screening history is no obstacle to retirement.

        PRD: "Retiring an outfall is reserved to the manager and requires
        `open_case_count` to be exactly 0; otherwise the request is refused with
        `ERR_OUTFALL_HAS_OPEN_CASES`."

        Design: Corner/state_machines/retired_outfalls_reject_every_field_operation
        """
        before = fx.read_outfall(screened_outfall["outfall"]["id"])
        assert before["open_case_count"] == 0, "the clear screening opened no case"

        retired = validate_success(
            api_client.retire_outfall(screened_outfall["outfall"]["id"], MANAGER_HEADERS)
        )

        assert retired["status"] == "RETIRED", "the outfall retires"
        assert retired["version"] > before["version"], "retirement is one mutation"

    @pytest.mark.parametrize(
        "operation",
        ["observation", "sweeping_run", "second_retire"],
    )
    def test_17_every_field_operation_is_refused_afterwards(
        self, screened_outfall, operation
    ):
        """Observations, sweeping runs and a repeat retirement all close.

        PRD: "A retired outfall accepts nothing further: recording an observation,
        appending a sweeping run, running a load assessment or retiring again all yield
        `ERR_OUTFALL_RETIRED`."

        Design: Corner/state_machines/retired_outfalls_reject_every_field_operation
        """
        outfall_id = screened_outfall["outfall"]["id"]
        validate_success(api_client.retire_outfall(outfall_id, MANAGER_HEADERS))

        calls = {
            "observation": lambda: api_client.create_observation(
                outfall_id,
                factories.screening_payload(
                    "2026-08-20T08:00:00Z",
                    dry_weather_flow_present=False,
                    indicator_bacteria_mpn=None,
                    indicator_surfactant_mg_per_l=None,
                    indicator_ammonia_mg_per_l=None,
                ),
                IDDE_HEADERS,
            ),
            "sweeping_run": lambda: api_client.create_sweeping_run(
                outfall_id,
                factories.sweeping_run_payload("2026-08-01", "2026-08-10", 5.00),
                OPERATIONS_HEADERS,
            ),
            "second_retire": lambda: api_client.retire_outfall(
                outfall_id, MANAGER_HEADERS
            ),
        }

        validate_error(calls[operation](), ApiErrorId.ERR_OUTFALL_RETIRED.value, 409)

    def test_18_the_history_survives_and_the_term_recounts(self, screened_outfall):
        """Retirement recomputes the term census without rewriting the past.

        PRD: "Retirement writes `RETIRED` into `status`, which removes the row from
        annual screening-coverage denominators and from the annual net load total,
        recomputes the term's `exceeding_outfall_count` and `compliance_posture`, and
        increments the outfall's `version` by one."

        Design: Corner/state_machines/retired_outfalls_reject_every_field_operation
        """
        outfall_id = screened_outfall["outfall"]["id"]
        validate_success(api_client.retire_outfall(outfall_id, MANAGER_HEADERS))
        api_client.create_sweeping_run(
            outfall_id,
            factories.sweeping_run_payload("2026-08-01", "2026-08-10", 5.00),
            OPERATIONS_HEADERS,
        )

        outfall = fx.read_outfall(outfall_id)
        assert outfall["screening_count"] == 1, "the one screening survives retirement"
        assert outfall["sweeping_runs"] == [], "the refused run appended nothing"
        assert outfall["swept_lane_miles_ytd"] == pytest.approx(0.00, abs=0.01), (
            "no lane miles were credited"
        )

        term = fx.read_term(screened_outfall["term_id"])
        assert term["exceeding_outfall_count"] == 0, "no outfall exceeds its allocation"
        assert term["compliance_posture"] == "COMPLIANT", "the recount leaves it clean"
