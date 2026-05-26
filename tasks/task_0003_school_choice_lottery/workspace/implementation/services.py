"""Business-logic services: CRUD, state machines, and cascades.

These functions assume the caller has already enforced auth and RBAC
(via routes). They raise ApiError on business-rule violations.
"""
from __future__ import annotations

import re
from datetime import timedelta

from db import store, new_id, utc_now_iso, parse_iso8601, fmt_iso
from errors import (
    ApiError,
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_WINDOW_TIMING,
    ERR_DISTRICT_ARCHIVED,
    ERR_DUPLICATE_CHOICE,
    ERR_GRADE_OUT_OF_RANGE,
    ERR_STALE_VERSION,
    ERR_INVALID_REQUEST,
    ERR_DISTRICT_DATA_INVALID,
    ERR_FORBIDDEN_OWNERSHIP,
)
from calculations import (
    compute_lottery_weight,
    compute_family_risk_score,
    assign_lottery_ranks,
)


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------

_CODE_RE_DISTRICT = re.compile(r"^[A-Z0-9]{3,8}$")
_CODE_RE_SCHOOL = re.compile(r"^[A-Z0-9]{3,12}$")
_CODE_RE_ZONE = re.compile(r"^[A-Z0-9]{3,10}$")


def _now() -> str:
    return utc_now_iso()


def _common_create() -> dict:
    ts = _now()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def _bump(entity: dict):
    entity["updated_at"] = _now()
    if "version" in entity:
        entity["version"] = entity["version"] + 1


def _require(d, kind: str) -> dict:
    if d is None:
        raise_err(ERR_NOT_FOUND, f"{kind} not found")
    return d


def _clock_now():
    """Returns the current logical clock (datetime, UTC). Falls back to wall clock
    when /_clock/set_current_utc has never been called."""
    from datetime import datetime, timezone
    return store.clock_current_utc or datetime.now(timezone.utc)


def _require_body_dict(body):
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")


def _require_present(body: dict, keys: list[str]):
    for k in keys:
        if k not in body:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {k}")


def _serialize(entity: dict) -> dict:
    """Return a shallow copy suitable for JSON."""
    return dict(entity)


# ---------------------------------------------------------------------------
# District
# ---------------------------------------------------------------------------

def create_district(body) -> dict:
    _require_body_dict(body)
    _require_present(body, ["code", "name", "poverty_index_pct"])
    code = body["code"]
    name = body["name"]
    pov = body["poverty_index_pct"]
    if not isinstance(code, str) or not _CODE_RE_DISTRICT.match(code):
        raise_err(ERR_INVALID_REQUEST, "code must be uppercase alphanumeric, 3-8 chars")
    if not isinstance(name, str) or not name:
        raise_err(ERR_INVALID_REQUEST, "name must be a non-empty string")
    if not isinstance(pov, (int, float)) or isinstance(pov, bool):
        raise_err(ERR_INVALID_REQUEST, "poverty_index_pct must be a number")
    if pov < 0 or pov > 100:
        raise_err(ERR_DISTRICT_DATA_INVALID, "poverty_index_pct must be in [0, 100]")
    # Uniqueness on code
    for d in store.districts.values():
        if d["code"] == code:
            raise_err(ERR_INVALID_REQUEST, f"district code {code!r} already exists")

    d = _common_create()
    d.update({
        "code": code,
        "name": name,
        "poverty_index_pct": pov,
        "status": "ACTIVE",
    })
    store.districts[d["id"]] = d
    return _serialize(d)


def get_district(did: str) -> dict:
    return _serialize(_require(store.districts.get(did), "district"))


def list_districts(status):
    items = list(store.districts.values())
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items.sort(key=lambda d: d["created_at"])
    return [_serialize(x) for x in items]


def patch_district(did: str, body) -> dict:
    d = _require(store.districts.get(did), "district")
    _require_body_dict(body)
    if "poverty_index_pct" in body:
        pov = body["poverty_index_pct"]
        if not isinstance(pov, (int, float)) or isinstance(pov, bool):
            raise_err(ERR_INVALID_REQUEST, "poverty_index_pct must be a number")
        if pov < 0 or pov > 100:
            raise_err(ERR_DISTRICT_DATA_INVALID, "poverty_index_pct must be in [0, 100]")
        d["poverty_index_pct"] = pov
    if "status" in body:
        st = body["status"]
        if st not in ("ACTIVE", "ARCHIVED"):
            raise_err(ERR_INVALID_REQUEST, "status must be ACTIVE or ARCHIVED")
        d["status"] = st
    _bump(d)
    return _serialize(d)


