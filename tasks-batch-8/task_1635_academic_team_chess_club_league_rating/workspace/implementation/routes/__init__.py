from flask import Blueprint


def register_routes(app):
    from routes import (clock, seasons, clubs, coaches, players, memberships,
                        ledger, meets, pairings, disputes, tournaments,
                        sections, entries, proctors, bids, rating_events,
                        standings, stipends)
    for mod in (clock, seasons, clubs, coaches, players, memberships, ledger,
                meets, pairings, disputes, tournaments, sections, entries,
                proctors, bids, rating_events, standings, stipends):
        app.register_blueprint(mod.bp)
