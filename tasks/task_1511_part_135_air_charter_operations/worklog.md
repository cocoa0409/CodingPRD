# Worklog — task_1511_part_135_air_charter_operations

## Step 1: Create Task Directory — 2026-08-13T15:21:00.000Z

Task directory `tasks/task_1511_part_135_air_charter_operations/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Verified existence; no index scan performed, no other task directory touched.

## Step 2: Generate Scaffold — 2026-08-13T16:53:30.000Z

All checks pass. Final state:

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## What was generated

Three files in `/home/ubuntu/github/CodingPRD/tasks/task_1511_part_135_air_charter_operations/`:

**SCAFFOLD.yaml** — §1.0–§1.7 for a Part 135 charter-operations API (prefix `/charter`):
- **Complexity profile**: temporal-windowing primary + compliance/audit secondary; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, scheduled_actions; flat topology; cyclic state machines; peer_roles with entity-backed AircraftOwner/CrewMember ownership checks; immediate consistency.
- **15 entities** (AircraftOwner, Aircraft, CrewMember, TripRequest, QuoteLeg, AircraftAssignment, CrewAssignment, MaintenanceWindow, Passenger, OverflightPermit, Payment, FlightLog, OwnerStatement, ComplianceFinding [polymorphic subject], WeatherAdvisory) — all FKs use the canonical `FK -> X.id` prefix and have reverse-reachability GETs.
- **9 state machines** with non-linear shapes on multiple entities: TripRequest requote cycle (QUOTED→QUOTE_DRAFT) plus a parallel derived `payment_posture` axis; CrewAssignment PROPOSED→VETTED→PROPOSED re-vet loop; Aircraft AVAILABLE↔IN_TRIP/MAINTENANCE_HOLD/GROUNDED cycles; Passenger TSA CLEARED→EXPIRED→CLEARED; permit GRANTED→EXPIRED.
- **8 calculations**, all constants and rounding orders pinned; dual variants on two different domains (quote-vs-final trip pricing; STANDARD-vs-GUARANTEED owner payout with negative operator residual allowed).
- **2 OCC concurrency rules** (requote, assignment-create-with-supersede; both guarded by `expected_trip_request_version`, HTTP 412, checked at priority 6 before state preconditions).
- **11 prioritized validation layers**, **61 endpoints** (incl. `POST /charter/_clock/set_current_utc` with the mandatory fixed default `2026-08-01T00:00:00Z`), **54 error codes**, **7 roles**.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 22 instances (≥2 per rule; 3 each for combinatorial_formula [modes a, b, c distinctly], boundary_precision_check, cross_entity_state_dependency, compensating_invariant), each with fully structured `setup_api_calls`/`trigger`/`assert` chains.

**SCAFFOLD_CORNER_DESIGN.yaml** — 96 instances (84 active recipes + 12 `excluded_because` stubs) across all nine claim-extraction sections; every one of the 54 error codes is exercised by at least one recipe or covered stub; includes all 13 per-resource not-found probes, invalid-transition/terminal-lockdown tests per machine, RBAC denials, OCC stale-version tests, clock-driven expiry sweeps, pagination/envelope checks.

All formula-derived assert literals (e.g., quote 360001 with the 1-cent round-per-leg trap, 2052000 discount-surcharge order, refund splits 1026000/1026000 and 205200/1846800, owner share 520000 vs 377600 with operator_retained −48000) were verified by executing the formulas as Python. Difficulty deliberately exceeds the Expert band as requested, while the design stays lint-clean and self-consistent per the skill's checklist.

## Step 3: Copy Shared Files — 2026-08-13T15:22:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1511_part_135_air_charter_operations/workspace/INSTRUCTION.md` (done early, while Step 2 subagent runs, since it has no dependency on the scaffold).

## Step 4: Generate PRD — 2026-08-13T17:35:00.000Z

PRD generation is complete and all three hard contracts pass.

## What was done

