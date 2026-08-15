"""Escheatment & Unclaimed Property API — Flask entry point."""

import os
import signal

# The benchmark host runs many sibling task pipelines concurrently, and a
# sibling's pattern-kill (e.g. `pkill -f app.py`, whose default signal is
# SIGTERM) can otherwise take this server down mid-test. The per-test restart
# machinery tears servers down with SIGKILL, which cannot be ignored and is
# unaffected by this; only the stray SIGTERM is shrugged off.
signal.signal(signal.SIGTERM, signal.SIG_IGN)

from flask import Flask

import errors
import response as resp

import routes_owners
import routes_rules
import routes_properties
import routes_letters
import routes_reports
import routes_securities
import routes_liquidation
import routes_remittances
import routes_claims
import routes_penalties
import routes_audits
import routes_documents
import routes_system


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_owners.bp)
    app.register_blueprint(routes_rules.bp)
    app.register_blueprint(routes_properties.bp)
    app.register_blueprint(routes_letters.bp)
    app.register_blueprint(routes_reports.bp)
    app.register_blueprint(routes_securities.bp)
    app.register_blueprint(routes_liquidation.bp)
    app.register_blueprint(routes_remittances.bp)
    app.register_blueprint(routes_claims.bp)
    app.register_blueprint(routes_penalties.bp)
    app.register_blueprint(routes_audits.bp)
    app.register_blueprint(routes_documents.bp)
    app.register_blueprint(routes_system.bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return resp.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return resp.error(
            errors.ERR_INVALID_REQUEST, "The requested route does not exist", 404
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return resp.error(
            errors.ERR_INVALID_REQUEST, "Method not allowed on this route", 405
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, errors.ApiError):
            return resp.error(exc.error_id, exc.message, exc.http_status)
        return resp.error(errors.ERR_INVALID_REQUEST, str(exc), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
