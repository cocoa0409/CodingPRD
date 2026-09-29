"""Walking the ladder: one rung per escalation, and the door rescission closes."""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories, fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import OFFICER_HEADERS


def _escalate(action_id, violation_days):
    return api_client.escalate_enforcement_action(
        action_id,
        factories.escalate_payload(violation_days=violation_days),
        OFFICER_HEADERS,
    )


def _issue(site_id, violation_days):
    return validate_success(
        api_client.create_enforcement_action(
            factories.enforcement_action_payload(
                "NOTICE_OF_VIOLATION",
                violation_days=violation_days,
                construction_site_id=site_id,
            ),
            OFFICER_HEADERS,
        ),
        201,
    )


class TestEscalationWalksOneRungAtATime:
    """Two rungs up through a self-loop, then a ceiling that is not a state error."""

    @pytest.fixture
    def noticed_site(self, active_program):
        """SITE-K approved with one ISSUED notice of violation at the initial clock."""
        site = fx.setup_site_with_approved_plan(
            active_program["term_id"],
            esc_plan_reference="ESC-K",
            site_name="SITE-K",
            operator_name="Northgate Civil",
            disturbed_acres=1.50,
        )
        action = _issue(site["id"], 0)
        return {"term_id": active_program["term_id"], "site": site, "action": action}

    def test_01_the_first_escalation_advances_the_type_and_reprices_the_action(
        self, noticed_site
    ):
        """Fourteen days on, the notice becomes an administrative order.

        PRD: "Escalation walks the ladder upward and is a self-loop once reached:
        `ISSUED → ESCALATED`, then `ESCALATED → ESCALATED` for each further rung. Each
        escalation advances `action_type` one step — `NOTICE_OF_VIOLATION` to
        `ADMINISTRATIVE_ORDER`, `ADMINISTRATIVE_ORDER` to `CIVIL_PENALTY` — so an action
        already at `CIVIL_PENALTY` has nowhere to go and is refused with
        `ERR_LADDER_EXHAUSTED`."

        Design: Corner/state_machines/escalation_walks_the_ladder_once_per_rung_and_stops_at_civil_penalty
        """
        fx.set_clock("2026-08-15T00:00:00Z")

        escalated = validate_success(_escalate(noticed_site["action"]["id"], 0))

        assert escalated["status"] == "ESCALATED", "the action leaves ISSUED"
        assert escalated["action_type"] == "ADMINISTRATIVE_ORDER", "one rung up"
        assert escalated["penalty_cents"] == 50000, (
            f"the order base replaces the notice base, got {escalated['penalty_cents']}"
        )
        assert escalated["escalation_count"] == 1, "one escalation was counted"
        assert escalated["last_escalated_at"] == "2026-08-15T00:00:00Z", (
            "the escalation instant is stamped from the logical clock"
        )

    def test_02_the_second_escalation_is_a_self_loop_to_the_top_rung(self, noticed_site):
        """ESCALATED to ESCALATED, with the type advancing all the same.

        PRD: "A successful escalation recomputes `prior_assessed_total_cents`,
        `escalation_multiplier` and `penalty_cents`, adjusts the term's
        `total_assessed_penalty_cents` by the difference between the new penalty and the
        old one, increments `escalation_count` by one and stamps `last_escalated_at` from
        the logical clock."

        Design: Corner/state_machines/escalation_walks_the_ladder_once_per_rung_and_stops_at_civil_penalty
        """
        action_id = noticed_site["action"]["id"]
        fx.set_clock("2026-08-15T00:00:00Z")
        validate_success(_escalate(action_id, 0))
        fx.set_clock("2026-08-29T00:00:00Z")

        top = validate_success(_escalate(action_id, 0))

        assert top["status"] == "ESCALATED", "the self-loop keeps the same status"
        assert top["action_type"] == "CIVIL_PENALTY", "the top rung is reached"
        assert top["penalty_cents"] == 100000, (
            f"the civil penalty base replaces the order base, got {top['penalty_cents']}"
        )
        assert top["escalation_count"] == 2, "both escalations were counted"
        assert top["last_escalated_at"] == "2026-08-29T00:00:00Z", (
            "the later instant replaces the earlier one"
        )

    def test_03_the_ledger_is_delta_adjusted_rather_than_accumulated(self, noticed_site):
        """The three rungs cost 100000 cents in total, not 175000.

        PRD: "Second, `prior_assessed_total_cents` is the sum of `penalty_cents` over
        the *other* enforcement actions on the same subject whose `status` is `ISSUED`,
        `ESCALATED` or `CLOSED`, excluding this action's own row and frozen before this
        row's own penalty is written. Excluding the row itself is the whole point: on
        escalation an action's previous penalty must not feed its own new multiplier, or
        every escalation would compound against itself."

        Design: Corner/state_machines/escalation_walks_the_ladder_once_per_rung_and_stops_at_civil_penalty
        """
        action_id = noticed_site["action"]["id"]
        fx.set_clock("2026-08-15T00:00:00Z")
        validate_success(_escalate(action_id, 0))
        fx.set_clock("2026-08-29T00:00:00Z")
        top = validate_success(_escalate(action_id, 0))

        assert top["prior_assessed_total_cents"] == 0, (
            "the row excludes itself and no other action exists on the site"
        )
        assert top["escalation_multiplier"] == pytest.approx(1.00, abs=0.01), (
            "a zero prior total never compounds"
        )

        term = fx.read_term(noticed_site["term_id"])
        assert term["total_assessed_penalty_cents"] == 100000, (
            "the ledger holds the current penalty of the one action, got "
            f"{term['total_assessed_penalty_cents']}"
        )

    def test_04_the_top_rung_refuses_a_further_escalation(self, noticed_site):
        """There is nowhere above CIVIL_PENALTY to go.

        PRD: "so an action already at `CIVIL_PENALTY` has nowhere to go and is refused
        with `ERR_LADDER_EXHAUSTED`."

        Design: Corner/state_machines/escalation_walks_the_ladder_once_per_rung_and_stops_at_civil_penalty
        """
        action_id = noticed_site["action"]["id"]
        fx.set_clock("2026-08-15T00:00:00Z")
        validate_success(_escalate(action_id, 0))
        fx.set_clock("2026-08-29T00:00:00Z")
        validate_success(_escalate(action_id, 0))
        fx.set_clock("2026-09-30T00:00:00Z")

        response = _escalate(action_id, 0)

        validate_error(response, ApiErrorId.ERR_LADDER_EXHAUSTED.value, 422)

        action = fx.read_action(action_id)
        assert action["action_type"] == "CIVIL_PENALTY", "the type did not advance"
        assert action["escalation_count"] == 2, "no third escalation was counted"
        assert action["penalty_cents"] == 100000, "the penalty was not recomputed"
        assert action["last_escalated_at"] == "2026-08-29T00:00:00Z", (
            "the refused escalation stamped nothing"
        )


