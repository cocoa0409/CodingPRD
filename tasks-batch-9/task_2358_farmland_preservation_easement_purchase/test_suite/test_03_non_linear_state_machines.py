"""Cyclic negotiation and the easement's three parallel state dimensions."""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    application_version,
    assert_negotiation_round,
    complete_visit,
    file_counter,
    issue_offer,
    issue_offer_payload,
    list_negotiation_log,
    read_easement,
    run_sweep,
    schedule_visit,
    setup_easement_with_approved_rights_amendment,
    setup_easement_with_open_violation,
    setup_ranked_application,
    setup_recorded_easement,
    read_application,
)

ADMIN = TEST_USERS["program_admin_headers"]
OFFICER = TEST_USERS["acquisition_officer_headers"]


class TestNegotiationCycleBound:
    """`COUNTERED -> OFFER_ISSUED -> COUNTERED` repeats until the offer bound."""

    def test_three_offer_rounds_are_admitted_and_the_fourth_is_rejected(self):
        """The bound is `max_negotiation_rounds`, counted over OFFER entries.

        PRD §3.5: "Separately, the application's `negotiation_round_count` — the
        number of `OFFER` entries in its log — must be strictly below the
        program's `max_negotiation_rounds`, and an attempt to exceed the bound is
        rejected with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`."

        Design: Difficulty/non_linear_state_machine/negotiation_cycle_bounded_at_three_offer_rounds_fourth_offer_rejected
        """
        scenario = setup_ranked_application()
        application_id = scenario["application"]["id"]
        landowner_id = scenario["landowner"]["id"]
        validate_success(api_client.set_clock("2026-10-05T00:00:00Z"))

        # The default program bound is three offer rounds.
        assert scenario["program"]["max_negotiation_rounds"] == 3

        for index, (offer_cents, counter_cents) in enumerate(
            [
                (170_000_000, 171_000_000),
                (172_000_000, 173_000_000),
                (174_000_000, 175_000_000),
            ],
            start=1,
        ):
            offered = issue_offer(application_id, offer_cents, "FULL_PURCHASE")
            assert offered["status"] == "OFFER_ISSUED"
            assert offered["negotiation_round_count"] == index
            countered = file_counter(application_id, landowner_id, counter_cents)
            assert countered["status"] == "COUNTERED"
            # A counter is not an offer, so the bound does not move.
            assert countered["negotiation_round_count"] == index

        fourth = api_client.issue_offer(
            application_id,
            issue_offer_payload(
                application_version(application_id), 175_500_000, "FULL_PURCHASE"
            ),
            OFFICER,
        )
        validate_error(fourth, ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED.value)

        # The rejected offer mutated nothing.
        application = read_application(application_id)
        assert application["status"] == "COUNTERED"
        assert application["negotiation_round_count"] == 3
        assert application["current_offer_cents"] == 174_000_000
        assert application["last_counter_cents"] == 175_000_000
        # `proposed_price_cents` tracks the most recent OFFER or COUNTER entry.
        assert application["proposed_price_cents"] == 175_000_000

    def test_the_log_records_six_alternating_entries_with_answering_round_indexes(self):
        """Each counter carries the `round_index` of the offer it answers.

        PRD §3.5: "A successful counter appends a `COUNTER` entry carrying the
        `round_index` of the offer it answers, sets both `last_counter_cents` and
        `proposed_price_cents` to the counter amount, and moves the application
        `OFFER_ISSUED → COUNTERED`."

        Design: Difficulty/non_linear_state_machine/negotiation_cycle_bounded_at_three_offer_rounds_fourth_offer_rejected
        """
        scenario = setup_ranked_application()
        application_id = scenario["application"]["id"]
        landowner_id = scenario["landowner"]["id"]
        validate_success(api_client.set_clock("2026-10-05T00:00:00Z"))

        amounts = [
            (170_000_000, 171_000_000),
            (172_000_000, 173_000_000),
            (174_000_000, 175_000_000),
        ]
        for offer_cents, counter_cents in amounts:
            issue_offer(application_id, offer_cents, "FULL_PURCHASE")
            file_counter(application_id, landowner_id, counter_cents)

        entries, meta = validate_paginated(
            api_client.list_negotiation_rounds(application_id, ADMIN, {"limit": 100})
        )
        assert meta["total_count"] == 6
        assert [entry["kind"] for entry in entries] == [
            "OFFER",
            "COUNTER",
            "OFFER",
            "COUNTER",
            "OFFER",
            "COUNTER",
        ]
        assert [entry["round_index"] for entry in entries] == [1, 1, 2, 2, 3, 3]
        assert [entry["amount_cents"] for entry in entries] == [
            170_000_000,
            171_000_000,
            172_000_000,
            173_000_000,
            174_000_000,
            175_000_000,
        ]
        for entry in entries:
            assert_negotiation_round(entry)
            if entry["kind"] == "OFFER":
                assert entry["offer_expires_on"] is not None
                assert entry["actor_role"] == "AcquisitionOfficer"
            else:
                assert entry["offer_expires_on"] is None
                assert entry["actor_role"] == "Landowner"

        offers_only, offers_meta = validate_paginated(
            api_client.list_negotiation_rounds(
                application_id, ADMIN, {"kind": "OFFER", "limit": 100}
            )
        )
        assert offers_meta["total_count"] == 3
        assert all(entry["kind"] == "OFFER" for entry in offers_only)

    def test_a_bound_of_one_still_admits_the_answering_counter(self):
        """Only OFFER entries count against the bound, never counters.

        PRD §3.5: "The cycle `COUNTERED → OFFER_ISSUED → COUNTERED` may repeat
        until `negotiation_round_count` reaches the program's
        `max_negotiation_rounds`."

        Design: Difficulty/non_linear_state_machine/negotiation_cycle_bounded_at_three_offer_rounds_fourth_offer_rejected
        """
        scenario = setup_ranked_application(
            program_overrides={"max_negotiation_rounds": 1}
        )
        application_id = scenario["application"]["id"]
        validate_success(api_client.set_clock("2026-10-05T00:00:00Z"))

        issue_offer(application_id, 170_000_000, "FULL_PURCHASE")
        countered = file_counter(
            application_id, scenario["landowner"]["id"], 171_000_000
        )
        assert countered["status"] == "COUNTERED"
        assert countered["negotiation_round_count"] == 1

        second = api_client.issue_offer(
            application_id,
            issue_offer_payload(
                application_version(application_id), 172_000_000, "FULL_PURCHASE"
            ),
            OFFICER,
        )
        validate_error(second, ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED.value)
        assert len(list_negotiation_log(application_id, {"limit": 100})) == 2


