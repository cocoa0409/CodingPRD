"""Flask entry point: error handlers + blueprint registration."""
import os

from flask import Flask, jsonify

import response
from errors import ApiError
from routes import (
    bookings,
    campaigns,
    clock,
    installments,
    ledger,
    loss_events,
    members,
    pile_allocations,
    piles,
    pools,
    samples,
    settlements,
    stations,
    tickets,
)


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return response.error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        from errors import ApiError
        return response.error_response(ApiError("ERR_NOT_FOUND", "Resource not found", 404))

    @app.errorhandler(405)
    def handle_405(err):
        from errors import ApiError
        return response.error_response(ApiError("ERR_NOT_FOUND", "Method not allowed", 404))

    @app.errorhandler(400)
    def handle_400(err):
        from errors import ApiError
        return response.error_response(ApiError("ERR_INVALID_REQUEST", "Malformed request", 400))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        from errors import ApiError
        if isinstance(err, ApiError):
            return response.error_response(err)
        app.logger.exception("unexpected error")
        return response.error_response(ApiError("ERR_INVALID_REQUEST", str(err), 400))

    for bp in (
        clock.bp,
        campaigns.bp,
        members.bp,
        stations.bp,
        piles.bp,
        bookings.bp,
        tickets.bp,
        samples.bp,
        pools.bp,
        installments.bp,
        loss_events.bp,
        pile_allocations.bp,
        ledger.bp,
        settlements.bp,
    ):
        app.register_blueprint(bp)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
