# Worklog — task_0551_paver_patio

Scenario: 551. Hardscape & Paver Patio / Outdoor Living (Belgard contractor style): design & 3D rendering, material selection (paver/retaining wall/fire pit/outdoor kitchen), site measure & sq-ft estimate, permit & HOA, material order & delivery, crew & phase scheduling, change order, deposit/progress draw & warranty

## Step 1: Create task directory — 2026-07-04T15:59:11.000Z

Used pre-assigned reserved directory `tasks/task_0551_paver_patio` (did NOT auto-scan ./tasks/). Ensured `tasks/task_0551_paver_patio/workspace/` exists. Design difficulty for scaffold generation: Expert.

## Step 2: Generate scaffold (Expert) — 2026-07-04T16:41:00.000Z

All three files are written, parse cleanly, and pass `scaffold_lint.py` (VERDICT: clean lint).

Scaffold: task_0551_paver_patio (Hardscape & Paver Patio / Outdoor Living, Expert)
Files written (all three, lint-clean): SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml.
Complexity profile: workflow_orchestration + ledger_reconciliation; flat topology; branching state machines; peer_roles; layers = dual-variant calc, cascading side effects, rate/threshold triggers, optimistic concurrency. 14 entities, 66 endpoints (broad because the scenario names 9 distinct sub-workflows).
Domain entities (14): Customer, Product (Belgard catalog), Crew, Project (posture + financial ledger), DesignRevision, SiteMeasurement, LineItem, Permit, HoaSubmission, ChangeOrder, MaterialOrder, WorkPhase, ProgressDraw, WarrantyClaim.
State machines (9): Project (DRAFT→QUOTED→PENDING_APPROVALS→CONTRACTED→IN_PRODUCTION→COMPLETED, +CANCELLED, with a CONTRACTED/IN_PRODUCTION→PENDING_APPROVALS revert triggered by a permit-raising change order); DesignRevision (cyclic revision loop IN_REVIEW→REVISION_REQUESTED→DRAFTING, revision_round++); HoaSubmission (fork to APPROVED/CONDITIONAL/REJECTED with CONDITIONAL→SUBMITTED re-entry); Permit (PREPARING→SUBMITTED→{APPROVED,DENIED}); ChangeOrder (PROPOSED→{APPROVED,REJECTED}); MaterialOrder (DRAFT→PLACED→DELIVERED,+CANCELLED); WorkPhase (PLANNED→SCHEDULED→IN_PROGRESS→COMPLETED,+BLOCKED,CANCELLED); ProgressDraw (PENDING→PAID→REFUNDED,+VOID); WarrantyClaim (FILED→{APPROVED,DENIED}). Two OCC concurrency rules on Project.version (change-order create, draw create).
Key calculations (literals pre-computed): project_valuation estimate(billable+waste, forward) vs as_built(installed, chronological) — 758565 vs 741453; labor_cost (flat tier + 1.15 complex-site multiplier); material_order_pallets (round-per-line-then-sum, pinned 3 vs wrong 2); prompt-pay discount evaluation order (total 4495763, discount 87600); change_order_price_delta recompute-vs-line-delta (142279 vs 160279); deposit_cap (min 10%/$1000); balance_due; permit_determination (wall_height ≥ 48).
Design-index counts: §1.8 = 19 difficulty instances across all 9 rules; §1.9 = 44 corner instances (31 real + 13 excluded_because stubs).
Notes: api_prefix empty by design (flat multi-collection domain). Added GET /products/{id}. scaffold_lint.py clean; no forbidden concurrency vocabulary.

## Step 3: Copy shared files — 2026-07-04T16:41:00.000Z

Copied ./INSTRUCTION.md → tasks/task_0551_paver_patio/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-07-04T16:48:00.000Z

Written: workspace/PRD.md (311 lines). Domain: Hardscape & paver-patio / outdoor-living contractor workflow (design → estimate → approvals → contract → material order → phased build → change orders → completion → warranty), flat-topology, 15-entity system with a financial ledger.
Section structure: §1 Introduction; §2 Global Specifications (2.1 Roles & auth — 4 roles + identity translation, Client is Customer-backed; 2.2 Response envelope; 2.3 Pagination; 2.4 Common attributes + Project.version counter; 2.5 11-rung validation precedence ladder; 2.6 Money/rounding; 2.7 OCC; 2.8 Cascading consistency; 2.9 Logical clock); §3 Business Logic (9 scattered subsections); §4 Endpoint Definitions (68 endpoints, 4-column table); §5 Error Code Catalogue (35 error IDs).
Hard Contracts: Contract 1 Field-Name Coverage 77/77 PASS; Contract 2 Rule Coverage PASS (11-rung ladder, both OCC rejections with expected_project_version/ERR_STALE_VERSION/412, all transitions/calcs/cascades, all 35 error IDs in narrative); Contract 3 §3 Path Purity PASS (402 backtick tokens, 0 paths/methods).
Confirmation: neither design YAML opened/grepped/referenced; no sibling task read. Inputs: SCAFFOLD.yaml + skill spec only.

