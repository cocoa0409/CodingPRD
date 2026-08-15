# Worklog — task_1577_pay_equity_analysis_reporting

## Step 1: Create Task Directory — 2026-08-13T22:14:00.000Z

Task directory `tasks/task_1577_pay_equity_analysis_reporting/` with `workspace/` subdirectory already existed at resume time (created by the prior killed run). Verified no worklog.md and no other artifacts present — resuming pipeline from Step 2.

## Step 2: Generate Scaffold — 2026-08-14T00:00:00.000Z

Done. All three scaffold artifacts generated for task 1577 (Pay Equity Analysis & Reporting), without looking at any sibling task.

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_1577_pay_equity_analysis_reporting/SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys): 12 entities, 9 state machines, 8 calculation rules, ordered validations (auth → existence → OCC 3.5 → input 3.7 → state 4 → safety 5 → temporal 6 → constraint 7 → fiscal 9), 59 endpoints (flat `/api/*` topology), 51 error codes, 6 roles (all `identity: opaque`; segregation-of-duties role model), 2 OCC concurrency rules, logical-clock test endpoint pinned to the `2026-08-01T00:00:00Z` default.
- `/home/ubuntu/github/CodingPRD/tasks/task_1577_pay_equity_analysis_reporting/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single `scaffold_difficulty_design:` key; all 9 rules × 2 instances = 18, every instance with a fully structured `setup_api_calls`/`trigger` chain and precomputed literal asserts.
- `/home/ubuntu/github/CodingPRD/tasks/task_1577_pay_equity_analysis_reporting/SCAFFOLD_CORNER_DESIGN.yaml` — single `scaffold_corner_design:` key; 60 instances (51 active + 9 `excluded_because:` stubs) across all nine guide sections, including a full error-catalog triggerability sweep.

**Key design choices**
- Archetypes: compliance/audit + workflow orchestration; layers: OCC, dual-variant calc, scheduled actions, cascading side effects; cyclic state shape (legal-review rework loop, plan reject loop, GAPS_PERSIST reopen loop).
- Difficulty highlights: OLS-vs-median gap variants that flip actionability on identical data (3.0612 vs 9.5238); FULL_CLOSURE vs PRO_RATA waterfall with floor+deterministic remainder (703704/666667/629629 on a 2000000 budget); four-fifths nested-rounding boundary (exactly 0.8000 not flagged); closed-vs-half-open overlap semantics (study periods vs monitoring windows); depth-3 clock cascade (APPROVED→EFFECTIVE → finding RESOLVED → plan COMPLETED → study MONITORING); privilege version-pinning with auto-invalidation on late finalize; approve/reverse budget-cents and assign/unassign headcount conservation invariants.
- Every assert numeric was hand-computed from the pinned formulas (medians, 2dp per-employee deflation rounding, p-value heuristic, waterfall cents).

**Verification (all clean)**
- `scaffold_lint.py` verdict, verbatim: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (59 endpoints, 12 entities, 18 §1.8 + 51 §1.9 active instances, 901 calls scanned.)
- Additional self-audits passed: grounds resolvability, instance-name uniqueness across both files, ≥2 instances per rule, placeholder closure (zero unbound `${var}`), no forbidden concurrency vocabulary, correct file split of the three top-level keys.

Note: the task directory already contained a pre-existing `worklog.md` and `workspace/` — left untouched.

## Step 3: Copy Shared Files — 2026-08-14T00:02:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T00:19:00.000Z

The PRD is complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1577_pay_equity_analysis_reporting/workspace/PRD.md` (347 lines)

