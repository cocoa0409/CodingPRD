# Worklog — task_1944_facility_condition_assessment_capital

## Step 1: Create task directory — 2026-08-15T02:15:00.000Z

Directory `tasks/task_1944_facility_condition_assessment_capital/` and `workspace/` already existed (created by pipeline launcher); orchestrator verified presence only.

## Step 2: Generate scaffold — 2026-08-15T02:33:00.000Z

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1944_facility_condition_assessment_capital/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design`

**Counts:**
- Entities: 10 (Client, Facility, AssetSystem, Deficiency, CapitalPlan, FundingScenario, PlanLineItem, ProjectBundle, RefreshCycle, ConditionSnapshot)
- Endpoints: 52
- State machines: 5 (CapitalPlan cyclic revision loop + supersede cascade; Deficiency parallel remediation×verification dimensions with compensation; AssetSystem branching fork at REASSESSED; RefreshCycle open/close with auto-successor; FundingScenario CONFIGURED→RUN→SUPERSEDED)
- Calculations: 6 (remaining_useful_life w/ optimistic/pessimistic variants, escalated_cost w/ present-day/year-of-need variants, deficiency_priority_score, facility_condition_index, waterfall_allocation, plan_refresh_health)
- Validations: 14 ordered priority rows; Errors: 14 (all referenced); Roles: 4 (Consultant / FacilityManager / CapitalPlanner / Approver, segregation-of-duties between planner and approver); Concurrency rules: 2 OCC rules (plan create on Facility.version, scenario run on CapitalPlan.version)
- Difficulty-design instances: 18 (exactly 2 per each of the 9 rules, all with the required differentiation: different entity domains, different modes (a) vs (b), different triggers, different error-category pairs, different metrics, different entity pairs, different interval semantics, different conserved quantities)
- Corner-design instances: 40 total (39 active + 1 `excluded_because` stub for ERR_DUPLICATE)

**Design decisions worth noting:**
- Archetype blend: compliance/audit (SoD approval, append-only ConditionSnapshot audit log) + quota/allocation (annual budget waterfall).
- All numeric asserts pre-computed as literals (verified by executing formulas in Python: e.g. escalated 109272700 = 100000000×1.03³, FCI 0.0400/0.0500/0.1000, priority scores 3.00/13.00/8.00/18.00, exact-budget-fit 80000000).
- Waterfall ordering pinned as `priority_score DESC, created_at ASC` — no id/random in any decision.
- Logical-clock endpoint `POST /fca/_clock/set_current_utc` with pinned startup default 2026-08-01T00:00:00Z (drives RUL year math deterministically).
- `scaffold_lint.py` verdict, verbatim: **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (360 calls scanned across 18 + 39 active instances; 52 endpoints, 10 entities.)

One caveat: two mechanical YAML normalizations were applied after the initial write (quoting `?`-suffixed input tokens, colon-containing descriptions, and bracket-containing flow items) — content unchanged, syntax only.

## Step 3: Copy INSTRUCTION.md — 2026-08-15T02:34:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `tasks/task_1944_facility_condition_assessment_capital/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T02:41:00.000Z

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1944_facility_condition_assessment_capital/workspace/PRD.md` — 298 lines.

### Section outline
- **§1. Introduction** (2 paragraphs — pain-point angle + role ensemble)
- **§2. Global Specifications & System-Wide Principles** (9 subsections):
  - 2.1 User and Role-Based Access Control (headers, 4 roles, all four `identity: opaque` translated, SoD pointer)
  - 2.2 API Response Structure (**byte-identical to the fixed verbatim block** — verified)
  - 2.3 Pagination (`limit` default 10 / min 1 / max 100, `offset` default 0, `created_at` ascending, four `meta` fields)
  - 2.4 Common Resource Properties and the Facility Aggregate's Derived Fields (UUID id, ISO-8601 timestamps, version; ConditionSnapshot's missing `updated_at`/`version` called out; CRV/backlog/FCI definitions including the zero-CRV-means-index-0 rule; fresh-facility initial values)
  - 2.5 Money, Precision, and Rounding (integer cents, priority score 2dp half-up, FCI 4dp half-up, escalate-once-never-re-round)
  - 2.6 Optimistic Concurrency Control (both rules, exact `occ_field` names, `ERR_STALE_VERSION`/412, no race framing)
  - 2.7 Validation Order and Nested Resource Retrieval (all 14 validation priorities as an explicit ordered cascade)
  - 2.8 The Server Logical Clock (startup default 2026-08-01T00:00:00Z, no wall-clock fallback, `to_iso8601`/`current_utc`)
  - 2.9 Hierarchical Consistency and Cascading Reconciliation
- **§3. Business Logic & Workflows** (9 subsections, lifecycle-stage grouping): 3.1 Clients/Facilities baseline + recompute; 3.2 Asset inventory + base/pessimistic RUL variants; 3.3 Reassessment + snapshot compensation fork; 3.4 Deficiency findings + priority score formula; 3.5 Dual-axis remediation/verification close-out; 3.6 Capital plan DRAFT→SUBMITTED→APPROVED/REJECTED→DRAFT/SUPERSEDED/ARCHIVED machine incl. SoD and approve-time OPEN→IN_PROGRESS cascade; 3.7 Funding scenarios + full waterfall allocation prose (candidate pool, priority_score-DESC/created_at-ASC sort, per-year budget walk, FUNDED/UNFUNDED, escalation from base year 2026, supersession cascade); 3.8 Bundling/phasing + retirement transitive cascade; 3.9 Refresh cycles + refresh-health read (NO_DATA/STALE/CRITICAL/WATCH/GOOD, inclusive 0.05/0.10 thresholds, stressed backlog)
- **§4. Endpoint Definitions** — 52 rows, 4 columns each, RBAC roles match scaffold exactly
- **§5. Error Code Catalogue** — 14 rows, 2 columns

### Hard contract reports

```
Contract 1 — Field coverage:
- entities[].fields: 47 required, 47 present, 0 missing
- endpoints[].request_body: 31 required, 31 present, 0 missing
- endpoints[].query_params: 15 required, 15 present, 0 missing
- endpoints[].path_params: 1 required, 1 present, 0 missing
Status: PASS

