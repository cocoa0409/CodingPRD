"""Expert Witness Sourcing API — Flask entry point."""
import os
import traceback

from flask import Flask

from lib import ApiError, authenticate, error_response


def create_app():
    app = Flask(__name__, static_folder=None)
    app.json.sort_keys = False

    app.before_request(authenticate)

    import routes_cases
    import routes_clock
    import routes_engagements
    import routes_evaluations
    import routes_experts
    import routes_invoices
    import routes_productions
    import routes_reports
    import routes_schedules
    import routes_screening

    for mod in (
        routes_experts,
        routes_cases,
        routes_screening,
        routes_engagements,
        routes_productions,
        routes_reports,
        routes_schedules,
        routes_invoices,
        routes_evaluations,
        routes_clock,
    ):
        app.register_blueprint(mod.bp)

    @app.errorhandler(ApiError)
    def _api_error(e):
        return error_response(e.error_id, e.status, e.message)

    @app.errorhandler(404)
    def _not_found(e):
        return error_response("ERR_NOT_FOUND", 404, "resource not found")

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_response("ERR_INVALID_REQUEST", 405, "method not allowed")

    @app.errorhandler(Exception)
    def _unhandled(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.status, e.message)
        traceback.print_exc()
        return error_response("ERR_INTERNAL", 500, "internal server error: %s" % e)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
