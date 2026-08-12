# Worklog — task_1152_tugboat_harbor_assist_services

## Step 1: Create task directory — 2026-08-11T03:22:00.000Z

Task directory `tasks/task_1152_tugboat_harbor_assist_services/` and its `workspace/` subdirectory were pre-assigned and already exist. Step 1 auto-index scan skipped per instructions.

## Step 2: Generate scaffold — 2026-08-11T04:07:30.000Z

Scaffold generation complete for task 1152 (Tugboat & Harbor Assist Services), calibrated above the Expert band per the "harder than expert" directive. Lint verdict (verbatim):

```
Coverage
  §1.5 endpoints declared:    53
  §1.1 entities declared:     14
  §1.8 instances scanned:     19
  §1.9 instances scanned:     42
  Calls scanned (§1.8+§1.9):  561

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files written:
- `/home/ubuntu/github/CodingPRD/tasks/task_1152_tugboat_harbor_assist_services/SCAFFOLD.yaml` — 76,223 B (§1.0–§1.7; no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1152_tugboat_harbor_assist_services/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 88,868 B (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1152_tugboat_harbor_assist_services/SCAFFOLD_CORNER_DESIGN.yaml` — 94,128 B (single key `scaffold_corner_design`)

Counts:
- Entities: 14 (Vessel, Tug, Pilot, CrewMember, TariffRate, JobOrder, TugAssignment, PilotBooking, WatchRotation, GearInspection, Incident, WeatherRestriction, Invoice, DamageClaim)
- Endpoints: 53; Errors: 28; Validations: 28 priority-ordered rows; State machines: 8 (three cyclic: JobOrder amend/hold loops, DamageClaim review loop, Tug operational-status cycle); Calculations: 6; Roles: 7 (peer roles with entity_backed Vessel/Pilot/Tug identities and segregation of duties for ClaimsAdjuster); OCC concurrency rules: 3
- §1.8 difficulty instances: 19 (all 9 rules ≥2; combinatorial_formula has 3 covering modes a/b/c)
- §1.9 corner instances: 49 total (42 active + 7 `excluded_because` stubs), spanning all nine guide sections

