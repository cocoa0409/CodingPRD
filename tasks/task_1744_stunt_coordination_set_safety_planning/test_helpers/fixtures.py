"""Composite setup helpers for the stunt-safety test suite.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before each test, so each test
starts against an empty database and the logical clock reads the startup
default 2026-08-01T00:00:00Z).

Setup calls use the lenient get_success_data() validator so that a setup
failure surfaces as a clear "Setup failed" error rather than a confusing
assertion failure inside the checks under test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    close_review_payload,
    create_certification_payload,
    create_equipment_payload,
    create_execution_payload,
    create_incident_payload,
    create_inspection_payload,
    create_pay_adjustment_payload,
    create_performer_payload,
    create_production_payload,
    create_rehearsal_payload,
    create_review_payload,
    create_risk_assessment_payload,
    create_safety_meeting_payload,
    create_sequence_payload,
    file_insurance_payload,
)
from .test_users import (
    TEST_USERS,
    make_performer_headers,
)

EXEC = TEST_USERS["executive_headers"]
COORD = TEST_USERS["coordinator_headers"]
SAFETY = TEST_USERS["safety_headers"]
DEPT_HEAD = TEST_USERS["department_head_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


def _setup_failed(step: str, resp) -> AssertionError:
    body = None
    try:
        body = resp.text
    except Exception:
        pass
    return AssertionError(f"Setup failed at step '{step}': HTTP {resp.status_code} body={body}")


def _ok(resp, step: str):
    try:
        return get_success_data(resp)
    except Exception as exc:
        raise _setup_failed(step, resp) from exc


# ---------------------------------------------------------------------------
# Tier 1: productions and the logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    return _ok(api_client.set_clock({"to_iso8601": to_iso8601}, EXEC), "set_clock")


def create_production(name: str = "Test Production", budget: int = 10000000) -> dict:
    return _ok(
        api_client.create_production(create_production_payload(name=name, total_budget_cents=budget), EXEC),
        "create_production",
    )


def get_production(production_id: str) -> dict:
    return _ok(api_client.get_production(production_id, EXEC), "get_production")


def file_insurance(production_id: str, exposure_cents: int = 50000000) -> dict:
    return _ok(
        api_client.file_insurance(production_id, file_insurance_payload(declared_exposure_cents=exposure_cents), EXEC),
        "file_insurance",
    )


def acknowledge_insurance(production_id: str) -> dict:
    return _ok(api_client.acknowledge_insurance(production_id, EXEC), "acknowledge_insurance")


def activate_production(production_id: str) -> dict:
    return _ok(api_client.activate_production(production_id, EXEC), "activate_production")


def create_active_production(name: str = "Active Production", budget: int = 10000000,
                             exposure_cents: int = 50000000) -> dict:
    """Production with insurance FILED and posture ACTIVE."""
    prod = create_production(name, budget)
    file_insurance(prod["id"], exposure_cents)
    activate_production(prod["id"])
    return get_production(prod["id"])


def create_acknowledged_active_production(name: str = "Acknowledged Production",
                                          budget: int = 10000000,
                                          exposure_cents: int = 50000000) -> dict:
    """Production with insurance ACKNOWLEDGED and posture ACTIVE (covers the
    HIGH/CRITICAL readiness insurance gate)."""
    prod = create_production(name, budget)
    file_insurance(prod["id"], exposure_cents)
    acknowledge_insurance(prod["id"])
    activate_production(prod["id"])
    return get_production(prod["id"])


# ---------------------------------------------------------------------------
# Tier 2: sequences and the risk-assessment cycle
# ---------------------------------------------------------------------------

def create_sequence(production_id: str, name: str = "Test Sequence", hazard_class: str = "FIGHT",
                    risk_category: str = "LOW", equipment_ids=None, coord_headers=None,
                    scheduled_execution_start: str = "2026-08-05T00:00:00Z",
                    scheduled_execution_end: str = "2026-08-06T00:00:00Z") -> dict:
    payload = create_sequence_payload(
        production_id,
        name=name,
        hazard_class=hazard_class,
        risk_category=risk_category,
        required_equipment_ids=equipment_ids or [],
        scheduled_execution_start=scheduled_execution_start,
        scheduled_execution_end=scheduled_execution_end,
    )
    return _ok(api_client.create_sequence(payload, coord_headers or COORD), "create_sequence")


def get_sequence(sequence_id: str) -> dict:
    return _ok(api_client.get_sequence(sequence_id, COORD), "get_sequence")


def create_draft_assessment(production_id: str, sequence_id: str, severity: int = 2,
                            likelihood: int = 2, mitigation_notes=None, coord_headers=None) -> dict:
    """Create a DRAFT assessment with a fresh OCC read of the sequence version."""
    headers = coord_headers or COORD
    seq = _ok(api_client.get_sequence(sequence_id, headers), "get_sequence(for occ)")
    payload = create_risk_assessment_payload(
        production_id, sequence_id, seq["version"],
        severity_rating=severity, likelihood_rating=likelihood,
    )
    if mitigation_notes is not None:
        payload["mitigation_notes"] = mitigation_notes
    return _ok(api_client.create_risk_assessment(payload, headers), "create_risk_assessment")


def create_approved_assessment(production_id: str, sequence_id: str, severity: int = 2,
                               likelihood: int = 2, mitigation_notes=None, coord_headers=None) -> dict:
    """Create -> submit -> approve. Approver is a different user than the author
    (segregation of duties, PRD §2.10)."""
    headers = coord_headers or COORD
    ra = create_draft_assessment(production_id, sequence_id, severity, likelihood, mitigation_notes, headers)
    _ok(api_client.submit_assessment(ra["id"], headers), "submit_assessment")
    return _ok(api_client.approve_assessment(ra["id"], SAFETY), "approve_assessment")


def lock_design(sequence_id: str, coord_headers=None) -> dict:
    return _ok(api_client.lock_design(sequence_id, coord_headers or COORD), "lock_design")


def create_locked_sequence(production_id: str, name: str = "Locked Sequence",
                           hazard_class: str = "FIGHT", risk_category: str = "LOW",
                           severity: int = 2, likelihood: int = 2, mitigation_notes=None,
                           equipment_ids=None, coord_headers=None) -> dict:
    """DRAFT sequence + APPROVED assessment + lock-design -> DESIGN_LOCKED."""
    headers = coord_headers or COORD
    seq = create_sequence(production_id, name, hazard_class, risk_category, equipment_ids, headers)
    create_approved_assessment(production_id, seq["id"], severity, likelihood, mitigation_notes, headers)
    return lock_design(seq["id"], headers)


# ---------------------------------------------------------------------------
# Tier 2: performers, certifications, equipment
# ---------------------------------------------------------------------------

def create_performer(production_id: str, first_name: str = "Stunt", last_name: str = "Performer",
                     day_rate: int = 150000, union_status: str = "NON_UNION") -> dict:
    return _ok(
        api_client.create_performer(
            create_performer_payload(
                production_id, first_name=first_name, last_name=last_name,
                base_day_rate_cents=day_rate, union_status=union_status,
            ),
            COORD,
        ),
        "create_performer",
    )


def create_certification(performer_id: str, discipline: str = "FIGHT", level: str = "ADVANCED",
                         expires_at: str = "2027-01-01T00:00:00Z") -> dict:
    return _ok(
        api_client.create_certification(
            create_certification_payload(performer_id, discipline=discipline, level=level, expires_at=expires_at),
            COORD,
        ),
        "create_certification",
    )


def create_qualified_performer(production_id: str, discipline: str = "FIGHT", **performer_kwargs) -> tuple:
    """Performer + one valid certification (first valid cert -> QUALIFIED).
    Returns (performer, certification)."""
    perf = create_performer(production_id, **performer_kwargs)
    cert = create_certification(perf["id"], discipline=discipline)
    return perf, cert


def create_equipment(production_id: str, name: str = "Rig", equipment_type: str = "RIGGING",
                     serial_number: str = "SN-001", inspection_interval_hours: int = 72) -> dict:
    return _ok(
        api_client.create_equipment(
            create_equipment_payload(
                production_id, name=name, equipment_type=equipment_type,
                serial_number=serial_number, inspection_interval_hours=inspection_interval_hours,
            ),
            COORD,
        ),
        "create_equipment",
    )


def record_inspection(equipment_id: str, outcome: str = "PASSED", notes: str = "inspection") -> dict:
    """Recorded by an inspector who is not the item's registrar (SoD, PRD §2.10)."""
    return _ok(
        api_client.create_inspection(create_inspection_payload(equipment_id, outcome=outcome, notes=notes), INSPECTOR),
        "create_inspection",
    )


