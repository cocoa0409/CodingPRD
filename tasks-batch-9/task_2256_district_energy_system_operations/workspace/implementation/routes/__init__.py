"""Blueprint registry."""

from routes.agreements import bp as agreements_bp
from routes.assets import bp as assets_bp
from routes.clock import bp as clock_bp
from routes.expansion import bp as expansion_bp
from routes.forecasts import bp as forecasts_bp
from routes.fuel import bp as fuel_bp
from routes.invoices import bp as invoices_bp
from routes.loops import bp as loops_bp
from routes.metering import bp as metering_bp
from routes.plans import bp as plans_bp
from routes.rates import bp as rates_bp
from routes.segments import bp as segments_bp
from routes.workorders import bp as workorders_bp

ALL_BLUEPRINTS = (
    clock_bp,
    loops_bp,
    segments_bp,
    fuel_bp,
    assets_bp,
    forecasts_bp,
    plans_bp,
    rates_bp,
    agreements_bp,
    metering_bp,
    invoices_bp,
    workorders_bp,
    expansion_bp,
)
