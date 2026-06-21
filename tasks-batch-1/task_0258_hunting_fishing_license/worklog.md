# Worklog — task_0258_hunting_fishing_license

## Step 1: Create Task Directory — 2026-06-09T00:00:00.000Z

Created `tasks/task_0258_hunting_fishing_license/` and `tasks/task_0258_hunting_fishing_license/workspace/` directly (pre-assigned index 0258; did not scan ./tasks/ to avoid ID contention with concurrent pipelines). Scaffold to be designed at Expert difficulty.

## Step 2: Generate Scaffold (Expert difficulty) — 2026-06-09T00:10:00.000Z

Generated a complete Expert-tier scaffold for the Hunting & Fishing License domain at `tasks/task_0258_hunting_fishing_license/`. All three files pass `scaffold_lint.py` with **VERDICT: clean lint** (362 calls scanned across §1.8/§1.9, all FK reverse-reachability satisfied).

**Complexity profile**: Quota/allocation primary (limited-tag lottery draw) × Compliance/audit secondary; flat entity topology; branching state-machine shape; peer-roles RBAC; immediate consistency. Layers: optimistic concurrency, cascading side effects, dual-variant calculation, rate/threshold triggers.

**SCAFFOLD.yaml** (§1.0–§1.7):
- **10 entities**: Applicant, ResidencyVerification, EducationCertificate, LicenseProduct, SpeciesSeason, DrawPool, DrawApplication, License, HarvestReport, Replacement (all `common_fields: true`)
- **7 state machines**: ResidencyVerification, EducationCertificate, SpeciesSeason, DrawPool (branching fork CLOSED→DRAWN with depth-3 cascade), DrawApplication (SUBMITTED→{AWARDED, UNSUCCESSFUL, WITHDRAWN}), License (ISSUED→VOIDED revert), HarvestReport
- **1 concurrency rule**: OCC on `DrawPool.version` for `execute-draw` (ERR_STALE_POOL_VERSION, 412)
- **4 calculations**: `license_fee` (resident vs non-resident, multiply-then-add rounding pinned), `draw_priority_score` (SQUARED vs LINEAR), `season_bag_budget_remaining` (status-filtered aggregation), `replacement_admin_fee` (3-input conditional with STOLEN short-circuit)
- **14 validations** (priority-ordered, 8 categories)
- **44 endpoints** (23 POST, 21 GET; one `/_clock/set_current_utc` test-driving endpoint)
- **15 error codes**
- **4 roles**: Applicant (entity_backed), LicenseAgent / DrawOfficer / GameWarden (opaque)
- `api_prefix: ""` — flat multi-collection topology

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8): all 9 Difficulty Rules, **2 instances each = 18 total**. All formula-derived asserts pre-computed as literals (fees 4800/11550/2000/2500/0; scores 4 vs 2; bag boundary 2==2 accept / 3>2 reject; age boundary at-12 vs under-12).

**SCAFFOLD_CORNER_DESIGN.yaml** (§1.9): 9 sections, **38 instances** (31 with full test_recipe + 7 `excluded_because:` stubs each citing a real §1.8 instance by name). Covers creation/defaults/computed/system fields, transitions, idempotency, side-effects, calc input-filtering, validation violations, pagination, RBAC denials, OCC happy/stale, immediate-consistency.

Notable: preference-points snapshot (`points_at_entry`) frozen at draw entry enables SQUARED-vs-LINEAR divergence; replacement void→relink cascade conserves season bag budget; tag-pool conservation pins `awarded_count == min(quota, n_submitted)`. All tie-breaks use `created_at ASC`.

## Step 3: Copy Shared Files — 2026-06-09T00:12:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0258_hunting_fishing_license/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-09T00:20:00.000Z

Generated `workspace/PRD.md` — a 247-line prose PRD for the Hunting & Fishing License API (from SCAFFOLD.yaml only; both design-index files confirmed NOT read).