Key design adjudications:
- Dual variants pinned on two distinct domains: Invoice SCHEDULED-vs-ACTUAL billing (standby forced to 0 provisionally) and DamageClaim PER_INCIDENT-vs-PER_VOYAGE liability caps (variant selected by whether the job's invoice is FINALIZED at claim time). All numeric asserts were pre-computed (740000/765000/790000/851000 cents; payouts 9000000/10800000/4500000).
- Rounding order pinned per-line-then-sum; the mode-(b) instance uses 100001 cents/h × 0.33 h lines so the two orders provably diverge (66000 vs 66001).
- Overlap semantics deliberately differentiated: tugs use strict half-open adjacency; pilots use a 60-minute turnaround buffer; weather uses half-open window intersection driving the ON_HOLD auto-transition.
- Compensating invariants cover two conserved quantities: tug/pilot commitment counts (confirm+cancel) and Vessel.outstanding_billed_cents (complete/finalize+void).
- Damage claims open the investigation (REPORTED→UNDER_INVESTIGATION) and are rejected on RESOLVED incidents (ERR_INCIDENT_ALREADY_RESOLVED) — chose this over claims-after-resolution to keep the Incident machine cyclic-adjacent and the claim state gating testable.
- Logical clock endpoint declared with the mandatory 2026-05-01T00:00:00Z default; a corner instance proves the default without ever setting the clock.
- GearInspection kept as an append-only event (`common_fields: false`) with a dedicated immutability corner.

## Step 3: Copy shared files — 2026-08-11T04:08:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1152_tugboat_harbor_assist_services/workspace/INSTRUCTION.md` (1,424 B).

## Step 4: Generate PRD — 2026-08-11T04:24:30.000Z

PRD generation complete. Summary:

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1152_tugboat_harbor_assist_services/workspace/PRD.md` — 46,498 bytes, 299 lines.

**Section coverage** (all scaffold sections projected to prose):
- §1 Introduction (2 paragraphs, business-context angle)
- §2.1 Roles/RBAC (7 roles with exact spellings; entity-backed identity prose for `VesselAgent`/`Pilot`/`TugCaptain`, opaque for the other four) · §2.2 response envelope (verbatim, byte-identical PASS) · §2.3 Pagination (limit 10/1/100, offset 0, created_at ascending) · §2.4 Logical clock (startup default 2026-05-01T00:00:00Z, `to_iso8601`/`current_utc`) + half-open window convention · §2.5 Common properties (UUID `id`, `created_at`/`updated_at`/`version`; explicit GearInspection exception — `id`+`created_at` only) · §2.6 OCC (all 3 rules with occ field + `ERR_STALE_VERSION`/412) · §2.7 Money/rounding (integer cents, pinned per-line round-half-up before summation) · §2.8 Validation pipeline (priorities 1–28 as an explicit 11-stage ordered list) · §2.9 Cascading consistency + left-to-right nested retrieval
- §3 in 9 subsections (reference data, job ordering/amendment, tug assignments, pilot bookings, crew watches, gear/incidents/tug availability, weather restrictions, invoicing SCHEDULED-vs-ACTUAL, damage claims/liability) — every state machine (41 transition pairs), all 6 calculations (maneuver factors 1.5/1.2/1.0/0.8/2.0, 200m/1.25 LOA surcharge, 20.0t floor, standby blocks with boundary rule, pinned liability waterfall with 10,000,000-cent floor / 20x voyage multiple / half insured value / 10% deductible, 24h/10-hour crew rest, vessel outstanding aggregation), all cascades (amend-supersede, tug-failure supersede-and-demote with `needs_reassignment`, weather hold/lift, completion settle, finalize, void, settle)
- §4 endpoint table: 53 rows, 4 columns only · §5 error catalogue: 28 rows, 2 columns only

**Zero-silence audit**: PASS on all three hard contracts.
- Contract 1: 81/81 field names present in backticks, 0 missing; 28/28 error IDs; 61/61 enum/state values
- Contract 2: 41/41 transition pairs with preconditions/side-effects; all constants embedded; all validation priorities ordered in prose; all 3 OCC rules fully expressed; applies_to scopes enumerated
- Contract 3: 441 backtick tokens scanned in §3 — 0 paths, 0 bare HTTP methods, 0 method+path combos

**Ambiguities resolved in prose**: (1) numeric field constraints (`deadweight_tonnage`>0 etc.) stated as registration requirements without inventing an error ID the scaffold doesn't declare; (2) `max_watch_hours` described as a recorded profile limit with default 12, no invented enforcement since no scaffold validation references it; (3) the tug-assignment-creation side effect of incrementing the parent job's `version` was surfaced explicitly as the serialization point between consecutive proposals; (4) 600 rest minutes expressed as "ten hours" and 1,440-minute day for inference difficulty, with exact figures preserved.

## Step 5: Generate unit tests — 2026-08-11T04:45:00.000Z

Generation complete. Final summary:

## Files written

**test_helpers/** (9 files, 1517 lines):
- `__init__.py` (35 lines) — barrel export of framework + PRD-specific code
- `types.py` (332 lines) — status enums, UserRole, TypedDicts for all 14 entities (GearInspection omits `updated_at`/`version` per common_fields: false)
- `api_client.py` (199 lines) — ApiClient subclassing GenericApiClient with one method per endpoint (~40 methods)
- `api_errors.py` (70 lines) — 28 ApiErrorId values + HTTP status map registered with `set_error_http_status_map`
- `assertions.py` (231 lines) — per-entity assert functions + domain invariant checkers
- `factories.py` (196 lines) — 13 payload factories, input fields only
- `constants.py` (32 lines) — maneuver factors, LOA threshold, liability constants, rest minutes
- `test_users.py` (34 lines) — TEST_USERS dict + per-instance builders for the 3 entity_backed roles (Vessel, Pilot, Tug)
- `fixtures.py` (388 lines) — composite fixtures across 5 tiers (reference data, job lifecycle primitives, confirmed/dispatched/completed chains, incident/claim chains, weather helpers)

**test_suite/** (11 files, 2737 lines):
- `conftest.py` (45 lines) — pytest fixtures bridging TEST_USERS
- `test_01_reference_data.py` (169) — 6 tests
- `test_02_auth_and_request_shape.py` (218) — 9 tests
- `test_03_job_order_lifecycle.py` (234) — 7 tests
- `test_04_assignments_and_bookings.py` (395) — 10 tests
- `test_05_dispatch_gates.py` (390) — 11 tests
- `test_06_weather_and_amend_cycles.py` (237) — 5 tests
- `test_07_watches_and_crew.py` (144) — 3 tests
- `test_08_invoices.py` (323) — 11 tests
- `test_09_cascades.py` (289) — 9 tests
- `test_10_damage_claims.py` (293) — 9 tests

## Test count: 80

## Queue A coverage (SCAFFOLD_DIFFICULTY_DESIGN)
19/19 instances translated with ≥2 tests each (38 tests). 0 skipped.

## Queue B coverage (SCAFFOLD_CORNER_DESIGN)
42/42 non-stub instances translated with ≥1 test each (42 tests). 0 skipped. All 7 `excluded_because:` stubs correctly not emitted (their owning difficulty instances cover them).

## Lint / audit verdicts
- **py_compile**: all 20 files pass
- **Design tag audit**: 80 tags, 0 missing, 0 stub leaks, 0 unknown, all resolve to real instances
- **Docstring shape**: every test function's docstring ends with exactly one `Design:` line (80/80)
- **PRD verbatim grep**: 87 quoted citations, 87 survive literal grep against PRD.md (after fixing 2 ellipsis-bearing citations)
- **Silence-pattern sweep**: no `pytest.mark.skip` / `skipif` / `xfail`; no scaffold-table references in generated code; no freelance tests outside the two design indices

## Step 6: Generate implementation — 2026-08-11T04:45:00.000Z

All clean. Implementation complete.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1152_tugboat_harbor_assist_services/workspace/implementation/`):

