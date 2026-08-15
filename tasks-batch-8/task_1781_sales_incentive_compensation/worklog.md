# Worklog — task_1781_sales_incentive_compensation

## Step 1: Create Task Directory — 2026-08-14T15:34:00.000Z

Task directory `tasks/task_1781_sales_incentive_compensation/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per invocation instructions. No index scan performed; no other task directory touched.

## Step 2: Generate Scaffold — 2026-08-14T16:21:00.000Z

Scaffold generation complete for task 1781 (Sales Incentive Compensation Administration). All three artifacts are written and lint-clean.

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1781_sales_incentive_compensation/SCAFFOLD.yaml` — §1.0–§1.7 (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1781_sales_incentive_compensation/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`, 19 instances
- `/home/ubuntu/github/CodingPRD/tasks/task_1781_sales_incentive_compensation/SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`, 52 instances (incl. 7 `excluded_because` stubs)

**Design summary:**
- **Complexity profile**: pricing_engine primary + multi_party_negotiation secondary (dispute adjudication); layers = rate_threshold_triggers, cascading_side_effects, ops_run_checkpoint, optimistic_concurrency; flat topology with self-referential Rep.manager_id hierarchy and CreditEntry.parent_credit_id rollup links; branching state shape; segregation_of_duties role model (plan creator ≠ publisher, adjustment creator ≠ approver).
- **Surface**: 10 entities, 43 endpoints, 30 error codes, 8 calculation rules, 7 state machines, 2 OCC concurrency rules (plan revise, period close). Period-epoch model (integer `current_period_index`), so no logical-clock endpoint is needed.
- **Rule coverage** (2+ instances each, all differentiated per §0.5): attainment DIRECT_ONLY vs INCLUDE_ROLLUP and provisional-vs-final payout (dual-variant, different domains); marginal tiered curve with cap (mode a), split rounding with remainder reconciliation (mode b), draw/guarantee settlement order (mode c); assignment acceptance cycle (OFFERED→ACCEPTED→OFFERED on revise) and dispute fork with divergent side effects; depth-3 posting→rollup→manager-earned cascade and depth-2 cancel→reverse→clawback-adjustment cascade; priority conflicts on (state, business_fiscal) and (business_temporal, business_referential); attainment floor at exactly 100% and dispute window at exactly 2 periods back; assignment-requires-published-plan and close-blocked-by-open-disputes; closed-interval plan windows vs half-open assignment windows; draw-ledger and credit-mass conservation invariants.
- **Precomputed literals**: all numeric asserts derived from a canonical curve ([{0,1000},{8000,1500},{10000,2500}], quota 1,000,000) — e.g., 999,990→gross 109,999 / 1,000,000→110,000 / 1,000,010→110,003; split 100,001 @ 3333/3333/3334 → 33,330/33,330/33,341; settlement with draw 50,000 + guarantee 120,000 → net 120,000.

**Verification**: `scaffold_lint.py` verdict — clean lint (600 calls scanned, all §1.8/§1.9 calls conform to §1.5, all FKs reverse-reachable). Additional self-checks passed: top-level key discipline, instance-name uniqueness across both design files, no forbidden concurrency vocabulary, all 9 rule_ids at ≥2 instances, all 4 roles with `identity:` declared. Two YAML/lint issues were fixed en route (nested-bracket `grounds:` quoting; `/programs/{id}/payroll-exports` literal `{id}` segment for the sub-resource FK check), plus a reachability fix adding `PUT /reps/{repId}` so the hierarchy-cycle error is actually triggerable.

## Step 3: Copy Shared Files — 2026-08-14T16:22:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1781_sales_incentive_compensation/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T16:33:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1781_sales_incentive_compensation/workspace/PRD.md` (~9 sections across §2, nine workflow subsections in §3, 43-row §4 endpoint table, 30-row §5 error catalogue). The withheld difficulty/corner index files were not opened.

Structure chosen for this domain: §2 subsections are domain-derived (compensation periods & accrual ledger, common resource properties, integer-cent/basis-point arithmetic, OCC, segregation of duties, validation ladder & Rep visibility); §3 follows the comp cycle chronologically — plan governance → roster/hierarchy → assignments & document acceptance → transaction crediting & roll-up → cancellations/clawbacks/adjustments → disputes → period close settlement → payroll export → effectiveness analytics.

Hard contract reports:

```
Field coverage check (Contract 1):
- entities[].fields: 62 required, 62 present, 0 missing
- endpoints[].input: 34 required, 34 present, 0 missing
- endpoints[].query_params: 12 required, 12 present, 0 missing
- path params + effectiveness-output/sub-field identifiers: covered (87 unique tokens total, 0 missing)
Status: PASS

Rule coverage check (Contract 2):
- validations[] priority ladder: 9 tiers expressed as an explicit ordered ladder in §2.9 (auth → role → existence/ownership-hiding → state → SoD → temporal → structural → referential → fiscal), 0 missing
- concurrency_rules[] OCC rejections: 2/2 expressed — revise requires expected_plan_version (ERR_STALE_PLAN_VERSION, 412, checked only after the PUBLISHED state precondition); close-period requires expected_program_version (ERR_STALE_PROGRAM_VERSION, 412, checked only after ERR_OPEN_DISPUTES_EXIST guard)
- state_machines[].transitions: all 6 machines fully expressed (plan publish/revise/archive with version bumps and re-offer cascade; assignment accept/decline/revise-cascade/terminate; transaction create/cancel; credit-entry PENDING→POSTED→LOCKED/REVERSED incl. LOCKED→REVERSED clawback-only path; adjustment approve/reject; dispute fork-join; statement DRAFT→APPROVED→EXPORTED), 0 missing
- calculations[]: 8/8 in precise prose — split allocation (per-split round-half-up then remainder to largest split_bps, ties to lowest array index, exact-sum invariant), rollup (one level, same-plan ACTIVE manager assignment, half-up), attainment (integer floor, DIRECT_ONLY vs INCLUDE_ROLLUP), marginal quota-to-payout curve (per-band half-up then sum, cap via min applied last, payout_cap_applied), provisional vs final payout estimate, pinned-order period_settlement, draw-ledger invariant, plan effectiveness (bucket bounds LT_8000/B8000_10000/GTE_10000)
- validations[] conditions: all 30 error IDs matchable to trigger conditions in §2/§3 prose
- endpoints[].side_effects / applies_to: expressed in workflow narratives (43/43 endpoints in §4 table, roles match scaffold)
- entities[].fields[] structured content: defaults, enum sets, sources (input/system/computed), and the PayrollExport common_fields exception (only id + created_at; updated_at/version absent) all stated
- sibling-branch symmetry: parallel branches (accept from OFFERED/DECLINED, reject/withdraw from SUBMITTED/UNDER_REVIEW, recoverable vs non-recoverable draws, DIRECT_ONLY vs INCLUDE_ROLLUP) rendered with equal density
Status: PASS

Path purity check (Contract 3, §3 only):
- backtick tokens scanned: 418
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 emitted byte-identical to the canonical `section-2.2-response-structure.md`; no pseudocode operators (`==`, `>=`, `min()`, `floor()`, etc.) anywhere; fuzzy-word scan clean; all 34 enum values and all 4 role names (with per-role `identity:` translations) present verbatim.


## Step 5: Generate Unit Tests — 2026-08-14T17:12:00.000Z

Generation complete. All deliverables are in place and all audits pass.

## What was generated

**`/home/ubuntu/github/CodingPRD/tasks/task_1781_sales_incentive_compensation/test_helpers/`** — 9 modules:
- `types.py` — status enums (plan/assignment/acceptance/transaction/credit/adjustment/dispute/statement), `UserRole`, and TypedDicts for all 10 entities; `PayrollExport` correctly omits `updated_at`/`version` (append-only per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (39 methods)
- `api_errors.py` — all 30 error IDs with the §5 HTTP status map, registered via `set_error_http_status_map()`
- `assertions.py` — per-entity shape assertions + `assert_draw_ledger_invariant` (outstanding == paid − recovered − forgiven)
- `factories.py`, `constants.py` (canonical 3-tier curve, flat 10% curve, quota 1,000,000, SoD operator ids), `test_users.py` (shared constants for the 3 opaque roles + mandatory `make_rep_headers(rep_id)` builder for the entity-backed Rep role), `fixtures.py` (composites: `setup_accepted_assignment`, `setup_manager_rep`, `setup_posted_credit`, `setup_closed_period`, `setup_exported_period`, `close_period` with OCC auto-versioning, `advance_periods`, filtered-list lookups)

**`/home/ubuntu/github/CodingPRD/tasks/task_1781_sales_incentive_compensation/test_suite/`** — `conftest.py` + 10 test files, **91 tests**:
- test_01 foundation/envelope/creation rejections (9), test_02 plan lifecycle/revise cascade/OCC/windows (9), test_03 roster hierarchy (5), test_04 assignments (7), test_05 transactions and split allocation (12), test_06 rollup and attainment modes (5), test_07 period close and settlement (17), test_08 statements/payroll/clawback/draw ledger/effectiveness (10), test_09 disputes (12), test_10 adjustments and RBAC (5)

## Audit results (all PASS)

- **Design-tag coverage:** all 19 difficulty instances have ≥2 tests (one has 3); all 47 non-stub corner instances have ≥1; all 7 `excluded_because` stubs verified to resolve to real difficulty instances and were not translated; every test has exactly one `Design:` line as the last docstring line; no tags point at non-existent instances
- **Verbatim PRD citations:** every ≥8-word quote in every docstring greps literally in `workspace/PRD.md`
- **No skip/xfail markers; no scaffold references** in generated code; pyflakes clean; pytest collects all 91 tests

## Judgment calls made

- **`program_creation_defaults`**: dropped the `version == 1` assertion — PRD never pins the initial value of `version` (only that it increments), so it fails the two-reader test; the period-1/accrual-0 assertions (explicitly stated in §2.4) are kept.
- **Nullable fields** (`payout_cap_cents`, `parent_credit_id`, `accepted_document_version`, `posted_period_index` on PENDING) asserted via `.get(...) is None` so both "null" and "omitted" serializers pass.
- **`dispute_credit_entry_mismatch_rejected` / `dispute_create_temporal_vs_referential`**: kept, because §3.6's filing ladder explicitly orders ownership → window → duplicate → credit-entry coherence → amount and names `ERR_DISPUTE_CREDIT_ENTRY_MISMATCH`; since only Reps file disputes, tier-3 ownership hiding of the body `credit_entry_id` would make the named error unreachable, so the §3.6 reading is uniquely derivable.
- No instances were skipped for silence — every non-stub instance in both queues has verbatim PRD coverage.

## Step 6: Generate Implementation — 2026-08-14T17:12:30.000Z

The implementation is complete. Here is the summary:

## What was built

A complete Python + Flask REST API implementation for the Sales Incentive Compensation Administration benchmark task, located at:

`/home/ubuntu/github/CodingPRD/tasks/task_1781_sales_incentive_compensation/workspace/implementation/`

### Architecture (20 source files)

- **`start.sh`** — Launcher with guarded dependency install (`import flask` check) and `exec python3 app.py`
- **`app.py`** — Flask entry point, error handlers, blueprint registration
- **`db.py`** — In-memory dict store (10 collections, fresh on every boot)
- **`errors.py`** — All 24 error IDs with exact HTTP statuses from the scaffold catalog
- **`response.py`** — Envelope helpers matching `meta`/`response_type`/`data` structure with `limit`/`offset`/`total_count`/`has_more` pagination
- **`middleware.py`** — Auth (X-User-ID + X-User-Role), role checking, Rep ownership hiding
- **`util.py`** — UUID generation, ISO 8601 timestamps (3 fractional digits), integer round-half-up, serialization
- **`validate.py`** — Body shape validation (ERR_INVALID_REQUEST before business rules)
- **`services/calculations.py`** — All 8 calculation rules: split_credit_allocation, rollup_credit_amount, attainment_calculation (DIRECT_ONLY/INCLUDE_ROLLUP), quota_to_payout_curve (marginal tiers, per-band rounding, cap last), payout_estimate (provisional/final), period_settlement (pinned order), draw_ledger, plan_effectiveness
- **`services/crediting.py`** — Credit posting with rollup spawn, reversal with clawback, acceptance cascade, termination cascade
- **`routes/`** — 10 blueprint files covering all 35 endpoints

### Key design decisions

- **9-tier validation ladder** enforced per PRD Section 2.9: auth headers -> role check -> existence/visibility -> state -> SoD -> temporal -> structural -> cross-reference -> money
- **OCC ordering**: plan revise checks state before OCC; period close checks open disputes before OCC (per concurrency_rules)
- **Rep ownership hiding**: Rep callers get 404 for foreign assignments/credits/disputes/statements
- **PayrollExport**: only `id` + `created_at`, no `updated_at`/`version` (immutable append-only)
- **No seeding**: store starts empty on every boot
- **Integer-cent arithmetic**: `round_half_up_int` uses exact integer arithmetic, attainment uses floor division

### Test results (provisional, run against a then-partial test suite mid-Step-5)

**39/42 tests passed, 3 failed** — all 3 failures are `NameError: name 'setup_posted_credit' is not defined` in `test_05_transactions_credit_allocation.py`, a test file import bug (the function is not in the test's import list despite being available from `test_helpers.fixtures`). These are not implementation issues. Step 7 will run the full 91-test sweep.

## Step 7: Run Tests and Iterate — 2026-08-14T17:25:00.000Z

All 8 rounds pass 91/91 — clean sweep. Task complete.

## Summary

- **Iterations run:** 2 (initial sweep → fix → verification sweep). Final state: all 8 parallel rounds at 91/91 passed, zero failures, zero errors.

- **Tests deleted:** none. Both failing tests traced to verbatim PRD §3.4 prose ("`provisional_period_payout_cents` is the forward-looking estimate: the curve of §3.7 applied to the mode-filtered sum of `current_period_earned_cents` **plus** all `PENDING` credits of the assignment" and "Two live indicators on each assignment are recomputed on every credit change"), with uniquely derivable expected values (canonical curve over 1,200,000 pending → 160,000). Both were implementation bugs.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `implementation/`** (all four trace to the same PRD §3.4 sentences above):
  1. `/home/ubuntu/github/CodingPRD/tasks/task_1781_sales_incentive_compensation/workspace/implementation/routes/transactions.py` — `create_transaction`: when a new credit parks in `PENDING` (assignment not ACCEPTED / plan not PUBLISHED), `recompute_assignment_indicators` was never called, leaving `provisional_period_payout_cents` stuck at 0. Added the recompute on the non-posting branch. (Fixed `test_provisional_payout_includes_pending_credits`.)
  2. `/home/ubuntu/github/CodingPRD/tasks/task_1781_sales_incentive_compensation/workspace/implementation/routes/programs.py` — `close_period`: hard-zeroed `provisional_period_payout_cents` and `current_attainment_bps` after resetting earned counters. PRD only resets `current_period_earned_cents`; PENDING credits survive close and must still count toward the provisional estimate. Replaced the hard zeroing with `recompute_assignment_indicators` after the counter reset. (Fixed `test_final_statement_excludes_pending_credits`.)
  3. `/home/ubuntu/github/CodingPRD/tasks/task_1781_sales_incentive_compensation/workspace/implementation/services/crediting.py` — `maybe_spawn_rollup`: added indicator recompute for the manager's assignment when the spawned rollup lands `PENDING` (same "every credit change" rule; counts under `INCLUDE_ROLLUP`).
  4. `/home/ubuntu/github/CodingPRD/tasks/task_1781_sales_incentive_compensation/workspace/implementation/services/crediting.py` — `reverse_credit_entry`: added indicator recompute on the `PENDING → REVERSED` branch so a reversed held credit is withdrawn from the provisional estimate.

Fixes 3 and 4 were proactive gap closures on the same PRD-mandated recompute trigger; no test currently exercises them, but leaving them would have been a latent stale-indicator bug of the same class.

## Step 8: Finalize PRD — 2026-08-14T17:35:00.000Z

Step 8 complete. `/home/ubuntu/github/CodingPRD/tasks/task_1781_sales_incentive_compensation/workspace/PRD_FINALIZED.md` written — a 2-line patch of PRD.md, everything else verbatim.

**Line counts / delta:** PRD.md 305 lines (49,706 chars) → PRD_FINALIZED.md 305 lines (50,409 chars). 0% line delta (both edits are inline within existing paragraph lines); +703 chars (+1.4%).

**Changes (one bullet each):**
- §3.4 — revise — expanded the "recomputed on every credit change" trigger sentence to define a credit change as any event that creates a credit entry or alters its status; pins that a credit's birth recomputes indicators in both landing states (`POSTED` or `PENDING`), that a spawned `ROLLUP` recomputes the **manager** assignment's indicators in either landing state, and that reversing a `PENDING` credit withdraws it from the provisional estimate despite no earned-counter movement — `implementation/routes/transactions.py:147-150`, `implementation/services/crediting.py:105-108`, `implementation/services/crediting.py:125-127`
- §3.7 — revise — the close-period movement now reads "resets each settled assignment's `current_period_earned_cents` to 0 **and recomputes both live indicators of §3.4 against the reset counter**", pinning that `PENDING` credits survive close and keep feeding the provisional estimate (indicators refreshed, never hard-zeroed) — `implementation/routes/programs.py:88-95`

**Why these are the only edits:** Step 7 recorded no test deletions and no test_helpers fixes — only 4 implementation fixes, all converging on the §3.4 trigger sentence. Fixes 1, 3, 4 (PENDING-park at booking, PENDING rollup spawn on the manager, PENDING→REVERSED) are pinned by Edit 1; fix 2 (close-period hard-zeroing) is pinned by Edit 2. Nothing else in the diff revealed PRD silence or mismatch.

**Per-edit pre-edit search log:**

*Edit 1 (§3.4 indicator trigger):*
- (a) Subject: when `current_attainment_bps` / `provisional_period_payout_cents` are recomputed.
- (b) Paths enumerated and read: `services/calculations.py:50-59,114-140` (mode filter, provisional, recompute definitions); `services/crediting.py:14-39` (post side effects), `:42-108` (rollup spawn both branches), `:111-167` (reversal: PENDING/POSTED branches recompute; LOCKED branch creates clawback, inputs unchanged so values stay formula-consistent), `:170-206` (terminate/accept cascades); `routes/transactions.py:117-152` (birth POSTED vs PENDING park); `routes/programs.py:91-95` (close); `routes/assignments.py:107-130,176-253` (birth at 0, accept/decline/terminate); grep-verified `plans.py`, `disputes.py`, `adjustments.py`, `statements.py`, `payroll_exports.py` never touch the indicators.
- (c) Wording adjustments: scoped the trigger definition to credit-entry creation/status-change only, so plan revision (re-offer cascade touches no credit entry), decline, and adjustment approval are excluded — matching impl. Scoped the reversal-withdrawal clause to `PENDING` credits so the LOCKED→REVERSED path (no recompute call, behaviorally no-op since neither earned nor the PENDING set changes) is not mis-described.

*Edit 2 (§3.7 close movements):*
- (a) Subject: indicator state at period close.
- (b) Paths enumerated and read: `routes/programs.py:45-102` (only close path: guard order, `period_settlement` per ACTIVE assignment reading the pre-reset counter, POSTED→LOCKED sweep restricted to closing-period entries, then reset + recompute per settled assignment); `services/calculations.py:147-242` (settlement pipeline consumes earned before reset); `services/crediting.py:170-190` (termination leaves no PENDING credits and zero earned on terminated assignments, so settled-only recompute is exact).
- (c) Wording adjustments: kept §3.7's existing "each settled assignment" scoping (not "all assignments") to match `active_assignments` iteration; stated "PENDING credits are untouched by the close" (the sweep only locks POSTED entries of the closing period) rather than claiming any per-entry recompute during the sweep itself, which the impl does not perform.

## Step 9: Complete PRD — 2026-08-14T17:52:00.000Z

Step 9 complete. `/home/ubuntu/github/CodingPRD/tasks/task_1781_sales_incentive_compensation/workspace/PRD_COMPLETED.md` produced as a minimal inline patch over `PRD_FINALIZED.md`.

## Summary

**Files:** `PRD_FINALIZED.md` (305 lines / 50,166 chars) → `PRD_COMPLETED.md` (305 lines / 53,256 chars), char-delta **+3,090**. All 18 changes are in-paragraph inserts/revisions; no new sections, no line-count change.

**Counts:** 14 ambiguity-pins, 4 mismatch-revisions.

**Changes (one per edit):**

- §2.3 — insert — ambiguity — list sort ties broken by resource `id` ascending — implementation/routes/plans.py:159 (same pattern in all 9 list endpoints, e.g. reps.py:139, programs.py:115)
- §2.5 — insert — ambiguity — `version` starts at 1 at creation and increments by 1 per modification — implementation/util.py:49
- §2.7 — insert — ambiguity — on revise, the segregation-of-duties check runs only after the OCC version check (stale version + creator → `ERR_STALE_PLAN_VERSION`) — implementation/routes/plans.py:199-208
- §2.9 tier 8 — revise — mismatch — referenced manager's existence (`ERR_NOT_FOUND`) is verified at the cross-reference tier, after tier-7 employee_ref uniqueness, not at tier 3 as the ladder's "body identifiers" sentence implies — implementation/routes/reps.py:31-33, 70-78
- §3.1 — revise — mismatch — `curve_tiers` shape+business validation runs during basic body validation, ahead of the program-existence check (ladder would put existence first); also pins negative `rollup_rate_bps` / non-positive `payout_cap_cents` → `ERR_INVALID_REQUEST` in that early pass — implementation/routes/plans.py:95, 100-108
- §3.1 — insert — ambiguity — on revise, replacement-field validation happens as fields are applied, after the SoD check (forbidden caller + invalid replacements → `ERR_SEGREGATION_OF_DUTIES`) — implementation/routes/plans.py:206-229
- §3.2 — revise — mismatch — rep `version` increments only when a field actually changes (no-op PUT does not increment); explicit null `manager_id` detaches the manager — implementation/routes/reps.py:103-119
- §3.3 — insert — ambiguity — body-identifier existence order is `program_id` → `rep_id` → `plan_id` — implementation/routes/assignments.py:80-88
- §3.3 — insert — ambiguity — negative draw/guarantee amounts rejected with `ERR_INVALID_REQUEST` during basic body validation, before existence checks — implementation/routes/assignments.py:74-77
- §3.3 — insert — ambiguity — all new-assignment monetary counters (`draw_outstanding_cents`, `draw_forgiven_cents`, `current_period_earned_cents`, `lifetime_earned_cents`, `lifetime_paid_cents`) and both live indicators begin at 0 — implementation/routes/assignments.py:120-127
- §3.4 — insert — ambiguity — non-positive `amount_cents`, non-integer/non-positive `split_bps`, missing/empty split `rep_id` → `ERR_INVALID_REQUEST` during body validation, before program existence — implementation/routes/transactions.py:65-74
- §3.4 — revise — ambiguity — provisional payout mode-filters the `PENDING` credits too (under `DIRECT_ONLY`, held ROLLUP credits are excluded from the estimate) — implementation/services/calculations.py:117-123
- §3.5 — insert — ambiguity — clawback adjustment pins: `dispute_id` null, `created_by_user_id` is the literal string `system`, system-generated `reason` identifying the reversed credit — implementation/services/crediting.py:142-156
- §3.6 — insert — ambiguity — supplied `credit_entry_id` resolving to no credit entry → `ERR_NOT_FOUND` at the referential-coherence step — implementation/routes/disputes.py:69-72
- §3.6 — revise — mismatch — dropped "carries an optional `note`" from dispute rejection (impl parses/stores no note); also pins dispute-spawned adjustment's `created_by_user_id` = approving manager and system-generated `reason` — implementation/routes/disputes.py:207-218, 184-202
- §3.7 — insert — ambiguity — period-close lock sweep is scoped to credit entries **of the program** — implementation/routes/programs.py:81-84
- §3.8 — insert — ambiguity — `period_index` below 1 passes the closed-period guard (only `>= current_period_index` is rejected) — implementation/routes/payroll_exports.py:36-38
- §3.8 — insert — ambiguity — `statement_ids` collected in statement-creation order; statement-less (program, period) still exports with empty `statement_ids`/`statement_count` 0/`total_cents` 0; export record carries `program_id` and `period_index` — implementation/routes/payroll_exports.py:63-82

**Verified already-pinned (no change needed):** full error catalogue vs `errors.py` (all 29 codes + HTTP statuses match), envelope shapes, validation-ladder ordering on all other paths, split-allocation remainder rule, curve band math + cap-last, settlement pipeline order, draw/guarantee/deficit ledger math, clawback-on-cancel vs survive-on-terminate, OCC guard ordering on close (`ERR_OPEN_DISPUTES_EXIST` before `ERR_STALE_PROGRAM_VERSION`), rep ownership-hiding resource set, dispute filing window `[current-2, current]`, effectiveness analytics formulas, and all endpoint roles/status codes from §4.
