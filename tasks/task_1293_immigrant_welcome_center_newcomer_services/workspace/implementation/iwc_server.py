"""Immigrant Welcome Center & Newcomer Services API — Flask entry point."""
import os
import traceback

from flask import Flask

import db
from envelope import error_response, ok
from errors import ApiError

from routes.ops import bp as ops_bp
from routes.registry import bp as registry_bp
from routes.cases import bp as cases_bp
from routes.notes_consents import bp as notes_bp
from routes.referrals import bp as referrals_bp
from routes.programs import bp as programs_bp
from routes.screenings_reports import bp as screenings_bp


def serialize_decimals(obj):
    """Flask's JSON encoder handles str/int/float; Decimal needs conversion."""
    from decimal import Decimal
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: serialize_decimals(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [serialize_decimals(v) for v in obj]
    return obj


class DecimalSafeJSONProvider:  # placeholder, replaced below
    pass


def _make_provider(app):
    from flask.json.provider import DefaultJSONProvider

    class Provider(DefaultJSONProvider):
        def dumps(self, obj, **kwargs):
            return super().dumps(serialize_decimals(obj), **kwargs)

    return Provider(app)


def create_app():
    app = Flask(__name__)
    app.json = _make_provider(app)
    app.url_map.strict_slashes = False

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404,
                                       "resource not found"))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404,
                                       "method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        traceback.print_exc()
        return error_response(ApiError("ERR_INVALID_REQUEST", 400,
                                       f"unexpected error: {err}"))

    for bp in (ops_bp, registry_bp, cases_bp, notes_bp, referrals_bp,
               programs_bp, screenings_bp):
        app.register_blueprint(bp)

    # Serialize all requests through one lock so cascades stay atomic.
    @app.before_request
    def _acquire():
        db.LOCK.acquire()

    @app.teardown_request
    def _release(exc):
        try:
            db.LOCK.release()
        except RuntimeError:
            pass

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
