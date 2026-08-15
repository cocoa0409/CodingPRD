# Worklog — task_1556_sewer_cctv_inspection_rehabilitation

## Step 1: Create Task Directory — 2026-08-13T20:49:00.000Z

Task directory and workspace/ subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per invocation args; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T22:12:00.000Z

All three files exist, lint is clean, and all quality checks pass. Final summary:

## Summary — task_1556_sewer_cctv_inspection_rehabilitation

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1556_sewer_cctv_inspection_rehabilitation/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1082 calls scanned, 0 violations.)

**Surface counts:**
- Entities: **14** (SewerDistrict, Technician, InspectionCycle, PipeSegment, Lateral, CctvInspection, DefectObservation, RehabPlan, WorkOrder, WorkOrderLineItem, BypassPlan, CustomerNotice, WarrantyCase, FlowMonitoringPeriod)
- State machines: **8** — CctvInspection (cyclic QA-reject loop with auto-void at 3 rejects), WorkOrder (parallel execution_status × billing_status), WarrantyCase (RESOLVED→OPENED re-open cycle), RehabPlan (APPROVED→DRAFT revert with budget compensation), BypassPlan, CustomerNotice (system expiry sweep), InspectionCycle, FlowMonitoringPeriod
- Calculations: **4** (pacp_scoring, work_order_cost, infiltration_reduction_pct, lateral_reinstatement_progress)
- Validations: **10** priority tiers (auth → authz → existence → state → safety → safety/flow-control → constraint → temporal → referential → fiscal)
- Endpoints: **84** (incl. `POST /sewer/_clock/set_current_utc` with pinned default 2026-08-01T00:00:00Z, and 4 filtered-list GETs added to satisfy FK reverse-reachability)
- Error catalog: **41** codes (all referenced by ≥1 validation/transition)
- Roles: **5** (DistrictEngineer opaque; Coder/QaReviewer/CrewLead entity_backed:Technician; CustomerServiceRep opaque)
- Concurrency rules: **2** OCC rules (RehabPlan approve, WorkOrder line-item create), both 412 ERR_STALE_VERSION

**§1.8 difficulty instances: 21** — dual_variant_calc ×3 (PACP quick-rating vs weighted index on segment; provisional vs final invoice on work order; dry-weather vs storm-event I/I on flow periods), combinatorial_formula ×2 (mode a: 3-input mobilization tier with pinned MOB_LARGE-first evaluation; mode b: per-line round-half-up-then-sum, pinned against sum-then-round with a 1-cent divergence fixture), non_linear_state_machine ×3, transitive_cascade ×2 (depth-4 complete→plan→segment→laterals; depth-2 stand-down→bypass), priority_pair_validation_conflict ×2 (state-vs-safety p4/p5; constraint-vs-fiscal p7/p10), boundary_precision_check ×2 (inclusive &gt;= basin target 30.0; half-open buffered bypass adjacency at exactly end+30min), cross_entity_state_dependency ×3 (WorkOrder→BypassPlan, RehabPlan→CctvInspection, FlowMonitoringPeriod→PipeSegment), resource_temporal_overlap ×2 (half-open +buffered bypass windows vs closed-inclusive unbuffered flow windows), compensating_invariant ×2 (budget commit/release ledger; lateral reinstatement tally reset across CIPP cycle).

**§1.9 corner instances: 40** across all nine guide sections — entities 6, state_machines 5, calculations 4, validations 8, endpoints 4, errors 4, rbac 4, cross_cutting_layers 4, consistency_model 1.

