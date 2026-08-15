"""Late-bound access to the app module's helpers (auth, obj, listing,
read_body).  Route modules import this at module load time; the real ``app``
module is only touched when a request is being served, which breaks the
import cycle between app.py and the route package."""

import sys

import envelope
import store


def _app():
    # When the server runs as ``python3 app.py``, the app module lives under
    # ``__main__``; ``import app`` would re-execute it as a second instance
    # whose ``auth`` is never populated.  Prefer the running module.
    main = sys.modules.get("__main__")
    if main is not None and hasattr(main, "auth") and hasattr(main, "read_body"):
        return main
    import app as base
    return base


class _AuthProxy(object):
    @property
    def role(self):
        return _app().auth.role

    @property
    def user_id(self):
        return _app().auth.user_id

    def require_roles(self, *roles):
        return _app().auth.require_roles(*roles)


auth = _AuthProxy()


def read_body():
    return _app().read_body()


def obj(data, status=200):
    return _app().obj(data, status)


def listing(rows, args):
    return _app().listing(rows, args)


def row_payload(row):
    return _app()._row_payload(row)
