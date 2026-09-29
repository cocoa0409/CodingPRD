"""Blueprints, one module per resource family."""

from routes.admin import bp as admin_bp
from routes.attempts import bp as attempts_bp
from routes.campaigns import bp as campaigns_bp
from routes.complaints import bp as complaints_bp
from routes.consent import bp as consent_bp
from routes.contacts import bp as contacts_bp
from routes.dialer import bp as dialer_bp
from routes.policies import bp as policies_bp
from routes.revocations import bp as revocations_bp
from routes.scripts import bp as scripts_bp
from routes.scrubjobs import bp as scrubjobs_bp
from routes.suppression import bp as suppression_bp

BLUEPRINTS = (
    admin_bp,
    contacts_bp,
    consent_bp,
    revocations_bp,
    suppression_bp,
    scrubjobs_bp,
    campaigns_bp,
    dialer_bp,
    scripts_bp,
    policies_bp,
    attempts_bp,
    complaints_bp,
)
