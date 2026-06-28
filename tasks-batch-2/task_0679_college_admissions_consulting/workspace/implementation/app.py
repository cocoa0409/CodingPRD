import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response

# route blueprints
from routes.counselors import bp as counselors_bp
from routes.students import bp as students_bp
from routes.contracts import bp as contracts_bp
from routes.billing_entries import bp as billing_entries_bp
from routes.school_list_items import bp as school_list_items_bp
from routes.applications import bp as applications_bp
from routes.application_tasks import bp as application_tasks_bp
from routes.essays import bp as essays_bp
from routes.essay_versions import bp as essay_versions_bp
from routes.recommendations import bp as recommendations_bp
from routes.activities import bp as activities_bp
from routes.scholarships import bp as scholarships_bp
from routes.appointments import bp as appointments_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(counselors_bp)
    app.register_blueprint(students_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(billing_entries_bp)
    app.register_blueprint(school_list_items_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(application_tasks_bp)
    app.register_blueprint(essays_bp)
    app.register_blueprint(essay_versions_bp)
    app.register_blueprint(recommendations_bp)
    app.register_blueprint(activities_bp)
    app.register_blueprint(scholarships_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route — treat as not found in envelope form.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response("ERR_INVALID_REQUEST", "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        # Surface unexpected errors as 500 in envelope form.
        return error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
