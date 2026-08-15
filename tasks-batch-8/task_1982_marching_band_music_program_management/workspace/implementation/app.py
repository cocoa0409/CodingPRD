"""Flask app entry point."""
import os
from flask import Flask
from errors import ApiError, ERR_INVALID_REQUEST
from response import error

app = Flask(__name__)

# Register blueprints
from routes.programs import bp as programs_bp
from routes.students import bp as students_bp
from routes.instruments import bp as instruments_bp
from routes.uniforms import bp as uniforms_bp
from routes.arrangements import bp as arrangements_bp
from routes.events import bp as events_bp
from routes.trips import bp as trips_bp
from routes.payments import bp as payments_bp
from routes.auditions import bp as auditions_bp
from routes.trucks import bp as trucks_bp
from routes.clock import bp as clock_bp

app.register_blueprint(programs_bp)
app.register_blueprint(students_bp)
app.register_blueprint(instruments_bp)
app.register_blueprint(uniforms_bp)
app.register_blueprint(arrangements_bp)
app.register_blueprint(events_bp)
app.register_blueprint(trips_bp)
app.register_blueprint(payments_bp)
app.register_blueprint(auditions_bp)
app.register_blueprint(trucks_bp)
app.register_blueprint(clock_bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error("ERR_INVALID_REQUEST", 400, "route not found")


@app.errorhandler(405)
def handle_405(e):
    return error("ERR_INVALID_REQUEST", 400, "method not allowed")


@app.errorhandler(Exception)
def handle_exception(e):
    import traceback
    traceback.print_exc()
    return error("ERR_INVALID_REQUEST", 400, f"internal error: {type(e).__name__}: {e}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
