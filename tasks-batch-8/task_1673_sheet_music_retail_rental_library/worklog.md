# Worklog — task_1673_sheet_music_retail_rental_library

## Step 1: Create Task Directory — 2026-08-14T06:39:00.000Z

Task directory `tasks/task_1673_sheet_music_retail_rental_library/` and `workspace/` subdirectory pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per instructions.

## Step 2: Generate Scaffold — 2026-08-14T07:15:00.000Z

Scaffold generation complete. All three artifacts written to `/home/ubuntu/github/CodingPRD/tasks/task_1673_sheet_music_retail_rental_library/` and lint-clean.

**Design** (Expert tier, hardened per directive): primary archetype quota/allocation (finite rental-set copies competed across overlapping loan windows) blended with compliance/audit; cyclic state-machine shape (renewal self-loop, dispute/reissue revert loop, PO credit-hold cycle); segregation-of-duties role model (condition assessor can never issue/resolve the damage invoice on the same line); logical clock + daily sweep with pinned default `2026-08-01T00:00:00Z`.

**Counts:**
- Entities: 12 (Publisher, Work, RentalSet, CustomerAccount, PurchaseOrder, RentalOrder, RentalLine, ConditionReport, DamageInvoice, PerusalRequest, SaleRecord, RightsAdvisoryCase)
- State machines: 10 (54 transitions)
- Calculation rules: 7 (incl. dual-variant rental fee provisional/final, dual-variant open/settled exposure, per-line-then-multiply rounding pin on perusal conversion credit, floor/cap damage matrix, half-open interval allocation, closed+buffer perusal holds)
- Validation rules: 22 (ordered priorities 1–22)
- Endpoints: 72 (incl. `/_clock/set_current_utc` and `/_sweep/run_daily`)
- Error codes: 44 (all verified triggerable)
- Roles: 6 (Customer is entity_backed:CustomerAccount; five opaque staff roles)
- Concurrency rules: 2 (OCC on RentalOrder.version via renew, on CustomerAccount.version via credit-adjustments)
- §1.8: 9 rule groups × 2 instances = 18 difficulty instances, all numeric asserts pre-computed as literals (e.g., provisional 50000 vs final 52400; open 72400 vs settled 20000; tier inversion 216000 vs 200000 at 24/25 copies; rounding-order split 6538 vs 6539)
- §1.9: 13 sections, 64 instances (45 full recipes + 19 excluded_because stubs citing §1.8)

**Difficulty-rule differentiation audit:** Rule 1 spans RentalOrder fees vs CustomerAccount exposure; Rule 2 spans mode (a) tiered inversion vs mode (b) rounding order; Rule 3 spans RentalOrder cycle vs DamageInvoice revert loop; Rule 4 spans sweep-triggered depth-3 vs invoice-issue-triggered depth-3 cascades; Rule 5 spans state-vs-fiscal vs auth-vs-safety pairs; Rule 6 spans a money threshold via reserve vs a date threshold via the sweep endpoint; Rule 7 spans RentalOrder→PurchaseOrder vs RentalOrder→RightsAdvisoryCase; Rule 8 spans half-open rental-copy intervals vs closed+quarantine perusal holds; Rule 9 spans copy-pool conservation vs monetary exposure conservation.

`scaffold_lint.py` verdict (verbatim): "VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1 5." (645 calls scanned, 0 violations). Additional audits passed: all state-machine states reachable from initial, all enum values producible, no forbidden concurrency vocabulary, unique instance names across both design files, stub references resolve.

## Step 3: Copy Shared Files — 2026-08-14T07:17:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1673_sheet_music_retail_rental_library/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T07:41:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1673_sheet_music_retail_rental_library/workspace/PRD.md`.

**Output**: 336 lines, ending at the §5 error table (no audit footer in the document).

