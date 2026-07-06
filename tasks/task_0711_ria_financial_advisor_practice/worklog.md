# Worklog — task_0711_ria_financial_advisor_practice

## Step 1: Create Task Directory (pre-assigned) — 2026-06-29T15:10:39.000Z

Pre-assigned output folder used verbatim: tasks/task_0711_ria_financial_advisor_practice. Step 1 index scan SKIPPED per orchestration instructions (ID pre-assigned to avoid contention with 4 parallel pipelines). Directory and workspace/ subdir already existed and are empty.

## Step 2: Generate Scaffold (Expert difficulty) — 2026-06-29T15:33:34.000Z

All three scaffold artifacts written and validated (orchestrator validation; subagent ran async). Expert-band design confirmed:
- SCAFFOLD.yaml (1347 lines): 12 entities, 8 state_machines, 5 calculations, 14 validations, 53 endpoints, 21 errors, 3 roles, concurrency_rules present, complexity_profile (8 keys), response_envelope.
- SCAFFOLD_DIFFICULTY_DESIGN.yaml (1142 lines): top-level key scaffold_difficulty_design (§1.8 depth index).
- SCAFFOLD_CORNER_DESIGN.yaml (1426 lines): top-level key scaffold_corner_design (§1.9 breadth index).
All YAML parses cleanly; design files carry the correct single top-level key each. Expert band targets met/exceeded (entities 10–15 → 12; endpoints 20–32 → 53; errors 18–30 → 21; calcs 3+ → 5; state machines 4+ → 8).

Subagent verbatim summary:

## RIA / Financial-Advisor Practice scaffold — Expert tier — COMPLETE

All three files written to `/home/ubuntu/github/CodingPRD/tasks/task_0711_ria_financial_advisor_practice/`:
- `SCAFFOLD.yaml` (§1.0–§1.7; no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`, §1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`, §1.9)

**`scaffold_lint.py` VERDICT: clean lint** — 53 endpoints, 12 entities, 19 §1.8 + 42 active §1.9 instances, 418 calls scanned; all calls conform to §1.5; all 13 FKs have reverse-reachability GETs.

**Counts (Expert band):**
- **Entities: 12** (Household, FeeSchedule, Client, InvestmentPolicyStatement, Portfolio, Account, FeeRun, FinancialPlan, Goal, RebalanceOrder, Review, ComplianceItem) — band 10–15 ✓
- **Endpoints: 53** (25 POST + 1 PATCH = 26 business/reasoning surface, squarely in the 20–32 band; the 27 GETs are mandatory FK reverse-reachability + entity reads). State transitions are consolidated into one `POST /{collection}/{id}/state` action endpoint per stateful entity.
- **Error codes: 21** — band 18–30 ✓
- **Calculation variants: 5 calculations / 8 variants** (aum_fee_basis_selection arrears|advance, tiered_marginal_fee floor_binds|floor_clear, householding_breakpoint_tier, drift_evaluation, goal_funding_projection projected|actual) — band 3+ ✓
- **State machines: 8** — band 4+ ✓. Non-linear shapes: IPS has a DRAFT↔PROPOSED **cycle**; ComplianceItem has an OPEN↔REMEDIATION **cycle**; FinancialPlan has **parallel dimensions** (lifecycle_status × review_status on one row); RebalanceOrder and Account have **branching + revert**. Plus 1 concurrency rule (OCC on Household.version for fee-run create — true CREATE-with-supersede).

**Design DNA:** primary archetype ledger_reconciliation (arrears vs advance AUM fee) + secondary compliance_audit; flat topology (api_prefix `/`); segregation_of_duties role model (IPS proposer ≠ approver; fee-run builder ≠ finalizer). All nine §0.5 difficulty rules satisfied with ≥2 differentiated instances each (19 total ≥ 18); all formula-derived asserts pre-computed as literals (e.g., fee 431507c, floor-binding 100000c, per-tier-round-then-sum 666c, breakpoint strict-`<` at 100,000,000c → tier 1, drift `>=` 500bps, goal on_track `>=` 10000bps); 0 unresolved grounds references; no forbidden concurrency vocabulary; no duplicate instance names; all `excluded_because` stubs cite valid §1.8 instances.

