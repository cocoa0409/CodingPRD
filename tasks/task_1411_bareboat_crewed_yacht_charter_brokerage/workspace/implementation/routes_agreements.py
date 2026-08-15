"""Routes: charter agreements (two state axes), escrow reads, APA position,
commission statements, agreement-scoped blocks (PRD §3.4, §3.5, §3.7-§3.9).
"""

from flask import Blueprint, g, request

from httpkit import (api_err, as_int, body_json, get_or_404, req_field,
                     require_roles, respond_object, respond_paginated,
                     sort_created)
from serializers import (ser_agreement, ser_block, ser_escrow, ser_movement,
                         ser_statement)
from services import (cancel_cascade, complete_cascade, escrow_of,
                      expenses_of, post_movement, void_agreement)
from store import clock, db, mutate
from util import date_obj

bp = Blueprint("agreements", __name__)


def _get_agreement(aid):
    return get_or_404("charter_agreements", aid, "CharterAgreement")


def _sign_party_check(agr):
    if g.role == "Client":
        if g.user_id != agr["client_id"]:
            raise api_err("ERR_FORBIDDEN", "Caller is not the agreement's client")
    elif g.role == "CentralAgent":
        if g.user_id != agr["central_agent_id"]:
            raise api_err(
                "ERR_FORBIDDEN", "Caller is not the agreement's central agent"
            )
    else:
        raise api_err("ERR_FORBIDDEN", "Role not authorized for this endpoint")


def _client_side_check(agr):
    if g.role == "Client":
        if g.user_id != agr["client_id"]:
            raise api_err("ERR_FORBIDDEN", "Caller is not the agreement's client")
    elif g.role == "RetailBroker":
        if g.user_id != agr["retail_broker_id"]:
            raise api_err(
                "ERR_FORBIDDEN", "Caller is not the agreement's retail broker"
            )
    else:
        raise api_err("ERR_FORBIDDEN", "Role not authorized for this endpoint")


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

@bp.route("/charter-agreements/<aid>", methods=["GET"])
def get_agreement(aid):
    agr = _get_agreement(aid)
    return respond_object(ser_agreement(agr))


@bp.route("/charter-agreements", methods=["GET"])
def list_agreements():
    items = list(db["charter_agreements"].values())
    for f in ("charter_request_id", "client_id", "yacht_id", "operator_id",
              "retail_broker_id", "central_agent_id", "status", "funds_status"):
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if a[f] == v]
    return respond_paginated([ser_agreement(a) for a in sort_created(items)])


@bp.route("/charter-agreements/<aid>/escrow", methods=["GET"])
def get_agreement_escrow(aid):
    agr = _get_agreement(aid)
    esc = escrow_of(agr["id"])
    items = [ser_escrow(esc)] if esc is not None else []
    return respond_paginated(items)


@bp.route("/escrow-accounts/<eid>", methods=["GET"])
def get_escrow(eid):
    esc = get_or_404("escrow_accounts", eid, "EscrowAccount")
    return respond_object(ser_escrow(esc))


@bp.route("/escrow-accounts/<eid>/movements", methods=["GET"])
def list_movements(eid):
    get_or_404("escrow_accounts", eid, "EscrowAccount")
    items = [
        m for m in db["escrow_movements"].values()
        if m["escrow_account_id"] == eid
    ]
    for f in ("movement_type", "bucket"):
        v = request.args.get(f)
        if v is not None:
            items = [m for m in items if m[f] == v]
    # posted (chronological) order
    items = sorted(items, key=lambda m: m["_seq"])
    return respond_paginated([ser_movement(m) for m in items])


@bp.route("/charter-agreements/<aid>/apa-position", methods=["GET"])
def apa_position(aid):
    agr = _get_agreement(aid)
    esc = escrow_of(agr["id"])
    held_apa = esc["held_apa_cents"] if esc is not None else 0
    apa_expenses = [e for e in expenses_of(agr["id"]) if e["bucket"] == "APA"]
    provisional = sum(
        e["amount_cents"] for e in apa_expenses
        if e["status"] in ("PENDING", "APPROVED")
    )
    final_spent = sum(
        e["amount_cents"] for e in apa_expenses if e["status"] == "APPROVED"
    )
    return respond_object({
        "held_apa_cents": held_apa,
        "provisional_apa_committed_cents": provisional,
        "final_apa_spent_cents": final_spent,
        "projected_apa_return_cents": held_apa - provisional,
        "final_apa_return_cents": held_apa - final_spent,
    })


@bp.route("/charter-agreements/<aid>/commission-statements", methods=["GET"])
def list_statements(aid):
    agr = _get_agreement(aid)
    items = [
        s for s in db["commission_statements"].values()
        if s["charter_agreement_id"] == agr["id"]
    ]
    return respond_paginated([ser_statement(s) for s in sort_created(items)])


