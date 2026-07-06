# Worklog — task_0554_appliance_repair

## Step 1: Create Task Directory — 2026-07-05T00:00:00.000Z

Created `tasks/task_0554_appliance_repair/workspace/` (directory pre-allocated). Scenario: Appliance Repair & Extended-Warranty Service (Sears Home Services style). Scaffold difficulty: Expert.

## Step 2: Generate Scaffold — 2026-07-05T00:00:00.000Z

All three artifacts generated, parse cleanly, pass `scaffold_lint.py` (VERDICT: clean lint).

Expert-difficulty scaffold. SCAFFOLD.yaml: primary `workflow_orchestration` + secondary `temporal_windowing`; layers optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation; flat topology, cyclic state-machine shape, peer_roles; `api_prefix: "/"`. 13 entities (Customer, Appliance, WarrantyContract, Part, Technician, TruckStockItem, ServiceZone, ServiceRequest, Appointment, Estimate, PartsOrder, Payment, RecallNotice — 15 FKs). 6 state machines (ServiceRequest cyclic callback loop + SAFETY_HOLD; Estimate branching; PartsOrder cyclic ORDERED↔BACKORDERED; Appointment; Technician; RecallNotice). 1 OCC rule (ServiceRequest.version supersede race → ERR_STALE_VERSION 412). 9 calculations (labor_cost, repair_cost dual-variant, warranty_customer_responsibility tiered, diagnostic_fee_assessment, appliance_health_score dual-variant, warranty_contract_selector, technician_timeline_conflict, zone_capacity_conflict, truck_stock_availability). 15 ordered validations, 38 endpoints (19 POST/19 GET), 16 errors, 4 roles (Customer/Technician entity-backed; Dispatcher/ServiceAdmin opaque).

SCAFFOLD_DIFFICULTY_DESIGN.yaml: 9 rules × 2 = 18 instances, executable setup/trigger/literal asserts.
SCAFFOLD_CORNER_DESIGN.yaml: 21 active instances + 6 excluded_because stubs.

Note: endpoint count (38) exceeds Expert 20–32 guideline, driven by flat 15-FK reverse-reachability GET pairs, not padding.

## Step 3: Copy Shared Files — 2026-07-05T00:00:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-05T00:00:00.000Z

PRD written to `workspace/PRD.md`: 5 top-level sections, 263 lines. §1 Introduction; §2 Global Specifications (9 subsections: RBAC + 15-stage validation pipeline, response envelope, pagination, common properties/UUID/version, cent-based money, recall cascades + hierarchical consistency, OCC on estimate revision, nested retrieval/ordering, warranty-ledger + truck-stock invariants); §3 Business Logic (8 lifecycle subsections); §4 38-row endpoint table; §5 16-row error catalogue.

Coverage: Contract 1 (field-name) PASS 68/68; Contract 2 (rule) PASS all 15 validations + OCC + 6 state machines + 9 calculations + constants; Contract 3 (§3 path purity) PASS. All 13 entities, 6 state machines, 9 calculations, 38 endpoints, 16 errors covered.

## Step 5: Generate Unit Tests — 2026-07-05T00:00:00.000Z

test_helpers/ (9 files: types, api_client, api_errors, assertions, factories, constants, test_users, fixtures, __init__). test_suite/ (conftest + 9 test files, 57 test functions). Queue A (Difficulty): all 18 instances × 2 = 36 tests. Queue B (Corner): all 21 non-stub instances × 1 = 21 tests. 6 excluded_because stubs not translated (correct). 0 instances skipped.

Notable adjudications: `second_trip_appointment_cancel_cascade_depth3` — dropped unreachable appointment-CANCELLED assertion (appt2 booked from APPROVED not PRD-reproducible), kept APPROVED→AWAITING_PARTS + ORDERED PartsOrder core. `create_service_request_returns_intake` — dropped `diagnostic_fee_cents == 0` default (default-value silence), kept status INTAKE + version 1. All Design: tags map to real instances; ~60 PRD citations verified verbatim; all files py_compile clean.

## Step 6: Generate Implementation — 2026-07-05T00:00:00.000Z

Python + Flask at `workspace/implementation/`: app.py (single-file, all 13 entities + state machines + calculations + RBAC + validation pipeline), requirements.txt (flask==3.0.3), start.sh. 39 endpoints implemented. start.sh reads $PORT (default 10000), binds 0.0.0.0, foreground `exec python3 app.py`, pip install guarded behind `import flask` check. In-memory dicts only, no seeding, no disk persistence. Verified: response envelope, pagination, auth headers, labor rounding per-task, integer-cent money, warranty split + claim reconciliation, diagnostic-fee waiver, health score dual-variant, truck-stock invariants, recall cascade + reversal, technician 30-min buffer, zone overlap, OCC ERR_STALE_VERSION 412, priority-ordered validation. One bug fixed: get_or_404 ApiError arg order.

