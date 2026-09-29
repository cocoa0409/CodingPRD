"""Mutating domain helpers and multi-hop cascades (PRD 2.4, 2.5, 2.6, 3.x)."""

from decimal import Decimal

from db import db, base_record, touch, now_iso, today, creation_order, fmt_ts
from validation import parse_date, fmt_date
from services import calc
from services.calc import rhu

CONTRACT_SUSPENSION_REASON = {
    "PROBATION": "POSTURE_PROBATION",
    "SUSPENDED": "POSTURE_SUSPENDED",
    "DEBARRED": "AGENCY_DEBARRED",
}
LIVE_CONTRACT = calc.LIVE_CONTRACT_STATUSES


# --- bookkeeping ------------------------------------------------------------

def apply_changes(rec, changes):
    changed = False
    for key, value in changes.items():
        if rec.get(key) != value:
            rec[key] = value
            changed = True
    return changed


def commit(rec, changes):
    """Apply changes and, when anything actually moved, bump updated_at/version."""
    if apply_changes(rec, changes):
        touch(rec)
        return True
    return False


# --- disclosure / territory / contract cascades -----------------------------

def invalidate_disclosure(app):
    return commit(app, {"disclosure_state": "INVALIDATED", "disclosure_ack_token": None})


def release_assignment(assignment, status="RELEASED"):
    return commit(assignment, {"status": status, "released_on": fmt_date(today())})


def suspend_contract(contract, reason):
    """ACTIVE -> SUSPENDED plus its two cascade hops."""
    if contract["status"] != "ACTIVE":
        return False
    commit(contract, {"status": "SUSPENDED", "suspension_reason": reason})
    for assignment in creation_order(calc.contract_assignments(contract["id"])):
        if assignment["status"] == "ACTIVE":
            release_assignment(assignment)
    for app in creation_order(calc.agency_applications(contract["agency_id"])):
        if app["status"] == "DRAFT" and app["disclosure_state"] in ("ISSUED", "ACKNOWLEDGED"):
            invalidate_disclosure(app)
    return True


def suspend_agency_contracts(agency_id, reason, skip_contract_id=None):
    for contract in creation_order(calc.agency_contracts(agency_id)):
        if skip_contract_id is not None and contract["id"] == skip_contract_id:
            continue
        if contract["status"] == "ACTIVE":
            suspend_contract(contract, reason)


# --- posture ----------------------------------------------------------------

def set_posture(agency, target, reason, skip_contract_id=None):
    """Unconditional posture move (manual action or for-cause debarment)."""
    changed = commit(agency, {"compliance_posture": target, "last_posture_reason": reason})
    if target in ("PROBATION", "SUSPENDED", "DEBARRED"):
        suspend_agency_contracts(agency["id"],
                                 CONTRACT_SUSPENSION_REASON[target],
                                 skip_contract_id=skip_contract_id)
    return changed


def escalate_posture(agency, target, reason):
    """Automatic movement: escalation only, and never out of DEBARRED."""
    current = agency["compliance_posture"]
    if current == "DEBARRED":
        return False
    if calc.POSTURE_RANK[target] <= calc.POSTURE_RANK[current]:
        return False
    return set_posture(agency, target, reason)


# --- agency recomputes ------------------------------------------------------

def recompute_document_counts(agency):
    docs = calc.agency_documents(agency["id"])
    reviewed = sum(1 for d in docs if d["verification_state"] in calc.REVIEWED_STATES)
    fraud = sum(1 for d in docs if d["verification_state"] == "CONFIRMED_FRAUD")
    return commit(agency, {"reviewed_document_count": reviewed,
                           "confirmed_fraud_document_count": fraud})


def recompute_risk(agency):
    """Recompute both risk variants and follow the escalation cascade."""
    figures = calc.risk_scores(agency["id"])
    commit(agency, {
        "rolling_risk_score": float(figures["rolling"]),
        "lifetime_risk_score": float(figures["lifetime"]),
        "confirmed_incident_count": figures["confirmed_incident_count"],
        "reviewed_document_count": figures["reviewed_document_count"],
        "confirmed_fraud_document_count": figures["confirmed_fraud_document_count"],
    })
    target = calc.risk_target_posture(figures["rolling"])
    if target is not None:
        escalate_posture(agency, target, "RISK_SCORE_ESCALATION")