@bp.route("/charter-agreements/<aid>/availability-blocks", methods=["GET"])
def list_agreement_blocks(aid):
    agr = _get_agreement(aid)
    items = [
        b for b in db["availability_blocks"].values()
        if b.get("charter_agreement_id") == agr["id"]
    ]
    v = request.args.get("status")
    if v is not None:
        items = [b for b in items if b["status"] == v]
    return respond_paginated([ser_block(b) for b in sort_created(items)])


# ---------------------------------------------------------------------------
# Signatures / void (PRD §3.4)
# ---------------------------------------------------------------------------

@bp.route("/charter-agreements/<aid>/sign", methods=["POST"])
def sign_agreement(aid):
    require_roles("Client", "CentralAgent")
    agr = _get_agreement(aid)
    _sign_party_check(agr)
    if agr["status"] != "PENDING_SIGNATURES":
        raise api_err(
            "ERR_INVALID_STATE", "Agreement is not PENDING_SIGNATURES"
        )
    if g.role == "Client" and agr["client_signed_at"] is not None:
        raise api_err("ERR_INVALID_STATE", "Client has already signed")
    if g.role == "CentralAgent" and agr["central_agent_signed_at"] is not None:
        raise api_err("ERR_INVALID_STATE", "Central agent has already signed")
    # Insurance gate sits at the state-validity tier for sign (PRD §2.11)
    verified = any(
        c["charter_agreement_id"] == agr["id"] and c["status"] == "VERIFIED"
        for c in db["insurance_certificates"].values()
    )
    if not verified:
        raise api_err(
            "ERR_INSURANCE_NOT_VERIFIED",
            "A VERIFIED insurance certificate is required before signing",
        )
    if g.role == "Client":
        agr["client_signed_at"] = clock.now()
    else:
        agr["central_agent_signed_at"] = clock.now()
    if agr["client_signed_at"] is not None and agr["central_agent_signed_at"] is not None:
        agr["status"] = "SIGNED"
    mutate(agr)
    return respond_object(ser_agreement(agr))


@bp.route("/charter-agreements/<aid>/void", methods=["POST"])
def void_agreement_route(aid):
    require_roles("CentralAgent")
    agr = _get_agreement(aid)
    if g.user_id != agr["central_agent_id"]:
        raise api_err(
            "ERR_FORBIDDEN", "Caller is not the agreement's central agent"
        )
    if agr["status"] != "PENDING_SIGNATURES":
        raise api_err(
            "ERR_INVALID_STATE", "Agreement is not PENDING_SIGNATURES"
        )
    if agr["client_signed_at"] is not None or agr["central_agent_signed_at"] is not None:
        raise api_err(
            "ERR_INVALID_STATE", "Cannot void after a signature has been recorded"
        )
    void_agreement(agr)
    return respond_object(ser_agreement(agr))


# ---------------------------------------------------------------------------
# Funding (PRD §3.5)
# ---------------------------------------------------------------------------

@bp.route("/charter-agreements/<aid>/fund", methods=["POST"])
def fund_agreement(aid):
    require_roles("Client", "RetailBroker")
    agr = _get_agreement(aid)
    _client_side_check(agr)
    if agr["status"] != "SIGNED":
        raise api_err("ERR_INVALID_STATE", "Funding requires status SIGNED")
    body = body_json()
    tranche = req_field(body, "tranche")
    if tranche not in ("SIGNING", "FINAL"):
        raise api_err("ERR_INVALID_REQUEST", "tranche must be SIGNING or FINAL")
    amount = as_int(req_field(body, "amount_cents"), "amount_cents")
    if amount < 0:
        raise api_err("ERR_INVALID_REQUEST", "amount_cents must be non-negative")

    # Sequencing is checked before the amount (PRD §3.5)
    if tranche == "SIGNING" and agr["funds_status"] != "UNFUNDED":
        raise api_err(
            "ERR_FUNDING_TRANCHE_OUT_OF_ORDER",
            "SIGNING requires funds_status UNFUNDED",
        )
    if tranche == "FINAL" and agr["funds_status"] != "DEPOSIT_HELD":
        raise api_err(
            "ERR_FUNDING_TRANCHE_OUT_OF_ORDER",
            "FINAL requires funds_status DEPOSIT_HELD",
        )

    esc = escrow_of(agr["id"])
    fee = agr["charter_fee_cents"]
    sp = agr["signing_due_cents"] - agr["security_deposit_cents"]
    if tranche == "SIGNING":
        if amount != agr["signing_due_cents"]:
            raise api_err(
                "ERR_FUNDING_AMOUNT_MISMATCH",
                "amount_cents must equal signing_due_cents",
            )
        post_movement(esc, "CLIENT_FUND", "CHARTER_FEE", sp,
                      "SIGNING tranche: charter fee part")
        post_movement(esc, "CLIENT_FUND", "DEPOSIT",
                      agr["security_deposit_cents"],
                      "SIGNING tranche: security deposit")
        agr["funds_status"] = "DEPOSIT_HELD"
    else:
        if amount != agr["final_due_cents"]:
            raise api_err(
                "ERR_FUNDING_AMOUNT_MISMATCH",
                "amount_cents must equal final_due_cents",
            )
        post_movement(esc, "CLIENT_FUND", "CHARTER_FEE", fee - sp,
                      "FINAL tranche: charter fee remainder")
        post_movement(esc, "CLIENT_FUND", "APA", agr["apa_amount_cents"],
                      "FINAL tranche: APA")
        if agr["gratuity_pledged_cents"] > 0:
            post_movement(esc, "CLIENT_FUND", "GRATUITY",
                          agr["gratuity_pledged_cents"],
                          "FINAL tranche: crew gratuity")
        agr["funds_status"] = "FULLY_FUNDED"
    mutate(esc)
    mutate(agr)
    return respond_object(ser_escrow(esc))


