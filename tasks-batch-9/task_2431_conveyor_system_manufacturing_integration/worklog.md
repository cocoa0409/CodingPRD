# Worklog — task_2431_conveyor_system_manufacturing_integration

## Step 1: Create task directory — 2026-09-02T16:11:40.427Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2431_conveyor_system_manufacturing_integration` and its `workspace/` subdirectory. Index 2431 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-02T17:49:02.520Z

Complete. All three scaffold artifacts for task 2431 are finished and the lint is clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2431_conveyor_system_manufacturing_integration/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (top-level keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities (14), state_machines, concurrency_rules (3), calculations, validations (15 priorities), endpoints (45), errors (48), roles (5)). Neither design key present.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`, 20 instances, >=2 per each of the nine §0.5 difficulty rules.
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`, 69 instances (53 full recipes + 16 `excluded_because` stubs) across the nine guide sections: entities 13, state_machines 15, calculations 12, validations 13, endpoints 5, errors 14, rbac 5, complexity_layers 7, consistency_model 1.

**Work completed this session** (the corner-design tail): the remaining `errors` instances (ERR_OPEN_CHANGE_ORDER, ERR_SEGREGATION_OF_DUTIES, a bundled ERR_CERTIFICATE_ALREADY_DISPUTED + ERR_DISPUTE_INVALID_STATE replay pair, ERR_DISPUTE_WINDOW_EXPIRED), the full `rbac` section (cross-desk role denials, priority-2-before-priority-8 refusal, five-role shared GET, ERR_NOT_PROJECT_CUSTOMER peer isolation, and a segregation-of-duties instance scoped to the 100%-ramp recorder only), the `complexity_layers` section (one OCC instance per §1.2.1 rule plus a version-increment walk and three stubs), and the `consistency_model` instance.

**Verification performed beyond the lint:** instance names are unique within the corner file and disjoint from the difficulty file; every stub cites an existing `rule / name` pair in SCAFFOLD_DIFFICULTY_DESIGN.yaml and carries no `test_recipe`; all 48 catalog error ids appear as triggered codes across the two design files; claim types are drawn only from `references/claim-extraction-guide.md`.

**Fixes made while authoring:** `FatTest` uses `result`, not `verdict` (corrected one assert); three new sections were emitted two spaces over-indented and were dedented to match the file's `  - section:` / `    instances:` shape (the only YAML parse failure encountered).

Lint verdict block, verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2431_conveyor_system_manufacturing_integration/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2431_conveyor_system_manufacturing_integration/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2431_conveyor_system_manufacturing_integration/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    45
  §1.1 entities declared:     14
  §1.8 instances scanned:     20
  §1.9 instances scanned:     69
  Calls scanned (§1.8+§1.9):  960

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

The hard constraint held throughout: no sibling task directory was listed, globbed, grepped, or read.

## Step 3: Copy shared files — 2026-09-02T17:49:18.564Z

Copied `./INSTRUCTION.md` to `tasks/task_2431_conveyor_system_manufacturing_integration/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T18:03:30.552Z

The PRD is complete and verified. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced at any point.

## What was produced

`/home/ubuntu/github/CodingPRD/tasks/task_2431_conveyor_system_manufacturing_integration/workspace/PRD.md` — **412 lines**, ending at a complete `## 5. Error Code Catalogue` table (last line `| ERR_NO_FUNDABLE_SPARE_LINES | 422 Unprocessable Entity |`). No audit footer, no contract reports in the file.

Structure (domain-derived, not copied from the example skeleton):
- §1 Introduction — 3 paragraphs approached from the integrator's operational pain points
- §2 — 12 subsections: 2.1 RBAC, 2.2 verbatim envelope, 2.3 Pagination, then eight domain subsections (Resource Identity/Logical Clock, Two Independent Project Dimensions, Cascade Discipline, Optimistic Concurrency, Monetary Precision & Basis Points, Conservation of Facility Throughput Share, Occupancy Windows & Continuing-Operations Protection, Nested Path Resolution, Rejection Precedence)
- §3 — 9 subsections grouped by programme timeline (project opening -> design graph -> simulation -> freeze/shop release -> FAT -> cutover -> commissioning/acceptance -> change-order negotiation -> service package & settlement)
- §4 — 45 endpoints, exactly 4 columns; §5 — 48 errors, exactly 2 columns

