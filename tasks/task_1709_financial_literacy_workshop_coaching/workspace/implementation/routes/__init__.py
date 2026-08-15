from .admin import bp as admin_bp
from .coaching import bp as coaching_bp
from .match import bp as match_bp
from .network import bp as network_bp
from .workshops import bp as workshops_bp


def register_routes(app):
    for bp in (admin_bp, workshops_bp, coaching_bp, match_bp, network_bp):
        app.register_blueprint(bp)
