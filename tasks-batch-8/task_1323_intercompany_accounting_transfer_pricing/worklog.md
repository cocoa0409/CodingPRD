# Worklog — task_1323_intercompany_accounting_transfer_pricing

## Step 1: Create Task Directory — 2026-08-12T22:03:22.387Z

Pre-assigned by pipeline runner; verified `tasks/task_1323_intercompany_accounting_transfer_pricing/workspace/` exists. No index scan or creation performed (per instructions).

## Step 3: Copy Shared Files — 2026-08-12T22:03:41.960Z

Copied `./INSTRUCTION.md` → `tasks/task_1323_intercompany_accounting_transfer_pricing/workspace/INSTRUCTION.md` (done early; independent of scaffold output).

## Step 2: Generate Scaffold — 2026-08-12T22:41:26.364Z

All checks pass. Final state of the deliverables:

## Summary

Generated the complete scaffold for **task_1323_intercompany_accounting_transfer_pricing** purely from the scenario + skill spec (no sibling tasks inspected).

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1323_intercompany_accounting_transfer_pricing/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Design**: compliance/audit primary archetype with ledger-reconciliation secondary; flat topology (peer entities under `/tp`), cyclic state machines (Agreement amendment loop, TrueUpRun recompute loop) plus parallel dimensions on ICTransaction (elimination × settlement) and case-type branching on AuditCase; segregation-of-duties role model (5 opaque roles: GroupTaxAdmin, TaxAnalyst, TaxManager, TransferPricingLead, TreasuryManager — preparer user-id can never approve own work); 2 OCC concurrency rules (study refresh, pool sweep) with `${var}`-pinned expected versions; logical clock endpoint with the mandated `2026-08-01T00:00:00Z` default.

**Counts**:
- 9 entities, 9 state machines, 8 calculations, 10 validations, 50 endpoints, 30 errors, 5 roles
- §1.8: **18 difficulty instances** (9 rules × 2, 0 stubs) — dual-variant (true-up TO_MEDIAN 90000 vs TO_RANGE_EDGE 60000; pool interest AVERAGE 2795 vs CLOSING 4192 cents), combinatorial modes (a) conditional branching and (b) round-per-position-then-residual (1667/1667/1667/4999), cascades of depth 3 and 2, boundary pairs at 750M EUR (inclusive) and p25=400bp margin, half-open date overlap vs integer year-set overlap, consolidated-net-zero and pool zero-sum invariants — all numeric asserts pre-computed as literals
- §1.9: **53 corner instances across all 9 guide sections, of which 4 are `excluded_because:` stubs** (each citing a §1.8 instance by name) and 49 active — every error in the catalog is exercised by at least one instance; the 9 additions closed error-coverage gaps (ERR_AGREEMENT_NOT_IN_EFFECT, ERR_ENTITY_HAS_ACTIVE_AGREEMENTS, ERR_APA_LOCKED, ERR_STALE_BENCHMARK, ERR_YEAR_HAS_OPEN_TRUE_UPS, ERR_CBC_FILING_MISSING, ERR_BOOKS_CLOSED, ERR_CBC_NOT_REQUIRED, ERR_DEFENSE_FILE_EMPTY)

