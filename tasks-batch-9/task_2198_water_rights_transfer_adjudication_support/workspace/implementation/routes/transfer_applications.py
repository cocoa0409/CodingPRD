"""TransferApplication lifecycle: draft, submit, publish, revise, decide."""
from decimal import Decimal

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

bp = Blueprint("transfer_applications", __name__)

APP_TYPES = (
    "CHANGE_OF_USE",
    "POINT_OF_DIVERSION_CHANGE",
    "PLACE_OF_USE_CHANGE",
    "COMBINED",
)
APP_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "PROTEST_PERIOD",
    "UNDER_PROTEST",
    "REVISION_REQUESTED",
    "READY_FOR_DECISION",
    "APPROVED",
    "APPROVED_WITH_CONDITIONS",
    "DENIED",
    "WITHDRAWN",
)
PURPOSES = ("IRRIGATION", "MUNICIPAL", "STOCKWATER", "INDUSTRIAL", "INSTREAM_FLOW")
CONDITION_TYPES = (
    "DRY_YEAR_FORBEARANCE",
    "MEASUREMENT_DEVICE",
    "RETURN_FLOW_MAINTENANCE",
    "MITIGATION_PAYMENT",
)
DISPOSITIONS = ("APPROVE", "APPROVE_WITH_CONDITIONS", "DENY")
MITIGATING_CONDITION_TYPES = ("MITIGATION_PAYMENT", "DRY_YEAR_FORBEARANCE")

REVISION_ROUND_CAP = 2
FIRST_WINDOW_DAYS = 30
REVISED_WINDOW_DAYS = 15
TRANSFERABLE_STATUSES = ("ACTIVE", "ENCUMBERED", "PARTIALLY_TRANSFERRED")
ZERO2 = Decimal("0.00")


def _require_transferable(right):
    if right["status"] not in TRANSFERABLE_STATUSES:
        raise ApiError(
            "ERR_RIGHT_NOT_TRANSFERABLE",
            "A right in status %s cannot back a transfer." % right["status"],
        )


def _require_good_standing(claimant):
    if claimant is None:
        return
    if claimant["standing_status"] != "IN_GOOD_STANDING":
        raise ApiError(
            "ERR_CLAIMANT_NOT_IN_GOOD_STANDING",
            "The claimant's standing is %s." % claimant["standing_status"],
        )


def _stale_right(body, right):
    expected = validate.req_int(body, "expected_water_right_version", minimum=0)
    if expected != right["version"]:
        raise ApiError(
            "ERR_STALE_RIGHT_VERSION",
            "expected_water_right_version %d does not match version %d."
            % (expected, right["version"]),
        )


# ---------------------------------------------------------------------------
# Create / read
# ---------------------------------------------------------------------------

