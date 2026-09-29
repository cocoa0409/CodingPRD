from flask import Blueprint, request

import auth
import calcs
import services
import store
import validators as v
from auth import ALL_ROLES
from envelope import ok, ok_page
from errors import ApiError
from store import DB

bp = Blueprint("audit_samples", __name__)

OUTCOMES = ("PASS", "FAIL", "NOT_PROVIDED")


@bp.post("/soc/audit-samples")
def draw_sample():
    user_id, _role = auth.authenticate({"Auditor"})
    body = auth.body()
    control = v.fk(body, "control_id", "controls")
    v.req_id(body, "control_id")
    start = v.req_dt(body, "period_start")
    end = v.req_dt(body, "period_end")
    if end <= start:
        raise ApiError("ERR_VALIDATION")
    expected = v.req_int(body, "expected_control_version")

    if expected != control["version"]:
        raise ApiError("ERR_STALE_CONTROL_VERSION")

    engagement = DB["engagements"][control["engagement_id"]]
    services.require_phase(engagement, {"OBSERVATION", "FIELDWORK"})

    if not control["in_scope"] or control["design_status"] == "DESIGN_CARVED_OUT":
        raise ApiError("ERR_CONTROL_OUT_OF_SCOPE")

    obs_start = store.parse_iso(engagement["observation_period_start"])
    obs_end = store.parse_iso(engagement["observation_period_end"])
    if start < obs_start or end > obs_end:
        raise ApiError("ERR_SAMPLE_WINDOW_INVALID")

    for req in services.evidence_of_control(control["id"]):
        if req["status"] not in ("ACCEPTED", "MISSED", "WAIVED"):
            raise ApiError("ERR_EVIDENCE_NOT_SETTLED")

    previous = None
    for sample in services.samples_of_control(control["id"]):
        if sample["status"] != "VOIDED":
            previous = sample
    population, sample_size, allowed, zero_population = calcs.sample_size_determination(
        control, engagement
    )

    row = store.new_row(
        "audit_samples",
        {
            "control_id": control["id"],
            "period_start": store.fmt_iso(start),
            "period_end": store.fmt_iso(end),
            "drawn_by_user_id": user_id,
            "drawn_at": store.now_iso(),
            "population_size_snapshot": population,
            "sample_size": sample_size,
            "allowed_deviations": allowed,
            "items_recorded": 0,
            "items_passed": 0,
            "items_failed": 0,
            "items_not_provided": 0,
            "deviation_rate": 0.0,
            "projected_failures": 0.0,
            "status": "DRAWN",
            "zero_population": zero_population,
            "supersedes_audit_sample_id": previous["id"] if previous else None,
            "voided_at": None,
        },
    )
    row["_items"] = []

    if previous is not None:
        services.void_sample(previous)

    if zero_population:
        row["status"] = "CONCLUDED_CLEAN"
        row["deviation_rate"] = 0.0
        row["projected_failures"] = 0.0
        if control["operating_status"] == "IN_OBSERVATION":
            control["operating_status"] = "TESTED_EFFECTIVE"
        services.refresh_tested_item_count(control)

    control["updated_at"] = store.now_iso()
    control["version"] = control["version"] + 1
    services.refresh_engagement(engagement)
    return ok(store.public(row), 201)


@bp.get("/soc/audit-samples/<audit_sample_id>")
def read_sample(audit_sample_id):
    auth.authenticate(ALL_ROLES)
    row = store.get_or_404("audit_samples", audit_sample_id)
    return ok(store.public(row))


@bp.get("/soc/audit-samples")
def list_samples():
    auth.authenticate(ALL_ROLES)
    limit, offset = auth.pagination()
    items = store.rows("audit_samples")
    for key in ("control_id", "status", "supersedes_audit_sample_id"):
        value = request.args.get(key)
        if value is not None:
            items = [r for r in items if r[key] == value]
    page, total = auth.paginate(items, limit, offset)
    return ok_page([store.public(r) for r in page], limit, offset, total)


@bp.post("/soc/audit-samples/<audit_sample_id>/items")
def record_item(audit_sample_id):
    auth.authenticate({"Auditor"})
    row = store.get_or_404("audit_samples", audit_sample_id)
    body = auth.body()
    outcome = v.req_enum(body, "outcome", OUTCOMES)
    reason = v.opt_str(body, "failure_reason", 1, 2000)

    if row["status"] not in ("DRAWN", "TESTING"):
        raise ApiError("ERR_INVALID_STATE")
    if row["status"] == "DRAWN" and row["sample_size"] < 1:
        raise ApiError("ERR_INVALID_STATE")
    if row["items_recorded"] >= row["sample_size"]:
        raise ApiError("ERR_SAMPLE_FULL")

    ordinal = row["items_recorded"]
    row.setdefault("_items", []).append(
        {"ordinal": ordinal, "outcome": outcome, "failure_reason": reason}
    )
    row["items_recorded"] = row["items_recorded"] + 1
    if outcome == "PASS":
        row["items_passed"] = row["items_passed"] + 1
    else:
        row["items_failed"] = row["items_failed"] + 1
        if outcome == "NOT_PROVIDED":
            row["items_not_provided"] = row["items_not_provided"] + 1
    if row["status"] == "DRAWN":
        row["status"] = "TESTING"
    store.touch(row)

    control = DB["controls"][row["control_id"]]
    services.refresh_tested_item_count(control)
    return ok(store.public(row))


@bp.post("/soc/audit-samples/<audit_sample_id>/conclude")
def conclude(audit_sample_id):
    auth.authenticate({"Auditor"})
    row = store.get_or_404("audit_samples", audit_sample_id)
    if row["status"] != "TESTING":
        raise ApiError("ERR_INVALID_STATE")
    if row["items_recorded"] != row["sample_size"]:
        raise ApiError("ERR_SAMPLE_INCOMPLETE")
    services.conclude_sample(row)
    return ok(store.public(row))


@bp.post("/soc/audit-samples/<audit_sample_id>/void")
def void(audit_sample_id):
    auth.authenticate({"Auditor"})
    row = store.get_or_404("audit_samples", audit_sample_id)
    body = auth.body()
    v.opt_str(body, "reason", 0, 2000)
    control = DB["controls"][row["control_id"]]
    engagement = DB["engagements"][control["engagement_id"]]
    if row["status"] not in ("CONCLUDED_CLEAN", "CONCLUDED_EXCEPTIONS"):
        raise ApiError("ERR_INVALID_STATE")
    if engagement["status"] == "ISSUED":
        raise ApiError("ERR_INVALID_STATE")
    services.void_sample(row)
    return ok(store.public(row))
