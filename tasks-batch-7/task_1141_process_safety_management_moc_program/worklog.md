# Worklog — task_1141_process_safety_management_moc_program

## Step 1: Create task directory — 2026-08-11T00:30:00.000Z

Pre-assigned output folder `tasks/task_1141_process_safety_management_moc_program` with `workspace/` subdirectory already exists; auto-index scan skipped per instruction. Step 1 treated as done.

## Step 2: Generate scaffold — 2026-08-11T01:15:24.000Z

Scaffold generation complete. All three artifacts written and lint-clean.

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_1141_process_safety_management_moc_program/SCAFFOLD.yaml` (~102 KB; §1.0–§1.7 only — no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1141_process_safety_management_moc_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (~73 KB; single top-level key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1141_process_safety_management_moc_program/SCAFFOLD_CORNER_DESIGN.yaml` (~132 KB; single top-level key `scaffold_corner_design`)

**Counts**
- Entities: 15 (PlantUnit, Personnel, MocRequest, TechnicalReview, PhaStudy, PhaRevalidation, Pssr, ActionItem, EvidenceItem, IncidentInvestigation, Audit, AuditFinding, ProcedureUpdate, TrainingAssignment, ExtensionRequest)
- Endpoints: 82 (incl. `POST /psm/_clock/set_current_utc` with pinned default 2026-05-01T00:00:00Z; every FK has a reverse-reachability GET)
- State machines: 12 — MocRequest (13 states, revision cycle + RIK bypass branch + clock-driven expiry), ActionItem (rejection + reopen cycles), PhaStudy (full revalidation cycle), plus 9 others
- Calculations: 9 — dual-variant pairs on two domains (MOC screening vs definitive risk; PHA nominal vs risk-accelerated due), combinatorial modes (a) nested min/max + posture branch, (b) pinned per-update-then-average rounding, (c) two-phase unit index
- Validations: 16 ordered priorities (auth → authz → existence → OCC 412 → state → 4-tier business_safety incl. SoD/qualifications/posture → temporal → 4-tier constraint → referential)
- Errors: 60; Roles: 9 (4 entity-backed with 4 segregation-of-duties rules); Concurrency rules: 2 OCC create-with-supersede races on MocRequest.version
- Difficulty design: 18 instances (9 rules × 2), all with structured `setup_api_calls`/`trigger` chains and precomputed literal asserts
- Corner design: 59 instances across all 9 guide sections (54 with test recipes + 5 `excluded_because` stubs)

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (82 endpoints, 15 entities, 18 + 54 instances, 895 calls scanned, 0 violations.)

**Key consistency work during the pass**: fixed index arithmetic in three FROZEN-setup instances (3 overdue P1 + overdue study = exactly 70), restored two personnel-creation calls a shared-block edit had removed from the cascade instance, quoted all list-index capture JSONPaths and bracketed `grounds` refs for YAML flow safety, and added the missing `ERR_CLOCK_REGRESSION` validation row. No sibling task directories were inspected at any point.

## Step 3: Copy shared files — 2026-08-11T01:15:41.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `tasks/task_1141_process_safety_management_moc_program/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-11T01:35:00.000Z

PRD generation complete. Final summary:

**Output path:** `/home/ubuntu/github/CodingPRD/tasks/task_1141_process_safety_management_moc_program/workspace/PRD.md`

