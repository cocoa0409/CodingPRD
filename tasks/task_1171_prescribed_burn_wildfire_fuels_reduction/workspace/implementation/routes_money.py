"""Monitoring report, cost-share agreement, and liability claim routes."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from core import (
    DB,
    ApiError,
    Validator,
    auth,
    body,
    clock,
    ok,
    paginate,
    require_role,
    stamp_new,
    touch,
)
from domain import (
    effectiveness_score,
    final_reimbursement,
    fund_payout_with_cap,
    get_agreement,
    get_claim,
    get_incident,
    get_landowner,
    get_plan,
    get_report,
    landowner_of_incident,
    landowner_standing,
    live_agreement_for_plan,
    plan_permit,
    provisional_estimate,
    round_half_up_cents,
    ser_agreement,
    ser_claim,
    ser_report,
    suppression_allocation,
    the_association,
)

bp = Blueprint("money", __name__)


def _plan_of_execution(ex):
    return DB["plans"].get(ex["burn_plan_id"]) if ex else None


def _author_or_403(plan, uid):
    if plan is None or uid != plan["author_boss_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Caller is not the plan's author")


def _validate_actual_lines(v, lines):
    if lines is None:
        v.invalid("Missing required field: actual_treatment_lines")
        return
    if not isinstance(lines, list):
        v.invalid("actual_treatment_lines must be an array")
        return
    for idx, line in enumerate(lines):
        if not isinstance(line, dict):
            v.invalid(f"actual_treatment_lines[{idx}] must be an object")
            return
        extra = set(line.keys()) - {"category", "rate_class", "acres"}
        if extra:
            v.invalid(f"actual_treatment_lines[{idx}] has unknown field")
            return
        cat, rc, acres = line.get("category"), line.get("rate_class"), line.get("acres")
        if cat is None or rc is None or acres is None:
            v.invalid(f"actual_treatment_lines[{idx}] is missing a field")
            return
        if not isinstance(cat, str) or not isinstance(rc, str):
            v.invalid(f"actual_treatment_lines[{idx}] has an invalid type")
            return
        if cat not in ("BROADCAST", "UNDERSTORY", "PILE_BURN"):
            v._set("ERR_INVALID_ENUM", f"actual_treatment_lines[{idx}].category is invalid")
            return
        if rc not in ("GRASS", "BRUSH", "TIMBER"):
            v._set("ERR_INVALID_ENUM", f"actual_treatment_lines[{idx}].rate_class is invalid")
            return
        if not (isinstance(acres, int) and not isinstance(acres, bool)) or acres < 0:
            v.invalid(f"actual_treatment_lines[{idx}].acres must be a non-negative integer")
            return


# ---------------------------------------------------------------------------
# Monitoring reports
# ---------------------------------------------------------------------------


@bp.get("/monitoring-reports/<rid>")
def get_one_report(rid):
    _, role = auth()
    require_role(role, None)
    return ok(ser_report(get_report(rid)))


@bp.get("/executions/<eid>/monitoring-reports")
def list_execution_reports(eid):
    from domain import get_execution

    _, role = auth()
    require_role(role, None)
    ex = get_execution(eid)
    items = [r for r in DB["reports"].values() if r["burn_execution_id"] == ex["id"]]
    # sorted by due_at ascending (exception to the default created_at sort)
    return paginate(items, ser_report, sort_key=lambda r: (r["due_at"], r["_seq"]))


@bp.post("/monitoring-reports/<rid>/submit")
def submit_report(rid):
    data = body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    report = get_report(rid)
    ex = DB["executions"].get(report["burn_execution_id"])
    plan = _plan_of_execution(ex)
    _author_or_403(plan, uid)
    if report["status"] not in ("DUE", "OVERDUE", "DEFICIENT"):
        raise ApiError(
            "ERR_REPORT_NOT_SUBMITTABLE",
            409,
            "MonitoringReport must be DUE, OVERDUE, or DEFICIENT",
        )
    v = Validator(data, {"actual_treatment_lines"})
    _validate_actual_lines(v, data.get("actual_treatment_lines"))
    v.finish()
    lines = data["actual_treatment_lines"]
    agreement = live_agreement_for_plan(plan["id"]) if plan else None
    planned_lines = (
        agreement["treatment_lines"]
        if agreement is not None
        else (plan["treatment_lines"] if plan else [])
    )
    report["actual_treatment_lines"] = lines
    report["effectiveness_score"] = effectiveness_score(planned_lines, lines)
    report["deficiency_reason"] = None
    report["status"] = "SUBMITTED"
    touch(report)
    return ok(ser_report(report))


@bp.post("/monitoring-reports/<rid>/accept")
def accept_report(rid):
    body()
    uid, role = auth()
    require_role(role, {"AgencyReviewer"})
    report = get_report(rid)
    ex = DB["executions"].get(report["burn_execution_id"])
    plan = _plan_of_execution(ex)
    # SoD (priority 5) before state (priority 7)
    if plan is not None and uid == plan["author_boss_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES_VIOLATION",
            403,
            "Reviewer may not accept the plan author's monitoring report",
        )
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_REPORT_NOT_SUBMITTED", 409, "Report must be SUBMITTED")
    report["status"] = "ACCEPTED"
    touch(report)
    if report["report_type"] == "THIRTY_DAY" and plan is not None:
        agreement = live_agreement_for_plan(plan["id"])
        if agreement is not None:
            agreement["final_reimbursement_cents"] = final_reimbursement(agreement, report)
    return ok(ser_report(report))


@bp.post("/monitoring-reports/<rid>/mark-deficient")
def mark_deficient(rid):
    data = body()
    _, role = auth()
    require_role(role, {"AgencyReviewer"})
    report = get_report(rid)
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_REPORT_NOT_SUBMITTED", 409, "Report must be SUBMITTED")
    v = Validator(data, {"reason"})
    v.opt("reason", str)
    v.finish()
    report["deficiency_reason"] = data.get("reason")
    report["status"] = "DEFICIENT"
    touch(report)
    return ok(ser_report(report))


# ---------------------------------------------------------------------------
# Cost-share agreements
# ---------------------------------------------------------------------------


@bp.post("/cost-share-agreements")
def create_agreement():
    data = body()
    uid, role = auth()
    require_role(role, {"Landowner"})
    landowner_id = data.get("landowner_id")
    landowner = None
    if isinstance(landowner_id, str):
        landowner = get_landowner(landowner_id)
    plan_id = data.get("burn_plan_id")
    plan = None
    if isinstance(plan_id, str):
        plan = get_plan(plan_id)
    # ownership (priority 4)
    if landowner_id is not None and landowner_id != uid:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER", 403, "landowner_id must equal the caller's X-User-ID"
        )
    # state (priority 7): plan must be APPROVED
    if plan is not None and plan["status"] != "APPROVED":
        raise ApiError("ERR_PLAN_NOT_APPROVED", 409, "Plan must be APPROVED")
    # standing gate (priority 9)
    if landowner is not None and landowner_standing(landowner) != "GOOD_STANDING":
        raise ApiError(
            "ERR_LANDOWNER_NOT_IN_GOOD_STANDING", 403, "Landowner is not in good standing"
        )
    # referential (priority 10): applicant must own the plan's parcel
    if plan is not None and landowner is not None:
        parcel = DB["parcels"].get(plan["parcel_id"])
        if parcel is not None and parcel["landowner_id"] != landowner["id"]:
            raise ApiError(
                "ERR_PARCEL_OWNERSHIP_MISMATCH",
                409,
                "Agreement landowner does not own the plan's parcel",
            )
    # uniqueness (priority 11)
    if plan is not None:
        for other in DB["agreements"].values():
            if other["burn_plan_id"] == plan["id"] and other["status"] in (
                "SUBMITTED",
                "UNDER_REVIEW",
                "APPROVED",
                "PARTIALLY_DISBURSED",
                "SUSPENDED",
            ):
                raise ApiError(
                    "ERR_ACTIVE_AGREEMENT_EXISTS_FOR_PLAN",
                    409,
                    "Plan already has a live cost-share agreement",
                )
    # field-level (priority 14)
    v = Validator(data, {"landowner_id", "burn_plan_id", "funding_tier", "treatment_lines"})
    v.req("landowner_id", str)
    v.req("burn_plan_id", str)
    v.enum("funding_tier", {"STANDARD", "PRIORITY", "LEGACY"})
    lines = data.get("treatment_lines")
    if lines is None:
        v.invalid("Missing required field: treatment_lines")
    elif not isinstance(lines, list) or len(lines) < 1:
        v.invalid("treatment_lines must be a non-empty array")
    else:
        for idx, line in enumerate(lines):
            if not isinstance(line, dict):
                v.invalid(f"treatment_lines[{idx}] must be an object")
                break
            extra = set(line.keys()) - {"category", "rate_class", "acres"}
            if extra:
                v.invalid(f"treatment_lines[{idx}] has unknown field")
                break
            cat, rc, acres = line.get("category"), line.get("rate_class"), line.get("acres")
            if cat is None or rc is None or acres is None:
                v.invalid(f"treatment_lines[{idx}] is missing a field")
                break
            if not isinstance(cat, str) or not isinstance(rc, str):
                v.invalid(f"treatment_lines[{idx}] has an invalid type")
                break
            if cat not in ("BROADCAST", "UNDERSTORY", "PILE_BURN"):
                v._set("ERR_INVALID_ENUM", f"treatment_lines[{idx}].category is invalid")
                break
            if rc not in ("GRASS", "BRUSH", "TIMBER"):
                v._set("ERR_INVALID_ENUM", f"treatment_lines[{idx}].rate_class is invalid")
                break
            if not (isinstance(acres, int) and not isinstance(acres, bool)):
                v.invalid(f"treatment_lines[{idx}].acres must be an integer")
                break
            if acres <= 0:
                v.prescription(f"treatment_lines[{idx}].acres must be positive")
                break
    v.finish()
    agreement = stamp_new(
        {
            "landowner_id": landowner["id"],
            "burn_plan_id": plan["id"],
            "funding_tier": data["funding_tier"],
            "treatment_lines": lines,
            "disbursed_cents": 0,
            "final_reimbursement_cents": None,
            "approved_at": None,
            "expires_at": None,
            "status": "SUBMITTED",
        }
    )
    agreement["provisional_estimate_cents"] = provisional_estimate(agreement)
    DB["agreements"][agreement["id"]] = agreement
    return ok(ser_agreement(agreement), 201)


@bp.get("/cost-share-agreements/<aid>")
def get_one_agreement(aid):
    _, role = auth()
    require_role(role, None)
    return ok(ser_agreement(get_agreement(aid)))


@bp.get("/cost-share-agreements")
def list_agreements():
    _, role = auth()
    require_role(role, None)
    items = list(DB["agreements"].values())
    for key in ("landowner_id", "burn_plan_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [a for a in items if a[key] == val]
    return paginate(items, ser_agreement)


@bp.post("/cost-share-agreements/<aid>/begin-review")
def begin_review(aid):
    body()
    _, role = auth()
    require_role(role, {"AssociationAdmin"})
    agreement = get_agreement(aid)
    if agreement["status"] != "SUBMITTED":
        raise ApiError("ERR_AGREEMENT_NOT_SUBMITTED", 409, "Agreement must be SUBMITTED")
    agreement["status"] = "UNDER_REVIEW"
    touch(agreement)
    return ok(ser_agreement(agreement))


@bp.post("/cost-share-agreements/<aid>/approve")
def approve_agreement(aid):
    body()
    uid, role = auth()
    require_role(role, {"AssociationAdmin"})
    agreement = get_agreement(aid)
    # SoD (priority 5) before state (priority 7)
    if uid == agreement["landowner_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES_VIOLATION",
            403,
            "Approver may not be the applying landowner",
        )
    if agreement["status"] != "UNDER_REVIEW":
        raise ApiError(
            "ERR_AGREEMENT_NOT_UNDER_REVIEW", 409, "Agreement must be UNDER_REVIEW"
        )
    agreement["status"] = "APPROVED"
    agreement["approved_at"] = clock()
    agreement["expires_at"] = clock() + timedelta(days=365)
    touch(agreement)
    return ok(ser_agreement(agreement))


@bp.post("/cost-share-agreements/<aid>/deny")
def deny_agreement(aid):
    data = body()
    _, role = auth()
    require_role(role, {"AssociationAdmin"})
    agreement = get_agreement(aid)
    if agreement["status"] != "UNDER_REVIEW":
        raise ApiError(
            "ERR_AGREEMENT_NOT_UNDER_REVIEW", 409, "Agreement must be UNDER_REVIEW"
        )
    v = Validator(data, {"reason"})
    v.opt("reason", str)
    v.finish()
    agreement["status"] = "DENIED"
    touch(agreement)
    return ok(ser_agreement(agreement))


@bp.post("/cost-share-agreements/<aid>/disburse")
def disburse(aid):
    body()
    _, role = auth()
    require_role(role, {"AssociationAdmin"})
    agreement = get_agreement(aid)
    assoc = the_association()
    status = agreement["status"]
    if status == "FULLY_DISBURSED":
        raise ApiError("ERR_NO_DISBURSEMENT_DUE", 402, "Nothing is due to disburse")
    if status not in ("APPROVED", "PARTIALLY_DISBURSED"):
        raise ApiError("ERR_AGREEMENT_NOT_APPROVED", 409, "Agreement must be APPROVED")
    plan = DB["plans"].get(agreement["burn_plan_id"])
    if status == "APPROVED":
        # provisional installment gate: a CLOSED execution on the plan
        closed = any(
            e["burn_plan_id"] == agreement["burn_plan_id"] and e["phase"] == "CLOSED"
            for e in DB["executions"].values()
        )
        if not closed:
            raise ApiError(
                "ERR_NO_CLOSED_EXECUTION", 409, "No CLOSED execution on the plan"
            )
        installment = round_half_up_cents(
            Decimal(agreement["provisional_estimate_cents"]) * Decimal("0.5")
        )
        target = "PARTIALLY_DISBURSED"
    else:
        # final installment gate: THIRTY_DAY report ACCEPTED
        thirty_ok = False
        for r in DB["reports"].values():
            ex = DB["executions"].get(r["burn_execution_id"])
            if (
                ex is not None
                and ex["burn_plan_id"] == agreement["burn_plan_id"]
                and r["report_type"] == "THIRTY_DAY"
                and r["status"] == "ACCEPTED"
            ):
                thirty_ok = True
                break
        if not thirty_ok:
            raise ApiError(
                "ERR_MONITORING_NOT_ACCEPTED",
                409,
                "THIRTY_DAY report is not ACCEPTED",
            )
        final_cents = agreement["final_reimbursement_cents"]
        if final_cents is None:
            raise ApiError(
                "ERR_MONITORING_NOT_ACCEPTED",
                409,
                "THIRTY_DAY report is not ACCEPTED",
            )
        installment = final_cents - agreement["disbursed_cents"]
        target = "FULLY_DISBURSED"
    # temporal (priority 12): agreement not expired
    if agreement["expires_at"] is not None and clock() > agreement["expires_at"]:
        raise ApiError("ERR_AGREEMENT_EXPIRED", 422, "Agreement has expired")
    if installment == 0:
        raise ApiError("ERR_NO_DISBURSEMENT_DUE", 402, "Nothing is due to disburse")
    # fiscal (priority 13): skipped for non-positive (clawback) installments
    if installment > 0:
        if assoc is None or assoc["fund_balance_cents"] < installment:
            raise ApiError(
                "ERR_INSUFFICIENT_ASSOCIATION_FUNDS",
                402,
                "Fund balance does not cover the installment",
            )
    agreement["disbursed_cents"] += installment
    if assoc is not None:
        assoc["fund_balance_cents"] -= installment
        touch(assoc)
    agreement["status"] = target
    touch(agreement)
    return ok(ser_agreement(agreement))


@bp.post("/cost-share-agreements/<aid>/reinstate")
def reinstate_agreement(aid):
    body()
    _, role = auth()
    require_role(role, {"AssociationAdmin"})
    agreement = get_agreement(aid)
    if agreement["status"] != "SUSPENDED":
        raise ApiError("ERR_AGREEMENT_NOT_SUSPENDED", 409, "Agreement must be SUSPENDED")
    # every liability claim on incidents of the plan's executions resolved
    for ex in DB["executions"].values():
        if ex["burn_plan_id"] != agreement["burn_plan_id"]:
            continue
        for incident in DB["incidents"].values():
            if incident["burn_execution_id"] != ex["id"]:
                continue
            for claim in DB["claims"].values():
                if claim["incident_id"] != incident["id"]:
                    continue
                if claim["status"] not in ("CLOSED", "DISMISSED", "PAYMENT_REVERSED"):
                    raise ApiError(
                        "ERR_CLAIMS_NOT_RESOLVED",
                        409,
                        "Liability claims on the plan's executions are not all resolved",
                    )
    permit = plan_permit(agreement["burn_plan_id"])
    if permit is None or permit["status"] != "ISSUED":
        raise ApiError("ERR_PERMIT_NOT_ISSUED", 409, "The plan's permit must be ISSUED")
    agreement["status"] = (
        "APPROVED" if agreement["disbursed_cents"] == 0 else "PARTIALLY_DISBURSED"
    )
    touch(agreement)
    return ok(ser_agreement(agreement))


@bp.post("/cost-share-agreements/<aid>/cancel")
def cancel_agreement(aid):
    body()
    _, role = auth()
    require_role(role, {"AssociationAdmin"})
    agreement = get_agreement(aid)
    if agreement["status"] not in ("SUBMITTED", "UNDER_REVIEW", "APPROVED"):
        raise ApiError(
            "ERR_AGREEMENT_NOT_CANCELLABLE",
            409,
            "Agreement must be SUBMITTED, UNDER_REVIEW, or APPROVED",
        )
    agreement["status"] = "CANCELLED"
    touch(agreement)
    return ok(ser_agreement(agreement))


# ---------------------------------------------------------------------------
# Liability claims
# ---------------------------------------------------------------------------


@bp.post("/incidents/<iid>/liability-claims")
def create_claim(iid):
    body()
    _, role = auth()
    require_role(role, {"IncidentCommander"})
    incident = get_incident(iid)
    if incident["billing_status"] != "ASSESSED":
        raise ApiError(
            "ERR_BILLING_NOT_ASSESSED", 409, "Incident billing must be ASSESSED"
        )
    claim = stamp_new(
        {
            "incident_id": incident["id"],
            "total_suppression_cost_cents": incident["suppression_cost_cents"],
            "negligence_found": None,
            "landowner_share_cents": None,
            "association_share_cents": None,
            "fund_payout_cents": None,
            "outcome": "PENDING",
            "adjudicated_at": None,
            "status": "FILED",
        }
    )
    DB["claims"][claim["id"]] = claim
    incident["billing_status"] = "BILLED"
    touch(incident)
    return ok(ser_claim(claim), 201)


@bp.get("/liability-claims/<cid>")
def get_one_claim(cid):
    _, role = auth()
    require_role(role, None)
    return ok(ser_claim(get_claim(cid)))


@bp.get("/incidents/<iid>/liability-claims")
def list_incident_claims(iid):
    _, role = auth()
    require_role(role, None)
    incident = get_incident(iid)
    items = [c for c in DB["claims"].values() if c["incident_id"] == incident["id"]]
    return paginate(items, ser_claim)


@bp.post("/liability-claims/<cid>/begin-investigation")
def begin_investigation(cid):
    body()
    _, role = auth()
    require_role(role, {"AssociationAdmin"})
    claim = get_claim(cid)
    if claim["status"] != "FILED":
        raise ApiError("ERR_CLAIM_NOT_FILED", 409, "LiabilityClaim must be FILED")
    claim["status"] = "UNDER_INVESTIGATION"
    touch(claim)
    return ok(ser_claim(claim))


@bp.post("/liability-claims/<cid>/adjudicate")
def adjudicate(cid):
    data = body()
    _, role = auth()
    require_role(role, {"AssociationAdmin"})
    claim = get_claim(cid)
    if claim["status"] != "UNDER_INVESTIGATION":
        raise ApiError(
            "ERR_CLAIM_NOT_UNDER_INVESTIGATION",
            409,
            "LiabilityClaim must be UNDER_INVESTIGATION",
        )
    v = Validator(data, {"outcome", "negligence_found"})
    v.enum("outcome", {"LANDOWNER_LIABLE", "ASSOCIATION_LIABLE", "NOT_LIABLE"})
    v.req("negligence_found", bool)
    v.finish()
    outcome = data["outcome"]
    claim["outcome"] = outcome
    if outcome == "NOT_LIABLE":
        claim["status"] = "DISMISSED"
        touch(claim)
        return ok(ser_claim(claim))
    negligence = data["negligence_found"]
    claim["negligence_found"] = negligence
    assoc = the_association()
    if assoc is None:
        raise ApiError("ERR_NOT_FOUND", 404, "No association exists")
    landowner_share, association_share = suppression_allocation(claim, assoc, negligence)
    claim["landowner_share_cents"] = landowner_share
    claim["association_share_cents"] = association_share
    claim["adjudicated_at"] = clock()
    claim["status"] = "ADJUDICATED"
    if outcome == "LANDOWNER_LIABLE":
        incident = DB["incidents"].get(claim["incident_id"])
        landowner = landowner_of_incident(incident) if incident else None
        if landowner is not None:
            landowner["outstanding_liability_cents"] += landowner_share
    touch(claim)
    return ok(ser_claim(claim))


@bp.post("/liability-claims/<cid>/pay")
def pay_claim(cid):
    body()
    _, role = auth()
    require_role(role, {"AssociationAdmin"})
    claim = get_claim(cid)
    if claim["status"] not in ("ADJUDICATED", "PAYMENT_REVERSED"):
        raise ApiError(
            "ERR_CLAIM_NOT_ADJUDICATED",
            409,
            "LiabilityClaim must be ADJUDICATED or PAYMENT_REVERSED",
        )
    assoc = the_association()
    if assoc is None:
        raise ApiError("ERR_NOT_FOUND", 404, "No association exists")
    share = claim["association_share_cents"] or 0
    payout = fund_payout_with_cap(assoc, share)
    if payout <= 0 and share > 0:
        raise ApiError(
            "ERR_INSUFFICIENT_ASSOCIATION_FUNDS",
            402,
            "Computed fund payout is zero while the association share is positive",
        )
    if payout < 0:
        payout = 0
    claim["fund_payout_cents"] = payout
    assoc["fund_balance_cents"] -= payout
    touch(assoc)
    claim["status"] = "PAID"
    touch(claim)
    incident = DB["incidents"].get(claim["incident_id"])
    if incident is not None:
        incident["billing_status"] = "SETTLED"
        touch(incident)
    return ok(ser_claim(claim))


@bp.post("/liability-claims/<cid>/reverse-payment")
def reverse_payment(cid):
    body()
    _, role = auth()
    require_role(role, {"AssociationAdmin"})
    claim = get_claim(cid)
    if claim["status"] != "PAID":
        raise ApiError("ERR_CLAIM_NOT_PAID", 409, "LiabilityClaim must be PAID")
    assoc = the_association()
    if assoc is not None:
        assoc["fund_balance_cents"] += claim["fund_payout_cents"]
        touch(assoc)
    claim["status"] = "PAYMENT_REVERSED"
    touch(claim)
    incident = DB["incidents"].get(claim["incident_id"])
    if incident is not None:
        incident["billing_status"] = "DISPUTED"
        touch(incident)
    return ok(ser_claim(claim))


@bp.post("/liability-claims/<cid>/close")
def close_claim(cid):
    body()
    _, role = auth()
    require_role(role, {"AssociationAdmin"})
    claim = get_claim(cid)
    if claim["status"] not in ("PAID", "PAYMENT_REVERSED"):
        raise ApiError(
            "ERR_CLAIM_NOT_CLOSABLE",
            409,
            "LiabilityClaim must be PAID or PAYMENT_REVERSED",
        )
    claim["status"] = "CLOSED"
    touch(claim)
    return ok(ser_claim(claim))
