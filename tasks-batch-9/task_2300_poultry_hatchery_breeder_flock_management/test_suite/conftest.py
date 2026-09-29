"""Pytest fixtures for the Poultry Hatchery & Breeder Flock API suite.

The API client is session-scoped; every principal is exposed as its own fixture
so a test can name the role a rule is written for. The harness restarts the
server before each test, so no data fixture needs to clean up after itself.
"""

import pytest

from test_helpers import (
    ApiClient,
    CHICK_PROCESSOR,
    CHICK_PROCESSOR_2,
    FLOCK_MANAGER,
    GROWER_1,
    GROWER_2,
    HATCHERY_MANAGER,
    INCUBATION_OPERATOR,
    VETERINARIAN,
    VETERINARIAN_2,
)


@pytest.fixture(scope="session")
def api():
    """One client for the whole session; each test still starts from empty data."""
    return ApiClient()


@pytest.fixture
def hatchery_manager():
    return HATCHERY_MANAGER


@pytest.fixture
def flock_manager():
    return FLOCK_MANAGER


@pytest.fixture
def incubation_operator():
    return INCUBATION_OPERATOR


@pytest.fixture
def chick_processor():
    return CHICK_PROCESSOR


@pytest.fixture
def second_chick_processor():
    return CHICK_PROCESSOR_2


@pytest.fixture
def veterinarian():
    return VETERINARIAN


@pytest.fixture
def second_veterinarian():
    return VETERINARIAN_2


@pytest.fixture
def grower_farm_principal():
    return GROWER_1


@pytest.fixture
def other_grower_farm_principal():
    return GROWER_2
