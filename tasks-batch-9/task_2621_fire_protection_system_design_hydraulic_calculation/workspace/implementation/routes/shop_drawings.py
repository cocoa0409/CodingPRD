"""Shop drawing sheets and trade coordination items (PRD 3.7)."""
from flask import Blueprint

import db
import guards
import helpers
import response
import validate
from errors import ApiError
from middleware import ALL_ROLES, authenticate

bp = Blueprint("shop_drawings", __name__)

TRADES = ["STRUCTURAL", "MECHANICAL", "LIGHTING"]
CONFLICT_SEVERITIES = ["BLOCKING", "ADVISORY"]
CLEARANCE_OUTCOMES = ["CLEARED", "CONFLICT_OPEN"]
REQUIRED_TRADE_COUNT = 3


def clearances_of(shop_drawing_id):
    rows = [
        c for c in db.trade_clearances.values() if c["shop_drawing_id"] == shop_drawing_id
    ]
    return db.by_created(rows)


@bp.post("/shop-drawings")
def create_shop_drawing():
    authenticate(["Contractor"])
    data = validate.body()
    project = guards.must_fk("project", validate.raw_fk(data, "project_id"))
    calc = guards.must_fk("calculation", validate.raw_fk(data, "hydraulic_calculation_id"))
    row = {
        "project_id": validate.req_str(data, "project_id"),
        "hydraulic_calculation_id": validate.req_str(data, "hydraulic_calculation_id"),
        "sheet_number": validate.req_str(data, "sheet_number"),
    }
    guards.require_not_frozen(project)
    if calc["state"] != "SEALED":
        raise ApiError(
            "ERR_CALCULATION_NOT_SEALED",
            "A shop drawing may only detail a SEALED calculation.",
        )
    row["required_trade_count"] = REQUIRED_TRADE_COUNT
    row["cleared_trade_count"] = 0
    row["state"] = "DRAFT"
    db.stamp_create(row)
    db.shop_drawings[row["id"]] = row
    return response.created(response.public(row))


@bp.get("/shop-drawings/<drawing_id>")
def get_shop_drawing(drawing_id):
    authenticate(ALL_ROLES)
    return response.ok(response.public(guards.must("shop_drawing", drawing_id)))


@bp.get("/shop-drawings")
def list_shop_drawings():
    authenticate(ALL_ROLES)
    rows = helpers.apply_filters(
        list(db.shop_drawings.values()),
        ["project_id", "hydraulic_calculation_id", "state"],
    )
    return helpers.list_response(rows)


@bp.post("/shop-drawings/<drawing_id>/trade-clearances")
def open_clearance(drawing_id):
    authenticate(["Contractor"])
    drawing = guards.must("shop_drawing", drawing_id)
    project = guards.must("project", drawing["project_id"])
    data = validate.body()
    row = {
        "shop_drawing_id": drawing["id"],
        "trade": validate.req_str(data, "trade", enum=TRADES),
        "elevation_low_in": validate.req_num(data, "elevation_low_in"),
        "elevation_high_in": validate.req_num(data, "elevation_high_in"),
    }
    if not row["elevation_high_in"] > row["elevation_low_in"]:
        validate._bad("Field 'elevation_high_in' must be greater than 'elevation_low_in'.")

    guards.require_not_frozen(project)
    if drawing["state"] == "ISSUED":
        guards.terminal("The sheet is ISSUED; its coordination record is frozen.")
    for existing in clearances_of(drawing["id"]):
        if existing["trade"] == row["trade"]:
            raise ApiError(
                "ERR_DUPLICATE_TRADE_CLEARANCE",
                "A clearance for trade %s already exists on this sheet." % row["trade"],
            )

    row["conflict_severity"] = None
    row["note"] = None
    row["state"] = "PENDING"
    db.stamp_create(row)
    db.trade_clearances[row["id"]] = row

    if drawing["state"] == "DRAFT":
        drawing["state"] = "IN_COORDINATION"
        db.touch(drawing)
    return response.created(response.public(row))


