# Worklog — task_1365_team_travel_charter_logistics

## Step 1: Create Task Directory — 2026-08-13T00:48:00.000Z

Task directory `tasks/task_1365_team_travel_charter_logistics/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline invoker. Step 1 treated as DONE per instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T01:12:00.000Z

All three files are written and the linter passes with a clean verdict.

## Summary

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1365_team_travel_charter_logistics/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1365_team_travel_charter_logistics/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1365_team_travel_charter_logistics/SCAFFOLD_CORNER_DESIGN.yaml`

**Counts:**
- Entities: **13** (Team, Season, Trip, TravelPartyMember, CharterContract, FlightLeg, ManifestEntry, HotelBlock, RoomAssignment, PerDiemLedger, EquipmentShipment, ContingencyEvent, CredentialRequest)
- State machines: **11** (Season, Trip, CharterContract, FlightLeg, ManifestEntry, HotelBlock, RoomAssignment, PerDiemLedger, EquipmentShipment, ContingencyEvent, CredentialRequest)
- Calculations: **9** (trip_estimated_cost, per_diem_net, charter_cancellation_penalty, rest_floor, hotel_attrition_penalty, equipment_weight_chargeback, trip_actual_cost_chronological, manifest_capacity_check, season_budget_remaining)
- Validations: **17** ordered priorities across auth / existence / state / business_safety / business_constraint / business_temporal / business_referential / business_fiscal
- Endpoints: **107** (43 business + 12 flat single-resource + 12 flat filtered-list + the rest sub-resource lists and the `/_clock/set_current_utc` test-driving endpoint)
- Errors: **40** domain-specific codes
- Roles: **10** (TravelOpsAdmin, TravelManager, TravelCoordinator, TravelFinanceLead, EquipmentManager, SecurityOfficer, VenueCredentialApprover, VendorRep, TeamMember [entity-backed], Any)
- §1.8 instances: **18** (2 per rule × 9 rules)
- §1.9 instances: **30** active corner instances across 8 sections (entities / state_machines / calculations / validations / endpoints / errors / rbac / cross_cutting_layers / consistency_model)

**Linter verdict:** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

**Notable design decisions (per the harder-than-expert directive):**

1. **Triple-cascade trip cancellation** (Rule 4 depth-3): Trip DISRUPTED→CANCELLED triggers CharterContract→CANCELLED (with penalty-band computation), which cascades FlightLeg→CANCELLED, which cascades ManifestEntry→BUMPED with OVERBOOK reason. Each hop is caused by the previous one, not the root trigger.

2. **Compound posture-driven Trip state**: Trip.posture is derived from child entity states (ContingencyEvent opens flip LOCKED→DISRUPTED without an explicit Trip-level call). Trip lock requires budget check against Season aggregate.

3. **Segregation-of-duties credential workflow**: CredentialRequest requires three distinct X-User-ID actors for submit → security-review → approve; revoke by SecurityOfficer cascades CONFIRMED ManifestEntries to BUMPED with SECURITY_DENIAL — bridging credential state into manifest state (cross-entity state dependency).

4. **Dual-variant trip cost calculation**: Forward-looking `estimated_cost_cents` (at lock) vs chronological `actual_cost_cents` (at close) diverge structurally on identical inputs — provisional counts DRAFT ledgers at base with zero meals, chronological replays only events that fired. Pinned literal difference (5000 cents) in §1.8.

5. **Circular-looking rest-floor rule** (Rule 2 mode c): Leg N+1's required departure floor depends on leg N's `delay_minutes`, but delay is finalized only on ARRIVE. Booking N+1 uses scheduled delay; if N later accrues more delay, N+1 auto-transitions to REBOOKING.

6. **Tiered straddle equipment chargeback** (Rule 2 mode a): 85%/100% capacity thresholds produce different per-lb rates on different slices of the same shipment (975000 cents literal pinned).

7. **Two distinct interval-overlap semantics** (Rule 8): BUFFER-style rest-floor (half-open minimum-gap) on FlightLeg vs EXCLUSION-POINT cutoff-date (half-open deadline) on HotelBlock.

8. **Two distinct compensating invariants** (Rule 9): fiscal budget conservation across lock→cancel vs seat-capacity conservation across bump→rebook→reconfirm.

9. **Priority-pair conflicts across two error-category pairs** (Rule 5): state vs business_fiscal (ERR_TRIP_NOT_DRAFT beats ERR_BUDGET_EXCEEDED), and business_safety vs business_constraint (ERR_REST_FLOOR_VIOLATION beats ERR_MANIFEST_FULL).

10. **Three OCC concurrency rules** on Trip lock, CharterContract execute, and HotelBlock lock — all using `expected_<parent>_version` placeholders referencing server-captured versions, never literals.

## Step 3: Copy Shared Files — 2026-08-13T01:12:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1365_team_travel_charter_logistics/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T01:28:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1365_team_travel_charter_logistics/workspace/PRD.md`. The withheld design files were not opened or referenced at any point.

## PRD Section List

