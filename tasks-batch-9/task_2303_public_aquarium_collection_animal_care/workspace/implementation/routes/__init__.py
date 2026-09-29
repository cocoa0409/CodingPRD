"""Flask blueprints, one module per entity family."""

from routes import (
    acquisitions,
    audits,
    clock,
    exhibits,
    institutions,
    lss,
    permits,
    plan_entries,
    quarantine,
    sessions,
    species,
    specimens,
    transfers,
    vet,
)

BLUEPRINTS = (
    clock.bp,
    lss.bp,
    exhibits.bp,
    species.bp,
    institutions.bp,
    plan_entries.bp,
    acquisitions.bp,
    permits.bp,
    specimens.bp,
    quarantine.bp,
    vet.bp,
    transfers.bp,
    sessions.bp,
    audits.bp,
)
