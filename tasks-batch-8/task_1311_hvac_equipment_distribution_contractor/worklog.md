# Worklog — task_1311_hvac_equipment_distribution_contractor

## Step 1: Create Task Directory — 2026-08-12T21:12:00.000Z

Task directory `tasks/task_1311_hvac_equipment_distribution_contractor/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per orchestration instructions (no index scan, no other task_* directory touched).

## Step 2: Generate Scaffold — 2026-08-12T21:47:30.000Z

## Summary

Generated the scaffold for task_1311 (HVAC Equipment Distribution & Contractor Program) purely from the scenario + skill spec, at harder-than-expert density.

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1311_hvac_equipment_distribution_contractor/SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1311_hvac_equipment_distribution_contractor/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1311_hvac_equipment_distribution_contractor/SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

**Counts:**
- Entities: 15 (Contractor, EquipmentModel, AHRISystemRating, PreBuyProgram, Order, OrderLine, AllocationPool, WarrantyRegistration, PartsClaim, RefrigerantCylinder, RefrigerantEvent (immutable, `common_fields: false`), RebateSubmission, TrainingCourse, TrainingCredit, CoopClaim)
- State machines: 8 declared in §1.2 (Order fulfillment, OrderBilling parallel dimension, PartsClaim revision loop, RefrigerantCylinder cycle, WarrantyRegistration, RebateSubmission, CoopClaim dispute loop, TrainingCourse) — non-linear shapes: cycles on PartsClaim/Cylinder/CoopClaim, parallel status × billing_status on Order
- Calculation rules: 9 (incl. dual variants on co-op accrual provisional-vs-final and tier list-vs-prebuy price basis; combinatorial modes (b) per-line-rounding and (c) pinned circular evaluation order on the federal rebate)
- Endpoints: 67; Errors: 24; Roles: 5 (segregation of duties: submitter ≠ qualifier ≠ payer); 2 OCC concurrency rules (Order PATCH, RebateSubmission PATCH); logical-clock test endpoint with pinned default 2026-08-01T00:00:00Z
- §1.8 difficulty instances: 18 (2 per rule × 9 rules), each with fully structured, placeholder-closed `setup_api_calls` and precomputed literal asserts
- §1.9 corner instances: 45 (40 active + 5 `excluded_because` stubs... lint counts 40 active; 45 total entries including stubs)

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

**Key design choices for difficulty:** transitive depth-3 cascade on order DELIVERED (accrual → tier flip → provisional rebase), depth-2 lapse cascade auto-denying open claims, validation priority conflicts on disjoint category pairs (state vs fiscal; temporal vs fiscal), half-open vs closed-plus-buffer interval semantics on different resources, compensating invariants on two conserved quantities (pool units, accrual cents), and a heel-shortfall compliance contagion that gates order submission. Two authoring bugs were caught and fixed during replay: a quantity-3 single line would have masked the per-line-rounding divergence (now three quantity-1 lines), and clock/deadline misalignment in the warranty revision-loop chain (now pinned to 2026-06-10).

## Step 3: Copy Shared Files — 2026-08-12T21:48:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1311_hvac_equipment_distribution_contractor/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-12T22:05:00.000Z

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1311_hvac_equipment_distribution_contractor/workspace/PRD.md` (358 lines)

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC (5 roles, per-role identity prose — `ContractorUser` entity-backed to `Contractor`, other four opaque; segregation-of-duties boundaries), 2.2 API Response Structure (canonical block emitted verbatim; only trailing `---` separator follows it, matching the reference example), 2.3 Pagination, 2.4 Logical Clock & Lazy State Sweeps (startup default 2026-08-01T00:00:00Z, deferred sweeps), 2.5 Resource Identity/Timestamps/Versioning (incl. explicit `RefrigerantEvent` exception: no `updated_at`/`version`), 2.6 OCC (both guarded writes with `expected_order_version` / `expected_rebate_version` → `ERR_STALE_VERSION` 412), 2.7 Units & Precision (integer cents, pinned per-calculation rounding points, 2-decimal weights, 1-decimal ratings), 2.8 Validation Pipeline (all 22 validations in explicit priority order, first-failure-wins, left-to-right path resolution), 2.9 Derived Fields & Cascading Consistency, 2.10 Compliance Standing Gate
- §3 Business Logic (9 subsections): dealer/tier program, catalog & AHRI matchups, pre-buy programs & allocation pools, order capture/pricing/allocation, billing & forfeiture, warranty & parts claims, refrigerant cylinders & heel compliance, rebate dossiers, training credits & co-op claims
- §4 Endpoint table: 67 rows, 4 columns, roles verified 1:1 against scaffold (0 mismatches)
- §5 Error catalogue: 24 rows, 2 columns