## Hard Contracts

```
Field coverage check:
- entities[].fields: 124 required, 124 present, 0 missing
- endpoints[].request_body: 57 required, 57 present, 0 missing
- endpoints[].query_params / path_params: 14 required, 14 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 15 checked, 15 expressed in prose (ordered list in §2.12 with error_id + applies_to per band), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_project_version / expected_fabrication_lot_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 47 checked, 47 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed (all constants embedded: 400/300 bps derates, 250000000/150, 500000000/220, 300 escalation tiers, 10000/6000/0 coverage factors, 30/60/120 sustain minutes, 105/2/3 FAT, 50/500 LD, 480/240/60 + 25 SLA, 500/30 retention, 3-round CO cap), 0 missing
- validations[] conditions: 48 error ids checked, 48 matchable to a condition in §2 or §3 prose, 0 missing
- endpoints[].side_effects / applies_to: 45 endpoints checked, all side-effect sets expressed, 0 missing
- entities[].fields[] structured content: 124 checked, defaults / initial values / enum domains / null-while-OPEN semantics / common_fields:false (FlowLink, FatTest, CommissioningRamp carry only id + created_at) reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (CO decision APPROVE/REJECT/REQUEST_REVISION, FAT PASS/FAIL/third-FAIL, window start/complete/abort, dispute UPHELD/CREDITED, simulation DETERMINISTIC/DEGRADED, damages NAMEPLATE/OBSERVED_AVAILABILITY), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 717
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 verified **byte-identical** to `section-2.2-response-structure.md`; zero pseudocode operator leaks (`==`, `>=`, `+=`, ...) outside code fences; zero fuzzy/approximating words; OCC prose avoids all timing-based framing.

Two judgement calls worth flagging for the scaffold author: (a) the scaffold never nominates an error for a design-freeze attempted outside `DESIGN`, so the PRD maps it to `ERR_PROJECT_NOT_IN_DESIGN` (the only code whose condition covers it); (b) `ERR_DESIGN_NOT_FROZEN` is split into two distinct statements because lot *creation* is legal in `DESIGN_FROZEN`/`IN_FABRICATION`/`REBASELINE_REQUIRED` while lot *release* is legal only in `DESIGN_FROZEN`/`IN_FABRICATION`.

**Orchestrator anti-truncation verification:** `wc -l` = 411 lines; headings walk ends at `## 5. Error Code Catalogue` (line 360); §5 table contains 48 `ERR_` rows matching the scaffold's 48-error catalogue; §4 table contains 45 endpoint rows + header/separator; tail ends on a complete table row, not mid-sentence. Grep for `expert|difficulty|scaffold` returns zero hits, so the Step 2 difficulty instruction did not leak into the PRD. Not truncated — no regeneration needed.

## Step 5: Generate unit tests — 2026-09-02T19:31:10.978Z

Done. Task 2431's PRD-compliance suite is complete and green.

## What was generated

`/home/ubuntu/github/CodingPRD/tasks/task_2431_conveyor_system_manufacturing_integration/`
- `test_helpers/` — `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`, `__init__.py` (unchanged this session)
- `test_suite/` — `conftest.py` + `test_01` … `test_16`, **157 tests**

New this session: `test_suite/test_16_concurrency_and_consistency.py` (12 tests) covering the last 5 real corner instances — the three §2.7 OCC pins (`change_order_decision_on_a_superseded_project_version_returns_412`, `spares_provisioning_rerun_on_a_stale_project_version_returns_412` with the 1 700 000 / 1 506 000 / 1 794 000 waterfall, `fat_test_on_a_stale_lot_version_returns_412_before_the_state_check` proving band 7 beats band 8), `project_version_advances_only_on_writes_that_declare_it` (1 → 4 → 4 across a run → 5 on freeze → 6 on a part line), and the `consistency_model` instance (completion moves zone/ledger/state in one request; `acceptance_ready` is true on the read straight after the 100 % ramp and issuance succeeds on the very next call).

