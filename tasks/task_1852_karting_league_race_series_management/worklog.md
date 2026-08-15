# Worklog — task_1852_karting_league_race_series_management

## Step 1: Create Task Directory — 2026-08-14T20:51:54.400Z

Directory `tasks/task_1852_karting_league_race_series_management/` and `workspace/` already existed (pre-created by the pipeline launcher); verified, no scan or index computation performed per instructions.

## Step 2: Generate Scaffold — 2026-08-14T21:35:33.925Z

Scaffold generation complete. All three artifacts are written and lint-clean.

## Files

- `/home/ubuntu/github/CodingPRD/tasks/task_1852_karting_league_race_series_management/SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1852_karting_league_race_series_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:` (§1.8)
- `/home/ubuntu/github/CodingPRD/tasks/task_1852_karting_league_race_series_management/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:` (§1.9)

## Counts

- **Entities: 11** — LeagueSeason, RaceClass, Driver, RentalKart, RaceEvent, EventEntry, RaceSession, SessionResult, TechInspection (append-only, `common_fields: false`), Incident, PracticeBooking. Hybrid topology: season→event tree plus flat drivers/karts/bookings with cross-aggregate FKs.
- **State machines: 9** — including two cyclic ones (EventEntry TECH_FAILED→TECH_CHECK re-inspection loop with a 2-fail disqualification threshold; Incident UPHELD→APPEALED→UNDER_REVIEW appeal loop capped at 1 appeal) and branching RaceEvent with a CANCELLED cascade.
- **Calculations: 7** — class_eligibility (age at event_date, inclusive bounds), weight_compliance (>= boundary), session_points (position table + conditional fastest-lap bonus), season_standings (dual-variant: provisional vs final with drop-rounds), championship_tiebreak (countback → latest-best-round → driver created_at), practice_billing (FLAT vs METERED with pinned per-booking round-half-up order), kart_booked_minutes.
- **Validations: 10 priority tiers** (auth → authorization/segregation → request shape → existence → OCC → state → safety → temporal → constraint → fiscal).
- **Endpoints: 54**, all under `/karting`, incl. computed standings read and full FK reverse-reachability GETs.
- **Errors: 27**, each referenced in §1.2/§1.4 and covered by at least one §1.8/§1.9 test.
- **Roles: 4** — LeagueAdmin/RaceDirector/Steward (opaque), Driver (`entity_backed:Driver`); segregation of duties: incident reporter cannot adjudicate the same incident (ERR_SELF_ADJUDICATION), appeals only by the penalized entry's driver.
- **Difficulty instances: 18** (9 rules × 2), with differentiating pairs: standings-vs-billing domains (Rule 1); mode-(a) points formula vs mode-(b) rounding order (Rule 2); entry vs incident cycles (Rule 3); depth-3 penalty cascade vs depth-2 cancel-refund cascade (Rule 4); state-vs-safety and temporal-vs-constraint priority pairs (Rule 5); weight-equality vs empty-counted-set boundaries on different endpoints (Rule 6); EventEntry→RaceEvent and RaceEvent→Incident pairs (Rule 7); half-open pairwise kart overlap vs aggregate track capacity (Rule 8); session-points sum vs fee-ledger cents invariants (Rule 9).
- **Corner instances: 47** (42 full recipes + 5 `excluded_because:` stubs), spanning all nine claim sections.

## Key design notes

- **OCC (§1.2.1)**: two true-race rules only — session create against `RaceEvent.version`, result-batch supersede against `RaceSession.version`; both endpoints take `expected_*_version` and bump the parent version. All other write-write conflicts were re-classified as state preconditions.
- **Penalty cascade**: TIME_SECONDS re-ranks session results by `total_time_ms + penalty_seconds*1000` (tie → prior finish_position), rewrites positions, marks results AMENDED, recomputes points → event_points → standings; appeal+DISMISSED is the exact compensation (asserted via the 47-point conservation test).
- **Pre-computed literals**: all formula-derived asserts were executed numerically (e.g., METERED 60 min = 9743 vs FLAT 4000; per-booking rounding 3735+3735=7470 vs aggregate 7469; standings 47/25 with drops [2]/[1]).
- `scaffold_lint.py` verdict, verbatim: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (54 endpoints, 11 entities, 18 + 47 instances, 888 calls scanned). Two fixes were needed en route: quoting `?`-suffixed flow scalars and bracketed `grounds` items, and renaming nested path placeholders to `{id}` for the lint's sub-resource FK check.

