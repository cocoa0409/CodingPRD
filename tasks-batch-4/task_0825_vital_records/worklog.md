# Worklog — task_0825_vital_records

## Step 1: Create task directory — 2026-07-11T00:00:00.000Z

Created `tasks/task_0825_vital_records/` and `tasks/task_0825_vital_records/workspace/` (pre-allocated path; task index NOT auto-computed due to 3 parallel sibling pipelines). Scenario: Vital Records Registration (state registrar). Difficulty: Expert.

## Step 2: Generate scaffold (Expert) — 2026-07-11T04:29:00.000Z

All three files complete, parse cleanly, pass scaffold_lint.py; verified safe_load OK on all 3 (correct top-level keys).

Expert band. Primary archetype compliance/audit + secondary workflow orchestration; layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers. Topology flat, state-machine branching, role model segregation_of_duties, consistency immediate.

- Entities (10): Facility, Certifier, VitalEvent, MedicalCertification, Amendment, PaternityAcknowledgment, CertifiedCopyRequest, ApostilleRequest, DelayedRegistrationPacket, StatisticsReport.
- State machines (7): VitalEvent (DRAFT→FILED→REGISTERED→AMENDED→VOIDED with RETURNED cycle), MedicalCertification (PENDING→CERTIFIED→LOCKED→AMENDED), Amendment (SUBMITTED↔REJECTED cycle + APPROVED), PaternityAcknowledgment (ACKNOWLEDGED→{RESCINDED,FINALIZED}), CertifiedCopyRequest (SUBMITTED→ID_VERIFIED→{ISSUED,DENIED}), ApostilleRequest, DelayedRegistrationPacket (SUBMITTED↔RETURNED cycle). Plus 2 concurrency rules (OCC on VitalEvent.version for amendment-approve and copy-issue).
- Calculations (5): registration_delay_fee (threshold, timely/delayed), certified_copy_fee (tiered, certified/informational), copy_eligibility (age threshold), statistics_counts (aggregation), state_remittance (per-transaction round-then-sum).
- Endpoints (47) incl. /_clock/set_current_utc (startup default 2026-03-01T00:00:00Z).
- Error catalog (31): auth/ownership, per-entity NOT_FOUND, request-validation, state, domain business errors (ERR_CERTIFICATION_REQUIRED, ERR_DELAYED_REGISTRATION_REQUIRED, ERR_NOT_ELIGIBLE, ERR_HEARING_SLOT_CONFLICT, ERR_REPORT_PERIOD_OVERLAP, ERR_STALE_EVENT_VERSION).
- Roles (4): StateRegistrar (opaque), FacilityFiler (entity_backed:Facility), MedicalCertifier (entity_backed:Certifier), Applicant (opaque).
- §1.8 depth: 18 instances (9 rules × 2). §1.9 breadth: 31 active + 3 stubs.

## Step 3: Copy INSTRUCTION.md — 2026-07-11T04:30:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-11T04:38:00.000Z

