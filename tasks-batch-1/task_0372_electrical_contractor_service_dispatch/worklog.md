# Worklog — task_0372_electrical_contractor_service_dispatch

## Step 1: Create task directory — 2026-06-16T08:02:00.000Z

Created `tasks/task_0372_electrical_contractor_service_dispatch/` and `workspace/` subdirectory using the pre-assigned path (no auto-index scan, per orchestration args). Verified project root contains `INSTRUCTION.md` and `skills/`.

## Step 2: Generate scaffold (Expert tier) — 2026-06-16T08:25:00.000Z

Scaffold generated in two passes (first scaffold-generator subagent wrote SCAFFOLD.yaml then died on a socket error before the design files; a second fresh subagent generated the two design-index files from the complete SCAFFOLD.yaml on disk).

SCAFFOLD.yaml (979 lines, Expert tier): domain `electrical-contractor-dispatch`, api_prefix `/v1`. complexity_profile primary_archetype "Quota / allocation" (truck-stock + dispatch-slot allocation), secondary "Pricing engine" (flat-rate vs time-and-materials). Layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation. §1.1–§1.7 keys all present: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles. Roles include Dispatcher, Technician, Inspector (opaque identity). Neither design key present (correct).

SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8, single key `scaffold_difficulty_design`): **18 instances** across all 9 Difficulty Rules × 2 each (Expert minimum): dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant. Formula-derived asserts computed against §1.3 formulas/constants and written as literals (e.g. member-TM invoice total==32767; discount half-up 4062.5→4063; quote-vs-actual 40500≠36148).

SCAFFOLD_CORNER_DESIGN.yaml (§1.9, single key `scaffold_corner_design`): **65 instances** across 9 claim-extraction-guide sections: entities(13), state_machines(10), calculations(10), validations(15), endpoints(5), errors(3), rbac(3), cross_cutting_concerns(5), consistency_model(1). 51 full test-recipe instances + 14 `excluded_because:` stubs citing §1.8 instances.

Verification: scaffold_lint.py clean (598 calls scanned, all §1.5-conformant; all §1.1 FKs reverse-reachable); all grounds[] references resolve; all instance names unique across both files. Note from generator: retargeted one cross-entity instance off a structurally-unreachable INVOICED→CLOSED ERR_OPEN_CALLBACK trigger to the reachable Callback→Job dependency; flagged a latent scaffold tension (the `(re)INVOICED` warranty-loop note vs the single-invoice precondition) — worked around, SCAFFOLD.yaml not modified.

## Step 3: Copy shared files — 2026-06-16T08:33:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-16T08:40:00.000Z

Output: `workspace/PRD.md` (~275 lines). Sections: §1 Introduction (business context + four-role framing); §2 Global Specs (2.1 RBAC, 2.2 API Response Structure, 2.3 Pagination, 2.4 Resource Identity/Timestamps/Versioning, 2.5 Optimistic Concurrency on Job-Scoped Creates, 2.6 Validation Order and Precedence [priority 1–15], 2.7 Nested Resource Resolution, 2.8 Monetary Precision and Rounding [round-then-sum, half-up], 2.9 Logical Clock); §3 Business Logic 3.1–3.10 (catalog provisioning, truck stock, opening/quoting, accept→dispatch, field visit/completion, permits/inspections, invoice calc, warranty/callback loop, cancellation cascades, dispatch queue ranking); §4 Endpoint Definitions (58-row table); §5 Error Code Catalogue (17 rows).

Hard contracts PASS: Contract 1 Field-Name Coverage (58/58 entity fields, 32/32 endpoint identifiers); Contract 2 Rule Coverage (2/2 OCC, all state-machine transitions w/ preconditions+error_ids+cascades, all calcs reconstructible with constants 12000/8900/15000/0.0825/30-day embedded); Contract 3 §3 Path Purity (0 path tokens, 0 bare HTTP methods in §3 prose). Confirmation: neither design file nor any sibling task was read.

