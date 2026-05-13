"""Composite setup helpers for the Government Hotline test suite.

Most interesting test claims need the system in a specific state reached
through 5-15 API calls (department → handler → category-rule →
work-order → classify → dispatch → accept → resolve). These helpers
encapsulate those preambles so test bodies stay focused on assertions.

Identity threading (PRD §2.1):
- DepartmentHandler is ENTITY-BACKED: 'When X-User-Role is
  DepartmentHandler, X-User-ID is the id of the acting Handler;
  ownership checks on any resource that references a Handler (notably
  whether the caller is the LEAD assignment's handler_id when resuming
  or resolving) compare the resource's foreign-key field to X-User-ID.'
  Every ownership-gated call by a DepartmentHandler MUST use
  make_department_handler_headers(handler['id']), never a shared
  fallback string.
- PlatformAdmin, HotlineOperator, Dispatcher, Supervisor, SurveyAgent
  are OPAQUE — shared constants are canonical.

Setup helpers use get_success_data (lenient), so a broken precondition
surfaces as a clear setup error rather than a confusing assertion
failure inside the test body.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .factories import (
    classify_work_order_payload,
    clock_advance_payload,
    create_category_rule_payload,
    create_department_payload,
    create_handler_payload,
    create_survey_payload,
    create_work_order_payload,
    pause_work_order_payload,
    reassign_assignment_payload,
    reject_assignment_payload,
    reject_work_order_payload,
    resolve_work_order_payload,
    respond_survey_payload,
    submit_opinion_payload,
    unique_category_code,
    unique_department_code,
    unique_jurisdiction_code,
    unique_sub_category_code,
    update_handler_payload,
)
from .test_users import (
    TEST_USERS,
    make_department_handler_headers,
)


# ===========================================================================
# Shared role-header constants (opaque roles — safe as module constants)
# ===========================================================================
PA = TEST_USERS["platform_admin_headers"]
PA_ALT = TEST_USERS["platform_admin_headers_alt"]
HO = TEST_USERS["hotline_operator_headers"]
HO_ALT = TEST_USERS["hotline_operator_headers_alt"]
DISP = TEST_USERS["dispatcher_headers"]
DISP_ALT = TEST_USERS["dispatcher_headers_alt"]
SUP = TEST_USERS["supervisor_headers"]
SA = TEST_USERS["survey_agent_headers"]


# ===========================================================================
# Test-harness drivers (PRD §2.10)
# ===========================================================================
def advance_clock(seconds: int,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §2.10: 'A clock-advance capability accepts a seconds body
    field and walks the server's logical clock forward by that many
    seconds.'"""
    return get_success_data(api_client.clock_advance(
        clock_advance_payload(seconds=seconds), headers or PA,
    ))


def align_clock_to_business_day_start() -> Dict[str, Any]:
    """Snap the logical clock forward to the next Monday 09:00 UTC,
    then advance an extra minute so subsequent setup HTTP calls land
    safely inside the business window even when wall-clock-vs-logical
    drift, sub-second flooring, or sequential request latency would
    otherwise leave the registration instant straddling 09:00.

    PRD §2.7 fixes business days as Monday-Friday 09:00-17:00 UTC.
    Tests that assert wall-clock-derived warning-state pct boundaries
    need the registration instant and the subsequent advance to lie
    entirely inside a single business day so that the wall-clock
    deadline span equals committed-business-hours * 3600s.
    """
    from datetime import datetime, timezone, timedelta
    # Read current logical clock via a no-op advance.
    data = advance_clock(0)
    now_iso = data["now"]
    if now_iso.endswith("Z"):
        now_iso = now_iso[:-1] + "+00:00"
    now_dt = datetime.fromisoformat(now_iso).astimezone(timezone.utc)
    # Next Monday 09:00 UTC strictly after now_dt.
    days_ahead = (0 - now_dt.weekday()) % 7  # 0 == Monday
    target = now_dt.replace(hour=9, minute=0, second=0, microsecond=0)
    target = target + timedelta(days=days_ahead)
    if target <= now_dt:
        target = target + timedelta(days=7)
    # Add a 60-second buffer so subsequent setup latency and sub-second
    # rounding cannot push the registration instant back across 09:00.
    target = target + timedelta(seconds=60)
    delta = int((target - now_dt).total_seconds())
    if delta > 0:
        return advance_clock(delta)
    return data


