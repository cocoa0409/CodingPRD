# Worklog — task_2757_scholastic_esports_league_team_eligibility

## Step 1: Create task directory — 2026-09-04T17:02:00.000Z

Created pre-assigned task directory `/home/ubuntu/github/CodingPRD/tasks/task_2757_scholastic_esports_league_team_eligibility` and its `workspace/` subdirectory. No index scan performed — the index 2757 was fixed by the orchestrating command because up to 32 pipelines run concurrently on this host and auto-allocation would collide.

## Step 2: Generate scaffold — 2026-09-04T19:32:00.000Z

Subagent summary (verbatim):

All three scaffold artifacts for task_2757 are complete and lint-clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2757_scholastic_esports_league_team_eligibility/`):
- `SCAFFOLD.yaml` — 3,449 lines / 168 KB (§1.0–§1.7 only; verified it contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2,980 lines / 179 KB (single top-level key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 7,704 lines / 459 KB (single top-level key `scaffold_corner_design`)

**Scaffold counts (§1.0–§1.7):** 11 entities, 6 state machines (TitleApproval, Season, Team, RosterSlot, Match, FairPlayCase), 2 §1.2.1 OCC rules, 12 calculations, 3 conserved-quantity invariants, 63 validations + 4 declared priority conflicts, 58 endpoints, 70 error ids, 7 roles. Profile: flat topology, parallel state shape, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation]`, `segregation_of_duties` role model, `immediate` consistency, `api_prefix: ""`.

**§1.8 depth probe:** 22 instances across the declared difficulty rules (dual-variant divergences, rank inversions, exact-threshold landings, cyclic state paths, 4- and 5-link cascades, all 4 priority conflicts, inclusive-boundary/millisecond cases, half-open interval capacity and adjacency, and the 3 conservation invariants).

**§1.9 breadth probe:** 92 instances = 72 with full test recipes + 20 `excluded_because` stubs, over nine sections — entities 12, state_machines 17, calculations 20, validations 24, endpoints 5, errors 1, rbac 6, complexity_layers 5, consistency_model 2. Every stub's cited `difficulty_instance` resolves by name in §1.8, no stub carries a `test_recipe`, and all 114 instance names are unique across the union of both design files.

**Coverage audits (both embedded as comment blocks in the corner file):**
- §1.5: 58 / 58 endpoints exercised, `uncovered: []` — the per-endpoint map is the comment block at the end of the endpoints section.
- §1.6: 70 / 70 error ids triggered by at least one recipe, `Uncovered error ids: NONE` — the map is the comment block at the end of the file (it accounts for the rbac, complexity_layers and consistency_model instances too).
- Both §1.2.1 OCC rules have a dedicated stale-version instance; all four complexity layers and the `immediate` consistency model have instances.

**Lint verdict** (`python3 /home/ubuntu/github/CodingPRD/skills/prd-bench-scaffold-generator/scaffold_lint.py <task dir>/`):

```
Coverage
  §1.5 endpoints declared:    58
  §1.1 entities declared:     11
  §1.8 instances scanned:     22
  §1.9 instances scanned:     72
  Calls scanned (§1.8+§1.9):  1744

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

One violation surfaced on the final pass and was fixed: the errors-section instance used a literal `expected_student_version: 999`; it now makes a real posting with the captured `${st1_v}` (bumping to `${st1_v2}`) and replays the stale `${st1_v}` to produce the 412, with the assertions renumbered accordingly.

**Action needed after Step 2:** `SCAFFOLD.yaml`'s `scenario:` key still begins with the verbatim line "Generate task harder than expert level!" as the task required. That directive must be stripped from `scenario:` before Step 3 or it leaks into PRD.md.

The no-peeking constraint was honoured throughout — every §1.1–§1.7 fact used by the design files was re-derived by dumping this task's own `SCAFFOLD.yaml` with Python; no sibling `tasks/task_*/` directory was listed, globbed, grepped or read.

**Orchestrator post-step action (per known leak):** the difficulty directive line `Generate task harder than expert level!` was stripped from `SCAFFOLD.yaml`'s `scenario:` block by the orchestrator immediately after this step; `grep -c "harder than expert" SCAFFOLD.yaml` now returns 0. The directive was never forwarded to the doc, test, or implementation generators.

## Step 3: Copy shared files — 2026-09-04T19:32:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-04T19:49:00.000Z

Subagent summary (verbatim):

PRD complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2757_scholastic_esports_league_team_eligibility/workspace/PRD.md` — **523 lines**, ends at the completed final section **`## 5. Error Code Catalogue`** (last row `| \`ERR_SUBSIDY_POOL_EXHAUSTED\` | 402 |`). Untruncated: confirmed by `wc -l` + `tail -40`; both tables are full-length (58 endpoint rows, 70 error rows).

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim fixed block) · 2.3 Pagination · 2.4 The Logical League Clock · 2.5 Resource Identity, Auditing and Record Versions · 2.6 Optimistic Concurrency on the Two Supersession Points · 2.7 Rejection Precedence · 2.8 Numeric Precision Across the League's Ledgers · 2.9 Conservation Invariants and Compensating Actions · 2.10 Flat Topology and Cross-Entity Resolution
- §3 Business Logic & Workflows — 3.1 District Policy Envelope and School Registry · 3.2 Coaching Credentials, Student Records and Academic Standing · 3.3 Title Catalogue and District Approval Pathway · 3.4 Season Construction and Stage Advancement · 3.5 Team Formation, Roster Building and Two-Person Eligibility Verification · 3.6 Registration Economics, Roster Lock and Withdrawal · 3.7 Match Scheduling, Result Reporting and Dispute Resolution · 3.8 Broadcasting, Spectator Conduct and Fair-Play Enforcement · 3.9 Playoff Seeding, Tiebreakers and the Showcase Pathway
- §4 Endpoint Definitions (4 columns: Method | Path | Description | Authorized Role(s))
- §5 Error Code Catalogue (2 columns: Error ID | HTTP Status Code)

