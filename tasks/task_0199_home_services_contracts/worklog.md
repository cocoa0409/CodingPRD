# Worklog — task_0199_home_services_contracts

Scenario: Home Services Contracts (HVAC/Pest): service agreement/membership plan, seasonal recurring visits, dispatch/route, equipment/site history, parts/refrigerant tracking, warranty, renewal/auto-renew, priority-service SLA

## Step 1: Create task directory — 2026-06-06T13:04:00.000Z

Created pre-allocated directory `tasks/task_0199_home_services_contracts/` with `workspace/` subdirectory. Auto-increment scan skipped per orchestration parameters (index 0199 pre-allocated to avoid collision with 4 concurrent pipelines).

## Step 2: Generate scaffold (Expert difficulty) — 2026-06-06T13:25:00.000Z

All three artifacts are complete, parse cleanly, and pass the scaffold linter.

**Complexity profile:** primary archetype temporal_windowing + secondary compliance_audit; flat topology; cyclic state-machine shape; peer_roles; immediate consistency. Layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers.

**Scaffold contents:**
- **Entities: 11** — ServicePlan, Customer, Site, Membership, Equipment, Technician, ServiceVisit, RefrigerantLog, PartUsage, WarrantyClaim, RenewalOffer.
- **State machines: 5** — Membership (renewal cycle ACTIVE↔RENEWAL_PENDING), ServiceVisit (reschedule self-loop + recall revert), WarrantyClaim (approve/deny fork-join), Equipment (parallel operational × warranty axes), RenewalOffer (branching accept/auto-accept/decline/expire).
- **Concurrency rules: 2** — both OCC on `Membership.version` (visit-create, renewal-offer-create), 412.
- **Calculations: 5** — VisitChargeAssessment (threshold, seasonal-overage vs priority-out-of-plan variants), WarrantyClaimSettlement (partial vs full credit), PartChargeRounding (round-per-line-then-sum, order pinned), SlaEvaluation (inclusive `<=` boundary), RefrigerantMassBalance (running accumulator + conserved-mass invariant).
- **Validations: 21** priority-ordered (auth → ownership → existence → request shape → referential → state → safety → constraint → temporal → fiscal/OCC).
- **Endpoints: 58** (incl. FK reverse-reachability GETs + `/_clock/set_current_utc` and `/_clock/advance` test-driving endpoints).
- **Error catalog: 21** codes.
- **Roles: 4** — ContractAdmin (opaque), Dispatcher (opaque), Technician (entity_backed:Technician), Customer (entity_backed:Customer).

**Design instance counts:**
- §1.8 Difficulty: **18 instances** = all 9 rules × 2 each (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).
- §1.9 Corner: **47 instances** = 42 active + 5 `excluded_because` stubs.

**Verification:** `scaffold_lint.py` returns `VERDICT: clean lint` (589 calls scanned; all FKs have reverse-reachability GETs; all numeric assertions precomputed and pinned). One correction: cert-vs-state priority-pair instance re-grounded from state (priority 8) to business_referential (priority 7).

## Step 3: Copy shared files — 2026-06-06T13:27:48.000Z

Copied `INSTRUCTION.md` → `tasks/task_0199_home_services_contracts/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-06T13:34:20.000Z

Generated PRD at `workspace/PRD.md`. **Structure:** 5 top-level sections, 20 `###` subsections, 295 lines.
- §1 Introduction; §2 Global Specs (9 subsections: RBAC, Response Structure, Pagination, Common Resource Properties, Hierarchical Consistency & reverse-reachability, Monetary/Mass Precision, Customer Ledger Principle, OCC, Validation Ordering); §3 Business Logic (11 subsections); §4 Endpoint table (all 58 endpoints); §5 Error catalogue (all 21 error IDs).

**Hard Contract reports (all PASS):** Contract 1 Field-Name Coverage 61/61; Contract 2 Rule Coverage (validations, 2 OCC rules, 5 state machines, 5 calculations, 21 error IDs, cascades) 0 missing; Contract 3 §3 Path Purity (413 backtick tokens, 0 paths/methods leaked).

**Notable coverage decisions:** both OCC rules use `expected_membership_version`/`ERR_STALE_VERSION`/412 (consolidated in §2.8); `ERR_VALIDATION` placed as catch-all in §2.9; `visits_consumed` derived-on-read + completion-does-NOT-bump-version stated in §2.5 and §3.8. Design YAMLs not opened.

## Step 5: Generate unit tests — 2026-06-06T13:53:51.000Z

**test_helpers/ (9 files):** types.py, api_client.py, api_errors.py (21-error catalog), assertions.py, factories.py, constants.py (LOW_CHARGE_RATIO=0.10), test_users.py (opaque ContractAdmin/Dispatcher + per-instance make_technician_headers/make_customer_headers + NO_AUTH_HEADERS), fixtures.py (5-tier composite setup), __init__.py.

