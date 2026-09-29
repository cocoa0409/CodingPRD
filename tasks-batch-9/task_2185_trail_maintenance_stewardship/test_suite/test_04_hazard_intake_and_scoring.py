"""Condition reports: triage scoring, reassessment at disposition, and resolution."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_condition_report,
    create_report,
    disposition_report,
    observe_weather,
    read_report,
    read_segment,
    set_clock,
    setup_briefed_party,
    setup_registry,
    triage_report,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]


def _aged_wet_report():
    """Report triaged on day zero, then aged fourteen days onto a wet segment."""
    world = setup_registry()
    report = create_report(
        world["seg_id"],
        world["gen_id"],
        hazard_type="TREAD_EROSION",
        severity_class="MODERATE",
        description="Rutting below the switchback.",
    )
    world["report"] = triage_report(report["id"], "HIGH")
    world["report_id"] = report["id"]
    set_clock("2026-08-15T00:00:00.000Z")
    world["segment_after_rain"] = observe_weather(
        world["seg_id"], 0.72, "2026-08-14T22:00:00.000Z"
    )
    return world


def test_triage_scores_the_report_with_the_initial_triage_variant_only(api):
    """PRD 3.4: "The `INITIAL_TRIAGE` variant, used at triage, forces both the ageing bonus and the wet surcharge to 0 regardless of how old the report is or what posture the segment is in, so the triage score is a pure severity-by-exposure-by-traffic product."
    PRD 3.4: "The score begins from a severity base: 20 for `LOW`, 50 for `MODERATE`, 80 for `HIGH` and 100 for `CRITICAL`, read from the post-override `severity_class` stored on the report."
    PRD 3.4: "The exact product plus the two increments gives a raw figure, and only then is a single round-half-up to a whole number applied, with the result capped at 100."

    Design: Difficulty/dual_variant_calc/condition_report_initial_triage_vs_reassessed_priority_diverges
    """
    world = _aged_wet_report()

    assert world["report"]["priority_score"] == 63, (
        "50 base by 1.25 exposure by 1.00 traffic is 62.5, rounded half up to 63"
    )
    assert world["report"]["priority_variant"] == "INITIAL_TRIAGE"
    assert_condition_report(world["report"])
    assert world["segment_after_rain"]["posture"] == "WET_RESTRICTED"


def test_reassessed_disposition_score_blocks_the_defer_and_permits_the_escalate(api):
    """PRD 3.4: "The `REASSESSED` variant, used on every disposition regardless of which disposition is chosen, has both increments live."
    PRD 3.4: "The first is an ageing bonus: the whole number of days from the report's `created_at` to the logical clock, divided by seven and rounded down to whole weeks, multiplied by 3 points per completed week, and then capped at 15 points."
    PRD 3.4: "The second is a wet surcharge of 8 points, applied when and only when the segment's `posture` is `WET_RESTRICTED`, and 0 otherwise."
    PRD 3.4: "It requires a `defer_until_date` strictly after the logical clock date, and it requires the freshly reassessed `priority_score` to be strictly below the escalation threshold of 70; a report scoring 70 or higher is too urgent to park and is refused with `ERR_PRIORITY_TOO_HIGH_TO_DEFER`."
    PRD 3.4: "Escalation raises the segment's `escalated_hazard_count` by 1."

    Design: Difficulty/dual_variant_calc/condition_report_initial_triage_vs_reassessed_priority_diverges
    """
    world = _aged_wet_report()

    refused = api.disposition_condition_report(
        world["report_id"],
        {"disposition": "DEFER", "defer_until_date": "2026-10-01"},
        COORD,
    )
    validate_error(refused, ApiErrorId.ERR_PRIORITY_TOO_HIGH_TO_DEFER.value, 422)

    escalated = validate_success(
        api.disposition_condition_report(
            world["report_id"], {"disposition": "ESCALATE"}, COORD
        )
    )
    assert escalated["priority_score"] == 77, (
        "62.5 exact product plus 6 ageing points plus 8 wet points rounds to 77"
    )
    assert escalated["priority_variant"] == "REASSESSED"
    assert escalated["status"] == "ESCALATED"

    segment = read_segment(world["seg_id"])
    assert segment["escalated_hazard_count"] == 1
    assert segment["hazard_index"] == 39, "77 weighted by 1.5 is 115.5, divided by 3"


def test_priority_score_is_clamped_at_one_hundred(api):
    """PRD 3.4: "That base is multiplied by an exposure multiplier — 0.8 for `LOW` exposure, 1.0 for `MEDIUM`, 1.25 for `HIGH` — and then by a traffic multiplier read from `traffic_class_snapshot`: 0.9 for `LIGHT`, 1.0 for `MODERATE`, 1.15 for `HEAVY`."
    PRD 3.4: "The exact product plus the two increments gives a raw figure, and only then is a single round-half-up to a whole number applied, with the result capped at 100."
    PRD 3.4: "Triage also freezes the segment's current `traffic_class` onto the report as `traffic_class_snapshot`, so that a later edit to the segment cannot silently re-score a historical report."

    Design: Corner/calculations/condition_report_priority_score_clamped_at_one_hundred
    """
    world = setup_registry(segment_overrides={"traffic_class": "HEAVY"})
    report = create_report(
        world["seg_id"],
        world["gen_id"],
        hazard_type="BRIDGE_DAMAGE",
        severity_class="CRITICAL",
        description="Deck collapsed at the north abutment.",
    )

    triaged = validate_success(
        api.triage_condition_report(report["id"], {"exposure_class": "HIGH"}, COORD)
    )
    assert triaged["priority_score"] == 100, "143.75 must be clamped, not rounded to 144"
    assert triaged["priority_score"] != 144
    assert triaged["priority_variant"] == "INITIAL_TRIAGE"
    assert triaged["traffic_class_snapshot"] == "HEAVY"
    assert read_segment(world["seg_id"])["hazard_index"] == 33


def test_hazard_index_is_forced_to_one_hundred_at_the_second_escalation(api):
    """PRD 3.4: "Those weighted contributions are summed, the sum is divided by 3, and the quotient is rounded half up to a whole number and capped at 100 to give `hazard_index`."
    PRD 3.4: "Separately, `escalated_hazard_count` is set to the number of included reports sitting in `ESCALATED`; and if that count reaches 2 or more, `hazard_index` is forced to 100 outright — an override applied **after** the rounded value has been computed, not before."
    PRD 3.4: "A `hazard_index` of 60 or above is what drives the segment into `HAZARD_RESTRICTED`."

    Design: Corner/calculations/segment_hazard_index_forced_to_one_hundred_at_two_escalations
    """
    world = setup_registry(segment_overrides={"traffic_class": "HEAVY"})
    first = create_report(
        world["seg_id"],
        world["gen_id"],
        hazard_type="BRIDGE_DAMAGE",
        severity_class="MODERATE",
        description="Stringer checked through.",
    )
    triaged_first = triage_report(first["id"], "HIGH")
    second = create_report(
        world["seg_id"],
        world["gen_id"],
        hazard_type="TREAD_EROSION",
        severity_class="MODERATE",
        description="Undercut tread above the drop.",
    )
    assert triaged_first["priority_score"] == 72

    assert disposition_report(first["id"], "ESCALATE")["status"] == "ESCALATED"
    after_one = read_segment(world["seg_id"])
    assert after_one["hazard_index"] == 36
    assert after_one["escalated_hazard_count"] == 1
    assert after_one["posture"] == "OPEN"

    triaged_second = triage_report(second["id"], "HIGH")
    assert triaged_second["priority_score"] == 72
    mid = read_segment(world["seg_id"])
    assert mid["hazard_index"] == 60, "the 60 threshold is inclusive"
    assert mid["posture"] == "HAZARD_RESTRICTED"

    assert disposition_report(second["id"], "ESCALATE")["status"] == "ESCALATED"
    after_two = read_segment(world["seg_id"])
    assert after_two["hazard_index"] == 100
    assert after_two["hazard_index"] != 72
    assert after_two["escalated_hazard_count"] == 2
    assert after_two["posture"] == "HAZARD_RESTRICTED"


def test_escalation_below_the_threshold_is_refused(api):
    """PRD 3.4: "Escalating the report moves it `TRIAGED → ESCALATED` and is the mirror image: it requires the reassessed `priority_score` to be greater than or equal to 70, and a report scoring below that is refused with `ERR_PRIORITY_TOO_LOW_TO_ESCALATE`."

    Design: Corner/state_machines/escalate_disposition_below_threshold_is_refused
    """
    world = setup_registry()
    report = create_report(
        world["seg_id"],
        world["gen_id"],
        hazard_type="BRUSH_ENCROACHMENT",
        severity_class="MODERATE",
        description="Salmonberry closing the corridor.",
    )
    triaged = triage_report(report["id"], "MEDIUM")
    assert triaged["priority_score"] == 50

    response = api.disposition_condition_report(
        report["id"], {"disposition": "ESCALATE"}, COORD
    )
    validate_error(response, ApiErrorId.ERR_PRIORITY_TOO_LOW_TO_ESCALATE.value, 422)

    assert read_report(report["id"])["status"] == "TRIAGED"
    assert read_segment(world["seg_id"])["escalated_hazard_count"] == 0


def test_deferred_report_cannot_be_resolved_before_its_defer_date(api):
    """PRD 3.4: "A `DEFERRED` report may be resolved only once the logical clock date has reached or passed its `defer_until_date`; an earlier attempt is refused with `ERR_DEFER_DATE_NOT_REACHED`."
    PRD 3.4: "Each included report contributes its `priority_score` multiplied by a status weight: 1.0 for a report in `TRIAGED` or `SCHEDULED`, 0.5 for one in `DEFERRED`, and 1.5 for one in `ESCALATED`."

    Design: Corner/state_machines/deferred_condition_report_cannot_be_resolved_before_defer_date
    """
    world = setup_registry()
    report = create_report(
        world["seg_id"],
        world["gen_id"],
        hazard_type="SIGNAGE_MISSING",
        severity_class="MODERATE",
        description="Junction sign gone.",
    )
    triaged = triage_report(report["id"], "MEDIUM")
    assert triaged["priority_score"] == 50

    deferred = disposition_report(
        report["id"], "DEFER", defer_until_date="2026-10-01"
    )
    assert deferred["status"] == "DEFERRED"
    assert deferred["priority_score"] == 50
    assert deferred["priority_variant"] == "REASSESSED"

    response = api.resolve_condition_report(report["id"], COORD)
    validate_error(response, ApiErrorId.ERR_DEFER_DATE_NOT_REACHED.value, 409)

    assert read_report(report["id"])["status"] == "DEFERRED"
    assert read_segment(world["seg_id"])["hazard_index"] == 8


def test_scheduled_report_cannot_be_resolved_before_its_party_completes(api):
    """PRD 3.4: "A `SCHEDULED` report may be resolved by a `StewardshipCoordinator` only once its linked work party has reached `schedule_status` `COMPLETED`; otherwise the resolution is refused with `ERR_LINKED_PARTY_NOT_COMPLETE`."
    PRD 3.4: "The identifier is stored on the report and the party's `linked_report_count` rises by 1."

    Design: Corner/validations/scheduled_report_cannot_be_resolved_before_its_party_completes
    """
    world = setup_briefed_party()
    report = create_report(
        world["seg_id"],
        world["gen_id"],
        hazard_type="DRAINAGE_FAILURE",
        severity_class="MODERATE",
        description="Ditch line filled in.",
    )
    triage_report(report["id"], "MEDIUM")
    scheduled = disposition_report(
        report["id"], "SCHEDULE", linked_work_party_id=world["party_id"]
    )
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["linked_work_party_id"] == world["party_id"]

    response = api.resolve_condition_report(report["id"], COORD)
    validate_error(response, ApiErrorId.ERR_LINKED_PARTY_NOT_COMPLETE.value, 409)

    assert validate_success(
        api.get_work_party(world["party_id"], COORD)
    )["linked_report_count"] == 1
    assert read_report(report["id"])["status"] == "SCHEDULED"


def test_escalated_report_needs_a_material_order_before_a_coordinator_may_resolve_it(api):
    """PRD 3.4: "An `ESCALATED` report may be resolved either by a `SafetyOfficer`, or by a `StewardshipCoordinator` when a material order naming this report through its `condition_report_id` has reached `APPROVED` or `DELIVERED`; a coordinator with neither of those is refused with `ERR_ESCALATION_NOT_CLEARED`."
    PRD 3.4: "On success it moves `ESCALATED → RESOLVED`, `resolved_at` is stamped, and the segment's `escalated_hazard_count` drops by 1."

    Design: Corner/validations/escalated_report_cannot_be_resolved_by_coordinator_without_a_material_order
    """
    world = setup_registry(segment_overrides={"traffic_class": "HEAVY"})
    report = create_report(
        world["seg_id"],
        world["gen_id"],
        hazard_type="BRIDGE_DAMAGE",
        severity_class="MODERATE",
        description="Handrail sheared off.",
    )
    triaged = triage_report(report["id"], "HIGH")
    assert triaged["priority_score"] == 72
    assert disposition_report(report["id"], "ESCALATE")["status"] == "ESCALATED"

    refused = api.resolve_condition_report(report["id"], COORD)
    validate_error(refused, ApiErrorId.ERR_ESCALATION_NOT_CLEARED.value, 409)

    resolved = validate_success(api.resolve_condition_report(report["id"], SAFETY))
    assert resolved["status"] == "RESOLVED"

    segment = read_segment(world["seg_id"])
    assert segment["escalated_hazard_count"] == 0
    assert segment["hazard_index"] == 0
    assert segment["posture"] == "OPEN"
