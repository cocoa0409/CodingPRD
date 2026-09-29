# Worklog — task_2428_recreational_tennis_league_rating_administration

## Step 1: Create task directory — 2026-09-02T15:34:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2428_recreational_tennis_league_rating_administration` and its `workspace/` subdirectory. Index was pre-assigned by the invoking pipeline (2428); no scan/allocation of `./tasks/` performed.

## Step 2: Generate scaffold — 2026-09-02T18:24:00.000Z

ORCHESTRATOR NOTE (decision made autonomously, no user available): the first attempt to generate all three scaffold artifacts in a single subagent died with `API Error: Claude's response exceeded the 64000 output token maximum` and wrote nothing. The step was therefore split into three subagents — 2a (SCAFFOLD.yaml), then 2b (SCAFFOLD_DIFFICULTY_DESIGN.yaml) and 2c (SCAFFOLD_CORNER_DESIGN.yaml) launched concurrently once 2a's output existed — each instructed to build its YAML incrementally in ~400-line chunks so no single response exceeds the output cap. The scenario text and the "Generate task harder than expert level!" difficulty instruction were passed verbatim to all three. Isolation from sibling tasks was enforced in every prompt.

Post-step verification by the orchestrator: `SCAFFOLD.yaml` 2894 lines, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` 2650 lines, `SCAFFOLD_CORNER_DESIGN.yaml` 6582 lines; `scaffold_lint.py .` over all three → `VERDICT: clean lint` (62 endpoints, 12 entities, 27 §1.8 instances, 93 §1.9 instances, 4974 calls scanned).

### Step 2a subagent summary (verbatim)

SCAFFOLD.yaml for task_2428 is complete, parses, and lints clean.

**File**: `/home/ubuntu/github/CodingPRD/tasks/task_2428_recreational_tennis_league_rating_administration/SCAFFOLD.yaml` — 2894 lines, §1.0–§1.7 only (top-level keys: `scenario`, `domain_name`, `api_prefix`, `complexity_profile`, `response_envelope`, `entities`, `state_machines`, `concurrency_rules`, `calculations`, `validations`, `endpoints`, `errors`, `roles`; **no** `scaffold_difficulty_design` / `scaffold_corner_design`).

**Counts (expert+ tier)**
- 12 entities: Section, League, Facility, Player, Team, RosterSpot, Match, Scorecard, Strike, RatingAppeal, Grievance, CommitteeVote
- 9 state machines over 8 entities — Match carries two independent dimensions (`schedule_status`, `result_status`); 4 revision cycles (League ROSTERS_LOCKED↔REGISTRATION_OPEN, RosterSpot ACTIVE↔INELIGIBLE, Player ACTIVE↔STRIKE_SUSPENDED, Scorecard/Match DISPUTED↔AMENDED/REPORTED) plus a SCHEDULED→SCHEDULED reschedule self-loop
- 2 OCC rules (`expected_team_version` on `POST /tennis/roster-spots`, `expected_match_version` on `POST /tennis/matches/{id}/schedule`, both 412) — no forbidden concurrency vocabulary anywhere (verified by grep)
- 10 calculations, incl. 2 dual-variant families (`player_dynamic_rating` in_season_provisional vs year_end_final; `team_standings_points` official vs provisional), pinned rounding order, two-phase `year_end_rating_recalculation`, two temporal-overlap rules with different geometry (`court_slot_capacity` half-open interval + turnaround buffer vs `team_calendar_conflict` UTC-date bucket / 240-min separation), and two conserved-quantity invariants (`strike_weight_ledger`, `league_standings_ledger_invariant`)
- 70 priority-ordered validations, contiguous 1–70, with three deliberate dual-failure pairs annotated in-file: PAIR A `state` (ERR_MATCH_RESULT_STATE_INVALID) vs `business_temporal` (ERR_SCORECARD_WINDOW_EXPIRED); PAIR B `business_safety` (ERR_AGE_GROUP_NOT_MET) vs `business_fiscal` (ERR_ROSTER_SIZE_EXCEEDED); PAIR C `business_referential` (ERR_FACILITY_SECTION_MISMATCH) vs `business_constraint` (ERR_TEAM_DATE_CONFLICT)
- 62 endpoints (flat under `/tennis`), incl. `POST /tennis/_clock/set_current_utc` documenting the mandatory `2026-08-01T00:00:00Z` startup default
- 71 error codes, 6 roles (`SectionAdmin`/`LeagueCoordinator` opaque; `Captain`, `Player`, `CommitteeMember`, `CommitteeChair` all `entity_backed:Player`, segregation of duties: member votes, chair decides, chair barred from deciding what it voted on)

**Verified mechanically**: every `ERR_*` referenced in §1.2/§1.3/§1.4/§1.5 exists in §1.6 and vice versa (zero orphans both directions); every `POST|GET|DELETE /tennis/...` string referenced anywhere is a declared §1.5 endpoint; every endpoint role exists in §1.7; no `id`-based ordering/tie-breaks (`created_at ASC` is the documented final tiebreaker); no tabs.

**Lint verdict** (run in a temp dir with stub design files, since `scaffold_lint.py` exits 2 unless all three files are present):
```
Coverage
  §1.5 endpoints declared:    62
  §1.1 entities declared:     12
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Two notes for the downstream design subagents: (1) optional `input:` entries are individually quoted (`"team_id?"`) because PyYAML rejects a bare `?` inside a flow sequence and `scaffold_lint._split_input` treats each list element as one field name; (2) validation rows use `category: concurrency` for the OCC trio, matching the skill's own example scaffold.

### Step 2b subagent summary (verbatim)

Linter run complete. My file is clean.

## Report

