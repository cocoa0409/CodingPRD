"""Trust ledger, audits and the compliance sweep."""
from datetime import timedelta

from flask import Blueprint

import cascades
import computed
import envelope
import serialize
import shape
import store
from authz import guard
from errors import fail, invalid

bp = Blueprint("trust", __name__)


# --------------------------------------------------------------- ledger append
@bp.post("/commission/trust-accounts/<aid>/ledger-entries")
def append_ledger_entry(aid):
    guard(["Broker", "LicensingAnalyst"])
    data = shape.body()
    entry_type = shape.req_enum(data, "entry_type", computed.ENTRY_TYPES)
    amount_cents = shape.req_int(data, "amount_cents", minimum=1)
    effective_date = shape.req_date(data, "effective_date")
    cleared_date = shape.opt_date(data, "cleared_date")
    transaction_reference = shape.req_str(data, "transaction_reference")
    memo = shape.opt_str(data, "memo")
    expected_version = shape.req_int(data, "expected_trust_account_version")

    account = computed.must("trust_account", aid)
    if account["status"] == "CLOSED":
        fail("ERR_TRUST_ACCOUNT_CLOSED", "A CLOSED trust account accepts nothing.")
    if account["status"] == "RESTRICTED" and entry_type == "DISBURSEMENT":
        fail("ERR_ACCOUNT_RESTRICTED_NO_DISBURSEMENT",
             "A RESTRICTED trust account may not disburse.")
    if account["version"] != expected_version:
        fail("ERR_TRUST_ACCOUNT_VERSION_CONFLICT",
             "Trust account version is %d." % account["version"])

    siblings = computed.rows_where("ledger_entry", trust_account_id=account["id"])
    if entry_type == "CORRECTION":
        target = any(e["entry_type"] == "DISBURSEMENT"
                     and e["transaction_reference"] == transaction_reference
                     for e in siblings)
        if not target:
            fail("ERR_CORRECTION_TARGET_NOT_FOUND",
                 "No DISBURSEMENT carries reference '%s'." % transaction_reference)
    for entry in siblings:
        if (entry["entry_type"] == entry_type
                and entry["transaction_reference"] == transaction_reference):
            fail("ERR_DUPLICATE_TRANSACTION_REFERENCE",
                 "Reference '%s' already exists for this entry class."
                 % transaction_reference)

    snap = cascades.posture_snapshot(account["brokerage_id"])
    row = store.insert("ledger_entry", {
        "trust_account_id": account["id"],
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "effective_date": store.fmt_date(effective_date),
        "cleared_date": store.fmt_date(cleared_date) if cleared_date else None,
        "transaction_reference": transaction_reference,
        "memo": memo,
    }, audited=False)
    store.touch(account)
    cascades.settle(snap)
    return envelope.created(serialize.ledger_entry(row))


# ------------------------------------------------------------ audit scheduling
@bp.post("/commission/trust-accounts/<aid>/audits")
def schedule_audit(aid):
    guard(["TrustAuditor", "LicensingAnalyst"])
    data = shape.body()
    auditor_user_id = shape.req_str(data, "auditor_user_id")
    basis = shape.req_enum(data, "basis", computed.BASES)
    as_of_date = shape.req_date(data, "as_of_date")
    start_at = shape.req_dt(data, "fieldwork_start_at")
    end_at = shape.req_dt(data, "fieldwork_end_at")

    account = computed.must("trust_account", aid)
    if account["status"] == "CLOSED":
        fail("ERR_TRUST_ACCOUNT_CLOSED",
             "A CLOSED trust account may not be audited.")

    overlapping = 0
    for other in store.all_rows("trust_audit"):
        if other["auditor_user_id"] != auditor_user_id:
            continue
        if other["status"] not in computed.ACTIVE_AUDIT_STATUSES:
            continue
        o_start = store.dt_of(other["fieldwork_start_at"])
        o_end = store.dt_of(other["fieldwork_end_at"])
        if start_at < o_end and o_start < end_at:
            overlapping += 1
    if overlapping >= computed.AUDITOR_WINDOW_CAPACITY:
        fail("ERR_AUDITOR_WINDOW_CAPACITY",
             "The auditor already has %d overlapping engagements." % overlapping)

    row = store.insert("trust_audit", {
        "trust_account_id": account["id"],
        "auditor_user_id": auditor_user_id,
        "basis": basis,
        "as_of_date": store.fmt_date(as_of_date),
        "fieldwork_start_at": store.fmt_dt(start_at),
        "fieldwork_end_at": store.fmt_dt(end_at),
        "status": "SCHEDULED",
        "bank_statement_balance_cents": None,
        "cleared_through_date": None,
        "computed_shortage_cents": None,
        "remediation_due_at": None,
        "remediation_round": 0,
        "verified_shortage_cents": None,
    })
    return envelope.created(serialize.trust_audit(row))


