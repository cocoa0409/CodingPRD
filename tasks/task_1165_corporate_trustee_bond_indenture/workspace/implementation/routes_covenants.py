"""Routes: CovenantObligation and CovenantCertificate (PRD 3.3)."""
from flask import Blueprint, request

from auth import require_roles, ALL_ROLES, check_issuer_owns
from envelope import ok, list_response, get_body, public
from errors import (raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_ALREADY_TERMINAL, ERR_COVENANT_RATIO_FAILED,
                    ERR_INVALID_REQUEST)
from store import DB, LOCK, new_entity, now, now_iso, mutate, fmt_ts
from validate import (req_str, opt_str, req_enum, opt_enum, req_date, opt_num,
                      opt_int, parse_date_strict)
from calc import covenant_ratio_passes
from domain import (recompute_posture, obligation_roll_forward,
                    cure_linked_alleged_case)

bp = Blueprint("covenants", __name__)

RATIO_TYPES = ("DEBT_SERVICE_COVERAGE", "LEVERAGE_RATIO")


# ---------------------------------------------------------------------------
# CovenantObligation
# ---------------------------------------------------------------------------

@bp.route("/covenant-obligations", methods=["POST"])
@require_roles("TrustOfficer")
def create_obligation():
    body = get_body()
    with LOCK:
        indenture_id = body.get("indenture_id")
        ind = DB["indentures"].get(indenture_id) if isinstance(indenture_id, str) else None
        if ind is None:
            raise_err(ERR_NOT_FOUND, "Indenture not found")
        # Shape (rule 26).
        req_str(body, "indenture_id")
        ctype = req_enum(body, "covenant_type",
                         ["FINANCIAL_REPORT", "INSURANCE_CERT",
                          "DEBT_SERVICE_COVERAGE", "LEVERAGE_RATIO",
                          "TAX_COMPLIANCE"])
        freq = req_enum(body, "frequency",
                        ["QUARTERLY", "SEMI_ANNUAL", "ANNUAL"])
        anchor = req_date(body, "period_anchor_date")
        threshold = opt_num(body, "threshold_value")
        direction = opt_enum(body, "threshold_direction", ["MIN", "MAX"])
        basis = opt_enum(body, "measurement_basis",
                         ["TTM", "QUARTERLY_ANNUALIZED"])
        grace = opt_int(body, "grace_period_days", 10)
        # Ratio covenants require threshold_value; whenever threshold_value is
        # present, threshold_direction and measurement_basis are required.
        if ctype in RATIO_TYPES and threshold is None:
            raise_err(ERR_INVALID_REQUEST,
                      "threshold_value is required for ratio covenant types")
        if threshold is not None:
            if direction is None:
                raise_err(ERR_INVALID_REQUEST,
                          "threshold_direction is required with threshold_value")
            if basis is None:
                raise_err(ERR_INVALID_REQUEST,
                          "measurement_basis is required with threshold_value")
        e = new_entity("covenant_obligations")
        e.update({
            "indenture_id": indenture_id,
            "covenant_type": ctype,
            "frequency": freq,
            "threshold_value": threshold,
            "threshold_direction": direction,
            "measurement_basis": basis,
            "period_anchor_date": anchor,
            "next_due_date": anchor,
            "grace_period_days": grace,
            "status": "OPEN",
        })
        recompute_posture(ind)
    return ok(public(e), 201)


