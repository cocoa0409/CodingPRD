import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import Builder, ShowSettlementApiClient  # noqa: E402
from test_helpers.constants import DEFAULT_CLOCK  # noqa: E402


@pytest.fixture
def api() -> ShowSettlementApiClient:
    return ShowSettlementApiClient()


@pytest.fixture
def build(api) -> Builder:
    builder = Builder(api)
    builder.set_clock(DEFAULT_CLOCK)
    return builder
