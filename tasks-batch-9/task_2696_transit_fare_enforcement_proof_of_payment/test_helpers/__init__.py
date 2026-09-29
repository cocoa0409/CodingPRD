"""
Test infrastructure for the Transit Fare Enforcement & Proof of Payment API.

Modules:
  constants   — business values taken from the requirements document
  api_errors  — the error catalogue and its HTTP status mapping
  test_users  — role headers and the identity threading helpers
  types       — response shapes, including the three records that carry no
                updated_at or version
  api_client  — one method per declared endpoint
  assertions  — domain assertions for ratios, money identities and ledgers
  factories   — request-body builders
  fixtures    — composite setup chains and the client fixture
"""

from . import api_errors  # noqa: F401  (registers the error/status mapping on import)