| File | Size | Purpose |
|---|---|---|
| `start.sh` | 341 B | Foreground launcher, `exec python3 app.py`, guarded `pip install` (no-op when Flask present), reads `$PORT`, binds 0.0.0.0 |
| `requirements.txt` | 11 B | `flask>=2.0` |
| `app.py` | 1,453 B | Entry point, blueprint registration, per-request RLock, envelope error handlers (ApiError/404/405/exception) |
| `db.py` | 1,558 B | In-memory store (14 dicts), logical clock defaulting to exactly `2026-05-01T00:00:00Z`, monotonic seq, `stamp_new`/`touch` (version starts 1, +1 per mutation incl. cascades) |
| `errors.py` | 314 B | `ApiError` carrying error_id/http_status/message |
| `util.py` | 8,226 B | Envelope (`meta.api_request_id/api_request_timestamp`, `response_type`, `data`; list meta `limit/offset/total_count/has_more`), auth (`X-User-ID`/`X-User-Role`, 7 roles), ISO-8601 parse/format (3 fractional digits, Z), half-open overlap, deferred shape/enum collector (PRD §2.8 stages 27/28 last), pagination (limit 1–100 default 10, offset ≥ 0) |
| `calc.py` | 17,002 B | All 6 calculations + all cascades + 14 serializers |
| `routes_refdata.py` | 7,212 B | tugs, vessels, pilots, crew-members, tariff-rates |
| `routes_jobs.py` | 11,821 B | job-orders CRUD + amend/confirm/dispatch/start/complete/cancel |
| `routes_assignments.py` | 6,336 B | tug-assignments + confirm/release |
| `routes_pilotbookings.py` | 5,979 B | pilot-bookings + confirm/board |
| `routes_watch.py` | 4,163 B | watch-rotations |
| `routes_safety.py` | 8,403 B | gear-inspections, incidents + resolve, weather-restrictions + lift |
| `routes_billing.py` | 8,608 B | invoices + finalize/void, damage-claims + review/settle |
| `routes_clock.py` | 574 B | `POST /api/_clock/set_current_utc` |

**Route count:** 53 registered method-path rules — exactly matches SCAFFOLD.yaml §1.5's 53 endpoints (including no GET-one for weather-restrictions, per spec).

**Entities implemented (14):** Vessel, Tug, Pilot, CrewMember, TariffRate, JobOrder, TugAssignment, PilotBooking, WatchRotation, GearInspection (immutable: no `updated_at`/`version` per PRD §2.5), Incident, WeatherRestriction, Invoice, DamageClaim. Storage is purely in-memory dicts; nothing seeded at startup (verified: reboot returns empty lists).

**State machines implemented (8):** JobOrder (12 transitions incl. weather-hold system transitions), TugAssignment (6), PilotBooking (7), Tug (5, with per-item gear-clean + unresolved-MAJOR/CRITICAL gates), Incident (3, incl. claim-triggered escalation), WeatherRestriction (1 with conservative hold-release), Invoice (2), DamageClaim (5).