**Hard contract reports:**
- Contract 1 (Field-Name Coverage): entities[].fields 99 required / 99 present / 0 missing; endpoint input+query+path identifiers 69 required / 69 present / 0 missing. Status: PASS
- Contract 2 (Rule Coverage): validations with priority 22/22 expressed in ordered pipeline prose; concurrency_rules 2/2 (endpoint + occ field + error id + status all named); state-machine transitions 38/38 across 8 machines fully expressed (preconditions + error ids + side effects, incl. the three delivery cascades, claim-denial cascades on lapse/void, BACKORDERED↔SUBMITTED cyclic reversion, RETURN_PENDING downgrade to `WATCH`-not-`GOOD`); calculations 9/9 in precise reconstructible prose; endpoint side_effects and applies_to scopes all covered (one gap found during the walk — `ERR_MODEL_NOT_ORDERABLE` also guards AHRI rating creation referencing `DISCONTINUED` components — fixed in §3.2); sibling branches (three cancel from-states, dual billing tracks, VERIFIED three exits, both rebate lanes) rendered with equal density. Status: PASS
- Contract 3 (§3 Path Purity): 585 backticked tokens scanned; 0 path tokens, 0 bare HTTP methods, 0 method+path combos. Status: PASS

**Coverage notes / judgment calls:**
- All 24 error IDs, all state values (8 machines), all enum field values, and all 5 role names verified present.
- Money constants expressed with dual units for exact reconstruction ($50,000 / 5,000,000 cents tier thresholds; $2,000 / 200,000 cents PREMIUM tier amount, etc.); time constants (60-day registration window, 45-day decision deadline, 30-day overdue, 12-month rolling violation window, 24-month credit TTL, 3-revision cap, 1-day instructor buffer, 2x pool capacity) embedded in business narrative.
- One scaffold inconsistency adjudicated: the `coop_accrual_calculation` formula's provisional `input_set` includes `DELIVERED` lines while the `Contractor` field description and delivery cascade note imply in-flight only. The PRD follows the formal calculation (provisional = `SUBMITTED`/`BACKORDERED`/`ALLOCATED`/`SHIPPED`/`DELIVERED`, excluding `CANCELLED`) consistently in both §3.4 and §3.9, rendering the delivery cascade as a recompute rather than a drop, so the document is internally consistent.
- The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, and no sibling task directories were inspected.

## Step 5: Generate Unit Tests — 2026-08-12T22:40:00.000Z

Done. Full test infrastructure and suite generated for task_1311.

## Summary

**Files written**

