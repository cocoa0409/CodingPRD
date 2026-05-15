"""Recruitment Platform API — Flask application entrypoint."""
import os
from flask import Flask

from errors import ApiError, register_error_handlers
from routes.companies import bp as companies_bp
from routes.job_postings import bp as job_postings_bp
from routes.candidates import bp as candidates_bp
from routes.applications import bp as applications_bp
from routes.interview_rounds import bp as interview_rounds_bp
from routes.offers import bp as offers_bp
from routes.onboardings import bp as onboardings_bp
from routes.contracts_commissions import bp as contracts_commissions_bp
from routes.audit_test_drivers import bp as audit_test_drivers_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    register_error_handlers(app)

    app.register_blueprint(companies_bp)
    app.register_blueprint(job_postings_bp)
    app.register_blueprint(candidates_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(interview_rounds_bp)
    app.register_blueprint(offers_bp)
    app.register_blueprint(onboardings_bp)
    app.register_blueprint(contracts_commissions_bp)
    app.register_blueprint(audit_test_drivers_bp)

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    application = create_app()
    application.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
