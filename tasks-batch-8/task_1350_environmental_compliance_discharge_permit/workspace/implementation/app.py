"""Entry point: Flask app, error handlers, route registration."""

import os
from flask import Flask

from errors import ApiError, ERR_NOT_FOUND
import response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return response.error(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return response.error(ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return response.error(ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(Exception)
    def handle_generic(e):
        # Unexpected error: surface as a 400 rather than an unformatted 500 to
        # keep the envelope consistent.
        return response.error("ERR_INVALID_REQUEST", 400, str(e))

    from routes.permits import bp as permits_bp
    from routes.outfalls import bp as outfalls_bp
    from routes.effluent_limits import bp as limits_bp
    from routes.sampling import bp as sampling_bp
    from routes.lab_results import bp as lab_results_bp
    from routes.exceedances import bp as exceedances_bp
    from routes.dmrs import bp as dmrs_bp
    from routes.swppp import bp as swppp_bp
    from routes.inspections import bp as inspections_bp
    from routes.corrective_actions import bp as ca_bp
    from routes.renewals import bp as renewals_bp
    from routes.consent_orders import bp as orders_bp
    from routes.audit import bp as audit_bp
    from routes.clock import bp as clock_bp

    for bp in (
        permits_bp,
        outfalls_bp,
        limits_bp,
        sampling_bp,
        lab_results_bp,
        exceedances_bp,
        dmrs_bp,
        swppp_bp,
        inspections_bp,
        ca_bp,
        renewals_bp,
        orders_bp,
        audit_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)

    return app


app = create_app()

if __name__ == "__main__":
    import time

    port = int(os.environ.get("PORT", "10000"))
    # The benchmark harness restarts the server before every test by killing the
    # listener and immediately respawning start.sh. A fresh boot can briefly find
    # its port still occupied (predecessor socket not yet reaped, or an ephemeral
    # client connection colliding with the just-freed port). Werkzeug exits(1)
    # on bind failure; retry inside the runner's restart-poll window instead of
    # dying. While serving, app.run blocks forever, so the loop runs at most once
    # in the normal case; a real kill signal terminates the process without
    # entering the retry path.
    for _attempt in range(80):  # ~20s of retries at 0.25s
        try:
            app.run(host="0.0.0.0", port=port, threaded=True)
            break
        except (SystemExit, OSError):
            time.sleep(0.25)