**test_suite/ (conftest + 7 test files, 76 test functions):** organized by domain — charge/ledger, refrigerant/equipment, membership lifecycle, warranty claims, dispatch/scheduling, membership-anchored creates, entities/RBAC/listing.

**Coverage (design-index-only):**
- Difficulty queue (§1.8): 18 instances → **17 translated** (≥2 tests each, 34 difficulty-tagged tests), **1 skipped**.
- Corner queue (§1.9): **42 non-stub instances → all 42 translated** (1 test each). 5 `excluded_because:` stubs not translated (all resolve to real difficulty instances).

**Notable skip:** `Difficulty/priority_pair_validation_conflict/dispatch_region_trade_business_constraint_beats_double_booked_business_temporal` — skipped under validation-priority silence pattern: asserts `ERR_TECH_REGION_TRADE_MISMATCH` wins over `ERR_TECH_DOUBLE_BOOKED`, but PRD §2.9 orders only categories (referential, safety, temporal, fiscal), placing no precedence between business_constraint and business_temporal → not uniquely derivable. (Sibling `refrigerant_post_visit_state_referential_beats_cert_safety` kept — PRD §2.9 explicitly orders referential before safety.)

All files parse; full package imports; every PRD citation verified verbatim; every docstring ends with exactly one `Design:` tag; no skip/xfail.

## Step 6: Generate implementation — 2026-06-06T13:53:51.000Z

Generated Python + Flask implementation in `workspace/implementation/` (12 files). Fresh boot verified `total_count: 0` (no seeding). In-memory dicts only; no persistence.

**Files (12):** start.sh (foreground, reads $PORT default 10000, binds 0.0.0.0, exec python3 app.py), requirements.txt (flask==3.0.3), app.py, routes_extra.py, db.py (in-memory + logical UTC clock), models.py, services.py, common.py, lookups.py, middleware.py (X-User-ID/X-User-Role auth + role gate), response.py, errors.py.

**Endpoints: 59 implemented** (full PRD §4 table — CRUD, every state-transition action, sub-resource lists, both `_clock` operations).

**Verified behaviors:** response envelope, pagination, validation precedence (401→403→ownership→404→400→business), OCC (412), fee accrual on activate/renew, round-half-up per-line part charges, seasonal allowance vs overage, PRIORITY SLA inclusive boundary + breach-still-created, double-booking half-open, daily-capacity calendar bucketing, refrigerant mass-balance both directions, deep-recovery cascade to NEEDS_SERVICE, derived visits_consumed (no version bump), warranty lifecycle, renewal manual + clock-driven auto-accept/auto-expire, no-show clock guard, decommission evacuation guard, warranty-expiry-on-read, ledger entries omitting version/updated_at.

**PRD ambiguities resolved:** (1) internal non-serialized `completed_at` (logical-clock instant) for term-window predicate; (2) mark-no-show clock guard → `ERR_INVALID_STATE` (409, state precondition, no dedicated code); (3) clear-service recharge guard → `ERR_INVALID_STATE`; (4) technician acting on unassigned visit → reused `ERR_NOT_RESOURCE_OWNER` (403, closest catalogued ownership code).

## Step 7: Run tests and iterate to PASS — 2026-06-06T13:59:17.000Z

**Final state: 8/8 parallel rounds at 76/76.**

**Iterations run:** 2 (initial sweep + 1 fix sweep).

**Tests deleted:** None.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `test_suite/`:** None.

**Fixes applied to `implementation/`:**
- `routes_extra.py`, `create_offer` handler (POST `/memberships/{id}/renewal-offers`): reordered the two guard checks so the open-offer guard (rejects with `ERR_OFFER_ALREADY_OPEN` when an offer in `PENDING`/`ACCEPTED`/`AUTO_ACCEPTED` exists) now precedes the membership-`ACTIVE` state gate (`ERR_INVALID_STATE`).

**Diagnosis:** Single consistent failure `test_second_open_renewal_offer_rejected` (failed in all 8 original rounds) expected `ERR_OFFER_ALREADY_OPEN` but got `ERR_INVALID_STATE`. Original code checked membership-`ACTIVE` first; since creating an offer atomically flips `ACTIVE → RENEWAL_PENDING`, a `PENDING` offer can never coexist with an `ACTIVE` membership, so `ERR_OFFER_ALREADY_OPEN` was unreachable for the `PENDING` case. PRD line 142 verbatim enumerates `PENDING` in the open-offer set and states a second open offer is rejected with `ERR_OFFER_ALREADY_OPEN` — uniquely requiring the open-offer guard to take precedence (STEP 1 coverage + unique-derivability pass; STEP 2 test confirmed faithful). No regression in stale-version or other renewal-offer paths.

## Step 8: Finalize PRD — 2026-06-06T14:02:29.000Z

