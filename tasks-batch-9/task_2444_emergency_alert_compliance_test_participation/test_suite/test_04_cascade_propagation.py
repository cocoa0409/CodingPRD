"""The two deterministic cascades of the EAS Compliance API.

Both writes covered here fan out across several rows in a single request, and in
both the hop order is normative because each hop's output is the next hop's
input:

* filing an equipment outage propagates device → assignments → station →
  test events (four hops);
* activating a state plan propagates plan → station → inspection requests
  (three hops), with the last hop conditional on the revalidation flag flipping.

Every test builds its own world: the harness restarts the API before each test,
so each one starts against an empty database with the logical clock at its
startup default 2026-08-01T00:00:00Z.
"""

from datetime import datetime

import pytest

from test_helpers import (
    ADMIN,
    ENGINEER,
    INSPECTOR,
    SOURCE_CALL_SIGNS,
    TEST_DEFAULTS,
    api_client,
    assign_source,
    create_active_plan,
    create_plan,
    create_ready_device,
    equipment_outage_payload,
    evaluate_readiness,
    get_success_data,
    register_device,
    register_station,
    schedule_test_event,
    set_clock,
    setup_closed_inspection,
    setup_responded_inspection,
    station_summary,
    validate_success,
)

TEST_WINDOW_START = "2026-08-12T00:00:00Z"
TEST_WINDOW_END = "2026-08-12T01:00:00Z"
OUTAGE_INSTANT = "2026-08-12T00:30:00Z"

CLOCK_AT_STARTUP = "2026-08-01T00:00:00Z"
INSPECTION_DUE_AT = "2026-08-08T00:00:00Z"


def _instant(value):
    """Parse a server-stamped ISO 8601 UTC instant so it compares by value."""
    assert value is not None, "expected a stamped instant, got null"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# The outage cascade — four hops out of one POST /equipment-outages
# ---------------------------------------------------------------------------
def _station_with_ready_event_and_spare_device():
    """A plan requiring PEP and NWS, one READY device carrying both assignments, a
    second device that is decommissioned out of the readiness denominator, and a
    WEEKLY test event driven to READY inside its window."""
    plan = create_active_plan(("PEP", "NWS"), ())
    station = register_station(plan["id"])
    dev1 = create_ready_device(station["id"])
    dev2 = register_device(
        station["id"], model_code="DASDEC-3", device_role="MONITOR", firmware_version="5.2.0"
    )
    ma1 = assign_source(
        station["id"], dev1["id"], source_type="PEP", source_call_sign=SOURCE_CALL_SIGNS["PEP"]
    )
    ma2 = assign_source(
        station["id"], dev1["id"], source_type="NWS", source_call_sign=SOURCE_CALL_SIGNS["NWS"]
    )
    event = schedule_test_event(station["id"], TEST_WINDOW_START, TEST_WINDOW_END)
    set_clock(OUTAGE_INSTANT)
    first_evaluation = evaluate_readiness(event["id"])
    get_success_data(api_client.decommission_device(dev2["id"], ADMIN))
    second_evaluation = evaluate_readiness(event["id"])
    return {
        "plan": plan,
        "station_id": station["id"],
        "dev1": dev1,
        "dev2": dev2,
        "ma1": ma1,
        "ma2": ma2,
        "event_id": event["id"],
        "first_evaluation": first_evaluation,
        "second_evaluation": second_evaluation,
    }


def _file_outage_on(device_id):
    return validate_success(
        api_client.create_equipment_outage(
            equipment_outage_payload(
                device_id, OUTAGE_INSTANT, failure_summary="decoder chassis dead"
            ),
            ENGINEER,
        ),
        201,
    )


