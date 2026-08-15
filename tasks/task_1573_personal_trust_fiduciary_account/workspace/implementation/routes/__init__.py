from flask import Blueprint


def register_routes(app):
    from routes import (clock_routes, trusts, documents, beneficiaries,
                        committee, distributions, investments, compliance,
                        ledger, fees, statements, filings, termination)
    for mod in (clock_routes, trusts, documents, beneficiaries, committee,
                distributions, investments, compliance, ledger, fees,
                statements, filings, termination):
        app.register_blueprint(mod.bp)
