# Worklog — task_0043_robo_advisor_tax_loss_harvesting

## Step 1: Create task directory — 2026-05-29T12:09:31Z

Created `tasks/task_0043_robo_advisor_tax_loss_harvesting/` and `tasks/task_0043_robo_advisor_tax_loss_harvesting/workspace/` (pre-allocated path; no ./tasks/ scan or auto-increment performed).

## Step 2: Generate scaffold — 2026-05-29T12:29:39Z

All three required files are written and the scaffold passes `scaffold_lint.py` clean. Here is the summary of what I generated.

## Generated scaffold — Robo-Advisor Tax-Loss Harvesting

Three files under `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0043_robo_advisor_tax_loss_harvesting/`:
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**Complexity profile:** primary archetype *ledger reconciliation* + secondary *compliance/audit*; layers = rate/threshold triggers, cascading side effects, dual-variant calculation, optimistic concurrency. Flat multi-collection topology (`api_prefix: /`), branching state-machine shape, peer roles, immediate consistency. Difficulty band: Advanced/Expert (8 entities, 38 endpoints).

**Entities (8):** Security, ModelPortfolio, Account, RiskQuestionnaire, TaxLot, HarvestEvent, RebalanceEvent, TaxForm1099B. 12 FKs declared with the canonical `FK -> X.id` prefix, all reverse-reachable via filtered-list GETs.

**State machines (5):** Account (PENDING_PROFILE→ACTIVE↔REBALANCE_DUE, FROZEN branch, CLOSED), RiskQuestionnaire (SCORED→ACCEPTED→SUPERSEDED), HarvestEvent (PROPOSED→{EXECUTED,REJECTED}, EXECUTED→REVERSED — the branch/compensation core), RebalanceEvent (PLANNED→{EXECUTED,CANCELLED}), TaxForm1099B (DRAFT→FINALIZED).

**Calculations (5):** risk_scoring (weighted, single-round-then-clamp), drift_computation (>= threshold boundary), capital_gain_realization (FIFO vs HIFO dual variant), wash_sale_disallowance (inclusive ±30-day interval, prorated min + basis carryover), form_1099b_totals (wash-sale add-back).

**Validations:** 17 priority-ordered rows. **Endpoints:** 38 (incl. one `/_clock/set_current_utc` test-driving endpoint). **Error catalog:** 18 codes. **Roles:** 2 (Advisor, Compliance — both opaque). **Concurrency rules:** 2 OCC-on-Account.version (harvest-create, rebalance-create).

**§1.8 design:** 18 instances = 9 Difficulty Rules × 2 each (all required rule_ids present, ≥2 each).
**§1.9 design:** 38 instances across all 9 claim-extraction-guide sections (entities 10, state_machines 6, calculations 5, validations 5, endpoints 2, errors 2, rbac 3, cross-cutting 4, consistency 1), of which 4 are `excluded_because` stubs citing named §1.8 instances.

**Lint:** `VERDICT: clean lint` — all 376 setup/trigger calls conform to §1.5 (checks a–e) and all 12 FKs pass reverse-reachability (check f). All formula-derived asserts were computed in code and pinned as literals (e.g. risk_score 82, drift 5/4 boundary, FIFO +6000 vs HIFO −6000, wash-sale disallowed 4000, reinvest 12 shares + 2000 cash remainder, 1099-B net −6000). No forbidden concurrency vocabulary; all enum values are produced by a transition/calc/init.

One deliberate decision worth flagging: `api_prefix` is set to `/` (root) rather than a single resource path, because the scenario is genuinely a flat federation of eight peer collections — this is what makes the lint's collection-segment derivation and FK reverse-reachability resolve correctly for every entity.

## Step 3: Copy INSTRUCTION.md — 2026-05-29T12:29:45Z

`cp ./INSTRUCTION.md ./tasks/task_0043_robo_advisor_tax_loss_harvesting/workspace/INSTRUCTION.md` (1424 bytes copied).

## Step 4: Generate PRD — 2026-05-29T12:34:36Z

