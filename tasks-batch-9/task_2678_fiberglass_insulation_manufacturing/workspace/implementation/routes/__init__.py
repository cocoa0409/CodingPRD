"""Blueprint registration."""

from routes.system import bp as system_bp
from routes.programs import bp as programs_bp
from routes.plants import bp as plants_bp
from routes.binders import bp as binders_bp
from routes.product_lines import bp as product_lines_bp
from routes.runs import bp as runs_bp
from routes.changeovers import bp as changeovers_bp
from routes.thermal import bp as thermal_bp
from routes.lots import bp as lots_bp
from routes.cullet import bp as cullet_bp
from routes.channel import bp as channel_bp

BLUEPRINTS = (
    system_bp,
    programs_bp,
    plants_bp,
    binders_bp,
    product_lines_bp,
    runs_bp,
    changeovers_bp,
    thermal_bp,
    lots_bp,
    cullet_bp,
    channel_bp,
)


def register_blueprints(app):
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)