**Section list**:
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC · 2.2 API Response Structure (verified byte-identical to the verbatim source) · 2.3 Pagination · 2.4 Common Resource Properties · 2.5 Money, Precision, and Rounding Discipline · 2.6 The Logical Clock and the Daily Sweep · 2.7 Optimistic Concurrency Control · 2.8 Resource Existence and Retrieval Order · 2.9 The Validation Pipeline (22 tiers in scaffold priority order) · 2.10 Loan Windows, Perusal Holds, and Quarantine Buffers
- §3 Business Logic (9 subsections): Publisher/Catalog Governance (incl. out-of-print sourcing ETA) · Rental Sets & Copy Availability Ledger · Customer Accounts, Credit Exposure (dual open/settled variants) & Standing · Purchase Orders & Encumbrance · Rental Journey Draft→Return (fee estimate, reserve, dispatch, renew, sweep, cancel) · Condition Assessment, Damage Billing & Dispute Loop (final fee, damage charge, segregation of duties, settle) · Perusal Copies, Holds & Conversion · Retail Sales · Performance-Rights Advisory
- §4 Endpoint table: 72 rows, 4 columns (Method / Path / Description / Authorized Roles)
- §5 Error catalogue: 44 rows, 2 columns (Error ID / HTTP Status)

**Coverage-audit results**:

- **Contract 1 (Field-Name Coverage)**: 97 required identifiers (all `entities[].fields[]` plus every endpoint input/query/output name) — 97 present in backticks, 0 missing. Additionally all 44 error IDs, all 6 role names, and all 66 state/enum literals verified present. **PASS**
- **Contract 2 (Rule Coverage)**: 36 targeted rule spot-checks all confirmed in prose — both OCC rules (write operation + `expected_*_version` field + `ERR_STALE_VERSION`/412); the 22-tier validation pipeline ordering; all 7 calculations with pinned rounding orders (fee estimate tiers 1.5×/2.0×, volume tiers 10–24/25+, digital 0.80; late tiers 7/23/31+ at 10/25/50%; damage fractions with 200,000-cent cap and 1,500-cent floor; exposure open-vs-settled status sets; 15% conversion credit with per-unit rounding; sourcing ETA 45+30/60−15 floor 7); all cross-entity cascades (reserve, check-in grade-D→UNDER_REPAIR, lost-copy non-restore, standing↔PO suspension, settle encumbrance release, cancel compensation, invoice issue/resolve/reissue with supersession); validation `applies_to` scopes enumerated by capability framing; sibling branches (accepted/waived, DRAFT/RESERVED cancel, ON_LOAN/OVERDUE check-in and report-lost, SHIPPED/OVERDUE_PERUSAL return) rendered with equal density. **PASS**
- **Contract 3 (§3 Path Purity)**: 744 backtick tokens scanned in §3 — 0 path tokens, 0 bare HTTP methods, 0 method+path combos. **PASS**

One note: the single fuzzy-word scan hit ("about") is the benign preposition "rules about whether works may circulate" in §1, not an approximation of any threshold — left as-is. The forbidden sibling files were never opened.

## Step 5: Generate Unit Tests — 2026-08-14T08:15:00.000Z

Test generation for task_1673 is complete. Summary:

## Test counts

**81 tests total** — Queue A (Difficulty): 36 tests; Queue B (Corner): 45 tests.

### Queue A — SCAFFOLD_DIFFICULTY_DESIGN.yaml (all 18 instances covered, ≥2 tests each)

