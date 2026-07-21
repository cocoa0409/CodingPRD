# Worklog — task_1041_student_travel_ef

## Step 1: Create task directory — 2026-07-16T11:23:00.000Z

Created `./tasks/task_1041_student_travel_ef/` and `workspace/` subdir (pre-assigned folder; no ID scan). Scenario: Educational & Student-Travel Operator (EF style). Difficulty: Expert (passed only to Step 2 scaffold-generator).

## Step 2: Generate scaffold — 2026-07-16T11:59:30.000Z

Expert flat-topology EF student-travel scaffold generated and lint-clean. All three files (SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml) yaml.safe_load cleanly; scaffold_lint.py → clean lint (321 calls scanned across 40 design instances, all conform to §1.5; all 10 FKs have reverse-reachability GETs); no forbidden race vocabulary; endpoint roles ⊆ RBAC.

Metrics:
- Entities: 11 — Tour, GroupLeader, Departure, Enrollment, PaymentPlan, Payment (append-only, common_fields:false), PermissionForm, Chaperone, RoomingAssignment, Supplier, SupplierBooking. Flat topology (all top-level collections, api_prefix: ""), peer-role model.
- State machines: 6 — Departure (branching + terminal cancel-cascade), Enrollment (parallel axes: lifecycle_status × payment_status), PaymentPlan (branching), PermissionForm (cyclic CHANGES_REQUESTED→SUBMITTED revision loop), RoomingAssignment, SupplierBooking. Plus 1 concurrency rule (OCC on Enrollment.version for plan-create-with-supersede).
- Endpoints: 46 — includes 2 computed reads (GET /departures/{id}/summary, GET /enrollments/{id}/refund-quote), 10 FK reverse-reachability GETs, and a /_clock/set_current_utc test-driving endpoint (startup default 2026-07-01T00:00:00Z).
- Errors: 27.
- Difficulty design: 18 instances (2 per rule × 9 rules); Corner design: 22 active instances + 5 excluded_because stubs.

Undeclared constants: none outstanding. All pinned — EARLY_BIRD_PCT=0.10, ADDON_PRICES, INSURANCE_PREMIUMS, DEPOSIT_CENTS=30000, refund tiers (90/60/30-day → 1.00/0.75/0.50/0.00), CHAPERONE_RATIO default 6, room capacities DOUBLE/TRIPLE/QUAD=2/3/4, CHAPERONE_REST_BUFFER_DAYS=1.

Downstream note: two dual-variant calculations (refund_amount on Enrollment money vs free_spot_credit on Departure seats) surface only through the two computed-read endpoints; neither provisional value is persisted.

## Step 3: Copy INSTRUCTION.md — 2026-07-16T11:59:40.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md (bash, no subagent).

## Step 4: Generate PRD — 2026-07-16T12:08:00.000Z

PRD.md generated (273 lines) for student-travel-ef domain, without reading either withheld design file or any sibling task. Documented: 11 entities, 46 endpoints (every scaffold endpoint covered, verified bidirectionally: 0 missing, 0 extra), 27 error codes (§5 catalogue), 3 roles, 5 calculations, 15 validations, 6 state machines, 1 OCC rule. All three hard contracts (field-name coverage 79/79, rule coverage, §3 path purity) PASS. Constants embedded in prose (0.10, 40000/12000/8000, 9900/19900, 30000, refund tiers, 1-day buffer, ratio 6). Verified: PRD endpoint count == scaffold endpoint count (46).

## Step 5: Generate unit tests — 2026-07-16T12:28:00.000Z

56 tests across 12 test_suite files + 9 test_helpers files. Coverage: Queue A (difficulty) 34 tests across 17/18 instances (≥2 each); Queue B (corner) 22 tests covering all 22 non-stub instances (1 each). 6 excluded_because stubs not translated.

Skipped (1 difficulty instance): priority_pair_validation_conflict / rooming_member_safety_gender_beats_room_full_constraint — asserts ERR_ROOMING_GENDER_MISMATCH pre-empts ERR_ROOM_FULL, but PRD §3.8 orders checks the opposite way (ERR_ROOM_FULL first), so precedence not uniquely derivable. Not weakened/xfailed — gap left as gap. Consequence: ERR_ROOMING_GENDER_MISMATCH ends up with no dedicated isolated test (corner stub delegated to the skipped instance).

Watch-item for Step 7: enrollment_confirm_requires_departure_open_or_guaranteed (kept) requires enrolling a traveler on a still-DRAFT departure; tests rely on DRAFT available_seats = capacity (seat identity invariant). If reference impl initializes DRAFT available_seats to 0, those two tests error at setup.

## Step 6: Generate implementation — 2026-07-16T12:28:10.000Z

Student Travel EF API in 4 Python/Flask modules (app.py, calc.py, store.py, errors.py) + start.sh + requirements.txt, in workspace/implementation/. 48 route decorators = 46 API routes (matching 46 PRD endpoints) + 2 unauthenticated /health and / readiness helpers. In-memory store (empty on boot), logical clock default 2026-07-01T00:00:00Z. app.py parses (ast.parse OK). Subagent self-verified live: envelope, RBAC/ownership, early-bird pricing, installment split, OCC ERR_STALE_VERSION, paid-in-full→free-spot→leader-credit cascade, guarantee chaperone-ceiling gate, refund tiers, departure-cancel full-refund cascade, rebook, depart transitions, supplier half-open overlap, chaperone rest-buffer, rooming, ERR_ENROLLMENT_CLOSED/ERR_VALIDATION.

## Step 7: Test-and-fix loop — 2026-07-16T12:40:00.000Z