**Structure:** 2-paragraph introduction; §2 with 10 domain-derived subsections (RBAC with all six roles' opaque identity translated individually, verbatim §2.2 response-structure block, pagination, the logical clock and its pinned 5-stage sweep, common resource properties, the two OCC rules, money/precision, the full validation-priority ordering, CLOSED-vs-HALF-OPEN calendar semantics, derived aggregates); §3 with 7 lifecycle-grouped subsections covering all state machines, both calculation variants (REGRESSION_OLS with the 0.04 level loading and per-employee 2dp rounding; COHORT_MEDIAN medians), both allocation variants (FULL_CLOSURE advisory vs PRO_RATA floor-and-remainder waterfall), all side-effect cascades (privilege invalidation, finding auto-resolution, plan auto-transitions, auto-monitoring, GAPS_PERSIST reopen loop); §4 with all 59 endpoints in a 4-column table; §5 with all 51 errors in a 2-column table whose statuses match the scaffold catalog exactly (including the 422 for `ERR_RANGE_DISCLOSURE_REQUIRED`).

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 93 required, 93 present, 0 missing
- endpoints[].request_body/input: 65 required, 65 present, 0 missing (decision/disposition fixed in pass 2)
- endpoints[].query_params: all covered (status, study_id, comparator_group_id, model_run_id, plan_id,
  employee_snapshot_id, gap_finding_id, jurisdiction_rule_id, stage, limit, offset — all entity-field names)
Status: PASS

Rule coverage check:
- validations[] priority ordering: 10 levels expressed as explicit ordered prose in §2.8, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write op + expected_group_version /
  expected_plan_version + ERR_STALE_GROUP_VERSION / ERR_STALE_PLAN_VERSION (412) + before-state evaluation), 0 missing
- state_machines[].transitions: 39 checked, 39 fully expressed (from/to states, precondition error ids,
  side effects), 0 missing
- calculations[]: 8 checked, 8 expressed in precise reconstructible prose (staged half-up rounding, 0.04
  loading, 365.25 tenure divisor, 0.80 four-fifths strict inequality, band edges with lower-inclusive
  semantics, pinned sweep order), 0 missing
- validations[] conditions: all 51 error ids matchable to prose in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: 59 endpoints, side effects expressed in §3 narratives, 0 missing
- entities[].fields[] structured content: defaults (0.05, 2.0, 30, 180, FULL_CLOSURE, false/null defaults)
  and derivations reconstructible from prose, 0 missing
- sibling-branch symmetry: APPROVE/REQUEST_CHANGES, APPROVE/REJECT (plan), APPROVE/REJECT (adjustment),
  ACCEPTED/REJECTED, TARGETED/MONITORED/DISMISSED, OLS/COHORT_MEDIAN, FULL_CLOSURE/PRO_RATA, both close
  paths — all rendered with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 607
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional lint: no pseudocode operators (`>=`, `==`, `min(`, `ROUND(`, etc.) and no fuzzy words ("approximately", "roughly", "about", "around") anywhere in the document. The forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-14T01:10:00.000Z

Generated complete test infrastructure for `task_1577_pay_equity_analysis_reporting`:

