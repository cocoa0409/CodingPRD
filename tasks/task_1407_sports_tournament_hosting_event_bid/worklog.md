# Worklog — task_1407_sports_tournament_hosting_event_bid

## Step 1: Create Task Directory — 2026-08-13T04:05:00.000Z

Pre-assigned directory `tasks/task_1407_sports_tournament_hosting_event_bid/` with `workspace/` subdirectory already exists (verified, not created by this run). User request: difficulty harder than expert level.

## Step 2: Generate Scaffold — 2026-08-13T05:16:00.000Z

All checks pass. The scaffold package is complete and lint-clean.

**Files written (all three required):**
- `/home/ubuntu/github/CodingPRD/tasks/task_1407_sports_tournament_hosting_event_bid/SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1407_sports_tournament_hosting_event_bid/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1407_sports_tournament_hosting_event_bid/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**SCAFFOLD.yaml counts:** 18 entities (incl. self-referential Match bracket wiring, polymorphic RoomBooking booker, junctions OfficialAssignment/ShiftSignup), 18 state machines (cyclic loops on Bid/Match/ImpactReport/Settlement/Field/Shift; posture-driven gating on Event), 11 calculations (tiered hotel rebate with per-booking rounding pin, marginal sanction fee with per-tier rounding pin, per-assignment stipend rounding, waterfall settlement, bracket seeding/topology, reschedule queue ordering, daily-load threshold, volunteer hours, bid score), 46 ordered validation rows, 115 endpoints (incl. `/_clock/set_current_utc` with pinned default 2026-08-01T00:00:00Z), 48 error codes (all referenced), 9 roles (entity-backed TeamRep/Official/Volunteer/HotelManager/VenueManager; opaque admin/reviewer/auditor with segregation-of-duties anchors), 4 OCC concurrency rules (412 semantics), fixed response envelope verbatim.

**§1.8 difficulty design:** 18 instances — all 9 rules × 2, with rule-required differentiations honored: dual variants in different domains (hotel rebate 114000→108000 vs impact spend 6940000→6155000), combinatorial modes (a) tier/attrition interplay and (b) per-assignment rounding (11998 ≠ 11999), cyclic machines on Bid vs Match, depth-3 weather cascade vs depth-2 settlement-pay cascade, disjoint validation-priority category pairs ({state, business_fiscal} vs {business_safety, business_temporal}), boundary precision on pickup_pct==0.9000 (inclusive) vs team_cap waitlist flip, cross-entity gates on Bid←BidRequirement vs Settlement←ImpactReport, overlap semantics half-open pairwise (field) vs per-night aggregate capacity (hotel), and compensating invariants on picked-up room-nights vs entered_team_count. All numeric asserts precomputed as literals.

**§1.9 corner design:** 52 instances (49 active recipes + 3 `excluded_because` stubs) across sections entities(7), state_machines(9), calculations(6), validations(4), endpoints(4), errors(6 batteries covering every remaining catalog error), rbac(6), cross_cutting_layers(8 incl. 4 OCC stale-version tests + blackout cascade + 3 stubs), consistency_model(1).

**Verification:** `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (115 endpoints, 18 entities, 18+49 instances, 1240 calls scanned). Additional mechanical checks passed: no forbidden race vocabulary, 70 unique instance names across both design files, zero unresolved grounds, stubs reference real difficulty instances, every error code reachable. No sibling task directories were read at any point.

## Step 3: Copy Shared Files — 2026-08-13T05:17:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1407_sports_tournament_hosting_event_bid/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T05:42:00.000Z

All checks pass. The PRD is complete and verified.

## Summary