@bp.get("/shop-drawings/<drawing_id>/trade-clearances")
def list_clearances(drawing_id):
    authenticate(ALL_ROLES)
    guards.must("shop_drawing", drawing_id)
    rows = helpers.apply_filters(clearances_of(drawing_id), ["state"])
    return helpers.list_response(rows)


@bp.post("/trade-clearances/<clearance_id>/record")
def record_clearance(clearance_id):
    actor = authenticate(["DesignEngineer"])
    item = guards.must("trade_clearance", clearance_id)
    drawing = guards.must("shop_drawing", item["shop_drawing_id"])
    project = guards.must("project", drawing["project_id"])
    guards.require_lead_engineer(actor, project)
    data = validate.body()
    outcome = validate.req_str(data, "outcome", enum=CLEARANCE_OUTCOMES)
    severity = validate.opt_str(data, "conflict_severity", enum=CONFLICT_SEVERITIES)
    note = validate.opt_str(data, "note")
    if outcome == "CONFLICT_OPEN" and severity is None:
        validate._bad("Field 'conflict_severity' is required when outcome is CONFLICT_OPEN.")

    guards.require_not_frozen(project)
    if item["state"] == "LOCKED":
        guards.terminal("The trade clearance is LOCKED and may not be dispositioned.")

    others = [c for c in clearances_of(drawing["id"]) if c["id"] != item["id"]]
    if outcome == "CLEARED":
        if item["state"] not in ("PENDING", "CONFLICT_OPEN", "STALE"):
            guards.invalid_transition(
                "No CLEARED disposition is declared from clearance state %s." % item["state"]
            )
        if item["state"] == "STALE":
            allowed_sheet = ("STALE", "IN_COORDINATION")
        else:
            allowed_sheet = ("IN_COORDINATION", "CONFLICTED", "STALE")
        if drawing["state"] not in allowed_sheet:
            guards.invalid_transition(
                "A CLEARED disposition is not admissible while the sheet is %s."
                % drawing["state"]
            )
        reaching = (drawing["cleared_trade_count"] or 0) + 1 >= drawing["required_trade_count"]
        if drawing["state"] == "CONFLICTED":
            if reaching:
                if any(c["state"] == "CONFLICT_OPEN" for c in others):
                    guards.invalid_transition(
                        "The sheet cannot become COORDINATED while an item remains in CONFLICT_OPEN."
                    )
            else:
                if any(
                    c["state"] == "CONFLICT_OPEN" and c["conflict_severity"] == "BLOCKING"
                    for c in others
                ):
                    guards.invalid_transition(
                        "The sheet cannot leave CONFLICTED while a BLOCKING conflict remains open."
                    )
        if drawing["state"] == "STALE" and not reaching:
            calc = db.calculations.get(drawing["hydraulic_calculation_id"])
            if calc is not None and calc["state"] == "REOPENED":
                guards.invalid_transition(
                    "A STALE sheet may not re-enter coordination while its calculation is REOPENED."
                )
        item["state"] = "CLEARED"
        item["conflict_severity"] = None
    else:
        if item["state"] != "PENDING":
            guards.invalid_transition(
                "A CONFLICT_OPEN disposition is only declared from PENDING."
            )
        item["state"] = "CONFLICT_OPEN"
        item["conflict_severity"] = severity
    item["note"] = note
    db.touch(item)

    cleared = len([c for c in clearances_of(drawing["id"]) if c["state"] == "CLEARED"])
    drawing["cleared_trade_count"] = cleared
    if outcome == "CLEARED":
        if cleared >= drawing["required_trade_count"]:
            drawing["state"] = "COORDINATED"
        else:
            drawing["state"] = "IN_COORDINATION"
    elif severity == "BLOCKING" and drawing["state"] == "IN_COORDINATION":
        drawing["state"] = "CONFLICTED"
    db.touch(drawing)
    return response.ok(response.public(item))