class TestOutageCascade:
    """POST /equipment-outages fans out device → assignments → station → test events."""

    def test_decommissioned_device_leaves_the_readiness_denominator(self):
        """PRD §3.6: "The **device ratio** is the number of the station's units in `READY` divided by the number of the station's countable units, where countable means units whose `status` is `REGISTERED`, `READY` or `FAILED`; `DECOMMISSIONED` units leave the denominator entirely, and the denominator is treated as 1 whenever the countable count is 0, so a station with no equipment scores a device ratio of 0 rather than failing to compute."
        PRD §3.2: "Decommissioning has one lasting consequence for scoring: a `DECOMMISSIONED` unit leaves the readiness denominator described in §3.6 entirely, whereas units in `REGISTERED`, `READY` and `FAILED` all remain counted there."
        PRD §3.6: "The score is 40 times the device ratio plus 40 times the coverage ratio plus 20 times the recent-activity ratio, rounded half-up to two decimal places once, after the weighted sum has been formed."

        Design: Difficulty/transitive_cascade/outage_create_cascades_four_levels_device_assignments_station_test_event
        """
        ctx = _station_with_ready_event_and_spare_device()

        first = ctx["first_evaluation"]
        assert first["readiness_score"] == pytest.approx(60.00, abs=0.01), (
            "40 * 1/2 ready devices + 40 * 2/2 coverage + 0 recent alerts"
        )
        assert first["status"] == "READINESS_PENDING", "60.00 falls short of 80.00"

        second = ctx["second_evaluation"]
        assert second["readiness_score"] == pytest.approx(80.00, abs=0.01), (
            "the decommissioned unit leaves the denominator: 40 * 1/1 + 40 * 2/2"
        )
        assert second["status"] == "READY"

    def test_outage_create_fails_the_device_and_suspends_its_assignments(self):
        """PRD §2.11: "Hop 1 is the direct effect of the create: the referenced `EASDevice` transitions to `FAILED` from either `REGISTERED` or `READY`."
        PRD §2.11: "Hop 2 is caused by the device becoming `FAILED`: every `MonitoringAssignment` referencing that device whose status is `ACTIVE` or `SILENT` transitions to `SUSPENDED`."
        PRD §3.4: "The create stamps `notified_at` from the logical clock — note that `notified_at` records when the notification reached the system, while `detected_at` records when the engineer saw the failure, and the two are ordinarily different instants — and opens the row in `OPEN` with `repair_cycle_count` 0, `repair_started_at` and `restored_at` null, `continuous_downtime_hours` and `obligation_downtime_hours` null, and `continuous_clock_breached` and `obligation_breached` both false."

        Design: Difficulty/transitive_cascade/outage_create_cascades_four_levels_device_assignments_station_test_event
        """
        ctx = _station_with_ready_event_and_spare_device()

        outage = _file_outage_on(ctx["dev1"]["id"])

        assert outage["status"] == "OPEN"
        assert _instant(outage["notified_at"]) == _instant(OUTAGE_INSTANT)
        assert outage["continuous_downtime_hours"] is None
        assert outage["obligation_downtime_hours"] is None
        assert outage["repair_cycle_count"] == 0

        failed_device = get_success_data(api_client.get_device(ctx["dev1"]["id"], ADMIN))
        assert failed_device["status"] == "FAILED", "hop 1 fails the referenced unit"

        for key in ("ma1", "ma2"):
            assignment = get_success_data(
                api_client.get_monitoring_assignment(ctx[key]["id"], ADMIN)
            )
            assert assignment["status"] == "SUSPENDED", (
                f"hop 2 suspends every ACTIVE assignment on the failed unit, {key} is "
                f"{assignment['status']}"
            )

        spare = get_success_data(api_client.get_device(ctx["dev2"]["id"], ADMIN))
        assert spare["status"] == "DECOMMISSIONED", (
            "hop 2 is scoped to the failed unit; the other device is untouched"
        )

    def test_outage_create_recomputes_the_station_score_and_posture(self):
        """PRD §2.11: "Hop 3 is caused by those assignments leaving `ACTIVE`: the station's `accessible_source_count` is recomputed and the station scoring re-runs, moving `compliance_posture` per the bands in §2.10."
        PRD §3.8: "`accessible_source_count` is the number of *distinct* `source_type` values among the station's monitoring assignments whose `status` is `ACTIVE` and whose `source_type` appears in the governing plan's `required_source_types`; two `ACTIVE` assignments covering the same required source type therefore count once, and assignments in `SILENT`, `SUSPENDED` or `DECOMMISSIONED` do not count at all."
        PRD §3.8: "25.00 points for every required source type the station is missing, where the missing count is the plan's `required_source_count` less the station's `accessible_source_count`, floored at zero so that over-coverage never earns a credit;"
        PRD §2.10: "The band mapping is: a score of 90.00 or greater yields `COMPLIANT`; a score of at least 75.00 but below 90.00 yields `WATCH`; anything below 75.00 yields `SUSPENDED_FILINGS`."
        PRD §3.8: "When the station is not certified-eligible, `compliance_variant_applied` is `PROVISIONAL` and only the first four deductions are applied."

        Design: Difficulty/transitive_cascade/outage_create_cascades_four_levels_device_assignments_station_test_event
        """
        ctx = _station_with_ready_event_and_spare_device()

        _file_outage_on(ctx["dev1"]["id"])

        summary = station_summary(ctx["station_id"])
        assert summary["accessible_source_count"] == 0, (
            "both assignments left ACTIVE, so no required source is covered"
        )
        assert summary["missing_source_count"] == 2
        assert summary["compliance_score"] == pytest.approx(50.00, abs=0.01), (
            "100.00 - 2 * 25.00; a score computed before hop 2 would still read 100.00"
        )
        assert summary["compliance_posture"] == "SUSPENDED_FILINGS", "50.00 is below 75.00"
        assert summary["compliance_variant_applied"] == "PROVISIONAL"
        assert summary["outage_breach_count"] == 0, (
            "the fresh outage has obligation_breached false, so it deducts nothing yet"
        )

    def test_outage_create_reverts_the_ready_test_event(self):
        """PRD §2.11: "Hop 4 fires only if hop 3 pushed the posture into `SUSPENDED_FILINGS`: every test event of that station in status `READY` reverts to `READINESS_PENDING` with `readiness_score` and `readiness_evaluated_at` cleared to null."
        PRD §3.4: "It then runs the full four-hop outage cascade of §2.11: the unit becomes `FAILED` (from `REGISTERED` → `FAILED` or `READY` → `FAILED`), its `ACTIVE` and `SILENT` assignments become `SUSPENDED`, the station's `accessible_source_count` is recomputed and the station rescored, and if that rescoring pushes the station into `SUSPENDED_FILINGS`, the station's `READY` test events revert to `READINESS_PENDING` with their readiness figures cleared."

        Design: Difficulty/transitive_cascade/outage_create_cascades_four_levels_device_assignments_station_test_event
        """
        ctx = _station_with_ready_event_and_spare_device()
        assert ctx["second_evaluation"]["status"] == "READY", "the event must start READY"

        _file_outage_on(ctx["dev1"]["id"])

        event = get_success_data(api_client.get_test_event(ctx["event_id"], ADMIN))
        assert event["status"] == "READINESS_PENDING", (
            f"hop 4 must revert the READY event, got {event['status']}"
        )
        assert event["readiness_score"] is None, "hop 4 clears readiness_score"
        assert event["readiness_evaluated_at"] is None, "hop 4 clears readiness_evaluated_at"


