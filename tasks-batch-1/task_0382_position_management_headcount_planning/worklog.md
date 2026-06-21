# Worklog — task_0382_position_management_headcount_planning

Scenario: 382. Position Management & Headcount Planning: position (requisitioned/funded) & FTE, org-chart & reporting line, vacancy & backfill, budget/cost-center mapping, reclassification & grade, span-of-control, headcount forecast vs actual, freeze/approval

Difficulty band (Step 2 only): Expert

## Step 1: Create task directory — 2026-06-16T14:43:54.000Z

Created pre-assigned task directory `tasks/task_0382_position_management_headcount_planning/` with `workspace/` subfolder. Index scan skipped per pre-assignment to avoid task-ID contention with concurrent sibling pipelines.

## Step 2: Generate scaffold (Expert band) — 2026-06-16T15:13:24.000Z

File-split rule honored: SCAFFOLD.yaml contains §1.0–§1.7 (plus preamble + concurrency_rules) with neither design key; each design file has exactly its single top-level key.

All three scaffold artifacts are generated, internally consistent, and pass `scaffold_lint.py` cleanly.

**Complexity profile**: primary archetype quota/allocation (cost-center FTE + dollar budget as a finite pool) blended with posture-driven gating (freeze posture gates child ops); graph topology (self-referential org-chart reporting line); parallel state-machine shape; approval-chain RBAC; immediate consistency. Layers: optimistic concurrency, cascading side effects, dual-variant calculation, derived-field reconciliation.

**SCAFFOLD.yaml contents**
- **10 entities**: Employee, Grade (immutable), CostCenter, Position, Incumbent, FreezeOrder, Requisition, ReclassRequest, ForecastPeriod, BudgetAdjustment (append-only event)
- **6 state machines** across Position (two parallel dimensions: lifecycle DRAFT→REQUISITIONED→FUNDED↔FROZEN→ABOLISHED, and occupancy VACANT↔FILLED), FreezeOrder, Requisition (branching+revert), ReclassRequest (cyclic revision loop), ForecastPeriod
- **2 concurrency rules** (OCC on CostCenter.version for fund and snapshot, both 412 ERR_STALE_VERSION)
- **13 calculations** (planned vs actual cost dual-variant, committed-cost round-per-position-then-sum, fund-admission nested min/max, span-of-control, half-open freeze posture, reclass direction, forecast variance, budget aggregation)
- **13 validations** (priority-ordered auth→existence→OCC→state→referential→constraint→fiscal)
- **51 endpoints**, **18 errors**, **4 roles** (HRBP, FinanceController, CompensationAnalyst, HRDirector — approval chain, all opaque identity)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml**: all 9 Difficulty Rules × 2 = **18 instances**, every formula-derived assert pre-computed to literals (e.g. planned 6000000 vs actual 7500000; round-per-position 10000002 vs 10000001; FTE cap 1.0 boundary; budget ±1 cent; freeze→position→requisition depth-3 cascade; fill/vacate conserves committed_cost_cents; freeze/lift conserves committed_fte).

**SCAFFOLD_CORNER_DESIGN.yaml**: **38 active** corner instances spanning all 9 claim-extraction-guide sections (entities, state_machines, calculations, validations, rbac, endpoints, cross_cutting_complexity_layers, consistency_model) plus **6 excluded_because stubs**.

