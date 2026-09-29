"""PRD 3.1 membership agreement negotiation (bounded SENT <-> COUNTERED cycle)."""
from flask import Blueprint

import auth
import clock
import db
import response
import services
import validators as v
from errors import ApiError

bp = Blueprint("agreements", __name__)

SHARED_SERVICES = ("ENROLLMENT", "BILLING", "FOOD_PROGRAM", "SUBSTITUTE_POOL", "GROUP_PURCHASING")
NEGOTIATION_MAX_ROUNDS = 3
SUPERSEDE_REASON = "SUPERSEDED_BY_NEWER_AGREEMENT"


def _agreement(actor, agreement_id):
    row = services.find_or_404(
        db.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND", "membership agreement"
    )
    auth.scope_provider(actor, row["provider_id"])
    return row


@bp.post("/fccn/membership-agreements")
def issue_agreement():
    auth.require_auth(("NetworkAdmin",))
    body = v.get_body()
    # ladder 6: body reference existence, before the rest of the shape checks
    provider_id = v.req_str(body, "provider_id")
    provider = services.provider_or_404(provider_id)

    network_fee_pct = v.req_number(body, "network_fee_pct", 0, 15)
    shared_services = v.req_enum_array(body, "shared_services", SHARED_SERVICES)
    effective_on = v.req_instant(body, "effective_on")
    expected_provider_version = v.req_int(body, "expected_provider_version", 0)

    if expected_provider_version != provider["version"]:
        raise ApiError(
            "ERR_STALE_PROVIDER_VERSION",
            "The provider's version has advanced since it was last observed.",
        )

    row = db.make_row(
        provider_id=provider["id"],
        network_fee_pct=network_fee_pct,
        proposed_network_fee_pct=None,
        shared_services=shared_services,
        effective_on=effective_on,
        round_index=1,
        status="SENT",
        superseded=False,
        withdrawal_reason=None,
        executed_at=None,
    )
    services.register_new(row)

    # Issuing supersedes anything still under negotiation for this provider.
    for other in db.by_created_at(services.provider_children(db.agreements, provider["id"])):
        if other["id"] == row["id"]:
            continue
        if other["status"] in ("SENT", "COUNTERED"):
            other["status"] = "WITHDRAWN"
            other["superseded"] = True
            other["withdrawal_reason"] = SUPERSEDE_REASON
            services.touch(other)
    services.touch(provider)

    db.agreements[row["id"]] = row
    return response.created(row)


@bp.post("/fccn/membership-agreements/<agreement_id>/counter")
def counter_agreement(agreement_id):
    actor = auth.require_auth(("Provider",))
    agreement = _agreement(actor, agreement_id)
    body = v.get_body()
    v.reject_unversioned(body)
    proposed = v.req_number(body, "proposed_network_fee_pct", 0, 15)

    if agreement["status"] != "SENT":
        raise ApiError("ERR_INVALID_AGREEMENT_STATE", "Only a SENT agreement may be countered.")
    if agreement["round_index"] >= NEGOTIATION_MAX_ROUNDS:
        raise ApiError(
            "ERR_NEGOTIATION_ROUNDS_EXHAUSTED",
            "The negotiation is bounded at %d rounds." % NEGOTIATION_MAX_ROUNDS,
        )

    agreement["proposed_network_fee_pct"] = proposed
    agreement["round_index"] += 1
    agreement["status"] = "COUNTERED"
    services.touch(agreement)
    return response.ok(agreement)


@bp.post("/fccn/membership-agreements/<agreement_id>/revise")
def revise_agreement(agreement_id):
    auth.require_auth(("NetworkAdmin",))
    agreement = services.find_or_404(
        db.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND", "membership agreement"
    )
    body = v.get_body()
    v.reject_unversioned(body)
    network_fee_pct = v.req_number(body, "network_fee_pct", 0, 15)

    if agreement["status"] != "COUNTERED":
        raise ApiError("ERR_INVALID_AGREEMENT_STATE", "Only a COUNTERED agreement may be revised.")

    agreement["network_fee_pct"] = network_fee_pct
    agreement["proposed_network_fee_pct"] = None
    agreement["status"] = "SENT"
    services.touch(agreement)
    return response.ok(agreement)


@bp.post("/fccn/membership-agreements/<agreement_id>/execute")
def execute_agreement(agreement_id):
    actor = auth.require_auth(("Provider",))
    agreement = _agreement(actor, agreement_id)
    provider = db.providers[agreement["provider_id"]]

    if agreement["status"] != "SENT":
        raise ApiError("ERR_INVALID_AGREEMENT_STATE", "Only a SENT agreement may be executed.")
    if provider["membership_status"] != "PENDING_AGREEMENT":
        raise ApiError(
            "ERR_INVALID_PROVIDER_STATE",
            "The provider must be PENDING_AGREEMENT to execute an agreement.",
        )
    expires = clock.parse_instant(provider.get("license_expires_on"))
    if expires is None or expires <= clock.now():
        raise ApiError("ERR_LICENSE_EXPIRED", "The provider's license is not current.")

    agreement["status"] = "EXECUTED"
    agreement["executed_at"] = clock.now_raw()
    services.touch(agreement)

    provider["network_fee_pct"] = agreement["network_fee_pct"]
    services.set_membership_status(provider, "ACTIVE")
    return response.ok(agreement)


@bp.post("/fccn/membership-agreements/<agreement_id>/withdraw")
def withdraw_agreement(agreement_id):
    auth.require_auth(("NetworkAdmin",))
    agreement = services.find_or_404(
        db.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND", "membership agreement"
    )
    body = v.get_body()
    v.reject_unversioned(body)
    reason = v.req_str(body, "reason")

    if agreement["status"] not in ("SENT", "COUNTERED"):
        raise ApiError(
            "ERR_INVALID_AGREEMENT_STATE",
            "Only an agreement still under negotiation may be withdrawn.",
        )

    agreement["status"] = "WITHDRAWN"
    agreement["withdrawal_reason"] = reason
    services.touch(agreement)
    return response.ok(agreement)


@bp.get("/fccn/membership-agreements/<agreement_id>")
def read_agreement(agreement_id):
    actor = auth.require_auth(("NetworkAdmin", "Provider"))
    return response.ok(_agreement(actor, agreement_id))
