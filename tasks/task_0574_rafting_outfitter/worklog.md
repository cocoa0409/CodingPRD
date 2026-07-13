# Worklog — task_0574_rafting_outfitter

## Step 1: Create Task Directory — 2026-07-09T13:04:34.000Z

Created `tasks/task_0574_rafting_outfitter/` and `tasks/task_0574_rafting_outfitter/workspace/` (index pre-allocated by the user; no index scan performed).

## Step 2: Generate Scaffold (Expert) — 2026-07-09T13:45:06.000Z

All checks pass. The scaffold is complete, lint-clean, and self-consistent.

## Summary

Generated three artifacts for **task_0574_rafting_outfitter** at **Expert** difficulty (all three files written to the task directory, lint verdict: `clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability`).

**Complexity profile:** primary archetype `quota_allocation` + secondary `temporal_windowing`; **flat** entity topology (prioritized, 0% in prior examples); **parallel** state-machine shape; `peer_roles`; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers. `api_prefix: "/"` (honest flat/peer surface, all collections root-level siblings).

**SCAFFOLD.yaml (§1.0–§1.7):**
- **11 entities** — RiverTrip, Guide, GuideAssignment, Reservation, Guest, Waiver, GearItem, GearAssignment, ShuttleVehicle, ShuttleRun, RiverConditionReading (append-only, `common_fields:false`).
- **10 state machines** (state per entity/dimension): RiverTrip is cyclic/posture-driven (SCHEDULED↔OPEN↔FULL↔WEATHER_HOLD→CANCELLED/COMPLETED); Reservation has **parallel dimensions** (payment_status × fulfillment_status); plus Guest, Waiver, GearItem, GearAssignment, GuideAssignment, ShuttleRun, Guide.
- **1 concurrency rule** — `reservation-create-stale-trip` (OCC on RiverTrip.version, 412).
- **9 calculations** — dual-variant reservation totals (estimated vs final), dual-variant gratuity distribution (equal-split vs role-weighted, pinned rounding order), tiered group discount, guide-ratio ceiling, deposits-held/gear-serviceable conservation aggregates, flow-safety band threshold.
- **9 validation priorities**, **48 endpoints** (26 POST / 22 GET; includes `/_clock/set_current_utc`), **41 error codes**, **4 roles** (OutfitterManager, Reservationist, SafetyOfficer opaque; Guest entity_backed).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** 9 rule_ids × 2 = **18 instances**, each grounded in §1.1–§1.7 with executable `setup_api_calls` chains and pre-computed literal asserts (e.g., estimated 58000 vs final 19800; gratuity provisional 3334 vs final 5001; ceil(7/6)=2 ratio boundary; PFD weight inclusive-200; guide half-open overlap vs shuttle 30-min buffer; gear-count and deposits-held conservation invariants).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **32 active instances** + 3 `excluded_because` stubs, spanning entities/state_machines/calculations/validations/endpoints/rbac/cross_cutting(OCC)/consistency_model — including OCC stale-vs-current version, RBAC denials + entity_backed ownership, FK reverse-reachability filters, flow SAFE boundary, and error-trigger coverage.

Note on calibration: the domain's eight sub-workflows push endpoints (48) and error codes (41) above the nominal Expert bands (20–32 / 18–30); entities (11), calculations (9), and state machines (10) sit squarely in-band. The surface is dense and tightly coupled rather than padded — every endpoint is load-bearing for either a lifecycle action, an FK reverse-reachability GET, or an assertion read.

## Step 3: Copy Shared Files — 2026-07-09T13:45:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0574_rafting_outfitter/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-07-09T13:52:00.000Z

All checks pass. The PRD is complete.

**Contract 1 — Field-Name Coverage: PASS** (entities[].fields: 60 required, 60 present, 0 missing; endpoints[].input request_body: all present; endpoints[].query_params: all present)

