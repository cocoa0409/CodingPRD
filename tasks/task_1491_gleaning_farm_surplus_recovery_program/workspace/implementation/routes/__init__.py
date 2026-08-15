from . import basic, offers, events, flow, reports, clock


def register(app):
    for mod in (basic, offers, events, flow, reports, clock):
        mod.register(app)
