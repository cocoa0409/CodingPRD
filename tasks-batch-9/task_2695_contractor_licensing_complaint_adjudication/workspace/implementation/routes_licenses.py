"""Licences: reads, CE banking, renewal, reinstatement, recovery repayment
and the ops-run compliance sweep.
"""

from flask import Blueprint, g

import calc
from core import (
    add_days,
    add_months,
    clock_date,
    err,
    fmt_date,
    get_body,
    ok,
    qfilter,
    render_list,
    require_auth,
    setf,
    touch,
    v_date,
    v_int,
    v_money,
    v_num,
    v_str,
)
import domain
from domain import D, find, must, rows

bp = Blueprint("licenses", __name__)

READ_ROLES = ["BoardAdmin", "LicensingAnalyst", "Investigator", "HearingOfficer",
              "FundAdjudicator", "Licensee", "Consumer"]


def owner_check(lic):
    if g.role == "Licensee" and g.user_id != lic["licensee_id"]:
        err("ERR_NOT_RESOURCE_OWNER", "the acting licensee does not hold this licence")


# ------------------------------------------------------------------- reads --
@bp.route("/licensing/licenses/<rid>", methods=["GET"])
def get_license(rid):
    require_auth(READ_ROLES)
    return ok(domain.ser_license(must("licenses", rid)))


@bp.route("/licensing/licenses", methods=["GET"])
def list_licenses():
    require_auth(READ_ROLES)
    items = rows("licenses")
    for field in ("licensee_id", "classification_id", "application_id",
                  "qualifying_individual_id", "predecessor_license_id", "status",
                  "compliance_posture"):
        items = qfilter(items, field)
    return render_list(items, domain.ser_license)


# -------------------------------------------------------------- ce credits --
@bp.route("/licensing/licenses/<rid>/ce-credits", methods=["POST"])
def bank_ce_credits(rid):
    require_auth(["Licensee", "LicensingAnalyst"])
    body = get_body()
    ce_hours = v_num(body, "ce_hours")
    completed_on = v_date(body, "completed_on")
    provider_name = v_str(body, "provider_name")

    lic = must("licenses", rid)
    owner_check(lic)
    if lic["status"] not in ("ACTIVE", "SUSPENDED", "EXPIRED"):
        err("ERR_LICENSE_STATE_INVALID", "this licence cannot bank continuing education")

    if ce_hours <= 0:
        err("ERR_CE_HOURS_CEILING_EXCEEDED", "ce_hours must be greater than zero")
    total = lic["ce_hours_completed"] + ce_hours
    if total > calc.CE_HOURS_TERM_CEILING:
        err("ERR_CE_HOURS_CEILING_EXCEEDED",
            "cumulative continuing-education hours may not exceed %d"
            % calc.CE_HOURS_TERM_CEILING)

    setf(lic, "ce_hours_completed", total)
    touch(lic)
    return ok(domain.ser_license(lic))


# ------------------------------------------------------------------ renewal --
@bp.route("/licensing/licenses/<rid>/renew", methods=["POST"])
def renew_license(rid):
    require_auth(["Licensee"])
    lic = must("licenses", rid)
    owner_check(lic)
    if lic["status"] not in ("ACTIVE", "EXPIRED"):
        err("ERR_LICENSE_STATE_INVALID", "only an ACTIVE or EXPIRED licence may renew")

    classification = find("trade_classifications", lic["classification_id"])
    today = clock_date()
    expires_on = D(lic["expires_on"])

    if domain.bond_gap_days(lic) != 0:
        err("ERR_COVERAGE_CONTINUITY_GAP",
            "bond coverage was not continuous over the expiring term")
    if lic["compliance_posture"] == "NON_COMPLIANT":
        err("ERR_LICENSE_NOT_COMPLIANT", "a NON_COMPLIANT licence may not renew")
    if today > add_days(expires_on, calc.DELINQUENT_GRACE_DAYS):
        err("ERR_RENEWAL_WINDOW_CLOSED", "the delinquent renewal grace period has closed")
    required = classification["required_ce_hours"]
    if lic["ce_hours_completed"] < required - calc.CE_SHORTFALL_GRACE_HOURS:
        err("ERR_CE_HOURS_INSUFFICIENT",
            "continuing-education hours fall more than %d hours short"
            % calc.CE_SHORTFALL_GRACE_HOURS)

    delinquent = today > expires_on
    fee = calc.renewal_fee(classification["renewal_base_fee_cents"], required,
                           lic["ce_hours_completed"], delinquent)

    if delinquent:
        new_expiry = add_months(today, calc.LICENSE_TERM_MONTHS)
    else:
        new_expiry = add_months(expires_on, calc.LICENSE_TERM_MONTHS)

    setf(lic, "status", "ACTIVE")
    setf(lic, "expires_on", fmt_date(new_expiry))
    setf(lic, "last_renewed_on", fmt_date(today))
    setf(lic, "renewal_count", lic["renewal_count"] + 1)
    setf(lic, "ce_hours_completed", 0)
    setf(lic, "last_renewal_fee_cents", fee)
    domain.recompute_posture(lic)
    touch(lic)

    payload = domain.ser_license(lic)
    payload["renewal_fee_cents"] = fee
    return ok(payload)


