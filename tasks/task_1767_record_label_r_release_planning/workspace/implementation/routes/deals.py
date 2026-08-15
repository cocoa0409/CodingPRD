"""Deal memos: draft, propose, counter (OCC), approve, execute, reject."""

from decimal import Decimal

from flask import Blueprint

from db import db, today
from errors import raise_err
from helpers import (
    get_body, make_entity, touch, serialize, get_or_404, list_page,
    apply_filters, parse_date, add_months, add_years, v_str, v_int, v_bool,
    v_enum, v_date,
)
from middleware import auth, check_ownership
from response import ok, ok_list
from services.domain import (
    OPEN_MEMO_STATES, has_open_memo, maybe_revert_artist_to_scouted, expire_memo,
    memo_is_expired, label_of_artist,
)

bp = Blueprint("deals", __name__)

SIGNABLE_STATES = ("SCOUTED", "IN_NEGOTIATION", "SIGNED", "ACTIVE")
RECoupScopes = ["MASTER_ONLY", "CROSS_COLLATERALIZED"]


def _validate_term_fields(body, partial=False):
    """Validate memo term-sheet fields; returns dict of validated values."""
    out = {}
    req = not partial
    v = v_int(body, "advance_cents", required=req, min_v=0)
    if v is not None:
        out["advance_cents"] = v
    v = v_int(body, "base_royalty_rate_bps", required=req, min_v=1000, max_v=3000)
    if v is not None:
        out["base_royalty_rate_bps"] = v
    v = v_enum(body, "recoupment_scope", RECoupScopes, required=req)
    if v is not None:
        out["recoupment_scope"] = v
    v = v_bool(body, "promo_costs_recoupable", required=req)
    if v is not None:
        out["promo_costs_recoupable"] = v
    v = v_int(body, "options_total", required=req, min_v=0, max_v=3)
    if v is not None:
        out["options_total"] = v
    v = v_int(body, "option_term_months", required=req, choices=[12, 24])
    if v is not None:
        out["option_term_months"] = v
    v = v_int(body, "option_escalation_bps", required=req, min_v=0)
    if v is not None:
        out["option_escalation_bps"] = v
    v = v_int(body, "term_months", required=req, choices=[12, 24, 36])
    if v is not None:
        out["term_months"] = v
    v = v_date(body, "valid_until_date", required=req)
    if v is not None:
        out["valid_until_date"] = v
    return out


@bp.post("/api/artists/<aid>/deal-memos")
def create_memo(aid):
    auth(["AnRManager"])
    artist = get_or_404(db.artists, aid)
    body = get_body()
    terms = _validate_term_fields(body, partial=False)
    guardian_name = v_str(body, "guardian_name", required=False, allow_null=True)
    guardian_email = v_str(body, "guardian_email", required=False, allow_null=True)

    if has_open_memo(aid):
        raise_err("ERR_DEAL_MEMO_ALREADY_OPEN", "Artist already has an open deal memo")
    if artist["status"] not in SIGNABLE_STATES:
        raise_err("ERR_ARTIST_NOT_SIGNABLE", "Artist status %s does not permit a deal memo" % artist["status"])

    memo = make_entity({
        "artist_id": aid,
        "advance_cents": terms["advance_cents"],
        "base_royalty_rate_bps": terms["base_royalty_rate_bps"],
        "recoupment_scope": terms["recoupment_scope"],
        "promo_costs_recoupable": terms["promo_costs_recoupable"],
        "options_total": terms["options_total"],
        "option_term_months": terms["option_term_months"],
        "option_escalation_bps": terms["option_escalation_bps"],
        "term_months": terms["term_months"],
        "valid_until_date": terms["valid_until_date"],
        "guardian_name": guardian_name,
        "guardian_email": guardian_email,
        "round_count": 0,
        "contract_id": None,
        "status": "DRAFT",
        "_valid_until": parse_date(terms["valid_until_date"]),
    })
    db.deal_memos[memo["id"]] = memo
    return ok(serialize(memo), code=201)


