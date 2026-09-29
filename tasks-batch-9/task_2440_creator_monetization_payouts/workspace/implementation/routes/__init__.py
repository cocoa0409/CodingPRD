"""Route blueprints, one module per domain area."""
from routes.clock import bp as clock_bp
from routes.creators import bp as creators_bp
from routes.tax import bp as tax_bp
from routes.products import bp as products_bp
from routes.content import bp as content_bp
from routes.revenue import bp as revenue_bp
from routes.appeals import bp as appeals_bp
from routes.periods import bp as periods_bp
from routes.statements import bp as statements_bp
from routes.payouts import bp as payouts_bp
from routes.investigations import bp as investigations_bp
from routes.funds import bp as funds_bp

blueprints = [
    clock_bp,
    creators_bp,
    tax_bp,
    products_bp,
    content_bp,
    revenue_bp,
    appeals_bp,
    periods_bp,
    statements_bp,
    payouts_bp,
    investigations_bp,
    funds_bp,
]
