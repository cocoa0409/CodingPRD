"""Mailing lists, recipient records, CASS, dedupe, NCOA moves and returns."""
from flask import Blueprint, request

import calc
import derive
import enums
import envelope
import ladder
import serial
import services
import store
from errors import ApiError
from ladder import Ctx
from model import new_row, touch
from store import db

bp = Blueprint("lists", __name__)

LIST_READ_ROLES = ["PlatformAdmin", "AccountOwner", "ListOperator", "CampaignManager"]
_AXES = ("cass_status", "deliverability_tier", "dedupe_status")


def _snapshot(rows):
    return dict((r["id"], tuple(r[a] for a in _AXES)) for r in rows)


def _touch_changed(rows, before):
    for r in rows:
        if before.get(r["id"]) != tuple(r[a] for a in _AXES):
            touch(r)


@bp.route("/mail/mailing-lists", methods=["POST"])
def create_mailing_list():
    ctx = Ctx(["PlatformAdmin", "AccountOwner", "ListOperator"])
    ctx.fk("account", "account_id")
    ctx.scope(lambda: ctx.get("account")["id"] if ctx.get("account") else None)
    ctx.fields(required=[("account_id", "str"), ("name", "str")])
    ctx.run()
    row = new_row({
        "account_id": ctx.body["account_id"],
        "name": ctx.body["name"],
        "import_status": "UPLOADED",
        "dedupe_mode": None,
    })
    db.mailing_lists[row["id"]] = row
    return envelope.object_response(serial.mailing_list(row), 201)


@bp.route("/mail/mailing-lists/<mailing_list_id>", methods=["GET"])
def get_mailing_list(mailing_list_id):
    ctx = Ctx(LIST_READ_ROLES)
    ctx.path("mailing_list", mailing_list_id)
    ctx.scope(lambda: ctx.get("mailing_list")["account_id"])
    ctx.run()
    return envelope.object_response(serial.mailing_list(ctx.get("mailing_list")), 200)


@bp.route("/mail/mailing-lists", methods=["GET"])
def list_mailing_lists():
    ctx = Ctx(LIST_READ_ROLES)
    ctx.run()
    rows = list(db.mailing_lists.values())
    account_id = request.args.get("account_id")
    if account_id is not None:
        rows = [r for r in rows if r["account_id"] == account_id]
    import_status = request.args.get("import_status")
    if import_status is not None:
        rows = [r for r in rows if r["import_status"] == import_status]
    rows = envelope.sort_rows(rows)
    page, limit, offset, total = envelope.paginate(rows, request.args)
    return envelope.list_response([serial.mailing_list(r) for r in page], limit, offset, total)


def _not_locked(lst):
    if lst["import_status"] == "LOCKED":
        raise ApiError("ERR_LIST_LOCKED")


def _list_state(lst, allowed):
    if lst["import_status"] not in allowed:
        raise ApiError("ERR_LIST_INVALID_STATE")


@bp.route("/mail/mailing-lists/<mailing_list_id>/records", methods=["POST"])
def add_record(mailing_list_id):
    ctx = Ctx(["PlatformAdmin", "ListOperator"])
    ctx.path("mailing_list", mailing_list_id)
    ctx.fields(required=[("first_name", "str"), ("last_name", "str"),
                         ("address_line1", "str"), ("city", "str"),
                         ("state_code", "str"), ("zip5", "str")],
               optional=[("address_line2", "str"), ("country_code", "str"),
                         ("dpv_confirmation_code", "str")])
    ctx.enums([("dpv_confirmation_code", enums.DPV_CODES)])
    ctx.at(12, lambda: _not_locked(ctx.get("mailing_list")))
    ctx.at(16, lambda: _list_state(ctx.get("mailing_list"), ("UPLOADED",)))
    ctx.run()
    lst = ctx.get("mailing_list")
    existing = derive.list_records_of(lst["id"])
    row = new_row({
        "mailing_list_id": lst["id"],
        "first_name": ctx.body["first_name"],
        "last_name": ctx.body["last_name"],
        "address_line1": ctx.body["address_line1"],
        "address_line2": ctx.body.get("address_line2"),
        "city": ctx.body["city"],
        "state_code": ctx.body["state_code"],
        "zip5": ctx.body["zip5"],
        "country_code": ctx.body.get("country_code") or store.DOMESTIC_COUNTRY_CODE,
        "dpv_confirmation_code": ctx.body.get("dpv_confirmation_code") or "U",
        "cass_status": "PENDING",
        "deliverability_tier": "UNASSIGNED",
        "dedupe_status": "UNSCREENED",
        "mail_status": "NOT_MAILED",
        "move_status": "NONE",
        "exact_key": "",
        "household_key": "",
        "last_mail_job_id": None,
        "insertion_seq": len(existing) + 1,
    })
    row["exact_key"], row["household_key"] = derive.record_keys(row)
    db.list_records[row["id"]] = row
    touch(lst)
    return envelope.object_response(serial.list_record(row), 201)


