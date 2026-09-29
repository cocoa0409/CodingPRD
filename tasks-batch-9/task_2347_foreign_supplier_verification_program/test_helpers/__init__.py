"""Test helper infrastructure for the Foreign Supplier Verification Program API.

Stage 1 infrastructure: typed response shapes, one API client method per
documented endpoint, the error-code catalog with its HTTP status map, domain
assertions, payload factories, domain constants, per-role identity headers and
the composable precondition fixtures every test builds its world from.
"""

from . import api_errors  # noqa: F401  (registers the error -> HTTP status map)
