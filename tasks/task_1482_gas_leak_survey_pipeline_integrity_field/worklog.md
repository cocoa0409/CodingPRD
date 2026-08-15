# Worklog — task_1482_gas_leak_survey_pipeline_integrity_field

## Step 1: Create Task Directory — 2026-08-13T11:55:00.000Z

Task directory `tasks/task_1482_gas_leak_survey_pipeline_integrity_field/` and `workspace/` created by the previous (terminated) run; treated as DONE per resume instructions.

## Step 2 (partial, prior run): Scaffold generation — 2026-08-13T12:23:00.000Z

Prior run produced `SCAFFOLD.yaml` (2137 lines, §1.1–§1.7, no difficulty/corner keys) and `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1941 lines, 9 rules / 18 non-stub instances) before termination; `SCAFFOLD_CORNER_DESIGN.yaml` was never written.

## Step 2 (resume repair): SCAFFOLD.yaml syntax fix — 2026-08-13T12:45:00.000Z

Orchestrator repaired 26 flow-sequence lines containing unquoted `fieldname?` scalars (invalid YAML) by single-quoting them in place — content-preserving. File now parses cleanly; all required sections present (entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles).

## Step 2 (resume completion): SCAFFOLD_CORNER_DESIGN.yaml — 2026-08-13T13:32:00.000Z

SCAFFOLD_CORNER_DESIGN.yaml generated at `/home/ubuntu/github/CodingPRD/tasks/task_1482_gas_leak_survey_pipeline_integrity_field/SCAFFOLD_CORNER_DESIGN.yaml` (4897 lines), following the claim-extraction-guide taxonomy against this task's SCAFFOLD.yaml only.

**Sections and instance counts (93 total):**

| section | instances | non-stub | stubs |
|---|---|---|---|
| entities | 10 | 10 | 0 |
| state_machines | 34 | 34 | 0 |
| calculations | 7 | 7 | 0 |
| validations | 16 | 16 | 0 |
| endpoints | 7 | 7 | 0 |
| errors | 8 | 2 | 6 |
| rbac | 6 | 6 | 0 |
| cross_cutting | 4 | 4 | 0 |
| consistency_model | 1 | 1 | 0 |

**Total non-stub instances: 87** (plus 6 `excluded_because:` stubs in the errors section, each citing a real §1.8 difficulty instance that already triggers that error: `state_vs_safety_on_survey_run_submit`, `route_dispatch_blocked_by_inactive_segment`, `route_start_outside_scheduled_window_rejected`, `leak_verify_blocked_by_missing_post_repair_survey`, `crew_at_capacity_boundary_exact_max`, `temporal_vs_constraint_on_repair_dispatch`).

**Coverage highlights (breadth beyond §1.8's 18 depth probes):** initial states, terminal lockdown, idempotent re-fires, and invalid-from rejections for every state machine (PipeSegment, SurveyRoute, SurveyRun, Leak, RepairOrder, ExcavationPermit, CathodicProtectionReading, RepairCrew, ComplianceReport, Instrument, RiskModelSnapshot); the remaining untested error codes (ERR_NOT_RUN_OWNER, ERR_COVERAGE_BELOW_MINIMUM, ERR_REGRADE_SAME_GRADE/LIMIT_EXCEEDED, ERR_PERMIT_NOT_APPLIED/NOT_REQUIRED, ERR_ANOMALY_*, ERR_NO_CLEANUP_READING, ERR_SEGMENT_*, ERR_OPEN_REPAIR_ORDERS_EXIST, ERR_NO_RECENT_CLEAN_CP_READING, ERR_INSTRUMENT_IN_USE/OUT_OF_CALIBRATION, ERR_REPORT_* ×5, ERR_OFFICER_OUT_OF_JURISDICTION, ERR_REPORT_PAST_DUE, ERR_SNAPSHOT_STALE, ERR_SEGREGATION_OF_DUTIES, ERR_UNAUTHENTICATED); both OCC concurrency rules not covered by §1.8 (stale leak version via regrade-bump, stale report version via double-bind); calculation corners with pre-computed literals (drift 3.0/5.0/5.1 boundary, CP −850 mV strict-> boundary, posture G3 threshold at exactly 3, crew selector region tie-break 1.0000 vs 0.7000, on-demand resurvey interval 365 days → 2027-08-01T00:00:00Z); envelope shape, pagination, filtered lists, reverse-FK sub-resources; 5 role denials + 1 shared-allow; auto-transitions (snapshot staling, instrument calibration expiry); immediate-consistency read-after-write.

**Validation performed (all passing):**
- YAML parses cleanly; exactly one top-level key `scaffold_corner_design`; every instance carries a unique `name:` (no collisions with the 18 difficulty-design names).
- Mechanical placeholder-closure check: every `${var}` in payloads/paths/as_user_id is bound by an earlier `captures:` in the same instance — zero unbound.
- Every `call:` resolves to a §1.5 endpoint with payload fields ⊆ the endpoint's declared `input:`; every `as:` role is declared in §1.7 (the 6 intentional RBAC-denial calls excepted, which are the test itself).

## Step 3: Copy Shared Files — 2026-08-13T13:35:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T13:50:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1482_gas_leak_survey_pipeline_integrity_field/workspace/PRD.md`.

