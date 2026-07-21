import os
from flask import Flask, jsonify
from core import (ApiError, auth, body, ok, as_str, set_clock, _boot_clock, err_response)

import routes_property
import routes_renter
import routes_autopay
import routes_cycle
import routes_cycle_actions
import routes_installment
import routes_remittance
import routes_delinquency


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    _boot_clock()

    # Logical clock control
    @app.post("/_clock/set_current_utc")
    @auth("PlatformAdmin")
    def set_current_utc():
        b = body()
        value = as_str(b, "to_iso8601")
        try:
            set_clock(value)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 400, "to_iso8601 is not a valid datetime.")
        return ok({}, 200)

    app.register_blueprint(routes_property.bp)
    app.register_blueprint(routes_renter.bp)
    app.register_blueprint(routes_autopay.bp)
    app.register_blueprint(routes_cycle.bp)
    app.register_blueprint(routes_cycle_actions.bp)
    app.register_blueprint(routes_installment.bp)
    app.register_blueprint(routes_remittance.bp)
    app.register_blueprint(routes_delinquency.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err_response(e)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
