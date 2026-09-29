"""Route registration."""
from routes import amendments, carriers, sites, structural


def register_routes(app):
    sites.register(app)
    carriers.register(app)
    structural.register(app)
    amendments.register(app)
