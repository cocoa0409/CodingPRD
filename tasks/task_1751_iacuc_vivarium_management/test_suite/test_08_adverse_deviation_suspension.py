"""Adverse events, protocol deviations, and the suspension chain: the
depth-3 cascade from deviation to protocol to cages and adverse events,
escalation-triggered deviation auto-filing, the serious-deviation close
restriction, the 72-hour resolution deadline, reinstatement recovery, and
OCC-guarded suspension (PRD §2.7, §3.8).
"""
from test_helpers import (
    ADMIN,
    STAFF,
    VET,
    ApiErrorId,
    api_client,
    assert_adverse_event,
    assert_protocol_deviation,
    create_cleared_personnel,
    get_success_data,
    set_clock,
    setup_approved_with_cage,
    setup_occupied_cage,
    setup_reinstated_protocol,
    setup_suspended_protocol,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_animal_payload
from test_helpers.fixtures import (
    add_mouse,
    create_approved_protocol,
    file_adverse_event,
    report_deviation,
)


class TestDeviationSuspensionCascade:
    def test_impose_suspension_cascades_three_hops(self, api):
        """PRD §3.8: "Imposing suspension moves the deviation to
        `SUSPENSION_IMPOSED` and cascades: the protocol moves from `APPROVED`
        to `SUSPENDED`, and that protocol suspension in turn cascades to cages
        and adverse-event reports as described below." and "Suspension
        cascades broadly: every cage billed to the protocol that stands
        `OCCUPIED` becomes `OVER_CAPACITY`, frozen against any new animal
        additions, and every adverse-event report on the protocol in `OPEN` or
        `UNDER_TREATMENT` becomes `ESCALATED`."

        Design: Difficulty/transitive_cascade/deviation_to_protocol_to_cage_and_adverse_event
        """
        scenario = setup_suspended_protocol(with_open_event=True)

        deviation = scenario["deviation"]
        assert_protocol_deviation(deviation)
        assert deviation["state"] == "SUSPENSION_IMPOSED"

        protocol = scenario["protocol"]
        assert protocol["status"] == "SUSPENDED", "hop 2: protocol suspended"

        cage = get_success_data(api_client.get_cage(scenario["cage"]["id"], ADMIN))
        assert cage["status"] == "OVER_CAPACITY", (
            "hop 3: the occupied cage freezes to OVER_CAPACITY"
        )

        events = get_success_data(
            api_client.list_protocol_adverse_events(protocol["id"], VET)
        )
        assert len(events) == 1
        assert events[0]["state"] == "ESCALATED", (
            "hop 3: the OPEN adverse event escalates"
        )

    def test_suspension_freezes_cage_against_new_animals(self, api):
        """PRD §3.8: "every cage billed to the protocol that stands `OCCUPIED`
        becomes `OVER_CAPACITY`, frozen against any new animal additions". PRD
        §3.4: "A protocol that is not `APPROVED` refuses admission with
        `ERR_PROTOCOL_NOT_APPROVED` (HTTP 409)."

        Design: Difficulty/transitive_cascade/deviation_to_protocol_to_cage_and_adverse_event
        """
        scenario = setup_suspended_protocol(with_open_event=True)

        resp = api_client.create_animal(
            create_animal_payload(
                scenario["cage"]["id"], scenario["protocol"]["id"],
            ),
            STAFF,
        )
        validate_error(resp, ApiErrorId.ERR_PROTOCOL_NOT_APPROVED)

        animals = get_success_data(
            api_client.list_cage_animals(scenario["cage"]["id"], STAFF)
        )
        assert len([a for a in animals if a["status"] == "ALIVE"]) == 1, (
            "the frozen cage accepted no new animal"
        )


class TestEscalationAutoDeviation:
    def _severe_event_scenario(self, severity):
        scenario = setup_approved_with_cage(
            species="RABBIT", capacity_adults=1, max_animals=3,
            pain_category="D", room_code="VIV-202",
        )
        animal = add_mouse(
            scenario["cage"]["id"], scenario["protocol"]["id"],
            species="RABBIT", date_of_birth="2026-02-01T00:00:00Z", sex="F",
        )
        reporter = create_cleared_personnel()
        event = file_adverse_event(
            scenario["protocol"]["id"], animal["id"], reporter["id"],
            severity=severity,
        )
        scenario["animal"] = animal
        scenario["reporter"] = reporter
        scenario["event"] = event
        return scenario

    def test_severe_escalation_auto_files_serious_deviation(self, api):
        """PRD §3.8: "Escalation carries a regulatory cascade: when the
        report's `severity` is `SEVERE` or `MORBUND`, the system automatically
        files a protocol deviation of `seriousness` `SERIOUS` against the same
        protocol." and "the deviation's `state` begins as `REPORTED`."

        Design: Difficulty/transitive_cascade/adverse_event_escalation_to_deviation
        """
        scenario = self._severe_event_scenario("SEVERE")

        escalated = validate_success(
            api_client.escalate_adverse_event(scenario["event"]["id"], VET)
        )
        assert_adverse_event(escalated)
        assert escalated["state"] == "ESCALATED"

        deviations = get_success_data(
            api_client.list_protocol_deviations(scenario["protocol"]["id"], ADMIN)
        )
        assert len(deviations) == 1, (
            "escalating a SEVERE report auto-files exactly one deviation"
        )
        deviation = deviations[0]
        assert_protocol_deviation(deviation)
        assert deviation["seriousness"] == "SERIOUS"
        assert deviation["state"] == "REPORTED"
        assert deviation["protocol_id"] == scenario["protocol"]["id"]

    def test_morbund_escalation_auto_files_serious_deviation(self, api):
        """PRD §3.8: "when the report's `severity` is `SEVERE` or `MORBUND`,
        the system automatically files a protocol deviation of `seriousness`
        `SERIOUS` against the same protocol."

        Design: Difficulty/transitive_cascade/adverse_event_escalation_to_deviation
        """
        scenario = self._severe_event_scenario("MORBUND")

        escalated = validate_success(
            api_client.escalate_adverse_event(scenario["event"]["id"], VET)
        )
        assert escalated["state"] == "ESCALATED"

        deviations = get_success_data(
            api_client.list_protocol_deviations(scenario["protocol"]["id"], ADMIN)
        )
        assert len(deviations) == 1
        assert deviations[0]["seriousness"] == "SERIOUS"
        assert deviations[0]["state"] == "REPORTED"


class TestDeviationCloseRestriction:
    def test_serious_deviation_cannot_close_but_minor_can(self, api):
        """PRD §3.8: "From `UNDER_REVIEW` there are exactly two exits. Closing
        is reserved for `MINOR` deviations — closing a `SERIOUS` deviation is
        rejected with `ERR_SERIOUS_DEVIATION_NOT_CLOSABLE` (HTTP 422) — and
        the closer must not be the reporter, per §2.10."

        Design: Corner/state_machines/serious_deviation_cannot_close
        """
        scenario = create_approved_protocol()
        proto_id = scenario["protocol"]["id"]
        reporter = create_cleared_personnel()
        serious = report_deviation(proto_id, reporter["id"], seriousness="SERIOUS")
        minor = report_deviation(proto_id, reporter["id"], seriousness="MINOR")
        get_success_data(api_client.begin_deviation_review(serious["id"], ADMIN))
        get_success_data(api_client.begin_deviation_review(minor["id"], ADMIN))

        resp = api_client.close_deviation(serious["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SERIOUS_DEVIATION_NOT_CLOSABLE)

        closed = validate_success(api_client.close_deviation(minor["id"], ADMIN))
        assert closed["state"] == "CLOSED"


class TestEscalatedResolution:
    def test_escalated_report_resolves_after_deadline_and_minor_files_no_deviation(self, api):
        """PRD §3.8: "Escalation moves a report from `OPEN` to `ESCALATED`,
        or from `UNDER_TREATMENT` to `ESCALATED`" and "An `ESCALATED` report
        can still be resolved — the move from `ESCALATED` to `RESOLVED`
        carries no deadline — and `RESOLVED` is terminal." and "when the
        report's `severity` is `SEVERE` or `MORBUND`, the system automatically
        files a protocol deviation of `seriousness` `SERIOUS` against the same
        protocol" — a `MINOR` report files none.

        Design: Corner/validations/adverse_event_resolve_overdue_requires_escalation
        """
        scenario = setup_occupied_cage(num_animals=1)
        reporter = create_cleared_personnel()
        event = file_adverse_event(
            scenario["protocol"]["id"], scenario["animals"][0]["id"],
            reporter["id"], severity="MINOR", description="scratch",
        )
        get_success_data(api_client.begin_treatment(event["id"], VET))

        escalated = validate_success(
            api_client.escalate_adverse_event(event["id"], VET)
        )
        assert escalated["state"] == "ESCALATED", (
            "escalation moves a report from UNDER_TREATMENT to ESCALATED"
        )

        # Past reported_at + 72 hours (2026-08-04T00:00:00Z): the ESCALATED
        # branch carries no resolution deadline.
        set_clock("2026-08-05T00:00:00Z")
        resolved = validate_success(api_client.resolve_adverse_event(event["id"], VET))
        assert resolved["state"] == "RESOLVED"
        assert resolved["resolved_at"] is not None

        deviations = get_success_data(
            api_client.list_protocol_deviations(scenario["protocol"]["id"], ADMIN)
        )
        assert deviations == [], (
            "escalating a MINOR report files no deviation (the cascade is "
            "SEVERE/MORBUND only, PRD §3.8)"
        )


class TestReinstatementRecovery:
    def test_reinstate_recovers_frozen_cage(self, api):
        """PRD §3.8: "Reinstatement requires every deviation on the protocol
        to stand in `CLOSED` or `SUSPENSION_IMPOSED`; it returns the protocol
        from `SUSPENDED` to `APPROVED` and recounts each frozen cage,
        returning those whose effective occupancy is within `capacity_adults`
        to `OCCUPIED`."

        Design: Corner/complexity_layers/suspension_cascade_then_reinstate_recovers_cage
        """
        scenario = setup_suspended_protocol()
        cage_id = scenario["cage"]["id"]
        frozen = get_success_data(api_client.get_cage(cage_id, ADMIN))
        assert frozen["status"] == "OVER_CAPACITY", (
            "while suspended the cage is frozen OVER_CAPACITY"
        )

        reinstated = validate_success(
            api_client.reinstate_protocol(scenario["protocol"]["id"], ADMIN)
        )
        assert reinstated["status"] == "APPROVED"

        cage = get_success_data(api_client.get_cage(cage_id, ADMIN))
        assert cage["status"] == "OCCUPIED", (
            "1 mouse within capacity 5: the recount restores OCCUPIED with no "
            "drift"
        )


class TestOccGuardedSuspension:
    def test_suspend_with_stale_protocol_version_rejected(self, api):
        """PRD §2.7: "Suspending a protocol requires the request body to carry
        `expected_protocol_version`, holding the protocol `version` the client
        last observed. If the protocol's current `version` has advanced since
        that observation, the suspension is rejected with `ERR_STALE_VERSION`
        (HTTP 412), and the client must re-read the protocol before retrying."
        PRD §3.3: "each successful attachment increments the protocol's
        `version`."

        Design: Corner/errors/stale_version_on_suspend
        """
        # A prior deviation stands SUSPENSION_IMPOSED (PRD §3.8 direct-suspend
        # precondition) and the protocol is APPROVED again after reinstatement.
        scenario = setup_reinstated_protocol()
        protocol = scenario["protocol"]
        assert protocol["status"] == "APPROVED"
        observed_version = protocol["version"]

        member = create_cleared_personnel()
        get_success_data(api_client.attach_protocol_personnel(
            protocol["id"], {"personnel_id": member["id"]},
            scenario["investigator_headers"],
        ))

        resp = api_client.suspend_protocol(
            protocol["id"],
            {"expected_protocol_version": observed_version},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        current = get_success_data(api_client.get_protocol(protocol["id"], ADMIN))
        assert current["status"] == "APPROVED", (
            "a stale suspension changes nothing"
        )
