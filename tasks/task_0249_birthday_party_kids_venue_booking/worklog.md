# Worklog — task_0249_birthday_party_kids_venue_booking

## Step 1: Create Task Directory — 2026-06-08T11:36:21.000Z

Created `tasks/task_0249_birthday_party_kids_venue_booking/` and `workspace/` subdirectory. Pre-allocated path used directly (no ID scan). Verified `INSTRUCTION.md` exists at project root.

## Step 2: Generate Scaffold (Expert band) — 2026-06-08T11:53:00.000Z

Generated a complete **Expert-band** scaffold for **Task 0249 — Birthday Party & Kids' Venue Booking** in three files. `scaffold_lint.py` returns **VERDICT: clean lint** (505 calls across 18 difficulty + 41 corner instances conform to §1.5; all 12 FKs reverse-reachable). All `grounds` refs resolve; instance names are unique across both design files.

**Complexity profile:** temporal_windowing (primary) + workflow_orchestration (secondary); layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation, scheduled_actions; hybrid topology; branching/cyclic state shape; peer-role RBAC.

**Entities (11):** Venue, Room, PartyPackage, StaffMember (flat config peers); Booking (central resource); AddOn, GuestParty (append-only roster, `common_fields: false`), Waiver, StaffAssignment, Payment (Booking children); SystemClock (test-driving).

**State machines (5):**
- **Booking** — non-linear/cyclic: QUOTE_DRAFT→HELD→CONFIRMED→COMPLETED with a weather branch CONFIRMED→WEATHER_HOLD→RESCHEDULED→CONFIRMED (cycle, reschedule_count++), plus *→CANCELLED with cascade; parallel payment_status dimension (UNPAID/DEPOSIT_PAID/PAID_IN_FULL/REFUNDED).
- **Waiver** — DRAFT↔SIGNED revert branch + →VOIDED.
- **StaffAssignment**, **AddOn**, **Payment** — linear with cross-entity guards.
- 1 concurrency rule: OCC on `Booking.version` for reschedule (ERR_STALE_VERSION/412).

**Key calculations (8):** dual-variant `booking_quote_total` (estimate, net-current children) vs `booking_final_total` (settlement, chronological peak-children replay → 7500¢ divergence); `cancellation_refund` (tiered forfeit-deposit vs full); `deposit_due_amount` (pinned eval-order, ceiling); `room_window_occupancy` (half-open intervals incl. buffer); `staff_window_occupancy` (closed intervals — adjacency conflicts); `payment_status_derive`; `amount_paid_reconcile`. All money in integer cents; chronological order keyed on `created_at ASC` (never `id`).

**Endpoints:** 44 (42 business + 2 `/_clock` test-driving).
**Error catalog:** 39 codes.
**RBAC:** 4 roles — VenueManager/Coordinator/FinanceClerk (opaque), Guardian (entity_backed:Booking).

**Design instances:** §1.8 = **18** (9 rules × 2). §1.9 = **46** (41 active corner instances + 5 `excluded_because` stubs pointing at covering §1.8 instances).

Note: `api_prefix` set to `/` so flat config collections (`/venues`, `/rooms`, etc.) are recognized by lint's FK reverse-reachability segment derivation.

Files: SCAFFOLD.yaml (1202 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1123 lines), SCAFFOLD_CORNER_DESIGN.yaml (1733 lines).

## Step 3: Copy Shared Files — 2026-06-08T11:53:30.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-08T11:59:30.000Z

Generated `workspace/PRD.md` from the EXPERT-band kids-venue-booking scaffold. 5 top-level sections, ~301 lines. §2 has 10 domain-derived subsections (role/auth, fixed response envelope, pagination, common-properties/versioning, hierarchical cascades, OCC, nested-retrieval ordering, validation priority, monetary precision, logical clock). §3 has 12 lifecycle/process subsections. §4 endpoint table (all 44 endpoints); §5 error table (all 39 codes).

Hard Contract reports: Contract 1 (Field-Name Coverage) 69/69 PASS; Contract 2 (Rule Coverage) all validations/OCC/state-machines/calculations/sibling-branch-symmetry 0 missing PASS; Contract 3 (§3 Path Purity) 0 path tokens PASS. Every entity, state machine, calculation, validation, endpoint, error, and role covered. Design index files not opened.

