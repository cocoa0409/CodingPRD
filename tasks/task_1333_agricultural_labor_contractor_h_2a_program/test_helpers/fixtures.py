"""Composite setup helpers for the H-2A labor contractor API tests.

Every test runs against a freshly restarted server with an empty database and
the logical clock at its default reading of 2026-08-01T00:00:00Z (PRD 2.4), so
each helper builds its preconditions from scratch through the public API and
sets the clock explicitly whenever a scenario needs a non-default date.

The canonical pipeline mirrors the program's lifecycle (PRD 3.1-3.6):
grower -> wage determination -> job order -> submit -> certify -> recruitment
open/close -> petition -> link workers -> file -> approve -> consular
appointments -> activate -> record ISSUED outcomes -> assignments -> start.
"""
from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    adjudicate_payload,
    create_audit_case_payload,
    create_consular_appointment_payload,
    create_domestic_application_payload,
    create_grower_payload,
    create_housing_assignment_payload,
    create_housing_inspection_payload,
    create_housing_unit_payload,
    create_hourly_only_determination_payload,
    create_job_order_payload,
    create_transfer_request_payload,
    create_visa_petition_payload,
    create_wage_determination_payload,
    create_work_log_payload,
    create_worker_assignment_payload,
    create_worker_payload,
    decide_application_payload,
    end_assignment_payload,
    issue_findings_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_grower_rep_headers

ADMIN = TEST_USERS["contractor_admin_headers"]
REVIEWER = TEST_USERS["program_reviewer_headers"]
INSPECTOR = TEST_USERS["housing_inspector_headers"]
VISA_OFFICER = TEST_USERS["visa_officer_headers"]
AUDITOR = TEST_USERS["wage_auditor_headers"]
SYSADMIN = TEST_USERS["system_admin_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str) -> None:
    """Advance the server logical clock (SystemAdmin only, PRD 2.4)."""
    get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), SYSADMIN))


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation helpers
# ---------------------------------------------------------------------------
def create_grower(fein: str = "12-3456789", legal_name: str = "Green Acres LLC", state_code: str = "CA") -> Dict[str, Any]:
    resp = api_client.create_grower(
        create_grower_payload(fein=fein, legal_name=legal_name, state_code=state_code), ADMIN
    )
    return get_success_data(resp)


def create_wage_determination(hourly_only: bool = False, **overrides) -> Dict[str, Any]:
    payload = (
        create_hourly_only_determination_payload(**overrides)
        if hourly_only
        else create_wage_determination_payload(**overrides)
    )
    return get_success_data(api_client.create_wage_determination(payload, REVIEWER))


def create_job_order(grower_id: str, wage_determination_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_job_order(create_job_order_payload(grower_id, wage_determination_id, **overrides), ADMIN)
    )


def create_worker(passport_number: str = "P0001", **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_worker(create_worker_payload(passport_number=passport_number, **overrides), ADMIN)
    )


def create_petition(job_order_id: str, receipt_code: str = "RCPT-1", requested_worker_count: int = 1) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_visa_petition(
            job_order_id,
            create_visa_petition_payload(receipt_code=receipt_code, requested_worker_count=requested_worker_count),
            ADMIN,
        )
    )


def link_worker(petition_id: str, worker_id: str) -> None:
    get_success_data(api_client.link_worker(petition_id, {"worker_id": worker_id}, ADMIN))


def file_petition(petition_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.file_visa_petition(petition_id, ADMIN))


def adjudicate_petition(petition_id: str, decision: str, approved_worker_count: Optional[int] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.adjudicate_petition(petition_id, adjudicate_payload(decision, approved_worker_count), REVIEWER)
    )


def schedule_appointment(worker_id: str, petition_id: str, appointment_date: str, consulate_code: str = "MEX-MTY") -> Dict[str, Any]:
    return get_success_data(
        api_client.create_consular_appointment(
            create_consular_appointment_payload(
                worker_id=worker_id, petition_id=petition_id,
                consulate_code=consulate_code, appointment_date=appointment_date,
            ),
            ADMIN,
        )
    )


