# Worklog — task_0728_coin_precious_metals

## Step 1: Create Task Directory — 2026-07-04T00:00:00.000Z

Task directory `tasks/task_0728_coin_precious_metals` and its `workspace/` were pre-allocated by the user. Skipped the ./tasks/ scan and auto-numbering per instruction; used the pre-assigned folder directly. No new task directory created. Difficulty: Expert.

## Step 2: Generate Scaffold — 2026-07-04T05:55:00.000Z

Generated INLINE in the orchestrator context after 3 spawned subagents (1 sync + 2 background) all died at the read→write boundary under headless `claude -p` (see memory prd-bench-subagent-death-at-write-boundary). Authored section-by-section via bounded Write/Bash-append calls; each flushes so no single turn composes the whole artifact.

Scenario: Coin & Precious-Metals Dealer. Expert difficulty.
Archetype: pricing_engine + compliance_audit; topology flat; state shape branching+cyclic; role_model peer_roles.

SCAFFOLD.yaml:
- 14 entities: SpotRate, Product, InventoryLot, Customer, IRAAccount, SellOrder, BuyOrder, Layaway, Consignment, HedgePosition, Settlement, Appraiser, AppraisalAppointment, AuctionSession.
- 8 state machines (Layaway cyclic ACTIVE->ACTIVE deposit loop; Consignment branching LISTED->{SOLD,RETURNED}).
- 2 concurrency_rules (OCC): layaway-deposit-stale-version, consignment-record-sale-stale-version.
- 7 calculations: unit_melt_value, unit_sell_price (numismatic premium-then-spread), unit_buy_payout (1099-B reportable >= $10,000.00 = 1000000 cents), sell_cogs_provisional (weighted-avg) vs sell_cogs_final (FIFO) dual-variant, hedge_pnl (unrealized/realized dual-variant), settlement_breakdown (round-then-sum pinned).
- 18 validations (priority-ordered), 18 errors, 4 roles (Trader/SalesAgent/ComplianceOfficer opaque; Customer entity_backed).

SCAFFOLD_DIFFICULTY_DESIGN.yaml: 9 rules × 2 instances = 18. All numeric asserts precomputed by code (e.g., provisional_cogs 660000 vs final 620000; numismatic sell 225750; settlement round-then-sum dealer_revenue 20000 vs sum-then-round 20001 at hammer 100003; reportable boundary total 1000000 exact).

SCAFFOLD_CORNER_DESIGN.yaml: 29 instances across entities/endpoints/state_machines/validations/errors/rbac/cross_cutting_complexity_layers/consistency_model.

Verification:
- scaffold_lint.py VERDICT: clean lint — 205 calls (18 diff + 29 corner instances) all conform to §1.5; all 14 FKs have reverse-reachability GETs.
- No forbidden concurrency vocabulary in SCAFFOLD.yaml.
- 47 instance names unique across both design files.

Open item for Step 5/7: priority_pair instance 2 (reserve_business_constraint_beats_stale_version) asserts ERR_RESERVE_NOT_MET wins over ERR_STALE_VERSION on record-sale — depends on implementation checking reserve (priority 11) before OCC (priority 17). Note: 55 endpoints exceeds the Expert 20–32 band, inflated by mandatory reverse-reachability GET/list endpoints across 14 flat entities.

## Step 3: Copy Shared Files — 2026-07-04T05:56:00.000Z

Copied ./INSTRUCTION.md → tasks/task_0728_coin_precious_metals/workspace/INSTRUCTION.md (bash, no subagent).

## Step 4: Generate PRD — 2026-07-04T06:02:00.000Z

Subagent (SYNCHRONOUS, run_in_background:false — succeeded on first try; synchronous mode lets the harness drive retry/timeout, unlike the Step-2 background deaths). Wrote workspace/PRD.md — 266 lines.

Sections: §1 Introduction; §2 Global Specs (RBAC/identity, verbatim envelope, pagination, versioning, precision/rounding, OCC, validation precedence, cascade semantics, referential integrity); §3 Business Logic (10 subsections: pricing, inventory/FIFO COGS, selling+IRA, buying+1099-B, layaway, consignment sale/return fork, settlement split, appraisals/auctions, hedging, customer balances); §4 endpoint table (all 56 endpoints); §5 error catalogue (all 18).

Subagent's self-reported hard-contract checks: Field-Name Coverage PASS, Rule Coverage PASS, §3 Path Purity PASS.

Scaffold ambiguities the subagent resolved: BuyOrder settle "create or augment" lot → "creates (or augments)"; sell_cogs_final tie-break translated literally; IRA ira_eligible check at placement only (priority 9) vs ira_account active check at placement+settle (priority 8) made explicit.

Orchestrator verification: no test-answer numbers (660000/620000/225750/100003/20001/640000) leaked; no design-file artifacts (test_recipe/distinguishing_aspect) present; §3 path-purity spot check clean.

## Step 6: Generate Implementation — 2026-07-04T07:08:00.000Z

Subagent (SYNCHRONOUS). Built Python+Flask impl in workspace/implementation/. Ran BEFORE Step 5 (sequential-synchronous instead of concurrent) to preserve the isolation invariant — test_suite/ provably absent when impl-gen ran — while avoiding background-subagent stalls.