Files: SCAFFOLD.yaml (1315 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (916 lines), SCAFFOLD_CORNER_DESIGN.yaml (1344 lines). Verified present.

## Step 3: Copy INSTRUCTION.md — 2026-06-16T15:13:24.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-16T15:18:58.000Z

Generated PRD at `workspace/PRD.md` (265 lines, 42499 bytes).

**Section count:** 5 top-level sections, 19 subsections — §1 Introduction; §2 Global Specifications (2.1 RBAC, 2.2 fixed Response Structure, 2.3 Pagination, plus 7 cross-cutting principles: common properties, validation ordering, OCC, plan-vs-actual cost doctrine, FTE/budget pool, freeze posture, cascade discipline); §3 Business Logic (9 lifecycle/workflow subsections); §4 Endpoint Definitions (52-row table); §5 Error Code Catalogue (18-row table).

**Hard Contract reports:**
- Contract 1 — Field-Name Coverage: 57 required identifiers, 57 present, 0 missing. PASS (3 initially-missing — `action`, `to_iso8601`, `MAX_SPAN_OF_CONTROL` — repaired then re-diffed clean).
- Contract 2 — Rule Coverage: 13 validations (priority order as explicit masking chain in §2.5); 2 concurrency_rules (both name write op + expected_cost_center_version + ERR_STALE_VERSION + 412); all state-machine transitions, cascades (freeze→positions→requisitions, lift compensating un-freeze, abolish teardown), dual-variant planned/actual cost, per-position-then-sum rounding, span gate, half-open freeze windows, reclass direction, forecast variance; all 18 error IDs surfaced. PASS.
- Contract 3 — §3 Path Purity: 345 backtick tokens, 0 paths/methods. PASS.

**Confirmation:** Neither design YAML was read; no sibling task accessed.

## Step 5: Generate unit tests — 2026-06-16T19:08:51.539Z

## Test Infrastructure Generation Summary — task_0382_position_management_headcount_planning

### Files generated

**`test_helpers/` (Stage 1 — 9 files, all compile clean):**
- `__init__.py` — barrel export (framework generics + PRD-specific)
- `types.py` — entity TypedDicts + 11 status/role enums; `Grade` and `BudgetAdjustment` correctly carry only `id`+`created_at` (common_fields:false), all others carry the full id/created_at/updated_at/version quartet
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (all 50 endpoints incl. `/_clock/set_current_utc`)
- `api_errors.py` — `ApiErrorId` enum (18 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + cost-center derived-field invariant checker
- `factories.py` — input-field-only payload factories with unique-value generators
- `constants.py` — `MAX_SPAN_OF_CONTROL=8`, pagination, reusable grade-band profiles
- `test_users.py` — shared role headers (all four roles are opaque; no entity-backed builders needed)
- `fixtures.py` — tiered composite helpers (master data, lifecycle progression, fill/vacate, freeze cascades, requisition, reclass, forecast, budget adjustment, span-of-control). Every fund/snapshot helper reads the live cost-center version as a fresh OCC token.

**`test_suite/` (Stage 2 — conftest + 6 test files):**
- `conftest.py` — `api` session fixture + 5 role-header fixtures
- `test_01_position_lifecycle.py` (12), `test_02_cost_calculations.py` (12), `test_03_freeze_cascades.py` (12), `test_04_reclass_workflow.py` (6), `test_05_validation_and_rbac.py` (16), `test_06_crud_and_listing.py` (16)

### Test counts
**74 tests total**, all from the two design indices (no freelance discovery).

### Coverage audit — fully green
- **Queue A (Difficulty):** 18/18 instances tagged, **each with exactly 2 tests** (≥2 satisfied). Zero shortfalls.
- **Queue B (Corner):** 38/38 non-stub instances tagged, **each with ≥1 test**.
- **Tag integrity:** every `Design: Difficulty/...` and `Design: Corner/...` line resolves to a real `name:` in the source YAML; zero dangling/dual/untagged tests; every test has exactly one tag.
- **6 excluded_because stubs** (`excl_reclass_revision_loop`, `excl_position_parallel_dimensions`, `excl_abolish_cascade_to_incumbent`, `excl_committed_cost_dual_variant`, `excl_committed_cost_rounding_order`, `excl_snapshot_occ_stale`) correctly NOT translated; all their `difficulty_instance` cross-references verified to resolve to real difficulty instances.

### PRD-citation pass
- Every docstring carries verbatim PRD quotes (C1) confirmed by scripted grep against `PRD.md` modulo backticks/bold/whitespace; all citations are rule-bearing (C2) and full-sentence (C3).
- Fixed 2 genuine C1 violations found during the sweep (editorial brackets spliced into quotes in `test_05`) by rewriting them to quote the exact PRD §2.5/§2.9/§3.8 sentences.
- Zero `pytest.mark.skip`/`skipif`/`xfail`. Zero "scaffold"/"Table N"/"§1.x" leakage in emitted code.

### Skipped instances
**None.** Every non-stub instance in both queues passed the PRD-first two-condition filter (verbatim coverage + unique derivability) and was translated. One test (`test_refill_overlapping_active_incumbency_rejected`, an earlier draft of a 2nd `rto_incumbency` test) was reworked — not skipped — into a deterministic VACATED-interval-overlap scenario so it asserts `ERR_INCUMBENCY_OVERLAP` cleanly without colliding with the validation-ordering `ERR_POSITION_ALREADY_FILLED` gate.

### Notes for downstream
- All four roles are opaque-identity, so RBAC/ownership is role-only — `test_users.py` emits no `make_*_headers` entity-backed builders (none exist in this PRD).
- The framework (`prd_bench_local_runner`) is not installed in this generation environment; all files were validated with `py_compile`/`compileall` (clean). The earlier `ast.parse` failure was purely the local `types.py` shadowing stdlib when run from inside the dir — package-qualified imports resolve correctly at runtime under the runner's PYTHONPATH.

## Step 6: Generate implementation — 2026-06-16T19:08:51.539Z

## Implementation Summary — task_0382_position_management_headcount_planning

### Files Generated (24 files in `workspace/implementation/`)

**Launcher / deps**
- `start.sh` — foreground bash launcher, guards `pip install` on a cheap `import flask` check, `exec python3 app.py`
- `requirements.txt` — `flask==3.0.3`

**Foundation**
- `app.py` — Flask entry point; registers 10 blueprints; ApiError/404/405/HTTPException/Exception handlers all emit the standard error envelope; binds `0.0.0.0:$PORT` (default 10000) with a bind-retry loop for per-test-server reboots. No seeding at startup.
- `db.py` — in-memory `Store` (10 dicts) + logical test clock `current_utc` + monotonic `_seq`; fresh per process boot
- `errors.py` — `ApiError` + `ERROR_CATALOG` (all 18 error IDs → HTTP codes from §5)
- `response.py` — success/list/error envelope (`meta`/`response_type`/`data`; `api_request_id` `req_` prefix; ISO-8601 UTC millis)
- `middleware.py` — `require_auth`: `X-User-Role` against the 4 roles (401 unrecognized), then RBAC (403); identity is opaque, X-User-ID never matched
- `util.py` — UUID ids, request ids, ISO timestamp formatting, half-up rounding, lenient datetime parsing

**Services**
- `services/calc.py` — all 12 calculations: per-position `planned/actual_cost_cents` (round-half-up before aggregation), cost-center `committed_cost_cents`/`committed_fte`/`filled_fte`/`adjusted`/`available` (sum-then-round 2dp for FTE), `span_of_control`, half-open `cost_center_posture`, `reclass_direction`; `MAX_SPAN_OF_CONTROL=8`
- `services/cascade.py` — freeze/lift/clock posture reconciliation; FUNDED↔FROZEN position cascade with transitive OPEN↔SUSPENDED requisition hops
- `services/serialize.py` — per-entity output dicts; derived fields materialized at read time (immediate consistency); Grade/BudgetAdjustment emit only `id`+`created_at`
- `services/common.py` — body parsing, field/enum/int validators, `validate_fte` ((0,1.0] ≤2dp), pagination (limit 10/1–100, offset 0), `created_at`-asc sort, version/timestamp bump helpers

**Routes (10 blueprints)** — employees, grades, cost_centers (+budget-adjustments), positions (+lifecycle/reports/cc-positions), incumbents (fill/vacate), freeze_orders (+lift), requisitions, reclass_requests, forecast_periods (+snapshot), clock.

### Endpoint Coverage
All **51 endpoints** from PRD §4 / SCAFFOLD Table 5 implemented: full CRUD+list for all 10 entities, position lifecycle (REQUISITION/FUND/ABOLISH), incumbent fill/vacate, freeze create/lift, requisition approve/close/cancel, reclass review/return/approve/reject, forecast create/snapshot, budget-adjustment apply, and `POST /_clock/set_current_utc`.

### Design Notes
- **Validation priority** (§2.5) strictly ordered: auth(401)→forbidden(403)→not-found(404)→well-formed(422)→OCC(412)→state(409)→frozen→span→has-reports→fill-preconditions→freeze-overlap→FTE-cap→budget. The shared `/lifecycle` endpoint admits the 3 lifecycle roles at the auth layer, then enforces per-action role (HRBP/FinanceController/HRDirector) after the action is parsed.
- **Plan-vs-actual doctrine** (§2.7): money in integer cents, `Decimal` + `ROUND_HALF_UP`, rounded **per position before** summation; fill swaps planned→actual basis, vacate restores planned (conservation verified: 1000→1250→1000).
- **OCC** (§2.6): only FUND and snapshot accept `expected_cost_center_version`; mismatch → `ERR_STALE_VERSION` (412); FUND and snapshot each bump the cost-center `version`.
- **Posture** (§2.9): half-open `[from, to)`; freeze orders cache parsed `_from_dt`/`_to_dt`; the clock endpoint snapshots all postures, advances time, then fires freeze/un-freeze cascades for windows that opened/closed.
- **Cascades** (§2.10): every touched record (position, requisition, reclass, incumbent, employee, cost center) bumps its own `version`+`updated_at`. Abolish-funded teardown (vacate incumbent, employee→AVAILABLE, OPEN/SUSPENDED reqs→CANCELLED, SUBMITTED/UNDER_REVIEW reclass→REJECTED, release commitment) verified end-to-end.
- **Derived consistency**: cost-center and position derived fields are computed from live state at serialization time, so reads are always consistent with children regardless of mutation path.

### Verification
Imported cleanly and booted via `start.sh` (HTTP 200 within ~3s). Ran three end-to-end smoke scenarios covering: auth/RBAC, envelope shape, plan/actual cost swing, OCC stale+valid, FTE-cap & budget gates, fill preconditions (salary-out-of-band, incumbency-overlap against vacated interval), freeze→FROZEN cascade + frozen-gate blocking + lift→FUNDED, reclass UPGRADE budget check + override, span-of-control (8 allowed / 9th rejected), abolish-has-reports guard, freeze-window overlap (rejected) vs touching-boundary (allowed), forecast snapshot variance, pagination meta, fte>1 and limit>100 rejection, and validation precedence (404-before-403, 401-before-existence). All passed with no server-side errors.

## Step 7: Run tests and iterate — 2026-06-16T19:55:19.763Z

All fixes complete and verified. Final summary below.

## Summary

**Iterations run:** 2 sweeps (1 diagnostic baseline + 1 confirmation). The baseline showed 71/74 passing with the same 3 tests failing deterministically in all 8 rounds (no flakiness). The post-fix sweep showed 73/73 in all 8 rounds.

**Tests deleted (1):**
- `test_filled_fte_sums_then_rounds_to_two_decimals` (test_02_cost_calculations.py) — **STEP 1b unique-derivability collapse**. The test asserts PRD §2.7's "sum FTE values then round half-up to two decimals" by funding/filling positions with `fte=0.333` and `fte=0.334`. But PRD line 124/82 verbatim requires every `fte` be "at most 1.0 with at most two decimal places", so the faithful implementation correctly rejects the setup with HTTP 422 `ERR_INVALID_REQUEST`. Under PRD-valid two-decimal inputs, the sum of two-decimal FTE values is already exact to two decimals, so the §2.7 rounding rule has no observable effect — the asserted outcome is only reachable with PRD-forbidden three-decimal inputs. The scaffold rule that drove it: `Corner/calculations/calc_filled_fte_sum_then_round`.

**Fixes applied to test_suite/ (1):**
- `test_05_validation_and_rbac.py`, `test_frozen_fund_leaves_position_requisitioned` — **STEP 2 test bug (payload inconsistent with PRD)**. The test hardcoded `expected_cost_center_version=2`, but after the setup (create CC → v1; requisition position and open freeze order do not bump CC version) the live version is 1. Per PRD §2.5 the OCC version check (ERR_STALE_VERSION, priority 5) legitimately masks the frozen-posture rule (priority 7), so the wrong hardcoded version produced `ERR_STALE_VERSION`. Replaced the literal with `fixtures.cost_center_version(cc["id"])`, matching its passing sibling `test_frozen_masks_budget_on_fund`. No assertion was weakened.

**Fixes applied to implementation/ (1):**
- `routes/incumbents.py`, `_intervals_overlap` — **STEP 3 implementation bug**. PRD §3.4 states a fill's `start_date` is "the inclusive occupancy start" (line 142) and a vacated incumbency's `end_date` is set to `vacate_date` "(inclusive)" (line 146). The helper used half-open `[start, end)` semantics (strict `<`), so a refill starting exactly on the prior interval's inclusive end (`2026-06-30`) was not detected as an overlap and the fill wrongly succeeded. Changed the comparison to inclusive closed-interval semantics (`<=`), so two intervals sharing a boundary instant overlap → `ERR_INCUMBENCY_OVERLAP`. Verified no legitimate refill-success test is affected (no test refills strictly after the inclusive end; the other refill test asserts overlap-inside-interval, still correct).

**Final sweep confirmation:** Round 1: 73/73 · Round 2: 73/73 · Round 3: 73/73 · Round 4: 73/73 · Round 5: 73/73 · Round 6: 73/73 · Round 7: 73/73 · Round 8: 73/73. All 8 parallel rounds green, 0 failures, 0 errors. Transient `results.*.json` files removed.

_Orchestrator note: regenerated the 8 durable `results.{1..8}.json` files via one final confirming sweep (all 73/73) since the subagent had cleaned them up; these are retained as the passing-sweep artifact._

## Step 8: Finalize PRD — 2026-06-16T19:58:50.114Z

The diff is clean — exactly one edit to §3.4 line 142, pinning the closed-interval (inclusive boundary) overlap semantics that the Step 7 impl fix established. Line count unchanged (the edit is within a single line).

## Summary

**Line counts:** PRD.md = 265 lines; PRD_FINALIZED.md = 265 lines; %-delta = 0% line count (1 line revised in place, content expanded).

**Changes (1):**
- §3.4 (Filling and Vacating) — *revise* — Appended an explicit closed-interval overlap rule to the incumbency-overlap sentence: both endpoints are inclusive, so two incumbency intervals that touch at a shared boundary instant DO overlap (the opposite of §2.9's half-open freeze windows), and a refill must begin strictly after the prior `end_date` — `routes/incumbents.py:20-32, 74-80` (`_intervals_overlap` using `<=`).

**Disposition of the 4 step_7_diff items:**
- Item 1 (deleted test `test_filled_fte_sums_then_rounds_to_two_decimals`): No PRD edit. A unique-derivability collapse — PRD lines 82/124 already forbid 3-decimal `fte` (impl's `validate_fte` rejects with `ERR_INVALID_REQUEST`), and §2.7's sum-then-round rule (line 96) already describes `calc.committed_fte`. PRD already determines this.
- Item 2/3 (test fixture fixes in `test_05_validation_and_rbac.py`): No PRD edit. Pure fixture bugs (hardcoded `expected_cost_center_version=2` vs. live `1`); PRD §2.5 priority ordering already correct.
- Item 4 (impl fix to `_intervals_overlap`): The one edit above. Although Step 7 framed it as an impl bug fixed *toward* the PRD, the original prose only implied closed semantics via two scattered "inclusive" qualifiers and never stated the boundary-touching rule for incumbencies (while it states it explicitly for freeze windows) — a genuine silence that produced the original half-open bug. Pinning it guarantees a fresh implementer reproduces the impl's `<=` behavior.

**Per-edit pre-edit search log:**
- Edit (§3.4 incumbency overlap):
  - (a) Subject: incumbency-interval overlap detection (`ERR_INCUMBENCY_OVERLAP`) and the inclusive/closed vs. half-open boundary semantics.
  - (b) Enumerated/read impl paths: `routes/incumbents.py` `_intervals_overlap` (lines 20-32) and its sole callsite in `fill_position` (lines 74-80); `util.parse_datetime`; grepped all of `implementation/` for `overlap`/`INCUMBENCY_OVERLAP`/`_intervals_overlap` — confirmed the only incumbency-overlap path. Also read `routes/freeze_orders.py` (lines 36-46) to confirm freeze-window overlap is a separate, explicitly half-open path (`<` strict) that PRD §2.9/§3.5 already describe correctly.
  - (c) Wording adjustments: used "instant" (not "date") to match the datetime-precision comparison; scoped the ACTIVE-prior clause to "whose end is still open"; referenced §2.9 (the canonical half-open freeze definition) rather than §3.5.

## Step 9: Complete PRD — 2026-06-16T20:04:51.003Z

Header count is identical (27 → 27): no sections added. 15 changed lines correspond to 14 edits (one edit touched line 72, which received two inserts in the same paragraph).

## Summary

**File metrics**
- `PRD_FINALIZED.md`: 265 lines, 43,208 chars
- `PRD_COMPLETED.md`: 265 lines, 46,441 chars (char delta +3,233; line count unchanged — every change was an in-paragraph insert/revise, no new lines or sections)

**Change counts**
- Ambiguity-pins (PRD silent → pinned): 11
- Mismatch-revisions (PRD said something else → revised): 3
- Total edits: 14

**Per-change log** (`{section} — {kind} — {class} — {what} — {impl ref}`)

- §2.3 Pagination — insert — ambiguity — out-of-range/non-integer `limit`/`offset` → `ERR_INVALID_REQUEST` (422) — `services/common.py:129-155`
- §2.3 Pagination — insert — ambiguity — list filters are exact-match, AND-combined, applied before pagination; unknown params ignored — e.g. `routes/positions.py:82-86`, `routes/incumbents.py:122-125`
- §2.6 OCC — revise — mismatch — `expected_cost_center_version` is optional (skipped when omitted) and must be an integer when present, not mandatory — `routes/positions.py:209-214`, `routes/forecast_periods.py:87-92`
- §3.1 Employee — insert — ambiguity — duplicate `email` → `ERR_INVALID_REQUEST` (422) — `routes/employees.py:27-29`
- §3.1 Grade — insert — ambiguity — duplicate `code`/`rank` and boundary-ordering violations → `ERR_INVALID_REQUEST`; ordering check before uniqueness, code-uniqueness before rank-uniqueness — `routes/grades.py:29-39`
- §3.1 CostCenter — insert — ambiguity — duplicate `code` → `ERR_INVALID_REQUEST` (422) — `routes/cost_centers.py:30-32`
- §3.1 BudgetAdjustment — insert — ambiguity — zero/non-integer/missing `amount_cents` → `ERR_INVALID_REQUEST` (422) — `routes/cost_centers.py:66-72`
- §3.2 Position edit — insert — ambiguity — non-editable-state edit → `ERR_INVALID_STATE` (409); `manager_position_id` nullable; field-less patch is a no-op with unchanged `version` — `routes/positions.py:116-137`
- §3.3 Lifecycle endpoint — insert — ambiguity — endpoint admits 3 roles; bad `action` → `ERR_INVALID_REQUEST`; per-action role check happens after existence (missing position → `ERR_NOT_FOUND`, else `ERR_FORBIDDEN`) — `routes/positions.py:162-178,181-184`
- §3.3 Fund — revise — mismatch — `expected_cost_center_version` may be omitted (skips check) — `routes/positions.py:209-214`
- §3.4 Vacate — insert — ambiguity — missing/malformed `vacate_date` → `ERR_INVALID_REQUEST` (422); wrong state → `ERR_INVALID_STATE` (409) — `routes/incumbents.py:135-145`
- §3.5 Freeze order — insert — ambiguity — malformed-window (`from >= to`) → `ERR_FREEZE_WINDOW_OVERLAP`; well-formedness before overlap; missing/non-parseable timestamps → `ERR_INVALID_REQUEST` first — `routes/freeze_orders.py:29-46`
- §3.6 Requisition approve — insert — ambiguity — gate order is state → frozen-posture → not-funded (frozen wins on a non-funded+frozen case) — `routes/requisitions.py:76-83`
- §3.8 Abolish teardown — insert — ambiguity — cascade-vacated incumbent's `end_date` is set to its own `start_date` — `routes/positions.py:269-270`
- §3.9 Snapshot — revise — mismatch — `expected_cost_center_version` may be omitted (skips check); OCC check precedes the DRAFT-state check — `routes/forecast_periods.py:87-96`

**Notes on intentionally-unchanged areas** (verified consistent, no edit needed): reclass-approve gate ordering and its budget check against base `annual_budget_cents` (vs. fund's `adjusted_budget_cents`) already match impl; fill precondition ordering matches PRD prose verbatim; per-position-then-sum rounding, half-open freeze windows, closed incumbency intervals, span cap of 8, and the plan↔actual cost swing are all already uniquely pinned. Tests were used only as auxiliary cross-reference and confirmed the pinned behaviors.