def create_inspected_equipment(production_id: str, name: str = "Rig", equipment_type: str = "RIGGING",
                               serial_number: str = "SN-001", inspection_interval_hours: int = 72) -> dict:
    """Equipment item with a passing inspection on file (inspection_current true
    at the default clock)."""
    eq = create_equipment(production_id, name, equipment_type, serial_number, inspection_interval_hours)
    record_inspection(eq["id"], "PASSED", "baseline")
    return eq


# ---------------------------------------------------------------------------
# Tier 3: rehearsals
# ---------------------------------------------------------------------------

def schedule_rehearsal(production_id: str, sequence_id: str, performer_id: str,
                       facility: str = "Stage 1", start: str = "2026-08-02T10:00:00Z",
                       end: str = "2026-08-02T11:00:00Z") -> dict:
    return _ok(
        api_client.create_rehearsal(
            create_rehearsal_payload(
                production_id, sequence_id, performer_id, facility=facility,
                scheduled_start=start, scheduled_end=end,
            ),
            COORD,
        ),
        "create_rehearsal",
    )


def complete_rehearsals(production_id: str, sequence_id: str, performer_id: str, count: int,
                        day: str = "2026-08-02", start_hour: int = 9) -> list:
    """Schedule `count` adjacent one-hour rehearsals for the same performer and
    complete them all. Adjacent windows are conflict-free under the half-open
    overlap rule (PRD §3.3). Advances the logical clock past every start so the
    completion time gate passes."""
    scheduled = []
    for i in range(count):
        start = f"{day}T{start_hour + i:02d}:00:00Z"
        end = f"{day}T{start_hour + i + 1:02d}:00:00Z"
        scheduled.append(schedule_rehearsal(production_id, sequence_id, performer_id,
                                            facility="Stage 1", start=start, end=end))
    set_clock(f"{day}T{start_hour + count - 1:02d}:30:00Z")
    completed = []
    for reh in scheduled:
        completed.append(_ok(api_client.complete_rehearsal(reh["id"], COORD), "complete_rehearsal"))
    return completed


