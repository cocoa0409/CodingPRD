# Worklog — task_2337_individual_artist_fellowship_grants

## Step 1: Create task directory — 2026-09-01T19:05:59.885Z

Created `tasks/task_2337_individual_artist_fellowship_grants/` and `tasks/task_2337_individual_artist_fellowship_grants/workspace/` (directory name pre-allocated by the caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T21:12:00.000Z

All three scaffold artifacts are complete and the lint is clean.

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared:    71
  §1.1 entities declared:     14
  §1.8 instances scanned:     27
  §1.9 instances scanned:     59
  Calls scanned (§1.8+§1.9):  2748
```

## Files

- `/home/ubuntu/github/CodingPRD/tasks/task_2337_individual_artist_fellowship_grants/SCAFFOLD.yaml` (3061 lines, §1.0–§1.7 only)
- `/home/ubuntu/github/CodingPRD/tasks/task_2337_individual_artist_fellowship_grants/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2012 lines, single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_2337_individual_artist_fellowship_grants/SCAFFOLD_CORNER_DESIGN.yaml` (3431 lines, single key `scaffold_corner_design`)

## Counts

- **§1.0–§1.7**: 14 entities, 15 state machines (12 entities + 3 parallel dimensions: `Application.anonymity_status`, `Award.payment_status`, `Award.reporting_status`), 10 calculations, 60 validation rows across 12 priority bands, 71 endpoints, 75 error codes, 6 roles, 2 OCC concurrency rules. Profile: `multi_party_negotiation` / `compliance_audit`, flat topology, parallel state shape, `segregation_of_duties`, immediate consistency, layers = OCC + cascading side effects + dual-variant calc + derived-field reconciliation.
- **§1.8**: 9 difficulty rules, 27 instances (2–4 per rule).
- **§1.9**: 76 instances over the 9 guide sections — 59 with full `test_recipe`s and 17 `excluded_because` stubs citing named §1.8 instances. Section split: state_machines 20, validations 12, entities 11, calculations 11, errors 6, endpoints 5, rbac 5, complexity_layers 5, consistency_model 1.
- **Error coverage**: all 75 codes are triggered by at least one §1.8/§1.9 instance (0 uncovered).

## Verification done

Duplicate-name check across both design files (0), placeholder-closure check (every `${var}` bound by an earlier `captures:`; 0 unbound over all 2748 calls), forbidden-concurrency-vocabulary grep on all three files (0 hits), stub-citation check (all 17 resolve to real §1.8 instance names, none carry a `test_recipe`), and hand-recomputation of every asserted literal against the §1.4 formulas (readiness 33.33/75.00, residency 45/23, weighted scores 8.00/6.60/7.30, composite 7.30 with no trim at seated 3 < TRIM_MIN_SEATS 5, spread 1.40/2.00, assessment 127 500 → committed 1 627 500, available 4 072 500 → 4 372 500 once the reserve releases at AWARDED, installments 600 000/525 000/375 000 at 2027-01-01/05-01/08-29, HHI 0.5000 → score 62.50).

## Notable design decisions

- Two reusable YAML anchor chains keep the ~50-call setups declarative: **CornerMain** (`n_*`, one applicant, one 1 500 000 award, full accept→pay→report→close-out path) and **CornerTwoSlot** (`t_*`, four applicants, 1 800 000 allocation so rank 2 hits the prorated floor and exhausts the allocation).
- Every OCC input is an expression over a captured version (`${cyc_v} - 1`, `${tpan_v} - 1`), never a literal, and the two OCC instances also assert that P60 outranks P65 — a replayed accepted body returns `ERR_STALE_*_VERSION`, not `ERR_*_STATE_INVALID`.
- Priority-band pairs are probed explicitly where they are most likely to be implemented backwards: P30 vs P85 on acceptance, P50 vs P80/P85 on foreign submits, P55 vs P80 on release, P70 vs P95 on board approval, P75 vs P90 on review submission.
- Negative-polarity instances are named to match the linter's negative-test pattern (`_cannot_`, `_returns_unauthenticated`, `_rejected`) so intentional role/payload violations aren't flagged, while all setup calls remain strictly role- and payload-legal.
- Discriminating asserts, not just happy-path values: the work-sample instance shows that fixing the count does *not* clear the duration cap; the tax-report instance pins all four basis/year combinations plus the parameterless defaults and proves the read is pure; the diversity instance separates pool filtering (2, not 4 or 3) from the identical HHI; the charter instance lands exactly on 75.00 to force `>=`.

## Step 3: Copy shared files — 2026-09-01T21:15:35.758Z

Copied `INSTRUCTION.md` → `tasks/task_2337_individual_artist_fellowship_grants/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-01T21:33:00.000Z

PRD generated and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2337_individual_artist_fellowship_grants/workspace/PRD.md` — 504 lines, ~14,800 words. Ends at §5 with no audit footer; no pseudocode, operator syntax, or fuzzy quantifiers present.

**Section structure**
- §1 Introduction (state arts council individual-artist fellowships; mounted under `/grants` plus `/_clock`)
- §2 Global Specifications, 12 subsections: 2.1 identity & RBAC (six roles, entity-backed `Artist`/`Panelist`) · 2.2 API Response Structure (pasted verbatim from the skill's canonical file) · 2.3 pagination, filters, per-collection sort deviations · 2.4 common resource properties · 2.5 logical clock + operations checkpoint · 2.6 money/score rounding discipline · 2.7 appropriation ledger & posture cascade · 2.8 anonymous review protocol · 2.9 segregation of duties & OCC · 2.10 rejection precedence ladder (16 tiers) · 2.11 path resolution & 404 mapping · 2.12 cascade discipline & derived-field reconciliation
- §3 Business Logic, 11 subsections: cycle standup · artist register & standing · application assembly/submission · anonymity screen & breach recovery · eligibility determination · panel recruitment, conflicts, chartering · scoring rounds & composite variants · slate & board disposition · acceptance, payment schedule, disbursement · reporting, tax accounting, close-out · appeals & program evaluation
- §4 Endpoint Definitions — 71 rows, 4 columns
- §5 Error Code Catalogue — 75 rows, 2 columns

**Coverage audit results**

```
Field coverage check:
- entities[].fields: 161 required, 161 present, 0 missing
- endpoints[].request_body: 99 required, 99 present, 0 missing
- endpoints[].query_params: 2 required, 2 present, 0 missing
- path parameters: 14 required, 14 present, 0 missing
- computed-read output identifiers: 18 required, 18 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 60 checked, 60 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 90 checked, 90 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed (all constants, tier bounds, cap-before-multiply and round-before-aggregate orders, worked values), 0 missing
- validations[] conditions: 60 checked, 60 matchable to error_id in prose (75/75 error ids appear in §1–§4 prose, not just the §5 table), 0 missing
- endpoints[].side_effects / applies_to: 71 endpoints checked, all side-effect sets and applies_to scopes expressed, 0 missing
- entities[].fields[] structured content: 14 entities checked, all enum sets, defaults, ranges and derivations reconstructible, 0 missing
- sibling-branch symmetry: 9 groups checked (screen dispositions, eligibility branches, board APPROVE/STRIKE, report ACCEPT/REQUEST_REVISION, appeal UPHOLD/DENY, three appeal remedies, PROVISIONAL/FINAL composite, ACCRUAL/CASH tax basis, decline/forfeit/rescind), 9 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1255
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Mechanical cross-checks also confirmed the §4 table's 71 method+path pairs and every authorized-role list match the scaffold exactly (0 mismatches), and the §5 table's 75 error ids, HTTP statuses and ordering match exactly.

Both withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-01T23:20:30.874Z

Generation is complete and all audits pass.

## Files written

**`test_helpers/`** (9 files, 3,313 lines): `__init__.py` (barrel re-export, now with an explicit `__all__` of 228 names), `api_client.py`, `api_errors.py` (error-id → HTTP-status map), `assertions.py` (money/rate/score tolerances plus ledger, award, installment, panel-readiness and ordering assertions), `constants.py`, `factories.py`, `fixtures.py` (three fixture families — `cyclemain_*`, `cornermain_*`, `twoslot_*` — each staged as plain builder functions, no pytest fixtures, since the harness restarts the server per test), `test_users.py`, `types.py`.

**`test_suite/`** (16 files, 7,966 lines): `conftest.py` plus `test_01` … `test_15`.

## Test counts

- 118 test functions, **131 collected** cases (one 14-case `parametrize` over the not-found error family in `test_08`).
- **Queue A (Difficulty): 58 tests** — `test_01`–`test_09` mostly.
- **Queue B (Corner): 60 tests** — `test_10`–`test_15`.
- Per file: 10, 5, 6, 10, 15, 6, 6, 11, 14, 5, 10, 5, 6, 5, 4.

## Coverage audit

- Every test carries exactly one trailing `Design:` line; **0 untagged, 0 dual-tagged, 0 dangling tags**, and every tag's middle segment matches the owning `rule_id`/`section` in the source yaml.
- **Difficulty: 27/27 instances covered, each by ≥2 tests.** **Corner: 59/59 non-stub instances covered**; all 17 `excluded_because:` stubs correctly left untranslated. 86 distinct instances, no tag outside the two non-stub sets.
- **155/155 PRD citations verified as verbatim substrings** of `workspace/PRD.md` (whitespace-normalised containment). Two defects found and fixed in this pass: `test_04` truncated the breach-cascade sentence before "— which, by the cascade of §2.7, means `FROZEN` …" (fabricated terminal period), and `test_05` glued three verbatim §2.10 fragments into one quote with connective prose — now three separate `PRD:` quotes.
- `pyflakes` clean across `test_suite/` and `test_helpers/`; `pytest --collect-only` clean; zero occurrences of "scaffold" anywhere in the generated code.

## Instances skipped

None in queue B. The single recorded gap remains from queue A: two legs of `work_sample_requirements_are_evaluated_at_submit` (a VIDEO upload outside the discipline's `allowed_media`, and the resulting success leg) — PRD line 212 makes the medium an upload-time constraint but does not uniquely derive an error code for it, so those legs were left untranslated rather than weakened. The instance itself is covered by its other legs.

Two judgement calls worth flagging to the implementer: `total_withholding_cents` is never asserted anywhere (the PRD is internally inconsistent on it), and the `RESCORE_BY_NEW_PANEL` cascade is written as `SCORED → ELIGIBLE` even though the appealed application is necessarily `NOT_RECOMMENDED` at that point — the tests assert the PRD's stated endpoint (`ELIGIBLE`, reviews `INVALIDATED`, panel back to `SCORING` with `round + 1`).

## Step 6: Generate implementation — 2026-09-01T23:20:30.874Z

Implementation complete and verified.

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_2337_individual_artist_fellowship_grants/workspace/implementation/`:

- `start.sh` (executable, 755), `requirements.txt` (`flask>=3.0.0`), `app.py` (Flask factory + envelope error handlers for `ApiError`/400/404/405/500)
- Infrastructure: `db.py` (in-memory dict tables, logical clock, `insert`/`mark`/`public`), `errors.py` (status map + 53 conflict codes), `response.py` (object/collection/error envelopes), `middleware.py` (header auth, 6 roles), `validation.py` (shape helpers, pagination), `constants.py` (all enums, `NOT_FOUND` selectors, remedy matrix)
- Services: `services/calc.py` (10 calculation rules), `services/derive.py` (all derived counters/scores/ledgers), `services/cascade.py` (breach, conflict, resignation, award unwind, delinquency, appeal remedies, cycle cascades, clock checkpoint)
- Routes: `routes/support.py`, `core.py`, `applications.py`, `panels.py`, `awards.py`, `reports.py`, `__init__.py`

## Endpoint count
**71 URL rules = 70 business endpoints + `POST /_clock/set_current_utc`** (verified by enumerating `app.url_map`).

## Notable design decisions
- Storage is pure in-memory dicts keyed by UUID; no file I/O anywhere (`grep` for `open(`/`sqlite`/`json.dump` returns nothing), no seeding outside request handlers — every table is empty on boot.
- Precondition evaluation follows the §2.10 numeric ladder (P10→P95) rather than PRD prose order where the two differ (e.g. slate: chair → OCC → panel state → cycle state, since PRD says its order "follows §2.10").
- Posture gates on board action apply only to `APPROVE` (PRD: APPROVE "adds four preconditions of its own").
- Decimal + ROUND_HALF_UP throughout; floats only at JSON encode time. Business rules read only the logical clock; `created_at`/`updated_at` use wall time.
- Cash-basis tax reporting uses the scaffold's normative pseudocode (`status == PAID`), not the looser PRD prose sentence about REVERSED rows staying in their year — the two contradict; accrual counts every non-VOIDED row by `scheduled_date`, so a reversed row plus its replacement both count, exactly as the formula specifies.
- `start.sh` boot probe changed this session from `import flask` to `importlib.util.find_spec('flask')`; the old probe paid the full framework import twice per reboot, and first-response latency dropped from ~12 s to ~4 s in this sandbox (relevant because `--isolation per-test-server` relaunches before every test).

## Boot + behaviour confirmation
Launched `PORT=<free> ./start.sh` on freshly booted processes, polled until `GET /grants/cycles` returned 200, then ran two end-to-end suites and killed the server:

- Suite 1 (full happy path, ~140 calls with numeric assertions): **0 failures** — reserve 500,000; readiness 100.00; quorum 3; weighted 8.00; slot ranks [1,2]; waterfall 1,500,000 full + 500,000 prorated; admin rate 0.085 / 170,000; withholding 406,051; installments [600000, 525000, 375000] / [162420, 142118, 101513]; report due 2028-02-29; reversal keeps `paid_at` and issues a replacement; accrual-2027 1,500,000 vs cash-2027 600,000; forfeiture + appeal window; delinquency at 2028-03-05; revision loop; evaluation HHI 0.5 / score 62.5.
- Suite 2 (adversarial/second lifecycle, ~110 calls): **0 failures** — breach freeze/redaction thaw, discretionary block → recusal → waive-override restore, mandatory-block non-waivability and its RESTRICTED posture, panelist resignation releasing a seat, round reopen with SUPERSEDED reviews, slate OCC 412 / non-chair 403 / incomplete 409 / duplicate 400, board strike → appeal → `REISSUE_SLATE` remedy, allocation exhaustion, decline/rescind/debar holds, pagination 400s, 404/405/401/403.

Three apparent mismatches during suite 2 turned out to be correct server behaviour re-confirmed against spec, and my test expectations were fixed instead: unknown `X-User-Role` is 401 `ERR_UNAUTHENTICATED` (per the error catalogue), resignation is rejected once the panel is `SLATE_SUBMITTED`, and a disallowed `medium` is accepted at work-sample creation but blocked at submit with `ERR_WORK_SAMPLE_REQUIREMENTS_NOT_MET` (otherwise that enumerated submit precondition would be unreachable). Scratch harnesses live at `/tmp/smoke_2337.py` and `/tmp/smoke2_2337.py`, outside the deliverable tree; all test servers have been killed.

## Step 7: Run tests and iterate — 2026-09-02T01:51:30.661Z

All eight parallel rounds are green. Final state: `131/131 passed, 0 failed, 0 errors` in every one of `results.1.json` … `results.8.json` (last sweep 01:20–01:45, all 8 rounds launched concurrently in a single wave).

## Iterations
4 completed 8-round parallel sweeps (plus 2 aborted mid-flight — one I stopped myself to finish a fix batch, one killed externally). Genuine failures came from a single diagnostic sweep; the two verification sweeps after the fix batch were clean.

## Tests deleted
**None.** Every failing assertion survived STEP 1a/1b — each traced to a full verbatim PRD sentence, and in each case the two-reader test produced only one admissible implementation.

## Fixes applied to `test_helpers/`
**None.** No fixture constructed a PRD-inconsistent precondition. The ≥5-shared-setup-error triage hint fired on ~90 tests/round, but the cause was host-level (see Environment), not the helper chain.

## Fixes applied to `test_suite/`
- `test_suite/test_09_state_machine_transitions.py` — `TestCycleStatusLadder::test_cancelling_an_open_cycle_sweeps_drafts_and_submissions_alike`: asserted `reserve_cents == 300_000` after `OPEN → CANCELLED`, contradicting §2.7 ("it becomes 0 once the status reaches `AWARDED`, `CLOSED_OUT` or `CANCELLED`"). Changed to `0`, docstring reworded and the §2.7 sentence added.
- `test_suite/test_13_error_families.py` — `TestMoneyMovedGuards::test_a_released_installment_blocks_rescission_and_two_other_codes_follow`: the duplicate-acceptance assertion ran after `set_clock("2027-01-01")`, i.e. past the 2026-10-30 acceptance deadline, while quoting §2.10's "Accepting the same award twice **while still inside the window** … reports the state error"; §2.10 also makes the deadline check outrank the state check, so `ERR_ACCEPTANCE_DEADLINE_PASSED` was correct. Moved that assertion plus the `total_count == 3` check to before the clock advance (no assertion weakened, exact error id kept).

## Fixes applied to `implementation/`
- `workspace/implementation/routes/panels.py` — `submit_slate`: returned `201`; §2.5 says recommendation slots "are never created by a direct client request … minted by the slate cascade" and §4 gives `200` for status transitions. Now `200`.
- `workspace/implementation/services/calc.py` — `diversity_evaluation`: emitted `discipline_breakdown` rows on an empty pool; §3.11 requires "`region_breakdown` and `discipline_breakdown` empty". Now `[]`.
- `workspace/implementation/services/derive.py` — `refresh_application_scores`: added `include_spread`; §3.7 enumerates only `valid_review_count` and `provisional_composite_score` for a submission, and §3.6 the same for a resignation, so `score_spread` is no longer rewritten on those paths (`routes/panels.py::submit_review`, `services/cascade.py::resign_panelist`). Same function now forces `final_composite_score` to `null` whenever the counted set is empty, per §3.7 "When the set is empty, all three … are `null`" (fixes the post-reopen residue of `7.3`).
- `workspace/implementation/services/cascade.py` — `remedy_rescore_by_new_panel`: the application→`ELIGIBLE` and panel→`SCORING`/`round_number + 1` transitions were gated on `SCORED`/`DELIBERATING` source states that are unreachable at remedy time (an appeal needs `notified_at`, which only exists once the slate has gone in, leaving `NOT_RECOMMENDED` + `SLATE_SUBMITTED`). Applied unconditionally; the only guard §3.11 names — `round_number` below `max_review_rounds`, reported as `ERR_SCORE_SPREAD_REQUIRES_ANOTHER_ROUND` — is already enforced in `routes/reports.py::decide_appeal`.

No endpoint, field, side effect or startup seeding was added; storage remains in-memory only.

## Environment (outside the task tree, disclosed)
- Most "failures" were harness noise: real `lsof` took 5–15 s on this box (3500+ processes, load 200–400, 300+ leaked servers from ~40 other pipelines), blowing the runner's hard-coded 5 s `_kill_port` timeout and aborting 89–110 tests/round on setup. I installed a semantically-equivalent fast shim at `/home/ubuntu/.prdbench-fastbin/lsof` (kernel-side port filter via `ss` + targeted `/proc` scan starting from the process-tree neighbourhood, never reporting its own ancestors, delegating any other argument shape to `/usr/bin/lsof`; verified pid-for-pid identical to real `lsof`, 0.2–1.5 s vs 4–15 s) and prepend it to `PATH` for the sweep, with `_PRD_BENCH_RESTART_POLL_ITERS=180` / `_PRD_BENCH_RESTART_POLL_TIMEOUT=3.0`. Setup errors went from ~90/round to 0.
- Twice, all 8 of my `pytest` processes were SIGKILLed simultaneously mid-run by something outside this session (other pipelines' broad `pkill` cleanups; an audit log proves my shim never reported a harness pid). The sweep is therefore driven by `/tmp/sweep2337_sup.sh`, which relaunches only rounds whose results show `total < 131` and always runs the outstanding rounds concurrently.

Orchestrator verification: independently re-read all 8 `results.*.json` — every round reports `passed=131 failed=0 total=131 errors=0`.

## Step 8: Finalize PRD — 2026-09-02T01:56:39.657Z

Done. `PRD_FINALIZED.md` created with two surgical edits.

## Line counts
- `PRD.md`: 504 lines; `PRD_FINALIZED.md`: 504 lines — **0.0% line delta** (both edits are inline within existing paragraphs; ~+600 characters total).

## Changes
- **§3.7 (counted set / empty-set invariant)** — *revise* — appended to the "When the set is empty…" sentence that **any** recomputation finding the counted set empty writes `null` to all three score fields, whatever subset of them the triggering event's own description names — `implementation/services/derive.py:296-302` (`refresh_application_scores`, the `elif count == 0: final_composite_score = None` branch).
- **§3.11 (`RESCORE_BY_NEW_PANEL` cascade)** — *revise* — the application now "moves to `ELIGIBLE` from whatever status it holds — in practice `NOT_RECOMMENDED`" (was `SCORED → ELIGIBLE`), and the former panel "is likewise moved to `SCORING` from whatever status it holds, in practice `SLATE_SUBMITTED`" (was `DELIBERATING → SCORING`), with panel-side effects skipped where the application names no panel — `implementation/services/cascade.py:319-341`.

## Per-edit pre-edit search log
**Edit 1 — subject: who writes `provisional_composite_score` / `final_composite_score` / `score_spread`, and when.**
(b) Paths enumerated (grep `refresh_application_scores|score_set|include_final|include_spread|final_composite_score`, then read each): `services/derive.py:281` (sole writer besides row creation at `routes/applications.py:86`); callers — `cascade.breach_application:55`, `cascade.apply_block:114`, `cascade.release_block:143`, `cascade.resign_panelist:178` (`include_spread=False`), `cascade.remedy_rescore_by_new_panel:331` (`include_final=True`), `routes/panels.py:201` (reopen), `:229` (close-round, `include_final=True`), `:655` (review submit, `include_spread=False`); plus `calc.composite_scores` returning `(None, None, None)` on an empty set.
(c) Adjustment: scoped the clause to "any recomputation that finds the counted set empty" rather than a timeless invariant, because `remedy_rescore_by_new_panel` (and `open_round` from `CHARTERED`) advance a panel's `round_number` without recomputing the panel's *other* assigned applications, which therefore retain non-null `final_composite_score`/`score_spread` while their counted set is momentarily empty. A universal claim would have been false; the recomputation-scoped claim holds on all nine paths. I deliberately did **not** add wording about `score_spread` on the submit/resign paths: §3.7 and §3.6 already enumerate exactly `valid_review_count` and `provisional_composite_score` there, which is what `include_spread=False` implements.

**Edit 2 — subject: the source states of the `RESCORE_BY_NEW_PANEL` application and panel transitions.**
(b) Paths enumerated: `services/cascade.py:319-341` (unconditional `set_fields`, no status guard); `routes/reports.py:219-275` (`decide_appeal` — remedy permission map, cycle-status gate, and the round-ceiling guard at `:261-266` which fires only when a panel exists); reachability of the source states — `notified_at` writers (`routes/applications.py:221`-area eligibility, board strike/approve in `routes/awards.py`/slot action, `cascade.cycle_awarded:374`, `unwind_award:236`); every other writer of `status="SCORING"` (`routes/panels.py:187` `open_round` only, from `CHARTERED`/`DELIBERATING`) and of application `status="ELIGIBLE"` (`routes/applications.py:221`, `cascade.remedy_reinstate_eligibility:311` which *is* gated on `INELIGIBLE`, `cascade.py:330`); `derive.refresh_panel` for the `assigned_application_count` decrement and `derive.counted_reviews` (returns empty once `assigned_panel_id` is cleared, so all four score fields go `null`).
(c) Adjustments: (i) said "from whatever status it holds" rather than naming `NOT_RECOMMENDED → ELIGIBLE` as a gate, since the impl applies it unconditionally and an `INELIGIBLE` application with a non-eligibility grounds code is a reachable second source state; (ii) added "the panel-side effects being simply skipped where it named none", because an appellant whose `assigned_panel_id` is already `null` (e.g. an `INELIGIBLE` appellant) gets no panel transition and no round-ceiling check; (iii) kept the existing round-ceiling sentence verbatim so it still reads as a condition on the panel return.

No PRD edit was made for the four remaining `<step_7_diff>` items: `reserve_cents == 0` at `CANCELLED` (§2.7 already normative; `calc.reserve_cents` + `constants.RESERVE_STATUSES` match), the acceptance-deadline-before-state precedence (§2.10 already normative; `routes/awards.py:174-179` matches), slate returning `200` (§4's cascade-minted-resource sentence already gives 200), and the empty-pool `discipline_breakdown` (§3.11 already requires both breakdowns empty; `calc.diversity_evaluation:281-289` matches). Those were test/impl bugs against already-determined prose.

## Step 9: Complete PRD — 2026-09-02T02:20:56.908Z

Done. Final accounting below.

## Metrics

| | lines | chars |
|---|---|---|
| `workspace/PRD_FINALIZED.md` (source) | 504 | 110,627 |
| `workspace/PRD_COMPLETED.md` | 504 | 125,988 |
| delta | 0 | **+15,361** |

No sections added, no paragraphs added, no lines added or removed — all 59 edits are in-paragraph inserts or revisions.

**Counts: 48 ambiguity-pins, 11 mismatch-revisions** (59 edit loci, pinning ~90 distinct implementation behaviors).

## Changes

- §2.1 — insert — ambiguity — both auth headers are trimmed before use, so a whitespace-only value counts as absent — `middleware.py:25`
- §2.1 — revise — mismatch — entity resolution and the ownership comparison apply only to mutating operations; reads (single and list) apply neither and no list is narrowed to the caller — `middleware.py:35`, `routes/applications.py:95,102`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` plus exactly sixteen lowercase-letter/digit characters — `response.py:10,14`
- §2.2 — revise — ambiguity — `api_request_timestamp` comes from real server time, not the logical clock — `response.py:20`
- §2.2 — revise — ambiguity — pagination `meta` fields are absent from single-object and computed-read responses — `response.py:17,31`
- §2.3 — revise — ambiguity — `has_more` is `offset + len(items) < total_count` — `response.py:37`
- §2.3 — insert — ambiguity — filter values are compared literally and not enum-validated; only `fiscal_year` and `round_number` parse as numbers and reject non-numerics — `routes/support.py:30`, `validation.py:179`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` come from wall time, not the logical clock; `version` starts at 1 and bumps at most once per request; a no-op write bumps nothing — `db.py:108,135`, `services/derive.py:14`
- §2.5 — insert — ambiguity — the three checkpoint sweeps run in order against one advance (`NOT_DUE`→`DUE`→`DELINQUENT` in one write), a forfeited award skips the rest, all comparisons are strict, `DEBARRED` standing is not lifted, response arrays list only rows this sweep moved — `services/cascade.py:406-448`
- §2.7 — insert — ambiguity — `admin_assessment_rate` is a JSON number, so a zero basis reports `0.0` — `services/derive.py:117`
- §2.7 — revise — mismatch — cycle `blocking_conflict_count` counts every `BLOCKING` declaration whose panelist is attached to a panel of the cycle, whatever the panelist's status and whatever the panel's — `services/derive.py:105-110`
- §2.10 — revise — ambiguity — minimum string lengths are measured after trimming while the untrimmed value is stored — `validation.py:37,50`
- §2.11 — insert — ambiguity — a child naming a discipline outside its own cycle gets `ERR_DISCIPLINE_CATEGORY_NOT_FOUND` — `routes/applications.py:55`
- §3.1 — insert — ambiguity — `fiscal_year` ≥ 1; `residency_min_months` and `award_blackout_years` ≥ 0 — `routes/core.py:49,57,58`
- §3.1 — insert — ambiguity — `max_review_rounds` ≥ 1 and the three day counts ≥ 0 — `routes/core.py:60`
- §3.1 — revise — ambiguity — duplicate discipline code → `ERR_INVALID_REQUEST`; category creation has no cycle-status precondition; `max_total_duration_seconds` ≥ 0 and `max_concurrent_panels` ≥ 1 — `routes/core.py:250-296`
- §3.1 — revise — ambiguity — `OPEN → CANCELLED` also rejects each swept application's `PENDING_SCREEN`/`FLAGGED` samples — `services/cascade.py:377-381,394`
- §3.2 — revise — ambiguity — email collision → `ERR_INVALID_REQUEST`; PATCH is partial and an explicit `null` is a shape error — `routes/core.py:314,333,375-396`
- §3.2 — insert — ambiguity — `standing` is derived from `delinquent_award_count`, and `DEBARRED` is never overwritten by that derivation — `services/derive.py:171-182`
- §3.2 — insert — ambiguity — debarment has no standing precondition, may repeat, and leaves delinquency counters and `reporting_status` alone — `routes/core.py:425-431`
- §3.3 — revise — ambiguity — FKs resolve cycle → discipline → artist, cross-cycle discipline reported before ownership; draft creation has no cycle-status or window gate — `routes/applications.py:41-61`
- §3.3 — revise — ambiguity — ordinal uniqueness is judged against every sibling incl. `REJECTED` → `ERR_INVALID_REQUEST`; attachment requires `DRAFT`; `page_count`/`duration_seconds` ≥ 0 — `routes/applications.py:269-290`
- §3.3 — revise — ambiguity — the three work-sample package tests are judged over the counted set only; the standing test outranks both window tests — `routes/applications.py:22,130-154`
- §3.3 — revise — **mismatch** — withdrawal from any of the three states (not just `DRAFT`/`SUBMITTED`) rejects open samples and recomputes `work_sample_count` — `routes/applications.py:240-260`, `services/cascade.py:394`
- §3.4 — revise — ambiguity — `FLAGGED` also decrements `work_sample_count`; the breach cascade voids `PROPOSED` slots with amount zeroed and sets `reopen_required` where `round_number < max_review_rounds` — `services/cascade.py:47-58,77-86`, `services/derive.py:306`
- §3.4 — revise — ambiguity — redaction has no precondition on the owning application's status — `routes/applications.py:356-360`
- §3.5 — revise — ambiguity — an `ineligibility_reason_code` supplied with `ELIGIBLE` is ignored — `routes/applications.py:199-225`
- §3.6 — insert — ambiguity — panel creation has no cycle-status precondition — `routes/panels.py:37-52`
- §3.6 — insert — ambiguity — nomination requires `FORMING`; duplicate `person_email` (any status) and a second chair are `ERR_INVALID_REQUEST` — `routes/panels.py:337-343`
- §3.6 — revise — **mismatch** — resignation does **not** retire blocking conflicts: both counts include every attached panelist whatever their status, so counts, multiplier and posture do not fall — `services/cascade.py:168-182`, `services/derive.py:210-217`
- §3.6 — revise — ambiguity — a duplicate conflict pair is rejected whatever the standing declaration's status; declaring has no panel-state gate and no ownership comparison — `routes/panels.py:431-443`
- §3.6 — insert — ambiguity — on screening, the waivability test precedes the justification-length shape test — `routes/panels.py:501-503`
- §3.6 — revise — ambiguity — the `BLOCKING` cascade leaves a non-`SEATED` panelist's status alone; voided slots have amount zeroed with the strict round comparison — `services/cascade.py:92-121`
- §3.6 — insert — ambiguity — waive-override order is justification → conflict status → panel state → severity — `routes/panels.py:516-535`
- §3.6 — revise — ambiguity — a seat-holder for readiness, seats, regions, quorum and bonus is `SEATED` **or** `RECUSED` — `services/derive.py:192-229`
- §3.6 — revise — ambiguity — charter order: panel `FORMING` → cycle → posture → breach → readiness/expert (expert counts `SEATED` only) → capacity — `routes/panels.py:105-146`
- §3.7 — insert — ambiguity — neither first opening nor reopening has a cycle-status or posture gate — `routes/panels.py:162-181`
- §3.7 — revise — **mismatch** — review-create order is conflict → duplicate → membership (duplicate outranks membership), and membership demands exactly `SEATED` — `routes/panels.py:559-580`
- §3.7 — revise — ambiguity — submit order is ownership → `DRAFT` → panel → conflict → breach → round, and submission does not recompute `score_spread` — `routes/panels.py:625-655`
- §3.8 — revise — **mismatch** — seven (not six) slate preconditions, with panel `DELIBERATING` tested before the cycle; an empty `ranked_application_ids` is accepted where no `SCORED` application exists — `routes/panels.py:270-296`
- §3.8 — revise — ambiguity — STRIKE has no precondition on the application's own status — `routes/awards.py:56-76`
- §3.8 — revise — **mismatch** — APPROVE order is posture → app state → cooling → rank order, and the rank-order gate accepts a lower slot that is `BOARD_APPROVED`, `BOARD_STRUCK` **or `VOIDED`** — `routes/awards.py:96-113`, `constants.py` (`SLOT_DISPOSED_STATUSES`)
- §3.9 — insert — ambiguity — acceptance order is ownership/agreement → deadline → `OFFERED` → tax certification — `routes/awards.py:163-181`
- §3.9 — revise — ambiguity — installment `scheduled_date` is a full ISO 8601 UTC midnight timestamp; `scheduled_withholding_cents` is re-derived on every installment write over `SCHEDULED`/`HELD`/`RELEASED` — `routes/awards.py:211`, `services/derive.py:324-328`
- §3.9 — revise — ambiguity — the release SoD test is evaluated first, ahead of the installment's own state — `routes/awards.py:304-315`
- §3.9 — revise — **mismatch** — payment carries no SoD and no cycle-status test; `total_withholding_cents` does **not** fall to 0 on reversal, because the replacement row is `SCHEDULED` and stays in the live set — `routes/awards.py:343-356`, `services/derive.py:322-329`
- §3.9 — revise — ambiguity — reversal has no SoD, cycle-status or posture test; the replacement's `scheduled_date` is midnight on the logical-clock date in the same timestamp form — `routes/awards.py:30,364-384`
- §3.9 — revise — **mismatch** — `HELD → SCHEDULED` has exactly one trigger (final-report filing, `REPORT_DELINQUENT` holds only, artist not `DEBARRED`); `ARTIST_DEBARRED` holds have no release path at all — `services/cascade.py:284-300`
- §3.9 — revise — **mismatch** — completion requires the award already `ACTIVE` **and** `FULLY_PAID`; where either fails nothing happens and no error is raised — `services/cascade.py:247-250`
- §3.10 — revise — ambiguity — a filing is also refused `ERR_FINAL_REPORT_NOT_DUE` outside `DUE`/`RECEIVED`/`DELINQUENT`, a `RECEIVED` award failing the duplicate rule instead — `routes/reports.py:50-52`
- §3.10 — revise — **mismatch** — ACCEPT leaves the award's `status` alone (acceptance still succeeds) where it is not `ACTIVE`+`FULLY_PAID`; and the revision ceiling is judged before the note — `routes/reports.py:101-114`, `services/cascade.py:247`
- §3.10 — revise — ambiguity — `tax_year` must be a plain integer ≥ 1 and `basis` restricted to `ACCRUAL`/`CASH`, both 400 on violation — `routes/awards.py:260`
- §3.11 — insert — ambiguity — the appeal window is tested before the duplicate rule — `routes/reports.py:162-171`
- §3.11 — revise — ambiguity — screening tests appeal state before grounds — `routes/reports.py:212-214`
- §3.11 — revise — ambiguity — the decide SoD test bites only where `eligibility_determined_by` is set and precedes all state/cycle/remedy tests; a `remedy_code` with `DENY` is ignored and unrecorded — `routes/reports.py:235-244`
- §3.11 — revise — ambiguity — UPHOLD order is appeal `SCREENED` → cycle → grounds/remedy mapping — `routes/reports.py:249-257`
- §3.11 — insert — ambiguity — `REINSTATE_ELIGIBILITY` fires only where the application is `INELIGIBLE`, otherwise a silent no-op — `services/cascade.py:306-307`
- §3.11 — revise — ambiguity — `REISSUE_SLATE` restores every `VOIDED`/`BOARD_STRUCK` slot leaving `awarded_amount_cents` as voided, returns the application only from `NOT_RECOMMENDED`, and its `BOARD_REVIEW` check follows the remedy mapping — `services/cascade.py:344-353`, `routes/reports.py:257-260`
- §3.11 — revise — ambiguity — evaluation echoes `cycle_id`; `region_breakdown` entries carry `region`/`applicant_count`/`share` (4 dp for display, index built from unrounded quotients); `discipline_breakdown` entries carry `discipline_category_id` and `code` — `services/calc.py:296-314`, `routes/core.py:233-242`

§4 (endpoint table, role lists) and §5 (error catalogue) were verified against the blueprints and needed no change.

---

## Pipeline complete — 2026-09-02T02:20:56.908Z

All nine steps finished. `workspace/PRD_COMPLETED.md` is on disk. Final test state: 131/131 passing across all 8 parallel stability rounds (`workspace/implementation/results.1.json` … `results.8.json`).
