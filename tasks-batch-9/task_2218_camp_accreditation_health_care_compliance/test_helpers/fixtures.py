"""Composite setup helpers that build accreditation preconditions from scratch.

Every helper drives the API through the endpoints the contract declares, so a
test starting against an empty database can reach any point in the workflow:
edition -> published standards -> registered camp -> open cycle -> self-assessed
cycle -> seated team -> confirmed visit -> scored visit -> issued decision ->
correction loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import validate_paginated, validate_success

from . import factories as f
from .api_client import ApiClient
from .constants import DEFAULT_CLOCK
from .test_users import (
    OFFICER_ONE_HEADERS,
    OFFICER_ONE_ID,
    OFFICER_TWO_HEADERS,
    STATE_AGENT_HEADERS,
    make_camp_director_headers,
    make_health_care_staff_headers,
    make_visitor_headers,
)
from .types import (
    Certification,
    PlanReviewDecision,
    ScoreSource,
    SelfScore,
    TeamRole,
    VisitorScore,
)

DEFAULT_WINDOW: Tuple[str, str] = ("2026-09-01", "2026-09-05")
DEFAULT_TRAVEL: Tuple[str, str] = ("2026-09-01", "2026-09-03")
IN_WINDOW_CLOCK = "2026-09-02T09:00:00Z"


# --------------------------------------------------------------------------
# Tier 1 - the logical clock
# --------------------------------------------------------------------------
def set_clock(api: ApiClient, to_iso8601: str, headers: Dict[str, str] = None) -> Dict[str, Any]:
    """Advance the logical clock and return the advance report."""
    return validate_success(api.set_clock(to_iso8601, headers or OFFICER_ONE_HEADERS))


def reset_clock(api: ApiClient) -> Dict[str, Any]:
    return set_clock(api, DEFAULT_CLOCK)


# --------------------------------------------------------------------------
# Tier 1 - reads
# --------------------------------------------------------------------------
def read_camp(api: ApiClient, camp_id: str, headers: Dict[str, str] = None) -> Dict[str, Any]:
    return validate_success(api.get_camp(camp_id, headers or OFFICER_ONE_HEADERS))


def read_risk_index(api: ApiClient, camp_id: str, headers: Dict[str, str] = None) -> Dict[str, Any]:
    return validate_success(api.get_camp_risk_index(camp_id, headers or OFFICER_ONE_HEADERS))


def read_edition(api: ApiClient, set_id: str, headers: Dict[str, str] = None) -> Dict[str, Any]:
    return validate_success(api.get_standards_set(set_id, headers or OFFICER_ONE_HEADERS))


def read_standard(api: ApiClient, standard_id: str, headers: Dict[str, str] = None) -> Dict[str, Any]:
    return validate_success(api.get_standard(standard_id, headers or OFFICER_ONE_HEADERS))


def read_cycle(api: ApiClient, cycle_id: str, headers: Dict[str, str] = None) -> Dict[str, Any]:
    return validate_success(api.get_cycle(cycle_id, headers or OFFICER_ONE_HEADERS))


def read_compliance_summary(
    api: ApiClient, cycle_id: str, headers: Dict[str, str] = None
) -> Dict[str, Any]:
    return validate_success(api.get_compliance_summary(cycle_id, headers or OFFICER_ONE_HEADERS))


def read_evaluation(
    api: ApiClient, evaluation_id: str, headers: Dict[str, str] = None
) -> Dict[str, Any]:
    return validate_success(api.get_evaluation(evaluation_id, headers or OFFICER_ONE_HEADERS))


def read_plan(api: ApiClient, plan_id: str, headers: Dict[str, str] = None) -> Dict[str, Any]:
    return validate_success(api.get_written_plan(plan_id, headers or OFFICER_ONE_HEADERS))


def read_visitor(api: ApiClient, visitor_id: str, headers: Dict[str, str] = None) -> Dict[str, Any]:
    return validate_success(api.get_visitor(visitor_id, headers or OFFICER_ONE_HEADERS))


def read_visit(api: ApiClient, visit_id: str, headers: Dict[str, str] = None) -> Dict[str, Any]:
    return validate_success(api.get_visit(visit_id, headers or OFFICER_ONE_HEADERS))


def read_assignment(
    api: ApiClient, assignment_id: str, headers: Dict[str, str] = None
) -> Dict[str, Any]:
    return validate_success(api.get_visit_assignment(assignment_id, headers or OFFICER_ONE_HEADERS))


def read_deficiency(
    api: ApiClient, deficiency_id: str, headers: Dict[str, str] = None
) -> Dict[str, Any]:
    return validate_success(api.get_deficiency(deficiency_id, headers or OFFICER_ONE_HEADERS))


def read_medication_record(
    api: ApiClient, record_id: str, headers: Dict[str, str] = None
) -> Dict[str, Any]:
    return validate_success(api.get_medication_record(record_id, headers or OFFICER_ONE_HEADERS))


def read_annual_report(
    api: ApiClient, report_id: str, headers: Dict[str, str] = None
) -> Dict[str, Any]:
    return validate_success(api.get_annual_report(report_id, headers or OFFICER_ONE_HEADERS))


def read_disclosure(
    api: ApiClient, disclosure_id: str, headers: Dict[str, str] = None
) -> Dict[str, Any]:
    return validate_success(api.get_incident_disclosure(disclosure_id, headers or OFFICER_ONE_HEADERS))


def list_deficiencies_for_visit(
    api: ApiClient, visit_id: str, headers: Dict[str, str] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return validate_paginated(
        api.list_deficiencies({"visit_id": visit_id}, headers or OFFICER_ONE_HEADERS)
    )


def list_seats_for_visitor(
    api: ApiClient, visitor_id: str, headers: Dict[str, str] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return validate_paginated(
        api.list_visit_assignments({"visitor_id": visitor_id}, headers or OFFICER_ONE_HEADERS)
    )


def list_seats_for_visit(
    api: ApiClient, visit_id: str, headers: Dict[str, str] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return validate_paginated(
        api.list_visit_assignments({"visit_id": visit_id}, headers or OFFICER_ONE_HEADERS)
    )


def list_medication_records_for_camp(
    api: ApiClient, camp_id: str, headers: Dict[str, str] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return validate_paginated(
        api.list_medication_records({"camp_id": camp_id}, headers or OFFICER_ONE_HEADERS)
    )


# --------------------------------------------------------------------------
# Tier 2 - single-entity creates
# --------------------------------------------------------------------------
def register_camp(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Register a camp as the national office and return the created row."""
    return validate_success(
        api.create_camp(f.camp_payload(**kwargs), OFFICER_ONE_HEADERS), 201
    )


