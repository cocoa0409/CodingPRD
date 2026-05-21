"""Flask app factory. Module-level singletons for clock + store."""
from flask import Flask

from .clock import LogicalClock
from .store import Store
from .envelope import install_request_context


clock = LogicalClock()
store = Store()


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    install_request_context(app)

    from .routes import restaurants as r_routes
    from .routes import menu_items as mi_routes
    from .routes import customers as c_routes
    from .routes import riders as ri_routes
    from .routes import orders as o_routes
    from .routes import assignments as a_routes
    from .routes import returns as ret_routes
    from .routes import fines as f_routes
    from .routes import work_orders as w_routes
    from .routes import clock_admin as ck_routes

    for prefix, mod in (
        ("restaurants", r_routes),
        ("menu_items", mi_routes),
        ("customers", c_routes),
        ("riders", ri_routes),
        ("orders", o_routes),
        ("assignments", a_routes),
        ("returns", ret_routes),
        ("fines", f_routes),
        ("work_orders", w_routes),
        ("clock_admin", ck_routes),
    ):
        mod.register(app, prefix)
    return app


def reset_state():
    """Fresh state — used by self-tests between runs."""
    global clock, store
    clock.__init__()
    store.reset()
