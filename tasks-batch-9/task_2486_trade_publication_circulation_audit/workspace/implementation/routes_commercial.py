"""Advertiser contracts, make-good obligations, snapshot adjudication."""
from flask import Blueprint

import calc
import validation as V
from auth import (ROLE_ADVERTISER_CONTACT, ROLE_CIRCULATION_AUDITOR,
                  ROLE_CIRCULATION_MANAGER, ROLE_PUBLISHER_EXECUTIVE,
                  current_role, current_user, endpoint)
from envelope import created, ok, paginate
from errors import ApiError
from lookups import get_contract, get_make_good, get_publication, get_snapshot
from store import (base_record, collection_sorted, db, now, serialize, touch)

commercial_bp = Blueprint("commercial", __name__)

CONTRACT_READ_ROLES = (ROLE_CIRCULATION_MANAGER, ROLE_CIRCULATION_AUDITOR,
                       ROLE_PUBLISHER_EXECUTIVE)
MAKEGOOD_READ_ROLES = (ROLE_CIRCULATION_MANAGER, ROLE_PUBLISHER_EXECUTIVE,
                       ROLE_ADVERTISER_CONTACT)
MAKEGOOD_LIST_ROLES = (ROLE_CIRCULATION_MANAGER, ROLE_CIRCULATION_AUDITOR,
                       ROLE_PUBLISHER_EXECUTIVE)
MAKEGOOD_TERMINAL = ("ACCEPTED", "WAIVED", "VOID")


def _require_owner(obligation):
    """PRD 2.1: an AdvertiserContact's X-User-ID is the contract it speaks for."""
    if current_role() != ROLE_ADVERTISER_CONTACT:
        return
    if current_user() != obligation["contract_id"]:
        raise ApiError("ERR_NOT_CONTRACT_OWNER",
                       "This make-good belongs to another contract.")


# --------------------------------------------------------------------------
# advertiser contracts
# --------------------------------------------------------------------------
@commercial_bp.route("/circulation/advertiser-contracts", methods=["POST"])
@endpoint(ROLE_CIRCULATION_MANAGER)
def create_contract():
    payload = V.body()
    pub = get_publication(payload.get("publication_id"))
    fields = V.parse(payload, [
        V.f_id("publication_id"),
        V.f_str("advertiser_name", max_len=200),
        V.f_int("insertion_count", minimum=1),
        V.f_int("gross_rate_cents_per_insertion", minimum=1),
        V.f_int("guaranteed_rate_base", minimum=1),
        V.f_pct("shortfall_tolerance_pct", required=False, default=V.round_half_up("2.00", 2)),
    ])

    pool = fields["insertion_count"] * fields["gross_rate_cents_per_insertion"]
    contract = base_record()
    contract.update({
        "publication_id": pub["id"],
        "advertiser_name": fields["advertiser_name"],
        "insertion_count": fields["insertion_count"],
        "gross_rate_cents_per_insertion": fields["gross_rate_cents_per_insertion"],
        "guaranteed_rate_base": fields["guaranteed_rate_base"],
        "shortfall_tolerance_pct": fields["shortfall_tolerance_pct"],
        "makegood_credit_pool_cents": pool,
        "makegood_credit_committed_cents": 0,
        "makegood_credit_waived_cents": 0,
        "makegood_credit_available_cents": pool,
        "guarantee_status": "ACTIVE",
    })
    db.contracts[contract["id"]] = contract
    return created(serialize(contract))


@commercial_bp.route("/circulation/advertiser-contracts/<contract_id>", methods=["GET"])
@endpoint(*CONTRACT_READ_ROLES)
def read_contract(contract_id):
    return ok(serialize(get_contract(contract_id)))


@commercial_bp.route("/circulation/advertiser-contracts", methods=["GET"])
@endpoint(*CONTRACT_READ_ROLES)
def list_contracts():
    publication_id = V.filter_str("publication_id")
    guarantee_status = V.filter_enum("guarantee_status", V.GUARANTEE_STATUSES)
    rows = list(db.contracts.values())
    if publication_id:
        rows = [c for c in rows if c["publication_id"] == publication_id]
    if guarantee_status:
        rows = [c for c in rows if c["guarantee_status"] == guarantee_status]
    return paginate(collection_sorted(rows))


# --------------------------------------------------------------------------
# make-good obligations
# --------------------------------------------------------------------------
@commercial_bp.route("/circulation/make-goods/<mg_id>", methods=["GET"])
@endpoint(*MAKEGOOD_READ_ROLES)
def read_make_good(mg_id):
    obligation = get_make_good(mg_id)
    _require_owner(obligation)
    return ok(serialize(obligation))