def run_sweep(headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §2.10: 'A sweep capability iterates the time-gated work that
    would otherwise be performed by a background job.'"""
    return get_success_data(api_client.sweep_run(headers or PA))


# ===========================================================================
# Department / Handler / CategoryRule creation
# ===========================================================================
def create_department(*,
                      name: Optional[str] = None,
                      code: Optional[str] = None,
                      jurisdiction_codes: Optional[List[str]] = None,
                      category_codes: Optional[List[str]] = None,
                      status: Optional[str] = None) -> Dict[str, Any]:
    """PRD §3.1: 'A Department is created with a name, a stable
    kebab-case code...'"""
    kwargs: Dict[str, Any] = {}
    if name is not None:
        kwargs["name"] = name
    if code is not None:
        kwargs["code"] = code
    if jurisdiction_codes is not None:
        kwargs["jurisdiction_codes"] = jurisdiction_codes
    if category_codes is not None:
        kwargs["category_codes"] = category_codes
    if status is not None:
        kwargs["status"] = status
    return get_success_data(api_client.create_department(
        create_department_payload(**kwargs), PA,
    ))


def create_handler(*, department_id: str,
                   full_name: Optional[str] = None,
                   status: Optional[str] = None) -> Dict[str, Any]:
    """PRD §3.1: 'A Handler is bound to a department at creation time
    through the department_id field.'"""
    kwargs: Dict[str, Any] = {"department_id": department_id}
    if full_name is not None:
        kwargs["full_name"] = full_name
    if status is not None:
        kwargs["status"] = status
    return get_success_data(api_client.create_handler(
        create_handler_payload(**kwargs), PA,
    ))


def create_category_rule(*,
                         lead_department_code: str,
                         category_code: Optional[str] = None,
                         sub_category_code: Optional[str] = None,
                         supporting_department_codes: Optional[List[str]] = None,
                         statutory_time_limit_hours: int = 72,
                         committed_time_limit_hours: int = 48,
                         difficulty_base: Optional[int] = None,
                         ) -> Dict[str, Any]:
    """PRD §3.1: 'A CategoryRule ties a (category_code, sub_category_code)
    pair... to a lead_department_code and a list of
    supporting_department_codes.'"""
    kwargs: Dict[str, Any] = {
        "lead_department_code": lead_department_code,
        "statutory_time_limit_hours": statutory_time_limit_hours,
        "committed_time_limit_hours": committed_time_limit_hours,
    }
    if category_code is not None:
        kwargs["category_code"] = category_code
    if sub_category_code is not None:
        kwargs["sub_category_code"] = sub_category_code
    if supporting_department_codes is not None:
        kwargs["supporting_department_codes"] = supporting_department_codes
    if difficulty_base is not None:
        kwargs["difficulty_base"] = difficulty_base
    return get_success_data(api_client.create_category_rule(
        create_category_rule_payload(**kwargs), PA,
    ))


# ===========================================================================
# Composite routing-world setup
# ===========================================================================
def setup_routing_world(*,
                        jurisdiction_code: Optional[str] = None,
                        num_supporting: int = 0,
                        statutory_hours: int = 72,
                        committed_hours: int = 48,
                        difficulty_base: Optional[int] = None,
                        ) -> Dict[str, Any]:
    """Build a complete routing world ready for WorkOrder creation.

    Returns dict with:
      - jurisdiction_code
      - lead_department, supporting_departments (list)
      - category_rule
      - lead_handler (ACTIVE handler in lead dept)
      - supporting_handlers (one ACTIVE handler per supporting dept)

    PRD §3.1, §3.3.
    """
    jc = jurisdiction_code or unique_jurisdiction_code()
    cat = unique_category_code()
    sub = unique_sub_category_code()
    lead_code = unique_department_code()
    lead_dept = create_department(
        code=lead_code, jurisdiction_codes=[jc], category_codes=[],
    )
    supporting_depts: List[Dict[str, Any]] = []
    supporting_codes: List[str] = []
    for _ in range(num_supporting):
        sc = unique_department_code()
        sd = create_department(
            code=sc, jurisdiction_codes=[jc], category_codes=[],
        )
        supporting_depts.append(sd)
        supporting_codes.append(sc)
    rule = create_category_rule(
        category_code=cat, sub_category_code=sub,
        lead_department_code=lead_code,
        supporting_department_codes=supporting_codes,
        statutory_time_limit_hours=statutory_hours,
        committed_time_limit_hours=committed_hours,
        difficulty_base=difficulty_base,
    )
    lead_handler = create_handler(department_id=lead_dept["id"])
    supporting_handlers = [
        create_handler(department_id=sd["id"]) for sd in supporting_depts
    ]
    return {
        "jurisdiction_code": jc,
        "lead_department": lead_dept,
        "supporting_departments": supporting_depts,
        "category_rule": rule,
        "lead_handler": lead_handler,
        "supporting_handlers": supporting_handlers,
    }


# ===========================================================================
# WorkOrder lifecycle helpers
# ===========================================================================
def register_work_order(*, jurisdiction_code: str,
                        category_code: str,
                        sub_category_code: str,
                        urgency: Optional[str] = None,
                        anonymous: bool = False,
                        caller_phone: Optional[str] = None,
                        content_text: Optional[str] = None,
                        headers: Optional[Dict[str, str]] = None,
                        **overrides: Any) -> Dict[str, Any]:
    """PRD §3.2 — POST /work-orders as HotlineOperator."""
    kwargs: Dict[str, Any] = {
        "jurisdiction_code": jurisdiction_code,
        "category_code": category_code,
        "sub_category_code": sub_category_code,
        "anonymous": anonymous,
    }
    if urgency is not None:
        kwargs["urgency"] = urgency
    if caller_phone is not None:
        kwargs["caller_phone"] = caller_phone
    if content_text is not None:
        kwargs["content_text"] = content_text
    kwargs.update(overrides)
    return get_success_data(api_client.create_work_order(
        create_work_order_payload(**kwargs), headers or HO,
    ))


def classify(work_order_id: str, *, mode: str = "RULE_BASED",
             headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §3.3 — POST /work-orders/{id}/classify as Dispatcher."""
    return get_success_data(api_client.classify_work_order(
        work_order_id, classify_work_order_payload(mode=mode),
        headers or DISP,
    ))


def dispatch(work_order_id: str,
             headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §3.4 — POST /work-orders/{id}/dispatch as Dispatcher."""
    return get_success_data(api_client.dispatch_work_order(
        work_order_id, headers or DISP,
    ))


def list_assignments(work_order_id: str,
                     headers: Optional[Dict[str, str]] = None
                     ) -> List[Dict[str, Any]]:
    """Read /work-orders/{id}/assignments and return list."""
    resp = api_client.list_assignments(work_order_id, headers or DISP)
    data, _meta = validate_paginated(resp)
    return data


def find_lead_assignment(work_order_id: str,
                         headers: Optional[Dict[str, str]] = None
                         ) -> Dict[str, Any]:
    """Return the LEAD DepartmentAssignment for a work order."""
    for a in list_assignments(work_order_id, headers):
        if a.get("role") == "LEAD":
            return a
    raise AssertionError(
        f"No LEAD assignment found for work_order_id={work_order_id}"
    )


def find_supporting_assignments(work_order_id: str,
                                headers: Optional[Dict[str, str]] = None
                                ) -> List[Dict[str, Any]]:
    """Return all SUPPORTING DepartmentAssignments for a work order."""
    return [a for a in list_assignments(work_order_id, headers)
            if a.get("role") == "SUPPORTING"]


def accept_assignment(work_order_id: str, assignment_id: str,
                      handler: Dict[str, Any]) -> Dict[str, Any]:
    """PRD §3.5 — POST /accept by the handler. Threads
    make_department_handler_headers(handler['id']) so the ownership
    check 'Handler.department_id == DepartmentAssignment.department_id'
    can match a real handler row."""
    return get_success_data(api_client.accept_assignment(
        work_order_id, assignment_id,
        make_department_handler_headers(handler["id"]),
    ))


def submit_opinion(work_order_id: str, assignment_id: str,
                   handler: Dict[str, Any], *,
                   opinion_text: str = "ok",
                   opinion_decision: str = "AGREE") -> Dict[str, Any]:
    """PRD §3.7 — POST /opinion as supporting handler."""
    return get_success_data(api_client.submit_opinion(
        work_order_id, assignment_id,
        submit_opinion_payload(
            opinion_text=opinion_text, opinion_decision=opinion_decision,
        ),
        make_department_handler_headers(handler["id"]),
    ))


def resolve(work_order_id: str, *, handler: Dict[str, Any],
            resolution_summary: str = "case resolved") -> Dict[str, Any]:
    """PRD §3.7 — POST /resolve as LEAD handler."""
    return get_success_data(api_client.resolve_work_order(
        work_order_id,
        resolve_work_order_payload(resolution_summary=resolution_summary),
        make_department_handler_headers(handler["id"]),
    ))


def pause(work_order_id: str, *, handler: Dict[str, Any],
          reason: str = "need clarification") -> Dict[str, Any]:
    """PRD §3.6 — POST /pause as LEAD handler."""
    return get_success_data(api_client.pause_work_order(
        work_order_id, pause_work_order_payload(reason=reason),
        make_department_handler_headers(handler["id"]),
    ))


def resume(work_order_id: str, *, handler: Dict[str, Any]) -> Dict[str, Any]:
    """PRD §3.6 — POST /resume as LEAD handler."""
    return get_success_data(api_client.resume_work_order(
        work_order_id, make_department_handler_headers(handler["id"]),
    ))


def get_work_order(work_order_id: str,
                   headers: Optional[Dict[str, str]] = None
                   ) -> Dict[str, Any]:
    """PRD §3.8 — GET /work-orders/{id} recomputes warning_state on read."""
    return get_success_data(api_client.get_work_order(
        work_order_id, headers or DISP,
    ))


def get_department(department_id: str,
                   headers: Optional[Dict[str, str]] = None
                   ) -> Dict[str, Any]:
    return get_success_data(api_client.get_department(
        department_id, headers or PA,
    ))


def get_handler(handler_id: str,
                headers: Optional[Dict[str, str]] = None
                ) -> Dict[str, Any]:
    return get_success_data(api_client.get_handler(
        handler_id, headers or PA,
    ))


# ===========================================================================
# Composite progression fixtures
# ===========================================================================
def setup_in_progress(*, urgency: str = "NORMAL",
                      num_supporting: int = 0,
                      statutory_hours: int = 72,
                      committed_hours: int = 48,
                      difficulty_base: Optional[int] = None,
                      ) -> Dict[str, Any]:
    """Build routing world → register → classify → dispatch → LEAD accept.

    Returns a dict containing every entity created plus the LEAD
    assignment. WorkOrder.status is IN_PROGRESS afterward.

    PRD §3.2 – §3.5.
    """
    world = setup_routing_world(
        num_supporting=num_supporting,
        statutory_hours=statutory_hours,
        committed_hours=committed_hours,
        difficulty_base=difficulty_base,
    )
    wo = register_work_order(
        jurisdiction_code=world["jurisdiction_code"],
        category_code=world["category_rule"]["category_code"],
        sub_category_code=world["category_rule"]["sub_category_code"],
        urgency=urgency,
    )
    classify(wo["id"])
    dispatch(wo["id"])
    lead_assign = find_lead_assignment(wo["id"])
    accept_assignment(wo["id"], lead_assign["id"], world["lead_handler"])
    world["work_order"] = get_work_order(wo["id"])
    world["lead_assignment"] = find_lead_assignment(wo["id"])
    world["supporting_assignments"] = find_supporting_assignments(wo["id"])
    return world


def setup_supporting_accepted(*, urgency: str = "NORMAL",
                              num_supporting: int = 1,
                              statutory_hours: int = 72,
                              committed_hours: int = 48,
                              difficulty_base: Optional[int] = None,
                              ) -> Dict[str, Any]:
    """Build a joint-handling case where LEAD and all SUPPORTING
    assignments have been ACCEPTED (but no opinions submitted yet).

    PRD §3.4, §3.5, §3.7.
    """
    world = setup_in_progress(
        urgency=urgency, num_supporting=num_supporting,
        statutory_hours=statutory_hours,
        committed_hours=committed_hours,
        difficulty_base=difficulty_base,
    )
    for assign, handler in zip(world["supporting_assignments"],
                               world["supporting_handlers"]):
        accept_assignment(world["work_order"]["id"], assign["id"], handler)
    world["work_order"] = get_work_order(world["work_order"]["id"])
    world["supporting_assignments"] = find_supporting_assignments(
        world["work_order"]["id"],
    )
    return world


def setup_all_opinions_submitted(*,
                                 supporting_decisions: List[str],
                                 urgency: str = "NORMAL",
                                 statutory_hours: int = 72,
                                 committed_hours: int = 48,
                                 difficulty_base: Optional[int] = None,
                                 ) -> Dict[str, Any]:
    """Joint-handling WO whose every SUPPORTING assignment is
    OPINION_SUBMITTED with the supplied decisions (one per supporting
    department). The LEAD is ACCEPTED but has not yet resolved.

    PRD §3.7.
    """
    world = setup_supporting_accepted(
        urgency=urgency, num_supporting=len(supporting_decisions),
        statutory_hours=statutory_hours,
        committed_hours=committed_hours,
        difficulty_base=difficulty_base,
    )
    for assign, handler, decision in zip(world["supporting_assignments"],
                                         world["supporting_handlers"],
                                         supporting_decisions):
        submit_opinion(
            world["work_order"]["id"], assign["id"], handler,
            opinion_decision=decision,
        )
    world["work_order"] = get_work_order(world["work_order"]["id"])
    world["supporting_assignments"] = find_supporting_assignments(
        world["work_order"]["id"],
    )
    return world


def setup_resolved(*, urgency: str = "NORMAL",
                   num_supporting: int = 0,
                   anonymous: bool = False,
                   caller_phone: Optional[str] = None,
                   statutory_hours: int = 72,
                   committed_hours: int = 48,
                   difficulty_base: Optional[int] = None,
                   resolution_summary: str = "case resolved",
                   ) -> Dict[str, Any]:
    """Lifecycle ending in WorkOrder.status = RESOLVED. For joint cases,
    all supporting opinions are AGREE.

    PRD §3.7.
    """
    # Build a fresh routing world (we may reuse handlers but each call
    # gets its own WO so the lead_handler's open_assignment_count stays
    # at most 1 across the run).
    world = setup_routing_world(
        num_supporting=num_supporting,
        statutory_hours=statutory_hours,
        committed_hours=committed_hours,
        difficulty_base=difficulty_base,
    )
    wo = register_work_order(
        jurisdiction_code=world["jurisdiction_code"],
        category_code=world["category_rule"]["category_code"],
        sub_category_code=world["category_rule"]["sub_category_code"],
        urgency=urgency, anonymous=anonymous,
        caller_phone=caller_phone,
    )
    classify(wo["id"])
    dispatch(wo["id"])
    lead_assign = find_lead_assignment(wo["id"])
    accept_assignment(wo["id"], lead_assign["id"], world["lead_handler"])
    # Supporting: accept and submit AGREE opinion.
    sup_assigns = find_supporting_assignments(wo["id"])
    for assign, handler in zip(sup_assigns, world["supporting_handlers"]):
        accept_assignment(wo["id"], assign["id"], handler)
        submit_opinion(wo["id"], assign["id"], handler,
                       opinion_decision="AGREE")
    resolve(wo["id"], handler=world["lead_handler"],
            resolution_summary=resolution_summary)
    world["work_order"] = get_work_order(wo["id"])
    world["lead_assignment"] = find_lead_assignment(wo["id"])
    world["supporting_assignments"] = find_supporting_assignments(wo["id"])
    return world


def setup_followed_up(*, urgency: str = "NORMAL",
                      num_supporting: int = 0,
                      survey_score: int = 5,
                      statutory_hours: int = 72,
                      committed_hours: int = 48,
                      difficulty_base: Optional[int] = None,
                      ) -> Dict[str, Any]:
    """Lifecycle through RESOLVED → SURVEY_DISPATCHED → SURVEY_RESPONDED
    so WorkOrder.status = FOLLOWED_UP. Auto-dispatched survey has
    channel=CALL because caller is reachable.

    PRD §3.7, §3.9.
    """
    world = setup_resolved(
        urgency=urgency, num_supporting=num_supporting,
        statutory_hours=statutory_hours,
        committed_hours=committed_hours,
        difficulty_base=difficulty_base,
    )
    # Survey is auto-dispatched at resolve; fetch the latest survey.
    surveys = list_surveys(world["work_order"]["id"])
    assert surveys, "Expected auto-dispatched survey after resolve"
    survey = surveys[-1]
    get_success_data(api_client.respond_survey(
        survey["id"], respond_survey_payload(score=survey_score), SA,
    ))
    world["work_order"] = get_work_order(world["work_order"]["id"])
    world["survey"] = survey
    return world


def list_surveys(work_order_id: str,
                 headers: Optional[Dict[str, str]] = None
                 ) -> List[Dict[str, Any]]:
    resp = api_client.list_surveys(work_order_id, headers or PA)
    data, _meta = validate_paginated(resp)
    return data


def list_audit_logs(*, work_order_id: Optional[str] = None,
                    action: Optional[str] = None,
                    headers: Optional[Dict[str, str]] = None
                    ) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"limit": 100}
    if work_order_id:
        params["work_order_id"] = work_order_id
    if action:
        params["action"] = action
    resp = api_client.list_audit_logs(headers or PA, params=params)
    data, _meta = validate_paginated(resp)
    return data


def list_sync_events(*, work_order_id: Optional[str] = None,
                     event_type: Optional[str] = None,
                     target_platform: Optional[str] = None,
                     delivery_status: Optional[str] = None,
                     headers: Optional[Dict[str, str]] = None
                     ) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"limit": 100}
    if work_order_id:
        params["work_order_id"] = work_order_id
    if event_type:
        params["event_type"] = event_type
    if target_platform:
        params["target_platform"] = target_platform
    if delivery_status:
        params["delivery_status"] = delivery_status
    resp = api_client.list_sync_events(headers or PA, params=params)
    data, _meta = validate_paginated(resp)
    return data


