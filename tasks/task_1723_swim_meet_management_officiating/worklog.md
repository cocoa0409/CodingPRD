# Worklog — task_1723_swim_meet_management_officiating

## Step 1: Create Task Directory — 2026-08-14T11:32:00.000Z

Task directory `tasks/task_1723_swim_meet_management_officiating/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per invocation instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-14T12:08:00.000Z

All three artifacts are complete and the lint is clean. Final report:

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1723_swim_meet_management_officiating/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:` key
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:` key

**Counts:**
- Entities: **13** (Meet, Team, Swimmer, SwimEvent, EventEntry, RelayTeam, RelayLeg, LaneAssignment, Result, Official, OfficialAssignment, Disqualification, MeetRecord) — flat topology, all times in integer centiseconds
- State machines: **11** (every entity except Official and RelayLeg)
- Calculations: **7** (backup_mean_rounded, timing_reconciliation, meet_seeding, place_points, team_points_rollup, age_group_derivation, record_challenge_check)
- Validations: **16** (ordered priority rows)
- Endpoints: **73** (incl. computed heat-sheet read and `POST /_clock/set_current_utc` with the mandatory `2026-08-01T00:00:00Z` startup default)
- Errors: **58** (all referenced by ≥1 design instance)
- Roles: **7** (MeetDirector/TimingOperator/RecordsOfficer opaque; TeamCoach→Team, DeckOfficial/MeetReferee→Official entity-backed; Any)
- §1.8 instances: **18** (exactly 2 per rule × 9 rules, each with full structured `setup_api_calls`/`trigger`/`assert`)
- §1.9 instances: **72** (70 active + 2 `excluded_because:` stubs)

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1279 calls scanned across both design files.)

**Notable design decisions (per the harder-than-expert directive):**
- **Posture-driven gating + compliance/audit blend**; `segregation_of_duties` role model — DQ recorder (DeckOfficial with confirmed STROKE_TURN_JUDGE assignment) and confirmer (MeetReferee) must be different officials, enforced via `ERR_SEGREGATION_OF_DUTY`.
- **Dual-variant calcs on two domains**: timing reconciliation (PRIMARY_PRIORITY pad vs BACKUP_MEAN_PRIORITY rounded backup mean — same readings yield 2500 vs 2535) and tie-policy scoring (SPLIT 6.50 vs TOP 7.00 for identical tied finals, demonstrated with two parallel meets).
- **Pinned nested-rounding order**: backup mean is rounded half-up *before* the delta comparison — pad 2543 / backups 2510+2515 auto-confirms (delta 30 ≤ 30) only under round-first; round-last would force MANUAL_REVIEW (30.5 > 30).
- **Combinatorial scoring**: place/tie-count/relay-multiplier/table-depth interaction (tied relay 1st with table [9,7,6] ×2 → 16.00 each; place 4 → 0.00).
- **Transitive cascades**: DQ-confirm rescore is depth 4 (DQ → EventEntry → Result rescore → two Team rollups + event version bump); relay scratch is depth 3; team withdraw cascades across swimmers/entries/lanes/relays.
- **Two true OCC races** (seed on Meet.version, complete on SwimEvent.version), both exercised with strictly sequential stale-version replays returning 412 before state checks.
- **Boundary precision**: qualifying-cut equality qualifies; protest window `<=` vs confirm's strict `>` on the same boundary; certification expiry `>=` session_date; delta 30 vs 31; 4th vs 5th entry limit; birthday-equals-start-date age derivation.
- **Temporal overlap with two different interval semantics**: official assignments are half-open (adjacency allowed) while swimmer entries require a 20-minute recovery buffer (adjacency rejected).
- **Compensating invariants**: scratch/unscratch conserves lane occupancy *and lane identity*; complete/reopen/re-complete conserves team provisional points (9.00 → 0.00 → 9.00).
- Design repair during audit: removed unreachable `ERR_NO_TIMING_SOURCE` and `ERR_SWIMMER_NOT_ACTIVE`, added missing state errors (`ERR_EVENT_NOT_SEEDED`, `ERR_EVENT_NOT_COMPLETED`, `ERR_MEET_INVALID_STATE`, `ERR_ENTRY_NOT_VERIFIABLE`, `ERR_LANE_NOT_RECONCILED`), normalized path placeholders to `{id}` for the lint's FK sub-resource check, and scrubbed forbidden race vocabulary (including renaming a DQ code containing "NON_SIMULTANEOUS" to `FLY_ARMS_ALTERNATING`).

## Step 3: Copy Shared Files — 2026-08-14T12:09:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1723_swim_meet_management_officiating/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T12:21:00.000Z

PRD generation complete. All three Hard Contracts pass.

**Output**
- **Path**: `/home/ubuntu/github/CodingPRD/tasks/task_1723_swim_meet_management_officiating/workspace/PRD.md`
- **Line count**: 398 lines
- **Constraint honored**: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

**Section list**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 User/RBAC (with per-role identity translations) · 2.2 API Response Structure (emitted byte-verbatim from `section-2.2-response-structure.md`) · 2.3 Pagination (incl. all list-endpoint filters) · 2.4 The Logical Clock (startup default 2026-08-01T00:00:00Z, never wall-clock) · 2.5 Common Resource Properties (incl. RelayLeg `common_fields: false` exception) · 2.6 Time Values and Points Precision · 2.7 Optimistic Concurrency Control · 2.8 Meet Posture, Cascades, and Derived State · 2.9 Resource Addressing/Existence (left-to-right, 11 named 404s) · 2.10 The Validation Pipeline (16 tiers, explicit ordering)
- §3 Business Logic (timeline grouping, 9 subsections): 3.1 Meet Configuration/Teams/Swimmers · 3.2 Event Program · 3.3 Entries/Eligibility/Qualification · 3.4 Relays and Legs · 3.5 Officials/Certifications/Deck Coverage · 3.6 Closing/Seeding/Heat Sheet · 3.7 Timing/Reconciliation/No-Shows · 3.8 Disqualifications · 3.9 Scoring/Publication/Records/Meet Completion
- §4 Endpoint Definitions — 73 rows, 4 columns (Method, Path, Description, Authorized Role(s))
- §5 Error Code Catalogue — 57 rows, 2 columns (Error ID, HTTP Status Code)

**Hard Contract reports**

Contract 1 — Field-Name Coverage: PASS. 83 required identifiers (69 entity fields + 5 endpoint-only inputs + 12 query params + 2 computed-read outputs `heats`/`current_utc` + 5 common fields) — 83 present in backticks, 0 missing (mechanically diffed; two passes run, first pass caught and fixed a code-fence extraction artifact, not a prose gap).

Contract 2 — Rule Coverage: PASS.
- validations[] priority: 16 checked, 16 expressed in the ordered §2.10 pipeline with explicit "earlier tiers mask later ones" semantics, 0 missing
- concurrency_rules[] OCC: 2 checked, 2 expressed — `POST /meets/{id}/seed` + `expected_meet_version` + `ERR_STALE_VERSION`/412 and `POST /events/{id}/complete` + `expected_event_version` + `ERR_STALE_VERSION`/412, both named with "checked before state guards", no race-framing language, 0 missing
- state_machines[].transitions: 50 checked across 11 machines (Meet 6, Team 1, Swimmer 1, SwimEvent 7, EventEntry 11, RelayTeam 3, LaneAssignment 5, Result 2, OfficialAssignment 3, Disqualification 6, MeetRecord 5), 50 fully expressed with preconditions paired to error IDs and all side effects, 0 missing
- calculations[]: 7 checked, 7 fully expressed — backup_mean_rounded (pinned nested-rounding order + the 2543/2510/2515 → 2513 counter-example), timing_reconciliation (both variant chains, reconstruction-safe), meet_seeding (sort/tie-break/no-id-tie-break, heat fill fastest-first, middle-out lane priority with 6- and 8-lane worked orders), place_points (1224 ranking, SPLIT 6.50 vs TOP 7.00 worked examples, relay multiplier after tie handling), team_points_rollup (recompute-not-incremental, DQ_EXCLUDED contributes 0.00, Team.version on change), age_group_derivation (birthday-on-start-date example 2014-08-15→12), record_challenge_check (strictly-less-than, equality does not break, exactly one PENDING_VERIFICATION), 0 missing
- validations[] conditions: 16 checked, all matchable to error IDs in §2/§3 prose (all 57 error IDs mechanically confirmed present in narrative), 0 missing
- endpoints[].side_effects / applies_to: 35 side-effect-bearing writes checked, 35 expressed (withdrawal/relay/seed/reopen/complete/reopen-event/publish cascades; DQ confirm/overturn depth-4 cascades; ratify supersede + auto-reject slower pending), 0 missing
- entities[].fields[] structured content: 97 field entries checked — defaults (lane_count 6, points_table [9..1], multiplier 2, caps 4/30/20/30, SPLIT), nullables (qualifying_time_cs, seed_time_cs, four readings, reconciled_variant, final_time_cs, notified_at, resolved_by_referee_id, challenger_entry_id, DQ_EXCLUDED null place/time), initial states, RelayLeg thin-record exception — all reconstructible, 0 missing
- sibling-branch symmetry: 9 groups checked (dual unscratch paths, dual relay-scratch paths, PROPOSED/CONFIRMED release pair, auto/manual readings pair, PRIMARY/BACKUP_MEAN chains, SPLIT/TOP, uphold/overturn/confirm ruling branches, record reject from both states, SEEDED/CANCELLED seed outcomes) — equal prose density, 0 asymmetric

Contract 3 — §3 Path Purity: PASS. 596 backticked tokens scanned in §3 — 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos. All endpoints referenced via state-transition framing (`SEEDED` → `IN_PROGRESS`), role + action verb ("the `MeetReferee` may mark a seeded entry as a no-show"), or capability description ("a test-driving capability … accepts a `to_iso8601` instant").

**Zero-Silence audit highlights**

Every scaffold behavior is stated in prose, including the easy-to-drop ones: Meet.version incrementing **only** on lifecycle/config edits; `REJECTED` entries staying `ENTERED` and never seeded; unscratch's two distinct restore paths (lane row absent → `ENTERED`; `VOIDED` lane present + meet/event `SEEDED` → restored with original `heat_number`/`lane_number`); overlap checks measured against PROPOSED+CONFIRMED at proposal but CONFIRMED-only at confirmation with adjacency allowed; equality-qualifies cut times and NT-against-a-cut rejection; the protest window's inclusive end vs. confirm's strictly-past requirement; `FINISHED`/`DQ` immutability once the event is `OFFICIAL` and `NO_SHOW` unconditional terminality; standing records born `CURRENT` while challenges are born `PENDING_VERIFICATION` only from the publish cascade; and the logical clock's fixed startup default with no wall-clock fallback.

## Step 5: Generate Unit Tests — 2026-08-14T12:44:00.000Z

Generation complete. Summary:

**Files written**

`test_helpers/` (Stage 1) — 9 modules under `/home/ubuntu/github/CodingPRD/tasks/task_1723_swim_meet_management_officiating/test_helpers/`:
- `types.py` — 13 entity TypedDicts + 15 status/role enums; `RelayLeg` correctly omits `updated_at`/`version` (PRD §2.5 thin join record)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (~60 methods incl. `/_clock/set_current_utc`)
- `api_errors.py` — all 55 PRD §5 error IDs + HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity structure assertions + points precision checker
- `factories.py`, `constants.py` — payload factories; PRD §3.1 defaults and clock instants
- `test_users.py` — 6 role headers + mandatory per-instance builders for entity-backed roles (`make_team_coach_headers`, `make_deck_official_headers`, `make_meet_referee_headers`)
- `fixtures.py` — composite chains: open meet, team/swimmer/event/entry/verify, relay declare/legs/lock, deck coverage (REFEREE+STROKE_TURN_JUDGE confirmed), `seed_meet` (clock + close + OCC seed), `setup_in_progress_event` (full chain to IN_PROGRESS with N seeded entries across teams), `complete_event_with_times`, DQ record/notify, standing records

`test_suite/` (Stage 2) — `conftest.py` + 11 test files organized by concern (lifecycle/posture, creation/envelope, reads/404s, entries/eligibility, scratch/withdraw, relays, officials/coverage, timing, DQs, scoring, records/finalization).

**Test counts**

- Queue A (Difficulty): 36 tests — all 18 instances covered with exactly 2 tests each (variant branches, boundary X vs X+1, cascade hops, invariant round-trip legs)
- Queue B (Corner): 71 tests — 69 of 70 non-stub instances covered (2 instances got 2 tests each)
- Total: 107 tests

**Instances skipped**

- `Corner/entities/relay_leg_not_found_returns_404` — PRD §2.9/§5 enumerate the dedicated 404s and omit relay legs; the asserted `ERR_RELAY_TEAM_NOT_FOUND` for an unknown leg id is not uniquely derivable by a PRD-only reader. Gap left as a gap.
- Stubs not translated (by design): `complexity_layers/dual_variant_layer_covered_by_difficulty`, `complexity_layers/cascading_layer_covered_by_difficulty` — cross-references verified to resolve to real difficulty instances.
- Sub-assertion dropped (not whole instance): `meet_creation_defaults_applied`'s `version == 1` — PRD §2.5 says version increments on modification but never states the initial value; all eight documented defaults + `SETUP` are asserted instead.

**Self-check results**

- Stage 1: all modules compile; `test_helpers` and `conftest` import cleanly against the installed framework
- Stage 2 audit script: every test carries exactly one `Design:` tag as the final docstring line; all tags resolve to real instances; difficulty ≥2/instance ✓; corner ≥1/non-stub instance ✓; 0 verbatim-citation failures (every quoted block survives whitespace-normalized containment in PRD.md); no `skip`/`skipif`/`xfail` markers; no scaffold references in generated code

Notable design decisions: DQ-recorder/ruling-official identity is threaded via per-instance official headers everywhere (segregation-of-duty chains); the `relay_lock_incomplete_legs` test isolates the leg-count failure (entry pre-verified) because the PRD places both lock gates in the same pipeline tier 15, so cross-error ordering there is not uniquely derivable; heat-sheet assertions use only the PRD-pinned shape (`event_id`, `heats` list length) plus lane placement via the fully-pinned lane-assignment list.

## Step 6: Generate Implementation — 2026-08-14T12:46:00.000Z

The implementation is complete and validated. Server processes are stopped; deliverables are in place.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1723_swim_meet_management_officiating/workspace/implementation/`):
- `start.sh` — executable launcher; guards `pip install` behind an `import flask` check (safe for per-test reboots), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask only
- `app.py` — Flask entry point, ApiError/404/405/500 handlers producing the exact error envelope, global request lock
- `db.py` — 13 empty in-memory dicts (zero seeding), logical clock defaulting to exactly `2026-08-01T00:00:00Z`, ISO-8601 helpers (3-fractional-digit wall timestamps; non-fractional logical-clock rendering)
- `errors.py` — full 58-entry error catalog with exact IDs and HTTP statuses
- `response.py` — `meta`/`response_type`/`data` envelope; pagination fields in `meta`; error meta limited to request id + timestamp
- `middleware.py` — `X-User-ID`/`X-User-Role` extraction, six declared roles
- `services.py` — body validators, serializers, all calculations and cascades
- `routes/` — 12 modules grouped by resource

