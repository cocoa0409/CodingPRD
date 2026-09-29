"""The cyclic case machine: which triggers exist, how often, and what blocks them."""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories, fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import IDDE_HEADERS, OFFICER_HEADERS


def _trace(case_id, method="DYE_TEST"):
    return api_client.start_tracing(
        case_id, factories.start_tracing_payload(method), IDDE_HEADERS
    )


def _identify(case_id, description):
    return api_client.identify_source(
        case_id,
        factories.identify_source_payload(
            source_description=description, responsible_party="Ridge Laundry"
        ),
        IDDE_HEADERS,
    )


def _reopen(case_id, reason):
    return api_client.reopen_tracing(
        case_id, factories.reopen_tracing_payload(reason=reason), IDDE_HEADERS
    )


def _resolve(case_id, note):
    return api_client.resolve_case(
        case_id, factories.resolve_case_payload(resolution_note=note), IDDE_HEADERS
    )


@pytest.fixture
def suspect_outfall():
    """An ACTIVE term whose OF-01 carries one suspect screening and its OPEN case."""
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
    _, case = fx.open_case_by_screening(outfall["id"], "2026-08-01T08:00:00Z")
    return {"term_id": program["term_id"], "outfall": outfall, "case": case}


class TestTransitionsAbsentFromTheMachine:
    """Only the arrows the machine draws may be walked."""

    @pytest.mark.parametrize(
        "trigger",
        ["identify_source", "resolve", "reopen_tracing"],
    )
    def test_01_an_open_case_offers_only_tracing(self, suspect_outfall, trigger):
        """Identify-source, resolve and reopen all lack an arrow out of OPEN.

        PRD: "Case work belongs entirely to the `IDDEInvestigator`, and the case
        machine is cyclic: `OPEN → TRACING → SOURCE_IDENTIFIED`, from where it may
        either advance to `ENFORCEMENT` or fall back to `TRACING`, and from either of
        those two it may finish at `RESOLVED`. Any transition requested from a state
        that does not offer it is refused with `ERR_CASE_INVALID_STATE`, and an unknown
        case identifier is `ERR_CASE_NOT_FOUND`."

        Design: Corner/state_machines/case_transitions_absent_from_the_machine_are_rejected_from_every_state
        """
        case_id = suspect_outfall["case"]["id"]
        calls = {
            "identify_source": lambda: _identify(case_id, "Cross connection"),
            "resolve": lambda: _resolve(case_id, "Nothing found"),
            "reopen_tracing": lambda: _reopen(case_id, "Premature"),
        }

        validate_error(calls[trigger](), ApiErrorId.ERR_CASE_INVALID_STATE.value, 409)

        case = fx.read_case(case_id)
        assert case["status"] == "OPEN", "the refused trigger left the case OPEN"
        assert case["tracing_attempt_count"] == 0, "no tracing attempt was recorded"

    def test_02_tracing_is_accepted_once_and_refused_the_second_time(
        self, suspect_outfall
    ):
        """The arrow out of OPEN is consumed by the first tracing attempt.

        PRD: "Tracing begins on an `OPEN` case while the owning permit term is
        `ACTIVE`, with the investigator supplying the `trace_method` used — one of
        `DYE_TEST`, `SMOKE_TEST`, `CCTV` or `UPSTREAM_SAMPLING`. The transition records
        that method on the case and increments `tracing_attempt_count` by one."

        Design: Corner/state_machines/case_transitions_absent_from_the_machine_are_rejected_from_every_state
        """
        case_id = suspect_outfall["case"]["id"]

        traced = validate_success(_trace(case_id, "DYE_TEST"))
        assert traced["status"] == "TRACING", "the case advances to TRACING"
        assert traced["trace_method"] == "DYE_TEST", "the method is recorded"
        assert traced["tracing_attempt_count"] == 1, "one attempt was counted"

        validate_error(
            _trace(case_id, "SMOKE_TEST"), ApiErrorId.ERR_CASE_INVALID_STATE.value, 409
        )

        case = fx.read_case(case_id)
        assert case["trace_method"] == "DYE_TEST", (
            "the rejected transition did not overwrite the method"
        )
        assert case["tracing_attempt_count"] == 1, (
            "the rejected transition counted no attempt"
        )

    def test_03_a_tracing_case_cannot_be_reopened(self, suspect_outfall):
        """Reopening is a fallback from further down the machine, not from TRACING.

        PRD: "Reopening is available from `SOURCE_IDENTIFIED` and from `ENFORCEMENT`,
        in both cases carrying a `reason`, and in both cases requires `reopen_count` to
        be below three; at three it is refused with `ERR_REOPEN_LIMIT_REACHED`."

        Design: Corner/state_machines/case_transitions_absent_from_the_machine_are_rejected_from_every_state
        """
        case_id = suspect_outfall["case"]["id"]
        validate_success(_trace(case_id))

        validate_error(
            _reopen(case_id, "Premature"), ApiErrorId.ERR_CASE_INVALID_STATE.value, 409
        )

        case = fx.read_case(case_id)
        assert case["status"] == "TRACING", "the case is still tracing"
        assert case["reopen_count"] == 0, "no reopen cycle was counted"

    def test_04_resolved_is_terminal_and_offers_nothing(self, suspect_outfall):
        """The walk finishes, and then every trigger is refused.

        PRD: "A resolution stamps `resolved_at` from the logical clock, records the
        note, decrements the outfall's `open_case_count`, and — when that leaves the
        outfall's `open_case_count` at 0 — reverts the outfall's `screening_status` from
        `SUSPECT` back to `CLEAR`." And: "`RESOLVED` is terminal."

        Design: Corner/state_machines/case_transitions_absent_from_the_machine_are_rejected_from_every_state
        """
        case_id = suspect_outfall["case"]["id"]
        validate_success(_trace(case_id))
        validate_success(_identify(case_id, "Cross connection at 14 Ridge Rd"))
        resolved = validate_success(
            _resolve(case_id, "Connection severed and inspected")
        )
        assert resolved["status"] == "RESOLVED", "the case finishes at RESOLVED"
        assert resolved["resolved_at"] is not None, "resolution stamps its instant"
        assert resolved["reopen_count"] == 0, "the walk used no reopen cycle"

        outfall = fx.read_outfall(suspect_outfall["outfall"]["id"])
        assert outfall["open_case_count"] == 0, "the resolved case leaves the census"
        assert outfall["screening_status"] == "CLEAR", "the emptied census reverts"

        validate_error(
            _trace(case_id, "CCTV"), ApiErrorId.ERR_CASE_INVALID_STATE.value, 409
        )

        case = fx.read_case(case_id)
        assert case["status"] == "RESOLVED", "the terminal state is unchanged"
        assert case["tracing_attempt_count"] == 1, "no further attempt was counted"