**Key behaviors verified:** validation pipeline precedence (ownership→existence→OCC→terminal→from-state→safety→temporal→constraints→shape→enum), OCC 412s, tug-window/pilot-buffer/watch-overlap conflicts, crew rest (600-min boundary exact), gear-failure and MAJOR-incident knock-out cascades (supersede future CONFIRMED assignments → demote jobs with `needs_reassignment`), weather hold/resume, pinned half-up per-line invoice rounding (provisional SCHEDULED: 563,500¢ incl. 15% surcharge; finalized ACTUAL: 598,000¢ with 40-min standby = 1 block), liability waterfall (PER_VOYAGE 20× invoice; PER_INCIDENT 0.5× insured with 10,000,000¢ floor; 10% deductible), vessel outstanding ledger with `max(0, …)` floor on settle/void/finalize/complete.

**Boot smoke test:** `PORT=<free> bash start.sh` boots in ~1 s; unauthenticated `GET /api/tugs` → 401 `ERR_UNAUTHENTICATED` envelope; clock set → 200; kill + reboot → store empty, clock back at default. A 72-check lifecycle E2E plus a 23-check edge suite both pass with zero failures against fresh processes.

**Orchestrator route-parity check**: Flask `url_map` vs SCAFFOLD.yaml §1.5 — 53/53 (method, path) pairs match; the only extra route is Flask's built-in `/static/<path>` handler.

## Step 7: 8-round stability sweep fix loop — 2026-08-11T05:05:00.000Z

Three sweep iterations run (8 parallel rounds each, `--isolation per-test-server`).

- Iteration 1: collection failure — `test_05_dispatch_gates.py` imported `cancel_job_order` from `test_helpers`, but the helper was missing from `fixtures.py` (69/80 collected, 1 module error in every round).
- Fix (test_helpers): added `cancel_job_order(job_order_id, **overrides)` to `test_helpers/fixtures.py`, following the existing lifecycle-fixture pattern (dispatcher identity, `get_success_data` unwrapping), per PRD §3.2 cancellation semantics ("Either the ordering agent or a dispatcher may cancel a job").
- Iteration 2: 78/80 passed in all 8 rounds. Union of failures: `TestTerminalBeatsWeatherSafety::test_dispatch_on_cancelled_job_returns_already_terminal` and `::test_weather_restriction_does_not_preempt_terminal_guard` — both `NameError: name 'api' is not defined` in the `_setup_cancelled_job_with_active_restriction` helper (pytest `api` fixture not in scope inside plain helper methods).
- Fix (test_suite): in `test_05_dispatch_gates.py` `_setup_cancelled_job_with_active_restriction`, replaced the out-of-scope `api.cancel_job_order(...)` + `validate_success` pair with the newly added `cancel_job_order(job["id"], cancel_reason="Vessel diverted")` fixture — matching the class's other fixture-driven setup calls. Assertions unchanged (PRD §2.8 stage 6 terminal guard vs stage 8 weather safety, verbatim-covered).
- AST sweep over the whole suite confirmed no other bare-`api` usage in helper methods lacking an `api` parameter.
- Iteration 3: **all 8 rounds clean — 80/80 passed in every round.** No test deletions were required (both failures were test bugs, not PRD-silent assertions).

## Step 7: Run tests and iterate — 2026-08-11T05:01:00.000Z

Clean 8-round sweep achieved. Final summary:

## Summary

**Iterations run:** 3 (8 parallel rounds each, `--isolation per-test-server`, 80 tests/round)

**Final state:** All 8 rounds clean — 80/80 passed in every round (rounds 1–8, zero failed, zero errors).

**Tests deleted:** None. Both failures were test bugs (import/scope errors), not PRD-silent assertions, so no deletions were warranted under the PRD-First contract.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1152_tugboat_harbor_assist_services/test_helpers/fixtures.py` — added missing `cancel_job_order(job_order_id, **overrides)` fixture (dispatcher identity, `get_success_data` unwrap), matching the existing lifecycle-fixture pattern. The test_suite imported it but it was never defined, causing a collection-level ImportError that zeroed every round of iteration 1. PRD §3.2 covers cancellation semantics verbatim.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1152_tugboat_harbor_assist_services/test_suite/test_05_dispatch_gates.py` — in `TestTerminalBeatsWeatherSafety._setup_cancelled_job_with_active_restriction`, replaced out-of-scope `api.cancel_job_order(...)` + `validate_success(...)` (the pytest `api` fixture is not in scope inside plain helper methods → `NameError`) with the new `cancel_job_order(job["id"], cancel_reason="Vessel diverted")` fixture call. Assertions untouched — the tests still verify PRD §2.8 stage-6 terminal guard outranking stage-8 weather safety, which PRD covers verbatim. An AST sweep over the full suite confirmed no other helper methods reference bare `api`.

