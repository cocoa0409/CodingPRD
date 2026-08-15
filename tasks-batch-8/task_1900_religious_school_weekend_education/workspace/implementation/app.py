"""Entry point: Flask app, error handlers, route registration."""

import os
from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(405)
def handle_405(err):
    return error_response(ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(400)
def handle_400(err):
    return error_response(ERR_INVALID_REQUEST, 400, "Bad request")


@app.errorhandler(Exception)
def handle_exception(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.http_status, err.message)
    import traceback
    traceback.print_exc()
    return error_response(ERR_INVALID_REQUEST, 400, f"Unhandled error: {err}")


# register blueprints
from routes.school_years import bp as school_years_bp
from routes.families import bp as families_bp
from routes.teachers import bp as teachers_bp
from routes.sections import bp as sections_bp
from routes.enrollments import bp as enrollments_bp
from routes.invoices import bp as invoices_bp
from routes.assistance import bp as assistance_bp
from routes.sessions import bp as sessions_bp
from routes.milestones import bp as milestones_bp
from routes.volunteer import bp as volunteer_bp

app.register_blueprint(school_years_bp)
app.register_blueprint(families_bp)
app.register_blueprint(teachers_bp)
app.register_blueprint(sections_bp)
app.register_blueprint(enrollments_bp)
app.register_blueprint(invoices_bp)
app.register_blueprint(assistance_bp)
app.register_blueprint(sessions_bp)
app.register_blueprint(milestones_bp)
app.register_blueprint(volunteer_bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
