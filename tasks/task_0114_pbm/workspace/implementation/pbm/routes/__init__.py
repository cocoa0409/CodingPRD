"""Per-resource route blueprints."""
from .plans import bp as plans_bp
from .drugs import bp as drugs_bp
from .members import bp as members_bp
from .formulary import bp as formulary_bp
from .prior_auth import bp as pa_bp
from .claims import bp as claims_bp
from .copay_cards import bp as copay_cards_bp
from .rebate_agreements import bp as rebate_agreements_bp
from .ledger import bp as ledger_bp
from .clock import bp as clock_bp

__all__ = [
    "plans_bp",
    "drugs_bp",
    "members_bp",
    "formulary_bp",
    "pa_bp",
    "claims_bp",
    "copay_cards_bp",
    "rebate_agreements_bp",
    "ledger_bp",
    "clock_bp",
]