Generated `/home/ubuntu/github/CodingPRD/tasks/task_1511_part_135_air_charter_operations/workspace/PRD.md` (325 lines) from the scaffold, per the prd-bench-doc-generator specification. The two difficulty-design files were not opened or referenced in any way. (Note: the first PRD subagent attempt died on an API connection error mid-write; it was resumed via its intact context and completed on the second attempt.)

**Document skeleton (domain-derived, not template-copied):**
- §1: 2-paragraph introduction (business context → system-of-record/logical-clock angle)
- §2: 11 subsections — RBAC with per-role identity prose, verbatim §2.2 response-envelope block (byte-for-byte verified against the source file), pagination, the logical clock and pinned expiry sweep, common resource properties (with the `Payment`/`FlightLog`/`WeatherAdvisory` `updated_at`/`version` absence called out), money/rounding discipline, OCC, half-open vs. closed interval arithmetic, cascade discipline, nested retrieval with the full 404 family, and the 11-tier validation priority order
- §3: 9 subsections organized along the trip lifecycle (registry → itinerary → quoting → booking/payments/cancellation → aircraft assignment/maintenance/grounding → crew legality → manifest/permits → dispatch gates → logging/completion/owner settlement), with endpoint parameters scattered across subsections and constants embedded in context (6000 minutes rendered as "one hundred hours", 840 as "fourteen hours", etc.)
- §4: 61-row endpoint table (Method, Path, Description, Authorized Role(s) only) — matches scaffold count
- §5: 54-row error catalogue (Error ID, HTTP Status Code only) — matches scaffold count

## Hard Contract Reports

```
Field coverage check:
- entities[].fields + endpoints[].input/query/path params: 88 required, 88 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 11 checked, 11 expressed in prose (§2.11 ordered cascade + dispatch sub-order in §3.8), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (requote + assignment-create, expected_trip_request_version + ERR_STALE_VERSION/412 named, pre-state evaluation stated), 0 missing
- state_machines[].transitions: 27 checked (across 9 machines), 27 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed in precise prose (pinned rounding/evaluation orders, boundary inclusivity, dual quote/final variants, STANDARD/GUARANTEED owner variants), 0 missing
- validations[] conditions: 11 checked, 11 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 61 checked, 61 expressed, 0 missing
- entities[].fields[] structured content: 88 checked (defaults, initial states, nullability, computed-field semantics), 88 reconstructible, 0 missing
- sibling-branch symmetry: 6 groups checked (screen outcomes, permit decisions, vet outcomes, leg-type billing, owner variants, cancel reasons), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 502
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 emitted byte-for-byte verbatim (placeholders `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `UNIQUE_ERROR_IDENTIFIER_STRING`, `"data": { }` intact); all 54 error IDs appear in backticks in §2/§3 prose; all 7 role names spelled exactly; all 54 enum/state values present; no pseudocode operator syntax (`==`, `>=`, `+=`, …) anywhere; no fuzzy/approximating wording (the single "around" hit is inside the domain term "turnaround buffer"); document ends at §5 with no audit footer.

## Step 6: Generate Implementation — 2026-08-13T18:24:00.000Z

All done. The leftover PIDs were my own probe shells; no servers remain and `__pycache__` is removed.

## Summary

