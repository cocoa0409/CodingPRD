"""Blueprint registry.  app.py imports BLUEPRINTS from here."""

from routes import (certificates, devices, inspections, lots, operators, ops,
                    pt, qc, results, sites, storage)

BLUEPRINTS = (
    certificates.bp,
    sites.bp,
    operators.bp,
    devices.bp,
    storage.bp,
    lots.bp,
    qc.bp,
    results.bp,
    pt.bp,
    inspections.bp,
    ops.bp,
)