def recompute_agency_ledger(agency):
    net, liability = calc.agency_ledger_balance(agency["id"])
    return commit(agency, {"net_earned_commission_cents": net,
                           "clawback_liability_cents": liability})


def refresh_current_tier(agency):
    return commit(agency, {"current_tier": calc.current_tier(agency["id"])})


def recompute_application_net(app, defer=False):
    """Recompute net_commission_cents. With defer=True the caller bumps."""
    net = calc.application_net_commission(app["id"])
    if defer:
        changed = apply_changes(app, {"net_commission_cents": net})
        return changed
    return commit(app, {"net_commission_cents": net})


def application_agency(app):
    return db.agencies.get(app["agency_id"])


def refresh_integrity_hold(app, defer=False):
    docs = calc.application_documents(app["id"])
    held = any(d["verification_state"] in calc.FLAGGED_STATES for d in docs)
    if defer:
        return apply_changes(app, {"integrity_hold": held})
    return commit(app, {"integrity_hold": held})


# --- ledger -----------------------------------------------------------------

def create_accrual(app, milestone, event_date):
    """One ACCRUAL row per milestone unless a suppression gate fires."""
    program = db.programs.get(app["program_id"])
    if program is None or not program["commission_eligible"]:
        return None
    contract = db.contracts.get(app.get("pinned_contract_id"))
    schedule = db.schedules.get(app.get("pinned_schedule_id"))
    if contract is None or schedule is None:
        return None
    if contract["status"] in ("TERMINATED", "EXPIRED"):
        return None

    tier = calc.resolve_tier(app["agency_id"], event_date)
    effective_bps, amount = calc.milestone_amount(program, schedule, milestone, tier)
    entry = base_record()
    entry.update({
        "contract_id": contract["id"],
        "application_id": app["id"],
        "schedule_id": schedule["id"],
        "parent_entry_id": None,
        "kind": "ACCRUAL",
        "milestone": milestone,
        "milestone_event_date": fmt_date(event_date),
        "tier_snapshot": tier,
        "effective_bps": effective_bps,
        "amount_cents": amount,
        "state": "ACCRUED",
        "incentive_comp_prohibited": app["recruitment_origin"] == "DOMESTIC",
        "approved_by_user_id": None,
        "paid_by_user_id": None,
        "void_reason": None,
        "_parent_was_paid": False,
    })
    db.entries[entry["id"]] = entry
    return entry


def ledger_order(entries):
    return sorted(entries, key=lambda e: (e["milestone_event_date"], e["created_at"], e["_seq"]))


def clawback_ledger(app, withdrawal_date):
    """Withdrawal clawback ledger (PRD 3.7). Runs from every originating status."""
    program = db.programs.get(app["program_id"])
    schedule = db.schedules.get(app.get("pinned_schedule_id"))
    reversible = [e for e in calc.application_entries(app["id"])
                  if e["kind"] == "ACCRUAL" and e["state"] in ("ACCRUED", "APPROVED", "PAID")]
    reversible = ledger_order(reversible)
    if not reversible:
        return []

    census = parse_date(program["census_date"]) if program else None
    window = schedule["clawback_window_days"] if schedule else None
    created = []
    for parent in reversible:
        if census is not None and withdrawal_date < census:
            pct = Decimal("1.0000")
        elif window:
            event = parse_date(parent["milestone_event_date"])
            age = (withdrawal_date - event).days
            if age <= window:
                pct = rhu(Decimal(window - age) / Decimal(window), 4)
            else:
                pct = Decimal("0.0000")
        else:
            pct = Decimal("0.0000")

        amount = int(rhu(Decimal(parent["amount_cents"]) * pct, 0))
        if amount > 0:
            row = base_record()
            row.update({
                "contract_id": parent["contract_id"],
                "application_id": parent["application_id"],
                "schedule_id": parent["schedule_id"],
                "parent_entry_id": parent["id"],
                "kind": "CLAWBACK",
                "milestone": parent["milestone"],
                "milestone_event_date": parent["milestone_event_date"],
                "tier_snapshot": parent["tier_snapshot"],
                "effective_bps": parent["effective_bps"],
                "amount_cents": amount,
                "state": "CLAWED_BACK",
                "incentive_comp_prohibited": parent["incentive_comp_prohibited"],
                "approved_by_user_id": None,
                "paid_by_user_id": None,
                "void_reason": None,
                "_parent_was_paid": parent["state"] == "PAID",
            })
            db.entries[row["id"]] = row
            created.append(row)
            commit(parent, {"state": "CLAWED_BACK"})
    return created


