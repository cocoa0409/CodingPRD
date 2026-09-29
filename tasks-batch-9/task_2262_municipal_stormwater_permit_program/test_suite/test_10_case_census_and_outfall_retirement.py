"""The open-case census: what a resolution gives back, and what it unblocks."""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories, fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import IDDE_HEADERS, MANAGER_HEADERS


def _resolve(case_id, note):
    return validate_success(
        api_client.resolve_case(
            case_id, factories.resolve_case_payload(resolution_note=note), IDDE_HEADERS
        )
    )


class TestOpenCaseCensusIsRebuiltOnEveryResolution:
    """Each resolution decrements exactly one outfall and nothing else."""

    @pytest.fixture
    def two_resolvable_cases(self):
        """OF-01 and OF-02 each carrying one case at SOURCE_IDENTIFIED."""
        program = fx.setup_active_program(
            outfall_codes=("OF-01",),
            outfall_overrides={
                "receiving_water": "Mill Creek",
                "drainage_area_acres": 45.00,
                "priority_tier": "HIGH",
                "baseline_concentration_mg_per_l": 0.45,
                "design_runoff_kl": 20000,
                "sweeping_capacity_lane_miles_per_month": 40.00,
            },
        )
        outfall_two = fx.create_outfall(
            program["term_id"],
            "OF-02",
            receiving_water="Bell Slough",
            drainage_area_acres=22.00,
            priority_tier="MEDIUM",
            baseline_concentration_mg_per_l=0.30,
            design_runoff_kl=12000,
        )
        measure_id = program["measures"]["ILLICIT_DISCHARGE"]["id"]
        fx.report_progress(measure_id, 20)
        first_case = fx.setup_case_in_state(
            program["outfalls"]["OF-01"]["id"], "SOURCE_IDENTIFIED", "2026-08-01T08:00:00Z"
        )
        second_case = fx.setup_case_in_state(
            outfall_two["id"], "SOURCE_IDENTIFIED", "2026-08-01T09:00:00Z"
        )
        return {
            "term_id": program["term_id"],
            "measure_id": measure_id,
            "outfall_one": program["outfalls"]["OF-01"],
            "outfall_two": outfall_two,
            "first_case": first_case,
            "second_case": second_case,
        }

    def test_01_the_census_starts_as_the_number_of_live_cases(self, two_resolvable_cases):
        """Two live cases show as one per outfall and two on the measure.

        PRD: "A `SUSPECT` result moves `screening_status` from either
        `NOT_SCREENED` or `CLEAR` to `SUSPECT` and additionally opens a case: the
        server creates an **illicit discharge case** in `OPEN` whose `outfall_id` is
        this outfall and whose `origin_observation_id` is the new observation,
        stamps the case's `opened_at` from the logical clock, raises the outfall's
        `open_case_count` by one, then recomputes the `ILLICIT_DISCHARGE` control
        measure's `open_case_count` and `goal_status`, the term's posture, and —
        where the posture moved and the observation falls inside a closed reporting
        window — the annual report's return to `DRAFT`."

        Design: Difficulty/compensating_invariant/open_case_census_is_rebuilt_from_live_cases_on_every_resolution
        """
        first = fx.read_outfall(two_resolvable_cases["outfall_one"]["id"])
        second = fx.read_outfall(two_resolvable_cases["outfall_two"]["id"])
        assert first["open_case_count"] == 1, "one live case at the first outfall"
        assert second["open_case_count"] == 1, "one live case at the second outfall"
        assert first["screening_status"] == "SUSPECT", "the first outfall is suspect"
        assert second["screening_status"] == "SUSPECT", "the second outfall is suspect"

        measure = fx.read_measure(two_resolvable_cases["measure_id"])
        assert measure["open_case_count"] == 2, (
            "the measure census equals the sum over outfalls"
        )
        assert measure["attainment_pct"] == pytest.approx(100.00, abs=0.01), (
            "20 of 20 reported is full attainment"
        )
        assert measure["goal_status"] == "MET", "two open cases do not trip the gate"

        term = fx.read_term(two_resolvable_cases["term_id"])
        assert term["behind_measure_count"] == 0, "no measure is behind"
        assert term["compliance_posture"] == "COMPLIANT", "the term is compliant"

    def test_02_the_first_resolution_is_scoped_to_its_own_outfall(
        self, two_resolvable_cases
    ):
        """One resolution empties one outfall and leaves the other suspect.

        PRD: "A resolution stamps `resolved_at` from the logical clock, records the
        note, decrements the outfall's `open_case_count`, and — when that leaves the
        outfall's `open_case_count` at 0 — reverts the outfall's `screening_status`
        from `SUSPECT` back to `CLEAR`."

        Design: Difficulty/compensating_invariant/open_case_census_is_rebuilt_from_live_cases_on_every_resolution
        """
        resolved = _resolve(
            two_resolvable_cases["first_case"]["id"], "Cross-connection severed and capped"
        )

        assert resolved["status"] == "RESOLVED", "resolution writes RESOLVED"
        assert resolved["resolved_at"] is not None, "resolution stamps resolved_at"

        first = fx.read_outfall(two_resolvable_cases["outfall_one"]["id"])
        assert first["open_case_count"] == 0, "the resolved case leaves the census"
        assert first["screening_status"] == "CLEAR", (
            "an emptied census reverts the screening dimension"
        )

        second = fx.read_outfall(two_resolvable_cases["outfall_two"]["id"])
        assert second["open_case_count"] == 1, "the other outfall keeps its own case"
        assert second["screening_status"] == "SUSPECT", (
            "the compensation is scoped to one outfall"
        )

        measure = fx.read_measure(two_resolvable_cases["measure_id"])
        assert measure["open_case_count"] == 1, (
            "the measure census still equals the sum over outfalls"
        )

    def test_03_the_second_resolution_empties_every_census(self, two_resolvable_cases):
        """With no live case left, every count reads zero.

        PRD: "It then recomputes the `ILLICIT_DISCHARGE` control measure's
        `open_case_count` and `goal_status`, which is where a cleared gate can lift
        that measure out of `BEHIND`, and recomputes the term's
        `compliance_posture`."

        Design: Difficulty/compensating_invariant/open_case_census_is_rebuilt_from_live_cases_on_every_resolution
        """
        _resolve(
            two_resolvable_cases["first_case"]["id"], "Cross-connection severed and capped"
        )
        _resolve(
            two_resolvable_cases["second_case"]["id"],
            "Lateral joint replaced and pressure tested",
        )

        for key in ("outfall_one", "outfall_two"):
            outfall = fx.read_outfall(two_resolvable_cases[key]["id"])
            assert outfall["open_case_count"] == 0, f"{key} carries no live case"
            assert outfall["screening_status"] == "CLEAR", f"{key} is clear again"

        measure = fx.read_measure(two_resolvable_cases["measure_id"])
        assert measure["open_case_count"] == 0, "the measure census is empty"
        assert measure["goal_status"] == "MET", (
            "the measure keeps the band its attainment earns"
        )

        term = fx.read_term(two_resolvable_cases["term_id"])
        assert term["behind_measure_count"] == 0, "no measure is behind"
        assert term["compliance_posture"] == "COMPLIANT", (
            "the census never crossed the gate, so the posture never moved"
        )

    def test_04_the_screening_history_is_not_part_of_the_census(
        self, two_resolvable_cases
    ):
        """Resolutions never touch `screening_count` or `last_screened_at`.

        PRD: "Every dry-weather screening stamps the outfall's `last_screened_at`
        with the observation's `observed_at` and increments `screening_count` by
        one."

        Design: Difficulty/compensating_invariant/open_case_census_is_rebuilt_from_live_cases_on_every_resolution
        """
        _resolve(
            two_resolvable_cases["first_case"]["id"], "Cross-connection severed and capped"
        )
        _resolve(
            two_resolvable_cases["second_case"]["id"],
            "Lateral joint replaced and pressure tested",
        )

        first = fx.read_outfall(two_resolvable_cases["outfall_one"]["id"])
        assert first["screening_count"] == 1, "the one screening is still counted"
        assert first["last_screened_at"] == "2026-08-01T08:00:00Z", (
            "the visit instant survives the resolution"
        )