## Step 3: Copy Shared Files — 2026-08-14T21:36:02.792Z

Copied `./INSTRUCTION.md` → `tasks/task_1852_karting_league_race_series_management/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T21:50:57.542Z

All checks pass. The generation is complete. Summary:

## Task 1852 PRD Generation — Complete

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1852_karting_league_race_series_management/workspace/PRD.md` — 290 lines.

### Section list
- **§1 Introduction** (2 paragraphs, business-context angle)
- **§2 Global Specifications** — 2.1 RBAC (with per-role `identity:` translation: Driver entity-backed, LeagueAdmin/RaceDirector/Steward opaque), 2.2 API Response Structure (verbatim block, verified byte-markers `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `UNIQUE_ERROR_IDENTIFIER_STRING`, `"data": { }`), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), 2.4 Common Resource Properties (incl. TechInspection append-only exception: no `updated_at`/`version`), 2.5 Precision (weights 1dp exact, age floor, integer points, integer cents round-half-up), 2.6 OCC (both rules), 2.7 Nested Retrieval (left-to-right, parent scoping), 2.8 Validation Order (10 tiers, explicit precedence), 2.9 Season Treasury (fee snapshot/pay/refund/recompute), 2.10 Half-Open Windows, Overlap, Track Capacity
- **§3 Business Logic** (8 subsections, chronological lifecycle grouping): 3.1 Seasons/Classes/Points Scheme, 3.2 Drivers/Rental Fleet, 3.3 Events/Entry Registration, 3.4 Tech Inspection/Grid Locking, 3.5 Sessions/Results/Scoring, 3.6 Incidents/Adjudication/Appeals, 3.7 Standings/Drop Rounds/Tiebreak, 3.8 Practice Bookings/Billing
- **§4 Endpoint Definitions** — 54-row table, 4 columns (Method, Path, Description, Authorized Role(s)); all 42 unique scaffold paths verified present
- **§5 Error Code Catalogue** — 27 rows, 2 columns (Error ID, HTTP Status Code)

### Hard Contract reports
- **Contract 1 (Field-Name Coverage):** entities[].fields: 58 required, 58 present, 0 missing; endpoint input/query/path identifiers: 17 required, 17 present, 0 missing (75 total, fence-aware extraction). **PASS**
- **Contract 2 (Rule Coverage):** validations priority: 10 tiers expressed with explicit masking order; OCC: 2/2 (endpoint + `expected_event_version`/`expected_session_version` + `ERR_STALE_VERSION`/412, no race-framing); state transitions: all 30 expressed with preconditions + side effects (incl. Cascade A hops 1–3, Cascade B hops 1–2, DISMISSED-after-appeal compensation); calculations: 7/7 in precise prose (no pseudocode, constants embedded as $40.00/$1.50-per-minute/8.25%/tenth-or-better); validation conditions: all matchable to error_ids in §2.8 + workflow narratives; applies_to scopes enumerated per tier; field structured content (defaults, initial states, computed-field definitions, null-until-COMPLETED) reconstructible; sibling branches (3 penalty kinds, FLAT/METERED, provisional/final, 4-state withdraw) at equal density. **PASS**
- **Contract 3 (§3 Path Purity):** 396 backtick tokens scanned; 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos. **PASS**

### Zero-Silence coverage audit (scaffold → PRD mapping)
- 11 entities → §2.4 (common props) + lifecycle homes in §3.1–3.8
- 10 state machines → §3.1 (LeagueSeason), §3.2 (Driver, RentalKart), §3.3 (RaceEvent, EventEntry pay/withdraw), §3.4 (EventEntry tech/DISQUALIFIED cascades), §3.5 (RaceSession, SessionResult), §3.6 (Incident), §3.8 (PracticeBooking)
- 2 concurrency rules → §2.6 (+ §3.5 context)
- 7 calculations → §3.3 eligibility, §3.4 weight, §3.5 session_points, §3.7 standings + tiebreak, §3.8 practice_billing, §2.10 kart_booked_minutes
- 10 validation priorities → §2.8 tier list + trigger-local error mentions
- 54 endpoints → §4 table; 27 errors → §5 table, all also in §2/§3 prose (verified mechanically)

### Design decisions worth recording
1. **`ERR_SEASON_NOT_ACTIVE` ambiguity:** the error catalog mentions "class changes" but the state machine requires ≥1 class before activation (a deadlock if class creation required ACTIVE). Resolved by scoping the ACTIVE-gate prose to event creation and registration opening, with class/event creation after `AWARDS_CONCLUDED` separately locked via `ERR_INVALID_STATE` per the scaffold side effect.
2. **`TRACK_CAPACITY_KARTS`** has no numeric value in the scaffold — referenced as a named configured ceiling without inventing a number.
3. **Grid lock over DISQUALIFIED entries:** transcribed faithfully ("every non-`WITHDRAWN` entry"), no carve-out invented.
4. **Constants converted for inference difficulty:** 4000 cents → $40.00, 150 cents/min → $1.50 per minute, 0.0825 → 8.25%, FASTEST_LAP_MAX_POSITION 10 → "tenth or better", threshold 2 → "second failed inspection".
5. The `re-rank` formula rendered as prose: recorded `total_time_ms` plus one thousand milliseconds per second of `penalty_seconds_applied`, ascending, ties to the pre-penalty better `finish_position`.

## Step 6: Generate Implementation — 2026-08-14T22:22:04.158Z

All 54 endpoints from the scaffold's endpoint table are implemented (54 route handlers matches exactly). The implementation is complete and verified.

## Summary

**Files created** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1852_karting_league_race_series_management/workspace/implementation/`):

