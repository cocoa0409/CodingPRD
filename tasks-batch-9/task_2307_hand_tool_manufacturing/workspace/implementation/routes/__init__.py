"""Blueprint registration for every /toolworks endpoint."""

from routes.brand import brand_bp
from routes.clock import clock_bp
from routes.lots import lots_bp
from routes.packs import packs_bp
from routes.shop import shop_bp
from routes.skus import skus_bp
from routes.testruns import runs_bp
from routes.warranty import warranty_bp

BLUEPRINTS = [
    skus_bp,
    shop_bp,
    lots_bp,
    runs_bp,
    packs_bp,
    warranty_bp,
    brand_bp,
    clock_bp,
]


def register(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
