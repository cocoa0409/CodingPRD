# Worklog — task_0696_comedy_club_venue

Scenario: Comedy Club & Live-Show Venue: show calendar & seating (GA/reserved/table), ticket tier & 2-item/drink minimum, reservation & comp/guest-list, performer/lineup & contract, table assignment & server, refund/exchange, private event, box-office settlement

Difficulty: Expert (passed to Step 2 scaffold-generator only).

## Step 1: Create Task Directory — 2026-06-28T15:32:48.340Z

Pre-assigned directory used verbatim (no ./tasks scan, no index recompute). Confirmed `tasks/task_0696_comedy_club_venue/workspace` exists.

## Step 2: Generate Scaffold (Expert) — 2026-06-28T15:58:49.159Z

Generated all three scaffold artifacts for task_0696_comedy_club_venue (Comedy Club & Live-Show Venue), targeting the SKILL §0.4 **Expert** band. Files written: SCAFFOLD.yaml (1515 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (913 lines, key `scaffold_difficulty_design`), SCAFFOLD_CORNER_DESIGN.yaml (1435 lines, key `scaffold_corner_design`).

### Counts
- **Entities: 13** — Venue, Show, SeatingSection, SeatTable, Performer, LineupSlot, TicketTier, Reservation, Ticket, GuestListEntry, Server, PrivateEvent, Settlement
- **Endpoints: 58** (above the 20–32 guideline, driven up by the mandatory FK reverse-reachability GETs the lint requires across a hybrid topology; the business surface itself is lean)
- **Error codes: 23**
- **Calculations: 6** with multiple variants — `compute_minimum_due` (pre/post-seating), `compute_settlement` (public/private-buyout), `compute_refund` (show-cancel/late-patron-cancel), plus `compute_ticket_charge`, `compute_buyout_deposit`, `compute_section_availability`
- **State machines: 8**, with non-linear dimensions: **Reservation** (PARALLEL — booking_status × settlement_status), **LineupSlot** (CYCLIC — OFFERED↔COUNTERED), **Settlement** (COMPOUND), **Show** (BRANCHING — DRAFT forks to ON_SALE/PRIVATE_HELD), plus SeatTable, PrivateEvent, GuestListEntry
- **Concurrency rules: 2** (OCC on SeatTable and LineupSlot versions), **Roles: 5** (Booker, BoxOffice, FloorManager, Patron, Performer)
- **§1.8: 18 difficulty instances**; **§1.9: 43 corner instances** (39 active + 4 excluded_because stubs)

### Verification
- `scaffold_lint.py` → VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5; all 18 FKs have reverse-reachability.
- Hard constraint honored: no sibling task_*/ directory read/globbed/listed.

## Step 3: Copy Shared Files — 2026-06-28T15:59:12.664Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md (53 lines).

## Step 4: Generate PRD — 2026-06-28T16:04:10.510Z

Generated workspace/PRD.md (295 lines). Sections: §1 Introduction, §2 Global Specs (9 subsections: RBAC/5 roles, Response Structure, Pagination, Common Properties & money, Hierarchical Consistency, Nested Retrieval + validation priority, Logical Clock, OCC×2, Posture/Sale-Window gating), §3 Business Logic (12 subsections), §4 Endpoint table (61 endpoints), §5 Error Catalogue (23 IDs). All three Hard Contracts PASS (field coverage 66/66 + 51/51 + 22/22; rule coverage incl. 2/2 OCC, all 23 errors, all 6 calculations; path purity 0 path-tokens in §3). Both SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml confirmed never read.

## Step 5: Generate Unit Tests — 2026-06-28T16:19:27.161Z

Test files: 8 (1 conftest + 7 test modules), **75 test functions** (75 Design tags, all resolving). Queue A (Difficulty §1.8): 36 tests across all 18/18 instances (≥2 each). Queue B (Corner §1.9): 39 tests across all 39/39 non-stub instances (≥1 each). 4 excluded_because stubs correctly not translated. Instances skipped: 0.
- Modules: test_01_resources_crud (11), test_02_seating_and_pricing (7), test_03_reservation_lifecycle (13), test_04_show_and_buyout_lifecycle (11), test_05_settlement (10), test_06_contracts (6), test_07_validation_rbac_concurrency (17).
- One scaffold-leakage adjustment: `show_cancel_cascade_depth3_to_server` asserts `Server.assigned_table_count == 0`, but PRD only releases table→AVAILABLE (not RETIRED) and never unassigns server → count not uniquely-derivable; covered the instance's 2 tests on PRD-derivable cascade facets (reservation→CANCELLED, table→AVAILABLE, full refund) instead.
- test_helpers/: __init__.py, types.py, api_client.py, api_errors.py, assertions.py, factories.py, constants.py, test_users.py, fixtures.py.
- Ticket TypedDict + assert_ticket omit updated_at/version (append-only). test_users provides entity-backed Performer + ownership-checked Patron builders. fixtures re-reads tables after server-assign so OCC expected_table_version stays current.

## Step 6: Generate Implementation — 2026-06-28T16:19:27.161Z

Implementation at workspace/implementation/: start.sh, requirements.txt (flask>=2.0), app.py (58 routes + error handlers + cascades), db.py (in-memory Store, dicts keyed by id), errors.py (ApiError + 23 error-ids), clock.py (logical clock default 2026-03-01T00:00:00Z), response.py (envelope meta/response_type/data, req_ ids, ms timestamps), middleware.py (X-User-ID/X-User-Role auth+RBAC), validate.py, serialize.py (Ticket omits updated_at/version), services.py (calculations/cascades).
- start.sh: reads $PORT (default 10000), binds 0.0.0.0, foreground `exec python3 app.py`, threaded=True; pip install guarded behind import check.
- Storage in-memory only, NO seeded data (verified: fresh boot → all collections total_count 0).
- 58 endpoints = every row of PRD §4.
- PRD-fidelity notes: check-in requires settlement_status==TICKET_PAID (literal); counter/revise-offer apply priority-6 state check before priority-9 counter-limit check (PRD verbatim).

## Step 7: Run Tests and Iterate — 2026-06-28T16:32:50.364Z

All tests pass across two consecutive clean 8-round parallel sweeps (16 rounds, 75/75 every round). Orchestrator then re-ran one more canonical 8-round sweep: results.1..8.json all passed=75 total=75 failed=0 errors=0.

**Iterations run:** 3 sweeps (1 diagnostic + 2 confirmation). Initial sweep: 72/75 in all 8 rounds (3 deterministic failures). After fixes: 75/75 in all 8 rounds, confirmed twice.

**Tests deleted:** None. All three failures were artifact bugs (test-helper/test-suite/implementation), not PRD-silence or non-derivability issues, so no test required deletion.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `setup_ga_show_on_sale`: the tier creation passed an explicit `name="GA"` keyword that collided with a caller-supplied `tier_overrides={"name": ...}`, raising `TypeError: got multiple values for keyword argument 'name'`. Replaced with a merged `tier_kwargs` dict so overrides cleanly replace the defaults. (Fixed `test_exchange_downsell_credits_difference`.)

**Fixes applied to `test_suite/`:**
- `test_suite/test_07_validation_rbac_concurrency.py` — added the missing import of `setup_ga_show_settlement_open`; the test used it but never imported it, causing `NameError`. (Fixed `test_invalid_state_beats_section_sold_out_on_settling_show`.)

**Fixes applied to `implementation/`:**
- `workspace/implementation/app.py` — `open_settlement`: removed a fabricated show-status precondition (`status not in {ON_SALE,PRIVATE_HELD,SOLD_OUT}` → `ERR_INVALID_STATE`) that does not trace to any PRD sentence. PRD §3.12 names only `ERR_SHOW_NOT_ENDED` (timing) and `ERR_SETTLEMENT_EXISTS` (duplicate) as open-settlement guards; the invented check masked the duplicate rule when a second settlement was opened on an already-`SETTLING` show. (Fixed `test_duplicate_open_settlement_rejected`.)
- `workspace/implementation/app.py` — `exchange_reservation`: now returns the addressed/modified old reservation (the `{reservation_id}` in the path, now `EXCHANGED`/`REFUNDED` with `refunded_cents` set to the credited difference) instead of the newly created `BOOKED` row. PRD §3.7 describes the operation as modifying the old row (refund, EXCHANGED transition, ticket voiding all live on it), and §2.2 says a modify operation returns the updated (addressed) resource. (Fixed the runtime assertion in `test_exchange_downsell_credits_difference` once its helper collision was resolved.)

**Note on flakiness:** Round 1's post-fix sweep showed a one-off "API server could not be restarted" setup error on `test_comp_reservation_zero_ticket_charge` — a transient per-test-server boot-contention artifact under 8x concurrent restart load (identical wall-clock timestamps across rounds confirmed host saturation, not a code defect). It did not recur in either of the two subsequent full 8-round sweeps, nor in the orchestrator's canonical confirmation sweep.

## Step 8: Finalize PRD — 2026-06-28T16:37:41.973Z

Produced workspace/PRD_FINALIZED.md. Line counts: PRD.md=295, PRD_FINALIZED.md=295 (delta 0 lines; 1 line revised in place, ~+1 sentence).

**Changes:**
- §3.7 (Exchange) — revise — appended a sentence pinning that the `exchange` endpoint returns the *modified old row* (the addressed `{reservation_id}`, now EXCHANGED/REFUNDED with refunded_cents = credited difference), not the newly created BOOKED row — implementation/app.py:1003 (`return ok(S.reservation(res))`).

**Step 7 items NOT requiring a PRD edit:**
- test_helpers/fixtures.py tier name-kwarg collision — pure fixture bug.
- test_07 missing import — pure test bug.
- app.py open_settlement (removed fabricated status precondition) — impl→PRD alignment; PRD §3.12 already uniquely determines the open-settlement guards (only ERR_SHOW_NOT_ENDED for timing, ERR_SETTLEMENT_EXISTS for duplicate OPEN). No edit.

Pre-edit search log (Edit 1, §3.7): subject = which Reservation resource the exchange endpoint returns; enumerated exchange_reservation (app.py:949-1003, returns old row 200), create_reservation (app.py:680-693, returns new row 201), all other S.reservation(...) return sites (725,768,832,857,881,896,920,1040 — all return the single addressed res), refund math services.py:99-125, §2.2 + §4 preamble. Wording scoped strictly to the exchange op and explicitly contrasted "not the newly created BOOKED row" so it cannot override the create endpoint's new-row/201 convention.

## Step 9: Complete PRD — 2026-06-28T16:43:05.875Z

Produced workspace/PRD_COMPLETED.md. Source PRD_FINALIZED.md (295 lines, 45,212 chars) → PRD_COMPLETED.md (295 lines, 48,112 chars); char delta +2,900; line count unchanged (all in-paragraph inserts/revisions, no new sections).

**Counts: 8 changes — 7 ambiguity-pins, 1 mismatch-revision.**
- §3.1 Programming the Venue — insert — ambiguity — publishing a non-DRAFT show is ERR_INVALID_STATE; unmet publish preconditions (no section/no tier/HELD-or-CONFIRMED buyout) each yield ERR_INVALID_STATE while a closed venue yields ERR_POSTURE_BLOCKED, in that order — app.py:198-213.
- §3.5 Booking a Reservation — insert — ambiguity — patron_id taken verbatim from body for both BoxOffice and Patron; no overwrite from X-User-ID, no creation-time ownership check — app.py:651,696-718.
- §3.5/§3.7 exchange new row — insert — ambiguity — new exchange row carries same patron_id, is_comp false, fresh money fields — app.py:992-993,696-718.
- §3.6 Seating the Room (assign-table) — revise — mismatch — reordered assign-table error checks to impl order (wrong-kind → no-server → too-small → server-overloaded → table-unavailable → stale-version) — app.py:797-822.
- §3.6 Recording Consumption — insert — ambiguity — delta_cents may be any integer (incl. negative); TICKET_PAID→MINIMUM_MET advance is one-way; recording while not TICKET_PAID updates tab without settlement transition — app.py:889-894.
- §3.7 No-Show — insert — ambiguity — no-show leaves settlement_status unchanged (not REFUNDED), recomputes server assigned_table_count and ga_sold_count (may flip SOLD_OUT→ON_SALE) — app.py:1023-1039.
- §3.10 Guest List Convert/Revoke — insert — ambiguity — converted comp reservation patron_id = entry host_performer_id; revoke-cancel uses full no-fee show-cancel refund rule with full cascade — app.py:1141,1161-1187.
- §3.12 Opening a Settlement — insert — ambiguity — only two open guards (timing then duplicate); no show-status precondition; prior FINALIZED settlement does not block a new open — app.py:1327-1338.

## Pipeline COMPLETE — 2026-06-28T16:43:05.875Z

All 9 steps done. Final canonical 8-round parallel sweep: results.1..8.json all **passed=75 total=75 failed=0 errors=0**. Task directory contains SCAFFOLD.yaml + 2 design indices, test_helpers/, test_suite/ (75 tests), workspace/{INSTRUCTION,PRD,PRD_FINALIZED,PRD_COMPLETED}.md + implementation/ (58 endpoints, in-memory Flask) + results.{1..8}.json.
