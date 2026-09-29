"""Handset registration, attestation, loss, recovery and remote wipe."""

from flask import Blueprint

import cascade
import derive
import gates
import lookup
import serialize
import validate as v
from auth import endpoint
from envelope import ok
from errors import ApiError
from store import base_row, db, now, profile_settings, sort_rows, touch

bp = Blueprint("device", __name__, url_prefix="/mdl")

PLATFORMS = ("IOS", "ANDROID")
PROTECTION_METHODS = ("BIOMETRIC", "PASSCODE")
ATTESTATION_RESULTS = ("PASS", "FAIL")
SECURE_ELEMENT_GRADES = ("HARDWARE_STRONGBOX", "HARDWARE_TEE", "SOFTWARE")


@endpoint(bp, "/devices", ["POST"], ["Holder", "SystemAdmin"])
def register_device():
    body = v.body()
    holder_id = v.req_str(body, "holder_id")
    platform = v.req_enum(body, "platform", PLATFORMS)
    model_name = v.req_str(body, "model_name")
    attestation_token = v.req_str(body, "hardware_attestation_token")
    protection_method = v.req_enum(body, "protection_method", PROTECTION_METHODS)

    holder = lookup.holder(holder_id)

    row = base_row("Device")
    row["holder_id"] = holder["id"]
    row["platform"] = platform
    row["model_name"] = model_name
    row["hardware_attestation_token"] = attestation_token
    row["protection_method"] = protection_method
    row["state"] = "REGISTERED"
    row["attestation_result"] = None
    row["secure_element_grade"] = None
    row["lost_reported_at"] = None
    row["reprovision_count"] = 0
    db.devices[row["id"]] = row
    return ok(serialize.dump(row), 201)


@endpoint(bp, "/devices/<device_id>", ["GET"],
          ["Holder", "SystemAdmin", "CredentialAdjudicator", "PrivacyAuditor"])
def read_device(device_id):
    row = lookup.device(device_id)
    return ok(serialize.dump(row))


@endpoint(bp, "/devices/<device_id>/attest", ["POST"], ["SystemAdmin"])
def attest_device(device_id):
    body = v.body()
    result = v.req_enum(body, "attestation_result", ATTESTATION_RESULTS)
    grade = v.req_enum(body, "secure_element_grade", SECURE_ELEMENT_GRADES)

    device = lookup.device(device_id)
    if device["state"] != "REGISTERED":
        raise ApiError("ERR_INVALID_STATE")

    holder = db.holders.get(device["holder_id"])
    if result == "PASS":
        cap = profile_settings()["max_devices_per_holder"]
        if derive.bound_device_count(holder["id"]) >= cap:
            raise ApiError("ERR_DEVICE_LIMIT_EXCEEDED")

    device["attestation_result"] = result
    device["secure_element_grade"] = grade
    device["state"] = "ATTESTED" if result == "PASS" else "RETIRED"
    touch(device)
    return ok(serialize.dump(device))


@endpoint(bp, "/devices/<device_id>/report-lost", ["POST"], ["Holder", "SystemAdmin"])
def report_device_lost(device_id):
    device = lookup.device(device_id)
    gates.require_holder_owner(device["holder_id"])
    if device["state"] != "BOUND":
        raise ApiError("ERR_INVALID_STATE")

    device["state"] = "LOST_REPORTED"
    device["lost_reported_at"] = now()
    touch(device)

    for credential in sort_rows(derive.credentials_of_device(device["id"])):
        if credential["lifecycle_state"] == "ACTIVE":
            cascade.suspend_credential(
                credential, "DEVICE_LOST", "SUSPENDED", "DEVICE_LOST"
            )
    return ok(serialize.dump(device))


@endpoint(bp, "/devices/<device_id>/recover", ["POST"], ["Holder", "SystemAdmin"])
def recover_device(device_id):
    body = v.body()
    v.req_str(body, "reattestation_token")

    device = lookup.device(device_id)
    gates.require_holder_owner(device["holder_id"])
    if device["state"] != "LOST_REPORTED":
        raise ApiError("ERR_INVALID_STATE")

    device["state"] = "BOUND"
    device["lost_reported_at"] = None
    touch(device)

    for credential in sort_rows(derive.credentials_of_device(device["id"])):
        if (credential["lifecycle_state"] == "SUSPENDED"
                and credential.get("suspend_reason") == "DEVICE_LOST"
                and now() < credential["valid_until"]):
            cascade.reinstate_credential(credential)
    return ok(serialize.dump(device))


@endpoint(bp, "/devices/<device_id>/wipe", ["POST"], ["SystemAdmin"])
def wipe_device(device_id):
    device = lookup.device(device_id)
    if device["state"] != "LOST_REPORTED":
        raise ApiError("ERR_INVALID_STATE")

    device["state"] = "WIPED"
    touch(device)

    for credential in sort_rows(derive.credentials_of_device(device["id"])):
        if credential["lifecycle_state"] == "SUSPENDED":
            cascade.revoke_credential(credential, "DEVICE_LOST")
    return ok(serialize.dump(device))