class TestReopeningStopsAfterThreeCycles:
    """The ceiling sits on the stored cycle count, not on the tracing attempts."""

    @pytest.fixture
    def identified_case(self, suspect_outfall):
        """The case parked at SOURCE_IDENTIFIED after one tracing attempt."""
        case_id = suspect_outfall["case"]["id"]
        validate_success(_trace(case_id))
        validate_success(_identify(case_id, "Suspected floor drain"))
        return {**suspect_outfall, "case_id": case_id}

    def _cycle(self, case_id, reason, description):
        validate_success(_reopen(case_id, reason))
        return validate_success(_identify(case_id, description))

    def test_05_a_reopen_clears_the_identified_source_and_counts_two_counters(
        self, identified_case
    ):
        """One cycle empties both narrative fields and raises both counters.

        PRD: "A successful reopen clears both `source_description` and
        `responsible_party` back to null and increments both `reopen_count` and
        `tracing_attempt_count` by one."

        Design: Corner/state_machines/reopen_tracing_stops_after_three_cycles
        """
        reopened = validate_success(
            _reopen(identified_case["case_id"], "Dye did not reappear")
        )

        assert reopened["status"] == "TRACING", "the case falls back to TRACING"
        assert reopened["source_description"] is None, "the narrative was cleared"
        assert reopened["responsible_party"] is None, "the accountable party was cleared"
        assert reopened["reopen_count"] == 1, "one cycle was counted"
        assert reopened["tracing_attempt_count"] == 2, "a second attempt was counted"

    def test_06_the_third_cycle_is_accepted_at_the_ceiling(self, identified_case):
        """reopen_count reaches exactly three while the attempts reach four.

        PRD: "in both cases requires `reopen_count` to be below three; at three it is
        refused with `ERR_REOPEN_LIMIT_REACHED`."

        Design: Corner/state_machines/reopen_tracing_stops_after_three_cycles
        """
        case_id = identified_case["case_id"]
        self._cycle(case_id, "Dye did not reappear", "Second candidate")
        self._cycle(case_id, "Party disputes the finding", "Third candidate")

        third = validate_success(_reopen(case_id, "Smoke test inconclusive"))

        assert third["status"] == "TRACING", "the third cycle is accepted"
        assert third["reopen_count"] == 3, "the stored cycle count reaches three"
        assert third["tracing_attempt_count"] == 4, (
            "the attempts stand one ahead of the cycles"
        )

    def test_07_the_fourth_cycle_is_refused_and_clears_nothing(self, identified_case):
        """At three the ceiling holds even though a fourth attempt looks plausible.

        PRD: "in both cases requires `reopen_count` to be below three; at three it is
        refused with `ERR_REOPEN_LIMIT_REACHED`."

        Design: Corner/state_machines/reopen_tracing_stops_after_three_cycles
        """
        case_id = identified_case["case_id"]
        self._cycle(case_id, "Dye did not reappear", "Second candidate")
        self._cycle(case_id, "Party disputes the finding", "Third candidate")
        self._cycle(case_id, "Smoke test inconclusive", "Fourth candidate")

        validate_error(
            _reopen(case_id, "One more look"),
            ApiErrorId.ERR_REOPEN_LIMIT_REACHED.value,
            422,
        )

        case = fx.read_case(case_id)
        assert case["status"] == "SOURCE_IDENTIFIED", "the refused reopen did not move it"
        assert case["reopen_count"] == 3, "the cycle count is untouched"
        assert case["tracing_attempt_count"] == 4, "no further attempt was counted"
        assert case["source_description"] == "Fourth candidate", (
            "the refused reopen cleared nothing"
        )
        assert case["responsible_party"] == "Ridge Laundry", (
            "the accountable party is still recorded"
        )

    def test_08_the_case_never_leaves_the_open_census_while_cycling(
        self, identified_case
    ):
        """Three cycles and a refusal keep the outfall suspect throughout.

        PRD: "A `SUSPECT` result moves `screening_status` from either `NOT_SCREENED` or
        `CLEAR` to `SUSPECT` and additionally opens a case: the server creates an
        **illicit discharge case** in `OPEN` whose `outfall_id` is this outfall and
        whose `origin_observation_id` is the new observation, stamps the case's
        `opened_at` from the logical clock, raises the outfall's `open_case_count` by
        one, then recomputes the `ILLICIT_DISCHARGE` control measure's
        `open_case_count` and `goal_status`, the term's posture, and — where the posture
        moved and the observation falls inside a closed reporting window — the annual
        report's return to `DRAFT`."

        Design: Corner/state_machines/reopen_tracing_stops_after_three_cycles
        """
        case_id = identified_case["case_id"]
        self._cycle(case_id, "Dye did not reappear", "Second candidate")
        self._cycle(case_id, "Party disputes the finding", "Third candidate")
        self._cycle(case_id, "Smoke test inconclusive", "Fourth candidate")
        _reopen(case_id, "One more look")

        outfall = fx.read_outfall(identified_case["outfall"]["id"])
        assert outfall["open_case_count"] == 1, (
            "the case never left the non-terminal set"
        )
        assert outfall["screening_status"] == "SUSPECT", "the outfall is still suspect"


