# Worklog — task_1758_tv_station_traffic_ad_inventory_scheduling

## Step 1: Create Task Directory — 2026-08-14T00:00:00.000Z

Task directory `tasks/task_1758_tv_station_traffic_ad_inventory_scheduling/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline invoker. Step 1 treated as DONE; no index scan performed, no other task directory touched.

## Step 2: Generate Scaffold — 2026-08-14T14:57:00.000Z

All three artifacts are generated and validated. Summary:

## Scaffold generated for task_1758 (TV Station Traffic & Ad Inventory Scheduling)

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1758_tv_station_traffic_ad_inventory_scheduling/SCAFFOLD.yaml` — §1.0–§1.7 only
- `/home/ubuntu/github/CodingPRD/tasks/task_1758_tv_station_traffic_ad_inventory_scheduling/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`, 19 instances across all 9 rules (≥2 each)
- `/home/ubuntu/github/CodingPRD/tasks/task_1758_tv_station_traffic_ad_inventory_scheduling/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`, 40 instances (36 active + 4 `excluded_because` stubs)

**Design shape** (Advanced band, quota/allocation + ledger reconciliation archetypes):
- 10 entities: Advertiser, Program, AvailWeek, AvailUnit, Order, OrderLine, CopyInstruction, Spot (self-referential via make_good_of_spot_id), LogDay, AsRunEntry (append-only)
- 50 endpoints including the `_clock/set_current_utc` test-driving endpoint with the mandated `2026-08-01T00:00:00Z` startup default
- 5 state machines: cyclic Order revision loop (APPROVED→REVISED→SUBMITTED→APPROVED), cyclic Spot preemption/make-good loop, guarded transitions (placement gated by AvailWeek status; reconcile gated by LogDay status)
- 6 calculations, including dual-variant pairs on different entity domains (discrepancy_credit provisional-vs-final on Spot; audience_delivery_shortfall per-spot-strict vs week-averaged on OrderLine) and combinatorial modes (a) conditional spot_class branch in avail_headroom_check and (b) pinned per-line floor rounding in post_buy_credit_value (3332 vs 3333 cent divergence)
- Two OCC concurrency rules (order approve, spot place) with `expected_*_version` always referenced via `${var}` captures
- 15 error codes, all exercised by at least one design instance

**Key consistency fixes made during rule-replay:** added REVISED→CANCELLED transition, relaxed preempt precondition to "no FINALIZED/RECONCILED LogDay covers the date" (so preempt works when no log day exists), pinned gross_budget_cents formula as rate × spots/week × weeks, split same-category multi-spot setups across separate breaks where separation wasn't the intended blocker, and quoted YAML flow-mapping values containing `?`, `[`, `$` that broke parsing.

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (50 endpoints, 10 entities, 19 + 36 instances, 659 calls scanned)

## Step 3: Copy Shared Files — 2026-08-14T14:58:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1758_tv_station_traffic_ad_inventory_scheduling/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T15:15:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1758_tv_station_traffic_ad_inventory_scheduling/workspace/PRD.md` (279 lines). The withheld difficulty/corner index files were never opened or referenced.

**Document skeleton (domain-derived, not templated):**
- §1 Introduction — 2 paragraphs from the business-context angle (affiliate-station traffic operation, logical-clock determinism), with the `/traffic` mount declared here (outside §3, as permitted).
- §2 (10 subsections): RBAC with all five roles' `opaque` identity translated individually; §2.2 verbatim envelope block (verified byte-identical to the canonical source); pagination (limit 10/1/100, offset 0, `created_at` ascending); resource identity including the AsRunEntry `common_fields: false` exception (no `updated_at`/`version`, append-only); logical clock (startup default `2026-08-01T00:00:00Z`, `to_iso8601`/`current_utc`, completion sweep); booked-second counters and the one-way political reserve fence; precision rules (integer cents floor-once, 3-decimal spot deficits, rational rotation scores, inclusive capacity boundaries); the two OCC rules; left-to-right nested-path validation and hierarchy cascades; and a 15-step validation-pipeline precedence subsection rendering every `validations[].priority` in ordinal prose (including the late evaluation of `ERR_INVALID_REQUEST` and last-position OCC checks).
- §3 (8 subsections, timeline/lifecycle grouping): advertisers/credit, program grid + avail weeks/units, copy clearance, order pipeline (spawning, revision/cancel cascades, completion sweep), placement (headroom both branches, separation rule with `created_at` tie-break, OCC), preemption/make-good cycle (provisional credit, comparable-or-better rating rule, duplicate-offer guard), log finalize + weighted round-robin rotation, reconcile + tiered discrepancy credit + both audience-shortfall variants + post-buy waterfall.
- §4: 50-endpoint table, 4 columns only. §5: 15-error table, 2 columns only. File ends at §5 with no audit footer.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 46 required, 46 present, 0 missing
- endpoints[].request_body/query_params: 7 required, 7 present, 0 missing
  (one omission, order_line_id, found on first pass and repaired; second pass clean)