# ---------------------------------------------------------------------------
# Tier 3: safety meetings and signoffs
# ---------------------------------------------------------------------------

def hold_safety_meeting(production_id: str, sequence_id: str, facility: str = "Stage 2",
                        start: str = "2026-08-03T10:00:00Z", end: str = "2026-08-03T11:00:00Z",
                        refuse_departments: tuple = (), refuse_user_id: str = "dh-med") -> tuple:
    """Create -> start -> decide every fanned-out signoff -> complete.

    Signoffs are signed with no conditions unless their department is listed in
    refuse_departments (those are refused). Returns (completed_meeting, decisions)
    where decisions maps department -> resulting status."""
    mtg = _ok(
        api_client.create_safety_meeting(
            create_safety_meeting_payload(production_id, sequence_id, facility=facility,
                                          scheduled_start=start, scheduled_end=end),
            COORD,
        ),
        "create_safety_meeting",
    )
    _ok(api_client.start_meeting(mtg["id"], SAFETY), "start_meeting")
    signoffs = _ok(api_client.list_signoffs(SAFETY, params={"meeting_id": mtg["id"]}), "list_signoffs")
    decisions = {}
    for sg in signoffs:
        if sg["department"] in refuse_departments:
            headers = {"X-User-ID": refuse_user_id, "X-User-Role": "DepartmentHead"}
            _ok(api_client.refuse_signoff(sg["id"], {"reason": "department refuses"}, headers), "refuse_signoff")
            decisions[sg["department"]] = "REFUSED"
        else:
            _ok(api_client.sign_signoff(sg["id"], DEPT_HEAD), "sign_signoff")
            decisions[sg["department"]] = "SIGNED"
    completed = _ok(api_client.complete_meeting(mtg["id"], SAFETY), "complete_meeting")
    return completed, decisions


