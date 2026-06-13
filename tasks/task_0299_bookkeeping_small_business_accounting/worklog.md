# Worklog — task_0299_bookkeeping_small_business_accounting

## Step 1: Create task directory — 2026-06-11T08:52:34.000Z

Created `tasks/task_0299_bookkeeping_small_business_accounting/` and `tasks/task_0299_bookkeeping_small_business_accounting/workspace/`. Pre-assigned index 0299 (no ./tasks/ scan, per orchestrator directive — 4 sibling tasks running concurrently).

## Step 2: Generate scaffold (Expert) — 2026-06-11T09:15:00.000Z

**task_0299_bookkeeping_small_business_accounting — scaffold generated (Expert band)**

Domain: double-entry bookkeeping & small-business accounting. Archetype: Ledger reconciliation × Compliance/audit. Topology: **flat** (peer entities under `/ledger`, FK-linked). State-machine shape: **parallel** (Invoice delivery × payment axes) plus cyclic loops. Role model: **segregation_of_duties**. Consistency: immediate.

- **Entities: 14** — Company, Account (self-referential sub-accounts), AccountingPeriod, JournalEntry, JournalLine, BankAccount, BankFeedTransaction, Reconciliation, Customer, Invoice, InvoicePayment, Vendor, Bill, TaxRate.
- **State machines: 7** — AccountingPeriod (OPEN↔CLOSING↔CLOSED, cyclic reopen), JournalEntry (DRAFT→POSTED→VOIDED w/ reversal), BankFeedTransaction (UNMATCHED↔CATEGORIZED cyclic, →EXCLUDED), Invoice (DRAFT→SENT→VOID delivery axis + UNPAID/PARTIALLY_PAID/PAID payment axis = parallel), InvoicePayment (CLEARED→REVERSED), Bill (DRAFT→APPROVED→PARTIALLY_PAID/PAID, →VOID), Reconciliation (IN_PROGRESS→RECONCILED/ABANDONED).
- **Concurrency rules: 2** — OCC on Company.version (period open) and BankAccount.version (reconciliation finalize); both 412 ERR_STALE_VERSION.
- **Calculations: 6** — account_balance (posted vs projected dual-variant), vendor_1099_total (cash vs accrual dual-variant), bill_use_tax_total (per-line round-then-sum, mode b), invoice_total_breakdown (discount-tier→tax-on-discounted-base→total pinned eval order, mode c), reconciliation_difference (exact-zero), invoice_balance_and_payment_status (AR conservation).
- **Validations: 22** (priority-ordered, auth→existence→state→business). **Endpoints: 64** (flat CRUD + reverse-reachability GETs + actions + computed reads: account balance, vendor 1099, financial statements). **Error catalog: 32**. **RBAC roles: 4** — Owner, Accountant, Bookkeeper, Auditor (all `identity: opaque`; maker-checker SoD on journal posting).
- **Difficulty design: 9 rules × 2 = 18 instances**; all nine §0.5 rules satisfied with proper differentiation.
- **Corner design: 31 instances** (26 full + 5 `excluded_because` stubs) across entities, state_machines, calculations, validations, endpoints, rbac, cross-cutting layers, consistency_model.

`scaffold_lint.py` → **VERDICT: clean lint** (416 calls scanned, all conform to §1.5; all 35 FKs reverse-reachable). All formula-derived asserts pre-computed as literals; zero unbound placeholders; all grounds resolve; design keys correctly separated into their own files.

Note: endpoint count (64) runs above the Expert 20–32 guideline — driven by 14 flat entities each needing single-GET + filtered-list GET for FK reverse-reachability plus the 8 named subsystems' action endpoints; band is a soft guideline, difficulty here comes from cascade depth, dual variants, and parallel/cyclic state rather than surface volume.

## Step 3: Copy INSTRUCTION.md — 2026-06-11T09:16:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0299_bookkeeping_small_business_accounting/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-11T09:22:00.000Z