task_1041_student_travel_ef passes a clean 8-round (2-wave) sweep at 54/54; deleted 2 non-derivable confirm-on-DRAFT tests, no implementation or helper changes required.

- Iterations run (number of sweeps): 2 full 8-round sweeps. Sweep 1 = 54/56 (2 failures, identical across all 8 rounds); Sweep 2 (after deletion) = 54/54 clean across all 8 rounds.

- Tests deleted:
  - test_confirm_on_draft_departure_rejected and test_enrollment_stays_pending_after_rejected_confirm (class TestConfirmRequiresOpenDeparture, test_suite/test_03_enrollment_lifecycle.py). Category: unique-derivability gap (unreachable state under faithful impl). Both required a PENDING enrollment sitting on a non-OPEN/GUARANTEED departure, constructed by enrolling on a DRAFT departure (on_draft=True). PRD §3.2 uniquely derives DRAFT available_seats = 0 ("A new departure starts in DRAFT ... every derived counter at 0"; publishing "initializes available_seats to capacity"), so §3.3's enrollment gate refuses any DRAFT enrollment with ERR_DEPARTURE_FULL — exactly what the impl (app.py:451) does. No PRD-faithful path yields a PENDING enrollment on a non-open departure (CANCELLED cascades the enrollment to CANCELLED, producing an ambiguous ERR_INVALID_STATE vs ERR_DEPARTURE_NOT_OPEN precedence). Scaffold rule that drove generation: Difficulty/cross_entity_state_dependency/enrollment_confirm_requires_departure_open_or_guaranteed (the Step-5 watch-item).

- Fixes applied to test_helpers/: none.

- Fixes applied to test_suite/: only the deletion above (replaced the class with an explanatory NOTE comment; the surviving test_cancel_already_cancelled_enrollment_returns_invalid_state and rest of file untouched).

- Fixes applied to implementation/: none. The impl correctly follows PRD §3.2 (DRAFT available_seats = 0, initialized to capacity on open) and returns ERR_DEPARTURE_NOT_OPEN on confirm against a non-open departure.

- Final sweep: round1 54/54, round2 54/54, round3 54/54, round4 54/54, round5 54/54, round6 54/54, round7 54/54, round8 54/54 — all 8 clean.

## Step 8: Finalize PRD — 2026-07-16T12:44:00.000Z

PRD_FINALIZED.md created as a byte-identical copy of PRD.md (273 lines, 0 edits, 0% delta). The lone Step-7 test deletion was an unreachable-state / unique-derivability gap already uniquely pinned by PRD §3.2 (DRAFT available_seats=0; publish initializes to capacity) and §3.3 (ERR_DEPARTURE_FULL enrollment gate, ERR_DEPARTURE_NOT_OPEN confirm gate), with impl (app.py:451) matching PRD verbatim — so no PRD silence or mismatch warranted a patch. Per Method step 1, no edit manufactured.

Pre-edit search log: subject = DRAFT departure available_seats / enrollment-confirm gate; impl paths = create_departure available_seats:0 on DRAFT (app.py:447-451), publish→capacity, enrollment gate <1→ERR_DEPARTURE_FULL, confirm non-OPEN/GUARANTEED→ERR_DEPARTURE_NOT_OPEN; wording adjustment = none.

## Step 9: Complete PRD — 2026-07-16T12:49:00.000Z

PRD_COMPLETED.md written — 6 minimal inline pins bring the PRD to zero silence/mismatch vs implementation/.
Source: PRD_FINALIZED.md (byte-identical to PRD.md) 273 lines / 38031 chars → PRD_COMPLETED.md 273 lines / 39311 chars (+1280 chars).
Counts: ambiguity-pins = 4, mismatch-revisions = 3 (7 behaviors across 6 sentence edits).

Changes:
- §2.1 Auth — insert — mismatch — only X-User-Role gates ERR_UNAUTHENTICATED; missing X-User-ID not itself rejected — app.py:97-102.
- §3.5 Recording Payments — insert — ambiguity — overpay ceiling (ERR_PAYMENT_EXCEEDS_BALANCE) enforced only for DEPOSIT/INSTALLMENT, not REFUND/PENALTY_RETAINED — app.py:971-974.
- §3.6 Enrollment cancel — revise — mismatch — refund and penalty-retained rows each appended only when amount > 0 — app.py:616-621.
- §3.6 Enrollment cancel — insert — ambiguity — with no active/paid plan cancel still succeeds, payment_status unchanged — app.py:605,626.
- §3.6 Rebook — insert — ambiguity — new enrollment starts PENDING with payment_status derived from transferred funds; new plan copies old deposit_cents/installment_count — app.py:767-802.
- §3.6 Rebook — insert — ambiguity — returns HTTP 200 with newly created enrollment as data — app.py:806.
- §3.8 Rooming add-member — revise — mismatch — gender check precedes room-full check (reports gender mismatch when both fail) — app.py:1166-1169.
- §3.8 Rooming finalize — revise — mismatch — check order DRAFT/count≥1 (ERR_INVALID_STATE) → docs → gender → over-capacity (over-capacity last) — app.py:1180-1198.

## Pipeline complete — 2026-07-16T12:49:30.000Z

All 9 steps done. Final state: 54/54 tests pass across 8-round stability sweep. Artifacts: SCAFFOLD.yaml + 2 design files, PRD.md / PRD_FINALIZED.md / PRD_COMPLETED.md, test_helpers/ + test_suite/ (54 tests), workspace/implementation/ (Flask, 46 routes) + results.{1..8}.json.
