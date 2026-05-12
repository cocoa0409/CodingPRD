"""Blockchain Evidence Preservation API — Flask entrypoint."""
import os

from flask import Flask

from errors import APIError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    from routes.customers import bp as customers_bp
    from routes.evidences import bp as evidences_bp
    from routes.notarizations import bp as notarizations_bp
    from routes.batches import bp as batches_bp
    from routes.certificates import bp as certificates_bp
    from routes.verifications import bp as verifications_bp
    from routes.judicial import bp as judicial_bp
    from routes.invoices import bp as invoices_bp
    from routes.audit_logs import bp as audit_logs_bp
    from routes.system import bp as system_bp

    for bp in (customers_bp, evidences_bp, notarizations_bp, batches_bp,
               certificates_bp, verifications_bp, judicial_bp, invoices_bp,
               audit_logs_bp, system_bp):
        app.register_blueprint(bp)

    @app.errorhandler(APIError)
    def handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Route or resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_VALIDATION_FAILED", "Bad request", 422)

    @app.errorhandler(Exception)
    def handle_exc(e):
        if isinstance(e, APIError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_VALIDATION_FAILED", str(e) or "Internal error", 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
