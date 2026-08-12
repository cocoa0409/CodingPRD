"""Flask entry point: error handlers, route registration, server boot."""
import os
from flask import Flask
from errors import ApiError
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_404(err):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(err):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(Exception)
def handle_generic(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.http_status, err.message)
    import traceback
    traceback.print_exc()
    return error_response("ERR_VALIDATION", 400, f"Unhandled error: {err}")


# Register all blueprints
from routes.clock import bp as clock_bp
from routes.landlords import bp as landlords_bp
from routes.tenants import bp as tenants_bp
from routes.fields import bp as fields_bp
from routes.offerings import bp as offerings_bp
from routes.bids import bp as bids_bp
from routes.leases import bp as leases_bp
from routes.installments import bp as installments_bp
from routes.settlements import bp as settlements_bp
from routes.expenses import bp as expenses_bp
from routes.compliance import bp as compliance_bp
from routes.improvements import bp as improvements_bp
from routes.notices import bp as notices_bp
from routes.reports import bp as reports_bp

for bp in (clock_bp, landlords_bp, tenants_bp, fields_bp, offerings_bp, bids_bp,
           leases_bp, installments_bp, settlements_bp, expenses_bp, compliance_bp,
           improvements_bp, notices_bp, reports_bp):
    app.register_blueprint(bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
