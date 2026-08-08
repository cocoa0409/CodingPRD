"""Employer On-Site & Near-Site Clinic API.

Entry point: builds the Flask app, registers every endpoint declared in the
route modules through the single ordered validation ladder, and serves on
0.0.0.0:$PORT in the foreground.

The store is in-memory only and starts completely empty on every boot: no
entity is seeded, preloaded, registered or hardcoded anywhere at startup.
"""

import os

from flask import Flask

from core import envelope, ladder
from routes import (
    alt_standards,
    appointments,
    assessments,
    awards,
    contracts,
    eligibility,
    employers,
    ops,
    participants,
    periods,
    providers,
    referrals,
    shifts,
    sites,
    visits,
)

ROUTE_MODULES = [
    ops,
    employers,
    sites,
    contracts,
    providers,
    shifts,
    eligibility,
    participants,
    appointments,
    visits,
    assessments,
    referrals,
    alt_standards,
    awards,
    periods,
]


def all_specs():
    specs = []
    for module in ROUTE_MODULES:
        specs.extend(module.SPECS)
    return specs


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for index, spec in enumerate(all_specs()):
        app.add_url_rule(
            spec.flask_rule,
            endpoint="ep_%d" % index,
            view_func=ladder.make_view(spec),
            methods=[spec.method],
        )

    @app.errorhandler(404)
    def _not_found(_err):
        return envelope.error_response(
            "ERR_RESOURCE_NOT_FOUND", "No such route.", 404
        )

    @app.errorhandler(405)
    def _not_allowed(_err):
        return envelope.error_response(
            "ERR_RESOURCE_NOT_FOUND", "Method not allowed for this route.", 404
        )

    @app.errorhandler(500)
    def _server_error(_err):  # pragma: no cover - defensive
        return envelope.error_response(
            "ERR_VALIDATION", "The request could not be processed.", 400
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
