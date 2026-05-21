"""ESPP API server entry point."""
import os

from flask import Flask

from core.envelope import register_error_handlers
from routes.plans import bp as plans_bp
from routes.offering_periods import bp as offering_periods_bp
from routes.enrollments import bp as enrollments_bp
from routes.contributions import bp as contributions_bp
from routes.purchases import bp as purchases_bp
from routes.form3922 import bp as form3922_bp
from routes.dispositions import bp as dispositions_bp
from routes.participants import bp as participants_bp
from routes.system import bp as system_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Register all route blueprints.
    app.register_blueprint(plans_bp)
    app.register_blueprint(offering_periods_bp)
    app.register_blueprint(enrollments_bp)
    app.register_blueprint(contributions_bp)
    app.register_blueprint(purchases_bp)
    app.register_blueprint(form3922_bp)
    app.register_blueprint(dispositions_bp)
    app.register_blueprint(participants_bp)
    app.register_blueprint(system_bp)

    register_error_handlers(app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
