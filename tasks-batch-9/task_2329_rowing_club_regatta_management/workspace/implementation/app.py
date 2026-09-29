"""Riverside Rowing Club — boathouse, water-safety and regatta service.

Storage is entirely in-memory: plain Python dicts that start empty on every boot.
Nothing is seeded, preloaded or written to disk.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import clock
import db
import response
from errors import ApiError
from routes import dues, entries, fleet, jury, members, race, regattas, trailers, water

PREFIX = "/boathouse"
BLUEPRINTS = (members.bp, dues.bp, fleet.bp, water.bp, regattas.bp, entries.bp,
              race.bp, jury.bp, trailers.bp)


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=PREFIX)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify(response.error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        return (jsonify(response.error_body("ERR_INVALID_REQUEST",
                                            exc.description or exc.name)),
                exc.code or 400)

    @app.errorhandler(Exception)
    def _unexpected(exc):  # pragma: no cover - safety net
        return jsonify(response.error_body("ERR_INVALID_REQUEST", str(exc))), 500

    # A fresh process always starts from an empty world and the default clock.
    db.reset_all()
    clock.reset()
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
