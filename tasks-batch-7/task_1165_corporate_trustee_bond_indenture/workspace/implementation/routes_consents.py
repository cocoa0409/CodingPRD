"""Routes: ConsentSolicitation (PRD 3.6)."""
from flask import Blueprint, request

from auth import require_roles, ALL_ROLES, uid, check_noteholder_owns, check_issuer_owns
from envelope import ok, list_response, get_body, public
from errors import (raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_ALREADY_TERMINAL, ERR_DUPLICATE_CONSTRAINT,
                    ERR_SOLICITATION_WINDOW_OVERLAP, ERR_SOLICITATION_EXPIRED,
                    ERR_NO_ELIGIBLE_POSITION, ERR_TARGET_OBLIGATION_MISMATCH,
                    ERR_INVALID_REQUEST)
from store import DB, LOCK, new_entity, now, now_iso, mutate
from validate import (req_str, req_int, req_enum, req_date, parse_date_strict)
from calc import (record_date_cutoff, principal_as_of, consent_passed)
from domain import (tranches_of, positions_of_tranche, eligible_principal,
                    recompute_posture, waive_linked_alleged_case)

bp = Blueprint("consents", __name__)

SOLICITATION_TERMINAL = ("PASSED", "FAILED", "EXPIRED", "REVOKED")


def _snapshot_weight(indenture_id, account_id, record_date_iso):
    """Holder's aggregate principal as of end of record_date via history."""
    cutoff = record_date_cutoff(record_date_iso)
    if cutoff is None:
        return 0
    total = 0
    for t in tranches_of(indenture_id):
        if t["status"] in ("ACTIVE", "ACCELERATED"):
            for p in positions_of_tranche(t["id"]):
                if p["noteholder_account_id"] == account_id:
                    total += principal_as_of(p, cutoff)
    return total


def _current_weight(indenture_id, account_id):
    from domain import holder_aggregate_principal
    return holder_aggregate_principal(indenture_id, account_id)


def _ballot_weight(sol, account_id):
    if sol["tabulation_basis"] == "RECORD_DATE":
        return _snapshot_weight(sol["indenture_id"], account_id,
                                sol["record_date"])
    return _current_weight(sol["indenture_id"], account_id)


@bp.route("/consent-solicitations", methods=["POST"])
@require_roles("Issuer")
def create_solicitation():
    body = get_body()
    with LOCK:
        indenture_id = body.get("indenture_id")
        ind = DB["indentures"].get(indenture_id) if isinstance(indenture_id, str) else None
        if ind is None:
            raise_err(ERR_NOT_FOUND, "Indenture not found")
        # Rule 3: issuer owns the indenture.
        check_issuer_owns(ind)
        # Rule 4: target obligation reference, when supplied, must exist.
        target_id = body.get("target_obligation_id")
        target = None
        if isinstance(target_id, str):
            target = DB["covenant_obligations"].get(target_id)
            if target is None:
                raise_err(ERR_NOT_FOUND, "CovenantObligation not found")
        # Rule 11: closed-interval window overlap with DRAFT/OPEN siblings;
        # adjacency (shared boundary date) IS a collision.
        rd = parse_date_strict(body.get("record_date"))
        ed = parse_date_strict(body.get("expiry_date"))
        if rd is not None and ed is not None:
            for s in DB["consent_solicitations"].values():
                if (s["indenture_id"] == ind["id"]
                        and s["status"] in ("DRAFT", "OPEN")):
                    s_rd = parse_date_strict(s["record_date"])
                    s_ed = parse_date_strict(s["expiry_date"])
                    if s_rd is None or s_ed is None:
                        continue
                    if rd <= s_ed and s_rd <= ed:  # closed intervals: adjacency collides
                        raise_err(ERR_SOLICITATION_WINDOW_OVERLAP,
                                  "Solicitation window overlaps a DRAFT/OPEN solicitation")
        # Rule 22: WAIVE_COVENANT target must reference the same indenture.
        subject = body.get("subject_type")
        if subject == "WAIVE_COVENANT":
            if target is None:
                raise_err(ERR_TARGET_OBLIGATION_MISMATCH,
                          "target_obligation_id is required for WAIVE_COVENANT")
            if target["indenture_id"] != ind["id"]:
                raise_err(ERR_TARGET_OBLIGATION_MISMATCH,
                          "Target obligation belongs to another indenture")
        # Rule 26: shape.
        req_str(body, "indenture_id")
        subject = req_enum(body, "subject_type", ["AMEND_TERMS", "WAIVE_COVENANT"])
        threshold = req_int(body, "consent_threshold_bps")
        basis = req_enum(body, "tabulation_basis",
                         ["RECORD_DATE", "CURRENT_OUTSTANDING"])
        record_date = req_date(body, "record_date")
        expiry_date = req_date(body, "expiry_date")
        payload = body.get("amendment_payload")
        if subject == "AMEND_TERMS":
            if not isinstance(payload, dict):
                raise_err(ERR_INVALID_REQUEST,
                          "amendment_payload is required for AMEND_TERMS")
        e = new_entity("consent_solicitations")
        e.update({
            "indenture_id": indenture_id,
            "subject_type": subject,
            "target_obligation_id": target_id if subject == "WAIVE_COVENANT" else body.get("target_obligation_id"),
            "amendment_payload": payload if isinstance(payload, dict) else None,
            "consent_threshold_bps": threshold,
            "tabulation_basis": basis,
            "record_date": record_date,
            "expiry_date": expiry_date,
            "ballots": [],
            "consenting_principal_cents": 0,
            "status": "DRAFT",
        })
    return ok(public(e), 201)