**Notable design decisions:**
- Segregation-of-duties role model: the QA certifier must differ from the coding technician (`ERR_SOD_VIOLATION`), exercised via a dual-capability technician to isolate SoD from RBAC.
- PACP scoring dualism: quick_rating (ordinal, extent-blind, 9-capped count digits) vs structural_index (extent-weighted mean, 2dp round-half-up) persisted from the same certification — the rule-1 fixture uses defects {5-pt, 4×30m} yielding quick `5141` vs index `4.03`.
- Pinned rounding order in costing: per-line round-half-up then sum; the mode-(b) fixture (1.5 × 33333/33335/33337 cents) produces 300009 under the pinned order vs 300008 under sum-then-round.
- Two genuinely different interval semantics for rule 8: bypass windows half-open [start,end) with ±30-min buffer; flow-monitoring windows closed [start,end] inclusive with no buffer — adjacency is accepted in the former and rejected in the latter.
- Warranty auto-loop: creating a WarrantyCase synthesizes a linked WARRANTY_RE inspection (discoverable via the reverse-reachability GETs); third QA reject on a re-inspection bounces the case RE_INSPECTION→OPENED via system cascade.
- OCC `expected_*_version` values are always `${var}` captures from prior responses, never literals — lint rule (e) clean.

(Note: the first scaffold subagent run ended after the design phase without writing files; it was resumed and completed all writes, including chunked writes after a single-Write size limit was hit on SCAFFOLD_DIFFICULTY_DESIGN.yaml.)

## Step 3: Copy Shared Files — 2026-08-13T22:13:00.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T22:36:00.000Z

PRD generation complete and verified. Output: `workspace/PRD.md` (384 lines, 7,772 words). The two difficulty-design files were never opened.

## PRD Section List

- **§1. Introduction** (2 paragraphs: business context + audience/gating philosophy)
- **§2. Global Specifications & System-Wide Principles** — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (byte-identical to canonical source) · 2.3 Pagination · 2.4 The Logical Clock · 2.5 Common Resource Properties and Entity Identity · 2.6 Pipeline Hierarchy, Cascades, and Nested Retrieval · 2.7 Monetary Precision: Integer Cents and Per-Line Rounding · 2.8 Scoring and Measurement Precision · 2.9 Optimistic Concurrency Control · 2.10 The Validation Cascade
- **§3. Business Logic & Workflows** (pipeline-timeline grouping) — 3.1 District Onboarding and the Technician Registry · 3.2 Inspection Cycles and the Pipe Segment Inventory · 3.3 CCTV Inspection, Defect Coding, and QA Certification · 3.4 Rehabilitation Planning: Method Selection and Budget Commitment · 3.5 Work Order Execution and Unit-Priced Line Items · 3.6 Bypass Pumping and Customer Notification · 3.7 Completion, Post-Lining Acceptance, and Lateral Reinstatement · 3.8 Warranty Claims and Re-Inspection · 3.9 Flow Monitoring and Inflow/Infiltration Reduction
- **§4. Endpoint Definitions** (84-row table; Method/Path/Description/Authorized Roles only)
- **§5. Error Code Catalogue** (41-row table; Error ID/HTTP Status only). File ends at §5, no audit footer.

## Hard Contract Reports

**Contract 1 — Field-Name Coverage:**
- entities[].fields: 75 required, 75 present (exact backtick match), 0 missing
- endpoints[].request_body/input: 60 required, 60 present, 0 missing
- path params (`id`, `lateralId`, `defectId`, `lineId`): 4 required, 4 present inside §4 path tokens
- Status: PASS

**Contract 2 — Rule Coverage:**
- validations[] priority: 10 checked, 10 expressed in the ordered §2.10 cascade, 0 missing
- concurrency_rules[] OCC: 2 checked, 2 expressed (`expected_plan_version` on plan approval, `expected_work_order_version` on line-item create; both rejected with `ERR_STALE_VERSION` HTTP 412, stale-version framing only), 0 missing
- state_machines[].transitions: 41 checked, 41 fully expressed (incl. QA reject-at-3 auto-void with warranty-case fallback, work-order dual execution/billing dimensions, notice expiry sweep), 0 missing
- calculations[]: 4 checked, 4 fully expressed in reconstruction-safe prose (PACP quick-rating 4-char encoding + extent-weighted index with worked examples `5241`/`5141`/4.03; per-line round-then-sum with mobilization tiers 150000/400000/900000 cents and large-first evaluation; dual I/I reduction variants with baseline selector and inclusive target boundary; vacuous-true lateral gate with reset semantics), 0 missing
- validations[] conditions: all matchable to their error IDs in §2/§3 prose (all 41 error IDs mentioned), 0 missing
- endpoints[].side_effects / applies_to: 84 checked, expressed in workflow narratives (cascades, budget ledger sync/release, lateral reset, linked WARRANTY_RE creation), 0 missing
- entities[].fields[] structured content: defaults (48h notice lead, 12-month warranty, `BASELINE` purpose, `extent_m` 0, null-until-computed grades), types, and enum spellings all stated, 0 missing
- sibling-branch symmetry: method-compatibility triplet, mobilization tiers, billing triplet, void/cancel/withdraw from-state pairs — all rendered at equal density, 0 asymmetric
- Status: PASS

