# Worklog — task_2534_sailing_regatta_handicap_rating_administration

## Step 1: Create task directory — 2026-09-03T07:07:30.000Z

Created pre-assigned task directory `/home/ubuntu/github/CodingPRD/tasks/task_2534_sailing_regatta_handicap_rating_administration` and its `workspace/` subdirectory. Index 2534 was fixed by the scenario number (no auto-allocation scan performed, per orchestration instructions — other pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-03T09:46:00.000Z

All three scaffold artifacts for task 2534 are complete and lint-clean.

**Files** (all at `/home/ubuntu/github/CodingPRD/tasks/task_2534_sailing_regatta_handicap_rating_administration/`):

| file | lines | top-level key |
|---|---|---|
| `SCAFFOLD.yaml` | **3105** | §1.0–§1.7 only (no `scaffold_difficulty_design`, no `scaffold_corner_design`), `difficulty_level: beyond_expert` |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | **1816** | single key `scaffold_difficulty_design`, 23 instances |
| `SCAFFOLD_CORNER_DESIGN.yaml` | **2583** | single key `scaffold_corner_design`, 75 instances |

Every file was built with an initial `Write` plus heredoc `cat >>` appends (never a one-shot dump), YAML-parsed after each chunk, and each ends at a real structural boundary (verified with `wc -l` + `tail`).

**§1.9 section coverage** (all nine claim-extraction-guide sections): entities 11, state_machines 17, calculations 9, validations 13, endpoints 6, errors 8, rbac 5, complexity_layers 4, consistency_model 2 — 57 full `test_recipe` instances + 18 `excluded_because` stubs, all stubs citing an existing §1.8 instance name; 97 instance names across both design files, zero duplicates.

**Work completed in this final stretch:** errors chunk C (score/entries-closed after RACING, protest-filing window and party rejections, and the full hearing/decision rejection ladder covering HEARING_TIME_INVALID → HEARING_NOT_DUE → EVIDENCE_REQUIRED → DECISION_PAYLOAD_INVALID ×2 → REDRESS_NOT_COMPUTABLE), the whole `rbac` section (three peer-role 403 probes, the ClubAdmin-exclusive credential patch that unlocks a measurer, and a segregation-of-duties probe where confirming a seated judge as PRO is 409 `ERR_JURY_CONFLICT_OF_INTEREST` until the judge is recused), `complexity_layers` (both OCC rules — `ERR_STALE_BOAT_VERSION` and `ERR_STALE_REGATTA_VERSION` — plus cascade/dual-variant stubs; a comment explains that `selector_policy` has no guide row and is carried by the two selector calculations), `consistency_model` (`immediate`), and one added `endpoints` instance closing the last untested endpoint, `POST /protests/{id}/invalidate` (terminal INVALID lockdown).

**Verification sweeps:** all 51 error ids in §1.6 have at least one positive `error_id` assertion across the two design files (no id appears only in a "not X" clause); forbidden concurrency vocabulary count is zero; asserted numerics were recomputed from the §1.4 formulas (e.g. rating 171.3 / 218.8 / 170.4, corrected 3772.2 / 2872.2 / 2987.2 — one assert was corrected from 171.2 to 170.4).

Lint verdict, verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2534_sailing_regatta_handicap_rating_administration/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2534_sailing_regatta_handicap_rating_administration/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2534_sailing_regatta_handicap_rating_administration/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    72
  §1.1 entities declared:     14
  §1.8 instances scanned:     23
  §1.9 instances scanned:     57
  Calls scanned (§1.8+§1.9):  1846

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

One earlier fix worth flagging to the caller: `SCAFFOLD.yaml` line 1847 (validation priority 12) was narrowed so `ERR_ENTRIES_CLOSED` at priority 13 is actually reachable — previously the phase rule shadowed it entirely. No sibling task directory was read at any point.

Orchestrator verification: all three files parse as YAML; top-level keys confirmed correct (SCAFFOLD.yaml has neither design key).

## Step 3: Copy shared files — 2026-09-03T09:47:00.000Z

Copied `./INSTRUCTION.md` (53 lines) to `tasks/task_2534_sailing_regatta_handicap_rating_administration/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-03T10:05:00.000Z

PRD.md is complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2534_sailing_regatta_handicap_rating_administration/workspace/PRD.md` — **493 lines**, 15,245 words, built by 1 `Write` + 9 heredoc `cat >>` appends (no one-shot giant write, so no 64k truncation risk).

**Tail is a clean section end.** The file's last line is the final row of the §5 error table (`| \`ERR_DIVISION_NOT_CONFIRMED\` | 409 |`) — a completed table, completed section, not mid-sentence, not mid-row.

**Sections covered** (verified by heading dump):
- §1 Introduction
- §2 Global Specifications: 2.1 RBAC (all 6 roles, `ClubAdmin` opaque, 5 `entity_backed:ClubMember`) · 2.2 Response Structure (byte-verbatim from `skills/prd-bench-doc-generator/section-2.2-response-structure.md`, confirmed by exact substring match) · 2.3 Pagination · 2.4 Identity/timestamps/logical clock · 2.5 Numeric precision · 2.6 OCC on `Boat.version` and `Regatta.version` · 2.7 Rejection Precedence (all 51 checks, numbered 1–51 in scaffold priority order) · 2.8 Cross-regatta coherence · 2.9 Cascades and derived counters · 2.10 Segregation of duties · 2.11 Filtered collections / reverse reachability · 2.12 Conserved quantities
- §3 Business Logic, 10 subsections 3.1–3.10 covering all 14 entities, all 8 state machines (both Entry dimensions, both Race dimensions, cyclic protest machine, compound jury/regatta bubble-ups) and all 10 calculations (`certificate_rating_value`, `corrected_time` dual variant, `race_points_and_places`, `series_standing`, `redress_points_average`, `entry_division_assignment_selection`, `division_merge_target_selection`, `race_staffing_readiness`, `duty_minutes_ledger`, `series_points_conservation`)
- §4 Endpoint Definitions — 72 rows, exactly 4 columns
- §5 Error Code Catalogue — 51 rows, exactly 2 columns

**Hard Contracts (reported here only, never written into PRD.md — confirmed by grep that no "Contract"/"PASS" report text leaked in; the 4 hits are domain terms `PASSED`/`PASS`/`CONFIRMED`):**

- **Contract 1 — Field-Name Coverage: PASS.** Two machine-checked passes. Pass A: all 148 `entities[].fields[].name` across the 14 entities appear verbatim in backticks — 0 missing. Pass B: every endpoint `input`, `query_params` and `path_params` identifier across all 72 endpoints appears verbatim in backticks — 0 missing (`limit`/`offset` excluded, covered generically in §2.3). Spot-checked risk items all present: `crew_capacity`, `seated_utc`, `seat_role`, `recused`, `resulting_start_status`, `black_flag_applied`, `filed_utc`, `rule_cited`, `to_iso8601`, `current_utc`, `outcome`, `reason_code`, `judge_certification_level`, `voided`.
- **Contract 2 — Rule Coverage: PASS.** All 51 validations present with their exact error IDs and `applies_to` scopes enumerated in §2.7 (0 error IDs absent from §2.7). All 43 state-machine transitions covered: 32 as explicit `FROM → TO` arrows, the remaining 11 in equally explicit prose (verified individually — `SUBMITTED`/`ACCEPTED`→`WITHDRAWN`, `SEQUENCE_STARTED`/`STARTED`→`ABANDONED`, `FINAL`→`NOT_SCORED`, the `FINAL`→`FINAL` rescore self-loop with `rescore_count` as its observable, `HEARING_SCHEDULED`→`FILED` recusal revert, `DECIDED`→`REOPENED`, `FILED`→`INVALID`, `PROPOSED`/`CONFIRMED`→`RELEASED`). Both OCC rules, all multi-hop cascades (4-hop certificate suspension, 3-hop recusal, 4-hop decision, 3-hop abandonment), sibling-branch symmetry for all four `decision` values, field-level structured content (`crew_manifest`, `seats`, `evidence_log`), selector policies, and the two conserved-quantity identities are all stated.
- **Contract 3 — §3 Path Purity: PASS.** Regex scan over the §3 region only: zero `/`-leading tokens, zero bare HTTP method tokens (`GET`/`POST`/`PATCH`/`PUT`/`DELETE`), zero occurrences of `regatta-ops`. Paths appear only in §2.6/§2.7/§4, which Contract 3 permits.

**Cross-checks against the scaffold:** §4 roles match `endpoints[].roles` exactly for all 72 rows (0 mismatches, 0 extra rows, 0 missing rows); §5 rows match `errors[]` in exact scaffold order with exact `http` statuses (51/51, zero diffs). The §4 status-code paragraph was revised after an audit found the generic wording ambiguous for the three sub-record appends (`.../crew`, `.../seats`, `.../evidence`) and `DELETE .../crew/{member_id}`, which the scaffold codes 200 rather than 201; it now names the 14 operations that return 201 explicitly.

**Constraint compliance:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced, and no sibling task directory was read.

Orchestrator truncation check (per the known doc-generator failure mode): independently confirmed 493 lines; headings §1 through §5 all present in order; §4 contains 72 method rows and §5 contains 51 error rows; `tail -25` ends on a complete final table row. Not truncated — no regeneration needed. Grep for `harder than expert` / `expert level` / `scaffold` / `difficulty_level` in PRD.md returns zero hits, so the Step 2-only difficulty instruction did not leak.

## Step 6: Generate implementation — 2026-09-03T10:47:00.000Z

The implementation for task 2534 is complete and boots clean.

## Files written (`.../task_2534_sailing_regatta_handicap_rating_administration/workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `start.sh` | 10 | `cd $(dirname $0)`, guarded `pip install` (only when flask is missing, so per-test reboots don't re-run pip), then `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 68 | app factory, 4 blueprints, `ApiError`/404/405/HTTPException/Exception handlers all emitting the error envelope, `0.0.0.0:$PORT` (default 10000) |
| `util.py` | 131 | ids, `req_` request ids, ISO-8601 parse/format, `rhu()` half-up rounding, `pub()` |
| `errors.py` | 122 | all 51 error ids → HTTP status, default messages |
| `store.py` | 132 | in-memory dicts for the 14 collections, logical clock pinned to `2026-08-01T00:00:00Z`, `insert/touch/apply_changes/find` |
| `pipeline.py` | 336 | envelope, precedence steps 1–10 (auth, licence, body spec, pagination, FK resolution) |
| `calc.py` | 452 | all 9 calculations with every rounding point pinned |
| `services.py` | 269 | cascades, derived counters, conserved-quantity refreshes, the four conflict predicates |
| `routes_core.py` | 544 | clock, club members, boats, certificates, regattas, race documents |
| `routes_fleet.py` | 658 | divisions, entries + crew/inspect/assign/accept/withdraw, series-standing read, mark boats, duty assignments |
| `routes_racing.py` | 458 | races, start-sequence/recall/start/abandon/score, staffing read, race results, recall events |
| `routes_jury.py` | 520 | jury panels, seats, recusal cascade, protests, evidence, hearings, decisions, reopen, invalidate |

Total 3701 lines. Storage is in-memory only (verified: no `open(`, `sqlite`, `json.dump`, `/tmp` anywhere) and nothing is seeded at startup.

## Verification performed
- Every module compiles (`python3 -m py_compile`), each written in chunks with heredoc appends.
- **Route parity is exact**: the registered URL map, method-for-method, is `diff`-identical to the 72 endpoints declared in SCAFFOLD.yaml.
- **End-to-end smoke run** against a fresh `PORT=18534 bash start.sh` process: clock set → 10 members → 3 boats/certs (created + issued) → regatta → NOR/SI with OCC versions → division → 3 entries with crew, inspection, division assignment and acceptance → division confirm → jury panel to quorum (`SEATED`) → `open-racing` → race → 3 duty assignments confirmed (`staffing_ready: true`, window 12:30–15:00) → start-sequence → GENERAL recall → re-sequence → start → 3 FINISHED results (TOD corrected times 4916.0 / 5037.0 / 5158.0) → score (`points_pool_total 6.0`, race `FINAL`, regatta auto-bubbled `SCORED`, `final_race_count 1`) → series-standing read → protest → evidence → schedule-hearing → hear → `PENALTY_DSQ` decide (target gross 2.0 → 4.0, rank 3) → reopen (restored to gross 2.0, rank 2, no drift) → invalidate. Negative probes returned the right codes: 401 unauthenticated, 400 pagination, 404 unknown id, 403 forbidden role, 409 `ERR_START_LINE_WINDOW_CONFLICT` (3-minute gap), 409 `ERR_DUPLICATE_RECORD`. Server then killed; no residue.

## Spec ambiguities resolved (as coded)
- Body validation (step 6) precedes path/FK resolution (step 8); the step-5 acting-party check uses lenient raw lookups since it runs before both.
- Race window conflict reduces to `|Δ scheduled_start| < 8 min` (5-minute closed window + 3-minute gap).
- `ERR_JURY_CONFLICT_OF_INTEREST` on hearing scheduling follows the PRD (chair vs the **protestee's** certificate measurer), not SCAFFOLD's wider "either entry".
- Recusal: no seat for that member → 404; seat already recused → 409; hop 3 fires only when the panel actually drops below quorum.
- `DISMISSED` rewrites nothing, so it neither re-scores nor bumps `rescore_count`; reopen bumps it only when a decision snapshot exists.
- JuryChair evidence/invalidate on a protest with no bound panel has no identity to compare against, so it is permitted.

Orchestrator note: Steps 5 and 6 were launched concurrently in a single assistant message, so the implementation generator started before `test_suite/` existed on disk — physical isolation from the test suite is guaranteed.

## Step 5: Generate unit tests — 2026-09-03T12:26:00.000Z

The suite is complete. Final state:

## Output files

`/home/ubuntu/github/CodingPRD/tasks/task_2534_sailing_regatta_handicap_rating_administration/test_helpers/` — 2451 lines
| file | lines |
|---|---|
| `__init__.py` | 50 |
| `api_client.py` | 284 |
| `api_errors.py` | 117 |
| `assertions.py` | 331 |
| `constants.py` | 138 |
| `factories.py` | 287 |
| `fixtures.py` | 678 |
| `test_users.py` | 68 |
| `types.py` | 498 |

`.../test_suite/` — 7035 lines, **104 tests**
| file | lines | tests |
|---|---|---|
| `conftest.py` | 29 | — |
| `test_01_corrected_time_and_series_variants.py` | 201 | 4 |
| `test_02_rating_value_and_points_formulas.py` | 330 | 6 |
| `test_03_non_linear_lifecycles.py` | 430 | 6 |
| `test_04_transitive_cascades.py` | 262 | 4 |
| `test_05_rejection_precedence_pairs.py` | 259 | 4 |
| `test_06_threshold_boundaries.py` | 305 | 4 |
| `test_07_cross_entity_gates.py` | 374 | 6 |
| `test_08_window_geometry.py` | 329 | 6 |
| `test_09_compensating_actions.py` | 269 | 4 |
| `test_10_entity_shapes.py` | 474 | 10 |
| `test_11_lifecycle_transitions.py` | 533 | 11 |
| `test_12_calculations.py` | 465 | 6 |
| `test_13_validations.py` | 651 | 10 |
| `test_14_endpoints.py` | 398 | 5 |
| `test_15_errors.py` | 968 | 8 |
| `test_16_roles_versions_and_visibility.py` | 758 | 8 |

(test_06 is 6 tests; the table row above is a typo — see verification output: 6.)

## Verification (whole suite, machine-checked)
- All 17 files `py_compile` clean and import cleanly as modules.
- **104 tests / 104 `Design:` tags**, one per test, always the last docstring line. Zero untagged, zero dual-tagged, zero tags pointing at a non-existent instance, zero tags pointing at an `excluded_because:` stub.
- **Coverage is complete with no skipped instances**: all 23 non-stub difficulty instances covered, each by ≥2 tests; all 57 non-stub corner instances covered by ≥1 test. The 19 corner stubs and the 4 difficulty stubs were correctly not translated. **The gap list is empty** — every instance passed the PRD-first two-condition filter.
- Every quoted PRD citation in every docstring verified byte-verbatim (whitespace-normalised) against `workspace/PRD.md`, and every `PRD X.Y` section label verified to be the section the quoted line actually lives in.
- No `scaffold` / `SCAFFOLD` / `§1.` leakage anywhere.
- No unused imports, no undefined names, every `from test_helpers import` name confirmed exported.

## Work done this session
`test_16_roles_versions_and_visibility.py` (new, 8 tests): the 5 `Corner/rbac` instances (measurer locked out of duty/staffing/standing reads; start-sequence reserved to `RaceOfficer` with the role check firing ahead of path resolution on an unknown id; `ClubAdmin` opens a regatta it may not publish/divide/open-race; the `ClubAdmin`-exclusive credential patch unlocking `ERR_MEASURER_NOT_LICENSED`; segregation of duties blocking a `PRO` confirmation until the judge's seat is recused), the 2 `Corner/complexity_layers` optimistic-concurrency instances (412 `ERR_STALE_BOAT_VERSION`, 412 `ERR_STALE_REGATTA_VERSION`), and the 1 `Corner/consistency_model` immediate-visibility instance.

I also fixed 11 pre-existing citation defects found by the final two audit passes: 5 non-verbatim quotes (3 clause-truncations that had substituted `.` for `;`/`,` in test_07/test_11; a fabricated withdrawal-cascade "Hop three…" paraphrase in test_07 replaced with the real §3.5 withdrawal sentence plus the §2.9 counter definition; a paraphrased race-defaults sentence in test_08 replaced with the real §3.7 text) and 6 wrong section labels (test_04 `3.10`→`2.9`, test_10 and test_13 `2.4`→`2.3`, test_12 `3.9`→`3.8` ×2, test_16 `2.11`→`2.6` ×2). Also dropped 2 unused imports from test_02.

## Design-vs-PRD conflicts found (PRD followed in every case)
1. `cross_entity_state_dependency/start_sequence_blocked_while_division_reverted_to_provisional` asserts a `WITHDRAWN` entry keeps the merged division's `division_id`; PRD §3.4 hop two says "the pointer itself moves for every entry of the merged division". test_07 asserts only what both agree on.
2. `state_machines/certificate_reinstate_returns_entries_to_submitted_not_accepted` has prose saying "accepted_entry_count stays 0" contradicting its own assert `accepted_entry_count == 1`. test_11 follows the asserts, which match the PRD.
3. All 19 corner stubs' `excluded_because.difficulty_instance` name rule_ids that do not exist in `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (`cascading_side_effects`, `rounding_order_dependency`, `threshold_boundary`, `guarded_cross_entity_transition`, `derived_ledger_reconciliation`, `validation_priority_ordering`, `dual_variant_calculation`, `aggregate_window_constraint`) versus the real `transitive_cascade`, `combinatorial_formula`, `boundary_precision_check`, `cross_entity_state_dependency`, `compensating_invariant`, `priority_pair_validation_conflict`, `dual_variant_calc`, `resource_temporal_overlap`. Every stub's *instance name* resolves, so the exclusions are legitimate; only the rule-label half is stale.
4. Design crew position `TRIMMER` is not a PRD enum member (`HELM, TACTICIAN, TRIM, BOW, FLOATER`); `TRIM` used.
5. Design's `422 ERR_INVALID_REQUEST` for protest invalidate contradicts the PRD §5 table (400); 400 asserted.
6. Design's `ERR_DIVISION_NOT_CONFIRMED` on a re-score of a `FINAL` race is masked by priority-11 `ERR_INVALID_STATE`; test_15 reaches the same error id via a second still-`PROVISIONAL` race on a two-race card.
7. RBAC instance 1 asserts the staffing read answers `required_position_codes`/`is_ready`; PRD §3.6 declares `race_id`, `staffing_ready`, `staffed_position_codes`, `missing_position_codes`, `coverage_window_start_utc`, `coverage_window_end_utc`. PRD names asserted.
8. RBAC instance 3 and complexity_layers instance 2 both assert a published document has `status EFFECTIVE`; PRD §3.3 says "The document's own `status` starts at `PUBLISHED`." `PUBLISHED` asserted.
9. RBAC instance 4 asserts `judge_certification_level` is still null after the licence patch; PRD §3.1 says it "defaults to `NONE`". `"NONE"` asserted.

## Step 7: Run tests and iterate — 2026-09-03T12:34:00.000Z

Loop complete and green.

## Result

**8/8 rounds: 104/104 passed, 0 failed, 0 errors, 0 skipped** (192s each, union of non-passing tests across all 8 rounds: empty). Baseline was 84/104 in every round.

## Summary

**Iterations run:** 2 full 8-round parallel `setsid nohup` sweeps (iteration 1 = 84/104 identical in all 8 rounds → zero flakiness, so all 20 failures were deterministic defects; iteration 2 = 104/104 in all 8 rounds).

**Tests deleted:** none. Every asserted rule had verbatim PRD coverage and was uniquely derivable. The one non-derivable element found was a *rendering* detail, not a rule, and was handled by STEP 1c splitting (below) rather than deletion.

**Fixes to `test_helpers/`:**
- `/home/ubuntu/.../test_helpers/assertions.py` — new `assert_same_instant(actual, expected, label)` (+ `import datetime as _dt`). PRD §2.4 fixes the three-fractional-digit rendering only for `created_at`/`updated_at` (and §2.2 for `api_request_timestamp`), and PRD writes clock values itself without fractional digits ("the clock reads exactly `2026-08-01T00:00:00Z`"), so the *rendering* of server-stamped/computed instants is not uniquely derivable — only the instant is. Auto-exported via the existing `from .assertions import *`.

**Fixes to `implementation/`:** none. The implementation was faithful in all five failure clusters; all `.py` mtimes remain pre-session (10:10–10:38) versus my edits at 12:09–12:16. Storage remains in-memory only — a persistence scan for sqlite/shelve/pickle/write-mode `open`/`json.dump`/`/tmp` came back clean.

**Fixes to `test_suite/` (all test bugs under STEP 2, plus one STEP 1c split):**
- `test_02_rating_value_and_points_formulas.py` — `ENTRANTS_D_A_B` boat B had `"measurement": None`, which `file_certificate` silently resolves to `MEASUREMENT_A`, so A and B shared rating 171.3 and never formed the tie group the four tests assert. Set to `MEASUREMENT_B` (rating 218.8 → corrected 4000.0, tying A); reproduces every asserted figure (8.8 / 4.4 / 4.2 / 7.2 / 17.6 / 13.4 / 0.0, ranks 1-2-3).
- `test_03_non_linear_lifecycles.py` — `_recall_cycle_to_black_flag` started the race before the individual recall, but PRD §3.7 only ever describes an individual recall with "the race stays in `SEQUENCE_STARTED`". Parameterised with `start_race=False`, ran the recall from `SEQUENCE_STARTED`, corrected `resulting_start_status` to `SEQUENCE_STARTED`, and moved the start + clock advance to just before the `record_result` calls.
- `test_05`, `test_06`, `test_07`, `test_09` — four `build_accepted_fleet_world(... racing=True ...)` call sites omitted `panel=True`, but PRD §3.3 verbatim requires "at least one jury panel of the regatta has reached status `SEATED`" before `SI_PUBLISHED → RACING`. Added `panel=True` (8 tests were failing with `ERR_INVALID_STATE`).
- `test_05`, `test_12`, `test_15`, `test_16` — 10 raw string comparisons on `results_closed_utc` / `filed_utc` / `recorded_utc` / `coverage_window_*_utc` converted to `assert_same_instant`. Exact-instant semantics preserved; client-echoed instants left as literal `==`.
- `test_15_errors.py` — two HTTP status corrections against PRD §4's explicit lists: crew registration is one of "the three operations that append a sub-record… and return that resource" (201 → 200), and "signalling a recall" is in the 201 list (default 200 → explicit 201).

Sweep artifacts: `workspace/sweep.log` and `workspace/implementation/results.1-8.json`.

**Orchestrator verification of the Step 7 claim** (a subagent has been known to report a clean sweep with no artifacts on disk): independently re-read all 8 `results.*.json` — 8 files present, mtime 12:22:20, each `total 104 / passed 104 / failed 0 / errors 0 / skipped 0`. `grep -c 'def test_'` over `test_suite/` sums to 104, so no test was silently dropped to reach green. All `implementation/*.py` mtimes are 10:11–10:38 (pre-Step-7), corroborating "0 implementation fixes". Persistence scan for `sqlite|shelve|pickle|json.dump(|open(...,'w'/'a')` over the implementation returns zero hits — storage is in-memory only. `sweep.log` tail confirms `Results: 104/104 passed` at 192.4s. Claim accepted.

**Step 8 skip decision:** NOT skipped. The skip condition requires all four counters at zero; here deletions = 0 and implementation fixes = 0, but there were 5 `test_suite/` fix clusters and 1 `test_helpers/` addition. Several of those are PRD-silence signals worth pinning (instant rendering for server-computed timestamps, the `panel=True` SEATED precondition, the crew-append/recall HTTP status split), so Step 8 runs with the above entry inlined as `<step_7_diff>`.

## Step 8: Finalize PRD — 2026-09-03T12:45:00.000Z

`PRD_FINALIZED.md` is written and intact.

## Line counts
- `PRD.md`: 493 lines
- `PRD_FINALIZED.md`: 493 lines (+0 lines, 0.0% delta; 2 lines revised in place — both paragraphs, so no line-count change)
- `tail -5` ends inside the §5 Error Code Catalogue table at `| ERR_DIVISION_NOT_CONFIRMED | 409 |`, a real document boundary.

## Changes

- **§2.4 — revise — pinned the rendering of every server-stamped/computed instant (three fractional digits + trailing `Z`), and pinned that client-supplied instants are echoed verbatim** — `implementation/util.py:39-43` (`fmt_dt`), `routes_racing.py:140,354-355`, `routes_jury.py:54,83,219,263`, `routes_core.py:26`, `pipeline.py:207-214`
- **§3.7 — revise — a recall may be signalled only while `start_status` is `SEQUENCE_STARTED`; any other start status is `ERR_INVALID_STATE`** — `implementation/routes_racing.py:163-164`

## Per-edit pre-edit search log

**Edit 1 — §2.4 instant rendering**
- (a) Subject: the wire rendering of every datetime-valued field in any response.
- (b) Paths enumerated: `grep -n fmt_dt implementation/*.py` gave the exhaustive set of server-rendered instants — `store.py:73,88` (`created_at`/`updated_at`, from `wall_now()`), `routes_jury.py:54,83` (`seated_utc`), `:219` (`filed_utc`), `:263` (`recorded_utc`), `routes_racing.py:140` (`results_closed_utc`), `:354-355` (`coverage_window_*_utc`), `routes_core.py:26` (`current_utc`), `pipeline.py:35` (`api_request_timestamp`). Read `util.py:39-43` to confirm the format (`%H:%M:%S.` + 3-digit ms + `Z`). Read `pipeline.py:207-214` (`F.coerce` for `kind == "datetime"`) and confirmed it returns the client string **unchanged**; then checked every client-supplied instant is stored raw: `routes_core.py:61,224-225,405,516`, `routes_racing.py:78,245`, `routes_racing.py:222` (`signal_utc`), `routes_jury.py:218,304`, `routes_fleet.py:583-584` (`window_start_utc`/`window_end_utc`).
- (c) Adjustment: originally considered a blanket "all instants are rendered with three fractional digits", which would have been a **false universal** — 12 client-supplied fields (`signal_utc`, `actual_start_utc`, `scheduled_start_utc`, `effective_utc`, `valid_from`/`valid_until`, `series_start_utc`, `hearing_utc`, `incident_utc`, `window_start_utc`/`window_end_utc`, `safety_course_expiry_utc`) are echoed byte-for-byte. Re-scoped the claim to "instants the server itself stamps or computes rather than echoing back from the client", enumerated them explicitly, and added the complementary sentence for the client-echoed case. Also deliberately said nothing about *which* clock feeds each stamp (`created_at`/`updated_at` use wall time, the rest use the logical clock) — that distinction is off the Step 7 site and PRD is silent on it, so widening would have invented behavior.

**Edit 2 — §3.7 recall start-status precondition**
- (a) Subject: the precondition on `start_status` for `POST /races/{id}/recall`, and its interaction with the other recall-path rejections.
- (b) Paths enumerated: `routes_racing.py:146-229` (whole `race_recall`, including the `must("entries", …)` FK resolution at 160-161 that precedes the state check, and the ordering of steps 17/23/45/46 after it); `routes_racing.py:106-107` (`start-sequence`, `PENDING`|`GENERAL_RECALLED`), `:238-239` (`start`, `SEQUENCE_STARTED`), `:256-257` (`abandon`, `SEQUENCE_STARTED`|`STARTED`) to confirm the full `start_status` enum is exactly `PENDING`, `SEQUENCE_STARTED`, `GENERAL_RECALLED`, `STARTED`, `ABANDONED` and that no other endpoint writes a sixth value; `routes_racing.py:185-197` to confirm both `recall_type` branches sit behind the same single gate (the gate is not type-conditional); `routes_racing.py:224` (`resulting_start_status`) to confirm the new sentence does not contradict the existing "immediately after the event" wording.
- (c) Adjustment: added "whatever the `recall_type`" so the sentence cannot be read as gating only the `GENERAL` branch (whose `SEQUENCE_STARTED → GENERAL_RECALLED` edge PRD already names), since impl line 163 gates both branches identically. Left the sentence at the head of the paragraph so §2.7's step-11 ordering (before withdrawn/cross-regatta/not-accepted/payload checks) continues to govern unchanged.

Three of the five Step 7 clusters needed **no** PRD patch: the `ENTRANTS_D_A_B` `measurement: None` default and the four missing `panel=True` call sites were pure fixture bugs against rules PRD already states verbatim (§3.3's `SEATED`-panel gate, §3.2's rating formulas), and the two `test_15` HTTP-status corrections were test bugs against §4's already-explicit 200/201 lists.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` is 8 lines — exactly the two claimed in-place paragraph revisions (§2.4 line 86, §3.7 line 290), no other edits, no truncation.

**Step 9 plan:** Step 9 always runs. Because a single-pass Step 9 has previously returned a PRD_COMPLETED.md byte-identical to its input (i.e. the scan never actually ran), it is dispatched as three sequential file-partitioned passes over `implementation/` — pass A: `pipeline.py`, `store.py`, `util.py`, `errors.py`, `app.py`, `calc.py`; pass B: `routes_core.py`, `routes_fleet.py`; pass C: `routes_racing.py`, `routes_jury.py`, `services.py` — each editing the same `PRD_COMPLETED.md` in turn, so no pass has to hold the whole 3701-line implementation in context at once.

## Step 9: Complete PRD — 2026-09-03T13:20:00.000Z

Dispatched as three sequential file-partitioned passes over a single in-place `PRD_COMPLETED.md` (seeded by the orchestrator as a copy of `PRD_FINALIZED.md`), so no pass had to hold the whole 3701-line implementation in context and no pass could clobber another with a whole-file Write.

### Pass A — pipeline.py, store.py, util.py, errors.py, app.py, calc.py

**Counts: 19 ambiguity-pins, 3 mismatch-revisions, ~30 no-change confirmations.** 22 in-paragraph Edit patches, no new sections.

- 2.1 — insert — ambiguity — a header present but empty counts as missing; role matched exactly, case included — `pipeline.py:72`
- 2.1 — insert — ambiguity — an empty-string `measurer_license_id` is as unlicensed as a null one — `pipeline.py:90`
- 2.2 — insert — ambiguity — `api_request_id` is `req_` plus exactly 20 random upper-case-alphanumeric characters — `util.py:24`
- 2.2 — insert — ambiguity — `api_request_timestamp` comes from host real time, not the logical clock — `pipeline.py:35`
- 2.2 — insert — ambiguity — computed reads and the clock capability also carry `response_type` "object"; only collection reads carry "array" — `pipeline.py:42`
- 2.2 — insert — ambiguity — framework rejections share the envelope: unmatched path *and* undeclared method both → `ERR_RESOURCE_NOT_FOUND`/404 (never 405), trailing slash insignificant, unexpected fault → `ERR_INVALID_REQUEST`/500, message wording non-contractual — `app.py:31,42-58`
- 2.3 — insert — ambiguity — absent/empty `limit`/`offset` take defaults; whitespace and leading `+` tolerated; `10.5` rejected — `pipeline.py:269`
- 2.3 — insert — ambiguity — `created_at` ties (same millisecond) and every `created_at` tie-break resolve by server creation sequence — `store.py:112`
- 2.4 — revise — ambiguity — `id` is a canonical hyphenated version-4 UUID — `util.py:18`
- 2.4 — insert — mismatch — sub-millisecond precision truncated not rounded; the listed business instants come from the logical clock while `created_at`/`updated_at` are real-time audit stamps; client-instant grammar (T/space, optional seconds, 1–9 fractional digits, `Z`/`±HH:MM`/`±HHMM`/no zone = UTC) converted only for comparison — `util.py:39-73`, `store.py:75`
- 2.4 — revise — mismatch — "must never fall back to real time" narrowed to rules evaluated against the clock, so the audit stamps do not contradict it — `store.py:75`
- 2.4 — insert — ambiguity — the clock *sets* rather than advances: a backwards instant is legal, normalised to UTC — `store.py:58`
- 2.5 — revise — mismatch — replaced the false "both ends fall on a whole minute, so no truncation question arises" with: whole minutes between the ends, residual seconds discarded, sub-minute window → 0 — `util.py:111`
- 2.7 §5 — revise — mismatch — "exactly twelve operations" → thirteen (13 call sites verified) — `routes_fleet.py:152`, `routes_jury.py:155`
- 2.7 §5 — insert — ambiguity — the acting-party comparison only runs against an already-resolving row (absent/non-string/unresolvable id, or a protest with no bound panel, silently passes the step to a later one); unparseable body still yields `ERR_INVALID_REQUEST`; the certificate-issue identity rule sits after the state check and before the validity check instead — `pipeline.py:332`
- 2.7 §6 — insert — ambiguity — absent/empty body = empty object, non-object body rejected; unknown-field sweep precedes per-field checks; explicit `null` = absent for optional, missing for required; integral float OK for integer, boolean never; no-input endpoints reject any field; deferred ranges (4 measurement inputs, `elapsed_seconds`) tested at their later step — `pipeline.py:106,226,241`
- 2.9 — insert — ambiguity — a write that changes nothing is not a mutation (re-derivation leaves `updated_at`/`version` alone), while the explicitly named version bumps are unconditional — `store.py:84,92`
- 2.11 — insert — ambiguity — filters compare textually; empty or `null` value matches null-valued fields; `voided` accepts `true`/`false` any case; no match → empty page; undeclared query params ignored — `pipeline.py:297-317`
- 3.6 — insert — ambiguity — `staffed_position_codes`/`missing_position_codes` alphabetically sorted; staffed may include a non-required position and counts each once — `calc.py:427`
- 3.9 — revise — ambiguity — rows no division pass picked up are written `points` 0 *and* `place` null (incl. entries with no `division_id` or in a division with no accepted entries); voided rows untouched — `calc.py:119`
- 3.9 — insert — ambiguity — last-race tie-break: an entry with no result, or a voided one, in the highest-numbered counted race ranks below every entry that has one — `calc.py:263`
- 3.9 — insert — ambiguity — `tie_break_trace` vocabulary: `NET_POINTS`/`PLACE_COUNTS`/`LAST_RACE_POINTS`/`CREATED_AT` against the entry immediately above, `NET_POINTS` for rank 1, `NO_COUNTED_RACES`, plus `NOT_RANKED` — `calc.py:282`, `routes_fleet.py:443`

Notable no-change confirmations: the section 5 error table matches `errors.py` exactly (51/51 ids and statuses, scripted diff); both certificate rating branches including round-then-clamp; both corrected-time variants and their selection condition; slot bases, group-average-once, penalty cap at fleet+1, `n+1`/`n+2`/RDG-passthrough; counted-races, gross-of-pre-rounded, all three discard entitlements and the higher-`race_number`-first discard tie; firsts ladder to fleet size; `series_rank` null with no counted races; redress source-status set; division eligibility and merge selectors with their `_seq` (= `created_at`) tail tie-break; coverage window −30/+120 with inclusive flush edges; required positions by course and safety category; ledger statuses; recall events inserted unversioned; clock epoch `2026-08-01T00:00:00Z`; steps 1–3 ordering with the enrolment exemption.

### Pass B — routes_core.py, routes_fleet.py

**Counts: 19 ambiguity-pins, 11 mismatch-revisions, ~40 no-change confirmations.** 30 in-paragraph patches, `wc -l` unchanged at 494.

- **2.7 step 11** — revise — mismatch — "applies to every action endpoint" was a false exhaustive claim; two creations also run an `ERR_INVALID_STATE` check (document publication's first-SI rule, result recording's `STARTED` race) — `routes_core.py:486`, `routes_racing.py:382`
- **2.7 step 12** — revise — mismatch — phase list omitted division confirmation, which impl also gates on `NOR_PUBLISHED`/`SI_PUBLISHED` — `routes_fleet.py:87`
- **2.7 step 26** — revise — mismatch — `ERR_CERTIFICATE_EXPIRED` was claimed exclusive to entry submission/acceptance; certificate issue and reinstate answer it too, on the resolved row after its state check — `routes_core.py:250,314`
- **2.8** — revise — mismatch — a `mark_boat_id` from another regatta is `ERR_MARK_BOAT_ASSIGNMENT_INVALID` (step 22), not `ERR_CROSS_REGATTA_REFERENCE` — `routes_fleet.py:549`
- **3.1 roster** — insert — ambiguity — `full_name`/`email` non-blank; email uniqueness also ignores surrounding whitespace — `routes_core.py:43,50`
- **3.1 roster** — revise — mismatch — member PATCH: explicit `null` *clears* `measurer_license_id`/`safety_course_expiry_utc` but is *ignored* for `judge_certification_level`; naming any of the three bumps `version` even with unchanged values, naming none bumps nothing (verified at runtime) — `routes_core.py:80-90`
- **3.1 boats** — insert — ambiguity — `sail_number` non-blank and compared ignoring whitespace; `boat_name` non-blank — `routes_core.py:123,131`
- **3.2 issue** — insert/revise — mismatch — window failure is `ERR_CERTIFICATE_EXPIRED`; superseding writes the row twice, so the issued certificate ends **two** versions up (verified: version 3) — `routes_core.py:250-261`
- **3.2 reinstate** — insert — ambiguity — window failure is `ERR_CERTIFICATE_EXPIRED` — `routes_core.py:314`
- **3.2 reinstate** — revise — mismatch — clearing was "races whose divisions all meet their floors"; impl clears only when no division remains `PROVISIONAL` while holding an assigned entry, and only for regattas of entries this cascade returned — `routes_core.py:324-325`, `services.py:93-99`
- **3.3 regatta** — insert — ambiguity — `host_club_name` non-blank — `routes_core.py:368`
- **3.3 documents** — insert/revise — ambiguity — first `SI` without a NOR is `ERR_INVALID_STATE`; **every** publication, amendment included, advances the regatta `version` by exactly one — `routes_core.py:486,523-531`
- **3.3 open-racing** — insert — ambiguity — all five refusals (wrong status included) are `ERR_INVALID_STATE`, and aggregates are read from stored counters — `routes_core.py:421-431`
- **3.4 create** — insert — ambiguity — `code` non-blank, unique case-insensitively/whitespace-insensitively; band edges unbounded and a bad edge order is `ERR_INVALID_REQUEST` *before* `regatta_id` resolves — `routes_fleet.py:32,43,48-51`
- **3.4 confirm** — insert — ambiguity — wrong phase is `ERR_REGATTA_PHASE_INVALID`; counts re-derived before the floor test — `routes_fleet.py:87-90`
- **3.4 merge** — insert — ambiguity — floor-already-met is `ERR_INVALID_STATE`; count re-derived first; no phase required — `routes_fleet.py:106-108`
- **3.5 crew** — insert — ambiguity — `weight_kg` has no range; manifest element holds exactly `member_id`/`position`/`weight_kg`, no id or timestamp; second `HELM` is also `ERR_DUPLICATE_RECORD`; unknown manifest member on removal is `ERR_RESOURCE_NOT_FOUND`; neither add nor remove reads `registration_status` or phase (a `WITHDRAWN` entry's manifest is editable, the `HELM` element removable) — `routes_fleet.py:227-276`
- **3.5 inspect** — insert — ambiguity — `FAIL` without a code is `ERR_INVALID_REQUEST` before the entry resolves; a code sent with `PASS` is accepted then discarded; all remaining refusals are `ERR_INVALID_STATE`, and the crew-count floor binds only the first pass — `routes_fleet.py:311-334`
- **3.5 assign-division** — revise — mismatch — "the entry's `version` advances" is false when the selector re-picks the held division (no-op, verified); assignment reads no `registration_status`; the vacated division re-derives its counts — `routes_fleet.py:293-297`
- **3.5 accept** — insert — ambiguity — acceptance/assignment touch neither `start_blocked_reason` nor `confirmed_division_count` — `routes_fleet.py:377-378`
- **3.6 mark boats** — insert — ambiguity — `call_sign` non-blank, unbounded length, unique case/whitespace-insensitively; any regatta phase — `routes_fleet.py:471-480`
- **3.6 duty create** — insert — ambiguity — bad window order is `ERR_INVALID_REQUEST` before references resolve; member overlap is tested across every regatta, not just this one — `routes_fleet.py:533,555`
- **3.6 duty confirm** — revise — mismatch — staffing is re-derived on **every** `PENDING` race of the regatta, not only races the assignment covers — `routes_fleet.py:611`, `services.py:112`
- **3.6 duty release** — revise — mismatch — the `SEQUENCE_STARTED` block applies to any covering assignment whatever its `position`; release also refreshes staffing on every `PENDING` race; `release_reason_code` required non-blank — `routes_fleet.py:618-642`

Notable no-change confirmations: clock capability shape; member/boat/certificate/regatta/document/division/entry/mark-boat/duty field sets, defaults and 201-vs-200 codes; certificate suspend cascade (hops 1–4, `SUBMITTED` untouched); merge candidate selection and its four hops; entry submission phase/`ENTRIES_CLOSED`/cross-reference/expiry order; acceptance's full guard chain and its 2.7 ordering; withdrawal's scored-result guard and division revert; series-standing response keys and trace vocabulary; duty `PROPOSED`-already-counts ledger semantics, half-open member windows, buffer-widened mark-boat overlap, `PRO`-versus-seated-panel conflict; all list filters and role lists in section 4.

### Pass C — routes_racing.py, routes_jury.py, services.py

**Counts: 19 ambiguity-pins, 4 mismatch-revisions, ~30 no-change confirmations.** 23 substantive changes across 25 Edit calls (2 were self-refinements for precision); passes A and B prose intact, section count still 5.

- 2.10 Segregation of Duties — revise — ambiguity — the helm conflict is tested against any entry of the regatta whatever its `registration_status`, a `WITHDRAWN` one included — `services.py:198`
- 3.7 (scheduling) — revise — mismatch — a gap of exactly 3 min is enough (starts 8 min apart legal), and an `ABANDONED` race is skipped by both the overlap and the gap test — `routes_racing.py:60-69`
- 3.7 (new race defaults) — insert — ambiguity — the block test ignores `MERGED` divisions and reads the stored `assigned_entry_count`; the seeded staffing values do not bump `version`, so a new race returns at `version` 1 — `routes_racing.py:70,93-96` / `services.py:65`
- 3.7 (start-sequence) — insert — ambiguity — "newest SI" means highest `revision`, and no `PUBLISHED` SI at all answers the same error — `routes_racing.py:116-121`
- 3.7 (recall payload) — insert — ambiguity — `reason_code` is a free-form non-blank string, not an enum — `routes_racing.py:155`
- 3.7 (recall record) — insert — ambiguity — `black_flag_applied` is captured before the general-recall increment (2nd general recall records false); the response body is the recall event, not the race — `routes_racing.py:184,215-229`
- 3.7 (black-flag individual recall) — insert — ambiguity — minted `OCS` row's full field shape, and a second such recall mints a second row (no `ERR_DUPLICATE_RECORD`) — `routes_racing.py:198-214`
- 3.7 (record start) — insert — ambiguity — no upper bound on `actual_start_utc`; recall counters, black flag and staffing fields untouched — `routes_racing.py:244-246`
- 3.7 (abandon) — revise — mismatch — PRD claimed a `SEQUENCE_STARTED` abandon voids nothing; all three hops always run, so a black-flag `OCS` row is voided and provisional scoring unwound; abandon demands no regatta phase — `routes_racing.py:256-277`
- 3.7 (abandon tail) — insert — ambiguity — `results_closed_utc`, recall counters, `black_flag_active`, `rescore_count`, staffing fields and `start_blocked_reason` are untouched, and the regatta `status` is never revisited (no bubble-up, no exit from `SCORED`) — `routes_racing.py:260-277`
- 3.8 (result payload) — insert — ambiguity — all eight abbreviations are declared enum members (a ninth string is `ERR_INVALID_REQUEST`) — `routes_racing.py:373,398`
- 3.8 (penalty_percent) — insert — ambiguity — a value outside {0,20,30,40} is `ERR_INVALID_REQUEST` at the body check — `routes_racing.py:375`
- 3.8 (corrected time) — insert — ambiguity — written as part of the creation, so the new result returns at `version` 1 — `routes_racing.py:427`
- 3.9 (scoring preconditions/hops) — revise — mismatch — division check reads the stored `accepted_entry_count`; DNC minting skips an entry holding any result voided or not; the `PROVISIONAL → FINAL` move happens before points are computed so the race is inside hop three's counted set (trailing sentence deleted) — `routes_racing.py:295-326`
- 3.10 (panel formation) — insert — ambiguity — formation reads no regatta phase — `routes_jury.py:33-61`
- 3.10 (seating) — revise — mismatch — `ERR_DUPLICATE_RECORD` only for a non-recused seat (a recused member may be re-seated, appending a second element); count is re-derived from non-recused seats; no panel-status or phase precondition, so a `SEATED` panel grows past quorum — `routes_jury.py:74-91`
- 3.10 (recusal) — insert — ambiguity — requires panel `SEATED` (`ERR_INVALID_STATE`), seat lookup after that check, no seat → `ERR_RESOURCE_NOT_FOUND`, already-recused seat → `ERR_INVALID_STATE`, first matching element wins, the `CHAIR` seat is recusable — `routes_jury.py:106-121`
- 3.10 (protest filing) — insert — ambiguity — a race whose `actual_start_utc` is null (results opened by a black-flag recall) admits no protest → `ERR_PROTEST_PARTIES_INVALID`; parties need not be `ACCEPTED` — `routes_jury.py:206-209`
- 3.10 (evidence) — insert — ambiguity — element field shape and no identifier; no protest-status check (appendable when `HEARD`/`DECIDED`/`INVALID`); the submitting entry need not be a party or of the same regatta — `routes_jury.py:245-267`
- 3.10 (decision payload) — insert — ambiguity — a `penalty_target_entry_id` on `DISMISSED` is stored unchecked; `redress_race_number` is written only by `REDRESS_GRANTED` — `routes_jury.py:369-404`
- 3.10 (decision hop two) — insert — ambiguity — target with no result in the affected race: hops two–four skipped, decision still succeeds, `rescore_count` unmoved — `routes_jury.py:406-441`
- 3.10 (reopen) — insert — ambiguity — `jury_panel_id`, `penalty_target_entry_id`, `redress_race_number` retained; `elapsed_seconds` restored; `rescore_count` increments again; a reopening with nothing to restore stops after hop one; the regatta stays `SCORED` — `routes_jury.py:458-481`

Notable no-change confirmations: start-sequence guard order and re-entry edge; recall state guard and cumulative `general_recall_count`/black-flag-at-2; `results_closed_utc` re-stamping; `ERR_DIVISION_NOT_CONFIRMED`, `ERR_ENTRY_NOT_ACCEPTED`, `ERR_ENTRY_WITHDRAWN`, `ERR_CROSS_REGATTA_REFERENCE` placements; hearing scheduling's five refusals and the `REOPENED` re-entry edge; `hear` (evidence + hearing-due) ordering; redress source-status set and single-evaluation rule; invalidation from `FILED`/`REOPENED` plus bubble-up; `maybe_score_regatta` conditions; `block_pending_races` (PENDING only) vs `clear_blocked_races` (any race carrying the reason); `refresh_final_race_count`; `hearing_conflict` (both helms, protestee's measurer only); staffing computed read's response shape.

### Orchestrator verification of Step 9

- `PRD_FINALIZED.md` 493 lines → `PRD_COMPLETED.md` 494 lines; **+19,305 chars**; 121 changed lines in the unified diff; md5sums differ. The scan genuinely ran (the known failure mode is a byte-identical output).
- Totals across the three passes: **57 ambiguity-pins, 18 mismatch-revisions**, ~100 no-change confirmations.
- Structure intact: 5 top-level sections, 22 subsections, §4 endpoint table still 72 rows, §5 error table still 51 rows, tail ends on the final complete table row.
- No `scaffold` / `§1.` / difficulty-instruction leakage in `PRD_COMPLETED.md`.
- `implementation/` untouched by Steps 8 and 9 (all `.py` and `start.sh` mtimes 10:10–10:38, pre-Step-7), and no `test_suite/`/`test_helpers/` file has an mtime after the green sweep at 12:22 — so `results.1-8.json` (8 × 104/104) remains a valid record of the current artifacts. No re-run needed.

**Pipeline complete.** `workspace/PRD_COMPLETED.md` is written; all nine steps done.