## Step 5: Generate unit tests — 2026-06-16T09:00:00.000Z

Test files: 9 (1 conftest + 8 test_*.py). Total tests: 89 — Queue A (Difficulty) 36, Queue B (Corner) 53.
- test_01_provisioning_crud.py (18) — entity CRUD, defaults, computed/system fields, input validation
- test_02_pricing_and_invoice.py (16) — dual-mode quote vs invoice, round-then-sum, pinned eval order, void-excludes-money, calc corners
- test_03_dispatch_scheduling.py (11) — half-open overlap, reschedule recheck, adjacency boundary, zone/on-call/OCC gating, dispatch queue ranking
- test_04_stock_and_materials.py (4) — stock-floor boundary, usage→void conservation
- test_05_job_lifecycle_state.py (21) — warranty cyclic loop, permit re-inspection loop, accept/cancel cascades, cross-entity permit & callback gates, valid/invalid transitions, terminal lockdown
- test_06_priority_and_permits.py (8) — both priority-pair conflicts (state>permit, license>overlap), single-invoice, warranty-coverage, existence>state
- test_07_authz_and_concurrency.py (7) — OCC stale-version on estimate, 401/403/404 ownership, RBAC peer-roles
- test_08_listing_and_uniqueness.py (4) — FK-reverse filtered reads, email/sku_code uniqueness

Coverage (audit-verified): all 18 difficulty instances → exactly 2 tests each (36); all 52 non-stub corner instances → ≥1 test each (one got 2 for member-present/null branches); 13 corner `excluded_because:` stubs not translated (their cited §1.8 instances own the assertion, all cross-refs resolve). Instances skipped: 0 — all have verbatim PRD coverage + unique derivability. Integrity: every test has exactly one Design: line; no skip/xfail; all 89 collect; framework signatures read from runner source. test_helpers (9): __init__, types, api_client, api_errors, assertions, factories, constants, test_users (per-instance make_customer_headers/make_technician_headers for the two entity_backed roles), fixtures. Note: suite uses PRD-declared `POST /v1/_clock/set` logical clock for warranty/callback determinism; OCC tests control versions explicitly.

## Step 6: Generate implementation — 2026-06-16T09:00:00.000Z

27 .py files + start.sh + requirements.txt in workspace/implementation/. Foundation: app.py, db.py (in-memory store + common-field stamping/versioning), response.py, errors.py, middleware.py (auth/RBAC), helpers.py (validation, pagination, round_half_up, serialization), clock.py. Services: services/domain.py (constants DEFAULT_HOURLY_RATE=12000, DISPATCH_FEE=8900, EMERGENCY_SURCHARGE=15000, TAX_RATE=0.0825, WARRANTY_DAYS=30), services/billing.py (7-step pinned-order invoice, round-then-sum). 15 route modules. Endpoint count: 58 (matches PRD §4). Storage: pure in-memory module-level dicts in db.py keyed by UUID + monotonic _seq for created_at-ASC tie-break (stripped from responses); no seeding, no disk — verified boot1=1 customer → restart → boot2=0. start.sh reads $PORT (default 10000), binds 0.0.0.0, foreground via `exec python3 app.py`, guards pip install behind import check.

Reconciliation note from impl-gen: PRD §3.4 says dispatch-create requires a QUOTED job, but §3.8's warranty loop + scaffold's WARRANTY→IN_PROGRESS arrive edge are only reachable if a WARRANTY job can be re-dispatched; impl allows dispatch creation from QUOTED **or** WARRANTY (only QUOTED bubbles to SCHEDULED; WARRANTY stays until arrive). Flag for Step 7/8/9 alignment review.

## Step 7: Run tests and iterate — 2026-06-16T09:10:00.000Z

All 8 parallel rounds passed cleanly (89/89 each). Benchmark stable. Orchestrator independently re-ran a confirming 8-round parallel sweep: rounds 1–8 all passed=89 failed=0 total=89; results.{1..8}.json regenerated in workspace/implementation/.