Note: `worklog.md` and `workspace/INSTRUCTION.md` in the task dir were created by the orchestrator (not me); I left them untouched per instructions.

## Step 4: Generate PRD — 2026-06-29T15:38:53.000Z

PRD.md written and stable (305 lines, 27 markdown section headers). Orchestrator validation: PRD head is a proper RIA Practice API PRD (intro + global specs + RBAC with 3 roles Advisor/ComplianceOfficer/BillingAdmin + logical-clock note). Leak check: grep for design-file tokens (`test_recipe`, `scaffold_difficulty_design`, `scaffold_corner_design`, `excluded_because`) returned 0 — no test-answer leakage.

Subagent verbatim summary:

All 53 scaffold endpoints are represented in the §4 table, and all 21 errors in the §5 catalogue. The PRD is complete and all three Hard Contracts pass.

**Line count:** 306 lines.

**Sections covered:**
- §1 Introduction (3 paragraphs — system goals, segregation-of-duties business context, logical-clock technical constraint)
- §2 Global Specifications — 10 subsections: 2.1 RBAC (all 3 opaque-identity roles translated), 2.2 Response Structure, 2.3 Pagination, 2.4 Common Properties & Logical Clock, 2.5 Nested Retrieval & Reference Integrity, 2.6 OCC on Fee-Run Creation, 2.7 Validation Ordering (all 14 priorities), 2.8 Households/Aggregation/Breakpoint Tiers, 2.9 Fee Precision & Schedule Locking, 2.10 Drift/Mandates/Suitability
- §3 Business Logic — 9 subsections (onboarding, portfolios+IPS, accounts+aggregation+drift, fee runs calc, fee finalization, financial plans+goals, rebalance orders, reviews, compliance)
- §4 Endpoint table (4 columns) and §5 Error catalogue (2 columns)

**Inventory described:** 12 entities; 53 endpoints (matches scaffold exactly); 9 state machines (all transitions/preconditions+error IDs/side-effects in prose); 4 calculations (aum_fee_basis_selection ARREARS/ADVANCE; tiered_marginal_fee with pinned per-slice rounding/proration/floor; householding_breakpoint_tier strict-boundary; drift_evaluation; goal_funding_projection projected/actual); 1 OCC concurrency rule (`expected_household_version` → `ERR_STALE_HOUSEHOLD_VERSION` 412); 21 error codes.

**Hard Contract Reports:** Contract 1 field coverage 81/81 present 0 missing PASS; Contract 2 rule coverage (14 validations, 1 OCC, 9 state machines, 4 calcs, side-effects, sibling-branch symmetry) 0 missing PASS; Path purity (§3 only, 432 backtick tokens scanned, 0 path/method tokens) PASS.

**Confirmation:** Neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was opened, grepped, or referenced.

## Step 5: Generate Unit Tests — 2026-06-29T15:59:07.000Z

Orchestrator validation: test_suite/ = conftest.py + 5 test files; 80 test functions; 80 `Design:` tags (1:1, all tagged); 0 skip/xfail/skipif. test_helpers/ = 9 files.

Subagent verbatim summary:

All test infrastructure is generated and validated. Here is the worklog summary.

Generated complete test infrastructure for task_0711 (RIA / Financial-Advisor Practice, Expert) under design-index-only contract.

**Test files: 5** (`test_suite/`)
- `test_01_fee_calculation.py` — 7 tests (basis ARREARS/ADVANCE, tiered marginal proration, per-tier round-then-sum, floor binds)
- `test_02_aggregation_and_drift.py` — 15 tests (breakpoint tiers, held-away filtering, drift @ tolerance, goal projected/actual variants, derived reconciliation, immediate consistency)
- `test_03_state_machines_and_cascades.py` — 17 tests (IPS revision cycle, plan parallel axes, freeze depth-3 cascade, IPS-approve supersede depth-2, compensating invariants, side-effects, rebalance execute)
- `test_04_validation_and_guards.py` — 28 tests (priority-pair conflicts, cross-entity preconditions, temporal overlap/collision, OCC, validation errors, RBAC denials)
- `test_05_entities_crud.py` — 13 tests (creation/defaults/computed/not-found/required/type, invalid-state & terminal lockdown, goal fund)