def mark_ready(sequence_id: str) -> dict:
    return _ok(api_client.mark_ready(sequence_id, COORD), "mark_ready")


# ---------------------------------------------------------------------------
# Tier 4: full readiness chain
# ---------------------------------------------------------------------------

def setup_locked_with_rehearsals(name: str = "Prod", hazard_class: str = "FIGHT",
                                 risk_category: str = "LOW", severity: int = 2, likelihood: int = 2,
                                 mitigation_notes=None, budget: int = 10000000,
                                 acknowledge: bool = True, equipment_specs=None,
                                 rehearsals_completed: int = None, day_rate: int = 150000,
                                 union_status: str = "NON_UNION", discipline: str = None) -> dict:
    """ACTIVE (insurance ACKNOWLEDGED unless acknowledge=False) production +
    DESIGN_LOCKED sequence + QUALIFIED performer + `rehearsals_completed`
    COMPLETED rehearsals (defaults to the sequence's required_rehearsal_count).

    equipment_specs: optional list of dicts {name, equipment_type, serial_number,
    inspection_interval_hours}; each item is registered and inspected PASSED
    before the sequence is created, and wired into required_equipment_ids.
    """
    if acknowledge:
        prod = create_acknowledged_active_production(name=f"{name}", budget=budget)
    else:
        prod = create_active_production(name=f"{name}", budget=budget)
    equipment_ids = []
    equipment = []
    for spec in (equipment_specs or []):
        eq = create_inspected_equipment(prod["id"], **spec)
        equipment.append(eq)
        equipment_ids.append(eq["id"])
    seq = create_locked_sequence(prod["id"], name=f"{name} Seq", hazard_class=hazard_class,
                                 risk_category=risk_category, severity=severity, likelihood=likelihood,
                                 mitigation_notes=mitigation_notes, equipment_ids=equipment_ids)
    perf, cert = create_qualified_performer(prod["id"], discipline=discipline or hazard_class,
                                            day_rate=day_rate, union_status=union_status)
    count = seq["required_rehearsal_count"] if rehearsals_completed is None else rehearsals_completed
    rehearsals = []
    if count:
        rehearsals = complete_rehearsals(prod["id"], seq["id"], perf["id"], count)
    return {
        "production": prod,
        "sequence": get_sequence(seq["id"]),
        "performer": perf,
        "certification": cert,
        "equipment": equipment,
        "rehearsals": rehearsals,
    }


def setup_ready_sequence(name: str = "Ready", hazard_class: str = "FIGHT", risk_category: str = "LOW",
                         severity: int = 2, likelihood: int = 2, acknowledge: bool = True,
                         equipment_specs=None, mitigation_notes=None) -> dict:
    """Full readiness chain: locked sequence with quota met + a COMPLETED meeting
    whose signoffs are all SIGNED -> mark-ready -> READY sequence."""
    ctx = setup_locked_with_rehearsals(
        name=name, hazard_class=hazard_class, risk_category=risk_category,
        severity=severity, likelihood=likelihood, mitigation_notes=mitigation_notes,
        acknowledge=acknowledge, equipment_specs=equipment_specs,
    )
    meeting, decisions = hold_safety_meeting(ctx["production"]["id"], ctx["sequence"]["id"])
    seq = mark_ready(ctx["sequence"]["id"])
    ctx["meeting"] = meeting
    ctx["decisions"] = decisions
    ctx["sequence"] = seq
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: executions, reviews, and the reshoot loop
# ---------------------------------------------------------------------------

def attempt_take(production_id: str, sequence_id: str, take_number: int) -> dict:
    """Attempt a take with a fresh OCC read of the sequence version."""
    seq = get_sequence(sequence_id)
    return _ok(
        api_client.create_execution(
            create_execution_payload(production_id, sequence_id, take_number, seq["version"]),
            COORD,
        ),
        "create_execution",
    )


