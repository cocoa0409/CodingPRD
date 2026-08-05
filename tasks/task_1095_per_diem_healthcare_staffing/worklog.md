# Worklog — task_1095_per_diem_healthcare_staffing

## Step 1: Create Task Directory — 2026-07-24T03:00:00.000Z

Pre-assigned folder used as-is (Step 1 directory scan skipped per orchestrator instruction).
Created `tasks/task_1095_per_diem_healthcare_staffing/workspace/`.
Difficulty parameter for Step 2 scaffold-generator: **Expert**.

## Step 2: Generate Scaffold — 2026-07-24T04:00:00.000Z

Files written (all `yaml.safe_load` OK):
- SCAFFOLD.yaml — 2613 lines
- SCAFFOLD_DIFFICULTY_DESIGN.yaml — 1980 lines
- SCAFFOLD_CORNER_DESIGN.yaml — 3571 lines

Surface counts:
- Entities: 11 (Facility, Clinician, Credential, RateCard, StaffingOrder, Shift, ShiftClaim, Assignment, Timesheet, ReliabilityEvent, Invoice)
- State machines: 10 (Assignment carries two parallel axes: work_status × pay_status)
- Concurrency rules: 2 (OCC on Shift.version at award; OCC on Facility.version at invoice generation)
- Calculations: 11
- Validations: 34 (strictly priority-ordered)
- Endpoints: 44 (includes `/_clock/set_current_utc` test clock; default clock 2026-05-01T00:00:00Z)
- Errors: 54
- Roles: 6 (SoD: PlatformAdmin, ComplianceOfficer, FacilityScheduler, FacilityVerifier, Clinician, BillingAgent)

Design instances:
- §1.8: 9 rule blocks × 2 = 18 instances
- §1.9: 7 sections, 63 instances (50 full test_recipe, 13 excluded_because stubs)

Verification: scaffold_lint clean; 45 global_constants declared, 0 undeclared references; no forbidden concurrency vocabulary; all formula literals pre-computed in Python.
Note: endpoint count 44 sits above Expert 20–32 band, driven by mandatory FK reverse-reachability GETs (15 FKs).

## Step 3: Copy INSTRUCTION.md — 2026-07-24T04:05:00.000Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md → workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-07-24T04:15:00.000Z

Output: workspace/PRD.md — 306 lines. Confirmed the two design YAMLs were NOT read.
Contracts pass: Field-Name Coverage 105/105; §3 Path Purity 0 violations; 55 error IDs + 6 roles present.
Covers §1 intro, §2 nine cross-cutting subsections (RBAC 6 roles, envelope, pagination limit 10/1/100 offset 0 created_at asc, logical clock default 2026-05-01T00:00:00Z, both OCC rules ERR_STALE_SHIFT_VERSION/ERR_STALE_FACILITY_VERSION 412, round-half-up, validation precedence, money invariants), §3 all 10 state machines + cascades + 10 calcs, §4 endpoint table, §5 55-code error catalogue. All named constants embedded in prose.

## Step 5: Generate Unit Tests — 2026-07-24T04:40:00.000Z

test_helpers/ (9 files): __init__, types, api_client, api_errors, assertions, constants, factories, test_users, fixtures. api_errors registers 57 error→HTTP mappings; test_users has per-instance entity_backed header builders; fixtures build deep states (CLOSED order, issued invoice).
test_suite/ (10 files): conftest + test_01..test_09.
Total 86 tests, all collect. Queue A 18/18 × 2 = 36; Queue B 50/50 × 1 = 50. 0 instances skipped by PRD-first filter; 13 corner excluded_because stubs correctly not translated.
FLAGGED deviation: Difficulty/compensating_invariant/award_then_cancel_restores_order_slot_partition — design literal cancellation_lead_hours==168.00 is an internal arithmetic slip; PRD-unique value is 175.00 (clock 2026-06-01, shift start 2026-06-08T07:00Z). Test asserts 175.00.

## Step 6: Generate Implementation — 2026-07-24T04:40:00.000Z

workspace/implementation/: start.sh (foreground, reads $PORT default 10000, binds 0.0.0.0, exec python3 app.py), requirements.txt (flask 3.0.3), store.py (in-memory DB, logical clock default 2026-05-01T00:00:00Z, constants, ISO render 3-digit+Z, round-half-up), envelope.py (57-code error catalog, envelopes, pagination, auth), logic.py (calcs + gates + reliability cascade), app.py (44 routes + validation ordering).
ast.parse OK all 4 sources. 44 routes = 44 scaffold endpoints. IDs str(uuid4()). In-memory only, no seeding.
Flagged interpretation decisions: version-bump counting per declared transition (timesheet-submit double-bumps assignment); order version bumps on counter change; invoice gate order per §2.7 precedence; credential compliance expiry-leg lazily materialized; no-show/confirm timing preconditions not hard-rejected (no error defined).


## Step 7: Run Tests and Iterate — 2026-07-24T11:35:00.000Z

Pre-sweep partial-write guard PASSED: py_compile clean; 44 routes == 44 scaffold endpoints; boots and serves (auth-gated clock, ERR_VALIDATION on bad payload). Routes are under the `/staffing/` path prefix.

Sweep discipline: 8-round stability sweep run as 4 WAVES OF 2 concurrent rounds (host shared with 4 sibling Step-7 sweeps on 8 cores) via `sweep.sh` (script file, not inline pkill). Per-round wall ~81s.

Baseline sweep: 80/86. 6 failures across 2 classes; 1 fix batch → clean.