@bp.route("/mail/mailing-lists/<mailing_list_id>/cass-runs", methods=["POST"])
def cass_run(mailing_list_id):
    ctx = Ctx(["PlatformAdmin", "ListOperator"])
    ctx.path("mailing_list", mailing_list_id)
    ctx.at(12, lambda: _not_locked(ctx.get("mailing_list")))
    ctx.at(16, lambda: _cass_precondition(ctx.get("mailing_list")))
    ctx.run()
    lst = ctx.get("mailing_list")
    rows = derive.list_records_of(lst["id"])
    before = _snapshot(rows)
    for record in rows:
        calc.apply_cass_to_record(record)
        record["dedupe_status"] = "UNSCREENED"
    _touch_changed(rows, before)
    lst["dedupe_mode"] = None
    lst["import_status"] = "CASS_RUN"
    touch(lst)
    return envelope.object_response(serial.mailing_list(lst), 200)


def _cass_precondition(lst):
    _list_state(lst, ("UPLOADED", "CASS_RUN", "DEDUPED"))
    if len(derive.list_records_of(lst["id"])) < 1:
        raise ApiError("ERR_LIST_INVALID_STATE", "The list holds no records.")


@bp.route("/mail/mailing-lists/<mailing_list_id>/dedupe-runs", methods=["POST"])
def dedupe_run(mailing_list_id):
    ctx = Ctx(["PlatformAdmin", "ListOperator"])
    ctx.path("mailing_list", mailing_list_id)
    ctx.fields(required=[("mode", "str")])
    ctx.enums([("mode", enums.DEDUPE_MODES)])
    ctx.at(12, lambda: _not_locked(ctx.get("mailing_list")))
    ctx.at(16, lambda: _list_state(ctx.get("mailing_list"), ("CASS_RUN", "DEDUPED")))
    ctx.run()
    lst = ctx.get("mailing_list")
    rows = derive.list_records_of(lst["id"])
    before = _snapshot(rows)
    calc.dedupe_screen(lst["id"], ctx.body["mode"])
    _touch_changed(rows, before)
    lst["dedupe_mode"] = ctx.body["mode"]
    lst["import_status"] = "DEDUPED"
    touch(lst)
    return envelope.object_response(serial.mailing_list(lst), 200)


@bp.route("/mail/mailing-lists/<mailing_list_id>/lock", methods=["POST"])
def lock_list(mailing_list_id):
    ctx = Ctx(["PlatformAdmin", "ListOperator"])
    ctx.path("mailing_list", mailing_list_id)
    ctx.at(12, lambda: _not_locked(ctx.get("mailing_list")))
    ctx.at(16, lambda: _lock_precondition(ctx.get("mailing_list")))
    ctx.run()
    lst = ctx.get("mailing_list")
    lst["import_status"] = "LOCKED"
    touch(lst)
    return envelope.object_response(serial.mailing_list(lst), 200)


def _lock_precondition(lst):
    _list_state(lst, ("DEDUPED",))
    if derive.list_counts(lst["id"])["mailable_count"] < 1:
        raise ApiError("ERR_LIST_INVALID_STATE", "The list holds no mailable records.")


# ----------------------------------------------------------- list records
@bp.route("/mail/list-records/<list_record_id>", methods=["GET"])
def get_list_record(list_record_id):
    ctx = Ctx(LIST_READ_ROLES)
    ctx.path("list_record", list_record_id)
    ctx.scope(lambda: ladder.account_of_record(ctx.get("list_record")))
    ctx.run()
    return envelope.object_response(serial.list_record(ctx.get("list_record")), 200)


