# Worklog — task_2564_student_records_transfer_education_records_requests

## Step 1: Create task directory — 2026-09-03T11:54:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2564_student_records_transfer_education_records_requests` and its `workspace/` subdirectory. Index 2564 was pre-assigned by the orchestrating prompt; no scan of `./tasks/` was performed (other pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-03T13:38:00.000Z

All three scaffold artifacts for task 2564 are complete and the linter is clean.

**Files**
- `SCAFFOLD.yaml` — 3350 lines (§1.0–§1.7 only; no `scaffold_difficulty_design` / `scaffold_corner_design` keys; top-level keys are scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1836 lines (single top-level key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4034 lines (single top-level key `scaffold_corner_design`)

**§1.8 depth probe:** 9 difficulty rules, 20 non-stub instances, 0 stubs.

**§1.9 breadth probe:** all 9 guide sections, 75 instances of which 57 non-stub and 18 `excluded_because` stubs:
entities 12+0, state_machines 12+3, calculations 5+7, validations 9+5, endpoints 6+0, errors 7+0, rbac 3+0, cross_cutting_layers 2+3, consistency_model 1+0. All 95 instance names unique across both design files; every stub cites an existing §1.8 instance by `rule_id / name` and carries no `test_recipe`.

**Lint verdict (verbatim, final run):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
Coverage
  §1.5 endpoints declared:    65
  §1.1 entities declared:     16
  §1.8 instances scanned:     20
  §1.9 instances scanned:     57
  Calls scanned (§1.8+§1.9):  972

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Fixes applied in the final pass**
- Wrote the last two §1.9 sections: `cross_cutting_layers` (full `optimistic_concurrency` instance driving ERR_STALE_CUMULATIVE_FILE_VERSION on `mark-ready`, including the "the token that just succeeded is now stale" case; full `derived_field_reconciliation` instance walking `District.open_request_count` 0→3→1 while requesting districts stay 0; plus three layer stubs) and `consistency_model` (one `immediate` instance asserting derived values are present in the causing write's own body).
- The first lint run reported 8 × `(f) FK_REVERSE_UNREACHABLE`: the linter's sub-resource form requires the parent placeholder to be literally `{id}`, while §1.5 used named placeholders (`{student_id}`, `{cumulative_file_id}`, …). Normalized all first-position path placeholders to `{id}` across SCAFFOLD.yaml (173 substitutions; deeper placeholders such as `{component_id}` and the natural key `{state_code}` left intact). Design-file calls use concrete `${var}` values, so nothing else needed changing.
- Normalized all 18 stub citations to the `rule_id / instance_name` form used by SKILL.md's example and verified each name exists in the difficulty file.

Error-code coverage is complete: every id in §1.6 is triggered by at least one §1.8 or §1.9 instance, with ERR_STALE_CUMULATIVE_FILE_VERSION landing in `cross_cutting_layers` and ERR_UNAUTHORIZED in `rbac`.

Orchestrator verification: all three files parse as YAML; top-level keys confirmed correct.

## Step 3: Copy shared files — 2026-09-03T13:39:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_2564_student_records_transfer_education_records_requests/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T13:56:00.000Z

The PRD is complete and verified.

**File:** `workspace/PRD.md` — **412 lines / 98178 bytes**

**Section list (top-level headings):**
- `# Student Records Transfer API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Rights-Holders, Operators, and Role-Based Access Control; 2.2 API Response Structure (verbatim from the skill's fixed block); 2.3 Pagination; 2.4 Collection Filters; 2.5 The Logical Clock and Statutory Time Arithmetic; 2.6 Common Resource Properties; 2.7 Statutory Reference Data; 2.8 Nested Path Resolution and Reference Integrity; 2.9 Validation Precedence; 2.10 Optimistic Concurrency Control; 2.11 Conservation Invariants; 2.12 Precision and Rounding
- `## 3. Business Logic & Workflows` — 3.1 Enrollment, the Records Skeleton, and Directory-Information Rights; 3.2 Withdrawal Clearance and the Exit Cascade; 3.3 Building the Cumulative File; 3.4 Discipline History and Cross-State Inclusion; 3.5 Inter-District Request Intake and the Statutory Response Window; 3.6 Packet Snapshot, Reopening, Release, and Denial; 3.7 Inspection Requests, Copy Fees, and Review Appointments; 3.8 Amendment Challenges, Hearings, and Statements of Disagreement; 3.9 Legal Demands, Retention Schedules, and Certified Destruction
- `## 4. Endpoint Definitions`
- `## 5. Error Code Catalogue`

**Endpoint coverage:** 65 documented vs 65 in scaffold. Every scaffold `(method, path)` pair matches a table row byte-for-byte (verified programmatically; zero mismatches).

**Error coverage:** 77 rows vs 77 scaffold errors — no missing, no extra, and every HTTP status matches the scaffold's `http` field exactly.

**Three Hard Contracts:**
- **Contract 1 — Field-Name Coverage: PASS.** All 159 distinct identifiers (146 entity field names ∪ 96 endpoint input/path-param names) appear verbatim inside backticks in the PRD. Verified with a script that strips the two fenced JSON blocks before extracting inline-code tokens; the missing set is empty. Scaffold-internal constant names (`PER_PAGE_CENTS`, `OFFICER_DAILY_MINUTE_CAP`, `CERT_TIER_*`, `SUMMARY_PAGE_COUNT`, etc.) are deliberately rendered as prose values (seven and a half cents per page, 240 minutes, 2000/10000-cent tier floors with 500/1500-cent fees, three-page summary, 500-page threshold, 15-minute buffer, age 18, 45-day inspection window, 5-day expedited cap, 10-day special-education extension) rather than as symbolic tokens, per the no-pseudocode rule.
- **Contract 2 — Rule Coverage: PASS.** All 8 calculations including the 3 with variants (standard vs expedited window, responding-state vs requesting-state discipline inclusion, last-activity vs exit-anchored retention), all 46 priority-ordered validations with their precedence bands, all 10 state machines including the 3 cyclic (component certify/restore, packet reopen, hearing reschedule), 2 branching (legal-demand production, amendment decision), and the compound amendment machine, both OCC rules, all cross-entity cascades (component → file → records request → packet void; disclosure/certification → retention → `records_disposition_date`), field-level defaults, and both sibling-branch symmetries are stated in prose. No fuzzy quantifiers occur anywhere in the file.
- **Contract 3 — §3 Path Purity: PASS.** Zero backtick tokens in §3 begin with `/`, are a bare HTTP method, or combine method and path.

**Terminal boundary:** the file ends at a genuine section boundary — the final row of the §5 error table.

Deliberate ambiguity resolutions flagged by the generator: (1) the scaffold names no error for "`responding_district_id` must equal `Student.district_id`", so the PRD states that requirement descriptively without nominating a code; (2) `ERR_COMPONENT_ALREADY_CERTIFIED` was assigned to a `CERTIFIED` target on an already-certified component while a `COLLECTED` target on a `CERTIFIED` component carries `ERR_COMPONENT_NOT_EXCLUDED`, reconciling validation priority 52 with the catalogue; (3) a decision call from a status outside {`SUBMITTED`, `HEARING_SCHEDULED`} maps to `ERR_AMENDMENT_NOT_SUBMITTED`, reserving `ERR_HEARING_NOT_SCHEDULED` for the scheduling endpoint; (4) the phantom enum `retention_anchor_mode` — named only inside validation priority 31 and never an entity field or endpoint input — was omitted. The two withheld design files were never opened, and no sibling task directory was read.

**Orchestrator truncation check:** PASS — tail ends on a complete error-catalogue table row (`| ``ERR_NOTIFICATION_REQUIRED`` | 422 |`), all five `##` sections present in order. No regeneration needed.

## Step 6: Generate implementation — 2026-09-03T14:33:00.000Z

Implementation complete.

## Files (`workspace/implementation/`)

| lines | file | role |
|---|---|---|
| 423 | `common.py` | logical clock, interval arithmetic (calendar/business/whole-year), `Decimal` ROUND_HALF_UP helpers, `ApiError`, in-memory `Store` (16 dicts), auth headers, body validators, pagination |
| 214 | `domain.py` | enum tuples, statutory constants, `get_*` 404 lookups, relationship helpers |
| 177 | `calc.py` | the 8 named calculations (request window, discipline inclusion set, packet page count, completeness, copy/certification fees, retention anchors) |
| 217 | `derive.py` | derived-state reconciliation: file counters/assembly status, packet void + reopen cascade, VALIDATED→ASSEMBLING bubble, district counter, retention recompute, disclosure-log append |
| 188 | `serialize.py` | explicit per-entity field lists (16 entities) |
| 60 | `response.py` | `meta`/`response_type`/`data` envelope, offset pagination, error body |
| 35 | `authz.py` | Parent/EligibleStudent rights-transfer guard |
| 304 | `routes_config.py` | clock, compliance sweep, state rules, districts, rooms, hearing officers (16 endpoints) |
| 275 | `routes_students.py` | enrollment + file/component minting, directory opt-out & disclosures, disclosure log, discipline incidents (9) |
| 167 | `routes_withdrawals.py` | withdrawal, holds/releases, completion + retention schedule minting (6) |
| 133 | `routes_files.py` | cumulative file, components, component PATCH (5) |
| 272 | `routes_requests.py` | records-request intake, validate, mark-ready snapshot, release, deny (7) |
| 252 | `routes_inspections.py` | inspection requests, fee transactions, appointments, attendance (8) |
| 296 | `routes_amendments.py` | challenges, decisions, hearing request/schedule, statement of disagreement (7) |
| 206 | `routes_legal.py` | legal demands, notification, production, retention schedule, certified destruction (7) |
| 85 | `app.py` | blueprint registration, `ApiError`/400/404/405/415/500 handlers |
| 16 | `start.sh` | guarded `pip install flask`, `exec python3 app.py` on `0.0.0.0:$PORT` (default 10000) |
| 1 | `requirements.txt` | flask |

3321 lines total.

## Endpoint coverage: 65 / 65

Diffed the live Flask URL map against the 65 method+path pairs in `SCAFFOLD.yaml` programmatically: **zero missing, zero extra**.

## Smoke test: pass

`bash start.sh` with `PORT=21566` booted clean; `GET /records-office/students` on a fresh process returned an empty list (store empty at boot, no seeding); killed by PID, exited cleanly on SIGTERM and released the port. `bash start.sh` execs into `python3 app.py` in-place (single process, same PID), so the harness's per-test kill/relaunch has nothing to orphan. Storage is process-memory dicts only; `PYTHONDONTWRITEBYTECODE=1` and no file writes anywhere.

Beyond booting, major flows exercised end to end, all PRD-conformant:
- Certify 3 required components → file `COMPLETE`, `completeness_pct` 100.0; validate bubbles VALIDATED→ASSEMBLING; mark-ready snapshot; release → `INTERDISTRICT_TRANSFER` disclosure with the packet page count.
- Summary-substitution packet math: 600 raw pages → `packet_page_count` 403 (600 − 200 discipline + 3).
- Amendment GRANT decertified the component and cascaded the READY_FOR_RELEASE request back to `ASSEMBLING` / `packet_status: VOID` / counters nulled / `reopen_count` 1.
- Hearing path: DENY → `hearing_due_at`, hearing request, schedule, `ERR_HEARING_NOT_HELD` before the end instant, `ERR_SEGREGATION_OF_DUTIES` for the original decider, UPHELD, then statement of disagreement adding one page.
- Withdrawal holds (`ERR_WITHDRAWAL_NOT_CLEARED`), completion minting the retention schedule, `records_disposition_date` mirror, sweep promotion to `DESTRUCTION_ELIGIBLE`, certified destruction zeroing page counts.
- Inspection fees: two 40-page components → 650¢ base (per-component double rounding), 0¢ certification (below the 2000¢ tier floor), `ERR_FEE_OUTSTANDING` before payment, then attendance → `COMPLETED` + `PARENT_INSPECTION` entry.
- Legal demand: `ERR_NOTIFICATION_REQUIRED`, notify → `production_allowed_at`, `ERR_NOTIFICATION_WAIT_NOT_ELAPSED`, then production + `LEGAL_DEMAND` entry.
- Envelope/error checks: `ERR_UNAUTHORIZED` (403) with no role header, `ERR_STUDENT_NOT_FOUND`, `ERR_METHOD_NOT_ALLOWED`, `ERR_VALIDATION` on `limit=0`, `has_more`/`total_count` pagination.

Two PRD-vs-scaffold conflicts resolved in favour of the PRD, with a hedge where the PRD is silent: SPED consent at mark-ready fires when `sped_requires_consent and (Student.has_iep or request.includes_special_education)`, and a statement of disagreement against any non-`UPHELD` status returns `ERR_STATEMENT_ALREADY_FILED`. Two process notes: `responding_district_id == Student.district_id` is not enforced (no error code exists for it), and `attendance` with `attended: false` returns the unchanged appointment with no state change.

## Step 5: Generate unit tests — 2026-09-03T15:41:00.000Z

Generation complete. Both output directories are final, syntax-clean, pyflakes-clean, import-clean, and every citation survives a literal grep of `PRD.md`.

## Files

Infrastructure — `test_helpers/`
| file | lines |
|---|---|
| `__init__.py` | 52 |
| `api_client.py` | 341 |
| `api_errors.py` | 167 |
| `assertions.py` | 334 |
| `constants.py` | 102 |
| `factories.py` | 253 |
| `fixtures.py` | 785 |
| `test_users.py` | 79 |
| `types.py` | 526 |
| **total** | **2639** |

Tests — `test_suite/`
| file | lines | tests |
|---|---|---|
| `conftest.py` | 19 | – |
| `test_01_statutory_windows_and_fees.py` | 324 | 7 |
| `test_02_discipline_and_retention_variants.py` | 247 | 4 |
| `test_03_request_and_amendment_cycles.py` | 328 | 6 |
| `test_04_exit_and_production_cascades.py` | 272 | 4 |
| `test_05_validation_precedence_conflicts.py` | 292 | 6 |
| `test_06_boundary_precision.py` | 390 | 6 |
| `test_07_cross_entity_state_dependency.py` | 322 | 4 |
| `test_08_resource_temporal_overlap.py` | 306 | 4 |
| `test_09_conservation_invariants.py` | 223 | 4 |
| `test_10_entity_lifecycles.py` | 666 | 13 |
| `test_11_state_machine_paths.py` | 964 | 17 |
| `test_12_calculations.py` | 418 | 8 |
| `test_13_validation_rules.py` | 1142 | 22 |
| `test_14_endpoint_behaviors.py` | 787 | 13 |
| `test_15_error_catalogue.py` | 900 | 16 |
| `test_16_role_permissions.py` | 533 | 7 |
| `test_17_concurrency_and_consistency.py` | 399 | 7 |
| **total** | **8532** | **148** |

## Coverage

- **Queue A (§1.8 Difficulty): 45 tests / 20 instances — 20 of 20 covered, every instance with ≥2 tests.**
- **Queue B (§1.9 Corner): 103 tests / 57 non-stub instances — 57 of 57 covered.** Per section: entities 12→13, state_machines 12→17, calculations 5→8, validations 9→22, endpoints 6→13, errors 7→16, rbac 3→7, cross_cutting_layers 2→5, consistency_model 1→2. The 18 `excluded_because:` stubs were not translated.
- Verification pass confirms: 148 `Design:` tags, one per test, zero tags pointing at a non-existent or stubbed instance, zero untagged/dual-tagged tests, and 148 verbatim one-line PRD citations ("checked 148 citations, 0 bad").

## Instances SKIPPED

**None.** Every non-stub instance in both indices passed the PRD-first two-condition filter.

Five recipe defects were corrected in the PRD's favour rather than skipped, since each instance's core claim remained PRD-derivable:
1. `errors`/`endpoints` legal-demand recipes assert `ERR_WAIVER_BASIS_REQUIRED` at 422; the PRD error table lists it at **400** and §3.11 calls the waiver pairing a payload condition — 400 asserted.
2. `endpoints` recipes pass `production_scope` as prose (`"Transcript"`, `"Everything"`); the PRD requires a non-empty array subset of ACADEMIC/HEALTH/DISCIPLINE/SPECIAL_EDUCATION — arrays used.
3. `errors/duplicate_state_rule_and_duplicate_district_code_codes` expects `district_code: "send01"` to be accepted (201, `total_count == 2`); the PRD requires 2–12 **uppercase** alphanumerics, so that case-sensitivity sub-claim was dropped and `total_count == 1` asserted instead.
4. Hearing-officer credential `RETIRED_ADMINISTRATOR` (in `errors` and `rbac` recipes) is not in the PRD enum — `DISTRICT_DESIGNEE` used.
5. `endpoints` ex-parte recipe includes a "still blocked once merely NOTIFIED" step that is unreachable, because notifying a waived demand is itself refused (`ERR_NOTIFICATION_WAIVED`) — that step dropped; the rest of the gate is asserted.

Two recipe claims were checked against the PRD and confirmed correct (not defects): excluding the *optional* SPECIAL_EDUCATION component leaves the file `COMPLETE` and does not reopen the request (§3.3/§3.6 scope the bubble to required components), and completing a withdrawal before its `effective_date` is legal (no clock-versus-effective-date precondition exists).

The suite was never run against an implementation, per instruction.

Orchestrator verification: `python3 -m compileall` clean over test_helpers/, test_suite/, and workspace/implementation/.

## Step 7: Run tests and iterate — 2026-09-03T16:02:00.000Z

Clean 8-round parallel sweep: all 8 rounds `148 passed / 0 failed / 0 errors` out of 148 (verified in `workspace/implementation/results.1.json` … `results.8.json`, ~259s each).

## Summary

**Iterations run:** 2

Iteration 1 was deterministic — the identical 3 tests failed in all 8 rounds, so no flakiness signal existed. Iteration 2 was clean.

**Tests deleted:** none. All three failures survived STEP 1 (PRD verbatim-covers and uniquely determines the outcome); the diagnosis landed on one test-artifact bug and one implementation bug.

**Fixes applied to `test_suite/`:**
- `test_suite/test_11_state_machine_paths.py` — `TestSnapshotRequiresTheAssemblingStatus::test_mark_ready_straight_out_of_received_is_refused_on_status` asserted `refused["last_packet_snapshot_at"] is None` on the **records request** row (`KeyError`). PRD puts `last_packet_snapshot_at` on the **cumulative file** only (§3.1 "`last_packet_snapshot_at` begins null" in the file's counter list; §3.6 "The cumulative file's `last_packet_snapshot_at` is set to…"), and the records-request creation field list in §3.5 does not include it. Per STEP 1c the assertion was re-pointed at the file (`get_file(file_id)["last_packet_snapshot_at"] is None`) rather than dropped — strictly more PRD-faithful, and it avoids adding a non-PRD field to the request response.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `setup_amendment_upheld` passed `outcome="UPHOLD"`, which is not in the PRD's `GRANT`/`DENY` decision enum (§3.8); changed to `"DENY"` (the post-hearing denial that moves `HEARING_SCHEDULED → UPHELD`). Latent only — no test currently calls this helper — but it was a fixture inconsistent with PRD.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes_inspections.py`, `_room_conflict` (and its one call site in `create_appointment`) — the function skipped any still-`SCHEDULED` appointment belonging to the *same* inspection request, on the theory that it was about to be superseded. PRD §3.7 states the padded-closed test runs over "**every existing** `SCHEDULED` or `ATTENDED` appointment in the same room", and the release is described as a consequence of an *accepted* booking ("Any appointment of that same request already in `SCHEDULED` moves `SCHEDULED → SUPERSEDED` and releases its room interval"), i.e. after the test. The release-before-test carve-out is granted only to hearings (§3.8: "the previously reserved interval is released before the new interval is tested"), which the PRD explicitly flags as "deliberately different from the padded, closed room rule of §3.7". Removing the carve-out fixed both `test_05` room-collision tests and left the legitimate-reschedule test (`test_11 TestRebookingSupersedesTheStandingAppointment`, which rebooks onto a different day) passing.

No test was weakened, skipped, or downgraded from an `error_id` to an HTTP-status assertion; no endpoint, field, or seeded data was added to the implementation.

Orchestrator verification: read all 8 results files directly — each `passed=148, failed=0, errors=0, total=148`; `workspace/sweep.log` contains no `Terminated` line, so no reaping occurred.

## Step 8: Finalize PRD — 2026-09-03T16:09:00.000Z

Done. `PRD_FINALIZED.md` created with a two-sentence patch, both tracing to the single `implementation/` fix in `<step_7_diff>`.

## Line counts
- `PRD.md`: 412 lines — `PRD_FINALIZED.md`: 412 lines — **0.0% line delta** (2 lines revised in place, 0 added/removed).

## Changes
- **§3.7 (room occupancy test)** — *revise* — the padded-closed occupancy sweep now states explicitly that a still-`SCHEDULED` appointment of the very inspection request being rebooked participates in the test, because its interval is released only after the booking is accepted — `routes_inspections.py:121-135` (`_room_conflict`, no self/same-request exclusion) and `:168` (test) vs `:176-179` (supersession, after the test).
- **§3.7 (supersession sentence)** — *revise* — "no longer participates in overlap detection" → "no longer participates in the overlap detection of **any later booking**", removing the reading that the release precedes the current booking's own conflict test — `routes_inspections.py:168` vs `:176-179` (ordering).

## Per-edit pre-edit search log

**Edit 1 — subject: which appointments occupy a room interval, and when an interval is released.**
(b) Paths enumerated and read: `routes_inspections.py:121-135` `_room_conflict` (iterates *all* `STORE.review_appointments`, filters only on `room_id` and `status in (SCHEDULED, ATTENDED)` — no request-scoped exclusion, no `exclude_id` parameter at all); its sole callsite `routes_inspections.py:168` (fires before the statutory-window 422, after the 412/409 status and `ERR_ROOM_CLOSED` gates); `routes_inspections.py:176-179` (supersession loop, strictly after the conflict test); `routes_inspections.py:216-254` `record_attendance` (`SCHEDULED → ATTENDED`, so an attended interval stays occupied); `routes_config.py:62-65` (sweep `SCHEDULED → EXPIRED` on `end_at < now`, dropping the interval out of the status filter); `routes_config.py` room PATCH / `ERR_ROOM_CLOSED` at `routes_inspections.py:165` (closure gates new bookings only, never mutates existing appointments); grep for `review_appointments` across all 15 impl modules confirmed `_room_conflict` and the sweep are the only occupancy readers. Contrast path checked for consistency: `routes_amendments.py:195-205` `_officer_conflict` and `:208-217` `_officer_daily_minutes`, which *do* take `exclude_id=row["id"]` — so §3.8's release-before-test carve-out and its "deliberately different from §3.7" contrast remain literally true and needed no edit.
(c) Adjustment: scoped the inserted clause to "any still-`SCHEDULED` appointment of this very inspection request" rather than a general "including the request's own appointments". An `ATTENDED` appointment of the same request is unreachable here (attendance drives the request to `COMPLETED`, refused at `routes_inspections.py:158`), so naming `ATTENDED` would have asserted a path the impl cannot exhibit; the narrower clause also leaves the pre-existing `SCHEDULED`/`ATTENDED` status list as the sole authority on which statuses occupy, so `SUPERSEDED` and `EXPIRED` intervals stay excluded.

**Edit 2 — subject: the ordering of interval release relative to the conflict test.**
(b) Paths enumerated: the same `routes_inspections.py:168` (test) vs `:176-179` (release) ordering; `routes_inspections.py:193-194` (request → `SCHEDULED`, version bump) to confirm the release is part of the accept path and never runs on a rejected call; `routes_config.py:62-65` (the sweep's `EXPIRED` release, the only other way an interval leaves occupancy) to confirm "any later booking" covers it; `routes_amendments.py:243`/`:247` (`exclude_id` passed) to confirm the hearing rule in §3.8 is genuinely the opposite order and its wording must stay untouched.
(c) Adjustment: chose "of any later booking" over deleting the trailing clause. Deletion would have dropped the still-true fact that `SUPERSEDED` intervals stop occupying the room — which `_room_conflict`'s status filter does exhibit, and which a subsequent booking into the vacated slot relies on.

Items 1 and 2 of `<step_7_diff>` produced **no** PRD edits: `serialize.py:58-65` puts `last_packet_snapshot_at` on the cumulative file only and `serialize.py:88-101` omits it from the records request, so §3.1/§3.6 already match the impl (the test was the artifact bug); and `routes_amendments.py:125` validates `outcome` against `AMENDMENT_OUTCOMES` = `GRANT`/`DENY`, so §3.8's enum already matches (the fixture's `"UPHOLD"` was a pure fixture bug in an uncalled helper).

## Step 9: Complete PRD — 2026-09-03T16:29:00.000Z

Pass C is complete and the file verifies clean.

## Verification

| | PRD_FINALIZED.md | PRD_COMPLETED.md |
|---|---|---|
| lines | 412 | 412 |
| bytes | 98,356 | 109,289 |

- `diff … | wc -l` = **196** (49 hunks, 50 lines revised, 0 lines added/removed, 0 new sections)
- char-delta **+10,933**
- `tail -5` ends on `| ERR_NOTIFICATION_REQUIRED | 422 |` — the final error-catalogue row. Not truncated.

**Counts: 35 ambiguity-pins, 22 mismatch-revisions (57 changes).**

## Changes

Pass A — cross-cutting
- §2.1 — revise — ambiguity — `ERR_UNAUTHORIZED` also fires when `X-User-ID` is absent or empty, not only on a bad role — common.py:257
- §2.3 — insert — ambiguity — unparseable/out-of-range `limit`/`offset` are `ERR_VALIDATION` 400; empty string = absent → default — common.py:383,393
- §2.3 — insert — ambiguity — `created_at` ties broken by server insertion sequence — common.py:422
- §2.4 — insert — ambiguity — empty filter applies none, unknown params ignored, boolean filters accept `true/false/1/0` else `ERR_VALIDATION` — common.py:403,410
- §2.6 — insert — ambiguity — reconciliation to an unchanged value is not a mutation; sole exception: every accepted component update bumps the file `version` — derive.py:31,101,154; routes_files.py:132
- §2.9 — insert — ambiguity — payload band: explicit null in an optional field takes the default, bool-where-int is rejected, enum arrays normalised + deduped — common.py:299,308,356
- §3.1 — insert — ambiguity — `exit_effective_date` is a calendar date; `records_disposition_date` a full millisecond instant — derive.py:154
- §3.1 — insert — ambiguity — every disclosure entry carries `recipient_name` + `legitimate_interest_note`, with per-family fill rules — serialize.py; routes_requests.py:238; routes_legal.py:150,154; routes_inspections.py:248

Pass B — config, students, withdrawals, files
- §2.7 — revise — mismatch — `discipline_min_days_removed` bounded 0–365; `include_pending_investigations` and `sped_requires_consent` are **required** booleans — routes_config.py:91-97
- §2.7 — insert — ambiguity — `state_code` enum-checked first, rule resolved as a natural key after name/code sanity — routes_config.py:156-157
- §2.7 — revise — mismatch — rooms accept no `buffer_minutes` at all (system constant), `status` defaults ACTIVE, `seats` never enforced; PATCH requires `status` — routes_config.py:195,238
- §2.7 — insert — ambiguity — officer `status` defaults ACTIVE, `full_name` not unique, PATCH requires `status` — routes_config.py:255,292
- §2.8 — insert — ambiguity — `district_id` added to the body-reference list; presence/string shape precedes the 404 — routes_requests.py:25-29
- §3.1 — insert — ambiguity — directory release answers **201** with the entry as `data`; field requirements pinned — routes_students.py
- §3.2 — insert — ambiguity — `effective_date` stored as supplied, never bounded against the clock — routes_withdrawals.py
- §3.2 — revise — mismatch — retention schedule is minted whether or not the file's status actually moved — routes_withdrawals.py; derive.py:90
- §3.3 — insert — ambiguity — target `status` required, PENDING unreachable, payload band precedes state — routes_files.py
- §3.3 — insert — ambiguity — `redacted_page_count` bounded 0–5000 and ≤ `page_count`; re-collection without it resets to 0; neither supplied leaves both — routes_files.py
- §3.3 — insert — ambiguity — certification requires ≥1 page, checked *after* the two status checks — routes_files.py
- §3.3 — insert — ambiguity — `EXCLUDED` against PENDING/EXCLUDED → `ERR_COMPONENT_NOT_COLLECTED` — routes_files.py
- §3.3 — insert — mismatch — an amendment grant against a non-`CERTIFIED` component leaves status alone — routes_amendments.py:99-108
- §3.4 — revise — mismatch — an incident attaches to DISCIPLINE as prose only: no pages written, nothing re-derived; `description` required non-empty — routes_students.py
- §3.4 — insert — ambiguity — `incident_date` unbounded against the clock — routes_students.py

Pass C — requests, inspections, amendments, legal
- §3.5 — revise — mismatch — `responding_district_id` is never validated against the student's district; disposed by denial `STUDENT_NOT_IN_DISTRICT` — routes_requests.py:50
- §3.5 — insert — ambiguity — `authorization_verified` required boolean, settled before the status checks — routes_requests.py:130
- §3.5 — insert — ambiguity — `is_overdue` is one-way, never cleared, untouched once true — routes_config.py:51-55
- §3.6 — revise — mismatch — sped consent = rule requires it **and** (`has_iep` **or** `includes_special_education`) — routes_requests.py:175-177
- §3.6 — insert — ambiguity — no separate all-required-certified guard; `COMPLETE` already implies it — routes_requests.py:169
- §3.6 — revise — mismatch — `packet_status` is SNAPSHOT by construction; no packet-status guard is evaluated — routes_requests.py:206-209
- §3.6 — revise — mismatch — release `disclosed_categories` are the file's `CERTIFIED` types read at release time, not the snapshot's — routes_requests.py:232
- §3.6 — insert — ambiguity — denial from `READY_FOR_RELEASE` → `ERR_REQUEST_NOT_ASSEMBLING` — routes_requests.py:265-266
- §3.7 — insert — ambiguity — no student precondition; unlimited concurrent inspection requests — routes_inspections.py:32-45
- §3.7 — insert — ambiguity — `REVERSAL` uncapped (may drive collected negative); no status precondition on fee transactions — routes_inspections.py:101-113
- §3.7 — insert — ambiguity — `attended` required boolean, status check first, **no no-show state**: false is a no-op leaving it `SCHEDULED` — routes_inspections.py:221-228
- §3.7 — insert — ambiguity — inspection disclosure copies `requested_categories`, `page_count` 0 — routes_inspections.py:243-253
- §3.8 — insert — ambiguity — `decision_note` among the null-initialised fields — routes_amendments.py
- §3.8 — insert — ambiguity — `decision_note` stored only when supplied; omission preserves an earlier note — routes_amendments.py
- §3.8 — revise — mismatch — grant against a non-`CERTIFIED` component keeps its status and only bumps `amendment_count` — routes_amendments.py:99-108
- §3.8 — insert — ambiguity — `AMENDED`/`STATEMENT_FILED` report `ERR_AMENDMENT_TERMINAL` on hearing request — routes_amendments.py:180-183
- §3.8 — insert — ambiguity — same terminal guard on hearing scheduling — routes_amendments.py:235-238
- §3.8 — insert — ambiguity — officer daily cap keyed on `hearing_start_at`'s UTC date; midnight-spanning windows count wholly to their start date; only `HEARING_SCHEDULED` windows summed — routes_amendments.py:208-217
- §3.8 — insert — ambiguity — statement's +1 page enters `included_`/`excluded_page_count` by the component's then-current status — routes_amendments.py:286-295
- §3.9 — insert — ambiguity — `LAW_ENFORCEMENT_DIRECTIVE` pairs with any demand type; out-of-enum `waiver_basis` is `ERR_VALIDATION` ahead of every pairing rule — routes_legal.py:39-52
- §3.9 — insert — ambiguity — `produced_page_count` required int ≥ 0, never reconciled against the file's pages — routes_legal.py:125
- §3.9 — insert — ambiguity — destruction also zeroes `disclosable_page_count`, leaves component **statuses** untouched (so `assembly_status`/`completeness_pct` survive), and freezes a `DESTROYED` schedule against later recomputation — routes_legal.py:198-205; derive.py:182-186

§4 endpoint table (all mismatch-revisions)
- state-rules POST — adds the discipline-inclusion knobs; 45-day inspection window is a constant, not a rule field — routes_config.py:84-101
- districts POST — `state_code` enum; no fee schedule on the district record — routes_config.py:149-167
- rooms POST — optional initial `status`; no `buffer_minutes` field exists — routes_config.py:195
- rooms PATCH — `status` required, `buffer_minutes` not updatable — routes_config.py:238
- hearing-officers PATCH — `status` required, `credential` optional — routes_config.py:292
- students POST — optional user identifiers; rights-transfer flag derived from DOB, never supplied — routes_students.py
- directory-optout — grace window measured from student creation; no withdrawal of an opt-out — routes_students.py
- discipline-incidents POST — real field list; immutable once recorded — routes_students.py
- records-requests POST/GET — actual field list (`request_priority`, `includes_special_education`, `sped_consent_on_file`, `authorization_reference`), not "transfer basis / requested scope"; GET also filters requesting district and `is_overdue` — routes_requests.py:42-112
- mark-ready — freezes the packet page count and the three incident counts, not "fee figures" (a records request has none) — routes_requests.py:181-187
- appointments POST — seat capacity is **not** enforced; supersedes the request's standing appointment — routes_inspections.py:165-179
- attendance POST — no no-show; `attended` false leaves the appointment in `SCHEDULED` — routes_inspections.py:223-228

Two deliberate non-changes: `ERR_NOT_FOUND` / `ERR_METHOD_NOT_ALLOWED` / `ERR_INTERNAL` (app.py:48-75) were not added to the §5 catalogue — they are framework-level handlers, and adding them would inflate scope; and `api_request_timestamp` needed no pin since §2.5 already binds every server-minted timestamp to the logical clock.

Orchestrator verification: `PRD_COMPLETED.md` is 412 lines / 109,289 bytes, is NOT byte-identical to `PRD_FINALIZED.md` (196 diff lines, +10,933 chars — the scan genuinely ran), retains all five `##` sections, and ends on the final error-catalogue row. No `.py` file under `workspace/implementation/`, `test_suite/`, or `test_helpers/` was modified after the clean 16:02 sweep, so the 8×148/148 result still describes the artifacts on disk.

## Pipeline complete — 2026-09-03T16:30:00.000Z

All nine steps finished. Final state: 65/65 endpoints, 148 tests, 8/8 rounds green at 148/148, PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md all present and untruncated.
