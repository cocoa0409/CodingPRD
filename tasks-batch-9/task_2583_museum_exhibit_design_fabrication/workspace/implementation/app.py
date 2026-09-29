"""Museum Exhibit Design & Fabrication API — entry point.

Storage is entirely in memory and the store starts COMPLETELY EMPTY on every boot:
no seeding, no preloading, no hardcoded rows.  The harness re-invokes start.sh before
every test, which therefore wipes every byte of state.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_artifacts
import routes_cases
import routes_clock
import routes_drawings
import routes_interactives
import routes_materials
import routes_packages
import routes_projects
import routes_punch
import routes_windows
import routes_zones
from envelope import error_response
from errors import ApiError

BLUEPRINTS = (
    routes_projects.bp,
    routes_packages.bp,
    routes_zones.bp,
    routes_cases.bp,
    routes_artifacts.bp,
    routes_interactives.bp,
    routes_materials.bp,
    routes_drawings.bp,
    routes_windows.bp,
    routes_punch.bp,
    routes_clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def handle_http_exception(err):
        # An unmatched route or method keeps its transport status but still answers
        # with the declared error envelope.
        status = err.code if err.code in (404, 405) else 400
        wrapped = ApiError("ERR_INVALID_REQUEST", err.description)
        wrapped.http_status = status
        return error_response(wrapped)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        wrapped = ApiError("ERR_INVALID_REQUEST", str(err))
        wrapped.http_status = 500
        return error_response(wrapped)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
