# Worklog — task_0169_venture_fund_lp_administration

## Step 1: Create task directory — 2026-06-05

Created `tasks/task_0169_venture_fund_lp_administration/` and `tasks/task_0169_venture_fund_lp_administration/workspace/` (pre-assigned index 0169; no auto-increment scan performed). Difficulty target: Expert.

## Step 2: Generate scaffold — 2026-06-05

All checks pass. The scaffold is complete and self-consistent.

Generated the full scaffold package for **task_0169_venture_fund_lp_administration** (Venture Fund / LP Administration) at the **Expert** difficulty band. All three required files were written and validated.

**Dimensions:**
- **Entities:** 12 (Fund, LimitedPartner, Commitment, CapitalCall, CapitalCallAllocation, PortfolioCompany, Investment, ValuationMark, ManagementFeeAccrual, DistributionEvent, DistributionAllocation, SideLetter)
- **Endpoints:** 49 (within Expert range for a 12-entity model; every GET serves either a recipe or an FK reverse-reachability requirement — no dead endpoints)
- **Error codes:** 22
- **Calculation variants:** 3 (`excused_lp_redistribution` on capital-call allocation, `fee_offset` on management fee, `clawback` on distribution waterfall), across 6 calculation rules
- **State machines:** 5 (Fund, Commitment, CapitalCall, ValuationMark, DistributionEvent) — including branching (CapitalCall: ISSUED→{SETTLED, PARTIALLY_DEFAULTED, DEFAULTED, CANCELLED}) and cyclic (DistributionEvent PAID→RECALLED recycling loop)

**Design coverage:**
- §1.8 difficulty design: 18 instances (all 9 Difficulty Rules × 2), each grounded in declared §1.1–§1.7 elements with formula-derived asserts pre-computed as literals (waterfall, largest-remainder allocation, round-per-commitment fee, recycling restoration all executed in code and pinned).
- §1.9 corner design: 37 active instances + 3 `excluded_because` stubs spanning the full claim-extraction taxonomy.
- 2 concurrency rules (OCC on Fund.version for capital-call issuance and distribution declaration).

**Validation results (all clean):**
- `scaffold_lint.py`: **VERDICT: clean lint** — 460 calls scanned, all conform to §1.5; all 15 FKs have reverse-reachability GETs.
- No forbidden concurrency vocabulary; all 22 error codes referenced; all 15 FK descriptions use the canonical prefix; perfect enum closure (state-machine states == status enums for all 5 machines); all grounds references resolve; all stubs cite valid §1.8 instances; all instance names unique across both files; file-split key discipline confirmed.

Files written: SCAFFOLD.yaml (1565 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1235 lines), SCAFFOLD_CORNER_DESIGN.yaml (1419 lines).

## Step 3: Copy shared files — 2026-06-05