**File written:** `/home/ubuntu/github/CodingPRD/tasks/task_1407_sports_tournament_hosting_event_bid/workspace/PRD.md` — 467 lines.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC, 2.2 API Response Structure (byte-identical to `section-2.2-response-structure.md`, verified programmatically), 2.3 Pagination, 2.4 The Logical Clock, 2.5 Event Posture: The Master Lifecycle Gate, 2.6 Common Resource Properties, 2.7 Money/Precision/Rounding, 2.8 Optimistic Concurrency Control, 2.9 Validation Order and Nested Resource Retrieval, 2.10 Cascading Consistency and Terminal States, 2.11 Segregation of Duties
- §3 Business Logic (9 subsections): bids/requirements, venues/fields, hotel blocks/bookings/rebates, divisions/registration/waitlist, seeding/brackets/scheduling, match play/weather/reschedule queue, officials/assignments, volunteers/shifts/signups, impact reporting/settlement
- §4 Endpoint Definitions (115 rows, 4 columns) — §5 Error Code Catalogue (48 rows, 2 columns)

**Scaffold tables covered:** all 18 entities, all 18 state machines (every transition's preconditions, error IDs, and side-effect cascades), all 4 OCC concurrency rules (write endpoint + `expected_*_version` field + `ERR_STALE_VERSION`/412 each named), all 11 calculations (rebate tiers with pinned per-booking rounding, both estimated/final variants, per-capita spend 14,500¢, marginal sanction fee 8/10/12% over 5M/10M¢ tiers with per-slice rounding, 9,999¢ stipend × 0.6/1.0/1.5 multipliers, waterfall with negative-net allowance, seeding order, bracket topology with bye placement and odd/even slot wiring, reschedule queue order, daily-load boundary, volunteer hours, bid score with WAIVED half-credit floor and inclusive 80 threshold), all 48 errors (each paired with its trigger in §2/§3 prose), all 9 roles with identity semantics.

**Zero-Silence decisions deliberately rendered in prose:**
- Validation priority order stated explicitly in §2.9 (auth → ownership → existence → OCC → posture → state → SoD → business → temporal → cross-event → fiscal), so tests can trace which error masks which.
- Every capacity/quota rule with its exact boundary semantics: daily official limit ("reaching exactly the limit is allowed; the assignment that would exceed it is refused"), half-open window adjacency for field conflicts, per-night inventory including non-CANCELLED bookings only.
- Cascades enumerated entity-by-entity with per-entity `version` +1 and `updated_at` refresh (§2.5, §2.10, and each workflow).
- Sort-order overrides (events `created_at` DESC, bids `cycle_number` DESC, name-ascending lists, match/booking null-ordering) stated next to each list.
- Clock contract (startup default 2026-08-01T00:00:00Z, monotonic, `to_iso8601`/`current_utc`) in §2.4.
- Nullability/defaults: `seed_number` null until seeded, `final_rebate_cents`/`attrition_penalty_cents`/`audited_direct_spend_cents`/`actual_attendance` null until their computing event, `released_reason` null unless RELEASED, `rebate_tier` TIER_0 until computable.

**Hard Contracts:** Contract 1 — 148/148 required names present, 0 missing. Contract 2 — full manual walk: validations/priorities, 4 OCC rules, all transitions, all calculations, all side effects, structured field content, sibling-branch symmetry (cancel cascades per posture, per-booking vs per-tier rounding) all expressed. Contract 3 — 996 §3 backtick tokens scanned, 0 path/method violations. §2.2 verified byte-identical to the canonical source. No pseudocode operators or fuzzy hedging words anywhere in prose.

## Step 5: Generate Unit Tests — 2026-08-13T06:14:00.000Z

All checks pass. One last sanity review of remaining subtle correctness issues before closing:

1. `test_bid_renewal_after_bid_lost_revives_event` uses `create_bid_payload(ev_lost["version"], ...)` — correct OCC threading.
2. `test_settlement_approve_sod_certifier_cannot_approve` certifies with ops-admin-1 then approves with the same id — expect SoD. Good.
3. `test_06` `_setup_approved_settlement_with_rebate` plays the final with no officials, reconciles block (18 rooms × 4 nights → 108000 rebate at TIER_2 — wait: 72/80 = 0.9000 → TIER_2 rate 0.10 → round(18*4*15000*0.10) = 108000. Correct).
4. Certify that settlement in the rebate cascade: registration revenue 2×10000=20000, sanction fee 8% of 20000 = 1600, venue rental 200000 — net negative, fine (PRD says it may be negative).
5. `setup_completed_event` reconciles the block with zero bookings → final_rebate 0, attrition penalty = floor(0.8*80)−0=64 nights × 15000 × 0.5 = 480000. That's fine for certify (no gate on penalty size).

Everything is in place.

## Summary

Generated complete test infrastructure for `task_1407_sports_tournament_hosting_event_bid` at `/home/ubuntu/github/CodingPRD/tasks/task_1407_sports_tournament_hosting_event_bid/`.

**test_helpers/ (9 modules):**
- `types.py` — 18 entity TypedDicts, 17 status enums, role enum
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (~70 methods), `api_client` singleton
- `api_errors.py` — `ApiErrorId` enum (46 errors) + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` validators + `assert_instant_equals` (timezone/fraction-tolerant instant comparison for echoed datetime fields, avoiding two-reader format risk)
- `factories.py` — input-only payload factories per creatable entity
- `constants.py` — PRD thresholds (AWARD_MIN_SCORE 80, tier floors/rates, PER_CAPITA_SPEND_CENTS 14500, sanction tiers, stipend multipliers, default clock)
- `test_users.py` — shared opaque-role headers + per-instance builders for the 5 entity-backed roles
- `fixtures.py` — composite lifecycle fixtures: `create_event`, `create_verified_bid`, `award_event_bid`, `create_contracted_venue`, `create_hotel_block`, `create_booking` (confirm/check-in-out walks), `reconcile_block`, `advance_posture` (re-reads version), `make_team_eligible`, `create_active_official/volunteer`, `setup_event_in_registration_open`, `setup_published_bracket`, `setup_completed_event`, `setup_accepted_impact_report`, `setup_approved_settlement`, `propose_and_accept_assignment`, `setup_match_in_reschedule_queue`, `list_division_matches`
- `__init__.py` — barrel export

**test_suite/ (6 files + conftest.py, 85 tests total):**
- `test_01_event_bid_requirements.py` (16 tests), `test_02_hotel_rebate_bookings.py` (14), `test_03_registration_divisions_teams.py` (14), `test_04_matches_weather_officials.py` (14), `test_05_volunteers_shifts_and_gates.py` (8), `test_06_impact_settlement_occ.py` (13)

**Per-instance disposition:**
- Queue A (Difficulty): all 18 instances emitted, exactly 2 tests each (36 tests).
- Queue B (Corner): all 46 non-stub instances emitted, 1 test each (49 tests incl. one per instance; some instances like `errors_bid_requirement_domain` bundle multiple error assertions). The 3 `excluded_because` stubs (`derived_team_count_reconciliation_stub`, `derived_pickup_reconciliation_stub`, `estimated_rebate_read_stub`) were not translated — their cited difficulty instances own the assertions. No instance was skipped for PRD-coverage reasons; every instance passed the coverage + unique-derivability filter.

**Stage 2 self-checks (all green):**
- Tag audit: 85 tests, 67 distinct Design tags; every Queue A instance has ≥2 tests; every non-stub Queue B instance has ≥1; no untagged/dual-tagged/orphan tags; stubs carry no tests.
- Verbatim citation audit: every ≥8-word `PRD §…: "…"` docstring citation (with truncation ellipses stripped) greps verbatim in `PRD.md`.
- `python -m py_compile` clean; `pytest --collect-only` collects 85 tests with zero import errors.
- Two-reader hardening: echoed-datetime assertions use instant-equality rather than string equality; the docstring for the generic-state fallback was re-cited to a full PRD §2.9 sentence after the audit flagged ellipsized quotes.

## Step 6: Generate Implementation — 2026-08-13T06:55:00.000Z

All checks pass. The implementation is complete and the full test suite is green.

**Files written under `workspace/implementation/` (4196 lines of source + start.sh + requirements.txt):**
- `start.sh` — foreground launcher; guarded dependency install (`python3 -c "import flask"` gate), `exec python3 app.py`, binds 0.0.0.0:$PORT (default 10000)
- `app.py` — Flask entry point, ApiError/404/405/exception envelope handlers
- `db.py` — in-memory store (18 entity dicts, empty at boot, no seeding), logical clock defaulting to exactly 2026-08-01T00:00:00Z, 3-fractional-digit ISO stamping, `_seq` insertion counter for timestamp tie-breaks
- `errors.py` — all 48 PRD §5 error ids with pinned HTTP statuses
- `response.py` — PRD §2.2 envelope (meta/response_type/data; pagination fields in meta for lists)
- `middleware.py` — X-User-ID/X-User-Role auth (401 ERR_UNAUTHENTICATED), role-set checks (403 ERR_FORBIDDEN), typed body validators, limit/offset pagination parsing
- `listing.py` — sort + paginate + envelope helper
- `services.py` — queries, per-entity whitelist serializers with live computed fields, all 11 calculations (dual-variant hotel rebate with per-booking rounding pin, dual-variant impact spend, marginal sanction fee with per-slice rounding pin, per-assignment stipend rounding, settlement waterfall, bracket seeding/topology incl. bye placement, reschedule queue order, daily load, volunteer hours, bid completeness score), cascades (event cancel by posture, award/reject, blackout enqueue, weather delay/resolve, disqualify-forfeit, advancement/elimination/division-completion, shift OPEN<->FILLED bubble, waitlist promotion, settlement pay -> event SETTLED + blocks SETTLED)
- `routes/` — 10 blueprints (ops, bids, venues, hotels, divisions, matches, officials, volunteers, weather, finance), all 115 endpoints registered (verified programmatically)

**Verification:**
- `prd-bench-local-run --start-command "cd workspace/implementation && bash start.sh" --test-dir test_suite --isolation per-test-server` — first run 82/85, second run **85/85 passed** (`results.1.json`), ~100s per run, 85 fresh server boots per run with zero restart failures.
- Additional ad-hoc smoke passes (4 scripts, ~130 assertions) covered the full happy-path lifecycle, ownership scoping for all 5 entity-backed roles, OCC 412s on all 4 guarded endpoints, and the blackout direct-enqueue path.

**Test-suite fixes applied during iteration (3 test-side slips, implementation untouched — it was spec-conformant in each case):**
1. `test_hotel_per_night_aggregate_capacity_inclusive_boundary` — `validate_success` call was missing `expected_status=201` for a create endpoint (PRD §4 pins 201; sibling tests for the same endpoint pass it explicitly).
2. `test_hotel_per_night_aggregate_non_overlapping_nights_admitted` — same missing `expected_status=201`.
3. `test_rebate_tier_one_night_below_090_falls_to_tier1` — setup created the second booking *after* the `check_in_out` fixture walk had advanced the logical clock to 2026-10-13, past the block's 2026-10-01 cutoff, so the PRD-mandated `ERR_CUTOFF_PASSED` gate (§3.3, also asserted by the passing `test_booking_domain_error_battery_rejected`) correctly rejected it. Fixed by creating both bookings before advancing the clock, then walking both CONFIRM → CHECK_IN → CHECK_OUT; asserted numbers unchanged (71 picked-up nights, TIER_1, final rebate 74550).

## Step 7: Run Tests and Iterate — 2026-08-13T07:05:00.000Z

The 8-round parallel stability sweep is fully clean. Stability is proven.

## Summary

- **Iterations run:** 1 (the initial 8-round parallel sweep passed; no further iterations needed).

- **Per-round results:** rounds 1-8 each `total=85, passed=85, failed=0, errors=0, skipped=0` — 680/680 test executions green across all concurrent rounds. No flaky/timing failures surfaced (no intermittent failures in any round's union set), and no runner-level anomalies (no restart failures or test timeouts; the `Killed` lines in the runner log are the normal per-test-server SIGTERM restarts under `--isolation per-test-server`).

- **Tests deleted:** none. No PRD-silence or unique-derivability violations found — no diagnostic STEP 1/2 interventions were required because no test failed in any round.

- **Fixes applied to `test_helpers/`:** none this iteration.

- **Fixes applied to `test_suite/`:** none this iteration.

- **Fixes applied to `implementation/`:** none this iteration.

The previously logged state (85/85 single-round pass plus the 3 test-side slips fixed during generation, recorded in `worklog.md` Step 6) is now confirmed stable under the full 8-round concurrent sweep at `/home/ubuntu/github/CodingPRD/tasks/task_1407_sports_tournament_hosting_event_bid`.

## Step 8: Finalize PRD — 2026-08-13T07:05:30.000Z

SKIPPED. Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. The 3 test-side fixes during Step 6 (generation phase) were corrections of tests toward an already-explicit PRD (201-on-create in PRD §4; the booking cutoff gate in PRD §3.3) — they reveal no PRD silence or PRD/impl mismatch, so no `PRD_FINALIZED.md` is produced.

## Step 9: Complete PRD — 2026-08-13T07:22:00.000Z

All edits applied. The file remains 466 lines (all changes are in-paragraph); 25 paragraphs were revised.

## Summary

**Source vs output**: `PRD.md` — 466 lines / 79,969 chars; `PRD_COMPLETED.md` — 466 lines / 84,016 chars (char-delta **+4,028**).

**Counts**: 15 ambiguity-pins, 10 mismatch-revisions (25 total changes).

### Changes

- **§2.3** — insert — ambiguity — non-integer/out-of-range `limit` (outside 1–100) or negative/non-integer `offset` rejected with `ERR_VALIDATION` (400) — implementation/middleware.py:163-181
- **§3.1 (event summary)** — insert — ambiguity — unreconciled blocks contribute zero to `total_final_rebate_cents` — implementation/routes/ops.py:99
- **§3.1 (bid patch)** — insert — ambiguity — every accepted PATCH bumps the bid's `version` even when `notes` is absent — implementation/routes/bids.py:101-103
- **§3.1 (verify)** — revise — mismatch — terminal (`VERIFIED`/`WAIVED`) requirement draws `ERR_ALREADY_TERMINAL`, not `ERR_REQUIREMENT_NOT_REVIEWABLE` — implementation/routes/bids.py:292-296
- **§3.1 (waive)** — revise — mismatch — same terminal carve-out for waive; also pinned `waiver_reason` is stored in the requirement's `review_notes` — implementation/routes/bids.py:319-328
- **§3.1 (withdraw)** — insert — ambiguity — withdrawing `UNDER_REVIEW` → `ERR_INVALID_STATE` (409); clearing `active_bid_id` does not increment the event's `version`/`updated_at` — implementation/routes/bids.py:139-145
- **§3.2 (fields)** — insert — ambiguity — field creation on a non-`CONTRACTED` venue → `ERR_INVALID_STATE` (409); fields list and per-field matches list each accept an optional `status` filter — implementation/routes/venues.py:121-122,143-145,210-212
- **§3.2 (blackout)** — insert — ambiguity — blacking out an already-`BLACKED_OUT` field or lifting a non-existent blackout → `ERR_INVALID_STATE` (409) — implementation/routes/venues.py:172-173,196-197
- **§3.3 (close-cutoff)** — insert — ambiguity — requires a `CONTRACTED` block (other non-terminal → `ERR_INVALID_STATE`; terminal → `ERR_ALREADY_TERMINAL`) — implementation/routes/hotels.py:137-140
- **§3.3 (booking create)** — revise — mismatch — block-status gate yields `ERR_ALREADY_TERMINAL` for terminal blocks (PRD claimed `ERR_BLOCK_NOT_CONTRACTED` for all); also pinned that the cross-event check runs after the block-window check, before inventory — implementation/routes/hotels.py:233-257
- **§3.3 (reconcile)** — revise — mismatch — "any other status" narrowed: terminal blocks draw `ERR_ALREADY_TERMINAL`, only other non-terminal statuses draw `ERR_BLOCK_NOT_RECONCILABLE` — implementation/routes/hotels.py:154-158
- **§3.4 (division create)** — insert — ambiguity — `min_teams` > `team_cap` → `ERR_VALIDATION` (400) — implementation/routes/divisions.py:31-33
- **§3.4 (registration)** — insert — ambiguity — division must be `OPEN` (else `ERR_DIVISION_NOT_OPEN`); teams list accepts optional `status` filter — implementation/routes/divisions.py:160-163,114-116
- **§3.4 (roster/eligibility)** — insert — ambiguity — non-`ENTERED` roster submit and non-`ROSTER_SUBMITTED` verify → `ERR_INVALID_STATE`; division-OPEN checked before team state, roster size last — implementation/routes/divisions.py:204-211,223-228
- **§3.5 (lock seeding)** — revise — ambiguity — check order pinned: posture → division-`OPEN` → min-teams; `created_at` seeding ties further broken by creation sequence — implementation/routes/divisions.py:73-81, services.py:401
- **§3.5 (publish bracket)** — insert — ambiguity — non-`SEEDING_LOCKED` division → `ERR_DIVISION_NOT_OPEN` (409), posture gate first — implementation/routes/divisions.py:97-102
- **§3.5 (bracket topology)** — insert — ambiguity — pinned round-1 slot ordering as the standard balanced draw (8-bracket: 1v8, 4v5, 3v6, 2v7), lower-numbered seed is `home_team_id`, and bye-seed round-2 placement via phantom slot k → ceil(k/2), home iff k odd — implementation/services.py:412-509
- **§3.5 (schedule preconditions)** — revise — mismatch — reordered to impl: posture → match/division state → teams-complete → time conflict → lights → event dates → cross-event venue → field `AVAILABLE` (PRD had teams first and cross-event/blacked-out before temporal checks) — implementation/routes/matches.py:53-118
- **§3.6 (start/finalize)** — insert — ambiguity — non-`SCHEDULED` start and non-`IN_PROGRESS` finalize → `ERR_MATCH_NOT_SCHEDULABLE` (409) — implementation/routes/matches.py:165-166,188-189
- **§3.6 (resolve)** — revise — mismatch — resolve also clears `scheduled_end`, not just `field_id`/`scheduled_start` — implementation/routes/weather.py:139-146
- **§3.6 (reschedule)** — revise — mismatch — "division need only remain BRACKET_PUBLISHED (not re-gated)" replaced: the division's status is not re-examined at all; queue-order check runs before field/window prechecks — implementation/routes/matches.py:138-146
- **§3.7 (proposal battery)** — revise — mismatch — reordered to impl: match `SCHEDULED` → official `ACTIVE` → certification → duplicates → turnover window → cross-event → daily cap (PRD listed cross-event first) — implementation/routes/officials.py:122-164
- **§3.7 (assigned_game_count)** — revise — mismatch — acceptance leaves the count unchanged (already counted while `PROPOSED`); PRD claimed acceptance adds one, contradicting its own live-set definition — implementation/services.py:54,566-568; routes/officials.py:196-205
- **§3.7 (assignment lists)** — insert — ambiguity — per-match and per-official assignment lists accept optional `status` filter — implementation/routes/officials.py:102-104, routes/matches.py:232-234
- **§3.8 (volunteer patch)** — insert — ambiguity — `background_check_cleared` is a required boolean; patch accepted on any non-terminal volunteer (terminal → `ERR_ALREADY_TERMINAL`) — implementation/routes/volunteers.py:62-72
- **§3.8 (signup gates)** — revise — mismatch — order pinned as impl: volunteer `ACTIVE` → shift non-terminal (a `FILLED` shift passes and fails later with `ERR_SHIFT_FULL`, not `ERR_SHIFT_NOT_OPEN`) → window overlap → cross-event → capacity — implementation/routes/volunteers.py:240-266
- **§3.8 (shift complete/cancel)** — insert — ambiguity — both require `OPEN` or `FILLED` (other non-terminal → `ERR_SHIFT_NOT_OPEN`); signup lists accept optional `status` filter — implementation/routes/volunteers.py:179-180,196-197,113-115,219-221
- **§3.9 (expense lines)** — insert — ambiguity — `amount_cents` is zero-or-more — implementation/routes/finance.py:198
- **§3.9 (settlement list)** — insert — ambiguity — settlements list accepts optional `status` filter — implementation/routes/finance.py:178-180

No new sections or paragraphs were added; every change is an inline insert/revision within the existing prose.
