"""Bankruptcy Filing API — Flask entry point and all routes.

Implements PRD.md (workspace/PRD.md) verbatim. Storage is in-memory only and
starts empty on every boot (see db.py). No entities are seeded.
"""

import os

from flask import Flask, request

import db
import errors
import services
from errors import ApiError, err
from middleware import (
    authorize,
    get_auth,
    get_body,
    invalid,
    optional_bool,
    optional_int,
    paginate,
    parse_pagination,
    require_enum,
    require_fk,
    require_int,
    require_path,
    require_str,
)
from response import array_response, error_response, object_response

app = Flask(__name__)

# Enum domains (SCAFFOLD 1.1).
CHAPTER_DOMAIN = {"CHAPTER_7", "CHAPTER_13"}
SCHEDULE_LETTERS = {"A", "B", "C", "D", "E", "F", "G", "H", "I", "J"}
DEBT_CLASSES = {"SECURED", "PRIORITY", "UNSECURED"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % str(e), 422)


# ---------------------------------------------------------------------------
# Public/serialization helpers
# ---------------------------------------------------------------------------

def public(obj):
    """Return a shallow copy of a stored resource for response output."""
    return dict(obj)


# ===========================================================================
# Registries: Debtors, Creditors, Trustees (PRD 3.1)
# ===========================================================================

@app.route("/debtors", methods=["POST"])
def create_debtor():
    _, role = get_auth()
    authorize(role, {"BankruptcyAdmin", "Debtor"})
    body = get_body()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    prior = optional_bool(body, "prior_discharge_within_8y", default=False)

    with db.lock:
        if email in db.debtor_emails:
            invalid("Debtor email must be unique.")
        d = {
            "id": db.new_id(),
            "full_name": full_name,
            "email": email,
            "prior_discharge_within_8y": prior,
        }
        db.stamp_create(d)
        db.debtors[d["id"]] = d
        db.debtor_emails[email] = d["id"]
    return object_response(public(d), 201)


@app.route("/debtors/<rid>", methods=["GET"])
def get_debtor(rid):
    _, role = get_auth()
    authorize(role, {"BankruptcyAdmin", "Debtor", "Trustee"})
    d = require_path(db.debtors, rid)
    return object_response(public(d), 200)


@app.route("/creditors", methods=["POST"])
def create_creditor():
    _, role = get_auth()
    authorize(role, {"BankruptcyAdmin", "Creditor"})
    body = get_body()
    name = require_str(body, "name")
    with db.lock:
        c = {"id": db.new_id(), "name": name}
        db.stamp_create(c)
        db.creditors[c["id"]] = c
    return object_response(public(c), 201)


@app.route("/creditors/<rid>", methods=["GET"])
def get_creditor(rid):
    _, role = get_auth()
    authorize(role, {"BankruptcyAdmin", "Creditor", "Trustee"})
    c = require_path(db.creditors, rid)
    return object_response(public(c), 200)


@app.route("/trustees", methods=["POST"])
def create_trustee():
    _, role = get_auth()
    authorize(role, {"BankruptcyAdmin", "Trustee"})
    body = get_body()
    name = require_str(body, "name")
    with db.lock:
        t = {"id": db.new_id(), "name": name}
        db.stamp_create(t)
        db.trustees[t["id"]] = t
    return object_response(public(t), 201)


@app.route("/trustees/<rid>", methods=["GET"])
def get_trustee(rid):
    _, role = get_auth()
    authorize(role, {"BankruptcyAdmin", "Trustee"})
    t = require_path(db.trustees, rid)
    return object_response(public(t), 200)


# ===========================================================================
# Cases (PRD 3.2, 3.4, 3.10)
# ===========================================================================

@app.route("/cases", methods=["POST"])
def create_case():
    _, role = get_auth()
    authorize(role, {"BankruptcyAdmin", "Debtor"})
    body = get_body()
    # FK existence (priority 4) before field well-formedness (priority 5) —
    # but debtor_id must be a string to even look it up. PRD 2.6 places FK
    # existence ahead of field validity; we honor that by checking the FK key's
    # presence/type minimally then resolving it.
    debtor_id = body.get("debtor_id")
    if not isinstance(debtor_id, str) or debtor_id == "":
        invalid("Field debtor_id must be a non-empty string.")
    with db.lock:
        require_fk(db.debtors, debtor_id)
        filed_chapter = require_enum(body, "filed_chapter", CHAPTER_DOMAIN)
        state_code = require_str(body, "state_code")
        if not (len(state_code) == 2 and state_code.isalpha() and state_code.isupper()):
            invalid("state_code must be a two-letter uppercase US state code.")
        household_size = require_int(body, "household_size", minimum=1)

        c = {
            "id": db.new_id(),
            "debtor_id": debtor_id,
            "filed_chapter": filed_chapter,
            "status": "DRAFT",
            "stay_posture": "NONE",
            "petition_date": None,
            "state_code": state_code,
            "household_size": household_size,
            "means_test_result": "NOT_RUN",
            "total_exempt_value_cents": 0,
            "nonexempt_estate_cents": 0,
        }
        db.stamp_create(c)
        db.cases[c["id"]] = c
    return object_response(public(c), 201)