**Total test functions: 80** — Queue A (Difficulty) **38** tests covering all **19** instances (every instance ≥2 tests); Queue B (Corner) **42** tests covering all **42** non-stub instances (each ≥1 test).

**Instances SKIPPED: 7** — all are `excluded_because:` corner-design stubs (no `test_recipe`); the cited difficulty-design instance owns each assertion, so per spec they are not translated:
- *cyclic / cascade reuse* (2): `ips_cycle_revision_round_increments`, `account_freeze_cascade_rejects_proposed_rebalance`
- *calc/validation reuse* (2): `fee_arrears_vs_advance_divergence_calc`, `priority_state_beats_segregation_ips_approve`
- *error reuse* (2): `billing_period_overlap_error`, `stale_household_version_error` (note: its `difficulty_instance:` cross-reference points to `cross_cutting/...`, which is a corner section not a difficulty rule — a broken pointer; but the assertion IS covered by the corner OCC instance `occ_stale_household_version_on_fee_run_create`, which I translated, so the gap is harmless)
- *cross-cutting reuse* (1): `rate_threshold_breakpoint_at_exact_boundary`

No difficulty/corner instances were skipped on PRD-first grounds — every non-stub instance had verbatim PRD coverage with unique derivability.

**test_helpers/ files written: 9** — `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py` (plus `test_suite/conftest.py`).

**Quality gates (all pass):** 0 verbatim-citation failures, 0 abbreviated/ellipsis quotes, every test docstring carries exactly one verbatim `Design:` tag resolving to a real instance, 0 orphan tags, 0 `skip/skipif/xfail`, 0 scaffold leakage in emitted code, all modules import cleanly and pytest collects 80 tests. Identity threading uses distinct opaque operator ids for both separation-of-duties checks (fee-run creator≠finalizer, IPS proposer≠approver).

## Step 6: Generate Implementation — 2026-06-29T15:59:07.000Z

Orchestrator validation: implementation/ has app.py + 14 route modules + 4 services + db/errors/response/middleware/util + start.sh + requirements.txt. start.sh reads $PORT, binds 0.0.0.0, exec foreground, guards pip install.

Subagent verbatim summary:

The implementation is complete and verified. Here is the summary for the worklog.

### Source files written (under `workspace/implementation/`)

**Foundation**
- `app.py` — Flask entry point; registers all 13 blueprints, installs error handlers (ApiError → envelope, 404/405 → `ERR_NOT_FOUND`, 400 → `ERR_INVALID_REQUEST`), reads `$PORT`, binds `0.0.0.0`, runs foreground.
- `db.py` — In-memory `Store` (one dict per entity collection keyed by id) + the logical clock; `uuid` id minting and ISO-8601-ms timestamp helper.
- `errors.py` — `ApiError` exception and the complete §5 error-id → HTTP-status catalogue.
- `response.py` — Standard envelope (`meta`/`response_type`/`data`), `req_`-prefixed request id, pagination meta (`limit`/`offset`/`total_count`/`has_more`).
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (`ERR_UNAUTHENTICATED`) and RBAC (`ERR_FORBIDDEN_ROLE`).
- `util.py` — Field parsers/validators (enums, scores, cents, ISO dates), pagination (`ERR_PAGINATION_INVALID`), and `round_half_up` via `Decimal`/`ROUND_HALF_UP`.