class TestQuietStatesAreBlockedByALiveAction:
    """Resolution and reopening both wait on the enforcement ledger."""

    @pytest.fixture
    def case_in_enforcement(self, suspect_outfall):
        """The case driven to ENFORCEMENT by one ISSUED notice of violation."""
        case_id = suspect_outfall["case"]["id"]
        validate_success(_trace(case_id))
        validate_success(_identify(case_id, "Suspected floor drain"))
        action = validate_success(
            api_client.create_enforcement_action(
                factories.enforcement_action_payload(
                    "NOTICE_OF_VIOLATION",
                    violation_days=0,
                    illicit_discharge_case_id=case_id,
                ),
                OFFICER_HEADERS,
            ),
            201,
        )
        return {**suspect_outfall, "case_id": case_id, "action": action}

    def test_09_issuance_moves_the_case_and_prices_the_first_rung(
        self, case_in_enforcement
    ):
        """The case reaches ENFORCEMENT without asking, at an unmultiplied base.

        PRD: "A case subject moves from `SOURCE_IDENTIFIED` to `ENFORCEMENT` and has
        its `enforcement_action_count` raised." And: "`penalty_cents` is then the ladder
        base for the action's current `action_type` — 25000 cents for
        `NOTICE_OF_VIOLATION`, 50000 cents for `ADMINISTRATIVE_ORDER`, 100000 cents for
        `CIVIL_PENALTY` — plus 2000 cents for each of the `billable_violation_days`,
        with that sum multiplied by `escalation_multiplier` and the product rounded to
        whole cents."

        Design: Corner/state_machines/case_quiet_states_are_blocked_while_an_enforcement_action_is_live
        """
        case = fx.read_case(case_in_enforcement["case_id"])
        assert case["status"] == "ENFORCEMENT", "issuance drove the case forward"
        assert case["enforcement_action_count"] == 1, "one action counts against it"

        action = case_in_enforcement["action"]
        assert action["status"] == "ISSUED", "a new action opens at ISSUED"
        assert action["prior_assessed_total_cents"] == 0, "no earlier action exists"
        assert action["escalation_multiplier"] == pytest.approx(1.00, abs=0.01), (
            "a zero prior total leaves the multiplier at one"
        )
        assert action["penalty_cents"] == 25000, (
            f"the notice base stands alone, got {action['penalty_cents']}"
        )

    @pytest.mark.parametrize("trigger", ["resolve", "reopen_tracing"])
    def test_10_both_quiet_transitions_are_refused_while_the_action_is_live(
        self, case_in_enforcement, trigger
    ):
        """One ISSUED action blocks the exit and the fallback alike.

        PRD: "Reopening from `ENFORCEMENT` additionally requires that no enforcement
        action on the case is still in `ISSUED` or `ESCALATED`, and is otherwise refused
        with `ERR_CASE_HAS_OPEN_ENFORCEMENT`." And: "From `ENFORCEMENT`, resolution
        requires that every enforcement action on the case has reached `CLOSED` or
        `RESCINDED`; from `SOURCE_IDENTIFIED`, it requires that no action on the case is
        in `ISSUED` or `ESCALATED`. Either shortfall is refused with
        `ERR_CASE_HAS_OPEN_ENFORCEMENT`."

        Design: Corner/state_machines/case_quiet_states_are_blocked_while_an_enforcement_action_is_live
        """
        case_id = case_in_enforcement["case_id"]
        calls = {
            "resolve": lambda: _resolve(case_id, "Owner promised to fix"),
            "reopen_tracing": lambda: _reopen(case_id, "Wrong party named"),
        }

        validate_error(
            calls[trigger](), ApiErrorId.ERR_CASE_HAS_OPEN_ENFORCEMENT.value, 409
        )

        case = fx.read_case(case_id)
        assert case["status"] == "ENFORCEMENT", "the refused trigger did not move it"
        assert case["reopen_count"] == 0, "no cycle was counted"
        assert case["resolved_at"] is None, "nothing was stamped"

    def test_11_closing_the_action_unblocks_resolution_without_refunding(
        self, case_in_enforcement
    ):
        """A closed action leaves its money standing and the case free to finish.

        PRD: "Closing an action documents compliance without forgiving the money. From
        `ISSUED` or `ESCALATED`, and carrying a `compliance_note`, it writes `CLOSED`
        into `status`, stamps `closed_at`, records the note, leaves `penalty_cents`
        standing in the term's ledger, and lowers the subject site's
        `open_enforcement_count` where the subject is a site."

        Design: Corner/state_machines/case_quiet_states_are_blocked_while_an_enforcement_action_is_live
        """
        closed = validate_success(
            api_client.close_enforcement_action(
                case_in_enforcement["action"]["id"],
                factories.close_enforcement_payload(
                    compliance_note="Connection severed and re-plumbed"
                ),
                OFFICER_HEADERS,
            )
        )
        assert closed["status"] == "CLOSED", "the action closes"
        assert closed["penalty_cents"] == 25000, "closure forgives nothing"

        resolved = validate_success(
            _resolve(case_in_enforcement["case_id"], "Source removed and verified")
        )
        assert resolved["status"] == "RESOLVED", "the quiet state is now reachable"

        outfall = fx.read_outfall(case_in_enforcement["outfall"]["id"])
        assert outfall["open_case_count"] == 0, "the census empties"
        assert outfall["screening_status"] == "CLEAR", "the screening dimension reverts"

        term = fx.read_term(case_in_enforcement["term_id"])
        assert term["total_assessed_penalty_cents"] == 25000, (
            f"the ledger keeps the closed penalty, got "
            f"{term['total_assessed_penalty_cents']}"
        )
