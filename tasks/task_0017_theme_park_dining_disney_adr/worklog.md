# Worklog — task_0017_theme_park_dining_disney_adr

## Step 1: Create task directory — 2026-05-27T00:00:00Z

Task directory was pre-created by the user at `./tasks/task_0017_theme_park_dining_disney_adr/`. Verified existence and ensured `workspace/` subdirectory exists. Skipped NNNN auto-allocation per user instruction.

## Step 2: Generate scaffold — 2026-05-27T04:27:00Z

All three files are written and pass the scaffold_lint cleanly. Here is the summary.

---

# Summary

**Generated files** (all in `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0017_theme_park_dining_disney_adr/`):

- `SCAFFOLD.yaml`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `SCAFFOLD_CORNER_DESIGN.yaml`

**Lint verdict**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (398 calls scanned)

**Scaffold counts**:
- Entities: 9 (Guest, Restaurant, ParkSession, DiningPlan, Reservation, AllergyMeal, LightningLaneAddOn, NoShowFeeAssessment, CreditLedgerEntry)
- State machines: 4 (Reservation, ParkSession, LightningLaneAddOn, AllergyMeal)
- Concurrency rules: 2 (both OCC on Reservation.version)
- Calculations: 4 (dining_plan_credit_debit, no_show_fee_amount, reservation_window_open_at, lightning_lane_addon_fee)
- Validations: 19 priority-ordered rules
- Endpoints: 45 (includes test-driving `/_clock/set_current_utc`, `/_ops/no-show-sweep`, `/_ops/lightning-lane-expiry-sweep`)
- Error codes: 20
- Roles: 3 (Guest entity-backed, Restaurant entity-backed, PlatformAdmin opaque — peer_roles model)

**Complexity profile**: primary archetype `temporal_windowing` × secondary `quota_allocation`; layers = OCC + cascading side effects + rate/threshold triggers + scheduled actions; flat topology; branching state machines.

**§1.8 Difficulty Design notable choices**: 18 instances across all 9 Rule IDs (2 each). Rule 1 contrasts DiningPlan credit-debit (provisional vs final, party-size-patch divergence) with LL addon fee (per-seat-rounded vs sum-rounded). Rule 2 instances span mode-a (tier × park × character combinatorial) and mode-b (PINNED per-seat rounding produces 5912 vs forbidden 5913 for the no-show fee). Rule 4 instance 1 is a depth-3 transitive cascade (ParkSession.cancel → Reservation.cancel → LL.cancel). DST-free dates (Feb 2026) keep arithmetic precise (EST UTC-5).

**§1.9 Corner Design notable choices**: 26 instances spanning entities / state_machines / validations / errors / rbac / complexity_layers / consistency_model sections, with `excluded_because:` stubs cross-referencing §1.8 instances (e.g., ERR_SLOT_CAPACITY_EXCEEDED defers to the overlap difficulty instance). Includes OCC positive-companion test, idempotent no-show sweep, scheduled-action clock toggle, and the 401-with-anonymous-role corner.

## Step 3: Copy INSTRUCTION.md — 2026-05-27T04:27:30Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD.md — 2026-05-27T04:32:00Z

## Summary

**Output**: `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0017_theme_park_dining_disney_adr/workspace/PRD.md`

**Line count**: 243 lines.

**Document structure**:
- §1 Introduction (2 paragraphs framing the multi-reality consistency problem)
- §2 Global Specifications (9 subsections): 2.1 RBAC, 2.2 Response Structure (verbatim), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Time/Timezones/Test-Drivable Clock, 2.6 Hierarchical Consistency and Cascade Semantics, 2.7 Optimistic Concurrency Control, 2.8 Validation Priority and Precision, 2.9 Nested Resource Retrieval
- §3 Business Logic & Workflows (8 subsections, grouped by lifecycle stage): 3.1 Onboarding, 3.2 Park Session, 3.3 Booking inside 60-day window, 3.4 Confirmation/Holding/Party-size patch, 3.5 Check-in/Seat/Complete/No-show, 3.6 Allergy Meals revert loop, 3.7 Lightning Lane pricing/redemption, 3.8 Operator clock & sweeps
- §4 Endpoint Definitions (45-row table, 4 columns)
- §5 Error Code Catalogue (20-row table, 2 columns)

