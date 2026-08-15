"""Route registration."""


def register_routes(app):
    from routes import compliance, core, ops, voyages
    app.register_blueprint(core.bp)
    app.register_blueprint(voyages.bp)
    app.register_blueprint(compliance.bp)
    app.register_blueprint(ops.bp)
