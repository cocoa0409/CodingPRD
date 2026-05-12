"""Mental Health Counseling API — Flask entrypoint."""
import os

from flask import Flask

from errors import APIError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    from routes.counselors import bp as counselors_bp
    from routes.clients import bp as clients_bp
    from routes.certification_cycles import bp as cycles_bp
    from routes.availability import bp as availability_bp
    from routes.appointments import bp as appointments_bp
    from routes.counseling_records import bp as records_bp
    from routes.crisis import bp as crisis_bp
    from routes.supervision import bp as supervision_bp
    from routes.settlement import bp as settlement_bp
    from routes.audit import bp as audit_bp
    from routes.system import bp as system_bp

    for bp in (
        counselors_bp, clients_bp, cycles_bp, availability_bp, appointments_bp,
        records_bp, crisis_bp, supervision_bp, settlement_bp, audit_bp, system_bp,
    ):
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
        return error_response("ERR_VALIDATION", "Bad request", 422)

    @app.errorhandler(415)
    def handle_415(e):
        return error_response("ERR_VALIDATION", "Unsupported media type", 422)

    @app.errorhandler(Exception)
    def handle_exc(e):
        if isinstance(e, APIError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_VALIDATION", str(e) or "Internal error", 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