`test_helpers/` (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1311_hvac_equipment_distribution_contractor/test_helpers/`):
- `types.py` — 18 status/role enums + 16 entity TypedDicts; `RefrigerantEvent` correctly omits `updated_at`/`version` (append-only)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (58 methods), `/api/v1` prefix
- `api_errors.py` — all 24 error IDs with HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + pool-conservation invariant checker
- `factories.py`, `constants.py` (tier thresholds, heel fraction, rebate amounts, windows), `test_users.py` (4 opaque-role shared headers + mandatory `make_contractor_headers(id)` builder for the entity-backed ContractorUser), `fixtures.py` (clock, order lifecycle through DELIVERED, warranty/claim, rebate dossier, cylinder, co-op, training composites, all identity-threaded), `__init__.py` barrel

`test_suite/` (10 files): `conftest.py` + `test_01_contractor_accounts.py`, `test_02_tier_and_pricing.py`, `test_03_allocation_fulfillment_billing.py`, `test_04_programs_pools_training.py`, `test_05_warranty_parts_claims.py`, `test_06_refrigerant_credit_compliance.py`, `test_07_rebates.py`, `test_08_catalog_pairing_lines.py`, `test_09_coop_accrual.py`

**Coverage** (audit script verified programmatically):
- Queue A (difficulty): **18/18 instances, 37 tests** (each instance ≥2)
- Queue B (corner): **40/40 non-stub instances, 43 tests**; 5 `excluded_because` stubs not translated (all cross-references verified to resolve)
- **80 tests total**, every docstring ends with exactly one resolving `Design:` tag; **134 quoted PRD sentences all grep verbatim** against PRD.md; no skip/xfail markers; no scaffold references; `py_compile` and `pytest --collect-only` clean; all test imports resolve against helpers.

**Instances skipped: 0.** Five corner stubs excluded by design (not skips). 

**Notable PRD-first adjudications** (instances translated with PRD-derived outcomes where the index's literal recipe contradicted the contract):
- `computed_field_input_ignored_on_create` — index pinned `ERR_INVALID_REQUEST`; PRD §3.1 explicitly says supplied `tier` "is ignored" → test asserts 201 + STANDARD/0.
- `order_terminal_delivered_lockdown` — index pinned `ERR_ALREADY_TERMINAL`; PRD §2.8 states the from-state check runs first, "so a request failing both reports `ERR_INVALID_STATE`" → asserted `ERR_INVALID_STATE`.
- `rebate_pay_after_deadline_window_expired` — PRD names both `ERR_WINDOW_EXPIRED` (§3.8 payout-deadline sentence) and implies terminal lockdown via the lazy EXPIRED sweep → used `validate_error_is_one_of([...])` (error-precedence silence pattern) + asserted the uniquely-derivable EXPIRED-on-read.
- `pool_quantity_conserved_across_submit_cancel` and `coop_accrual_input_set_filtering` — recipes assumed orders stay SUBMITTED after submit, but PRD advances fully-reserved orders to ALLOCATED (not cancellable) → conservation claims realized via the PRD-legal BACKORDERED → (pool-close reversion) → SUBMITTED → cancel path.
- `rebate_qualification_circular_order_pinned` — recipe's `install_date` preceded `submitted_at` (would trip `ERR_REBATE_MISMATCH`); fixed to `submitted_at`, and the indoor coil priced at 0 so the 150000-cent answer holds under any plausible component-pricing reading.
- `backordered_order_recovers_on_pool_reopen` — second pool given a strictly later `season_start` so the pool-selection ranking (most recent first) makes the tier-priority sweep outcome PRD-derivable.

## Step 6: Generate Implementation — 2026-08-12T22:40:00.000Z

Done. Final summary:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1311_hvac_equipment_distribution_contractor/workspace/implementation/`)

- `start.sh` — executable launcher; guards `pip install` behind an `import flask` check, `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000), foreground
- `requirements.txt` — flask>=3.0
- `app.py` — Flask entry, blueprint registration under `/api/v1`, `before_request` lazy sweeps (skipped for the clock endpoint), JSON error handlers for `ApiError`/404/405/500
- `db.py` — in-memory dicts keyed by id (15 entity stores + heel-violation ledger); starts completely empty, no seeding anywhere
- `clock.py` — logical clock pinned to `2026-08-01T00:00:00Z` at boot, never wall-clock
- `errors.py`, `response.py`, `middleware.py`, `utils.py`, `serializers.py` — envelope (`meta.api_request_id`/`api_request_timestamp` 3-fractional-digit ISO, `response_type`, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more` in meta), `X-User-ID`/`X-User-Role` auth + RBAC + ContractorUser ownership, Decimal-safe parsing, `round_half_up` money helpers, structural-error collector (priority-22-last semantics)
- `routes/` — clock_route, contractors, catalog (equipment + AHRI), programs (pre-buy + pools), orders, warranty (registrations + parts claims), refrigerant, rebates, training, coop
- `services/core.py` — tier calc, per-line pre-buy pricing, provisional/final co-op accruals, waterfall allocation with per-pool aggregation + re-reservation sweep (tier → submitted_at → created_at priority) + pool-close reversion, compliance standing (heel violations, overdue), warranty coverage bands, rebate qualification, co-op eligibility with period caps, and the lazy sweep suite (cylinder overdue, registration lapse + claim-denial cascade, rebate expiry, credit expiry, deposit forfeiture, program/pool window recompute)

## Endpoint count
67 routes implemented — the complete scaffold endpoint table (all CRUD, list/filter/pagination, actions, billing events, decision endpoints, event ledger, clock).

