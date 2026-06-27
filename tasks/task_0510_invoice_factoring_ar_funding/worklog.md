# Worklog — task_0510_invoice_factoring_ar_funding

## Step 1: Create Task Directory — 2026-06-27T00:00:00.000Z

Created `tasks/task_0510_invoice_factoring_ar_funding/` and `tasks/task_0510_invoice_factoring_ar_funding/workspace/` via mkdir -p. Directory was pre-allocated by the orchestration request; index not re-scanned.

## Step 2: Generate Scaffold — 2026-06-27T00:10:00.000Z

All three files written to task dir (SCAFFOLD.yaml 828 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1332 lines, SCAFFOLD_CORNER_DESIGN.yaml 1560 lines). Subagent summary verbatim:

Generated all three scaffold artifacts for **task_0510_invoice_factoring_ar_funding** (BlueVine-style Invoice Factoring & A/R Funding), designed at **Expert** difficulty. All files written to `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0510_invoice_factoring_ar_funding/`:

- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, single key `scaffold_corner_design`)

**Entity count: 12** — FactoringProgram, Client, Debtor, ClientDebtorRelationship (M:N junction), Invoice, PurchaseBatch, Verification, CollectionPosting, Adjustment, Buyback, Settlement, LedgerEntry (append-only). Topology is flat/graph: peer entities under `/factoring` joined by FK filter params.

**Profile:** ledger-reconciliation + compliance-audit; layers = dual-variant calc, cascading side-effects, rate/threshold triggers, OCC, derived-field reconciliation; branching state-machine shape; segregation-of-duties role model (PlatformAdmin, UnderwritingOfficer, FundingOfficer, CollectionsOfficer).

**State machines (5):** Client (PENDING→APPROVED→SUSPENDED↔/CLOSED), Debtor (PENDING→APPROVED→INSOLVENT with cascade), ClientDebtorRelationship (cyclic notice_status PENDING→NOTICED↔SUSPENDED), Invoice (branching: SUBMITTED→VERIFIED→FUNDED→OUTSTANDING forking to SETTLED vs SHORT_PAID→BOUGHT_BACK/WRITTEN_OFF), PurchaseBatch (DRAFT→FUNDED/FAILED all-or-nothing). 2 OCC concurrency rules on Client.version (fund-batch, posting).

**Key calculations (6):** `advance_split` (round-half-up principal/reserve), `factoring_fee` (dual-variant: flat PROVISIONAL per-diem vs tiered FINAL with round-per-tier-then-sum — diverge 2250 vs 2625 at 45 days), `settlement_rebate` (3-bucket waterfall principal→fee→rebate), `recourse_buyback`, `debtor_concentration` (exact cross-multiplied ratio, `>` rejects / `==` allows), `aging_bucket` (DPD thresholds). 50 endpoints, 21 error codes, 22 ordered validations. All formula-derived asserts pre-computed as literals via Python.

**Difficulty/corner coverage:** §1.8 has all 9 Difficulty Rules × 2 differentiated instances = **18 instances**; §1.9 has **37 instances (30 active + 7 excluded_because stubs)** across 8 claim-extraction sections.

**Verification:** `scaffold_lint.py` returns **VERDICT: clean lint** (498 calls scanned, all conform to §1.5; all 12-entity FKs have reverse-reachability GETs). Additional manual audits passed: all grounds refs resolve, OCC version freshness correct across all chains, no dead system enums, every error code referenced, no forbidden concurrency vocabulary, no id-based business decisions, clock default `2026-05-01T00:00:00Z` declared. One real bug caught and fixed during design: the concentration-boundary test originally couldn't fund its first invoice (100% concentration) — restructured with per-relationship limit overrides so each funding step satisfies the cap while the candidate lands exactly at the 0.50 boundary.

## Step 3: Copy Shared Files — 2026-06-27T00:12:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0510_invoice_factoring_ar_funding/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-27T00:25:00.000Z

PRD written to workspace/PRD.md (311 lines). Subagent summary verbatim:

Generated the PRD at workspace/PRD.md (311 lines).

Major sections: §1 Introduction (BlueVine-style invoice factoring / A/R funding, ledger-reconciliation + compliance). §2 Global Specifications (10 subsections): RBAC 4 roles (identity opaque, credit_decision_user_id recording), response envelope, pagination, common properties + logical clock + OCC, path resolution/referential integrity, validation priority order, monetary precision/round-half-up, reserve/exposure/append-only ledger, hierarchical consistency & cascades, concentration/credit-limit/aging. §3 Business Logic (8 subsections): program setup & onboarding, underwriting/credit decisions, relationships & notice-of-assignment, invoice submission/verification, batch funding (OCC + segregation + 5 funding preconditions + advance-split cascade), collections/aging/settlement waterfall, final fee/buyback/write-off, adjustments. §4 Endpoint Definitions (51 endpoints incl. /_clock/set_current_utc). §5 Error Code Catalogue (21 error IDs).

Hard Contracts: Contract 1 Field-Name Coverage PASS (70/70). Contract 2 Rule Coverage PASS (validations ordering, 2 OCC rules, all state-machine transitions, all 6 calculations incl. factoring_fee per-tier-round-then-sum + settlement waterfall + concentration cross-multiply + aging inclusive edges, all 21 error IDs, side-effects, sibling-branch symmetry). Contract 3 §3 Path Purity PASS (422 tokens scanned, 0 paths/methods leaked). Did not open either design index file.

## Step 5: Generate Unit Tests — 2026-06-27T00:55:00.000Z

test_helpers/ (9 files) + test_suite/ (11 files, 66 test functions) written. Subagent summary verbatim:

Generated complete test infrastructure for task_0510 (Invoice Factoring & A/R Funding) from the two design indices only — no freelance walks of SCAFFOLD.yaml.

test_helpers/ (9 files) — Stage 1, PRD-specific infrastructure: types.py (status enums + entity TypedDicts; Verification/LedgerEntry correctly carry only id+created_at), api_client.py (one method per endpoint), api_errors.py (20 error IDs + HTTP map registered with framework), assertions.py, factories.py (input fields only), constants.py, test_users.py (4 opaque roles + per-id builders for the segregation-of-duties case), fixtures.py (composite onboarding→fund→collect→terminalize chains), __init__.py barrel export. All imports resolve against a stubbed framework.

test_suite/ (11 files) — Stage 2, 66 test functions, each tagged with exactly one Design: line: test_01 fee calculations, test_02 settlement waterfall/cascade, test_03 state-machine branching/invariants, test_04 priority/boundary, test_05 cross-entity/temporal (Queue A); test_06–test_10 cover Queue B entities/state-machines/calculations/validations+errors/rbac+concurrency.

Coverage: Queue A (Difficulty) all 18 instances translated, 0 skipped, each with ≥2 tests (36 difficulty-tagged tests). Queue B (Corner) all 30 non-stub instances translated, 0 skipped, ≥1 test each (30 corner-tagged tests). The 7 excluded_because stubs correctly NOT translated; all 7 cross-references resolve to real difficulty instances.

Verification passes: 66 test functions ↔ 66 Design lines (no untagged/dual-tagged). Every difficulty instance ≥2 tests. Verbatim PRD-citation check passed (fixed 3 citations using elision). No skip/skipif/xfail; no scaffold leakage. Whole suite parses and collects under pytest (66 collected, 0 errors). All instances passed the PRD-first two-condition filter; no gaps required skipping.

## Step 6: Generate Implementation — 2026-06-27T00:55:00.000Z

