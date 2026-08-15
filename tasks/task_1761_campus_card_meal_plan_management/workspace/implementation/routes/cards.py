"""CampusCard and PhotoSubmission endpoints (PRD 3.1, 3.2)."""

from flask import Blueprint, g, request

from db import store
from errors import (
    err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_NOT_RESOURCE_OWNER,
    ERR_INVALID_STATE_TRANSITION, ERR_HOLDER_NOT_ACTIVE, ERR_CARD_NOT_ACTIVE,
    ERR_CARD_NOT_RECOVERABLE, ERR_PHOTO_NOT_APPROVED, ERR_ACTIVE_CARD_EXISTS,
    ERR_STALE_VERSION,
)
from middleware import (
    authenticate, require_roles, get_body, v_str, v_int, v_bool, v_enum, v_dt,
    find_or_404, pub, paginate, fmt_dt,
)
from response import success
from services.core import (
    new_row, touch, clock, dt_of, get_or_create_campus_cash, mint_card_number,
)
from services.cascades import (
    revoke_card_grants, suspend_card_grants, add_fraud_strike,
    create_card_for_holder,
)
from services.ledger import post_entry
from services.pricing import replacement_fee

bp = Blueprint("cards", __name__)

CARD_LIFECYCLE = {"PENDING_PHOTO", "ACTIVE", "LOST_FROZEN", "STOLEN_FROZEN",
                  "REPLACED", "EXPIRED", "DEACTIVATED"}
NON_TERMINAL_CARD = {"PENDING_PHOTO", "ACTIVE", "LOST_FROZEN", "STOLEN_FROZEN"}
REPLACEMENT_REASONS = {"LOST", "STOLEN", "DAMAGED"}


def _own_card_or_403(card):
    if g.role == "CardHolder" and card["holder_id"] != g.user_id:
        err(ERR_NOT_RESOURCE_OWNER, "CardHolder may act only on its own card")


# ---------------------------------------------------------------- card issue
@bp.route("/api/card-holders/<hid>/cards", methods=["POST"])
def issue_card(hid):
    authenticate()
    require_roles("CardOfficeAdmin")
    body = get_body()
    expires_at = v_dt(body, "expires_at")
    holder = find_or_404(store.holders, hid)
    if clock() >= expires_at:
        err(ERR_VALIDATION, "expires_at must be in the future at issuance")
    for c in store.cards.values():
        if c["holder_id"] == holder["id"] and c["lifecycle_status"] in NON_TERMINAL_CARD:
            err(ERR_ACTIVE_CARD_EXISTS, "Holder already has a non-terminal card")
    card = create_card_for_holder(
        holder, fmt_dt(expires_at), "PENDING_PHOTO", "NOT_SUBMITTED", True, 0)
    return success(pub(card), 201)


@bp.route("/api/cards", methods=["GET"])
def list_cards():
    authenticate()
    require_roles("CardOfficeAdmin", "FraudAnalyst", "SecurityOfficer")
    rows = list(store.cards.values())
    holder_id = request.args.get("holder_id")
    lifecycle = request.args.get("lifecycle_status")
    replaced_by = request.args.get("replaced_by_card_id")
    if holder_id is not None:
        rows = [c for c in rows if c["holder_id"] == holder_id]
    if lifecycle is not None:
        rows = [c for c in rows if c["lifecycle_status"] == lifecycle]
    if replaced_by is not None:
        rows = [c for c in rows if c.get("replaced_by_card_id") == replaced_by]
    data, page = paginate(rows)
    return success(data, 200, page)


@bp.route("/api/cards/<cid>", methods=["GET"])
def get_card(cid):
    authenticate()
    require_roles("CardOfficeAdmin", "FraudAnalyst", "SecurityOfficer", "CardHolder")
    card = store.cards.get(cid)
    if card is not None:
        _own_card_or_403(card)
    if card is None:
        err(ERR_NOT_FOUND, "Card not found")
    return success(pub(card), 200)


# ------------------------------------------------------------- card actions
@bp.route("/api/cards/<cid>/activate", methods=["POST"])
def activate_card(cid):
    authenticate()
    require_roles("CardOfficeAdmin")
    body = get_body()
    allow_provisional = v_bool(body, "allow_provisional", default=False)
    card = find_or_404(store.cards, cid)
    if card["lifecycle_status"] != "PENDING_PHOTO":
        err(ERR_INVALID_STATE_TRANSITION, "Only a PENDING_PHOTO card can be activated")
    if clock() >= dt_of(card, "expires_at"):
        err(ERR_INVALID_STATE_TRANSITION, "Card has expired")
    holder = store.holders[card["holder_id"]]
    if holder["status"] != "ACTIVE":
        err(ERR_HOLDER_NOT_ACTIVE, "Holder is not ACTIVE")
    if card["photo_status"] != "APPROVED" and not allow_provisional:
        err(ERR_PHOTO_NOT_APPROVED,
            "photo_status is not APPROVED and allow_provisional is not true")
    card["lifecycle_status"] = "ACTIVE"
    card["is_provisional"] = not (card["photo_status"] == "APPROVED")
    touch(card)
    return success(pub(card), 200)