## State machines implemented (8)
Order fulfillment (DRAFT→SUBMITTED→ALLOCATED/BACKORDERED→SHIPPED→DELIVERED, cancellations, BACKORDERED↔SUBMITTED pool-epoch cycle), OrderBilling (deposit/final tracks + FORFEITED), PartsClaim (revision loop bounded at 3 with `ERR_REVISION_LIMIT`, registration-lapse auto-denial), RefrigerantCylinder (IN_STOCK→ISSUED→RETURN_PENDING→RETURNED→IN_STOCK/RECLAIMED with heel-shortfall ADJUSTMENT markers), WarrantyRegistration (inclusive-deadline register, lapse/void cascades), RebateSubmission (DRAFT→SUBMITTED→DOCS_COMPLETE same-request flow, QUALIFY/PAY with deadline expiry), CoopClaim (VERIFY/APPROVE/DISPUTE/RESUBMIT loop, PAY debits final accrual), TrainingCourse (complete grants 24-month credits).

## Key semantics honored
OCC via `expected_order_version`/`expected_rebate_version` → `ERR_STALE_VERSION` (412); validation priority pipeline with structural checks deliberately last (verified: stale-version+unknown-field returns 412, not 400); segregation-of-duties (processor/coordinator adjudicate, only DistributorAdmin pays); integer-cents Decimal math with pinned rounding points; all-or-nothing per-line allocation with same-family component aggregation.

## Boot verification
`bash start.sh` boots cleanly in ~2s and serves HTTP 200; after kill + relaunch the store is empty (`total_count: 0`), confirming per-test-server isolation readiness. Two smoke suites (121 assertions total, run against fresh boots) pass with zero failures.

## Step 7: Run Tests and Iterate — 2026-08-12T23:20:00.000Z

## Summary

**Exit state: clean 8-round parallel sweep — all 8 rounds 80/80 passed** (rounds 1-8, zero failures in the union).

### Iterations run
3 diagnostic sweeps with fixes applied (plus 1 solo confirmation run and 2 infra-killed retries). Failure trajectory: 70/80 → 79/80 → 79/80 (flake only) → **80/80 × 8**.

### Tests deleted
None. Every failing test traced to a verbatim PRD rule; all fixes were in test code or implementation.

### Fixes applied to `test_helpers/`
None — the helpers (fixtures, factories, role headers, constants) were all PRD-consistent.

### Fixes applied to `test_suite/`
- `/home/ubuntu/github/CodingPRD/tasks/task_1311_hvac_equipment_distribution_contractor/test_suite/test_02_tier_and_pricing.py` — `TestPrebuyPerLineRounding._setup_rounding_order`: bare `api.get_order` → `api_client.get_order` (NameError; `api` is a test-method fixture, not in scope in the helper). Both per-line-rounding tests then verified the implementation's PRD §2.7/§3.4 rounding discipline as correct.
- `/home/ubuntu/github/CodingPRD/tasks/task_1311_hvac_equipment_distribution_contractor/test_suite/test_06_refrigerant_credit_compliance.py` — added missing `submit_order` to the `test_helpers` import (NameError in both `TestValidationPriorityPairs` tests).
- `/home/ubuntu/github/CodingPRD/tasks/task_1311_hvac_equipment_distribution_contractor/test_suite/test_07_rebates.py` — `test_rebate_rating_not_on_order_rejected`: `get_success_data(resp, 201)` → `validate_success(resp, 201)` (TypeError; `get_success_data` takes 1 positional arg).
- `/home/ubuntu/github/CodingPRD/tasks/task_1311_hvac_equipment_distribution_contractor/test_suite/test_09_coop_accrual.py` — two setup-arithmetic bugs:
  - `TestProvisionalVsFinalDivergence._setup_two_orders`: delivered seed 10,000,000 → 4,000,000. The old seed flipped the contractor to SILVER, so the 5,000,000 in-flight order priced at 3% off (net 4,850,000) and the asserted exact accrual (300,000) silently assumed the gross-vs-net reading PRD leaves unpinned ("merchandise totals"). Keeping the contractor STANDARD makes list == net, so the dual-variant divergence assertions (provisional 180,000 / final 80,000 / ytd 4,000,000) are exact under any reading. PRD rule under test (§3.9 provisional-covers-in-flight vs final-covers-delivered-only) fully preserved.
  - `test_cancelled_order_excluded_from_both_accruals`: setup assertion 80,000 → 160,000 — the quantity-2 line against a pool of 1 (needed to force BACKORDERED) makes the in-flight order total 8,000,000, not 4,000,000; 2% = 160,000. The actual PRD assertion (cancelled → both accruals 0) unchanged.

