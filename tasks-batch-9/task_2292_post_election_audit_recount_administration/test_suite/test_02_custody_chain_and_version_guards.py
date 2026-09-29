"""Second custody cycles on one container, and the batch version guard's precedence."""

from test_helpers import ApiErrorId, api_client, assertions, factories, fixtures
from test_helpers import validate_error, validate_success
from test_helpers.test_users import TEST_USERS

CUSTODY_OFFICER = TEST_USERS["custody_officer_headers"]


def _setup_resealed_batch_drawn_by_a_second_audit():
    """B-003 counted and resealed under the risk-limiting audit, then drawn again.

    Returns the scenario plus the comparison audit's drawn row for B-003.
    """
    scenario = fixtures.setup_canvassed_contest()
    scenario["team"] = fixtures.create_bipartisan_team(scenario["election"]["id"])
    scenario.update(fixtures.setup_audit_round_one(scenario["contest"]["id"]))

    first_drawn = scenario["audit_batches"][0]
    physical = fixtures.read_batch(first_drawn["ballot_batch_id"])
    fixtures.retrieve_batch(
        first_drawn["id"], physical["id"], physical["current_seal_number"]
    )
    tally = fixtures.open_manual_tally(
        first_drawn["id"],
        scenario["team"]["id"],
        counted_votes={"ALVAREZ": 525, "BRENNAN": 475},
        ambiguous_ballot_count=0,
        no_vote_count=0,
    )
    scenario["manual_tally"] = fixtures.submit_manual_tally(
        tally["id"], scenario["team"]["id"]
    )
    fixtures.return_batch(first_drawn["id"], "SEAL-003R")

    comparison = fixtures.setup_audit_round_one(
        scenario["contest"]["id"], audit_type="COMPARISON"
    )
    scenario["comparison"] = comparison
    scenario["first_drawn"] = first_drawn
    scenario["second_drawn"] = comparison["audit_batches"][0]
    scenario["physical"] = fixtures.read_batch(physical["id"])
    return scenario


class TestSecondCustodyCycleOnOneBatch:
    """The same physical container leaves storage once per audit that draws it."""

    def test_second_retrieval_opens_a_new_cycle_under_the_reseal_number(self):
        """PRD §3.2: "The second and later cycles start from `RESEALED` rather than
        `SEALED`: the `observed_seal_number` the officer attests to is then the reseal
        number written at the previous check-in, and the side effects are identical,
        producing a second custody cycle on the same container."

        Design: Difficulty/non_linear_state_machine/nonlinear_batch_custody_reseal_and_second_checkout
        """
        scenario = _setup_resealed_batch_drawn_by_a_second_audit()
        resealed = scenario["physical"]
        assert resealed["custody_status"] == "RESEALED"
        assert resealed["current_seal_number"] == "SEAL-003R"
        assert resealed["checkout_cycle_count"] == 1
        assert resealed["open_checkout_count"] == 0

        response = api_client.retrieve_audit_batch(
            scenario["second_drawn"]["id"],
            factories.retrieve_audit_batch_payload(
                resealed["version"],
                "SEAL-003R",
                note="Second custody cycle for the comparison audit.",
            ),
            CUSTODY_OFFICER,
        )

        validate_success(response)
        batch = fixtures.read_batch(resealed["id"])
        assert batch["current_seal_number"] == "SEAL-003R"
        assert batch["custody_status"] == "CHECKED_OUT"
        assert batch["checkout_cycle_count"] == 1
        assert batch["open_checkout_count"] == 1

    def test_the_two_drawings_carry_independent_retrieval_and_tally_dimensions(self):
        """PRD §3.2: "`tally_status` advances separately, driven by the hand count:
        `NOT_STARTED` becomes `IN_PROGRESS` when a hand tally is opened against the drawn
        batch, `IN_PROGRESS` becomes `COUNTED` when that tally is submitted."

        Design: Difficulty/non_linear_state_machine/nonlinear_batch_custody_reseal_and_second_checkout
        """
        scenario = _setup_resealed_batch_drawn_by_a_second_audit()
        fixtures.retrieve_batch(
            scenario["second_drawn"]["id"], scenario["physical"]["id"], "SEAL-003R"
        )

        first = fixtures.read_audit_batch(scenario["first_drawn"]["id"])
        second = fixtures.read_audit_batch(scenario["second_drawn"]["id"])
        assert first["retrieval_status"] == "RETURNED"
        assert second["retrieval_status"] == "RETRIEVED"
        assert first["tally_status"] == "COUNTED"
        assert second["tally_status"] == "NOT_STARTED"
        assert first["ballot_batch_id"] == second["ballot_batch_id"]

    def test_custody_log_records_both_cycles_in_one_growing_sequence(self):
        """PRD §2.10: "A batch's `open_checkout_count` is the number of `CHECK_OUT` events
        minus the number of `CHECK_IN` events recorded for it, and it is always either 0
        or 1 — a batch is never out of storage twice at once."

        Design: Difficulty/non_linear_state_machine/nonlinear_batch_custody_reseal_and_second_checkout
        """
        scenario = _setup_resealed_batch_drawn_by_a_second_audit()
        fixtures.retrieve_batch(
            scenario["second_drawn"]["id"], scenario["physical"]["id"], "SEAL-003R"
        )

        events = fixtures.list_custody_events(scenario["physical"]["id"])
        for event in events:
            assertions.assert_custody_event(event)
        assertions.assert_custody_log_ordered(events)
        assert [event["event_type"] for event in events] == [
            "INTAKE",
            "AUTHORIZED",
            "CHECK_OUT",
            "CHECK_IN",
            "AUTHORIZED",
            "CHECK_OUT",
        ]
        assert events[3]["event_type"] == "CHECK_IN"
        assert events[3]["seal_number_after"] == "SEAL-003R"
        assert events[5]["event_type"] == "CHECK_OUT"
        assert events[5]["seal_number_before"] == "SEAL-003R"
        assert events[5]["sequence_no"] == 6

    def test_an_exact_machine_match_records_no_discrepancy(self):
        """PRD §3.5: "When `net_error_votes` is not zero, or when the sum of the
        hand-counted votes differs from the sum of the machine votes for that batch, a
        discrepancy is created in `OPEN`."

        Design: Difficulty/non_linear_state_machine/nonlinear_batch_custody_reseal_and_second_checkout
        """
        scenario = _setup_resealed_batch_drawn_by_a_second_audit()

        tally = fixtures.read_manual_tally(scenario["manual_tally"]["id"])
        assert tally["net_error_votes"] == 0
        assert tally["status"] == "SUBMITTED"
        assert fixtures.list_discrepancies(tally["id"]) == []


