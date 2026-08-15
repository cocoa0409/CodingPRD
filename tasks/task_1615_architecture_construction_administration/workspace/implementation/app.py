"""Entry point for the Construction Administration API server."""

import os

from flask import Flask, jsonify

from errors import ApiError, ERR_INVALID_REQUEST
from response import error_response
from routes import (
    clock,
    projects,
    submittals,
    site_visits,
    field_reports,
    rfis,
    clarification_drawings,
    payment_applications,
    change_orders,
    punch_list_items,
    record_documents,
    invoices,
)


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock.bp)
    app.register_blueprint(projects.bp)
    app.register_blueprint(submittals.bp)
    app.register_blueprint(site_visits.bp)
    app.register_blueprint(field_reports.bp)
    app.register_blueprint(rfis.bp)
    app.register_blueprint(clarification_drawings.bp)
    app.register_blueprint(payment_applications.bp)
    app.register_blueprint(change_orders.bp)
    app.register_blueprint(punch_list_items.bp)
    app.register_blueprint(record_documents.bp)
    app.register_blueprint(invoices.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(_err):
        return error_response(ERR_INVALID_REQUEST, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_err):
        return error_response(ERR_INVALID_REQUEST, "Method not allowed", 405)

    @app.errorhandler(500)
    def handle_internal_error(_err):
        return error_response(ERR_INVALID_REQUEST, "Internal server error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
