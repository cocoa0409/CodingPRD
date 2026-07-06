# Worklog — task_0698_wine_brewery_food_tour

## Step 1: Create Task Directory — 2026-06-29T02:38:01.000Z

Skipped scanning/indexing per orchestrator instruction. Task directory `tasks/task_0698_wine_brewery_food_tour/` with `workspace/` subdir was pre-created by the orchestrator. Verified both exist and `workspace/` is empty. `INSTRUCTION.md` confirmed present at project root. Difficulty for Step 2: **Expert**.

## Step 2: Generate Scaffold (Expert) — 2026-06-29T03:00:29.000Z

Generated the three Expert-tier scaffold artifacts for **task_0698_wine_brewery_food_tour** from the verbatim scenario and the scaffold-generator spec only (no sibling tasks consulted). All three files written to `tasks/task_0698_wine_brewery_food_tour/`:
- **SCAFFOLD.yaml** (§1.0–§1.7, no design keys) — 1191 lines
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** (single key `scaffold_difficulty_design`) — 1380 lines
- **SCAFFOLD_CORNER_DESIGN.yaml** (single key `scaffold_corner_design`) — 1442 lines

### Counts (Expert tier: 10–15 entities / 20–32 endpoints / 18–30 validations / 3+ calcs / 4+ state machines)
- **Entities: 10** — TourProduct, AddOn, Vehicle, PartnerVenue, PickupPoint, Departure, Stop, VenueConfirmation, Guest, Booking
- **Endpoints: 46** (44 business + 2 test-driving `/_clock/set_current_utc`, `/_verify/age`). Endpoint-rich because the four state machines are action-heavy; redundant sub-resource GETs trimmed.
- **Validations: 23** (priority-ordered)
- **Calculations: 4** — `booking_price_quote` (tiered group pricing, round-per-person-then-multiply), `gratuity_amount` (circular-looking dep, charter excluded from base), `partner_commission` (dual-variant estimated vs settled), `cancellation_refund` (lead-time tiers + weather override)
- **State machines: 4** — TourProduct (linear), VenueConfirmation (cyclic revision loop), Departure (branching weather/ops cancel), Booking (parallel status × payment_status dimensions)
- Errors: 24; Roles: 5 (Operator/Guide opaque, PartnerVenue/Guest entity_backed, Anonymous); 1 OCC concurrency rule on `Departure.version`

### Quality gates
- `scaffold_lint.py` → **VERDICT: clean lint** (469 §1.8+§1.9 calls conform to §1.5; all 11 FKs have reverse-reachability GETs).
- §1.8: all 9 difficulty rules × 2 instances = **18 instances**, each grounded with literal-computed asserts.
- §1.9: **33 active corner instances + 7 `excluded_because` stubs** across all 9 claim-extraction sections; all stub references resolve to real §1.8 instance names; all instance names unique across both design files.
- `api_prefix` is `/` (flat topology) — many peer top-level collections, no single nesting resource.

## Step 3: Copy Shared Files — 2026-06-29T03:00:29.000Z

