"""Blueprint registration."""
from flask import Flask

from . import (applications, clock, districts, families, lottery_runs,
               programs, schools, students, transfer_requests, waitlist_events)


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(districts.bp)
    app.register_blueprint(schools.bp)
    app.register_blueprint(programs.bp)
    app.register_blueprint(families.bp)
    app.register_blueprint(students.bp)
    app.register_blueprint(applications.bp)
    app.register_blueprint(transfer_requests.bp)
    app.register_blueprint(lottery_runs.bp)
    app.register_blueprint(waitlist_events.bp)
    app.register_blueprint(clock.bp)
