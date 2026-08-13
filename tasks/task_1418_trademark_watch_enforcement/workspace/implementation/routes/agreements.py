"""CoexistenceAgreement endpoints (PRD 3.8)."""

from flask import Blueprint

import db
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_STALE_VERSION,
    ERR_ROUND_CAP_REACHED, ERR_AGREEMENT_OVERLAP, ERR_VALIDATION,
)
from middleware import require_roles, enforce_client_scope
from response import success
from services import domain
from services.domain import (
    ser_agreement, reopen_matter, LIVE_AGREEMENT_STATES,
)
from util import (
    get_payload, reject_unknown_fields, require_string, require_enum,
    optional_int, optional_string, require_datetime, require_array,
    coerce_version, stamp_new, touch, fmt_business, parse_dt, add_days,
)
from routes.common import do_list

bp = Blueprint("coexistence_agreements", __name__)

READ_ROLES = ("Paralegal", "AssociateAttorney", "PartnerAttorney", "ClientContact")
CURE_ACTIONS = ("GRANT", "CONFIRM_CURED")
ROUND_CAP = 8
EXECUTE_RECORD_STATES = ("PUBLISHED", "REGISTERED", "UNDER_CHALLENGE")


def _get_agreement(agreement_id):
    agreement = db.coexistence_agreements.get(agreement_id)
    if agreement is None:
        raise_error(ERR_NOT_FOUND, "CoexistenceAgreement not found")
    return agreement


def _scope(user_id, role, agreement):
    enforce_client_scope(user_id, role,
                         domain.client_id_for_resource("coexistence_agreement", agreement))


# ---------------------------------------------------------------------------
# Nested create: POST /brand/trademark-records/{id}/coexistence-agreements
# ---------------------------------------------------------------------------

@bp.route("/brand/trademark-records/<record_id>/coexistence-agreements", methods=["POST"])
def create_agreement(record_id):
    user_id, role = require_roles("AssociateAttorney")
    body = get_payload()
    reject_unknown_fields(body, {"counterparty_name", "territory_codes", "effective_start",
                                 "effective_end", "cure_period_days", "enforcement_matter_id"})
    counterparty_name = require_string(body, "counterparty_name")
    territory_codes = require_array(body, "territory_codes")
    for code in territory_codes:
        if not isinstance(code, str):
            raise_error(ERR_VALIDATION, "territory_codes entries must be strings")
    effective_start = require_datetime(body, "effective_start")
    effective_end = require_datetime(body, "effective_end")
    cure_period_days = optional_int(body, "cure_period_days", default=30, minimum=0)
    enforcement_matter_id = optional_string(body, "enforcement_matter_id", default=None)
    record = db.trademark_records.get(record_id)
    if record is None:
        raise_error(ERR_NOT_FOUND, "TrademarkRecord not found")
    if enforcement_matter_id is not None and enforcement_matter_id not in db.enforcement_matters:
        raise_error(ERR_NOT_FOUND, "EnforcementMatter not found")
    agreement = {
        "trademark_record_id": record["id"],
        "enforcement_matter_id": enforcement_matter_id,
        "counterparty_name": counterparty_name,
        "territory_codes": list(territory_codes),
        "effective_start": fmt_business(effective_start),
        "effective_end": fmt_business(effective_end),
        "cure_period_days": cure_period_days,
        "round_count": 0,
        "current_terms_text": None,
        "breach_claimed_at": None,
        "cure_deadline": None,
        "status": "DRAFT",
    }
    stamp_new(agreement)
    db.coexistence_agreements[agreement["id"]] = agreement
    return success(ser_agreement(agreement), 201)


@bp.route("/brand/coexistence-agreements", methods=["GET"])
def list_agreements():
    user_id, role = require_roles(*READ_ROLES)
    return do_list(db.coexistence_agreements.values(), ser_agreement,
                   [("trademark_record_id", "trademark_record_id", None),
                    ("enforcement_matter_id", "enforcement_matter_id", None),
                    ("status", "status", None)],
                   user_id, role, "coexistence_agreement")


@bp.route("/brand/coexistence-agreements/<agreement_id>", methods=["GET"])
def get_agreement(agreement_id):
    user_id, role = require_roles(*READ_ROLES)
    agreement = _get_agreement(agreement_id)
    _scope(user_id, role, agreement)
    return success(ser_agreement(agreement), 200)


@bp.route("/brand/coexistence-agreements/<agreement_id>/propose", methods=["POST"])
def propose_agreement(agreement_id):
    user_id, role = require_roles("AssociateAttorney")
    body = get_payload()
    reject_unknown_fields(body, {"terms_text", "expected_agreement_version"})
    terms_text = require_string(body, "terms_text")
    expected_version = coerce_version(body, "expected_agreement_version")
    agreement = _get_agreement(agreement_id)
    if agreement["status"] not in ("DRAFT", "COUNTERED"):
        raise_error(ERR_INVALID_STATE, "propose is declared only from DRAFT / COUNTERED")
    # OCC: expected_agreement_version must match the agreement's version.
    if expected_version != agreement["version"]:
        raise_error(ERR_STALE_VERSION,
                    "expected_agreement_version does not match agreement version")
    if agreement["status"] == "DRAFT":
        agreement["round_count"] = 1
    else:
        # Proposing from COUNTERED consumes a round and respects the cap of 8.
        if agreement["round_count"] >= ROUND_CAP:
            raise_error(ERR_ROUND_CAP_REACHED, "Negotiation round cap of 8 reached")
        agreement["round_count"] += 1
    agreement["current_terms_text"] = terms_text
    agreement["status"] = "PROPOSED"
    touch(agreement)
    return success(ser_agreement(agreement), 200)


