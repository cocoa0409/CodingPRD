"""HSM partitions and key ceremonies (PRD 3.6)."""

import datetime

from flask import Blueprint

from db import db, make_record, public, sort_records, touch
from errors import fail
from filters import apply_filters
from middleware import ALL_ROLES, authenticate, json_body, read_only
from response import created, ok, paginated
from services import cascade
from services.lookup import get_ceremony, get_partition
from validation import in_range, req_int, req_str, req_ts

bp = Blueprint("partitions", __name__)

BUFFER = datetime.timedelta(minutes=60)
BLOCKING_STATES = ("SCHEDULED", "WITNESSED", "ATTESTED")


@bp.route("/ca/hsm-partitions", methods=["POST"])
def create_partition():
    authenticate(("POLICY_ADMIN",))
    body = json_body()
    label = req_str(body, "label", 1, 60)
    serial = req_str(body, "serial", 1, 40)

    for existing in db.partitions.values():
        if existing["serial"] == serial:
            fail("ERR_PARTITION_SERIAL_DUPLICATE", "That hardware serial is already registered.")

    record = make_record({
        "label": label,
        "serial": serial,
        "state": "OPERATIONAL",
        "quarantined_at": None,
        "attested_ceremony_count": 0,
    })
    db.partitions[record["id"]] = record
    return created(public(record))


@bp.route("/ca/hsm-partitions", methods=["GET"])
def list_partitions():
    read_only(ALL_ROLES)
    records = apply_filters(db.partitions.values(), {"state": "str"})
    return paginated(sort_records(records))


@bp.route("/ca/hsm-partitions/<partition_id>", methods=["GET"])
def get_one_partition(partition_id):
    read_only(ALL_ROLES)
    return ok(public(get_partition(partition_id)))


@bp.route("/ca/hsm-partitions/<partition_id>/key-ceremonies", methods=["POST"])
def create_ceremony(partition_id):
    authenticate(("ISSUANCE_OPERATOR",))
    body = json_body()
    window_start = req_ts(body, "window_start")
    window_end = req_ts(body, "window_end")
    attestation_valid_days = req_int(body, "attestation_valid_days")
    in_range(attestation_valid_days, 1, 365, "attestation_valid_days")

    partition = get_partition(partition_id)

    if partition["state"] != "OPERATIONAL":
        fail("ERR_PARTITION_QUARANTINED", "The partition is quarantined.")

    if window_end <= window_start:
        fail("ERR_INVALID_CEREMONY_WINDOW", "window_end must be strictly after window_start.")

    for existing in db.ceremonies.values():
        if existing["partition_id"] != partition["id"]:
            continue
        if existing["state"] not in BLOCKING_STATES:
            continue
        if (window_start <= existing["window_end"] + BUFFER
                and existing["window_start"] <= window_end + BUFFER):
            fail("ERR_CEREMONY_WINDOW_CONFLICT", "The window conflicts with another ceremony.")

    record = make_record({
        "partition_id": partition["id"],
        "window_start": window_start,
        "window_end": window_end,
        "attestation_valid_days": attestation_valid_days,
        "state": "SCHEDULED",
        "witness_user_ids": [],
        "witness_count": 0,
        "attested_at": None,
        "attested_by_user_id": None,
        "attestation_expires_at": None,
        "attestation_revoked_at": None,
        "issued_certificate_count": 0,
    })
    db.ceremonies[record["id"]] = record
    return created(public(record))


@bp.route("/ca/hsm-partitions/<partition_id>/key-ceremonies", methods=["GET"])
def list_ceremonies(partition_id):
    read_only(ALL_ROLES)
    partition = get_partition(partition_id)
    records = [c for c in db.ceremonies.values() if c["partition_id"] == partition["id"]]
    records = apply_filters(records, {"state": "str"})
    records = sorted(records, key=lambda c: (c["window_start"], c["_seq"]))
    return paginated(records)


@bp.route("/ca/key-ceremonies/<ceremony_id>", methods=["GET"])
def get_one_ceremony(ceremony_id):
    read_only(ALL_ROLES)
    return ok(public(get_ceremony(ceremony_id)))


@bp.route("/ca/key-ceremonies/<ceremony_id>/witness", methods=["POST"])
def witness_ceremony(ceremony_id):
    user_id, _role = authenticate(("ISSUANCE_OPERATOR", "COMPLIANCE_AUDITOR"))
    ceremony = get_ceremony(ceremony_id)

    if ceremony["state"] != "SCHEDULED":
        fail("ERR_CEREMONY_NOT_SCHEDULED", "The ceremony is not SCHEDULED.")
    if user_id in ceremony["witness_user_ids"]:
        fail("ERR_DUPLICATE_WITNESS", "This user has already witnessed the ceremony.")

    ceremony["witness_user_ids"] = list(ceremony["witness_user_ids"]) + [user_id]
    ceremony["witness_count"] = len(ceremony["witness_user_ids"])
    if ceremony["witness_count"] >= 2:
        ceremony["state"] = "WITNESSED"
    touch(ceremony)
    return ok(public(ceremony))


@bp.route("/ca/key-ceremonies/<ceremony_id>/attest", methods=["POST"])
def attest_ceremony(ceremony_id):
    user_id, _role = authenticate(("COMPLIANCE_AUDITOR",))
    ceremony = get_ceremony(ceremony_id)
    partition = db.partitions.get(ceremony["partition_id"])

    if partition is not None and partition["state"] != "OPERATIONAL":
        fail("ERR_PARTITION_QUARANTINED", "The partition is quarantined.")
    if ceremony["state"] != "WITNESSED":
        fail("ERR_CEREMONY_NOT_WITNESSED", "The ceremony is not WITNESSED.")
    if user_id in ceremony["witness_user_ids"]:
        fail("ERR_ATTESTER_WAS_WITNESS", "A witness may not attest the ceremony.")
    now = db.now()
    if now < ceremony["window_end"]:
        fail("ERR_CEREMONY_WINDOW_OPEN", "The ceremony window has not closed yet.")

    ceremony["state"] = "ATTESTED"
    ceremony["attested_at"] = now
    ceremony["attested_by_user_id"] = user_id
    ceremony["attestation_expires_at"] = now + datetime.timedelta(
        days=ceremony["attestation_valid_days"]
    )
    touch(ceremony)
    if partition is not None:
        partition["attested_ceremony_count"] += 1
        touch(partition)
    return ok(public(ceremony))


@bp.route("/ca/key-ceremonies/<ceremony_id>/revoke-attestation", methods=["POST"])
def revoke_attestation(ceremony_id):
    authenticate(("COMPLIANCE_AUDITOR",))
    body = json_body()
    req_str(body, "reason")
    ceremony = get_ceremony(ceremony_id)
    if ceremony["state"] != "ATTESTED":
        fail("ERR_CEREMONY_NOT_ATTESTED", "Only an ATTESTED ceremony may be repudiated.")
    cascade.cascade_revoke_attestation(ceremony)
    return ok(public(ceremony))


@bp.route("/ca/key-ceremonies/<ceremony_id>/abort", methods=["POST"])
def abort_ceremony(ceremony_id):
    authenticate(("ISSUANCE_OPERATOR",))
    body = json_body()
    req_str(body, "reason")
    ceremony = get_ceremony(ceremony_id)
    if ceremony["state"] not in ("SCHEDULED", "WITNESSED"):
        fail("ERR_CEREMONY_NOT_ABORTABLE", "Only a SCHEDULED or WITNESSED ceremony may be aborted.")
    ceremony["state"] = "ABORTED"
    touch(ceremony)
    return ok(public(ceremony))
