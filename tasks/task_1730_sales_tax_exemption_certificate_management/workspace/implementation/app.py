"""Entry point: Flask app, auth hook, error handlers, route registration."""

import os
import traceback

from flask import Flask, jsonify

import db
from errors import ApiError
from middleware import authenticate
from response import err
from routes import (
    audit_campaigns,
    audit_samples,
    certificates,
    config,
    customers,
    defense_packets,
    drop_ship_links,
    orders,
    outreach_campaigns,
    remediation_actions,
    tenants,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.before_request(authenticate)

    for module in (
        tenants,
        config,
        customers,
        certificates,
        orders,
        drop_ship_links,
        audit_campaigns,
        audit_samples,
        remediation_actions,
        outreach_campaigns,
        defense_packets,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_not_found(e):
        return err("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return err("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        traceback.print_exc()
        return err("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
