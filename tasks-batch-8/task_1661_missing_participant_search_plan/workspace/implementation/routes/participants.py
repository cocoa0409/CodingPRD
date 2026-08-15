"""Participant endpoints (PRD sections 3.1, 3.3, 3.6)."""

import db
import services
from errors import (
    ApiError,
    ERR_BALANCE_EXCEEDS_FORCED_LIMIT,
    ERR_CASE_CENSUS_FROZEN,
    ERR_CASE_INVALID_STATE,
    ERR_DEFAULT_TREATMENT_WINDOW_NOT_PASSED,
    ERR_ELECTION_INVALID_STATE,
    ERR_INVALID_FLAG_TRANSITION,
    ERR_PARTICIPANT_MISSING_REQUIRES_SEARCH,
    ERR_PARTICIPANT_NOT_FLAGGED,
    ERR_PARTICIPANT_NOT_MISSING,
    ERR_SEARCH_CASE_EXHAUSTED_REDECLARE,
)
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from routes import make_blueprint
from services import public_participant
from util import (
    apply_filters,
    body_fk,
    body_json,
    check_no_fields,
    check_shape,
    paginate,
    pagination_params,
    parse_dt,
    path_entity,
)

bp = make_blueprint("participants")

CENSUS_OPEN_STATUSES = {"DRAFT", "NOTICE_OF_INTENT_ISSUED", "TERMINATION_EFFECTIVE"}


def _get_participant(participant_id):
    return path_entity("participants", participant_id, "participant")


@bp.post("/participants")
def create_participant():
    authenticate(["PlanAdministrator"])
    body = body_json()
    check_shape(body, {
        "termination_case_id": {"type": "string", "required": True},
        "full_name": {"type": "string", "required": True},
        "ssn": {"type": "digits", "length": 9, "required": True},
        "mailing_address": {"type": "string", "required": True},
        "account_balance_cents": {"type": "integer", "min": 0, "required": True},
        "vested_pct": {"type": "integer", "min": 0, "max": 100, "required": True},
    })
    case = body_fk(body, "termination_case_id", "cases", "termination case")
    if case["status"] not in CENSUS_OPEN_STATUSES:
        raise ApiError(
            ERR_CASE_CENSUS_FROZEN, 409,
            "the census is frozen once distributions have begun",
        )
    vested_pct = body["vested_pct"]
    if case["status"] == "TERMINATION_EFFECTIVE":
        # Termination forces full vesting regardless of the supplied value.
        vested_pct = 100
    participant = db.new_entity("participants", {
        "termination_case_id": case["id"],
        "full_name": body["full_name"],
        "ssn": body["ssn"],
        "mailing_address": body["mailing_address"],
        "account_balance_cents": body["account_balance_cents"],
        "vested_pct": vested_pct,
        "locate_status": "UNVERIFIED",
        "distribution_status": "PENDING_ELECTION",
        "active_search_case_id": None,
        "flagged_at": None,
        "declared_missing_at": None,
        "located_at": None,
        "_expense_share_cents": 0,
        "_restoration_credit_cents": 0,
    })
    return success_obj(public_participant(participant), 201)


@bp.get("/participants/<participant_id>")
def get_participant(participant_id):
    authenticate(ALL_ROLES)
    return success_obj(public_participant(_get_participant(participant_id)), 200)


@bp.get("/participants")
def list_participants():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("participants"), [
        "termination_case_id",
        "active_search_case_id",
        "locate_status",
        "distribution_status",
    ])
    page, total, has_more = paginate(items, limit, offset)
    return success_list(
        [public_participant(p) for p in page], limit, offset, total, has_more
    )


@bp.post("/participants/<participant_id>/contact-flags")
def flag_contact(participant_id):
    authenticate(["Recordkeeper"])
    body = body_json()
    check_shape(body, {
        "flag_type": {
            "type": "enum",
            "values": {"UNCASHED_CHECK", "UNDELIVERABLE_MAIL"},
            "required": True,
        },
        "evidence_note": {"type": "string"},
    })
    participant = _get_participant(participant_id)
    if participant["locate_status"] not in ("UNVERIFIED", "LOCATED"):
        raise ApiError(
            ERR_INVALID_FLAG_TRANSITION, 409,
            "contact flags require locate_status UNVERIFIED or LOCATED",
        )
    participant["locate_status"] = (
        "FLAGGED_UNCASHED"
        if body["flag_type"] == "UNCASHED_CHECK"
        else "FLAGGED_UNDELIVERABLE"
    )
    participant["flagged_at"] = db.now()
    db.touch(participant)
    return success_obj(public_participant(participant), 200)