**Endpoint count: 73** (every row of the endpoint table, including the test-driving clock). **Entity count: 13.**

**Key design decisions:**
- **Validation pipeline ordering** follows PRD §2.10 strictly: headers (400) → role (403) → path/body existence left-to-right (404) → resource-dependent authz incl. the STJ-assignment DQ gate and TeamCoach/Official ownership (403) → segregation of duty (403) → OCC `expected_meet_version`/`expected_event_version` (412, deliberately before state guards) → state machines (409) → certification (422) → entry window → protest windows → eligibility (team → age → gender) → entry limit → recovery buffer → double-booking → relay structure → aggregate gates → readings payload sanity (400, checked last on that endpoint per priority 16).
- **Pinned calculation semantics**: backup mean rounded half-up to whole centiseconds *before* the delta comparison (the 2543/2510/2515 counter-example auto-confirms at delta 30 ≤ 30); competition ranking 1224 with SPLIT vs TOP tie policies; relay multiplier applied after tie handling; all points as `Decimal` quantized 2dp ROUND_HALF_UP, serialized as JSON numbers; seeding with NT-last sort, `created_at` tie-break (never id), fastest-heat-highest-number, middle-out lane priority `[3,4,2,5,1,6]` for 6 lanes.
- **Cascades implemented as full recomputation**: team withdraw, meet reopen-entries (hard-deletes lanes), event reopen (hard-deletes results), DQ confirm/overturn rescore (event version bumps only when a rescore occurs), record challenge at publish (one PENDING_VERIFICATION per event, strictly-faster check), ratify superseding CURRENT and auto-rejecting slower pending challenges.
- **RelayLeg** carries only `id` + `created_at` (no `updated_at`/`version`) per PRD §2.5; leg POST replaces an existing `leg_number` in place.
- **Logical clock** drives all deadline/window decisions; `notified_at` is a logical-clock reading; resource `created_at`/`updated_at` are wall-clock UTC with 3 fractional digits.
- **Ambiguity resolutions** (no catalog ID exists): relay-leg 404 and a few off-machine transitions return `ERR_INVALID_REQUEST`; mark-no-show on a non-SEEDED entry returns `ERR_EVENT_NOT_IN_PROGRESS`; record-challenge holder for relays uses `relay_name`.
- Verified end-to-end with two smoke suites (~100 assertions): full meet arc (setup → entries → close → seed → start → readings/DQ → complete → publish → records → meet complete/finalize), reopen cycles, OCC staleness after reopen-close, scoring ties under both policies, DQ rescore cascades, withdraw cascades, relay lifecycle, no-shows, pagination, and error-envelope shape — all passing across fresh `start.sh` boots.

