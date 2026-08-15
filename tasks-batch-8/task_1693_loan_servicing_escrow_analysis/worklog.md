# Worklog — task_1693_loan_servicing_escrow_analysis

## Step 1: Create Task Directory — 2026-08-14T08:29:00.000Z

Task directory `tasks/task_1693_loan_servicing_escrow_analysis/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-14T09:53:00.000Z

Done. The scaffold package for task 1693 is complete and lint-clean.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1693_loan_servicing_escrow_analysis/`):
- `SCAFFOLD.yaml` (2039 lines) — §1.0–§1.7 only; neither design key present
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (670 lines) — single key `scaffold_difficulty_design`, 18 instances (9 rules × 2)
- `SCAFFOLD_CORNER_DESIGN.yaml` (1246 lines) — single key `scaffold_corner_design`, 54 active instances + 3 `excluded_because` stubs across all nine taxonomy sections

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (83 endpoints, 12 entities, 770 calls scanned; 0 violations.)

**Design shape** (harder-than-expert posture): Ledger-reconciliation archetype + compliance/audit secondary; flat topology; segregation-of-duties role model (payee creator≠verifier, scheduler≠releaser, investigator≠resolver — three SoD checks); 12 entities, 83 endpoints (incl. `/_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`), 36 errors, 11 state machines, 8 calculations, 2 OCC concurrency rules (analysis-create supersede on `EscrowAccount.version`, disbursement PATCH on `Disbursement.version`, both 412).

**Difficulty highlights, all grounded in §1.1–§1.7 and replayed call-by-call:**
- Dual-variant calcs on three domains: PROSPECTIVE vs LEDGER_ACTUAL analysis start balance (shortage 36000 vs 60000 on identical data), SIMPLE vs COMPOUND tax penalty (13500 vs 13704), ACT/365 vs 30/360 force-placement refund (160000 vs 160194)
- Combinatorial formulas in two modes: per-line-then-sum rounding (24999 vs 25000) and a pinned evaluation order for the circular payment↔shortage↔projection dependency (old payment for all 12 months, then derive)
- Non-linear machines on different entities: EscrowAccount parallel dimensions (`account_status` × `hold_status`) and the InsurancePolicy lapse→notice→reinstate cycle (traversed twice)
- Cascades: depth-4 error-correction chain (resolve → ERROR_CORRECTION entry → balance → analysis REOPENED → notice VOIDED) and depth-2 release→advance chain
- Boundary precision: surplus exactly 5000 cents refunds vs 4999 credits; force-placement charge at exactly 45+15 days passes, 44 fails
- Temporal overlap with two interval semantics: half-open insurance coverage (adjacency allowed) vs closed-interval analysis windows (shared boundary day collides)
- Compensating invariants: ledger balance conservation under release/return, and advance decomposition `amount == recovered + written_off + outstanding` through partial recovery + write-off
- RESPA business-day compliance: 5-bd acknowledge / 30-bd resolve / 45-bd extended deadlines with a pinned 2026–2027 federal-holiday calendar (Labor Day skip verified: received 2026-09-04 → deadline 2026-09-14)

Every formula-derived assert was pre-computed by executing the formulas in Python (projection paths, spread remainders, penalties, prorations, business-day arithmetic) — all literals replay-verified programmatically before finalizing.

## Step 3: Copy Shared Files — 2026-08-14T09:54:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `tasks/task_1693_loan_servicing_escrow_analysis/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T10:06:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1693_loan_servicing_escrow_analysis/workspace/PRD.md`.

**Structure**: §1 introduction (2 paragraphs, business-context angle); §2 with 10 subsections (RBAC, verbatim response structure, pagination, resource identity/versioning, logical clock + sweep, monetary precision, ledger conservation, OCC, validation ordering, two-dimensional account state); §3 with 9 lifecycle subsections (loan boarding → payees → line items/cushion → deposits/disbursements/advances → insurance/force-placement → tax monitoring → annual analysis → payment notices → error resolution); §4 endpoint table (4 columns, 83 rows); §5 error catalogue (2 columns, 36 rows). No contract-report footer in the file — PRD ends at §5.

