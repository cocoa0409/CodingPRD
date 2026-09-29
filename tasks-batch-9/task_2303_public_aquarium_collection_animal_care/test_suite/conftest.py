"""Pytest fixtures exposing the aquarium test infrastructure."""
from typing import Any, Dict

import pytest

from test_helpers import (
    AQUARIST_HEADERS,
    CURATOR_HEADERS,
    DIRECTOR_HEADERS,
    DIRECTOR_SECOND_HEADERS,
    PERMIT_OFFICER_HEADERS,
    VET_HEADERS,
    VET_SECOND_HEADERS,
    ApiClient,
    Builder,
    api_client,
    register_error_status_map,
)

# Teach the shared error validator the HTTP status published for each error id.
register_error_status_map()


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Shared API client; server lifecycle is the runner's responsibility."""
    return api_client


@pytest.fixture
def build() -> Builder:
    """State builder over the published endpoints, clock parked at the epoch."""
    return Builder(api_client)


@pytest.fixture
def curator_headers() -> Dict[str, str]:
    return CURATOR_HEADERS


@pytest.fixture
def director_headers() -> Dict[str, str]:
    return DIRECTOR_HEADERS


@pytest.fixture
def second_director_headers() -> Dict[str, str]:
    return DIRECTOR_SECOND_HEADERS


@pytest.fixture
def vet_headers() -> Dict[str, str]:
    return VET_HEADERS


@pytest.fixture
def second_vet_headers() -> Dict[str, str]:
    return VET_SECOND_HEADERS


@pytest.fixture
def aquarist_headers() -> Dict[str, str]:
    return AQUARIST_HEADERS


@pytest.fixture
def permit_officer_headers() -> Dict[str, str]:
    return PERMIT_OFFICER_HEADERS


@pytest.fixture
def approved_line(build: Builder) -> Dict[str, Any]:
    """Plant, exhibit, species and an APPROVED plan line binding the pair."""
    return build.approved_line()


@pytest.fixture
def cleared_specimen(build: Builder) -> Dict[str, Any]:
    """A specimen that has completed quarantine: CLEARED and HEALTHY."""
    return build.cleared_specimen()


@pytest.fixture
def specimen_on_exhibit(build: Builder) -> Dict[str, Any]:
    """A cleared specimen placed on its exhibit."""
    return build.specimen_on_exhibit()
