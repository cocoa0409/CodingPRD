# Worklog — task_0834_fire_marshal_inspection

## Step 1: Create task directory — 2026-07-11T17:14:51.000Z

Created `tasks/task_0834_fire_marshal_inspection/` and `tasks/task_0834_fire_marshal_inspection/workspace/`. Pre-assigned folder (no index scan performed).

## Step 2: Generate scaffold — 2026-07-11T17:41:00.000Z

All checks pass. The scaffold is complete and self-consistent. Generated three artifacts, designed at **Expert** difficulty for the Fire Marshal Plan Review & Inspection domain. Built purely from the scenario + skill spec (no sibling tasks consulted). `scaffold_lint.py` reports **VERDICT: clean lint**.

**Complexity profile**: primary archetype `compliance_audit` + secondary `workflow_orchestration`; layers dual-variant calc, cascading side-effects, rate/threshold triggers, optimistic concurrency; `flat` topology; `parallel` state-machine shape; `peer_roles`.

**SCAFFOLD.yaml**
- **10 entities**: Property, PermitApplication, PlanReview, Permit, Inspection, Violation, AbatementOrder, Certificate, Hydrant, FlowTest (14 FKs, all reverse-reachable via filtered lists).
- **38 endpoints** (incl. `/_clock/set_current_utc` default `2026-03-01T00:00:00Z` and `/_ops/process-overdue-orders` sweep). Slightly above the 20–32 band — the regulatory surface genuinely needs the breadth; entity coupling carries the difficulty.
- **7 state machines**: PermitApplication (cyclic corrections loop), PlanReview (3 parallel discipline axes + compound bubble-up), Inspection, Violation (cyclic OPEN↔ABATED), AbatementOrder, Permit, Certificate (parallel occupancy × placard axes).
- **6 calculations** (permit_fee estimated/final, occupant_load net/gross, required_exits, required_fire_flow_gpm, flow_available_at_20psi, abatement_deadline); **26 errors**; 4 roles (all opaque).
- **1 concurrency rule**: OCC create-with-supersede for re-issued abatement orders on `Violation.version` (412).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 18 instances — exactly 2 per each of the 9 §0.5 rules.

**SCAFFOLD_CORNER_DESIGN.yaml**: 21 instances across all §1.9 sections, plus 4 `excluded_because:` stubs. All 43 instance names unique across both design files.

safe_load verification: all three files parse cleanly.

## Step 3: Copy INSTRUCTION.md — 2026-07-11T17:41:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-11T17:46:00.000Z

Generated `workspace/PRD.md` — 274 lines, ~5,100 words. Sections: §1 Introduction, §2 Global Specs (RBAC, envelope, pagination, logical clock default `2026-03-01T00:00:00Z`, rounding, cascade principle, referential resolution order, OCC on abatement issuance, validation-precedence), §3 Business Logic (8 lifecycle subsections; all six calculations translated to prose), §4 (39-endpoint table), §5 (26-error table). All three doc-generator hard contracts PASS (field coverage, rule coverage, §3 path purity). No blocking scaffold ambiguities. Did not open either withheld design file.

## Step 5: Generate unit tests — 2026-07-11T18:02:00.000Z

**Stage 1 — `test_helpers/`** (9 files): types.py (10 entity TypedDicts + 15 enums), api_client.py (one method per endpoint, `/api`-prefixed), api_errors.py (26 error IDs + HTTP status map), assertions.py, factories.py, constants.py, test_users.py (4 opaque roles + `make_applicant_headers`), fixtures.py, `__init__.py` barrel.

**Stage 2 — `test_suite/`**: conftest.py + 7 domain test files, **55 test functions**.

**Coverage:** Queue A (Difficulty): 17 of 18 instances translated, 2 tests each (34 tests), 1 skipped. Queue B (Corner): all 21 non-stub instances translated, 1 test each (21 tests). Every test docstring carries a verbatim PRD citation + exactly one `Design:` tag.