Generated a complete Python + Flask implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1511_part_135_air_charter_operations/workspace/implementation/`:

**Files**
- `start.sh` — guarded dependency install (`if ! python3 -c "import flask"`, so per-test reboots skip pip), `exec python3 app.py` in foreground, binds `0.0.0.0:$PORT` (default 10000)
- `app.py` — Flask app factory, 4 blueprints, error handlers
- `store.py` — in-memory dicts per entity, **empty on every boot** (no seeding), logical clock starting exactly `2026-08-01T00:00:00Z`, monotonic insertion seq for `created_at` tie-breaking
- `util.py` — ISO 8601 parse/format (3 fractional digits, `Z`), `Decimal` round-half-up money math
- `httpkit.py` — response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; error body `error_id`/`message`), auth on `X-User-ID`/`X-User-Role` with the 7 declared roles, strict body validation, `limit`/`offset` pagination (default 10, min 1, max 100)
- `serializers.py` — all 15 entities; `Payment`/`FlightLog`/`WeatherAdvisory` serialize as ledger records (no `updated_at`/`version`)
- `services.py` — all 8 calculations (quote_price with pinned per-leg rounding then discount-tier then surcharge-on-discounted, final_price with 60-min revenue minimum and planned-minutes positioning, cancellation_refund with 72h/24h `>=` boundaries via `Decimal`, crew_duty_legality with 840/600 inclusive limits and overlap-gap-0 rule, check_hours_projection, payment_posture, owner_statement with guarantee floor, time_based_expiry sweep in pinned trips→passengers→permits→windows order) plus cascades (ground, completion, cancel, re-vet loops)
- `routes_registry.py`, `routes_trips.py`, `routes_assignments.py`, `routes_ops.py` — all 62 endpoints

**Key fidelity decisions**
- Validation cascade follows PRD §2.11 exactly: auth → role gate → body shape → time-range → existence (left-to-right) → OCC (`ERR_STALE_VERSION` before state checks) → state → compliance sub-order → interval conflicts (half-open buffered for assignments vs closed touching-counts for maintenance) → cross-reference → money gates last
- Flight-log PIC ownership is evaluated after trip/leg existence (so a bogus `trip_request_id` yields 404, a non-PIC on a valid trip yields 403)
- Trip `version` bumps only on declared trip-mutating operations (quote/requote/book/cancel/dispatch/assignment-create/payment/sweep-expiry), never on leg add/delete; cascaded entities each get their own `touch()`
- `quoted_total_cents` etc. null until QUOTED; `planned_duty_minutes` computed at vet (kept, not cleared, on re-vet reset — only `duty_legal`/`rest_legal`/`vetted_at` clear per PRD); clock rejects backward moves with `ERR_INVALID_REQUEST`

**Verification**: ~150 end-to-end assertions across 5 smoke waves all pass against fresh `bash start.sh` boots, including exact cent math (tier boundaries at 2,000,000/5,000,000, per-leg rounding order, guarantee binding with zero operator residual), half-open touching boundary confirm, IN_TRIP maintenance-activation skip with retry on next clock set, post-dispatch OPS cancel returning the tail to AVAILABLE, and version progression through the full lifecycle.

## Step 5: Generate Unit Tests — 2026-08-13T18:35:00.000Z

Generation complete and fully verified.

## Summary

**Stage 1 — `test_helpers/`** (9 files, all importing cleanly):
- `types.py` — 20 enums + 15 entity TypedDicts; ledger-style `Payment`/`FlightLog`/`WeatherAdvisory` correctly omit `updated_at`/`version` per PRD §2.5
- `api_client.py` — `ApiClient(GenericApiClient)` with all 61 endpoints under the `/charter` prefix
- `api_errors.py` — all 54 error IDs with HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions (ledger entities assert `updated_at`/`version` absence) + `assert_statement_conservation` / `assert_trip_money_invariants`
- `factories.py`, `constants.py` (rate card, 840/600/6000 thresholds, tier boundaries, precomputed canonical quotes), `test_users.py` (7 roles; mandatory `make_aircraft_owner_headers`/`make_crew_member_headers` per-instance builders for the entity-backed roles)
- `fixtures.py` — full ops-chain spine: `setup_quoted_trip` → `setup_booked_trip` → `setup_trip_with_confirmed_aircraft` → `setup_dispatch_ready` (crew vet, manifest screening, permit grants) → `setup_dispatched_trip` → `setup_completed_trip` (flight logs posted as the VETTED PIC via identity-bound headers), all amounts derived from live responses, OCC versions fetched fresh per call

**Stage 2 — `test_suite/`** (13 files + conftest, 130 tests):
- Every one of the 22 difficulty instances has ≥2 tests; every one of the 84 non-stub corner instances has ≥1 test; the 12 `excluded_because` stubs are untranslated (cross-references verified to resolve)
- Zero instances failed the PRD-first filter — every asserted rule has verbatim PRD coverage (the PRD is unusually complete: pinned rounding/evaluation orders, boundary inclusivity, validation tier ordering, and both dual variants are all in prose)

**Verification results:**
- Coverage audit: NONE missing, NONE dangling, no stub translated
- Citation audit (AST-parsed docstrings): all 130 tests carry a ≥8-word quoted span surviving literal grep of `PRD.md`, with exactly one `Design:` tag as the last docstring line
- No `skip`/`skipif`/`xfail` markers; no scaffold references in comments
- `pytest --collect-only`: 130 tests collected, 0 errors

**One deliberate setup repair:** corner instance `duplicate_flight_log_rejected` was emitted with a two-leg itinerary instead of the design's literal single-leg chain — with one leg, the first log completes the trip and the second posting would hit the `ERR_INVALID_STATE` state gate (priority 7) before the duplicate gate (priority 10), making the asserted `ERR_DUPLICATE_FLIGHT_LOG` unreachable under the PRD's own validation order. The repair keeps the asserted rule (verbatim in PRD §3.9) reachable; the deviation is documented in the test docstring.

## Step 7: Run Tests and Iterate — 2026-08-13T18:47:00.000Z

All 8 rounds pass cleanly: **130/130 in every round**. The fix holds under the full parallel stability sweep.

## Summary

**Iterations run:** 2 (sweep 1: 115/130 with 15 deterministic failures across all 8 rounds; sweep 2 after fixes: 130/130 × 8 rounds).

**Tests deleted:** none — every failing test traced to verbatim PRD prose; all failures were test-artifact bugs, not PRD-silent assertions.

**Fixes applied to `test_helpers/`:**

- `/home/ubuntu/github/CodingPRD/tasks/task_1511_part_135_air_charter_operations/test_helpers/fixtures.py` — `_parse()` helper: rejected the server's ISO 8601 timestamps with three fractional digits (`2026-08-10T10:00:00.000Z`), the exact format PRD §2.5 mandates ("ISO 8601 UTC with three fractional digits"). Replaced `strptime("%Y-%m-%dT%H:%M:%SZ")` with `datetime.fromisoformat(ts.replace("Z", "+00:00"))`. Fixed 8 tests that build on `setup_completed_trip` (test_10 ×3, test_11 ×4, test_12 ×1).

**Fixes applied to `test_suite/`:**

- `/home/ubuntu/github/CodingPRD/tasks/task_1511_part_135_air_charter_operations/test_suite/test_04_payments_and_cancellation.py` — added `cancel_trip` to the `from test_helpers import (...)` list; 5 tests called it bare (`NameError`). The helper exists in `fixtures.py` and is exported via the barrel.
- `/home/ubuntu/github/CodingPRD/tasks/task_1511_part_135_air_charter_operations/test_suite/test_08_passengers_and_permits.py` — `test_trip_manifest_lists_exactly_its_passengers`: setup added passengers to a raw `QUOTE_DRAFT` trip, violating the PRD §3.7 precondition ("Passengers may be added while the trip is `QUOTED` or `BOOKED`; against any other status the add is rejected with `ERR_INVALID_STATE`"). The implementation's 409 was PRD-correct; switched setup to `_quoted_trip(passenger_count=2, ...)` so the manifest add happens on a QUOTED trip.

**Fixes applied to `implementation/`:** none — in all 15 failures the implementation behaved exactly as PRD requires (correct rejection of passenger-add on QUOTE_DRAFT, correct 3-fractional-digit timestamps, correct cancellation math). No PRD-required check was weakened and nothing was added to the implementation.

## Step 8: Finalize PRD — 2026-08-13T18:56:00.000Z

Done. The diff is exactly one sentence inserted inline into the §2.5 paragraph (line 80); line count unchanged.

## Summary

**Line counts / delta:** PRD.md 325 lines; PRD_FINALIZED.md 325 lines — 0% line-count delta. One sentence inserted inline within the existing §2.5 paragraph.

**Changes (one total):**
- §2.5 — revise — appended "The same rendering applies to every timestamp the server emits: server-stamped fields and echoes of client-supplied instants (such as `departure_at`) are all rendered as ISO 8601 UTC with three fractional digits." — `implementation/util.py:17-24` (`fmt_ts`), `implementation/serializers.py:13-223` (every timestamp field routed through `fmt_ts`), `implementation/httpkit.py:69` (meta timestamp via `wall_now_ts`).

**Per-edit pre-edit search log (the single edit):**
- (a) Subject: server-side rendering format of timestamp fields in responses (the Step 7 `_parse` fixture fix revealed the PRD pins three-fractional-digit rendering only for `created_at` (§2.5) and `api_request_timestamp` (§2.2), while the field that actually broke the fixture was `departure_at` — a client-supplied instant the server re-emits normalized to `.000Z`; fixtures.py:336).
- (b) Paths enumerated and read/grepped: `util.py:17-24` (`fmt_ts` — sole renderer, UTC-normalizing, `.{millis:03d}Z`); full `serializers.py` (all 20+ timestamp emission callsites: created_at, updated_at, departure_at, quote_valid_until, occupied_start_at/end_at, vetted_at, starts_at/ends_at for windows and advisories, screened_at, decided_at, departed_at, arrived_at, issued_at, resolved_at — all via `fmt_ts`); `httpkit.py:66-73` (meta via `wall_now_ts`); grep for `strftime|isoformat|timestamp` across all impl files confirming no emission bypass; all four route modules read end-to-end confirming every response passes through serializers. Exclusions checked: `date_of_birth` (`serializers.py:142`) is emitted verbatim but is an ISO 8601 *date* per §3.7, not a timestamp; null-valued timestamps render as JSON null (already covered by existing "stay null" prose); input *acceptance* breadth (`util.py:12-14`) is untouched — the sentence covers emission only.
- (c) Wording adjustment: scoped the sentence to "every timestamp the server emits" (not "every field"), and used "rendered" (emission-only) so as not to pin input acceptance or sweep in the verbatim-emitted `date_of_birth` date; no universal claim about request parsing was made.

**Step 7 items verified with no edit (PRD already uniquely determines; prose kept verbatim):**
- test_04 import fix (`cancel_trip`): pure test-artifact bug, no PRD subject. The cancellation math it exercised is pinned verbatim in §3.4 (72/24-hour tiers, inclusive boundaries, fee on collected, round-half-up, refund = collected − fee, REFUND row only when positive, posture recompute) and the impl matches exactly — `routes_trips.py:178-219`, `services.py:41-45` and `348-369`.
- test_08 manifest-setup fix: §3.7 already states verbatim "Passengers may be added while the trip is `QUOTED` or `BOOKED`; against any other status the add is rejected with `ERR_INVALID_STATE`", and the §5 catalogue pins `ERR_INVALID_STATE` → 409. Impl `routes_ops.py:166-168` matches exactly, with existence (`get_trip_or_404`) evaluated before the state gate per §2.11. No residual ambiguity; no edit.

## Step 9: Complete PRD — 2026-08-13T19:20:00.000Z

Done. PRD_COMPLETED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1511_part_135_air_charter_operations/workspace/PRD_COMPLETED.md`.

