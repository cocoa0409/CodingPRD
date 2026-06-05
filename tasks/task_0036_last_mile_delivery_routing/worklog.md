# Worklog — task_0036_last_mile_delivery_routing

## Step 1: Create task directory — 2026-05-28T18:51:06Z

Created `tasks/task_0036_last_mile_delivery_routing/` with `workspace/` subdirectory (pre-allocated ID, no auto-scan).

## Step 2: Generate scaffold — 2026-05-28T19:07:15Z

Generated a complete scaffold package for **task_0036_last_mile_delivery_routing** (Last-Mile Delivery Route Optimization, UPS/FedEx style). All three files written and `scaffold_lint.py` reports **VERDICT: clean lint** (439 calls scanned, all FKs reverse-reachable).

**Complexity profile:** primary archetype `temporal_windowing` + secondary `workflow_orchestration`; flat topology; branching/cyclic state shape; peer-role model; layers = cascading side effects, dual-variant calc, rate/threshold triggers, optimistic concurrency. Advanced difficulty band.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **7 entities** — TransitCenter, Driver, Parcel, DeliveryRoute, DeliveryStop, DeliveryAttempt (append-only, `common_fields:false`), Appointment. All FKs use the canonical `FK -> X.id` prefix.
- **4 state machines** — Parcel (RECEIVED→SORTED→ROUTED→{DELIVERED|RETURNED}, branch), DeliveryRoute (PLANNING→DISPATCHED→COMPLETED / cancel cascade), DeliveryStop (PENDING→OUT_FOR_DELIVERY→ATTEMPTED with a redelivery cycle and an ATTEMPTED→{REDELIVERY_SCHEDULED|FAILED} branch), Appointment (REQUESTED→{APPLIED|REJECTED}).
- **6 calculations** — route_load_metrics (planned vs committed weight, dual-variant), service_failure_score (driver risk accumulator with floor), redelivery_surcharge (tiered + escalation + signature + hazmat multiplier, multiply-then-round pinned, cumulative-vs-latest dual-variant), sort_handling_fee (round-per-line-then-sum pinned), center_sorted_count, stop_attempt_count.
- **16 validations** (priority-ordered, auth→existence→input→state→safety→temporal→constraint→fiscal→OCC).
- **33 endpoints**, including reverse-reachability GETs for every FK, a computed `/manifest` read, and an OCC-guarded dispatch.
- **35 errors**; **1 concurrency rule** (`route-dispatch-stale-version`, OCC on `DeliveryRoute.version`, 412).
- **4 roles** — DispatchManager, SortAssociate, CustomerServiceAgent (opaque), Driver (`entity_backed:Driver`).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** all 9 Difficulty Rules × 2 = **18 instances**, executable setup/trigger chains with literal-computed asserts.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **43 active instances + 4 stubs** across all 9 sections; all 65 instance names unique.

## Step 3: Copy shared files — 2026-05-28T19:07:15Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-28T19:12:25Z

Generated `workspace/PRD.md` — a 257-line PRD for the Last-Mile Delivery Routing API.

**Structure:** §1 Introduction; §2 Global Specs (9 subsections: RBAC, response envelope, pagination, common props, cascades, nested ref validation, monetary rounding, OCC at dispatch, validation ordering); §3 Business Logic (8 subsections, lifecycle-by-entity); §4 Endpoint table (33 endpoints); §5 Error catalogue (35 errors).

**Hard Contracts all PASS:** Contract 1 (44 field names in backticks), Contract 2 (35 error IDs + 4 state machines + 6 calcs + 16 validations + OCC + cascades; fixed missing ERR_STOP_NOT_CANCELLABLE / PENDING→CANCELLED), Contract 3 (§3 path purity, zero HTTP/URL tokens).

**Notable:** both fee calcs spell out pinned rounding order (surcharge multiply-then-round; manifest round-per-line-then-sum); reschedule-index = attempt_count−1 in prose; planned vs committed weight differentiated by status-inclusion sets; appointment 30-min buffered overlap vs dispatch exact-date double-booking contrasted; constants embedded; DeliveryAttempt append-only (no updated_at/version).

## Step 5: Generate unit tests — 2026-05-28T19:27:44Z