class TestStaleBatchVersionPrecedesQuarantine:
    """The version guard is evaluated ahead of every safety test on the batch."""

    def test_stale_batch_version_wins_over_the_quarantine_state(self):
        """PRD §2.6: "The mismatch is rejected with `ERR_STALE_BALLOT_BATCH_VERSION`
        (HTTP 412), and this check is evaluated before every safety test on the batch,
        including the quarantine test."

        Design: Difficulty/priority_pair_validation_conflict/priority_stale_ballot_batch_version_precedes_batch_quarantined
        """
        scenario = fixtures.setup_canvassed_contest()
        scenario.update(fixtures.setup_audit_round_one(scenario["contest"]["id"]))
        drawn = scenario["audit_batches"][0]
        physical = fixtures.read_batch(drawn["ballot_batch_id"])
        stale_version = physical["version"]
        validate_success(
            api_client.quarantine_ballot_batch(
                physical["id"],
                {"reason": "Sealed evidence bag damaged in transit."},
                CUSTODY_OFFICER,
            )
        )

        response = api_client.retrieve_audit_batch(
            drawn["id"],
            factories.retrieve_audit_batch_payload(
                stale_version, physical["current_seal_number"]
            ),
            CUSTODY_OFFICER,
        )

        validate_error(response, ApiErrorId.ERR_STALE_BALLOT_BATCH_VERSION.value, 412)
        refreshed = fixtures.read_batch(physical["id"])
        assert refreshed["version"] == stale_version + 1
        assert refreshed["custody_status"] == "QUARANTINED"

    def test_refreshing_the_version_then_surfaces_the_quarantine(self):
        """PRD §2.9: "The physical ballot batch is not `QUARANTINED` — otherwise
        `ERR_BATCH_QUARANTINED`. Applies to batch retrieval, batch return, hand-tally
        creation, hand-tally submission and recount filing: a quarantined batch is
        evidence, so it can neither leave storage nor be counted nor be placed in a
        recount scope."

        Design: Difficulty/priority_pair_validation_conflict/priority_stale_ballot_batch_version_precedes_batch_quarantined
        """
        scenario = fixtures.setup_canvassed_contest()
        scenario.update(fixtures.setup_audit_round_one(scenario["contest"]["id"]))
        drawn = scenario["audit_batches"][0]
        physical = fixtures.read_batch(drawn["ballot_batch_id"])
        validate_success(
            api_client.quarantine_ballot_batch(
                physical["id"],
                {"reason": "Sealed evidence bag damaged in transit."},
                CUSTODY_OFFICER,
            )
        )
        refreshed = fixtures.read_batch(physical["id"])

        response = api_client.retrieve_audit_batch(
            drawn["id"],
            factories.retrieve_audit_batch_payload(
                refreshed["version"], refreshed["current_seal_number"]
            ),
            CUSTODY_OFFICER,
        )

        validate_error(response, ApiErrorId.ERR_BATCH_QUARANTINED.value, 409)
        assert fixtures.read_batch(physical["id"])["open_checkout_count"] == 0

    def test_quarantine_voids_the_drawn_slot_and_logs_no_checkout(self):
        """PRD §3.2: "then every drawn batch referencing this physical batch whose
        `tally_status` is `NOT_STARTED` or `IN_PROGRESS` has its `tally_status` set to
        `VOIDED`."

        Design: Difficulty/priority_pair_validation_conflict/priority_stale_ballot_batch_version_precedes_batch_quarantined
        """
        scenario = fixtures.setup_canvassed_contest()
        scenario.update(fixtures.setup_audit_round_one(scenario["contest"]["id"]))
        drawn = scenario["audit_batches"][0]
        physical = fixtures.read_batch(drawn["ballot_batch_id"])
        validate_success(
            api_client.quarantine_ballot_batch(
                physical["id"],
                {"reason": "Sealed evidence bag damaged in transit."},
                CUSTODY_OFFICER,
            )
        )

        slot = fixtures.read_audit_batch(drawn["id"])
        assert slot["retrieval_status"] == "PENDING_RETRIEVAL"
        assert slot["tally_status"] == "VOIDED"
        events = fixtures.list_custody_events(physical["id"])
        assert [event["event_type"] for event in events] == [
            "INTAKE",
            "AUTHORIZED",
            "QUARANTINE",
        ]
        assert events[2]["sequence_no"] == 3
        assert fixtures.list_custody_events(physical["id"], event_type="CHECK_OUT") == []