**Section list:**
- §1. Introduction (2 paragraphs — regulatory/business-context angle)
- §2. Global Specifications & System-Wide Principles: 2.1 User and Role-Based Access Control; 2.2 API Response Structure (byte-identical verbatim block, confirmed programmatically); 2.3 Pagination; 2.4 The Logical Clock and Calendar-Day Semantics; 2.5 Common Resource Properties and Identity; 2.6 Numeric Precision, Rounding, and Date Arithmetic; 2.7 Optimistic Concurrency Control; 2.8 Nested Resource Retrieval; 2.9 Validation Pipeline and Priority Ordering; 2.10 Unit Process Safety Index and Posture Gating; 2.11 Hierarchical Consistency, Cascades, and Compensating Actions
- §3. Business Logic & Workflows: 3.1 Program Foundations: Plant Units and the Personnel Registry; 3.2 MOC Intake: Drafting, Classification, and Screening Risk; 3.3 Technical Review and the Revision Cycle; 3.4 Approval, Procedure Updates, and Training Readiness; 3.5 Pre-Startup Safety Review and Startup Authorization; 3.6 Life in Service: Activation, Temporary Expiry, and Extensions; 3.7 PHA Studies, Revalidation, and Incident Feedback; 3.8 Audits, Findings, and Corrective Actions; 3.9 Action Items, Evidence, and the Verification Loop
- §4. Endpoint Definitions (82 rows, exactly 4 columns, matching all 82 scaffold endpoints)
- §5. Error Code Catalogue (60 rows, exactly 2 columns, matching all 60 scaffold errors)

**Line count:** 369 lines (long-paragraph prose style). File ends at §5 with no audit footer.

**Zero-silence self-audit (hard contracts):**

