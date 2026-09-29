"""
Test infrastructure for the Berry Harvest Ops API compliance suite.

Layout:
  constants.py   — the PRD's variety tables, money constants and enumerations
  api_errors.py  — the sixty error identifiers of PRD section 5 and their statuses
  types.py       — TypedDict shapes for the eleven resource families
  api_client.py  — one method per endpoint of PRD section 4
  test_users.py  — pre-built auth headers for the seven roles of PRD section 2.1
  factories.py   — request-body builders for every write endpoint
  assertions.py  — envelope, audit-triple and precision assertions
  fixtures.py    — composite setup chains walking the season of PRD section 3

Importing this package registers the error-identifier to HTTP-status mapping
with the framework validator, so ``validate_error`` cross-checks status codes.
"""

from . import api_errors  # noqa: F401  (registers the error/status map)
from .api_client import ApiClient, canonical_instant, same_instant

__all__ = ["ApiClient", "canonical_instant", "same_instant", "api_errors"]