**Deliverable**: `/home/ubuntu/github/CodingPRD/tasks/task_2428_recreational_tennis_league_rating_administration/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2650 lines, single top-level key `scaffold_difficulty_design` (a list of 9 rule blocks).

**Rules covered**: 9 of 9 (all §0.5 Difficulty Rules). **Total non-stub instances: 27** — 3 per rule, zero stubs, zero placeholders.

| rule_id | instances |
|---|---|
| `dual_variant_calc` | 3 |
| `combinatorial_formula` | 3 |
| `non_linear_state_machine` | 3 |
| `transitive_cascade` | 3 |
| `priority_pair_validation_conflict` | 3 |
| `boundary_precision_check` | 3 |
| `cross_entity_state_dependency` | 3 |
| `resource_temporal_overlap` | 3 |
| `compensating_invariant` | 3 |

Per-rule differentiation constraints are satisfied (e.g. `dual_variant_calc` spans three distinct entity domains — player dynamic rating, team/league standings, rating-epoch recalculation; `combinatorial_formula` covers modes a/b/c — rounding order, threshold discard, clamped min/max with penalty; `transitive_cascade` has three cascades of depth ≥3 with different triggering transitions — strike suspension, appeal grant, grievance team disqualification; `resource_temporal_overlap` uses three distinct interval semantics — court occupancy + turnaround buffer, date-bucket team calendar, 240-minute start-to-start doubleheader gap).

**Validation status: all clean.**
- `yaml.safe_load` → `list(d.keys()) == ['scaffold_difficulty_design']`.
- Mechanical checks across all 27 instances (every `setup_api_calls` + `trigger` call): undeclared endpoints `0`, role (`as:`) mismatches `0`, unknown `ERR_*` ids `0`, unbound `${var}` references `0`, payload keys outside §1.5 `input` `0`, missing required (non-`?`) input fields `0`, `captures:` JSONPaths not resolving on the endpoint's output entity `0`.
- `scaffold_lint.py .` with all three scaffold files present: `§1.8 instances scanned: 27`, `3596` calls scanned across §1.8+§1.9. Verdict reports 3 violations, and **all 3 are in §1.9** (`SCAFFOLD_CORNER_DESIGN.yaml`, owned by the concurrent Step 2c agent): a missing required `roster_lock_at` on `POST /tennis/leagues`, an undeclared `rating_level` payload key on `POST /tennis/players`, and a malformed call string `GET /tennis/players with limit=101`. **Zero violations are attributable to my file**, so no fixes were applied. Those three are worth relaying to the corner-design agent — note that all three look like intentional negative probes whose names don't match the linter's negative-trigger name pattern (`_cannot_`/`_rejected`/`_returns_4XX`), so renaming to `..._rejected` would likely clear them.

I did not create or modify `SCAFFOLD.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`, and did not read any sibling task directory.

### Step 2c subagent summary (verbatim)

The corner-design file is complete and validated.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2428_recreational_tennis_league_rating_administration/SCAFFOLD_CORNER_DESIGN.yaml` — 6,582 lines, single top-level key `scaffold_corner_design`.

## Sections and instance counts (93 total, 0 stubs)
| section | instances |
|---|---|
| entities | 12 |
| state_machines | 12 |
| calculations | 11 |
| validations | 10 |
| endpoints | 6 |
| errors | 20 |
| rbac | 8 |
| cross_cutting_complexity_layers | 12 |
| consistency_model | 2 |