**Contract 2 — Rule Coverage: PASS** (9/9 validations as ordered precedence chain §2.6; 1/1 OCC rejection §2.9; all transitions across 10 machines with from/to + preconditions paired to error IDs + side-effects §3.1–3.9; 9/9 calculations in precise prose, no pseudocode; cancellation cascades and recompute effects expressed §2.8/§3.9; sibling-branch symmetry rendered at equal density)

**Contract 3 — §3 Path Purity: PASS** (0 tokens starting with `/`; 0 bare HTTP-method tokens; 0 method+path combined tokens)

## Summary

- **Output**: `workspace/PRD.md`
- **Line count**: 293 lines
- **Sections**: §1 Introduction; §2 Global Specs (2.1 RBAC, 2.2 Response Structure [verbatim], 2.3 Pagination, 2.4 Common Properties, 2.5 Money/Rounding, 2.6 Validation Order, 2.7 Reference Resolution, 2.8 State Reconciliation/Cascades, 2.9 OCC on trip version, 2.10 Logical Clock); §3 Business Logic (3.1 Trips/Guides/GuideAssignments, 3.2 Booking/Capacity/Discounts, 3.3 Guests/Waivers/Age, 3.4 Gear Inventory, 3.5 Check-In, 3.6 Payments/Gratuity, 3.7 River Conditions/Posture, 3.8 Shuttles, 3.9 Completion & Cascades); §4 Endpoint table (4 columns, 49 endpoints); §5 Error table (2 columns, 41 errors).

**Scaffold coverage**: 11 entities, 10 state machines (RiverTrip cyclic posture + Reservation's dual payment/fulfillment dimensions + 7 others), 9 calculations, 9 priority-ordered validations, 49 endpoints, 41 errors, 4 roles (3 opaque + Guest entity-backed with waiver-ownership check). All enum value sets (whitewater classes, guide roles, gear types, flow bands, all lifecycle states, booking modes, directions) are rendered as exact backticked strings. The `RiverConditionReading` append-only exception (no `updated_at`/`version`) is stated explicitly.

One scaffold note surfaced during generation: the deposit-sufficiency formula references a `DEPOSIT_PCT` constant that the scaffold declares by name but assigns no numeric value; I rendered it as the named percentage constant `DEPOSIT_PCT` (round-half-up to a whole cent) rather than inventing a figure.

### Orchestrator repair (post Step 4)

The doc-generator's closing note surfaced a real scaffold defect: `DEPOSIT_PCT` was declared by name in three SCAFFOLD.yaml sites (§1.3 pay-deposit precondition, §1.4 priority-8 validation, §1.6 `ERR_DEPOSIT_TOO_LOW`) with **no numeric value**, while `SCAFFOLD_CORNER_DESIGN.yaml` already assumes 25% (a 12000 estimate → required 3000; `deposit_cents: 2999` → `ERR_DEPOSIT_TOO_LOW`; `deposit_cents: 3000` accepted on the `>=` boundary). Left unpinned, every deposit-sufficiency test would be un-derivable from PRD prose and would have to be deleted in Step 7.

Repaired at the root, consistently in both artifacts, before Steps 5/6 were launched:
- `SCAFFOLD.yaml` ×3 — `DEPOSIT_PCT` → `round_half_up(estimated_total_cents * 0.25)` (with `DEPOSIT_PCT = 0.25, i.e. 25%` retained as a gloss on the priority-8 validation).
- `workspace/PRD.md` §3.6 — the deposit sentence now reads "multiplied by the deposit percentage of 25 percent (0.25), rounded half-up to the nearest whole cent; a deposit exactly equal to the required amount is accepted, and only a strict shortfall is rejected with `ERR_DEPOSIT_TOO_LOW`", pinning both the constant and the inclusive `>=` boundary.

## Step 5: Generate Unit Tests — 2026-07-09T14:10:00.000Z

All checks pass. Test infrastructure and suite are complete.

## Summary

Generated complete test infrastructure for task_0574_rafting_outfitter from the two design indices only (no freelance walking of SCAFFOLD.yaml). All Python compiles; all PRD citations verified verbatim against PRD.md; no scaffold/table leakage; no skip/xfail markers.

**Files written**

`test_helpers/` (9 files): `__init__.py` (barrel), `types.py` (10 entity TypedDicts + enums; RiverConditionReading correctly append-only with only id+created_at), `api_client.py` (one method per PRD endpoint), `api_errors.py` (full error catalog + HTTP-status map registered), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque roles as shared constants; Guest entity_backed via `make_guest_headers`), `fixtures.py` (composite setup helpers: `setup_open_trip`, `setup_confirmed_reservation`, `setup_checked_in_reservation`, `setup_settled_trip_three_guides`).