@bp.get("/api/deal-memos/<mid>")
def get_memo(mid):
    uid, role = auth(["LabelAdmin", "AnRManager", "ArtistPortal"])
    memo = get_or_404(db.deal_memos, mid)
    check_ownership(role, uid, memo["artist_id"])
    return ok(serialize(memo))


@bp.get("/api/artists/<aid>/deal-memos")
def list_artist_memos(aid):
    uid, role = auth(["LabelAdmin", "AnRManager", "FinanceController", "ArtistPortal"])
    artist = get_or_404(db.artists, aid)
    check_ownership(role, uid, artist["id"])
    items = [m for m in db.deal_memos.values() if m["artist_id"] == aid]
    items = apply_filters(items, [("status", lambda m: m["status"])])
    data, pagination = list_page(items)
    return ok_list(data, pagination)


@bp.get("/api/deal-memos")
def list_memos():
    auth(["LabelAdmin", "AnRManager", "FinanceController"])
    items = apply_filters(db.deal_memos.values(), [
        ("artist_id", lambda m: m["artist_id"]),
        ("contract_id", lambda m: m["contract_id"] or ""),
        ("status", lambda m: m["status"]),
    ])
    data, pagination = list_page(items)
    return ok_list(data, pagination)


def _expire_and_fail(memo):
    expire_memo(memo)
    raise_err("ERR_DEAL_MEMO_EXPIRED", "Deal memo valid_until_date has passed")


