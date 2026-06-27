"""StateRule create/upsert and reads (PRD §3.4)."""
import app as A
import errors
import middleware
import response
import services
from app import app
from db import store


def _bool_or(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise errors.invalid_request(f"{name} must be a boolean.")
    return v


@app.route("/state-rules", methods=["POST"])
def create_state_rule():
    middleware.require_roles({A.R_COMPLIANCE, A.R_ADMIN})
    body = A.get_body()
    state_code = A.require_str(body, "state_code")
    if not A.is_two_letter_state(state_code):
        raise errors.invalid_request("state_code must be two uppercase letters.")

    ship_allowed = _bool_or(body, "ship_allowed", True)
    growler_keg_allowed = _bool_or(body, "growler_keg_allowed", True)
    requires_sig = _bool_or(body, "requires_adult_signature", True)
    monthly_cap = body.get("monthly_volume_limit_ml", None)
    if monthly_cap is not None:
        if isinstance(monthly_cap, bool) or not isinstance(monthly_cap, int):
            raise errors.invalid_request("monthly_volume_limit_ml must be an integer or null.")
        if monthly_cap < 1:
            raise errors.invalid_request("monthly_volume_limit_ml must be >= 1.")

    # Upsert: creating a rule for an existing state_code updates it in place.
    existing = services.state_rule_by_code(state_code)
    if existing is not None:
        existing["ship_allowed"] = ship_allowed
        existing["growler_keg_allowed"] = growler_keg_allowed
        existing["requires_adult_signature"] = requires_sig
        existing["monthly_volume_limit_ml"] = monthly_cap
        A.touch(existing)
        return response.object_response(A.public(existing), 201)

    rec = {
        "state_code": state_code,
        "ship_allowed": ship_allowed,
        "growler_keg_allowed": growler_keg_allowed,
        "monthly_volume_limit_ml": monthly_cap,
        "requires_adult_signature": requires_sig,
    }
    A.stamp_create(rec)
    store.state_rules[rec["id"]] = rec
    return response.object_response(A.public(rec), 201)


@app.route("/state-rules/<rid>", methods=["GET"])
def get_state_rule(rid):
    middleware.require_roles({A.R_CUSTOMER, A.R_ASSOCIATE, A.R_COMPLIANCE, A.R_ADMIN})
    rec = A.get_or_404(store.state_rules, rid)
    return response.object_response(A.public(rec))


@app.route("/state-rules", methods=["GET"])
def list_state_rules():
    middleware.require_roles({A.R_CUSTOMER, A.R_ASSOCIATE, A.R_COMPLIANCE, A.R_ADMIN})
    limit, offset = A.get_pagination()
    items = list(store.state_rules.values())
    state_code = A.request.args.get("state_code")
    if state_code is not None:
        items = [r for r in items if r["state_code"] == state_code]
    items = A.sort_created(items)
    page, total = A.paginate(items, limit, offset)
    return response.array_response(A.public_list(page), limit, offset, total)
