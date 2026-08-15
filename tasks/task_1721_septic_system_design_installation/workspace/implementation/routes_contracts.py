"""Maintenance contracts and service visits."""

import db
import errors
import helpers as H
import middleware as mw
import response as R
import services as svc

S = db.STORE
BASE = "/septic-ops/installer-companies/<cid>/customers/<cuid>/sites/<sid>/maintenance-contracts"
PM = ("ProjectManager",)


def create_contract(cid, cuid, sid):
    site = H.resolve_site(cid, cuid, sid)
    b = mw.body()
    # (4) FK: installation within this site
    inst = H.fk_site_row("installations", site, b.get("installation_id"))
    # (19) ranges: window monotonicity and positive fee
    start_period = mw.req_int(b, "start_period")
    end_period = mw.req_int(b, "end_period")
    annual_fee_cents = mw.req_int(b, "annual_fee_cents")
    if end_period <= start_period:
        errors.invalid_request("end_period must be > start_period")
    if annual_fee_cents <= 0:
        errors.invalid_request("annual_fee_cents must be > 0")
    # (29) creation-scope state: installation must be COMPLETED
    if inst["status"] != "COMPLETED":
        errors.invalid_state(
            "A maintenance contract requires a COMPLETED installation")
    rec = db.create_record("maintenance_contracts", {
        "site_id": site["id"],
        "customer_id": site["customer_id"],
        "installation_id": inst["id"],
        "start_period": start_period,
        "end_period": end_period,
        "annual_fee_cents": annual_fee_cents,
        "prorated_fee_cents": svc.prorate_fee_cents(
            annual_fee_cents, start_period, end_period),
        "status": "ACTIVE",
    })
    return R.respond_object(rec, 201)


def list_contracts(cid, cuid, sid):
    site = H.resolve_site(cid, cuid, sid)
    rows = H.children("maintenance_contracts", "site_id", site["id"])
    rows = H.apply_filters(rows, {"status": "status"})
    return R.respond_list(rows)


def get_contract(cid, cuid, sid, mcid):
    site = H.resolve_site(cid, cuid, sid)
    return R.respond_object(H.resolve_contract(site, mcid))


def renew_contract(cid, cuid, sid, mcid):
    site = H.resolve_site(cid, cuid, sid)
    contract = H.resolve_contract(site, mcid)
    b = mw.body()
    # (5) state
    if contract["status"] != "LAPSED":
        errors.invalid_state("Only a LAPSED contract may be renewed")
    new_end = b.get("new_end_period")
    if not isinstance(new_end, int) or isinstance(new_end, bool):
        errors.invalid_request("new_end_period is required and must be an integer")
    # (22) renewal monotonicity
    if new_end <= contract["end_period"]:
        raise errors.ApiError(errors.ERR_INVALID_RENEWAL, 400,
                              "new_end_period must be greater than end_period")
    # (25) OCC
    expected = b.get("expected_contract_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        errors.invalid_request(
            "expected_contract_version is required and must be an integer")
    if expected != contract["version"]:
        raise errors.ApiError(errors.ERR_STALE_VERSION, 412,
                              "expected_contract_version does not match the current version")
    db.set_fields(contract,
                  end_period=new_end,
                  prorated_fee_cents=svc.prorate_fee_cents(
                      contract["annual_fee_cents"], contract["start_period"], new_end),
                  status="ACTIVE")
    return R.respond_object(contract)


def cancel_contract(cid, cuid, sid, mcid):
    site = H.resolve_site(cid, cuid, sid)
    contract = H.resolve_contract(site, mcid)
    # (5) state
    if contract["status"] != "ACTIVE":
        errors.invalid_state("Only an ACTIVE contract may be cancelled")
    db.set_fields(contract, status="CANCELLED")
    # delete future visits (visit_period > current); retain past visits
    future = [v for v in H.children("maintenance_visits", "contract_id", contract["id"])
              if v["visit_period"] > site["current_period_index"]]
    for v in future:
        del S["maintenance_visits"][v["id"]]
    return R.respond_object(contract)


def create_visit(cid, cuid, sid, mcid):
    site = H.resolve_site(cid, cuid, sid)
    contract = H.resolve_contract(site, mcid)
    b = mw.body()
    visit_period = b.get("visit_period")
    # (17) contract ACTIVE and visit inside the inclusive coverage window
    if (contract["status"] != "ACTIVE"
            or not isinstance(visit_period, int) or isinstance(visit_period, bool)
            or visit_period < contract["start_period"]
            or visit_period > contract["end_period"]):
        raise errors.ApiError(
            errors.ERR_VISIT_OUTSIDE_CONTRACT, 409,
            "visit_period must lie inside the coverage window of an ACTIVE contract")
    # (19) field types
    findings = mw.req_str(b, "findings")
    alarm_condition = mw.req_bool(b, "alarm_condition")
    technician_name = mw.req_str(b, "technician_name")
    rec = db.create_record("maintenance_visits", {
        "contract_id": contract["id"],
        "visit_period": visit_period,
        "findings": findings,
        "alarm_condition": alarm_condition,
        "technician_name": technician_name,
    })
    return R.respond_object(rec, 201)


def list_visits(cid, cuid, sid, mcid):
    site = H.resolve_site(cid, cuid, sid)
    contract = H.resolve_contract(site, mcid)
    return R.respond_list(H.children("maintenance_visits", "contract_id",
                                     contract["id"]))


def get_visit(cid, cuid, sid, mcid, vid):
    site = H.resolve_site(cid, cuid, sid)
    contract = H.resolve_contract(site, mcid)
    return R.respond_object(H.resolve_visit(contract, vid))


def register(app):
    app.add_url_rule(BASE, "contract_create", mw.auth(*PM)(create_contract),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(BASE, "contract_list", mw.auth()(list_contracts),
                     methods=["GET"], strict_slashes=False)
    app.add_url_rule(BASE + "/<mcid>", "contract_get", mw.auth()(get_contract),
                     methods=["GET"], strict_slashes=False)
    app.add_url_rule(BASE + "/<mcid>/renew", "contract_renew",
                     mw.auth(*PM)(renew_contract),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(BASE + "/<mcid>/cancel", "contract_cancel",
                     mw.auth(*PM)(cancel_contract),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(BASE + "/<mcid>/visits", "visit_create",
                     mw.auth(*PM)(create_visit),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(BASE + "/<mcid>/visits", "visit_list",
                     mw.auth()(list_visits),
                     methods=["GET"], strict_slashes=False)
    app.add_url_rule(BASE + "/<mcid>/visits/<vid>", "visit_get",
                     mw.auth()(get_visit),
                     methods=["GET"], strict_slashes=False)
