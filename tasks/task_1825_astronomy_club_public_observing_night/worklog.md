# Worklog — task_1825_astronomy_club_public_observing_night

## Step 1: Create Task Directory — 2026-08-14T19:03:00.000Z

Directory `tasks/task_1825_astronomy_club_public_observing_night/` and `workspace/` pre-created by the invoking pipeline (index 1825 assigned externally). No action taken by orchestrator.

## Step 2: Generate Scaffold — 2026-08-14T19:25:00.000Z

## Task 1825 — Astronomy Club & Public Observing Night: scaffold complete

**Files written** (all three, in `/home/ubuntu/github/CodingPRD/tasks/task_1825_astronomy_club_public_observing_night/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no `scaffold_difficulty_design`/`scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Counts:**
- **Entities: 13** (MembershipTier, Member, DuesInvoice, DuesPayment, Telescope, TrainingCertification, LoanReservation, MaintenanceTicket, ObservingEvent, EventOperatorAssignment, GroupVisitBooking, SkyQualityReading, DarkSkyReport)
- **Endpoints: 67** (including `POST /club/_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`)
- **Error codes: 23**
- **State machines: 10** (4 non-linear: Member ACTIVE↔SUSPENDED/LAPSED cycle, Telescope AVAILABLE↔MAINTENANCE cycle, MaintenanceTicket IN_PROGRESS↔VERIFICATION cycle, ObservingEvent DRAFT↔SCHEDULED + CONFIRMED→SCHEDULED coverage-lapse revert)
- **Calculations: 7**, of which **dual-variant: 2** (dues_proration full/mid-year; overdue_fee provisional/final-with-cap; dark_sky_median provisional/final — 3 calcs carry variants)
- **§1.8 instances: 18** (exactly 2 per rule for all 9 rule_ids; each rule's two instances honor its differentiation clause — e.g., half-open loan-window vs closed-touch operator-overlap interval semantics; state-vs-temporal and safety-vs-temporal error pairs; suspension-triggered depth-3 vs revocation-triggered cascade)
- **§1.9 instances: 29** (28 active + 1 `excluded_because` stub), spanning entities/state_machines/calculations/validations/endpoints/errors/roles/cross_cutting_layers/consistency_model sections

**Difficulty mechanisms layered per the requester's "harder than Expert" brief:** dual-variant calcs where two prose readings yield different cents (30247 vs 120000; uncapped 11500 vs capped 10000); 3-hop cascades (clock → Member suspend → assignment WITHDRAWN → event CONFIRMED→SCHEDULED); validation priority conflicts with pinned winners; boundary checks at exactly 40/41 moon pct, exactly-60 group capacity, grace-day == vs +1; half-open vs closed-touch overlap semantics on different resources; OCC on both ObservingEvent.confirm and Telescope update.

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (405 calls scanned). Additionally verified: no forbidden concurrency vocabulary, all 23 errors wired to ≥1 validation/transition, unique instance names across both design files, zero unbound `${var}` placeholders, and all formula-derived asserts pre-computed as literals.

One design note: loan-window overlap (p12) is pinned to the *borrowing member's own* schedule rather than per-telescope, because telescope-level double-booking is already structurally prevented by p11 (a telescope with a live reservation is never AVAILABLE) — this keeps both validations reachable and testable.

## Step 3: Copy Shared Files — 2026-08-14T19:26:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1825_astronomy_club_public_observing_night/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T19:33:00.000Z

PRD generated and audited. Final summary below.

---

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1825_astronomy_club_public_observing_night/workspace/PRD.md`
**Line count:** 323 lines

### Section list

- **§1. Introduction** — 2 paragraphs (club operations pain points → scope of API)
- **§2. Global Specifications & System-Wide Principles**
  - 2.1 User and Role-Based Access Control
  - 2.2 API Response Structure (verbatim canonical block)
  - 2.3 Pagination
  - 2.4 The Logical Clock and Time-Driven Automation
  - 2.5 Common Resource Properties (incl. DuesPayment/SkyQualityReading `common_fields:false` exception)
  - 2.6 Nested Resource Retrieval and Referential Existence
  - 2.7 Monetary Values, Precision, and Rounding
  - 2.8 Optimistic Concurrency Control (both rules: `expected_event_version`, `expected_telescope_version`)
  - 2.9 Temporal Windows: Half-Open and Closed-Touch Semantics
  - 2.10 Validation Ordering
  - 2.11 Domain Enumerations
- **§3. Business Logic & Workflows** (10 subsections)
  - 3.1 Membership Tiers, Registration, and Dues Standing
  - 3.2 The Telescope Fleet: Registry, Condition, and Collimation
  - 3.3 Maintenance Tickets and the Repair Cycle
  - 3.4 The Telescope Loan Program (with ordered 5-check battery)
  - 3.5 Training and Certification
  - 3.6 Observing Events: Scheduling, Coverage, Weather, and Completion
  - 3.7 Staffing Public Nights: Operator Assignments and No-Show Strikes
  - 3.8 Group Visits: Booking, Capacity, and Deposits
  - 3.9 Sky-Quality Measurement and Dark-Sky Reporting
  - 3.10 Role-by-Role Operating Summary
- **§4. Endpoint Definitions** — 68 endpoints in 4-column table (Method | Path | Description | Authorized Role(s))
- **§5. Error Code Catalogue** — 23 errors in 2-column table (Error ID | HTTP Status Code)

### Hard Contracts — all PASS

- **Contract 1 (Field-Name Coverage):** 62 required identifiers (entity fields + endpoint input/query/path params), 62 present in backticks, 0 missing. PASS.
- **Contract 2 (Rule Coverage):**
  - validations[] with priority ordering: 22 rules checked; ordered validation cascade stated in §2.10; explicit per-endpoint priority statements present in §3.1 (payment sufficiency, resign outstanding-loans), §3.4 (5-check loan battery in order), §3.6 (3-gate confirm battery in order), §3.8 (standing then throttle for booking creation). All expressed in prose.
  - concurrency_rules[] OCC rejections: 2 of 2 expressed (`POST .../confirm` requiring `expected_event_version` → `ERR_STALE_VERSION` HTTP 412; `PUT .../telescopes/{id}` requiring `expected_telescope_version` → `ERR_STALE_VERSION` HTTP 412), each naming write-endpoint behavior, occ_field, error_id, http_status.
  - state_machines[].transitions: all 38 transitions across 10 state machines fully expressed (from/to states named, preconditions paired with error ids, side effects stated, including cascades for suspension, resignation, certification revocation, weather auto-cancel, coverage lapse, completion).
  - calculations[]: all 8 expressed in precise business narrative (dues_proration with both variants and single-round-half-up rule; overdue_fee with provisional/final variants, 2-day grace, 500-cent daily rate, 10000-cent final cap, inclusive boundary; operator_coverage with `>=` boundary; group_deposit with marginal 10/30 tier structure and 22000-cent worked example; dark_sky_median with half-open window, odd/even variants, 2-decimal half-up rounding on even branch only, A–F banding with inclusive edges; no_show_strikes with rolling 365-day window, mark-instant then created_at tiebreak, inclusive window start, throttle limit 2; membership_clock_thresholds with 7-day grace, 37-day lapse, 180-day collimation, 40% moon, 70% weather, 60-attendee capacity; condition_score_reconcile with full recompute over CLOSED set, floor 0, collimation reset).
  - validations[] conditions: every error_id matchable to its trigger condition in §2/§3 prose (mechanical check confirmed all 23 error ids present in §2+§3).
  - endpoints[].side_effects / applies_to: all expressed (e.g., weather-check auto-cancel at >=70; payment posting reviving LAPSED member; retire cascade closing non-CLOSED tickets; checkout/return stamping checkout_at/returned_at and toggling telescope status).
  - entities[].fields[] structured content: defaults and initial values reconstructible from prose (Member.status initial `ACTIVE`, `dues_paid_through = joined_at`, `effective_access_level` rule, Telescope.condition_score=100, `collimation_due_at = created_at + 180 days`, ObservingEvent.weather_cancellation_pct initialized 0, invoice `amount_cents` read-only, etc.).
  - sibling-branch symmetry: parallel branches (resign from ACTIVE vs SUSPENDED; retire from AVAILABLE vs MAINTENANCE; cancel from SCHEDULED vs CONFIRMED; return with vs without damage_reported) rendered with equal density.
- **Contract 3 (§3 Path Purity):** 402 backticked tokens inside §3; 0 start with `/`; 0 bare HTTP methods; 0 method+path combos. PASS. All endpoints in §3 referenced via state-transition framing, role+verb, or capability description.

Zero-Silence Rule confirmed: every scaffold element (entities, state machines, calculations, validations, endpoints, errors, roles) has verbatim-rule coverage in the prose. The two withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened or consulted.

## Step 5: Generate Unit Tests — 2026-08-14T19:55:00.000Z

## Test counts

- **Queue A (Difficulty):** 17 of 18 instances covered with ≥2 tests each (34 tests).
- **Queue B (Corner):** all 28 non-stub instances covered with ≥1 test (28 tests); 1 stub (`errors/err_stale_version_covered`) not translated per spec — its `excluded_because` pointer names "stale_telescope_version_rejected", which is a corner-section instance (not a difficulty one), but that instance IS translated and owns the ERR_STALE_VERSION assertion, so the error is covered.
- **Total: 62 tests**, all collected cleanly by pytest, all with exactly one `Design:` tag resolving to a real instance, all PRD citations verbatim-verified by literal grep against PRD.md.

## Skipped instance (PRD-first two-condition filter)

- **`Difficulty/priority_pair_validation_conflict/safety_vs_referential_on_solar_confirm`** — fails **unique derivability**. The instance asserts that a SOLAR_SESSION confirm failing both the solar-operator gate and the weather gate surfaces `ERR_NO_SOLAR_CERTIFIED_OPERATOR` (scaffold priority p8 < p20). But PRD §3.6 pins the opposite evaluation order verbatim: "First, operator coverage… Second, weather: the latest `weather_cancellation_pct` must be strictly below 70; at 70 or above the confirm is rejected with `ERR_WEATHER_RISK` (HTTP 422). Third, solar safety…". A PRD-faithful implementer surfaces `ERR_WEATHER_RISK` when both gates fail, so the asserted outcome contradicts the contract. Gap left as a gap (no weakened variant emitted).

## test_helpers/ (Stage 1)

`/home/ubuntu/github/CodingPRD/tasks/task_1825_astronomy_club_public_observing_night/test_helpers/`:
- `__init__.py` — barrel export (framework generics + PRD-specific)
- `types.py` — 13 entity TypedDicts (append-only `DuesPayment`/`SkyQualityReading` correctly omit `updated_at`/`version`), status/class/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (44 methods incl. the logical clock)
- `api_errors.py` — 23 `ApiErrorId` values + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + append-only field-absence checks
- `factories.py` — payload factories (input fields only, PRD-exact names)
- `constants.py` — thresholds (grace 2d/500c/10000c cap, grace 7d, lapse 37d, collimation 180d, moon 40, weather 70, capacity 60, grades, deposit tiers, default clock)
- `test_users.py` — opaque role constants + `make_member_headers(member_id)` per-instance builder for the entity-backed Member role
- `fixtures.py` — composite helpers (tiers/members, paid-dues ledger, certified member+scope, reserved/checked-out loans, scheduled/confirmed/completed events, invite-and-accept operators, group bookings, readings, reports, ticket lifecycle), all threading `make_member_headers` for ownership-gated calls

## test_suite/ (Stage 2)

`/home/ubuntu/github/CodingPRD/tasks/task_1825_astronomy_club_public_observing_night/test_suite/`:
- `conftest.py` — session-scoped `api` + per-role header fixtures
- `test_01_members_tiers_and_rbac.py` — member creation defaults, 404, pagination envelope, 4 RBAC/auth denials
- `test_02_dues_billing.py` — proration dual-variant (30247 vs 120000), payment sufficiency, credit conservation, append-only payments
- `test_03_loans_and_overdue_fees.py` — provisional-uncapped vs final-capped fee (11500/10000), grace boundary (0 @ 2d, 500 @ 3d), half-open loan overlap, standing gate, availability conservation, invalid transitions, collimation gate, loan cap
- `test_04_fleet_maintenance.py` — verification cycle + delta-applied-once (95), retire cascade (70), cross-ticket recompute (85), cert-revocation cascade (matched cancelled / unmatched untouched), damage-return consistency, telescope OCC
- `test_05_events_scheduling_and_confirmation.py` — moon 40/41, daylight gate, terminal lockdown, unschedule cycle, weather auto-cancel cascade, completion cascade, confirm gate ordering (state→coverage→weather), event OCC
- `test_06_operators_and_groups.py` — closed-touch operator overlap (+ non-touching accept), marginal deposit tiers (22000 / 0), capacity exact-fill (60 pass / 61 fail), booking-confirm event-state dependency, no-show throttle (2 strikes → ERR_NO_SHOW_THROTTLED), resignation guard
- `test_07_dark_sky_reports.py` — provisional recompute vs frozen final (21.40/B), SQM range 23.50 reject / 22.99 accept, even-count median 21.50→A with half-open period_end exclusion
- `test_08_member_lifecycle_cascades.py` — suspension drops access to 0, reinstatement restores it, depth-3 cascade (SUSPENDED → WITHDRAWN → event falls back to SCHEDULED), suspension cancels RESERVED loan + releases telescope

## Step 6: Generate Implementation — 2026-08-14T19:55:00.000Z

Implementation complete and verified. All files live under `/home/ubuntu/github/CodingPRD/tasks/task_1825_astronomy_club_public_observing_night/workspace/implementation/`.

## File list

- `start.sh` — launcher (executable)
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask entry point: blueprint registration, global request lock, `ApiError`/404/405/exception handlers emitting the envelope, binds `0.0.0.0:$PORT` (default 10000)
- `store.py` — in-memory dicts keyed by id, logical clock pinned at `2026-08-01T00:00:00Z`, monotonic insertion sequence. **Empty at boot; no seeding anywhere.**
- `helpers.py` — `ApiError`, success/error envelope (`meta.api_request_id`/`api_request_timestamp` with 3-fractional-digit ISO, `response_type`, `data`), auth (`X-User-Role`/`X-User-ID`, 401/403), typed field validators, body-FK existence (404), pagination (`limit` 1–100 default 10, `offset` default 0, `total_count`, `has_more`; lists sorted `created_at` ascending)
- `domain.py` — pinned constants, all 8 scaffold calculations (dues proration with single final round-half-up and 365-day full-period variant, overdue fee 2-grace-days/500-per-day/10000-cap with provisional-uncapped vs final-capped, operator coverage, marginal group deposit, dark-sky median + grade bands, rolling 365-day no-show strikes, membership clock thresholds, condition-score full recompute), cascades, and clock-driven automatic transitions
- `views.py` — serializers emitting exactly the scaffold-declared fields (payments/readings get only `id` + `created_at`, no `updated_at`/`version`)
- `routes/core.py` — clock set, tiers, members (reinstate/resign with cascades), dues invoices, dues payments with member-credit ledger and LAPSED→ACTIVE revival
- `routes/equipment.py` — telescopes (OCC-guarded PUT, retire incl. MAINTENANCE write-off cascade), maintenance ticket cycle, certifications (revoke cascade), loans (5-gate creation battery in PRD §3.4 order, checkout/return/cancel)
- `routes/events.py` — observing events (moon/daylight schedule gates, OCC-guarded confirm with coverage→weather→solar gate order per PRD §3.6, weather auto-cancel at ≥70, coverage-lapse fallback CONFIRMED→SCHEDULED), operator assignments (closed-interval overlap), group bookings (capacity 60, deposit), readings, dark-sky reports (provisional vs frozen)

## How to boot

`bash start.sh` from `implementation/`: guarded dep install (`if ! python3 -c "import flask"` — no-op once Flask present, safe for concurrent per-test reboots), then `exec python3 app.py` in the foreground on `0.0.0.0:$PORT`. Verified: fresh boot has empty collections and clock at the pinned default; all 67 endpoints implemented.

## Verification

Three smoke suites (~120 assertions) run green against live boots covering: auth/role/ownership ordering, envelope shape, proration (incl. leap-year 366-day case), payment credit (`credit_applied_cents`), suspension/lapse boundaries and cascades, reinstate gating, OCC 412s, loan gate ordering, half-open loan-window touch (legal) vs closed-touch operator overlap (409), overdue provisional-vs-final fees and cap, ticket cycle with condition recompute and collimation reset, retire write-off floor at 0, weather/solar/moon gates and boundaries (20:00:00 inclusive, 20:00:01 rejected), coverage lapse fallback, capacity boundary (60 passes, 61 fails), strike throttle at 2 and 365-day roll-off, half-open report window (reading exactly at `period_end` excluded), median even/odd + grade bands, freeze after finalize, pagination meta and 400s.

## PRD ambiguities resolved

1. **Group booking `mark-no-show` is unreachable under literal rules** — completion cascades all CONFIRMED bookings to COMPLETED, and confirm requires a SCHEDULED/CONFIRMED host. I implemented both rules verbatim (the transition exists and works if the state ever occurred; operator no-show *is* reachable since completion leaves assignments CONFIRMED).
2. **Error choice where the catalog has no specific code**: duplicate email → `ERR_INVALID_REQUEST` (400); payment `member_id` ≠ invoice member → 400; booking on non-PUBLIC_NIGHT event → 400; checkout outside window / complete before window_end / retire with blocking loans / reinstate while dues not current → `ERR_INVALID_STATE` (409).
3. **Damage-return auto-ticket fields unspecified** — opened with `kind=REPAIR`, `severity=MEDIUM`, `condition_delta=0`, status OPEN (flows through the normal cycle).
4. **Pagination bounds** — `limit` 0 or >100 and negative/non-integer `limit`/`offset` rejected with 400 ("accepts a minimum of 1, and a maximum of 100").
5. **Ownership enforcement (PRD §2.1 + "acts on its own")** — Member-role creates/actions with mismatched FK (`member_id`, `contact_member_id`, `taken_by_member_id`, path id on resign) → 403, checked after FK existence.
6. **Clock set backward** — allowed, fires nothing (transitions fire only when preconditions are satisfied).
7. **Clock-jump pasting both dues thresholds** — suspension (with cascades) fires first, then lapse, matching PRD "move from ACTIVE to SUSPENDED and later to LAPSED" so the suspension cascades are not skipped.
8. **`advocacy_grade` with zero readings** — null alongside `median_sqm` (bands are undefined without a median).
9. **Weather auto-cancel version bump** — weather record and cancel transition each bump the event version (+2 total); all other single mutations bump +1 per PRD §2.5.
10. **Entity timestamps use the logical clock** (deterministic, matches `collimation_due_at = created_at + 180d` derivations); `meta.api_request_timestamp` uses wall UTC.

## Step 7: Run Tests and Iterate — 2026-08-14T20:25:00.000Z

All 8 rounds pass 62/62. Exit condition met.

## Summary

**Iterations run:** 2 (iteration 1: initial sweep hit a transient infrastructure kill at startup — all 8 servers SIGKILLed ~1s in, likely host contention from ~11 concurrent pipeline processes; a single diagnostic round gave 58/62 with 4 failures. Iteration 2: full 8-round parallel sweep after fixes → **62/62 passed in all 8 rounds**).

**Tests deleted:** None.

**Implementation changes:** None — the implementation was PRD-correct in all four failures.

**test_helpers changes:** None.

**test_suite fixes (4 test bugs):**

1. `/home/ubuntu/github/CodingPRD/tasks/task_1825_astronomy_club_public_observing_night/test_suite/test_01_members_tiers_and_rbac.py` — `test_member_accept_only_own_assignment`: `NameError: create_telescope` — the name was used but missing from the `test_helpers` import list. Added it. The rule under test ("Only the invited Member may respond"; ownership compares `member_id` to `X-User-ID`) is PRD-verbatim (§3.7, §2.1); test logic was faithful, import was missing.

2. `/home/ubuntu/github/CodingPRD/tasks/task_1825_astronomy_club_public_observing_night/test_suite/test_02_dues_billing.py` — `test_overpayment_creates_credit_and_settles_invoice`: asserted raw-string equality `dues_paid_through == "2027-08-01T00:00:00Z"`, but the server serializes with the PRD §2.5-mandated three fractional digits (`...00.000Z`). The PRD-covered rule is instant equality with the invoice's `period_end`; the exact string format was not uniquely derivable. Fixed with an `_instant()` parser comparing instants, keeping the covered assertion intact.

3. Same file — `test_credit_consumed_by_later_settlement`: the second invoice's window 2027-08-01→2028-08-01 spans leap day 2028-02-29 (366 days), so PRD proration correctly yields 120000×366/365 → 120329 (implementation was right). Fixed the fixture window to 2028-08-01→2029-08-01 (exactly 365 days, leap day outside), preserving all downstream credit-conservation assertions (tender 90000 + 30000 credit settles 120000; `credit_applied_cents == 30000`).

4. `/home/ubuntu/github/CodingPRD/tasks/task_1825_astronomy_club_public_observing_night/test_suite/test_06_operators_and_groups.py` — `test_no_show_strikes_throttle`: setup failed with 409 marking a group booking NO_SHOW after host completion. Root cause is a PRD-internal tension: §3.6/§3.8 cascade *every* CONFIRMED booking to COMPLETED at host completion, while §3.8's booking mark-no-show requires a CONFIRMED booking on a COMPLETED host — an unreachable state pair under a faithful reading (the implementation implements both rules verbatim). Per STEP 1c partial-coverage handling, kept the verbatim-covered throttle assertion ("no_show_strikes reached 2 → ERR_NO_SHOW_THROTTLED, HTTP 422") and re-sourced both strikes via the unambiguous PRD-reachable path: two operator-assignment NO_SHOWs on two completed events (assignments explicitly "remain CONFIRMED at completion", §3.6).

**Stability note:** the clean sweep ran with all 8 rounds concurrent; no flakiness observed in the fixed tests.

## Step 8: Finalize PRD — 2026-08-14T20:33:00.000Z

Done. `PRD_FINALIZED.md` is produced with exactly one minimal insertion.

## Summary

**Line counts / delta:** PRD.md = 323 lines, PRD_FINALIZED.md = 325 lines (+2 lines, +0.62%).

### Step-7 item disposition

- **Item 1** (`test_member_accept_only_own_assignment` NameError) — pure test bug (missing `create_telescope` import); the ownership rule is PRD-verbatim (§3.7, §2.1). No PRD edit.
- **Item 2** (`dues_paid_through` string format) — genuine PRD silence → **the single edit below**.
- **Item 3** (leap-day proration, 366-day window → 120329) — pure fixture bug; PRD §3.1/§2.7 already pins day-count proration with a single final round-half-up, and `domain.py:56-62` implements it verbatim (`(period_end - period_start).days`, full-year iff exactly 365). No PRD edit.
- **Item 4** (booking NO_SHOW unreachable after host completion) — the implementation implements both PRD rules verbatim (completion cascades every CONFIRMED booking to COMPLETED at `routes/events.py:187-202`; booking mark-no-show requires a CONFIRMED booking on a COMPLETED host at `routes/events.py:438-459`). The impl made no choice beyond the PRD text, so there is no silence to pin; adding a "this is unreachable" note would be a universal reachability claim not grounded in any impl deviation. No PRD edit.

### Change list

- **§2.5 — insert —** added a paragraph pinning that every instant the server emits (server-stamped fields `joined_at`/`posted_at`/`taken_at`/`invited_at`/`opened_at`/`closed_at`/`issued_at`/`checkout_at`/`returned_at`; derived/stored instants `dues_paid_through`/`collimation_due_at`/`expires_at`; echoed client-supplied `window_start`/`window_end`/`period_start`/`period_end`; the clock endpoint's `current_utc`) serializes as ISO 8601 UTC with exactly three fractional digits and a `Z` suffix (e.g. `2027-08-01T00:00:00.000Z`), and that unset instant fields emit null — `implementation/helpers.py:22-25` (`fmt_dt`, the sole serializer), `implementation/views.py:6-192` (every view routes every datetime through `fmt_dt`/`_opt_dt`), `implementation/routes/core.py:32` (`current_utc`).

### Pre-edit search log (mandatory per edit)

**Edit 1 (§2.5 instant-serialization paragraph):**
- **(a) Subject:** wire serialization format of server-emitted instant (timestamp) fields.
- **(b) Impl paths enumerated and read/grepped:** `implementation/helpers.py:22-25` (`fmt_dt` — UTC, `%Y-%m-%dT%H:%M:%S.` + milliseconds + `Z`); `helpers.py:47-51` (`api_request_timestamp` via `fmt_dt`); `helpers.py:28-42` (`parse_dt`, input side only); all of `implementation/views.py` — `_base`/`_opt_dt` (9, 16), `member_view` `dues_paid_through`/`joined_at` (38, 41), `invoice_view` `period_start`/`period_end` (50-51), `payment_view` `posted_at` (66), `telescope_view` `collimation_due_at` (77), `cert_view` `issued_at`/`expires_at` (88-89), `loan_view` `window_start`/`window_end`/`checkout_at`/`returned_at` (103-107), `ticket_view` `opened_at`/`closed_at` (120-121), `event_view` `window_start`/`window_end` (132-133), `assignment_view` `invited_at` (151), `booking_view` (base fields only), `reading_view` `taken_at` (177), `report_view` `period_start`/`period_end` (185-186); `routes/core.py:32` (clock `current_utc`); `routes/equipment.py:210-230` (cert issuance stores client `expires_at`, echoed via view); `store.py` (no serialization). A repo-wide grep for `isoformat|strftime|fmt_dt` confirmed no output path bypasses `fmt_dt`.
- **(c) Wording adjustments made:** (i) added the null-emission clause because `_opt_dt` (views.py:16) emits JSON null for unset `checkout_at`/`returned_at`/`closed_at` — a blanket "all serialized as timestamps" claim would mis-describe those paths; (ii) explicitly enumerated the non-resource instant `current_utc` and client-supplied echoed bounds (`window_*`, `period_*`, `expires_at`) so the sentence covers them without claiming anything about input-precision handling, which the step-7 item did not exercise; (iii) scoped the claim to emitted values only, leaving request-parsing tolerance (naive→UTC, `z` suffix in `parse_dt`) unpinned since no step-7 fix touched it.

Files: `/home/ubuntu/github/CodingPRD/tasks/task_1825_astronomy_club_public_observing_night/workspace/PRD_FINALIZED.md` (created; sole source `/home/ubuntu/github/CodingPRD/tasks/task_1825_astronomy_club_public_observing_night/workspace/PRD.md` left untouched).

## Step 9: Complete PRD — 2026-08-14T20:45:00.000Z

The work is complete. Summary:

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1825_astronomy_club_public_observing_night/workspace/PRD_COMPLETED.md`

**Size delta:** PRD_FINALIZED.md 325 lines / 52,831 chars → PRD_COMPLETED.md 326 lines / 57,473 chars (**+1 line, +4,623 chars**).

**Counts:** 26 ambiguity-pins, 0 mismatch-revisions (PRD_FINALIZED.md was already behaviorally aligned wherever it made a claim; every change closes a silence). All edits are in-paragraph inserts; no new sections.

**Changes (all insert / ambiguity):**

- §2.1 — insert — ambiguity — failed ownership comparison pinned to `ERR_FORBIDDEN` (403) — implementation/routes/equipment.py:419, routes/events.py:258, routes/core.py:144
- §2.2 — insert — ambiguity — unknown path or unsupported method rejected as `ERR_NOT_FOUND` (404) in the standard envelope — implementation/app.py:39-46
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` (400); `created_at` ties broken by insertion sequence; `has_more` ⟺ `offset+limit < total_count` — implementation/helpers.py:158-190
- §2.4 — insert — ambiguity — clock set accepts any instant (no monotonicity); all server-stamped instants read the logical clock, only `api_request_timestamp` is wall-clock — implementation/routes/core.py:30, domain.py:37-51, helpers.py:47-51
- §2.5 — insert — ambiguity — client-supplied instants may be any ISO 8601 string; offset-less values interpreted as UTC — implementation/helpers.py:28-42
- §2.9 — insert — ambiguity — window-sanity check runs after shape validation and before domain business rules — implementation/routes/equipment.py:284-290, routes/events.py:54-56
- §2.10 — insert — ambiguity — ownership comparisons slot in as step (4b) between body-id existence and shape validation — implementation/routes/core.py:228-233, routes/events.py:347-351
- §3.1 (tiers) — insert — ambiguity — `annual_dues_cents` and `max_concurrent_loans` must be non-negative, else `ERR_INVALID_REQUEST` (400) — implementation/routes/core.py:43-52
- §3.1 (registration) — insert — ambiguity — duplicate email → `ERR_INVALID_REQUEST` (400) — implementation/routes/core.py:87-88
- §3.1 (invoices) — insert — ambiguity — invoices issuable in any member status; coverage day count is whole 24-hour days, fractional remainder discarded — implementation/routes/core.py:166-188, domain.py:58
- §3.1 (payments) — insert — ambiguity — non-negative `amount_cents`; member/invoice mismatch → `ERR_INVALID_REQUEST` (400); non-`OPEN` invoice → `ERR_INVALID_STATE` (409); credit consumed only to cover a shortfall (`credit_applied_cents` = min(credit, shortfall), 0 when tender alone covers, excess added to balance) — implementation/routes/core.py:237-251
- §3.1 (reinstate) — insert — ambiguity — non-`SUSPENDED` member or clock not before `dues_paid_through` → `ERR_INVALID_STATE` (409) — implementation/routes/core.py:129-133
- §3.2 (update) — insert — ambiguity — PUT must supply `name` in full; no partial update — implementation/routes/equipment.py:70
- §3.2 (retire) — insert — ambiguity — retirement from other statuses or blocked by live reservations → `ERR_INVALID_STATE` (409); forced ticket closes on the MAINTENANCE write-off path do not reset `collimation_due_at` even for COLLIMATION tickets — implementation/routes/equipment.py:85-103
- §3.3 — insert — ambiguity — tickets may be opened against telescopes in any status; only `AVAILABLE` transitions to `MAINTENANCE` — implementation/routes/equipment.py:131-133
- §3.4 (checkout) — insert — ambiguity — outside-window checkout → `ERR_INVALID_STATE` (409); non-`ACTIVE` member → `ERR_MEMBER_NOT_IN_GOOD_STANDING` (422) — implementation/routes/equipment.py:359-365
- §3.4 (return) — insert — ambiguity — `damage_reported` defaults to false, must be boolean; auto-opened damage ticket is kind `REPAIR`, severity `MEDIUM`, `condition_delta` 0 — implementation/routes/equipment.py:382-408
- §3.5 — insert — ambiguity — certification issuable to a member in any lifecycle status with any `expires_at` — implementation/routes/equipment.py:209-227
- §3.6 (daylight) — insert — ambiguity — windows spanning two UTC dates rejected with `ERR_NOT_DAYLIGHT_WINDOW` — implementation/routes/events.py:29-30
- §3.6 (weather-check) — insert — ambiguity — weather check accepted in every lifecycle status; auto-cancel fires only when `CONFIRMED` — implementation/routes/events.py:124-137
- §3.6 (confirm) — insert — ambiguity — `SCHEDULED`-state check precedes the OCC version comparison — implementation/routes/events.py:146-150
- §3.6 (complete) — insert — ambiguity — completing from a non-`CONFIRMED` status or before `window_end` → `ERR_INVALID_STATE` (409) — implementation/routes/events.py:191-195
- §3.7 — insert — ambiguity — inviting and accepting impose no precondition on host event status; invite also has no standing gate — implementation/routes/events.py:207-226, 263-291
- §3.8 (create) — insert — ambiguity — `contact_member_id` must be the acting Member (else `ERR_FORBIDDEN` 403); non-`PUBLIC_NIGHT` host → `ERR_INVALID_REQUEST` (400) before the standing/throttle gates — implementation/routes/events.py:349-360
- §3.8 (confirm) — insert — ambiguity — host not `SCHEDULED`/`CONFIRMED` → `ERR_INVALID_STATE` (409) — implementation/routes/events.py:410-412
- §3.9 — insert — ambiguity — `sqm_value` rounded half-up to two decimals at recording; no constraint on the event's status/window or the recorder's standing — implementation/routes/events.py:476-496
