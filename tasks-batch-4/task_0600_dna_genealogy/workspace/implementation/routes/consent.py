"""Consent grants: closed-interval windows, cooling-off and the withdrawal
cascades (PRD §2.9, §3.6)."""
from flask import Blueprint, request

import calc
import db
import services as S
from auth import endpoint, require_owner
from errors import ApiError
from response import ok, paginate
from routes.common import body

bp = Blueprint("consent", __name__)

SCOPES = ("HEALTH_TRAITS", "RELATIVE_MATCHING", "RESEARCH")


@bp.post("/dna/consent-grants")
@endpoint(["Customer"])
def create_grant():
    payload = body()
    S.require_fields(payload, ["customer_id", "scope", "effective_from", "effective_until"])
    customer = S.get("customers", payload["customer_id"])
    require_owner(customer["id"])

    scope = payload["scope"]
    S.require_enum(scope, SCOPES, "scope")
    effective_from = db.parse_dt(payload["effective_from"])
    effective_until = db.parse_dt(payload["effective_until"])
    if effective_from is None or effective_until is None:
        raise ApiError("ERR_INVALID_REQUEST", "effective_from / effective_until must be ISO 8601.")

    S.require_not_purged(customer)

    # CLOSED-interval overlap: touching endpoints DO intersect.
    for other in db.db.grants.values():
        if (
            other["customer_id"] == customer["id"]
            and other["scope"] == scope
            and other["status"] == "ACTIVE"
            and effective_from <= other["effective_until"]
            and other["effective_from"] <= effective_until
        ):
            raise ApiError("ERR_CONSENT_OVERLAP")

    # Cooling-off buffer: inclusive at exactly +24h.
    withdrawals = [
        g["withdrawn_at"]
        for g in db.db.grants.values()
        if g["customer_id"] == customer["id"]
        and g["scope"] == scope
        and g["status"] == "WITHDRAWN"
        and g["withdrawn_at"] is not None
    ]
    if withdrawals:
        earliest_allowed = max(withdrawals) + db.hours(calc.CONSENT_COOLING_OFF_HOURS)
        if effective_from < earliest_allowed:
            raise ApiError("ERR_CONSENT_COOLING_OFF")

    grant = db.new_record(
        {
            "customer_id": customer["id"],
            "scope": scope,
            "effective_from": effective_from,
            "effective_until": effective_until,
            "status": "ACTIVE",
            "withdrawn_at": None,
        }
    )
    db.db.grants[grant["id"]] = grant

    # Re-grant cascade: SUPPRESSED matches whose other side is opted in return to ACTIVE.
    if scope == "RELATIVE_MATCHING" and S.covers_now(grant):
        S.reactivate_matches_for(customer)

    return ok(S.grant_json(grant), 201)


@bp.get("/dna/consent-grants/<grant_id>")
@endpoint(["Customer", "PrivacyOfficer"])
def read_grant(grant_id):
    grant = S.get("grants", grant_id)
    require_owner(grant["customer_id"])
    return ok(S.grant_json(grant))


@bp.get("/dna/consent-grants")
@endpoint(["Customer", "PrivacyOfficer", "PlatformAdmin"])
def list_grants():
    records = S.all_of("grants")
    customer_id = request.args.get("customer_id")
    scope = request.args.get("scope")
    status = request.args.get("status")
    if customer_id:
        records = [r for r in records if r["customer_id"] == customer_id]
    if scope:
        records = [r for r in records if r["scope"] == scope]
    if status:
        records = [r for r in records if r["status"] == status]
    return paginate(records, S.grant_json)


@bp.post("/dna/consent-grants/<grant_id>/withdraw")
@endpoint(["Customer", "PrivacyOfficer"])
def withdraw_grant(grant_id):
    grant = S.get("grants", grant_id)
    require_owner(grant["customer_id"])

    customer = db.db.customers[grant["customer_id"]]
    S.require_not_purged(customer)

    if grant["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")

    grant["status"] = "WITHDRAWN"
    grant["withdrawn_at"] = db.now()
    db.touch(grant)

    if grant["scope"] == "HEALTH_TRAITS":
        S.revoke_reports(customer["id"], lambda r: r["report_type"] == "HEALTH_TRAIT")
    elif grant["scope"] == "RESEARCH":
        S.revoke_reports(customer["id"], lambda r: r["variant"] == "FINAL")
    elif grant["scope"] == "RELATIVE_MATCHING":
        if not S.matching_opt_in(customer["id"]):
            S.suppress_matches_for(customer)

    return ok(S.grant_json(grant))
