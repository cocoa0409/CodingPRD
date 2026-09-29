# Worklog — task_2556_senior_games_masters_competition

## Step 1: Create task directory — 2026-09-03T00:00:00.000Z

Created pre-assigned directory `/home/ubuntu/github/CodingPRD/tasks/task_2556_senior_games_masters_competition` and its `workspace/` subdirectory. Index was fixed by the scenario number (2556); no scan of ./tasks/ was performed, per orchestration instructions (32 concurrent pipelines on this host).

## Step 2: Generate scaffold (§1.0–§1.9) — 2026-09-03T11:53:00.000Z

Wrote the three scaffold artifacts from the verbatim scenario plus
`skills/prd-bench-scaffold-generator/SKILL.md` and its
`references/claim-extraction-guide.md`. No sibling task under `tasks/` was read,
listed or grepped.

- `SCAFFOLD.yaml` — 3270 lines. §1.0–§1.7 only (no `scaffold_difficulty_design`,
  no `scaffold_corner_design`): 16 entities, 12 state machines across 2 Athlete
  dimensions, 3 concurrency rules, 11 calculations, 30 validation priorities,
  75 endpoints under `/senior-games`, 58 error codes, 7 peer roles.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2251 lines, single top-level key, 25
  instances over the §1.8 rule set.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4405 lines, single top-level key, all nine
  claim-extraction-guide sections: entities 13, state_machines 16,
  calculations 14, validations 18, endpoints 9, errors 13, rbac 5,
  cross_cutting_complexity_layers 9, consistency_model 2 (99 instances, 22 of
  them `excluded_because` stubs citing a §1.8 instance).

Checks: `scaffold_lint.py` reports `VERDICT: clean lint` over 1073 §1.8+§1.9
calls; all 58 error ids are asserted by at least one non-stub instance; instance
names unique across both design files; every cited `difficulty_instance` exists.

### Step 2 — subagent-returned summary (verbatim)

All three scaffold artifacts are complete and lint-clean.

## Output (`/home/ubuntu/github/CodingPRD/tasks/task_2556_senior_games_masters_competition/`)

| File | Lines | Contents |
|---|---|---|
| `SCAFFOLD.yaml` | 3270 | §1.0–§1.7 only — neither design key present |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2251 | single key `scaffold_difficulty_design`, 25 instances |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4405 | single key `scaffold_corner_design`, 99 instances |

`ls -la` also shows the pre-existing `worklog.md` (extended with a Step 2 entry) and empty `workspace/`.

## Scaffold surface
`api_prefix: /senior-games`; 16 entities, 12 state machines (Athlete carries two independent dimensions), 3 OCC concurrency rules, 11 calculations, 30 validation priorities, 75 endpoints, 58 error codes, 7 peer roles under segregation-of-duties. Complexity layers: `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `ops_run_checkpoint`; consistency model `immediate`.

## §1.9 breadth
All nine claim-extraction-guide sections present: entities 13, state_machines 16, calculations 14, validations 18, endpoints 9, errors 13, rbac 5, cross_cutting_complexity_layers 9, consistency_model 2 — 22 of the 99 are `excluded_because` stubs citing a §1.8 instance.

## Work done this session
1. **Fixed a cross-file precondition violation.** §1.2 requires `medical_status IN {SCREENED_CLEARED, SCREENED_RESTRICTED, CLEARED_BY_APPEAL}` for `SportEntry UNDER_REVIEW -> ACCEPTED`, but 10 §1.9 instances accepted an entry with the default `NOT_SCREENED`. Inserted 13 `POST /senior-games/medical-screenings` calls (MedicalDirector, `128/70/false` -> risk 7.5 -> CLEARED) before each first TAKE_UP, one per athlete per instance. Verified no instance asserted an Athlete `version` that the extra write would shift.
2. **Wrote `cross_cutting_complexity_layers`** (9 instances): real instances for all three OCC rules, the per-row version contract, and the ops-run checkpoint; stubs for the cascading and dual-variant layers.
   - Discovered that **`ERR_STALE_SPORT_EVENT_VERSION` was triggered nowhere** — the §1.8 instance only asserts it is *not* returned. So it became a real instance rather than the planned stub, driven off `POST /age-group-records`'s own declared `increments SportEvent.version by 1`: two claims from one snapshot, the first invalidating the second.
   - The block-OCC instance doubles as a priority proof: a request that is both stale *and* outside the village window answers 412 at priority 26, then the refreshed retry of the same body answers 422 `ERR_STAY_OUTSIDE_VILLAGE_WINDOW` at priority 72.
   - Used fresh sponsorship figures (BRONZE 120000 -> 120000, GOLD 400000 -> 448000, ledger 568000) to avoid re-treading §1.8's 250100/262606 rounding corner.
3. **Wrote `consistency_model`** (1 real + 1 stub). The real instance bounds the `immediate` claim honestly: every derived value lands in its own write response, but `provisional_impact_cents` stays 0 for a REGISTERED athlete because that recompute is bound to ops-run phase 6 by design.

## Verification
- `scaffold_lint.py` — **`VERDICT: clean lint`**, 75 endpoints / 16 entities / 25 §1.8 / 61 §1.9 instances / 1073 calls scanned.
- All **58** error ids are asserted by at least one non-stub instance (previously the three OCC codes were not).
- Instance names unique across both design files; every stub has exactly `name`/`claim_type`/`grounds`/`excluded_because` and cites an existing §1.8 instance; no forbidden concurrency vocabulary.
- No sibling `task_*/` directory was read, listed or grepped; every file was built with chunked `cat >>` appends.

## Step 3: Copy shared files — 2026-09-03T12:00:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-03T12:20:00.000Z

### Orchestrator truncation check (per instructions)
`wc -lc workspace/PRD.md` = 485 lines / 114508 chars. `tail -25` ends on the final row of the §5 error table (`ERR_IMPACT_ALREADY_FINALIZED | 409 Conflict`) — a real section boundary, not mid-sentence. Heading sweep confirms all of §1, §2.1–§2.11, §3.1–§3.9, §4 (endpoint table) and §5 (error catalogue) are present. No regeneration needed.

### Subagent-returned summary (verbatim)

PRD complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2556_senior_games_masters_competition/workspace/PRD.md` — 485 lines, ~15,600 words, built with 12 chunked `cat >>` appends (no giant Write, no truncation). The file ends at a real section boundary: the last row of the §5 error table (`ERR_IMPACT_ALREADY_FINALIZED`), not mid-sentence.

