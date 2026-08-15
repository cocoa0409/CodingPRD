"""IntercompanyAgreement lifecycle (PRD 3.3).

DRAFT -> ACTIVE (activation pins study + range snapshot)
ACTIVE -> UNDER_AMENDMENT -> ACTIVE (cyclic amendment loop)
ACTIVE -> TERMINATED (terminal)
"""
from flask import Blueprint, request

import errors
from db import store, new_resource, touch, public
from errors import ApiError
from middleware import (
    require_auth, get_body, get_path, require_fk, is_int, parse_date,
    shape_str, shape_enum, shape_date, list_page, ALL_ROLES,
)
from response import ok_object, ok_list

bp = Blueprint("agreements", __name__)

TX_TYPES = ["GOODS", "SERVICES", "IP_ROYALTY", "FINANCING", "COST_SHARING"]
PRICING_METHODS = ["COST_PLUS", "TNMM", "RESALE_MINUS", "CUP"]
TRUE_UP_METHODS = ["TO_MEDIAN", "TO_RANGE_EDGE"]


def _half_open_overlap(ef1, et1, ef2, et2):
    """[ef, et) overlap; adjacency (to == from) is allowed."""
    return ef1 < et2 and ef2 < et1


def _entity_active(entity_id):
    ent = store.legal_entities.get(entity_id)
    return ent is not None and ent["status"] == "ACTIVE"


def _pin_study(agreement, study):
    agreement["pinned_study_id"] = study["id"]
    agreement["pinned_p25_bp"] = study["p25_bp"]
    agreement["pinned_median_bp"] = study["median_bp"]
    agreement["pinned_p75_bp"] = study["p75_bp"]


@bp.post("/tp/agreements")
def create_agreement():
    uid, _ = require_auth(["TaxAnalyst"])
    body = get_body()
    prov = body.get("provider_entity_id")
    rec = body.get("recipient_entity_id")
    study_id = body.get("benchmarking_study_id")
    # (3) existence of body FKs in declared order.
    require_fk(store.legal_entities, prov, "provider_entity_id")
    require_fk(store.legal_entities, rec, "recipient_entity_id")
    require_fk(store.studies, study_id, "benchmarking_study_id")
    # (6) entity referential: distinctness, then ACTIVE status.
    if isinstance(prov, str) and isinstance(rec, str) and prov and prov == rec:
        raise ApiError(errors.SAME_LEGAL_ENTITY, 409,
                       "provider_entity_id and recipient_entity_id must differ")
    for eid in (prov, rec):
        if isinstance(eid, str) and eid in store.legal_entities and not _entity_active(eid):
            raise ApiError(errors.ENTITY_INACTIVE, 409,
                           "Referenced legal entity is not ACTIVE")
    # (7) temporal: half-open overlap vs DRAFT/ACTIVE/UNDER_AMENDMENT peers.
    ef = parse_date(body.get("effective_from"))
    et = parse_date(body.get("effective_to"))
    tt = body.get("transaction_type")
    if ef is not None and et is not None and isinstance(prov, str) and isinstance(rec, str):
        for a in store.agreements.values():
            if (a["provider_entity_id"] == prov
                    and a["recipient_entity_id"] == rec
                    and a["transaction_type"] == tt
                    and a["status"] in ("DRAFT", "ACTIVE", "UNDER_AMENDMENT")):
                if _half_open_overlap(ef, et, parse_date(a["effective_from"]),
                                      parse_date(a["effective_to"])):
                    raise ApiError(errors.AGREEMENT_PERIOD_OVERLAP, 409,
                                   "Effective window overlaps an existing agreement "
                                   "for the same provider, recipient, and transaction type")
    # (10) shape.
    shape_str(body, "provider_entity_id")
    shape_str(body, "recipient_entity_id")
    shape_enum(body, "transaction_type", TX_TYPES)
    pm = shape_enum(body, "pricing_method", PRICING_METHODS)
    shape_enum(body, "true_up_method", TRUE_UP_METHODS)
    shape_date(body, "effective_from")
    shape_date(body, "effective_to")
    markup = body.get("markup_bp")
    if pm == "COST_PLUS":
        if not is_int(markup):
            raise ApiError(errors.INVALID_REQUEST, 400,
                           "markup_bp is required when pricing_method is COST_PLUS")
        if not isinstance(study_id, str) or not study_id:
            raise ApiError(errors.INVALID_REQUEST, 400,
                           "benchmarking_study_id is required when pricing_method is COST_PLUS")
    else:
        if markup is not None and not is_int(markup):
            raise ApiError(errors.INVALID_REQUEST, 400, "markup_bp must be an integer")
        if study_id is not None and (not isinstance(study_id, str) or not study_id):
            raise ApiError(errors.INVALID_REQUEST, 400,
                           "benchmarking_study_id must be a string")
    a = new_resource()
    a.update({
        "provider_entity_id": prov,
        "recipient_entity_id": rec,
        "transaction_type": tt,
        "pricing_method": pm,
        "markup_bp": markup,
        "true_up_method": body.get("true_up_method"),
        "benchmarking_study_id": study_id,
        "pinned_study_id": None,
        "pinned_p25_bp": None,
        "pinned_median_bp": None,
        "pinned_p75_bp": None,
        "effective_from": body.get("effective_from"),
        "effective_to": body.get("effective_to"),
        "status": "DRAFT",
        "pending_markup_bp": None,
        "pending_study_id": None,
        "amendment_started_by_user_id": None,
        "created_by_user_id": uid,
        "amendments_count": 0,
        "pricing_review_required": False,
        "apa_locked": False,
    })
    store.agreements[a["id"]] = a
    return ok_object(public(a), 201)