@bp.route("/transfer-applications", methods=["POST"])
def create_app():
    caller = middleware.authenticate(
        (middleware.ROLE_ANALYST, middleware.ROLE_ADJUDICATOR, middleware.ROLE_CLAIMANT)
    )
    body = validate.get_body()
    common.owner_precheck(
        caller, body, "water_right_id", db.water_rights, common.right_owner
    )

    right_id = validate.req_str(body, "water_right_id")
    study_id = validate.req_str(body, "hcu_study_id")
    app_type = validate.req_enum(body, "application_type", APP_TYPES)
    requested_af = validate.req_decimal(body, "requested_af", gt=0)
    pod_id = validate.opt_str(body, "proposed_point_of_diversion_id")
    purpose = validate.opt_enum(body, "proposed_purpose_of_use", PURPOSES)
    place_acres = validate.opt_decimal(body, "proposed_place_of_use_acres", gte=0)

    right = common.get_right(right_id)
    study = common.get_study(study_id)
    pod = common.get_pod(pod_id) if pod_id is not None else None

    # priority 8 -- scope coherence
    pod_required = app_type in ("POINT_OF_DIVERSION_CHANGE", "COMBINED")
    purpose_required = app_type in ("CHANGE_OF_USE", "COMBINED")
    acres_required = app_type in ("PLACE_OF_USE_CHANGE", "COMBINED")
    if pod_required != (pod_id is not None):
        raise ApiError(
            "ERR_APPLICATION_SCOPE_INCOMPLETE",
            "proposed_point_of_diversion_id is %s for application_type %s."
            % ("required" if pod_required else "not permitted", app_type),
        )
    if purpose_required != (purpose is not None):
        raise ApiError(
            "ERR_APPLICATION_SCOPE_INCOMPLETE",
            "proposed_purpose_of_use is %s for application_type %s."
            % ("required" if purpose_required else "not permitted", app_type),
        )
    if acres_required != (place_acres is not None):
        raise ApiError(
            "ERR_APPLICATION_SCOPE_INCOMPLETE",
            "proposed_place_of_use_acres is %s for application_type %s."
            % ("required" if acres_required else "not permitted", app_type),
        )

    # priority 9 -- study / headgate belong to the same right
    if study["water_right_id"] != right["id"]:
        raise ApiError(
            "ERR_STUDY_RIGHT_MISMATCH",
            "The referenced study belongs to a different water right.",
        )
    if pod is not None and pod["water_right_id"] != right["id"]:
        raise ApiError(
            "ERR_STUDY_RIGHT_MISMATCH",
            "The proposed point of diversion belongs to a different water right.",
        )

    row = db.base_row()
    row.update({
        "water_right_id": right["id"],
        "hcu_study_id": study["id"],
        "proposed_point_of_diversion_id": pod["id"] if pod else None,
        "application_type": app_type,
        "requested_af": calc.q2(requested_af),
        "proposed_purpose_of_use": purpose,
        "proposed_place_of_use_acres": (
            calc.q2(place_acres) if place_acres is not None else None
        ),
        "status": "DRAFT",
        "revision_round": 0,
        "protest_deadline": None,
        "unresolved_protest_count": 0,
        "escrowed_af": ZERO2,
        "mitigation_fee_total_usd": ZERO2,
        "decided_by_user_id": None,
        "decision_note": None,
    })
    db.transfer_applications[row["id"]] = row
    derive.recompute_app(row)
    return response.object_response(serialize.transfer_application(row), 201)


@bp.route("/transfer-applications", methods=["GET"])
def list_apps():
    middleware.authenticate(middleware.ALL_ROLES)
    limit, offset = validate.pagination()
    right_id = validate.query_str("water_right_id")
    study_id = validate.query_str("hcu_study_id")
    pod_id = validate.query_str("proposed_point_of_diversion_id")
    status = validate.query_enum("status", APP_STATUSES)

    rows = []
    for row in db.transfer_applications.values():
        derive.recompute_app(row)
        if right_id is not None and row["water_right_id"] != right_id:
            continue
        if study_id is not None and row["hcu_study_id"] != study_id:
            continue
        if pod_id is not None and row["proposed_point_of_diversion_id"] != pod_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    rows = common.sort_created_desc(rows)
    return common.emit(rows, serialize.transfer_application, limit, offset)


@bp.route("/transfer-applications/<aid>", methods=["GET"])
def get_app(aid):
    caller = middleware.authenticate(middleware.ALL_ROLES)
    app = common.get_app(aid)
    middleware.require_owner(caller, common.app_owner(app))
    return response.object_response(serialize.transfer_application(app))


# ---------------------------------------------------------------------------
# Submit / publish / close protest period
# ---------------------------------------------------------------------------