# ---------------------------------------------------------------------------
# School
# ---------------------------------------------------------------------------

def create_school(body) -> dict:
    _require_body_dict(body)
    _require_present(body, ["district_id", "code", "name", "school_type", "grade_min", "grade_max", "total_seats"])
    did = body["district_id"]
    code = body["code"]
    name = body["name"]
    st = body["school_type"]
    gmin = body["grade_min"]
    gmax = body["grade_max"]
    seats = body["total_seats"]

    district = _require(store.districts.get(did), "district")
    if district["status"] != "ACTIVE":
        raise_err(ERR_DISTRICT_ARCHIVED, "Referenced district is ARCHIVED")
    if not isinstance(code, str) or not _CODE_RE_SCHOOL.match(code):
        raise_err(ERR_INVALID_REQUEST, "code must be uppercase alphanumeric, 3-12 chars")
    if not isinstance(name, str) or not name:
        raise_err(ERR_INVALID_REQUEST, "name must be a non-empty string")
    if st not in ("NEIGHBORHOOD", "MAGNET"):
        raise_err(ERR_INVALID_REQUEST, "school_type must be NEIGHBORHOOD or MAGNET")
    if not isinstance(gmin, int) or isinstance(gmin, bool):
        raise_err(ERR_INVALID_REQUEST, "grade_min must be an integer")
    if not isinstance(gmax, int) or isinstance(gmax, bool):
        raise_err(ERR_INVALID_REQUEST, "grade_max must be an integer")
    if gmin < 0 or gmax > 12 or gmin > gmax:
        raise_err(ERR_INVALID_REQUEST, "grade range invalid (0<=grade_min<=grade_max<=12)")
    if not isinstance(seats, int) or isinstance(seats, bool):
        raise_err(ERR_INVALID_REQUEST, "total_seats must be an integer")
    if seats < 0:
        raise_err(ERR_INVALID_REQUEST, "total_seats must be >= 0")
    # Uniqueness on (district_id, code)
    for s in store.schools.values():
        if s["district_id"] == did and s["code"] == code:
            raise_err(ERR_INVALID_REQUEST, f"school code {code!r} already exists in district")

    s = _common_create()
    s.update({
        "district_id": did,
        "code": code,
        "name": name,
        "school_type": st,
        "grade_min": gmin,
        "grade_max": gmax,
        "total_seats": seats,
    })
    store.schools[s["id"]] = s
    return _serialize(s)


def get_school(sid: str) -> dict:
    return _serialize(_require(store.schools.get(sid), "school"))


def list_schools(district_id, school_type):
    items = list(store.schools.values())
    if district_id is not None:
        items = [s for s in items if s["district_id"] == district_id]
    if school_type is not None:
        items = [s for s in items if s["school_type"] == school_type]
    items.sort(key=lambda s: s["created_at"])
    return [_serialize(x) for x in items]


def patch_school(sid: str, body) -> dict:
    s = _require(store.schools.get(sid), "school")
    _require_body_dict(body)
    if "name" in body:
        nm = body["name"]
        if not isinstance(nm, str) or not nm:
            raise_err(ERR_INVALID_REQUEST, "name must be a non-empty string")
        s["name"] = nm
    if "total_seats" in body:
        seats = body["total_seats"]
        if not isinstance(seats, int) or isinstance(seats, bool):
            raise_err(ERR_INVALID_REQUEST, "total_seats must be an integer")
        if seats < 0:
            raise_err(ERR_INVALID_REQUEST, "total_seats must be >= 0")
        s["total_seats"] = seats
    _bump(s)
    return _serialize(s)


# ---------------------------------------------------------------------------
# Boundary Rules
# ---------------------------------------------------------------------------

