"""The consumer recovery fund: filing, adjudication and disbursement."""

from flask import Blueprint

import calc
from core import (
    add_days,
    clock_date,
    created,
    db,
    err,
    fmt_date,
    get_body,
    new_row,
    ok,
    qfilter,
    render_list,
    require_auth,
    setf,
    touch,
    v_date,
    v_enum,
    v_id,
    v_int,
    v_money,
    v_str,
)
import domain
from domain import D, find, must, rows

bp = Blueprint("fund", __name__)

CLAIM_READ_ROLES = ["BoardAdmin", "LicensingAnalyst", "FundAdjudicator", "Consumer",
                    "Licensee"]
JUDGMENT_BASES = ["FINAL_CITATION", "COURT_JUDGMENT"]


@bp.route("/licensing/recovery-fund-claims", methods=["POST"])
def create_claim():
    require_auth(["Consumer", "FundAdjudicator"])
    body = get_body()
    fund_account_id = v_id(body, "fund_account_id")
    complaint_id = v_id(body, "complaint_id")
    basis = v_enum(body, "basis", JUDGMENT_BASES)
    claimed_amount_cents = v_money(body, "claimed_amount_cents")
    judgment_amount_cents = v_money(body, "judgment_amount_cents", required=False)
    judgment_docket_number = v_str(body, "judgment_docket_number", required=False)
    judgment_entered_on = v_date(body, "judgment_entered_on", required=False)

    account = must("recovery_fund_accounts", fund_account_id)
    complaint = must("complaints", complaint_id)

    if not complaint.get("license_id"):
        err("ERR_UNLICENSED_SUBJECT_NOT_CLAIMABLE",
            "the recovery fund does not reach unlicensed operators")

    for existing in rows("recovery_fund_claims"):
        if existing["complaint_id"] == complaint["id"] and existing["status"] != "DENIED":
            err("ERR_DUPLICATE_CLAIM", "a live claim already stands on this complaint")

    judgment_supplied = [judgment_amount_cents is not None,
                         judgment_docket_number is not None,
                         judgment_entered_on is not None]
    if basis == "COURT_JUDGMENT":
        if not all(judgment_supplied):
            err("ERR_JUDGMENT_FIELDS_MISMATCH",
                "a COURT_JUDGMENT claim requires the full judgment field set")
    else:
        if any(judgment_supplied):
            err("ERR_JUDGMENT_FIELDS_MISMATCH",
                "a FINAL_CITATION claim must omit every judgment field")

    if (claimed_amount_cents < 1
            or claimed_amount_cents > complaint["alleged_loss_cents"]):
        err("ERR_CLAIM_EXCEEDS_ALLEGED_LOSS",
            "the claimed amount must be between one cent and the pleaded loss")

    row = new_row()
    row.update({
        "fund_account_id": account["id"],
        "complaint_id": complaint["id"],
        "consumer_id": complaint["consumer_id"],
        "license_id": complaint["license_id"],
        "basis": basis,
        "claimed_amount_cents": claimed_amount_cents,
        "judgment_amount_cents": judgment_amount_cents,
        "judgment_docket_number": judgment_docket_number,
        "judgment_entered_on": (fmt_date(judgment_entered_on)
                               if judgment_entered_on is not None else None),
        "estimated_award_cents": calc.recovery_preliminary_estimate(
            claimed_amount_cents, account["per_claim_cap_cents"]),
        "awarded_amount_cents": None,
        "paid_amount_cents": 0,
        "repaid_amount_cents": 0,
        "status": "FILED",
        "denial_reason": None,
        "adjudicated_on": None,
        "paid_on": None,
    })
    db.recovery_fund_claims[row["id"]] = row
    return created(domain.ser_claim(row))


@bp.route("/licensing/recovery-fund-claims/<rid>", methods=["GET"])
def get_claim(rid):
    require_auth(CLAIM_READ_ROLES)
    return ok(domain.ser_claim(must("recovery_fund_claims", rid)))


@bp.route("/licensing/recovery-fund-claims", methods=["GET"])
def list_claims():
    require_auth(CLAIM_READ_ROLES)
    items = rows("recovery_fund_claims")
    for field in ("fund_account_id", "complaint_id", "consumer_id", "license_id",
                  "status"):
        items = qfilter(items, field)
    return render_list(items, domain.ser_claim)