## Step 5: Generate Unit Tests — 2026-06-08T12:15:00.000Z

Generated complete test infrastructure for EXPERT band kids venue booking API.

### test_helpers/ (9 files)
- `__init__.py` — barrel export; `types.py` — entity TypedDicts + status/role enums (GuestParty & SystemClock omit `updated_at`/`version` per `common_fields: false`); `api_client.py` — one method per endpoint; `api_errors.py` — full 41-error catalog + HTTP-status map; `assertions.py` — per-entity assertions + money-conservation invariant; `factories.py` — input-field-only payload factories; `constants.py` — domain thresholds (FREE_CANCEL_HOURS=72, deposit/duration/buffer defaults); `test_users.py` — opaque role headers + `make_guardian_headers`; `fixtures.py` — composite lifecycle setup helpers.

### test_suite/ (conftest + 9 test files, 76 test functions)
- **Queue A (Difficulty §1.8): 36 tests** — all 18 instances covered, exactly 2 tests each.
- **Queue B (Corner §1.9): 40 tests** — 40 of 41 non-stub instances covered ≥1 test each.

### Skipped instances (1)
- **`Corner/endpoints/filtered_list_bookings_by_status`** — endpoint-titular/applies_to-scope: PRD's only `status`-filter prose (§3.1) is scoped to *configuration* list endpoints; `/bookings` listing is titular only. No verbatim PRD sentence uniquely derives `?status=HELD` filters bookings → skipped.

### Stubs (5, correctly NOT translated)
All 5 `excluded_because` corner stubs resolve to real difficulty instances that own the assertion.

### Audits passed
Every difficulty instance ≥2 tests; every covered corner instance ≥1 test; no dangling tags; every docstring carries exactly one verbatim `Design:` tag; all cited PRD sentences survive literal grep; no skip/xfail; no scaffold leakage; all imports resolve; all files compile. One non-derivable assertion dropped (`version == 1` in `booking_system_fields_ignored_on_input`, since PRD §2.4 says version "starts at its initial value" without pinning to 1).

## Step 6: Generate Implementation — 2026-06-08T12:15:00.000Z

Built complete Python + Flask in-memory REST API at `workspace/implementation/`.

### Source files created (15)
`start.sh` (foreground `exec`, guarded pip install, reads `$PORT`, binds `0.0.0.0`), `requirements.txt`, `app.py`, `db.py`, `errors.py`, `response.py`, `middleware.py`, `routes/config.py`, `routes/bookings.py`, `routes/children.py`, `routes/__init__.py`, `services/common.py`, `services/calc.py`, `services/booking.py`, `services/__init__.py`.

### Endpoint count — all 44 declared endpoints implemented.

### start.sh contract — confirmed: reads `$PORT` (default 10000), binds `0.0.0.0`, foreground via `exec`, ready ~0.6s. Empty store on fresh boot, no seeding, no disk persistence.

### Notable design decisions
- **Dual-variant totals**: `quote_total_cents` (estimate) prices on live children_count + ACTIVE add-ons; `final_total_cents` (settlement) reconstructs creation-time children count (current − Σdeltas), replays GuestParty events in `created_at` ASC, prices overage on peak running count. Verified divergence (20000 settlement vs 12000 net estimate).
- **OCC**: only `PATCH /reschedule` accepts `expected_booking_version`; compared against `Booking.version` (bumps +1 on every mutation) → `ERR_STALE_VERSION` (412).
- **Temporal overlap buffers**: room windows half-open `[start, end+buffer)` (adjacency allowed); staff windows closed `[start, end+buffer]` (back-to-back conflict). Candidate set `{HELD,CONFIRMED,WEATHER_HOLD,RESCHEDULED}`.
- **Cascade side-effects**: cancel cascades ACTIVE add-ons→REMOVED, ASSIGNED staff→RELEASED, DRAFT/SIGNED waivers→VOIDED, synthesizes tiered CANCELLATION_REFUND payment (72h threshold + pre-confirmation stage), re-reconciles amount_paid→balance→payment_status (→REFUNDED at net-zero). Complete releases all ASSIGNED staff.
- **Pinned reconciliation order** (quote → deposit → balance → payment_status); deposit frozen via `_deposit_pinned` on first HELD→CONFIRMED; deposit uses `ceil`. Integer cents only.
- **Validation precedence** per PRD §2.8 (auth → perm → existence → FK → shape → state → config → waivers → staffing → overlap → capacity → timing → fiscal → OCC).