@bp.route("/mail/list-records", methods=["GET"])
def list_list_records():
    ctx = Ctx(LIST_READ_ROLES)
    ctx.run()
    rows = list(db.list_records.values())
    for field in ("mailing_list_id", "last_mail_job_id", "cass_status", "dedupe_status",
                  "mail_status", "move_status"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    rows = envelope.sort_rows(rows)
    page, limit, offset, total = envelope.paginate(rows, request.args)
    return envelope.list_response([serial.list_record(r) for r in page], limit, offset, total)


def _reject_eddm(job):
    if job is not None and job["job_kind"] == "EDDM":
        raise ApiError("ERR_EDDM_NOT_APPLICABLE")


@bp.route("/mail/list-records/<list_record_id>/ncoa-moves", methods=["POST"])
def ncoa_move(list_record_id):
    ctx = Ctx(["PlatformAdmin", "ListOperator"])
    ctx.path("list_record", list_record_id)
    ctx.fields(required=[("new_address_line1", "str?")],
               optional=[("new_city", "str"), ("new_state_code", "str"),
                         ("new_zip5", "str"), ("new_dpv_confirmation_code", "str")])
    ctx.enums([("new_dpv_confirmation_code", enums.DPV_CODES)])
    ctx.gate(lambda: ladder.campaign_of_record(ctx.get("list_record")))
    ctx.at(12, lambda: _not_locked(db.mailing_lists[ctx.get("list_record")["mailing_list_id"]]))
    ctx.at(13, lambda: _reject_eddm(ladder.job_of_record(ctx.get("list_record"))))
    ctx.run()
    record = ctx.get("list_record")
    if ctx.body.get("new_address_line1") is not None:
        record["move_status"] = "MOVE_APPLIED"
        record["address_line1"] = ctx.body["new_address_line1"]
        for src, dst in (("new_city", "city"), ("new_state_code", "state_code"),
                         ("new_zip5", "zip5")):
            if ctx.body.get(src) is not None:
                record[dst] = ctx.body[src]
        if ctx.body.get("new_dpv_confirmation_code") is not None:
            record["dpv_confirmation_code"] = ctx.body["new_dpv_confirmation_code"]
    else:
        record["move_status"] = "MOVE_NO_FORWARD"
        record["dpv_confirmation_code"] = "N"
    calc.apply_cass_to_record(record)
    record["exact_key"], record["household_key"] = derive.record_keys(record)
    touch(record)
    return envelope.object_response(serial.list_record(record), 200)


@bp.route("/mail/list-records/<list_record_id>/returns", methods=["POST"])
def record_return(list_record_id):
    ctx = Ctx(["PlatformAdmin", "ListOperator"])
    ctx.path("list_record", list_record_id)
    ctx.fields(required=[("return_reason", "str")])
    ctx.enums([("return_reason", enums.RETURN_REASONS)])
    ctx.gate(lambda: ladder.campaign_of_record(ctx.get("list_record")))
    ctx.at(13, lambda: _reject_eddm(ladder.job_of_record(ctx.get("list_record"))))
    ctx.at(20, lambda: _returnable(ctx.get("list_record")))
    ctx.run()
    record = ctx.get("list_record")
    job = db.mail_jobs[record["last_mail_job_id"]]
    campaign = db.campaigns.get(job["campaign_id"])
    # CASCADE B hop 1
    record["mail_status"] = "RETURNED"
    touch(record)
    # CASCADE B hop 2
    entitlement, fee = calc.return_settlement(record, job)
    event = new_row({
        "list_record_id": record["id"],
        "mail_job_id": job["id"],
        "return_reason": ctx.body["return_reason"],
        "entitlement": entitlement,
        "return_fee_cents": fee,
    }, common=False)
    db.return_events[event["id"]] = event
    # CASCADE B hop 3 — a zero class fee writes no FORFEIT row at all.
    # Adjudication of friction 8: a FORFEIT that would drive
    # permit_balance_cents below zero is ALLOWED.  No rung guards the forfeit
    # path (rung 41 is scoped to commitment), so refusing it would require an
    # error the catalogue does not contain and would make the REFUND-entitled
    # return branch unreachable on a thin escrow.
    if entitlement == "REFUND" and fee > 0 and campaign is not None:
        services.append_ledger(campaign["account_id"], "FORFEIT", fee,
                               "return-to-sender fee",
                               campaign_id=campaign["id"], mail_job_id=job["id"])
    # CASCADE B hop 4 — job.returned_piece_count and the campaign counters are
    # derived from the ReturnEvent rows, so they refresh with the append.
    return envelope.object_response(serial.return_event(event), 201)


def _returnable(record):
    if record["mail_status"] != "MAILED" or not record.get("last_mail_job_id"):
        raise ApiError("ERR_INVALID_STATE", "The record is not currently mailed.")
    job = db.mail_jobs.get(record["last_mail_job_id"])
    if job is None:
        raise ApiError("ERR_INVALID_STATE", "The record has no mailing job.")
