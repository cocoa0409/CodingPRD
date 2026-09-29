"""Blueprints, one module per resource group."""

from routes import (
    batch,
    campaigns,
    clock,
    complaints,
    customers,
    designs,
    furnaces,
    jobs,
    lots,
    machines,
    molds,
    programs,
)

BLUEPRINTS = (
    clock.bp,
    furnaces.bp,
    campaigns.bp,
    batch.bp,
    machines.bp,
    customers.bp,
    designs.bp,
    molds.bp,
    programs.bp,
    jobs.bp,
    lots.bp,
    complaints.bp,
)