**Contract 3 — §3 Path Purity:**
- backtick tokens scanned: 460; tokens starting with `/`: 0; bare HTTP-method tokens: 0; method+path tokens: 0
- Status: PASS

## Zero-Silence Coverage Checklist

All scaffold sections fully rendered to prose: `scenario` → §1; `response_envelope` → §2.2 (verbatim) + §2.3; `entities` (14/14, incl. `common_fields: false` exception for DefectObservation) → §2.5/§2.6/§3; `state_machines` (8/8 machines, 41 transitions with preconditions + side effects + version bumps) → §3; `concurrency_rules` (2/2) → §2.9 + §3.4/§3.5; `calculations` (4/4 incl. constants, precision, variants) → §2.7/§2.8/§3.3/§3.7/§3.9; `validations` (10/10 priority tiers) → §2.10 + inline §3 triggers; `endpoints` (84/84 incl. logical clock, reverse-lookup lists, DELETE 204) → §3 narratives + §4 table; `errors` (41/41) → §2/§3 triggers + §5 table; `roles` (5/5 with identity translations: Coder/QaReviewer/CrewLead entity-backed to Technician, DistrictEngineer/CustomerServiceRep opaque) → §2.1 + §4 role columns.

## Step 6: Generate Implementation — 2026-08-13T23:10:00.000Z

All clean. Implementation is complete and functional.

## Summary

