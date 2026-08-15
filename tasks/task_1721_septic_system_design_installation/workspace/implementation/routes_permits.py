"""Permits: issuance, suspension, reinstatement (OCC), revocation."""

import db
import errors
import helpers as H
import middleware as mw
import response as R
import services as svc

S = db.STORE
BASE = "/septic-ops/installer-companies/<cid>/customers/<cuid>/sites/<sid>/permits"
OFFICER = ("HealthOfficer",)


def create_permit(cid, cuid, sid):
    site = H.resolve_site(cid, cuid, sid)
    b = mw.body()
    # (4) body FKs
    design = H.fk_site_row("designs", site, b.get("design_id"))
    H.fk_company_staff("health_officers", cid, b.get("officer_id"))
    # (29) creation-scope state: design must be APPROVED for the same site
    if design["status"] != "APPROVED":
        errors.invalid_state("Permits may only pin an APPROVED design")
    issued = site["current_period_index"]
    rec = db.create_record("permits", {
        "site_id": site["id"],
        "design_id": design["id"],
        "permit_number": db.new_permit_number(),
        "issued_period": issued,
        "expires_period": svc.permit_expires_period(issued),
        "status": "ISSUED",
    })
    return R.respond_object(rec, 201)


def list_permits(cid, cuid, sid):
    site = H.resolve_site(cid, cuid, sid)
    rows = H.children("permits", "site_id", site["id"])
    rows = H.apply_filters(rows, {"status": "status"})
    return R.respond_list(rows)


def get_permit(cid, cuid, sid, pid):
    site = H.resolve_site(cid, cuid, sid)
    return R.respond_object(H.resolve_permit(site, pid))


def suspend_permit(cid, cuid, sid, pid):
    site = H.resolve_site(cid, cuid, sid)
    permit = H.resolve_permit(site, pid)
    # (5) state
    if permit["status"] != "ISSUED":
        errors.invalid_state("Only an ISSUED permit may be suspended")
    svc.suspend_permit(permit)
    return R.respond_object(permit)


def reinstate_permit(cid, cuid, sid, pid):
    site = H.resolve_site(cid, cuid, sid)
    permit = H.resolve_permit(site, pid)
    b = mw.body()
    # (5) state
    if permit["status"] != "SUSPENDED":
        errors.invalid_state("Only a SUSPENDED permit may be reinstated")
    # (7) expiry
    if site["current_period_index"] > permit["expires_period"]:
        raise errors.ApiError(errors.ERR_PERMIT_EXPIRED, 409,
                              "The permit validity window has passed")
    # (25) OCC
    expected = b.get("expected_permit_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        errors.invalid_request("expected_permit_version is required and must be an integer")
    if expected != permit["version"]:
        raise errors.ApiError(errors.ERR_STALE_VERSION, 412,
                              "expected_permit_version does not match the current version")
    # (26) pinned design must currently be APPROVED
    design = S["designs"].get(permit["design_id"])
    if design is None or design["status"] != "APPROVED":
        raise errors.ApiError(errors.ERR_PINNED_BY_LIVE_DESIGN, 409,
                              "The pinned design is no longer APPROVED")
    db.set_fields(permit, status="ISSUED")
    return R.respond_object(permit)


def revoke_permit(cid, cuid, sid, pid):
    site = H.resolve_site(cid, cuid, sid)
    permit = H.resolve_permit(site, pid)
    b = mw.body()
    # (5) state: ISSUED or SUSPENDED
    if permit["status"] not in ("ISSUED", "SUSPENDED"):
        errors.invalid_state("Only an ISSUED or SUSPENDED permit may be revoked")
    # (18) revoke_note >= 20 chars
    mw.req_note(b, "revoke_note")
    db.set_fields(permit, status="REVOKED")
    svc.revoke_permit_cascade(permit)
    return R.respond_object(permit)


def register(app):
    app.add_url_rule(BASE, "permit_create", mw.auth(*OFFICER)(create_permit),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(BASE, "permit_list", mw.auth()(list_permits),
                     methods=["GET"], strict_slashes=False)
    app.add_url_rule(BASE + "/<pid>", "permit_get", mw.auth()(get_permit),
                     methods=["GET"], strict_slashes=False)
    app.add_url_rule(BASE + "/<pid>/suspend", "permit_suspend",
                     mw.auth(*OFFICER)(suspend_permit),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(BASE + "/<pid>/reinstate", "permit_reinstate",
                     mw.auth(*OFFICER)(reinstate_permit),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(BASE + "/<pid>/revoke", "permit_revoke",
                     mw.auth(*OFFICER)(revoke_permit),
                     methods=["POST"], strict_slashes=False)
