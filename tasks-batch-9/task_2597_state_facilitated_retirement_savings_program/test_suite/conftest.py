"""
Shared pytest configuration for the retirement savings program test suite.

The runner owns the service lifecycle and relaunches the API with an empty
database before each test, so every fixture below builds its preconditions from
scratch through the documented endpoints. Importing them here makes them
available to every test module without a per-module import.
"""

from test_helpers.fixtures import (  # noqa: F401
    active_saver_env,
    affirmed_penalty_env,
    api,
    assessed_penalty_env,
    closed_account_env,
    closure_pending_env,
    employer_env,
    excess_case_env,
    exempt_certified_env,
    funded_account_env,
    program_config,
    referred_employer_env,
    unregistered_employer_env,
)

# Importing the error catalogue registers the error_id to HTTP status mapping
# with the framework validators, so validate_error() cross-checks statuses.
import test_helpers.api_errors  # noqa: F401,E402