# ------------------------------------------------------------ reinstatement --
@bp.route("/licensing/licenses/<rid>/reinstate", methods=["POST"])
def reinstate_license(rid):
    require_auth(["LicensingAnalyst"])
    lic = must("licenses", rid)
    if lic["status"] != "SUSPENDED":
        err("ERR_LICENSE_STATE_INVALID", "only a SUSPENDED licence may be reinstated")

    classification = find("trade_classifications", lic["classification_id"])
    today = clock_date()

    if not domain.has_live_coverage(lic["id"], "BOND"):
        err("ERR_BOND_COVERAGE_MISSING", "no VERIFIED bond covers the clock date")
    if (domain.unpaid_penalty_exposure(lic["id"]) != 0
            or domain.license_outstanding_recovery(lic) != 0):
        err("ERR_OUTSTANDING_OBLIGATIONS", "penalties or recovery-fund money remain owed")
    if lic.get("suspension_until") is not None and today < D(lic["suspension_until"]):
        err("ERR_SUSPENSION_PERIOD_ACTIVE", "the suspension period has not yet run")
    if lic["ce_hours_completed"] < classification["required_ce_hours"]:
        err("ERR_CE_HOURS_INSUFFICIENT",
            "reinstatement requires the full continuing-education obligation")

    domain.reactivate_license(lic)
    setf(lic, "ce_hours_completed", 0)
    domain.recompute_posture(lic)
    touch(lic)
    return ok(domain.ser_license(lic))


# ------------------------------------------------------ recovery repayments --
@bp.route("/licensing/licenses/<rid>/recovery-repayments", methods=["POST"])
def credit_recovery_repayment(rid):
    require_auth(["Licensee"])
    body = get_body()
    repayment_amount_cents = v_money(body, "repayment_amount_cents")
    expected_license_version = v_int(body, "expected_license_version")

    lic = must("licenses", rid)
    owner_check(lic)

    if expected_license_version != lic["version"]:
        err("ERR_STALE_LICENSE_VERSION", "the presented licence version is stale")

    outstanding = domain.license_outstanding_recovery(lic)
    if lic["status"] == "SUSPENDED":
        pass
    elif lic["status"] == "ACTIVE" and outstanding > 0:
        pass
    else:
        err("ERR_LICENSE_STATE_INVALID",
            "this licence cannot accept a recovery repayment")

    if repayment_amount_cents < 1 or repayment_amount_cents > outstanding:
        err("ERR_REPAYMENT_EXCEEDS_OUTSTANDING",
            "the credit must be between one cent and the outstanding balance")

    remaining = repayment_amount_cents
    claims = [c for c in domain.license_claims(lic["id"]) if c["status"] == "PAID"]
    claims.sort(key=lambda c: (c["created_at"], c["_seq"]))
    for claim in claims:
        if remaining <= 0:
            break
        room = claim["paid_amount_cents"] - claim["repaid_amount_cents"]
        if room <= 0:
            continue
        applied = min(room, remaining)
        setf(claim, "repaid_amount_cents", claim["repaid_amount_cents"] + applied)
        remaining -= applied
        if claim["repaid_amount_cents"] >= claim["paid_amount_cents"]:
            setf(claim, "status", "REIMBURSED")
        touch(claim)
        touch(find("recovery_fund_accounts", claim["fund_account_id"]))

    touch(find("licensees", lic["licensee_id"]))

    if (domain.license_outstanding_recovery(lic) == 0
            and lic.get("suspension_reason") == "RECOVERY_FUND_PAYOUT"
            and lic["status"] == "SUSPENDED"):
        domain.reactivate_license(lic)

    domain.recompute_posture(lic)
    touch(lic)
    return ok(domain.ser_license(lic))


# ------------------------------------------------------- compliance sweeps ---
@bp.route("/licensing/compliance-sweeps", methods=["POST"])
def compliance_sweep():
    require_auth(["BoardAdmin", "LicensingAnalyst"])
    today = clock_date()
    affected = {}

    lapsed = 0
    for record in rows("coverage_records"):
        if record["status"] != "VERIFIED":
            continue
        if today >= D(record["expiration_date"]):
            setf(record, "status", "LAPSED")
            touch(record)
            lapsed += 1
            lic = find("licenses", record["license_id"])
            if lic is not None:
                affected[lic["id"]] = lic

    expired = 0
    for lic in rows("licenses"):
        if lic["status"] == "ACTIVE" and today > D(lic["expires_on"]):
            setf(lic, "status", "EXPIRED")
            expired += 1
            affected[lic["id"]] = lic

    suspended = 0
    for lic in rows("licenses"):
        if lic["status"] != "ACTIVE":
            continue
        if not domain.has_live_coverage(lic["id"], "BOND"):
            domain.suspend_license(lic, "BOND_LAPSE", None)
            suspended += 1
            affected[lic["id"]] = lic

    for lic in affected.values():
        domain.recompute_posture(lic)

    return ok({
        "lapsed_coverage_count": lapsed,
        "expired_license_count": expired,
        "suspended_license_count": suspended,
        "swept_on": fmt_date(today),
    })