- `start.sh` — foreground launcher; guarded `pip install` (no-op once Flask is importable), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=2.2`
- `app.py` — Flask entry point, blueprint registration under `/karting`, global write-lock serialization, ApiError/404/405 handlers emitting the standard error envelope
- `db.py` — 11 in-memory dict collections; boots empty, no seeding
- `errors.py` — full 27-error catalog with exact IDs and HTTP statuses from PRD §5
- `response.py` — envelope helpers (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more` only on paginated endpoints)
- `middleware.py` — X-User-ID/X-User-Role auth (401), role gates (403 ERR_FORBIDDEN), driver-ownership helper
- `validate.py` — body validators (types, enums, dates, datetimes) raising ERR_INVALID_REQUEST
- `util.py` — UUIDs, monotonic 3-fractional-digit UTC timestamps, 365.25-day floored age math, Decimal weight comparison, metered-fee `round_half_up(minutes*150*1.0825)`
- `services/core.py` — record factory, `touch()` (updated_at + version+1), on-read computed fields (`rounds_completed`, `collected_fees_cents`, `tech_fail_count`, `event_points`), serializers, pagination
- `services/calculations.py` — session points (fastest-lap tie by finish position, position-10 bonus cap, DISQUALIFIED zeroing), effective-time re-rank, standings with drop-rounds (score ASC/round ASC drop boundary) and the 4-level championship tiebreak (countback → latest-best-round → driver created_at)
- `services/cascades.py` — disqualification cascade, TIME_SECONDS apply/reverse (penalty → re-rank → AMENDED → points recompute), event-cancel refund cascade
- `routes/` — 8 modules: seasons (+classes +standings), drivers, karts, events (+lock-grid), entries (+pay/withdraw/inspections), sessions (+results/score), incidents (report/open-review/adjudicate/appeal), bookings

**Endpoint count:** 54 — matches the scaffold endpoint table exactly.

