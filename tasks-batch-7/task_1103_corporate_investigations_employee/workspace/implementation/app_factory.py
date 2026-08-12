"""Flask application factory: middleware chain and route registration."""
import json

from flask import Flask, Response, g, request

import db
import errors
import resp
import services as svc

LIST_ROLES = frozenset(
    [
        "IntakeCoordinator",
        "Investigator",
        "InvestigationsManager",
        "HRBusinessPartner",
        "GeneralCounsel",
        "ChiefLegalOfficer",
        "ComplianceAuditor",
    ]
)

# Endpoint role sets keyed by (method, url rule). Every declared (method, path)
# pair from SCAFFOLD §1.5 appears exactly once.
ENDPOINT_ROLES = {
    ("POST", "/api/cases"): {"IntakeCoordinator"},
    ("GET", "/api/cases"): LIST_ROLES,
    ("GET", "/api/cases/<rid>"): LIST_ROLES,
    ("POST", "/api/cases/<rid>/transition"): {
        "IntakeCoordinator",
        "Investigator",
        "InvestigationsManager",
    },
    ("POST", "/api/cases/<rid>/allegations"): {"IntakeCoordinator"},
    ("GET", "/api/allegations"): LIST_ROLES,
    ("GET", "/api/allegations/<rid>"): LIST_ROLES,
    ("POST", "/api/allegations/<rid>/transition"): {
        "IntakeCoordinator",
        "InvestigationsManager",
    },
    ("POST", "/api/cases/<rid>/plans"): {"Investigator"},
    ("GET", "/api/plans"): LIST_ROLES,
    ("GET", "/api/plans/<rid>"): LIST_ROLES,
    ("POST", "/api/plans/<rid>/transition"): {"Investigator", "InvestigationsManager"},
    ("POST", "/api/cases/<rid>/subjects"): {"Investigator"},
    ("GET", "/api/subjects"): LIST_ROLES,
    ("GET", "/api/subjects/<rid>"): LIST_ROLES,
    ("POST", "/api/subjects/<rid>/transition"): {"Investigator", "InvestigationsManager"},
    ("POST", "/api/cases/<rid>/preservation-notices"): {"GeneralCounsel"},
    ("GET", "/api/preservation-notices"): LIST_ROLES,
    ("GET", "/api/preservation-notices/<rid>"): LIST_ROLES,
    ("POST", "/api/preservation-notices/<rid>/transition"): {"GeneralCounsel"},
    ("POST", "/api/cases/<rid>/collection-scopes"): {"Investigator"},
    ("GET", "/api/collection-scopes"): LIST_ROLES,
    ("GET", "/api/collection-scopes/<rid>"): LIST_ROLES,
    ("POST", "/api/collection-scopes/<rid>/transition"): {
        "Investigator",
        "InvestigationsManager",
    },
    ("POST", "/api/collection-scopes/<rid>/evidence-items"): {"Investigator"},
    ("GET", "/api/evidence-items"): LIST_ROLES,
    ("GET", "/api/evidence-items/<rid>"): LIST_ROLES,
    ("POST", "/api/evidence-items/<rid>/transition"): {"Investigator"},
    ("POST", "/api/cases/<rid>/interviews"): {"Investigator"},
    ("GET", "/api/interviews"): LIST_ROLES,
    ("GET", "/api/interviews/<rid>"): LIST_ROLES,
    ("POST", "/api/interviews/<rid>/transition"): {"Investigator"},
    ("POST", "/api/cases/<rid>/privilege-designations"): {"GeneralCounsel"},
    ("GET", "/api/privilege-designations"): LIST_ROLES,
    ("GET", "/api/privilege-designations/<rid>"): LIST_ROLES,
    ("POST", "/api/privilege-designations/<rid>/transition"): {
        "GeneralCounsel",
        "ChiefLegalOfficer",
    },
    ("POST", "/api/cases/<rid>/findings"): {"Investigator"},
    ("GET", "/api/findings"): LIST_ROLES,
    ("GET", "/api/findings/<rid>"): LIST_ROLES,
    ("POST", "/api/findings/<rid>/transition"): {
        "HRBusinessPartner",
        "InvestigationsManager",
        "GeneralCounsel",
    },
    ("POST", "/api/findings/<rid>/disciplinary-recommendations"): {"HRBusinessPartner"},
    ("GET", "/api/disciplinary-recommendations"): LIST_ROLES,
    ("GET", "/api/disciplinary-recommendations/<rid>"): LIST_ROLES,
    ("POST", "/api/disciplinary-recommendations/<rid>/transition"): {
        "InvestigationsManager"
    },
    ("POST", "/api/cases/<rid>/reports"): {"Investigator"},
    ("GET", "/api/reports"): LIST_ROLES,
    ("GET", "/api/reports/<rid>"): LIST_ROLES,
    ("POST", "/api/reports/<rid>/transition"): {
        "Investigator",
        "GeneralCounsel",
        "ChiefLegalOfficer",
    },
    ("POST", "/api/cases/<rid>/self-disclosure-decisions"): {"GeneralCounsel"},
    ("GET", "/api/self-disclosure-decisions"): LIST_ROLES,
    ("GET", "/api/self-disclosure-decisions/<rid>"): LIST_ROLES,
    ("POST", "/api/self-disclosure-decisions/<rid>/transition"): {
        "ChiefLegalOfficer",
        "GeneralCounsel",
    },
    ("POST", "/api/cases/<rid>/remediation-actions"): {"HRBusinessPartner"},
    ("GET", "/api/remediation-actions"): LIST_ROLES,
    ("GET", "/api/remediation-actions/<rid>"): LIST_ROLES,
    ("POST", "/api/remediation-actions/<rid>/transition"): {
        "HRBusinessPartner",
        "ComplianceAuditor",
        "GeneralCounsel",
    },
    ("POST", "/api/pattern-alerts/scan"): {"ComplianceAuditor"},
    ("GET", "/api/pattern-alerts"): LIST_ROLES,
    ("GET", "/api/pattern-alerts/<rid>"): LIST_ROLES,
    ("POST", "/api/pattern-alerts/<rid>/transition"): {"InvestigationsManager"},
    ("POST", "/api/_clock/set_current_utc"): {"SystemAdmin"},
}


