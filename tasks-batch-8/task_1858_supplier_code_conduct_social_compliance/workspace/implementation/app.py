"""Flask app entry point."""
import os
from flask import Flask
from errors import ApiError
from response import error_body

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_body(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_not_found(err):
    return error_body("ERR_NOT_FOUND", "resource not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return error_body("ERR_NOT_FOUND", "method not allowed", 404)


@app.errorhandler(Exception)
def handle_uncaught(err):
    import traceback
    traceback.print_exc()
    return error_body("ERR_INVALID_REQUEST", str(err), 400)


# Register blueprints
from routes import clock, code_versions, suppliers, acknowledgments, facilities, auditors, audits, findings, caps, grievances, interviews, reviews, mutual_recognition

app.register_blueprint(clock.bp)
app.register_blueprint(code_versions.bp)
app.register_blueprint(suppliers.bp)
app.register_blueprint(acknowledgments.bp)
app.register_blueprint(facilities.bp)
app.register_blueprint(auditors.bp)
app.register_blueprint(audits.bp)
app.register_blueprint(findings.bp)
app.register_blueprint(caps.bp)
app.register_blueprint(grievances.bp)
app.register_blueprint(interviews.bp)
app.register_blueprint(reviews.bp)
app.register_blueprint(mutual_recognition.bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
