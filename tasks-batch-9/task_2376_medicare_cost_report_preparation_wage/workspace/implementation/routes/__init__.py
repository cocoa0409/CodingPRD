"""Blueprint registration."""

from routes.accounting import bp as accounting_bp
from routes.cost_reports import bp as cost_reports_bp
from routes.misc import bp as misc_bp
from routes.providers import bp as providers_bp
from routes.settlement import bp as settlement_bp
from routes.wage import bp as wage_bp

BLUEPRINTS = (misc_bp, providers_bp, cost_reports_bp, accounting_bp, wage_bp, settlement_bp)