## Summary

**PRD line count:** 349 lines

**Section list:**
- 1. Introduction (3 paragraphs)
- 2. Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (verbatim fixed block); 2.3 Pagination; 2.4 Common Resource Properties and the Logical Clock; 2.5 Validation Order and Error Selection; 2.6 Instrument Calibration Discipline; 2.7 Optimistic Concurrency Control; 2.8 Pipe Segment Posture; 2.9 Precision, Rounding, and Numeric Conventions; 2.10 Cascade and Compensating-Action Semantics
- 3. Business Logic & Workflows — 3.1 Registering Pipe Segments; 3.2 Instrument Lifecycle; 3.3 Personnel and Repair Crews; 3.4 Planning and Executing Survey Routes; 3.5 Leak Reporting, Grading, and Re-Grading; 3.6 Repair Dispatch and the Excavation Permit Track; 3.7 Post-Repair Verification; 3.8 Integrity Risk Scoring; 3.9 Re-Survey Intervals; 3.10 Cathodic Protection and Anomaly Disposition; 3.11 Risk Model Snapshots and Regulatory Reporting; 3.12 Segment Decommissioning
- 4. Endpoint Definitions (4-column table, 88 endpoints)
- 5. Error Code Catalogue (2-column table, 54 errors)

**Coverage-audit notes (Hard Contracts):**