Contract 2 — Rule coverage:
- validations[] priority ordering: 14 checked, 14 expressed as an explicit ordered cascade in §2.7 plus trigger-local prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write op + expected_facility_version / expected_capital_plan_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 19 checked (6 CapitalPlan, 6 Deficiency dual-axis, 4 AssetSystem, 2 RefreshCycle, 1 FundingScenario), all from/to states, preconditions, side effects expressed, 0 missing
- calculations[]: 6 checked (remaining_useful_life incl. pessimistic variant, escalated_cost incl. present-day variant, deficiency_priority_score, facility_condition_index, waterfall_allocation, plan_refresh_health), all formulas/constants/precision expressed without pseudocode, 0 missing
- validations[] conditions: 14 checked, all matchable to their error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 52 endpoints walked; every side effect (derived-field recomputes, version bumps, snapshot appends, supersession and retirement cascades, epoch advancement) expressed, 0 missing
- entities[].fields[] structured content: defaults (false flags, OPEN/UNVERIFIED, DRAFT, CONFIGURED, ACTIVE, initial zeros/epoch 0), enum memberships, integer ranges, nullability of project_bundle_id and note — all reconstructible from prose
- sibling-branch symmetry: accept-vs-reject assessment fork, verify-vs-reject-verification fork, approve-vs-reject plan fork, defer/reopen loop — each branch rendered with equal density
Status: PASS

Contract 3 — §3 path purity:
- backtick tokens scanned: 288
- tokens starting with '/': 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verification: §2.2 block is byte-identical to `section-2.2-response-structure.md`; no fuzzy/approximating words; no pseudocode operators; all 52 endpoints and 14 error IDs in the §4/§5 tables match the scaffold exactly (method, path, RBAC roles, HTTP statuses). The two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