def move_state_license(
    api: ApiClient,
    camp_id: str,
    state_license_status: str,
    state_license_number: Optional[str] = None,
) -> Dict[str, Any]:
    return validate_success(
        api.patch_state_license(
            camp_id,
            f.state_license_payload(state_license_status, state_license_number),
            STATE_AGENT_HEADERS,
        )
    )


def revise_health_center(api: ApiClient, camp_id: str, **kwargs: Any) -> Dict[str, Any]:
    return validate_success(
        api.patch_health_center(
            camp_id, f.health_center_payload(**kwargs), make_health_care_staff_headers(camp_id)
        )
    )


def receive_controlled_stock(api: ApiClient, camp_id: str, units: int) -> Dict[str, Any]:
    return revise_health_center(api, camp_id, controlled_intake_units_added=units)


def create_edition(
    api: ApiClient, edition_code: str, effective_year: int = 2026
) -> Dict[str, Any]:
    return validate_success(
        api.create_standards_set(
            f.standards_set_payload(edition_code, effective_year), OFFICER_ONE_HEADERS
        ),
        201,
    )


def add_standard(api: ApiClient, standards_set_id: str, **kwargs: Any) -> Dict[str, Any]:
    return validate_success(
        api.create_standard(f.standard_payload(standards_set_id, **kwargs), OFFICER_ONE_HEADERS),
        201,
    )


