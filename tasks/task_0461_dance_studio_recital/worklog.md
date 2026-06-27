# Worklog — task_0461_dance_studio_recital

## Step 1: Create task directory — 2026-06-21T17:22:41.000Z

Created `tasks/task_0461_dance_studio_recital/` with `workspace/` subdirectory (pre-assigned task_dir; no auto-increment scan performed). Verified `./INSTRUCTION.md` exists for Step 3 copy.

## Step 2: Generate scaffold (Expert difficulty) — 2026-06-21T17:44:35.000Z

Scaffold subagent generated all three artifacts; subagent connection closed during summary return (after all files written). Orchestrator verified via YAML parse + content inspection:
- SCAFFOLD.yaml (2262 lines) — valid, top-level keys: scenario, domain_name (`dance-studio-recital`), api_prefix (`""`, root-mounted endpoints), complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles.
- SCAFFOLD_DIFFICULTY_DESIGN.yaml (1217 lines) — valid, single key `scaffold_difficulty_design`, 18 instances.
- SCAFFOLD_CORNER_DESIGN.yaml (1454 lines) — valid, single key `scaffold_corner_design`, 33 instances.

Coverage / scale (Expert band): 18 entities (Family, Student, Term, Room, Instructor, ClassSection, ClassSession, Enrollment, Attendance, Costume, CostumeOrder, Recital, SeatAssignment, CompetitionTeam, TeamMembership, TravelTrip, TripParticipant, Invoice); 13 state machines; 6 calculations (student_age_as_of_cutoff, tuition_monthly_charge, invoice_totals, costume_order_price, ticket_pricing_allotment, chaperone_requirement); 21 validations; 80 endpoints; 21 errors; 4 roles (StudioAdmin, Instructor, Parent, Anonymous); 2 concurrency rules. All 8 scenario facets covered (class/level & age placement, recurring tuition & auto-pay, costume order & sizing, recital ticketing & seat, competition team & travel, attendance & makeup, instructor/room schedule, family/multi-class discount). complexity_profile: temporal_windowing + pricing_engine, graph topology, parallel state machines, peer_roles.

## Step 3: Copy INSTRUCTION.md — 2026-06-21T17:44:35.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-21T17:50:43.000Z

PRD generated at `workspace/PRD.md` — **319 lines**. Sections: §1 Introduction; §2 Global Specs (2.1 RBAC for all 4 roles, 2.2 Response Structure, 2.3 Pagination, 2.4 Common Properties + Logical Clock, 2.5 Money/Rounding, 2.6 Hierarchical Consistency/Cascades, 2.7 Nested Retrieval ordering, 2.8 OCC, 2.9 Family Fiscal Standing, 2.10 Validation Ordering); §3 Business Logic (3.1 Households/Students/config spine, 3.2 Sections/Sessions/Scheduling, 3.3 Placement/Enrollment/Tuition Discount Engine, 3.4 Drop/Waitlist/Withdrawal Cascades, 3.5 Attendance/Makeups, 3.6 Costume Sizing/Ordering, 3.7 Teams/Rosters/Travel, 3.8 Recitals/Seats/Ticket Allotment, 3.9 Invoicing/Payment/Auto-Pay/Delinquency); §4 Endpoint table; §5 Error Catalogue (21 error IDs).

All three Hard Contracts PASS (Contract 1 field-name coverage 0 missing; Contract 2 rule coverage — validations/OCC/state-machines/calculations/cascades all expressed; Contract 3 §3 path-purity 0 path tokens). **Confirmed: neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read.**

## Step 5: Generate unit tests — 2026-06-21T18:06:23.000Z

Generated test infrastructure (Steps 5 & 6 launched concurrently for isolation).