## Step 7: Run Tests and Iterate — 2026-08-14T12:56:00.000Z

All 8 rounds pass 107/107. The sweep is clean — exiting with the summary.

**Iterations run:** 2 (sweep 1: 3 deterministic failures, identical across all 8 rounds; sweep 2 after fixes: 8/8 rounds clean, 107/107 each).

**Tests deleted:** none. All three failing tests assert rules PRD covers verbatim with unique derivability; all three failures were setup bugs, not assertion bugs.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:**

- `test_suite/test_03_reads_listing_and_not_found.py` — `test_entries_pagination_with_event_filter` and `test_heat_sheet_groups_seeded_lanes_by_heat`: inline setup generated `birth_date=f"2014-03-1{c}"` over `c in "ABC"`, producing malformed dates (`2014-03-1A`, …) that the PRD-faithful implementation correctly rejects (`ERR_INVALID_REQUEST`, PRD §2.10; §3.1's birth_date is an ISO date per the worked examples). Changed the loop to `c in "123"` → valid dates 2014-03-11/12/13, all age 12 at the 2026-08-15 start → `ELEVEN_TWELVE`, matching the event default age group. The asserted rules (§2.3 pagination meta, §3.6 heat sheet + middle-out lane dealing) were already faithful.
- `test_suite/test_09_disqualification_adjudication.py` — `test_recorder_cannot_confirm_own_call`: setup confirmed one dual-certified official in BOTH `REFEREE` and `STROKE_TURN_JUDGE` roles on the same event. PRD §3.5's double-booking rule ("the official's other assignments on the same `session_date`, whether `PROPOSED` or `CONFIRMED`, must not overlap the event's half-open scheduled window") forbids one official holding two assignments on one event (identical windows overlap), so the implementation's PRD-required `ERR_OFFICIAL_ASSIGNMENT_CONFLICT` correctly rejected setup. Rewrote the setup to use two distinct officials via the existing `setup_deck_coverage` helper: the judge records the DQ as `DeckOfficial`, then the judge's official id presented with the `MeetReferee` role attempts the confirm, surfacing `ERR_SEGREGATION_OF_DUTY` exactly as PRD §3.8 states. Pruned now-unused imports (`add_official`, `confirm_assignment`, `create_meet`, `propose_assignment`) and added `setup_deck_coverage`.

**Fixes applied to `implementation/`:** none — in all three cases the implementation was behaving exactly as PRD requires (malformed-date rejection per §2.10, double-booking conflict per §3.5), and no PRD-required checks were weakened.

## Step 8: Finalize PRD — 2026-08-14T13:00:00.000Z

All verification is complete. Both step_7_diff items are pure test-fixture bugs: the PRD already uniquely determines each behavior and the implementation already matches the PRD verbatim. PRD_FINALIZED.md is therefore a byte-identical copy of PRD.md.

**Conclusion: no PRD edits — PRD_FINALIZED.md is byte-identical to PRD.md.**

**Line counts / delta:** PRD.md 397 lines, PRD_FINALIZED.md 397 lines — 0.0% delta (`diff -q` confirms identical).

**Changes:** none.

**Per-item reasoning (each step_7_diff item inspected against PRD + implementation):**

- **test_03 fixture fix (`birth_date=f"2014-03-1{c}"`, `"ABC"` → `"123"`)** — pure fixture bug. The malformed-date rejection the buggy setup tripped is uniquely determined by PRD §2.10's closing sentence ("malformed bodies, missing required fields, type mismatches, and invalid enum values are rejected with `ERR_INVALID_REQUEST` (HTTP 400) wherever they occur") combined with §3.1's ISO-format worked example ("a swimmer born 2014-08-15"). Implementation matches exactly: `implementation/routes/swimmers.py:34` → `v_date` (`services.py:117-123`) → `parse_date` (`db.py:63-70`, strptime `%Y-%m-%d` + length-10 check) → `ERR_INVALID_REQUEST`. The fixed dates (2014-03-11/12/13) yield age 12 at `DEFAULT_START_DATE=2026-08-15` → `ELEVEN_TWELVE` per §3.1, matching `add_event`'s default age group. The rules those two tests actually assert — §2.3 pagination meta (impl `response.py:21-27`) and §3.6 heat-sheet grouping + middle-out lane dealing (impl `events.py:244-267`, `services.py:344-347`) — are verbatim PRD, matched by the implementation, and pass post-fix.

- **test_09 fixture fix (`test_recorder_cannot_confirm_own_call` setup rewrite to two distinct officials)** — pure fixture bug. The double-booking rejection that broke the buggy setup is uniquely determined by PRD §3.5 ("the official's other assignments on the same `session_date`, whether `PROPOSED` or `CONFIRMED`, must not overlap the event's half-open scheduled window … genuine overlaps fail with `ERR_OFFICIAL_ASSIGNMENT_CONFLICT`"); two assignments on one event have identical windows, a genuine overlap, not the back-to-back adjacency §3.5 explicitly permits. Implementation matches: `propose_assignment` (`events.py:344-348`) → `_assignment_conflict` (`events.py:307-324`) → `windows_overlap` (`services.py:661-663`). The rule the fixed test asserts — §3.8 segregation of duty, `ERR_SEGREGATION_OF_DUTY` when the ruling referee's `X-User-ID` equals `reporting_official_id` — is verbatim PRD and matched at `dqs.py:167-168` (confirm), with identical checks at `dqs.py:190-191` (uphold) and `dqs.py:205-206` (overturn).

**Per-edit pre-edit search log:** zero edits committed, so no edit-triggered searches were required. The two candidate subjects were nonetheless enumerated globally before concluding "no edit": (1) birth_date/date validation — all `v_date` callsites (`swimmers.py:34`, `officials.py:46`, `events.py:75`, `events.py:371`) route through the same `services.py:117-123`/`db.py:63-70` path, all consistent with §2.10's blanket `ERR_INVALID_REQUEST` rule as written; (2) assignment conflict + DQ ruling — all `_assignment_conflict` callsites (`events.py:344` propose with PROPOSED+CONFIRMED; `officials.py:120-122` confirm with CONFIRMED-only, both matching §3.5 verbatim) and all three segregation checks (`dqs.py:167,190,205`, all matching §3.8 verbatim).

Corroboration: `implementation/results.7.json` and `results.8.json` both show 107/107 passed, 0 failed — sweep 2 fully clean with the implementation untouched.

## Step 9: Complete PRD — 2026-08-14T13:14:00.000Z

The patch is complete and verified: 22 paragraph-lines revised inline, no new lines or sections, all changes within existing paragraphs. Final summary:

**Source vs output:** `PRD_FINALIZED.md` = 397 lines / 58,832 chars → `PRD_COMPLETED.md` = 397 lines / 62,605 chars (**+3,773 chars, +0 lines**). PRD_FINALIZED.md was byte-identical to PRD.md (Step 8 had changed nothing), so all 32 pins originate here.

**Counts:** 30 ambiguity-pins, 2 mismatch-revisions.

**Changes** (section — insert|revise — ambiguity|mismatch — what — impl ref):

- §2.3 — insert — ambiguity — `limit`<1, `offset`<0, or non-integer either → `ERR_INVALID_REQUEST`; `limit`>100 silently capped — implementation/services.py:156-174
- §2.3 — insert — ambiguity — `total_count` = full filtered listing size; `has_more` ⟺ offset + returned < total_count — implementation/response.py:21-27
- §2.4 — insert — ambiguity — clock set is unconditional; no monotonicity guard (may move backward) — implementation/routes/clock.py:13-19
- §2.9 — insert — ambiguity — missing relay-leg id → `ERR_INVALID_REQUEST` (400); legs carry no dedicated not-found error — implementation/routes/relays.py:201-207
- §3.1 — insert — ambiguity — `lane_count` below 1 → `ERR_INVALID_REQUEST` — implementation/routes/meets.py:53-55
- §3.1 — insert — ambiguity — duplicate `team_code` within meet → `ERR_INVALID_REQUEST` — implementation/routes/teams.py:42-44
- §3.1 — insert — ambiguity — withdrawing an already-`WITHDRAWN` team → `ERR_INVALID_REQUEST`, checked ahead of the meet-posture gate — implementation/routes/teams.py:96-100
- §3.2 — insert — ambiguity — duplicate `event_number` → `ERR_INVALID_REQUEST` — implementation/routes/events.py:83-85
- §3.2 — insert — ambiguity — individual-entry write against a relay event → `ERR_INVALID_REQUEST` — implementation/routes/entries.py:66-69
- §3.2 — insert — ambiguity — `scheduled_end_minute` ≤ start → `ERR_INVALID_REQUEST` — implementation/routes/events.py:79-82
- §3.3 — insert — ambiguity — every verification write bumps entry `version` even when `qualification_status` is unchanged — implementation/routes/entries.py:167-174
- §3.4 — insert — ambiguity — declaration against a non-relay event → `ERR_INVALID_REQUEST` — implementation/routes/relays.py:69-70
- §3.4 — insert — ambiguity — `relay_name` uniqueness enforced against all of the club's relays in the event, scratched included; duplicate → `ERR_INVALID_REQUEST` — implementation/routes/relays.py:78-86
- §3.4 — insert — ambiguity — `leg_number` outside 1–4 → `ERR_INVALID_REQUEST` — implementation/routes/relays.py:149-150
- §3.4 — revise — **mismatch** — leg add/replace answers `201 Created` in both cases, overriding §4's blanket 200-on-modify rule — implementation/routes/relays.py:171-187
- §3.4 — revise — ambiguity — leg eligibility also enforces club standing (`ERR_TEAM_NOT_ACTIVE`) and the event's gender rule (`ERR_GENDER_INELIGIBLE`, MIXED accepts any) — implementation/routes/relays.py:154-161
- §3.4 — insert — ambiguity — lock from non-`DECLARED` → `ERR_RELAY_LEGS_LOCKED` — implementation/routes/relays.py:231-232
- §3.4 — insert — ambiguity — lock gate order pinned: relay posture → event lock window → leg count → entry verification — implementation/routes/relays.py:231-241
- §3.4 — insert — ambiguity — scratching an already-`SCRATCHED` relay → `ERR_RELAY_NOT_SCRATCHABLE` — implementation/routes/relays.py:259-260
- §3.5 — insert — ambiguity — duplicate `lsc_membership_id` → `ERR_INVALID_REQUEST` — implementation/routes/officials.py:48-50
- §3.5 — insert — ambiguity — confirming a non-`PROPOSED` assignment → `ERR_INVALID_REQUEST` — implementation/routes/officials.py:117-118
- §3.5 — insert — ambiguity — releasing an already-`RELEASED` assignment → `ERR_INVALID_REQUEST` — implementation/routes/officials.py:145-146
- §3.6 — revise — ambiguity — heat sheet includes only `ACTIVE` lanes; `{heat_number, lanes[]}` shape; lanes sorted by `lane_number`, heats by `heat_number` ascending; empty `heats` when none — implementation/routes/events.py:244-267
- §3.7 — insert — ambiguity — mark-no-show on a non-`SEEDED` entry → `ERR_EVENT_NOT_IN_PROGRESS` (flagged candidate, confirmed) — implementation/routes/entries.py:245-246
- §3.7 — insert — ambiguity — readings accepted in any `reconciliation_status` while event `IN_PROGRESS`; each submission merges and re-runs auto-confirm afresh — implementation/routes/lanes.py:75-96
- §3.7 — revise — **mismatch** — resolve applies a supplied `pad_status` update **before** walking the chain (PRD's "computes… and applies" implied compute-first); `INVALID` in the resolve request removes the pad from the chain — implementation/routes/lanes.py:113-116
- §3.7 — insert — ambiguity — resolve on a lane not in `MANUAL_REVIEW` → `ERR_LANE_NOT_RECONCILED` — implementation/routes/lanes.py:111-112
- §3.7 — insert — ambiguity — reopen-timing on a lane not `RESOLVED`/`AUTO_CONFIRMED` → `ERR_LANE_NOT_RECONCILED` — implementation/routes/lanes.py:130-131
- §3.8 — revise — ambiguity — DQ-confirm cascade also nulls the rewritten Result's `final_time_cs` (PRD enumerated only place/points) — implementation/services.py:576-582
- §3.9 — insert — ambiguity — completion creates an `UNOFFICIAL` Result for entries restored to `FINISHED` by a pre-completion overturn that lack one — implementation/services.py:492-498
- §3.9 — revise — ambiguity — record-challenge holder for relays is the relay team's `relay_name` (was the vague "relay display") (flagged candidate, confirmed) — implementation/services.py:543-548
- §3.9 — insert — ambiguity — equal fastest challenger times break by the result's `created_at`, earliest first — implementation/services.py:541
- §3.9 — revise — ambiguity — per-entry results read returns an `array` envelope holding zero or one Result — implementation/routes/entries.py:259-266
- §3.9 — insert — ambiguity — explicitly created standing record is born with null `challenger_entry_id` — implementation/routes/events.py:378-388

All three flagged candidates verified against the impl and pinned; the walk additionally surfaced the two genuine mismatches (leg-replace 201, resolve pad_status ordering) and the heat-sheet/pagination/clock contract pins.
