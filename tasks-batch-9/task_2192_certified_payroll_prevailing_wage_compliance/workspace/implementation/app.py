"""Entry point: registers the route blueprints and the error envelope handlers.

The in-memory store starts completely empty -- no entity is seeded, preloaded or
hardcoded at startup. Every entity a caller needs is built through the API.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body

from routes.clock import bp as clock_bp
from routes.portals import bp as portals_bp
from routes.determinations import bp as determinations_bp
from routes.programs import bp as programs_bp
from routes.contractors import bp as contractors_bp
from routes.fringe import bp as fringe_bp
from routes.projects import bp as projects_bp
from routes.assignments import bp as assignments_bp
from routes.workers import bp as workers_bp
from routes.payroll import bp as payroll_bp
from routes.findings import bp as findings_bp
from routes.restitution import bp as restitution_bp
from routes.interviews import bp as interviews_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (
        clock_bp,
        portals_bp,
        determinations_bp,
        programs_bp,
        contractors_bp,
        fringe_bp,
        projects_bp,
        assignments_bp,
        workers_bp,
        payroll_bp,
        findings_bp,
        restitution_bp,
        interviews_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return jsonify(error_body("ERR_VALIDATION", "No such route.")), 404
        if exc.code == 405:
            return jsonify(error_body("ERR_VALIDATION", "Method not allowed.")), 405
        return (
            jsonify(error_body("ERR_VALIDATION", exc.description or "Request could not be processed.")),
            exc.code or 400,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        return jsonify(error_body("ERR_VALIDATION", "Unexpected server error: %s" % exc)), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
