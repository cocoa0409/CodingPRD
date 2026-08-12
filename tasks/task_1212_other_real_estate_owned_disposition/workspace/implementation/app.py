import os

from flask import Flask, request, g, jsonify

from envelope import error_body
from routes import register_routes

ROLES = {
    "OREOAdmin", "PropertyManager", "OREOSpecialist", "Appraiser", "ChiefAppraiser",
    "CreditOfficer", "OREOCommittee", "ComplianceOfficer", "Broker",
}

app = Flask(__name__)


@app.before_request
def authenticate():
    if not request.path.startswith("/api"):
        return None
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        return jsonify(error_body(
            "ERR_UNAUTHENTICATED",
            "Missing or invalid X-User-Role / X-User-ID headers")), 401
    g.user_id = uid
    g.user_role = role
    return None


@app.errorhandler(404)
def not_found(_e):
    return jsonify(error_body("ERR_NOT_FOUND", "Resource not found")), 404


@app.errorhandler(405)
def method_not_allowed(_e):
    return jsonify(error_body("ERR_NOT_FOUND", "Resource not found")), 404


@app.errorhandler(Exception)
def handle_exception(e):
    from errors import ApiError
    if isinstance(e, ApiError):
        return jsonify(error_body(e.error_id, e.message)), e.status
    return jsonify(error_body("ERR_INTERNAL", str(e))), 500


register_routes(app)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
