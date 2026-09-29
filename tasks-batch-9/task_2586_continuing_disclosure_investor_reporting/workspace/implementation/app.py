"""Continuing Disclosure & Investor Reporting API.

A single Flask process holding every row in memory. Nothing is seeded: the
store starts empty on every boot and all state is built through the endpoints.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, render_error
import routes_a
import routes_b
import routes_c
import routes_d


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except AttributeError:  # older Flask
        app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_a.bp)
    app.register_blueprint(routes_b.bp)
    app.register_blueprint(routes_c.bp)
    app.register_blueprint(routes_d.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return render_error(exc)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        return {"meta": {}, "response_type": "error",
                "data": {"error_id": "ERR_INVALID_REQUEST",
                         "message": exc.description}}, exc.code

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)