Generated `workspace/PRD.md` (300 lines). 47 endpoints documented (== scaffold's 47), 31 error codes. Sections: §1 Intro, §2 Global Specs (9 subsections incl. RBAC/response/pagination/clock/cascading counters/OCC/xref-ordering/fees-rounding/validation-order), §3 Business Logic (8 entity-lifecycle subsections), §4 endpoint table, §5 error table.

Hard contracts all PASS: field-name coverage 0 missing; both OCC rules + all 5 calculations + validation priority + state transitions/cascades stated; §3 path purity 0 violations; no fuzzy words. Ambiguities resolved: 15-min hearing-slot buffer rendered as ±15min interval extension with touching-endpoint conflict; registered_count/copy conserved counters (inc on register/issue, dec on void); registration precondition order CERTIFICATION(15) before DELAYED(16); FOREIGN fee overage floored at 0; added Facility facility_type/npi coverage. Did NOT open either withheld design file.

## Step 5: Generate unit tests — 2026-07-11T04:53:00.000Z

test_helpers/ (9 modules): types.py, api_client.py, api_errors.py (31-value enum), assertions.py, factories.py, constants.py, test_users.py (opaque + entity_backed builders), fixtures.py (composites setup_registered_birth/death_event, setup_id_verified_copy, event_version), __init__.py.
test_suite/ (7 files, 67 test functions): conftest + test_01..test_07 grouped by domain.
Coverage: Queue A (Difficulty) all 18 instances × 2 tests = 36; Queue B (Corner) all 31 non-stub × 1 = 31. 0 skipped. 3 excluded_because stubs correctly not translated. Verified: 67 collected no import errors; py_compile all 16 files; every docstring ends with verbatim Design: line, all 49 names resolve; every PRD citation grep-verified verbatim. No PRD-first filter rejections needed.
Orchestrator verified: 67 tests collect cleanly from task root.

## Step 6: Generate implementation — 2026-07-11T04:53:00.000Z

workspace/implementation/: start.sh (foreground, reads $PORT default 10000, binds 0.0.0.0, pip-install guarded by flask import check, exec python3 app.py), requirements.txt (Flask==3.0.3), app.py (~47 routes, in-memory dicts only, no seeding).
Endpoints: 47 (orchestrator verified route-count 47 == scaffold 47; ast.parse OK). Full envelope, limit/offset/total_count/has_more pagination, 31-error catalogue w/ validation precedence (auth→authz→ownership→existence→shape→body→state→domain→OCC).
Clock: module holder default 2026-03-01T00:00:00Z, reset each boot, set_current_utc overwrites; ISO-8601 UTC 3-frac-digit serialization. OCC: expected_vital_event_version vs VitalEvent.version (412 ERR_STALE_EVENT_VERSION), checked last; version starts 1, bumps at register/void/amendment-approve/paternity ack+rescind/copy-issue, not file/return. Cascades: register 3-link (Facility.registered_count++ → cert CERTIFIED→LOCKED → Certifier.locked_certification_count++); void compensates; MEDICAL amendment chain B. Fees: Decimal ROUND_HALF_UP — registration_delay_fee (2000 + min(5000,100×overage)), certified_copy_fee (pinned order, VETERAN→0, INDIGENT→half, INFORMATIONAL flat), copy_eligibility age gate, state_remittance per-transaction round-then-sum. state_file_number = {year}-{event_type}-{seq:06d}.

## Step 7: Run tests and iterate — 2026-07-11T05:00:00.000Z

All 8 rounds pass 67/67 (orchestrator re-verified all results.1-8.json). Iterations run: 2 (initial diagnosis + verification after fix). Sweeps split into 2 waves of 4 due to 3 concurrent sibling pipelines.

Tests deleted: None. One assertion split off (partial-coverage), not a full deletion.
test_helpers/ fixes: None.
implementation/ fixes: None.
test_suite/ fix (test_05_apostille_packets_reports.py, test_report_period_adjacent_allowed): removed the line asserting `adjacent["period_start"] == "2026-02-01T00:00:00Z"` — format-silence / non-unique-derivability. PRD specifies "three fractional digits" only for api_request_timestamp/created_at/updated_at, nothing about echo format of user-supplied period_start/period_end in the report response. Impl parse-and-reserializes to .000Z (app.py:118); a faithful reader could echo verbatim OR reserialize — both PRD-consistent. Kept the covered adjacency (201) assertion per STEP 1c.

Final: 67/67 passing across all 8 rounds, no flakiness.

## Step 8: Finalize PRD — 2026-07-11T05:05:00.000Z

Created workspace/PRD_FINALIZED.md (300 → 302 lines, +0.67%). Single scoped edit tracing to the Step 7 test_suite fix (datetime echo format silence).
§2.4 (Common Resource Properties) — insert — pinned that every datetime-valued response field is rendered ISO-8601 UTC with three fractional digits (ms precision), and user-supplied datetimes (event_date, hearing_start/end, period_start/end) are normalized to this canonical form rather than echoed byte-for-byte — app.py fmt_dt (112-118) via serialize() (145-151).
NO-NEW-MISMATCH search: enumerated shared serializer serialize()+fmt_dt applied to all datetime fields (system timestamps + all user-supplied stored datetimes); widened wording from period_start/end-only to a general claim over every datetime field since all share one serializer; deliberately did not pin sub-ms rounding rule to avoid over-constraining beyond the Step 7 site.

## Step 9: Complete PRD — 2026-07-11T05:10:00.000Z

Created workspace/PRD_COMPLETED.md from PRD_FINALIZED.md (302 → 302 lines, +1810 chars, all in-paragraph edits). Full impl-vs-PRD scan. Ambiguity-pins: 5, mismatch-revisions: 2.
- §2.4 version — revise — pinned version starts at 1; file/return refresh updated_at without incrementing version (app.py bump vs touch, 307-310/558/627).
- §2.5 cascading — revise — version increments on every mutated resource incl cascade-touched Facility/Certifier/MedicalCertification, not only OCC-guarded event (606/610/613-614/725/832).
- §2.3 pagination — insert — out-of-range limit/offset clamped (limit→[1,100], neg offset→0), non-integer → defaults (379-401).
- §2.3 sort — insert — created_at ties broken by insertion order (376).
- §2.3 filters — insert — per-endpoint equality filters, total_count post-filter (paginate_and_list 371-409).
- §3.3 packet — insert — hearing_end not strictly after hearing_start → ERR_INVALID_REQUEST 400, before evidence-count check (1162-1165).
- §3.5 paternity — insert — mother_consent false → ERR_INVALID_STATE 409 (910-911).
No mismatches in roles, state transitions, calc formulas, existence-ordering, or envelope.

## Pipeline complete — 2026-07-11T05:10:00.000Z

All 9 steps done. Final: 67/67 tests passing across 8 stability rounds. Artifacts present: SCAFFOLD.yaml + 2 design files, PRD.md/PRD_FINALIZED.md/PRD_COMPLETED.md, test_helpers/ + test_suite/ (67 tests), workspace/implementation/ (Flask, 47 routes) + 8 passing results files.