@commercial_bp.route("/circulation/make-goods", methods=["GET"])
@endpoint(*MAKEGOOD_LIST_ROLES)
def list_make_goods():
    contract_id = V.filter_str("contract_id")
    statement_id = V.filter_str("statement_id")
    status = V.filter_enum("status", V.MAKEGOOD_STATUSES)
    rows = list(db.make_goods.values())
    if contract_id:
        rows = [m for m in rows if m["contract_id"] == contract_id]
    if statement_id:
        rows = [m for m in rows if m["statement_id"] == statement_id]
    if status:
        rows = [m for m in rows if m["status"] == status]
    return paginate(collection_sorted(rows))


@commercial_bp.route("/circulation/make-goods/<mg_id>/offer", methods=["POST"])
@endpoint(ROLE_CIRCULATION_MANAGER)
def offer_make_good(mg_id):
    obligation = get_make_good(mg_id)
    payload = V.body()
    V.parse(payload, [V.f_str("offer_note", required=False, max_len=1000, default=None)])

    if obligation["status"] in MAKEGOOD_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "This obligation has already reached %s." % obligation["status"])
    if obligation["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Only a PENDING obligation may be offered.")

    contract = db.contracts.get(obligation["contract_id"])
    if contract is None or contract["guarantee_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE",
                       "The owning contract is no longer ACTIVE.")
    stmt = db.statements.get(obligation["statement_id"])
    if stmt is None or stmt["status"] not in ("FILED", "AUDIT_CLEARED"):
        raise ApiError("ERR_INVALID_STATE",
                       "The underlying statement must be FILED or AUDIT_CLEARED.")

    obligation["status"] = "OFFERED"
    obligation["offered_at"] = now()
    touch(obligation)
    return ok(serialize(obligation))


@commercial_bp.route("/circulation/make-goods/<mg_id>/accept", methods=["POST"])
@endpoint(ROLE_ADVERTISER_CONTACT)
def accept_make_good(mg_id):
    obligation = get_make_good(mg_id)
    _require_owner(obligation)
    payload = V.body()
    V.parse(payload, [V.f_str("acceptance_note", required=False, max_len=1000, default=None)])

    if obligation["status"] in MAKEGOOD_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "This obligation has already reached %s." % obligation["status"])
    if obligation["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", "Only an OFFERED obligation may be accepted.")

    contract = db.contracts.get(obligation["contract_id"])
    if contract is None or contract["guarantee_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "The owning contract is no longer ACTIVE.")
    stmt = db.statements.get(obligation["statement_id"])
    if stmt is None or stmt["status"] in ("RESTATEMENT_REQUIRED", "SUPERSEDED"):
        raise ApiError("ERR_INVALID_STATE",
                       "The underlying statement has been withdrawn from audit.")

    obligation["status"] = "ACCEPTED"
    obligation["accepted_at"] = now()
    touch(obligation)
    return ok(serialize(obligation))


@commercial_bp.route("/circulation/make-goods/<mg_id>/waive", methods=["POST"])
@endpoint(ROLE_PUBLISHER_EXECUTIVE)
def waive_make_good(mg_id):
    obligation = get_make_good(mg_id)
    payload = V.body()
    fields = V.parse(payload, [V.f_str("waiver_reason", max_len=1000)])

    if obligation["status"] in MAKEGOOD_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "This obligation has already reached %s." % obligation["status"])
    if obligation["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", "Only an OFFERED obligation may be waived.")

    obligation["status"] = "WAIVED"
    obligation["closed_reason"] = fields["waiver_reason"]
    touch(obligation)

    contract = db.contracts.get(obligation["contract_id"])
    if contract is not None:
        calc.recompute_contract_ledger(contract)
        touch(contract)
    return ok(serialize(obligation))


# --------------------------------------------------------------------------
# POST /circulation/digital-snapshots/{id}/validate
# --------------------------------------------------------------------------
@commercial_bp.route("/circulation/digital-snapshots/<snap_id>/validate", methods=["POST"])
@endpoint(ROLE_CIRCULATION_AUDITOR)
def validate_snapshot(snap_id):
    snap = get_snapshot(snap_id)
    payload = V.body()
    fields = V.parse(payload, [V.f_enum("decision", V.VALIDATE_DECISIONS)])

    if snap["status"] != "RECORDED":
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "This snapshot has already been adjudicated as %s." % snap["status"])
    if fields["decision"] == "VALIDATE" and snap["source"] != "THIRD_PARTY_CERTIFIED":
        raise ApiError("ERR_DIGITAL_SOURCE_UNCERTIFIED",
                       "Only a THIRD_PARTY_CERTIFIED snapshot may be validated.")

    snap["status"] = "VALIDATED" if fields["decision"] == "VALIDATE" else "REJECTED"
    snap["validated_by_user_id"] = current_user()
    touch(snap)
    return ok(serialize(snap))