@bp.route("/brand/coexistence-agreements/<agreement_id>/counter", methods=["POST"])
def counter_agreement(agreement_id):
    user_id, role = require_roles("AssociateAttorney")
    body = get_payload()
    reject_unknown_fields(body, {"counter_terms_text"})
    counter_terms_text = require_string(body, "counter_terms_text")
    agreement = _get_agreement(agreement_id)
    if agreement["status"] != "PROPOSED":
        raise_error(ERR_INVALID_STATE, "counter is declared only from PROPOSED")
    agreement["round_count"] += 1
    agreement["current_terms_text"] = counter_terms_text
    agreement["status"] = "COUNTERED"
    touch(agreement)
    return success(ser_agreement(agreement), 200)


@bp.route("/brand/coexistence-agreements/<agreement_id>/execute", methods=["POST"])
def execute_agreement(agreement_id):
    user_id, role = require_roles("PartnerAttorney")
    body = get_payload()
    reject_unknown_fields(body, set())
    agreement = _get_agreement(agreement_id)
    if agreement["status"] not in ("PROPOSED", "COUNTERED"):
        raise_error(ERR_INVALID_STATE, "execute is declared only from PROPOSED / COUNTERED")
    record = db.trademark_records.get(agreement["trademark_record_id"])
    if record["status"] not in EXECUTE_RECORD_STATES:
        raise_error(ERR_INVALID_STATE,
                    "execute requires the record to be PUBLISHED / REGISTERED / UNDER_CHALLENGE")
    # Overlap guard: no other live agreement on the same record with
    # intersecting territories and overlapping half-open [start, end) term;
    # mere adjacency (new.start == existing.end) is allowed.
    new_start = parse_dt(agreement["effective_start"])
    new_end = parse_dt(agreement["effective_end"])
    new_territories = set(agreement["territory_codes"])
    for other in db.coexistence_agreements.values():
        if other["id"] == agreement["id"]:
            continue
        if other["trademark_record_id"] != agreement["trademark_record_id"]:
            continue
        if other["status"] not in LIVE_AGREEMENT_STATES:
            continue
        if not (new_territories & set(other["territory_codes"])):
            continue
        other_start = parse_dt(other["effective_start"])
        other_end = parse_dt(other["effective_end"])
        if new_start < other_end and other_start < new_end:
            raise_error(ERR_AGREEMENT_OVERLAP,
                        "A live agreement on this record overlaps in territory and term")
    agreement["status"] = "EXECUTED"
    touch(agreement)
    return success(ser_agreement(agreement), 200)


@bp.route("/brand/coexistence-agreements/<agreement_id>/breach", methods=["POST"])
def breach_agreement(agreement_id):
    user_id, role = require_roles("Paralegal")
    body = get_payload()
    reject_unknown_fields(body, {"breach_notes"})
    require_string(body, "breach_notes")
    agreement = _get_agreement(agreement_id)
    if agreement["status"] != "MONITORING":
        raise_error(ERR_INVALID_STATE, "breach is declared only from MONITORING")
    now = db.clock.now()
    agreement["breach_claimed_at"] = fmt_business(now)
    agreement["status"] = "BREACH_ALLEGED"
    touch(agreement)
    # Depth-3 cascade (PRD 3.8): a linked RESOLVED matter reopens; every
    # COMPLIED letter of that matter is reissued (budget check bypassed);
    # each reissued letter gets a fresh auto-docketed RESPONSE_DUE deadline.
    if agreement["enforcement_matter_id"] is not None:
        matter = db.enforcement_matters.get(agreement["enforcement_matter_id"])
        if matter is not None and matter["status"] == "RESOLVED":
            reopen_matter(matter, now)
    return success(ser_agreement(agreement), 200)


@bp.route("/brand/coexistence-agreements/<agreement_id>/cure", methods=["POST"])
def cure_agreement(agreement_id):
    user_id, role = require_roles("PartnerAttorney")
    body = get_payload()
    reject_unknown_fields(body, {"cure_action"})
    cure_action = require_enum(body, "cure_action", CURE_ACTIONS)
    agreement = _get_agreement(agreement_id)
    if cure_action == "GRANT":
        if agreement["status"] != "BREACH_ALLEGED":
            raise_error(ERR_INVALID_STATE, "cure GRANT is declared only from BREACH_ALLEGED")
        # cure_deadline = breach_claimed_at + cure_period_days calendar days.
        deadline = add_days(parse_dt(agreement["breach_claimed_at"]),
                            agreement["cure_period_days"])
        agreement["cure_deadline"] = fmt_business(deadline)
        agreement["status"] = "CURE_PERIOD"
    else:  # CONFIRM_CURED
        if agreement["status"] != "CURE_PERIOD":
            raise_error(ERR_INVALID_STATE,
                        "cure CONFIRM_CURED is declared only from CURE_PERIOD")
        agreement["cure_deadline"] = None
        agreement["status"] = "MONITORING"
    touch(agreement)
    return success(ser_agreement(agreement), 200)
