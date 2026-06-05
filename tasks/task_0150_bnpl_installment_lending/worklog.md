# Worklog — task_0150_bnpl_installment_lending

Scenario: 150. BNPL / Installment Lending: soft-credit eligibility, installment plan (Pay-in-4/monthly), down payment, repayment/autopay schedule, late fee/delinquency, partial-return reallocation, merchant settlement/MDR, Reg Z disclosure

## Step 1: Create task directory — 2026-06-04T14:12:56.000Z

Created `tasks/task_0150_bnpl_installment_lending/` and `tasks/task_0150_bnpl_installment_lending/workspace/`. Next index resolved to 0150 (highest existing was 0149).

## Step 2: Generate scaffold — 2026-06-04T14:33:03.000Z

All three scaffold artifacts for task_0150_bnpl_installment_lending are generated, written, and lint-clean.

**Files written** (all three confirmed present):
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`, §1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`, §1.9)

**Counts:**
- **Entities: 10** — Merchant, Borrower, Application, DisclosureAcceptance (immutable, `common_fields:false`), Loan, Installment, Payment, Return, AutopayMandate, MerchantSettlement
- **State machines: 4** — Application (branching + revision cycle COUNTERED→SUBMITTED), Loan (parallel `status` × `delinquency_status` dimensions), Installment (linear with LATE revert + write-off/cancel branches), MerchantSettlement (PENDING→RELEASED/CLAWED_BACK) — plus 2 concurrency rules (OCC on `Loan.version` for default/cancel)
- **Calculations: 8** — installment_schedule (Pay-in-4 vs monthly-amortized dual variant), finance_charge, eligibility_limit (provisional vs final dual variant), return_reallocation, payment_allocation, late_fee_assessment, merchant_settlement_net, delinquency_posture
- **Endpoints: 36** (incl. 2 test-driving `/_clock/set_current_utc` and `/_servicer/run_autopay_sweep`)
- **Errors: 12**
- **Roles: 3** — Servicer (opaque), Borrower (`entity_backed:Borrower`), Merchant (`entity_backed:Merchant`)
- **§1.8: 18 instances** (9 Difficulty Rules × 2). **§1.9: 37 instances** (32 active + 5 `excluded_because` stubs).

**Notable design decisions:**
- **Expert band, flat topology** (FK-linked peers, no URL nesting); `api_prefix: ""`.
- **Primary archetype ledger-reconciliation + secondary compliance/audit** — same financed principal diverges (zero-interest Pay-in-4 vs 19.90%-APR amortized monthly), partial-return reallocation reallocates the ledger newest-first.
- **Non-linearity on distinct entities** via Application's revision cycle and Loan's two parallel state dimensions.
- **Reg Z gate** modeled as a `business_safety` validation: activation requires an accepted DisclosureAcceptance.
- **MDR/settlement clawback** = `return_amount − MDR_on_return`, capped at net; added RELEASED→CLAWED_BACK transition for full returns.
- **Rule 8 (temporal overlap)**: half-open grace window (strict `>`) on Installment vs closed-inclusive settlement-hold window (`>=`) on MerchantSettlement.
- All formula-derived asserts precomputed literals (verified in Python): monthly schedule `[21177×5, 21175]`, finance_charge 7060, MDR fee 6000, partial-return clawback 28200, late-fee floor 700/clamp 1500.

**Lint: clean** — 360 §1.8/§1.9 calls conform to §1.5; all 14 FKs have reverse-reachability GETs. (Set `api_prefix` to `""`; added single-resource GETs for Payment/Return/DisclosureAcceptance/AutopayMandate + `merchant_id?` filter on `GET /returns`.)

## Step 3: Copy INSTRUCTION.md — 2026-06-04T14:34:06.000Z

