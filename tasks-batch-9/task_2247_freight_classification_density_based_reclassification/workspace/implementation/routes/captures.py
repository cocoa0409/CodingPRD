"""Terminal capture events and inspector findings."""
from flask import Blueprint

import auth
import clock
import db
import response
import serialize
import validation
from constants import (
    DEVICE_TYPES,
    FINDING_BASES,
    FINDING_STATUSES,
    MIN_FINDING_PHOTOS,
    REWEIGH_MIN_ABS_LB,
    REWEIGH_VARIANCE_PCT,
)
from errors import fail
from routes import _helpers as h
from services import notices, rating
from util import D, rhu

bp = Blueprint("captures", __name__)

CAPTURE_READ_ROLES = ("TerminalOperator", "ClassificationAuditor", "PricingAnalyst", "DisputeReviewer")
FINDING_READ_ROLES = ("FreightInspector", "ClassificationAuditor", "DisputeReviewer")

DIMENSION_FIELDS = ("measured_length_in", "measured_width_in", "measured_height_in")


# ---------------------------------------------------------------------------
# capture events (PRD 3.6)
# ---------------------------------------------------------------------------
def _parse_measurements(raw):
    if not isinstance(raw, list) or not raw:
        fail("ERR_INVALID_REQUEST", "line_measurements must be a non-empty array.")
    parsed = []
    for element in raw:
        if not isinstance(element, dict):
            fail("ERR_INVALID_REQUEST", "each line measurement must be an object.")
        item = {
            "line_no": validation.req_int(element, "line_no", minimum=1),
            "measured_weight_lb": validation.req_int(element, "measured_weight_lb", minimum=1),
        }
        present = [field for field in DIMENSION_FIELDS if element.get(field) is not None]
        if present and len(present) != len(DIMENSION_FIELDS):
            fail(
                "ERR_INVALID_REQUEST",
                "a line measurement must carry all three measured dimensions or none.",
            )
        for field in present:
            item[field] = validation.req_number(element, field)
        parsed.append(item)
    return parsed