@bp.route("/transfer-applications/<aid>/submit", methods=["POST"])
def submit_app(aid):
    caller = middleware.authenticate(
        (middleware.ROLE_ANALYST, middleware.ROLE_ADJUDICATOR, middleware.ROLE_CLAIMANT)
    )
    app = common.get_app(aid)
    right = common.get_right(app["water_right_id"])
    middleware.require_owner(caller, right["claimant_id"])

    body = validate.get_body()
    derive.recompute_right(right)
    _stale_right(body, right)

    study = db.hcu_studies.get(app["hcu_study_id"])
    if app["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a DRAFT application may be submitted (status is %s)." % app["status"],
        )
    if study is None or study["status"] != "CERTIFIED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "The relied-upon consumptive-use study must be CERTIFIED.",
        )
    _require_transferable(right)
    _require_good_standing(db.claimants.get(right["claimant_id"]))

    requested = calc.q2(app["requested_af"])
    if requested > right["transferable_af"]:
        raise ApiError(
            "ERR_TRANSFERABLE_VOLUME_EXCEEDED",
            "requested_af %s exceeds transferable_af %s."
            % (requested, right["transferable_af"]),
        )

    app["status"] = "SUBMITTED"
    derive.recompute_app(app)
    db.touch(app)
    derive.recompute_right(right)
    db.touch(right)
    claimant = db.claimants.get(right["claimant_id"])
    if claimant is not None:
        derive.recompute_claimant(claimant)
    return response.object_response(serialize.transfer_application(app))


@bp.route("/transfer-applications/<aid>/publish", methods=["POST"])
def publish_app(aid):
    middleware.authenticate((middleware.ROLE_ANALYST, middleware.ROLE_ADJUDICATOR))
    app = common.get_app(aid)
    validate.get_body(required=False)

    if app["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a SUBMITTED application may be published (status is %s)."
            % app["status"],
        )
    if cascades.latest_live_analysis(app) is None:
        raise ApiError(
            "ERR_INJURY_ANALYSIS_MISSING",
            "An injury analysis must exist before the protest window opens.",
        )

    days = FIRST_WINDOW_DAYS if app["revision_round"] == 0 else REVISED_WINDOW_DAYS
    app["status"] = "PROTEST_PERIOD"
    app["protest_deadline"] = clock.format_instant(clock.now() + days * clock.DAY)
    derive.recompute_app(app)
    db.touch(app)
    return response.object_response(serialize.transfer_application(app))


@bp.route("/transfer-applications/<aid>/close-protest-period", methods=["POST"])
def close_protest_period(aid):
    middleware.authenticate(
        (middleware.ROLE_ANALYST, middleware.ROLE_HEARING, middleware.ROLE_ADJUDICATOR)
    )
    app = common.get_app(aid)

    if app["status"] != "PROTEST_PERIOD":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a PROTEST_PERIOD application may be closed (status is %s)."
            % app["status"],
        )
    deadline = clock.parse_date(app["protest_deadline"]) if app["protest_deadline"] else None
    if deadline is not None and clock.now() < deadline:
        raise ApiError(
            "ERR_WINDOW_STILL_OPEN",
            "The protest window is open until %s." % app["protest_deadline"],
        )

    app["status"] = "READY_FOR_DECISION"
    cascades.finalize_draft_analyses(app)
    derive.recompute_app(app)
    db.touch(app)
    right = db.water_rights.get(app["water_right_id"])
    if right is not None:
        derive.recompute_right(right)
        db.touch(right)
    return response.object_response(serialize.transfer_application(app))


# ---------------------------------------------------------------------------
# Revision leg
# ---------------------------------------------------------------------------

@bp.route("/transfer-applications/<aid>/request-revision", methods=["POST"])
def request_revision(aid):
    middleware.authenticate((middleware.ROLE_HEARING,))
    app = common.get_app(aid)
    body = validate.get_body()
    validate.req_str(body, "revision_note", min_len=1, max_len=500)

    derive.recompute_app(app)
    if app["status"] != "UNDER_PROTEST":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only an UNDER_PROTEST application may be sent back (status is %s)."
            % app["status"],
        )
    if app["revision_round"] >= REVISION_ROUND_CAP:
        raise ApiError(
            "ERR_REVISION_LIMIT_REACHED",
            "revision_round %d has reached the cap of %d."
            % (app["revision_round"], REVISION_ROUND_CAP),
        )

    app["status"] = "REVISION_REQUESTED"
    app["protest_deadline"] = None
    derive.recompute_app(app)
    db.touch(app)
    return response.object_response(serialize.transfer_application(app))