- enum/state values: 44 required, 44 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 15 checked, 15 expressed in ordered §2.10 prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write op + expected_<parent>_version + exact error_id/412), 0 missing
- state_machines[].transitions: 22 checked, 22 fully expressed (preconditions + error pairing + side effects incl. cascades), 0 missing
- calculations[]: 6 checked, 6 fully expressed in precise reconstruction-safe prose (constants 25%/0%/1000/1 embedded), 0 missing
- validations[] conditions: 15 checked, 15 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed in workflow narrative, 0 missing
- entities[].fields[] structured content (defaults, constraints, nullability): reconstructible from prose, 0 missing
- sibling-branch symmetry: 7 groups checked (4 cancel transitions, 2 submit transitions, 2 expire transitions, headroom branches, credit tiers, shortfall variants, post-buy variants), all equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 313
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Notable fidelity decision: the scaffold's `booked_*_seconds` field descriptions mention "SCHEDULED or PREEMPTED" states, but every operative rule (preemption "frees seconds," decrement side effects, endpoint descriptions) treats the counters as live held-seconds that decrement on preemption/cancel. I rendered the operative side-effect semantics ("currently held," maintained by placement/preemption side effects) rather than transcribing the contradictory state-filter phrasing, since the PRD must be internally consistent and the hidden tests assert behavior.

## Step 5: Generate Unit Tests — 2026-08-14T15:50:00.000Z

Complete. Both stages are generated and all audits pass.

## Deliverables

**`test_helpers/`** (9 files) under `/home/ubuntu/github/CodingPRD/tasks/task_1758_tv_station_traffic_ad_inventory_scheduling/`:
- `types.py` — 10 status/role enums + TypedDicts; `AsRunEntry` correctly omits `updated_at`/`version` (append-only per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (advertisers, programs, avail weeks/units, orders, lines, copy, spots, log days, post-buy, clock)
- `api_errors.py` — all 15 error IDs with HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions, post-buy bucket-sum invariant, week booked-seconds invariant
- `factories.py`, `constants.py` (penalty tiers, spot lengths, clock default, Monday-anchored week dates), `test_users.py` (5 opaque roles + `NO_AUTH_HEADERS`)
- `fixtures.py` — tiered builders plus `setup_scheduled_scenario` (advertiser→program→week→units→approved order→copy→placements→optional log/finalize), `setup_second_advertiser_order`, `setup_preempted_spot`

**`test_suite/`** — conftest + 8 concern-grouped files, **74 tests**.

## Audit results
- **Design tags**: all 55 non-stub instances covered (18 difficulty × ≥2 tests, 37 corner × ≥1); all 4 corner `excluded_because` stubs verified to resolve to real difficulty instances and left untranslated; zero untagged/dual-tagged/unknown-tag tests
- **PRD citations**: 116 quoted sentences across all docstrings survive whitespace-normalized literal grep of PRD.md
- **Hygiene**: no `skip`/`skipif`/`xfail`, no scaffold references in comments, clean `py_compile` and `pytest --collect-only` (74 tests)

## Two judgment calls worth noting
1. **`occ_stale_avail_version_on_place`** — the design's literal setup (two spots from one AUTOMOTIVE advertiser) would trip commercial separation (pipeline priority 9) before the OCC check (priority 15), contradicting its own asserted `ERR_STALE_AVAIL_VERSION`. I kept the instance's assertion but rebuilt the setup with two different-category advertisers, so the request is otherwise valid and the PRD (§2.8 + §2.10 "a stale version surfaces only on an otherwise-valid request") uniquely derives the 412.
2. **`advertiser_creation_defaults_and_stored_fields`** — dropped the recipe's `version == 1` assertion (PRD §2.4 says version increments per mutation but never pins the initial value, so it's not two-reader derivable); the test retains the verbatim-covered claims (`agency_name` defaulting to `""`, GET echo of stored fields).

## Step 6: Generate Implementation — 2026-08-14T15:58:30.000Z

Done. The complete implementation is in place and passing the full benchmark suite.

