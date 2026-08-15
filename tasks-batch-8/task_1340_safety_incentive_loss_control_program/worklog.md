# Worklog — task_1340_safety_incentive_loss_control_program

## Step 1: Create Task Directory — 2026-08-12T22:38:00.000Z

Pre-assigned directory `tasks/task_1340_safety_incentive_loss_control_program/` with `workspace/` already exists (verified). Step 1 treated as DONE per pipeline instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-12T23:32:00.000Z

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1340_safety_incentive_loss_control_program/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys), 96.5 KB
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:`, 84.7 KB
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:`, 109.3 KB

**SCAFFOLD.yaml contents:**
- **Entities: 16** — SafetyProgram, JobRole, TrainingCourse, Employee, TrainingAssignment, Hazard, ControlItem, Observation, CommitteeMeeting, ActionItem, ContractorOrg, ClaimRecord, LossControlRecommendation, IncentiveAward, IncentiveEvent (append-only), EMRForecast (append-only snapshot)
- **State machines: 12** — with cycles on Hazard (verify-fail revision loop + CLOSED→OPEN reopen), ContractorOrg (CONDITIONAL/SUSPENDED→UNDER_REVIEW), ActionItem (verify-fail loop), LossControlRecommendation (carrier-rejection loop), TrainingAssignment (EXPIRED→ASSIGNED)
- **Concurrency rules: 2** — OCC on SafetyProgram.version for config patch and EMR forecast creation (ERR_STALE_VERSION, 412)
- **Calculations: 10** — incl. dual-variant EMR forecast (provisional incl. REPORTED claims + annualized payroll vs final; verified literals 2.97 vs 1.80), dual-variant incentive scoring (LEADING_ONLY vs BALANCED claims-free bonus; 5100c vs 16800c payouts on identical activity), per-employee-before-sum rounding payout, banded contractor prequal score, posture thresholds, renewal-window suppression, half-open meeting overlap
- **Validations: 24** (priority-ordered, auth → fiscal; segregation-of-duties as business_safety)
- **Endpoints: 80** (flat topology under `/safety`, plus `POST /_clock/set_current_utc` with the mandated 2026-08-01T00:00:00Z default)
- **Errors: 29** (all referenced by validations/transitions)
- **Roles: 7** — EHSAdmin/CarrierConsultant opaque; SafetyManager/Supervisor/Employee/CommitteeChair entity_backed:Employee; ContractorRep entity_backed:ContractorOrg; SoD checks on verify/triage

**§1.8 (depth): 21 instances** across all 9 rules (2 each for dual_variant, combinatorial, non-linear machines, cascades, overlaps, invariants; 3 each for priority conflicts, boundary precision, cross-entity gates). All formula-derived asserts were executed in Python and pinned as literals (e.g., EMR 1.80/2.97, prequal 80.00/79.99/66.90, payouts 800/2900/4400/5100/6000/10000/16800).

**§1.9 (breadth): 51 instances** — 48 active + 3 `excluded_because:` stubs — spanning all 9 claim-extraction sections: entities (8), state_machines (8), calculations (6), validations (11), endpoints (3), errors (1), rbac (5), cross-cutting layers (5), consistency (1).

**Verification:** `scaffold_lint.py` — `VERDICT: clean lint` on the final run (one early FK-reverse-reachability finding on `JobRole.required_course_ids` was fixed by aligning the list filter name; two arithmetic fixture bugs in the budget-invariant recipe were caught by replay and corrected so the control verifies late, matching the pinned 40-point/6000c award).

## Step 3: Copy Shared Files — 2026-08-12T23:33:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1340_safety_incentive_loss_control_program/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-12T23:50:00.000Z