@bp.route("/transfer-applications/<aid>/resubmit", methods=["POST"])
def resubmit_app(aid):
    caller = middleware.authenticate(
        (middleware.ROLE_ANALYST, middleware.ROLE_ADJUDICATOR, middleware.ROLE_CLAIMANT)
    )
    app = common.get_app(aid)
    right = common.get_right(app["water_right_id"])
    middleware.require_owner(caller, right["claimant_id"])

    body = validate.get_body()
    new_requested = validate.req_decimal(body, "requested_af", gt=0)
    derive.recompute_right(right)
    _stale_right(body, right)

    if app["status"] != "REVISION_REQUESTED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a REVISION_REQUESTED application may be resubmitted (status is %s)."
            % app["status"],
        )
    study = db.hcu_studies.get(app["hcu_study_id"])
    if study is None or study["status"] != "CERTIFIED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "The relied-upon consumptive-use study must be CERTIFIED.",
        )
    _require_transferable(right)
    _require_good_standing(db.claimants.get(right["claimant_id"]))
    if app["revision_round"] >= REVISION_ROUND_CAP:
        raise ApiError(
            "ERR_REVISION_LIMIT_REACHED",
            "revision_round %d has reached the cap of %d."
            % (app["revision_round"], REVISION_ROUND_CAP),
        )

    derive.recompute_app(app)
    budget = calc.q2(right["transferable_af"] + app["escrowed_af"])
    new_requested = calc.q2(new_requested)
    if new_requested > budget:
        raise ApiError(
            "ERR_TRANSFERABLE_VOLUME_EXCEEDED",
            "requested_af %s exceeds transferable_af + escrowed_af (%s)."
            % (new_requested, budget),
        )

    app["requested_af"] = new_requested
    app["status"] = "SUBMITTED"
    app["revision_round"] = app["revision_round"] + 1
    derive.recompute_app(app)
    db.touch(app)

    derive.recompute_right(right)
    db.touch(right)

    analysis = cascades.draft_analysis(app)
    if analysis is not None:
        cascades.recompute_analysis(analysis, app)
    return response.object_response(serialize.transfer_application(app))


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------

def _parse_conditions(body, disposition):
    raw = body.get("conditions")
    if disposition == "APPROVE_WITH_CONDITIONS":
        if not isinstance(raw, list) or not raw:
            raise validate.invalid(
                "conditions must be a non-empty array for APPROVE_WITH_CONDITIONS."
            )
    else:
        if raw is not None:
            raise validate.invalid(
                "conditions is only permitted for APPROVE_WITH_CONDITIONS."
            )
        return []

    parsed = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise validate.invalid("Each conditions entry must be an object.")
        ctype = validate.req_enum(entry, "condition_type", CONDITION_TYPES)
        required_af = validate.req_decimal(entry, "required_af", gt=0)
        due_raw, _due = validate.opt_date(entry, "compliance_due_date")
        parsed.append({
            "condition_type": ctype,
            "required_af": calc.q2(required_af),
            "compliance_due_date": due_raw,
        })
    return parsed


def _segregation_check(caller, app, study):
    if study is not None and study.get("certified_by_user_id") == caller.user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The operator who certified the consumptive-use study may not decide "
            "the application.",
        )
    for protest in derive.protests_for_app(app["id"]):
        if protest.get("resolved_by_user_id") == caller.user_id:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                "The operator who resolved a protest on this application may not "
                "decide it.",
            )


def _authorize_proposed_pod(app):
    if app["application_type"] not in ("POINT_OF_DIVERSION_CHANGE", "COMBINED"):
        return
    pod_id = app["proposed_point_of_diversion_id"]
    if pod_id is None:
        return
    for pod in derive.pods_for_right(app["water_right_id"]):
        if pod["id"] == pod_id:
            if pod["status"] == "PROPOSED":
                pod["status"] = "AUTHORIZED"
                db.touch(pod)
        elif pod["status"] == "AUTHORIZED":
            pod["status"] = "RETIRED"
            db.touch(pod)