| Instance | Tests | Notes |
|---|---|---|
| dual_variant_calc/rental_fee_provisional_vs_final_on_late_return | 2 | provisional 50000 stamped at reserve + final null; final 52400 after 10-day-late return |
| dual_variant_calc/account_exposure_open_vs_settled_divergence | 2 | open 72400; settled 20000 (then 22400 after invoice issue) |
| combinatorial_formula/rental_fee_tiered_volume_discount_inversion | 2 | 24 copies → 216000; 25 copies → 200000 (inversion) |
| combinatorial_formula/perusal_conversion_per_unit_rounding_order | 2 | unit 934 / total 6538; balance_due == total |
| non_linear_state_machine/rental_order_renewal_cycle_and_cap | 2 | renewals 1–2 (100000/150000, due 10-04/11-03); third → ERR_RENEWAL_CAP_REACHED |
| non_linear_state_machine/damage_invoice_dispute_reissue_loop | 2 | reissue → ISSUED 4800, reports SUPERSEDED/INVOICED; loop closes via RESOLVED_ACCEPTED |
| transitive_cascade/overdue_sweep_cascade_order_account_po | 2 | OVERDUE→HOLD→SUSPENDED chain; sweep tallies (swept_rentals 1, standing_flips 1) |
| transitive_cascade/invoice_issue_credit_breach_cascade | 2 | settled 8400 at limit 7000; HOLD + PO SUSPENDED |
| priority_pair_validation_conflict/state_vs_business_fiscal_on_dispatch | 2 | ERR_INVALID_STATE masks ERR_PREPAYMENT_REQUIRED (PRD §2.9 pins pipeline order, so not a silence-pattern skip); order stays DRAFT |
| priority_pair_validation_conflict/safety_vs_referential_on_invoice_issue | 2 | role gate beats SoD; SoD blocks same-user BillingManager, distinct user succeeds |
| boundary_precision_check/credit_limit_exact_boundary_on_reserve | 2 | 70000 == limit passes; 69999 → ERR_CREDIT_LIMIT_EXCEEDED |
| boundary_precision_check/po_valid_until_date_threshold_boundary | 2 | sweep at valid_until → APPROVED; +1 day → EXPIRED |
| cross_entity_state_dependency/dispatch_gated_by_purchase_order_state | 2 | SUBMITTED PO → ERR_PO_NOT_USABLE; after approve RESERVED + encumbered 10000 |
| cross_entity_state_dependency/dispatch_gated_by_rights_advisory_state | 2 | OPEN and LICENSE_REQUIRED → ERR_RIGHTS_NOT_CLEARED; CLEARED → DISPATCHED |
| resource_temporal_overlap/rental_copy_half_open_adjacency | 2 | adjacent touch RESERVED; 1-day overlap ERR_INSUFFICIENT_COPIES |
| resource_temporal_overlap/perusal_hold_closed_interval_with_quarantine | 2 | ship at hold_end → ERR_PERUSAL_HOLD_CONFLICT; next day APPROVED |
| compensating_invariant/copy_pool_conserved_across_reserve_and_cancel | 2 | 30→25 on reserve; 25→30 on cancel (with ledger invariant probe) |
| compensating_invariant/outstanding_balance_conserved_across_issue_and_waive | 2 | 5400→7800 on issue; back to 5400 after dispute+waive |

### Queue B — SCAFFOLD_CORNER_DESIGN.yaml (all 45 non-stub instances covered, 1 test each)

All 7 entities, 6 state_machines, 5 calculations, 14 validations (incl. the non-stub `zero_copy_pool_boundary_on_overlap`), 3 endpoints, 3 errors, 4 rbac, 2 cross_cutting_layers, 1 consistency_model instances yielded tests. The 19 `excluded_because:` stubs were not translated; all stub `difficulty_instance` cross-references resolve to real §1.8 instances.

**Instances skipped:** none. Two assertion-level weakenings within covered instances, both for unique-derivability (not coverage):
- `create_publisher_applies_defaults`: dropped the `version == 1` assertion — PRD §2.4 pins "+1 per modification" but never the initial counter value. All flag defaults and status ACTIVE are asserted.
- `zero_copy_pool_boundary_on_overlap`: dropped the `available_copy_count == 0` assertion — after a 2-copy and an adjacent 2-copy reservation, the PRD §3.2 ledger formula (`copy_count` minus held lines) naively yields −2, and the PRD never pins clamping. Both rule-bearing outcomes (overlap → ERR_INSUFFICIENT_COPIES, adjacent → RESERVED) are asserted.

