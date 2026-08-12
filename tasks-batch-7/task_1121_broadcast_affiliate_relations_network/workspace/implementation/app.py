"""Flask application entry point."""
import os
import traceback

from flask import Flask, jsonify

from errors import ApiError, ERR_INVALID_REQUEST
from response import error_response


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # Register blueprints
    from routes.networks import bp as networks_bp
    from routes.stations import bp as stations_bp
    from routes.territories import bp as territories_bp
    from routes.programs import bp as programs_bp
    from routes.agreements import bp as agreements_bp
    from routes.renewal_offers import bp as renewal_offers_bp
    from routes.clearance_reports import bp as clearance_reports_bp
    from routes.preemptions import bp as preemptions_bp
    from routes.avail_allocations import bp as avail_allocations_bp
    from routes.retrans_settlements import bp as retrans_settlements_bp
    from routes.outages import bp as outages_bp
    from routes.compliance_reports import bp as compliance_reports_bp
    from routes.exclusivity_claims import bp as exclusivity_claims_bp
    from routes.clock import bp as clock_bp

    app.register_blueprint(networks_bp)
    app.register_blueprint(stations_bp)
    app.register_blueprint(territories_bp)
    app.register_blueprint(programs_bp)
    app.register_blueprint(agreements_bp)
    app.register_blueprint(renewal_offers_bp)
    app.register_blueprint(clearance_reports_bp)
    app.register_blueprint(preemptions_bp)
    app.register_blueprint(avail_allocations_bp)
    app.register_blueprint(retrans_settlements_bp)
    app.register_blueprint(outages_bp)
    app.register_blueprint(compliance_reports_bp)
    app.register_blueprint(exclusivity_claims_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        traceback.print_exc()
        return error_response(ERR_INVALID_REQUEST, f"unexpected error: {err}", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
