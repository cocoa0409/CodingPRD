# Worklog — task_0283_renters_insurance

## Step 1: Create task directory — 2026-06-10T00:00:00.000Z

Created `tasks/task_0283_renters_insurance/` with `workspace/` subdirectory. Task name and index are pre-assigned/reserved (no re-scan, no auto-increment). Project root: `/Users/uni/Desktop/吉/project/custom_prd_bench`. Difficulty target: Expert (passed only to scaffold-generator in Step 2).

## Step 2: Generate scaffold (Expert) — 2026-06-10T00:00:00.000Z

All three scaffold artifacts are written and validated. (Note: a `worklog.md` and empty `workspace/` were pre-existing in the directory, not created by me.)

Generated a complete Expert-tier scaffold for the Renters Insurance scenario. All three files were written and pass `scaffold_lint.py` with **VERDICT: clean lint** (462 setup/trigger calls checked across §1.8+§1.9; all FK reverse-reachability satisfied).

**Surface counts:**
- **Entities:** 10 (Policyholder, Bundle, Policy, CoverageLine, ScheduledItem, AdditionalInsured, PremiumInvoice, Payment, Claim, ClaimItem)
- **State machines:** 4 (Policy, Claim, PremiumInvoice, Bundle)
- **Calculations:** 4 (claim_settlement, cancellation_refund, premium_calculation, coverage_limit_ledger)
- **Endpoints:** 38 (incl. one `/_clock/set_current_utc` test hook)
- **Errors:** 30
- **Roles:** 3 (Underwriter [opaque], Policyholder [entity_backed], ClaimsAdjuster [opaque]) with segregation-of-duties model
- **Concurrency rules:** 2 (OCC on Policy.version for coverage-line and scheduled-item adds)
- **§1.8:** 18 difficulty instances (all 9 rules × 2); **§1.9:** 37 active corner instances + 2 `excluded_because` stubs; 58 unique instance names across both files.

**Expert-difficulty design choices:**
- **Primary archetype ledger_reconciliation + secondary pricing_engine**, `flat` topology, `cyclic` state-machine shape, `segregation_of_duties` RBAC.
- **Two dual-variant calcs on different domains:** RCV-vs-ACV claim settlement (Claim) and pro-rata-vs-short-rate cancellation refund (Policy).
- **Two combinatorial modes:** premium = base + 4 per-component rounded rate products × tiered territory factor × bundle factor (mode a); claim settlement with pinned round-per-item-then-sum order proven by a 1-cent divergence (mode b).
- **Two non-linear machines on different entities:** Policy lapse↔reinstate cycle; Claim deny→appeal→approve branching fork-join with appeal cap.
- **Two transitive cascades from different triggers:** depth-4 payment→overdue→lapse→coverage/scheduled-item/claim suspension; depth-2 claim-approve→limit-debit→EXHAUSTED.
- **Two compensating invariants over different conserved quantities:** coverage-limit conservation (reverse-approval restores `settled_cents`/`remaining_limit_cents`) and billed-money conservation (payment void restores invoice balance).
- **Two temporal-overlap rules with different interval semantics:** half-open policy-term overlap vs closed-interval-with-shared-boundary loss-of-use displacement overlap.

Files: SCAFFOLD.yaml (697 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1123 lines), SCAFFOLD_CORNER_DESIGN.yaml (1506 lines).

## Step 3: Copy shared files — 2026-06-10T00:00:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0283_renters_insurance/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-10T00:00:00.000Z