@bp.post("/participants/<participant_id>/clear-contact-flag")
def clear_contact_flag(participant_id):
    authenticate(["Recordkeeper"])
    body = body_json()
    check_shape(body, {
        "flag_type": {
            "type": "enum",
            "values": {"UNCASHED_CHECK", "UNDELIVERABLE_MAIL"},
            "required": True,
        },
    })
    participant = _get_participant(participant_id)
    expected = {
        "UNCASHED_CHECK": "FLAGGED_UNCASHED",
        "UNDELIVERABLE_MAIL": "FLAGGED_UNDELIVERABLE",
    }[body["flag_type"]]
    if participant["locate_status"] != expected:
        raise ApiError(
            ERR_INVALID_FLAG_TRANSITION, 409,
            "flag_type does not match the participant's current flag",
        )
    participant["locate_status"] = "UNVERIFIED"
    db.touch(participant)
    return success_obj(public_participant(participant), 200)


@bp.post("/participants/<participant_id>/declare-missing")
def declare_missing(participant_id):
    user_id, _role = authenticate(["PlanAdministrator"])
    body = body_json()
    check_no_fields(body)
    participant = _get_participant(participant_id)
    # The locate-state gate fires before any search-case check.
    if participant["locate_status"] not in (
        "FLAGGED_UNCASHED", "FLAGGED_UNDELIVERABLE"
    ):
        raise ApiError(
            ERR_PARTICIPANT_NOT_FLAGGED, 409,
            "declare-missing requires a flagged participant",
        )
    existing = services.participant_search_case(participant["id"])
    if existing is not None and existing["status"] == "EXHAUSTED":
        raise ApiError(
            ERR_SEARCH_CASE_EXHAUSTED_REDECLARE, 409,
            "the participant's search case is EXHAUSTED; disposition must proceed",
        )
    ts = db.now()
    participant["locate_status"] = "MISSING"
    participant["declared_missing_at"] = ts
    if existing is None:
        search_case = db.new_entity("search_cases", {
            "participant_id": participant["id"],
            "termination_case_id": participant["termination_case_id"],
            "status": "STEP1_COMMERCIAL_LOCATOR",
            "opened_at": ts,
            "resolved_at": None,
            "exhausted_at": None,
            "exhausted_by_user_id": None,
            "exhaustion_snapshot_cents": None,
        })
    else:
        # Reopen the RESOLVED case: protocol restarts at step 1, resolved_at
        # cleared, opened_at preserved, attempt history intact.
        search_case = existing
        search_case["status"] = "STEP1_COMMERCIAL_LOCATOR"
        search_case["resolved_at"] = None
        db.touch(search_case)
    participant["active_search_case_id"] = search_case["id"]
    db.touch(participant)
    return success_obj(public_participant(participant), 200)


@bp.post("/participants/<participant_id>/locate")
def locate(participant_id):
    authenticate(["PlanAdministrator"])
    body = body_json()
    check_shape(body, {"verified_address": {"type": "string"}})
    participant = _get_participant(participant_id)
    if participant["locate_status"] != "MISSING":
        raise ApiError(
            ERR_PARTICIPANT_NOT_MISSING, 409,
            "locate requires locate_status MISSING",
        )
    services.locate_participant(participant)
    return success_obj(public_participant(participant), 200)


@bp.post("/participants/<participant_id>/apply-default-treatment")
def apply_default_treatment(participant_id):
    authenticate(["PlanAdministrator"])
    body = body_json()
    check_no_fields(body)
    participant = _get_participant(participant_id)
    case = db.get("cases", participant["termination_case_id"])
    # Priority 6: from-state gates.
    if case["status"] != "DISTRIBUTION_IN_PROGRESS":
        raise ApiError(
            ERR_CASE_INVALID_STATE, 409,
            "apply-default-treatment requires DISTRIBUTION_IN_PROGRESS",
        )
    if participant["distribution_status"] not in ("PENDING_ELECTION", "RESTORED"):
        raise ApiError(
            ERR_ELECTION_INVALID_STATE, 409,
            "default treatment requires PENDING_ELECTION or RESTORED",
        )
    # Priority 10: statutory window (strictly-greater comparison).
    dtd = services.default_treatment_date(case)
    if dtd is None or not db.now() > dtd:
        raise ApiError(
            ERR_DEFAULT_TREATMENT_WINDOW_NOT_PASSED, 409,
            "the default treatment date has not passed",
        )
    # Priority 11: cross-entity state.
    if participant["locate_status"] == "MISSING":
        raise ApiError(
            ERR_PARTICIPANT_MISSING_REQUIRES_SEARCH, 409,
            "missing participants must go through the search protocol",
        )
    # Priority 12: money rules; tier resolution (inclusive bounds).
    net = services.net_distributable(participant)
    if net > services.FORCED_ROLLOVER_LIMIT_CENTS:
        raise ApiError(
            ERR_BALANCE_EXCEEDS_FORCED_LIMIT, 422,
            "balance exceeds the forced-distribution limit",
        )
    method = (
        "LUMP_SUM_CHECK"
        if net < services.CASHOUT_LIMIT_CENTS
        else "AUTO_ROLLOVER_IRA"
    )
    services.create_payout(participant, "DEFAULT_TREATMENT", method, None)
    participant["distribution_status"] = "ELECTION_ACCEPTED"
    db.touch(participant)
    return success_obj(public_participant(participant), 200)
