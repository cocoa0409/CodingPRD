# Worklog — task_1300_retail_store_fixture_manufacturing_rollout

## Step 1: Create Task Directory — 2026-08-12T19:24:00.000Z

Task directory `tasks/task_1300_retail_store_fixture_manufacturing_rollout/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher. Step 1 treated as DONE per invocation instructions; no index scan performed, no other task directory touched.

## Step 2: Generate Scaffold — 2026-08-12T20:15:00.000Z

All three scaffold artifacts are generated and lint-clean. Final report:

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1300_retail_store_fixture_manufacturing_rollout/SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1300_retail_store_fixture_manufacturing_rollout/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`, 9 rules × 2 instances = 18
- `/home/ubuntu/github/CodingPRD/tasks/task_1300_retail_store_fixture_manufacturing_rollout/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`, 43 instances (38 full recipes + 5 `excluded_because:` stubs) across all 9 claim-extraction-guide sections

## Lint verdict (verbatim)

```
Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     9
  §1.8 instances scanned:     18
  §1.9 instances scanned:     43
  Calls scanned (§1.8+§1.9):  679

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Design summary

- **Complexity profile**: workflow_orchestration + quota_allocation; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; flat topology (all peer entities, canonical `FK -> X.id` references, filtered-list reverse GETs); cyclic state-machine shape; approval_chain roles (9 opaque roles incl. segregation-of-duties rules on prototype approval and photo signoff).
- **Entities (9)**: RolloutProgram, FixturePrototype (VE cycle), StoreKitConfig, ProductionWave, StagingReservation, InstallDelivery, DamageClaim, InstallSignoff (reject→resubmit cycle), AtticStockLedger (auto-created by the signoff-approval cascade).
- **Difficulty rule grounding**: dual variants on prototype cost (provisional 55000 vs engineered 47000) and attic valuation (12720 vs 10000); combinatorial formulas in mode (a) tiered+rush wave release charge (9000/3450/2531 literal-asserted) and mode (b) per-line-then-sum rounding (3287 vs the forbidden 3286); depth-4 signoff-approval cascade and depth-3 claim-approval cascade; state-vs-fiscal and safety-vs-fiscal priority conflicts; exact-fit wave capacity and reorder-point equality boundaries; half-open bay overlap vs aggregate crew-day capacity; freeze/cancel budget conservation and schedule/fail crew-hours conservation.
- **Testability**: logical-clock test-driving endpoint `POST /_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z` (auto-starts waves, auto-expires reservations); two OCC concurrency rules (`expected_config_version`, `expected_ledger_version`) both exercised with `${var}`-captured versions.
- **No sibling tasks were consulted**; design derived solely from the scenario text and the skill specification.

One issue caught and fixed in self-audit: the closeout reconciliation literal in `closed_program_terminal_lockdown` was recomputed by executing the pinned formula (2000000 − 318000 − 15000 + 795 = **1667795**) and corrected; also added `POST /production-waves/{id}/cancel` so the CANCELLED enum value is reachable (enum-value closure).

## Step 3: Copy Shared Files — 2026-08-12T20:16:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1300_retail_store_fixture_manufacturing_rollout/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-12T20:24:00.000Z

All checks pass. The "about" hit is ordinary prose ("learns about the most fundamental problem first"), not a fuzzy numeric approximation, so the precision rule is intact.

## Task Complete

Generated `/home/ubuntu/github/CodingPRD/tasks/task_1300_retail_store_fixture_manufacturing_rollout/workspace/PRD.md` (~11 KB of prose) from the task 1300 scaffold, per the prd-bench-doc-generator specification. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened or referenced in any way.

**Document structure** (skeleton designed fresh for this domain):
- §1 Introduction — 2 paragraphs, business-context angle (fixture manufacturer / rollout calendar)
- §2 Global Specifications — 10 subsections: RBAC (all 9 roles named, opaque-identity prose per role), verbatim §2.2 response envelope, pagination + list filters, common resource properties, monetary precision (integer cents, round-half-up, pinned per-line-then-sum), OCC, the nine-tier validation precedence, the logical clock (startup default 2026-08-01T00:00:00Z, clock-driven `COMMITTED → IN_PRODUCTION` and `HELD → EXPIRED`), program fiscal aggregates, and the cross-entity cascade catalog
- §3 Business Logic — 8 subsections organized by lifecycle timeline (program setup → prototype/VE loop → kit config & budget commitment → waves & release charging → staging & delivery → hotline claims → signoff cascade → attic stock & closeout), with all constants embedded in narrative (6% handling, 150-cent base rate, 70/90 tier boundaries, 1.25 rush, 8-hour crew day, 5% attic stock, 2,500-cent liquidation rate, 80/5/0 recovery rates)
- §4 Endpoint table — 52 rows, 4 columns only
- §5 Error catalogue — 41 rows, 2 columns only

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + endpoint inputs + query params: 69 required, 69 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 9 checked, 9 expressed as explicit ordered precedence in §2.7, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_config_version / expected_ledger_version + ERR_STALE_VERSION 412 all named; non-listed endpoints explicitly excluded), 0 missing
- state_machines[].transitions: 34 checked (incl. system/clock transitions and sibling branches), 34 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed in reconstructible prose (boundary inclusivity and rounding order stated), 0 missing
- validations[] conditions: 41 error IDs checked, all 41 matchable to triggers in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 52 checked, 52 expressed (multi-hop cascades enumerated per hop), 0 missing
- entities[].fields[] structured content: defaults, null-until semantics, and computed-field derivations all reconstructible, 0 missing
- sibling-branch symmetry: 7 groups checked (cancel DRAFT/FROZEN, complete COMMITTED/IN_PRODUCTION, fail SCHEDULED/DISPATCHED, dispose ACTIVE/DEPLETED, prototype approve from both review states, submit/resubmit, both valuation and cost variants), all with equal prose density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 422
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 matches the fixed verbatim block byte-for-byte (verified against `section-2.2-response-structure.md`); no operator-syntax (`>=`, `==`, `+=`, `Σ`) leaks in prose; no fuzzy/approximating words; all state and enum values (`DRAFT`…`CLOSED`, `NORMAL`/`AT_RISK`, `PROGRAM_AVERAGE`/`LIQUIDATION`, `RETURN_VENDOR`/`SCRAP`/`DONATE`, `DAMAGED`/`MISSING`) present as exact strings.

## Step 6: Generate Implementation — 2026-08-12T20:33:00.000Z

Implementation complete. Here is a summary of what was generated.

## Files Created

**Layout** (under `/home/ubuntu/github/CodingPRD/tasks/task_1300_retail_store_fixture_manufacturing_rollout/workspace/implementation/`):

- `start.sh` — executable launcher; guards `pip install` behind `python3 -c "import flask"`, then `exec python3 app.py` (binds `0.0.0.0:$PORT`, default 10000).
- `requirements.txt` — Flask.
- `app.py` — Flask app factory, blueprint registration, `ApiError` handler producing the error envelope, 404/405/500 fallbacks.
- `db.py` — in-memory stores (empty at boot, no seeding), logical clock (defaults to `2026-08-01T00:00:00Z`), `stamp_new`/`touch` helpers (UUID id, ISO-8601 ms timestamps, version bump).
- `errors.py` — `ApiError` class + full error catalog with HTTP statuses matching PRD §5.
- `response.py` — envelope helpers producing `{meta:{api_request_id, api_request_timestamp[, limit, offset, total_count, has_more]}, response_type, data}`.
- `middleware.py` — `require_roles` decorator: validates `X-User-ID`/`X-User-Role` headers (400 if missing/empty), then role membership (403); special "Any" allows any of the nine recognized roles.
- `util.py` — pagination (`limit`/`offset`, default 10, min 1, max 100), body validation, ISO date/datetime parsing, `Decimal` `ROUND_HALF_UP` helpers, filter/sort utilities.
- `services/calculations.py` — per-line-then-sum rounding for prototype cost and kit totals (HANDLING_PCT 0.06); tiered wave release charge (BASE 150, tiers 1.0/1.15/1.35, rush 1.25 for IN_PRODUCTION); wave utilization (1 dp, ≥90.0 → AT_RISK); half-open staging overlap; crew daily capacity (8 h aggregate); attic valuation (PROGRAM_AVERAGE / LIQUIDATION @ 2500¢, rates 0.80/0.05/0.00); reorder flag (inclusive ≤).
- `services/serializers.py` — strips underscore-prefixed internal fields.
- `routes/` — one module per resource: `programs`, `prototypes`, `kits`, `waves`, `reservations`, `deliveries`, `claims`, `signoffs`, `ledgers`, `clock`.

## Key Behaviors Implemented

- **Validation precedence** per PRD §2.7: auth (400) → role (403) → path existence (404, left-to-right) → body-FK existence → state (409) → segregation/recall (403/422) → shape (400/422) → temporal conflicts (409) → fiscal (402/409).
- **OCC** on `PATCH /store-kit-configs/{id}` (`expected_config_version`) and `POST /attic-stock-ledgers/{id}/adjust` (`expected_ledger_version`); stale → 412 ERR_STALE_VERSION.
- **Cascades** with per-hop `updated_at`/`version` bumps: freeze debits budget and locks prototype on first freeze; release computes charge, debits program, bumps wave committed/units + utilization; claim approve adds contingency spend and wave load (can exceed capacity); signoff approve completes delivery → fulfills kit → increments program count → creates attic ledger; dispose adds recovery.
- **Logical clock** POST `/_clock/set_current_utc` (PlatformAdmin): advances clock, fires COMMITTED→IN_PRODUCTION when start_date reached and HELD→EXPIRED when end_ts reached/passed.
- **Auto-oscillation** of attic ledger ACTIVE↔DEPLETED at quantity 0 on adjust.
- **Self-approval guards** on prototype approve (vs `submitted_by_user_id`) and signoff approve.
- **Fresh-boot determinism**: stores initialize empty, logical clock fixed at `2026-08-01T00:00:00Z` before any clock call — safe for `prd-bench-local-run --isolation per-test-server`.

## Verified via Smoke Tests

End-to-end workflow: program create/activate → prototype submit/approve → kit create/freeze (prototype auto-LOCKED) → wave commit → kit release (charge 1875 with rush multiplier verified) → staging reservation → delivery (reservation auto-CONSUMED) → claim approve (contingency debited) → signoff approve (kit FULFILLED, ledger auto-created with qty=ceil(2×0.05)=1, unit_cost=5300) → initiate-closeout → dispose (recovery 4240 = 1×5300×0.80) → finalize-closeout (final_reconciliation = 99,990,840 as expected). Error paths verified: missing auth header (400), wrong role (403), not found (404), self-approval (403), stale OCC version (412).

## Step 5: Generate Unit Tests — 2026-08-12T21:00:00.000Z

All checks pass. Generation is complete.

## Report

**Generated for task_1300_retail_store_fixture_manufacturing_rollout:**

**`test_helpers/`** (9 files):
- `types.py` — 9 entity TypedDicts (all carry id/created_at/updated_at/version per PRD §2.4), 12 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with 46 endpoint methods (all PRD §4 endpoints + `/_clock/set_current_utc`)
- `api_errors.py` — 41 `ApiErrorId` values with the PRD §5 HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` validators
- `factories.py` — 8 payload factories (optional fields omitted when not supplied, so PRD defaults are exercised)
- `constants.py` — PRD-stated thresholds (1.06 handling, 150-cent base rate, 1.25 rush, 90.0% posture boundary, 8-hour crew day, 5% attic seeding, 2500 liquidation rate, recovery rates)
- `test_users.py` — all 9 roles (all opaque per PRD §2.1) as shared constants plus `make_*_headers` builders for segregation-of-duties tests
- `fixtures.py` — composite chains: active program, approved prototype (submitter "eng-1" / approver "pm-1" to satisfy SoD), frozen/released kits, delivered deliveries, submitted signoffs, `setup_fulfilled_scenario` (full cascade + ledger fetch), `setup_closeout_pending_scenario`, clock advance

