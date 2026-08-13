"""Meeting endpoints: CRUD, lifecycle transitions, quorum read (PRD §3.1/§3.7)."""

from __future__ import annotations

from decimal import Decimal

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_MEETING_NOT_FOUND,
    ERR_INVALID_MEETING_STATE,
    ERR_RECORD_DATE_INVALID,
    ERR_MEETING_NOT_YET_STARTED,
    ERR_NO_ACTIVE_PROPOSAL,
    ERR_BROKER_SEARCH_INCOMPLETE,
    ERR_QUORUM_NOT_MET,
    ERR_STALE_VERSION,
)
from middleware import require_roles
from response import success_object, success_list
from services.quorum import compute_quorum
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    optional_enum,
    optional_field,
    paginate,
    parse_date_value,
    parse_iso8601,
    parse_pagination,
    require_date,
    require_enum,
    require_field,
    require_number,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("meetings", __name__)

MEETING_TYPES = {"ANNUAL", "SPECIAL", "CONTESTED"}
MEETING_MODES = {"IN_PERSON", "VIRTUAL", "HYBRID"}
QUORUM_VARIANTS = {"PROVISIONAL", "FINAL"}


def get_meeting_or_404(meeting_id: str) -> dict:
    meeting = db.meetings.get(meeting_id)
    if meeting is None:
        raise_err(ERR_MEETING_NOT_FOUND, "Meeting id does not exist")
    return meeting


def _check_record_date_ordering(record_date_str: str, meeting_datetime_str: str) -> None:
    """record_date (a YYYY-MM-DD day, read as 00:00:00 UTC) must fall strictly
    before the meeting_datetime instant (PRD §3.1)."""
    rd = parse_date_value(record_date_str, "record_date")
    md = parse_iso8601(meeting_datetime_str, "meeting_datetime")
    if not rd < md:
        raise_err(
            ERR_RECORD_DATE_INVALID,
            "record_date must be strictly before meeting_datetime",
        )


def _validate_quorum_threshold(value) -> None:
    dec = Decimal(str(value))
    if not (dec > 0 and dec <= 1):
        raise_err(
            ERR_INVALID_REQUEST,
            "quorum_threshold_pct must be greater than 0 and at most 1",
        )


def _validate_outstanding_shares(value) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise_err(ERR_INVALID_REQUEST, "outstanding_shares must be a positive integer")


# ---------------------------------------------------------------------------
# Create / read / amend
# ---------------------------------------------------------------------------

@bp.route("/proxy/meetings", methods=["POST"])
@require_roles("ProxyAdministrator")
def create_meeting(_user_id: str, _role: str):
    body = get_json_body()

    # Temporal ordering (precedence 6) is checked before the remaining body
    # shape rules (precedence 10); both fields must parse first.
    record_date = require_date(body, "record_date")
    meeting_datetime = require_field(body, "meeting_datetime")
    parse_iso8601(meeting_datetime, "meeting_datetime")
    _check_record_date_ordering(record_date, meeting_datetime)

    company_name = require_string(body, "company_name")
    ticker = require_string(body, "ticker")
    meeting_type = require_enum(body, "meeting_type", MEETING_TYPES)
    meeting_mode = require_enum(body, "meeting_mode", MEETING_MODES)
    quorum_threshold_pct = require_number(body, "quorum_threshold_pct")
    _validate_quorum_threshold(quorum_threshold_pct)
    outstanding_shares = require_field(body, "outstanding_shares")
    _validate_outstanding_shares(outstanding_shares)

    meeting = {
        "company_name": company_name,
        "ticker": ticker,
        "meeting_type": meeting_type,
        "record_date": record_date,
        "meeting_datetime": meeting_datetime,
        "meeting_mode": meeting_mode,
        "quorum_threshold_pct": quorum_threshold_pct,
        "outstanding_shares": outstanding_shares,
        "status": "DRAFT",
        "walk_in_shares": 0,
        "filed_at": None,
        "filing_reference": None,
    }
    db.stamp_new(meeting)
    db.meetings[meeting["id"]] = meeting
    return success_object(serialize(meeting), 201)


