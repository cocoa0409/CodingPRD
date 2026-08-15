"""Entry point: Flask app assembly, error handlers, blueprint registration."""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.sites import bp as sites_bp
    from routes.jobs import bp as jobs_bp
    from routes.jhas import bp as jhas_bp
    from routes.permits import bp as permits_bp
    from routes.registry import bp as registry_bp
    from routes.assignments import bp as assignments_bp
    from routes.waste import bp as waste_bp
    from routes.manifests import bp as manifests_bp
    from routes.containment import bp as containment_bp
    from routes.downtime import bp as downtime_bp
    from routes.invoices import bp as invoices_bp
    from routes.incidents import bp as incidents_bp
    from routes.ops import bp as ops_bp

    for blueprint in (sites_bp, jobs_bp, jhas_bp, permits_bp, registry_bp,
                      assignments_bp, waste_bp, manifests_bp, containment_bp,
                      downtime_bp, invoices_bp, incidents_bp, ops_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response(ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response(ERR_NOT_FOUND, 405, "Method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_INTERNAL", 500, "Internal server error")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