**Structure:**
- **§1 Introduction** — allocation-under-scarcity + strict compliance framing.
- **§2 Global Specifications** — 9 subsections: RBAC (4 roles; Applicant entity-backed, others opaque), §2.2 envelope, pagination, common properties/versioning, nested-reference existence ordering (flat topology, path-then-body), validation precedence, OCC on draw execution, monetary/score precision, logical clock.
- **§3 Business Logic** — 10 subsections by lifecycle: applicant registration & residency, hunter education, catalog, seasons & pools, license pricing, draw entry/withdrawal, OTC issuance, draw execution (depth-3 cascade), harvest reporting & bag budget, replacement.
- **§4 Endpoint table** — 43 endpoints (Method, Path, Description, Authorized Roles).
- **§5 Error catalogue** — 15 errors (Error ID, HTTP Status).

**Hard Contract results:** Field coverage 59/59 PASS; Rule coverage PASS (all 7 state machines, 4 calculations, OCC, validation precedence expressed); Path purity PASS (0 path tokens in §3). No design-index files read.

## Step 5: Generate Unit Tests — 2026-06-09T00:40:00.000Z

Generated complete test infrastructure for the Hunting & Fishing License PRD benchmark task.

**Stage 1 — `test_helpers/`** (9 files): `types.py` (10 entity TypedDicts + 14 status/role enums), `api_client.py` (44 endpoint methods), `api_errors.py` (15 error IDs + HTTP-status map), `assertions.py` (per-entity validators), `factories.py` (10 input-only payload factories), `constants.py` (PRD numeric thresholds), `test_users.py` (4 role headers + `make_applicant_headers` per-instance builder for entity-backed Applicant role), `fixtures.py` (composite setup helpers), barrel `__init__.py`.

**Stage 2 — `test_suite/`** (conftest + 6 domain-named test files): **67 test functions total.**

**Coverage:**
- Test file count: 7 (`conftest.py` + 6 `test_*.py`)
- Total tests: 67
- **Queue A (Difficulty):** 36 tests covering all 18 difficulty instances (each ≥2 tests)
- **Queue B (Corner):** 31 tests covering 30 of 31 non-stub corner instances (7 `excluded_because` stubs correctly not translated)
- **Skipped (PRD-first filter failure):** 1 corner instance — `Corner/endpoints/filtered_list_licenses_by_applicant` (PRD never states `GET /licenses` supports an `applicant_id` filter; no verbatim coverage, not uniquely derivable).

**Verification:** all files byte-compile; package imports cleanly under a framework stub; all 82 PRD citations verbatim in PRD.md; every `api.<method>()` resolves; every docstring ends with exactly one resolvable `Design:` tag; no scaffold/§-reference leakage.

## Step 6: Generate Implementation — 2026-06-09T00:40:00.000Z

Generated a complete Python + Flask implementation at `workspace/implementation/`.

**Files (23 total):** `start.sh` (foreground; reads `$PORT` default 10000, binds `0.0.0.0`, guarded `pip install`, `exec`s server), `requirements.txt` (flask==3.0.3), `app.py`, `db.py` (in-memory `Store`, 10 dicts keyed by UUID, logical clock §2.9), `errors.py` (15-entry catalog), `response.py` (envelope, `req_` ids, 3-digit ISO-8601), `middleware.py` (X-User-ID/Role auth, 4 roles, `require_roles`, 401 before 403), `validation.py` (field validators, pagination, created_at-ASC sort), `serialize.py` (per-entity projections), `services/core.py` (calculations with Decimal ROUND_HALF_UP), `routes/` (11 blueprints).

**Endpoints:** 44 (43 PRD + `_clock` test-driving endpoint).

**Storage:** in-memory only, no seeded data — confirmed via fresh boot (all 10 collections `total_count=0`). No SQLite, no disk persistence, no startup seeding.

**Verified behaviors (4 fresh boots):** auth precedence (401→403→404→409→412→business→400); license pricing (resident/non-resident multiply-round-surcharge, round-half-up edge); draw cascade (SQUARED/LINEAR scoring, priority-DESC/created_at-ASC, AWARDED→mint License + points reset, UNSUCCESSFUL→+1 clamped at 12, OCC stale 412); harvest bag budget (SUBMITTED+ACCEPTED counted, REJECTED released); replacement cascade (admin-fee branches, void+supersede, SUBMITTED-only harvest re-link). Note: re-executing a DRAWN pool returns ERR_INVALID_STATE (priority 4) not ERR_STALE_POOL_VERSION (priority 5), per PRD §2.6.

