"""Oil & Gas Land Administration and Joint Interest Billing API."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from common import ApiError, error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    import routes_system
    import routes_lease
    import routes_well
    import routes_owner
    import routes_afe
    import routes_cost
    import routes_jib
    import routes_dispute
    import routes_revenue
    import routes_transfer

    # The clock endpoint sits outside the /land-admin prefix.
    app.register_blueprint(routes_system.clock_bp)

    for blueprint in (routes_system.bp, routes_lease.bp, routes_well.bp,
                      routes_owner.bp, routes_afe.bp, routes_cost.bp,
                      routes_jib.bp, routes_dispute.bp, routes_revenue.bp,
                      routes_transfer.bp):
        app.register_blueprint(blueprint, url_prefix="/land-admin")

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        return error_response(ApiError("ERR_VALIDATION", err.code or 500,
                                       err.description))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(ApiError("ERR_VALIDATION", 500, str(err)))

    return app


application = create_app()

if __name__ == "__main__":
    application.run(host="0.0.0.0",
                    port=int(os.environ.get("PORT", "10000")),
                    threaded=False,
                    use_reloader=False)
