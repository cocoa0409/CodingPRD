"""Route blueprints, one module per resource group."""

from routes.adjustments import bp as adjustments_bp
from routes.audits import bp as audits_bp
from routes.brands import bp as brands_bp
from routes.clock import bp as clock_bp
from routes.instruments import bp as instruments_bp
from routes.invoices import bp as invoices_bp
from routes.programs import bp as programs_bp
from routes.schedules import bp as schedules_bp

ALL_BLUEPRINTS = (
    clock_bp,
    programs_bp,
    brands_bp,
    schedules_bp,
    instruments_bp,
    adjustments_bp,
    invoices_bp,
    audits_bp,
)
