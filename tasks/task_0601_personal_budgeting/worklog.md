# Worklog — task_0601_personal_budgeting

## Step 1: Create Task Directory — 2026-06-21

Created `tasks/task_0601_personal_budgeting/` with `workspace/` subdir. Index 0601 chosen as max existing task index (0600) + 1.

## Step 2: Generate Scaffold — 2026-06-21

All three scaffold artifacts are generated and validated for `task_0601_personal_budgeting`.

Generated three files under `tasks/task_0601_personal_budgeting/`:

- **SCAFFOLD.yaml** — §1.0–§1.7 plus preamble. 10 entities, 44 endpoints, 16 error codes, 5 calculations, 6 state machines, 16 validations, 3 roles, 1 concurrency rule.
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** — single key `scaffold_difficulty_design`; 9 rule_ids × 2 instances = 18 instances.
- **SCAFFOLD_CORNER_DESIGN.yaml** — single key `scaffold_corner_design`; 34 corner instances (32 active + 2 `excluded_because` stubs).

### Design highlights
- **Archetype**: ledger reconciliation + posture-driven gating. Aggregate root `Household` (computed `posture` HEALTHY/OVERSPENT/FROZEN) gates child writes; nested `Account → Transaction` tree with cross-aggregate refs (`Transaction → BudgetCategory`, `Goal → BudgetCategory`).
- **Dual-variant calcs across domains**: cleared vs pending-aware `net_worth_rollup` (account domain) and allocated vs available `envelope_accounting` (budget domain).
- **Non-linear state machines on different entities**: `Transaction` POSTED↔RECATEGORIZED cycle; `Goal` ACTIVE↔FUNDED cycle + ACTIVE→ABANDONED branch.
- **Cascades**: transaction-post → envelope → posture (depth 3) and remove → envelope → posture (depth 2).
- **Compensating invariants** on two conserved quantities: goal-abandon conserves envelope `available_cents`; post/remove conserves account `cleared_balance_cents`.
- **OCC** via `Household.version` on period close (412).

### Key correction during generation
Rule 8 (temporal overlap) initially had both instances on `BudgetPeriod`, violating its "different resource entities" clause. Added a recurring-bill due-day slot rule (`ERR_BILL_SLOT_CONFLICT`, ±2-day buffer) on `RecurringBill` so the two overlap instances sit on different entities with different interval semantics.

### Validation
`scaffold_lint.py` verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`
All single-resource and filtered-list GETs use a flat `/households/<segment>` form; action/transition POSTs retain nested paths. Hard constraint honored — no sibling task directories were read.

## Step 3: Copy Shared Files — 2026-06-21

Copied root `INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-21

The PRD has been generated at `workspace/PRD.md` (248 lines).

Generated a prose PRD for the Personal Budgeting & Account Aggregation domain (task_0601) from the scaffold. Structure:
- **§1 Introduction** — 3 paragraphs framing consistency/reconciliation and posture-gating themes.
- **§2 Global Specs** — 11 domain-derived subsections: RBAC (3 roles; HouseholdOwner/HouseholdMember as entity-backed Member, PlatformAdmin opaque), verbatim §2.2 envelope, pagination, money/precision (integer cents, no rounding), common-property + reconciliation semantics (GoalContribution has only id/created_at), nested-retrieval + reference integrity, priority-ordered validation ladder, freeze gate, OCC on period close, net-worth rollup (cleared vs projected), envelope accounting.
- **§3 Business Logic** — 7 lifecycle subsections: provisioning, account linking, Transaction state machine (PENDING→POSTED→RECATEGORIZED cyclic, →REMOVED) with cascades, auto-categorization ranking, budget period open/allocate/zero-based close/rollover, goals/sinking funds (threshold >=, FUNDED↔ACTIVE cycle, abandon reversal), recurring bills + dual-variant cash-flow forecast with ±2-day slot-conflict rule and logical-clock default 2026-01-01T00:00:00Z.
- **§4** 4-column endpoint table (all 44 endpoints); **§5** 2-column error table (all 16 errors).

