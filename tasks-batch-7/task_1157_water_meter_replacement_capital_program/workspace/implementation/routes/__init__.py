from flask import Blueprint

from . import (
    accounts,
    appointments,
    audits,
    bench_tests,
    cases,
    clock,
    complaints,
    contractors,
    invoices,
    meters,
    notifications,
    programs,
    readings,
    registrations,
    waves,
    work_orders,
)

MODULES = (
    programs,
    contractors,
    accounts,
    meters,
    waves,
    work_orders,
    notifications,
    appointments,
    cases,
    readings,
    registrations,
    bench_tests,
    complaints,
    audits,
    invoices,
    clock,
)


def register_all(app):
    for mod in MODULES:
        app.register_blueprint(mod.bp)