`test_suite/` (conftest + 8 test files): 66 test functions total.

**Coverage**

- Queue A (Difficulty §1.8): all 18 non-stub instances translated, 2 tests each = 36 tests. Every rule_id/instance covered (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant). Precedence-pair tests are legitimate here because PRD §2.6 states the fixed validation order verbatim.
- Queue B (Corner §1.9): 30 of 32 non-stub instances translated, 1 test each = 30 tests. The 2 `excluded_because` stubs (`guide_ratio_boundary_covered_by_difficulty`, `pfd_weight_upper_bound_covered_by_difficulty`) and the 1 calculations stub (`flow_marginal_moves_trip_to_weather_hold`) were correctly not translated (cross-references resolve to owning difficulty instances).

**Instances skipped (gaps, not weakened)**

- `Corner/endpoints/filter_guests_by_reservation_id_returns_children` and `Corner/endpoints/filter_gear_assignments_by_guest_id_returns_children` — SKIPPED. The PRD only lists "List/filter" as the endpoint title (§4 table) and never describes query-parameter filtering semantics in prose; asserting "returns exactly the matching children" fails C2 (endpoint-titular) and unique-derivability (a faithful PRD-only implementer could ignore unknown filter params). Fixtures were written to be robust to filter-less implementations (each `waiver_for_guest` call occurs when exactly one waiver exists), and the serviceable-count invariant test computes counts client-side from the full unfiltered list rather than relying on `?status=`/`?gear_type=` filtering.

## Step 6: Generate Implementation — 2026-07-09T14:10:00.000Z

Implementation complete and verified.

## Files written
All under `workspace/implementation/`:
- `start.sh` — foreground launcher; `flask`-import-guarded `pip install` (avoids per-test-reboot contention), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000).
- `requirements.txt` — `flask==3.0.3`.
- `app.py` — single cohesive module (~1050 LOC), 48 routes, in-memory `DB` dicts keyed by id, **no seeding** at startup.

## Module layout (within app.py)
Constants/error catalog → `ApiError` → in-memory store + monotonic `_SEQ` → ISO parser (regex-based, since Python 3.9's `fromisoformat` can't handle `Z`) → response-envelope helpers → auth/authorization → typed body-field validators → existence lookups → pagination → calculations → trip-aggregate recompute → cascade helpers → gratuity distribution → routes grouped by entity (RiverTrip, Guide, GuideAssignment, Reservation, Guest, Waiver, GearItem, GearAssignment, ShuttleVehicle, ShuttleRun, RiverConditionReading, `/_clock`).

## Endpoint count
48 endpoints, matching the PRD/scaffold surface exactly (envelope `meta`/`response_type`/`data`, error body `error_id`/`message`, pagination `limit`/`offset`/`total_count`/`has_more`).

