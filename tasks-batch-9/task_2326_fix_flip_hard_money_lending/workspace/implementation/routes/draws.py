"""Draw intake, verification, underwriting, disbursement and lien waivers."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calc
import serialize as ser
import services as svc
from core import (
    ROLE_BORROWER, ROLE_CONTRACTOR, ROLE_DRAW_INSPECTOR, ROLE_LOAN_OFFICER,
    ROLE_LOAN_SERVICER, ROLE_PLATFORM_ADMIN,
    ApiError, authenticate, caller_id, caller_role, clock_instant, conflict, db,
    f_array, f_bool, f_date, f_datetime, f_enum, f_int, f_str, invalid,
    json_body, new_record, ok, ok_list, paginate, q_enum, q_str,
    require_borrower_owner, require_contractor_owner, rhu, sort_records,
    to_decimal, touch,
)

ZERO = Decimal("0.00")
ONE_PCT = Decimal("0.01")
FULL = Decimal("1.00")

bp = Blueprint("draws", __name__)

DRAW_STATUSES = ("SUBMITTED", "INSPECTION_ORDERED", "INSPECTED", "REVISION_REQUESTED",
                 "APPROVED", "FUNDED", "REJECTED", "SUPERSEDED", "SUSPENDED")
VISIT_STATUSES = ("SCHEDULED", "COMPLETED", "CANCELLED")
WAIVER_STATUSES = ("COLLECTED", "DISPUTED")


def _loan_of(request):
    return db.loans.get(request["loan_id"])


def _entry_field(entry, name, index, array_name):
    if name not in entry or entry[name] is None:
        raise invalid("Entry %d of '%s' is missing '%s'." % (index, array_name, name))
    return entry[name]


def _read_allocations(body):
    rows = []
    entries = f_array(body, "line_allocations")
    for index, entry in enumerate(entries):
        line_id = _entry_field(entry, "rehab_line_item_id", index, "line_allocations")
        if not isinstance(line_id, str) or line_id.strip() == "":
            raise invalid("Entry %d of 'line_allocations' has an invalid rehab_line_item_id." % index)
        claimed = to_decimal(_entry_field(entry, "claimed_percent_complete", index, "line_allocations"),
                             "claimed_percent_complete", places=2,
                             minimum=ONE_PCT, maximum=FULL)
        rows.append({"rehab_line_item_id": line_id, "claimed_percent_complete": claimed})
    return rows


def _read_verifications(body):
    entries = f_array(body, "line_verifications")
    rows = []
    for index, entry in enumerate(entries):
        line_id = _entry_field(entry, "rehab_line_item_id", index, "line_verifications")
        if not isinstance(line_id, str) or line_id.strip() == "":
            raise invalid("Entry %d of 'line_verifications' has an invalid rehab_line_item_id." % index)
        verified = to_decimal(_entry_field(entry, "verified_percent_complete", index, "line_verifications"),
                              "verified_percent_complete", places=2,
                              minimum=ZERO, maximum=FULL)
        rows.append({"rehab_line_item_id": line_id, "verified_percent_complete": verified})
    return rows


def _apply_verifications(request, rows):
    """Priority 7 coverage test, then write verified/effective onto every allocation."""
    allocations = sort_records(ser.request_allocations(request["id"]))
    alloc_by_line = {}
    for alloc in allocations:
        alloc_by_line[alloc["rehab_line_item_id"]] = alloc
    seen = set()
    for row in rows:
        line_id = row["rehab_line_item_id"]
        if line_id not in alloc_by_line or line_id in seen:
            raise conflict("ERR_LINE_VERIFICATION_INCOMPLETE",
                           "line_verifications must cover every allocation of the request exactly once.")
        seen.add(line_id)
    if len(seen) != len(alloc_by_line):
        raise conflict("ERR_LINE_VERIFICATION_INCOMPLETE",
                       "line_verifications must cover every allocation of the request exactly once.")
    return alloc_by_line


def _write_verifications(request, rows, alloc_by_line):
    for row in rows:
        alloc = alloc_by_line[row["rehab_line_item_id"]]
        alloc["verified_percent_complete"] = row["verified_percent_complete"]
        alloc["effective_percent_complete"] = calc.effective_percent(
            alloc["claimed_percent_complete"], row["verified_percent_complete"],
            request["verification_method"])
        touch(alloc)


def _contractor_of_allocation(alloc):
    line = db.rehab_line_items.get(alloc["rehab_line_item_id"])
    if line is None:
        return None
    return db.contractors.get(line["contractor_id"])


# ---------------------------------------------------------------------------
# Draw request intake
# ---------------------------------------------------------------------------
@bp.post("/loans/<rec_id>/draw-requests")
def create_draw_request(rec_id):
    authenticate((ROLE_BORROWER, ROLE_PLATFORM_ADMIN))
    body = json_body()
    allocations = _read_allocations(body)
    verification_method = f_enum(body, "verification_method", calc.VERIFICATION_METHODS)
    expected_loan_version = f_int(body, "expected_loan_version", minimum=0)

    loan = ser.find_loan(rec_id)
    lines = [ser.find_rehab_line_item(a["rehab_line_item_id"]) for a in allocations]
    require_borrower_owner(loan["borrower_id"])

    for line in lines:
        if line["application_id"] != loan["application_id"]:
            raise conflict("ERR_LINE_ITEM_MISMATCH",
                           "A scope line does not belong to the loan's originating application.")

    if expected_loan_version != loan["version"]:
        raise ApiError("ERR_STALE_LOAN_VERSION", 412,
                       "expected_loan_version does not match the loan's current version.")

    svc.require_loan_writable(loan)
    svc.require_serviceable(loan)

    for line in lines:
        if line["status"] != "APPROVED":
            raise conflict("ERR_SCOPE_LINE_NOT_APPROVED",
                           "An allocation targets a scope line that is not APPROVED.")

    seen = set()
    for alloc in allocations:
        if alloc["rehab_line_item_id"] in seen:
            raise conflict("ERR_LINE_ALLOCATION_DUPLICATE",
                           "The same rehab_line_item_id appears twice in line_allocations.")
        seen.add(alloc["rehab_line_item_id"])

    request = new_record()
    sequence_number = len(ser.loan_draw_requests(loan["id"])) + 1
    request.update({
        "loan_id": loan["id"],
        "sequence_number": sequence_number,
        "verification_method": verification_method,
        "photo_count": None,
        "requested_total_cents": 0,
        "approved_release_cents": None,
        "status": "SUBMITTED",
        "reviewed_by_user_id": None,
        "funded_by_user_id": None,
        "funded_at": None,
        "superseded_by_draw_request_id": None,
    })
    db.draw_requests[request["id"]] = request

    total = 0
    for alloc, line in zip(allocations, lines):
        amount = rhu(alloc["claimed_percent_complete"] * calc.Decimal(line["approved_cost_cents"])) \
            - line["released_cents"]
        row = new_record()
        row.update({
            "draw_request_id": request["id"],
            "rehab_line_item_id": line["id"],
            "claimed_percent_complete": alloc["claimed_percent_complete"],
            "verified_percent_complete": None,
            "effective_percent_complete": None,
            "requested_amount_cents": amount,
            "approved_amount_cents": None,
            "released_cents": 0,
        })
        db.draw_line_items[row["id"]] = row
        total += amount
    request["requested_total_cents"] = total

    svc.supersede_open_requests(loan, request["id"])
    touch(loan)
    return ok(ser.draw_request_out(request), 201)


@bp.get("/draw-requests")
def list_draw_requests():
    authenticate((ROLE_LOAN_OFFICER, ROLE_LOAN_SERVICER, ROLE_BORROWER,
                  ROLE_DRAW_INSPECTOR, ROLE_PLATFORM_ADMIN))
    loan_id = q_str("loan_id")
    status = q_enum("status", DRAW_STATUSES)
    superseded_by = q_str("superseded_by_draw_request_id")
    rows = list(db.draw_requests.values())
    if caller_role() == ROLE_BORROWER:
        rows = [d for d in rows
                if (db.loans.get(d["loan_id"]) or {}).get("borrower_id") == caller_id()]
    if loan_id is not None:
        rows = [d for d in rows if d["loan_id"] == loan_id]
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    if superseded_by is not None:
        rows = [d for d in rows if d["superseded_by_draw_request_id"] == superseded_by]
    items, meta = paginate(rows, ser.draw_request_out)
    return ok_list(items, meta)


@bp.get("/draw-requests/<rec_id>")
def read_draw_request(rec_id):
    authenticate((ROLE_LOAN_OFFICER, ROLE_LOAN_SERVICER, ROLE_BORROWER,
                  ROLE_DRAW_INSPECTOR, ROLE_PLATFORM_ADMIN))
    request = ser.find_draw_request(rec_id)
    loan = _loan_of(request)
    if loan is not None:
        require_borrower_owner(loan["borrower_id"])
    return ok(ser.draw_request_out(request))


# ---------------------------------------------------------------------------
# Inspection leg
# ---------------------------------------------------------------------------
@bp.post("/draw-requests/<rec_id>/inspection-visits")
def order_inspection_visit(rec_id):
    authenticate((ROLE_LOAN_SERVICER, ROLE_PLATFORM_ADMIN))
    body = json_body()
    inspector_id = f_str(body, "inspector_id")
    window_start = f_datetime(body, "window_start")
    window_end = f_datetime(body, "window_end")
    if window_end <= window_start:
        raise invalid("window_end must be strictly later than window_start.")
    request = ser.find_draw_request(rec_id)
    loan = _loan_of(request)

    if request["status"] not in ("SUBMITTED", "INSPECTION_ORDERED"):
        raise conflict("ERR_DRAW_REQUEST_STATE_INVALID",
                       "Only a SUBMITTED draw request can have an inspection ordered.")
    if loan is not None:
        svc.require_loan_writable(loan)

    buffer_delta = timedelta(minutes=calc.TRAVEL_BUFFER_MINUTES)
    for visit in db.inspection_visits.values():
        if visit["inspector_id"] != inspector_id or visit["status"] != "SCHEDULED":
            continue
        existing_start = visit["window_start"] - buffer_delta
        existing_end = visit["window_end"] + buffer_delta
        if window_start < existing_end and existing_start < window_end:
            raise conflict("ERR_INSPECTOR_WINDOW_CONFLICT",
                           "The inspector already holds a SCHEDULED visit overlapping this window.")

    for visit in ser.request_visits(request["id"]):
        if visit["status"] == "SCHEDULED":
            raise conflict("ERR_VISIT_ALREADY_SCHEDULED",
                           "This draw request already has a SCHEDULED inspection visit.")
    if request["verification_method"] != "INSPECTION":
        raise conflict("ERR_VERIFICATION_METHOD_MISMATCH",
                       "This draw request is not verified by site inspection.")

    visit = new_record()
    visit.update({
        "draw_request_id": request["id"],
        "inspector_id": inspector_id,
        "window_start": window_start,
        "window_end": window_end,
        "status": "SCHEDULED",
        "reported_at": None,
        "site_notes": None,
    })
    db.inspection_visits[visit["id"]] = visit
    request["status"] = "INSPECTION_ORDERED"
    touch(request)
    return ok(ser.inspection_visit_out(visit), 201)


@bp.get("/draw-requests/<rec_id>/inspection-visits")
def list_inspection_visits(rec_id):
    authenticate((ROLE_LOAN_SERVICER, ROLE_DRAW_INSPECTOR, ROLE_BORROWER, ROLE_PLATFORM_ADMIN))
    status = q_enum("status", VISIT_STATUSES)
    request = ser.find_draw_request(rec_id)
    loan = _loan_of(request)
    if loan is not None:
        require_borrower_owner(loan["borrower_id"])
    rows = ser.request_visits(request["id"])
    if status is not None:
        rows = [v for v in rows if v["status"] == status]
    items, meta = paginate(rows, ser.inspection_visit_out)
    return ok_list(items, meta)


@bp.post("/inspection-visits/<rec_id>/report")
def report_inspection_visit(rec_id):
    authenticate((ROLE_DRAW_INSPECTOR, ROLE_PLATFORM_ADMIN))
    body = json_body()
    rows = _read_verifications(body)
    site_notes = f_str(body, "site_notes", required=False)
    visit = ser.find_inspection_visit(rec_id)
    for row in rows:
        ser.find_rehab_line_item(row["rehab_line_item_id"])
    request = ser.find_draw_request(visit["draw_request_id"])

    if caller_id() != visit["inspector_id"]:
        raise ApiError("ERR_NOT_ASSIGNED_INSPECTOR", 403,
                       "Only the assigned inspector may file this report.")

    alloc_by_line = _apply_verifications(request, rows)

    if visit["status"] != "SCHEDULED":
        raise conflict("ERR_INSPECTION_VISIT_STATE_INVALID",
                       "Only a SCHEDULED visit can be reported.")
    if request["status"] != "INSPECTION_ORDERED":
        raise conflict("ERR_DRAW_REQUEST_STATE_INVALID",
                       "The owning draw request is not INSPECTION_ORDERED.")

    _write_verifications(request, rows, alloc_by_line)
    visit["status"] = "COMPLETED"
    visit["reported_at"] = clock_instant()
    visit["site_notes"] = site_notes
    touch(visit)
    request["status"] = "INSPECTED"
    touch(request)
    return ok(ser.inspection_visit_out(visit))


# ---------------------------------------------------------------------------
# Photo leg
# ---------------------------------------------------------------------------
@bp.post("/draw-requests/<rec_id>/photo-verification")
def photo_verification(rec_id):
    authenticate((ROLE_LOAN_SERVICER, ROLE_PLATFORM_ADMIN))
    body = json_body()
    rows = _read_verifications(body)
    photo_count = f_int(body, "photo_count", minimum=0)
    request = ser.find_draw_request(rec_id)
    for row in rows:
        ser.find_rehab_line_item(row["rehab_line_item_id"])
    loan = _loan_of(request)

    alloc_by_line = _apply_verifications(request, rows)

    if request["status"] != "SUBMITTED":
        raise conflict("ERR_DRAW_REQUEST_STATE_INVALID",
                       "Only a SUBMITTED draw request can be photo-verified.")
    if loan is not None:
        svc.require_loan_writable(loan)

    if request["verification_method"] != "PHOTO":
        raise conflict("ERR_VERIFICATION_METHOD_MISMATCH",
                       "This draw request is not verified from photographic evidence.")
    if photo_count < calc.PHOTO_MIN_PHOTOS_PER_LINE * len(alloc_by_line):
        raise conflict("ERR_INSUFFICIENT_PHOTO_EVIDENCE",
                       "At least three photos per allocation are required.")
    if request["requested_total_cents"] > calc.PHOTO_MAX_REQUEST_CENTS:
        raise conflict("ERR_PHOTO_REQUEST_TOO_LARGE",
                       "A photo-verified draw may not exceed thirty thousand dollars.")

    _write_verifications(request, rows, alloc_by_line)
    request["photo_count"] = photo_count
    request["status"] = "INSPECTED"
    touch(request)
    return ok(ser.draw_request_out(request))


# ---------------------------------------------------------------------------
# Underwriting
# ---------------------------------------------------------------------------
def _release_plan(request):
    """Per-line releases in ascending scope_code order (PRD 3.6)."""
    allocations = ser.request_allocations(request["id"])
    decorated = []
    for alloc in allocations:
        line = db.rehab_line_items.get(alloc["rehab_line_item_id"])
        code = line["scope_code"] if line is not None else ""
        decorated.append((code, alloc["_seq"], alloc, line))
    decorated.sort(key=lambda row: (row[0], row[1]))
    plan = []
    for _, _, alloc, line in decorated:
        eff = calc.effective_percent(alloc["claimed_percent_complete"],
                                     alloc["verified_percent_complete"],
                                     request["verification_method"])
        amount = calc.line_release(line["approved_cost_cents"], line["released_cents"], eff,
                                   request["verification_method"])
        plan.append((alloc, line, eff, amount))
    return plan


@bp.post("/draw-requests/<rec_id>/review")
def review_draw_request(rec_id):
    authenticate((ROLE_LOAN_SERVICER, ROLE_PLATFORM_ADMIN))
    body = json_body()
    decision = f_enum(body, "decision", ("APPROVE", "REQUEST_REVISION", "REJECT"))
    f_str(body, "reviewer_note", required=False)
    request = ser.find_draw_request(rec_id)
    loan = ser.find_loan(request["loan_id"])

    if request["status"] != "INSPECTED":
        raise conflict("ERR_DRAW_REQUEST_STATE_INVALID",
                       "Only an INSPECTED draw request can be reviewed.")
    svc.require_loan_writable(loan)
    if loan["payment_status"] not in ("CURRENT", "DELINQUENT"):
        raise conflict("ERR_LOAN_NOT_SERVICEABLE",
                       "The loan is not serviceable for a draw review.")

    if decision != "APPROVE":
        request["reviewed_by_user_id"] = caller_id()
        request["status"] = "REVISION_REQUESTED" if decision == "REQUEST_REVISION" else "REJECTED"
        touch(request)
        return ok(ser.draw_request_out(request))

    plan = _release_plan(request)

    for _, line, _, _ in plan:
        contractor = db.contractors.get(line["contractor_id"])
        if contractor is None or not calc.payable(contractor):
            raise conflict("ERR_CONTRACTOR_NOT_PAYABLE",
                           "A contractor on this draw is not payable.")

    contractor_ids = []
    for _, line, _, _ in plan:
        if line["contractor_id"] not in contractor_ids:
            contractor_ids.append(line["contractor_id"])
    for contractor_id in contractor_ids:
        for waiver in db.lien_waivers.values():
            if waiver["contractor_id"] == contractor_id and waiver["status"] == "DISPUTED":
                raise conflict("ERR_LIEN_WAIVER_DISPUTED",
                               "A contractor on this draw has a disputed lien waiver.")

    shares = {}
    for _, line, _, amount in plan:
        shares[line["contractor_id"]] = shares.get(line["contractor_id"], 0) + amount
    for contractor_id in contractor_ids:
        if shares[contractor_id] > calc.open_waiver_headroom_cents(contractor_id):
            raise conflict("ERR_WAIVER_HEADROOM_EXCEEDED",
                           "A contractor's share of this release exceeds its waiver headroom.")

    for _, _, _, amount in plan:
        if amount < 0:
            raise conflict("ERR_PERCENT_COMPLETE_REGRESSION",
                           "A computed per-line release is negative.")

    total = 0
    for alloc, _, eff, amount in plan:
        alloc["effective_percent_complete"] = eff
        alloc["approved_amount_cents"] = amount
        touch(alloc)
        total += amount

    request["approved_release_cents"] = total
    request["reviewed_by_user_id"] = caller_id()
    request["status"] = "APPROVED"
    touch(request)
    loan["undisbursed_holdback_cents"] -= total
    loan["reserved_release_cents"] += total
    touch(loan)
    return ok(ser.draw_request_out(request))


@bp.post("/draw-requests/<rec_id>/fund")
def fund_draw_request(rec_id):
    authenticate((ROLE_LOAN_SERVICER, ROLE_PLATFORM_ADMIN))
    body = json_body()
    funding_date = f_date(body, "funding_date")
    joint_check_ack = f_bool(body, "joint_check_ack", required=False)
    request = ser.find_draw_request(rec_id)
    loan = ser.find_loan(request["loan_id"])

    if request["status"] != "APPROVED":
        raise conflict("ERR_DRAW_REQUEST_STATE_INVALID",
                       "Only an APPROVED draw request can be funded.")
    svc.require_loan_writable(loan)
    if loan["payment_status"] not in ("CURRENT", "DELINQUENT"):
        raise conflict("ERR_LOAN_NOT_SERVICEABLE",
                       "The loan is not serviceable for a draw disbursement.")

    if caller_id() == request["reviewed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "The operator that reviewed this draw may not fund it.")

    allocations = sort_records(ser.request_allocations(request["id"]))
    shares = {}
    for alloc in allocations:
        line = db.rehab_line_items.get(alloc["rehab_line_item_id"])
        amount = alloc["approved_amount_cents"] or 0
        shares[line["contractor_id"]] = shares.get(line["contractor_id"], 0) + amount
    for contractor_id, share in shares.items():
        if share > calc.open_waiver_headroom_cents(contractor_id):
            raise conflict("ERR_WAIVER_HEADROOM_EXCEEDED",
                           "A contractor's share of this disbursement exceeds its waiver headroom.")

    for alloc in allocations:
        line = db.rehab_line_items.get(alloc["rehab_line_item_id"])
        amount = alloc["approved_amount_cents"] or 0
        if line["released_cents"] + amount < line["approved_cost_cents"]:
            continue
        has_final = False
        for waiver in db.lien_waivers.values():
            if (waiver["contractor_id"] == line["contractor_id"]
                    and waiver["waiver_type"] == "FINAL_UNCONDITIONAL"):
                has_final = True
                break
        if not has_final:
            raise conflict("ERR_FINAL_WAIVER_REQUIRED",
                           "A scope line reaching full completion needs a final unconditional waiver.")

    for alloc in allocations:
        line = db.rehab_line_items.get(alloc["rehab_line_item_id"])
        contractor = db.contractors.get(line["contractor_id"])
        if contractor is not None and contractor["joint_check_required"]:
            if joint_check_ack is not True:
                raise conflict("ERR_JOINT_CHECK_ACK_REQUIRED",
                               "A joint-check acknowledgement is required for this disbursement.")

    total = request["approved_release_cents"] or 0
    for alloc in allocations:
        amount = alloc["approved_amount_cents"] or 0
        alloc["released_cents"] = amount
        touch(alloc)
        line = db.rehab_line_items.get(alloc["rehab_line_item_id"])
        line["released_cents"] += amount
        if line["approved_cost_cents"] is not None and line["released_cents"] >= line["approved_cost_cents"]:
            line["status"] = "FULLY_RELEASED"
        touch(line)

    loan["reserved_release_cents"] -= total
    loan["funded_principal_cents"] += total
    if loan["construction_status"] == "NOT_STARTED":
        loan["construction_status"] = "IN_PROGRESS"
    if loan["construction_status"] == "IN_PROGRESS":
        remaining = [l for l in ser.application_lines(loan["application_id"])
                     if l["status"] == "APPROVED"]
        if not remaining:
            loan["construction_status"] = "COMPLETE"
    touch(loan)

    request["status"] = "FUNDED"
    svc.stamp_funded(request, caller_id())
    touch(request)
    svc.write_ledger(loan, "DRAW_DISBURSEMENT", total, funding_date,
                     "Draw disbursement", request["id"])
    return ok(ser.draw_request_out(request))


# ---------------------------------------------------------------------------
# Draw allocations
# ---------------------------------------------------------------------------
@bp.get("/draw-line-items")
def list_draw_line_items():
    authenticate((ROLE_LOAN_OFFICER, ROLE_LOAN_SERVICER, ROLE_BORROWER,
                  ROLE_DRAW_INSPECTOR, ROLE_PLATFORM_ADMIN))
    draw_request_id = q_str("draw_request_id")
    rehab_line_item_id = q_str("rehab_line_item_id")
    rows = list(db.draw_line_items.values())
    if caller_role() == ROLE_BORROWER:
        allowed = set()
        for request in db.draw_requests.values():
            loan = db.loans.get(request["loan_id"])
            if loan is not None and loan["borrower_id"] == caller_id():
                allowed.add(request["id"])
        rows = [a for a in rows if a["draw_request_id"] in allowed]
    if draw_request_id is not None:
        rows = [a for a in rows if a["draw_request_id"] == draw_request_id]
    if rehab_line_item_id is not None:
        rows = [a for a in rows if a["rehab_line_item_id"] == rehab_line_item_id]
    items, meta = paginate(rows, ser.draw_line_item_out)
    return ok_list(items, meta)


@bp.get("/draw-line-items/<rec_id>")
def read_draw_line_item(rec_id):
    authenticate((ROLE_LOAN_OFFICER, ROLE_LOAN_SERVICER, ROLE_BORROWER,
                  ROLE_DRAW_INSPECTOR, ROLE_PLATFORM_ADMIN))
    alloc = ser.find_draw_line_item(rec_id)
    request = db.draw_requests.get(alloc["draw_request_id"])
    loan = _loan_of(request) if request is not None else None
    if loan is not None:
        require_borrower_owner(loan["borrower_id"])
    return ok(ser.draw_line_item_out(alloc))


# ---------------------------------------------------------------------------
# Lien waivers
# ---------------------------------------------------------------------------
@bp.post("/lien-waivers")
def create_lien_waiver():
    authenticate((ROLE_CONTRACTOR, ROLE_LOAN_SERVICER, ROLE_PLATFORM_ADMIN))
    body = json_body()
    loan_id = f_str(body, "loan_id")
    contractor_id = f_str(body, "contractor_id")
    waiver_type = f_enum(body, "waiver_type", calc.WAIVER_TYPES)
    amount_covered_cents = f_int(body, "amount_covered_cents", minimum=1)
    through_date = f_date(body, "through_date")
    loan = ser.find_loan(loan_id)
    contractor = ser.find_contractor(contractor_id)
    require_contractor_owner(contractor["id"])

    rec = new_record()
    rec.update({
        "loan_id": loan["id"],
        "contractor_id": contractor["id"],
        "waiver_type": waiver_type,
        "amount_covered_cents": amount_covered_cents,
        "through_date": through_date,
        "status": "COLLECTED",
    })
    db.lien_waivers[rec["id"]] = rec
    return ok(ser.lien_waiver_out(rec), 201)


@bp.get("/loans/<rec_id>/lien-waivers")
def list_loan_lien_waivers(rec_id):
    authenticate((ROLE_LOAN_OFFICER, ROLE_LOAN_SERVICER, ROLE_BORROWER, ROLE_PLATFORM_ADMIN))
    status = q_enum("status", WAIVER_STATUSES)
    loan = ser.find_loan(rec_id)
    require_borrower_owner(loan["borrower_id"])
    rows = ser.loan_lien_waivers(loan["id"])
    if status is not None:
        rows = [w for w in rows if w["status"] == status]
    items, meta = paginate(rows, ser.lien_waiver_out)
    return ok_list(items, meta)


@bp.post("/lien-waivers/<rec_id>/dispute")
def dispute_lien_waiver(rec_id):
    authenticate((ROLE_LOAN_SERVICER, ROLE_PLATFORM_ADMIN))
    body = json_body()
    action = f_enum(body, "action", ("DISPUTE", "RESOLVE"))
    f_str(body, "note", required=False)
    waiver = ser.find_lien_waiver(rec_id)
    waiver["status"] = "DISPUTED" if action == "DISPUTE" else "COLLECTED"
    touch(waiver)
    return ok(ser.lien_waiver_out(waiver))