## Step 7: Run Tests and Iterate — 2026-06-09T01:00:00.000Z

**Iterations run:** 2 (initial sweep + 1 fix sweep).

**Tests deleted (1):**
- `test_execute_draw_stale_version_rejected` (in `test_suite/test_02_draw_scoring_and_fork.py`) — **STEP 1b collapse: ERROR PRECEDENCE SILENCE / PRD self-contradiction.**

  The test executes a draw once (pool → `DRAWN`, version incremented), then re-executes carrying the now-stale pre-draw version, and asserts `ERR_STALE_POOL_VERSION` (412). The implementation returns `ERR_INVALID_STATE` (409). The PRD does not uniquely determine which is correct — it contradicts itself for this exact scenario:
  - **§2.6** (verbatim): *"Fourth comes state validity ... yielding `ERR_INVALID_STATE`. Fifth, on the draw-execution endpoint only, comes the optimistic-concurrency check ... yielding `ERR_STALE_POOL_VERSION`."* A faithful implementer ranks state-validity (4th) ahead of OCC (5th); since the pool is `DRAWN` (a state from which execution is undefined), `ERR_INVALID_STATE` fires first — exactly what the implementation does (`routes/draw_pools.py` lines 112-116).
  - **§2.7** (verbatim): *"a prior execution that moved the pool to `DRAWN` ... legitimately superseding the stale view in which the pool was still `CLOSED` — ... rejected with `ERR_STALE_POOL_VERSION` (HTTP 412) on the stale-version check."* A faithful implementer following this worked example produces `ERR_STALE_POOL_VERSION` for the identical case.

  Two divergent PRD-faithful implementations exist, each backed by a verbatim sentence, so the test goes per the cardinal rule. The implementation was left intact: reordering OCC ahead of state to satisfy this test would directly violate §2.6's explicit "Fourth … Fifth …" precedence, and weakening the assertion (e.g., `validate_error_is_one_of`) is not permitted here because the PRD names two specific contradictory choices rather than a set membership. Also removed the now-unused `validate_error` import from that file.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none — the implementation was already PRD-faithful (state-before-OCC precedence per §2.6).

**Final state:** clean 8-round parallel sweep, 66/66 passing in every round.

## Step 8: Finalize PRD — 2026-06-09T01:20:00.000Z

Produced `workspace/PRD_FINALIZED.md` — minimal patch of PRD.md targeting the lone Step 7 diff item (the §2.6/§2.7 PRD self-contradiction the deleted test exposed).

**Line counts:** PRD.md = 247, PRD_FINALIZED.md = 247 (0% line-count delta; one paragraph revised in place).

**Changes (1):**
- **§2.7 — revise** — Rewrote the OCC worked example so the stale-version scenario no longer claims an already-`DRAWN` re-execution yields `ERR_STALE_POOL_VERSION`. New wording: (1) describes the reachable OCC failure as the pool's `version` advancing while it remains `CLOSED`; (2) states that because the stale-version check is fifth in precedence (after fourth-priority state-validity), a re-execution against an already-`DRAWN` pool returns `ERR_INVALID_STATE`, not `ERR_STALE_POOL_VERSION`. — `implementation/routes/draw_pools.py:113-116`.

Resolves the contradiction in favor of §2.6's precedence, matching the implementation (state check at line 113 fires before version comparison at line 115; OCC path reachable only while `CLOSED`).