PRD generated at `workspace/PRD.md` (325 lines, ~7,350 words, ~53.8 KB).

**Structure:** §1 Introduction (business-context + double-entry-integrity). §2 Global Specs — 10 subsections: RBAC, Response Structure (verbatim), Pagination, Common Properties/Identifiers, Double-Entry Ledger & Posted Balances, Cascading Recomputation/Reversal, OCC, Monetary Precision & Tax Rounding, Accounting Period & Open-Period Lock, Sales/Use Tax & Effective Windows. §3 Business Logic — 11 subsections by lifecycle/entity (company+chart-of-accounts, period open/work/close, journal drafting, posting/maker-checker/void, bank-feed categorization loop, invoices+tiered-discount tax, customer payments, vendors/bills/use-tax/1099, reconciliation, financial statements, §3.11 validation-ordering for the 22 priority-ordered validations). §4 endpoint table (65 endpoints). §5 error table (32 errors).

**Rendering decisions:**
- Entities (16 incl. JournalLine): field names scattered through narrative; §2.4 names JournalLine as the lone `common_fields:false` entity (only id+created_at).
- State machines (7): state-transition prose, UPPERCASE states, preconditions paired with error IDs, side-effects stated incl. 3-hop CASCADE A (closing entry → zero revenue/expense → recompute retained earnings) and CASCADE B (reversal).
- Calculations (6): precise prose, no pseudocode. Invoice breakdown w/ pinned subtotal→discount→tax→total order + tier thresholds (500,000/1,000,000 cents at 5%/10%); per-line round-half-up-then-sum for invoice tax + bill use tax; 1099 accrual vs cash variants + tax-year derivation; reconciliation difference; invoice balance/payment-status.
- OCC: both rules rendered in stale-version terms (expected_company_version / expected_bank_account_version + ERR_STALE_VERSION 412).
- Roles (4): all named, all identity:opaque, created_by_user_id capture noted for maker-checker.

**Hard Contracts — all PASS:** Contract 1 Field-Name Coverage 104/104. Contract 2 Rule Coverage — 32/32 error IDs in body, all states + enum values present. Contract 3 §3 Path Purity — 583 backtick tokens, 0 path-leading/bare-method/method+path. §2.2 byte-for-byte identical to canonical source.

**Zero-Silence note:** priority-ordered validation chain given own §3.11 (22-rule ordering incl. archived-before-categorization-type subtlety + OCC-last) explicit. Fuzzy-word scan flagged only innocuous prose, no precision-bearing hedges.

## Step 5: Generate unit tests — 2026-06-11T09:36:00.000Z

**Test file count:** 8 test files + conftest.py in `test_suite/`; 9 files in `test_helpers/`.

**Total tests:** 62.
- **Queue A (Difficulty):** 36 tests — all 18 difficulty instances (9 rules × 2) covered with exactly 2 tests each.
- **Queue B (Corner):** 26 tests — all 26 non-stub corner instances covered with exactly 1 test each.

**Instances SKIPPED:** 0 dropped on the PRD-first filter — every non-stub instance had verbatim PRD coverage and a uniquely-derivable outcome. The 5 `excluded_because:` corner stubs (post_already_posted_entry_returns_invalid_state, account_projected_balance_equals_posted_when_no_drafts, priority_post_state_before_fiscal, occ_stale_bank_version_on_recon_finalize, derived_account_balance_reconciles_after_post) correctly NOT translated; all 5 cross-references resolve to real difficulty instances.

**test_helpers files emitted:** types.py, api_client.py (one method per endpoint), api_errors.py (30-entry error→HTTP map), assertions.py (per-entity + AR-identity invariant), factories.py, constants.py, test_users.py (4 opaque roles + maker-checker id threading), fixtures.py (company+chart+period base, posted/draft entries, bank-feed categorization, sent invoices, approved/paid bills, period-close-to-CLOSED, reconciliation), __init__.py barrel.