@bp.post("/ltl/capture-events")
def create_capture_event():
    auth.authenticate(("TerminalOperator",))
    body = validation.body()
    shipment = validation.fk(body, "shipment_id", "shipments", "ERR_SHIPMENT_NOT_FOUND")
    if shipment is None:
        validation.req_str(body, "shipment_id")
    auth.require_owner(shipment["origin_terminal_id"])

    device_type = validation.req_enum(body, "device_type", DEVICE_TYPES)
    total_weight = validation.req_int(body, "measured_total_weight_lb", minimum=1)
    measurements = _parse_measurements(body.get("line_measurements"))

    for item in measurements:
        for field in DIMENSION_FIELDS:
            if field in item:
                item[field] = validation.as_dimension(item[field], field)

    if shipment["billing_status"] == "CLOSED":
        fail("ERR_INVALID_STATE_TRANSITION", "The shipment is CLOSED.")

    terminal = db.get("terminals", shipment["origin_terminal_id"])
    if terminal is None or terminal["dimensioner_status"] != "CALIBRATED":
        fail("ERR_DEVICE_OUT_OF_CALIBRATION", "The terminal's dimensioner needs recalibration.")

    lines = rating.lines_of(shipment["id"])
    if not lines:
        fail("ERR_NO_SHIPMENT_LINES", "The shipment carries no bill-of-lading lines.")
    by_line_no = {int(line["line_no"]): line for line in lines}
    for item in measurements:
        if item["line_no"] not in by_line_no:
            fail(
                "ERR_LINE_NO_MISMATCH",
                "line_no %s does not exist on this shipment." % item["line_no"],
            )

    # ---- project the capture without mutating anything ---------------------
    projected = {}
    for item in measurements:
        line = by_line_no[item["line_no"]]
        draft = projected.get(line["id"]) or dict(line)
        draft["measured_weight_lb"] = item["measured_weight_lb"]
        for field in DIMENSION_FIELDS:
            if field in item:
                draft[field] = item[field]
        if (
            draft.get("measured_length_in") is not None
            and draft.get("measured_width_in") is not None
            and draft.get("measured_height_in") is not None
        ):
            cubic_ft, density = rating.cube_and_density(
                draft["measured_length_in"],
                draft["measured_width_in"],
                draft["measured_height_in"],
                draft["pieces"],
                draft["measured_weight_lb"],
            )
            draft["measured_cubic_ft"] = cubic_ft
            draft["measured_density_pcf"] = density
        rating.recompute_line_class(shipment, draft)
        projected[line["id"]] = draft

    after = [projected.get(line["id"], line) for line in lines]
    reclassed = [line for line in after if rating.is_reclassed(line)]
    triggered_reclass = bool(reclassed)

    declared_total = D(shipment["declared_total_weight_lb"] or 0)
    delta_lb = abs(D(total_weight) - declared_total)
    if declared_total == 0:
        variance_pct = rhu(0, 2)
    else:
        variance_pct = rhu(delta_lb / declared_total * 100, 2)
    reweigh_required = variance_pct >= REWEIGH_VARIANCE_PCT and delta_lb >= REWEIGH_MIN_ABS_LB
    fires = bool(reweigh_required or triggered_reclass)

    if fires and int(shipment["open_notice_count"] or 0) > 0:
        fail(
            "ERR_OPEN_NOTICE_EXISTS",
            "The shipment already carries an open correction notice.",
        )

    # ---- commit ------------------------------------------------------------
    for line in lines:
        draft = projected.get(line["id"])
        if draft is None:
            continue
        line.update(draft)
        db.touch(line)

    sequence = 1 + max(
        [
            int(event["capture_sequence"])
            for event in db.all_rows(
                "capture_events", lambda e: e["shipment_id"] == shipment["id"]
            )
        ]
        or [0]
    )
    triggered_reweigh = bool(reweigh_required) and not bool(shipment.get("reweigh_required"))

    event = db.insert(
        "capture_events",
        {
            "shipment_id": shipment["id"],
            "terminal_id": terminal["id"],
            "captured_by_user_id": auth.user_id(),
            "device_type": device_type,
            "capture_sequence": sequence,
            "measured_total_weight_lb": total_weight,
            "line_measurements": body.get("line_measurements"),
            "captured_at": clock.now(),
            "variance_pct": variance_pct,
            "triggered_reweigh": triggered_reweigh,
            "triggered_reclass": triggered_reclass,
            "reclassed_line_count": len(reclassed),
        },
        versioned=False,
    )

    terminal["captures_since_calibration"] = int(terminal["captures_since_calibration"] or 0) + 1
    terminal["last_capture_at"] = event["captured_at"]
    terminal["dimensioner_status"] = (
        "OUT_OF_CALIBRATION"
        if terminal["captures_since_calibration"] >= int(terminal["calibration_interval_captures"])
        else "CALIBRATED"
    )
    db.touch(terminal)

    shipment["measured_total_weight_lb"] = total_weight
    shipment["weight_variance_pct"] = variance_pct
    shipment["reweigh_required"] = bool(reweigh_required)
    shipment["declared_vs_found_class_delta_count"] = len(reclassed)
    if fires:
        shipment["class_status"] = "RECLASS_PENDING"
    elif shipment["class_status"] == "DECLARED":
        shipment["class_status"] = "CAPTURED"
    db.touch(shipment)

    if fires:
        if reweigh_required and triggered_reclass:
            notice_type = "BOTH"
        elif triggered_reclass:
            notice_type = "RECLASS"
        else:
            notice_type = "REWEIGH"
        notices.new_notice_row(
            shipment, notice_type, "AUTOMATED_CAPTURE", basis_capture_event_id=event["id"]
        )

    rating.recompute_line_charges(shipment)
    notices.recompute_open_notice_count(shipment)
    notices.refresh_draft_notices(shipment)
    return response.created(serialize.capture_event(event))


@bp.get("/ltl/capture-events/<event_id>")
def read_capture_event(event_id):
    auth.authenticate(CAPTURE_READ_ROLES)
    row = validation.path_row("capture_events", event_id, "ERR_CAPTURE_EVENT_NOT_FOUND")
    return response.ok(serialize.capture_event(row))


@bp.get("/ltl/capture-events")
def list_capture_events():
    auth.authenticate(CAPTURE_READ_ROLES)
    rows = db.all_rows("capture_events")
    rows = h.apply_filters(
        rows,
        (("shipment_id", "shipment_id", None), ("terminal_id", "terminal_id", None)),
    )
    return h.paged(rows, serialize.capture_event)