**Services**
- `services/common.py` — `stamp_new` (id/created_at/updated_at/version=1) and `touch` (updated_at refresh + version++).
- `services/calculations.py` — The 4 calc rules: tier-index (strict boundary), tiered marginal annual fee (per-slice rounding then sum), fee proration + floor, drift bps, goal funding (projected/actual + annuity).
- `services/recompute.py` — Derived-field reconciliation: household billable/aggregated AUM + breakpoint tier, account drift/rebalance_flagged, goal funded_ratio/on_track. Each recompute is a mutation (bumps version).
- `services/lookup.py` — `get_or_404` (path existence) and `ref_or_422` (body-FK existence).

**Routes (one per resource group)** — `clock`, `fee_schedules`, `portfolios`, `households`, `clients`, `ips`, `accounts`, `fee_runs`, `financial_plans`, `goals`, `rebalance`, `reviews`, `compliance`.

### Endpoint count
**51 endpoints** implemented (matches PRD §4 table): clock(1), fee-schedules(4), portfolios(4), households(6), clients(4), IPS(4), accounts(6), fee-runs(4), financial-plans(5), goals(3), rebalance-orders(4), reviews(4), compliance-items(4). All state machines driven via `/{resource}/{id}/state` with an `action` body field, except `/reviews/{id}/complete`.

### Logical clock
Single in-memory `datetime` on the `Store`, default exactly `2026-03-01T00:00:00Z`, never falls back to wall time. Set via `POST /_clock/set_current_utc` (`to_iso8601`). All "today" comparisons (overdue reviews, lapsed compliance, goal months-to-target, 30-day remediation extension, review `completed_at`/`next_due_date`) read `clock_now`/`clock_date`. `is_overdue` is computed lazily on read.

### In-memory storage
A module-level `db = Store()`; each entity type is a plain dict keyed by string UUID. No SQLite, no JSON-on-disk, no /tmp cache. State exists only for the process lifetime, so every `start.sh` reboot yields an empty store.

### start.sh / no-seeding confirmation
- `start.sh` reads `$PORT` (default 10000), binds `0.0.0.0`, runs `exec python3 app.py` in the foreground, and guards the `pip install` behind `if ! python3 -c "import flask"` to avoid per-test-reboot contention.
- **No data is seeded, preloaded, or hardcoded at startup** — there is no `seed_*` helper and no module-load population of any dict. Verified empirically: a fresh boot returns empty lists for every collection (`total_count: 0`).

### Verification
Booted via `bash start.sh` and ran three smoke suites against fresh boots — **89/89 checks pass** (RBAC, envelope, fee-schedule locking, household aggregation + strict breakpoint tiers, client onboarding/suitability, IPS lifecycle/SoD/supersession/archive, accounts cross-entity gates/freeze cascade/close-block, fee runs OCC/ARREARS+ADVANCE/per-slice tiered+proration+floor/SoD finalize/period overlap, plans parallel axes, goals actual vs projected, rebalance trade-delta/execute/drift collapse, reviews collision/supersession→MISSED/lazy overdue, compliance remediation cycle/archive hash, pagination + validation-priority ordering). One real bug found and fixed during verification (rebalance EXECUTE was not setting status to EXECUTED).

## Step 3: Copy Shared Files — 2026-06-29T15:33:34.000Z

Copied ./INSTRUCTION.md → tasks/task_0711_ria_financial_advisor_practice/workspace/INSTRUCTION.md (1424 bytes).

## Step 7 (RESUME): Integrity Check — 2026-06-30T03:07:00.000Z

Resumed interrupted pipeline. Integrity check PASSED — no regeneration needed:
- (a) start.sh boots cleanly via single prd-bench-local-run round: server launches, no boot-timeout ERRORs, 80 tests collect and execute (48/80 passed, 32 failed, 0 errors).
- (b) pytest --collect-only: 80 tests collected, 0 SyntaxError/collection errors; test_helpers/ (9 files) + test_suite/ (5 files + conftest) import cleanly.
Steps 4/5/6 worklog entries from prior run confirmed coherent against on-disk files. Dominant failure cluster (~20 tests) = "Setup step failed HTTP 409 ERR_CROSS_ENTITY_PRECONDITION (Owning client must be IPS_SIGNED or ACTIVE)" — shared upstream-fixture suspect. Proceeding to Step 7 fix loop. Stale results.*.json deleted.
NOTE: 5 sibling pipelines (tasks 0708-0712) run concurrently on this host; do not mass-kill app.py processes.

