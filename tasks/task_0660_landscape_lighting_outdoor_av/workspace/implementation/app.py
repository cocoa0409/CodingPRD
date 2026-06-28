"""Landscape Lighting & Outdoor AV API — Flask entry point.

Registers every blueprint, installs the global error handlers that render the
standard error envelope, and runs the server in the foreground on 0.0.0.0:$PORT
(default 10000). The in-memory store starts EMPTY on every boot — no seeding.
"""

import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_body

from routes.add_ons import bp as add_ons_bp
from routes.clock_route import bp as clock_bp
from routes.crew_routes import bp as crew_routes_bp
from routes.customers import bp as customers_bp
from routes.fixtures import bp as fixtures_bp
from routes.install_jobs import bp as install_jobs_bp
from routes.projects import bp as projects_bp
from routes.quotes import bp as quotes_bp
from routes.schedule_programs import bp as schedule_programs_bp
from routes.service_plans import bp as service_plans_bp
from routes.service_visits import bp as service_visits_bp
from routes.transformers import bp as transformers_bp
from routes.warranty_claims import bp as warranty_claims_bp
from routes.zones import bp as zones_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        customers_bp,
        projects_bp,
        transformers_bp,
        zones_bp,
        fixtures_bp,
        quotes_bp,
        install_jobs_bp,
        schedule_programs_bp,
        service_plans_bp,
        service_visits_bp,
        crew_routes_bp,
        warranty_claims_bp,
        add_ons_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        body = error_body(exc.error_id, exc.message)
        resp = jsonify(body)
        resp.status_code = exc.http_status
        return resp

    @app.errorhandler(404)
    def handle_404(exc):
        body = error_body("ERR_RESOURCE_NOT_FOUND", "Resource not found.")
        resp = jsonify(body)
        resp.status_code = 404
        return resp

    @app.errorhandler(405)
    def handle_405(exc):
        body = error_body("ERR_RESOURCE_NOT_FOUND", "Method not allowed.")
        resp = jsonify(body)
        resp.status_code = 404
        return resp

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return handle_api_error(exc)
        body = error_body("ERR_INVALID_REQUEST", "Unexpected server error.")
        resp = jsonify(body)
        resp.status_code = 400
        return resp

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Prefer waitress: a production-grade pure-Python WSGI server that accepts a
    # proper connection backlog and survives heavy concurrent load (the 8-round
    # per-test-server sweep boots ~8x servers at once). The Werkzeug dev server
    # resets/drops connections when CPU-starved, surfacing as flaky
    # ConnectionReset / IncompleteRead / "could not be restarted" failures.
    # Behaviour is identical — this only changes the transport.
    try:
        from waitress import serve

        serve(app, host="0.0.0.0", port=port, threads=8, backlog=1024,
              connection_limit=1000, channel_timeout=60, _quiet=True)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
