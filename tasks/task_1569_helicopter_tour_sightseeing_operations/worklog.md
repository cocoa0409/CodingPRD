# Worklog — task_1569_helicopter_tour_sightseeing_operations

## Step 0: Resume assessment — 2026-08-13T22:40:00.000Z

RESUME RUN. Prior run was killed mid-Step-2. Directory state on resume:
- `SCAFFOLD.yaml` (85,674 B) — VALID YAML, all §1.1–§1.7 top-level keys present (scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles). KEPT.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (83,806 B) — VALID YAML, single top-level key `scaffold_difficulty_design`. KEPT.
- `SCAFFOLD_CORNER_DESIGN.yaml` — MISSING. Must be generated (Step 2 completion).
- `workspace/` — empty (no INSTRUCTION.md, no PRD.md). Steps 3-4 pending.
- No `test_helpers/`, `test_suite/`, `workspace/implementation/`. Steps 5-7 pending.

Plan: generate only the missing SCAFFOLD_CORNER_DESIGN.yaml (Step 2 completion), then proceed Step 3 → Step 9.

## Step 2 (completion): Generate SCAFFOLD_CORNER_DESIGN.yaml — 2026-08-13T23:30:00.000Z

**Written:** `SCAFFOLD_CORNER_DESIGN.yaml` (3,841 lines) — §1.9 breadth probe derived purely from the existing `SCAFFOLD.yaml`, per the claim-extraction-guide taxonomy.

**Instance counts by section** (79 total = 68 active with full `test_recipe` chains + 11 `excluded_because` stubs citing §1.8 instances):

| section | active | stubs |
|---|---|---|
| entities | 11 | 0 |
| state_machines | 16 | 0 |
| calculations | 9 | 0 |
| validations | 18 | 0 |
| endpoints | 3 | 0 |
| rbac | 6 | 0 |
| complexity_layers | 4 | 3 |
| consistency_model | 1 | 0 |
| errors | 0 | 8 |

**Coverage achieved:**
- All 36 error codes are triggerable: 28 via new §1.9 instances, 8 via stubs citing the §1.8 instance that already triggers them (all stub citations verified to exist by name in `SCAFFOLD_DIFFICULTY_DESIGN.yaml`).
- All 4 §1.2.1 concurrency rules have dedicated OCC stale-version instances (412 happy/stale pairs, `expected_*_version` always `${var}`-bound).
- All 12 entities, 11 state machines, and 10 calculations get at least one corner instance beyond §1.8's depth coverage; formula-derived asserts were pre-computed as literals (e.g., load-tier quotes 20000/22000/25000, CG boundary 54.25 accept vs 54.24 reject, refund tiers 25000/22500/18750, duty span 840 vs 841).
- Zero name collisions across the union of both design files; every active instance has complete `setup` / `setup_api_calls` / `trigger` / `assert`.

**Validation:** file parses as YAML; single top-level key `scaffold_corner_design` confirmed. `scaffold_lint.py` verdict on the full package: **2 violations, both rule (f) `FK_REVERSE_UNREACHABLE` and both pre-existing in `SCAFFOLD.yaml`** (`Booking.season_id -> Season`, `Complaint.matched_flight_id -> Flight` — verified reproducible with an empty corner file). All 68 §1.9 instances (and all 18 §1.8 instances) pass checks (a)–(e) across 1,015 scanned calls — zero call-level violations attributable to the new file. (Pre-existing scaffold-level findings noted; SCAFFOLD.yaml kept as-is per resume policy.)

## Step 3: Copy shared files — 2026-08-13T23:32:00.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md.

## Step 4: Generate PRD.md — 2026-08-13T23:50:00.000Z

**Output:** `workspace/PRD.md` — 294 lines.

