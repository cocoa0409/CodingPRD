"""Assignment endpoints — actions live in services.dispatch / services.delivery."""
from ..auth import parse_headers, require_role
from ..envelope import success
from ..errors import fail
from ..server import store


def register(app, prefix):
    app.add_url_rule("/api/assignments/<aid>", endpoint=f"{prefix}.read", view_func=read, methods=["GET"])
    app.add_url_rule("/api/assignments/<aid>/accept", endpoint=f"{prefix}.accept", view_func=accept, methods=["POST"])
    app.add_url_rule("/api/assignments/<aid>/reject", endpoint=f"{prefix}.reject", view_func=reject, methods=["POST"])
    app.add_url_rule("/api/assignments/<aid>/pickup", endpoint=f"{prefix}.pickup", view_func=pickup, methods=["POST"])
    app.add_url_rule("/api/assignments/<aid>/deliver", endpoint=f"{prefix}.deliver", view_func=deliver, methods=["POST"])
    app.add_url_rule("/api/assignments/<aid>/cancel", endpoint=f"{prefix}.cancel", view_func=cancel, methods=["POST"])


def read(aid):
    user_id, role = parse_headers()
    require_role("PlatformAdmin", "Rider", "CustomerService")
    a = store.assignments.get(aid)
    if not a:
        raise fail("ERR_NOT_FOUND")
    if role == "Rider" and user_id != a["rider_id"]:
        raise fail("ERR_FORBIDDEN")
    return success(a)


def accept(aid):
    from ..services.dispatch import accept_assignment
    return accept_assignment(aid)


def reject(aid):
    from ..services.dispatch import reject_assignment
    return reject_assignment(aid)


def pickup(aid):
    from ..services.dispatch import pickup_assignment
    return pickup_assignment(aid)


def deliver(aid):
    from ..services.delivery import deliver_assignment
    return deliver_assignment(aid)


def cancel(aid):
    from ..services.dispatch import cancel_assignment
    return cancel_assignment(aid)