**`test_helpers/`** (9 files):
- `types.py` — 12 status/enum classes + 12 entity TypedDicts (all entities carry `id`/`created_at`/`updated_at`/`version`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (44 methods covering clock, studies, snapshots, groups, runs, findings, plans, adjustments, filings, jurisdictions, postings, pipeline analyses, cycles)
- `api_errors.py` — all 51 PRD §5 error IDs with HTTP status map, registered via `set_error_http_status_map` (note: `ERR_RANGE_DISCLOSURE_REQUIRED` mapped to 422 per the PRD §5 table)
- `assertions.py` — per-entity asserts + `assert_plan_budget_invariant` + order-agnostic `band_rows_as_set`
- `factories.py`, `constants.py` (LEVEL_LOADING 0.04, four-fifths 0.80, EEO band edges, default clock), `test_users.py` (six opaque roles + per-role `make_*_headers(user_id)` builders for segregation-of-duties scenarios)
- `fixtures.py` — tiered composites: `setup_provisional_run_scenario` → `setup_analyzed_study` → `setup_privileged_final_study` → `setup_remediation_open` → `setup_monitoring_study` (full clock-sweep cascade), plus standard member-spec sets reproducing the pinned gap math (six-FIN gap 10.0000/p 0.0323; two-ENG p 0.0909; seven-ENG median 9.5238 vs OLS 3.0612)

**`test_suite/`** — `conftest.py` + 9 test files, **86 tests**, all collected cleanly by pytest:
- All 18 difficulty instances covered by exactly 2 tests each (36 tests)
- All 49 translatable non-stub corner instances covered by 1 test each (50 tests)
- All 8 `excluded_because:` stubs correctly not translated (cross-references verified to resolve)

**Deliberate skip (1):** `Corner/errors/error_catalog_triggerability_sweep` — it is an audit instance whose trigger (`GET /api/pay-equity-studies`) has no asserted API behavior; its "asserts" are a coverage map of other tests, so it fails the PRD-first unique-derivability filter.

**Key PRD-fidelity decisions** (two-reader rule):
- Suggested-allocation tests assert the PRD-pinned fields (`strategy`, `total_suggested_cents`, suggestion count) and determinism of repeated reads; per-employee entry field names are not pinned by PRD prose, so per-entry cent values are not asserted by key.
- `version` initial value is never pinned (PRD only says "increments with every modification") — the defaults test asserts int-typedness, and the consistency test asserts strict increment.
- Timestamp equality asserts use the prefix `2026-08-01T00:00:00`, tolerating the PRD-pinned three-fractional-digit rendering.
- `create_posting_payload` leaves the optional salary bounds absent unless specified, so the publish ladder's min-only and range-less cases actually exercise the conditional validation.

**Verification performed:** all files compile; `test_helpers` imports cleanly; every test docstring carries exactly one resolving `Design:` tag; all 153 PRD citations grep verbatim against `PRD.md` (whitespace-normalized); no `skip`/`xfail` markers; no "scaffold" references in generated code.

## Step 6: Generate Implementation — 2026-08-14T00:50:00.000Z

Complete. The implementation for task_1577 (Pay Equity Analysis & Reporting) is finished and verified.

## What was built

`/home/ubuntu/github/CodingPRD/tasks/task_1577_pay_equity_analysis_reporting/workspace/implementation/` — Python + Flask, in-memory store (empty on every boot, no seeding), all 44 endpoints under `/api`:

- **`start.sh`** — guarded install (`if ! python3 -c "import flask"`), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000). Verified: fresh boot in ~3s, empty store, default-port works.
- **Foundation** — `app.py` (blueprints + error handlers), `db.py` (12 collections), `errors.py` (exact 47-error catalog; PRD §5 wins: `ERR_RANGE_DISCLOSURE_REQUIRED` = 422), `response.py` (envelope `meta`/`response_type`/`data`, pagination fields `limit`/`offset`/`total_count`/`has_more` in meta), `middleware.py` (`X-User-ID`/`X-User-Role`, 6 roles), `util.py` (logical clock defaulting to `2026-08-01T00:00:00Z`, Decimal half-up rounding), `validate.py`.
- **Routes** — one module per resource group: clock, studies, snapshots, groups, runs, findings, plans, adjustments, filings, jurisdictions, postings, pipelines, cycles.
- **Services** — `core.py` (record lifecycle with `id`/`created_at`/`updated_at`/`version`, derived aggregates per PRD §2.10, finding-resolution/plan-completion/auto-monitoring auto-transitions, pinned-order clock sweep), `calculations.py` (both `adjusted_pay_gap` variants with staged Decimal rounding, FULL_CLOSURE/PRO_RATA waterfall with deterministic remainder distribution, EEO band aggregation, four-fifths pipeline analytics).

## Key fidelity decisions (all PRD-driven)

- **Validation order** per PRD §2.8: auth → permissions → existence (path+body FK, 404) → OCC (412) → shape (incl. `ERR_RATIONALE_REQUIRED` before state) → state → safety → temporal → constraint → budget last.
- **OCC**: `expected_group_version` on run create, `expected_plan_version` on adjustment decision (evaluated before any state check).
- **Calculations**: per-employee 2dp level deflation before averaging (OLS); exact .5 medians (COHORT_MEDIAN); p-value from the rounded 4dp gap; PRO_RATA floors + cent-at-a-time remainder by (gap DESC, created_at ASC); pipeline ratio computed from rounded rates, strict `< 0.80`.
- **Calendar semantics**: closed study periods (shared boundary conflicts), half-open monitoring windows (touching allowed), inclusive boundaries for due dates / effective dates / posting duration.
- **Cascades**: finalize generates findings in pinned order, flips group LOCKED→ANALYZED, invalidates privilege (PRIVILEGED_FINAL→UNDER_LEGAL_REVIEW, clears pins, +1 review_rounds); clock sweep effectivates adjustments → finding resolution → plan FULLY_COMMITTED/COMPLETED → study auto-MONITORING → cycles DUE; GAPS_PERSIST reopens remediation.

## Verification

~130 scenario checks across 7 smoke scripts, all passing: full lifecycle (study→snapshots→groups→runs→finalize→legal→remediation→plans→adjustments→clock sweep→monitoring→close), both methodologies with hand-verified numbers (OLS staged rounding 6.9444, median even-count 16.6667, PRO_RATA 57/29/14 remainder distribution, pipeline nested rounding 0.4999), privilege-invalidation and rework loops, filing compile/submit-lateness/reopen loop, posting disclosure/spread/duration gates, OCC 412s, segregation of duties, and every error-path boundary in the catalog. Fresh-process boot via `bash start.sh` confirmed clean each time.

