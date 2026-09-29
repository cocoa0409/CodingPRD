"""Sterile Fill-Finish CMO API - application entry point.

Storage is in-memory only: plain Python dicts that start empty on every boot.
Nothing is seeded, preloaded or hardcoded; every row arrives through one of the
61 declared endpoints. There is no database file, no JSON on disk and no cache.
"""

import os
import sys

from flask import Flask, jsonify

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import envelope_error  # noqa: E402
from routes.audit import bp as audit_bp  # noqa: E402
from routes.batches import bp as batches_bp  # noqa: E402
from routes.lots import bp as lots_bp  # noqa: E402
from routes.mediafills import bp as mediafills_bp  # noqa: E402
from routes.personnel import bp as personnel_bp  # noqa: E402
from routes.projects import bp as projects_bp  # noqa: E402
from routes.qa import bp as qa_bp  # noqa: E402
from routes.quality import bp as quality_bp  # noqa: E402
from routes.suites import bp as suites_bp  # noqa: E402


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.json.sort_keys = False

    for blueprint in (
        projects_bp,
        suites_bp,
        mediafills_bp,
        personnel_bp,
        lots_bp,
        batches_bp,
        quality_bp,
        qa_bp,
        audit_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(404)
    def not_found(_err):
        response = jsonify(
            envelope_error("ERR_INVALID_REQUEST", "No such route on this API.")
        )
        response.status_code = 404
        return response

    @app.errorhandler(405)
    def method_not_allowed(_err):
        response = jsonify(
            envelope_error("ERR_INVALID_REQUEST", "That method is not allowed here.")
        )
        response.status_code = 405
        return response

    @app.errorhandler(500)
    def server_error(_err):  # pragma: no cover - defensive
        response = jsonify(
            envelope_error("ERR_INVALID_REQUEST", "The request could not be processed.")
        )
        response.status_code = 400
        return response

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
