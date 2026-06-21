# Worklog — task_0163_book_publishing_royalties

Scenario: Book Publishing & Royalties: title/edition/format, advance/royalty tier escalator, reserve against returns, subsidiary rights (foreign/audio/film), author statement, returns reserve liquidation, agent commission

Target difficulty (Step 2 scaffold only): Expert

## Step 1: Create task directory — 2026-06-05T00:00:00.000Z

Created `tasks/task_0163_book_publishing_royalties/` and `tasks/task_0163_book_publishing_royalties/workspace/` using the pre-assigned index (no auto-scan).

## Step 2: Generate scaffold (Expert) — 2026-06-05T00:00:00.000Z

All three scaffold artifacts are generated, internally consistent, and pass the lint cleanly.

Generated the **Expert-tier** scaffold for `task_0163_book_publishing_royalties` (Book Publishing & Royalties domain). All three files written to `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0163_book_publishing_royalties/`.

**Complexity profile:** ledger_reconciliation (primary) + compliance_audit (secondary); layers = dual_variant_calculation, cascading_side_effects, derived_field_reconciliation, optimistic_concurrency; hybrid topology; branching state-machine shape; peer_roles RBAC; immediate consistency.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **12 entities:** Author, Agent, Contract (OCC parent / aggregate root), Title, Format, RoyaltyTier, SalesPeriod, SalesRecord, ReturnsReserve, SubsidiaryRight, AuthorStatement, StatementLine (immutable, common_fields:false). 15 FKs, all with reverse-reachability GETs.
- **6 state machines:** Contract (DRAFT→ACTIVE→TERMINATED), Title (DRAFT→PUBLISHED→OUT_OF_PRINT), SalesPeriod (OPEN→CLOSED→STATEMENTED), AuthorStatement (branching DRAFT→FINALIZED→PAID), ReturnsReserve (HELD→LIQUIDATED), SubsidiaryRight (branching REGISTERED→{STATEMENTED,VOID}).
- **2 concurrency rules:** OCC on Contract.version for statement finalize and pay (412 ERR_STALE_CONTRACT_VERSION).
- **5 calculations:** tiered_royalty_escalator (per-format-then-sum rounding pinned), returns_reserve_sizing, reserve_liquidation (provisional vs committed variants), statement_reconciliation (waterfall: royalty→reserve→subsidiary→recoup→commission→tax, with commission-base dual variant), subsidiary_author_income.
- **16 validation rules** (priority-ordered across auth/existence/state/business categories).
- **43 endpoints**, **19 error codes**, **3 roles** (Publisher opaque; Author/Agent entity_backed read-scoped).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** **18 instances** — all 9 Difficulty Rules × 2 instances each, every rule's differentiation clause honored (different entity domains / formula modes / error-category pairs / interval semantics / conserved quantities). Rule 8 (temporal-overlap) realized as period-sequence point-occupation vs royalty-tier closed-range overlap.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **39 active instances** across all 9 claim-extraction sections (entities 12, state_machines 8, calculations 4, validations 4, endpoints 2, errors 2, rbac 3, cross_cutting 3, consistency_model 1), including the OCC stale-version negative-test path.

**Verification:** All asserted monetary literals were computed in Python against the formulas (round_half_up, integer cents) and confirmed. 57 unique instance names, zero collisions across both design files. `scaffold_lint.py` verdict: **clean lint** (561 calls scanned, all conform to §1.5; all FKs reverse-reachable).

Design note: `api_prefix` is set to `""` (empty root) because the domain spans many top-level collections.

## Step 3: Copy shared files — 2026-06-05T00:00:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0163_book_publishing_royalties/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-05T00:00:00.000Z

Endpoint count matches exactly (43 in scaffold, 43 in §4 table). The PRD is complete.

**Output:** `workspace/PRD.md`

**Structure:** 5 top-level sections, 20 subsections (`### 2.1`–`2.10`, `### 3.1`–`3.10`), 268 lines.
- §2 (Global): 10 subsections — RBAC, fixed §2.2 envelope, pagination, common properties, hierarchical consistency, nested retrieval/referential, monetary precision, numeric ranges, OCC, validation ordering.
- §3 (Business Logic, scattering zone): 10 subsections organized by lifecycle/process — parties+contracts+tiers, catalogue, periods+sales posting, subsidiary rights, statement generation, finalize/pay reconciliation, the tier escalator, reserve sizing+liquidation, the settlement waterfall, read access.

