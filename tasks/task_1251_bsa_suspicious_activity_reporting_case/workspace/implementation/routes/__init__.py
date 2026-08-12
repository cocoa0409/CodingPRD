from routes import (alerts, cases, decisions, inquiries, ops, qa, reference,
                    reviews, scenarios, sars, shares)


def register_routes(app):
    for module in (ops, reference, scenarios, alerts, cases, sars, reviews,
                   inquiries, shares, decisions, qa):
        app.register_blueprint(module.bp)