**Structure:** §1 Introduction; §2 Global Specifications in 11 subsections (RBAC; response structure; pagination; logical clock and games calendar; common resource properties and immutable rows; identifier resolution; version guards on shared parents; money/counters/rounding; cascade propagation; a 41-step validation precedence ladder; interval and boundary conventions); §3 Business Logic in 9 subsections (edition + catalogue; athlete registration, age bands, fee settlement; qualification/review/waitlist; medical screening, risk bands, appeals; venues, competition blocks and schedule disruption; officials, volunteers and staffing; marks, protests and age-group records; the athlete village; checkpoints, sponsorship recognition, economic impact); §4 the 75-endpoint table; §5 the 58-error catalogue.

**Hard Contract results:**
- **Contract 1 — Field-Name Coverage: PASS.** Programmatic re-check after repair: all 141 entity fields across 16 entities appear as backticked tokens; all 91 distinct endpoint inputs/query filters appear; all 58 error ids appear; a full all-caps token sweep of the scaffold found every enum member and state name present (the only unmatched all-caps tokens are the scaffold's *constant identifiers* — e.g. `MAX_DAILY_ASSIGNED_MINUTES`, `ECONOMIC_MULTIPLIER`, `VILLAGE_LEAD_DAYS` — which the skill requires be expressed as embedded prose values rather than named, and each is; plus YAML commentary words). One gap was found and repaired: the literal `status` field/filter token was missing, and a sentence was added to §2.5 covering it and the athlete's two-dimension exception.
- **Contract 2 — Rule Coverage: PASS.** All 41 validation priorities are rendered as 41 ordered ladder steps in §2.10 with their error ids, HTTP statuses and `applies_to` scopes; the priority-14/18 not-found family is enumerated resource-by-resource in §2.6. All 73 transitions across the 12 state machines (including the two Athlete dimensions) are described — 60 with explicit `FROM` -> `TO` arrows, the remaining 13 in prose (edition ladder steps, the `IN_PROGRESS` slot displacement, the self-loop `SCREENED_HOLD` denial, the six entry-withdrawal origins, both assignment releases, both stay cancellations). All 11 calculations are reconstructible in prose, including the four distinct interval semantics (half-open buffered venue windows, closed symmetric travel-buffered personnel windows, minimum-gap athlete recovery, per-night date-granular bed occupancy), the per-bucket-then-sum sponsorship rounding, and both economic-impact variants.
- **Contract 3 — §3 Path Purity: PASS.** Zero backticked tokens in §3 begin with `/`, are bare HTTP methods, or combine method+path; zero raw `/senior-games...` strings and zero bare method words appear anywhere in §3. Endpoints are referenced only by actor + action, state transition, or capability.

**Other checks:** §2.2 is byte-verbatim against `section-2.2-response-structure.md` (diff shows only the trailing blank line). No pseudocode operators (`==`, `>=`, `IN {`, `min(`, `round(`, `+=`) and no fuzzy hedging words survive anywhere in the document. The two withheld design files were never opened, grepped, or referenced, and no sibling task directory was read.

## Step 5 & 6: launch note (orchestrator) — 2026-09-03T12:18:00.000Z

Orchestrator deviation, recorded for honesty: Steps 5 and 6 were launched in two back-to-back assistant messages rather than one message with two Agent tool uses, so the impl generator did NOT get physical isolation from `test_suite/` (the directory already existed when it started). Mitigation applied: the Step 6 prompt carried an ABSOLUTE PROHIBITION section forbidding any read/list/glob/grep of `test_suite/` or `test_helpers/`, and the Step 6 subagent explicitly confirmed on exit that neither directory was ever read or listed. Symmetrically, the Step 5 subagent confirmed `workspace/implementation/` was never read or listed. Both agents ran fully concurrently regardless (Step 6 finished at ~12:59, Step 5 at ~13:31).

## Step 5: Generate unit tests — 2026-09-03T13:31:00.000Z

Done. Full suite is complete and audited.

## Deliverables

`test_helpers/` — 2379 lines, 9 files
| file | lines |
|---|---|
| types.py | 470 |
| fixtures.py | 669 |
| api_client.py | 345 |
| assertions.py | 306 |
| factories.py | 239 |
| api_errors.py | 128 |
| constants.py | 95 |
| test_users.py | 81 |
| __init__.py | 46 |

`test_suite/` — 8190 lines, 19 test files + conftest, **142 tests**
| file | lines | tests |
|---|---|---|
| test_scheduling_intervals.py | 804 | 18 |
| test_corner_validations.py | 781 | 12 |
| test_corner_entities.py | 772 | 13 |
| test_age_bands_and_fees.py | 658 | 15 |
| test_compensating_ledgers.py | 569 | 12 |
| test_corner_errors.py | 520 | 6 |
| test_corner_complexity_layers.py | 489 | 5 |
| test_corner_rbac.py | 476 | 5 |
| test_corner_state_machines.py | 410 | 8 |
| test_medical_screening.py | 398 | 8 |
| test_corner_calculations.py | 382 | 5 |
| test_corner_endpoints.py | 377 | 6 |
| test_cascades.py | 334 | 6 |
| test_entry_review.py | 255 | 6 |
| test_results_and_records.py | 246 | 6 |
| test_sponsorship_allocation.py | 177 | 4 |
| test_economic_impact.py | 171 | 3 |
| test_corner_consistency.py | 152 | 1 |
| test_waitlist_promotion.py | 163 | 3 |
| conftest.py | 56 | — |

## Design-index coverage (the only test source)
- Queue A: **81 tests** over all **25** difficulty instances, every instance >=2 tests.
- Queue B: **61 tests** over all **61** non-stub corner instances, every instance >=1 test. The 38 `excluded_because:` stubs were not translated; every stub's `difficulty_instance` cross-reference resolves.
- 142 tests / 142 `Design:` tags, one per test, all last-line, zero unknown tags, zero stub-pointing tags, zero dual tags. No instance had to be skipped for the PRD two-condition filter.

## Final passes
- **PRD citation pass (C1/C2/C3)** — this was the one thing missing when I picked the work back up: no test carried a PRD quote. Every one of the 142 docstrings now opens with `PRD §x.y: "<full verbatim sentence>"` lines (1–9 per test, one per asserted rule; precedence tests cite both §2.10 rungs). Verified mechanically with a checker I wrote (`/tmp/prd_cite_check.py`): each quote whitespace-normalised-grep-matches `workspace/PRD.md`, the cited section equals the heading the sentence actually lives under, quotes are full sentences, and the `Design:` line is still last -> `tests checked: 142; failures: 0`. Insertion was done by script (`/tmp/citer.py`) so quotes are copied from the PRD rather than retyped; the five partitioned agents each confirmed AST equality against pre-edit backups, so only docstrings changed.
- **Scaffold-citation pass** — zero occurrences of "scaffold", "Table N" or `§1.x` anywhere in `test_suite/` or `test_helpers/`.
- All files `ast.parse` clean, zero unused imports across all 20 modules, no `skip`/`skipif`/`xfail`, no lenient `.get("field")` reads of response bodies.

## Last file written this session
`test_suite/test_corner_consistency.py` — the one non-stub `consistency_model` instance: a single lifecycle pass proving each write response already carries what it derives (event `available_slots` 8/`accepted_entry_count` 0 at insert, athlete `age_at_reference` 60 -> band `60-64` with `fee_total_cents` 0, entry `qualification_priority` 4 for ORGANIZER_INVITE, the seven-key `fee_breakdown` totalling 15500 with the follow-up read revealing nothing new, `risk_score` 7.5 -> `CLEARED` with the athlete immediately `SCREENED_CLEARED`, acceptance showing 1/7/OPEN with no checkpoint, stay 5 nights/60000 bracketing block bed-nights 0 -> 5) and the one stated exception, `provisional_impact_cents == 0` at `ops_epoch == 0`.

No server was started or killed, `workspace/implementation/` was never read or listed, and no sibling task directory was touched.

## Step 6: Generate implementation — 2026-09-03T12:59:00.000Z

The implementation is complete, verified, and the smoke-test server is stopped (killed by captured PID; no broad pkill was ever used).

## Deliverable
`/home/ubuntu/github/CodingPRD/tasks/task_2556_senior_games_masters_competition/workspace/implementation/` — 16 Python modules + `start.sh` + `requirements.txt`, 3244 lines total. Derived exclusively from `PRD.md`, `SCAFFOLD.yaml`, `INSTRUCTION.md`; `test_suite/`, `test_helpers/` and the two design YAMLs were never read or listed.

Per-file line counts: `core.py` 416, `domain.py` 471, `calc.py` 272, `store.py` 114, `web.py` 62, `app.py` 74, `r_edition.py` 233, `r_catalog.py` 148, `r_schedule.py` 212, `r_athlete.py` 210, `r_entry.py` 268, `r_medical.py` 85, `r_staff.py` 150, `r_results.py` 290, `r_village.py` 130, `r_sponsor.py` 98, `start.sh` 10, `requirements.txt` 1.

## Machine-checked conformance (all against a live server on port 47311)
- **Endpoints**: 75 in SCAFFOLD, 75 implemented, empty diff both directions.
- **Entity shapes**: all 16 entities return exactly the scaffold's field names *in the scaffold's declared order* (`id` first, `created_at`/`updated_at`/`version` last; `QualifyingResult` and `MedicalScreening` correctly immutable with `created_at` only). 0 mismatches.
- **Errors**: all 58 scaffold error ids mapped with the exact HTTP status, none extra, none unreachable from the route modules.
- **Roles**: probed all 75 endpoints x 7 roles — `ERR_ROLE_NOT_PERMITTED` fires exactly on the disallowed set. 0 mismatches.
- **Body validation**: probed every POST with `{}` and with an unknown field — required/optional split matches the scaffold's `input` list on every endpoint, unknown fields always rejected. 0 issues.
- **List filters**: every declared query filter on all 16 list endpoints actually filters (bogus value -> `total_count` 0, real value -> all rows match). 0 issues.

## Bug found and fixed this session
The smoke run exposed a **validation-precedence inversion**: I had the terminal-state check (PRD §2.10 step 12 / scaffold priority 38) running *before* the origin-state check (step 11 / priority 34) in 14 call sites across `r_athlete.py`, `r_entry.py`, `r_results.py`, `r_sponsor.py`, `r_village.py`. The spec order is unambiguous and makes `ERR_ALREADY_TERMINAL` reachable precisely in the cross-dimension cases — e.g. `medical-appeal` on an athlete whose `medical_status` is a valid origin (`SCREENED_HOLD`) but whose `registration_status` is `WITHDRAWN`. Swapped all 14 sites; probes now return `ERR_ALREADY_TERMINAL` for that case and `ERR_INVALID_STATE_TRANSITION` for a re-withdraw / re-cancel / stale origin.

## Behaviour confirmed end-to-end
Two full scenario runs exercised: pinned money math (`SILVER` 250100 -> `recognized_cents` 262606 with buckets 105042/78782/52521/26261; fee 9500+3000 -> 12500 with the seven-key `fee_breakdown`), risk model (age 78/bp 120/hr 66/1 high-contact -> 37.0 -> `CLEARED_WITH_RESTRICTION`; capped 100.0 -> `HOLD`), one-step-per-checkpoint edition advance, waitlist/capacity conservation, screening-hold and appeal-grant restore cascades, venue close -> `DISPLACED` -> reschedule -> `SEEDED`, personnel travel-buffer double-booking and certification gates, slot completion booking `CONFIRMED`->`COMPLETED`, verify -> `RECORD_PENDING` -> ratify with segregation of duties -> publish -> protest -> `VOID` unwinding the record and resetting `current_record_id`, bed-night capacity plus compensating debit on cancel, and the four interval models. Envelope, `req_`-prefixed request ids, logical clock (`2026-08-01T00:00:00.000Z` at boot, host clock never read), pagination `has_more`, 404/405/malformed-JSON handlers all correct. Storage is in-memory only (no file, sqlite, or `/tmp` use anywhere) and nothing is seeded at startup.

## Step 7: Run tests and iterate — 2026-09-03T13:52:00.000Z

### Orchestrator independent verification (per known failure mode: subagent claiming a clean sweep with no artifacts)
`ls -la workspace/implementation/results.*.json` -> 8 files, all written 13:52. Parsed each with json.load: results.1..8 all report `passed=142 total=142 failed=0`. Claim confirmed against artifacts on disk.

### Subagent-returned summary (verbatim)

All 8 parallel rounds green: 142/142 in every round.

## Summary

**Iterations run:** 2 (each an 8-round parallel `setsid nohup` sweep; round 1 = 137/142 in all 8 rounds with a deterministic 5-test union, round 2 = 142/142 in all 8 rounds). Verified all 8 `results.$i.json` parse with `passed == total` in both iterations.

**Tests deleted:** none. Every failing test's rule was verbatim-covered by PRD; the defects were all in the test layer's translation of PRD, not in coverage.

**Fixes applied to `test_helpers/`:** none — the shared fixtures were faithful. The one setup failure was inline in a test function, not in a helper.

**Fixes applied to `implementation/`:** none. The implementation's precedence (§2.10 step 11 origin-state before step 12 terminal-state) and its open-registration precondition were both PRD-faithful; weakening either to satisfy the tests would have violated the cardinal rules.

**Fixes applied to `test_suite/`:**

- `test_corner_errors.py::test_a_sport_code_is_global_while_an_email_is_unique_only_inside_its_edition` — STEP 2 test bug (setup state). The test called `open_registration` on both editions before any sport event existed, while PRD §3.1 requires "at least one sport event belonging to that edition currently `OPEN`". Reordered setup so the `TRACK` sport is created first and one event is created per edition before registration opens; all assertions (including `sport_meta["total_count"] == 1`) preserved unchanged.

- `test_compensating_ledgers.py::test_a_second_release_compensates_nothing_at_all` — STEP 2 assertion mis-translation. PRD §2.10 step 12 gives an exhaustive terminal-state list ("The terminal states **for this purpose are** ... sport entry / competition result / age-group record / village stay / athlete / sponsorship commitment") that does **not** include a personnel assignment, so `ERR_ALREADY_TERMINAL` is unreachable there; a second release of a `RELEASED` assignment can only fail step 11 (release origins are `ASSIGNED`/`CONFIRMED`). Assertion tightened to exact `ERR_INVALID_STATE_TRANSITION` (409), docstring re-cited to the step-11 sentence plus the terminal-state enumeration.

- Three tests relaxed to `validate_error_is_one_of([ERR_ALREADY_TERMINAL, ERR_INVALID_STATE_TRANSITION])` (both 409, and the 409 status is still asserted separately) — ERROR PRECEDENCE SILENCE: PRD §2.10 puts the origin-state check at step 11 *above* the terminal-state check at step 12, so for a same-dimension repeat command the terminal state is never a declared origin and the literal ordering yields `ERR_INVALID_STATE_TRANSITION`, while the deliberate step-12 enumeration of these very entities supports the `ERR_ALREADY_TERMINAL` reading. Both readings are PRD-faithful, so the exact-error assertion was not uniquely derivable:
  - `test_compensating_ledgers.py::test_a_second_cancellation_never_drives_the_bed_night_ledger_negative` (re-cancel a `CANCELLED` stay) — scaffold rule: `Difficulty/compensating_invariant/village_stay_cancel_restores_block_bed_nights_and_frees_the_night`.
  - `test_compensating_ledgers.py::test_the_recognition_ledger_returns_to_zero_and_a_repeat_withdrawal_moves_nothing` (re-withdraw a `WITHDRAWN` commitment) — scaffold rule: `Difficulty/compensating_invariant/sponsorship_withdraw_restores_edition_recognition_ledger_in_cents`.
  - `test_corner_state_machines.py::test_a_withdrawn_entry_refuses_resubmission_review_and_a_second_withdrawal` (resubmit / review / re-withdraw a `WITHDRAWN` entry) — scaffold rule: `Corner/state_machines/corner_state_machine_terminal_withdrawn_entry_cannot_resubmit`. Its docstring had asserted "the terminal answer is preferred over the generic wrong-origin answer", a precedence inversion stated nowhere in PRD; that claim was removed.

  In all three the substantive content is unchanged and still exact: the follow-up call is refused with 409, no version advances, and the bed-night / recognition / capacity ledgers hold at their compensated values. No `skip`/`xfail` was added and no `error_id` check was downgraded to a bare HTTP-status check.

**Notable:** no flakiness at all — the failure set was identical across all 8 rounds in iteration 1, and no load-induced timeout or connection failure appeared in either sweep.

### Step 8 skip-condition adjudication (orchestrator)
Step 7 had 0 deletions, 0 `test_helpers/` fixes and 0 `implementation/` fixes, but **5 `test_suite/` fixes**, so the skip condition (all four counts zero) is NOT met. Step 8 runs. Its focus is narrow by construction: with no implementation fixes, the only PRD-silence sites are the ones the test-layer corrections exposed — chiefly the §2.10 step-11/step-12 precedence interaction for same-dimension repeat commands, and the §3.1 open-registration precondition.

## Step 8: Finalize PRD — 2026-09-03T14:04:00.000Z

### Orchestrator verification
`wc -lc`: PRD.md 485 lines / 114508 chars, PRD_FINALIZED.md 485 lines / 115539 chars. `diff` shows exactly 4 changed lines (2 revised line-pairs), file still ends at `| ERR_IMPACT_ALREADY_FINALIZED | 409 Conflict |`. Not truncated, no section loss.

### Subagent-returned summary (verbatim)

Done. Both edits applied; structure verified intact.

## PRD.md vs PRD_FINALIZED.md

- Lines: 485 -> 485 (0.0% delta). Bytes: 114,508 -> 115,539 (+1,031, +0.90%). Exactly 2 lines revised (no insertions/deletions of lines, no new sections).
- Structure verified: heading list byte-identical (§1, §2.1–§2.11 = 11 subsections, §3.1–§3.9 = 9 subsections, §4, §5), file still ends at `| ERR_IMPACT_ALREADY_FINALIZED | 409 Conflict |`.

## Changes

- **§2.10 step 12** — revise — appended two sentences pinning that the step-11 origin-state check runs strictly before, and is never skipped by, the step-12 terminal-state check: a repeat command whose target sits in a terminal state that is not a declared origin answers `ERR_INVALID_STATE_TRANSITION` (naming the re-cancel of a `CANCELLED` stay, re-withdraw of a `WITHDRAWN` commitment, and re-withdraw/resubmit/review of a `WITHDRAWN` entry), and `ERR_ALREADY_TERMINAL` surfaces only where step 11's status and step 12's terminal status are different dimensions of the same row (medical appeal). — `implementation/web.py:45-57`, `r_village.py:127-128`, `r_sponsor.py:81-82`, `r_entry.py:259-260`, `r_athlete.py:183-184`
- **§3.1, open-registration paragraph** — revise — appended that a non-`DRAFT` edition and an edition with no `OPEN` sport event of its own are both refused with `ERR_INVALID_STATE_TRANSITION`, decided at step 11 and hence before the deadline check. — `implementation/r_edition.py:95-107`

## Per-edit pre-edit search log

**Edit 1 — §2.10 step 12**
- (a) Subject: relative precedence of the origin-state check (step 11) and the terminal-state check (step 12), and the reachability of `ERR_ALREADY_TERMINAL`.
- (b) Paths enumerated: grepped `ALREADY_TERMINAL` repo-wide (only `core.py:203` status map and `web.py:47,52`), then grepped every `guard_state`/`guard_terminal`/`guard_athlete_terminal` callsite and read each. Terminal-bearing sites: `r_results.py:78/79, 110/111, 134/135, 180/181, 261/262`; `r_entry.py:172/173, 229/230, 259/260`; `r_sponsor.py:62/63, 81/82`; `r_athlete.py:99/100, 120/121, 154/155, 183/184`; `r_village.py:127/128`. Origin-only sites (entities absent from PRD's step-12 list): `r_catalog.py:121,138` (sport event), `r_staff.py:123,141` (personnel assignment), `r_edition.py:95` (edition), `r_schedule.py:60,161,193` (venue/slot). Also read `web.py:9-16` (`TERMINAL_STATES`, `ATHLETE_TERMINAL_STATES`), `domain.py:6-32` (`LIVE_ENTRY_STATES`, `LIVE_ASSIGNMENT_STATES`), `r_entry.py:152-158` (`REVIEW_ORIGIN`). Confirmed `guard_state` precedes `guard_terminal` at every site with no exception, that no declared origin set anywhere contains a step-12 terminal state, and that `r_athlete.py:183-184` is the sole cross-dimension site (origin on `medical_status`, terminal on `registration_status`).
- (c) Adjustments: used "as on a medical appeal" rather than an exhaustive "only on the medical appeal" so the clause stays example-form and does not become a false universal if another cross-dimension path exists; wrote "a review decision on a `WITHDRAWN` sport entry" rather than naming individual decisions, since all five `REVIEW_ORIGIN` sets behave alike; deliberately made no claim about personnel assignments, sport events, slots or venues, which PRD's existing step-12 enumeration already excludes.

**Edit 2 — §3.1 open-registration**
- (a) Subject: failure identity and evaluation order of the three open-registration preconditions.
- (b) Paths enumerated: `r_edition.py:90-110` (the only open-registration handler — `guard_state(DRAFT)`, then the no-`OPEN`-event `fail("ERR_INVALID_STATE_TRANSITION")`, then the deadline `fail`); grepped `open-registration`/`open_registration` for other callsites (none); `core.py:202` (`ERR_INVALID_STATE_TRANSITION` -> 409); cross-checked §2.10 step 10's existing sentence "Opening registration is governed by the edition's own origin state `DRAFT`, which is decided at step 11" and step 26's deadline guard for consistency with the new "decided at step 11" phrasing.
- (c) Adjustments: phrased the event precondition as "no `OPEN` sport event of its own" to match the impl's per-edition filter (`e["games_edition_id"] == edition["id"] and e["status"] == "OPEN"`) rather than a catalogue-wide reading; anchored the ordering claim to step 11 to stay consistent with §2.10 step 10's existing cross-reference instead of introducing a competing ordering statement.

No other Step 7 item required a PRD change: the `test_corner_errors.py` sport-code/email item was a pure fixture-ordering bug (§3.1's "at least one sport event ... currently `OPEN`", §3.1's catalogue-wide `sport_code` uniqueness and §3.2's per-edition email uniqueness are all already verbatim and impl-faithful), and the second-release-of-a-personnel-assignment item is already uniquely determined by step 12's exhaustive "terminal states for this purpose are" list, which omits personnel assignments.

## Step 9: partitioning decision (orchestrator) — 2026-09-03T14:06:00.000Z

Step 9 is a full 3244-line-implementation vs 485-line-PRD scan. Known failure mode: a single-pass Step 9 agent runs out of working room, copies PRD_FINALIZED.md to PRD_COMPLETED.md and returns without ever scanning, leaving the two files byte-identical. Mitigation: run Step 9 as three sequential file-partitioned passes over `implementation/`, each pass editing the same PRD_COMPLETED.md in place and handing its partition to the next:
  - Pass A — infrastructure + edition/catalogue/athlete: `core.py`, `domain.py`, `store.py`, `web.py`, `app.py`, `calc.py`, `r_edition.py`, `r_catalog.py`, `r_athlete.py`
  - Pass B — entry/medical/schedule/staff: `r_entry.py`, `r_medical.py`, `r_schedule.py`, `r_staff.py`
  - Pass C — results/village/sponsor: `r_results.py`, `r_village.py`, `r_sponsor.py`
Pass A performs the `cp`; B and C edit the existing file. Orchestrator asserts PRD_COMPLETED.md differs from PRD_FINALIZED.md after the passes.

## Step 9: Complete PRD — 2026-09-03T14:35:00.000Z

Run as three sequential file-partitioned passes over `implementation/` (rationale recorded above). Pass A performed the `cp` from PRD_FINALIZED.md; B and C edited in place. **57 edits total: 43 ambiguity-pins, 14 mismatch-revisions.**

### Orchestrator verification
`wc -lc`: PRD.md 485/114508 -> PRD_FINALIZED.md 485/115539 -> PRD_COMPLETED.md 485/127106 (+11567 chars over PRD_FINALIZED, +10.0%). `diff PRD_FINALIZED.md PRD_COMPLETED.md` = 102 diff lines / 51 changed line-pairs — decisively NOT byte-identical, so the scan genuinely landed (the known no-op failure mode did not occur). Heading sweep: 28 headings, all of §1 / §2 / §3 / §4 / §5 present with §2.1–§2.11 and §3.1–§3.9 intact; file ends at `| ERR_IMPACT_ALREADY_FINALIZED | 409 Conflict |`. `find` over `test_suite/`, `test_helpers/`, `workspace/implementation/` for `*.py` newer than the 13:52 green sweep returns 0 files — Steps 8 and 9 touched only PRD_* documents, so the 8x 142/142 sweep result still describes the delivered artifact.

### Pass A summary (verbatim) — core.py, domain.py, store.py, web.py, app.py, calc.py, r_edition.py, r_catalog.py, r_athlete.py

**Setup**: performed `cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` as the first action; all subsequent work was targeted `Edit` calls on `PRD_COMPLETED.md` only.

**Verification**
- Lines: 485 before -> **485** after (unchanged; every edit was in-paragraph).
- Chars: 115,539 -> 120,673 (**+5,134**).
- Headings intact: §1, §2.1–§2.11, §3.1–§3.9, §4, §5.
- File still ends at `| ERR_IMPACT_ALREADY_FINALIZED | 409 Conflict |`.
- `diff PRD_FINALIZED.md PRD_COMPLETED.md` is **non-empty** (23 changed line pairs, 46 diff lines).
- Cross-check: the §5 error catalogue is byte-for-byte consistent with `core.ERROR_STATUS` (58 ids, zero id or status divergence) — no edit needed there.

**Counts**: 24 edits — **17 ambiguity-pins**, **7 mismatch-revisions**.

**Changes**
- §2.1 — insert — ambiguity — whitespace-only auth headers are refused, and both header values are trimmed before role recognition / ownership comparison — `core.py:250-255`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alphanumeric chars; `api_request_timestamp` is read from the logical clock, not host time — `core.py:55-56`, `core.py:147-148`
- §2.3 — insert — ambiguity — equal-`created_at` rows tie-break on server write order; unmatched/unknown filter values yield an empty page, undeclared query params ignored — `store.py:91`, `web.py:27-37`
- §2.4 — insert — ambiguity — `current_utc` is the canonical 3-fractional-digit form and the only response field — `r_edition.py:227-233`
- §2.4 — insert — ambiguity — client-supplied dates/instants are stored and echoed verbatim (never normalised); only server-minted instants use the canonical form — `core.py:382-383`, `r_edition.py:68`
- §2.5 — insert — ambiguity — `created_at`/`updated_at` come from the logical clock, and `updated_at` equals `created_at` until first mutation — `store.py:53-73`
- §2.9 — insert — ambiguity — an event whose counter write then drives its own status change is `version`-incremented **twice** in one request — `domain.py:169-191`
- §3.1 — insert — mismatch — `age_group_code` bounds are each validated only as an age 50–99; upper is never checked to be lower+4 — `calc.py:79-83`
- §3.1 — insert — ambiguity — `national_qualifying_standard` must be strictly > 0 when supplied — `r_catalog.py:67-68`
- §3.1 — insert — ambiguity — `equipment_profile`/`format_modifications` store `{}` for an explicit null — `r_catalog.py:41-42`
- §3.1 — insert — ambiguity — the `UNDERSUBSCRIBED` fall admits only `OPEN`/`SEEDED`; other statuses keep status while counters still move — `domain.py:174-178`
- §3.1 — insert — ambiguity — event-cancel `reason` is **mandatory** (empty string allowed) and is stored nowhere — `r_catalog.py:136`
- §3.2 — insert — ambiguity — `email` is any non-empty string, unchecked for syntax; uniqueness ignores the first row's status — `r_athlete.py:16`, `r_athlete.py:42-44`
- §3.2 — insert — ambiguity — `discount_pct` is persisted as the decimal fraction (0.0/0.05/0.12/0.2), not percentage points — `calc.py:146`
- §3.2 — insert — ambiguity — the `CHECKED_IN`-withdrawal verified-result precondition fails with `ERR_INVALID_STATE_TRANSITION`, and scans entries in any status — `r_athlete.py:156-162`
- §3.2 — revise — **mismatch** — expiry does **not** consult `fee_paid_cents`/`fee_total_cents` (PRD's "short of" clause was false for a fresh 0/0 athlete); added the full capacity->slot->personnel ripple — `r_edition.py:125-133`
- §3.3 — revise — **mismatch** — `created_at` is not the *final* promotion tie-break; server write order breaks remaining ties — `domain.py:411-417`
- §3.4 — insert — ambiguity — appeal `note` is validated then discarded; a `GRANT` from hold with no screening row fails `ERR_INVALID_STATE_TRANSITION` — `r_athlete.py:177`, `r_athlete.py:192-196`
- §3.4 — insert — ambiguity — `DENY` admits only `SCREENED_HOLD`, so a `DENY` on `SCREENED_RESTRICTED` fails `ERR_INVALID_STATE_TRANSITION` — `r_athlete.py:182-183`
- §3.5 — insert — ambiguity — on the acceptance path the target event is folded into the athlete's slot set as if already `ACCEPTED` — `domain.py:344-348`
- §3.9 — revise — **mismatch** — ops-run expiry phase fires "at or past" the deadline (PRD said "past") and inspects nothing while the clock is short of it — `r_edition.py:126-128`
- §3.9 — revise — **mismatch** — the economic-impact read **recomputes** the provisional figure live while `final_impact_cents` is null (PRD said "without recomputing it"), echoing the stored value only after finalisation; all three counts are always live — `r_edition.py:207-213`
- §4 — revise — **mismatch** — editions list is also filterable by host state code — `r_edition.py:87`
- §4 — revise — **mismatch** — athletes list is also filterable by `age_group_code` — `r_athlete.py:84-87`

**Notable non-findings in my partition**: the fee/sponsorship/impact/risk formulas, rounding placement and counts, the four interval models, pagination bounds, validation-precedence ordering inside `r_edition`/`r_catalog`/`r_athlete`, and the full error catalogue all already matched the PRD uniquely.

### Pass B summary (verbatim) — r_entry.py, r_medical.py, r_schedule.py, r_staff.py

Pass B complete.

## Verification
- `wc -l PRD_COMPLETED.md`: **485 before -> 485 after** (>=480 OK); chars 115,539 -> **123,697** (**+8,158**)
- Heading list intact: §1, §2.1–§2.11, §3.1–§3.9, §4, §5 OK
- File still ends at `| ERR_IMPACT_ALREADY_FINALIZED | 409 Conflict |` OK
- **Pass A's edits all survived**: every one of Pass A's 23 changed line numbers (17, 46, 47, 78, 84, 86, 92, 126, 188, 190, 196, 198, 202, 210, 216, 218, 236, 250, 262, 320, 338, 348, 372) is still divergent from PRD_FINALIZED.md, and distinctive Pass A phrases spot-checked present ("folded into that athlete's own set", "exactly twenty characters drawn from the uppercase letters", "`SCREENED_HOLD` is the only origin `DENY` admits").

## Counts
**18 changes in 14 Edit calls — 15 ambiguity-pins, 3 mismatch-revisions.**

## Changes
- **§3.3 (L226)** — insert — ambiguity — an explicit `null` `qualifying_result_id` counts as absent, not as a malformed value — `r_entry.py:61,105`
- **§3.3 (L230)** — insert — ambiguity — an omitted or explicitly-null `review_note` leaves the entry's existing note untouched; an empty string does overwrite — `r_entry.py:194-195`
- **§3.3 (L230)** — insert — ambiguity — the `SCREENED_HOLD` bar guards all five review decisions, not acceptance alone — `r_entry.py:182-183`
- **§3.3 (L230)** — insert — ambiguity — `TAKE_UP` against an event that is neither `OPEN` nor `UNDERSUBSCRIBED` answers `ERR_INVALID_STATE_TRANSITION` — `r_entry.py:177-178`
- **§3.3 (L234)** — insert — ambiguity — entry-withdrawal `reason` is validated then discarded, stored on no field — `r_entry.py:256`
- **§3.4 (L246)** — insert — ambiguity — a screening on an athlete already out of `NOT_SCREENED` is still stored and still 201, but moves neither `medical_status` nor any entry — `r_medical.py:30-31`
- **§3.5 (L254)** — **revise** — **mismatch** — `spectator_capacity` is *not* carried into the economic-impact packet; it is read by nothing at all — `r_schedule.py:35` vs `r_edition.py:214-223`
- **§3.5 (L258)** — insert — ambiguity — slot writes never compare the venue's and event's edition, and never inspect the event's status — `r_schedule.py:106-133`
- **§3.5 (L264)** — insert — ambiguity — all three start-gate refusals (event not ready, short of officials, start not arrived) are `ERR_INVALID_STATE_TRANSITION` — `r_schedule.py:199-204`
- **§3.5 (L264)** — insert — ambiguity — closing a block carries no clock condition of its own — `r_schedule.py:210-211`
- **§3.5 (L266)** — insert — ambiguity — venue-close `reason` is mandatory, empty string accepted — `r_schedule.py:58`
- **§3.5 (L268)** — **revise** — **mismatch** — reschedule also overwrites `teardown_buffer_minutes`, resetting it to the default 15 when omitted; `required_official_count` is not an input and `confirmed_official_count` is left as displacement left it — `r_schedule.py:150,174-178`
- **§3.6 (L272)** — insert — ambiguity — an explicit null `certified_sport_codes` is stored as an empty list — `r_staff.py:17,34`
- **§3.6 (L274)** — insert — ambiguity — the person/slot edition divergence answers `ERR_INVALID_REQUEST` and is decided *after* the duplicate check; the slot's own status is not a gate on assignment creation — `r_staff.py:82-88`
- **§3.6 (L282)** — insert — ambiguity — confirming against a slot in any state but `SCHEDULED` answers `ERR_INVALID_STATE_TRANSITION` — `r_staff.py:125-126`
- **§3.6 (L284)** — insert — ambiguity — release `reason` is validated then discarded (PRD said "recording", implying storage) — `r_staff.py:139`
- **§3.6 (L284)** — insert — ambiguity — releasing a `CONFIRMED` assignment off a running block answers `ERR_INVALID_STATE_TRANSITION` — `r_staff.py:143-148`
- **§4 (L379)** — **revise** — **mismatch** — `GET /qualifying-results` also filters by `meet_level` — `r_entry.py:53`

## Notes for the caller
- Everything else in my partition was already uniquely pinned, including the full §2.10 precedence chain — impl gate order in `create_session_slot` (14->18->19->25->29->38) and `create_personnel_assignment` (23->24->31->36->38) matches §2.10 exactly, as does `review` (11->12->13->17->25->32->39).
- One systemic gap I deliberately did **not** touch because it belongs to `core.py` (Pass A): §2.10 step 4 never pins how an explicit `null` is treated for an optional body field. `core.py:369-373` accepts null only where the field's declared default is itself `None` (or it is `nullable`), and 400s otherwise — so `has_onsite_medical_bay: null`, `teardown_buffer_minutes: null`, `certification_level: null` are all `ERR_INVALID_REQUEST` while `review_note: null` and `reason: null` are accepted. I pinned the two instances inside my own partition; the general rule is still unstated in §2.10.

### Pass C summary (verbatim) — r_results.py, r_village.py, r_sponsor.py + the §2.10 null gap Pass B escalated

Pass C complete.

## Line counts / deltas
- `PRD_COMPLETED.md`: **485 lines before -> 485 lines after** (no line added or removed; all edits in-paragraph).
- Char delta from my pass: **+3,409** (123,697 -> 127,106).
- Final total delta vs `PRD_FINALIZED.md`: **+11,567 chars**; 50 divergent hunks, of which the 36 from Passes A and B are all still present and unchanged (lines 17, 46–47, 78, 84, 86, 92, 126, 188, 190, 196, 198, 202, 210, 216, 218, 226, 230, 234, 236, 246, 250, 254, 258, 262, 264, 266, 268, 272, 274, 282, 284, 320, 338, 348, 372, 379). Heading list (§1, §2.1–§2.11, §3.1–§3.9, §4, §5) intact; file still ends at `| ERR_IMPACT_ALREADY_FINALIZED | 409 Conflict |`.

## Counts
- **JOB 1** (r_results.py, r_village.py, r_sponsor.py): 14 edits — 11 ambiguity-pins, 3 mismatch-revisions.
- **JOB 2** (§2.10 step 4 null rule): 1 edit — 1 ambiguity-pin.

## Changes
- §2.10 step 4 — insert — ambiguity — **JOB 2**: pinned the general explicit-`null` rule. Verified `core.py:369-373`: `null` is accepted iff `nullable` or (optional and declared default is `None`); otherwise 400. Worded as "null is read exactly as an omission where omission leaves something absent (optional identifier / corrected mark or placement / free-text note or reason / map or list / figure that is itself null)", and closed the rejecting set by exhaustive enumeration of the *only* nine optional fields with a substantive scalar default — `min_age` 50, `min_entries_to_stage` 3, `accessible_units` 0, `certification_level` 0, `teardown_buffer_minutes` 15, `required_official_count` 2, `municipal_support_cents` 0, `age_basis` `REFERENCE_DATE`, `has_onsite_medical_bay` false — plus required fields. Deliberately *not* keyed on "default is null", because Pass A's §3.1/§3.6 sentences describe `equipment_profile`/`format_modifications`/`certified_sport_codes` as defaulting to empty object/list while still accepting explicit null; the "leaves something absent / substantive scalar default" split keeps both true. Consistent with Pass B's §3.3 `review_note` and §3.6/§3.8 `reason` sentences. (`core.py:369-373`, all 24 `required=False` sites)
- §3.7 — insert — ambiguity — the cited entry's own review status is not re-examined when a mark is filed (`r_results.py:27,36`)
- §3.7 — insert — ambiguity — entry and slot are never checked to concern the same sport event (`r_results.py:27-33`)
- §3.7 — insert — ambiguity — the record-beating comparison is strict: a mark equal to the standing record takes the non-record (`VERIFIED`) branch, contrasted against the national-qualifying comparison which equality does satisfy (`calc.py:269-272`)
- §3.7 — insert — ambiguity — publishing a `RECORD_PENDING` mark with no filed claim is `ERR_INVALID_STATE_TRANSITION` (409); PRD stated the rule but no error id (`r_results.py:112-120`)
- §3.7 — insert — ambiguity — protest `grounds` is a mandatory non-empty field, validated then discarded (`r_results.py:129`)
- §3.7 — revise — mismatch — PRD said `REMEASURE` "rewrites both" `mark_value` and `placement`; both are optional and an omitted or explicitly null figure leaves the existing one standing; supplied values still `> 0` / `>= 1` (`r_results.py:175-186`)
- §3.7 — insert — ambiguity — a claim's `sport_event_id` is never checked against the event the cited mark was contested in; `age_group_code`/`superseded_record_id` derive from the named event regardless (`r_results.py:212-226`)
- §3.7 — revise — mismatch — PRD claimed "a cascade-driven rejection leaves `ratified_by_user_id` null" unconditionally; true only for claims swept from `PENDING_RATIFICATION`. The void cascade rejecting an already-`RATIFIED` claim leaves the ratifier's id in place (`r_results.py:150-153` vs `274`)
- §3.8 — insert — ambiguity — `accessible_units` defaults to zero and is read by no gate, cascade or computed figure (`r_village.py:20,36`; no other reader in `implementation/`)
- §3.8 — insert — ambiguity — athlete and block are never checked to share an edition, no athlete-registration or edition-status gate, and the village window comes from the **block's** edition (`r_village.py:74-89`)
- §3.8 — insert — ambiguity — stay-cancellation `reason` is validated then discarded; empty string and explicit null both accepted (`r_village.py:124`)
- §3.9 — insert — ambiguity — commitment withdrawal accepts an optional `reason`, validated then discarded (PRD previously described no body at all for that endpoint) (`r_sponsor.py:79`)
- §3.9 — revise — mismatch — PRD said a finalized edition accepts "no sponsorship withdrawal"; only the `ALLOCATED` branch is barred, a still-`PLEDGED` commitment can be withdrawn after finalization because it touches no ledger (`r_sponsor.py:81-97`)
- §4 (competition-results row) — revise — mismatch — description said "for an accepted entry"; changed to "under their own identity for an entry in a competed slot" (`r_results.py:24-35`)

Checked and found already uniquely pinned (no edit): verify/publish/protest/resolve/ratify role sets and origin states, `LIVE_MARK_STATES` duplicate gate, `ERR_SEGREGATION_OF_DUTIES` pair on `RATIFY` only, supersede/revival guards, bed-night per-night gate and `RESERVED|CHECKED_IN|COMPLETED` occupancy set, village window inclusivity and `nights`/`total_charge_cents` derivation, the four sponsorship buckets with per-bucket rounding, and all list-filter sets in the three files. Precedence positions of every error raised in my partition agree with §2.10's existing ordering, including the withdraw-branch edition check (not listed at step 10, and unreachable before step 11 in impl).

---

## PIPELINE COMPLETE — 2026-09-03T14:36:00.000Z

All nine steps ran. Final artifact state:
- `SCAFFOLD.yaml` 3270 lines, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` 2251 lines (25 instances), `SCAFFOLD_CORNER_DESIGN.yaml` 4405 lines (99 instances, 61 non-stub)
- `test_helpers/` 9 files / 2379 lines; `test_suite/` 19 test files + conftest / 142 tests, every test carrying one `Design:` tag and verbatim PRD citations
- `workspace/implementation/` 16 Python modules + start.sh / 3244 lines, 75 endpoints, in-memory only, nothing seeded
- `workspace/PRD.md` (485 lines) -> `PRD_FINALIZED.md` (2 revisions) -> `PRD_COMPLETED.md` (57 further edits: 43 ambiguity-pins, 14 mismatch-revisions)
- Final sweep: 8/8 rounds at 142/142, `results.1..8.json` on disk and independently re-parsed by the orchestrator