## What was built

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_1758_tv_station_traffic_ad_inventory_scheduling/workspace/implementation/`

Python + Flask, in-memory store (empty on every boot, no seeding), all 50 endpoints from the scaffold endpoint table:

- **`start.sh`** — executable; guarded dependency install (`if ! python3 -c "import flask"` so per-test reboots skip pip); `exec python3 app.py` in foreground, `0.0.0.0:$PORT` (default 10000)
- **`app.py`** — Flask app, envelope-shaped error handlers (404/405/500 included), and a global-lock WSGI middleware serializing requests so OCC races resolve cleanly
- **`store.py`** — empty entity tables, logical clock pinned at `2026-08-01T00:00:00Z`, monotonic `_seq` for the PRD's creation-order tie-breaks
- **`helpers.py`** — 15-error catalog with exact HTTP statuses, `meta`/`response_type`/`data` envelope, `limit`/`offset`/`total_count`/`has_more` pagination (default 10/0, clamp 1–100), `X-User-ID`/`X-User-Role` auth for the 5 roles, strict field validators
- **`serializers.py`** — exact field names per scaffold §1.1; AsRunEntry carries only `id`/`created_at` (append-only, no `updated_at`/`version`)
- **`domain.py`** — budget recompute, spot spawning, revise/cancel teardown with finalized-log protection, headroom check (both class branches, inclusive boundaries, `ERR_POLITICAL_RESERVE` vs `ERR_AVAIL_OVERFLOW` classification), separation check (occupants by `created_at`, candidate appended last), rational-compared copy rotation, discrepancy credits (early 0% / late 25% tiers, multiply-then-floor), per-spot-strict and week-averaged shortfall, post-buy waterfall with per-line floor
- **`routes_core.py` / `routes_orders.py` / `routes_spots.py` / `routes_logs.py`** — all endpoints with the PRD §2.10 15-step validation pipeline order (auth → role → existence → state → date-window → reference → political → capacity → separation → copy → reconcile → credit → field sanity → OCC last)

## Verification

- Two full `prd-bench-local-run --isolation per-test-server` runs: **74/74 passed both rounds** (~100s each; server re-booted via `bash start.sh` before every test, so fresh-process boot is verified 148 times)
- Plus ~130 ad-hoc smoke assertions covering priority-order interleavings (existence vs window, credit vs OCC), rotation weights, both post-buy variants, per-line floor divergence (3332), clock-driven completion sweep semantics (strictly-before flight end)

## Key finding during testing

The one initial failure pinned an ambiguity in PRD §3.7: `times_used` for copy rotation is a **snapshot taken at finalize-run start** — assignments made during the same run do not affect scoring, so multiple spots in one run can receive the same copy; prior runs' assignments count normally. Fixed by snapshotting usage counts before the assignment loop (`usage_snapshot()` in `domain.py`).

## Step 7: Run Tests and Iterate — 2026-08-14T16:05:00.000Z

All 8 parallel rounds pass cleanly — 74/74 tests in every round, with zero failures, zero errors, and zero skips. No flakiness surfaced across the concurrent sweep (each round ~123s wall time under per-test-server isolation, 8 rounds running concurrently against isolated ports).

**Summary**

- Iterations run: 1 (single 8-round parallel stability sweep, all rounds green on first pass)
- Tests deleted: none — no failing tests, so no PRD-coverage/unique-derivability deletions were triggered
- Fixes applied to `test_helpers/`: none
- Fixes applied to `implementation/`: none

The existing implementation in `/home/ubuntu/github/CodingPRD/tasks/task_1758_tv_station_traffic_ad_inventory_scheduling/workspace/implementation/` (Flask app with routes split across `routes_core.py`, `routes_orders.py`, `routes_spots.py`, `routes_logs.py`, in-memory store in `store.py`) already satisfies all 74 tests in the suite stably. The `start.sh` conditional-pip-install guard (skip install when flask is already importable) is doing its job of avoiding boot-time contention during the 8-way concurrent per-test restarts — no "could not be restarted" timeouts occurred in any round.

## Step 8: Finalize PRD — SKIPPED — 2026-08-14T16:05:30.000Z

Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. Per the skip condition, `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` was produced. (Note: the single ambiguity resolved during Step 6 generation — copy-rotation `times_used` as a finalize-run-start snapshot — is in scope for Step 9's full PRD-vs-implementation completeness scan.)

## Step 9: Complete PRD — 2026-08-14T16:20:00.000Z

The patch is complete and verified. Final summary:

## Result

**Source**: `PRD.md` (Step 8 was skipped; no `PRD_FINALIZED.md`) → `/home/ubuntu/github/CodingPRD/tasks/task_1758_tv_station_traffic_ad_inventory_scheduling/workspace/PRD_COMPLETED.md`
**Size**: 279 → 279 lines (all edits inline, no new sections); 47,261 → 50,369 chars (+3,108).
**Counts**: 12 ambiguity-pins, 0 mismatch-revisions. Every impl behavior traced to PRD prose either matched an existing pin or was covered by one of the 12 edits below; no impl behavior contradicted PRD prose outright.

- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped into [1,100]/[0,∞) and unparsable values fall back to defaults, never rejected — implementation/helpers.py:287-302
- §2.3 — insert — ambiguity — uniform filter convention: every list endpoint over a status-bearing resource accepts an optional `status` filter (covers program order-lines, avail-unit spots, copy spots, make-goods); flat order list also takes `advertiser_id`; non-integer integer-filter values yield `ERR_INVALID_REQUEST` — implementation/routes_core.py, routes_orders.py:88-98, helpers.py:315-322
- §2.4 — revise — ambiguity — `version` starts at 1 on creation, not merely "increments" — implementation/helpers.py:259-267
- §2.5 — insert — ambiguity — all server-generated timestamps (envelope `api_request_timestamp`, `created_at`, `updated_at`) read the logical clock; clock setter accepts any parseable ISO 8601 (offsets converted to UTC, naive read as UTC, no monotonicity guard — backward sets accepted); `current_utc` renders whole-second without fractional part, else 3 digits; completion sweep runs on every set — implementation/helpers.py:57-67, 229-241, routes_logs.py:221-231
- §2.5 — revise — ambiguity — `week_start_date` weekday is not verified; any ISO date opens a week spanning the supplied date plus six days — implementation/routes_core.py:200-208 (no Monday check)
- §2.7 — revise — ambiguity — 3-decimal deficit quantization is rounded half up — implementation/domain.py:324-326 (`ROUND_HALF_UP`)
- §3.4 — revise — ambiguity — single-line cancel additionally requires the line itself to be `ACTIVE`; re-cancelling a `CANCELLED` line yields `ERR_INVALID_STATE` — implementation/routes_orders.py:169-180
- §3.6 — insert — ambiguity — offering a make-good touches the originating preempted spot (version advances, `updated_at` refreshes, no field change) — implementation/routes_spots.py:230 (`touch(spot)`)
- §3.7 — revise — ambiguity — error partition pinned: `ERR_COPY_NOT_RECEIVED` only when the advertiser holds no `RECEIVED` copy at all; `RECEIVED` copy existing in wrong lengths only yields `ERR_REFERENCE_MISMATCH` — implementation/routes_logs.py:62-85
- §3.7 — revise — ambiguity — **the reported lead, confirmed**: the old prose ("spots ... created before the current finalize run began") admitted live-counting, since same-run copy assignments attach to pre-existing spots; pinned the snapshot reading — counts frozen at finalize-run start, same-run assignments don't affect later spots in that run, prior runs count normally — implementation/domain.py:291-295 (`usage_snapshot`), used at routes_logs.py:89
- §3.8 — insert — ambiguity — `actual_rating` on a not-aired entry is accepted, held to the same non-negative rule, and stored — implementation/routes_logs.py:144-164, 169-178
- §3.8 — insert — ambiguity — week-averaged weekly deficit is likewise kept to three decimals, rounded half up — implementation/domain.py:341-361
- §3.8 — revise — ambiguity — `method_variant` accepted values pinned (`per_spot_strict` default when omitted/empty, `week_averaged`; else `ERR_INVALID_REQUEST`) and full report shape pinned: echoes `method_variant`; `lines` covers every line of the order regardless of status in creation order, each carrying `order_line_id`, `status`, `guaranteed_rating`, `aired_spot_count`, `average_actual_rating` (3-decimal mean, null when none aired), `post_buy_deficit_points`, `adu_owed`, `cpp_cents` (null when guarantee is 0), `shortfall_credit_cents` — implementation/routes_orders.py:319-329, domain.py:364-427

Deliberately not pinned (out of declared API surface or unobservable): Flask 404/405 fallback to `ERR_INVALID_REQUEST` for undeclared paths (app.py:47-53), the 500 `ERR_INTERNAL` handler, internal `_seq` tie-break mechanics (already covered by PRD's "creation order" phrasing), and per-spot single-entry reality behind `_latest_entry_by_spot` (a spot can only be reconciled once).
