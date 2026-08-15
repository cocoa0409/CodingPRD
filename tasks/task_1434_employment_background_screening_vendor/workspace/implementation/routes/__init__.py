"""Blueprint registration."""
from flask import Blueprint

from . import (clock, vendors, audits, packages, jurisdictions, matrices,
               positions, candidates, orders, consents, reports, cases,
               disputes)

ALL_BLUEPRINTS = [
    clock.bp,
    vendors.bp,
    audits.bp,
    packages.bp,
    jurisdictions.bp,
    matrices.bp,
    positions.bp,
    candidates.bp,
    orders.bp,
    consents.bp,
    reports.bp,
    cases.bp,
    disputes.bp,
]