```
Field coverage check:
- entities[].fields: 95 required, 95 present, 0 missing
- endpoints[].request_body: 52 required, 52 present, 0 missing
- endpoints[].query_params: 4 required, 4 present, 0 missing
- common fields (id/created_at/updated_at/version): 4 required, 4 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 17 checked, 17 expressed in prose (global pipeline §2.9 with explicit sub-orderings 6.0-6.4 / 7-7.5 / 8.0-8.3, plus pinned numeric-cap order restated at extension creation in §3.6), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint + expected_moc_version non-optional + ERR_STALE_MOC_VERSION/HTTP 412, evaluated before business checks), 0 missing
- state_machines[].transitions: 55 checked (across all 12 machines, incl. RIK bypass branch, 3 abandon-restore branches, 3 void branches, 2 start branches, supersede-VOID pairs, revert bubble-up), 55 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed in reconstruction-safe prose (screening/definitive risk with class multipliers 1.0/1.2/0.5, min-25 cap, detection ramp 1+(det-1)*0.25, posture factor 1.25 at index >= 70; rank bands 5/12/20 inclusive-low; nominal/risk-accelerated dues with 30-day months, 0.1-per-incident compression, 0.25 floor, day-floor; SLA 30/90/180 with strict-less-than overdue; pinned round-per-update-then-average training coverage; two-phase pinned index 15/25/20/10/5 capped at 100 with bands 40/70 inclusive-low; extension cap order count -> days -> total), 0 missing
- validations[] conditions: 17 checked, 17 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed in workflow narratives (ownership scopes, posture gates, completion gates, window checks each placed at their guarded operation), 0 missing
- entities[].fields[] structured content: all defaults/initials stated (180/2/90/360/100.00 unit defaults, empty qualifications, active=true, zero counters, null-until-set stamps, EvidenceItem append-only exception), 0 missing
- sibling-branch symmetry: 12 groups checked (withdraw 2, verdict 2, PSSR approve 2, PSSR reject 2, void 3, start 2, abandon 3, incident-cascade 3, open-revalidation 3, risk bands 4, SLA 3, severity->priority 3), 12 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 563
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional mechanical checks: all 60 error IDs, 40 state values, 37 enum values, and 9 role names appear verbatim in backticks; §2.2 is byte-identical to `section-2.2-response-structure.md`; every role's `identity:` translated individually in §2.1 (6 entity-backed Personnel roles, 3 opaque roles). The forbidden design-index files were not opened.

## Step 5: Generate unit tests — 2026-08-11T02:10:00.000Z

Generation complete. Summary:

## Files written

**test_helpers/** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1141_process_safety_management_moc_program/test_helpers/`):
- `types.py` — 19 enums + 15 entity TypedDicts (EvidenceItem correctly omits `updated_at`/`version` per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)` with ~62 methods, one per PRD §4 endpoint
- `api_errors.py` — all 60 error IDs + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions + `assert_unit_index_invariants` (0–100 band/posture consistency)
- `factories.py`, `constants.py` (clock default, class multipliers, SLA days, index weights, band edges)
- `test_users.py` — shared constants for opaque roles; mandatory `make_<role>_headers(user_id)` builders for the six entity-backed roles
- `fixtures.py` — composite drivers: `drive_moc_to_technical_review/approval_pending/approved/implemented/in_service/closed`, `setup_implemented_scenario`, `setup_in_service_scenario`, `drive_unit_to_frozen_via_overdue_and_study` (exact index-70 targeting), `setup_moc_with_split_training_coverage` (the pinned 66.67/75.00 → 70.84 scenario), incident/audit/revalidation drivers, OCC-aware `create_pssr_for_moc`/`moc_version` (always GETs fresh version, sidestepping version-counting ambiguity)
- `__init__.py` — barrel export

**test_suite/** (under `.../test_suite/`): `conftest.py` + `test_01_unit_config_and_registry.py`, `test_02_moc_intake_classification.py`, `test_03_technical_review_and_risk.py`, `test_04_approval_procedures_training.py`, `test_05_pssr_startup.py`, `test_06_action_items_evidence.py`, `test_07_lifecycle_close_expiry_extensions.py`, `test_08_pha_revalidation.py`, `test_09_incidents_audits.py`, `test_10_posture_security_envelope.py`.

## Test counts
- **Queue A (Difficulty)**: 18/18 instances, exactly 2 tests each → **36 tests**
- **Queue B (Corner)**: 54/54 non-stub instances, 1 test each → **54 tests**
- **Total: 90 tests**, all collected by pytest successfully

## Instances skipped
None. Every non-stub instance passed the PRD-first two-condition filter. The 5 `excluded_because:` corner stubs were not translated (their `difficulty_instance` cross-references all resolve to real §1.8 instances — verified). One borderline case (`sod_verifier_is_completer_rejected`: PsmManager presenting the completer's id) was analyzed against the opaque-role carve-out in PRD §2.1 and retained as uniquely derivable, since verify is PsmManager-exclusive and the SoD error would otherwise be unreachable; PRD §3.9 names the trigger verbatim.

## Self-audit verdicts
- **Tag coverage**: scripted check — every test has exactly one `Design:` line as the last docstring line; all 90 tags resolve to real instances; no tag points at a stub; 0 under-covered instances. PASS
- **PRD citations**: scripted verbatim check — every quoted segment in every docstring greps literally (modulo whitespace) against `workspace/PRD.md`; 16 initial mismatches (elisions/added punctuation) were fixed to contiguous verbatim text; final run 0 failures. PASS
- **Lint**: `py_compile` clean on all 20 files; pyflakes clean on `test_suite/` (barrel re-export warnings in `__init__.py` are by design per the skill template); `pytest --collect-only` → 90 tests, 0 errors. PASS

Notable design decisions: priority-pair tests (queue A rule `priority_pair_validation_conflict`) were kept because PRD §2.9 states the pipeline ordering verbatim ("the first failing check determines the error returned" + numbered steps), so they are not silence-pattern violations. All asserted numbers were independently recomputed (21.60/42.00 definitive scores, 70.84 pinned rounding, 2026-12-05 accelerated due, 2027-12-23 revalidation due, index 40/45/70/100 compositions) and match the pre-computed values in the design indices.

## Step 6: Generate implementation — 2026-08-11T02:10:00.000Z

Implementation complete. Summary:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1141_process_safety_management_moc_program/workspace/implementation/`)