## Validation precedence
Implemented as the PRD §2.6 fixed order, and where the scaffold's state-machine precondition ordering conflicts with §2.6, **PRD §2.6 wins** (e.g., at check-in, referential waiver/gear checks (priority 6) fire before the guide-ratio constraint (priority 7), even though the scaffold prose lists ratio first). Per-request flow: auth (401) → role authz (403) → body shape/type/enum + time-window (400) → existence left-to-right, path before body FKs (404) → state (409) → safety (422) → referential (409) → business constraints (409) → fiscal deposit (402) → OCC (412). Unknown role strings are treated as malformed → 401.

## OCC (optimistic concurrency)
Only `POST /reservations` is guarded. `expected_trip_version` is required and compared to `RiverTrip.version` as the last check; mismatch → `ERR_STALE_TRIP_VERSION` (412). A successful create bumps `trip.version` by exactly one (`touch(trip)`), so two sequential creates carrying the same expected version behave as first-succeeds/second-stale. All other mutations bump a resource's `version`/`updated_at` once per operation, and only when material fields actually change (snapshot-diff on trips) so computed-field changes correctly count as mutations without spurious bumps.

## Logical clock
A module-global `LOGICAL_NOW` initialized to `2026-05-01T00:00:00Z`; it never falls back to wall time. It drives **all** server timestamps — `api_request_timestamp`, `created_at`, `updated_at` (all formatted ISO-8601 UTC with exactly 3 fractional digits) — making them deterministic for tests. `POST /_clock/set_current_utc` (OutfitterManager) parses `to_iso8601` and sets it. Entity temporal comparisons (guide half-open `[trip_date,end_time)` overlap with adjacency allowed; shuttle 30-minute turnaround buffer with `gap==30` allowed) compare stored input datetimes directly. List ordering uses a stable `(created_at, _seq)` key so ties resolve to insertion order, never id (matching the gratuity ordering rule).

Money uses `Decimal` with `ROUND_HALF_UP` for the base term; gratuity pools use floor division with remainder distributed one cent at a time in `created_at` order (equal-split provisional on settle, role-weighted LEAD:3/SAFETY:2/SWEEP:1 final on completion). Both cancellation cascades (trip-level L1 and reservation/guest-level L2) release gear back to `AVAILABLE`, void waivers, remove guests, refund deposits, and recompute trip aggregates, each affected child touched independently.

## Step 7: Run Tests and Iterate — 2026-07-09T14:17:48.000Z

All 8 rounds now pass 66/66. Clean sweep.

## Summary

**Iterations run:** 2 (initial sweep + one fix, then confirming sweep).

**Diagnosis:** The first sweep showed 7/8 rounds fully green (66/66) and one round (round 5) with a single failure in `test_unsafe_reading_cancels_trip_and_refunds`. The failure was NOT an assertion mismatch — it was a connection-level flake: `requests.exceptions.ConnectionError: ('Connection aborted.', BadStatusLine('POST /gear-assignments HTTP/1.1\r\n'))` raised during the test's setup helper. The `BadStatusLine` echoing the request line back is the classic symptom of the werkzeug threaded dev-server's keep-alive race, which only surfaces under the 8x concurrent CPU load of the parallel sweep. The test logic and PRD tracing were correct, so no test or PRD-coverage changes were warranted.

**Tests deleted:** None. No test was PRD-silent or non-derivable; the only failure was infrastructure flakiness.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:**
- `workspace/implementation/app.py` (`__main__` block): switched the WSGI server from the werkzeug dev server (`app.run(threaded=True)`) to `waitress.serve(app, threads=8)`, with a fallback to `app.run` if waitress is unavailable. Waitress is a robust production-grade pure-Python WSGI server that does not exhibit the keep-alive/BadStatusLine race under concurrent load. No application logic, endpoints, or response behavior changed.
- `workspace/implementation/requirements.txt`: added `waitress==3.0.0` (version pinned to the already-installed build so no boot-time pip install contention is introduced).
- `workspace/implementation/start.sh`: the dependency-presence check now imports both `flask` and `waitress` so the guarded install still fires only when a dependency is actually missing.

