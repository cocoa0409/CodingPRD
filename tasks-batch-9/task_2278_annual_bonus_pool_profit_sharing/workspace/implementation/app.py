"""Annual Bonus Pool & Profit Sharing Administration API.

Python + Flask, in-memory storage only.  The store is empty on every boot:
no entity is seeded, preloaded, registered or hardcoded at startup.
"""

import os
from decimal import Decimal

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.accrual_periods import bp as accrual_periods_bp
from routes.adjustments import bp as adjustments_bp
from routes.awards import bp as awards_bp
from routes.bonus_plans import bp as bonus_plans_bp
from routes.business_units import bp as business_units_bp
from routes.clock import bp as clock_bp
from routes.company_metrics import bp as company_metrics_bp
from routes.disputes import bp as disputes_bp
from routes.eligibility_events import bp as eligibility_events_bp
from routes.job_level_targets import bp as job_level_targets_bp
from routes.participants import bp as participants_bp
from routes.payout_runs import bp as payout_runs_bp
from routes.pools import bp as pools_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    try:  # Flask >= 2.2 JSON provider
        from flask.json.provider import DefaultJSONProvider

        class DomainJSONProvider(DefaultJSONProvider):
            sort_keys = False

            @staticmethod
            def default(obj):
                if isinstance(obj, Decimal):
                    return float(obj)
                return DefaultJSONProvider.default(obj)

        app.json = DomainJSONProvider(app)
    except Exception:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False

    for blueprint in (
        bonus_plans_bp,
        company_metrics_bp,
        business_units_bp,
        job_level_targets_bp,
        participants_bp,
        eligibility_events_bp,
        pools_bp,
        awards_bp,
        adjustments_bp,
        accrual_periods_bp,
        payout_runs_bp,
        disputes_bp,
        clock_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 404:
            return error_response("ERR_INVALID_REQUEST", "Unknown route", 404)
        if exc.code == 405:
            return error_response("ERR_INVALID_REQUEST",
                                  "Method not allowed for this route", 405)
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST",
                                  "Request could not be parsed", 400)
        return error_response("ERR_INVALID_REQUEST",
                              exc.description or "Request failed", exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover
        app.logger.exception("Unhandled error: %s", exc)
        return error_response("ERR_INVALID_REQUEST",
                              "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
