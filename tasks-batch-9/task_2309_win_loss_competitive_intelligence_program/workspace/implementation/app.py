"""Win-Loss & Competitive Intelligence Program API (Flask, in-memory).

Boots completely empty on every invocation: no seeded rows, no persistence.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import (analysts, attributions, battlecards, buyer_contacts, clock,
                    competitors, deals, enablement, frames, interviews,
                    loss_reasons, product_gaps, programs)

BLUEPRINTS = (
    clock.bp,
    programs.bp,
    competitors.bp,
    deals.bp,
    analysts.bp,
    buyer_contacts.bp,
    frames.bp,
    interviews.bp,
    loss_reasons.bp,
    attributions.bp,
    battlecards.bp,
    enablement.bp,
    product_gaps.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(404)
    def handle_not_found(error):
        return error_response("ERR_INVALID_REQUEST",
                              "The requested route does not exist.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(error):
        return error_response("ERR_INVALID_REQUEST",
                              "The method is not allowed on this route.", 405)

    @app.errorhandler(HTTPException)
    def handle_http_exception(error):
        status = error.code or 400
        if status == 400:
            return error_response("ERR_INVALID_REQUEST",
                                  "The request could not be parsed.", 400)
        return error_response("ERR_INVALID_REQUEST",
                              error.description or "Request rejected.", status)

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        app.logger.exception("unhandled error")
        return error_response("ERR_INVALID_REQUEST",
                              "The request could not be processed.", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False,
            threaded=True)
