# Worklog — task_0040_golf_tee_time_handicap

## Step 1: Create task directory — 2026-05-29

Created `tasks/task_0040_golf_tee_time_handicap/workspace`. Index 0040 used per explicit user instruction (highest existing was 0037).

## Step 2: Generate scaffold — 2026-05-29

No forbidden vocabulary. All artifacts are complete and validated.

Generated all three scaffold artifacts for **task_0040_golf_tee_time_handicap**. `scaffold_lint.py` returns **VERDICT: clean lint** (22 endpoints, 6 entities, 18 §1.8 instances, 40 active §1.9 instances, 349 calls scanned, zero violations).

**Complexity profile:** pricing_engine + quota_allocation; flat topology; branching state machines; peer_roles; immediate consistency. Layers: dual-variant calculation, ops-run checkpoint, rate/threshold triggers, optimistic concurrency, cascading side effects.

**Entities (6):** Course (rating/slope, peak window, fees, member discount), Golfer (provisional + official handicap_index, low_handicap_index, handicap_revision), Score (frozen score_differential, POSTED/VOID), TeeTime (capacity from group_type, confirmed_count, OPEN/FULL/CLOSED), Booking (CONFIRMED/STANDBY/CANCELLED, pricing_tier, green_fee_cents, standby_rank), HandicapRevision (append-only epoch, common_fields:false).

**State machines (3):** TeeTime (OPEN↔FULL cycle + OPEN→CLOSED), Booking (branching: CONFIRMED→CANCELLED forking into promote-vs-reopen; STANDBY→CONFIRMED guarded; STANDBY→CANCELLED), Score (POSTED→VOID).

**Calculations (5):** score_differential; provisional_handicap_index (uncapped live, all POSTED); official_handicap_index (as-of-date-bounded + soft/hard caps — the dual variant); booking_green_fee (tiered peak/off-peak, member discount with pinned round-then-subtract); standby_priority selector (MEMBER before PUBLIC, then created_at).

**Concurrency:** one OCC rule on TeeTime.version guarding booking-create supersede (ERR_STALE_TEE_TIME_VERSION, 412).

**Validations (14, priority-ordered)** and **errors (14)** including two distinct temporal-overlap semantics (half-open golfer-calendar conflict vs symmetric tee-sheet buffer).

**Roles (3):** ProShop (opaque operator), Golfer (entity_backed, owns own bookings/scores), Anonymous (read + self-register).

## Step 3: Copy shared files — 2026-05-29

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-29

Generated `workspace/PRD.md` — 214 lines. §1 Introduction, §2 Global Specs (10 subsections: RBAC, response envelope, pagination, versioning, cascades, OCC, rating/slope & differential, pricing tiers, field ranges, precision), §3 Business Logic (9 subsections), §4 endpoint table (22 endpoints), §5 error table (14 codes).

Notable scattering: booking-create inputs split across §3.6/§2.6/§2.8; numeric constants embedded in narrative (SLOT_MINUTES 12, TEE_INTERVAL 8, caps 3.0/0.5/5.0, STANDARD_SLOPE 113); dual-variant calc divergence contrasted between provisional (§3.2) and official (§3.4); booking validation priority order explicit in §3.6.

Hard Contracts all PASS: field coverage 41/41, rule coverage (14 validations, 1 OCC, 7 transitions, 5 calcs) complete, path purity clean (0 path tokens in §3), §2.2 envelope byte-intact.

## Step 5: Generate unit tests — 2026-05-29

Stage 1 `test_helpers/` (9 files): types.py (HandicapRevision omits version/updated_at per common_fields:false), api_client.py, api_errors.py (14 error IDs + status map), assertions.py, factories.py, constants.py, test_users.py, fixtures.py (setup_full_twosome, add_standby, clock/score/booking/refresh primitives), __init__.py.

Stage 2 `test_suite/` (conftest + 7 files): test_01_resources_crud, test_02_listing_and_rbac, test_03_booking_validations, test_04_pricing, test_05_handicap_index, test_06_booking_cascade, test_07_depth_second_angles.

