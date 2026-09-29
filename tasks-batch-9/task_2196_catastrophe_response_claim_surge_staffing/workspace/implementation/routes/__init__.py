"""Route registration.  Paths are flat - no api prefix is applied anywhere."""

MODULES = (
    "clock",
    "events",
    "bulletins",
    "adjusters",
    "housing",
    "deployments",
    "claims",
    "reserve_entries",
    "assignments",
    "advances",
    "vendor_firms",
    "vendor_assignments",
    "loss_estimates",
    "batches",
)


def register(app):
    import importlib
    for name in MODULES:
        module = importlib.import_module("routes.%s" % name)
        app.register_blueprint(module.bp)
