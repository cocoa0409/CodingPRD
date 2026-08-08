"""Collateral writes and multi-hop cascades (PRD 2.11, 3.2, 3.6, 3.8, 3.9).

Every hop is a real write: the affected row's `version` is incremented and its
`updated_at` refreshed exactly as if it had been addressed directly.
"""
import calc
import config
import store
import util


# ------------------------------------------------------------- pellets -----
def recompute_pellets_allocated(procedure):
    total = 0
    for row in calc.allocations_of_procedure(procedure["id"]):
        if row["status"] in config.ALLOCATED_STATUSES:
            total += row["quantity"]
    procedure["pellets_allocated"] = total
    return total


def move_lot(lot, frm, to, quantity):
    lot[frm] -= quantity
    lot[to] += quantity
    store.touch(lot)


def release_allocations(procedure, statuses=("RESERVED", "OPENED")):
    """Return reserved/opened pellets to the shelf."""
    for row in calc.allocations_of_procedure(procedure["id"]):
        if row["status"] not in statuses:
            continue
        lot = store.get("PelletLot", row["lot_id"])
        row["status"] = "RELEASED"
        store.touch(row)
        if lot is not None:
            move_lot(lot, "qty_reserved", "qty_on_hand", row["quantity"])
    recompute_pellets_allocated(procedure)


# ------------------------------------------------------------ patients -----
def recompute_eligibility(patient):
    patient["eligibility_status"] = calc.patient_eligibility_projection(patient)


def set_clinical_hold(patient, value):
    patient["clinical_hold"] = bool(value)
    recompute_eligibility(patient)
    store.touch(patient)


def set_financial_hold(patient, value):
    patient["financial_hold"] = bool(value)
    recompute_eligibility(patient)
    store.touch(patient)


def mint_notification(patient, notification_type, message, severity_class=None,
                      procedure_id=None, lot_id=None):
    now = store.now()
    row = store.create("PatientNotification", {
        "patient_id": patient["id"],
        "procedure_id": procedure_id,
        "lot_id": lot_id,
        "notification_type": notification_type,
        "severity_class": severity_class,
        "message": message,
        "due_at": util.add_days(now, config.RECALL_NOTIFICATION_DUE_DAYS),
        "acknowledged_at": None,
        "status": "PENDING",
    })
    patient["open_notification_count"] = patient.get("open_notification_count", 0) + 1
    store.touch(patient)
    return row


def recompute_last_insertion(patient):
    best = None
    for proc in store.where("Procedure", patient_id=patient["id"]):
        if proc["status"] != "COMPLETED" or proc.get("performed_at") is None:
            continue
        if best is None or proc["performed_at"] > best["performed_at"]:
            best = proc
    patient["last_insertion_at"] = best["performed_at"] if best else None
    patient["last_insertion_hormone_type"] = best["hormone_type"] if best else None


# ---------------------------------------------------------- procedures -----
def freeze_procedure(procedure, hold_reason):
    """SCHEDULED / CONSENTED / SUPPLY_OPENED -> SUPPLY_HOLD (PRD 3.6)."""
    was_opened = procedure["status"] == "SUPPLY_OPENED"
    procedure["status"] = "SUPPLY_HOLD"
    procedure["hold_reason"] = hold_reason
    release_allocations(procedure)
    if was_opened:
        procedure["pellets_opened"] = 0
    store.touch(procedure)


def unfreeze_procedure(procedure):
    """SUPPLY_HOLD -> SCHEDULED; the procedure must be re-consented."""
    procedure["status"] = "SCHEDULED"
    procedure["hold_reason"] = None
    procedure["consent_record_id"] = None
    store.touch(procedure)


# ------------------------------------------------------------- consents ----
def supersede_consents(rows):
    for row in rows:
        if row["status"] == "ACTIVE":
            row["status"] = "SUPERSEDED"
            store.touch(row)


def highest_protocol_version(hormone_type):
    best = 0
    for row in store.where("Protocol", hormone_type=hormone_type):
        best = max(best, row["protocol_version"])
    return best


