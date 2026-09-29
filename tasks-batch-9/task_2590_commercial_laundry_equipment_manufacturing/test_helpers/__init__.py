"""Domain test helpers for the commercial laundry equipment manufacturing API.

Importing this package registers the error catalogue's HTTP status mapping with
the framework validators, so ``validate_error`` cross-checks statuses in every
test module without further setup.
"""

from . import api_errors  # noqa: F401  (registers the error/HTTP status mapping)
from .api_client import ApiClient

__all__ = ["ApiClient", "api_errors"]