# ---------------------------------------------------------------------------
# The plan-supersede cascade — three hops out of one activation
# ---------------------------------------------------------------------------
def _station_with_two_inspections_and_a_draft_successor():
    """Plan p1 governing a fully covered station, one RESPONDED inspection request, one
    CLOSED_SATISFIED inspection request, and a DRAFT successor plan for the same state."""
    p1 = create_active_plan(("PEP",), ())
    station = register_station(p1["id"])
    dev1 = create_ready_device(station["id"])
    assign_source(
        station["id"], dev1["id"], source_type="PEP", source_call_sign=SOURCE_CALL_SIGNS["PEP"]
    )
    responded = setup_responded_inspection(station["id"], ["STATION_LOG", "TEST_LOGS"])
    closed = setup_closed_inspection(station["id"], ["PLAN_COPY"])
    p2 = create_plan(
        ("PEP", "NWS"),
        ("EAN",),
        state_code=TEST_DEFAULTS["STATE_CODE"],
        plan_version_label=TEST_DEFAULTS["SUCCESSOR_PLAN_LABEL"],
    )
    return {
        "p1": p1,
        "p2": p2,
        "station_id": station["id"],
        "responded": responded,
        "closed": closed,
    }


def _activate(plan_id):
    return validate_success(api_client.activate_state_plan(plan_id, ADMIN), 200)


