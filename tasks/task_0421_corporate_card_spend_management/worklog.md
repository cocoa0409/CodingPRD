# Worklog — task_0421_corporate_card_spend_management

## Step 1: Create Task Directory — 2026-06-19T13:30:40.000Z

Created `tasks/task_0421_corporate_card_spend_management/` and `workspace/` subdirectory. Verified `INSTRUCTION.md` exists at project root for Step 3 copy.

## Step 2: Generate Scaffold — 2026-06-19T14:06:00.000Z

All three scaffold artifacts are complete and validated.

Generated the full scaffold for **task_0421_corporate_card_spend_management** (Brex/Ramp-style corporate card & spend management) at EXPERT difficulty. All three files were written:

- `SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Counts (Expert band thresholds all met):**
- Entities: **14** (target 10–15) — Company, SpendPolicy, Employee, GlAccount, Card, Transaction, Receipt, ApprovalRequest, ReimbursementClaim, Statement, Repayment, RewardAccount, SpendAuthorization, ErpSyncBatch
- Endpoints: **72** (above the 20–32 guideline; inflated by the lint-mandated single + filtered-list GETs that every FK needs for reverse-reachability — the business-action surface is ~35)
- Errors: **25** (target 18–30)
- Roles: **4** (target 3+) — FinanceAdmin, Approver, CardholderEmployee, Auditor (segregation-of-duties model)
- State machines: **8** (target 4+), including non-linear shapes: Transaction parallel `auth_status × review_status`, ApprovalRequest reject↔resubmit cycle, ReimbursementClaim reject→draft cycle, Statement linear-with-revert (PAID→DUE)
- Calculations: 6; concurrency rules: 1 (OCC on Statement.version for repayment create)

**Difficulty design:** 18 §1.8 instances (exactly 2 per all nine §0.5 rules). Rule 8 (resource_temporal_overlap) is satisfied by a genuinely-temporal `SpendAuthorization` entity with two different interval semantics (EMPLOYEE-scope half-open overlap vs CARD-scope buffered adjacency). **Corner design:** 38 test-recipe instances + 4 `excluded_because` stubs.

**Verification:** `scaffold_lint.py` returns `VERDICT: clean lint`. Independently confirmed: all `grounds[]` resolve to declared §1.1–§1.7 elements, all 59 instance names unique, every error triggerable (no dead errors), no forbidden concurrency vocabulary, correct file-split, flat `api_prefix: /` topology so every FK has reverse-reachability. All formula-derived asserts are pre-computed literals.

## Step 3: Copy Shared Files — 2026-06-19T14:08:23.000Z

Copied `INSTRUCTION.md` → `tasks/task_0421_corporate_card_spend_management/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-19T14:16:33.000Z

(Note: first subagent attempt died with a mid-response connection error before writing PRD.md; a fresh subagent was spawned and succeeded.)

**Written:** `workspace/PRD.md` (313 lines)

**Domain:** Corporate Card & Spend Management (Brex/Ramp style) — EXPERT-band ledger-reconciliation + workflow-orchestration with 14 entities, parallel/revision-cycle state machines, dual-variant calculations, OCC, and a conserved credit pool.

**Section structure:**
- **§1 Introduction** — system goals + two-dimensional reconciliation challenge + segregation of duties
- **§2 Global Specifications** (11 subsections): RBAC, Response Structure, Pagination, Common Resource Properties & nested-path validation, Monetary Precision & Reward Rounding, The Conserved Credit Pool, Hierarchical Consistency & Cascading Reconciliation, OCC on Repayment Creation, Merchant/Limit/Credit Gating precedence, Validation Precedence, The Simulated Company Clock
- **§3 Business Logic** (10 subsections): Company Setup, Card Lifecycle, Two-Dimensional Transaction, Receipt/GL/Reward, Approval Workflow, Statements & Repayment, Reimbursement, Rewards & Redemption, Pre-Authorized Spend Budgets, ERP Export
- **§4 Endpoint Definitions** — 4-column table (74 endpoints) + query-parameter prose
- **§5 Error Code Catalogue** — 2-column table (25 error codes)

**Hard Contract Reports:** Contract 1 (field coverage 64/64) PASS; Contract 2 (rule coverage: OCC, all state machines, all calculations, all constants, validation precedence) PASS; Contract 3 (path purity in §3) PASS. The two withheld design files were not read.