## Step 7: Run Tests and Iterate — 2026-06-08T12:30:00.000Z

All 8 parallel rounds pass 76/76. Clean exit. (Orchestrator re-ran an independent verification 8-round sweep afterward: rounds 1–8 all 76/76, results.{1..8}.json persisted.)

**Iterations run:** 2 (1 diagnostic baseline at 67/76, then 1 fix batch → 8/8 green).

The baseline sweep showed a stable 9-test failure set (identical across all 8 rounds, no flakiness). The 9 failures fell into 4 root causes.

**Tests deleted:** None. All 9 failing tests traced to verbatim PRD prose and were uniquely derivable; every one was kept.

**Fixes applied to `test_helpers/`:**
- `assertions.py` — added `assert_instant_eq(actual, expected)` (parses both ISO-8601 strings to instants and compares). Reason: 5 tests asserted `event_start_utc`/`event_end_utc` via exact string equality against `...:00Z`, but the implementation serializes event times as `...:00.000Z`. PRD §2.4 pins "three fractional digits" only for `created_at`/`updated_at`; for event times PRD §2.9 says merely "Times are ISO 8601 UTC" — the fractional-digit count is not PRD-determined and the framework's own `is_iso8601_timestamp` accepts both forms. Per STEP 1c (partial coverage) the computed *instant* is PRD-derivable while exact serialization is not.

**Fixes applied to `test_suite/`** (mechanical follow-on — swapped exact-string event-time equality for `assert_instant_eq`):
- `test_01_pricing_and_settlement.py` (lines 197, 234), `test_02_booking_lifecycle.py` (lines 33-34), `test_03_cascades_and_invariants.py` (lines 80, 86), `test_07_entities_and_crud.py` (line 48).

**Fixes applied to `implementation/`:**
- `routes/bookings.py`, `confirm_booking()` — reordered confirmation gates so staffing completeness (host/add-on-staff) is checked *before* the deposit fiscal gate. PRD §2.8's numbered precedence places "(9) staffing completeness" before "(13) fiscal gates" and states "Earlier checks mask later ones"; code previously returned `ERR_DEPOSIT_NOT_MET` where tests (citing §2.8) require `ERR_HOST_NOT_ASSIGNED`/`ERR_ADDON_STAFF_MISSING`. §2.8 is the authoritative ordering section over §3.8's narrative.
- `routes/bookings.py`, `create_booking()` — added package-status precondition: a `RETIRED` package rejects booking creation with `ERR_PACKAGE_RETIRED`. Traces to PRD §3.1 ("after which it rejects new quotes with `ERR_PACKAGE_RETIRED`") + §3.2 (booking create is a new quote). Placed at validation priority 7.
- `app.py`, server bootstrap — replaced `app.run()` with a pre-bound listening socket (`SO_REUSEADDR`+`SO_REUSEPORT`, short retry loop) handed to `werkzeug.serving.make_server`. Under per-test-server isolation the runner SIGKILLs and immediately respawns on the same port; the dying socket could linger causing "Address already in use" → spurious restart failure. Caused `test_confirm_quote_draft_returns_state_error_not_waiver` to fail on setup every round (assertion was already correct).

**Final result:** 8/8 parallel rounds at 76/76. No tests deleted; no assertions weakened; no PRD-required implementation check removed.

## Step 8: Finalize PRD — 2026-06-08T12:40:00.000Z

Produced `workspace/PRD_FINALIZED.md`. PRD.md = 301 lines, PRD_FINALIZED.md = 301 lines (0 line delta; 2 lines revised in place). Both edits trace to Step 7 implementation fixes.

**Changes:**
- **§3.2 — revise** — Added that booking creation rejects a `RETIRED` package with `ERR_PACKAGE_RETIRED` (checked after the venue-agreement resolution), since opening a booking computes the quote estimate immediately — `routes/bookings.py:72-73`.
- **§3.8 — revise** — Reordered the confirmation completeness gates so staffing completeness (`ERR_HOST_NOT_ASSIGNED`/`ERR_ADDON_STAFF_MISSING`) precedes the deposit gate (`ERR_DEPOSIT_NOT_MET`), matching §2.8's numbered precedence; original prose listed deposit before staffing — `routes/bookings.py:246-260`, `services/booking.py:132-142`.

