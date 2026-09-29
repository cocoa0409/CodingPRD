"""The normative same-request cascades (PRD 2.8, 3.2, 3.5, 3.7, 3.9)."""
from datetime import timedelta

import computed
import store


# ----------------------------------------------------------- posture plumbing
def posture_snapshot(*brokerage_ids):
    snap = {}
    for bid in brokerage_ids:
        if bid and bid not in snap:
            snap[bid] = computed.posture_of(bid)
    return snap


def add_snapshot(snap, brokerage_id):
    if brokerage_id and brokerage_id not in snap:
        snap[brokerage_id] = computed.posture_of(brokerage_id)
    return snap


def settle(snap):
    """Recompute (touch) each brokerage; auto-reject names on entering
    RESTRICTED / FROZEN."""
    for bid, prev in list(snap.items()):
        firm = store.get("brokerage", bid)
        if firm is None:
            continue
        store.touch(firm)
        current = computed.supervision_posture(firm)
        if (current in ("RESTRICTED", "FROZEN")
                and prev not in ("RESTRICTED", "FROZEN")):
            reject_submitted_names(bid)


def reject_submitted_names(brokerage_id):
    for row in computed.rows_where("advertising_name", brokerage_id=brokerage_id):
        if row["status"] == "SUBMITTED":
            row["status"] = "REJECTED"
            row["rejection_reason"] = "POSTURE_RESTRICTED"
            store.touch(row)


def revoke_team_names(licensee_id):
    """A team lead who transfers away or loses ACTIVE standing (PRD 3.12)."""
    for row in store.all_rows("advertising_name"):
        if (row["kind"] == "TEAM" and row["team_lead_licensee_id"] == licensee_id
                and row["status"] == "APPROVED"):
            row["status"] = "REVOKED"
            row["rejection_reason"] = "TEAM_LEAD_INELIGIBLE"
            # PRD 3.12: the system revocation happens "again with no
            # `reviewed_by_user_id`" -- "the absence of a reviewer is the audit
            # trail's way of showing no human made that call". The row was
            # APPROVED by an analyst, so the approver's id has to be cleared
            # for the revoked row to show no reviewer. Only this system cascade
            # clears it; the analyst's manual REVOKE keeps recording its own.
            row["reviewed_by_user_id"] = None
            store.touch(row)


# ------------------------------------------------------------------ discipline
def open_investigation(licensee):
    if licensee is None:
        return
    if licensee["discipline_status"] in ("NONE", "CLEARED"):
        licensee["discipline_status"] = "UNDER_INVESTIGATION"
        store.touch(licensee)


def clear_discipline(licensee, *, from_states=("UNDER_INVESTIGATION", "PENDING_HEARING")):
    """CLEARED only when no other open complaint remains against them."""
    if licensee is None:
        return
    if licensee["discipline_status"] not in from_states:
        return
    for row in store.all_rows("complaint"):
        if (row["respondent_licensee_id"] == licensee["id"]
                and row["status"] in computed.OPEN_COMPLAINT_STATUSES):
            return
    licensee["discipline_status"] = "CLEARED"
    store.touch(licensee)


# ---------------------------------------------------- education-side cascades
def invalidate_recent_completions(instructor_id):
    cutoff = store.now().date() - timedelta(days=365)
    stamp = store.fmt_dt(store.now())
    for row in computed.rows_where("course_completion", instructor_id=instructor_id):
        if row["credit_status"] != "VALID":
            continue
        if store.date_of(row["completed_on"]) >= cutoff:
            row["credit_status"] = "INVALIDATED"
            row["invalidated_at"] = stamp


def suspend_instructors_of_licensee(licensee_id):
    """CASCADE L3 -> L4 -> L5 of PRD 3.5."""
    hit = False
    for row in computed.rows_where("instructor", licensee_id=licensee_id):
        if row["status"] in ("PENDING", "APPROVED"):
            row["status"] = "SUSPENDED"
            row["suspended_reason"] = "LICENSE_REVOKED"
            store.touch(row)
            invalidate_recent_completions(row["id"])
            hit = True
    if hit:
        demote_providers_with_suspended_instructors()


def demote_providers_with_suspended_instructors():
    for provider in store.all_rows("education_provider"):
        if (provider["status"] == "APPROVED"
                and computed.suspended_instructor_count(provider["id"]) >= 1):
            provider["status"] = "PROBATION"
            store.touch(provider)


# ------------------------------------------------------- licence consequences
def suspend_licensee(licensee, ends_at, order_id):
    licensee["license_status"] = "SUSPENDED"
    licensee["suspension_ends_at"] = store.fmt_dt(ends_at)
    licensee["_suspension_order_id"] = order_id
    store.touch(licensee)
    revoke_team_names(licensee["id"])


def revoke_licensee(licensee):
    licensee["license_status"] = "REVOKED"
    licensee["sponsoring_brokerage_id"] = None
    licensee["supervising_broker_id"] = None
    licensee["suspension_ends_at"] = None
    licensee["_suspension_order_id"] = None
    store.touch(licensee)
    revoke_team_names(licensee["id"])


def firm_cascade_for_sanction(licensee_id, revocation, snap):
    """PRD 3.2: suspend the firm this licensee designates, then maybe close it."""
    for firm in computed.rows_where("brokerage", designated_broker_id=licensee_id):
        add_snapshot(snap, firm["id"])
        if firm["status"] == "ACTIVE":
            firm["status"] = "SUSPENDED"
            store.touch(firm)
            reject_submitted_names(firm["id"])
        if (revocation and firm["status"] == "SUSPENDED"
                and computed.affiliated_licensee_count(firm["id"]) == 0):
            firm["status"] = "CLOSED"
            store.touch(firm)
            for account in computed.rows_where("trust_account", brokerage_id=firm["id"]):
                if account["status"] != "CLOSED" and computed.account_triple(account)[2] == 0:
                    account["status"] = "CLOSED"
                    store.touch(account)


