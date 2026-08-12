"""RegulatorySubmission bundle lifecycle (PRD 3.6)."""
from flask import Blueprint

from authz import COMPLIANCE_REVIEWER, READ_ROLES, STATE_REGULATOR, require_roles
from db import store
from errors import (
    bundle_item_mismatch, invalid_request, record_not_found,
    release_event_not_found, order_not_found, stale_version, submission_not_draft,
    submission_not_found, submission_not_rejected, submission_not_submitted,
)
from respond import success
from routes.facilities import get_facility_or_404
from serialize import ser_submission
from store_ops import (
    check_closed, get_or_404, json_body, new_common_fields, new_id, opt_str,
    opt_version, paginate, qparam, req_enum, req_list, req_period, req_str,
    sorted_by_creation, touch,
)
from timeutil import parse_period, period_due_ts

bp = Blueprint("submissions", __name__)

SUBMISSION_TYPES = ["MONTHLY_RELEASE_DETECTION", "TEST_REPORT", "RELEASE_NOTIFICATION"]


def get_submission_or_404(sub_id):
    return get_or_404(store.submissions, sub_id, submission_not_found)


def _validate_bundle(facility_id, submission_type, period_month,
                     record_ids, order_ids, release_event_id):
    """Priority 17 (with priority-4 FK existence inside): the type-specific
    bundle must be present, and every item must belong to the facility and
    satisfy the type's state/period rules."""
    if submission_type == "MONTHLY_RELEASE_DETECTION":
        if period_month is None or not record_ids:
            raise bundle_item_mismatch("MONTHLY_RELEASE_DETECTION requires period_month and release_detection_record_ids")
        for rid in record_ids:
            rec = store.release_detection_records.get(rid)
            if rec is None:
                raise record_not_found()
            tank = store.tank_systems.get(rec["tank_system_id"])
            if tank is None or tank["facility_id"] != facility_id:
                raise bundle_item_mismatch("Bundled record does not belong to the facility")
            if rec["period_month"] != period_month:
                raise bundle_item_mismatch("Bundled record period_month does not match the filing")
    elif submission_type == "TEST_REPORT":
        if not order_ids:
            raise bundle_item_mismatch("TEST_REPORT requires service_order_ids")
        for oid in order_ids:
            o = store.service_orders.get(oid)
            if o is None:
                raise order_not_found()
            if o["facility_id"] != facility_id or o["status"] != "CERTIFIED":
                raise bundle_item_mismatch("Bundled orders must be CERTIFIED and belong to the facility")
    else:  # RELEASE_NOTIFICATION
        if release_event_id is None:
            raise bundle_item_mismatch("RELEASE_NOTIFICATION requires release_event_id")
        rel = store.release_events.get(release_event_id)
        if rel is None:
            raise release_event_not_found()
        if rel["facility_id"] != facility_id:
            raise bundle_item_mismatch("Bundled release event does not belong to the facility")


def _bundle_inputs(data):
    period_month = None
    if "period_month" in data and data["period_month"] is not None:
        period_month = req_period(data, "period_month")  # bad format -> ERR_INVALID_REQUEST
    record_ids = None
    if "release_detection_record_ids" in data and data["release_detection_record_ids"] is not None:
        record_ids = req_list(data, "release_detection_record_ids")
        for rid in record_ids:
            if not isinstance(rid, str):
                raise invalid_request("release_detection_record_ids must be an array of ids")
    order_ids = None
    if "service_order_ids" in data and data["service_order_ids"] is not None:
        order_ids = req_list(data, "service_order_ids")
        for oid in order_ids:
            if not isinstance(oid, str):
                raise invalid_request("service_order_ids must be an array of ids")
    release_event_id = opt_str(data, "release_event_id")
    return period_month, record_ids, order_ids, release_event_id


@bp.route("/submissions", methods=["POST"])
def create_submission():
    require_roles([COMPLIANCE_REVIEWER])
    data = json_body()
    check_closed(data, {"facility_id", "submission_type", "period_month",
                        "release_detection_record_ids", "service_order_ids",
                        "release_event_id"})
    facility_id = req_str(data, "facility_id")
    submission_type = req_enum(data, "submission_type", SUBMISSION_TYPES)
    period_month, record_ids, order_ids, release_event_id = _bundle_inputs(data)

    get_facility_or_404(facility_id)
    _validate_bundle(facility_id, submission_type, period_month, record_ids,
                     order_ids, release_event_id)

    s = {
        "id": new_id(),
        "_seq": next(store.seq),
        "facility_id": facility_id,
        "submission_type": submission_type,
        "period_month": period_month if submission_type == "MONTHLY_RELEASE_DETECTION" else None,
        "release_detection_record_ids": record_ids if submission_type == "MONTHLY_RELEASE_DETECTION" else [],
        "service_order_ids": order_ids if submission_type == "TEST_REPORT" else [],
        "release_event_id": release_event_id if submission_type == "RELEASE_NOTIFICATION" else None,
        "submitted_at": None,
        "is_late": False,
        "state_reviewer_note": None,
        "status": "DRAFT",
    }
    s.update(new_common_fields())
    store.submissions[s["id"]] = s
    return success(ser_submission(s), status=201)


