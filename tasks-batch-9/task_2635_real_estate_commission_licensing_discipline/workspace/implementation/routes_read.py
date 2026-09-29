"""Every GET endpoint (27 of them)."""
from flask import Blueprint, request

import computed
import envelope
import serialize
import shape
import store
from authz import guard

bp = Blueprint("reads", __name__)

STAFF_ALL = ["LicensingAnalyst", "TrustAuditor", "CommissionCounsel",
             "HearingPanelChair", "RecoveryFundTrustee"]


def _matches(row, kind, spec):
    for param, field in spec.items():
        wanted = request.args.get(param)
        if wanted is None or str(wanted).strip() == "":
            continue
        wanted = str(wanted).strip()
        if field == "supervision_posture":
            actual = computed.supervision_posture(row)
        elif field == "normalized_name":
            actual = row.get("normalized_name")
            if actual == computed.normalize_name(wanted):
                continue
        else:
            actual = row.get(field)
        if actual is None or str(actual) != wanted:
            return False
    return True


def _listing(kind, spec, rows=None):
    limit, offset = shape.paging()
    source = rows if rows is not None else store.all_rows(kind)
    picked = [r for r in source if _matches(r, kind, spec)]
    window = picked[offset:offset + limit]
    return envelope.collection([serialize.project(kind, r) for r in window],
                               limit, offset, len(picked))


# ------------------------------------------------------------------ licensees
@bp.get("/commission/licensees/<lid>")
def get_licensee(lid):
    guard(["LicensingAnalyst", "TrustAuditor", "CommissionCounsel", "HearingPanelChair",
           "RecoveryFundTrustee", "Broker", "Salesperson", "Respondent", "ProviderAdmin"])
    return envelope.ok(serialize.licensee(computed.must("licensee", lid)))


@bp.get("/commission/licensees")
def list_licensees():
    guard(["LicensingAnalyst", "TrustAuditor", "CommissionCounsel", "HearingPanelChair",
           "RecoveryFundTrustee", "Broker", "ProviderAdmin"])
    return _listing("licensee", {
        "sponsoring_brokerage_id": "sponsoring_brokerage_id",
        "supervising_broker_id": "supervising_broker_id",
        "license_status": "license_status",
        "discipline_status": "discipline_status",
        "person_type": "person_type",
    })


# ----------------------------------------------------------------- brokerages
@bp.get("/commission/brokerages/<bid>")
def get_brokerage(bid):
    guard(["LicensingAnalyst", "TrustAuditor", "CommissionCounsel", "HearingPanelChair",
           "Broker", "Salesperson"])
    return envelope.ok(serialize.brokerage(computed.must("brokerage", bid)))


@bp.get("/commission/brokerages")
def list_brokerages():
    guard(["LicensingAnalyst", "TrustAuditor", "CommissionCounsel", "HearingPanelChair",
           "Broker"])
    return _listing("brokerage", {
        "designated_broker_id": "designated_broker_id",
        "status": "status",
        "supervision_posture": "supervision_posture",
    })


# ------------------------------------------------------------- trust accounts
TRUST_ROLES = ["LicensingAnalyst", "TrustAuditor", "CommissionCounsel", "Broker"]


@bp.get("/commission/trust-accounts/<aid>")
def get_trust_account(aid):
    guard(TRUST_ROLES)
    return envelope.ok(serialize.trust_account(computed.must("trust_account", aid)))


@bp.get("/commission/trust-accounts")
def list_trust_accounts():
    guard(TRUST_ROLES)
    return _listing("trust_account", {
        "brokerage_id": "brokerage_id",
        "status": "status",
        "account_type": "account_type",
    })


@bp.get("/commission/trust-accounts/<aid>/ledger-entries")
def list_ledger_entries(aid):
    guard(TRUST_ROLES)
    account = computed.must("trust_account", aid)
    rows = computed.rows_where("ledger_entry", trust_account_id=account["id"])
    return _listing("ledger_entry", {"entry_type": "entry_type"}, rows)


@bp.get("/commission/trust-audits/<aid>")
def get_trust_audit(aid):
    guard(TRUST_ROLES)
    return envelope.ok(serialize.trust_audit(computed.must("trust_audit", aid)))


@bp.get("/commission/trust-audits")
def list_trust_audits():
    guard(TRUST_ROLES)
    return _listing("trust_audit", {
        "trust_account_id": "trust_account_id",
        "auditor_user_id": "auditor_user_id",
        "status": "status",
        "basis": "basis",
    })


# ----------------------------------------------------------------- complaints
@bp.get("/commission/complaints/<cid>")
def get_complaint(cid):
    guard(["LicensingAnalyst", "TrustAuditor", "CommissionCounsel", "HearingPanelChair",
           "Respondent", "Public"])
    return envelope.ok(serialize.complaint(computed.must("complaint", cid)))


@bp.get("/commission/complaints")
def list_complaints():
    guard(["LicensingAnalyst", "TrustAuditor", "CommissionCounsel", "HearingPanelChair"])
    return _listing("complaint", {
        "respondent_licensee_id": "respondent_licensee_id",
        "respondent_brokerage_id": "respondent_brokerage_id",
        "source_audit_id": "source_audit_id",
        "status": "status",
        "allegation_type": "allegation_type",
    })


