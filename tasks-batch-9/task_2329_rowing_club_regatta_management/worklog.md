# Worklog — task_2329_rowing_club_regatta_management

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2329_rowing_club_regatta_management/` and `tasks/task_2329_rowing_club_regatta_management/workspace/` (directory name pre-allocated by the caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T20:25:00.000Z

All three artifacts are complete and the lint is clean.

Final lint run (verbatim):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2329_rowing_club_regatta_management/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2329_rowing_club_regatta_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2329_rowing_club_regatta_management/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    68
  §1.1 entities declared:     13
  §1.8 instances scanned:     21
  §1.9 instances scanned:     78
  Calls scanned (§1.8+§1.9):  861

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_2329_rowing_club_regatta_management/`):
- `SCAFFOLD.yaml` (§1.0–§1.7, 145 KB) — no `scaffold_difficulty_design` / `scaffold_corner_design` keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, single top-level key, 128 KB)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, single top-level key, 240 KB)

Scaffold surface (domain `boathouse`, prefix `/boathouse`, logical clock default `2026-08-01T00:00:00Z`):
- 13 entities: Member, DuesInvoice, Shell, DamageReport, WaterConditionReading (immutable, `common_fields: false`), WaterSession, Regatta, RegattaEntry, LineupSeat, Heat, RaceLane, Protest, TrailerLoad
- 11 state machines (cyclic shape: shell repair loop, protest remand loop), 2 OCC `concurrency_rules` (`ERR_STALE_ENTRY_VERSION`, `ERR_STALE_TRAILER_VERSION`, both 412)
- 11 calculations (2 dual-variant: dues provisional/actual, shell condition conservative/optimistic; algorithms include `waterfall_allocation`, `threshold`, `interval_merge`, `aggregation`)
- 58 validations across 58 priorities, 68 endpoints, 71 error codes (69 in §1.6 + 2 OCC), 7 roles with `role_model: segregation_of_duties`
- complexity layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy; consistency `immediate`

§1.8 difficulty design: all 9 §0.5 `rule_id`s covered by 21 instances (dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2 at depth 5 and 4, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 3, compensating_invariant 2) — above the Expert band minimum on every rule.

§1.9 corner design: 94 instances over all 9 guide sections (entities 12, state_machines 14, calculations 15, validations 17, endpoints 6, errors 17, rbac 7, complexity_layers 5, consistency_model 1); 78 carry executable `test_recipe`s and 16 are `excluded_because` stubs citing a §1.8 instance by name. Every one of the 71 error codes is referenced by at least one design-file instance.

Notable design fixes made during generation: `ERR_INVOICE_NOT_PAYABLE` was unreachable (shadowed by the priority-8 terminal-state rule), fixed by carving payments/true-up out of validation 8 and folding it into validation 55; validation 22 was broadened to back the Member/Regatta/TrailerLoad transition preconditions that had no dedicated error; the TrailerLoad `OPEN→SEALED` precondition was relaxed to `Regatta.status IN {OPEN_FOR_ENTRY, ENTRIES_CLOSED}` so sealing before entries close is legal.

## Step 3: Copy shared files — 2026-09-01T20:25:30.000Z

Copied `INSTRUCTION.md` to `tasks/task_2329_rowing_club_regatta_management/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T20:43:00.000Z

PRD generated and audited clean.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2329_rowing_club_regatta_management/workspace/PRD.md` — **511 lines**, ends at §5 (no audit text inside the document).

## Sections
- **§1 Introduction** — 3 paragraphs (club pain, service scope under `/boathouse`, the two engineering properties: explicit logical clock and pinned arithmetic).
- **§2 Global Specifications** — 11 subsections: 2.1 RBAC (7 roles, `X-User-ID`/`X-User-Role`, opaque `ClubAdmin` vs six `entity_backed:Member` roles); 2.2 API Response Structure (verbatim block); 2.3 Pagination and List Filtering (limit 10/1/100, offset 0, `created_at` ASC, every query filter); 2.4 Common Resource Properties (incl. `WaterConditionReading` carrying only `id`/`created_at`); 2.5 Logical Clock, Windows and Temporal Comparisons (baseline `2026-08-01T00:00:00Z`, half-open vs closed windows); 2.6 Rounding Discipline (per-component vs sum-then-round, opposing orders); 2.7 Optimistic Concurrency (both OCC rules, 412s); 2.8 Reference Resolution (left-to-right paths, 13 entity-specific 404s, body FKs); 2.9 The Rejection Ladder (all 58 priorities in order with `applies_to` scopes and the priority-8/55 carve-out); 2.10 Cascade Discipline (immediate, version-incrementing, non-suppressible; derived aggregates); 2.11 Segregation of Duties (4 checks + audit stamps).
- **§3 Business Logic** — 9 subsections: membership/standing; dues assessment, payment, true-up, void, delinquency chain; fleet, damage triage, repair bays, condemnation; river readings and clearance; regattas, entries, lineup declaration; weigh-ins, fees, confirmation, scratches; trailer rack waterfall; race day lanes/results/advancement; jury protests, deposits, remedies.
- **§4 Endpoint Definitions** — 4-column table, 68 rows.
- **§5 Error Code Catalogue** — 2-column table, 69 rows.

