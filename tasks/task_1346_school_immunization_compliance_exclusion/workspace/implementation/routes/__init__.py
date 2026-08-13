"""Route registration — pulls together all resource routers."""

from . import students, requirements, records, exemptions, notices, outbreaks
from . import sessions, appointments, registry, snapshots, ops


def register(app):
    for mod in (students, requirements, records, exemptions, notices, outbreaks,
                sessions, appointments, registry, snapshots, ops):
        mod.register(app)
