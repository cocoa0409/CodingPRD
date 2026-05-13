"""Composite setup helpers for the Nursing Home test suite.

Most interesting test claims need the system in a state reached through
5–15 API calls. These helpers encapsulate those preambles so the test
bodies stay focused on the rule under test.

Setup helpers use ``get_success_data`` (lenient validator), so a broken
precondition produces a clear "setup failed" error rather than a
confusing assertion failure inside the test body.

Identity (PRD §2.1): every role in this system is opaque — none is
entity-backed. Distinct X-User-IDs in the same role are constructed
ad-hoc only when the PRD requires distinct identities for segregation
of duties (assessor vs approver, prescriber vs nurse, nurse vs witness).
"""
from __future__ import annotations
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .factories import (
    admit_payload, administration_payload, adjust_bill_payload,
    check_in_payload, clock_payload, create_assessment_payload,
    create_bed_payload, create_bill_payload, create_care_plan_payload,
    create_elder_payload, create_prescription_payload, create_room_payload,
    create_visit_reservation_payload, create_waitlist_payload,
    daily_task, deposit_payload, emergency_contact,
    epidemic_config_payload, external_event_payload,
    future_iso, future_iso_hours, iso_z, leave_payload,
    medication_error_payload, pay_bill_payload, refund_payload,
    supersede_payload, task_execution_payload, transfer_payload,
    unique_bed_code, unique_drug_code, unique_id_card,
    unique_idempotency_key, unique_payment_ref, unique_room_number,
    unique_suffix,
)
from .test_users import (
    TEST_USERS,
    make_admin_headers, make_finance_headers, make_nurse_headers,
    make_physician_headers, make_supervisor_headers,
)


