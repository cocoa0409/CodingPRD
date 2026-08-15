from flask import Blueprint


def make_blueprint(name):
    return Blueprint(name, __name__, url_prefix="/um")


from . import providers  # noqa: E402,F401
from . import criteria  # noqa: E402,F401
from . import requests  # noqa: E402,F401
from . import conferences  # noqa: E402,F401
from . import determinations  # noqa: E402,F401
from . import appeals  # noqa: E402,F401
from . import delegation  # noqa: E402,F401
from . import events  # noqa: E402,F401
from . import metrics  # noqa: E402,F401
from . import clock_route  # noqa: E402,F401


def all_blueprints():
    return [
        providers.bp,
        criteria.bp,
        requests.bp,
        conferences.bp,
        determinations.bp,
        appeals.bp,
        delegation.bp,
        events.bp,
        metrics.bp,
        clock_route.bp,
    ]
