"""Every GET list and detail endpoint (PRD 4)."""
from flask import Blueprint, g, request

from core import (ApiError, DB, ROLE_CLIENT_SPONSOR, ROLE_COMPLIANCE_AUDITOR, ROLE_FITNESS_STAFF,
                 ROLE_MEMBER, ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER, bad_request, find,
                 get_or_404, ok, paginate, parse_dt, require, scope_contract, view, where)

bp = Blueprint("reads", __name__)

ALL_STAFF_READ = (ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER, ROLE_COMPLIANCE_AUDITOR)


# --------------------------------------------------------------------------
# Filter helpers
# --------------------------------------------------------------------------
def _eq_filters(rows, mapping):
    """mapping: query-parameter name -> record field name."""
    for param, field in mapping.items():
        raw = request.args.get(param)
        if raw is None or raw == "":
            continue
        rows = [r for r in rows if str(r.get(field)) == str(raw)]
    return rows


def _instant_arg(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    parsed = parse_dt(raw)
    if parsed is None:
        raise bad_request("%s must be an ISO-8601 instant" % name)
    return parsed


def _window(rows, field, after_param, before_param):
    after = _instant_arg(after_param)
    before = _instant_arg(before_param)
    if after is not None:
        rows = [r for r in rows if r.get(field) is not None and r[field] >= after]
    if before is not None:
        rows = [r for r in rows if r.get(field) is not None and r[field] <= before]
    return rows


def _own_contract_only(rows):
    if g.role == ROLE_CLIENT_SPONSOR:
        return [r for r in rows if r.get("contract_id") == g.user_id]
    return rows


# --------------------------------------------------------------------------
# Contracts
# --------------------------------------------------------------------------
@bp.get("/client-contracts")
def list_contracts():
    require(ROLE_OPERATOR_ADMIN, ROLE_COMPLIANCE_AUDITOR, ROLE_CLIENT_SPONSOR, ROLE_SITE_MANAGER)
    rows = DB.all("contract")
    rows = _eq_filters(rows, {"status": "status", "fee_structure": "fee_structure",
                              "client_name": "client_name",
                              "supersedes_contract_id": "supersedes_contract_id"})
    if g.role == ROLE_CLIENT_SPONSOR:
        rows = [r for r in rows if r["id"] == g.user_id]
    return paginate(rows)


@bp.get("/client-contracts/<cid>")
def get_contract(cid):
    require(ROLE_OPERATOR_ADMIN, ROLE_COMPLIANCE_AUDITOR, ROLE_CLIENT_SPONSOR, ROLE_SITE_MANAGER)
    contract = get_or_404("contract", cid)
    scope_contract(contract["id"])
    return ok(view(contract))


# --------------------------------------------------------------------------
# Staff and credentials
# --------------------------------------------------------------------------
@bp.get("/staff-members")
def list_staff():
    require(*ALL_STAFF_READ)
    rows = _eq_filters(DB.all("staff"), {"contract_id": "contract_id",
                                         "duty_status": "duty_status",
                                         "role_type": "role_type"})
    return paginate(rows)


@bp.get("/staff-members/<sid>")
def get_staff(sid):
    require(*ALL_STAFF_READ)
    return ok(view(get_or_404("staff", sid)))


@bp.get("/staff-members/<sid>/credentials")
def list_staff_credentials(sid):
    require(*ALL_STAFF_READ)
    staff = get_or_404("staff", sid)
    rows = _eq_filters(where("credential", staff_member_id=staff["id"]),
                       {"status": "status", "credential_type": "credential_type"})
    return paginate(rows)


@bp.get("/staff-credentials/<cid>")
def get_credential(cid):
    require(*ALL_STAFF_READ)
    return ok(view(get_or_404("credential", cid)))


# --------------------------------------------------------------------------
# Facility
# --------------------------------------------------------------------------
@bp.get("/facility-rooms")
def list_rooms():
    require(ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER, ROLE_COMPLIANCE_AUDITOR, ROLE_CLIENT_SPONSOR)
    rows = _eq_filters(DB.all("room"), {"contract_id": "contract_id",
                                        "room_state": "room_state",
                                        "room_type": "room_type"})
    return paginate(_own_contract_only(rows))


@bp.get("/facility-rooms/<rid>")
def get_room(rid):
    require(ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER, ROLE_COMPLIANCE_AUDITOR, ROLE_CLIENT_SPONSOR)
    room = get_or_404("room", rid)
    scope_contract(room["contract_id"])
    return ok(view(room))


@bp.get("/facility-assets")
def list_assets():
    require(*ALL_STAFF_READ)
    rows = _eq_filters(DB.all("asset"), {"contract_id": "contract_id", "room_id": "room_id",
                                         "asset_type": "asset_type", "status": "status",
                                         "readiness_status": "readiness_status"})
    return paginate(rows)


@bp.get("/facility-assets/<aid>")
def get_asset(aid):
    require(*ALL_STAFF_READ)
    return ok(view(get_or_404("asset", aid)))


# --------------------------------------------------------------------------
# Programming
# --------------------------------------------------------------------------
@bp.get("/program-offerings")
def list_offerings():
    require(ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER, ROLE_CLIENT_SPONSOR, ROLE_COMPLIANCE_AUDITOR)
    rows = _eq_filters(DB.all("offering"), {"contract_id": "contract_id",
                                            "lead_staff_id": "lead_staff_id",
                                            "status": "status",
                                            "program_type": "program_type"})
    return paginate(_own_contract_only(rows))


@bp.get("/program-offerings/<oid>")
def get_offering(oid):
    require(ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER, ROLE_CLIENT_SPONSOR, ROLE_COMPLIANCE_AUDITOR)
    offering = get_or_404("offering", oid)
    scope_contract(offering["contract_id"])
    return ok(view(offering))


@bp.get("/program-sessions")
def list_sessions():
    require(ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER, ROLE_FITNESS_STAFF, ROLE_CLIENT_SPONSOR,
            ROLE_COMPLIANCE_AUDITOR)
    rows = _eq_filters(DB.all("session"), {"offering_id": "offering_id", "room_id": "room_id",
                                           "status": "status"})
    rows = _window(rows, "scheduled_start_utc", "starts_after", "starts_before")
    if g.role == ROLE_CLIENT_SPONSOR:
        kept = []
        for session in rows:
            offering = find("offering", session["offering_id"])
            if offering is not None and offering["contract_id"] == g.user_id:
                kept.append(session)
        rows = kept
    return paginate(rows)


@bp.get("/program-sessions/<sid>")
def get_session(sid):
    require(ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER, ROLE_FITNESS_STAFF, ROLE_CLIENT_SPONSOR,
            ROLE_COMPLIANCE_AUDITOR)
    session = get_or_404("session", sid)
    offering = find("offering", session["offering_id"])
    if offering is not None:
        scope_contract(offering["contract_id"])
    return ok(view(session))


@bp.get("/staff-assignments")
def list_assignments():
    require(ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER, ROLE_FITNESS_STAFF, ROLE_COMPLIANCE_AUDITOR)
    rows = _eq_filters(DB.all("assignment"), {"session_id": "session_id",
                                              "staff_member_id": "staff_member_id",
                                              "status": "status",
                                              "role_on_session": "role_on_session"})
    return paginate(rows)


@bp.get("/staff-assignments/<aid>")
def get_assignment(aid):
    require(ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER, ROLE_FITNESS_STAFF, ROLE_COMPLIANCE_AUDITOR)
    return ok(view(get_or_404("assignment", aid)))


# --------------------------------------------------------------------------
# Members, waivers
# --------------------------------------------------------------------------
@bp.get("/members")
def list_members():
    require(ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER, ROLE_CLIENT_SPONSOR, ROLE_COMPLIANCE_AUDITOR)
    rows = _eq_filters(DB.all("member"), {"contract_id": "contract_id",
                                          "sponsor_member_id": "sponsor_member_id",
                                          "member_class": "member_class",
                                          "eligibility_status": "eligibility_status",
                                          "access_status": "access_status"})
    return paginate(_own_contract_only(rows))


@bp.get("/members/<mid>")
def get_member(mid):
    require(ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER, ROLE_CLIENT_SPONSOR, ROLE_COMPLIANCE_AUDITOR,
            ROLE_MEMBER)
    member = get_or_404("member", mid)
    if g.role == ROLE_MEMBER:
        if g.user_id != member["id"]:
            raise ApiError("ERR_FORBIDDEN_SCOPE", 403)
    else:
        scope_contract(member["contract_id"])
    return ok(view(member))


@bp.get("/members/<mid>/waivers")
def list_member_waivers(mid):
    require(ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER, ROLE_COMPLIANCE_AUDITOR, ROLE_MEMBER)
    member = get_or_404("member", mid)
    if g.role == ROLE_MEMBER and g.user_id != member["id"]:
        raise ApiError("ERR_FORBIDDEN_SCOPE", 403)
    rows = _eq_filters(where("waiver", member_id=member["id"]), {"status": "status"})
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]), reverse=True)
    return paginate(rows)