## Step 5: Generate unit tests — 2026-07-04T17:05:00.000Z

Generated a complete PRD-first test suite: 65 tests across 7 files, every one carrying exactly one Design: tag (65 tests = 65 tags = 36 Difficulty + 29 Corner; all citations survive literal grep of PRD.md; no scaffold/table leakage; no skip/xfail markers).
Queue A (Difficulty): 18 of 19 instances translated, 2 tests each = 36 tests. 1 skipped.
Queue B (Corner): 29 of 31 non-stub instances translated, 1 test each = 29 tests. 2 skipped. (All 14 excluded_because: stub cross-refs checked, resolve to real difficulty instances; none emitted per spec.)
Skips (3 total), unique-derivability failures rooted in one systematic design-index defect:
 - Queue A priority_pair_validation_conflict/draw_state_beats_fiscal: asserts PROGRESS draw on DRAFT project → ERR_INVALID_STATE, but PRD states no state precondition on draw creation; on DRAFT (balance_due 0) fiscal check fires → ERR_DRAW_EXCEEDS_BALANCE (422), not 409.
 - Queue B validations/deposit_exceeds_cap_returns_error and validations/progress_draw_exceeds_balance_returns_error: trigger amounts derived from contract value 170279, but under PRD contract is 177279, so specified amounts are within limits → correct impl accepts (201).
Critical finding — design-index vs PRD labor-quantity conflict: design indices compute labor legs of project_valuation from MEASURED quantities, but PRD §3.3 steps 3–4 say "sum of billable quantities" (measured × (1+waste_factor)). Makes every labor-dependent exact monetary total in the indices PRD-inconsistent (simple 100-sqft: design 170279 vs PRD 177279; labor_tier 717609 vs PRD 742809). Scaffold's own formula comment (qty = measured*(1+waste)) agrees with PRD → indices' numbers are a computation bug, not intentional trap. Pallet counts (waste=0) and as-built 741453 unaffected, asserted exactly. Consequently asserted PRD-derivable RELATIONSHIPS instead of buggy exact values for affected Queue A calc instances (change_order_recompute → delta == new−old; dual_variant → as-built 741453 + divergence; final_phase retention → round_half_up(contract × 0.05); money_conservation → amount_paid == 15000 + balance formula; labor_tier/prompt_pay → permit-required / discount>0 / contract == estimated).
Deliberate fixture deviation: start_production_without_delivered_material isolated by adding a SCHEDULED phase (literal recipe left outcome ambiguous).
Files — test_helpers/: __init__, types, api_client, api_errors, assertions, factories, constants, test_users, fixtures. test_suite/: conftest, test_01_foundations, test_02_design_revisions, test_03_estimate_valuation, test_04_approvals, test_05_materials_and_scheduling, test_06_change_orders_and_cascades, test_07_draws_and_completion. All 17 files byte-compile; every fx.* fixture reference resolves.

## Step 6: Generate implementation — 2026-07-04T17:05:00.000Z

