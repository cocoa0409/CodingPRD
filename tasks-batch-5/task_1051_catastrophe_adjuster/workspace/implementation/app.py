import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from core import ApiError, error_response, _meta

from routes.clock import bp as clock_bp
from routes.people import bp as people_bp
from routes.roster import bp as roster_bp
from routes.claims import bp as claims_bp
from routes.fieldwork import bp as fieldwork_bp
from routes.billing import bp as billing_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(people_bp)
    app.register_blueprint(roster_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(fieldwork_bp)
    app.register_blueprint(billing_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def handle_http_exception(err):
        # Represent framework-level errors (404/405/400) in the standard envelope.
        error_id = "ERR_NOT_FOUND"
        if err.code == 405:
            error_id = "ERR_METHOD_NOT_ALLOWED"
        elif err.code == 400:
            error_id = "ERR_INVALID_REQUEST"
        body = {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": error_id, "message": err.description},
        }
        return jsonify(body), (err.code or 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