@bp.get("/tp/agreements/<agreementId>")
def get_agreement(agreementId):
    require_auth(ALL_ROLES)
    a = get_path(store.agreements, agreementId)
    return ok_object(public(a), 200)


@bp.get("/tp/agreements")
def list_agreements():
    require_auth(ALL_ROLES)
    filters = [
        ("provider_entity_id", request.args.get("provider_entity_id")),
        ("recipient_entity_id", request.args.get("recipient_entity_id")),
        ("pinned_study_id", request.args.get("pinned_study_id")),
        ("benchmarking_study_id", request.args.get("benchmarking_study_id")),
        ("status", request.args.get("status")),
    ]
    page, limit, offset, total = list_page(list(store.agreements.values()), filters)
    return ok_list([public(r) for r in page], limit, offset, total)


@bp.post("/tp/agreements/<agreementId>/activate")
def activate_agreement(agreementId):
    uid, _ = require_auth(["TaxManager"])
    a = get_path(store.agreements, agreementId)
    if a["status"] != "DRAFT":
        raise ApiError(errors.INVALID_STATE, 409,
                       "activate requires the agreement to be DRAFT")
    # (5) segregation of duties vs creator.
    if uid == a["created_by_user_id"]:
        raise ApiError(errors.SEGREGATION, 409,
                       "Activator must differ from the agreement creator")
    # (6) both counterparties still ACTIVE.
    if not _entity_active(a["provider_entity_id"]) or not _entity_active(a["recipient_entity_id"]):
        raise ApiError(errors.ENTITY_INACTIVE, 409,
                       "Both counterparties must be ACTIVE at activation")
    # (7) logical clock date inside the half-open window.
    today = store.clock.date()
    if not (parse_date(a["effective_from"]) <= today < parse_date(a["effective_to"])):
        raise ApiError(errors.AGREEMENT_NOT_IN_EFFECT, 409,
                       "Logical clock date is outside [effective_from, effective_to)")
    # (7) overlap vs ACTIVE / UNDER_AMENDMENT peers.
    ef = parse_date(a["effective_from"])
    et = parse_date(a["effective_to"])
    for o in store.agreements.values():
        if (o["id"] != a["id"]
                and o["provider_entity_id"] == a["provider_entity_id"]
                and o["recipient_entity_id"] == a["recipient_entity_id"]
                and o["transaction_type"] == a["transaction_type"]
                and o["status"] in ("ACTIVE", "UNDER_AMENDMENT")):
            if _half_open_overlap(ef, et, parse_date(o["effective_from"]),
                                  parse_date(o["effective_to"])):
                raise ApiError(errors.AGREEMENT_PERIOD_OVERLAP, 409,
                               "Effective window overlaps a live agreement for the "
                               "same provider, recipient, and transaction type")
    # (8) referenced study must be CURRENT; activation pins it with its range.
    study = None
    if a["benchmarking_study_id"] is not None:
        study = store.studies.get(a["benchmarking_study_id"])
        if study is None or study["status"] != "CURRENT":
            raise ApiError(errors.STALE_BENCHMARK, 409,
                           "The referenced benchmarking study is not CURRENT")
    if study is not None:
        _pin_study(a, study)
    a["status"] = "ACTIVE"
    touch(a)
    return ok_object(public(a), 200)