CASE_ROLES = ["LicensingAnalyst", "CommissionCounsel", "HearingPanelChair", "Respondent"]


@bp.get("/commission/complaints/<cid>/consent-agreements")
def list_consent_agreements(cid):
    guard(CASE_ROLES)
    complaint = computed.must("complaint", cid)
    rows = computed.rows_where("consent_agreement", complaint_id=complaint["id"])
    return _listing("consent_agreement", {"status": "status"}, rows)


@bp.get("/commission/complaints/<cid>/hearings")
def list_hearings(cid):
    guard(CASE_ROLES)
    complaint = computed.must("complaint", cid)
    rows = computed.rows_where("hearing", complaint_id=complaint["id"])
    return _listing("hearing", {"status": "status"}, rows)


@bp.get("/commission/consent-agreements/<aid>")
def get_consent_agreement(aid):
    guard(CASE_ROLES)
    return envelope.ok(serialize.consent_agreement(
        computed.must("consent_agreement", aid)))


@bp.get("/commission/hearings/<hid>")
def get_hearing(hid):
    guard(CASE_ROLES)
    return envelope.ok(serialize.hearing(computed.must("hearing", hid)))


# ------------------------------------------------------------ sanction orders
@bp.get("/commission/sanction-orders/<oid>")
def get_sanction_order(oid):
    guard(["LicensingAnalyst", "CommissionCounsel", "HearingPanelChair",
           "RecoveryFundTrustee", "Respondent", "Public"])
    return envelope.ok(serialize.sanction_order(computed.must("sanction_order", oid)))


@bp.get("/commission/sanction-orders")
def list_sanction_orders():
    guard(["LicensingAnalyst", "CommissionCounsel", "HearingPanelChair",
           "RecoveryFundTrustee"])
    return _listing("sanction_order", {
        "complaint_id": "complaint_id",
        "respondent_licensee_id": "respondent_licensee_id",
        "consent_agreement_id": "consent_agreement_id",
        "hearing_id": "hearing_id",
        "status": "status",
        "sanction_type": "sanction_type",
    })


@bp.get("/commission/sanction-orders/<oid>/recovery-claims")
def list_recovery_claims(oid):
    guard(["LicensingAnalyst", "CommissionCounsel", "RecoveryFundTrustee", "Public"])
    order = computed.must("sanction_order", oid)
    rows = computed.rows_where("recovery_claim", sanction_order_id=order["id"])
    return _listing("recovery_claim", {"status": "status"}, rows)


@bp.get("/commission/recovery-fund")
def get_recovery_fund():
    guard(["LicensingAnalyst", "CommissionCounsel", "RecoveryFundTrustee", "Public"])
    return envelope.ok(serialize.recovery_fund(store.fund()))


# ------------------------------------------------------------------ education
PROVIDER_ROLES = ["LicensingAnalyst", "CommissionCounsel", "ProviderAdmin"]


@bp.get("/commission/education-providers/<pid>")
def get_provider(pid):
    guard(PROVIDER_ROLES)
    return envelope.ok(serialize.education_provider(
        computed.must("education_provider", pid)))


@bp.get("/commission/education-providers")
def list_providers():
    guard(PROVIDER_ROLES)
    return _listing("education_provider", {"status": "status"})


@bp.get("/commission/instructors/<iid>")
def get_instructor(iid):
    guard(PROVIDER_ROLES)
    return envelope.ok(serialize.instructor(computed.must("instructor", iid)))


@bp.get("/commission/instructors")
def list_instructors():
    guard(PROVIDER_ROLES)
    return _listing("instructor", {
        "education_provider_id": "education_provider_id",
        "licensee_id": "licensee_id",
        "status": "status",
        "credential_type": "credential_type",
    })


COMPLETION_ROLES = ["LicensingAnalyst", "CommissionCounsel", "ProviderAdmin",
                    "Broker", "Salesperson"]


@bp.get("/commission/course-completions/<cid>")
def get_completion(cid):
    guard(COMPLETION_ROLES)
    return envelope.ok(serialize.course_completion(
        computed.must("course_completion", cid)))


@bp.get("/commission/course-completions")
def list_completions():
    guard(COMPLETION_ROLES)
    return _listing("course_completion", {
        "licensee_id": "licensee_id",
        "instructor_id": "instructor_id",
        "education_provider_id": "education_provider_id",
        "credit_status": "credit_status",
        "course_type": "course_type",
    })


# ---------------------------------------------------------------- advertising
@bp.get("/commission/advertising-names/<aid>")
def get_advertising_name(aid):
    guard(["LicensingAnalyst", "CommissionCounsel", "Broker", "Salesperson", "Public"])
    return envelope.ok(serialize.advertising_name(
        computed.must("advertising_name", aid)))


@bp.get("/commission/advertising-names")
def list_advertising_names():
    guard(["LicensingAnalyst", "CommissionCounsel", "Broker", "Public"])
    return _listing("advertising_name", {
        "brokerage_id": "brokerage_id",
        "team_lead_licensee_id": "team_lead_licensee_id",
        "status": "status",
        "kind": "kind",
        "normalized_name": "normalized_name",
    })
