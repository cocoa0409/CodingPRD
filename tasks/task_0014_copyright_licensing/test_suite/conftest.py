"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


# A baseline instant well before any term_start the suite uses (the
# default _next_term_window() in test_helpers.fixtures starts at year
# 2200+). Resetting to this baseline at the start of every test is what
# allows tests to use hardcoded future term_start dates regardless of
# the order in which they run — without clock isolation, an earlier
# test that advances the clock to e.g. 2099-12-31 would cause a later
# test using term_start=2099-01-01 to fail PRD §3.3's "term_start must
# lie in the future" check.
_CLOCK_BASELINE_ISO = "2025-01-01T00:00:00.000Z"


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_clock_per_test():
    """Reset the logical clock to a known pre-term baseline before every
    test, so per-test fixtures are not poisoned by clock advances done
    by previous tests. The implementation's POST /_clock/advance accepts
    arbitrary instants (PRD §3.6 only specifies the test-driving capability)."""
    try:
        api_client.advance_clock(_CLOCK_BASELINE_ISO,
                                  TEST_USERS["admin_headers"])
    except Exception:
        # If the server is not yet up or the route is missing, leave the
        # test to fail naturally — do not mask infrastructure issues.
        pass
    yield


@pytest.fixture
def admin_headers():
    """PlatformAdmin headers — opaque identity per PRD §2.1."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def shared_rights_holder_headers():
    """Shared-constant RightsHolder headers — only safe for tests that don't
    exercise ownership (e.g., role permission negative tests)."""
    return TEST_USERS["rights_holder_headers"]
