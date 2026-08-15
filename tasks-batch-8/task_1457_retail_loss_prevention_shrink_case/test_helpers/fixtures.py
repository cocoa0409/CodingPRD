"""Composite setup helpers.

The interesting PRD claims require the system to be in a state that takes
5-15 API calls to reach (a case at ADJUDICATING, an issued demand, a sealed
evidence chain, a reconciled period). These helpers encapsulate those chains
so tests focus on assertions. Every helper builds preconditions from scratch
(the server restarts with an empty database before each test) and uses the
lenient get_success_data() validator so setup failures surface as clear
"Setup step failed" errors.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    ADMIN_1,
    ANALYST_1,
    HR_PARTNER_1,
    MANAGER_1,
    POS_FEED_1,
)
from .factories import (
    create_case_link_payload,
    create_case_payload,
    create_demand_payload,
    create_employee_payload,
    create_evidence_payload,
    create_event_payload,
    create_interview_payload,
    create_orc_group_payload,
    create_payment_payload,
    create_referral_packet_payload,
    create_shrink_period_payload,
    create_store_payload,
)
from .test_users import (
    make_admin_headers,
    make_analyst_headers,
    make_hr_partner_headers,
    make_manager_headers,
    make_pos_feed_headers,
)

_txn_counter = itertools.count(1)
_store_counter = itertools.count(1)
_ref_counter = itertools.count(1)


def _next(prefix):
    return f"{prefix}-{next(_txn_counter):04d}"


# ---------------------------------------------------------------------------
# Tier 0: clock and single-resource creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str, admin_id: str = ADMIN_1) -> dict:
    """Drive the logical clock (PRD §2.5); mutates no entity."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, make_admin_headers(admin_id))
    )


def make_store(store_number: str = None, name: str = None, region_code: str = "R1",
               admin_id: str = ADMIN_1) -> dict:
    store_number = store_number or _next("S")
    payload = create_store_payload(
        store_number=store_number,
        name=name or f"Store {store_number}",
        region_code=region_code,
    )
    return get_success_data(
        api_client.create_store(payload, make_admin_headers(admin_id))
    )


def make_employee(store_id: str, employee_ref: str = None, full_name: str = None,
                  hr_id: str = HR_PARTNER_1) -> dict:
    employee_ref = employee_ref or _next("E")
    payload = create_employee_payload(
        store_id, employee_ref=employee_ref, full_name=full_name or f"Employee {employee_ref}"
    )
    return get_success_data(
        api_client.create_employee(payload, make_hr_partner_headers(hr_id))
    )


def make_period(store_id: str, period_start: str = "2026-07-01T00:00:00Z",
                period_end: str = "2026-09-30T23:59:59Z",
                book_inventory_cents: int = 5_000_000,
                period_sales_cents: int = 4_000_000,
                admin_id: str = ADMIN_1) -> dict:
    payload = create_shrink_period_payload(
        store_id,
        period_start=period_start,
        period_end=period_end,
        book_inventory_cents=book_inventory_cents,
        period_sales_cents=period_sales_cents,
    )
    return get_success_data(
        api_client.create_shrink_period(payload, make_admin_headers(admin_id))
    )


def make_store_with_period(store_number: str = None, **period_kwargs):
    """Active store plus one OPEN shrink period covering the default clock
    instant 2026-08-01. Returns (store, period)."""
    store = make_store(store_number=store_number)
    period = make_period(store["id"], **period_kwargs)
    return store, period


# ---------------------------------------------------------------------------
# POS feed ingestion and alert discovery
# ---------------------------------------------------------------------------

def post_event(store_id: str, exception_type: str, amount_cents: int,
               occurred_at: str, employee_id=None, register_ref: str = "R-1",
               txn_ref: str = None, feed_id: str = POS_FEED_1) -> dict:
    payload = create_event_payload(
        store_id,
        register_ref=register_ref,
        txn_ref=txn_ref or _next("TXN"),
        exception_type=exception_type,
        amount_cents=amount_cents,
        occurred_at=occurred_at,
    )
    if employee_id is not None:
        payload["employee_id"] = employee_id
    return get_success_data(
        api_client.create_exception_event(payload, make_pos_feed_headers(feed_id))
    )