def publish_edition(api: ApiClient, set_id: str) -> Dict[str, Any]:
    return validate_success(api.publish_standards_set(set_id, OFFICER_ONE_HEADERS))


def publish_edition_with_standards(
    api: ApiClient,
    edition_code: str,
    standards: Sequence[Dict[str, Any]],
    effective_year: int = 2026,
) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    """Create a draft edition, add every standard in order, then publish it.

    Returns the published edition and the standards keyed by their ``code``.
    """
    edition = create_edition(api, edition_code, effective_year)
    created: Dict[str, Dict[str, Any]] = {}
    for spec in standards:
        standard = add_standard(api, edition["id"], **spec)
        created[standard["code"]] = standard
    edition = publish_edition(api, edition["id"])
    return edition, created


def open_cycle(
    api: ApiClient,
    camp_id: str,
    standards_set_id: str,
    cycle_year: int = 2026,
    expected_camp_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Open a cycle, pinning the camp version the caller supplies or the current one."""
    if expected_camp_version is None:
        expected_camp_version = read_camp(api, camp_id)["version"]
    return validate_success(
        api.create_cycle(
            f.cycle_payload(camp_id, standards_set_id, expected_camp_version, cycle_year),
            OFFICER_ONE_HEADERS,
        ),
        201,
    )


def file_plan(
    api: ApiClient,
    camp_id: str,
    plan_type: str,
    body_ref: str = "PLAN-2026-REV1",
    effective_date: str = "2026-05-01",
    expires_at: str = "2027-05-01",
    physician_reviewed: Optional[bool] = None,
    expected_camp_version: Optional[int] = None,
    as_health_care_staff: bool = False,
) -> Dict[str, Any]:
    """File a written plan for the camp, pinning the camp version."""
    if expected_camp_version is None:
        expected_camp_version = read_camp(api, camp_id)["version"]
    headers = (
        make_health_care_staff_headers(camp_id)
        if as_health_care_staff
        else make_camp_director_headers(camp_id)
    )
    return validate_success(
        api.create_written_plan(
            f.written_plan_payload(
                camp_id,
                plan_type,
                expected_camp_version,
                body_ref=body_ref,
                effective_date=effective_date,
                expires_at=expires_at,
                physician_reviewed=physician_reviewed,
            ),
            headers,
        ),
        201,
    )


def verify_plan(
    api: ApiClient, plan_id: str, verification_note: str = "plan accepted"
) -> Dict[str, Any]:
    return validate_success(
        api.review_written_plan(
            plan_id,
            f.plan_review_payload(PlanReviewDecision.VERIFY, verification_note),
            OFFICER_ONE_HEADERS,
        )
    )


def reject_plan(
    api: ApiClient, plan_id: str, verification_note: str = "plan rejected"
) -> Dict[str, Any]:
    return validate_success(
        api.review_written_plan(
            plan_id,
            f.plan_review_payload(PlanReviewDecision.REJECT, verification_note),
            OFFICER_ONE_HEADERS,
        )
    )


def add_visitor(
    api: ApiClient,
    full_name: str = "Lead One",
    home_state_code: str = "PA",
    trained_through_year: int = 2026,
    certifications: Optional[List[str]] = None,
    employer_camp_id: Optional[str] = None,
) -> Dict[str, Any]:
    return validate_success(
        api.create_visitor(
            f.visitor_payload(
                full_name=full_name,
                home_state_code=home_state_code,
                trained_through_year=trained_through_year,
                certifications=certifications,
                employer_camp_id=employer_camp_id,
            ),
            OFFICER_ONE_HEADERS,
        ),
        201,
    )


def deactivate_visitor(
    api: ApiClient, visitor_id: str, deactivated_reason: Optional[str] = None
) -> Dict[str, Any]:
    payload = {} if deactivated_reason is None else {"deactivated_reason": deactivated_reason}
    return validate_success(api.deactivate_visitor(visitor_id, payload, OFFICER_ONE_HEADERS))


def open_visit(
    api: ApiClient,
    cycle_id: str,
    window_start_date: str = DEFAULT_WINDOW[0],
    window_end_date: str = DEFAULT_WINDOW[1],
    expected_cycle_version: Optional[int] = None,
    scheduled_note: Optional[str] = None,
) -> Dict[str, Any]:
    """Open a draft visit, pinning the cycle version the caller supplies or the current one."""
    if expected_cycle_version is None:
        expected_cycle_version = read_cycle(api, cycle_id)["version"]
    return validate_success(
        api.create_visit(
            f.visit_payload(
                cycle_id,
                expected_cycle_version,
                window_start_date=window_start_date,
                window_end_date=window_end_date,
                scheduled_note=scheduled_note,
            ),
            OFFICER_ONE_HEADERS,
        ),
        201,
    )


def seat_visitor(
    api: ApiClient,
    visit_id: str,
    visitor_id: str,
    team_role: str,
    travel_block_start_date: str = DEFAULT_TRAVEL[0],
    travel_block_end_date: str = DEFAULT_TRAVEL[1],
) -> Dict[str, Any]:
    return validate_success(
        api.create_visit_assignment(
            f.visit_assignment_payload(
                visit_id,
                visitor_id,
                team_role,
                travel_block_start_date,
                travel_block_end_date,
            ),
            OFFICER_ONE_HEADERS,
        ),
        201,
    )


def withdraw_seat(
    api: ApiClient, assignment_id: str, withdrawal_reason: Optional[str] = None
) -> Dict[str, Any]:
    payload = {} if withdrawal_reason is None else {"withdrawal_reason": withdrawal_reason}
    return validate_success(
        api.withdraw_visit_assignment(assignment_id, payload, OFFICER_ONE_HEADERS)
    )


def confirm_visit(
    api: ApiClient, visit_id: str, headers: Dict[str, str] = None
) -> Dict[str, Any]:
    return validate_success(api.schedule_visit(visit_id, headers or OFFICER_ONE_HEADERS))


def open_scoring(api: ApiClient, visit_id: str, lead_visitor_id: str) -> Dict[str, Any]:
    return validate_success(api.start_visit(visit_id, make_visitor_headers(lead_visitor_id)))


def close_scoring(api: ApiClient, visit_id: str, lead_visitor_id: str) -> Dict[str, Any]:
    return validate_success(api.finalize_scoring(visit_id, make_visitor_headers(lead_visitor_id)))


def issue_decision(
    api: ApiClient, cycle_id: str, headers: Dict[str, str] = None
) -> Dict[str, Any]:
    """Issue the decision as the second officer, who did not confirm the visit."""
    return validate_success(api.issue_decision(cycle_id, headers or OFFICER_TWO_HEADERS))


# --------------------------------------------------------------------------
# Tier 3 - evaluation-row helpers
# --------------------------------------------------------------------------
def evaluation_for_standard(
    api: ApiClient, cycle_id: str, standard_id: str, camp_id: str
) -> Dict[str, Any]:
    """Find the evaluation row a cycle materialised for one standard."""
    rows, _ = validate_paginated(
        api.list_evaluations(
            {"cycle_id": cycle_id, "standard_id": standard_id},
            make_camp_director_headers(camp_id),
        )
    )
    assert rows, f"no evaluation row for standard {standard_id} on cycle {cycle_id}"
    return rows[0]


def evaluations_by_code(
    api: ApiClient,
    cycle_id: str,
    camp_id: str,
    standards: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Map each standard code to the evaluation row the cycle materialised for it."""
    return {
        code: evaluation_for_standard(api, cycle_id, standard["id"], camp_id)
        for code, standard in standards.items()
    }


def record_self_score(
    api: ApiClient,
    evaluation_id: str,
    camp_id: str,
    self_score: str,
    written_plan_id: Optional[str] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    return validate_success(
        api.patch_self_assessment(
            evaluation_id,
            f.self_assessment_payload(self_score, written_plan_id, note),
            make_camp_director_headers(camp_id),
        )
    )


def submit_self_assessment(api: ApiClient, cycle_id: str, camp_id: str) -> Dict[str, Any]:
    return validate_success(
        api.submit_self_assessment(cycle_id, make_camp_director_headers(camp_id))
    )


def record_visitor_score(
    api: ApiClient,
    evaluation_id: str,
    visitor_id: str,
    visitor_score: str,
    score_source: str,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    return validate_success(
        api.patch_visitor_score(
            evaluation_id,
            f.visitor_score_payload(visitor_score, score_source, note),
            make_visitor_headers(visitor_id),
        )
    )


# --------------------------------------------------------------------------
# Tier 4 - deficiency correction helpers
# --------------------------------------------------------------------------
def file_correction_plan(
    api: ApiClient, camp_id: str, deficiency_id: str, correction_plan_text: str
) -> Dict[str, Any]:
    return validate_success(
        api.file_correction_plan(
            deficiency_id,
            f.correction_plan_payload(correction_plan_text),
            make_camp_director_headers(camp_id),
        )
    )


def review_deficiency(
    api: ApiClient, deficiency_id: str, decision: str, reviewer_note: Optional[str] = None
) -> Dict[str, Any]:
    return validate_success(
        api.review_deficiency(
            deficiency_id,
            f.deficiency_review_payload(decision, reviewer_note),
            OFFICER_ONE_HEADERS,
        )
    )


# --------------------------------------------------------------------------
# Tier 4 - health centre and annual reporting helpers
# --------------------------------------------------------------------------
def administer_medication(api: ApiClient, camp_id: str, **kwargs: Any) -> Dict[str, Any]:
    return validate_success(
        api.create_medication_record(
            f.medication_record_payload(camp_id, **kwargs),
            make_health_care_staff_headers(camp_id),
        ),
        201,
    )


def void_medication_record(
    api: ApiClient, camp_id: str, record_id: str, void_reason: Optional[str] = None
) -> Dict[str, Any]:
    return validate_success(
        api.void_medication_record(
            record_id, f.void_payload(void_reason), make_health_care_staff_headers(camp_id)
        )
    )


def open_annual_report(api: ApiClient, camp_id: str, report_year: int = 2026) -> Dict[str, Any]:
    return validate_success(
        api.create_annual_report(
            f.annual_report_payload(camp_id, report_year), make_camp_director_headers(camp_id)
        ),
        201,
    )


def file_annual_report(
    api: ApiClient, camp_id: str, report_id: str, declared_incident_count: int
) -> Dict[str, Any]:
    return validate_success(
        api.submit_annual_report(
            report_id,
            f.annual_report_submit_payload(declared_incident_count),
            make_camp_director_headers(camp_id),
        )
    )


def review_annual_report(
    api: ApiClient, report_id: str, decision: str, reviewer_note: Optional[str] = None
) -> Dict[str, Any]:
    return validate_success(
        api.review_annual_report(
            report_id, f.annual_report_review_payload(decision, reviewer_note), OFFICER_ONE_HEADERS
        )
    )


def disclose_incident(
    api: ApiClient, camp_id: str, annual_report_id: str, incident_type: str, occurred_at: str
) -> Dict[str, Any]:
    return validate_success(
        api.create_incident_disclosure(
            f.incident_disclosure_payload(annual_report_id, incident_type, occurred_at),
            make_camp_director_headers(camp_id),
        ),
        201,
    )


# --------------------------------------------------------------------------
# Tier 5 - whole-workflow composites
# --------------------------------------------------------------------------
@dataclass
class Scenario:
    """Everything one accreditation storyline needs, refreshed as it advances."""

    edition: Dict[str, Any]
    standards: Dict[str, Dict[str, Any]]
    camp: Dict[str, Any]
    cycle: Dict[str, Any]
    evaluations: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    visitors: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    visit: Optional[Dict[str, Any]] = None
    assignments: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    deficiencies: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def camp_id(self) -> str:
        return self.camp["id"]

    @property
    def cycle_id(self) -> str:
        return self.cycle["id"]

    @property
    def visit_id(self) -> str:
        assert self.visit is not None
        return self.visit["id"]

    @property
    def director_headers(self) -> Dict[str, str]:
        return make_camp_director_headers(self.camp_id)

    @property
    def health_staff_headers(self) -> Dict[str, str]:
        return make_health_care_staff_headers(self.camp_id)

    def evaluation_id(self, code: str) -> str:
        return self.evaluations[code]["id"]

    def visitor_id(self, key: str) -> str:
        return self.visitors[key]["id"]

    def assignment_id(self, key: str) -> str:
        return self.assignments[key]["id"]

    def refresh(self, api: ApiClient) -> "Scenario":
        self.camp = read_camp(api, self.camp_id)
        self.cycle = read_cycle(api, self.cycle_id)
        self.evaluations = {
            code: read_evaluation(api, row["id"]) for code, row in self.evaluations.items()
        }
        self.visitors = {
            key: read_visitor(api, row["id"]) for key, row in self.visitors.items()
        }
        if self.visit is not None:
            self.visit = read_visit(api, self.visit_id)
        self.assignments = {
            key: read_assignment(api, row["id"]) for key, row in self.assignments.items()
        }
        return self


DEFAULT_TEAM: List[Dict[str, Any]] = [
    {
        "key": "lead",
        "full_name": "Lead One",
        "home_state_code": "PA",
        "certifications": [Certification.LEAD_VISITOR],
        "team_role": TeamRole.LEAD,
    },
    {
        "key": "member",
        "full_name": "Member Two",
        "home_state_code": "NY",
        "certifications": [],
        "team_role": TeamRole.MEMBER,
    },
]


def open_cycle_scenario(
    api: ApiClient,
    *,
    edition_code: str,
    standards: Sequence[Dict[str, Any]],
    camp: Dict[str, Any],
    cycle_year: int = 2026,
    effective_year: int = 2026,
    self_scores: Optional[Dict[str, str]] = None,
    submit: bool = False,
) -> Scenario:
    """Publish an edition, register a camp, open a cycle and optionally self-score it.

    ``camp`` is the keyword payload for the registration call; ``self_scores`` maps
    a standard ``code`` to the camp's own verdict for that row.
    """
    edition, created_standards = publish_edition_with_standards(
        api, edition_code, standards, effective_year
    )
    camp_row = register_camp(api, **camp)
    cycle = open_cycle(api, camp_row["id"], edition["id"], cycle_year, camp_row["version"])
    scenario = Scenario(
        edition=edition,
        standards=created_standards,
        camp=read_camp(api, camp_row["id"]),
        cycle=cycle,
    )
    scenario.evaluations = evaluations_by_code(
        api, cycle["id"], camp_row["id"], created_standards
    )
    for code, score in (self_scores or {}).items():
        record_self_score(api, scenario.evaluation_id(code), camp_row["id"], score)
    if submit:
        submit_self_assessment(api, cycle["id"], camp_row["id"])
    return scenario.refresh(api)


def seat_team(
    api: ApiClient,
    scenario: Scenario,
    *,
    team: Sequence[Dict[str, Any]] = None,
    window: Tuple[str, str] = DEFAULT_WINDOW,
    travel: Tuple[str, str] = DEFAULT_TRAVEL,
    confirm: bool = False,
) -> Scenario:
    """Add the roster visitors, open a visit, seat every team member, optionally confirm."""
    team = list(DEFAULT_TEAM if team is None else team)
    for spec in team:
        scenario.visitors[spec["key"]] = add_visitor(
            api,
            full_name=spec.get("full_name", spec["key"]),
            home_state_code=spec.get("home_state_code", "PA"),
            trained_through_year=spec.get("trained_through_year", 2026),
            certifications=spec.get("certifications"),
            employer_camp_id=spec.get("employer_camp_id"),
        )
    scenario.visit = open_visit(
        api,
        scenario.cycle_id,
        window_start_date=window[0],
        window_end_date=window[1],
        expected_cycle_version=read_cycle(api, scenario.cycle_id)["version"],
    )
    for spec in team:
        block = spec.get("travel", travel)
        scenario.assignments[spec["key"]] = seat_visitor(
            api,
            scenario.visit_id,
            scenario.visitors[spec["key"]]["id"],
            spec["team_role"],
            block[0],
            block[1],
        )
    if confirm:
        confirm_visit(api, scenario.visit_id)
    return scenario.refresh(api)


def score_visit(
    api: ApiClient,
    scenario: Scenario,
    *,
    visitor_scores: Dict[str, Tuple[str, str]],
    clock: Optional[str] = IN_WINDOW_CLOCK,
    lead_key: str = "lead",
    scorer_key: Optional[str] = None,
    finalize: bool = True,
) -> Scenario:
    """Advance the clock into the window, open scoring, record verdicts, close scoring.

    ``visitor_scores`` maps a standard ``code`` to a ``(visitor_score, score_source)``
    pair. Rows left out of the mapping are never scored.
    """
    if clock is not None:
        set_clock(api, clock)
    lead_id = scenario.visitors[lead_key]["id"]
    open_scoring(api, scenario.visit_id, lead_id)
    scorer_id = scenario.visitors[scorer_key]["id"] if scorer_key else lead_id
    for code, (visitor_score, score_source) in visitor_scores.items():
        record_visitor_score(
            api, scenario.evaluation_id(code), scorer_id, visitor_score, score_source
        )
    if finalize:
        close_scoring(api, scenario.visit_id, lead_id)
        scenario.deficiencies = list_deficiencies_for_visit(api, scenario.visit_id)[0]
    return scenario.refresh(api)


def decide_cycle(
    api: ApiClient, scenario: Scenario, headers: Dict[str, str] = None
) -> Scenario:
    """Issue the decision and refresh the whole scenario."""
    issue_decision(api, scenario.cycle_id, headers)
    scenario.refresh(api)
    if scenario.visit is not None:
        scenario.deficiencies = list_deficiencies_for_visit(api, scenario.visit_id)[0]
    return scenario


def universal_mandatory_standard(
    code: str, domain: str = "SUPERVISION", scoring_weight: int = 1, **extra: Any
) -> Dict[str, Any]:
    """A standard with every applicability gate left empty, so it excludes nobody."""
    spec = {
        "code": code,
        "title": f"{code} requirement",
        "domain": domain,
        "mandatory": True,
        "scoring_weight": scoring_weight,
    }
    spec.update(extra)
    return spec


def universal_optional_standard(
    code: str, domain: str = "OPERATIONS", scoring_weight: int = 1, **extra: Any
) -> Dict[str, Any]:
    spec = {
        "code": code,
        "title": f"{code} requirement",
        "domain": domain,
        "mandatory": False,
        "scoring_weight": scoring_weight,
    }
    spec.update(extra)
    return spec


ALL_MET_OBSERVED = (VisitorScore.MET, ScoreSource.OBSERVED)
NOT_MET_OBSERVED = (VisitorScore.NOT_MET, ScoreSource.OBSERVED)
MET_INTERVIEW = (VisitorScore.MET, ScoreSource.INTERVIEW)
MET_DOCUMENT = (VisitorScore.MET, ScoreSource.DOCUMENT)
NOT_APPLICABLE_OBSERVED = (VisitorScore.NOT_APPLICABLE, ScoreSource.OBSERVED)

ALL_MET_SELF = SelfScore.MET
OFFICER_WHO_SCHEDULES = OFFICER_ONE_ID
