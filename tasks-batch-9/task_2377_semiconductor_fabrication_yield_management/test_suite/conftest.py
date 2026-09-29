"""Pytest configuration for the Semiconductor Fab Yield API suite.

The composite fixtures (``api``, ``fab``) and the session-wide error-status
registration live in ``test_helpers.fixtures``; loading that module as a plugin
makes them available to every test file without a per-file import.
"""

pytest_plugins = ["test_helpers.fixtures"]
