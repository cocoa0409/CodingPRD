# Worklog — task_0162_appraisal_management_company

## Step 1: Create task directory — 2026-06-05T02:47:58.000Z

Created `tasks/task_0162_appraisal_management_company/` and `tasks/task_0162_appraisal_management_company/workspace/` (pre-assigned directory; no ./tasks index auto-scan per orchestration constraint).

## Step 2: Generate scaffold (Expert difficulty) — 2026-06-05T03:16:30.000Z

Generated the Expert-level scaffold for **task_0162_appraisal_management_company** (AMC: order intake/assignment, panel rotation, turnaround SLA, USPAP/UAD compliance, revision requests, fee split, reconsideration of value, AIR independence firewall). All three files written to the task dir and pass `scaffold_lint.py` — **VERDICT: clean lint** (36 endpoints, 11 entities, 18 §1.8 instances, 28 §1.9 active instances, 355 calls scanned, FK reverse-reachability satisfied including the self-referential `Assignment.supersedes_assignment_id`).

**Archetype/profile:** workflow_orchestration + compliance_audit; hybrid topology; cyclic state machines; segregation_of_duties role model; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, selector_policy.

**SCAFFOLD.yaml contents:**
- **11 entities:** Lender, Appraiser, Property, Order, Assignment, Report, ComplianceReview, RevisionRequest, ReconsiderationOfValue, FeeSplit, FirewallEvent (append-only, `common_fields:false`).
- **5 state machines / 27 transitions:** Order (7-state lifecycle w/ cancel cascade), Assignment (cyclic via REVISION), Report (cyclic revision loop), ComplianceReview (PASS/CONDITIONAL/FAIL branch), ReconsiderationOfValue (VALUE_CHANGED/UPHELD fork).
- **5 calculations:** fee_split_computation (provisional↔final variants, per-component-then-sum rounding pinned, floor clamp), appraiser_panel_score (weighted, nested-min, conditional branch), rotation_selector (eligibility/ranking/tie-break→created_at, empty-pool fallback), turnaround_sla (projected↔actual variants, strict-greater breach), rov_value_delta (>10% threshold).
- **14 validations** (priority-ordered; AIR firewall at priority 2 ahead of generic authZ), **14 errors**, **1 concurrency rule** (OCC on Order.version for assignment supersede, 412), **5 roles** (AMCCoordinator/ComplianceReviewer opaque; Appraiser/LenderUser entity_backed; PlatformAdmin override + `/_clock` test endpoint).

**§1.8 difficulty design:** all 9 rules × 2 = 18 instances, each grounded and with executable setup→trigger→assert chains carrying pre-computed literals (fee splits 30000/27500/52000/5000-floor; panel scores 0.3000/0.0; SLA 120/72; ROV delta 10.00 boundary vs 12.00; turnaround 48h). Covers depth-3 compliance-FAIL cascade and depth-2 ROV→value→fee cascade, fee-conservation and load-count compensating invariants, appraiser (half-open+60min buffer) vs property (closed, no-buffer) overlap semantics on distinct resources.

**§1.9 corner design:** 9 sections (entities/state_machines/calculations/validations/endpoints/errors/rbac/cross_cutting/consistency_model), 28 active corners + 6 `excluded_because` stubs (all referencing valid §1.8 instances). Breadth covers creation/404/required/defaults/system-field/enum/immutability/pagination/parent-FK, invalid-transition/terminal-lockdown/initial-state/cascade, fee-floor/SLA-rush, budget boundary, invalid-window, second-review-required, RBAC denials (including SoD + AIR firewall), OCC version-increment + stale-version on two endpoints.

Scenario-design note flagged to downstream: the AIR firewall is modeled as a priority-2 business_safety check that supersedes generic authorization for LenderUser on the three firewalled endpoints (returns ERR_AIR_FIREWALL_VIOLATION + logs a FirewallEvent rather than ERR_UNAUTHORIZED); non-Lender unauthorized actors fall through to priority-3 authZ.

## Step 3: Copy shared files — 2026-06-05T03:18:17.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0162_appraisal_management_company/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-05T03:23:56.000Z

Generated `workspace/PRD.md` (301 lines, prose PRD for the AMC API, mount prefix `/amc`).

