"""Entity construction, serialization, and common-field management.

Per PRD §2.4 every primary resource carries id/created_at/updated_at/version;
custody events carry only id/created_at.
"""

import uuid
from datetime import datetime, timezone

from db import db, fmt_iso, clock_now


def new_id():
    return str(uuid.uuid4())


def _stamp_new(obj):
    now = fmt_iso(clock_now())
    obj["id"] = new_id()
    obj["created_at"] = now
    obj["updated_at"] = now
    obj["version"] = 1
    return obj


def touch(obj):
    """Refresh updated_at and increment version (PRD §2.4: recomputation counts)."""
    obj["updated_at"] = fmt_iso(clock_now())
    obj["version"] = obj.get("version", 1) + 1
    return obj


# ---------------------------------------------------------------------------
# Constructors — set system fields; input fields set by the caller
# ---------------------------------------------------------------------------

def make_store(store_number, name, region_code):
    return _stamp_new({
        "store_number": store_number,
        "name": name,
        "region_code": region_code,
        "status": "ACTIVE",
        "total_adjudicated_loss_cents": 0,
        "restitution_collected_cents": 0,
    })


def make_employee(store_id, employee_ref, full_name):
    return _stamp_new({
        "store_id": store_id,
        "employee_ref": employee_ref,
        "full_name": full_name,
        "status": "ACTIVE",
        "prior_substantiated_count": 0,
    })


def make_exception_event(store_id, register_ref, txn_ref, exception_type,
                         amount_cents, occurred_at, employee_id):
    return _stamp_new({
        "store_id": store_id,
        "register_ref": register_ref,
        "txn_ref": txn_ref,
        "employee_id": employee_id,
        "exception_type": exception_type,
        "amount_cents": amount_cents,
        "occurred_at": occurred_at,
        "status": "UNAGGREGATED",
    })


def make_alert(store_id, employee_id):
    return _stamp_new({
        "store_id": store_id,
        "employee_id": employee_id,
        "subject_type": "EMPLOYEE" if employee_id else "UNKNOWN",
        "score": 0.0,
        "event_count": 0,
        "total_amount_cents": 0,
        "window_start": None,
        "window_end": None,
        "status": "OPEN",
        "case_id": None,
        "dismiss_reason": None,
        "_member_event_ids": [],  # internal: member event ids in attach order
    })


def mint_case_number(store):
    store_id = store["id"]
    seq = db.case_seq.get(store_id, 0) + 1
    db.case_seq[store_id] = seq
    return "LP-%s-%06d" % (store["store_number"], seq)


def make_case(store, source, subject_type, employee_id, created_by,
              manual_loss_cents=0):
    return _stamp_new({
        "case_number": mint_case_number(store),
        "store_id": store["id"],
        "source": source,
        "subject_type": subject_type,
        "employee_id": employee_id,
        "status": "OPEN",
        "created_by": created_by,
        "assigned_analyst_id": None,
        "manual_loss_cents": manual_loss_cents,
        "recovered_value_cents": 0,
        "total_loss_cents": 0,
        "priority": "STANDARD",
        "restitution_status": "NONE",
        "loss_posted_period_id": None,
        "loss_posted_cents": 0,
        "adjudicated_at": None,
        "adjudicated_by": None,
        "closed_at": None,
        "merged_into_case_id": None,
    })


def make_interview(case_id, interviewer_id, subject_employee_id,
                   scheduled_start, scheduled_end):
    return _stamp_new({
        "case_id": case_id,
        "interviewer_id": interviewer_id,
        "subject_employee_id": subject_employee_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "SCHEDULED",
        "outcome": None,
        "conducted_at": None,
        "notes": None,
        "documented_at": None,
        "doc_stale": False,
    })


def make_evidence_item(case_id, evidence_type, captured_at, retention_class,
                       retention_until):
    return _stamp_new({
        "case_id": case_id,
        "evidence_type": evidence_type,
        "captured_at": captured_at,
        "retention_class": retention_class,
        "retention_until": retention_until,
        "status": "ACTIVE",
        "sealed_by": None,
        "legal_hold": False,
    })


def make_custody_event(evidence_id, action, actor_id, note):
    now = fmt_iso(clock_now())
    return {
        "id": new_id(),
        "created_at": now,
        "evidence_id": evidence_id,
        "action": action,
        "actor_id": actor_id,
        "note": note,
    }


def make_civil_demand(case_id, basis, priors_offense_count, recovery_cost_cents,
                      created_by):
    return _stamp_new({
        "case_id": case_id,
        "basis": basis,
        "priors_offense_count": priors_offense_count,
        "recovery_cost_cents": recovery_cost_cents,
        "merchandise_loss_cents": 0,
        "statutory_penalty_cents": 0,
        "amount_due_cents": 0,
        "fees_incurred_cents": 0,
        "paid_to_date_cents": 0,
        "outstanding_cents": 0,
        "status": "DRAFT",
        "created_by": created_by,
        "issued_at": None,
        # internal waterfall paid counters
        "_fees_paid_cents": 0,
        "_penalty_paid_cents": 0,
        "_merch_paid_cents": 0,
    })


def make_restitution_payment(demand_id, amount_cents, method):
    return _stamp_new({
        "demand_id": demand_id,
        "amount_cents": amount_cents,
        "method": method,
        "status": "RECEIVED",
        "applied_fees_cents": 0,
        "applied_penalty_cents": 0,
        "applied_merch_cents": 0,
    })


def make_orc_group(name, description):
    return _stamp_new({
        "name": name,
        "description": description,
        "status": "IDENTIFIED",
        "confirmed_case_count": 0,
        "distinct_store_count": 0,
        "exposure_cents": 0,
    })


def make_case_link(case_id, orc_group_id, link_score):
    return _stamp_new({
        "case_id": case_id,
        "orc_group_id": orc_group_id,
        "link_score": link_score,
        "status": "PROPOSED",
    })


def make_shrink_period(store_id, period_start, period_end,
                       book_inventory_cents, period_sales_cents):
    return _stamp_new({
        "store_id": store_id,
        "period_start": period_start,
        "period_end": period_end,
        "book_inventory_cents": book_inventory_cents,
        "period_sales_cents": period_sales_cents,
        "counted_inventory_cents": None,
        "counted_at": None,
        "known_loss_posted_cents": 0,
        "accrual_case_basis_cents": 0,
        "accrual_sales_basis_cents": 0,
        "variance_cents": None,
        "variance_pct": None,
        "status": "OPEN",
        "auto_case_id": None,
    })


def make_referral_packet(case_id, jurisdiction_code):
    return _stamp_new({
        "case_id": case_id,
        "jurisdiction_code": jurisdiction_code,
        "status": "DRAFT",
        "packet_exposure_cents": 0,
        "submitted_at": None,
        "return_reason": None,
    })


# ---------------------------------------------------------------------------
# Serializers — strip internal fields (names starting with "_")
# ---------------------------------------------------------------------------

def pub(obj):
    return {k: v for k, v in obj.items() if not k.startswith("_")}
