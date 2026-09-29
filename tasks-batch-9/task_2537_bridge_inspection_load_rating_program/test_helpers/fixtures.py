"""
Composite setup builders for the Bridge Inspection & Load Rating Program API.

Every scenario in this suite starts from an empty database, so each builder here
constructs its preconditions from scratch through the public API and returns the
identifiers a test needs. The builders are layered: a roster, then a structure,
then a draft report, then an accepted report, then whatever the domain hangs off
an accepted report (a rating, a finding, a scour evaluation, a candidate, a
permit, a submission).

Nothing in this module asserts a business claim. Its job is to reach a state; the
claims live in the test modules.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import BridgeProgramClient
from .constants import BASE_CLOCK, FIELD_DAY_CLOCK, QA_DAY_CLOCK
from . import factories as f
from .test_users import (
    make_bridge_inspector_headers,
    make_district_engineer_headers,
    make_qa_reviewer_headers,
    make_rating_engineer_headers,
    permit_officer_headers,
    program_admin_headers,
)

# The field-work window every scenario reserves, and the observation instant
# inside it. `inspection_date` must fall "at or after `field_window_start` and at
# or before `field_window_end`, and must not be later than the logical clock"
# (PRD §3.3), which these three literals satisfy together with FIELD_DAY_CLOCK.
FIELD_WINDOW_START = "2026-09-02T08:00:00Z"
FIELD_WINDOW_END = "2026-09-02T16:00:00Z"
INSPECTION_DATE = "2026-09-02T10:00:00Z"

# A refresher expiry comfortably after every clock instant these builders pin, so
# that `qualification_status` reads `CURRENT` throughout (PRD §2.10).
CURRENT_REFRESHER = "2027-06-30"
# A refresher expiry strictly before BASE_CLOCK's calendar date, for the EXPIRED
# side of the same rule.
EXPIRED_REFRESHER = "2026-08-31"


# ─── The logical clock (PRD §2.4) ───────────────────────────────────────────
def set_clock(client: BridgeProgramClient, instant: str) -> str:
    """Move the logical clock and return the `current_utc` the server reports."""
    response = client.set_clock(instant, program_admin_headers())
    data = validate_success(response, 200)
    return data["current_utc"]


def pin_base_clock(client: BridgeProgramClient) -> str:
    """Pin the clock to the instant every scenario in this suite starts from."""
    return set_clock(client, BASE_CLOCK)


# ─── The roster (PRD §3.1, §2.10) ──────────────────────────────────────────
def create_person(
    client: BridgeProgramClient, payload: Dict[str, Any]
) -> Dict[str, Any]:
    """Register one roster entry and return the created record."""
    response = client.create_personnel(payload, program_admin_headers())
    return get_success_data(response, 201)


def create_roster(client: BridgeProgramClient) -> Dict[str, Dict[str, Any]]:
    """
    Register the four entity-backed actors every workflow needs.

    * `inspector` — team-leader certified, so it may own a report.
    * `reviewer` — team-leader certified, so it may claim a report, and a
      different person from the inspector so the segregation-of-duties rule of
      PRD §2.10 is satisfiable.
    * `engineer` — additionally `load_rating_engineer_licensed` with a
      `pe_license_number`, so it may seal a rating and finalise a scour
      evaluation.
    * `district` — additionally licensed as well, and distinct from the sealing
      engineer so it may approve what the engineer sealed.
    """
    inspector = create_person(
        client,
        f.personnel_payload(
            "Ivy Inspector", CURRENT_REFRESHER, team_leader_certified=True
        ),
    )
    reviewer = create_person(
        client,
        f.personnel_payload("Quinn Qa", CURRENT_REFRESHER, team_leader_certified=True),
    )
    engineer = create_person(
        client,
        f.personnel_payload(
            "Rita Rating",
            CURRENT_REFRESHER,
            team_leader_certified=True,
            load_rating_engineer_licensed=True,
            pe_license_number="PE-11021",
        ),
    )
    district = create_person(
        client,
        f.personnel_payload(
            "Dana District",
            CURRENT_REFRESHER,
            team_leader_certified=True,
            load_rating_engineer_licensed=True,
            pe_license_number="PE-20044",
        ),
    )
    return {
        "inspector": inspector,
        "reviewer": reviewer,
        "engineer": engineer,
        "district": district,
    }


class Roster:
    """Convenience view over a roster dict, exposing ids and ready-made headers."""

    def __init__(self, people: Dict[str, Dict[str, Any]]) -> None:
        self.people = people

    @property
    def inspector_id(self) -> str:
        return self.people["inspector"]["id"]

    @property
    def reviewer_id(self) -> str:
        return self.people["reviewer"]["id"]

    @property
    def engineer_id(self) -> str:
        return self.people["engineer"]["id"]

    @property
    def district_id(self) -> str:
        return self.people["district"]["id"]

    @property
    def inspector_headers(self) -> Dict[str, str]:
        return make_bridge_inspector_headers(self.inspector_id)

    @property
    def reviewer_headers(self) -> Dict[str, str]:
        return make_qa_reviewer_headers(self.reviewer_id)

    @property
    def engineer_headers(self) -> Dict[str, str]:
        return make_rating_engineer_headers(self.engineer_id)

    @property
    def district_headers(self) -> Dict[str, str]:
        return make_district_engineer_headers(self.district_id)


# ─── The inventory (PRD §3.1) ──────────────────────────────────────────────
def create_bridge(
    client: BridgeProgramClient, payload: Dict[str, Any]
) -> Dict[str, Any]:
    """Add one structure to the inventory and return the created record."""
    response = client.create_bridge(payload, program_admin_headers())
    return get_success_data(response, 201)


def create_cedar_creek(
    client: BridgeProgramClient,
    nbi_structure_number: str = "STR-000001",
    **overrides: Any,
) -> Dict[str, Any]:
    """
    The structure the worked examples of PRD §3.4 and §3.8 describe: a 1972
    girder bridge of 1000 square metres carrying 12000 vehicles a day with an
    8.5 km detour, crossing a waterway so that scour evaluation applies.
    """
    payload = f.bridge_payload(
        nbi_structure_number, spans_water=True, **overrides
    )
    return create_bridge(client, payload)


def read_bridge(client: BridgeProgramClient, bridge_id: str) -> Dict[str, Any]:
    """Re-read a structure, which is how a client learns its current `version`."""
    response = client.get_bridge(bridge_id, program_admin_headers())
    return validate_success(response, 200)


def read_bridge_version(client: BridgeProgramClient, bridge_id: str) -> int:
    """The structure's current `version`, for the OCC guard of PRD §2.9."""
    return read_bridge(client, bridge_id)["version"]