# ---------------------------------------------------------------------------
# Departure + completion + cancellation (PRD §3.7-§3.9)
# ---------------------------------------------------------------------------

@bp.route("/charter-agreements/<aid>/start-prep", methods=["POST"])
def start_prep(aid):
    require_roles("Operator")
    agr = _get_agreement(aid)
    if agr["operator_id"] != g.user_id:
        raise api_err("ERR_FORBIDDEN", "Caller does not own the yacht")
    if agr["status"] != "SIGNED":
        raise api_err("ERR_INVALID_STATE", "Agreement is not SIGNED")
    from services import legs_of
    if any(l["status"] != "PERMITTED" for l in legs_of(agr["id"])):
        raise api_err(
            "ERR_PERMIT_NOT_GRANTED", "Every itinerary leg must be PERMITTED"
        )
    if agr["funds_status"] != "FULLY_FUNDED":
        raise api_err(
            "ERR_ESCROW_INSUFFICIENT", "start-prep requires funds FULLY_FUNDED"
        )
    agr["status"] = "IN_PREP"
    mutate(agr)
    return respond_object(ser_agreement(agr))


@bp.route("/charter-agreements/<aid>/embark", methods=["POST"])
def embark(aid):
    require_roles("Operator")
    agr = _get_agreement(aid)
    if agr["operator_id"] != g.user_id:
        raise api_err("ERR_FORBIDDEN", "Caller does not own the yacht")
    if agr["status"] != "IN_PREP":
        raise api_err("ERR_INVALID_STATE", "Agreement is not IN_PREP")
    if clock.now().date() < date_obj(agr["start_date"]):
        raise api_err(
            "ERR_INVALID_REQUEST", "Cannot embark before the charter start_date"
        )
    agr["status"] = "UNDERWAY"
    mutate(agr)
    return respond_object(ser_agreement(agr))


@bp.route("/charter-agreements/<aid>/complete", methods=["POST"])
def complete(aid):
    require_roles("Operator", "CentralAgent")
    agr = _get_agreement(aid)
    if g.role == "Operator":
        if agr["operator_id"] != g.user_id:
            raise api_err("ERR_FORBIDDEN", "Caller does not own the yacht")
    else:
        if agr["central_agent_id"] != g.user_id:
            raise api_err(
                "ERR_FORBIDDEN", "Caller is not the agreement's central agent"
            )
    if agr["status"] != "UNDERWAY":
        raise api_err("ERR_INVALID_STATE", "Agreement is not UNDERWAY")
    if clock.now().date() < date_obj(agr["end_date"]):
        raise api_err(
            "ERR_INVALID_REQUEST", "Cannot complete before the charter end_date"
        )
    complete_cascade(agr)
    return respond_object(ser_agreement(agr))


@bp.route("/charter-agreements/<aid>/cancel", methods=["POST"])
def cancel(aid):
    require_roles("Client", "RetailBroker", "CentralAgent")
    agr = _get_agreement(aid)
    party_ids = {
        "Client": agr["client_id"],
        "RetailBroker": agr["retail_broker_id"],
        "CentralAgent": agr["central_agent_id"],
    }
    if g.user_id != party_ids[g.role]:
        raise api_err("ERR_FORBIDDEN", "Caller is not a party to this deal")
    if agr["status"] not in ("PENDING_SIGNATURES", "SIGNED", "IN_PREP"):
        raise api_err(
            "ERR_INVALID_STATE",
            "Cancel requires PENDING_SIGNATURES, SIGNED or IN_PREP",
        )
    cancel_cascade(agr)
    return respond_object(ser_agreement(agr))
