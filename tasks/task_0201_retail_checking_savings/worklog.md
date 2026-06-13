# Worklog — task_0201_retail_checking_savings

Scenario: Retail Checking & Savings Account: account opening (CIP/KYC), direct deposit & ACH origination, overdraft/NSF fee tiers, courtesy-pay opt-in (Reg E/Reg DD), interest accrual/APY tiers, joint/POD ownership, dormancy & escheat, stop payment

Difficulty: Expert (§0.4 Expert calibration band) — applied to Step 2 scaffold generation only.

## Step 1: Create Task Directory — 2026-06-06T16:29:01.000Z

Task directory pre-allocated by caller: `tasks/task_0201_retail_checking_savings/` with `workspace/` subdir present. Step 1 auto-scan skipped per instructions. No new directory created.

## Step 2: Generate Scaffold (Expert) — 2026-06-06T16:46:00.000Z

Generated the complete scaffold package for **task_0201_retail_checking_savings** (Expert difficulty band), all three files passing `scaffold_lint.py` with `VERDICT: clean lint`.

### SCAFFOLD.yaml (§1.0–§1.7) counts
- **Entities: 12** — Customer, Application, Account, AccountOwner, ApyTier, Transaction, FeeAssessment, StopPayment, AchOrigination, AchLeg, InterestPosting, EscheatEvent
- **State machines: 5** — Application (branching fork-join), Account (cyclic ACTIVE↔DORMANT + FROZEN revert), Transaction (3-way branch PENDING→{POSTED,RETURNED,STOPPED}), AchOrigination (STAGED→SETTLED→REVERSED), StopPayment
- **Calculations: 7** — kyc_risk_scoring, cip_status_derivation, available_balance, overdraft_nsf_fee_tier (dual-variant), ach_settlement_posting (dual-variant), interest_accrual_apy, ach_reversal_invariant
- **Validations: 19** (priority-ordered) · **Endpoints: 47** · **Errors: 22** · **Roles: 3** (AccountHolder=entity_backed:Customer, Teller=opaque, ComplianceOfficer=opaque; segregation-of-duties model) · **Concurrency rules: 2** (OCC on AchOrigination.version for settle + reverse)

### Design files
- **§1.8 SCAFFOLD_DIFFICULTY_DESIGN.yaml: 18 instances** (all 9 rules × 2), every formula-derived assert pre-computed as a literal (KYC scores, fee tiers, interest truncation, ACH posting-order divergence, conserved-quantity invariants).
- **§1.9 SCAFFOLD_CORNER_DESIGN.yaml: 38 instances** (34 active + 4 `excluded_because` stubs) spanning all 9 claim-extraction-guide sections.

### Profile
Primary archetype **compliance/audit**, secondary **ledger reconciliation**; layers: cascading side effects, rate/threshold triggers, derived-field reconciliation, optimistic concurrency. Topology hybrid, branching state shapes, segregation_of_duties role model, immediate consistency.

### Worklog-worthy design notes
- **`api_prefix` set to `/`** (not `/accounts`): the scaffold spans many root-level peer collections (`/customers`, `/applications`, `/ach-originations`, …); the lint's FK reverse-reachability segment-derivation only works when the prefix lets it read the first path segment as the collection name.
- **Dual-variant pinned numbers**: ACH posting CHRONOLOGICAL vs HIGH_TO_LOW on identical legs [4000,7000] / start-avail 5000 / courtesy-limit 6000 → fees 3000 vs 6500, ledgers −9000 vs −8500. Overdraft-vs-NSF variant: same 12000 debit → POSTED+OD-fee (ledger −5000) vs RETURNED+NSF-fee (ledger 7000).
- **Rule 8 (temporal-overlap)** mapped to InterestPosting half-open day intervals (adjacency allowed) and StopPayment closed amount-bands (adjacency impossible) — backed by errors `ERR_INTEREST_PERIOD_OVERLAP` / `ERR_DUPLICATE_STOP_PAYMENT`.
- **Fee schedule**: tier-1 $30, tiers 2–4 $35, 5th+ $0 (daily cap of 4 fee-bearing items).
- Endpoint count (47) exceeds the Expert 20–32 guideline, but ~22 are mandatory read-only FK reverse-reachability GETs; the business/action surface is Expert-sized.
- Hard constraint honored: no sibling `task_*/` directory was read.