```
Field coverage check:
- entities[].fields: 94 required, 94 present, 0 missing
- endpoints[].request_body/input (incl. inline query params): 66 required, 66 present, 0 missing
- endpoints[].query_params: 0 separate keys (folded into input lists in this scaffold), covered above
Status: PASS

Rule coverage check:
- validations[] priority ordering: 21 checked, 21 expressed (global order in §2.5; per-endpoint order stated for survey-run submit/accept, regrade, verify-clear, bind-snapshots, dispatch)
- concurrency_rules[] OCC: 3 checked, 3 expressed (schedule-repair + expected_leak_version + ERR_STALE_LEAK_VERSION/412; submit-for-review and bind-snapshots + expected_report_version + ERR_STALE_REPORT_VERSION/412)
- state_machines[].transitions: 47 checked, 47 fully expressed (preconditions + error_ids + side effects, including cascades and compensating unwinds)
- calculations[]: 8 checked, 8 fully expressed in precise prose (leak_grade incl. HCA escalation variant, resurvey_interval incl. forward/on-demand variants, risk_score incl. provisional/final variants, crew_dispatch_selection incl. tie-breaks, posture_derivation, instrument_calibration_due, report_payload_generation incl. nested-rounding rule, overdue_leak_count incl. strict-greater-than boundary)
- validations[] conditions: all matchable to error_ids in §2/§3 prose
- endpoints[].side_effects / applies_to: expressed (instrument check on both run create and submit; snapshot-currency check on both bind and submit-for-review; SoD on both accept and verify-clear)
- entities[].fields[] structured content: reconstructible (defaults, initial states, computed sources stated)
- sibling-branch symmetry: equal density across parallel branches (grant/deny, accept/reject, G1/G2/G3 grading arms, six base-interval arms, AT_CAPACITY⇄AVAILABLE, crew on/off duty)
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 535
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional notes:
- All state/enum values verified present as exact UPPERCASE strings (including `SKIPPED`, `ABORTED`, `FAIL`, which needed explicit enumeration).
- §2.2 emitted byte-verbatim from `section-2.2-response-structure.md` (markers `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `UNIQUE_ERROR_IDENTIFIER_STRING`, `"data": { }` confirmed).
- One scaffold inconsistency surfaced: `ERR_CREW_HAS_OPEN_ORDERS` is referenced by the RepairCrew `AT_CAPACITY → OFF_DUTY` transition precondition but is absent from the `errors[]` catalog, so it has no declared HTTP status. It is named in §3.3 prose (per rule coverage) but intentionally omitted from the §5 table (which is generated strictly from `errors[]`) rather than inventing a status code.
- The two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened, and no sibling tasks were inspected.

## Step 5: Generate Unit Tests — 2026-08-13T15:15:00.000Z

All checks pass. Generation complete.

## Summary

**Output locations**
- `/home/ubuntu/github/CodingPRD/tasks/task_1482_gas_leak_survey_pipeline_integrity_field/test_helpers/` — `types.py` (19 entity TypedDicts + 19 enums), `api_client.py` (67 endpoint methods under the `/integrity-program` prefix), `api_errors.py` (56 `ApiErrorId`s; 55 HTTP statuses from PRD §5 registered via `set_error_http_status_map` — `ERR_CREW_HAS_OPEN_ORDERS` is deliberately unmapped because PRD names the id in §3.3 prose but assigns it no status), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (all five roles are entity-backed, so per-instance `make_<role>_headers` builders plus a bootstrap analyst constant), `fixtures.py` (org bootstrap → instrument → segment → route → run → leak → repair → permit → report composite tiers, including `add_post_repair_survey` for the §3.7 post-repair-survey gate), `__init__.py` barrel.
- `/home/ubuntu/github/CodingPRD/tasks/task_1482_gas_leak_survey_pipeline_integrity_field/test_suite/` — `conftest.py` + 12 test files.

**Counts**
- Queue A (Difficulty): **34 tests** covering **17/18 instances** with ≥2 tests each.
- Queue B (Corner): **87 tests** covering **87/87 non-stub instances** with exactly 1 test each; the 6 `excluded_because:` stubs were not translated and all 6 cross-references resolve to real difficulty instances.
- Total: **121 tests**. Per-file: 01=12, 02=7, 03=15, 04=7, 05=12, 06=16, 07=8, 08=7, 09=5, 10=12, 11=8, 12=12.

**Skipped instances (1)**
- `Difficulty/combinatorial_formula/report_payload_nested_rounding_order` — the nested-rounding order (ratios rounded to 4dp before payload assembly) is PRD-stated in prose but has **no API-observable surface**: the assembled payload lives behind `report_payload_uri` and no endpoint returns the ratios; the instance's own assert concedes "actual numeric check would require populated leak data". Fails unique-derivability of an observable outcome; gap left as a gap.

