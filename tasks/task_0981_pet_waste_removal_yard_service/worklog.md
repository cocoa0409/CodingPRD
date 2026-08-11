# Worklog — task_0981_pet_waste_removal_yard_service

## Step 1: Create Task Directory — 2026-08-10T09:26:07.000Z

Pre-assigned output folder `tasks/task_0981_pet_waste_removal_yard_service` with `workspace/` subdirectory already exists per command args; Step 1 auto-index scan skipped as instructed. Treating Step 1 as done.

## Step 2: Generate Scaffold — 2026-08-10T09:48:29.000Z

Lint verdict: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

## Summary of generated scaffold

**Files produced** (all three under `/home/ubuntu/github/CodingPRD/tasks/task_0981_pet_waste_removal_yard_service/`):
- `SCAFFOLD.yaml` — §1.0–§1.7
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — §1.8 (single top-level `scaffold_difficulty_design:`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — §1.9 (single top-level `scaffold_corner_design:`)

**Archetype / profile**: Pricing engine (primary) × Temporal windowing (secondary); hybrid topology; cyclic state-machine shape; hierarchical_override role model; immediate consistency. Complexity layers: optimistic_concurrency, cascading_side_effects, scheduled_actions, rate_threshold_triggers, derived_field_reconciliation.

**Surface metrics**:
- Entities: 13 (Customer, Yard, PropertyAccessProfile, SubscriptionPlan, ServiceAddon, Subscription, ServiceRoute, Technician, VacationWindow, Visit, Invoice, InvoiceLineItem, SatisfactionReport)
- State machines: 6 (Subscription [cyclic ACTIVE⇄PAUSED], Visit [branching with multiple SKIPPED/MISSED/CANCELLED exits + bubble-up], ServiceRoute [linear + auto-close], PropertyAccessProfile [cyclic VERIFIED⇄SUSPENDED with reverify loop], VacationWindow [SCHEDULED→APPLIED/CANCELLED], Invoice [branching FINALIZED→{PAID,DISPUTED→RESOLVED}])
- Calculation rules: 6 (`monthly_subscription_fee` tiered+multifamily, `per_visit_charge` PROVISIONAL/FINAL, `vacation_skip_credit` waterfall+round-per-line, `route_load_factor_bp` constraint-propagation, `satisfaction_rolling_score` decay, `addon_bundle_pricing` sanitize+deodorize 15% bundle)
- Validation rules: 20 ordered priorities (auth → existence → state → safety → constraint → temporal → fiscal → referential)
- Endpoints: 69 (includes 3 test-driving `/_clock` and `/_system/*` runners)
- Error catalog: 35 codes (HTTP 400/401/403/404/409/412/422)
- RBAC: 4 roles (Customer entity-backed, Technician entity-backed, OperationsManager opaque, BillingAdmin opaque)
- Concurrency rules: 2 OCC (`subscription-plan-change-stale-version`, `invoice-finalize-stale-version`, both 412 ERR_STALE_VERSION)
- §1.8 instances: 18 (2 per rule × 9 rules; each rule's two instances satisfy §0.5's differentiation clause)
- §1.9 instances: 42 (entities / state_machines / calculations / validations / endpoints / errors / rbac / cross-cutting layers / consistency_model sections)

**Notable harder-than-expert design decisions**:
1. Dual-variant calculations on two different entity domains: `monthly_subscription_fee` (FORWARD_LOOKING vs RECONCILED on Subscription) and `per_visit_charge` (PROVISIONAL vs FINAL on Visit) — pinned divergence with literal assertions (25000 vs 28000; 4000 vs 5500).
2. Combinatorial formulas in two different modes: tiered multifamily multiplier (mode a, 4-input non-linear, 96250c computed literal) and vacation-credit rounding pinned to round-per-line (mode b, 3×-2310=-6930 vs sum-then-round -6928 divergence).
3. Two transitive cascades from distinct triggers: VacationWindowApplier depth-3 (window→visit→route-counters→invoice-line) and Subscription.pause depth-2 (subscription→visits→route-counters).
4. Priority-pair conflicts on different error-category pairs: state-vs-safety (5 vs 7) and constraint-vs-fiscal (10 vs 18).
5. Boundary precision on different metrics/endpoints: route capacity 10000bp `>=` check on `POST /visits` vs empty-set NULL `satisfaction_rolling_avg` on `GET /customers/{id}`.
6. Temporal overlap with different interval semantics: closed-closed on VacationWindow (touching endpoints conflict) vs half-open + 15-min buffer on Visit windows (20-min gap conflicts, 30-min gap does not).
7. Compensating invariants on different conserved quantities: `Customer.credit_balance_cents + Invoice.total_due_cents` and `ServiceRoute.committed_visit_count`.
8. Pre-computed literal asserts throughout (e.g., 96250c multifamily fee, 4605c bundled visit, 4285bp floor(3*10000/7), 3.97 decayed satisfaction) — no unresolved formulas downstream.
9. Default logical clock pinned to `2026-05-01T00:00:00Z` on `POST /api/_clock/set_current_utc` per §1.5 mandatory rule.

Lint verdict pasted verbatim: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

## Step 3: Copy Shared Files — 2026-08-10T09:48:56.000Z

Copied `./INSTRUCTION.md` to `tasks/task_0981_pet_waste_removal_yard_service/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-10T09:56:17.000Z

(Note: the first Step 4 subagent invocation exited after outlining a plan without writing the file; it was resumed via SendMessage and completed the write on the second pass.)

File size grew (48,424 → 49,307) confirming edits landed; line count is coincidentally the same because my edits were single-paragraph replacements. All three contracts pass.

---

## Summary

**File written**: `/home/ubuntu/github/CodingPRD/tasks/task_0981_pet_waste_removal_yard_service/workspace/PRD.md` (332 lines, 49,307 bytes).

**Section list**:
- §1 Introduction (3 paragraphs — system goals / design forces / audience)
- §2 Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control
  - 2.2 API Response Structure (verbatim fixed block)
  - 2.3 Pagination
  - 2.4 Resource Identity and Common Fields
  - 2.5 Money, Precision, and Rounding
  - 2.6 The Logical Clock and Scheduled Actions
  - 2.7 Optimistic Concurrency Control
  - 2.8 Route Capacity and Load Accounting
  - 2.9 Validation Order and Error Discipline
- §3 Business Logic & Workflows
  - 3.1 Onboarding Customers, Yards, and Access Profiles
  - 3.2 Building the Plan and Add-on Catalogue
  - 3.3 Subscriptions: Creation, Activation, Pause, Resume, and Cancel
  - 3.4 Pricing the Monthly Fee
  - 3.5 Routing and Field Execution
  - 3.6 Vacation Windows and Customer-Initiated Skips
  - 3.7 Invoicing and Credits
  - 3.8 Satisfaction Reports and Service Recovery
- §4 Endpoint Definitions (69 endpoints, 4-column table)
- §5 Error Code Catalogue (35 errors, 2-column table)

**Coverage notes**:
- **Contract 1 (Field-Name Coverage)**: PASS — 100 required identifiers, 100 present, 0 missing. Two repair passes were needed: the first draft missed `employee_code`, `invoice_id`, `invoiced_at`, `line_type`; these were added into §3.1 (technician onboarding) and §3.7 (invoice line items) narrative.
- **Contract 2 (Rule Coverage)**: PASS — All 35 error IDs, all 26 state values, and all 51 enum values appear verbatim in backticks. One repair: `TECH_CANNOT_ACCESS` (a Visit `skip_source` enum) was missing and was added to §3.5. All 20 validation rules are enumerated in priority order in §2.9 with their HTTP statuses, error IDs, and exact applies_to scopes. Both OCC rules (subscription plan-change and invoice finalize) are explicitly described in §2.7 and re-anchored in §3.3 / §3.7 with the named `expected_*_version` field, `ERR_STALE_VERSION`, and HTTP 412. All calculation formulas (monthly fee tiering, per-visit amortization, vacation-skip credit waterfall, route load basis points, satisfaction rolling decay, addon bundle discount) are translated to precise business prose with all constants embedded — 4.33/2.17/8.67/30 visits-per-month mapping, 1500 bp bundle discount, 10000 bp full load and multifamily base, 0.9 daily decay, 5.0 resolved-reset rating. All state-machine transitions (Subscription, Visit, ServiceRoute, PropertyAccessProfile, VacationWindow, Invoice, SatisfactionReport) are narrated with from → to state pairs in UPPERCASE, preconditions paired with error IDs, and side effects stated.
- **Contract 3 (§3 Path Purity)**: PASS — 462 backticked tokens in §3 scanned; 0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path combinations.

**Zero-Silence Rule decisions** (places where I had to pick a prose home for a rule with no natural narrative hook):
- The `InvoiceLineItem` exception to common fields (no `updated_at`, no `version`) is stated twice — once in §2.4 (the contract-level statement) and once in §3.7 (the business-narrative reinforcement).
- The `skip_source` enum value `TECH_CANNOT_ACCESS` is declared in §3.5 alongside visit creation, even though no current transition writes it, because the scaffold lists it in the enum constraint.
- Validation priority ordering (item 6, the eight customer-role actions subject to `ERR_ACCOUNT_NOT_ACTIVE`) is enumerated exhaustively as a list in §2.9 — "creating a subscription, activating, pausing, resuming, or cancelling a subscription, creating a vacation window, skipping a visit, filing a satisfaction report" — to avoid the "four independent checks" silent-ordering anti-pattern.
- The `ERR_ROUTE_TECH_MISMATCH` elevation from generic 403 to specific 403 is called out at the end of §2.1 so it isn't lost.
- The bundle discount (1500 bp off the SANITIZE+DEODORIZE pair, rounded once on the pair) is placed inside §3.4 as step 3 of the per-visit charge narrative rather than as a standalone paragraph, preserving the pinned evaluation order.

## Step 5: Generate Unit Tests — 2026-08-10T10:26:12.000Z

## Summary

**Test counts per queue:**
- Queue A (Difficulty): 36 tests across 18 instances (≥2 per instance, all covered)
- Queue B (Corner): 42 tests across 42 non-stub instances (≥1 per instance, all covered)
- **Total: 78 tests**

**Per-instance coverage:**

Queue A — all 18 instances translated with exactly 2 tests each:
- `dual_variant_calc/monthly_fee_forward_looking_vs_reconciled_divergence`
- `dual_variant_calc/per_visit_charge_provisional_vs_final_divergence`
- `combinatorial_formula/monthly_fee_tiered_mode_a_multi_input_nonlinear`
- `combinatorial_formula/vacation_credit_rounding_mode_b_per_line_not_aggregate`
- `non_linear_state_machine/subscription_pause_resume_cycle`
- `non_linear_state_machine/invoice_dispute_resolve_branching`
- `transitive_cascade/vacation_window_applied_depth3_cascade`
- `transitive_cascade/subscription_pause_cascade_visit_cancel_depth2`
- `priority_pair_validation_conflict/state_vs_business_safety_priority_pair`
- `priority_pair_validation_conflict/business_constraint_vs_business_fiscal_priority_pair`
- `boundary_precision_check/route_capacity_at_10000bp_boundary`
- `boundary_precision_check/satisfaction_rating_zero_count_empty_set`
- `cross_entity_state_dependency/subscription_activate_depends_on_access_profile_state`
- `cross_entity_state_dependency/visit_arrive_depends_on_technician_certification_state`
- `resource_temporal_overlap/vacation_window_closed_interval_overlap`
- `resource_temporal_overlap/visit_window_overlap_with_buffer_half_open`
- `compensating_invariant/customer_credit_balance_invariant`
- `compensating_invariant/route_committed_visit_count_invariant`

Queue B — all 42 non-stub instances translated with 1 test each (entities 9, state_machines 6, calculations 5, validations 7, endpoints 4, errors 1, rbac 4, cross_cutting_complexity_layers 5, consistency_model 1).

**Skipped instances:**
- `Corner/errors/error_plan_retired` — stub with `excluded_because:` citing unreachable without a plan-retire endpoint; correctly not translated (0 tests).

**Judgment call:** `Difficulty/resource_temporal_overlap/visit_window_overlap_with_buffer_half_open` — the design instance's literal 20-minute gap (10:20 vs 10:00) does NOT actually intersect `[08:45, 10:15)` under PRD §2.9 item 15's pinned formula, so I used a 10-minute gap (10:10) for the conflict test (PRD-faithful) and added a 30-minute gap test confirming no conflict (boundary precision).

**`test_helpers/` files (9):** `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`

**`test_suite/` files (9):** `conftest.py`, `test_01_pricing.py`, `test_02_subscription_lifecycle.py`, `test_03_routes_and_visits.py`, `test_04_vacation_windows_and_skips.py`, `test_05_invoicing_and_credits.py`, `test_06_entities_and_customers.py`, `test_07_satisfaction_and_visits.py`, `test_08_rbac_and_security.py`

**Self-check results:**
- All 18 files parse as valid Python (ast.parse OK)
- 78 tests, 0 untagged, 0 double-tagged, 0 unresolved tags
- Queue A coverage: 18/18 instances with ≥2 tests
- Queue B coverage: 42/42 non-stub instances with ≥1 test
- Stub `error_plan_retired` correctly has 0 tests
- No `pytest.mark.skip` / `skipif` / `xfail` markers anywhere
- PRD citation verbatim check: 78/78 docstrings contain a quoted phrase that literally appears in PRD.md

All output rooted at `/home/ubuntu/github/CodingPRD/tasks/task_0981_pet_waste_removal_yard_service/test_helpers/` and `/home/ubuntu/github/CodingPRD/tasks/task_0981_pet_waste_removal_yard_service/test_suite/`.

## Step 6: Generate Implementation — 2026-08-10T10:26:12.000Z

Implementation complete and verified. All three smoke suites passed end-to-end (happy path with exact cent-level pricing assertions, cascade/scheduled-action flows, and access-profile/route/tech error paths), and a fresh `bash start.sh` boot was confirmed to start with an empty store and the default logical clock.

**File list** (all under `/home/ubuntu/github/CodingPRD/tasks/task_0981_pet_waste_removal_yard_service/workspace/implementation/`):
- `start.sh` — executable launcher: guards dependency install behind `python3 -c "import flask"`, then `exec python3 app.py`
- `requirements.txt` — `flask>=2.2`
- `app.py` — Flask entry point, blueprint registration, ApiError/404/405/500 envelope handlers; `app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))`
- `db.py` — in-memory `STORE` of 13 empty dicts + UUID/sequence helpers; nothing seeded
- `clock.py` — logical clock pinned at `2026-05-01T00:00:00Z` on boot, ISO-8601 3-fraction-digit formatting/parsing
- `errors.py`, `response.py`, `middleware.py` — ApiError classes, envelope builders (`meta.api_request_id`/`api_request_timestamp` + pagination fields, `response_type`, `data.error_id`/`message`), auth header validation (`X-User-ID`/`X-User-Role`), body/field/enum/pagination validators
- `services.py` — all calculations (tiered monthly fee with round-half-up multifamily multiplier, per-visit charge with 4.33/2.17/8.67/30 amortization and 1500bp SANITIZE+DEODORIZE bundle, vacation-skip credit waterfall with no-over-credit roll-forward, route load factor floor division, 0.9^days decay satisfaction score with RESOLVED-reset-to-5.0), visit generation, cascades, serializers
- `routes/` — `customers.py`, `yards.py` (yards + access profiles), `catalog.py` (plans + addons), `subscriptions.py`, `field.py` (technicians + routes), `visits.py`, `vacation.py`, `billing.py` (invoices + line items), `satisfaction.py`, `system.py` (clock + runners)

**Endpoint count: 69** (matches the scaffold endpoint table exactly, including the 3 test-driving endpoints).

**Logical clock / scheduled-action runners**: `POST /api/_clock/set_current_utc` (OperationsManager) sets the module-level logical clock (default exactly `2026-05-01T00:00:00Z`, never wall-clock) and effectuates pending plan changes whose anchor has passed; `POST /api/_system/vacation-window-applier/run` synchronously applies due SCHEDULED VacationWindows (returns `applied_window_ids`, cascades VACATION skips + VACATION_CREDIT lines); `POST /api/_system/end-of-day-sweep/run` transitions past-window SCHEDULED visits to MISSED (returns `missed_visit_ids`, posts good-will SATISFACTION_CREDIT lines, recomputes route counters).

**OCC**: `version` starts at 1 on creation and increments on every mutation (including cascaded writes to routes, invoices, customers). `POST /api/subscriptions/{id}/plan-change` requires `expected_subscription_version`; `POST /api/invoices/{id}/finalize` requires `expected_invoice_version`; a missing field → 400 `ERR_INVALID_REQUEST`, a mismatch → 412 `ERR_STALE_VERSION`. The OCC check runs before any mutation, so a rejected finalize leaves the invoice untouched.

**`start.sh` confirmation**: reads `$PORT` (via `app.py`, default 10000), binds `0.0.0.0`, and runs the server in the foreground via `exec python3 app.py`; dependency install is guarded so per-test reboots skip pip once Flask is present.

## Step 7: Run Tests and Iterate — 2026-08-10T10:36:54.000Z

## Summary

- **Iterations run**: 2 (initial sweep + post-fix sweep).

- **Tests deleted**: None.

- **Fixes applied to `test_helpers/`**: None.

- **Fixes applied to `test_suite/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_0981_pet_waste_removal_yard_service/test_suite/test_01_pricing.py`:
    - `TestVacationCreditRoundPerLine.test_per_line_credit_value_and_aggregate_sum` — corrected `round_half_up(10000/4.33)` from `-2310` to `-2309` per line and total from `-6930` to `-6927`. `10000/4.33 = 2309.4688…` rounds half-up to 2309 (not 2310).
    - `TestAddonBundlePricing.test_bundle_discount_applied_when_both_present` — corrected expected provisional charge from `4605` to `4604` (2309 base + 2295 bundled).
    - `TestAddonBundlePricing.test_no_bundle_when_only_one_addon` — corrected expected provisional charge from `3810` to `3809` (2309 base + 1500 addon).
  - `/home/ubuntu/github/CodingPRD/tasks/task_0981_pet_waste_removal_yard_service/test_suite/test_04_vacation_windows_and_skips.py`:
    - `TestVacationWindowAppliedCascade.test_cascade_decrements_route_counters_and_posts_vacation_credit` — corrected `unit_price_cents` from `-2310` to `-2309`.
  - `/home/ubuntu/github/CodingPRD/tasks/task_0981_pet_waste_removal_yard_service/test_suite/test_03_routes_and_visits.py`:
    - `TestRouteCapacityAt10000Bp._setup_full_route` — changed `max_visit_capacity` from 2 to 3. PRD §2.9 #16 requires load factor to stay strictly below 10000 bp after adding; with capacity=2 the second visit (which would push load to exactly 10000) is rejected by the PRD-faithful implementation, so setup itself was failing with `ERR_ROUTE_AT_CAPACITY`. With capacity=3, two visits fit (load=6666) and the third is the rejected boundary.
    - `TestRouteCapacityAt10000Bp.test_route_counters_unchanged_after_rejected_assignment` — updated `route_load_factor_bp` assertion from `10000` to `6666` (`2 * 10000 // 3 = 6666` floor division).