Copied `INSTRUCTION.md` → `tasks/task_0169_venture_fund_lp_administration/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-05

**File written:** `workspace/PRD.md` (261 lines, 44569 bytes).

**Major sections:** §1 Introduction; §2 Global Specifications (2.1 RBAC 4 roles, 2.2 Response Structure, 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Cent-Ledger Discipline/round-half-up/largest-remainder, 2.6 Ledger Reconciliation, 2.7 OCC on Fund version, 2.8 Path Resolution/validation precedence); §3 Business Logic (3.1 Fund lifecycle, 3.2 LP onboarding & commitments, 3.3 Capital calls/allocation/funding/default, 3.4 Portfolio marking & realization, 3.5 Distributions/4-tier waterfall/clawback/commitment split, 3.6 Recycling/recall, 3.7 Side letters/MFN/excused, 3.8 Management fees/offset/LP statements & K-1); §4 Endpoint Definitions (49 endpoints); §5 Error Code Catalogue (22 codes).

**Coverage:** 12/12 entities, 49/49 endpoints, 22/22 errors, 6 calculations (allocate_capital_call, accrue_management_fee+fee_offset, distribution_waterfall+clawback, split_distribution_to_commitments, recycle_distribution, compute_lp_irr_summary), 6 entities' state machines incl. cascades.

**Hard Contract Reports:** Field coverage PASS (65/65), Rule coverage PASS, Path purity PASS (0 path tokens in §3). §2.2 byte-identical to canonical source. DIFFICULTY/CORNER design yamls were NOT read.

## Step 5: Generate unit tests — 2026-06-05

Generated complete test infrastructure for **task_0169_venture_fund_lp_administration** purely from this task's four input files plus the unit-test-generator skill.

**Test files: 6** (1 conftest + 5 test files)
- `test_01_fund_lifecycle_and_access.py` — 20 tests (fund CRUD, lifecycle transitions, listing/pagination, existence guards, RBAC)
- `test_02_capital_calls_and_allocations.py` — 12 tests (largest-remainder split, excused redistribution, branching state machine, commitment-default cascade, derived-field reconciliation)
- `test_03_distributions_waterfall_recycling.py` — 17 tests (4-tier waterfall, recycling/recall, reverse, recall-cap boundary, LP statement/K-1)
- `test_04_management_fees.py` — 11 tests (base vs offset variant, round-per-commitment-then-sum, period overlap/adjacency)
- `test_05_validations_and_marks.py` — 12 tests (MFN uniqueness, mark date conflict/supersession, WRITE_OFF cascade, realize/NAV, OCC, state-precedence cancel)

**Total test count: 72** — Queue A (Difficulty): **36**, Queue B (Corner): **36**.

**Coverage (audited programmatically):** All 18 difficulty instances have exactly 2 tests each (≥2 required). 36 of 37 corner non-stub instances have ≥1 test. All 3 `excluded_because:` stubs correctly NOT translated.

**Instances skipped: 1** (category: *unique-derivability failure*)
- `Corner/errors/no_participating_commitments_on_call` — asserts `ERR_COMMITMENT_NOT_ACCEPTED` for issuing a capital call on a fund whose only commitment is PENDING (empty participant set). PRD §3.3 uniquely derives `ERR_NO_PARTICIPATING_COMMITMENTS` for an empty participant set; `ERR_COMMITMENT_NOT_ACCEPTED` is the fund-*activation* error in PRD §3.1. A PRD-only implementer would not return the asserted error, so the instance fails the two-reader filter and was skipped (gap left as a gap, no placeholder/xfail).

**test_helpers files produced (9):** `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`.

**Validation:** all 9 helper modules and 5 test files byte-compile; `pytest --collect-only` collects all 72 tests with no import/fixture errors; every docstring carries exactly one `Design:` tag resolving to a real instance + PRD citation; all quoted citations verified verbatim against PRD.md; no skip/xfail markers; no scaffold leakage. Numeric expectations (fee 49315/19315, round-per-commitment 14796, waterfall 14M/1M, recycling restorations 4.2M/2.8M) hand-verified.

## Step 6: Generate implementation — 2026-06-05

**Stack:** Python 3 + Flask 3.0.3 (mandated). All state in-memory.

**Source files produced (28 files):**
- `start.sh` — foreground launcher; reads `$PORT` (default 10000), binds `0.0.0.0`, guards `pip install` on a cheap `import flask` check, `exec python3 app.py`. Executable, boots and serves HTTP 200 within ~0.6s.
- `app.py` — entry point, blueprint registration, error handlers (maps `ApiError`, 404/405 → `ERR_RESOURCE_NOT_FOUND`).
- `db.py`, `response.py`, `errors.py`, `middleware.py`, `validation.py` — foundation (in-memory dicts, envelope helpers, error catalogue, auth, request/pagination validation).
- `routes/` (10 files): funds, limited_partners, commitments, capital_calls, allocations, portfolio (companies+investments), valuation_marks, fee_accruals, distributions, side_letters.
- `services/` (11 files): derive (all computed/derived fields), serialize, lookup, dates, sideletters, allocation (largest-remainder split), capital_call, capitalcall_state, fee, waterfall (4-tier + clawback + split + recycle), statement (K-1).

**Endpoint count:** 49 distinct (method, path) endpoints — exact match to the PRD endpoint table (0 missing, 0 extra).

**Storage/state structure:** Twelve module-level dicts keyed by UUID `id`, a per-fund monotonic `call_number` counter, and a global `RLock`. State starts EMPTY on every boot — no seeding/preloading anywhere. Common fields (`id`, `created_at`, `updated_at`, `version` starting at 1) stamped by `db.stamp_new`/`db.touch`. Derived totals recomputed at serialize time; recycling restorations persist via `recycled_restored_cents` offset. Money uses `decimal.Decimal` with `ROUND_HALF_UP`; largest-remainder splits break ties by `created_at` ASC.

**start.sh confirmation:** exists, executable, boots cleanly from a fresh process and serves on `0.0.0.0:$PORT`. (Note: backgrounded server processes were unreliable across separate Bash calls in the gen environment — a harness artifact; functional verification used Flask in-process test client + single-call live-HTTP boots, both passed.)

## Step 7: Test-and-fix loop — 2026-06-05

**Iterations run:** 2 sweeps (1 diagnostic baseline + 1 verification). The baseline 8-round sweep was perfectly consistent (no flakiness): the same 2 tests failed in all 8 rounds; the rest of the 72 passed everywhere.

**Union of failing tests (identical across all 8 rounds):**
1. `test_create_commitment_nonexistent_lp_rejected` — expected `ERR_RESOURCE_NOT_FOUND` (404), got `ERR_INVALID_REFERENCE` (422).
2. `test_mgmt_fee_offset_variant_reduces_net` — expected `offset_applied_cents == 30000`, got `0`.

**Tests deleted (2) — both STEP 1b unique-derivability collapses:**

- **`test_create_commitment_nonexistent_lp_rejected`** (`test_suite/test_01_fund_lifecycle_and_access.py`) — *ERROR-PRECEDENCE / contradictory-PRD silence.* PRD §2.8 contains two verbatim sentences that govern the exact case (commitment created with a non-existent LP FK) and contradict each other: ¶1 "every foreign key referenced in the body is resolved left-to-right; if any does not exist, the request fails with `ERR_RESOURCE_NOT_FOUND` (HTTP 404)" vs. ¶2 "When a commitment is created it must reference a `Fund` and a `LimitedPartner` that both exist… A reference that points at a non-existent or incompatible parent is rejected with `ERR_INVALID_REFERENCE` (HTTP 422)." A faithful PRD-only implementer can reasonably treat the creation-specific ¶2 as authoritative and return `ERR_INVALID_REFERENCE` (which the implementation does), so the assertion is not uniquely derivable. Scaffold rule that drove generation: `Corner/errors/invalid_reference_commitment_bad_lp`.

- **`test_mgmt_fee_offset_variant_reduces_net`** (`test_suite/test_04_management_fees.py`) — *COMPUTED-FIELD SILENCE.* PRD §3.8 gates the offset on a MANAGEMENT_FEE call "whose period falls in the accrual period," but a `CapitalCall` has no `period` field — only `due_date` (input) and `created_at` (system); the SCAFFOLD likewise says "in the period" without pinning the temporal anchor. Two PRD-faithful readings diverge: (A) match by `due_date ∈ [period_start, period_end)` → offset 0 (impl's choice); (B) any MANAGEMENT_FEE call counts → offset 30000. The test's own fixture uses the default `due_date` of 2030-02-01 against a 2024 accrual period, so no time-based reading yields a match — and a STEP 2 fixture fix is impossible because PRD §3.3/§2.8 forbid a past `due_date` (today is 2026), so a call's `due_date` can never fall inside a historical accrual period. Untestable + non-uniquely-derivable → deleted. Scaffold rule that drove generation: `Difficulty/dual_variant_calc/mgmt_fee_base_vs_offset_variant`.

**Fixes applied to test_helpers/:** none required — the two failures were PRD-silence/contradiction issues, not fixture inconsistencies.

**Fixes applied to implementation/:** none — the implementation's behavior on both deleted tests was a defensible PRD-faithful reading (returning `ERR_INVALID_REFERENCE` for commitment-creation referential integrity per §2.8 ¶2; gating the fee offset on the call's `due_date` falling in the accrual period). No implementation check was weakened or removed.

**Final state:** 8/8 parallel rounds clean, 70/70 tests passing in every round, no flakiness observed. Storage remains in-memory only (no new seeding/persistence introduced).

## Step 8: Finalize PRD — 2026-06-05

**Line counts:** PRD.md = 261 lines; PRD_FINALIZED.md = 261 lines. Delta: 0 lines (+0.0%); 2 lines revised in place, 0 inserted/deleted.

**Changes (one bullet each):**
- **§2.8 ¶1 (Path Resolution / error precedence) — revise — Scoped the body-FK `ERR_RESOURCE_NOT_FOUND` (404) rule to exclude the three referential-integrity creation endpoints, and pinned that a non-existent FK on those three endpoints yields `ERR_INVALID_REFERENCE` (422), never 404. Resolves the §2.8 ¶1-vs-¶2 contradiction in favor of the impl's choice.** — `implementation/routes/commitments.py:28-31` (also `routes/portfolio.py:53-59`, `routes/side_letters.py:29-35`).
- **§3.8 (Fee offset) — revise — Replaced the under-determined "whose period falls in the accrual period" with the pinned temporal anchor: a `MANAGEMENT_FEE` call qualifies when its `due_date` lies in the half-open accrual interval `period_start ≤ due_date < period_end`, noting a `CapitalCall` carries no separate `period` field.** — `implementation/services/fee.py:47-66` (`start_dt <= due < end_dt`).

**Per-edit pre-edit search log:**
- **Edit 1 (§2.8 ¶1).** (a) Subject: error returned for a non-existent body FK, and whether it differs between creation endpoints and others. (b) Enumerated/read: `routes/commitments.py:28-31`, `routes/portfolio.py:53-59`, `routes/side_letters.py:29-35` (all → 422); contrasted with `routes/capital_calls.py:32`, `routes/distributions.py:42-43`, `routes/valuation_marks.py:28`, `routes/fee_accruals.py:30,72` (FK via `lookup.get_*` → 404); `services/lookup.py:6-10`; `validation.py:7,11`. grep over routes/+services/ confirmed only those three creation endpoints use 422. (c) Adjustment: scoped ¶1's body-FK 404 clause to exclude the referential-integrity endpoints and added an explicit carve-out sentence pointing those three to ¶2's 422; ¶2 left verbatim.
- **Edit 2 (§3.8 offset).** (a) Subject: which `MANAGEMENT_FEE` calls count toward the offset and the temporal anchor. (b) Enumerated/read: `services/fee.py:47-66` (gate, iterate fund's MANAGEMENT_FEE calls, qualify when `period_start <= due < period_end`, sum `called_amount_cents`, round-half-up, `min(gross, candidate)`); `services/fee.py:68` (`net = max(0, gross - offset)`); `routes/fee_accruals.py:52-62`; `services/dates.py:10-32` (`parse_dt`); `routes/capital_calls.py:27,38-42` (only other `due_date` use: not-in-past at issuance); `services/serialize.py:76` (no `period` field). (c) Adjustment: wrote condition as half-open `period_start ≤ due_date < period_end`, stated `due_date` is the anchor and `CapitalCall` has no `period` field; kept wording narrow to the offset gate so it doesn't collide with the not-in-past issuance check; downstream offset-0 fallback left verbatim.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-05T20:54:00.000Z

**Source vs completed file:** PRD_FINALIZED.md = 261 lines (45,284 chars); PRD_COMPLETED.md = 261 lines (47,735 chars). Char delta: +2,451 (line count unchanged; all edits in-paragraph).

**Counts:** 10 changes total — 9 ambiguity-pins, 1 mismatch-revision. (All edits insert/revise inline within existing paragraphs; no new sections, no new behavior invented.)

**Per-change bullets** (`{section} — {action} — {type} — {what} — {impl ref}`):
- §3.1 — insert — ambiguity — pinned the `ERR_VALIDATION_LIMIT` upper bounds on `mgmt_fee_rate_bps` (≤1000) and `pref_rate_bps` (≤3000), plus the already-known `carry_rate_bps` (≤5000), which the PRD left unbounded — `routes/funds.py:32-34`
- §3.1 — insert — ambiguity — named the NAV computed-read response field `fund_nav_cents` (PRD said only "its NAV in cents") — `routes/funds.py:158`
- §3.2 — insert — ambiguity — pinned `ERR_INVALID_STATE` (409) when declare-default is attempted with `default_strike_count` still zero — `routes/commitments.py:107-111`
- §3.3 — insert — ambiguity — pinned `ERR_INVALID_STATE` (409) when cancelling a call that is not `ISSUED` or already has a `PAID` allocation — `routes/capital_calls.py:85-93`
- §3.5 — insert — ambiguity — pinned that "amounts already distributed from" the investment = sum of `gross_amount_cents` over all non-`REVERSED` prior events (DECLARED/PAID/RECALLED hold proceeds; REVERSED frees them) — `routes/distributions.py:18-25`
- §3.5 — insert — ambiguity — pinned preferred-years as the whole-number difference between the server's current UTC calendar year and `vintage_year`, floored at zero (year components only) — `services/waterfall.py:31-36`
- §3.5 — insert — ambiguity — pinned cumulative LP receipts for clawback = sum of `lp_share_cents` over prior `DECLARED`/`PAID` events plus this event's LP share — `services/waterfall.py:39-46,94-95`
- §3.6 — insert — ambiguity — pinned `ERR_INVALID_STATE` (409) when recalling an event that is not `PAID` or whose `recyclable` is false (cap guard reached only afterward) — `routes/distributions.py:166-169`
- §3.7 — insert — ambiguity — pinned that `fee_discount_bps` is capped at 1000 (out-of-range → `ERR_VALIDATION_LIMIT` 422); and that with multiple executed letters only the lowest-`mfn_rank` letter's discount applies (never summed) — `routes/side_letters.py:39`, `services/sideletters.py:38-41`
- §3.8 — insert — ambiguity — named the LP-statement response fields exactly (`paid_in_cents`, `distributed_cents`, `nav_cents`, `dpi_bps`, `tvpi_bps`, `k1_return_of_capital_cents`, `k1_capital_gain_cents`, `k1_income_cents`, `ubti_flag`), pinned `dpi_bps`/`tvpi_bps` as truncating (floor) division, pinned `nav_cents`=0 when `total_committed_cents`=0, and noted the body is not an entity envelope — `services/statement.py:33-73`

**Notes on items left unchanged:** The fee-accrual `INVOICED`/`PAID`/`REVERSED` lifecycle states and the side-letter `TERMINATED` state are described in prose but have no transition endpoints in `implementation/` or the §4 table; since the PRD never asserts an operation for them, there is no mismatch to revise. Tests were used only as auxiliary cross-reference, never as authority.
