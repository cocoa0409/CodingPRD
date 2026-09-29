"""Publication notices: the insertion order, the invoice and certification."""
from flask import Blueprint

import calc
import domain
from core import (ROLE_CITY_CLERK, ROLE_DEPUTY_CLERK, STAFF_ROLES, ApiError,
                  authorize, body_dict, db, fetch, invalid, listing, now_date,
                  ok, parse_date, q, req_bool, req_date, req_decimal, req_list,
                  req_str, touch)

bp = Blueprint("notices", __name__)


@bp.route("/clerk/publication-notices/<notice_id>", methods=["GET"])
def get_notice(notice_id):
    authorize(STAFF_ROLES)
    return ok(fetch(db.notices, notice_id, "ERR_NOTICE_NOT_FOUND"))


@bp.route("/clerk/publication-notices", methods=["GET"])
def list_notices():
    authorize(STAFF_ROLES)
    return listing(list(db.notices.values()), {
        "instrument_id": q("instrument_id"),
        "meeting_id": q("meeting_id"),
        "status": q("status"),
    })


@bp.route("/clerk/publication-notices/<notice_id>/order", methods=["POST"])
def order_notice(notice_id):
    authorize((ROLE_CITY_CLERK, ROLE_DEPUTY_CLERK))
    notice = fetch(db.notices, notice_id, "ERR_NOTICE_NOT_FOUND")
    body = body_dict()
    newspaper = req_str(body, "newspaper_name")
    column_inches = req_decimal(body, "column_inches", minimum_exclusive=0)
    raw_dates = req_list(body, "publication_dates")
    affidavit = req_bool(body, "affidavit_required")
    dates = [parse_date(value) for value in raw_dates]
    if notice["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_NOTICE_STATE", 409)
    if len(dates) != notice["required_publication_count"]:
        raise ApiError("ERR_PUBLICATION_COUNT_MISMATCH", 409)
    deadline = notice["publication_deadline_on"]
    if deadline is not None and max(dates) > deadline:
        raise ApiError("ERR_PUBLICATION_DEADLINE_MISSED", 409)
    for earlier, later in zip(dates, dates[1:]):
        if (later - earlier).days < calc.PUBLICATION_MIN_GAP_DAYS:
            raise ApiError("ERR_PUBLICATION_INTERVAL_TOO_SHORT", 409)
    gross, pct, total = calc.publication_invoice_total(
        column_inches, len(dates), affidavit)
    notice["status"] = "ORDERED"
    notice["newspaper_name"] = newspaper
    notice["column_inches"] = column_inches
    notice["publication_dates"] = dates
    notice["gross_cost_cents"] = gross
    notice["discount_pct"] = pct
    notice["invoice_total_cents"] = total
    touch(notice)
    return ok(notice)


@bp.route("/clerk/publication-notices/<notice_id>/certify-publication",
          methods=["POST"])
def certify_publication(notice_id):
    authorize((ROLE_CITY_CLERK,))
    notice = fetch(db.notices, notice_id, "ERR_NOTICE_NOT_FOUND")
    body = body_dict()
    completed_on = req_date(body, "publication_completed_on")
    if notice["status"] != "ORDERED":
        raise ApiError("ERR_INVALID_NOTICE_STATE", 409)
    dates = notice["publication_dates"] or []
    if not dates or completed_on != max(dates):
        raise invalid("publication_completed_on must equal the latest ordered "
                      "publication date.")
    instrument = db.instruments.get(notice["instrument_id"])
    cycle = None
    if instrument is not None and instrument.get("ordinance_category") == "CODE_AMENDMENT":
        # raised before anything commits: a failed enrolment fails the whole request
        cycle = domain.select_cascade_cycle(instrument)

    # hop 1
    notice["status"] = "PUBLISHED"
    notice["publication_completed_on"] = completed_on
    touch(notice)
    if instrument is None:
        return ok(notice)

    # hop 2
    instrument["publication_completed_on"] = completed_on
    domain.apply_effective_date(instrument)
    if instrument["status"] in ("ADOPTED", "VETO_OVERRIDDEN"):
        instrument["status"] = "PUBLISHED"
    if instrument.get("ordinance_category") != "CODE_AMENDMENT":
        effective = instrument["effective_date"]
        if (instrument["status"] == "PUBLISHED" and effective is not None
                and effective <= now_date()):
            instrument["status"] = "EFFECTIVE"
    touch(instrument)

    # hops 3 and 4
    if cycle is not None:
        domain.new_submission(cycle, instrument, instrument["code_section_ref"],
                              "AMEND", "CASCADE")
    return ok(notice)
