# Worklog — task_2292_post_election_audit_recount_administration

## Step 1: Create task directory — 2026-09-01T14:45:59.000Z

Created `tasks/task_2292_post_election_audit_recount_administration/` and `tasks/task_2292_post_election_audit_recount_administration/workspace/` (directory name pre-allocated by the invoker; no index scan performed).

## Step 3: Copy shared files — 2026-09-01T14:46:10.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2292_post_election_audit_recount_administration/workspace/INSTRUCTION.md` (1424 bytes). Run out of order (before Step 2) since it has no dependency on the scaffold.

## Step 2: Generate scaffold — 2026-09-01T16:51:28.000Z

All three artifacts are complete and pass the lint gate.

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(Coverage line from the same run: 70 endpoints declared, 14 entities declared, 24 §1.8 instances scanned, 73 §1.9 instances scanned, 1386 calls scanned.)

## Generated files
- `/home/ubuntu/github/CodingPRD/tasks/task_2292_post_election_audit_recount_administration/SCAFFOLD.yaml` (3630 lines, §1.0–§1.7 only — no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_2292_post_election_audit_recount_administration/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2157 lines, single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_2292_post_election_audit_recount_administration/SCAFFOLD_CORNER_DESIGN.yaml` (6047 lines, single key `scaffold_corner_design`)

## SCAFFOLD.yaml counts
| Section | Count |
|---|---|
| Entities (§1.1) | 14 |
| State machines (§1.2) | 13 |
| Concurrency rules (§1.2) | 3 |
| Calculations (§1.3) | 9 |
| Validations (§1.4) | 48 (fully priority-ordered, 1–48) |
| Endpoints (§1.5) | 70 |
| Errors (§1.6) | 79 |
| Roles (§1.5) | 7 |

`complexity_profile`: `difficulty_level: expert_plus`; primary archetype compliance_audit + secondary multi_party_negotiation; five cross-cutting layers (optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, derived_field_reconciliation); flat topology, cyclic state machines, `segregation_of_duties` role model, immediate consistency. Two roles are entity-backed (`TallyTeamLead` → TallyTeam, `Observer` → ObserverCredential); Recount carries two independent state dimensions (workflow `status` + money `deposit_status`); a logical clock endpoint (`POST /_clock/set_current_utc`) makes every deadline/window boundary deterministic.

## Design instance counts
- **§1.8 difficulty design: 24 instances across all 9 rule blocks** — dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 3, compensating_invariant 3.
- **§1.9 corner design: 87 instances across all 9 guide sections** — entities 12, state_machines 17, calculations 12, validations 14, endpoints 7, errors 11, rbac 8, cross_cutting_complexity_layers 5, consistency_model 1. 73 carry full `test_recipe`s; 14 are `excluded_because` stubs citing a §1.8 instance by name (all citations resolve; all 111 instance names globally unique).

Every recipe is fully executable: structured `setup_api_calls`/`trigger` with `call`/`payload`/`as`/`as_user_id`/`captures`, all placeholders closed by earlier captures, pre-computed literal asserts (e.g. `round_measure == 0.0050` reached only cumulatively over 2000 ballots, `margin_pct == 0.1438` half-up at the 4th decimal, deposit `130000`/floor-lifted `100000`, refund conservation `deposit_paid == refunded + forfeited + admin_retained`), and no forbidden concurrency vocabulary anywhere.

## Step 4: Generate PRD — 2026-09-01T17:06:43.000Z

PRD generated and audited.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2292_post_election_audit_recount_administration/workspace/PRD.md` — **579 lines**, ends at §5 with no audit footer.

**Section structure**

- `# Post-Election Audit Recount API — Product Requirements Document`
- **§1 Introduction** (3 paragraphs: the coordination problem, the four intertwined processes, the two design commitments — reproducibility and immediate consistency)
- **§2 Global Specifications & System-Wide Principles** — 11 subsections: 2.1 User and Role-Based Access Control (7 roles, 5 opaque / 2 entity-backed) · 2.2 API Response Structure (**verbatim** paste, byte-identical to `section-2.2-response-structure.md`) · 2.3 Pagination (+ all per-endpoint sort orders) · 2.4 Resource Identity, System Fields and the Logical Clock (incl. the `CustodyEvent` `common_fields: false` exception and the `2026-08-01T00:00:00Z` default clock) · 2.5 Path Resolution and Collection Filters (14-name 404 vocabulary + every filter) · 2.6 Stale-Version Guards on Three Contested Writes · 2.7 Vote Arithmetic, Measures and Integer Cents · 2.8 Immediate Cascade Consistency · 2.9 The Order of Refusal (explicit 48-tier ordered list) · 2.10 Chain of Custody as an Append-Only Record · 2.11 Observer Transparency and Segregation of Duties
- **§3 Business Logic & Workflows** — 9 subsections: 3.1 Elections, Contests and the Canvass · 3.2 Physical Custody · 3.3 Planning an Audit (3 sizing variants) · 3.4 Seed Ceremony, Rounds and Reproducible Batch Selection (LCG draw, full audit + round lifecycles) · 3.5 Bipartisan Tally Teams and the Hand Count (2 measure variants) · 3.6 Discrepancy Findings, Escalation and Corrective Actions · 3.7 Voter-Intent Adjudication · 3.8 Recounts (deposit pricing, 3 refund variants, conservation invariant) · 3.9 Timeline Projection, Observer Access and the Public Report (9 ordered steps)
- **§4 Endpoint Definitions** — 4-column table (Method, Path, Description, Authorized Role(s)), **70 rows**
- **§5 Error Code Catalogue** — 2-column table (Error ID, HTTP Status Code), **79 rows**

**Coverage audit results**

```
Field coverage check:
- entities[].fields: 150 required, 150 present, 0 missing
- endpoints[].request_body: 72 required, 72 present, 0 missing
- endpoints[].query_params: 26 required, 26 present, 0 missing
Status: PASS
```
(164 unique identifiers; verified twice — once against the whole document, once restricted to §1–§3 so no identifier survives only inside the §4/§5 tables. All enum members and all 30 calculation constants also verified present.)

```
Rule coverage check:
- validations[] with priority: 48 checked, 48 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 70 checked, 70 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed, 0 missing
- validations[] conditions: 48 checked, 48 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 70 checked, 70 expressed, 0 missing
- entities[].fields[] structured content: 14 checked, 14 reconstructible from prose, 0 missing
- sibling-branch symmetry: 14 groups checked, 14 with equal prose density, 0 asymmetric
Status: PASS
```
(All 79 error ids appear in the document; the 13 `*_NOT_FOUND` ids are catalogued in §2.5 and referenced by tiers 4–5 of §2.9.)

```
Path purity check (§3 only):
- backtick tokens scanned: 1026
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```
(Also zero unbackticked slash-paths and zero bare method words anywhere in §3.)

No-pseudocode scan: zero occurrences of `==`, `>=`, `<=`, `+=`, `min(`, `max(`, `ceil(`, `round_half_up`, `abs(` or of any fuzzy hedge ("approximately", "roughly", "conservatively", "etc.") in the document.

**Three scaffold inconsistencies found; all resolved in favour of §1.3 (the designated formula authority), and worth flagging back to the scaffold author:**
1. `Contest.automatic_recount_required`'s field description implies a single 0.5 threshold, but `recount_trigger_evaluation` specifies 0.5000 for `CANDIDATE` and 0.2500 for `MEASURE`. The PRD documents the type-dependent thresholds.
2. `Recount.ballots_in_scope`'s field description says `Contest.ballots_cast` for `FULL_CONTEST`, but `recount_deposit_assessment` says the sum of `ballot_count` over every `BallotBatch` of the contest. The PRD documents the calculation's version (these differ whenever batched ballots are below `ballots_cast`, which validation 36 permits).
3. `Recount.final_margin_votes`'s description ("after folding `final_votes` into the contest totals") versus step 2 of `recount_cost_and_refund` (rank `final_votes` directly). Reconciled by stating that `reported_votes` is replaced by the recounted totals and the margin is taken over those totals, ranked by votes descending then name ascending.

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced, and no sibling task directory was accessed.

## Step 5: Generate unit tests — 2026-09-01T18:45:35.000Z

Queue B is now complete; the suite is finished and verified.

## Files written

**Stage 1 — `/home/ubuntu/github/CodingPRD/tasks/task_2292_post_election_audit_recount_administration/test_helpers/`** (9 files, generated earlier, unchanged): `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `constants.py`, `factories.py`, `test_users.py`, `assertions.py`, `fixtures.py`.

**Stage 2 — `.../test_suite/`** (`conftest.py` + 17 test modules):
- Queue A (depth): `test_01_audit_planning_and_seed_ceremony.py` … `test_08_recount_workflow_and_money_dimension.py`
- Queue B (breadth): `test_09_entity_shape_defaults_and_identity.py`, `test_10_lifecycle_transitions_and_cascades.py`, `test_11_derived_calculations.py`, `test_12_validation_rules_and_windows.py`, `test_13_endpoint_behaviours.py`, `test_14_error_vocabulary_and_precedence.py`, `test_15_role_based_access_control.py`, and new this session `test_16_cross_cutting_concurrency_and_rollups.py` (3 tests), `test_17_immediate_consistency.py` (1 test).

## Test counts

| Queue | Instances | Tests emitted |
|---|---|---|
| A — `SCAFFOLD_DIFFICULTY_DESIGN.yaml` §1.8 | 24 / 24 non-stub covered | 62 functions (65 collected, one `parametrize` in `test_01`) |
| B — `SCAFFOLD_CORNER_DESIGN.yaml` §1.9 | 72 / 73 non-stub covered | 73 functions |
| **Total** | | **135 functions, 138 collected** |

Queue B per section: entities 13, state_machines 13, calculations 7, validations 11, endpoints 7, errors 10, rbac 8, cross_cutting_complexity_layers 3, consistency_model 1.

## Verification performed

- Every test carries exactly one `Design:` line (135 tags / 135 functions); all tags resolve to real instance `name:` values; zero tags point at the 14 `excluded_because:` stubs; zero `skip`/`skipif`/`xfail` markers; the word "scaffold" appears nowhere in the suite.
- PRD-citation pass: all 235 quoted fragments across all 17 modules machine-checked verbatim (whitespace-normalized) against `workspace/PRD.md` — 0 failures. This pass caught and fixed two pre-existing near-quotes: a paraphrased recount-initial-state sentence in `test_10` (now the real §3.8 sentence plus the §3.8 pricing sentence that grounds `deposit_status == PENDING`) and a bracketed §2.7 elision in `test_11`.
- `py_compile` clean on all modules, `pyflakes` clean, `pytest --collect-only` collects 138 tests.

## Instances skipped (gaps left as gaps)

1. `Corner/errors/entity_backed_roles_are_unauthenticated_without_a_resolvable_user_id` — asserts `ERR_TALLY_TEAM_NOT_FOUND` (404) for an unresolvable `TallyTeamLead` `X-User-ID`, but PRD §2.9 tier 6 makes that failure `ERR_TALLY_TEAM_MISMATCH` (403) and §2.1 names a not-found error only for the observer credential. The asserted outcome is not uniquely derivable from the PRD, and weakening is forbidden.
2. The 14 `excluded_because:` stubs in queue B were not translated (by design — each defers to a queue-A instance).

One design/PRD conflict was resolved in favour of the PRD rather than skipped: `Corner/rbac/counters_may_not_adjudicate_the_ballots_they_counted` expects the tally to stay `PENDING_ADJUDICATION` after its last referral is adjudicated, whereas §3.7 uniquely derives a return to `SUBMITTED`; the test asserts `SUBMITTED` and cites that sentence, keeping the instance's central segregation-of-duties claim (fully PRD-covered) under test.

## Step 6: Generate implementation — 2026-09-01T18:45:35.000Z

Implementation is complete and verified.

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_2292_post_election_audit_recount_administration/workspace/implementation/` (22 files, ~4,480 lines of Python):

**Core**
- `app.py` — app factory, 9 blueprint registrations, `ApiError`/404/405/500 handlers, `app.run(host="0.0.0.0", port=int(os.environ["PORT"]), threaded=True)`, `strict_slashes = False`
- `db.py` — in-memory `Store` with the 14 entity dicts, logical clock (default `2026-08-01T00:00:00Z`), id/sequence generators, `insert`/`touch`/`set_fields`/`serialize`/`sorted_rows`
- `errors.py` — `ApiError`, `fail()`, error_id → HTTP status map (~80 codes)
- `middleware.py` — 7 roles, `authenticate()`, `guard(roles)`
- `response.py` — §2.2 envelope (`meta`/`response_type`/`data`, pagination meta)
- `validate.py` — typed field extractors, pagination, filter coercion
- `requirements.txt`, `start.sh`

**services/** — `calc.py` (all 9 calculations, Decimal ROUND_HALF_UP/CEILING, LCG sampling), `domain.py` (cascade/roll-up engine, state machines, termination, discrepancy sync)

**routes/** — `common.py` (lookup/list/paged/filter helpers) plus `elections.py` (10), `custody.py` (8), `audits.py` (15), `teams.py` (5), `tallies.py` (6), `findings.py` (10), `interpretations.py` (4), `recounts.py` (8), `observers.py` (4)

## Verification

- **70 endpoints registered** — matches the SCAFFOLD count exactly (enumerated programmatically from `app.url_map`).
- **`bash start.sh` boots and serves on `$PORT`** — confirmed on `PORT=10457`; `start.sh` does a *guarded* pip install (`if ! python3 -c "import flask"`) then `exec python3 app.py`, so per-test relaunches are fast and can't race on install.
- **In-memory only** — no `sqlite`, no `open()`, no file or JSON persistence anywhere; store starts empty on every boot with zero seeded data.
- Two end-to-end smoke suites both report `FAILURES: 0`, covering the full happy path (election → contest → batches → canvass → audit seed/round/sample → custody retrieve/return → team formation → hand tally → interpretations with board quorum → discrepancy → corrective action → audit close → public report → recount deposit/start/complete/withdraw/deny → clock advance → timeline review → certify) plus ~35 negative cases across the auth, pagination, 404, OCC, state-machine, segregation-of-duties, capacity and deposit tiers.

## Notable findings during verification

- **Real bug fixed** in `services/domain.py`: `LIVE_TALLY_STATES` omitted `PENDING_ADJUDICATION`, so a board adjudication zeroed the audit's `counted_ballots`/`discrepancy_measure` mid-cascade. PRD §3.7 states an adjudication "re-derives the round counters and the audit measure exactly as a submission would", so `PENDING_ADJUDICATION` now counts as live.
- `calc.fnum` made `None`-safe (several nullable fields flow through it).
- Two apparent failures turned out to be correct behaviour: (1) `ERR_NO_UNSAMPLED_BATCHES` when `planned_sample_size` clamps to the *total* batch count (PRD §3.3) but a quarantined batch shrinks the eligible pool — the documented `sample_size_batches` override is the intended escape; (2) reopening a tally VOIDs its discrepancy and re-submission creates a fresh `OPEN` one, matching PRD §3.6's exact-compensation rule.

## Step 7: Run tests and iterate — 2026-09-02T00:17:03.000Z

All 17 test files, 138 tests, 8/8 parallel rounds green. Done.

## Summary

**Iterations run:** 4 full 8-round parallel sweeps this session (plus targeted single-file diagnostic runs). Final state: **8/8 rounds `passed == total` = 138/138**, zero failures, zero errors.

**Tests deleted:** none. No assertion in this suite turned out to rest on a PRD-silent or PRD-underdetermined rule — every failure traced either to a test-side precondition bug or to host-level harness breakage.

**Fixes applied to `test_helpers/`**
- `test_helpers/fixtures.py` — added a `sibling_contests` parameter threaded through `setup_election_with_contest_and_batches` → `setup_canvassed_contest` → `setup_round_one_with_checked_out_batch` / `setup_draft_tally`, so a second contest of the same election is registered **before** the first contest is canvassed. PRD §3.1 requires the election to still be `OPEN` when a canvass is recorded, and the election leaves `OPEN` as soon as every one of its contests reaches `CANVASSED`; three tests were registering a sibling contest afterwards and could then never get past §2.9 tier 14 (`ERR_INVALID_ELECTION_STATE`).
- `test_helpers/fixtures.py` — `setup_canvassed_two_contest_election` now registers both extra contests and their batches before canvassing either, same PRD §3.1 reason.

**Fixes applied to `test_suite/`** (all strengthen or correct fidelity to PRD; none weaken an assertion)
- `test_14_error_vocabulary_and_precedence.py` (`test_four_payload_shapes_share_the_rule_and_no_vote_is_the_one_exception`), `test_15_role_based_access_control.py` (`test_the_recount_and_report_surfaces_admit_their_whole_role_list`), `test_16_cross_cutting_concurrency_and_rollups.py` (`test_a_withdrawal_a_denial_and_two_terminations_return_the_counters_to_zero`) — use the new `sibling_contests` fixture parameter.
- `test_15` — `selection_sequence` corrected from the truncated 3-item list to the full PRD-determined 6-item order `["B-003","B-004","B-005","B-001","B-002","B-006"]`: PRD §3.3 sizing for that 0.3333 % margin clamps `planned_sample_size` to the whole 6-batch pool, and PRD §3.4's LCG run six times from seed `0459231087` yields exactly that order (independently corroborated by `test_13`'s `FULL_DRAW_ORDER`).
- `test_06_escalation_and_timeline_projection.py` — `cumulative_sampled_batches == 3` (was 6): PRD §3.4 counts non-superseded rounds only.

**Fixes applied to `implementation/`:** **none.** The implementation was never modified, never seeded, and remains in-memory only.

**Host-contention workaround (tooling only, outside the deliverable)** — the dominant noise source was ~400 concurrent sweeps from other tasks (load ~400), which made the harness's `lsof -ti:<port> -sTCP:LISTEN` inside `pytest_plugin._kill_port` exceed its hard 5 s timeout: **422 of 422 non-passes in the first completed sweep were that one `subprocess.TimeoutExpired`**. Two decisive findings:
- A fast `lsof` shim on `PATH` (`.logs/bin/lsof`) fixes it, but my earlier version reported only the `/bin/sh -c` wrapper pid; the real listener `python3 app.py` is its **child**, so `kill -9` left the port bound. That produced `Address already in use` on respawn while the orphaned old server kept answering — proven from `/tmp/prd_bench_server_60267.log`, where one server instance served two consecutive tests. That, not any logic defect, was the single genuine-looking `FAILED` (`test_ten_cross_role_attempts_are_all_refused_and_change_nothing`, `assert 2 == 1` on `total_count` of elections: a leaked election).
- The shim now walks its own ancestry, expands descendants, matches `PORT=<port>` in `/proc/<pid>/environ`, and keeps a per-port pid note for orphans: 0.08–0.29 s per call vs 1–25 s for real `lsof`. It touches no test and no implementation file.
- Also used the harness's own documented knobs `_PRD_BENCH_RESTART_POLL_ITERS=180` / `_PRD_BENCH_RESTART_POLL_TIMEOUT=2.0` and `--timeout 200 --test-timeout 60`.

One residual, non-reproducible harness artifact seen once in the penultimate sweep (round 2, 137/138): `requests.exceptions.ConnectionError: RemoteDisconnected` on the fixture's first `POST /elections` — a stale keep-alive socket to the just-killed server, no assertion involved. It did not recur in the final sweep, where all 8 rounds were 138/138.

**Orchestrator verification:** re-read all 8 `results.{1..8}.json` independently — every round reports `passed=138 / total=138, failed=0`.

## Step 8: Finalize PRD — 2026-09-02T00:30:00.000Z

`PRD_FINALIZED.md` written. Two sentence-level edits; everything else kept verbatim.

**Line counts:** PRD.md 579 lines → PRD_FINALIZED.md 579 lines (0.00% line delta; 2 lines revised = 0.35% of lines touched).

**Changes**

- §3.4 "An escalated finding drives the audit to `ESCALATED_FULL_HAND_COUNT`…" — *insert* — the escalation cascade list now says the audit's `cumulative_sampled_batches` is recomputed as the number of drawn-batch rows across its **non-superseded** rounds, so the just-superseded round's batches stop counting (the PRD's escalation list previously named only the timeline fields, leaving "cumulative" open to a monotone-accumulation reading) — `services/domain.py:313,320` via `routes/findings.py:127`.
- §3.9 "**The public report.**" — *revise* — pins that `selection_sequence` **and** `discrepancy_count` come from the audit's reported round (latest non-superseded round by `round_number`; the highest-numbered round when all are superseded; empty list / 0 when no round exists), and that the remaining ledger/timeline fields are the audit's own — `routes/audits.py:330,338,342` + `services/domain.py:488-494`.

**Per-edit pre-edit search log**

1. Edit 1 — (a) subject: `cumulative_sampled_batches` (definition, every recomputation trigger, and its consumer). (b) enumerated: `grep -rn "cumulative_sampled_batches|recompute_audit_ledger"` → `routes/audits.py:131` (init 0), `:215` (read as the escalation-target subtrahend), `:225` (round creation), `:275` (close), `services/domain.py:303-325` (sole definition, `live_rounds = status != SUPERSEDED`), `:477` (`cascade_round` — tally submit/reopen/adjudication), `:605` (`terminate_audit`), `routes/findings.py:127` (escalate); also read `create_round`/`eligible_pool` (drawn-row creation, previous-round supersession) and `rounds_of_audit`. All eight callsites route through the one definition, so no path is mis-described. (c) adjustment: replaced my first draft's vague "recomputed … as always" with the §3.4 definitional wording ("the number of drawn-batch rows across its non-superseded rounds") so the sentence states the same rule the single helper implements at every trigger, rather than implying an escalation-specific rule; deliberately did **not** add the field to the close/terminate lists (no Step 7 item there, and the existing §3.4/§3.5 definitions already cover them, incl. the drop to zero on termination).
2. Edit 2 — (a) subject: which row supplies each field of `GET /audits/{id}/public-report`. (b) enumerated: `routes/audits.py:309-347` (whole handler, field by field), `services/domain.py:488-494` (`report_round`) and `:483-485` (`latest_live_round`, the sibling selector used for round drawing/escalation — confirmed the report uses the *other* helper with a superseded-fallback), `services/domain.py:59-61` (`rounds_of_audit` order = `round_number` then insertion), `routes/audits.py:263-273` (close: live rounds → `COMPLETE`, so `live[-1]` is the last round), `services/domain.py:600-604` (terminate: non-terminal rounds → `SUPERSEDED`, which is exactly when the fallback branch fires), audit row shape at `routes/audits.py:112-144` (confirmed the audit has **no** `discrepancy_count` field, so that report field can only be the round's), and §2.11's parallel field list (left verbatim — a bare list, no contradiction). (c) adjustment: added the "when every round of the audit has been superseded" fallback clause after seeing that a *terminated* audit — the common report case — has no non-superseded round; without it the sentence would have wrongly implied an empty sequence there. Also scoped `counted_ballots`/`cumulative_net_error_votes`/`discrepancy_measure`/`escalation_level`/`timeline_status` explicitly to the audit to avoid the new round-attribution clause accidentally sweeping them in.

**Items deliberately left unpatched** (PRD already determines them; the Step 7 change was test/fixture-side): the `sibling_contests` fixture threading and `setup_canvassed_two_contest_election` (§3.1 line 211 already requires the election to be `OPEN` at canvass, and line 217 already makes the election leave `OPEN` when the last contest canvasses — `routes/elections.py:320-322`, `services/domain.py:439-450`); the `test_14`/`test_15`/`test_16` fixture-parameter adoptions (same rule); and the 6-item `selection_sequence` *content* itself, which §3.3's clamp (`min(total, max(2, raw))` — `services/calc.py:161`) and §3.4's advance-then-draw LCG (`services/calc.py:180-194`) already determine uniquely.

## Step 9: Complete PRD — 2026-09-02T00:58:23.000Z

Done. `PRD_COMPLETED.md` is written.

## Analysis

`PRD_FINALIZED.md` was already unusually well-pinned (48-tier refusal order, explicit rounding modes, explicit LCG constants), so the residual gaps clustered in four places: (a) **intra-tier ordering** — where §2.9 puts two checks in the same tier and the impl picks one, (b) **error-id attribution** — where §3.x prose says "must be X" without naming which of the twelve invalid-state ids fires, (c) **absent guards** — several operations (quarantine, timeline-review, referral, session-open, corrective-action creation) test far less than the prose implies, and (d) **ledger recomputation semantics** — the impl re-derives round/audit ledgers from scratch everywhere the PRD described increment/decrement, which changes observable behavior in three cases.

Note: the Step 9 subagent reported that `test_helpers/` and `test_suite/` "do not exist in this workspace" — they live at the task root rather than under `workspace/`, so no auxiliary cross-reference was consulted; `implementation/` was the sole authority, which is what the step requires anyway.

## Counts

- `PRD_FINALIZED.md`: **579 lines**, 132,663 chars
- `PRD_COMPLETED.md`: **579 lines**, 145,964 chars — **char delta +13,237**
- 61 lines touched; no sections added, no paragraphs added — every change is an in-paragraph insert or revision
- **46 ambiguity-pins**, **14 mismatch-revisions** (60 total)

## Changes

- §2.1 — revise — ambiguity — the missing-`X-User-ID` 401 fires only when the *acting* role is itself entity-backed (opaque roles never need it); both headers are trimmed — `implementation/middleware.py:48,66-71`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + 20 lowercase alphanumerics; `api_request_timestamp` comes from the wall clock, not the logical clock — `implementation/response.py:12,16-17`
- §2.3 — insert — ambiguity — every ordering breaks ties on a monotonic per-process insertion sequence (the frozen clock makes `created_at` ties routine) — `implementation/db.py:146,181-189`
- §2.4 — insert — ambiguity — a request bumps a given row's `version` at most once, however many writes it performs on that row — `implementation/db.py:151-163`
- §2.4 — insert — ambiguity — clock-set returns a `data` object carrying only `current_utc`, and may move the clock backwards — `implementation/routes/elections.py:84`
- §2.5 — insert — ambiguity — multi-FK bodies resolve in a fixed order (`election_id`→`contest_id`; `audit_batch_id`→`tally_team_id`; `contest_id`→`audit_id`→scope batches) — `implementation/routes/custody.py:56-60`, `routes/tallies.py:88-94`, `routes/recounts.py:145-166`
- §2.5 — insert — ambiguity — a filter on an enumerated field rejects out-of-enum values as `ERR_VALIDATION` at tier 3; the literal `null` matches null fields — `implementation/validate.py:278-283`, `routes/common.py:55-59`
- §2.9 tier 19 — revise — **mismatch** — on recount filing the quarantine test reads only `scope_batch_ids`, so `FULL_CONTEST` is never refused on that ground — `implementation/routes/recounts.py:158-162`
- §2.9 tier 25 — revise — **mismatch** — observer credentialing has no cross-election test at all; removed from the tier's endpoint list — `implementation/routes/observers.py:41-44`
- §2.9 tier 27 — revise — **mismatch** — hand-tally *creation* also validates `counted_votes` keys; added to the tier's endpoint list — `implementation/routes/tallies.py:103`
- §2.9 tier 41 — insert — ambiguity — the pending-count ceiling is tested before the duplicate `ballot_ref` — `implementation/routes/interpretations.py:71-74`
- §2.10 — insert — ambiguity — per-event-type seal bracketing (`INTAKE` null→seal; `AUTHORIZED`/`QUARANTINE` seal→same seal; `CHECK_OUT` seal→null; `CHECK_IN` old→new), `note` null on `INTAKE`/`AUTHORIZED`, and custody events carry no `updated_at`/`version` — `implementation/routes/custody.py:72-80,207-215`, `services/domain.py:551-558`
- §3.1 — revise — ambiguity — canvass tests contest state (`ERR_INVALID_CONTEST_STATE`) before election state (`ERR_INVALID_ELECTION_STATE`), both before candidate/accounting — `implementation/routes/elections.py:318-322`
- §3.1 — revise — **mismatch** — a closed request window is reported *ahead of* an ineligible margin (the prose implied the reverse) — `implementation/routes/recounts.py:168-172`
- §3.1 — revise — **mismatch** — amendment projects only when the deadline actually changes, and only for non-terminal audits; a recount filing against a certified election reports `ERR_CONTEST_NOT_CANVASSED`; team/quarantine/credential work is outside the freeze — `implementation/routes/elections.py:164-178`
- §3.1 — insert — ambiguity — certification's requirements are evaluated in §2.9 order (deadline ahead of discrepancy/equipment), and a non-canvassed contest is `ERR_INVALID_CONTEST_STATE` — `implementation/routes/elections.py:187-204`
- §3.2 — insert — ambiguity — `machine_votes` summing above `ballot_count` is `ERR_VALIDATION` at tier 3, not `ERR_BALLOT_ACCOUNTING_EXCEEDED` — `implementation/routes/custody.py:52-53`
- §3.2 — insert — ambiguity — the bulk `batches` array needs at least one entry — `implementation/routes/custody.py:131`
- §3.2 — revise — ambiguity — retrieval order pinned (drawn-batch state first; `CHECKED_OUT` physical batch → `ERR_INVALID_BATCH_STATE`; then quarantine, then authorization, then seal) — `implementation/routes/audits.py:405-425`
- §3.2 — revise — ambiguity — return order pinned with error ids (`ERR_INVALID_AUDIT_BATCH_STATE`, `ERR_INVALID_BATCH_STATE`, `ERR_INVALID_TALLY_STATE`, then quarantine, then reseal) — `implementation/routes/audits.py:452-470`
- §3.2 — insert — ambiguity — quarantine is unconditional (no election, contest or audit guard; works post-certification); a repeat is `ERR_INVALID_BATCH_STATE` — `implementation/routes/custody.py:194-215`
- §3.3 — revise — ambiguity — out-of-range `prior_error_rate` is `ERR_VALIDATION` (not `ERR_AUDIT_CONFIG_INVALID`), and the field is stored on every audit type defaulting to 0.10 — `implementation/routes/audits.py:84,103-123`
- §3.3 — insert — ambiguity — a newly planned audit's projection fields are null with `timeline_status` `ON_TRACK`; planning runs no projection — `implementation/routes/audits.py:135-140`
- §3.3 — insert — ambiguity — zero registered batches ⇒ `planned_sample_size` 0; a zero margin fraction ⇒ raw batch requirement = whole batch count — `implementation/services/calc.py:137,147-148`
- §3.3 — insert — ambiguity — the additional-batches figure is clamped at zero, and a null `planned_sample_size` yields an escalation target of 0 — `implementation/services/calc.py:169-172`
- §3.4 — insert — ambiguity — an explicit `sample_size_batches` must be ≥ 1, and the pool must be at least as large as the size drawn — `implementation/routes/audits.py:197,220`
- §3.4 — insert — ambiguity — the round row carries its own `sample_size_batches` recording rows actually drawn — `implementation/services/domain.py:530`
- §3.4 — revise — ambiguity — `REVIEW_REQUIRED` requires a *brand-new* finding, not a re-derived one — `implementation/services/domain.py:458-475`
- §3.4 — revise — **mismatch** — the recount-driven termination cascade is not held to the no-`DRAFT`/`PENDING_ADJUDICATION` condition; only the director's request is — `implementation/routes/recounts.py:359-362`, `services/domain.py:595`
- §3.4 — insert — **mismatch** — termination is the one audit status change that does *not* re-run the projection — `implementation/services/domain.py:595-620`
- §3.5 — insert — ambiguity — duplicate `user_id` or a seventh member is `ERR_VALIDATION`; an empty `members` array is legal and clears the roster — `implementation/routes/teams.py:100,110`
- §3.5 — insert — ambiguity — roster replacement always bumps `version`, even when identical — `implementation/routes/teams.py:121-124`
- §3.5 — insert — ambiguity — an initial `counted_votes` map is key-validated at session open — `implementation/routes/tallies.py:103`
- §3.5 — insert — ambiguity — opening a session tests no state on the owning round or audit — `implementation/routes/tallies.py:67-140`
- §3.5 — revise — ambiguity — submission tests bipartisanship *before* ballot accounting — `implementation/routes/tallies.py:246,254`
- §3.5 — revise — **mismatch** — the cascade re-derives the round ledger from scratch (with `discrepancy_count` = non-`VOIDED` findings of the round's tallies) instead of incrementing, and an existing `OPEN`/`DOCUMENTED` finding is updated in place rather than duplicated — `implementation/services/domain.py:277-295,639-680`
- §3.5 — revise — **mismatch** — round and audit ledgers include `PENDING_ADJUDICATION` tallies, not just `SUBMITTED`/`CERTIFIED` — `implementation/services/domain.py:26,267`
- §3.5 — insert — ambiguity — the audit recomputation also re-derives `cumulative_sampled_batches` — `implementation/services/domain.py:320`
- §3.5 — revise — ambiguity — reopen order and ids: `ERR_INVALID_AUDIT_STATE`, then `ERR_INVALID_DISCREPANCY_STATE`, then the reopen limit — `implementation/routes/tallies.py:281-291`
- §3.5 — revise — ambiguity — reopen leaves `manual_margin_votes`/`machine_margin_votes` intact; the ledger is recomputed from scratch — `implementation/routes/tallies.py:295-300`
- §3.6 — revise — **mismatch** — a finding's `relative_taint` (with `discrepancy_type`/`magnitude_votes`) is refreshed while `OPEN`/`DOCUMENTED` and frozen only at `ESCALATED`/`RESOLVED`/`VOIDED` — `implementation/services/domain.py:639-680`
- §3.6 — insert — ambiguity — documentation's audit-state failure is `ERR_INVALID_AUDIT_STATE` — `implementation/routes/findings.py:93`
- §3.6 — insert — ambiguity — corrective-action creation tests neither discrepancy state nor audit state — `implementation/routes/findings.py:179-205`
- §3.6 — revise — ambiguity — the transition `note` is type-validated but never persisted — `implementation/routes/findings.py:232-234`
- §3.7 — revise — ambiguity — referral tests no tally state; only a `SUBMITTED` tally moves to `PENDING_ADJUDICATION` — `implementation/routes/interpretations.py:60-95`
- §3.7 — insert — ambiguity — a null `counted_votes` is initialised to zero for every candidate before incrementing; the ambiguous decrement is floored at zero — `implementation/routes/interpretations.py:171-177`
- §3.8 — insert — ambiguity — non-null `scope_batch_ids` on `FULL_CONTEST` is `ERR_VALIDATION`; `requested_by_candidate_name` is forced null under other triggers — `implementation/routes/recounts.py:120-135`
- §3.8 — revise — **mismatch** — filing order: quarantine (named batches only) before batch-not-in-contest, and window before margin — `implementation/routes/recounts.py:155-172`
- §3.8 — revise — ambiguity — funding checks the requesting party before any state test (including a caller with no `X-User-ID`) — `implementation/routes/recounts.py:257-265`
- §3.8 — insert — ambiguity — `refund_variant` is recorded even when `deposit_status` is `NOT_REQUIRED` (money fields stay zero) — `implementation/routes/recounts.py:95-103`
- §3.8 — insert — ambiguity — re-canvass leaves `canvassed_at` and `recount_request_deadline_at` untouched — `implementation/routes/recounts.py:347-351`
- §3.8 — insert — ambiguity — `terminated_reason` is the literal `Superseded by a full-contest recount` — `implementation/routes/recounts.py:362`
- §3.8 — revise — ambiguity — withdrawal and denial settle only from `HELD`; otherwise `refund_variant` stays `NONE` — `implementation/routes/recounts.py:380-381,401-402`
- §3.9 step 2 — revise — **mismatch** — the hand-count ballot sum reads the physical batch's *current* `ballot_count`, not the drawn batch's snapshot — `implementation/services/domain.py:355-358`
- §3.9 — revise — **mismatch** — projection triggers: not on termination; the amendment and clock triggers reach only non-terminal audits, and the amendment only when the value changes — `implementation/services/domain.py:595-620`, `routes/elections.py:173-177`
- §3.9 — insert — ambiguity — timeline-review has no audit-state guard (works on `COMPLETE`/`TERMINATED`) — `implementation/routes/audits.py:299-307`
- §3.9 — revise — **mismatch** — no cross-election test on credentialing, and room capacity is counted across *every* election, not per election — `implementation/routes/observers.py:41-57`
- §3.9 — insert — ambiguity — for an observer, credential existence/status/window are tested ahead of `public_report_published` — `implementation/routes/audits.py:309-330`
- §4 — revise — ambiguity — `retrieve` and `return` respond with the drawn batch (not the physical batch); clock-set's `data` carries only `current_utc` — `implementation/routes/audits.py:437,480`, `routes/elections.py:480`
- §5 — insert — ambiguity — `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) exist outside the catalogue; trailing slashes are not significant — `implementation/app.py:39,49-66`
