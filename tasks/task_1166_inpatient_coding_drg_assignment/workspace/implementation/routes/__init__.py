from flask import Blueprint


def register_routes(app):
    from routes import (accounts, assignments, audits, bills, charts, clock,
                        coded_cases, coders, deficiencies, findings, lines,
                        reviews, sweeps)
    for mod in (clock, accounts, charts, deficiencies, lines, coders,
                assignments, coded_cases, bills, sweeps, audits, findings,
                reviews):
        app.register_blueprint(mod.bp)