**PRD-adjudication notes (translated with PRD-correct expectations, not skipped)**
- `Difficulty/priority_pair_validation_conflict/state_vs_safety_on_survey_run_submit` — the yaml's literal assert says `ERR_INVALID_STATE`, but PRD §3.4 names the state error `ERR_RUN_NOT_DRAFT` for a non-DRAFT submit; the test asserts `ERR_RUN_NOT_DRAFT` (priority-4 state still beats priority-5 safety, preserving the instance's claim), plus an isolated `ERR_INSTRUMENT_OUT_OF_CALIBRATION` control.
- `Difficulty/resource_temporal_overlap/excavation_permit_expiry_exclusive_bound` — the yaml asserts dispatch succeeds at exactly `expires_at`; PRD §3.6 requires "`expires_at` later than the current logical clock" (strict), so tests assert success 1s before and `ERR_NO_VALID_EXCAVATION_PERMIT` at and after expiry.
- `Difficulty/dual_variant_calc/leak_grade_hca_vs_non_hca` — the yaml's second pair (bar_hole=4 → G2 on HCA) contradicts PRD §3.5 (escalation only "whenever the inputs land exactly on a threshold boundary"); tests assert G1-threshold inputs (30% LEL → G1 both) and the true boundary differential (bar_hole exactly 5.0 → G2 non-HCA, G1 HCA).
- `risk_score_provisional_vs_final` and `verify_clear_cascades_to_segment_counters` — fixtures insert an ACCEPTED post-repair leak-free survey run before verify-clear, which PRD §3.7 requires (the yaml's chains would otherwise hit `ERR_NO_POST_REPAIR_SURVEY`, as its own sibling instance `leak_verify_blocked_by_missing_post_repair_survey` confirms).

**Verification performed**
- Every test docstring ends with exactly one `Design:` line; all 121 tags resolve to real yaml instances (no untagged, no dual-tagged, no dangling).
- All 164 quoted docstring spans survive whitespace-normalized verbatim match against `PRD.md` (0 failures).
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; all `from test_helpers import …` names resolve; all files parse.

## Step 6: Generate Implementation — 2026-08-13T15:10:00.000Z

Done. Summary:

## Files created (all under `/home/ubuntu/github/CodingPRD/tasks/task_1482_gas_leak_survey_pipeline_integrity_field/workspace/implementation/`)

- `start.sh` — foreground launcher; guards pip install behind `python3 -c "import flask"`, then `exec python3 app.py` (binds `0.0.0.0:$PORT`, default 10000)
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask app factory, envelope error handlers (ApiError/404/405/500), `before_request` time-based sweep, blueprint registration
- `db.py` — in-memory `STORE` dicts (19 collections, keyed by id, empty at boot, zero seeding), logical clock defaulting to `2026-08-01T00:00:00Z`, UUID/`version`/`created_at`/`updated_at` helpers, ISO-8601 3-fractional-digit formatting
- `errors.py`, `response.py`, `middleware.py` — error type, `meta`/`response_type`/`data` envelope + pagination (`limit`/`offset`/`total_count`/`has_more`, default 10/0, min 1, max 100), `X-User-ID`/`X-User-Role` auth + RBAC decorator + body validators
- `services.py` — all calculations: leak grading with HCA boundary escalation, repair clocks (1/30/365d), risk score (0.20/0.15/0.30/0.20 weights, ×1.5 HCA, half-up 2dp, cap 100), posture derivation, re-survey intervals (base × 0.25/0.5 × 0.5 CP factor, floor), coverage prefix model, crew dispatch score (0.7/0.3, 4dp half-up), snapshot generation (sha256 input_set_hash, ≥70 high-risk), report payload ratios (4dp half-up at ratio level), and the instrument-calibration / permit-expiry sweep (with the DISPATCHED/ON_SITE compensating unwind)
- `routes/` — 12 modules: segments, instruments, people (5 personnel types), crews, survey_routes, survey_runs, leaks, orders (repair orders + excavation permits), cp_readings, snapshots, reports, clock

## Endpoint count
**87 endpoints**, all mounted under `/integrity-program`, matching the PRD §4 table exactly (10 PipeSegment, 6 Instrument, 12 personnel, 6 RepairCrew, 9 SurveyRoute, 6 SurveyRun, 8 Leak, 7 RepairOrder, 4 ExcavationPermit, 5 CPReading, 3 RiskModelSnapshot, 10 ComplianceReport, 1 clock).

## Key semantics implemented
- Full state machines with PRD-ordered checks (e.g. submit: ownership 403 → `ERR_RUN_NOT_DRAFT` 409 → `ERR_INSTRUMENT_OUT_OF_CALIBRATION` 422; dispatch: state → `ERR_CREW_OFF_DUTY` → `ERR_CREW_AT_CAPACITY` → qualification → permit; regrade: `ERR_LEAK_NOT_OPEN` → `ERR_REGRADE_LIMIT_EXCEEDED` → `ERR_REGRADE_SAME_GRADE`)
- OCC: `expected_leak_version` on schedule-repair, `expected_report_version` on bind-snapshots/submit-for-review (412s), checked after state/business rules
- Cascades with per-entity `version`/`updated_at` bumps: out-of-service abandons leaks + cancels pending orders; permit expiry unwinds dispatch; run rejection abandons OPEN leaks; snapshot auto-staling on new leak / verify-clear / CP anomaly / posture shift / regrade; report pin/unpin of snapshots

## Boot verification
`bash start.sh` was smoke-tested on scratch port 18149 across three fresh boots (each confirmed the store wipes clean and the clock resets to 2026-08-01). Three end-to-end suites passed: full survey-route → run → accept → complete lifecycle; leak grading (incl. HCA boundary escalation), regrade limits, OCC 412s, crew selector + capacity, permit apply/grant/expiry unwind; CP anomaly ack/resolve with cleanup-reading rule; compliance report bind → pin → submit → reject → resubmit → reopen cycle; and auth/403/404/400 ordering. Server shut down cleanly afterward.

## Step 7: Run Tests and Iterate — 2026-08-13T15:35:00.000Z

All 8 rounds pass 121/121. Clean exit achieved.

## Summary

- **Iterations run**: 2 (initial sweep: 119/121 in all 8 rounds; post-fix sweep: 121/121 × 8 rounds, zero failures).

- **Tests deleted**: none. Both failing tests were PRD-faithful and uniquely derivable:
  - `test_leak_grade_hca_escalates_only_on_boundary` — PRD §3.5 verbatim-covers HCA boundary escalation; the failure was a setup precondition violation (PRD §3.3 unique `employee_code`), not a bad assertion.
  - `test_temporal_permit_check_beats_capacity_constraint` — PRD §2.5 verbatim fixes the validation priority: "then business-temporal checks (scheduled windows, filing deadlines, permit validity), then business-constraint checks (crew capacity, crew qualification, ...)".

- **Fixes applied to `test_helpers/`**:
  - `fixtures.py`, `make_org()` — personnel employee codes were hardcoded (`IA-1`/`FT-1`/`CT-1`/`DC-1`/`CO-1`), so any test building two orgs in one server boot tripped PRD §3.3's unique-`employee_code` rule during setup (manifested as "Setup step failed with HTTP 400: employee_code must be unique"). Codes are now suffixed with a per-call uuid tag (`IA-<8hex>`, etc.); no test asserts on specific employee-code values.

- **Fixes applied to `test_suite/`**: none.

- **Fixes applied to `implementation/`**:
  - `workspace/implementation/routes/orders.py`, `_check_crew()` — reordered dispatch validation so the excavation-permit validity check (business-temporal per PRD §2.5) is evaluated before crew capacity and excavation-qualification checks (business-constraint). Previously an expired-permit + at-capacity dispatch returned `ERR_CREW_AT_CAPACITY`; it now correctly returns `ERR_NO_VALID_EXCAVATION_PERMIT`. OFF_DUTY remains first (uncategorized by §2.5, listed first in §3.6), and the selector path (`_check_permit` before `_select_crew`) was already compliant.

## Step 8: Finalize PRD — 2026-08-13T15:50:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1482_gas_leak_survey_pipeline_integrity_field/workspace/PRD_FINALIZED.md` is written with exactly two inline patches, both tracing to `<step_7_diff>` items.

**Line counts / %-delta**
- PRD.md: 348 lines / 52,194 chars → PRD_FINALIZED.md: 348 lines / 52,371 chars (+0.34% chars; 2 lines revised in place, no lines added/removed, no new sections).

**Changes**
- §3.3 — insert — added "For every personnel record type, `employee_code` must be unique among records of that same type; a duplicate is rejected with `ERR_INVALID_REQUEST`." (PRD previously said "unique" only for FieldTechnician) — `workspace/implementation/routes/people.py:17-19` (`_check_unique_employee`), callsites at lines 52, 85, 110; error mapping `workspace/implementation/errors.py:16-17`.
- §3.6 — revise — reordered the dispatch-check list so the excavation-permit validity check (`ERR_NO_VALID_EXCAVATION_PERMIT`, business-temporal) precedes crew-capacity (`ERR_CREW_AT_CAPACITY`) and excavation-qualification (`ERR_CREW_NOT_QUALIFIED_EXCAVATION`) checks (business-constraint), keeping OFF_DUTY first and adding the house-style pointer "in the order given by §2.5" — `workspace/implementation/routes/orders.py:62-75` (`_check_crew`), 105-117 (`dispatch_order`, both explicit and selector paths).

**Pre-edit search log**
- Edit 1 (§3.6): (a) subject = dispatch validation check ordering. (b) Enumerated/read: `orders.py::dispatch_order` (both `crew_id` sub-paths), `_check_crew`, `_check_permit`, `_select_crew`, `services.py::has_valid_permit` (304-309); repo-wide grep for all five dispatch error ids + `has_valid_permit` confirmed orders.py is the only raise site; also read `test_suite/test_06_repair_dispatch.py:224` and its sibling capacity test to confirm pinned behavior. (c) Kept the OFF_DUTY clause first (only the explicit-crew path can raise `ERR_CREW_OFF_DUTY`; the selector path eligibility-filters OFF_DUTY crews into `ERR_NO_ELIGIBLE_CREW`, and there the permit check also runs before crew selection, so the reordered list describes both paths); retained "for the two excavation methods" qualifier on the permit clause (impl skips it for non-excavation methods).
- Edit 2 (§3.3): (a) subject = `employee_code` uniqueness on personnel creation. (b) Enumerated/read: `people.py::_check_unique_employee` plus all five create endpoints (FT 40-58, CO 74-90, `_create_simple` 106-114 covering CT/DC/IA); `errors.py::bad_request`; §4 endpoint table confirming no personnel update endpoints exist (creation is the sole enforcement point); repo-wide `employee_code` grep (remaining hits are serializer field lists only). (c) Scoped wording to "unique among records of that same type" because the impl check is per-collection — cross-type duplicate codes are accepted, so any "globally unique" phrasing would have been a new mismatch; named `ERR_INVALID_REQUEST` since all five create paths raise it.

No other Step 7 items required patching: no tests were deleted, no test_suite changes were made, and the two originally failing tests were both consequences of the two fixes above (fixture precondition violation and the impl-side ordering bug, respectively).

## Step 9: Complete PRD — 2026-08-13T16:25:00.000Z

All edits are in place. Final verification of counts: PRD_FINALIZED.md = 348 lines / 52,535 chars; PRD_COMPLETED.md = 351 lines / 59,439 chars (+3 lines, +6,904 chars).

## Summary

**Source vs output:** `PRD_FINALIZED.md` (348 lines, 52,535 chars) → `PRD_COMPLETED.md` (351 lines, 59,439 chars); char-delta +6,904. 17 edit operations, all inline inserts/revisions; no new sections.

**Counts:** ambiguity-pins: 26 · mismatch-revisions: 4

**Ambiguity pins (insert):**
- §2.1 — insert — ambiguity — pinned that authentication checks only header presence + role membership; personnel-record existence is resolved only where business rules dereference it (route start, report filing) — implementation/middleware.py:22-33
- §2.2 — insert — ambiguity — unknown path → `ERR_NOT_FOUND` (404); unsupported method → `ERR_INVALID_REQUEST` body with HTTP 405 — implementation/app.py:24-40
- §2.3 — insert — ambiguity — offset ≥ 0, non-integer limit/offset → 400, `created_at` ties broken by creation order, boolean filter params accept `true/1/false/0` case-insensitive — implementation/middleware.py:38-65, services.py:111-113
- §2.4 — insert — ambiguity — clock accepts any instant (no monotonicity), responds 200 `{"current_utc": ...}`, automatic transitions swept on clock-set and before each request — implementation/routes/clock.py:9-16, app.py:16-18
- §2.5 — insert — ambiguity — parse-time `ERR_INVALID_REQUEST` placement (after authn/authz + path-id resolution, before body-id resolution/state/business); uniqueness checks fire at creation point after state checks — implementation/routes/leaks.py:30-47, orders.py:195-209
- §2.6 — insert — ambiguity — `reference_gas_ppm` must be > 0 (else 400); calibrating a `RETIRED` instrument → `ERR_INVALID_STATE`; `drift_pct` stored unrounded — implementation/routes/instruments.py:81-93
- §2.9 — insert — ambiguity — fractional `concentration_ppm` rounded half-up to integer at recording — implementation/routes/leaks.py:44-47
- §3.1 — insert — ambiguity — `risk_score` computed at segment creation per §3.8 — implementation/routes/segments.py:61
- §3.1 — insert — ambiguity — on-demand next-survey-due anchors at `last_surveyed_at` if set, else current logical clock — implementation/routes/segments.py:149-152
- §3.2 — insert — ambiguity — failed calibrations persist no record (all persisted Calibrations have outcome `PASS`); calibrate responds 201 with the Calibration record — implementation/routes/instruments.py:86-102
- §3.2 — insert — ambiguity — retire requires `IN_SERVICE` (else `ERR_INVALID_STATE`), checked before the in-use rule — implementation/routes/instruments.py:109-115
- §3.3 — insert — ambiguity — `qualified_methods`/`jurisdiction_scope` entries validated against method/regulator sets; new personnel start `ACTIVE`; personnel lists accept a `status` filter — implementation/routes/people.py:46-50, 80-84, 26-32, 56/88/112
- §3.3 — insert — ambiguity — `max_concurrent_orders` ≥ 0; set-off-duty on already-`OFF_DUTY` crew → `ERR_INVALID_STATE`; set-on-duty requires `OFF_DUTY` — implementation/routes/crews.py:25-26, 73-74, 91-92
- §3.4 — insert — ambiguity — window endpoints not cross-validated at creation; add-assignment on non-`PLANNED` route → `ERR_ROUTE_NOT_PLANNED`; `sequence_index` ≥ 1; no uniqueness of sequence/segment across assignments — implementation/routes/survey_routes.py:27-40, 78-92
- §3.4 — insert — ambiguity — route start resolves the `FieldTechnician` record after the `DISPATCHED` check (`ERR_NOT_FOUND` if absent) — implementation/routes/survey_routes.py:123-125
- §3.4 — insert — ambiguity — run creation checks no route status; `distance_covered_feet` ≥ 0; run ends at submission (`ended_at` stamped at submit) — implementation/routes/survey_runs.py:21-42, 82-83
- §3.4 — insert — ambiguity — route completion has no technician-ownership check — implementation/routes/survey_runs.py (absence), routes/survey_routes.py:139-167
- §3.5 — insert — ambiguity — leak reporting applies no status check to segment or survey run, only existence — implementation/routes/leaks.py:42-43
- §3.5 — insert — ambiguity — pinned exact HCA boundary set (LEL=25, LEL=5, ppm=10000, dist=50, dist=20 with migration) — implementation/services.py:216-225
- §3.6 — insert — ambiguity — schedule-repair responds 201 with the RepairOrder; initial `excavation_permit_status` = `PERMIT_REQUIRED` for excavation methods else `NOT_REQUIRED` — implementation/routes/leaks.py:161-174
- §3.6 — insert — ambiguity — permit-expiry unwind also clears `crew_id`/`dispatched_at` to null — implementation/services.py:400-402
- §3.6 — insert — ambiguity — with `crew_id` omitted on excavation methods, permit check precedes crew selection (`ERR_NO_VALID_EXCAVATION_PERMIT` before `ERR_NO_ELIGIBLE_CREW`) — implementation/routes/orders.py:114-117
- §3.7 — insert — ambiguity — defined qualifying post-repair run (ACCEPTED, no leak references it, COVERED assignment for segment, created at/after latest completed order's `completed_at`) and that `verified_by_officer_id` lands on the most recently completed order — implementation/routes/leaks.py:189-219
- §3.10 — insert — ambiguity — readings recordable on segments in any status; "newer" cleanup reading = strictly later `recorded_at`, ties by creation order — implementation/routes/cp_readings.py:28, 90-94
- §3.11 — insert — ambiguity — snapshot generation writes recomputed scores back to segments that differ; `high_risk_segment_ids` in `created_at` order; `input_set_hash` = SHA-256 over sorted ids of ACTIVE segments + their leaks/CP readings — implementation/services.py:312-334
- §3.11 — insert — ambiguity — payload aggregated at creation and re-aggregated at submit-to-regulator; verified-cleared window keyed on verify-clear timestamp; anomalies opened/resolved definitions; `report_payload_uri` format `/integrity-program/compliance-reports/{id}/payload`; binding does not validate snapshot kind against section; missing officer record treated as out of jurisdiction — implementation/routes/reports.py:29-40, 128-137

**Mismatch revisions (revise):**
- §2.4 — revise — mismatch — PRD said the clock "advances"; impl sets any instant forward or backward — implementation/routes/clock.py:11-14
- §3.4 — revise — mismatch — PRD's coverage definition ("sum over assignments marked COVERED") was circular; revised to impl's prefix model (assignments in `sequence_index` order covered while cumulative length fits `distance_covered_feet`; stops at first non-fitting; all assignments participate regardless of status; `coverage_pct` computed at creation, recomputed at acceptance) — implementation/services.py:258-284, routes/survey_runs.py:39-40, 97-106
- §3.6 — revise — mismatch — PRD §2.5's general ordering puts body-id resolution before state checks, but dispatch resolves an explicit `crew_id` only after the `PENDING_DISPATCH` check; pinned as a stated exception — implementation/routes/orders.py:105-113
- §5 — revise — mismatch — added missing catalogue row `ERR_CREW_HAS_OPEN_ORDERS | 422` (error was referenced in §3.3 prose and used by impl but absent from the catalogue) — implementation/routes/crews.py:79-81

No other discrepancies found: all 80+ endpoints in the §4 table exist in impl with matching roles; all state machines, formulas (risk §3.8, intervals §3.9, grading §3.5, dispatch score), OCC guards, cascade semantics, and error statuses match the implementation.

## Pipeline Complete — 2026-08-13T16:30:00.000Z

All Steps 1–9 done. Final state: 121 tests, 8/8 rounds passing 121/121 under `--isolation per-test-server`; PRD chain PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md complete.
