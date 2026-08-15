"""Route registration."""
from routes import (
    ad_tracks,
    archive,
    assignments,
    caption_tracks,
    clients,
    complaints,
    conversions,
    live_events,
    media,
    ops,
    stenographers,
    work_orders,
)

BLUEPRINTS = [
    clients.bp,
    media.bp,
    work_orders.bp,
    caption_tracks.bp,
    ad_tracks.bp,
    live_events.bp,
    stenographers.bp,
    assignments.bp,
    complaints.bp,
    conversions.bp,
    archive.bp,
    ops.bp,
]


def register_routes(app):
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)