**Coverage**
- Entities: 11/11 (District, School, Coach, Student, Title, TitleApproval, Season, Team, RosterSlot, Match, FairPlayCase), all flat, all carrying `id`/`created_at`/`updated_at`/`version`.
- Endpoints: 58/58 in §4, method+path verified row-by-row against the scaffold.
- Errors: 70/70 in §5 with correct statuses, and all 70 also named inside §1–§3 (none appears only in the table).
- State machines: 6/6 (TitleApproval, Season, Team, RosterSlot, Match with 4 parallel dimensions, FairPlayCase), 48 transitions; every state atom appears backticked somewhere in the doc; all 16 action/decision enum values covered.
- Calculations: all 12 rendered as prose (incl. both dual-variant pairs, the per-line-item money rounding, the integrity-score ladder, the showcase award chain).
- Validations: all 63 priorities enumerated in §2.7 in order, plus the 4 named precedence-conflict pairs; both `concurrency_rules` in §2.6; 3 conservation invariants with compensating pairs in §2.9.

**Hard Contract reports**
- Contract 1 (Field-Name Coverage) — **PASS.** 185 distinct `entities[].fields[].name` + `request_body`/`input`/`query_params`/`path_params` identifiers extracted from the scaffold; 0 missing from backticked PRD tokens. Field-level defaults/initials also checked: 0 missing (the two `[]` defaults, `recruiting_contact_log` and `seed_order`, are stated in prose as empty).
- Contract 2 (Rule Coverage) — **PASS.** 70/70 validation error IDs present in the §2.7 precedence ladder; all transitions, states, triggers, calculations, invariants, OCC rules and the `ERR_NOT_RESOURCE_OWNER` 13-operation `applies_to` scope are covered; sibling branches (APPROVE/DENY/REVOKE, SUSTAIN/DISMISS, AFFIRM/OVERTURN, UPHOLD/REJECT) written symmetrically.
- Contract 3 (§3 Path Purity) — **PASS.** §3 spans 162 lines; 0 backticked tokens beginning with `/`, 0 bare HTTP methods, 0 method+path combinations, and 0 un-backticked raw path mentions. Paths occur only in §2.6 and §4.

No audit footer or contract-report section was written into PRD.md. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced, and no sibling task directory was read.

**Orchestrator verification (truncation guard):** `wc -l` = 523; `tail -25` ends on the final error-catalogue row `| ERR_SUBSIDY_POOL_EXHAUSTED | 402 |` — a real section boundary, not mid-sentence. Section headings present: §1 Introduction, §2 Global Specifications, §3 Business Logic & Workflows, §4 Endpoint Definitions, §5 Error Code Catalogue. `grep -ci "harder than expert|expert level" PRD.md` = 0, so the Step 2 difficulty directive did not leak into the PRD. No regeneration needed.

## Step 6: Generate implementation — 2026-09-04T20:24:00.000Z

