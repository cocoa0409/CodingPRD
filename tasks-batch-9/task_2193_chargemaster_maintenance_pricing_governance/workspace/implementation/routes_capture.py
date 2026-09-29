"""Charge capture reconciliation and missing-charge findings (PRD 3.9)."""

from datetime import timedelta

from flask import Blueprint

import validate
from auth import ALL_ROLES, CO, DM, PCA, RIA, SA, require, scope_check
from calc import charge_capture_variance_summary, missing_charge_detection
from derive import find, recompute_batch_counters, recompute_department
from envelope import list_response, ok
from errors import fail
from routes_facilities import body_facility
from routes_items import body_department
from store import STORE, fmt_iso, serialize

bp = Blueprint("routes_capture", __name__)

BATCH_READERS = [SA, RIA, PCA, CO, DM]
FINDING_READERS = [SA, RIA, PCA, CO, DM]
BATCH_ACTIONS = {
    "FINALIZE": (RIA, ("RECONCILING",), "RECONCILED"),
    "DISPUTE": (DM, ("RECONCILED",), "DISPUTED"),
    "CLOSE": (RIA, ("RECONCILED",), "CLOSED"),
}
FINDING_ACTIONS = {
    "CONFIRM": (("OPEN",), "CONFIRMED"),
    "DISMISS": (("OPEN",), "DISMISSED"),
    "RESOLVE": (("CONFIRMED",), "RESOLVED"),
}


def find_batch(batch_id):
    return find(
        STORE.batches, batch_id, "ERR_CAPTURE_RESOURCE_NOT_FOUND", "ChargeCaptureBatch"
    )


def _days(start, end):
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    last = end.replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    while day <= last:
        out.append(day)
        day = day + timedelta(days=1)
    return out


@bp.route("/chargemaster/charge-capture-batches", methods=["POST"])
def create_batch():
    user_id, role = require(DM)
    data = validate.body()
    scope_check(user_id, role, data.get("department_id"))
    facility = body_facility(data)
    department = body_department(data)
    window_start = validate.req_dt(data, "window_start_date")
    window_end = validate.req_dt(data, "window_end_date")
    if window_end < window_start:
        fail("ERR_VALIDATION", "window_end_date must be no earlier than window_start_date.")

    new_days = set(_days(window_start, window_end))
    counts = {}
    for row in STORE.batches.values():
        if row["department_id"] != department["id"]:
            continue
        if row["status"] == "CLOSED":
            continue
        for day in _days(row["_window_start"], row["_window_end"]):
            if day in new_days:
                counts[day] = counts.get(day, 0) + 1
    for day in sorted(counts):
        if counts[day] >= 2:
            fail(
                "ERR_BATCH_WINDOW_CAPACITY_EXCEEDED",
                "More than two open batches would cover %s." % fmt_iso(day),
            )
    if department["capture_hold"]:
        fail("ERR_DEPARTMENT_CAPTURE_HOLD", "The department is on capture hold.")

    batch = {
        "facility_id": facility["id"],
        "department_id": department["id"],
        "window_start_date": fmt_iso(window_start),
        "window_end_date": fmt_iso(window_end),
        "status": "INGESTED",
        "line_count": 0,
        "matched_line_count": 0,
        "exception_line_count": 0,
        "mean_line_variance_bp": None,
        "total_expected_charge_cents": 0,
        "total_posted_charge_cents": 0,
        "open_finding_count": 0,
        "reconcile_pass_count": 0,
        "_window_start": window_start,
        "_window_end": window_end,
    }
    STORE.stamp_new(batch)
    STORE.batches[batch["id"]] = batch
    return ok(serialize(batch), 201)


@bp.route("/chargemaster/charge-capture-batches", methods=["GET"])
def list_batches():
    require(BATCH_READERS)
    facility_id = validate.query_filter("facility_id")
    department_id = validate.query_filter("department_id")
    status = validate.query_filter("status")

    def keep(row):
        if facility_id is not None and row["facility_id"] != facility_id:
            return False
        if department_id is not None and row["department_id"] != department_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return list_response(STORE.ordered(STORE.batches, keep), serialize)


@bp.route("/chargemaster/charge-capture-batches/<batch_id>", methods=["GET"])
def read_batch(batch_id):
    require(BATCH_READERS)
    return ok(serialize(find_batch(batch_id)))


