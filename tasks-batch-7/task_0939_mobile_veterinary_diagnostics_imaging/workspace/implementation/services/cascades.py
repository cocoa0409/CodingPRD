"""The multi-hop cascades: stop bump (PRD 3.3), provider-side cancellation
(PRD 3.4), image-QC repeat (PRD 3.5) and the seven-hop equipment quarantine
(PRD 3.6)."""

from core import clock, db, gates
from services import derive, notify, pricing


# --------------------------------------------------------------------------
# billing reversal leg, shared by the quarantine and bump cascades
# --------------------------------------------------------------------------

def reverse_study_billing(study, reason):
    """Reverse a study's ACTIVE lines on OPEN invoices and refund its block draw."""
    touched_any = False
    for line in db.sort_rows(db.where("charge_lines", study_id=study["id"])):
        if line["status"] != "ACTIVE":
            continue
        invoice = db.get("invoices", line["invoice_id"])
        if invoice is None or invoice["status"] != "OPEN":
            continue
        line["status"] = "REVERSED"
        line["reversal_reason"] = reason
        db.touch(line)
        touched_any = True

    if study["billing_status"] == "POSTED" and touched_any:
        study["billing_status"] = "REVERSED"
        db.touch(study)

    if touched_any:
        _refund_block_draw(study)


def _refund_block_draw(study):
    entries = db.sort_rows(db.where("block_ledger_entries", study_id=study["id"]))
    draws = [e for e in entries if e["reason"] == "DRAW"]
    refunds = [e for e in entries if e["reason"] == "REFUND_QC"]
    if len(draws) <= len(refunds):
        return
    contract = db.get("contracts", draws[-1]["contract_id"])
    if contract is None:
        return
    rec = db.new_record(with_version=False)
    rec["contract_id"] = contract["id"]
    rec["study_id"] = study["id"]
    rec["delta_studies"] = 1
    rec["reason"] = "REFUND_QC"
    db.insert("block_ledger_entries", rec)
    rec["balance_after_studies"] = derive.contract_remaining(contract)
    db.touch(contract)


# --------------------------------------------------------------------------
# equipment quarantine — the seven-hop cascade (PRD 3.6)
# --------------------------------------------------------------------------

def blast_radius(equipment):
    """Studies acquired on this unit at or after the cutoff, created_at ASC."""
    cutoff = equipment.get("last_passing_qc_at") or equipment["created_at"]
    out = []
    for study in db.all_rows("studies"):
        if study.get("equipment_id") != equipment["id"]:
            continue
        if study.get("acquired_at") is None:
            continue
        if study["acquired_at"] < cutoff:
            continue
        if study["workflow_status"] in ("CANCELLED", "NOT_PERFORMED", "REPEAT_PENDING"):
            continue
        out.append(study)
    return db.sort_rows(out)


def quarantine_cascade(equipment, affected):
    """Runs AFTER gate G1 has cleared.  Returns the affected study count."""
    now = clock.now()

    # HOP 1 — the unit is quarantined.
    equipment["quarantined_at"] = now
    db.touch(equipment)

    touched_stops = []
    for study in affected:
        # HOP 2 — retroactive demotion on both axes.
        study["qc_status"] = "REPEAT_REQUIRED"
        study["workflow_status"] = "REPEAT_PENDING"
        db.touch(study)

        # HOP 2b — published reports on those studies are retracted.
        for report in db.sort_rows(db.where("reports", study_id=study["id"])):
            if report["status"] != "PUBLISHED":
                continue
            report["status"] = "RETRACTED"
            report["retracted_at"] = now
            report["retract_reason"] = "EQUIPMENT_QUARANTINE"
            db.touch(report)

        # HOP 3 — open read assignments are revoked (HOP 4 = the specialists'
        # open_read_count / workload_score, both derived on read, move downward).
        for assignment in db.sort_rows(db.where("read_assignments", study_id=study["id"])):
            if assignment["status"] not in ("OFFERED", "ACCEPTED"):
                continue
            assignment["status"] = "REVOKED"
            assignment["responded_at"] = now
            db.touch(assignment)

        # HOP 4b — charge lines reversed, billing axis POSTED -> REVERSED, and
        # HOP 6 — the block draw refunded.
        reverse_study_billing(study, "EQUIPMENT_QUARANTINE")

        stop = derive.stop_of_study(study)
        if stop is not None and stop["id"] not in [s["id"] for s in touched_stops]:
            touched_stops.append(stop)

        # HOP 7 — one notification per condemned study.
        notify.append(
            derive.clinic_id_of_study(study),
            study["id"],
            "STUDY_REPEAT_REQUIRED",
            "Study %s condemned by equipment quarantine." % study["id"],
        )

    # HOP 4c — the survivors at those stops get MORE expensive.
    # HOP 5 — invoice total_cents / posted_study_count are derived on read.
    for stop in touched_stops:
        pricing.reprice_stop_siblings(stop)

    return len(affected)


