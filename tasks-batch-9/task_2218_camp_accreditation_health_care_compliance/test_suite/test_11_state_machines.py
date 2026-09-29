"""Every declared machine walked on its own edges: the licensing axis, the initial state
of nine freshly created rows, the from-state preconditions of the visit and annual-report
triggers, the two supersede cascades, terminal lockdown, and clock-driven escalation."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_pct
from test_helpers.factories import (
    annual_report_review_payload,
    annual_report_submit_payload,
    correction_plan_payload,
    cycle_payload,
    standard_payload,
    visit_assignment_payload,
)
from test_helpers.test_users import (
    OFFICER_ONE_HEADERS,
    make_camp_director_headers,
    make_visitor_headers,
)
from test_helpers.types import (
    AccreditationStatus,
    AnnualReportDecision,
    AnnualReportStatus,
    AssignmentStatus,
    Certification,
    CompliancePosture,
    CycleStatus,
    DecisionLevel,
    DeficiencySeverity,
    DeficiencyStatus,
    HealthIntakeStatus,
    PlanType,
    SelfScore,
    SelfStatus,
    StandardDomain,
    StandardsSetStatus,
    StateLicenseStatus,
    TeamRole,
    VisitStatus,
    VisitStatusAxis,
    VisitorStatus,
    WrittenPlanStatus,
)
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)

SUPERVISION_ONLY = [
    fx.universal_mandatory_standard("SU.1", domain=StandardDomain.SUPERVISION, scoring_weight=1)
]

ESCALATION_STANDARDS = [
    fx.universal_mandatory_standard("SU.1", domain=StandardDomain.SUPERVISION, scoring_weight=5),
    fx.universal_mandatory_standard("SU.2", domain=StandardDomain.SUPERVISION, scoring_weight=5),
    fx.universal_mandatory_standard("SU.3", domain=StandardDomain.SUPERVISION, scoring_weight=5),
    fx.universal_mandatory_standard("SU.4", domain=StandardDomain.SUPERVISION, scoring_weight=4),
    fx.universal_optional_standard("OM.4", domain=StandardDomain.OPERATIONS, scoring_weight=1),
]

ESCALATION_MANDATORY = ("SU.1", "SU.2", "SU.3", "SU.4")

ESCALATION_TEAM = [
    {
        "key": "lead",
        "full_name": "Lead Visitor Esc",
        "home_state_code": "PA",
        "certifications": [Certification.LEAD_VISITOR],
        "team_role": TeamRole.LEAD,
    },
    {
        "key": "member",
        "full_name": "Member Visitor Esc",
        "home_state_code": "PA",
        "certifications": [],
        "team_role": TeamRole.MEMBER,
    },
]


def _one_row_of_every_kind(api):
    """Create a camp, edition, cycle, visitor, plan, visit, seat and annual report in order."""
    camp = fx.register_camp(api, name="Initial State Camp")
    edition = fx.create_edition(api, "ACA-2026-INIT")
    standard = fx.add_standard(
        api,
        edition["id"],
        code="SU.1",
        title="Supervision ratios",
        domain=StandardDomain.SUPERVISION,
        mandatory=True,
        scoring_weight=1,
    )
    draft_edition = dict(edition)
    fx.publish_edition(api, edition["id"])

    cycle = fx.open_cycle(api, camp["id"], edition["id"])
    evaluation = fx.evaluation_for_standard(api, cycle["id"], standard["id"], camp["id"])
    visitor = fx.add_visitor(api, "Ada Frost", "PA", 2026)
    plan = fx.file_plan(
        api,
        camp["id"],
        PlanType.SUPERVISION,
        body_ref="doc://sup-1",
        effective_date="2026-05-01",
        expires_at="2027-04-30",
    )
    visit = fx.open_visit(api, cycle["id"], "2026-08-03", "2026-08-07")
    seat = fx.seat_visitor(
        api, visit["id"], visitor["id"], TeamRole.LEAD, "2026-08-03", "2026-08-05"
    )
    report = fx.open_annual_report(api, camp["id"], 2025)
    return {
        "camp": camp,
        "draft_edition": draft_edition,
        "cycle": cycle,
        "evaluation": evaluation,
        "visitor": visitor,
        "plan": plan,
        "visit": visit,
        "seat": seat,
        "report": report,
    }


def _draft_visit_with_a_lead_seated(api):
    """A DRAFT visit whose window already contains the clock date, holding one LEAD seat."""
    edition, _standards = fx.publish_edition_with_standards(api, "ACA-2026-VP", SUPERVISION_ONLY)
    camp = fx.register_camp(api, name="Visit Precondition Camp")
    cycle = fx.open_cycle(api, camp["id"], edition["id"])
    visit = fx.open_visit(api, cycle["id"], "2026-08-01", "2026-08-07")
    visitor = fx.add_visitor(api, "Ida Bell", "PA", 2026)
    fx.seat_visitor(
        api, visit["id"], visitor["id"], TeamRole.LEAD, "2026-08-01", "2026-08-03"
    )
    return {"camp": camp, "cycle": cycle, "visit": visit, "visitor": visitor}


def _verified_plan_cited_by_a_verified_self_score(api):
    """A VERIFIED HEALTH_CARE plan cited by a submitted-and-verified self score."""
    edition, standards = fx.publish_edition_with_standards(
        api,
        "ACA-2026-SUP",
        [
            fx.universal_mandatory_standard(
                "HW.7",
                domain=StandardDomain.HEALTH_WELLNESS,
                scoring_weight=2,
                written_plan_type_required=PlanType.HEALTH_CARE,
            )
        ],
    )
    camp = fx.register_camp(api, name="Supersede Camp")
    plan_one = fx.file_plan(
        api,
        camp["id"],
        PlanType.HEALTH_CARE,
        body_ref="doc://hc-v1",
        effective_date="2026-05-01",
        expires_at="2027-04-30",
        physician_reviewed=True,
        as_health_care_staff=True,
    )
    fx.verify_plan(api, plan_one["id"], "physician signature on file")

    cycle = fx.open_cycle(api, camp["id"], edition["id"])
    evaluation = fx.evaluation_for_standard(
        api, cycle["id"], standards["HW.7"]["id"], camp["id"]
    )
    fx.record_self_score(
        api, evaluation["id"], camp["id"], SelfScore.MET, plan_one["id"], "plan attached"
    )
    fx.submit_self_assessment(api, cycle["id"], camp["id"])
    return {"camp": camp, "cycle": cycle, "evaluation": evaluation, "plan_one": plan_one}


def _cycle_with_a_draft_visit_and_one_seat(api, *, name: str, edition_code: str):
    """Cycle A for 2026 carrying a DRAFT visit with one three-day LEAD seat."""
    edition, _standards = fx.publish_edition_with_standards(api, edition_code, SUPERVISION_ONLY)
    camp = fx.register_camp(api, name=name)
    cycle_a = fx.open_cycle(api, camp["id"], edition["id"], 2026)
    visitor = fx.add_visitor(api, "Nora Vance", "PA", 2026)
    visit_a = fx.open_visit(api, cycle_a["id"], "2026-08-03", "2026-08-07")
    seat_a = fx.seat_visitor(
        api, visit_a["id"], visitor["id"], TeamRole.LEAD, "2026-08-03", "2026-08-05"
    )
    return {
        "camp": camp,
        "edition": edition,
        "cycle_a": cycle_a,
        "visitor": visitor,
        "visit_a": visit_a,
        "seat_a": seat_a,
    }


def _cascade_aftermath_with_an_inactive_visitor(api):
    """Cycle A TERMINATED and visit A RESCINDED by cycle B, plus a deactivated visitor."""
    edition, _standards = fx.publish_edition_with_standards(
        api, "ACA-2026-TL", SUPERVISION_ONLY
    )
    camp = fx.register_camp(api, name="Terminal Lockdown Camp")
    cycle_a = fx.open_cycle(api, camp["id"], edition["id"], 2026)
    visit_a = fx.open_visit(api, cycle_a["id"], "2026-08-03", "2026-08-07")
    cycle_b = fx.open_cycle(api, camp["id"], edition["id"], 2027)
    visit_b = fx.open_visit(api, cycle_b["id"], "2026-08-03", "2026-08-07")
    visitor = fx.add_visitor(api, "Kai Osei", "PA", 2026)
    fx.deactivate_visitor(api, visitor["id"], "left the visitor pool")
    return {
        "camp": camp,
        "cycle_a": cycle_a,
        "visit_a": visit_a,
        "cycle_b": cycle_b,
        "visit_b": visit_b,
        "visitor": visitor,
    }


def _accredited_cycle_holding_one_open_finding(api):
    """Four mandatory rows met and one optional row not met: ACCREDITED, IN_CORRECTION."""
    fx.reset_clock(api)
    scenario = fx.open_cycle_scenario(
        api,
        edition_code="ACA-2026-ESC",
        standards=ESCALATION_STANDARDS,
        camp={"name": "Escalation Camp"},
        self_scores={code: SelfScore.MET for code in ESCALATION_MANDATORY + ("OM.4",)},
        submit=True,
    )
    fx.seat_team(
        api,
        scenario,
        team=ESCALATION_TEAM,
        window=("2026-08-01", "2026-08-07"),
        travel=("2026-08-01", "2026-08-03"),
        confirm=True,
    )
    verdicts = {code: fx.ALL_MET_OBSERVED for code in ESCALATION_MANDATORY}
    verdicts["OM.4"] = fx.NOT_MET_OBSERVED
    # The clock stays on 2026-08-01, which is the first day of the agreed window.
    fx.score_visit(api, scenario, visitor_scores=verdicts, clock=None)
    return fx.decide_cycle(api, scenario)


def test_the_licence_axis_walks_five_edges_and_recomputes_the_gate_at_every_step(api):
    """PRD §3.1: "Every licensing write recomputes the compliance posture and the risk index
    and increments the camp's `version` by one, and none of them touches
    `accreditation_status`."

    Design: Corner/state_machines/state_license_axis_walks_every_declared_edge_and_recomputes_posture_each_step
    """
    camp = fx.register_camp(api, name="License Walk Camp")
    assert camp["state_license_status"] == StateLicenseStatus.NONE
    assert camp["version"] == 1

    pending = fx.move_state_license(
        api, camp["id"], StateLicenseStatus.PENDING, "OH-CAMP-10001"
    )
    assert pending["state_license_status"] == StateLicenseStatus.PENDING
    assert pending["state_license_number"] == "OH-CAMP-10001"
    assert pending["compliance_posture"] == CompliancePosture.RESTRICTED
    assert_pct(pending["risk_index"], 14.00)
    assert pending["version"] == 2

    active = fx.move_state_license(api, camp["id"], StateLicenseStatus.ACTIVE)
    assert active["state_license_status"] == StateLicenseStatus.ACTIVE
    assert active["compliance_posture"] == CompliancePosture.OPEN
    assert_pct(active["risk_index"], 10.00)
    assert active["version"] == 3

    probation = fx.move_state_license(api, camp["id"], StateLicenseStatus.PROBATION)
    assert probation["compliance_posture"] == CompliancePosture.RESTRICTED
    assert_pct(probation["risk_index"], 20.00)
    assert probation["version"] == 4

    suspended = fx.move_state_license(api, camp["id"], StateLicenseStatus.SUSPENDED)
    assert suspended["compliance_posture"] == CompliancePosture.FROZEN
    assert suspended["health_intake_status"] == HealthIntakeStatus.SUSPENDED
    assert_pct(suspended["risk_index"], 30.00)
    assert suspended["version"] == 5

    restored = fx.move_state_license(api, camp["id"], StateLicenseStatus.ACTIVE)
    assert restored["compliance_posture"] == CompliancePosture.OPEN
    assert restored["health_intake_status"] == HealthIntakeStatus.OPEN
    assert_pct(restored["risk_index"], 10.00)
    assert restored["version"] == 6

    # The accreditation axis never read the licensing axis.
    assert restored["accreditation_status"] == AccreditationStatus.NOT_ACCREDITED


def test_the_direct_activation_edge_and_the_probation_round_trip_stand_on_their_own(api):
    """PRD §3.1: "The permitted moves are `NONE → PENDING`, `PENDING → ACTIVE`,
    `NONE → ACTIVE`, `ACTIVE → PROBATION`, `ACTIVE → SUSPENDED`, `PROBATION → SUSPENDED`,
    `SUSPENDED → ACTIVE` and `PROBATION → ACTIVE`."

    Design: Corner/state_machines/state_license_axis_walks_every_declared_edge_and_recomputes_posture_each_step
    """
    camp = fx.register_camp(api, name="Direct Active Camp")

    active = fx.move_state_license(
        api, camp["id"], StateLicenseStatus.ACTIVE, "OH-CAMP-10002"
    )
    assert active["state_license_status"] == StateLicenseStatus.ACTIVE
    assert active["state_license_number"] == "OH-CAMP-10002"
    assert active["compliance_posture"] == CompliancePosture.OPEN
    assert active["version"] == 2

    probation = fx.move_state_license(api, camp["id"], StateLicenseStatus.PROBATION)
    assert probation["compliance_posture"] == CompliancePosture.RESTRICTED
    assert probation["version"] == 3

    reinstated = fx.move_state_license(api, camp["id"], StateLicenseStatus.ACTIVE)
    assert reinstated["compliance_posture"] == CompliancePosture.OPEN
    assert reinstated["version"] == 4
    assert reinstated["accreditation_status"] == AccreditationStatus.NOT_ACCREDITED


def test_the_cycle_evaluation_visitor_and_plan_open_in_their_declared_initial_states(api):
    """PRD §3.3: "The cycle opens in `SELF_ASSESSMENT` with `decision_level` null,
    `self_assessment_submitted_at` null, all three percentages null,
    `open_deficiency_count` 0, `assessed_fee_cents` null, `correction_deadline_at` null, and
    both `decision_issued_at` and `decision_issued_by_user_id` null."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    world = _one_row_of_every_kind(api)

    assert world["draft_edition"]["status"] == StandardsSetStatus.DRAFT
    assert world["camp"]["accreditation_status"] == AccreditationStatus.NOT_ACCREDITED
    assert world["camp"]["state_license_status"] == StateLicenseStatus.NONE
    assert world["camp"]["compliance_posture"] == CompliancePosture.OPEN

    cycle = world["cycle"]
    assert cycle["status"] == CycleStatus.SELF_ASSESSMENT
    assert cycle["decision_level"] is None
    assert cycle["self_assessment_submitted_at"] is None

    row = world["evaluation"]
    assert row["self_status"] == SelfStatus.DRAFT
    assert row["visit_status"] == VisitStatusAxis.UNSCORED
    assert row["self_score"] is None
    assert row["visitor_score"] is None
    assert row["visit_id"] is None

    visitor = world["visitor"]
    assert visitor["status"] == VisitorStatus.ACTIVE
    assert visitor["committed_travel_days"] == 0

    plan = world["plan"]
    assert plan["status"] == WrittenPlanStatus.SUBMITTED
    assert plan["verified_at"] is None
    assert plan["supersedes_plan_id"] is None