**Hard Contracts**:
- **Contract 1 (Field-Name Coverage)**: PASS — 57 required field names, 57 present, 0 missing (after one repair pass adding `assessed_at` and `posted_at`).
- **Contract 2 (Rule Coverage)**: PASS — all 17 state-transition entries, 4 calculation formulas (with PINNED per-seat rounding), all 19 validation priorities (explicitly ordered in §2.8), both OCC rules (write_endpoint + `expected_reservation_version` + `ERR_STALE_VERSION`/412 all named in §2.7 and reaffirmed at use sites), all cascade side-effects (ParkSession cancel's two-hop cascade, no-show's full cascade chain) expressed.
- **Contract 3 (§3 Path Purity)**: PASS — §3 contains 400 backtick tokens; 0 start with `/`, 0 are bare HTTP methods, 0 are method+path combos. Endpoints referenced via state-transition framing and role+verb gerunds.

**Notable design choices**:
- Scattered the no-show fee constants (1000¢ character surcharge, tier multipliers 1.075/1.250, threshold strike counts 1/3/4+) inside §3.5 narrative rather than a constants block.
- Lightning Lane park multipliers embedded inline in §3.7 prose.
- The two-hop session-cancel cascade is described in §3.2 with explicit ordering (reservation first, then add-on), and the no-show fee per-seat-rounding-then-multiply ordering is given in §3.5 with the explicit warning that rounding-after-multiply is wrong.
- Validation priority enumerated as a single ordered prose sentence in §2.8 rather than a numbered list, forcing the reader to track sequence.
- §2.7 explicitly forbids race/timing framing per the OCC contract guidance; rejection is purely stale-version.

## Step 5: Generate unit tests — 2026-05-27T04:58:00Z

Generation complete. Let me provide the summary.

## Summary

Generated complete test infrastructure for **task_0017_theme_park_dining_disney_adr**.

### Files created