**Subsystem organization:**
- *State machines* live in the route handlers with explicit transition tables (drivers/karts) and gated lifecycle actions (seasons, events, sessions, incidents, bookings); the EventEntry tech machine (TECH_CHECK self-resolution, 2-FAIL threshold DQ, GRID_LOCKED-FAIL immediate DQ) is in `routes/entries.py`
- *Calculations* are isolated in `services/calculations.py`; derived fields reconcile on read for immediate consistency
- *OCC*: `expected_event_version` (session create) and `expected_session_version` (result batch) checked at priority 5, both required int fields, mismatch → 412 ERR_STALE_VERSION; writes bump parent version
- *Validation priority* follows PRD §2.8 tiers literally: auth → RBAC/ownership/segregation (ERR_SELF_ADJUDICATION, ERR_NOT_ENTRY_DRIVER checked as soon as the resource resolves, before body checks) → body → existence/scope → OCC → state → 422 eligibility → overlap → uniqueness/capacity → 402 fiscal gate (lock-grid checks TECH_PASSED before PAID)
- *Cascades* in `services/cascades.py`; the DISMISSED-after-appeal compensation uses internal `_applied_penalty` bookkeeping (never serialized) to subtract penalty seconds and re-rank/recompute identically to the UPHELD path

**Boot smoke test results:** `start.sh` on ports 18452–18455 booted in ~2–3 s. Verified: unauthenticated GET → 401 ERR_UNAUTHENTICATED envelope; POST /karting/karts → 201 with server-minted UUID; kill -9 + relaunch → `total_count == 0` (in-memory wipe confirmed). Two custom end-to-end suites passed against a start.sh-launched instance: SMOKE OK (full race flow: season→class→activate→drivers→event→entries→pay→inspections→start→lock-grid→OCC session create (412 on stale)→results→score with fastest-lap tie + bonus (27/22 pts)→TIME_SECONDS penalty cascade (positions swap, AMENDED, points 22/27)→appeal→DISMISSED compensation restoring position/points→complete→finalize→standings with drop-rounds→FLAT 4000 vs METERED 9743 billing→overlap rejection with touching-endpoint acceptance→pagination envelope) and EDGE OK (2-FAIL threshold DQ, post-race GRID_LOCKED FAIL immediate DQ, re-inspection loop, exact-weight-equality PASS, age-16-exact boundary vs age-15 rejection, registration-closed shadowing class-mismatch, lock-grid 402/409 gates, ERR_RESULTS_INCOMPLETE, batch supersede, drop-round standings with tiebreak rank swap after season finalize, event-cancel refund cascade to 0, duplicate round/class/entry, rental eligibility trio, self-adjudication 403, appeal limit, track capacity 4, 23-minute metered = 3735).

## Step 5: Generate Unit Tests — 2026-08-14T22:26:24.427Z

Done. All generation and self-checks complete.

## Summary

**Output locations**
- `/home/ubuntu/github/CodingPRD/tasks/task_1852_karting_league_race_series_management/test_helpers/` — `__init__.py` (barrel), `types.py` (10 entity TypedDicts incl. append-only `TechInspection` without `updated_at`/`version`, 16 status/role enums), `api_client.py` (45 endpoint methods), `api_errors.py` (27 error IDs + HTTP map registered with the framework), `assertions.py` (11 entity assertions + `standings_row_for`), `factories.py` (12 payload factories), `constants.py` (PRD §3.4/§3.5/§3.8 thresholds), `test_users.py` (4 roles, `make_driver_headers` for the entity-backed Driver role), `fixtures.py` (composite builders through grid-lock, scored sessions, completed events, multi-round championships, incidents, bookings).
- `.../test_suite/` — `conftest.py` + 8 test files, **81 tests total**.

**Queue A (Difficulty)** — 34 tests, 2 per translated instance, all 17 translated instances covered:
- `dual_variant_calc`: standings_provisional_vs_final_drop_rounds (2), booking_flat_vs_metered_fee (2)
- `combinatorial_formula`: session_points_position_bonus_conditionals (2), metered_billing_per_booking_rounding_order (2)
- `non_linear_state_machine`: entry_tech_reinspection_cycle (2), incident_appeal_review_cycle (2)
- `transitive_cascade`: penalty_reorders_results_points_standings (2 — hop-3 standings read is done after completing the event, since PRD §3.7 counts only COMPLETED/FINALIZED events), event_cancel_withdraws_entries_refunds_fees (2)
- `priority_pair_validation_conflict`: entry_closed_registration_shadows_class_mismatch (2), booking_overlap_shadows_track_capacity (2)
- `boundary_precision_check`: weight_exact_minimum_passes (2), drop_rounds_equal_completed_counts_zero (2)
- `cross_entity_state_dependency`: entry_requires_event_registration_open (2), event_finalize_blocked_by_open_incident (2)
- `resource_temporal_overlap`: kart_half_open_window_overlap (2)
- `compensating_invariant`: penalty_apply_reverse_conserves_session_points (2), pay_withdraw_conserves_collected_fees (2)