class TestOutfallRetirementWaitsOnItsCases:
    """Retirement reads a census of other rows, not a field of its own parent."""

    @pytest.fixture
    def outfall_with_open_case(self):
        """OF-01 with one OPEN case cascaded from a suspect screening."""
        program = fx.setup_active_program(
            outfall_codes=("OF-01",),
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
        _, case = fx.open_case_by_screening(outfall["id"], "2026-08-01T08:00:00Z")
        return {
            "term_id": program["term_id"],
            "measure_id": program["measures"]["ILLICIT_DISCHARGE"]["id"],
            "outfall": outfall,
            "case": case,
        }

    def _clear_the_case(self, case_id):
        validate_success(
            api_client.start_tracing(
                case_id, factories.start_tracing_payload("DYE_TEST"), IDDE_HEADERS
            )
        )
        validate_success(
            api_client.identify_source(
                case_id,
                factories.identify_source_payload(
                    source_description="Wash bay drain tied to the storm lateral",
                    responsible_party="Mill Road Autocare",
                ),
                IDDE_HEADERS,
            )
        )
        return _resolve(case_id, "Cross-connection severed and capped")

    def test_05_retirement_is_refused_while_one_case_is_live(
        self, outfall_with_open_case
    ):
        """A single non-terminal case blocks an otherwise legal retirement.

        PRD: "Retiring an outfall is reserved to the manager and requires
        `open_case_count` to be exactly 0; otherwise the request is refused with
        `ERR_OUTFALL_HAS_OPEN_CASES`."

        Design: Difficulty/cross_entity_state_dependency/outfall_retirement_blocked_by_open_illicit_discharge_case
        """
        response = api_client.retire_outfall(
            outfall_with_open_case["outfall"]["id"], MANAGER_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_OUTFALL_HAS_OPEN_CASES.value, 409)

        outfall = fx.read_outfall(outfall_with_open_case["outfall"]["id"])
        assert outfall["status"] == "ACTIVE", "the refused retirement left the status"
        assert outfall["open_case_count"] == 1, "the blocking case is still live"

    def test_06_resolving_the_case_unblocks_the_identical_retirement(
        self, outfall_with_open_case
    ):
        """Once the census empties, the same call retires the outfall.

        PRD: "Retirement writes `RETIRED` into `status`, which removes the row from
        annual screening-coverage denominators and from the annual net load total,
        recomputes the term's `exceeding_outfall_count` and `compliance_posture`,
        and increments the outfall's `version` by one."

        Design: Difficulty/cross_entity_state_dependency/outfall_retirement_blocked_by_open_illicit_discharge_case
        """
        api_client.retire_outfall(
            outfall_with_open_case["outfall"]["id"], MANAGER_HEADERS
        )

        resolved = self._clear_the_case(outfall_with_open_case["case"]["id"])
        assert resolved["status"] == "RESOLVED", "the case reached its terminal state"

        cleared = fx.read_outfall(outfall_with_open_case["outfall"]["id"])
        assert cleared["open_case_count"] == 0, "the census is empty"
        assert cleared["screening_status"] == "CLEAR", "the screening dimension reverted"

        retired = validate_success(
            api_client.retire_outfall(
                outfall_with_open_case["outfall"]["id"], MANAGER_HEADERS
            )
        )
        assert retired["status"] == "RETIRED", "the unblocked retirement succeeds"

    def test_07_retirement_leaves_the_screening_dimension_where_it_was(
        self, outfall_with_open_case
    ):
        """The screening history and the case census are independent of `status`.

        PRD: "A new outfall has `status` `ACTIVE`, `screening_status`
        `NOT_SCREENED`, `tmdl_status` `NOT_ASSESSED`, an empty `sweeping_runs` list,
        `swept_lane_miles_ytd` at 0.00, `screening_count` and `open_case_count` at
        0, `last_screened_at` and `last_assessed_year` null, and
        `last_assessed_gross_load_lb`, `last_assessed_credit_lb` and
        `last_assessed_net_load_lb` at 0.00."

        Design: Difficulty/cross_entity_state_dependency/outfall_retirement_blocked_by_open_illicit_discharge_case
        """
        self._clear_the_case(outfall_with_open_case["case"]["id"])
        validate_success(
            api_client.retire_outfall(
                outfall_with_open_case["outfall"]["id"], MANAGER_HEADERS
            )
        )

        outfall = fx.read_outfall(outfall_with_open_case["outfall"]["id"])
        assert outfall["status"] == "RETIRED", "the outfall is retired"
        assert outfall["screening_count"] == 1, "its one screening survives retirement"
        assert outfall["last_screened_at"] == "2026-08-01T08:00:00Z", (
            "the visit instant survives retirement"
        )
        assert outfall["screening_status"] == "CLEAR", (
            "the screening dimension is untouched by the inventory dimension"
        )

    def test_08_the_measure_and_the_posture_settle_after_the_resolution(
        self, outfall_with_open_case
    ):
        """No gate was ever tripped, so the posture stayed compliant throughout.

        PRD: "If `last_progress_reported_at` is null and `measurable_goal_actual` is
        0, the result is `PENDING`."

        Design: Difficulty/cross_entity_state_dependency/outfall_retirement_blocked_by_open_illicit_discharge_case
        """
        self._clear_the_case(outfall_with_open_case["case"]["id"])

        measure = fx.read_measure(outfall_with_open_case["measure_id"])
        assert measure["open_case_count"] == 0, "the resolved case leaves the census"
        assert measure["goal_status"] == "PENDING", (
            "no progress was ever reported on the measure"
        )

        term = fx.read_term(outfall_with_open_case["term_id"])
        assert term["behind_measure_count"] == 0, "no measure is behind"
        assert term["compliance_posture"] == "COMPLIANT", (
            "one case never crossed the gate of more than three"
        )
