# Worklog — task_1122_bankruptcy_trustee_claims_administration

## Step 1: Create Task Directory — 2026-08-10T19:45:00.000Z

Task directory pre-assigned by pipeline launcher: `tasks/task_1122_bankruptcy_trustee_claims_administration` with `workspace/` subdirectory. Directory and workspace verified present and empty. Step 1 treated as done per headless-run instructions; auto-index scan skipped.

## Step 2: Generate Scaffold — 2026-08-10T20:15:00.000Z

Scaffold generation complete. Summary:

**Artifacts written**
- `/home/ubuntu/github/CodingPRD/tasks/task_1122_bankruptcy_trustee_claims_administration/SCAFFOLD.yaml` (§1.0–§1.7; no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1122_bankruptcy_trustee_claims_administration/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1122_bankruptcy_trustee_claims_administration/SCAFFOLD_CORNER_DESIGN.yaml` (single top-level key `scaffold_corner_design`)

**Surface metrics**
- Entities: 13 (Case, Creditor, Claim, ClaimObjection, Asset, AvoidanceAction, RecoveryDeposit, AuctionSale, DistributionPlan, PlanClassAllocation, Dividend, FeeApplication, FinalReport)
- Endpoints: 77 (including `/_clock/set_current_utc` with the mandatory 2026-05-01T00:00:00Z default)
- State machines: 9 (Case posture machine with 8 states; cyclic Claim review loop; ClaimObjection; branching Asset; AuctionSale with half-open objection window; AvoidanceAction with judgment/rescind compensation; DistributionPlan; FeeApplication; FinalReport)
- Concurrency rules: 2 (OCC on `Case.version` for plan confirm and fee filing)
- Calculations: 7 (§326 tiered commission with DISBURSED/PROPOSED variants; waterfall allocation with secured cap + deficiency spill + floor/remainder-to-last; bar-date late flag; lookback windows; sale minimum price; estate-cash ledger identity; final report totals)
- Errors: 30; Validations: 13 ordered priorities; Roles: 4 (Trustee/Clerk/Court opaque, Creditor entity-backed; segregation-of-duties model)

**§1.8 difficulty design**: 18 instances, 2 per rule, all 9 rules with the required differentiation (dual-variant: FeeApplication vs Claim domains; combinatorial: mode (a) tiered commission + mode (b) rounding-order waterfall; non-linear machines on Claim vs AvoidanceAction; cascades from objection-settle (depth 3) vs sale-consummate (depth 2); priority conflicts state×temporal and safety×fiscal; boundaries on price-cents vs calendar-day edges; cross-entity gates on Plan→Case and Sale→Asset; temporal-overlap with half-open window vs set-membership exclusion; compensating invariants on cash ledger vs register total). All numeric asserts pre-computed as literals (e.g., 275000/625000 commission divergence, 5325000 at the $1M tier cap, 33333/33333/33334 pro-rata remainder).

**§1.9 corner design**: 40 instances total — 37 active + 3 `excluded_because` stubs (`commission_constants_applied_exactly_at_tier_caps`, `late_flag_precision`, `derived_field_reconciliation_on_recovery_void`), spanning all nine taxonomy sections (entities 9, state_machines 6, calculations 4, validations 7, endpoints 3, errors 3, rbac 3, cross_cutting_layers 4, consistency_model 1).

**Lint**: `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (77 endpoints, 13 entities, 18+37 instances, 640 calls scanned; zero violations). Fixes applied during iteration: flow-style `grounds` lists with nested brackets converted to block style, all path-template placeholders normalized to `{id}`, 8 reverse-reachability GET endpoints added (e.g., `GET /trustee/claims`, `/trustee/claims/{id}/dividends|objections|encumbered_assets`, `/trustee/creditors/{id}/avoidance_actions`, `/trustee/assets/{id}/sales`, `/trustee/avoidance_actions/{id}/recovery_deposits`, `/trustee/cases/{id}/allocations`), `FinalReport` GET switched to `FinalReport[]` per the 0-or-1 array convention, `ERR_INVALID_REQUEST`/`ERR_FINAL_REPORT_NOT_READY` wired into validations and the FinalReport machine, and the dual-variant commission instance rebuilt with two claims (4,000,000 + 2,000,000) so DISBURSED (275,000) and PROPOSED (625,000) genuinely diverge.

## Step 3: Copy Shared Files — 2026-08-10T20:17:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1122_bankruptcy_trustee_claims_administration/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-10T20:35:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1122_bankruptcy_trustee_claims_administration/workspace/PRD.md` — 371 lines, ending at §5 with no audit footer. Neither forbidden design file was opened.

## Section outline

- **§1 Introduction** — 2 paragraphs (business context of chapter 7 liquidation; segregation-of-duties + exact-reconciliation commitments)
- **§2 Global Specifications** (11 subsections): 2.1 RBAC & identity semantics · 2.2 API Response Structure (verbatim block, byte-identical, confirmed by containment check) · 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending) · 2.4 The Logical Clock (default 2026-05-01T00:00:00Z, Court-only `to_iso8601` advance) · 2.5 Common Resource Properties (incl. FinalReport exception: only `id`/`created_at`, no `updated_at`/`version`) · 2.6 Case Posture & Hierarchical Consistency · 2.7 Estate Ledger & Fiscal Sufficiency · 2.8 Monetary Precision (integer cents, floor semantics) · 2.9 OCC · 2.10 Nested Resource Retrieval · 2.11 Validation Ordering (all 13 priority tiers in ascending order)
- **§3 Business Logic** (8 subsections, chronological lifecycle): 3.1 Case Intake/No-Asset Exit/Conversion · 3.2 Creditor Registration/Bar Date/Claims Intake · 3.3 Claim Review/Objection/Reconsideration Cycle · 3.4 Asset Investigation/Auction Sales · 3.5 Preference & Fraudulent-Transfer Recovery · 3.6 Distribution Plan & Waterfall · 3.7 Trustee Compensation/Fees · 3.8 Final Report & Closing
- **§4 Endpoint table** — 4 columns, 77/77 rows match scaffold exactly (no extras/missing)
- **§5 Error catalogue** — 2 columns, all 36 error IDs with HTTP statuses