- **Fixes applied to `implementation/`**: None — the implementation was already PRD-faithful on every tripped assertion (rounding, capacity floor, cascade shape). The flaky "could not be restarted" setup failures on the three `TestVacationWindowValidation` tests disappeared once the deterministic failures were resolved; they were 8-way parallel boot contention noise, not implementation bugs.

- **Final sweep**: 8/8 rounds × 78/78 passed.

## Step 8: Finalize PRD — 2026-08-10T10:41:30.000Z

# Summary

**PRD_FINALIZED.md is a byte-identical copy of PRD.md** (verified via `diff -q` and matching md5 `ab5299d3d2f93a4f8315b713bf5b9951`). Zero edits were needed: every Step 7 item was a pure test-side fixture bug where PRD.md already uniquely determines the behavior and `implementation/` was already PRD-faithful (Step 7 itself applied no implementation fixes).

## Line counts and %-delta

- `PRD.md`: 332 lines; `PRD_FINALIZED.md`: 332 lines; delta 0 lines, 0.0% (byte-identical).

## Per-Step-7-item analysis (why each needs no PRD edit)

- **§3.6 vacation-credit per-line value (-2309/line, -6927 total)** — Pure fixture bug. PRD §3.6 already pins: "divided by the average visits per month ... (the same 4.33 / 2.17 / 8.67 / 30 mapping ...) rounded half-up to whole cents per line ... quantity 1 and `unit_price_cents` equal to the negated per-visit credit". `round_half_up(10000/4.33) = round_half_up(2309.4688…) = 2309` is the unique result; the test's `-2310` was a miscalculation. Impl: `services.py:79-84` (`rhu(Decimal(snapshot)/Decimal("4.33"))`), `services.py:362-379`, `services.py:257-312`.
- **§3.4 bundle provisional charge (4604)** — Pure fixture bug (consequence of the 2309 base). PRD §3.4 pins base = snapshot/4.33 rounded half-up (2309), bundle pair = `(1500+1200)*8500/10000` rounded half-up once (2295), charge = base + add-on total (4604). Impl: `services.py:97-126`, `services.py:479`.
- **§3.4 no-bundle provisional charge (3809)** — Pure fixture bug; 2309 + 1500 = 3809 is PRD-determined by the same §3.4 sentences.
- **§3.6 cascade `unit_price_cents` -2309 (test_04)** — Same rounding rule as the first item; PRD-determined. Impl path: `routes/system.py:57-63` → `finalize_visit_skip` → `base_per_visit_cents`.
- **§2.9 #16 capacity setup (max_visit_capacity 2→3)** — Pure fixture bug. PRD §2.9 #16 already requires the post-add `route_load_factor_bp` to be "strictly below 10000", and §2.8 says "would reach or exceed 10000" is rejected. With capacity=2 the second visit yields exactly 10000 and is PRD-mandated to fail, so the old test setup was infeasible under the PRD itself. Impl: `routes/visits.py:42-48` (`(committed_after * 10000) // max_visit_capacity >= 10000` → reject), called from create (`visits.py:87`) and assign-route (`visits.py:154`).
- **§2.8 load factor 6666** — Pure fixture bug. PRD §2.8 already pins "multiplied by 10000 and divided by `max_visit_capacity`, computed with integer floor division"; `2*10000//3 = 6666` is unique. Impl: `services.py:136-145`.

