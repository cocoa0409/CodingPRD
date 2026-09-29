"""Utilization filings and the audit programme (PRD 3.3)."""

from flask import Blueprint

from db import base_record, by_created, days, db, now, r2, touch
from errors import fail
from middleware import (
    ROLE_ADMIN,
    ROLE_APPROVER,
    ROLE_CARRIER,
    body,
    opt_id,
    opt_int,
    opt_str,
    req_enum,
    req_id,
    req_int,
    req_int_list,
    req_str,
    require_roles,
)
from response import object_response, paginate
from routes.common import PERIOD_PATTERN, field, filter_rows
from services import constants as C
from services import calc, core, serialize

bp = Blueprint("filings", __name__)

READERS = (ROLE_ADMIN, ROLE_APPROVER, ROLE_CARRIER)
ADJUSTMENT_TYPES = ("UNDERSTATED_UTILIZATION", "OVERSTATED_UTILIZATION")


@bp.route("/numbering/utilization-filings", methods=["POST"])
def create_filing():
    actor = require_roles(ROLE_CARRIER)
    payload = body()
    carrier_id = req_id(payload, "carrier_id")
    rate_center_id = req_id(payload, "rate_center_id")
    period = req_str(payload, "reporting_period", 7, 7, PERIOD_PATTERN)
    assigned = req_int(payload, "numbers_assigned", 0)
    intermediate = req_int(payload, "numbers_intermediate", 0)
    reserved = req_int(payload, "numbers_reserved", 0)
    aging = req_int(payload, "numbers_aging", 0)
    administrative = req_int(payload, "numbers_administrative", 0)
    blocks_held = req_int(payload, "blocks_held_at_period_end", 1)
    forecast = req_int_list(payload, "forecast_quarters", 4, 0)

    carrier = core.get_carrier(carrier_id)
    rate_center = core.get_rate_center(rate_center_id)

    if actor.user_id != carrier["id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "a carrier may only file for itself")

    for existing in db.filings.values():
        if (
            existing["carrier_id"] == carrier["id"]
            and existing["rate_center_id"] == rate_center["id"]
            and existing["reporting_period"] == period
            and existing["status"] != "REJECTED"
        ):
            fail("ERR_DUPLICATE_FILING_PERIOD", "a filing for that period already exists")

    record = base_record(
        carrier_id=carrier["id"],
        rate_center_id=rate_center["id"],
        reporting_period=period,
        numbers_assigned=assigned,
        numbers_intermediate=intermediate,
        numbers_reserved=reserved,
        numbers_aging=aging,
        numbers_administrative=administrative,
        blocks_held_at_period_end=blocks_held,
        forecast_quarters=forecast,
        status="DRAFT",
        claimed_utilization_pct=None,
        strict_utilization_pct=None,
        audited_utilization_pct=None,
        submitted_at=None,
        amendment_count=0,
    )
    record["claimed_utilization_pct"] = r2(calc.claimed_utilization(record))
    record["strict_utilization_pct"] = r2(calc.strict_utilization(record))
    db.filings[record["id"]] = record
    return object_response(serialize.filing(record), 201)


@bp.route("/numbering/utilization-filings", methods=["GET"])
def list_filings():
    require_roles(*READERS)
    rows = by_created(db.filings.values())
    rows = filter_rows(
        rows,
        [
            ("carrier_id", field("carrier_id")),
            ("rate_center_id", field("rate_center_id")),
            ("reporting_period", field("reporting_period")),
            ("status", field("status")),
        ],
    )
    return paginate(rows, serialize.filing)


@bp.route("/numbering/utilization-filings/<filing_id>", methods=["GET"])
def get_filing(filing_id):
    require_roles(*READERS)
    return object_response(serialize.filing(core.get_filing(filing_id)))


@bp.route("/numbering/utilization-filings/<filing_id>/submissions", methods=["POST"])
def submit_filing(filing_id):
    actor = require_roles(ROLE_CARRIER)
    payload = body()
    amendment_note = opt_str(payload, "amendment_note", 1, 1000)

    filing = core.get_filing(filing_id)

    if actor.user_id != filing["carrier_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "only the filing carrier may submit")

    if filing["status"] == "ACCEPTED":
        fail("ERR_TERMINAL_STATE", "the filing is already accepted")

    carrier = core.get_carrier(filing["carrier_id"])
    if filing["status"] not in ("DRAFT", "REJECTED"):
        fail("ERR_INVALID_STATE_TRANSITION", "the filing cannot be submitted from here")
    if carrier["license_status"] != "GRANTED":
        fail("ERR_INVALID_STATE_TRANSITION", "the carrier licence is not granted")
    if core.license_expired(carrier):
        fail("ERR_LICENSE_EXPIRED", "the carrier licence has expired")

    amending = filing["status"] == "REJECTED"
    if amending and amendment_note is None:
        fail("ERR_INVALID_REQUEST", "amendment_note is required to amend a filing")

    filing["status"] = "SUBMITTED"
    filing["submitted_at"] = now()
    filing["claimed_utilization_pct"] = r2(calc.claimed_utilization(filing))
    filing["strict_utilization_pct"] = r2(calc.strict_utilization(filing))
    if amending:
        filing["amendment_count"] += 1
        filing["audited_utilization_pct"] = None
    touch(filing)

    rate_center = db.rate_centers.get(filing["rate_center_id"])
    if rate_center is not None:
        touch(rate_center)

    return object_response(serialize.filing(filing))


@bp.route("/numbering/utilization-filings/<filing_id>/audit-findings", methods=["POST"])
def create_finding(filing_id):
    actor = require_roles(ROLE_ADMIN)
    payload = body()
    finding_type = req_enum(payload, "finding_type", C.FINDING_TYPES)
    opt_id(payload, "utilization_filing_id")
    if finding_type in ADJUSTMENT_TYPES:
        adjusted_assigned = req_int(payload, "adjusted_numbers_assigned", 0)
        adjusted_admin = opt_int(payload, "adjusted_numbers_administrative", 0)
    else:
        if payload.get("adjusted_numbers_assigned") is not None:
            fail(
                "ERR_INVALID_REQUEST",
                "adjusted_numbers_assigned is not permitted for this finding_type",
            )
        if payload.get("adjusted_numbers_administrative") is not None:
            fail(
                "ERR_INVALID_REQUEST",
                "adjusted_numbers_administrative is not permitted for this finding_type",
            )
        adjusted_assigned = None
        adjusted_admin = None
    note = opt_str(payload, "disposition_note", 1, 1000)

    filing = core.get_filing(filing_id)

    if adjusted_assigned is not None:
        ceiling = filing["blocks_held_at_period_end"] * C.NUMBERS_PER_BLOCK
        if adjusted_assigned > ceiling:
            fail(
                "ERR_INVALID_REQUEST",
                "adjusted_numbers_assigned exceeds the numbers the carrier holds",
            )

    if filing["status"] == "ACCEPTED":
        fail("ERR_TERMINAL_STATE", "the filing is already accepted")
    if filing["status"] not in ("SUBMITTED", "UNDER_AUDIT"):
        fail("ERR_INVALID_STATE_TRANSITION", "the filing is not open to audit")

    adjusted_pct = None
    if finding_type in ADJUSTMENT_TYPES:
        adjusted_pct = r2(
            calc.adjusted_utilization(filing, adjusted_assigned, adjusted_admin)
        )

    penalty = calc.audit_penalty_action(
        finding_type, filing["claimed_utilization_pct"], adjusted_pct
    )

    record = base_record(
        utilization_filing_id=filing["id"],
        auditor_user_id=actor.user_id,
        finding_type=finding_type,
        adjusted_numbers_assigned=adjusted_assigned,
        adjusted_numbers_administrative=adjusted_admin,
        adjusted_utilization_pct=adjusted_pct,
        penalty_action=penalty,
        status="OPEN",
        disposed_by_user_id=None,
        disposition_note=note,
    )
    db.findings[record["id"]] = record

    if filing["status"] == "SUBMITTED":
        filing["status"] = "UNDER_AUDIT"
    touch(filing)

    return object_response(serialize.finding(record), 201)


@bp.route("/numbering/utilization-filings/<filing_id>/audit-findings", methods=["GET"])
def list_findings(filing_id):
    require_roles(*READERS)
    filing = core.get_filing(filing_id)
    rows = by_created(
        [f for f in db.findings.values() if f["utilization_filing_id"] == filing["id"]]
    )
    rows = filter_rows(rows, [("status", field("status"))])
    return paginate(rows, serialize.finding)


@bp.route("/numbering/audit-findings/<finding_id>", methods=["GET"])
def get_finding(finding_id):
    require_roles(*READERS)
    return object_response(serialize.finding(core.get_finding(finding_id)))


@bp.route("/numbering/audit-findings/<finding_id>/dispositions", methods=["POST"])
def dispose_finding(finding_id):
    actor = require_roles(ROLE_APPROVER)
    payload = body()
    disposition = req_enum(payload, "disposition", C.DISPOSITIONS)
    note = opt_str(payload, "disposition_note", 1, 1000)

    finding = core.get_finding(finding_id)

    if finding["status"] in ("ACCEPTED", "REJECTED"):
        fail("ERR_TERMINAL_STATE", "the finding is already disposed")

    if actor.user_id == finding["auditor_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "an auditor may not dispose of its own finding")

    finding["disposed_by_user_id"] = actor.user_id
    if note is not None:
        finding["disposition_note"] = note
    finding["status"] = "ACCEPTED" if disposition == "ACCEPT" else "REJECTED"
    touch(finding)

    if disposition == "ACCEPT":
        _apply_acceptance(finding)

    return object_response(serialize.finding(finding))


def _apply_acceptance(finding):
    filing = db.filings.get(finding["utilization_filing_id"])
    if filing is None:
        return
    carrier = db.carriers.get(filing["carrier_id"])
    penalty = finding["penalty_action"]

    if penalty == "NONE":
        others_open = [
            f
            for f in db.findings.values()
            if f["utilization_filing_id"] == filing["id"]
            and f["id"] != finding["id"]
            and f["status"] == "OPEN"
        ]
        if others_open:
            return
        if filing["status"] != "UNDER_AUDIT":
            return
        filing["status"] = "ACCEPTED"
        if finding["adjusted_utilization_pct"] is not None:
            filing["audited_utilization_pct"] = finding["adjusted_utilization_pct"]
        else:
            filing["audited_utilization_pct"] = filing["strict_utilization_pct"]
        touch(filing)
        return

    if filing["status"] == "UNDER_AUDIT":
        filing["status"] = "REJECTED"
    filing["audited_utilization_pct"] = finding["adjusted_utilization_pct"]
    touch(filing)

    if carrier is None:
        return
    if penalty == "RECLAMATION_REFERRAL":
        carrier["reclamation_strike_count"] += 1
    carrier["probation_until"] = now() + days(C.PROBATION_DAYS)
    touch(carrier)
    core.push_pending_growth_requests_to_info(carrier["id"])