def complete_appointment(appointment_id: str, outcome: str = "ISSUED") -> Dict[str, Any]:
    return get_success_data(
        api_client.complete_consular_appointment(appointment_id, {"outcome": outcome}, VISA_OFFICER)
    )


def create_assignment(worker_id: str, job_order_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_worker_assignment(create_worker_assignment_payload(worker_id, job_order_id), ADMIN)
    )


def start_assignment(assignment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.start_worker_assignment(assignment_id, ADMIN))


def end_assignment(assignment_id: str, end_reason: str) -> Dict[str, Any]:
    return get_success_data(api_client.end_worker_assignment(assignment_id, end_assignment_payload(end_reason), ADMIN))


def create_work_log(assignment_id: str, work_date: str, hours_worked: float, units_picked: int) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_work_log(create_work_log_payload(assignment_id, work_date, hours_worked, units_picked), ADMIN)
    )


def create_work_logs(assignment_id: str, dates: Sequence[str], hours_worked: float, units_picked: int) -> List[Dict[str, Any]]:
    """Record one work log per date with identical hours/units."""
    return [create_work_log(assignment_id, d, hours_worked, units_picked) for d in dates]


def get_reconciliation(assignment_id: str) -> Dict[str, Any]:
    """Fetch the single reconciliation row of an assignment (array of 0 or 1, PRD 3.7)."""
    rows = get_success_data(api_client.get_reconciliation(assignment_id, ADMIN))
    assert isinstance(rows, list) and len(rows) == 1, f"expected exactly one reconciliation row, got {rows!r}"
    return rows[0]


def create_application(job_order_id: str, applicant_name: str = "Dom Worker", contact_phone: str = "555-0100") -> Dict[str, Any]:
    return get_success_data(
        api_client.create_domestic_application(
            job_order_id,
            create_domestic_application_payload(applicant_name=applicant_name, contact_phone=contact_phone),
            ADMIN,
        )
    )


def decide_application(application_id: str, decision: str, qualification: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.decide_domestic_application(application_id, decide_application_payload(decision, qualification), ADMIN)
    )


def create_housing_unit(grower_id: str, name: str = "Camp A", capacity: int = 2) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_housing_unit(create_housing_unit_payload(grower_id, name=name, capacity=capacity), ADMIN)
    )


def record_inspection(unit_id: str, inspected_on: str, result: str, deficiency_codes: Optional[List[str]] = None) -> Dict[str, Any]:
    payload = create_housing_inspection_payload(inspected_on, result)
    if deficiency_codes is not None:
        payload["deficiency_codes"] = deficiency_codes
    return get_success_data(api_client.record_housing_inspection(unit_id, payload, INSPECTOR))


def create_certified_unit(grower_id: str, name: str = "Camp A", capacity: int = 2, inspected_on: str = "2026-08-05") -> Dict[str, Any]:
    """Create a unit and record a PASS inspection (requires clock >= inspected_on)."""
    unit = create_housing_unit(grower_id, name=name, capacity=capacity)
    record_inspection(unit["id"], inspected_on, "PASS")
    return get_success_data(api_client.get_housing_unit(unit["id"], ADMIN))


def move_worker_into_housing(unit_id: str, worker_id: str, assignment_id: str, move_in_date: str = "2026-09-01") -> Dict[str, Any]:
    return get_success_data(
        api_client.create_housing_assignment(
            create_housing_assignment_payload(
                housing_unit_id=unit_id, worker_id=worker_id,
                worker_assignment_id=assignment_id, move_in_date=move_in_date,
            ),
            ADMIN,
        )
    )


def create_audit_case(grower_id: str, trigger_source: str = "MANUAL", **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_audit_case(create_audit_case_payload(grower_id, trigger_source, **overrides), AUDITOR)
    )


