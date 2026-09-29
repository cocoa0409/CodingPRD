"""Renewal analyses: immutable leverage projections (PRD 3.9)."""
from flask import Blueprint

import constants as K
from auth import guard
from calc import renewal_leverage
from common import (
    BUSINESS_READ_ROLES,
    created,
    list_endpoint,
    read_endpoint,
    scope_from_body_agreement,
)
from lookup import must, put
from store import db, new_entity
from validation import check_body, field

bp = Blueprint("renewals", __name__)
BASE = "/carriage/renewal-analyses"


@bp.route(BASE, methods=["POST"])
def create_renewal_analysis():
    caller = guard(["AffiliateSalesExec"])
    scope_from_body_agreement(caller)
    body = check_body(
        {
            "agreement_id": field("id", required=True),
            "variant": field("enum", required=True, enum=K.RENEWAL_VARIANTS),
        }
    )
    # The validations table does not gate this projection on lifecycle state:
    # a model may be run against any agreement the exec can see.
    agreement = must("agreement", body["agreement_id"])
    distributor = db.distributors.get(agreement["distributor_id"])

    # id and created_at only: the analysis is a snapshot, never updated.
    record = new_entity(versioned=False, created=True)
    record.update(
        {
            "agreement_id": agreement["id"],
            "variant": body["variant"],
        }
    )
    record.update(renewal_leverage(agreement, distributor, body["variant"]))
    put("analysis", record)
    # Running a model does not move renewal_status.
    return created(record)


@bp.route(BASE, methods=["GET"])
def list_renewal_analyses():
    return list_endpoint(
        "analysis",
        BUSINESS_READ_ROLES,
        ["agreement_id", "variant", "latest_accepted_report_id"],
    )


@bp.route(BASE + "/<analysis_id>", methods=["GET"])
def read_renewal_analysis(analysis_id):
    return read_endpoint("analysis", BUSINESS_READ_ROLES, analysis_id)
