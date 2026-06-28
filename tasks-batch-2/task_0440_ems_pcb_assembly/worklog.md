# Worklog — task_0440_ems_pcb_assembly

Scenario: 440. Contract Electronics / PCB Assembly (EMS): BOM & approved-vendor list (AVL), kitting & component shortage, SMT line & program setup, AOI/ICT test & yield, serialization & traceability, ECO/rework, RoHS/conflict-minerals compliance, RMA/field return

Difficulty band: Expert (§0.4)

## Step 1: Create task directory — 2026-06-20T17:32:08.000Z

Pre-assigned task directory tasks/task_0440_ems_pcb_assembly used verbatim (directory-creation was already DONE per orchestrator instructions). workspace/ subdirectory present.

## Step 2: Generate scaffold (Expert band) — 2026-06-20T17:55:00.000Z

Generated the three Expert-band scaffold artifacts for task_0440_ems_pcb_assembly (Contract Electronics / PCB Assembly EMS) at the paths requested. All files parse, and scaffold_lint.py returns VERDICT: clean lint (474 §1.8/§1.9 calls checked; all FK reverse-reachability satisfied).

Design profile: graph_constraint primary archetype + quota_allocation secondary; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation, rate_threshold_triggers; graph topology; branching/cyclic/parallel state shapes; segregation_of_duties role model (ProcessEngineer authors ECOs, QualityEngineer approves, neither closes their own rework). api_prefix is empty (flat top-level collections, required for the lint's segment derivation).

Counts:
- Entities: 13 (Part, Vendor, AvlEntry, InventoryLot, Bom, BomLine, WorkOrder, KitRequirement, LineProgram, Unit, ReworkOrder, Eco, Rma)
- State machines: 8 (Bom, WorkOrder, Unit [parallel quality×disposition dimensions], Eco [cyclic reject→resubmit], ReworkOrder [+re-rework loop], Rma, AvlEntry, InventoryLot)
- Calculations: 5 (kit_required_qty, work_order_material_cost [dual variant planned/consumed, FIFO], first_pass_yield [instantaneous/final], rework_material_cost [tiered surcharge], rma_warranty_credit [weighted + rework penalty])
- Validations: 17 (priority-ordered, two OCC checks at priority 6)
- Endpoints: 63 (incl. one /_test/build-and-test-units test-driving endpoint added via the §1.5 priority ladder rung 3 to hit an exact FPY=70.00 boundary)
- Error catalog: 20
- Roles: 3 (all opaque, segregation-of-duties)
- Concurrency rules: 2 (OCC on WorkOrder ship, OCC on AvlEntry receive-lot)

§1.8 difficulty instances: 18 — exactly 2 per each of the 9 rules.
§1.9 corner instances: 39 total = 31 active test recipes + 8 excluded_because: stubs (pointing at the §1.8 instances that already cover them), across all 9 claim-extraction sections.

Key correctness notes: every formula-derived assertion was computed in Python against the pinned formulas/constants before being written as a literal (material cost 160 vs planned 200; FIFO straddle 4400; tiered rework 32500/6500/2700; warranty credit 100/60; FPY 70.00→PASSED at inclusive >= boundary). Caught and fixed two would-be-broken recipes during replay (depth-4 cascade asserts; open-rework-blocks-close corner rebuilt as a 4-unit run with REWORKED→REWORKED re-rework transition added to Unit machine).

## Step 3: Copy INSTRUCTION.md — 2026-06-20T17:55:05.000Z

Copied ./INSTRUCTION.md → tasks/task_0440_ems_pcb_assembly/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-06-20T17:58:00.000Z

Output: workspace/PRD.md (283 lines).

Major sections: §1 Introduction (EMS/PCB graph domain, derived rollups, segregation-of-duties + OCC); §2 Global Specifications (2.1 RBAC for ProcessEngineer/ProductionPlanner/QualityEngineer with opaque identity → authored_by_user_id/approved_by_user_id; 2.2 Response structure verbatim; 2.3 Pagination; 2.4 Identity/timestamps/versioning; 2.5 Monetary & yield precision; 2.6 OCC for both expected_work_order_version/ERR_STALE_WORK_ORDER_VERSION and expected_avl_entry_version/ERR_STALE_AVL_VERSION; 2.7 Validation priority 1–16; 2.8 RoHS/conflict-minerals gating with applies_to scopes; 2.9 Inventory rollups & lot lifecycle); §3 Business Logic (11 subsections lifecycle-ordered, all 5 calculations in prose — kit qty, FIFO material cost planned/consumed, FPY instantaneous/final, tiered rework cost, RMA warranty credit; constants embedded: 70% yield floor, 5000/20000-cent tiers, 1500-cent surcharge, 20%/30% rates, 1.00/0.60/0.80/0.00 credit factors, 0.10 rework penalty); §4 Endpoint table (65 endpoints incl. /_test/build-and-test-units); §5 Error catalogue (20 codes).

Hard contracts: Contract 1 field-name coverage 75/75 PASS; Contract 2 rule coverage (20 error IDs in §2/§3 narrative, 38 states + 7 package_type values, transitions/cascades/OCC/priorities/5 calcs) PASS; Contract 3 §3 path purity (404 backtick tokens, 0 paths/methods) PASS.

Confirmation: Neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read/grepped/referenced; no sibling tasks consulted.

## Step 5: Generate unit tests — 2026-06-20T18:15:00.000Z

Generated complete test infrastructure for task_0440_ems_pcb_assembly purely from the four input files plus the unit-test-generator spec.

test_helpers/ (9 files): __init__.py (barrel export); types.py (13 entity TypedDicts + 12 status/role enums; all entities common_fields=true → carry updated_at/version); api_client.py (ApiClient one method per PRD §4 endpoint incl. /_test/build-and-test-units); api_errors.py (ApiErrorId + HTTP status map, 20 errors); assertions.py (per-entity + common-field checker); factories.py (input-field-only payload factories); constants.py (yield floor, rework tier, warranty factor constants); test_users.py (shared headers for 3 opaque roles + per-identity builders for SoD/authorship); fixtures.py (composite setup helpers).

test_suite/ (conftest + 8 test files, 66 tests): test_01 inventory/compliance (8), test_02 BOM/release cascade (6), test_03 kitting/costing (11), test_04 setup/WO lifecycle (7), test_05 yield/finalize (2), test_06 rework/ECO (17), test_07 RMA/warranty (6), test_08 security/CRUD (9).

Provenance: Queue A (Difficulty §1.8): 36 tests — all 18 instances covered with exactly 2 tests each. Queue B (Corner §1.9): 30 tests — 30 of 31 non-stub instances covered (1 test each); all 8 excluded_because stubs left untranslated; every stub's difficulty_instance cross-reference verified to resolve.

Skips (1 instance): Corner/state_machines/terminal_obsolete_bom_cannot_anchor_workorder — unique-derivability failure (silence-pattern applies_to-scope): asserts ERR_INVALID_STATE for creating a WorkOrder against an OBSOLETE BOM, but PRD §3.5 only says "creating a work order against a released bill of materials" without naming the rejection error; creation is not a BOM state-transition so §2.7's ERR_INVALID_STATE rule doesn't verbatim apply. Faithful reader could ship ERR_FK_NOT_FOUND/ERR_VALIDATION/ERR_INVALID_STATE — no unique outcome. Gap left as gap.

Audits passed: every test docstring ends with exactly one Design: tag verbatim from source YAML (66/66); all 87 PRD citation quotes survive whitespace-normalized grep of PRD.md (C1); no skip/skipif/xfail; no scaffold/§-label leakage; all fx./api./f. references resolve; all files compile.

NOTE (orchestrator): Steps 5 and 6 were run sequentially rather than in a single concurrent message. To preserve the impl-gen physical isolation (impl must not read tests), Step 6's prompt carries an explicit hard constraint forbidding any read of test_helpers/ or test_suite/.

## Step 6: Generate implementation — 2026-06-20T18:25:00.000Z

Generated complete Python + Flask implementation in workspace/implementation/.

Files: start.sh (guarded pip install + exec python3 app.py); requirements.txt (Flask==3.0.3); app.py (entry point, error handlers, ~60 route handlers); db.py (in-memory store, UUID/serial/timestamp/version mgmt); response.py (success/error/list envelopes); errors.py (ApiError + 20 error-ID constants); middleware.py (X-User-ID/X-User-Role auth + role enforcement); lookups.py (path 404 ERR_NOT_FOUND vs FK 404 ERR_FK_NOT_FOUND); pagination.py (limit/offset default 10, 1–100, created_at asc); inventory.py (total_on_hand_qty/available_qty rollups, FIFO ordering); calculations.py (Decimal half-up; FPY, rework tiered surcharge, RMA warranty credit); serializers.py / workflows.py (response stripping; kitting/consume/yield logic).

start.sh: set -euo pipefail, cd to dirname, guards install behind import-flask check, exec python3 app.py; app.py binds 0.0.0.0:$PORT (default 10000, threaded=True). Boots ~1s on empty store.

Coverage: 13 entities with system/computed fields; all §1.5/§4 endpoints incl. /_test/build-and-test-units; all 8 state machines with cascades (BOM supersession → obsolete + cancel planned WOs; rework close → consume/deplete/roll-cost/mark-REWORKED); both OCC guards (expected_avl_entry_version on receive-lot, expected_work_order_version on ship, checked after state per §2.7); 4 calculations (kit required_qty, FIFO consumed-actual material cost, FPY 2dp half-up REWORKED-excluded, tiered rework surcharge flat1500/20%/30% upper-inclusive, RMA warranty credit floor-div build cost × class factor − 10% rework penalty floored at 0); validation precedence (auth→forbidden→path404→FK404→state409→OCC412→SoD/RoHS/CMRT→shape400); RBAC by 3 roles; RoHS/CMRT gates at kit/start/rework-close.

Self-verified with 79 smoke assertions (happy path + RoHS/CMRT gates, kit shortage, supersession cascade, PASSED/FAILED finalize, OCC staleness, SoD, tiered costs, validation ordering) — all passing.

Isolation confirmation: did NOT read test_helpers/, test_suite/, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, or any sibling task. In-memory storage only, no seeding at startup (empty-store boot probe confirmed).

## Step 7: Test-and-fix loop — 2026-06-20T18:40:00.000Z

Clean exit — all 8 parallel rounds passed (65/65 each).

**Iterations run:** 2 (initial diagnostic sweep + one fix-and-verify sweep).

**Initial state:** 66 tests, 5 distinct failures consistent across all completed rounds (round 4 produced no file in iteration 1 due to a boot timeout, but the 7 completed rounds agreed). Final state: 65 tests, all passing in all 8 rounds.

**Tests deleted (1):**
- `test_repair_no_fault_found_rejected` (test_07_rma_warranty.py) — STEP 1b unique-derivability failure, error-precedence collapse. The test asserted `ERR_INVALID_STATE` when repairing a `TRIAGED` RMA whose `failure_class` is `NO_FAULT_FOUND`. But PRD §3.10 gates this as a *business rule* ("only when the `failure_class` is not `NO_FAULT_FOUND`"), and `TRIAGED` is a valid state for the repair transition (TRIAGED → REPAIRED). Under PRD §2.7's fixed precedence, the state check passes (valid state) and the failure-class block — having no specific error code in the catalogue — maps to the generic `ERR_VALIDATION`. PRD does not uniquely determine `ERR_INVALID_STATE`; §2.7 in fact favors `ERR_VALIDATION`, which is what the faithful implementation returns. Rule that drove generation: `rma_repair_no_fault_found_blocked`.

**Fixes applied to test_helpers/ (1):**
- `test_helpers/fixtures.py` — added `setup_kitted_for_start(bom_id, wo_id)` helper: creates a verified line program for the BOM and assigns it via setup, taking a KITTED work order to SETUP. Needed because PRD §3.6 requires a work order to be in `SETUP` before `start` ("A `ProductionPlanner` may start a work order only while it is `SETUP`").

**Fixes applied to test_suite/ (4 call sites, all in test_03_kitting_and_costing.py):**
- `test_consumed_actual_cost_differs_from_standard`, `test_consumed_actual_cost_depletes_lot_correctly`, and the shared `_setup_two_lot_fifo` helper (feeding `test_fifo_straddle_cost_is_order_defined` and `test_fifo_straddle_leaves_newer_lot_remaining`) all created a KITTED work order and called `start_work_order` directly, skipping the PRD-required SETUP step. Inserted a `fx.setup_kitted_for_start(...)` call before each `start_work_order` so the precondition matches PRD §3.6. These were test-setup bugs (STEP 2); the FIFO-costing assertions themselves trace verbatim to PRD §3.6 and were left unchanged.

**No changes made to implementation/** — the implementation correctly enforced the SETUP→RUNNING precondition (PRD §3.6) and the §2.7 state-before-business-rule precedence on RMA repair; both apparent failures were test-side issues.

ORCHESTRATOR NOTE: Step 7 subagent removed its results.*.json on exit; orchestrator independently re-ran the 8-round parallel sweep and confirmed all 8 rounds 65/65 (results.{1..8}.json regenerated and present).

## Step 8: Finalize PRD — 2026-06-20T18:48:00.000Z

Step 8 ran (Step 7 had 1 deletion + test fixes, so skip condition not met). Result: PRD_FINALIZED.md is byte-identical to PRD.md (0 lines changed, 0% delta). Both Step 7 diff items were analyzed and neither warranted a PRD edit.

Item 1 — Deleted test test_repair_no_fault_found_rejected (RMA repair of NO_FAULT_FOUND TRIAGED): subject = error code from POST /rmas/{id}/repair when TRIAGED but failure_class==NO_FAULT_FOUND. Impl (repair_rma app.py:1263–1279): state guard status!=TRIAGED → ERR_INVALID_STATE, then business guard failure_class==NO_FAULT_FOUND → ERR_VALIDATION (422). PRD §3.10 frames "only when failure_class is not NO_FAULT_FOUND" as a business rule with no catalogue code, and §2.7 already uniquely routes it to ERR_VALIDATION (state validity checked first, passes). PRD already determines the behavior → NO EDIT (pure test bug).

Item 2 — Fixture/helper additions (setup_kitted_for_start) + 4 test call-site SETUP-step fixes: subject = precondition state for starting a work order. Impl (start_work_order app.py:745–756): guard status!=SETUP → ERR_INVALID_STATE; setup_work_order KITTED→SETUP; kit_work_order PLANNED→KITTED. PRD §3.6 already states verbatim "A ProductionPlanner may start a work order only while it is SETUP." → NO EDIT (pure test-setup bug).

Per-edit pre-edit search log: both items received the mandatory NO-NEW-MISMATCH enumeration (callsites/branches/cascades read in app.py + workflows.py + errors.py); neither produced an edit since PRD already pins both behaviors uniquely.

## Step 9: Complete PRD — 2026-06-20T18:55:00.000Z

Source: PRD_FINALIZED.md (byte-identical to PRD.md). Output: workspace/PRD_COMPLETED.md.

Line counts: 283 → 283 (all edits in-paragraph). Char delta: 45,552 → 46,689 (+1,137 chars).
Counts: 6 ambiguity-pins, 0 mismatch-revisions. (No outright PRD-vs-impl mismatches found; error catalogue, role table, response envelope, pagination, FIFO/cost formulas, compliance gates, validation ordering, and all state machines verified already uniquely pinned.)

Changes:
- §3.5 Planning a Run — insert — ambiguity — creating a work order against a BOM not RELEASED → ERR_VALIDATION (422); PRD prose only said "against a released BOM" without error code — app.py:648-649.
- §3.7 Serialization and Test — insert — ambiguity — passed_qty = count of units whose quality_status is exactly PASS, excludes REWORKED; PRD named the counter but never defined what it counts — workflows.py:227-228.
- §3.8 Finalizing Test — insert/revise — ambiguity — pinned branch priority (all-PASS/REWORKED branch evaluated first → PASSED regardless of FPY) and previously-undefined third case (outstanding BUILT/FAIL units with FPY ≥ 70 → ERR_INVALID_STATE 409, WO stays AT_TEST); PRD claimed "two finalize outcomes" with no priority/fallthrough — app.py:814-823.
- §3.9 Rework close — insert — ambiguity — replacement_qty must be > 0; non-positive → ERR_VALIDATION (422); PRD stated no constraint — app.py:1030-1031.
- §3.10 Field Returns — insert — ambiguity — routing a NO_FAULT_FOUND RMA to repair → ERR_VALIDATION (422) (business-rule rejection, not state error, since TRIAGED is a valid transition state); PRD stated the restriction without an error code — app.py:1270-1271.
- §3.11 Build-and-Test Driver — insert — ambiguity — each count ≥ 0 and sum must equal planned_qty; negative count or sum mismatch → ERR_VALIDATION (422); PRD stated the equality without an error code — app.py:1335-1339.

## PIPELINE COMPLETE — 2026-06-20T18:55:00.000Z

All 9 steps finished. Final state: 65 tests, all passing across an 8-round parallel per-test-server stability sweep (results.{1..8}.json present, 65/65 each). Task directory contains SCAFFOLD.yaml + 2 design indices, test_helpers/ (9 files), test_suite/ (conftest + 8 test files), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}.
