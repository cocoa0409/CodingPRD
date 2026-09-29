"""Dividend declaration, settlement and voiding (PRD section 3.9).

Voiding reverses a settlement exactly, which is only possible for the latest
settled round because each certificate remembers only its most recent payment.
"""

from flask import Blueprint, request

import db as dbmod
import lookup
import response
import serializers
import shape
from auth import ALL_ROLES, RECEIVERSHIP_TRUSTEE, require
from db import db, new_row, touch
from errors import ApiError
from services import aggregates
from services import dividend as dividend_service

bp = Blueprint("dividends", __name__)


@bp.post("/institutions/<institution_id>/dividend-distributions")
@require(RECEIVERSHIP_TRUSTEE)
def declare_distribution(institution_id):
    institution = lookup.institution(institution_id)
    payload = shape.body()
    priority_class = shape.req_enum(
        payload, "priority_class", dividend_service.PRIORITY_CLASSES
    )
    declared_rate_bps = shape.req_int(
        payload, "declared_rate_bps", minimum=1, maximum=10000
    )
    expected_version = shape.req_int(payload, "expected_institution_version")

    # Stage 7: the stale-view guard is evaluated before the ordering guard.
    if expected_version != institution["version"]:
        raise ApiError("ERR_STALE_INSTITUTION_VERSION")

    if priority_class == "INSURED_SUBROGATION":
        for existing in lookup.distributions_of(institution_id):
            if (
                existing["priority_class"] == "GENERAL_UNSECURED"
                and existing["status"] == "SETTLED"
            ):
                raise ApiError("ERR_PRIORITY_CLASS_OUT_OF_ORDER")

    row = new_row(
        {
            "institution_id": institution_id,
            "distribution_round": aggregates.dividend_round_count(institution_id) + 1,
            "priority_class": priority_class,
            "declared_rate_bps": declared_rate_bps,
            "status": "DECLARED",
            "total_distributed_cents": 0,
            "certificate_count": 0,
            "settled_at": None,
            "voided_at": None,
        }
    )
    db.distributions[row["id"]] = row
    touch(institution)
    return response.created(serializers.distribution(row))


@bp.get("/dividend-distributions")
@require(ALL_ROLES)
def list_distributions():
    rows = list(db.distributions.values())
    for field in ("institution_id", "status", "priority_class"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return response.paginated(dbmod.ordered(rows), serializers.distribution)


@bp.get("/dividend-distributions/<distribution_id>")
@require(ALL_ROLES)
def get_distribution(distribution_id):
    return response.ok(serializers.distribution(lookup.distribution(distribution_id)))


@bp.post("/dividend-distributions/<distribution_id>/settle")
@require(RECEIVERSHIP_TRUSTEE)
def settle_distribution(distribution_id):
    distribution = lookup.distribution(distribution_id)
    shape.body()
    institution = lookup.institution(distribution["institution_id"])

    if distribution["status"] != "DECLARED":
        raise ApiError("ERR_DISTRIBUTION_NOT_DECLARED")

    total, certificate_count, allocations = dividend_service.allocate(
        institution, distribution
    )

    # Fiscal guards last: the payout is checked against available cash before
    # anything is written, and a total exactly equal to the cash is allowed.
    if total > aggregates.receivership_cash_cents(institution):
        raise ApiError("ERR_INSUFFICIENT_RECEIVERSHIP_CASH")

    for certificate, payable in allocations:
        if payable <= 0:
            # A certificate allocated exactly zero cents keeps its status.
            continue
        certificate["cumulative_dividends_cents"] += payable
        certificate["last_dividend_amount_cents"] = payable
        certificate["last_dividend_round"] = distribution["distribution_round"]
        certificate["status"] = dividend_service.certificate_status_for(certificate)
        touch(certificate)

    distribution["total_distributed_cents"] = total
    distribution["certificate_count"] = certificate_count
    distribution["settled_at"] = db.now_iso()
    distribution["status"] = "SETTLED"
    touch(distribution)
    touch(institution)
    return response.ok(serializers.distribution(distribution))


@bp.post("/dividend-distributions/<distribution_id>/void")
@require(RECEIVERSHIP_TRUSTEE)
def void_distribution(distribution_id):
    distribution = lookup.distribution(distribution_id)
    shape.body()
    institution = lookup.institution(distribution["institution_id"])

    if distribution["status"] != "SETTLED":
        raise ApiError("ERR_DISTRIBUTION_NOT_SETTLED")

    settled_rounds = [
        d
        for d in lookup.distributions_of(distribution["institution_id"])
        if d["status"] == "SETTLED"
    ]
    highest = max(d["distribution_round"] for d in settled_rounds)
    if distribution["distribution_round"] != highest:
        raise ApiError("ERR_NOT_LATEST_DIVIDEND_ROUND")

    for certificate in dbmod.ordered(
        lookup.certificates_of_institution(distribution["institution_id"])
    ):
        if certificate["last_dividend_round"] != distribution["distribution_round"]:
            continue
        certificate["cumulative_dividends_cents"] -= certificate[
            "last_dividend_amount_cents"
        ]
        certificate["last_dividend_amount_cents"] = 0
        certificate["last_dividend_round"] = 0
        certificate["status"] = dividend_service.certificate_status_for(certificate)
        touch(certificate)

    distribution["status"] = "VOIDED"
    distribution["voided_at"] = db.now_iso()
    # total_distributed_cents is kept for audit rather than zeroed.
    touch(distribution)
    touch(institution)
    return response.ok(serializers.distribution(distribution))
