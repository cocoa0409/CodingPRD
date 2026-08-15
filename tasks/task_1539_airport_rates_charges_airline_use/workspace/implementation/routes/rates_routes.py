"""RatesSetting transitions and consultation comments."""
from flask import Blueprint

import errors
import helpers
import services
from db import store
from helpers import (authenticate, get_path, json_body, paginate, resolve_fk,
                     req_string, require_ownership, READ_ROLES)
from response import success_object, success_list
from services import (ser_rates_setting, ser_comment, touch, stamp, now_dt,
                      check_fy_open_guard, derive_rates, rederive_rates_onto,
                      CONSULTATION_MIN_DAYS, COUNTERSIGN_WINDOW_DAYS)
from util import new_id, fmt_iso, days_later

bp = Blueprint("rates_settings", __name__)


def _get_rs(rs_id):
    return get_path(store.rates_settings, rs_id, "RatesSetting")


@bp.get("/airport/rates_settings/<rs_id>")
def get_rates_setting(rs_id):
    authenticate(READ_ROLES)
    rs = _get_rs(rs_id)
    rederive_rates_onto(rs)  # re-derived whenever the schedule is read (§3.2)
    return success_object(ser_rates_setting(rs))


@bp.post("/airport/rates_settings/<rs_id>/publish")
def publish_rates_setting(rs_id):
    authenticate(("AirportFinance",))
    rs = _get_rs(rs_id)
    # priority 6: state
    if rs["status"] != "DRAFT":
        raise errors.invalid_state("Only a DRAFT rate schedule can be published")
    fy = store.fiscal_years[rs["fiscal_year_id"]]
    if fy["status"] == "DRAFT":
        raise errors.invalid_state("The parent fiscal year must be OPEN to publish rates")
    # priority 9
    check_fy_open_guard(fy)
    # priority 14: derivability re-checked at publish
    derived = derive_rates(fy)
    rs.update(derived)
    rs["status"] = "CONSULTATION"
    rs["consultation_comment_count"] = 0
    touch(rs)
    # publish-supersedes: any ADOPTED schedule on the same year -> SUPERSEDED
    for other in store.rates_settings.values():
        if (other["id"] != rs["id"] and other["fiscal_year_id"] == fy["id"]
                and other["status"] == "ADOPTED"):
            other["status"] = "SUPERSEDED"
            touch(other)
    return success_object(ser_rates_setting(rs))


@bp.post("/airport/rates_settings/<rs_id>/adopt")
def adopt_rates_setting(rs_id):
    authenticate(("AirportDirector",))
    rs = _get_rs(rs_id)
    # priority 6: state
    if rs["status"] != "CONSULTATION":
        raise errors.invalid_state("Only a schedule in CONSULTATION can be adopted")
    fy = store.fiscal_years[rs["fiscal_year_id"]]
    # priority 8: minimum consultation window (30 days from schedule creation)
    if now_dt() < days_later(rs["_created_dt"], CONSULTATION_MIN_DAYS):
        raise errors.temporal_violation(
            "Minimum consultation period has not elapsed")
    # priority 9
    check_fy_open_guard(fy)
    rs["status"] = "ADOPTED"
    rs["adopted_at"] = stamp()
    rs["_adopted_dt"] = now_dt()
    touch(rs)
    # cascade: every active agreement gets its countersign deadline stamped
    deadline_iso = fmt_iso(days_later(now_dt(), COUNTERSIGN_WINDOW_DAYS))
    for ag in store.agreements.values():
        if ag["fiscal_year_id"] == fy["id"] and ag["superseded_by_id"] is None:
            ag["countersign_deadline"] = deadline_iso
            touch(ag)
    return success_object(ser_rates_setting(rs))


# ---------------------------------------------------------------------------
# ConsultationComment
# ---------------------------------------------------------------------------
@bp.post("/airport/rates_settings/<rs_id>/comments")
def create_comment(rs_id):
    uid, _ = authenticate(("SignatoryAirline",))
    rs = _get_rs(rs_id)
    body = json_body()
    airline = resolve_fk(body, "airline_id", store.airlines)  # priority 4
    airline_id = req_string(body, "airline_id")               # priority 5
    comment_body = req_string(body, "body")
    require_ownership(uid, airline_id)
    # priority 6: comments are filed during consultation
    if rs["status"] != "CONSULTATION":
        raise errors.invalid_state("Comments may be filed only while the schedule is in CONSULTATION")
    fy = store.fiscal_years[rs["fiscal_year_id"]]
    check_fy_open_guard(fy)  # priority 9
    ts = stamp()
    comment = {
        "id": new_id(),
        "rates_setting_id": rs["id"],
        "airline_id": airline["id"],
        "body": comment_body,
        "submitted_at": ts,
        "created_at": ts,
        "_created_dt": now_dt(),
        "_seq": next(store.seq),
    }
    store.comments[comment["id"]] = comment
    rs["consultation_comment_count"] += 1
    touch(rs)
    return success_object(ser_comment(comment), status=201)


@bp.get("/airport/rates_settings/<rs_id>/comments")
def list_comments(rs_id):
    authenticate(READ_ROLES)
    rs = _get_rs(rs_id)
    items = [c for c in store.comments.values() if c["rates_setting_id"] == rs["id"]]
    data, meta = paginate(items, ser_comment)
    return success_list(data, meta)


@bp.get("/airport/consultation_comments/<comment_id>")
def get_comment(comment_id):
    authenticate(READ_ROLES)
    comment = get_path(store.comments, comment_id, "ConsultationComment")
    return success_object(ser_comment(comment))


@bp.get("/airport/activity_records/<record_id>")
def get_activity_record(record_id):
    authenticate(READ_ROLES)
    record = get_path(store.activity_records, record_id, "ActivityRecord")
    return success_object(services.ser_activity(record))