- `start.sh` — foreground launcher, `exec python3 app.py`, guarded pip install (`import flask` check), binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask
- `app.py` — Flask app, blueprint registration, ApiError/404/405/500 envelope handlers
- `db.py` — in-memory `Store` (15 dicts keyed by id + logical clock defaulting to 2026-05-01); **no seeding** — store starts empty every boot
- `errors.py` — ApiError + all 60 catalog error-id constants
- `helpers.py` — response envelope (`meta.api_request_id`/`api_request_timestamp` 3-fractional-digit ISO, `response_type`, `data`; error body `error_id`/`message`), `X-User-ID`/`X-User-Role` auth + RBAC decorator, field validators (`ERR_INVALID_REQUEST`), calendar-day date parsing (UTC-midnight normalization), limit/offset pagination (default 10, 1..100)
- `services.py` — calculations (screening/definitive risk with Decimal round-half-up 2dp, risk-rank bands, PHA nominal/risk-accelerated dues with 0.25 floor via Decimal, pinned two-step training coverage, two-phase unit safety index with inclusive-low posture bands), `recompute_unit`, bubble-ups (verify/reopen), clock sweep (PHA DUE_SOON/OVERDUE aging, TEMPORARY MOC expiry + REVERT P1 spawn), serializers
- `routes_core.py`, `routes_moc.py`, `routes_pha.py`, `routes_pssr.py`, `routes_actions.py`, `routes_safety.py`, `routes_training.py`, `routes_extensions.py`

## Endpoint count
**82 API endpoints** — verified programmatically via Flask's url_map (83 routes minus Flask's built-in `/static`), matching the 82 method+path pairs in SCAFFOLD.yaml exactly. Orchestrator independently re-verified: 82 scaffold endpoints vs 82 Flask routes, missing=[], extra=[].

## State machines implemented (12)
MocRequest (13 states, incl. RIK class-driven bypass, revision cycle, revert bubble-up close), TechnicalReview, PhaStudy (cyclic, with status_before_revalidation restore), PhaRevalidation, Pssr (supersede-to-VOID, reject backward branch), ActionItem (verify/reject/reopen/void loops with compensating count conservation), IncidentInvestigation (feeds_pha cascade forcing REVALIDATION_REQUIRED), Audit, AuditFinding (bubble-up close/reopen), ProcedureUpdate, TrainingAssignment, ExtensionRequest (supersede, deny compensating invariant). OCC via `expected_moc_version` (412 `ERR_STALE_MOC_VERSION`) on PSSR/extension create; validation pipeline ordered auth → role → existence → OCC → state → ownership/qualification/SoD/posture/checklist → temporal → constraints (pinned cap order) → completion gates.

## Smoke-test evidence
`bash start.sh` boots cleanly from a fresh process (verified 4 separate boots). Live-server tests all passed: full MOC lifecycle (classify → review verdicts → approve → procedures/training → mark-implemented → PSSR → authorize → activate → close), TEMPORARY extensions (caps, supersede, deny invariant) + clock-sweep expiry + REVERT-verify bubble-up, incident→PHA forced-revalidation cascade with risk-accelerated dues (324d), audit 14-day separation + corrective-action bubble-ups, pinned coverage rounding (70.84 vs naive 71.43), posture-factor definitive score (27.00 CRITICAL at index 75), DUE_SOON/OVERDUE day-boundary transitions, FROZEN/RESTRICTED posture gates, SoD rejections, and fresh-boot isolation (empty store + 2026-05-01 default clock).

## Step 7: 8-round stability sweep + fix loop — 2026-08-11T02:35:00.000Z

Three sweep iterations (`prd-bench-local-run --isolation per-test-server`, 8 parallel rounds, 90 tests each).

- Iteration 1: 83-84/90 per round. Failures: (a) ids minted as `uuid.uuid4().hex` (no dashes) failed the UUID format assertion — fixed in `services.py` / `routes_actions.py` (`str(uuid.uuid4())`); (b) audit 14-day-clear separation was off by one (`timedelta(days=14)` in a strict `<` comparison admitted a 14-day end-to-start gap, i.e. only 13 clear days) — fixed to 15 in `routes_safety.py`; (c) `create_unit_payload` default `unit_code` "TU-1" collided when a test created two units — fixed in `test_helpers/factories.py` (unique per-call default); (d) flaky "server could not be restarted" under 8-way parallel load (runner port-kill race) — hardened `start.sh` to free its own port (lsof -n -P + bind probe, ~10s budget) before exec.
- Iteration 2: 89/90 in all 8 rounds. Remaining: `create_standard_actors()` fixed employee_refs collided on second invocation within one test — fixed in `test_helpers/fixtures.py` (unique per-call refs).
- Iteration 3: **90/90 in all 8 rounds. 0 failed, 0 errors.**