### Hard Contract Reports
- Field coverage: 50 required, 50 present, 0 missing — PASS
- Rule coverage: 16 validations, 1 OCC, all state transitions, 5 calculations, sibling-branch symmetry — PASS
- Path purity (§3 only): 280 backtick tokens scanned, 0 path/method tokens — PASS

Withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened or referenced.

## Step 5: Generate Unit Tests — 2026-06-21

Test infrastructure generation is complete.

Generated complete test infrastructure under `tasks/task_0601_personal_budgeting/`.

### Stage 1 — `test_helpers/` (8 modules + barrel)
- **types.py** — entity TypedDicts + status/role enums. `GoalContribution` carries only `id`+`created_at` (common_fields:false); others carry `version`/`updated_at`.
- **api_client.py** — one method per endpoint.
- **api_errors.py** — all 16 error IDs with PRD §5 HTTP-status map.
- **assertions.py**, **factories.py**, **constants.py** — per-entity assertions, input-only payload factories, domain thresholds.
- **test_users.py** — PlatformAdmin opaque (shared constant); HouseholdOwner/HouseholdMember entity_backed:Member, per-instance builders `make_owner_headers(member_id)`/`make_member_headers(member_id)`.
- **fixtures.py** — composite setup helpers.

### Stage 2 — `test_suite/` (conftest + 9 test files, 68 test functions)
Domain-organized, simple→complex.

### Design-index contract — fully satisfied
- All 18 difficulty instances (queue A) covered with exactly 2 tests each.
- All 32 non-stub corner instances (queue B) covered with ≥1 test each.
- Both `excluded_because:` stubs correctly not translated.
- Every test docstring carries verbatim PRD citation + one `Design:` tag. No instances skipped.

### Validation
All 17 files compile; modules import cleanly against stub framework; PRD citations grep-verified.

## Step 6: Generate Implementation — 2026-06-21

The implementation is complete at `workspace/implementation/`.