**Stage 1 — `test_helpers/` (9 files):** types.py (entity TypedDicts + 17 status/role enums; Attendance omits updated_at/version as append-only), api_client.py (~80 methods, one per PRD endpoint), api_errors.py (21 error IDs + HTTP-status map), assertions.py, factories.py (input-only payloads, PRD-correct required/optional split), constants.py (discount percentages, clock default), test_users.py (opaque StudioAdmin/Anonymous shared constants + entity-backed make_instructor_headers/make_parent_headers), fixtures.py (composite setups: open-term/section chains, confirmed enrollment, delinquent family, recital-on-sale/held-seat, locked-team/proposed-trip, costume draft order, invoice generation), __init__.py.

**Stage 2 — `test_suite/` (conftest + 8 test files, 68 tests):**
- Queue A (Difficulty): all 18/18 instances × 2 tagged tests = 36 tests (files 01–05). Covers dual-variant calc, pinned-rounding/non-linear tuition, section OPEN↔FULL cycle, parallel placement/billing, depth-3 drop→promote→recompute & section-cancel cascades, state-before-fiscal & existence-before-temporal priority pairs, costume-rush & sold-out boundaries (both sides), Enrollment→Family & Section→Term cross-entity deps, buffered room vs unbuffered instructor overlaps, costume-cancel/seat-release compensation invariants.
- Queue B (Corner): all 32/32 non-stub instances, 1 test each = 32 tests (files 06–08), spanning entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting (OCC stale-version ×2, trip-confirm fee cascade), consistency_model.

**Skips/notes:** 1 stub skipped as required (`Corner/state_machines/confirm_already_dropped_enrollment_invalid_state`, has excluded_because; covered by 2 Queue-A tests). No instances dropped to PRD silence — every non-stub instance passed the two-condition filter. All citations grep-verified verbatim against PRD.md; no scaffold-terminology leakage; every test carries exactly one `Design:` tag; no skip/xfail markers. All 9 helpers + 68 tests import and collect cleanly.

## Step 6: Generate implementation — 2026-06-21T18:06:23.000Z

Built complete Python + Flask implementation in `workspace/implementation/` (16 files).

**Files:** start.sh (foreground, reads $PORT default 10000, binds 0.0.0.0, guarded pip install, exec server); app.py (blueprint registration, ApiError→envelope handlers); requirements.txt (flask==3.0.3); core: db.py (in-memory dicts + logical clock default 2026-01-01T00:00:00Z), errors.py (21-entry catalogue), response.py, middleware.py (auth/role/ownership), helpers.py (validation, pagination, level ladder, date parsing), views.py (serialization stripping _-prefixed internals); services: tuition.py, billing.py, enrollment.py; routes (12 blueprints): clock, families, students, config, sections, enrollments, attendance, costumes, recitals, teams, trips, invoices.

**Coverage:** 80 endpoints — exact 1:1 match with PRD endpoint table (zero missing, zero extra). All 21 error codes with correct HTTP statuses; validation precedence enforced (auth → role → ownership → existence → state → OCC → business rules → invalid-request).

**Notable logic:** tuition discount engine (pinned round-half-up after multi-class % then family %, per line item; multi-class index per-student by tuition DESC then created_at; family tier by sibling_count); parallel enrollment dimensions (placement × billing) with full drop→waitlist-promotion→rank-resequence→family-recompute cascade; section OPEN↔FULL cycling; explicit-confirm ERR_CAPACITY_EXCEEDED distinct from auto-resolve waitlisting; OCC on seat holds (expected_recital_version) and team roster adds (expected_team_version) → ERR_STALE_VERSION 412; ticket allotment waterfall (complimentary recompute on release); recital ON_SALE↔SOLD_OUT; clock-driven delinquency (advance past due → invoice PAST_DUE → family DELINQUENT gate); credit waterfall; frozen tuition snapshot; costume rush strict boundary; chaperone ceil() ratio; void/cancel compensation conserving fees+credit; attendance append-only; makeup eligibility recompute.

**Boot:** start.sh boots cleanly from fresh process, store empty on every boot (verified total_count=0, no seeding). All modules pass py_compile.

