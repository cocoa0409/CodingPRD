from . import aircraft, parties, leases, utilization, claims, returns, novation, defaults, clock

BLUEPRINTS = (
    aircraft.bp,
    parties.bp,
    leases.bp,
    utilization.bp,
    claims.bp,
    returns.bp,
    novation.bp,
    defaults.bp,
    clock.bp,
)


def register_routes(app):
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)