All nine claim-extraction-guide sections are covered. `claim_type:` values are verbatim guide rows (guide Table 6 declares no rows, so the errors section uses `Violation → Error`; the complexity-layer and consistency sections use the layer/model names `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `rate_threshold_triggers`, `immediate`). The four declared complexity layers each get 2–4 instances (OCC: stale team version, stale match version, missing version field → 400, version-increment/read-your-writes; cascades: 6-level verify chain, order-sensitive strike chain, atomicity of a refused 3-effect default; dual variant: official vs provisional divergence and its exact closure on verify; thresholds: cumulative boundary at exactly 3 via 2+1, the 5-vs-6 band, and rescission reset with the disqualification asymmetry).

## Validation status
- `python3 -c "import yaml; list(d.keys())"` → `['scaffold_corner_design']` ✓
- `scaffold_lint.py .` (all three files present, real difficulty file untouched and unread) → **clean lint**, 93 §1.9 instances, 4,974 calls scanned, checks (a)–(f) pass.
- Custom mechanical pass: every `call:` resolves to a declared §1.5 (method, path-template); every `ERR_*` exists in §1.6 (0 unknown); every `${var}` bound by an earlier `captures:` in the same instance (including asserts); all `expected_*_version` values are `${...}` placeholders; all `trigger:` values are lists of call dicts; 93/93 unique instance names; no `excluded_because` stubs.
- Error-code breadth: 62 of 71 declared codes are exercised. The 9 remaining are deliberate: `ERR_APPEAL_STATE_FORBIDS_ACTION` / `ERR_GRIEVANCE_STATE_FORBIDS_ACTION` / `ERR_ROSTER_SPOT_HAS_RESULTS` are shadowed by higher-priority rules (20 `ERR_INVALID_STATE`, 21 `ERR_LEAGUE_PHASE_FORBIDS_ROSTER_CHANGE`) and are unreachable as written; the others (`ERR_ADVANCEMENT_SLOTS_EXHAUSTED`, `ERR_NO_PLAYOFF_ELIGIBLE_TEAMS`, `ERR_AMENDMENT_LIMIT_REACHED`, `ERR_APPEAL_BASELINE_STALE`, `ERR_REMEDY_NOT_ADMISSIBLE`, `ERR_TEAM_HAS_VERIFIED_RESULTS`) need playoff-seeding or multi-cycle grievance/amendment setups that exceed a breadth-probe budget.

Fixes made during this final pass: three lint violations of mine (a malformed `GET /tennis/players with limit=101` call string; two negative instances whose names lacked an HTTP-code marker so the payload-shape check applied — renamed to `..._returns_422_validation...`), one unbound `${pa7_id}` in a calculations assert (added `- *a_pa7` to that setup), and a correctness fix in the new capacity instance: the Team state machine hardcodes `active_roster_size >= 2` at register, so the one-team league now uses `min_active_roster_size: 2` with two activated spots per team.

## Step 3: Copy shared files — 2026-09-02T18:25:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T18:44:00.000Z

ORCHESTRATOR VERIFICATION (guarding the known silent-truncation failure): `wc -l workspace/PRD.md` = 588; `grep -n '^#'` shows the full outline (§1 Introduction, §2.1–§2.11, §3.1–§3.9, §4 API Endpoint Definitions at line 443, §5 Error Codes at line 512); `tail -25` ends on the complete final error-table row `| \`ERR_CLOCK_NOT_MONOTONIC\` | 422 |` with a trailing newline — a real section boundary, no mid-sentence cut. No regeneration needed. Both design indices were withheld from this subagent per the skill's leakage constraint, and the "harder than expert level" difficulty line was NOT forwarded (Step 2 only), so it cannot leak into PRD.md.

### Step 4 subagent summary (verbatim)

PRD generation complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2428_recreational_tennis_league_rating_administration/workspace/PRD.md` — **588 lines**, built in 8 incremental chunks (one per turn, none exceeding ~300 lines of prose).

**Section list (from `grep -n '^#'`):**
- `# Recreational Tennis League API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Actors/Headers/RBAC · 2.2 API Response Structure (+ the two fixed `####` sub-blocks) · 2.3 Pagination and List Ordering · 2.4 Resource Identity, Timestamps and Version Counters · 2.5 The Logical Clock and Temporal Evaluation · 2.6 Level Vocabulary, Rating Arithmetic and Rounding Discipline · 2.7 Optimistic Concurrency on Rosters and Slots · 2.8 The Section-Wide Rating Epoch · 2.9 Validation Precedence · 2.10 Nested Path Resolution and Section Scoping · 2.11 Cascade Discipline and the Two Conserved Ledgers
- `## 3. Business Logic & Workflows` — 3.1 Section/facilities/ladder · 3.2 Rating provenance and the dynamic rating engine · 3.3 Team formation and eligibility gates · 3.4 League lifecycle · 3.5 Competition calendar (court capacity, calendar conflict) · 3.6 Scorecards, disputes, line credit, standings ledger · 3.7 Weighted strike ledger and rescission · 3.8 Committee review (appeals, votes, grievances, three remedy families) · 3.9 Playoffs, advancement, year-end recalculation
- `## 4. API Endpoint Definitions` (4-column table)
- `## 5. Error Codes` (2-column table) — document ends here, no audit footer.

**Measured coverage (all mechanical, scaffold-driven):**
| Item | Scaffold | Covered |
|---|---|---|
| §1.5 endpoints | 62 | 62 rows matched by method+path regex in §4; 0 missing |
| §1.6 error codes | 71 | 71 rows in §5 with matching HTTP status; 0 missing/mismatched |
| §1.4 validations | 70 | 70/70 error_ids present in §1–§4 prose (priority 57's dual id `ERR_ROSTER_SPOT_HAS_RESULTS` / `ERR_TEAM_HAS_VERIFIED_RESULTS` both present) |
| §1.3 calculations | 10 | 10/10 described; all numeric constants present (5+2+2+1+1+2+9+4+4+2), the only literals absent are descriptive-string constants rendered as prose |
| §1.2 state machines | 9 | 9/9; 56/56 transitions; every `from`/`to`/initial state present (0 absent) |
| §1.1 entities | 12 | 12/12 |
| §1.7 roles | 6 | 6/6 |

**Hard Contract 1 — Field-Name Coverage: PASS.** Required set = 150 identifiers (133 entity field names ∪ 95 endpoint input identifiers, plus `id`, `created_at`, `updated_at`, `version`). Word-boundary scan of PRD.md: **0 missing.**

**Hard Contract 2 — Rule Coverage: PASS.** 70/70 validations (ordered ladder in §2.9 plus in-context restatement); 56/56 transitions with preconditions and side effects; 10/10 calculations with pinned evaluation/rounding order; 2/2 OCC rules with parent entity, `occ_field`, error id and 412; all enum constraint values present (0 of the scaffold's field-level enum values missing); cross-entity cascades (strike→roster→team→league, publish-recalc→roster→team→league, advance-teams 4-level, forfeit reversal+re-credit) stated with their recomputed counters.

**Hard Contract 3 — §3 Path Purity: PASS.** 1410 backticked tokens in §3 scanned: 0 begin with `/`, 0 are bare HTTP methods, 0 combine method+path; 0 raw `/tennis` occurrences anywhere in §3 (paths appear only in §2.7's OCC contract and the §4 table).

**§2.2 fidelity:** the fixed block from `section-2.2-response-structure.md` is present byte-identical.

**Tail intact:** `tail -40` ends on the complete final table row `| \`ERR_CLOCK_NOT_MONOTONIC\` | 422 |` with a trailing newline — a real section boundary, no mid-sentence truncation. No fuzzy/placeholder language found (`approximately`, `roughly`, `etc.`, `TODO`, `TBD` all zero). The two withheld design files were never opened, grepped, or referenced, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-02T20:20:00.000Z

Launched concurrently with Step 6 in a single assistant message (per the skill's concurrency requirement — this also gives Step 6 physical isolation, since `test_suite/` did not exist when the impl subagent booted). Orchestrator verification: `test_helpers/` has all 9 expected modules, `test_suite/` has `conftest.py` + 24 themed test modules, `grep -c` over `^def test_` totals **155** tests.

### Step 5 subagent summary (verbatim)

Generation is complete. The final file (`test_24_consistency.py`, the two `consistency_model` instances) is written and the whole-suite audits pass.

## Files written

**`test_helpers/`** (infrastructure, 1,910 lines total)

| file | lines |
|---|---|
| `__init__.py` | 15 |
| `api_client.py` | 355 |
| `api_errors.py` | 171 |
| `assertions.py` | 156 |
| `constants.py` | 349 |
| `factories.py` | 220 |
| `fixtures.py` | 554 |
| `test_users.py` | 70 |
| `types.py` | 221 |

**`test_suite/`** (`conftest.py` 28 lines + 24 test modules, 9,232 lines, 155 tests)

Queue A (difficulty, `test_01`–`test_09`): 278/6, 328/6, 344/6, 342/6, 337/6, 328/6, 347/6, 273/6, 400/7.
Queue B (corner, `test_10`–`test_24`): 619/12, 288/7, 375/6, 577/11, 494/10, 556/8, 502/10, 409/6, 386/6, 508/8, 236/4, 370/4, 271/3, 213/3, 251/2.

## Tests per queue

- **Queue A — `Design: Difficulty/...`: 55 tests covering all 27 non-stub instances across the 9 rules.** Minimum per-instance coverage is 2 (the ≥2 requirement holds for every instance; no instance is under-covered).
- **Queue B — `Design: Corner/...`: 100 tests covering all 93 non-stub instances across the 9 sections** (≥1 each).
- Every test carries exactly one `Design:` line; a script cross-check against both design YAMLs resolves all 155 tags to real instance names, with zero untagged, dual-tagged or dangling tags.

## Instances SKIPPED

**None.** All 27 queue-A and all 93 queue-B non-stub instances passed the PRD-first two-condition filter (verbatim PRD coverage + uniquely-derived outcome) and were emitted. No skip/xfail markers and no placeholders exist in the suite.

Two design/PRD divergences were resolved in the PRD's favour rather than by skipping: the design's `$.data.defaulting_side` on a match body is asserted as the PRD's entity field `default_side` (`defaulting_side` is the *request* field), and `basis` is sent lowercase (`official`/`provisional`) per PRD §3.9 rather than the design's uppercase. One design assertion ("a second review call returns 409") names no error id the PRD uniquely derives, so only the status code is asserted.

## Verification status

- `python3 -m py_compile` over all 33 generated `.py` files: **clean**.
- AST undefined/unused-name audit over all 24 test modules: **clean** (`conftest.py` reports two known false positives — the module global `__file__`, and the deliberately side-effecting `from test_helpers import api_errors` that calls `set_error_http_status_map`).
- **All 155 docstring PRD quotes verified greppable in `workspace/PRD.md`** after whitespace/em-dash normalisation. This audit caught one real defect: `test_13_calculations.py::test_a_match_may_be_rescheduled_into_the_slot_it_already_occupies` cited a sentence ("In both geometries the match being scheduled is **excluded from its own comparison set**...") that does not exist in the PRD; it was replaced with the actual §3.5 sentence from PRD line 312 ("Both edges enforce the identical rule set; the difference is that on a reschedule the match's own prior slot is **excluded** from both geometric checks before the new slot is measured, so a match never collides with the slot it is in the act of releasing.").
- No occurrence of "scaffold", `§1.x` or "queue A/B" anywhere in the generated code.

The suite was never executed (no server was started), so these are static guarantees only — first-run behavioural failures against a real implementation are still possible.

## Step 6: Generate implementation — 2026-09-02T20:20:00.000Z

Launched concurrently with Step 5. The impl subagent was denied the design indices and both test directories; it read only INSTRUCTION.md + SCAFFOLD.yaml + PRD.md. Orchestrator verification: 21 `.py` modules + `start.sh` + `requirements.txt` present in `workspace/implementation/`.

### Step 6 subagent summary (verbatim)

Implementation complete and verified.

## Deliverable
`/home/ubuntu/github/CodingPRD/tasks/task_2428_recreational_tennis_league_rating_administration/workspace/implementation/`

| module | lines | role |
|---|---|---|
`app.py` | 60 | app factory, blueprint registration, error handlers, `PORT`/`0.0.0.0` bind
`store.py` | 192 | in-memory dict store (12 collections), `_seq` insertion counter, logical clock
`errors.py` | 99 | 71-code catalog → HTTP status map, `ApiError`
`response.py` | 89 | §2.2 envelope, `req_<20 alnum>` ids, pagination meta
`auth.py` | 113 | `X-User-Role`/`X-User-ID`, 6 roles, entity-backed role resolution
`validation.py` | 194 | field/type/vocabulary checks, pagination parsing, instant parsing
`credit.py` | 372 | line crediting (PLAYED / LINE_DEFAULT / TEAM_DEFAULT / FORFEIT), match rollups
`derive.py` | 357 | standings, team/league counters, dynamic ratings, strike ledger, roster cascades
`routes_common.py` | 103 | shared list/get helpers, FK resolution, OCC guards
`routes_section.py` | 218 | sections, facilities, year-end recalc / publish
`routes_player.py` | 125 | players, self-rating, rating history
`routes_league.py` | 173 | leagues, ladder validation, standings
`routes_league_lifecycle.py` | 261 | open-registration → … → seed-playoffs / advance-teams
`routes_team.py` | 186 | teams, register, withdraw
`routes_roster.py` | 196 | roster spots (create/activate/remove) with `expected_team_version`
`routes_match.py` | 268 | fixtures, schedule geometry, confirm, mark-played, default
`routes_scorecard.py` | 303 | submit / review (VERIFY, DISPUTE) / amend
`committee.py` | 87 | quorum, vote recount, appeal auto-grant threshold
`routes_appeal.py` | 179 | rating appeals + decide cascade
`routes_grievance.py` | 321 | grievances + 3 remedy families
`routes_discipline.py` | 210 | strikes, rescission, committee votes; mounts appeal + grievance
**total** | **4106** | 21 modules, all `py_compile` clean

Plus `start.sh` (exec's `python3 app.py`, reads `$PORT`, foreground, `PYTHONDONTWRITEBYTECODE`) and `requirements.txt`.

## Coverage
- **62 endpoints** registered — exactly the PRD/scaffold endpoint table (verified by walking `app.url_map`).
- 12 entities, 9 state machines, 10 calculations, the 70-rank precedence ladder, all 71 error codes.
- Storage is dicts only; no file, no SQLite, no cache. Two back-to-back relaunches on the same port each accepted the *same* section `code` and reported `total_count=1`, proving state is wiped per boot. Only `__pycache__` (from my own `py_compile`) ever appeared on disk and was removed.

## Verification
Two urllib end-to-end suites, each against a freshly booted server, both **0 failures / exit 0** (129 and 131 assertions+calls):
- Suite 1: clock, section, facility, players+ratings, league, registration, teams, 6 roster spots/team with `412 ERR_STALE_TEAM_VERSION`, lock-rosters, start-play, match create/schedule/`400 ERR_MISSING_EXPECTED_VERSION`/confirm/mark-played, scorecard submit + `422 ERR_SCORECARD_LINE_INVALID` + `409 ERR_SELF_VERIFICATION_FORBIDDEN` + verify, standings official & provisional (`standings_points == 6`, 3 lines / 36 games), dynamic rating, strike → `STRIKE_SUSPENDED` at weight 3 → rescind → `ACTIVE`/0, appeal file/`403 ERR_NOT_SELF`/votes/`409 ERR_DUPLICATE_VOTE`/GRANT → 4.0 `APPEAL_GRANTED`, grievance UPHOLD `MATCH_FORFEIT` → match `VOIDED` with winner flipped and counters zeroed, error-envelope shape (`meta` = exactly the 2 keys, `data` = exactly `error_id`+`message`), `401 ERR_UNKNOWN_ROLE` / `ERR_MISSING_ROLE_HEADER`, `400 ERR_INVALID_PAGINATION`, `422 ERR_CLOCK_NOT_MONOTONIC`.
- Suite 2 (playoff/recalc happy paths): roster-spot `DELETE 204`, team withdraw → league auto-`CANCELLED`, match `default` (`DEFAULTED`+`VERIFIED`, 3 lines/36 games to the non-defaulting side, `NO_SHOW_DEFAULT` strike on the captain), scorecard DISPUTE → amend (non-submitter blocked `409`) → VERIFY, all four §2.11 standings equalities asserted exact, grievance withdraw + `403 ERR_NOT_TEAM_CAPTAIN`, appeal DENY with `403 ERR_SOD_INTERESTED_PARTY` on an interested voter, **seed-playoffs → `PLAYOFFS`, 2 seeds, 2 matches FINALIZED**, **advance-teams → league `COMPLETED`, top seed `ADVANCED`, other `ELIMINATED`**, year-end-recalc → `RECALC_IN_PROGRESS` + `409 ERR_RATING_PERIOD_CLOSED` on a rating write → publish-recalc → `RECALC_PUBLISHED`, `recalc_run_index == 1`.

## Adjudication worth flagging
The scaffold's seed-playoffs/advance-teams precondition reads as "no match with open `schedule_status` **or** open `result_status`". Taken literally it is unsatisfiable, since `PLAYED` is terminal in the schedule dimension, so any played fixture keeps a league out of the playoffs forever. I implemented the AND reading (a fixture is settled once *either* dimension reaches a settled value — result `VERIFIED`/`FINALIZED`/`VOIDED`, or schedule `DEFAULTED`/`CANCELLED`), per PRD §3.9 "every regular fixture must have reached a settled place". This is the only place I departed from a literal scaffold clause; it is documented in a docstring at `routes_league_lifecycle.py:_still_open`.

All smoke servers I started (ports 18431-18436) are stopped; other agents' servers on 18443-18450 were left untouched.

## Step 7: Run tests and iterate — 2026-09-02T20:57:00.000Z

ORCHESTRATOR VERIFICATION (guarding the known "clean sweep with no artifacts" failure mode): all 8 `workspace/implementation/results.{1..8}.json` exist on disk (~47 KB each, mtime 20:55) and each reads `passed=153 total=153 failed=0 errors=0 skipped=0`. Independent checks: `grep -c '^def test_'` over `test_suite/` = **153** (155 minus the 2 deletions, consistent); `grep` for `pytest.mark.skip` / `pytest.mark.xfail` across `test_suite/` + `test_helpers/` = **0**; `grep` for `sqlite3` / file-write / `json.dump` / `/tmp/` / `pickle` across `workspace/implementation/*.py` = **0 files**, so storage is still in-memory only. The sweep was run under `setsid` per the pipeline's anti-reaping instruction. Step 7 had non-zero fixes, so Step 8 is NOT skipped.

### Step 7 subagent summary (verbatim)

All 8 rounds now pass: **153/153 each**.

## Summary

**Iterations run:** 2 full 8-round parallel sweeps (sweep 1: 131/155 in 7 rounds, 130/155 in one; sweep 2 after fixes: 153/153 in all 8). The single round-2-only `ConnectionResetError` on `test_05::test_the_refused_schedule_leaves_the_fixture_unscheduled_and_unversioned` did not recur — confirmed load-induced, not fixed.

**Tests deleted (2)**
- `test_08_resource_temporal_overlap.py::test_doubleheader_gap_of_exactly_240_minutes_is_admitted_on_the_same_date` — BOUNDARY-INCLUSIVITY SILENCE. PRD §3.5 says only "rejected if any peer's start is within 240 minutes ... in either direction"; §2.5 promises inclusivity is stated explicitly, and here it is not, so exactly-240 admits both verdicts (the test's own docstring quotes a buffer sentence, not a boundary rule). Scaffold rule: `Difficulty/resource_temporal_overlap/doubleheader_start_to_start_gap_rejects_a_slot_the_court_rule_admits` (its 210-minute sibling, unambiguous, is kept).
- `test_11_state_machines_league_and_team.py::test_a_single_activated_player_is_not_a_doubles_team` — ERROR-CODE SILENCE. PRD §3.4 states the two-active-spot precondition ("a team with a single activated player is not a doubles team") but names no `error_id`, and rank 20 does not apply because register *is* declared from `DRAFT`. Scaffold rule: `Corner/state_machines/team_register_with_only_one_active_spot_returns_invalid_state`.

**Fixes to `test_helpers/`**
- `assertions.py` — added `assert_instant_equals(actual, expected)` (+ `_instant` parser): PRD §2.5 pins every stored instant as "an ISO 8601 UTC instant" and fixes the three-fractional-digit rendering only for `created_at`/`updated_at` (§2.4), so exact-string equality on `scheduled_start_at`/`scheduled_end_at`/`verified_at`/`recorded_at`/`roster_lock_at`/`season_end_at` asserted an unstated rendering.

**Fixes to `test_suite/` (assertion-level, all made more PRD-faithful)**
- 30 assertion sites across `test_06, 07, 08, 10, 12, 13, 15, 18, 20, 21, 24` converted from exact instant strings to `assert_instant_equals` (15 of the 24 stable failures were this one cluster).
- `test_21_cascades.py::test_one_strike_reorders_the_player_the_spot_the_team_and_the_league` — `noncompliant_team_count` corrected from 1 to 0 while both teams are still `REGISTERED` (PRD §3.1 counts only teams "in the roster-locked or in-play states"), and the `== 1` claim moved onto the `lock-rosters` response, where §3.4 says the stranded team "remains counted in `noncompliant_team_count`".
- `test_23_strike_thresholds.py::test_a_ledger_of_five_holds_the_band_between_the_two_limits` — dropped `team["version"] > version_before` (BRANCH-ASYMMETRIC SIDE EFFECT: §3.7 bumps team versions only "When a player crosses into `STRIKE_SUSPENDED`"; this second strike crosses nothing). Roster-size and compliance assertions kept.

**Fixes to `implementation/`**
- `routes_team.py::create_team` — foreign-section `home_facility_id` now raises `ERR_SECTION_SCOPE_MISMATCH`: §2.10 scopes team creation and rank 12 outranks rank 42 under §2.9's "lowest matching one wins".
- `routes_team.py::withdraw_team` — non-withdrawable origin state now `ERR_INVALID_STATE` (rank 20) instead of `ERR_TEAM_STATE_INVALID` (rank 31).
- `routes_scorecard.py::amend_scorecard` — non-`DISPUTED` card now `ERR_INVALID_STATE` (rank 20) instead of `ERR_SCORECARD_STATE_FORBIDS_ACTION` (rank 26), which §3.6 names for *review* only.
- `routes_league_lifecycle.py::_require_stage` — stage mismatch reports `ERR_INVALID_STATE`, keeping `ERR_LEAGUE_ALREADY_TERMINAL` for `COMPLETED`/`CANCELLED` leagues and for the two mismatches PRD names for it (seed off `IN_PLAY`, advance off `PLAYOFFS`, via `terminal_code=True`).
- `routes_roster.py::remove_roster_spot` — unconditional `touch(team)`; §3.3 says a successful removal "increases the team's `version` by 1" regardless of whether a counter moved (a `PENDING` removal previously bumped nothing).
- `credit.py::standings_figures` (+ new `carries_forfeit_credit`) — a `VOIDED` match still holding an all-`FORFEIT` `line_results` now contributes its lines/sets/games to both teams but no match win or loss: §3.8 says "the aggrieved team gains 3 lines, 6 sets and 36 games and the forfeiting team the mirror-image losses", while §2.11 invariant A (a voided match is not *decided*) forbids a match win.

**Final per-round results** (`workspace/implementation/results.{1..8}.json`): 153/153, 153/153, 153/153, 153/153, 153/153, 153/153, 153/153, 153/153 — 0 failed, 0 errors, 0 skipped in every round.

## Step 8: Finalize PRD — 2026-09-02T21:10:00.000Z

Step 8 was NOT skipped: Step 7 recorded 2 deletions, 32 `test_suite/` fixes, 1 `test_helpers/` fix and 6 `implementation/` fixes, so the skip condition (zero iterations beyond baseline) did not hold. The Step 7 worklog entry was inlined verbatim as `<step_7_diff>`; the subagent was denied `SCAFFOLD*.yaml` and `worklog.md`. Orchestrator verification: `PRD_FINALIZED.md` is 588 lines (same as `PRD.md`), `diff` shows 24 changed lines = 12 in-place revisions with no insertions or deletions of whole lines and no new sections; tail still ends on the complete `| \`ERR_CLOCK_NOT_MONOTONIC\` | 422 |` row.

### Step 8 subagent summary (verbatim)

`PRD_FINALIZED.md` is written. Summary below.

## Line counts
- `PRD.md`: 588 lines — `PRD_FINALIZED.md`: 588 lines — **0.0% line delta** (12 lines revised in place, no lines added or removed, no new sections).

## Changes (one bullet each)

- **§2.5** — revise — pinned the rendering of stored instants: server-written instants (`created_at`/`updated_at`, `verified_at`, `decided_at`, `rating_history.recorded_at`, and `scheduled_start_at`/`scheduled_end_at`) carry exactly three fractional digits and `Z`, while the four league window instants are retained verbatim as supplied — `store.py:74-81` (`iso`), `routes_match.py:174-176,254`, `routes_scorecard.py:261-269`, `routes_league.py:98-101`
- **§2.9 rank 23** — revise — gloss narrowed to "the seeding or advancement action matches the current stage" — `routes_league_lifecycle.py:39-51`
- **§2.9 rank 69** — revise — gloss widened to include team registration's minimum active-spot count — `routes_team.py:117-118`
- **§3.3** — revise — a foreign-section `home_facility_id` at team creation is `ERR_SECTION_SCOPE_MISMATCH` (rank 12), not `ERR_FACILITY_SECTION_MISMATCH` (rank 42) — `routes_team.py:47-49`
- **§3.4** — revise — seed/advance stage mismatch reports `ERR_LEAGUE_ALREADY_TERMINAL` at any stage; open-registration, lock-rosters and start-play report `ERR_INVALID_STATE` on a non-terminal stage mismatch — `routes_league_lifecycle.py:39-51,59,87,119,140,195`
- **§3.4** — revise — the two-active-spot registration precondition is refused with `ERR_ROSTER_QUOTA_NOT_MET` — `routes_team.py:117-118`
- **§3.4** — insert — a withdrawal from a state with no declared withdrawal edge, or with the league outside the paired stages, is `ERR_INVALID_STATE` (rank 20), not `ERR_TEAM_STATE_INVALID` (rank 31) — `routes_team.py:135-141`
- **§3.4** — revise — "every other team-state mismatch" carved out to except withdrawal and to name registration's `DRAFT`-only departure — `routes_team.py:107-108`, `routes_roster.py:34-35`
- **§3.5** — revise — the 240-minute doubleheader start-to-start bound is inclusive; exactly 240 minutes conflicts — `credit.py:386-388`
- **§3.6** — insert — an amendment against a non-`DISPUTED` scorecard is `ERR_INVALID_STATE` (rank 20), not `ERR_SCORECARD_STATE_FORBIDS_ACTION` (rank 26, reserved for review) — `routes_scorecard.py:288-290`
- **§3.6** — revise — a `VOIDED` match whose `line_results` are all `credit_source` `FORFEIT` still contributes lines/sets/games for and against under both bases, but no match win or loss — `credit.py:218-248`
- **§3.6** — revise — "official basis counts only VERIFIED and FINALIZED" softened to admit the surviving forfeit credit — `credit.py:226-248`

## Per-edit pre-edit search log

1. **§2.5 instant rendering.** (a) Rendered form of every stored instant. (b) Grepped all `iso(`/`now_iso`/`req_instant`/`opt_instant` uses and all `["*_at"] =` assignments across `implementation/`; read `store.iso`/`insert`/`touch`, `validation.req_instant`, `routes_league.create_league` (window instants stored raw from payload), `routes_match.schedule_match`/`record_default`, `routes_scorecard.review_scorecard`, `routes_appeal:153`, `routes_grievance:216,297`, `routes_player:115`, `routes_section:191`. (c) Split the claim in two — three-digit `Z` for server-written instants, verbatim retention for the four league window instants — because a single universal "three digits" claim would have mis-described `routes_league.py:98-101`.
2. **§2.9 rank 23.** (a) Scope of `ERR_LEAGUE_ALREADY_TERMINAL`. (b) Grepped every raise site: `_require_stage` (terminal + `terminal_code`), `open_registration` parent-not-live (`:65`), `advance_teams` parent-not-`REGISTRATION_OPEN` (`:215`). (c) Kept the gloss non-exhaustive (parent-league conditions stay unnamed, as in unedited §3.4/§3.9) rather than enumerating them.
3. **§2.9 rank 69.** (a) Scope of `ERR_ROSTER_QUOTA_NOT_MET`. (b) All three raise sites: `routes_team.py:118`, `routes_league_lifecycle.py:92,124`. (c) Widened to "minimum active-spot **and** team counts" so the registration site is covered without falsifying the lock/start-play sites.
4. **§3.3 facility scope.** (a) Which code a cross-section facility reference yields. (b) Grepped both codes: `ERR_FACILITY_SECTION_MISMATCH` only at `routes_match.py:152` (scheduling); `ERR_SECTION_SCOPE_MISMATCH` at `routes_team.py:49`, `routes_roster.py:66`, `routes_league.py:47`, `routes_discipline.py:40`, `routes_common.py:41`. Re-read §3.5's scheduling sentence and §2.9's closing example. (c) Scoped the change to team creation only; §3.5 and the §2.9 example keep `ERR_FACILITY_SECTION_MISMATCH` verbatim.
5. **§3.4 lifecycle stages.** (a) Stage-mismatch code per lifecycle op. (b) Read all five `_require_stage` callsites plus the non-stage raises in the same file (`:65,90,92,124,146,150,198,204,215,217`). (c) Restricted the `ERR_LEAGUE_ALREADY_TERMINAL` claim to seed/advance and terminal leagues, leaving the file's other `ERR_INVALID_STATE` raises (roster-lock instant, still-open fixtures) undescribed rather than accidentally covered.
6. **§3.4 registration quota.** (a) Refusal for fewer than two active spots at registration. (b) Read `routes_team.register_team` in full and checked check order against ranks 21/31/60/68/69. (c) None; ordering already matches the ladder.
7. **§3.4 withdrawal state.** (a) Codes on withdrawal preconditions. (b) Read `withdraw_team` fully (`WITHDRAW_LEAGUE_GATES`, both `ERR_INVALID_STATE` raises, `ERR_TEAM_HAS_VERIFIED_RESULTS`); grepped every remaining `ERR_TEAM_STATE_INVALID` site (`routes_match.py:52,200`, `routes_roster.py:35`, `routes_league_lifecycle.py:150`, `routes_team.py:108`). (c) Phrased as a carve-out ("withdrawal alone excepted") and added registration's `DRAFT`-only departure, so the surviving universal claim stays true for fixture creation, confirmation, roster add/activate, seeding and registration.
8. **§3.5 doubleheader bound.** (a) Inclusivity of the start-to-start separation. (b) `credit.team_has_conflict` (sole definition), `DOUBLEHEADER_MIN_GAP_MINUTES` (sole use), its only callsite `routes_match.py:169-171` (invoked for both sides), and the flag-false calendar-date branch. (c) Confined the inclusivity clause to the separation bound; left the interval-intersection clause and the calendar-date geometry untouched.
9. **§3.6 amendment state.** (a) Wrong-state code for amend. (b) Grepped `ERR_SCORECARD_STATE_FORBIDS_ACTION` (only `routes_scorecard.py:238`, review) and the amend raise (`:290`); read both handlers' check order. (c) Said "reserved for review" instead of narrowing rank 26's gloss, keeping the change local.
10. **§3.6 voided forfeit credit.** (a) Standings inclusion for `VOIDED` matches. (b) Read `credit.standings_figures`, `carries_forfeit_credit`, `match_figures`, `rollup`, `forfeit_credit`; both callers (`derive.recompute_team_standings` official, `routes_league.league_standings` provisional); the only writer of `VOIDED` + all-`FORFEIT` lines (`routes_grievance._apply_match_forfeit`); plus `credit._head_to_head` and `seeding_candidates`, and `derive.counted_lines` (all of which still exclude `VOIDED`). Re-verified all four §2.11 equalities arithmetically against the forfeit credit. (c) Limited the exception to line/set/game figures and explicitly denied any match win or loss, so §2.11's "decided" definition, §3.9's head-to-head key and §3.2's counted-line set remain accurate untouched.
11. **§3.6 official-basis sentence.** (a) Same subject as 10. (b) Same paths. (c) Added "alongside the surviving forfeit credit just described" so the two §3.6 paragraphs do not contradict each other.

**Step 7 items that needed no PRD edit** (impl already matches PRD prose): `remove_roster_spot`'s unconditional `touch(team)` (§3.3 already pins "+1", and `store.touch` is idempotent per request, so an `ACTIVE` removal is also exactly +1); the `test_21` `noncompliant_team_count` correction (§3.1/§3.4 already count only roster-locked/in-play teams and already say the stranded team stays counted); the `test_23` team-version assertion drop (§3.7 already bumps team versions only on crossing into `STRIKE_SUSPENDED`).

## Step 9: Complete PRD — 2026-09-02T21:30:00.000Z

Step 9 always runs. Source was `PRD_FINALIZED.md` (present from Step 8). The subagent was denied `SCAFFOLD*.yaml` and `worklog.md`.

ORCHESTRATOR VERIFICATION: `PRD.md` 588 lines / 132844 chars → `PRD_FINALIZED.md` 588 / 135941 → `PRD_COMPLETED.md` 588 / 149529. `diff` of `grep -n '^#'` between `PRD_FINALIZED.md` and `PRD_COMPLETED.md` is empty — **outline identical**, no sections added or moved. `tail -3` ends on the complete final error-table row, so no truncation. `find implementation ../test_suite ../test_helpers -name '*.py' -newer implementation/results.1.json` returns **nothing** — neither the implementation nor the tests were touched after the green sweep, so the recorded 8×153/153 result still describes the delivered artifacts.

### Step 9 subagent summary (verbatim)

All planned edits are applied and the document verifies clean.

**Verification**
- `PRD_FINALIZED.md`: 588 lines / 135,941 chars → `PRD_COMPLETED.md`: 588 lines / 149,529 chars (**char delta +13,588**, line delta 0, blank-line/paragraph count identical at 173).
- `diff` of `grep -n '^#'` between the two files: **OUTLINE IDENTICAL** (same headings, same line numbers).
- `tail -5` ends inside the §5 Error Codes table at a real section boundary (`| ERR_CLOCK_NOT_MONOTONIC | 422 |`).
- No new sections, no new paragraphs (one pre-compaction edit had split §2.3 into an extra paragraph; it was folded back inline to restore the original paragraph count).

**Counts: 52 changes — 44 ambiguity-pins, 8 mismatch-revisions.**

- §2.2 — insert — ambiguity — `api_request_timestamp` reads the host wall clock, not the logical clock; no rule reads it — `response.py:_meta` / `store.py:wall_now_iso`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` also `ERR_INVALID_PAGINATION`; empty string = omitted — `response.py:paginate`
- §2.3 — insert — ambiguity — undeclared query params ignored; uninterpretable declared filter matches no rows — `routes_common.py:apply_filters`
- §2.3 — revise — ambiguity — `created_at` ties broken by insertion order; `id` never a sort key — `store.py:sorted_rows`
- §2.10 — insert — ambiguity — `ERR_NOT_FOUND` covers unknown route/method; non-object body → `ERR_VALIDATION`, absent body = `{}` — `app.py`, `validation.py:body`
- §2.11 — revise — **mismatch** — version bumps at most once per request and only on real change; no-op recompute leaves `updated_at`/`version` alone; inserted rows leave at `version` 1 — `store.py:touch`
- §3.1 — insert — ambiguity — section `code` trimmed before length/uniqueness tests; duplicate → `ERR_VALIDATION` — `routes_section.py`
- §3.1 — insert — ambiguity — `strike_limit` < `disqualification_strike_limit` violation → `ERR_VALIDATION`; three window dials must be ≥0 — `routes_section.py`
- §3.1 — insert — ambiguity — league dial minimums (≥1 / ≥0 per dial); even `lines_per_match` → `ERR_VALIDATION` — `routes_league.py:57-64`
- §3.1 — insert — ambiguity — the three instant orderings violated → `ERR_VALIDATION` — `routes_league.py:70-75`
- §3.2 — insert — ambiguity — `source`/role pairing is enforced: wrong role → `ERR_ROLE_NOT_PERMITTED` — `routes_player.py:91-94`
- §3.2 — insert — ambiguity — history entry `dynamic_rating` is a live snapshot, `effective_season_year` = section `season_year`, `recorded_at` = logical clock — `routes_player.py:114`
- §3.2 — revise — ambiguity — pinned-level divisor = opponents listed; fallback to live `rating_level`, still-null read as 0 — `derive.py:53-88`
- §3.3 — insert — ambiguity — duplicate team `name` in a league → `ERR_VALIDATION` — `routes_team.py:51-53`
- §3.3 — insert — ambiguity — activation off `PENDING` → `ERR_INVALID_STATE` ahead of all gates — `routes_roster.py:134`
- §3.3 — insert — ambiguity — activation clears `ineligible_reason` and `source_strike_id` — `routes_roster.py:163-164`
- §3.3 — insert — ambiguity — removal off `PENDING`/`ACTIVE` → `ERR_INVALID_STATE` — `routes_roster.py:179`
- §3.4 — insert — ambiguity — open-registration window → `ERR_OUTSIDE_REGISTRATION_WINDOW`; dead parent → `ERR_LEAGUE_ALREADY_TERMINAL` — `routes_league_lifecycle.py:61-75`
- §3.4 — insert — ambiguity — lock before `roster_lock_at` → `ERR_INVALID_STATE` — `routes_league_lifecycle.py:89-90`
- §3.4 — revise — **mismatch** — withdrawal cancels only matches whose `result_status` is still `PENDING` — `routes_team.py:157-163`
- §3.4 — revise — **mismatch** — the league-cancellation sweep ignores `result_status` entirely — `routes_team.py:181-186`
- §3.5 — revise — **mismatch** — deleted "must be marked active"; a `Facility` has no availability flag — `routes_match.py:157-162`
- §3.5 — insert — ambiguity — `courts_required` <1 or >`lines_per_match` → `ERR_VALIDATION`; >`court_count` → `ERR_FACILITY_COURTS_EXCEEDED` — `routes_match.py:136`
- §3.5 — insert — ambiguity — late confirmation → `ERR_MATCH_START_OUTSIDE_WINDOW` — `routes_match.py:204-205`
- §3.5 — revise — ambiguity — mark-played uses the broad `ROSTERS_LOCKED`/`IN_PLAY`/`PLAYOFFS` test, not confirmation's narrower pair — `routes_match.py:219-220`
- §3.5 — insert — ambiguity — `scheduled_from`/`scheduled_to` inclusive; null `scheduled_start_at` excluded by either bound — `routes_match.py:111-120`
- §3.5 — revise — **mismatch** — the `result_status PENDING` cascade precondition is team-driven only; league cancellation carries none — `routes_team.py:157-186`
- §3.6 — insert — ambiguity — default `note` validated then discarded; `Match` has no note field — `routes_match.py:239`
- §3.6 — revise — ambiguity — submission requires `schedule_status` exactly `PLAYED` (`ERR_MATCH_SCHEDULE_STATE_INVALID`) and `result_status` `PENDING` (`ERR_MATCH_RESULT_STATE_INVALID`) — `routes_scorecard.py:163-166`
- §3.6 — revise — ambiguity — two fault tiers: shape → `ERR_VALIDATION`, content → `ERR_SCORECARD_LINE_INVALID`; server sorts `lines` — `routes_scorecard.py:50-103`
- §3.6 — revise — ambiguity — 2–3 sets, no negative/level sets, tiebreak only in third position, line must be a completed 2-0/2-1 — `routes_scorecard.py:95-102`
- §3.6 — insert — ambiguity — unknown line player id → `ERR_INELIGIBLE_LINEUP`, never `ERR_REFERENCE_NOT_FOUND` — `routes_scorecard.py:112-114`
- §3.6 — insert — ambiguity — dispute fields optional on both branches; ignored on `VERIFY` — `routes_scorecard.py:223-253`
- §3.6 — revise — ambiguity — omitted `disputed_line_numbers` retains the prior array; `dispute_reason` written as null when omitted — `routes_scorecard.py:250-253`
- §3.6 — insert — ambiguity — `PLAYED` line `credited_to` decided by set count; null on a level line — `credit.py:126-128`
- §3.6 — insert — ambiguity — bad `basis` → `ERR_VALIDATION`; listing returns every team of the league as full `Team` objects — `routes_league.py:161-173`
- §3.6 — insert — ambiguity — provisional basis reads the verified scorecard else the newest open one; none → empty lines — `credit.py:32-43`
- §3.6 — insert — ambiguity — auto default strike carries the match id and system-generated `reason` — `routes_match.py:264-265`
- §3.7 — insert — ambiguity — rescission off `ACTIVE` → `ERR_INVALID_STATE` — `routes_discipline.py:99-100`
- §3.7 — revise — **mismatch** — on a `DISQUALIFIED` player, rescission is refused with `ERR_PLAYER_DISQUALIFIED_PERMANENT` only when remaining active weight would drop below `disqualification_strike_limit`; otherwise it proceeds and the status stays — `routes_discipline.py:104-109`
- §3.8 — insert — ambiguity — wrong step or null baseline → `ERR_INVALID_RATING_LEVEL` — `routes_appeal.py:47-53`
- §3.8 — revise — ambiguity — the only self-dealing test is that the filer does not captain the accused team; filer need not be in the league — `routes_grievance.py:61-62`
- §3.8 — revise — ambiguity — `RATING_VIOLATION` anchor = latest `decided_at` of the target's appeals; no anchor means no deadline — `routes_grievance.py:119-134`
- §3.8 — insert — ambiguity — grievance start-review off `IN_PLAY`/`PLAYOFFS`/`COMPLETED` → `ERR_INVALID_STATE` — `routes_grievance.py:165-166`
- §3.8 — insert — ambiguity — `DISMISS` against a quorum → `ERR_QUORUM_NOT_MET`; `UPHOLD` with no remedy → `ERR_REMEDY_NOT_ADMISSIBLE`, checked first (rank 47 vs 55) — `routes_grievance.py:210-238`
- §3.8 — revise — **mismatch** — the forfeit remedy voids *every* non-`VOIDED` scorecard of the match — `routes_grievance.py:269-272`
- §3.8 — insert — ambiguity — remedy strike has null `match_id` and generated `reason` — `routes_grievance.py:285-286`
- §3.8 — insert — ambiguity — the level-raise half of `PLAYER_STRIKE` is skipped when the target has no level — `routes_grievance.py:288-296`
- §3.9 — revise — **mismatch** — a fixture blocks seeding only when schedule *and* result are both unsettled; refusal `ERR_INVALID_STATE` — `routes_league_lifecycle.py:21-25,142-146`
- §3.9 — revise — ambiguity — no team left at `IN_PLAY` → `ERR_TEAM_STATE_INVALID`, ahead of the candidate predicates — `routes_league_lifecycle.py:148-150`
- §3.9 — insert — ambiguity — reseed visits every team and nulls the seed of a team that has left the candidate set; no status moves — `routes_league_lifecycle.py:177-187`
- §3.9 — revise — **mismatch** — advancement uses the same conjunctive open-match test (`ERR_INVALID_STATE`); parent off `REGISTRATION_OPEN` → `ERR_LEAGUE_ALREADY_TERMINAL` — `routes_league_lifecycle.py:200-215`
- §3.9 — insert — ambiguity — publish does not clear `proposed_recalc_level`/`proposed_recalc_dynamic` — `routes_section.py:192-212`

Deliberately not pinned (very low value, to honour "change as little as possible"): role-header whitespace trimming, the `extra=0` headroom re-check at activation, and the unreachable phase-one branch for a null `rating_level`.

---

## Pipeline complete — 2026-09-02T21:30:00.000Z

All nine steps ran. Final state of `tasks/task_2428_recreational_tennis_league_rating_administration/`:
- `SCAFFOLD.yaml` (2894 lines), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2650), `SCAFFOLD_CORNER_DESIGN.yaml` (6582) — `scaffold_lint.py` clean
- `test_helpers/` 9 modules, `test_suite/` conftest + 24 modules, **153 tests**
- `workspace/implementation/` 21 Flask modules + `start.sh` + `requirements.txt`, in-memory storage only
- `workspace/PRD.md` → `workspace/PRD_FINALIZED.md` → `workspace/PRD_COMPLETED.md` (588 lines each; 12 then 52 in-place revisions)
- `workspace/implementation/results.{1..8}.json` — 8/8 rounds at 153/153, 0 failed, 0 errors, 0 skipped