## Step 5: Generate Unit Tests — 2026-06-20T00:00:00.000Z

72 tests collected cleanly across 7 files. Generation is complete. Here is the final report.

Generated complete test infrastructure for `task_0421_corporate_card_spend_management` from the two design indices (PRD-first adjudication), the only permitted test source.

### `test_helpers/` (Stage 1) — 9 files
- **types.py** — 17 status/role enums + 14 entity TypedDicts. `Receipt` correctly omits `version`/`updated_at` (PRD §2.4 immutable, `common_fields:false`).
- **api_client.py** — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (all ~70 endpoints).
- **api_errors.py** — all 25 PRD §5 error IDs + HTTP status map, registered with the framework.
- **assertions.py**, **factories.py**, **constants.py**, **test_users.py** (entity-backed role builders thread real `Employee.id` for ownership/SoD), **fixtures.py** (8 tiers of composite setup: org graph, transaction lifecycle, statement/repayment, approval cycle, reimbursement, auth windows, ERP batch), **__init__.py** barrel.

### `test_suite/` (Stage 2) — conftest + 7 files, 72 tests
- **Difficulty queue:** 17/18 instances × 2 tests = 34 tests. All 9 rules covered.
- **Corner queue:** 38/38 non-stub instances × 1 test = 38 tests. The 3 `excluded_because:` stubs were verified to cross-reference real difficulty instances and were correctly NOT translated.