**Coverage documented:**
- **Entities:** all 11 (Author, Agent, Contract, Title, Format, RoyaltyTier, SalesPeriod, SalesRecord, ReturnsReserve, SubsidiaryRight, AuthorStatement, StatementLine). `RoyaltyTier`/`StatementLine` explicitly noted as `common_fields: false` (only `id`+`created_at`).
- **State machines:** 6 (Contract; Title; SalesPeriod; AuthorStatement; ReturnsReserve; SubsidiaryRight) — all transitions, preconditions, cascade side-effects in prose.
- **Calculations:** all 5 (tiered_royalty_escalator; returns_reserve_sizing; reserve_liquidation; statement_reconciliation waterfall; subsidiary_author_income) — precise prose, reconstruction-safe.
- **Endpoints:** 43 (§4 table, matches scaffold exactly).
- **Errors:** 19 (§5 table; every ID also surfaced in §2/§3 trigger narrative).

**Hard Contracts (all PASS):** Field-Name Coverage 54/54 + 9/9 identifiers (fixed one initially-missing `title_id`); Rule Coverage (both OCC rules, validation ordering, cascades, all 5 pinned-order semantics, both range-collision semantics); §3 Path Purity (328 tokens, 0 slash-paths / 0 bare methods).

**Notable decisions:** both OCC rules collapsed into §2.9 (shared error_id/412/occ_field), each write_endpoint framed in stale-version terms; validation priority rendered as ordered narrative in §2.10 (auth→authz→existence→well-formedness→domain, state-conflict-before-OCC tie-break); provisional-vs-committed divergence documented for escalator + reserve liquidation.

## Step 5: Generate unit tests — 2026-06-05T00:00:00.000Z

Clean collection of all 75 tests with zero errors. Everything is in place.

Generated complete test infrastructure for **task_0163_book_publishing_royalties** purely from the four task inputs + the unit-test-generator skill spec.

**Test files: 6** (plus `conftest.py`)
- `test_01_royalty_escalator.py` — tiered escalator, per-format rounding order, boundary precision
- `test_02_reconciliation_and_reserves.py` — waterfall reconciliation, reserve sizing/liquidation, finalize cascade chain, conservation
- `test_03_statement_lifecycle.py` — branching state machine, tax-at-pay, subsidiary fork, bubble-up, terminal lockdown, version bumps
- `test_04_validations_and_concurrency.py` — validation precedence, temporal/range collisions, cross-entity state deps, OCC
- `test_05_entities_and_access.py` — CRUD, computed fields, filtered listings, immutable ledger lines, RBAC scoping
- `test_06_difficulty_second_angles.py` — the mandatory second assertion-angle for every depth instance

**Total test functions: 75**
- **Queue A (Difficulty): 36 tests** — all 18 depth instances, each covered by exactly 2 tests (primary scenario + a distinct second observable), satisfying the ≥2-per-instance rule.
- **Queue B (Corner): 39 tests** — all 39 non-stub corner instances, each covered exactly once (≥1 rule).

**Instances SKIPPED: 0.** Every depth and corner instance had verbatim PRD coverage and uniquely-derivable outcomes, so the PRD-first two-condition filter passed for all 57 instances. No `excluded_because:` stubs in the corner index.

**test_helpers files written (9):** `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`.

**Audits passed:** all 75 tests have exactly one verbatim-from-yaml `Design:` tag; difficulty 18/18 ≥2 tests, corner 39/39 ≥1 test; all 105 PRD citation spans (≥12 chars) survive a literal grep of PRD.md; no scaffold/section-table leakage; no skip/xfail markers; all files byte-compile; full pytest collection succeeds (75 items, 0 errors). Numeric expecteds (per-format 555c→112, straddle gross 1950000, net_to_author 2045312) independently recomputed against PRD formulas and match.

## Step 6: Generate implementation — 2026-06-05T00:00:00.000Z

Implementation complete. All source written, server boots cleanly via `start.sh`, and a comprehensive end-to-end exercise of the reconciliation pipeline, RBAC, validations, and edge cases passes.

