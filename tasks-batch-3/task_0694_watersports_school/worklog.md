# Worklog — task_0694_watersports_school

Scenario: Surf / Sailing / Watersports School: course & level (lesson/certification), instructor-to-student ratio & equipment, session scheduling & tide/weather, waiver & swim/age requirement, rental & gear, package/membership & makeup, group/camp, certification card

Difficulty: Expert (passed only to Step 2 scaffold generator)

## Step 1: Create task directory — 2026-06-28T15:32:37.000Z

Created `tasks/task_0694_watersports_school/` and `tasks/task_0694_watersports_school/workspace/` (pre-assigned folder; Step-1 ./tasks scan skipped per invocation instructions). Verified `INSTRUCTION.md` and all prd-bench skills present at project root.

## Step 2: Generate scaffold (Expert) — 2026-06-28T15:53:04.000Z

Generated all three scaffold artifacts for task_0694_watersports_school (Surf/Sailing/Watersports School) at Expert difficulty, written to tasks/task_0694_watersports_school/:

- SCAFFOLD.yaml (§1.0–§1.7) — 1459 lines
- SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8) — 1250 lines
- SCAFFOLD_CORNER_DESIGN.yaml (§1.9) — 1338 lines

Metrics (Expert band targets met):
- Entities: 13 — School, Course, CourseLevel, Instructor, EquipmentItem, Student, Waiver, Membership, Enrollment, Session, SessionBooking, RentalAgreement, CertificationCard (target 10–15).
- Endpoints: 57 (56 business + 1 /_clock test-driving): 30 mutating + 26 GET reads. GET count inflated by flat URL topology (single + filtered-list GET per entity) required by lint FK reverse-reachability check; state-changing surface = 30 POSTs.
- Error codes: 22 (target 18–30).
- Calculation variants: 5 calculations / 5 variants, including mandated dual-variant pair on different entity domains (enrollment_estimate_price forward-looking vs enrollment_final_price chronological), plus tiered marginal rental_fee, session_required_instructors ratio ceiling, enrollment_refund lead-time waterfall.
- State machines: 6, with required non-linear shapes: Session = cyclic (SCHEDULED↔WEATHER_HOLD loop), Enrollment = parallel dimensions (progress_status × payment_status), SessionBooking = branching fork (ATTENDED|NO_SHOW at completion), plus RentalAgreement and Waiver lifecycles. 2 concurrency rules (OCC on Session.version and EquipmentItem.version).

Design coverage: §1.8 has 18 instances (all 9 Difficulty Rules × 2). §1.9 has 35 instances (34 active + 1 excluded_because stub) spanning all nine claim-extraction-guide sections.

Verification: scaffold_lint.py returns VERDICT: clean lint — 464 calls conform to §1.5; all 23 FKs have reverse-reachability GETs. No duplicate instance names; every rule has ≥2 instances; all formula-derived literals computed in Python and verified. Hard constraint respected — no sibling task directories read.

## Step 3: Copy INSTRUCTION.md — 2026-06-28T15:53:04.000Z