**Per-edit pre-edit search log:**
- (a) Subject: §2.7 claim that re-executing an already-`DRAWN` pool with stale version yields `ERR_STALE_POOL_VERSION`; OCC precedence vs state validity on the draw-execution endpoint.
- (b) Impl paths enumerated: `grep -rn "ERR_STALE_POOL_VERSION\|expected_draw_pool_version"` → only `errors.py:21,39` and `routes/draw_pools.py:7,107-116` (sole `execute_draw`). Read `execute_draw` fully (state check 113 before OCC 115; OCC reachable only while `CLOSED`). Cross-checked §3.8 and `close_entries` (87-100, only other version-touching endpoint) — consistent; no other endpoint accepts a version field. Confirmed `touch` advances version on every mutation (§2.4), so a `CLOSED` pool's version can legitimately drift.
- (c) Wording adjustment: phrased reachable failure as version "advanced while still `CLOSED`" without naming a specific competing writer; scoped the `DRAWN`-case statement to "regardless of whether the carried version is stale" to match impl's unconditional state-first ordering and stay consistent with §2.6 and §3.8.

## Step 9: Complete PRD — 2026-06-09T01:40:00.000Z

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-`implementation/` scan, starting from PRD_FINALIZED.md.

**File comparison:** PRD_FINALIZED.md 247 lines / 35,080 chars → PRD_COMPLETED.md 247 lines / 37,713 chars (char delta +2,633; in-paragraph inserts/revisions only, no new sections).

**Counts:** ambiguity-pins **6**, mismatch-revisions **3**.

**Per-change log:**
- §2.1 (RBAC / X-User-ID) — revise — mismatch — PRD claimed ownership checks compare a resource's applicant FK to `X-User-ID`; impl performs no per-applicant ownership enforcement (records `X-User-ID` for audit only; any authorized role may read/act on any resource) — `middleware.py:47-49`.
- §2.4 (versioning) — revise — ambiguity — pinned "initial value" to `1`; first mutation makes it `2` — `db.py:47`.
- §2.7 (OCC on execute-draw) — insert — mismatch — `expected_draw_pool_version` presence/integer-shape validated up front (before existence/state), so a missing/non-integer value yields `ERR_INVALID_REQUEST` even for a nonexistent or non-`CLOSED` pool — `routes/draw_pools.py:108`.
- §2.9 (logical clock) — insert — ambiguity — `to_iso8601` must parse (else `ERR_INVALID_REQUEST`); set-clock returns `200` with `data:{current_utc}` and no common system fields — `routes/clock.py:18-23`.
- §3.1 (registration) — insert — ambiguity — `full_name`/`birth_date`/`declared_state_code` validated only as required non-empty strings; no `YYYY-MM-DD` or two-letter enforcement — `routes/applicants.py:20-22`.
- §3.3 (product retirement) — revise — mismatch — impl does not gate issuance on product `status`, and retire is not state-guarded (re-retire allowed, bumps version) — `routes/products.py:97-101`, `routes/licenses.py:26-64`, `routes/draw_pools.py:148-164`.
- §3.4 (close-entries) — insert — ambiguity — `ACCEPTING` state checked first (`ERR_INVALID_STATE`), then premature-deadline also yields `ERR_INVALID_STATE` — `routes/draw_pools.py:92-97`.
- §3.9 (harvest season-window gate) — insert — ambiguity — when the license's product is bound to no season, the report is rejected with `ERR_SEASON_NOT_OPEN` — `routes/harvests.py:43-48`.
- §3.9 (bag-budget read) — insert — ambiguity — read returns a plain object (no common system fields); for a license whose product has no bound season it returns `season_id` null and `bag_limit`/`counted`/`remaining` all 0 — `routes/licenses.py:106-114`.

**Already uniquely pinned (no change):** license pricing, draw priority scoring (SQUARED/LINEAR), AWARDED/UNSUCCESSFUL fork cascade, tie-break by `created_at` ASC, replacement admin-fee + void→re-link cascade, residency adjudication threshold, validation precedence, pagination, full error catalogue/HTTP statuses.

---

## Pipeline complete

All 9 steps finished. Final 8-round stability sweep: **66/66 passing in every round.** Task directory `tasks/task_0258_hunting_fishing_license/` contains scaffold (3 files), worklog, test_helpers/ (9 files), test_suite/ (6 test files, 66 tests), and workspace/ (INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/).
