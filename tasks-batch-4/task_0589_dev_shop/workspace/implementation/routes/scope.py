"""Change requests and releases — PRD §3.6, §3.7."""
from decimal import Decimal

from flask import Blueprint, g, request

from core import (auth, clock, created, err, fk, get_body, invalid, must_get, new_entity,
                  ok, ok_list, pagination, paginate, r2, req_enum, req_int, req_number,
                  req_str, opt_str, scope_client, store, touch)
import services as S

bp = Blueprint("scope", __name__)


# --------------------------------------------------------------------------
# Change requests
# --------------------------------------------------------------------------
@bp.post("/change-requests")
def create_change_request():
    auth("DeliveryLead")
    b = get_body()
    eng = fk(b, "engagement_id", "engagement")
    if eng is None:
        invalid("engagement_id is required.")
    title = req_str(b, "title")
    delta_hours = req_number(b, "delta_hours", positive=True)
    rush = b.get("rush", False)
    if not isinstance(rush, bool):
        invalid("rush must be a boolean.")
    expected = req_int(b, "expected_engagement_version")
    # OCC outranks every business-state check (PRD 2.5).
    if expected != eng["version"]:
        err("ERR_STALE_ENGAGEMENT_VERSION", "The engagement has moved on since you read it.")
    if eng["status"] != "ACTIVE":
        err("ERR_ENGAGEMENT_NOT_ACTIVE", "The engagement is not ACTIVE.")
    row = new_entity({
        "engagement_id": eng["id"], "title": title, "delta_hours": r2(delta_hours),
        "rush": rush, "quoted_amount": Decimal("0.00"), "status": "DRAFT",
        "revision_rounds": 0,
    })
    store.change_requests[row["id"]] = row
    touch(eng)   # the engagement's ledger has been touched
    return created(S.ser_change_request(row))


@bp.get("/change-requests/<cid>")
def get_change_request(cid):
    auth()
    cr = must_get("change_request", cid)
    scope_client(store.engagements[cr["engagement_id"]]["client_id"])
    return ok(S.ser_change_request(cr))


@bp.get("/change-requests")
def list_change_requests():
    auth()
    limit, offset = pagination()
    rows = list(store.change_requests.values())
    if g.role == "ClientContact":
        rows = [c for c in rows
                if store.engagements[c["engagement_id"]]["client_id"] == g.user_id]
    for key in ("engagement_id", "status"):
        val = request.args.get(key)
        if val:
            rows = [c for c in rows if c[key] == val]
    page, total = paginate(rows, limit, offset)
    return ok_list([S.ser_change_request(c) for c in page], limit, offset, total)