@bp.route("/api/cards/<cid>/report-lost", methods=["POST"])
def report_lost(cid):
    authenticate()
    require_roles("CardHolder")
    card = store.cards.get(cid)
    if card is not None:
        _own_card_or_403(card)
    if card is None:
        err(ERR_NOT_FOUND, "Card not found")
    if card["lifecycle_status"] != "ACTIVE":
        err(ERR_INVALID_STATE_TRANSITION, "Only an ACTIVE card can be reported lost")
    card["lifecycle_status"] = "LOST_FROZEN"
    card["lost_or_stolen_report_count"] += 1
    suspend_card_grants(card)
    touch(card)
    return success(pub(card), 200)


@bp.route("/api/cards/<cid>/report-stolen", methods=["POST"])
def report_stolen(cid):
    authenticate()
    require_roles("CardHolder")
    card = store.cards.get(cid)
    if card is not None:
        _own_card_or_403(card)
    body = get_body()
    police = v_str(body, "police_report_number", required=False)
    if card is None:
        err(ERR_NOT_FOUND, "Card not found")
    if card["lifecycle_status"] not in ("ACTIVE", "LOST_FROZEN"):
        err(ERR_INVALID_STATE_TRANSITION,
            "Only an ACTIVE or LOST_FROZEN card can be reported stolen")
    card["lifecycle_status"] = "STOLEN_FROZEN"
    card["lost_or_stolen_report_count"] += 1
    if police:
        card["stolen_police_report_number"] = police
    touch(card)
    holder = store.holders[card["holder_id"]]
    # Cascade links 1->2->3->4: strike, threshold suspension, suspension cascade.
    add_fraud_strike(holder, exclude_card_id=card["id"])
    suspend_card_grants(card)
    # Independently of the strike count, freeze OPEN accounts (CARD_STOLEN).
    for acct in store.accounts.values():
        if acct["holder_id"] == holder["id"] and acct["status"] == "OPEN":
            acct["status"] = "FROZEN"
            acct["frozen_reason"] = "CARD_STOLEN"
            touch(acct)
    return success(pub(card), 200)


@bp.route("/api/cards/<cid>/unfreeze", methods=["POST"])
def unfreeze_card(cid):
    authenticate()
    require_roles("CardHolder")
    card = store.cards.get(cid)
    if card is not None:
        _own_card_or_403(card)
    if card is None:
        err(ERR_NOT_FOUND, "Card not found")
    if card["lifecycle_status"] == "STOLEN_FROZEN" or \
            card["lifecycle_status"] in ("REPLACED", "EXPIRED", "DEACTIVATED"):
        err(ERR_CARD_NOT_RECOVERABLE,
            "A stolen or terminal card cannot be unfrozen")
    if card["lifecycle_status"] != "LOST_FROZEN":
        err(ERR_INVALID_STATE_TRANSITION, "Only a LOST_FROZEN card can be unfrozen")
    holder = store.holders[card["holder_id"]]
    if holder["status"] != "ACTIVE":
        err(ERR_HOLDER_NOT_ACTIVE, "Holder is not ACTIVE")
    card["lifecycle_status"] = "ACTIVE"
    for gr in store.grants.values():
        if (gr["card_id"] == card["id"] and gr["status"] == "SUSPENDED"
                and gr.get("suspended_reason") == "CARD_FROZEN"):
            gr["status"] = "ACTIVE"
            gr["suspended_reason"] = None
            touch(gr)
    touch(card)
    return success(pub(card), 200)


