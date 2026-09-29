"""Provisioning, activation, renewal and revocation of digital credentials."""

from flask import Blueprint

import calc
import cascade
import derive
import gates
import lookup
import serialize
import validate as v
from auth import endpoint
from envelope import ok, ok_list
from errors import ApiError
from store import base_row, db, iso, now, profile_settings, sort_rows, touch

bp = Blueprint("credential", __name__, url_prefix="/mdl")

LIFECYCLE_STATES = (
    "PENDING_PROVISION", "ACTIVE", "SUSPENDED", "REPLACED", "REVOKED", "EXPIRED",
)
SYNC_STATES = ("IN_SYNC", "UPDATE_PENDING", "UPDATE_FAILED", "STALE")
DELIVERY_STATUSES = ("PENDING", "DELIVERED", "FAILED", "SUPERSEDED")
PROTECTION_METHODS = ("BIOMETRIC", "PASSCODE")
REVOCATION_REASONS = (
    "DEVICE_LOST", "HOLDER_REQUEST", "FRAUD", "PHYSICAL_CREDENTIAL_REVOKED",
    "RENEWAL_SUPERSEDE", "ADMIN_HOLD", "RECOVERY", "VALIDITY_LAPSED", "UPDATE_FAILED",
)
LIVE_STATES = ("PENDING_PROVISION", "ACTIVE", "SUSPENDED")


@endpoint(bp, "/credentials", ["POST"], ["CredentialAdjudicator"])
def provision_credential():
    body = v.body()
    holder_id = v.req_str(body, "holder_id")
    device_id = v.req_str(body, "device_id")
    proofing_session_id = v.req_str(body, "proofing_session_id")
    valid_from = v.req_dt(body, "valid_from")
    valid_until = v.req_dt(body, "valid_until")
    v.interval(valid_from, valid_until, "valid_from", "valid_until")
    expected_device_version = v.req_int(body, "expected_device_version")
    supersedes_id = v.opt_str(body, "supersedes_credential_id")
    expedite = v.opt_bool(body, "expedite", False)

    # ladder step 5: body foreign keys resolve in the endpoint's declared order
    holder = lookup.holder(holder_id)
    device = lookup.device(device_id)
    session = lookup.proofing_session(proofing_session_id)
    prior = lookup.credential(supersedes_id) if supersedes_id is not None else None

    cascade.lazy_expire_proofing(session)

    # step 7: declared source states
    if session["state"] not in ("VERIFIED", "EXPIRED"):
        raise ApiError("ERR_INVALID_STATE")
    if prior is not None and prior["lifecycle_state"] == "REPLACED":
        raise ApiError("ERR_INVALID_STATE")

    # step 11: optimistic concurrency on the parent handset
    if expected_device_version != device["version"]:
        raise ApiError("ERR_STALE_DEVICE_VERSION")

    # step 17: device binding integrity
    if device["state"] not in ("ATTESTED", "BOUND") or device["holder_id"] != holder["id"]:
        raise ApiError("ERR_DEVICE_BINDING_MISMATCH")

    # step 18: the plastic is the root of trust
    gates.require_physical_eligible(holder)

    # step 19: the proofing assurance must still be inside its validity period
    expires_at = session.get("assurance_expires_at")
    if (session["state"] == "EXPIRED" or expires_at is None
            or expires_at <= now()):
        raise ApiError("ERR_PROOFING_ASSURANCE_EXPIRED")

    # step 20: half-open validity windows, adjacency allowed
    for other in derive.credentials_of_device(device["id"]):
        if other["lifecycle_state"] not in LIVE_STATES:
            continue
        if prior is not None and other["id"] == prior["id"]:
            continue
        if valid_from < other["valid_until"] and other["valid_from"] < valid_until:
            raise ApiError("ERR_CREDENTIAL_VALIDITY_OVERLAP")

    # step 24: assurance sufficiency against the governing profile
    required = profile_settings()["required_assurance_level"]
    if not calc.assurance_at_least(session.get("achieved_assurance_level"), required):
        raise ApiError("ERR_ASSURANCE_LEVEL_INSUFFICIENT")

    row = base_row("DigitalCredential")
    row["holder_id"] = holder["id"]
    row["device_id"] = device["id"]
    row["proofing_session_id"] = session["id"]
    row["supersedes_credential_id"] = prior["id"] if prior is not None else None
    row["lifecycle_state"] = "PENDING_PROVISION"
    row["sync_state"] = "IN_SYNC"
    row["doc_version"] = 1
    row["valid_from"] = valid_from
    row["valid_until"] = valid_until
    row["assurance_level"] = session.get("achieved_assurance_level")
    row["restriction_codes"] = list(holder.get("restriction_codes") or [])
    row["address_version_synced"] = holder["address_version"]
    row["suspend_reason"] = None
    row["activated_at"] = None
    row["protection_method_at_activation"] = None
    row["age_only_capable"] = True
    if prior is not None:
        row["reissuance_settlement_cents"] = calc.reissuance_settlement(
            prior, device["id"], expedite
        )
    else:
        row["reissuance_settlement_cents"] = 0
    db.credentials[row["id"]] = row

    # cascading effects
    session["state"] = "CONSUMED"
    touch(session)
    if device["state"] == "ATTESTED":
        device["state"] = "BOUND"
    touch(device)

    return ok(serialize.dump(row), 201)