def list_supervision_tasks(*, work_order_id: Optional[str] = None,
                           status: Optional[str] = None,
                           reason: Optional[str] = None,
                           headers: Optional[Dict[str, str]] = None
                           ) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"limit": 100}
    if status:
        params["status"] = status
    if reason:
        params["reason"] = reason
    resp = api_client.list_supervision(headers or SUP, params=params)
    data, _meta = validate_paginated(resp)
    # Optional client-side filter by work_order_id.
    if work_order_id:
        data = [t for t in data if t.get("work_order_id") == work_order_id]
    return data


# ===========================================================================
# Targeted scenario fixtures driven by SCAFFOLD_DIFFICULTY_DESIGN
# ===========================================================================
def setup_for_difficulty_dual_variant(
    *, urgency: str = "NORMAL", difficulty_base: int = 2,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Difficulty Rule 1 (dual_variant_calc):
    registration vs post-classification variants.

    Returns (world, work_order_after_registration). The work order has
    one supporting department so classification will set joint_handling
    true and the post-classification score will be larger.

    PRD §3.2, §3.3, §3.12.
    """
    world = setup_routing_world(
        num_supporting=1, statutory_hours=72, committed_hours=48,
        difficulty_base=difficulty_base,
    )
    wo = register_work_order(
        jurisdiction_code=world["jurisdiction_code"],
        category_code=world["category_rule"]["category_code"],
        sub_category_code=world["category_rule"]["sub_category_code"],
        urgency=urgency,
    )
    return world, wo


def setup_three_resolved_with_surveys(*,
                                      scores_for_handler_a: List[int],
                                      scores_for_handler_b: List[int],
                                      ) -> Dict[str, Any]:
    """For Difficulty Rule 1 (satisfaction_index variants): create N
    RESOLVED+RESPONDED WOs in a single department but split across two
    handlers, with specific survey scores. The lead department serves
    every WO; each WO is accepted by exactly one of two handlers in that
    department.

    PRD §3.14, §3.9.
    """
    jc = unique_jurisdiction_code()
    cat = unique_category_code()
    sub = unique_sub_category_code()
    lead_code = unique_department_code()
    lead_dept = create_department(
        code=lead_code, jurisdiction_codes=[jc], category_codes=[],
    )
    create_category_rule(
        category_code=cat, sub_category_code=sub,
        lead_department_code=lead_code,
        supporting_department_codes=[],
        statutory_time_limit_hours=72,
        committed_time_limit_hours=48,
    )
    handler_a = create_handler(department_id=lead_dept["id"])
    handler_b = create_handler(department_id=lead_dept["id"])

    work_orders_a: List[Dict[str, Any]] = []
    work_orders_b: List[Dict[str, Any]] = []
    for score in scores_for_handler_a:
        wo = register_work_order(
            jurisdiction_code=jc, category_code=cat, sub_category_code=sub,
        )
        classify(wo["id"])
        dispatch(wo["id"])
        lead_assign = find_lead_assignment(wo["id"])
        accept_assignment(wo["id"], lead_assign["id"], handler_a)
        resolve(wo["id"], handler=handler_a)
        # Auto-survey may or may not exist; fetch and respond.
        surveys = list_surveys(wo["id"])
        if surveys:
            get_success_data(api_client.respond_survey(
                surveys[-1]["id"], respond_survey_payload(score=score), SA,
            ))
        work_orders_a.append(get_work_order(wo["id"]))
    for score in scores_for_handler_b:
        wo = register_work_order(
            jurisdiction_code=jc, category_code=cat, sub_category_code=sub,
        )
        classify(wo["id"])
        dispatch(wo["id"])
        lead_assign = find_lead_assignment(wo["id"])
        accept_assignment(wo["id"], lead_assign["id"], handler_b)
        resolve(wo["id"], handler=handler_b)
        surveys = list_surveys(wo["id"])
        if surveys:
            get_success_data(api_client.respond_survey(
                surveys[-1]["id"], respond_survey_payload(score=score), SA,
            ))
        work_orders_b.append(get_work_order(wo["id"]))
    return {
        "jurisdiction_code": jc,
        "category_code": cat, "sub_category_code": sub,
        "lead_department": lead_dept,
        "handler_a": handler_a, "handler_b": handler_b,
        "work_orders_a": work_orders_a,
        "work_orders_b": work_orders_b,
    }


# ===========================================================================
# Targeted pause/resume invariant fixtures
# ===========================================================================
def setup_paused_with_seconds(*, pause_seconds: int = 1800) -> Dict[str, Any]:
    """Reach IN_PROGRESS, pause, advance clock, resume — pauses
    pause_seconds wall-clock seconds. Returns world dict.

    PRD §3.6.
    """
    world = setup_in_progress()
    wo_id = world["work_order"]["id"]
    pause(wo_id, handler=world["lead_handler"])
    advance_clock(pause_seconds)
    resume(wo_id, handler=world["lead_handler"])
    world["work_order"] = get_work_order(wo_id)
    return world


__all__ = [
    "PA", "PA_ALT", "HO", "HO_ALT", "DISP", "DISP_ALT", "SUP", "SA",
    "advance_clock", "align_clock_to_business_day_start", "run_sweep",
    "create_department", "create_handler", "create_category_rule",
    "setup_routing_world",
    "register_work_order", "classify", "dispatch",
    "list_assignments", "find_lead_assignment", "find_supporting_assignments",
    "accept_assignment", "submit_opinion",
    "resolve", "pause", "resume",
    "get_work_order", "get_department", "get_handler",
    "setup_in_progress", "setup_supporting_accepted",
    "setup_all_opinions_submitted",
    "setup_resolved", "setup_followed_up",
    "list_surveys", "list_audit_logs", "list_sync_events",
    "list_supervision_tasks",
    "setup_for_difficulty_dual_variant",
    "setup_three_resolved_with_surveys",
    "setup_paused_with_seconds",
]
