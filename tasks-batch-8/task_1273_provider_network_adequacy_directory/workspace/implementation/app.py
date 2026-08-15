"""Provider Network Adequacy & Directory Accuracy API — Flask entry point."""

import os
import traceback

from flask import Flask, jsonify

import errors
from response import error_response, _request_id, _now_iso


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    from routes.clock import bp as clock_bp
    from routes.regions import bp as regions_bp
    from routes.standards import bp as standards_bp
    from routes.providers import bp as providers_bp
    from routes.locations import bp as locations_bp
    from routes.listings import bp as listings_bp
    from routes.members import bp as members_bp
    from routes.cycles import bp as cycles_bp
    from routes.records import bp as records_bp
    from routes.probes import bp as probes_bp
    from routes.evaluations import bp as evaluations_bp
    from routes.results import bp as results_bp
    from routes.deficiencies import bp as deficiencies_bp
    from routes.access_plans import bp as access_plans_bp
    from routes.complaints import bp as complaints_bp
    from routes.corrections import bp as corrections_bp

    for bp in (clock_bp, regions_bp, standards_bp, providers_bp, locations_bp,
               listings_bp, members_bp, cycles_bp, records_bp, probes_bp,
               evaluations_bp, results_bp, deficiencies_bp, access_plans_bp,
               complaints_bp, corrections_bp):
        app.register_blueprint(bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(errors.err_invalid("Resource not found"))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(errors.err_invalid("Method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        traceback.print_exc()
        body = {
            "meta": {
                "api_request_id": _request_id(),
                "api_request_timestamp": _now_iso(),
            },
            "response_type": "error",
            "data": {
                "error_id": "ERR_INTERNAL",
                "message": f"Internal server error: {err}",
            },
        }
        return jsonify(body), 500

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