Complete Python + Flask REST API for Hardscape Outdoor Living. File layout (workspace/implementation/): start.sh (executable bash launcher), requirements.txt (Flask>=2.2,<4), store.py (14 dicts keyed by UUID + id/seq/logical-clock helpers), util.py (ApiError, response envelope, RBAC/auth, body validators, pagination, serialization, Decimal/ROUND_HALF_UP money helpers), calc.py (project_valuation estimate & as_built, material_order_pallets, deposit_cap), app.py (Flask entrypoint, ~65 routes, state machines, cascades, error handler).
Entrypoint: Flask; start.sh runs `exec python3 app.py` → app.run(host="0.0.0.0", port=int(PORT default 10000), threaded=True). start.sh reads $PORT, binds 0.0.0.0, foreground via exec, guards pip install behind `if ! import flask`.
Storage & IDs: purely in-memory module-level Store() dicts — no SQLite/disk/tmp. IDs bare UUIDs. Records carry id/created_at/updated_at/version(starts 1); list order via hidden monotonic _seq. Logical clock default 2026-05-01T00:00:00Z. No seeding — store empty on every boot; /projects returns total_count 0 fresh.
Self-verified end-to-end (90+ assertions): full lifecycle; pinned 11-step valuation (flat labor tiers, 1.15 complex-site uplift, 2% prompt-pay at ≥$20,000 boundary, permit fee); as-built vs estimate divergence; RECOMPUTE change-order delta with paver re-tiering (98625); depth-3 permit-revert cascade (project→PENDING_APPROVALS, +2 version bumps, phase BLOCKED, crew released, PREPARING permit); OCC ERR_STALE_VERSION; deposit cap, delivery-slot cap (2), crew closed-interval double-booking; HOA fork; cancel cascade; warranty window closure; validation precedence (422 before 404, auth before authz); fresh-boot isolation.
Note: impl valuation uses billable (waste-inflated) labor quantities per PRD §3.3 — consistent with the Step 5 finding that the design indices used measured quantities (buggy).

## Step 7: Test-and-fix loop — 2026-07-04T17:20:00.000Z

All 8 rounds pass 65/65. The loop is complete.