Copied project-root `INSTRUCTION.md` to `tasks/task_0694_watersports_school/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-28T15:58:06.000Z

PRD written to workspace/PRD.md — 289 lines.

Sections: §1 Introduction; §2 Global Specs (10 subsections: RBAC, Response Structure, Pagination, Logical Clock, Common Properties & Versioning, OCC, Hierarchical Consistency & Cascades, Reverse-Reachability, Monetary/Rounding, Validation Ordering); §3 Business Logic (9 subsections: catalog, instructors & equipment, students/swim-tests/waivers, memberships & enrolling, enrollment lifecycle (parallel progress/payment), session scheduling & weather loop, booking/check-in/attendance fork, pricing (5 calculations), rentals & certification cards); §4 Endpoint Definitions (59-row table); §5 Error Code Catalogue (22-row table).

Hard Contract reports all PASS: Contract 1 (field-name coverage 63/63 entity fields, 46/46 request bodies, 12/12 query params); Contract 2 (rule coverage — OCC 2/2, state machines incl. Session cyclic + Enrollment parallel dims + SessionBooking fork, 5 calculations reconstructible, 22/22 error IDs in prose, cascades expressed); Contract 3 (§3 path purity — 0 path tokens in 419 backticks). Neither design file was read.

## Step 5: Generate unit tests — 2026-06-28T16:13:08.000Z

Test files: 5 (plus conftest.py), 69 tests total, all collecting cleanly.
Files: test_01_pricing_calculations.py, test_02_state_machines_and_lifecycle.py, test_03_cascades_and_invariants.py, test_04_validations_and_gates.py, test_05_crud_rbac_concurrency.py.

Coverage by queue:
- Queue A (Difficulty): 35 tests across 17 of 18 instances, every covered instance ≥2 tests.
- Queue B (Corner): 34 tests across all 34 non-stub instances (≥1 each).

Skipped — 1 instance (Difficulty/priority_pair_validation_conflict/storm_closed_outranks_waiver_on_checkin): fails unique-derivability. PRD §2.10 declares per-workflow §3 ordering authoritative, and §3.7 lists check-in gates with waiver requirement BEFORE storm-closure — opposite of the design instance's asserted precedence. Faithful PRD-only implementer could return ERR_WAIVER_REQUIRED first, so asserted ERR_SCHOOL_STORM_CLOSED not pinned (error-precedence silence). Documented in test_04 module docstring; no placeholder/xfail.

Stub handling: 1 excluded_because corner stub (stale_session_version_on_booking_returns_412) correctly NOT translated; its difficulty_instance cross-ref resolves to a real instance.

test_helpers/ files written (9): __init__.py, types.py, api_client.py, api_errors.py, assertions.py, factories.py, constants.py, test_users.py, fixtures.py.

Key correctness: CertificationCard lean entity (id + created_at only); ERR_VALIDATION (not template ERR_INVALID_REQUEST); entity-backed identity threading; OCC version threading in fixtures; literal expected values copied from design indices and re-derived against PRD §3.8; every docstring carries verbatim PRD citation + exactly one Design: tag.

## Step 6: Generate implementation — 2026-06-28T16:13:08.000Z

Complete Python + Flask implementation in workspace/implementation/.

Source files: app.py (6 blueprints, error handlers, binds 0.0.0.0:$PORT), start.sh, requirements.txt (flask==3.0.3), db.py (in-memory dicts), clock.py (logical clock default 2026-03-01T00:00:00Z), errors.py (ApiError + 22 error-id/HTTP constants from PRD §5), response.py (envelopes), middleware.py (X-User-ID/X-User-Role role gating), util.py (ISO-8601, validators, pagination limit default 10/min 1/max 100, created_at-ASC sort, touch()), services/calc.py (5 calculations, Decimal/ROUND_HALF_UP), services/derive.py (computed fields + serializers), routes/ (catalog, people, enrollments, sessions, bookings, rentals + certification-cards).

Storage: in-memory only (Python dicts in db.py keyed by id). No SQLite/JSON/tmp. Every start.sh re-import wipes state.

start.sh: set -euo pipefail, cd to script dir, guarded flask install, exec python3 app.py → app.run(host=0.0.0.0, port=$PORT default 10000, threaded=True) foreground.

Endpoints: 57 — exact 1:1 match against PRD §4 table (none missing/extra).
No seeding at startup confirmed: fresh boot returns total_count=0 for all 13 collections.
Self-verified 74 ad-hoc assertions (full pipeline, all 5 calculations w/ boundaries, OCC stale-version, makeup-credit grant, storm gating, prerequisite/age/swim/waiver gates, instructor/student ownership, waiver expiry, validation ordering) — all passed. Note: withdraw-cancelled bookings flagged internally (cancelled_by_withdraw) so refund still sees future sessions.

## Step 7: Test and iterate to PASS — 2026-06-28T16:20:54.000Z

FINAL: 8/8 parallel rounds green, 69/69 tests passing, zero flakiness. Confirmed all 8 results.{1..8}.json show passed==total==69.

Iterations run: 2 (1 diagnostic sweep + 1 verification sweep after fixes).

Root cause: All 6 failing tests shared one setup error — HTTP 422: ERR_WAIVER_REQUIRED - student waiver not SIGNED — a single upstream fixture bug masquerading as 6 independent failures (matches triage hint). Each test registered students via create_student(...) (no waiver) then called create_enrollment(...). Per PRD §3.4 (line 142, verbatim: "The student must have a waiver_status of SIGNED, or the enrollment is rejected with ERR_WAIVER_REQUIRED"), the PRD-faithful implementation correctly rejected the enrollment setup step. None of the 6 tests are about the waiver gate (they cover ratio-ceiling boundaries, session capacity, OCC stale-version, withdraw cascade), so the SIGNED waiver is an incidental enrollment precondition the setup failed to satisfy. STEP 2 test-bug, not impl bug.

Tests deleted: None. (No PRD-silence or unique-derivability failures; enrollment waiver gate is PRD-required, left intact.)

Fixes applied to test_suite/ (test setup): Swapped create_student(...) → create_student_with_waiver(...) for enrolled students in 6 affected setups so the SIGNED-waiver enrollment precondition is met:
- test_03_cascades_and_invariants.py — TestWithdrawCascadeDepth3._three_booked_session (covers test_withdraw_cancels_booking_and_drops_enrolled_count, test_withdraw_recomputes_required_instructors); TestRatioCeilingBoundary.test_third_booking_crosses_ratio_ceiling; TestRatioCeilingBoundary.test_ratio_ceiling_at_exactly_cap.
- test_04_validations_and_gates.py — test_session_full_on_booking_over_capacity.
- test_05_crud_rbac_concurrency.py — test_stale_session_version_on_booking_create.
The create_student_with_waiver helper already existed in test_helpers/fixtures.py and was already imported in all affected modules; no test_helpers/ edits needed.

Fixes applied to test_helpers/: None.
Fixes applied to implementation/: None. The implementation was PRD-faithful throughout (waiver gated on enrollment §3.4 and check-in §3.7, correctly absent from booking-create).

## Step 8: Finalize PRD — 2026-06-28T16:23:17.000Z

Ran (skip condition not met — 6 test_suite/ fixes in Step 7). Result: PRD_FINALIZED.md is byte-identical to PRD.md — 289 vs 289 lines, 0.0% delta, diff clean.

No edits — all Step 7 items are pure fixture bugs already pinned verbatim by PRD §3.4 (waiver gate). Entire Step 7 diff was test-setup swaps (create_student → create_student_with_waiver) to satisfy the §3.4 SIGNED-waiver enrollment precondition; zero impl fixes, zero deletions.

Per-item analysis confirmed no PRD silence/mismatch: waiver gate (ERR_WAIVER_REQUIRED fires only at routes/enrollments.py enrollment-create §3.4 order + routes/bookings.py check-in §3.7, correctly absent from booking-create — both pinned verbatim); ratio ceiling (services/calc.py ceiling w/ 0-special-case, §3.8 pinned); session capacity ERR_SESSION_FULL (services/derive.py seat-status set + strictly-less-than capacity, §3.7 pinned); OCC stale-version (routes/bookings.py expected_session_version → ERR_STALE_VERSION 412, §2.6 pinned); withdraw cascade (routes/enrollments.py BOOKED/CHECKED_IN→CANCELLED, no makeup, decrement enrolled_count + recompute required_instructors, §3.5 pinned). No-new-mismatch grep confirmed waiver gate touches only the two PRD-sanctioned callsites.

## Step 9: Complete PRD — eliminate residual ambiguity/mismatch — 2026-06-28T16:28:00.000Z

Full PRD-vs-implementation/ scan. Source PRD_FINALIZED.md (289 lines, 45,280 chars) → PRD_COMPLETED.md (289 lines, 46,565 chars). Char delta +1,280, 8 in-paragraph edits, no new lines/sections.

Counts: 2 mismatch-revisions, 6 ambiguity-pins.

Changes:
- §3.3 (Waivers) — revise — mismatch — waiver_status is the effective status of the single latest waiver by created_at; revoking the latest yields REVOKED and does NOT fall back to an earlier signed/unexpired waiver (services/derive.py:148-158).
- §3.4 (Enrolling) — insert — ambiguity — membership_id, when supplied, must resolve to a membership belonging to the same student_id or create returns ERR_NOT_FOUND (routes/enrollments.py:66-69).
- §3.6 (Weather loop) — insert — ambiguity — clear-hold against storm-closed school blocked with ERR_SCHOOL_STORM_CLOSED (routes/sessions.py:163-165).
- §3.6 (Start session) — insert — ambiguity — starting with logical clock outside tide window blocked with ERR_INVALID_STATE (routes/sessions.py:189-190).
- §3.7 (Check-in) — insert — ambiguity — session-not-IN_PROGRESS yields ERR_INVALID_STATE; booking-state check precedes session-state check, both precede storm/waiver gates, storm before waiver per §2.10 (routes/bookings.py:136-148).
- §3.8 (Refund waterfall) — revise — mismatch — "remaining bookings" includes the bookings the prerequisite withdrawal already cancelled; tie-break is the session's created_at (routes/enrollments.py:225-242).
- §3.9 (Rental overlap) — insert — ambiguity — new window's own endpoints treated as closed in collision test (collision when new starts_at ≤ existing buffered close AND new ends_at ≥ existing starts_at) (routes/rentals.py:89-94).
- §3.9 (Rental checkout) — insert — ambiguity — checkout with logical clock before starts_at blocked with ERR_INVALID_STATE (routes/rentals.py:174-176).

Pipeline complete. Final deliverables in workspace/: PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, INSTRUCTION.md, implementation/ (+ 8 passing results.{1..8}.json). Tests: test_helpers/ (9 files), test_suite/ (5 files + conftest, 69 tests). FINAL STATUS: 8/8 parallel sweep rounds, 69/69 tests passing.
