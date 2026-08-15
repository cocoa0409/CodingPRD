"""Blueprint registration."""
from routes.flocks import bp as flocks_bp
from routes.breeding import bp as breeding_bp
from routes.grazing import bp as grazing_bp
from routes.shearing import bp as shearing_bp
from routes.wool import bp as wool_bp
from routes.sales import bp as sales_bp
from routes.ops import bp as ops_bp
from routes.clock_routes import bp as clock_bp


def register_all(app):
    for bp in (flocks_bp, breeding_bp, grazing_bp, shearing_bp, wool_bp, sales_bp, ops_bp, clock_bp):
        app.register_blueprint(bp)