All contracts verified. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1340_safety_incentive_loss_control_program/workspace/PRD.md` (ends at §5 with no audit footer, per spec).

## What was generated

A prose PRD for the Safety Incentive & Loss Control API with a domain-derived skeleton: 11 subsections in §2 (RBAC with per-role identity semantics, verbatim §2.2 envelope, pagination, common resource properties, the logical clock starting at `2026-08-01T00:00:00Z`, validation cascade with explicit priority ordering, monetary/rounding precision, OCC, segregation of duties, nested-resource resolution, derived-counter consistency) and 9 subsections in §3 organized by business process (program setup → workforce/training → hazards/controls → leading indicators → committee/action items → external parties [contractors, claims, carrier recommendations] → sweep/posture → incentive scoring/close-out → EMR forecasting). §4 holds the 80-endpoint 4-column table; §5 holds the 29-error 2-column catalogue. The withheld difficulty/corner design files were never opened.

Notable fidelity decisions: rounding bases stated per rule (unrounded ratio for the integrity flag vs. rounded 2dp score for contractor banding, per-employee whole-dollar rounding before aggregation); all 55 state transitions expressed with state-pair framing (`ASSESSED → CONTROLS_PLANNED`, etc.); constants embedded with unit conversions (200,000-hour normalization, $15,000 split point, $20,000/$180,000 weighting window); no pseudocode operators or fuzzy quantifiers anywhere in prose.

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 105 required, 105 present, 0 missing
- endpoints[].request_body (input): 74 required, 74 present, 0 missing
- endpoints[].query_params: 51 required, 51 present, 0 missing
- endpoints[].path_params: 1 required, 1 present, 0 missing
(two passes run, both clean)
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 24 checked, 24 expressed in prose (global cascade in §2.6 + endpoint-specific orderings: contractor decide posture-before-score, training create duplicate→cert-window→employee-active, program close hazards→recommendations→meetings), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (config patch + EMR forecast; `expected_program_version`, mismatch → `ERR_STALE_VERSION` 412, forecast success increments program version), 0 missing
- state_machines[].transitions: 55 checked, 55 fully expressed (from/to, preconditions with error ids, side effects), 0 missing
- calculations[]: 10 checked, 10 fully expressed in precise prose (hazard risk bands + SLA days, leading-indicator rates, incentive points with both scoring variants, award payout with pinned rounding order, dual-basis EMR, prequal weighted score, posture thresholds, certification window, quorum, meeting overlap), 0 missing
- validations[] conditions: 24 checked, 24 matchable to error_id in §2/§3 narrative, 0 missing
- endpoints[].side_effects / applies_to: 80 endpoints' side effects and all 24 applies_to scopes expressed (incl. all four ERR_PROGRAM_NOT_ACTIVE phase gates and all four ERR_FUTURE_DATE_NOT_ALLOWED endpoints), 0 missing
- entities[].fields[] structured content: 105 checked, 105 reconstructible (defaults 0.20 / 5 / 30 days / false / empty list / sweep_index from zero; null-until-completed cert_valid_until; common_fields=false pair carries only id + created_at), 0 missing
- sibling-branch symmetry: 10 groups checked (verify PASS/FAIL ×2, triage ×3, contractor submit ×4, decide ×3, LCR respond ×3 / review ×2, claim disposition ×3, implement ×2, complete ×2, void ×2), all with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 655
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional spot checks: §2.2 byte-identical to `section-2.2-response-structure.md`; all 40 state values and all enum literals (`LEADING_ONLY`/`BALANCED`, `LOW`/`MODERATE`/`HIGH`, `BRONZE`/`SILVER`/`GOLD`/`PLATINUM`, six `source_type` values, etc.) present as exact strings; all 7 role names exact; all 29 error IDs present; all 80 endpoint paths present in §4's 4-column table.

## Resume Assessment — 2026-08-13T00:35:00.000Z

Prior run was killed mid-flight after Step 4 entry. State on disk at resume:

- **Step 1-4: COMPLETE.** SCAFFOLD.yaml / SCAFFOLD_DIFFICULTY_DESIGN.yaml / SCAFFOLD_CORNER_DESIGN.yaml all present and lint-clean per prior entries; INSTRUCTION.md copied; PRD.md complete (62,986 bytes, §5-terminated, all hard-contract reports PASS per Step 4 entry). Kept as-is; not regenerated.
- **Step 5 (tests): INCOMPLETE — resuming in continuation mode.** `test_helpers/` is complete (all 9 spec files, clean file tails, no truncation). `test_suite/` has conftest.py + 5 test files = 46 tests / 46 Design tag-lines, but only 37 unique design instances covered: 9 instances are double-tested (two test functions sharing one Design tag: near_miss_ratio_exactly_floor, control_verify_gated_by_hazard_state, observation_create_gated_by_program_active, training_assignment_gated_by_employee_active, hazard_verification_revision_loop, training_create_constraint_beats_referential, triage_safety_beats_referential, certification_renewal_window_suppression, control_verify_close_cascade), and 32 of 69 active instances (21 difficulty + 48 corner) have no test at all — the entire committee-meeting/action-item, contractor-prequalification, claims, loss-control-recommendation, incentive-award, sweep/posture, and EMR-forecast areas are untested. No Step 5 worklog entry exists. Decision: keep test_helpers/ and the existing 5 test files; spawn a continuation subagent to adjudicate the 9 duplicates and generate the 32 missing tests.
- **Step 6 (implementation): COMPLETE — verified at resume.** workspace/implementation/ has all 15 route blueprints registered in routes/__init__.py, exactly 80 route decorators (matches scaffold's 80 endpoints), services/calc|core|ops present, `python3 -m py_compile` clean on all modules, start.sh present and minimal-install aware, and a live boot smoke test passed (server bound $PORT, envelope-correct 401 ERR_UNAUTHENTICATED on unauthenticated requests, logical clock defaulting to 2026-08-01T00:00:00Z). Kept as-is; not regenerated. No Step 6 worklog entry exists (run killed before it was written).
- **Steps 7-9: NOT STARTED.** No results.*.json, no PRD_FINALIZED.md, no PRD_COMPLETED.md.

## Step 5 (continuation): Complete Test Suite — 2026-08-13T00:58:00.000Z

**Step 5 continuation (test-suite completion for task_1340) — DONE**

**Part A — Coverage audit.** 46 pre-existing tests carried 37 unique Design tags (9 difficulty, 28 corner) with 9 tags duplicated ×2. Walking both indices (21 difficulty + 48 corner active + 3 corner stubs = 72 instances): 32 non-stub instances had no test — 12 difficulty (`emr_provisional_vs_final_divergence`, `incentive_leading_only_vs_balanced_payout`, `prequal_score_weighted_band_selection`, `award_payout_rounding_order`, `contractor_prequal_cycles`, `sweep_posture_cascade`, `award_approve_state_beats_fiscal`, `prequal_band_exactly_80_approves`, `quorum_exactly_min_holds`, `meeting_half_open_overlap`, `incentive_budget_approve_void_conservation`, `action_item_carryover_count_conservation`) and 20 corner (entities 2, state_machines 3, calculations 4, validations 5, rbac 4, cross-cutting 1, consistency 1).

**Part B — Duplicate adjudication.** For all 9 duplicated tags, the second test asserted a rule with no matching uncovered instance in either index, so each pair resolved to keep-stronger / delete-redundant (9 deletions, 0 re-tags):
- `near_miss_ratio_exactly_floor` — kept `test_near_miss_ratio_at_exactly_floor_does_not_flag` (the namesake strict-< boundary); deleted `test_near_miss_ratio_below_floor_raises_integrity_flag`.
- `control_verify_gated_by_hazard_state` — kept `test_control_verify_rejected_while_hazard_in_progress` (the instance's exact ERR_INVALID_STATE assert); deleted the success-path test.
- `observation_create_gated_by_program_active` — kept the DRAFT-rejection test; deleted the ACTIVE-success test.
- `training_assignment_gated_by_employee_active` — kept the INACTIVE-rejection test; deleted the active-success test.
- `hazard_verification_revision_loop` — kept `test_hazard_closes_after_revision_and_can_reopen` (covers instance assert lines 3–5: revision loop completion + CLOSED→OPEN recurrence); deleted `test_verify_fail_loops_hazard_back_to_in_progress` (FAIL-field half).
- `training_create_constraint_beats_referential` — kept `test_certification_window_conflict_creates_no_assignment` (asserts both the error AND the no-new-row side effect, a superset); deleted `test_certification_window_shadows_employee_inactive`.
- `triage_safety_beats_referential` — kept the SoD-shadows test (the instance's exact recipe); deleted the isolated ERR_HAZARD_NOT_OPEN test.
- `certification_renewal_window_suppression` — kept the 31-days-blocked test (carries ERR_CERTIFICATION_ACTIVE); deleted the 30-days-allowed test.
- `control_verify_close_cascade` — kept `test_control_verify_close_cascade_pays_validated_events` (deepest cascade link + exact point math, 49 total); deleted the status-cascade-only test.

**Part C — Generated 32 tests in 5 new files** (all reuse existing test_helpers; no helper changes needed; every instance passed the PRD-first two-condition filter, no skips):
- `test_06_committee_action_items.py` (5): quorum_exactly_min_holds, meeting_half_open_overlap, cancelled_meeting_cannot_be_held, non_assignee_cannot_complete_action_item_returns_unauthorized, action_item_carryover_count_conservation.
- `test_07_contractor_prequalification.py` (8): contractor_create_retrieval_roundtrip, prequal_score_weighted_band_selection, prequal_conditional_band_upper_edge_79_99, prequal_band_exactly_80_approves, contractor_prequal_cycles, contractor_submit_expired_cert_rejected, carrier_consultant_cannot_decide_contractor_returns_unauthorized, contractor_rep_cannot_submit_other_org_returns_unauthorized.
- `test_08_claims_and_recommendations.py` (6): emr_medical_only_era_factor, deny_claim_then_accept_returns_invalid_state, lcr_carrier_rejection_loop, lcr_evidence_control_must_be_verified, close_blocked_by_open_hazard, close_blocked_by_open_recommendation.
- `test_09_incentive_scoring_awards.py` (9): incentive_leading_only_vs_balanced_payout, award_payout_rounding_order, award_tier_boundary_exactly_50_silver, claims_free_bonus_withheld_when_claim_exists, award_approve_state_beats_fiscal, incentive_budget_approve_void_conservation, reconcile_blocked_by_unpaid_awards, supervisor_cannot_approve_award_returns_unauthorized, close_immediately_reflects_awards.
- `test_10_sweep_posture_and_emr_forecasting.py` (4): sweep_posture_cascade, emr_provisional_vs_final_divergence, emr_forecast_snapshot_immutability, occ_stale_emr_forecast_returns_412.

**Final verification:** py_compile OK on all suite+helper files; 69 tests total, 69 unique Design tags, 69/69 non-stub instances covered (missing-after = 0, no skips), no duplicated/dangling/stub-pointing tags, all 3 stub cross-references resolve; all new imports resolve against test_helpers and all 5 new modules import cleanly; 52/52 PRD citations in new files survive whitespace-normalized verbatim grep of PRD.md.

Note for Step 7: the difficulty queue's "≥2 tests per instance" skill target is intentionally superseded here by the task's one-test-per-tag adjudication rule (9 duplicate pairs collapsed to one keeper each).

## Step 7: Run Tests and Iterate — 2026-08-13T01:05:00.000Z

All 8 rounds pass 69/69. The sweep is clean.

**Iterations run:** 2 (sweep 1 surfaced 3 deterministic failures, identical across all 8 rounds; sweep 2 after fixes passed 8/8 × 69/69).

**Tests deleted:** none — every failing test traced to a verbatim PRD rule (PRD §3.4 reporter filter, PRD §2.1/§3.4 triage RBAC, PRD §3.8 LEADING_ONLY vs BALANCED payout divergence). The failures were mechanical test-artifact bugs, not PRD-coverage or unique-derivability problems.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `setup_dual_variant_scenario`: unpacked `hazard, controls = setup_hazard_with_controls(...)` (the helper returns a *list* of controls) and changed `implement_control(control["id"], …)` / `verify_control(control["id"], …)` to `controls[0]["id"]`. Previously indexing a list with `["id"]` raised `TypeError: list indices must be integers or slices, not str`, killing `test_incentive_leading_only_vs_balanced_payout` in setup before any assertion ran.

**Fixes applied to `test_suite/`:**
- `test_suite/test_05_observations_leading_indicators.py` — added the missing `create_employee_record` name to the explicit `from test_helpers import (...)` list. It is used at lines 119 (`TestReporterFilter`) and 276 (`TestTriageAuthorization`); the barrel export in `test_helpers/__init__.py` already exposed it, so this was purely a missing import in the test file (`NameError: name 'create_employee_record' is not defined`).

**Fixes applied to `implementation/`:** none — the reference implementation was correct on all three PRD rules; no code changes were needed.

## Step 8: Finalize PRD — 2026-08-13T01:09:00.000Z

**Output:** `workspace/PRD_FINALIZED.md` — byte-identical copy of `PRD.md` (the `cp` with zero edits).

**Line counts / %-delta:** PRD.md = 350 lines; PRD_FINALIZED.md = 350 lines; delta = 0 lines, 0.0%. `diff -q` confirms identical.

**Changes made:** none. No edits were warranted — both Step 7 fixes are mechanical test-artifact bugs that reveal neither PRD silence nor PRD/impl mismatch, and Step 7 made zero implementation changes and zero test deletions.

### Per-item investigation (in lieu of pre-edit search logs, since no edits were committed)

**Item 1 — `test_helpers/fixtures.py::setup_dual_variant_scenario` unpacking fix**
- (a) Subject: the internal Python return shape of the test helper `setup_hazard_with_controls` — it returns `(hazard, controls)` where `controls` is a *list*; the fixture previously indexed the list with `["id"]` (TypeError).
- (b) Paths enumerated and read: `test_helpers/fixtures.py:191-209` (helper; docstring states "Returns (hazard, controls)", controls built by list comprehension), `test_helpers/fixtures.py:212-227` (sibling caller `close_hazard_via_single_control`, which already unpacked and indexed `controls[0]` correctly), `test_helpers/fixtures.py:538-577` (the fixed fixture), `test_suite/test_09_incentive_scoring_awards.py:37-77` (the killed test), and the implementation site the test actually exercises — `implementation/services/ops.py:222-266` (`close_program`: bonus pass gated on `scoring_variant == "BALANCED"`, claims-present check over `ACCEPTED`/`CLOSED`, integrity-flag check, one `CLAIMS_FREE_BONUS` per employee with an existing event) plus `implementation/services/calc.py:26` (base 50).
- (c) Conclusion: the bug is a Python TypeError wholly inside test-fixture code — no endpoint, request, response, or domain rule is involved. The behavior the test asserts (PRD §3.8 LEADING_ONLY vs BALANCED divergence) is pinned verbatim at PRD.md line 209 and implemented exactly at `ops.py:229-243`. No PRD silence, no mismatch → no edit.

**Item 2 — `test_suite/test_05_observations_leading_indicators.py` missing `create_employee_record` import**
- (a) Subject: the test file's explicit import list omitted a name that the `test_helpers` barrel already exported.
- (b) Paths enumerated and read: `test_suite/test_05_observations_leading_indicators.py:6-32` (import list), lines 106-133 (`TestReporterFilter`) and 264-285 (`TestTriageAuthorization`), `test_helpers/__init__.py:39` (`from .fixtures import *` barrel), `test_helpers/fixtures.py:102` (`create_employee_record` definition), and the implementation sites for both affected behaviors — `implementation/routes/observations.py:46-67` (list endpoint filtering by `reporter_id` at lines 52, 61-62) and `implementation/routes/observations.py:77-79` (`auth(["SafetyManager"])` on triage) with `implementation/middleware.py:17-32` (role-not-permitted → `ERR_UNAUTHORIZED` 403).
- (c) Conclusion: a pure NameError in test code. Both behaviors asserted are pinned verbatim in the PRD — reporter filter at PRD.md line 163 and triage RBAC at lines 165 and 15 (§2.1 `ERR_UNAUTHORIZED` 403) — and the implementation matches each. No PRD silence, no mismatch → no edit.

**Per instructions:** where the investigation confirms neither fix reveals a PRD silence or PRD/impl mismatch, the correct output is the byte-identical copy. No edits were manufactured.

## Step 9: PRD Completeness Scan — 2026-08-13T01:28:00.000Z

Confirmed: scalar bounds (negative `incurred_cents`) fire at gathering before FK resolution; the interval rule fires after program resolution — exactly as the §2.6 revision states. All 16 edits verified against impl.

**Summary**

- Source: `workspace/PRD_FINALIZED.md` (350 lines, 62,986 chars) → `workspace/PRD_COMPLETED.md` (350 lines, 66,472 chars; **+3,486 chars**, all inline edits, no new sections).
- Counts: **ambiguity-pins: 13, mismatch-revisions: 3** (the §2.6 cascade revision, the `scoring_variant`-writability revision, and the `suspension_claim_id` error-tier correction — the latter two folded into the §2.6/§3.1 rewrites).

Changes (section — insert|revise — ambiguity|mismatch — what changed — impl ref):

- §2.3 — insert — ambiguity — ties in creation-timestamp ordering are broken by server insertion sequence — services/core.py:46-47, db.py:27-32.
- §2.4 — insert — ambiguity — `version` starts at 1 at creation — services/core.py:27.
- §2.5 — insert — ambiguity — all server timestamps (envelope meta, created_at/updated_at, business stamps) come from the logical clock — response.py:16, services/core.py:24-26, clock.py.
- §2.6 — revise — mismatch — re-tiered existence vs well-formedness to impl's actual grouping: path 404s → body gathering 400s (presence/type/enum/scalar bounds) → body-FK 404s → cross-field 400s (`scheduled_end`>`scheduled_start`) → state gates; FAIL-note/deny/void reason checks fire pre-state, contractor no-change check post-state — routes/claims.py:18-31, routes/meetings.py:17-25, routes/controls.py:76-91, routes/contractors.py:83-109.
- §2.6 — revise — mismatch — dropped `suspension_claim_id` from the 404 body-reference list; it yields `ERR_INVALID_REQUEST` (as §3.6 already pinned) — routes/contractors.py:168-175.
- §3.1 — revise — mismatch — `scoring_variant` is never writable via incentive-config (a body member is ignored), not merely "immutable once the program leaves DRAFT" — routes/programs.py:103-139.
- §3.1 — insert — ambiguity — config write evaluates the DRAFT gate before the version comparison; field values validated as applied after both gates — routes/programs.py:110-136.
- §3.1 — insert — ambiguity — activation names `ERR_PROGRAM_NOT_DRAFT` for a non-DRAFT program and pins gate order: positivity 400 → DRAFT 409 → ALREADY_ACTIVE 409 → PAYROLL_INCOMPLETE 422 — routes/programs.py:148-166.
- §3.2 — insert — ambiguity — `required_course_ids` list filter matches roles whose list contains the given course id — routes/catalog.py:42-47.
- §3.2 — insert — ambiguity — `cert_valid_until` month addition clamps the day to the target month's last day — util.py:35-41, routes/training.py:119.
- §3.3 — insert — ambiguity — control creation permitted only while hazard is `ASSESSED`/`CONTROLS_PLANNED`/`IN_PROGRESS`/`PENDING_VERIFICATION`, else `ERR_INVALID_STATE` — routes/hazards.py:146-149.
- §3.3 — insert — ambiguity — chained automatic hazard transitions in one request are a single mutation (one version bump) — services/ops.py:84-116.
- §3.3 — insert — ambiguity — an `outcome_note` supplied on a PASS verification is recorded — routes/controls.py:101-102.
- §3.4 — insert — ambiguity — triage `CREATE_HAZARD`: new hazard's `identified_by` is the observation's `reporter_id`; `description` defaults to the observation's own — routes/observations.py:125-130.
- §3.4 — insert — ambiguity — `observation_rate` reported as 0 when `exposure_hours` is zero; program and leading-indicator reads recompute `integrity_flag` live at response time while posture consumes the sweep-refreshed stored value — services/calc.py:99-102, services/core.py:236, routes/programs.py:231-235.
- §3.7 — insert — ambiguity — sweep scoping pinned: control/action-item/recommendation flips and SLA pass are scoped to the swept program; training-assignment expiry and contractor expiry are global; sweep runnable against a program in any status — services/ops.py:127-196, routes/programs.py:217-224.
- §3.8 — insert — ambiguity — closing a non-`ACTIVE` program yields `ERR_INVALID_STATE` — routes/programs.py:178-180.
- §3.8 — insert — ambiguity — `CLAIMS_FREE_BONUS` event's `reference_id` names the program itself — services/ops.py:243.
- §3.8 — insert — ambiguity — reconciling a non-`CLOSED` program yields `ERR_PROGRAM_NOT_CLOSED` — routes/programs.py:205-207.
- §3.9 — insert — ambiguity — an EMR forecast may be created against a program in any status (no phase gate) — routes/forecasts.py:16-38.

All other implementation behaviors traced (endpoints, state machines, formulas, error codes, response shapes, role lists, filters, rounding rules, OCC semantics) were already uniquely pinned by PRD_FINALIZED.md and required no change.