# ===========================================================================
# Common headers
# ===========================================================================
ADMIN = TEST_USERS["admin_headers"]
ADMIN_ALT = TEST_USERS["admin_headers_alt"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
SUPERVISOR_ALT = TEST_USERS["supervisor_headers_alt"]
PHYSICIAN = TEST_USERS["physician_headers"]
PHYSICIAN_ALT = TEST_USERS["physician_headers_alt"]
NURSE = TEST_USERS["nurse_headers"]
NURSE_ALT = TEST_USERS["nurse_headers_alt"]
NURSE_THIRD = TEST_USERS["nurse_headers_third"]
CAREGIVER = TEST_USERS["caregiver_headers"]
FAMILY = TEST_USERS["family_headers"]
FINANCE = TEST_USERS["finance_headers"]
SYSTEMSYNC = TEST_USERS["systemsync_headers"]


# ===========================================================================
# Operational helpers (PRD §2.11)
# ===========================================================================
def advance_clock(seconds: int,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §2.11: 'A clock-advance capability accepts an integer number of
    seconds and advances the server's logical clock by exactly that amount.'"""
    return get_success_data(api_client.advance_clock(
        clock_payload(seconds), headers or ADMIN,
    ))


def run_sweep(headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §2.11: 'A sweep capability runs the periodic background actions
    in a single synchronous call.'"""
    return get_success_data(api_client.run_sweep(headers or ADMIN))


# ===========================================================================
# Rooms / beds (PRD §3.8)
# ===========================================================================
def create_room(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_room(
        create_room_payload(**overrides), ADMIN,
    ))


def create_bed(room_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_bed(
        room_id, create_bed_payload(**overrides), ADMIN,
    ))


def create_room_with_bed(room_overrides: Optional[Dict[str, Any]] = None,
                         bed_overrides: Optional[Dict[str, Any]] = None,
                         ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a STANDARD room + a SINGLE AVAILABLE bed."""
    room = create_room(**(room_overrides or {}))
    bed = create_bed(room["id"], **(bed_overrides or {}))
    return room, bed


def create_intensive_room_with_bed() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """PRD §3.8: INTENSIVE_CARE bed within an INTENSIVE_CARE room."""
    room = create_room(room_type="INTENSIVE_CARE")
    bed = create_bed(
        room["id"],
        bed_type="INTENSIVE_CARE",
        monthly_bed_fee_cents=120_000,
    )
    return room, bed


# ===========================================================================
# Elder helpers (PRD §3.1)
# ===========================================================================
def create_elder(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_elder(
        create_elder_payload(**overrides), ADMIN,
    ))


def get_elder(elder_id: str,
              headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_elder(
        elder_id, headers or ADMIN,
    ))


def update_elder(elder_id: str, payload: Dict[str, Any],
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.update_elder(
        elder_id, payload, headers or ADMIN,
    ))


def top_up_deposit(elder_id: str, amount_cents: int,
                   headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.deposit(
        elder_id, deposit_payload(amount_cents),
        headers or FINANCE,
    ))


# ===========================================================================
# Care assessment helpers (PRD §3.2)
# ===========================================================================
def draft_assessment(elder_id: str,
                     adl_score: int = 80,
                     cognitive_score: int = 10,
                     medical_condition_score: int = 20,
                     nurse_headers: Optional[Dict[str, str]] = None,
                     ) -> Dict[str, Any]:
    return get_success_data(api_client.create_care_assessment(
        elder_id,
        create_assessment_payload(
            adl_score=adl_score,
            cognitive_score=cognitive_score,
            medical_condition_score=medical_condition_score,
        ),
        nurse_headers or NURSE,
    ))


def submit_assessment(assessment_id: str,
                      nurse_headers: Optional[Dict[str, str]] = None,
                      ) -> Dict[str, Any]:
    return get_success_data(api_client.submit_care_assessment(
        assessment_id, nurse_headers or NURSE,
    ))


def approve_assessment(assessment_id: str,
                       supervisor_headers: Optional[Dict[str, str]] = None,
                       ) -> Dict[str, Any]:
    """PRD §3.2: supervisor's X-User-ID must differ from the draft's
    assessor_id. Default NURSE drafts → SUPERVISOR approves: distinct ids."""
    return get_success_data(api_client.approve_care_assessment(
        assessment_id, supervisor_headers or SUPERVISOR,
    ))


def create_approved_assessment(elder_id: str,
                               adl_score: int = 80,
                               cognitive_score: int = 10,
                               medical_condition_score: int = 20,
                               nurse_headers: Optional[Dict[str, str]] = None,
                               supervisor_headers: Optional[Dict[str, str]] = None,
                               ) -> Dict[str, Any]:
    """Full DRAFT → PENDING_APPROVAL → APPROVED cycle. Uses default
    NURSE (assessor) and SUPERVISOR (approver) — guaranteed distinct
    X-User-IDs to satisfy SoD (PRD §2.7 #6)."""
    a = draft_assessment(elder_id, adl_score, cognitive_score,
                         medical_condition_score, nurse_headers)
    submit_assessment(a["id"], nurse_headers)
    return approve_assessment(a["id"], supervisor_headers)


# ===========================================================================
# Care plan helpers (PRD §3.3)
# ===========================================================================
def create_draft_care_plan(elder_id: str,
                           based_on_assessment_id: str,
                           daily_tasks: Optional[List[Dict[str, Any]]] = None,
                           headers: Optional[Dict[str, str]] = None,
                           ) -> Dict[str, Any]:
    return get_success_data(api_client.create_care_plan(
        elder_id,
        create_care_plan_payload(based_on_assessment_id, daily_tasks),
        headers or SUPERVISOR,
    ))


def activate_care_plan(plan_id: str,
                       headers: Optional[Dict[str, str]] = None,
                       ) -> Dict[str, Any]:
    return get_success_data(api_client.activate_care_plan(
        plan_id, headers or SUPERVISOR,
    ))


def create_active_care_plan(elder_id: str,
                            assessment_id: str,
                            daily_tasks: Optional[List[Dict[str, Any]]] = None,
                            headers: Optional[Dict[str, str]] = None,
                            ) -> Dict[str, Any]:
    """Create DRAFT plan based on an APPROVED assessment and activate it."""
    p = create_draft_care_plan(elder_id, assessment_id, daily_tasks, headers)
    return activate_care_plan(p["id"], headers)


# ===========================================================================
# Admission / leave / discharge (PRD §3.1, §3.8)
# ===========================================================================
def admit_elder(elder_id: str, bed_id: str,
                headers: Optional[Dict[str, str]] = None,
                ) -> Dict[str, Any]:
    return get_success_data(api_client.admit_elder(
        elder_id, admit_payload(bed_id), headers or ADMIN,
    ))


def leave_elder(elder_id: str, reason: Optional[str] = None,
                headers: Optional[Dict[str, str]] = None,
                ) -> Dict[str, Any]:
    return get_success_data(api_client.leave_elder(
        elder_id, headers or ADMIN, leave_payload(reason),
    ))


def return_elder(elder_id: str,
                 headers: Optional[Dict[str, str]] = None,
                 ) -> Dict[str, Any]:
    return get_success_data(api_client.return_elder(
        elder_id, headers or ADMIN,
    ))


def transfer_elder(elder_id: str, target_bed_id: str,
                   headers: Optional[Dict[str, str]] = None,
                   ) -> Dict[str, Any]:
    return get_success_data(api_client.transfer_elder(
        elder_id, transfer_payload(target_bed_id), headers or ADMIN,
    ))


def discharge_elder(elder_id: str,
                    headers: Optional[Dict[str, str]] = None,
                    ) -> Dict[str, Any]:
    return get_success_data(api_client.discharge_elder(
        elder_id, headers or ADMIN,
    ))


# ===========================================================================
# Composite setup — Tier 2: Admitted elder with assessment
# ===========================================================================
def setup_admitted_elder_v2(
    adl_score: int = 80,
    cognitive_score: int = 10,
    medical_condition_score: int = 20,
    deposit_cents: int = 1_000_000,
    bed_type: str = "SINGLE",
    monthly_bed_fee_cents: int = 60_000,
    intensive_room: bool = False,
    elder_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create room, bed, elder, deposit, approved assessment, admit.

    Returns ``{elder, room, bed, assessment, bed_id}``.

    PRD §3.8 / §2.7 #13: an INTENSIVE elder may only occupy an
    INTENSIVE_CARE bed. When the (adl, cog, med) scores resolve to
    INTENSIVE classification, the bed must be INTENSIVE_CARE within an
    INTENSIVE_CARE room; we auto-promote the defaults so callers do not
    need to special-case the bed/room types for INTENSIVE scores.
    """
    from .constants import expected_composite_score, expected_classification

    classification = expected_classification(
        expected_composite_score(
            adl_score, cognitive_score, medical_condition_score,
        )
    )
    if classification == "INTENSIVE":
        # Auto-promote unless caller has already overridden.
        if bed_type == "SINGLE":
            bed_type = "INTENSIVE_CARE"
        if not intensive_room:
            intensive_room = True

    room = create_room(
        room_type="INTENSIVE_CARE" if intensive_room else "STANDARD",
    )
    bed = create_bed(
        room["id"],
        bed_type=bed_type,
        monthly_bed_fee_cents=monthly_bed_fee_cents,
    )
    elder = create_elder(**(elder_overrides or {}))
    top_up_deposit(elder["id"], deposit_cents)
    assessment = create_approved_assessment(
        elder["id"], adl_score, cognitive_score, medical_condition_score,
    )
    admit_elder(elder["id"], bed["id"])
    elder = get_elder(elder["id"])
    return {
        "elder": elder,
        "room": room,
        "bed": bed,
        "assessment": assessment,
    }


def setup_admitted_intensive_elder(deposit_cents: int = 1_000_000,
                                   monthly_bed_fee_cents: int = 120_000,
                                   ) -> Dict[str, Any]:
    """Admitted elder with care level INTENSIVE on an INTENSIVE_CARE bed.

    Composite 105 = (100-20)*0.5 + (30-5)*1 + 40*1 = 40+25+40 → INTENSIVE
    (PRD §3.2 inclusive threshold 80 → INTENSIVE).
    """
    return setup_admitted_elder_v2(
        adl_score=20,
        cognitive_score=5,
        medical_condition_score=40,
        deposit_cents=deposit_cents,
        bed_type="INTENSIVE_CARE",
        monthly_bed_fee_cents=monthly_bed_fee_cents,
        intensive_room=True,
    )


# ===========================================================================
# Care plan composite setup
# ===========================================================================
def setup_admitted_elder_with_active_plan(
    adl_score: int = 80,
    cognitive_score: int = 10,
    medical_condition_score: int = 20,
    daily_tasks: Optional[List[Dict[str, Any]]] = None,
    bed_type: str = "SINGLE",
    monthly_bed_fee_cents: int = 60_000,
    deposit_cents: int = 1_000_000,
    intensive_room: bool = False,
) -> Dict[str, Any]:
    """Admitted elder with an ACTIVE CarePlan based on the approved assessment.

    Returns ``{elder, room, bed, assessment, plan}``.
    """
    bundle = setup_admitted_elder_v2(
        adl_score=adl_score,
        cognitive_score=cognitive_score,
        medical_condition_score=medical_condition_score,
        deposit_cents=deposit_cents,
        bed_type=bed_type,
        monthly_bed_fee_cents=monthly_bed_fee_cents,
        intensive_room=intensive_room,
    )
    plan = create_active_care_plan(
        bundle["elder"]["id"],
        bundle["assessment"]["id"],
        daily_tasks,
    )
    bundle["plan"] = plan
    return bundle


# ===========================================================================
# Prescription helpers (PRD §3.4)
# ===========================================================================
def create_prescription(elder_id: str,
                        physician_headers: Optional[Dict[str, str]] = None,
                        **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_prescription(
        elder_id,
        create_prescription_payload(**overrides),
        physician_headers or PHYSICIAN,
    ))


def activate_prescription(prescription_id: str,
                          headers: Optional[Dict[str, str]] = None,
                          ) -> Dict[str, Any]:
    return get_success_data(api_client.activate_prescription(
        prescription_id, headers or SUPERVISOR,
    ))


def create_active_prescription(elder_id: str,
                               physician_headers: Optional[Dict[str, str]] = None,
                               **overrides: Any) -> Dict[str, Any]:
    """Create a PENDING_REVIEW prescription and activate it."""
    rx = create_prescription(elder_id, physician_headers, **overrides)
    return activate_prescription(rx["id"])


def get_prescription(prescription_id: str,
                     headers: Optional[Dict[str, str]] = None,
                     ) -> Dict[str, Any]:
    return get_success_data(api_client.get_prescription(
        prescription_id, headers or SUPERVISOR,
    ))


# ===========================================================================
# Visit reservations (PRD §3.6)
# ===========================================================================
def set_epidemic_mode(mode: str = "NORMAL",
                      max_temperature_c: Optional[float] = None,
                      max_visitors_per_day: Optional[int] = None,
                      ) -> Dict[str, Any]:
    return get_success_data(api_client.put_epidemic_config(
        epidemic_config_payload(
            mode=mode,
            max_temperature_c=max_temperature_c,
            max_visitors_per_day=max_visitors_per_day,
        ),
        ADMIN,
    ))


def create_visit_reservation(elder_id: str,
                             slot_start_at: str,
                             slot_end_at: str,
                             visitor_id_number: Optional[str] = None,
                             headers: Optional[Dict[str, str]] = None,
                             ) -> Dict[str, Any]:
    return get_success_data(api_client.create_visit_reservation(
        elder_id,
        create_visit_reservation_payload(
            slot_start_at=slot_start_at,
            slot_end_at=slot_end_at,
            visitor_id_number=visitor_id_number,
        ),
        headers or FAMILY,
    ))


# ===========================================================================
# Billing (PRD §3.7) — Tier 4 helper
# ===========================================================================
def _last_day_of_month(start: date) -> date:
    """Return last day of the calendar month containing ``start``."""
    if start.month == 12:
        nxt = date(start.year + 1, 1, 1)
    else:
        nxt = date(start.year, start.month + 1, 1)
    return nxt - timedelta(days=1)


def full_cycle_window(start: Optional[date] = None) -> Tuple[str, str, int]:
    """Choose a complete calendar-month cycle (e.g. 2025-06-01..2025-06-30).

    Returns (start_iso, end_iso, days_in_cycle).
    """
    start = start or date(2025, 6, 1)
    end = _last_day_of_month(start)
    days = (end - start).days + 1
    return start.isoformat(), end.isoformat(), days


def create_bill(elder_id: str,
                cycle_start_date: str,
                cycle_end_date: str,
                billing_mode: str = "PACKAGE",
                headers: Optional[Dict[str, str]] = None,
                ) -> Dict[str, Any]:
    return get_success_data(api_client.create_bill(
        elder_id,
        create_bill_payload(cycle_start_date, cycle_end_date, billing_mode),
        headers or FINANCE,
    ))


def finalize_bill(bill_id: str,
                  headers: Optional[Dict[str, str]] = None,
                  ) -> Dict[str, Any]:
    return get_success_data(api_client.finalize_bill(
        bill_id, headers or FINANCE,
    ))


def pay_bill(bill_id: str,
             external_payment_ref: Optional[str] = None,
             headers: Optional[Dict[str, str]] = None,
             ) -> Dict[str, Any]:
    return get_success_data(api_client.pay_bill(
        bill_id, pay_bill_payload(external_payment_ref),
        headers or FAMILY,
    ))


# ===========================================================================
# Tier 5: finalize + pay an entire bill end-to-end
# ===========================================================================
def setup_admitted_with_finalized_bill(
    cycle_start: Optional[date] = None,
    billing_mode: str = "PACKAGE",
    deposit_cents: int = 1_000_000,
    adl_score: int = 80,
    cognitive_score: int = 10,
    medical_condition_score: int = 20,
    monthly_bed_fee_cents: int = 60_000,
) -> Dict[str, Any]:
    """Admit an elder over a full calendar month, then finalize a bill.

    Returns ``{elder, room, bed, assessment, bill, days, start, end}``.
    """
    bundle = setup_admitted_elder_v2(
        adl_score=adl_score,
        cognitive_score=cognitive_score,
        medical_condition_score=medical_condition_score,
        deposit_cents=deposit_cents,
        monthly_bed_fee_cents=monthly_bed_fee_cents,
    )
    start_iso, end_iso, days = full_cycle_window(cycle_start)
    bill = create_bill(
        bundle["elder"]["id"], start_iso, end_iso, billing_mode,
    )
    bill = finalize_bill(bill["id"])
    bundle.update({
        "bill": bill,
        "days": days,
        "start": start_iso,
        "end": end_iso,
    })
    return bundle


# ===========================================================================
# Audit log access (PRD §2.8)
# ===========================================================================
def list_audit_logs(headers: Optional[Dict[str, str]] = None,
                    **params: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    offset = 0
    while True:
        resp = api_client.list_audit_logs(
            headers or ADMIN,
            params={"limit": 100, "offset": offset, **params},
        )
        data, meta = validate_paginated(resp)
        rows.extend(data)
        if not meta.get("has_more"):
            break
        offset += len(data) or 100
        if len(rows) > 10_000:
            break
    return rows


# ===========================================================================
# External-event ingestion helpers (PRD §2.10, §3.9)
# ===========================================================================
def ingest_external_event(source: str,
                          event_type: str,
                          payload: Dict[str, Any],
                          idempotency_key: Optional[str] = None,
                          headers: Optional[Dict[str, str]] = None,
                          ) -> Dict[str, Any]:
    return get_success_data(api_client.ingest_external_event(
        external_event_payload(
            source=source,
            event_type=event_type,
            payload=payload,
            idempotency_key=idempotency_key,
        ),
        headers or SYSTEMSYNC,
    ))


# ===========================================================================
# Waitlist helpers (PRD §3.1)
# ===========================================================================
def enqueue_waitlist(elder_id: str,
                     requested_bed_type: str = "SINGLE",
                     headers: Optional[Dict[str, str]] = None,
                     ) -> Dict[str, Any]:
    return get_success_data(api_client.create_waitlist_entry(
        create_waitlist_payload(elder_id, requested_bed_type),
        headers or ADMIN,
    ))


__all__ = [
    "ADMIN", "ADMIN_ALT", "SUPERVISOR", "SUPERVISOR_ALT",
    "PHYSICIAN", "PHYSICIAN_ALT",
    "NURSE", "NURSE_ALT", "NURSE_THIRD",
    "CAREGIVER", "FAMILY", "FINANCE", "SYSTEMSYNC",
    "advance_clock", "run_sweep",
    "create_room", "create_bed", "create_room_with_bed",
    "create_intensive_room_with_bed",
    "create_elder", "get_elder", "update_elder", "top_up_deposit",
    "draft_assessment", "submit_assessment", "approve_assessment",
    "create_approved_assessment",
    "create_draft_care_plan", "activate_care_plan",
    "create_active_care_plan",
    "admit_elder", "leave_elder", "return_elder",
    "transfer_elder", "discharge_elder",
    "setup_admitted_elder_v2", "setup_admitted_intensive_elder",
    "setup_admitted_elder_with_active_plan",
    "create_prescription", "activate_prescription",
    "create_active_prescription", "get_prescription",
    "set_epidemic_mode", "create_visit_reservation",
    "full_cycle_window", "create_bill", "finalize_bill", "pay_bill",
    "setup_admitted_with_finalized_bill",
    "list_audit_logs",
    "ingest_external_event",
    "enqueue_waitlist",
]