Copied `/Users/uni/Desktop/吉/project/custom_prd_bench/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-04T14:40:04.000Z

Generated `workspace/PRD.md` (~226 lines, 41518 bytes).

**Structure:** 5 top-level sections (§1 Introduction, §2 Global Specifications, §3 Business Logic & Workflows, §4 Endpoint Definitions, §5 Error Code Catalogue); 18 subsections (8 in §2, 10 in §3).

**Hard Contracts — all PASS:**
- Field coverage: 52/52 entity fields, 24(+id) endpoint request/query/path fields, 0 missing.
- Rule coverage: 12 validations (ordering in §2.8), 2 OCC rejections (default + cancel; expected_loan_version + ERR_STALE_VERSION + HTTP 412), all state-machine transitions (Application/Loan/Installment/MerchantSettlement), 7 calculations (incl. dual-variant installment_schedule + eligibility_limit, return_reallocation waterfall, late_fee clamp, settlement_net, delinquency_posture), 12 error triggers, sibling-branch symmetry — 0 missing/asymmetric.
- Path purity (§3): 388 backtick tokens scanned, 0 paths/methods leaked.
- §2.2 response structure verbatim from canonical; §2.3 pagination (limit default 10/min 1/max 100, offset 0, created_at-asc with installment sequence_no exception); §4 table 36 endpoints; §5 table 12 errors.

**Confirmation:** Neither design YAML was read, opened, grepped, or referenced.

## Step 5: Generate unit tests — 2026-06-04T14:58:24.000Z

Generated complete test infrastructure for task_0150_bnpl_installment_lending.

**Test files:** 8 (`test_01_pricing_and_schedules` … `test_08_crud_rbac_and_listings`) plus `conftest.py`, totaling **68 test functions**.

**Coverage by queue:**
- **Queue A (Difficulty, §1.8):** all **18** instances covered with 2 tests each = **36 tests** (dual-variant pricing, monthly amortization, return rounding, application revision loop, parallel loan dimensions, both validation-priority pairs, both temporal-overlap boundaries, both conservation invariants, both depth-2/depth-3 cascades).
- **Queue B (Corner, §1.9):** all **32 non-stub** instances covered with ≥1 test = **32 tests**.

**Skipped instances:** only the **5 `excluded_because` stubs** (own no test_recipe; assertion belongs to cited difficulty instance). All 5 cross-references verified to resolve to real difficulty instances. No instance dropped for failing the PRD two-condition filter — PRD covers and uniquely-derives every non-stub instance.

**test_helpers/ files (9):** `__init__.py`, `types.py`, `api_client.py` (42 endpoint methods), `api_errors.py` (12 errors + HTTP-status registration), `assertions.py` (per-entity + credit-conservation invariant), `factories.py`, `constants.py`, `test_users.py` (opaque Servicer + entity-backed borrower/merchant header builders), `fixtures.py` (composite origination/release/autopay/aging helpers).

**Verification:** every file compiles; all 68 tests collect; every import resolves; all 68 docstrings carry exactly one `Design:` tag resolving to a real instance; every PRD citation verbatim (grep-confirmed); zero scaffold leakage; zero skip/xfail marks.

## Step 6: Generate implementation — 2026-06-04T14:58:24.000Z

Built complete Python + Flask implementation at `workspace/implementation/`.

**Files:** `start.sh`, `requirements.txt`, `app.py`, `db.py`, `errors.py`, `response.py`, `middleware.py`, `routes/` (__init__, common, merchants, borrowers, applications, disclosures, loans, installments, payments, returns, autopay, settlements, operator), `services/` (__init__, calculations, engine).

**Endpoints:** 36 implemented (18 GET, 18 POST) matching SCAFFOLD §1.5 / PRD §4, incl. `/_clock/set_current_utc`, `/_servicer/run_autopay_sweep`.

**Storage:** in-memory only (module-level dicts in db.py keyed by id). No SQLite, no disk dump, nothing seeded/preloaded. Fresh boot = empty store (verified via restart).

**start.sh:** reads $PORT (default 10000), binds 0.0.0.0, foreground via exec. pip install guarded by `if ! python3 -c "import flask"` sentinel (2nd boot logs zero pip lines). app.py has bind-retry loop (EADDRINUSE/EADDRNOTAVAIL ~30s) for same-port races.

**Self-verification (52 smoke assertions all pass):** envelope format, ISO-8601 ms timestamps, validation precedence (401→403→404→422→domain), dual-variant schedule math (PAY_IN_4 residual on #4; MONTHLY 19.90% amortization with sum invariants exact), eligibility tiers/income cap, decision branching + counter→revise→submit loop, Reg Z gate, immutable disclosure, activation cascade, oldest-due-first payment allocation + payoff bubble, autopay sweep, clock-advance LATE (strict `> due+grace`), late-fee clamp (floor 700/cap 1500), delinquency posture (30-day), return newest-first reallocation + MDR clawback, settlement hold/release, default (clawback + OCC 412 + ERR_NOT_DELINQUENT), cancel (ERR_LOAN_HAS_PAYMENTS + OCC). Money via Decimal ROUND_HALF_UP, no floats.

**Impl-author note for test correctness:** list endpoints honor default `limit:10`, so a 12-installment schedule needs `limit=100` (or paging) to retrieve in full; `total_count`/`has_more` reflect the full filtered set.

## Step 7: Test & fix loop — 2026-06-04T15:07:15.000Z

**Result: clean on the first 8-round parallel sweep. 0 iterations beyond baseline.**

- Iterations run: 1 (single 8-round parallel sweep).
- All 8 rounds passed 68/68 tests (0 failed, 0 errored, 0 skipped). No flakiness surfaced across concurrent rounds.
- Tests deleted: none.
- Fixes applied to test_helpers/: none.
- Fixes applied to implementation/: none.
- Known flake patterns (stale keep-alive, same-port bind-race, time-window fixtures) did not manifest.

**Orchestrator confirmation sweep (beyond Step 7):** ran an additional 40 rounds (5 sequential batches of 8 concurrent) because this benchmark's framework client uses a persistent keep-alive `requests.Session` and the stale-keep-alive / bind-race flakes historically need ~48 rounds to surface. **All 40 confirmation rounds green at 68/68** (distinct total-test count = {68}); combined with Step 7's 8 → 48/48 rounds green. Canonical `results.{1..8}.json` from Step 7's final sweep retained in `implementation/`.

## Step 8: Finalize PRD — SKIPPED — 2026-06-04T15:07:15.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes (zero iterations beyond baseline). PRD.md already determined every behavior the implementation exhibits at the Step-7 sites. No subagent spawned; `PRD_FINALIZED.md` not produced. Step 9 will start from `PRD.md`.

## Step 9: Complete PRD — 2026-06-04T15:12:58.000Z

Produced `workspace/PRD_COMPLETED.md` from `PRD.md` (PRD_FINALIZED.md absent — Step 8 skipped).

**File metrics:** PRD.md 226 lines / 41,518 chars → PRD_COMPLETED.md 226 lines / 44,323 chars (char-delta +2,805; line count unchanged — all edits in-paragraph).

**Change counts:** 8 edits — 5 ambiguity-pins, 3 mismatch-revisions.

**Per-change log** (`{section} — {kind} — {class} — {what} — {impl ref}`):
- §2.1 — insert — ambiguity — missing/empty `X-User-ID` (with valid role) → `ERR_UNAUTHENTICATED`; role header checked before user-id — `middleware.py:24-30`
- §3.1 — insert — mismatch — merchant suspension does NOT block application submission; enforced only at decision time via `MERCHANT_SUSPENDED` decline branch — `routes/applications.py:45-97` vs `:166-167`
- §3.3 (decision) — revise — mismatch — supplied `decision` is enum-validated (`ERR_INVALID_REQUEST` on miss) but otherwise ignored; outcome derived solely from eligibility math; membership check precedes the `SUBMITTED`-state check — `routes/applications.py:147-176`
- §3.3 (revise) — insert — ambiguity — revised `requested_down_payment_cents` must be strictly `< cart_amount_cents` (`ERR_INVALID_REQUEST`), `decline_reason` cleared, application re-priced provisionally; state check precedes bound checks — `routes/applications.py:206-224`
- §3.4 (disclosure) — insert — ambiguity — `accepted` must be a JSON boolean (`ERR_INVALID_REQUEST`) and application must be `APPROVED` (`ERR_INVALID_STATE`) to record acceptance — `routes/disclosures.py:30-37`
- §3.4 (activation) — revise — mismatch — removed "exactly one accepted disclosure consumed / duplicate → `ERR_DUPLICATE`" claim (impl never tracks consumption); re-activation blocked by `APPROVED`-state check (`ERR_INVALID_STATE`), evaluated before disclosure/credit preconditions — `routes/loans.py:38-59`
- §3.6 (clock) — insert — ambiguity — `SCHEDULED→LATE` fires only for installments whose loan is still `ACTIVE` — `routes/operator.py:45-46`
- §3.7 (sweep) — insert — ambiguity — mandate's loan must be `ACTIVE`; mandates processed in creation order; charge = next-due installment outstanding (`amount_due − amount_paid`); zero-outstanding skipped — `routes/operator.py:78-103`
- §3.8 (release) — insert — ambiguity — settlement-must-be-`PENDING` precondition (`ERR_INVALID_STATE`) as first of three ordered checks (PENDING → hold-window → loan-`ACTIVE`) — `routes/settlements.py:59-73`

**Key findings:** two substantive mismatches — (1) servicer `decision` field is inert (outcome purely eligibility-driven); (2) PRD's disclosure-consumption / `ERR_DUPLICATE`-on-duplicate-activation machinery does not exist in impl — re-activation gated by terminal state via `ERR_INVALID_STATE`. All other §3 calculations/cascades/roll-ups already matched and were left unchanged.

## Pipeline complete — 2026-06-04T15:12:58.000Z

All steps done. Final state: 68/68 tests pass across 48 stability rounds (8 Step-7 + 40 confirmation). Artifacts: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/ (9 files), test_suite/ (8 test files + conftest), workspace/{INSTRUCTION.md, PRD.md, PRD_COMPLETED.md, implementation/}. PRD_FINALIZED.md intentionally absent (Step 8 skipped).