def _fingerprint():
    body = request.get_data(as_text=True) or ""
    try:
        canon = json.dumps(json.loads(body), sort_keys=True, separators=(",", ":"))
    except (ValueError, TypeError):
        canon = body
    return f"{request.method} {request.path}\n{canon}"


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False

    @app.before_request
    def authenticate_and_authorize():
        rule = request.url_rule.rule if request.url_rule is not None else None
        if rule is None or not rule.startswith("/api/"):
            return None  # fall through to the 404/405 handlers

        # priority 1: authentication
        role = request.headers.get("X-User-Role")
        user_id = request.headers.get("X-User-ID")
        if not user_id or role not in svc.ROLES:
            errors.unauthenticated()
        g.user_id = user_id
        g.role = role

        # priority 2: idempotency on every POST
        if request.method == "POST":
            key = request.headers.get("Idempotency-Key")
            if not key:
                errors.missing_idempotency_key()
            fp = _fingerprint()
            g.idem_key = key
            g.idem_fp = fp
            record = db.idempotency.get(key)
            if record is not None:
                if record["fp"] != fp:
                    errors.idempotency_replay_mismatch()
                g.idem_replay = True
                return Response(
                    record["body"], status=record["status"], content_type="application/json"
                )

        # priority 3: endpoint role authorization
        allowed = ENDPOINT_ROLES.get((request.method, rule))
        if allowed is not None and role not in allowed:
            errors.unauthorized_role()
        return None

    @app.after_request
    def store_idempotent_response(response):
        if request.method == "POST" and getattr(g, "idem_key", None):
            if not getattr(g, "idem_replay", False) and g.idem_key not in db.idempotency:
                if response.status_code < 500:
                    db.idempotency[g.idem_key] = {
                        "fp": g.idem_fp,
                        "status": response.status_code,
                        "body": response.get_data(as_text=True),
                    }
        return response

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return resp.error(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_404(exc):
        return resp.error("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(exc):
        return resp.error("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return resp.error("ERR_INTERNAL", 500, str(exc))

    import routes_a
    import routes_b
    import routes_c
    import routes_d

    app.register_blueprint(routes_a.bp)
    app.register_blueprint(routes_b.bp)
    app.register_blueprint(routes_c.bp)
    app.register_blueprint(routes_d.bp)
    return app
