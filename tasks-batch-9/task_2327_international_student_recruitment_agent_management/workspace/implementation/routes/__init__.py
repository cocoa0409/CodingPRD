"""Blueprint registry."""

from routes import (agencies, applications, clock, contracts, documents, entries,
                   incidents, programs, transitions)

BLUEPRINTS = (
    agencies.bp,
    programs.bp,
    contracts.bp,
    applications.bp,
    documents.bp,
    incidents.bp,
    entries.bp,
    transitions.bp,
    clock.bp,
)
