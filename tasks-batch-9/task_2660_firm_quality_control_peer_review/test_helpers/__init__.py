"""Shared test infrastructure for the Firm Quality Control & Peer Review API."""

from . import api_errors  # noqa: F401  (registers the error -> HTTP status map)
from .api_client import QualityControlApiClient  # noqa: F401
