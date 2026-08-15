"""Repair cases: open, triage, begin-remediation, resolve, close."""

import constants as C
import db
import errors
import helpers as H
import middleware as mw
import response as R
import services as svc

S = db.STORE
BASE = "/septic-ops/installer-companies/<cid>/customers/<cuid>/sites/<sid>/repair-cases"
PM = ("ProjectManager",)


def create_repair_case(cid, cuid, sid):
    site = H.resolve_site(cid, cuid, sid)
    b = mw.body()
    # (4) FK: failed installation within this site
    inst = H.fk_site_row("installations", site, b.get("failed_installation_id"))
    # (18) diagnosis note >= 20 chars
    diagnosis_note = mw.req_note(b, "diagnosis_note")
    # (19) enum
    failure_kind = mw.req_enum(b, "failure_kind", C.FAILURE_KINDS)
    # (29) creation-scope state: the failed installation must be COMPLETED
    if inst["status"] != "COMPLETED":
        errors.invalid_state(
            "A repair case requires the failed installation to be COMPLETED")
    rec = db.create_record("repair_cases", {
        "site_id": site["id"],
        "failed_installation_id": inst["id"],
        "failure_kind": failure_kind,
        "diagnosis_note": diagnosis_note,
        "remedy": "UNDECIDED",
        "replacement_design_id": None,
        "status": "OPEN",
    })
    return R.respond_object(rec, 201)


def list_repair_cases(cid, cuid, sid):
    site = H.resolve_site(cid, cuid, sid)
    rows = H.children("repair_cases", "site_id", site["id"])
    rows = H.apply_filters(rows, {"status": "status"})
    return R.respond_list(rows)


def get_repair_case(cid, cuid, sid, rid):
    site = H.resolve_site(cid, cuid, sid)
    return R.respond_object(H.resolve_repair(site, rid))


def triage_repair_case(cid, cuid, sid, rid):
    site = H.resolve_site(cid, cuid, sid)
    case = H.resolve_repair(site, rid)
    b = mw.body()
    remedy = b.get("remedy")
    replacement_id = b.get("replacement_design_id")
    replacement = None
    # (4) FK: the replacement design, when referenced, must exist for this site
    if replacement_id is not None:
        replacement = H.fk_site_row("designs", site, replacement_id)
    # (5) state
    if case["status"] != "OPEN":
        errors.invalid_state("Only an OPEN repair case may be triaged")
    # (10) REPAIR_IN_KIND on STRUCTURAL_COLLAPSE requires an APPROVED variance
    if (remedy == "REPAIR_IN_KIND"
            and case["failure_kind"] == "STRUCTURAL_COLLAPSE"
            and not svc.has_approved_variance_for_site(site["id"],
                                                       "REPAIR_IN_KIND")):
        raise errors.ApiError(
            errors.ERR_VARIANCE_REQUIRED, 409,
            "An APPROVED REPAIR_IN_KIND variance is required for this site")
    # (15) REPLACEMENT requires an APPROVED replacement design for the site
    if remedy == "REPLACEMENT":
        if replacement is None:
            errors.fk_not_found(
                "replacement_design_id is required for the REPLACEMENT remedy")
        if replacement["status"] != "APPROVED":
            raise errors.ApiError(
                errors.ERR_REPLACEMENT_DESIGN_NOT_APPROVED, 409,
                "The replacement design must be APPROVED for this site")
    # (28) enumerated remedy payload
    if remedy not in ("REPAIR_IN_KIND", "REPLACEMENT"):
        raise errors.ApiError(errors.ERR_INVALID_DECISION, 400,
                              "remedy must be REPAIR_IN_KIND or REPLACEMENT")
    fields = {"remedy": remedy, "status": "TRIAGED"}
    if remedy == "REPLACEMENT":
        fields["replacement_design_id"] = replacement["id"]
    db.set_fields(case, **fields)
    if remedy == "REPLACEMENT":
        # provisional estimate: triage-time design row flow x cost-per-gpd
        db.set_fields(
            replacement,
            provisional_estimate_cents=svc.replacement_estimate_cents(
                replacement["design_daily_flow_gpd"]))
    return R.respond_object(case)


def begin_remediation(cid, cuid, sid, rid):
    site = H.resolve_site(cid, cuid, sid)
    case = H.resolve_repair(site, rid)
    # (5) state
    if case["status"] != "TRIAGED":
        errors.invalid_state("Only a TRIAGED repair case may begin remediation")
    # (6) site must be OPEN
    if site["status"] != "OPEN":
        raise errors.ApiError(errors.ERR_SITE_FROZEN, 409, "Site is not OPEN")
    # (27) REPLACEMENT requires an installation whose permit pins the design
    # (the case's replacement design, or a descendant amendment of it — §3.9's
    # "amended between triage and issuance" scenario must be reachable).
    if case["remedy"] == "REPLACEMENT":
        found = False
        for inst in svc.installations_of_site(site["id"]):
            permit = S["permits"].get(inst["permit_id"])
            if permit is None:
                continue
            pinned = S["designs"].get(permit["design_id"])
            if (pinned is not None and case["replacement_design_id"] is not None
                    and svc.design_descends_from(
                        pinned, case["replacement_design_id"])):
                found = True
                break
        if not found:
            raise errors.ApiError(
                errors.ERR_REMEDIATION_NOT_STARTED, 409,
                "No installation exists under a permit pinning the replacement design")
    db.set_fields(case, status="IN_REMEDIATION")
    return R.respond_object(case)


def resolve_repair_case(cid, cuid, sid, rid):
    site = H.resolve_site(cid, cuid, sid)
    case = H.resolve_repair(site, rid)
    b = mw.body()
    # (5) state: manual resolution is the REPAIR_IN_KIND path only
    if case["status"] != "IN_REMEDIATION" or case["remedy"] != "REPAIR_IN_KIND":
        errors.invalid_state(
            "Manual resolve is available only for a REPAIR_IN_KIND case in remediation")
    # (18) resolution note >= 20 chars
    mw.req_note(b, "resolution_note")
    db.set_fields(case, status="RESOLVED")
    return R.respond_object(case)


def close_repair_case(cid, cuid, sid, rid):
    site = H.resolve_site(cid, cuid, sid)
    case = H.resolve_repair(site, rid)
    # (5) state
    if case["status"] not in ("OPEN", "RESOLVED"):
        errors.invalid_state("Only an OPEN or RESOLVED repair case may be closed")
    db.set_fields(case, status="CLOSED")
    return R.respond_object(case)


def register(app):
    app.add_url_rule(BASE, "repair_create", mw.auth(*PM)(create_repair_case),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(BASE, "repair_list", mw.auth()(list_repair_cases),
                     methods=["GET"], strict_slashes=False)
    app.add_url_rule(BASE + "/<rid>", "repair_get", mw.auth()(get_repair_case),
                     methods=["GET"], strict_slashes=False)
    app.add_url_rule(BASE + "/<rid>/triage", "repair_triage",
                     mw.auth(*PM)(triage_repair_case),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(BASE + "/<rid>/begin-remediation", "repair_begin",
                     mw.auth(*PM)(begin_remediation),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(BASE + "/<rid>/resolve", "repair_resolve",
                     mw.auth(*PM)(resolve_repair_case),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(BASE + "/<rid>/close", "repair_close",
                     mw.auth(*PM)(close_repair_case),
                     methods=["POST"], strict_slashes=False)