def apply_order_consequences(order, snap):
    """Licence consequence + firm cascade for a freshly issued order."""
    licensee = store.get("licensee", order["respondent_licensee_id"])
    if licensee is None:
        return
    add_snapshot(snap, licensee.get("sponsoring_brokerage_id"))
    sanction = order["sanction_type"]
    if sanction == "SUSPENSION":
        if licensee["license_status"] == "ACTIVE":
            ends = store.dt_of(order["effective_at"]) + timedelta(
                seconds=order["suspension_days"] * 86400)
            suspend_licensee(licensee, ends, order["id"])
        firm_cascade_for_sanction(licensee["id"], False, snap)
    elif sanction == "REVOCATION":
        if licensee["license_status"] != "REVOKED":
            revoke_licensee(licensee)
        firm_cascade_for_sanction(licensee["id"], True, snap)
        suspend_instructors_of_licensee(licensee["id"])


def issue_sanction_order(complaint, source, sanction_type, fine_cents,
                         suspension_days, consent_agreement_id=None, hearing_id=None):
    moment = store.now()
    fine_due = None
    if fine_cents > 0:
        fine_due = store.fmt_dt(moment + timedelta(seconds=FINE_DUE_SECONDS))
    order = store.insert("sanction_order", {
        "complaint_id": complaint["id"],
        "respondent_licensee_id": complaint["respondent_licensee_id"],
        "consent_agreement_id": consent_agreement_id,
        "hearing_id": hearing_id,
        "source": source,
        "sanction_type": sanction_type,
        "fine_cents": fine_cents,
        "suspension_days": suspension_days,
        "effective_at": store.fmt_dt(moment),
        "fine_due_at": fine_due,
        "fine_paid_cents": 0,
        "fund_credited_cents": 0,
        "status": "ISSUED",
        "vacated_at": None,
    })
    snap = posture_snapshot(complaint.get("respondent_brokerage_id"))
    complaint["status"] = "ADJUDICATED"
    store.touch(complaint)
    respondent = store.get("licensee", complaint["respondent_licensee_id"])
    if respondent is not None:
        add_snapshot(snap, respondent.get("sponsoring_brokerage_id"))
        respondent["discipline_status"] = "SANCTIONED"
        store.touch(respondent)
    apply_order_consequences(order, snap)
    settle(snap)
    return order


FINE_DUE_SECONDS = computed.FINE_DUE_DAYS * 86400


# ------------------------------------------------------------- audit cascades
def remediation_cascade(audit, remediation_days, snap):
    """FINDINGS_ISSUED -> REMEDIATION_ORDERED, 4 normative layers."""
    days = remediation_days if remediation_days is not None else computed.DEFAULT_REMEDIATION_DAYS
    audit["status"] = "REMEDIATION_ORDERED"
    audit["remediation_round"] = 1
    audit["remediation_due_at"] = store.fmt_dt(
        store.now() + timedelta(seconds=days * 86400))
    store.touch(audit)
    account = store.get("trust_account", audit["trust_account_id"])
    if account is not None and account["status"] == "OPEN":
        account["status"] = "RESTRICTED"
        store.touch(account)
    settle(snap)


def release_account_if_clean(audit, require_no_other_audit=True):
    account = store.get("trust_account", audit["trust_account_id"])
    if account is None or account["status"] != "RESTRICTED":
        return
    if computed.account_triple(account)[2] != 0:
        return
    if require_no_other_audit:
        for other in computed.rows_where("trust_audit", trust_account_id=account["id"]):
            if other["id"] == audit["id"]:
                continue
            if other["status"] in ("REMEDIATION_ORDERED", "ESCALATED"):
                return
    account["status"] = "OPEN"
    store.touch(account)


def escalate_audit(audit, investigator_user_id, snap):
    """REMEDIATION_ORDERED -> ESCALATED with CASCADE L2/L3/L4."""
    audit["status"] = "ESCALATED"
    store.touch(audit)
    account = store.get("trust_account", audit["trust_account_id"])
    firm = store.get("brokerage", account["brokerage_id"]) if account else None
    respondent_id = firm.get("designated_broker_id") if firm else None
    loss = audit.get("verified_shortage_cents")
    if loss is None:
        loss = audit.get("computed_shortage_cents") or 0
    moment = store.now()
    complaint = store.insert("complaint", {
        "case_number": store.next_case_number(),
        "complainant_name": "Trust Audit Escalation",
        "respondent_licensee_id": respondent_id,
        "respondent_brokerage_id": firm["id"] if firm else None,
        "source_audit_id": audit["id"],
        "allegation_type": "TRUST_SHORTAGE",
        "alleged_loss_cents": loss,
        "filed_at": store.fmt_dt(moment),
        "statute_deadline_at": store.fmt_dt(
            moment + timedelta(seconds=computed.STATUTE_DAYS * 86400)),
        "status": "INVESTIGATION",
        "screener_user_id": None,
        "investigator_user_id": investigator_user_id,
        "amendment_count": 0,
    })
    if firm is not None:
        add_snapshot(snap, firm["id"])
    open_investigation(store.get("licensee", respondent_id))
    return complaint
