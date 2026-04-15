"""Main application entry point — Flask server for University Course Selection API."""
import os
from flask import Flask
from errors import APIError
from response import error_response

app = Flask(__name__)


# Register error handler
@app.errorhandler(APIError)
def handle_api_error(e):
    return error_response(e.error_id, e.detail, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("NOT_FOUND", "The requested resource was not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("METHOD_NOT_ALLOWED", "Method not allowed", 405)


@app.errorhandler(500)
def handle_500(e):
    return error_response("INTERNAL_ERROR", str(e), 500)


# Register blueprints
from routes.semesters import bp as semesters_bp
from routes.departments import bp as departments_bp
from routes.courses import bp as courses_bp
from routes.sections import bp as sections_bp
from routes.enrollments import bp as enrollments_bp
from routes.instructors import bp as instructors_bp
from routes.students import bp as students_bp
from routes.cross_dept_permissions import bp as cross_dept_bp
from routes.diagnostics import bp as diagnostics_bp

app.register_blueprint(semesters_bp)
app.register_blueprint(departments_bp)
app.register_blueprint(courses_bp)
app.register_blueprint(sections_bp)
app.register_blueprint(enrollments_bp)
app.register_blueprint(instructors_bp)
app.register_blueprint(students_bp)
app.register_blueprint(cross_dept_bp)
app.register_blueprint(diagnostics_bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