(Steps 5 and 6 were launched concurrently so the implementation generator could not see `test_suite/`. Step 6 returned first; its summary is recorded here, Step 5's below.)

Subagent summary (verbatim):

Implementation complete and verified.

## Files written (`/home/ubuntu/github/CodingPRD/tasks/task_2757_scholastic_esports_league_team_eligibility/workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `domain.py` | 858 | all 12 calculations, 6 state machines' cascades, conservation invariants |
| `routes_d.py` | 449 | matches (schedule, server-config, result-reports, finalize, forfeit, disputes, dispute-actions, broadcast) |
| `routes_b.py` | 434 | students, academic postings, showcase, recruiting, title-approvals, seasons |
| `routes_c.py` | 404 | teams + roster slots (two-person verification) |
| `routes_a.py` | 287 | districts, schools, coaches, titles, logical clock |
| `http_util.py` | 276 | envelope, rungs 1/2, pagination, rung-5 validators |
| `store.py` | 237 | in-memory dict store, logical clock, Decimal/rounding, version coalescing |
| `routes_e.py` | 237 | fair-play cases (sanction cascade + appeal compensation) |
| `serialize.py` | 158 | per-kind ordered field/precision specs |
| `errors.py` | 122 | 69 catalogued error ids -> HTTP status + fallback |
| `app.py` | 57 | blueprint registration, error handlers, `PORT`/`0.0.0.0` |
| `guards.py` | 54 | rung-3 ownership helpers |
| plus `start.sh` (exec's `python3 app.py`, reads `$PORT`, foreground) and `requirements.txt` (`flask>=2.2`) | | |

3573 lines of Python; every file passes `python3 -m py_compile`.

## Coverage
- **58 endpoints** registered, exactly matching PRD §4 (verified by enumerating `app.url_map`); plus an extra `/health` for boot probing.
- **6 state machines**: TitleApproval, Season (5 advances incl. the 2 compound-over-children conditions), Team (incl. SUSPENDED/WITHDRAWN/DISQUALIFIED), RosterSlot (2 verification axes -> derived participation), Match (4 parallel dimensions: play/result/dispute/broadcast), FairPlayCase (SUSTAIN/DISMISS fork + APPEALED re-entry with the five-link cascade and its exact inverse).
- **All 69 error ids** from PRD §5 present with byte-matching HTTP statuses (checked programmatically against the catalogue table).
- Storage is in-memory dicts only; nothing is seeded, no disk/SQLite/tmp use; clock starts at `2026-08-01T00:00:00.000Z` and only moves forward.

## Boot smoke test
`PORT=41983 ./start.sh` booted cleanly and answered `/health`. Two scripted end-to-end passes (~60 assertions) exercised the full spine and all figures matched the PRD's worked examples:
- entry fee 15845 with per-line-item subsidy rounding **3128+834 = 3962** (not 3961), net 11883
- scholarship **330000 -> SILVER -> 369600** (tier pinned, bonus not recomputed at the gold rate)
- integrity MAJOR+SMURFING = weight 25.00, penalty 25.00, score **75.00**, sanction `STUDENT_SUSPENSION`; after OVERTURN the score returns to **100.00** and the student to `CLEAR`
- upheld dispute flipped the winner, moved 3 points across teams, left `match_point_pool` conserved at 3, set `seeding_state=STALE`, `seed_stale=true`, and the nominated student to `RECALC_REQUIRED`; a later forfeit took the pool to 6 with `forfeit_wins=1`
- broadcast REGISTER/GO_LIVE/END, spectator-strike suspension via a `MATCH_BROADCAST` case (`WARNING`, strikes 1), RESUME, and ladder inversions (401 bad role, 404 unknown id, 409 duplicate/state, 412-style stale-version path, clock-rewind 409) all behaved per §2.7.

The smoke server was killed by its specific PID (3465097); no pattern kill was used, and `__pycache__`/temp scripts were removed.

## Step 5: Generate unit tests — 2026-09-04T21:33:00.000Z

Subagent summary (verbatim):

Test generation is complete. Summary for the orchestrator's worklog (I did not touch `worklog.md`):

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_2757_scholastic_esports_league_team_eligibility/` — task root, nothing inside `workspace/`, nothing read or written under `workspace/implementation/`.

`test_helpers/` — 9 files, 2932 lines: `types.py` 500, `api_client.py` 567, `api_errors.py` 156, `assertions.py` 197, `constants.py` 144, `factories.py` 343, `fixtures.py` 830, `test_users.py` 109, `__init__.py` 86.

`test_suite/` — `conftest.py` 20 plus 18 test modules, 9266 lines:

| module | lines | tests |
|---|---|---|
| test_boundary_precision.py | 269 | 6 |
| test_combinatorial_formulas.py | 336 | 6 |
| test_compensating_invariants.py | 367 | 6 |
| test_cross_entity_state_dependencies.py | 212 | 4 |
| test_dual_variant_academic_and_seeding.py | 251 | 4 |
| test_non_linear_state_machines.py | 253 | 4 |
| test_resource_temporal_overlap.py | 285 | 4 |
| test_transitive_cascades.py | 305 | 4 |
| test_validation_priority_pairs.py | 280 | 6 |
| test_corner_entities.py | 598 | 12 |
| test_corner_state_machines.py | 1053 | 14 |
| test_corner_calculations.py | 889 | 11 |
| test_corner_validations.py | 1967 | 20 |
| test_corner_endpoints.py | 737 | 5 |
| test_corner_errors.py | 208 | 1 |
| test_corner_rbac.py | 698 | 6 |
| test_corner_complexity_layers.py | 338 | 3 |
| test_corner_consistency_model.py | 200 | 2 |

## Totals and coverage

- **118 tests, 118 `Design:` tags** — every test function's docstring ends with exactly one tag, verified by AST walk (no untagged, no dual-tagged, no test lacking a docstring).
- **Queue A (Difficulty): 44 tests / 44 tags** across the 9 depth modules.
- **Queue B (Corner): 74 tests / 72 distinct instances = 72/72 of the non-stub instances**, machine-diffed against `SCAFFOLD_CORNER_DESIGN.yaml`: entities 12/12, state_machines 12/12, calculations 11/11, validations 20/20, endpoints 5/5, errors 1/1, rbac 6/6, complexity_layers 3/3, consistency_model 2/2. Every emitted tag resolves to a real `name:` in the yaml; no tag points at a stub.
- The 74-vs-72 gap is two deliberately split broad instances in `test_corner_state_machines.py`: `initial_states_are_pinned_for_every_entity_with_a_state_machine` (approval/season/team/slot, then match/case) and `terminal_states_reject_every_further_transition` (denied approval + dismissed case, then forfeited match). Each of the four tests carries exactly one tag and translates a disjoint subset of its instance's triggers.
- **SKIPPED instances: none.** All 20 `excluded_because:` stubs were left untranslated as required (state_machines 5, calculations 9, validations 4, complexity_layers 2), and no non-stub instance failed the PRD-first two-condition filter — every one had verbatim PRD coverage and a uniquely-derivable outcome, so there are no PRD-silence or non-unique-derivability gaps to report.

## Final audits

`python3 -m py_compile` passes on all 9 helper files and all 19 test-suite files (`ALL_COMPILE_OK`); `ls -la` confirms both directories at the task root; `__pycache__` byproducts removed. Nothing named `test_helpers`/`test_suite` exists under `workspace/` (which still holds only `INSTRUCTION.md`, `PRD.md`, `implementation`).

Two notes for the next step: the last two modules reuse the already-validated composites `fx.build_ready_match`, `fx.build_draft_team` and `fx.build_two_team_season` rather than hand-rolled chains, so a season-stage ordering bug in setup would surface identically across many modules rather than in one; and the money assertions in `test_corner_consistency_model.py` pin the per-line-item rounding answer (3128 + 834 = 3962) with an explicit guard against the sum-then-round 3961.

## Step 7: Run tests and iterate — 2026-09-04T21:54:00.000Z

Subagent summary (verbatim):

Clean sweep — 118/118 passing in all 8 rounds.

## Summary

**Iterations run:** 2

**Iteration 1** — all 8 rounds identical: 114/118 passed, 4 failures (fully deterministic, no flakiness anywhere in the suite).

**Tests deleted:** none (no whole test failed PRD coverage).

**Assertions removed (STEP 1c partial-coverage handling):**
- `/home/ubuntu/github/CodingPRD/tasks/task_2757_scholastic_esports_league_team_eligibility/test_suite/test_corner_endpoints.py` — `test_action_endpoints_answer_200_with_the_whole_entity_from_either_role`: dropped `assert released["release_note"] is None` (was raising `KeyError: 'release_note'`). **DEFAULT-VALUE / COMPUTED-FIELD SILENCE**: PRD §3.5 names `release_note` only as an optional *request* input ("optionally recording a `release_note`"); it is absent from the fresh-slot initialization list (which enumerates `released_at` and `ineligibility_reason` as the null-initialized fields) and absent from the on-success side-effect list. A faithful reader may accept-and-discard the note rather than expose it on the slot. The rest of the test (200 status, whole-entity payload, RELEASED axes, `released_at`, version, seat counters, dual-role certification) was kept.

**Fixes applied to `test_helpers/`:** none — the fixture layer was clean.

**Fixes applied to `test_suite/`:**
- `test_suite/test_resource_temporal_overlap.py` — `test_a_match_starting_exactly_when_a_peer_ends_still_fits_the_pool`: `A.data_of(accepted)` -> `A.data_of(accepted, 201)`. `data_of` defaults to `expected_status=200`, so re-validating an already-verified 201 creation response tripped "Expected 200, got 201". PRD §4: "Operations that bring a brand-new resource into existence answer with HTTP 201 Created" — the fix makes the test more faithful, not less.
- `test_suite/test_validation_priority_pairs.py` — builder `_build_nominated_student_at_the_cap_inside_the_dead_period`: `recruiting_dead_period_start`/`_end` changed from pure dates (`"2026-08-10"`) to ISO 8601 instants (`"2026-08-10T00:00:00.000Z"` / `"2026-08-20T00:00:00.000Z"`). PRD §2.4 is exhaustive — "**Four** fields are pure dates rather than instants ... a student's `birthdate`, a season's `age_cutoff_date`, a school's `enrollment_verified_through`, and a coach's `background_check_expires_on`" — so the dead-period bounds are datetimes, and rung 5 ("every datetime parsing as ISO 8601") correctly rejected the date-shaped input. This was one fixture bug masquerading as two independent failures (`test_dead_period_outranks_the_rolling_contact_cap`, `test_after_the_dead_period_the_rolling_cap_answers_instead`).

**Fixes applied to `implementation/`:** none. All four failures traced to the test layer; no PRD-required check was weakened and no endpoint, field, or side effect was added.

**Iteration 2 (verification):** 8/8 rounds, 118/118 passed each, ~240 s per round. No flaky or load-induced failures observed in either iteration.

Note: `workspace/implementation/results.{1..8}.json` are the sweep's own per-round outputs (the location the runner command specifies) and remain on disk if you want to re-inspect them. `worklog.md` was not touched.

**Orchestrator verification of sweep artifacts:** independently re-read all eight `workspace/implementation/results.{1..8}.json` with `json.load`; every round reports `passed=118 total=118 failed=0`, and all eight files carry a fresh mtime of 21:51 UTC from the final sweep. The clean-sweep claim is confirmed against on-disk evidence, not taken on the subagent's word.

**Step 8 skip decision:** NOT skipped. Step 7 ran 2 iterations and applied 3 test-layer changes (1 partial-coverage assertion removal, 2 `test_suite/` fixes), which mark PRD-silence sites even though `implementation/` needed 0 fixes. Step 8 runs with those items as its focus list.

## Step 8: Finalize PRD — 2026-09-04T22:01:00.000Z

Subagent summary (verbatim):

Both edits are in place. Verified with `diff` — two single-line revisions, no structural changes.

## Line counts
- `PRD.md`: 523 lines; `PRD_FINALIZED.md`: 523 lines — 0% line delta (2 lines revised in place, no insertions/deletions).

## Changes

- **§3.5 (roster-slot release)** — revise — `release_note` is now stated to be a request-only input that the server accepts and discards, with the slot representation carrying no `release_note` field at all — `implementation/routes_c.py:398` (`opt_str(ctx.body, "release_note", None, 1, 500)`, return value never stored) + `implementation/serialize.py:72-80` (`roster_slot` field spec omits `release_note`; `dump` emits spec fields only).
- **§2.4 (datetime serialization)** — insert — one sentence pinning that a datetime input must carry a time component; a bare `YYYY-MM-DD` value where a datetime is expected is `ERR_INVALID_REQUEST` (rung 5) rather than being coerced to midnight — `implementation/store.py:79-82` (`_ISO_RE` requires `[Tt ]HH:MM:SS`), `implementation/http_util.py:248-259` (`req_dt`/`opt_dt` -> `ERR_INVALID_REQUEST`).

No edit was made for the third Step 7 item (`A.data_of(accepted, 201)`): PRD §4 already fixes 201 for creation and `implementation/routes_d.py:129` returns `created(...)` for `POST /matches` — a pure fixture bug.

## Per-edit pre-edit search log

**Edit 1 — `release_note`**
- (a) Subject: the optional `release_note` on `POST /roster-slots/{slotId}/release`, and more generally whether optional action-endpoint notes become persisted/serialized slot fields.
- (b) Enumerated/read: `grep -rn "release_note"` across `implementation/` (single hit, routes_c.py:398); the full release handler `routes_c.py:391-404`; the sibling slot writers `verify_enrollment` (routes_c.py:309-349) and `verify_academics` (routes_c.py:352-388) to confirm no note field enters the slot record; `serialize.py` in full (`roster_slot` spec, `dump`, `SPECS` for every other kind); `grep -rn "withdrawal_note|decision_note|investigation_note|appeal_note|info_request_note|reason_note|dispute_note"` to confirm the discard-the-note pattern is the house rule and that title-approval's `decision_note` (routes_b.py:299-317, serialize.py:47) is the sole persisted note — so wording had to stay confined to `release_note` and not generalize about notes.
- (c) Adjustment: scoped the new clause to this one field ("That note is a request-only input") instead of a general claim about optional notes, since `decision_note` on title approvals *is* persisted and would have been mis-described by a universal sentence. Also avoided asserting a length bound so as not to over-determine beyond the Step 7 subject.

**Edit 2 — datetime input shape**
- (a) Subject: what string shapes are accepted for any datetime-typed input anywhere in the API (triggered by the dead-period fixture fix).
- (b) Enumerated/read: `grep -rn "req_dt|opt_dt|parse_datetime"` across `implementation/` — every datetime input funnels through one parser: district `recruiting_dead_period_start`/`_end` (routes_a.py:62-63), clock `current_utc` (routes_a.py:283), season `registration_opens_at`/`registration_closes_at`/`roster_lock_at`/`regular_season_end_at` (routes_b.py:332-336), match `scheduled_start_at` (routes_d.py:75), broadcast `broadcast_start_at`/`broadcast_end_at` on both the `REGISTER` and non-`REGISTER` branches (routes_d.py:403-411); `http_util.py:248-259` (`req_dt`/`opt_dt` -> `_bad` -> `ERR_INVALID_REQUEST`); `store.py:79-119` (`_ISO_RE`, `parse_datetime`); `store.py:120-131` (`parse_date`) and `req_date`/`opt_date` to confirm the four pure-date fields use a separate, unaffected parser; `serialize.py:14-15` confirming the dead-period bounds serialize as `dt`.
- (c) Adjustment: the sentence asserts only the *missing time component* case. Wording deliberately does not claim the input must match `YYYY-MM-DDTHH:MM:SS.mmmZ`, because `parse_datetime` also accepts a space separator, an omitted or arbitrary-width fractional part, and `+HH:MM`/`-HHMM` offsets; a stricter phrasing would have become a new mismatch on those off-Step-7 paths.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly two in-place line revisions (line 94 §2.4 datetime input shape, line 283 §3.5 `release_note`); `cmp` reports the files DIFFER, so Step 8 genuinely ran rather than emitting a byte-identical copy.

**Step 9 plan:** run as three sequential passes over one shared `PRD_COMPLETED.md`, partitioned by implementation module, because a single subagent cannot exhaustively scan a 3,573-line implementation against a 523-line PRD inside one output budget. Pass 1 does the `cp PRD_FINALIZED.md PRD_COMPLETED.md` and covers the infrastructure + domain core; passes 2 and 3 must NOT re-copy (that would discard the prior pass's edits) and each covers a disjoint set of route modules.

## Step 9: Complete PRD — 2026-09-04T22:32:00.000Z

Run as three sequential passes over one shared `PRD_COMPLETED.md`, partitioned by implementation module (pass 1 owned the `cp`; passes 2 and 3 edited in place and were explicitly forbidden from re-copying). Combined: **61 edits — 53 ambiguity-pins, 8 mismatch-revisions.**

### Pass 1 — infrastructure + domain core (app.py, store.py, http_util.py, errors.py, serialize.py, guards.py, domain.py)

Subagent summary (verbatim):

All 23 edit sites are on disk (22 in-paragraph revisions plus one added catalogue row).

**Counts:** 20 ambiguity-pins, 3 mismatch-revisions.

- §2.1 — revise — mismatch — an empty `X-User-ID`/`X-User-Role` header counts as absent (`ERR_UNAUTHENTICATED`), not as a present value — `http_util.py:94`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alphanumeric chars — `http_util.py:28-29`
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, so it is identical for every request at one clock value — `http_util.py:33`
- §2.2 — insert — ambiguity — every declared field is always present; a null-valued field is emitted as JSON `null`, never omitted — `serialize.py:144-154`
- §2.3 — insert — ambiguity — non-integer / empty `limit`/`offset` are `ERR_INVALID_REQUEST`; leading sign and whitespace tolerated — `http_util.py:109-134`
- §2.3 — insert — ambiguity — `created_at` ties (routine under a static logical clock) break by creation order via a stable sort — `store.py:235-237`
- §2.4 — insert — ambiguity — the store is empty at boot; nothing is seeded — `store.py:43-46`
- §2.4 — insert — ambiguity — >3 fractional digits truncate (not round) to ms; numeric offsets accepted and converted; missing zone read as UTC; `T` or space separator — `store.py:86-117`
- §2.5 — revise — **mismatch** — `version` advances once per **request** per record, not once per write; a record created by the request stays at 1 through later cascades; a no-op write moves neither `updated_at` nor `version` — `store.py:192-218`, `domain.py:66-75`
- §2.7 rung 3 — insert — ambiguity — ownership passes vacuously on an unresolvable path so rung 4 reports the 404 — `guards.py:1-19`
- §2.7 rung 5 — insert — **mismatch** — explicit `null` = absent; booleans rejected for int/number; precision-carrying numbers rounded before range test; empty body = `{}`; an unparseable / non-object body is rejected *before* ownership and path existence — `http_util.py:74-83, 159-231`
- §2.8 — insert — ambiguity — all four precision regimes emit JSON **numbers** with no fixed width (`2.0`, `6.0`, `100.0`); credit counts are outside all regimes and are echoed unrounded — `store.py:178-182`, `serialize.py:119-128`
- §2.10 — insert — ambiguity — filters are exact string equality, never enum-validated; unknown query params ignored — `http_util.py:137-149`
- §3.2 — insert — ambiguity — `standing_basis_applied` stays null until an evaluation produces an `effective_gpa` — `domain.py:185-194`, `routes_b.py:96`
- §3.5 — insert — ambiguity — `enrollment_document_ref` and `verified_birthdate` are persisted on the slot and appear in its representation — `serialize.py:72-80`
- §3.5 — insert — ambiguity — all other free-text `*_note` inputs are accepted and discarded; only a title approval's `decision_note` persists — `serialize.py:96-104`
- §3.7 — insert — ambiguity — the memory of what a match previously credited is server-side only, not a match field — `domain.py:459`
- §3.8 — insert — ambiguity — `suspension_reason` precedence when several triggers hold: roster minimum, then fair-play sanction, then integrity floor — `domain.py:692-700`
- §3.8 AFFIRM — insert — ambiguity — disqualification acts only from `COMPETING`/`SUSPENDED` and also forfeits unplayed matches — `domain.py:800-806`
- §3.8 OVERTURN link 5 — insert — ambiguity — `winner_team_id` also cleared and both `*_points_awarded` return to 0; restoration reaches only matches forfeited by *this* case's suspension — `domain.py:479-491, 536-551, 777-786`
- §3.9 — insert — ambiguity — the head-to-head tied group is the maximal run sharing one `seed_points`, fixed by the first key and never narrowed — `domain.py:636-661`
- §3.9 — insert — ambiguity — per-event scope of `seed_stale` (two participants / one team / whole season) and `seeding_state` only moves from `SEEDED` — `domain.py:315-332`, `routes_d.py:227,269,380`, `routes_c.py:226`
- §4 + §5 — insert — **mismatch** — trailing slashes tolerated; unknown path *and* unsupported method both answer 404 `ERR_NOT_FOUND` (never 405); `GET /health` is the one non-envelope response; `ERR_NOT_FOUND` added to the §5 catalogue at 404 — `app.py:22, 30-47`, `errors.py:86`

**Verified clean (no change needed):** the full 63-rung error-id -> HTTP status map in `errors.py` matches the §5 table entry-for-entry (only `ERR_NOT_FOUND` was missing); all 11 serializer field lists are otherwise fully declared in §3; pagination `has_more`/`total_count`, integrity scoring, clean-conduct credit, sanction selection, entry-fee per-line rounding, scholarship four-step projection, seed-point variants, server-pool half-open probing, and broadcast closed-interval buffering all already pinned uniquely.

**Line/char counts:** `PRD_FINALIZED.md` 523 lines / 108,746 bytes -> `PRD_COMPLETED.md` 524 lines / 115,537 bytes.

### Pass 2 — routes_a.py, routes_b.py, routes_c.py

Subagent summary (verbatim):

All 23 patches applied cleanly; the document is structurally intact (27 headings identical to `PRD_FINALIZED.md`, pass 1's `api_request_id` / per-request `version` / `ERR_NOT_FOUND` material all still present).

**Counts:** 20 ambiguity-pins, 3 mismatch-revisions (23 `Edit` calls, no `Write`, no `cp`).

Mismatch-revisions
- **§2.4** — revise — pure-date field list said "Four fields"; a roster slot's `verified_birthdate` is a fifth (`serialize.py:77` emits it as `date`, `routes_c.py:314` parses it with `req_date`). Now "Five fields", naming it.
- **§3.5, axis two** — revise — PRD had the standing evaluation *writing* `effective_gpa`/`academic_standing`/`standing_basis_applied` before the ineligible/probation refusals. Impl uses a pure `evaluate_standing` for the guards and only calls `apply_standing` after every check passes, so a refused verification persists nothing (`routes_c.py:366` vs `:376`). Revised to pin the pure-computation-then-persist order.
- **§3.9, recruiting contacts** — revise — PRD ordered the showcase check *before* the district dead-period check; impl checks the dead period first (`routes_b.py:211` before `:213`), which is what §2.7's rungs 50 < 60 already imply. Reordered the narrative to blackout -> showcase -> rolling cap and stated that a never-nominated student inside a blackout still hears `ERR_RECRUITING_DEAD_PERIOD`.

Ambiguity-pins
- §2.4 — insert — clock endpoint: `current_utc` sole required field, answers 200 with empty `data` rather than echoing the clock — `routes_a.py:283,287`
- §3.2 — insert — `background_check_expires_on` optional on `CERTIFY` (omitted preserves existing); discarded on `SUSPEND`; no from-state precondition, action repeatable from any status — `routes_a.py:209-217`
- §3.2 — insert — a null `background_check_expires_on` counts as lapsed, drawing `ERR_COACH_BACKGROUND_CHECK_EXPIRED` — `routes_c.py:69`
- §3.2 — insert — student creation opens the shift register and scholarship block: term/`effective_gpa` fields null, `nominating_team_id` null, both award money figures 0 — `routes_b.py:89-104`
- §3.2 — insert — posting bounds: `term_label` 1–120, `term_gpa` 0.000–4.000 at three decimals, `term_credits` unbounded above and never rounded — `routes_b.py:130-132`
- §3.2 — insert — `term_credits` <= 0 -> `ERR_INVALID_REQUEST` — `routes_b.py:133`
- §3.2 — insert — the ineligible-posting sweep skips `CLEARED` slots but does hit already-`RELEASED` ones (reason written, participation stays `RELEASED`) — `routes_b.py:151-157`
- §3.3 — insert — `AthleticDirector` ownership compares `X-User-ID` to `requested_by_school_id`; body FKs checked district -> title -> school — `routes_b.py:246,251-256`
- §3.3 — insert — `decision_note` 1–500 chars; omitted note preserves the stored one rather than nulling it — `routes_b.py:299,316`
- §3.4 — insert — season creation applies no cross-field consistency test (window ordering, `min_starters` vs `max_starters`) — `routes_b.py:332-341`
- §3.4 — insert — `to_status` enum excludes `DRAFT`; naming it is `ERR_INVALID_REQUEST`, not a stage error — `routes_b.py:391`
- §3.5 — insert — team-creation ownership FK differs by role (`Coach`->`coach_id`, `AthleticDirector`->`school_id`); body FKs checked season -> school -> title -> coach — `routes_c.py:83-101`
- §3.5 — insert — every team competitive counter opens at 0, `seed_points` 0.0000, `seed_position` null, `seed_stale` false — `routes_c.py:125-136`
- §3.5 — insert — slot body FKs checked team before student; the five listed conditions are evaluated in listing order — `routes_c.py:242-262`
- §3.5 — insert — fresh slot's five axis figures (`enrollment_document_ref`, `verified_birthdate`, `age_at_cutoff`, `standing_at_verification`, `effective_gpa_at_verification`) all null; roll-up recompute bumps the *team's* version while the slot stays at 1 — `routes_c.py:271-281`
- §3.5 — insert — `enrollment_document_ref` 1–200 chars, `verified_birthdate` a required pure date; plus a general clarifier that §3 condition lists are by subject matter and §2.7's ladder fixes precedence — `routes_c.py:313-314`, `routes_c.py:300`
- §3.5 — insert — axis one has no from-state guard; re-verifying overwrites the document ref, birthdate, age and verifying officer — `routes_c.py:309-345`
- §3.5 — insert — axis two has no from-state guard either; student `version` bumps unconditionally; clearing academics never clears an existing `ineligibility_reason`, so a `BLOCKED`->`CLEARED` slot stays `INELIGIBLE` — `routes_c.py:377-385`
- §3.5 — insert — every discarded free-text note (and the persisted approval note) is shape-checked at 1–500 chars — `routes_c.py:211,398`
- §3.9 — insert — a seeding run answers with the updated season, not the ordered team list — `routes_b.py:434`

**PRD_COMPLETED.md after pass 2:** 524 lines, 123,475 chars (was 524 / 115,537 at pass 1 hand-off — no lines added or removed, all edits in-paragraph, no new sections).

One note for pass 3: my §3.5 clarifier states generally that §3's condition lists are ordered by subject matter and that §2.7's ladder is what fixes reported precedence. That is consistent with routes_d/e as I spot-checked them, but pass 3 should confirm it holds for the match and fair-play handlers it owns.

### Pass 3 — routes_d.py, routes_e.py (final pass)

Subagent summary (verbatim):

All 15 patches landed and the document is intact.

**Files scanned exhaustively:** `routes_d.py` (449 lines, all 10 handlers), `routes_e.py` (237 lines, all 7 handlers).

**Counts:** 15 patches — 13 ambiguity-pins, 2 mismatch-revisions.

- **§3.5** — revise — mismatch — the pass-2 clarifier claimed §2.7's ladder universally fixes reported precedence; qualified it with the one deviation (result-report body-level ownership) so the claim is no longer false globally — `routes_d.py:191-195`
- **§3.7 ¶scheduling** — insert — ambiguity — body-FK check order pinned: season -> participants, so `ERR_SEASON_NOT_FOUND` precedes `ERR_TEAM_NOT_FOUND` — `routes_d.py:78-84`
- **§3.7 ¶scheduling** — insert — ambiguity — full initial figures of a newly scheduled match (report pairs, game counts, confirm/deadline, dispute and forfeit fields, all three broadcast-window fields null; `spectator_strikes` and both `*_points_awarded` at 0) — `routes_d.py:96-128`
- **§3.7 ¶server-config** — insert — ambiguity — `region_code` and `patch_version` are required strings of 1–40 characters — `routes_d.py:148-149`
- **§3.7 ¶result reports** — insert — ambiguity — game counts are required integers >= 0 with no upper bound; `expected_match_version` a required unbounded integer — `routes_d.py:181-183`
- **§3.7 ¶result reports** — insert — **mismatch** — the reporting-team ownership test is the one `ERR_NOT_RESOURCE_OWNER` decided *below* its rung: rung 3 only checks the coach coaches a participant; the body-level test runs after the version, stage, match-state and participation rungs — `routes_d.py:194-195`
- **§3.7 ¶result reports** — insert — ambiguity — re-reporting only reachable while `play_status` is `SERVER_READY`; once `PLAYED` (confirmed or contested) a further report is `ERR_INVALID_MATCH_STATE` — `routes_d.py:189-190, 212`
- **§3.7 ¶finalize** — insert — ambiguity — overrides are integers >= 0 — `routes_d.py:238-239`
- **§3.7 ¶finalize** — insert — ambiguity — the presence rule keys on `result_status` alone, never `play_status`: overrides ignored from `AWAITING_REPORTS`/`PARTIALLY_REPORTED`; an already-`FINALIZED`/`FORFEITED` decided match still reports the forbidden-override 400 ahead of the 409; the non-adjudicating branch also leaves seeding freshness untouched — `routes_d.py:240-276`
- **§3.7 ¶dispute filing** — insert — ambiguity — ownership reaches only as far as participation; `filing_team_id` need not be the acting coach's own team (unlike result reports) — `routes_d.py:299-311`
- **§3.7 ¶dispute actions** — insert — ambiguity — `ACCEPT_REVIEW`/`REQUEST_INFO`/`RESUME_REVIEW` neither require nor forbid the corrected counts; a supplied pair is accepted and ignored — `routes_d.py:360-368`
- **§3.7 ¶UPHOLD** — insert — ambiguity — corrected counts are integers >= 0 — `routes_d.py:360-361`
- **§3.8 ¶broadcast REGISTER** — insert — ambiguity — start/end are never compared; an end at or before the start is accepted and conflict-tested as supplied — `routes_d.py:403-404`
- **§3.8 ¶case creation** — insert — ambiguity — no owner scoping on the charging coach; body-FK order `team_id -> subject_student_id -> subject_match_id`, existence sweep covering even the field the pairing rule forbids (`ERR_MATCH_NOT_FOUND` beats `ERR_SUBJECT_REFERENCE_MISMATCH`) — `routes_e.py:48-70`
- **§3.8 ¶SUSTAIN** — insert — ambiguity — the `MATCH_BROADCAST` effect is conditional on `broadcast_status == LIVE`; otherwise the case sustains, integrity and sanction still run, and no strike is recorded — `routes_e.py:170-177`
- **§3.8 ¶appeal** — insert — ambiguity — `appeal_grounds` is a required string of 1–1000 characters and is persisted, unlike the discarded notes — `routes_e.py:190`
- **§3.8 ¶AFFIRM** — insert — ambiguity — disqualification leaves `suspension_reason` as it stood — `domain.py:800-806` via `routes_e.py:216-217`
- **§3.8 ¶OVERTURN** — insert — ambiguity — the fourth (team-restoration) link is evaluated even when links two and three were skipped because another sustained case keeps the student sanctioned — `routes_e.py:224-228`, `domain.py:740-748, 767-776`

Verdict on the pass-2 carry-over clarifier: it did **not** hold universally. Every other routes_d/e handler matches the §2.7 ladder (season stage before match state; rung-8 presence before from-state; match state before broadcast state; case from-state before segregation of duties; body FK existence before discriminator agreement). The single contradiction is `report_result`, where `ERR_NOT_RESOURCE_OWNER` for the body-named reporting team is raised *after* the version, season-stage, match-state and participation checks rather than at rung 3. The §3.5 clarifier was revised to carve out exactly that deviation and it is documented inline in §3.7, so the universal claim is now true as written.

Final integrity check: `PRD_FINALIZED.md` 523 lines / 108,746 chars; `PRD_COMPLETED.md` 524 lines / 128,228 chars. `cmp -s` -> DIFFERING. All five headings present. `tail -5` ends cleanly on the §5 catalogue. Pass-1 marker `api_request_id` -> 4 hits; pass-2 marker `Five fields` -> 2 hits.

### Orchestrator verification of Step 9

- `wc`: PRD.md 523 / 108,350 — PRD_FINALIZED.md 523 / 108,746 — PRD_COMPLETED.md 524 / 128,228 (+19,482 chars, ~+17.9% over PRD_FINALIZED).
- `cmp -s PRD_FINALIZED.md PRD_COMPLETED.md` -> DIFFERS, so the scan genuinely ran (a byte-identical Step 9 output would mean the passes never executed).
- All five top-level headings present at lines 3 / 11 / 221 / 383 / 448; document ends on the completed §5 catalogue row `| ERR_NOT_FOUND | 404 |` — a real section boundary, not mid-sentence.
- Pass-1 and pass-2 markers both still hit (`api_request_id` x4, `Five fields` x2), confirming passes 2 and 3 edited in place rather than re-copying over prior work.
- `grep -ci "harder than expert" PRD_COMPLETED.md` = 0 — the Step 2 difficulty directive never reached any PRD variant.
- Step 9 changed documentation only; `implementation/`, `test_suite/` and `test_helpers/` were untouched, so the verified 8/8 x 118/118 sweep from Step 7 remains valid.

## Pipeline complete — 2026-09-04T22:33:00.000Z

All nine steps finished. Final state: 118 tests, 8/8 sweep rounds green (118/118 each), PRD_COMPLETED.md written.