## Pre-edit search log

No edits were committed, so per-edit wording adjustments (c) are vacuous. The mandatory enumeration (a)/(b) was performed for each candidate edit subject before deciding against editing:

1. **Subject: vacation-credit per-line rounding.** Impl paths enumerated: `services.py:24-29` (AVG_VISITS constants), `services.py:38-40` (`rhu`), `services.py:79-84` (`base_per_visit_cents`), `services.py:362-379` (`finalize_visit_skip`), `services.py:257-312` (`post_vacation_credit` waterfall), and all credit-posting callsites — `routes/system.py:57-63` (window applier), `routes/visits.py:244-250` (customer skip), plus `routes/subscriptions.py:162,203` (pause/cancel cascades use `cancel_visit_record`, no credit — consistent with PRD §3.3). Every path computes `round_half_up(snapshot / 4.33)` per line with quantity 1 and negated unit price, exactly as PRD §3.6 states. No wording gap found.
2. **Subject: per-visit charge incl. SANITIZE+DEODORIZE bundle.** Impl paths enumerated: `services.py:97-126` (`addon_total_cents`, `per_visit_charge_cents`), `services.py:479` (provisional at create via `create_visit_record`, also used by `generate_visits` at `services.py:441-462`), `services.py:398` (FINAL at completion), `services.py:404-412` (VISIT_CHARGE/ADDON_CHARGE line posting). All compute base = `rhu(snapshot/avg)` then add the add-on total with the 1500 bp pair discount rounded half-up once — PRD §3.4 already pins this evaluation order and rounding. No wording gap found.
3. **Subject: route capacity check and load-factor floor division.** Impl paths enumerated: `services.py:136-145` (`recompute_route`, floor division), `routes/visits.py:42-48` (`_check_capacity`, prospective would-be load `>= 10000` → `ERR_ROUTE_AT_CAPACITY`), callsites `routes/visits.py:87,154`, `routes/visits.py:158-159`, `services.py:369,389,422,489`, `routes/system.py:88`, `routes/field.py:92,155`. All consistent with PRD §2.8 (floor division; reject when load "would reach or exceed 10000") and §2.9 #16 ("strictly below 10000"). No wording gap found.