@bp.route("/licensing/recovery-fund-claims/<rid>/adjudicate", methods=["POST"])
def adjudicate_claim(rid):
    require_auth(["FundAdjudicator"])
    body = get_body()
    outcome = v_enum(body, "outcome", ["APPROVE", "DENY"])
    denial_reason = v_str(body, "denial_reason", required=False)

    claim = must("recovery_fund_claims", rid)
    if claim["status"] != "FILED":
        err("ERR_CLAIM_STATE_INVALID", "only a FILED claim may be adjudicated")

    today = clock_date()

    if outcome == "DENY":
        setf(claim, "status", "DENIED")
        setf(claim, "awarded_amount_cents", 0)
        setf(claim, "denial_reason", denial_reason)
        setf(claim, "adjudicated_on", fmt_date(today))
        touch(claim)
        return ok(domain.ser_claim(claim))

    complaint = find("complaints", claim["complaint_id"])
    complaint_status = complaint["status"] if complaint is not None else None
    if claim["basis"] == "FINAL_CITATION":
        allowed = ("CLOSED_SANCTIONED",)
    else:
        allowed = ("MEDIATION", "INVESTIGATION", "CITATION_ISSUED", "CLOSED_SANCTIONED")
    if complaint_status not in allowed:
        err("ERR_CLAIM_BASIS_NOT_ESTABLISHED",
            "the underlying complaint does not establish this claim's basis")

    if claim["basis"] == "COURT_JUDGMENT":
        ripe_on = add_days(D(claim["judgment_entered_on"]), calc.JUDGMENT_RIPENING_DAYS)
        if today < ripe_on:
            err("ERR_JUDGMENT_NOT_RIPE",
                "the judgment has not gone ninety days unsatisfied")

    account = find("recovery_fund_accounts", claim["fund_account_id"])
    lic = find("licenses", claim["license_id"])
    award = calc.recovery_final_award(
        claim["basis"], claim["claimed_amount_cents"],
        claim.get("judgment_amount_cents"),
        complaint["settlement_amount_cents"] if complaint is not None else 0,
        account["per_claim_cap_cents"],
        account["per_license_aggregate_cap_cents"],
        domain.license_recovery_encumbered(lic) if lic is not None else 0)

    setf(claim, "awarded_amount_cents", award)
    setf(claim, "adjudicated_on", fmt_date(today))
    if award >= 1:
        setf(claim, "status", "APPROVED")
    else:
        setf(claim, "status", "DENIED")
        setf(claim, "denial_reason", "AGGREGATE_CAP_EXHAUSTED")
    touch(claim)
    if lic is not None:
        touch(lic)
    return ok(domain.ser_claim(claim))


@bp.route("/licensing/recovery-fund-claims/<rid>/pay", methods=["POST"])
def pay_claim(rid):
    require_auth(["FundAdjudicator"])
    body = get_body()
    expected_fund_account_version = v_int(body, "expected_fund_account_version")

    claim = must("recovery_fund_claims", rid)
    account = find("recovery_fund_accounts", claim["fund_account_id"])

    if account is None or expected_fund_account_version != account["version"]:
        err("ERR_STALE_FUND_ACCOUNT_VERSION",
            "the presented fund account version is stale")

    if claim["status"] != "APPROVED":
        err("ERR_CLAIM_STATE_INVALID", "only an APPROVED claim may be disbursed")

    balance = domain.account_balance(account)
    if balance < 1:
        err("ERR_FUND_BALANCE_EXHAUSTED", "the appropriation has no cash to disburse")

    lic = find("licenses", claim["license_id"])
    cohort = [c for c in domain.license_claims(claim["license_id"])
              if c["status"] == "APPROVED"]
    cohort.sort(key=lambda c: (c["created_at"], c["_seq"]))
    awards = [c["awarded_amount_cents"] or 0 for c in cohort]
    shares = calc.recovery_prorata_distribution(awards, balance)

    today = fmt_date(clock_date())
    for member, share in zip(cohort, shares):
        setf(member, "paid_amount_cents", share)
        setf(member, "paid_on", today)
        setf(member, "status", "PAID")
        touch(member)

    touch(account)

    if lic is not None:
        if lic["status"] == "ACTIVE":
            domain.suspend_license(lic, "RECOVERY_FUND_PAYOUT", None)
        domain.recompute_posture(lic)
        touch(lic)
        touch(find("licensees", lic["licensee_id"]))

    return ok(domain.ser_claim(claim))