Orchestrator record — Step 7 subagent returned summary (verbatim):

All 8 rounds pass: 90/90 in every round of the final sweep.

## Summary

- **Iterations run**: 3 (8 parallel rounds each, 90 tests per round, `--isolation per-test-server`).
- **Tests deleted**: none. Every failing test traced to a verbatim PRD rule; no PRD-silence or unique-derivability collapses found.
- **Fixes to `test_helpers/`** (2):
  - `factories.py::create_unit_payload` — default `unit_code` was the shared constant `"TU-1"`; `test_extension_day_cap_and_total_cap_violations` creates two units in one test, so the second create drew `ERR_UNIT_CODE_EXISTS` (PRD §3.1 requires unit_code uniqueness). Default is now minted unique per call (`TU-{seq}`).
  - `fixtures.py::create_standard_actors` — fixed employee_refs (`E-REQ`/`E-REV`/`E-APP`/`E-LEAD`) collided when the same test built two actor sets (PRD §1: `employee_ref` unique across all personnel). Refs are now unique per call (`E-REQ-{n}` etc.).
- **Fixes to `implementation/`** (3):
  - `services.py::new_entity` and `routes_actions.py::attach_evidence` — ids were minted as `uuid.uuid4().hex` (32 hex chars, no dashes), violating PRD §2.5's "server-minted UUID" as enforced by the test UUID format assertion. Now `str(uuid.uuid4())` (canonical dashed form). Cured 4 deterministic failures (unit/MOC/evidence id assertions).
  - `routes_safety.py::create_audit` — the 14-day-clear separation check used `timedelta(days=14)` in a strict `<` comparison, admitting an end-to-start gap of exactly 14 days (only 13 clear days). PRD §3.8: "must stand at least fourteen days clear" — with closed windows that requires a raw day difference of ≥15, so the buffer is now 15 days (08-19 start vs 08-05 end rejected, 08-20 allowed).
  - `start.sh` — hardened against the flaky "API server could not be restarted" runner errors (7 occurrences across sweep 1 under 8-way parallel load): the script now frees its own `$PORT` before exec (lsof `-n -P` kill of leftover LISTEN sockets + bind-probe retry, ~10s budget), covering the case where the runner's pre-launch port kill races/times out.
- **Final state**: sweep 3 — all 8 rounds `passed == total == 90`, `failed == 0`, `errors == 0`. Worklog updated.

Orchestrator verification: all 8 `results.{i}.json` files exist on disk; each reports passed=90, total=90, failed=0, errors=0.

## Step 8: Finalize PRD — 2026-08-11T02:45:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1141_process_safety_management_moc_program/workspace/PRD_FINALIZED.md` written.

## Line counts / delta

- PRD.md: 369 lines; PRD_FINALIZED.md: 369 lines (0.0% line-count delta; 2 lines revised in place, no insertions/deletions).

## Changes (2 edits; the other 3 step_7 items required none)

- **§2.5 — revise — `id` bullet now pins the canonical dashed 8-4-4-4-12 lowercase-hex serialization with an example — `implementation/services.py:36` (`new_entity`), `implementation/routes_actions.py:182` (`attach_evidence`).**
- **§3.8 — revise — audit separation rule now pins the boundary: closed windows require ≥14 whole calendar days strictly between them (start ≥ neighbor end + 15 days, symmetrically); Aug-5 end rejects starts ≤ Aug 19, allows Aug 20 — `implementation/routes_safety.py:177–183` (`create_audit`).**
- No edit for the two `test_helpers/` fixes (factories `unit_code`, fixtures `employee_ref`): PRD §3.1 already pins both uniqueness rules verbatim (`ERR_UNIT_CODE_EXISTS`, `ERR_EMPLOYEE_REF_EXISTS`) — pure fixture bugs. No edit for `start.sh`: port-freeing is harness infrastructure, no API behavior.