## Summary

**Source vs output**: `PRD_FINALIZED.md` 325 lines / 52,362 chars → `PRD_COMPLETED.md` 326 lines / 55,182 chars (char-delta **+2,820**, +1 line = the single new error-catalogue row). No sections added; all other changes are in-paragraph inserts/revisions.

**Counts**: 15 ambiguity-pins, 5 mismatch-revisions (20 changes total).

### Changes

- §2.1 — insert — ambiguity — empty `X-User-ID` value counts as a missing header — implementation/httpkit.py:118
- §2.2 — insert — ambiguity — unexpected internal failure answered HTTP 500 with `error_id` `ERR_INTERNAL` in the same envelope — implementation/app.py:37-39
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` and negative/non-integer `offset` rejected with `ERR_INVALID_REQUEST` — implementation/httpkit.py:233-258
- §2.3 — insert — ambiguity — `created_at` sort ties broken by creation sequence — implementation/httpkit.py:262-264
- §2.3 — insert — ambiguity — `total_count` counts all filter-matching resources before pagination; `has_more` true iff `offset`+`limit` < `total_count` — implementation/httpkit.py:81-90, 267-271
- §2.4 — insert — ambiguity — clock never moves backward: earlier `to_iso8601` rejected `ERR_INVALID_REQUEST`, same instant accepted, sweep runs on every accepted set — implementation/routes_ops.py:575-580
- §2.5 — insert — ambiguity — client instants parsed leniently (missing offset read as UTC) and re-rendered canonical; resource timestamps stamped from the logical clock, only envelope `api_request_timestamp` uses wall clock — implementation/util.py:27-48, implementation/services.py:70-93
- §2.5 — insert — ambiguity — `version` starts at 1 on creation — implementation/services.py:76-84
- §2.10 — insert — ambiguity — request to undeclared path/method rejected `ERR_INVALID_REQUEST` (400), not 404 — implementation/app.py:27-35
- §2.11 item 2 — revise — mismatch — flight-log PIC identity check is the exception to tier-2 placement: evaluated after existence (it reads the trip's crew assignments) — implementation/routes_ops.py:347-358
- §2.11 item 3 — insert — ambiguity — body must be valid JSON object with no undeclared fields; declared ranges (`revenue_share_pct` 0–100; non-negative `guarantee_cents_per_block_min`, `hourly_rate_cents`, `initial_airframe_minutes`, `next_check_due_minutes`, `passenger_count`); payload-less action POSTs and the quote-leg DELETE reject any non-empty body — implementation/httpkit.py:162-213, routes_registry.py:34-41/86-92, routes_trips.py:49-50
- §3.1 — revise — mismatch — "a unique `tail_number`" → recorded as supplied, uniqueness not enforced (impl has no uniqueness check) — implementation/routes_registry.py:71-109
- §3.6 — insert — ambiguity — crew-assignment creation with a non-`ACTIVE` member rejected `ERR_INVALID_STATE` — implementation/routes_assignments.py:178-180
- §3.6 — insert — ambiguity — re-vet resets clear only `duty_legal`/`rest_legal`/`vetted_at`; `planned_duty_minutes` keeps its last computed value — implementation/services.py:428-437
- §3.7 — revise — mismatch — `date_of_birth` carried as opaque string; format not validated — implementation/routes_ops.py:163
- §3.7 — revise — mismatch — "two-letter `country_code`" → conventionally two letters, any string accepted — implementation/routes_ops.py:226
- §3.8 — revise — ambiguity — international permit gate: at least one permit of either type must exist (impl counts both OVERFLIGHT and LANDING rows) — implementation/routes_trips.py:278-284
- §3.9 — insert — mismatch — PIC identity check evaluated after trip/leg existence, before the `DISPATCHED` state precondition — implementation/routes_ops.py:347-362
- §4 table (8 rows) — revise — ambiguity — filter descriptions now name exact query parameters: aircraft `owner_id`/`category`/`status`; crew-members, trip-requests `status`; aircraft-assignments `trip_request_id`/`aircraft_id`/`status`; crew-assignments `trip_request_id`/`crew_member_id`/`status`; flight-logs `trip_request_id`/`quote_leg_id`; findings `subject_type`/`subject_id`/`status`; advisories `station_icao` — implementation/routes_registry.py:117-125/213-215, routes_trips.py:81-83, routes_assignments.py:70-78/205-213, routes_ops.py:403-408/491-499/558-560
- §5 — insert — ambiguity — added `ERR_INTERNAL` | 500 Internal Server Error row — implementation/app.py:37-39

**Notable non-changes (verified already pinned and matching impl)**: full quote/final pricing formulas and rounding order, deposit 25%, cancellation fee tiers with 72h/24h boundaries, OCC tier placement on requote/assignment-create, dispatch gate sub-order, confirm gate order, sweep order and strictness (`>` for expiry, `<=` for window activation), half-open vs closed interval rules, ledger-resource field shape, owner-statement math and conservation, and the crew duty (840) / rest (600) computations.