## Step 3: Copy Shared Files — 2026-06-06T16:48:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0201_retail_checking_savings/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-06T16:54:00.000Z

Generated `workspace/PRD.md` (299 lines) from the retail checking/savings scaffold. SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml withheld (not read).

**Section structure:**
- **§1 Introduction** — dual compliance + ledger spines (CIP/KYC four-eyes; signed-transaction balance derivation).
- **§2 Global Specifications** — 10 subsections: 2.1 RBAC (AccountHolder entity-backed, Teller/ComplianceOfficer opaque), 2.2 fixed response envelope, 2.3 pagination, 2.4 id/timestamp/version (ApyTier common_fields:false — id/created_at only), 2.5 money/days/rounding (cents atomic, interest floored once), 2.6 OCC on ACH batches, 2.7 cascades, 2.8 nested resolution, 2.9 well-formedness, 2.10 validation precedence (1–19 ordering).
- **§3 Business Logic** — 15 subsections by entity lifecycle (onboarding → KYC scoring → adjudication → ledger → debit posting → fee tiers → dormancy/escheat → freeze/close → ownership → stop-payments → interest → ACH stage/settle/reverse → clock).
- **§4** 47-endpoint table; **§5** 22-error table.

**Hard Contract reports:**
- Contract 1 (Field-Name Coverage): 62/62 identifiers present, 0 missing — PASS. (Repair: `origin_application_id` added to §3.3 account-opening cascade.)
- Contract 2 (Rule Coverage): PASS — both OCC entries express `expected_ach_origination_version` + 412 `ERR_STALE_VERSION`; 18 states, 28 enum values, 22 error IDs surfaced; KYC + interest formulas reconstructible.
- Contract 3 (§3 Path Purity): 413 §3 backtick tokens, 0 paths/bare-methods — PASS.

**Notable decisions:** interest tier resolved by `Account.apy_tier_code`; fee constants embedded as prose (3000c tier-1, 3500c tiers 2–4, cap at 4th item inclusive); high-to-low vs chronological ACH posting divergence narrated in §3.13. Cleaned a stray tag leak at EOF.

## Step (Unit Tests): Generate test_helpers/ + test_suite/ — 2026-06-07

Generated complete test infrastructure from the two design indices (design-index-only contract).

### test_helpers/ (Stage 1)
- `types.py` — 11 status/role enums, 11 full-envelope entity TypedDicts; `ApyTier` correctly carries only id + created_at (common_fields:false per PRD §2.4).
- `api_client.py` — one method per endpoint in PRD §4 (clock, apy-tiers, customers, applications, accounts + lifecycle ops, owners, transactions, fee-assessments, stop-payments, interest-postings, escheat-events, ACH originations/legs/settle/reverse).
- `api_errors.py` — all 22 error ids + HTTP status map registered with the framework.
- `assertions.py` — per-entity assertions + `assert_balance_identity` (available == ledger - hold).
- `factories.py` — input-field-only payload builders.
- `constants.py` — KYC/FEE/DORMANCY/INTEREST thresholds.
- `test_users.py` — opaque Teller/ComplianceOfficer shared headers + entity-backed AccountHolder `make_account_holder_headers(customer_id)` (identity threading enforced).
- `fixtures.py` — composite helpers: open_account / open_account_with_deposit / open_account_with_courtesy_pay / reject_application / place_stop_payment / stage_batch_with_legs / settle_batch / open_account_then_make_dormant + paginated list drainers.

### test_suite/ (Stage 2) — 6 files, 70 test functions
- test_01 onboarding/applications, test_02 transactions/fees, test_03 account lifecycle, test_04 ACH settlement, test_05 interest/stops/owners, test_06 crud/rbac/errors.

### Coverage
- Queue A (Difficulty): all 18 instances translated, each with exactly 2 tests (36 tests). 0 skipped.
- Queue B (Corner): all 34 non-stub instances translated, 1 test each (34 tests). 0 skipped. The 4 `excluded_because` stubs (apy_tier_resolution_uses_account_tier_code, filter_transactions_by_ach_origination, approve_from_draft_returns_invalid_state, dormant_to_active_revert_via_deposit) NOT translated — all 4 cross-references resolve to real difficulty instances.
- Every test docstring carries a verbatim PRD citation (AST-checked against PRD.md, normalized whitespace) ending in exactly one `Design:` line. No skip/xfail markers. No scaffold leakage.
- Import graph + pytest collection verified against a stub framework: 70 tests collected, 0 errors.