## Step 7: Run Tests and Iterate — 2026-06-30T03:40:00.000Z

All 8 rounds of the final two-wave sweep pass 80/80. Clean exit.

**Iterations run:** 4 two-wave sweeps (8 rounds each). Baseline 48/80 → 51/80 → 77/80 → 80/80. No flakiness at any stage (failures were fully deterministic across all 8 rounds; my first union-counting script had a bug — re-confirmed via `status` field that only 32, then fewer, tests failed).

**Tests deleted:** none. Every failing assertion traced to a verbatim PRD sentence and was uniquely derivable; all failures were test-helper/test-fixture bugs or one implementation bug.

**Root cause of the dominant cluster (30 tests):** fixtures activated accounts on clients left at `KYC_VERIFIED`. PRD §3.3 (line 165) requires the owning client be `IPS_SIGNED` or `ACTIVE` to activate an account, and §3.1 (line 149) requires an `APPROVED` IPS to reach `IPS_SIGNED`. The fixtures never signed the IPS, so activation correctly returned `ERR_CROSS_ENTITY_PRECONDITION`. The impl gate was PRD-faithful; the fixtures were missing the onboarding step.

**Fixes applied to test_helpers/ (fixtures.py):**
- Added `ensure_ips_signed(client_id)` — idempotently advances a `KYC_VERIFIED` client to `IPS_SIGNED`; reuses an existing `APPROVED` IPS when present (preserving drift-model setups), else builds a throwaway published portfolio + approved IPS, then `SIGN_IPS`. Why: satisfy the PRD §3.3 activation gate without altering tests' own IPS/drift configuration. (Fixed a follow-on bug: `get_success_data(api.list_ips(...))` already returns the list, not an envelope.)
- `create_active_billable_account` now calls `ensure_ips_signed` before activating. Why: every fixture/test routing through it now reaches a PRD-faithful activatable state.

**Fixes applied to test_suite/ (assertion/setup mistranslations):**
- `test_02_aggregation_and_drift.py::test_goal_on_track_at_exactly_100_percent` and `::test_goal_below_100_percent_not_on_track` — added `expected_status=201` to the `validate_success(api.create_goal(...))` calls. Why: PRD §6 (line 223) verbatim "Operations that create a brand-new resource return `201 Created`"; tests wrongly expected 200.
- `test_02::test_drift_zero_when_no_approved_ips` — value a `PENDING` account instead of activating. Why: PRD-faithfully, an ACTIVE account's client always holds an `APPROVED` IPS (activation⇒IPS_SIGNED⇒approved IPS that only supersedes-to-another-approved), so "ACTIVE account + no approved IPS" is unconstructible; drift recomputes on valuation regardless of account status, so a PENDING account faithfully exercises the no-model→drift 0 rule.
- `test_02::test_aum_visible_immediately_after_activate` — inserted `ensure_ips_signed` before the direct `ACTIVATE`. Why: same gate as above.
- `test_04_validation_and_guards.py::test_rebalance_propose_without_approved_ips_rejected` — value a `PENDING` account instead of `create_active_billable_account`. Why: same unconstructibility; rebalance proposal (PRD §3.7) has no account-status precondition, only the approved-IPS guard, so a PENDING account faithfully triggers `ERR_NO_APPROVED_IPS`.

**Fix applied to implementation/ (services/recompute.py, `recompute_household_aggregation`):** `aggregated_aum_cents` now sums `ACTIVE` **and `FROZEN`** accounts; `billable_aum_cents` restricted to `ACTIVE` + billable + not-held-away. Why: PRD §3.3 (line 167) verbatim — "a frozen account's value is still aggregated into `aggregated_aum_cents` but is no longer billable, so the two figures diverge"; the impl previously dropped frozen accounts from aggregated entirely.