# --------------------------------------------------------------------------
# image-QC move into REPEAT_PENDING — the four-hop trip-share cascade (PRD 3.5)
# --------------------------------------------------------------------------

def repeat_pending_trip_share_cascade(study):
    """
    # Adjudication of friction 8: the four-hop trip-share re-allocation is
    # attached to the MOVE INTO REPEAT_PENDING, not to the REPEAT_REQUIRED
    # verdict alone.  Chosen in reachability terms: membership of the billable
    # set is defined purely by workflow state, so a NON_DIAGNOSTIC verdict
    # removes the study from the set exactly as REPEAT_REQUIRED does.  Attaching
    # the cascade to only one branch would leave the derived trip_share_cents
    # of the survivors disagreeing with their own ACTIVE charge lines after a
    # NON_DIAGNOSTIC verdict, breaking INV_MONEY_INVOICE_TOTAL and making the
    # re-price-in-place behaviour unreachable on that branch.  PRD 3.5 states
    # the same reading explicitly.
    """
    stop = derive.stop_of_study(study)
    if stop is None:
        return
    pricing.reprice_stop_siblings(stop)


# --------------------------------------------------------------------------
# provider-side appointment / stop cancellation (PRD 3.3, 3.4)
# --------------------------------------------------------------------------

def cancel_appointment_provider(appt, cancel_reason, notify_clinic=True):
    """Move one appointment to CANCELLED_BY_PROVIDER and fan out to its studies."""
    now = clock.now()
    appt["status"] = "CANCELLED_BY_PROVIDER"
    appt["cancelled_at"] = now
    if cancel_reason is not None:
        appt["cancel_reason"] = cancel_reason
    db.touch(appt)

    stops = []
    for study in derive.studies_of_appointment(appt):
        if study["workflow_status"] != "ORDERED":
            continue
        study["workflow_status"] = "NOT_PERFORMED"
        study["cancellation_fee_cents"] = 0
        study["billing_status"] = "NON_BILLABLE"
        if cancel_reason is not None:
            study["cancel_reason"] = cancel_reason
        db.touch(study)
        # HOP 4 of the bump cascade / the same leg on a stop cancel.
        reverse_study_billing(study, cancel_reason or "PROVIDER_CANCELLED")
        stop = derive.stop_of_study(study)
        if stop is not None and stop["id"] not in [s["id"] for s in stops]:
            stops.append(stop)

    # Adjudication of friction 1 (provider limb): the surviving billable set is
    # re-derived from scratch.  Since every study removed here was ORDERED and
    # ORDERED studies are never members of the billable set, the re-derivation
    # is a no-op on the survivors' shares — which is exactly what makes this
    # choice safe under BOTH readings of the friction.
    for stop in stops:
        pricing.reprice_stop_siblings(stop)

    if notify_clinic:
        referral = derive.referral_of_appointment(appt)
        notify.append(
            referral["clinic_id"] if referral else None,
            None,
            "APPOINTMENT_CANCELLED",
            "Appointment %s cancelled by the provider." % appt["id"],
        )


def bump_stop(victim, stat_stop_id):
    """PLANNED -> BUMPED with the six-hop cascade of PRD 3.3."""
    now = clock.now()
    # HOP 1
    victim["status"] = "BUMPED"
    victim["bumped_by_stop_id"] = stat_stop_id
    victim["cancel_reason"] = "BUMPED_BY_STAT_INSERTION"
    db.touch(victim)
    _ = now

    # HOPS 2-6
    for appt in derive.appointments_of_stop(victim):
        if appt["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        cancel_appointment_provider(appt, "STOP_BUMPED", notify_clinic=True)

    notify.append(
        victim["clinic_id"],
        None,
        "STOP_BUMPED",
        "Stop %s was bumped by a STAT insertion." % victim["id"],
    )


def cancel_stop(stop, cancel_reason):
    """PLANNED/EN_ROUTE -> CANCELLED with the provider-side fan-out (PRD 3.4)."""
    stop["status"] = "CANCELLED"
    stop["cancel_reason"] = cancel_reason
    db.touch(stop)
    for appt in derive.appointments_of_stop(stop):
        if appt["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        cancel_appointment_provider(appt, cancel_reason, notify_clinic=True)


def guard_provider_cancel_gate_g1(stop):
    """G1 for the cascade legs that would reverse charge lines."""
    study_ids = []
    for appt in derive.appointments_of_stop(stop):
        if appt["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        for study in derive.studies_of_appointment(appt):
            if study["workflow_status"] == "ORDERED":
                study_ids.append(study["id"])
    gates.g1_no_frozen_lines(study_ids)
