from flask import Blueprint

from routes import (
    aircraft,
    airports,
    applications,
    clock,
    environmental,
    evictions,
    findings,
    hangars,
    inspections,
    insurance,
    leases,
    offers,
    rates,
    rent_charges,
)


def all_blueprints():
    return [
        clock.bp,
        airports.bp,
        rates.bp,
        hangars.bp,
        applications.bp,
        offers.bp,
        leases.bp,
        aircraft.bp,
        insurance.bp,
        environmental.bp,
        inspections.bp,
        findings.bp,
        evictions.bp,
        rent_charges.bp,
    ]
