from .system import bp as system_bp
from .advertisers import bp as advertisers_bp
from .qualifications import bp as qualifications_bp
from .users import bp as users_bp
from .campaigns import bp as campaigns_bp
from .ad_groups import bp as ad_groups_bp
from .creatives import bp as creatives_bp
from .auctions import bp as auctions_bp
from .billing import bp as billing_bp
from .conversions import bp as conversions_bp
from .wallet import bp as wallet_bp
from .reports import bp as reports_bp
from .audit_logs import bp as audit_logs_bp


def register_routes(app):
    app.register_blueprint(system_bp)
    app.register_blueprint(advertisers_bp)
    app.register_blueprint(qualifications_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(campaigns_bp)
    app.register_blueprint(ad_groups_bp)
    app.register_blueprint(creatives_bp)
    app.register_blueprint(auctions_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(conversions_bp)
    app.register_blueprint(wallet_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(audit_logs_bp)