@endpoint(bp, "/credentials/<credential_id>", ["GET"],
          ["SystemAdmin", "CredentialAdjudicator", "Holder", "PrivacyAuditor",
           "VerifierOperator"])
def read_credential(credential_id):
    row = lookup.credential(credential_id)
    cascade.lazy_expire_credential(row)
    return ok(serialize.dump(row))


@endpoint(bp, "/credentials", ["GET"],
          ["SystemAdmin", "CredentialAdjudicator", "PrivacyAuditor", "Holder"])
def list_credentials():
    limit, offset = v.pagination()
    holder_id = v.q_str("holder_id")
    device_id = v.q_str("device_id")
    proofing_session_id = v.q_str("proofing_session_id")
    supersedes_credential_id = v.q_str("supersedes_credential_id")
    lifecycle_state = v.q_enum("lifecycle_state", LIFECYCLE_STATES)
    sync_state = v.q_enum("sync_state", SYNC_STATES)

    rows = list(db.credentials.values())
    if holder_id is not None:
        rows = [c for c in rows if c["holder_id"] == holder_id]
    if device_id is not None:
        rows = [c for c in rows if c["device_id"] == device_id]
    if proofing_session_id is not None:
        rows = [c for c in rows if c["proofing_session_id"] == proofing_session_id]
    if supersedes_credential_id is not None:
        rows = [c for c in rows
                if c["supersedes_credential_id"] == supersedes_credential_id]
    if lifecycle_state is not None:
        rows = [c for c in rows if c["lifecycle_state"] == lifecycle_state]
    if sync_state is not None:
        rows = [c for c in rows if c["sync_state"] == sync_state]
    return ok_list(serialize.dump_many(sort_rows(rows)), limit, offset)


