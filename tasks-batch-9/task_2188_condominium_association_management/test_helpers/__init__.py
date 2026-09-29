"""Test infrastructure for the condominium association management API.

Layout:

* ``types``       -- TypedDict shapes for every entity the API returns
* ``api_errors``  -- error identifiers and their HTTP status codes
* ``api_client``  -- one method per endpoint
* ``constants``   -- by-law defaults, enum value sets, rounding helpers
* ``test_users``  -- actor header builders for the seven roles
* ``factories``   -- request payload builders with keyword overrides
* ``assertions``  -- entity-shape checks and the two conservation invariants
* ``fixtures``    -- composite state builders and pytest fixtures
"""
