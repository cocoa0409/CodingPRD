"""Route registration."""
from flask import Flask

from . import (
    audit_log_routes,
    clock_routes,
    incidents_routes,
    matches_routes,
    misc_routes,
    player_contracts_routes,
    referee_routes,
    team_registrations_routes,
    tournaments_routes,
    transfers_routes,
)


def register_all_routes(app: Flask) -> None:
    tournaments_routes.register(app)
    team_registrations_routes.register(app)
    player_contracts_routes.register(app)
    matches_routes.register(app)
    incidents_routes.register(app)
    referee_routes.register(app)
    transfers_routes.register(app)
    audit_log_routes.register(app)
    clock_routes.register(app)
    misc_routes.register(app)
