"""Routes: logical clock, payment simulator, editions, category configs,
submitters, programmers."""

from flask import Blueprint

import domain as D
from errors import (err409, err_invalid_state, err_not_found, err_phase,
                    err_referential, err_validation)
from store import DB
from util import (AUTHENTICATED_ROLES, auth, check_ownership, created_key,
                  get_body, get_or_404, ok, paginate, parse_dt, require_role,
                  v_arr, v_bool, v_date, v_dt, v_enum, v_int, v_str)

bp = Blueprint("editions", __name__)

ADMIN = ["FESTIVAL_ADMIN"]


# ------------------------------------------------------------- test driving
@bp.post("/festival/_clock/set_current_utc")
def set_clock():
    body = get_body()
    raw = v_str(body, "to_iso8601")
    target = parse_dt(raw, "to_iso8601")
    uid, role = auth()
    require_role(role, ADMIN)
    DB.clock = target
    DB.clock_raw = raw
    D.run_sweeps()
    return ok({"current_utc": DB.clock_raw})


@bp.post("/festival/_payments/simulate")
def simulate_payment():
    body = get_body()
    payment_id = v_str(body, "fee_payment_id")
    outcome = v_enum(body, "outcome", ["SUCCEEDED", "FAILED"])
    uid, role = auth()
    require_role(role, ADMIN)
    payment = DB.fee_payments.get(payment_id)
    if payment is None:
        raise err_referential("Fee payment not found")
    if payment["status"] != "INITIATED":
        raise err_invalid_state("Payment is not INITIATED")
    if outcome == "SUCCEEDED":
        payment["status"] = "SUCCEEDED"
        payment["paid_at"] = D.now()
        D.touch(payment)
        sub = DB.submissions.get(payment["submission_id"])
        if sub is not None and sub["status"] == "DRAFT":
            sub["status"] = "SUBMITTED"
            sub["payment_status"] = "PAID"
            D.touch(sub)
        edition = DB.editions.get(sub["edition_id"]) if sub else None
        if edition is not None:
            D.recompute_edition_ledger(edition)
    else:
        payment["status"] = "FAILED"
        D.touch(payment)
        sub = DB.submissions.get(payment["submission_id"])
        edition = DB.editions.get(sub["edition_id"]) if sub else None
        if edition is not None:
            D.recompute_edition_ledger(edition)
    return ok(D.ser_payment(payment))


# ------------------------------------------------------------------ editions
@bp.post("/festival/editions")
def create_edition():
    body = get_body()
    year = v_int(body, "year")
    intake_open_at = v_dt(body, "intake_open_at")
    early_deadline_at = v_dt(body, "early_deadline_at")
    regular_deadline_at = v_dt(body, "regular_deadline_at")
    late_deadline_at = v_dt(body, "late_deadline_at")
    festival_start_at = v_dt(body, "festival_start_at")
    festival_end_at = v_dt(body, "festival_end_at")
    hotel_nights_pool = v_int(body, "hotel_nights_pool")
    travel_budget_cents = v_int(body, "travel_budget_cents")
    prize_pool_cents = v_int(body, "prize_pool_cents")
    host_country_code = v_str(body, "host_country_code", required=False) or "US"
    rsvp_window_days = v_int(body, "rsvp_window_days", required=False)
    if rsvp_window_days is None:
        rsvp_window_days = 7
    uid, role = auth()
    require_role(role, ADMIN)
    if any(e["year"] == year for e in DB.editions.values()):
        raise err409("ERR_DUPLICATE_EDITION",
                     "An edition with this year already exists")
    rec = D.new_rec({
        "year": year, "host_country_code": host_country_code,
        "intake_open_at": intake_open_at, "early_deadline_at": early_deadline_at,
        "regular_deadline_at": regular_deadline_at,
        "late_deadline_at": late_deadline_at,
        "rsvp_window_days": rsvp_window_days,
        "festival_start_at": festival_start_at,
        "festival_end_at": festival_end_at,
        "hotel_nights_pool": hotel_nights_pool,
        "travel_budget_cents": travel_budget_cents,
        "prize_pool_cents": prize_pool_cents,
        "status": "SETUP",
        "total_fees_collected_cents": 0, "total_refunded_cents": 0,
        "hotel_nights_allocated": 0, "hotel_nights_remaining": hotel_nights_pool,
        "travel_committed_cents": 0, "travel_penalty_sink_cents": 0,
        "travel_budget_remaining": travel_budget_cents,
        "prize_committed_cents": 0, "prize_disbursed_cents": 0,
    })
    DB.editions[rec["id"]] = rec
    return ok(D.ser_edition(rec), 201)


@bp.get("/festival/editions/<eid>")
def get_edition(eid):
    uid, role = auth()
    require_role(role, AUTHENTICATED_ROLES)
    edition = get_or_404(DB.editions, eid)
    return ok(D.ser_edition(edition))


