# Worklog — task_0455_talent_agency_booking

Scenario: Talent Agency & Booking (actors/models): talent roster & portfolio/comp card, casting/job submission, audition & callback scheduling, booking & rate/usage rights, agency commission & escrow, payment (SAG/non-union) & residual, availability/conflict hold, deal memo

Difficulty band: Expert (10–15 entities)

## Step 1: Create task directory — 2026-06-21T11:56:40.000Z

Created `tasks/task_0455_talent_agency_booking/` with `workspace/` subdirectory. Verified `INSTRUCTION.md` and `prd-bench-local-run` are available. Project root: `/Users/uni/Desktop/吉/project/custom_prd_bench`.

## Step 2: Generate scaffold (Expert) — 2026-06-21T12:15:06.000Z

Generated the complete scaffold for **task_0455_talent_agency_booking** at the **Expert** difficulty band. All three files written:
- `SCAFFOLD.yaml` (§1.0–§1.7) — 1427 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single `scaffold_difficulty_design` key) — 1434 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` (single `scaffold_corner_design` key) — 1380 lines

**Entity count: 13** (within Expert 10–15). Entities: `Agency, CastingDirector, Talent, CompCard, CastingCall, Submission, AuditionSlot, AvailabilityHold, DealMemo, Booking, CommissionEntry, Payment, ResidualSchedule`.

**State machines: 9** — `Talent`, `CastingCall`, `Submission` (branching fork-join), `AuditionSlot`, `AvailabilityHold`, `DealMemo` (cyclic OFFERED↔COUNTERED negotiation loop), `Booking` (work lifecycle), `Booking_payment_dimension` (parallel payment axis), `ResidualSchedule`.

**Calculations: 7** — `booking_gross_fee`, `provisional_commission` (forward-looking) vs `final_commission` (chronological), `talent_availability_projection` vs `talent_committed_days` (dual-variant), `sag_residual` (tiered/media combinatorial), `payment_net_to_talent` (pinned per-component rounding order).

**Validations/errors: 13 validation rules, 26 error codes. Roles: 3** — `Agent`, `CastingDirector` (entity_backed), `Talent` (entity_backed). **57 endpoints, 1 concurrency rule** (OCC on `Talent.version` for booking create).

Lint clean (484 calls scanned, all FK reverse-reachability satisfied). All 9 Difficulty Rules covered with 2 instances each (18 total); 26 active corner instances + 10 `excluded_because` stubs.

## Step 3: Copy INSTRUCTION.md — 2026-06-21T12:15:25.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-21T12:21:01.000Z

Output written: `workspace/PRD.md` (275 lines, 39836 bytes). Did NOT read either withheld design file.

**Section structure:** §1 Introduction; §2 Global Specifications (2.1 RBAC for Agent/CastingDirector/Talent, 2.2 Response Structure verbatim, 2.3 Pagination, 2.4 Common Properties + Logical Clock, 2.5 Hierarchical Consistency/Cascades, 2.6 Left-to-Right Resolution, 2.7 Monetary Precision, 2.8 OCC on Booking Creation, 2.9 Validation Ordering); §3 Business Logic (9 lifecycle subsections); §4 Endpoint table (57 endpoints); §5 Error table (26 errors).

**Hard Contract:** Field coverage PASS (52/52 entity fields, 44/44 endpoint inputs). Rule coverage PASS (13/13 validations, 1/1 OCC, 36/36 transitions, 7/7 calculations). Path purity PASS (0 path tokens in §3). All constants embedded (commission 0–5000, bps denom 10000, SAG P&H 1850, MAX_ROUNDS=8, SLOT_BUFFER 15min, media multipliers, period tiers).

## Step 5: Generate unit tests — 2026-06-21T12:42:00.000Z

**Test files: 9** (+ conftest.py), **total tests: 61**.
- test_01_commission_and_payment_math.py (10), test_02_availability_and_holds.py (5), test_03_deal_memo_negotiation.py (3), test_04_booking_lifecycle.py (10), test_05_cascades_and_invariants.py (8), test_06_validation_precedence_and_concurrency.py (7), test_07_entities_crud.py (7), test_08_state_transitions.py (6), test_09_rbac_and_listing.py (5).

**Queue A (Difficulty):** 18/18 instances translated, 2 tests each (36 tests). 0 skipped.
**Queue B (Corner):** 25/26 non-stub instances translated (1 test each). **1 skipped:** `state_machines/max_negotiation_rounds_blocked` — unique-derivability failure (setup does 6 exchanges but PRD §3.5 MAX_ROUNDS=8, so a faithful reader would permit the 7th; asserted ERR_MAX_NEGOTIATION_ROUNDS not derivable). 11 `excluded_because` stubs correctly not translated.

**test_helpers/ files (9):** __init__.py, types.py, api_client.py, api_errors.py, assertions.py, factories.py, constants.py, test_users.py, fixtures.py. Every test carries exactly one verbatim-grep-verified `Design:` tag; entity-backed roles thread real entity ids via make_*_headers.

## Step 6: Generate implementation — 2026-06-21T12:42:00.000Z

Python + Flask implementation in `workspace/implementation/`. Files: start.sh (executable, foreground), requirements.txt (Flask==3.0.3), app.py, db.py, errors.py, response.py, middleware.py, timeutil.py, routes/ (14 blueprints), services/ (common.py, calc.py, reconcile.py).

**Storage:** in-memory only — one Python dict per collection on a single `Store` in db.py; derived fields recomputed on mutation. **No seeding** — store boots empty (verified total_count 0, 404 for any id). start.sh reads `PORT` (default 10000), binds 0.0.0.0, `exec python3 app.py` foreground; pip install guarded.

**Spec-fidelity notes from impl-gen:** (1) `expected_talent_version` checked only on booking *create*, not confirm (PRD §2.8: "No other endpoint accepts or requires a version field"). (2) Cancelling a COMPLETED+PAID booking → ERR_INVALID_STATE (priority 6), since the state machine has no cancel transition out of COMPLETED; ERR_BOOKING_ALREADY_PAID bound to CONFIRMED→CANCELLED.

## Step 7: Test & iterate loop — 2026-06-21T12:42:00.000Z

Clean 8-round parallel sweep achieved. All 60 tests pass in every one of the 8 concurrent rounds, with zero flakiness.

**Iterations run:** 2 sweeps after the initial baseline (baseline: 23/61 passing → fix → 55/61 → fix → 60/60 clean).

**Root cause:** A single systemic test-helper bug masked as 38 failures. PRD §3.5 states that opening a deal memo advances the submission to `OFFER_EXTENDED` *only* if it is in `AUDITION_SCHEDULED`/`CALLBACK_SCHEDULED`, and the first offer is permitted *only* when the submission is `OFFER_EXTENDED` (else `ERR_SUBMISSION_NOT_OFFERABLE`). The fixtures and several inline test setups submitted a talent and opened a deal memo while the submission was still `SUBMITTED`, so it never advanced to `OFFER_EXTENDED` and the subsequent offer was correctly rejected by the PRD-faithful implementation. This is a test-precondition bug (STEP 2), not an implementation bug — the implementation correctly enforces the PRD gate.

**Fixes applied to `test_helpers/` (1 file):**
- `test_helpers/fixtures.py` — in `setup_accepted_deal` and `setup_offered_deal_memo`, inserted a `schedule_audition_slot(cd_id, submission["id"])` call after `create_submission` and before `create_deal_memo`, driving the submission `SUBMITTED → AUDITION_SCHEDULED` so the deal-memo open advances it to `OFFER_EXTENDED` (PRD §3.5).

**Fixes applied to `test_suite/` (5 inline setups, same precondition bug):**
- `test_04_booking_lifecycle.py` — `test_confirm_booking_requires_deal_memo_accepted`, `test_confirm_booking_with_rejected_deal_rejected`: added `schedule_audition_slot` before the deal-memo open (and to their inline imports).
- `test_06_validation_precedence_and_concurrency.py` — `test_confirm_cancelled_booking_state_check_beats_deal_gate`, `test_create_booking_with_stale_talent_version_rejected`: added `schedule_audition_slot` before the deal-memo open.
- `test_09_rbac_and_listing.py` — `test_casting_director_cannot_create_booking`: added `schedule_audition_slot` before the deal-memo open (and to its inline import).

**Tests deleted (1):**
- `test_cancel_paid_booking_rejected` (`test_08_state_transitions.py`) — **ERROR PRECEDENCE SILENCE** (STEP 1b). PRD scaffold rule `Corner/state_machines/cancel_paid_booking_rejected`. The test cancels a `COMPLETED`+`PAID` booking expecting `ERR_BOOKING_ALREADY_PAID`, but PRD §3.7 scopes that error strictly to a `CONFIRMED` booking ("A `CONFIRMED` booking ... once payment has been posted, the cancel is refused with `ERR_BOOKING_ALREADY_PAID`"), while PRD §3.8 requires a booking to be `COMPLETED` to receive payment — making `CONFIRMED`+`PAID` unreachable. The only reachable paid state is `COMPLETED`+`PAID`, on which the PRD is silent for cancellation; §2.9 priority-6 state-legality then uniquely yields `ERR_INVALID_STATE` (the implementation's behavior). The PRD does not support even the "ERR_BOOKING_ALREADY_PAID is possible" reading for a COMPLETED booking, so relaxation was not applicable — deletion per cardinal rules.

**Fixes applied to `implementation/`:** None. The implementation was PRD-faithful throughout; no implementation check was weakened or added.

## Step 8: Finalize PRD — 2026-06-21T12:57:18.000Z

Produced `workspace/PRD_FINALIZED.md` (275 lines / 5884 words; PRD.md was 275 lines / 5814 words → +70 words / +1.2%, 0 lines added). Single in-place sentence revision in §3.7.

**Changes (1):**
- §3.7 — revise — Pinned booking-cancel state-legality: only `PENDING`/`CONFIRMED` are cancellable; any other `booking_status` (notably `COMPLETED`, whether `UNPAID` or `PAID`, and already-`CANCELLED`) is refused with `ERR_INVALID_STATE` per §2.9 priority-6, and `ERR_BOOKING_ALREADY_PAID` is scoped strictly to a `CONFIRMED` booking (never `COMPLETED`+`PAID`). — `routes/bookings.py:178-182`.

**Step 7 diff disposition:** Fixture/inline-setup fixes (the systemic 38-failure root cause) drove NO PRD edit — pure test-precondition bugs; PRD §3.5 already uniquely determines impl behavior. The deleted `test_cancel_paid_booking_rejected` (error-precedence silence) drove the single §3.7 edit. No implementation/test files modified.

## Step 9: Complete PRD — 2026-06-21T13:06:03.000Z

Produced `workspace/PRD_COMPLETED.md` from `PRD_FINALIZED.md` (both 275 lines; 40,364 → 42,421 chars, +2,057 chars, all in-paragraph). **11 ambiguity-pins, 0 mismatch-revisions** — implementation already matched every uniquely-described PRD behavior; all gaps were silences.

**Changes (11 inserts):**
- §2.3 Pagination — pinned out-of-range/non-integer limit/offset handling (clamp; unparseable → default) — `services/common.py:149`
- §2.4 Common Properties — pinned `version` initial value = 1 — `services/common.py:14`
- §2.4 Logical Clock — pinned clock echo shape (single `now`, UTC, 3 fractional digits only when sub-second) — `routes/clock.py:23-25`
- §2.9 Validation Ordering — pinned `ERR_INVALID_DATE_RANGE` as trailing business rule (after overlap constraints) — `routes/audition_slots.py:69-74`
- §3.2 Submissions — pinned decline/withdraw legal source states (excludes OFFER_EXTENDED) — `routes/submissions.py:82,96`
- §3.3 Audition Slots — added `status` to list filter set — `routes/audition_slots.py:118`
- §3.5 Deal Memo — pinned DRAFT-memo initial rate/term = 0 — `routes/deal_memos.py:41-42`
- §3.5 Deal Memo — pinned offer/counter field bounds (rates ≥ 0, term no lower bound) — `routes/deal_memos.py:83-84,111-112`
- §3.5 Deal Memo — pinned accept/reject errors (non-facing party → ERR_FORBIDDEN_ROLE; not OFFERED/COUNTERED → ERR_INVALID_STATE) — `routes/deal_memos.py:151-164`
- §3.7 Commission Entries — added `status` to list filter set — `routes/commission_entries.py:18`
- §3.8 Payment — pinned posted-payment returned fields; `final_commission_cents` lives on booking not payment — `routes/payments.py:68-77`
- §3.9 Residual Schedules — added `status` to list filter set — `routes/residual_schedules.py:59`

## Final verification — 2026-06-21T13:06:03.000Z

Steps 8–9 touched only PRD docs (PRD_FINALIZED.md, PRD_COMPLETED.md); implementation/test code unchanged from Step 7. Ran a final 8-round parallel confirmation sweep to regenerate durable `results.{1..8}.json` artifacts: **all 8 rounds 60/60 passing, 0 failures, 0 flakiness.** Pipeline complete.
