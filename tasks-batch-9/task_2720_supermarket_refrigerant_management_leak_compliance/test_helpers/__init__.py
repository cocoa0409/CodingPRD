"""
Test infrastructure for the Supermarket Refrigerant Leak Compliance API.

Modules
-------
constants   : pinned numeric and calendar constants taken from the PRD.
types       : enumeration values and per-entity response shapes.
api_errors  : the error catalogue and its error_id -> HTTP status mapping.
test_users  : role headers and the builders for the two entity-backed roles.
api_client  : one method per declared endpoint.
factories   : request-payload builders with PRD-legal defaults.
assertions  : domain assertions over envelopes, money, masses and postures.
fixtures    : composite state builders that drive the API through its endpoints.

Nothing here talks to a database; every builder reaches the system under test
through the HTTP surface only.
"""
