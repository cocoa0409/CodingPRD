# Worklog — task_0275_recreational_adult_sports_league

## Step 1: Create task directory — 2026-06-10

Created `tasks/task_0275_recreational_adult_sports_league/` with `workspace/` subdirectory (pre-assigned path; no index scan performed). Scenario: Recreational Adult Sports League (team/free-agent registration, division/skill tier, schedule & venue assignment, referee/scorekeeping, standings & playoffs, forfeit/reschedule, fee & refund, sportsmanship/conduct). Difficulty band: Expert.

## Step 2: Generate scaffold (Expert band) — 2026-06-10

Generated the three Expert-band scaffold artifacts (`SCAFFOLD.yaml` 1325 lines, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` 1428 lines, `SCAFFOLD_CORNER_DESIGN.yaml` 1447 lines). `scaffold_lint.py` verdict: clean — all 542 §1.8/§1.9 calls conform to §1.5; all 14 §1.1 FKs have reverse-reachability GETs.

### Scaffold metrics
- **Entities:** 11 (Season, Division, Team, Player, RosterEntry junction, Venue, Referee, Game, RefereeAssignment, Payment ledger, ConductReport) — 14 FKs
- **State machines:** 5 — Season (7-state lifecycle), Team (branching + cyclic waitlist promotion), Game ×2 parallel dimensions (`schedule_status` × `score_status`, incl. cyclic DISPUTED→SUBMITTED), ConductReport (branching + cyclic UPHELD↔APPEALED)
- **Calculations:** 6 — `team_withdraw_refund` (3-branch dual-variant, floor rounding-order), `standings_points`, `standings_seed` (two pinned tiebreak chains), `player_suspension` (threshold cascade), `resource_overlap_referee` (half-open no-buffer), `resource_overlap_venue` (buffered, per venue+field)
- **Validations:** 15 (priority-ordered: auth → existence → OCC → season-phase → state → business safety/referential/temporal/constraint/fiscal)
- **Endpoints:** 45 (23 POST / 20 GET / 2 DELETE); empty `api_prefix` (flat/hybrid topology)
- **Error catalog:** 18
- **Roles:** 4 (LeagueAdmin/ConductOfficer opaque; TeamCaptain→Player, Referee→Referee entity-backed)
- **Concurrency:** 2 OCC rules (Division on team-register, Game on submit-score) with `expected_*_version` input + version-bump side effect

### Design index instance counts
- **§1.8 (difficulty):** 9 rules × 2 = 18 instances
- **§1.9 (corner):** 27 active instances + 10 `excluded_because` stubs = 37 total

## Step 3: Copy INSTRUCTION.md — 2026-06-10

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-10

Generated `workspace/PRD.md` (277 lines). Major sections: §1 Introduction; §2 Global Specifications (10 subsections — RBAC w/ per-role X-User-ID binding, response structure, pagination, common resource properties incl. Payment no-`updated_at`/no-`version` exception, hierarchical consistency & cascades, OCC for both `expected_division_version`/`expected_game_version`, nested retrieval + full 15-tier validation priority order, season-phase gating, monetary precision & fee ledger, enumerations & logical clock); §3 Business Logic (9 lifecycle/process subsections); §4 Endpoint table (all 45 endpoints, 4 cols); §5 Error catalogue (all 18 errors).

Hard contracts all PASS: field coverage 75/75, rule coverage (15 validation tiers, 2 OCC rules, all state machines, all 6 calculations, all 18 errors present in narrative), path purity (0 path tokens in §3). §2.2 verified byte-identical to fixed source. Neither design-index file (DIFFICULTY/CORNER) was read.

## Step 5: Generate unit tests — 2026-06-10

Generated test infrastructure (`test_helpers/`, 9 files: `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`) and `test_suite/` (10 files, **64 tests**): conftest.py + test_01_refunds_and_money (8), test_02_standings_and_seeding (5), test_03_game_states_and_scoring (4), test_04_conduct_and_suspension (7), test_05_withdrawal_cascades (4), test_06_scheduling_overlaps (8), test_07_registration_and_phase (11), test_08_concurrency_and_derived (4), test_09_crud_rbac_and_listing (13).

Queue provenance: Queue A (Difficulty §1.8) all 18 instances ≥2 tests each → 38 tests; Queue B (Corner §1.9) all 26 non-stub instances ≥1 test each → 26 tests. 64 tests = 64 verbatim `Design:` tags. **0 instances skipped** — every non-stub instance passed Coverage + Unique-derivability. For two `standings_seed` divergence instances whose literal setup plays no games, asserted the uniquely-PRD-derivable portion (created_at-asc final tie-break, seed determinism) rather than inventing fixtures. All 10 `excluded_because` corner stubs left untranslated. Audits passed: all files byte-compile; 78 PRD citations verbatim; no skip/xfail; Payment omits version/updated_at; entity-backed roles thread real entity ids.

## Step 6: Generate implementation — 2026-06-10

Built Python+Flask implementation at `workspace/implementation/`: `app.py` (~1915 lines, all routes + auth/RBAC + error handlers + serializers + state machines + calculations + cascades), `store.py` (in-memory Store, empty dicts on every boot), `response.py` (PRD §2.2 envelope), `errors.py` (ApiError + 18-code catalogue), `requirements.txt` (Flask==3.0.3), executable `start.sh`. **46 routes** (45 PRD §4 endpoints + 1 health probe). start.sh reads `$PORT` (default 10000), binds `0.0.0.0`, `exec`s python3 in foreground; storage in-memory only, no startup seeding, no disk persistence. Self-smoke-tested 0 failures across 3 suites.

## Step 7: Test and iterate to green — 2026-06-10

Final state: **60/60 passing in all 8 concurrent rounds, no errors, no flakiness.** (64 tests generated → 4 deleted → 60 remaining.)

**Iterations run:** 2 full 8-round parallel sweeps (baseline → fix batch → confirming sweep). Baseline: 28 deterministic failures/round. After fixes: a server-boot timeout surfaced under concurrent load (1 error/round) → fixed → final sweep 60/60 in all 8 rounds.

**Root-cause breakdown of the 28 baseline failures** (all deterministic, identical across rounds — not flakiness): three distinct test/helper defects plus one implementation gap, traced to PRD prose.

### Tests deleted (4) — PRD-silence / non-unique-derivability per cardinal rules
- `test_07::test_score_submit_blocked_when_season_not_in_play` — **PHASE-GATE SILENCE.** Asserts submission in the SCHEDULED season phase yields `ERR_SEASON_PHASE`. PRD §3.7 (the narrative §2.8 explicitly defers to) lists submission preconditions as *game* `schedule_status=SCHEDULED` + clock past `starts_at` — it names no season-phase gate. A faithful reader permits SCHEDULED-phase submission; expected rejection is not uniquely derivable.
- `test_01::test_no_refund_after_confirmed_game_writes_zero_audit_row` — **BRANCH UNREACHABLE.** Asserts a successful 200 withdrawal of a CONFIRMED team that has a confirmed-score game (NO_REFUND row). PRD §3.4 explicitly forbids CONFIRMED-team withdrawal when "a game involving the team has yet reached a confirmed score" and only in CLOSED/SCHEDULED. The no-refund refund branch is unreachable for a faithful §3.4 implementation; can't be satisfied without weakening a PRD-required check.
- `test_05::test_confirmed_count_conserved_under_withdraw_then_promote` and `test_05::test_waitlisted_team_auto_promoted_on_confirmed_withdrawal` — **CONFLICTING-RULE / non-unique.** PRD §3.4 ("`confirmed_team_count` recomputed downward by one" + "highest-seeded WAITLISTED team is auto-promoted" + §3.2 "frees a slot") is irreconcilable with §3.2 ("`confirmed_team_count` counts CONFIRMED **or WITHDRAWN_LOCKED**" + promotion requires count "still below `team_capacity`"). No implementation satisfies all clauses simultaneously in the withdraw-then-promote scenario; admits two divergent PRD-faithful readings.

### Fixes applied to `test_helpers/` (`fixtures.py`)
- Atomic creators `create_season/division/player/venue/referee` — let an explicit `name`/`full_name` override win over the unique default (`F.create_x_payload(**{"name": _uniq(...), **overrides})`), fixing the `got multiple values for keyword argument 'name'` TypeError (root cause E, `test_list_divisions_pagination_envelope`).
- `advance_to(...)` — supply `force=True` automatically for the OPEN→CLOSED step. The setups drive the clock to control refund/eligibility timing, not the close date; PRD §3.1 makes early close the admin's documented `force` prerogative (root cause A, ~11 tests whose setup hit "Registration window has not closed").

### Fixes applied to `test_suite/`
- `test_01` — six refund tests now `advance_to(season, "CLOSED")` before withdrawing a CONFIRMED team (PRD §3.4 permits CONFIRMED-team withdrawal only while CLOSED/SCHEDULED). Faithful precondition repair, not assertion weakening (root cause B).
- `test_07` — four capacity/phase tests changed `team_capacity=1`→`2` (and added a third team where "division full" is needed). `team_capacity=1` violated PRD §3.1's "at least 2"; the impl correctly rejected it (root cause C).

### Fixes applied to `implementation/` (`app.py`)
- `get_standings` (`GET /divisions/{id}/standings`) — return the seeded list through the paginated envelope (`list_response`) so `meta.total_count`/`has_more` are present, preserving seed order. PRD §2.3: "Every list response carries the pagination bookkeeping in the `meta` object" (root cause D, 4 standings tests).
- `__main__` boot block — monkeypatch `socket.getfqdn` to short-circuit before `app.run`. werkzeug's `server_bind()` calls `getfqdn("0.0.0.0")`, which on this macOS host blocks ~5s on a reverse-DNS timeout; under the per-test restart harness (server rebooted before every test, 8 rounds concurrent) this blew the boot timeout, causing the deterministic restart error on `test_confirm_score_by_team_captain_forbidden`. Boot dropped 5.1s → 0.18s. Pure runtime fix; no API behavior touched.

**Final state:** 60/60 passing in all 8 concurrent rounds, no errors, no flakiness.

## Step 8: Finalize PRD — align to implementation — 2026-06-10

Produced `workspace/PRD_FINALIZED.md` as a minimal patch of `PRD.md`. Line counts: 276 → 276 (2 lines changed, 0 added/removed, ~0.7% delta).

Changes:
- **§3.7 — insert** — Pinned the score-submission season-phase gate: submission permitted only while season `registration_status` is `SCHEDULED` or `IN_PLAY` (else `ERR_SEASON_PHASE`); clarified confirmation has no such gate. PRD §3.7 was silent; impl pins it — `app.py:1628` (gate), `1659-1682` (confirm has no gate).
- **§3.4 — revise** — Replaced the false "confirmed_team_count recomputed downward by one" + unconditional auto-promotion with impl behavior: because `confirmed_team_count` counts `WITHDRAWN_LOCKED` (§3.2), the withdrawal does not free the slot, so auto-promotion fires only when count still below `team_capacity` and a `WAITLISTED` team exists; count actually drops only at `IN_PLAY` (`WITHDRAWN_LOCKED`→`WITHDRAWN`). Resolves the §3.4/§3.2 internal conflict toward impl — `app.py:245-250` (count), `1034-1047` (withdraw), `1053-1068` (`_auto_promote_waitlist`), `657-664` (`_inplay_cascade`).

Step 7 items deliberately NOT patched: test_01 no-refund deletion (branch already forbidden by §3.4, impl matches); fixture fixes (pure fixture bugs); test_suite repairs (preconditions already pinned by §3.4/§3.1); get_standings envelope (already mandated by §2.3); getfqdn monkeypatch (runtime boot fix, no API behavior). NO-NEW-MISMATCH pre-edit search performed and logged for both edits.

## Step 9: Complete PRD — eliminate residual ambiguity/mismatch — 2026-06-10

Produced `workspace/PRD_COMPLETED.md` from `PRD_FINALIZED.md` via full PRD-vs-implementation scan. Line counts: 276 → 276 (all in-paragraph, no new sections). Char delta: +1,480. Ambiguity-pins: 5; mismatch-revisions: 1.

Changes:
- **§3.1 — revise — mismatch** — `ERR_SCHEDULE_INCOMPLETE` also raised for unsettled PLAYOFF game on PLAYOFFS→COMPLETE; broadened prose to include COMPLETE — `app.py:682-691` (`_check_can_complete`).
- **§3.6 — insert — ambiguity** — pinned `ERR_INVALID_REQUEST` for non-future reschedule `starts_at` + ordering (after RESCHEDULE_REQUESTED state check, before overlap checks) — `app.py:1525-1526`.
- **§3.7 — insert — ambiguity** — pinned `ERR_INVALID_STATE` when game has not started (clock < starts_at) on score submit — `app.py:1642-1643`.
- **§3.7 — insert — ambiguity** — pinned drawn score has no losing captain → dispute rejected `ERR_FORBIDDEN` — `app.py:1699-1709`.
- **§3.7 — insert — ambiguity** — pinned confirm error split: `ERR_INVALID_STATE` (no ASSIGNED HEAD exists) vs `ERR_FORBIDDEN` (actor not that head) — `app.py:1664-1675`.
- **§3.7 — insert — ambiguity** — pinned DISPUTED resubmission restricted to assigned head referee; captain/non-head → `ERR_FORBIDDEN` — `app.py:1636-1638`.
- **§3.8 — insert — ambiguity** — pinned `GET /divisions/{id}/standings` returns same seed chain anytime, CONFIRMED teams only, paginated envelope — `app.py:744-747, 841-850`.

## Pipeline complete — 2026-06-10

All 9 steps executed end-to-end. Final test state: **60/60 passing across all 8 concurrent stability rounds** (64 generated → 4 deleted for PRD-silence/non-unique-derivability). Deliverables present: SCAFFOLD.yaml (+ DIFFICULTY/CORNER design indices), workspace/PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ (9 files), test_suite/ (10 files), workspace/implementation/ (Python+Flask, in-memory, 8 passing results.*.json).
