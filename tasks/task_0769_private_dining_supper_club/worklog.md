# Worklog — task_0769_private_dining_supper_club

## Step 1: Create Task Directory — 2026-07-06T03:00:00.000Z

Created `tasks/task_0769_private_dining_supper_club/` and `tasks/task_0769_private_dining_supper_club/workspace/`. Scenario: Private-Dining & Supper-Club Experience (Expert difficulty).

## Step 2: Generate Scaffold — 2026-07-06T03:26:00.000Z

All three files parse cleanly and the lint is green. Summary for `task_0769_private_dining_supper_club`.

Three files: `SCAFFOLD.yaml` (§1.0–§1.7, preamble, no design keys), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, single top-level key), `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, single top-level key).

Design (Expert):
- Archetype: quota/allocation (seat inventory) blended with temporal windowing (chef & venue scheduling). Layers: optimistic concurrency, cascading side effects, dual-variant calculation, rate/threshold triggers. Topology hybrid; role model peer_roles; consistency immediate.
- Entities (10): SupperClubSeries, Venue, Chef, Guest, Event, Seat, MenuCourse, Booking, WaitlistEntry, Payment (append-only, `common_fields: false`).
- State machines (5): Event (cyclic OPEN↔SUSPENDED + branching cancel/complete cascades), Booking (parallel `booking_status` × `payment_status`), WaitlistEntry, Seat, Chef.
- Calculations (6): `booking_deposit_due` (round-per-seat-then-sum, pinned), `booking_total_price` (tiered group discount + corkage, pinned eval order), `event_revenue` (projected vs realized dual variant), `cancellation_refund` (day-tier threshold), `seat_inventory_counts`, `waitlist_position` (created_at ordering, id never used).
- Endpoints: 36 (every FK has a reverse-reachability GET; `/_clock/set_current_utc` with default `2026-03-01T00:00:00Z`).
- Error catalog: 31 codes. Validations: 23 priority-ordered rows. Concurrency: 1 OCC rule (`reprice-stale-event` on `Event.version`, 412).

§1.8: 9 rule_ids × 2 = 18 instances. §1.9: 28 active instances + 6 `excluded_because` stubs.

Lint: clean — §1.5 endpoints 36, §1.1 entities 10, §1.8 instances 18, §1.9 instances 28, calls scanned 443.

## Step 3: Copy Shared Files — 2026-07-06T03:27:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_0769_private_dining_supper_club/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-06T03:33:00.000Z

PRD complete at `workspace/PRD.md`. 5 top-level sections, 10 §2 subsections, 9 §3 subsections. 301 lines.

Coverage (mechanically verified): Entities (9→10 incl. Payment) all field names verbatim; Payment `common_fields: false` stated. State machines (5): Event, Booking (parallel booking_status × payment_status), WaitlistEntry, Seat, Chef. Calculations (6): booking_deposit_due (round-per-seat-then-sum, 2000-cent head-table supplement), booking_total_price (subtotal→group discount party≥6 rates 0.10/0.15 cap 15000→corkage), event_revenue (projected vs realized), cancellation_refund (14/7/2-day tiers + event-cancel 100%), seat_inventory_counts, waitlist_position. Endpoints (37) full §4 table. Errors (32) in §5 + prose. OCC reprice with `expected_event_version` + ERR_STALE_EVENT_VERSION/412. Roles (5).

Note for downstream: `VENUE_TURNOVER_MINUTES`, `CHEF_PREP_MINUTES` carry no numeric value in scaffold; PRD specifies half-open interval-overlap semantics precisely but names them as fixed configured buffers without minute counts. (Buffer-minute-specific tests may fail unique-derivability in Step 7.)

## Step 5: Generate Unit Tests — 2026-07-06T03:48:00.000Z

test_helpers/ (9 files): types.py (Payment carries only id+created_at), api_client.py, api_errors.py (31 error IDs + HTTP map), assertions.py, factories.py, constants.py, test_users.py (opaque roles + make_guest/venue_manager/chef_headers), fixtures.py (provision_draft/scheduled/open_event, provision_pending/confirmed_booking, waitlist/clock helpers), __init__.py.

test_suite/ (4 files + conftest): 62 tests, all collecting cleanly.
- §1.8 Difficulty (queue A): 17 of 18 instances translated, 2 tests each (34 tests).
- §1.9 Corner (queue B): all 28 non-stub instances translated, 1 test each (28 tests). 6 excluded_because stubs correctly not translated.

Skipped for PRD silence: Difficulty/resource_temporal_overlap/chef_prep_buffer_overlap — CHEF_PREP_MINUTES named but numeric value not in PRD; outcome not uniquely derivable. Sibling venue_turnover_buffer_overlap kept (base intervals 16:00–19:00 vs 15:00–18:00 already overlap independent of buffer).

Kept-with-caveat: Event version == 1 at creation / == 2 after reprice — PRD §2.4 says version increments but doesn't pin initial integer; treated 1-based as reasonable-reader reading.

## Step 6: Generate Implementation — 2026-07-06T03:48:00.000Z

Python + Flask in-memory implementation at workspace/implementation/. Files: start.sh (reads $PORT default 10000, binds 0.0.0.0, foreground via exec python3 app.py, pip guarded on import flask), requirements.txt (Flask 3.0.3), app.py (~1000 lines, in-memory Store dicts, no seeding).

All 36 endpoints. Mechanics: response envelope + pagination on 3 top-level lists; X-User-ID/X-User-Role RBAC + per-role ownership (VenueManager→venue_id, Chef→chef_id, Guest→guest_id); §2.10 validation precedence; Decimal round-half-up pricing (deposit round-then-sum, total subtotal→group discount w/ 15000 cap→corkage, head-table +2000); parallel Booking state machines; tiered refunds (14/7/2-day); event-cancel 3-hop cascade; completion no-show forfeiture; waitlist promotion; OCC on expected_event_version (412); logical clock default 2026-03-01T00:00:00Z.

Flagged ambiguity: VENUE_TURNOVER_MINUTES=30, CHEF_PREP_MINUTES=60 set as labeled constants (scaffold gap, PRD-silent).

## Step 7: Run Tests and Iterate — 2026-07-06T03:56:00.000Z

All 8 rounds pass 62/62. Clean sweep achieved.

Iterations run: 2 (initial sweep, then one fix + verification sweep).

Tests deleted: None.

Fixes applied to test_suite/:
- test_03_cancellation_refunds_waitlist.py, test_event_cancel_frees_seat_and_appends_refund_payment — changed seat-status assertion from AVAILABLE to BLOCKED (and added current_booking_id is None check). Test asserted an intermediate state. PRD §3.9 (line 220): hop 3 frees each held seat BOOKED/HELD → AVAILABLE with current_booking_id cleared, then "After the booking cascade completes, any seat that is still AVAILABLE (or was HELD by nothing) is taken out of service by transitioning it to BLOCKED." Final observable state (via GET) of a seat freed by a cancelled booking is BLOCKED. Fix makes the test faithful to PRD's final-state rule.

Fixes applied to implementation/: None — cancel_event in app.py (lines 908–952) already transcribes PRD line 220 exactly.

Single failure (assert 'BLOCKED' == 'AVAILABLE') was deterministic across all 8 initial rounds, not flakiness.

## Step 8: Finalize PRD — 2026-07-06T04:00:00.000Z

No-op finalization. PRD.md = 301 lines; PRD_FINALIZED.md = 301 lines (exact copy). Zero edits — PRD already pins the Step 7 subject.

The only Step 7 fix was a test-suite correction (AVAILABLE→BLOCKED seat status). PRD §3.9 line 220 already fully and uniquely determines the event-cancel seat cascade, and cancel_event (app.py:907-952) transcribes it exactly: hop 3 frees held seats BOOKED/HELD→AVAILABLE clearing current_booking_id, then post-cascade blocks every still-AVAILABLE/HELD seat →BLOCKED. Parallel paths checked: complete_event does not block seats (PRD §3.8 correctly silent on BLOCKED); DRAFT-branch cancel has no seats (PRD line 218). No PRD silence/mismatch at the Step 7 site.

## Step 9: Complete PRD — 2026-07-06T04:05:00.000Z

PRD_COMPLETED.md produced (minimal patch over PRD_FINALIZED.md). PRD_FINALIZED.md 301 → PRD_COMPLETED.md 303 (+2 lines); chars 39,149 → 40,211 (+1,062). Ambiguity-pins: 8. Mismatch-revisions: 0.

Changes:
- §2.3 Pagination — insert — only top-level /events, /bookings, /waitlist paginate; nested sub-resource lists return full set sorted by created_at asc, no pagination meta (app.py:977-1006, 1187-1198, 1323-1336).
- §2.3 Pagination — insert — exact-match filter query params per list endpoint; unrecognized params ignored (app.py:774-777, 1073-1076, 1192-1195, 982-984, 1002-1004).
- §2.4 Common Resource Properties — revise — version starts at 1 upon creation (app.py:193).
- §2.8 Logical Clock — insert — clock-set echoes new value in `now` field (app.py:1351).
- §3.2 Scheduling — insert — VENUE_TURNOVER_MINUTES = 30 (app.py:20).
- §3.2 Scheduling — insert — CHEF_PREP_MINUTES = 60 (app.py:21).
- §3.3 Menus — revise — optional description/paired_wine_name/wine_varietal default null (app.py:1019-1021).
- §3.5 Booking — revise — optional table_preference/allergy_notes default null (app.py:1121, 1123).
- §3.7 Waitlist — insert — serialized position is null for entries not in WAITING (app.py:575-582, 589).

Checked, already pinned (no change): refund tier boundaries, pricing eval order, discount rates 0.10/0.15, party 6/10, 15000 cap, head-table +2000, pagination default 10/min 1/max 100/offset 0, chef initial AVAILABLE, derived event fields.

## Pipeline Complete

All 9 steps finished. Final state: 62/62 tests pass across all 8 stability-sweep rounds. Artifacts: SCAFFOLD.yaml + 2 design YAMLs, PRD.md → PRD_FINALIZED.md (no-op) → PRD_COMPLETED.md, test_helpers/ + test_suite/ (62 tests), workspace/implementation/ (Flask, in-memory).
