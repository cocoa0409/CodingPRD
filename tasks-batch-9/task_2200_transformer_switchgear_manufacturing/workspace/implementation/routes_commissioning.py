"""Field commissioning jobs and punch list closure (PRD 3.8)."""
from flask import Blueprint

import calc
import clock
import common
import envelope
import posture
import rbac
import store
import validation
from errors import ApiError
from validation import DATETIME, STRING, f

bp = Blueprint("commissioning", __name__)

SEVERITIES = ["BLOCKING", "MAJOR", "MINOR"]
REMEDIATING = ("PUNCH_OPEN", "DEMOBILIZED_INCOMPLETE")


def _refresh_job(job, order):
    """Recompute the three aggregates and evaluate the compound completion edge."""
    calc.refresh_job_aggregates(job)
    if job.get("status") == "PUNCH_OPEN" and job.get("open_punch_count") == 0 \
            and job.get("blocking_punch_count") == 0 and job.get("energized_at"):
        job["status"] = "COMPLETE"
        job["startup_certificate_issued"] = True
        job["completion_ratio_bp"] = 10000
        store.touch("job", job)
        store.touch("order", order)
        common.auto_close_order(order)
    else:
        store.touch("job", job)
    posture.refresh(order)
    return job


def _check_job_remediating(job):
    if job.get("status") not in REMEDIATING:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "the commissioning job is %s" % job.get("status"))


def _issued_label(order):
    for lab in store.where("label", engineered_order_id=order["id"]):
        if lab.get("status") == "ISSUED":
            return lab
    return None


# --------------------------------------------------------------------------- #
# commissioning jobs
# --------------------------------------------------------------------------- #

@bp.route("/engineered-orders/<oid>/commissioning-jobs", methods=["POST"])
def create_job(oid):
    rbac.authenticate("POST /engineered-orders/{id}/commissioning-jobs")
    order = common.resolve("order", oid)
    payload = validation.body()
    release = common.resolve_body_ref("release", payload, "shipment_release_id")
    data = validation.validate(payload, [
        f("shipment_release_id", STRING, required=True),
        f("mobilization_at", DATETIME, required=True),
        f("lead_field_user_id", STRING, required=True),
    ])
    common.check_order_not_cancelled(order)
    job = {
        "engineered_order_id": oid,
        "shipment_release_id": release["id"],
        "status": "SCHEDULED",
        "mobilization_at": data["mobilization_at"],
        "energized_at": None,
        "lead_field_user_id": data["lead_field_user_id"],
        "open_punch_count": 0,
        "blocking_punch_count": 0,
        "completion_ratio_bp": 10000,
        "demobilization_round": 0,
        "startup_certificate_issued": False,
    }
    store.insert("job", job)
    posture.refresh(order)
    return envelope.created(store.public(job))


@bp.route("/commissioning-jobs", methods=["GET"])
def list_jobs():
    rbac.authenticate("GET /commissioning-jobs")
    limit, offset = envelope.pagination()
    rows = common.apply_filters(store.all_rows("job"), {
        "engineered_order_id": common.qstr("engineered_order_id"),
        "shipment_release_id": common.qstr("shipment_release_id"),
        "status": common.qstr("status"),
        "startup_certificate_issued": common.qbool("startup_certificate_issued"),
    })
    return envelope.listing(store.public_list(rows), limit, offset)


@bp.route("/commissioning-jobs/<jid>", methods=["GET"])
def get_job(jid):
    rbac.authenticate("GET /commissioning-jobs/{id}")
    return envelope.ok(store.public(common.resolve("job", jid)))


@bp.route("/commissioning-jobs/<jid>/mobilize", methods=["POST"])
def mobilize_job(jid):
    rbac.authenticate("POST /commissioning-jobs/{id}/mobilize")
    job = common.resolve("job", jid)
    order = common.resolve("order", job.get("engineered_order_id"))
    release = common.resolve("release", job.get("shipment_release_id"))
    first_trip = job.get("status") == "SCHEDULED"
    common.check_state("job", job, ("SCHEDULED", "DEMOBILIZED_INCOMPLETE"))
    common.check_order_not_cancelled(order)
    if first_trip:
        common.check_order_fulfillment(order, ("SHIPPING", "COMMISSIONING"))
    posture.check_posture_blocked(order)
    if first_trip:
        if release.get("status") != "DELIVERED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "the stage is %s, not DELIVERED" % release.get("status"))
        planned = clock.sec(clock.parse(job.get("mobilization_at")))
        if planned is not None and clock.sec(clock.now()) < planned:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "the logical clock is before mobilization_at")
    job["status"] = "MOBILIZED"
    store.touch("job", job)
    if order.get("fulfillment_status") == "SHIPPING":
        order["fulfillment_status"] = "COMMISSIONING"
    store.touch("order", order)
    posture.refresh(order)
    return envelope.ok(store.public(job))


