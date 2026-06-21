# Worklog — task_0105_citizen_311_service_requests

## Step 1: Create task directory — 2026-06-02T14:57:36.000Z

Created `tasks/task_0105_citizen_311_service_requests/` with `workspace/` subdirectory. Scenario: 311 Citizen Service Requests (Expert difficulty). Task ID pre-assigned (no tasks/ scan).

## Step 2: Generate scaffold — 2026-06-02T15:31:22.000Z

## Task 0105 — 311 Citizen Service Requests: scaffold generation complete

**All three files written** to `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0105_citizen_311_service_requests/`:
- `SCAFFOLD.yaml` (§1.0–§1.7; no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Counts:**
- Entities: **13** (ServiceCategory, Jurisdiction, Department, SlaPolicy, Citizen, Agent, ServiceRequest, DuplicateCluster, WorkOrder, Escalation, StatusNotification, SatisfactionSurvey, ServiceWindow)
- Endpoints: **44**
- State machines: **5** (ServiceRequest, WorkOrder, DuplicateCluster, Escalation, SatisfactionSurvey)
- Calculations: **7** (jurisdiction_match, haversine_distance, sla_deadline, sla_breach_sweep, department_backlog, avg_satisfaction, window_overlap)
- Validations: **21**
- Errors: **22**
- Roles: **5** (SystemAdmin, Dispatcher, Agent, Citizen, Anonymous)
- Concurrency rules: **2** (OCC on cluster-create vs canonical request; OCC on work-order assign)

**Design coverage:** 18 difficulty instances (9 Difficulty Rules × 2) + 32 corner instances (27 active + 5 `excluded_because` stubs). All 22 errors are triggered across the design files.

**Profile:** workflow_orchestration + compliance_audit; hybrid topology; branching/cyclic state shape; hierarchical_override roles; layers = cascading side effects, rate/threshold triggers, derived-field reconciliation, scheduled/deferred actions, OCC.

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Key note on endpoint count:** 44 exceeds the Expert ceiling (20–32). This is the FK-reverse-reachability floor — 13 entities with 18 FKs each require a reverse-reachability GET (lint check (f)), plus 9 creates and ~16 lifecycle actions. Per the documented "Expert endpoint band vs FK reachability" guidance, the overage is accepted because the scaffold is lint-clean and every endpoint maps to a real operation (the scenario explicitly spans 8 subsystems: intake/category, geo/jurisdiction routing, SLA, duplicate clustering, work orders, notifications, escalation, survey). All literals in difficulty/corner asserts (SLA deadlines, overdue-hour tier selection, haversine boundary at 149.83 m / 177.91 m, round-half-up average 4.67, half-open vs closed window overlap) were computed by code, not estimated. Forbidden concurrency vocabulary is absent from all three files.

## Step 3: Copy INSTRUCTION.md — 2026-06-02T15:31:41.000Z

Copied root `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-02T15:37:02.000Z

PRD written to `workspace/PRD.md` — 274 lines.

**Domain:** Citizen 311 Service Requests (workflow orchestration + compliance audit). 13 entities, 5 roles, 44 endpoints, 22 error codes, 5 state machines, 7 calculations, 21 validation rules, 2 OCC rules.

**Major sections produced:**
- §1 Introduction (system goals, actor model, contract scope)
- §2 Global Specifications: 2.1 RBAC (5 roles, header semantics, identity translation), 2.2 Response Structure, 2.3 Pagination, 2.4 Common Properties & Versioning, 2.5 Nested Retrieval & existence ordering, 2.6 Validation Ordering, 2.7 OCC, 2.8 Logical Clock, 2.9 Geographic Routing (smallest-box match + haversine), 2.10 Backlog & Congestion, 2.11 Numeric Precision
- §3 Business Logic (10 subsections): Reference Config, Intake & Triage, Routing & SLA Deadlines, Work Order Execution, Reopening, Closing, Duplicate Clustering, Maintenance/Blackout Windows, Escalations & SLA Sweep, Satisfaction Surveys
- §4 Endpoint table (44 rows)
- §5 Error Code Catalogue (22 rows)

**Hard Contract Reports:** Field coverage PASS (56/56 entity fields, 6/6 extra ids); Rule coverage PASS (21/21 validations, 2/2 OCC, 21/21 transitions, 7/7 calculations, 22/22 error IDs, sibling-branch symmetry 2 groups equal density); Path purity PASS (0 path tokens in §3). All three hard contracts PASS.

## Step 5: Generate unit tests — 2026-06-02T15:50:00.000Z

Generated complete test infrastructure for `task_0105_citizen_311_service_requests` from the design-index-only contract.

**test_helpers/ (Stage 1) — 9 files:** `__init__.py`, `types.py` (entity TypedDicts + enums; append-only StatusNotification/Escalation carry only id+created_at), `api_client.py` (one method per endpoint), `api_errors.py` (22 error IDs + HTTP-status map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque shared constants for SystemAdmin/Dispatcher/Anonymous; per-instance make_agent_headers/make_citizen_headers for entity-backed roles), `fixtures.py` (tiered composite setups: clock/config, request creation, routed→started→resolved lifecycle, cluster-on-canonical, SLA-breach builders).

**test_suite/ (Stage 2) — 8 test files + conftest.py.**

**Totals:** 68 test functions, all collecting cleanly.
- Queue A (Difficulty): 36 tests — all 18 instances (9 rules × 2) covered, 2 tests each.
- Queue B (Corner): 32 tests — all 32 non-stub instances covered with ≥1 test each.

**Instances skipped:** None for PRD-filter failure. The 5 `excluded_because:` corner stubs correctly NOT translated (initial_state_submitted_on_create, start_workorder_from_open_valid_transition, derived_member_count_reconciled_on_attach, cascade_complete_chain_end_to_end, route_changes_visible_in_same_response).

**Verification:** Every test docstring ends with exactly one Design: tag (68 tags, no dual-tags). Every cited PRD sentence confirmed verbatim. No scaffold/section-reference leakage. All 68 tests collect with zero import errors.

## Step 6: Generate implementation — 2026-06-02T15:50:00.000Z

## Implementation summary — task_0105_citizen_311_service_requests

**Source files** (under `workspace/implementation/`, Python 3 + Flask 3.0.3):
- `start.sh` — foreground launcher, reads `$PORT` (default 10000), binds `0.0.0.0`, `exec python3 app.py`; guards `pip install` behind an `import flask` sentinel.
- `requirements.txt`, `app.py` (entry + blueprint registration + ApiError/404/405/catch-all handlers in standard envelope).
- Foundation: `db.py` (in-memory dicts keyed by id, common-field stamping, `_seq` insertion-order ordering), `clock.py` (logical clock + ISO-8601 ms), `response.py` (envelope), `errors.py` (full ERR_* catalog), `middleware.py` (X-User-ID/X-User-Role auth + RBAC), `validate.py` (schema/pagination), `serialize.py` (per-entity output projection).
- `routes/`: config, requests, clusters, work_orders, escalations, surveys, windows, clock_ctl.
- `services/`: calc.py (jurisdiction_match smallest-box, haversine, SLA deadline, strict breach sweep, department_backlog, round-half-up satisfaction, window overlap), notify.py, workflow.py (cross-aggregate cascades).

**Endpoints implemented**: all 44 from PRD §4.

**State machines / calculations**: State machines centralized in `services/workflow.py` (request ROUTED→IN_PROGRESS→RESOLVED bubble-ups, RESOLVED→REOPENED→IN_PROGRESS cascade with WorkOrder COMPLETED→REOPENED→IN_PROGRESS + backlog recompute + survey expiry + escalation compensation) with per-route guards enforcing §2.6 validation priority (auth→role→existence→ownership→agent-dept→state→OCC→business). Calculations isolated in `services/calc.py` with Decimal+ROUND_HALF_UP satisfaction mean, strict `now > deadline` breach, half-open jurisdiction boxes + smallest-area tie-break, inclusive 150m haversine cluster radius, MAINTENANCE-closed / BLACKOUT-half-open window semantics. OCC uses expected_canonical_version / expected_work_order_version → ERR_STALE_VERSION 412.

**Verification**: Three smoke suites (~90 assertions) pass; `bash start.sh` boots to HTTP 200 within ~1s with empty store (no seeding); in-memory only. All Python compiles clean.

## Step 7: Test/fix iteration loop — 2026-06-02T15:57:56.000Z

All 8 rounds green: 68/68 in every round (verified on disk: results.1.json–results.8.json all 68/68).

Iterations run: 3 sweeps total (1 diagnostic baseline + 2 verification sweeps).

Root cause: 56 of 68 tests failed in every round with an identical setup error — `ERR_INVALID_REQUEST - code must be uppercase letters A-Z and underscore`. This was a single test_helpers bug shared by every fixture that creates a category. The remaining 1-test failure in the concurrent sweep was an environment artifact (cold-start boot contention), not a defect.

Tests deleted: none. Every failing test traced to a verbatim PRD rule and was uniquely derivable; the failures were a fixture defect, not a coverage/derivability problem.

Fixes applied to test_helpers/:
- `test_helpers/fixtures.py` — `create_category` generated `code=f"CAT_{n}"` (where `n` is an integer counter), producing codes like `CAT_1` that contain a digit. PRD §3.1 states a category's code is "composed of uppercase letters A–Z and underscores", so the PRD-faithful implementation correctly rejected the digit with `ERR_INVALID_REQUEST`. Added a `_code_suffix(n)` helper that bijectively encodes the counter in base-26 uppercase letters (A, B, ... Z, AA, ...) and changed the default to `code=f"CAT_{_code_suffix(n)}"`, keeping codes unique while satisfying the A–Z/underscore rule. STEP 2 fix (test bug), not an implementation change.

Fixes applied to implementation/: none. The implementation's category-code validation is PRD-required and correct; no logic was changed. start.sh already guards pip with an import sentinel and the in-memory store starts empty on every boot.

Final state: all 8 parallel rounds pass 68/68; a solo run also passes 68/68. The only residual flakiness observed was cold-start boot contention when all 8 rounds launch their first server simultaneously (exacerbated by 5 sibling pipelines on the same host); staggering the launches by 0.75s eliminated it — a sweep-launch concern, not an artifact defect.

## Step 8: Finalize PRD — 2026-06-02T15:59:45.000Z

PRD_FINALIZED.md produced as a verbatim copy of PRD.md, with no edits — the correct, expected outcome.

**Line counts:** PRD.md = 274 lines, PRD_FINALIZED.md = 274 lines. **0% delta** (byte-identical; `diff -q` reports IDENTICAL).

**Changes:** No edits. The single Step 7 fix was a pure test_helpers fixture bug (the `create_category` factory generated codes containing digits, e.g. `CAT_1`), not a PRD silence or PRD/impl mismatch. The PRD-faithful implementation correctly rejected the digit, and PRD §3.1 already pins the rule verbatim.

**Pre-edit search log (single subject, no edit committed):**
- (a) Subject: category `code` validation rule (PRD §3.1: "unique, composed of uppercase letters A–Z and underscores").
- (b) Impl paths enumerated: `routes/config.py:17` (`_CODE_RE = ^[A-Z_]+$`), `:28–30` (create_category requires non-empty matching code, else ERR_INVALID_REQUEST), `:44–45` (uniqueness check), `:49` (stored), `serialize.py:14` (exposed). No other module validates/mutates/re-keys on `code`; write-once at creation. Regex `^[A-Z_]+$` = exactly "uppercase letters A–Z and underscores"; uniqueness check = exactly "unique". PRD §3.1 uniquely determines all.
- (c) Wording adjustment: None. PRD already pins the rule with no silence and no mismatch.

## Step 9: Complete PRD — 2026-06-02T16:03:47.000Z

PRD_COMPLETED.md produced via full PRD-vs-implementation scan.

**Source vs completed:** PRD_FINALIZED.md → PRD_COMPLETED.md: 274 → 274 lines (unchanged); 41,682 → 42,511 chars (**+829 chars**). All changes in-paragraph; no new sections, no new lines. Section headers intact (29 = 29).

**Counts:** ambiguity-pins: 4, mismatch-revisions: 1.

**Changes:**
- §2.8 The Logical Clock — insert — ambiguity — pinned `_clock/set` response shape (`{ "clock_now": <ISO 8601 instant> }`) and that advance `hours` is a JSON integer whose sign is not otherwise constrained — `routes/clock_ctl.py:29-30,38-45`, `clock.py:55-57`.
- §3.1 Reference Configuration — insert — ambiguity — pinned that a category's `default_department_id` is required at creation and the named department must already exist, else `ERR_NOT_FOUND` — `routes/config.py:32,37-38`.
- §3.2 Intake and Triage — insert — ambiguity — pinned `requested_priority` precedence at triage (body override > value stored at intake) and that a triage-time value is written back onto stored `requested_priority` — `routes/requests.py:136-139`.
- §3.4 Work Order Execution (completion) — revise — mismatch — pinned completion check order (agent-dept membership → state → acting-agent-is-assigned → `completion_note`) and that an assigned-agent mismatch is rejected with `ERR_AGENT_WRONG_DEPARTMENT` — `routes/work_orders.py:123-138`.
- §3.9 Escalations — insert — ambiguity — pinned that `resolved_by_role` records the acting role string verbatim (`Dispatcher`/`Agent`/`SystemAdmin`) or the literal `system` for the request-resolution cascade — `routes/escalations.py:58`, `services/workflow.py:59-60`.

**Deliberate non-changes:** routing's "resolved department not found" 404 is unreachable now that both override and default department ids are validated at creation; list/filter query-param keys already admitted by §4 "List/filter" wording; global §2.6 ordering already pins agent-dept (priority 5) before state (priority 6) for work-order `start`.

---

## Pipeline complete

All 9 steps finished. Final state: **68/68 tests passing across all 8 parallel sweep rounds.** Task directory contains SCAFFOLD.yaml (+ DIFFICULTY/CORNER design files), PRD.md → PRD_FINALIZED.md (verbatim copy) → PRD_COMPLETED.md (5 ambiguity/mismatch pins), test_helpers/, test_suite/ (68 tests), and workspace/implementation/ (44 endpoints, Python/Flask, in-memory). 0 tests deleted; 1 test_helpers fixture fix; 0 implementation fixes.
