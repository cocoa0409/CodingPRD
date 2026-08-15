"""Campus Card & Meal Plan Management API — Flask entry point."""

import os

from flask import Flask

from errors import ApiError
from response import error as error_response

app = Flask(__name__)
app.url_map.strict_slashes = False


def register_blueprints():
    from routes.clock import bp as clock_bp
    from routes.holders import bp as holders_bp
    from routes.cards import bp as cards_bp
    from routes.terms import bp as terms_bp
    from routes.plans import bp as plans_bp
    from routes.enrollments import bp as enrollments_bp
    from routes.accounts import bp as accounts_bp
    from routes.transactions import bp as transactions_bp
    from routes.access import bp as access_bp
    from routes.merchants import bp as merchants_bp
    for bp in (clock_bp, holders_bp, cards_bp, terms_bp, plans_bp,
               enrollments_bp, accounts_bp, transactions_bp, access_bp,
               merchants_bp):
        app.register_blueprint(bp)


register_blueprints()


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.http_status, exc.message)


@app.errorhandler(404)
def handle_not_found(_exc):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_method_not_allowed(_exc):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(400)
def handle_bad_request(_exc):
    return error_response("ERR_VALIDATION", 400, "Malformed request")


@app.errorhandler(Exception)
def handle_unexpected(exc):
    app.logger.exception("unexpected error: %s", exc)
    return error_response("ERR_INTERNAL", 500, "Internal server error")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
