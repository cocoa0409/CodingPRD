"""AuditEngagement endpoints (§3.9)."""

from datetime import timedelta

from flask import Blueprint

import lookup
import serializers
import validation
from constants import (
    API_PREFIX,
    AUDIT_INTEREST_ANNUAL_BPS,
    AUDIT_WINDOW_DAYS,
    DATA_PRODUCTION_DAYS,
    DAYS_PER_YEAR,
    RESOLUTIONS,
    ROLE_RIGHTS_HOLDER_USER,
    ROLE_ROYALTY_ADMIN,
)
from db import db, fmt_dt, now, parse_dt, stamp_new, touch
from errors import ApiError
from middleware import current_role, current_user_id, require
from response import created_response, object_response, paginate_and_serialize
from services import derive
from validation import round_half_up

bp = Blueprint("audits", __name__, url_prefix=API_PREFIX)


def _require_owner(engagement):
    if current_role() == ROLE_RIGHTS_HOLDER_USER \
            and engagement["rights_holder_id"] != current_user_id():
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


@bp.post("/audit-engagements")
@require(ROLE_RIGHTS_HOLDER_USER)
def create_engagement():
    data = validation.body()

    raw_holder_id = data.get("rights_holder_id")
    holder = None
    if isinstance(raw_holder_id, str) and raw_holder_id:
        holder = lookup.holder(raw_holder_id)
    raw_statement_id = data.get("statement_id")
    statement = None
    if isinstance(raw_statement_id, str) and raw_statement_id:
        statement = lookup.statement(raw_statement_id)

    rights_holder_id = validation.get_id(data, "rights_holder_id")
    statement_id = validation.get_id(data, "statement_id")
    scope_start = validation.get_date(data, "requested_scope_start")
    scope_end = validation.get_date(data, "requested_scope_end")

    if holder is None:
        holder = lookup.holder(rights_holder_id)
    if statement is None:
        statement = lookup.statement(statement_id)

    # Item 6: ownership.
    if rights_holder_id != current_user_id():
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    # Item 11: the audited statement must be ISSUED.
    if statement["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATEMENT_STATE")

    # Item 18: audit window.
    issued_at = parse_dt(statement["issued_at"])
    if issued_at is None or now() > issued_at + timedelta(days=AUDIT_WINDOW_DAYS):
        raise ApiError("ERR_AUDIT_WINDOW_EXPIRED")

    # Item 19: scope well-formed and contained in the audited period.
    period = db.periods.get(statement["period_id"])
    if scope_end < scope_start:
        raise ApiError("ERR_INVALID_EFFECTIVE_PERIOD")
    if period is None or scope_start < period["usage_start"] \
            or scope_end > period["usage_end"]:
        raise ApiError("ERR_INVALID_EFFECTIVE_PERIOD")

    record = {
        "rights_holder_id": holder["id"],
        "statement_id": statement["id"],
        "requested_scope_start": scope_start,
        "requested_scope_end": scope_end,
        "required_line_count": len(derive.statement_lines_of(statement["id"])),
        "produced_line_count": 0,
        "finding_status": "NONE",
        "asserted_underpayment_cents": 0,
        "settled_amount_cents": 0,
        "interest_cents": 0,
        "finding_note": None,
        "findings_recorded_by_user_id": None,
        "_produced_ids": [],
    }
    stamp_new(record)
    record["production_deadline_at"] = fmt_dt(
        record["_created_dt"] + timedelta(days=DATA_PRODUCTION_DAYS))
    db.engagements[record["id"]] = record
    return created_response(serializers.audit_engagement(record))


@bp.get("/audit-engagements/<engagement_id>")
@require()
def read_engagement(engagement_id):
    engagement = lookup.engagement(engagement_id)
    _require_owner(engagement)
    return object_response(serializers.audit_engagement(engagement))


@bp.get("/audit-engagements")
@require()
def list_engagements():
    records = lookup.apply_filters(db.engagements.values(), {
        "rights_holder_id": lookup.field("rights_holder_id"),
        "statement_id": lookup.field("statement_id"),
        "production_status": derive.production_status,
        "finding_status": lookup.field("finding_status"),
    })
    return paginate_and_serialize(records, serializers.audit_engagement)


