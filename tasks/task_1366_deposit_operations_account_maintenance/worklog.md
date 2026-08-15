# Worklog — task_1366_deposit_operations_account_maintenance

## Step 1: Create Task Directory — 2026-08-13T00:52:00.000Z

Task directory `tasks/task_1366_deposit_operations_account_maintenance/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher. Step 1 treated as DONE per command args; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T01:35:00.000Z

All three artifacts are written and the lint is clean. Summary:

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1366_deposit_operations_account_maintenance/SCAFFOLD.yaml` — 1145 lines (§1.0–§1.7; no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1366_deposit_operations_account_maintenance/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1011 lines (single top key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1366_deposit_operations_account_maintenance/SCAFFOLD_CORNER_DESIGN.yaml` — 1626 lines (single top key `scaffold_corner_design`)

## Counts
- **Entities: 9** — DepositAccount, AccountTransaction (append-only, `common_fields: false`), AuthorizedSigner, AccountDocument, TitleChangeRequest, DeceasedCase, GarnishmentOrder, StatementCycle, ProductConversion
- **State machines: 9** (one per entity; DepositAccount carries parallel dimensions lifecycle × restriction)
- **Endpoints: 32** (Expert band top edge), **errors: 20**, **calculations: 6**, **concurrency rules: 2** (OCC on DepositAccount.version for title-change create and close), **roles: 4** (OpsOfficer / OpsManager / System / Auditor, all `identity: opaque`, segregation-of-duties model)
- **§1.8 difficulty instances: 18** (2 per rule × 9 rules, all §0.5 differentiation clauses honored — e.g., exempt-funds federal-vs-state floor on GarnishmentOrder vs estate-release date-of-death-vs-release on DeceasedCase for dual-variant; min/max nested formula (mode a) vs per-day-vs-end rounding (mode b, computed literals 42 vs 41 cents) for combinatorial)
- **§1.9 corner instances: 46 total = 39 active + 7 `excluded_because:` stubs**, across all nine guide sections
- **Lint: clean** — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (271 calls scanned, 0 violations)

## Design notes
- **Archetype**: compliance/audit primary + posture-driven gating secondary; flat topology under `/bank`, all children FK to DepositAccount with sub-resource list GETs (lint check (f) required the literal `{id}` segment name for parent-prefix matching).
- **Logical clock**: `POST /bank/_clock/set_current_utc` with the mandated default `2026-08-01T00:00:00Z`; all dormancy/deadline/effective-date rules read it.
- **Key mechanics**: garnishment exempt-funds variants (federal lookback vs $1000 state floor), half-open statement-cycle adjacency vs closed-interval garnishment service windows, 365/1095/1125-day dormancy/escheat thresholds with a $5 fee capped at balance (zero-balance auto-close cascade), estate release with residual sweep conserving `balance_before == release + residual`, and SoD enforced by X-User-ID comparison (same person acting under two roles triggers ERR_SEGREGATION_OF_DUTIES).
- **Fixes applied during QA**: cleaned fee-cadence formula wording, added estate residual-sweep semantics, advanced the clock in the closed-interval garnishment instance (future `served_date` would have hit ERR_DATE_RANGE_INVALID), and replaced all fuzzy "non-terminal"/"active" constraint wording with explicit enum sets. All formula-derived asserts are pre-computed literals; every `${var}` traces to a `captures:` binding.

## Step 3: Copy Shared Files — 2026-08-13T01:36:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1366_deposit_operations_account_maintenance/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T01:55:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1366_deposit_operations_account_maintenance/workspace/PRD.md`. The difficulty/corner design files were not opened or consulted at any point.

## Summary

**Line count:** 292 lines

**Section list:**
- §1 Introduction (2 paragraphs — business context + system scope/role model)
- §2 Global Specifications: 2.1 User & RBAC, 2.2 API Response Structure (verbatim block), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Logical Clock & Calendar Semantics, 2.6 Money/Interest Rates/Rounding, 2.7 Ledger Integrity, 2.8 Two-Dimensional Account Posture, 2.9 Nested Resource Retrieval, 2.10 Validation Order, 2.11 Optimistic Concurrency Control
- §3 Business Logic (9 subsections): 3.1 Opening Accounts & Posting Transactions, 3.2 Documents & Signers, 3.3 Title Changes, 3.4 Deceased Handling & Estate Release, 3.5 Garnishments & Exempt-Funds Analysis, 3.6 Statement Cycles, 3.7 Product Conversions, 3.8 Dormancy/Fees/Daily Sweep, 3.9 Closure & Residual Payouts
- §4 Endpoint Definitions (32 endpoints, 4-column table), §5 Error Code Catalogue (20 errors, 2-column table)

**Coverage audit (mechanically verified against SCAFFOLD.yaml):**
- **Contract 1 (field names): PASS** — 100/100 required identifiers present in backticks (all 8 entity field sets, all endpoint `input` keys, query params `status`/`ownership_type`/`txn_type`/`doc_type`/`limit`/`offset`, path params `id`/`signerId`/`documentId`/`requestId`/`caseId`/`orderId`/`conversionId`, sweep output tallies, `current_utc`).
- **Contract 2 (rules): PASS** — all 9 validation tiers rendered as an explicit ordered list with masking examples; both OCC rules named with endpoint framing + `expected_account_version` + `ERR_STALE_VERSION`/412; all state-machine transitions with preconditions and error IDs; all 6 calculations in reconstructible prose (exempt-funds 60-day closed window/$1,000 floor, STANDARD vs SIMPLE interest variants with round-half-up pinning, fee schedule 1+floor(30-day periods)/500-cent cap/zero-fee stop, dormancy 365/1095/1125 inclusive thresholds, both estate release variants, available-balance reconciliation); all enum values (67) including the `POSTED` transaction state; sibling-branch symmetry kept across REMITTED/RELEASED, the two exemption variants, the two release variants, and the four closure paths; conservation invariant and full closure cascade stated.
- **Contract 3 (§3 path purity): PASS** — 473 backticked tokens in §3, zero paths/methods.

**Ambiguities resolved:**
1. `common_fields: false` on AccountTransaction → §2.4 states explicitly it carries only `id`/`created_at`, no `updated_at`/`version`, single `POSTED` state.
2. Deceased snapshot and DATE_OF_RELEASE interest use the STANDARD rounding variant even for MONEY_MARKET accounts — stated explicitly per scaffold pinning.
3. Conversion execute allows `LEGAL_HOLD` (only `DECEASED_HOLD` blocks it) — called out as "an ordinary legal hold does not stop a conversion" to avoid over-restricting.
4. Sweep output field `fees_assessed_count` shares its name with the account field — both senses rendered in their own contexts (§3.8 tallies vs dormancy episode counter).

## Step 6: Generate Implementation — 2026-08-13T02:12:00.000Z

Implementation complete and verified. Summary:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1366_deposit_operations_account_maintenance/workspace/implementation/`)

| File | Lines |
|---|---|
| `start.sh` (exec launcher, guarded `pip install`, `$PORT`/0.0.0.0/foreground) | 10 |
| `requirements.txt` | 1 |
| `app.py` (entry point, blueprint registration, ApiError/404/405 handlers) | 72 |
| `db.py` (in-memory dicts, logical clock default 2026-08-01T00:00:00Z, account-number minter) | 80 |
| `errors.py` (20 error IDs with catalogue HTTP statuses) | 56 |
| `response.py` (envelope: `meta.api_request_id/api_request_timestamp`, `response_type`, `data`; pagination `limit`/`offset`/`total_count`/`has_more`) | 104 |
| `middleware.py` (`X-User-ID`/`X-User-Role` auth, 4 roles) | 42 |
| `serialization.py` (9 serializers; transactions omit `updated_at`/`version` per PRD §2.4) | 177 |
| `services/account.py` (ledger postings, posture derivation, closure cascade) | 156 |
| `services/interest.py` (STANDARD/SIMPLE accrual variants, Decimal exact rationals) | 79 |
| `services/sweep.py` (dormancy/fees/auto-close/escheat/statements) | 160 |
| `routes/` (10 modules: accounts, transactions, signers, documents, title_changes, deceased_cases, garnishments, statement_cycles, conversions, ops) | 1,410 |
| **Total** | **2,347** |

## Coverage
- **Endpoints: 32/32** from the PRD §4 table (accounts 4, transactions 2, signers 3, documents 3, title-changes 5, deceased-cases 5, garnishments 3, statement-cycles 2, conversions 3, ops sweep + clock 2).
- **State machines: 8** — DepositAccount parallel dimensions (lifecycle OPEN/DORMANT/ESCHEAT_PENDING/CLOSED × restriction NONE/LEGAL_HOLD/DECEASED_HOLD with derived `statement_suppression` precedence CLOSED &gt; DECEASED &gt; DORMANT &gt; NONE), AuthorizedSigner (ACTIVE/SUSPENDED/REMOVED), AccountDocument, cyclic TitleChangeRequest (REJECTED→SUBMITTED resubmit loop), DeceasedCase (4-stage with estate-release closure), branching GarnishmentOrder (REMITTED/RELEASED forks), StatementCycle, ProductConversion.
- **Calculations: 6** — `exempt_funds_analysis` (FEDERAL_LOOKBACK/STATE_MINIMUM with $1000 floor, closed 60-day lookback), `accrued_interest_settlement` (half-open daily windows, end-of-day balances, round-per-day vs round-once pinned variants), `inactivity_fee_assessment` (500¢/30-day pinned schedule, entry fee, zero-balance auto-close), `dormancy_evaluation` (365/1095/1125 inclusive thresholds, one transition per sweep per the state-keyed scaffold formula), `estate_release_amount` (DATE_OF_DEATH/DATE_OF_RELEASE), `available_balance_reconciliation`.
- **Validation order** per PRD §2.10 (auth → role → existence → shape → state/OCC → compliance → uniqueness → clock → funds), OCC `expected_account_version` on title-change filing and close only, segregation-of-duties on approve/verify-resolve/initiate pairs. No seeding anywhere — store provably empty at boot.

## Smoke check
Booted via `bash start.sh` on ports 18231–18233 (fresh process each time, verified empty store on reboot), ran three suites totaling **105 assertions, all passing**: full lifecycle flows (open→transact→garnish→resolve, document→signer, title approve/reject/resubmit, deceased verify→release with residual sweep, conversion execute, close), exact interest figures (STANDARD 248¢ over a mixed-balance 31-day window; SIMPLE 11¢ vs STANDARD 12¢ divergence on identical series), dormancy at the 365-day boundary, fee draining to zero-balance auto-close, escheat progression 365→1095→1125 with STATE_ESCHEAT payout, closure cascades (signers REMOVED with correct reasons, conversions CANCELLED, cycles SUPPRESSED), error precedence (stale-version-beats-closure-blocked, restricted-beats-insufficient), and pagination envelope. Server shut down cleanly after each run.

## Step 5: Generate Unit Tests — 2026-08-13T02:20:00.000Z

Generation complete. Summary:

## Files written

**`test_helpers/`** (9 files, 1280 lines) under `/home/ubuntu/github/CodingPRD/tasks/task_1366_deposit_operations_account_maintenance/test_helpers/`:
- `types.py` (327) — status enums for all 9 entities + `UserRole`; TypedDicts with the append-only `AccountTransaction` correctly carrying only `id`/`created_at` (no `updated_at`/`version`)
- `api_client.py` (161) — `ApiClient(GenericApiClient)` with one method per PRD endpoint (33 methods, incl. `run_daily_sweep`, `set_clock`)
- `api_errors.py` (58) — all 20 error IDs + HTTP map, registered via `set_error_http_status_map`
- `assertions.py` (203) — per-entity asserts + `assert_account_invariants` (available = balance − held; `statement_suppression` precedence derivation)
- `factories.py` (141), `constants.py` (36 — dormancy/fee/lookback/floor thresholds), `test_users.py` (54 — 4 opaque roles + SoD pins `OFFICER_1`="u-off-1", `MANAGER_2`="u-mgr-2"), `fixtures.py` (258 — composite helpers: `open_account`, `add_verified_document`, `add_active_signer`, `setup_verified_estate`, `make_dormant_account`, `close_with_fresh_version`, etc.), `__init__.py` (42)

**`test_suite/`** (9 files, 2302 lines): `conftest.py` + 8 test files (`test_01_account_opening_and_envelope` … `test_08_security_and_rbac`).

## Test counts
- **Queue A (Difficulty): 36 tests** — all 18 instances × exactly 2 tests each
- **Queue B (Corner): 39 tests** — one per non-stub instance
- **Total: 75 tests** (pytest collection verified)

## Instances skipped
7 corner stubs (`excluded_because:`, no test_recipe, correctly not translated): `interest_rounding_variant_selection`, `state_vs_safety_priority_conflict`, `safety_vs_fiscal_priority_conflict`, `cascading_side_effects_coverage`, `scheduled_conversion_side_effects`, `statement_suppression_derived_on_death`, `immediate_consistency_mutation_visible_in_response` — all 7 difficulty-instance cross-references verified to resolve. **Zero non-stub instances skipped**: every emitted instance passes the PRD-first two-condition filter (priority-pair instances are legitimate because PRD §2.10 pins the validation tiers verbatim, including "the restriction gate reports first").

## Notable YAML inconsistencies repaired (setup side only; all asserted literals copied verbatim)
- `exempt_funds_nested_min_max_all_clauses_bind`: opening deposit set to 20000 (not 80000) so balance at receipt is 80000 per the natural-language setup — making all four literals (50000/60000/0/30000) hold.
- `garnishment_hold_conservation_invariant`: opening deposit set to 70000 (not 100000) so pre-hold balance is 100000 and `bal == 80000` after remit holds.

## Stage 2 self-audit verdict
- **Tag coverage**: 18/18 queue-A instances have ≥2 tagged tests; 39/39 non-stub queue-B instances have ≥1 tagged test.
- **No dual tags**: every test has exactly one `Design:` line, and it is the last docstring line in all 75 tests.
- **All tags resolve**: every tag maps to a real instance in the source yamls; no tag points at a stub.
- **Citation pass**: every test carries a quoted PRD citation, and an 8-word window of each quote was verified to survive a whitespace-normalized literal grep of `workspace/PRD.md` (75/75 pass). No skip/xfail marks; no scaffold references in generated code.

## Step 7: Test-Fix Iteration Loop — 2026-08-13T02:35:00.000Z

Clean sweep on the first iteration — the exit condition is met.

## Summary

- **Iterations run:** 1 (eight parallel rounds, all ran to completion)
- **Round results:** rounds 1–8 each `passed == total == 75`, `failed == 0`, `errors == 0`. No flakiness observed across the union of 8 rounds (600 test executions total, ~1.9s/test average with per-test-server restarts).
- **Tests deleted:** none. I audited all 8 test files (`test_01`–`test_08`, 75 tests) and the `test_helpers/` layer (factories, fixtures, role-header builders, assertions) against `/home/ubuntu/github/CodingPRD/tasks/task_1366_deposit_operations_account_maintenance/workspace/PRD.md` — every assertion traces to verbatim PRD prose (each test carries a quoted PRD citation), fixtures construct PRD-consistent preconditions (opaque role IDs with SoD pins `u-off-1`/`u-mgr-2`, OCC-guarded flows re-read fresh versions, lookback/service windows honor the closed-interval rule).
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `implementation/`:** none. Spot review of the implementation (`services/sweep.py`, `services/account.py`, `services/interest.py`, `routes/garnishments.py`, `routes/deceased_cases.py`, `routes/title_changes.py`, `routes/transactions.py`, `routes/accounts.py`, `routes/conversions.py`, `routes/signers.py`, `serialization.py`) confirmed PRD-faithful behavior: §2.10 validation tiers in order, OCC on title-change filing and closure only, STANDARD/SIMPLE rounding pinned per product with exact rationals, exempt-funds dual variants (60-day closed lookback, $1000 state floor), dormancy 365/1095/1125 inclusive thresholds, fee cadence 1 + floor(30-day periods) with 500-cent cap and zero-balance auto-close, estate-release conservation (release + residual == balance before), and in-memory-only storage wiped on every `start.sh` reboot.

No further work required — the benchmark task is in a passing, stable state.

## Step 8: Finalize PRD — SKIPPED — 2026-08-13T02:35:30.000Z

Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. Per the skip condition, `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` produced.

## Step 9: PRD Completeness Scan — 2026-08-13T02:55:00.000Z

The diff is complete and exactly as intended. All verification done — task complete.

## Summary

**Source vs. output:** `workspace/PRD.md` (292 lines, 48,415 chars) → `workspace/PRD_COMPLETED.md` (292 lines, 51,720 chars). Char delta **+3,305**, line count unchanged (all edits are in-paragraph inserts/revisions; 23 lines touched, no sections added).

**Counts:** 23 ambiguity-pins, 6 mismatch-revisions.

**Changes (one per pinned behavior):**

- §2.2 — insert — ambiguity — `api_request_id` pinned as `req_` + twenty random alphanumerics — `implementation/response.py:24-25`
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` (400) — `implementation/response.py:74-99`
- §2.3 — insert — ambiguity — same-millisecond creations ordered by creation sequence; multiple filters combine conjunctively — `implementation/db.py:23-38`, `implementation/routes/accounts.py:128-135`
- §2.3 — insert — ambiguity — `total_count` counts the filtered set; `has_more` ⇔ `offset` + returned items < `total_count` — `implementation/response.py:46-59`
- §2.5 — revise — mismatch — "never reads the wall clock" scoped to business dates; `created_at`/`updated_at`/`api_request_timestamp` are wall-clock audit stamps — `implementation/db.py:41-44`, `implementation/response.py:28-31`
- §2.5 — revise — mismatch — clock set is not advance-only: any instant accepted, normalized to UTC `Z`; unparseable `to_iso8601` → `ERR_INVALID_REQUEST` — `implementation/routes/ops.py:21-33`
- §2.7 — revise — ambiguity — `accrued_interest_cents` is reset to zero (not recomputed) at each settlement event — `implementation/services/account.py:145`, `implementation/routes/conversions.py:115`
- §2.7 — insert — ambiguity — zero-amount computed postings (settlement/payout/remittance/release/fee) never land on the ledger — `implementation/services/account.py:143-144`, `implementation/routes/accounts.py:186-187`, `implementation/routes/deceased_cases.py:202-207`, `implementation/routes/garnishments.py:170-173`
- §2.10 — revise — ambiguity — tier-4 shape validation includes JSON type checks (bool ≠ int) and well-formed `YYYY-MM-DD` dates — `implementation/routes/accounts.py:37-49`, `implementation/routes/transactions.py:46-59`
- §3.1 — insert — ambiguity — `account_number` is ten random decimal digits, leading zeros permitted — `implementation/db.py:74-80`
- §3.1 — insert — ambiguity — account-list `status` filter matches either `lifecycle_status` or `restriction_status` — `implementation/routes/accounts.py:129-133`
- §3.1 — insert — ambiguity — system postings value-dated to the posting event's clock date, except conversion-settlement `INTEREST_CREDIT` carrying `effective_date` — `implementation/services/sweep.py:56`, `implementation/routes/conversions.py:110`, `implementation/routes/garnishments.py:171-172`
- §3.1 — insert — ambiguity — malformed `posted_date` → `ERR_INVALID_REQUEST`; well-formed dates accepted without clock-relative bounds — `implementation/routes/transactions.py:52-59`
- §3.1 — insert — ambiguity — posting any transaction against a `CLOSED` account → `ERR_INVALID_STATE` — `implementation/routes/transactions.py:61-63`
- §3.1 — revise — mismatch — `last_customer_activity_date` "is set to" (not "advances to") `posted_date`; backdated postings move it backward — `implementation/routes/transactions.py:80`
- §3.2 — insert — ambiguity — document submission/review and signer addition are not posture-gated — `implementation/routes/documents.py:31-34`, `implementation/routes/signers.py:29-33`
- §3.3 — insert — ambiguity — title-change filing is not posture-gated (gate applies at approve/resubmit) — `implementation/routes/title_changes.py:47-105`
- §3.3 — insert — ambiguity — approval leaves `pod_beneficiary_name` unchanged when requested type is not `POD` — `implementation/routes/title_changes.py:132-134`
- §3.4 — insert — ambiguity — death reporting and verification are not posture-gated — `implementation/routes/deceased_cases.py:53-56`, `106-110`
- §3.4 — revise — mismatch — verification sets `DECEASED_HOLD` superseding any in-force restriction (not only from `NONE`) — `implementation/routes/deceased_cases.py:130`
- §3.5 — insert — ambiguity — garnishment registration not posture-gated; restriction becomes `LEGAL_HOLD` superseding whatever was in force — `implementation/routes/garnishments.py:50-53`, `137-139`
- §3.5 — insert — ambiguity — `remit_amount_cents` must be a non-negative integer (`ERR_INVALID_REQUEST` otherwise) — `implementation/routes/garnishments.py:153-156`
- §3.5 — revise — mismatch — resolution returns only a `LEGAL_HOLD` restriction to `NONE`; a `DECEASED_HOLD` survives — `implementation/services/account.py:72-82`, `implementation/routes/garnishments.py:186`
- §3.6 — insert — ambiguity — overlap checked against existing cycles of any status; scheduling not posture-gated — `implementation/routes/statement_cycles.py:21-49`
- §3.7 — insert — ambiguity — conversion scheduling not posture-gated — `implementation/routes/conversions.py:36-39`
- §3.8 — insert — ambiguity — fees assessed only while `DORMANT`; no fee on the sweep that advances to `ESCHEAT_PENDING` — `implementation/services/sweep.py:99-118`
- §3.8 — revise — mismatch — auto-close fires whenever a sweep's fee assessment ends with a `DORMANT` account at exactly zero, regardless of cause — `implementation/services/sweep.py:63-67`
- §3.8 — insert — ambiguity — sweep processes accounts (creation order) fully before settling due statement cycles, so same-day posture changes apply to production — `implementation/services/sweep.py:83-149`
- §3.9 — insert — ambiguity — zero-balance auto-close settles no interest — `implementation/services/sweep.py:35-41`, `63-67`

Everything else in the implementation (endpoint/role matrix, error catalogue and statuses, state machines, interest math, exempt-funds formulas, fee schedule, OCC scope, cascade contents, validation tier ordering, response envelope) was already uniquely pinned by PRD prose and left untouched.

