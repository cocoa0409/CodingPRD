"""Mobile Imaging Unit Scheduling API — entry point.

In-memory only; the store starts empty on every boot. All server timestamps
read the logical clock (default 2026-08-01T00:00:00Z).
"""
import os

from flask import Flask

from core import (ApiError, error_response, auth, body, ok_object, fmt_dt,
                  set_clock, parse_iso_dt, f_str, fail, DB, touch)
import logic
import routes_network
import routes_planning
import routes_ops
import routes_compliance
import routes_billing

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(routes_network.bp)
app.register_blueprint(routes_planning.bp)
app.register_blueprint(routes_ops.bp)
app.register_blueprint(routes_compliance.bp)
app.register_blueprint(routes_billing.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ApiError('ERR_NOT_FOUND', 404, 'Resource not found'))


@app.errorhandler(405)
def handle_405(e):
    return error_response(ApiError('ERR_NOT_FOUND', 405, 'Method not allowed'))


@app.errorhandler(Exception)
def handle_unexpected(e):
    return error_response(
        ApiError('ERR_INTERNAL', 500, 'Internal error: {}'.format(e)))


@app.post('/api/_clock/set_current_utc')
def set_current_utc():
    auth(('OperationsDirector',))
    d = body()
    dt = parse_iso_dt(f_str(d, 'to_iso8601'))
    set_clock(dt)
    # Re-derive accreditation statuses; governing EXPIRED flips cascade:
    # future SCHEDULED days for the unit are cancelled at no charge (PRD 3.7).
    for unit_id in logic.rederive_accreditations_on_clock():
        clk = dt.date().isoformat()
        for day in list(DB['site_days'].values()):
            if (day['unit_id'] == unit_id and day['status'] == 'SCHEDULED'
                    and day['service_date'] > clk):
                logic.cancel_day_accreditation(day)
    return ok_object({'current_utc': fmt_dt(dt)})


if __name__ == '__main__':
    import socket
    import time

    from werkzeug.serving import make_server

    _port = int(os.environ.get('PORT', '10000'))
    # Bind the listening socket ourselves with a retry loop: under the
    # per-test-server stability sweep many servers are killed and re-bound on
    # the same port in quick succession on a busy shared host, and a transient
    # EADDRINUSE at the exact bind instant must not be fatal (werkzeug's
    # app.run path sys.exits on it). The poll window gives us ~15s; retry
    # briefly within it.
    _deadline = time.monotonic() + 12.0
    _sock = None
    while _sock is None:
        _candidate = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _candidate.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            _candidate.bind(('0.0.0.0', _port))
            _candidate.listen(128)
            _sock = _candidate
        except OSError:
            _candidate.close()
            if time.monotonic() >= _deadline:
                raise
            time.sleep(0.2)

    _server = make_server('0.0.0.0', _port, app, threaded=True, fd=_sock.fileno())
    _server.serve_forever()
