"""Test helpers for the Broadband Consumer Label Compliance API.

Importing this package registers the error-id to HTTP-status map with the
framework validators, so `validate_error` cross-checks the status code of every
rejection.
"""

from . import api_errors as api_errors  # noqa: F401  (registers the status map)
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId

__all__ = [
    "ApiClient",
    "api_client",
    "ApiErrorId",
    "HTTP_STATUS_CODES",
]