### Fixes applied to `implementation/`
- `/home/ubuntu/github/CodingPRD/tasks/task_1311_hvac_equipment_distribution_contractor/workspace/implementation/routes/contractors.py` — `create_contractor`: extended the unknown-field whitelist to all PRD §3.1-named derived contractor fields (`ytd_purchase_cents`, `coop_accrual_provisional_cents`, `coop_accrual_final_cents`, `training_credit_balance_hours`, `compliance_standing`, `heel_violation_count_12m`; `tier` was already allowed). PRD §2.9 ("where a request supplies a value for a derived field, the supplied value is ignored") + §3.1 ("any value supplied at creation is ignored") require 201-with-ignore, not `ERR_INVALID_REQUEST`; the resource's own derived fields are "known", so §2.8 stage 22's unknown-field rejection does not apply to them.

### Infrastructure note (not a code bug)
The recurring `test_… could not be restarted` setup errors (one stall window per sweep, hitting all lockstep rounds at the same test index) were diagnosed as external host interference: ~10 sibling `prd-bench-entrance` pipelines run concurrently on this shared host, and a transient burst (or cross-pipeline port/process cleanup race) can stall a fresh server's first answer beyond the runner's fixed 15s poll, or SIGKILL a pytest chain (one sweep died with exit 144). Evidence: the identical test passes in solo runs; boot storms reproduced 120/120 healthy in isolation; failures carried no assertion traceback; two sweeps died mid-run with no results written. The final certification sweep ran clean end-to-end with all 8 rounds at 80/80.

## Step 8: Finalize PRD — 2026-08-12T23:35:00.000Z

Done. The diff is exactly two lines touched, both inline insertions; no other content changed.

## Summary

**Line counts:** PRD.md = 358 lines, PRD_FINALIZED.md = 358 lines, 0% line-count delta (2 lines revised in place, insertions only).