@bp.post("/tp/agreements/<agreementId>/start_amendment")
def start_amendment(agreementId):
    uid, _ = require_auth(["TaxAnalyst"])
    a = get_path(store.agreements, agreementId)
    body = get_body()
    new_study = body.get("new_benchmarking_study_id")
    require_fk(store.studies, new_study, "new_benchmarking_study_id")
    if a["status"] != "ACTIVE":
        raise ApiError(errors.INVALID_STATE, 409,
                       "start_amendment requires the agreement to be ACTIVE")
    if a["apa_locked"]:
        raise ApiError(errors.APA_LOCKED, 409,
                       "Agreement pricing is locked by an agreed APA")
    new_markup = body.get("new_markup_bp")
    if not is_int(new_markup):
        raise ApiError(errors.INVALID_REQUEST, 400,
                       "new_markup_bp is required and must be an integer")
    if new_study is not None and (not isinstance(new_study, str) or not new_study):
        raise ApiError(errors.INVALID_REQUEST, 400,
                       "new_benchmarking_study_id must be a string")
    a["pending_markup_bp"] = new_markup
    a["pending_study_id"] = new_study
    a["amendment_started_by_user_id"] = uid
    a["status"] = "UNDER_AMENDMENT"
    touch(a)
    return ok_object(public(a), 200)


@bp.post("/tp/agreements/<agreementId>/approve_amendment")
def approve_amendment(agreementId):
    uid, _ = require_auth(["TaxManager"])
    a = get_path(store.agreements, agreementId)
    if a["status"] != "UNDER_AMENDMENT":
        raise ApiError(errors.INVALID_STATE, 409,
                       "approve_amendment requires the agreement to be UNDER_AMENDMENT")
    if uid == a["amendment_started_by_user_id"]:
        raise ApiError(errors.SEGREGATION, 409,
                       "Amendment approver must differ from the amendment starter")
    study = None
    if a["pending_study_id"] is not None:
        study = store.studies.get(a["pending_study_id"])
        if study is None or study["status"] != "CURRENT":
            raise ApiError(errors.STALE_BENCHMARK, 409,
                           "The proposed replacement study is not CURRENT")
    a["markup_bp"] = a["pending_markup_bp"]
    if study is not None:
        a["benchmarking_study_id"] = study["id"]
        _pin_study(a, study)
    a["pending_markup_bp"] = None
    a["pending_study_id"] = None
    a["amendment_started_by_user_id"] = None
    a["amendments_count"] += 1
    a["pricing_review_required"] = False
    a["status"] = "ACTIVE"
    touch(a)
    return ok_object(public(a), 200)


@bp.post("/tp/agreements/<agreementId>/discard_amendment")
def discard_amendment(agreementId):
    require_auth(["TaxAnalyst"])
    a = get_path(store.agreements, agreementId)
    if a["status"] != "UNDER_AMENDMENT":
        raise ApiError(errors.INVALID_STATE, 409,
                       "discard_amendment requires the agreement to be UNDER_AMENDMENT")
    a["pending_markup_bp"] = None
    a["pending_study_id"] = None
    a["amendment_started_by_user_id"] = None
    a["status"] = "ACTIVE"
    touch(a)
    return ok_object(public(a), 200)


@bp.post("/tp/agreements/<agreementId>/terminate")
def terminate_agreement(agreementId):
    require_auth(["TaxManager"])
    a = get_path(store.agreements, agreementId)
    if a["status"] != "ACTIVE":
        raise ApiError(errors.INVALID_STATE, 409,
                       "terminate requires the agreement to be ACTIVE")
    if a["apa_locked"]:
        raise ApiError(errors.APA_LOCKED, 409,
                       "Agreement pricing is locked by an agreed APA")
    for t in store.transactions.values():
        if (t["agreement_id"] == a["id"]
                and t["elimination_status"] != "ELIMINATED"):
            raise ApiError(errors.AGREEMENT_HAS_OPEN_TRANSACTIONS, 409,
                           "Agreement has transactions not yet ELIMINATED")
    a["status"] = "TERMINATED"
    touch(a)
    return ok_object(public(a), 200)
