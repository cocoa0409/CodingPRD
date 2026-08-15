from flask import Blueprint, request

from auth import parse_auth, require_role, check_ownership
from db import store
from envelope import ok, paginate
from errors import (not_found, invalid_request, conflict, ERR_INVALID_STATE,
                    ERR_OPEN_MARGIN_CALL, ERR_COLLATERAL_SHORTFALL,
                    ERR_POSTING_NOT_DRAWABLE)
from routes.participants import get_participant
from util import (get_body, check_unknown, req_int, req_enum, new_record,
                  serialize, sort_key, touch)
from services import credit

bp = Blueprint("postings", __name__)

INSTRUMENTS = ("CASH", "LETTER_OF_CREDIT")


def get_posting(pid):
    p = store.postings.get(pid)
    if p is None:
        raise not_found("collateral posting not found")
    return p


@bp.post("/market/participants/<participantId>/postings")
def create_posting(participantId):
    auth = parse_auth()
    require_role(auth, ["CreditOfficer"])
    body = get_body()
    check_unknown(body, {"amount_cents", "instrument_type"})
    amount = req_int(body, "amount_cents", minimum=1)
    instrument = req_enum(body, "instrument_type", INSTRUMENTS)
    participant = get_participant(participantId)
    check_ownership(auth, participant["id"])
    rec = new_record()
    rec.update({
        "market_participant_id": participant["id"],
        "amount_cents": amount,
        "instrument_type": instrument,
        "status": "POSTED",
    })
    store.postings[rec["id"]] = rec
    participant["posted_collateral_cents"] += amount
    touch(participant)
    credit.evaluate_credit(participant)  # may CURE an open margin call
    return ok(serialize(rec), status=201)


@bp.get("/market/postings/<postingId>")
def get_one(postingId):
    parse_auth()
    return ok(serialize(get_posting(postingId)))


@bp.get("/market/postings")
def list_postings():
    parse_auth()
    rows = sorted(store.postings.values(), key=sort_key)
    pid = request.args.get("market_participant_id")
    status = request.args.get("status")
    if pid is not None:
        rows = [r for r in rows if r["market_participant_id"] == pid]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate([serialize(r) for r in rows])


@bp.post("/market/postings/<postingId>/release")
def release_posting(postingId):
    auth = parse_auth()
    require_role(auth, ["CreditOfficer"])
    posting = get_posting(postingId)
    participant = store.participants[posting["market_participant_id"]]
    check_ownership(auth, participant["id"])
    if posting["status"] != "POSTED":
        raise conflict(ERR_INVALID_STATE, "only a POSTED posting can be released")
    if credit.open_margin_call(participant) is not None:
        raise conflict(ERR_OPEN_MARGIN_CALL,
                       "participant has an OPEN margin call")
    effective = credit.effective_requirement(participant)
    if participant["posted_collateral_cents"] - posting["amount_cents"] < effective:
        raise conflict(ERR_COLLATERAL_SHORTFALL,
                       "release would leave collateral below the effective requirement")
    posting["status"] = "RELEASED"
    touch(posting)
    participant["posted_collateral_cents"] -= posting["amount_cents"]
    touch(participant)
    credit.evaluate_credit(participant)  # requirement unchanged
    return ok(serialize(posting))


@bp.post("/market/postings/<postingId>/draw")
def draw_posting(postingId):
    auth = parse_auth()
    require_role(auth, ["IsoOperator"])
    posting = get_posting(postingId)
    participant = store.participants[posting["market_participant_id"]]
    if posting["status"] != "POSTED":
        raise conflict(ERR_INVALID_STATE, "only a POSTED posting can be drawn")
    if credit.defaulted_margin_call(participant) is None:
        raise conflict(ERR_POSTING_NOT_DRAWABLE,
                       "participant has no DEFAULTED margin call")
    # waterfall targets: ISSUED statements with positive uncovered balance,
    # oldest first (issued_at ASC, then created_at ASC)
    targets = sorted(
        (s for s in store.statements.values()
         if s["market_participant_id"] == participant["id"]
         and s["status"] == "ISSUED"
         and s["net_amount_cents"] > s["paid_cents"]),
        key=lambda s: (s["issued_at"], s["created_at"], s["_seq"]))
    uncovered_total = sum(s["net_amount_cents"] - s["paid_cents"] for s in targets)
    amount = posting["amount_cents"]
    if amount > uncovered_total:
        raise invalid_request(
            "draw amount exceeds the participant's uncovered statement total")

    remaining = amount
    for stmt in targets:
        if remaining <= 0:
            break
        cover = min(remaining, stmt["net_amount_cents"] - stmt["paid_cents"])
        stmt["paid_cents"] += cover
        remaining -= cover
        if stmt["net_amount_cents"] > 0 and stmt["paid_cents"] >= stmt["net_amount_cents"]:
            stmt["status"] = "PAID"  # leaves the requirement input set
        touch(stmt)

    posting["status"] = "DRAWN"
    touch(posting)
    participant["posted_collateral_cents"] -= amount
    touch(participant)
    credit.refresh_credit(participant)
    return ok(serialize(posting))