**Iterations run:** 2 sweeps (1 diagnostic 8-round sweep surfaced 50 union failures, then 1 confirming 8-round sweep after fixes — all 8 rounds 89/89; one intermediate single-round check used for fast feedback).

**Tests deleted:** None. Every failing test traced to a verbatim PRD rule with a uniquely-determined outcome; all failures were genuine implementation bugs or test-setup bugs, not PRD-silence/collapse cases.

**Fixes applied to `implementation/`:**
- `services/domain.py` — `job_zone()`: was returning the full `service_zip` (e.g. "10001"); PRD §3.1/§3.4/§3.10 define the zone as the customer's `service_zip` **prefix**. Changed to return `service_zip[:3]`. Dominant root cause (~45 of 50 failures cascaded through dispatch creation, scheduling, completion, invoicing, warranty, dispatch-queue — all gate on zone match). Tests use 5-char zips with 3-char zones.
- `routes/service_jobs.py` — `invoice_job()`: reordered single-invoice guard to reconcile PRD §3.7 (re-invoicing a job with an existing invoice → ERR_ALREADY_INVOICED) with §3.8 (warranty work can be re-invoiced). Now: COMPLETED job always invoices (allowing warranty re-invoice); non-COMPLETED job with existing invoice → ERR_ALREADY_INVOICED, else ERR_INVALID_STATE.

**Fixes applied to `test_suite/` (test-setup bugs, made more PRD-faithful):**
- `test_05_job_lifecycle_state.py` — `test_cascade_estimate_accept_supersede_chain` & `test_cascade_estimate_accept_copies_time_materials_pricing_mode`: second estimate's `expected_job_version` sourced from `estA["version"]` (=1) instead of live job version; per PRD §2.5 estimate creation bumps the parent job version. Changed to `current_job_version(job["id"])`.
- `test_05_job_lifecycle_state.py` — `test_cascade_job_cancel_from_scheduled_supersedes_estimate`: customer `service_zip="51002"` (prefix "510") didn't match technician `service_zone="511"` → ERR_ZONE_MISMATCH in setup. Changed zip to "51102".
- `test_08_listing_and_uniqueness.py` — `test_fk_reverse_estimates_by_job`: same estimate-version-as-job-version bug; changed `v1 = est1["version"]` to `current_job_version(job["id"])` and added import.

**Fixes applied to `test_helpers/`:** None.

No PRD-required implementation checks weakened; no endpoints/fields/side-effects added; storage remains in-memory only.

## Step 8: Finalize PRD — 2026-06-16T09:20:00.000Z

Not skipped (Step 7 had 2 impl fixes + 4 test_suite fixes). Output: `workspace/PRD_FINALIZED.md`. PRD.md=275 lines; PRD_FINALIZED.md=275 lines (2 lines revised in place, 0 added/removed; ~+620 chars; 0% line delta).

Changes:
- §3.1 — revise — Pinned routing zone as the leading 3 chars of customer's `service_zip`; clarified technician `service_zone` and dispatch-queue `zone` query param are compared for exact equality against that 3-char zone (stored/supplied as-is, not themselves truncated) — services/domain.py:30 (consumed at routes/dispatches.py:92, routes/dispatch_queue.py:48).
- §3.7 — revise — Reconciled single-invoice guard with warranty re-invoice path: COMPLETED job always invoiced (even with prior invoice → further invoice); non-COMPLETED + existing invoice → ERR_ALREADY_INVOICED, else ERR_INVALID_STATE; softened "one per job" to "an Invoice for the job" since warranty re-invoicing accumulates multiple invoices — routes/service_jobs.py:179-183 (+ :195-198, routes/invoices.py).

