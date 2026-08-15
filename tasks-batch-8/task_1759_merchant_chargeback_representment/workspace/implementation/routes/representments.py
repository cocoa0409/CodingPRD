"""Representment packet endpoints (PRD 3.6, 3.7) — OCC-guarded assembly,
inclusive submit deadline, network outcomes, single-cure rule."""

from flask import Blueprint, g, request

from clock import CLOCK
from db import db
from errors import ApiError
from middleware import is_merchant_user
from records import new_representment, touch
from response import ok_object
from routes.common import ALL_ROLES, authenticate, get_or_404, hide_if_cross_merchant, json_body, list_response
from serializers import serialize_representment
from services.cascade import (
    cascade_decided_lost, cascade_decided_won, merchant_of, supersede_representment,
)
from util import Body, MAX_CURES, NETWORK_OUTCOMES, REPRESENTMENT_STATUSES, filter_enum, is_int

bp = Blueprint("representments", __name__)


def _owning_merchant_id(rep):
    cb = db.chargebacks.get(rep["chargeback_id"])
    return cb["merchant_id"] if cb is not None else None


def _open_packet(chargeback_id):
    return next((r for r in db.representments.values()
                 if r["chargeback_id"] == chargeback_id and r["status"] in ("ASSEMBLED", "SUBMITTED")), None)


def _latest_non_superseded(chargeback_id):
    reps = [r for r in db.representments.values()
            if r["chargeback_id"] == chargeback_id and r["status"] != "SUPERSEDED"]
    if not reps:
        return None
    reps.sort(key=lambda r: r["created_at"])  # stable: creation order on ties
    return reps[-1]


@bp.post("/acquirer/representments")
def create_representment():
    authenticate(("MerchantUser", "AcquirerOps"))
    b = Body(json_body())
    chargeback_id = b.req_str("chargeback_id")
    evidence_item_ids = b.d.get("evidence_item_ids")
    ids_valid = isinstance(evidence_item_ids, list)
    ecv_raw = b.d.get("expected_chargeback_version")

    # Priority 3: body-referenced chargeback (+ MerchantUser ownership hiding).
    cb = None
    if chargeback_id is not None:
        cb = get_or_404(db.chargebacks, chargeback_id, "Chargeback")
        hide_if_cross_merchant(cb["merchant_id"])

    # Priority 4 (OCC): expected_chargeback_version == Chargeback.version.
    if ecv_raw is not None:
        if not is_int(ecv_raw):
            b._fail(("ERR_INVALID_REQUEST", 400), "Field 'expected_chargeback_version' must be an integer")
        elif cb is not None and ecv_raw != cb["version"]:
            raise ApiError(412, "ERR_STALE_VERSION",
                           "expected_chargeback_version does not match the chargeback's current version")
    else:
        b._fail(("ERR_INVALID_REQUEST", 400), "Field 'expected_chargeback_version' is required")

    # Priority 5: case state permits assembly.
    if cb is not None and cb["case_status"] not in ("MERCHANT_NOTIFIED", "REPRESENTED"):
        raise ApiError(409, "ERR_INVALID_CASE_STATE",
                       "Representment assembly requires MERCHANT_NOTIFIED or REPRESENTED")
    # Priority 6: suspension gate.
    if cb is not None:
        merchant = merchant_of(cb)
        if merchant["status"] != "ACTIVE":
            raise ApiError(409, "ERR_MERCHANT_SUSPENDED", "Merchant is SUSPENDED")
    # Priority 7, in scaffold order: in-flight packet, cure rule, empty packet, attachability.
    superseded_packet = None
    if cb is not None:
        if _open_packet(cb["id"]) is not None:
            raise ApiError(409, "ERR_REPRESENTMENT_ALREADY_OPEN",
                           "A representment of this chargeback is already ASSEMBLED or SUBMITTED")
        if cb["case_status"] == "REPRESENTED":
            latest = _latest_non_superseded(cb["id"])
            if latest is None or latest["status"] != "RETURNED_FOR_CURE" or latest["cure_count"] >= MAX_CURES:
                raise ApiError(409, "ERR_CURE_LIMIT_EXCEEDED",
                               "The single network cure cycle for this packet lineage is exhausted")
            superseded_packet = latest
    if ids_valid:
        if len(evidence_item_ids) == 0:
            raise ApiError(409, "ERR_EMPTY_EVIDENCE_PACKET", "evidence_item_ids must be non-empty")
        if cb is not None:
            for item_id in evidence_item_ids:
                item = db.evidence_items.get(item_id) if isinstance(item_id, str) else None
                if item is None or item["chargeback_id"] != cb["id"] or item["status"] != "DRAFT":
                    raise ApiError(409, "ERR_EVIDENCE_NOT_ATTACHABLE",
                                   "Evidence item is not DRAFT or belongs to a different chargeback")
    else:
        b._fail(("ERR_INVALID_REQUEST", 400), "Field 'evidence_item_ids' is required and must be an array")
    b.raise_pending()

    cure_count = 0 if cb["case_status"] == "MERCHANT_NOTIFIED" else superseded_packet["cure_count"] + 1
    if superseded_packet is not None:
        supersede_representment(superseded_packet)  # its ATTACHED evidence returns to DRAFT
    rep = new_representment(cb["id"], evidence_item_ids, cure_count)
    db.representments[rep["id"]] = rep
    for item_id in evidence_item_ids:
        item = db.evidence_items[item_id]
        item["status"] = "ATTACHED"
        touch(item)
    touch(cb)  # case activity: the OCC write
    return ok_object(serialize_representment(rep), status=201)