### Infrastructure notes
- Framework `_request` signature is `(method, path, payload=None, headers=None, params=None)`; GET/DELETE send payload as query params — list helpers pass filters via `params=`.
- SoD relies on distinct opaque ids within a single test (teller-1 vs officer-1, officer-1 vs officer-2; the SoD corner case submits+approves as the same officer-9). Per-test DB reset means no cross-test id collisions.
- Courtesy-out NSF case: the returned item does not post but the NSF fee DOES post as a FEE debit (PRD §3.6), so opted-out ledger lands at 10000 - 3000 = 7000 (matches design assertion).

## Step 6: Generate Implementation — 2026-06-06T16:56:00.000Z

Generated a complete Python + Flask implementation at `workspace/implementation/`. All 47 endpoints, 5 state machines, 7 calculations, and 22 error codes implemented and smoke-tested end to end.

### File/module layout
- **`app.py`** — Flask entry; registers 10 blueprints, error handlers (ApiError → envelope, 404/405→ERR_NOT_FOUND, 400→ERR_INVALID_REQUEST), serves via waitress (Werkzeug fallback) on `0.0.0.0:$PORT`.
- **`db.py`** — In-memory `Store` (12 dicts), ledger clock, UUID/`req_`-id/ISO-8601-with-3-fractional-digits helpers, date arithmetic.
- **`errors.py`** — `ApiError` + 22 error-id constants. **`response.py`** — meta/response_type/data success+error envelope + pagination meta. **`middleware.py`** — auth (X-User-Role/X-User-ID, 3 roles → 401/403), `@require_roles`, limit/offset (default 10, 1–100). **`models.py`** — common-field stamping (id/created_at/updated_at/version; version starts 1, bumps on mutation) + private-field-stripping serializer.
- **`routes/`** — clock, apy_tiers, customers, applications, accounts, owners, transactions, stop_payments, reads (fee/interest/escheat lists), ach.
- **`services/`** — ledger (balance derivation, fee tiers, debit gates), application (KYC scoring, cip_status, account opening), account_ops (dormancy/escheat/interest/stop-expiry), ach (posting-order settlement + reversal invariant), resolve (specialized not-found + ownership), validate (body well-formedness).

### Storage model
Pure in-process dicts keyed by UUID, one per entity. No seeding at startup, no disk/DB — every `start.sh` re-invocation gets an empty store. Ledger clock defaults to fixed epoch (2025-01-01), advanced only via `/_clock/set_current_utc`; timestamps derive from ledger clock so deterministic under frozen time.

### start.sh boot
`set -euo pipefail`, cd to script dir, guarded install (`if ! python3 -c "import flask, waitress"`) to avoid pip contention across concurrent per-test reboots, then `exec python3 app.py` (foreground, signals propagate). requirements.txt: flask 3.0.3 + waitress 3.0.0.

### Notable implementation decisions
- Balances always **derived** from POSTED/PENDING transactions, never stored; `last_activity_date` is the one stored field (init at opening, refreshed on customer-initiated activity + ACH-credit reactivation).
- Pinned ACH divergence verified exactly: legs [4000,7000], start-avail 5000, courtesy-limit 6000 → CHRONOLOGICAL ledger −9000/fees 3000 vs HIGH_TO_LOW ledger −8500/fees 6500.
- Reversal conservation invariant holds (two-account total 50000→50000 unchanged). Leg-txns reversed equal-and-opposite; FeeAssessments offset by FEE credits, no double-count.
- Fee FEE-debit txns post immediately, never NSF/recursively fee'd; capped 5th+ fee posts no balance-moving txn.
- Interest uses single floor-after-full-multiplication (`bal*bps*days/(10000*365)`, math.floor); verified 3698 for $10k @ 450bps / 30 days.
- Validation precedence per PRD §2.10: auth→forbidden→existence (specialized not-found override)→ownership→state→business; SoD precedes KYC gate; state gate precedes OCC on ACH settle/reverse; nonzero-balance precedes pending-items on close.
- OCC keyed on `expected_ach_origination_version` vs `AchOrigination.version` (412 ERR_STALE_VERSION); version bumps on leg-add and settle.
- ApyTier carries only id/created_at.
- Modeling choice: `EscheatEvent.jurisdiction` taken from primary owner's `country_of_residence` (only residence field on Customer in scaffold).

