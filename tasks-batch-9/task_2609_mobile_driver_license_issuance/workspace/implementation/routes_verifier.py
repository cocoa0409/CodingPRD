"""Verifier admission, trust decisions, reader applications and oversight reads."""

import secrets
from datetime import timedelta

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
from store import base_row, db, iso, now, sort_rows, touch

bp = Blueprint("verifier", __name__, url_prefix="/mdl")

CATEGORIES = ("COMMERCIAL", "LAW_ENFORCEMENT", "GOVERNMENT_SERVICE",
              "AGE_RESTRICTED_RETAIL")
TRUST_STATUSES = ("APPLIED", "APPROVED", "PROBATION", "SUSPENDED", "TERMINATED")
DECISIONS = ("APPROVE", "PROBATION", "SUSPEND", "REINSTATE", "TERMINATE")
READER_TRUST_STATES = ("PENDING", "LISTED", "DELISTED")
LIST_DECISIONS = ("LIST", "DELIST")
OUTCOMES = ("DISCLOSED", "DENIED_BY_HOLDER", "BLOCKED_BY_POLICY", "ABORTED")
BILLING_STATES = ("UNBILLED", "BILLED", "VOIDED")
TRUSTED_STATUSES = ("APPROVED", "PROBATION")


@endpoint(bp, "/verifiers", ["POST"], ["SystemAdmin"])
def create_verifier():
    body = v.body()
    organization_name = v.req_str(body, "organization_name")
    category = v.req_enum(body, "category", CATEGORIES)
    purpose_scope = v.req_array_str(body, "purpose_scope")
    retention_ceiling_days = v.req_int(body, "retention_ceiling_days", 0, 90)

    row = base_row("Verifier")
    row["organization_name"] = organization_name
    row["category"] = category
    row["purpose_scope"] = list(purpose_scope)
    row["retention_ceiling_days"] = retention_ceiling_days
    row["trust_status"] = "APPLIED"
    row["exposure_index"] = 0
    row["last_attestation_at"] = None
    row["attested_max_retention_days"] = None
    row["credited_amount_cents"] = 0
    row["probation_strike_count"] = 0
    # per-verifier secret behind the pseudonymised presentation log
    row["_salt"] = secrets.token_hex(16)
    db.verifiers[row["id"]] = row
    return ok(serialize.dump(row), 201)


@endpoint(bp, "/verifiers/<verifier_id>", ["GET"],
          ["SystemAdmin", "VerifierOperator", "PrivacyAuditor"])
def read_verifier(verifier_id):
    return ok(serialize.dump(lookup.verifier(verifier_id)))