def create_boundary_rule(body) -> dict:
    _require_body_dict(body)
    _require_present(body, ["school_id", "zone_code"])
    sid = body["school_id"]
    zc = body["zone_code"]
    iib = body.get("is_in_boundary", True)
    _require(store.schools.get(sid), "school")
    if not isinstance(zc, str) or not _CODE_RE_ZONE.match(zc):
        raise_err(ERR_INVALID_REQUEST, "zone_code must be uppercase alphanumeric, 3-10 chars")
    if not isinstance(iib, bool):
        raise_err(ERR_INVALID_REQUEST, "is_in_boundary must be boolean")
    r = _common_create()
    r.update({"school_id": sid, "zone_code": zc, "is_in_boundary": iib})
    store.boundary_rules[r["id"]] = r
    return _serialize(r)


def get_boundary_rule(rid: str) -> dict:
    return _serialize(_require(store.boundary_rules.get(rid), "boundary_rule"))


def list_boundary_rules(school_id):
    items = list(store.boundary_rules.values())
    if school_id is not None:
        items = [r for r in items if r["school_id"] == school_id]
    items.sort(key=lambda r: r["created_at"])
    return [_serialize(x) for x in items]


# ---------------------------------------------------------------------------
# Enrollment Windows
# ---------------------------------------------------------------------------

def create_window(body) -> dict:
    _require_body_dict(body)
    _require_present(body, ["district_id", "cycle_label", "opens_at", "closes_at", "lottery_runs_at"])
    did = body["district_id"]
    cl = body["cycle_label"]
    oa = body["opens_at"]
    ca = body["closes_at"]
    lra = body["lottery_runs_at"]

    _require(store.districts.get(did), "district")
    if not isinstance(cl, str) or not cl:
        raise_err(ERR_INVALID_REQUEST, "cycle_label must be a non-empty string")
    # Uniqueness per district
    for w in store.windows.values():
        if w["district_id"] == did and w["cycle_label"] == cl:
            raise_err(ERR_INVALID_REQUEST, "cycle_label must be unique per district")
    try:
        oa_dt = parse_iso8601(oa)
        ca_dt = parse_iso8601(ca)
        lra_dt = parse_iso8601(lra)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "timestamps must be ISO 8601 UTC")
    if not (oa_dt < ca_dt):
        raise_err(ERR_WINDOW_TIMING, "opens_at must be strictly before closes_at")
    if not (ca_dt <= lra_dt):
        raise_err(ERR_WINDOW_TIMING, "closes_at must be <= lottery_runs_at")

    w = _common_create()
    w.update({
        "district_id": did,
        "cycle_label": cl,
        "opens_at": fmt_iso(oa_dt),
        "closes_at": fmt_iso(ca_dt),
        "lottery_runs_at": fmt_iso(lra_dt),
        "status": "DRAFT",
    })
    store.windows[w["id"]] = w
    return _serialize(w)


def get_window(wid: str) -> dict:
    return _serialize(_require(store.windows.get(wid), "window"))


def list_windows(district_id, status):
    items = list(store.windows.values())
    if district_id is not None:
        items = [w for w in items if w["district_id"] == district_id]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    items.sort(key=lambda w: w["created_at"])
    return [_serialize(x) for x in items]


def open_window(wid: str) -> dict:
    w = _require(store.windows.get(wid), "window")
    if w["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Window must be in DRAFT to open")
    now = _clock_now()
    oa = parse_iso8601(w["opens_at"])
    ca = parse_iso8601(w["closes_at"])
    if not (oa <= now < ca):
        raise_err(ERR_WINDOW_TIMING, "Clock must be in [opens_at, closes_at) to open window")
    district = store.districts.get(w["district_id"])
    if not district or district["status"] != "ACTIVE":
        raise_err(ERR_DISTRICT_ARCHIVED, "District is not ACTIVE")
    pov = district["poverty_index_pct"]
    if pov < 0 or pov > 100:
        raise_err(ERR_DISTRICT_DATA_INVALID, "District poverty_index_pct out of range")
    w["status"] = "OPEN"
    _bump(w)
    return _serialize(w)