## Scaffold-to-prose rendering

- **Entities**: all 13 rendered narratively; all 72 field names in backticks (mechanical diff: 0 missing), incl. defaults (`objection_window_days` 30, `insider`/`exempt` false), nullables, computed vs input sources, and the `reclassified_from_claim_id` self-reference
- **State machines**: all 9 machines, every transition rendered as state-pair prose (`OPEN` → `ASSET_INVESTIGATION`, etc.) with preconditions paired to error IDs and all side effects (asset sweep on bar-date, conversion cascade, rescind compensating entry, plan auto-transitions, dividend materialization at confirm)
- **Calculations**: all 7 in precise prose passing the reconstruction test — strictly-greater late determination with the exact-boundary-is-timely rule; 90/365/730-day lookbacks with both boundary semantics; minimum-price as greater-of-two-floors with half-value truncated down and equality acceptable; §326 tiers (25%/10%/5%/3% at $5,000/$50,000/$1,000,000 breakpoints, per-tier integer-division floor then sum, DISBURSED vs PROPOSED bases); 4-step waterfall with secured cap/deficiency spill and remainder-to-last pinned by `claim_number` ascending never `id`; estate-cash four-term reconciliation; final-report totals with the unclaimed==cash invariant
- **Validations**: all 14 rules, priority ordering 1–13 stated explicitly in §2.11 (body well-formedness last per scaffold), each tier's `applies_to` scope enumerated
- **Endpoints**: all 77 in §4 with correct roles; all 48 request/query identifiers in backticks (0 missing); side effects woven into §3 narratives
- **Errors**: all 36 IDs present in §2/§3 prose plus §5 table
- **Roles**: all 4 with identity semantics — Trustee/Clerk/Court opaque (trustee binding via `trustee_user_id` match, `ERR_NOT_ASSIGNED_TRUSTEE`), Creditor entity-backed (`X-User-ID` = acting `Creditor.id`, ownership via `creditor_id`)

## Zero-Silence / Hard-Contract audit

