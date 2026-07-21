import os

from flask import Flask

import envelope as env
from errors import ApiError

from routes.programs import bp as programs_bp
from routes.applicants import bp as applicants_bp
from routes.properties import bp as properties_bp
from routes.applications import bp as applications_bp
from routes.education import bp as education_bp
from routes.awards import bp as awards_bp
from routes.funding import bp as funding_bp
from routes.closings import bp as closings_bp
from routes.servicing import bp as servicing_bp
from routes.reports import bp as reports_bp

API_PREFIX = "/api/v1"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (programs_bp, applicants_bp, properties_bp, applications_bp,
               education_bp, awards_bp, funding_bp, closings_bp,
               servicing_bp, reports_bp):
        app.register_blueprint(bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return env.error(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        return env.error("ERR_INVALID_REQUEST", 404, "Resource not found.")

    @app.errorhandler(405)
    def handle_405(err):
        return env.error("ERR_INVALID_REQUEST", 405, "Method not allowed.")

    @app.errorhandler(Exception)
    def handle_uncaught(err):
        if isinstance(err, ApiError):
            return env.error(err.error_id, err.http_status, err.message)
        return env.error("ERR_INVALID_REQUEST", 500, "Internal server error: %s" % err)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
