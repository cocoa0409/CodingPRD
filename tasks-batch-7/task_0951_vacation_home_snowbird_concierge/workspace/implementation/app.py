"""Vacation-Home & Snowbird Concierge API.

Storage is in-memory only: every collection lives in a Python dict that is
created empty at import time.  Nothing is seeded, nothing is persisted, and a
fresh process therefore starts from a completely empty system.
"""
import errno
import os
import sys
import time

from flask import Flask, g

import core
from core import ApiError, error_response
from routes import (catalog, facilities, findings, incidents, invoices, keys, owners,
                    plans, properties, storms, subscriptions, system, vendors, visits,
                    workorders)


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in (system.bp, owners.bp, properties.bp, plans.bp, subscriptions.bp,
                      catalog.bp, visits.bp, findings.bp, vendors.bp, workorders.bp,
                      keys.bp, facilities.bp, incidents.bp, storms.bp, invoices.bp):
        app.register_blueprint(blueprint)

    @app.before_request
    def _init_request_context():
        g.created_rows = set()
        g.touched_rows = set()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message)

    @app.errorhandler(404)
    def _not_found(_exc):
        return error_response("ERR_RESOURCE_NOT_FOUND", "No such endpoint or resource.")

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        return error_response("ERR_RESOURCE_NOT_FOUND", "No such endpoint or resource.")

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message)
        app.logger.exception("unhandled error")
        return error_response("ERR_INVALID_FIELD_TYPE", "The request could not be processed.")

    return app


app = create_app()


def _serve():
    from werkzeug.serving import make_server
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "10000"))
    server = None
    last = None
    # Per-test-server isolation kills and relaunches this process about once per
    # test; the dying process's listening socket can still hold the port.  Retry
    # the bind briefly instead of letting Werkzeug sys.exit(1) on EADDRINUSE.
    for _ in range(40):
        try:
            server = make_server(host, port, app, threaded=True)
            break
        except OSError as exc:
            if exc.errno not in (errno.EADDRINUSE, errno.EACCES):
                raise
            last = exc
            time.sleep(0.05)
    if server is None:
        sys.stderr.write("could not bind %s:%d: %s\n" % (host, port, last))
        sys.exit(1)
    server.serve_forever()


if __name__ == "__main__":
    _serve()