class TestPlanSupersedeCascade:
    """Activating a successor plan reaches an entity two foreign keys away."""

    def test_activation_supersedes_the_prior_active_plan_for_the_state(self):
        """PRD §2.11: "Hop 1 is caused by the activation: every *other* `StatePlan` with the same `state_code` whose status is `ACTIVE` transitions `ACTIVE` → `SUPERSEDED` and has its `superseded_at` stamped from the logical clock."
        PRD §3.1: "Activation stamps `activated_at` from the logical clock and then fires the plan-supersede cascade described in §2.11: any other plan for the same `state_code` sitting in `ACTIVE` is pushed `ACTIVE` → `SUPERSEDED`, its `superseded_at` is stamped, its stations get `plan_revalidation_required` set to true and rescored, and any `RESPONDED` inspection request of those stations falls back to `RESPONSE_DRAFTED`."
        PRD §3.1: "At create time the server derives `required_source_count` as the number of entries in `required_source_types`, sets `status` to `DRAFT`, and leaves both `activated_at` and `superseded_at` null."

        Design: Difficulty/transitive_cascade/plan_supersede_cascades_three_levels_and_reverts_only_non_terminal_inspections
        """
        ctx = _station_with_two_inspections_and_a_draft_successor()

        successor = _activate(ctx["p2"]["id"])

        assert successor["status"] == "ACTIVE"
        assert _instant(successor["activated_at"]) == _instant(CLOCK_AT_STARTUP)
        assert successor["required_source_count"] == 2

        predecessor = get_success_data(api_client.get_state_plan(ctx["p1"]["id"], ADMIN))
        assert predecessor["status"] == "SUPERSEDED", (
            f"hop 1 must supersede the prior ACTIVE plan, got {predecessor['status']}"
        )
        assert _instant(predecessor["superseded_at"]) == _instant(CLOCK_AT_STARTUP)

    def test_supersede_flags_station_revalidation_and_rescores_it(self):
        """PRD §2.11: "Hop 2 is caused by that row becoming `SUPERSEDED`, not by the activate call itself: every `Station` whose `state_plan_id` points at the now-superseded plan sets `plan_revalidation_required` to true and re-runs the station scoring, which moves `compliance_posture` per the bands."
        PRD §3.8: "a flat 15.00 points when `plan_revalidation_required` is true, and nothing when it is false;"
        PRD §2.10: "The band mapping is: a score of 90.00 or greater yields `COMPLIANT`; a score of at least 75.00 but below 90.00 yields `WATCH`; anything below 75.00 yields `SUSPENDED_FILINGS`."
        PRD §2.11: "The `plan_revalidation_required` flag, once true, is cleared only by re-pointing the station at a plan whose status is `ACTIVE`; no recompute event clears it on its own, so it keeps costing the station its revalidation deduction until the station's plan reference is corrected."

        Design: Difficulty/transitive_cascade/plan_supersede_cascades_three_levels_and_reverts_only_non_terminal_inspections
        """
        ctx = _station_with_two_inspections_and_a_draft_successor()
        before = station_summary(ctx["station_id"])
        assert before["plan_revalidation_required"] is False
        assert before["compliance_score"] == pytest.approx(100.00, abs=0.01)

        _activate(ctx["p2"]["id"])

        summary = station_summary(ctx["station_id"])
        assert summary["plan_revalidation_required"] is True, "hop 2 must raise the flag"
        assert summary["compliance_score"] == pytest.approx(85.00, abs=0.01), (
            "100.00 - 15.00; the flag must be set before the recompute reads it"
        )
        assert summary["compliance_posture"] == "WATCH", "85.00 is at least 75.00 and below 90.00"
        assert summary["required_source_count"] == 1, (
            "the station still points at the superseded plan, whose required_source_count is 1"
        )
        assert summary["missing_source_count"] == 0
        assert summary["accessible_source_count"] == 1

    def test_supersede_reverts_the_responded_inspection_keeping_provided_kinds(self):
        """PRD §2.11: "Hop 3 is caused by hop 2's flag flipping from false to true: every `InspectionRequest` of that station whose status is `RESPONDED` reverts to `RESPONSE_DRAFTED`, with `completeness_score` and `responded_at` cleared to null and `provided_document_kinds` deliberately retained so the station can re-attest against the new plan."
        PRD §3.9: "The `response_due_at` deadline is not extended by that revert."

        Design: Difficulty/transitive_cascade/plan_supersede_cascades_three_levels_and_reverts_only_non_terminal_inspections
        """
        ctx = _station_with_two_inspections_and_a_draft_successor()
        responded = ctx["responded"]
        assert responded["status"] == "RESPONDED", "the request must start RESPONDED"
        assert responded["completeness_score"] == pytest.approx(100.00, abs=0.01)

        _activate(ctx["p2"]["id"])

        reverted = get_success_data(
            api_client.get_inspection_request(responded["id"], INSPECTOR)
        )
        assert reverted["status"] == "RESPONSE_DRAFTED", (
            f"hop 3 must rewind the RESPONDED request, got {reverted['status']}"
        )
        assert reverted["completeness_score"] is None
        assert reverted["responded_at"] is None
        assert sorted(reverted["provided_document_kinds"]) == ["STATION_LOG", "TEST_LOGS"], (
            "provided_document_kinds is deliberately retained across the revert"
        )
        assert _instant(reverted["requested_at"]) == _instant(CLOCK_AT_STARTUP)
        assert _instant(reverted["response_due_at"]) == _instant(INSPECTION_DUE_AT), (
            "the seven-day response deadline is not extended by the revert"
        )

    def test_supersede_leaves_the_closed_inspection_untouched(self):
        """PRD §2.11: "Hop 3 is caused by hop 2's flag flipping from false to true: every `InspectionRequest` of that station whose status is `RESPONDED` reverts to `RESPONSE_DRAFTED`, with `completeness_score` and `responded_at` cleared to null and `provided_document_kinds` deliberately retained so the station can re-attest against the new plan."
        PRD §3.9: "a `completeness_score` of 100.00 or greater closes the request `RESPONDED` → `CLOSED_SATISFIED`, and anything below 100.00 closes it `RESPONDED` → `CLOSED_DEFICIENT`."
        PRD §3.9: "Both closed statuses are terminal."

        Design: Difficulty/transitive_cascade/plan_supersede_cascades_three_levels_and_reverts_only_non_terminal_inspections
        """
        ctx = _station_with_two_inspections_and_a_draft_successor()
        closed = ctx["closed"]
        assert closed["status"] == "CLOSED_SATISFIED", (
            "a full, on-time response scores 100.00 and closes satisfied"
        )

        _activate(ctx["p2"]["id"])

        reread = get_success_data(api_client.get_inspection_request(closed["id"], INSPECTOR))
        assert reread["status"] == "CLOSED_SATISFIED", (
            "hop 3 is conditional on RESPONDED; a terminal request is left alone"
        )
        assert reread["completeness_score"] == pytest.approx(100.00, abs=0.01)
        assert reread["responded_at"] is not None, "the terminal row keeps its responded_at"