Copied `INSTRUCTION.md` (1424 bytes) from project root to `tasks/task_0698_wine_brewery_food_tour/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-29T03:06:02.000Z

Generated `workspace/PRD.md` (272 lines, 40585 bytes) from `SCAFFOLD.yaml`. Neither design YAML read.

**Sections covered:**
- §1 Introduction (3 paragraphs, business-context angle)
- §2 Global Specifications — 10 subsections: 2.1 RBAC (all 5 roles + identity translation for entity-backed `PartnerVenue`/`Guest` and opaque `Operator`/`Guide`/`Anonymous`), 2.2 Response Structure, 2.3 Pagination, 2.4 Common Properties/Versioning, 2.5 Logical Clock, 2.6 Precision/Rounding, 2.7 OCC on seat reservation, 2.8 Cascades/Atomicity, 2.9 Lookup & Validation Ordering, 2.10 Enumerations
- §3 Business Logic — 8 lifecycle-organized subsections (catalogue, fleet/pickup/venues, departure scheduling, venue confirmation loop, guest clearing, booking lifecycle + seat pool, pricing/gratuity/refund/commission, departure run + cancel cascades)
- §4 Endpoint Definitions (4-column table, 46 rows)
- §5 Error Code Catalogue (2-column table, 24 rows)

**Hard Contract reports (PASS):** Contract 1 field coverage 51/51; Contract 2 rule coverage (validation orderings, OCC, 4 state machines, 4 calculations, cascades, sibling-branch symmetry) all 0 missing; Contract 3 path purity in §3 (306 backtick tokens scanned, 0 path-like). Confirmed neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was read.

## Step 5: Generate Unit Tests — 2026-06-29T03:20:02.000Z

Generated complete test infrastructure for **task_0698_wine_brewery_food_tour** (Expert tier).

### Test helpers (Stage 1) — 9 files written to `test_helpers/`
`__init__.py` (barrel), `types.py` (10 entity TypedDicts + 11 status/role enums), `api_client.py` (one method per endpoint), `api_errors.py` (`ApiErrorId` enum + HTTP-status map), `assertions.py` (per-entity + `assert_booking_quote` invariant), `factories.py` (one payload factory per entity), `constants.py` (pricing tiers, refund lead-time hours, gratuity/commission ceilings, revision limit, clock default), `test_users.py` (shared role headers + `make_*` builders, entity-backed identity for PartnerVenue/Guest), `fixtures.py` (composite setups).

### Test suite (Stage 2) — 10 test files, **69 test functions**
- **Queue A (Difficulty): 36 tests** — 18 instances × 2 tests each (primary in test_03–09, complements in test_10).
- **Queue B (Corner): 33 tests** — all 33 non-stub instances, ≥1 test each.

### Coverage audit (all green)
All 18 difficulty instances ≥2 tests; all 33 non-stub corner instances ≥1 test; all 7 `excluded_because:` stubs NOT translated (cross-refs resolve); every `Design:` tag resolves; every docstring carries verbatim PRD citation; no scaffold leakage; no skip/xfail/placeholders.

### Instances skipped: 0
No instance failed the PRD-first filter. Pre-computed values (1440/720 commission, 60300/96800/16524/113324 quotes, 71154/35577 refunds, 17936 at 48h boundary) independently reproduced and confirmed PRD-consistent.

## Step 6: Generate Implementation — 2026-06-29T03:20:02.000Z

Generated complete Python + Flask implementation in `workspace/implementation/`.

### Files (25 Python source files + start.sh + requirements.txt)
- **Foundation**: `start.sh`, `requirements.txt`, `app.py`, `db.py` (in-memory store), `errors.py`, `response.py`, `middleware.py` (auth/RBAC), `validate.py`, `serialize.py`, `records.py`, `clock.py`, `util.py`.
- **routes/**: `admin.py` (`/_clock/set_current_utc`, `/_verify/age`), `tour_products.py`, `add_ons.py`, `vehicles.py`, `partner_venues.py`, `pickup_points.py`, `guests.py`, `departures.py`, `stops.py`, `venue_confirmations.py`, `bookings.py`.
- **services/**: `pricing.py` (tiered quote, gratuity, commission, refund), `departures.py` (derived seat/headcount figures).

### Endpoints: 46 route handlers (all PRD §4 rows).

### Startup contract confirmed
`start.sh` reads `$PORT` (default 10000), binds `0.0.0.0`, runs FOREGROUND via `exec python3 app.py`. Storage in-memory only (dicts in `db.py`); no seeding; clock defaults `2026-03-01T00:00:00Z`; state wipes on every boot. Boot-to-ready ~0.24s. Self-verified ~75 end-to-end assertions across auth/envelope/lifecycle/OCC/pricing/cascades/refund-boundaries — all passed.

Design note: `seats_taken`/`expected_headcount` computed on read (sum over bookings) per PRD §3.3; `Departure.version` bumps on reserve/cancel per state-machine side effects.

## Step 7: Run Tests and Iterate — 2026-06-29T03:31:02.000Z

Clean 8-round sweep achieved. Final report below.

**Iterations run:** 2 (baseline sweep → diagnose/fix → confirming sweep).

**Baseline:** All 8 rounds were stably 67/69 — the same 2 tests failed in every round (not flaky; a deterministic precedence-ordering disagreement):
- `test_state_beats_fiscal_on_reserve_terminal_departure` (test_08_cross_entity_and_validations.py)
- `test_state_check_precedes_capacity_on_completed_departure_reserve` (test_10_difficulty_complements.py)

Both failed identically: `Expected error_id 'ERR_DEPARTURE_NOT_BOOKABLE', got 'ERR_INVALID_STATE'`.

**Root cause (diagnostic STEP 1b — ERROR PRECEDENCE SILENCE):** Both tests create a DRAFT booking, then cancel its *departure* (cancel-ops / cancel-weather) to make the departure non-SCHEDULED, then reserve the booking expecting the departure-state check (`ERR_DEPARTURE_NOT_BOOKABLE`) to beat the capacity check. But PRD §3.8 mandates that the cancel cascade move "every non-terminal booking" — which includes the DRAFT booking — to CANCELLED. So at reserve time the booking is itself terminal. PRD §3.6's reserve precedence enumerates checks starting with the departure-SCHEDULED check but never names or orders a booking-own-state guard. Thus two PRD-faithful readings exist: check the URL-path booking's own state first → `ERR_INVALID_STATE` (the implementation's choice, traceable to PRD §5's `ERR_INVALID_STATE` "Resource not in a state that permits this transition"), or check departure state first → `ERR_DEPARTURE_NOT_BOOKABLE`. PRD does not uniquely determine which wins, and both map to HTTP 409.

**Resolution (the protocol's prescribed remedy for ERROR PRECEDENCE SILENCE):** Relaxed both assertions from an exact `validate_error(..., ERR_DEPARTURE_NOT_BOOKABLE)` to `validate_error_is_one_of([ERR_DEPARTURE_NOT_BOOKABLE, ERR_INVALID_STATE])`, retaining an explicit `status_code == 409` check (both errors are 409). This is the permitted exception to the no-weakening rule because the PRD supports both members of the set.

**Fixes applied to `test_suite/`:**
- `test_suite/test_08_cross_entity_and_validations.py` — `test_state_beats_fiscal_on_reserve_terminal_departure`: relaxed assertion to `validate_error_is_one_of([ERR_DEPARTURE_NOT_BOOKABLE, ERR_INVALID_STATE])` + 409 check; added `validate_error_is_one_of` import.
- `test_suite/test_10_difficulty_complements.py` — `test_state_check_precedes_capacity_on_completed_departure_reserve`: same relaxation + 409 check; added import.

**Fixes applied to `test_helpers/`:** None needed.

**Fixes applied to `implementation/`:** None — the implementation's `ERR_INVALID_STATE` on reserving a cascade-cancelled booking is PRD-faithful; no PRD-required check was added, removed, or weakened.

**Tests deleted:** None.

**Final result:** Fresh 8-round parallel sweep — all 8 rounds 69/69, no union failures, no flakiness.

**Orchestrator re-verification:** results.{1..8}.json were cleaned by the fix subagent; orchestrator re-ran the full 8-round parallel sweep at 2026-06-29T03:30 — all 8 rounds 69/69, 0 failures. Evidence files `workspace/implementation/results.{1..8}.json` now persisted.

## Step 8: Finalize PRD — 2026-06-29T03:33:37.000Z

Not skipped (Step 7 applied 2 `test_suite/` fixes). Produced `workspace/PRD_FINALIZED.md`.

**Line counts:** PRD.md 272 → PRD_FINALIZED.md 272 (0 line delta; 2 content lines revised, ~0.7%).

**Changes:**
- **§3.6 "Reserving seats"** — *revise* — Inserted sentence pinning that reserve first checks the booking's own status must be `DRAFT`, else `ERR_INVALID_STATE`, evaluated before the departure/age/charter/capacity/version checks. — `implementation/routes/bookings.py:150-151` preceding `:162-163`.
- **§3.6 reserve-precedence paragraph** — *revise* — Prepended the booking-own-state `DRAFT` check (`ERR_INVALID_STATE`) as first step in the deterministic reserve-time ordering, ahead of the departure-SCHEDULED check. — `implementation/routes/bookings.py:150-151`, `:162-189`.

**Why only this edit:** Step 7's two failing tests revealed an error-precedence silence — DRAFT booking, cancel its departure (PRD §3.8 cascade sweeps DRAFT→CANCELLED), then reserve. PRD §3.6 enumerated reserve precedence from the departure-SCHEDULED check but never ordered a booking-own-state guard; impl pins the booking-own-state-first reading (`ERR_INVALID_STATE`, already 409). No error-catalogue or endpoint change needed.

**Pre-edit search log:** Both edits' subject = reserve-time guard on URL-path booking's own status + precedence. Enumerated impl paths: `routes/bookings.py:137-197` (reserve sequence: own-state 150-151 → departure-SCHEDULED 162-163 → age 166-168 → charter 173-181 → capacity 184-185 → OCC 188-189; field validation 146-147; quote recompute 158); `:200-274` (pay/check-in/cancel own-state guards — confirms uniform own-state-first pattern); `routes/departures.py:235-299` (cancel cascade DRAFT→CANCELLED). Adjustment: scoped precedence claim to "the departure, age, charter, capacity, or version checks below" (not "all other checks") so it doesn't contradict §2.9 structural field-presence validation of `expected_departure_version` which runs before the guard.

## Step 9: Complete PRD — 2026-06-29T03:38:43.000Z

Always runs. Produced `workspace/PRD_COMPLETED.md` from `PRD_FINALIZED.md`.

**File deltas:** Lines 272 → 272 (all in-paragraph); chars 41,127 → 43,867 (+2,740).

**Change counts:** 14 changes — **14 ambiguity-pins, 0 mismatch-revisions** (no PRD passage contradicted impl; every gap was silence where impl makes a definite choice, chiefly the error code + check-order for invalid state-machine transitions).

**Per-change log:**
- §2.1 RBAC — insert — ambiguity — unrecognized `X-User-Role` rejected with `ERR_UNAUTHENTICATED` (not `ERR_FORBIDDEN_ROLE`) — middleware.py:37,69
- §2.3 Pagination — insert — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_PAGINATION` — validate.py:122-133
- §2.4 Versioning — insert — ambiguity — `version` initial value is 1 — records.py:11
- §3.1 Tour product lifecycle — insert — ambiguity — publish on non-`DRAFT` / retire on non-`PUBLISHED` → `ERR_INVALID_STATE`; retire status check precedes active-departure check — tour_products.py:86-106
- §3.3 Stops — insert — ambiguity — add stop to non-`SCHEDULED` departure → `ERR_INVALID_STATE`, after structural/range, before duplicate-sequence — stops.py:37-48
- §3.4 Venue confirmation moves — insert — ambiguity — owner check precedes state-machine check; request-changes requires `decline_note`; decline records note only if present — venue_confirmations.py:83-144
- §3.4 Resubmit — insert — ambiguity — resubmit from non-`CHANGES_REQUESTED` → `ERR_INVALID_STATE`, before revision-limit check — venue_confirmations.py:116-121
- §3.6 Paying — insert — ambiguity — pay from non-`RESERVED` → `ERR_INVALID_STATE` (first); non-`UNPAID` payment_status likewise — bookings.py:206-209
- §3.6 Checking in — insert — ambiguity — check-in from non-`PAID` → `ERR_INVALID_STATE`, before departure-status check — bookings.py:229-234
- §3.6 Cancelling — insert — ambiguity — cancelling terminal booking → `ERR_INVALID_STATE` — bookings.py:251-252
- §3.8 Confirming — insert — ambiguity — confirm from non-`SCHEDULED` → `ERR_INVALID_STATE`, before three preconditions — departures.py:149-150
- §3.8 Departing — insert — ambiguity — depart from non-`CONFIRMED` → `ERR_INVALID_STATE`, before timing guard — departures.py:180-185
- §3.8 Completing — insert — ambiguity — complete from non-`DEPARTED` → `ERR_INVALID_STATE`, before timing guard — departures.py:210-215
- §3.8 Cancel-weather/cancel-ops — insert — ambiguity — `cancel_reason` required non-empty; cancel from non-`SCHEDULED`/`CONFIRMED` → `ERR_INVALID_STATE` — departures.py:245-281

**Already-pinned (no change):** clock-set 200 + empty data; `/_verify/age` returns guest; reserve-time check order; pricing/gratuity/commission/refund formulas + round-then-multiply; derived `seats_taken`/`expected_headcount` on read; set-status enum validation; FK/auth/validation precedence (§2.9).

---

## Pipeline complete — 2026-06-29T03:38:43.000Z

All 9 steps executed. Final 8-round parallel per-test-server stability sweep: **all 8 rounds 69/69 green, 0 failures**. Deliverables present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/, test_suite/ (69 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/, results.{1..8}.json}.
