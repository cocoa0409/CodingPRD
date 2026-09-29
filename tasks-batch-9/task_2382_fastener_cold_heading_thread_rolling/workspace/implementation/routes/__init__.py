"""Blueprint registration."""

from routes.clock import bp as clock_bp
from routes.part_specs import bp as part_specs_bp
from routes.steel_heats import bp as steel_heats_bp
from routes.wire_lots import bp as wire_lots_bp
from routes.heading_tools import bp as heading_tools_bp
from routes.furnaces import bp as furnaces_bp
from routes.production_lots import bp as production_lots_bp
from routes.secondary_ops import bp as secondary_ops_bp
from routes.heat_treat import bp as heat_treat_bp
from routes.plating import bp as plating_bp
from routes.lot_tests import bp as lot_tests_bp
from routes.certs import bp as certs_bp
from routes.pack_units import bp as pack_units_bp

BLUEPRINTS = (
    clock_bp,
    part_specs_bp,
    steel_heats_bp,
    wire_lots_bp,
    heading_tools_bp,
    furnaces_bp,
    production_lots_bp,
    secondary_ops_bp,
    heat_treat_bp,
    plating_bp,
    lot_tests_bp,
    certs_bp,
    pack_units_bp,
)


def register_routes(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