Class A — 4× `NameError: name 'api' is not defined` (TEST bug). Module-level setup helpers referenced the bare `api` fixture, which is only injectable into test functions, not module-level helpers. The file's own established pattern (e.g. test_05 `_setup_revoked_claimant` line 284) uses `fx.api_client.<method>`. Fixed:
  - test_05_award_assignment.py `_setup_award_then_prepare_cancel`: `api.get_order` → `fx.api_client.get_order` (2 sites, lines ~397/401). Fixes test_award_then_cancel_restores_slot_partition + test_award_then_cancel_waives_pay_and_records_no_reliability_event.
  - test_07_reliability.py `_setup_single_no_show`: `api.no_show_assignment` → `fx.api_client.no_show_assignment`. Fixes test_pending_no_show_diverges_provisional_from_adjudicated + test_pending_no_show_cascade_side_effects.
  Systematic scan of all test files confirmed no other module-level helper references bare `api.`.

Class B — 2× timestamp format `.000Z` vs `Z` (TEST over-pin; split assertion). PRD §2 (line 78) scopes the "exactly three fractional digits" render rule to SERVER-STAMPED fields via an explicit enumeration (created_at, updated_at, claimed_at, awarded_at, confirmed_at, verified_at, occurred_at, adjudicated_at, issued_at, due_at). The two failing fields are CLIENT-SUPPLIED inputs NOT in that list:
  - test_02_credentials.py `test_credential_expires_then_renews_back_to_verified`: `expires_on` (supplied in the verify/renew payload). Impl stores/echoes it verbatim (app.py:264/307/318, no render_dt), while server-stamped `verified_at` correctly renders `.000Z`. Assertion relaxed `2027-07-01T00:00:00.000Z` → `2027-07-01T00:00:00Z` (the supplied value, verbatim). Value/instant still pinned; only the PRD-unpinned format corrected.
  - test_06_timesheets_pay.py `test_resubmit_from_submitted_returns_not_resubmittable`: `clock_out` (client punch, factory default `2026-06-08T19:00:00Z`). Assertion relaxed `.000Z` → `Z`.
  Impl verified internally consistent: client-supplied timestamps echoed verbatim, server-stamped timestamps rendered `.000Z` — exactly PRD §2 as written. No impl change (normalizing client input to `.000Z` would add behavior not traced to a verbatim PRD sentence). Scan confirmed no other `.000Z` assertions on client-supplied fields.

Result: 1 iteration beyond baseline. Final 4-waves-of-2 sweep — all 8 rounds passed==total==86, independently re-parsed; 0 skipped/xfail/errors; grep confirms no skip/xfail markers in source.

Summary:
- Iterations run: 1 (baseline 80/86 → fixed → clean 8-round sweep).
- Tests deleted: 0.
- test_helpers/ fixes: 0.
- test_suite/ fixes: 4 (2 NameError helper-scope fixes: test_05, test_07 → fx.api_client; 2 client-supplied timestamp format splits: test_02 expires_on, test_06 clock_out).
- implementation/ fixes: 0.

## Step 8: Finalize PRD — SKIPPED — 2026-07-24T11:36:00.000Z

Skipped: Step 7 made 0 implementation/ fixes (per orchestrator rule "run Step 8 only if Step 7 made implementation fixes"). Step 8's method aligns PRD to implementation choices at implementation-fix sites via <step_7_diff>; with no impl changes there is nothing to align. The lone PRD silence Step 7 surfaced (client-supplied timestamp render format for expires_on/clock_out) is a full-scan concern and is deferred to Step 9. No PRD_FINALIZED.md produced.

## Step 9: Complete PRD — 2026-07-24T11:40:00.000Z

Full PRD-vs-implementation/ scan (subagent, synchronous). Started from PRD.md (Step 8 skipped → no PRD_FINALIZED.md). Output: workspace/PRD_COMPLETED.md.

PRD.md 306 lines / 61952 chars → PRD_COMPLETED.md 306 lines / 63007 chars (+1055 chars). ambiguity-pins: 3; mismatch-revisions: 0.

Changes:
- §2.4 Timestamps — insert — ambiguity — pinned that CLIENT-SUPPLIED timestamp inputs (issued_on, expires_on, scheduled_start/end, window_start/end, effective_from/to, clock_in/out, period_start/end) are stored and echoed back verbatim (exact string form supplied), NOT renormalized to three fractional digits; the §2 3-digit rule remains scoped to server-stamped fields. Verified against app.py raw-string stores + envelope.py _render_value (only datetime objects hit render_dt). This closes the Step-7 Class-B silence (expires_on/clock_out).
- §2.3 Pagination — insert — ambiguity — pinned clamp semantics: limit→[1,100], non-int limit→10, negative/non-int offset→0 (clamped, not rejected) (envelope.py:194-214).
- §3.5 Confirmation — revise — ambiguity — broadened confirm state gate from "already terminal" to "anything other than PENDING_CONFIRMATION → ERR_ASSIGNMENT_NOT_CANCELLABLE", and pinned that this state gate precedes the clinician-active gate (app.py:805-809). Consistent with passing test_confirm_blocked_by_suspended_clinician (PENDING+suspended → ERR_CLINICIAN_SUSPENDED).

No mismatches found; §2.7 precedence chain already matches impl.

## Pipeline COMPLETE — 2026-07-24T11:40:00.000Z

Done-state satisfied: all 8 results.{1..8}.json passed==total==86 (independently re-parsed; 0 skipped/xfail/errors); worklog reached Step 9; workspace/PRD_COMPLETED.md exists.