@bp.get("/acquirer/representments")
def list_representments():
    authenticate(ALL_ROLES)
    chargeback_id = request.args.get("chargeback_id")
    status = filter_enum(request.args, "status", REPRESENTMENT_STATUSES)
    records = list(db.representments.values())
    if is_merchant_user():
        records = [r for r in records if _owning_merchant_id(r) == g.uid]
    if chargeback_id is not None:
        records = [r for r in records if r["chargeback_id"] == chargeback_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records, serialize_representment)


@bp.get("/acquirer/representments/<rid>")
def get_representment(rid):
    authenticate(ALL_ROLES)
    rep = get_or_404(db.representments, rid, "Representment")
    hide_if_cross_merchant(_owning_merchant_id(rep))
    return ok_object(serialize_representment(rep))


@bp.post("/acquirer/representments/<rid>/submit")
def submit_representment(rid):
    authenticate(("MerchantUser", "AcquirerOps"))
    rep = get_or_404(db.representments, rid, "Representment")
    cb = db.chargebacks[rep["chargeback_id"]]
    hide_if_cross_merchant(cb["merchant_id"])
    # Priority 5: only an ASSEMBLED packet can be submitted.
    if rep["status"] != "ASSEMBLED":
        raise ApiError(409, "ERR_INVALID_REPRESENTMENT_STATE", "Only an ASSEMBLED representment can be submitted")
    # Priority 6: suspension gate.
    merchant = merchant_of(cb)
    if merchant["status"] != "ACTIVE":
        raise ApiError(409, "ERR_MERCHANT_SUSPENDED", "Merchant is SUSPENDED")
    # Priority 8: the network hard deadline is inclusive.
    if CLOCK.now() > cb["representment_due_at"]:
        raise ApiError(409, "ERR_REPRESENTMENT_DEADLINE_PASSED", "The representment deadline has passed")
    # Priority 9: compelling-evidence completeness against the governing rule.
    rule = db.rules[cb["_rule_id"]]
    attached_types = {db.evidence_items[i]["evidence_type"]
                      for i in rep["evidence_item_ids"]
                      if db.evidence_items[i]["status"] == "ATTACHED"}
    missing = [t for t in rule["required_evidence_types"] if t not in attached_types]
    if missing:
        raise ApiError(422, "ERR_EVIDENCE_INCOMPLETE",
                       "Packet does not cover required evidence types: %s" % ", ".join(missing))

    rep["status"] = "SUBMITTED"
    rep["submitted_at"] = CLOCK.now()
    touch(rep)
    if cb["case_status"] == "MERCHANT_NOTIFIED":
        cb["case_status"] = "REPRESENTED"  # first submission only
    touch(cb)
    return ok_object(serialize_representment(rep))


@bp.post("/acquirer/representments/<rid>/network-outcome")
def network_outcome(rid):
    authenticate(("AcquirerOps",))
    rep = get_or_404(db.representments, rid, "Representment")
    cb = db.chargebacks[rep["chargeback_id"]]
    # Priority 5: the packet must be SUBMITTED.
    if rep["status"] != "SUBMITTED":
        raise ApiError(409, "ERR_INVALID_REPRESENTMENT_STATE",
                       "A network outcome can only be posted on a SUBMITTED representment")
    b = Body(json_body())
    outcome_raw = b.d.get("outcome")
    # Priority 7: single-cure rule.
    if outcome_raw == "RETURNED_FOR_CURE" and rep["cure_count"] >= MAX_CURES:
        raise ApiError(409, "ERR_CURE_LIMIT_EXCEEDED",
                       "The single network cure cycle for this packet lineage is exhausted")
    # Priority 11: payload shape (outcome enum; PARTIAL_WON amount bounds).
    outcome = b.req_enum("outcome", NETWORK_OUTCOMES)
    won_amount = None
    if outcome == "PARTIAL_WON":
        won_amount = b.d.get("won_amount_cents")
        if not is_int(won_amount) or not (0 < won_amount < cb["amount_cents"]):
            b._fail(("ERR_INVALID_REQUEST", 400),
                    "PARTIAL_WON requires 0 < won_amount_cents < chargeback amount_cents")
            won_amount = None
    b.raise_pending()

    now = CLOCK.now()
    if outcome == "WON":
        rep["status"] = "WON"
        rep["won_amount_cents"] = cb["amount_cents"]
        rep["decided_at"] = now
        touch(rep)
        cascade_decided_won(cb, cb["amount_cents"])
    elif outcome == "PARTIAL_WON":
        rep["status"] = "PARTIAL_WON"
        rep["won_amount_cents"] = won_amount
        rep["decided_at"] = now
        touch(rep)
        cascade_decided_won(cb, won_amount)
    elif outcome == "LOST":
        rep["status"] = "LOST"
        rep["decided_at"] = now
        touch(rep)
        cascade_decided_lost(cb)
    else:  # RETURNED_FOR_CURE — case stays REPRESENTED, decided_at stays null
        rep["status"] = "RETURNED_FOR_CURE"
        touch(rep)
        touch(cb)
    return ok_object(serialize_representment(rep))