**Structure**
- §1 Introduction (3 paragraphs: AMC role, dual regulatory pressure of AIR independence + compliance loop, design goal).
- §2 Global Specifications — 10 subsections: 2.1 RBAC + identity translation, 2.2 Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 AIR Firewall, 2.5 State Propagation/cascades, 2.6 Common Resource Properties, 2.7 Monetary Precision + fee-conservation invariant, 2.8 OCC on Orders, 2.9 Nested Retrieval left-to-right, 2.10 Validation Ordering (full 14-priority list).
- §3 Business Logic — 9 subsections: 3.1 intake/lender panel/budget, 3.2 assignment + rotation selector, 3.3 accept/decline + window scheduling, 3.4 report submit/resubmit, 3.5 compliance review + revision cascade, 3.6 fee split, 3.7 reconsideration of value, 3.8 completion/cancellation/appraiser scoring, 3.9 turnaround SLA.
- §4 Endpoint table (4 columns, 36 endpoints). §5 Error table (2 columns, 14 errors).

**Entities documented (11):** Lender, Appraiser, Property, Order, Assignment, Report, ComplianceReview, RevisionRequest, ReconsiderationOfValue, FeeSplit, plus audit-only FirewallEvent (explicitly noted as `common_fields:false` — only `id`/`created_at`, no `updated_at`/`version`).

**State machines (5):** Order (PLACED→ASSIGNED→IN_PROGRESS→IN_QC→DELIVERED→COMPLETED, +CANCELLED, +IN_QC→IN_PROGRESS revert), Assignment (OFFERED→ACCEPTED/DECLINED, ACCEPTED↔REVISION cyclic, →COMPLETED/CANCELLED), Report (SUBMITTED→UNDER_REVIEW→{ACCEPTED|REVISION_REQUESTED→RESUBMITTED}, →REJECTED), ComplianceReview (PENDING→PASS/CONDITIONAL/FAIL), ReconsiderationOfValue (REQUESTED→UNDER_REVIEW→VALUE_CHANGED/VALUE_UPHELD). The depth-3 compliance-fail cascade and its reverse revision-loop close are described in both directions.

**Calculations (5), all in precise prose with constants embedded:** fee_split_computation (waterfall, per-component round-half-up then sum, 10% rush premium, 5%/round penalty, 5000-cent floor, AMC residual; PROVISIONAL/FINAL variants), appraiser_panel_score (status branch→0, weighted 0.4/0.3/0.3 blend, load cap at 5, 4-decimal round-half-up), rotation_selector (eligibility filter + panel_score DESC, active_count ASC, last_assigned_at ASC nulls-first, created_at ASC tie-breaks, never id), turnaround_sla (projected lookup 120/96/72 hours, −48 rush; actual floored hours; strict-greater breach, equal=on-time), rov_value_delta (abs %, 2-decimal round-half-up, strict-greater 10% threshold).

**Validations (14, priority-ordered)** rendered as the §2.10 normative ordering; AIR firewall precedence over generic auth made explicit; OCC stale-version (`expected_order_version` on the three order ops, ERR_STALE_ORDER_VERSION/412) framed purely in stale-version terms.

**Roles (5):** AMCCoordinator, ComplianceReviewer, Appraiser, LenderUser, PlatformAdmin — each identity translated (Appraiser→entity_backed:Appraiser, LenderUser→entity_backed:Lender, other three opaque).

All three doc-generator Hard Contracts PASS (Field-Name Coverage, Rule Coverage, §3 Path Purity); §2.2 verbatim block intact; §4 = 4 columns/36 rows; §5 = 2 columns/14 rows; the two withheld design files were not opened.

## Step 5: Generate unit tests — 2026-06-05T03:45:56.000Z

