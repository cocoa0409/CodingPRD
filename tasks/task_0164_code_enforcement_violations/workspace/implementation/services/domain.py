"""Core domain logic: lazy overdue evaluation, fine recomputation, case posture,
balance recomputation, and child lookups.

These functions implement the cross-cutting recomputation described in PRD §2.5,
§3.6, §3.10, and the case_posture / fine_accrual calculations (SCAFFOLD §1.3).
"""

from clock import clock
from db import db, touch
from services import calc


# ---------------------------------------------------------------------------
# Child lookups by foreign key
# ---------------------------------------------------------------------------

def fee_schedule_for(violation_class):
    """Return a FeeSchedule row matching violation_class, or None."""
    for fs in db.fee_schedules.values():
        if fs["violation_class"] == violation_class:
            return fs
    return None


def notices_for_case(case_id):
    return [n for n in db.notices.values() if n["case_id"] == case_id]


def fines_for_case(case_id):
    """All Fine ledger lines whose notice belongs to the case."""
    case_notice_ids = {n["id"] for n in db.notices.values() if n["case_id"] == case_id}
    return [f for f in db.fines.values() if f["notice_id"] in case_notice_ids]


def fines_for_notice(notice_id):
    return [f for f in db.fines.values() if f["notice_id"] == notice_id]


def abatement_orders_for_case(case_id):
    return [a for a in db.abatement_orders.values() if a["case_id"] == case_id]


def liens_for_case(case_id):
    return [l for l in db.liens.values() if l["case_id"] == case_id]


def hearings_for_notice(notice_id):
    return [h for h in db.hearings.values() if h["notice_id"] == notice_id]


def owner_for_case(case):
    prop = db.properties.get(case["property_id"])
    if prop is None:
        return None
    return db.owners.get(prop["owner_id"])


# ---------------------------------------------------------------------------
# Notice: lazy OVERDUE evaluation + provisional fine recomputation
# ---------------------------------------------------------------------------

def evaluate_notice(notice):
    """Lazily evaluate ISSUED->OVERDUE and recompute provisional fine for OVERDUE
    notices against the current clock (PRD §3.6).

    Mutates the notice in place; returns the notice. Frozen statuses are untouched
    except that days_overdue/fine_total are left as stored.
    """
    now = clock.now()
    fs = fee_schedule_for(notice["violation_class"])

    if notice["status"] == "ISSUED":
        # Lazy crossing into OVERDUE: clock passed deadline and no PASSED reinspection.
        if notice["compliance_deadline"] is not None and now > notice["compliance_deadline"]:
            has_passed = any(
                r["notice_id"] == notice["id"] and r["result"] == "PASSED"
                for r in db.reinspections.values()
            )
            if not has_passed:
                notice["status"] = "OVERDUE"
                touch(notice)

    if notice["status"] == "OVERDUE":
        if fs is not None:
            total, days = calc.fine_accrual(
                fs, notice["escalation_multiplier"], notice["compliance_deadline"], now
            )
            notice["fine_total_cents"] = total
            notice["days_overdue"] = days
    return notice


def freeze_fine(notice, as_of):
    """Freeze fine_total_cents / days_overdue at the settlement variant as-of an
    instant (PRD §3.6 settlement variant). Returns the frozen total.
    """
    fs = fee_schedule_for(notice["violation_class"])
    if fs is None:
        return notice["fine_total_cents"]
    total, days = calc.fine_accrual(
        fs, notice["escalation_multiplier"], notice["compliance_deadline"], as_of
    )
    notice["fine_total_cents"] = total
    notice["days_overdue"] = days
    return total


# ---------------------------------------------------------------------------
# Case posture + outstanding balance recomputation (PRD §2.5, §3.10)
# ---------------------------------------------------------------------------

def compute_posture(case):
    """Compute the compound posture in strict priority order (PRD §2.5)."""
    if case.get("closed_at") is not None:
        return "CLOSED"
    if any(l["status"] == "RECORDED" for l in liens_for_case(case["id"])):
        return "LIENED"
    if any(a["status"] in ("ORDERED", "IN_PROGRESS") for a in abatement_orders_for_case(case["id"])):
        return "ABATEMENT"
    if any(
        n["status"] in ("ISSUED", "OVERDUE", "CONTESTED", "UPHELD")
        for n in notices_for_case(case["id"])
    ):
        return "ACTIVE"
    return "INTAKE"


def compute_balance(case):
    """outstanding_balance_cents = sum of provisional fine_total_cents over the
    case's notices NOT in {DISMISSED, SETTLED}, plus recorded abatement cost,
    minus payments_applied_cents (PRD §3.10).

    Recorded abatement cost = sum of OPEN ABATEMENT_COST Fine.assessed_cents on the
    case (settled/waived excluded).
    """
    total = 0
    for n in notices_for_case(case["id"]):
        if n["status"] in ("DISMISSED", "SETTLED"):
            continue
        # For OVERDUE notices, use the live provisional total.
        if n["status"] == "OVERDUE":
            evaluate_notice(n)
        total += n["fine_total_cents"] or 0

    for f in fines_for_case(case["id"]):
        if f["source_kind"] == "ABATEMENT_COST" and f["settlement_status"] == "OPEN":
            total += f["assessed_cents"] or 0

    total -= case["payments_applied_cents"]
    # The balance floors at zero: payments may exceed the fine ledger (e.g. a lien
    # payment covers the admin fee, which is not itself a Fine line), and PRD §3.12
    # asserts release "recomputes outstanding_balance_cents to zero". A settled case
    # therefore never reports a negative balance.
    if total < 0:
        total = 0
    return total


def recompute_case(case, bump=True):
    """Recompute posture and outstanding_balance on the case, and (by default)
    mutate it — bumping version and refreshing updated_at (PRD §2.5).

    Pass bump=False for read-time previews that must not mutate.
    """
    case["posture"] = compute_posture(case)
    case["outstanding_balance_cents"] = compute_balance(case)
    if bump:
        touch(case)


def refresh_case_for_read(case):
    """Read-time live recomputation that does NOT mutate version/updated_at
    (PRD §2.5: 'fetching a case recomputes its posture and provisional balance')."""
    # Evaluate notices lazily so OVERDUE crossing is visible, but those notice
    # mutations are their own; the case read itself does not bump the case version.
    for n in notices_for_case(case["id"]):
        evaluate_notice(n)
    case["posture"] = compute_posture(case)
    case["outstanding_balance_cents"] = compute_balance(case)
