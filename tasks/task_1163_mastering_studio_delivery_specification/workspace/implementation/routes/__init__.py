from flask import Blueprint

from routes import (
    clock, clients, engineers, platform_profiles, rush_tier_rules, projects,
    session_slots, source_assets, rounds, deliverables, metadata_tags,
    qc_reports, archive_bundles,
)

BLUEPRINTS = [
    clock.bp,
    clients.bp,
    engineers.bp,
    platform_profiles.bp,
    rush_tier_rules.bp,
    projects.bp,
    session_slots.bp,
    source_assets.bp,
    rounds.bp,
    deliverables.bp,
    metadata_tags.bp,
    qc_reports.bp,
    archive_bundles.bp,
]


def register_routes(app):
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)