**Skipped (1 instance)** — `Difficulty/resource_temporal_overlap/track_aggregate_capacity_window`: fails unique derivability. The PRD (§2.10) names the ceiling `TRACK_CAPACITY_KARTS` but never states its value; the instance's assertion (5th booking rejected with 4 already parked) holds only if the ceiling is exactly 4, which a PRD-only implementer cannot derive. No test emitted. For the surviving shadow test (`booking_overlap_shadows_track_capacity`) I reduced the pre-existing bookings from 4 to 2: the asserted `ERR_BOOKING_OVERLAP` is invariant to the ceiling value (tier 8 masks tier 9 per PRD §2.8's fixed order), while a 4-booking setup would break under any conforming implementation choosing a ceiling below 4.

**Queue B (Corner)** — 47 tests, 1 per non-stub instance (entities 6, state_machines 8, calculations 5, validations 17, rbac 6, endpoints 2, complexity_layers 2, consistency_model 1). All 5 `errors`-section stubs were left untranslated; their `difficulty_instance` cross-references all resolve.

**Notable adjudications**
- `season_creation_defaults` / `driver_system_fields_and_initial_state`: the PRD (§2.4) never pins the initial `version` value (unlike sibling task PRDs that say "starts at 1"), so the literal `version == 1` sub-assertion was dropped in favor of presence/type; all other instance assertions (status, zeroed counters, defaults, timestamps, UUID) are asserted at full strength.
- No priority-ordering test was skipped: PRD §2.8 explicitly enumerates the fixed tier order, covering both queue-A shadow instances verbatim.

**Self-checks (all run)**
- `py_compile` on all 17 files: OK
- pyflakes (excluding intentional barrel re-exports): clean
- pytest `--collect-only`: 81 tests collected, no import errors
- Tag audit script: every test has exactly one terminal `Design:` line resolving to a real instance; all 17 translated difficulty instances have ≥2 tests; all 47 corner non-stub instances have ≥1; no stub translated; only the intentionally skipped instance reports undercovered
- Citation audit script: all 128 `PRD §x.y: "..."` docstring quotes grep verbatim against `workspace/PRD.md` (whitespace-normalized): OK

## Step 7: Run Tests and Iterate — 2026-08-14T22:38:38.947Z

All 8 rounds pass: 81/81 × 8 = 648/648 test executions. The sweep is clean and stable. (Orchestrator independently verified all 8 `results.{i}.json`: passed 81 / total 81 in every round.)

## Summary

**Iterations run:** 2 (sweep 1 diagnosed, one fix applied, sweep 2 clean 8/8)

**Tests deleted:** None. Every test in the suite traces to verbatim PRD prose; no PRD-silence or unique-derivability violations found.

**Fixes applied to `test_helpers/`:**
- `test_helpers/api_client.py` — added an `ApiClient._request` override that injects `Connection: close` on every request. Why: the runner's `per-test-server` isolation SIGKILLs and rebinds the server on the same port before every test; the session-scoped `requests.Session` pooled keep-alive connections to the killed instance, and a later POST/PATCH on a dying pooled socket failed with `RemoteDisconnected` / `ConnectionResetError` (requests' default adapter applies zero retries, and POST/PATCH are never retried). Forcing per-request connections eliminates the stale-pool race deterministically, with no retry-double-apply risk. Asserted semantics are unchanged — this is transport hardening of the test harness only.

**Fixes applied to `test_suite/`:** None.

**Fixes applied to `implementation/`:** None. The implementation was logically correct throughout — in sweep 1 every assertion-level check passed in all 8 rounds; the only failures (4/648: `test_driver_suspend_reinstate_cycle` in rounds 2/3/5, `test_per_booking_rounding_not_aggregate_rounding` in round 1) were TCP-level connection aborts with no server-side traceback (verified across `/tmp/prd_bench_server_*.log`), i.e., test-harness transport flakiness under the 8× concurrent restart load, not an implementation defect.

