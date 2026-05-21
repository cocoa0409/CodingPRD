"""Return endpoints — most logic lives in services.refunds."""
from ..auth import parse_headers, require_role
from ..envelope import success
from ..errors import fail
from ..server import store


def register(app, prefix):
    app.add_url_rule("/api/returns/<rid>", endpoint=f"{prefix}.read", view_func=read, methods=["GET"])
    app.add_url_rule("/api/returns/<rid>/approve", endpoint=f"{prefix}.approve", view_func=approve, methods=["POST"])
    app.add_url_rule("/api/returns/<rid>/reject", endpoint=f"{prefix}.reject", view_func=reject, methods=["POST"])
    app.add_url_rule("/api/returns/<rid>/escalate", endpoint=f"{prefix}.escalate", view_func=escalate, methods=["POST"])
    app.add_url_rule("/api/returns/<rid>/reopen", endpoint=f"{prefix}.reopen", view_func=reopen, methods=["POST"])


def read(rid):
    user_id, role = parse_headers()
    require_role("PlatformAdmin", "Customer", "Restaurant", "CustomerService")
    ret = store.returns.get(rid)
    if not ret:
        raise fail("ERR_NOT_FOUND")
    o = store.orders[ret["order_id"]]
    if role == "Customer" and user_id != o["customer_id"]:
        raise fail("ERR_FORBIDDEN")
    if role == "Restaurant" and user_id != o["restaurant_id"]:
        raise fail("ERR_FORBIDDEN")
    return success(ret)


def approve(rid):
    from ..services.refunds import approve_return
    return approve_return(rid)


def reject(rid):
    from ..services.refunds import reject_return
    return reject_return(rid)


def escalate(rid):
    from ..services.refunds import escalate_return
    return escalate_return(rid)


def reopen(rid):
    from ..services.refunds import reopen_return
    return reopen_return(rid)