@app.route("/cases/<rid>", methods=["GET"])
def get_case(rid):
    _, role = get_auth()
    authorize(role, {"BankruptcyAdmin", "Debtor", "Trustee", "Creditor"})
    c = require_path(db.cases, rid)
    return object_response(public(c), 200)


@app.route("/cases", methods=["GET"])
def list_cases():
    _, role = get_auth()
    authorize(role, {"BankruptcyAdmin", "Trustee"})
    limit, offset = parse_pagination()
    debtor_id = request.args.get("debtor_id")
    status = request.args.get("status")
    items = list(db.cases.values())
    if debtor_id is not None:
        items = [c for c in items if c["debtor_id"] == debtor_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    window, total = paginate(items, limit, offset)
    return array_response([public(c) for c in window], limit, offset, total)


@app.route("/cases/<rid>/petition", methods=["POST"])
def petition_case(rid):
    user_id, role = get_auth()
    authorize(role, {"Debtor"})
    with db.lock:
        c = require_path(db.cases, rid)
        # State precedes business rules (PRD 2.7).
        if c["status"] != "DRAFT":
            raise err(errors.ERR_INVALID_STATE, "Case is not in DRAFT.")
        # Required precondition: Schedule I and J both exist.
        letters = {s["schedule_letter"] for s in services.case_schedule_rows(c["id"])}
        if "I" not in letters or "J" not in letters:
            raise err(errors.ERR_INVALID_STATE, "Petition requires Schedule I and J rows.")
        # A means test must exist and have a result other than NOT_RUN.
        mt = next((m for m in db.means_tests.values() if m["case_id"] == c["id"]), None)
        if mt is None or mt["result"] == "NOT_RUN":
            raise err(errors.ERR_INVALID_STATE, "Petition requires a completed means test.")
        # Chapter 7 abuse bar (priority 11).
        if c["filed_chapter"] == "CHAPTER_7" and c["means_test_result"] == "PRESUMPTION_ABUSE":
            raise err(errors.ERR_MEANS_TEST_ABUSE, "Presumption of abuse bars a Chapter 7 petition.")

        c["status"] = "FILED"
        c["petition_date"] = db.now_iso()
        c["stay_posture"] = "ACTIVE"
        db.touch(c)
    return object_response(public(c), 200)


@app.route("/cases/<rid>/confirm", methods=["POST"])
def confirm_case(rid):
    _, role = get_auth()
    authorize(role, {"Trustee"})
    with db.lock:
        c = require_path(db.cases, rid)
        if c["status"] != "MEETING_HELD":
            raise err(errors.ERR_INVALID_STATE, "Case is not in MEETING_HELD.")
        if c["filed_chapter"] != "CHAPTER_13":
            raise err(errors.ERR_NOT_CHAPTER_13, "Case confirmation requires CHAPTER_13.")
        has_confirmed_plan = any(
            p["case_id"] == c["id"] and p["status"] == "CONFIRMED"
            for p in db.plans.values()
        )
        if not has_confirmed_plan:
            raise err(errors.ERR_INVALID_STATE, "Case has no CONFIRMED plan.")
        c["status"] = "CONFIRMED"
        db.touch(c)
    return object_response(public(c), 200)


@app.route("/cases/<rid>/discharge", methods=["POST"])
def discharge_case(rid):
    _, role = get_auth()
    authorize(role, {"Trustee"})
    with db.lock:
        c = require_path(db.cases, rid)
        chapter = c["filed_chapter"]

        if chapter == "CHAPTER_7":
            if c["status"] != "MEETING_HELD":
                raise err(errors.ERR_INVALID_STATE, "Chapter 7 discharge requires MEETING_HELD.")
            if c["means_test_result"] != "PRESUMPTION_OK":
                raise err(errors.ERR_INVALID_STATE, "Chapter 7 discharge requires PRESUMPTION_OK.")
            debtor = db.debtors.get(c["debtor_id"])
            if debtor is not None and debtor.get("prior_discharge_within_8y"):
                raise err(errors.ERR_PRIOR_DISCHARGE_BAR, "Prior discharge within 8 years bars a new one.")
        else:  # CHAPTER_13
            if c["status"] != "CONFIRMED":
                raise err(errors.ERR_INVALID_STATE, "Chapter 13 discharge requires CONFIRMED.")
            plan = services.active_plan(c["id"])
            if plan is None or plan["paid_to_date_cents"] < plan["total_committed_cents"]:
                raise err(errors.ERR_INVALID_STATE, "Chapter 13 discharge requires a fully funded plan.")

        # Common discharge side effects.
        c["status"] = "DISCHARGED"
        c["stay_posture"] = "TERMINATED"

        # Chapter 13: mark active plan COMPLETED.
        if chapter == "CHAPTER_13":
            plan = services.active_plan(c["id"])
            if plan is not None:
                plan["status"] = "COMPLETED"
                db.touch(plan)

        # Reduce UNSECURED debts' allowed amounts to 0; SECURED/PRIORITY survive.
        for d in db.debts.values():
            if d["case_id"] == c["id"] and d["debt_class"] == "UNSECURED":
                d["allowed_amount_cents"] = 0
                db.touch(d)

        # Reconcile exemption settlement.
        services.recompute_estate_fields(c)
        db.touch(c)
    return object_response(public(c), 200)


@app.route("/cases/<rid>/dismiss", methods=["POST"])
def dismiss_case(rid):
    _, role = get_auth()
    authorize(role, {"Trustee"})
    with db.lock:
        c = require_path(db.cases, rid)
        if c["status"] not in ("FILED", "MEETING_HELD", "CONFIRMED"):
            raise err(errors.ERR_INVALID_STATE, "Case cannot be dismissed from its current state.")
        c["status"] = "DISMISSED"
        c["stay_posture"] = "TERMINATED"
        # Moot pending stay-relief motions.
        for m in db.stay_relief_motions.values():
            if m["case_id"] == c["id"] and m["status"] == "PENDING":
                m["status"] = "DENIED"
                db.touch(m)
        db.touch(c)
    return object_response(public(c), 200)


# ===========================================================================
# Means tests (PRD 3.2)
# ===========================================================================

@app.route("/means-tests", methods=["POST"])
def create_means_test():
    _, role = get_auth()
    authorize(role, {"Debtor"})
    body = get_body()
    case_id = body.get("case_id")
    if not isinstance(case_id, str) or case_id == "":
        invalid("Field case_id must be a non-empty string.")
    with db.lock:
        case = require_fk(db.cases, case_id)
        cmi = require_int(body, "cmi_monthly_cents", minimum=0)
        expenses = require_int(body, "monthly_expenses_cents", minimum=0)
        median = require_int(body, "median_annual_income_cents", minimum=0)

        computed = services.compute_means_test(cmi, expenses, median)

        # At most one means test per case; resubmitting replaces it.
        existing = next((m for m in db.means_tests.values() if m["case_id"] == case_id), None)
        if existing is not None:
            existing["cmi_monthly_cents"] = cmi
            existing["monthly_expenses_cents"] = expenses
            existing["median_annual_income_cents"] = median
            existing["annualized_cmi_cents"] = computed["annualized_cmi_cents"]
            existing["disposable_monthly_cents"] = computed["disposable_monthly_cents"]
            existing["result"] = computed["result"]
            db.touch(existing)
            mt = existing
        else:
            mt = {
                "id": db.new_id(),
                "case_id": case_id,
                "cmi_monthly_cents": cmi,
                "monthly_expenses_cents": expenses,
                "median_annual_income_cents": median,
                "annualized_cmi_cents": computed["annualized_cmi_cents"],
                "disposable_monthly_cents": computed["disposable_monthly_cents"],
                "result": computed["result"],
            }
            db.stamp_create(mt)
            db.means_tests[mt["id"]] = mt

        # Mirror result onto the case and bump the case version.
        case["means_test_result"] = computed["result"]
        db.touch(case)
    return object_response(public(mt), 201)


@app.route("/means-tests/<rid>", methods=["GET"])
def get_means_test(rid):
    _, role = get_auth()
    authorize(role, {"BankruptcyAdmin", "Debtor", "Trustee"})
    mt = require_path(db.means_tests, rid)
    return object_response(public(mt), 200)


@app.route("/means-tests", methods=["GET"])
def list_means_tests():
    _, role = get_auth()
    authorize(role, {"BankruptcyAdmin", "Debtor", "Trustee"})
    limit, offset = parse_pagination()
    case_id = request.args.get("case_id")
    items = list(db.means_tests.values())
    if case_id is not None:
        items = [m for m in items if m["case_id"] == case_id]
    window, total = paginate(items, limit, offset)
    return array_response([public(m) for m in window], limit, offset, total)


# ===========================================================================
# 341 meetings (PRD 3.5)
# ===========================================================================

@app.route("/meetings", methods=["POST"])
def create_meeting():
    _, role = get_auth()
    authorize(role, {"Trustee"})
    body = get_body()
    case_id = body.get("case_id")
    if not isinstance(case_id, str) or case_id == "":
        invalid("Field case_id must be a non-empty string.")
    trustee_id = body.get("trustee_id")
    if not isinstance(trustee_id, str) or trustee_id == "":
        invalid("Field trustee_id must be a non-empty string.")
    with db.lock:
        case = require_fk(db.cases, case_id)
        require_fk(db.trustees, trustee_id)
        room_code = require_str(body, "room_code")
        start_raw = require_str(body, "scheduled_start")
        end_raw = require_str(body, "scheduled_end")
        try:
            start_dt = services.parse_dt(start_raw)
            end_dt = services.parse_dt(end_raw)
        except (ValueError, TypeError):
            invalid("scheduled_start / scheduled_end must be ISO 8601 timestamps.")
        if not (end_dt > start_dt):
            invalid("scheduled_end must be strictly after scheduled_start.")

        # State: case must be FILED.
        if case["status"] != "FILED":
            raise err(errors.ERR_INVALID_STATE, "Scheduling a 341 meeting requires the case to be FILED.")

        # Trustee half-open conflict (priority 9) before room buffer (priority 10).
        if services.trustee_conflict(trustee_id, start_dt, end_dt):
            raise err(errors.ERR_TRUSTEE_DOUBLE_BOOKED, "Trustee is double-booked for this slot.")
        if services.room_conflict(room_code, start_dt, end_dt):
            raise err(errors.ERR_ROOM_BUFFER_CONFLICT, "Room buffer conflict for this slot.")

        m = {
            "id": db.new_id(),
            "case_id": case_id,
            "trustee_id": trustee_id,
            "room_code": room_code,
            "scheduled_start": start_raw,
            "scheduled_end": end_raw,
            "status": "SCHEDULED",
        }
        db.stamp_create(m)
        db.meetings[m["id"]] = m
    return object_response(public(m), 201)


@app.route("/meetings/<rid>", methods=["GET"])
def get_meeting(rid):
    _, role = get_auth()
    authorize(role, {"BankruptcyAdmin", "Debtor", "Trustee", "Creditor"})
    m = require_path(db.meetings, rid)
    return object_response(public(m), 200)


@app.route("/meetings", methods=["GET"])
def list_meetings():
    _, role = get_auth()
    authorize(role, {"BankruptcyAdmin", "Debtor", "Trustee", "Creditor"})
    limit, offset = parse_pagination()
    case_id = request.args.get("case_id")
    trustee_id = request.args.get("trustee_id")
    status = request.args.get("status")
    items = list(db.meetings.values())
    if case_id is not None:
        items = [m for m in items if m["case_id"] == case_id]
    if trustee_id is not None:
        items = [m for m in items if m["trustee_id"] == trustee_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    window, total = paginate(items, limit, offset)
    return array_response([public(m) for m in window], limit, offset, total)


@app.route("/meetings/<rid>/hold", methods=["POST"])
def hold_meeting(rid):
    user_id, role = get_auth()
    authorize(role, {"Trustee"})
    with db.lock:
        m = require_path(db.meetings, rid)
        case = db.cases.get(m["case_id"])
        if m["status"] != "SCHEDULED":
            raise err(errors.ERR_INVALID_STATE, "Meeting is not SCHEDULED.")
        if case is None or case["status"] != "FILED":
            raise err(errors.ERR_INVALID_STATE, "Holding the meeting requires the case to be FILED.")
        # Only the assigned trustee may chair it (PRD 2.1 / 3.5).
        if user_id != m["trustee_id"]:
            raise err(errors.ERR_UNAUTHORIZED, "Only the assigned trustee may conduct this meeting.")
        m["status"] = "HELD"
        db.touch(m)
        # Bubble up: Case FILED -> MEETING_HELD.
        case["status"] = "MEETING_HELD"
        db.touch(case)
    return object_response(public(m), 200)


# ===========================================================================
# Schedules A-J (PRD 3.3)
# ===========================================================================

@app.route("/schedules", methods=["POST"])
def create_schedule():
    _, role = get_auth()
    authorize(role, {"Debtor"})
    body = get_body()
    case_id = body.get("case_id")
    if not isinstance(case_id, str) or case_id == "":
        invalid("Field case_id must be a non-empty string.")
    with db.lock:
        case = require_fk(db.cases, case_id)
        letter = require_enum(body, "schedule_letter", SCHEDULE_LETTERS)
        description = require_str(body, "description")
        asset_value = optional_int(body, "asset_value_cents", default=0, minimum=0)
        claimed_exempt = optional_int(body, "claimed_exempt_value_cents", default=0, minimum=0)

        # Schedule C over-exemption guard (priority 14).
        if letter == "C":
            gross = services.gross_asset_cents(case_id)
            if claimed_exempt > gross:
                raise err(
                    errors.ERR_EXEMPTION_EXCEEDS_ASSET,
                    "Claimed exemption exceeds the case's gross scheduled asset value.",
                )

        s = {
            "id": db.new_id(),
            "case_id": case_id,
            "schedule_letter": letter,
            "description": description,
            "asset_value_cents": asset_value,
            "claimed_exempt_value_cents": claimed_exempt,
        }
        db.stamp_create(s)
        db.schedules[s["id"]] = s

        # Recompute derived case fields and bump case version.
        services.recompute_estate_fields(case)
        db.touch(case)
    return object_response(public(s), 201)


@app.route("/schedules/<rid>", methods=["GET"])
def get_schedule(rid):
    _, role = get_auth()
    authorize(role, {"BankruptcyAdmin", "Debtor", "Trustee", "Creditor"})
    s = require_path(db.schedules, rid)
    return object_response(public(s), 200)


@app.route("/schedules", methods=["GET"])
def list_schedules():
    _, role = get_auth()
    authorize(role, {"BankruptcyAdmin", "Debtor", "Trustee", "Creditor"})
    limit, offset = parse_pagination()
    case_id = request.args.get("case_id")
    letter = request.args.get("schedule_letter")
    items = list(db.schedules.values())
    if case_id is not None:
        items = [s for s in items if s["case_id"] == case_id]
    if letter is not None:
        items = [s for s in items if s["schedule_letter"] == letter]
    window, total = paginate(items, limit, offset)
    return array_response([public(s) for s in window], limit, offset, total)


# ===========================================================================
# Debts (PRD 3.3)
# ===========================================================================

@app.route("/debts", methods=["POST"])
def create_debt():
    _, role = get_auth()
    authorize(role, {"Debtor"})
    body = get_body()
    case_id = body.get("case_id")
    if not isinstance(case_id, str) or case_id == "":
        invalid("Field case_id must be a non-empty string.")
    creditor_id = body.get("creditor_id")
    if not isinstance(creditor_id, str) or creditor_id == "":
        invalid("Field creditor_id must be a non-empty string.")
    with db.lock:
        require_fk(db.cases, case_id)
        require_fk(db.creditors, creditor_id)
        debt_class = require_enum(body, "debt_class", DEBT_CLASSES)
        scheduled = require_int(body, "scheduled_amount_cents", minimum=1)

        d = {
            "id": db.new_id(),
            "case_id": case_id,
            "creditor_id": creditor_id,
            "debt_class": debt_class,
            "scheduled_amount_cents": scheduled,
            # Until a claim is adjudicated, allowed equals scheduled (PRD 3.3).
            "allowed_amount_cents": scheduled,
        }
        db.stamp_create(d)
        db.debts[d["id"]] = d
    return object_response(public(d), 201)


@app.route("/debts/<rid>", methods=["GET"])
def get_debt(rid):
    _, role = get_auth()
    authorize(role, {"BankruptcyAdmin", "Debtor", "Trustee", "Creditor"})
    d = require_path(db.debts, rid)
    return object_response(public(d), 200)


@app.route("/debts", methods=["GET"])
def list_debts():
    _, role = get_auth()
    authorize(role, {"BankruptcyAdmin", "Debtor", "Trustee", "Creditor"})
    limit, offset = parse_pagination()
    case_id = request.args.get("case_id")
    creditor_id = request.args.get("creditor_id")
    debt_class = request.args.get("debt_class")
    items = list(db.debts.values())
    if case_id is not None:
        items = [d for d in items if d["case_id"] == case_id]
    if creditor_id is not None:
        items = [d for d in items if d["creditor_id"] == creditor_id]
    if debt_class is not None:
        items = [d for d in items if d["debt_class"] == debt_class]
    window, total = paginate(items, limit, offset)
    return array_response([public(d) for d in window], limit, offset, total)


# ===========================================================================
# Claims / proofs of claim (PRD 3.6)
# ===========================================================================

@app.route("/claims", methods=["POST"])
def create_claim():
    _, role = get_auth()
    authorize(role, {"Creditor"})
    body = get_body()
    case_id = body.get("case_id")
    if not isinstance(case_id, str) or case_id == "":
        invalid("Field case_id must be a non-empty string.")
    debt_id = body.get("debt_id")
    if not isinstance(debt_id, str) or debt_id == "":
        invalid("Field debt_id must be a non-empty string.")
    creditor_id = body.get("filed_by_creditor_id")
    if not isinstance(creditor_id, str) or creditor_id == "":
        invalid("Field filed_by_creditor_id must be a non-empty string.")
    with db.lock:
        case = require_fk(db.cases, case_id)
        debt = require_fk(db.debts, debt_id)
        require_fk(db.creditors, creditor_id)
        claimed = require_int(body, "claimed_amount_cents", minimum=1)

        # Stay-termination guard (priority 13) — creditor collection action.
        if case["stay_posture"] == "TERMINATED":
            raise err(errors.ERR_STAY_TERMINATED, "The automatic stay has terminated.")

        # Claim/creditor match (priority 7): filed_by must equal Debt.creditor_id.
        if creditor_id != debt["creditor_id"]:
            raise err(
                errors.ERR_CLAIM_CREDITOR_MISMATCH,
                "A creditor may only file claims on its own scheduled debts.",
            )

        cr = {
            "id": db.new_id(),
            "case_id": case_id,
            "debt_id": debt_id,
            "filed_by_creditor_id": creditor_id,
            "claimed_amount_cents": claimed,
            "status": "FILED",
            "allowed_amount_cents": 0,
        }
        db.stamp_create(cr)
        db.claims[cr["id"]] = cr
    return object_response(public(cr), 201)


@app.route("/claims/<rid>", methods=["GET"])
def get_claim(rid):
    _, role = get_auth()
    authorize(role, {"BankruptcyAdmin", "Debtor", "Trustee", "Creditor"})
    cr = require_path(db.claims, rid)
    return object_response(public(cr), 200)


@app.route("/claims", methods=["GET"])
def list_claims():
    _, role = get_auth()
    authorize(role, {"BankruptcyAdmin", "Debtor", "Trustee", "Creditor"})
    limit, offset = parse_pagination()
    case_id = request.args.get("case_id")
    debt_id = request.args.get("debt_id")
    creditor_id = request.args.get("filed_by_creditor_id")
    status = request.args.get("status")
    items = list(db.claims.values())
    if case_id is not None:
        items = [c for c in items if c["case_id"] == case_id]
    if debt_id is not None:
        items = [c for c in items if c["debt_id"] == debt_id]
    if creditor_id is not None:
        items = [c for c in items if c["filed_by_creditor_id"] == creditor_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    window, total = paginate(items, limit, offset)
    return array_response([public(c) for c in window], limit, offset, total)


def _adjudicate_claim(rid, allow):
    with db.lock:
        cr = require_path(db.claims, rid)
        case = db.cases.get(cr["case_id"])
        if cr["status"] != "FILED":
            raise err(errors.ERR_INVALID_STATE, "Claim is not in FILED.")
        if case is None or case["status"] not in ("MEETING_HELD", "CONFIRMED"):
            raise err(errors.ERR_INVALID_STATE, "Claims are adjudicated only after the 341 meeting.")
        debt = db.debts.get(cr["debt_id"])
        if allow:
            cr["status"] = "ALLOWED"
            cr["allowed_amount_cents"] = cr["claimed_amount_cents"]
        else:
            cr["status"] = "DISALLOWED"
            cr["allowed_amount_cents"] = 0
        db.touch(cr)
        # Cross-aggregate ledger sync onto the linked debt.
        if debt is not None:
            debt["allowed_amount_cents"] = cr["allowed_amount_cents"]
            db.touch(debt)
    return object_response(public(cr), 200)


@app.route("/claims/<rid>/allow", methods=["POST"])
def allow_claim(rid):
    _, role = get_auth()
    authorize(role, {"Trustee"})
    return _adjudicate_claim(rid, allow=True)


@app.route("/claims/<rid>/disallow", methods=["POST"])
def disallow_claim(rid):
    _, role = get_auth()
    authorize(role, {"Trustee"})
    return _adjudicate_claim(rid, allow=False)


# ===========================================================================
# Chapter 13 plans (PRD 3.7)
# ===========================================================================

@app.route("/plans", methods=["POST"])
def create_plan():
    _, role = get_auth()
    authorize(role, {"Debtor"})
    body = get_body()
    case_id = body.get("case_id")
    if not isinstance(case_id, str) or case_id == "":
        invalid("Field case_id must be a non-empty string.")
    with db.lock:
        case = require_fk(db.cases, case_id)
        monthly = require_int(body, "monthly_payment_cents", minimum=1)
        duration = require_int(body, "plan_duration_months", minimum=36, maximum=60)
        expected_version = require_int(body, "expected_case_version")

        # Chapter-13 gate (priority 15) before OCC (priority 18).
        if case["filed_chapter"] != "CHAPTER_13":
            raise err(errors.ERR_NOT_CHAPTER_13, "Plan operations require a CHAPTER_13 case.")

        # OCC on Case.version (priority 18).
        if expected_version != case["version"]:
            raise err(errors.ERR_STALE_CASE_VERSION, "expected_case_version does not match current Case.version.")

        # A new draft plan supersedes the prior active plan.
        prior = services.active_plan(case_id)
        if prior is not None and prior.get("is_active"):
            prior["is_active"] = False
            db.touch(prior)

        p = {
            "id": db.new_id(),
            "case_id": case_id,
            "monthly_payment_cents": monthly,
            "plan_duration_months": duration,
            "status": "DRAFT",
            "is_active": True,
            "total_committed_cents": monthly * duration,
            "paid_to_date_cents": 0,
        }
        db.stamp_create(p)
        db.plans[p["id"]] = p

        # Creating a plan increments the case version.
        db.touch(case)
    return object_response(public(p), 201)


@app.route("/plans/<rid>", methods=["GET"])
def get_plan(rid):
    _, role = get_auth()
    authorize(role, {"BankruptcyAdmin", "Debtor", "Trustee"})
    p = require_path(db.plans, rid)
    return object_response(public(p), 200)


@app.route("/plans", methods=["GET"])
def list_plans():
    _, role = get_auth()
    authorize(role, {"BankruptcyAdmin", "Debtor", "Trustee"})
    limit, offset = parse_pagination()
    case_id = request.args.get("case_id")
    status = request.args.get("status")
    items = list(db.plans.values())
    if case_id is not None:
        items = [p for p in items if p["case_id"] == case_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    window, total = paginate(items, limit, offset)
    return array_response([public(p) for p in window], limit, offset, total)


@app.route("/plans/<rid>/file-plan", methods=["POST"])
def file_plan(rid):
    _, role = get_auth()
    authorize(role, {"Debtor"})
    with db.lock:
        p = require_path(db.plans, rid)
        case = db.cases.get(p["case_id"])
        if case is not None and case["filed_chapter"] != "CHAPTER_13":
            raise err(errors.ERR_NOT_CHAPTER_13, "Plan operations require a CHAPTER_13 case.")
        if p["status"] != "DRAFT" or not p.get("is_active"):
            raise err(errors.ERR_INVALID_STATE, "Only the active DRAFT plan can be filed.")
        if case is None or case["status"] not in ("FILED", "MEETING_HELD"):
            raise err(errors.ERR_INVALID_STATE, "Filing the plan requires the case in FILED or MEETING_HELD.")
        p["status"] = "FILED"
        db.touch(p)
    return object_response(public(p), 200)


@app.route("/plans/<rid>/confirm-plan", methods=["POST"])
def confirm_plan(rid):
    _, role = get_auth()
    authorize(role, {"Trustee"})
    with db.lock:
        p = require_path(db.plans, rid)
        case = db.cases.get(p["case_id"])
        if case is not None and case["filed_chapter"] != "CHAPTER_13":
            raise err(errors.ERR_NOT_CHAPTER_13, "Plan operations require a CHAPTER_13 case.")
        if p["status"] != "FILED":
            raise err(errors.ERR_INVALID_STATE, "Only a FILED plan can be confirmed.")
        if case is None or case["status"] != "MEETING_HELD":
            raise err(errors.ERR_INVALID_STATE, "Plan confirmation requires the case in MEETING_HELD.")
        # Feasibility (priority 16): total_committed >= priority floor.
        floor = services.priority_floor_cents(p["case_id"])
        if p["total_committed_cents"] < floor:
            raise err(errors.ERR_PLAN_INFEASIBLE, "Plan total is below the priority floor.")
        p["status"] = "CONFIRMED"
        db.touch(p)
    return object_response(public(p), 200)


@app.route("/plans/<rid>/deny-plan", methods=["POST"])
def deny_plan(rid):
    _, role = get_auth()
    authorize(role, {"Trustee"})
    with db.lock:
        p = require_path(db.plans, rid)
        if p["status"] != "FILED":
            raise err(errors.ERR_INVALID_STATE, "Only a FILED plan can be denied.")
        p["status"] = "DENIED"
        p["is_active"] = False
        db.touch(p)
    return object_response(public(p), 200)


@app.route("/plans/<rid>/distribution", methods=["GET"])
def plan_distribution(rid):
    _, role = get_auth()
    authorize(role, {"BankruptcyAdmin", "Debtor", "Trustee"})
    p = require_path(db.plans, rid)
    result = services.waterfall_distribution(p)
    return object_response(result, 200)


# ===========================================================================
# Plan payments (PRD 3.8)
# ===========================================================================

@app.route("/plan-payments", methods=["POST"])
def create_plan_payment():
    _, role = get_auth()
    authorize(role, {"Trustee"})
    body = get_body()
    plan_id = body.get("plan_id")
    if not isinstance(plan_id, str) or plan_id == "":
        invalid("Field plan_id must be a non-empty string.")
    with db.lock:
        plan = require_fk(db.plans, plan_id)
        amount = require_int(body, "amount_cents", minimum=1)

        # Overpayment guard (priority 17).
        if plan["paid_to_date_cents"] + amount > plan["total_committed_cents"]:
            raise err(errors.ERR_PLAN_OVERPAYMENT, "Payment would overpay the committed fund.")

        pp = {
            "id": db.new_id(),
            "plan_id": plan_id,
            "amount_cents": amount,
            "applied_at": db.now_iso(),
        }
        db.stamp_create(pp)
        db.plan_payments[pp["id"]] = pp

        plan["paid_to_date_cents"] += amount
        db.touch(plan)
    return object_response(public(pp), 201)


@app.route("/plan-payments/<rid>", methods=["GET"])
def get_plan_payment(rid):
    _, role = get_auth()
    authorize(role, {"BankruptcyAdmin", "Debtor", "Trustee"})
    pp = require_path(db.plan_payments, rid)
    return object_response(public(pp), 200)


@app.route("/plan-payments", methods=["GET"])
def list_plan_payments():
    _, role = get_auth()
    authorize(role, {"BankruptcyAdmin", "Debtor", "Trustee"})
    limit, offset = parse_pagination()
    plan_id = request.args.get("plan_id")
    items = list(db.plan_payments.values())
    if plan_id is not None:
        items = [pp for pp in items if pp["plan_id"] == plan_id]
    window, total = paginate(items, limit, offset)
    return array_response([public(pp) for pp in window], limit, offset, total)


# ===========================================================================
# Stay relief motions (PRD 3.9)
# ===========================================================================

@app.route("/stay-relief-motions", methods=["POST"])
def create_motion():
    _, role = get_auth()
    authorize(role, {"Creditor"})
    body = get_body()
    case_id = body.get("case_id")
    if not isinstance(case_id, str) or case_id == "":
        invalid("Field case_id must be a non-empty string.")
    creditor_id = body.get("movant_creditor_id")
    if not isinstance(creditor_id, str) or creditor_id == "":
        invalid("Field movant_creditor_id must be a non-empty string.")
    debt_id = body.get("target_debt_id")
    if not isinstance(debt_id, str) or debt_id == "":
        invalid("Field target_debt_id must be a non-empty string.")
    with db.lock:
        case = require_fk(db.cases, case_id)
        require_fk(db.creditors, creditor_id)
        debt = require_fk(db.debts, debt_id)

        # Stay-termination guard (priority 13) — creditor collection action.
        if case["stay_posture"] == "TERMINATED":
            raise err(errors.ERR_STAY_TERMINATED, "The automatic stay has terminated.")

        # Relief target must be SECURED (priority 8).
        if debt["debt_class"] != "SECURED":
            raise err(errors.ERR_RELIEF_TARGET_NOT_SECURED, "Relief target debt must be SECURED.")

        m = {
            "id": db.new_id(),
            "case_id": case_id,
            "movant_creditor_id": creditor_id,
            "target_debt_id": debt_id,
            "status": "PENDING",
        }
        db.stamp_create(m)
        db.stay_relief_motions[m["id"]] = m
    return object_response(public(m), 201)


@app.route("/stay-relief-motions/<rid>", methods=["GET"])
def get_motion(rid):
    _, role = get_auth()
    authorize(role, {"BankruptcyAdmin", "Debtor", "Trustee", "Creditor"})
    m = require_path(db.stay_relief_motions, rid)
    return object_response(public(m), 200)


@app.route("/stay-relief-motions", methods=["GET"])
def list_motions():
    _, role = get_auth()
    authorize(role, {"BankruptcyAdmin", "Debtor", "Trustee", "Creditor"})
    limit, offset = parse_pagination()
    case_id = request.args.get("case_id")
    creditor_id = request.args.get("movant_creditor_id")
    debt_id = request.args.get("target_debt_id")
    status = request.args.get("status")
    items = list(db.stay_relief_motions.values())
    if case_id is not None:
        items = [m for m in items if m["case_id"] == case_id]
    if creditor_id is not None:
        items = [m for m in items if m["movant_creditor_id"] == creditor_id]
    if debt_id is not None:
        items = [m for m in items if m["target_debt_id"] == debt_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    window, total = paginate(items, limit, offset)
    return array_response([public(m) for m in window], limit, offset, total)


@app.route("/stay-relief-motions/<rid>/grant", methods=["POST"])
def grant_motion(rid):
    _, role = get_auth()
    authorize(role, {"Trustee"})
    with db.lock:
        m = require_path(db.stay_relief_motions, rid)
        case = db.cases.get(m["case_id"])
        if m["status"] != "PENDING":
            raise err(errors.ERR_INVALID_STATE, "Motion is not PENDING.")
        if case is None or case["stay_posture"] not in ("ACTIVE", "LIFTED_PARTIAL"):
            raise err(errors.ERR_INVALID_STATE, "The stay must still be in force to be lifted.")
        debt = db.debts.get(m["target_debt_id"])
        if debt is None or debt["debt_class"] != "SECURED":
            raise err(errors.ERR_RELIEF_TARGET_NOT_SECURED, "Relief target debt must be SECURED.")
        m["status"] = "GRANTED"
        db.touch(m)
        # Cascade: case posture -> LIFTED_PARTIAL, case version bumps.
        case["stay_posture"] = "LIFTED_PARTIAL"
        db.touch(case)
    return object_response(public(m), 200)


@app.route("/stay-relief-motions/<rid>/deny", methods=["POST"])
def deny_motion(rid):
    _, role = get_auth()
    authorize(role, {"Trustee"})
    with db.lock:
        m = require_path(db.stay_relief_motions, rid)
        if m["status"] != "PENDING":
            raise err(errors.ERR_INVALID_STATE, "Motion is not PENDING.")
        m["status"] = "DENIED"
        db.touch(m)
    return object_response(public(m), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
