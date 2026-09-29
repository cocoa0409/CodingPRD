"""
Shared pytest configuration for the servicing rights transfer test suite.

The runner owns the service lifecycle and relaunches the API with an empty
database before each test, so every fixture below builds its preconditions from
scratch through the documented endpoints. Importing them here makes them
available to every test module without a per-module import.
"""

from test_helpers.fixtures import (  # noqa: F401
    api,
    approved_agreement,
    awarded_trade,
    completed_transfer,
    desk,
    live_bid,
    locked_portfolio,
    published_package,
    ready_transfer,
    settled_trade,
    stratified_package,
    valued_portfolio,
)

# Importing the error catalogue registers the error_id to HTTP status mapping
# with the framework validators, so validate_error() cross-checks statuses.
import test_helpers.api_errors  # noqa: F401,E402