# ------------------------------------ protocol publication cascade ---------
def protocol_publication_cascade(hormone_type):
    """Hops 2 to 4: supersede consent, de-consent procedures, notify."""
    superseded = []
    for row in store.where("ConsentRecord", hormone_type=hormone_type):
        if row["status"] == "ACTIVE":
            row["status"] = "SUPERSEDED"
            store.touch(row)
            superseded.append(row["id"])
    if not superseded:
        return
    for proc in store.all_rows("Procedure"):
        if proc["status"] != "CONSENTED":
            continue
        if proc.get("consent_record_id") not in superseded:
            continue
        proc["consent_record_id"] = None
        proc["status"] = "SCHEDULED"
        store.touch(proc)
        patient = store.get("Patient", proc["patient_id"])
        if patient is not None:
            mint_notification(
                patient,
                "CONSENT_REQUIRED",
                "A new clinical protocol has been published; re-consent is required "
                "before this procedure may proceed.",
                severity_class=None,
                procedure_id=proc["id"],
            )


# ------------------------------ severe adverse-event cascade ---------------
def severe_adverse_event_cascade(patient, lot, order):
    """Hops 1 to 4 of PRD 3.8."""
    set_clinical_hold(patient, True)
    supersede_consents(store.where("ConsentRecord", patient_id=patient["id"]))
    if lot is not None and lot["sterility_status"] == "RELEASED":
        lot["sterility_status"] = "QUARANTINED"
        store.touch(lot)
    if order is not None and order["status"] == "ACTIVE":
        order["status"] = "SUSPENDED"
        order["suspended_reason"] = "SEVERE_ADVERSE_EVENT"
        store.touch(order)
        for proc in store.where("Procedure", standing_order_id=order["id"]):
            if proc["status"] in ("SCHEDULED", "CONSENTED", "SUPPLY_OPENED"):
                freeze_procedure(proc, "STANDING_ORDER_SUSPENDED")


def clear_clinical_hold_if_resolved(patient):
    """A review reaching CLOSED lifts the hold when nothing else holds it."""
    for event in store.where("AdverseEvent", patient_id=patient["id"]):
        if event["severity"] in ("SEVERE", "SURVEILLANCE") and event["status"] in (
            "OPEN",
            "ESCALATED",
        ):
            return False
    set_clinical_hold(patient, False)
    return True


# ------------------------------------------ lot recall cascade -------------
def recall_lot_cascade(lot, severity_class, recall_reason):
    """The five-hop recall of PRD 3.8."""
    now = store.now()
    # hop 1
    lot["sterility_status"] = "RECALLED"
    lot["qty_returned"] += lot["qty_on_hand"]
    lot["qty_on_hand"] = 0
    lot["recall_severity"] = severity_class
    lot["recall_reason"] = recall_reason
    lot["recalled_at"] = now
    store.touch(lot)

    # hop 2
    released_procedure_ids = []
    flagged_procedure_ids = []
    for row in calc.allocations_of_lot(lot["id"]):
        if row["status"] in ("RESERVED", "OPENED"):
            row["status"] = "RECALL_RELEASED"
            store.touch(row)
            move_lot(lot, "qty_reserved", "qty_returned", row["quantity"])
            released_procedure_ids.append(row["procedure_id"])
        elif row["status"] == "CONSUMED":
            row["status"] = "RECALL_FLAGGED"
            store.touch(row)
            flagged_procedure_ids.append(row["procedure_id"])

    # hop 3a -- recall axis, COMPLETED procedures only
    affected = []
    for procedure_id in _unique(flagged_procedure_ids):
        proc = store.get("Procedure", procedure_id)
        if proc is None or proc["status"] != "COMPLETED":
            continue
        if proc.get("recall_status") != "NONE":
            continue
        proc["recall_status"] = "RECALL_AFFECTED"
        store.touch(proc)
        affected.append(proc)

    # hop 3b -- primary axis, live procedures frozen
    for procedure_id in _unique(released_procedure_ids):
        proc = store.get("Procedure", procedure_id)
        if proc is None:
            continue
        if proc["status"] in ("SCHEDULED", "CONSENTED", "SUPPLY_OPENED"):
            freeze_procedure(proc, "LOT_RECALL")
        else:
            before = proc.get("pellets_allocated")
            if recompute_pellets_allocated(proc) != before:
                store.touch(proc)

    # hops 4 and 5 -- notify, then surveil for a class-one recall
    for proc in affected:
        patient = store.get("Patient", proc["patient_id"])
        if patient is None:
            continue
        mint_notification(
            patient,
            "RECALL",
            "Pellet lot %s has been recalled; please contact the clinic." % lot["lot_code"],
            severity_class=severity_class,
            procedure_id=proc["id"],
            lot_id=lot["id"],
        )
        proc["recall_status"] = "NOTIFIED"
        store.touch(proc)
        if severity_class == "CLASS_I":
            store.create("AdverseEvent", {
                "patient_id": patient["id"],
                "procedure_id": proc["id"],
                "injection_visit_id": None,
                "lot_id": lot["id"],
                "standing_order_id": None,
                "reported_by_provider_id": proc["provider_id"],
                "reviewed_by_provider_id": None,
                "severity": "SURVEILLANCE",
                "source": "RECALL_SURVEILLANCE",
                "narrative": "Class I recall surveillance for pellet lot %s." % lot["lot_code"],
                "onset_at": now,
                "review_due_at": None,
                "disposition_note": None,
                "status": "OPEN",
            })
            set_clinical_hold(patient, True)