The PRD is complete and well-structured. The document ends at §5 Error Code Catalogue with no audit footer, as required. All three hard contracts pass.

## Summary

Generated the PRD for the Robo-Advisor Tax-Loss Harvesting API at `workspace/PRD.md`. **Approximate length:** 256 lines.

**Section list:**
- §1 Introduction (3 paragraphs — wash-sale framing, lifecycle overview, role overview)
- §2 Global Specifications (10 subsections, domain-derived): 2.1 RBAC (both roles opaque), 2.2 API Response Structure, 2.3 Pagination, 2.4 Common Resource Properties and Identity (RiskQuestionnaire is the lone `common_fields: false` entity — only id/created_at), 2.5 Nested Path Resolution and Resource Existence, 2.6 Monetary Precision and Rounding, 2.7 Drift, Allocation, and the Rebalance-Due Boundary (inclusive `>=`), 2.8 Cost-Basis Ledger and Account Value, 2.9 Optimistic Concurrency Control on the Account (expected_account_version / ERR_STALE_ACCOUNT_VERSION / 412), 2.10 Validation Ordering
- §3 Business Logic & Workflows (10 subsections): securities & models, profiling & activation, tax lots, harvest proposal+execute cascade, wash-sale disallowance, rebalancing & FIFO/HIFO variants, compliance oversight, account close, 1099-B reporting, test-driving clock
- §4 Endpoint Definitions (4-column table, 38 endpoints)
- §5 Error Code Catalogue (2-column table, 18 errors)

**Hard Contract reports:** Field coverage PASS (53/53 entity fields, 32/32 endpoint params). Rule coverage PASS (17/17 validations, 2/2 OCC concurrency rules, all state-machine transitions incl. L1→L2→L3 cascade + reversal compensation, 5/5 calculations with constants embedded, sibling-branch symmetry). Path purity PASS (301 backtick tokens scanned, 0 path-like / 0 method / 0 method+path tokens in §3).

**Confirmation:** Neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read, opened, grepped, or referenced. Only SKILL.md, SCAFFOLD.yaml, section-2.2-response-structure.md, and example-prd.md were consulted.

## Step 5: Generate unit tests — 2026-05-29T12:54:52Z

Generated complete test infrastructure for **task_0043_robo_advisor_tax_loss_harvesting** from the two design indices only (no freelance discovery from SCAFFOLD.yaml).

### Test files: 9 (+ conftest.py)
`test_suite/`: `test_01_crud_and_validation.py`, `test_02_auth_and_rbac.py`, `test_03_risk_scoring_and_models.py`, `test_04_account_lifecycle.py`, `test_05_drift_and_rebalancing.py`, `test_06_harvest_workflow.py`, `test_07_wash_sale_and_reversal.py`, `test_08_tax_forms.py`, `test_09_endpoints_and_listing.py`, `conftest.py`.

### Test functions: 70
- **Queue A (Difficulty):** all 18 instances covered, exactly 2 tests each = 36 tests.
- **Queue B (Corner):** all 34 non-stub instances covered, 1 test each = 34 tests.
- 70 tests / 70 `Design:` tag lines (1:1; no untagged, dual-tagged, or dangling tags). Every difficulty/corner instance name verified to match the source yaml verbatim.

### Design instances consumed vs skipped
- **Consumed:** 18/18 Difficulty + 34/34 non-stub Corner = **52 instances**, zero skipped.
- **4 Corner stubs** correctly NOT translated (`error_invalid_state…_stub`, `fifo_hifo_divergence_stub`, `occ_stale_version_on_harvest_create_stub`, `replacement_too_correlated_stub`); each `difficulty_instance` cross-reference resolves to a real §1.8 instance that owns the assertion.
- No instances failed the PRD-first two-condition filter — every asserted rule (drift `>=` boundary, wash-sale inclusive 30-day window, FIFO/HIFO lot ordering, 1099-B add-back, OCC, validation-priority precedence per PRD §2.10, compensating reversal invariants) is verbatim-covered and uniquely-derivable from PRD prose.

