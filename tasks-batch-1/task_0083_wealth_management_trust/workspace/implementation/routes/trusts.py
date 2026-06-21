"""Trust lifecycle + amendment/revoke/terminate (PRD §3.2, §3.9)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import authenticate, require_role, parse_pagination, paginate
from response import success
from services import serialize
from services.helpers import get_json_body, require_str, require_enum, optional_bool, must_exist
from services import calc
from services.ledger import (
    recompute_account_figures, recompute_k1, recompute_trust_balances,
    recompute_inclusion_ratio, trust_accounts, account_distributions,
)

bp = Blueprint("trusts", __name__)

TRUST_TYPES = {"REVOCABLE", "IRREVOCABLE"}


def _grantor_owns(role, user_id, trust):
    """ERR_NOT_OWNER if a Grantor actor's id doesn't match the trust's grantor."""
    if role == "Grantor" and user_id != trust["grantor_id"]:
        raise err("ERR_NOT_OWNER")


@bp.route("/trusts", methods=["POST"])
def create_trust():
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    body = get_json_body()
    name = require_str(body, "name")
    grantor_id = require_str(body, "grantor_id")
    trust_type = require_enum(body, "trust_type", TRUST_TYPES)
    is_grantor_trust = optional_bool(body, "is_grantor_trust", False)
    cgti = optional_bool(body, "capital_gains_to_income", False)
    must_exist(db.grantors, grantor_id)

    with db.LOCK:
        t = db.base_fields()
        t.update({
            "name": name,
            "grantor_id": grantor_id,
            "trust_type": trust_type,
            "is_grantor_trust": is_grantor_trust,
            "capital_gains_to_income": cgti,
            "status": "DRAFT",
            "principal_balance_cents": 0,
            "income_balance_cents": 0,
            "gst_exemption_allocated_cents": 0,
            "inclusion_ratio": 0.0,
            # internal staging for amendments
            "_pending_cgti": None,
            "_pending_is_grantor_trust": None,
        })
        db.trusts[t["id"]] = t
    return success(serialize.trust(t), status=201)


@bp.route("/trusts/<tid>", methods=["GET"])
def get_trust(tid):
    user_id, role = authenticate()
    require_role(role, {"TrustAdmin", "Grantor", "Trustee"})
    t = must_exist(db.trusts, tid)
    _grantor_owns(role, user_id, t)
    if role == "Trustee" and not _trustee_appointed(user_id, t["id"]):
        raise err("ERR_NOT_OWNER")
    return success(serialize.trust(t))


@bp.route("/trusts", methods=["GET"])
def list_trusts():
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    limit, offset = parse_pagination()
    grantor_id = request.args.get("grantor_id")
    items = list(db.trusts.values())
    if grantor_id is not None:
        items = [t for t in items if t["grantor_id"] == grantor_id]
    page, meta = paginate(items, limit, offset)
    return success([serialize.trust(t) for t in page], pagination=meta)


def _trustee_appointed(trustee_id, trust_id):
    for a in db.trustee_appointments.values():
        if a["trust_id"] == trust_id and a["trustee_id"] == trustee_id and a["status"] == "ACTIVE":
            return True
    return False


# ---- Lifecycle: fund / activate (TrustAdmin) ----
@bp.route("/trusts/<tid>/fund", methods=["POST"])
def fund_trust(tid):
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    t = must_exist(db.trusts, tid)
    with db.LOCK:
        if t["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE")
        has_active = any(
            a["trust_id"] == t["id"] and a["status"] == "ACTIVE"
            for a in db.trustee_appointments.values()
        )
        if not has_active:
            raise err("ERR_INVALID_STATE", "Funding requires at least one ACTIVE trustee appointment.")
        t["status"] = "FUNDED"
        db.touch(t)
    return success(serialize.trust(t))


@bp.route("/trusts/<tid>/activate", methods=["POST"])
def activate_trust(tid):
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    t = must_exist(db.trusts, tid)
    with db.LOCK:
        if t["status"] != "FUNDED":
            raise err("ERR_INVALID_STATE")
        if t["principal_balance_cents"] <= 0:
            raise err("ERR_INVALID_STATE", "Activation requires principal_balance_cents > 0.")
        t["status"] = "ACTIVE"
        db.touch(t)
    return success(serialize.trust(t))


# ---- Amendment loop (Grantor, revocable only) ----
@bp.route("/trusts/<tid>/amendments", methods=["POST"])
def open_amendment(tid):
    user_id, role = authenticate()
    require_role(role, {"Grantor"})
    t = must_exist(db.trusts, tid)
    _grantor_owns(role, user_id, t)
    body = get_json_body()
    # optional staged elections
    set_cgti = body.get("set_capital_gains_to_income")
    set_igt = body.get("set_is_grantor_trust")
    if set_cgti is not None and not isinstance(set_cgti, bool):
        raise err("ERR_VALIDATION", "set_capital_gains_to_income must be a boolean")
    if set_igt is not None and not isinstance(set_igt, bool):
        raise err("ERR_VALIDATION", "set_is_grantor_trust must be a boolean")

    with db.LOCK:
        if t["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE")
        if t["trust_type"] == "IRREVOCABLE":
            raise err("ERR_TRUST_IRREVOCABLE")
        t["_pending_cgti"] = set_cgti
        t["_pending_is_grantor_trust"] = set_igt
        t["status"] = "AMENDMENT_PENDING"
        db.touch(t)
    return success(serialize.trust(t))