**Notable design-coverage decisions:**
- JournalLine TypedDict + assert_journal_line omit updated_at/version per PRD §2.4 (append-only row).
- Maker-checker threading: fixtures draft as u_book and post as u_acct (segregation passes by default); segregation test deliberately drafts+posts under one u_acct id.
- accounting_period_non_contiguous: avoided not-uniquely-derivable "contiguous-accepted" positive test; used two distinct rejection scenarios (forward gap + backward overlap) pinned to verbatim "start_date must equal prior end_date" rule.
- Two priority-pair instances (state-vs-fiscal, unbalanced-vs-stale) grounded on §3.11 explicit verbatim ordering prose.
- All 69 quoted citation fragments verified verbatim against PRD.md; no skip/xfail, no scaffold/section leakage.

## Step 6: Generate implementation — 2026-06-11T09:36:00.000Z

**File layout** (`workspace/implementation/`): start.sh (guarded pip install then exec python3 app.py; reads $PORT default 10000, binds 0.0.0.0, foreground); requirements.txt (flask==3.0.3); app.py (~1690 lines, all 62 endpoints, error handlers, period helpers); db.py (in-memory dicts per entity, make_record/touch, reset_all, monotonic _seq for stable sort); ledger.py (double-entry engine: signed balance, trial-balance, posting + reversal cascade); calculations.py (invoice_total_breakdown + bill_use_tax_total via Decimal/ROUND_HALF_UP); errors.py, response.py, middleware.py, serializers.py, util.py.

**Storage:** pure in-memory dicts keyed by UUID; empty on every boot; nothing seeded. State wipes verified across re-launches.

**State machines:** all six implemented (AccountingPeriod OPEN→CLOSING→CLOSED→OPEN; JournalEntry DRAFT→POSTED→VOIDED; BankFeedTransaction UNMATCHED↔CATEGORIZED,→EXCLUDED; Invoice DRAFT→SENT→VOID + independent payment axis; InvoicePayment CLEARED→REVERSED; Bill DRAFT→APPROVED→PARTIALLY_PAID/PAID,→VOID; Reconciliation IN_PROGRESS→RECONCILED/ABANDONED). CASCADE A (post-close closing entry zeroing REVENUE/EXPENSE → retained earnings) and CASCADE B (reversal) keep trial-balance invariant; reopen reverses closing entry.

**Calculations:** pinned order subtotals→discount→tax→total; tier discount on taxable subtotal (5% ≥$5k, 10% ≥$10k); per-line round-half-up tax on discounted base scaled by discounted/taxable ratio; bill use-tax per-line then summed; vendor 1099 accrual (bill totals by bill_date) vs cash (paid_in_tax_year). Verified vs worked examples (600000 taxable → 30000 discount, 49875 tax).

**Validations/RBAC:** priority-ordered per §3.11 (headers→role→account-existence→general-existence→state→segregation→archived-before-categorization-type→structural→fiscal→content→OCC). Owner-exclusive void/reopen/company-create/config; Accountant-exclusive close steps; Auditor read-only; maker-checker on posting.

**OCC:** expected_company_version on period open, expected_bank_account_version on recon finalize → ERR_STALE_VERSION (412); checked only when supplied.

**Notable PRD-ambiguity resolutions:**
1. Reversal/void balance model — VOIDED entries' lines remain counted; POSTED reversal cancels them (honors §2.5 posted-derived + §2.6 non-erasure); trial balance stays BALANCED, restores on reopen.
2. Bill use-tax "company default jurisdiction" — no such field; resolved to company TaxRate whose window covers bill_date (most-recently-created wins on overlap), 0 if none.
3. is_cash on non-ASSET account create — no dedicated error; rejected with ERR_INVALID_REQUEST.

## Step 7: Test-and-fix loop — 2026-06-11T09:55:00.000Z