**Result:** Fresh 8-round parallel sweep — all 8 rounds 66/66, zero failures, zero flakes.

### Orchestrator verification

Independently re-read all 8 `results.{1..8}.json`: every round reports `passed=66 / total=66 / failed=0`.

### Step 8 skip evaluation

Not skipped. Step 7 ran 2 iterations and applied 3 `implementation/` edits, so the literal skip condition (zero iterations beyond baseline) does not hold. All three edits are, however, purely infrastructural (WSGI server swap + its dependency plumbing) with no behavioral surface — no endpoint, response field, side effect, calculation, or validation changed. Step 8 is therefore expected to find no PRD-silence or PRD-mismatch site to patch; it is run anyway so that conclusion is established by scan rather than assumed.

## Step 8: Finalize PRD — 2026-07-09T14:19:35.000Z

Done. PRD_FINALIZED.md was produced as a byte-identical copy of PRD.md.

## Summary

**Line counts:** PRD.md = 292 lines, PRD_FINALIZED.md = 292 lines. **Delta: 0% (0 edits).**

**Per-change bullets:** None. Zero PRD edits were made.

## Rationale

All three `<step_7_diff>` items are pure process/infrastructure changes with no behavioral surface visible through the API contract that PRD.md specifies:

1. **`app.py` `__main__` block (lines 1482–1493)** — swaps the WSGI server from werkzeug's dev server to `waitress.serve(..., threads=8)` with an `app.run` fallback. This block runs only at boot and touches no route, no response envelope, no status code, no state transition. The 40+ endpoints and all business logic above it are untouched. Nothing PRD-observable changed.

2. **`requirements.txt` (line 2)** — adds `waitress==3.0.0`. A dependency pin has no API-behavioral surface.

3. **`start.sh` (line 7)** — the guarded dependency-presence check now imports `flask, waitress` instead of just `flask`. This only governs whether a `pip install` fires at launch; it changes no request/response behavior.

## Pre-edit search log

Even though no edits were committed, I confirmed the no-behavioral-surface conclusion by reading the full implementation:

- **Subject:** the WSGI-serving / launch / dependency-install machinery.
- **Paths enumerated and read:** `app.py` in full (all routes, calculation helpers, cascade helpers, gratuity distribution, auth, envelope helpers, and the `__main__` block), `start.sh` in full, `requirements.txt` in full. The `__main__` block is the sole consumer of the waitress/werkzeug choice; no route handler, error handler, or helper references the server or the dependency list. `start.sh`'s changed line only gates the install step.
- **Wording adjustment:** none — no PRD sentence describes WSGI server choice, launch mechanics, or dependency management, so there is no PRD prose that these items could contradict or that requires pinning.

The Step 7 diagnosis itself states the sole test failure was connection-level flakiness (`BadStatusLine`), not an assertion/behavior mismatch, and that no test or PRD-coverage changes were warranted. A byte-identical PRD_FINALIZED.md is the correct and expected result here.

### Orchestrator verification

`diff PRD.md PRD_FINALIZED.md` → no output. Byte-identical confirmed.

## Step 9: Complete PRD — 2026-07-09T20:01:08.000Z

All 15 edits applied cleanly (one added table row accounts for the +1 line). Task complete.

## Summary

**Files:** Source `PRD_FINALIZED.md` (292 lines, 39,963 chars) → `PRD_COMPLETED.md` (293 lines, 42,318 chars); char delta **+2,355**. Source was identical to `PRD.md`; used `PRD_FINALIZED.md` per method.

**Counts:** ambiguity-pins **14**, mismatch-revisions **1** (15 edits total). The one mismatch is a closed-list gap: an error code the impl raises that the PRD's enumerations omitted entirely.