@bp.post("/change-requests/<cid>/submit")
def submit_change_request(cid):
    auth("DeliveryLead")
    cr = must_get("change_request", cid)
    eng = store.engagements[cr["engagement_id"]]
    if eng["status"] != "ACTIVE":
        err("ERR_ENGAGEMENT_NOT_ACTIVE", "The engagement is not ACTIVE.")
    if cr["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        err("ERR_INVALID_TRANSITION", "Only a DRAFT or REVISION_REQUESTED CR may be submitted.")
    cr["status"] = "SUBMITTED"
    cr["quoted_amount"] = S.quote_change_request(cr, eng)
    touch(cr)
    return ok(S.ser_change_request(cr))


@bp.post("/change-requests/<cid>/decision")
def decide_change_request(cid):
    auth("ClientContact")
    cr = must_get("change_request", cid)
    b = get_body()
    action = req_enum(b, "action", {"APPROVE", "REJECT", "REQUEST_REVISION"})
    opt_str(b, "note")
    eng = store.engagements[cr["engagement_id"]]
    scope_client(eng["client_id"])
    if action == "APPROVE" and eng["status"] != "ACTIVE":
        err("ERR_ENGAGEMENT_NOT_ACTIVE", "The engagement is not ACTIVE.")
    if cr["status"] != "SUBMITTED":
        err("ERR_INVALID_TRANSITION", "Only a SUBMITTED change request may be decided.")

    if action == "REQUEST_REVISION":
        if cr["revision_rounds"] >= S.MAX_CR_REVISION_ROUNDS:
            err("ERR_CR_ROUND_LIMIT", "The revision limit for this change request is reached.")
        cr["status"] = "REVISION_REQUESTED"
        cr["revision_rounds"] += 1
        touch(cr)
        return ok(S.ser_change_request(cr))

    if action == "REJECT":
        cr["status"] = "REJECTED"
        touch(cr)
        return ok(S.ser_change_request(cr))

    # APPROVE — four-link cascade (PRD 3.6)
    cr["status"] = "APPROVED"                                            # LINK 1
    touch(cr)
    eng["contract_value"] = r2(eng["contract_value"] + cr["quoted_amount"])   # LINK 2
    eng["budget_hours_cap"] = r2(eng["budget_hours_cap"] + cr["delta_hours"])
    S.recompute_scope_hours(eng)
    S.recompute_burn_ledger(eng)                                         # LINKS 3, 4
    touch(eng)
    return ok(S.ser_change_request(cr))


# --------------------------------------------------------------------------
# Releases
# --------------------------------------------------------------------------
@bp.post("/releases")
def create_release():
    auth("Engineer")
    b = get_body()
    eng = fk(b, "engagement_id", "engagement")
    if eng is None:
        invalid("engagement_id is required.")
    milestone = fk(b, "milestone_id", "milestone")
    if milestone is None:
        invalid("milestone_id is required.")
    version_label = req_str(b, "version_label")
    if eng["status"] != "ACTIVE":
        err("ERR_ENGAGEMENT_NOT_ACTIVE", "The engagement is not ACTIVE.")
    if milestone["engagement_id"] != eng["id"]:
        err("ERR_MILESTONE_ENGAGEMENT_MISMATCH",
            "The milestone belongs to a different engagement.")
    row = new_entity({
        "engagement_id": eng["id"], "milestone_id": milestone["id"],
        "version_label": version_label, "status": "BUILDING",
        "defect_count": 0, "qa_rounds": 0, "accepted_at": None, "environment": None,
    })
    store.releases[row["id"]] = row
    return created(S.ser_release(row))


@bp.get("/releases/<rid>")
def get_release(rid):
    auth()
    r = must_get("release", rid)
    scope_client(store.engagements[r["engagement_id"]]["client_id"])
    return ok(S.ser_release(r))


@bp.get("/releases")
def list_releases():
    auth()
    limit, offset = pagination()
    rows = list(store.releases.values())
    if g.role == "ClientContact":
        rows = [r for r in rows
                if store.engagements[r["engagement_id"]]["client_id"] == g.user_id]
    for key in ("engagement_id", "milestone_id", "status"):
        val = request.args.get(key)
        if val:
            rows = [r for r in rows if r[key] == val]
    page, total = paginate(rows, limit, offset)
    return ok_list([S.ser_release(r) for r in page], limit, offset, total)


@bp.post("/releases/<rid>/qa-result")
def qa_result(rid):
    auth("Engineer")
    r = must_get("release", rid)
    b = get_body()
    outcome = req_enum(b, "outcome", {"PASS", "FAIL"})
    defect_count = req_int(b, "defect_count", minimum=0)
    eng = store.engagements[r["engagement_id"]]
    if eng["status"] != "ACTIVE":
        err("ERR_ENGAGEMENT_NOT_ACTIVE", "The engagement is not ACTIVE.")

    if outcome == "PASS" and defect_count == 0 and r["status"] in ("BUILDING", "REWORK"):
        r["status"] = "QA_PASSED"
        r["defect_count"] = 0
    elif outcome == "FAIL" and defect_count >= 1 and r["status"] == "BUILDING":
        r["status"] = "REWORK"
        r["defect_count"] = defect_count
    else:
        err("ERR_INVALID_TRANSITION", "The QA result does not match any legal transition.")
    r["qa_rounds"] += 1
    touch(r)
    return ok(S.ser_release(r))


@bp.post("/releases/<rid>/acceptance")
def acceptance(rid):
    auth("ClientContact")
    r = must_get("release", rid)
    b = get_body()
    action = req_enum(b, "action", {"ACCEPT", "REJECT"})
    opt_str(b, "note")
    eng = store.engagements[r["engagement_id"]]
    scope_client(eng["client_id"])
    if eng["status"] != "ACTIVE":
        err("ERR_ENGAGEMENT_NOT_ACTIVE", "The engagement is not ACTIVE.")
    if r["status"] != "QA_PASSED":
        err("ERR_INVALID_TRANSITION", "Only a QA_PASSED release may be accepted or rejected.")

    if action == "REJECT":
        r["status"] = "REWORK"          # the milestone is deliberately left alone
        touch(r)
        return ok(S.ser_release(r))

    # ACCEPT — three-link cascade (PRD 3.7)
    r["status"] = "ACCEPTED"                                      # LINK 1
    r["accepted_at"] = clock.now
    touch(r)
    milestone = store.milestones[r["milestone_id"]]
    if milestone["status"] == "PLANNED":                          # LINK 2
        milestone["status"] = "COMPLETED"
        milestone["accepted_at"] = clock.now
        touch(milestone)
        if eng["billing_model"] == "FIXED":                       # LINK 3 (conditional)
            S.create_invoice_row(eng, "MILESTONE", milestone=milestone)
    return ok(S.ser_release(r))


@bp.post("/releases/<rid>/deploy")
def deploy(rid):
    auth("Engineer")
    r = must_get("release", rid)
    b = get_body()
    environment = req_str(b, "environment")
    if r["status"] != "ACCEPTED":
        err("ERR_INVALID_TRANSITION", "Only an ACCEPTED release may be deployed.")
    r["status"] = "DEPLOYED"
    r["environment"] = environment
    touch(r)
    return ok(S.ser_release(r))