def post_events(store_id: str, events, employee_id=None, register_ref: str = "R-1"):
    """events: list of (exception_type, amount_cents, occurred_at) tuples."""
    return [
        post_event(store_id, et, amt, at, employee_id=employee_id, register_ref=register_ref)
        for et, amt, at in events
    ]


def list_alert_dicts(headers, **params):
    data, _meta = validate_paginated(api_client.list_alerts(headers, params=params or None))
    return data


def the_only_alert(store_id: str, employee_id=None, viewer_id: str = ANALYST_1) -> dict:
    """Fetch the single alert of a (store_id, employee_id) group."""
    params = {"store_id": store_id}
    if employee_id is not None:
        params["employee_id"] = employee_id
    alerts = list_alert_dicts(make_analyst_headers(viewer_id), **params)
    assert len(alerts) == 1, f"Expected exactly one alert, got {len(alerts)}"
    return alerts[0]


# ---------------------------------------------------------------------------
# Tier 1-3: case lifecycle progression
# ---------------------------------------------------------------------------

def get_case(case_id: str, viewer_id: str = MANAGER_1) -> dict:
    return get_success_data(api_client.get_case(case_id, make_manager_headers(viewer_id)))


def get_case_version(case_id: str, viewer_id: str = MANAGER_1) -> int:
    return get_case(case_id, viewer_id)["version"]


def make_manual_case(store_id: str, subject_type: str = "EXTERNAL", employee_id=None,
                     manual_loss_cents: int = 1000, creator_id: str = ANALYST_1) -> dict:
    payload = create_case_payload(
        store_id, subject_type=subject_type, manual_loss_cents=manual_loss_cents
    )
    if employee_id is not None:
        payload["employee_id"] = employee_id
    return get_success_data(
        api_client.create_case(payload, make_analyst_headers(creator_id))
    )


def assign_case(case_id: str, analyst_id: str = ANALYST_1,
                manager_id: str = MANAGER_1) -> dict:
    return get_success_data(
        api_client.assign_case(
            case_id, {"analyst_id": analyst_id}, make_manager_headers(manager_id)
        )
    )


def attach_evidence(case_id: str, actor_id: str, evidence_type: str = "PHOTO",
                    captured_at: str = "2026-07-15T10:00:00Z",
                    retention_class: str = "STANDARD") -> dict:
    payload = create_evidence_payload(
        case_id,
        evidence_type=evidence_type,
        captured_at=captured_at,
        retention_class=retention_class,
    )
    return get_success_data(
        api_client.create_evidence_item(payload, make_analyst_headers(actor_id))
    )


def advance_case(case_id: str, actor_id: str, recovered_value_cents=None) -> dict:
    payload = {}
    if recovered_value_cents is not None:
        payload["recovered_value_cents"] = recovered_value_cents
    return get_success_data(
        api_client.advance_case(case_id, payload, make_analyst_headers(actor_id))
    )


def schedule_interview(case_id: str, actor_id: str, interviewer_id: str,
                       subject_employee_id=None,
                       scheduled_start: str = "2026-08-02T09:00:00Z",
                       scheduled_end: str = "2026-08-02T10:00:00Z") -> dict:
    payload = create_interview_payload(
        case_id,
        interviewer_id,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
    )
    if subject_employee_id is not None:
        payload["subject_employee_id"] = subject_employee_id
    return get_success_data(
        api_client.create_interview(payload, make_analyst_headers(actor_id))
    )


def hold_interview(interview_id: str, interviewer_id: str, outcome: str = "ADMITTED") -> dict:
    return get_success_data(
        api_client.record_interview_outcome(
            interview_id, {"outcome": outcome}, make_analyst_headers(interviewer_id)
        )
    )


def document_interview(interview_id: str, interviewer_id: str,
                       notes: str = "Documented.") -> dict:
    return get_success_data(
        api_client.document_interview(
            interview_id, {"notes": notes}, make_analyst_headers(interviewer_id)
        )
    )


def setup_case_investigating(store_id: str, *, subject_type: str = "EXTERNAL",
                             employee_id=None, manual_loss_cents: int = 1000,
                             creator_id: str = ANALYST_1, analyst_id: str = ANALYST_1,
                             manager_id: str = MANAGER_1) -> dict:
    """Manual case created and assigned: OPEN -> INVESTIGATING."""
    case = make_manual_case(
        store_id,
        subject_type=subject_type,
        employee_id=employee_id,
        manual_loss_cents=manual_loss_cents,
        creator_id=creator_id,
    )
    case = assign_case(case["id"], analyst_id, manager_id)
    return {
        "store_id": store_id,
        "case": case,
        "creator_id": creator_id,
        "analyst_id": analyst_id,
        "manager_id": manager_id,
    }


