# Worklog — task_2552_transportation_procurement_freight_bid_management

## Step 1: Create task directory — 2026-09-03T09:26:55.811Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2552_transportation_procurement_freight_bid_management` and its `workspace/` subdirectory. Index 2552 was pre-assigned by the invocation (no scan/allocation performed, per instruction, to avoid collision with the up-to-32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-03T11:32:54.248Z

All three artifacts are complete and the lint is clean.

## Files

| File | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_2552_transportation_procurement_freight_bid_management/SCAFFOLD.yaml` | 3790 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2552_transportation_procurement_freight_bid_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2379 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2552_transportation_procurement_freight_bid_management/SCAFFOLD_CORNER_DESIGN.yaml` | 2848 |

Top-level keys verified: `SCAFFOLD.yaml` carries neither design key; the other two carry exactly `scaffold_difficulty_design` / `scaffold_corner_design`.

## SCAFFOLD.yaml counts (§1.0–§1.7)
- 14 entities, 13 state machines, 2 concurrency rules (OCC), 13 calculations, 18 validation rules, **61 endpoints**, 62 errors, 5 roles
- profile: `multi_party_negotiation` / `quota_allocation`, flat topology, cyclic state shape, `segregation_of_duties`, layers `optimistic_concurrency` + `cascading_side_effects` + `dual_variant_calculation` + `selector_policy`, `difficulty_level: expert_plus`

## §1.8 difficulty design
**9 Difficulty Rules / 20 instances** (>=2 differentiated instances per rule), covering dual-variant calculation, combinatorial formula ordering, non-linear (cyclic + parallel-dimension) state machines, 3-5 link transitive cascades, priority-pair validation conflicts, boundary/precision, cross-entity state dependency, half-open temporal overlap (rate intervals, mini-bid window/cooldown/rolling quota) and compensating invariants (volume and money conservation).

## §1.9 corner design
**102 instances** across all nine claim-extraction-guide sections — 76 with full `test_recipe`s, 26 `excluded_because` stubs whose `difficulty_instance` citations all resolve to real §1.8 instance names:
entities 14 (1 stub), state_machines 29 (8), calculations 15 (5), validations 13 (5), endpoints 8 (2), errors 8 (1), rbac 5 (0), cross_cutting_complexity_layers 8 (4), consistency_model 2 (0).
All 62 error ids are reachable except `ERR_AWARD_SHARE_EXCEEDED`, which is deliberately delegated to the §1.8 boundary instance (the waterfall floors allocations to the cap, so it can only be provoked there).

## Lint verdict (verbatim)
```
Coverage
  §1.5 endpoints declared:    61
  §1.1 entities declared:     14
  §1.8 instances scanned:     20
  §1.9 instances scanned:     76
  Calls scanned (§1.8+§1.9):  769

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Notes for downstream steps: the corner file's header defines a shared `CHAIN:AWARDED_CONTRACT` setup macro (S1–S12 with verified literals — contract total 1267629.99, composite 90.60, objective 41.09/42.65) that every recipe references instead of repeating setup; the constraint hard-won during generation is that invitations can only be created while a BidEvent is `LANES_LOCKED`/`INVITING`, so all multi-carrier recipes invite everyone before round 1 opens. The pre-existing `worklog.md` and empty `workspace/` in that directory were left untouched, and no sibling task was read.

Orchestrator verification: all three files parse as YAML; top-level keys confirmed correct.

## Step 3: Copy shared files — 2026-09-03T11:33:09.525Z

Copied `./INSTRUCTION.md` to `tasks/task_2552_transportation_procurement_freight_bid_management/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T11:51:35.983Z

