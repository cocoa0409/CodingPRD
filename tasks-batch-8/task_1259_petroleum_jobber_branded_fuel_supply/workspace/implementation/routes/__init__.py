from flask import Blueprint

from routes import (products, stations, agreements, postings, tanks, trucks,
                    drops, meters, losses, recons, invoices, drafts, taxes,
                    audits, clock)

BLUEPRINTS = [
    products.bp, stations.bp, agreements.bp, postings.bp, tanks.bp,
    trucks.bp, drops.bp, meters.bp, losses.bp, recons.bp, invoices.bp,
    drafts.bp, taxes.bp, audits.bp, clock.bp,
]


def register_routes(app):
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)
