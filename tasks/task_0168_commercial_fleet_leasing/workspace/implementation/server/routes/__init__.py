"""Route registration — wires every blueprint to the Flask app."""
from flask import Flask

from .admin import bp as admin_bp
from .collision_claims import bp as collision_bp
from .fuel_cards import bp as fuel_cards_bp
from .fuel_card_transactions import bp as fuel_txn_bp
from .ifta_quarters import bp as ifta_bp
from .lease_agreements import bp as lease_bp
from .lessees import bp as lessees_bp
from .maintenance_tickets import bp as maint_bp
from .overage_settlements import bp as settlement_bp
from .vehicles import bp as vehicles_bp


def register_blueprints(app: Flask) -> None:
    for bp in (
        lessees_bp,
        vehicles_bp,
        lease_bp,
        fuel_cards_bp,
        fuel_txn_bp,
        maint_bp,
        collision_bp,
        settlement_bp,
        ifta_bp,
        admin_bp,
    ):
        app.register_blueprint(bp)