# ─── A draft report with its element rows (PRD §3.2) ────────────────────────
def open_inspection(
    client: BridgeProgramClient,
    bridge_id: str,
    roster: Roster,
    inspection_type: str = "ROUTINE",
    field_window_start: str = FIELD_WINDOW_START,
    field_window_end: str = FIELD_WINDOW_END,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open a `DRAFT` report led by the roster's inspector."""
    payload = f.inspection_payload(
        roster.inspector_id,
        field_window_start,
        field_window_end,
        inspection_type=inspection_type,
        **overrides,
    )
    response = client.create_inspection(bridge_id, payload, roster.inspector_headers)
    return get_success_data(response, 201)


def add_element(
    client: BridgeProgramClient,
    inspection_id: str,
    roster: Roster,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Record one element-condition row on a `DRAFT` report."""
    response = client.create_element_condition(
        inspection_id, payload, roster.inspector_headers
    )
    return get_success_data(response, 201)


def add_baseline_elements(
    client: BridgeProgramClient, inspection_id: str, roster: Roster
) -> Dict[str, Dict[str, Any]]:
    """
    Record the four-row element set the worked examples of PRD §3.2 and §3.3 use:
    a deck scoring 82.00, a girder scoring 40.00, a bearing scoring 50.00 and an
    abutment scoring 95.00. The set covers all three element groups, every row is
    balanced, and every row carrying poor or severe quantity carries photographs
    and defect notes, so it passes all six submit gates of PRD §3.3.
    """
    rows = {}
    for key, payload in (
        ("deck", f.BASELINE_DECK),
        ("girder", f.BASELINE_GIRDER),
        ("bearing", f.BASELINE_BEARING),
        ("abutment", f.BASELINE_ABUTMENT),
    ):
        rows[key] = add_element(client, inspection_id, roster, payload)
    return rows


def draft_report_with_baseline(
    client: BridgeProgramClient, bridge_id: str, roster: Roster, **overrides: Any
) -> Dict[str, Any]:
    """A `DRAFT` routine report already carrying the baseline element set."""
    inspection = open_inspection(client, bridge_id, roster, **overrides)
    rows = add_baseline_elements(client, inspection["id"], roster)
    return {"inspection": inspection, "elements": rows}


# ─── Submit, claim, decide (PRD §3.3) ──────────────────────────────────────
def submit_report(
    client: BridgeProgramClient,
    inspection_id: str,
    roster: Roster,
    inspection_date: str = INSPECTION_DATE,
) -> Dict[str, Any]:
    """Submit a `DRAFT` report; the clock must already be at or after the date."""
    response = client.submit_inspection(
        inspection_id, f.submit_payload(inspection_date), roster.inspector_headers
    )
    return validate_success(response, 200)


def qa_claim(
    client: BridgeProgramClient, inspection_id: str, roster: Roster
) -> Dict[str, Any]:
    """Claim a `SUBMITTED` report for review as the roster's reviewer."""
    response = client.qa_claim_inspection(inspection_id, roster.reviewer_headers)
    return validate_success(response, 200)


def qa_decide(
    client: BridgeProgramClient,
    inspection_id: str,
    roster: Roster,
    decision: str,
    return_note: Optional[str] = None,
) -> Dict[str, Any]:
    """Issue the QA decision as the reviewer who holds the claim."""
    response = client.qa_decision_inspection(
        inspection_id,
        f.qa_decision_payload(decision, return_note=return_note),
        roster.reviewer_headers,
    )
    return validate_success(response, 200)


def accepted_report(
    client: BridgeProgramClient,
    bridge_id: str,
    roster: Roster,
    inspection_type: str = "ROUTINE",
    field_window_start: str = FIELD_WINDOW_START,
    field_window_end: str = FIELD_WINDOW_END,
    inspection_date: str = INSPECTION_DATE,
    submit_clock: str = FIELD_DAY_CLOCK,
    qa_clock: str = QA_DAY_CLOCK,
) -> Dict[str, Any]:
    """
    Drive one report all the way from `DRAFT` to `ACCEPTED` with the baseline
    element set, advancing the clock to the field day before submitting and to the
    QA day before the decision. Returns the report, its element rows and the
    structure as the acceptance cascade of PRD §3.3 left it.
    """
    drafted = draft_report_with_baseline(
        client,
        bridge_id,
        roster,
        field_window_start=field_window_start,
        field_window_end=field_window_end,
        inspection_type=inspection_type,
    )
    inspection_id = drafted["inspection"]["id"]
    set_clock(client, submit_clock)
    submit_report(client, inspection_id, roster, inspection_date=inspection_date)
    set_clock(client, qa_clock)
    qa_claim(client, inspection_id, roster)
    accepted = qa_decide(client, inspection_id, roster, "ACCEPT")
    return {
        "inspection": accepted,
        "elements": drafted["elements"],
        "bridge": read_bridge(client, bridge_id),
    }


# ─── Load ratings (PRD §3.4) ───────────────────────────────────────────────
def create_rating(
    client: BridgeProgramClient,
    bridge_id: str,
    roster: Roster,
    source_inspection_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """
    Create a `DRAFT` rating, re-reading the structure first so that
    `expected_bridge_version` is fresh (PRD §2.9).
    """
    payload = f.load_rating_payload(
        read_bridge_version(client, bridge_id), source_inspection_id, **overrides
    )
    response = client.create_load_rating(bridge_id, payload, roster.engineer_headers)
    return get_success_data(response, 201)


def seal_rating(
    client: BridgeProgramClient, rating_id: str, roster: Roster
) -> Dict[str, Any]:
    """Seal a `DRAFT` rating as the licensed engineer who owns it."""
    response = client.seal_load_rating(
        rating_id, f.seal_payload(roster.engineer_id), roster.engineer_headers
    )
    return validate_success(response, 200)


def approve_rating(
    client: BridgeProgramClient, rating_id: str, roster: Roster
) -> Dict[str, Any]:
    """Approve a `SEALED` rating as the district engineer, who did not seal it."""
    response = client.approve_load_rating(
        rating_id, f.approve_rating_payload(roster.district_id), roster.district_headers
    )
    return validate_success(response, 200)


def approved_rating(
    client: BridgeProgramClient,
    bridge_id: str,
    roster: Roster,
    source_inspection_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Drive one rating from create through seal to approval, so it governs."""
    rating = create_rating(
        client, bridge_id, roster, source_inspection_id, **overrides
    )
    seal_rating(client, rating["id"], roster)
    return approve_rating(client, rating["id"], roster)


# ─── Critical findings (PRD §3.5) ──────────────────────────────────────────
def raise_finding(
    client: BridgeProgramClient,
    roster: Roster,
    bridge_id: str,
    source_inspection_id: str,
    severity: str,
    element_condition_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Raise a critical finding as the inspector who surfaced it."""
    payload = f.critical_finding_payload(
        bridge_id,
        source_inspection_id,
        severity,
        element_condition_id=element_condition_id,
        **overrides,
    )
    response = client.create_critical_finding(payload, roster.inspector_headers)
    return get_success_data(response, 201)


def notify_owner(
    client: BridgeProgramClient, finding_id: str, roster: Roster, **overrides: Any
) -> Dict[str, Any]:
    """Walk the `BRIDGE_OWNER` link of the notification chain."""
    response = client.notify_finding(
        finding_id, f.notify_payload("BRIDGE_OWNER", **overrides), roster.district_headers
    )
    return get_success_data(response)


def notify_fhwa(
    client: BridgeProgramClient, finding_id: str, roster: Roster, **overrides: Any
) -> Dict[str, Any]:
    """Walk the `FHWA` link, which is only reachable from `OWNER_NOTIFIED`."""
    payload = f.notify_payload(
        "FHWA", recipient_label="FHWA Division Office", **overrides
    )
    response = client.notify_finding(finding_id, payload, roster.district_headers)
    return get_success_data(response)


def impose(
    client: BridgeProgramClient, finding_id: str, roster: Roster, action: str
) -> Dict[str, Any]:
    """Exercise restriction or closure authority as the district engineer."""
    response = client.impose_restriction(
        finding_id,
        f.restriction_payload(action, roster.district_id),
        roster.district_headers,
    )
    return validate_success(response, 200)


def mitigate(
    client: BridgeProgramClient,
    finding_id: str,
    roster: Roster,
    note: str = "Temporary shoring installed under the girder",
) -> Dict[str, Any]:
    """Record interim mitigation on an `OPEN` finding."""
    response = client.mitigate_finding(
        finding_id, {"mitigation_note": note}, roster.district_headers
    )
    return validate_success(response, 200)


def resolve(
    client: BridgeProgramClient,
    finding_id: str,
    roster: Roster,
    note: str = "Girder web plated and re-inspected",
) -> Dict[str, Any]:
    """Close out a finding, which requires the owner chain to be walked first."""
    response = client.resolve_finding(
        finding_id, {"resolution_note": note}, roster.district_headers
    )
    return validate_success(response, 200)


# ─── Scour (PRD §3.6) ──────────────────────────────────────────────────────
def create_scour_evaluation(
    client: BridgeProgramClient,
    bridge_id: str,
    roster: Roster,
    scour_code: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """Record a `DRAFT` scour evaluation as the licensed engineer."""
    payload = f.scour_evaluation_payload(roster.engineer_id, scour_code, **overrides)
    response = client.create_scour_evaluation(
        bridge_id, payload, roster.engineer_headers
    )
    return get_success_data(response, 201)


def finalize_scour(
    client: BridgeProgramClient, evaluation_id: str, roster: Roster
) -> Dict[str, Any]:
    """Finalise an evaluation, running the four-hop cascade of PRD §3.6."""
    response = client.finalize_scour_evaluation(
        evaluation_id, roster.engineer_headers
    )
    return validate_success(response, 200)


def plans_for_bridge(
    client: BridgeProgramClient, bridge_id: str
) -> List[Dict[str, Any]]:
    """
    Discover the plans of action a structure owes. PRD §3.6: "Because plans of
    action are created by a cascade rather than by a client request, the plan list
    is the only way to discover that a plan now exists."
    """
    response = client.list_plans_of_action(
        program_admin_headers(), {"bridge_id": bridge_id}
    )
    return validate_success(response, 200)


def approved_plan(
    client: BridgeProgramClient, plan_id: str, roster: Roster
) -> Dict[str, Any]:
    """Take a `REQUIRED` plan through draft, submission and approval."""
    validate_success(
        client.update_plan_of_action(
            plan_id,
            f.plan_of_action_payload(6, 3.5, countermeasure_type="RIPRAP"),
            roster.district_headers,
        ),
        200,
    )
    validate_success(
        client.submit_plan_of_action(plan_id, roster.district_headers), 200
    )
    response = client.decide_plan_of_action(
        plan_id,
        f.plan_decision_payload("APPROVE", approved_by_id=roster.district_id),
        roster.district_headers,
    )
    return validate_success(response, 200)


# ─── Programming (PRD §3.8) ────────────────────────────────────────────────
def create_cycle(
    client: BridgeProgramClient, **overrides: Any
) -> Dict[str, Any]:
    """Open a programming cycle in `PLANNING`."""
    response = client.create_program_cycle(
        f.program_cycle_payload(**overrides), program_admin_headers()
    )
    return get_success_data(response, 201)


def read_cycle(client: BridgeProgramClient, cycle_id: str) -> Dict[str, Any]:
    """Re-read a cycle, which is how a client learns its current `version`."""
    response = client.get_program_cycle(cycle_id, program_admin_headers())
    return validate_success(response, 200)


def identify_candidate(
    client: BridgeProgramClient,
    cycle_id: str,
    bridge_id: str,
    roster: Roster,
    **overrides: Any,
) -> Dict[str, Any]:
    """
    Identify a candidate against a cycle, re-reading the cycle first so that
    `expected_program_cycle_version` is fresh (PRD §2.9).
    """
    payload = f.candidate_payload(
        read_cycle(client, cycle_id)["version"], bridge_id, **overrides
    )
    response = client.create_project_candidate(
        cycle_id, payload, roster.district_headers
    )
    return get_success_data(response, 201)


def candidates_in_cycle(
    client: BridgeProgramClient, cycle_id: str
) -> List[Dict[str, Any]]:
    """
    Discover a cycle's candidates. PRD §3.3: "Because these candidates are
    created by a cascade rather than by a client call, the candidate listing is
    the only channel through which a client can discover them."
    """
    response = client.list_project_candidates(
        program_admin_headers(), {"program_cycle_id": cycle_id}
    )
    return validate_success(response, 200)


# ─── Permits (PRD §3.7) ────────────────────────────────────────────────────
def receive_permit(
    client: BridgeProgramClient,
    permit_number: str,
    route_bridge_ids: List[str],
    **overrides: Any,
) -> Dict[str, Any]:
    """Receive a permit application in `RECEIVED`."""
    payload = f.permit_application_payload(
        permit_number, route_bridge_ids, **overrides
    )
    response = client.create_permit_application(payload, permit_officer_headers())
    return get_success_data(response, 201)


def analyze_permit(client: BridgeProgramClient, permit_id: str) -> Dict[str, Any]:
    """Run the route analysis, which is permitted only once and only from `RECEIVED`."""
    response = client.analyze_permit_application(permit_id, permit_officer_headers())
    return validate_success(response, 200)


def analyses_for_permit(
    client: BridgeProgramClient, permit_id: str
) -> List[Dict[str, Any]]:
    """
    Discover the per-bridge analysis rows. PRD §3.7: "Because the analysis rows
    are created by that run rather than by a client request, the per-bridge
    analysis list is the only way to discover them."
    """
    response = client.list_permit_bridge_analyses(
        program_admin_headers(), {"permit_application_id": permit_id}
    )
    return validate_success(response, 200)


def decide_permit(
    client: BridgeProgramClient, permit_id: str, decision: str, **overrides: Any
) -> Dict[str, Any]:
    """Issue the permit decision, which must equal the recommendation."""
    response = client.decide_permit_application(
        permit_id, f.permit_decision_payload(decision, **overrides), permit_officer_headers()
    )
    return validate_success(response, 200)


# ─── Federal reporting (PRD §3.9) ──────────────────────────────────────────
def start_submission(
    client: BridgeProgramClient, cycle_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Open a federal submission in `BUILDING` against a cycle."""
    response = client.create_federal_submission(
        cycle_id, f.federal_submission_payload(**overrides), program_admin_headers()
    )
    return get_success_data(response, 201)


def lock_cycle(client: BridgeProgramClient, cycle_id: str) -> Dict[str, Any]:
    """Lock a cycle, the precondition for sending a submission."""
    response = client.lock_program_cycle(cycle_id, program_admin_headers())
    return validate_success(response, 200)


def send_submission(
    client: BridgeProgramClient, submission_id: str
) -> Dict[str, Any]:
    """Send a submission, recomputing the statewide snapshot at the clock."""
    response = client.submit_federal_submission(
        submission_id, program_admin_headers()
    )
    return validate_success(response, 200)


def review_submission(
    client: BridgeProgramClient, submission_id: str, decision: str, headers: Dict[str, str]
) -> Dict[str, Any]:
    """Review a `SUBMITTED` package as an FHWA reviewer other than the sender."""
    response = client.review_federal_submission(
        submission_id, f.review_payload(decision), headers
    )
    return validate_success(response, 200)


# ─── Plain reads, for tests that check a settled state after a cascade ──────
def read_inspection(client: BridgeProgramClient, inspection_id: str) -> Dict[str, Any]:
    """Re-read an inspection report."""
    return validate_success(
        client.get_inspection(inspection_id, program_admin_headers()), 200
    )


def read_element(client: BridgeProgramClient, element_id: str) -> Dict[str, Any]:
    """Re-read one element-condition row."""
    return validate_success(
        client.get_element_condition(element_id, program_admin_headers()), 200
    )


def read_finding(client: BridgeProgramClient, finding_id: str) -> Dict[str, Any]:
    """Re-read a critical finding with all three of its status dimensions."""
    return validate_success(
        client.get_critical_finding(finding_id, program_admin_headers()), 200
    )


def read_rating(client: BridgeProgramClient, rating_id: str) -> Dict[str, Any]:
    """Re-read a load rating with both variant results."""
    return validate_success(
        client.get_load_rating(rating_id, program_admin_headers()), 200
    )


def read_permit(client: BridgeProgramClient, permit_id: str) -> Dict[str, Any]:
    """Re-read a permit application with its aggregated analysis outcome."""
    return validate_success(
        client.get_permit_application(permit_id, program_admin_headers()), 200
    )


def read_scour(client: BridgeProgramClient, evaluation_id: str) -> Dict[str, Any]:
    """Re-read a scour evaluation."""
    return validate_success(
        client.get_scour_evaluation(evaluation_id, program_admin_headers()), 200
    )


def read_plan(client: BridgeProgramClient, plan_id: str) -> Dict[str, Any]:
    """Re-read a scour plan of action."""
    return validate_success(
        client.get_plan_of_action(plan_id, program_admin_headers()), 200
    )


def read_candidate(client: BridgeProgramClient, candidate_id: str) -> Dict[str, Any]:
    """Re-read a project candidate with its scored priority."""
    return validate_success(
        client.get_project_candidate(candidate_id, program_admin_headers()), 200
    )


def read_submission(client: BridgeProgramClient, submission_id: str) -> Dict[str, Any]:
    """Re-read a federal submission with its compliance snapshot."""
    return validate_success(
        client.get_federal_submission(submission_id, program_admin_headers()), 200
    )


def read_compliance(client: BridgeProgramClient, bridge_id: str) -> Dict[str, Any]:
    """The per-structure compliance read of PRD §3.9."""
    return validate_success(
        client.get_compliance_summary(bridge_id, program_admin_headers()), 200
    )


def read_allocation(client: BridgeProgramClient, cycle_id: str) -> Dict[str, Any]:
    """The cycle's budget identity and candidate mix (PRD §3.8)."""
    return validate_success(
        client.get_allocation_summary(cycle_id, program_admin_headers()), 200
    )


def read_person(client: BridgeProgramClient, personnel_id: str) -> Dict[str, Any]:
    """Re-read a roster entry, whose `qualification_status` is recomputed on read."""
    return validate_success(
        client.get_personnel(personnel_id, program_admin_headers()), 200
    )


def elements_for_inspection(
    client: BridgeProgramClient, inspection_id: str
) -> Dict[str, Any]:
    """The element rows of one report, together with the listing envelope's meta."""
    from prd_bench_local_runner.testing import validate_paginated

    rows, meta = validate_paginated(
        client.list_element_conditions(
            program_admin_headers(), {"inspection_id": inspection_id}
        )
    )
    return {"rows": rows, "meta": meta}


def inspections_for_bridge(
    client: BridgeProgramClient, bridge_id: str
) -> Dict[str, Any]:
    """The reports filed against one structure, with the listing meta."""
    from prd_bench_local_runner.testing import validate_paginated

    rows, meta = validate_paginated(
        client.list_inspections(program_admin_headers(), {"bridge_id": bridge_id})
    )
    return {"rows": rows, "meta": meta}


def inspections_for_leader(
    client: BridgeProgramClient, team_leader_id: str
) -> Dict[str, Any]:
    """The reports one team leader owns, with the listing meta."""
    from prd_bench_local_runner.testing import validate_paginated

    rows, meta = validate_paginated(
        client.list_inspections(
            program_admin_headers(), {"team_leader_id": team_leader_id}
        )
    )
    return {"rows": rows, "meta": meta}


def ratings_for_bridge(client: BridgeProgramClient, bridge_id: str) -> Dict[str, Any]:
    """The load ratings written against one structure, with the listing meta."""
    from prd_bench_local_runner.testing import validate_paginated

    rows, meta = validate_paginated(
        client.list_load_ratings(program_admin_headers(), {"bridge_id": bridge_id})
    )
    return {"rows": rows, "meta": meta}


def logs_for_finding(client: BridgeProgramClient, finding_id: str) -> List[Dict[str, Any]]:
    """
    The notification log entries of one finding. PRD §4 makes the log listing the
    "reverse-reachability channel for NotificationLog.critical_finding_id".
    """
    return validate_success(
        client.list_notification_logs(
            program_admin_headers(), {"critical_finding_id": finding_id}
        ),
        200,
    )


def void_report(
    client: BridgeProgramClient, inspection_id: str, roster: Roster
) -> Dict[str, Any]:
    """Void a `DRAFT` or `SUBMITTED` report, releasing the window it reserved."""
    return validate_success(
        client.void_inspection(inspection_id, roster.inspector_headers), 200
    )