@bp.get("/liability-waivers/<wid>")
def get_waiver(wid):
    require(ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER, ROLE_COMPLIANCE_AUDITOR, ROLE_MEMBER)
    waiver = get_or_404("waiver", wid)
    if g.role == ROLE_MEMBER and g.user_id != waiver["member_id"]:
        raise ApiError("ERR_FORBIDDEN_SCOPE", 403)
    return ok(view(waiver))


# --------------------------------------------------------------------------
# Participation (with the health-note projection of PRD 2.10)
# --------------------------------------------------------------------------
def _participation_view(record):
    data = view(record)
    if g.role == ROLE_COMPLIANCE_AUDITOR:
        return data
    if g.role == ROLE_MEMBER and g.user_id == record["member_id"]:
        return data
    data["health_metrics_note"] = None
    return data


@bp.get("/participation-records")
def list_participation():
    require(ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER, ROLE_FITNESS_STAFF, ROLE_COMPLIANCE_AUDITOR,
            ROLE_MEMBER)
    rows = _eq_filters(DB.all("participation"), {"member_id": "member_id",
                                                 "session_id": "session_id",
                                                 "status": "status"})
    rows = _window(rows, "check_in_utc", "checked_in_after", "checked_in_before")
    if g.role == ROLE_MEMBER:
        rows = [r for r in rows if r["member_id"] == g.user_id]
    return paginate(rows, _participation_view)