@bp.route("/submissions", methods=["GET"])
def list_submissions():
    require_roles(READ_ROLES)
    items = store.submissions.values()
    for f in ("facility_id", "submission_type", "release_event_id", "status"):
        v = qparam(f)
        if v is not None:
            items = [s for s in items if s[f] == v]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_submission(s) for s in page], response_type="array",
                   pagination=pagination)


@bp.route("/submissions/<sub_id>", methods=["GET"])
def get_submission(sub_id):
    require_roles(READ_ROLES)
    return success(ser_submission(get_submission_or_404(sub_id)))


def _transition_bundled_records(s, to_status):
    for rid in s["release_detection_record_ids"]:
        rec = store.release_detection_records.get(rid)
        if rec is not None and rec["status"] != to_status:
            rec["status"] = to_status
            touch(rec)


@bp.route("/submissions/<sub_id>/submit", methods=["POST"])
def submit_submission(sub_id):
    require_roles([COMPLIANCE_REVIEWER])
    json_body()
    s = get_submission_or_404(sub_id)
    if s["status"] != "DRAFT":
        raise submission_not_draft()
    s["submitted_at"] = store.clock
    if s["submission_type"] == "MONTHLY_RELEASE_DETECTION":
        y, m = parse_period(s["period_month"])
        s["is_late"] = s["submitted_at"] > period_due_ts(y, m)
    else:
        s["is_late"] = False
    s["status"] = "SUBMITTED"
    touch(s)
    _transition_bundled_records(s, "SUBMITTED")
    return success(ser_submission(s))


@bp.route("/submissions/<sub_id>/accept", methods=["POST"])
def accept_submission(sub_id):
    require_roles([STATE_REGULATOR])
    json_body()
    s = get_submission_or_404(sub_id)
    if s["status"] != "SUBMITTED":
        raise submission_not_submitted()
    s["status"] = "ACCEPTED"
    touch(s)
    _transition_bundled_records(s, "ACCEPTED")
    return success(ser_submission(s))


@bp.route("/submissions/<sub_id>/reject", methods=["POST"])
def reject_submission(sub_id):
    require_roles([STATE_REGULATOR])
    data = json_body()
    check_closed(data, {"note"})
    note = req_str(data, "note")
    s = get_submission_or_404(sub_id)
    if s["status"] != "SUBMITTED":
        raise submission_not_submitted()
    s["state_reviewer_note"] = note
    s["status"] = "REJECTED"
    touch(s)
    _transition_bundled_records(s, "RECORDED")  # compensation
    return success(ser_submission(s))


@bp.route("/submissions/<sub_id>/amend", methods=["POST"])
def amend_submission(sub_id):
    require_roles([COMPLIANCE_REVIEWER])
    data = json_body()
    check_closed(data, {"expected_submission_version", "period_month",
                        "release_detection_record_ids", "service_order_ids",
                        "release_event_id"})
    expected = opt_version(data, "expected_submission_version")
    s = get_submission_or_404(sub_id)
    # Priority 5 (state) precedes priority 19 (OCC).
    if s["status"] != "REJECTED":
        raise submission_not_rejected()

    # Replacement bundle fields (provided fields only); only the fields that
    # make up the submission's type-specific bundle are considered, matching
    # creation semantics.
    new_period, new_records, new_orders, new_release = (None, None, None, None)
    if "period_month" in data:
        new_period = req_period(data, "period_month") if data["period_month"] is not None else None
    if "release_detection_record_ids" in data:
        v = data["release_detection_record_ids"]
        new_records = None if v is None else req_list(data, "release_detection_record_ids")
        if new_records is not None:
            for rid in new_records:
                if not isinstance(rid, str):
                    raise invalid_request("release_detection_record_ids must be an array of ids")
    if "service_order_ids" in data:
        v = data["service_order_ids"]
        new_orders = None if v is None else req_list(data, "service_order_ids")
        if new_orders is not None:
            for oid in new_orders:
                if not isinstance(oid, str):
                    raise invalid_request("service_order_ids must be an array of ids")
    if "release_event_id" in data:
        new_release = opt_str(data, "release_event_id")

    if s["submission_type"] == "MONTHLY_RELEASE_DETECTION":
        merged_period = new_period if "period_month" in data else s["period_month"]
        merged_records = new_records if "release_detection_record_ids" in data else s["release_detection_record_ids"]
        merged_orders, merged_release = [], None
    elif s["submission_type"] == "TEST_REPORT":
        merged_orders = new_orders if "service_order_ids" in data else s["service_order_ids"]
        merged_period, merged_records, merged_release = None, [], None
    else:  # RELEASE_NOTIFICATION
        merged_release = new_release if "release_event_id" in data else s["release_event_id"]
        merged_period, merged_records, merged_orders = None, [], []

    # Priority 17: provided bundle fields re-validated under creation rules.
    _validate_bundle(s["facility_id"], s["submission_type"], merged_period,
                     merged_records, merged_orders, merged_release)
    # Priority 19: optimistic concurrency.
    if expected != s["version"]:
        raise stale_version()

    s["period_month"] = merged_period
    s["release_detection_record_ids"] = merged_records
    s["service_order_ids"] = merged_orders
    s["release_event_id"] = merged_release
    s["submitted_at"] = None
    s["is_late"] = False
    s["status"] = "DRAFT"
    touch(s)
    return success(ser_submission(s))
