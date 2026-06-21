# Worklog — task_0428_title_insurance_escrow

## Step 1: Create Task Directory — 2026-06-20T15:30:47.000Z

Created `tasks/task_0428_title_insurance_escrow/` with `workspace/` subdirectory. Task index 0428 (highest existing was 0427).

## Step 2: Generate Scaffold — 2026-06-20T15:58:00.000Z

Generated all three scaffold artifacts for **task_0428_title_insurance_escrow** (Title Insurance Underwriter & Escrow, First American style), built fresh from the scenario plus the scaffold-generator spec. No sibling tasks were inspected.

**Files written** (all at `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0428_title_insurance_escrow/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design` (§1.9)

**Validation:** `scaffold_lint.py` returns **`VERDICT: clean lint`** — all 453 §1.8/§1.9 calls conform to §1.5 (endpoint/role/payload/captures/OCC checks) and all 11 FKs have reverse-reachability GETs. All three files parse as YAML.

**Design profile (Expert band):** workflow-orchestration + ledger-reconciliation; layers: OCC, cascading side-effects, dual-variant calc, derived-field reconciliation, multi-tenancy.
- 13 entities, 12 state machines, 5 calculations, 10 validations, 50 endpoints, 24 errors, 3 roles (`Agency` entity-backed with own-order ownership; `TitleOfficer`/`Underwriter` opaque), 2 OCC concurrency rules (both on `Order.version`, CREATE-with-supersede).
- api_prefix `/title` (namespace root so flat collection segments are derivable for FK lint); path id placeholders are uniformly `{id}` as the lint's FK check requires.

**Difficulty coverage:** all 9 §0.5 rules × 2 instances = 18, each with the required differentiation (dual-variant calc, combinatorial modes, non-linear machines, depth-3/depth-2 cascades, priority conflicts, boundary checks, cross-entity deps, temporal overlaps, compensating invariants).

**Corner design:** 9 sections, 47 instances (3 `excluded_because` stubs pointing to valid §1.8 instances) covering CRUD, defaults/computed/system/immutable fields, invalid-transition/terminal-lockdown/initial-state, calculation correctness, every error trigger, RBAC denials incl. cross-tenant, FK reverse-reachability, OCC stale-version (both rules), cascade side-effects, multi-tenancy, immediate consistency.

**Key correctness work:** formula-derived asserts precomputed as literals; OCC `expected_order_version` uses fresh-captured `${var}`; enum-status closure holds for all 12 stateful entities; no forbidden concurrency vocabulary; dropped an unreachable commitment-window-overlap rule.

## Step 3: Copy Shared Files — 2026-06-21T00:00:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_0428_title_insurance_escrow/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-21T00:05:00.000Z

Generated the PRD at `workspace/PRD.md` (282 lines) from the scaffold, following the doc-generator spec. Domain: title-insurance underwriter + escrow-trust system (13 entities, 12 state machines, 5 calculations, 50 endpoints, 24 error codes, 3 roles).

**Document structure:** §1 Introduction; §2 cross-cutting (RBAC, fixed response envelope, pagination, common resource properties/identity, hierarchical consistency Cascade A / Cascade B, monetary precision, OCC on escrow order, validation ordering); §3 ten lifecycle/process subsections; §4 50-endpoint table; §5 24-error table.

**Hard Contracts — all three PASS** (verified mechanically): Field coverage 62/62 required present, 0 missing; Rule coverage — validations priority ordering, 2 OCC rejections, 12 state machines, 5 calculations, 24 error IDs, Cascade A/B all expressed, sibling-branch symmetry equal density; Path purity (§3) — 395 backtick tokens, 0 path/method leaks.

**Key fidelity points:** boundary inclusivity exact (closed gap interval, half-open wire window, `>=` expiry); rounding order pinned (agency share first, underwriter by subtraction; reissue factor on un-rounded base rounded once); OCC framed purely in stale-version terms. Withheld DIFFICULTY/CORNER design files were not opened.

## Step 5: Generate Unit Tests — 2026-06-21T00:25:00.000Z

Generated complete test infrastructure and a design-index-driven test suite for `task_0428_title_insurance_escrow`.

### Stage 1 — `test_helpers/` (9 files)
- **types.py** — 13 entity TypedDicts + all status/enum value types. `TitlePlantRecord` correctly omits `updated_at`/`version` (the only `common_fields: false` entity).
- **api_client.py** — `ApiClient(GenericApiClient)` with one method per endpoint (all 47 endpoints incl. the logical-clock setter).
- **api_errors.py** — 24-error `ApiErrorId` enum + HTTP-status map.
- **assertions.py** — per-entity assertions + `assert_escrow_invariants` (balance = deposits − disbursed) and `assert_premium_split_conserves`.
- **factories.py / constants.py / test_users.py / fixtures.py / __init__.py** — fixtures thread Agency identity via `make_agency_headers(agency["id"])` for every ownership-gated call; TitleOfficer/Underwriter opaque shared constants. Composite fixtures cover the pipeline through `CLEAR_TO_CLOSE`, issued policies + remittances, deposits/disbursements, claim/curative chains.

### Stage 2 — `test_suite/` (conftest + 6 test files, 80 tests)
Organized by concern: premium/split, escrow accounting, temporal windows, state machines/cascades, preconditions/precedence, CRUD/OCC/RBAC.

### Coverage (audited programmatically)
- **Queue A (Difficulty):** all **18** instances covered, each ≥2 tests (39 tagged tests).
- **Queue B (Corner):** all **44 non-stub** instances covered ≥1 test each (41 tagged tests); the 3 `excluded_because` stubs correctly NOT translated; all 3 `difficulty_instance` cross-references resolve to real covered Difficulty instances.
- **80 tests = 80 `Design:` lines** (1:1; no untagged/dual-tagged/mis-pointing tags).

### Quality gates passed
- Every PRD citation verified verbatim. Priority-pair conflicts assert PRD-ordered winner (§2.8). No skip/xfail/skipif; no scaffold leakage. All files byte-compile; full suite **collects 80 tests with zero errors**. No gaps skipped.

## Step 6: Generate Implementation — 2026-06-21T00:25:00.000Z

Generated a complete Python + Flask implementation at `workspace/implementation/` (28 files).

### Structure
- `start.sh` — foreground launcher, `exec`s `python3 app.py`, binds `0.0.0.0:$PORT` (default 10000), guarded `pip install`.
- `app.py`, `db.py`, `errors.py`, `response.py`, `middleware.py`, `helpers.py`, `clock.py`, `serializers.py`
- `services/calculations.py` (premium tiers, split, reserve/payout, endorsement charge), `services/domain.py` (touch/version bookkeeping, escrow ledger, ownership checks, cascades)
- `routes/` — one blueprint per resource group (14 groups + clock)

### Key contract points
- Response envelope `meta`/`response_type`/`data`; error `{error_id, message}`; pagination `limit`/`offset`/`total_count`/`has_more` in `meta` (limit default 10, min 1, max 100; offset default 0).
- Auth/RBAC via `X-User-ID` + `X-User-Role`. Agency entity-backed: ownership (`Order.agency_id == X-User-ID`) propagates to every order-reachable resource. Validation priority auth→RBAC→existence→body→OCC→state→referential→temporal→safety→fiscal.
- `version` increments on every mutation. Two OCC-guarded creates (commitment re-issue, disbursement create) require `expected_order_version` (412 `ERR_STALE_VERSION`).
- Calculations use `Decimal` + round-half-up: owner tiered premium (5/4/3 per $1,000), reissue factor 0.60 on un-rounded base rounded once, lender co-issue flat 2500, premium split (round agency share first then subtract), claim reserve (×1.15 capped at coverage), payout (`min(settled, coverage)`), endorsement charge.
- State machines + cascades: Cascade A (order cancel → commitments → policies → remittances/endorsements + exception voids); Cascade B (wire → escrow recompute → auto-close from CLEAR_TO_CLOSE at balance 0). Gap-defect closed interval, wire-window half-open (adjacent allowed), expiry vs logical clock (default `2026-01-01T00:00:00Z`).
- `TitlePlantRecord` carries only `id`/`created_at`. No startup seeding — store boots empty.

### Verification
Booted server via `start.sh`, ran ~40 assertions across the full pipeline; all passed; boots within 60s; `py_compile` clean.

## Step 7: Run Tests and Iterate — 2026-06-21T00:45:00.000Z

- **Iterations run:** 1 (single 8-round parallel sweep).
- **Result:** All 8 rounds passed 80/80 — no flakiness surfaced across the concurrent sweep. (Independently re-verified by orchestrator: rounds 1–8 each `passed=80 total=80`.)
- **Tests deleted:** None. No test failed any PRD-coverage or unique-derivability check because none failed at all.
- **Fixes applied to `test_helpers/`:** None required.
- **Fixes applied to `implementation/`:** None required.

The implementation already satisfies the full test suite under `--isolation per-test-server` stably across 8 concurrent rounds on the first sweep.

## Step 8: Finalize PRD — 2026-06-21T00:45:30.000Z

**SKIPPED.** Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. Per the skip condition, `PRD.md` already determined every behavior the implementation exhibits, so no `PRD_FINALIZED.md` is produced. Step 9 will start from `PRD.md`.

## Step 9: Complete PRD — 2026-06-21T00:55:00.000Z

Full PRD-vs-`implementation/` completeness scan, starting from `PRD.md` (Step 8 skipped). NOTE: the first Step 9 subagent was interrupted by a connection error mid-run after applying 6 edits; a second subagent continued from the partial `PRD_COMPLETED.md` (no re-copy), verified all 6 prior edits against `implementation/`, added 2 more pins, and confirmed no half-applied/truncated sentence.

**Line counts / char-delta:**
- PRD.md: 282 lines, 44,767 chars
- PRD_COMPLETED.md: 282 lines, 47,733 chars (+0 lines, +2,966 chars; 8 lines revised in place, all in-paragraph inserts)

**Counts:** ambiguity-pins 7, mismatch-revisions 0.

**Per-change bullets:**
- §2.1 — insert — ambiguity — Agency GET `/agencies/{id}` self-only (not-found-before-ownership), agency list endpoints as silent filter, `GET /orders` implicit self-scope without `agency_id` — `routes/agencies.py:53-58`, `routes/orders.py:94-95`
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` clamped (not rejected); non-integer → `ERR_INVALID_REQUEST` — `helpers.py:131-147`
- §2.3 — insert — ambiguity — `created_at` ties broken by server-side insertion order (stable sort) — `helpers.py:150-156`, `db.py:34`
- §2.4 — insert — ambiguity — `id` is bare canonical UUID (no type prefix); audit timestamps from logical clock startup default, distinct from envelope `api_request_timestamp` — `db.py:51-53`, `clock.py:12`, `response.py:21-25`
- §3.1 — insert — ambiguity — agency `to_status` equal to current is a no-op → `ERR_INVALID_STATE` — `routes/agencies.py:71-72`
- §3.2 — insert — ambiguity — order `agency_id` must exist (`ERR_NOT_FOUND`), existence checked before self-ownership (real-but-other agency → `ERR_UNAUTHORIZED`) — `routes/orders.py:52-57`
- §3.5 — insert — ambiguity — curative `subject_id` resolves globally by id to any existing `Exception`/`Claim` (not order-scoped); unmatched → `ERR_NOT_FOUND` — `routes/curative_actions.py:43-48`
- §3.6 — insert — ambiguity — policy `commitment_id` must exist and belong to the same order; unknown or cross-order → `ERR_NOT_FOUND` (existence-within-scope, before state/fiscal checks) — `routes/policies.py:50-52`

**Half-applied edit from the interrupted run:** None found; file coherent.

---

## Pipeline Complete

All 9 steps done (Step 8 legitimately skipped). Final state: 80/80 tests pass stably across 8 concurrent per-test-server rounds; `PRD_COMPLETED.md` is the authoritative contract with zero residual PRD silence/mismatch versus `implementation/`.