@bp.post("/festival/editions/<eid>/advance")
def advance_edition(eid):
    body = get_body()
    to_status = v_enum(body, "to_status", D.EDITION_STATUSES)
    uid, role = auth()
    require_role(role, ADMIN)
    edition = get_or_404(DB.editions, eid)
    current = edition["status"]
    idx = D.EDITION_STATUSES.index(current)
    expected_next = (D.EDITION_STATUSES[idx + 1]
                     if idx + 1 < len(D.EDITION_STATUSES) else None)
    if to_status != expected_next:
        raise err_invalid_state(
            "Cannot advance edition from %s to %s" % (current, to_status))

    if current == "SETUP" and to_status == "INTAKE_OPEN":
        if not any(c["edition_id"] == eid for c in DB.category_configs.values()):
            raise err409("ERR_NO_CATEGORY_CONFIG",
                         "At least one category config is required")

    elif current == "INTAKE_CLOSED" and to_status == "SCREENING":
        for s in sorted(DB.submissions.values(), key=lambda x: x["_seq"]):
            if s["edition_id"] == eid and s["status"] == "ELIGIBLE":
                s["status"] = "IN_SCREENING"
                D.touch(s)

    elif current == "SCREENING" and to_status == "DELIBERATION":
        subs = [s for s in DB.submissions.values() if s["edition_id"] == eid]
        if any(s["status"] in ("SUBMITTED", "NEEDS_INFO") for s in subs):
            raise err409("ERR_ELIGIBILITY_DECISIONS_PENDING",
                         "Submissions remain SUBMITTED or NEEDS_INFO")
        for s in subs:
            if s["status"] != "IN_SCREENING":
                continue
            config = D.category_config_for(eid, s["category"])
            required = config["screener_count_required"] if config else 3
            scored = sum(1 for a in DB.assignments.values()
                         if a["submission_id"] == s["id"]
                         and a["status"] == "SCORED")
            if scored < required:
                raise err409("ERR_SCORING_INCOMPLETE",
                             "An IN_SCREENING submission lacks scored assignments")
        # Pin the deliberation record: lock every score of this edition.
        sub_ids = {s["id"] for s in subs}
        assignment_ids = {a["id"] for a in DB.assignments.values()
                          if a["submission_id"] in sub_ids}
        for sc in DB.scores.values():
            if sc["assignment_id"] in assignment_ids and not sc["locked"]:
                sc["locked"] = True
                D.touch(sc)

    elif current == "DELIBERATION" and to_status == "SLATE_LOCKED":
        slates = [s for s in DB.slates.values() if s["edition_id"] == eid]
        if not slates or any(s["status"] != "LOCKED" for s in slates):
            raise err409("ERR_SLATES_UNLOCKED",
                         "Every slate must be LOCKED (and at least one must exist)")

    elif current == "NOTIFICATION" and to_status == "SCHEDULING":
        slate_ids = {s["id"] for s in DB.slates.values()
                     if s["edition_id"] == eid}
        if any(e["slate_id"] in slate_ids and e["status"] == "INVITED"
               for e in DB.entries.values()):
            raise err409("ERR_INVITATIONS_PENDING",
                         "Invitations remain unanswered")

    elif current == "SCHEDULING" and to_status == "FESTIVAL_LIVE":
        if D.now() < edition["festival_start_at"]:
            raise err409("ERR_FESTIVAL_NOT_STARTED",
                         "The festival has not started yet")
        # Close out the waitlist: WAITLISTED -> DECLINED; entry -> RELEASED.
        for s in sorted(DB.submissions.values(), key=lambda x: x["_seq"]):
            if s["edition_id"] == eid and s["status"] == "WAITLISTED":
                s["status"] = "DECLINED"
                D.touch(s)
                for e in DB.entries.values():
                    if (e["submission_id"] == s["id"]
                            and e["status"] == "NOMINATED"):
                        e["status"] = "RELEASED"
                        D.touch(e)

    elif current == "AWARDS_NIGHT" and to_status == "CLOSED":
        if any(a["edition_id"] == eid and a["status"] != "DISBURSED"
               for a in DB.awards.values()):
            raise err409("ERR_AWARDS_PENDING",
                         "Every award must be DISBURSED before closing")

    edition["status"] = to_status
    D.touch(edition)
    return ok(D.ser_edition(edition))


# ----------------------------------------------------------- category configs
@bp.post("/festival/category-configs")
def create_category_config():
    body = get_body()
    edition_id = v_str(body, "edition_id")
    category = v_enum(body, "category", D.CATEGORIES)
    min_rt = v_int(body, "min_runtime_minutes")
    max_rt = v_int(body, "max_runtime_minutes")
    premiere_requirement = v_enum(body, "premiere_requirement",
                                  D.PREMIERE_REQUIREMENTS)
    completion_cutoff = v_date(body, "completion_cutoff")
    early_fee = v_int(body, "early_fee_cents")
    regular_fee = v_int(body, "regular_fee_cents")
    late_fee = v_int(body, "late_fee_cents")
    scr = v_int(body, "screener_count_required", required=False)
    if scr is None:
        scr = 3
    uid, role = auth()
    require_role(role, ADMIN)
    if edition_id not in DB.editions:
        raise err_referential("Edition not found")
    if D.category_config_for(edition_id, category) is not None:
        raise err409("ERR_DUPLICATE_CATEGORY_CONFIG",
                     "Category config already exists for this edition")
    rec = D.new_rec({
        "edition_id": edition_id, "category": category,
        "min_runtime_minutes": min_rt, "max_runtime_minutes": max_rt,
        "premiere_requirement": premiere_requirement,
        "completion_cutoff": completion_cutoff,
        "early_fee_cents": early_fee, "regular_fee_cents": regular_fee,
        "late_fee_cents": late_fee, "screener_count_required": scr,
    })
    DB.category_configs[rec["id"]] = rec
    return ok(D.ser_category_config(rec), 201)


