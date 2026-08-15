# Worklog — task_1521_fan_event_contest_cosplay_competition

## Step 1: Create Task Directory — 2026-08-13T18:07:00.000Z

Directory `tasks/task_1521_fan_event_contest_cosplay_competition/` and its `workspace/` subdirectory were pre-created and pre-assigned by the invoking pipeline. Verified existence; no index scan or new directory creation performed (per orchestration args, Step 1 treated as DONE).

## Step 2: Generate Scaffold — 2026-08-13T19:13:27.130Z

Scaffold generation complete. All three artifacts are written under `/home/ubuntu/github/CodingPRD/tasks/task_1521_fan_event_contest_cosplay_competition/` and pass `scaffold_lint.py` with **VERDICT: clean lint** (759 calls scanned across §1.8+§1.9, zero violations; all 18 FKs reverse-reachable).

**Counts**
- Entities: 10 (ContestEvent, Category, Contestant, Judge, Entry, PreJudgingSlot, ScoreSheet, PerformanceSlot, PrizeAward, GreenRoomBooking)
- State machines: 8 (all except Contestant/Judge, which carry cyclic consent items and conflict links as fields)
- Calculations: 7 (entry_final_score, placement_rank_assignment, category_purse_split, prize_payout_net, contest_tax_summary, junior_age_eligibility, stage_sequence_compaction, green_room_overlap_count — 8 counting the capacity calc)
- Validations: 28 ordered rows across priorities 1–12
- Endpoints: 51 (incl. `POST /_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` default)
- Errors: 30, all referenced and triggerable
- Roles: 7 (Anonymous, Contestant entity-backed, ContestLead, Judge entity-backed, SafetyOfficer, StageManager, Treasurer)
- §1.8 instances: 18 (2 per rule × 9 rules, all live)
- §1.9 instances: 41 live + 14 `excluded_because` stubs

**Complexity profile**: workflow_orchestration × temporal_windowing; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; flat topology, cyclic state machines, segregation_of_duties role model (Treasurer maker/checker on PrizeAward).

**Notable design decisions**
- Dual variants sit on different entity domains: TRIMMED_MEAN vs WEIGHTED_MEAN tabulation (Entry) and WITH_W9 vs 24% backup-withholding payout (PrizeAward). All asserted numbers were computed by script (e.g., sheets 8.10/8.70/6.30 → 7.70 vs 8.10; purse 9999 → 5000/3000/1999 with the remainder-absorbs-rounding pin; tie-break fixture ties at 7.00 with craft means 7.67 vs 6.67).
- Rule 4 cascades: depth-3 disqualify chain (Entry → ScoreSheet VOID → Category TABULATED→SCORING → ContestEvent TABULATION→JUDGING) and depth-2 withdraw chain (Entry → PerformanceSlot SKIPPED → gap-free resequence).
- Rule 8 contrasts half-open mutual-exclusion (pre-judging slots per panel, back-to-back legal) with aggregate-capacity overlap (green room, 4 concurrent bookings legal, 5th rejected).
- A mid-design rework worth noting: the safety re-inspection flow was simplified (REJECTED only from SUBMITTED/SAFETY_APPROVED) so that `ERR_SAFETY_NOT_APPROVED` stays genuinely reachable — the stage-queue state gate would otherwise have subsumed it, breaking the §1.8 priority-pair instance.
- Endpoint count (51) exceeds the Expert guideline band deliberately: the scenario's eight operational concerns each require real surface, and FK reverse-reachability forced single-GET + filtered-list pairs per child entity; complexity is concentrated in coupling (cascades, priority ordering, dual variants) rather than CRUD volume.

## Step 3: Copy Shared Files — 2026-08-13T19:13:40.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1521_fan_event_contest_cosplay_competition/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T19:22:00.000Z

PRD generated successfully at `/home/ubuntu/github/CodingPRD/tasks/task_1521_fan_event_contest_cosplay_competition/workspace/PRD.md`.

## Summary

**File**: 266 lines, ~6110 words.

