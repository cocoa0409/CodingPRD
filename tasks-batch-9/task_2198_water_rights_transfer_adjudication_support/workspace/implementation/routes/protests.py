"""Protest filing, routing and resolution."""
from flask import Blueprint

import calc
import cascades
import clock
import db
import derive
import middleware
import response
import serialize
import validate
from errors import ApiError
from routes import common

bp = Blueprint("protests", __name__)

BASES = (
    "INJURY_TO_SENIOR_RIGHT",
    "PUBLIC_INTEREST",
    "ENLARGEMENT",
    "NO_BENEFICIAL_USE",
)
TRACKS = ("NEGOTIATION", "HEARING")
PROTEST_STATUSES = (
    "FILED",
    "IN_NEGOTIATION",
    "IN_HEARING",
    "RESOLVED_STIPULATED",
    "DISMISSED",
    "WITHDRAWN",
)
OUTCOMES = ("STIPULATE", "DISMISS")
CONDITION_TYPES = (
    "DRY_YEAR_FORBEARANCE",
    "MEASUREMENT_DEVICE",
    "RETURN_FLOW_MAINTENANCE",
    "MITIGATION_PAYMENT",
)
PROTESTABLE_APP_STATUSES = ("PROTEST_PERIOD", "UNDER_PROTEST")


@bp.route("/protests", methods=["POST"])
def create_protest():
    caller = middleware.authenticate((middleware.ROLE_CLAIMANT,))

    body = validate.get_body()
    raw_protestant = body.get("protestant_claimant_id")
    if isinstance(raw_protestant, str) and caller.user_id != raw_protestant:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER",
            "A claimant may only file a protest in its own name.",
        )

    app_id = validate.req_str(body, "transfer_application_id")
    protestant_id = validate.req_str(body, "protestant_claimant_id")
    claimed_af = validate.req_decimal(body, "claimed_injury_af", gt=0)
    basis = validate.req_enum(body, "basis", BASES)

    app = common.get_app(app_id)
    protestant = common.get_claimant(protestant_id)

    derive.recompute_app(app)
    if app["status"] not in PROTESTABLE_APP_STATUSES:
        raise ApiError(
            "ERR_INVALID_STATE",
            "An application in status %s is not open to protest." % app["status"],
        )
    if protestant["standing_status"] == "BARRED":
        raise ApiError(
            "ERR_CLAIMANT_NOT_IN_GOOD_STANDING",
            "A BARRED claimant may not file a protest.",
        )

    deadline = (
        clock.parse_date(app["protest_deadline"]) if app["protest_deadline"] else None
    )
    if deadline is None or clock.now() >= deadline:
        raise ApiError(
            "ERR_PROTEST_WINDOW_CLOSED",
            "The protest window for this application has closed.",
        )

    right = db.water_rights.get(app["water_right_id"])
    if right is not None and right["claimant_id"] == protestant["id"]:
        raise ApiError(
            "ERR_SELF_PROTEST_FORBIDDEN",
            "A claimant may not protest its own transfer application.",
        )

    for existing in derive.protests_for_app(app["id"]):
        if existing["protestant_claimant_id"] == protestant["id"]:
            raise ApiError(
                "ERR_DUPLICATE_PROTEST",
                "This claimant has already filed a protest on the application.",
            )

    row = db.base_row()
    row.update({
        "transfer_application_id": app["id"],
        "protestant_claimant_id": protestant["id"],
        "claimed_injury_af": calc.q2(claimed_af),
        "basis": basis,
        "track": None,
        "status": "FILED",
        "stipulated_offset_af": calc.D("0.00"),
        "resolution_note": None,
        "resolved_by_user_id": None,
    })
    db.protests[row["id"]] = row

    if app["status"] == "PROTEST_PERIOD":
        app["status"] = "UNDER_PROTEST"
    derive.recompute_app(app)
    db.touch(app)
    return response.object_response(serialize.protest(row), 201)


@bp.route("/protests", methods=["GET"])
def list_protests():
    middleware.authenticate(middleware.ALL_ROLES)
    limit, offset = validate.pagination()
    app_id = validate.query_str("transfer_application_id")
    protestant_id = validate.query_str("protestant_claimant_id")
    status = validate.query_enum("status", PROTEST_STATUSES)
    track = validate.query_enum("track", TRACKS)

    rows = []
    for row in db.protests.values():
        if app_id is not None and row["transfer_application_id"] != app_id:
            continue
        if protestant_id is not None and row["protestant_claimant_id"] != protestant_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if track is not None and row["track"] != track:
            continue
        rows.append(row)
    rows = common.sort_created_asc(rows)
    return common.emit(rows, serialize.protest, limit, offset)


@bp.route("/protests/<pid>", methods=["GET"])
def get_protest(pid):
    caller = middleware.authenticate(middleware.ALL_ROLES)
    protest = common.get_protest(pid)
    middleware.require_owner(caller, common.protest_owner(protest))
    return response.object_response(serialize.protest(protest))


