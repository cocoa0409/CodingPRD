"""Urgent Care Walk-In Queue API — Flask entry point."""
import os
from flask import Flask

from errors import ApiError
from response import error_response

from routes.clinics import bp as clinics_bp
from routes.exam_rooms import bp as exam_rooms_bp
from routes.providers import bp as providers_bp
from routes.queue_entries import bp as queue_entries_bp
from routes.patients import bp as patients_bp
from routes.coverages import bp as coverages_bp
from routes.visits import bp as visits_bp
from routes.charges import bp as charges_bp
from routes.occ_health import bp as occ_health_bp
from routes.referrals import bp as referrals_bp
from routes.discharge_instructions import bp as discharge_bp
from routes.test_driving import bp as test_driving_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clinics_bp)
    app.register_blueprint(exam_rooms_bp)
    app.register_blueprint(providers_bp)
    app.register_blueprint(queue_entries_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(coverages_bp)
    app.register_blueprint(visits_bp)
    app.register_blueprint(charges_bp)
    app.register_blueprint(occ_health_bp)
    app.register_blueprint(referrals_bp)
    app.register_blueprint(discharge_bp)
    app.register_blueprint(test_driving_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", 404, "Method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response("ERR_INVALID_REQUEST", 400, "Unexpected error: %s" % str(e))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
