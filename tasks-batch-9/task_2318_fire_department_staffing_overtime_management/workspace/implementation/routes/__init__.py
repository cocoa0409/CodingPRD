"""Blueprint registration for every endpoint in PRD 4."""

from routes import assignments, duty_shifts, leave, master, members, offers, trades, vacancies

BLUEPRINTS = (
    master.bp,
    members.bp,
    duty_shifts.bp,
    assignments.bp,
    leave.bp,
    trades.bp,
    vacancies.bp,
    offers.bp,
)


def register(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
