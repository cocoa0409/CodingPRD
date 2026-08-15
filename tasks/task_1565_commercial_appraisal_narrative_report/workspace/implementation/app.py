import os

from flask import Flask

import response
from errors import ApiError
from routes.clock import bp as clock_bp
from routes.clients import bp as clients_bp
from routes.appraisers import bp as appraisers_bp
from routes.engagements import bp as engagements_bp
from routes.submissions import bp as submissions_bp
from routes.approaches import bp as approaches_bp
from routes.comparables import bp as comparables_bp
from routes.reports import bp as reports_bp
from routes.revisions import bp as revisions_bp
from routes.retention import bp as retention_bp


def create_app():
    app = Flask(__name__)
    for bp in (
        clock_bp,
        clients_bp,
        appraisers_bp,
        engagements_bp,
        submissions_bp,
        approaches_bp,
        comparables_bp,
        reports_bp,
        revisions_bp,
        retention_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(e):
        return response.error(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def _not_found(e):
        return response.error("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return response.error("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(Exception)
    def _internal(e):
        return response.error("ERR_INTERNAL", 500, str(e))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