@bp.route("/protests/<pid>/route", methods=["POST"])
def route_protest(pid):
    middleware.authenticate((middleware.ROLE_HEARING,))
    protest = common.get_protest(pid)

    body = validate.get_body()
    track = validate.req_enum(body, "track", TRACKS)

    if protest["status"] != "FILED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a FILED protest may be routed (status is %s)." % protest["status"],
        )

    protest["track"] = track
    protest["status"] = "IN_NEGOTIATION" if track == "NEGOTIATION" else "IN_HEARING"
    db.touch(protest)
    return response.object_response(serialize.protest(protest))


def _clear(app, right_touched=True):
    """Apply protest-clearance links 3-5 and bump the application once."""
    cascades.protest_clearance(app)
    derive.recompute_app(app)
    db.touch(app)


@bp.route("/protests/<pid>/resolve", methods=["POST"])
def resolve_protest(pid):
    caller = middleware.authenticate((middleware.ROLE_HEARING,))
    protest = common.get_protest(pid)

    body = validate.get_body()
    outcome = validate.req_enum(body, "outcome", OUTCOMES)
    note = validate.req_str(body, "resolution_note", min_len=1, max_len=500)

    if protest["status"] not in ("IN_NEGOTIATION", "IN_HEARING"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a routed protest may be resolved (status is %s)." % protest["status"],
        )
    track = protest["track"]
    if track == "NEGOTIATION" and outcome == "DISMISS":
        raise ApiError(
            "ERR_INVALID_STATE",
            "A NEGOTIATION-track protest cannot be dismissed; withdraw or "
            "stipulate instead.",
        )

    offset = None
    condition_type = None
    due_raw = None
    if track == "NEGOTIATION" and outcome == "STIPULATE":
        # PRD §3.6 gives both ends of the bound the same domain identity: the
        # offset "must be strictly greater than 0.00 and no greater than the
        # protest's `claimed_injury_af`, with equality accepted; a value at or
        # below zero or above the claim is `ERR_OFFSET_EXCEEDS_CLAIM` (HTTP 422)",
        # so the lower bound is not an ERR_INVALID_REQUEST well-formedness check.
        offset = validate.req_decimal(body, "stipulated_offset_af")
    elif track == "HEARING" and outcome == "STIPULATE":
        condition_type = validate.req_enum(body, "condition_type", CONDITION_TYPES)
        due_raw, _due = validate.opt_date(body, "compliance_due_date")

    if offset is not None:
        offset = calc.q2(offset)
        if offset <= calc.q2(0) or offset > calc.q2(protest["claimed_injury_af"]):
            raise ApiError(
                "ERR_OFFSET_EXCEEDS_CLAIM",
                "stipulated_offset_af %s must be strictly greater than 0.00 and "
                "no greater than claimed_injury_af %s."
                % (offset, protest["claimed_injury_af"]),
            )

    app = db.transfer_applications.get(protest["transfer_application_id"])
    protest["resolution_note"] = note
    protest["resolved_by_user_id"] = caller.user_id

    if outcome == "DISMISS":
        protest["status"] = "DISMISSED"
    else:
        protest["status"] = "RESOLVED_STIPULATED"
        if offset is not None:
            protest["stipulated_offset_af"] = offset
    db.touch(protest)

    if app is None:
        return response.object_response(serialize.protest(protest))

    if track == "HEARING" and outcome == "STIPULATE":
        condition = cascades.create_condition(
            app,
            condition_type,
            protest["claimed_injury_af"],
            due_raw,
            "HEARING_RESOLUTION",
            caller.user_id,
        )
        if condition["payment_status"] == "OUTSTANDING":
            owner_id = derive.app_owner_claimant_id(app)
            derive.apply_fee_cascade(db.claimants.get(owner_id))

    if track == "NEGOTIATION" and outcome == "STIPULATE":
        analysis = cascades.draft_analysis(app)
        if analysis is not None:
            cascades.recompute_analysis(analysis, app)

    _clear(app)
    return response.object_response(serialize.protest(protest))


@bp.route("/protests/<pid>/withdraw", methods=["POST"])
def withdraw_protest(pid):
    caller = middleware.authenticate(
        (middleware.ROLE_CLAIMANT, middleware.ROLE_ADJUDICATOR)
    )
    protest = common.get_protest(pid)
    middleware.require_owner(caller, common.protest_owner(protest))

    body = validate.get_body()
    validate.req_str(body, "withdrawal_reason", min_len=1, max_len=500)

    if protest["status"] not in derive.PROTEST_OPEN_STATUSES:
        raise ApiError(
            "ERR_INVALID_STATE",
            "A protest in status %s can no longer be withdrawn." % protest["status"],
        )

    protest["status"] = "WITHDRAWN"
    db.touch(protest)

    app = db.transfer_applications.get(protest["transfer_application_id"])
    if app is not None:
        _clear(app)
    return response.object_response(serialize.protest(protest))
