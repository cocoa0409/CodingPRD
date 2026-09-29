"""Contact-Centre Quality Monitoring and Coaching API.

Flask application factory and error handling.  Storage is in-memory only:
every process start begins with an empty store and the logical clock at
2026-08-01T00:00:00Z (PRD 2.4).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from common import ApiError, error_response
import routes_calibration
import routes_clock
import routes_coaching
import routes_disputes
import routes_evaluations
import routes_forms
import routes_interactions
import routes_people
import routes_sampling


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(routes_forms.bp)
    app.register_blueprint(routes_people.bp)
    app.register_blueprint(routes_interactions.bp)
    app.register_blueprint(routes_sampling.bp)
    app.register_blueprint(routes_evaluations.bp)
    app.register_blueprint(routes_disputes.bp)
    app.register_blueprint(routes_calibration.bp)
    app.register_blueprint(routes_coaching.bp)
    app.register_blueprint(routes_clock.bp)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        wrapped = ApiError("ERR_INVALID_REQUEST", err.description or err.name)
        wrapped.http_status = err.code or 500
        return error_response(wrapped)

    @app.errorhandler(Exception)
    def _unexpected(err):
        wrapped = ApiError("ERR_INVALID_REQUEST", str(err) or "unexpected error")
        wrapped.http_status = 500
        return error_response(wrapped)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
