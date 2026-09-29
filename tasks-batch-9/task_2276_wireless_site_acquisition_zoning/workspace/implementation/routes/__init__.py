"""Route blueprints."""

from routes import (candidates, environmental, leases, onair, permits, refdata,
                    rings, structural, zoning)

BLUEPRINTS = (
    rings.bp,
    refdata.bp,
    candidates.bp,
    leases.bp,
    zoning.bp,
    structural.bp,
    environmental.bp,
    permits.bp,
    onair.bp,
)
