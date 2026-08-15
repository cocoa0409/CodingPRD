"""Route registration."""

from routes.ops import bp as ops_bp
from routes.employees import bp as employees_bp
from routes.candidates import bp as candidates_bp
from routes.requisitions import bp as requisitions_bp
from routes.policies import bp as policies_bp
from routes.campaigns import bp as campaigns_bp
from routes.referrals import bp as referrals_bp
from routes.milestones import bp as milestones_bp
from routes.batches import bp as batches_bp
from routes.abuse import bp as abuse_bp
from routes.analytics import bp as analytics_bp


def register_routes(app):
    for bp in (ops_bp, employees_bp, candidates_bp, requisitions_bp, policies_bp,
               campaigns_bp, referrals_bp, milestones_bp, batches_bp, abuse_bp,
               analytics_bp):
        app.register_blueprint(bp)
