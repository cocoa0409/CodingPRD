# Worklog — task_1543_mobile_heavy_duty_truck_repair_roadside

## Step 1: Create Task Directory — 2026-08-13T19:20:00.000Z

Task directory `tasks/task_1543_mobile_heavy_duty_truck_repair_roadside/` and `workspace/` pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per invocation instructions.

## Step 2: Generate Scaffold — 2026-08-13T21:12:56.172Z

All three scaffold artifacts are generated, cross-audited, and lint-clean.

## Deliverables

- `/home/ubuntu/github/CodingPRD/tasks/task_1543_mobile_heavy_duty_truck_repair_roadside/SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1543_mobile_heavy_duty_truck_repair_roadside/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1543_mobile_heavy_duty_truck_repair_roadside/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

## Counts

| Element | Count |
|---|---|
| Entities (§1.1) | 17 |
| State machines (§1.2) | 13 (Invoice carries parallel dimensions issue_status × payment_status) |
| Concurrency rules (§1.2.1, OCC) | 2 (estimate-create / dispatch-create, both create-with-supersede on `ServiceCall.version`, 412 `ERR_STALE_VERSION`) |
| Calculations (§1.3) | 17 |
| Validations (§1.4, priority-ordered) | 41 |
| Endpoints (§1.5) | 96 (incl. `/_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`, `/_ops/run_daily`) |
| Errors (§1.6) | 42 — every one has a validation/transition reference AND at least one test trigger |
| Roles (§1.7) | 7 (OpsAdmin, Dispatcher, Technician=`entity_backed:Technician`, FleetManager=`entity_backed:FleetAccount`, BillingClerk, WarrantyAdministrator, SafetyOfficer) |
| §1.8 non-stub instances | 27 (3 per rule × 9 rules) |
| §1.9 instances | 61 non-stub + 3 `excluded_because` stubs |

Lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1447 calls scanned.)

## Notable design decisions

- **Complexity profile**: pricing_engine primary + workflow_orchestration secondary; flat topology with self-referential `ServiceCall.repeat_of_call_id`; segregation-of-duties role model (claim filer ≠ decider; invoice issuer ≠ voider, enforced via `issued_by` vs X-User-ID as `ERR_SEGREGATION_OF_DUTIES`).
- **Chained layered pricing**: after-hours flag (boundary `>= 18:00`) → 1.5× labor multiplier + portal-to-portal travel (2× miles, no free-mile deduction) → P1 callout → GOLD/PLATINUM tier discount snapshotted from mtd-before (pinned evaluation order against the circular mtd dependency) → parts tax rounded once on the subtotal (7250 vs naive 7251 trap) → warranty offset `min(oem, retail)` → payment waterfall over 7 pinned buckets.
- **All assertion literals precomputed by executing the formulas** (e.g., estimate 161444 vs final invoice 200995; warranty OEM 63600 vs retail 106248; authorization boundary at exactly 100000 vs 100001 using parts 79720/79721; tier-snapshot invoice 24500 at mtd_before 499999).
- **Three depth-tagged cascades with distinct triggers**: invoice-issue → mtd → CREDIT_HOLD suspension → call hold flags → PROPOSED dispatch expiry (depth 4); part usage → stock decrement → auto RestockRequest with dedupe (depth 2); full payment → invoice PAID → call CLOSED → comeback case RESOLVED + original REOPENED→CLOSED (depth 3).
- **Three interval semantics**: half-open dispatch windows on technicians (touch allowed), ±30-min buffered tow-unit windows (touch conflicts), closed-closed rate-card windows (touch conflicts).
- Chain-replay self-audit caught and fixed real fixture bugs pre-lint (technician ON_DISPATCH conflicts in multi-call chains, an invalid dispatch-complete, and a miscomputed REDUCED-comeback total corrected to 30750).

## Step 3: Copy Shared Files — 2026-08-13T21:13:30.603Z

Copied `./INSTRUCTION.md` → `tasks/task_1543_mobile_heavy_duty_truck_repair_roadside/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T21:25:21.543Z