@bp.route("/chargemaster/charge-capture-batches/<batch_id>/lines", methods=["POST"])
def append_line(batch_id):
    user_id, role = require(DM)
    data = validate.body()
    existing = STORE.batches.get(batch_id)
    if existing is not None:
        scope_check(user_id, role, existing["department_id"])
    batch = find_batch(batch_id)
    cdm_number = validate.req_string(data, "submitted_cdm_number")
    encounter_id = validate.req_string(data, "encounter_id")
    payer_code = validate.req_string(data, "payer_code")
    service_datetime = validate.req_dt(data, "service_datetime")
    quantity = validate.req_int(data, "quantity", 1)
    posted = validate.req_int(data, "posted_charge_cents")

    if batch["status"] != "INGESTED":
        fail(
            "ERR_INVALID_BATCH_STATE",
            "Lines may only be appended to an INGESTED batch.",
        )
    if service_datetime < batch["_window_start"] or service_datetime > batch["_window_end"]:
        fail(
            "ERR_SERVICE_DATE_OUTSIDE_WINDOW",
            "service_datetime falls outside the batch window.",
        )

    line = {
        "batch_id": batch["id"],
        "charge_item_id": None,
        "submitted_cdm_number": cdm_number,
        "encounter_id": encounter_id,
        "payer_code": payer_code,
        "service_datetime": fmt_iso(service_datetime),
        "quantity": quantity,
        "posted_charge_cents": posted,
        "expected_charge_cents": None,
        "match_status": "UNRECONCILED",
        "line_variance_bp": None,
        "_service_datetime": service_datetime,
    }
    STORE.stamp_new(line, versioned=False)
    STORE.captured_charges[line["id"]] = line
    recompute_batch_counters(batch, bump=True)
    return ok(serialize(line), 201)


@bp.route("/chargemaster/charge-capture-batches/<batch_id>/reconcile", methods=["POST"])
def reconcile_batch(batch_id):
    require(RIA)
    batch = find_batch(batch_id)
    if batch["status"] not in ("INGESTED", "DISPUTED"):
        fail(
            "ERR_INVALID_BATCH_STATE",
            "A reconciliation pass is not declared out of %s." % batch["status"],
        )
    if batch["line_count"] < 1:
        fail("ERR_BATCH_HAS_NO_LINES", "An empty batch cannot be reconciled.")

    batch["status"] = "RECONCILING"
    batch["reconcile_pass_count"] = batch["reconcile_pass_count"] + 1
    STORE.touch(batch)

    lines, mean, _total_expected, _total_posted = charge_capture_variance_summary(batch)
    creations, dismissals = missing_charge_detection(batch, lines)
    for finding in dismissals:
        finding["status"] = "DISMISSED"
        finding["disposition_note"] = "COMPANION_PRESENT_ON_REPASS"
        STORE.touch(finding)
    for spec in creations:
        finding = {
            "batch_id": batch["id"],
            "department_id": batch["department_id"],
            "trigger_captured_charge_id": spec["trigger"]["id"],
            "expected_charge_item_id": spec["companion"]["id"],
            "estimated_lost_charge_cents": spec["estimated_lost_charge_cents"],
            "status": "OPEN",
            "disposition_note": None,
            "recovery_captured_charge_id": None,
        }
        STORE.stamp_new(finding)
        STORE.findings[finding["id"]] = finding

    batch["mean_line_variance_bp"] = mean
    recompute_batch_counters(batch, bump=False)
    return ok(serialize(batch))


@bp.route("/chargemaster/charge-capture-batches/<batch_id>/lifecycle", methods=["POST"])
def batch_lifecycle(batch_id):
    user_id, role = require([RIA, DM])
    data = validate.body()
    raw_action = data.get("action")
    if isinstance(raw_action, str) and raw_action in BATCH_ACTIONS:
        if role != BATCH_ACTIONS[raw_action][0]:
            fail(
                "ERR_ROLE_NOT_PERMITTED",
                "Role %s may not perform action %s." % (role, raw_action),
            )
    existing = STORE.batches.get(batch_id)
    if existing is not None and raw_action == "DISPUTE":
        scope_check(user_id, role, existing["department_id"])
    batch = find_batch(batch_id)
    action = validate.req_enum(data, "action", sorted(BATCH_ACTIONS))
    validate.opt_string(data, "note")

    _actor, from_states, to_state = BATCH_ACTIONS[action]
    if batch["status"] not in from_states:
        fail(
            "ERR_INVALID_BATCH_STATE",
            "Action %s is not declared out of %s." % (action, batch["status"]),
        )

    department = STORE.departments.get(batch["department_id"])
    if action == "FINALIZE":
        for line in STORE.captured_charges.values():
            if line["batch_id"] != batch["id"]:
                continue
            if line["match_status"] == "UNRECONCILED":
                fail(
                    "ERR_BATCH_LINES_UNRECONCILED",
                    "A line of this batch is still UNRECONCILED.",
                )
    elif action == "DISPUTE":
        if batch["exception_line_count"] < 1:
            fail("ERR_NOTHING_TO_DISPUTE", "The batch carries no exception lines.")
    elif action == "CLOSE":
        if batch["open_finding_count"] != 0:
            fail("ERR_FINDINGS_OPEN", "The batch still carries OPEN findings.")
        if department is not None and department["capture_hold"]:
            fail("ERR_DEPARTMENT_CAPTURE_HOLD", "The department is on capture hold.")

    batch["status"] = to_state
    STORE.touch(batch)
    if action == "CLOSE" and department is not None:
        recompute_department(department, bump=False)
    return ok(serialize(batch))