def test_the_visit_seat_and_annual_report_open_in_their_declared_initial_states(api):
    """PRD §3.5: "A new visit begins in `DRAFT` with `lead_visitor_id` null, `team_size` 0,
    `mandatory_scored_count` and `mandatory_met_count` at 0, `provisional_mandatory_pct`
    null, `scheduled_by_user_id` null and `scored_at` null."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    world = _one_row_of_every_kind(api)

    visit = world["visit"]
    assert visit["status"] == VisitStatus.DRAFT
    assert visit["lead_visitor_id"] is None
    assert visit["team_size"] == 0
    assert visit["required_specialist_domains"] == []
    assert visit["scheduled_by_user_id"] is None

    seat = world["seat"]
    assert seat["status"] == AssignmentStatus.ASSIGNED
    assert seat["travel_days"] == 3
    seated_visit = fx.read_visit(api, visit["id"])
    assert seated_visit["lead_visitor_id"] == world["visitor"]["id"]
    assert seated_visit["team_size"] == 1

    report = world["report"]
    assert report["status"] == AnnualReportStatus.DRAFT
    assert report["due_date"] == "2026-03-01"
    assert report["declared_incident_count"] == 0
    assert report["disclosed_incident_count"] == 0
    assert report["reopen_count"] == 0


def test_start_and_finalize_both_refuse_a_draft_visit_on_the_same_state_error(api):
    """PRD §3.6: "The visit must be `SCHEDULED` (`ERR_VISIT_INVALID_STATE`), the camp's
    posture must not be `FROZEN` (`ERR_CAMP_POSTURE_FROZEN`), and the logical clock's
    calendar date must fall inside the agreed window counting both endpoints, or the request
    is refused with `ERR_OUTSIDE_VISIT_WINDOW` (HTTP 422)."

    Design: Corner/state_machines/visit_lifecycle_triggers_enforce_their_from_state_preconditions
    """
    world = _draft_visit_with_a_lead_seated(api)
    lead_headers = make_visitor_headers(world["visitor"]["id"])

    validate_error(
        api.start_visit(world["visit"]["id"], lead_headers),
        ApiErrorId.VISIT_INVALID_STATE,
        409,
    )
    validate_error(
        api.finalize_scoring(world["visit"]["id"], lead_headers),
        ApiErrorId.VISIT_INVALID_STATE,
        409,
    )

    visit = fx.read_visit(api, world["visit"]["id"])
    assert visit["status"] == VisitStatus.DRAFT
    assert visit["scored_at"] is None
    assert fx.read_cycle(api, world["cycle"]["id"])["status"] == CycleStatus.SELF_ASSESSMENT

    _rows, meta = fx.list_deficiencies_for_visit(api, world["visit"]["id"])
    assert meta["total_count"] == 0


def test_annual_report_review_and_submit_are_refused_outside_their_source_states(api):
    """PRD §3.9: "An `AccreditationOfficer` then adjudicates with a `decision` of `ACCEPT` or
    `REJECT` and an optional `reviewer_note`; both `SUBMITTED` and `LATE` are reviewable,
    `ACCEPT` moves the report to `ACCEPTED` and `REJECT` moves it to `REJECTED`, and a
    rejected report may be filed again."

    Design: Corner/state_machines/annual_report_submit_and_review_outside_the_current_status_are_rejected
    """
    fx.set_clock(api, "2026-02-01T00:00:00Z")
    camp = fx.register_camp(api, name="Report State Camp")
    report = fx.open_annual_report(api, camp["id"], 2025)
    director = make_camp_director_headers(camp["id"])
    assert report["status"] == AnnualReportStatus.DRAFT
    assert report["due_date"] == "2026-03-01"

    validate_error(
        api.review_annual_report(
            report["id"],
            annual_report_review_payload(AnnualReportDecision.ACCEPT),
            OFFICER_ONE_HEADERS,
        ),
        ApiErrorId.ANNUAL_REPORT_INVALID_STATE,
        409,
    )

    submitted = fx.file_annual_report(api, camp["id"], report["id"], 0)
    assert submitted["status"] == AnnualReportStatus.SUBMITTED
    assert is_iso8601_timestamp(submitted["submitted_at"])
    assert submitted["submitted_at"].startswith("2026-02-01T00:00:00")
    assert submitted["attested_by_user_id"] == camp["id"]

    validate_error(
        api.submit_annual_report(report["id"], annual_report_submit_payload(0), director),
        ApiErrorId.ANNUAL_REPORT_INVALID_STATE,
        409,
    )

    accepted = fx.review_annual_report(
        api, report["id"], AnnualReportDecision.ACCEPT, "clean season"
    )
    assert accepted["status"] == AnnualReportStatus.ACCEPTED

    validate_error(
        api.review_annual_report(
            report["id"],
            annual_report_review_payload(AnnualReportDecision.REJECT),
            OFFICER_ONE_HEADERS,
        ),
        ApiErrorId.ANNUAL_REPORT_INVALID_STATE,
        409,
    )
    assert fx.read_annual_report(api, report["id"])["reopen_count"] == 0


def test_publication_is_not_idempotent_and_seals_the_edition_against_new_standards(api):
    """PRD §3.2: "Adding a standard to an edition that is `PUBLISHED` or `RETIRED` is
    rejected with `ERR_STANDARDS_SET_ALREADY_PUBLISHED` (HTTP 409), and so is an attempt to
    publish an edition that is not `DRAFT`."

    Design: Corner/state_machines/second_publish_and_post_publish_standard_addition_are_rejected
    """
    edition = fx.create_edition(api, "ACA-2026-IDEM")
    fx.add_standard(
        api,
        edition["id"],
        code="SU.1",
        title="Supervision ratios",
        domain=StandardDomain.SUPERVISION,
        mandatory=True,
        scoring_weight=1,
    )

    published = fx.publish_edition(api, edition["id"])
    assert published["status"] == StandardsSetStatus.PUBLISHED
    assert is_iso8601_timestamp(published["published_at"])
    assert published["published_at"].startswith("2026-08-01T00:00:00")

    validate_error(
        api.publish_standards_set(edition["id"], OFFICER_ONE_HEADERS),
        ApiErrorId.STANDARDS_SET_ALREADY_PUBLISHED,
        409,
    )
    assert fx.read_edition(api, edition["id"])["published_at"] == published["published_at"]

    validate_error(
        api.create_standard(
            standard_payload(
                edition["id"],
                code="OM.9",
                title="Late addition",
                domain=StandardDomain.OPERATIONS,
                mandatory=False,
                scoring_weight=1,
            ),
            OFFICER_ONE_HEADERS,
        ),
        ApiErrorId.STANDARDS_SET_ALREADY_PUBLISHED,
        409,
    )

    sealed = fx.read_edition(api, edition["id"])
    assert sealed["standard_count"] == 1
    assert sealed["mandatory_count"] == 1


def test_a_cycle_cannot_pin_a_draft_edition_but_the_identical_request_lands_after_publish(api):
    """PRD §3.3: "If the named edition's `status` is not `PUBLISHED`, the request is rejected
    with `ERR_STANDARDS_SET_NOT_PUBLISHED` (HTTP 409)."

    Design: Corner/state_machines/cycle_creation_against_a_draft_edition_is_rejected_until_it_is_published
    """
    camp = fx.register_camp(api, name="Draft Edition Camp")
    edition = fx.create_edition(api, "ACA-2026-DRAFT")
    fx.add_standard(
        api,
        edition["id"],
        code="SU.1",
        title="Supervision ratios",
        domain=StandardDomain.SUPERVISION,
        mandatory=True,
        scoring_weight=4,
    )
    fx.add_standard(
        api,
        edition["id"],
        code="OM.4",
        title="Operations records",
        domain=StandardDomain.OPERATIONS,
        mandatory=False,
        scoring_weight=1,
    )

    pinned_version = fx.read_camp(api, camp["id"])["version"]
    request = cycle_payload(camp["id"], edition["id"], pinned_version, 2026)

    validate_error(
        api.create_cycle(request, OFFICER_ONE_HEADERS),
        ApiErrorId.STANDARDS_SET_NOT_PUBLISHED,
        409,
    )
    _rows, meta = validate_paginated(
        api.list_cycles({"camp_id": camp["id"]}, OFFICER_ONE_HEADERS)
    )
    assert meta["total_count"] == 0
    assert fx.read_camp(api, camp["id"])["version"] == pinned_version

    fx.publish_edition(api, edition["id"])

    # The very same body, carrying the very same expected_camp_version, now lands.
    cycle = validate_success(api.create_cycle(request, OFFICER_ONE_HEADERS), 201)
    assert cycle["status"] == CycleStatus.SELF_ASSESSMENT
    assert cycle["applicable_standard_count"] == 2
    assert cycle["applicable_mandatory_count"] == 1


def test_filing_a_newer_plan_supersedes_the_old_one_and_rejects_the_citing_self_score(api):
    """PRD §3.4: "The prior plan of that type moves to `SUPERSEDED` — from `SUBMITTED`, from
    `VERIFIED`, from `REVALIDATION_REQUIRED` or from `REJECTED` alike — and the new plan's
    `supersedes_plan_id` is set to the retired plan's `id`."

    Design: Corner/state_machines/written_plan_supersede_chain_sets_the_pointer_and_knocks_the_citing_evaluation_to_rejected
    """
    world = _verified_plan_cited_by_a_verified_self_score(api)
    plan_one = world["plan_one"]
    verified_at = fx.read_plan(api, plan_one["id"])["verified_at"]
    assert fx.read_evaluation(api, world["evaluation"]["id"])["self_status"] == SelfStatus.VERIFIED

    plan_two = fx.file_plan(
        api,
        world["camp"]["id"],
        PlanType.HEALTH_CARE,
        body_ref="doc://hc-v2",
        effective_date="2026-08-01",
        expires_at="2027-07-31",
        physician_reviewed=True,
        as_health_care_staff=True,
    )
    assert plan_two["status"] == WrittenPlanStatus.SUBMITTED
    assert plan_two["verified_at"] is None
    assert plan_two["supersedes_plan_id"] == plan_one["id"]

    retired = fx.read_plan(api, plan_one["id"])
    assert retired["status"] == WrittenPlanStatus.SUPERSEDED
    assert retired["verified_at"] == verified_at

    row = fx.read_evaluation(api, world["evaluation"]["id"])
    assert row["self_status"] == SelfStatus.REJECTED
    # Only the status dimension moved: the citation and the camp's own verdict stand.
    assert row["written_plan_id"] == plan_one["id"]
    assert row["self_score"] == SelfScore.MET
    assert row["visit_status"] == VisitStatusAxis.UNSCORED

    cycle = fx.read_cycle(api, world["cycle"]["id"])
    assert cycle["status"] == CycleStatus.SELF_ASSESSMENT
    assert cycle["self_assessment_submitted_at"].startswith("2026-08-01T00:00:00")


def test_opening_a_second_cycle_terminates_the_first_and_rescinds_its_draft_visit(api):
    """PRD §3.3: "Opening a cycle terminates any prior cycle of the same camp still sitting
    in `SELF_ASSESSMENT`, moving it `SELF_ASSESSMENT → TERMINATED`."

    Design: Corner/state_machines/cycle_supersede_cascade_terminates_the_prior_cycle_and_rescinds_its_draft_visit
    """
    world = _cycle_with_a_draft_visit_and_one_seat(
        api, name="Supersede Cycle Camp", edition_code="ACA-2026-SC"
    )
    assert fx.read_visitor(api, world["visitor"]["id"])["committed_travel_days"] == 3

    cycle_b = fx.open_cycle(api, world["camp"]["id"], world["edition"]["id"], 2027)
    assert cycle_b["status"] == CycleStatus.SELF_ASSESSMENT
    assert cycle_b["applicable_standard_count"] == 1

    cycle_a = fx.read_cycle(api, world["cycle_a"]["id"])
    assert cycle_a["status"] == CycleStatus.TERMINATED
    assert cycle_a["decision_level"] is None

    visit_a = fx.read_visit(api, world["visit_a"]["id"])
    assert visit_a["status"] == VisitStatus.RESCINDED
    assert visit_a["team_size"] == 0
    assert visit_a["lead_visitor_id"] is None

    seat_a = fx.read_assignment(api, world["seat_a"]["id"])
    assert seat_a["status"] == AssignmentStatus.WITHDRAWN
    assert seat_a["travel_days"] == 3
    assert fx.read_visitor(api, world["visitor"]["id"])["committed_travel_days"] == 0

    _rows, meta = validate_paginated(
        api.list_evaluations({"cycle_id": world["cycle_a"]["id"]}, OFFICER_ONE_HEADERS)
    )
    assert meta["total_count"] == 1
    for untouched in _rows:
        assert untouched["self_status"] == SelfStatus.DRAFT
        assert untouched["visit_status"] == VisitStatusAxis.UNSCORED


def test_terminated_cycles_rescinded_visits_and_inactive_visitors_absorb_every_trigger(api):
    """PRD §3.5: "Deactivating a visitor who is already `INACTIVE` is rejected with
    `ERR_VISITOR_INACTIVE` (HTTP 409)."

    Design: Corner/state_machines/terminal_rows_reject_every_further_trigger_after_a_supersede_cascade
    """
    world = _cascade_aftermath_with_an_inactive_visitor(api)
    director = make_camp_director_headers(world["camp"]["id"])

    validate_error(
        api.submit_self_assessment(world["cycle_a"]["id"], director),
        ApiErrorId.CYCLE_NOT_IN_SELF_ASSESSMENT,
        409,
    )
    validate_error(
        api.schedule_visit(world["visit_a"]["id"], OFFICER_ONE_HEADERS),
        ApiErrorId.VISIT_INVALID_STATE,
        409,
    )
    validate_error(
        api.deactivate_visitor(
            world["visitor"]["id"], {"deactivated_reason": "second attempt"}, OFFICER_ONE_HEADERS
        ),
        ApiErrorId.VISITOR_INACTIVE,
        409,
    )
    validate_error(
        api.create_visit_assignment(
            visit_assignment_payload(
                world["visit_b"]["id"],
                world["visitor"]["id"],
                TeamRole.LEAD,
                "2026-08-03",
                "2026-08-05",
            ),
            OFFICER_ONE_HEADERS,
        ),
        ApiErrorId.VISITOR_INACTIVE,
        409,
    )

    visitor = fx.read_visitor(api, world["visitor"]["id"])
    assert visitor["status"] == VisitorStatus.INACTIVE
    assert visitor["deactivated_reason"] == "left the visitor pool"

    visit_b = fx.read_visit(api, world["visit_b"]["id"])
    assert visit_b["team_size"] == 0
    assert visit_b["lead_visitor_id"] is None


def test_a_camp_can_be_accredited_while_one_non_mandatory_finding_stays_open(api):
    """PRD §3.7: "otherwise a cycle whose `open_deficiency_count` is greater than zero moves
    `VISIT_COMPLETED → IN_CORRECTION`, and a cycle with no open findings moves
    `VISIT_COMPLETED → CLOSED`."

    Design: Corner/state_machines/clock_advance_past_a_correction_due_date_escalates_the_deficiency_terminates_the_cycle_and_revokes_the_camp
    """
    scenario = _accredited_cycle_holding_one_open_finding(api)

    assert len(scenario.deficiencies) == 1
    finding = scenario.deficiencies[0]
    assert finding["severity"] == DeficiencySeverity.SCORED
    assert finding["base_points"] == 2
    assert finding["penalty_points"] == 2
    assert finding["status"] == DeficiencyStatus.OPEN
    assert finding["correction_due_date"] == "2026-10-30"

    cycle = fx.read_cycle(api, scenario.cycle_id)
    assert_pct(cycle["final_mandatory_pct"], 100.00)
    # 19 of 20 applicable weight is exactly 95.00, which clears the correction threshold.
    assert_pct(cycle["final_weighted_pct"], 95.00)
    assert cycle["decision_level"] == DecisionLevel.ACCREDITED
    assert cycle["status"] == CycleStatus.IN_CORRECTION
    assert cycle["correction_deadline_at"] == "2026-10-30T23:59:59.999Z"
    assert cycle["assessed_fee_cents"] == 95000 + 5 * 350 + 6 * 18000

    camp = fx.read_camp(api, scenario.camp_id)
    assert camp["accreditation_status"] == AccreditationStatus.ACCREDITED
    assert camp["penalty_point_balance"] == 2
    assert camp["compliance_posture"] == CompliancePosture.OPEN
    # The loyalty counters move on the CLOSED branch only, and this cycle is IN_CORRECTION.
    assert camp["prior_accredited_cycle_count"] == 0
    assert camp["last_accredited_year"] is None


def test_one_clock_advance_escalates_the_finding_terminates_the_cycle_and_revokes_the_camp(api):
    """PRD §3.8: "When the new clock calendar date is strictly after a finding's
    `correction_due_date` on a cycle in `IN_CORRECTION`, and that finding's `status` is
    `OPEN` or `PLAN_ACCEPTED`, the finding moves to `ESCALATED`, the cycle moves
    `IN_CORRECTION → TERMINATED`, the camp's `accreditation_status` moves to `REVOKED` — from
    `ACCREDITED`, from `ACCREDITED_WITH_CORRECTION` or from `PROVISIONAL` alike — and the
    camp's `penalty_point_balance` and then posture are recomputed, landing on `FROZEN`."

    Design: Corner/state_machines/clock_advance_past_a_correction_due_date_escalates_the_deficiency_terminates_the_cycle_and_revokes_the_camp
    """
    scenario = _accredited_cycle_holding_one_open_finding(api)
    finding_id = scenario.deficiencies[0]["id"]

    advance = fx.set_clock(api, "2026-10-31T00:00:00Z")
    assert advance["current_utc"].startswith("2026-10-31T00:00:00")
    assert advance["escalated_deficiency_count"] == 1
    assert advance["terminated_cycle_count"] == 1

    assert fx.read_deficiency(api, finding_id)["status"] == DeficiencyStatus.ESCALATED

    cycle = fx.read_cycle(api, scenario.cycle_id)
    assert cycle["status"] == CycleStatus.TERMINATED
    assert cycle["decision_level"] == DecisionLevel.ACCREDITED

    camp = fx.read_camp(api, scenario.camp_id)
    assert camp["accreditation_status"] == AccreditationStatus.REVOKED
    assert camp["compliance_posture"] == CompliancePosture.FROZEN
    assert camp["health_intake_status"] == HealthIntakeStatus.SUSPENDED
    # ESCALATED stays inside the counted set, so the points never left the balance.
    assert camp["penalty_point_balance"] == 2

    validate_error(
        api.file_correction_plan(
            finding_id,
            correction_plan_payload("too late to matter"),
            make_camp_director_headers(scenario.camp_id),
        ),
        ApiErrorId.DEFICIENCY_INVALID_STATE,
        409,
    )
