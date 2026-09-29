"""Shared pytest configuration for the warranty reserve test suite.

Importing the helper package registers the error-code/HTTP-status map with the
shared validators and exposes every fixture defined in `test_helpers.fixtures`.
"""

from test_helpers import *  # noqa: F401,F403
from test_helpers.fixtures import (  # noqa: F401
    actuary,
    admin,
    analyst,
    api,
    controller,
    engineer,
)
