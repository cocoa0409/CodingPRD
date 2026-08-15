"""Railcar Leasing & Fleet Management API — Flask entry point."""
import os
from datetime import date, datetime

from flask import Flask, jsonify
from flask.json.provider import DefaultJSONProvider

from envelope import error_body
from errors import ApiError


class JSONProvider(DefaultJSONProvider):
    """Serialize stored date objects as ISO strings (YYYY-MM-DD)."""

    @staticmethod
    def default(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
        return DefaultJSONProvider.default(obj)


app = Flask(__name__)
app.json = JSONProvider(app)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def handle_api_error(e):
    return jsonify(error_body(e.error_id, e.message)), e.status


@app.errorhandler(404)
def handle_404(e):
    return jsonify(error_body("ERR_NOT_FOUND", "Resource not found")), 404


@app.errorhandler(405)
def handle_405(e):
    return jsonify(error_body("ERR_NOT_FOUND", "Resource not found")), 404


@app.errorhandler(Exception)
def handle_unexpected(e):
    return (
        jsonify(error_body("ERR_INTERNAL", f"Unexpected error: {e}")),
        500,
    )


# Route registration
from routes.clock_lessee import bp_clock, bp_lessees  # noqa: E402
from routes.railcars import bp_railcars  # noqa: E402
from routes.tariffs import bp_tariffs  # noqa: E402
from routes.leases import bp_leases  # noqa: E402
from routes.assignments import bp_assignments  # noqa: E402
from routes.mileage import bp_mileage  # noqa: E402
from routes.statements import bp_statements  # noqa: E402
from routes.repairs import bp_repairs  # noqa: E402
from routes.cleanings import bp_cleanings  # noqa: E402
from routes.damage import bp_damage  # noqa: E402
from routes.directives import bp_directives  # noqa: E402
from routes.retrofits import bp_retrofits  # noqa: E402
from routes.retirements import bp_retirements  # noqa: E402
from routes.pools import bp_pools  # noqa: E402

for bp in (
    bp_clock,
    bp_lessees,
    bp_railcars,
    bp_tariffs,
    bp_leases,
    bp_assignments,
    bp_mileage,
    bp_statements,
    bp_repairs,
    bp_cleanings,
    bp_damage,
    bp_directives,
    bp_retrofits,
    bp_retirements,
    bp_pools,
):
    app.register_blueprint(bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
