"""Copyright Licensing API — Flask application entry point."""
import os

from flask import Flask

from errors import APIError
from response import error_response

from routes.system import bp as system_bp
from routes.rights_holders import bp as rights_holders_bp
from routes.works import bp as works_bp
from routes.licenses import bp as licenses_bp
from routes.contracts import bp as contracts_bp
from routes.royalty_statements import bp as royalty_statements_bp
from routes.infringement_cases import bp as infringement_cases_bp
from routes.events import bp as events_bp
from routes.audit_logs import bp as audit_logs_bp


# api_prefix is "/works" per scaffold but actually individual blueprints already
# include their own resource paths. The scaffold's "domain_name" suggests no
# global prefix — endpoint table paths begin with "/rights-holders", "/works",
# "/licenses", "/contracts", etc. Use empty prefix.
PREFIX = ""


def create_app():
    app = Flask(__name__)

    app.register_blueprint(system_bp, url_prefix=PREFIX)
    app.register_blueprint(rights_holders_bp, url_prefix=PREFIX)
    app.register_blueprint(works_bp, url_prefix=PREFIX)
    app.register_blueprint(licenses_bp, url_prefix=PREFIX)
    app.register_blueprint(contracts_bp, url_prefix=PREFIX)
    app.register_blueprint(royalty_statements_bp, url_prefix=PREFIX)
    app.register_blueprint(infringement_cases_bp, url_prefix=PREFIX)
    app.register_blueprint(events_bp, url_prefix=PREFIX)
    app.register_blueprint(audit_logs_bp, url_prefix=PREFIX)

    @app.errorhandler(APIError)
    def handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Not Found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method Not Allowed", 404)

    @app.errorhandler(500)
    def handle_500(e):
        return error_response("ERR_INTERNAL", f"Internal error: {e}", 500)

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app = create_app()
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