**Changes (one bullet each):**
- §3.1 — revise — pinned the ambiguous "merchandise totals" in the `ytd_purchase_cents` definition to net-of-discounts: each delivered order contributes its `total_cents` (the sum of its lines' `line_total_cents`), never undiscounted list prices — `implementation/services/core.py:171-180` (`compute_ytd` sums `o["total_cents"]`).
- §3.9 — revise — pinned the same "merchandise totals" phrase for both co-op accruals to the covered lines' `line_total_cents` summed (net of all line discounts) — `implementation/services/core.py:143-153` (`compute_provisional_accrual`), `156-168` (`compute_final_accrual`), `631-641` (`compute_coop_eligible` period-cap base).

Both edits trace to the step_7_diff `test_09_coop_accrual.py` `_setup_two_orders` fix, which explicitly identified "merchandise totals" (gross-vs-net) as a PRD silence the tests no longer pin but the implementation does (net everywhere). All other step_7_diff items produced no PRD edit: the `test_02` `api_client` NameError, `test_06` missing import, `test_07` `validate_success` fix, and the `test_09` 80,000→160,000 assertion are pure test/fixture bugs; the `contractors.py` whitelist extension was an implementation fix toward a behavior PRD §2.9 ("where a request supplies a value for a derived field, the supplied value is ignored") + §3.1 already uniquely determine, so that prose was kept verbatim.

**Per-edit pre-edit search log:**
1. Edit §3.1 (ytd):
   - (a) Subject: monetary base ("merchandise totals") for `ytd_purchase_cents` — gross vs net of discounts.
   - (b) Enumerated impl paths (grep for `line_total_cents|total_cents|ytd_purchase|coop_accrual|compute_*|refresh_*` across all routes/services, then read): `services/core.py:171-180` `compute_ytd` (order `total_cents`, net); `core.py:110-126` `recompute_order_totals` (proves order `total_cents` ≡ Σ`line_total_cents`); `core.py:86-107` `resolve_line_pricing` (tier discount baked into `unit_price_cents`, pre-buy discount into `line_discount_cents`, so `line_total_cents` is net of both); `core.py:183-197` `refresh_contractor_commercials`; `routes/orders.py:279-342` submit/cancel/deliver (all delegate to `core`, no parallel math); `routes/coop.py:121,151` (delegates); PRD-side parallel phrasings checked: §3.4's "$100,000 submitted order raises provisional by $2,000" example (consistent under net) and §3.8's installed-cost rule (already explicitly "net of any line discounts").
   - (c) Wording adjustment: phrased as "its `total_cents` ... (the sum of its lines' `line_total_cents`)" because both enumerations exist in the impl and are provably equal, so neither is mis-described; explicitly excluded "undiscounted list prices" only, leaving everything else in the sentence verbatim.
2. Edit §3.9 (both accruals):
   - (a) Subject: monetary base for `coop_accrual_provisional_cents` and `coop_accrual_final_cents` — gross vs net.
   - (b) Enumerated impl paths: `core.py:143-153` provisional (Σ`line_total_cents` over SUBMITTED/BACKORDERED/ALLOCATED/SHIPPED/DELIVERED); `core.py:156-168` final (Σ`line_total_cents` over DELIVERED minus PAID claims); `core.py:624-654` `compute_coop_eligible` (period-cap base also Σ`line_total_cents` of delivered orders, so the "final accrual for that period's window" is likewise net); `core.py:200-206, 407-443` refresh paths (cancel, re-reservation sweep, pool-close reversion) — all call the same two compute functions; no alternative accrual math exists anywhere in the codebase.
   - (c) Wording adjustment: scoped the clarification to "the merchandise total of the covered lines" (not a global redefinition of all money fields) and cross-referenced §3.1 ("here as in §3.1") so the two sites cannot drift into contradiction; left the status-set, rounding-discipline, and claims-debit clauses verbatim since every enumerated path confirms them.

File produced: `/home/ubuntu/github/CodingPRD/tasks/task_1311_hvac_equipment_distribution_contractor/workspace/PRD_FINALIZED.md`

## Step 9: Complete PRD — 2026-08-13T00:00:00.000Z

All edits are in place and verified. Here is the final summary.

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1311_hvac_equipment_distribution_contractor/workspace/PRD_COMPLETED.md`

**Size:** PRD_FINALIZED.md = 358 lines / 60,674 chars → PRD_COMPLETED.md = 364 lines / 67,186 chars (char delta **+6,512**; 28 diff hunks).

**Counts:** ambiguity-pins: **24**; mismatch-revisions: **5**.

### Changes (section — insert|revise — ambiguity|mismatch — what changed — impl ref)

- §2.1 — insert — ambiguity — pinned ownership scope: enforced on contractor-linked resources (contractor, orders+lines, registrations, claims, dossiers, credits, co-op claims) with 403 + list restriction for `ContractorUser`, pipeline position between stages 4 and 5; catalog/ratings/programs/pools/courses/cylinders unrestricted — `middleware.py:32-37`, `routes/common.py:46-47`
- §2.3 — insert — ambiguity — limit/offset out-of-range values clamped; non-integer → `ERR_INVALID_REQUEST` (400) — `middleware.py:40-59`
- §2.3 — insert — ambiguity — list sort ties broken by creation (insertion) order — `routes/common.py:53`
- §2.5 — insert — ambiguity — `version` starts at 1 — `routes/common.py:36-38`
- §2.6 — insert — ambiguity — missing `expected_*_version` → `ERR_INVALID_REQUEST` (400); only mismatches → 412 — `routes/orders.py:116-120`, `routes/rebates.py:151-155`
- §2.8 stage 6 — revise — mismatch — terminal-lockdown `ERR_ALREADY_TERMINAL` never fires; every transition's from-state enumeration rejects terminal from-states with `ERR_INVALID_STATE` (409) — `errors.py:54-55` (defined, never raised); all routes use `invalid_state`
- §2.8 — insert — ambiguity — undefined route/unsupported method → `ERR_NOT_FOUND` (404); decision/billing endpoints validate `action`/`event_type` and action-specific role before path resolution, and (with the course-cancel patch) ignore undeclared payload fields — `app.py:49-56`, `routes/orders.py:354-365`, `routes/warranty.py:233-248`, `routes/rebates.py:218-230`, `routes/coop.py:88-104`, `routes/training.py:94-104`
- §2.7 — insert — ambiguity — weights supplied at finer precision are rounded half-up to two decimals on acceptance — `utils.py:84-86`, `routes/refrigerant.py:64-66,143`
- §2.9 — revise — mismatch — supplied derived values ignored only when the endpoint's payload admits the field; otherwise rejected as unknown under stage 22 — `routes/contractors.py:29-35` vs `routes/programs.py:26-28`
- §3.1 — revise — ambiguity — every accepted contractor PATCH increments version even when values unchanged; `SUSPENDED` dealer's submission and cylinder issuance both rejected with `ERR_INVALID_STATE` (409) — `routes/contractors.py:113`, `routes/orders.py:256-257`, `routes/refrigerant.py:112-113`
- §3.2 — revise — mismatch — dropped "re-derives whenever a referenced model becomes DISCONTINUED" (no endpoint mutates model status; classification runs only at rating creation) — `routes/catalog.py:80-91,160-171`
- §3.2 — insert — ambiguity — rating creation payload may carry `status` ACTIVE (default) or WITHDRAWN — `routes/catalog.py:113-114`
- §3.3 — insert — ambiguity — manual program close legal only from SCHEDULED/OPEN, else `ERR_INVALID_STATE` — `routes/programs.py:96-97`
- §3.3 — insert — ambiguity — pool capacity cap judges coverage by season bounds regardless of manual close; pool-close reversion applies on season passage too; closing a CLOSED pool → `ERR_INVALID_STATE` — `routes/programs.py:121-132,180-188`, `services/core.py:474-485`
- §3.4 — revise — ambiguity — line list-price basis = model price for part lines, sum of component prices for system lines; non-pre-buy lines carry zero `line_discount_cents` — `services/core.py:62-107`
- §3.4 — insert — ambiguity — submission's DRAFT/has-lines/ACTIVE checks fail with `ERR_INVALID_STATE` (409); deposit recomputed on every totals recomputation, not only at submit — `routes/orders.py:249-257`, `services/core.py:110-126`
- §3.4 — insert — ambiguity — allocation demand is per component; components sharing one pool each contribute the line's quantity — `services/core.py:317-327`
- §3.4 — revise — ambiguity — re-reservation sweep covers SUBMITTED and BACKORDERED orders; fully-reservable swept orders move to ALLOCATED from either state — `services/core.py:407-429`
- §3.4 — revise — mismatch — removed "on a tier change the period caps re-derive" (caps derive live from delivered volume; tier plays no role) — `services/core.py:624-654`
- §3.6 — insert — ambiguity — registration create: non-DELIVERED order → `ERR_INVALID_STATE` (409); future install_date → `ERR_INVALID_REQUEST` (400); registering a LAPSED record → `ERR_WINDOW_EXPIRED`; claim_number is uppercase hex; future failure_date → 400 — `routes/warranty.py:51-64,114-126,185-191`
- §3.7 — revise — ambiguity — heel-shortfall ADJUSTMENT carries zero delta; violation window is twelve calendar months, boundary-inclusive; post-overdue WATCH floor is sticky (never returns to GOOD) — `routes/refrigerant.py:160-166`, `services/core.py:239-281`
- §3.9 — insert — ambiguity — cancelled courses skip the instructor-conflict check; cancel patch takes `action: CANCEL` (other → 400; non-SCHEDULED → 409); early completion → `ERR_WINDOW_EXPIRED`; duplicate roster ids yield one credit; `expires_at` is 24 calendar months with day clamping — `routes/training.py:42-53,100-107,136-160`
- §3.9 — revise — ambiguity — provisional accrual also recomputed at re-reservation sweeps and pool-close reversions — `services/core.py:429,443`
- §3.9 — revise — ambiguity — co-op period windows pinned (H1=[Jan 1, Jul 1), H2=[Jul 1, next Jan 1), membership by delivery timestamp), cap rounding steps, reduction by other APPROVED/PAID claims, zero floor; APPROVE additionally bounded by current final accrual — `services/core.py:624-654`, `utils.py:218-229`, `routes/coop.py:118-124`
- §4 — revise — mismatch — line additions return 201 Created (new OrderLine resource), not 200 — `routes/orders.py:204`

### Notable non-changes (verified consistent, no edit needed)
- All 40+ endpoints in §4 match impl exactly (no missing/extra routes).
- Warranty coverage bands, rebate qualification four-step math, tier thresholds/discounts, pre-buy rounding discipline, heel-check 90% threshold, 30-day overdue rule, and all lazy-sweep boundaries already match impl precisely.
- No training-credit consumption endpoint exists in either PRD §4 or impl, so the FIFO consumption prose is unreachable rather than contradictory — left untouched.
- `ERR_INTERNAL` (500) is a defensive fallback for server bugs only; not spec-surface behavior — left out of the catalogue.
