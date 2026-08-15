import os
from flask import Flask

from errors import ApiError
from envelope import err

import routes_clients
import routes_benchmarks
import routes_ips
import routes_portfolios
import routes_securities
import routes_positions
import routes_restricted
import routes_proposals
import routes_trades
import routes_withdrawals
import routes_reports
import routes_amendments
import routes_minutes
import routes_events
import routes_ops


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for mod in (routes_clients, routes_benchmarks, routes_ips,
                routes_portfolios, routes_securities, routes_positions,
                routes_restricted, routes_proposals, routes_trades,
                routes_withdrawals, routes_reports, routes_amendments,
                routes_minutes, routes_events, routes_ops):
        app.register_blueprint(mod.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err(e)

    @app.errorhandler(404)
    def handle_404(e):
        return err(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_405(e):
        return err(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return err(e)
        return err(ApiError("ERR_INVALID_REQUEST", 400, str(e)))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
