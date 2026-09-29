"""
Shared pytest configuration for the Ocean Cargo Insurance API test suite.

The runner owns the server lifecycle and restarts the API with an empty
database before each test, so every fixture here builds its preconditions from
scratch through the documented endpoints. Importing the fixtures below makes
them available to every test module without a per-module import.
"""

from test_helpers.fixtures import (  # noqa: F401
    api,
    canonical_env,
    claim_ready_env,
    ga_called_env,
    ga_secured_env,
    issued_certificate_env,
    open_declaration_env,
    surveyor_env,
    two_contributor_env,
)

# Importing the error catalogue registers the error_id to HTTP status mapping
# with the framework validators, so validate_error() cross-checks statuses.
import test_helpers.api_errors  # noqa: F401,E402