**Output file**: `/home/ubuntu/github/CodingPRD/tasks/task_0981_pet_waste_removal_yard_service/workspace/PRD_FINALIZED.md` (byte-identical copy of `PRD.md`).

## Step 9: Complete PRD — 2026-08-10T10:58:30.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_0981_pet_waste_removal_yard_service/workspace/PRD_COMPLETED.md` produced as a minimal patch over `PRD_FINALIZED.md`.

**Size delta**
- PRD_FINALIZED.md: 332 lines / 49,307 chars
- PRD_COMPLETED.md: 335 lines / 57,322 chars (+3 lines, +8,015 chars; 31 diff hunks, all in-paragraph inserts/revisions — no new sections)

**Counts: 34 changes total — 27 ambiguity-pins, 7 mismatch-revisions**

- §2.1 — insert — ambiguity — resource-ownership (403) checks pinned as evaluated after path/body id resolution (steps 3–4) and before business rules — middleware.py:109-122 + per-route ownership checks
- §2.2 — insert — ambiguity — undefined path/unsupported method → ERR_NOT_FOUND(404); malformed/non-object JSON body → ERR_INVALID_REQUEST(400) — app.py:21-36
- §2.3 — insert — ambiguity — non-integer/out-of-range limit/offset → ERR_INVALID_REQUEST; created_at ties broken by insertion order; full per-endpoint filter-param catalogue; Customer list scoping + foreign customer_id filter → ERR_UNAUTHORIZED — middleware.py:125-155; routes/*.py list handlers
- §2.4 — revise — ambiguity — version starts at 1 on creation; every mutation refreshes updated_at — services.py:43-56
- §2.6 — insert — ambiguity — clock-set returns data.current_utc; advancing the clock applies due staged plan changes — system.py:13-27
- §2.7 — insert — ambiguity — expected-version check evaluated after state-validity, before remaining business rules — subscriptions.py:219-223; billing.py:132-139
- §3.1 — revise — ambiguity — duplicate email → ERR_INVALID_REQUEST; duplicate employee_code → ERR_INVALID_REQUEST; inactive technician blocks route publication (no visit-assignment mechanism exists) — customers.py:18-20; field.py:32-34,151-154
- §3.1 — insert — ambiguity — out-of-range yard_size_sqft/pet_count → ERR_INVALID_REQUEST — yards.py:23-27
- §3.1 — revise — ambiguity — service_region_code required at yard creation — yards.py:51
- §3.1 — revise — mismatch+ambiguity — dropped "held encrypted at rest" (stored/returned plaintext); pinned gate_access_code/gate_instructions/pet_on_premises all required; second profile on same yard → ERR_INVALID_REQUEST — yards.py:151-170; services.py:563-576
- §3.1 — insert — ambiguity — yard updates are partial; HOA requirement evaluated on merged post-update state — yards.py:116-126
- §3.2 — insert — ambiguity — plan-definition validation pinned: strictly ascending thresholds, surcharges exactly one longer than thresholds (pet tiers too — PRD previously stated the +1 rule only for yard tiers), non-negative base fee, unique plan_code, all → ERR_INVALID_REQUEST — catalog.py:22-37,54-60
- §3.2 — insert — ambiguity — unique addon_code and non-negative price → ERR_INVALID_REQUEST — catalog.py:107-111
- §3.3 — revise — ambiguity — activation requires an existing VERIFIED profile; generated-visit cadence pinned (begin on current date; 7/14-day, alternating 3/4-day floor(7k/2), daily offsets; stop before anchor; 08:00–17:00 UTC windows; no route/add-ons) — subscriptions.py:125-139; services.py:429-462
- §3.3 — revise — ambiguity — resume requires an existing VERIFIED profile — subscriptions.py:176-179
- §3.3 — revise — ambiguity — plan change stageable from any non-CANCELLED status (incl. DRAFT); staged plan's plan_status unchecked; DRAFT anchor falls back to first-of-next-month; swap applied lazily on clock-set/subscription read, clears pending fields, recomputes snapshot only when ACTIVE, bumps version — subscriptions.py:211-232; services.py:503-522
- §3.4 — revise — ambiguity — addon_ids de-duplicated before resolution — services.py:87-103
- §3.4 — revise — mismatch — dropped "add-ons added after scheduling are included" (no endpoint can modify a visit's add-ons); FINAL charge recomputed from add-ons attached at completion — services.py:393-399
- §3.5 — revise — mismatch — route_code unique per service_date (not globally); service_date stored as supplied, not forced to UTC midnight; max_visit_capacity < 1 → ERR_INVALID_REQUEST — field.py:63-82
- §3.5 — revise — ambiguity — unpublish while EN_ROUTE/ON_SITE → ERR_INVALID_STATE(409) — field.py:170-173
- §3.5 — revise — ambiguity — window-conflict scan considers only non-terminal visits — visits.py:27-39
- §3.5 — insert — ambiguity — reassignment excludes the visit itself from conflict scan; same-route reassignment adds no capacity delta — visits.py:150-154
- §3.5 — revise — mismatch — ack-safety allowed from SCHEDULED or EN_ROUTE, not only "while en route" — visits.py:188
- §3.5 — revise — mismatch — skip_source rewritten: set on SKIPPED (VACATION/CUSTOMER_REQUEST) and MISSED (OTHER), also stamped CUSTOMER_REQUEST on cascade-cancelled visits; direct single-visit cancel leaves it null — services.py:362-390; subscriptions.py:156-162,198-203; visits.py:254-265; system.py:82-84
- §3.5 — revise — ambiguity — route auto-close check runs on every visit terminal transition (complete, skip, miss, cancel), not only completion — services.py:148-155
- §3.5 — revise — ambiguity — sweep good-will SATISFACTION_CREDIT pinned at unit_price_cents 0, posted to covering OPEN invoice else new calendar-month invoice — system.py:90-100
- §3.6 — revise — ambiguity — direct skip only from SCHEDULED (else ERR_INVALID_STATE) — visits.py:231-232
- §3.6 — revise — mismatch — waterfall corrected: credits on charge-carrying invoices capped at running subtotal, but credits-only invoices post in full (can go negative, contra "never push an invoice negative"); new invoice period = calendar month of skipped date; "next OPEN invoice" = earliest billing_period_start after covering period start, created [period_end, next month boundary) when absent; one skipped visit may yield several split VACATION_CREDIT lines — services.py:257-312
- §3.7 — revise — mismatch — VISIT_CHARGE carries base per-visit amount; ADDON_CHARGE lines carry full price (bundle discount never hits invoices); visit_id is NOT unique per invoice (visit-derived lines share it); invoiced_at stamped only at completion, not by credit lines; SATISFACTION_CREDIT sources pinned (dispute resolution + zero-amount sweep) — services.py:393-423,226-244
- §3.7 — insert — ambiguity — proration pinned: one SUBSCRIPTION_FEE_PRORATED line per ACTIVE subscription with started_on; quantity = days from max(period_start, started_on) to period_end exclusive (skipped when ≤ 0); unit price = fee ÷ period days, rounded half-up per day — billing.py:142-169
- §3.7 — revise — ambiguity — resolve-dispute: next OPEN = earliest period start after disputed period; created invoice spans disputed period_end → next month boundary — billing.py:225-233; services.py:191-201
- §3.8 — insert — ambiguity — filing pins: referenced visit must belong to filer (ERR_UNAUTHORIZED), any visit status allowed, rating outside 1–5 → ERR_INVALID_REQUEST, filing immediately recomputes satisfaction_rolling_avg — satisfaction.py:37-48,62-63
- §3.8 — insert — ambiguity — resolve valid only as UNDER_REVIEW+OperationsManager or ESCALATED+BillingAdmin; other combos → ERR_INVALID_STATE — satisfaction.py:129-135
- §5 — insert — ambiguity — added missing catalogue row `ERR_GATE_CODE_REQUIRED | 422` (error was used in §3.1 prose and impl but absent from the table) — yards.py:208-210

Behaviors verified as already uniquely pinned by the PRD (no change): monthly-fee tier math, per-visit charge formula and bundle rounding, route load-factor accounting and capacity rule, validation priority order 1–20, all state-machine from-states except those noted, activation precondition order, pause/cancel cascades, vacation-window validity/overlap/cancel rules, finalize totals math, payment/dispute flow, satisfaction decay formula, endpoint table roles, and all other catalogue error codes.
