"""Route modules, one per resource group."""
from . import (
    adverse_events,
    clock,
    consents,
    consults,
    financing,
    injection_visits,
    lab_panels,
    memberships,
    notifications,
    patients,
    pellet_lots,
    procedures,
    protocols,
    providers,
    series_packs,
    standing_orders,
)

MODULES = (
    patients,
    providers,
    protocols,
    consents,
    consults,
    lab_panels,
    pellet_lots,
    standing_orders,
    procedures,
    injection_visits,
    memberships,
    series_packs,
    adverse_events,
    financing,
    notifications,
    clock,
)


def register_all(app):
    for module in MODULES:
        module.register(app)