Generated a complete Python + Flask implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1556_sewer_cctv_inspection_rehabilitation/workspace/implementation/` for the Sewer CCTV Inspection & Rehabilitation PRD.

### Layout
- `start.sh` — executable launcher; guards pip install via `python3 -c "import flask"`; `exec python3 app.py` on `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry point, error handlers, blueprint registration
- `db.py` — In-memory stores (dicts keyed by id), logical clock starting at `2026-08-01T00:00:00Z`, never falls back to wall clock
- `errors.py`, `response.py`, `middleware.py` — `ApiError`, envelope helpers (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`, pagination `limit/offset/total_count/has_more`), auth via `X-User-ID`/`X-User-Role` against the five-role catalog
- `routes/` — one file per resource group: `districts.py`, `technicians.py`, `cycles.py`, `segments.py` (+ laterals), `inspections.py` (+ defects), `plans.py`, `work_orders.py` (+ line items + billing), `bypass.py`, `notices.py`, `warranty.py`, `flow.py`, `clock.py`
- `services/common.py` — pagination parsing, payload validators, hierarchical lookups, notice-expiry sweep, PACP scoring (structural_grade, om_grade, weighted structural_index rounded half-up to 2dp, 4-char quick_rating), mobilization-tier derivation + fee constants, per-line `round_half_up` money math, pump sizing (`25 gpm/inch` with `ceil(diameter_mm/25.4)` inches), buffered bypass window overlap

### Fidelity highlights
- Response envelope, pagination, role catalog, all error IDs / HTTP statuses taken verbatim from scaffold
- Logical clock defaults to `2026-08-01T00:00:00Z`; `POST /sewer/_clock/set_current_utc` is `DistrictEngineer`-only and runs the QUEUED→EXPIRED notice sweep; sweep also runs on every state-changing endpoint
- OCC on plan `approve` (`expected_plan_version`) and line-item create (`expected_work_order_version`) returning `ERR_STALE_VERSION` 412
- Validation priority honored: auth → RBAC → existence → state → personnel/SoD/cert → flow-control → business → temporal → referential → fiscal (`ERR_BUDGET_EXCEEDED` last)
- Auto-void at third QA reject (`reject_count: 3`), with cascading WarrantyCase RE_INSPECTION → OPENED
- Certification side effects: persists PACP scores to segment; POST_CIPP acceptance rule flips `rehab_status` to `WARRANTY` when a COMPLETED WO exists and all active laterals are reinstated
- Work-order `complete` cascade: stamps `completed_at`, derives `warranty_expires_at` (month-arithmetic), recomputes final line cents, bubbles plan EXECUTING→COMPLETED, releases district budget, sets segment REHABILITATED + `last_rehab_completed_at`, resets active laterals for CIPP
- Bypass approval: pump-size check (priority 6) evaluated before window-conflict check (priority 8), half-open intervals widened by ±30 min on both ends
- Flow period: 168 h minimum, closed-interval overlap (inclusive endpoints), POST_REHAB gating on REHABILITATED/WARRANTY segment, analyze picks baseline by greatest `window_end` (tie: latest `created_at`), computes both reduction variants rounded half-up to 1dp, `basin_target_met` uses dry-weather only with inclusive `>=`

### Verified via smoke tests
- Boot from clean process via `bash start.sh` on default port 10000 — store starts empty, auth headers enforced, error envelope correct
- Full happy path: district → technicians → cycle open → segment → inspection schedule → start → begin-coding → defect coding → submit-qa → certify (SoD enforced; `ERR_UNAUTHORIZED` when coder tried to act as QA) → plan create/propose (method compatibility) → approve (OCC) → WO create (mob tier MOB_SMALL for 200 mm/100 m) → line item with OCC → provisional = 250 000 + 150 000 = 400 000 → mobilize bubbles plan EXECUTING + segment IN_PROGRESS
- One PRD-fidelity fix during testing: `pacp_code` regex relaxed from `{2,6}` to `{1,6}` since the PRD explicitly cites `'B'` as a valid code

No entities seeded at startup; storage is in-memory dicts only (no SQLite / JSON / tmp files).

## Step 5: Generate Unit Tests — 2026-08-13T23:30:00.000Z

Generation complete for `task_1556_sewer_cctv_inspection_rehabilitation`. All work stayed inside the task directory.

## What was generated

**`test_helpers/` (Stage 1, 9 files)**
- `types.py` — all 14 entity TypedDicts + status/role enums; `DefectObservation` correctly carries only `id` + `created_at` (no `updated_at`/`version`, per PRD §2.5 append-only rule)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (84 endpoints)
- `api_errors.py` — all 41 error IDs with HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions; `assert_defect_observation` actively asserts absence of `updated_at`/`version`
- `factories.py`, `constants.py` (MOB fee tiers, 168h monitoring, 30-min bypass buffer, 48h/12mo defaults), `test_users.py` (opaque constants for DistrictEngineer/CustomerServiceRep; `make_coder/qa_reviewer/crew_lead_headers(user_id)` builders for the three entity-backed roles)
- `fixtures.py` — composite builders: `setup_certified_segment`, `setup_plan_with_work_order` (OCC version threading via GET-before-write on both plan-approve and line-item-create), `setup_completed_spot_repair`, `setup_cipp_ready_to_complete` (laterals + POST_CIPP certification), warranty-chain and flow-period helpers, `setup_notice_ctx`

**`test_suite/` (Stage 2, 82 tests across 9 files + conftest)**

## Audit results (all machine-verified)

- **Coverage:** all 21 difficulty instances have exactly 2 tests; all 40 non-stub corner instances have exactly 1 test (no corner stubs exist in this task). Tag audit: every test has exactly one `Design:` line, as the last docstring line, resolving to a real instance name.
- **Citation:** every docstring's `PRD §x.y: "..."` quotation survives whitespace-normalized literal grep against `workspace/PRD.md` — 0 failures.
- **Collection:** `pytest --collect-only` collects 82 tests cleanly; both trees compile.
- **No skips:** zero `skip`/`skipif`/`xfail` markers; zero instances dropped — PRD covers every instance, including the two priority-pair instances (PRD §2.10 explicitly enumerates the fixed validation order) and both OCC rules (PRD §2.9).

## Key design decisions

- **State-vs-SoD priority pair** is tested bidirectionally: certify in CODING yields `ERR_INVALID_STATE`; the same actor after submit-qa yields `ERR_SOD_VIOLATION`, proving the §2.10 ordering both ways.
- **Boundary tests use both sides where the instance documents them**: bypass adjacency accepted at exactly buffered-end touch (13:00 vs 12:30 buffered) and rejected at 12:29; flow-period closed-interval sharing rejected at shared endpoint, disjoint day-after accepted; notice send at exactly `event_start − 48h` succeeds, +1 minute fails.
- **`sent_at` assertion** uses a `startswith("2026-08-12T00:00:00")` prefix rather than exact-string equality, because PRD leaves sub-second formatting of `sent_at` open (two-reader rule).
- The `segment_missing_required_field` test was kept (rather than skipped as silent): `ERR_INVALID_REQUEST` is the catalogue's only 400 and has PRD-prose triggers, so the outcome is uniquely derivable.

## Step 7: Run Tests and Iterate — 2026-08-13T23:55:00.000Z

All 8 rounds passed 82/82. The full sweep is clean.

## Summary

- **Iterations run:** 2 (initial sweep identified 46 failing tests, all 8 rounds deterministic; post-fix sweep: all 8 rounds 82/82).

- **Tests deleted:** None.

- **Fixes applied to `test_helpers/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1556_sewer_cctv_inspection_rehabilitation/test_helpers/fixtures.py` — `setup_plan_with_work_order`: reordered to `propose → approve → create_work_order → add_line_item`. The previous fixture created the work order while the plan was still PROPOSED, violating PRD §3.5 ("A `DistrictEngineer` creates the work order under an `APPROVED` plan") and §4 ("Issue a WorkOrder under an APPROVED plan"). With `approve=False`, no work order is created and `ctx["work_order"]` is None.

- **Fixes applied to `test_suite/` (test logic, all to comply with PRD §3.5's "under an APPROVED plan" rule):**
  - `test_04_rehab_planning_and_budget.py::_setup_two_plans_same_segment` — approve P1 before creating its WO; drop the WO/line staging on P2 (uniqueness check needs only the PROPOSED status).
  - `test_04_rehab_planning_and_budget.py::test_error_budget_exceeded_on_approve` — restructured via reopen cycle (approve → stage lines → reopen → re-propose → approve) so the plan carries a non-zero provisional into the failing approval, which is the only PRD-reachable path for `ERR_BUDGET_EXCEEDED` on approve.
  - `test_04_rehab_planning_and_budget.py::test_occ_line_item_create_stale_work_order_version` — flipped `approve=False` → `approve=True` so the WO exists for line-item creation.
  - `test_05_work_order_costing.py::test_mobilization_tier_large_when_both_predicates_fire` and `test_mobilization_tier_large_fee_joins_cost_rollup` — added `approve_plan` before `create_work_order`.
  - `test_05_work_order_costing.py::test_per_line_rounding_then_sum_line_values`, `test_per_line_rounding_then_sum_plan_total`, `test_provisional_cost_constants_applied_mob_standard_tier` — flipped `approve=False` → `approve=True`.
  - `test_06_bypass_flow_control.py::_setup_full_replace_two_work_orders`, `test_mobilize_full_replace_blocked_until_bypass_approved`, `test_mobilize_full_replace_succeeds_after_bypass_approved`, `_setup_in_work_with_active_bypass`, `test_bypass_approve_reject_action_endpoints`, `test_activate_bypass_before_window_start_rejected` — flipped `approve=False` → `approve=True` and removed now-redundant manual `approve_plan` calls. Removed unused `approve_plan` import.

- **Fixes applied to `implementation/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1556_sewer_cctv_inspection_rehabilitation/workspace/implementation/services/common.py::recompute_plan_provisional` — when the plan is APPROVED or EXECUTING, propagate the provisional-total delta to the district's `budget_committed_cents`. PRD §3.1 requires `budget_committed_cents` be "maintained by the system as the running sum of provisional totals over the district's plans that sit in `APPROVED` or `EXECUTING` status"; the prior implementation only adjusted it at approve/reopen/complete, which broke the running-sum invariant whenever line items were added or corrected after approval.

## Step 8: Finalize PRD — 2026-08-14T00:05:00.000Z

Both edits applied and verified against all enumerated implementation paths. Final report:

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1556_sewer_cctv_inspection_rehabilitation/workspace/PRD_FINALIZED.md`

**Line counts / delta:** PRD.md 384 lines (55,231 chars) → PRD_FINALIZED.md 384 lines (55,714 chars). Line delta 0.0% (edits are inline within existing paragraphs); char delta +0.87%.

**Step-7 item triage:** Of the diff items, only two required PRD edits. The `_setup_two_plans_same_segment` restructure, the `test_error_budget_exceeded_on_approve` reopen-cycle restructure, and every `approve=False` → `approve=True` flip were pure fixture/test conformance to a rule PRD §3.5 already pinned ("under an APPROVED plan"); the reopen-cycle path relies only on already-pinned behavior (§3.4 reopen rule, proposal-time recompute, fiscal check last). No edits for those.

**Changes (one bullet each):**
- §3.5 — revise — work-order issuance paragraph now pins the concrete gate: the plan must sit in `APPROVED` status at issuance, and issuing under any other status, `EXECUTING` included, fails with `ERR_PLAN_NOT_APPROVED` (PRD previously said "under an APPROVED plan" without naming the error or foreclosing the loose "approved-or-later" reading) — `workspace/implementation/routes/work_orders.py:71-72`.
- §3.5 — insert — line-item paragraph now states that every provisional-total recompute on a plan in `APPROVED` or `EXECUTING` shifts the district's `budget_committed_cents` by the same delta (triggered by line-item add/correct, work-order creation, work-order cancellation), preserving the §3.1 running sum — `workspace/implementation/services/common.py:296-302` (the Step 7 implementation fix), with callers at `work_orders.py:92, 358, 446, 506` and `plans.py:132`.

**Per-edit pre-edit search log:**

*Edit 1 (§3.5 issuance gate):*
- (a) Subject: plan-status gate and error id on work-order issuance.
- (b) Enumerated paths: `work_orders.py::create_work_order` lines 60-94 (crew-lead existence 404 → plan-status check `!= "APPROVED"` → `ERR_PLAN_NOT_APPROVED` at line 71-72 → crew active/capability `ERR_NOT_ASSIGNED_CREW`); `work_orders.py::mobilize` lines 167-169 (accepts `APPROVED` *or* `EXECUTING`, already named in PRD §3.5 — deliberately untouched); §4 table row 292 ("Issue a WorkOrder under an APPROVED plan"); §5 catalogue (`ERR_PLAN_NOT_APPROVED` → 409 already present); §2.10 cascade (existence rank 3 precedes state rank 4 — consistent with impl ordering). Grep confirmed no test asserts this error id and no other endpoint creates work orders.
- (c) Wording scoped strictly to issuance ("creates the work order", "at that moment") and explicitly includes `EXECUTING` in the rejected set, so the mobilize gate's APPROVED-or-EXECUTING rule is not narrowed.

*Edit 2 (§3.5 ledger delta propagation):*
- (a) Subject: `budget_committed_cents` maintenance when a provisional recompute occurs on an active plan.
- (b) Enumerated paths: every writer of `budget_committed_cents` — `districts.py:60` (init 0), `plans.py:164-168` (approve `+=` provisional), `plans.py:190` (reopen `max(0, -=)`), `work_orders.py:328` (complete `max(0, -=)`), `common.py:296-302` (recompute `+= delta` only when plan is `APPROVED`/`EXECUTING` and delta non-zero); every `recompute_plan_provisional` caller — `plans.py:132` (propose, plan DRAFT → no propagation), `work_orders.py:92` (create WO adds mobilization fee to the ledger of an APPROVED plan), `work_orders.py:358` (cancel WO releases its contribution), `work_orders.py:446` (line add), `work_orders.py:506` (line correct; installed-qty-only updates yield zero delta → no-op). Also verified the approval-time fiscal check stays approval-scoped per §2.10 item 10 and that committed can transiently exceed budget via post-approval line adds (PRD-consistent; no new check introduced).
- (c) Wording conditioned on "a plan sitting in `APPROVED` or `EXECUTING`" and on the recompute "that moves" the total (mirrors the `if delta:` guard), with an illustrative trigger list, and makes no claim about approve/reopen/complete ledger writes, which §3.4/§3.7 already describe verbatim.

## Step 9: Complete PRD — 2026-08-14T00:15:00.000Z

All edits applied cleanly. Here is the summary.

## Result

**Source vs output:** `PRD_FINALIZED.md` (384 lines, 55,983 chars) → `PRD_COMPLETED.md` (384 lines, 60,801 chars). Char delta **+4,818**; 30 lines revised in place, no lines added or removed, no new sections.

**Counts:** 33 ambiguity-pins, 5 mismatch-revisions (38 distinct behavior pins across 30 edited paragraphs).

### Changes

- §2.1 — insert — ambiguity — entity-backed actor with unregistered / capability-lacking / inactive technician is rejected `ERR_UNAUTHORIZED` (403) — implementation/middleware.py:45-59
- §2.3 — insert — ambiguity — non-integer limit/offset, limit outside 1–100, negative offset → `ERR_INVALID_REQUEST` — implementation/services/common.py:16-29
- §2.3 — insert — ambiguity — `created_at` sort ties broken by `id` ascending — implementation/services/common.py:34
- §2.4 — insert — ambiguity — clock may be set to any instant, backward allowed, no monotonicity — implementation/routes/clock.py:18-19, db.py:49-50
- §2.5 — insert — ambiguity — `version` starts at 1 on creation — implementation/db.py:92-98
- §2.10 — insert — ambiguity — `ERR_CYCLE_NOT_OPEN` evaluated immediately after the certification-validity check on inspection start — implementation/routes/inspections.py:240-243
- §3.1 — insert — ambiguity — duplicate district `name`, out-of-range target, non-non-negative-integer knobs → `ERR_INVALID_REQUEST` — implementation/routes/districts.py:40-52
- §3.1 — insert — ambiguity — `capabilities` must be non-empty; duplicate `nassco_cert_number` → `ERR_INVALID_REQUEST` — implementation/routes/technicians.py:41-52
- §3.2 — insert — ambiguity — cycle window-order violation → `ERR_INVALID_REQUEST` — implementation/routes/cycles.py:42-43
- §3.2 — insert — ambiguity — `segment_ref` format illustrative (any non-empty string), duplicates 400; `diameter_mm` positive integer; `install_year` integer — implementation/routes/segments.py:66-77
- §3.2 — revise — mismatch — `min_structural_grade` filters on the segment's current stored `structural_grade` (not "worst certified"); non-integer value → 400 — implementation/routes/segments.py:117-123
- §3.2 — insert — ambiguity — lateral `active`/`reinstated` filters accept true/false/1/0, else 400 — implementation/routes/segments.py:167-182
- §3.3 — insert — ambiguity — scheduling: cycle must exist and be in segment's district (404), window inclusive of both endpoints, coder must be active with `CODER` capability (400) — implementation/routes/inspections.py:82-102
- §3.3 — insert — ambiguity — assigned-coder + cert-validity gates also guard begin-coding, submit-qa, defect append/remove — implementation/routes/inspections.py:172-181
- §3.3 — revise — mismatch — `pacp_code` is one to six uppercase chars (was "two to six"; impl regex `^[A-Z]{1,6}$` and PRD's own example 'B' is one char) — implementation/routes/inspections.py:24
- §3.3 — insert — ambiguity — negative `extent_m` → `ERR_INVALID_REQUEST` — implementation/routes/inspections.py:368-369
- §3.3 — revise — mismatch — removed the "scoring preview" claim; defect writes leave segment scores untouched until certification (impl exposes no preview) — implementation/routes/inspections.py:341-383
- §3.3 — insert — ambiguity — rejection applies the same capability/certification gates as certification — implementation/routes/inspections.py:184-193, 308
- §3.3 — insert — ambiguity — defect list filters by `family` — implementation/routes/inspections.py:393-395
- §3.4 — insert — ambiguity — basis inspection must exist and belong to segment (404); `CERTIFIED` enforced only at proposal — implementation/routes/plans.py:42-46, 128-129
- §3.4 — insert — ambiguity — missing/non-integer `expected_plan_version` → `ERR_INVALID_REQUEST` — implementation/routes/plans.py:155-159
- §3.4 — insert — ambiguity — reopen: cancelled work orders never block; budget decrement floored at zero; per-segment plan list filters by `status` — implementation/routes/plans.py:186-190, 77-79
- §3.5 — insert — ambiguity — issuance: unknown `crew_lead_id` → 404; inactive or incapable technician → `ERR_NOT_ASSIGNED_CREW` — implementation/routes/work_orders.py:67-76
- §3.5 — insert — ambiguity — line items addable in any execution status; missing/non-integer `expected_work_order_version` → 400 — implementation/routes/work_orders.py:413-431
- §3.5 — insert — ambiguity — line PATCH rules: corrections DE-only (`ERR_UNAUTHORIZED`/`ERR_INVALID_STATE`), installed_qty by assigned crew lead or DE, must be ≥ 0, empty update → 400 — implementation/routes/work_orders.py:462-510
- §3.5 — insert — ambiguity — FULL_REPLACE mobilize gate accepts bypass in `APPROVED` **or** `ACTIVE`; notice gate's "earliest event start" = earliest `event_start` among the work order's notices — implementation/routes/work_orders.py:171-186, 145-152
- §3.6 — insert — ambiguity — bypass proposal restricted to the assigned crew lead (`ERR_NOT_ASSIGNED_CREW`); window-order/non-positive-capacity → 400 — implementation/routes/bypass.py:41-51
- §3.6 — insert — ambiguity — activate/demobilize allowed for any `CREW_LEAD`-capable technician (not just the assignee); window check evaluated before the work-order status check — implementation/routes/bypass.py:135-168
- §3.7 — insert — ambiguity — `REJECTED` bypass plans never block completion — implementation/routes/work_orders.py:293-295
- §3.7 — revise — mismatch — reinstatement is idempotent, allowed for any lateral (active or not) regardless of work-order state; progress computed on demand, no stored field (PRD had claimed a stored "reinstatement progress" recompute) — implementation/routes/segments.py:187-197
- §3.7 — revise — mismatch — lateral reset fires only when the completing lining work order finishes its plan (last non-cancelled WO), not on every lining WO completion — implementation/routes/work_orders.py:322-337
- §3.7 — insert — ambiguity — `warranty_expires_at` = calendar-month addition with day-of-month clamped — implementation/routes/work_orders.py:269-281, 313
- §3.7 — insert — ambiguity — completion budget release floored at zero — implementation/routes/work_orders.py:328
- §3.8 — insert — ambiguity — case creation validates WO `COMPLETED` (400), cycle exists + same district (404), coder active + `CODER` (400), `scheduled_at` inside window inclusive (`ERR_OUTSIDE_CYCLE_WINDOW`) — implementation/routes/warranty.py:46-68
- §3.9 — insert — ambiguity — non-numeric close payload values → `ERR_INVALID_REQUEST` — implementation/routes/flow.py:144-146
- §3.9 — insert — ambiguity — zero baseline flow figure fails analysis with `ERR_INVALID_REQUEST` — implementation/routes/flow.py:182-183
- §3.9 — insert — ambiguity — `basin_target_met` compares the rounded, reported dry-weather figure against the target — implementation/routes/flow.py:184-186
- §3.9 — insert — ambiguity — analyzing a `CLOSED` `PRE_REHAB` period is permitted and returns null analysis fields while advancing to `ANALYZED` — implementation/routes/flow.py:196-206

Output file: /home/ubuntu/github/CodingPRD/tasks/task_1556_sewer_cctv_inspection_rehabilitation/workspace/PRD_COMPLETED.md