All 8 parallel rounds pass cleanly (60/60 each, 0 failures, 0 errors, 0 skipped). Total dropped from 62 to 60 (two tests deleted). The transient round-3 connection error did not recur. Clean sweep achieved — exited.

**Iterations run:** 2 (initial diagnostic sweep + post-fix verification sweep). Post-fix sweep clean across all 8 rounds (60/60 each).

**Initial state:** 4 deterministic failures in all 8 rounds, plus 1 transient ConnectionError in round 3 (server boot under 8x load, not a real bug — did not recur).

**Tests deleted (2):**
- `test_get_account_nonexistent_returns_not_found` (test_01_chart_of_accounts.py) — ERROR-ID SILENCE / non-unique-derivability. Asserts direct `GET /ledger/accounts/{id}` of a missing account returns `ERR_NOT_FOUND`, but PRD §3.11 ties missing `account_id` to `ERR_ACCOUNT_NOT_FOUND` (impl's choice) while §2.4 only says a missing path id "produces a 404" without naming the error_id. Both readings PRD-faithful → outcome not uniquely determined. Scaffold rule: Corner/entities/get_account_nonexistent_returns_not_found.
- `test_closing_entry_direct_void_protected` (test_04_period_close_cascade.py) — ERROR PRECEDENCE SILENCE. Asserts directly voiding a closing entry yields `ERR_CLOSING_ENTRY_PROTECTED`. But a CLOSING-source entry always lives in a CLOSED period, and §3.11 fixes precedence so `ERR_PERIOD_CLOSED` is evaluated before `ERR_CLOSING_ENTRY_PROTECTED`. Under any §3.11-faithful impl `ERR_PERIOD_CLOSED` wins (as impl returns); asserted error unreachable via a real closing entry. Scaffold rule: Corner/state_machines/closing_entry_direct_void_protected.

**Fixes applied to test_suite/ (test-setup faithfulness, STEP 2):**
- `test_08_tax_rates_and_periods.py`, helper `_company_with_first_period` — the two contiguity tests (`test_non_contiguous_period_with_gap_rejected`, `test_period_start_before_prior_end_rejected`) left the first period OPEN, but PRD §3.2/§2.9 key the contiguity rule on "the prior CLOSED period's end_date". The PRD-faithful impl only checks contiguity against closed periods, so the second period opened successfully and the tests saw an object instead of an error. Fixed the helper to fully close the first period (complete checklist, begin-close, post-close) before the next open; added `checklist_item_payload` to the import block.

**Fixes applied to implementation/:** None. The implementation was already PRD-faithful on all four failures; corrective action was deletion of two non-derivable tests and one test-setup fix.

Final: 60/60 tests pass across all 8 rounds.

## Step 8: Finalize PRD — 2026-06-11T10:02:00.000Z

Produced `workspace/PRD_FINALIZED.md`. **Line counts:** PRD.md = 325, PRD_FINALIZED.md = 325 (+0 lines; one line revised in place, +1 sentence). ~0% delta.

**Changes (1):**
- §2.4 — revise — Pinned that a missing **path** identifier surfaces `ERR_ACCOUNT_NOT_FOUND` when it is an accountId, and `ERR_NOT_FOUND` for every other resource's path id. PRD previously said only "produces a 404" without naming the error_id, leaving direct `GET /ledger/accounts/{id}` (and /balance, /archive) miss non-uniquely-derivable between the two 404 codes — impl `util.py:118-123` (get_account_or_404 → account_not_found), wired at app.py:220,241,258.

**Items from <step_7_diff> requiring NO PRD edit (and why):**
- Deleted test test_closing_entry_direct_void_protected — pure precedence already pinned by §3.11. Impl (app.py:649-658) checks ERR_PERIOD_CLOSED (priority 11) before CLOSING-source ERR_CLOSING_ENTRY_PROTECTED (priority 20); a closing entry always lives in a closed period, so ERR_PERIOD_CLOSED always wins. §3.4 prose stays verbatim.
- test_08 contiguity fixture fixes — pure test-setup bugs. PRD §3.2/§2.9 already pin contiguity against "the prior closed period's end_date"; impl (app.py:289-299) keys strictly on the most recent CLOSED period. No silence/mismatch.

**Per-edit pre-edit search log (Edit 1, §2.4):**
- (a) Subject: which error_id (ERR_ACCOUNT_NOT_FOUND vs ERR_NOT_FOUND) a missing path identifier surfaces, per resource kind.
- (b) Enumerated/grepped all get_account_or_404/get_or_404/get_company_or_404/not_found callsites in app.py. Account path-id endpoints get_account(220), get_account_balance(241), archive_account(258) → ERR_ACCOUNT_NOT_FOUND (util.py:118-123). All account body refs also ERR_ACCOUNT_NOT_FOUND. All non-account path-id endpoints (company, period, journal entry/line, bank account, transaction, reconciliation, customer, invoice, payment, vendor, bill, tax rate) → ERR_NOT_FOUND. errors.py confirms both codes are 404.
- (c) Scoped the account clause to "a path accountId" only (not all path ids); explicitly enumerated other resources as ERR_NOT_FOUND; tied to §3.11 to avoid implying a different rule for path vs body account references.

## Step 9: Complete PRD — 2026-06-11T10:10:00.000Z

Produced `workspace/PRD_COMPLETED.md` from PRD_FINALIZED.md. **Line counts:** 325 → 325 (all edits in-paragraph). **Char delta:** +2,441 (54,279 → 56,720).

**Counts:** 10 changes — 5 ambiguity-pins, 5 mismatch-revisions.

**Per-change log:**
- §2.3 Pagination — insert — ambiguity — out-of-range limit/offset clamped (limit→[1,100], offset→≥0), non-integers rejected ERR_INVALID_REQUEST — util.py:60-65
- §2.5 Posted Balances — insert — ambiguity — projected_balance_cents echoes posted figure unless include_drafts=true (literal, case-insensitive) — app.py:243-247
- §2.7 OCC — revise — mismatch — softened absolute "no other endpoint takes a version field" to admit configure-company optional check — app.py:151-153
- §3.1 Company configure — insert — mismatch — configure accepts optional expected_company_version, mismatch → ERR_STALE_VERSION (412), no check when omitted — app.py:151-153
- §3.2 Period post-close — insert — ambiguity — period with no REVENUE/EXPENSE activity creates no closing entry, closing_journal_entry_id stays null — app.py:461-466
- §3.5 Categorization — insert — ambiguity — non-archived counter account in a different company yields ERR_INVALID_CATEGORIZATION_ACCOUNT — app.py:785-787
- §3.6 Void invoice — revise — mismatch — period guard evaluated against company's current_period_id, not issue-date period — app.py:1180-1182
- §3.7 Reverse payment — revise — mismatch — period guard uses company's current period, not invoice's issue-date period — app.py:1301-1303
- §3.8 Bill approval use-tax — insert — ambiguity — "default jurisdiction" rate = any company TaxRate whose window covers bill_date regardless of jurisdiction; most-recently-created wins; 0 if none — app.py:1485-1496
- §3.9 Reconciliation start — revise — mismatch — statement-end-date/opening-balance contiguity are expectations only; not validated/rejected at creation — app.py:874-924
- §3.10 Financial statements — revise — mismatch — as_of_period_id accepted but does not narrow result; figures always roll up all posted entries — app.py:1651-1685

(11 diff hunks but 10 logical changes — §2.7 + §3.1 both trace to configure-company OCC.)

---

## Pipeline complete — 2026-06-11T10:10:00.000Z

All 9 steps finished. Final state: **60/60 tests pass across all 8 stability rounds**. Artifacts: SCAFFOLD.yaml (+ DIFFICULTY/CORNER design), PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ + test_suite/ (60 tests), workspace/implementation/ (Python+Flask, in-memory). Expert difficulty.