@bp.route("/proxy/meetings", methods=["GET"])
@require_roles(
    "ProxyAdministrator", "TransferAgent", "Shareholder", "Broker", "InspectorOfElection"
)
def list_meetings(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.meetings.values()))
    items = apply_filters(items, ["status", "meeting_type"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/proxy/meetings/<meeting_id>", methods=["GET"])
@require_roles(
    "ProxyAdministrator", "TransferAgent", "Shareholder", "Broker", "InspectorOfElection"
)
def get_meeting(meeting_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_meeting_or_404(meeting_id)))


@bp.route("/proxy/meetings/<meeting_id>", methods=["PATCH"])
@require_roles("ProxyAdministrator")
def amend_meeting(meeting_id: str, _user_id: str, _role: str):
    meeting = get_meeting_or_404(meeting_id)
    if meeting["status"] not in ("DRAFT", "RECORD_DATE_LOCKED"):
        raise_err(
            ERR_INVALID_MEETING_STATE,
            "Meeting may only be amended in DRAFT or RECORD_DATE_LOCKED",
        )
    body = get_json_body()

    # Temporal (precedence 6): the record-date ordering is re-enforced on every
    # amendment, against the amended meeting_datetime when one is supplied.
    new_datetime = meeting["meeting_datetime"]
    if "meeting_datetime" in body and body["meeting_datetime"] is not None:
        parse_iso8601(body["meeting_datetime"], "meeting_datetime")
        new_datetime = body["meeting_datetime"]
    _check_record_date_ordering(meeting["record_date"], new_datetime)

    # OCC (precedence 9): expected_meeting_version is a required input (§2.7).
    expected = optional_field(body, "expected_meeting_version")
    if expected is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: expected_meeting_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST, "expected_meeting_version must be an integer")
    if expected != meeting["version"]:
        raise_err(
            ERR_STALE_VERSION,
            "expected_meeting_version does not match the meeting's current version",
        )

    # Remaining shape (precedence 10).
    quorum = optional_field(body, "quorum_threshold_pct")
    if quorum is not None:
        if isinstance(quorum, bool) or not isinstance(quorum, (int, float)):
            raise_err(ERR_INVALID_REQUEST, "quorum_threshold_pct must be a number")
        _validate_quorum_threshold(quorum)
    meeting_mode = optional_enum(body, "meeting_mode", MEETING_MODES)
    outstanding = optional_field(body, "outstanding_shares")
    if outstanding is not None:
        _validate_outstanding_shares(outstanding)

    if quorum is not None:
        meeting["quorum_threshold_pct"] = quorum
    if "meeting_datetime" in body and body["meeting_datetime"] is not None:
        meeting["meeting_datetime"] = body["meeting_datetime"]
    if meeting_mode is not None:
        meeting["meeting_mode"] = meeting_mode
    if outstanding is not None:
        meeting["outstanding_shares"] = outstanding
    db.touch(meeting)
    return success_object(serialize(meeting))


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------

@bp.route("/proxy/meetings/<meeting_id>/lock-record-date", methods=["POST"])
@require_roles("ProxyAdministrator")
def lock_record_date(meeting_id: str, _user_id: str, _role: str):
    meeting = get_meeting_or_404(meeting_id)
    if meeting["status"] != "DRAFT":
        raise_err(ERR_INVALID_MEETING_STATE, "lock-record-date requires meeting DRAFT")
    _check_record_date_ordering(meeting["record_date"], meeting["meeting_datetime"])
    accounts = [a for a in db.accounts.values() if a["meeting_id"] == meeting_id]
    if not accounts:
        raise_err(
            ERR_INVALID_MEETING_STATE,
            "lock-record-date requires at least one shareholder account",
        )
    # Record-date list snapshot: every account PENDING -> ELIGIBLE.
    for account in accounts:
        if account["status"] == "PENDING":
            account["status"] = "ELIGIBLE"
            db.touch(account)
    meeting["status"] = "RECORD_DATE_LOCKED"
    db.touch(meeting)
    return success_object(serialize(meeting))


@bp.route("/proxy/meetings/<meeting_id>/open-voting", methods=["POST"])
@require_roles("ProxyAdministrator")
def open_voting(meeting_id: str, _user_id: str, _role: str):
    meeting = get_meeting_or_404(meeting_id)
    if meeting["status"] != "MATERIALS_DISTRIBUTED":
        raise_err(
            ERR_INVALID_MEETING_STATE, "open-voting requires meeting MATERIALS_DISTRIBUTED"
        )
    if not any(
        p["meeting_id"] == meeting_id and p["status"] == "ACTIVE"
        for p in db.proposals.values()
    ):
        raise_err(ERR_NO_ACTIVE_PROPOSAL, "open-voting requires at least one ACTIVE proposal")
    if any(
        b["meeting_id"] == meeting_id and b["status"] == "REQUESTED"
        for b in db.broker_searches.values()
    ):
        raise_err(
            ERR_BROKER_SEARCH_INCOMPLETE,
            "open-voting blocked: a broker search record remains REQUESTED",
        )
    meeting["status"] = "VOTING_OPEN"
    db.touch(meeting)
    return success_object(serialize(meeting))


@bp.route("/proxy/meetings/<meeting_id>/convene", methods=["POST"])
@require_roles("ProxyAdministrator")
def convene_meeting(meeting_id: str, _user_id: str, _role: str):
    meeting = get_meeting_or_404(meeting_id)
    if meeting["status"] != "VOTING_OPEN":
        raise_err(ERR_INVALID_MEETING_STATE, "convene requires meeting VOTING_OPEN")
    if parse_iso8601(db.get_current_utc(), "current_utc") < parse_iso8601(
        meeting["meeting_datetime"], "meeting_datetime"
    ):
        raise_err(
            ERR_MEETING_NOT_YET_STARTED,
            "Logical clock has not reached meeting_datetime",
        )
    meeting["status"] = "MEETING_IN_PROGRESS"
    db.touch(meeting)
    return success_object(serialize(meeting))