## Step 7: Run Tests and Iterate — 2026-07-05T00:00:00.000Z

All 8 parallel rounds pass 57/57. Clean sweep.

Iterations run: 2 (1 diagnostic sweep + 1 verification sweep). Initial sweep showed the same 4 failures deterministically across all 8 rounds (no flakiness); fix sweep all green.

Tests deleted: None.

Fixes applied to test_helpers/:
- fixtures.py — provision_base(): added `recall=False` param that, when set, creates and activates a brand/model-matching RecallNotice BEFORE the service request is opened. Why: the two recall-booking tests previously activated the recall AFTER the INTAKE request existed, which per PRD §2.6 cascades that in-flight request to SAFETY_HOLD, so booking failed at state-guard #4 (ERR_INVALID_STATE) instead of recall-guard #7 (ERR_SAFETY_RECALL_HOLD). Implementation correct; fixture constructed PRD-inconsistent precondition.

Fixes applied to test_suite/ (assertion trims per STEP 1c, PRD-silence):
- test_02_scheduling_guards.py — test_booking_recalled_appliance_rejected, test_booking_blocked_by_recall_leaves_request_in_intake: switched to provision_base(model="MD10", recall=True).
- test_01_requests_and_lookup.py — test_open_service_request_born_in_intake: removed shared assert_service_request(sr) call (kept §2.4 status==INTAKE + version==1). Why: helper requires warranty_routing be an enum member, but PRD assigns warranty_routing only at diagnosis (§3.3); INTAKE-stage routing value never pinned (DEFAULT-VALUE SILENCE — null vs "NONE" both faithful).
- test_05_approval_and_truck_stock.py — test_reserve_exactly_available_quantity_succeeds: removed assert_service_request(sr) (kept 200 + status=="APPROVED"). Why: asserted /estimates/{id}/decision echoes a ServiceRequest, but PRD never states which resource that endpoint echoes (RESPONSE-SHAPE SILENCE).

Fixes applied to implementation/: None — implementation was faithful to PRD in all four cases.

## Step 8: Finalize PRD — 2026-07-05T00:00:00.000Z

PRD_FINALIZED.md written. PRD.md = 263 lines, PRD_FINALIZED.md = 263 lines (+0.0%; both edits in-line revisions).

Changes:
- §3.2 — revise — added warranty_routing to the list of ServiceRequest fields null at INTAKE, pinned it stays null through INTAKE/SCHEDULED until diagnosis assigns coverage_type or NONE — app.py:612 / app.py:750.
- §3.4 — revise — pinned /estimates/{id}/decision returns the updated Estimate resource (not ServiceRequest) in data, for both approve and decline — app.py:1069 / app.py:1112.

Recall-fixture items in the diff were pure fixture/precondition bugs — no PRD edit warranted.

## Step 9: Complete PRD — 2026-07-05T00:00:00.000Z

PRD_COMPLETED.md written. Source PRD_FINALIZED.md (263 lines, 44074 chars) → PRD_COMPLETED.md (263 lines, 45559 chars); +1485 chars. 4 ambiguity-pins, 2 mismatch-revisions.

Changes:
- §2.3 Pagination — insert — ambiguity — out-of-range limit/offset clamped (limit→[1,100], negative offset→0), only non-integer values raise ERR_VALIDATION — app.py:220-225.
- §3.1 Onboarding — insert — ambiguity — pinned appliance initial health_score (formula with purchase_date reference → age=0, 0 repairs → 100 CLEAR / 80 RECALLED) and recompute on recall activation/rescission and completion — app.py:399-412,1235-1287.
- §3.5 Second Trip — insert — ambiguity — endpoint returns updated ServiceRequest (not created PartsOrder) — app.py:999.
- §3.6 Completing the Repair — insert — ambiguity — endpoint returns updated ServiceRequest — app.py:959.
- §3.3 Diagnosis — revise — mismatch — required_parts part_id existence checked AFTER state/ownership/safety (ERR_NOT_FOUND after ERR_NOT_OWNER/ERR_SAFETY_RECALL_HOLD) — app.py:730-743.
- §3.4 Estimate Revision — revise — mismatch — referenced-part existence checked after ownership, before OCC version check — app.py:824-837.

## Pipeline Complete — 2026-07-05T00:00:00.000Z

All 9 steps complete. 57/57 tests pass across 8 parallel rounds. Final artifacts: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/, test_suite/ (57 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}.
