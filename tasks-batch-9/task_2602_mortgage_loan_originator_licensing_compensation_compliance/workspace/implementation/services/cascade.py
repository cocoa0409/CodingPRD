"""The two five-hop cascades and the nightly compliance sweep (PRD 2.11, 3.1,
3.7, 3.9)."""
from datetime import datetime, timezone

from db import create, db, sort_key, touch
from services import audit, authority, calc

EPOCH = datetime(1, 1, 1, tzinfo=timezone.utc)


def loan_order_key(loan):
    """Loans are always processed by funded_at ASC then created_at ASC."""
    return (loan["funded_at"] or EPOCH, loan["created_at"], loan["_seq"])


def license_order_key(lic):
    """Licences are always processed by expiration_date ASC then created_at ASC."""
    return (lic["expiration_date"], lic["created_at"], lic["_seq"])


# =============================================================================
# The authority-lapse cascade
# =============================================================================
def authority_lapse(lic, full=True, system=False, detail=None):
    """Run the authority-lapse chain for a licence that has just stopped
    authorising. `full` is False for surrender, which only closes sponsorship
    and recomputes authority (hops 1-2).

    hop 1  the licence's ACTIVE sponsorship moves to RELINQUISHED
    hop 2  the licence's denormalised sponsorship fields go null and
           authorized_state_codes is recomputed (it is derived, so it needs no
           write of its own)
    hop 3  the originator's TAKEN/LOCKED loans in that state are SUSPENDED
    hop 4  one CASCADE investigation per suspended loan
    hop 5  open_investigation_count is recomputed (also derived)
    """
    result = {
        "relinquished_sponsorship_ids": [],
        "suspended_loan_ids": [],
        "opened_investigation_ids": [],
    }

    # hop 1
    transfer = authority.active_transfer(lic["id"])
    if transfer is not None:
        transfer["status"] = "RELINQUISHED"
        transfer["relinquished_at"] = db.clock
        touch(transfer)
        result["relinquished_sponsorship_ids"].append(transfer["id"])

    # hop 2
    lic["active_sponsoring_institution_code"] = None
    lic["active_sponsorship_effective_at"] = None
    touch(lic)

    opened = []
    if full:
        # hop 3
        loans = [l for l in db.loan_applications.values()
                 if l["originator_id"] == lic["originator_id"]
                 and l["state_code"] == lic["state_code"]
                 and l["status"] in ("TAKEN", "LOCKED")]
        loans.sort(key=loan_order_key)
        for loan in loans:
            loan["authority_flag"] = "SUSPENDED"
            touch(loan)
            result["suspended_loan_ids"].append(loan["id"])
        # hop 4
        for loan in loans:
            investigation = create(db.investigations, {
                "originator_id": loan["originator_id"],
                "loan_application_id": loan["id"],
                "opened_by": "CASCADE",
                "detected_at": db.clock,
                "trigger_reason": "AUTHORITY_LAPSE",
                "status": "OPEN",
                "finding_by_user_id": None,
                "restitution_cents": 0,
                "remediated_at": None,
            })
            opened.append(investigation)
            result["opened_investigation_ids"].append(investigation["id"])
        # hop 5 - open_investigation_count is derived from the investigation set.

    # The trail reads as the causal chain: the licence entry, then one
    # investigation entry per created investigation.
    audit.append("LicenseRegistration", lic["id"], "LICENSE_STATUS_CHANGED",
                 detail or {"status": lic["status"]}, system=system)
    for investigation in opened:
        audit.append("UnlicensedActivityInvestigation", investigation["id"],
                     "INVESTIGATION_OPENED",
                     {"trigger_reason": "AUTHORITY_LAPSE",
                      "opened_by": "CASCADE",
                      "loan_application_id": investigation["loan_application_id"]},
                     system=True)
    return result