Iterations run: 2 (initial diagnostic sweep + verification sweep after fix).
Root cause: All 4 failures (identical across all 8 rounds of iteration 1) traced to one payload-shape bug in the test artifacts. The tests sent installed_quantities on POST /work-phases/{id}/complete as a LIST of {line_item_id, quantity} objects, but PRD §3.7 declares it verbatim as "the request carries an installed_quantities MAP from which each covered line's installed_quantity is recorded." The PRD-faithful implementation correctly required an object/map and returned ERR_INVALID_REQUEST — a test bug (STEP 2: fixture/test payload inconsistent with PRD's declared payload shape), not an implementation defect.
Tests deleted: None. Every failing test asserted PRD-verbatim, uniquely-derivable outcomes (project bubbles to COMPLETED, warranty stamps, retention = 5% of contract value, as-built total = 741453, estimate/as-built divergence); only the setup payload shape was wrong.
Fixes applied to test_helpers/:
 - test_helpers/fixtures.py — setup_dual_variant_completed: changed the complete_work_phase call's installed_quantities from a list of {line_item_id, quantity} objects to a map {line_item_id: quantity}, matching PRD §3.7's "map" wording (the impl reads installed[lid] → quantity).
Fixes applied to test_suite/:
 - test_suite/test_07_draws_and_completion.py — test_final_phase_completion_bubbles_project_to_completed and test_completion_creates_pending_retention_release_draw: same list→map conversion for installed_quantities (both occurrences).
Fixes applied to implementation/: None. The implementation was already PRD-faithful (calc.py as-built variant correctly uses installed_quantity with no waste and pinned_unit_price_cents, yielding the PRD-derivable 741453; complete-phase correctly enforced the map shape).
Final sweep: All 8 parallel rounds passed 65/65.

## Step 8: Finalize PRD — 2026-07-04T17:35:00.000Z

PRD.md vs PRD_FINALIZED.md: 311 vs 311 lines, 0% delta. Byte-identical (verified via diff). Edits made: ZERO. PRD_FINALIZED.md is a verbatim copy of PRD.md — a valid outcome here.
Why zero edits: the <step_7_diff> contains only fixture/test payload-shape corrections and explicitly reports zero implementation fixes. Every behavior those fixes touched is already uniquely determined by existing PRD prose, so none reveals a PRD silence or PRD/impl mismatch. Per HARD SCOPE, a pure fixture bug against an already-pinned sentence is not a PRD silence.
Confirmed each touched behavior against implementation/:
 1. installed_quantities map shape — PRD §3.7 (PRD.md:180) states verbatim "the request carries an installed_quantities map from which each covered line's installed_quantity is recorded"; impl app.py:866-881 requires a dict (else ERR_INVALID_REQUEST) and reads installed[lid]. Already pinned.
 2. Project bubbles to COMPLETED — PRD §3.7 + §3.9; impl app.py:885-886,906. Already pinned.
 3. Warranty stamps — PRD §3.9: start = current logical-clock instant, end = 365 days after; impl app.py:901-904. Already pinned.
 4. Retention = 5% of contract value, PENDING — PRD §3.9 "five percent of contract_value_cents, rounded half up to whole cents"; impl app.py:894-900. Already pinned.
 5. As-built total (741453) / estimate-vs-as-built divergence — PRD §3.9 (actual installed_quantity, no waste, locked pinned_unit_price_cents); impl calc.py:31-35. Already pinned.
Pre-edit subject-enumeration (no edits committed): installed_quantities shape (writer app.py:862-888, as-built reader calc.py:31-35, null-writers app.py:461/643); retention-release draw (_complete_project app.py:891-907, draw creation excludes RETENTION_RELEASE from client-postable types app.py:936-943, enum guard app.py:918); as-built valuation (sole caller app.py:892, shared calc.py:9-82). All consistent — no wording change needed.

## Step 9: Complete PRD — 2026-07-05T10:33:00.000Z

PRD_FINALIZED.md vs PRD_COMPLETED.md: 311 vs 311 lines; 42715 vs 43174 chars (char-delta +459). Started by `cp PRD_FINALIZED.md PRD_COMPLETED.md` (byte-identical baseline), then ran a full PRD-vs-`implementation/` scan (app.py, calc.py, util.py, store.py) and edited only PRD_COMPLETED.md. Did NOT read SCAFFOLD*.yaml or worklog.md while producing PRD_COMPLETED.md.
Counts: 5 changes total — 4 ambiguity-pins, 1 mismatch-revision. All changes are in-paragraph inserts/revisions; no new paragraphs, no new sections, no invented behavior; line count unchanged (311).
Scan verdict: implementation is faithful to the PRD everywhere; the residual gaps were PRD silences the impl resolved at generation time (never surfaced as Step 7 failures because no test both exercised them and over-asserted) plus one plural-wording mismatch on the generate-estimate version bump. The 11-step valuation, pallet aggregation rounding order, deposit cap, OCC/version model, cascade mechanics, permit/HOA gates, precedence ladder, and every not-found/state error already trace uniquely to PRD prose and needed no change.
Changes (`{section} — {insert|revise} — {ambiguity|mismatch} — {what} — {impl}`):
 1. §3.1 (Catalog) — insert — ambiguity — the PRD pins duplicate-email → validation-time uniqueness failure but leaves duplicate-`sku` unstated; pinned "a duplicate `sku` is a uniqueness failure rejected at request-validation time with `ERR_INVALID_REQUEST`" — app.py:98-100.
 2. §3.3 (Estimate) — revise — mismatch — "Each of these mutations increments the project version." reads as one bump per field-update, but generate-estimate does a single `touch`; revised to "these field updates are a single version-bumping operation that increments the project `version` exactly once." — app.py:216-224 (single touch at 224).
 3. §3.6 (start-production) — insert — ambiguity — the sibling material precondition names `ERR_MATERIAL_NOT_DELIVERED` but the "at least one work phase is already `SCHEDULED`" precondition named no code; pinned the generic "(else the generic `ERR_INVALID_STATE`, 409)" — app.py:286-288.
 4. §3.6 (pallet aggregation) — insert — ambiguity — PRD divides billable qty by `coverage_per_pallet_sqft` for SQFT/FACE_SQFT lines but is silent when coverage is 0 (the default, undefined division); pinned "a square-foot line whose `coverage_per_pallet_sqft` is zero likewise contributes no pallets and no ordered square footage" — calc.py:95-99 (`if coverage <= 0: continue`).
 5. §3.7 (draw create) — insert — ambiguity — §2.5's tier-7 error enumeration omits `ERR_WORK_PHASE_NOT_FOUND` for the body `work_phase_id`, and §3.7 did not state its resolution; pinned "(which, when supplied, must reference a work phase on the same project, else `ERR_WORK_PHASE_NOT_FOUND`, 404)" — app.py:923-926.
Considered-but-not-changed (already uniquely PRD-pinned or PRD-consistent): pagination clamp-to-bounds (§2.3 min/max); `_seq` creation-order sort ≡ created_at asc (§2.3); generic-state-violation → `ERR_INVALID_STATE` for material-order-place / work-phase-schedule / change-order-approve project-status gates (§2.5 tier-6 generic rule already pins these); paver-labor tier boundaries (≤200 / ≤500 / >500) and complex-site 1.15 uplift rounding-only-in-branch (§3.3); as-built variant null installed_quantity→0 (§3.9 "same eleven-step valuation"); clock echoes raw `to_iso8601` string as `current_utc` (§2.9); warranty window `>` strict (§3.9 "not passed"); decide resolution_notes accepted-not-persisted (claim has no such field). None of these admit a divergent faithful-reader implementation, so no wording added.