**Lint verdict** (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (482 calls scanned). Also verified: no forbidden race vocabulary, file split honored, all 71 instance names unique across both design files, all stub references resolve, all errors referenced outside the catalog. One scaffold fix driven by §1.9 generation: `submit_response` is now defined from OPENED as well as ACTIVE_PREP so ERR_DEFENSE_FILE_EMPTY is reachable as a business error rather than being masked by a state error.

## Step 4: Generate PRD — 2026-08-12T22:49:25.873Z

All audits pass. The nine "missing" tokens were the path variables, confirmed present inside `{...}` in §4 table paths.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1323_intercompany_accounting_transfer_pricing/workspace/PRD.md` — 296 lines.

**Section list:**
- §1 Introduction (3 paragraphs: business context, system scope, three design realities)
- §2 Global Specifications: 2.1 RBAC (5 roles, header names, all roles' `identity: opaque` translated individually) · 2.2 API Response Structure (verbatim fixed block) · 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, meta fields) · 2.4 Common Resource Properties (`id`/`created_at`/`updated_at`/`version`, cascade increments) · 2.5 The Logical Clock (default 2026-08-01T00:00:00Z, monotonic, `to_iso8601`, backwards → `ERR_INVALID_REQUEST`) · 2.6 Monetary Precision, Basis Points, and Rounding (integer cents/bp, round half-up) · 2.7 Optimistic Concurrency Control (both OCC rules) · 2.8 Validation Order and Error Precedence (10-step explicit ordering, parseable-vs-unparseable nuance) · 2.9 Resource Existence and Identifier Validation (flat topology, left-to-right) · 2.10 Segregation of Duties (all five guarded operations)
- §3 Business Logic (8 subsections): 3.1 Fiscal Years/Legal Entities/CbC threshold · 3.2 Benchmarking Studies/interquartile range · 3.3 Agreement lifecycle (draft→activate→amend cycle→terminate) · 3.4 Transaction booking/matching/elimination (dual independent dimensions) · 3.5 True-Up Runs (compute/recompute/approve/post, 3-link cascade) · 3.6 Documentation Packages · 3.7 Audit Defense/APA · 3.8 Cash Pooling (sweeps/netting/settlement)
- §4 Endpoint Definitions (4-column table, all 50 endpoints, 201/200 rules incl. refresh-201 note)
- §5 Error Code Catalogue (2-column table, all 30 errors)

**Coverage audit (hard contracts):**
- **Contract 1 — Field coverage:** All ~90 required identifiers verified mechanically against backticked tokens: every `entities[].fields[].name` (incl. CashPool position members `balance_cents`/`accrued_balance_day_cents`/`pending_cents`/`interest_cents`/`fee_cents`), every request-body key (`to_iso8601`, `new_markup_bp`, `new_benchmarking_study_id`, `expected_study_version`, `movements`, `expected_cash_pool_version`, `doc_package_id`), every query-param filter name (all seven list filters enumerated in prose), and all 9 path params (inside §4 paths). **PASS.**
- **Contract 2 — Rule coverage:** validations priority order expressed as explicit numbered sequence (§2.8); both OCC rules named with write operation + occ field + `ERR_STALE_VERSION`/412 in stale-version framing only (§2.7); all state-machine transitions with preconditions→error IDs and side effects (incl. version+1 per mutation, cascades, cyclic loops: amendment cycle, true-up recompute loop, attach self-transition, submit-from-OPENED nuance); all 8 calculations in precise no-pseudocode prose passing the reconstruction test (CbCR inclusive 750000000 boundary, provisional price + margin with zero-cost-base special case, nearest-rank percentile with worked n=5 example, true-up with inclusive range membership and TO_MEDIAN/TO_RANGE_EDGE tie-to-low rule, elimination plug invariant with created_at-ascending order, pool interest 85bp/365 per cent-day with both variants, fee allocation round-per-position→sum→residual with largest-abs + entity `created_at` tie-break, zero-sum netting invariant); sibling branches rendered with equal density (amendment approve vs discard, AUDIT vs APA resolve, both interest variants, both true-up methods, submit from OPENED vs ACTIVE_PREP). **PASS.**
- **Contract 3 — §3 path purity:** 420 backticked tokens scanned in §3; 0 path tokens, 0 bare HTTP methods, 0 method+path combos. Endpoints referenced via state-pair framing and role+verb only. **PASS.**

All 30 error IDs appear in §1–§4 prose (trigger conditions scattered near their workflows); §5 table carries IDs and statuses only. The withheld difficulty/corner design files were never opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-12T23:18:29.620Z

Generation complete and fully audited. Final summary:

## Generated artifacts

**`/home/ubuntu/github/CodingPRD/tasks/task_1323_intercompany_accounting_transfer_pricing/test_helpers/`** — `types.py` (9 entity TypedDicts, 11 status/field enums, role enum; all entities carry `common_fields`), `api_client.py` (44 methods covering every `/tp` endpoint incl. clock), `api_errors.py` (30 error IDs + HTTP map registered with the framework), `assertions.py` (per-entity validators, `find_position`, `assert_pool_zero_sum`), `factories.py`, `constants.py` (CbCR threshold 750M, match tolerance 100, pool spread 85bp, min comparables 5, default clock), `test_users.py` (5 opaque-role headers + per-user-id builders for segregation probes), `fixtures.py` (composite helpers: `setup_active_agreement`, `setup_agreement_with_matched_transactions`, run lifecycle `create_computed_run`/`approve_run`/`post_run`, `setup_approved_true_up_with_pool`, `setup_apa_locked_agreement`, study refresh/approve helpers, pool sweep/netting helpers), `__init__.py` barrel.

**`test_suite/`** — `conftest.py` + 8 files: `test_01_fiscal_years_and_cbc_threshold.py` (6), `test_02_envelopes_pagination_and_validation_order.py` (10), `test_03_agreements_lifecycle.py` (12), `test_04_transactions_matching_elimination.py` (10), `test_05_true_up_runs.py` (14), `test_06_fiscal_close_and_benchmark_studies.py` (8), `test_07_doc_packages_and_audit_cases.py` (13), `test_08_cash_pool.py` (12).

## Test counts

- **Queue A (Difficulty): 36 tests** — all 9 rules × 2 instances × 2 tests each (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant: 4 tests per rule).
- **Queue B (Corner): 49 tests** — entities 5, state_machines 7, calculations 4, validations 5, endpoints 3, errors 16, rbac 4, cross_cutting_layers 4, consistency_model 1.
- **Total: 85 tests**, each with exactly one terminal `Design:` tag resolving to a real instance.

## Skipped instances

None. Every non-stub instance passed the two-condition filter (verbatim PRD coverage + unique derivability — all asserted thresholds, error IDs, cascades, rounding orders, and variant arithmetic are stated in PRD §2–§3). The 4 `excluded_because:` stubs were correctly NOT translated; all four cross-references resolve to real queue-A instances (`cbc_below_threshold_carries_no_obligation` → `cbcr_threshold_inclusive_at_750m`; `err_agreement_not_active_on_booking` → `transaction_booking_requires_agreement_active`; `err_year_not_closing_on_approve` → `true_up_approve_requires_fiscal_year_closing`; `cascading_side_effects_layer_coverage` → `true_up_post_cascades_adjustment_elimination_pool_accrual`).

## Coverage audit result

PASS on all checks: 18/18 difficulty instances with ≥2 tests, 49/49 non-stub corner instances with ≥1 test, 0 unresolved/duplicate/stub tags, every docstring carries a verbatim ≥8-word PRD citation window (129 windows grep-verified against PRD.md), no `skip`/`skipif`/`xfail` markers, pyflakes clean, and pytest collects all 85 tests. Literal expected values were copied from the design YAMLs (e.g., true-up 90000/60000, pool interest 2795/4192, fee split 1667/1667/1667/4999) and independently re-verified against the PRD formulas.

## Step 6: Generate Implementation — 2026-08-12T23:18:29.620Z

Implementation complete and verified. Summary:

## File list
`/home/ubuntu/github/CodingPRD/tasks/task_1323_intercompany_accounting_transfer_pricing/workspace/implementation/`
- `start.sh` — guarded install (skips pip when flask importable), `exec python3 app.py`, binds 0.0.0.0:$PORT (default 10000)
- `requirements.txt` — flask>=2.2
- `app.py` — entry point, blueprint registration, ApiError/404/405/500 envelope handlers, RLock serialization
- `db.py` — empty-at-boot in-memory store, logical clock (default 2026-08-01T00:00:00Z, monotonic), id/timestamp/version helpers, internal-key stripping serializer
- `errors.py` — ApiError + all 30 error-id constants verbatim from the catalog
- `response.py` — envelope: `meta{api_request_id, api_request_timestamp[,limit,offset,total_count,has_more]}`, `response_type`, `data`; error body `data{error_id,message}`
- `middleware.py` — X-User-ID/X-User-Role auth, role check, body parsing (malformed short-circuits before state check), FK/path existence, shape validators, date/instant parsing, limit/offset pagination (default 10/0, clamped 1–100)
- `services/calc.py` — all money/bp math in Decimal ROUND_HALF_UP
- `routes/` — clock, fiscal_years, legal_entities, agreements, transactions, true_up_runs, studies, doc_packages, audit_cases, cash_pools

## Endpoint count
50/50 endpoints from the endpoint table implemented (10 route modules; refresh returns 201, creates 201, all other actions/GETs 200).

## State machines implemented (9)
- FiscalYear OPEN→CLOSING→CLOSED with auto-elimination batch (created_at ASC, plug booking, consolidated net stays 0) and close-time staleness cascade (CURRENT studies vintage ≤ year−2 → STALE → pinned agreements flagged `pricing_review_required`)
- LegalEntity ACTIVE→INACTIVE (blocked by ACTIVE/UNDER_AMENDMENT agreements; DRAFT doesn't block)
- Agreement DRAFT→ACTIVE (segregation, entity-active, in-effect window, half-open overlap, CURRENT-study pin + range snapshot) with cyclic ACTIVE↔UNDER_AMENDMENT (pending fields, re-pin on approve, discard path) and ACTIVE→TERMINATED (APA-lock + open-transaction guards)
- ICTransaction dual independent dimensions: UNMATCHED→MATCHED→ELIMINATED (100-cent tolerance) and UNSETTLED→NETTED→SETTLED (system-driven via pool)
- TrueUpRun DRAFT→COMPUTED→(recompute loop)→APPROVED→POSTED with 3-link cascade (adjustment tx → immediate auto-elimination → OPEN-pool pending accrual; skipped when amount 0)
- BenchmarkingStudy DRAFT→CURRENT (nearest-rank IQR, parent supersession), CURRENT→STALE→SUPERSEDED; refresh creates successor DRAFT, bumps parent version (OCC witness)
- DocPackage DRAFT→SUBMITTED→APPROVED→FILED (submitter segregation, books-open, CbC obligation, stale-benchmark local-file guard)
- AuditCase OPENED→ACTIVE_PREP (first attach auto-advance)→SUBMITTED_TO_AUTHORITY→CLOSED_RESOLVED/CLOSED_AGREED branching by case_type; APA resolve locks covered agreements (Jan-1 coverage test)
- CashPool OPEN→NETTING→SETTLED (zero-sum settle guard, position + transaction settling)

## Calculations implemented (8)
CbCR threshold (inclusive 750M), provisional price + margin (round-half-up, zero-cost-base → 0), nearest-rank IQR (rank=⌈p·n/100⌉), true-up (inclusive range, TO_MEDIAN vs TO_RANGE_EDGE with tie-to-low), elimination consolidation (plug = revenue − cost, net invariant 0), pool interest (85bp/365 per cent-day; AVERAGE_BALANCE balance-day accrual vs CLOSING_BALANCE point-in-time), pool fee (round-per-position first in entity created_at ASC order, residual to largest |balance| with created_at tie-break), pool netting (pending + MATCHED/ELIMINATED UNSETTLED tx folds). OCC on study refresh (`expected_study_version`) and pool sweeps (`expected_cash_pool_version`) → 412 ERR_STALE_VERSION.

## Self-check result
Yes — booted via `bash start.sh` three times and smoke-tested. Round 1: 72 checks passed (auth/RBAC, envelope shape, CbC boundary, segregation on all five guarded approvals, overlap rules, match tolerance, elimination, true-up cascade with exact expected numbers (margin 803 bp, amount −4550), pending accrual, doc chain, APA lock, begin_netting figures verified hand-computed: interest ±12, fees 500/500, zero-sum settle rejection). Round 2 after fresh reboot: 18 checks passed (empty store, default clock, not-in-effect, TO_RANGE_EDGE −500, empty-set compute error, CLOSING_BALANCE interest ±23 with zero accrual, fee residual tie-break → 166/167, settle, terminal-state 409, all-role GETs). Round 3 reboot confirmed a pristine empty store — clean per-test-server isolation with no seeding at startup.

## Step 7: Test-Fix Iteration Loop — 2026-08-12T23:32:49.529Z

All 8 rounds pass cleanly: 85/85 in every round.

**Summary**

- **Iterations run:** 2 (two full 8-round parallel sweeps).

- **Tests deleted:** none. Every failing test traced to either an implementation bug or environmental noise; no PRD-silence or unique-derivability violations found.

- **Fixes applied to `test_helpers/`:** none. The two flaky tests (`test_doc_approve_from_draft_rejected`, `test_year_close_flags_pinned_agreement_for_review`) failed only in the runner's setup hook ("API server could not be restarted" after exactly the 15s poll window) — the test bodies never executed. Root cause was host CPU saturation from ~10 co-tenant `prd-bench-entrance` pipelines running concurrent sweeps on the same box, not the tests.

- **Fixes applied to `implementation/`:**
  1. `/home/ubuntu/github/CodingPRD/tasks/task_1323_intercompany_accounting_transfer_pricing/workspace/implementation/routes/studies.py` — `list_studies` called `ok_list(...)` but the import line only brought in `ok_object`, so `GET /tp/benchmarking_studies` (with any filter) raised `NameError` → 500 `ERR_INTERNAL`. Added `ok_list` to the `from response import` line. This was the single deterministic failure (`test_occ_stale_study_refresh_rejected`, failed all 8 rounds); smoke-verified the endpoint returns the correct paginated envelope after the fix.
  2. `/home/ubuntu/github/CodingPRD/tasks/task_1323_intercompany_accounting_transfer_pricing/workspace/implementation/start.sh` — added `export PYTHONDONTWRITEBYTECODE=1` before `exec python3 app.py` to eliminate `.pyc` write contention when 8 rounds reboot the server before every test, hardening boot time against the flaky restart timeouts.

- **Stability evidence:** sweep 1 = 83-84/85 per round (1 deterministic NameError + sporadic restart-timeout noise); sweep 2 after fixes = 85/85 × 8 rounds. Static check (`pyflakes`) over all implementation modules is clean, ruling out other missing-import landmines.

## Step 8: Finalize PRD — 2026-08-12T23:35:00.000Z

Verification complete. PRD_FINALIZED.md is byte-identical to PRD.md — no edits were warranted.

## Summary on exit

**Line counts / delta:** PRD.md = 296 lines, PRD_FINALIZED.md = 296 lines, 0% delta (identical md5 `3068a42d...`). File produced at `/home/ubuntu/github/CodingPRD/tasks/task_1323_intercompany_accounting_transfer_pricing/workspace/PRD_FINALIZED.md`.

**Changes:** none.

**Verification evidence (why no edits were needed), per Step 7 fix:**

**Fix 1 — `implementation/routes/studies.py` missing `ok_list` import.**
- (a) Subject identified: the externally-visible behavior of `GET /tp/benchmarking_studies` (filters, pagination, envelope, roles) — the import fix changed none of it, it only made the already-written handler execute.
- (b) Impl paths enumerated and read: `implementation/routes/studies.py` in full (create/get/list/approve/refresh); the shared list machinery `implementation/middleware.py` (`pagination_params` lines 144-158, `list_page` lines 161-169); the envelope builder `implementation/response.py` (`ok_list` lines 32-39); `implementation/db.py` (`_seq` monotonic creation sequence, lines 13, 54-63, and `public` stripper); plus a grep across all route files confirming every list endpoint (agreements, transactions, true_up_runs, studies, doc_packages, audit_cases, cash_pools) uses the identical `list_page(...)` + `ok_list(...)` pattern, so nothing about the studies listing is special-cased.
- (c) PRD cross-check: PRD §4 endpoint table (line 241) declares the endpoint with all five roles — impl uses `ALL_ROLES` ✓. PRD §3.2 (line 150) declares exactly the optional filters `supersedes_study_id`, `status`, `transaction_type` — impl filters exactly those three, exact-match, only when the query arg is present ✓. PRD §2.3 pins limit default 10 / min 1 / max 100, offset default 0, creation-timestamp-ascending sort, and meta fields `limit`/`offset`/`total_count`/`has_more` — impl matches (clamp in `pagination_params`, `_seq` sort, `ok_list` meta) ✓. PRD §2.2 pins the `meta`/`response_type: "array"`/`data` envelope — impl matches ✓. The PRD already uniquely determines every externally-visible aspect of the fixed endpoint; there is no silence to fill and no mismatch to correct.

**Fix 2 — `implementation/start.sh` `PYTHONDONTWRITEBYTECODE=1`.**
- (a) Subject: server boot behavior. (b) Read `implementation/start.sh` in full and `INSTRUCTION.md` (the boot contract: PORT env, 0.0.0.0 bind, foreground `exec`, respond within 60s). (c) The env var is implementation-internal hardening against `.pyc` write contention under concurrent test reboots; it has no externally-visible API behavior and does not alter the INSTRUCTION.md contract. The PRD governs API behavior only, so there is nothing to pin — adding wording would invent a requirement the PRD has no business stating.

Per the task note, byte-identical output is the legitimate outcome here: both Step 7 fixes are implementation-internal, and the PRD already fully and correctly specifies the behavior the import fix restored.

## Step 9: Complete PRD — 2026-08-12T23:49:11.715664257Z

All 23 diff hunks correspond exactly to my intended edits — no unintended changes. Final verification of counts: PRD_FINALIZED.md = 296 lines / 45,796 chars; PRD_COMPLETED.md = 296 lines / 49,875 chars (+4,079 chars, +0 lines — all changes are inline inserts/revisions, no new sections).

## Summary

**Source:** `PRD_FINALIZED.md` (copied to `PRD_COMPLETED.md`, only the latter edited). Both at `/home/ubuntu/github/CodingPRD/tasks/task_1323_intercompany_accounting_transfer_pricing/workspace/`.

**Counts:** 29 logical changes — 27 ambiguity-pins, 2 mismatch-revisions — applied as 21 inline edit operations across 23 changed lines/paragraphs. Line count unchanged (296 → 296); char delta +4,079.

**Changes** (impl paths relative to `…/workspace/implementation/`):

- §2.3 — insert — ambiguity — `limit` clamped to [1,100] and `offset` to ≥0 rather than rejected; non-integer pagination params → `ERR_INVALID_REQUEST` — middleware.py:144-158
- §2.3 — insert — ambiguity — list filter params are exact-match on the named field — middleware.py:161-169
- §2.4 — insert — ambiguity — `version` starts at 1 at creation — db.py:54-63
- §2.4 — insert — ambiguity — a cascade that would re-set a flag to its already-held value performs no write and no version bump (covers close-cascade and APA-lock no-ops) — routes/fiscal_years.py:113-116, routes/audit_cases.py:154-157
- §2.5 — insert — ambiguity — logical-clock instants rendered ISO 8601 UTC with 3 fractional digits, fraction omitted when exactly zero — db.py:41-51
- §2.7 — insert — ambiguity — OCC check sits immediately after state legality (§2.8 step 4) and before all later categories; missing/non-integer expected-version field → `ERR_INVALID_REQUEST` at the shape step — routes/studies.py:113-125, routes/cash_pools.py:107-140
- §2.8 step 6 — insert — ambiguity — within the step, provider–recipient distinctness is checked before entity-active status, provider before recipient — routes/agreements.py:54-60
- §2.9 — insert — ambiguity — `ERR_NOT_FOUND` fires only for well-formed non-empty string FKs; missing/wrong-typed FKs fall through to the step-10 shape check — middleware.py:58-65
- §3.1 — insert — ambiguity — `country_code`/`functional_currency` stored as supplied, no ISO-registry validation — routes/legal_entities.py:19-21
- §3.2 — insert — ambiguity — new study starts with `supersedes_study_id` null — routes/studies.py:56
- §3.2 — insert — ambiguity — refresh successor inherits `transaction_type`/`region`/`vintage_year` from the refreshed study and records the refreshing user as its `created_by_user_id` — routes/studies.py:126-138
- §3.3 — insert — ambiguity — effective window not validated (`effective_from` may be ≥ `effective_to`; such a window simply never satisfies the in-effect test) — routes/agreements.py:82-83
- §3.3 — insert — ambiguity — activation without a `benchmarking_study_id` (non-COST_PLUS) skips the CURRENT check and activates with all four pinned fields null — routes/agreements.py:182-189
- §3.3 — insert — ambiguity — amendment approval also re-points `benchmarking_study_id` at the replacement study — routes/agreements.py:240-241
- §3.4 — insert — ambiguity — booking minimums: `cost_base_cents` ≥ 1; `provider_revenue_cents`/`recipient_cost_cents` ≥ 0 — routes/transactions.py:46-48
- §3.4 — insert — ambiguity — agreement without `markup_bp` derives both booking figures with markup 0 — routes/transactions.py:49
- §3.5 — insert — ambiguity — true-up run starts with `approved_by_user_id` null — routes/true_up_runs.py:47
- §3.5 — insert — ambiguity — zero total cost base yields `actual_margin_bp` 0 (mirrors §3.4 zero rule) — services/calc.py:32-36,62
- §3.5 — insert — ambiguity — agreement with no pinned range computes `true_up_amount_cents` 0 — services/calc.py:66-67
- §3.5 — insert — ambiguity — zero true-up amount skips the entire posting cascade, including cash-pool position upserts — routes/true_up_runs.py:141-176
- §3.7 — revise — mismatch — "a resolved APA no longer blocks" contradicted the explicit blocking list (which includes `CLOSED_AGREED`); revised to "an agreed APA therefore keeps blocking its covered years" — routes/audit_cases.py:22,43-48
- §3.7 — insert — ambiguity — APA `covered_year_indexes` must be a non-empty integer list; AUDIT may carry an inert optional integer list; `authority_country` stored unvalidated — routes/audit_cases.py:52-60,66
- §3.7 — insert — ambiguity — resolve is defined only from `SUBMITTED_TO_AUTHORITY` (other states → `ERR_INVALID_STATE_TRANSITION`) — routes/audit_cases.py:136-138
- §3.8 — insert — ambiguity — `admin_fee_cents` is a mandatory integer ≥ 0 — routes/cash_pools.py:65
- §3.8 — insert — ambiguity — movement amount carried in `amount_cents` (alias `amount` also accepted) — routes/cash_pools.py:116-120
- §3.8 — insert — ambiguity — position `status` mirrors the pool phase: `OPEN` on creation, `NETTING` once netting begins, `SETTLED` at settlement — routes/cash_pools.py:38,216-217,233-234
- §3.8 — revise — mismatch — the old prose ordered fee allocation (Third) before the pending/transaction fold (Fourth) while defining the fee base as post-fold; renumbered so the fold is Third and fee allocation Fourth, matching impl — routes/cash_pools.py:178-215
- §3.8 — insert — ambiguity — interest is computed on pre-fold balances; positions first created by the transaction fold accrue no balance-days and carry `interest_cents` 0 — routes/cash_pools.py:170-177,192-195
- §3.8 — insert — ambiguity — zero fee base (all balances 0): every `fee_cents` set to 0 and the entire `admin_fee_cents` assigned to the first position in entity `created_at` order — routes/cash_pools.py:203-208

Everything else in the implementation — all 47 endpoints, roles, state machines, formulas (nearest-rank IQR, provisional price, margin, true-up targets with lower-edge tie-break, 85 bp/365 interest, round-per-position-then-residual fee), error catalogue, envelope shapes, and validation precedence — was already uniquely pinned by the PRD and left untouched.