## Coverage audit (scripted, zero problems)

- Queue A: 20 difficulty instances, 0 stubs — **every one has ≥2 tests**.
- Queue B: 85 corner instances, 16 `excluded_because` stubs skipped, **69 real instances all covered ≥1**.
- Every test carries exactly one `Design:` tag; all 157 tags resolve to real non-stub instance names; no tag points at a stub. Every docstring PRD quote was matched verbatim (whitespace-normalised) against `workspace/PRD.md`. No `skip`/`xfail`/placeholder anywhere. pyflakes clean (also removed a stale `make_frozen_project` import from `test_04`).

## Verification run

`prd-bench-local-run --isolation per-test-server --timeout 120` against `workspace/implementation`: **157/157 passed, 0 failed, 0 errors (407 s)**. Note for whoever runs the sweep: with the default `--timeout 30` on this loaded host every test ERRORs at server restart (matches the known lsof/boot-contention artifact) — `--timeout 120` is required.

## PRD gaps found and left as gaps

1. **Segment `version` after a simulation run.** §2.4 says `version` "increases by exactly 1 on every mutation" and §3.3 says the run "refreshes `flow_share_bps` and `derated_capacity_cph` on every segment", yet §3.3 never states a segment-version side effect. The corner recipe asserts `version == 2` (run does not bump); the implementation returns 4 (two bumps per run). Not uniquely derivable, so `test_13` now asserts only the §3.2-derived `revised == before + 1`.
2. **Scrap → `REBASELINE_REQUIRED` with no window.** §3.5 states it unconditionally, but §2.6 calls link 3 "caused by that cancellation", i.e. conditional on a `SCHEDULED` window existing; the implementation takes the §2.6 reading. Assertion dropped from the `ERR_LOT_SCRAPPED` test; the transition is still fully covered in `test_05`, where a window is present and both readings agree.
3. **Recipe enum leak.** The rbac instance `design_freeze_and_simulation_are_refused_across_the_two_integrator_desks` triggers a run with `method: "DETERMINISTIC"`, an undeclared value; the test uses `DETERMINISTIC_STEADY_STATE` and asserts only the role denial rather than an ungrounded band-2-before-band-5 precedence claim.

## Step 6: Generate implementation — 2026-09-02T18:32:43.954Z

(Completed concurrently with Step 5; logged after it for readability.)

The implementation is complete, validated, and cleaned up.

## Deliverable
`/home/ubuntu/github/CodingPRD/tasks/task_2431_conveyor_system_manufacturing_integration/workspace/implementation/` — 20 files, no `__pycache__`, no data files:

- `start.sh` (executable; `cd "$(dirname "$0")"`, conditional `pip install -r requirements.txt` only when Flask is missing, then `exec python3 app.py`), `requirements.txt`, `app.py` (blueprint registration, per-request store lock, full error-handler chain, `0.0.0.0:$PORT` default 10000)
- Infrastructure: `store.py` (14 in-memory dicts + logical clock at `2026-08-01T00:00:00Z`), `errors.py`, `response.py`, `auth.py`, `validate.py`, `serializers.py`, `lookups.py`
- Domain services: `services/calculations.py`, `services/cascade.py`, `services/scheduling.py`
- Routes: `routes/projects.py`, `design.py`, `shop.py`, `site.py`, `commercial.py` — all 45 declared endpoints plus `POST /_clock/set_current_utc`

Constraints honored: storage is process-local dicts only (a `grep` for `sqlite|json.load|pickle|open(` across the package returns nothing), every boot starts empty with no seeded rows, and nothing under `test_suite/`, `test_helpers/`, the design YAMLs, or any sibling `task_*/` was read.

## Validation this pass
Booted via `bash /abs/path/start.sh` from `/` (foreign cwd) — ready on the 3rd 250 ms poll, so per-test relaunch latency is fine. Two throwaway end-to-end scripts (`/tmp/conv_smoke.py`, `/tmp/conv_smoke2.py`, not part of the deliverable) both pass back-to-back against one fresh process: `ALL SMOKE CHECKS PASSED` and `ALL CASCADE CHECKS PASSED`.