# ---------------------------------------------------------------------------
# inspection findings (PRD 3.6)
# ---------------------------------------------------------------------------
@bp.post("/ltl/inspection-findings")
def create_inspection_finding():
    auth.authenticate(("FreightInspector",))
    body = validation.body()
    line = validation.fk(body, "shipment_line_id", "shipment_lines", "ERR_SHIPMENT_LINE_NOT_FOUND")
    found_profile = validation.fk(
        body,
        "found_commodity_profile_id",
        "commodity_profiles",
        "ERR_COMMODITY_PROFILE_NOT_FOUND",
        required=False,
    )
    if line is None:
        validation.req_str(body, "shipment_line_id")

    basis = validation.req_enum(body, "finding_basis", FINDING_BASES)
    raw_class = body.get("found_class_code")
    if raw_class is None or not validation.is_number(raw_class):
        fail("ERR_INVALID_REQUEST", "found_class_code must be a number.")
    if basis == "COMMODITY_MISMATCH":
        if found_profile is None:
            fail(
                "ERR_INVALID_REQUEST",
                "found_commodity_profile_id is required for a COMMODITY_MISMATCH finding.",
            )
    elif found_profile is not None:
        fail(
            "ERR_INVALID_REQUEST",
            "found_commodity_profile_id must be null unless finding_basis is COMMODITY_MISMATCH.",
        )
    photos = validation.opt_int(body, "evidence_photo_count", default=0, minimum=0)
    notes = validation.opt_str(body, "notes")

    found_class = validation.as_class_code(raw_class, "found_class_code")

    shipment = h.shipment_of(line)
    if shipment is not None and shipment["billing_status"] == "CLOSED":
        fail("ERR_INVALID_STATE_TRANSITION", "The shipment is CLOSED.")

    row = db.insert(
        "inspection_findings",
        {
            "shipment_line_id": line["id"],
            "inspector_user_id": auth.user_id(),
            "finding_basis": basis,
            "found_commodity_profile_id": found_profile["id"] if found_profile else None,
            "found_class_code": found_class,
            "evidence_photo_count": photos,
            "notes": notes,
            "status": "RECORDED",
            "accepted_by_user_id": None,
            "accepted_at": None,
        },
    )

    if shipment is not None and shipment["class_status"] in ("DECLARED", "CAPTURED"):
        shipment["class_status"] = "UNDER_INSPECTION"
        db.touch(shipment)
    if shipment is not None:
        notices.refresh_draft_notices(shipment)
    return response.created(serialize.inspection_finding(row))


@bp.get("/ltl/inspection-findings/<finding_id>")
def read_inspection_finding(finding_id):
    auth.authenticate(FINDING_READ_ROLES)
    row = validation.path_row("inspection_findings", finding_id, "ERR_INSPECTION_FINDING_NOT_FOUND")
    return response.ok(serialize.inspection_finding(row))


@bp.get("/ltl/inspection-findings")
def list_inspection_findings():
    auth.authenticate(FINDING_READ_ROLES)
    rows = db.all_rows("inspection_findings")
    rows = h.apply_filters(
        rows,
        (
            ("shipment_line_id", "shipment_line_id", None),
            ("found_commodity_profile_id", "found_commodity_profile_id", None),
            ("status", "status", FINDING_STATUSES),
        ),
    )
    return h.paged(rows, serialize.inspection_finding)


@bp.post("/ltl/inspection-findings/<finding_id>/accept")
def accept_inspection_finding(finding_id):
    auth.authenticate(("ClassificationAuditor",))
    row = validation.path_row("inspection_findings", finding_id, "ERR_INSPECTION_FINDING_NOT_FOUND")
    if row["status"] != "RECORDED":
        fail("ERR_INVALID_STATE_TRANSITION", "Finding is %s, not RECORDED." % row["status"])

    line = db.get("shipment_lines", row["shipment_line_id"])
    shipment = h.shipment_of(line) if line else None
    if shipment is not None and shipment["billing_status"] == "CLOSED":
        fail("ERR_INVALID_STATE_TRANSITION", "The shipment is CLOSED.")

    if auth.user_id() == row["inspector_user_id"]:
        fail("ERR_SOD_VIOLATION", "The recording inspector may not accept their own finding.")

    if int(row["evidence_photo_count"] or 0) < MIN_FINDING_PHOTOS:
        fail(
            "ERR_INSUFFICIENT_EVIDENCE",
            "A finding needs at least %d photographs to be accepted." % MIN_FINDING_PHOTOS,
        )

    previous = rating.accepted_finding(line) if line is not None else None
    if previous is not None and previous["id"] != row["id"]:
        previous["status"] = "SUPERSEDED"
        db.touch(previous)

    row["status"] = "ACCEPTED"
    row["accepted_by_user_id"] = auth.user_id()
    row["accepted_at"] = clock.now()
    db.touch(row)

    if line is not None and shipment is not None:
        rating.recompute_line_class(shipment, line)
        db.touch(line)
        rating.recompute_line_charges(shipment)
        rating.refresh_delta_count(shipment)
        if shipment["class_status"] == "UNDER_INSPECTION":
            shipment["class_status"] = "RECLASS_PENDING"
            db.touch(shipment)
        notices.refresh_draft_notices(shipment)
    return response.ok(serialize.inspection_finding(row))
