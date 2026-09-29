"""Composite scenario builders.

Every precondition is built from scratch through the public endpoints of PRD
section 4 — there is no database seeding and no back door. The builders are
layered so that a test can stop at whatever stage it needs:

    master data -> screening pursuit -> qualified -> scoped -> baselined
    -> statement of work (DRAFT) -> internal review -> client review
    -> signed (engagement MOBILIZING) -> mobilised (engagement ACTIVE)

Each layer forwards unknown keyword arguments to the layer beneath it, so a test
that needs a ``PROCUREMENT_LED`` client on an ``OUTCOME_BASED`` document writes
one call.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as F
from .api_client import ConsultingApiClient
from .test_users import (
    PRACTICE_ADMIN_HEADERS,
    make_client_headers,
    make_leadership_headers,
    make_manager_headers,
    make_partner_headers,
    make_reviewer_headers,
)

JsonDict = Dict[str, Any]


@dataclass
class Scenario:
    """Identities and row ids of a built-up scenario."""

    api: ConsultingApiClient
    client_id: str = ""
    partner_id: str = ""
    manager_id: str = ""
    consultant_id: str = ""
    reviewer_id: str = ""
    leadership_id: str = ""
    opportunity_id: str = ""
    deliverable_ids: List[str] = field(default_factory=list)
    sow_id: str = ""
    engagement_id: str = ""
    opportunity_version: int = 0
    extras: JsonDict = field(default_factory=dict)

    # -- headers -------------------------------------------------------
    @property
    def admin(self) -> Dict[str, str]:
        return PRACTICE_ADMIN_HEADERS

    @property
    def partner(self) -> Dict[str, str]:
        return make_partner_headers(self.partner_id)

    @property
    def manager(self) -> Dict[str, str]:
        return make_manager_headers(self.manager_id)

    @property
    def reviewer(self) -> Dict[str, str]:
        return make_reviewer_headers(self.reviewer_id)

    @property
    def leadership(self) -> Dict[str, str]:
        return make_leadership_headers(self.leadership_id)

    @property
    def client_contact(self) -> Dict[str, str]:
        return make_client_headers(self.client_id)

    # -- convenience ---------------------------------------------------
    @property
    def d1_id(self) -> str:
        return self.deliverable_ids[0]

    @property
    def d2_id(self) -> str:
        return self.deliverable_ids[1]


# ---------------------------------------------------------------------------
# Layer 1 - the logical clock and master data
# ---------------------------------------------------------------------------


def set_clock(api: ConsultingApiClient, current_utc: str) -> JsonDict:
    return get_success_data(
        api.set_clock(F.clock_payload(current_utc), PRACTICE_ADMIN_HEADERS)
    )


def create_client(api: ConsultingApiClient, **overrides: Any) -> JsonDict:
    return get_success_data(
        api.create_client(F.client_payload(**overrides), PRACTICE_ADMIN_HEADERS)
    )


def create_consultant(api: ConsultingApiClient, **overrides: Any) -> JsonDict:
    return get_success_data(
        api.create_consultant(F.consultant_payload(**overrides), PRACTICE_ADMIN_HEADERS)
    )


def build_master_data(
    api: ConsultingApiClient,
    clock: str = C.SEED_CLOCK,
    client: Optional[JsonDict] = None,
) -> Scenario:
    """Clock, one client and the five consultants the suite acts through."""
    set_clock(api, clock)
    sc = Scenario(api=api)
    sc.client_id = create_client(api, **(client or {}))["id"]
    sc.partner_id = create_consultant(
        api,
        name="P. Reyes",
        grade=C.GRADE_PARTNER,
        cost_rate_cents_per_hour=C.SEED_PARTNER_COST_RATE,
    )["id"]
    sc.manager_id = create_consultant(
        api,
        name="M. Osei",
        grade=C.GRADE_MANAGER,
        cost_rate_cents_per_hour=C.SEED_MANAGER_COST_RATE,
    )["id"]
    sc.consultant_id = create_consultant(
        api,
        name="C. Vaz",
        grade=C.GRADE_CONSULTANT,
        cost_rate_cents_per_hour=C.SEED_CONSULTANT_COST_RATE,
    )["id"]
    sc.reviewer_id = create_consultant(
        api,
        name="Q. Haddad",
        grade=C.GRADE_MANAGER,
        cost_rate_cents_per_hour=C.SEED_REVIEWER_COST_RATE,
        quality_reviewer_certified=True,
    )["id"]
    sc.leadership_id = create_consultant(
        api,
        name="L. Brandt",
        grade=C.GRADE_PARTNER,
        cost_rate_cents_per_hour=C.SEED_LEADERSHIP_COST_RATE,
    )["id"]
    return sc


# ---------------------------------------------------------------------------
# Layer 2 - the pursuit in SCREENING
# ---------------------------------------------------------------------------


def open_pursuit(sc: Scenario, **overrides: Any) -> JsonDict:
    payload = F.opportunity_payload(
        sc.client_id, sc.partner_id, sc.manager_id, **overrides
    )
    return get_success_data(sc.api.create_opportunity(payload, sc.partner))


def build_screening_pursuit(
    api: ConsultingApiClient, opportunity: Optional[JsonDict] = None, **kwargs: Any
) -> Scenario:
    sc = build_master_data(api, **kwargs)
    row = open_pursuit(sc, **(opportunity or {}))
    sc.opportunity_id = row["id"]
    sc.opportunity_version = row["version"]
    return sc


# ---------------------------------------------------------------------------
# Layer 3 - screened, budget-verified and QUALIFIED
# ---------------------------------------------------------------------------


def screen_conflicts(
    sc: Scenario,
    screened: Optional[List[str]] = None,
    waiver_obtained: Optional[bool] = None,
) -> JsonDict:
    return get_success_data(
        sc.api.conflict_check(
            sc.opportunity_id,
            F.conflict_check_payload(screened, waiver_obtained),
            sc.partner,
        )
    )


def verify_budget(sc: Scenario, verified_budget_cents: int) -> JsonDict:
    return get_success_data(
        sc.api.verify_budget(
            sc.opportunity_id, F.verify_budget_payload(verified_budget_cents), sc.partner
        )
    )


def build_qualified_pursuit(
    api: ConsultingApiClient,
    screened: Optional[List[str]] = None,
    waiver_obtained: Optional[bool] = None,
    verified_budget_cents: int = C.SEED_VERIFIED_BUDGET_CENTS,
    **kwargs: Any,
) -> Scenario:
    sc = build_screening_pursuit(api, **kwargs)
    screen_conflicts(sc, screened, waiver_obtained)
    verify_budget(sc, verified_budget_cents)
    row = get_success_data(sc.api.qualify(sc.opportunity_id, {}, sc.partner))
    sc.opportunity_version = row["version"]
    return sc


# ---------------------------------------------------------------------------
# Layer 4 - SCOPING with a narrative and deliverables
# ---------------------------------------------------------------------------

DEFAULT_DELIVERABLES: List[JsonDict] = [
    dict(C.SEED_D1),
    dict(C.SEED_D2, depends_on_index=0),
]


def edit_scope(sc: Scenario, **overrides: Any) -> JsonDict:
    return get_success_data(
        sc.api.patch_scope(sc.opportunity_id, F.scope_payload(**overrides), sc.manager)
    )


def add_deliverable(sc: Scenario, spec: JsonDict) -> JsonDict:
    spec = dict(spec)
    depends_on_index = spec.pop("depends_on_index", None)
    if depends_on_index is not None:
        spec["depends_on_deliverable_id"] = sc.deliverable_ids[depends_on_index]
    row = get_success_data(
        sc.api.create_deliverable(
            F.deliverable_payload(sc.opportunity_id, **spec), sc.manager
        )
    )
    sc.deliverable_ids.append(row["id"])
    return row


def build_scoped_pursuit(
    api: ConsultingApiClient,
    scope: Optional[JsonDict] = None,
    deliverables: Optional[List[JsonDict]] = None,
    **kwargs: Any,
) -> Scenario:
    sc = build_qualified_pursuit(api, **kwargs)
    row = edit_scope(sc, **(scope or {}))
    sc.opportunity_version = row["version"]
    for spec in DEFAULT_DELIVERABLES if deliverables is None else deliverables:
        add_deliverable(sc, spec)
    return sc


# ---------------------------------------------------------------------------
# Layer 5 - the frozen, priced baseline
# ---------------------------------------------------------------------------


def baseline_scope(sc: Scenario) -> JsonDict:
    row = get_success_data(sc.api.baseline_scope(sc.opportunity_id, {}, sc.manager))
    sc.opportunity_version = row["version"]
    return row


def build_baselined_pursuit(api: ConsultingApiClient, **kwargs: Any) -> Scenario:
    sc = build_scoped_pursuit(api, **kwargs)
    baseline_scope(sc)
    return sc


# ---------------------------------------------------------------------------
# Layer 6 - the statement of work in DRAFT
# ---------------------------------------------------------------------------


def draft_sow(sc: Scenario, **overrides: Any) -> JsonDict:
    payload = F.sow_payload(sc.opportunity_id, sc.opportunity_version, **overrides)
    row = get_success_data(sc.api.create_sow(payload, sc.partner))
    sc.sow_id = row["id"]
    return row


def build_sow_draft(api: ConsultingApiClient, sow: Optional[JsonDict] = None, **kwargs):
    sc = build_baselined_pursuit(api, **kwargs)
    draft_sow(sc, **(sow or {}))
    return sc


# ---------------------------------------------------------------------------
# Layer 7 - internal review and release to the client
# ---------------------------------------------------------------------------


def submit_sow_internal(sc: Scenario) -> JsonDict:
    return get_success_data(sc.api.submit_sow_internal(sc.sow_id, {}, sc.partner))


def build_sow_internal_review(api: ConsultingApiClient, **kwargs: Any) -> Scenario:
    sc = build_sow_draft(api, **kwargs)
    submit_sow_internal(sc)
    return sc


def approve_sow_internally(sc: Scenario) -> JsonDict:
    return get_success_data(
        sc.api.sow_internal_decision(sc.sow_id, {"decision": "APPROVE"}, sc.leadership)
    )


def build_sow_client_review(api: ConsultingApiClient, **kwargs: Any) -> Scenario:
    sc = build_sow_internal_review(api, **kwargs)
    approve_sow_internally(sc)
    return sc


# ---------------------------------------------------------------------------
# Layer 8 - signature creates the engagement (MOBILIZING)
# ---------------------------------------------------------------------------


def sign_sow(sc: Scenario, signature_name: str = C.SEED_SIGNATURE_NAME) -> JsonDict:
    return get_success_data(
        sc.api.sow_client_decision(
            sc.sow_id, F.sign_payload(signature_name), sc.client_contact
        )
    )


def discover_engagement(sc: Scenario) -> JsonDict:
    body = sc.api.list_engagements(sc.partner, {"sow_id": sc.sow_id}).json()
    row = body["data"][0]
    sc.engagement_id = row["id"]
    return row


def build_signed_engagement(api: ConsultingApiClient, **kwargs: Any) -> Scenario:
    sc = build_sow_client_review(api, **kwargs)
    sign_sow(sc)
    discover_engagement(sc)
    return sc


# ---------------------------------------------------------------------------
# Layer 9 - mobilised engagement (delivery ACTIVE)
# ---------------------------------------------------------------------------


def mobilize(sc: Scenario, manager_id: Optional[str] = None) -> JsonDict:
    return get_success_data(
        sc.api.mobilize(
            sc.engagement_id,
            {"engagement_manager_consultant_id": manager_id or sc.manager_id},
            sc.partner,
        )
    )


def build_active_engagement(api: ConsultingApiClient, **kwargs: Any) -> Scenario:
    sc = build_signed_engagement(api, **kwargs)
    mobilize(sc)
    return sc


# ---------------------------------------------------------------------------
# Delivery, timesheet and change-control helpers
# ---------------------------------------------------------------------------


def read_opportunity(sc: Scenario) -> JsonDict:
    return get_success_data(sc.api.get_opportunity(sc.opportunity_id, sc.partner))


def read_deliverable(sc: Scenario, deliverable_id: str) -> JsonDict:
    return get_success_data(sc.api.get_deliverable(deliverable_id, sc.manager))


def read_sow(sc: Scenario) -> JsonDict:
    return get_success_data(sc.api.get_sow(sc.sow_id, sc.partner))


def read_engagement(sc: Scenario) -> JsonDict:
    return get_success_data(sc.api.get_engagement(sc.engagement_id, sc.partner))


def read_client(sc: Scenario) -> JsonDict:
    return get_success_data(sc.api.get_client(sc.client_id, sc.partner))


def read_consultant(sc: Scenario, consultant_id: str) -> JsonDict:
    return get_success_data(sc.api.get_consultant(consultant_id, sc.partner))


def read_change_request(sc: Scenario, change_request_id: str) -> JsonDict:
    return get_success_data(sc.api.get_change_request(change_request_id, sc.manager))


def read_time_entry(sc: Scenario, time_entry_id: str) -> JsonDict:
    return get_success_data(sc.api.get_time_entry(time_entry_id, sc.manager))


def read_quality_review(sc: Scenario, review_id: str) -> JsonDict:
    return get_success_data(sc.api.get_quality_review(review_id, sc.manager))


def engagement_version(sc: Scenario) -> int:
    return read_engagement(sc)["version"]


def assign_lead(sc: Scenario, deliverable_id: str, consultant_id: str) -> JsonDict:
    return get_success_data(
        sc.api.assign_lead(
            deliverable_id, {"lead_consultant_id": consultant_id}, sc.manager
        )
    )


def set_status(
    sc: Scenario, deliverable_id: str, target_status: str, headers=None
) -> JsonDict:
    return get_success_data(
        sc.api.set_deliverable_status(
            deliverable_id, {"target_status": target_status}, headers or sc.manager
        )
    )


def start_deliverable(
    sc: Scenario, deliverable_id: str, lead_id: Optional[str] = None
) -> JsonDict:
    if lead_id is not None:
        assign_lead(sc, deliverable_id, lead_id)
    return set_status(sc, deliverable_id, C.DELIVERABLE_IN_PROGRESS)


def accept_deliverable(sc: Scenario, deliverable_id: str) -> JsonDict:
    set_status(sc, deliverable_id, C.DELIVERABLE_SUBMITTED)
    return set_status(
        sc, deliverable_id, C.DELIVERABLE_ACCEPTED, headers=sc.client_contact
    )


def log_time(
    sc: Scenario,
    hours: float,
    week_ending_date: str,
    consultant_id: Optional[str] = None,
    deliverable_id: Optional[str] = None,
    billable: bool = True,
    headers=None,
) -> JsonDict:
    payload = F.time_entry_payload(
        sc.engagement_id,
        deliverable_id or sc.d1_id,
        consultant_id or sc.partner_id,
        week_ending_date,
        hours,
        billable,
    )
    return get_success_data(sc.api.create_time_entry(payload, headers or sc.partner))


def approve_time(sc: Scenario, time_entry_id: str) -> JsonDict:
    return get_success_data(
        sc.api.time_entry_decision(time_entry_id, {"decision": "APPROVE"}, sc.manager)
    )


def log_and_approve_time(sc: Scenario, hours: float, week_ending_date: str, **kwargs):
    entry = log_time(sc, hours, week_ending_date, **kwargs)
    approve_time(sc, entry["id"])
    return entry


def raise_change_request(sc: Scenario, **overrides: Any) -> JsonDict:
    payload = F.change_request_payload(
        sc.engagement_id, engagement_version(sc), **overrides
    )
    return get_success_data(sc.api.create_change_request(payload, sc.manager))


def assess_change_request(sc: Scenario, change_request_id: str) -> JsonDict:
    return get_success_data(sc.api.assess_impact(change_request_id, {}, sc.manager))


def leadership_approve_change(sc: Scenario, change_request_id: str) -> JsonDict:
    return get_success_data(
        sc.api.change_request_leadership_decision(
            change_request_id, {"decision": "APPROVE"}, sc.leadership
        )
    )


def client_approve_change(sc: Scenario, change_request_id: str) -> JsonDict:
    return get_success_data(
        sc.api.change_request_client_decision(
            change_request_id, {"decision": "APPROVE"}, sc.client_contact
        )
    )


def schedule_review(sc: Scenario, **overrides: Any) -> JsonDict:
    payload = F.quality_review_payload(sc.engagement_id, sc.reviewer_id, **overrides)
    return get_success_data(sc.api.create_quality_review(payload, sc.manager))


def record_review_outcome(
    sc: Scenario, review_id: str, outcome: str, findings_severity: str
) -> JsonDict:
    return get_success_data(
        sc.api.record_outcome(
            review_id,
            F.record_outcome_payload(outcome, findings_severity),
            sc.reviewer,
        )
    )


def list_escalations(sc: Scenario) -> List[JsonDict]:
    body = sc.api.list_risk_escalations(
        sc.leadership, {"engagement_id": sc.engagement_id}
    ).json()
    return body["data"]


def first_escalation(sc: Scenario) -> JsonDict:
    rows = list_escalations(sc)
    assert rows, "expected at least one risk escalation on the engagement"
    return rows[0]


def respond_to_escalation(sc: Scenario, escalation_id: str, response: str, **extra):
    payload = {"response": response}
    payload.update(extra)
    return get_success_data(
        sc.api.leadership_response(escalation_id, payload, sc.leadership)
    )


def accept_all_deliverables(sc: Scenario) -> None:
    """Take every deliverable of the pursuit to ACCEPTED in dependency order."""
    leads = [sc.consultant_id, sc.manager_id, sc.reviewer_id, sc.leadership_id]
    for index, deliverable_id in enumerate(sc.deliverable_ids):
        start_deliverable(sc, deliverable_id, lead_id=leads[index % len(leads)])
        accept_deliverable(sc, deliverable_id)


def begin_closing(sc: Scenario) -> JsonDict:
    return get_success_data(sc.api.begin_closing(sc.engagement_id, {}, sc.partner))


def close_engagement(sc: Scenario) -> JsonDict:
    return get_success_data(sc.api.close_engagement(sc.engagement_id, {}, sc.leadership))


def build_closed_engagement(api: ConsultingApiClient, **kwargs: Any) -> Scenario:
    """An ACTIVE engagement driven all the way to delivery CLOSED."""
    sc = build_active_engagement(api, **kwargs)
    accept_all_deliverables(sc)
    begin_closing(sc)
    close_engagement(sc)
    return sc


# ---------------------------------------------------------------------------
# Layer 10 - delivery in flight: leads, acceptance and the burn ledger
# ---------------------------------------------------------------------------


def build_started_engagement(
    api: ConsultingApiClient, clock: str = C.SEED_DELIVERY_CLOCK, **kwargs: Any
) -> Scenario:
    """ACTIVE engagement whose first deliverable is IN_PROGRESS with a lead."""
    sc = build_active_engagement(api, **kwargs)
    set_clock(api, clock)
    start_deliverable(sc, sc.d1_id, lead_id=sc.consultant_id)
    return sc


def build_burned_engagement(
    api: ConsultingApiClient,
    hours: List[float] = [60.0, 40.0],
    accept_first: bool = True,
    **kwargs: Any,
) -> Scenario:
    """A started engagement with the first deliverable accepted and partner
    hours approved onto the burn ledger, one line per delivery week."""
    sc = build_started_engagement(api, **kwargs)
    if accept_first:
        accept_deliverable(sc, sc.d1_id)
    weeks = [C.SEED_WEEK_1, C.SEED_WEEK_2]
    sc.extras["time_entry_ids"] = [
        log_and_approve_time(sc, amount, week)["id"]
        for amount, week in zip(hours, weeks)
    ]
    return sc


def clone_actors(sc: Scenario) -> Scenario:
    """A second, empty scenario over the same client and the same consultants."""
    return Scenario(
        api=sc.api,
        client_id=sc.client_id,
        partner_id=sc.partner_id,
        manager_id=sc.manager_id,
        consultant_id=sc.consultant_id,
        reviewer_id=sc.reviewer_id,
        leadership_id=sc.leadership_id,
    )


def build_sibling_screening_pursuit(sc: Scenario, **overrides: Any) -> Scenario:
    """A second pursuit in SCREENING, conflict-screened and awaiting a budget."""
    sib = clone_actors(sc)
    row = open_pursuit(sib, **overrides)
    sib.opportunity_id = row["id"]
    sib.opportunity_version = row["version"]
    screen_conflicts(sib)
    return sib


def build_sibling_pursuit(
    sc: Scenario,
    practice_code: str = C.SEED_PRACTICE_CODE,
    deliverables: Optional[List[JsonDict]] = None,
    **overrides: Any,
) -> Scenario:
    """A second pursuit in SCOPING sharing the first one's client and actors.

    Lead capacity is counted firm-wide across every pursuit and every client
    (PRD 3.3), so a second pursuit is the only way to build that count honestly.
    """
    sib = clone_actors(sc)
    row = open_pursuit(sib, requested_practice_code=practice_code, **overrides)
    sib.opportunity_id = row["id"]
    sib.opportunity_version = row["version"]
    screen_conflicts(sib)
    verify_budget(sib, C.SEED_VERIFIED_BUDGET_CENTS)
    get_success_data(sib.api.qualify(sib.opportunity_id, {}, sib.partner))
    row = edit_scope(sib)
    sib.opportunity_version = row["version"]
    for spec in deliverables or []:
        add_deliverable(sib, spec)
    return sib


def build_pending_client_change(
    api: ConsultingApiClient, change: Optional[JsonDict] = None, **kwargs: Any
) -> Scenario:
    """A burned engagement carrying one assessed, leadership-approved change
    request resting at PENDING_CLIENT_APPROVAL."""
    sc = build_burned_engagement(api, **kwargs)
    row = raise_change_request(sc, **(change or {}))
    assess_change_request(sc, row["id"])
    leadership_approve_change(sc, row["id"])
    sc.extras["change_request_id"] = row["id"]
    return sc


def file_satisfaction(sc: Scenario, **overrides: Any) -> JsonDict:
    return get_success_data(
        sc.api.create_satisfaction_assessment(
            F.satisfaction_payload(sc.engagement_id, **overrides), sc.client_contact
        )
    )