The two test_suite fixes (estimate-version, zip-prefix in setup) traced to behavior PRD already determines verbatim (§2.5 estimate creation bumps parent job version; §3.4 zone-prefix matching), so required no PRD edits. NO-NEW-MISMATCH pre-edit search performed for both edits (zone-prefix applies only to customer service_zip not technician/query values; invoice wording softened to allow multi-invoice warranty path consistent with invoices.py).

## Step 9: Complete PRD — 2026-06-16T09:30:00.000Z

Always runs. Source PRD_FINALIZED.md → output `workspace/PRD_COMPLETED.md`. 275 → 275 lines (all in-paragraph edits, no lines added/removed; +3,795 chars). 12 changes: 10 ambiguity-pins, 2 mismatch-revisions.

Changes:
- §2.1 RBAC ownership — insert — ambiguity — ERR_NOT_RESOURCE_OWNER/ownership applies only to mutating actions; GET-single and list never ownership-scoped — routes/customers.py:44, service_jobs.py:92,102, memberships.py:50,60.
- §2.3 Pagination — insert — ambiguity — list-ordering tie-break for equal created_at = insertion order — helpers.py:121-125, db.py:79.
- §3.2 Truck stock — insert — ambiguity — opening quantity_on_hand/reorder_threshold non-negative ints (may be 0); ">0" rule only for quantity/add_quantity — routes/truck_stock.py:39-43,94.
- §3.2 Material balances — insert — ambiguity — missing truck-stock item treated as 0 on-hand → usage rejected ERR_INSUFFICIENT_STOCK — routes/material_usages.py:58-61.
- §3.3 Job creation — insert — ambiguity — multiple ACTIVE memberships → earliest-created snapshotted — services/domain.py:33-45.
- §3.3 Estimate fields — insert — ambiguity — estimated_material_cents optional (default 0); unsupplied mode-irrelevant inputs persisted as 0; estimate-create has no job-state precondition beyond version check — routes/estimates.py:66-104.
- §3.3 Quote rate — revise — ambiguity — quote-time technician = latest non-CANCELLED dispatch's technician — routes/estimates.py:24-36.
- §3.4 Dispatch preconditions — insert — ambiguity — bullet checks resolve in §2.6 precedence (state→license→on-call→zone→double-booking) — routes/dispatches.py:79-97.
- §3.4 Dispatch state — revise — mismatch — "must be QUOTED" → allow QUOTED (→SCHEDULED) or WARRANTY (stays WARRANTY) — routes/dispatches.py:79-114.
- §3.5 Material usage — insert — ambiguity — no job-state precondition on recording a usage; re-voiding a voided line → ERR_INVALID_STATE — routes/material_usages.py:28-61,127-128.
- §3.5 Completion — revise — mismatch — actual_labor_hours optional, treated as 0 when omitted — routes/service_jobs.py:132-153, services/billing.py:33.
- §3.7 Labor subtotal — insert — ambiguity — invoice technician = latest non-CANCELLED dispatch's technician, rate 0 if none — routes/service_jobs.py:41-46,192, services/billing.py:34.
- §3.8 Callback filing — insert — ambiguity — ERR_INVALID_STATE for filing against non-INVOICED/CLOSED job (precedes warranty check); persisted callbacks always covered_by_warranty true — routes/callbacks.py:40-55.
- §3.10 Dispatch queue — insert — ambiguity — zone required (missing/empty → ERR_INVALID_REQUEST), exact-string match, ranking replaces default ordering under standard pagination — routes/dispatch_queue.py:36-62.

Step 9 edits only PRD_COMPLETED.md; implementation/ and tests unchanged from the verified passing Step 7 state (8/8 rounds 89/89). results.{1..8}.json present.

---

## Pipeline complete — 2026-06-16T09:30:00.000Z

All 9 steps done. Final state: 89 tests, 8/8 parallel rounds passing (89/89 each). Artifacts: SCAFFOLD.yaml + 2 design files, worklog.md, test_helpers/ (9 files), test_suite/ (9 files, 89 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ (27 .py + start.sh + requirements.txt + results.{1..8}.json)}.