@bp.route("/commissioning-jobs/<jid>/request-energization", methods=["POST"])
def request_energization(jid):
    rbac.authenticate("POST /commissioning-jobs/{id}/request-energization")
    job = common.resolve("job", jid)
    order = common.resolve("order", job.get("engineered_order_id"))
    common.check_state("job", job, ("MOBILIZED",))
    common.check_order_not_cancelled(order)
    if _issued_label(order) is None:
        raise ApiError("ERR_LABEL_NOT_ISSUED", "no compliance label on the order is ISSUED")
    calc.refresh_job_aggregates(job)
    if (job.get("blocking_punch_count") or 0) != 0:
        raise ApiError("ERR_BLOCKING_PUNCH_OPEN",
                       "%d blocking punch items are still open" % job["blocking_punch_count"])
    job["status"] = "ENERGIZATION_PENDING"
    store.touch("job", job)
    posture.refresh(order)
    return envelope.ok(store.public(job))


@bp.route("/commissioning-jobs/<jid>/energize", methods=["POST"])
def energize_job(jid):
    rbac.authenticate("POST /commissioning-jobs/{id}/energize")
    job = common.resolve("job", jid)
    order = common.resolve("order", job.get("engineered_order_id"))
    common.check_state("job", job, ("ENERGIZATION_PENDING",))
    common.check_order_not_cancelled(order)
    posture.check_posture_blocked(order)
    calc.refresh_job_aggregates(job)
    if (job.get("blocking_punch_count") or 0) != 0:
        raise ApiError("ERR_BLOCKING_PUNCH_OPEN",
                       "%d blocking punch items are still open" % job["blocking_punch_count"])
    job["status"] = "PUNCH_OPEN"
    job["energized_at"] = clock.now_str()
    # PRD 3.8 pins the completion edge to punch-item state changes: "After every
    # punch item state change the system re-evaluates the job". Energization only
    # "recomputes the completion ratio", so the aggregates are refreshed here and
    # the job is left in PUNCH_OPEN.
    calc.refresh_job_aggregates(job)
    store.touch("job", job)
    posture.refresh(order)
    return envelope.ok(store.public(job))


@bp.route("/commissioning-jobs/<jid>/demobilize", methods=["POST"])
def demobilize_job(jid):
    rbac.authenticate("POST /commissioning-jobs/{id}/demobilize")
    job = common.resolve("job", jid)
    order = common.resolve("order", job.get("engineered_order_id"))
    payload = validation.body()
    validation.validate(payload, [f("reason", STRING)])
    was_punch_open = job.get("status") == "PUNCH_OPEN"
    common.check_state("job", job, ("MOBILIZED", "ENERGIZATION_PENDING", "PUNCH_OPEN"))
    common.check_order_not_cancelled(order)
    calc.refresh_job_aggregates(job)
    if was_punch_open and (job.get("open_punch_count") or 0) < 1:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "demobilizing from PUNCH_OPEN requires at least one open punch item")
    job["status"] = "DEMOBILIZED_INCOMPLETE"
    job["demobilization_round"] = (job.get("demobilization_round") or 0) + 1
    if isinstance(payload.get("reason"), str):
        job["demobilization_reason"] = payload["reason"]
    store.touch("job", job)
    posture.refresh(order)
    return envelope.ok(store.public(job))


@bp.route("/commissioning-jobs/<jid>/cancel", methods=["POST"])
def cancel_job(jid):
    rbac.authenticate("POST /commissioning-jobs/{id}/cancel")
    job = common.resolve("job", jid)
    order = common.resolve("order", job.get("engineered_order_id"))
    payload = validation.body()
    validation.validate(payload, [f("reason", STRING)])
    common.check_state("job", job, ("SCHEDULED", "MOBILIZED", "ENERGIZATION_PENDING",
                                    "PUNCH_OPEN", "DEMOBILIZED_INCOMPLETE"))
    job["status"] = "CANCELLED"
    if isinstance(payload.get("reason"), str):
        job["cancel_reason"] = payload["reason"]
    for item in store.where("punch", commissioning_job_id=jid):
        if item.get("status") in ("OPEN", "ASSIGNED", "RESOLVED"):
            item["status"] = "REJECTED"
            store.touch("punch", item)
    calc.refresh_job_aggregates(job)
    store.touch("job", job)
    posture.refresh(order)
    return envelope.ok(store.public(job))


# --------------------------------------------------------------------------- #
# punch list items
# --------------------------------------------------------------------------- #

