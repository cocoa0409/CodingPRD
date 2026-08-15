"""Entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask

from util import ApiError, error_response
import routes_core
import routes_pipeline
import routes_deals

app = Flask(__name__)
app.register_blueprint(routes_core.bp)
app.register_blueprint(routes_pipeline.bp)
app.register_blueprint(routes_deals.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Method not allowed"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    import traceback
    traceback.print_exc()
    return error_response(ApiError("ERR_INVALID_REQUEST", 400, str(err)))


def _self_check():
    """Boot self-check: the app must dispatch every declared route. Not a seed —
    no entities are created; the store starts empty on every boot."""
    rules = sorted({(r.rule, ",".join(sorted(m for m in r.methods if m in ("GET", "POST"))))
                    for r in app.url_map.iter_rules()})
    assert any(p == "/_clock/set_current_utc" for p, _ in rules)
    assert any(p.startswith("/crm/deals/") and "approve" in p for p, _ in rules)
    return len(rules)


if __name__ == "__main__":
    route_count = _self_check()
    print(f"[boot] real-estate-team-lead-routing: {route_count} routes registered", flush=True)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