def issue_findings(case_id: str, findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    return get_success_data(api_client.issue_findings(case_id, issue_findings_payload(findings), AUDITOR))


def setup_case_with_findings(findings: List[Dict[str, Any]], trigger_source: str = "MANUAL", fein: str = "12-3456789") -> Dict[str, Any]:
    """Grower + audit case moved to FINDINGS_ISSUED."""
    grower = create_grower(fein=fein)
    case = create_audit_case(grower["id"], trigger_source)
    case = issue_findings(case["id"], findings)
    return {"grower": grower, "case": case}


# ---------------------------------------------------------------------------
# Tier 2: job-order state progression
# ---------------------------------------------------------------------------
def submit_order(job_order_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.submit_job_order(job_order_id, ADMIN))


def certify_order(job_order_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.certify_job_order(job_order_id, REVIEWER))


def create_recruiting_order(grower_id: str, wage_determination_id: str, **order_overrides) -> Dict[str, Any]:
    """Order walked DRAFT -> SUBMITTED -> CERTIFIED -> RECRUITING.

    Relies on the default clock 2026-08-01 satisfying the thirty-day
    certification lead time for a 2026-09-01 start (PRD 3.2).
    """
    jo = create_job_order(grower_id, wage_determination_id, **order_overrides)
    submit_order(jo["id"])
    certify_order(jo["id"])
    get_success_data(api_client.begin_recruitment(jo["id"], ADMIN))
    return get_success_data(api_client.get_job_order(jo["id"], ADMIN))


def create_petitioning_order(grower_id: str, wage_determination_id: str, **order_overrides) -> Dict[str, Any]:
    """Order walked through RECRUITING and into PETITIONING (no undecided applications)."""
    jo = create_recruiting_order(grower_id, wage_determination_id, **order_overrides)
    get_success_data(api_client.close_recruitment(jo["id"], ADMIN))
    return get_success_data(api_client.get_job_order(jo["id"], ADMIN))


def approve_petition_with_workers(petition_id: str, worker_ids: Sequence[str]) -> Dict[str, Any]:
    """Link every worker, file the petition, and approve it for the linked count."""
    for worker_id in worker_ids:
        link_worker(petition_id, worker_id)
    file_petition(petition_id)
    return adjudicate_petition(petition_id, "APPROVE", approved_worker_count=len(worker_ids))


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle pipeline
# ---------------------------------------------------------------------------
def setup_active_order_pipeline(
    *,
    passports: Sequence[str] = ("P0001",),
    receipt_code: str = "RCPT-1",
    requested_worker_count: Optional[int] = None,
    hourly_only: bool = False,
    order_overrides: Optional[Dict[str, Any]] = None,
    wd_overrides: Optional[Dict[str, Any]] = None,
    fein: str = "12-3456789",
    grower_name: str = "Green Acres LLC",
    appointment_date: str = "2026-09-01",
    pre_appointment_clock: str = "2026-08-31T00:00:00Z",
    activation_clock: str = "2026-09-01T00:00:00Z",
    visa_passports: Optional[Sequence[str]] = None,
    activate: bool = True,
    issue_visas: bool = True,
    start_assignments: bool = True,
) -> Dict[str, Any]:
    """Full pipeline: grower -> determination -> order to PETITIONING -> petition
    -> link/file/approve -> appointments -> activate -> ISSUED visas -> started
    assignments. Returns every created entity keyed by role/passport.
    """
    grower = create_grower(fein=fein, legal_name=grower_name)
    wd = create_wage_determination(hourly_only=hourly_only, **(wd_overrides or {}))
    jo = create_petitioning_order(grower["id"], wd["id"], **(order_overrides or {}))

    requested = requested_worker_count if requested_worker_count is not None else len(passports)
    petition = create_petition(jo["id"], receipt_code=receipt_code, requested_worker_count=requested)

    workers = {p: create_worker(passport_number=p) for p in passports}
    approve_petition_with_workers(petition["id"], [workers[p]["id"] for p in passports])

    visa_set = set(visa_passports) if visa_passports is not None else set(passports)
    appointments: Dict[str, Any] = {}
    assignments: Dict[str, Any] = {}

    if issue_visas:
        set_clock(pre_appointment_clock)
        for p in passports:
            if p in visa_set:
                appointments[p] = schedule_appointment(workers[p]["id"], petition["id"], appointment_date)

    if activate:
        set_clock(activation_clock)
        get_success_data(api_client.activate_job_order(jo["id"], ADMIN))

    if issue_visas:
        for p, appt in appointments.items():
            complete_appointment(appt["id"], "ISSUED")
            workers[p] = get_success_data(api_client.get_worker(workers[p]["id"], ADMIN))

    if start_assignments:
        for p in passports:
            if p in visa_set:
                asg = create_assignment(workers[p]["id"], jo["id"])
                assignments[p] = start_assignment(asg["id"])

    # Return fresh worker snapshots: linking/visas/assignment-starts all mutate
    # worker status server-side after the initial create_worker response.
    workers = {
        p: get_success_data(api_client.get_worker(workers[p]["id"], ADMIN))
        for p in passports
    }

    return {
        "grower": grower,
        "wd": wd,
        "order": get_success_data(api_client.get_job_order(jo["id"], ADMIN)),
        "petition": get_success_data(api_client.get_visa_petition(petition["id"], ADMIN)),
        "workers": workers,
        "appointments": appointments,
        "assignments": assignments,
    }


# ---------------------------------------------------------------------------
# Tier 4: two-grower scenarios (transfers, cross-grower rules)
# ---------------------------------------------------------------------------
def setup_two_grower_scenario(
    *,
    start_j1_assignment: bool = True,
    start_j2_assignment: bool = False,
    include_j1b: bool = False,
    j1_logs: Sequence[Tuple[str, float, int]] = (),
    j1_passport: str = "P0001",
    j2_passport: str = "P0009",
    j1b_passport: str = "P0008",
    advance_clock: str = "2026-09-15T00:00:00Z",
) -> Dict[str, Any]:
    """G1's J1 (2026-09-01..2026-10-20) and G2's J2 (2026-09-15..2026-11-03),
    both ACTIVE with approved petitions. W_A is petitioned to J1 and receives a
    visa on 2026-09-01; W_H is linked to J2's petition (visa only when
    start_j2_assignment). Optionally a second G1 order J1B (same-grower target).
    """
    g1 = create_grower(fein="12-3456789", legal_name="Green Acres LLC")
    g2 = create_grower(fein="98-7654321", legal_name="Sunny Field Farms")
    wd = create_wage_determination()

    jo1 = create_petitioning_order(g1["id"], wd["id"], title="J1 fall lettuce")
    jo2 = create_petitioning_order(
        g2["id"], wd["id"],
        title="J2 late lettuce", work_start_date="2026-09-15", work_end_date="2026-11-03",
        workers_requested=2,
    )
    jo1b = None
    if include_j1b:
        jo1b = create_petitioning_order(g1["id"], wd["id"], title="J1B", workers_requested=2)

    pet1 = create_petition(jo1["id"], receipt_code="RCPT-1", requested_worker_count=1)
    pet2 = create_petition(jo2["id"], receipt_code="RCPT-2", requested_worker_count=1)
    pet1b = create_petition(jo1b["id"], receipt_code="RCPT-1B", requested_worker_count=1) if jo1b else None

    wa = create_worker(passport_number=j1_passport, full_name="Worker A")
    wh = create_worker(passport_number=j2_passport, full_name="Worker H")
    wh1 = create_worker(passport_number=j1b_passport, full_name="Worker H1") if jo1b else None

    approve_petition_with_workers(pet1["id"], [wa["id"]])
    approve_petition_with_workers(pet2["id"], [wh["id"]])
    if pet1b and wh1:
        approve_petition_with_workers(pet1b["id"], [wh1["id"]])

    set_clock("2026-08-31T00:00:00Z")
    appt_a = schedule_appointment(wa["id"], pet1["id"], "2026-09-01")
    appt_c = schedule_appointment(wh["id"], pet2["id"], "2026-09-15") if start_j2_assignment else None

    set_clock("2026-09-01T00:00:00Z")
    get_success_data(api_client.activate_job_order(jo1["id"], ADMIN))
    if jo1b:
        get_success_data(api_client.activate_job_order(jo1b["id"], ADMIN))
    complete_appointment(appt_a["id"], "ISSUED")
    wa = get_success_data(api_client.get_worker(wa["id"], ADMIN))

    asg_a = None
    if start_j1_assignment:
        asg_a = start_assignment(create_assignment(wa["id"], jo1["id"])["id"])

    set_clock(advance_clock)
    for work_date, hours, units in j1_logs:
        assert asg_a is not None, "j1_logs require start_j1_assignment=True"
        create_work_log(asg_a["id"], work_date, hours, units)

    get_success_data(api_client.activate_job_order(jo2["id"], ADMIN))
    asg_c = None
    if start_j2_assignment:
        complete_appointment(appt_c["id"], "ISSUED")
        wh = get_success_data(api_client.get_worker(wh["id"], ADMIN))
        asg_c = start_assignment(create_assignment(wh["id"], jo2["id"])["id"])

    return {
        "g1": g1, "g2": g2, "wd": wd,
        "jo1": jo1, "jo2": jo2, "jo1b": jo1b,
        "pet1": pet1, "pet2": pet2, "pet1b": pet1b,
        "wa": wa, "wh": wh, "wh1": wh1,
        "asg_a": asg_a, "asg_c": asg_c,
    }


def setup_transfer_grower_approved(
    *,
    j1_logs: Sequence[Tuple[str, float, int]] = (),
    reason: str = "CONTRACT_IMPOSSIBILITY",
) -> Dict[str, Any]:
    """Two-grower scenario plus a transfer request for W_A -> J2 already in
    GROWER_APPROVED (target grower consent given)."""
    scenario = setup_two_grower_scenario(j1_logs=j1_logs)
    tr = get_success_data(
        api_client.create_transfer_request(
            create_transfer_request_payload(
                scenario["wa"]["id"], scenario["asg_a"]["id"], scenario["jo2"]["id"], reason
            ),
            ADMIN,
        )
    )
    get_success_data(api_client.grower_approve_transfer(tr["id"], make_grower_rep_headers(scenario["g2"]["id"])))
    scenario["transfer"] = get_success_data(api_client.get_transfer_request(tr["id"], ADMIN))
    return scenario


# ---------------------------------------------------------------------------
# Tier 5: consular quota scenario (approved petition, no activation needed)
# ---------------------------------------------------------------------------
def setup_approved_petition_with_linked_workers(
    num_workers: int,
    *,
    order_overrides: Optional[Dict[str, Any]] = None,
    receipt_code: str = "RCPT-3",
    clock_after_approval: str = "2026-09-01T00:00:00Z",
) -> Dict[str, Any]:
    """J3-style order in PETITIONING with one APPROVED petition and N linked
    (PETITIONED) workers; clock parked at clock_after_approval afterwards."""
    grower = create_grower()
    wd = create_wage_determination()
    jo = create_petitioning_order(
        grower["id"], wd["id"],
        **(order_overrides or {"title": "J3 short harvest", "work_end_date": "2026-09-20", "workers_requested": 8}),
    )
    petition = create_petition(jo["id"], receipt_code=receipt_code, requested_worker_count=num_workers)
    passports = [f"P{1000 + i}" for i in range(1, num_workers + 1)]
    workers = [create_worker(passport_number=p, full_name=f"W{i}") for i, p in enumerate(passports, start=1)]
    approve_petition_with_workers(petition["id"], [w["id"] for w in workers])
    set_clock(clock_after_approval)
    return {
        "grower": grower,
        "wd": wd,
        "order": jo,
        "petition": get_success_data(api_client.get_visa_petition(petition["id"], ADMIN)),
        "workers": workers,
    }