@bp.get("/participation-records/<pid>")
def get_participation(pid):
    require(ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER, ROLE_FITNESS_STAFF, ROLE_COMPLIANCE_AUDITOR,
            ROLE_MEMBER)
    record = get_or_404("participation", pid)
    if g.role == ROLE_MEMBER and g.user_id != record["member_id"]:
        raise ApiError("ERR_FORBIDDEN_SCOPE", 403)
    return ok(_participation_view(record))


# --------------------------------------------------------------------------
# Incidents, invoices
# --------------------------------------------------------------------------
@bp.get("/incident-reports")
def list_incidents():
    require(*ALL_STAFF_READ)
    rows = _eq_filters(DB.all("incident"), {"contract_id": "contract_id",
                                            "member_id": "member_id",
                                            "reported_by_staff_id": "reported_by_staff_id",
                                            "asset_id": "asset_id", "status": "status",
                                            "severity": "severity",
                                            "cause_category": "cause_category"})
    return paginate(rows)


@bp.get("/incident-reports/<iid>")
def get_incident(iid):
    require(*ALL_STAFF_READ)
    return ok(view(get_or_404("incident", iid)))


@bp.get("/monthly-invoices")
def list_invoices():
    require(ROLE_OPERATOR_ADMIN, ROLE_CLIENT_SPONSOR, ROLE_COMPLIANCE_AUDITOR)
    rows = _eq_filters(DB.all("invoice"), {"contract_id": "contract_id", "status": "status",
                                           "period_month": "period_month"})
    return paginate(_own_contract_only(rows))


@bp.get("/monthly-invoices/<iid>")
def get_invoice(iid):
    require(ROLE_OPERATOR_ADMIN, ROLE_CLIENT_SPONSOR, ROLE_COMPLIANCE_AUDITOR)
    invoice = get_or_404("invoice", iid)
    scope_contract(invoice["contract_id"])
    return ok(view(invoice))
