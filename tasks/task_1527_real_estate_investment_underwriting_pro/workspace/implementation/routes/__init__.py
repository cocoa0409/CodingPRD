"""Route registration."""


def register_routes(app):
    from routes import deals, properties, rent_roll, opex, assumptions, scenarios, ic_memos, clock

    for mod in (deals, properties, rent_roll, opex, assumptions, scenarios, ic_memos, clock):
        mod.register(app)