**Section list**:
- §1. Introduction (2 paragraphs, business-context framing)
- §2. Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control (all 7 roles with identity semantics)
  - 2.2 API Response Structure (verbatim from `section-2.2-response-structure.md`)
  - 2.3 Pagination
  - 2.4 Common Resource Properties and Mutation Semantics
  - 2.5 Monetary Values and Precision
  - 2.6 Optimistic Concurrency Control (both OCC rules with `expected_category_version` / `expected_entry_version` → `ERR_STALE_VERSION` 412)
  - 2.7 The Logical Clock (default `2026-08-01T00:00:00Z`)
  - 2.8 Validation Order (priority tiers explicit)
  - 2.9 Hierarchical Consistency and Cascades
  - 2.10 Nested Resource Retrieval
- §3. Business Logic & Workflows (9 subsections, grouped by business process)
  - 3.1 Setting Up the Contest and Its Categories
  - 3.2 Contestants, Judges, and Consent
  - 3.3 Registration, Safety Check-in, and the Entry Lifecycle
  - 3.4 Craftsmanship Pre-Judging
  - 3.5 Scoring and Tabulation
  - 3.6 The Stage Walk
  - 3.7 Prize Awards, Withholding, and Tax Reporting
  - 3.8 Disqualification and Its Cascade
  - 3.9 Green-Room Booking
- §4. Endpoint Definitions (4-column table, 51 endpoints)
- §5. Error Code Catalogue (2-column table, 30 errors)

**Coverage counts**:
- Entities: 10 (ContestEvent, Category, Contestant, Judge, Entry, PreJudgingSlot, ScoreSheet, PerformanceSlot, PrizeAward, GreenRoomBooking) — all fields (58) covered in backticks
- State machines: 8 entities covered — ContestEvent (9 transitions), Category (4), Entry (19), PreJudgingSlot (3), ScoreSheet (6), PerformanceSlot (4), PrizeAward (5), GreenRoomBooking (1) — every transition's from/to, preconditions with error_id, and side-effects expressed in prose
- Calculations: 8 — `entry_final_score` (both WEIGHTED_MEAN and TRIMMED_MEAN variants with trim rule and <3 fallback), `placement_rank_assignment` (3 sort keys, `id` never used), `category_purse_split` (pinned rounding order with 9999 worked example), `prize_payout_net` (both WITH_W9 and BACKUP_WITHHOLDING variants), `contest_tax_summary` (input set + 4 aggregates, no re-rounding), `junior_age_eligibility` (strictly less than 16, boundary inclusive of contest date), `stage_sequence_compaction` (gap-free 1..N, created_at tie-break), `green_room_overlap_count` (half-open adjacency, capacity 4, boundary legal at 4/rejected at 5)
- Validations: 28 rules across priorities 1–12 all expressed with their error_ids and applies_to scopes
- Endpoints: 51 — every endpoint's inputs (49 field/path/query/path params) appear in backticks somewhere in the PRD; §4 table has only Method/Path/Description/Roles columns
- Errors: all 30 error IDs present in §2/§3 prose triggers and §5 table
- Roles: all 7 (`Anonymous`, `Contestant`, `ContestLead`, `Judge`, `SafetyOfficer`, `StageManager`, `Treasurer`) with identity semantics (entity_backed vs opaque) explicitly stated in §2.1