- **1. Introduction** (2 paragraphs, business-context angle)
- **2. Global Specifications & System-Wide Principles** — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`, verified programmatically); 2.3 Pagination; 2.4 Common Resource Properties; 2.5 Hierarchical Addressing and Left-to-Right Path Validation; 2.6 Validation Cascade and Priority Ordering (all 17 validation priorities in order); 2.7 Optimistic Concurrency Control; 2.8 The Logical Operations Clock; 2.9 Money, Integer Cents, and Rounding; 2.10 Provisional versus Chronological Cost Accounting; 2.11 Posture Propagation and Cascade Consistency; 2.12 Season Budget Conservation
- **3. Business Logic & Workflows** — 3.1 Enrolling a Team and Opening a Season; 3.2 Building the Trip and the Travel Party; 3.3 Charter Contracting from Draft to Execution; 3.4 Flight Legs, Booking, and the League Rest Floor; 3.5 Manifests, Bumping, and the Venue Credential Gate; 3.6 Hotel Blocks and Room Assignment Discipline; 3.7 Equipment Shipments and Cargo Chargebacks; 3.8 Per-Diem Ledgers and Meal Deductions; 3.9 Disruptions, Recovery, Cancellation, and Close-Out; 3.10 Venue Credentials and Segregation of Duties
- **4. Endpoint Definitions** — 107 rows (matches scaffold exactly; method/path/role verified per endpoint)
- **5. Error Code Catalogue** — 40 rows (matches scaffold exactly)

**Line count:** 391

## Hard Contract Reports

```
Field coverage check:
- entities[].fields + endpoint inputs + query/path params: 113 required, 113 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority ordering: 17 checked, 17 expressed in the §2.6 cascade plus endpoint-specific orderings in §3, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (lock/execute/block-lock + expected_trip_version/expected_contract_version/expected_block_version + ERR_STALE_VERSION 412), 0 missing
- state_machines[].transitions: 52 transitions across 13 machines checked, all from/to states, preconditions, and side effects expressed (incl. LOCKED→DISRUPTED vs IN_FLIGHT→DISRUPTED asymmetry and DELAYED vs REBOOKING rebook asymmetry), 0 missing
- calculations[]: 9 checked, 9 fully expressed in prose (tier matrix, 2500-cent meal deduction, 600/720-min rest bases with 60/90 compounding, penalty-band selection with 100% fallback and half-up rounding, 85%/350/900 cargo tiers, 5-component estimate with both variants, 7-event chronological actuals replay, budget aggregation), 0 missing
- validations[] conditions: all matchable to error_ids in §2/§3 prose; all 40 error IDs appear in prose before §5
- endpoints[].side_effects / applies_to: expressed (scratch cascade, contract-cancel cascade, deny/revoke bump cascades, cutoff's three guarded operations, budget's three guarded operations)
- entities[].fields[] structured content: all defaults, enums, nullability, and computed-field derivations reconstructible
- sibling-branch symmetry: DRAFT vs DISRUPTED trip cancel, both hotel close paths, both rebook variants, deny vs revoke — all equally specified
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 586
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

One judgment call worth noting: the scaffold's equipment-load side effect mentions a "90%" trigger while the authoritative calculation table tiers at 85%; the PRD follows the calculation (85% boundary, 350/900 cents-per-pound tiers) to keep the math reconstructible.

## Step 5: Generate Unit Tests — 2026-08-13T02:05:00.000Z

All 64 tests collect cleanly. The generation is complete.

## Summary

**Output locations**
- `test_helpers/` — 9 files: `types.py` (13 entity TypedDicts + 12 status enums + role enum), `api_client.py` (one method per PRD endpoint, `/travel` prefix, incl. flat accessors), `api_errors.py` (all 41 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity validators + per-diem money / season-budget invariants), `factories.py`, `constants.py` (tier rates, 2500¢ meal deduction, 600/720 rest floors, 85%/350/900 chargeback tiers), `test_users.py` (10 roles; `make_team_member_headers(member_id)` builder for the entity-backed TeamMember role), `fixtures.py` (clock helpers, `setup_lockable_trip`/`setup_locked_trip`/`setup_disrupted_trip`/`setup_disrupted_charter_trip`/`setup_closed_trip`/`setup_closed_season`, executed/active contract chains, credential SoD chains), `__init__.py` barrel.
- `test_suite/` — `conftest.py` + 11 test files, **64 tests**, all importing cleanly and collected by pytest.

**Coverage**
- Queue A (Difficulty): 17 of 18 instances × 2 tests = **34 tests**. Every covered instance tagged `Design: Difficulty/<rule_id>/<name>`.
- Queue B (Corner): all **30 non-stub instances × 1 test = 30 tests** (the corner file contains no `excluded_because:` stubs). Tagged `Design: Corner/<section>/<name>`.
- Automated audits pass: every test has exactly one resolving Design tag; every docstring citation contains a ≥8-word verbatim substring of PRD.md.

