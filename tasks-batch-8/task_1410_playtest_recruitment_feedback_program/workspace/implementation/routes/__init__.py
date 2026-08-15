from flask import Blueprint


def make_blueprint(name):
    return Blueprint(name, __name__)


from . import (  # noqa: E402,F401
    system_ops,
    participants,
    moderators,
    studies,
    applications,
    nda,
    builds,
    stations,
    sessions,
    bookings,
    surveys,
    tickets,
    payouts,
    breaches,
    exposure,
)

ALL_BLUEPRINTS = [
    system_ops.bp,
    participants.bp,
    moderators.bp,
    studies.bp,
    applications.bp,
    nda.bp,
    builds.bp,
    stations.bp,
    sessions.bp,
    bookings.bp,
    surveys.bp,
    tickets.bp,
    payouts.bp,
    breaches.bp,
    exposure.bp,
]
