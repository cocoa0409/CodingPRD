"""Corporate Sustainability & Emissions Reporting API — Flask entry point."""
import os
from datetime import date, datetime
from decimal import Decimal

from flask import Flask, jsonify
from flask.json.provider import DefaultJSONProvider

from envelope import error_body
from errors import ApiError


class JSONProvider(DefaultJSONProvider):
    """Serialize Decimal as JSON numbers and datetime objects as ISO strings."""

    @staticmethod
    def default(obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, (datetime, date)):
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
from routes.sites import bp as bp_sites  # noqa: E402
from routes.factors import bp as bp_factors  # noqa: E402
from routes.cycles import bp as bp_cycles  # noqa: E402
from routes.records import bp as bp_records  # noqa: E402
from routes.evidence import bp as bp_evidence  # noqa: E402
from routes.engagements import bp as bp_engagements  # noqa: E402
from routes.targets import bp as bp_targets  # noqa: E402
from routes.instruments import bp as bp_instruments  # noqa: E402
from routes.questionnaires import bp as bp_questionnaires  # noqa: E402
from routes.clock import bp as bp_clock  # noqa: E402

for bp in (
    bp_sites,
    bp_factors,
    bp_cycles,
    bp_records,
    bp_evidence,
    bp_engagements,
    bp_targets,
    bp_instruments,
    bp_questionnaires,
    bp_clock,
):
    app.register_blueprint(bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