### Section list
- **§1 Introduction** (2 paragraphs: regulatory/business context, system scope)
- **§2 Global Specifications** (9 subsections): 2.1 RBAC, 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Resource Identity/Timestamps/Change Tracking, 2.5 The Logical Clock, 2.6 Optimistic Concurrency Control, 2.7 Money/Weights/Measures, 2.8 Windows/Intervals/Boundary Semantics, 2.9 Validation Order and Error Precedence
- **§3 Business Logic & Workflows** (9 subsections, organized by operational timeline): 3.1 Bases/Routes/Seasons/Fleet setup, 3.2 Weather Surveillance & Posture, 3.3 Scheduling & Crewing, 3.4 Duty Ledger & Fatigue, 3.5 Quotes/Holds/Payment, 3.6 Waivers/Briefings/Check-In, 3.7 Manifest/Dispatch/Completion, 3.8 Cancellations/Moves/Credit Ledger, 3.9 Complaints & Noise Quota
- **§4 Endpoint Definitions** (47-row table, 4 columns)
- **§5 Error Code Catalogue** (36-row table, 2 columns)

### Hard Contract reports
- Contract 1 (Field-Name Coverage): 130 required, 130 present, 0 missing — PASS
- Contract 2 (Rule Coverage): PASS — validations priority ladder (§2.9's 11-rung ladder + explicit per-endpoint orders); concurrency_rules 4/4; state transitions all 12 machines fully expressed (Base 2, Route 2, Season 1, Aircraft 5, Pilot 2, DutyDay 1, Flight 18, Booking 15, Passenger 2, RebookingCredit 5, Complaint 7); calculations 12/12 in precise prose with constants embedded (8h/14h duty, 24h/2h refund tiers, 10%/75% legs, 60% fuel floor, 5-lb allowance, 30-min overflight pad); validations 36/36; all cascades expressed with full booking sub-cascades.
- Contract 3 (§3 Path Purity): 346 backtick tokens scanned, 0 paths, 0 bare methods, 0 combos — PASS

Supporting checks: 36/36 error IDs in §2/§3 and §5 table; 47/47 endpoint rows; §2.2 emitted byte-verbatim; WeatherObservation's missing `updated_at`/`version` stated explicitly; Pilot entity-backed identity and all five opaque identities translated in §2.1.

### Coverage audit (scaffold → PRD)
| Scaffold section | PRD destination |
|---|---|
| `scenario` | §1 (rewritten, 2 paragraphs) |
| `response_envelope` | §2.2 (verbatim block) + §2.3 (limit 10/1/100, offset 0, `created_at` ascending, meta fields) |
| `entities` (12) | §2.4 (common fields, WeatherObservation exception) + §3.1–3.9 (every field in narrative backticks) |
| `state_machines` (12) | Base→3.2, Route→3.9/3.1, Season→3.1, Aircraft→3.1, Pilot/DutyDay→3.4, Flight→3.3/3.7/3.8, Booking→3.5/3.6/3.7/3.8, Passenger→3.6, RebookingCredit→3.8, Complaint→3.9 |
| `calculations` (12) | seat_price_quote+manifest_estimate→3.5, manifest_final_wb→3.7, pilot_duty_minutes→3.4, cancellation_settlement+move_settlement+credit_redemption→3.8, complaint_auto_match+complaint_quota_rollup→3.9, rotation_sequence→3.3, weather_posture→3.2, turn_window→3.3 |
| `validations` (36) | Global order → §2.9 ladder; trigger conditions scattered to guarding workflows in §3.1–3.9 |
| `concurrency_rules` (4) | §2.6 (all four, exact error id + HTTP 412) + cross-references in §3.3/3.7/3.8/3.1 |
| `endpoints` (47) | §4 table (Method/Path/Description/Roles only); side effects narrated in §3 |
| `errors` (36) | §5 table (ID + status only); trigger conditions in §2/§3 |
| `roles` (6) | §2.1 (identity prose per role) + §4 Authorized Role(s) column |

## Step 6: Generate implementation — 2026-08-14T00:30:00.000Z

Implementation complete and verified. Summary:

## File inventory
All under `workspace/implementation/`:

| File | Purpose |
|---|---|
| `start.sh` | Executable launcher; guarded `pip install` (no-op when Flask present), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | `flask>=3.0` |
| `app.py` | Flask app factory, blueprint registration, envelope-shaped error handlers (ApiError, 404, 405) |
| `store.py` | In-memory dict store (12 entity collections + credit-application ledger), logical clock starting exactly at `2026-08-01T00:00:00Z`, ID/timestamp helpers (ISO-8601 UTC, 3 fractional digits) |
| `errors.py` | ApiError + all 36 catalog error IDs with their HTTP statuses |
| `envelope.py` | Success/error envelope builders (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields in `meta`) |
| `validate.py` | Rung-1 body/field validators, auth (`X-User-ID`/`X-User-Role`, 6 roles), role checks, `limit`/`offset` pagination (defaults 10/0, clamp 1–100) |
| `domain.py` | Serializers + all 9 calculations (seat_price_quote pinned round-half-up steps, manifest estimate/final W&B with fuel trim and Decimal CG, dual-variant duty ledger, cancellation tiers, move waterfall, credit redemption, complaint auto-match, quota rollup, rotation sequence, weather posture, turn windows) and cascades |
| `routes_admin.py` | bases, routes, seasons, aircraft, pilots, duty-days, run-ops, `/_clock/set_current_utc` |
| `routes_flights.py` | flight create (full gate battery in PRD order), OCC assignment, all 8 flight events, OCC close-manifest |
| `routes_bookings.py` | bookings CRUD+, apply-credit, confirm, CANCEL (3 settlement tiers), OCC move, passenger waiver/briefing/check-in/uncheck, credits |
| `routes_weather_complaints.py` | weather observations (immutable, no version/updated_at) + cascade trigger, complaints with auto-match and quota-driven auto-suspension |

## Counts
- **Endpoints: 47** — exact match to the scaffold endpoint table (including `POST /_clock/set_current_utc`; no `GET /bases` list, which the PRD omits).
- **State machines: 10** — Base posture (derived), Route, Season, Aircraft, Pilot, DutyDay, Flight (14 transitions incl. PILOT_ACK self-transitions), Booking (13 transitions), Passenger check-in loop, RebookingCredit, Complaint (with REOPEN loop).
- **OCC endpoints: 4** (`expected_flight_version` ×2, `expected_booking_version`, `expected_base_version`) → `ERR_STALE_VERSION`/412.
- Storage is purely in-memory dicts; **no seeding, no disk/JSON/SQLite persistence** (grep-verified); a credit-application sub-ledger supports HELD-cancel release-back.

## Boot verification
Launched `bash start.sh` on port 18369 (fresh process), hit `GET /routes` (200), then ran ~90 assertions across four smoke suites covering: quote math (season 1.2x × weekend 1.1x → 13200/seat), manifest W&B (CG 100.06 verified by hand), SoD 403, pilot-mismatch 403, turn/quiet-hours/overlap boundaries (half-open edges allowed), cancel tiers (full/10%/75%), hold expiry at boundary, credit waterfall + expiry, fatigue lock at 480 min + run-ops reset, complaint quota auto-suspension cascade, aircraft ground cascade, pagination meta. All passed. Then killed and relaunched the server and confirmed a **completely empty store** on fresh boot (total_count 0 on all collections), confirming per-test-server isolation compliance. Test server was killed afterward; no stray processes left.

## Step 5: Generate unit tests — 2026-08-14T00:45:00.000Z

Everything resolves. Generation is complete and fully audited.

## Summary

**File inventory** — `tasks/task_1569_helicopter_tour_sightseeing_operations/`

- `test_helpers/` (9 files): `__init__.py` (barrel: framework + PRD-specific), `types.py` (12 entity TypedDicts — `WeatherObservation` correctly omits `updated_at`/`version`, 15 status enums, `UserRole`), `api_client.py` (45 methods covering all 47 PRD endpoints incl. `/_clock/set_current_utc`), `api_errors.py` (all 36 error IDs + HTTP map, registered via `set_error_http_status_map`), `assertions.py` (per-entity asserts + `parse_instant`/`assert_instant_equals`/`assert_cg` + seat/payment/credit invariants), `factories.py`, `constants.py` (all PRD thresholds), `test_users.py` (opaque-role constants incl. disp-1/disp-2 + `make_pilot_headers` for the entity-backed Pilot), `fixtures.py` (5 tiers: clock/creators, ops-env, booking+check-in chains, manifest-close/dispatch/complete lifecycle, complaint/credit minting composites).
- `test_suite/` (16 files): `conftest.py` + 15 test modules, **105 tests**, all import-executed clean against the installed framework.

**Test counts per source queue**
- Queue A (Difficulty): **18/18 instances, exactly 2 tests each = 36 tests.**
- Queue B (Corner): **68/68 non-stub instances covered = 69 tests** (one instance, `dispatch_requires_pilot_ack_then_succeeds`, split into reject/succeed halves). The 11 `excluded_because:` stubs (3 complexity-layer, 8 error-catalog) were not translated; all their cross-references resolve to real queue-A instances.

**Skipped instances: 0.** Every instance passed the PRD-first two-condition filter.

**Design-tag confirmation:** automated audit verified all 105 docstrings end with exactly one `Design:` line resolving to a real instance; 200 quoted PRD sentences all survive literal grep of `PRD.md`; zero skip/xfail markers; zero scaffold-reference leakage.

**Four design-index defects corrected in translation** (asserted outcomes preserved, recipes adjusted to stay PRD-faithful):
1. `departure_in_past_rejected` — recipe's DELAY leg targeted 12:30 with the clock at 12:00 (future, would succeed). Retargeted DELAY to 11:30 (genuinely past) so `ERR_DEPARTURE_IN_PAST` is the unique PRD outcome.
2. `cancel_refund_tier_boundaries` — recipe stacked 3 bookings on one 4-seat flight; the third would price at the 50% load tier (27500) and its 25000 confirm would fail. Gave each booking its own flight (3 aircraft/3 pilots, same departure) so all quotes are 25000 and the tier boundary arithmetic holds.
3. `dispatch_requires_pilot_ack_then_succeeds` and `dispatch_marks_no_show_and_expires_held` — recipes issued PILOT_ACK after close-manifest (MANIFEST_CLOSED), a transition PRD §3.3 declares only from SCHEDULED/DELAYED. Reordered the ack to while-SCHEDULED.
4. Initial-`version == 1` and absolute `created_at == logical clock` assertions dropped (PRD silent on both); replaced with relative/instant-based assertions (`expires_at − created_at == hold_expire_minutes`; timestamp comparisons via parsed instants, tolerating the PRD's 3-fractional-digit format).

## Step 7: Run tests and iterate — 2026-08-14T01:20:00.000Z

All 8 rounds pass 105/105 with zero failures. The sweep is clean.

## Summary

**Iterations run:** 2 (initial sweep identified 7 distinct failing tests; fixed all in one batch; second sweep confirmed all 105 tests pass across all 8 parallel rounds).

**Tests deleted:** None. All 7 failures were fixable without deletion.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `test_suite/`:**

1. `test_suite/test_03_pricing_and_seasons.py` — added missing `from test_helpers.fixtures import create_base` import. The `test_season_adjacent_windows_allowed_overlap_rejected` test called `create_base()` without importing it (NameError). This was a test bug.

2. `test_suite/test_14_complaints.py` — in `test_third_substantiation_suspends_route_and_cancels_flights` and `test_suspension_cascade_credits_booking_and_blocks_scheduling`, replaced `substantiate_complaint(c3)` with `complaint_event(c3, "SUBSTANTIATE")`. The `_setup_quota_cascade` helper had already advanced c3 from LOGGED to UNDER_REVIEW; calling `substantiate_complaint` (which does REVIEW + SUBSTANTIATE) attempted REVIEW again from UNDER_REVIEW, tripping the PRD-required `ERR_INVALID_STATE` gate. This was a test bug — the test failed to express the PRD's stated state machine.

**Fixes applied to `implementation/`:**

3. `workspace/implementation/routes_bookings.py` — `move_booking`: removed `b['paid_cents'] -= refund` on the negative-delta branch. PRD §3.8's relock rule ("credits_applied_cents is recomposed as the new quoted_total_cents minus the new paid_cents") combined with the §3.8 fiscal invariant ("paid_cents always equals refunded_card_cents plus credited_cents plus retained_fee_cents") requires paid_cents to remain the historical paid amount; the refund is tracked in `refunded_card_cents`. The implementation was double-subtracting, which broke the test's `paid_cents == 5000` and `credits_applied_cents == 5000` assertions.

4. `workspace/implementation/routes_weather_complaints.py` — `create_observation`: relaxed the cascade trigger. The previous code required the new observation to satisfy `governing_observation(...)['id'] == o['id']`, which under the PRD's posture rule ("the governing observation is the one with the greatest `observed_at` at or before now") excludes observations whose `observed_at` is in the future. Under that strict reading, a forward-dated adverse observation would never fire the cascade — yet the cascade window is defined from `observed_at` to `validity_until`, which only has effect on flights departing within that future window. The fix fires the cascade for any newly posted adverse observation that supersedes the prior latest observation for the base (by `(observed_at, _seq)`), so the cascade window's semantics are honored without changing the posture rule.

**Final state:** all 8 rounds of the parallel sweep pass 105/105 tests with zero failures and zero errors.

## Step 8: Finalize PRD — 2026-08-14T01:35:00.000Z

Produced `workspace/PRD_FINALIZED.md`.

**Line counts:** PRD.md 294 lines → PRD_FINALIZED.md 294 lines (0% line delta; two sentences revised inline, no sections added or removed).

**Changes (2 edits, both traced to step_7_diff implementation fixes 3 and 4; test-suite fixes 1-2 were pure test bugs — a missing `create_base` import and a helper double-firing REVIEW — over behavior PRD §3.9 already pins, so they required no PRD change):**

- §3.2 (weather surveillance) — revise — replaced the cascade trigger "when a newly posted adverse observation becomes the governing one, the base flips NORMAL → WEATHER_HOLD and the weather cascade fires" with a trigger decoupled from the posture rule: the cascade fires when a newly posted adverse observation supersedes every previously posted observation of its base (no prior observation has a greater `observed_at`; ties on `observed_at` favor the newly posted one), explicitly including forward-dated observations, which pre-cancel flights inside their future `[observed_at, validity_until)` window while not governing posture until now reaches `observed_at` — `implementation/routes_weather_complaints.py:63-70` (trigger), `implementation/domain.py:394-403` (window).
- §3.8 (move settlement) — revise — on a negative delta, the card refund now explicitly adds to `refunded_card_cents` while `paid_cents` is left unchanged as the historical amount paid (previously the PRD said only "the card refund is the smaller of the delta's magnitude and `paid_cents`" without naming where the refund lands or whether `paid_cents` decreases) — `implementation/routes_bookings.py:262-266` (negative branch), `:271` (relock formula unchanged).

**Per-edit pre-edit search log:**

1. **Edit §3.8 (move negative delta).**
   (a) Subject: booking money fields (`paid_cents`, `refunded_card_cents`, `credited_cents`, `retained_fee_cents`, `credits_applied_cents`) in move settlement.
   (b) Enumerated via grep over all of `implementation/`: `routes_bookings.py:81-85` (create zeros), `:152` (apply-credit), `:183` (confirm sets paid), `:215-217,222` (voluntary cancel tiers), `:256` (move positive delta grows paid), `:262-266,271` (move negative branch — the Step 7 site), `domain.py:364` (release_applied_credits), `domain.py:378-379` (cascade: credited=paid, mint paid+applied), `routes_flights.py:207` (dispatch NO_SHOW: retained=paid), `routes_admin.py:125-129` (run-ops HELD expiry). Also re-checked the §3.8 cancellation-tier fiscal-invariant sentence and the §3.5 confirm rule for interplay.
   (c) Wording scoped strictly to the move's negative-delta branch ("the refund adds to `refunded_card_cents` while `paid_cents` itself is left unchanged") so no other settlement path is mis-described; the existing relock sentence ("`credits_applied_cents` recomposed as the new `quoted_total_cents` minus the new `paid_cents`") was left verbatim since it is consistent once `paid_cents` is pinned as unchanged on this branch. Verified numerically against `test_11` (paid 5000, refund 5000, excess 15000 minted, credits_applied recomposed to 5000).

2. **Edit §3.2 (weather cascade trigger).**
   (a) Subject: weather-cascade firing condition and its coupling to the governing-observation/posture rule.
   (b) Enumerated: `routes_weather_complaints.py:63-70` (the Step 7 site — `>=` comparison on `(observed_at, _seq)` against all prior same-base observations including future-dated ones), `domain.py:85-100` (`governing_observation` restricted to `observed_at <= now`; `compute_posture`), `domain.py:394-403` (`weather_cascade` window/statuses), `domain.py:519` (posture in `ser_base`), `routes_flights.py:194,275` (dispatch and open-boarding posture gates), `store.py:47-49` (`_seq` monotonic ⇒ observed_at ties favor the newly posted). Read all four weather tests in `test_suite/test_08_dispatch_and_weather_gates.py` (two cascade tests post forward-dated observations — 12:30 with clock 12:00, and 13:55 with clock 13:00 — and require the cascade to fire).
   (c) Dropped the original "the base flips NORMAL → WEATHER_HOLD" clause from the trigger sentence: under the widened trigger that clause would be a false universal (a forward-dated observation does not flip posture at posting time, and even a governing adverse observation whose validity already lapsed leaves posture NORMAL). Posture remains fully and exactly pinned by the untouched preceding sentence ("Posture is WEATHER_HOLD exactly when…"). Used "cannot be the governing observation for posture before now reaches its `observed_at`" rather than "becomes governing at `observed_at`" to avoid asserting governance that a later-posted observation could preempt.

## Step 9: Complete PRD — 2026-08-14T02:00:00.000Z

PRD_COMPLETED.md is written. Summary:

**Source vs output**: `PRD_FINALIZED.md` (294 lines / 49,641 chars) → `PRD_COMPLETED.md` (294 lines / 52,261 chars), char-delta **+2,620**. All changes are inline inserts/revisions inside existing paragraphs — no new sections, no new paragraphs, line count unchanged.

**Counts**: 21 ambiguity-pins, 4 mismatch-revisions (25 changed passages total).

**Changes** (section — insert|revise — ambiguity|mismatch — what changed — impl ref):

- §2.1 — insert — ambiguity — Pilot must pass `pilot_id` filter equal to `X-User-ID` on `GET /duty-days`; omitting it is `ERR_UNAUTHORIZED_ROLE` — routes_admin.py:460-464
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped, not rejected; non-integer is `ERR_INVALID_REQUEST` — validate.py:136-152
- §2.3 — insert — ambiguity — `created_at` list-sort ties break by creation order (`_seq` insertion counter) — domain.py:736-737, store.py:47-49
- §2.4 — insert — ambiguity — `version` starts at 1 — store.py:56-65
- §2.4 — insert — ambiguity — body foreign keys validated in the order the endpoint names them (flight create: base, route, aircraft, pilot) — routes_flights.py:68-72
- §2.4 — insert — ambiguity — undefined path or unsupported method surfaces `ERR_NOT_FOUND` (404) — app.py:31-37
- §2.5 — insert — ambiguity — clock may be set to any instant, earlier or later — routes_admin.py:492-499
- §2.8 — insert — ambiguity — quiet-hours window with start > end wraps midnight (inside = at/after start or before end) — domain.py:292-296
- §3.1 — insert — ambiguity — `PATCH /bases` accepts exactly the create-time fields; `posture`/`ops_run_index` never settable — routes_admin.py:91-106
- §3.1 — insert — ambiguity — `multiplier_bps` outside 1–30000 fails request validity with `ERR_INVALID_REQUEST` — routes_admin.py:249-250
- §3.1 — insert — ambiguity — START_MAINTENANCE refusal with future active flights is `ERR_INVALID_STATE` — routes_admin.py:379-386
- §3.2 — insert — ambiguity — governing-observation ties break by greatest `created_at`, then creation order — domain.py:93
- §3.3 — insert — ambiguity — neither reassignment nor delay resets `pilot_acknowledged` — routes_flights.py:155-163, 182-189
- §3.3 — revise — mismatch — DELAY gate order pinned to impl: duty (flight time, then span) → noise class → quiet hours → departure-in-future → aircraft turn → pilot overlap, and no others (PRD's prior list order differed) — routes_flights.py:173-181
- §3.3 — insert — ambiguity — PILOT_ACK: non-Pilot role refused with `ERR_PILOT_MISMATCH` before any state check; for Pilot, state check precedes identity match — routes_flights.py:248-257
- §3.4 — revise — mismatch — `duty_minutes_projected` spans the non-cancelled set (COMPLETED included), not "active flights" — domain.py:207-241, 244-255
- §3.5 — insert — ambiguity — booking creation imposes no flight-status requirement; duplicate-name check runs after the estimate and capacity gates — routes_bookings.py:56-68
- §3.5 — insert — ambiguity — confirm's flight-state check (`ERR_INVALID_STATE`) sits after hold-expiry, before amount — routes_bookings.py:176-181
- §3.6 — insert — ambiguity — waiver signing and briefing completion carry no booking-state guard — routes_bookings.py:323-331
- §3.6 — insert — ambiguity — check-in requires passenger not already checked in (`ERR_INVALID_STATE` first) — routes_bookings.py:333-334
- §3.6 — insert — ambiguity — UNCHECK permitted only while passenger checked in and booking CONFIRMED/CHECKED_IN — routes_bookings.py:357-361
- §3.8 — insert — ambiguity — every HELD→EXPIRED transition (batch tick, dispatch housekeeping, cancellation cascade) releases applied credits like a HELD cancel; a credit already EXPIRED keeps that status — routes_bookings.py:199, domain.py:344-364, routes_flights.py:209-212, routes_admin.py:126-129
- §3.8 — insert — ambiguity — voluntary cancellation lands the booking in CANCELLED (status was unnamed in PRD) — routes_bookings.py:200, 223
- §3.8 — insert — ambiguity — a settlement leg that would mint zero cents mints no credit — domain.py:382-383, routes_bookings.py:218-222, 265-266
- §3.9 — revise — mismatch — auto-match ranks by the whole-minute floor of the absolute distance (PRD said plain "absolute distance"), ties → earlier departure → earlier `created_at` → creation order — domain.py:493-497
- §3.9 — revise — mismatch — complaint quota is scoped per base (complaints are base-filed, routes global): substantiation triggers on the complaint's own base's window/threshold; the route read field aggregates across bases; resume requires every base's scoped count below its threshold — domain.py:107-133, routes_weather_complaints.py:187-194, routes_admin.py:231-232
- §3.9 — insert — ambiguity — LINK_FLIGHT permitted from any complaint status — routes_weather_complaints.py:170-178
- §3.9 — insert — ambiguity — `resolution_note` optional on CLOSE; omitted leaves the field null — routes_weather_complaints.py:161, 203-205

Everything else in the PRD (envelope shape, OCC quartet, create-flight gate order, quote waterfall, manifest W&B order, dispatch guard order, cancel tiers, cascade semantics, weather cascade trigger, error catalogue) matched implementation exactly and was left untouched.