Counts: **74 tests**, one Design: tag each. Queue A (Difficulty): 36 tests — all 18 instances (9 rules × 2) × 2 tests each. Queue B (Corner): 38 tests covering 38 of 40 non-stub instances.

Instances skipped (2): `Corner/entities/get_golfer_not_found` and `Corner/entities/score_fk_course_not_found` — ERR_NOT_FOUND prose scoped strictly to booking-create's referenced slot/golfer, not to GET golfer / POST scores with bad course_id; no uniquely-derivable PRD sentence (applies_to-scope silence). Stubs (excluded_because) verified, not translated.

## Step 6: Generate implementation — 2026-05-29

Built Python + Flask impl at `workspace/implementation/`. Files: start.sh (foreground, 0.0.0.0:$PORT default 10000), requirements.txt (Flask 3.0.3), app.py, db.py (in-memory, empty every boot, logical clock + insertion-seq), errors/response/middleware/pagination/serializers/validate/util, routes/ (courses, golfers, scores, tee_times, bookings, revisions, clock), services/ (handicap.py, booking.py).

All 22 endpoints. Response envelope verbatim (meta/response_type/data, req_ IDs, ISO 8601 3-digit). Decimal + round_half_up; member discount round-then-subtract. Dual handicap variant: provisional all POSTED any date; official adds played_on<=effective_date filter + soft(4.0+half-excess)/hard(anchor+5.0) caps; first refresh skips caps, seeds low_handicap_index. Depth-3 cancel cascade (promote member-first standby, reprice frozen tier, re-rank, version bumps; reopen only if no standby). OCC via expected_tee_time_version → ERR_STALE_TEE_TIME_VERSION 412. Validation precedence per §3.6 (auth→role→existence→closed→duplicate→time-conflict→slot-passed→OCC→capacity/standby). Internal fields (_seq, _index_history) excluded from serializers.

## Step 7: Run tests and iterate — 2026-05-29

Iterations run: 1 (initial 8-round parallel sweep already fully green). All 8 rounds passed 74/74, 0 failures, 0 errors, no flakiness. Tests deleted: none. Fixes to test_helpers/: none. Fixes to implementation/: none. Confirmed independently: results.{1..8}.json all 74/74.

## Step 8: Finalize PRD — 2026-05-29

SKIPPED per skip condition: Step 7 exited on first sweep with 0 deletions, 0 test_suite fixes, 0 test_helpers fixes, 0 implementation fixes. PRD.md already determined every behavior the implementation exhibits at every Step 7-exercised site. No PRD_FINALIZED.md produced.

## Step 9: Complete PRD — 2026-05-29

Produced `workspace/PRD_COMPLETED.md` from PRD.md (Step 8 skipped). PRD.md = 214 lines / 30,602 chars; PRD_COMPLETED.md = 214 lines / 32,359 chars (+1,757 chars, no line-count change — all in-paragraph). Counts: ambiguity-pins = 3, mismatch-revisions = 1.

Changes:
- §2.5 Cascades — revise — mismatch — slot derived-state recompute only on confirmed-booking create, seat-freeing (confirmed) cancel, and promotion; standby create/cancel only re-rank standbys, never touch confirmed_count/status/updated_at/version. (routes/bookings.py:113-129, 243-250)
- §2.6 OCC — insert — ambiguity — expected_tee_time_version presence/type validated at OCC step, after existence/closed/duplicate/time-conflict/slot-passed guards; omitting it on a slot that trips an earlier guard yields that earlier error. (routes/bookings.py:82-90)
- §3.4 Refresh anchor — insert — ambiguity — caps use pre-run persisted low_handicap_index; anchor refreshed only after computing capped value; strictly-open lower edge (effective_utc-365d excluded); low observed drawn from golfer's own prior official-index history. (routes/revisions.py:37,49,56-62; services/handicap.py:100-117)
- §3.4 Revision response shape — insert — ambiguity — revision resource echoes effective_utc; serializer returns id/created_at/revision_number/effective_utc/golfer_count. (serializers.py:80-87; routes/revisions.py:73-80)

No other endpoint, formula, ordering, error, or default diverged.