@bp.route("/consent-solicitations", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_solicitations():
    return list_response(DB["consent_solicitations"].values(), {
        "indenture_id": request.args.get("indenture_id"),
        "status": request.args.get("status"),
    })


@bp.route("/consent-solicitations/<sid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_solicitation(sid):
    e = DB["consent_solicitations"].get(sid)
    if e is None:
        raise_err(ERR_NOT_FOUND, "ConsentSolicitation not found")
    return ok(public(e))


@bp.route("/consent-solicitations/<sid>/open", methods=["POST"])
@require_roles("TrustOfficer")
def open_solicitation(sid):
    with LOCK:
        sol = DB["consent_solicitations"].get(sid)
        if sol is None:
            raise_err(ERR_NOT_FOUND, "ConsentSolicitation not found")
        if sol["status"] in SOLICITATION_TERMINAL:
            raise_err(ERR_ALREADY_TERMINAL,
                      "Solicitation is terminal (%s)" % sol["status"])
        if sol["status"] != "DRAFT":
            raise_err(ERR_INVALID_STATE, "Only a DRAFT solicitation can open")
        # Rule 17: clock date must be on or before expiry_date.
        ed = parse_date_strict(sol["expiry_date"])
        if ed is not None and now().date() > ed:
            raise_err(ERR_SOLICITATION_EXPIRED, "The solicitation has expired")
        mutate(sol, status="OPEN")
    return ok(public(sol))


@bp.route("/consent-solicitations/<sid>/ballots", methods=["POST"])
@require_roles("Noteholder")
def cast_ballot(sid):
    body = get_body()
    with LOCK:
        # Rule 3: noteholder casts for its own account.
        account_id = body.get("noteholder_account_id")
        if account_id is not None:
            check_noteholder_owns(account_id)
        sol = DB["consent_solicitations"].get(sid)
        if sol is None:
            raise_err(ERR_NOT_FOUND, "ConsentSolicitation not found")
        acc = DB["noteholder_accounts"].get(account_id) if isinstance(account_id, str) else None
        if acc is None:
            raise_err(ERR_NOT_FOUND, "NoteholderAccount not found")
        # Rule 5: solicitation must be OPEN.
        if sol["status"] in SOLICITATION_TERMINAL:
            raise_err(ERR_ALREADY_TERMINAL,
                      "Solicitation is terminal (%s)" % sol["status"])
        if sol["status"] != "OPEN":
            raise_err(ERR_INVALID_STATE, "Solicitation is not OPEN")
        # Rule 9: at most one ballot per (solicitation, account).
        for b in sol["ballots"]:
            if b["noteholder_account_id"] == account_id:
                raise_err(ERR_DUPLICATE_CONSTRAINT,
                          "This account has already cast a ballot")
        # Rule 17: balloting only while clock date <= expiry_date.
        ed = parse_date_strict(sol["expiry_date"])
        if ed is not None and now().date() > ed:
            raise_err(ERR_SOLICITATION_EXPIRED, "The solicitation has expired")
        # Rule 23: holder-of-record eligibility per tabulation basis.
        weight = _ballot_weight(sol, account_id)
        if weight <= 0:
            raise_err(ERR_NO_ELIGIBLE_POSITION,
                      "Balloter holds no eligible principal")
        # Rule 26: shape.
        req_str(body, "noteholder_account_id")
        vote = req_enum(body, "vote", ["CONSENT", "WITHHOLD"])
        sol["ballots"].append({
            "noteholder_account_id": account_id,
            "vote": vote,
            "principal_voted_cents": weight,
            "cast_at": now_iso(),
        })
        consenting = sum(b["principal_voted_cents"] for b in sol["ballots"]
                         if b["vote"] == "CONSENT")
        mutate(sol, consenting_principal_cents=consenting)
    return ok(public(sol), 201)


@bp.route("/consent-solicitations/<sid>/close", methods=["POST"])
@require_roles("TrustOfficer")
def close_solicitation(sid):
    with LOCK:
        sol = DB["consent_solicitations"].get(sid)
        if sol is None:
            raise_err(ERR_NOT_FOUND, "ConsentSolicitation not found")
        if sol["status"] in SOLICITATION_TERMINAL:
            raise_err(ERR_ALREADY_TERMINAL,
                      "Solicitation is terminal (%s)" % sol["status"])
        if sol["status"] != "OPEN":
            raise_err(ERR_INVALID_STATE, "Only an OPEN solicitation can close")
        ed = parse_date_strict(sol["expiry_date"])
        if ed is not None and now().date() > ed:
            # EXPIRED wins over tabulation regardless of the tally.
            mutate(sol, status="EXPIRED")
            return ok(public(sol))
        eligible = eligible_principal(sol["indenture_id"])
        consenting = 0
        for b in sol["ballots"]:
            if b["vote"] == "CONSENT":
                consenting += _ballot_weight(sol, b["noteholder_account_id"])
        passed = consent_passed(consenting, sol["consent_threshold_bps"], eligible)
        mutate(sol, status="PASSED" if passed else "FAILED",
               consenting_principal_cents=consenting)
        if passed:
            ind = DB["indentures"].get(sol["indenture_id"])
            if sol["subject_type"] == "WAIVE_COVENANT":
                ob = DB["covenant_obligations"].get(sol.get("target_obligation_id"))
                if ob is not None and ob["status"] in ("OPEN", "LATE", "BREACHED"):
                    mutate(ob, status="WAIVED")
                    if ind is not None:
                        waive_linked_alleged_case(ind, ob)
                if ind is not None:
                    recompute_posture(ind)
            else:  # AMEND_TERMS
                payload = sol.get("amendment_payload") or {}
                if ind is not None and "annual_admin_fee_cents" in payload:
                    mutate(ind, annual_admin_fee_cents=payload["annual_admin_fee_cents"])
    return ok(public(sol))


@bp.route("/consent-solicitations/<sid>/revoke", methods=["POST"])
@require_roles("Issuer")
def revoke_solicitation(sid):
    with LOCK:
        sol = DB["consent_solicitations"].get(sid)
        if sol is None:
            raise_err(ERR_NOT_FOUND, "ConsentSolicitation not found")
        ind = DB["indentures"].get(sol["indenture_id"])
        check_issuer_owns(ind)
        if sol["status"] in SOLICITATION_TERMINAL:
            raise_err(ERR_ALREADY_TERMINAL,
                      "Solicitation is terminal (%s)" % sol["status"])
        if sol["status"] not in ("DRAFT", "OPEN"):
            raise_err(ERR_INVALID_STATE, "Solicitation cannot be revoked")
        mutate(sol, status="REVOKED")
    return ok(public(sol))