- **Contract 1 (Field-Name Coverage)**: PASS — 72 entity fields + 48 endpoint identifiers, 0 missing (script-verified, two passes; one fix applied for `CANCELLED` state enum)
- **Contract 2 (Rule Coverage)**: PASS — 14/14 validations with priority, 2/2 OCC rules (endpoint + `expected_case_version` + `ERR_STALE_CASE_VERSION`/412, stale-version framing only), 41/41 state values, all enum members (grounds, outcomes, applicant roles, bases, action types, priority classes), all transitions/calculations/side-effects expressed, sibling branches symmetric (sustain/overrule/settle/withdraw bullets; both withdrawal branches; both abandon branches; both cancel branches; both commission bases)
- **Contract 3 (§3 Path Purity)**: PASS — 482 backticked tokens scanned, 0 paths, 0 bare HTTP methods, 0 method+path combos; no operator pseudocode tokens; no fuzzy-word hits
- §2.2 emitted verbatim from the canonical source file (containment check true); no scaffold rule omitted or reinterpreted

## Step 5: Generate Unit Tests — 2026-08-10T21:00:00.000Z

Generation complete. Summary:

## Files written

**`test_helpers/`** (Stage 1, under `/home/ubuntu/github/CodingPRD/tasks/task_1122_bankruptcy_trustee_claims_administration/test_helpers/`):
- `types.py` — 18 enums (Case/Claim/Objection/Asset/Sale/Plan/Dividend/Fee/Report statuses, PriorityClass, ActionType, etc.) + 13 TypedDicts; `FinalReport` correctly carries only `id`/`created_at` (no `updated_at`/`version`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (all 60+ PRD §4 endpoints, incl. the test-driving clock)
- `api_errors.py` — all 36 error IDs with §5 HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + ledger non-negativity invariant
- `factories.py`, `constants.py` (§326 tier caps, 90/365/730-day lookbacks, 0.50 sale floor, default clock), `test_users.py` (opaque Trustee/Clerk/Court constants + `make_creditor_headers` for the entity-backed Creditor role)
- `fixtures.py` — composite setup tiers: `setup_case_in_claims_administration` → `_in_liquidation` → `_with_consummated_sale` → `_in_distribution` → `setup_confirmed_plan`, plus avoidance-action walkers (`create_demanded_action`, `create_judgment_action`), OCC-aware `confirm_plan`/`file_fee_application`, and per-claim dividend lookup
- `__init__.py` barrel export

**`test_suite/`** — `conftest.py` + 9 files: `test_01_case_intake_and_posture.py`, `test_02_claims_register.py`, `test_03_claim_review_objection_cycle.py`, `test_04_assets_and_sales.py`, `test_05_avoidance_actions.py`, `test_06_distribution_waterfall.py`, `test_07_fee_applications.py`, `test_08_final_report.py`, `test_09_security_and_validation.py`.

## Coverage
- **Total: 72 tests** (pytest-collected cleanly)
- **Queue A: 36 tests / 18 instances** — every §1.8 instance has exactly 2 tests
- **Queue B: 36 tests / 37 active instances** — every non-stub §1.9 instance has 1 test except one skip
- The 3 `excluded_because` stubs (`commission_constants_applied_exactly_at_tier_caps`, `late_flag_precision`, `derived_field_reconciliation_on_recovery_void`) were not translated; their cross-referenced difficulty instances resolve and are covered.

## Skipped instances
- `Corner/entities/asset_realized_proceeds_input_ignored` — the PRD never states the pre-sale value of `realized_proceeds_cents` nor that unknown request fields are ignored, so "client input ignored, stays 0" is not uniquely derivable (two-reader failure).

## PRD-fidelity adjustments made during translation
- Trustee fee filings use `requested_amount_cents` equal to the §326 DISBURSED-basis commission (PRD §3.7 requires this equality) instead of the recipe's 999,999,999.
- `waterfall_secured_cap_and_deficiency_spill` recipe was internally inconsistent (hammer 400,000 − costs 100,000 = 300,000 cash, but asserts assume 400,000); added a 100,000 judgment recovery so realized proceeds stay 300,000 while cash is 400,000, preserving all pre-computed literals (300,000 / 100,000 / 40,000 / 60,000).
- `final_report_totals_reconcile_to_ledger` reordered to pay the counsel fee before plan completion, so the DRAFT report is created after all ledger activity — the asserted totals (400,000/350,000/50,000/0) hold under either snapshot or live report semantics.
- `version == 1` initial-value assertions were reduced to integer presence + exact +1 increments per mutation (PRD §2.5/§3.x pin the increment, not the origin).
- `invalid_demand_amount_rejected` accepts the error at either the registration or the demand transition (PRD names the band and error; the site is ambiguous), asserting `ERR_INVALID_DEMAND_AMOUNT` either way without weakening.

## Tag confirmation
Every one of the 72 test docstrings ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line, each resolving to a real instance in the source YAMLs (verified programmatically), and every PRD citation survives a literal whitespace-normalized grep of `workspace/PRD.md` (0 failures).

## Step 6: Generate Implementation — 2026-08-10T21:05:00.000Z

Implementation complete. Summary:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1122_bankruptcy_trustee_claims_administration/workspace/implementation/`)

- `start.sh` — guarded pip install (no-op once Flask importable), `exec python3 app.py`, reads `$PORT` (default 10000), binds 0.0.0.0, foreground
- `requirements.txt`, `app.py` (entry point, blueprint registration, envelope-wrapped error handlers)
- Foundation: `db.py` (in-memory dicts only, zero seeding), `logical_clock.py` (default 2026-05-01T00:00:00Z, never wall-clock), `errors.py` (full 35-error catalog), `response.py` (meta/response_type/data envelope + limit/offset/total_count/has_more pagination), `middleware.py` (X-User-ID / X-User-Role auth, role gating), `util.py` (ISO-8601 3-fractional-digit serialization, body validators)
- Routes: `routes_clock.py`, `routes_cases.py`, `routes_creditors.py`, `routes_claims.py`, `routes_objections.py`, `routes_assets.py`, `routes_sales.py`, `routes_avoidance.py`, `routes_plans.py` (plans + allocations + dividends), `routes_fees.py`, `routes_reports.py`
- Services: `services_common.py` (entity lifecycle, serializers, guards), `services_calc.py` (calculations)

## Route count
77 (method, path) pairs — verified programmatically to exactly match SCAFFOLD.yaml §1.5 (0 missing, 0 extra).

## State machines implemented
All 9: Case (OPEN→…→CLOSED / CONVERTED_DISMISSED with full cascade), Claim (incl. the ALLOWED→UNDER_REVIEW→OBJECTED→ALLOWED reconsideration cycle), ClaimObjection (sustain/overrule/settle ALLOW|DISALLOW|PARTIAL/withdraw), Asset, AuctionSale (objection-window gated consummate/cancel), AvoidanceAction (incl. judgment rescission with compensating ledger entry), DistributionPlan (CONFIRMED→EXECUTING→FULLY_DISTRIBUTED auto-transitions, vacate), FeeApplication, FinalReport (auto-created DRAFT on FINAL_REPORT posture; approve closes case and remits unclaimed funds).

## Calculations implemented
- §326(a) tiered commission (25/10/5/3%, per-tier integer floor then sum), DISBURSED vs PROPOSED basis variants; trustee filings must equal the DISBURSED-basis commission
- Distribution waterfall: reserve snapshot, pool = cash − reserve − approved-unpaid fees, class cascade SECURED→…→GENERAL_UNSECURED, secured carve-out capped at realized proceeds with deficiency spill into GENERAL_UNSECURED, per-class pro-rata with floor + remainder-to-last (claim_number ASC)
- Lookback windows (90/365/730 days, whole-day granularity, boundary-inclusive lower/exclusive petition date), late-claim strictly-greater at second granularity, sale minimum-price floor `max(costs, scheduled//2)`, estate-cash reconciliation invariant (never negative), final-report totals
- OCC `expected_case_version` (412 ERR_STALE_CASE_VERSION) on plan confirm and fee filing; case version bumps once per mutating request per the endpoint side-effect table

## Verification
- `py_compile` + `pyflakes` clean on all 22 files
- `bash start.sh` boots cleanly on a fresh process; two end-to-end smoke suites passed: full lifecycle (intake → bar date → claims/objections → liquidation → sale → judgment recovery → plan confirm → dividends → FINAL_REPORT → fee pay → report file/approve → CLOSED) plus deep checks (pro-rata remainder-to-last amounts 24999/25001, secured cap + deficiency spill, claim-swap creation, vacate/void unclaimed funds, no-asset exit, convert/dismiss cascade, register renumbering by received_at, error-id spot checks)
- Fresh-reboot isolation confirmed: empty store and default logical clock on every boot

## Step 6.5 (orchestrator verification): Route Parity Check — 2026-08-10T21:06:00.000Z

Pre-sweep verification: extracted (method, path) pairs from SCAFFOLD.yaml §1.5 (77 endpoints) and from Flask decorators in `workspace/implementation/*.py` (77 routes). Normalized path-template syntax (`<conv:id>` vs `{id}`). Result: **77 scaffold == 77 impl, 0 missing, 0 extra**.

## Step 7: Run Tests and Iterate — 2026-08-10T21:40:00.000Z

Two consecutive clean 8-round sweeps (16/16 rounds, 576/576 test executions). The task is done.

## Summary

**Iterations run:** 4 sweeps total — initial (65/72 × 8 rounds, 7 deterministic failures), post-test-fixes (assertion failures gone; 7 infrastructure boot-timeout flakes), post-start.sh-fix (72/72 × 8), confirmation (72/72 × 8).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` — `create_case()` gained `debtor_name`/`district` passthrough to `create_case_payload` (PRD §3.1 intake fields). Fixed `TypeError` in `test_claim_secured_with_foreign_case_asset_rejected`.

**Fixes applied to `test_suite/`:**
- `test_04_assets_and_sales.py::test_hammer_one_cent_below_greater_floor_rejected` — setup violated PRD §3.4 ("net_proceeds_cents … never permitted to be negative"): hammer 409,999 with costs 410,000 is uncreatable, so the approve-step gate was unreachable. Restructured to costs 300,000 / scheduled 800,000 (greater floor = half-scheduled 400,000), hammer 399,999 — one cent below with net 99,999 ≥ 0. Same asserted rule (`ERR_BELOW_MINIMUM_PRICE` at approve).
- `test_04_assets_and_sales.py::test_mark_for_sale_exempt_asset_rejected` — setup used `asset=False` then `begin_investigation`, which PRD §3.1 rejects with `ERR_NO_ASSETS_SCHEDULED`. Now creates the exempt asset before `begin_investigation`; the bar-date sweep (PRD §3.4) supplies the `UNDER_INVESTIGATION` from-state so only the exempt guard can fire.
- `test_03_claim_review_objection_cycle.py::test_second_objection_rejected_while_one_pending` and `::test_objection_after_sustain_rejected_from_terminal_claim` (mid-test assertion) — asserted `ERR_OBJECTION_ALREADY_PENDING` while the claim was `OBJECTED`; PRD §2.11 ("the earliest failing tier determines the error surfaced"; tier 5 from-state validity before tier 9 uniqueness) uniquely determines `ERR_INVALID_STATE`. Assertions corrected with the §2.11 citation added.
- `test_04_assets_and_sales.py::test_second_sale_while_one_pending_rejected` — same precedence collapse: with a sale pending the asset is `IN_AUCTION`, and §3.4 requires `MARKED_FOR_SALE`; §2.11 tier 5 pre-empts tier 9. Assertion corrected to `ERR_INVALID_STATE`. (Note: `ERR_OBJECTION_ALREADY_PENDING`/`ERR_SALE_ALREADY_PENDING` are shadowed by the state guard in every reachable scenario under the PRD's state machines — a scaffold design flaw, not fixable test-side without violating §2.11.)
- `test_07_fee_applications.py::test_proposed_basis_uses_confirmed_plan_allocations` — unique-derivability collapse: PRD §3.7's "the case's `CONFIRMED` plan" does not determine whether an `EXECUTING` plan counts (posting a dividend auto-moves the plan per §3.6), and the strict-status reading (implementation) vs pending-plan reading diverge. Per STEP 1c, kept the covered assertion by filing while the plan is still `CONFIRMED` (no dividend posted); `requested_amount_cents` pinned to the DISBURSED-basis commission (0) per §3.7; the 625,000 PROPOSED-basis assertion retained.

**Fixes applied to `workspace/implementation/`:**
- `start.sh` — replaced the per-boot `python3 -c "import flask"` probe (a full interpreter spawn on each of 576 server restarts under 8× concurrency) with a pure-bash filesystem check across site-packages roots. Boot ~0.26s; eliminated the runner's 15s restart-poll timeouts. No application logic touched — no checks weakened, no endpoints/fields added, storage remains in-memory with zero seeding.

Orchestrator verification of final sweep artifacts: all 8 `results.{1..8}.json` files present on disk, each reporting `passed: 72, total: 72, failed: 0`.

## Step 8: Finalize PRD — 2026-08-10T21:50:00.000Z

`PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1122_bankruptcy_trustee_claims_administration/workspace/PRD_FINALIZED.md`.

## Line counts / delta

- `PRD.md`: 371 lines; `PRD_FINALIZED.md`: 371 lines; 0% line-count delta (2 lines revised in place, no insertions or deletions of lines).

## Changes (one bullet per edit)

- §3.4 — revise — the "never permitted to be negative" parenthetical now pins the enforcement point and error: a sale proposal whose `sale_costs_cents` exceed its `hammer_price_cents` is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — `implementation/routes_sales.py:60-62`.
- §3.7 — revise — the `PROPOSED` commission basis now pins the strict-status reading: only a plan in `CONFIRMED` status at the filing instant contributes; once the first dividend posting moves the plan to `EXECUTING` its allocations stop counting, and with no `CONFIRMED` plan the basis is zero — `implementation/services_calc.py:53-61` (sole caller `implementation/routes_fees.py:59`).

## Step 7 items that required NO edit (with verification)

- `fixtures.py` `debtor_name`/`district` passthrough — pure fixture bug; PRD §3.1 already pins both as required intake fields, and the impl requires them (`routes_cases.py:37,39`).
- `test_mark_for_sale_exempt_asset_rejected` — test setup bug; PRD §3.1 already pins `ERR_NO_ASSETS_SCHEDULED`, §3.2 the bar-date sweep, §3.4 the exempt guard.
- `ERR_OBJECTION_ALREADY_PENDING` / `ERR_SALE_ALREADY_PENDING` shadowing — PRD already uniquely determines this: §2.11 orders tier 5 (`ERR_INVALID_STATE`) before tier 9 (uniqueness), and §3.3/§3.4 pin the state moves (objection creation moves claim to `OBJECTED` at `routes_claims.py:270`; sale proposal moves asset to `IN_AUCTION` at `routes_sales.py:77`) that make the pending guards unreachable. Confirmed the impl evaluates the from-state guard first at `routes_claims.py:246-251` and `routes_sales.py:48-54`. Prose kept verbatim per "where PRD already determines behavior".
- `start.sh` — launcher infrastructure only (bash filesystem probe replacing a Python import probe); no API surface, storage, or endpoint behavior touched. PRD governs API behavior, so no edit.

## Per-edit pre-edit search log

**Edit 1 (§3.4 negative net proceeds):**
- (a) Subject: `net_proceeds_cents` computation and where/how its non-negativity is enforced.
- (b) Paths enumerated (grep `net_proceeds_cents` across impl): `routes_sales.py:56-62` (creation-time `net < 0` → `ERR_INVALID_REQUEST` 400, evaluated after the state/uniqueness guards, consistent with §2.11 tier 13), `routes_sales.py:70` (stored), `routes_sales.py:112-115` (approve gate uses `sale_costs_cents` and `scheduled_value_cents // 2`, not net — and any created sale already has hammer ≥ costs, so the greater-floor logic and "exactly equal is acceptable" sentence remain accurate), `routes_sales.py:139-141` (consummate credits net; sets `realized_proceeds_cents`), `services_calc.py:186` (final-report receipts), `services_common.py:199` (serialization).
- (c) Adjustment: worded as a rejection at proposal naming `ERR_INVALID_REQUEST` (HTTP 400) — no universal claim about other endpoints; consistent with every enumerated path since creation is the only place a negative net could arise.

**Edit 2 (§3.7 PROPOSED basis):**
- (a) Subject: which plan(s) contribute to the `PROPOSED` commission basis.
- (b) Paths enumerated (grep `proposed_basis` / `computed_commission` / plan status transitions): `services_calc.py:53-61` (sums `allocated_cents` over plans with status exactly `CONFIRMED`; zero when none), `routes_fees.py:59` (sole caller, feeds only `computed_commission_cents`), `routes_fees.py:61-65` (`requested_amount_cents` equality check always uses the DISBURSED basis — unaffected, PRD already pins), `services_common.py:291` (serialization), `routes_plans.py:92-94` (`ERR_PLAN_ALREADY_ACTIVE` guarantees at most one `CONFIRMED`/`EXECUTING` plan, so the PRD's singular "the case's `CONFIRMED` plan" stays accurate), `routes_plans.py:206-207` (first dividend posting moves `CONFIRMED` → `EXECUTING`), `routes_plans.py:118-119` (vacate only from `CONFIRMED`, covered by the "no `CONFIRMED` plan → basis zero" clause).
- (c) Adjustment: appended a strict-status sentence rather than altering the existing main clause, and scoped it to "at the filing instant"; covers `EXECUTING`, `VACATED`, and no-plan cases without redefining any other basis consumer.

## Step 9: Complete PRD — 2026-08-10T22:05:00.000Z

Produced `/home/ubuntu/github/CodingPRD/tasks/task_1122_bankruptcy_trustee_claims_administration/workspace/PRD_COMPLETED.md`.

**Source vs output:** PRD_FINALIZED.md 371 lines / 55,230 chars → PRD_COMPLETED.md 371 lines / 60,201 chars (char-delta +4,971; line count unchanged — all edits are in-paragraph, no new sections; §4 endpoint table and §5 error catalogue untouched).

**Counts:** 25 total changes — 21 ambiguity-pins, 4 mismatch-revisions.

**Change log** (`{PRD section} — {insert|revise} — {ambiguity|mismatch} — {what} — {impl ref}`):

- §2.1 — insert — ambiguity — blank/whitespace `X-User-ID` and any `X-User-Role` outside the four roles are malformed → `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, never 403 — middleware.py:16-24
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` (1–100) and non-integer/negative `offset` → `ERR_INVALID_REQUEST` (400) — response.py:50-72
- §2.3 — insert — ambiguity — `created_at` ties in list ordering break by server insertion order (`_seq`) — services_common.py:315-317
- §2.4 — insert — ambiguity — logical clock also stamps all server-recorded timestamps (`created_at`, `updated_at`, `resolved_at`, `proposed_at`, `sale_approved_on`, claim-swap `received_at`, response `api_request_timestamp`) — services_common.py:27-41, response.py:20-24
- §2.5 — insert — ambiguity — `version` starts at 1 at creation; one increment per affected resource per mutating request — services_common.py:33,38-42
- §2.10 — insert — ambiguity — undefined paths and unsupported methods → `ERR_NOT_FOUND` (404) — app.py:41-48
- §2.11 — revise — mismatch — reordered tiers 11/12: at the distribution gate impl runs `ERR_ASSETS_PENDING_SALE` → `ERR_OBJECTIONS_PENDING` → fiscal (`ERR_NO_FUNDS_TO_DISTRIBUTE`), and `ERR_CLAIMS_UNREVIEWED` sits right after the tier-7 bar-date check — routes_cases.py:133-136,151-157
- §3.1 — insert — ambiguity — no-asset-report precondition failures (assets exist / open claims / non-zero cash) → `ERR_INVALID_STATE` (409); filing bumps case version exactly once — routes_cases.py:172-181
- §3.1 — insert — ambiguity — conversion clears swept claims' `objection_id` but leaves objection rows (incl. `PENDING`) untouched — routes_cases.py:193-207
- §3.2 — insert — ambiguity — creditor-filed claim with `creditor_id` ≠ `X-User-ID` → `ERR_NOT_ASSIGNED_TRUSTEE` (403); nonexistent `creditor_id` → `ERR_REFERENTIAL_INTEGRITY` (422) — routes_claims.py:44-51
- §3.2 — revise — mismatch — `claim_number` is a 1-based register rank re-ranked on every filing (tie chain `received_at` → creditor `created_at` → claim `created_at` → insertion order); renumbering shifts existing claims without refreshing their `updated_at`/`version` — services_calc.py:87-99
- §3.2 — insert — ambiguity — `late` filter accepts case-insensitive `true`/`false`; other values apply no filtering; encumbered-assets listing is the union of `encumbered_claim_id` referrers and the claim's own `secured_by_asset_id` asset — routes_claims.py:105-109,158-167
- §3.3 — insert — ambiguity — `proposed_priority_class` class-match violation → `ERR_INVALID_REQUEST` (400) — routes_claims.py:256-258
- §3.3 — insert — ambiguity — PARTIAL settle: `settled_priority_class` optional (defaults to current class); `settled_amount_cents` missing/non-integer/negative → `ERR_INVALID_REQUEST` (400) — routes_objections.py:102-115
- §3.3 — insert — ambiguity — reopen from any non-`CLAIMS_ADMINISTRATION`/`LIQUIDATION` posture (incl. `OPEN`, `ASSET_INVESTIGATION`, `FINAL_REPORT`) → `ERR_CASE_BEYOND_REOPEN` — routes_claims.py:210-212
- §3.4 — insert — ambiguity — asset scheduling not posture-gated; `encumbered_claim_id` must name an existing same-case claim (422) but its class is not validated — routes_assets.py:24-58
- §3.4 — insert — ambiguity — `mark_for_sale` posture violation → `ERR_INVALID_STATE` (409); `release_exemption` on non-exempt asset → `ERR_INVALID_STATE` (409) — routes_assets.py:114-116,146-147
- §3.4 — revise — mismatch — `sale_approved_on` stamps the full logical timestamp (not a date) and `effective_on` is that exact instant + `objection_window_days` days — routes_sales.py:116-118, services_calc.py:214-215
- §3.4 — insert — ambiguity — Trustee cancelling an `APPROVED` sale → `ERR_FORBIDDEN_FOR_ROLE` (403) — routes_sales.py:156-160
- §3.5 — insert — ambiguity — registration not posture-gated; `transferee_creditor_id` must exist (422); `demand_amount_cents` shape-checked only (integer ≥ 0) at registration, band enforced at demand — routes_avoidance.py:48-69
- §3.5 — insert — ambiguity — settle amount missing/non-integer/negative/above demand → `ERR_INVALID_REQUEST` (400); zero settlement accepted and posts a zero-amount deposit — routes_avoidance.py:187-201
- §3.6 — revise — mismatch — `reserve_for_objected_cents` is a single cross-class total (not per-class); `plan_sequence` = count of all existing plans of the case (any status, incl. `VACATED`) + 1; proposal outside `DISTRIBUTION` → `ERR_CASE_NOT_IN_DISTRIBUTION` (409) — routes_plans.py:36-56
- §3.6 — insert — ambiguity — `PlanClassAllocation` rows created only for strictly-positive grants; per-class ordering `claim_number` asc with insertion-order final tie-break — services_calc.py:115,131-148
- §3.6 — insert — ambiguity — voiding never starts execution; all-voided or zero-dividend confirmed plans stay `CONFIRMED` until vacated — routes_plans.py:173-182,215-230
- §3.7 — insert — ambiguity — trustee filing with missing `commission_basis` or `requested_amount_cents` ≠ DISBURSED-basis commission → `ERR_INVALID_REQUEST` (400); non-trustee applications may omit `commission_basis` and carry `computed_commission_cents` null — routes_fees.py:54-77

Everything else in the implementation (all 77 routes, envelope shapes, waterfall math, §326 tiers, ledger invariant, OCC scope, report lifecycle) was already uniquely pinned by PRD_FINALIZED.md and required no change.
