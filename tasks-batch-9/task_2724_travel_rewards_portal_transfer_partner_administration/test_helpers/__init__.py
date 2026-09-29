"""
Test infrastructure for the Travel Rewards Portal & Transfer Partner API.

Modules
-------
constants   : pinned numeric and calendar constants taken from the PRD.
types       : enumeration members and the audit-field shapes of §2.4.
api_errors  : the §5 catalogue and its error_id -> HTTP status mapping.
test_users  : role headers, the two entity-backed builders, and malformed headers.
api_client  : one method per §4 endpoint, plus ISO-8601 canonicalisation.
factories   : request-payload builders with PRD-legal defaults.
assertions  : domain assertions over envelopes, ledgers, postures and sweeps.
fixtures    : composite state builders that drive the API through its endpoints.

Nothing here talks to a database; every builder reaches the system under test
through the HTTP surface only.
"""
