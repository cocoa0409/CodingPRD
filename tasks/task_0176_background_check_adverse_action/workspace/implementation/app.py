"""FCRA Background Check API server entry point."""
import os

from flask import Flask

from core.envelope import register_error_handlers
from routes.candidates import bp as candidates_bp
from routes.consent import bp as consent_bp
from routes.jurisdictions import bp as jurisdictions_bp
from routes.orders import bp as orders_bp
from routes.verification_items import bp as items_bp
from routes.disputes import bp as disputes_bp
from routes.system import bp as system_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(candidates_bp)
    app.register_blueprint(consent_bp)
    app.register_blueprint(jurisdictions_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(items_bp)
    app.register_blueprint(disputes_bp)
    app.register_blueprint(system_bp)

    register_error_handlers(app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