**`test_suite/`** — 79 tests across 7 files (conftest + test_01…test_07), all collected cleanly by pytest:
- Queue A: all **18/18 difficulty instances covered with exactly 2 tests each** (36 tests)
- Queue B: all **43/43 non-stub corner instances covered with ≥1 test** (43 tests)
- The 7 `excluded_because:` stubs were not translated; all their `difficulty_instance` cross-references resolve to real §1.8 instances

**Audit results (scripted):** every test has exactly one `Design:` tag resolving to a real instance; all 104 PRD docstring citations survive normalized literal match against PRD.md; no `skip`/`xfail`; no "scaffold" references in generated code.

**Notable decisions:**
1. **Data-typo reconciliation in `dual_variant_calc/attic_valuation_program_average_vs_liquidation`:** the recipe's setup payload said `unit_cost_cents: 1000` but its own asserts and `distinguishing_aspect` require a kit-derived unit cost of 3180 (recovery 12720 = 5×3180×0.8). I used `unit_cost_cents: 3000` (100×3000×1.06=318000 → /100 = 3180), making setup and asserts self-consistent; all literal asserted values were kept verbatim.
2. **Version assertions:** the PRD says version "increments by one on every mutation" but never pins the initial value, so `version_increments_on_mutation` asserts the captured-base increment (`v+1`) rather than hard-coding `== 1`, which a 0-start PRD-faithful implementation would otherwise fail.
3. **`clock_endpoint_default_and_shape`:** the startup-default line (2026-08-01T00:00:00Z) is not observable through the API (no clock GET; transitions fire only on advance), so the test asserts the PRD-derivable behavior — 200 response echoing `current_utc` — and leaves the default unasserted.
4. **Arithmetic bug caught in self-review:** the tiered-rush budget-conservation assert initially read 1,890,419; re-derivation gives 2,000,000 − 95,400 − 14,981 = **1,889,619** (fixed).