## Step 5: Generate unit tests — 2026-08-15T03:12:00.000Z

## Files written

**test_helpers/** (9 files) — `/home/ubuntu/github/CodingPRD/tasks/task_1944_facility_condition_assessment_capital/test_helpers/`
- `types.py` — 4 role enums + 8 status enums + 10 entity TypedDicts (ConditionSnapshot correctly omits `updated_at`/`version`)
- `api_client.py` — 45 methods, one per PRD §4 endpoint
- `api_errors.py` — 14 error IDs + HTTP map registered via `set_error_http_status_map`
- `assertions.py`, `factories.py`, `constants.py` (weights, FCI bands, BASE_YEAR 2026, RUL caps), `test_users.py` (all 4 roles opaque; `make_*_headers(user_id)` builders for segregation-of-duties control), `fixtures.py` (tiered composites: `setup_facility_with_system`, `setup_funded_plan`, `setup_submitted_plan`, `setup_approved_plan`, `setup_assessed_system`, OCC-safe `create_draft_plan`/`run_scenario`), `__init__.py` barrel

**test_suite/** (8 files) — `conftest.py` + `test_01_facilities_and_inventory`, `test_02_auth_and_rbac`, `test_03_reassessment_and_refresh_cycles`, `test_04_deficiency_workflow`, `test_05_capital_plan_lifecycle`, `test_06_funding_waterfall`, `test_07_retire_bundling_refresh_health`

## Coverage (audited programmatically)

- **Queue A (Difficulty): 36 test functions — 18/18 instances at exactly 2 tests each**
- **Queue B (Corner): 39 test functions — 39/39 non-stub instances at 1 test each**
- 96 pytest items collected after parametrization; every docstring carries verbatim PRD quotes (all 75 verified grep-able against PRD.md) ending in exactly one resolving `Design:` line
- **Skipped:** only the `excluded_because` stub `Corner/errors/err_duplicate_covered` (cross-ref to `refresh_cycle_single_open_interval_per_facility` resolves; not translated per spec). No non-stub instance skipped; no skip/xfail markers anywhere.

## Deviations forced by PRD-first adjudication

1. **`assess_requires_open_refresh_cycle_of_facility`**: the design yaml pins `ERR_PRECONDITION_UNMET`, but PRD §3.3 verbatim says assess without an open cycle "is rejected with `ERR_INVALID_STATE`". Tests assert the PRD's error id (the yaml's would fail every PRD-faithful implementation).
2. **`code_violation_low_severity_rejected`**: yaml pins `priority_score == 9.20` for severity 3 / urgency 4 / accessibility — the PRD §3.4 formula gives 8.40 (1.8+1.6+5). Test asserts 8.40.
3. **OCC version capture bug in recipes**: most recipes capture `facility.version` at creation, then create systems/deficiencies (each bumps `Facility.version` per PRD §2.9) before POST /fca/capital-plans — the stale capture would 412 every plan create. Fixtures re-read the facility immediately before plan creation.
4. **Defer/backlog contradiction contained**: PRD §2.4's backlog formula ({OPEN, IN_PROGRESS}) contradicts §3.5's "deferred items remain in the backlog". Tests assert only the round-trip (OPEN→DEFERRED→OPEN) conservation and transition state-legality — outcomes identical under both readings — never the contested intermediate DEFERRED membership.
5. **`last_assessed_epoch == 1`** after assess in open cycle 1: asserted per the only reading consistent with §3.9's close gate (equal to the closing cycle's epoch).
6. **Reject-assessment restore**: asserts observable restoration (rating 4 / RUL 9) and presence of the assess-time snapshot row, but not an exact snapshot count (PRD is silent on whether registration appends a snapshot).
7. No freelance tests — claims absent from both indices (e.g., supersede-on-submit of a prior APPROVED plan, clock-endpoint behavior) were not invented.

## Step 6: Generate implementation — 2026-08-15T03:12:00.000Z

## Summary

### Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1944_facility_condition_assessment_capital/workspace/implementation/`)

| File | Purpose |
|---|---|
| `start.sh` | Launcher: `cd` to script dir, guarded dep install (`if ! python3 -c "import flask"`), then `exec python3 app.py` |
| `requirements.txt` | `flask>=3.0,<4` |
| `app.py` | Entry point, blueprint registration, envelope-shaped error handlers (ApiError/404/405/500), `app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))` |
| `db.py` | In-memory dicts keyed by id for all 10 entities; starts empty, zero seeding |
| `errors.py` | `ApiError` + the full 14-entry error catalog with exact ids/HTTP statuses |
| `response.py` | Envelope helpers: `meta.api_request_id` (`req_…`), `api_request_timestamp` (ISO 8601, 3 fractional digits), `response_type` object/array/error, pagination fields `limit`/`offset`/`total_count`/`has_more` in meta for lists |
| `middleware.py` | `X-User-ID`/`X-User-Role` auth (401 `ERR_UNAUTHENTICATED`, 403 `ERR_UNAUTHORIZED`), 4 roles |
| `util.py` | Monotonic wall-clock timestamps (deterministic `created_at` ordering), body parsing, typed field validators (bool-safe int checks), pagination param parsing (default 10, clamp 1–100) |
| `clock.py` | Logical clock pinned at `2026-08-01T00:00:00Z` until explicitly set; drives `current_calendar_year()` and `RefreshCycle.opened_at` |
| `services/core.py` | All calculations + derived-field reconciliation + serializers |
| `routes/clients.py`, `facilities.py`, `asset_systems.py`, `deficiencies.py`, `plans.py`, `misc.py` | Route handlers grouped by aggregate |

### Endpoint coverage: 52 / 52
Every PRD §4 endpoint implemented, including the 8 reverse-lookup collections, all 14 state-transition actions, the waterfall run, bundle attach, refresh-health computed read, and `POST /fca/_clock/set_current_utc`.

### Calculation & state-machine coverage
- **Calculations (all 6):** `remaining_useful_life` (base + pessimistic `max(0, rul-2)` variant), `escalated_cost` (Decimal compounding from BASE_YEAR 2026, round-half-up once per item), `deficiency_priority_score` (0.6/0.4 weights + 10/5 bonuses, 2dp half-up), `facility_condition_index` (CRV excluding RETIRED, backlog = OPEN+IN_PROGRESS, 4dp half-up, 0 when CRV=0), `waterfall_allocation` (candidate filter OPEN/DEFERRED, non-RETIRED, in-horizon; sort priority DESC/created_at ASC; per-year budget remainder never re-rounded), `plan_refresh_health` (NO_DATA → STALE → CRITICAL ≥0.10 → WATCH ≥0.05, inclusive thresholds, stressed backlog via pessimistic RUL).
- **State machines (all 5):** CapitalPlan incl. revision loop, supersede-on-submit, SoD via recorded submitter id, archive close-out gate; Deficiency dual-axis remediation/verification with reject-verification compensation; AssetSystem assess/accept/reject (snapshot-revert compensation with pre-assessment fallback)/retire with transitive cascade to PlanLineItem→CapitalPlan (and bundle cost reconciliation); RefreshCycle open/close with epoch auto-advance (`last_assessed_epoch` set to the OPEN cycle's epoch so close can ever succeed); FundingScenario CONFIGURED→RUN with prior-RUN supersession cascade.
- **OCC (both rules):** `expected_facility_version` on plan create, `expected_capital_plan_version` on scenario run → 412 `ERR_STALE_VERSION`; validation cascade follows scaffold priority order (auth → RBAC → path 404 left-to-right → body FK 422 → state 409 → OCC 412 → SoD 403 → code-severity 422 → temporal 422 → shape 400 → duplicate 409 → referential 409 → precondition 409 → fiscal 422).

### start.sh contract
Verified by direct invocation: `bash start.sh` boots in the foreground via `exec`, binds `0.0.0.0:$PORT` (tested on non-default port 18712), responds within ~2s, and a fresh boot returns empty collections (`total_count: 0`) — pure in-memory dicts, no disk/SQLite/seed data. Dependency install is guarded so per-test-server reboots are no-ops.

### Verification
An 80-assertion smoke suite (auth/RBAC, CRUD, both OCC rules, SoD, cycle open/assess/accept/reject/close, waterfall math with exact cent values 45000000/15450000, scenario supersession, bundle attach incl. superseded-plan 409 and cross-plan 422, retire cascade, defer/reopen, verify/reject-verification, clock-driven RUL, pagination meta, 404s) — **all checks passed** on a fresh boot.

## Step 7: Run tests and iterate — 2026-08-15T03:25:00.000Z

## Summary

**Result: all 8 parallel rounds pass — 96/96 tests, 0 failed, 0 errors, in every round.**

- **Iterations run:** 2 eight-round parallel sweeps. Sweep 1: 94/96 in all 8 rounds (same 2 deterministic failures everywhere — no flakiness). Sweep 2 (after fixes): 96/96 × 8 rounds. (One intermediate sweep attempt was killed by host contention before producing results and was re-run; only completed sweeps counted.)

- **Tests deleted:** none. Both failures traced to PRD-covered rules; deletion criteria were not met.

- **Fixes applied to `test_helpers/`:**
  - `test_helpers/fixtures.py` — fixture `remediate_to_corrected`: now reads the deficiency first and skips the `start-remediation` call when the finding is already `IN_PROGRESS`. Why: PRD §3.6 ("On approval, every funded line item's linked deficiency has its `remediation_status` advanced from `OPEN` to `IN_PROGRESS`") means an approved plan's funded finding legitimately starts at `IN_PROGRESS`; the fixture's blind OPEN→IN_PROGRESS leg issued a request the PRD state machine forbids (`start-remediation` requires `OPEN`), so the PRD-faithful implementation correctly 409'd. Behavior for all other call sites (fresh OPEN findings in test_02/06/07) is unchanged.

- **Fixes applied to `test_suite/`:**
  - `test_suite/test_04_deficiency_workflow.py::TestDualAxisCloseOut::test_parallel_dimensions_and_verification_rejection_compensation` — the tail asserted `verify` succeeds after a reject-verification → re-complete cycle. PRD §3.5 verbatim: "Verifying corrected work requires `remediation_status` of `CORRECTED` with `verification_status` still `UNVERIFIED`" — after rejection the pair is `(CORRECTED, REJECTED)`, so verify must fail (scaffold state machine likewise has no exit from `REJECTED`). Rewrote the tail: re-completion still succeeds (remediation axis is independent), the subsequent `verify` now asserts `ERR_INVALID_STATE` (PRD §2.7 check 5), and the PRD-covered "verify appends a ConditionSnapshot" assertion moved to a fresh never-rejected finding driven OPEN → IN_PROGRESS → CORRECTED → VERIFIED on the same system. No assertion was weakened; the mis-translated one was corrected to the PRD-mandated outcome.

- **Fixes applied to `implementation/`:** none. The implementation was PRD-faithful in both failure cases (verify precondition enforcement and approval-time OPEN → IN_PROGRESS advancement); both bugs lived in the test layer.

## Step 8: Finalize PRD — 2026-08-15T03:29:00.000Z

Done. `PRD_FINALIZED.md` created at `/home/ubuntu/github/CodingPRD/tasks/task_1944_facility_condition_assessment_capital/workspace/PRD_FINALIZED.md`.

## Summary

**Result: 0 edits.** Both `<step_7_diff>` items are pure test-layer bugs; every behavior they touch is already uniquely determined by PRD.md and the implementation matches the PRD verbatim at every enumerated path. PRD_FINALIZED.md is a byte-identical copy (diff confirms IDENTICAL).

**Line counts:** PRD.md = 298 lines / 43,973 bytes; PRD_FINALIZED.md = 298 lines / 43,973 bytes; delta = 0 lines, 0.0%.

### Per-item analysis (mandatory search log, applied to both items)

**Item 1 — fixture `remediate_to_corrected` skip of `start-remediation` on already-IN_PROGRESS findings**
- (a) Subject: `remediation_status` transitions into `IN_PROGRESS` (start-remediation endpoint; approval-time advancement).
- (b) Impl paths enumerated (grep over all `*.py` for `remediation_status`/`verification_status`, reads + writes): `routes/deficiencies.py:133-145` (start-remediation requires exactly `OPEN`, else `ERR_INVALID_STATE`); `routes/plans.py:143-170` (approve advances only `OPEN`→`IN_PROGRESS` for funded items, leaves `DEFERRED`/`IN_PROGRESS` untouched, then recomputes facility); plus all other readers/writers — `deficiencies.py:152,163` (complete), `:173,179` (defer), `:188,193` (reopen), `:226` (reject-verification compensation), `plans.py:213` (archive gate), `plans.py:370` (waterfall pool), `asset_systems.py:209` (retire gate), `services/core.py:117,213` (backlog set = OPEN/IN_PROGRESS).
- (c) No wording adjustment: PRD §3.5 ("Starting remediation on an `OPEN` finding…") and §3.6 ("advanced from `OPEN` to `IN_PROGRESS`; deficiencies already `DEFERRED` or already `IN_PROGRESS` are left exactly as they are") pin both behaviors exactly as implemented. The fixture's blind start-remediation leg violated an already-determinate rule — pure fixture bug.

**Item 2 — test_04 verify-after-reject tail corrected to `ERR_INVALID_STATE`**
- (a) Subject: `verification_status` axis — verify/reject preconditions and terminality of `REJECTED`.
- (b) Impl paths enumerated: `routes/deficiencies.py:198-212` (verify requires `remediation_status == CORRECTED` AND `verification_status == UNVERIFIED`, sets `VERIFIED`, appends ConditionSnapshot); `deficiencies.py:215-229` (reject-verification requires the identical precondition pair, sets `REJECTED` + drives remediation back to `IN_PROGRESS`, recomputes facility). Grep confirms no other endpoint in the codebase writes `verification_status`, so `REJECTED` has no exit — entailed, not merely implemented.
- (c) No wording adjustment: PRD §3.5 verbatim — "Verifying corrected work requires `remediation_status` of `CORRECTED` with `verification_status` still `UNVERIFIED`" and "Rejecting corrected work requires the same preconditions but moves `verification_status` to `REJECTED`…" — fully determines the (CORRECTED, REJECTED) → verify-fails outcome the corrected test now asserts. The original test assertion mis-translated an already-determinate rule — pure test bug.

Step_7_diff itself states "Fixes applied to `implementation/`: none… both bugs lived in the test layer," and independent verification above confirms the PRD already covers both sites. Per method step 1, no PRD patch is warranted.

## Step 9: Complete PRD — 2026-08-15T03:36:00.000Z

## Summary

**Source vs target:**
- `PRD_FINALIZED.md`: 298 lines, 43,973 chars
- `PRD_COMPLETED.md`: 300 lines, 47,388 chars (+2 lines, +3,415 chars)

**Counts:**
- Ambiguity-pins: 9
- Mismatch-revisions: 1

**Changes:**

- §2.2 — insert — ambiguity — Pin that HTTP 405 surfaces as `ERR_NOT_FOUND` envelope (with HTTP 405 status) and unhandled exceptions surface as `ERR_INTERNAL` at HTTP 500 — `implementation/app.py:33-40`
- §2.3 — insert — ambiguity — Pin lenient pagination parsing (non-numeric falls back to default, out-of-range limit silently clamped into [1,100], negative offset silently raised to 0) — `implementation/util.py:101-117`
- §2.3 — insert — ambiguity — Pin `total_count` = post-filter pre-pagination length, and `has_more = (offset + len(items)) < total_count` — `implementation/response.py:25-41`, `implementation/services/core.py:51-56`
- §2.4 — insert — ambiguity — Pin that at creation `updated_at == created_at` — `implementation/services/core.py:26-30`
- §2.6 — insert — ambiguity — Pin that missing/non-integer `expected_facility_version` / `expected_capital_plan_version` is rejected with `ERR_STALE_VERSION` (not `ERR_INVALID_REQUEST`) — `implementation/routes/plans.py:54-59, 331-336`
- §2.8 — insert — ambiguity — Pin that clock-set response echoes the verbatim `to_iso8601` string (not normalized), unparseable input → `ERR_INVALID_REQUEST`, and `opened_at` is formatted ISO-8601 UTC with three fractional digits — `implementation/routes/misc.py:87-96`, `implementation/clock.py:18-22`
- §3.3 — revise — mismatch — `last_assessed_epoch` and snapshot epoch are stamped with the **open cycle's epoch**, not the facility's ratified `assessment_epoch` (the two differ while a cycle is OPEN; §3.9's close gate compares against the cycle's epoch) — `implementation/routes/asset_systems.py:142-143`, `implementation/services/core.py:167-171`
- §3.3 — insert — ambiguity — Pin that reject-assessment reverts to the newest snapshot **other than the one this reassessment appended** (which stays in the log); when no prior snapshot exists, falls back to the pre-assessment values stashed at submission time — `implementation/routes/asset_systems.py:135-144, 174-191`
- §3.5 — insert — ambiguity — Pin the verify-time snapshot's epoch (current epoch = open cycle's epoch if present, else ratified `assessment_epoch`), null `note`, and that no facility recomputation is triggered by verify — `implementation/routes/deficiencies.py:207-212`, `implementation/services/core.py:167-171`
- §3.6 — insert — ambiguity — Pin that the submitter's `X-User-ID` is recorded internally only and never serialized on the CapitalPlan resource; supersession of the prior APPROVED plan itself counts as a mutation (refreshes `updated_at`, increments `version`) — `implementation/routes/plans.py:75, 128, 132-139`, `implementation/services/core.py:39-41`
- §3.7 — insert — ambiguity — Pin that the supersession cascade also recomputes `bundled_cost_cents` (and bumps `version`) on any project bundle that was holding a just-REMOVED line item — `implementation/routes/plans.py:339-358`
- §3.8 — insert — ambiguity — Pin that attach does not require the item to be FUNDED (UNFUNDED/REMOVED items attach and contribute 0 until FUNDED), and that re-attaching an item already on another bundle moves it and recomputes the prior bundle's `bundled_cost_cents` — `implementation/routes/plans.py:503-508`
- §3.8 — insert — ambiguity — Pin that the retirement cascade also recomputes `bundled_cost_cents` on any project bundle holding a just-REMOVED line item — `implementation/routes/asset_systems.py:225-243`

**Not changed (verified already pinned or consistent with impl):**
- §2.1 auth / RBAC ordering and opaque `X-User-ID` semantics
- §2.2 envelope shapes, request id format, response_type values
- §2.5 money/rounding contracts (priority score half-up 2dp; FCI half-up 4dp; escalated cost half-up to whole cent once)
- §2.7 the 14-step validation cascade (impl follows it: auth → authz → path → body FK → state → OCC → SoD → severity → year → shape → dup → ref-conflict → precondition → fiscal)
- §3.1-§3.4 core field sets, priority-score formula, guards, and list filters
- §3.6 approval/reject/revise/archive state machine
- §3.7 waterfall ordering (`-priority_score, created_at`), per-year budget walk, escalated-cost formula, ERR_DUPLICATE rule (unreachable in practice due to cascade REMOVing prior items, but PRD wording remains accurate as an invariant)
- §3.9 refresh-health thresholds and `NO_DATA`/`STALE`/`CRITICAL`/`WATCH`/`GOOD` ordering

File path: `/home/ubuntu/github/CodingPRD/tasks/task_1944_facility_condition_assessment_capital/workspace/PRD_COMPLETED.md`