**PRD-coverage gap (1 skipped):** `Difficulty/priority_pair_validation_conflict/flow_test_temporal_beats_constraint` — asserts window-overlap beats invalid-readings, but PRD §3.2 orders readings first → contradicts unique-derivability → skipped (sibling `issue_permit_state_beats_fiscal` kept, matches PRD §3.5). Minor sub-assert dropped: `version==1` in `corner_create_property_success_with_computed_fields` (PRD §2.4 doesn't pin initial version).

## Step 6: Generate implementation — 2026-07-11T18:02:00.000Z

Generated `workspace/implementation/`: app.py (full server), requirements.txt (flask==3.0.3), start.sh (foreground, binds 0.0.0.0:$PORT default 10000). **38 route decorators** (37 declared endpoints + ops/clock). In-memory `Store` of dicts, zero seeded entities. Verified fee/occupant-load/fire-flow/flow math against factory defaults (valuation 100080 → estimated fee 20640). Booted server + ran 4 end-to-end scripts covering lifecycle, plan-review loop, all calcs, cascades C1/C2, permit-revoke cascade, OCC stale-version — all passed.

**PRD ambiguities resolved:** (1) Flow-test validation order — PRD §3.2 prose says readings checked FIRST (overrides scaffold priority), so `ERR_INVALID_FLOW_READINGS` before `ERR_FLOW_TEST_WINDOW_OVERLAP` — **matches Step 5's independent resolution**. (2) Logical clock used only for enumerated domain-event fields; wall-clock + monotonic seq for created_at/updated_at. (3) version starts at 1. (4) provided-but-unresolvable FK → 404 before missing-required 400. (5) findings-required-on-FAILED → ERR_VALIDATION (400) after SCHEDULED gate.

app.py compiles; all test files ast.parse cleanly.

## Step 7: Test and iterate — 2026-07-11T18:12:00.000Z

All 8 parallel rounds pass 55/55. Clean sweep.

- **Iterations run:** 2 (initial sweep + one fix).
- **Tests deleted:** None.
- **Fixes applied to `test_helpers/`:** None.
- **Fixes applied to `test_suite/`:** `test_05_inspections_and_cascades.py`, `test_overdue_order_escalates_violation` (line 63) — changed the abatement-order assertion from `== "OVERDUE"` to `== "ESCALATED"`. STEP 2 test-vs-PRD consistency bug: the assertion contradicted the exact PRD §3.7 sentence quoted in the test's own docstring — "the order moves `ISSUED` to `OVERDUE` and, in the same sweep, on to `ESCALATED`" — which makes `ESCALATED` the terminal order status after the overdue sweep. The implementation (`app.py` `process_overdue_orders`) was already PRD-faithful, so the assertion was made more faithful rather than weakening any check.
- **Fixes applied to `implementation/`:** None.

Only one test was ever failing, and it failed deterministically in all 8 rounds (no flakiness). Final state: 55/55 passing across all 8 parallel rounds.

## Step 8: Finalize PRD — 2026-07-11T18:14:00.000Z

Ran (not skipped — Step 7 had 1 `test_suite/` fix). Result: **no edits**. PRD §3.7 (line 190) already states verbatim "the order moves `ISSUED` to `OVERDUE` and, in the same sweep, on to `ESCALATED`", which uniquely pins the terminal order status, matching `implementation/app.py:1217`. The Step 7 fix was a test-side correction; implementation was already PRD-faithful. `PRD_FINALIZED.md` = verbatim copy of PRD.md (274 lines, 0% delta). Pre-edit search confirmed parallel ESCALATED references (app.py:398, 777, 815 certificate guards) consistent with PRD §3.8.

## Step 9: Complete PRD — 2026-07-11T18:20:00.000Z

Full PRD-vs-implementation scan. Source `PRD_FINALIZED.md` → `PRD_COMPLETED.md`. 274 → 274 lines (all in-paragraph inserts), char delta +910. **Ambiguity-pins: 6; Mismatch-revisions: 1.**

Changes:
- §2.3 Pagination — insert — ambiguity — limit clamps to [1,100], negative offset→0, non-integer→defaults (app.py:358-371)
- §2.3 Pagination — insert — ambiguity — created_at ties break by insertion (_seq) order (app.py:356)
- §2.4 Common Properties — revise — ambiguity — version "starts at 1 on creation" (app.py:219)
- §2.4 Logical Clock — insert — ambiguity — created_at/updated_at/api_request_timestamp use real wall-clock, not logical clock (app.py:213,227,163)
- §3.3 Fee payment — insert — ambiguity — amount_cents is non-negative integer (app.py:586)
- §3.8 Certificates — insert — ambiguity — suspend cascade leaves already-REVOKED cert REVOKED (placard stays RED); only non-REVOKED move to SUSPENDED (app.py:411-414)
- §3.8 Certificates — revise — mismatch — placard→YELLOW on any existing cert regardless of occupancy_status (app.py:973-976)
- §3.7 Overdue sweep — insert — ambiguity — eligible orders processed in ascending creation order; escalated_violation_ids returned in that order (app.py:1211)

## Pipeline complete — 2026-07-11T18:20:00.000Z

Final state: 55/55 tests passing across all 8 parallel stability rounds. All 9 pipeline steps done. Task directory contains SCAFFOLD*.yaml, PRD.md / PRD_FINALIZED.md / PRD_COMPLETED.md, test_helpers/, test_suite/ (55 tests), workspace/implementation/ (37 endpoints, in-memory Flask).
