"""Application factory."""
from flask import Flask

from .errors import register_error_handlers
from .routes.employees import bp_employees
from .routes.i9_documents import bp_i9_documents
from .routes.i9_forms import bp_i9_forms
from .routes.everify import bp_everify
from .routes.reverification import bp_reverification
from .routes.audit import bp_audit
from .routes.system import bp_system


def create_app() -> Flask:
    app = Flask(__name__)
    # Disable strict slashes so /foo and /foo/ both resolve the same way (we control routes explicitly).
    app.url_map.strict_slashes = False

    app.register_blueprint(bp_employees)
    app.register_blueprint(bp_i9_documents)
    app.register_blueprint(bp_i9_forms)
    app.register_blueprint(bp_everify)
    app.register_blueprint(bp_reverification)
    app.register_blueprint(bp_audit)
    app.register_blueprint(bp_system)

    register_error_handlers(app)
    return app