**Source files written** (under `workspace/implementation/`):
- `app.py` — Flask entry point, blueprint registration, error handlers (maps `ApiError`/404/405/500 to the error envelope), binds `0.0.0.0:$PORT` (default 10000), `threaded=True`
- `db.py` — in-memory store: one dict per entity collection keyed by UUID; `make_common` (id/created_at/updated_at/version) and `make_light` (id/created_at only, for RoyaltyTier + StatementLine); `touch` bumps updated_at + version. No seeding.
- `errors.py` — `ApiError` class + all 19 PRD §5 error IDs with factory helpers
- `response.py` — success (object/array) and error envelopes: `meta`/`response_type`/`data`, `req_` + 20-char id, ISO-8601 UTC 3-fractional-digit timestamps, pagination fields in `meta`
- `middleware.py` — `X-User-Role`/`X-User-ID` extraction, role validation, Publisher gate, output serialization (strips internal `_`-prefixed fields)
- `services/` — `validate.py`, `money.py` (Decimal ROUND_HALF_UP), `listing.py` (created_at sort + paginate), `access.py` (Author/Agent ownership scoping), `statement.py` (the calculation engine)
- `routes/` — `parties.py`, `contracts.py`, `catalogue.py`, `periods.py`, `rights.py`, `statements.py`
- `start.sh`, `requirements.txt`

**Endpoints implemented: 44** — every route in the PRD §4 / scaffold §1.5 table, plus all reverse-reachability GETs.

**State machines (5/6 families):** Contract (DRAFT→ACTIVE→TERMINATED), Title (DRAFT→PUBLISHED→OUT_OF_PRINT with format-deactivation cascade), SalesPeriod (OPEN→CLOSED→STATEMENTED), AuthorStatement (DRAFT→FINALIZED→PAID), ReturnsReserve (HELD→LIQUIDATED), SubsidiaryRight (REGISTERED→STATEMENTED|VOID). All preconditions, ordering, OCC enforced; state conflicts surface ahead of stale-version (PRD §2.10).

**Calculations (5):** tiered royalty escalator (per-format-then-sum, segment-level round-half-up, against `lifetime_net_units` baseline — verified 4¢ not 3¢); returns-reserve sizing; reserve liquidation (consumed from exact `held*charged/units` ratio — verified 35000·50/300→5833); statement reconciliation waterfall (royalty→reserve_released→subsidiary→earnings→recoup→commission→tax-at-pay→net, commission on post-recoupment payable); subsidiary author income. All integer cents via Decimal ROUND_HALF_UP.

**Finalize cascade** wired atomically: debit unrecouped advance, increment lifetime_net_units, liquidate eligible reserves, statement subsidiary rights, create new HELD reserve, transition period→STATEMENTED, emit StatementLines (one per non-zero component), bump contract version. Tax + TAX_WITHHELD/NET_PAYABLE lines applied only at pay.

**Storage:** in-memory module-level dicts only — no SQLite, no disk, no /tmp. Fresh `start.sh` boot verified to wipe all state.

**start.sh boot:** `set -euo pipefail`, `cd` to script dir, guarded dep install (`if ! python3 -c "import flask"`), then `exec python3 app.py` foreground reading `$PORT` and binding `0.0.0.0`.

## Step 7: Run tests and iterate — 2026-06-05T00:00:00.000Z

Clean across the board. All 8 parallel rounds collected the identical 75-test set, every test `passed`, zero `failed`, zero `errors`, zero `skipped` (no skip/xfail masking). The exit condition `passed == total` holds for all 8 rounds, so no diagnostic protocol, deletions, or fixes were required.

- Iterations run: 1 (the very first 8-round parallel stability sweep came back clean).
- Sweep result: all 8 rounds reported `passed=75, total=75, failed=0, errors=0, skipped=0`. The union of failing tests across all 8 rounds is empty, so there is no flakiness signal to chase.
- Tests deleted: none.
- Fixes applied to test_helpers/: none.
- Fixes applied to implementation/: none.

Orchestrator independently re-verified all 8 `results.{1..8}.json` files: each shows tests_passed=75/75 and top-level passed=75/total=75.