def clawback_ratio_escalation(agency):
    accrued_total = 0
    clawed_total = 0
    for entry in calc.agency_entries(agency["id"]):
        if entry["kind"] == "ACCRUAL":
            accrued_total += entry["amount_cents"]
        elif entry["kind"] == "CLAWBACK" and entry["state"] == "CLAWED_BACK":
            clawed_total += entry["amount_cents"]
    if accrued_total <= 0:
        return
    ratio = Decimal(clawed_total) / Decimal(accrued_total)
    if ratio >= calc.CLAWBACK_RATIO_THRESHOLD and agency["compliance_posture"] == "GOOD_STANDING":
        escalate_posture(agency, "WATCH", "CLAWBACK_RATIO_THRESHOLD")


def forfeit_for_termination(contract, reason_code):
    """Termination hop 3: select and forfeit unvested accruals."""
    candidates = [e for e in calc.contract_entries(contract["id"])
                  if e["kind"] == "ACCRUAL" and e["state"] in ("ACCRUED", "APPROVED")]
    void_reason = "TERMINATION_" + reason_code
    touched_apps = []
    for entry in ledger_order(candidates):
        app = db.applications.get(entry["application_id"])
        keep = False
        if reason_code != "FOR_CAUSE" and app is not None:
            keep = app["status"] in ("ENROLLED", "CENSUS_CONFIRMED", "PERSISTED")
        if keep:
            continue
        commit(entry, {"state": "FORFEITED", "void_reason": void_reason})
        if app is not None and app not in touched_apps:
            touched_apps.append(app)
    for app in touched_apps:
        recompute_application_net(app)


def write_file_transition(app, from_agency_id, to_agency_id, contract, reason_code):
    record = base_record(with_version=False)
    record.update({
        "application_id": app["id"],
        "from_agency_id": from_agency_id,
        "to_agency_id": to_agency_id,
        "trigger_contract_id": contract["id"],
        "reason_code": "TERMINATION_" + reason_code,
        "application_status_at_transition": app["status"],
        "disclosure_reset": True,
    })
    db.transitions[record["id"]] = record
    return record


# --- epoch sweep ------------------------------------------------------------

def epoch_sweep():
    current = today()
    stamp = fmt_date(current)
    expired_contracts = 0
    expired_assignments = 0
    expired_certifications = 0

    for contract in creation_order(list(db.contracts.values())):
        if contract["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        term_end = parse_date(contract["term_end_date"])
        if term_end is None or not (term_end < current):
            continue
        was_active = contract["status"] == "ACTIVE"
        commit(contract, {"status": "EXPIRED"})
        expired_contracts += 1
        if was_active:
            for assignment in creation_order(calc.contract_assignments(contract["id"])):
                if assignment["status"] == "ACTIVE":
                    commit(assignment, {"status": "EXPIRED", "released_on": stamp})
                    expired_assignments += 1

    for assignment in creation_order(list(db.assignments.values())):
        if assignment["status"] != "ACTIVE":
            continue
        end = parse_date(assignment["end_date"])
        if end is not None and end <= current:
            commit(assignment, {"status": "EXPIRED", "released_on": stamp})
            expired_assignments += 1

    for cert in creation_order(list(db.certifications.values())):
        if cert["status"] != "VALID":
            continue
        expires = parse_date(cert["expires_on"])
        if expires is not None and expires <= current:
            commit(cert, {"status": "EXPIRED"})
            expired_certifications += 1

    recomputed = 0
    for agency in creation_order(list(db.agencies.values())):
        incidents = calc.agency_incidents(agency["id"])
        if any(i["status"] == "CONFIRMED" for i in incidents):
            recompute_risk(agency)
            recomputed += 1

    return {
        "current_utc": now_iso(),
        "expired_contract_count": expired_contracts,
        "expired_assignment_count": expired_assignments,
        "expired_certification_count": expired_certifications,
        "risk_recomputed_agency_count": recomputed,
    }
