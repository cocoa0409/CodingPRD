from flask import Blueprint

from routes import (
    clock, writers, works, societies, registrations, splits, subpub,
    licensees, statements, advances, distributions, audits, claims,
)

ALL_BLUEPRINTS = [
    clock.bp, writers.bp, works.bp, societies.bp, registrations.bp,
    splits.bp, subpub.bp, licensees.bp, statements.bp, advances.bp,
    distributions.bp, audits.bp, claims.bp,
]