## Coverage audit (mechanical, re-run after repairs)

**Hard Contract 1 — Field-Name Coverage: PASS.** 125/125 entity field names present verbatim in backticks; 96/96 endpoint input + path identifiers present (includes `expected_regatta_entry_version`, `expected_trailer_load_version`, `to_iso8601`, `to_status`, `seats`, `lane_results`, `disposition`, `decision`, `remedy`, `rationale`, `amount_cents`, `limit`, `offset`, `{id}`). All enum literals across all entities present: 0 missing.

**Hard Contract 2 — Rule Coverage: PASS.** All 58 validation priorities appear in §2.9 in scaffold priority order with their `applies_to` scopes (the only two error IDs not named individually in the ladder are `ERR_ENTRY_NOT_FOUND`/`ERR_MEMBER_NOT_FOUND`, the scaffold's nominal labels for the generic existence rungs 3 and 4, whose 13 entity-specific codes are enumerated in §2.8 and cross-referenced from those rungs). Both `concurrency_rules` documented with OCC field, endpoint framing and 412 error. All 11 state machines with 80/80 transitions, preconditions, side effects, terminal states and every documented cycle; 78 use explicit `FROM → TO` arrow form, the remaining 2 (`RaceLane` `PROVISIONAL → PENDING` on RE_ROW and `PROVISIONAL → VOIDED` on regatta cancellation) are stated as set-based prose in the same paragraphs. All 11 calculations with every constant value present (0 missing after adding decimal forms for the six percentage constants), pinned rounding/evaluation orders, input sets, tie-breaks and both dual-variant divergences. Sibling-branch asymmetries preserved (e.g. `FILED` vs `REMANDED` review-opening screens differently; strict `<` on water temp vs `<=` on the combined sum; buffer applies to hull conflicts but not launch-driver conflicts). 69/69 errors in §5 with **0 HTTP status mismatches**; 68/68 endpoints in §4 with **0 role-list mismatches**.

**Hard Contract 3 — §3 Path Purity: PASS.** 1,014 backtick tokens in §3, **0 violations** — no token starts with `/`, no bare HTTP method, no method+path combination; zero occurrences of the string `/boathouse` anywhere in §3.

## Step 5: Generate unit tests — 2026-09-01T23:15:00.000Z

Generation is complete. Both queues are fully translated and verified.

## Files written

**`test_helpers/` (9 files, infrastructure)** — `__init__.py` (barrel), `constants.py`, `types.py`, `api_errors.py` (69 error ids + HTTP map, registered via `set_error_http_status_map`), `api_client.py` (68 methods, `/boathouse` prefix), `test_users.py` (7 role header builders), `factories.py`, `assertions.py` (20 helpers), `fixtures.py` (scenario builders + 15 pytest fixtures).

**`test_suite/` (17 files, 152 tests)**

| file | tests | source |
|---|---|---|
| `conftest.py` | — | fixture re-exports |
| `test_01_season_dues_assessment.py` | 6 | queue A |
| `test_02_fleet_condition_and_repairs.py` | 7 | queue A |
| `test_03_water_safety_clearance.py` | 6 | queue A |
| `test_04_entry_fees_and_scratch_ledger.py` | 6 | queue A |
| `test_05_race_day_seeding_and_jury.py` | 4 | queue A |
| `test_06_cascade_chains.py` | 4 | queue A |
| `test_07_threshold_boundaries.py` | 8 | queue A |
| `test_08_trailer_racking.py` | 4 | queue A |
| `test_09_entity_shapes_and_listings.py` | 18 | queue B `entities` |
| `test_10_lifecycle_transitions.py` | 14 | queue B `state_machines` |
| `test_11_computed_values.py` | 13 | queue B `calculations` |
| `test_12_validation_gates.py` | 15 | queue B `validations` |
| `test_13_endpoint_behaviour.py` | 8 | queue B `endpoints` |
| `test_14_rejection_ladder.py` | 22 | queue B `errors` |
| `test_15_role_authorisation.py` | 11 | queue B `rbac` |
| `test_16_concurrency_and_visibility.py` | 6 | queue B `complexity_layers` + `consistency_model` |

## Coverage audit (machine-verified against both YAMLs)

- **Queue A: 45 tests / 21 difficulty instances** (floor was 42). All 21 covered, zero skipped.
- **Queue B: 107 tests / 78 non-stub corner instances** (floor was 78). All 78 covered — entities 12→18, state_machines 10→14, calculations 8→13, validations 15→15, endpoints 5→8, errors 17→22, rbac 7→11, complexity_layers 3→4, consistency_model 1→2.
- **99 distinct `Design:` tags; MISSING: none; UNKNOWN: none.** No tag points at any of the 16 `excluded_because:` stubs (they were not translated, as required).
- **AST audit:** all 152 test functions have a docstring whose single, terminal line is a `Design:` tag, plus at least one `PRD:` citation. No dual tags.
- **Citation audit:** every `PRD: "..."` string survives a literal whitespace-normalised grep of `workspace/PRD.md` (152/152). No test file references the scaffold or any scaffold section.
- `python -m pytest test_suite --collect-only` → **152 tests collected, 0 errors**; pyflakes clean (only the expected `# noqa: F401` fixture re-export warnings in `conftest.py`, which pyflakes doesn't honour). No skip/xfail markers, no mocking.

## Instances skipped

**None.** Every non-stub instance in both indices passed the PRD-first two-condition filter and was emitted.

## Design-vs-PRD conflicts resolved in favour of the PRD

Where a design recipe asserted something the PRD does not uniquely derive, I emitted the PRD-derived outcome and dropped the non-derivable assert rather than weakening or skipping:

- Two rack-assignment recipes racked **DRAFT** entries while asserting `rack_units_used == 1`; PRD §3.7 counts only `SUBMITTED`/`CONFIRMED`/`RACED` entries, and `OPEN → SEALED` requires used > 0 — both fixtures rebuilt from submitted entries so the designed counters are correct.
- `corner_weigh_in_at_window_close_instant_returns_409` asserted `deadweight_kg == 0`; PRD §3.5 says seats are born null → asserted `is None`.
- `corner_confirm_without_coxswain_weigh_in_returns_409` asserted the cox seat still reads `NOT_REQUIRED`; submission moves it to `PENDING` → asserted `PENDING`.
- `corner_jury_chair_cannot_open_review_on_own_protest_returns_403` says "UNDER_REVIEW"; the PRD status name is `UNDER_JURY_REVIEW`.
- `corner_immediate_visibility_of_fee_ledger_after_submit` asserted `refund_cents == 0` on submit; PRD §3.6 leaves it null until a scratch → asserted `is None`.
- Exact-string timestamp asserts (e.g. `protest_window_closes_at == "...Z"`) replaced with `.startswith(...)`, since PRD §2.4 mandates three fractional digits.
- For `corner_entry_version_increments_on_every_write`'s "updated_at has advanced", the logical clock is advanced between writes (PRD §2.5: all stamped instants come from the logical clock), making the assertion derivable.

## Step 6: Generate implementation — 2026-09-01T22:35:00.000Z

The implementation is complete and verified end to end.

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_2329_rowing_club_regatta_management/workspace/implementation/` — 24 files:

- Launcher/deps: `start.sh` (guarded `pip install`, then `exec python3 app.py`, binds `0.0.0.0:$PORT`, default 10000), `requirements.txt` (`Flask==3.0.3`)
- App core: `app.py`, `clock.py`, `db.py`, `errors.py`, `util.py`, `calc.py`
- Cross-cutting layers: `auth.py`, `validate.py`, `response.py`, `derive.py`, `helpers.py`, `cascade.py`
- Routes (9 blueprints under `/boathouse`): `routes/{__init__,members,dues,fleet,water,regattas,entries,race,jury,trailers}.py`

**68 endpoints** registered (verified via `url_map.iter_rules()`), matching the PRD's endpoint table exactly.

## Storage / boot
Storage is 13 module-level Python dicts in `db.py`; no SQLite, no disk writes, nothing seeded. A fresh import confirms all 13 stores at length 0 and the logical clock at the default `2026-08-01T00:00:00Z`. `create_app()` calls `db.reset_all()` + `clock.reset()`, so every `start.sh` relaunch under `--isolation per-test-server` starts from an empty world.

## Notable design decisions
- **Uniform handler shape** enforcing the 58-rung global rejection ladder in order: `@auth.require` → `helpers.load` (404) → `helpers.check_fk` → `validate.*` (ERR_INVALID_REQUEST) → version guards (412) → `not_terminal` → declared state rungs → domain rungs → mutate → serialize. Lineup submission pre-sweeps `seats[].member_id` for existence so rung 4 precedes rung 5.
- **Versioning**: `db.touch` dedupes per row per request via `flask.g._touched`, and `base_record` pre-registers new ids so a cascade can't push a just-created row to version 2.
- **Pinned arithmetic** in `calc.py`/`derive.py` with `Decimal` + `ROUND_HALF_UP`: dues and scratch refunds round per component then sum; entry fee rounds once at the late-fee product; condition index sums unrounded then rounds once; weights at 1 dp.
- **Ladder ambiguities resolved**: protest filing reports `ERR_HEAT_NOT_PROVISIONAL` for any non-provisional heat (skipping the parent terminal guard); rack assignment checks `ERR_TRAILER_TIER_UNAVAILABLE` before `ERR_TRAILER_REGATTA_MISMATCH`; rung 21 (driver ACTIVE) applies to every trailer transition; non-filer withdrawal is `ERR_UNAUTHORIZED` checked before body validation; unresolved protests on officialize and missing-lane completeness map to `ERR_INVALID_STATUS_TRANSITION` / `ERR_INVALID_REQUEST` respectively.
- **Advancement** (undeclared but required): officializing a source heat seeds the target and moves it `SCHEDULED → LANES_ASSIGNED`; re-seeding reuses existing PENDING lane ids while updating `lane_number` per the club preference order `[3,4,2,5,1,6,7,8]`.

## Verification
Three throwaway smoke suites (in `/tmp`, not part of the deliverable) over ~100 assertions all pass, covering: dues assessment 27584 and full-season 118500 with true-up 43000, the four-hop delinquency chain including SUBMITTED→LINEUP_DECLARED demotion and seat unblocking on settlement, damage triage/bay-conflict/verify with residual index 90 and structural condemnation retiring the hull, water posture OPEN/RESTRICTED/CLOSED with clearance revocation and launch-coverage, entry fees 25850 / late fee 2350, refund windows (100% → 4500, 55% → 2723, 0% after the scratch deadline), coxswain weigh-in 15.1 FAILED then 15.0 PASSED, rack allocation tier 1 position 1 with the full seal→depart→arrive→return tow, heats/lanes/results/places/officialize/advancement, and the jury flow (remand → max rounds → uphold DISQUALIFY, RE_ROW returning lanes to PENDING, deposit 5000 → 0). The two apparent failures in the second suite were my script's expectations, not server behaviour: submitting with a nonzero `dues_balance_cents` correctly returns 402 `ERR_SEAT_MEMBER_DELINQUENT`, and a scratch after `scratch_deadline_at` correctly refunds 0.

The smoke server was stopped by recorded PID (never a broad `pkill`, which in this shared environment matches other agents' processes), and `__pycache__` directories were removed.

## Step 7: Run tests and iterate — 2026-09-02T05:14:00.000Z

All iteration is complete. Final state below.

## Summary

**Iterations run: 10 full 8-round parallel sweeps launched; 7 of them completed all 8 rounds** (attempts 3, 4 and 5 were killed mid-run by something external on this shared host — all 8 `prd-bench-local-run` parents died within the same second, orphaning their pytest children; I cleaned those up by PID with `/proc/<pid>/cwd` verification, never with a broad `pkill`).

**Result of the last four completed sweeps (32 rounds, 4 864 test executions): `failed == 0` in every single round.** Every non-passing outcome, in every round, is harness infrastructure, not the suite:

| sweep | rounds | assertion failures | infra errors | tests passing in >=1 round |
|---|---|---|---|---|
| 6 | 8/8 | 0 | 700 (all `lsof` port-kill timeout) | 149/152 |
| 7 | 8/8 | 0 | 552 (all `lsof`) | 151/152 |
| 8 | 8/8 | 0 | 256 (all `lsof`) | **152/152** |
| 9 | 8/8 | 0 | 208 `lsof` + 1 conn-reset | **152/152** |
| 10 | 8/8 | 0 | 311 `lsof` + 1 conn-reset | **152/152** |

The single error signature is `subprocess.TimeoutExpired: Command 'pids=$(lsof -ti:<port> -sTCP:LISTEN ...)' timed out after 5 seconds`, raised in `prd_bench_local_runner/pytest_plugin.py::_kill_port` (5 s hard-coded, not configurable) during the per-test server reboot. The host carries 3 000–3 800 processes and load average 200–430 from other agents all night; a bare `lsof -ti:<free port>` measured 1.3–1.5 s at load 220 and blows past 5 s in bursts. `passed == total` needs 1 216 consecutive sub-5 s `lsof` calls, which is unreachable at this contention. I did not touch the shared runner.

**Independent verification that closes the gap:** I ran the whole suite test-by-test, each test against its own freshly booted server on its own private port (equivalent isolation to `--isolation per-test-server`, but without the `lsof` path). Pass 1: **152/152 PASS, 0 FAIL**. Pass 2: 149/152 (the 3 misses were `Connection refused` server-boot failures under load). Pass 3: 121/124 before it was externally killed (the 3 misses again boot refusals). Combined with the sweeps, all 152 tests are confirmed green.

**Tests deleted: none.** No failure survived STEP 0 as a PRD-coverage or unique-derivability problem, so no deletion was warranted. Suite still collects 152 tests.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `add_single`, `add_coxed_four`, `add_eight`: replaced explicit-keyword-plus-`**overrides` forwarding with a defaults-dict merge. The old form raised `TypeError: add_shell() got multiple values for keyword argument 'hull_weight_kg'` whenever a caller overrode a default (e.g. `add_coxed_four(hull_name="Cormorant", hull_weight_kg=51.0, home_bay="BAY-4")` in `test_15_role_authorisation.py` and `test_14_rejection_ladder.py`), erroring 5 tests at setup and masking their real assertions.

**Fixes applied to `test_suite/`:**
- `test_11_computed_values.py` — fixture `away_load_with_two_draft_singles` -> `away_load_with_two_submitted_singles`: it racked `DRAFT` entries and then asserted `rack_units_used == 1`, but PRD §3.7 recomputes that counter over "the entries whose `trailer_load_id` is this load and whose status is `SUBMITTED`, `CONFIRMED` or `RACED`", so 0 was the PRD-correct answer. The fixture now carries both entries to `SUBMITTED` (rename applied at all 4 usage sites).
- `test_14_rejection_ladder.py` — `test_the_jury_cannot_rule_on_a_protest_it_never_opened`: the ruling payload omitted the `remedy` that PRD §3.9 requires "when upholding", so PRD §2.9 rung 5 (payload shape, `ERR_INVALID_REQUEST`) legitimately fired ahead of rung 19. Added `"remedy": "DISQUALIFY"` so rung 19 is the first failing rung. The `ERR_PROTEST_NOT_UNDER_REVIEW` assertion was left exactly as strict as before.

**Fixes applied to `implementation/`: none.** In all three cases the implementation was PRD-faithful and the test layer was at fault; no PRD-required check was removed or weakened, no endpoint/field/side-effect was added. Re-confirmed the storage contract: `db.py` is plain in-memory dicts, `create_app()` calls `db.reset_all()` + `clock.reset()`, and a grep of `implementation/**.py` finds no `open(`, `json.dump`, `sqlite3`, `pickle`, `/tmp/` or external store, and no seeded entities.

### Orchestrator's independent re-verification (after Step 7 exited)

The orchestrator re-ran the sweep itself to confirm the subagent's account, as host load decayed from ~200 to ~140:

| run | shape | assertion failures | infra errors | best round |
|---|---|---|---|---|
| A | 8 rounds parallel | 0 | 48 (47 `lsof`, 1 harness-induced setup 404 that did not recur) | 151/152 |
| B | 8 rounds parallel | 0 | 40 (all `lsof`) | 150/152; all 152 tests passed in >=1 round |
| C | 2 rounds parallel (low self-contention) | 0 | 3 (all `lsof`) | 151/152 |
| D | 1 round alone (zero self-contention) | 0 | 1 (`lsof`, on `test_seeding_before_the_regatta_is_racing_is_refused`) | **151/152** |

Run D is the decisive datum: with no self-contention at all, the only non-pass is the shared runner's hard-coded 5 s `lsof` port-kill timeout firing on one arbitrary test. Host state at the time: load average ~140, ~2 900 processes, and **176 stray `python3 app.py` servers belonging to other agents' task directories** (verified per-PID via `/proc/<pid>/cwd`; exactly 1 belonged to this task and was cleaned up by PID). Across every run the failing test is different and the signature is always identical, while `failed` is 0 everywhere and every one of the 152 tests has passed in multiple rounds.

**Conclusion: the suite is green — 152/152, zero assertion failures. The residual gap to a literal `passed == total` round is an external-load limitation of the shared test runner, not a defect in the implementation or the test suite.** The shared runner was not modified.

## Step 8: Finalize PRD — 2026-09-02T05:22:00.000Z

All seven edits are in. Line counts unchanged (510 → 510); byte size 87,638 → 90,356 (+3.1% by characters, 7 of 510 lines revised ≈ 1.4% of lines).

## Changes

- **§2.9 rung 18** — revise — protest filing applies no rung-8 terminal guard to the resources it names, so a heat in any non-`RESULTS_PROVISIONAL` status (including terminal `RESULTS_OFFICIAL`) is `ERR_HEAT_NOT_PROVISIONAL`, and a withdrawn filer surfaces at rung 21 — `routes/jury.py:39-49`
- **§3.7 rack waterfall** — insert — placement search (rung 47) is decided above the regatta-match check (rung 53) on a rack assignment — `routes/trailers.py:102-110`
- **§3.7 Moving the trailer** — insert — the towing driver's `ACTIVE` standing is screened on *every* transition request (not only `SEALED → DEPARTED`), ahead of transition legality — `routes/trailers.py:155-160`
- **§3.8 Results** — insert — each `lane_results` element identifies its lane by `race_lane_id` or `lane_number`; malformed element = rung-5 `ERR_INVALID_REQUEST`, unknown `race_lane_id` = rung-4 `ERR_LANE_NOT_FOUND`; missing-lane completeness is judged only after the heat-status gate and reported as `ERR_INVALID_REQUEST`; non-`PENDING` elements ignored — `routes/race.py:411-451`
- **§3.8 Officialization** — insert — an unresolved protest is reported as `ERR_INVALID_STATUS_TRANSITION` — `routes/race.py:486-489`
- **§3.8 Advancement step three** — insert — target seeding is truncated to the filtered lane list, is repeatable across further source officializations, reuses an advancing crew's existing `PENDING` lane row (same `id`/`created_at`, only `lane_number` rewritten), and moves the target `SCHEDULED → LANES_ASSIGNED` only when it is still `SCHEDULED` — `routes/race.py:227-301`
- **§3.9 Withdrawal** — revise — a `reason` is required; a non-filer is `ERR_UNAUTHORIZED`, decided right after the path protest resolves and ahead of body validation — `routes/jury.py:198-206`

## Per-edit pre-edit search log

1. **Rung 18 / terminal guard on protest filing.** (a) Subject: which rung reports a parent heat's status, and where rung 8 applies. (b) Enumerated: `grep -rn not_terminal routes/` — all 33 sites; `jury.py:97/141/208` guard the *protest*, `race.py:174/239/275` guard the heat on assign-lanes/results/officialize, and `entries.py:35-36`, `race.py:123`, `trailers.py:54/99`, `water.py:98` guard *parents* on creation; `jury.py:26-71` (filing has no terminal guard at all) and `jury.py:143-149` (ruling guards the protest, then the heat's provisional status). (c) Adjustment: scoped the sentence to *filing a protest* instead of a general "parents are never terminal-guarded" claim, which `entries.py:35`/`race.py:123`/`trailers.py:54`/`water.py:98` would have contradicted; also worded the filer clause as rung 21 rather than a terminal claim, matching `jury.py:44`.

2. **Rung 47 above rung 53 on rack assignment.** (a) Subject: precedence of tier-unavailable vs regatta-mismatch. (b) Enumerated: `trailers.py:87-118` (assign: version → terminal → open → placement → mismatch), `trailers.py:121-145` (release: mismatch checked with no placement search, then `ERR_INVALID_STATUS_TRANSITION` when the entry holds nothing), `derive.rack_allocate` (`derive.py:388-412`). (c) Adjustment: added "an assignment naming an entry…" so the release path — which reports `ERR_TRAILER_REGATTA_MISMATCH` with no placement search — is not mis-described.

3. **Driver standing on trailer transitions.** (a) Subject: where `ERR_MEMBER_NOT_ACTIVE` applies to a trailer load. (b) Enumerated: `grep -n member_active routes/*.py` → `trailers.py:160` (the only trailer site, before the transition branch), `entries.py:115`, `jury.py:44`, `water.py:103/185`; all `cascade.py` trailer paths (`release_rack`, `scratch_entry`, `condemn_shell`) — none perform a server-initiated trailer *status* transition, so the claim stays confined to the transitions endpoint. (c) Adjustment: wrote "ahead of the transition legality of rung 22" rather than "before every other check", since `helpers.not_terminal("trailer", load)` (rung 8) still fires first on a `RETURNED` load.

4. **`lane_results` shape and completeness.** (a) Subject: results payload parsing and its error codes/ordering. (b) Enumerated: `race.py:405-466` (rung-4 lane FK sweep, per-element `elapsed_seconds`/identifier validation, terminal + `ERR_HEAT_NOT_ASSIGNED` gates, then the completeness loop, then `derive.recompute_places`); `derive.recompute_places` (`derive.py:347-357`); `test_helpers/factories.py:228` confirms tests use `race_lane_id`. (c) Adjustment: said "identifies its lane — by `race_lane_id`, or equivalently by the `lane_number`…" rather than naming one key exclusively, because the impl accepts either; and split shape (rung 5) from completeness (post-status-gate) so a `SCHEDULED` heat still reports `ERR_HEAT_NOT_ASSIGNED` first.

5. **Unresolved protests on officialize.** (a) Subject: error code for the open-protest precondition. (b) Enumerated: `race.py:486-489` (`helpers.invalid_transition`), `regattas.py:113-127` (same code on `RACING → COMPLETE`), `helpers.invalid_transition` (`helpers.py:63`), the shared `OPEN_PROTEST_STATUSES` tuple in both modules. (c) None — the two paths already agree, so the parallel was stated explicitly.

6. **Target-heat seeding on advancement.** (a) Subject: `_seed_lanes` and the target heat's status. (b) Enumerated: `race.py:227-254` (`_seed_lanes`, shared by initial seeding and advancement; reuses `PENDING` rows, rewrites `lane_number`, truncates at `len(numbers)`), `race.py:257-301` (`_run_advancement`, status bump only when `selected` and target is `SCHEDULED`), `race.py:368-402` (`assign_lanes` — requires `SCHEDULED`), `cascade.demote_heat`/`void_lane` (`cascade.py:58-83` — a demotion voids every remaining `PENDING` lane, which is why the reuse branch is unreachable from initial seeding), `derive.occupied_lane_count`. (c) Adjustment: scoped the lane-reuse and status sentences to the advancement re-seed ("every further source heat that officializes"), and made the status bump conditional ("still `SCHEDULED`… keeps the status it holds") so an already-`LANES_ASSIGNED` or provisional target is not mis-described.

7. **Protest withdrawal.** (a) Subject: withdrawal authorisation and payload. (b) Enumerated: `jury.py:198-219` (ownership check at line 202 before `validate.body()` at 205; `reason` required non-empty at 206; then rung 8 and the `FILED` guard), `auth.require("Member")` (`auth.py:15-38`), `derive.deposit_held_cents` (`derive.py:231-242`) for the ledger sentence left untouched, plus `test_helpers/fixtures.py:616` (helper posts `{}` but is never called by any test, so nothing contradicts the required `reason`). (c) Adjustment: phrased the ordering as "as soon as the protest in the path resolves, ahead of the payload-shape rung" rather than "before all other checks", since header/role rungs 1-2 and path resolution (rung 3) still precede it.

**Deliberately not patched:** the `test_helpers/fixtures.py` `**overrides` `TypeError` (pure fixture bug, no behavioral content) and the `test_11` `DRAFT` → `SUBMITTED` fixture rename (PRD §3.7 already pins `rack_units_used` over `SUBMITTED`/`CONFIRMED`/`RACED`; prose kept verbatim) and the missing-`remedy` ruling payload (PRD §3.9 plus rung 5 already determine the 422).

## Step 9: Complete PRD — 2026-09-02T05:38:00.000Z

Done. `PRD_COMPLETED.md` is complete.

## Deltas

| | PRD_FINALIZED.md | PRD_COMPLETED.md | delta |
|---|---|---|---|
| lines | 510 | 512 | +2 |
| bytes | 90,356 | 104,726 | +14,370 |
| characters | 89,922 | 104,210 | +14,288 |

Only two lines were added (a single new lead-in paragraph before the §5 table). Every other change is an in-paragraph insert or revision; no section was added.

## Counts
- **ambiguity-pins: 35**
- **mismatch-revisions: 5**
- total change sites: 40 (39 revised lines + 1 inserted paragraph)

## Changes

- §2.1 — insert — ambiguity — an empty-string `X-User-ID` or `X-User-Role` counts as absent → `ERR_MISSING_AUTH_HEADERS` — `implementation/auth.py:21`
- §2.2 (`api_request_id` bullet) — revise — ambiguity — pinned `req_` + exactly 20 chars drawn from uppercase letters and digits — `implementation/response.py:13`
- §2.2 (`api_request_timestamp` bullet) — insert — ambiguity — read from the logical clock, never wall time — `implementation/response.py:17`
- §2.2 (`data` bullet) — insert — ambiguity — every `note`/`reason`/`rationale` is shape-validated but never persisted (`narrative` excepted); unrecognised body keys ignored — `implementation/validate.py:12`, `implementation/routes/entries.py:197`
- §2.2 (pagination bullet) — insert — ambiguity — the delinquency run is the one non-listing `array` payload and carries no pagination fields; the clock write returns `data` `{}` — `implementation/response.py:40`, `implementation/routes/members.py:26`
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST`; empty query value treated as absent — `implementation/response.py:51`
- §2.3 — insert — ambiguity — `created_at` ties broken by server write sequence — `implementation/db.py:99`
- §2.3 — insert — ambiguity — filter semantics: string-form comparison, empty value absent, boolean `true`/`false` only, null never matches, `athlete_member_ids` is containment — `implementation/response.py:90`
- §2.4 — insert — ambiguity — `version` increments at most once per row per request, and a new row is already counted as touched — `implementation/db.py:68`
- §2.5 — insert — ambiguity — client datetimes echoed back byte for byte; only the seven server-stamped instants are canonicalised — `implementation/db.py:83`
- §2.6 — insert — ambiguity — every client-supplied 1dp figure is rounded half up to 1dp on receipt — `implementation/validate.py:85`
- §2.8 — insert — ambiguity — protest body-FK order `heat_id` → `filed_by_member_id` → `against_race_lane_id`; a non-string FK is not resolved and falls to rung 5 — `implementation/routes/jury.py:30`, `implementation/helpers.py:50`
- §2.9 rung 8 — insert — ambiguity — the terminal guard also covers named parent resources (report/session/entry/heat/load creation, rack assignment, weigh-in), with carve-outs: submit guards only the entry, rack release only the load, protest filing nothing — `implementation/helpers.py:55`, `implementation/routes/trailers.py:97`
- §2.9 rung 22 — insert — ambiguity — consolidated the full `ERR_INVALID_STATUS_TRANSITION` catch-all set and pinned that on those endpoints it is evaluated last — `implementation/helpers.py:63`
- §3.1 — insert — ambiguity — certification PATCH is partial (omitted keys untouched, empty payload accepted); it recomputes seats and can demote a `SUBMITTED` entry in-call — `implementation/routes/members.py:86`
- §3.2 Payments — insert — ambiguity — `amount_cents` must be >= 1, rejected at rung 5 before either money check — `implementation/routes/dues.py:69`
- §3.2 Payments — insert — ambiguity — the settling-to-zero routine runs after payment, true-up and void; re-runs the full gate ladder rather than forcing `ELIGIBLE`; never promotes a demoted entry — `implementation/cascade.py:213`
- §3.2 True-up — insert — ambiguity — payable check, then `ERR_TRUEUP_ALREADY_APPLIED`, then the `PARTIALLY_PAID` requirement — `implementation/routes/dues.py:94`
- §3.2 Voiding — insert — ambiguity — `ERR_INVOICE_HAS_PAYMENTS` is decided before the `ISSUED` requirement — `implementation/routes/dues.py:126`
- §3.2 Delinquency — insert — ambiguity — hop three fires for every freshly delinquent member regardless of whether they moved to `DUES_HOLD`; response is a bare array of flagged invoices — `implementation/routes/dues.py:151`
- §3.3 Retire — insert — ambiguity — `RETIRED` hull → `ERR_ALREADY_TERMINAL`; any other non-`AVAILABLE` status or a live holder → `ERR_INVALID_STATUS_TRANSITION` — `implementation/routes/fleet.py:85`
- §3.3 Filing — insert — ambiguity — filing always mutates the hull row, and a hull already `DAMAGED` or `IN_REPAIR` keeps its status — `implementation/routes/fleet.py:111`
- §3.3 Schedule repair — insert — ambiguity — a non-`DAMAGED` hull keeps its status; the window fields carry no ordering constraint — `implementation/routes/fleet.py:212`
- §3.3 Verify repair — insert — ambiguity — the hull moves only `IN_REPAIR → AVAILABLE`; any other status is left alone — `implementation/routes/fleet.py:255`
- §3.3 Condemnation — revise — **mismatch** — the hull is driven to `RETIRED` from whatever status it holds, not only from `DAMAGED`/`IN_REPAIR`, and the cascade's refunds are pinned — `implementation/cascade.py:181`
- §3.4 Booking — insert — ambiguity — the hull tier gate covers only `coxswain_member_id` and `athlete_member_ids`; hull status never bars a booking except `RETIRED` — `implementation/routes/water.py:98`
- §3.4 Clearance — insert — ambiguity — the session's own `PLANNED` requirement is checked last, so re-clearing a `CLEARED`/`LAUNCHED` session surfaces as `ERR_SHELL_NOT_AVAILABLE` — `implementation/routes/water.py:168`
- §3.5 Lifecycle — revise + insert — **mismatch** — `COMPLETE` does not snapshot `net_fee_cents`/`deposit_held_cents` (both stay derived); cancellation keeps rack placements and does not demote the heats whose lanes it voids — `implementation/routes/regattas.py:113`, `implementation/cascade.py:163`
- §3.5 Lineup — insert — ambiguity — `ERR_SEAT_COUNT_MISMATCH` also covers coxswain-shape violations at a correct count; `seat_number` is otherwise unpoliced (duplicates and gaps accepted) — `implementation/routes/entries.py:148`
- §3.5 Lineup — insert — ambiguity — superseded seat rows are deleted outright (old ids → `ERR_SEAT_NOT_FOUND`); the response is the entry at HTTP 200 — `implementation/routes/entries.py:170`
- §3.6 Weigh-in — revise — **mismatch** — the endpoint is not fenced to coxswain seats or to a `PENDING` `weigh_in_status`: a `ROWER` seat records `deadweight_kg` `0.0` and is judged (typically `PASSED`), and a settled seat may be re-weighed — `implementation/routes/entries.py:317`, `implementation/derive.py:302`
- §3.7 Opening a load — revise — **mismatch** — `venue_kind` is never inspected, so a load may be opened against a `HOME` regatta; the only requirement is a non-terminal regatta — `implementation/routes/trailers.py:39`
- §3.7 Rack units — insert — ambiguity — `ERR_TRAILER_REGATTA_MISMATCH` applies to releases as well as assignments; both operations answer with the trailer load — `implementation/routes/trailers.py:135`
- §3.7 Placement — insert — ambiguity — occupancy counts only *other* `SUBMITTED`/`CONFIRMED`/`RACED` entries with non-null placement, so `DRAFT`/`LINEUP_DECLARED`/`SCRATCHED` racked entries obstruct nothing and the entry being placed is excluded from its own occupancy — `implementation/derive.py:394`
- §3.8 Results — insert — ambiguity — `lane_id` and `id` are exact synonyms for `race_lane_id`, consulted in that order, and `lane_number` is read only when none carries a value — `implementation/routes/race.py:216`
- §3.8 Advancement — insert — ambiguity — `advanced` is monotone; a crew dropped by a later re-run keeps the flag and its existing `PENDING` target lane — `implementation/routes/race.py:88`
- §3.9 Opening review — insert — ambiguity — the conflict-of-interest seat check disregards `VOIDED` lanes — `implementation/routes/jury.py:105`
- §3.9 Ruling — insert — ambiguity — `remedy` is required only on `UPHELD`; on `REMAND`/`DENIED` it may be omitted, null, or a valid value that is ignored, but an out-of-enum value is still `ERR_INVALID_REQUEST` — `implementation/routes/jury.py:137`
- §3.9 Ruling (UPHELD bullet) — insert — ambiguity — a `DISQUALIFY` naming a lane that is not `PROVISIONAL` is a silent no-op on the lane while the ruling still lands — `implementation/routes/jury.py:166`
- §5 — insert — **mismatch** — requests that never reach the domain (unrouted path, unsupported method) answer `ERR_INVALID_REQUEST` with the framework's 404/405, not the tabulated 422 — `implementation/app.py:34`

Note: the subagent reported that `test_helpers/` and `test_suite/` "do not exist in this workspace" — they live at the task root, not under `workspace/`, so it worked from the implementation as sole authority, which is the intended alignment target anyway. The PRD's three worked arithmetic examples (dues 27584; true-up 36500/8916; condition indices 90/94) were verified against the implementation and all match, so none needed revision.

## Pipeline complete — 2026-09-02T05:40:00.000Z

All nine steps done. Final artifacts: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `worklog.md`, `test_helpers/` (9 files), `test_suite/` (17 files, 152 tests collecting), `workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}`.
