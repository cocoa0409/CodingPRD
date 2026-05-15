"""Aggregate all route blueprints and register them with the app."""
from __future__ import annotations

from flask import Flask

from .authors import authors_bp
from .reviewers import reviewers_bp
from .editors import editors_bp
from .manuscripts import manuscripts_bp
from .invitations import invitations_bp
from .reviews import reviews_bp
from .decisions import decisions_bp
from .publications import publications_bp
from .audit_logs import audit_bp
from .events import events_bp


def register_all_routes(app: Flask) -> None:
    app.register_blueprint(authors_bp)
    app.register_blueprint(reviewers_bp)
    app.register_blueprint(editors_bp)
    app.register_blueprint(manuscripts_bp)
    app.register_blueprint(invitations_bp)
    app.register_blueprint(reviews_bp)
    app.register_blueprint(decisions_bp)
    app.register_blueprint(publications_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(events_bp)