class TestEasementParallelDimensions:
    """Deed, monitoring and compliance advance without touching one another."""

    def test_the_sweep_advances_monitoring_while_compliance_stays_violation_open(self):
        """A violating easement traverses the monitoring edges all the same.

        PRD §3.8: "The sweep advances `MONITORING_CURRENT → MONITORING_DUE` and
        then `MONITORING_DUE → MONITORING_DELINQUENT` as the clock crosses those
        boundaries, incrementing the easement's `version` at each step, and it
        does so independently of compliance: a compliant easement and one with
        an open violation both traverse those edges on the same sweep."

        Design: Difficulty/non_linear_state_machine/easement_three_parallel_dimensions_advance_independently
        """
        scenario = setup_easement_with_open_violation(
            program_overrides={"monitoring_interval_days": 120}
        )
        easement = scenario["easement"]
        assert easement["status"] == "RECORDED"
        assert easement["compliance_status"] == "VIOLATION_OPEN"
        assert easement["stewardship_status"] == "MONITORING_CURRENT"
        assert easement["stewardship_hold"] is True
        # 2026-12-15 advanced by 120 days.
        assert easement["next_monitoring_due_on"].startswith("2027-04-14")
        # The MINOR cure clock runs to 2027-06-13, well past the sweep below.
        assert scenario["violation"]["cure_deadline_on"].startswith("2027-06-13")

        validate_success(api_client.set_clock("2027-04-20T00:00:00Z"))
        counters = run_sweep()
        assert counters["due_count"] == 1
        assert counters["escalated_violation_count"] == 0

        after = read_easement(easement["id"])
        assert after["stewardship_status"] == "MONITORING_DUE"
        # Neither of the other two dimensions moved.
        assert after["compliance_status"] == "VIOLATION_OPEN"
        assert after["status"] == "RECORDED"

    def test_an_approved_amendment_moves_only_the_deed_dimension(self):
        """Approval flips the deed dimension and leaves the other two alone.

        PRD §3.9: "On approval the amendment moves `UNDER_REVIEW → APPROVED`,
        the easement's deed dimension flips to `AMENDED` from either `RECORDED`
        or `AMENDED`, and `amendment_count` is recomputed."

        Design: Difficulty/non_linear_state_machine/easement_three_parallel_dimensions_advance_independently
        """
        scenario = setup_easement_with_approved_rights_amendment()
        easement = scenario["easement"]
        assert easement["status"] == "AMENDED"
        assert easement["stewardship_status"] == "MONITORING_CURRENT"
        assert easement["compliance_status"] == "COMPLIANT"
        assert easement["amendment_count"] == 1
        assert easement["pending_amendment_count"] == 0
        assert easement["stewardship_hold"] is False

    def test_monitoring_completion_resets_only_the_stewardship_dimension(self):
        """Completion re-anchors monitoring and never touches compliance.

        PRD §3.8: "Completion then resets the stewardship dimension only:
        `last_monitored_on` becomes the completion instant,
        `next_monitoring_due_on` is re-projected from that new anchor, and
        `stewardship_status` returns to `MONITORING_CURRENT` whether it was
        `MONITORING_DUE` or `MONITORING_DELINQUENT`."

        Design: Difficulty/non_linear_state_machine/easement_three_parallel_dimensions_advance_independently
        """
        scenario = setup_recorded_easement()
        easement_id = scenario["easement"]["id"]
        assert scenario["easement"]["next_monitoring_due_on"].startswith("2027-12-15")

        validate_success(api_client.set_clock("2027-12-20T00:00:00Z"))
        run_sweep()
        assert read_easement(easement_id)["stewardship_status"] == "MONITORING_DUE"

        visit = schedule_visit(
            easement_id,
            window_start="2027-12-20T00:00:00Z",
            window_end="2027-12-27T00:00:00Z",
        )
        completed = complete_visit(visit["id"], 0)
        assert completed["finding"] == "NO_ISSUE"
        assert completed["completed_at"].startswith("2027-12-20")

        after = read_easement(easement_id)
        assert after["stewardship_status"] == "MONITORING_CURRENT"
        assert after["last_monitored_on"].startswith("2027-12-20")
        # 2027-12-20 advanced by the 365-day interval across a leap February.
        assert after["next_monitoring_due_on"].startswith("2028-12-19")
        # Compliance and the deed dimension are untouched.
        assert after["compliance_status"] == "COMPLIANT"
        assert after["status"] == "RECORDED"
        assert after["impervious_used_sqft"] == 0
        assert after["impervious_allowance_sqft"] == 139_392
        assert after["protected_acres"] == pytest.approx(160.00, abs=0.01)
