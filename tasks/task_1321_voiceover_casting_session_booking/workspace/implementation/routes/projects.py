"""Project endpoints: CRUD, lifecycle transitions, cancellation cascade."""
from flask import Blueprint, request

import errors
from db import DB, clock_now, parse_iso
from middleware import auth, json_body
from response import ok, ok_list
from services import (
    CATEGORIES, USAGE_TYPES, add_months, agent_commission, base_record,
    buyout_final, buyout_quote, close_project, expire_exclusions,
    lazy_read_tick, paginate, project_json, sorted_rows, touch,
)

bp = Blueprint("projects", __name__)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _get_project(pid):
    p = DB["projects"].get(pid)
    if p is None:
        raise errors.not_found("Project not found")
    return p


def _own_project(p, uid):
    if p["client_id"] != uid:
        raise errors.forbidden("Project belongs to a different client")


@bp.post("/projects")
def create_project():
    uid, _ = auth(["Client"])
    body = json_body()
    # priority 3: body FK existence
    cid = body.get("client_id")
    client = DB["clients"].get(cid) if isinstance(cid, str) else None
    if cid is not None and client is None:
        raise errors.not_found("Client not found")
    # priority 4: ownership
    if cid is not None and cid != uid:
        raise errors.forbidden("client_id must equal the acting client's X-User-ID")
    # priority 11: shape
    for field in ("client_id", "title", "product_category", "usage_type",
                  "spots_count", "brief_text", "audition_deadline"):
        if body.get(field) is None:
            raise errors.invalid_request(f"Missing required field: {field}")
    if not isinstance(body["title"], str) or not isinstance(body["brief_text"], str):
        raise errors.invalid_request("title and brief_text must be strings")
    if body["product_category"] not in CATEGORIES:
        raise errors.invalid_request("Invalid product_category")
    if body["usage_type"] not in USAGE_TYPES:
        raise errors.invalid_request("Invalid usage_type")
    term_months = body.get("term_months")
    if body["usage_type"] == "TERM":
        if not _is_int(term_months) or term_months < 1:
            raise errors.invalid_request("term_months is required (positive integer) for TERM projects")
    else:
        if term_months is not None:
            raise errors.invalid_request("term_months must be absent for non-TERM projects")
    if not _is_int(body["spots_count"]) or body["spots_count"] < 1:
        raise errors.invalid_request("spots_count must be an integer >= 1")
    deadline = parse_iso(body["audition_deadline"])
    if deadline is None:
        raise errors.invalid_request("audition_deadline must be a valid ISO 8601 timestamp")
    exclusivity = body.get("exclusivity_required", False)
    if not isinstance(exclusivity, bool):
        raise errors.invalid_request("exclusivity_required must be a boolean")
    rec = base_record()
    rec.update({
        "client_id": cid,
        "title": body["title"],
        "product_category": body["product_category"],
        "usage_type": body["usage_type"],
        "term_months": term_months if body["usage_type"] == "TERM" else None,
        "spots_count": body["spots_count"],
        "exclusivity_required": exclusivity,
        "brief_text": body["brief_text"],
        "audition_deadline": deadline,
        "status": "DRAFT",
        "selected_talent_id": None,
        "buyout_quote_cents": None,
        "buyout_final_cents": None,
    })
    DB["projects"][rec["id"]] = rec
    return ok(project_json(rec), 201)


@bp.get("/projects")
def list_projects():
    auth(["CastingDirector", "Client", "Agent"])
    lazy_read_tick()
    rows = sorted_rows("projects")
    cid = request.args.get("client_id")
    tid = request.args.get("selected_talent_id")
    st = request.args.get("status")
    if cid is not None:
        rows = [p for p in rows if p["client_id"] == cid]
    if tid is not None:
        rows = [p for p in rows if p["selected_talent_id"] == tid]
    if st is not None:
        rows = [p for p in rows if p["status"] == st]
    page, total, limit, offset = paginate(rows, request.args)
    return ok_list([project_json(p) for p in page], total, limit, offset)


@bp.get("/projects/<pid>")
def get_project(pid):
    auth(["CastingDirector", "Client", "Talent", "Agent"])
    lazy_read_tick()
    return ok(project_json(_get_project(pid)))


@bp.post("/projects/<pid>/open_casting")
def open_casting(pid):
    auth(["CastingDirector"])
    p = _get_project(pid)
    # priority 5: state (brief_text non-empty is a state-category fitness check per PRD §3.2)
    if p["status"] != "DRAFT":
        raise errors.invalid_state("Project is not in DRAFT")
    if not p["brief_text"]:
        raise errors.invalid_state("brief_text must be non-empty to open casting")
    # priority 6: temporal
    if not p["audition_deadline"] > clock_now():
        raise errors.temporal("audition_deadline must lie strictly after the current clock")
    p["buyout_quote_cents"] = buyout_quote(p)
    p["status"] = "CASTING"
    touch(p)
    return ok(project_json(p))