@bp.post("/commission/trust-audits/<aid>/fieldwork")
def start_fieldwork(aid):
    user_id, _ = guard(["TrustAuditor"])
    data = shape.body()
    bank_balance = shape.opt_int(data, "bank_statement_balance_cents")
    cleared_through = shape.opt_date(data, "cleared_through_date")

    audit = computed.must("trust_audit", aid)
    if user_id != audit["auditor_user_id"]:
        fail("ERR_AUDITOR_MISMATCH",
             "Only the assigned auditor may perform this fieldwork.")
    if audit["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE",
             "Fieldwork may only begin on a SCHEDULED audit.")
    if store.now() < store.dt_of(audit["fieldwork_start_at"]):
        fail("ERR_FIELDWORK_NOT_STARTED", "The fieldwork window has not opened.")
    if audit["basis"] == "BANK" and (bank_balance is None or cleared_through is None):
        invalid("A BANK-basis audit requires bank_statement_balance_cents "
                "and cleared_through_date.")

    if bank_balance is not None:
        audit["bank_statement_balance_cents"] = bank_balance
    if cleared_through is not None:
        audit["cleared_through_date"] = store.fmt_date(cleared_through)
    audit["status"] = "FIELDWORK"
    audit["computed_shortage_cents"] = computed.audit_shortage(audit)
    store.touch(audit)
    account = store.get("trust_account", audit["trust_account_id"])
    if account is not None:
        account["last_audited_at"] = store.fmt_dt(store.now())
        store.touch(account)
    return envelope.ok(serialize.trust_audit(audit))


AUDIT_ACTIONS = {"ISSUE_FINDINGS", "VERIFY_REMEDIATION", "ESCALATE", "CLOSE"}


@bp.post("/commission/trust-audits/<aid>/disposition")
def dispose_audit(aid):
    user_id, _ = guard(["TrustAuditor"])
    data = shape.body()
    action = shape.req_enum(data, "action", AUDIT_ACTIONS)
    remediation_days = shape.opt_int(data, "remediation_days", minimum=0)
    shape.opt_str(data, "note")

    audit = computed.must("trust_audit", aid)
    if user_id != audit["auditor_user_id"]:
        fail("ERR_AUDITOR_MISMATCH",
             "Only the assigned auditor may dispose of this audit.")
    account = store.get("trust_account", audit["trust_account_id"])
    brokerage_id = account["brokerage_id"] if account else None
    snap = cascades.posture_snapshot(brokerage_id)

    if action == "ISSUE_FINDINGS":
        if audit["status"] != "FIELDWORK" or audit["computed_shortage_cents"] is None:
            fail("ERR_INVALID_STATE",
                 "Findings may only be issued from FIELDWORK.")
        audit["status"] = "FINDINGS_ISSUED"
        store.touch(audit)
        if audit["computed_shortage_cents"] == 0:
            audit["verified_shortage_cents"] = 0
            audit["status"] = "CLOSED"
            store.touch(audit)
        else:
            cascades.remediation_cascade(audit, remediation_days, snap)
        return envelope.ok(serialize.trust_audit(audit))

    if action == "VERIFY_REMEDIATION":
        if audit["status"] != "REMEDIATION_ORDERED":
            fail("ERR_INVALID_STATE",
                 "Verification requires a REMEDIATION_ORDERED audit.")
        audit["status"] = "VERIFYING"
        audit["verified_shortage_cents"] = computed.audit_shortage(audit)
        store.touch(audit)
        if audit["verified_shortage_cents"] == 0:
            audit["status"] = "CLOSED"
            cascades.release_account_if_clean(audit, True)
        else:
            audit["status"] = "REMEDIATION_ORDERED"
            audit["remediation_round"] = audit["remediation_round"] + 1
            audit["remediation_due_at"] = store.fmt_dt(
                store.now() + timedelta(seconds=computed.DEFAULT_REMEDIATION_DAYS * 86400))
        store.touch(audit)
        cascades.settle(snap)
        return envelope.ok(serialize.trust_audit(audit))

    if action == "ESCALATE":
        if audit["status"] != "REMEDIATION_ORDERED":
            fail("ERR_INVALID_STATE",
                 "Escalation requires a REMEDIATION_ORDERED audit.")
        if audit["remediation_round"] < 2:
            fail("ERR_INVALID_STATE",
                 "A manual escalation requires remediation_round of at least 2.")
        cascades.escalate_audit(audit, audit["auditor_user_id"], snap)
        cascades.settle(snap)
        return envelope.ok(serialize.trust_audit(audit))

    if audit["status"] != "ESCALATED":
        fail("ERR_INVALID_STATE", "Closure requires an ESCALATED audit.")
    spawned = [c for c in store.all_rows("complaint")
               if c.get("source_audit_id") == audit["id"]]
    for complaint in spawned:
        if complaint["status"] not in ("ADJUDICATED", "DISMISSED", "CLOSED_NO_ACTION"):
            fail("ERR_INVALID_STATE",
                 "The escalated complaint is still open.")
    audit["verified_shortage_cents"] = computed.audit_shortage(audit)
    audit["status"] = "CLOSED"
    store.touch(audit)
    cascades.release_account_if_clean(audit, False)
    cascades.settle(snap)
    return envelope.ok(serialize.trust_audit(audit))