# =============================================================================
# The early-payoff clawback cascade
# =============================================================================
def payoff_clawback(loan, payoff_date):
    """Runs after the loan has advanced CLOSED -> PAID_OFF.

    hop 1  compensation_status RECONCILED -> CLAWED_BACK
    hop 2  the FINAL ledger line RECONCILED -> CLAWED_BACK, writing days_held,
           recapture_pct and clawback_cents
    hop 3  the originator's ledger totals are recomputed (derived)
    hop 4  exposure_score recomputed; monitoring_status may flip to ELEVATED
    hop 5  every SUBMITTED pricing exception of this originator now requires a
           second approver - only when hop 4 actually changed monitoring_status
    """
    record = None
    for row in db.compensation_records.values():
        if (row["loan_application_id"] == loan["id"]
                and row["variant"] == "FINAL"
                and row["status"] == "RECONCILED"):
            record = row
            break
    if record is None:
        # An ACCRUED line has paid_cents 0; nothing is recaptured and the loan's
        # compensation_status stays exactly where it was.
        return

    days_held = calc.days_held_between(loan["funded_at"], payoff_date)
    recapture_pct = calc.recapture_pct_for(days_held)
    record["days_held"] = days_held
    record["recapture_pct"] = recapture_pct
    touch(record)
    if recapture_pct <= 0:
        return

    # hop 1
    loan["compensation_status"] = "CLAWED_BACK"
    touch(loan)
    # hop 2
    record["clawback_cents"] = calc.clawback_cents_for(record["paid_cents"], recapture_pct)
    record["status"] = "CLAWED_BACK"
    # hop 3 - lifetime_clawed_back_cents / net_compensation_cents are derived.
    originator = db.originators[loan["originator_id"]]
    touch(originator)
    # hop 4
    escalated = calc.recompute_exposure(originator)
    audit.append("CompensationRecord", record["id"], "COMP_CLAWED_BACK",
                 {"loan_application_id": loan["id"],
                  "days_held": days_held,
                  "recapture_pct": recapture_pct,
                  "clawback_cents": record["clawback_cents"]},
                 system=True)
    if escalated:
        # hop 5
        exceptions = [e for e in db.pricing_exceptions.values()
                      if e["status"] == "SUBMITTED"
                      and e["loan_application_id"] in db.loan_applications
                      and db.loan_applications[e["loan_application_id"]]["originator_id"]
                      == originator["id"]]
        exceptions.sort(key=sort_key)
        for exception in exceptions:
            if not exception["requires_second_approval"]:
                exception["requires_second_approval"] = True
                touch(exception)
        audit.append("Originator", originator["id"], "MONITORING_ESCALATED",
                     {"exposure_score": originator["exposure_score"],
                      "monitoring_status": originator["monitoring_status"]},
                     system=True)


# =============================================================================
# The nightly compliance sweep
# =============================================================================
def daily_license_sweep():
    result = {
        "swept_at": db.clock,
        "expired_license_ids": [],
        "relinquished_sponsorship_ids": [],
        "suspended_loan_ids": [],
        "opened_investigation_ids": [],
        "escalated_inquiry_ids": [],
        "unassigned_originator_ids": [],
    }

    # 1 - licence expiry, each running the full five-hop cascade.
    expiring = [l for l in db.license_registrations.values()
                if l["status"] in ("ACTIVE", "RENEWAL_PENDING")
                and l["expiration_date"] <= db.clock]
    expiring.sort(key=license_order_key)
    for lic in expiring:
        lic["status"] = "EXPIRED"
        touch(lic)
        result["expired_license_ids"].append(lic["id"])
        hops = authority_lapse(lic, full=True, system=True,
                               detail={"status": "EXPIRED", "reason": "SWEEP_EXPIRY"})
        result["relinquished_sponsorship_ids"].extend(hops["relinquished_sponsorship_ids"])
        result["suspended_loan_ids"].extend(hops["suspended_loan_ids"])
        result["opened_investigation_ids"].extend(hops["opened_investigation_ids"])

    # 2 - lapsed plan assignments.
    plans = [p for p in db.compensation_plans.values()
             if p["assignment_effective_to"] is not None
             and p["assignment_effective_to"] < db.clock]
    plans.sort(key=sort_key)
    for plan in plans:
        originator_id = plan["assigned_originator_id"]
        if originator_id is None:
            continue
        originator = db.originators.get(originator_id)
        if originator is None:
            continue
        if originator["compensation_plan_id"] != plan["id"]:
            continue
        originator["compensation_plan_id"] = None
        touch(originator)
        if originator_id not in result["unassigned_originator_ids"]:
            result["unassigned_originator_ids"].append(originator_id)

    # 3 - examination inquiries past their deadline.
    inquiries = [i for i in db.examination_inquiries.values()
                 if i["status"] in ("OPEN", "INFO_REQUESTED")
                 and i["response_due_at"] < db.clock]
    inquiries.sort(key=sort_key)
    for inquiry in inquiries:
        inquiry["status"] = "ESCALATED"
        inquiry["escalation_reason"] = "DEADLINE_MISSED"
        touch(inquiry)
        result["escalated_inquiry_ids"].append(inquiry["id"])

    return result