**Impl-gen spec-gap note (for Step 7/9 attention):** `MAKEUP_WINDOW_DAYS` referenced in PRD/scaffold but never assigned a concrete value, and "makeup session date" has no explicit input field — implementer defaulted constant to 30 days measured against logical-clock date as the makeup-session reference.

## Step 7: Test-fix iteration loop — 2026-06-21T18:12:35.000Z

Final state: **68/68 passing in all 8 parallel rounds, deterministic, no flakiness.** Verified results.{1..8}.json all show passed=68 total=68.

**Iterations run:** 2 (baseline sweep at 67/68, one fix, then clean confirming sweep at 68/68 across all 8 rounds).

**Tests deleted:** None.

**Fixes applied to test_helpers/:** None.

**Fixes applied to test_suite/:**
- `test_05_difficulty_complementary.py` — `test_section_cancel_drops_all_enrollments`: rewrote setup so the cancelled section stays in a PRD-cancellable state. Old setup used `capacity_cap: 1` with one confirmed + one waitlisted student, forcing the section into `FULL`. PRD §3.2 states verbatim "Cancellation is permitted from `PLANNED`, `SCHEDULED`, or `OPEN`" — `FULL` is excluded — so the PRD-faithful implementation correctly returned `ERR_INVALID_STATE` and the test's expected 200 was unreachable. A `WAITLISTED` enrollment can only exist while a section is `FULL`, so the waitlist branch of the cascade is structurally unreachable under any cancellable state; that assertion was not uniquely derivable (STEP 1c partial-coverage). Fix uses `capacity_cap: 20` with two `CONFIRMED` enrollments, keeping the section `OPEN` (cancellable), and asserts both confirmed enrollments move to `DROPPED` with `billing_status` → `BILLING_ENDED` — exactly the PRD-covered, uniquely-derivable portion of the §3.2 cascade rule (matches scaffold design recipe `section_cancel_drop_recompute_chain_depth2` which used capacity_cap:20 + CONFIRMED-only; the test author had deviated from it).

**Fixes applied to implementation/:** None. `cancel_section` (routes/sections.py) and `cancel_section_cascade` (services/enrollment.py) were already PRD-faithful; failure was a test-setup bug per STEP 2, not an implementation defect. No PRD-required check was weakened.

## Step 8: Finalize PRD — 2026-06-21T18:14:42.000Z

Step 8 ran (not skipped: Step 7 had 1 test_suite/ fix + 2 iterations beyond baseline). Result: **`PRD_FINALIZED.md` is byte-for-byte identical to `PRD.md`** (319 vs 319 lines, 0% delta, 0 edits).

Rationale: the single Step 7 item was a pure test-setup fixture bug, not a PRD silence or PRD/impl mismatch. The original test tried to cancel a section in `FULL` state; PRD §3.2 already states verbatim "Cancellation is permitted from `PLANNED`, `SCHEDULED`, or `OPEN`" (FULL excluded), so the PRD-faithful implementation correctly returned ERR_INVALID_STATE and the test's expected 200 was unreachable. The cancellable-state set, the drop cascade, and the PLANNED-with-confirmed guard are all already stated verbatim in PRD §3.2 and matched exactly by `routes/sections.py:152` `cancel_section` and `services/enrollment.py:128` `cancel_section_cascade`. No behavioral choice was left open by PRD here, so no patch was warranted. Pre-edit search performed on the section-cancellation subject (enumerated cancel guard, cascade, maybe_full/maybe_open writers, billing/tuition recompute) confirmed consistency.

## Step 9: Complete PRD — 2026-06-21T18:22:04.000Z

Full PRD-vs-implementation scan produced `PRD_COMPLETED.md` (source: `PRD_FINALIZED.md`). 319 → 319 lines (all edits in-paragraph), 50,067 → 54,709 chars (+4,628). Structure unchanged (27 headers, 105 table rows). **16 edits: 12 ambiguity-pins, 4 mismatch-revisions.**

