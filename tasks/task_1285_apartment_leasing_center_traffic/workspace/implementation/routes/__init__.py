"""Route registration."""


def register_routes(app):
    from routes import (
        applications,
        config,
        inquiries,
        leases,
        moveins,
        offers,
        reports,
        tours,
        waitlist,
    )

    for mod in (
        config,
        offers,
        inquiries,
        tours,
        waitlist,
        applications,
        leases,
        moveins,
        reports,
    ):
        app.register_blueprint(mod.bp)