## Step 7: Test-Fix Iteration Loop — 2026-08-14T01:45:00.000Z

Two 8-round parallel stability sweeps (`prd-bench-local-run --isolation per-test-server`).

**Sweep 1:** 8/8 rounds failed exactly one test deterministically:
`test_jurisdiction_create_id_input_ignored` — `created_at` was stamped from the
host wall clock (`2026-08-14T01:13:32.834Z`) instead of the logical clock
startup default (`2026-08-01T00:00:00`).

- STEP 1: PRD §2.4 verbatim-covers the rule ("Timestamps stamped by the system —
  such as when a run is finalized, a filing is submitted, or a posting is
  published or closed — always read from this logical clock"; main clause is an
  unqualified universal, `created_at` is a system-stamped timestamp per §2.5).
  Unique derivability holds (a wall-clock implementation falsifies the clause).
- STEP 2: test faithful (fresh server per test, prefix-tolerant assertion).
- STEP 3 implementation fix: added `clock_now_ts()` (logical-clock reading with
  PRD §2.5 three-fractional-digit rendering) in
  `workspace/implementation/util.py`; `services/core.py` `new_record()`/`touch()`
  now stamp `created_at`/`updated_at` from it. Envelope `api_request_timestamp`
  left on wall clock (§2.2 pins format only, no clock source). Existing `_seq`
  tiebreakers keep created_at-ascending sorts deterministic under clock ties.

**Sweep 2:** all 8 rounds passed 86/86. No tests deleted; no test_helpers changes.

**Loop exit: ALL 8 ROUNDS CLEAN.**

## Step 8: Finalize PRD — 2026-08-14T01:35:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1577_pay_equity_analysis_reporting/workspace/PRD_FINALIZED.md` written — a two-sentence minimal patch.

## Summary

**Line counts / delta:** PRD.md 347 lines, PRD_FINALIZED.md 347 lines (0% line-count delta; both edits are in-place sentence appends, 2 lines modified).

**Changes (one bullet per edit):**
- **§2.4 — revise — appended the carve-out "The sole exception is the `api_request_timestamp` carried in every response envelope (§2.2): it is not a resource timestamp and is generated from the host wall clock at response time." — `implementation/response.py:10` (wall-clock `now_ts()` from `implementation/util.py:19-22`), contrasted with `implementation/services/core.py:18,29` (`created_at`/`updated_at` from `clock_now_ts()`).**
- **§2.3 — revise — appended the tie rule "Resources that share an identical creation timestamp — common while the logical clock holds one reading across many creations — are ordered among themselves by creation sequence, the earliest-created record first." — `implementation/routes/helpers.py:50` (`items.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))`), `_seq` from `implementation/db.py:25-30`.**

**The core Step 7 fix itself (created_at/updated_at from the logical clock) required no edit:** Step 7's own STEP 1 concluded §2.4's universal plus §2.5 verbatim-cover it with unique derivability, and `implementation/services/core.py` now conforms — prose kept verbatim per method step 2.

**Per-edit pre-edit search log:**

Edit 1 (§2.4 envelope carve-out):
- (a) Subject: clock source for system-generated timestamps / scope of the §2.4 universal.
- (b) Enumerated paths: `implementation/response.py:7-46` (every envelope — success object, list, error — stamps via `now_ts()`); `implementation/util.py:19-22` (sole wall-clock read; grep for `now_ts`/`datetime.now` confirms no other caller); `implementation/util.py:72-81` (`clock_now_iso`/`clock_now_ts`, logical clock); `implementation/services/core.py:18-20,29` (created_at/updated_at); `implementation/routes/filings.py:108`, `routes/runs.py:109`, `routes/postings.py:104,123` (event stamps, logical clock); `implementation/routes/clock.py:20` (`current_utc` is the reading itself, not a stamp); `implementation/middleware.py` (no timestamps).
- (c) Wording adjustment: added "it is not a resource timestamp" to harmonize with §2.4's existing "the server never falls back to the host's wall clock" (which governs the clock's reading), and used "sole exception" only after grep confirmed `response.py:10` is the single wall-clock site; §2.2's format-only bullet left untouched so nothing narrows the format pin.