Produced `workspace/PRD_FINALIZED.md`. PRD.md = 295 lines; PRD_FINALIZED.md = 295 lines (0-line delta; one line revised in place within §3.4).

**Change (1 bullet):**
- §3.4 (Seasonal Rhythm: Renewal Offers) — insert — pinned the precedence of the open-offer guard over the membership-`ACTIVE` state gate in renewal-offer create: `ERR_OFFER_ALREADY_OPEN` surfaces before `ERR_INVALID_STATE`, explicitly overriding §2.9's generic state-gate-first ordering for this one operation — `routes_extra.py:174-182`.

**Why genuine PRD pin:** §2.9 establishes generic state-gate-first ordering (ERR_INVALID_STATE before remaining business rules); a fresh implementer would check ACTIVE first and produce ERR_INVALID_STATE for the PENDING case, diverging from impl. §3.4 enumerated PENDING in the open-offer set but did not state the local precedence override. Inserted clause pins it.

**Pre-edit search log:** (a) subject = precedence between open-offer guard and membership-ACTIVE gate in renewal-offer create. (b) enumerated routes_extra.py create_offer (only callsite raising ERR_OFFER_ALREADY_OPEN), services.py accept_offer/lapse_offer/advance_clock, routes_extra.py accept/decline/cancel — confirmed PENDING offer only coexists with RENEWAL_PENDING membership; ACCEPTED/AUTO_ACCEPTED coincide with ACTIVE (both orderings agree). (c) scoped override to "this create only" so §2.9 generic ordering intact elsewhere; left stale-version guard ordering untouched.

## Step 9: Complete PRD — 2026-06-06T14:11:52.000Z

Produced `workspace/PRD_COMPLETED.md` from `PRD_FINALIZED.md`. 295 lines → 295 lines (in-paragraph inserts only); char delta **+3,204** (47,470 → 50,674 chars).

**Counts:** 11 changes total — **11 ambiguity-pins, 0 mismatch-revisions** (impl never contradicted PRD prose; every gap was a silence impl resolved one way).

**Per-change bullets:**
- §2.1 (RBAC) — insert — ambiguity — pinned per-resource Customer ownership-chain resolution incl. warranty-claim chain equipment→site→customer — `lookups.py:61-85`, `routes_extra.py:663`
- §2.1 (RBAC) — insert — ambiguity — pinned Customer list endpoints auto-scope to owned resources on top of query filters — `app.py:202-203`, `routes_extra.py:87-88,242-244,674-676`
- §2.3 (Pagination) — insert — ambiguity — pinned silent clamping of out-of-range limit/offset + ERR_INVALID_REQUEST for non-integers — `common.py:149-168`
- §2.3 (Pagination) — insert — ambiguity — pinned created_at tie-break by ascending creation sequence — `common.py:180`
- §2.9 (Validation ordering) — insert — ambiguity — pinned per-field numeric-range constraints surface as ERR_INVALID_REQUEST not ERR_VALIDATION fallback — `common.py:37-54`, `routes_extra.py:541,612`
- §3.2 (Customers) — insert — ambiguity — pinned ERR_INVALID_REQUEST for duplicate-email creates — `app.py:144-146`
- §3.3 (Term lifecycle) — insert — ambiguity — pinned ERR_INVALID_STATE for activation against a retired plan — `app.py:98-100`
- §3.5 (Booking/routing) — insert — ambiguity — pinned ERR_INVALID_STATE for mark-no-show before clock reaches window_end — `routes_extra.py:478-479`
- §3.6 (Dispatch safety) — insert — ambiguity — pinned daily-capacity guard evaluated only against visit's technician, excludes own count, skipped when no tech — `routes_extra.py:307-308,355-357,506-520`
- §3.7 (Refrigerant) — insert — ambiguity — pinned ERR_INVALID_REQUEST when equipment site_id ≠ visit site_id — `routes_extra.py:543-545`
- §3.9 (Equipment service) — insert — ambiguity — pinned ERR_INVALID_STATE for clear-service below 10% recharge threshold — `app.py:268-269`
- §3.11 (Test clock) — insert — ambiguity — pinned persisted timestamps come from logical clock while meta.api_request_timestamp is wall-clock; clock defaults to wall-clock until set — `models.py:77,91`, `db.py:47-65`, `response.py:18`

Already-pinned (no change): SLA inclusive boundary, per-line round-half-up, deep-recovery <10% vs clear-service ≥10%, half-open overlap, reschedule re-running window/capacity/SLA only, settlement crediting exactly approved_amount_cents, entity field shapes.

---

## Pipeline complete — 2026-06-06T14:11:52.000Z

All 9 steps finished. Final test state: **8/8 parallel rounds at 76/76**. Deliverables present: SCAFFOLD.yaml (+ DIFFICULTY/CORNER design), workspace/{PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, INSTRUCTION.md, implementation/}, test_helpers/, test_suite/, worklog.md.
