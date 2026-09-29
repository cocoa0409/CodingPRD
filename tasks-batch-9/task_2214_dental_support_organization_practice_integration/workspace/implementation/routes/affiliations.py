"""Affiliation lifecycle: DRAFT -> DILIGENCE -> SIGNED -> CLOSED (PRD 3.1, 3.3)."""

from flask import Blueprint

import clock
import config
import db
import middleware
import payload
import support
from errors import ApiError
from services import cascade, derive, uow

bp = Blueprint("affiliations", __name__)

READ_ROLES = config.ALL_ROLES
LIST_ROLES = config.DSO_ROLES


def _require_status(affiliation, expected):
    if affiliation["status"] != expected:
        raise ApiError(
            "ERR_INVALID_AFFILIATION_STATE",
            "The affiliation must be in %s for this operation." % expected,
        )


@bp.post("/affiliations")
@support.transactional
def create_affiliation():
    middleware.authorize([config.ROLE_DEAL_COUNSEL])
    data = payload.body()
    seller_group_name = payload.string(data, "seller_group_name")
    purchase_price_cents = payload.integer(data, "purchase_price_cents", minimum=1)
    earnout_pool_cents = payload.integer(data, "earnout_pool_cents", minimum=0)
    baseline_ebitda_cents = payload.integer(data, "baseline_ebitda_cents", minimum=1)
    baseline_net_collections_cents = payload.integer(
        data, "baseline_net_collections_cents", minimum=1
    )
    post_close_doctor_term_months = payload.integer(
        data,
        "post_close_doctor_term_months",
        required=False,
        default=config.DEFAULT_POST_CLOSE_DOCTOR_TERM_MONTHS,
        minimum=0,
    )
    row = db.insert(
        "affiliations",
        {
            "seller_group_name": seller_group_name,
            "status": "DRAFT",
            "purchase_price_cents": purchase_price_cents,
            "earnout_pool_cents": earnout_pool_cents,
            "baseline_ebitda_cents": baseline_ebitda_cents,
            "baseline_net_collections_cents": baseline_net_collections_cents,
            "earnout_measurement_state": "NOT_OPEN",
            "repricing_round": 0,
            "post_close_doctor_term_months": post_close_doctor_term_months,
            "diligence_opened_at": None,
            "signed_date": None,
            "close_date": None,
        },
    )
    return "affiliations", row, 201


@bp.get("/affiliations/<affiliation_id>")
def get_affiliation(affiliation_id):
    middleware.authorize(READ_ROLES)
    row = support.load("affiliations", affiliation_id)
    return support.read_one("affiliations", row)


@bp.get("/affiliations")
def list_affiliations():
    middleware.authorize(LIST_ROLES)
    rows = db.all_rows("affiliations")
    rows = support.filter_rows(rows, "status", payload.filter_value("status"))
    return support.read_many("affiliations", rows)


@bp.post("/affiliations/<affiliation_id>/advance-diligence")
@support.transactional
def advance_diligence(affiliation_id):
    middleware.authorize([config.ROLE_DEAL_COUNSEL])
    affiliation = support.load("affiliations", affiliation_id)
    payload.body()
    _require_status(affiliation, "DRAFT")
    if derive.practice_count(affiliation) < 1:
        raise ApiError(
            "ERR_NO_TARGET_PRACTICE",
            "At least one practice must be attached before diligence opens.",
        )
    affiliation["status"] = "DILIGENCE"
    affiliation["diligence_opened_at"] = clock.now()
    uow.touch(affiliation)
    return "affiliations", affiliation, 200


@bp.post("/affiliations/<affiliation_id>/reprice")
@support.transactional
def reprice(affiliation_id):
    middleware.authorize([config.ROLE_DEAL_COUNSEL])
    affiliation = support.load("affiliations", affiliation_id)
    data = payload.body()
    purchase_price_cents = payload.integer(data, "purchase_price_cents", minimum=1)
    earnout_pool_cents = payload.integer(data, "earnout_pool_cents", minimum=0)
    payload.string(data, "reprice_note", required=False)
    _require_status(affiliation, "DILIGENCE")
    if affiliation["repricing_round"] >= config.MAX_REPRICING_ROUNDS:
        raise ApiError(
            "ERR_REPRICING_LIMIT_REACHED",
            "The repricing loop has no rounds left.",
        )
    if derive.tranches_of_affiliation(affiliation["id"]):
        raise ApiError(
            "ERR_EARNOUT_POOL_LOCKED",
            "The earn-out pool is locked once a tranche exists.",
        )
    affiliation["purchase_price_cents"] = purchase_price_cents
    affiliation["earnout_pool_cents"] = earnout_pool_cents
    affiliation["repricing_round"] += 1
    affiliation["status"] = "DRAFT"
    uow.touch(affiliation)
    return "affiliations", affiliation, 200


@bp.post("/affiliations/<affiliation_id>/sign")
@support.transactional
def sign(affiliation_id):
    middleware.authorize([config.ROLE_DEAL_COUNSEL])
    affiliation = support.load("affiliations", affiliation_id)
    data = payload.body()
    payload.string(data, "signature_note", required=False)
    _require_status(affiliation, "DILIGENCE")
    for practice in derive.practices_of_affiliation(affiliation["id"]):
        offered = [
            employment
            for employment in derive.employments_of_practice(practice["id"])
            if employment["employment_status"] == "OFFERED"
        ]
        if not offered:
            raise ApiError(
                "ERR_NO_POST_CLOSE_EMPLOYMENT",
                "Every practice needs at least one offered post-close employment.",
            )
    affiliation["status"] = "SIGNED"
    affiliation["signed_date"] = clock.now()
    uow.touch(affiliation)
    return "affiliations", affiliation, 200


@bp.post("/affiliations/<affiliation_id>/close")
@support.transactional
def close(affiliation_id):
    middleware.authorize([config.ROLE_INTEGRATION_LEAD])
    affiliation = support.load("affiliations", affiliation_id)
    data = payload.body()
    payload.string(data, "close_note", required=False)
    _require_status(affiliation, "SIGNED")
    for practice in derive.practices_of_affiliation(affiliation["id"]):
        effective = [
            agreement
            for agreement in derive.agreements_of_practice(practice["id"])
            if agreement["status"] == "EFFECTIVE"
        ]
        if not effective:
            raise ApiError(
                "ERR_SERVICE_AGREEMENT_NOT_EFFECTIVE",
                "Every practice needs an effective service agreement before close.",
            )
    affiliation["status"] = "CLOSED"
    cascade.close_affiliation(affiliation)
    return "affiliations", affiliation, 200