@bp.get("/festival/editions/<eid>/category-configs")
def list_category_configs(eid):
    uid, role = auth()
    require_role(role, AUTHENTICATED_ROLES)
    get_or_404(DB.editions, eid)
    items = sorted((c for c in DB.category_configs.values()
                    if c["edition_id"] == eid), key=created_key)
    page, meta = paginate(items)
    return ok([D.ser_category_config(c) for c in page], pagination=meta)


# ----------------------------------------------------------------- submitters
@bp.post("/festival/submitters")
def create_submitter():
    body = get_body()
    legal_name = v_str(body, "legal_name")
    email = v_str(body, "email")
    country = v_str(body, "country_of_residence")
    is_student = v_bool(body, "is_student", required=False)
    is_member = v_bool(body, "is_member", required=False)
    uid, role = auth()
    require_role(role, ["PUBLIC"])
    if any(s["email"] == email for s in DB.submitters.values()):
        raise err409("ERR_DUPLICATE_EMAIL", "Email already registered")
    rec = D.new_rec({
        "legal_name": legal_name, "email": email,
        "country_of_residence": country,
        "is_student": bool(is_student) if is_student is not None else False,
        "is_member": bool(is_member) if is_member is not None else False,
    })
    DB.submitters[rec["id"]] = rec
    return ok(D.ser_submitter(rec), 201)


@bp.get("/festival/submitters/<sid>")
def get_submitter(sid):
    uid, role = auth()
    require_role(role, ["FESTIVAL_ADMIN", "FILMMAKER"])
    rec = get_or_404(DB.submitters, sid)
    if role == "FILMMAKER":
        check_ownership(uid == sid)
    return ok(D.ser_submitter(rec))


# ---------------------------------------------------------------- programmers
@bp.post("/festival/programmers")
def create_programmer():
    body = get_body()
    display_name = v_str(body, "display_name")
    email = v_str(body, "email")
    seniority = v_enum(body, "seniority", D.SENIORITIES)
    categories_covered = v_arr(body, "categories_covered",
                               item_enum=D.CATEGORIES)
    coi = v_arr(body, "coi_production_companies", required=False) or []
    max_active = v_int(body, "max_active_assignments", required=False)
    if max_active is None:
        max_active = 12
    active = v_bool(body, "active", required=False)
    if active is None:
        active = True
    uid, role = auth()
    require_role(role, ADMIN)
    if any(p["email"] == email for p in DB.programmers.values()):
        raise err409("ERR_DUPLICATE_EMAIL", "Email already registered")
    rec = D.new_rec({
        "display_name": display_name, "email": email, "seniority": seniority,
        "categories_covered": list(categories_covered),
        "coi_production_companies": list(coi),
        "max_active_assignments": max_active, "active": active,
    })
    DB.programmers[rec["id"]] = rec
    return ok(D.ser_programmer(rec), 201)


@bp.get("/festival/programmers/<pid>")
def get_programmer(pid):
    uid, role = auth()
    require_role(role, ["FESTIVAL_ADMIN", "PROGRAM_CHAIR", "PROGRAMMER"])
    rec = get_or_404(DB.programmers, pid)
    return ok(D.ser_programmer(rec))


@bp.patch("/festival/programmers/<pid>")
def patch_programmer(pid):
    body = get_body()
    active = v_bool(body, "active", required=False)
    categories_covered = v_arr(body, "categories_covered", required=False,
                               item_enum=D.CATEGORIES)
    max_active = v_int(body, "max_active_assignments", required=False)
    coi = v_arr(body, "coi_production_companies", required=False)
    uid, role = auth()
    require_role(role, ADMIN)
    rec = get_or_404(DB.programmers, pid)
    was_active = rec["active"]
    if categories_covered is not None:
        rec["categories_covered"] = list(categories_covered)
    if max_active is not None:
        rec["max_active_assignments"] = max_active
    if coi is not None:
        rec["coi_production_companies"] = list(coi)
    if active is not None:
        rec["active"] = active
    D.touch(rec)
    # Deactivation recuses every open assignment and runs the replacement
    # selector for each (§3.1 / §3.4).
    if was_active and rec["active"] is False:
        for a in sorted(DB.assignments.values(), key=lambda x: x["_seq"]):
            if a["programmer_id"] == pid and a["status"] == "ASSIGNED":
                a["status"] = "RECUSED"
                D.touch(a)
                sub = DB.submissions.get(a["submission_id"])
                if sub is not None:
                    D.replacement_cascade(sub, a)
    return ok(D.ser_programmer(rec))
