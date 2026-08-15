from routes.customers import bp as customers_bp
from routes.applications import bp as applications_bp
from routes.accounts import bp as accounts_bp
from routes.securities import bp as securities_bp
from routes.marks import bp as marks_bp
from routes.orders import bp as orders_bp
from routes.calls import bp as calls_bp
from routes.liquidations import bp as liquidations_bp
from routes.cash import bp as cash_bp
from routes.interest import bp as interest_bp
from routes.disputes import bp as disputes_bp
from routes.ops import bp as ops_bp

ALL_BLUEPRINTS = [
    customers_bp, applications_bp, accounts_bp, securities_bp, marks_bp,
    orders_bp, calls_bp, liquidations_bp, cash_bp, interest_bp, disputes_bp,
    ops_bp,
]