**Key content decisions**:
- §2.2 pasted byte-identical from `section-2.2-response-structure.md` (verified programmatically).
- All formulas rendered as precise prose with pinned rounding orders and the scaffold's worked examples (3×100001 cushion rounding, business-day ack-deadline dates, 5000/4999 surplus boundary, 2026-09 finalize → 2026-11-01 notice effective date).
- Ambiguity resolution: the tax-record uniqueness rule has no error id in the scaffold, so the PRD states duplicates are rejected without inventing one; the 30/360 day-count follows the scaffold's explicit conditional clause (end-day 31 → 30 only when start day is 30 or 31); disbursement unblock on payee re-verification carries the endpoint table's `hold_status NONE` qualifier.
- The difficulty-design files were not opened or referenced.

**Hard Contract Reports**:

```
Field coverage check:
- entities[].fields + endpoint inputs/outputs + query params: 134 required, 134 present, 0 missing
- (checked programmatically against the parsed scaffold, fenced code blocks stripped)
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 18 checked, 18 expressed in prose (§2.9 fixed-order enumeration), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (expected_escrow_account_version / expected_disbursement_version + ERR_STALE_VERSION 412 each named), 0 missing
- state_machines[].transitions: 12 machines, all from→to pairs, preconditions, and side effects expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed (pinned rounding, variants, constants), 0 missing
- validations[] conditions: 18 checked, 18 matchable to error_id in §2/§3 prose (all 36 error ids appear in prose), 0 missing
- endpoints[].side_effects / applies_to: 83 endpoints checked, cascades and scopes expressed, 0 missing
- entities[].fields[] structured content: defaults, initial values, and ledger immutability (no updated_at/version) reconstructible from prose, 0 missing
- sibling-branch symmetry: reinstate ×3, mark-paid ×5, resolve ×2 outcomes, cancel ×2, advance recovery paths — equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 653
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional mechanical verification: all 95 enum/state values appear as exact backticked strings; §4 has exactly 83 endpoint rows matching the scaffold; §5 has exactly 36 error rows.

## Step 6: Generate Implementation — 2026-08-14T10:35:00.000Z

Implementation complete and verified.

## What was built

A full Python + Flask implementation of the Loan Servicing Escrow Analysis API in `/home/ubuntu/github/CodingPRD/tasks/task_1693_loan_servicing_escrow_analysis/workspace/implementation/`:

- `start.sh` — executable launcher with guarded `pip install` (no-op once Flask is importable, so per-test-server reboots stay fast) and `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000).
- `app.py` — app factory, blueprint registration, envelope-compliant error handlers (400/404/405/500).
- `store.py` — in-memory store, empty at every boot, logical clock defaulting to exactly `2026-08-01T00:00:00Z`.
- `util.py` — envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`, pagination fields `limit/offset/total_count/has_more` in meta), 3-fractional-digit timestamps, strict date/datetime parsing, month arithmetic, 30/360 day count, business-day add with the pinned federal-holiday list, `Decimal` ROUND_HALF_UP money helpers.
- `auth.py` — `X-User-ID`/`X-User-Role` validation (400), role authorization (403), borrower ownership (403).
- `domain.py` — ledger posting + replay (effective_date ASC, created-order tie-break), cushion recompute, advance waterfall (FIFO by created_at, larger-outstanding tie-break), advance-cap check (1,000,000), clock sweep (payee expiry + disbursement block cascade, insurance LAPSED/EXPIRED_CLOSED, tax DUE_SOON→DELINQUENT→PENALTY_ACCRUING→REDEMPTION_RISK with SIMPLE/COMPOUND penalty recompute), the 12-month trial-balance projection with both PROSPECTIVE and LEDGER_ACTUAL start balances, shortage/deficiency/surplus, pinned per-line-then-sum base monthly and floor-spread with first-month remainder, payoff/transfer and analysis-reopen cascades, notice creation.
- `routes_*.py` — all 70 endpoints: clock, loans, escrow accounts, deposits/ledger, line items, payees, disbursements, insurance, tax monitoring, analyses, notices, advances, error cases.
- Validation priority order from the scaffold is implemented per endpoint (auth → role → borrower ownership → path 404 → body FK 422 → shape 400 → OCC 412 → terminal 409 → from-state 409 → hold 409 → loan-active 409 → SoD 409 → notice windows 409 → coverage 409 → temporal → uniqueness → cross-entity → amounts 422).

## Verification

Four scenario scripts (run against fresh boots each) pass fully — roughly 150 assertions covering: envelope shape, pagination, RBAC and SoD, OCC (412 on both guarded writes), pinned rounding (3×100001 → 24999 monthly, cushion 50001), full analysis lifecycle (window 364 days, surplus 4999 credit vs 5000 refund boundary, notice effective/send-by dates, SPREAD_12 default, LUMP_SUM deposit proof, `ERR_DEFICIENCY_SPREAD_MANDATORY`), shortfall auto-advances and recovery waterfall, payee expiry cascade and re-verify unblock, force-placement notice windows + ACT_365/30-360 refund proration, business-day deadlines (Fri 2026-08-07 → ack 2026-08-14; Fri 2026-09-04 → 2026-09-14 skipping Labor Day), redemption risk at >730 days, error-case correction cascade re-opening the EFFECTIVE analysis and voiding notices, and payoff/transfer-out cascades zeroing the balance via SURPLUS_REFUND. Fresh boot is ~1 s (well under the 60 s limit), store is empty at boot, and repeated rapid reboots all succeed.

One judgment call to note: duplicate non-terminal tax records (parcel, year, sequence) have no error ID in the catalog; I reject with HTTP 409 and `ERR_DUPLICATE_TAX_RECORD`.

## Step 5: Generate Unit Tests — 2026-08-14T11:00:00.000Z

All audits pass. Generation is complete. Final state of the deliverables:

## What was generated

**`test_helpers/`** (Stage 1) at `/home/ubuntu/github/CodingPRD/tasks/task_1693_loan_servicing_escrow_analysis/test_helpers/`:
- `types.py` — 11 entity TypedDicts (EscrowLedgerEntry correctly carries only `id`+`created_at`, no `updated_at`/`version`) + 20 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (~70 methods covering `/servicing/*` and `/_clock/*`)
- `api_errors.py` — all 36 error IDs with HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions + `assert_balance_conservation` (ledger-sum invariant) and `assert_advance_decomposition`
- `factories.py`, `constants.py` (ADVANCE_CAP_CENTS=1000000, SURPLUS threshold 5000, holiday calendar, etc.)
- `test_users.py` — header constants for the 6 roles with dual identities per SoD desk (dp_1/dp_2, pv_1/pv_2, co_1/co_2) and `make_borrower_headers(loan_id)` for the entity-backed Borrower
- `fixtures.py` — composite chains: `setup_active_account`, `setup_released_disbursement`, `open_analysis_cycle` (auto-threads OCC version), `setup_computed_analysis`, `setup_effective_analysis` (+notice), `setup_policy_notice2`, `file_error_case`, `advance_case_to_investigating`, etc.

**`test_suite/`** (Stage 2): `conftest.py` + 10 numbered test files, **92 tests**, organized by concern (loans/accounts, payees, disbursements, advances, insurance, tax, analysis, notices, error cases, platform).

## Audit results (all green)
- **Completeness**: 18/18 difficulty instances × ≥2 tests; 54/54 non-stub corner instances × ≥1 test; the 3 `excluded_because:` stubs not translated (cross-references all resolve); every test has exactly one verbatim `Design:` tag.
- **Citation pass**: 134 quoted PRD passages verified verbatim against PRD.md (whitespace-normalized grep).
- No skip/xfail markers; no scaffold references in comments; all modules import cleanly.

## Notable adjudications (PRD-first filter)
1. **`validations/lump_sum_missing_then_satisfied`** — the instance's literal setup (funding deposit effective 2026-08-10, notice sent 2026-08-01) contradicts its expected `ERR_SHORTAGE_LUMP_SUM_MISSING` under the PRD's "effective_date on or after the notice's sent date" rule (the deposit would already satisfy the gate). Repaired the setup: funding deposit effective 2026-07-10 (before the sent date); the asserted rule and all expected outcomes are preserved.
2. **`priority_pair_validation_conflict/release_cancelled_early_state_beats_temporal`** — the recipe's CANCELLED vehicle is not uniquely derivable: CANCELLED is terminal, and PRD §2.9 evaluates terminal-state lockout (`ERR_ALREADY_TERMINAL`) before from-state validity. Translated the same priority-9-beats-15 claim via a BLOCKED disbursement (payee suspended, release date in future), which uniquely yields `ERR_INVALID_STATE_TRANSITION`.
3. **Dropped non-derivable micro-assertions**: initial `version == 1` (PRD never pins the starting version) and exact zero-fraction `created_at`/`current_utc` string matching where §2.4's three-fractional-digit rule conflicts with the bare literal (asserted the shared prefix / the clock endpoint's verbatim default instead).
4. **`tax_penalty_simple_vs_compound_accrual`** — added a second clock nudge (2026-11-16, same whole-month count) so `PENALTY_ACCRUING` is deterministic under both fixpoint and one-transition-per-pass sweep readings; the asserted amounts (13500 / 13704) are unchanged.

## Step 7: Run Tests and Iterate — 2026-08-14T11:20:00.000Z

All 8 rounds pass cleanly: 92/92 in every round, zero failures in any round log. Exiting with the summary.

## Summary

**Iterations run:** 2 (initial sweep → 4 deterministic failures fixed → clean 8-round sweep, 92/92 passed in all 8 rounds)

**Tests deleted:** None. All four failures were test-artifact bugs where the rule itself is verbatim in PRD; each test was repaired to faithfully express the PRD rule.

**Fixes applied to `test_suite/`:**

1. `/home/ubuntu/github/CodingPRD/tasks/task_1693_loan_servicing_escrow_analysis/test_suite/test_03_disbursements.py` — `test_create_line_item_with_unverified_payee_rejected`: setup created a `HAZARD_INSURANCE` line item, duplicating a `STANDARD_LINE_ITEMS` entry. Per PRD §2.9, uniqueness/duplicate constraints (`ERR_DUPLICATE_LINE_ITEM_TYPE`) are evaluated before cross-entity state requirements (`ERR_PAYEE_NOT_VERIFIED`), so the implementation correctly surfaced the duplicate error. Changed the test's line item to `FLOOD_INSURANCE` so the payee-verification gate is actually reached.

2. `/home/ubuntu/github/CodingPRD/tasks/task_1693_loan_servicing_escrow_analysis/test_suite/test_03_disbursements.py` — `test_release_debits_balance_and_ledger_stays_conserved`: assertion message said "release of 70000 against a 100000 balance leaves 30000" but the `setup_released_disbursement` call used the default `disbursement_amount=30_000` (leaving 70000). Added `disbursement_amount=70_000` to match the assertion.

3. `/home/ubuntu/github/CodingPRD/tasks/task_1693_loan_servicing_escrow_analysis/test_suite/test_07_analysis_cycles.py` — `test_shared_boundary_day_is_an_overlap`: used `projection_start_date="2027-08-31"`, which violates PRD §3.7's month-first rule; per §2.9, `ERR_PROJECTION_START_INVALID` (temporal gate) precedes the overlap check, so the implementation was correct. Changed the start to `2027-08-01` — the nearest legal month-first date inside the existing `[2026-09-01, 2027-08-31]` window — which still exercises `ERR_ANALYSIS_WINDOW_OVERLAP`.

4. `/home/ubuntu/github/CodingPRD/tasks/task_1693_loan_servicing_escrow_analysis/test_suite/test_07_analysis_cycles.py` — `test_tiling_window_starting_next_day_is_allowed`: hardcoded `window_end_date == "2028-08-31"` for start 2027-09-01, but PRD pins "exactly 364 days later"; the span includes leap day 2028-02-29, so the correct end is 2028-08-30 (implementation was right). Updated the expectation and comment.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:** None — the implementation was PRD-faithful in all four cases.

## Step 8: Finalize PRD — 2026-08-14T11:30:00.000Z

Done. `PRD_FINALIZED.md` is produced at `/home/ubuntu/github/CodingPRD/tasks/task_1693_loan_servicing_escrow_analysis/workspace/PRD_FINALIZED.md` and is byte-identical to `PRD.md` — the minimal patch is the empty patch, because all four Step 7 fixes were test-artifact repairs against behavior the PRD already uniquely determines and the implementation already follows.

**Line counts / delta**
- PRD.md: 356 lines; PRD_FINALIZED.md: 356 lines; delta 0 lines (0.0%). `diff` confirms identical.

**Per-item verification (no edits committed)**

- **§2.9 / §3.3 — duplicate line-item vs payee-verified ordering (test_03 item 1)** — no edit. PRD §2.9 (line 107) verbatim pins "then uniqueness and duplicate constraints; then cross-entity state requirements", and §3.3 (line 137) pins both rules verbatim. Impl matches: `implementation/routes_core.py` `create_line_item` checks duplicate expense_type (raises `ERR_DUPLICATE_LINE_ITEM_TYPE`, ~line 386) before payee verification (`ERR_PAYEE_NOT_VERIFIED`, line 389). The test had created a HAZARD_INSURANCE item duplicating a STANDARD_LINE_ITEMS entry; repaired to FLOOD_INSURANCE. Pure fixture bug.
- **§3.4 / §2.7 — release debit conservation (test_03 item 2)** — no edit. The failure was an intra-test inconsistency (assertion message assumed 70000 release, setup used default 30000; fixed by passing `disbursement_amount=70_000`). No PRD content implicated; impl release/balance behavior conforms to §3.4 and §2.7.
- **§3.7 / §2.9 — projection-start temporal gate vs window-overlap (test_07 item 3)** — no edit. PRD §3.7 (line 183) pins the month-first rule verbatim; §2.9 lists `ERR_PROJECTION_START_INVALID` among "the remaining temporal gates", which precede both "uniqueness and duplicate constraints" and "cross-entity state requirements" — the only two plausible categories for the overlap constraint, so the surfaced-error order is uniquely determined under any reading. Impl matches: `implementation/routes_analysis.py` lines 96-106 check month-first, then compute `window_end = start + timedelta(days=364)`, then scan for closed-interval overlap (excluding TERMINAL and DRAFT cycles). HTTP codes in §5 (422 / 409) match impl.
- **§3.7 — 364-day window end across a leap day (test_07 item 4)** — no edit. PRD §3.7 pins "exactly 364 days later, both ends inclusive" verbatim; impl derives it solely at `routes_analysis.py:98` (`start + timedelta(days=364)`), so 2027-09-01 → 2028-08-30 (span includes 2028-02-29). Test had hardcoded 2028-08-31; repaired.

**Pre-edit search log**: no edits were committed, so no wording required the mandatory pre-commit search. The verification searches above enumerated the relevant impl paths for each candidate edit subject — `routes_core.py` create_line_item (plus the parallel payee gates at `routes_disbursements.py:63,164`), `routes_analysis.py` cycle creation (the sole `window_end_date` derivation site), and the §5 error catalogue — and in each case confirmed the PRD already determines the implementation's behavior, so any "clarifying" wording would have risked violating the no-new-mismatch rule without cause. Under the hard scope (edits must trace to a step-7 item revealing PRD-silence or PRD/impl mismatch), zero items qualified.

## Step 9: Complete PRD — 2026-08-14T11:50:00.000Z

All 27 diff hunks correspond exactly to the intended edits. Final verification of the completed file state is done. Here is the summary.

## Summary

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1693_loan_servicing_escrow_analysis/workspace/PRD_COMPLETED.md`

**Source vs. output:** `PRD_FINALIZED.md` (source, byte-identical to `PRD.md`) — 356 lines / 60,528 chars → `PRD_COMPLETED.md` — 357 lines / 65,177 chars. Char delta: **+4,649** (one added line = the new §5 table row; all other changes are in-paragraph inserts/revisions).

**Counts:** 26 ambiguity-pins, 5 mismatch-revisions (27 diff hunks; two edits were mixed ambiguity+mismatch and are counted under both).

**Changes (one bullet per change):**

- §2.2 — insert — ambiguity — `api_request_timestamp` pinned to server wall clock (entity timestamps stay on the logical clock) — implementation/util.py:193,229,245 vs 154-170
- §2.3 — revise — mismatch — list ordering pinned to creation order, not a `created_at` sort (diverges only after a backward clock move) — implementation/util.py:222-238; all list handlers sort by `_seq`
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` rejected with `ERR_INVALID_REQUEST` (400); `offset` must be ≥ 0 — implementation/util.py:201-219
- §2.4 — insert — ambiguity — resources are created with `version` 1 and `updated_at` = `created_at` — implementation/util.py:154-161
- §2.5 — revise — ambiguity — clock-set accepts any well-formed instant, including earlier than the current reading (no forward-only constraint) — implementation/routes_core.py:70-85
- §2.7 — revise — mismatch — ledger replay tie-break pinned to creation order instead of `created_at` ascending — implementation/domain.py:43-46
- §2.7 — insert — ambiguity — no endpoint accepts a client-supplied `note`; every entry carries the empty-string default — all 15 `post_ledger` call sites (e.g. implementation/routes_core.py:341)
- §2.9 — revise — mismatch — borrower-ownership vs. path-existence order pinned: loan-nested endpoints check ownership against the path id before existence; deeper-nested ones (deposit, reinstate, notice-acknowledge) resolve the enclosing resource first, so 404 precedes `ERR_BORROWER_NOT_OWNER` — implementation/routes_insurance.py:83-85, routes_error_cases.py:55-56 vs routes_core.py:330-332, routes_insurance.py:254-256, routes_analysis.py:306-310
- §3.1 — insert — ambiguity — `principal_balance_cents`/`monthly_pi_cents` must be non-negative integers (`ERR_INVALID_REQUEST`) — implementation/routes_core.py:103-104
- §3.1 — insert — ambiguity — escrow-account creation is not gated on the loan's status — implementation/routes_core.py:212-231
- §3.1 — insert — ambiguity — payoff/transfer-out cascade leaves a `SETUP` account untouched; a loan with no account transitions with no cascade — implementation/domain.py:351-363
- §3.3 — insert — ambiguity — `expected_annual_amount_cents` must be a positive integer (`ERR_INVALID_AMOUNT`, 422) — implementation/routes_core.py:390
- §3.3 — insert — ambiguity — month arithmetic clamps day-of-month to target month length; installments computed from `first_due_date` so clamping never accumulates; applies wherever months are added — implementation/util.py:100-111
- §3.3 — revise — ambiguity — `REMOVED` pinned terminal: patch/re-remove of a `REMOVED` line item → `ERR_ALREADY_TERMINAL` — implementation/routes_core.py:442-445,465-466
- §3.4 — insert — ambiguity — deposit returns HTTP 201 with the posted `DEPOSIT` ledger entry; `source_entity_type` is `Deposit` and `source_entity_id` is the entry's own id — implementation/routes_core.py:341-345
- §3.4 — insert — ambiguity — scheduling with another account's `line_item_id` rejected with `ERR_INVALID_REQUEST` (400) — implementation/routes_disbursements.py:57-59
- §3.4 — insert — ambiguity — `RETURNED` is terminal in practice: the `ERR_ALREADY_TERMINAL` lockout covers only `CLEARED`/`CANCELLED`; actions on `RETURNED` fail from-state with `ERR_INVALID_STATE_TRANSITION` — implementation/routes_disbursements.py:127-130,192-196,206-209,220-223
- §3.4 — insert — ambiguity — waterfall `ADVANCE_RECOVERY` entries carry the triggering inflow's `effective_date` (deposit's date, or current date for force-placement refunds) — implementation/domain.py:138-155, routes_insurance.py:324
- §3.4 — insert — ambiguity — manual advance: non-`MANUAL_CORRECTION` reason → `ERR_INVALID_REQUEST` (400); non-positive amount → `ERR_INVALID_AMOUNT` (422) — implementation/routes_advances.py:44-53
- §3.4 — insert — ambiguity — `RECOVERED` and `WRITTEN_OFF` pinned terminal (`ERR_ALREADY_TERMINAL` on recover/write-off) — implementation/routes_advances.py:90-91,115-116
- §3.5 — insert — ambiguity — `annual_premium_cents` must be a positive integer (`ERR_INVALID_AMOUNT`, 422) — implementation/routes_insurance.py:92-105
- §3.5 — insert — ambiguity — force-placement charge/refund on a loan with no escrow account still transitions the policy but posts no ledger entry, creates no advance, touches no account — implementation/routes_insurance.py:226-248,320-329
- §3.5 — insert — ambiguity — refund with no qualifying evidence policy rejected with `ERR_INVALID_STATE_TRANSITION` (409) — implementation/routes_insurance.py:303-304
- §3.5 — insert — ambiguity — reinstatement enforces no new-end vs new-start ordering and accepts any integer `new_annual_premium_cents` without a positivity check — implementation/routes_insurance.py:258-278
- §3.6 — revise — mismatch — duplicate tax record rejected with `ERR_DUPLICATE_TAX_RECORD` (409), scoped per loan; error id added to the §5 catalogue — implementation/routes_tax.py:51-57
- §3.6 — insert — ambiguity — `amount_due_cents` positive (`ERR_INVALID_AMOUNT`, 422); `monthly_penalty_rate_bps`/`grace_period_days` non-negative (`ERR_INVALID_REQUEST`) — implementation/routes_tax.py:44-59
- §3.6 — revise — ambiguity — mark-paid: disbursement not `RELEASED`/`CLEARED`, or belonging to another loan's account, each rejected with `ERR_INVALID_AMOUNT` (422), not only the shortfall — implementation/routes_tax.py:116-125
- §3.6 — insert — ambiguity — mark-paid from `MONITORING`/`DUE_SOON` after `due_date` + grace (sweep not yet run) rejected with `ERR_INVALID_STATE_TRANSITION` — implementation/routes_tax.py:111-114
- §3.7 — revise — ambiguity — `analysis_year` pinned integer; opening a cycle is not gated on `account_status`/`hold_status` — implementation/routes_analysis.py:75-98
- §3.7 — insert — ambiguity — new `DRAFT` cycle's computed fields null except `shortage_cents`/`deficiency_cents`/`surplus_cents`/`spread_monthly_cents`/`spread_first_month_cents`, which start at 0 — implementation/routes_analysis.py:113-135
- §3.7 — revise — mismatch — compute checks the compliance-hold gate before the account-`ACTIVE` gate, a documented exception to §2.9's generic priority — implementation/routes_analysis.py:171-174
- §3.8 — insert — ambiguity — apply-from-`SENT` `SPREAD_12` default leaves the notice's `shortage_option` null — implementation/routes_analysis.py:330,336-373
- §3.9 — insert — ambiguity — resolve `outcome` must be `CORRECTED` or `NO_ERROR` (`ERR_INVALID_REQUEST`, 400) — implementation/routes_error_cases.py:165-168
- §3.9 — insert — ambiguity — `correction_amount_cents` supplied with `NO_ERROR` is ignored; field stays null — implementation/routes_error_cases.py:202-203,216-217
- §3.9 — insert — ambiguity — `dismissal_reason` is stored into the case's `resolution_note` field — implementation/routes_error_cases.py:235
- §5 — revise — mismatch — added `ERR_DUPLICATE_TAX_RECORD` | 409 row to the error catalogue — implementation/routes_tax.py:56

**Notable non-changes (verified already aligned):** penalty day-count/rounding formulas, advance-cap and waterfall FIFO order, analysis projection evaluation order (old payment for all 12 months), shortage/deficiency/surplus formulas, spread floor-division with first-month remainder, notice effective/send-by derivation, business-day deadlines with the pinned holiday calendar (both PRD examples reproduce), SoD checkpoints, and all §2.9 bucket orderings except the two documented pins (compute's hold-first; borrower-ownership nesting rule).