Changes (`{section} — {kind} — {type} — {what} — {impl ref}`):
- §2.1 RBAC — insert — ambiguity — ERR_NOT_RESOURCE_OWNER applies only to single-resource ops; only `GET /invoices` auto-scopes Parent's list to own family — routes/invoices.py:87-88
- §2.3 Pagination — insert — ambiguity — out-of-range/non-integer limit/offset → ERR_INVALID_REQUEST; empty string treated as absent — helpers.py:40-52
- §3.1 Family email — insert — ambiguity — duplicate (case-insensitive) email → ERR_INVALID_REQUEST — routes/families.py:27-28
- §3.1 Grant credit — insert — ambiguity — amount_cents must be non-negative else ERR_INVALID_REQUEST — routes/families.py:110
- §3.1 Patch family — insert — ambiguity — expected_family_version mismatch → ERR_STALE_VERSION (412); no-op patch leaves version/updated_at untouched — routes/families.py:69-87
- §3.1 Instructor email — insert — ambiguity — duplicate email → ERR_INVALID_REQUEST — routes/config.py:137-138
- §3.2 Session end_minute — revise — ambiguity — bounded inclusive 1–1440 — routes/sections.py:85
- §3.3 Enrollment makeup_for_attendance_id — insert — ambiguity — field present only when a makeup was cited, absent otherwise — routes/enrollments.py:92-93
- §3.3 Enrollment auto-resolve — insert — ambiguity — non-enrollable section state (or OPEN-at-capacity) → ERR_INVALID_STATE; resolution ordering + initial field values — routes/enrollments.py:96-107
- §3.3 age_as_of_cutoff — revise — mismatch — PRD said "computed when student created"; impl initializes to 0, first computes at placement-vs-term — routes/students.py:39 / routes/enrollments.py:21-32
- §3.3 Explicit admin confirm — insert — ambiguity — section must be OPEN/FULL else ERR_INVALID_STATE; capacity guard after eligibility, before delinquency — routes/enrollments.py:141-158
- §3.5 Makeup window — insert — ambiguity — MAKEUP_WINDOW_DAYS = 30; makeup date = current logical-clock date; inclusive bounds; consume/eligible flips; validated before level/age — helpers.py:19, routes/enrollments.py:43-56,72-77,109-111
- §3.6 Submit-order — insert — ambiguity — processed in created_at order; all-or-nothing enrollment-status validation; empty-draft submit still moves costume to ORDERED; "current open invoice" = most-recent OPEN (no-fold when none) — routes/costumes.py:74-92, services/billing.py:5-32
- §3.6 Submitted-order cancel — revise — mismatch — PRD said "if that invoice has already been paid"; impl keys on whether an OPEN invoice currently exists — services/billing.py:35-49
- §3.8 Seat hold/purchase — insert — ambiguity — hold/purchase require recital ON_SALE/SOLD_OUT (else ERR_INVALID_STATE); state→OCC→label/sold-out ordering; purchase does not bump version — routes/recitals.py:152-157,239-249
- §3.9 Invoice generate/void — revise+insert — mismatch+ambiguity — tuition snapshot restricted to enrollments whose section is in invoice's term_id; fees_cents starts at 0; voiding a PAST_DUE that clears the last delinquency returns family to ACTIVE — routes/invoices.py:37-43,45,127-130

The §3.5 makeup-window pin (MAKEUP_WINDOW_DAYS=30) resolves the impl-gen spec-gap flagged in Step 6. Tests used only as auxiliary cross-reference; no new sections/paragraphs, no invented behavior.

---

## Pipeline complete — 2026-06-21T18:22:04.000Z

All 9 steps finished. Final state: **68/68 tests passing across 8 deterministic parallel rounds.** Task artifacts: SCAFFOLD.yaml (+ DIFFICULTY/CORNER design yamls), workspace/PRD.md → PRD_FINALIZED.md (identical) → PRD_COMPLETED.md (16 pins), test_helpers/ (9 files), test_suite/ (8 test files + conftest, 68 tests), workspace/implementation/ (16 files, 80 endpoints), results.{1..8}.json (all 68/68).
