"""Blueprint registration for all resource groups."""


def register_blueprints(app):
    from routes import (
        agreements,
        clock,
        crossings,
        incidents,
        localities,
        maintenance,
        preemptions,
        programs,
        projects,
        quiet_zones,
        reviews,
        teams,
    )

    for module in (
        crossings,
        localities,
        teams,
        reviews,
        incidents,
        programs,
        projects,
        agreements,
        quiet_zones,
        maintenance,
        preemptions,
        clock,
    ):
        app.register_blueprint(module.bp)