**Fixes applied to `implementation/`:** None required — the implementation was already PRD-faithful; all failures were in the test artifact layer.

Orchestrator verification: all 8 `results.{1..8}.json` files exist in `workspace/implementation/` and each shows passed=80 total=80 failed=0 errors=0.

## Step 8: Finalize PRD — 2026-08-11T05:04:00.000Z

## Summary

**PRD.md vs PRD_FINALIZED.md line counts and %-delta:**
- PRD.md: 299 lines; PRD_FINALIZED.md: 299 lines; delta: 0 lines, 0.0%. The files are byte-identical (verified via `diff`).

**Changes made:** None.

Both `<step_7_diff>` items were pure test-artifact bugs (a missing fixture definition and an out-of-scope fixture reference) with zero implementation fixes. Tracing each to the implementation confirmed the PRD already pins the exercised behavior verbatim:

- **Step 7 item 1 (`cancel_job_order` fixture added to `test_helpers/fixtures.py:164`)** — The fixture merely wraps `POST /api/job-orders/{id}/cancel`. The implementation (`implementation/routes_jobs.py:267-289`, cascades at `implementation/calc.py:237-248`) matches PRD §3.2 verbatim: `VesselAgent`+`PortDispatcher` roles, vessel-ownership check, optional `cancel_reason` recorded when supplied, terminal guard then from-state check admitting exactly `REQUESTED`/`CONFIRMED`/`DISPATCHED`/`ON_HOLD`, `PROPOSED`/`CONFIRMED` assignments → `RELEASED`, `REQUESTED`/`CONFIRMED` bookings → `CANCELLED`. No PRD silence.
- **Step 7 item 2 (`test_05_dispatch_gates.py` helper fixed to use the new fixture)** — The test asserts stage-6 terminal guard outranking stage-8 weather safety on dispatch of a cancelled job. The implementation (`implementation/routes_jobs.py:209` `_guard_terminal` before the weather check at line 214) matches PRD §2.8's numbered pipeline verbatim. No PRD silence.

Since no fix revealed any place where the implementation made a concrete behavioral choice the PRD leaves open, the minimal correct patch is the identity patch.

**Per-edit pre-edit search log:** No edits were committed. For completeness, the two candidate-edit subjects were investigated and rejected:

1. (a) Subject: job cancellation semantics (endpoint + cascades + error ordering). (b) Paths enumerated/read: `routes_jobs.py:267-289` (cancel endpoint), `calc.py:237-248` (`release_assignments_on_cancel`, `cancel_bookings_on_cancel`), `test_helpers/fixtures.py:164-166`, `test_helpers/api_client.py:69`. (c) No wording adjustment made — existing PRD §3.2 prose describes every enumerated path exactly, so any edit would risk creating a new mismatch rather than fixing one.
2. (a) Subject: validation-stage precedence between terminal-state guard (stage 6) and weather safety (stage 8) on dispatch. (b) Paths enumerated/read: `routes_jobs.py:205-232` (dispatch: `_guard_terminal` at line 209 precedes `any_active_restriction_overlaps` at line 214), `routes_jobs.py:35-37` (`_guard_terminal` definition), plus all other `_guard_terminal` callsites (lines 150, 188, 240, 256, 278) confirming uniform stage-6 placement across job transitions. (c) No wording adjustment made — PRD §2.8's fixed pipeline already pins this ordering universally; the test only confirmed it.

Output file: `workspace/PRD_FINALIZED.md` (exact copy of PRD.md).

## Step 9: Complete PRD — 2026-08-11T05:20:00.000Z

Done. `workspace/PRD_COMPLETED.md` is written as a minimal patch over `PRD_FINALIZED.md`.

**Size:** PRD_FINALIZED.md 299 lines / 46,498 bytes → PRD_COMPLETED.md 299 lines / 48,460 bytes (char delta +1,938 chars / +1,962 bytes; line count unchanged — all edits are inline, in-paragraph).

