"""Distribution lifecycle: propose/approve/reject/pay/reverse (PRD §3.5)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import authenticate, require_role, parse_pagination, paginate
from response import success
from services import serialize, calc
from services.helpers import get_json_body, require_str, require_int, require_enum, must_exist
from services.ledger import recompute_after_ledger_mutation

bp = Blueprint("distributions", __name__)

DIST_KINDS = {"MANDATORY", "DISCRETIONARY"}


def _trustee_appointed(trustee_id, trust_id):
    for ap in db.trustee_appointments.values():
        if ap["trust_id"] == trust_id and ap["trustee_id"] == trustee_id and ap["status"] == "ACTIVE":
            return True
    return False


@bp.route("/accounts/<aid>/distributions", methods=["POST"])
def propose_distribution(aid):
    user_id, role = authenticate()
    require_role(role, {"Trustee"})
    a = must_exist(db.accounts, aid)
    t = db.trusts[a["trust_id"]]
    body = get_json_body()
    beneficiary_id = require_str(body, "beneficiary_id")
    amount_cents = require_int(body, "amount_cents")
    distribution_kind = require_enum(body, "distribution_kind", DIST_KINDS)
    proposer_trustee_id = require_str(body, "proposer_trustee_id")
    # existence of FKs (priority 3)
    beneficiary = must_exist(db.beneficiaries, beneficiary_id)
    must_exist(db.trustees, proposer_trustee_id)
    # ownership: acting trustee must be appointed to the owning trust (priority 4)
    if not _trustee_appointed(user_id, t["id"]):
        raise err("ERR_NOT_OWNER")

    with db.LOCK:
        # state (priority 5): period must be OPEN -> else ERR_PERIOD_FROZEN (priority 10)
        if a["status"] != "OPEN":
            raise err("ERR_PERIOD_FROZEN")
        if amount_cents <= 0:
            raise err("ERR_INVALID_AMOUNT")
        if beneficiary["grantor_id"] != t["grantor_id"]:
            raise err("ERR_GRANTOR_MISMATCH")
        d = db.base_fields()
        d.update({
            "account_id": aid,
            "beneficiary_id": beneficiary_id,
            "amount_cents": amount_cents,
            "distribution_kind": distribution_kind,
            "proposer_trustee_id": proposer_trustee_id,
            "approver_trustee_id": None,
            "status": "PROPOSED",
            "funded_from_income_cents": 0,
            "funded_from_principal_cents": 0,
            "dni_carried_amount_cents": 0,
            "_gst_event_id": None,
        })
        db.distributions[d["id"]] = d
    return success(serialize.distribution(d), status=201)


@bp.route("/distributions/<did>", methods=["GET"])
def get_distribution(did):
    user_id, role = authenticate()
    require_role(role, {"TrustAdmin", "Trustee"})
    d = must_exist(db.distributions, did)
    _trustee_scope_dist(role, user_id, d)
    return success(serialize.distribution(d))


@bp.route("/accounts/<aid>/distributions", methods=["GET"])
def list_account_distributions(aid):
    user_id, role = authenticate()
    require_role(role, {"TrustAdmin", "Trustee"})
    a = must_exist(db.accounts, aid)
    if role == "Trustee" and not _trustee_appointed(user_id, a["trust_id"]):
        raise err("ERR_NOT_OWNER")
    limit, offset = parse_pagination()
    beneficiary_id = request.args.get("beneficiary_id")
    items = [d for d in db.distributions.values() if d["account_id"] == aid]
    if beneficiary_id is not None:
        items = [d for d in items if d["beneficiary_id"] == beneficiary_id]
    page, meta = paginate(items, limit, offset)
    return success([serialize.distribution(d) for d in page], pagination=meta)


@bp.route("/distributions", methods=["GET"])
def list_distributions():
    _, role = authenticate()
    require_role(role, {"TrustAdmin", "Trustee"})
    limit, offset = parse_pagination()
    beneficiary_id = request.args.get("beneficiary_id")
    proposer = request.args.get("proposer_trustee_id")
    approver = request.args.get("approver_trustee_id")
    items = list(db.distributions.values())
    if beneficiary_id is not None:
        items = [d for d in items if d["beneficiary_id"] == beneficiary_id]
    if proposer is not None:
        items = [d for d in items if d["proposer_trustee_id"] == proposer]
    if approver is not None:
        items = [d for d in items if d["approver_trustee_id"] == approver]
    page, meta = paginate(items, limit, offset)
    return success([serialize.distribution(d) for d in page], pagination=meta)


@bp.route("/distributions/<did>/approve", methods=["POST"])
def approve_distribution(did):
    user_id, role = authenticate()
    require_role(role, {"Trustee"})
    d = must_exist(db.distributions, did)
    a = db.accounts[d["account_id"]]
    t = db.trusts[a["trust_id"]]
    # ownership: acting trustee appointed to trust
    if not _trustee_appointed(user_id, t["id"]):
        raise err("ERR_NOT_OWNER")
    with db.LOCK:
        if d["status"] != "PROPOSED":
            raise err("ERR_INVALID_STATE")
        # segregation of duties (priority 7) before period-frozen (priority 10)
        if user_id == d["proposer_trustee_id"]:
            raise err("ERR_SEGREGATION_OF_DUTIES")
        if a["status"] != "OPEN":
            raise err("ERR_PERIOD_FROZEN")
        d["approver_trustee_id"] = user_id
        d["status"] = "APPROVED"
        db.touch(d)
    return success(serialize.distribution(d))


@bp.route("/distributions/<did>/reject", methods=["POST"])
def reject_distribution(did):
    user_id, role = authenticate()
    require_role(role, {"Trustee"})
    d = must_exist(db.distributions, did)
    a = db.accounts[d["account_id"]]
    t = db.trusts[a["trust_id"]]
    if not _trustee_appointed(user_id, t["id"]):
        raise err("ERR_NOT_OWNER")
    with db.LOCK:
        if d["status"] != "PROPOSED":
            raise err("ERR_INVALID_STATE")
        d["status"] = "REJECTED"
        db.touch(d)
    return success(serialize.distribution(d))


@bp.route("/distributions/<did>/pay", methods=["POST"])
def pay_distribution(did):
    user_id, role = authenticate()
    require_role(role, {"Trustee"})
    d = must_exist(db.distributions, did)
    a = db.accounts[d["account_id"]]
    t = db.trusts[a["trust_id"]]
    if not _trustee_appointed(user_id, t["id"]):
        raise err("ERR_NOT_OWNER")
    with db.LOCK:
        if d["status"] != "APPROVED":
            raise err("ERR_INVALID_STATE")
        if t["status"] not in ("ACTIVE", "TERMINATING"):
            raise err("ERR_INVALID_STATE", "Owning trust cannot pay in its current state.")
        if a["status"] != "OPEN":
            raise err("ERR_PERIOD_FROZEN")
        if d["amount_cents"] > t["principal_balance_cents"] + t["income_balance_cents"]:
            raise err("ERR_INSUFFICIENT_CORPUS")

        # Fund income-first.
        from_income = min(d["amount_cents"], t["income_balance_cents"])
        from_principal = d["amount_cents"] - from_income
        d["funded_from_income_cents"] = from_income
        d["funded_from_principal_cents"] = from_principal
        d["status"] = "PAID"

        # Cascade: balances -> account figures (carry-out) -> K1.
        recompute_after_ledger_mutation(a, t)

        # GST event if recipient is a skip person.
        beneficiary = db.beneficiaries[d["beneficiary_id"]]
        if beneficiary["is_skip_person"]:
            snapshot = t["inclusion_ratio"]
            ev = db.base_fields()
            ev.update({
                "trust_id": t["id"],
                "beneficiary_id": beneficiary["id"],
                "distribution_id": d["id"],
                "event_type": "TAXABLE_DISTRIBUTION",
                "taxable_amount_cents": d["amount_cents"],
                "inclusion_ratio_snapshot": snapshot,
                "gst_tax_cents": calc.gst_tax(d["amount_cents"], snapshot),
            })
            db.gst_events[ev["id"]] = ev
            d["_gst_event_id"] = ev["id"]

        db.touch(d)
    return success(serialize.distribution(d))


@bp.route("/distributions/<did>/reverse", methods=["POST"])
def reverse_distribution(did):
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    d = must_exist(db.distributions, did)
    a = db.accounts[d["account_id"]]
    t = db.trusts[a["trust_id"]]
    with db.LOCK:
        if d["status"] != "PAID":
            raise err("ERR_INVALID_STATE")
        if a["status"] != "OPEN":
            raise err("ERR_PERIOD_FROZEN")
        # Compensation: zero the funded portions so the balance recompute backs them out.
        d["funded_from_income_cents"] = 0
        d["funded_from_principal_cents"] = 0
        d["dni_carried_amount_cents"] = 0
        d["status"] = "REVERSED"

        # Delete any GST event spawned at payment.
        if d["_gst_event_id"] is not None:
            db.gst_events.pop(d["_gst_event_id"], None)
            d["_gst_event_id"] = None

        recompute_after_ledger_mutation(a, t)
        db.touch(d)
    return success(serialize.distribution(d))


def _trustee_scope_dist(role, user_id, d):
    if role != "Trustee":
        return
    a = db.accounts[d["account_id"]]
    if not _trustee_appointed(user_id, a["trust_id"]):
        raise err("ERR_NOT_OWNER")
