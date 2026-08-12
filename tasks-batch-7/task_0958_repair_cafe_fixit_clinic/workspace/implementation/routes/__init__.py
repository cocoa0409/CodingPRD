from routes.events import bp as events_bp
from routes.stations import bp as stations_bp
from routes.fixers import bp as fixers_bp
from routes.frontdesk import bp as frontdesk_bp
from routes.items import bp as items_bp
from routes.outcomes import bp as outcomes_bp
from routes.parts import bp as parts_bp
from routes.incidents import bp as incidents_bp
from routes.donations import bp as donations_bp


def register_routes(app):
    for bp in (
        events_bp,
        stations_bp,
        fixers_bp,
        frontdesk_bp,
        items_bp,
        outcomes_bp,
        parts_bp,
        incidents_bp,
        donations_bp,
    ):
        app.register_blueprint(bp)