Note (subagent): a first summarizing script keyed on a nonexistent `outcome` field instead of `status`, which briefly made every test look like a failure — corrected to `tests[].status`, confirming 75/75 passed in every round.

## Step 8: Finalize PRD — SKIPPED — 2026-06-05T00:00:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes (zero iterations beyond baseline). `PRD.md` already determined every behavior the implementation exhibits, so no `PRD_FINALIZED.md` is produced. Step 9 will start from `PRD.md`.

## Step 9: Complete PRD — eliminate residual ambiguity — 2026-06-05T00:00:00.000Z

All six edits applied cleanly as in-paragraph revisions, no structural changes.

**File counts:** PRD.md = 267 lines / 42,673 chars → PRD_COMPLETED.md = 267 lines / 44,107 chars (char-delta +1,434; line-delta 0 — all edits in-paragraph).

**Change counts:** ambiguity-pins = 4, mismatch-revisions = 2 (total 6 edits, no new sections/paragraphs).

**Per-change bullets:**
- §2.6 Nested Resource Retrieval — revise — mismatch — PRD said body FK existence (`ERR_NOT_FOUND`) is checked right after path identifiers; impl resolves body FKs only after the body is parsed and range-validated, so out-of-range + bad-FK surfaces the range/well-formedness error first — `routes/contracts.py:34-44`, `routes/periods.py:114-119`
- §2.10 Validation Ordering and Priority — revise — mismatch — same ordering correction: split path-identifier existence (before body inspection) from body-FK existence (after well-formedness and range) — `routes/contracts.py:33-44`, `routes/periods.py:111-119`
- §3.1 Contracts (`agent_id`) — insert — ambiguity — PRD said `agent_id` "defaults to absent"; pinned that impl persists/serializes it as a present `null`-valued field, not omitted — `routes/contracts.py:53`, `middleware.py:27-29`
- §3.1 Royalty Tiers (`upper_unit`) — insert — ambiguity — PRD said `upper_unit` "absent" for the open tier; pinned that impl stores/returns it as `null` — `routes/contracts.py:211,219-224`
- §3.4 Subsidiary Rights (`statement_id`) — insert — ambiguity — PRD said `statement_id` "absent until credited"; pinned that impl emits it as a present `null` field until credited and that voiding leaves it `null` — `routes/rights.py:50,90-91`
- §3.6 StatementLine emission — insert — ambiguity — PRD named the line types and credit/deduction sign convention but never mapped each `line_type` to a specific monetary field, sign, emission order, or the zero-emission rule; pinned the full mapping (ROYALTY=+gross_royalty, RESERVE_WITHHELD=−reserve_held, RESERVE_RELEASED=+reserve_released, SUBSIDIARY=+subsidiary_income, ADVANCE_RECOUP=−advance_recouped, AGENT_COMMISSION=−agent_commission at finalize in that order for non-zero components; TAX_WITHHELD=−tax_withheld at pay only when non-zero; NET_PAYABLE=+net_to_author always at pay) — `routes/statements.py:219-229,274-276`
- §3.10 Read Access filters — insert — ambiguity — PRD listed the `email`/`status`/`line_type`/`format_id`/`author_id`/`agent_id` filters but not their matching semantics; pinned exact-equality matching with an unmatched value yielding an empty page rather than an error — `routes/parties.py:54-57,97-100`, `routes/rights.py:59-62`, `routes/statements.py:109-115,287-289`, `routes/periods.py:148-151`, `routes/contracts.py:85-95`

**Deliberately unchanged:** §2.7 already pins `reserve_unit_value_cents` full-precision behavior; activation-readiness vs tier-coverage ordering already named in §3.1 (strict order would over-specify); `memo` free-text already marked "snapshotted". Tests used only as auxiliary cross-reference, never authority.

---

## Pipeline complete

All 9 steps finished. Final tree under `tasks/task_0163_book_publishing_royalties/`:
- SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml (Expert tier)
- test_helpers/ (9 files) + test_suite/ (conftest + 6 test files, 75 tests)
- workspace/INSTRUCTION.md, PRD.md, PRD_COMPLETED.md (PRD_FINALIZED.md absent — Step 8 skipped), implementation/ (Flask, in-memory, start.sh)
- 8/8 stability-sweep rounds at 75/75 passed.
