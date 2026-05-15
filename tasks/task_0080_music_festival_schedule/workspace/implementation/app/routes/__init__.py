"""Per-resource blueprint registration.

Each module under `app.routes` exposes a `register(app)` function that
wires its routes onto the Flask app via Blueprint.
"""
from __future__ import annotations

from flask import Flask


def register_all(app: Flask) -> None:
    from . import (
        festivals,
        program_versions,
        stages,
        equipment_kits,
        artists,
        program_items,
        riders,
        sound_engineer_teams,
        sound_checks,
        rehearsals,
        ticket_types,
        sponsor_tiers,
        exposure_catalog,
        exposure_allocations,
        schedule_changes,
        audit_entries,
        operator,
    )

    festivals.register(app)
    program_versions.register(app)
    stages.register(app)
    equipment_kits.register(app)
    artists.register(app)
    program_items.register(app)
    riders.register(app)
    sound_engineer_teams.register(app)
    sound_checks.register(app)
    rehearsals.register(app)
    ticket_types.register(app)
    sponsor_tiers.register(app)
    exposure_catalog.register(app)
    exposure_allocations.register(app)
    schedule_changes.register(app)
    audit_entries.register(app)
    operator.register(app)
