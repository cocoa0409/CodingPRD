"""HTTP endpoints. Ordering of checks per request follows PRD 2.9:
auth (401) -> role permission (403) -> existence (404) -> ownership (403) ->
state (409) -> domain business checks. Body well-formedness (400) is enforced
while reading fields.
"""
from datetime import timedelta

from flask import request

from store import db, make_entity, touch, fmt_ts, parse_date, date_to_dt, timezone
import store
import core
from core import (
    ApiError,
    authenticate,
    require_role,
    json_body,
    req_str,
    req_int,
    req_enum,
    opt_str,
    opt_int,
    opt_bool,
    opt_enum,
    opt_list,
    ok,
    ok_list,
    paginate,
    ser,
    ser_account,
)
import domain
from domain import (
    line_count_for,
    estimated_cost,
    find_statutory,
    notice_insertions,
    check_dates_temporal,
    check_capacity,
    edition_occupied,
    create_insertion,
    per_insertion_cost,
    on_publish,
    compute_compliance,
    draft_invoice_of,
    issued_invoice_of,
    issued_affidavit_of,
    account_balances,
)

NOTICE_TYPES = {"FORECLOSURE", "PROBATE", "BID"}
ACCOUNT_TYPES = {"LAW_FIRM", "GOVERNMENT", "INDIVIDUAL"}
ACCOUNT_STATUSES = {"ACTIVE", "SUSPENDED"}
PRICING_BASES = {"PER_LINE", "PER_WORD"}


