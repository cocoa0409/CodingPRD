from flask import Blueprint

from routes import (clock, terms, rates, students, enrollments, accounts,
                    payments, waivers, sponsors, plans, holds, refunds,
                    taxforms)

ALL_BLUEPRINTS = [
    clock.bp, terms.bp, rates.bp, students.bp, enrollments.bp, accounts.bp,
    payments.bp, waivers.bp, sponsors.bp, plans.bp, holds.bp, refunds.bp,
    taxforms.bp,
]


def register_routes(app):
    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)