## Step 7: Run Tests and Iterate — 2026-06-06T17:19:00.000Z

Final 8-round parallel sweep: uniformly **70/70 passed, 0 failed, 0 errors** — no flakiness across rounds.

**Iterations run:** 2 (1 diagnostic baseline sweep + 1 verification sweep after the fix).

**Root cause (single coherent bug):** All 9 failing tests lived in `test_04_ach_settlement.py`. Eight failed identically in setup with `HTTP 412 ERR_STALE_VERSION`; the ninth (`test_leg_add_increments_version_by_one`) failed `assert 1 == (1 + 1)`. The test layer conflated two distinct entities' `version` fields. Per PRD §2.4 (version begins at initial value on creation, increments by one on every mutation), a freshly created `AchLeg` carries its OWN version starting at 1. Per PRD §2.6/§3.12 (adding a leg advances the *origination's* version by one), the bumped value lives on the `AchOrigination`. The test helper read the post-add version off the leg response (`leg["version"]` = 1) and fed it as `expected_ach_origination_version` to settle — but the origination's version had advanced to 2, so every settle was rejected stale. The implementation was PRD-faithful; the test was not. This was the TRIAGE-HINT case (≥5 tests sharing one setup error → test_helpers first suspect).

**Tests deleted:** None. Every failing test traced to a verbatim, uniquely-derivable PRD rule (the leg-add version-bump on the origination); the bug was a wrong version *source*, not an unfair assertion.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` — `stage_batch_with_legs`: after each `add_leg`, the threaded version is now re-read from the **origination** (new helper `origination_version()` via `GET /ach-originations/{id}`) instead of from the leg response, matching PRD §2.6's "adding a leg bumps the origination's version". Added the `origination_version()` helper.

**Fixes applied to `test_suite/`:**
- `test_04_ach_settlement.py` — `test_leg_add_increments_version_by_one`: the assertion now reads the post-add version from the origination (`GET /ach-originations/{id}` → `o_after["version"]`) and asserts `new_version == pre_version + 1`, then settles with that origination version. This makes the assertion express exactly the PRD rule (origination version advances by one) rather than the leg's own version field.

**Fixes applied to `implementation/`:** None. The implementation correctly returns the new `AchLeg` with its own version=1 and advances the origination's version by one; PRD-faithful behavior preserved.

**Stability:** Final 8-round parallel sweep uniformly 70/70 passed, 0 failed, 0 errors — no flakiness.

## Step 8: Finalize PRD — 2026-06-06T17:22:00.000Z

Produced `workspace/PRD_FINALIZED.md`. **One single-line edit, no structural change.**

**Line counts:** PRD.md = 299, PRD_FINALIZED.md = 299. Delta = 0 lines (one line modified in place); 0% line-count delta.

**Change:**
- §2.4 (Resource Identity, Timestamps, and Versioning) — **revise** — changed the self-referential "the `version` field … begins at its initial value when the resource is created" to "begins at `1`", pinning the previously-unstated initial version value — `implementation/models.py:18` (`entity["version"] = 1` in `stamp_new`).

**Per-edit pre-edit search log:**
- (a) Subject: the initial integer value of the `version` field on resource creation.
- (b) Impl paths enumerated/read: `models.py:10-26` (`stamp_new` sets version=1; `touch` increments by one; no entity is touched at creation). All 12 versioned-entity creation callsites route through `stamp_new` (origination, leg, application, owner ×2, customer, stop-payment, account, fee, transaction, escheat event, interest posting) — all start at 1. `ApyTier` created with `with_version=False` (no version field), already carved out by PRD §2.4.
- (c) Wording adjustment: scoped "begins at 1" to the existing §2.4 sentence whose following paragraph already excludes ApyTier; no over-claim, no further softening needed.

**Why only this edit:** Step 7's single item was a pure fixture bug (test read the leg's version instead of the origination's). The implementation was PRD-faithful — PRD §2.6/§3.12 already uniquely determine that adding a leg advances the *origination's* version by one, and §2.4 already determines a new leg carries its own version. The genuine residual silence at the version subject was the *initial* value, which §2.4 left self-referential; impl pins it to 1 uniformly, so that was pinned. No other edits warranted.

## Step 9: Complete PRD — 2026-06-06T17:28:00.000Z

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-implementation scan, starting from PRD_FINALIZED.md.

**File metrics:** PRD_FINALIZED.md = 299 lines / 48,256 chars; PRD_COMPLETED.md = 299 lines / 51,771 chars (char-delta **+3,515**; line count unchanged — every change was an in-paragraph insert/revision, no new sections).

**Change counts:** 11 edits total — **8 ambiguity-pins, 3 mismatch-revisions**.

**Per-change log** (`{section} — {kind} — {type} — {what} — {impl ref}`):
- §2.1 RBAC — insert — ambiguity — missing/blank `X-User-ID` → `ERR_UNAUTHENTICATED` (401), evaluated before role-permission check — `middleware.py:24`
- §2.3 Pagination — insert — ambiguity — out-of-range/non-integer `limit`/`offset` → `ERR_INVALID_REQUEST` (422) — `middleware.py:62,73`
- §2.3 Pagination — insert — ambiguity — `created_at` ties broken by server insertion order — `routes/common.py:13`
- §2.4 Timestamps — insert — ambiguity — `created_at`/`updated_at`/`api_request_timestamp` read from ledger clock, not wall-clock — `models.py:11-18`, `response.py:8-12`, `db.py:83`
- §2.5 Ledger clock — insert — ambiguity — clock defaults to `2025-01-01T00:00:00.000Z` until first set — `db.py:35`
- §3.3 Account opening — insert — ambiguity — pin default field values at open (`courtesy_pay_opted_in=false`, `courtesy_pay_limit_cents=50000`, `accrued_interest_cents=0`, `dormancy_threshold_days=365`, `escheat_threshold_days=1095`, `last_activity_date`=open date) — `services/application.py:68-79`
- §3.5 Transaction state gate — insert — ambiguity — `CLOSED`/`ESCHEATED` → `ERR_INVALID_STATE`; `FROZEN` accepts credits while returning debits — `routes/transactions.py:25,53`, `ledger.py:199`
- §3.5 Courtesy-pay endpoint — insert — ambiguity — request body shape (required `courtesy_pay_opted_in`, optional `courtesy_pay_limit_cents`; limit updated only when supplied; callable in any account status) — `routes/accounts.py:48-66`
- §3.7 Dormancy reactivation — insert — ambiguity — `WITHDRAWAL` reactivates from the attempt regardless of terminal outcome; `CHECK_DEBIT` refreshes `last_activity_date` but does not reactivate — `routes/transactions.py:80-85`
- §3.7 Escheat jurisdiction — revise — **mismatch** — "primary owner's state of residence" → active `PRIMARY` owner's customer's `country_of_residence` (null when unresolvable); Customer has no state field — `services/account_ops.py:32-38`
- §3.11 Interest — revise — **mismatch** + insert — "balance as it stood at period start" is the live `ledger_balance_cents` at posting time (no historical reconstruction); unresolvable `apy_tier_code` treated as 0 bps — `services/account_ops.py:66-76`
- §3.13 ACH settlement — insert — ambiguity — `created_at` ties in posting order broken by leg insertion order — `services/ach.py:26-30`
- §3.13 ACH settlement — revise — **mismatch** — frozen-debtor debit leg `settlement_outcome=RETURNED_NSF` produces `ACCOUNT_FROZEN` return with **no fee**; only floor-breach (`NSF`) case assesses a fee — `ledger.py:199-228`, `services/ach.py:67-71`
- §3.14 ACH reversal — insert — ambiguity — offset txns are `ACH_DEBIT`/`ACH_CREDIT` carrying `ach_origination_id`; offsetting `FEE` txn carries `direction=CREDIT`; zero-cent capped fees produce no offset — `services/ach.py:115-143`

Tests used only as auxiliary cross-reference (frozen-debtor fee, interest-balance cases); implementation was the alignment target throughout.

---

## Pipeline Complete

All 9 steps finished. Final state: **70/70 tests passing across 8 parallel stability rounds, 0 deletions, 0 implementation fixes.** Artifacts present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/, test_suite/ (70 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}.
