"""The hazmat-transport-permit application package.

This package exposes the `create_app` Flask application-factory that the
top-level `app.py` entry-point invokes. The factory wires the per-resource
blueprints onto the canonical `/v1` URL-namespace, registers the auth-middleware
as a `before_request` hook, registers the response-envelope shaper as an
`after_request` hook (so successful responses uniformly carry the `meta` wrapper
with the `api_request_id` and `api_request_timestamp` fields per the PRD §2.2
contract), initializes the in-memory data store and the simulated wall-clock
and the idempotency registry at module-import time, and returns the configured
Flask application instance.

The PRD's natural-language identifier vocabulary that the test-helpers package
keys its assertion-strings against is the cross-step interface contract this
implementation honors. The canonical error-id strings, role names, header
names, envelope field names, pagination field names, and entity field names
are all read from the PRD's §2 global-spec prose by the implementer; the
scaffold's structured tables are the back-up reference for the same vocabulary
in a tabular form. The two artifacts (this implementation and the unit-test
suite that the sibling Step-5 generator produces concurrently) meet on the
docker-network of Step-7's `prd-bench-docker-run` invocation because both honor
the same PRD prose as the single source of cross-component contract.
"""

from __future__ import annotations

from flask import Flask

from .config import load_config
from .errors import APIError, register_error_handlers
from .envelope import register_meta_hooks
from .auth import register_auth_middleware
from .store import init_store
from .clock import init_clock
from .idempotency import init_idempotency_registry

# The eleven resource-group blueprints. Each blueprint owns the URL-rules for
# one resource family in the PRD's §4 endpoint reference table; collectively the
# blueprints register exactly the 37 (method, path) pairs the scaffold's §1.5
# endpoint enumeration declares.
from .blueprints.companies import companies_bp
from .blueprints.drivers import drivers_bp
from .blueprints.vehicles import vehicles_bp
from .blueprints.inspections import inspections_bp
from .blueprints.routes_bp import routes_bp
from .blueprints.permits import permits_bp
from .blueprints.trips import trips_bp
from .blueprints.gps import gps_bp
from .blueprints.penalties import penalties_bp
from .blueprints.admin import admin_bp


__all__ = ["create_app", "APIError"]


def create_app() -> Flask:
    """The canonical Flask application-factory.

    The factory's contract is the one named in the implementation-generator's
    SKILL.md: construct the Flask instance, attach the per-process singleton
    state (the in-memory store, the simulated clock, the idempotency registry,
    the deployment-configured constants table), register the cross-cutting
    middleware hooks (auth-tier check and response-envelope shaper), register
    the per-resource blueprints under the `/v1` prefix, and return the
    fully-configured `Flask` instance ready for the WSGI server.
    """
    app = Flask(__name__)

    # Disable Flask's default 404 handler behavior so unmatched routes go
    # through our standard error-envelope formatter rather than Flask's
    # plain-text "404 Not Found" page. The `propagate_exceptions = False` is
    # the default for the non-debug case; we make the JSON-envelope on errors
    # explicit via the `register_error_handlers` hook.
    app.config["PROPAGATE_EXCEPTIONS"] = False
    app.config["JSON_SORT_KEYS"] = False

    # Load the deployment-configured constants. The eleven configurable
    # constants are read from the environment (with the canonical-default
    # values baked in as the deployment-sensible defaults), and the eight
    # PRD-pinned regulatory-regime constants are hard-coded module-level
    # values per the scaffold's-and-the-PRD's "intrinsic constants" partition.
    app.config["HAZMAT_CONSTANTS"] = load_config()

    # Initialize the per-process global state. These three init calls reset
    # the module-level singletons so a fresh `create_app()` invocation gets a
    # clean world — the test harness's between-test isolation also fires the
    # `/v1/_admin/reset` endpoint which calls the same reset functions on the
    # singletons, providing the deterministic state reset the test fixtures'
    # autoreset depends on.
    init_store()
    init_clock()
    init_idempotency_registry()

    # Wire the cross-cutting middleware hooks.
    register_auth_middleware(app)
    register_meta_hooks(app)
    register_error_handlers(app)

    # Register the per-resource blueprints, each owning the URL-rules for its
    # entity family under the `/v1` prefix the scaffold's `api_prefix` field
    # pins. The 37 endpoints across the ten blueprints are the full surface
    # the RBAC matrix's 37 rows times 4 roles = 148 cells walks.
    url_prefix = "/v1"
    app.register_blueprint(companies_bp, url_prefix=url_prefix)
    app.register_blueprint(drivers_bp, url_prefix=url_prefix)
    app.register_blueprint(vehicles_bp, url_prefix=url_prefix)
    app.register_blueprint(inspections_bp, url_prefix=url_prefix)
    app.register_blueprint(routes_bp, url_prefix=url_prefix)
    app.register_blueprint(permits_bp, url_prefix=url_prefix)
    app.register_blueprint(trips_bp, url_prefix=url_prefix)
    app.register_blueprint(gps_bp, url_prefix=url_prefix)
    app.register_blueprint(penalties_bp, url_prefix=url_prefix)
    app.register_blueprint(admin_bp, url_prefix=url_prefix)

    return app