**Stage 1 — `test_helpers/` (9 modules):**
- `types.py` — role/status enums + entity TypedDicts; `FirewallEvent` correctly modeled audit-only (id + created_at, no updated_at/version per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)`, one method per `/amc` endpoint, with per-test-server connection hardening
- `api_errors.py` — `ApiErrorId` + HTTP map (ERR_INVALID_REQUEST=422 per PRD §5), registered with framework
- `assertions.py` — per-entity asserts + `assert_fee_conservation`
- `factories.py`, `constants.py` (fee/SLA/ROV/window thresholds)
- `test_users.py` — opaque roles as shared constants; `make_appraiser_headers` / `make_lender_user_headers` per-instance builders for the two entity-backed roles
- `fixtures.py` — composite setups incl. clock-pinned lifecycles (`setup_order_in_qc`, `setup_order_delivered`, `setup_order_completed_after_one_revision`, `setup_order_completed_clean`, `setup_rov_under_review`)

**Stage 2 — `test_suite/` (8 files + conftest, 63 test functions):**
- Queue A (Difficulty): **36 tests**, all 18 instances covered ≥2 each
- Queue B (Corner): **27 tests**, all 28 non-stub instances covered ≥1

**Validation passed:** every test carries exactly one `Design:` tag resolving to a real instance; no broken/stub/dual/untagged tags; all 6 `excluded_because` stubs verified to cross-reference real difficulty instances (not translated); all 103 docstring PRD quotes are literally verbatim in PRD.md; no skip/xfail markers; no scaffold leakage; 63 tests collect cleanly.

**1 instance skipped (gap left as gap):**
- `Corner/cross_cutting/occ_stale_order_version_assignment_supersede` — its asserted outcome (ERR_STALE_ORDER_VERSION on a second supersede carrying a stale version) is **not uniquely derivable**. After the first reassign succeeds the latest assignment is OFFERED, so the reassign state-precondition ("latest assignment in DECLINED/CANCELLED") also fails; under PRD §2.10's normative priority, state legality (priority 7) preempts OCC (priority 8), so a faithful PRD-only implementer would return ERR_INVALID_STATE, not ERR_STALE_ORDER_VERSION. The clean OCC-on-assign/cancel path is still covered by `Corner/errors/stale_order_version_on_order_cancel_returns_412` (cancel from ASSIGNED is a valid transition, isolating the version check). The same ambiguity is why the version-increment test asserts before+1 relatively rather than the literal `version==2` (PRD §2.6 pins increment-by-one but not the starting value).

## Step 6: Generate implementation — 2026-06-05T03:45:56.000Z

### Files created (in `workspace/implementation/`)
- `start.sh` — foreground launcher; guards `pip install` on a `flask` import check, reads `$PORT` (default 10000), `exec python3 app.py`
- `requirements.txt` — `flask==3.0.3`
- `app.py` — Flask entry point, blueprint registration, error handlers (ApiError → envelope; 404/405 → `ERR_NOT_FOUND`; catch-all → 500), binds `0.0.0.0:$PORT`, `threaded=True`
- `clock.py` — pinnable server clock; ISO-8601 UTC with exactly 3 fractional digits + `Z`; parse helper
- `db.py` — in-memory dict stores (one per entity), `stamp_create`/`touch` (sets `id`/`created_at`/`updated_at`/`version`; `mutable=False` for FirewallEvent), internal `_created_dt` sort key. **No seeding** — empty on every boot
- `errors.py`, `response.py`, `middleware.py` — error catalog/classes, success/array/error envelope helpers, auth + RBAC (PlatformAdmin override)
- `routes/` (8 blueprints): `lenders`, `appraisers`, `properties`, `orders`, `assignments`, `reports`, `compliance_reviews`, `reconsiderations`, `clock_route`
- `services/`: `calculations`, `domain` (counters/scoring/committed-fee/fee-split/rotation), `cascade`, `firewall`, `validate`, `pagination`, `serialize`

### Endpoints: all 36 from the PRD/scaffold table implemented and smoke-tested.

### Structure of the hard parts
- **State machines** — enforced per-endpoint with explicit from-state guards (`ERR_INVALID_STATE`); cascades centralized in `services/cascade.py` (`open_revision_cascade` for the depth-3 compliance-fail loop: Report→REVISION_REQUESTED → Assignment→REVISION+round++ → Order IN_QC→IN_PROGRESS + fee-split penalty recompute; `deliver_cascade` for PASS/CONDITIONAL). Each touched resource bumps its own `updated_at`/`version`; Order version increments on every own transition.
- **Calculations** (`Decimal` + `ROUND_HALF_UP`, never float) — fee split per-component-then-sum (base, 10% rush premium, per-round 5% penalty summed, 5000-cent floor, AMC = conserved residual); panel_score (weighted 0.4/0.3/0.3, nested-min load factor, 4dp, 0 when not ACTIVE); SLA lookup (120/96/72, −48 rush) + floored actual turnaround with strict-greater breach; ROV delta (2dp, strict-greater 10% threshold).
- **Rotation selector** — eligibility filter (ACTIVE, license_state==property, on lender panel, not-declined-on-order, active<5) then sort `panel_score DESC, active ASC, last_assigned_at ASC NULLS FIRST, created_at ASC` (never id).
- **Validations** — implemented in the exact PRD §2.10 priority order: auth(1) → firewall(2, before generic auth, logs FirewallEvent) → authz(3) → existence(4) → eligibility(5) → revisability(6) → state(7) → OCC(8) → appraiser-window(9) → property-window(10) → window-validity(11) → second-review(12) → budget(13) → field-shape(14). Verified state(7) surfaces before stale-version(8).
- **OCC** — `expected_order_version` required on assignment-create/cancel/complete; `ERR_STALE_ORDER_VERSION` (412) on mismatch.
- **Computed fields** recomputed lazily from the assignment store (appraiser counters, committed_fee) to keep cascades consistent.

### PRD ambiguities resolved
1. **Provisional FeeSplit appraiser share at placement** — no appraiser exists at placement, so the split is created with `appraiser_fee_cents=0`/`amc=fee`, then recomputed to the gross appraiser share (variant stays PROVISIONAL) at assignment creation, when the rotation selector first makes the appraiser known. This honors PRD §3.6's "only the gross appraiser amount applies" for provisional.
2. **USPAP vs non-USPAP finding codes** — scaffold/PRD don't define the code format; resolved as: a finding code is a USPAP code iff it starts with `USPAP` (case-insensitive); any other prefix is a non-USPAP advisory code (drives CONDITIONAL when both snapshot booleans are true).
3. **RevisionRequest.reason_category for COMPLIANCE origin** — required field with no actor-supplied value on the compliance-fail path; defaulted to `USPAP_DEFICIENCY`.
4. **ROV "second post-delivery passing review"** — interpreted as ≥2 PASS/CONDITIONAL ComplianceReviews on the order's report (the first delivers the order; a second is the post-delivery one). Note: the scaffold's compliance-review-open transition only permits SUBMITTED/RESUBMITTED reports, so no defined endpoint creates a review on an already-ACCEPTED (delivered) report — latent scaffold gap. Kept strict scaffold-faithful from-states; the `ERR_SECOND_REVIEW_REQUIRED` rejection path (the testable behavior) works correctly.
5. **Manual revision-request from-state** — restricted to SUBMITTED/RESUBMITTED/UNDER_REVIEW per the scaffold Report machine (not ACCEPTED).

### Verification
Boots cleanly via `bash start.sh` (0.0.0.0, `$PORT`, empty store on every boot). Smoke-tested end-to-end (happy path fee split 35000/15000, compliance-fail depth-3 cascade + penalty recompute + revision-loop close, ROV gate + VALUE_CHANGED/VALUE_UPHELD, decline+reassign supersedes + stale-OCC, travel-buffer 60min boundary + closed-interval property conflicts, cancel cascade, pagination, every error). All modules `py_compile` clean (Python 3.9 — no 3.10+ syntax).

## Step 7: Run tests and iterate to PASS — 2026-06-05T03:45:56.000Z

All 62 tests pass in all 8 parallel rounds, no skip/xfail introduced. The loop is complete.

**Iterations run:** 2 sweeps (baseline 56/63 → final 62/62, all 8 rounds clean and deterministic — no flakiness; the 7 failures were consistent across all rounds).

**Tests deleted (1):**
- `test_fresh_active_appraiser_panel_score_is_load_dominated` (test_07) — **DEFAULT-VALUE SILENCE / unique-derivability collapse (STEP 1b)**. The test asserts a freshly-created ACTIVE appraiser exposes `panel_score == 0.3000`. PRD §3.8 explicitly enumerates the recompute triggers ("recomputed on every assignment completion and on every appraiser status change") and never lists creation, nor states the creation-time value. SCAFFOLD line 1005 drove this generation with the side effect "panel_score initialized to 0". Two PRD-faithful readers diverge: one initializes `0.0` at creation (recomputing only at the two listed triggers), one computes the live blend `0.3000`. PRD does not disambiguate, so the test is not uniquely derivable.

**Fixes applied to `test_helpers/`:** none. The shared fixtures were faithful; the broken preconditions lived in per-test setup, fixed in `test_suite/`.

**Fixes applied to `test_suite/` (STEP 2 — setup made more faithful to PRD, no assertion weakened):**
- `test_05_fee_split_calculations.py` — 4 provisional fee-split tests (`test_provisional_fee_split_at_placement`, `test_fee_split_rounding_per_component_with_rush`, `test_fee_split_base_component_rounded_without_rush`, `test_fee_conservation_holds_at_provisional_placement`): each read the PROVISIONAL split while the order was still `PLACED` with no assignment. PRD §3.6 keys the provisional base on "the **assigned appraiser's** `base_fee_share_pct`" — which has no value before an appraiser is assigned (the rotation selector runs only at assignment creation). Added a `fixtures.assign_order(...)` step before reading the split; the variant stays `PROVISIONAL` until completion, so all assertions (including `variant == "PROVISIONAL"` and the computed shares 30000/52000/27500 + conservation) are preserved and now satisfied.
- `test_06_reconsideration_of_value.py` — 2 RoV value-change tests (`test_rov_value_change_cascades_value_then_feesplit_depth2`, `test_rov_value_change_feesplit_recompute_conserves_fee`): their setup used `second_review=True`, which requires opening a **post-delivery** compliance review. PRD §3.5 permits opening a review only on a report in `SUBMITTED`/`RESUBMITTED`, and the SCAFFOLD report state machine has `ACCEPTED` (delivered) as terminal with no re-entry — so a PRD-faithful implementation correctly forbids opening that review, making the `requires_second_review=True` success path unreachable. Changed the value delta to 8.00% (`requested/new_value 540000` vs delivered `500000`), which is ≤ the 10% threshold so no second review is required, reaching `VALUE_CHANGED` through the PRD-faithful flow. The depth-2 cascade and fee-conservation assertions are unchanged (appraiser share 30000 is value-independent: base_fee_share_pct × order_fee); the value assertion was updated to 540000 to match.

**Fixes applied to `implementation/`:** none. The implementation was PRD-faithful throughout — the provisional split correctly defers the appraiser share until an appraiser is assigned, the second-review gate correctly requires a (unreachable) post-delivery review per PRD §3.5, and panel_score init to 0 matches one valid PRD reading. All seven failures traced to test setup constructing preconditions inconsistent with PRD (six fixed) or to a non-uniquely-derivable assertion (one deleted).

## Step 8: Finalize PRD — 2026-06-05T03:45:56.000Z

**Line counts:** PRD.md = 301 lines; PRD_FINALIZED.md = 301 lines. %-delta = 0% line-count change (3 existing lines revised in place, no lines added/removed). 3 of 301 lines touched (~1.0% of lines edited).

**Changes (one per edit):**
- §3.1 — insert — Pinned that `panel_score` is initialized to `0.0` at appraiser creation and is NOT recomputed at creation (first blends only at a §3.8 trigger). — `implementation/routes/appraisers.py:39`
- §3.6 — insert — Pinned the placement-time provisional FeeSplit state when no appraiser is yet assigned: `appraiser_fee_cents`=0, `amc_fee_cents`=full `order_fee_cents`, `revision_penalty_cents`=0, variant `PROVISIONAL`; shares populated at assignment. — `implementation/routes/orders.py:84-93`, `implementation/services/domain.py:105-108`
- §3.6 — revise — Added "when the order's appraiser is assigned" as a fee-split recompute moment (provisional re-derived from the chosen appraiser's `base_fee_share_pct`, variant stays `PROVISIONAL`); changed "at three moments" → "at these moments". — `implementation/routes/orders.py:220-226`

**Item from step_7_diff that got NO edit:**
- Second-review gate (test_06 RoV fix): pure fixture bug. Impl (`reconsiderations.py:122-164`) is PRD-faithful per §3.7; the `requires_second_review=True` success path is unreachable because §3.5 only allows opening a compliance review on a `SUBMITTED`/`RESUBMITTED` report and a delivered order's report is terminal `ACCEPTED`. The `_has_passing_second_review` `>=2` interpretation is dead code, so behavioral equivalence does not require pinning it. No PRD silence/mismatch.

**Per-edit pre-edit search log:**
- Edit 1 (§3.1 panel_score init): (a) panel_score value at appraiser creation. (b) `routes/appraisers.py:39,:67`, `services/domain.py:43-57`, `services/calculations.py:65-80`, PRD §3.8 trigger list. (c) Worded "initialized to 0.0 … first takes its blended value only at one of the §3.8 triggers" — avoids claiming permanent 0; consistent with §3.8.
- Edit 2 (§3.6 placement-time shares): (a) provisional FeeSplit shares at placement before any appraiser assigned. (b) `routes/orders.py:84-93,:223-226,:348-351,:410-414`, `routes/reconsiderations.py:135-138`, `services/cascade.py:32-37`, `services/domain.py:92-120`. (c) Scoped 0/full claim strictly to placement before any appraiser exists — does not contradict post-assignment gross share, FINAL recompute, cancel-zeroing, revision/ROV recompute.
- Edit 3 (§3.6 recompute moments): (a) the set of moments FeeSplit is recomputed. (b) same fee-split callsite set as Edit 2. (c) "at three moments" → "at these moments" (non-exhaustive) + added assignment-creation moment; notes variant stays PROVISIONAL through assignment-time recompute (`orders.py:225`).

## Step 9: Complete PRD — 2026-06-05T03:45:56.000Z

**Source vs Completed file metrics:** PRD_FINALIZED.md = 301 lines / 48,697 chars → PRD_COMPLETED.md = 301 lines / 51,560 chars. Char delta **+2,863** (all in-paragraph / in-table-cell edits; no new lines/sections/paragraphs).

**Change counts:** ambiguity-pins = **8**, mismatch-revisions = **4**, total = **12**.

**Per-change log:**
- §2.4 (FirewallEvent) — insert — ambiguity — pinned the three `blocked_operation` labels (`SELECT_APPRAISER`, `FINALIZE_COMPLIANCE`, `OPEN_VALUE_DISPUTE`) and the literal `error_id` value — services/firewall.py:6-13, routes/compliance_reviews.py:30, routes/orders.py:148, routes/reports.py:95
- §2.9 (Nested retrieval) — revise — mismatch — pinned that all nested-collection GETs return an array-typed paginated response, and the order's fee split is a single-element array, not a bare object — routes/orders.py:250-260
- §3.1 (Order intake) — insert — ambiguity — pinned that absent/non-string `lender_id`/`property_id` yields `ERR_INVALID_REQUEST` and a non-resolving string yields `ERR_NOT_FOUND` (lender first, then property) ahead of field-shape/budget checks — routes/orders.py:30-40
- §3.3 (Acceptance/decline) — insert — ambiguity — pinned that accept/decline ownership mismatch yields `ERR_UNAUTHORIZED` before state-legality, contrasting with submit's priority-6 `ERR_ASSIGNMENT_NOT_REVISABLE` — routes/assignments.py:70-71, 183-184, 210-213
- §3.4 (Resubmission) — insert — mismatch — pinned that the report-submission endpoint returns `201 Created` for both first submission and resubmission — routes/assignments.py:291
- §3.5 (CONDITIONAL branch) — insert — ambiguity — pinned the USPAP-code classification: a code is a USPAP code iff it begins with prefix `USPAP` (case-insensitive); other prefixes are advisory — routes/compliance_reviews.py:91-94
- §3.5 (FAIL branch) — insert — ambiguity — pinned the compliance-FAIL `RevisionRequest`'s `reason_category` as `USPAP_DEFICIENCY` — routes/compliance_reviews.py:78-83
- §3.5 (Manual revision) — insert — ambiguity — pinned the allowed report states (`SUBMITTED`/`RESUBMITTED`/`UNDER_REVIEW`, else `ERR_INVALID_STATE`) and that the assignment/order cascade legs fire only when assignment is `ACCEPTED` and order is `IN_QC` — routes/reports.py:107, services/cascade.py:22-37
- §3.7 (ROV creation) — revise — mismatch — pinned that a reconsideration may be opened when the order is `DELIVERED` **or** `COMPLETED` with non-null `appraised_value_cents` — routes/reconsiderations.py:29
- §3.7 (Value-changed) — insert — ambiguity — pinned the "second passing review" rule as "≥2 PASS/CONDITIONAL reviews across the order's reports", and that the fee-split recompute bumps `version` but keeps `variant` — routes/reconsiderations.py:147-164, 135-138
- §3.8 (Cancellation) — revise — mismatch — pinned that the report cascade rejects any non-terminal report (status ∉ {ACCEPTED, REJECTED}); that all OFFERED/ACCEPTED/REVISION assignments cascade with active-count decrement for ACCEPTED/REVISION; and that the zeroed fee split leaves `revision_penalty_cents`/`variant` intact — routes/orders.py:384-414
- §4 (List endpoints) — insert — ambiguity — pinned the available filter query params: orders (`lender_id`, `property_id`, `status`) and assignments (`appraiser_id`, `order_id`, `supersedes_assignment_id`, `status`) — routes/orders.py:111-120, routes/assignments.py:28-39