Files: start.sh (reads $PORT default 10000, binds 0.0.0.0, foreground exec python3 app.py, guarded pip install), requirements.txt (flask==3.0.3), core.py (in-memory dict store, no seeding, envelope, auth, round-half-up via Decimal, calculations, pagination, validators), app.py (all routes, error handlers, state machines, cascades). 54 endpoints implemented.

Subagent self-verification: booted a live server, 44 end-to-end assertions all pass.

PRD ambiguities resolved by subagent: sell-order placement checks account-active(8) before product-eligible(9); settle checks ERR_INSUFFICIENT_INVENTORY before ERR_IRA_NOT_ACTIVE; layaway deposit checks version(412) before overpayment(422); reportable-approval stored as internal _reportable_approved (stripped from responses); SKU/metal uniqueness → ERR_INVALID_REQUEST(400).

Orchestrator verification: files present; PORT=18728 boot test returned proper 201 envelope on POST /api/spot-rates.

## Step 5: Generate Unit Tests — 2026-07-04T07:34:00.000Z

Subagent (SYNCHRONOUS). Generated test_helpers/ (9 files) + test_suite/ (conftest + 7 test files, 62 test functions). All authored against PRD + design indices only (did not read implementation/).

Coverage vs design indices:
- Difficulty (queue A): 17/18 realized (34 tests). SKIPPED reserve_business_constraint_beats_stale_version_business_constraint — not uniquely derivable (PRD §3.6 lists version-match before reserve, so a faithful reader could return ERR_STALE_VERSION before ERR_RESERVE_NOT_MET; scaffold's priority-number winner not PRD-fixed). [This confirms the Step-2 open item.]
- Corner (queue B): 28/29 realized (28 tests). SKIPPED approve_ira_account_without_id_on_file_returns_invalid_state — not uniquely derivable (PRD scopes ERR_INVALID_STATE to wrong starting state; no error_id named for the id-on-file precondition).
- Two difficulty recipes (state-beats-safety, IRA-active-at-settle) had scaffold setups contradicting PRD placement guards; subagent built PRD-reachable equivalents asserting the same PRD-derivable outcome.

Every test docstring carries a verbatim PRD citation + exactly one Design: tag.

Orchestrator verification: 62 def test_ functions, 62 Design: tags, all test files parse (ast).

## Step 7: Run Tests and Iterate — 2026-07-04T07:52:00.000Z

Long-lived diagnostic subagent (SYNCHRONOUS). Ran ONE stability sweep as 2 waves of 4 concurrent rounds (per host-self-saturation guidance). Result: ALL 8 rounds passed 62/62, failed=0, errors=0.

- Iterations run: 1 (single 2-wave sweep).
- Tests deleted: none — no PRD-silence or non-unique-derivability case surfaced (nothing failed).
- Fixes applied to test_helpers/: none.
- Fixes applied to implementation/: none.
- Final: 62/62 in all 8 rounds.

Orchestrator independent verification: parsed all 8 results.*.json — each passed=62 total=62 failed=0 errors=0. ALL CLEAN confirmed.

=> Step 8 SKIP CONDITION met (0 deletions, 0 test_suite fixes, 0 test_helpers fixes, 0 implementation fixes). Step 8 skipped per pipeline spec. Step 9 always runs.

## Step 8: Finalize PRD — 2026-07-04T07:53:00.000Z

SKIPPED. Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite fixes, 0 test_helpers fixes, 0 implementation fixes → PRD.md already determined every behavior the implementation exhibits. PRD_FINALIZED.md not produced (correctly absent).

## Step 9: Complete PRD — 2026-07-04T08:02:00.000Z

Subagent (SYNCHRONOUS). Full PRD-vs-implementation/ scan. Started from PRD.md (Step 8 skipped). Wrote workspace/PRD_COMPLETED.md (266 lines, +3163 chars, all in-paragraph inserts/revisions; no new sections).

12 ambiguity-pins + 2 mismatch-revisions = 14 changes, each traced to impl file:line. Highlights:
- record-sale precedence pinned: state → stale-version(412) → reserve(422) [confirms the non-derivable ordering the test-gen skipped].
- IRA approve with id_document_on_file false → ERR_ID_REQUIRED_FOR_REPORTABLE(422).
- settle: insufficient-inventory before IRA-active.
- buy settle: "creates (or augments)" corrected to "always creates a brand-new lot".
- reportable-approval flag internal/not surfaced; approve bumps version, no guard.
- duplicate metal spot-rate / duplicate sku → ERR_INVALID_REQUEST(400).
- missing spot rate for priced/hedged metal → ERR_INVALID_REQUEST(400).
- weight_troy_oz 4-decimal claim softened (impl only checks >0).
- layaway deposit OCC-before-overpayment already uniquely pinned — no change needed.

Orchestrator verification: PRD_COMPLETED.md present; PRD_FINALIZED.md absent (correct); all 8 results rounds 62/62.

## PIPELINE COMPLETE — 2026-07-04T08:02:00.000Z
Final: 62/62 tests pass across all 8 stability rounds. All artifacts present:
SCAFFOLD.yaml (1561), SCAFFOLD_DIFFICULTY_DESIGN.yaml (807, 18 instances), SCAFFOLD_CORNER_DESIGN.yaml (814, 29 instances), PRD.md (266), PRD_COMPLETED.md (266), implementation (app.py 997 + core.py 391 + start.sh), test_suite (7 files, 62 fns), test_helpers (9 files).