def setup_case_ready_for_interview(store_id: str, *, with_evidence: bool = True,
                                   evidence_type: str = "PHOTO",
                                   captured_at: str = "2026-07-15T10:00:00Z",
                                   retention_class: str = "STANDARD",
                                   recovered_value_cents=None, **kw) -> dict:
    """INVESTIGATING case advanced to READY_FOR_INTERVIEW (evidence gate)."""
    ctx = setup_case_investigating(store_id, **kw)
    if with_evidence:
        ctx["evidence"] = attach_evidence(
            ctx["case"]["id"], ctx["analyst_id"],
            evidence_type=evidence_type, captured_at=captured_at,
            retention_class=retention_class,
        )
    ctx["case"] = advance_case(
        ctx["case"]["id"], ctx["analyst_id"], recovered_value_cents=recovered_value_cents
    )
    return ctx


def setup_case_interviewed(store_id: str, *, interviewer_id: str = None,
                           outcome: str = "ADMITTED", notes: str = "Documented.",
                           scheduled_start: str = "2026-08-02T09:00:00Z",
                           scheduled_end: str = "2026-08-02T10:00:00Z",
                           **kw) -> dict:
    """READY_FOR_INTERVIEW case whose interview is documented: -> INTERVIEWED."""
    ctx = setup_case_ready_for_interview(store_id, **kw)
    interviewer_id = interviewer_id or ctx["analyst_id"]
    subject_employee_id = ctx["case"].get("employee_id")
    interview = schedule_interview(
        ctx["case"]["id"], ctx["analyst_id"], interviewer_id,
        subject_employee_id=subject_employee_id,
        scheduled_start=scheduled_start, scheduled_end=scheduled_end,
    )
    hold_interview(interview["id"], interviewer_id, outcome=outcome)
    interview = document_interview(interview["id"], interviewer_id, notes=notes)
    ctx["interview"] = interview
    ctx["interviewer_id"] = interviewer_id
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


def setup_case_adjudicating(store_id: str, **kw) -> dict:
    """INTERVIEWED case advanced to ADJUDICATING."""
    ctx = setup_case_interviewed(store_id, **kw)
    ctx["case"] = advance_case(ctx["case"]["id"], ctx["analyst_id"])
    return ctx


def adjudicate_case(case_id: str, adjudicator_id: str, *, subject_type: str = "EXTERNAL",
                    decision: str = "SUBSTANTIATED", employment_action=None,
                    restitution_waived=None, documentation_override=None) -> dict:
    payload = {"decision": decision}
    if employment_action is not None:
        payload["employment_action"] = employment_action
    if restitution_waived is not None:
        payload["restitution_waived"] = restitution_waived
    if documentation_override is not None:
        payload["documentation_override"] = documentation_override
    if subject_type == "EMPLOYEE":
        headers = make_hr_partner_headers(adjudicator_id)
    else:
        headers = make_manager_headers(adjudicator_id)
    return get_success_data(api_client.adjudicate_case(case_id, payload, headers))


def setup_case_closed_substantiated(store_id: str, *, subject_type: str = "EXTERNAL",
                                    employee_id=None, manual_loss_cents: int = 10000,
                                    restitution_waived: bool = True,
                                    adjudicator_id: str = None,
                                    employment_action=None, **kw) -> dict:
    """Full pipeline: case adjudicated SUBSTANTIATED.

    The caller must ensure the store has a period covering the current logical
    date (loss posting target). With restitution_waived False, an ACTUAL_LOSS
    demand is drafted first so the demand gate passes.
    """
    ctx = setup_case_adjudicating(
        store_id, subject_type=subject_type, employee_id=employee_id,
        manual_loss_cents=manual_loss_cents, **kw,
    )
    if not restitution_waived:
        ctx["demand"] = draft_demand(ctx["case"]["id"], ctx["analyst_id"])
    adjudicator_id = adjudicator_id or (
        HR_PARTNER_1 if subject_type == "EMPLOYEE" else MANAGER_1
    )
    ctx["adjudicator_id"] = adjudicator_id
    ctx["case"] = adjudicate_case(
        ctx["case"]["id"], adjudicator_id,
        subject_type=subject_type, decision="SUBSTANTIATED",
        employment_action=employment_action, restitution_waived=restitution_waived,
    )
    return ctx