PRD generated and verified.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2552_transportation_procurement_freight_bid_management/workspace/PRD.md` — **638 lines, 122,148 bytes**. Built incrementally (one `Write` + five `cat >>` heredoc appends + three targeted edits); `wc -l` checked after every append.

## Section outline
- `# Freight Bid Management API — Product Requirements Document`
- `## 1. Introduction` (3 paragraphs from the scenario)
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User Roles and Access Control · 2.2 API Response Structure · 2.3 Pagination · 2.4 Collection Reads, Filters and Ordering · 2.5 The Logical Procurement Clock · 2.6 Common Resource Properties · 2.7 Money, Rates and Rounding Discipline · 2.8 Version Guards on Scenario and Amendment Writes · 2.9 The Rule Evaluation Ladder · 2.10 Carrier Standing as a Portfolio-Wide Gate · 2.11 Segregation of Duties Between Award and Signature · 2.12 Cascade Discipline, Rollups and Conserved Quantities
- `## 3. Business Logic & Workflows` — 3.1 Carrier Registration and the Qualification Fork · 3.2 Carrier Standing Over Time: Scorecards and Composite Re-Scoring · 3.3 Preparing the Lane Package and Freezing the Baseline · 3.4 Inviting Carriers and Opening Negotiation Rounds · 3.5 Rate Submission, Evaluation and Ranking · 3.6 Optimisation Scenarios, the Allocation Waterfall and the Routing Guide · 3.7 Allocation Governance and the Award Commit · 3.8 Contract Execution, Rate Loading and Go-Live · 3.9 Live Tendering, Mini-Bids and Mid-Contract Adjustment (9 subsections)
- `## 4. Endpoint Definitions` (4-column table)
- `## 5. Error Code Catalogue` (2-column table)

## Coverage verified
- **Endpoints: 61/61.** All 61 scaffold paths grep-matched; §4 table has exactly 61 data rows and exactly 4 columns.
- **Errors: 62/62.** All 62 error IDs present; §5 table has exactly 62 data rows and exactly 2 columns.
- **Ends at a real section boundary:** last line is the final `ERR_NO_FEASIBLE_ALLOCATION | 422` row of the §5 table — complete row, complete table, complete final section, no audit footer, no mid-sentence truncation.

## Hard Contract reports
**Contract 1 — Field-Name Coverage: PASS.** Required set = 176 entity field names ∪ 95 endpoint input/query/path identifiers = **185 unique names**. Two verification passes run mechanically against backtick-extracted tokens. Pass 1 found 2 missing (`volume_discount_pct`, `accessorial_allowance_pct` — described as "the discount rate"/"the allowance rate" in §3.8); both fixed by naming them explicitly. Pass 2: **0 missing / 185 present**.

**Contract 2 — Rule Coverage: PASS.** Validation `priority` ladder stated as an explicit ascending 18-rung list in §2.9 with "the first violated check decides the response" plus three worked precedence consequences; all `applies_to` endpoint sets enumerated exhaustively per rung. Both `concurrency_rules` in §2.8 as write_endpoint + `expected_bid_event_version`/`expected_contract_version` + mismatch rejection + `ERR_STALE_BID_EVENT_VERSION`/`ERR_STALE_CONTRACT_VERSION` at 412, framed purely as stale-version (grep confirms zero occurrences of "simultaneous", "race", "concurrent", "at the same time", "first-writer"). All 6 multi-link cascades stated link-by-link (5-link award commit, 3-link tender-risk, 3-link mini-bid apply + 3-link compensating revert, 3-link scorecard publish, 3-step optimisation supersede, 4-link backup promotion, 4-link go-live cutover). All field defaults/initial values/types stated. Sibling-branch symmetry held for the four `decision_outcome` branches, accept/decline, apply/revert, and suspend/reinstate/disqualify. Tail: all 13 state machines' transitions, all 13 calculation formulas with pinned rounding order and every constant value, all 18 validation conditions matched to their error_ids, and all 37 endpoints carrying side_effects. Mechanical check: 0 validation error IDs missing; all calculation constant values present (the 3 flagged as "missing" were composite strings — `[0.5, 0.3, 0.2]` and the two tier tables — whose components are all spelled out in prose). Zero fuzzy quantifiers.

**Contract 3 — §3 Path Purity: PASS.** Zero backtick tokens in §3 begin with `/`, are a bare HTTP method, or combine method+path; zero raw `METHOD /path` occurrences anywhere in §3. Endpoints referenced only by state-transition framing, role + action verb, or capability description. All paths confined to §2 and §4.

Withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `worklog.md`, sibling task dirs) were not opened, grepped, or referenced.

Two scaffold internal inconsistencies I resolved and should flag: (1) `RateRecord.rejection_count` — the field descriptions say "REJECTED or TIMEOUT" while the formula line says `outcome == REJECTED`; I used **REJECTED or TIMEOUT**, since it is the reading consistent with `acceptance_pct = 100 − rejection_pct` and with `scorecard_period_score` counting only `ACCEPTED` as acceptance. (2) `OptimizationRun.objective_score` is declared at 4 dp but its formula and the precision block both round to 2 dp; I used **2 dp**.