@bp.route("/transfer-applications/<aid>/decide", methods=["POST"])
def decide_app(aid):
    caller = middleware.authenticate((middleware.ROLE_DECISION,))
    app = common.get_app(aid)

    body = validate.get_body()
    disposition = validate.req_enum(body, "disposition", DISPOSITIONS)
    validate.req_str(body, "decision_note", min_len=1, max_len=500)
    conditions = _parse_conditions(body, disposition)

    derive.recompute_app(app)
    if app["status"] != "READY_FOR_DECISION":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a READY_FOR_DECISION application may be decided (status is %s)."
            % app["status"],
        )

    study = db.hcu_studies.get(app["hcu_study_id"])
    _segregation_check(caller, app, study)

    analysis = cascades.finalized_analysis(app)
    if analysis is None:
        raise ApiError(
            "ERR_INJURY_ANALYSIS_MISSING",
            "A FINALIZED injury analysis is required before a decision.",
        )
    net = calc.q2(analysis["net_injury_af"])

    if disposition == "APPROVE":
        if net >= calc.D(calc.INJURY_MATERIALITY_AF):
            raise ApiError(
                "ERR_UNMITIGATED_INJURY",
                "net_injury_af %s is material; approve with conditions instead."
                % net,
            )
    elif disposition == "APPROVE_WITH_CONDITIONS":
        mitigating = calc.q2(
            sum(
                (
                    c["required_af"]
                    for c in conditions
                    if c["condition_type"] in MITIGATING_CONDITION_TYPES
                ),
                calc.D(0),
            )
        )
        if mitigating < net:
            raise ApiError(
                "ERR_MITIGATION_INSUFFICIENT",
                "Mitigating conditions cover %s AF of %s AF of net injury."
                % (mitigating, net),
            )

    right = db.water_rights.get(app["water_right_id"])
    app["decided_by_user_id"] = caller.user_id
    app["decision_note"] = body["decision_note"]

    if disposition == "DENY":
        app["status"] = "DENIED"
    else:
        app["status"] = (
            "APPROVED" if disposition == "APPROVE" else "APPROVED_WITH_CONDITIONS"
        )
        _authorize_proposed_pod(app)

    for spec in conditions:
        cascades.create_condition(
            app,
            spec["condition_type"],
            spec["required_af"],
            spec["compliance_due_date"],
            "DECISION",
            caller.user_id,
        )

    derive.recompute_app(app)
    db.touch(app)

    if right is not None:
        derive.recompute_right(right)
        db.touch(right)
        claimant = db.claimants.get(right["claimant_id"])
        if claimant is not None:
            if conditions:
                derive.apply_fee_cascade(claimant)
            else:
                derive.recompute_claimant(claimant)
    return response.object_response(serialize.transfer_application(app))


@bp.route("/transfer-applications/<aid>/withdraw", methods=["POST"])
def withdraw_app(aid):
    caller = middleware.authenticate(
        (middleware.ROLE_ANALYST, middleware.ROLE_ADJUDICATOR, middleware.ROLE_CLAIMANT)
    )
    app = common.get_app(aid)
    middleware.require_owner(caller, common.app_owner(app))

    body = validate.get_body()
    validate.req_str(body, "withdrawal_reason", min_len=1, max_len=500)

    derive.recompute_app(app)
    if app["status"] not in (
        "DRAFT",
        "SUBMITTED",
        "PROTEST_PERIOD",
        "UNDER_PROTEST",
        "REVISION_REQUESTED",
    ):
        raise ApiError(
            "ERR_INVALID_STATE",
            "An application in status %s can no longer be withdrawn." % app["status"],
        )

    app["status"] = "WITHDRAWN"
    cascades.dismiss_open_protests(app)
    cascades.void_draft_analyses(app)
    derive.recompute_app(app)
    db.touch(app)

    right = db.water_rights.get(app["water_right_id"])
    if right is not None:
        derive.recompute_right(right, bump=True)
        claimant = db.claimants.get(right["claimant_id"])
        if claimant is not None:
            derive.recompute_claimant(claimant)
    return response.object_response(serialize.transfer_application(app))
