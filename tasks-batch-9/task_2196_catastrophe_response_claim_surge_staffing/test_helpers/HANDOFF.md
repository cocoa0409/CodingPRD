# test_helpers handoff (queue B agents)

Read these modules; do **not** edit them. If you need new shared code, put it in your
own new module under `test_helpers/` (e.g. `corner_support.py`) and import it.

## Layout
- `api_client.py` — `api_client` singleton + `ApiClient`, one method per endpoint
  (75 total). `api_prefix` is EMPTY: paths are exactly as declared in SCAFFOLD.
  Signatures: bodyless transitions are `verb_x(x_id, headers, payload=None)`;
  transitions with a required body are `verb_x(x_id, payload, headers)`; creates are
  `create_x(payload, headers)`; lists are `list_x(headers, params=None)`; reads are
  `get_x(x_id, headers)`. Clock: `set_clock(iso, headers)` and
  `set_clock_raw(payload, headers)` for malformed-payload probes.
- `api_errors.py` — `ApiErrorId` (`str` Enum, all 101 ids) and `HTTP_STATUS_CODES`;
  importing it registers the id→status map, so `validate_error(resp, ApiErrorId.X)`
  checks the status for you. `.value` when comparing to a returned `error_id`.
- `types.py`, `constants.py` — enum tuples; pinned literals (`CLOCK_START_UTC`,
  `REST_BUFFER_HOURS`, tier factors, premium bands, `RANGES`).
- `factories.py` — `create_<entity>_payload(**overrides)` for all 13 entities plus
  `coverage_line(...)`, `drop_keys(payload, *keys)`, `unique_suffix()`. Defaults are
  valid; override/drop one field for a targeted invalid payload.
- `fixtures.py` — plain functions (NOT pytest fixtures), all taking the client
  first: `declared_event`, `surge_event`, `effective_bulletin`, `create_adjuster`,
  `active_housing_block`, `confirmed_deployment`, `desk_deployment_confirmed`,
  `demobilized_deployment`, `triaged_claim`, `scheduled_inspection`,
  `completed_inspection`, `issued_advance`, `voided_advance`, `append_reserve_entry`,
  `ledger_for_claim`, `activated_vendor_firm`, `accepted_vendor_assignment`,
  `open_batch`, `submitted_batch`, `mint_loss_estimate`, `event_version`,
  `claim_version`, `set_clock`, `clock_start`.
- `assertions.py` — `assert_money_equals(a, b, label)` (tol 0.005), `assert_<entity>`
  shape asserters for all 13 entities, `assert_event_incurred_conservation`,
  `assert_housing_room_conservation`, `assert_ledger_sequence_ascending`,
  `assert_claim_tier_band`, `assert_identity_fields`, `find_by_id`.
- `test_users.py` — see below. `__init__.py` re-exports the framework generics
  (`validate_success`, `validate_error`, `validate_error_is_one_of`,
  `validate_paginated`, `run_race`, `assert_exactly_one_succeeds`,
  `NON_EXISTENT_UUID`, …) so `from test_helpers import validate_success` works.

## Acting as an identity
`make_catastrophe_manager_headers(user_id="cm_1")`, `..._deployment_coordinator_...`,
`..._claims_examiner_...`, `..._compliance_officer_...` take an opaque id — pass an
explicit distinct id for segregation-of-duties pairs. The two entity-backed roles
must carry the row id: `make_adjuster_headers(adjuster["id"])` and
`make_vendor_coordinator_headers(firm["id"])`, else `ERR_NOT_ASSIGNED_*`.
Also `headers_for_role(role, user_id)`, `missing_role_headers(user_id)`,
`missing_user_id_headers(role)`, `NO_AUTH_HEADERS`, and `TEST_USERS` whose keys are the
`conftest.py` fixture names (`claims_examiner_headers`, `*_alt_headers`). All six roles
may drive the clock.

## Conventions
- The server restarts per test, so the DB is empty at test start and there is no
  shared mutable module state: build every precondition inside the test, via a
  module-level `_setup(api)` helper, not a pytest fixture.
- The clock starts at `2026-08-01T00:00:00.000Z`; advance it only forward with
  `api.set_clock(...)` and assert stamps as `...T00:00:00.000Z` strings.
- `validate_error` returns the error dict; use it to assert a masked error is absent:
  `err = validate_error(r, ApiErrorId.A, 409); assert err["error_id"] != ApiErrorId.B.value`.
- Queue A owns `test_suite/test_difficulty_<rule_id>.py`; name yours differently.
- Every docstring must end with one verbatim `Design: Corner/<section>/<name>` line,
  and every quoted PRD sentence must be greppable in `workspace/PRD.md` in full.
