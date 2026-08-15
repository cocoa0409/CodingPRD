"""Platform-admin routes: logical clock, client accounts, jurisdiction profiles."""
from flask import Blueprint, request as flask_request

import errors
from db import store
from middleware import (
    as_enum, as_enum_list, as_int, as_str_list, auth, body,
    check_client_ownership, pagination_params, req_enum, req_int, req_str,
    require_role,
)
from response import ok, ok_list
from services import (
    COLLATERAL_CLASSES, NAME_RULES, client_json, jurisdiction_json, lapse_sweep,
    stamp_new, touch,
)
from util import fmt_dt, new_id, parse_dt

bp = Blueprint("admin", __name__)


def _paginate(records, serializer):
    limit, offset = pagination_params()
    items = [serializer(r) for r in records]
    return ok_list(items[offset:offset + limit], len(items), limit, offset)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    auth()
    data = body()
    if "to_iso8601" not in data or data["to_iso8601"] is None:
        raise errors.err_invalid_request("Missing required field: to_iso8601")
    target = parse_dt(data["to_iso8601"])
    if target is None:
        raise errors.err_invalid_request("to_iso8601 must be an ISO 8601 datetime")
    _user_id, role = auth()
    require_role(role, "PlatformAdmin")
    store.clock = target
    lapse_sweep()
    return ok({"current_utc": fmt_dt(store.clock)})


# ---------------------------------------------------------------------------
# Client accounts
# ---------------------------------------------------------------------------

@bp.post("/client-accounts")
def create_client():
    auth()
    data = body()
    name = req_str(data, "name")
    _user_id, role = auth()
    require_role(role, "PlatformAdmin")
    client = stamp_new({
        "id": new_id(),
        "name": name,
        "status": "ACTIVE",
        "fees_charged_total_cents": 0,
        "fees_refunded_total_cents": 0,
    })
    store.clients[client["id"]] = client
    return ok(client_json(client), 201)


@bp.get("/client-accounts")
def list_clients():
    auth()
    return _paginate(list(store.clients.values()), client_json)


@bp.get("/client-accounts/<client_id>")
def get_client(client_id):
    user_id, role = auth()
    check_client_ownership(role, user_id, client_id)
    client = store.clients.get(client_id)
    if client is None:
        raise errors.err_not_found("client")
    return ok(client_json(client))


@bp.post("/client-accounts/<client_id>/suspend")
def suspend_client(client_id):
    auth()
    body()
    _user_id, role = auth()
    require_role(role, "PlatformAdmin")
    client = store.clients.get(client_id)
    if client is None:
        raise errors.err_not_found("client")
    if client["status"] != "ACTIVE":
        raise errors.err_request_invalid_state("Client must be ACTIVE to be suspended")
    client["status"] = "SUSPENDED"
    touch(client)
    return ok(client_json(client))


@bp.post("/client-accounts/<client_id>/reinstate")
def reinstate_client(client_id):
    auth()
    body()
    _user_id, role = auth()
    require_role(role, "PlatformAdmin")
    client = store.clients.get(client_id)
    if client is None:
        raise errors.err_not_found("client")
    if client["status"] != "SUSPENDED":
        raise errors.err_request_invalid_state("Client must be SUSPENDED to be reinstated")
    client["status"] = "ACTIVE"
    touch(client)
    return ok(client_json(client))


# ---------------------------------------------------------------------------
# Jurisdiction profiles
# ---------------------------------------------------------------------------

@bp.post("/jurisdiction-profiles")
def create_jurisdiction():
    auth()
    data = body()
    # Structural validation (priority 2).
    state_code = req_str(data, "state_code")
    base_fee = req_int(data, "base_fee_cents")
    per_addl = req_int(data, "per_additional_debtor_fee_cents")
    county_surcharge = req_int(data, "county_surcharge_cents")
    classes = as_enum_list(data.get("county_filing_collateral_classes"),
                           "county_filing_collateral_classes", COLLATERAL_CLASSES)
    counties = as_str_list(data.get("county_names"), "county_names")
    name_rule = req_enum(data, "individual_name_rule", NAME_RULES)
    capacity = req_int(data, "expedited_daily_capacity")
    _user_id, role = auth()
    require_role(role, "PlatformAdmin")
    if state_code in store.jurisdiction_by_code:
        raise errors.err_duplicate_state_code()
    profile = stamp_new({
        "id": new_id(),
        "state_code": state_code,
        "base_fee_cents": base_fee,
        "per_additional_debtor_fee_cents": per_addl,
        "county_surcharge_cents": county_surcharge,
        "county_filing_collateral_classes": classes,
        "county_names": counties,
        "individual_name_rule": name_rule,
        "expedited_daily_capacity": capacity,
    })
    store.jurisdictions[profile["id"]] = profile
    store.jurisdiction_by_code[profile["state_code"]] = profile
    return ok(jurisdiction_json(profile), 201)


@bp.get("/jurisdiction-profiles")
def list_jurisdictions():
    auth()
    records = list(store.jurisdictions.values())
    state_code = flask_request.args.get("state_code")
    if state_code is not None:
        records = [p for p in records if p["state_code"] == state_code]
    return _paginate(records, jurisdiction_json)


@bp.get("/jurisdiction-profiles/<profile_id>")
def get_jurisdiction(profile_id):
    auth()
    profile = store.jurisdictions.get(profile_id)
    if profile is None:
        raise errors.err_not_found("jurisdiction")
    return ok(jurisdiction_json(profile))


@bp.put("/jurisdiction-profiles/<profile_id>")
def update_jurisdiction(profile_id):
    auth()
    data = body()
    # Structural validation of any provided fields (priority 2).
    fields = {}
    if "base_fee_cents" in data and data["base_fee_cents"] is not None:
        fields["base_fee_cents"] = as_int(data["base_fee_cents"], "base_fee_cents")
    if "per_additional_debtor_fee_cents" in data and data["per_additional_debtor_fee_cents"] is not None:
        fields["per_additional_debtor_fee_cents"] = as_int(
            data["per_additional_debtor_fee_cents"], "per_additional_debtor_fee_cents")
    if "county_surcharge_cents" in data and data["county_surcharge_cents"] is not None:
        fields["county_surcharge_cents"] = as_int(data["county_surcharge_cents"], "county_surcharge_cents")
    if "expedited_daily_capacity" in data and data["expedited_daily_capacity"] is not None:
        fields["expedited_daily_capacity"] = as_int(data["expedited_daily_capacity"], "expedited_daily_capacity")
    if "county_filing_collateral_classes" in data and data["county_filing_collateral_classes"] is not None:
        fields["county_filing_collateral_classes"] = as_enum_list(
            data["county_filing_collateral_classes"], "county_filing_collateral_classes", COLLATERAL_CLASSES)
    if "county_names" in data and data["county_names"] is not None:
        fields["county_names"] = as_str_list(data["county_names"], "county_names")
    if "individual_name_rule" in data and data["individual_name_rule"] is not None:
        fields["individual_name_rule"] = as_enum(data["individual_name_rule"], "individual_name_rule", NAME_RULES)
    _user_id, role = auth()
    require_role(role, "PlatformAdmin")
    profile = store.jurisdictions.get(profile_id)
    if profile is None:
        raise errors.err_not_found("jurisdiction")
    for k, v in fields.items():
        profile[k] = v
    touch(profile)
    return ok(jurisdiction_json(profile))