**Hard contracts**:
- Contract 1 (Field-Name Coverage): **PASS** — 58/58 entity fields, 49/49 endpoint inputs/query/path params in backticks
- Contract 2 (Rule Coverage): **PASS** — validation priority ordering explicit in §2.8; both OCC rules with endpoint + occ_field + error_id + http_status named; cross-entity cascades (cancel, tabulation reopen, disqualify's 3 links + fan-out) fully specified; applies_to scopes enumerated; field defaults and structured content placed on owning entities; sibling-branch symmetry preserved (both safety verdicts, both re-inspection states, both score phases, both prize variants, both skipped-from states, both revocation sources)
- Contract 3 (§3 Path Purity): **PASS** — 511 §3 backtick tokens, 0 violations (no `/`-prefixed, no bare HTTP methods, no method+path combos)

Every scaffold element §1.1–§1.7 is represented in prose.

## Step 5: Generate Unit Tests — 2026-08-13T19:52:00.000Z

Generation complete. Summary:

## Totals
- **Queue A (Difficulty): 36 tests** — all 18 instances covered with exactly 2 tests each.
- **Queue B (Corner): 42 tests** — all 41 non-stub instances covered with ≥1 test each; the 14 `excluded_because:` stubs (6 errors, 7 cross-cutting, 1 consistency) were not translated; all stub cross-references resolve to real difficulty instances.
- **Total: 78 tests**, all collected cleanly by pytest and compile-clean.

## Instances skipped
None. Every non-stub instance passed the PRD-first two-condition filter (verbatim PRD coverage + unique derivability).

Two deliberate PRD-adjudication adjustments (not skips):
1. **Difficulty `scoresheet_lock_reopen_cycle`**: the YAML's precomputed `final_score == 9.9` contradicts the PRD formula (0.5·9+0.3·9+0.2·9 = 9.00). The test asserts the PRD-derived 9.00 — a faithful PRD-only implementer would compute 9.00.
2. **Corner `entity_creation_defaults_and_system_fields` and both OCC instances**: the YAML asserts absolute version values (version == 1 at creation, "1 → 2"). The PRD says only that `version` "increments on every mutation" without pinning the initial value, so assertions use relative increments (`observed + 1`) and drop the initial-value claim (two-reader rule).

Also, for `placement_tiebreak_created_at_order`, the recipe was translated with logical-clock advancement between the two entry creations — PRD §2.7 states the logical clock supplies `created_at`, so without advancing it both entries would share a timestamp and the tie-break outcome would not be uniquely derivable.

## Files
**test_helpers/** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1521_fan_event_contest_cosplay_competition/test_helpers/`): `__init__.py` (barrel), `types.py` (10 entity TypedDicts + 14 enums), `api_client.py` (37 endpoint methods), `api_errors.py` (30 errors, registered with `set_error_http_status_map`), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (shared constants + `make_contestant_headers`/`make_judge_headers`/`make_treasurer_headers` builders), `fixtures.py` (state progression, stage walk, scoring, `setup_scored_contest`/`setup_tabulated_category` composite builders, prize lifecycle, green room, logical clock).

**test_suite/**: `conftest.py`, `test_01_contest_registration_and_entries.py` (17), `test_02_prejudging_slots.py` (9), `test_03_stage_walk.py` (11), `test_04_scoring_and_tabulation.py` (12), `test_05_prize_awards_and_tax.py` (13), `test_06_disqualify_and_withdraw_cascades.py` (4), `test_07_green_room_booking.py` (4), `test_08_security_concurrency_and_reads.py` (7).

## Stage 2 self-audit result
- Tag coverage: 18/18 difficulty instances at ≥2 tests; 41/41 non-stub corner instances at ≥1 test.
- Zero untagged tests, zero dual-tagged tests, zero tags pointing at stubs or nonexistent instances; every tag is the last line of its docstring.
- Every docstring carries a ≥8-word verbatim PRD quote (machine-checked by literal grep against PRD.md); no `skip`/`skipif`/`xfail` markers; no "scaffold" references in generated code.

## Step 6: Generate Implementation — 2026-08-13T19:52:00.000Z

Implementation complete and verified. Final summary:

## Summary

**Task**: task_1521_fan_event_contest_cosplay_competition — Fan Event Contest & Cosplay Competition Operations API (Python + Flask, in-memory only).

### File list (all under `/home/ubuntu/github/CodingPRD/tasks/task_1521_fan_event_contest_cosplay_competition/workspace/implementation/`)

- `start.sh` — foreground launcher, guarded `pip install` (no-op once Flask importable), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — Flask
- `app.py` — Flask entry point, blueprint registration, error handlers, `/healthz`
- `db.py` — in-memory stores (dicts keyed by id, all start empty), logical clock defaulting to exactly `2026-08-01T00:00:00Z` (never wall-clock), UUID minting, ISO-8601 3-fractional-digit timestamps
- `errors.py` — full error catalog (30 error IDs with exact HTTP statuses)
- `response.py` — `meta`/`response_type`/`data` envelope; pagination fields `limit`/`offset`/`total_count`/`has_more` in `meta`
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, 7 roles
- `routes/` — 11 blueprints: contest_events, categories, contestants, judges, entries, prejudging_slots, scoresheets, performance_slots, prize_awards, green_room_bookings, clock
- `services/` — calculations.py, cascades.py, helpers.py, serializers.py

### Counts

- **Endpoints implemented: 50** (all 50 from SCAFFOLD §1.5, including `/_clock/set_current_utc`; plus `/healthz` liveness)
- **State machines: 8** (ContestEvent incl. SETUP→REGISTRATION_OPEN category precondition + CANCELLED cascade, Category incl. tabulate + tabulation reopen, Entry (9 states incl. withdraw/disqualify cascades), PreJudgingSlot, ScoreSheet, PerformanceSlot, PrizeAward, GreenRoomBooking)
- **Calculations: 8** (entry_final_score with WEIGHTED_MEAN/TRIMMED_MEAN variants, placement_rank_assignment, category_purse_split with pinned rounding order, prize_payout_net with W9/backup-withholding variants, contest_tax_summary, junior_age_eligibility, stage_sequence_compaction, green_room_overlap_count) — all via `Decimal` ROUND_HALF_UP, integer cents for money, 2dp for scores
- **Validations/errors: 30 error IDs** across all 12 priority tiers (auth → role → field-shape → FK resolution → ownership → state → safety → referential → constraint → temporal → fiscal), plus 2 OCC rules (`expected_category_version`/`expected_entry_version` → `ERR_STALE_VERSION` 412)

### Storage & boot contract

Storage is purely in-memory dicts; nothing is seeded, preloaded, or persisted (no SQLite, no JSON dump, no /tmp). Verified: a fresh `bash start.sh` boot returns `total_count: 0` on all lists and the clock reads the default `2026-08-01T00:00:00Z`.

### Smoke verification

Server boots cleanly via `bash start.sh` and responds 200 on `/healthz`. End-to-end flows exercised successfully: full contest lifecycle (SETUP→…→TABULATION), purse split pinning (9999→5000/3000/1999), TRIMMED_MEAN trim (10,8,5,2→6.5), tabulation reopen cascade (category→SCORING, contest→JUDGING, placements cleared), disqualify 3-link cascade + award revoke with budget restore, SoD rejection, backup withholding (5000→1200 withheld/3800 net), tax summary, green-room capacity (4 overlap OK / 5th rejected, adjacency not overlapping), `ERR_BOOKING_IN_PAST`, `ERR_GREEN_ROOM_INACCESSIBLE`, slot window/overlap rules, JUNIOR age boundary (exactly 16 → ineligible), OCC 412, and error-priority ordering (ERR_VALIDATION before ERR_NOT_FOUND).

## Step 7: Test/Fix Iteration Loop — 2026-08-13T20:01:00.000Z

### Iteration 1 (baseline sweep)
8 parallel rounds × 78 tests, `--isolation per-test-server`. Union of failures (deterministic, all 8 rounds):
1. `test_trimmed_vs_weighted_craftsmanship_mean_and_sheet_totals` — `assert 'SUBMITTED' == 'LOCKED'`.
2. `test_green_room_booking_in_past_rejected` — `assert '2026-08-15T10:00:00.000Z' == '2026-08-15T10:00:00Z'`.

### Diagnosis (diagnostic protocol)
- Failure 1 — STEP 1a PRD-covered (§3.5 "every `SUBMITTED` sheet of every entry in the category moves to `LOCKED`"); STEP 1b uniquely derivable; STEP 2 TEST IS WRONG at the fixture layer: `setup_scored_contest(lock=True)` returned sheet snapshots captured at submit time, before the bulk lock. Fix in `test_helpers/fixtures.py`: re-fetch every sheet via `get_scoresheet` after locking so the returned structure matches post-lock server state. Verified safe against all 6 `scenario["sheets"]` consumers (ids and `sheet_total` are immutable post-creation; only the failing test reads `status`).
- Failure 2 — STEP 1a: PRD is silent on the `/_clock/set_current_utc` response serialization (`current_utc` never appears in PRD; §2.7 pins only the instant the clock advances to). Two PRD-faithful implementations diverge (echo raw input vs. normalize to the §2.4 three-fractional-digit timestamp convention). STEP 1c partial coverage: kept the fully-covered `ERR_BOOKING_IN_PAST` assertion; corrected the uncovered exact-string assertion in `test_suite/test_07_green_room_booking.py` to compare parsed instants (`datetime.fromisoformat` equality). No assertion of a PRD rule was weakened — the serialization was never a PRD rule.

No tests deleted; no implementation changes (implementation was already PRD-faithful in both cases).

### Iteration 2 (verification sweep)
Re-ran the 8-round parallel sweep: **78/78 passed in every round (8/8 CLEAN)**. Loop exit condition met.

### Step 7 Final Summary (subagent exit report, verbatim)

All 8 parallel rounds pass 78/78. Loop exit condition met.

**Iterations run: 2** (baseline sweep → fix → verification sweep, 8 parallel rounds each, `--isolation per-test-server`).

**Tests deleted: none.** Both failing tests asserted PRD-covered rules; no deletion criterion triggered.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `setup_scored_contest()`: after the bulk `lock_category_scoresheets` step, every sheet snapshot is re-fetched via `get_scoresheet`. The fixture previously returned submit-time (`SUBMITTED`) snapshots even though the server had moved them to `LOCKED`, causing `test_trimmed_vs_weighted_craftsmanship_mean_and_sheet_totals` to assert against stale state. Verified safe against all six `scenario["sheets"]` consumers (only ids and immutable `sheet_total` are read elsewhere; the one `SUBMITTED` assertion lives in a `lock=False` scenario and is untouched).

**Fixes applied to `test_suite/`:**
- `test_suite/test_07_green_room_booking.py` — `test_green_room_booking_in_past_rejected`: replaced the exact-string assertion `current == "2026-08-15T10:00:00Z"` on the clock endpoint's response with parsed-instant equality (`datetime.fromisoformat`). PRD §2.7 pins only the *instant* the clock advances to ("advances the logical clock to a supplied `to_iso8601` instant"); the response serialization (field name `current_utc`, fractional-digit shape) never appears in PRD, so exact-string echo was not uniquely derivable — an implementer normalizing to the §2.4 three-fractional-digit convention (as this one does) is equally PRD-faithful. The test's covered rule (`ERR_BOOKING_IN_PAST` rejection) is unchanged. This is a STEP 1c partial-coverage correction, not a weakening.

**Fixes applied to `implementation/`: none.** The implementation was PRD-faithful in both cases; both failures were test-artifact bugs (one stale fixture snapshot, one over-specified serialization assertion).

**Flakiness signal:** both failures were deterministic (8/8 rounds failed identically pre-fix); post-fix sweep is 78/78 in every round (8/8 clean), so no timing-sensitive issues remain.

## Step 8: Finalize PRD — 2026-08-13T20:05:00.000Z

Done. PRD_FINALIZED.md is written with exactly one minimal, in-place revision.

**Line counts / delta**
- PRD.md: 265 lines; PRD_FINALIZED.md: 265 lines (0% line-count delta — the change is an in-place sentence insertion within existing line 84, §2.7).

**Changes (one bullet per change)**
- §2.7 The Logical Clock — revise — inserted one sentence pinning the clock-advance success response: the new logical-now is returned in a `current_utc` field of the response `data` object, serialized as an ISO 8601 UTC timestamp with three fractional digits per the §2.4 convention — `implementation/routes/clock.py:26` (`return success({"current_utc": format_ts(CLOCK.now())})`), with format from `implementation/db.py:49-53`.

**Step 7 diff items disposition**
- `test_helpers/fixtures.py` setup_scored_contest re-fetch — no edit. Step 7 itself diagnosed this as a pure fixture bug; PRD §3.5 (line 138) already pins "every `SUBMITTED` sheet of every entry in the category moves to `LOCKED`" and the implementation was PRD-faithful.
- `test_07_green_room_booking.py` exact-string clock assertion weakened — this was the genuine PRD silence; addressed by the single §2.7 edit above.

**Per-edit pre-edit search log**
- Edit 1 (§2.7 clock response sentence):
  - (a) Subject: response body of `POST /_clock/set_current_utc` — field name and timestamp serialization of the returned logical-now.
  - (b) Impl paths enumerated and read/grepped: `implementation/routes/clock.py:14-26` (sole handler; ContestLead guard; `CLOCK.set` then `success({"current_utc": format_ts(CLOCK.now())})`); `implementation/db.py:19-27` (`LogicalClock.set`/`now` — no monotonicity check, response re-reads the just-set instant); `implementation/db.py:30-42` (`_parse_iso` normalizes `Z`/offsets/naive to UTC); `implementation/db.py:49-53` (`format_ts` — UTC, three fractional digits via ms truncation, `Z` suffix); `implementation/response.py:16-31` (`success` envelope puts the dict under `data`, confirming "field of the response `data` object"); repo-wide grep for `current_utc` (only `routes/clock.py` produces it; only `test_helpers/fixtures.py:444` consumes it — no parallel endpoint to contradict); grep of all `now_ts`/`format_ts` call sites across `routes/*.py`, `services/cascades.py`, `services/calculations.py` (all share the same three-fractional-digit format, consistent with referencing the §2.4 convention).
  - (c) Wording adjustments made: chose "the new logical-now" rather than "echoes the supplied `to_iso8601`" to avoid over-claiming echo semantics; deliberately said nothing about monotonicity (impl permits setting the clock backward despite the verb "advances") and nothing about offset-input rejection (impl normalizes offsets); phrased the format as "three fractional digits per the §2.4 convention" to borrow §2.4's existing format description without rescoping §2.4's resource-field wording.

## Step 9: Complete PRD — 2026-08-13T20:20:00.000Z

Done. `PRD_COMPLETED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1521_fan_event_contest_cosplay_competition/workspace/PRD_COMPLETED.md` (23 in-place paragraph/table revisions, no new sections).

**Source vs output:** PRD_FINALIZED.md 265 lines / 43,800 chars → PRD_COMPLETED.md 265 lines / 46,879 chars (+3,079 chars, 23 lines touched, 0 lines added/removed).

**Counts:** ambiguity-pins: 18 · mismatch-revisions: 5

**Changes (section — insert|revise — ambiguity|mismatch — what — impl ref):**

- §2.3 — revise — ambiguity — pinned limit/offset non-integer fallback to defaults, out-of-range clamping, and `has_more` = `offset + limit < total_count` — implementation/services/serializers.py:179-202
- §2.4 — revise — ambiguity — pinned `version` starts at 1 and `updated_at` initialized equal to `created_at` at creation — implementation/routes/contest_events.py:44-56 (same pattern in every create)
- §2.6 — revise — mismatch — `expected_category_version`/`expected_entry_version` are optional, not mandatory; when present must be an integer (else `ERR_VALIDATION`) equal to current version (else `ERR_STALE_VERSION`); absent → no OCC check — implementation/routes/categories.py:89-101, implementation/routes/entries.py:154-169
- §2.7 — revise — ambiguity — clock capability *sets* (not monotonically "advances") the logical clock; any parseable ISO instant accepted; missing/unparseable `to_iso8601` → `ERR_VALIDATION` — implementation/routes/clock.py:14-26
- §2.8 — revise — ambiguity — inserted OCC tier (after ownership, before state preconditions) and added `ERR_SCORESHEETS_NOT_LOCKED`/`ERR_NO_ELIGIBLE_ENTRIES` to the state-tier code list — implementation/routes/entries.py:163-172, implementation/routes/categories.py:141-151
- §2.9 — revise — ambiguity — cancellation cascade skips only `QUEUED` stage slots; `ON_STAGE` slots left untouched — implementation/services/cascades.py:37-41
- §3.1 — insert — ambiguity — contest-create shape violations (`end_at` ≤ `start_at`, negative budget, `max_entries_per_contestant` < 1) → `ERR_VALIDATION` — implementation/routes/contest_events.py:35-42
- §3.1 — revise — ambiguity — categories may be created at any time regardless of parent contest status — implementation/routes/categories.py:23-57
- §3.1 — insert — ambiguity — `CANCELLED` and `COMPLETED` are terminal states; any transition attempt → `ERR_INVALID_STATE` — implementation/routes/contest_events.py:19-25
- §3.2 — revise — ambiguity — duplicate contestant email → `ERR_VALIDATION` — implementation/routes/contestants.py:28-29
- §3.2 — revise — ambiguity — a `Contestant` reading another's profile → `ERR_NOT_OWNER` — implementation/routes/contestants.py:53-54
- §3.2 — revise — ambiguity — judge onboarding requires every `category_ids` id and non-null `linked_contestant_id` to resolve, else `ERR_NOT_FOUND` — implementation/routes/judges.py:30-34
- §3.3 — revise — mismatch — removed the false "slot release pulls a `PREJUDGED` entry back to `SAFETY_APPROVED`" pathway; pinned approval only from `SUBMITTED`, rejection only from `SUBMITTED`/`SAFETY_APPROVED`, all other verdict-state combos → `ERR_INVALID_STATE` — implementation/routes/entries.py:249-259
- §3.3 — revise — ambiguity — disqualify's optional `reason` is accepted but not persisted — implementation/routes/entries.py:222
- §3.4 — revise — ambiguity — slot window `end_at` ≤ `start_at` → `ERR_VALIDATION` — implementation/routes/prejudging_slots.py:29-30
- §3.4 — revise — ambiguity — booking a non-`OPEN` slot or an entry already holding a `BOOKED` slot → `ERR_INVALID_STATE` — implementation/routes/prejudging_slots.py:118-126
- §3.4 — revise — ambiguity — releasing a non-`BOOKED` slot → `ERR_INVALID_STATE` — implementation/routes/prejudging_slots.py:150-151
- §3.5 — revise — ambiguity — `X-User-ID` not resolving to a persisted `Judge` → `ERR_NOT_FOUND` — implementation/routes/scoresheets.py:38-40
- §3.5 — revise — mismatch — tabulate responds with `{placed_entry_count, category_id}`, not the category resource (overrides §2.2 default) — implementation/routes/categories.py:153-158
- §3.5 — revise — ambiguity — a `PERFORMED` entry with zero `LOCKED` sheets gets null scores, sorts below all scored entries, still receives a `placement_rank` — implementation/services/calculations.py:74-93,130-133
- §3.5 — revise — mismatch — lock-scoresheets responds with `{locked_count}` (overrides §2.2 default) — implementation/routes/categories.py:181
- §3.6 — revise — ambiguity — `ON_STAGE` advance precondition violations (another slot on stage; entry not `STAGE_QUEUED`) → `ERR_INVALID_STATE` — implementation/routes/performance_slots.py:188-200
- §3.7 — revise — ambiguity — fresh award: `tax_form_received` false, `withheld_cents`/`net_payout_cents` null until disbursement — implementation/routes/prize_awards.py:68-70
- §3.9 — revise — ambiguity — booking window `end_at` ≤ `start_at` → `ERR_VALIDATION` — implementation/routes/green_room_bookings.py:34-35
- §4 intro — revise — ambiguity — list filters are exact-match and conjunctive; undefined routes/unsupported methods → `ERR_NOT_FOUND` (404) in the standard envelope — implementation/app.py:51-59
- §4 table — revise — mismatch — `POST /contestants` authorized roles changed from `Anonymous` only to any authenticated role (impl admits all seven roles) — implementation/routes/contestants.py:19-21

No changes were needed for the calculation formulas (purse split, sheet_total, trimmed/weighted means, withholding, tax summary), the validation-order tiers beyond the two insertions noted, cascade link structures, or any endpoint's role set other than `POST /contestants` — the implementation already matched PRD prose there.

## Pipeline Complete — 2026-08-13T20:20:00.000Z

All 9 steps finished. Final state: 78/78 tests pass across 8/8 parallel stability rounds under `--isolation per-test-server`; `workspace/PRD_COMPLETED.md` is the authoritative contract aligned to `workspace/implementation/`.

## Final Verification Sweep — 2026-08-13T20:22:00.000Z

Orchestrator re-ran the full 8-round parallel stability sweep (`prd-bench-local-run --isolation per-test-server`) to persist the final result artifacts, since Step 7's subagent had cleaned them up on exit. All 8 rounds: **78/78 passed, 0 failed, 0 errors, 0 skipped**. `workspace/implementation/results.{1..8}.json` are present and all-green. No code or document changes resulted from this sweep.
