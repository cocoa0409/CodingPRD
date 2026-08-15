"""Aircraft Maintenance Shop & Annual Inspection API -- entry point.

Mounts every route module under /api, installs the error-envelope handlers
(PRD 2.2), and serves on 0.0.0.0:$PORT (default 10000).  The store starts
empty on every boot; nothing is seeded.
"""

import os

from flask import Flask

import envelope
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes_discrepancies import bp as discrepancies_bp
    from routes_directives import bp as directives_bp
    from routes_invoices import bp as invoices_bp
    from routes_logbook import bp as logbook_bp
    from routes_parts import bp as parts_bp
    from routes_principals import bp as principals_bp
    from routes_work_orders import bp as work_orders_bp

    app.register_blueprint(principals_bp)
    app.register_blueprint(work_orders_bp)
    app.register_blueprint(discrepancies_bp)
    app.register_blueprint(directives_bp)
    app.register_blueprint(parts_bp)
    app.register_blueprint(logbook_bp)
    app.register_blueprint(invoices_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return envelope.error(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(err):
        return envelope.error("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return envelope.error("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return envelope.error("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