**Step 7 items requiring no PRD edit:**
- Event-time serialization (assertions.py + test_suite) — pure test-laxity fix; §2.9 left verbatim (fractional-digit count is PRD-free for event times).
- app.py socket bootstrap — pure infrastructure (port-rebind under per-test-server isolation); no observable behavioral contract.

NO-NEW-MISMATCH pre-edit search performed for both edits (RESCHEDULED vs HELD confirm paths verified consistent; RETIRED check ordering verified against `create_booking`/`hold_booking` and binary LISTED/RETIRED status set).

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-09T00:00:00.000Z

**Files:** Source `PRD_FINALIZED.md` vs `PRD_COMPLETED.md`
- Line count: 301 → 301 (unchanged; all edits are in-paragraph)
- Char count: 44,601 → 46,827 (char-delta **+2,226**)

**Counts:** ambiguity-pins: 6; mismatch-revisions: 1.

**Changes (one bullet each):**

- §3.8 Confirming a Booking — revise — mismatch — PRD said the `RESCHEDULED → CONFIRMED` path re-checks only waiver completeness + deposit gate; impl also enforces exactly one `ASSIGNED HOST` (`ERR_HOST_NOT_ASSIGNED`) on that path and skips only the add-on-staffing check — `routes/bookings.py:255-257`
- §3.2 Opening a Booking — insert — ambiguity — create-time field list omitted the monetary derivations; pinned that `amount_paid_cents`/`final_total_cents` init to 0 and that `quote_total_cents`, `deposit_due_cents` (ceil of quote × `deposit_pct`), and `balance_due_cents` are all computed at creation in `QUOTE_DRAFT` — `routes/bookings.py:86-105`, `services/calc.py:172-188`
- §3.2 Opening a Booking — insert — ambiguity — PRD §2.1 only covered Guardian-set `guardian_user_id`; pinned that a Coordinator-created booking takes it from an optional `guardian_user_id` body field, null when absent — `routes/bookings.py:81`
- §3.4 Guest Roster — insert — ambiguity — pinned that a roster event whose deltas would drop resulting `children_count` below 1 or `adults_count` below 0 is rejected with `ERR_INVALID_REQUEST` (and that this is checked before applying deltas) — `routes/children.py:145-151`
- §2.3 Pagination — insert — ambiguity — pinned that out-of-range `limit`/`offset` are silently clamped (limit→[1,100], negative offset→0), while non-integer values raise `ERR_INVALID_REQUEST` — `services/common.py:131-139`
- §3.2 Opening a Booking (head-count paragraph) — insert — ambiguity — pinned the booking list's optional exact-match filters: `room_id`, `package_id`, `venue_id`, `guardian_user_id`, `status`, `payment_status` — `routes/bookings.py:117-121`
- §2.7 Nested Resource Retrieval — insert — ambiguity — pinned the optional `status` filter on the add-on, waiver, and both staff-assignment list endpoints, and that the roster-event list takes no filter — `routes/children.py:89-91,222-224,330-332,368-370`
- §2.8 Validation Ordering (step 6) — insert — ambiguity — pinned that the wrong-source-state case surfaces the transition's named state error where one exists (`ERR_ADDON_LOCKED`, `ERR_WAIVER_LOCKED`, `ERR_BOOKING_NOT_SIGNABLE`, `ERR_BOOKING_SETTLED`, `ERR_REFUND_IMMUTABLE`, `ERR_HOLD_HAS_PAYMENTS`) and otherwise the generic `ERR_INVALID_STATE` (409) used by hold/release-hold/confirm/complete/reschedule/head-count-update and by signing a non-DRAFT waiver, revoking a non-SIGNED waiver, releasing a non-ASSIGNED assignment, voiding a non-SETTLED payment — `routes/bookings.py:148,187,222,242,312,341`, `routes/children.py:244,270,347,446`

**Notes on items deliberately left unchanged** (verified consistent, not mismatches): no capacity check at booking creation (enforced only on hold — confirmed by `test_08:63-75`); deposit ceiling via `round(raw,9)` is float-safety only; reschedule does no re-pricing; staff overlap candidate set includes same-booking other assignments; completion balance gate computes settlement before COMPLETED — all already pinned correctly by existing PRD prose.