**Changes:**
- §2.3 — revise — ambiguity — pin limit/offset clamping (below-1/above-100 clamped, negative offset→0), non-integer→`ERR_INVALID_REQUEST`, and creation-order tie-break for list sort — `app.py:349-372, 382`
- §2.7 — revise — mismatch — add `ERR_CONDITION_READING_NOT_FOUND` to the not-found catalogue (impl raises it; PRD listed none for readings) — `app.py:57, 1465`
- §2.10 — insert — ambiguity — pin that `created_at`/`updated_at`/`api_request_timestamp` all read the logical clock — `app.py:156-169`
- §3.1 — insert — ambiguity — opening a non-`SCHEDULED` trip → `ERR_INVALID_TRIP_STATE` — `app.py:680-681`
- §3.1 — insert — ambiguity — deactivating an already-`INACTIVE` guide is a no-op; define "non-terminal trip" as not `CANCELLED`/`COMPLETED` — `app.py:765-772`
- §3.1 — insert — ambiguity — releasing an already-`RELEASED` guide assignment is a no-op — `app.py:846`
- §3.2 — insert — ambiguity — `gratuity_cents` starts 0, `final_total_cents` starts null at creation — `app.py:895-897`
- §3.2 — insert — ambiguity — confirm on already-`CANCELLED`→`ERR_RESERVATION_CANCELLED`, other non-`PENDING`→`ERR_INVALID_RESERVATION_STATE` — `app.py:933-936`
- §3.4 — insert — ambiguity — releasing a non-`ASSIGNED` gear assignment → `ERR_INVALID_GEAR_STATE` — `app.py:1293-1294`
- §3.5 — insert — ambiguity — check-in on `CANCELLED`→`ERR_RESERVATION_CANCELLED`, other non-`CONFIRMED`→`ERR_INVALID_RESERVATION_STATE` — `app.py:992-995`
- §3.6 — insert — ambiguity — pay-deposit requires `payment_status` `UNPAID` else `ERR_INVALID_RESERVATION_STATE` — `app.py:974-975`
- §3.6 — insert — ambiguity — settle: `CANCELLED`→`ERR_RESERVATION_CANCELLED` first, then `DEPOSIT_PAID` precondition→`ERR_INVALID_RESERVATION_STATE` — `app.py:1035-1040`
- §3.8 — insert — ambiguity — cancelling an already-`CANCELLED` shuttle run is a no-op — `app.py:1399`
- §3.9 — insert — ambiguity — completing a trip not in `OPEN`/`FULL` → `ERR_INVALID_TRIP_STATE` — `app.py:693-694`
- §3.9 — insert — ambiguity — direct cancel of a `CANCELLED`/`COMPLETED` trip → `ERR_INVALID_TRIP_STATE`; cancel of an already-`CANCELLED` or `COMPLETED` reservation → `ERR_RESERVATION_CANCELLED`/`ERR_INVALID_RESERVATION_STATE` — `app.py:718-719, 1060-1063`
- §5 — insert — mismatch — add `ERR_CONDITION_READING_NOT_FOUND | 404` row (companion to §2.7 fix) — `app.py:57`

Note: `test_helpers/` and `test_suite/` directories do not exist in this workspace; alignment was performed against `implementation/app.py` alone (the sole source), consistent with the instruction that implementation is the authority.

### Orchestrator verification

`PRD_COMPLETED.md` exists: 293 lines / 42,318 chars, matching the subagent's reported figures. `PRD.md` and `PRD_FINALIZED.md` re-verified byte-identical to each other and unmodified. `SCAFFOLD*.yaml`, `implementation/`, `test_suite/`, `test_helpers/` untouched.

Caveat on the subagent's closing note: `test_helpers/` and `test_suite/` DO exist, at the task-dir level rather than under `workspace/`. The subagent looked only under `workspace/` and concluded they were absent, so it never consulted them. Per the Step 9 prompt tests are auxiliary cross-reference and explicitly NOT authority — `implementation/` is the alignment target — so the omission does not invalidate the patch, but the cross-reference pass was not performed.