# ---------------------------------------------------------------------------
# Civil demands and restitution payments
# ---------------------------------------------------------------------------

def draft_demand(case_id: str, actor_id: str, *, basis: str = "ACTUAL_LOSS",
                 priors_offense_count=None, recovery_cost_cents=None,
                 expected_case_version=None) -> dict:
    """Draft a demand; reads the case's current version for OCC when not given."""
    if expected_case_version is None:
        expected_case_version = get_case_version(case_id)
    payload = create_demand_payload(
        case_id, expected_case_version, basis=basis
    )
    if priors_offense_count is not None:
        payload["priors_offense_count"] = priors_offense_count
    if recovery_cost_cents is not None:
        payload["recovery_cost_cents"] = recovery_cost_cents
    return get_success_data(
        api_client.create_civil_demand(payload, make_analyst_headers(actor_id))
    )


def issue_demand(demand_id: str, issuer_id: str = MANAGER_1) -> dict:
    return get_success_data(
        api_client.issue_civil_demand(demand_id, make_manager_headers(issuer_id))
    )


def setup_case_with_issued_demand(store_id: str, *, manual_loss_cents: int = 30000,
                                  basis: str = "ACTUAL_LOSS",
                                  priors_offense_count=None,
                                  recovery_cost_cents=None,
                                  subject_type: str = "EXTERNAL",
                                  employee_id=None,
                                  creator_id: str = ANALYST_1,
                                  analyst_id: str = ANALYST_1,
                                  interviewer_id: str = ANALYST_1,
                                  issuer_id: str = MANAGER_1,
                                  **kw) -> dict:
    """Case walked to INTERVIEWED; demand drafted by the assignee and issued
    by a manager. Returns ctx with case + demand."""
    ctx = setup_case_interviewed(
        store_id, subject_type=subject_type, employee_id=employee_id,
        manual_loss_cents=manual_loss_cents, creator_id=creator_id,
        analyst_id=analyst_id, interviewer_id=interviewer_id, **kw,
    )
    demand = draft_demand(
        ctx["case"]["id"], analyst_id,
        basis=basis, priors_offense_count=priors_offense_count,
        recovery_cost_cents=recovery_cost_cents,
    )
    demand = issue_demand(demand["id"], issuer_id)
    ctx["demand"] = demand
    ctx["issuer_id"] = issuer_id
    return ctx


def record_payment(demand_id: str, amount_cents: int, method: str = "CASH",
                   actor_id: str = ANALYST_1) -> dict:
    payload = create_payment_payload(
        demand_id, amount_cents=amount_cents, method=method
    )
    return get_success_data(
        api_client.create_restitution_payment(payload, make_analyst_headers(actor_id))
    )


def post_payment(payment_id: str, actor_id: str = ANALYST_1) -> dict:
    return get_success_data(
        api_client.post_restitution_payment(payment_id, make_analyst_headers(actor_id))
    )


def return_payment(payment_id: str, actor_id: str = ANALYST_1) -> dict:
    return get_success_data(
        api_client.return_restitution_payment(payment_id, make_analyst_headers(actor_id))
    )


def record_and_post_payment(demand_id: str, amount_cents: int, method: str = "CASH",
                            actor_id: str = ANALYST_1) -> dict:
    payment = record_payment(demand_id, amount_cents, method=method, actor_id=actor_id)
    return post_payment(payment["id"], actor_id)


# ---------------------------------------------------------------------------
# Shrink period count / reconcile
# ---------------------------------------------------------------------------

def get_period(period_id: str, admin_id: str = ADMIN_1) -> dict:
    return get_success_data(
        api_client.get_shrink_period(period_id, make_admin_headers(admin_id))
    )