**Instances skipped (with reason)**
- `Difficulty/cross_entity_state_dependency/per_diem_approve_requires_member_in` — the pinned outcome (`ERR_MEMBER_NOT_IN` on approving a scratched member's ledger) is unreachable via PRD-declared pathways: the only way a member leaves `IN` is scratch, and §3.2's scratch cascade moves that member's DRAFT ledgers to ADJUSTED, so the priority-6 target-state check (ledger not DRAFT) fires before the priority-15 member check. Two faithful PRD readers would not arrive at the instance's asserted error.

**Notable fixture/design decisions (PRD adjudications)**
1. `equipment_weight_tiered_straddle`: the >100%-capacity 900¢/lb tier is unreachable — §3.7 rejects overweight loads with `ERR_CARGO_OVERWEIGHT` first. Tests pin the free slice (≤85% inclusive), the exact boundary, and the full 350¢/lb tier-2 band; the recipe's 10500-lb scenario is logged as a PRD-internal contradiction (tier 3 vs. cargo ceiling).
2. `trip_cost_provisional_vs_chronological_diverge`: recipe assumed an *unlocked* hotel block contributes to close-out actuals; §3.9's replay only counts "hotel block lock" events. My close-out test locks the block first, making actual = 70000 (60000 hotel-lock + 10000 per-diem pay) vs. 75000 estimated-at-lock (provisional DRAFT-ledger-at-base rule) uniquely derivable.
3. `manifest_capacity_exactly_at_limit` / `manifest_seat_conservation_across_bump_rebook`: recipes added the extra member *before* booking, which trips the book-time IN-count ≤ seat_capacity check; tests add the third member after the leg is booked.
4. `rest_floor_compound_delay_circular`: recipe re-delayed a DELAYED leg (rejected with `ERR_LEG_NOT_BOOKED` per §3.4). Restructured: compound term pinned by booking leg 2 after leg 1 *arrives* 130 min late (delay_minutes finalized at arrival), plus the delay→REBOOKING downstream cascade.
5. `occ_hotel_block_lock_stale_version`: recipe assumed room creation bumps the block's version (not in PRD); used the system-driven HOLDING→NAME_LIST_DUE clock transition as the version-bumping mutation (explicitly covered by §2.4).
6. `hotel_block_cutoff_date_exclusion`: exact-day behavior is ambiguous in the PRD ("accepted only before cutoff_date" vs. "last day room names may be submitted"); tests pin clearly-before (accepted) and clearly-after (`ERR_CUTOFF_PASSED`).
7. `room_checkin_requires_block_locked`: PRD names no specialized error for the guard → `validate_error_is_one_of([ERR_INVALID_STATE, ERR_BLOCK_NOT_NAME_LIST_DUE])` with 409 asserted.
8. `team_creation_required_fields`: dropped the `version == 1` sub-assertion (PRD §2.4 never pins the initial version value); kept 201/UUID/`STANDARD` default assertions.

## Step 6: Generate Implementation — 2026-08-13T02:05:30.000Z

Implementation complete and verified. All 107 endpoints from SCAFFOLD.yaml §1.5 are registered and the server boots cleanly via `bash start.sh` with an empty store.

## Files created (all under `/home/ubuntu/github/CodingPRD/tasks/task_1365_team_travel_charter_logistics/workspace/implementation/`)

- `start.sh` — guarded dependency install (`python3 -c "import flask"` check), `exec python3 app.py` in foreground
- `requirements.txt` — flask
- `app.py` — Flask bootstrap, before-request hook (logical-clock sweep → header auth), error handlers (ApiError/404/405/500 all return the standard error envelope)
- `state.py` — in-memory `STORE` dicts (empty at boot, no seeding), logical clock (default `2026-08-01T00:00:00Z`, never wall clock), UUID ids, ISO-8601 3-fractional-digit timestamps, `version` starting at 1
- `envelope.py` — `meta`/`response_type`/`data` envelope; pagination fields (`limit`, `offset`, `total_count`, `has_more`) in `meta` for lists only
- `calc.py` — all §1.3 calculations: per-diem tiers, cancellation penalty (round-half-up), rest floor with delay compounding, attrition, tiered weight chargeback, estimate rollup, chronological actual rollup, derived season budget counters
- `util.py` — auth (10 roles), left-to-right path resolvers, body validation, OCC, pagination, clock sweep (NAME_LIST_DUE at cutoff−7d, ATTRITION_EXPOSED at cutoff, CLOSED after checkout, DRAFT→EXPIRED past tipoff−30d)
- `routes_core.py` — clock, teams, seasons, trips (lock/close/cancel), members + scratch cascade
- `routes_charter.py` — contracts (submit/countersign/execute/cancel), legs (book/delay/rebook/depart/arrive/cancel), manifest (create/confirm/bump)
- `routes_hotel.py` — blocks (create/lock/release), rooms (create/confirm/checkin/checkout/cancel)
- `routes_ops.py` — per-diem (create/approve/pay/dispute/resolve), equipment (create/load/deliver/mark-lost), contingencies (create/mitigate/resolve/close-noop), credentials (submit/security-review/approve/deny/revoke with SoD)
- `routes_flat.py` — 24 flat accessors (12 collections × get/list) with filter support

## Coverage

- **13/13 entities**, **107/107 endpoints** (83 nested/action + 24 flat)
- **All 12 state machines** with preconditions, side effects, and per-resource version bumps on cascades
- **All 8 calculations** including the dual-variant cost accounting (estimate: DRAFT per-diems at `base_amount_cents`; actual: chronological event-log replay)
- **All 17 validation priorities** with exact error IDs/statuses; verified precedence examples from §2.6 (credential gate before capacity, roommate before cutoff, cargo before contract state, execution window before budget, OCC 412 before state 409)
- Smoke-verified with 3 end-to-end scenarios (~180 assertions): full trip lifecycle to season close, disruption/rebook/DISRUPTED-cancel with penalty and `_incurred_loss` accounting, capacity boundaries, attrition exposure, scratch cascade, TeamMember read isolation, execution window, budget 402, penalty rounding

## Interpretation decisions (PRD prose admitted multiple readings)

1. **Cancelled contracts in the estimate**: §3.3's explicit arithmetic ("estimated -= base+cap−penalty; the penalty remains as cost exposure") wins over the §3.9 formula domain that lists only TEAM_EXECUTED/ACTIVE — CANCELLED contracts contribute their penalty.
2. **DRAFT per-diem rows in the estimate** count at `base_amount_cents` (zero-meals provisional assumption) — the scaffold's named `provisional_at_lock` variant plus §3.9 paragraph 3 override the generic "net_amount_cents" wording in the final maintained-sum sentence.
3. **DISRUPTED-cancel budget residue**: "committed -= (estimated − actual already incurred)" implemented as `_incurred_loss_cents` = cancellation penalties + RESOLVED/CLOSED recovery costs + LOST chargebacks + PAID per-diem, retained in derived season committed.
4. **`weight_class`** (no mapping given): PLAYER and EQUIPMENT → HEAVY, else LIGHT. **Roommate groups** (no table given): PLAYER→ATHLETE, COACH→COACH, STAFF/MEDICAL/SECURITY/EQUIPMENT→STAFF, EXECUTIVE→EXECUTIVE (same role always compatible).
5. **Credential gate trigger**: a destination "requires venue credential" iff any CredentialRequest exists on the trip with `venue_code == leg.destination_code`; the member then needs an APPROVED credential for that venue.
6. **Missing `ERR_ROOM_NOT_FOUND`** in the catalog (rooms absent from the 404 family): invented `ERR_ROOM_NOT_FOUND`/404 mirroring the family pattern; duplicate `team_code` (no error ID catalogued) → `ERR_INVALID_REQUEST`/400.
7. **Trip cancel** allowed only from DRAFT and DISRUPTED per the state machine (LOCKED/IN_FLIGHT/RECOVERING → `ERR_INVALID_STATE`); the DRAFT variant has no side effects.
8. **Delay cascade** moves only BOOKED downstream legs to REBOOKING (PLANNED→REBOOKING would violate the state machine); effective prior delay for rest-floor compounding uses computed `delay_minutes` after ARRIVAL and tracked reported delay while DELAYED (reset on rebook).
9. **Unknown role strings** are treated as malformed → `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`/400 (PRD: "carrying a malformed value"); out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` rather than clamping.
10. **TeamMember reads**: allowed everywhere except resources referencing another member (403); member-scoped lists filtered to own id. VendorRep retains GET access per PRD §2.1 ("every read endpoint is available to all roles") over the roles table's empty `shared_operations`.

Never read `test_helpers/`, `test_suite/`, or the corner/difficulty design files.

## Step 7/8: Test-diagnostic iteration (8-round parallel sweeps) — 2026-08-13T02:45:00.000Z

Iteration 1 sweep: 57/64 in all 8 rounds (identical failures; no flakiness). Fixes applied:

1. `implementation/state.py::new_id` — minted `uuid4().hex` (32 hex chars); PRD §2.4 "a server-minted UUID" is asserted in canonical RFC 4122 hyphenated form by the framework's `is_valid_uuid` → now `str(uuid.uuid4())`. Fixed `test_team_creation_applies_rest_policy_default` + `test_trip_computed_fields_at_creation`.
2. `test_suite/test_01::test_clock_set_returns_new_now` — PRD §2.8 pins that the clock capability "returns the new `now_utc`" (the instant) but never its string serialization (`now_utc` is neither a §2.4 resource field nor the §2.2 meta timestamp; canonical-ms vs echo-raw diverge across faithful readers). STEP 1c split: kept the covered assertion via new `assert_same_instant` helper, dropped the format pin.
3. `test_suite/test_05::test_delay_pushes_downstream_leg_into_rebooking` + `test_delay_rebook_cycles_increment_generation` — same format-silence on `scheduled_arrive_utc`/`scheduled_depart_utc` (§3.4 pins the instant shift/rewrite only); relaxed to `assert_same_instant`.
4. `test_suite/test_11::test_rebook_from_delayed_violating_rest_and_capacity` — setup bug: leg 1 inherited factory defaults (arrive 2027-02-28) while leg 2 departed 2026-12-26, so the setup's own `book_leg` violated the rest floor before the scenario under test. Added `leg_overrides` matching the documented timeline (leg 1 SAT→HOU 14:00→15:00). Assertion (§2.6 item 7 rest floor beats item 11 capacity) unchanged.
5. `test_suite/test_06::test_revoke_leaves_other_members_entries_untouched` — setup bug: confirmed the second member's manifest entry without an APPROVED credential although the venue gate was active for the leg's destination (a credential request for that venue exists on the trip; §3.5 gate + §3.10 "lifts the manifest gate ... for that member on legs to that venue"). Now approves a credential for the second member first. Cascade-scoping assertions unchanged.
6. `test_disrupted_trip_cancel_cascades_depth3` restart errors (8/8 rounds, full 15s poll budget consumed) — reproduced standalone: passes; root cause is external load from other pipelines on the shared host, not an artifact bug.

`test_helpers/assertions.py` gained `parse_instant`/`assert_same_instant` (format-agnostic instant comparison). No tests deleted.

Iteration 2 sweep: 64/64 in all 8 rounds.

## Step 7: Run Tests and Iterate — 2026-08-13T02:45:00.000Z

All 8 rounds of the final certification sweep are clean: 64/64 passed, 0 failed, 0 errors, in the final state of every file.

## Summary

**Iterations run:** 3 sweeps (sweep 1: 57/64 × 8 rounds, identical failures; verification round after fixes: 64/64; sweep 2: 64/64 × 8; final certification sweep after a mid-sweep test edit: 64/64 × 8 — `passed == total` in every round).

**Tests deleted:** none.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1365_team_travel_charter_logistics/workspace/implementation/state.py` — `new_id()`: minted `uuid4().hex` (32 hex chars); PRD §2.4 "a server-minted UUID" denotes the canonical RFC 4122 hyphenated string form that the framework's `is_valid_uuid` asserts. Changed to `str(uuid.uuid4())`. (Fixed `test_team_creation_applies_rest_policy_default`, `test_trip_computed_fields_at_creation`.)

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1365_team_travel_charter_logistics/test_helpers/assertions.py` — added `parse_instant`/`assert_same_instant`: PRD pins timestamp *instants* (§2.8 `now_utc`, §3.4 `scheduled_arrive_utc` shift) but never their string serialization for non-§2.4 fields, so comparisons must be format-agnostic.

**Fixes applied to `test_suite/` (all STEP 1c coverage corrections or STEP 2 setup bugs; no assertion weakened against a PRD-verbatim rule):**
- `test_01_enrollment_and_roster.py::test_clock_set_returns_new_now` — exact-string equality on `now_utc` relaxed to instant equality (PRD §2.8 covers the returned instant; the format is silent, two faithful readers diverge: echo-raw vs canonical 3-fractional-digit).
- `test_05_flight_legs_rest_floor.py::test_delay_pushes_downstream_leg_into_rebooking` and `::test_delay_rebook_cycles_increment_generation` — same format silence on `scheduled_arrive_utc`/`scheduled_depart_utc` (§3.4 covers the instant shift/rewrite only); relaxed to `assert_same_instant`.
- `test_11_validation_priority_and_occ.py::test_rebook_from_delayed_violating_rest_and_capacity` — setup bug: leg 1 inherited factory default times (arrive 2027-02-28) while leg 2 departed 2026-12-26, so the setup's own `book_leg` failed `ERR_REST_FLOOR_VIOLATION` before the scenario under test. Added `leg_overrides` (SAT→HOU 2026-12-25 14:00→15:00) matching the test's documented timeline. The asserted rule (§2.6 item 7 rest floor precedes item 11 manifest capacity) is unchanged.
- `test_06_manifest_and_credentials.py::test_revoke_leaves_other_members_entries_untouched` — setup bug: confirmed the second member's manifest entry with no APPROVED credential while the §3.5 venue gate was active for the leg's destination (a credential request for that venue exists on the trip; §3.10 "lifts the manifest gate … for that member on legs to that venue"). The fixture now approves a credential for the second member before confirming. Cascade-scoping assertions unchanged.

**Non-artifact finding:** `test_disrupted_trip_cancel_cascades_depth3` errored in all 8 rounds of sweep 1 with "API server could not be restarted" (full ~15s poll budget consumed). Root cause: environmental — another pipeline was running 8 concurrent rounds for a different task on the same host, and my 8 rounds run in lockstep, so one external load spike hit all of them at the same test index simultaneously. Standalone and in both later sweeps the test passes; no artifact change needed.

Final state: 64/64 tests passing in all 8 parallel rounds under `per-test-server` isolation.

## Step 8: Finalize PRD — 2026-08-13T02:55:00.000Z

The diff is minimal and complete. Final verification of every claim in the new paragraph against the implementation was done during enumeration — all 12 server-stamped fields and all 7 client-supplied fields match.

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1365_team_travel_charter_logistics/workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md = 390 lines; PRD_FINALIZED.md = 392 lines (+2 lines, +0.51%). Exactly two edits, both in §2.4.

### Changes

- **§2.4 — revise — `id` bullet now pins the canonical RFC 4122 hyphenated string form (8-4-4-4-12 hex groups)** — `implementation/state.py:33-35` (`new_id()` returns `str(uuid.uuid4())`); minted via `new_resource()` at `implementation/state.py:113-121`, the single id source for every resource. Step 7 fixed the impl from `uuid4().hex` (32 unhyphenated hex chars) because PRD's bare "a server-minted UUID" did not determine the form that the framework's `is_valid_uuid` asserts.
- **§2.4 — insert — new paragraph pinning date/datetime wire serialization: client-supplied fields stored verbatim, server-stamped timestamps canonical ISO 8601 UTC with exactly three fractional digits and `Z` suffix** — echo-raw sites: `implementation/routes_core.py:189-190,200-201` (`game_tipoff_utc`/`return_arrival_utc`), `implementation/routes_charter.py:243-244,265-266` (leg create), `implementation/routes_charter.py:400-401,415-416` (rebook), `implementation/routes_ops.py:357,367` (`detected_at`), `implementation/routes_ops.py:59,79` and `implementation/routes_hotel.py:65,67,77,79` (date fields); canonical sites: `implementation/state.py:52-55,114,127,131` (`created_at`/`updated_at` via `fmt_ts`/`now_iso`), `implementation/routes_core.py:71` (`now_utc`), `implementation/routes_charter.py:373` (delay-rewritten `scheduled_arrive_utc`), `implementation/routes_charter.py:445,475` (`actual_*`), `implementation/routes_charter.py:183,205` + `implementation/routes_core.py:304` (`executed_at`/`cancelled_at`), `implementation/routes_ops.py:156` (`paid_at`), `implementation/routes_hotel.py:350` (`confirmed_at`), `implementation/envelope.py:15` (`api_request_timestamp`). Traces to the Step 7 `test_helpers/assertions.py` fix (`parse_instant`/`assert_same_instant`), which revealed PRD pinned instants but never string serialization for non-§2.4 fields.

### Step 7 diff items with no PRD edit (with reason)

- `test_11_...::test_rebook_from_delayed_violating_rest_and_capacity` — pure fixture setup bug (leg times inconsistent with the scenario's own timeline); the asserted §2.6 priority (rest floor item 7 before manifest capacity item 11) is PRD-verbatim already.
- `test_06_...::test_revoke_leaves_other_members_entries_untouched` — pure fixture setup bug (confirmed a member with no APPROVED credential while the §3.5 venue gate was active); cascade-scoping assertions unchanged.
- Non-artifact environmental failure (`test_disrupted_trip_cancel_cascades_depth3`) — no change.

### Per-edit pre-edit search log

**Edit 1 (id form).** (a) Subject: string form of server-minted resource `id`. (b) Paths enumerated: `state.py:33-35` `new_id()` (sole minting site); `state.py:113-121` `new_resource()` assigning `id` to every resource; all create routes across `routes_core.py`, `routes_charter.py`, `routes_hotel.py`, `routes_ops.py` build resources via `new_resource()`; all resolvers in `util.py:111-199` compare ids by string equality; framework `is_valid_uuid` (`prd-bench-local-runner/src/prd_bench_local_runner/testing/assertions.py:19-21`) regex requires the hyphenated form. (c) Adjustment: named the 8-4-4-4-12 hyphenated form explicitly with an example; no enumerated path conflicts.

**Edit 2 (timestamp serialization).** (a) Subject: wire serialization of date/datetime fields, client-supplied vs server-stamped. (b) Paths enumerated and read: all `fmt_ts`/`now_iso` call sites across `state.py`, `envelope.py`, `routes_core.py`, `routes_charter.py`, `routes_hotel.py`, `routes_ops.py` (full grep of `"*_utc"`/`"*_at"`/`"*_date"` assignments plus `req_dt`/`req_date` inputs); `routes_flat.py`, `app.py`, `calc.py` confirmed to stamp nothing; internal `_locked_at`/`_attrition_at`/`_resolved_at` are stripped by `state.py:134-136` `public()` and never reach the wire. (c) Adjustment: an initial draft said client fields are "accepted in any ISO 8601 form" — dropped that acceptance-grammar claim because `parse_dt` (`state.py:62-80`) is narrower (requires a full time component); re-scoped the sentence to storage/return behavior only ("stored verbatim and returned exactly as supplied"), and limited the canonical-form claim to server-stamped fields actually written via `fmt_ts`, keeping it consistent with §2.2's existing `api_request_timestamp` wording and §2.4's existing `created_at` wording.

## Step 9: Complete PRD — 2026-08-13T03:05:00.000Z

All implementation error ids are now covered by the PRD catalogue. The patch is complete. Here is the summary.

## Summary

**Source vs output**: `PRD_FINALIZED.md` (392 lines / 61,585 chars) → `PRD_COMPLETED.md` (393 lines / 72,845 chars); char-delta **+11,260**, line-delta **+1** (one added error-catalogue row; all other edits are in-paragraph). File: `/home/ubuntu/github/CodingPRD/tasks/task_1365_team_travel_charter_logistics/workspace/PRD_COMPLETED.md`.

**Counts**: 30 ambiguity-pins (inserts), 10 mismatch-revisions.

### Ambiguity pins (insert)

- §2.1 — insert — ambiguity — pinned TeamMember read scoping: member-backed fetches/lists match `member_id` (room lists also include roommate; single room fetch matches primary only); non-member-backed resources unrestricted — `implementation/util.py:90-105`, `implementation/routes_flat.py:41-58`
- §2.3 — insert — ambiguity — invalid/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST`; `created_at` ties broken by creation order; `has_more` = offset+returned < total_count; exact-match whitelisted filters — `implementation/util.py:291-328`, `implementation/envelope.py:27-36`
- §2.4 — insert — ambiguity — `version` starts at 1 on creation — `implementation/state.py:113-121`
- §2.5 — insert — ambiguity — added `ERR_ROOM_NOT_FOUND` to the 404 enumeration — `implementation/util.py:46`
- §2.6 — insert — ambiguity — generic body-shape validation sits between path existence (item 3) and OCC (item 4); added consequence sentence pinning ordering on leg booking (rest floor → seat check → executable-state), contract submission (seat → band shape), and block lock (rooming preconditions → cutoff) — `implementation/routes_charter.py:313-347`, `implementation/routes_hotel.py:111-169`
- §2.8 — insert — ambiguity — time-driven transitions (contract expiry, block milestones) evaluated lazily on clock-set and before every request — `implementation/app.py:21-29`, `implementation/util.py:371-411`
- §2.12 — insert — ambiguity — trips cancelled from DISRUPTED contribute already-incurred costs (penalties, RESOLVED/CLOSED recovery, LOST chargebacks, PAID per-diem nets) to committed; projected = committed + DRAFT estimates — `implementation/calc.py:181-195`
- §3.1 — insert — ambiguity — duplicate `team_code` → `ERR_INVALID_REQUEST`; season close failures: already-CLOSED → `ERR_SEASON_CLOSED`, unmet preconditions → `ERR_INVALID_STATE` — `implementation/routes_core.py:84-86, 158-176`
- §3.2 — insert — ambiguity — `weight_class`: PLAYER/EQUIPMENT are HEAVY, all others LIGHT — `implementation/calc.py:25, 51-52`
- §3.2 — insert — ambiguity — scratch requires IN (else `ERR_INVALID_STATE`), allowed post-lock; cascade scoped to PENDING/CONFIRMED entries and RESERVED/CONFIRMED rooms (primary or roommate) — `implementation/routes_core.py:405-437`
- §3.2 — insert — ambiguity — trip-lock precondition error ids: party → `ERR_INVALID_STATE`, outbound leg → `ERR_LEG_NOT_BOOKED`, hotel block → `ERR_INVALID_STATE` — `implementation/routes_core.py:234-261`
- §3.3 — insert — ambiguity — drafting requires DRAFT trip; `penalty_bands` must be a list at creation, non-empty/descending shape enforced at submission; submit check order and error ids — `implementation/routes_charter.py:48-61, 67-137`
- §3.3 — insert — ambiguity — cancel precondition failure → `ERR_INVALID_STATE`; cascade limited to PLANNED/BOOKED/DELAYED/REBOOKING legs; unexecuted contract's estimate gains the penalty — `implementation/routes_charter.py:190-228`
- §3.4 — insert — ambiguity — leg creation requires DRAFT; `contract_id` validated for existence only at creation; commercial leg carrying one is stored but rejected at booking with `ERR_LEG_NOT_CHARTER` — `implementation/routes_charter.py:234-282`
- §3.4 — insert — ambiguity — "prior leg" = non-cancelled leg with greatest lower `leg_seq`; floor boundary inclusive; effective delay = `delay_minutes` if ARRIVED else accumulated reported delay; delay-report check order and accumulation; downstream REBOOKING limited to BOOKED legs; rebook resets accumulated delay and bumps trip version only from DELAYED; depart/arrive/cancel error ids; first/last leg definitions; arrival `delay_minutes` floored, negative when early — `implementation/routes_charter.py:313-515`, `implementation/calc.py:228-263`
- §3.5 — insert — ambiguity — entry creation allowed on any leg of a non-terminal trip, no per-member uniqueness; venue "requires credential" exactly when any credential request for that `venue_code` exists on the trip; bump of non-CONFIRMED → `ERR_INVALID_STATE` — `implementation/routes_charter.py:521-545, 589-603, 650-664`
- §3.6 — insert — ambiguity — block creation requires DRAFT; date-based sweep semantics (NAME_LIST_DUE at cutoff−7d; ATTRITION_EXPOSED only when penalty positive; CLOSED once date strictly past check_in+night_count) — `implementation/routes_hotel.py:56-91`, `implementation/util.py:371-401`
- §3.6 — insert — ambiguity — release guards: posture HOLDING/NAME_LIST_DUE, no CHECKED_IN, `rooms_to_release` in 1..releasable (else `ERR_INVALID_REQUEST`), full release closes block cancelling RESERVED/CONFIRMED rooms, partial release can immediately expose attrition — `implementation/routes_hotel.py:173-214`
- §3.6 — insert — ambiguity — room creation performs no status/compatibility checks (only CLOSED/cutoff); rooming groups: PLAYER alone, COACH alone, EXECUTIVE alone, STAFF+MEDICAL+SECURITY+EQUIPMENT shared; confirm ordering (roommate → cutoff → member-IN); lifecycle violations → `ERR_INVALID_STATE` — `implementation/routes_hotel.py:220-411`, `implementation/calc.py:28-36`
- §3.7 — insert — ambiguity — shipment creation guards; load preconditions and order (STAGED → cargo ceiling → contract ACTIVE as `ERR_CONTRACT_NOT_EXECUTABLE`); deliver only from IN_TRANSIT; mark-lost error id; loss chargeback replaces weight chargeback — `implementation/routes_ops.py:217-344`
- §3.8 — insert — ambiguity — ledger creation requires member IN before input validation; negative meals → `ERR_INVALID_PER_DIEM_INPUT`, non-integer/non-string → `ERR_INVALID_REQUEST`; dispute is self-only (`ERR_INSUFFICIENT_PERMISSIONS`); dispute/resolve/pay state error ids — `implementation/routes_ops.py:52-211`
- §3.9 — insert — ambiguity — events may open in any non-terminal posture (posture changes only from LOCKED/IN_FLIGHT); mitigate/resolve state errors; REBOOK → `ERR_LEG_NOT_BOOKED`; OVERNIGHT = any block in HOLDING/NAME_LIST_DUE/LOCKED/ATTRITION_EXPOSED; budget ceiling enforced only in LOCKED/IN_FLIGHT/DISRUPTED/RECOVERING; close-noop guards — `implementation/routes_ops.py:350-505`
- §3.9 — insert — ambiguity — close-out precondition failures → `ERR_INVALID_STATE`; financial events logged as signed deltas at occurrence (execution +base+cap; cancellation penalty alone if unexecuted, penalty−base−cap if executed) — `implementation/routes_core.py:264-284`, `implementation/calc.py:334-337`
- §3.10 — insert — ambiguity — self-submission only, non-terminal trip, member IN; security-review state error; denial and revocation perform no SoD check; missing `denial_reason` fails generic shape validation — `implementation/routes_ops.py:511-675`
- §5 — insert — ambiguity — added `ERR_ROOM_NOT_FOUND | 404 Not Found` catalogue row — `implementation/util.py:46`

### Mismatch revisions (revise)

- §3.4 — revise — mismatch — booking rule order: PRD listed contract-executable first; impl checks leg/contract consistency (`ERR_LEG_NOT_CHARTER`) → rest floor → IN-count seat check (`ERR_MANIFEST_FULL`) → executable-state (`ERR_CONTRACT_NOT_EXECUTABLE`) — `implementation/routes_charter.py:313-354`
- §3.5 — revise — mismatch — member-IN gate listed first among confirmation gates in PRD; impl evaluates it last, after the credential gate and capacity — `implementation/routes_charter.py:610-643`
- §3.5 — revise — mismatch — PRD checked "count of entries in PENDING or CONFIRMED" against `seat_capacity` at booking; impl checks the count of IN travel party members — `implementation/routes_charter.py:336-340`
- §3.5 — revise — mismatch — PRD's NO_SHOW transition never occurs: departure is gated on all PENDING entries resolved, so CONFIRMED entries survive departure and become FLOWN at arrival — `implementation/routes_charter.py:432-494`
- §3.5/§3.3 — revise — mismatch — PRD said cancelled leg/contract bumps its PENDING entries; impl bumps PENDING **and** CONFIRMED entries with OVERBOOK — `implementation/routes_charter.py:213-226, 509-513`
- §3.7 — revise — mismatch — PRD had delay move shipments to DELAYED generally and "rebooked departure" return them to IN_TRANSIT; impl moves only IN_TRANSIT→DELAYED on delay, and the depart action (not rebook) moves LOADED/DELAYED→IN_TRANSIT — `implementation/routes_charter.py:383-388, 454-459`
- §3.8 — revise — mismatch — approval required member "IN on the ledger's `service_date`"; impl checks the member is IN at approval time — `implementation/routes_ops.py:121-136`
- §3.9 — revise — mismatch — estimate enumeration counted DRAFT per-diem rows at `net_amount_cents`; impl counts DRAFT at full `base_amount_cents` (APPROVED/PAID at net) — `implementation/calc.py:157-166`
- §3.9 — revise — mismatch — estimate enumeration omitted CANCELLED contracts and landed attrition penalties; impl includes both (`cancellation_penalty_cents`, `_attrition_penalty_cents`) — `implementation/calc.py:139-152`
- §3.9 — revise — mismatch — PRD §2.11's blanket cancel cascade; impl cascades only when cancelling from DISRUPTED — a DRAFT cancellation performs no child cascade — `implementation/routes_core.py:287-345`

**Notes**: Tests were used only as cross-reference (e.g., confirming the 600-minute boundary inclusivity and delay-rewrite serialization). No new sections were added; the only structural addition is one row in the §5 error catalogue. The app-level catch-all `ERR_NOT_FOUND` for unrouted non-PRD paths (`implementation/app.py:37-44`) was deliberately left out of the PRD as outside the specified endpoint surface.