## Step 7: Run Tests and Iterate — 2026-08-12T21:55:00.000Z

The iteration loop was owned and driven in-session: 8-round parallel sweep (`prd-bench-local-run --isolation per-test-server`, `results.{1..8}.json`), union of failures across rounds, diagnose, fix, rerun. Iterations: 6 sweeps total (1 baseline + 4 instrumented/diagnostic + 2 final clean).

**Sweep 1 (baseline):** 77-79/79 per round; union of 5 distinct failing tests across rounds — every failure was one of two harness/timing signatures, zero assertion failures:
- `error` at ~15.2s: "API server ... could not be restarted" (the pytest plugin's 30x(0.5s+0.4s) restart-readiness poll exhausted).
- `failed` at ~1.2s: `RemoteDisconnected` / `ConnectionResetError 104` mid-test.

**Diagnosis (instrumented, 3 sweeps with per-boot tracing + wall-clock timestamps in start.sh/app.py, all reverted after):**
- The ECONNRESET class: the framework's session-scoped `requests.Session` (`GenericApiClient`) pools keep-alive connections; after the per-test `kill -9` + respawn, a pooled dead socket surfaces as connection reset on the next POST (urllib3 does not retry POST). Fixed once by `Connection: close`, then superseded by the pool-reset fix below.
- The restart-timeout class: NOT a server-side defect. Traces proved server bash+python boot completes in <1s every time (no pip runs, no import stalls >0.4s, no tracebacks, no OOM, no cgroup throttle). Failures struck multiple rounds at the *same wall-clock instant* — box-wide contention events on a host shared by ~60 concurrent benchmark pipelines: loopback ephemeral-port/TIME_WAIT exhaustion (27k of 28.2k ports occupied at idle) plus scheduling bursts. The plugin's readiness poll fast-fails (EADDRNOTAVAIL class, wrapped as ConnectionError) for its full 15s budget, then the next restart kills the (already listening) server.

**Fixes applied (final state):**
- `workspace/implementation/app.py` — serve via waitress (`threads=8`, `channel_timeout=30`) with fallback to Flask dev server (same pattern as task_1247). Serving-infrastructure only; no PRD-visible behavior change.
- `workspace/implementation/requirements.txt` — added `waitress>=3.0.0`.
- `workspace/implementation/start.sh` — import check widened to `import flask, waitress`, guarded pip install with a `--user --break-system-packages` fallback (PEP 668 host).
- `test_suite/conftest.py` — new autouse fixture `_fresh_connection_pool` calling `api_client.session.close()` before every test: drops pooled connections to the just-killed server (deterministic cure for the ECONNRESET class) while preserving keep-alive reuse *within* a test, cutting per-round connection churn ~5x (box TIME_WAIT fell 27k -> 15k).
- `test_helpers/api_client.py` — no net change (a `Connection: close` header was trialled and then removed in favor of the pool-reset fixture, which is strictly better: same determinism, far less churn).

**Tests deleted: 0.** Every failing test asserted PRD-covered, uniquely-derivable behavior; all failures traced to harness/environment timing, never to assertions, fixtures, or implementation logic. No test weakening, no skip/xfail, no implementation check removed.

**Final: two consecutive clean sweeps — 8/8 rounds x 79/79 tests each (16 rounds, union of failures: 0).** Exit condition met.

## Step 7: Run Tests and Iterate — 2026-08-12T21:50:00.000Z

All done. Two consecutive clean 8-round sweeps confirm stability.

## Summary

**Exit condition met: two consecutive 8-round parallel sweeps, each 8/8 rounds × 79/79 tests passed (union of failures across all 16 final rounds: 0).**

**Iterations run:** 6 sweeps (1 baseline + 1 after first fix + 3 instrumented diagnostics + 1 clean + 1 confirmation).

**Tests deleted:** 0 — every failure in every round was a harness/environment timing event (`could not be restarted` setup errors, `ConnectionResetError`/`RemoteDisconnected` mid-test), never an assertion failure. No test was deleted, weakened, skipped, or downgraded; no PRD rule was implicated by any failure.

**Fixes applied to `test_helpers/`:**
- `test_helpers/api_client.py` — trialled `api_client.session.headers["Connection"] = "close"` (the task_1247 pattern), then removed it in favor of the strictly better pool-reset below (same determinism, ~5× less connection churn). Net: no change to this file.
- `test_suite/conftest.py` — added autouse fixture `_fresh_connection_pool` calling `api_client.session.close()` before every test: deterministically discards pooled keep-alive connections to the just-killed server (cures the ECONNRESET class at its root) while keeping keep-alive reuse *within* each test.

**Fixes applied to `implementation/` (serving infrastructure only — no PRD-visible behavior change):**
- `workspace/implementation/app.py` — serve via waitress (`threads=8`, `channel_timeout=30`) with fallback to Flask dev server.
- `workspace/implementation/requirements.txt` — added `waitress>=3.0.0`.
- `workspace/implementation/start.sh` — import guard widened to `import flask, waitress`; pip install gets a `--user --break-system-packages` fallback (this host is PEP 668-managed). Waitress was also preinstalled to user site-packages so no boot ever runs pip.

**Root-cause evidence (diagnostics all reverted):** timestamped boot traces across 3 instrumented sweeps proved every server boot completed in <1s (no pip runs, no import stalls, no tracebacks, no OOM, no cgroup throttle); failures struck multiple rounds at identical wall-clock instants — box-wide contention storms on a host shared by ~60 concurrent benchmark pipelines: loopback ephemeral-port/TIME_WAIT exhaustion (27k of 28.2k ports occupied at idle, falling to 15k after our churn reduction) plus scheduling bursts. The pytest plugin's 15s restart-readiness poll fast-fails through such a storm, then kills the already-listening server.

## Step 8: Finalize PRD — 2026-08-12T21:55:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1300_retail_store_fixture_manufacturing_rollout/workspace/PRD_FINALIZED.md` exists and is byte-identical to `PRD.md` — the identity patch is the correct minimal patch here, because every Step 7 fix was serving/test-harness infrastructure with no PRD-visible behavior change, and Step 7 recorded zero assertion failures and zero test deletions across all sweeps.

## Line counts / delta

- `PRD.md`: 326 lines — `PRD_FINALIZED.md`: 326 lines — delta 0 lines, 0.0% (md5-identical: `ca30bd7c…`).

## Changes

None. Zero `<step_7_diff>` items trace to a PRD silence or PRD/impl mismatch:

- **`test_helpers/api_client.py`** — net zero change (trial header reverted); nothing to pin.
- **`test_suite/conftest.py`** — `_fresh_connection_pool` autouse fixture is test-harness connection hygiene, not API behavior.
- **`implementation/app.py` / `requirements.txt` / `start.sh`** — waitress serving, dependency, and boot-guard changes are transport/boot-layer only; the PRD governs REST semantics and is (correctly) silent on WSGI serving, which INSTRUCTION.md owns.

## Per-edit (candidate) pre-edit search log

For each candidate edit, the mandatory (a) subject and (b) enumerated impl paths; (c) wording adjustment — moot, since each candidate was rejected before wording was committed.

1. **Candidate: pin waitress/threaded serving in PRD.**
   (a) Subject: HTTP serving layer (WSGI server choice, thread count, `channel_timeout`).
   (b) Enumerated paths: `grep -rn "waitress\|app.run\|serve("` and `grep -rn "PORT\|0.0.0.0"` over `implementation/` — the only server-start site in the codebase is `app.py:62-68` (`serve(app, host="0.0.0.0", port=port, threads=8, channel_timeout=30)` with `except ImportError: app.run(host="0.0.0.0", port=port, threaded=True)`); launched solely via `start.sh:11` (`exec python3 app.py`); dependency declared in `requirements.txt:2`. Also grepped `PRD.md` for `flask|waitress|wsgi|thread|server|port|deploy|host|listen` — zero infrastructure hits; every "server" occurrence denotes the API server's behavioral role (logical clock, cascades, aggregates), which this change does not touch.
   (c) Rejected, not reworded: the implementation itself treats waitress and the Flask dev server as interchangeable (explicit ImportError fallback), so any PRD sentence pinning waitress would be a false universal claim — a new mismatch under the NO-NEW-MISMATCH RULE. Step 7's diff also asserts "no PRD-visible behavior change" for this item.

2. **Candidate: document the conftest connection-pool reset.**
   (a) Subject: test-suite fixture lifecycle (`_fresh_connection_pool` calling `api_client.session.close()` before each test, `test_suite/conftest.py:14,25`).
   (b) Enumerated paths: `test_suite/conftest.py` and `test_helpers/api_client.py` (confirmed no net change there). The fixture acts on the *client* session, not the server; no file under `implementation/` is involved.
   (c) Rejected: test-harness-only, outside PRD scope by definition.

3. **Candidate: document `start.sh` boot behavior (import guard, pip `--user --break-system-packages` fallback).**
   (a) Subject: boot/install contract.
   (b) Enumerated paths: `implementation/start.sh:1-11` (the only entrypoint), checked against INSTRUCTION.md's contract (PORT env with default 10000, bind 0.0.0.0, foreground via `exec`, <60s readiness) — all still satisfied verbatim.
   (c) Rejected: the boot contract lives in INSTRUCTION.md, which is not being patched; PRD.md makes no boot claims, so there is nothing to align.

No other edits were considered, per the hard scope limiting edits to `<step_7_diff>` items. Step 7's exit condition (two consecutive 8/8-round × 79/79-test clean sweeps, zero assertion failures ever) confirms the implementation already matches the PRD on every behaviorally tested dimension; the failures cured were host-contention artifacts (ephemeral-port/TIME_WAIT exhaustion, connection resets), not spec divergences.

## Step 9: Complete PRD — 2026-08-12T22:15:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1300_retail_store_fixture_manufacturing_rollout/workspace/PRD_COMPLETED.md` produced.

## Summary

**Source:** `PRD_FINALIZED.md` (byte-identical to `PRD.md`) → copied to `PRD_COMPLETED.md`, edited in place only.
**Line counts:** 326 → 328 lines; 52,849 → 57,154 chars (char-delta **+4,305**). 21 diff hunks, all inline inserts/revisions; no new sections.
**Counts:** 23 ambiguity-pins, 5 mismatch-revisions.

### Ambiguity-pins (PRD silent → pinned impl behavior)

- §2.1 — insert — ambiguity — whitespace-only `X-User-ID`/`X-User-Role` rejected with 400; a role header naming none of the nine roles gets `ERR_INSUFFICIENT_PERMISSIONS` on every endpoint, reads included — middleware.py:37, 58-70
- §2.2 — insert — ambiguity — undefined route → `ERR_NOT_FOUND` (404), unsupported method → `ERR_METHOD_NOT_ALLOWED` (405), unexpected failure → `ERR_INTERNAL` (500), same envelope — app.py:43-54
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST`; empty value treated as omitted — util.py:25-52
- §2.3 — insert — ambiguity — `created_at`-ascending sort ties broken by `id` ascending — util.py:179-181
- §2.3 — insert — ambiguity — `has_more` true iff `offset` + page size < `total_count` — response.py:35
- §2.3 — insert — ambiguity — filters are exact-match equality; empty filter values ignored — util.py:170-176
- §2.4 — insert — ambiguity — `version` starts at 1 at creation — db.py:71
- §2.4 — insert — ambiguity — `created_at`/`updated_at` are wall-clock UTC, independent of the §2.8 logical clock — db.py:53-57
- §2.6 — insert — ambiguity — missing/non-integer version expectation → `ERR_INVALID_REQUEST`; stale check fires after the state gate and the body's other required fields, before the underflow rule on ledger adjust — kits.py:126-134, ledgers.py:63-79
- §2.7 item 4 — insert — ambiguity — kit creation resolves `program_id` before `prototype_id` — kits.py:81-86
- §2.7 item 7 — insert — ambiguity — required strings non-empty; calendar dates `YYYY-MM-DD`; timestamps well-formed ISO 8601 — util.py:86-147
- §3.2 — insert — ambiguity — `bom_lines` may be empty (both estimates zero) — prototypes.py:69, calculations.py:25-37
- §3.2 — insert — ambiguity — patch field explicitly null is treated as omitted — prototypes.py:123-129
- §3.2 — insert — ambiguity — submit-review from states other than `DRAFT`/`VALUE_ENGINEERING` → `ERR_PROTOTYPE_INVALID_STATE` — prototypes.py:141-145
- §3.3 — insert — ambiguity — kit patch body must carry `config_lines` as an array, else `ERR_INVALID_REQUEST` — kits.py:129
- §3.4 — insert — ambiguity — release-charge tier boundaries evaluated on the unrounded post-release percentage, not the 1-dp `utilization_pct` — calculations.py:62-68
- §3.5 — insert — ambiguity — delivery created for a kit with no `HELD` reservation consumes none and succeeds — deliveries.py:71-79
- §3.7 — insert — ambiguity — `notes` defaults to null when omitted — signoffs.py:59
- §3.7 — insert — ambiguity — reject with absent/empty/non-string `reason` → `ERR_INVALID_REQUEST` — signoffs.py:166-169
- §3.7 — insert — ambiguity — resubmit retains previous `notes` when omitted or null — signoffs.py:185-189
- §3.8 — insert — ambiguity — adjust check order: state gate → `delta`/`expected_ledger_version` presence+type → version match → underflow → `reorder_point` type — ledgers.py:63-85
- §3.8 — insert — ambiguity — `reorder_required` re-evaluated against a newly supplied `reorder_point` — ledgers.py:81-88
- §4 — insert — ambiguity — unconsumed request-body fields (incl. client-supplied computed fields) are ignored — programs.py:67-83 and all create handlers

### Mismatch-revisions (PRD described different behavior → revised to impl)

- §2.7 item 4 — revise — mismatch — creation endpoints structurally validate the body (required fields, types, minimum bounds, enums, line well-formedness, date/timestamp formats, photo evidence on signoff create) immediately after role auth, *before* body-referenced existence (PRD had existence strictly 4th, shape strictly 7th); wave creation's `capacity_units` minimum and window check noted as the lone post-existence exception — prototypes.py:67-75, kits.py:73-86, waves.py:45-58, reservations.py:46-63, deliveries.py:45-58, claims.py:49-59, signoffs.py:57-65
- §2.7 item 4 — revise — mismatch — on kit release the kit's `FROZEN` gate precedes resolution of the body-supplied `wave_id` (§3.4 narrative already matched impl) — kits.py:190-196
- §2.7 item 7 — revise — mismatch — companion scope note: on existing-resource operations the whole shape category sits at position 7 (after state gates); on creations its structural portion ran earlier — kits.py:126-132, ledgers.py:63-73, prototypes.py:117-129
- §3.1 — revise — mismatch — prototype/kit/wave creation is not gated on program status (was "While the program is `DRAFT` or `ACTIVE`…"); pre-activation reachability restated as a consequence of the freeze/commit `ACTIVE` gates — prototypes.py:73-75, kits.py:81-86, waves.py:51-53 (no state checks)
- §3.8 — revise — mismatch — dispose ordering pinned as ledger state → `disposition_type` validity → program `CLOSEOUT_PENDING` (PRD prose implied program-state gate before disposition_type) — ledgers.py:104-112

Everything else in the impl (all 45 endpoints/roles, all state machines, all calculation formulas and rounding orders, cascades, error catalogue and HTTP statuses, envelope shapes, clock transitions) matched PRD prose uniquely and required no change.