Edit 2 (§2.3 list-sort tie-break):
- (a) Subject: ordering of list-endpoint results when `created_at` ties (now the norm under the frozen default clock).
- (b) Enumerated paths: `implementation/routes/helpers.py:50` and verification that all 12 list endpoints (`studies.py:84`, `snapshots.py:107`, `groups.py:66`, `runs.py:86`, `findings.py:28`, `plans.py:66`, `adjustments.py:89`, `filings.py:76`, `jurisdictions.py:47`, `postings.py:62`, `pipelines.py:79`, `cycles.py:70`) route through `list_response`; `implementation/services/core.py:242` (sweep tiebreak — unobservable via the API since the clock-set response carries only `current_utc`, and §2.4 already pins its first two keys verbatim); `implementation/routes/studies.py:151` (`privileged_model_run_ids` ordering — not a list endpoint); `implementation/services/calculations.py:122,131,160` (suggested-allocation internal order — §3.4 already pins the created_at tiebreak; deeper `_seq` refinement left under-determined).
- (c) Wording adjustment: scoped the sentence strictly to "list endpoints" (matching the diff's "created_at-ascending list sorts") so the three non-list orderings above are neither covered nor contradicted; avoided naming `_seq` (internal, stripped by `public()` at `helpers.py:14`) in favor of the observable "creation sequence, earliest-created first."

## Step 9: Complete PRD — 2026-08-14T01:50:00.000Z

## Summary

**Source:** `/home/ubuntu/github/CodingPRD/tasks/task_1577_pay_equity_analysis_reporting/workspace/PRD_FINALIZED.md` (347 lines / 58,702 chars) → `PRD_COMPLETED.md` (347 lines / 62,488 chars). Char delta: **+3,780**. Line count unchanged (all edits are in-paragraph inserts/revisions; no new sections, no new paragraphs).

**Counts:** 23 ambiguity-pins, 1 mismatch-revision (24 edit sites total).

### Changes

- **§2.1** — insert — ambiguity — Header values are whitespace-stripped; empty-after-strip treated as missing — `implementation/middleware.py:33-44`
- **§2.3** — insert — ambiguity — Non-integer/out-of-range `limit`/`offset` rejected with `ERR_INVALID_REQUEST` — `implementation/routes/helpers.py:17-38`
- **§2.3** — insert — ambiguity — Query filters match by exact equality on the named field — `implementation/routes/helpers.py:46-49`
- **§2.3** — insert — ambiguity — `has_more` true exactly when `offset + len(page) < total_count` — `implementation/response.py:28`
- **§2.4** — insert — ambiguity — `to_iso8601` accepts any ISO offset, normalized to UTC at whole-second precision; `current_utc` and action timestamps (`finalized_at`, `submitted_at`, `published_at`, `closed_at`) render whole-second; only `created_at`/`updated_at` use 3-fractional digits — `implementation/util.py:32-46, 58-59`; `implementation/routes/runs.py:109`; `implementation/routes/filings.py:108`; `implementation/routes/postings.py:104,123`
- **§2.5** — insert — ambiguity — `created_at`/`updated_at` stamped from the logical clock; `version` starts at 1 — `implementation/services/core.py:14-24`
- **§2.6** — insert — ambiguity — Missing/null/non-integer `expected_*_version` → `ERR_INVALID_REQUEST`; only an integer mismatch yields 412 — `implementation/routes/runs.py:40-47`; `implementation/routes/adjustments.py:111-118`
- **§3.1** — insert — ambiguity — `protected_classes` stored exactly as supplied, duplicates neither rejected nor removed — `implementation/routes/studies.py:43,66`; `implementation/validate.py:126-133`
- **§3.1** — insert — ambiguity — Same-value compensation patch is a no-op (no `ERR_SNAPSHOT_LOCKED`, no recompute, no version bump) — `implementation/routes/snapshots.py:146-154`
- **§3.1** — insert — ambiguity — Snapshots collection supports `study_id` and `comparator_group_id` filters — `implementation/routes/snapshots.py:106-110`
- **§3.2** — insert — ambiguity — Group creation in a study neither `DRAFT` nor `MODELING` → `ERR_STUDY_INVALID_STATE` — `implementation/routes/groups.py:42-44`
- **§3.2** — insert — ambiguity — Combined comp-field + reassignment patch evaluates criteria against updated field values — `implementation/routes/snapshots.py:176-186`
- **§3.2** — insert — ambiguity — Run creation: group-state check (`ERR_GROUP_INVALID_STATE`) runs first, then study-state check → `ERR_STUDY_INVALID_STATE` — `implementation/routes/runs.py:50-57`
- **§3.2** — insert — ambiguity — Zero reference mean/median defines adjusted gap as 0.0000 (no division) — `implementation/services/calculations.py:88-89, 95-96`
- **§3.3** — insert — ambiguity — `privileged_model_run_ids` ordered by run creation order — `implementation/routes/studies.py:150-152`
- **§3.3** — insert — ambiguity — New finding's `disposition_rationale`/`disposition_by_user_id` are null until disposition — `implementation/routes/runs.py:134-135`
- **§3.3** — revise — mismatch — Disposition state checks: finding-state (`ERR_FINDING_INVALID_STATE`) checked before study-state (`ERR_STUDY_NOT_IN_REMEDIATION`); PRD prose previously ordered study first — `implementation/routes/findings.py:56-62`
- **§3.3** — insert — ambiguity — `disposition_rationale` supplied with `TARGETED`/`MONITORED` is accepted but not stored — `implementation/routes/findings.py:68-71`
- **§3.4** — insert — ambiguity — Adjustment creation: non-`TARGETED` finding → `ERR_FINDING_INVALID_STATE`; plan-state check runs before finding-state check — `implementation/routes/adjustments.py:56-61`
- **§3.4** — insert — ambiguity — Plan full-commitment/completion checks also run after every rejection and every reversal — `implementation/routes/adjustments.py:155, 185`
- **§3.4** — insert — ambiguity — Missing/blank reversal `rationale` → `ERR_INVALID_REQUEST` (not `ERR_RATIONALE_REQUIRED`) — `implementation/routes/adjustments.py:164-166`
- **§3.4** — insert — ambiguity — Suggested-allocation suggestion shape (`employee_snapshot_id`, `gap_finding_id`, `per_capita_gap_cents`, `suggested_cents`), one row per finding-employee pair, ordered by finding creation then snapshot creation — `implementation/services/calculations.py:122-172`
- **§3.4** — insert — ambiguity — `PRO_RATA` remainder ties beyond equal `created_at` broken by creation sequence — `implementation/services/calculations.py:160`
- **§3.5** — insert — ambiguity — Negative `min_posting_duration_days` → `ERR_INVALID_REQUEST` — `implementation/routes/jurisdictions.py:22`
- **§3.5** — insert — ambiguity — `reporting_year` pinned as an integer — `implementation/routes/filings.py:42`
- **§3.5** — insert — ambiguity — `band_rows` emitted band `BAND_A`→`BAND_E`, within band by gender `MALE`, `FEMALE`, `NONBINARY` — `implementation/services/calculations.py:209-217`
- **§3.5** — insert — ambiguity — record-decision `notes` validated as string when present but not persisted — `implementation/routes/filings.py:123-128`
- **§3.5** — insert — ambiguity — Posting salary bounds must be integers ≥ 0 when provided; relative order not validated at creation — `implementation/routes/postings.py:39-40`
- **§3.5** — insert — ambiguity — Zero-floor spread degenerate case: zero when ceiling also zero, else treated as over cap — `implementation/routes/postings.py:96-102`
- **§3.6** — insert — ambiguity — Pipeline record counts pinned as integers, `class_label` non-empty string, violations → `ERR_INVALID_PIPELINE_RECORD` — `implementation/routes/pipelines.py:29-40`
- **§3.6** — insert — ambiguity — `highest_rate_class` null when no positive `count_in`; duplicate `class_label`s: first record's rate wins — `implementation/services/calculations.py:232-245`

**Not changed (verified consistent):** sweep pinned order and boundary semantics, OCC-before-state on adjustment decision, staged rounding rules and per-computation decimal places, band edge lower-inclusive/upper-exclusive boundaries, finding generation order, resolution re-check conditions and its no-op-on-reversal property, auto-monitoring gates and their order, one-live-plan rule, close paths from `PRIVILEGED_FINAL`/`MONITORING`, late-submission strict inequality, publish check order, cycle window half-open overlap, GAPS_PERSIST reopen, all endpoint/role rows in §4, and all error-id→status mappings in §5.