@bp.route("/proxy/meetings/<meeting_id>/adjourn", methods=["POST"])
@require_roles("ProxyAdministrator")
def adjourn_meeting(meeting_id: str, _user_id: str, _role: str):
    meeting = get_meeting_or_404(meeting_id)
    if meeting["status"] != "MEETING_IN_PROGRESS":
        raise_err(ERR_INVALID_MEETING_STATE, "adjourn requires meeting MEETING_IN_PROGRESS")
    meeting["status"] = "ADJOURNED"
    db.touch(meeting)
    return success_object(serialize(meeting))


@bp.route("/proxy/meetings/<meeting_id>/reconvene", methods=["POST"])
@require_roles("ProxyAdministrator")
def reconvene_meeting(meeting_id: str, _user_id: str, _role: str):
    meeting = get_meeting_or_404(meeting_id)
    if meeting["status"] != "ADJOURNED":
        raise_err(ERR_INVALID_MEETING_STATE, "reconvene requires meeting ADJOURNED")
    meeting["status"] = "MEETING_IN_PROGRESS"
    db.touch(meeting)
    return success_object(serialize(meeting))


@bp.route("/proxy/meetings/<meeting_id>/conclude", methods=["POST"])
@require_roles("ProxyAdministrator")
def conclude_meeting(meeting_id: str, _user_id: str, _role: str):
    meeting = get_meeting_or_404(meeting_id)
    if meeting["status"] != "MEETING_IN_PROGRESS":
        raise_err(
            ERR_INVALID_MEETING_STATE, "conclude requires meeting MEETING_IN_PROGRESS"
        )
    body = get_json_body()
    walk_ins = optional_field(body, "walk_in_shares", 0)
    if isinstance(walk_ins, bool) or not isinstance(walk_ins, int) or walk_ins < 0:
        raise_err(ERR_INVALID_REQUEST, "walk_in_shares must be an integer >= 0")
    # FINAL-variant quorum with the request's walk_in_shares included (§3.7).
    quorum = compute_quorum(meeting, "FINAL", walk_in_shares=walk_ins)
    if not quorum["quorum_met"]:
        raise_err(ERR_QUORUM_NOT_MET, "FINAL quorum (walk-in shares included) is not met")
    meeting["walk_in_shares"] = walk_ins
    meeting["status"] = "MEETING_HELD"
    db.touch(meeting)
    return success_object(serialize(meeting))


@bp.route("/proxy/meetings/<meeting_id>/cancel", methods=["POST"])
@require_roles("ProxyAdministrator")
def cancel_meeting(meeting_id: str, _user_id: str, _role: str):
    meeting = get_meeting_or_404(meeting_id)
    if meeting["status"] not in ("DRAFT", "RECORD_DATE_LOCKED"):
        raise_err(
            ERR_INVALID_MEETING_STATE,
            "cancel requires meeting DRAFT or RECORD_DATE_LOCKED",
        )
    meeting["status"] = "CANCELLED"
    db.touch(meeting)
    return success_object(serialize(meeting))


@bp.route("/proxy/meetings/<meeting_id>/file-8k", methods=["POST"])
@require_roles("ProxyAdministrator")
def file_8k(meeting_id: str, _user_id: str, _role: str):
    meeting = get_meeting_or_404(meeting_id)
    if meeting["status"] != "RESULTS_CERTIFIED":
        raise_err(ERR_INVALID_MEETING_STATE, "file-8k requires meeting RESULTS_CERTIFIED")
    body = get_json_body()
    filing_reference = require_string(body, "filing_reference")
    meeting["filed_at"] = db.now_iso()
    meeting["filing_reference"] = filing_reference
    meeting["status"] = "FILED_8K"
    db.touch(meeting)
    return success_object(serialize(meeting))


# ---------------------------------------------------------------------------
# Computed quorum read
# ---------------------------------------------------------------------------

@bp.route("/proxy/meetings/<meeting_id>/quorum", methods=["GET"])
@require_roles("ProxyAdministrator", "TransferAgent", "InspectorOfElection")
def get_quorum(meeting_id: str, _user_id: str, _role: str):
    meeting = get_meeting_or_404(meeting_id)
    from flask import request

    variant = request.args.get("variant") or "PROVISIONAL"
    if variant not in QUORUM_VARIANTS:
        raise_err(ERR_INVALID_REQUEST, "variant must be PROVISIONAL or FINAL")
    return success_object(compute_quorum(meeting, variant))