**Root-cause note for the record:** failure signature was `requests.exceptions.ConnectionError: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))` / `ConnectionResetError(104, ...)` landing on non-idempotent requests mid-test — the classic stale keep-alive connection reuse after a same-port server restart, surfacing only under parallel sweep load.

## Step 8: Finalize PRD — 2026-08-14T22:40:58.549Z

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1852_karting_league_race_series_management/workspace/PRD_FINALIZED.md` — produced as a byte-identical copy of PRD.md (verified via `cmp` and matching md5 `d7e34eada1a6507c3855daf6d59cefc7`).

**Line counts / delta:** PRD.md = 289 lines, PRD_FINALIZED.md = 289 lines, 0% delta. **Zero edits were made.**

### Justification for zero edits

The `<step_7_diff>` contains exactly one fix, and it is transport-level test-harness hardening only:

- **test_helpers/api_client.py** — an `ApiClient._request` override injecting `Connection: close` on every request, to defeat a stale keep-alive pooled-connection race between the session-scoped `requests.Session` and the per-test-server isolation runner (which SIGKILLs and rebinds the server on the same port before each test). Step 7's own diagnosis confirmed the implementation was logically correct in all 8 rounds; the 4/648 failures were TCP-level client-side aborts with no server-side traceback.

This fix reveals no PRD silence about server behavior:

1. The `Connection` header is a **client-side transport choice**, not a server behavioral choice. The implementation (`implementation/app.py`, stock Flask/Werkzeug dev server via `app.run`) neither requires, inspects, nor emits any connection-management headers, and behaves identically whether clients use keep-alive or per-request close.
2. My pre-edit verification grep across all of `implementation/` (`grep -rniE "connection|keep.?alive|close|header"`) found header handling only for `X-User-ID` / `X-User-Role` in `middleware.py:28-29` — which PRD §2.1 already pins verbatim — and no connection-semantics code anywhere. `response.py` sets no transport headers.
3. PRDs in this benchmark conventionally do not specify HTTP connection management, and no PRD sentence a fresh implementer reads could cause them to build a server that diverges from this one on connection handling — any conformant HTTP/1.1 server satisfies the harness with `Connection: close`.

Any inserted wording about connection semantics would therefore invent behavior the implementation does not exhibit (violating the "never invent behavior" rule) and risk a new mismatch under the NO-NEW-MISMATCH rule. The correct minimal patch is the empty patch.

### Per-edit pre-edit search log

Zero edits were made, so there are no per-edit entries. The single candidate edit (pinning HTTP connection semantics) was evaluated and rejected: (a) subject — HTTP connection/keep-alive semantics; (b) paths enumerated — `implementation/app.py` (full read: no connection handling), `implementation/middleware.py` (full read: auth headers only), `implementation/response.py` (full read: no transport headers), `implementation/start.sh` (full read), repo-wide grep for `connection|keep-alive|close|header` across all routes/services (hits were only auth headers and unrelated status-string matches like `CLOSED`/`ERR_SESSION_NOT_CLOSED`); (c) no wording committed, because no wording could describe a behavior the server actually performs.

## Step 9: Complete PRD — 2026-08-14T22:52:13.215Z

All edits applied cleanly; every change is an in-paragraph insert/revision with no new sections. The work is complete.

## Summary

**Files**
- Source: `/home/ubuntu/github/CodingPRD/tasks/task_1852_karting_league_race_series_management/workspace/PRD_FINALIZED.md` (289 lines, 43,910 chars)
- Produced: `/home/ubuntu/github/CodingPRD/tasks/task_1852_karting_league_race_series_management/workspace/PRD_COMPLETED.md` (289 lines, 45,638 chars; **+1,728 chars**, +0 lines — all edits inline)

**Counts**: 12 ambiguity-pins, 5 mismatch-revisions (17 changes total)

**Changes**

- §2.2 — revise — ambiguity — pagination `meta` fields pinned to paginated list endpoints only; non-paginated lists carry just `api_request_id`/`api_request_timestamp` — implementation/response.py:29-36 (success_array) vs 39-51 (success_list)
- §2.3 — revise — ambiguity — only §4 "paginated" endpoints apply `limit`/`offset`; others ignore them and return all records; non-integer values → `ERR_INVALID_REQUEST`; out-of-range values clamped, not rejected; sort tie-break by `id`; `has_more` defined as `offset + returned < total_count` — implementation/services/core.py:261-289
- §2.4 — insert — ambiguity — `version` starts at 1 at creation — implementation/services/core.py:26-35
- §2.10 — insert — ambiguity — `TRACK_CAPACITY_KARTS` value pinned to 4 (PRD named the constant but never gave its value) — implementation/services/core.py:16
- §2.10 — revise — mismatch — deleted the "fleet availability read model / booked minutes per day" sentence; no endpoint or code path exposes or computes it — no impl counterpart (routes/bookings.py has none)
- §3.1 — revise — mismatch — class creation permitted while season is `SCHEDULED` **or** `ACTIVE` (was: only `ACTIVE`, which made activation's class precondition unreachable); `FINALIZED` breaches → `ERR_SEASON_NOT_ACTIVE`; `AWARDS_CONCLUDED` lock → `ERR_INVALID_STATE` — implementation/routes/seasons.py:110-116
- §3.2 — revise — mismatch — dropped "unique" from `fleet_number` (impl enforces no uniqueness; no error code exists for it) — implementation/routes/karts.py:22-33
- §3.3 — insert — ambiguity — `event_date` pinned as ISO 8601 date or datetime; only the calendar date feeds age eligibility — implementation/routes/events.py:36, util.py:43-58
- §3.3 — revise — mismatch — event creation in a non-`ACTIVE` season: `ERR_SEASON_NOT_ACTIVE`, except `AWARDS_CONCLUDED` → `ERR_INVALID_STATE` — implementation/routes/events.py:22-28
- §3.3 — insert — ambiguity — paying an entry whose `fee_status` is not `UNPAID` fails with `ERR_INVALID_STATE` — implementation/routes/entries.py:150-151
- §3.4 — insert — ambiguity — disqualification does not re-rank sessions or reassign fastest lap; disqualified results still participate in the fastest-lap comparison, and no other result's flag/points change — implementation/services/cascades.py:24-29, calculations.py:60-94
- §3.5 — revise — mismatch — dropped "unique within the event" from session `sequence` (impl enforces no uniqueness) — implementation/routes/sessions.py:26-49
- §3.6 — insert — ambiguity — `UPHELD` with omitted `penalty_kind` recorded as `NONE`; penalty fields on a `DISMISSED` ruling are validated but recorded as null with no cascade — implementation/routes/incidents.py:111-119, 142-165
- §3.7 — revise — ambiguity — standings rows pinned to drivers holding an entry in the class in at least one *counted* event — implementation/services/calculations.py:107-121
- §3.7 — insert — ambiguity — missing `class_id` → `ERR_INVALID_REQUEST`; `class_id` from another season → `ERR_NOT_FOUND` — implementation/routes/seasons.py:94-99
- §3.7 — insert — ambiguity — `dropped_round_numbers` listed in discard order (score asc, then `round_number` asc) — implementation/services/calculations.py:126-133
- §3.8 — insert — ambiguity — `start_time`/`end_time` pinned as ISO 8601 datetimes; `minutes_used` discards sub-minute remainder — implementation/routes/bookings.py:41-42, util.py:105-107

**Verified already-aligned (no change needed)**: all 27 error codes/HTTP statuses, validation tier order (incl. OCC before state preconditions, fiscal gate last), role/ownership model, age formula (365.25-day floor), exact Decimal weight comparison with equality passing, tech state machine with 2-fail disqualify and GRID_LOCKED fail-out, grid-lock all-or-nothing gates (DISQUALIFIED entries, being non-WITHDRAWN, block locking per the literal PRD rule impl follows), session OCC fields and version bumps, supersede semantics of result batches, scoring/fastest-lap/bonus math, penalty cascade re-rank by effective time, DISMISSED-after-appeal reversal, drop-round and countback tiebreak rules, treasury derivation, half-open overlap windows, and the 201/200 status conventions.