# --------------------------------------------------------------------------
# resolution / ownership helpers
# --------------------------------------------------------------------------
def _get(coll, rid):
    e = coll.get(rid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", 404, "referenced resource does not exist")
    return e


def _deny():
    raise ApiError("ERR_UNAUTHORIZED", 403, "role does not own the target resource")


def own_account(uid, account_id):
    if account_id != uid:
        _deny()


def own_notice_advertiser(uid, notice):
    if notice["account_id"] != uid:
        _deny()


def own_publisher_insertion(uid, insertion):
    if insertion["newspaper_id"] != uid:
        _deny()


def own_publisher_notice(uid, notice):
    if notice["newspaper_id"] != uid:
        _deny()


def _list_response(items, kind="plain"):
    items = sorted(items, key=lambda e: e["_seq"])
    window, pagination = paginate(items)
    if kind == "account":
        data = [ser_account(i) for i in window]
    else:
        data = [ser(i) for i in window]
    return ok_list(data, pagination)


def _filter_eq(items, field, value):
    if value is None:
        return items
    return [i for i in items if str(i.get(field)) == value]


def register(app):
    # ----------------------------------------------------------------------
    # Logical clock
    # ----------------------------------------------------------------------
    @app.route("/_clock/set_current_utc", methods=["POST"])
    def clock_set():
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin"})
        data = json_body()
        iso = req_str(data, "to_iso8601")
        try:
            db.clock = store.parse_dt(iso)
        except ValueError:
            raise ApiError("ERR_VALIDATION", 400, "to_iso8601 is not a valid ISO 8601 instant")
        return ok({})

    # ----------------------------------------------------------------------
    # Newspapers
    # ----------------------------------------------------------------------
    @app.route("/newspapers", methods=["POST"])
    def newspaper_create():
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin"})
        data = json_body()
        blackout = opt_list(data, "blackout_dates", [])
        paper = make_entity({
            "name": req_str(data, "name"),
            "county": req_str(data, "county"),
            "circulation_qualified": opt_bool(data, "circulation_qualified", True),
            "pricing_basis": req_enum(data, "pricing_basis", PRICING_BASES),
            "chars_per_line": req_int(data, "chars_per_line"),
            "line_rate_first_cents": req_int(data, "line_rate_first_cents"),
            "line_rate_subsequent_cents": req_int(data, "line_rate_subsequent_cents"),
            "word_rate_cents": req_int(data, "word_rate_cents"),
            "affidavit_fee_cents": req_int(data, "affidavit_fee_cents"),
            "edition_line_capacity": req_int(data, "edition_line_capacity"),
            "publication_weekday": req_int(data, "publication_weekday"),
            "blackout_dates": blackout,
        })
        db.newspapers[paper["id"]] = paper
        return ok(ser(paper), 201)

    @app.route("/newspapers/<rid>", methods=["GET"])
    def newspaper_get(rid):
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin", "Advertiser", "Publisher", "ComplianceOfficer"})
        paper = _get(db.newspapers, rid)
        return ok(ser(paper))

    # ----------------------------------------------------------------------
    # Accounts
    # ----------------------------------------------------------------------
    @app.route("/accounts", methods=["POST"])
    def account_create():
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin"})
        data = json_body()
        acct = make_entity({
            "name": req_str(data, "name"),
            "account_type": req_enum(data, "account_type", ACCOUNT_TYPES),
            "credit_limit_cents": opt_int(data, "credit_limit_cents", 0),
            "status": opt_enum(data, "status", ACCOUNT_STATUSES, "ACTIVE"),
        })
        db.accounts[acct["id"]] = acct
        return ok(ser_account(acct), 201)

    @app.route("/accounts/<rid>", methods=["GET"])
    def account_get(rid):
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin", "Advertiser"})
        acct = _get(db.accounts, rid)
        return ok(ser_account(acct))

    # ----------------------------------------------------------------------
    # Statutory requirements
    # ----------------------------------------------------------------------
    @app.route("/statutory-requirements", methods=["POST"])
    def statutory_create():
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin"})
        data = json_body()
        notice_type = req_enum(data, "notice_type", NOTICE_TYPES)
        county = req_str(data, "county")
        min_ins = req_int(data, "min_insertions")
        min_days = req_int(data, "min_days_before_deadline")
        req = make_entity({
            "notice_type": notice_type,
            "county": county,
            "min_insertions": min_ins,
            "min_days_before_deadline": min_days,
        })
        db.statutory[req["id"]] = req
        return ok(ser(req), 201)

    @app.route("/statutory-requirements", methods=["GET"])
    def statutory_list():
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin", "Advertiser", "ComplianceOfficer"})
        items = list(db.statutory.values())
        items = _filter_eq(items, "notice_type", request.args.get("notice_type"))
        items = _filter_eq(items, "county", request.args.get("county"))
        return _list_response(items)

    # ----------------------------------------------------------------------
    # Notices
    # ----------------------------------------------------------------------
    @app.route("/notices", methods=["POST"])
    def notice_create():
        uid, role = authenticate()
        require_role(role, {"Advertiser"})
        data = json_body()
        account_id = req_str(data, "account_id")
        newspaper_id = req_str(data, "newspaper_id")
        notice_type = req_enum(data, "notice_type", NOTICE_TYPES)
        county = req_str(data, "county")
        title = req_str(data, "title")
        body_text = req_str(data, "body_text")
        deadline_date = req_str(data, "deadline_date")
        # ownership: advertiser may only create for its own account
        own_account(uid, account_id)
        # existence
        newspaper = _get(db.newspapers, newspaper_id)
        # statutory rule must exist for (notice_type, county)
        statutory = find_statutory(notice_type, county)
        if statutory is None:
            raise ApiError("ERR_STATUTORY_REQUIREMENT_MISSING", 422,
                           "no statutory requirement matches (notice_type, county)")
        word_count = len(body_text.split())
        line_count = line_count_for(body_text, newspaper)
        notice = make_entity({
            "account_id": account_id,
            "newspaper_id": newspaper_id,
            "notice_type": notice_type,
            "county": county,
            "title": title,
            "body_text": body_text,
            "deadline_date": deadline_date,
            "status": "DRAFT",
            "word_count": word_count,
            "line_count": line_count,
            "required_insertions": statutory["min_insertions"],
            "insertions_published": 0,
            "paid_insertion_count": 0,
            "estimated_cost_cents": 0,
            "final_cost_cents": None,
            "compliance_status": "PENDING",
            "_min_days_before_deadline": statutory["min_days_before_deadline"],
        })
        notice["estimated_cost_cents"] = estimated_cost(newspaper, notice)
        db.notices[notice["id"]] = notice
        return ok(ser(notice), 201)

    @app.route("/notices/<rid>", methods=["GET"])
    def notice_get(rid):
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin", "Advertiser", "Publisher", "ComplianceOfficer"})
        notice = _get(db.notices, rid)
        return ok(ser(notice))

    @app.route("/notices", methods=["GET"])
    def notice_list():
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin", "Advertiser", "Publisher", "ComplianceOfficer"})
        items = list(db.notices.values())
        a = request.args
        items = _filter_eq(items, "account_id", a.get("account_id"))
        items = _filter_eq(items, "newspaper_id", a.get("newspaper_id"))
        items = _filter_eq(items, "notice_type", a.get("notice_type"))
        items = _filter_eq(items, "county", a.get("county"))
        items = _filter_eq(items, "status", a.get("status"))
        items = _filter_eq(items, "compliance_status", a.get("compliance_status"))
        return _list_response(items)

    @app.route("/notices/<rid>/submit", methods=["POST"])
    def notice_submit(rid):
        uid, role = authenticate()
        require_role(role, {"Advertiser"})
        notice = _get(db.notices, rid)
        own_notice_advertiser(uid, notice)
        if notice["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", 409, "notice is not in DRAFT")
        account = db.accounts[notice["account_id"]]
        if account["status"] != "ACTIVE":
            raise ApiError("ERR_ACCOUNT_SUSPENDED", 409, "account is not ACTIVE")
        _outstanding, committed = account_balances(account["id"])
        if committed + notice["estimated_cost_cents"] > account["credit_limit_cents"]:
            raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", 402, "account credit limit would be exceeded")
        notice["status"] = "SUBMITTED"
        touch(notice)
        proof = make_entity({
            "notice_id": notice["id"],
            "status": "PENDING",
            "proof_text": notice["body_text"],
            "reviewer_note": None,
        })
        db.proofs[proof["id"]] = proof
        return ok(ser(notice))

    @app.route("/notices/<rid>/proofs", methods=["GET"])
    def notice_proofs(rid):
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin", "Advertiser", "ComplianceOfficer"})
        notice = _get(db.notices, rid)
        items = [p for p in db.proofs.values() if p["notice_id"] == notice["id"]]
        return _list_response(items)

    @app.route("/notices/<rid>/schedule", methods=["POST"])
    def notice_schedule(rid):
        uid, role = authenticate()
        require_role(role, {"Advertiser"})
        notice = _get(db.notices, rid)
        own_notice_advertiser(uid, notice)
        data = json_body()
        first_publication_date = req_str(data, "first_publication_date")
        expected_version = req_int(data, "expected_notice_version")

        status = notice["status"]
        reschedule = False
        if status == "PROOF_APPROVED":
            reschedule = False
        elif status == "SCHEDULED":
            if notice["insertions_published"] != 0:
                raise ApiError("ERR_INVALID_STATE", 409,
                               "notice already has published insertions and cannot be rescheduled")
            reschedule = True
        else:
            raise ApiError("ERR_INVALID_STATE", 409,
                           "notice is not schedulable from its current state")

        newspaper = db.newspapers[notice["newspaper_id"]]
        # business-referential: newspaper qualified + county match
        if not newspaper["circulation_qualified"] or notice["county"] != newspaper["county"]:
            raise ApiError("ERR_NEWSPAPER_NOT_QUALIFIED", 422,
                           "newspaper is not qualified for this notice")
        # statutory still present
        statutory = find_statutory(notice["notice_type"], notice["county"])
        if statutory is None:
            raise ApiError("ERR_STATUTORY_REQUIREMENT_MISSING", 422,
                           "no statutory requirement matches (notice_type, county)")
        # optimistic concurrency
        if expected_version != notice["version"]:
            raise ApiError("ERR_STALE_VERSION", 412, "expected_notice_version does not match")

        try:
            first = parse_date(first_publication_date)
        except ValueError:
            raise ApiError("ERR_VALIDATION", 400, "first_publication_date is not a valid date")
        n = notice["required_insertions"]
        dates = [first + timedelta(days=7 * k) for k in range(n)]
        check_dates_temporal(dates, newspaper, notice, statutory)
        check_capacity(dates, newspaper, notice, exclude_notice_id=notice["id"])

        # commit
        if reschedule:
            for ins in notice_insertions(notice["id"]):
                if ins["status"] == "SCHEDULED":
                    ins["status"] = "CANCELLED"
                    touch(ins)
        for k, d in enumerate(dates):
            create_insertion(notice, newspaper, d, k + 1)
        notice["status"] = "SCHEDULED"
        touch(notice)
        return ok(ser(notice), 201)

    @app.route("/notices/<rid>/insertions", methods=["GET"])
    def notice_insertions_list(rid):
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin", "Advertiser", "Publisher", "ComplianceOfficer"})
        notice = _get(db.notices, rid)
        items = [i for i in db.insertions.values() if i["notice_id"] == notice["id"]]
        items = sorted(items, key=lambda i: (i["scheduled_date"], i["_seq"]))
        window, pagination = paginate(items)
        return ok_list([ser(i) for i in window], pagination)

    @app.route("/notices/<rid>/insertions", methods=["POST"])
    def notice_insertion_add(rid):
        uid, role = authenticate()
        require_role(role, {"Advertiser"})
        notice = _get(db.notices, rid)
        own_notice_advertiser(uid, notice)
        if notice["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", 409, "notice is not SCHEDULED")
        data = json_body()
        scheduled_date = req_str(data, "scheduled_date")
        try:
            d = parse_date(scheduled_date)
        except ValueError:
            raise ApiError("ERR_VALIDATION", 400, "scheduled_date is not a valid date")
        newspaper = db.newspapers[notice["newspaper_id"]]
        statutory = find_statutory(notice["notice_type"], notice["county"])
        # temporal: weekday, blackout, deadline (single date)
        check_dates_temporal([d], newspaper, notice, statutory)
        # spacing: exactly 7 days from nearest active insertion of this notice
        actives = [parse_date(i["scheduled_date"])
                   for i in notice_insertions(notice["id"])
                   if i["status"] in ("SCHEDULED", "PUBLISHED")]
        if actives:
            nearest = min(abs((d - a).days) for a in actives)
            if nearest != 7:
                raise ApiError("ERR_INSERTION_SPACING_VIOLATION", 409,
                               "insertion date breaks consecutive-week adjacency")
        # edition capacity
        check_capacity([d], newspaper, notice)
        seq = max((i["sequence_number"] for i in notice_insertions(notice["id"])), default=0) + 1
        ins = create_insertion(notice, newspaper, d, seq)
        return ok(ser(ins), 201)

    # ----------------------------------------------------------------------
    # Proofs
    # ----------------------------------------------------------------------
    @app.route("/proofs/<rid>/approve", methods=["POST"])
    def proof_approve(rid):
        uid, role = authenticate()
        require_role(role, {"Advertiser"})
        proof = _get(db.proofs, rid)
        notice = db.notices[proof["notice_id"]]
        own_notice_advertiser(uid, notice)
        data = json_body()
        note = opt_str(data, "reviewer_note")
        if proof["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", 409, "proof is not PENDING")
        proof["status"] = "APPROVED"
        if note is not None:
            proof["reviewer_note"] = note
        touch(proof)
        notice["status"] = "PROOF_APPROVED"
        touch(notice)
        return ok(ser(proof))

    @app.route("/proofs/<rid>/reject", methods=["POST"])
    def proof_reject(rid):
        uid, role = authenticate()
        require_role(role, {"Advertiser"})
        proof = _get(db.proofs, rid)
        notice = db.notices[proof["notice_id"]]
        own_notice_advertiser(uid, notice)
        data = json_body()
        note = opt_str(data, "reviewer_note")
        if proof["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", 409, "proof is not PENDING")
        proof["status"] = "REJECTED"
        if note is not None:
            proof["reviewer_note"] = note
        touch(proof)
        notice["status"] = "DRAFT"
        touch(notice)
        return ok(ser(proof))

    # ----------------------------------------------------------------------
    # Insertions
    # ----------------------------------------------------------------------
    @app.route("/insertions/<rid>", methods=["GET"])
    def insertion_get(rid):
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin", "Advertiser", "Publisher", "ComplianceOfficer"})
        ins = _get(db.insertions, rid)
        return ok(ser(ins))

    @app.route("/insertions", methods=["GET"])
    def insertion_list():
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin", "Advertiser", "Publisher", "ComplianceOfficer"})
        items = list(db.insertions.values())
        a = request.args
        items = _filter_eq(items, "notice_id", a.get("notice_id"))
        items = _filter_eq(items, "newspaper_id", a.get("newspaper_id"))
        items = _filter_eq(items, "status", a.get("status"))
        items = _filter_eq(items, "makes_good_insertion_id", a.get("makes_good_insertion_id"))
        if a.get("scheduled_date") is not None:
            want = a.get("scheduled_date")
            items = [i for i in items if i["scheduled_date"] == want]
        items = sorted(items, key=lambda i: (i["scheduled_date"], i["_seq"]))
        window, pagination = paginate(items)
        return ok_list([ser(i) for i in window], pagination)

    @app.route("/insertions/<rid>/publish", methods=["POST"])
    def insertion_publish(rid):
        uid, role = authenticate()
        require_role(role, {"Publisher"})
        ins = _get(db.insertions, rid)
        own_publisher_insertion(uid, ins)
        data = json_body()
        line_count_actual = req_int(data, "line_count_actual")
        if line_count_actual < 1:
            raise ApiError("ERR_VALIDATION", 400, "line_count_actual must be >= 1")
        notice = db.notices[ins["notice_id"]]
        if ins["status"] != "SCHEDULED" or notice["status"] not in ("SCHEDULED", "RUNNING"):
            raise ApiError("ERR_INVALID_STATE", 409, "insertion cannot be published from its current state")
        sched_dt = date_to_dt(parse_date(ins["scheduled_date"]))
        if db.clock < sched_dt:
            raise ApiError("ERR_PUBLISH_BEFORE_SCHEDULED", 422,
                           "the logical clock has not reached the scheduled date")
        newspaper = db.newspapers[notice["newspaper_id"]]
        ins["line_count_actual"] = line_count_actual
        ins["published_date"] = fmt_ts(db.clock)
        if ins["is_make_good"]:
            ins["cost_cents"] = 0
        else:
            ins["cost_cents"] = per_insertion_cost(
                newspaper, notice, ins["sequence_number"], line_count_actual)
        ins["status"] = "PUBLISHED"
        touch(ins)
        on_publish(ins)
        return ok(ser(ins))

    @app.route("/insertions/<rid>/skip", methods=["POST"])
    def insertion_skip(rid):
        uid, role = authenticate()
        require_role(role, {"Publisher"})
        ins = _get(db.insertions, rid)
        own_publisher_insertion(uid, ins)
        if ins["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", 409, "insertion is not SCHEDULED")
        if ins["is_make_good"]:
            raise ApiError("ERR_MAKE_GOOD_NOT_SKIPPABLE", 409, "a make-good insertion cannot be skipped")
        notice = db.notices[ins["notice_id"]]
        newspaper = db.newspapers[notice["newspaper_id"]]
        ins["status"] = "SKIPPED"
        touch(ins)
        makegood_date = parse_date(ins["scheduled_date"]) + timedelta(days=7)
        mg = create_insertion(notice, newspaper, makegood_date, ins["sequence_number"],
                              is_make_good=True, makes_good_insertion_id=ins["id"])
        mg["cost_cents"] = 0
        new_compliance = compute_compliance(notice)
        if new_compliance != notice["compliance_status"]:
            notice["compliance_status"] = new_compliance
            touch(notice)
        return ok(ser(ins))

    @app.route("/insertions/<rid>/cancel", methods=["POST"])
    def insertion_cancel(rid):
        uid, role = authenticate()
        require_role(role, {"Advertiser"})
        ins = _get(db.insertions, rid)
        notice = db.notices[ins["notice_id"]]
        own_notice_advertiser(uid, notice)
        if ins["status"] != "SCHEDULED" or notice["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", 409, "insertion cannot be cancelled from its current state")
        ins["status"] = "CANCELLED"
        touch(ins)
        return ok(ser(ins))

    # ----------------------------------------------------------------------
    # Affidavits
    # ----------------------------------------------------------------------
    @app.route("/notices/<rid>/affidavits", methods=["GET"])
    def notice_affidavits(rid):
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin", "Advertiser", "Publisher", "ComplianceOfficer"})
        notice = _get(db.notices, rid)
        items = [a for a in db.affidavits.values() if a["notice_id"] == notice["id"]]
        return _list_response(items)

    @app.route("/affidavits/<rid>", methods=["GET"])
    def affidavit_get(rid):
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin", "Advertiser", "Publisher", "ComplianceOfficer"})
        aff = _get(db.affidavits, rid)
        return ok(ser(aff))

    @app.route("/affidavits/<rid>/issue", methods=["POST"])
    def affidavit_issue(rid):
        uid, role = authenticate()
        require_role(role, {"Publisher"})
        aff = _get(db.affidavits, rid)
        notice = db.notices[aff["notice_id"]]
        own_publisher_notice(uid, notice)
        data = json_body()
        sworn_by = req_str(data, "sworn_by")
        if aff["status"] != "PENDING" or notice["status"] != "PUBLISHED":
            raise ApiError("ERR_INVALID_STATE", 409, "affidavit cannot be issued from its current state")
        published = [i for i in notice_insertions(notice["id"]) if i["status"] == "PUBLISHED"]
        dates = sorted(i["published_date"] for i in published)
        aff["status"] = "ISSUED"
        aff["sworn_by"] = sworn_by
        aff["issued_at"] = fmt_ts(db.clock)
        aff["publication_dates"] = dates
        touch(aff)
        notice["status"] = "AFFIDAVIT_ISSUED"
        touch(notice)
        inv = draft_invoice_of(notice["id"])
        if inv is not None:
            inv["status"] = "ISSUED"
            touch(inv)
        return ok(ser(aff))

    @app.route("/affidavits/<rid>/void", methods=["POST"])
    def affidavit_void(rid):
        uid, role = authenticate()
        require_role(role, {"ComplianceOfficer"})
        aff = _get(db.affidavits, rid)
        notice = db.notices[aff["notice_id"]]
        json_body()  # optional reason; not persisted
        if aff["status"] != "ISSUED":
            raise ApiError("ERR_INVALID_STATE", 409, "affidavit is not ISSUED")
        inv = issued_invoice_of(notice["id"])
        # a paid invoice cannot be unwound
        paid = [i for i in db.invoices.values()
                if i["notice_id"] == notice["id"] and i["status"] == "PAID"]
        if paid:
            raise ApiError("ERR_INVOICE_PAID_LOCK", 409, "the notice's invoice is already paid")
        aff["status"] = "VOID"
        touch(aff)
        notice["status"] = "PUBLISHED"
        touch(notice)
        if inv is not None:
            inv["status"] = "VOID"
            touch(inv)
        return ok(ser(aff))

    # ----------------------------------------------------------------------
    # Invoices / line items
    # ----------------------------------------------------------------------
    @app.route("/invoices/<rid>", methods=["GET"])
    def invoice_get(rid):
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin", "Advertiser"})
        inv = _get(db.invoices, rid)
        return ok(ser(inv))

    @app.route("/invoices", methods=["GET"])
    def invoice_list():
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin", "Advertiser"})
        items = list(db.invoices.values())
        a = request.args
        items = _filter_eq(items, "account_id", a.get("account_id"))
        items = _filter_eq(items, "notice_id", a.get("notice_id"))
        items = _filter_eq(items, "status", a.get("status"))
        return _list_response(items)

    @app.route("/invoice-line-items/<rid>", methods=["GET"])
    def line_item_get(rid):
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin", "Advertiser"})
        li = _get(db.line_items, rid)
        return ok(ser(li))

    @app.route("/invoice-line-items", methods=["GET"])
    def line_item_list():
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin", "Advertiser"})
        items = list(db.line_items.values())
        a = request.args
        items = _filter_eq(items, "invoice_id", a.get("invoice_id"))
        items = _filter_eq(items, "insertion_id", a.get("insertion_id"))
        return _list_response(items)

    # ----------------------------------------------------------------------
    # Payments
    # ----------------------------------------------------------------------
    @app.route("/payments", methods=["POST"])
    def payment_create():
        uid, role = authenticate()
        require_role(role, {"Advertiser"})
        data = json_body()
        invoice_id = req_str(data, "invoice_id")
        amount_cents = req_int(data, "amount_cents")
        inv = _get(db.invoices, invoice_id)
        own_account(uid, inv["account_id"])
        if inv["status"] != "ISSUED":
            raise ApiError("ERR_INVALID_STATE", 409, "invoice is not ISSUED")
        remaining = inv["total_cents"] - inv["amount_paid_cents"]
        if amount_cents <= 0 or amount_cents > remaining:
            raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE", 422,
                           "payment amount is not within the remaining balance")
        pay = make_entity({
            "account_id": inv["account_id"],
            "invoice_id": inv["id"],
            "amount_cents": amount_cents,
        }, light=True)
        db.payments[pay["id"]] = pay
        inv["amount_paid_cents"] += amount_cents
        if inv["amount_paid_cents"] >= inv["total_cents"]:
            inv["status"] = "PAID"
        touch(inv)
        return ok(ser(pay), 201)

    @app.route("/payments/<rid>", methods=["GET"])
    def payment_get(rid):
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin", "Advertiser"})
        pay = _get(db.payments, rid)
        return ok(ser(pay))

    @app.route("/payments", methods=["GET"])
    def payment_list():
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin", "Advertiser"})
        items = list(db.payments.values())
        a = request.args
        items = _filter_eq(items, "account_id", a.get("account_id"))
        items = _filter_eq(items, "invoice_id", a.get("invoice_id"))
        return _list_response(items)

    # ----------------------------------------------------------------------
    # Archive
    # ----------------------------------------------------------------------
    @app.route("/notices/<rid>/archive", methods=["POST"])
    def notice_archive(rid):
        uid, role = authenticate()
        require_role(role, {"ComplianceOfficer"})
        notice = _get(db.notices, rid)
        aff = issued_affidavit_of(notice["id"])
        if notice["status"] != "AFFIDAVIT_ISSUED" or aff is None:
            raise ApiError("ERR_INVALID_STATE", 409, "notice cannot be archived from its current state")
        notice["status"] = "ARCHIVED"
        touch(notice)
        return ok(ser(notice))