New coverage added this pass (all green, no implementation changes needed):
- Design-reopening cascade: approving a `scope_delta_cph != 0` order bumps `design_version`, clears `design_frozen_at`, returns delivery to `DESIGN`, marks runs `STALE`, window `BLOCKED_STALE_DESIGN`, lot `HOLD`; `required_throughput_cph` untouched (PRD §274) and repricing to 102,515,000. Reverse release: a compliant fresh `DEGRADED_AVAILABILITY` run restores the window to `SCHEDULED` and the lot to `STAGED` (FAT credit lost, matching PRD §112).
- Scrap-unwind: three failing FAT attempts → `SCRAPPED`, window `CANCELLED_LOT_SCRAPPED` with `closed_at`, project `REBASELINE_REQUIRED`, further lot ops 409, and a replacement lot returning the project to `IN_FABRICATION`.
- Simulation arithmetic: MERGE 2-inbound derate (9600 bps → effective 960, bottleneck `M`, shortfall 1040), freeze without a degraded run 409, shortfall freeze 422, split-share total != 10000 → 422, missing `source_share_bps` → 422.
- Negotiation bounds: ceiling breach 422, `round_no` 2→3 then round-limit 409, REJECT leaving `commercial_status` `CLEAN` without repricing.

Two environment notes worth remembering: `pkill -f "python3 app.py"` / `pgrep -f "python3 app.py" | xargs kill` kills the tool's own shell wrapper (exit 144) because the wrapper's command line contains the pattern — use a bracketed pattern like `ap[p].py`. That pkill also took down other `app.py` servers on the host, which the per-test-server runner would relaunch anyway.

**Orchestrator note (clock endpoint):** the implementation's `POST /_clock/set_current_utc` is NOT an untraced addition — it is declared in `PRD.md` §4 (endpoint table line 358, `ProjectDirector`) and its semantics are stated in §2.4 ("An administrative test-driving capability, restricted to a `ProjectDirector`, sets the clock to an instant supplied as `to_iso8601`"). No implementation-hacking finding.

## Step 7: Test-and-fix loop — 2026-09-02

Ran the mandated 8-round parallel stability sweep (`setsid nohup`, `--isolation per-test-server --timeout 120 --test-timeout 30`, one runner-claimed port per round). **All 8 rounds: 157/157 passed, 0 failed, 0 errors, 0 skipped** (304–307 s per round; 8 rounds concurrent).

No iteration was needed: zero failing tests in the union across all 8 rounds, so no test was deleted, no `test_helpers/` fixture changed and no `implementation/` change was made. Integrity spot-checks alongside the sweep: no `skip`/`xfail` anywhere in `test_suite/` or `test_helpers/`; `store.py` boots 14 empty dicts with the logical clock at `2026-08-01T00:00:00Z` and no seeded rows; grep for `sqlite|pickle|json.load|shelve|open(` across `workspace/implementation/` returns nothing.

Results files retained at `workspace/implementation/results.{1..8}.json`; sweep console log at `workspace/sweep.log`.

## Step 7: Run tests and iterate (canonical orchestrator entry — verbatim subagent summary) — 2026-09-02T19:52:24.836Z

(Note: the Step 7 subagent appended its own preliminary entry above at line 156. This is the orchestrator-owned canonical entry carrying the subagent's returned summary verbatim, per the skill's worklog contract. Nothing above was overwritten.)

The task is complete — the suite was already green and stable, so no fixes were required.

## Summary

**Iterations run:** 1 (a single 8-round parallel sweep; it came back clean, so the loop exited).

**Sweep configuration:** exactly as mandated — `setsid nohup`, all 8 rounds launched concurrently and joined with `wait`, `--isolation per-test-server --timeout 120 --test-timeout 30`, no `--api-url` (runner claimed a free port per round). No reaping symptoms: every round ran to completion with its own ~305 s duration, no `Terminated`, no `RemoteDisconnected`, and all 8 `results.$i.json` files were read off disk.

**Final sweep, per-round passed/total read from the 8 results files:**

