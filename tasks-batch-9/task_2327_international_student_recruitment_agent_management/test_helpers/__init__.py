"""Test support package for the international-student recruitment API.

Three layers cooperate:

* ``prd_bench_local_runner.testing`` -- the generic HTTP client, envelope
  validators and race helpers shared by every benchmark task.
* this package -- the API-specific client wrapper, payload factories, domain
  constants, assertion helpers and composite setup builders.
* ``test_suite`` -- the tests themselves.
"""

# Importing api_errors registers the error/HTTP-status map with the shared
# validators, so importing this package is enough to enable status cross-checks.
from . import api_errors  # noqa: F401
from . import assertions, constants, factories, fixtures, types  # noqa: F401
from .api_client import RecruitmentApiClient  # noqa: F401
from .test_users import (  # noqa: F401
    TEST_USERS,
    make_agency_owner_headers,
    make_applicant_headers,
)

__all__ = [
    "RecruitmentApiClient",
    "api_errors",
    "TEST_USERS",
    "make_agency_owner_headers",
    "make_applicant_headers",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "types",
]