Generated complete test infrastructure. **test_helpers/** (9 files) + **test_suite/** (conftest + 8 test files): **79 tests, 79 Design tags, one per test.**
- Queue A (Difficulty): 36 tests covering all 18/18 instances (≥2 each).
- Queue B (Corner): 43 tests covering all 43 non-stub instances (≥1 each).
- Skipped: none beyond the 4 mandated `excluded_because:` stubs.
- Verified: all compile; one Design tag/test resolving to real instance; citation substrings grep-confirmed in PRD; no skip/xfail. Runtime not executed (runner installs framework at test time).

## Step 6: Generate implementation — 2026-05-28T19:27:44Z

Built complete Python + Flask in-memory REST API at `workspace/implementation/` (17 files).
- start.sh installs requirements + `exec python3 app.py` (foreground, $PORT default 10000, binds 0.0.0.0).
- 33 endpoints matching PRD §4 exactly; in-memory dicts, starts empty, no seeding.
- Validation order: auth → role → existence(404) → type/range → uniqueness → state → domain; dispatch OCC checked last (412 ERR_STALE_ROUTE_VERSION).
- Money: Decimal ROUND_HALF_UP; redelivery surcharge cumulative multiply-then-round; manifest round-per-line-then-sum.
- Cascades bump version+updated_at per touched resource.
- Verified end-to-end smoke (happy path, OCC, signature/driver-release, appointment 30-min buffer, double-booking, max-attempts FAILED branch, cumulative fees, failure-score).

## Step 7: Test and fix loop — 2026-05-28T19:52:54Z

All 8 parallel rounds pass cleanly: 79/79 each, zero failures and zero errors. Loop complete.

**Iterations run:** 3 (baseline sweep + 2 fix-and-resweep cycles).

**Tests deleted:** None. Every failure traced to a fixture/harness bug, not a PRD-silence or non-uniqueness problem.

**Fixes applied to test_helpers/:**
- `test_helpers/fixtures.py` — added missing `cancel_route(route_id)` helper (calls `api_client.cancel_route` with DispatchManager headers via `get_success_data`). Two tests (`test_route_cancel_restores_parcel_sorted_at_center_id`, `test_center_sorted_count_conserved_across_route_and_cancel`) referenced `fx.cancel_route(...)`, which did not exist (`AttributeError`). The `cancel_route` endpoint and its DispatchManager-owned cascade are PRD §3.3, so the helper is PRD-faithful; missing-fixture test bug, not an implementation gap.

**Fixes applied to implementation/:**
- `workspace/implementation/start.sh` — guarded the dependency install with `python3 -c "import flask" 2>/dev/null || pip install ...` so `pip install` only runs on cold boot, not every per-test-server restart. The unconditional `pip install -q` slowed restarts enough that `test_driver_dispatched_on_distinct_dates_allowed` intermittently exceeded the restart window. No application logic/endpoints changed; state still wiped on every restart (in-memory only).

Final state: 79/79 passing across all 8 concurrent rounds.

## Step 8: Finalize PRD — 2026-05-28T19:54:07Z

**Outcome: PRD_FINALIZED.md is a verbatim copy of PRD.md — no edits.** (257 lines → 257 lines, 0% delta.)

Per-item analysis of step_7_diff:
- `cancel_route` helper addition: subject = route-cancel cascade (PRD §3.3 line 141). Enumerated impl paths (delivery_routes.py:171-201, calc.py recompute helpers) all fully determined by PRD line 141. Missing-fixture test bug, not PRD silence.
- `start.sh` pip-install guard: pure boot-performance; no app logic/endpoints/state semantics changed. PRD specifies no boot behavior. Not PRD silence/mismatch.

Both Step 7 fixes were exactly as anticipated (fixture addition + boot guard), neither revealing PRD silence or mismatch → verbatim copy is the valid result.

## Step 9: Complete PRD — 2026-05-28T19:56:59Z

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-implementation scan.

**Line counts:** PRD_FINALIZED.md 257 lines / 35,977 chars → PRD_COMPLETED.md 257 lines / 36,507 chars (+530 chars, 0 line delta — all in-paragraph).

**Counts:** 3 ambiguity-pins, 1 mismatch-revision.

- §4 Endpoint Definitions — insert — ambiguity — POST attempts returns HTTP 201 (creates stand-alone DeliveryAttempt) — routes/stops.py:192
- §2.3 Pagination — insert — ambiguity — list ordering breaks created_at ties by id ascending — routes/*.py
- §2.4 Common Resource Properties — insert — ambiguity — version initial value = 1 — routes/transit_centers.py:31 (+ all create handlers)
- §3.3 Building a Route — revise — mismatch — service_date validated only as non-empty string; compared as opaque exact-equality string at dispatch — delivery_routes.py:25, :135

Behaviors confirmed already pinned (no change): dispatch validation ordering, surcharge multiply-then-round, manifest round-per-line-then-sum, failure-score zero floor, weight view status sets, 30-min buffered appointment conflict, expected_route_version type validation, all response field shapes.

## Pipeline complete — 2026-05-28T19:56:59Z

Final verification: all 8 stability rounds report **79/79 passing**. All deliverables present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/, test_suite/, workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}.