@bp.route("/chargemaster/captured-charges", methods=["GET"])
def list_captured_charges():
    require(ALL_ROLES)
    filters = {
        key: validate.query_filter(key)
        for key in ("batch_id", "charge_item_id", "encounter_id", "match_status")
    }

    def keep(row):
        for key, value in filters.items():
            if value is not None and row.get(key) != value:
                return False
        return True

    return list_response(STORE.ordered(STORE.captured_charges, keep), serialize)


@bp.route("/chargemaster/captured-charges/<captured_charge_id>", methods=["GET"])
def read_captured_charge(captured_charge_id):
    require(ALL_ROLES)
    row = find(
        STORE.captured_charges,
        captured_charge_id,
        "ERR_CAPTURE_RESOURCE_NOT_FOUND",
        "CapturedCharge",
    )
    return ok(serialize(row))


@bp.route("/chargemaster/missing-charge-findings", methods=["GET"])
def list_findings():
    require(FINDING_READERS)
    filters = {
        key: validate.query_filter(key)
        for key in (
            "batch_id",
            "department_id",
            "trigger_captured_charge_id",
            "expected_charge_item_id",
            "recovery_captured_charge_id",
            "status",
        )
    }

    def keep(row):
        for key, value in filters.items():
            if value is not None and row.get(key) != value:
                return False
        return True

    return list_response(STORE.ordered(STORE.findings, keep), serialize)


@bp.route("/chargemaster/missing-charge-findings/<finding_id>", methods=["GET"])
def read_finding(finding_id):
    require(FINDING_READERS)
    row = find(
        STORE.findings,
        finding_id,
        "ERR_CAPTURE_RESOURCE_NOT_FOUND",
        "MissingChargeFinding",
    )
    return ok(serialize(row))


@bp.route(
    "/chargemaster/missing-charge-findings/<finding_id>/disposition", methods=["POST"]
)
def disposition_finding(finding_id):
    require(RIA)
    finding = find(
        STORE.findings,
        finding_id,
        "ERR_CAPTURE_RESOURCE_NOT_FOUND",
        "MissingChargeFinding",
    )
    data = validate.body()
    recovery_line = None
    if "recovery_captured_charge_id" in data and isinstance(
        data.get("recovery_captured_charge_id"), str
    ):
        recovery_line = STORE.captured_charges.get(data["recovery_captured_charge_id"])
        if recovery_line is None:
            fail(
                "ERR_REFERENCED_RESOURCE_NOT_FOUND",
                "CapturedCharge %s does not exist." % data["recovery_captured_charge_id"],
            )
    action = validate.req_enum(data, "action", sorted(FINDING_ACTIONS))
    if action == "DISMISS":
        disposition_note = validate.req_string(data, "disposition_note", 1)
    else:
        disposition_note = validate.opt_string(data, "disposition_note")
    if action == "RESOLVE" and recovery_line is None:
        validate.req_id(data, "recovery_captured_charge_id")

    from_states, to_state = FINDING_ACTIONS[action]
    if finding["status"] not in from_states:
        fail(
            "ERR_INVALID_FINDING_STATE",
            "Action %s is not declared out of %s." % (action, finding["status"]),
        )

    batch = STORE.batches.get(finding["batch_id"])
    if action == "RESOLVE":
        if (
            recovery_line["batch_id"] != finding["batch_id"]
            or recovery_line.get("charge_item_id") != finding["expected_charge_item_id"]
        ):
            fail(
                "ERR_RECOVERY_LINE_INVALID",
                "The recovery line does not capture the expected companion item.",
            )
        if batch is not None and batch["status"] == "CLOSED":
            fail("ERR_INVALID_BATCH_STATE", "The owning batch is CLOSED.")
    else:
        if batch is not None and batch["status"] not in (
            "RECONCILING",
            "RECONCILED",
            "DISPUTED",
        ):
            fail(
                "ERR_INVALID_BATCH_STATE",
                "The owning batch is in %s." % batch["status"],
            )

    finding["status"] = to_state
    if disposition_note is not None:
        finding["disposition_note"] = disposition_note
    if action == "RESOLVE":
        finding["recovery_captured_charge_id"] = recovery_line["id"]
    STORE.touch(finding)

    department = STORE.departments.get(finding["department_id"])
    if action in ("CONFIRM", "RESOLVE") and department is not None:
        recompute_department(department, bump=True)
    if action in ("CONFIRM", "DISMISS") and batch is not None:
        recompute_batch_counters(batch, bump=True)
    return ok(serialize(finding))
