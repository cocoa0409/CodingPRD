import os
from flask import Flask
from errors import ApiError
from response import error_response

app = Flask(__name__)


# Register error handlers
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)


@app.errorhandler(500)
def handle_500(e):
    return error_response("ERR_INTERNAL", "Internal server error", 500)


# Register blueprints
from routes.rooms import rooms_bp
from routes.bookings import bookings_bp
from routes.series import series_bp
from routes.waitlist import waitlist_bp
from routes.audit_logs import audit_logs_bp

app.register_blueprint(rooms_bp)
app.register_blueprint(bookings_bp)
app.register_blueprint(series_bp)
app.register_blueprint(waitlist_bp)
app.register_blueprint(audit_logs_bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