def complete_take(execution_id: str) -> dict:
    return _ok(api_client.complete_execution(execution_id, COORD), "complete_execution")


def setup_executed_sequence(name: str = "Executed", **kwargs) -> dict:
    """READY sequence + take 1 ATTEMPTED -> COMPLETED (sequence -> EXECUTED)."""
    ctx = setup_ready_sequence(name=name, **kwargs)
    take1 = attempt_take(ctx["production"]["id"], ctx["sequence"]["id"], 1)
    ctx["execution"] = complete_take(take1["id"])
    ctx["sequence"] = get_sequence(ctx["sequence"]["id"])
    return ctx


def reshoot_and_reready(production_id: str, sequence_id: str, facility: str = "Stage 3") -> dict:
    """RESHOOT_REQUIRED review close (EXECUTED -> DESIGN_LOCKED, design_revision
    +1), then a fresh meeting pinned to the new revision, then mark-ready.
    Returns the READY sequence."""
    review = _ok(api_client.create_review(create_review_payload(production_id, sequence_id), SAFETY),
                 "create_review")
    _ok(
        api_client.close_review(
            review["id"],
            close_review_payload(outcome="RESHOOT_REQUIRED", findings="camera missed the gag"),
            SAFETY,
        ),
        "close_review(reshoot)",
    )
    hold_safety_meeting(production_id, sequence_id, facility=facility,
                        start="2026-08-03T12:00:00Z", end="2026-08-03T13:00:00Z")
    return mark_ready(sequence_id)


# ---------------------------------------------------------------------------
# Tier 4: hazard-pay negotiation
# ---------------------------------------------------------------------------

def create_open_adjustment(production_id: str, sequence_id: str, performer_id: str,
                           base_amount_cents: int = 100000, requested_pct: float = 0.20,
                           adjustment_type: str = "HAZARD_BUMP", side: str = "PERFORMER") -> dict:
    """Open a negotiation. side='PERFORMER' calls with entity-backed performer
    headers (performer_id == X-User-ID); side='COORDINATOR' uses the coordinator."""
    payload = create_pay_adjustment_payload(
        production_id, sequence_id, performer_id,
        base_amount_cents=base_amount_cents, requested_pct=requested_pct,
        adjustment_type=adjustment_type,
    )
    headers = make_performer_headers(performer_id) if side == "PERFORMER" else COORD
    return _ok(api_client.create_pay_adjustment(payload, headers), "create_pay_adjustment")


def counter_adjustment(adjustment_id: str, counter_pct: float, performer_id: str,
                       side: str) -> dict:
    headers = make_performer_headers(performer_id) if side == "PERFORMER" else COORD
    return _ok(api_client.counter_pay_adjustment(adjustment_id, {"counter_pct": counter_pct}, headers),
               "counter_pay_adjustment")


def agree_adjustment(adjustment_id: str, performer_id: str, side: str = "COORDINATOR") -> dict:
    headers = make_performer_headers(performer_id) if side == "PERFORMER" else COORD
    return _ok(api_client.agree_pay_adjustment(adjustment_id, headers), "agree_pay_adjustment")


def get_adjustment(adjustment_id: str) -> dict:
    return _ok(api_client.get_pay_adjustment(adjustment_id, COORD), "get_pay_adjustment")


# ---------------------------------------------------------------------------
# Tier 5: incidents and stoppages
# ---------------------------------------------------------------------------

def report_incident(production_id: str, severity: str = "MINOR", sequence_id=None,
                    occurred_at: str = "2026-08-02T12:00:00Z", description: str = "On-set incident",
                    headers=None) -> dict:
    payload = create_incident_payload(production_id, severity=severity, occurred_at=occurred_at,
                                      description=description)
    if sequence_id is not None:
        payload["sequence_id"] = sequence_id
    return _ok(api_client.create_incident(payload, headers or SAFETY), "create_incident")


def stop_production(production_id: str, reason: str = "weather") -> dict:
    return _ok(api_client.stop_production(production_id, {"reason": reason}, SAFETY), "stop_production")