## Per-edit pre-edit search log

**Edit 1 (§2.5 id format)**
- (a) Subject: rendering/serialization format of server-minted `id` values on all resources.
- (b) Paths enumerated: `services.py:33–41` `new_entity()` — the sole mint helper — and every caller: `routes_core.py:77` (unit), `routes_core.py:146` (personnel), `routes_moc.py:68` (MOC), `routes_moc.py:33` (review), `routes_pha.py:33` (study), `routes_pha.py:81` (revalidation), `routes_pssr.py:70` (PSSR), `services.py:290` (`spawn_action_item`, all action items incl. cascades), `routes_safety.py:44` (incident), `routes_safety.py:184` (audit), `routes_safety.py:268` (finding), `routes_training.py:28` (procedure), `routes_training.py:85` (training), `routes_extensions.py:62` (extension); plus `routes_actions.py:182` (EvidenceItem, minted inline). Serializers (`_common`, `ser_evidence`) pass `id` through unchanged. Grep for `uuid` across `implementation/` confirms these are the only two mint sites; both now emit `str(uuid.uuid4())`. The runner's `is_valid_uuid` regex (`^[0-9a-f]{8}-...{12}$`, case-insensitive) and §2.2's distinct `req_`-prefixed `api_request_id` were checked to avoid scoping confusion.
- (c) Wording scoped to the `id` field definition itself (not "primary resources" only), so it also covers `EvidenceItem.id` — which §2.5's exception paragraph defines as the same `id` field — and says "lowercase-hexadecimal" to match `str(uuid.uuid4())` exactly. No claim made about `api_request_id`.

**Edit 2 (§3.8 audit separation boundary)**
- (a) Subject: boundary semantics of the "fourteen days clear" audit-window separation rule.
- (b) Paths enumerated: only `routes_safety.py:160–194` `create_audit` enforces `ERR_AUDIT_WINDOW_CONFLICT` (no audit PATCH/reschedule exists); verified the status filter (`SCHEDULED`/`FIELDWORK`/`REPORTED`, so `CLOSED` audits are exempt — already PRD-pinned), the symmetric two-sided check (`start < a.end + 15d and a.start < end + 15d`), and the closed-window reading (`begin_audit_fieldwork` at line 239 uses `start <= clock <= end`, both bounds inclusive). Adjacent but distinct behavior checked so the edit doesn't bleed: PSSR overlap (`routes_pssr.py`, half-open intervals per §3.5 — untouched), §2.9 step 8's bare mention of `ERR_AUDIT_WINDOW_CONFLICT` (name only), §4 table row 283 ("14-day buffered separation" — still accurate under the pinned reading), and the `end < start` → `ERR_INVALID_REQUEST` guard at lines 168–169 (orthogonal, untouched). Test cross-check: `test_09_incidents_audits.py:225–262` pins Aug-5-end → Aug-19-start rejected, Aug-20-start allowed, matching `buffer = timedelta(days=15)` with strict `<`.
- (c) Replaced the ambiguous trailing clause ("comes within fourteen days of a neighbor") with the explicit boundary rule plus the worked Aug-5/Aug-19/Aug-20 example; kept "at least fourteen days clear" as the headline phrase so §4's "14-day buffered separation" stays consistent, and scoped everything to audits only.

## Step 9: Complete PRD — 2026-08-11T02:55:00.000Z

The file is complete: 369 lines in both (in-paragraph edits only), char delta +2804 (60,448 → 63,252).

## Summary

**Source vs output:** `PRD_FINALIZED.md` (369 lines, 60,448 chars) → `PRD_COMPLETED.md` (369 lines, 63,252 chars), char-delta **+2,804**. All edits are in-paragraph inserts/revisions; no new sections, no new paragraphs.