@bp.post("/audit-engagements/<engagement_id>/data-productions")
@require(ROLE_ROYALTY_ADMIN)
def produce_data(engagement_id):
    engagement = lookup.engagement(engagement_id)
    data = validation.body()

    # Item 3: supplied line identifiers resolve as StatementLine references.
    raw_ids = data.get("statement_line_ids")
    resolved = []
    if isinstance(raw_ids, list) and all(isinstance(i, str) and i for i in raw_ids):
        for identifier in raw_ids:
            resolved.append(lookup.statement_line(identifier))

    line_ids = validation.get_string_list(data, "statement_line_ids")
    if not resolved:
        resolved = [lookup.statement_line(i) for i in line_ids]

    for line in resolved:
        if line["statement_id"] != engagement["statement_id"]:
            validation.bad("A produced statement line belongs to another statement.")

    # Item 12: finding state.
    if engagement["finding_status"] in ("SETTLED", "WITHDRAWN"):
        raise ApiError("ERR_INVALID_ENGAGEMENT_STATE")

    # Item 18: production window.
    deadline = parse_dt(engagement["production_deadline_at"])
    if deadline is None or now() > deadline:
        raise ApiError("ERR_AUDIT_WINDOW_EXPIRED")

    produced = engagement["_produced_ids"]
    for line in resolved:
        if line["id"] not in produced:
            produced.append(line["id"])
    engagement["produced_line_count"] = len(produced)
    touch(engagement)
    return object_response(serializers.audit_engagement(engagement))


@bp.post("/audit-engagements/<engagement_id>/findings")
@require(ROLE_RIGHTS_HOLDER_USER)
def record_finding(engagement_id):
    engagement = lookup.engagement(engagement_id)
    data = validation.body()

    asserted = validation.get_int(data, "asserted_underpayment_cents", minimum=1)
    note = validation.get_string(
        data, "finding_note", required=False, default=None, nullable=True)

    _require_owner(engagement)

    if engagement["finding_status"] != "NONE":
        raise ApiError("ERR_INVALID_ENGAGEMENT_STATE")

    if derive.production_status(engagement) != "COMPLETE":
        raise ApiError("ERR_DATA_PRODUCTION_INCOMPLETE")

    engagement["asserted_underpayment_cents"] = asserted
    engagement["finding_note"] = note
    engagement["findings_recorded_by_user_id"] = current_user_id()
    engagement["finding_status"] = "ASSERTED"
    touch(engagement)
    return object_response(serializers.audit_engagement(engagement))


@bp.post("/audit-engagements/<engagement_id>/settle")
@require(ROLE_ROYALTY_ADMIN)
def settle_engagement(engagement_id):
    engagement = lookup.engagement(engagement_id)
    data = validation.body()

    resolution = validation.get_enum(data, "resolution", RESOLUTIONS)
    settled_amount = validation.get_int(
        data, "settled_amount_cents", required=False, minimum=0, default=0,
        nullable=True)
    if settled_amount is None:
        settled_amount = 0

    # Item 7: segregation of duties.
    if engagement["findings_recorded_by_user_id"] is not None \
            and engagement["findings_recorded_by_user_id"] == current_user_id():
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    # Item 12: finding state.
    if engagement["finding_status"] != "ASSERTED":
        raise ApiError("ERR_INVALID_ENGAGEMENT_STATE")

    # Item 30: settlement amount against the assertion.
    if resolution == "UPHOLD":
        if settled_amount < 1 \
                or settled_amount > engagement["asserted_underpayment_cents"]:
            raise ApiError("ERR_SETTLEMENT_EXCEEDS_ASSERTION")
        engagement["settled_amount_cents"] = settled_amount
        engagement["interest_cents"] = _settlement_interest(engagement, settled_amount)
        engagement["finding_status"] = "SETTLED"
        touch(engagement)
        holder = db.rights_holders.get(engagement["rights_holder_id"])
        if holder is not None:
            touch(holder)
    else:
        if settled_amount != 0:
            raise ApiError("ERR_SETTLEMENT_EXCEEDS_ASSERTION")
        engagement["settled_amount_cents"] = 0
        engagement["interest_cents"] = 0
        engagement["finding_status"] = "WITHDRAWN"
        touch(engagement)

    return object_response(serializers.audit_engagement(engagement))


def _settlement_interest(engagement, settled_amount):
    """§3.9: one single rounding on the fully assembled quotient."""
    statement = db.statements.get(engagement["statement_id"])
    issued_at = parse_dt(statement["issued_at"]) if statement else None
    if issued_at is None:
        return 0
    elapsed = (now() - issued_at).total_seconds()
    days_elapsed = int(elapsed // 86400)
    if days_elapsed <= 0:
        return 0
    return round_half_up(
        settled_amount * AUDIT_INTEREST_ANNUAL_BPS * days_elapsed,
        10000 * DAYS_PER_YEAR,
    )
