"""Management services agreements and their service scope (PRD 3.2).

The corporate-practice-of-dentistry boundary lives here: a line item naming a
clinical domain is refused outright, so `is_clinical` can only ever be false.
"""

from flask import Blueprint

import clock
import config
import db
import middleware
import payload
import support
from errors import ApiError
from services import derive, uow

bp = Blueprint("agreements", __name__)

READ_ROLES = config.DSO_ROLES


def _require_agreement_status(agreement, expected):
    if agreement["status"] != expected:
        raise ApiError(
            "ERR_INVALID_AGREEMENT_STATE",
            "The agreement must be in %s for this operation." % expected,
        )


@bp.post("/service-agreements")
@support.transactional
def create_agreement():
    middleware.authorize([config.ROLE_DEAL_COUNSEL])
    data = payload.body()
    practice = support.load_fk(data, "practice_id", "practices")
    payload.string(data, "practice_id")
    fee_model = payload.enum(data, "fee_model", config.FEE_MODELS)
    mgmt_fee_bps = payload.integer(data, "mgmt_fee_bps", minimum=0)
    row = db.insert(
        "service_agreements",
        {
            "practice_id": practice["id"],
            "status": "DRAFT",
            "fee_model": fee_model,
            "mgmt_fee_bps": mgmt_fee_bps,
            "scope_findings_count": 0,
            "review_round": 0,
            "effective_date": None,
        },
    )
    return "service_agreements", row, 201


@bp.get("/service-agreements/<service_agreement_id>")
def get_agreement(service_agreement_id):
    middleware.authorize(READ_ROLES)
    row = support.load("service_agreements", service_agreement_id)
    return support.read_one("service_agreements", row)


@bp.get("/service-agreements")
def list_agreements():
    middleware.authorize(READ_ROLES)
    rows = db.all_rows("service_agreements")
    rows = support.filter_rows(rows, "practice_id", payload.filter_value("practice_id"))
    rows = support.filter_rows(rows, "status", payload.filter_value("status"))
    return support.read_many("service_agreements", rows)


@bp.post("/service-agreements/<id>/line-items")
@support.transactional
def create_line_item(id):
    middleware.authorize([config.ROLE_DEAL_COUNSEL])
    agreement = support.load("service_agreements", id)
    data = payload.body()
    service_code = payload.string(data, "service_code")
    service_domain = payload.enum(data, "service_domain", config.SERVICE_DOMAINS)
    monthly_fee_cents = payload.integer(data, "monthly_fee_cents", minimum=0)
    _require_agreement_status(agreement, "DRAFT")
    if service_domain in config.CLINICAL_DOMAINS:
        raise ApiError(
            "ERR_CORPORATE_PRACTICE_VIOLATION",
            "A clinical service domain may not be bought by the support organization.",
        )
    for existing in derive.line_items_of_agreement(agreement["id"]):
        if existing["service_code"] == service_code:
            raise ApiError(
                "ERR_DUPLICATE_SERVICE_CODE",
                "That service code already appears on this agreement.",
            )
    row = db.insert(
        "service_line_items",
        {
            "service_agreement_id": agreement["id"],
            "service_code": service_code,
            "service_domain": service_domain,
            "is_clinical": False,
            "monthly_fee_cents": monthly_fee_cents,
        },
        versioned=False,
    )
    # Each accepted line increments the agreement's line_item_count and version.
    uow.touch(agreement)
    return "service_line_items", row, 201


@bp.get("/service-agreements/<id>/line-items")
def list_line_items(id):
    middleware.authorize(
        [
            config.ROLE_DEAL_COUNSEL,
            config.ROLE_INTEGRATION_LEAD,
            config.ROLE_FINANCE_CONTROLLER,
            config.ROLE_CLINICAL_DIRECTOR,
        ]
    )
    agreement = support.load("service_agreements", id)
    rows = derive.line_items_of_agreement(agreement["id"])
    return support.read_many("service_line_items", rows)


@bp.post("/service-agreements/<service_agreement_id>/submit-legal-review")
@support.transactional
def submit_legal_review(service_agreement_id):
    middleware.authorize([config.ROLE_DEAL_COUNSEL])
    agreement = support.load("service_agreements", service_agreement_id)
    payload.body()
    _require_agreement_status(agreement, "DRAFT")
    if derive.line_item_count(agreement) < 1:
        raise ApiError(
            "ERR_SERVICE_SCOPE_EMPTY",
            "The agreement scope carries no line items.",
        )
    agreement["status"] = "LEGAL_REVIEW"
    agreement["review_round"] += 1
    uow.touch(agreement)
    return "service_agreements", agreement, 200


@bp.post("/service-agreements/<service_agreement_id>/reject-scope")
@support.transactional
def reject_scope(service_agreement_id):
    middleware.authorize([config.ROLE_DEAL_COUNSEL])
    agreement = support.load("service_agreements", service_agreement_id)
    data = payload.body()
    finding_count = payload.integer(data, "finding_count", minimum=0)
    payload.string(data, "finding_note", required=False)
    _require_agreement_status(agreement, "LEGAL_REVIEW")
    agreement["status"] = "DRAFT"
    agreement["scope_findings_count"] += finding_count
    uow.touch(agreement)
    return "service_agreements", agreement, 200


@bp.post("/service-agreements/<service_agreement_id>/make-effective")
@support.transactional
def make_effective(service_agreement_id):
    middleware.authorize([config.ROLE_DEAL_COUNSEL])
    agreement = support.load("service_agreements", service_agreement_id)
    payload.body()
    practice = db.get("practices", agreement["practice_id"])
    affiliation = derive.affiliation_of_practice(practice)
    if affiliation["status"] not in ("SIGNED", "CLOSED"):
        raise ApiError(
            "ERR_INVALID_AFFILIATION_STATE",
            "The affiliation must be SIGNED or CLOSED before an agreement goes live.",
        )
    _require_agreement_status(agreement, "LEGAL_REVIEW")
    if agreement["mgmt_fee_bps"] > config.MAX_MGMT_FEE_BPS:
        raise ApiError(
            "ERR_MGMT_FEE_CAP_EXCEEDED",
            "mgmt_fee_bps exceeds the %d basis point ceiling."
            % config.MAX_MGMT_FEE_BPS,
        )
    agreement["status"] = "EFFECTIVE"
    agreement["effective_date"] = clock.now()
    uow.touch(agreement)
    return "service_agreements", agreement, 200
