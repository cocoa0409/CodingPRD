"""Variance requests: file, decide, withdraw."""

import constants as C
import db
import errors
import helpers as H
import middleware as mw
import response as R

S = db.STORE
BASE = "/septic-ops/installer-companies/<cid>/customers/<cuid>/sites/<sid>/variance-requests"
DESIGNER = ("SystemDesigner",)
OFFICER = ("HealthOfficer",)


def create_variance(cid, cuid, sid):
    site = H.resolve_site(cid, cuid, sid)
    b = mw.body()
    # (4) FK: design must exist for this site
    design = H.fk_site_row("designs", site, b.get("design_id"))
    # (18) justification >= 20 chars
    justification = mw.req_note(b, "justification")
    # (19) enum
    relief_kind = mw.req_enum(b, "relief_kind", C.RELIEF_KINDS)
    rec = db.create_record("variance_requests", {
        "site_id": site["id"],
        "design_id": design["id"],
        "relief_kind": relief_kind,
        "justification": justification,
        "decided_by": None,
        "decision_note": None,
        "status": "PENDING",
    })
    return R.respond_object(rec, 201)


def list_variances(cid, cuid, sid):
    site = H.resolve_site(cid, cuid, sid)
    rows = H.children("variance_requests", "site_id", site["id"])
    rows = H.apply_filters(rows, {"status": "status"})
    return R.respond_list(rows)


def get_variance(cid, cuid, sid, vid):
    site = H.resolve_site(cid, cuid, sid)
    return R.respond_object(H.resolve_variance(site, vid))


def decide_variance(cid, cuid, sid, vid):
    site = H.resolve_site(cid, cuid, sid)
    var = H.resolve_variance(site, vid)
    b = mw.body()
    # (4) officer FK
    officer = H.fk_company_staff("health_officers", cid, b.get("officer_id"))
    # (5) state
    if var["status"] != "PENDING":
        errors.invalid_state("Only a PENDING variance request may be decided")
    decision = b.get("decision")
    # (11) officer independence from the referenced design's designer
    design = S["designs"].get(var["design_id"])
    if design is not None:
        designer = S["system_designers"].get(design["designer_id"])
        if (designer is not None
                and officer["badge_number"] == designer["license_number"]):
            raise errors.ApiError(
                errors.ERR_SEGREGATION_OF_DUTIES, 403,
                "The deciding officer must not be the design's designer")
    # (18) DENY requires a decision_note >= 20 chars
    note = b.get("decision_note")
    if decision == "DENY":
        mw.req_note(b, "decision_note")
    # (28) enumerated decision payload
    if decision not in ("APPROVE", "DENY"):
        raise errors.ApiError(errors.ERR_INVALID_DECISION, 400,
                              "decision must be APPROVE or DENY")
    fields = {"decided_by": officer["id"]}
    if isinstance(note, str):
        fields["decision_note"] = note
    fields["status"] = "APPROVED" if decision == "APPROVE" else "DENIED"
    db.set_fields(var, **fields)
    return R.respond_object(var)


def withdraw_variance(cid, cuid, sid, vid):
    site = H.resolve_site(cid, cuid, sid)
    var = H.resolve_variance(site, vid)
    # (5) state
    if var["status"] != "PENDING":
        errors.invalid_state("Only a PENDING variance request may be withdrawn")
    db.set_fields(var, status="WITHDRAWN")
    return R.respond_object(var)


def register(app):
    app.add_url_rule(BASE, "variance_create", mw.auth(*DESIGNER)(create_variance),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(BASE, "variance_list", mw.auth()(list_variances),
                     methods=["GET"], strict_slashes=False)
    app.add_url_rule(BASE + "/<vid>", "variance_get", mw.auth()(get_variance),
                     methods=["GET"], strict_slashes=False)
    app.add_url_rule(BASE + "/<vid>/decide", "variance_decide",
                     mw.auth(*OFFICER)(decide_variance),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(BASE + "/<vid>/withdraw", "variance_withdraw",
                     mw.auth(*DESIGNER)(withdraw_variance),
                     methods=["POST"], strict_slashes=False)