@endpoint(bp, "/credentials/<credential_id>/activate", ["POST"], ["Holder"])
def activate_credential(credential_id):
    body = v.body()
    unlock_proof = v.req_str(body, "device_unlock_proof")

    credential = lookup.credential(credential_id)

    # step 6: the resident's own credential and nobody else's
    gates.require_holder_owner(credential["holder_id"])

    # step 7: declared source state
    if credential["lifecycle_state"] != "PENDING_PROVISION":
        raise ApiError("ERR_INVALID_STATE")
    session = db.proofing_sessions.get(credential["proofing_session_id"])
    if session is None or session["state"] != "CONSUMED":
        raise ApiError("ERR_INVALID_STATE")

    device = db.devices.get(credential["device_id"])
    holder = db.holders.get(credential["holder_id"])

    # step 17: the handset must still be a legitimate carrier
    if (device is None or device["state"] not in ("ATTESTED", "BOUND")
            or device["holder_id"] != credential["holder_id"]):
        raise ApiError("ERR_DEVICE_BINDING_MISMATCH")

    # step 18: the plastic must still be eligible
    gates.require_physical_eligible(holder)

    prior_id = credential.get("supersedes_credential_id")
    prior = db.credentials.get(prior_id) if prior_id is not None else None

    # step 26: the active-credential slot cap, with the supersede exemption
    if prior is None or prior["lifecycle_state"] != "ACTIVE":
        cap = profile_settings()["max_active_credentials_per_holder"]
        if derive.active_credential_count(holder["id"]) >= cap:
            raise ApiError("ERR_ACTIVE_CREDENTIAL_LIMIT_EXCEEDED")

    # step 28: the unlock proof the resident actually reproduced
    if unlock_proof != device["protection_method"]:
        raise ApiError("ERR_PROTECTION_METHOD_MISMATCH")

    credential["lifecycle_state"] = "ACTIVE"
    credential["activated_at"] = now()
    credential["protection_method_at_activation"] = device["protection_method"]
    touch(credential)

    # displacement of the predecessor happens inside the same request
    if prior is not None and prior["lifecycle_state"] in ("ACTIVE", "SUSPENDED"):
        prior["lifecycle_state"] = "REPLACED"
        prior["suspend_reason"] = None
        touch(prior)
        cascade.append_revocation_entry(prior, "REVOKED", "RENEWAL_SUPERSEDE")
        device["reprovision_count"] += 1
        touch(device)

    return ok(serialize.dump(credential))


@endpoint(bp, "/credentials/<credential_id>/renew", ["POST"], ["CredentialAdjudicator"])
def renew_credential(credential_id):
    body = v.body()
    new_valid_until = v.req_dt(body, "new_valid_until")

    credential = lookup.credential(credential_id)
    if credential["lifecycle_state"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")

    holder = db.holders.get(credential["holder_id"])
    credential["valid_until"] = new_valid_until
    touch(credential)

    cascade.open_update_order(
        holder,
        "RENEWAL",
        "Credential %s validity extended to %s" % (credential["id"], iso(new_valid_until)),
        holder["address_version"],
    )
    return ok(serialize.dump(credential))


@endpoint(bp, "/credentials/<credential_id>/revoke", ["POST"], ["SystemAdmin"])
def revoke_credential_endpoint(credential_id):
    body = v.body()
    reason = v.req_enum(body, "reason", REVOCATION_REASONS)

    credential = lookup.credential(credential_id)
    if credential["lifecycle_state"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE")

    cascade.revoke_credential(credential, reason, "CREDENTIAL_REVOKED")
    return ok(serialize.dump(credential))


@endpoint(bp, "/credentials/<credential_id>/revocation-entries", ["GET"],
          ["SystemAdmin", "PrivacyAuditor", "VerifierOperator", "CredentialAdjudicator"])
def list_revocation_entries(credential_id):
    limit, offset = v.pagination()
    credential = lookup.credential(credential_id)
    rows = sorted(derive.entries_of_credential(credential["id"]),
                  key=lambda r: r["sequence"])
    return ok_list(serialize.dump_many(rows), limit, offset)


@endpoint(bp, "/credentials/<credential_id>/revocation-status", ["GET"],
          ["SystemAdmin", "PrivacyAuditor", "VerifierOperator", "CredentialAdjudicator"])
def read_revocation_status(credential_id):
    credential = lookup.credential(credential_id)
    projection = calc.revocation_status(credential)
    effective_at = projection["effective_at"]
    projection["effective_at"] = iso(effective_at) if effective_at is not None else None
    return ok(projection)


@endpoint(bp, "/credentials/<credential_id>/deliveries", ["GET"],
          ["SystemAdmin", "Holder"])
def list_credential_deliveries(credential_id):
    limit, offset = v.pagination()
    status = v.q_enum("status", DELIVERY_STATUSES)
    credential = lookup.credential(credential_id)
    rows = derive.deliveries_of_credential(credential["id"])
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    return ok_list(serialize.dump_many(sort_rows(rows)), limit, offset)