def _unique(values):
    seen = set()
    out = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


# ------------------------------------------ delinquency ops run ------------
def recompute_plan_money(plan):
    paid = sum(e["amount_cents"] for e in plan["schedule"] if e["status"] == "PAID")
    outstanding = sum(
        e["amount_cents"] for e in plan["schedule"] if e["status"] in ("PENDING", "MISSED")
    )
    waived = sum(e["amount_cents"] for e in plan["schedule"] if e["status"] == "WAIVED")
    missed = sum(1 for e in plan["schedule"] if e["status"] == "MISSED")
    plan["paid_installment_cents"] = paid
    plan["outstanding_cents"] = outstanding
    plan["waived_cents"] = waived
    plan["missed_count"] = missed


def delinquency_run():
    """Phase 1 financing, then phase 2 notifications (PRD 3.9)."""
    now = store.now()
    counters = {
        "plans_scanned": 0,
        "entries_missed": 0,
        "plans_delinquent": 0,
        "plans_defaulted": 0,
        "patients_held": 0,
        "procedures_held": 0,
        "notifications_overdue": 0,
    }
    held_patients = set()

    for plan in store.all_rows("FinancingPlan"):
        if plan["status"] not in ("ACTIVE", "DELINQUENT"):
            continue
        counters["plans_scanned"] += 1
        changed = False
        for entry in sorted(plan["schedule"], key=lambda e: e["index"]):
            if entry["status"] != "PENDING":
                continue
            if util.days_between(entry["due_date"], now) > config.FINANCING_GRACE_PERIOD_DAYS:
                entry["status"] = "MISSED"
                plan["late_fee_cents"] += config.FINANCING_LATE_FEE_CENTS
                counters["entries_missed"] += 1
                changed = True
        before_missed = plan["missed_count"]
        recompute_plan_money(plan)
        if plan["missed_count"] != before_missed:
            changed = True
        if plan["missed_count"] >= config.FINANCING_DEFAULT_MISSED_THRESHOLD:
            if plan["status"] != "DEFAULTED":
                plan["status"] = "DEFAULTED"
                counters["plans_defaulted"] += 1
                changed = True
                patient = store.get("Patient", plan["patient_id"])
                if patient is not None:
                    if not patient["financial_hold"]:
                        held_patients.add(patient["id"])
                    set_financial_hold(patient, True)
                    for proc in store.where("Procedure", patient_id=patient["id"]):
                        if proc["status"] == "SCHEDULED":
                            freeze_procedure(proc, "PATIENT_FINANCIAL_HOLD")
                            counters["procedures_held"] += 1
        elif plan["missed_count"] >= 1:
            if plan["status"] != "DELINQUENT":
                plan["status"] = "DELINQUENT"
                counters["plans_delinquent"] += 1
                changed = True
        if changed:
            store.touch(plan)

    counters["patients_held"] = len(held_patients)

    for note in store.all_rows("PatientNotification"):
        if note["status"] == "PENDING" and note["due_at"] < now:
            note["status"] = "OVERDUE"
            store.touch(note)
            counters["notifications_overdue"] += 1
    return counters


# ------------------------------- financing cancelled by a procedure --------
def cancel_plans_for_procedure(procedure, membership, cancel_tier, cancel_fee_cents):
    """A cancelled procedure waives and settles its financing plan (PRD 3.9)."""
    now = store.now()
    for plan in store.where("FinancingPlan", procedure_id=procedure["id"]):
        if plan["status"] not in ("DRAFT", "ACTIVE", "DELINQUENT"):
            continue
        for entry in plan["schedule"]:
            if entry["status"] in ("PENDING", "MISSED"):
                entry["status"] = "WAIVED"
        recompute_plan_money(plan)
        settlement = calc.refund_settlement_cents(
            procedure, membership, now, "FINAL_SETTLEMENT", plan=plan,
            forced_tier=cancel_tier, forced_fee=cancel_fee_cents,
        )
        plan["refunded_cents"] = settlement["refund_cents"]
        plan["status"] = "CANCELLED"
        store.touch(plan)