@bp.route("/trusts/<tid>/amendments/commit", methods=["POST"])
def commit_amendment(tid):
    user_id, role = authenticate()
    require_role(role, {"Grantor"})
    t = must_exist(db.trusts, tid)
    _grantor_owns(role, user_id, t)
    with db.LOCK:
        if t["status"] != "AMENDMENT_PENDING":
            raise err("ERR_INVALID_STATE")
        # Apply staged elections.
        if t["_pending_cgti"] is not None:
            t["capital_gains_to_income"] = t["_pending_cgti"]
        if t["_pending_is_grantor_trust"] is not None:
            t["is_grantor_trust"] = t["_pending_is_grantor_trust"]
        t["_pending_cgti"] = None
        t["_pending_is_grantor_trust"] = None
        t["status"] = "ACTIVE"
        # Recompute ledger sides for CAPITAL_GAIN receipts, then DNI/K1/balances.
        _reallocate_capital_gain_receipts(t)
        recompute_trust_balances(t)
        recompute_inclusion_ratio(t)
        for acct in trust_accounts(t["id"]):
            recompute_account_figures(acct)
            recompute_k1(acct)
            db.touch(acct)
        db.touch(t)
    return success(serialize.trust(t))


def _reallocate_capital_gain_receipts(trust):
    """On amendment commit, recompute ledger_side of CAPITAL_GAIN receipts."""
    for acct in trust_accounts(trust["id"]):
        for r in db.receipts.values():
            if r["account_id"] != acct["id"]:
                continue
            if r["receipt_kind"] == "CAPITAL_GAIN":
                new_side = calc.receipt_ledger_side("CAPITAL_GAIN", trust["capital_gains_to_income"])
                if r["ledger_side"] != new_side:
                    r["ledger_side"] = new_side
                    db.touch(r)


# ---- Revoke (Grantor, revocable only) ----
@bp.route("/trusts/<tid>/revoke", methods=["POST"])
def revoke_trust(tid):
    user_id, role = authenticate()
    require_role(role, {"Grantor"})
    t = must_exist(db.trusts, tid)
    _grantor_owns(role, user_id, t)
    with db.LOCK:
        if t["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE")
        if t["trust_type"] == "IRREVOCABLE":
            raise err("ERR_TRUST_IRREVOCABLE")
        _close_open_accounts(t)
        t["status"] = "REVOKED"
        db.touch(t)
    return success(serialize.trust(t))


# ---- Terminate (TrustAdmin, two steps) ----
@bp.route("/trusts/<tid>/terminate", methods=["POST"])
def terminate_trust(tid):
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    t = must_exist(db.trusts, tid)
    with db.LOCK:
        if t["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE")
        # no unsettled (PROPOSED/APPROVED) distribution on any account
        for acct in trust_accounts(t["id"]):
            for d in account_distributions(acct["id"]):
                if d["status"] in ("PROPOSED", "APPROVED"):
                    raise err("ERR_UNSETTLED_DISTRIBUTION")
        _close_open_accounts(t)
        t["status"] = "TERMINATING"
        db.touch(t)
    return success(serialize.trust(t))


@bp.route("/trusts/<tid>/terminate/finalize", methods=["POST"])
def finalize_termination(tid):
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    t = must_exist(db.trusts, tid)
    with db.LOCK:
        if t["status"] != "TERMINATING":
            raise err("ERR_INVALID_STATE")
        accts = trust_accounts(t["id"])
        if any(a["status"] != "FILED" for a in accts):
            raise err("ERR_INVALID_STATE", "Every account must be FILED before finalizing.")
        _spawn_termination_gst_events(t)
        t["status"] = "TERMINATED"
        db.touch(t)
    return success(serialize.trust(t))


def _close_open_accounts(trust):
    """CASCADE: every OPEN TrustAccount on this trust -> CLOSED (PRD §2.5, §3.7, §3.9)."""
    for acct in trust_accounts(trust["id"]):
        if acct["status"] == "OPEN":
            acct["status"] = "CLOSED"
            recompute_account_figures(acct)
            recompute_k1(acct)
            db.touch(acct)


def _spawn_termination_gst_events(trust):
    """For each skip beneficiary, create a TAXABLE_TERMINATION GstEvent (PRD §3.9)."""
    skip_bens = [
        b for b in db.beneficiaries.values()
        if b["grantor_id"] == trust["grantor_id"] and b["is_skip_person"]
    ]
    if not skip_bens:
        return
    skip_bens.sort(key=lambda b: b["_seq"])
    n = len(skip_bens)
    principal = trust["principal_balance_cents"]
    base_share = principal // n
    remainder = principal - base_share * n
    snapshot = trust["inclusion_ratio"]
    for idx, b in enumerate(skip_bens):
        amount = base_share + (remainder if idx == 0 else 0)
        ev = db.base_fields()
        ev.update({
            "trust_id": trust["id"],
            "beneficiary_id": b["id"],
            "distribution_id": None,
            "event_type": "TAXABLE_TERMINATION",
            "taxable_amount_cents": amount,
            "inclusion_ratio_snapshot": snapshot,
            "gst_tax_cents": calc.gst_tax(amount, snapshot),
        })
        db.gst_events[ev["id"]] = ev