@bp.post("/projects/<pid>/select_talent")
def select_talent(pid):
    uid, _ = auth(["Client"])
    p = _get_project(pid)
    body = json_body()
    # priority 3: body FK existence (scoped to this project)
    aid = body.get("self_audition_id")
    a = DB["self_auditions"].get(aid) if isinstance(aid, str) else None
    if a is None or a["project_id"] != pid:
        raise errors.not_found("Self-audition not found on this project")
    # priority 4: ownership
    _own_project(p, uid)
    # priority 5: state
    if p["status"] != "CASTING":
        raise errors.invalid_state("Project is not in CASTING")
    if a["status"] not in ("SUBMITTED", "SHORTLISTED"):
        raise errors.invalid_state("Audition is not in SUBMITTED or SHORTLISTED")
    t = DB["talents"].get(a["talent_id"])
    if t is None or t["roster_status"] != "ACTIVE":
        raise errors.invalid_state("Selected talent is not ACTIVE on the roster")
    # cast attempts lazily expire exclusions (scaffold §1.2 ConflictExclusion)
    expire_exclusions()
    # priority 7: exclusivity conflict
    now = clock_now()
    window_end = add_months(now, p["term_months"]) if p["term_months"] else now
    if p["exclusivity_required"]:
        for ce in DB["conflict_exclusions"].values():
            if (ce["talent_id"] == t["id"] and ce["status"] == "ACTIVE"
                    and ce["product_category"] == p["product_category"]
                    and ce["starts_at"] < window_end and now < ce["ends_at"]):
                raise errors.talent_conflict()
    # priority 13: fiscal
    final = buyout_final(p, t)
    if final <= 0:
        raise errors.fiscal("buyout_final_cents must be positive")
    # ---- side effects (atomic: all preconditions passed) ----
    a["status"] = "SELECTED"
    touch(a)
    for sib in DB["self_auditions"].values():
        if sib["project_id"] == pid and sib["id"] != a["id"] and sib["status"] in ("SUBMITTED", "SHORTLISTED"):
            sib["status"] = "REJECTED"
            touch(sib)
    p["selected_talent_id"] = t["id"]
    p["buyout_final_cents"] = final
    p["status"] = "CAST"
    touch(p)
    commission, payout = agent_commission(final, t["union_status"])
    ut = base_record()
    ut.update({
        "project_id": pid,
        "usage_type": p["usage_type"],
        "term_months": p["term_months"],
        "broadcast_regions": [],
        "digital_placements": [],
        "buyout_cents": final,
        "agent_commission_cents": commission,
        "talent_payout_cents": payout,
        "locked_at_cast": True,
    })
    DB["usage_terms"][ut["id"]] = ut
    if p["exclusivity_required"]:
        ce = base_record()
        ce.update({
            "talent_id": t["id"],
            "product_category": p["product_category"],
            "starts_at": now,
            "ends_at": window_end,
            "source": "PROJECT_CAST",
            "status": "ACTIVE",
            "_project_id": pid,
        })
        DB["conflict_exclusions"][ce["id"]] = ce
    return ok(project_json(p))


@bp.post("/projects/<pid>/cancel")
def cancel_project(pid):
    uid, _ = auth(["Client"])
    p = _get_project(pid)
    _own_project(p, uid)
    # priority 5: state — cancellable only from DRAFT, CASTING, CAST
    if p["status"] not in ("DRAFT", "CASTING", "CAST"):
        raise errors.invalid_state("Project cannot be cancelled from its current state")
    # OCC (scaffold §1.2.1): expected_project_version is required on this endpoint
    body = json_body()
    expected = body.get("expected_project_version")
    if expected is None:
        raise errors.invalid_request("expected_project_version is required")
    try:
        expected = int(expected)
    except (TypeError, ValueError):
        raise errors.invalid_request("expected_project_version must be an integer")
    if expected != p["version"]:
        raise errors.stale_version("Project version has advanced since last read")
    # state-category blockers (PRD §3.9)
    if any(s["project_id"] == pid and s["status"] == "CONFIRMED" for s in DB["sessions"].values()):
        raise errors.invalid_state("A CONFIRMED session blocks cancellation")
    if any(i["project_id"] == pid and i["status"] in ("ISSUED", "PAID") for i in DB["invoices"].values()):
        raise errors.invalid_state("An ISSUED or PAID invoice blocks cancellation")
    # ---- cascade ----
    for a in DB["self_auditions"].values():
        if a["project_id"] == pid and a["status"] in ("SUBMITTED", "SHORTLISTED"):
            a["status"] = "REJECTED"
            touch(a)
    for s in DB["sessions"].values():
        if s["project_id"] == pid and s["status"] == "TENTATIVE":
            s["status"] = "CANCELLED"
            touch(s)
    for ce in DB["conflict_exclusions"].values():
        if ce.get("_project_id") == pid and ce["status"] == "ACTIVE":
            ce["status"] = "RELEASED"
            touch(ce)
    for inv in DB["invoices"].values():
        if inv["project_id"] == pid and inv["status"] == "PENDING":
            inv["status"] = "VOID"
            touch(inv)
    p["status"] = "CANCELLED"
    touch(p)
    return ok(project_json(p))


@bp.post("/projects/<pid>/close")
def close(pid):
    uid, _ = auth(["Client"])
    p = _get_project(pid)
    _own_project(p, uid)
    if p["status"] != "DELIVERED":
        raise errors.invalid_state("Project is not DELIVERED")
    close_project(p)
    return ok(project_json(p))


@bp.post("/projects/<pid>/request_revision")
def request_revision(pid):
    uid, _ = auth(["Client"])
    p = _get_project(pid)
    _own_project(p, uid)
    # NB: lazy auto-close is intentionally NOT run here, so that a late revision
    # request surfaces ERR_TEMPORAL_VIOLATION (priority 6) rather than a 409 that
    # an auto-closed project would produce.
    if p["status"] != "DELIVERED":
        raise errors.invalid_state("Project is not DELIVERED")
    from services import latest_delivery
    d = latest_delivery(pid)
    if d is None:
        raise errors.invalid_state("No delivery exists for this project")
    if d["revision_requested"]:
        raise errors.invalid_state("A revision was already requested for this delivery")
    if clock_now() > d["revision_window_closes_at"]:
        raise errors.temporal("The revision window has closed")
    d["revision_requested"] = True
    p["status"] = "CAST"
    touch(p)
    return ok(project_json(p))
