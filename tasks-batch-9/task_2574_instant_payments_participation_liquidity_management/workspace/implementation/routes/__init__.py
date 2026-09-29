"""Blueprint registration."""

from routes.system import bp as system_bp
from routes.participants import bp as participants_bp
from routes.position_accounts import bp as position_accounts_bp
from routes.configuration import bp as configuration_bp
from routes.credit_transfers import bp as credit_transfers_bp
from routes.fraud_reviews import bp as fraud_reviews_bp
from routes.request_for_payments import bp as rfp_bp
from routes.return_requests import bp as return_requests_bp
from routes.settlement import bp as settlement_bp
from routes.outages import bp as outages_bp

BLUEPRINTS = (
    system_bp,
    participants_bp,
    position_accounts_bp,
    configuration_bp,
    credit_transfers_bp,
    fraud_reviews_bp,
    rfp_bp,
    return_requests_bp,
    settlement_bp,
    outages_bp,
)


def register_blueprints(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