**Counts:** 16 ambiguity-pins, 1 mismatch-revision (17 changes total).

**Changes:**

- §2.1 — insert — ambiguity — entity-backed role with an `X-User-ID` matching no Personnel record fails caller qualification checks with `ERR_QUALIFICATION_MISSING` (not 404) — implementation/routes_moc.py:411-413, implementation/routes_pssr.py:46-48
- §2.4 — insert — ambiguity — clock set normalizes `to_iso8601` to its UTC calendar day (time discarded) — implementation/routes_core.py:34-40
- §2.4 — insert — ambiguity — clock-set success body is `{"current_utc": <day>T00:00:00Z}` with 200 — implementation/routes_core.py:42
- §3.1 — insert — ambiguity — the four integer limits and the threshold carry no range validation (integer/number type only) — implementation/routes_core.py:62-66
- §3.1 — insert — ambiguity — `unit_code` is immutable; PATCH does not accept it — implementation/routes_core.py:57-67
- §3.2 — insert — ambiguity — MOC-creation FROZEN posture gate fires before request-body parsing — implementation/routes_moc.py:60-67
- §3.3 — insert — ambiguity — posture and PHA-currency gates apply to initial submit only, not to resubmit — implementation/routes_moc.py:201-213
- §3.3 — insert — ambiguity — submit-verdict returns the updated TechnicalReview object (not the MOC) for either verdict — implementation/routes_moc.py:449
- §3.4 — insert — ambiguity — approval condition element shape (`title`, `priority` P1/P2/P3, active `assignee_id`, optional `due_in_days` ≥ 1) and validate-all-before-spawn atomicity — implementation/routes_moc.py:229-248
- §3.4 — insert — ambiguity — MOC with no PUBLISHED update carries null `training_coverage_pct` — implementation/services.py:203-217
- §3.5 — insert — ambiguity — `field_window_end` < `field_window_start` on PSSR create is malformed `ERR_INVALID_REQUEST` — implementation/routes_pssr.py:51-52
- §3.5 — insert — ambiguity — punch-item creation returns 201 carrying the spawned ActionItem — implementation/routes_pssr.py:143
- §3.5 — insert — ambiguity — PSSR rejection pushes the MOC back only when the MOC currently stands in `IMPLEMENTED_PSSR_PENDING` — implementation/routes_pssr.py:179-182
- §3.6 — insert — ambiguity — closing a TEMPORARY MOC via `/close` draws `ERR_MOC_INVALID_STATE` (folded into the state check, not `ERR_MOC_NOT_TEMPORARY`) — implementation/routes_moc.py:354-359
- §3.6 — insert — ambiguity — `requested_days` < 1 is malformed `ERR_INVALID_REQUEST`, rejected before the three caps — implementation/routes_extensions.py:42-44
- §3.7 — revise — mismatch — dues-recompute trigger list ("at study creation, at revalidation completion, and on unit configuration changes") extended with "at the closure of any incident investigation", since impl recomputes all three dues on incident close so the risk-accelerated due absorbs newly CLOSED severe incidents — implementation/routes_safety.py:144-149
- §3.7 — insert — ambiguity — incident `submit-findings` requires the `findings` array (may be empty); closure on a unit with no PHA study sets `feeds_pha` but runs no cascade — implementation/routes_safety.py:107, 135-136
- §3.8 — insert — ambiguity — audit report's `findings` array is required (may be empty) and severity enum pinned inline — implementation/routes_safety.py:255-261
- §3.9 — insert — ambiguity — the `due_in_days`-accepting creation paths are enumerated (manual create, approval conditions, PSSR punch items), override must be an integer ≥ 1; unknown `status`/`priority` list-filter values are malformed `ERR_INVALID_REQUEST` — implementation/routes_actions.py:52-55, 36
- §3.9 — insert — ambiguity — reopen retains `completer_id` and `verifier_id` as recorded — implementation/routes_actions.py:138-149

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1141_process_safety_management_moc_program/workspace/PRD_COMPLETED.md`.
