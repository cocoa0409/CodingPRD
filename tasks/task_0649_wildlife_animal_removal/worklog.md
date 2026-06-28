# Worklog — task_0649_wildlife_animal_removal

Scenario: 649. Wildlife & Nuisance-Animal Removal (Critter Control style): inspection & species/entry-point assessment, trap/exclusion plan & quote, humane removal & relocation compliance, exclusion/repair (sealing) & sanitation, recurring monitoring & re-set, permit/regulated-species, warranty/callback, emergency

Difficulty: Expert

## Step 1: Create task directory — 2026-06-26

Task directory `tasks/task_0649_wildlife_animal_removal/` and `workspace/` were pre-created and pre-assigned (index 0649 fixed by orchestrator constraint). Skipped task-index scan per execution constraints.

## Step 2: Generate scaffold — 2026-06-26

The three scaffold artifacts are complete and pass clean lint.

**Domain:** Wildlife & Nuisance-Animal Removal (Critter Control style). Archetype: `workflow_orchestration` + `compliance_audit`; topology `hybrid`; state shape `compound`; role model `peer_roles`; layers: dual-variant calc, cascading side effects, OCC, rate/threshold triggers, derived-field reconciliation.

**Files written** (all under `tasks/task_0649_wildlife_animal_removal/`):
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**SCAFFOLD.yaml counts:**
- Entities: 15 — SpeciesProfile, Technician, ServiceAccount, Property, Inspection, EntryPoint, Quote, QuoteLineItem, WorkOrder, Permit, TrapPlacement, CaptureEvent, ExclusionRepair, MonitoringVisit, WarrantyClaim
- State machines: 6 — Inspection (linear), Quote (cyclic revision loop), Permit (branching APPROVE/DENY), WorkOrder (parallel removal_status × exclusion_status + compound auto-close), TrapPlacement, WarrantyClaim
- Calculations: 6 — quote_provisional_total, quote_final_total (dual-variant cost), infestation_risk_score (initial/residual dual-variant risk), relocation_distance (haversine threshold), warranty_window (datetime threshold), workorder_net_charge (waterfall/compensation)
- Validations: 15 (priority-ordered, categories auth→existence→state→OCC→safety→referential→temporal→constraint→fiscal)
- Endpoints: 61 (incl. `/_clock/set_current_utc` default 2026-04-01T00:00:00Z)
- Errors: 15
- Roles: 4 — Dispatcher (opaque), PropertyOwner (entity_backed:ServiceAccount), FieldTechnician (entity_backed:Technician), ComplianceOfficer (opaque)
- Concurrency rules: 1 — `cancel-stale-work-order` (OCC on WorkOrder.version, 412)

**§1.8:** 9 rule_ids × 2 = 18 instances. **§1.9:** 31 active instances + 7 excluded_because stubs across 9 taxonomy sections.

**Validation:** `scaffold_lint.py` → VERDICT: clean lint. `api_prefix` set to `""` (flat top-level resources).

## Step 3: Copy INSTRUCTION.md — 2026-06-26