## Step 8: Finalize PRD — 2026-06-30T03:55:00.000Z

PRD_FINALIZED.md produced (305 lines, 0-line delta; 2 intra-line revisions, ~0.66% of lines). Both edits trace to the single implementation/ fix in the Step 7 diff.

**Changes:**
- §2.8 — revise — `aggregated_aum_cents` from "all the household's `ACTIVE` member accounts" to "all the household's `ACTIVE` and `FROZEN` member accounts (a frozen account's value is still aggregated even though it is no longer billable)" — services/recompute.py:26-29
- §3.3 — revise — formula restatement: `aggregated_aum_cents` from "the household's `ACTIVE` accounts" to "the household's `ACTIVE` and `FROZEN` accounts"; `billable_aum_cents` reworded to "the sum ... over the household's `ACTIVE` accounts that are also billable and not held away" (so the FROZEN-inclusive base does not leak into the billable definition) — services/recompute.py:26-33

**Rationale:** The recompute.py fix aligned impl to the §3.3 line-167 prose ("a frozen account's value is still aggregated ... but is no longer billable"), but PRD's two formula restatements (§2.8 and the §3.3 clause) both said "ACTIVE accounts" only, contradicting that prose and the impl. Patched both restatements to match impl. Pre-edit NO-NEW-MISMATCH search confirmed recompute.py is the sole aggregation computation; all 5 account-route callsites invoke it identically; billable rescoped to avoid admitting FROZEN billable accounts.

## Step 9: Complete PRD — 2026-06-30T04:10:00.000Z

PRD_COMPLETED.md produced from PRD_FINALIZED.md (305→305 lines, +1,586 chars). 9 edits: 7 ambiguity-pins + 2 mismatch-revisions (in-paragraph only, no new sections).

**Changes:**
- §2.3 Pagination — insert — ambiguity — list ordering tie-breaks on identical `created_at` by ascending `id` — routes/households.py:78, clients.py:91
- §2.8 Households — revise — mismatch — removed false claim that a `CLOSED` household rejects new fee runs / account additions; impl applies no household-state guard at POST /fee-runs or POST /accounts (the ACTIVE requirement bites only at fee-run CALCULATE and account ACTIVATE); pinned that the close action is unguarded (re-closing returns 200) — routes/fee_runs.py:47-80, accounts.py:42-76, households.py:83-90
- §3.1 Onboarding — insert — ambiguity — suitability-band thresholds on smaller score: <34 CONSERVATIVE, 34–66 MODERATE, ≥67 AGGRESSIVE — routes/clients.py:42-46
- §3.2 IPS approval — insert — ambiguity — auto-spawned IPS_ARCHIVE compliance item has due_date=null — routes/ips.py:142, compliance.py:40-53
- §3.3 Accounts — insert — ambiguity — UNFREEZE with non-ACTIVE household → ERR_INVALID_STATE (409) — routes/accounts.py:163-164
- §3.4 Fee runs — insert — ambiguity — CALCULATE against non-ACTIVE household → ERR_INVALID_STATE (409) — routes/fee_runs.py:136-137
- §3.5 Finalizing — insert — ambiguity — auto-spawned FEE_DISCLOSURE compliance item has due_date=null — routes/fee_runs.py:185
- §3.7 Rebalance — insert — ambiguity — EXECUTE against non-ACTIVE account → ERR_INVALID_STATE (409) — routes/rebalance.py:121-122
- §3.8 Reviews — insert — ambiguity — COMPLETE with non-ACTIVE household → ERR_INVALID_STATE (409) — routes/reviews.py:111-112
- §3.9 Compliance — insert — ambiguity — null-due_date items never lapse (always SATISFY-able while OPEN) and never overdue (FLAG_REMEDIATION → ERR_COMPLIANCE_NOT_DUE); archive_hash = lowercase hex SHA-256 over the four fields joined in order with a single `|` separator — routes/compliance.py:107-117, 131-135

Pipeline COMPLETE. Final state: 80/80 tests pass across all 8 stability rounds; PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md all present.