def record_count(period_id: str, counted_inventory_cents: int,
                 expected_shrink_period_version=None, admin_id: str = ADMIN_1) -> dict:
    if expected_shrink_period_version is None:
        expected_shrink_period_version = get_period(period_id, admin_id)["version"]
    payload = {
        "counted_inventory_cents": counted_inventory_cents,
        "expected_shrink_period_version": expected_shrink_period_version,
    }
    return get_success_data(
        api_client.record_shrink_count(period_id, payload, make_admin_headers(admin_id))
    )


def reconcile_period(period_id: str, admin_id: str = ADMIN_1) -> dict:
    return get_success_data(
        api_client.reconcile_shrink_period(period_id, make_admin_headers(admin_id))
    )


def close_period(period_id: str, admin_id: str = ADMIN_1) -> dict:
    return get_success_data(
        api_client.close_shrink_period(period_id, make_admin_headers(admin_id))
    )


# ---------------------------------------------------------------------------
# Evidence custody and referral packets
# ---------------------------------------------------------------------------

def collect_custody(evidence_id: str, actor_id: str = ANALYST_1,
                    note: str = None) -> dict:
    payload = {"action": "COLLECTED"}
    if note is not None:
        payload["note"] = note
    return get_success_data(
        api_client.create_custody_event(evidence_id, payload, make_analyst_headers(actor_id))
    )


def collect_and_seal(evidence_id: str, actor_id: str = ANALYST_1) -> dict:
    """Append COLLECTED custody, then seal (seal requires a prior COLLECTED)."""
    collect_custody(evidence_id, actor_id)
    return get_success_data(
        api_client.seal_evidence(evidence_id, make_analyst_headers(actor_id))
    )


def get_evidence(evidence_id: str, viewer_id: str = MANAGER_1) -> dict:
    return get_success_data(
        api_client.get_evidence_item(evidence_id, make_manager_headers(viewer_id))
    )


def make_packet(case_id: str, actor_id: str, jurisdiction_code: str = "CA-LA") -> dict:
    payload = create_referral_packet_payload(case_id, jurisdiction_code=jurisdiction_code)
    return get_success_data(
        api_client.create_referral_packet(payload, make_analyst_headers(actor_id))
    )


def seal_packet(packet_id: str, actor_id: str) -> dict:
    return get_success_data(
        api_client.seal_referral_packet(packet_id, make_analyst_headers(actor_id))
    )


def submit_packet(packet_id: str, manager_id: str = MANAGER_1) -> dict:
    return get_success_data(
        api_client.submit_referral_packet(packet_id, make_manager_headers(manager_id))
    )


def acknowledge_packet(packet_id: str, outcome: str, manager_id: str = MANAGER_1,
                       return_reason: str = None) -> dict:
    payload = {"outcome": outcome}
    if return_reason is not None:
        payload["return_reason"] = return_reason
    return get_success_data(
        api_client.acknowledge_referral_packet(
            packet_id, payload, make_manager_headers(manager_id)
        )
    )


def get_packet(packet_id: str, viewer_id: str = MANAGER_1) -> dict:
    return get_success_data(
        api_client.get_referral_packet(packet_id, make_manager_headers(viewer_id))
    )


# ---------------------------------------------------------------------------
# ORC groups and case links
# ---------------------------------------------------------------------------

def make_orc_group(name: str = None, description: str = None,
                   manager_id: str = MANAGER_1) -> dict:
    payload = create_orc_group_payload(name=name or _next("Ring"))
    if description is not None:
        payload["description"] = description
    return get_success_data(
        api_client.create_orc_group(payload, make_manager_headers(manager_id))
    )


def propose_link(case_id: str, orc_group_id: str, link_score: int = 80,
                 actor_id: str = ANALYST_1) -> dict:
    payload = create_case_link_payload(case_id, orc_group_id, link_score=link_score)
    return get_success_data(
        api_client.create_case_link(payload, make_analyst_headers(actor_id))
    )


def confirm_link(link_id: str, manager_id: str = MANAGER_1) -> dict:
    return get_success_data(
        api_client.confirm_case_link(link_id, make_manager_headers(manager_id))
    )


def reject_link(link_id: str, manager_id: str = MANAGER_1) -> dict:
    return get_success_data(
        api_client.reject_case_link(link_id, make_manager_headers(manager_id))
    )


def get_group(group_id: str, viewer_id: str = MANAGER_1) -> dict:
    return get_success_data(
        api_client.get_orc_group(group_id, make_manager_headers(viewer_id))
    )
