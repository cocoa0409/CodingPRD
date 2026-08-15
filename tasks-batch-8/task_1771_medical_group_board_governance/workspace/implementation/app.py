"""Entry point: app factory, error handlers, route registration."""
import os
from flask import Flask

from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        import traceback
        traceback.print_exc()
        return error_response("ERR_INVALID_REQUEST", str(e), 400)

    from routes.policy_physicians import bp as bp_policy
    from routes.seats_committees import bp as bp_seats
    from routes.offers import bp as bp_offers
    from routes.motions import bp as bp_motions
    from routes.calls_distributions import bp as bp_calls
    from routes.exits_coi_mergers import bp as bp_exits
    from routes.clock import bp as bp_clock

    for bp in (bp_policy, bp_seats, bp_offers, bp_motions, bp_calls,
               bp_exits, bp_clock):
        app.register_blueprint(bp)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