**Counts:** 18 ambiguity-pins, 3 mismatch-revisions (21 changes total, across 16 paragraphs).

**Changes:**
- §2.3 — insert — ambiguity — bad `limit`/`offset` (non-integer, out of range, negative offset) → `ERR_INVALID_REQUEST`; bad enum-typed filter value → `ERR_INVALID_ENUM`; equal creation timestamps ordered by creation sequence — implementation/util.py:245-279
- §2.4 — insert — ambiguity — clock may be set to any instant, earlier or later; no forward-only constraint — implementation/routes_clock.py:18-21
- §2.5 — revise — ambiguity — `version` starts at 1 on creation — implementation/db.py:44-51
- §2.6 — insert — ambiguity — absent/non-integer version field is request shape (`ERR_INVALID_REQUEST`, final stage), not a concurrency failure — implementation/util.py:233-240
- §2.7 — revise — mismatch — crew-rest arithmetic is exact elapsed seconds (86,400s day; 36,000s required rest), not "whole minutes" — implementation/calc.py:23-24, implementation/routes_watch.py:57-72
- §3.1 tugs — revise — ambiguity — horsepower is a positive integer; `insured_value_cents` may be zero but never negative — implementation/routes_refdata.py:33-36
- §3.1 vessels — insert — ambiguity — duplicate `imo_number` → `ERR_INVALID_REQUEST`; `deadweight_tonnage` is an integer — implementation/routes_refdata.py:82-88
- §3.1 pilots — insert — ambiguity — `active` flag is informational; booking creation never consults it — implementation/routes_pilotbookings.py:54-61
- §3.1 crew — revise — ambiguity — `max_watch_hours` is a positive integer, informational only, not enforced when watches are logged — implementation/routes_refdata.py:149
- §3.1 tariffs — insert — ambiguity — duplicate `tariff_code` → `ERR_INVALID_REQUEST` — implementation/routes_refdata.py:186-190
- §3.1 tariffs — revise — ambiguity — `base_fee_cents`/`standby_block_rate_cents` non-negative; `free_standby_minutes` non-negative integer; `standby_block_minutes` positive integer; `weather_surcharge_pct` non-negative — implementation/routes_refdata.py:179-183
- §3.1 tariffs — insert — ambiguity — `effective_to` preceding `effective_from` → `ERR_INVALID_REQUEST`; equal endpoints accepted as a single-instant window — implementation/routes_refdata.py:191-192
- §3.3 — insert — ambiguity — malformed assignment window (end not strictly after start) → `ERR_INVALID_REQUEST` — implementation/routes_assignments.py:77-79
- §3.3 — revise — mismatch — most-recent-inspection tie-break is creation order, not "later `created_at`" — implementation/calc.py:158-165
- §3.3 — insert — ambiguity — a never-inspected tug cannot be confirmed (`ERR_GEAR_INSPECTION_OVERDUE`) — implementation/routes_assignments.py:132-136
- §3.4 — insert — ambiguity — malformed booking window → `ERR_INVALID_REQUEST` — implementation/routes_pilotbookings.py:82-84
- §3.5 — insert — ambiguity — malformed watch span → `ERR_INVALID_REQUEST` — implementation/routes_watch.py:73-75
- §3.5 — revise — mismatch — "worked minutes" wording changed to exact worked time, companion to the §2.7 seconds pin — implementation/routes_watch.py:57-72
- §3.6 — insert — ambiguity — per-item "latest inspection" convention: latest by `inspected_at`, ties by creation order, never-inspected gear items do not block restoration — implementation/calc.py:147-155,168-173
- §3.8 — insert — ambiguity — ACTUAL-basis standby is elapsed whole minutes; partial minutes discarded — implementation/calc.py:57-59
- §3.8 — insert — ambiguity — `void_reason` is accepted but never stored, and the invoice representation never carries it — implementation/routes_billing.py:98, implementation/calc.py:437-449

Everything else in the implementation (all 45 endpoints' auth/role/ownership/existence/OCC/terminal/from-state/business/temporal/shape ordering per §2.8, both cascade families, both invoice bases with per-line half-up rounding, claim economics order, vessel balance formula and its four recompute triggers, all terminal-state sets, all list filters, envelope shapes) was verified to already be uniquely pinned by PRD prose; the 80/80-passing test suite was used only as a cross-reference, never as authority.
