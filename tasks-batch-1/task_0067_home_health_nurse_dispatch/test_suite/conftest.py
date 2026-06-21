"""Pytest fixtures exposing test_helpers infrastructure (Home Health Nurse Dispatch).

The runner sets PYTHONPATH so ``test_helpers`` is importable; we also add the task
root defensively so the suite runs under a plain ``pytest`` invocation.
"""
import os
import sys

import pytest

_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers import ApiClient, TEST_USERS, api_client  # noqa: E402


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


@pytest.fixture
def intake_headers():
    return TEST_USERS["intake_headers"]


@pytest.fixture
def scheduler_headers():
    return TEST_USERS["scheduler_headers"]


@pytest.fixture
def billing_headers():
    return TEST_USERS["billing_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_headers"]


@pytest.fixture
def clinician_headers():
    return TEST_USERS["clinician_headers"]