# ------------------------------------------------------------- compliance sweep
@bp.post("/commission/compliance-sweeps")
def compliance_sweep():
    guard(["LicensingAnalyst"])
    shape.body()
    moment = store.now()
    snap = {}
    expired = 0
    escalated = 0
    defaulted = 0
    restored = 0
    suspended_providers = 0

    # 1. expire licences
    for licensee in store.all_rows("licensee"):
        if licensee["license_status"] != "ACTIVE":
            continue
        expires = licensee.get("license_expires_at")
        if expires is None or store.dt_of(expires) > moment:
            continue
        cascades.add_snapshot(snap, licensee.get("sponsoring_brokerage_id"))
        licensee["license_status"] = "EXPIRED"
        licensee["inactive_since"] = store.fmt_dt(moment)
        licensee["sponsoring_brokerage_id"] = None
        licensee["supervising_broker_id"] = None
        store.touch(licensee)
        cascades.revoke_team_names(licensee["id"])
        expired += 1

    # 2. escalate overdue remediations
    for audit in store.all_rows("trust_audit"):
        if audit["status"] != "REMEDIATION_ORDERED":
            continue
        due = audit.get("remediation_due_at")
        if due is None or store.dt_of(due) >= moment:
            continue
        account = store.get("trust_account", audit["trust_account_id"])
        if account is not None:
            cascades.add_snapshot(snap, account["brokerage_id"])
        cascades.escalate_audit(audit, "SYSTEM_SWEEP", snap)
        escalated += 1

    # 3. default unpaid fines
    for order in store.all_rows("sanction_order"):
        if order["status"] != "ISSUED" or order["fine_cents"] <= 0:
            continue
        if order["fine_paid_cents"] >= order["fine_cents"]:
            continue
        due = order.get("fine_due_at")
        if due is None or store.dt_of(due) >= moment:
            continue
        order["status"] = "IN_DEFAULT"
        store.touch(order)
        defaulted += 1
        respondent = store.get("licensee", order["respondent_licensee_id"])
        if respondent is not None and respondent["license_status"] == "ACTIVE":
            cascades.add_snapshot(snap, respondent.get("sponsoring_brokerage_id"))
            cascades.suspend_licensee(
                respondent,
                moment + timedelta(seconds=computed.DEFAULT_SUSPENSION_DAYS * 86400),
                order["id"])

    # 4. restore served suspensions
    for licensee in store.all_rows("licensee"):
        if licensee["license_status"] != "SUSPENDED":
            continue
        ends = licensee.get("suspension_ends_at")
        if ends is None or store.dt_of(ends) > moment:
            continue
        driving = store.get("sanction_order", licensee.get("_suspension_order_id"))
        if driving is None or driving["status"] != "SATISFIED":
            continue
        cascades.add_snapshot(snap, licensee.get("sponsoring_brokerage_id"))
        licensee["license_status"] = "ACTIVE"
        licensee["suspension_ends_at"] = None
        licensee["_suspension_order_id"] = None
        store.touch(licensee)
        restored += 1

    # 5. suspend failing providers
    for provider in store.all_rows("education_provider"):
        if provider["status"] != "PROBATION":
            continue
        if computed.invalidated_credit_hours(provider["id"]) < computed.PROVIDER_SUSPEND_HOURS:
            continue
        provider["status"] = "SUSPENDED"
        store.touch(provider)
        suspended_providers += 1
        for instructor in computed.rows_where("instructor",
                                              education_provider_id=provider["id"]):
            if instructor["status"] in ("PENDING", "APPROVED"):
                instructor["status"] = "SUSPENDED"
                instructor["suspended_reason"] = "LICENSE_SUSPENDED"
                store.touch(instructor)

    cascades.settle(snap)
    return envelope.ok({
        "expired_licensee_count": expired,
        "escalated_audit_count": escalated,
        "defaulted_order_count": defaulted,
        "restored_licensee_count": restored,
        "suspended_provider_count": suspended_providers,
    })
