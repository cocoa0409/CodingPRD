"""Determination openings, revision rounds, preparation and certification
(PRD sections 3.4, 3.5 and 3.6)."""

from flask import Blueprint, g, request

import db as dbmod
import lookup
import response
import serializers
import shape
from auth import ALL_ROLES, CLAIMS_AGENT, CLAIMS_CERTIFIER, require
from db import db, new_row, touch
from errors import ApiError
from services import determination as determination_service
from services import insurance

bp = Blueprint("determinations", __name__)


@bp.post("/insurance-determinations")
@require(CLAIMS_AGENT)
def open_determination():
    raw = shape.raw_body()
    depositor = None
    if shape.present(raw, "depositor_record_id"):
        depositor = lookup.depositor(raw["depositor_record_id"])

    payload = shape.body()
    shape.req_id(payload, "depositor_record_id")
    expected_version = shape.req_int(payload, "expected_depositor_record_version")
    revision_reason = shape.opt_str(payload, "revision_reason", min_len=1)

    # Stage 7: the stale-view guard runs before the lifecycle guards.
    if expected_version != depositor["version"]:
        raise ApiError("ERR_STALE_DEPOSITOR_VERSION")

    if determination_service.active_determination_of(depositor["id"]) is not None:
        raise ApiError("ERR_ACTIVE_DETERMINATION_EXISTS")

    prior = determination_service.certified_determination_of(depositor["id"])
    revision_round = 0
    if prior is not None:
        certificate = determination_service.certificate_of(prior["id"])
        if certificate is not None and certificate["cumulative_dividends_cents"] > 0:
            # Money has already moved against the claim, so the position can no
            # longer be quietly rewritten.
            raise ApiError("ERR_CERTIFICATE_ALREADY_PAID")
        revision_round = prior["revision_round"] + 1

    institution = lookup.institution_of_depositor(depositor)

    row = new_row(
        {
            "depositor_record_id": depositor["id"],
            "status": "DRAFT",
            "method_variant": None,
            "insured_amount_cents": 0,
            "uninsured_amount_cents": 0,
            "attributed_total_cents": 0,
            "category_breakdown": {},
            "prepared_by_user_id": None,
            "certified_by_user_id": None,
            "revision_round": revision_round,
            "revision_reason": revision_reason,
            "prepared_at": None,
            "certified_at": None,
        }
    )
    db.determinations[row["id"]] = row

    if prior is not None:
        determination_service.supersede(prior, depositor, institution)

    # Every successful opening bumps the parent depositor record's version, which
    # is what makes the concurrency guard of PRD 2.9 self-invalidating.
    touch(depositor)
    return response.created(serializers.determination(row))


@bp.get("/insurance-determinations")
@require(ALL_ROLES)
def list_determinations():
    rows = list(db.determinations.values())
    for field in ("depositor_record_id", "status", "method_variant"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return response.paginated(dbmod.ordered(rows), serializers.determination)


@bp.get("/insurance-determinations/<determination_id>")
@require(ALL_ROLES)
def get_determination(determination_id):
    return response.ok(
        serializers.determination(lookup.determination(determination_id))
    )


@bp.post("/insurance-determinations/<determination_id>/prepare")
@require(CLAIMS_AGENT)
def prepare_determination(determination_id):
    determination = lookup.determination(determination_id)
    payload = shape.body()
    method_variant = shape.req_enum(
        payload, "method_variant", determination_service.METHOD_VARIANTS
    )

    depositor = lookup.depositor(determination["depositor_record_id"])
    institution = lookup.institution_of_depositor(depositor)

    # Three guards, in the order PRD 3.4 pins them.
    if determination["status"] not in determination_service.PREPARABLE_STATUSES:
        raise ApiError("ERR_DETERMINATION_NOT_PREPARABLE")
    if institution is None or institution["status"] != "CLOSED_IN_RECEIVERSHIP":
        raise ApiError("ERR_INSTITUTION_NOT_CLOSED")
    accounts = insurance.eligible_accounts(depositor["institution_id"])
    insurance.validate_joint_shares(depositor["id"], accounts)

    determination_service.prepare(determination, depositor, method_variant, g.user_id)
    return response.ok(serializers.determination(determination))


@bp.post("/insurance-determinations/<determination_id>/submit-review")
@require(CLAIMS_AGENT)
def submit_review(determination_id):
    determination = lookup.determination(determination_id)
    shape.body()

    if (
        determination["status"] != "PREPARED"
        or determination["prepared_by_user_id"] is None
    ):
        raise ApiError("ERR_DETERMINATION_NOT_PREPARED")

    determination["status"] = "UNDER_REVIEW"
    touch(determination)
    return response.ok(serializers.determination(determination))


@bp.post("/insurance-determinations/<determination_id>/certify")
@require(CLAIMS_CERTIFIER)
def certify_determination(determination_id):
    determination = lookup.determination(determination_id)
    shape.body()

    depositor = lookup.depositor(determination["depositor_record_id"])
    institution = lookup.institution_of_depositor(depositor)

    # Four guards, in the order PRD 3.6 pins them.
    if determination["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_DETERMINATION_NOT_UNDER_REVIEW")
    if institution is None or institution["status"] != "CLOSED_IN_RECEIVERSHIP":
        raise ApiError("ERR_INSTITUTION_NOT_CLOSED")
    if g.user_id == determination["prepared_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES_VIOLATION")
    if determination["method_variant"] != "AGGREGATE_BY_CATEGORY":
        raise ApiError("ERR_PROVISIONAL_VARIANT_NOT_CERTIFIABLE")

    determination_service.certify(determination, depositor, institution, g.user_id)
    return response.ok(serializers.determination(determination))


@bp.post("/insurance-determinations/<determination_id>/request-revision")
@require(CLAIMS_CERTIFIER)
def request_revision(determination_id):
    determination = lookup.determination(determination_id)
    payload = shape.body()
    revision_reason = shape.req_str(payload, "revision_reason", min_len=1)

    if determination["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_DETERMINATION_NOT_UNDER_REVIEW")

    determination["revision_reason"] = revision_reason
    determination["revision_round"] = determination["revision_round"] + 1
    determination["status"] = "REVISION_REQUESTED"
    touch(determination)
    return response.ok(serializers.determination(determination))