Generated `workspace/PRD.md` (254 lines) from the renters-insurance scaffold. The two design YAMLs (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never read, grepped, or referenced.

**Section structure:**
- §1 Introduction; §2 Global Specifications (2.1 RBAC three roles + segregation-of-duties; 2.2 Response Structure; 2.3 Pagination; 2.4 Common Resource Properties; 2.5 Nested Retrieval & Referential Integrity; 2.6 Monetary Precision/Rounding; 2.7 OCC; 2.8 Hierarchical Consistency & Cascades; 2.9 Validation Ordering); §3 Business Logic (8 subsections lifecycle-ordered: policyholders/bundles/discount; premium calc; issuing & billing; payments/voids/billing sweep; reinstatement/cancellation/refunds; coverage limits & settlement ledger; filing claims & items; claim review/settlement/adjudication); §4 Endpoint Definitions (all 38 endpoints); §5 Error Code Catalogue (all 30 error IDs).

**Hard Contract reports:** Contract 1 (Field-Name Coverage) PASS — 61/61 present; Contract 2 (Rule Coverage) PASS — 2 OCC, 21 validations, all state transitions (Policy 6, Claim 7, PremiumInvoice 3, Bundle 2), 4 calculations; Contract 3 (§3 Path Purity) PASS — 0 path/method tokens in §3. All 30 error IDs + 18 state-enum values verbatim; constants embedded as prose (14-day grace, 30-day reinstatement window, 2-member bundle min, max 2 appeals, 5% installment surcharge, 10% short-rate penalty).

## Step 5: Generate unit tests — 2026-06-10T00:00:00.000Z

All 18 difficulty instances are translated, none skipped. Generation is complete.

Generated complete test infrastructure for `task_0283_renters_insurance` from the two design indices only (no freelance discovery from SCAFFOLD.yaml).

**test_helpers/ (Stage 1) — 9 modules emitted:**
- `types.py` — role enum, 12 status enums, 10 entity TypedDicts (all entities `common_fields: true`, all carry id/created_at/updated_at/version)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (37 endpoints incl. `_clock` test hook)
- `api_errors.py` — `ApiErrorId` enum (29 errors) + HTTP status map
- `assertions.py` — per-entity assertions plus the two conservation invariants (coverage-limit and invoice-balance)
- `factories.py` — input-field-only payload factories
- `constants.py` — premium rates, territory factors, grace/window days, MAX_APPEALS, pre-computed STANDARD_ANNUAL_PREMIUM (33350)
- `test_users.py` — opaque Underwriter/ClaimsAdjuster constants + entity-backed `make_policyholder_headers(id)` for ownership-gated calls
- `fixtures.py` — composite setup (active policy, claim-under-review, approved claim, lapsed policy, paid invoice) with correct OCC version threading and Policyholder identity threading
- `__init__.py` — barrel export

**test_suite/ (Stage 2) — conftest.py + 7 test files, 73 test functions.**

**Queue A (Difficulty):** all 18 instances translated, each with ≥2 tests (36+ tests). 0 skipped — every instance passed the PRD-first filter.

**Queue B (Corner):** 39 instances total → 37 non-stub all translated (≥1 test each), 2 `excluded_because:` stubs correctly skipped (`claim_settlement_computed_field_input_ignored`, `policy_lapse_reinstate_cycle_stub`).

**Key adjudication notes (carried into Step 7):**
- Two design-index instances embed `GRACE_DAYS=15` annotation contradicting PRD's "grace period of fourteen days" (§3.4). Asserted outcomes remain true under PRD's 14-day grace, so tests emitted with PRD-correct (14-day) reasoning.
- Corner `bundle_dissolution` instance issues two same-policyholder bundle members on identical overlapping terms (PRD §3.3 term-overlap would reject); test uses a non-overlapping term for member 2.
- `process-billing` lapse-vs-expiry precedence when both hold is PRD-underspecified; cross-entity pay test set inside term (past grace, before expiry) to deterministically lapse.
- No segregation-of-duties test exists in either index, so none was invented.

Verification passed: all helpers/tests import; every PRD citation greps verbatim; every test carries exactly one resolving `Design:` tag; no skip/xfail markers.

## Step 6: Generate implementation — 2026-06-10T00:00:00.000Z

Built a complete Python + Flask Renters Insurance API in `workspace/implementation/`.

**Files created:** `start.sh` (foreground launcher, guards pip on `import flask`, `exec python3 app.py`); `requirements.txt` (flask==3.0.3); `app.py` (1140 lines — all 38 routes, error handlers, state machines); `db.py` (in-memory dict store, UUID/timestamp minting, server clock); `calc.py` (Decimal/ROUND_HALF_UP money math); `store.py` (common-fields minting, versioned touch(), derived-field recompute, bundle membership/discount cascade); `errors.py`, `response.py`, `middleware.py`, `validate.py`, `listing.py`, `ownership.py`, `constants.py`.

**Mapping:** every PRD §4 endpoint implemented; list endpoints sort by created_at asc + paginate per §2.3. State machines: Policy (QUOTED→ACTIVE→LAPSED↔ACTIVE, CANCELLED/EXPIRED with lapse/reinstate cascades); Claim (FILED→UNDER_REVIEW→APPROVED/DENIED→SETTLED, appeal + reverse-approval); PremiumInvoice OPEN/OVERDUE/PAID; Bundle FORMING/ACTIVE/DISSOLVED. Calculations: premium (base + 4 per-component-rounded rate terms × territory × bundle, single final round), claim settlement (per-item rounding then sum, deductible-eligible minus waived, limit cap), settlement ledger waterfall by created_at, OCC on expected_policy_version. Validation precedence follows §2.9.

**Confirmation:** start.sh reads $PORT (default 10000), binds 0.0.0.0, foreground via exec; storage in-memory only (plain dicts, no SQLite/JSON/disk); nothing seeded/preloaded at boot.

**Impl-gen's own preliminary test run (informational; Step 7 owns the authoritative loop):** 70 passed, 3 failed. Subagent flagged all 3 as suspected test-side defects: (1) `test_reinstate_restores_suspended_children` pays 33350 vs PRD-correct 36950 premium for a scheduled-item policy → 3600 balance blocks reinstatement; (2) `test_partial_payment_balance_visible_immediately` mis-unpacks fixture 4-tuple → KeyError 'id'; (3) `test_approve_limit_exceeded_rejected` contradicts the PRD limit-cap settlement formula and its own sibling exhaust test. These are Step 7's to adjudicate under the full STEP 1/2/3 protocol.

## Step 7: Run tests and iterate — 2026-06-10T00:00:00.000Z

All tests pass across a clean 8-round parallel sweep. Final report below.

**Iterations run:** 2 (initial sweep to surface failures, second sweep to confirm fixes). The first sweep was stable: all 7 completed rounds showed the identical 3 failures (round 8's result file was missing due to a boot hiccup, not a distinct failure — confirmed by the clean re-run). The second sweep produced 8/8 clean rounds at 72/72.

**Tests deleted (1):**
- `test_approve_limit_exceeded_rejected` (in `test_suite/test_06_claim_adjudication.py`) — **STEP 1b unique-derivability collapse (unreachable-guard / ERROR-PRECEDENCE silence).** PRD §3.8 pins `settlement_cents = max(0, min(covered_loss, Σremaining_limit) − deductible)`, which is structurally `≤ Σremaining_limit`. The approve-time guard "`settlement_cents` not exceed the sum of `remaining_limit_cents` … else `ERR_LIMIT_EXCEEDED`" can therefore NEVER trip under any PRD-faithful implementation. The test's fixture (95000 RCV claim, 50000 limit) produces a faithful settlement of exactly 50000 = the remaining limit (not exceeding), so a faithful implementer correctly returns success. The test's own comment reveals it relies on an "uncapped settlement" concept absent from the PRD. No fixture configuration could make this fire, so it is not a STEP 2 fixable bug. The PRD-required `ERR_LIMIT_EXCEEDED` check was left intact in the implementation (never weakened to accommodate the test). Scaffold rule that drove generation: `Corner/validations/approve_limit_exceeded_rejected`.

**Fixes applied to `test_suite/` (2 — both faithful-intent tests with test-side bugs, STEP 2):**
- `test_suite/test_03_billing_lapse_reinstate.py` → `test_reinstate_restores_suspended_children`: fixture builds a policy with a scheduled item (premium 36950, not the standard 33350), but the test paid a hardcoded 33350, leaving a 3600 residual that correctly tripped `ERR_LAPSE_BALANCE_OUTSTANDING`. Changed the payment to the invoice's actual `amount_cents` so the overdue balance reaches zero per PRD §3.5.
- `test_suite/test_03_billing_lapse_reinstate.py` → `test_partial_payment_balance_visible_immediately`: mis-unpacked `setup_active_policy()`'s 4-tuple as `(ph, policy, invoice, _payment)` when it returns `(ph, policy, lines, invoice)`, binding `invoice` to the coverage-lines dict and yielding `KeyError 'id'`. Corrected to `(ph, policy, _lines, invoice)`.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none — the implementation was PRD-faithful on all three flagged behaviors (settlement cap, scheduled-item premium, balance recomputation).

Final state: 72 tests, all passing in all 8 parallel rounds.

## Step 8: Finalize PRD — 2026-06-10T00:00:00.000Z

PRD_FINALIZED.md created. **Line counts:** PRD.md = 254 lines; PRD_FINALIZED.md = 254 lines. **%-delta: 0%** (byte-for-byte identical, confirmed via `diff`).

**Changes:** None. All three `<step_7_diff>` items resolve to test-side issues or PRD-already-determined behavior, so no edit traces to a PRD silence or PRD/impl mismatch.

- **Item 1 — `test_approve_limit_exceeded_rejected` (deleted):** No PRD edit. PRD §3.8 already pins both the settlement formula `max(0, min(covered_loss, Σremaining_limit) − deductible)` and the approve-time `ERR_LIMIT_EXCEEDED` guard verbatim (`app.py:842-875`, `app.py:927-949`). The guard is structurally unreachable but intact in impl; PRD matches impl exactly. The deleted test relied on an "uncapped settlement" concept absent from PRD.
- **Item 2 — `test_reinstate_restores_suspended_children` (test fixture fix):** No PRD edit. PRD §3.5 already pins reinstatement precondition `balance_due_cents == 0`; §3.2/§3.3 pin premium + `amount_cents` (`app.py:497-501`, `store.py:120-145`, `calc.py:35-50`). The 36950-vs-33350 discrepancy was the fixture's own payment arithmetic, not PRD ambiguity.
- **Item 3 — `test_partial_payment_balance_visible_immediately` (test unpacking fix):** No PRD edit. PRD §3.3/§3.4 already pin `balance_due_cents = amount_cents − paid_cents` (`app.py:1054-1085`, `store.py:57-64`, `app.py:1110-1124` void parallel). Failure was a pure 4-tuple mis-unpack in the test, no behavioral PRD bearing.

Per the HARD SCOPE rule, PRD_FINALIZED.md is correctly an exact copy of PRD.md (impl had 0 fixes; the deletion + 2 test fixes all trace to test-side bugs / a PRD-already-determined unreachable guard).

## Step 9: Complete PRD — 2026-06-10T00:00:00.000Z

PRD_COMPLETED.md created via full PRD-vs-implementation/ scan. **Source vs completed:** `PRD_FINALIZED.md` (254 lines, 44,534 chars) → `PRD_COMPLETED.md` (254 lines, 47,200 chars). Char delta: **+2,666**. Line count unchanged — every change is an in-paragraph insert/revision (no new sections).

**Counts:** 8 changes total — **5 ambiguity-pins**, **3 mismatch-revisions**.

**Changes:**
- §2.3 Pagination — insert — ambiguity — out-of-range/non-integer `limit`/`offset` rejected with `ERR_INVALID_REQUEST`; `created_at`-ascending tie-broken by server insertion order. (listing.py:27-31,44)
- §2.4 Common Resource Properties — revise — ambiguity — `version` starts at `1` on creation. (store.py:24-25)
- §2.9 Validation Ordering — insert — ambiguity — editability state variants (`ERR_POLICY_NOT_EDITABLE`/`NOT_ACTIVE`/`NOT_BILLABLE`) sit at the state step; on the two OCC-guarded adds order is editability → `ERR_STALE_POLICY_VERSION` → `ERR_DUPLICATE_COVERAGE_TYPE`. (app.py:247-257,297-303)
- §3.3 Issuing — revise — mismatch — term-overlap guard's bundle exemption: a candidate policy with non-null `bundle_id` is not overlap-checked against other members of that same bundle. (app.py:389,397)
- §3.4 Billing Sweep — revise — mismatch — sweep requires ACTIVE policy (else `ERR_INVALID_STATE`); expiry evaluated before lapse; not-yet-expired with no lapsable invoice → `ERR_NOT_YET_EXPIRED` (impl never raises `ERR_NO_OVERDUE_INVOICE`). (app.py:548-582)
- §3.5 Reinstatement — revise — mismatch — fee-satisfying zero-balance invoice must be a separate invoice, not the overdue invoice cleared by the balance precondition. (app.py:506,647-653)
- §3.7 Filing a Claim — revise — ambiguity — `displacement_start`/`displacement_end` optional on LOSS_OF_USE filing (overlap check only when both supplied); only SETTLED LOU claims (plus those missing displacement endpoints) are terminal/exempt from blocking. (app.py:667-699)
- §3.8 Claim Adjudication — insert — ambiguity — "reviewed" for SoD = actor who performed `start-review` (not re-stamped on appeal); cross-entity ACTIVE-policy precondition (`ERR_POLICY_NOT_ACTIVE`) precedes claim's own `ERR_INVALID_STATE` on start-review/approve/appeal/pay, so a lapse-suspended claim surfaces `ERR_POLICY_NOT_ACTIVE`. (app.py:909-916,922,1012-1022)

## Final verification — 2026-06-10T00:00:00.000Z

Orchestrator re-ran the 8-round parallel stability sweep (Step 7's prior result files had been cleared by its per-iteration `rm`). Independently confirmed: **all 8 rounds 72/72 passed, 0 failed, 0 errors.** Result artifacts `results.1.json`–`results.8.json` regenerated in `workspace/implementation/`.