@bp.route("/covenant-obligations", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_obligations():
    return list_response(DB["covenant_obligations"].values(), {
        "indenture_id": request.args.get("indenture_id"),
        "status": request.args.get("status"),
    })


@bp.route("/covenant-obligations/<oid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_obligation(oid):
    e = DB["covenant_obligations"].get(oid)
    if e is None:
        raise_err(ERR_NOT_FOUND, "CovenantObligation not found")
    return ok(public(e))


# ---------------------------------------------------------------------------
# CovenantCertificate
# ---------------------------------------------------------------------------

@bp.route("/covenant-certificates", methods=["POST"])
@require_roles("Issuer")
def create_certificate():
    body = get_body()
    with LOCK:
        ob_id = body.get("covenant_obligation_id")
        ob = DB["covenant_obligations"].get(ob_id) if isinstance(ob_id, str) else None
        if ob is None:
            raise_err(ERR_NOT_FOUND, "CovenantObligation not found")
        # Rule 3: issuer must own the obligation's indenture.
        ind = DB["indentures"].get(ob["indenture_id"])
        check_issuer_owns(ind)
        # Shape (rule 26).
        req_str(body, "covenant_obligation_id")
        period_end = req_date(body, "period_end_date")
        doc_ref = req_str(body, "document_ref")
        metric = opt_num(body, "metric_value")
        ttm = opt_num(body, "ttm_metric_value")
        if ob.get("threshold_value") is not None:
            if metric is None:
                raise_err(ERR_INVALID_REQUEST,
                          "metric_value is required for ratio obligations")
            if ttm is None:
                raise_err(ERR_INVALID_REQUEST,
                          "ttm_metric_value is required for ratio obligations")
        submitted = now()
        nd = parse_date_strict(ob["next_due_date"])
        is_late = bool(nd is not None and submitted.date() > nd)
        e = new_entity("covenant_certificates")
        e.update({
            "covenant_obligation_id": ob_id,
            "period_end_date": period_end,
            "metric_value": metric,
            "ttm_metric_value": ttm,
            "document_ref": doc_ref,
            "submitted_at": fmt_ts(submitted),
            "is_late": is_late,
            "status": "SUBMITTED",
            "reviewed_by_user_id": None,
        })
    return ok(public(e), 201)


@bp.route("/covenant-certificates", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_certificates():
    return list_response(DB["covenant_certificates"].values(), {
        "covenant_obligation_id": request.args.get("covenant_obligation_id"),
        "status": request.args.get("status"),
    })


@bp.route("/covenant-certificates/<cid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_certificate(cid):
    e = DB["covenant_certificates"].get(cid)
    if e is None:
        raise_err(ERR_NOT_FOUND, "CovenantCertificate not found")
    return ok(public(e))


@bp.route("/covenant-certificates/<cid>/review", methods=["POST"])
@require_roles("TrustOfficer")
def review_certificate(cid):
    body = get_body()
    with LOCK:
        cert = DB["covenant_certificates"].get(cid)
        if cert is None:
            raise_err(ERR_NOT_FOUND, "CovenantCertificate not found")
        # Rule 5: state admissibility.
        if cert["status"] in ("ACCEPTED", "REJECTED"):
            raise_err(ERR_ALREADY_TERMINAL,
                      "Certificate is terminal (%s)" % cert["status"])
        if cert["status"] != "SUBMITTED":
            raise_err(ERR_INVALID_STATE, "Certificate is not SUBMITTED")
        ob = DB["covenant_obligations"].get(cert["covenant_obligation_id"])
        decision = body.get("decision")
        # Rule 21: ratio covenant pass on ACCEPT.
        if decision == "ACCEPT" and ob is not None:
            if not covenant_ratio_passes(ob, cert):
                raise_err(ERR_COVENANT_RATIO_FAILED,
                          "Certificate metric fails the obligation threshold")
        # Rule 26: shape.
        decision = req_enum(body, "decision", ["ACCEPT", "REJECT"])
        opt_str(body, "rejection_reason")
        ind = DB["indentures"].get(ob["indenture_id"]) if ob else None
        from auth import uid
        if decision == "ACCEPT":
            mutate(cert, status="ACCEPTED", reviewed_by_user_id=uid())
            if ob is not None and ob["status"] != "WAIVED":
                was_breached = ob["status"] == "BREACHED"
                obligation_roll_forward(ob)
                if ind is not None:
                    if was_breached:
                        cure_linked_alleged_case(ind, ob)
                    recompute_posture(ind)
        else:
            mutate(cert, status="REJECTED", reviewed_by_user_id=uid())
    return ok(public(cert))