@bp.route("/api/cards/<cid>/replacement", methods=["POST"])
def replace_card(cid):
    authenticate()
    require_roles("CardOfficeAdmin")
    body = get_body()
    reason = v_enum(body, "reason", REPLACEMENT_REASONS)
    expected_version = v_int(body, "expected_card_version")
    police = v_str(body, "police_report_number", required=False)
    surrendered = v_bool(body, "surrendered", default=False)
    card = find_or_404(store.cards, cid)
    if card["lifecycle_status"] not in NON_TERMINAL_CARD:
        err(ERR_INVALID_STATE_TRANSITION, "A terminal card cannot be replaced")
    if expected_version != card["version"]:
        err(ERR_STALE_VERSION, "expected_card_version does not match the card version")
    holder = store.holders[card["holder_id"]]
    fee = replacement_fee(holder, card, reason, police, surrendered)
    if police:
        card["stolen_police_report_number"] = police
    if card["photo_status"] == "APPROVED":
        new_card = create_card_for_holder(
            holder, card["expires_at"], "ACTIVE", "APPROVED", False, fee)
    else:
        new_card = create_card_for_holder(
            holder, card["expires_at"], "PENDING_PHOTO", "NOT_SUBMITTED", True, fee)
    card["lifecycle_status"] = "REPLACED"
    card["replaced_by_card_id"] = new_card["id"]
    revoke_card_grants(card)
    touch(card)
    if fee > 0:
        acct = get_or_create_campus_cash(holder["id"])
        post_entry(acct, "FEE", fee,
                   f"Replacement fee for card {card['id']} (reason {reason})")
    return success(pub(new_card), 201)


@bp.route("/api/cards/<cid>/deactivate", methods=["POST"])
def deactivate_card(cid):
    authenticate()
    require_roles("CardOfficeAdmin", "FraudAnalyst")
    card = find_or_404(store.cards, cid)
    if card["lifecycle_status"] not in NON_TERMINAL_CARD:
        err(ERR_INVALID_STATE_TRANSITION, "A terminal card cannot be deactivated")
    card["lifecycle_status"] = "DEACTIVATED"
    revoke_card_grants(card)
    touch(card)
    return success(pub(card), 200)


# ------------------------------------------------------------------- photos
@bp.route("/api/cards/<cid>/photos", methods=["POST"])
def submit_photo(cid):
    authenticate()
    require_roles("CardHolder")
    card = store.cards.get(cid)
    if card is not None:
        _own_card_or_403(card)
    body = get_body()
    image_ref = v_str(body, "image_ref")
    if card is None:
        err(ERR_NOT_FOUND, "Card not found")
    if card["lifecycle_status"] not in ("PENDING_PHOTO", "ACTIVE", "LOST_FROZEN"):
        err(ERR_INVALID_STATE_TRANSITION,
            "Photos are accepted only while the card is PENDING_PHOTO, ACTIVE or LOST_FROZEN")
    if card["photo_status"] not in ("NOT_SUBMITTED", "REJECTED"):
        err(ERR_INVALID_STATE_TRANSITION,
            "A photo may be submitted only from NOT_SUBMITTED or REJECTED")
    seq = 1 + sum(1 for p in store.photos.values() if p["card_id"] == card["id"])
    photo = new_row()
    photo.update({
        "card_id": card["id"],
        "image_ref": image_ref,
        "review_status": "PENDING_REVIEW",
        "rejection_reason": None,
        "reviewed_by": None,
        "submission_sequence": seq,
    })
    store.photos[photo["id"]] = photo
    card["photo_status"] = "PENDING_REVIEW"
    touch(card)
    return success(pub(photo), 201)


@bp.route("/api/cards/<cid>/photos", methods=["GET"])
def list_photos(cid):
    authenticate()
    require_roles("CardOfficeAdmin", "CardHolder")
    card = store.cards.get(cid)
    if card is not None:
        _own_card_or_403(card)
    if card is None:
        err(ERR_NOT_FOUND, "Card not found")
    rows = [p for p in store.photos.values() if p["card_id"] == card["id"]]
    data, page = paginate(rows)
    return success(data, 200, page)


@bp.route("/api/photos/<pid>/review", methods=["POST"])
def review_photo(pid):
    authenticate()
    require_roles("CardOfficeAdmin")
    body = get_body()
    decision = v_enum(body, "decision", {"APPROVED", "REJECTED"})
    rejection_reason = v_str(body, "rejection_reason", required=False)
    if decision == "REJECTED" and not rejection_reason:
        err(ERR_VALIDATION, "rejection_reason is required when decision is REJECTED")
    photo = find_or_404(store.photos, pid)
    if photo["review_status"] != "PENDING_REVIEW":
        err(ERR_INVALID_STATE_TRANSITION, "Only a PENDING_REVIEW submission is reviewable")
    card = store.cards[photo["card_id"]]
    latest_seq = max(
        (p["submission_sequence"] for p in store.photos.values()
         if p["card_id"] == card["id"]),
        default=0,
    )
    if photo["submission_sequence"] != latest_seq:
        err(ERR_INVALID_STATE_TRANSITION,
            "Only the card's latest submission is reviewable")
    photo["review_status"] = decision
    photo["reviewed_by"] = g.user_id
    photo["rejection_reason"] = rejection_reason if decision == "REJECTED" else None
    touch(photo)
    card["photo_status"] = decision
    if decision == "APPROVED" and card["is_provisional"]:
        card["is_provisional"] = False
    touch(card)
    return success(pub(photo), 200)