Implementation written to workspace/implementation/. The generation subagent's final API call hit a transient 503 Bedrock server error during its summary/verification phase (after 102 tool uses), so no verbatim summary was returned. Orchestrator verified the artifact directly:
- Files present: app.py, common.py, db.py, errors.py, middleware.py, response.py, requirements.txt (flask==3.0.3), start.sh (reads $PORT, binds 0.0.0.0, foreground, conditional pip install), routes/ (programs, clients, debtors, relationships, invoices, collections, batches, clock, helpers — 1278 lines), services/ (calc, ledger, transitions, views — 446 lines).
- `python3 -m py_compile` over all .py files: ALL COMPILE OK (no truncation).
- `import app` succeeds; url_map reports 51 routes registered (matches PRD's 51 endpoints).
- In-memory storage only (db.py dicts); no seeding at startup.
Functional completeness will be validated by Step 7's diagnostic loop rather than re-running generation.

## Step 7: Run Tests and Iterate — 2026-06-26T21:20:13.000Z

Continuation run (prior run interrupted at Step 7 by transient Bedrock 503 before any sweep ran). Long-lived fix subagent owned the full run-diagnose-fix-rerun loop. Final state: all 8 parallel rounds pass 65/65, zero failures, no flakiness. Subagent summary verbatim:

**Iterations run:** 2 (baseline sweep + 1 verification sweep after the fix).

**Tests deleted:**
- `test_settlement_waterfall_three_bucket_minmax_short_pay` (test_suite/test_02_settlement_waterfall_cascade.py) — **BRANCH-ASYMMETRIC SIDE EFFECT** (STEP 1b). The test asserted a `Settlement` record exists (`len(data) == 1`) and read `principal_applied_cents`/`fee_applied_cents`/`rebate_cents` off it on the **short-pay** branch (`OUTSTANDING → SHORT_PAID`). PRD §3.6 line 212 renders the full-settlement happy path fully ("Settlement records a `Settlement` child carrying ...") but the short-pay branch (line 214) enumerates its side effects exhaustively — sets `advance_outstanding_cents`, pins `final_fee_cents`, appends `COLLECTION_POSTED` + `FEE_ACCRUED`, increments `version`, and explicitly contrasts "Unlike a full settlement..." — and never states a `Settlement` record is created. The waterfall fields appear in PRD only as formula intermediates and as full-settlement `Settlement` attributes, never as a short-pay response-visible surface (line 222 even allows "or zero if none" prior waterfall, implying short-pay persists none). A faithful PRD-only implementer would not create a Settlement on short-pay, so the test fails on a faithful implementation — unique derivability broken. No value assertion was salvageable under STEP 1c since the entire precondition (the Settlement record) is PRD-silent. Driving scaffold rule: Difficulty/combinatorial_formula/cf_settlement_waterfall_three_bucket_minmax.

**Fixes applied to test_helpers/:** None.

**Fixes applied to implementation/:** None. The implementation (`services/transitions.py: short_pay_invoice`) was already PRD-faithful — it runs the waterfall internally, sets `advance_outstanding_cents`, pins the fee, and appends `COLLECTION_POSTED` + `FEE_ACCRUED` without persisting a Settlement, exactly matching PRD §3.6 line 214.

Final state: all 8 parallel rounds pass 65/65 with zero failures and no flakiness.

## Step 8: Finalize PRD — 2026-06-26T21:44:38.000Z

Step 7 had 1 test deletion (>0), so Step 8 ran (skip condition not met). The PRD_FINALIZED.md edit was committed and verified by the subagent, but its final summary-text emission was lost to a transient Bedrock 503 (the subagent had already finished the substantive work — committed the edit and run `wc -l` confirming both files at 311 lines — before the 503 hit). Summary reconstructed by the orchestrator from the verified subagent transcript + on-disk diff (no verbatim subagent summary available):

- PRD.md vs PRD_FINALIZED.md: 311 vs 311 lines (0.0% line-delta); 48073 → 48270 chars (+197 chars). Exactly 1 line revised (line 214, §3.6 Short pay).
- Change: §3.6 Short pay branch — revise — added an explicit clause that the `OUTSTANDING → SHORT_PAID` short-pay branch persists **no** `Settlement` record; the waterfall figures (principal/fee/rebate) are computed only to drive `advance_outstanding_cents` and `final_fee_cents` pinning and are not exposed as a stored child. Pins the PRD silence surfaced by the Step 7 deletion of `test_settlement_waterfall_three_bucket_minmax_short_pay`. Impl alignment target: services/transitions.py `short_pay_invoice` (creates no Settlement; the full-settlement path DOES create one, leaving the "Unlike a full settlement..." contrast intact).
- Pre-edit search log: (a) subject = whether the short-pay branch persists a `Settlement` record + the visibility of waterfall figures; (b) impl paths enumerated — services/transitions.py `short_pay_invoice` (no Settlement) and the full-settlement path (creates a Settlement child), plus the collections/settlement route handlers and services/views.py serializer (no short-pay Settlement serialized anywhere); (c) wording scoped to assert the Settlement-absence ONLY on the short-pay branch and preserve the existing full-settlement contrast, so the full-settlement Settlement-creation path is not mis-described.

## Step 9: Complete PRD — 2026-06-26T22:15:50.000Z

Full PRD-vs-implementation completeness scan, started from PRD_FINALIZED.md. The subagent's run was resumed once after a transient Bedrock 503 (it had completed the cp + begun the impl walk; resumed from preserved transcript, then ran to completion). Subagent summary verbatim:

Summary:
- Source PRD_FINALIZED.md: 311 lines / 48,270 chars. PRD_COMPLETED.md: 311 lines / 50,615 chars. Char delta: +2,345. (All edits in-paragraph; no lines added/removed, no new sections.)
- Counts: ambiguity-pins = 4, mismatch-revisions = 4 (total 8 changes).
- Per change:
  - `§2.3 Pagination` — insert — ambiguity — pinned that a non-integer / out-of-bounds `limit` (below 1 or above 100) or negative `offset` is rejected with `ERR_INVALID_REQUEST` (422) rather than clamped, with empty/omitted falling back to default — `middleware.py:54-66`.
  - `§2.3 Pagination` — insert — ambiguity — pinned the list sort tie-break (records sharing a `created_at` are ordered by insertion sequence ascending) — `routes/helpers.py:37-39`.
  - `§2.8 Append-Only Ledger` — revise — mismatch — PRD claimed a "signed `amount_cents` whose sign follows the convention of its entry type"; impl stores every entry's amount as a non-negative magnitude (no sign ever applied). Revised to pin unsigned magnitudes and the per-entry-type amount each carries — `services/ledger.py:33-46`, `services/transitions.py:35-36,74-76,119-120,169-170,194-195`.
  - `§2.10 Debtor concentration` — revise — mismatch — impl carves out the case where the candidate's debtor already constitutes the client's entire pre-candidate portfolio (incl. the all-zero first-funding case): the ceiling is treated as satisfied regardless of limit; PRD prose would have rejected for limits < 1. Added the carve-out clause — `services/calc.py:138-139`.
  - `§3.4 Verification` — revise — mismatch — PRD required both `confirmed_amount_cents == face_amount_cents` AND `method != WAIVED` when `verification_required`; impl enforces only the confirmed-amount equality and does not constrain `method`. Revised to match — `routes/invoices.py:129-132`.
  - `§3.5 Batch funding preconditions` — insert — ambiguity — pinned that an invoice reached in array order that is not `VERIFIED` (e.g. `SUBMITTED`/terminal) is itself a funding-precondition failure surfacing `ERR_FUNDING_BLOCKED` (not `ERR_INVALID_STATE`) — `routes/batches.py:172-174`.
  - `§3.6 Collections` — insert — ambiguity — pinned that every accepted posting bumps the owning client's `version` by one (even a partial collection moving no reserve), while reversal touches only the posting and its invoice and does not bump client `version` — `routes/collections.py:83`, `routes/collections.py:120-124`.
  - `§3.6 Provisional fee` — insert — ambiguity — pinned that read-time `accrued_fee_cents` is recomputed provisionally only while `FUNDED`/`OUTSTANDING`; after terminalization it reports the frozen `final_fee_cents` — `services/views.py:18-21`, `services/transitions.py:50,107,149,185`.
