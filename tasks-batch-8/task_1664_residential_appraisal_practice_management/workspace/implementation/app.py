"""Flask entry point: auth ladder rungs 1-2, route registration, envelope."""

import os

from flask import Flask, request

import envelope
import store
from errors import ApiError
from services import ROLES


def _row_payload(row):
    payload = store.public(row)
    if "sanction_override" in payload:
        # Appraiser rows carry the computed standing (PRD 3.2: computed, never
        # stored by hand) and the no-show performance counter (PRD 3.4:
        # marking an appointment NO_SHOW "increments the appraiser's
        # no_show_count").
        import services
        payload["standing"] = services.compute_standing(row)
        payload["no_show_count"] = sum(
            1 for a in store.appointments.values()
            if a["appraiser_id"] == row["id"] and a["status"] == "NO_SHOW"
        )
    return payload


def obj(data, status=200):
    return envelope.object_response(_row_payload(data) if isinstance(data, dict) and "id" in data else data, status)


def listing(rows, args):
    window, limit, offset, total = envelope.paginate(store.ordered(rows), args)
    return envelope.array_response([_row_payload(r) for r in window], limit, offset, total)


def read_body():
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


class Auth(object):
    """Ladder rungs 1-2 (PRD 2.7): authentication then role authorization."""

    def __init__(self):
        self.user_id = None
        self.role = None

    def authenticate(self):
        role = request.headers.get("X-User-Role")
        user_id = request.headers.get("X-User-ID")
        if (
            role is None or not str(role).strip()
            or user_id is None or not str(user_id).strip()
            or role not in ROLES
        ):
            raise ApiError("ERR_UNAUTHENTICATED")
        self.role = role
        self.user_id = user_id

    def require_roles(self, *roles):
        if self.role not in roles:
            raise ApiError("ERR_FORBIDDEN_ROLE")


auth = Auth()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _authenticate():
        auth.authenticate()

    from routes import register_routes
    register_routes(app)
    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return envelope.error_response("ERR_VALIDATION", "No such route.", 404)

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return envelope.error_response("ERR_VALIDATION", "Method not allowed.", 405)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
