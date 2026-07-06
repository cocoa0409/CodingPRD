import os
from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(bp, url_prefix="/training")

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", 400, "Bad request")

    @app.errorhandler(Exception)
    def handle_generic(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        if isinstance(e, HTTPException):
            code = e.code or 500
            if code == 404 or code == 405:
                return error_response("ERR_NOT_FOUND", 404, "Resource not found")
            if code == 400:
                return error_response("ERR_INVALID_REQUEST", 400, "Bad request")
            return error_response("ERR_INVALID_REQUEST", code, str(e))
        return error_response("ERR_INVALID_REQUEST", 500, "Internal error: %s" % str(e))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