**test_helpers/** (9 modules):
- `__init__.py` — barrel export of framework generics + PRD-specific symbols
- `types.py` — entity TypedDicts (Guest/Restaurant/ParkSession/DiningPlan/Reservation/AllergyMeal/LightningLaneAddOn carry full common-fields; NoShowFeeAssessment + CreditLedgerEntry are append-only, only `id` + `created_at`) and all status enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint
- `api_errors.py` — `ApiErrorId` enum + HTTP status map registered with framework
- `assertions.py` — per-entity assertions; separate `_assert_common_fields` and `_assert_append_only_fields` for the two-tier model
- `constants.py` — pricing tables (LL_BASE_CENTS, LL_PARK_MULT, character uplift), no-show tiers, booking-window arithmetic
- `factories.py` — input-only payload factories for every entity + ops
- `test_users.py` — TEST_USERS shared constants + `make_guest_headers`/`make_restaurant_headers` per-instance builders (mandatory for entity_backed roles)
- `fixtures.py` — five tiers of composite setup: `set_clock`, single-entity creators, `setup_guest_restaurant_plan_session`, `setup_pending_reservation`, `setup_confirmed_reservation`, `drive_guest_no_show_count` (for suspension scenarios), plus fetchers and ledger listers

**test_suite/** (14 test files + conftest):
14 test files with **62 test functions total**.

### Test counts
- **Queue A (Difficulty): 36 tests** — every one of the 18 difficulty instances receives **exactly 2** tests (the ≥2 minimum).
- **Queue B (Corner): 26 tests** — every one of the 26 non-stub corner instances receives **exactly 1** test (the ≥1 minimum).

### Instances skipped (Queue B stubs only — these have `excluded_because:` cross-references to Queue A instances and were not translated, per skill rules):
- `state_machines/error_reservation_no_show_branch_already_covered_by_dual_variant` (cited difficulty: `combinatorial_formula/no_show_fee_nested_rounding_per_seat_first_mode_b` ✓)
- `errors/error_err_outside_booking_window_covered_in_difficulty` (cited difficulty: `priority_pair_validation_conflict/safety_vs_temporal_priority_conflict_guest_suspended_outside_window` ✓; also positively asserted in `boundary_precision_check/window_open_at_boundary_inclusive_on_post_reservations` ✓)
- `errors/error_err_slot_capacity_exceeded_covered_in_difficulty` (cited difficulty: `resource_temporal_overlap/restaurant_slot_capacity_aggregate_seat_sum_half_open_overlap` ✓)
- `errors/error_err_guest_double_booking_covered_in_difficulty` (cited difficulty: `resource_temporal_overlap/guest_double_booking_padded_buffer_60min_pairwise_overlap` ✓)

All four stub cross-references resolve correctly to real Queue A instance names.

### PRD-silence skips: none
No instances were dropped due to PRD silence. Every translated test passes the two-condition filter (verbatim PRD coverage AND unique-derivability), and an automated audit confirms every docstring's quoted PRD substring survives a literal `grep` of `PRD.md` (modulo backticks). Every test docstring ends with exactly one `Design: Difficulty/<rule_id>/<instance.name>` or `Design: Corner/<section>/<instance.name>` line, copied verbatim from the source YAML.

## Step 6: Generate implementation — 2026-05-27T04:58:00Z

Server boots cleanly, returns proper envelopes, the auth gate fires, creates work, and the clock-set endpoint accepts ISO 8601. Notably the timestamps in the data field were set before the clock was advanced (using wall clock at boot — which is correct), and after the clock-set call, subsequent `created_at` would reflect the virtual clock. The `meta.api_request_timestamp` uses wall-clock — also intentional, as it's the request stamp.

Implementation is complete. Here is the report:

---

**Implementation report — task_0017_theme_park_dining_disney_adr**

**Source file structure** (`workspace/implementation/`):
- `start.sh` — bash launcher: `pip install -q -r requirements.txt && exec python3 app.py`
- `requirements.txt` — flask 3.0.3
- `db.py` (32 lines) — `Store` class with 9 in-memory dicts (guests, restaurants, park_sessions, dining_plans, reservations, allergy_meals, lightning_lane_addons, no_show_fee_assessments, credit_ledger_entries) plus a logical `current_utc` clock string
- `errors.py` (44 lines) — `ApiError` + the full 21-entry error catalog from scaffold §1.6
- `response.py` (66 lines) — envelope helpers (`success_object`, `success_array`, `error_response`) matching scaffold §1.0 exactly
- `middleware.py` (29 lines) — `X-User-ID` / `X-User-Role` extraction; `VALID_ROLES = {"Guest", "Restaurant", "PlatformAdmin"}`
- `calculations.py` (192 lines) — resort-timezone helpers (zoneinfo `America/New_York`), `reservation_window_open_utc` (60 days back, 06:00 wall-clock then convert to UTC for DST correctness), 30-min grid alignment, and the two pinned per-seat-rounded `Decimal`+`ROUND_HALF_UP` fee calculations
- `services.py` (165 lines) — id/version/timestamp helpers, ledger append, credit-release helper, cascade utilities (`cascade_cancel_addon_for_reservation`, `cascade_decline_allergy_for_no_show`), `commit_no_show` orchestrator, and `allocate_lightning_lane`
- `app.py` (816 lines) — entry point, error handlers, all 44 declared endpoints + `/` and `/healthz`

**Endpoint count**: 44 declared endpoints implemented (8 Guest/Restaurant CRUD, 5 ParkSession routes, 3 DiningPlan, 11 Reservation routes incl. confirm/cancel/check-in/seat/complete/mark-no-show/party-size, 8 AllergyMeal, 7 LightningLaneAddOn, 4 read-only views for assessments and ledger, 3 ops/clock) plus 2 health endpoints. Flask reports 48 url rules total (44 + 2 health + 1 static + duplicates from URL normalisation).

**Notable design decisions**
- *In-memory layout*: one dict per entity keyed by UUID; cascades scan the dict directly (small N — fine for benchmark workloads).
- *Validation ordering*: enforced inside each route by literally arranging checks in scaffold §1.4 priority order (auth → role → path-404 → FK-404 → state → OCC → business rules). For `POST /reservations` the ladder runs FK existence → guest-suspension → window-open → past-date → hours → grid → capacity → double-booking → park-session match.
- *OCC pattern*: both `expected_reservation_version`-gated endpoints (`/reservations/{id}/cancel`, `/lightning-lane-addons/{id}/allocate`) require the field, type-check it as int, run state check first (priority 5), then OCC (priority 6); LL-allocate also bumps `Reservation.version` per scaffold side-effect note.
- *Cascade pattern*: `commit_no_show` runs the 5-hop side effect in scaffold order; `cancel_park_session` cascades to reservations and then to their LL add-ons (two-hop, each bumping its own version per PRD §2.6); each cascaded child gets its own `bump_version()`.
- *Monetary precision*: all fee math via `Decimal` with `ROUND_HALF_UP`, rounding applied exactly once at the per-seat boundary, then integer multiply by `party_size` — the FORBIDDEN-order divergence example in the scaffold is explicitly avoided.
- *Clock*: `store.current_utc` defaults to real wall-clock; `set_current_utc` overwrites it; every time-sensitive check (`get_current_utc_dt`) reads it; resort-timezone projection uses `zoneinfo("America/New_York")` to correctly compute the 60-day window opener across DST.
- *No seeding*: `Store.__init__` populates only empty dicts and the clock; no entity is created at module-load.

Smoke-tested live: server boots in <2s on port 18017, returns 200 on `/`, 401 on unauthenticated POST, 201 on guest/restaurant create, 200 on clock-set — all with the correct envelope structure.

## Step 7: Run tests and iterate — 2026-05-27T05:15:00Z

All 8 rounds: 62/62 passed. Clean sweep. Exiting per Summary block.

## Summary

**Iterations run**: 2 (one initial baseline sweep + one fix sweep).

**Tests deleted**: none. All failures were test bugs that contradicted PRD, not PRD-silent assertions.

**Fixes applied to `test_helpers/`**: none. No fixture-level fix was needed (the email-default in factories already lowercases the default `guest@example.com`; only ad-hoc per-test emails in `test_13_resource_overlap.py` violated PRD).

**Fixes applied to `test_suite/`**:
- `test_suite/test_07_calculations.py` — `TestLightningLanePerSeatRoundFirst.test_multi_pass_epcot_party_size_3_pinned_ordering`: changed expected `redemption_window_end_utc` from `"2026-02-15T19:30:00Z"` to `"2026-02-15T19:30:00.000Z"`. PRD §2.4 ("ISO 8601 UTC form with three fractional digits and a trailing `Z`") is verbatim — the test's missing `.000` contradicted PRD. Implementation was correct.
- `test_suite/test_11_boundary_precision.py` — `TestLightningLaneExpiryBoundary.test_at_redemption_window_end_sweep_does_not_expire`: same `.000Z` fix for the same PRD §2.4 reason.
- `test_suite/test_13_resource_overlap.py` — `TestRestaurantSlotCapacityAggregateSum.test_overflow_aggregate_seat_sum_returns_capacity_exceeded`: lowercased `capA@x.com`, `capB@x.com`, `capT@x.com` → `capa@`, `capb@`, `capt@`. PRD §3.1 says email must be "lowercase, RFC 5322 form"; the test setup violated the precondition and tripped the PRD-required `ERR_INVALID_REQUEST` lowercase guard.
- `test_suite/test_13_resource_overlap.py` — `TestGuestDoubleBookingPaddedBuffer.test_far_apart_non_overlapping_bookings_succeed`: changed first booking slot from `2026-02-15T12:00:00Z` (07:00 EST, before 08:00 opening) to `2026-02-15T14:00:00Z` (09:00 EST, inside hours), and second from `T20:00:00Z` to `T22:00:00Z` (17:00 EST) so it remains far outside the padded 60-min buffer of the first. PRD §3.3 requires slot inside `[opening_local_time, closing_local_time)` in resort wall-clock; the test was constructing a UTC slot that fell outside the resort window and tripping the PRD-required `ERR_SLOT_OUTSIDE_HOURS`.

**Fixes applied to `implementation/`**: none. Every failing test was a test-side defect; all PRD-required implementation checks (email-lowercase guard, slot-window guard, three-fractional-digit timestamp serialisation) were correct and preserved.

**Final state**: 8/8 parallel rounds × 62/62 tests = 496/496 passes, no flakiness observed.

## Step 8: Finalize PRD — 2026-05-27T05:27:30Z

Report:

## Summary

**PRD.md vs PRD_FINALIZED.md line counts**: 243 / 243 (0.0% line delta — all edits are in-paragraph). Word count delta: 5862 → 6496 (+10.8%); character delta: 41614 → 46396 (+11.5%).

**Changes (one bullet per change)**:

- §2.1 — revise — pinned `X-User-ID` empty/whitespace and unknown `X-User-Role` both produce `ERR_UNAUTHENTICATED`, and pinned that `GET /v1/restaurants/{id}` requires Restaurant role to access only own row — `middleware.py:17-22`, `app.py:328-331`.
- §2.2 — revise — pinned `api_request_id` format as `req_` + 20 chars of uppercase ASCII + digits (length 24) — `response.py:25-27`.
- §2.3 — revise — pinned that non-integer or out-of-range `limit`/`offset` produces `ERR_INVALID_REQUEST`, and pinned `has_more` formula — `app.py:107-114`, `response.py:51`.
- §3.1 (Guest) — revise — pinned email regex `^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$`, `email == email.lower()` requirement, and that uppercase/duplicate/malformed email yields `ERR_INVALID_REQUEST` (HTTP 400) — `app.py:225-236`.
- §3.1 (Restaurant) — revise — pinned that `slot_minutes` must equal 30 if supplied (else `ERR_INVALID_REQUEST`), `closing_local_time > opening_local_time` strictly, and that malformed/invalid field values are `ERR_INVALID_REQUEST` — `app.py:282-304`.
- §3.1 (DiningPlan) — revise — pinned `valid_until > valid_from` strictly with `ERR_INVALID_REQUEST` on violation — `app.py:502-503`.
- §3.2 — revise — pinned ParkSession cancel sets `status = "CANCELLED"` (the fourth permissible status value alongside `NOT_STARTED`/`ACTIVE`/`CLOSED`) and bumps version; non-NOT_STARTED yields `ERR_INVALID_STATE` — `app.py:453-457`, `assertions.py:68`.
- §3.3 — revise — pinned `party_size` integer-and-range and ISO-8601-parse failures as `ERR_INVALID_REQUEST` (occurring before the §2.8 domain ladder); pinned `slot_end_utc` serialised in §2.5 three-fractional-digit `Z` form — `app.py:578-583`, `app.py:205-209`.
- §3.3 — insert — pinned that `slot_start_utc` must carry zero seconds and zero microseconds (else `ERR_SLOT_MISALIGNED`) — `app.py:627-628`.
- §3.4 — revise — pinned that cancel inside the 2-hour window yields `ERR_INVALID_STATE`; pinned that state check runs before OCC per §2.8; pinned PENDING-cancel runs harmless LL-cascade; pinned non-integer `expected_reservation_version` as `ERR_INVALID_REQUEST` — `app.py:801-820`.
- §3.5 — revise — pinned that out-of-window check-in or non-ACTIVE ParkSession yields `ERR_INVALID_STATE` — `app.py:830-842`.
- §3.5 — revise — relaxed `repeat_offender_multiplier` storage spec to allow any JSON-numeric encoding whose decimal value equals the tier constant (impl emits as `float`) — `calculations.py:190`, `services.py:167`.
- §3.6 — revise — pinned non-string `notes` as `ERR_INVALID_REQUEST` and non-list `allergen_codes` as `ERR_INVALID_ALLERGEN` — `app.py:1014-1020`.
- §3.6 — revise — pinned that `decline` requires non-empty `reason` (else `ERR_INVALID_REQUEST`) and is valid from `REQUESTED` regardless of parent reservation status — `app.py:1122-1131`.
- §3.7 — revise — pinned that state checks (add-on `REQUESTED` and parent `CONFIRMED`) run before OCC per §2.8; pinned that allocate ALSO bumps parent `Reservation.version`; pinned non-integer OCC field as `ERR_INVALID_REQUEST` — `app.py:1219-1233`.
- §3.7 — revise — pinned that manual redeem of a non-`ALLOCATED` add-on or one past `redemption_window_end_utc` yields `ERR_INVALID_STATE`; pinned that cancel of a non-`REQUESTED` add-on yields `ERR_INVALID_STATE`; pinned that the SEATED→COMPLETED cascade only flips to `REDEEMED` while still within the window (otherwise stays `ALLOCATED`, awaiting operator expiry sweep) — `app.py:899-907`, `app.py:1249-1271`.
- §3.8 — revise — pinned `set_current_utc` normalises `to_iso8601` into the §2.5 three-fractional-digit `Z` form and returns `data` of shape `{"current_utc": "<normalised ISO>"}`; pinned parse-failure as `ERR_INVALID_REQUEST` — `app.py:1360-1367`.

**Step 7 diff items reviewed**:
- `.000Z` fractional-digit serialisation (test_07, test_11): PRD §2.4 already verbatim-pins "three fractional digits and a trailing `Z`". No edit needed.
- Lowercase email guard (test_13): PRD §3.1 already pins "lowercase, RFC 5322 form". Added explicit regex and error code as the impl pin.
- Slot-inside-hours wall-clock check (test_13): PRD §3.3 already pins. No edit needed.

All Step 7 fixes were test-side; no implementation behavior diverged from PRD-required text. Patch focuses on the broader set of PRD silences pinned by the implementation.