@endpoint(bp, "/verifiers/<verifier_id>/trust-decision", ["POST"], ["SystemAdmin"])
def trust_decision(verifier_id):
    body = v.body()
    decision = v.req_enum(body, "decision", DECISIONS)

    verifier = lookup.verifier(verifier_id)
    status = verifier["trust_status"]

    if decision == "APPROVE":
        if status != "APPLIED":
            raise ApiError("ERR_INVALID_STATE")
        verifier["trust_status"] = "APPROVED"
    elif decision == "PROBATION":
        if status != "APPROVED":
            raise ApiError("ERR_INVALID_STATE")
        verifier["trust_status"] = "PROBATION"
    elif decision == "SUSPEND":
        if status not in ("APPROVED", "PROBATION"):
            raise ApiError("ERR_INVALID_STATE")
        verifier["trust_status"] = "SUSPENDED"
    elif decision == "REINSTATE":
        if status not in ("PROBATION", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE")
        if verifier["exposure_index"] >= calc.PROBATION_THRESHOLD:
            raise ApiError("ERR_INVALID_STATE")
        if status == "PROBATION" and verifier.get("last_attestation_at") is None:
            raise ApiError("ERR_INVALID_STATE")
        verifier["trust_status"] = "APPROVED"
    else:
        if status == "TERMINATED":
            raise ApiError("ERR_INVALID_STATE")
        verifier["trust_status"] = "TERMINATED"

    touch(verifier)

    if decision == "TERMINATE":
        for app in sort_rows(derive.reader_apps_of_verifier(verifier["id"])):
            if app["trust_state"] == "LISTED":
                app["trust_state"] = "DELISTED"
                touch(app)
            cascade.abort_sessions_of_reader_app(app, "VERIFIER_TERMINATED")

    return ok(serialize.dump(verifier))


@endpoint(bp, "/verifiers/<verifier_id>/retention-attestation", ["POST"],
          ["VerifierOperator"])
def retention_attestation(verifier_id):
    body = v.body()
    attested = v.req_int(body, "attested_max_retention_days", 0)

    verifier = lookup.verifier(verifier_id)
    gates.require_verifier_owner(verifier["id"])

    # the historical log is scored against the ceiling arriving in this very
    # request, over the window that ended the moment before this call.
    index, _count = calc.since_attestation_index(verifier, attested)
    verifier["exposure_index"] = index
    verifier["attested_max_retention_days"] = attested
    verifier["last_attestation_at"] = now()
    touch(verifier)
    calc.apply_exposure_thresholds(verifier, index)
    return ok(serialize.dump(verifier))


@endpoint(bp, "/verifiers/<verifier_id>/exposure-index", ["GET"],
          ["SystemAdmin", "PrivacyAuditor", "VerifierOperator"])
def read_exposure_index(verifier_id):
    verifier = lookup.verifier(verifier_id)
    rolling, rolling_count = calc.rolling_window_index(verifier)
    since, since_count = calc.since_attestation_index(verifier)
    return ok({
        "rolling_window_index": rolling,
        "rolling_window_entry_count": rolling_count,
        "since_last_attestation_index": since,
        "since_attestation_entry_count": since_count,
        "computed_at": iso(now()),
    })


@endpoint(bp, "/verifiers/<verifier_id>/invoice", ["GET"],
          ["SystemAdmin", "VerifierOperator"])
def read_invoice(verifier_id):
    verifier = lookup.verifier(verifier_id)
    return ok(calc.invoice(verifier))


@endpoint(bp, "/verifiers/<verifier_id>/reader-apps", ["GET"],
          ["SystemAdmin", "VerifierOperator", "PrivacyAuditor"])
def list_verifier_reader_apps(verifier_id):
    limit, offset = v.pagination()
    trust_state = v.q_enum("trust_state", READER_TRUST_STATES)
    app_identifier = v.q_str("app_identifier")
    verifier = lookup.verifier(verifier_id)
    rows = derive.reader_apps_of_verifier(verifier["id"])
    if trust_state is not None:
        rows = [a for a in rows if a["trust_state"] == trust_state]
    if app_identifier is not None:
        rows = [a for a in rows if a["app_identifier"] == app_identifier]
    return ok_list(serialize.dump_many(sort_rows(rows)), limit, offset)


@endpoint(bp, "/verifiers/<verifier_id>/presentation-log-entries", ["GET"],
          ["SystemAdmin", "PrivacyAuditor"])
def list_verifier_log_entries(verifier_id):
    limit, offset = v.pagination()
    outcome = v.q_enum("outcome", OUTCOMES)
    billing_state = v.q_enum("billing_state", BILLING_STATES)
    verifier = lookup.verifier(verifier_id)
    rows = derive.log_entries_of_verifier(verifier["id"])
    if outcome is not None:
        rows = [e for e in rows if e["outcome"] == outcome]
    if billing_state is not None:
        rows = [e for e in rows if e["billing_state"] == billing_state]
    rows = sorted(rows, key=lambda e: (e["recorded_at"], e["_seq"]))
    return ok_list(serialize.dump_many(rows), limit, offset)


@endpoint(bp, "/reader-apps", ["POST"], ["VerifierOperator"])
def register_reader_app():
    body = v.body()
    verifier_id = v.req_str(body, "verifier_id")
    app_identifier = v.req_str(body, "app_identifier", 1, 64)
    certificate_serial = v.req_str(body, "certificate_serial")
    cert_not_before = v.req_dt(body, "cert_not_before")
    cert_not_after = v.req_dt(body, "cert_not_after")
    v.interval(cert_not_before, cert_not_after, "cert_not_before", "cert_not_after")
    requested_elements = v.req_array_str(body, "requested_elements")
    base_rate_cents = v.opt_int(body, "base_rate_cents", 25, 0)

    verifier = lookup.verifier(verifier_id)

    # step 6: an operator registers only under its own verifier record
    gates.require_verifier_owner(verifier["id"])

    # step 16: only an approved (or on-probation) organisation may register
    if verifier["trust_status"] not in TRUSTED_STATUSES:
        raise ApiError("ERR_VERIFIER_NOT_TRUSTED")

    siblings = derive.reader_apps_of_verifier(verifier["id"])

    # step 22: the mandatory 24-hour certificate renewal buffer
    buffer = timedelta(hours=calc.CERT_RENEWAL_BUFFER_HOURS)
    for app in sort_rows(siblings):
        if app["app_identifier"] != app_identifier:
            continue
        if app["trust_state"] not in ("PENDING", "LISTED"):
            continue
        if cert_not_before < app["cert_not_after"] + buffer:
            raise ApiError("ERR_CERT_WINDOW_CONFLICT")

    # step 23: (verifier, certificate_serial) is unique
    for app in siblings:
        if app["certificate_serial"] == certificate_serial:
            raise ApiError("ERR_DUPLICATE_READER_APP")

    row = base_row("ReaderApp")
    row["verifier_id"] = verifier["id"]
    row["app_identifier"] = app_identifier
    row["certificate_serial"] = certificate_serial
    row["cert_not_before"] = cert_not_before
    row["cert_not_after"] = cert_not_after
    row["requested_elements"] = list(requested_elements)
    row["base_rate_cents"] = base_rate_cents
    row["trust_state"] = "PENDING"
    row["listed_at"] = None
    db.reader_apps[row["id"]] = row
    return ok(serialize.dump(row), 201)


@endpoint(bp, "/reader-apps/<reader_app_id>/list-decision", ["POST"], ["SystemAdmin"])
def reader_app_list_decision(reader_app_id):
    body = v.body()
    decision = v.req_enum(body, "decision", LIST_DECISIONS)

    app = lookup.reader_app(reader_app_id)
    if decision == "LIST":
        app["trust_state"] = "LISTED"
        app["listed_at"] = now()
    else:
        app["trust_state"] = "DELISTED"
    touch(app)

    # the distributed trust list is now one delta behind
    cascade.reader_set_changed_hop()
    return ok(serialize.dump(app))