### Structure
- `start.sh` — foreground launcher, guards dep install on `import flask`, `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000), `uv pip` fallback.
- `app.py` — entry point, blueprint registration, error-envelope handlers.
- Foundation: `db.py` (empty-on-boot in-memory, no seeding), `errors.py`, `response.py`, `middleware.py`, `helpers.py`, `serializers.py`, `lookups.py`, `clock.py` (logical clock default 2026-01-01T00:00:00Z).
- `routes/` — one blueprint per resource group.
- `services/` — `reconcile.py`, `categorize.py`, `forecast.py`.

### Spec fidelity (smoke-tested)
Response envelope per §2.2; auth roles/scoping; ledger reconciliation (cleared/available, dual net-worth, envelope, posture cascade with freeze dominance); state machines (transaction/goal/period/account/bill); calculations (zero-based close + OCC 412, rollover-carry, auto-categorize, goal funding >= boundary, bill slot conflict ±2-day, forecast variants); validation ordering per §2.7.

### Note
Local python3 (3.14) lacks pip; grading harness runs pip-capable env. App validated locally via `uv run --with flask python app.py`; boots clean from fresh process, store empty on every boot.

## Step 7: Test and Fix Loop — 2026-06-21

Clean. All 8 parallel rounds pass.

**Iterations run:** 1 (after the start.sh fix; baseline failed only on server boot, not on any test logic).

**Root cause:** The server never started in this environment, so all 8 baseline rounds reported `ServerStartError: Server process exited prematurely with code 2`. The original `start.sh` tried to install Flask via `python3 -m pip` (host system `python3` is 3.14 with no pip) and fell back to `uv pip install --system` — which the externally-managed interpreter rejected. Flask was never importable, so `python3 app.py` exited immediately.

**Fix applied (implementation only):**
- `workspace/implementation/start.sh` — Rewrote dependency bootstrap to provision a dedicated local virtualenv with `uv venv` and install `requirements.txt` via `uv pip install --python .venv/bin/python`, then `exec .venv/bin/python app.py`. Guarded by idempotent `needs_provision` check (steady-state no-op) and serialized with `flock` on `.venv.lock` so 8 concurrent first-boots don't race. Venv holds only dependencies — no entity/state persistence, so per-test reboots still wipe all in-memory data.

**Tests deleted:** None — no test asserted a scaffold-only rule or non-uniquely-derivable outcome; failures were purely boot-environment.

**Fixes to test_helpers/:** None.

**Final result:** 8/8 parallel rounds passing, 68/68 tests each round.

## Step 8: Finalize PRD — 2026-06-21

Done. PRD_FINALIZED.md is a verbatim copy of PRD.md.

**Line counts:** PRD.md = 248; PRD_FINALIZED.md = 248. Delta: 0 lines, 0%.

**Changes:** None — byte-for-byte identical.

The single `<step_7_diff>` item was the `start.sh` venv-provisioning fix. Subject: server boot / dependency provisioning / launcher. Impl paths inspected: `start.sh`, `requirements.txt` — provisions a venv (only `flask==3.0.3`), serializes concurrent first-boots with a file lock, `exec`s unchanged `app.py`. Touches no application state, entities, derived-field logic, endpoint behavior, validation, or reconciliation. Pure boot/launcher fix with zero application-behavior content → reveals no PRD silence or mismatch → verbatim copy is the correct outcome. No edits invented.

## Step 9: Complete PRD — 2026-06-21

All five edits applied cleanly. PRD_COMPLETED.md is a minimal patch over PRD_FINALIZED.md.

**Line/char delta:** PRD_FINALIZED.md = 248 lines / 41,660 chars → PRD_COMPLETED.md = 248 lines / 42,514 chars (+854 chars, +0 lines; all in-paragraph inserts).

**Counts:** ambiguity-pins = 4, mismatch-revisions = 1.

**Changes:**
- §2.3 Pagination — insert — ambiguity — out-of-range `limit`/`offset` are clamped (not rejected); non-integer values yield `ERR_INVALID_REQUEST` — `helpers.py:104-114`.
- §3.3 Transaction Lifecycle (ingest) — insert — ambiguity — `merchant_name` required and non-empty — `routes/transactions.py:32-33`.
- §3.5 Budget Period (patch income) — revise — mismatch — impl enforces no period-state precondition on PATCH and refreshes `updated_at`/`version`; dropped the OPEN restriction — `routes/budget_periods.py:94-108`.
- §3.5 Budget Period (close) — insert — ambiguity — next period's `month` is the calendar month after the closed period; its `income_expected_cents` begins at zero — `routes/budget_periods.py:150-153`.
- §3.7 Recurring Bills (create) — insert — ambiguity — non-positive `amount_cents` yields `ERR_INVALID_REQUEST` — `routes/recurring_bills.py:65-66`.
- §3.7 Cash-Flow Forecast — insert — ambiguity — response shape: top-level object with `points` (chronological `{date, projected_balance_cents}`), `min_projected_balance_cents`, `shortfall`; each `date` an ISO 8601 UTC midnight `...T00:00:00.000Z` at three fractional digits — `services/forecast.py:48-61`, `clock.py:46-49`.

**Deliberately not changed:** One §2.7 ordering divergence on ingest (impl checks `ERR_ACCOUNT_ARCHIVED` before the `budget_category_id` reference check) left unchanged — manifests only in a doubly-degenerate request and rewriting the sweeping §2.7 priority contract would be non-minimal. Goal-contribution positivity ordering, `state` alias field, mismatched-parent `ERR_NOT_FOUND`, and `frozen_by_owner` were already adequately pinned by existing prose.

---

## Pipeline complete — all 9 steps finished. Final: 68/68 tests passing across 8/8 parallel rounds.