**PRD-citation audit:** all 81 docstrings carry verbatim, whitespace-normalized PRD quotes (0 failures; 5 initial ASCII `->` vs PRD `→` mismatches fixed). No skip/xfail markers. Priority-pair tests are legitimate because PRD §2.9 explicitly states the tier order and masking rule.

### test_helpers/ file list
- `/home/ubuntu/github/CodingPRD/tasks/task_1673_sheet_music_retail_rental_library/test_helpers/__init__.py` — barrel (framework + PRD-specific)
- `types.py` — 12 entity TypedDicts + 20 status/role enums (all entities carry id/created_at/updated_at/version per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with 55 methods, one per endpoint
- `api_errors.py` — `ApiErrorId` (45 errors) + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity shape assertions + `assert_copy_pool_invariant`
- `factories.py` — 10 payload factories (input fields only)
- `constants.py` — fee tiers, late tiers, damage cap/floor, perusal window/quarantine, OOP base, renewal cap
- `test_users.py` — `TEST_USERS` for the 5 opaque roles + `make_customer_headers(account_id)` for the entity-backed Customer role
- `fixtures.py` — clock/sweep helpers, tier-1 creators, lifecycle transitions (reserve/dispatch/confirm/check-in/renew/settle/dispute), and composites: `setup_catalog`, `setup_order_on_loan`, `setup_returned_order`, `setup_draft_invoice`, `setup_draft_invoice_with_assessor` (pinned assessor for SoD), `setup_issued_invoice`, `setup_shipped_perusal`

Suite collects cleanly under pytest (81 collected), all files compile, pyflakes clean (barrel re-exports excluded), and no generated comment mentions the scaffold.

## Step 6: Generate Implementation — 2026-08-14T08:15:00.000Z

Done. Implementation complete and verified: **81/81 tests pass, twice in a row**, under `prd-bench-local-run --isolation per-test-server` (fresh server boot via `start.sh` before every test).

## File list — `tasks/task_1673_sheet_music_retail_rental_library/workspace/implementation/`

| File | Role |
|---|---|
| `start.sh` | Foreground launcher; guarded `pip install` (no-op once flask present); `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | `flask>=3.0,<4` |
| `app.py` | App factory, envelope-shaped error handlers (ApiError/404/405/500), blueprint registration |
| `db.py` | Empty-per-boot in-memory stores + logical clock (starts exactly `2026-08-01T00:00:00Z`) + global insertion sequence |
| `errors.py` | `ApiError` + all 43 error-ID constants |
| `util.py` | IDs, timestamps (3-fractional-digit ISO), date/instant parsing, `touch()` (updated_at refresh + version increment), type validators |
| `response.py` | `meta`/`response_type`/`data` envelope; list pagination fields `limit/offset/total_count/has_more` |
| `middleware.py` | `X-User-ID`/`X-User-Role` check (tier 1, exempting the two system endpoints) + role gate (tier 2) |
| `calc.py` | All calculations in Decimal with round-half-up: tiered rental fee (provisional + settlement projection), final fee with 7/23/31+ late tiers off a once-rounded daily base, damage charge (fraction table, 1500 floor, 200000 cap, LOST per-copy value), perusal conversion per-unit-then-multiply pricing, out-of-print sourcing ETA |
| `services.py` | Existence lookup, derived ledgers, overlap counting, standing HOLD/GOOD cascade with PO suspend/restore, daily sweep |
| `serializers.py` | Per-entity output shape and per-field date formats |
| `routes/` (13 modules) | system, publishers, works, rental_sets, accounts, purchase_orders, rental_orders, rental_lines, condition_reports, damage_invoices, perusals, sales, rights |

## Endpoint count
**72 routes** implemented (all 72 from the scaffold/PRD table), covering 12 entities plus `_clock/set_current_utc` and `_sweep/run_daily`.

## Design decisions worth noting
- **Derived ledgers, imperative version bumps.** `available_copy_count`, PO `encumbered_cents`, and both exposure counters are computed on read from current state (no drift possible), while `version`/`updated_at` increments fire imperatively at exactly the scaffold-listed cascade points (e.g. account +1 on reserve/renew/check-in/settle/cancel, +2 on invoice issue that trips the credit limit; PO +1 on encumber/release/suspend/restore).
- **Availability = `max(0, copy_count − lines in {RESERVED, DISPATCHED, ON_LOAN, OVERDUE, LOST})`** — LOST stays subtracted (pinned by the report-lost test: 30→28), clamped at 0 (pinned by the zero-pool adjacency test). The overlap *projection* uses only the four live statuses with half-open windows; the reserve overlap check is skipped for DIGITAL orders per the precondition text.
- **Validation pipeline follows PRD §2.9 numeric precedence**, which the state-machine prose contradicts in places — e.g. reserve surfaces license (7) → set rentability (8) → work rentability → overlap (9) → PO usable (12) → PO amount (13) → credit (14) → standing (16); renew runs overlap/PO/standing/cap *before* shape (19) and OCC (20). Priority-pair tests (state-beats-prepay, auth-beats-SoD) pass.
- **Date formats are field-specific**, matching the pinned assertions: rental/PO dates echo date-only (`2026-09-04`); perusal `ship_date`/`hold_start`/`hold_end`/`return_due_date` are instants (`2026-08-29T00:00:00Z`); `created_at`/`updated_at` carry three fractional digits.
- **`line_grades` is polymorphic** (comma-separated string like `"C,A"`, list of grades, line-id map, or list of objects); unmentioned lines default to their checkout condition.
- **No startup seeding** — the store is empty on every boot; everything is built through the API.
- **OCC fields accept int or numeric string** (test recipes interpolate versions as strings).
- **One test-side fix, not implementation-side**: `test_helpers/fixtures.py::setup_shipped_perusal` passed `title=`/`sale_price_cents=` both as explicit kwargs and inside `**work_over`, a Python `TypeError` killing 3 tests at setup. Merged the dicts before the call; the suite then went 78/81 → 81/81.

## Step 7: Run Tests and Iterate — 2026-08-14T08:30:00.000Z

## Summary — task_1673_sheet_music_retail_rental_library

**Result: CLEAN — all 8 parallel rounds passed 81/81. Zero failures, zero errors, zero flakiness.**

- **Iterations run:** 1 (single 8-round parallel sweep under `--isolation per-test-server`, all rounds launched concurrently and joined with `wait`; every round ran to completion).
- **Per-round outcome:** rounds 1–8 each `passed=81 total=81 failed=0 errors=0`. Union of failing tests across all rounds = empty set.
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none this iteration (the prior-step `setup_shipped_perusal` duplicate-kwarg fix held).
- **Fixes applied to `implementation/`:** none.

The implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1673_sheet_music_retail_rental_library/workspace/implementation/` and the test artifacts at `test_suite/` / `test_helpers/` are stable under the 8-round concurrency sweep. Step 7 (test/fix iteration loop) is complete; Step 8 (PRD finalization) can be skipped per the pipeline rules since this step required zero fixes, and Step 9 (PRD completeness scan) is next.

## Step 8: Finalize PRD — 2026-08-14T08:30:00.000Z

SKIPPED. Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes (zero iterations beyond baseline), so per the pipeline's skip condition `PRD.md` already determined every behavior the implementation exhibits. No `PRD_FINALIZED.md` produced; Step 9 will start from `PRD.md`. (Note: the one pre-Step-7 fix in Step 6 — `setup_shipped_perusal` duplicate-kwarg TypeError — was a pure Python fixture bug, not a PRD silence/mismatch signal.)

## Step 9: Complete PRD — 2026-08-14T08:55:00.000Z

The odd-backtick lines are pre-existing JSON code fences, identical in the original. The file is complete and consistent.

## Report

Produced `/home/ubuntu/github/CodingPRD/tasks/task_1673_sheet_music_retail_rental_library/workspace/PRD_COMPLETED.md`.

**Size**: PRD.md 335 lines / 58,433 chars → PRD_COMPLETED.md 339 lines / 64,405 chars. Delta: +4 lines, +5,972 chars. 35 hunks touched; all edits are inline inserts/revisions except two standalone paragraphs (§2.2 error fallbacks, §2.4 date-format sentence). No sections added or removed.

**Counts**: 40 changes total — 32 ambiguity-pins, 8 mismatch-revisions.

**Changes** (PRD section — insert|revise — ambiguity|mismatch — what — impl source):

- §2.1 — revise — mismatch — Customer `ERR_FORBIDDEN_ACCOUNT` ownership checks pinned to only the four explicit sites (account read, confirm-receipt, dispute, case withdraw); other reads/lists unscoped — middleware.py + routes/accounts.py:74-81, rental_orders.py:290-304,464-482, rights.py:94-104
- §2.2 — insert — ambiguity — `api_request_timestamp` reads the logical clock — response.py:7-11, util.py:26-27
- §2.2 — insert — ambiguity — unknown path/method/server failure → same envelope, `ERR_INVALID_REQUEST` at 404/405/500 — app.py:36-46
- §2.3 — insert — ambiguity — limit/offset clamped (not rejected), non-numeric → `ERR_INVALID_REQUEST`, `created_at` ties break by creation order — routes/helpers.py:23-49
- §2.4 — insert — ambiguity — `version` starts at 1; `created_at`/`updated_at` captured from logical clock — util.py:69-82
- §2.4 — insert — ambiguity — field-specific date formats: order/PO dates bare ISO dates; perusal timing fields and `current_utc`/`quoted_expiry` second-precision instants — serializers.py:20-26, util.py:34-41
- §2.6 — insert — ambiguity — in-memory per-process store, empty at boot, no seeding — db.py:1-24
- §2.6 — insert — ambiguity — clock-set accepts instant or bare date (midnight UTC), adopted verbatim (backward allowed), unparseable → 400 — routes/system.py:17-25, util.py:44-60
- §2.7 — insert — ambiguity — OCC fields accept int or numeric string; missing/non-numeric → `ERR_INVALID_REQUEST` before version compare — routes/helpers.py:58-63
- §2.8 — insert — ambiguity — body-carried ids produce the same resource-specific 404s, checked after required-field presence — create endpoints across routes/
- §2.9 tier 4 — revise — ambiguity — out-of-vocabulary status target is no transition and falls to tier 19 — routes/publishers.py:78-83, rental_sets.py:85-90
- §2.9 tier 8 — revise — mismatch — at perusal approval the eligibility check (`ERR_PERUSAL_NOT_ALLOWED`) runs before license-format (tier 7) — routes/perusals.py:100-106
- §2.9 tier 19 — insert — ambiguity — body must be a JSON object (absent = empty); unrecognized fields ignored — routes/helpers.py:13-20
- §3.1 — insert — ambiguity — work status settable in either direction — routes/works.py:117-121
- §3.1 — insert — ambiguity — duplicate `catalog_number` per publisher → `ERR_INVALID_REQUEST` — routes/works.py:63-65
- §3.1 — insert — ambiguity — sourcing quote served regardless of `out_of_print` flag — routes/works.py:102-108
- §3.2 — revise — mismatch — availability = `copy_count` − lines in {RESERVED, DISPATCHED, ON_LOAN, OVERDUE, **LOST**}, computed from current line state on read, floored at 0 — services.py:10,53-55
- §3.2 — insert — ambiguity — duplicate `set_code` → `ERR_INVALID_REQUEST` — routes/rental_sets.py:42-44
- §3.2 — insert — ambiguity — repair-complete default lifts D→C when no grade supplied; direct `condition_grade` override allowed, D on IN_SERVICE → UNDER_REPAIR — routes/rental_sets.py:97-118
- §3.3 — insert — ambiguity — standing restoration evaluated at invoice payment/resolve/reissue, sale payment/write-off, settlement, perusal return, and sweep; check-in excluded — services.py:147-162 + call sites
- §3.3 — insert — ambiguity — new credit limit must be a non-negative integer — routes/accounts.py:91-93
- §3.4 — revise — mismatch — `encumbered_cents` = sum of `estimated_fee_cents` of non-terminal referencing orders only (dropped "plus invoiced damage" — no such mechanism exists), derived from current state — services.py:58-63
- §3.4 — revise — mismatch — renewal headroom substitutes renewed fee for current estimate (`encumbered − old + new ≤ ceiling`), no double-count — routes/rental_orders.py:326-332
- §3.4 — insert — ambiguity — PO validity window inclusive of both boundary dates — routes/rental_orders.py:70-72
- §3.5 — insert — ambiguity — reservation copy-window overlap check skipped for DIGITAL orders — routes/rental_orders.py:126-130
- §3.5 — revise — mismatch — `checkout_condition` stamped `A` at line creation (reservation), unchanged at dispatch — routes/rental_orders.py:158-168,281-284
- §3.5 — insert — ambiguity — renewal overlap re-check applies to DIGITAL orders too — routes/rental_orders.py:321-324
- §3.5 — insert — ambiguity — sweep moves only still-`ON_LOAN` lines to OVERDUE — services.py:180-188
- §3.5 — insert — ambiguity — prepayments accepted in any order status; `amount_cents` must be positive int — routes/rental_orders.py:567-577
- §3.5 — insert — ambiguity — settlement-preview outside ON_LOAN/OVERDUE → `ERR_INVALID_STATE` — routes/rental_orders.py:227-228
- §3.6 — insert — ambiguity — `line_grades` polymorphism (comma string / grade list in `copy_seq` order / line-id map / object list), unmentioned lines default to checkout condition, unknown line ids ignored, invalid grade → 400 — routes/rental_orders.py:359-398
- §3.6 — revise — mismatch — `findings` requirement binds only manually filed reports; auto-filed reports (check-in, lost) carry none — routes/rental_orders.py:431-442, rental_lines.py:53-64, condition_reports.py:56-58
- §3.6 — insert — ambiguity — manual re-assessment filing not gated on an open dispute — routes/condition_reports.py:43-74
- §3.6 — revise — mismatch — invoice creation accepts a report in any status (must belong to the named line, else 400), not only FILED — routes/damage_invoices.py:54-83
- §3.6 — insert — ambiguity — resolve accepts ACCEPT/ACCEPTED/RESOLVED_ACCEPTED and WAIVE/WAIVED/RESOLVED_WAIVED — routes/damage_invoices.py:32-33,158-163
- §3.6 — insert — ambiguity — collected damage = amounts of PAID/RESOLVED_ACCEPTED invoices; `topup_cents` non-negative int, added to `prepayment_cents` — routes/rental_orders.py:513-530
- §3.6 — insert — ambiguity — lost-copy report leaves the set's `version` unchanged — routes/rental_lines.py:40-65
- §3.7 — insert — ambiguity — perusal approval check order pinned: state, eligibility, license, hold separation, standing, institution — routes/perusals.py:95-120
- §3.7 — insert — ambiguity — rental conversion creates the order with `fulfillment_format` PHYSICAL — routes/perusals.py:180-188
- §3.7 — insert — ambiguity — purchase conversion takes optional `quantity` (default 1) — routes/perusals.py:192-194

All seven "known design decisions" from the brief were verified in code and are pinned (availability formula w/ LOST + clamp; DIGITAL overlap skip at reservation; renew pipeline order confirmed consistent with §2.9; date formats; `line_grades` polymorphism; OCC int-or-string; no seeding). The two material mismatches found beyond the brief: the §3.4 encumbrance "invoiced damage" clause (impl has no damage-to-PO path) and the §2.1 blanket ownership-scoping sentence (impl scopes only four operations).