@bp.post("/api/deal-memos/<mid>/propose")
def propose_memo(mid):
    auth(["AnRManager"])
    memo = get_or_404(db.deal_memos, mid)
    get_body()
    if memo["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "Only a DRAFT memo may be proposed")
    artist = db.artists.get(memo["artist_id"])
    # Order per PRD 3.2: one-open-memo, scouting gate, signability, expiry.
    if has_open_memo(memo["artist_id"], exclude_memo_id=memo["id"]):
        raise_err("ERR_DEAL_MEMO_ALREADY_OPEN", "Artist already has an open deal memo")
    label = label_of_artist(artist)
    if Decimal(str(artist["scouting_score"])) < Decimal(str(label["sign_threshold_score"])):
        raise_err("ERR_SCOUTING_SCORE_TOO_LOW", "Scouting score below the label sign threshold")
    if artist["status"] not in SIGNABLE_STATES:
        raise_err("ERR_ARTIST_NOT_SIGNABLE", "Artist status %s does not permit proposing" % artist["status"])
    if memo_is_expired(memo):
        _expire_and_fail(memo)
    memo["status"] = "PROPOSED"
    touch(memo)
    if artist["status"] == "SCOUTED":
        artist["status"] = "IN_NEGOTIATION"
        touch(artist)
    return ok(serialize(memo))


@bp.post("/api/deal-memos/<mid>/counter")
def counter_memo(mid):
    uid, role = auth(["AnRManager", "ArtistPortal"])
    memo = get_or_404(db.deal_memos, mid)
    check_ownership(role, uid, memo["artist_id"])
    body = get_body()
    expected = v_int(body, "expected_deal_memo_version")
    terms = _validate_term_fields(body, partial=True)
    if expected != memo["version"]:
        raise_err("ERR_STALE_VERSION", "Deal memo version mismatch")
    if memo["status"] not in ("PROPOSED", "COUNTERED"):
        raise_err("ERR_INVALID_STATE", "Memo in %s cannot be countered" % memo["status"])
    if memo_is_expired(memo):
        _expire_and_fail(memo)
    memo["status"] = "COUNTERED" if memo["status"] == "PROPOSED" else "PROPOSED"
    memo["round_count"] += 1
    for key, value in terms.items():
        memo[key] = value
    if "valid_until_date" in terms:
        memo["_valid_until"] = parse_date(terms["valid_until_date"])
    touch(memo)
    return ok(serialize(memo))


@bp.post("/api/deal-memos/<mid>/approve")
def approve_memo(mid):
    auth(["LabelAdmin"])
    memo = get_or_404(db.deal_memos, mid)
    get_body()
    if memo["status"] not in ("PROPOSED", "COUNTERED"):
        raise_err("ERR_INVALID_STATE", "Memo in %s cannot be approved" % memo["status"])
    if memo_is_expired(memo):
        _expire_and_fail(memo)
    memo["status"] = "APPROVED"
    touch(memo)
    return ok(serialize(memo))


@bp.post("/api/deal-memos/<mid>/execute")
def execute_memo(mid):
    auth(["LabelAdmin"])
    memo = get_or_404(db.deal_memos, mid)
    get_body()
    if memo["status"] != "APPROVED":
        raise_err("ERR_INVALID_STATE", "Only an APPROVED memo may be executed")
    artist = db.artists.get(memo["artist_id"])
    label = label_of_artist(artist)
    now = today()
    # PRD order: guardian consent, expiry, advance cap.
    birth = artist.get("_birth_date")
    if birth is not None and now < add_years(birth, 18):
        if not memo.get("guardian_name") or not memo.get("guardian_email"):
            raise_err("ERR_GUARDIAN_CONSENT_REQUIRED",
                      "Artist is under 18; guardian_name and guardian_email are required")
    if memo_is_expired(memo):
        _expire_and_fail(memo)
    if memo["advance_cents"] > label["advance_cap_cents"]:
        raise_err("ERR_ADVANCE_CAP_EXCEEDED", "advance_cents exceeds the label advance cap")

    term_start = now
    term_end = add_months(term_start, memo["term_months"])
    contract = make_entity({
        "artist_id": memo["artist_id"],
        "deal_memo_id": memo["id"],
        "advance_cents": memo["advance_cents"],
        "base_royalty_rate_bps": memo["base_royalty_rate_bps"],
        "recoupment_scope": memo["recoupment_scope"],
        "promo_costs_recoupable": memo["promo_costs_recoupable"],
        "options_total": memo["options_total"],
        "options_exercised": 0,
        "option_escalation_bps": memo["option_escalation_bps"],
        "option_term_months": memo["option_term_months"],
        "term_start_date": term_start.isoformat(),
        "current_term_end_date": term_end.isoformat(),
        "advance_status": "FUNDED" if memo["advance_cents"] == 0 else "PENDING",
        "effective_base_rate_bps": min(memo["base_royalty_rate_bps"], 3000),
        "status": "ACTIVE",
        "_current_term_end_date": term_end,
    })
    db.contracts[contract["id"]] = contract

    account = make_entity({
        "contract_id": contract["id"],
        "recording_balance_cents": 0,
        "advance_balance_cents": 0,
        "tour_support_balance_cents": 0,
        "promo_balance_cents": 0,
        "total_unrecouped_cents": 0,
        "total_recouped_cents": 0,
        "writeoff_cents": 0,
        "payout_status": "RECOUPING",
    })
    db.recoupment_accounts[account["id"]] = account

    if artist["status"] == "IN_NEGOTIATION":
        artist["status"] = "SIGNED"
        touch(artist)

    memo["contract_id"] = contract["id"]
    memo["status"] = "EXECUTED"
    touch(memo)

    return ok(serialize(contract), code=201)


@bp.post("/api/deal-memos/<mid>/reject")
def reject_memo(mid):
    auth(["AnRManager"])
    memo = get_or_404(db.deal_memos, mid)
    get_body()
    if memo["status"] not in ("DRAFT", "PROPOSED", "COUNTERED"):
        raise_err("ERR_INVALID_STATE", "Memo in %s cannot be rejected" % memo["status"])
    memo["status"] = "REJECTED"
    touch(memo)
    maybe_revert_artist_to_scouted(db.artists.get(memo["artist_id"]))
    return ok(serialize(memo))