@bp.route("/commissioning-jobs/<jid>/punch-list-items", methods=["POST"])
def create_punch(jid):
    rbac.authenticate("POST /commissioning-jobs/{id}/punch-list-items")
    job = common.resolve("job", jid)
    order = common.resolve("order", job.get("engineered_order_id"))
    payload = validation.body()
    data = validation.validate(payload, [
        f("severity", STRING, required=True, enum=SEVERITIES),
        f("description_text", STRING, required=True),
    ])
    if job.get("status") in common.TERMINAL["job"]:
        raise ApiError("ERR_TERMINAL_STATE", "the commissioning job is %s" % job.get("status"))
    common.check_order_not_cancelled(order)
    item = {
        "commissioning_job_id": jid,
        "severity": data["severity"],
        "description_text": data["description_text"],
        "status": "OPEN",
        "assigned_to_user_id": None,
        "resolved_by_user_id": None,
        "closed_by_user_id": None,
        "reject_count": 0,
        "closed_at": None,
    }
    store.insert("punch", item)
    _refresh_job(job, order)
    return envelope.created(store.public(item))


@bp.route("/commissioning-jobs/<jid>/punch-list-items", methods=["GET"])
def list_job_punches(jid):
    rbac.authenticate("GET /commissioning-jobs/{id}/punch-list-items")
    common.resolve("job", jid)
    limit, offset = envelope.pagination()
    rows = common.apply_filters(store.where("punch", commissioning_job_id=jid), {
        "status": common.qstr("status"),
        "severity": common.qstr("severity"),
    })
    return envelope.listing(store.public_list(rows), limit, offset)


@bp.route("/punch-list-items/<pid>", methods=["GET"])
def get_punch(pid):
    rbac.authenticate("GET /punch-list-items/{id}")
    return envelope.ok(store.public(common.resolve("punch", pid)))


@bp.route("/punch-list-items/<pid>/assign", methods=["POST"])
def assign_punch(pid):
    rbac.authenticate("POST /punch-list-items/{id}/assign")
    item = common.resolve("punch", pid)
    job = common.resolve("job", item.get("commissioning_job_id"))
    order = common.resolve("order", job.get("engineered_order_id"))
    payload = validation.body()
    data = validation.validate(payload, [f("assigned_to_user_id", STRING, required=True)])
    common.check_state("punch", item, ("OPEN",))
    common.check_order_not_cancelled(order)
    _check_job_remediating(job)
    item["status"] = "ASSIGNED"
    item["assigned_to_user_id"] = data["assigned_to_user_id"]
    store.touch("punch", item)
    _refresh_job(job, order)
    return envelope.ok(store.public(item))


@bp.route("/punch-list-items/<pid>/resolve", methods=["POST"])
def resolve_punch(pid):
    rbac.authenticate("POST /punch-list-items/{id}/resolve")
    item = common.resolve("punch", pid)
    job = common.resolve("job", item.get("commissioning_job_id"))
    order = common.resolve("order", job.get("engineered_order_id"))
    payload = validation.body()
    data = validation.validate(payload, [f("resolved_by_user_id", STRING, required=True)])
    common.check_state("punch", item, ("ASSIGNED",))
    common.check_order_not_cancelled(order)
    item["status"] = "RESOLVED"
    item["resolved_by_user_id"] = data["resolved_by_user_id"]
    store.touch("punch", item)
    _refresh_job(job, order)
    return envelope.ok(store.public(item))


@bp.route("/punch-list-items/<pid>/close", methods=["POST"])
def close_punch(pid):
    actor = rbac.authenticate("POST /punch-list-items/{id}/close")
    item = common.resolve("punch", pid)
    job = common.resolve("job", item.get("commissioning_job_id"))
    order = common.resolve("order", job.get("engineered_order_id"))
    rbac.check_sod(actor, item.get("resolved_by_user_id"))
    payload = validation.body()
    data = validation.validate(payload, [f("closed_by_user_id", STRING, required=True)])
    if data["closed_by_user_id"] == item.get("resolved_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "closed_by_user_id must differ from resolved_by_user_id")
    common.check_state("punch", item, ("RESOLVED",))
    common.check_order_not_cancelled(order)
    _check_job_remediating(job)
    item["status"] = "CLOSED"
    item["closed_by_user_id"] = data["closed_by_user_id"]
    item["closed_at"] = clock.now_str()
    store.touch("punch", item)
    _refresh_job(job, order)
    return envelope.ok(store.public(item))


@bp.route("/punch-list-items/<pid>/reject", methods=["POST"])
def reject_punch(pid):
    actor = rbac.authenticate("POST /punch-list-items/{id}/reject")
    item = common.resolve("punch", pid)
    job = common.resolve("job", item.get("commissioning_job_id"))
    order = common.resolve("order", job.get("engineered_order_id"))
    rbac.check_sod(actor, item.get("resolved_by_user_id"))
    payload = validation.body()
    validation.validate(payload, [f("reason", STRING)])
    common.check_state("punch", item, ("RESOLVED",))
    common.check_order_not_cancelled(order)
    _check_job_remediating(job)
    item["status"] = "OPEN"
    item["reject_count"] = (item.get("reject_count") or 0) + 1
    item["assigned_to_user_id"] = None
    item["resolved_by_user_id"] = None
    if isinstance(payload.get("reason"), str):
        item["reject_reason"] = payload["reason"]
    store.touch("punch", item)
    _refresh_job(job, order)
    return envelope.ok(store.public(item))