Copied `./INSTRUCTION.md` → `tasks/task_0649_wildlife_animal_removal/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-26

**Output:** `workspace/PRD.md` (~295 lines)

**Sections covered:** §1 Introduction; §2 Global Specs (12 subsections: RBAC, fixed §2.2 envelope, pagination, common props/versioning, hierarchical consistency + nested retrieval, OCC on work-order cancel, monetary/risk precision, conserved trap kit, conserved-money principle, regulatory posture/compliance gates, logical clock, validation ordering); §3 Business Logic (10 subsections); §4 Endpoint table (63 endpoints); §5 Error catalogue (15 error IDs).

**Coverage:** 16 entities (all 70 field/param names verbatim), 4 roles, all 15 error IDs, all 6 state machines, all 5 calculations, OCC (work-order cancel + `/quotes` create endpoint-level OCC).

**Hard Contracts — all PASS:** Contract 1 (Field-Name Coverage 70/70), Contract 2 (Rule Coverage 0 missing), Contract 3 (§3 Path Purity 0 violations). §2.2 verified byte-identical to template. Design files (DIFFICULTY/CORNER) not read.

## Step 5: Generate unit tests — 2026-06-26

**test_helpers/ (9 files):** types.py (14 enums + 16 entity TypedDicts), api_client.py (~50 methods), api_errors.py (15 errors), assertions.py (per-entity + conserved-kit invariant), factories.py, constants.py, test_users.py (shared role headers + entity_backed builders: PropertyOwner→ServiceAccount, FieldTechnician→Technician), fixtures.py (composite setup tiers), __init__.py.

**test_suite/ (conftest + 4 test files, 67 tests):** test_01_quote_pricing_and_risk.py (12), test_02_workflows_and_cascades.py (14), test_03_gates_and_boundaries.py (16), test_04_money_concurrency_and_crud.py (25).

**Coverage (design-index-only):** Queue A — all 18 difficulty instances × 2 = 36. Queue B — all 31 non-stub corner instances × 1 = 31. Total 67 tests, each with exactly one verbatim `Design:` tag; 96 PRD citations verified verbatim; no skip/xfail; 7 corner stubs not translated.

**Instances skipped:** None beyond the 7 mandated excluded_because stubs.

**Key finding (handled):** Difficulty instance `dual_variant_calc/infestation_risk_initial_vs_residual_risk_domain` has an internal recipe inconsistency (asserts 48.0/42.0 but its setup creates EP1 as non-regulated → 34.0/28.0). Resolved by keeping each variant test internally PRD-consistent: initial-variant test uses regulated EP1 (48.0), residual-variant uses non-regulated species and asserts PRD-derivable 34.0/28.0.

## Step 6: Generate implementation — 2026-06-26

Complete Python + Flask impl at `workspace/implementation/`.

**Files:** start.sh (guarded launcher: pip install only if Flask import fails, then `exec python3 app.py`), app.py (60+ routes, error handlers, pagination, validation ordering; binds 0.0.0.0:$PORT default 10000, foreground, threaded=True), db.py (in-memory dict-per-entity, 15 tables, wiped on boot, UUID ids, monotonic _seq, no seeding), calculations.py (Decimal + ROUND_HALF_UP), services.py (cascades, derived-field recompute, kit conservation, state-machine helpers), clock.py (logical clock default 2026-04-01T00:00:00Z), response.py, errors.py, middleware.py, serialize.py, requirements.txt.

**Envelope:** Success meta{api_request_id req_*, api_request_timestamp ISO8601 .3f Z}, response_type, data. Error data{error_id, message}, response_type:"error". Pagination limit/offset/total_count/has_more (default 10, max 100). Auth X-User-ID/X-User-Role. OCC expected_work_order_version (cancel) + expected_inspection_version (quote create).

**State machines:** Quote cyclic loop; WorkOrder compound (parallel removal_status × exclusion_status + auto-close + cancel cascade); Permit branching + deny-cascade + approve-bubble; Property posture derivation; TrapPlacement; WarrantyClaim.

**Calculations:** round-then-sum provisional/final totals + 15% emergency surcharge; infestation risk (severity 1.0/2.0/3.5, ×1.5 regulated, cap 1000.0, 2dp, initial vs residual); haversine (R=3958.8mi, 2dp, inclusive); conserved-money refund (+7500 sanitation); 30-day inclusive warranty window vs logical clock.

**Verification:** 4 self-contained smoke suites against live server all passed; start.sh boots clean, binds 0.0.0.0.

## Step 7: Run tests and iterate — 2026-06-26

**Iterations run:** 2 (1 diagnostic baseline + 1 verification). Baseline: 62/67 passing in all 8 rounds with 5 deterministic (non-flaky) failures. Final: all 8 rounds 66/66 clean.

**Tests deleted (1):**
- `test_complete_inspection_with_no_entry_points_rejected` (test_04_money_concurrency_and_crud.py) — ERROR PRECEDENCE SILENCE. Asserted completing a DRAFT inspection with zero entry points yields `ERR_EMPTY_SET`. PRD §3.2 states the "at least one entry point" precondition but never assigns an error_id to its violation; only `ERR_INVALID_STATE` is named for inspection completion. `ERR_EMPTY_SET` is anchored exclusively to quote-send (§3.3) and trap-pull (§3.6). Two divergent PRD-faithful implementations exist → not uniquely derivable. Scaffold rule: Corner/state_machines/inspection_complete_with_no_entry_points_rejected.

**Fixes applied to test_suite/ (4):**
- `test_01_quote_pricing_and_risk.py` — `test_infestation_risk_regulated_branch_multiplies_by_one_point_five`: corrected assertion 42.0 → 21.0 (bad test arithmetic: 2 × 2.0 × 3.5 × 1.5 = 21.0). Impl was PRD-faithful (§3.4).
- `test_02_workflows_and_cascades.py` — `test_accept_cascade_workorder_risk_permit_posture_depth4`: replaced private non-exported helper `th._get_list` (AttributeError under `import *`) with public barrel-exported `validate_paginated`; added it to imports.
- `test_04_money_concurrency_and_crud.py` — `test_cancel_settles_net_charged_to_performed_subtotal` and `test_cancel_conserves_money_net_plus_refund_equals_provisional`: both wrongly assumed setting a trap flips a TRAP line's `performed`. Per PRD §3.6, `performed` flips only when `removal_status` reaches CLEARED. Added a `pull_trap` call after `set_trap` so removal advances to CLEARED (net=12000 / refund=14000). Added `pull_trap` to imports.

**Fixes applied to test_helpers/:** None.
**Fixes applied to implementation/:** None — implementation was PRD-faithful for every failure; all 5 root causes were in the test artifact (4 test-suite mistranslations + 1 PRD-silent error_id assertion).

**Orchestrator independent re-verification:** Re-ran the 8-round foreground sweep (subagent's per-iteration results files were transient). All 8 rounds confirmed 66/66 passed, 0 failed. Durable `results.{1..8}.json` written to `workspace/implementation/`.

**Step 8 decision:** NOT skipped — Step 7 had 1 deletion + 4 test_suite fixes (non-zero), so PRD-silence/mismatch sites exist to finalize.

## Step 8: Finalize PRD — 2026-06-26

**Output:** `workspace/PRD_FINALIZED.md` (295 lines; PRD.md = 295 lines; ~0.3% content delta — one sentence-level in-place revision).

**Changes (1):**
- §3.2 (Inspection completion) — revise — pinned that a completion attempt failing the entry-point precondition (zero entry points) or the posture precondition (REGULATORY_HOLD) yields `ERR_INVALID_STATE`, not `ERR_EMPTY_SET`, and that `ERR_EMPTY_SET` is never raised by inspection completion — impl app.py:301 (empty entry points), app.py:304 (REGULATORY_HOLD).

Traces to the single deleted test (ERROR-PRECEDENCE SILENCE). The other four Step 7 items were pure test/fixture bugs where impl was already PRD-faithful (no PRD edit): regulated-branch arithmetic (§3.4 determines 21.0); `th._get_list`→`validate_paginated` (test-helper API bug); the two cancel tests adding `pull_trap` (§3.2/§3.6 already determine `performed` flips only at removal_status=CLEARED).

**Pre-edit search log:** subject = error_id for inspection-complete precondition failures + scope of `ERR_EMPTY_SET`; enumerated app.py:290-308 (complete_inspection 3 branches), app.py:311-321 (cancel_inspection), and both `ERR_EMPTY_SET` sites (app.py:495 quote-send, app.py:926 pull-trap); confirmed `ERR_EMPTY_SET` never used on inspection completion. Wording scoped to both precondition failures + narrow exclusion so it doesn't contradict the two legitimate `ERR_EMPTY_SET` sites.

## Step 9: Complete PRD — 2026-06-26

**Output:** `workspace/PRD_COMPLETED.md` (295 lines, 46,672 chars; source PRD_FINALIZED.md 295 lines, 45,443 chars; char delta +1,229; all in-paragraph inserts, no line-count change).

**Counts:** 8 ambiguity-pins, 0 mismatch-revisions (full impl scan found no PRD passage contradicting impl; every gap was PRD silence on a uniquely-resolved detail).

**Changes (8):**
- §2.3 Pagination — insert — ambiguity — out-of-range clamp-to-nearest-bound (limit<1→1, >100→100; negative offset→0; unparseable→default) — middleware.py:29-48
- §2.4 Common Resource Properties — insert — ambiguity — `version` initial value = 1 — db.py:51-61
- §3.3 Quoting — insert — ambiguity — new quote born with provisional_total_cents and final_total_cents both 0 until computed at send/close — app.py:404-406, calculations.py:50-66
- §3.4 Acceptance — insert — ambiguity — work order residual_risk_score initialized 0 at creation, recomputed only at close — app.py:555, services.py:116-121
- §3.4 Acceptance — insert — ambiguity — initially-absent permit_number serialized as null (not omitted) — app.py:571, serialize.py:11-14
- §3.6 Captures — insert — ambiguity — matching TRAP line resolution: per distinct species among non-cancelled (SET/SPENT/EMPTY) placements, first not-yet-performed TRAP line for that species — services.py:132-186
- §3.6 Exclusion repairs — insert — ambiguity — matching EXCLUSION line = first not-yet-performed EXCLUSION line whose species_id equals targeted entry point's species — app.py:1042-1058
- §3.9 Warranty — insert — ambiguity — close timestamp = work order updated_at at the OPEN→CLOSED auto-close instant (logical-clock reading) — services.py:229-236, app.py:1190-1194

**Left unchanged (already covered):** trap-placement gate ordering (§2.12/§3.8); datetime-format validation deferral (impl detail); FK existence checks (§2.5 generic); empty-data clock response (§2.2).

---

## PIPELINE COMPLETE — 2026-06-26

All 9 steps finished. Final state: 8-round stability sweep 66/66 all rounds; PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md all present. Implementation PRD-faithful (0 impl fixes in Step 7). PRD_COMPLETED.md exists on disk.
