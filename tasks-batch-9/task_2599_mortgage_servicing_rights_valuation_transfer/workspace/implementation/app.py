"""MSR Valuation & Servicing Transfer Platform -- Flask entry point.

The in-memory store starts completely empty on every boot: no entity is ever
seeded, preloaded or hardcoded. Every record is created through the API.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, base_meta, error_response
import routes_a
import routes_b
import routes_c
import routes_d
import routes_e
import routes_f


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(routes_a.bp)
    app.register_blueprint(routes_b.bp)
    app.register_blueprint(routes_c.bp)
    app.register_blueprint(routes_d.bp)
    app.register_blueprint(routes_e.bp)
    app.register_blueprint(routes_f.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        from flask import jsonify
        body = {
            "meta": base_meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_INVALID_REQUEST",
                     "message": err.description or err.name},
        }
        return jsonify(body), err.code

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        from flask import jsonify
        body = {
            "meta": base_meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_INVALID_REQUEST", "message": str(err)},
        }
        return jsonify(body), 422

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)