class TestRescissionIsLostOnceAnActionHasEscalated:
    """The guard reads the escalation count, not the current status or type."""

    @pytest.fixture
    def ten_day_notice(self, active_program):
        """SITE-L approved with one ISSUED notice documenting ten violation days."""
        site = fx.setup_site_with_approved_plan(
            active_program["term_id"],
            esc_plan_reference="ESC-L",
            site_name="SITE-L",
            operator_name="Northgate Civil",
            disturbed_acres=1.50,
        )
        action = _issue(site["id"], 10)
        return {"term_id": active_program["term_id"], "site": site, "action": action}

    def test_05_documented_days_are_billed_alongside_the_ladder_base(self, ten_day_notice):
        """Ten days at 2000 cents each sit on top of the notice base.

        PRD: "`penalty_cents` is then the ladder base for the action's current
        `action_type` — 25000 cents for `NOTICE_OF_VIOLATION`, 50000 cents for
        `ADMINISTRATIVE_ORDER`, 100000 cents for `CIVIL_PENALTY` — plus 2000 cents for
        each of the `billable_violation_days`, with that sum multiplied by
        `escalation_multiplier` and the product rounded to whole cents."

        Design: Corner/state_machines/rescission_is_barred_once_the_action_has_escalated
        """
        action = ten_day_notice["action"]

        assert action["status"] == "ISSUED", "the action opens at ISSUED"
        assert action["billable_violation_days"] == 10, "ten days are billable"
        assert action["penalty_cents"] == 45000, (
            f"25000 plus ten days at 2000 is 45000, got {action['penalty_cents']}"
        )

    def test_06_escalation_carries_the_documented_days_up_the_ladder(
        self, ten_day_notice
    ):
        """The order base replaces the notice base and the days ride along.

        PRD: "The officer may supply a revised `violation_days`, but escalation is
        monotonic in money: a supplied value below the stored `violation_days` is refused
        with `ERR_PENALTY_DECREASE_FORBIDDEN`."

        Design: Corner/state_machines/rescission_is_barred_once_the_action_has_escalated
        """
        fx.set_clock("2026-08-15T00:00:00Z")

        escalated = validate_success(_escalate(ten_day_notice["action"]["id"], 10))

        assert escalated["action_type"] == "ADMINISTRATIVE_ORDER", "one rung up"
        assert escalated["penalty_cents"] == 70000, (
            f"50000 plus ten days at 2000 is 70000, got {escalated['penalty_cents']}"
        )
        assert escalated["escalation_count"] == 1, "one escalation was counted"

    def test_07_rescission_is_refused_after_the_first_escalation(self, ten_day_notice):
        """An escalated action can be closed but never unwound.

        PRD: "Rescission reverses the money and is only available while the action has
        never been escalated: an `escalation_count` above 0 is refused with
        `ERR_RESCIND_AFTER_ESCALATION`."

        Design: Corner/state_machines/rescission_is_barred_once_the_action_has_escalated
        """
        action_id = ten_day_notice["action"]["id"]
        fx.set_clock("2026-08-15T00:00:00Z")
        validate_success(_escalate(action_id, 10))

        response = api_client.rescind_enforcement_action(
            action_id,
            factories.rescind_payload(reason="Operator produced a compliant plan"),
            OFFICER_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_RESCIND_AFTER_ESCALATION.value, 409)

        action = fx.read_action(action_id)
        assert action["status"] == "ESCALATED", "the refused rescission moved nothing"
        assert action["rescinded_at"] is None, "nothing was stamped"
        assert action["rescinded_reason"] is None, "no reason was recorded"
        assert action["penalty_cents"] == 70000, "the money was not zeroed"

    def test_08_the_refused_rescission_leaves_the_ledger_alone(self, ten_day_notice):
        """The term still carries the escalated penalty in full.

        PRD: "Nothing is persisted when a request is rejected — no partial writes, no
        counter increments, no cascades."

        Design: Corner/state_machines/rescission_is_barred_once_the_action_has_escalated
        """
        action_id = ten_day_notice["action"]["id"]
        fx.set_clock("2026-08-15T00:00:00Z")
        validate_success(_escalate(action_id, 10))
        api_client.rescind_enforcement_action(
            action_id,
            factories.rescind_payload(reason="Operator produced a compliant plan"),
            OFFICER_HEADERS,
        )

        term = fx.read_term(ten_day_notice["term_id"])
        assert term["total_assessed_penalty_cents"] == 70000, (
            "the refused rescission reduced nothing, got "
            f"{term['total_assessed_penalty_cents']}"
        )

        site = fx.read_site(ten_day_notice["site"]["id"])
        assert site["open_enforcement_count"] == 1, "the action is still live"
