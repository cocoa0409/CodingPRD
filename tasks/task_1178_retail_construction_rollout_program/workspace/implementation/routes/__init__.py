"""Shared route plumbing + blueprint registration."""
from flask import request

from errors import invalid_state, already_terminal, invalid_request
from response import paginate
from util import serialize, sort_key


def require_state(entity, allowed, terminal):
    """Step-5 from-state guard: terminal states reject all transitions."""
    st = entity["status"]
    if st in allowed:
        return st
    if st in terminal:
        already_terminal("resource is in terminal state %s" % st)
    invalid_state("transition not allowed from state %s" % st)


def apply_filters(items, mapping):
    """mapping: list of (query_param, entity_field, kind); kind 'str' or 'int'.
    Exact-match filtering; malformed int filters are a request-shape error."""
    for param, field, kind in mapping:
        raw = request.args.get(param)
        if raw is None:
            continue
        if kind == "int":
            try:
                value = int(raw)
            except (TypeError, ValueError):
                invalid_request("query param '%s' must be an integer" % param)
            items = [e for e in items if e.get(field) == value]
        else:
            items = [e for e in items if e.get(field) == raw]
    return items


def list_response(collection, mapping=()):
    items = sorted(collection.values(), key=sort_key)
    items = apply_filters(items, mapping)
    return paginate([serialize(e) for e in items])


def register_blueprints(app):
    from routes.admin import bp as admin_bp
    from routes.programs import bp as programs_bp
    from routes.markets import bp as markets_bp
    from routes.municipalities import bp as municipalities_bp
    from routes.sites import bp as sites_bp
    from routes.drawings import bp as drawings_bp
    from routes.permits import bp as permits_bp
    from routes.contractors import bp as contractors_bp
    from routes.bid_packages import bp as bid_packages_bp
    from routes.bids import bp as bids_bp
    from routes.mobilizations import bp as mobilizations_bp
    from routes.change_orders import bp as change_orders_bp
    from routes.punch_items import bp as punch_items_bp
    from routes.turnovers import bp as turnovers_bp
    from routes.commitments import bp as commitments_bp

    for bp in (admin_bp, programs_bp, markets_bp, municipalities_bp, sites_bp,
               drawings_bp, permits_bp, contractors_bp, bid_packages_bp,
               bids_bp, mobilizations_bp, change_orders_bp, punch_items_bp,
               turnovers_bp, commitments_bp):
        app.register_blueprint(bp)