### Adjudication decisions (gaps left as gaps, per the Core rule)
- **SKIPPED: `priority_pair_validation_conflict / ppvc_gl_required_beats_receipt_required`** — the instance asserts `ERR_GL_CODE_REQUIRED` wins over `ERR_RECEIPT_REQUIRED` on approve-review. But PRD §3.5 prose enumerates the checks "First… `ERR_RECEIPT_REQUIRED`. Second… `ERR_GL_CODE_REQUIRED`", ordering the receipt check **first**. A faithful PRD-only implementer would return `ERR_RECEIPT_REQUIRED`, contradicting the asserted outcome — fails unique derivability. No weakened/xfail test emitted; the gap is documented in the test_03 module docstring. (The `priority_pair_validation_conflict` rule remains exercised via the MCC/card-active pair's 2 tests.)

### Verification performed
- All 14 helper + 7 suite files `py_compile` and import cleanly against the installed framework.
- `pytest --collect-only`: 72 tests, 0 collection errors.
- **C1 verbatim audit** (AST-based, backtick/quote/dash-normalized): a ≥8-word substring of every test's PRD citation survives a literal grep of PRD.md — 0 failures across all 72.
- **C4 audit**: exactly one `Design:` line per test — 0 violations.
- No `pytest.mark.skip`/`skipif`/`xfail`/placeholder tests; no "scaffold"/"Table"/"§1.x"/`test_recipe` leakage in emitted code.

Note: tests were not executed against a live server (no implementation exists yet and Stage 1/Stage 2 assume the runner manages server lifecycle); validation was limited to compile, import, collection, and the citation/coverage audits.

## Step 6: Generate Implementation — 2026-06-20T00:00:00.000Z

The implementation is complete and verified. Here is a summary.

A complete Python + Flask REST API for the Corporate Card & Spend Management benchmark task, in `workspace/implementation/`.

**Files (18 total):**
- `start.sh` — foreground launcher with guarded `pip install` (only installs when `flask` is missing) and `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000)
- `app.py` — Flask entry point, blueprint registration, error handlers (ApiError + 404/405/400/500 → well-formed envelope)
- `errors.py`, `response.py`, `db.py`, `middleware.py` — error catalog, envelope helpers, in-memory store, auth/role extraction
- `services/common.py`, `services/calculations.py`, `services/statements.py` — shared helpers, calculation rules, statement/repayment cascades
- `routes/{setup,cards,transactions,reimbursements,billing,misc}.py` — all 70 endpoints across the 13 entities

**Verification:** Server boots via `start.sh` in ~2s with an empty store (no seeding). Ran 75+ assertions across three smoke suites, all passing — covering the conserved credit pool reconciliation (hold/settle/reverse/close/repay), dual-variant statement balance (CHARGE accrual sweep vs CREDIT cash), ceil-vs-floor minimum due, reward accrual with MCC override + per-txn cap + half-up rounding, parallel auth/review state dimensions, the high-value approval gate, segregation-of-duties (ERR_SELF_APPROVAL), OCC on repayment create (ERR_STALE_VERSION/412), past-due sweep, both auth-window interval semantics (EMPLOYEE touching-allowed vs CARD 2-day buffer), and validation precedence.

**Key fidelity decisions traced to PRD prose:**
- Response envelope `meta`/`response_type`/`data` with `req_` request IDs and 3-fractional-digit ISO8601 timestamps; pagination (`limit`/`offset`/`total_count`/`has_more`) in `meta`
- Auth headers `X-User-ID`/`X-User-Role`; the four exact role names; Auditor read-only enforced by excluding it from every write `require_role` set
- Capture gate precedence (§2.9): MCC block → card-active → per-txn → card headroom → company credit
- Transaction reward uses the `MAX_REWARD_PER_TXN_CENTS` cap; reimbursement-pay reward does **not** (per §3.7 / scaffold side-effect, which omit the cap there) — these round half-up, while minimum-due rounds up (ceil)
- Repayment create checks state (DUE/PAST_DUE → ERR_INVALID_STATE) before OCC, matching §3.6 prose ordering
- Receipt is immutable: only `id` + `created_at`, no `version`/`updated_at`
- Derived fields (`held_cents`, `available_credit_cents`) recomputed from first principles on every relevant mutation; parent `version`/`updated_at` bumped only when the derived value actually changes (e.g. `clear` keeps the hold counted, so no parent bump)

No language/structural names were assumed — all header names, envelope fields, error IDs, OCC field (`expected_statement_version`), and pagination params were read from the scaffold/PRD.

## Step 7: Run Tests and Iterate — 2026-06-20T00:00:00.000Z

All 8 parallel rounds pass: `passed == total == 71` in every round, 0 failures, 0 errors. The clean sweep condition is met. Exiting with the summary.

**Iterations run:** 2 (initial sweep → diagnose/fix → confirming sweep).

**Initial state:** 8/8 rounds showed a single consistent failure: `test_patch_transaction_gl_code_invalid_account_rejected` (the rest of the 72-test suite passed in every round). The failure was deterministic, not flaky.

**Diagnosis:** The test PATCHed `/transactions/{id}` with a **non-existent** `gl_account_id` (the framework's `NON_EXISTENT_UUID`) and asserted `ERR_GL_CODE_REQUIRED`. The implementation correctly returned `ERR_NOT_FOUND`.

Applying the diagnostic protocol:
- **STEP 1a (coverage):** The test cites PRD §3.4: "the referenced GL account must be `ACTIVE` or the change is rejected with `ERR_GL_CODE_REQUIRED`." That sentence governs the "exists-but-not-ACTIVE" case, not a non-existent reference.
- **STEP 1b (unique derivability) — FAILED:** PRD §2.4 states "A reference to a non-existent company or child resource yields `ERR_NOT_FOUND`," and §2.10 fixes the precedence: "(3) existence of all referenced resources, `ERR_NOT_FOUND` … then the domain-specific checks at lower priority … Endpoint-specific gates (GL coding, …) take effect after the generic state check." Existence (priority 3) strictly precedes the endpoint-specific GL gate. The two-reader experiment yields divergent PRD-faithful implementations (Reader A → `ERR_NOT_FOUND` per §2.4/§2.10 precedence; Reader B → `ERR_GL_CODE_REQUIRED` reading §3.4 in isolation). This is an **ERROR PRECEDENCE SILENCE** collapse: the PRD names `ERR_GL_CODE_REQUIRED` only for the not-ACTIVE case and never states the GL gate pre-empts the existence-check path — in fact §2.10 dictates the opposite ordering.

**Tests deleted:**
- `test_04_entities_and_endpoints.py::test_patch_transaction_gl_code_invalid_account_rejected` — ERROR PRECEDENCE SILENCE. Asserted `ERR_GL_CODE_REQUIRED` for a non-existent `gl_account_id`, but PRD §2.4 + §2.10 place the existence check (`ERR_NOT_FOUND`) strictly before the endpoint-specific GL gate; the cited §3.4 sentence covers only the exists-but-not-ACTIVE case. (Scaffold rule that drove generation: Corner/endpoints/patch_transaction_gl_code_inactive_account_rejected.) The implementation's existence check is PRD-required and was deliberately NOT weakened.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:** None — the implementation was already precedence-correct per §2.4/§2.10.

**Final result:** Clean 8-round parallel sweep — every round `passed == total == 71`, 0 failures, 0 errors.

## Step 8: Finalize PRD — 2026-06-20T00:00:00.000Z

(Step 8 ran because Step 7 had 1 test deletion — the skip condition requires 0 deletions AND 0 fixes of every kind.)

Done. `PRD_FINALIZED.md` was created and is a byte-for-byte copy of `PRD.md` — no edits were warranted.

**Line counts:** PRD.md = 313 lines; PRD_FINALIZED.md = 313 lines. **Delta: 0% (byte-identical).**

**Changes:** None.

**Rationale:** The single Step 7 item — the deleted test `test_patch_transaction_gl_code_invalid_account_rejected` — concerns error precedence on PATCH `/transactions/{txId}` when the body carries a non-existent `gl_account_id`. After locating the matching behavior in the implementation, the subagent confirmed PRD.md already uniquely determines it (§2.4 + §2.10 place the existence check `ERR_NOT_FOUND` strictly above the endpoint-specific GL gate; §3.4 names `ERR_GL_CODE_REQUIRED` only for the exists-but-not-ACTIVE case), so this is the valid no-edit outcome.

**Per-edit pre-edit search log** (one subject, no edit committed):
- **(a) Subject:** Error precedence between existence of a body-referenced `gl_account_id` (`ERR_NOT_FOUND`) and the GL-active gate (`ERR_GL_CODE_REQUIRED`), centered on PATCH `/transactions/{txId}`.
- **(b) Impl paths enumerated:** `routes/transactions.py:114-127` (`code_transaction`, Step 7 site), `:37-39` (`capture_transaction`), `:296-300` (`approve_review`); `routes/reimbursements.py:29` (claim create), `:96-98` (claim approve); `services/common.py:64-68` (`get_or_404`); `errors.py` (status map). All consistent — body-reference existence → `ERR_NOT_FOUND`; stored-value review gate → `ERR_GL_CODE_REQUIRED`.
- **(c) Wording adjustment:** None. No PRD silence, no PRD/impl mismatch.

## Step 9: Complete PRD — 2026-06-20T00:00:00.000Z

All three edits applied cleanly. The implementation walk is complete and PRD_COMPLETED.md now pins the behaviors the implementation actually adopts wherever the prose was silent.

**File metrics**
- Source: `PRD_FINALIZED.md` — 313 lines, 51,941 chars
- Result: `PRD_COMPLETED.md` — 313 lines, 52,112 chars (char-delta: +171)

**Counts**
- Ambiguity-pins: 3
- Mismatch-revisions: 0

**Changes**
- §2.4 (Common Resource Properties) — insert — ambiguity — pinned the `version` initial value as 1 ("begins at its initial value of 1"), which the PRD left unspecified — `db.py:51` (`stamp_create` sets `version = 1`).
- §3.3 (Spending: The Two-Dimensional Transaction) — insert — ambiguity — pinned the at-birth values of `settled_amount_cents` (null) and `reward_points_cents` (0) on capture, which the PRD's capture prose did not state — `routes/transactions.py:71,74`.
- §3.7 (Out-of-Pocket Reimbursement) — insert — ambiguity — pinned that the §3.4 per-transaction cashback cap does NOT apply to the reimbursement-payment reward, which the PRD left open — `routes/reimbursements.py:151-154` (no cap, unlike `services/calculations.py:reward_for_amount`).

**Notes on areas checked but left unchanged (already uniquely pinned):** capture-gate precedence (§2.9), approve-review check order (receipt→GL→approval→self), repayment state-before-OCC order, dual-variant closing balance & minimum-due, PAID↔DUE reversion, half-open vs buffered authorization windows, role/RBAC matrix, pagination/sort, and the dual rounding rules all match the implementation. The PRD's `ARCHIVED`/`DEACTIVATED` states have no transition endpoint in either the endpoint table or the implementation, and the prose never promises one — not a mismatch, left as-is.

---

**PIPELINE COMPLETE.** All 9 steps finished. Final state: 71/71 tests pass across all 8 parallel stability rounds. Artifacts: SCAFFOLD trio, PRD.md, PRD_FINALIZED.md (byte-identical to PRD.md), PRD_COMPLETED.md (+3 ambiguity-pins), test_helpers/, test_suite/ (72 generated → 71 after 1 PRD-First deletion), workspace/implementation/.