All checks pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1543_mobile_heavy_duty_truck_repair_roadside/workspace/PRD.md`.

## Summary

**PRD line count:** 356 lines

**Section list:**
- §1 Introduction (2 paragraphs — business context + structural properties angle)
- §2 Global Specifications (9 subsections): 2.1 RBAC, 2.2 API Response Structure (verbatim block), 2.3 Pagination, 2.4 Common Resource Properties and the Audit Trail, 2.5 Nested Resource Retrieval and Request Validation Order, 2.6 The Logical Clock and the Daily Operations Run, 2.7 Monetary Values / Integer Cents / Rounding, 2.8 Optimistic Concurrency Control on Service Calls, 2.9 Rate Card Governance
- §3 Business Logic & Workflows (11 subsections, organized by business-process timeline): 3.1 Fleet Accounts / Rate Cards / Credit Governance, 3.2 Vehicles / Technicians / Van Stock, 3.3 Call Intake and Triage, 3.4 Dispatching and the Selector, 3.5 Diagnosis / Estimates / Fleet Authorization, 3.6 Parts Usage and Repair Completion, 3.7 Tow Coordination, 3.8 Warranty Claims, 3.9 Invoicing / Payments / Suspension Cascade, 3.10 Repeat Failures and Comeback Calls, 3.11 Inspection Defects and Roadworthiness
- §4 Endpoint Definitions (95-row table, 4 columns only)
- §5 Error Code Catalogue (42 rows, 2 columns only)

**Coverage confirmation (Hard Contracts):**
- Contract 1 Field-Name Coverage: PASS — 172/172 entity fields, 113/113 endpoint request/query inputs, 17/17 path params present in backticks (verified mechanically against the scaffold; two passes run — the first caught 6 field names plus 4 inputs, which were repaired before the final pass).
- Contract 2 Rule Coverage: PASS — all 41 validations matchable to their error IDs in prose (global validation priority order stated in §2.5); both `concurrency_rules` entries expressed with write capability, `expected_service_call_version`, `ERR_STALE_VERSION` / HTTP 412, no race-framing; all ~90 state transitions have from/to states, precondition error refs, and side effects present (mechanically checked every error ref inside `preconditions`/`side_effects`); all 17 calculations rendered as precise prose (boundary values spelled out: 18:00:00Z vs 17:59:59Z, 199999/200000/499999/500000 tier boundaries, day 30/31/45/46 comeback windows, reorder-point equality triggers, strictly-later deadline escalation, touching-endpoints rate-card overlap, half-open dispatch windows vs buffered touching-counts tow windows); four-hop invoice-issue suspension cascade and `status_before_invoice` revert path fully expressed; sibling branches (dual pricing variants, dual warranty bases, four cancellation origins, four escalation sources, three attach-call entry points) rendered with equal density.
- Contract 3 §3 Path Purity: PASS — 772 backtick tokens in §3, zero starting with `/`, zero bare HTTP methods, zero method+path combos.

**Zero-Silence Rule concerns resolved during writing:**
1. `MANUAL` restock source — initially only `AUTO_LOW_STOCK` was named; added explicit `MANUAL`-sourced wording with its caller-supplied quantity semantics.
2. `RELEASED` and `FULFILLED` terminal states — first draft implied them only via verbs; made the state names explicit.
3. Invoice snapshot fields `labor_rate_cents`, `travel_miles_actual`, `travel_miles_billable`, `travel_minutes_actual` — the narrative described the computations but not the stored snapshot fields; reworked the invoice-draft paragraph to name each.
4. `ERR_INVOICE_EXISTS` covers both directions (invoice-create gate and claim-after-invoice gate); both directions are stated in §3.8.
5. Technician `set-status` input `to_status`, claim `decision`, defect `verification_note`, and payment-side `invoice_id` reference were added where their workflows live.

## Step 6: Generate Implementation — 2026-08-13T22:22:10.252Z

Boot contract verified: `bash start.sh` on a fresh process binds 0.0.0.0:$PORT, serves the empty-state list with correct envelope/pagination, enforces 401, and dies cleanly on SIGTERM (exec handoff). All state is in-memory dicts; nothing is seeded — the list returned `total_count: 0` on fresh boot.

## Summary

**Output location:** `/home/ubuntu/github/CodingPRD/tasks/task_1543_mobile_heavy_duty_truck_repair_roadside/workspace/implementation/`

**File list (24 source files + start.sh + requirements.txt, 3780 lines of Python):**
- `start.sh` (11 lines, guarded pip install + `exec python3 app.py`), `requirements.txt` (flask)
- Foundation: `app.py` (62), `db.py` (51), `errors.py` (48), `response.py` (42), `middleware.py` (35), `util.py` (192), `serializers.py` (125)
- Services: `services/pricing.py` (223), `services/cascades.py` (128)
- Routes: `ops.py` 81, `fleets.py` 174, `vehicles.py` 115, `technicians.py` 143, `rate_cards.py` 79, `van_stock.py` 64, `service_calls.py` 385, `dispatches.py` 261, `estimates.py` 239, `part_usages.py` 133, `tow_orders.py` 162, `warranty_claims.py` 201, `inspection_defects.py` 184, `invoices.py` 211, `payments.py` 126, `repeat_failures.py` 171, `restock.py` 97, `call_events.py` 48

**Endpoint coverage: 96/96** from the PRD §4 table (2 ops/clock, 9 fleet, 4 vehicle, 4 technician, 3 rate-card, 4 van-stock, 12 service-call incl. events, 8 dispatch, 6 estimate, 4 part-usage, 6 tow, 6 warranty, 6 defect, 7 invoice, 4 payment, 5 repeat-failure, 5 restock — counted per distinct method+path row).

**State machines implemented (11):** ServiceCall (14 states incl. CANCELLED terminal guard, CLOSED↔REOPENED comeback cycle, hold_reason flags), Dispatch (9 states incl. SUPERSEDED/EXPIRED), WorkEstimate (DRAFT↔REJECTED revision loop, SUPERSEDED/EXPIRED), TowOrder, WarrantyClaim (appeal cap 2), InspectionDefect (escalation + verification-failure rework loop), Invoice (parallel issue_status × payment_status dimensions), Payment, RepeatFailureCase, FleetAccount (ACTIVE/SUSPENDED/CLOSED with ADMIN vs CREDIT_HOLD reasons), Technician (ON_DISPATCH system-managed), RestockRequest, PartUsage.

**Calculations implemented (14):** after_hours boundary + severity→priority + symptom→cert/part-class maps; rate-card resolution (fleet-pinned over window); dispatch selector (3-key ranking, NULL-completed-first); provisional estimate pricing (free-mile deduction even after-hours, no travel time); final invoice pricing (portal-to-portal 2x after-hours, travel time, pinned component order, round-half-up per component, total floored at 0); comeback NO_CHARGE zeroing / REDUCED half-labor; fleet discount tiers (200000/500000 boundaries); single-rounding parts tax; dual-basis warranty valuation (standard-rate retail basis); pinned 7-bucket payment waterfall; fleet MTD with calendar-month rollover computed from ISSUED invoices + adjustments; repeat-failure window (30d/1000mi, 45d/2000mi); van reorder trigger (qty ≤ reorder_point, max(1, rp+2−qoh)); 15-day defect deadline escalation (strictly-greater); OCC via `expected_service_call_version` (ERR_STALE_VERSION 412) on estimate/dispatch create.

**Boot sanity check:** fresh `bash start.sh` on port 19345 → 200 on `GET /roadside/technicians` with empty array + correct envelope (`meta.api_request_id`/`limit`/`offset`/`total_count`/`has_more`, `response_type`), 401 without headers, clean kill. Six smoke suites (60+ assertions) passed end-to-end covering: full dispatch journey, OCC 412, estimate supersede/approve gates (ERR_AUTHORIZATION_REQUIRED, FleetManager ownership), the 4-hop invoice-issue CREDIT_HOLD suspension cascade, void with segregation-of-duties + auto-reinstate, restock auto-trigger/fulfill, warranty appeal cap, defect verify FAIL→rework→PASS loop with roadworthiness flip, tow conflict windows, comeback NO_CHARGE zero-total auto-close resolving the case and re-closing the original, write-off, run_daily expiries with strict-boundary checks.

**Notable fidelity decisions** (PRD-prose honored over scaffold where they diverged): start-repair checks resolution-path before the estimate gate (PRD §3.5 gate order); INVOICE_VOIDED event appended only when the call reverts to REPAIR_COMPLETED, not TOWED (scaffold side-effect asymmetry); cascade events (CALL_CLOSED, CALL_REOPENED, HOLD_FLAGGED) recorded with actor `system`; payment posting refused on VOID invoices and on PAID/WRITTEN_OFF invoices (no collectible balance); FleetManager reads scoped to own fleet across calls/estimates/invoices/vehicles/defects/events.

## Step 5: Generate Unit Tests — 2026-08-13T22:34:03.137Z

Generation complete. All verification passes are green.

## Summary

**Test count per file** (108 tests total in `tasks/task_1543_mobile_heavy_duty_truck_repair_roadside/test_suite/`):

| File | Tests |
|---|---|
| test_01_master_data_envelope_and_auth.py | 13 |
| test_02_temporal_windows.py | 6 |
| test_03_dispatching_and_selector.py | 11 |
| test_04_intake_triage_and_audit.py | 5 |
| test_05_estimates_and_authorization.py | 14 |
| test_06_parts_repairs_and_tows.py | 11 |
| test_07_warranty_claims.py | 6 |
| test_08_invoice_pricing_variants.py | 13 |
| test_09_payments_and_invoice_lifecycle.py | 9 |
| test_10_fleet_credit_governance.py | 5 |
| test_11_repeat_failures.py | 7 |
| test_12_inspection_defects.py | 4 |
| test_13_rbac.py | 4 |

**Queue A (Difficulty): 25/27 instances emitted, 2 tests each (50 tests).** Skipped instances:
- `priority_pair_validation_conflict/safety_beats_temporal_on_dispatch_create` — both errors (ERR_TECHNICIAN_NOT_CERTIFIED, ERR_DISPATCH_WINDOW_OVERLAP) sit inside PRD §2.5's single "business rules" priority bucket; the PRD pins category-level order only (the parenthetical "certification, window overlap, fleet gates…" is illustrative, ending in "and the like", and contradicts §3 narrative order), so intra-bucket ordering fails unique derivability.
- `priority_pair_validation_conflict/temporal_beats_referential_on_dispatch_create` — same reason (ERR_DISPATCH_WINDOW_OVERLAP vs ERR_FLEET_SUSPENDED, both business rules). The cross-category pair `state_beats_fiscal_on_estimate_approve` (state-machine legality explicitly precedes business rules in §2.5) WAS emitted.

**Queue B (Corner): 58/61 non-stub instances emitted, 1 test each.** The 3 `excluded_because` stubs (repeat_of_call_id_self_reference, layer_cascading_side_effects, layer_dual_variant_calculation) were not translated; their difficulty-instance cross-references resolve. Skipped non-stub instances:
- `entities/version_increments_on_every_mutation` — pins absolute version values (create==1, triage==2); PRD §2.4 says version "increments with every modification" but never pins the initial value, so the asserted 1/2/3 is not uniquely derivable.
- `state_machines/payment_on_draft_invoice_rejected` — asserts payments require issue_status==ISSUED; no PRD sentence states that gate (§3.9 gates only the amount bounds), so two PRD-only readers diverge.
- `calculations/payment_waterfall_bucket_order_and_remainder` — asserts an exact allocation_json key map; the PRD pins the bucket order but never specifies the map's key serialization. (The related difficulty instance `payment_post_then_void_restores_invoice_outstanding` was emitted using only its PRD-derivable assertions.)

**Helper files created** in `test_helpers/`: `types.py` (17 TypedDicts, 27 enums; CallEvent correctly omits updated_at/version), `api_client.py` (one method per PRD endpoint under /roadside), `api_errors.py` (42 error IDs registered with the framework), `assertions.py` (per-entity assertions + invoice outstanding invariant), `factories.py`, `constants.py` (canonical rate card + S1 money constants), `test_users.py` (7 roles; entity-backed builders for Technician/FleetManager), `fixtures.py` (tiered composites: master data, lifecycle steps, `run_on_site_repair`, `repair_existing_call`, canonical S1 job, issued-invoice and comeback fixtures), `__init__.py` barrel. Plus `test_suite/conftest.py`.

**Verification performed:** py_compile clean; pytest collects 108 tests; every docstring ends with exactly one Design tag resolving to a real instance (≥2 per emitted difficulty instance, ≥1 per emitted corner instance); all 126 quoted PRD spans verified verbatim against PRD.md via whitespace-normalized 8-word-window grep; no skip/skipif/xfail markers; no scaffold references in generated code; money literals (161444, 200995, 136698, 73098, 46675, 41313, 100000/100001, 30750, 7250, 24500, etc.) independently recomputed against the PRD formulas. A stub-transport execution pass flushed out and fixed real bugs (fixture signature gaps, an odometer-regression fixture bug in the FULL-policy repeat-case test, `api` scoping in class helpers).

## Step 7 resume note — 2026-08-13T22:45:00.000Z

Resume run: Steps 1-6 verified complete on disk (3 scaffold files, INSTRUCTION.md, PRD.md, 108 collected tests, implementation imports cleanly). Prior Step 7 subagent completed one 8-round sweep (results.{1..8}.json at 22:39, ~21-22 failures per round) but was killed before the diagnose/fix loop; no worklog entry was recorded. Spawning a fresh long-lived Step 7 fix subagent to own the full iterate loop.

## Step 7: Run Tests and Iterate — 2026-08-13T23:10:00.000Z

**Result: clean 8-round parallel sweep — all 8 rounds report 108/108 passed (was 87/108 per round, 21 distinct deterministic failures).**

## Iterations run
2 sweeps total: (1) fresh diagnostic sweep confirming the same 21-test failure set across all 8 rounds; (2) post-fix verification sweep, all green.

## Tests deleted
None. Every failing test traced to verbatim PRD prose and survived the coverage + unique-derivability checks.

## Fixes applied to `test_suite/` (test bugs — setups/assertions violating or exceeding PRD)

- **test_07_warranty_claims.py `_completed_warranty_job`** — removed a redundant `create_standard_rate_card()` before `setup_s1_completed_job(...)` (which publishes the identical STD-2026 window itself). The second publish violates PRD §2.9's closed-window non-overlap invariant and was correctly rejected with `ERR_RATE_CARD_WINDOW_OVERLAP` (STEP 2 fixture bug; fixed 5 tests).
- **test_09_payments_and_invoice_lifecycle.py `_issued_invoice_with_credit_hold`** — same redundant rate-card publish removed (fixed 2 tests); also dropped the now-unused import.
- **test_10_fleet_credit_governance.py** `test_month_rollover_resets_mtd_and_reinstates_credit_hold` and `test_immediate_consistency_after_invoice_issue` — same redundant publish removed (fixed 2 tests).
- **Odometer preconditions (STEP 2 fixture bugs; 6 tests)**: fixtures completed repairs below the vehicle's recorded odometer, which PRD §3.6 forbids (`ERR_ODOMETER_REGRESSION`). test_04 `test_cancel_terminal_lockdown_and_late_cancel_rejected`: 80020 → 90020; test_08 `test_priority_mapping_drives_callout_fee`: 80020 → 90040; test_08 `test_free_mile_boundary_25_vs_26_{billable_miles,totals}`: 80030 → 90040; test_08 `test_travel_standard_vs_after_hours_portal_basis` and `test_travel_variant_selection_moves_the_total`: 80100 → 90110. Values are immaterial to the asserted pricing math.
- **Timestamp string-format assertions (STEP 1c partial coverage; 3 tests)**: PRD pins the *instant* for `effective_from`/`received_at`/`correction_deadline_at` but mandates the three-fractional-digit string format only for `created_at`/`updated_at`/`api_request_timestamp`, so exact-string equality was not uniquely derivable (implementation serializes `.000Z`). Added `parse_iso8601_utc` to `test_helpers/assertions.py` and switched to instant comparisons in test_02 `test_rate_card_window_starting_next_instant_allowed`, test_04 `test_after_hours_flag_stamps_received_at_from_logical_clock`, test_12 `test_vehicle_roadworthiness_flips_with_oos_defect_lifecycle`.

## Fixes applied to `implementation/`

- **routes/dispatches.py `create_dispatch`** — the state gate rejected every non-`TRIAGED` call with `ERR_INVALID_STATE`, which made two PRD §3.4 clauses unreachable: "supersedes any prior `PROPOSED` dispatch of the same call" (a call holding a PROPOSED dispatch is necessarily `DISPATCHED`) and the `ERR_DISPATCH_ACTIVE` refusal for calls with an `ACCEPTED`/`EN_ROUTE`/`ON_SITE` dispatch. Now: `DISPATCHED` calls with no active dispatch pass the gate (supersede path; the OCC test's stale create then correctly surfaces `ERR_STALE_VERSION` 412 per §2.5 ordering), `DISPATCHED`-with-active yields `ERR_DISPATCH_ACTIVE`, other non-`TRIAGED` states still yield `ERR_INVALID_STATE` (fixed 2 tests).
- **routes/technicians.py `set_status`** — targeting `ON_DISPATCH` previously raised `ERR_VALIDATION`; `ON_DISPATCH` is a declared member of the four-value technician status enum (§3.2) that is simply system-managed, so a self-service transition targeting it is an undeclared transition → `ERR_INVALID_STATE`; non-member strings now yield `ERR_INVALID_ENUM` instead of `ERR_VALIDATION` (fixed 1 test).

No assertions were weakened, no tests skipped, no implementation checks removed, and no endpoint/field/behavior was added beyond verbatim PRD prose.

## Step 8: Finalize PRD — 2026-08-13T23:25:00.000Z

Step 8 complete. `workspace/PRD_FINALIZED.md` is written.

## Line counts

- `PRD.md`: 355 lines; `PRD_FINALIZED.md`: 357 lines (+2 lines, +0.56%). Three edits total; no new sections.

## Changes (one bullet per edit)

- **§2.4** — insert — added a paragraph pinning that every non-null datetime field the server emits (logical-clock-stamped, computed, or client-echoed) is serialized as an ISO 8601 UTC string with three fractional digits — `implementation/util.py:19-24` (`fmt_dt`), `implementation/serializers.py:50-71` (`_DT_FIELDS` via `_base`), `implementation/util.py:13-16` (`now_wall_iso` for `created_at`/`updated_at`/`api_request_timestamp`).
- **§3.2** — revise — appended error semantics for the self-service status transition: a `to_status` string outside the four-member enum → `ERR_INVALID_ENUM`; an enum member with no declared transition from the current status (including any self-service target of `ON_DISPATCH`) → `ERR_INVALID_STATE` — `implementation/routes/technicians.py:98-107`.
- **§3.4** — revise — dispatch creation is allowed against a `TRIAGED` call or a `DISPATCHED` call holding no `ACCEPTED`/`EN_ROUTE`/`ON_SITE` dispatch; any other status → `ERR_INVALID_STATE` (with the `CANCELLED` terminal-guard carve-out); successful creation "moves the call to `DISPATCHED` (advancing a `TRIAGED` call, or leaving an already-`DISPATCHED` call in place)" — `implementation/routes/dispatches.py:54-67,105-106`.

Step-7 items producing **no** PRD edit (pure fixture bugs; PRD already pins the behavior verbatim): the redundant STD-2026 rate-card publishes (PRD §2.9 closed-window non-overlap; `implementation/routes/rate_cards.py:35-40`) and the below-odometer repair completions (PRD §3.6 `ERR_ODOMETER_REGRESSION`; `implementation/routes/service_calls.py:278`, `implementation/routes/vehicles.py:110`).

## Per-edit pre-edit search log

**Edit 1 (timestamp wire format).** (a) Subject: string serialization format of every datetime field in any response payload. (b) Enumerated/read: `serializers.py` `_DT_FIELDS` (all 21 datetime field names) + `fmt_dt`; `util.py` `now_wall_iso`/`parse_dt`; grep of all `store.clock`/`datetime` assignments across `routes/*.py` and `services/*.py` (received_at, submitted_at, issued_at, due_at, completed_at, departed_at, arrived_at, posted_at x2, verified_at, decided_at, hooked_at, delivered_at, effective_from/to, discovered_at, oem_warranty_expires_at, window/pickup windows — all land in `_DT_FIELDS`); grep of every `success(` callsite confirming all resource payloads pass through `serialize*` (only non-resource payloads: `current_utc` via `fmt_dt` in `ops.py:29`, daily-run integer counts, dispatch-suggestion ids). (c) Wording scoped to "non-null datetime field the server emits" (unset timestamps serialize as JSON null, not strings) and gave representative field examples rather than an exhaustive list to avoid excluding any path.

**Edit 2 (technician set-status).** (a) Subject: error ids for `POST /technicians/{id}/set-status` targets. (b) Enumerated/read: `technicians.py:89-110` (shape pass → `ERR_VALIDATION` for non-string; membership vs `ALL_STATUSES` → `ERR_INVALID_ENUM`; `ALLOWED_TRANSITIONS` check → `ERR_INVALID_STATE`, covering `ON_DISPATCH` targets, same-state, and `ON_DISPATCH`→x sources); all other status-mutating paths (`dispatches.py:151` accept → `ON_DISPATCH`, `cascades.py:46-51` `free_technician`, `create_technician` initial `OFF_DUTY`) to confirm the edit speaks only about the self-service endpoint; test call sites (`test_03:324-337`, `api_client.py:92`). (c) Restricted the enum clause to "a `to_status` **string** outside the four-member enum" so mistyped (non-string) values remain `ERR_VALIDATION` per §2.5 shape-first ordering, matching impl pass structure.

**Edit 3 (dispatch create gate).** (a) Subject: call-state precondition and outcome of `POST /service-calls/{id}/dispatches`. (b) Enumerated/read: `dispatches.py:39-108` (gate order: `ensure_not_cancelled` → `DISPATCHED` branch with `ERR_DISPATCH_ACTIVE` / other-state `ERR_INVALID_STATE` → OCC → certification → window overlap → fleet gate → supersede loop → `call["status"]="DISPATCHED"` + version bump + event); `service_calls.py:47-72` helpers (`ensure_not_cancelled` covers only `CANCELLED`; `fleet_gate_active`); `cascades.py:34-43,73-89` (revert-on-no-active, suspension cascade) and `ops.py:35-48` (daily-run expiry) to confirm how `DISPATCHED`-with-only-`PROPOSED` states arise and revert; `estimates.py:61-106` as the parallel OCC write (no state gate there, so no wording bleed); tests `test_03:163-235`. (c) Two adjustments: added the explicit `CANCELLED` → `ERR_CALL_ALREADY_TERMINAL` carve-out (impl raises it for CANCELLED, `ERR_INVALID_STATE` for all other non-gate states including `CLOSED`); and deliberately left the relative ordering of `ERR_DISPATCH_ACTIVE` vs `ERR_STALE_VERSION` unpinned (impl evaluates the active-dispatch refusal inside the pre-OCC gate, but no test exercises the combination — under-determined wording preferred over a claim that would collide with §2.5's global ordering sentence).

## Step 9: Complete PRD — 2026-08-13T23:50:00.000Z

Done. `workspace/PRD_COMPLETED.md` written as a minimal patch over PRD_FINALIZED.md.

**Size delta:** PRD_FINALIZED.md 357 lines / 66,236 chars → PRD_COMPLETED.md 359 lines / 72,778 chars (+2 lines, +6,542 chars). 29 diff hunks; no new sections, all inline.

**Counts:** 26 ambiguity-pins, 9 mismatch-revisions (35 change intents total across 29 hunks).

**Ambiguity-pins (PRD silent → pinned to impl):**
- §2.1 — insert — FleetManager ownership scope extended to vehicles, service calls, call events, inspection defects; list endpoints filter to own fleet — routes/vehicles.py:72-85, service_calls.py:158-169, call_events.py:22-39, inspection_defects.py:81-99, invoices.py:33-101
- §2.3 — insert — non-integer/out-of-range `limit`/`offset` → `ERR_VALIDATION` — util.py:159-185
- §2.3 — insert — exact-match list filters enumerated per resource; unrecognized params ignored; same-timestamp ties broken by creation sequence — routes/*.py list handlers, util.py:188-192
- §2.4 — insert — `version` starts at 1 — db.py:44-45
- §2.5 — insert — `fleet_account_id` added to body-FK `ERR_NOT_FOUND` list — routes/vehicles.py:44-45
- §2.6 — insert — clock set responds with `current_utc` — routes/ops.py:29
- §2.6 — insert — expired dispatch lands in `EXPIRED`; call reverts only when no active dispatch remains — routes/ops.py:42-49
- §3.1 — insert — `rate_card_id` null on update clears the pin — routes/fleets.py:103-107
- §3.1 — insert — suspend only from `ACTIVE`, reinstate only from `SUSPENDED`, close from `ACTIVE`/`SUSPENDED` (already-`CLOSED` → `ERR_INVALID_STATE`); terminal call = `CANCELLED`/`CLOSED`; spend adjustment stamps logical-clock `posted_at`, is not fleet-gated, returns updated fleet with 201 — routes/fleets.py:114-174
- §3.2 — insert — vehicle update may also revise `unit_number` — routes/vehicles.py:101-107
- §3.2 — insert — new technician begins `OFF_DUTY` with `current_dispatch_id` null — routes/technicians.py:57-58
- §3.2 — insert — duplicate `part_number` per van → `ERR_VALIDATION`; negative adjustment result → `ERR_VALIDATION`; restock approve/reject from `PENDING`, fulfill from `APPROVED` — routes/technicians.py:128-132, van_stock.py:58-60, restock.py:57-93
- §3.3 — insert — cancel permitted only from `RECEIVED`/`TRIAGED`/`DISPATCHED`/`EN_ROUTE` — routes/service_calls.py:304-306
- §3.4 — insert — selector read on non-`TRIAGED` call → `ERR_INVALID_STATE` — routes/service_calls.py:325-326
- §3.4 — insert — dispatch complete only from dispatch's own `ON_SITE` — routes/dispatches.py:232-233
- §3.5 — insert — estimate creation permitted in any non-`CANCELLED` status — routes/estimates.py:74
- §3.5 — insert — `requires_fleet_approval` always false on retail calls; FleetManager cannot approve/reject retail estimates (`ERR_FORBIDDEN_OWNERSHIP`); rejection also stamps `decided_by`/`decided_at` — routes/estimates.py:43-50, 187-189, 229-235
- §3.5 — insert — start-repair requires on-site dispatch technician — routes/service_calls.py:244
- §3.6 — insert — `SHOP_GUARANTEE` on non-comeback → `ERR_VALIDATION`; return requires on-site dispatch technician; complete-repair requires on-site technician — routes/part_usages.py:49-51, 122-125; service_calls.py:274
- §3.8 — insert — `filed_by` for WarrantyAdmin = serving dispatch technician; submit fails with `ERR_NO_ACTIVE_RATE_CARD` when no card covers; blank `denial_reason` → `ERR_VALIDATION` — routes/warranty_claims.py:74-75, services/pricing.py:198, warranty_claims.py:160-161
- §3.9 — insert — `invoice_number` begins at `INV-000001` — routes/invoices.py:58
- §3.9 — insert — cascade names `EXPIRED` dispatch status, conditional revert, `hold_reason` persists forever — services/cascades.py:79-89
- §3.9 — insert — payment against `VOID`/`PAID`/`WRITTEN_OFF` invoice → `ERR_INVALID_STATE`; unissued `DRAFT` invoice accepts payments; voiding a payment never reopens a `CLOSED` call — routes/payments.py:52-55, 107-126, services/cascades.py:54-57
- §3.9 — insert — overdue surfaced as computed `is_overdue` field — serializers.py:94-99
- §3.10 — insert — tow-only original call (no `completed_at`/`completion_odometer_miles`) yields window 0 days, zero mileage baseline — routes/repeat_failures.py:57-64

**Mismatch-revisions (PRD said X, impl does Y → PRD revised):**
- §2.5 — revise — check order rewritten to impl's actual order (path existence → shape → enum → body-FK existence → state → OCC → business; ownership position resource-dependent), with the two deviating orderings named (dispatch create resolves `technician_id` before window-order check; repeat-case vehicle-match before `CLOSED` check); also "non-positive quantities" → floor-based wording — routes/dispatches.py:49-53, repeat_failures.py:41-46, util.py:107-112
- §3.2 — revise — `ON_DISPATCH` clearing triggers: complete / release-of-accepted / call cancel with dispatch `ACCEPTED`/`EN_ROUTE`; removed the impossible "fleet-suspension cascade expires their proposed dispatch" clause (cascade only expires `PROPOSED`, which never holds `ON_DISPATCH`) — services/cascades.py:46-51, 73-89, routes/dispatches.py:260-261, service_calls.py:307-312
- §3.2 — revise — dropped the `MANUAL`-sourced restock clause (no endpoint creates one) — routes/restock.py (no create route), services/cascades.py:122
- §3.5 — revise — `revision` semantics: starts at 1 per newly created estimate, +1 per revise of a rejected one (not "monotone per call") — routes/estimates.py:88, 146-148
- §3.8 + §2.1 — revise — any `Technician` may file a claim (recorded from `X-User-ID`), not only the on-site one — routes/warranty_claims.py:71-72
- §3.9 — revise — "completed dispatch (latest by completed_at)" → serving dispatch: latest `COMPLETED` else `ON_SITE` fallback — services/pricing.py:53-66
- §3.9 — revise — "payments process chronologically by `received_at`" → allocation is strictly posting-ordered; `received_at` plays no part — services/pricing.py:208-223
- §3.3 — revise — terminal-call guard scoped to call-scoped writes (enumerated); document lifecycles (estimate edit/approve, dispatch self-actions, invoicing/payments) proceed unaffected — routes/estimates.py (no `ensure_not_cancelled` on PATCH/submit/approve/reject)
- §3.11 — revise — mark-corrected ownership: serving dispatch (latest completed else on-site), not strictly the `ON_SITE` dispatch — routes/inspection_defects.py:154-157
