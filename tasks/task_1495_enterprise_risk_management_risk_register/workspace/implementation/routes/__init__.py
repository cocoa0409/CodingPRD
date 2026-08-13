from routes import (categories, risks, controls, appetite, plans,
                    actions_breaches, kris, reports, emerging, clock)


def register_all(app):
    for module in (categories, risks, controls, appetite, plans,
                   actions_breaches, kris, reports, emerging, clock):
        app.register_blueprint(module.bp)