def close_window(wid: str) -> dict:
    w = _require(store.windows.get(wid), "window")
    if w["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "Window must be OPEN to close")
    now = _clock_now()
    ca = parse_iso8601(w["closes_at"])
    if now < ca:
        raise_err(ERR_INVALID_STATE, "Clock must have reached closes_at before close")
    w["status"] = "CLOSED"
    _bump(w)
    # Cascade: every DRAFT application in this window -> WITHDRAWN
    for app in store.applications.values():
        if app["window_id"] == wid and app["status"] == "DRAFT":
            app["status"] = "WITHDRAWN"
            _bump(app)
            # recompute family risk score (provisional) — opportunistic; no persistence needed
    return _serialize(w)


def run_lottery(wid: str, body) -> dict:
    w = _require(store.windows.get(wid), "window")
    _require_body_dict(body)
    _require_present(body, ["expected_window_version"])
    expected = body["expected_window_version"]
    if w["status"] != "CLOSED":
        raise_err(ERR_INVALID_STATE, "Window must be CLOSED to run lottery")
    now = _clock_now()
    lra = parse_iso8601(w["lottery_runs_at"])
    if now < lra:
        raise_err(ERR_WINDOW_TIMING, "Clock must have reached lottery_runs_at")
    if expected != w["version"]:
        raise_err(ERR_STALE_VERSION, "expected_window_version does not match current version")

    # Step 1: compute final lottery_weight for every SUBMITTED app
    submitted = [a for a in store.applications.values()
                 if a["window_id"] == wid and a["status"] == "SUBMITTED"]
    for app in submitted:
        app["lottery_weight"] = compute_lottery_weight(app, variant="final")

    # Step 2: group by school and run waterfall + IDT cap
    by_school: dict[str, list[dict]] = {}
    for app in submitted:
        by_school.setdefault(app["school_id"], []).append(app)

    for sid, apps in by_school.items():
        school = store.schools.get(sid)
        if not school:
            continue
        total_seats = school["total_seats"]
        accepted, waitlisted = assign_lottery_ranks(apps, total_seats)
        # ACCEPTED branch
        for app in accepted:
            family = store.families.get((store.students.get(app["student_id"]) or {}).get("family_id", "")) or {}
            app["status"] = "ACCEPTED"
            app["inter_district_transfer"] = school["district_id"] != family.get("residence_district_id")
            _bump(app)
            # Create Offer (source=LOTTERY)
            off = _common_create()
            offered_at = _clock_now()
            off.update({
                "application_id": app["id"],
                "status": "OFFERED",
                "offered_at": fmt_iso(offered_at),
                "respond_by": fmt_iso(offered_at + timedelta(days=7)),
                "source": "LOTTERY",
            })
            store.offers[off["id"]] = off
        # WAITLISTED branch — queue_rank reflects position in waitlist after IDT demotions
        # PRD: "waitlist position 1 = first overflow". We re-rank based on order in waitlisted list.
        for i, app in enumerate(waitlisted, start=1):
            app["status"] = "WAITLISTED"
            _bump(app)
            we = _common_create()
            we.update({
                "application_id": app["id"],
                "school_id": sid,
                "queue_rank": i,
                "status": "ACTIVE",
            })
            store.waitlist_entries[we["id"]] = we

    w["status"] = "LOTTERY_RUN"
    _bump(w)
    return _serialize(w)


def finalize_window(wid: str) -> dict:
    w = _require(store.windows.get(wid), "window")
    if w["status"] != "LOTTERY_RUN":
        raise_err(ERR_INVALID_STATE, "Window must be LOTTERY_RUN to finalize")
    # No application in this window has status=OFFERED — meaning no app whose linked offer is OFFERED.
    # Per scaffold: "No Application in this window has status=OFFERED (all responded or expired)"
    # Applications never have status OFFERED in our enum; this means: no OFFERED offers remain for this window's apps.
    for off in store.offers.values():
        if off["status"] == "OFFERED":
            app = store.applications.get(off["application_id"])
            if app and app["window_id"] == wid:
                raise_err(ERR_INVALID_STATE, "Cannot finalize: outstanding OFFERED offers remain")
    # Cascade: all ACTIVE WaitlistEntry rows for schools in this window -> REMOVED;
    # any still-WAITLISTED apps linked to those entries -> WITHDRAWN.
    for we in store.waitlist_entries.values():
        if we["status"] != "ACTIVE":
            continue
        app = store.applications.get(we["application_id"])
        if not app or app["window_id"] != wid:
            continue
        we["status"] = "REMOVED"
        we["updated_at"] = _now()
        if app["status"] == "WAITLISTED":
            app["status"] = "WITHDRAWN"
            _bump(app)
    w["status"] = "FINALIZED"
    _bump(w)
    return _serialize(w)


def expire_offers_for_window(wid: str) -> dict:
    w = _require(store.windows.get(wid), "window")
    now = _clock_now()
    expired_count = 0
    promoted_count = 0
    # Iterate stable list (since we may add new offers via promotions)
    candidates = [o for o in list(store.offers.values()) if o["status"] == "OFFERED"]
    # Sort deterministically: by offered_at then id, so multi-expire cascades are stable
    candidates.sort(key=lambda o: (o.get("offered_at", ""), o.get("id", "")))
    for off in candidates:
        app = store.applications.get(off["application_id"])
        if not app or app["window_id"] != wid:
            continue
        if now < parse_iso8601(off["respond_by"]):
            continue
        # Expire
        off["status"] = "EXPIRED"
        _bump(off)
        # Cascade application
        app["status"] = "DECLINED"
        _bump(app)
        expired_count += 1
        # Promotion cascade on this school
        if _promote_top_waitlist(app["school_id"], w):
            promoted_count += 1
    # PRD: window version increments once for the batch
    _bump(w)
    return {"expired_count": expired_count, "promoted_count": promoted_count}


def _promote_top_waitlist(school_id, window):
    """Promote the lowest-queue_rank ACTIVE WaitlistEntry on this school (within
    the given window). Returns True if a promotion happened."""
    # Find ACTIVE entries linked to apps in this window for this school
    candidates = []
    for we in store.waitlist_entries.values():
        if we["status"] != "ACTIVE" or we["school_id"] != school_id:
            continue
        app = store.applications.get(we["application_id"])
        if not app or app["window_id"] != window["id"]:
            continue
        candidates.append(we)
    if not candidates:
        return False
    candidates.sort(key=lambda x: x["queue_rank"])
    top = candidates[0]
    app = store.applications.get(top["application_id"])
    if not app:
        return False
    # Linked window must be LOTTERY_RUN per scaffold
    if window["status"] != "LOTTERY_RUN":
        return False
    # Promote
    top["status"] = "PROMOTED"
    top["updated_at"] = _now()
    app["status"] = "ACCEPTED"
    # IDT recompute at acceptance time
    family = store.families.get((store.students.get(app["student_id"]) or {}).get("family_id", "")) or {}
    school = store.schools.get(app["school_id"]) or {}
    app["inter_district_transfer"] = school.get("district_id") != family.get("residence_district_id")
    _bump(app)
    # New offer
    new_off = _common_create()
    now = _clock_now()
    new_off.update({
        "application_id": app["id"],
        "status": "OFFERED",
        "offered_at": fmt_iso(now),
        "respond_by": fmt_iso(now + timedelta(days=7)),
        "source": "WAITLIST_PROMOTION",
    })
    store.offers[new_off["id"]] = new_off
    # Decrement queue_rank of remaining ACTIVE entries by 1
    for we in candidates[1:]:
        we["queue_rank"] = we["queue_rank"] - 1
        we["updated_at"] = _now()
    return True


# ---------------------------------------------------------------------------
# Families & Students
# ---------------------------------------------------------------------------

def register_family(body) -> dict:
    _require_body_dict(body)
    _require_present(body, ["guardian_email", "residence_zone_code", "residence_district_id"])
    email = body["guardian_email"]
    zc = body["residence_zone_code"]
    did = body["residence_district_id"]
    pflag = body.get("poverty_flag", False)
    if not isinstance(email, str) or not email:
        raise_err(ERR_INVALID_REQUEST, "guardian_email required")
    email_norm = email.lower()
    if not isinstance(zc, str) or not zc:
        raise_err(ERR_INVALID_REQUEST, "residence_zone_code required")
    if not isinstance(pflag, bool):
        raise_err(ERR_INVALID_REQUEST, "poverty_flag must be boolean")
    district = _require(store.districts.get(did), "district")
    if district["status"] != "ACTIVE":
        raise_err(ERR_DISTRICT_ARCHIVED, "Referenced district is ARCHIVED")
    # Uniqueness of email
    for f in store.families.values():
        if f["guardian_email"] == email_norm:
            raise_err(ERR_INVALID_REQUEST, "guardian_email already registered")
    f = _common_create()
    f.update({
        "guardian_email": email_norm,
        "residence_zone_code": zc,
        "residence_district_id": did,
        "poverty_flag": pflag,
    })
    store.families[f["id"]] = f
    return _serialize(f)


def get_family(fid: str) -> dict:
    return _serialize(_require(store.families.get(fid), "family"))


def list_families(residence_district_id):
    items = list(store.families.values())
    if residence_district_id is not None:
        items = [f for f in items if f["residence_district_id"] == residence_district_id]
    items.sort(key=lambda f: f["created_at"])
    return [_serialize(x) for x in items]


def family_risk_preview(fid: str) -> dict:
    _require(store.families.get(fid), "family")
    score = compute_family_risk_score(fid, "provisional")
    return {"risk_score": score, "variant": "provisional"}


def family_risk_final(fid: str) -> dict:
    _require(store.families.get(fid), "family")
    score = compute_family_risk_score(fid, "final")
    return {"risk_score": score, "variant": "final"}


def create_student(body, caller_role: str, caller_id: str) -> dict:
    _require_body_dict(body)
    _require_present(body, ["family_id", "full_name", "grade_for_cycle"])
    fid = body["family_id"]
    name = body["full_name"]
    g = body["grade_for_cycle"]
    family = _require(store.families.get(fid), "family")
    if caller_role == "Guardian" and family["id"] != caller_id:
        raise_err(ERR_FORBIDDEN_OWNERSHIP, "Cannot create student for another family")
    if not isinstance(name, str) or not name:
        raise_err(ERR_INVALID_REQUEST, "full_name required")
    if not isinstance(g, int) or isinstance(g, bool) or g < 0 or g > 12:
        raise_err(ERR_INVALID_REQUEST, "grade_for_cycle must be integer 0..12")
    # Verify family's district is still ACTIVE per validation #6
    district = store.districts.get(family["residence_district_id"])
    if district and district["status"] != "ACTIVE":
        raise_err(ERR_DISTRICT_ARCHIVED, "Family's district is ARCHIVED")
    s = _common_create()
    s.update({"family_id": fid, "full_name": name, "grade_for_cycle": g})
    store.students[s["id"]] = s
    return _serialize(s)


def get_student(sid: str) -> dict:
    return _serialize(_require(store.students.get(sid), "student"))


def list_students(family_id):
    items = list(store.students.values())
    if family_id is not None:
        items = [s for s in items if s["family_id"] == family_id]
    items.sort(key=lambda s: s["created_at"])
    return [_serialize(x) for x in items]


# ---------------------------------------------------------------------------
# Sibling Bonds
# ---------------------------------------------------------------------------

def create_sibling_bond(body, caller_role: str, caller_id: str) -> dict:
    _require_body_dict(body)
    _require_present(body, ["student_id", "sibling_student_id", "school_id"])
    stu_id = body["student_id"]
    sib_id = body["sibling_student_id"]
    sid = body["school_id"]
    student = _require(store.students.get(stu_id), "student")
    _require(store.students.get(sib_id), "sibling_student")
    _require(store.schools.get(sid), "school")
    if caller_role == "Guardian" and student["family_id"] != caller_id:
        raise_err(ERR_FORBIDDEN_OWNERSHIP, "Cannot declare sibling bond for another family")
    # SiblingBond is lean: id + created_at only
    bond = {
        "id": new_id(),
        "created_at": _now(),
        "student_id": stu_id,
        "sibling_student_id": sib_id,
        "school_id": sid,
    }
    store.sibling_bonds[bond["id"]] = bond
    return _serialize(bond)


def get_sibling_bond(bid: str) -> dict:
    return _serialize(_require(store.sibling_bonds.get(bid), "sibling_bond"))


def list_sibling_bonds(student_id, sibling_student_id, school_id) -> list[dict]:
    items = list(store.sibling_bonds.values())
    if student_id is not None:
        items = [b for b in items if b["student_id"] == student_id]
    if sibling_student_id is not None:
        items = [b for b in items if b["sibling_student_id"] == sibling_student_id]
    if school_id is not None:
        items = [b for b in items if b["school_id"] == school_id]
    items.sort(key=lambda b: b["created_at"])
    return [_serialize(x) for x in items]


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

def create_application(body, caller_id: str) -> dict:
    _require_body_dict(body)
    _require_present(body, ["window_id", "student_id", "school_id", "choice_rank"])
    wid = body["window_id"]
    stu_id = body["student_id"]
    sid = body["school_id"]
    cr = body["choice_rank"]

    # Existence checks (left to right)
    window = _require(store.windows.get(wid), "window")
    student = _require(store.students.get(stu_id), "student")
    school = _require(store.schools.get(sid), "school")

    # District-archived check
    family = store.families.get(student["family_id"]) or {}
    fam_district = store.districts.get(family.get("residence_district_id", ""))
    sch_district = store.districts.get(school["district_id"])
    if fam_district and fam_district["status"] != "ACTIVE":
        raise_err(ERR_DISTRICT_ARCHIVED, "Family's district is ARCHIVED")
    if sch_district and sch_district["status"] != "ACTIVE":
        raise_err(ERR_DISTRICT_ARCHIVED, "School's district is ARCHIVED")

    # Ownership: guardian only acts on their own family's students
    if student["family_id"] != caller_id:
        raise_err(ERR_FORBIDDEN_OWNERSHIP, "Guardian may only apply for their own students")

    # Choice rank validations
    if not isinstance(cr, int) or isinstance(cr, bool) or cr < 1 or cr > 5:
        raise_err(ERR_DUPLICATE_CHOICE, "choice_rank must be integer in [1,5]")
    existing = [a for a in store.applications.values()
                if a["student_id"] == stu_id and a["window_id"] == wid]
    if len(existing) >= 5:
        raise_err(ERR_DUPLICATE_CHOICE, "Student has already reached 5 applications in this window")
    for a in existing:
        if a["choice_rank"] == cr:
            raise_err(ERR_DUPLICATE_CHOICE, "Duplicate choice_rank in same (student, window)")

    # Grade fit
    g = student["grade_for_cycle"]
    if g < school["grade_min"] or g > school["grade_max"]:
        raise_err(ERR_GRADE_OUT_OF_RANGE, "Student grade outside school's grade band")

    a = _common_create()
    a.update({
        "window_id": wid,
        "student_id": stu_id,
        "school_id": sid,
        "choice_rank": cr,
        "inter_district_transfer": False,
        "status": "DRAFT",
        "lottery_weight": 0.0,
        "lottery_rank": None,
    })
    store.applications[a["id"]] = a
    return _serialize(a)


def get_application(aid: str) -> dict:
    return _serialize(_require(store.applications.get(aid), "application"))


def list_applications(window_id, student_id, school_id, status) -> list[dict]:
    items = list(store.applications.values())
    if window_id is not None:
        items = [a for a in items if a["window_id"] == window_id]
    if student_id is not None:
        items = [a for a in items if a["student_id"] == student_id]
    if school_id is not None:
        items = [a for a in items if a["school_id"] == school_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda a: a["created_at"])
    return [_serialize(x) for x in items]


def _check_app_ownership(app: dict, caller_role: str, caller_id: str):
    if caller_role != "Guardian":
        return
    student = store.students.get(app["student_id"])
    if not student or student["family_id"] != caller_id:
        raise_err(ERR_FORBIDDEN_OWNERSHIP, "Guardian may only act on their own family's applications")


def submit_application(aid: str, caller_role: str, caller_id: str) -> dict:
    a = _require(store.applications.get(aid), "application")
    _check_app_ownership(a, caller_role, caller_id)
    if a["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Application must be DRAFT to submit")
    w = _require(store.windows.get(a["window_id"]), "window")
    if w["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "Parent window must be OPEN")
    student = store.students.get(a["student_id"])
    school = store.schools.get(a["school_id"])
    if student and school:
        g = student["grade_for_cycle"]
        if g < school["grade_min"] or g > school["grade_max"]:
            raise_err(ERR_GRADE_OUT_OF_RANGE, "Student grade outside school's grade band")
    a["status"] = "SUBMITTED"
    _bump(a)
    return _serialize(a)


def withdraw_application(aid: str, caller_role: str, caller_id: str) -> dict:
    a = _require(store.applications.get(aid), "application")
    _check_app_ownership(a, caller_role, caller_id)
    if a["status"] not in ("DRAFT", "SUBMITTED"):
        raise_err(ERR_INVALID_STATE, "Application must be DRAFT or SUBMITTED to withdraw")
    w = _require(store.windows.get(a["window_id"]), "window")
    if w["status"] not in ("OPEN", "CLOSED"):
        raise_err(ERR_INVALID_STATE, "Parent window must be OPEN or CLOSED")
    a["status"] = "WITHDRAWN"
    _bump(a)
    return _serialize(a)


def reject_application(aid: str) -> dict:
    a = _require(store.applications.get(aid), "application")
    if a["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Application must be SUBMITTED to reject")
    w = _require(store.windows.get(a["window_id"]), "window")
    if w["status"] not in ("OPEN", "CLOSED"):
        raise_err(ERR_INVALID_STATE, "Parent window must be OPEN or CLOSED")
    a["status"] = "REJECTED"
    _bump(a)
    return _serialize(a)


def application_weight_preview(aid: str) -> dict:
    a = _require(store.applications.get(aid), "application")
    w = compute_lottery_weight(a, variant="provisional")
    return {"lottery_weight": w, "variant": "provisional"}


# ---------------------------------------------------------------------------
# Offers
# ---------------------------------------------------------------------------

def get_offer(oid: str) -> dict:
    return _serialize(_require(store.offers.get(oid), "offer"))


def list_offers(application_id, status, source) -> list[dict]:
    items = list(store.offers.values())
    if application_id is not None:
        items = [o for o in items if o["application_id"] == application_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    if source is not None:
        items = [o for o in items if o["source"] == source]
    items.sort(key=lambda o: o["created_at"])
    return [_serialize(x) for x in items]


def accept_offer(oid: str, body, caller_role: str, caller_id: str) -> dict:
    off = _require(store.offers.get(oid), "offer")
    _require_body_dict(body)
    _require_present(body, ["expected_offer_version"])
    expected = body["expected_offer_version"]
    app = _require(store.applications.get(off["application_id"]), "application")
    _check_app_ownership(app, caller_role, caller_id)
    if off["status"] != "OFFERED":
        raise_err(ERR_INVALID_STATE, "Offer is not in OFFERED state")
    now = _clock_now()
    if now >= parse_iso8601(off["respond_by"]):
        raise_err(ERR_INVALID_STATE, "Offer has passed respond_by")
    if expected != off["version"]:
        raise_err(ERR_STALE_VERSION, "expected_offer_version does not match current version")
    off["status"] = "ACCEPTED"
    _bump(off)
    app["status"] = "ENROLLED"
    _bump(app)
    return _serialize(off)


def decline_offer(oid: str, caller_role: str, caller_id: str) -> dict:
    off = _require(store.offers.get(oid), "offer")
    app = _require(store.applications.get(off["application_id"]), "application")
    _check_app_ownership(app, caller_role, caller_id)
    if off["status"] != "OFFERED":
        raise_err(ERR_INVALID_STATE, "Offer is not in OFFERED state")
    off["status"] = "DECLINED"
    _bump(off)
    app["status"] = "DECLINED"
    _bump(app)
    # Cascade waitlist promotion
    window = store.windows.get(app["window_id"])
    if window:
        _promote_top_waitlist(app["school_id"], window)
    return _serialize(off)


# ---------------------------------------------------------------------------
# Waitlist Entries
# ---------------------------------------------------------------------------

def get_waitlist_entry(wid: str) -> dict:
    return _serialize(_require(store.waitlist_entries.get(wid), "waitlist_entry"))


def list_waitlist_entries(school_id, application_id, status) -> list[dict]:
    items = list(store.waitlist_entries.values())
    if school_id is not None:
        items = [w for w in items if w["school_id"] == school_id]
    if application_id is not None:
        items = [w for w in items if w["application_id"] == application_id]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    items.sort(key=lambda w: w["created_at"])
    return [_serialize(x) for x in items]


# ---------------------------------------------------------------------------
# System clock
# ---------------------------------------------------------------------------

def set_clock(body) -> dict:
    _require_body_dict(body)
    _require_present(body, ["to_iso8601"])
    try:
        dt = parse_iso8601(body["to_iso8601"])
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be ISO 8601")
    store.clock_current_utc = dt
    return {"current_utc": fmt_iso(dt)}


def get_clock() -> dict:
    now = _clock_now()
    return {"current_utc": fmt_iso(now)}