### Verification passed
- All 18 helper + test files compile.
- **PRD-citation pass:** every quoted citation survives a whitespace-normalized literal grep of PRD.md — 0 misses, 0 unbalanced backticks.
- No `scaffold`/`§1.x`/`Table N`/`test_recipe` leakage; no `skip`/`skipif`/`xfail`; no unused imports.

### test_helpers/ file list
`__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`.

Key design notes: both roles (`Advisor`, `Compliance`) are opaque per PRD §2.1, so `test_users.py` uses shared header constants. `RiskQuestionnaire` is the sole `common_fields:false` entity — its TypedDict and `assert_questionnaire` omit `version`/`updated_at`. `fixtures.py` provides composite chains (`setup_proposed_harvest`, `setup_executed_harvest`, `setup_active_account_with_washsale_loss_lot`, `setup_rebalance_due_account`) reused across both queues.

## Step 6: Generate implementation — 2026-05-29T12:54:52Z

Built a complete Python + Flask REST API for the Robo-Advisor Tax-Loss Harvesting task at `workspace/implementation/`.

### Files (9)
- `start.sh` — foreground launcher: reads `$PORT` (default 10000), binds `0.0.0.0`, frees any stale listener on the port before binding, `exec`s the app; sentinel-guarded pip install
- `app.py` — Flask entry point, all 38 routes, serializers, auth/RBAC, pagination, validation ordering, error handlers
- `services.py` — cross-aggregate logic: drift bubble-up, harvest execute cascade (L1→L2→L3), harvest reverse (compensating undo), rebalance execute, FIFO/HIFO lot consumption, wash-sale scan
- `calculations.py` — risk scoring, drift computation, wash-sale disallowance, `round_half_up` (Decimal, half-up not banker's)
- `db.py` — in-memory dicts keyed by id, common-field minting, `touch()` version bump
- `errors.py` — full 18-code error catalog with HTTP statuses
- `response.py` — success/error envelope (`meta`/`response_type`/`data`, `req_` ids, ms-precision ISO8601 Z)
- `clock.py` — test-driving logical clock
- `requirements.txt` — `Flask==3.0.3`

### Stack
Python 3.9-compatible, Flask, `decimal.Decimal` for all money/percentage math. Pure in-memory storage — no SQLite, no file I/O, no `/tmp`, no seeding (verified by grep).

### Endpoints
38 implemented, matching the PRD §4 / scaffold §1.5 table exactly.

### Verification
Ran ~70 live assertions across five scenarios — auth/RBAC, full lifecycle, risk scoring, model band resolution, drift boundary, harvest execute cascade, wash-sale disallowance, harvest reverse, rebalance, 1099-B totals, and all error screens. All passed.

### start.sh contract confirmed
Reads `$PORT`, binds `0.0.0.0`, runs foreground via `exec`. Re-invocation kills the stale listener, frees the port, boots fresh empty state. Storage is in-memory only.

## Step 7: Run tests and iterate — 2026-05-29T13:13:34Z

All tests pass. Exiting with the summary.

## Summary

**Iterations run:** 2 (initial diagnostic sweep + 1 fix sweep). Final 8-round parallel sweep: all 8 rounds passed 70/70, zero failures, zero flakiness.

**Initial state:** Each round deterministically failed the same 3 tests. The real failing set was stable across all 8 rounds: `test_questionnaire_has_no_version_field`, `test_harvest_propose_on_closed_account_blocked`, `test_cascade_l3_ytd_ledgers_updated_with_disallowance`.

**Tests deleted:** None. All three failures traced to verbatim PRD prose and were uniquely derivable; none collapsed under STEP 1.

**Fixes applied to `test_suite/`:**
- `test_01_crud_and_validation.py` — `test_questionnaire_has_no_version_field`: added a model-portfolio creation to the setup. STEP 2 test bug: the test submitted a questionnaire (default score 82) with no active model in the system, so the PRD-faithful server correctly rejected it with `ERR_NO_MODEL_FOR_SCORE` per PRD §3.2 ("If no active model's band contains the score, the submission is rejected with `ERR_NO_MODEL_FOR_SCORE`"). The asserted rule (questionnaire has no `version`/`updated_at`, PRD §2.4 line 88) is covered; only the precondition was unfaithful.
- `test_04_account_lifecycle.py` — `test_harvest_propose_on_closed_account_blocked`: replaced a fabricated non-existent `source_lot_id` with a real lot opened on a separate operable account. STEP 2 test bug: PRD §2.5 + §2.10 fix the precedence — identifier resolution (`ERR_NOT_FOUND`) runs *before* the operability gate (`ERR_ACCOUNT_NOT_OPERABLE`), so the fake lot id correctly produced `ERR_NOT_FOUND`. Making the source lot exist lets the closed-account operability gate fire as the test intends.

**Fixes applied to `implementation/`:**
- `services.py` — `_recompute_ytd_ledgers`: changed `realized_gain_cents_ytd` to be net of wash-sale disallowance (`realized_gain + wash_sale_disallowed` per closed lot) instead of the raw signed sum. STEP 3 implementation bug: PRD §3.4 ("`realized_gain_cents_ytd` (the loss net of any disallowance)") and §3.5 ("the net realized loss recognized in the current year is the realized loss plus the disallowed amount") both mandate the add-back. Verified consistent with the reversal tests (lot reopened → ytd back to 0) and the 1099-B form tests (which compute their own net via a separate §3.9 path, unaffected).

**Orchestrator independent re-verification (2026-05-29T13:14Z):** re-ran the full 8-round parallel sweep; all 8 rounds = 70 passed / 70 total / 0 failed / 0 errors / 0 skipped. `results.{1..8}.json` persisted in `workspace/implementation/`.

## Step 8: Finalize PRD — 2026-05-29T13:23:49Z

The patch is exactly one line revised, no other changes.

## Summary

**Line counts:** PRD.md = 256 lines; PRD_FINALIZED.md = 256 lines. Delta = 0 lines (one line revised in place). %-delta ≈ 0.4% (1 of 256 lines changed).

**Changes (one bullet per change):**
- §2.8 — *revise* — Redefined `realized_gain_cents_ytd` from "the signed sum of `realized_gain_cents` over `CLOSED` tax lots" to the signed sum of each lot's `realized_gain_cents` **net of that lot's wash-sale disallowance** (`realized_gain_cents` + the lot's positive `wash_sale_disallowed_cents`), citing §3.4/§3.5 — `services.py:40-64` (`_recompute_ytd_ledgers`, `realized += rg + lot_disallowed`).

**Why only one edit (the other two step_7_diff items needed none):**
- Item 1 (`test_01` fix) was a pure fixture bug. Asserted behaviors (no `version`/`updated_at` §2.4; `ERR_NO_MODEL_FOR_SCORE` §3.2) already uniquely pinned. No edit.
- Item 2 (`test_04` fix) was a pure fixture bug. Precedence (`ERR_NOT_FOUND` before `ERR_ACCOUNT_NOT_OPERABLE`) already pinned in §2.5/§2.10. No edit.
- Item 3 (impl fix) was the real PRD issue: §2.8's prior wording ("signed sum of `realized_gain_cents`") described the raw sum and contradicted §3.4/§3.5 which the impl follows. Revision aligns §2.8 with impl + other sections.

**Per-edit pre-edit search log:**
- **(a) Subject:** account field `realized_gain_cents_ytd` (and adjacent `wash_sale_disallowed_cents_ytd`).
- **(b) Enumerated impl paths:** `services.py:_recompute_ytd_ledgers` (40-65, sole computation); caller `recompute_account_aggregates` (24-33); all four recompute callsites — `bubble_up` (87), `execute_harvest` L3 (213), `reverse_harvest` (272), `execute_rebalance` (371); `ser_account` (app.py:200, 212-213); account-creation defaults (app.py:480-481). All YTD computation routes through the single helper. Independent path confirmed unaffected: 1099-B `_reportable_lots`/form totals (app.py:1050-1057), `net_realized_gain_cents = (proceeds - cost) + disallowed`, already described by §3.9. Reversal clears the closed lot's fields (services.py:258-259), so net add-back returns ytd to pre-harvest value.
- **(c) Wording adjustment:** anchored rule to "each lot's `realized_gain_cents` ... plus the lot's positive `wash_sale_disallowed_cents`" and cross-referenced §3.4/§3.5; left `wash_sale_disallowed_cents_ytd` clause + "Both default to zero" verbatim (impl matches as-is).

## Step 9: Complete PRD — 2026-05-29T13:30:34Z

## Summary

**File comparison:**
- Source: `PRD_FINALIZED.md` — 256 lines, 40,964 chars
- Output: `PRD_COMPLETED.md` — 256 lines, 43,559 chars (+2,595 chars; line count unchanged — all edits in-paragraph)

**Change counts:** 10 changes — 8 ambiguity-pins, 2 mismatch-revisions.

**Per-change log** (`{section} — {kind} — {type} — {what} — {impl ref}`):
- §2.3 Pagination — insert — ambiguity — out-of-range/non-numeric `limit`/`offset` are clamped to bounds (or fall back to defaults) rather than rejected — `app.py:129-159`
- §2.10 Validation Ordering — revise — mismatch — on create requests, body well-formedness (`ERR_INVALID_REQUEST`) is validated *before* body-carried FK existence (`ERR_NOT_FOUND`); only path identifiers resolve before body validation — `app.py:580-586, 702-714, 929-936, 1066-1068`
- §3.1 Securities — insert — ambiguity — correlation lookup is symmetric (either security's `correlated_with` map by the other's ticker); a missing pairing means the correlation screen imposes no constraint — `app.py:759-768, 873-876`
- §3.2 Questionnaire accept — insert — ambiguity — re-profile branch fires for any account *not* in `PENDING_PROFILE`; lands `ACTIVE`/`REBALANCE_DUE` by drift regardless of prior status, not gated on operability — `app.py:666-689`
- §3.3 Tax lots — insert — ambiguity — `quantity` may be integer or fractional; account resolved before security (left-to-right) — `app.py:707-714`
- §3.4 Harvest execute — revise — mismatch — pinned actual screen order: source-lot OPEN/belongs (`ERR_INVALID_STATE`) → substantially-identical → too-correlated → not-a-loss-lot → delisted — `app.py:860-886`
- §3.5 Wash-sale — insert — ambiguity — triggering lots must belong to the *same account*; full basis carryover goes to the single earliest-acquired survivor (tie-break `created_at` asc) — `services.py:112-149`
- §3.6 Rebalance cancel — insert — ambiguity — cancelling a non-`PLANNED` event yields `ERR_INVALID_STATE` — `app.py:1024-1025`
- §3.7 Compliance — insert — ambiguity — freeze of non-operable account, unfreeze of non-`FROZEN`, reject of non-`PROPOSED`, reverse of non-`EXECUTED` (or while `CLOSED`) all yield `ERR_INVALID_STATE` — `app.py:531-532, 543-544, 897-898, 912-915`
- §3.8 Close account — insert — ambiguity — closing an already-`CLOSED` account yields `ERR_INVALID_STATE`, checked before the open-lots check — `app.py:561-566`

**Deliberately left unchanged:** rebalance trade-generation algorithm internals (only observable outputs pinned by §3.6); idempotent re-retire/re-delist and delisted-security price-update (impl-tolerant, untested, PRD-neutral) — left alone to avoid over-pinning.

---

## Pipeline complete — 2026-05-29T13:30:34Z

All 9 steps done. Final state: 70/70 tests pass across 8 parallel rounds (0 flakiness). Artifacts: SCAFFOLD.yaml + 2 design indices, PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ (9 files) + test_suite/ (9 test files + conftest), workspace/implementation/ (9 files, Python/Flask, in-memory). No tests deleted; 2 test_suite fixture fixes; 1 implementation fix.