Orchestrator truncation check (per the known doc-generator failure mode): `tail -25` shows the file ending on the final complete row of the §5 error table — a genuine section boundary, not mid-sentence. 638 lines / 122,148 bytes. Endpoint table row count and heading outline verified independently. No regeneration needed. Also grep-confirmed the Step 2-only difficulty instruction ("expert") did not leak into PRD.md.

## Step 6: Generate implementation — 2026-09-03T12:31:12.000Z

Implementation complete and smoke-verified.

## Module layout (`workspace/implementation/`, 3,839 lines total)

**Foundation** — `app.py` (62), `store.py` (160, 14 in-memory dicts + logical clock + row/version bookkeeping), `errors.py` (88, all 63 error ids → HTTP status), `responses.py` (111, §2.2 envelope + §2.3 pagination), `auth.py` (51, headers/RBAC/ownership), `validators.py` (151, rung-4 body shape), `numeric.py` (49, Decimal + ROUND_HALF_UP), `helpers.py` (99, lookups/filters/§2.10 fitness gate), `start.sh` (8, guarded install + `exec python3 app.py`), `requirements.txt`.

**services/** — `scoring.py` (144), `lanes.py` (165), `bidding.py` (129), `optimize.py` (286), `contracts.py` (114), `tender.py` (106).

**routes/** (one blueprint per domain area) — `clock.py` (17), `carriers.py` (236), `reviews.py` (141), `scorecards.py` (55), `events.py` (401), `lanes.py` (58), `invitations.py` (93), `rounds.py` (158), `lanebids.py` (52), `optimization.py` (104), `allocations.py` (135), `contracts.py` (149), `raterecords.py` (159), `minibids.py` (357).

**Endpoint count: 61/61** — enumerated from `app.url_map` and matched one-for-one against PRD §4.

## Smoke test (port 21473, `bash start.sh`, then killed by that exact listener PID + its `start.sh` parent; no broad pkill)

Three scripted end-to-end passes, all green, envelope matching §2.2 exactly (`meta.api_request_id` = `req_` + 20 uppercase alnum, `api_request_timestamp` from the logical clock with 3 fractional digits, `response_type`, `data`; list responses add limit/offset/total_count/has_more):

1. **Full award chain** — clock set → 2 carriers registered/screened/qualified → event → lane validate → lock-lanes → invitations accepted → round → 2 lane bids → close → optimization run (COMPLETED, coverage 100.00) → routing guide (PRIMARY 300 / BACKUP_1 200) → both approved (lane `unallocated_volume_loads` 0, `awarded_coverage_pct` 100.00) → award commit → 2 DRAFT/PENDING_BOTH contracts.
2. **Contract → live → tender → mini-bid** — SoD correctly returned `ERR_SEGREGATION_OF_DUTIES` (403) for the approver's countersignature; carrier + a different shipper signer → FULLY_SIGNED/EXECUTED; rate staged (`committed_value_usd` 475200.00, contract base 475200.00, allowance tier 0.010, total 479952.00, `rate_load_status` STAGED) → load → go-live (allocation ACTIVE, contract LIVE, event AWARDED→LIVE); 5 tenders with 1 rejection → `rejection_pct` exactly 20.00 → record AT_RISK, lane UNDER_REBID, SYSTEM mini-bid auto-created with a 10-day window; duplicate `load_reference` → `ERR_DUPLICATE_LOAD_REFERENCE`; proposal (`adjustment_pct` 4.55) → apply (before 479952.00 / after 501768.00, contract AMENDED, lane back to AWARDED) → revert → contract EXECUTED, `amendment_count` 0, total **479952.00 exactly equal** to `contract_value_before_usd` (the §2.12 conserved round trip).
3. **Rejection cascade** — approving the PRIMARY debited the lane (unallocated 150), rejecting it credited back, set the bid NOT_AWARDED, promoted BACKUP_1→PRIMARY with `promoted_from_position`, and re-derived the promoted volume through the waterfall (150→300, lane unallocated back to 400 since a PROPOSED allocation holds no debit).

Storage is in-memory dicts only, empty on every boot — no seeding, preloading, hardcoded entities, SQLite, file or /tmp persistence anywhere (verified by grep and by the first list call returning `total_count: 0`).

Notable interpretation calls where the PRD leaves an error id unnamed: double-signature → `ERR_CONTRACT_NOT_FULLY_SIGNED`; proposal outside the closed window / proposer not routed on the lane → `ERR_MINI_BID_NOT_OPEN`; revert whose replacement is no longer LIVE → `ERR_RATE_RECORD_NOT_LIVE`; staging with a `routing_position` mismatching the allocation → `ERR_INVALID_REQUEST`. Error precedence follows the §2.9 ladder over §3's narrative order where the two disagree (e.g. mini-bid apply checks the rung-14 interval overlap before the rung-17 cap/floor re-checks).

Orchestrator note: Steps 5 and 6 were launched concurrently in a single assistant message, so this impl-gen subagent started before `test_suite/` existed — physical isolation from the tests held.

## Step 5: Generate unit tests — 2026-09-03T14:12:00.000Z

The suite is complete. Both output directories are final and verified.

## Files written

**`/home/ubuntu/github/CodingPRD/tasks/task_2552_transportation_procurement_freight_bid_management/test_helpers/`** (unchanged this session)
`__init__.py` 35, `api_client.py` 408, `api_errors.py` 155, `assertions.py` 487, `constants.py` 161, `factories.py` 324, `fixtures.py` 833, `test_users.py` 80, `types.py` 547.

**`.../test_suite/`** — `conftest.py` 50 plus 31 test modules, 13,519 lines total across both dirs. Files added in this final session:
- `test_30_version_guards_and_write_counting.py` — 427 lines, 5 tests (the two OCC guards + the version counter)
- `test_31_round_target_and_immediate_consistency.py` — 428 lines, 6 tests (round-2 reduction target selector + the two consistency-model instances)

Earlier modules: test_01 193/5, 02 181/4, 03 157/3, 04 307/6, 05 355/8, 06 285/6, 07 203/5, 08 264/6, 09 299/7, 10 421/8, 11 535/13, 12 452/9, 13 440/8, 14 460/9, 15 389/6, 16 447/6, 17 393/8, 18 263/5, 19 312/5, 20 356/7, 21 371/6, 22 439/6, 23 276/4, 24 343/6, 25 238/4, 26 256/5, 27 254/3, 28 321/6, 29 374/5.

## Totals and audit

- **190 tests, 190 `Design:` tags.** An AST pass confirms every test has exactly one tag, it is the last non-blank docstring line, it is well-formed, and `unknown tags: []`.
- **Queue A (§1.8 Difficulty): 20/20 non-stub instances translated, 0 skipped** (all nine rule_ids fully covered).
- **Queue B (§1.9 Corner): 76/76 non-stub instances translated, 0 skipped.** entities 13, state_machines 21, calculations 10, validations 8, endpoints 6, errors 7, rbac 5, cross_cutting 4, consistency_model 2. The remaining 26 corner instances carry `excluded_because` (explicit stubs deferring to a §1.8 instance already covered in queue A) and correctly produced no tests.
- **Citations: 567 quoted `PRD §x.y` snippets, 0 missing** — each is a literal substring of `workspace/PRD.md` after whitespace normalisation.
- `python3 -m py_compile` clean on all 41 files; `pyflakes` clean everywhere except the deliberate `# noqa: F401` re-export block in `test_helpers/__init__.py`; unused-import audit clean on the same basis. No file mentions "scaffold" or `implementation/`. `__pycache__` removed.

## Design-vs-PRD conflicts resolved in favour of the PRD (no weakening)

- The contract-OCC design claims the apply "stages and loads the amended" record; PRD §3.9 mints the replacement **directly in `LIVE`** — asserted per the PRD.
- The design's BFLX floor probe was sequenced after its accepted 2.4000 bid, where uniqueness (rung 7) would pre-empt the money rung; the 1.4900 attempt is therefore made **before** the newcomer's accepted bid, so `ERR_RATE_BELOW_FLOOR` (422) is genuinely the deciding rung.
- The design's "event version is 1 at the setup read" is not PRD-derivable (§2.6 states only that the counter increments per mutation), so the write-counting test asserts the **delta** from a read baseline instead of the absolute 1.
- Contract version after an apply is asserted as strictly advanced rather than exactly +1, since the same request also mints a rate record; the OCC claim (a stale version is refused, a fresh one lands) is asserted exactly.

No tests were executed, per the constraint, and `workspace/implementation/`, `worklog.md` and sibling task directories were never read.

## Step 7: Run tests and iterate — 2026-09-03T14:53:14.993Z

All 8 rounds are green. Final state: `190 / 190` in every round.

## Summary

**Iterations run:** 3 full 8-round parallel sweeps (`setsid nohup`, 8 concurrent rounds, `--isolation per-test-server`, no early exit). 184/190 → 187/190 → 190/190. Every failure was deterministic (identical in all 8 rounds each time); no load-induced or timing flakiness appeared.

**Tests deleted:** none. No test was deleted, skipped, xfailed, or weakened; total stayed 190 in every sweep. Every failure traced to a test-side claim that contradicted a verbatim PRD sentence, so each was corrected upward rather than removed.

**Fixes to `test_helpers/`:** none required — the shared fixtures were faithful. The PRD-violating setups were all test-module-local helpers.

**Fixes to `test_suite/`** (all test bugs under STEP 2 — setup or expectation contradicting verbatim PRD prose):

1. `test_01_bid_cost_evaluation.py` — `_bid_on_basis` walked the whole chain twice with the default SCAC, breaking §2.9 rung 13 ("`scac_code` is unique across all carriers"). Added `carrier_overrides` pass-through; the HISTORICAL leg now registers under `second_carrier_overrides()`.
2. `test_21_collection_reads_and_close.py` — same global-SCAC collision between the bystander carrier and `setup_awarded_event()`; bystander moved to the second carrier's SCAC. Also `active_primary_lane_count == 0` after the award contradicted the PRD §2.12 sentence the test itself quotes ("whose status is `EXECUTED` or `ACTIVE`") — corrected to `== 1` (consistent with `test_05`'s `== 2`).
3. `test_25_declared_counter_limits.py` — same SCAC collision across the two events; plus `_event_at_its_round_cap(3)` walked a 3-round event to *its own cap* and then expected the third round to succeed. Renamed to `_event_walked_to_round(rounds_allowed, walk_to=...)` so the roomier event carries the identical two-round history under a three-round cap. Also `decision_outcome is None` after two remediations contradicted §3.1 "In every branch the review records `decision_outcome`" (the reset is enumerated as arm results only) — corrected to `== "REMEDIATE"`.
4. `test_07_threshold_boundaries.py` — asserted the run was still `COMPLETED` after its guide was published, contradicting §3.6 "The run moves from `COMPLETED` to `PUBLISHED`" — corrected to `PUBLISHED`.
5. `test_22_scenario_supersede_rates_and_cutover.py` — the module constants assumed the cheaper *per-mile* bid wins PRIMARY, but §3.5 ranks on `cost_rank_score`, a service-adjusted **annual** cost. The 250-load bid at 2.2000 totals 670,395.00 versus the 300-load bid's 775,293.00, so it takes PRIMARY. Corrected `PRIMARY_GRANT_LOADS`/`BACKUP_GRANT_LOADS` to 250/300, both percentages to 45.45, `VOLUME_AFTER_APPROVAL_LOADS` to 300, and renamed the misleading `PRIMARY_BID`/`BACKUP_BID` to `BULK_BID`/`LEAN_BID`.

**Fixes to `implementation/`:** one, in `/home/ubuntu/github/CodingPRD/tasks/task_2552_transportation_procurement_freight_bid_management/workspace/implementation/services/optimize.py` — `supersede_history()` credited lane volume back and recomputed the lane's `awarded_coverage_pct`, but never recomputed the *event's* `coverage_pct` / `diversity_pct`, so the event rollup drifted (stuck at 45.45 after every allocation had left the `APPROVED/EXECUTED/ACTIVE/SUSPENDED_ROUTING` set). Now recomputes them once when anything was superseded, guarded so the event's `version` still advances exactly once per request (§2.12 cascade discipline, §3.3 `coverage_pct` definition). No data was seeded, no storage added — the store remains in-memory dicts only.

**Final per-round results** (`workspace/implementation/results.1..8.json`, all present and parsing, all `passed == total`):

| round | passed / total |
|---|---|
| 1 | 190 / 190 |
| 2 | 190 / 190 |
| 3 | 190 / 190 |
| 4 | 190 / 190 |
| 5 | 190 / 190 |
| 6 | 190 / 190 |
| 7 | 190 / 190 |
| 8 | 190 / 190 |

Orchestrator independent verification (per the known "clean sweep with no artifacts" failure mode): all 8 `results.N.json` exist on disk (~66 KB each, same 14:44 mtime), parse as JSON, and each reports `total 190 / passed 190 / failed 0 / errors 0 / skipped 0` with 190 test entries. `grep " Design:"` across `test_suite/` still totals 190 tags, confirming zero deletions and zero skip/xfail markers. Step 8 is NOT skipped: Step 7 made 1 `implementation/` fix and 5 `test_suite/` fixes.

## Step 8: Finalize PRD — 2026-09-03T15:04:09.533Z

Done. Both edits are in place.

## Line counts
- `PRD.md`: 638 lines / `PRD_FINALIZED.md`: 638 lines — **0.00% line delta** (2 lines revised in place, no lines added or removed, no new sections).

## Changes

- **§2.6 (Common Resource Properties, `version` bullet)** — *revise* — pinned that the `version` counter advances **at most once per request**: multiple links of one request mutating the same row each refresh `updated_at` but bump `version` only once for the request as a whole, and a row the request creates is written with `version` 1 and not advanced again by later links. — `implementation/store.py:127-138` (`touch()` dedupes against `_touched["ids"]`), `implementation/store.py:100-115` (`begin_request()` / `new_row()` pre-registers the new id), `implementation/app.py:26-29` (`before_request` hook resets the set).
- **§3.6 (Running a scenario, supersede-the-history paragraph)** — *revise* — (a) the credited lane's `awarded_coverage_pct` is recomputed from the credited figure; (b) when the supersession moved at least one allocation, the event's `coverage_pct` and `diversity_pct` are recomputed per §3.3 before the new run is created. — `implementation/services/optimize.py:189-221` (specifically 213 for the lane, 219-221 for the event), `implementation/services/lanes.py:143-165` (`recompute_coverage`).

## Items that needed **no** PRD edit
step_7_diff items 1-5 were all test-side bugs against prose the PRD already determines uniquely, so their text stays verbatim:
- SCAC collisions in `test_01` / `test_21` / `test_25` — §2.9 rung 13 already states `scac_code` is globally unique.
- `active_primary_lane_count` after award — §2.12 already pins the `PRIMARY` + `EXECUTED`/`ACTIVE` status set.
- `decision_outcome` after two remediations — §3.1 already says "In every branch the review records `decision_outcome`", and the `REMEDIATE` reset is enumerated as arm results only.
- Round cap fixture (`_event_at_its_round_cap`) — §3.4 already pins `current_round_no` vs `rounds_allowed`.
- Run `COMPLETED` → `PUBLISHED` — §3.6 already states the transition.
- `test_22` PRIMARY/BACKUP constants — §3.5 already ranks on `cost_rank_score` (service-adjusted annual cost), not per-mile rate.

## Per-edit pre-edit search log

**Edit 1 — §2.6 `version`**
- (a) Subject: what increments `version`, and how many times per request.
- (b) Paths enumerated: `grep '"version"'` across all of `implementation/` → only two writers, `store.py:110` (`new_row`, `version: 1`) and `store.py:138` (`touch`, `+1`); the three readers are guard/snapshot sites only (`routes/optimization.py:36`, `routes/minibids.py:202`, `routes/invitations.py:58`, `routes/events.py:222`). Counted `touch(` callsites per module (allocations 9, events 10, minibids 13, raterecords 8, reviews 8, optimize 7, tender 4, …) and read the multi-touch cascades individually to confirm the cap is observable and consistent: `routes/allocations.py:39-135` (reject touches the lane at link 3 and again after `rederive_lane_volumes` at link 4), `routes/optimization.py:45+69` (event touched inside `supersede_history` and again for `OPTIMIZING`), `routes/events.py:308-400` (award: contracts created then `recompute_committed_value` with no touch; event mutated at link 1 and touched once at the end), `routes/raterecords.py:91-116`, `routes/minibids.py:265-292`, `implementation/app.py:26-29`. Also swept §3 for any place the PRD claims more than +1 per operation — every occurrence is "increases by one", so the cap only reinforces existing prose.
- (c) Adjustment: widened the sentence to cover *creation* as well as mutation (`version` 1, not advanced again), since `new_row` pre-registers the id — without that clause the mini-bid-apply replacement record and the award-commit contracts would have been mis-described. Added the closing sentence tying the cap back to §3's existing "+1" statements so the two readings cannot be taken as contradictory.

**Edit 2 — §3.6 supersede-the-history**
- (a) Subject: rollup recomputation triggered by allocation supersession — the lane's `awarded_coverage_pct` and the event's `coverage_pct` / `diversity_pct`.
- (b) Paths enumerated via `grep -rn "recompute_coverage\|recompute_awarded_coverage"`: definitions at `services/lanes.py:97` and `:143`; every caller read — `services/optimize.py:213,220` (the Step 7 site), `routes/allocations.py:64` (approve, §3.7 link 2/3), `:104` and `:130-133` (reject, §3.7 link 3/4 and the closing recompute), `routes/events.py:363` (award link 3), `routes/raterecords.py:114` (go-live link 4), `routes/minibids.py:287` (apply resolving `UNDER_REBID`), `services/tender.py:105` (risk cascade). Also checked the paths that deliberately do *not* recompute event coverage — `publish_guide` (creates only `PROPOSED` allocations, outside the holding set), `commit_award` (`recompute_award_cost` only, per §3.7 link 1), mini-bid apply/revert (`recompute_award_cost` only; `SUSPENDED_ROUTING` ↔ `ACTIVE` never leaves the holding set) — to make sure the new sentence stays scoped to supersession and does not imply a recompute those paths omit.
- (c) Adjustment: scoped the event-rollup sentence to "when the supersession moved at least one allocation" to match the `superseded_any` guard exactly (a run-only supersession with no allocations recomputes nothing), and confined the `awarded_coverage_pct` clause to the `APPROVED`-only credit-back branch rather than to all superseded allocations. Changed "in three linked steps" to "in three linked steps followed by a rollup refresh" so the added behaviour does not read as a contradiction of the step count.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` is 8 lines total (exactly the 2 revised lines, §2.6 line 110 and §3.6 line 346); file is still 638 lines and ends on the final complete row of the §5 error table — not truncated by the copy-and-edit.

## Step 9: Complete PRD — 2026-09-03T16:13:54.668Z

Orchestrator decision (recorded per the autonomy instruction): rather than one monolithic PRD-vs-implementation scan, Step 9 was run as **three sequential file-partitioned passes** over a single shared `PRD_COMPLETED.md`. A single-pass scan over a 638-line PRD against a ~3,900-line implementation has a known failure mode of silently no-opping (output byte-identical to its input, i.e. the scan never really ran). Partitioning bounds each subagent's reading load while keeping the no-new-mismatch perspective global; each pass was told to read any file it needed for consistency but to edit only its own slice, and passes 2 and 3 were forbidden to `cp`/recreate the file so earlier edits survived. Passes ran strictly sequentially because all three edit the same file.

Partition: pass 1 = foundation (`app/store/errors/responses/auth/validators/numeric/helpers`) + `services/scoring.py` + `routes/{clock,carriers,reviews,scorecards}.py`. Pass 2 = `routes/{events,lanes,invitations,rounds,lanebids}.py` + `services/{lanes,bidding}.py`. Pass 3 = `routes/{optimization,allocations,contracts,raterecords,minibids}.py` + `services/{optimize,contracts,tender}.py`, plus final-pass duty to reconcile contradictions across all three.

### Pass 1 (foundation + carriers/reviews/scorecards) — 30 ambiguity-pins, 2 mismatch-revisions
Created `PRD_COMPLETED.md` by `cp` from `PRD_FINALIZED.md`, then targeted edits only; 639 lines on exit (638 + one new bullet in the §2.2 error-format list), all 28 changed lines within §2.1–§3.2. Highlights: `api_request_id` shape (`req_` + 20 chars `A-Z0-9`) and `api_request_timestamp` sourced from the logical clock; 201-on-create vs 200 elsewhere; unknown route/method and `ERR_INTERNAL` handling; pagination and filter edge semantics (empty string = omitted, exact string equality, null never matches, undeclared params ignored); accepted ISO forms for the clock and naive=UTC; decimals serialise as JSON numbers; rung-4 body-shape rules (JSON null = absent, decimal strings allowed, booleans not, non-finite rejected); §2.10 fitness-check ordering; review-arm re-run and wrong-arm-pair errors; `outcome` as the decision field name (mismatch); `REMEDIATE`/`REJECT` non-effects; the disqualification cascade's event-count recompute; and the exact composite-recompute trigger set (mismatch).
Confirmed already uniquely pinned (so later passes skipped them): the five roles and 401/403 split, the whole §5 status table against `errors.py` (all 65 ids), §2.6 system fields incl. the Step 8 `version`-at-most-once rule, `ROUND_HALF_UP` scales, carrier registration validation and status matrix, both review arms' formulas and the 70.00 floor, the remediation ceiling of 2, all four scorecard metrics and the publication cascade, and the composite lookback/weights/thresholds.

### Pass 2 (events/lanes/invitations/rounds/lane bids) — 21 ambiguity-pins, 5 mismatch-revisions
639 lines on exit; pass-1 inserts spot-checked present. Highlights: §2.10 corrected from "Six operations" to "Seven" (invitation acceptance) and the `WATCHLIST`-inclusive standing set corrected as non-universal — acceptance and allocation approval narrow to `QUALIFIED`/`CONDITIONALLY_QUALIFIED` (both mismatches); inbound range enforcement on event creation; which lane inputs are rounded on the way in; `ERR_LANE_NOT_VALIDATED` as one guard over three cases; the lock response body carrying the event; the five event rollups explicitly **not** derived together but each on its own trigger set (mismatch); the invite gate asking only "has the event left `DRAFT`"; `ERR_INVITATION_NOT_ACCEPTED` as the catch-all for non-`SENT` responses and for revocation of `DECLINED`/`REVOKED`; a decline not touching the event row; the revocation cascade following the *carrier* across events; round-open/close error precedence (`ERR_ROUND_STILL_OPEN` vs `ERR_ROUND_LIMIT_EXCEEDED` vs `ERR_ROUND_NOT_OPEN`); closing re-evaluating against state *as at closing time*; the round-target ceiling at 4 dp consulting only round `round_no − 1` and only non-`WITHDRAWN` bids; rank renumbering scoped to exactly four trigger points; and §3.7's "Four preconditions" corrected to "Five" plus the three 422 gates as one ladder rung ordered share → diversity → coverage (mismatch).

### Pass 3 (optimization/allocations/contracts/rate records/mini-bids) — 21 ambiguity-pins, 19 mismatch-revisions
645 lines on exit (+6 from three inserted paragraph breaks); pass-1 and pass-2 inserts spot-checked present, and both pass-2 hand-off invariants kept true. Highlights: run-creation and publication error precedence (`ERR_EVENT_NOT_OPTIMIZING`, feasibility before coverage); the run storing *resolved* constraint values; `diversity_pct` `0.00` on a FAILED run; guide materialisation leaving already-`SHORTLISTED` bids alone and scoping `NOT_AWARDED` to the latest `CLOSED` round on guided lanes; reject link 4's promotions scoped to the same run and independent, with a zero grant *keeping* its seat; the award commit's cost rollup taken after link 4 and leaving `award_cost_usd`/`savings_pct` at `0.00` until rates are staged; signature SoD above the state check and `DRAFT`-only move to `EXECUTED`; staging having no state precondition, FK order lane→carrier→allocation, and 4-dp quantisation; per-record value taking the fuel index from the *contract's* event and mileage from the record's own lane; the interval-overlap scan spanning every record system-wide; go-live links 2–4 conditionality and both carrier rollups; §2.7 4-dp inbound quantisation for staged and proposed rates; the tender-risk cascade's independent conditional moves and bypassed creation gates; recovery semantics; mini-bid cooldown counted only from still-`APPLIED` mini-bids with exactly 7 days passing; the 90-day quota window inclusive at both ends with `REQUESTED` system windows not consuming quota; the three distinct failures sharing `ERR_MINI_BID_NOT_OPEN` in fixed order; apply/revert guard ordering, the replacement record's clean metrics, `amendment_count` rising regardless and floored at 0 on revert, and the round-trip identity qualified to what impl actually restores.

**Final-pass consistency read — three genuine cross-pass contradictions found and fixed minimally:** (1) §2.9 rung 9 required `OPEN` to deny a mini-bid, contradicting §3.9's `REQUESTED`-or-`OPEN`, and omitted revert's `ERR_RATE_RECORD_NOT_LIVE`; (2) §3.5 called `SHORTLISTED` terminal, contradicting §3.6 publication and §3.7 links; (3) §2.9 rung 18's listed order implied coverage before feasibility, contradicting §3.6 while §3.7 cites "the rung-18 order" — the rung now fixes intra-rung order per operation. No others found.

### Orchestrator final verification
- `workspace/PRD_COMPLETED.md` exists: 645 lines / 153,004 bytes, up from `PRD_FINALIZED.md`'s 638 lines / 123,206 bytes (**+29,798 bytes, +24.2%**) — emphatically not byte-identical to its input, so the scan demonstrably ran.
- Ends on the final complete row of the §5 error-code table (`ERR_NO_FEASIBLE_ALLOCATION | 422`); structure intact at 5 `##` / 21 `###`, no new sections.
- Totals across the three passes: **72 ambiguity-pins, 26 mismatch-revisions, 98 changes**, plus 3 cross-pass contradiction fixes.
- `find workspace/implementation -name '*.py' -newermt '2026-09-03 14:45'` returns nothing: no implementation file was modified after the green sweep, so the 8 × `190/190` results in `workspace/implementation/results.{1..8}.json` remain valid for the delivered code. Step 9 changed documentation only.

Pipeline complete through Step 9.
