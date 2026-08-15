from flask import Blueprint

from routes.clock import bp as clock_bp
from routes.customers import bp as customers_bp
from routes.freight import bp as freight_bp
from routes.lines import bp as lines_bp
from routes.molds import bp as molds_bp
from routes.specs import bp as specs_bp
from routes.qualifications import bp as quals_bp
from routes.materials import bp as materials_bp
from routes.orders import bp as orders_bp
from routes.runs import bp as runs_bp
from routes.quality import bp as quality_bp
from routes.shipments import bp as shipments_bp
from routes.docks import bp as docks_bp
from routes.slots import bp as slots_bp


def register_all(app):
    api = Blueprint("plant", __name__, url_prefix="/plant")
    for bp in (clock_bp, customers_bp, freight_bp, lines_bp, molds_bp,
               specs_bp, quals_bp, materials_bp, orders_bp, runs_bp,
               quality_bp, shipments_bp, docks_bp, slots_bp):
        api.register_blueprint(bp)
    app.register_blueprint(api)