| round | result |
| --- | --- |
| results.1.json | 157/157 passed, 0 failed, 0 errors, 0 skipped (305 s) |
| results.2.json | 157/157 passed, 0 failed, 0 errors, 0 skipped (305 s) |
| results.3.json | 157/157 passed, 0 failed, 0 errors, 0 skipped (305 s) |
| results.4.json | 157/157 passed, 0 failed, 0 errors, 0 skipped (307 s) |
| results.5.json | 157/157 passed, 0 failed, 0 errors, 0 skipped (304 s) |
| results.6.json | 157/157 passed, 0 failed, 0 errors, 0 skipped (305 s) |
| results.7.json | 157/157 passed, 0 failed, 0 errors, 0 skipped (305 s) |
| results.8.json | 157/157 passed, 0 failed, 0 errors, 0 skipped (305 s) |

Union of failing tests across all 8 rounds: **empty**. No flakiness surfaced — no test passed in some rounds and failed in others.

**Tests deleted:** none. The diagnostic protocol (STEP 0–3) was never entered because there was no failing-test union to triage.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none. No PRD-required check was weakened and nothing was added to the implementation.

**Integrity spot-checks performed instead of fixes** (to confirm the green result wasn't the product of a pre-weakened artifact):
- No `pytest.mark.skip`, `pytest.mark.xfail`, or `pytest.skip` anywhere in `test_suite/` or `test_helpers/`.
- 157 `def test_` functions present, matching the 157 collected per round — no silent collection loss.
- `workspace/implementation/store.py` initialises 14 empty in-memory dicts plus the logical clock at `2026-08-01T00:00:00Z`; zero seeded rows. Grep for `sqlite|pickle|json.load|shelve|open(` across the implementation package returns nothing, so storage is process-local dicts only.

**Artifacts left on disk:** `workspace/implementation/results.1.json` … `results.8.json` (sweep evidence) and `workspace/sweep.log`. Stale `__pycache__` directories created by the run were removed.

One note worth relaying: the Step 5 worklog entry warned that a low boot timeout makes every test ERROR at server restart on this loaded host. The mandated sweep already uses `--timeout 120`, which was sufficient — `--test-timeout 30` needed no raising, and no round showed restart contention errors.

### Orchestrator independent verification of the sweep (per known Step-7 failure mode)

A Step 7 subagent can report a clean sweep without leaving evidence behind, so the orchestrator re-read the artifacts directly rather than trusting the claim:
- All 8 files `workspace/implementation/results.{1..8}.json` exist on disk (~52 KB each, mtime 2026-09-02 19:38).
- Parsed each with `json.load`: every round reports `passed=157, failed=0, errors=0, skipped=0, total=157`, durations 304.4–307.0 s. No round missing, no round partial.
- `workspace/sweep.log` tail confirms the runner's own `Results: 157/157 passed, 0 failed, 0 errors, 0 skipped` and a normal port release — no `Terminated`, so no reaping.
- `grep -rn 'mark.skip|mark.xfail|pytest.skip' test_suite/ test_helpers/` → 0 hits; `def test_` count → 157, matching `total` in every results file.

Verification passed. The clean 8-round sweep is real.

## Step 8: Finalize PRD — SKIPPED — 2026-09-02T19:53:00.000Z

Skip condition from the skill is satisfied exactly: Step 7 exited on its **first** 8-round sweep with **0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes** — zero iterations beyond the baseline. `PRD.md` therefore already determined every behavior the implementation exhibits at every site the test suite exercised, and there is no `<step_7_diff>` to hand off. No subagent was spawned and `workspace/PRD_FINALIZED.md` is deliberately absent; Step 9 will consequently start from `workspace/PRD.md`.

Orchestrator judgement note (recorded because this pipeline runs non-interactively and no one can be consulted): the three PRD gaps Step 5 reported — segment `version` bumping on a simulation run, the scrap→`REBASELINE_REQUIRED` cascade when no `SCHEDULED` window exists, and the `DETERMINISTIC` enum leak in one rbac recipe — were resolved by the test generator at generation time by *narrowing the assertions to PRD-derivable claims*, not by any Step 7 fix. They are genuine residual PRD silences against the implementation, but they are out of Step 8's hard scope (which is strictly `<step_7_diff>` items, of which there are none). They fall squarely inside Step 9's full-scan mandate and are flagged for it there.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-02T20:03:31.778Z

Done. `workspace/PRD_COMPLETED.md` written.

## Source vs completed

| | PRD.md | PRD_COMPLETED.md |
|---|---|---|
| lines | 411 | 413 (+2, both new §5 table rows) |
| chars | 90,820 | 96,592 (**+5,772**) |

22 existing lines revised in place, 2 lines appended to the §5 table. No new sections, no new paragraphs.

## Counts
- **ambiguity-pins: 17**
- **mismatch-revisions: 7**

## The three upstream residuals — verified before writing
- **(a) confirmed, with a nuance the brief did not state.** `calculations.py:216-222` bumps a segment's `version` **only when the refreshed `(flow_share_bps, derated_capacity_cph)` pair actually differs** from what is stored; a numerically-unchanged segment is not bumped. Pinned that way, not as an unconditional bump.
- **(b) confirmed.** `cascade.py:71-79` gates the `IN_FABRICATION → REBASELINE_REQUIRED` step on `cancelled_any` — i.e. the §2.6 conditional reading. §3.5's unconditional prose was revised; §2.6 already read correctly and was left alone.
- **(c) confirmed.** `projects.py:49` declares exactly `("DETERMINISTIC_STEADY_STATE", "DEGRADED_AVAILABILITY")`, mandatory, `req_enum` → `ERR_INVALID_REQUEST` on omission or any other value.

## Changes

- §2.1 — revise — ambiguity — a header present but empty/whitespace-only counts as absent for `ERR_UNAUTHENTICATED` — `auth.py:20`
- §2.3 — revise — ambiguity — a non-integer-parseable `limit`/`offset` is also `ERR_INVALID_REQUEST` — `validate.py:120-133`
- §2.4 — insert — ambiguity — version accounting is once per row **per request**: a row mutated twice in one request still advances `version` by exactly 1; a row created by the request stays at 1 — `store.py:119-137`, `store.py:90-103`
- §2.4 — revise — ambiguity — `to_iso8601` is mandatory and must parse; the clock endpoint answers 200 with an empty `data` object — `projects.py:309-322`
- §2.11 — insert — ambiguity — multi-identifier bodies resolve left to right in a fixed order (`project_id` first, `staging_bay_id` before `segment_codes`, `site_zone_id` before `fabrication_lot_id`, `from_segment_id` before `to_segment_id`) — `shop.py:70-79`, `site.py:84-86`, `design.py:129-131`
- §2.12 band 5 — revise — ambiguity — required string fields must be non-blank; an integer field carrying a non-integer (booleans included) fails in this band — `validate.py:24-36`
- §3.2 — revise — ambiguity — on segment revise, an omitted field is left as-is while an explicit null `source_share_bps` clears it; a revision supplying no revisable field still succeeds and still advances `version`/`design_version` — `design.py:92-108`
- §3.3 — revise — ambiguity — `method` mandatory, domain exactly the two values, otherwise `ERR_INVALID_REQUEST`; a run consults no `delivery_status`; response is `201 Created` — `projects.py:140-148`, `projects.py:182`
- §3.3 step 3 — revise — **mismatch** — PRD said the minimum is taken "across all of the project's segments"; impl skips segments whose `flow_share_bps` is 0 and, when none carries flow, reports `effective_throughput_cph` 0 with both bottleneck fields null — `calculations.py:228-245`
- §3.3 — insert — ambiguity **(a)** — the per-segment refresh is a row mutation: each segment whose pair changed bumps its own `version`/`updated_at`; unchanged segments are not bumped; a run never advances `design_version` — `calculations.py:216-222`
- §3.4 — revise — ambiguity — rework release from `FAT_FAILED` does not consult project `delivery_status` and does not touch the project; `fat_attempt_count` at 3 and any other lot status (incl. `HOLD`) → `ERR_LOT_INVALID_STATE` — `shop.py:148-178`
- §3.5 — revise — **mismatch (b)** — `REBASELINE_REQUIRED` fires only when at least one `SCHEDULED` window was actually cancelled; otherwise the project stays `IN_FABRICATION` unbumped — `cascade.py:71-79`
- §3.6 — revise — **mismatch** — on completion the lot advances to `INSTALLED` only if it is still `FAT_PASSED`; a lot on `HOLD` via a sibling window's block is left untouched and unbumped — `site.py:254-256`
- §3.6 — revise — **mismatch** — the 10000-bps zone-share total is re-checked on **every** start, not only the very first — `site.py:209-214`
- §3.6 — revise — ambiguity — `abort_reason` is mandatory and non-blank, and being a body-shape rule is decided ahead of the `IN_PROGRESS` check — `site.py:274-277`
- §3.7 — revise — ambiguity — certificate `bottleneck_availability_pct` takes the greatest-`created_at` qualifying degraded run and is null if none exists — `commercial.py:257`, `commercial.py:264-266`
- §3.7 — revise — ambiguity — issuance is not gated on `delivery_status`; an already-`ACCEPTED` project still meeting the three gates may be issued a further certificate, `delivery_status` staying `ACCEPTED` — `commercial.py:278-280`
- §3.8 — revise — **mismatch** — §3.8 read as an unconditional return to `DESIGN`; impl resets only from `DESIGN_FROZEN`/`IN_FABRICATION`/`CUTOVER`/`REBASELINE_REQUIRED` and otherwise leaves the posture alone — `cascade.py:86-93`
- §3.8 — insert — ambiguity — a scope-bearing approval leaves the project's `version` exactly 1 higher, not 2 — `commercial.py:174-181`, `store.py:130-137`
- §3.9 — revise — ambiguity — provisioning answers 200 with the updated **project** object; each changed part line bumps once for the run, and lines left numerically identical (every `MINOR` line included) are not bumped — `projects.py:225-227`, `calculations.py:288-332`
- §3.9 — revise — ambiguity — a null or 0 snapshot `bottleneck_availability_pct` leaves the `OBSERVED_AVAILABILITY` basis rate unmodified, collapsing it onto `NAMEPLATE` — `calculations.py:423-430`
- §3.9 — revise — **mismatch** — `ERR_CROSS_PROJECT_REFERENCE` on dispute filing is unreachable: the ownership check compares against the project reached *through* the certificate, so a foreign certificate reports `ERR_NOT_PROJECT_CUSTOMER` — `commercial.py:300-309`
- §4 — revise — **mismatch** — "running a simulation" added to the `201 Created` list; the §4 prose omitted it while impl returns 201 — `projects.py:182`
- §5 — insert — ambiguity — two catalogue rows for the transport-level codes impl emits: `ERR_NOT_FOUND` (404, unrouted path) and `ERR_METHOD_NOT_ALLOWED` (405) — `app.py:53-61`

Nothing was taken from `test_suite/` as authority; tests were consulted only where they happened to corroborate impl behavior. `SCAFFOLD*.yaml` and `worklog.md` were not read.

### Orchestrator verification of Step 9 output

- `workspace/PRD_COMPLETED.md` exists: 413 lines / 96,592 chars vs PRD.md's 411 / 90,820.
- Heading walk is intact at 29 headings (identical to PRD.md), and the file ends on a complete §5 table row (`| ERR_METHOD_NOT_ALLOWED | 405 Method Not Allowed |`) — not truncated mid-sentence.
- §5 now carries 50 `ERR_` rows = the original 48 plus the two transport-level codes; consistent with "no new sections".
- `workspace/PRD_FINALIZED.md` correctly absent (Step 8 skipped).
- `find workspace/implementation -newermt "2026-09-02 19:39"` excluding results files returns nothing, confirming Step 9 changed no implementation code — so the verified 8×157/157 sweep remains the standing evidence for `implementation/`.

## Pipeline complete — 2026-09-02T20:03:31.778Z

All nine steps finished. Step 8 was skipped under the skill's explicit skip condition; every other step ran and its artifact is on disk.
