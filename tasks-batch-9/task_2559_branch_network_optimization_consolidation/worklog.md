# Worklog — task_2559_branch_network_optimization_consolidation

## Step 1: Create task directory — 2026-09-03T10:16:39.722Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2559_branch_network_optimization_consolidation` and `.../workspace` (pre-assigned path, index fixed by scenario number 2559 — no index auto-allocation performed).

## Step 2: Generate scaffold — 2026-09-03T12:35:19.254Z

All three artifacts are complete and the lint is clean.

## Files (all in `/home/ubuntu/github/CodingPRD/tasks/task_2559_branch_network_optimization_consolidation/`)

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` (§1.0–§1.7) | 3037 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8) | 1457 |
| `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9) | 3932 |

`SCAFFOLD.yaml` carries no `scaffold_difficulty_design` / `scaffold_corner_design` keys; each design file has exactly one top-level key.

## SCAFFOLD.yaml surface
`api_prefix: /distribution` — **12 entities** (MarketArea, Branch, PerformanceSnapshot, ConsolidationCase, RetentionForecast, CommunityImpactAssessment, ClosureNotice, StaffDisposition, PropertyDisposition, CustomerTransitionCampaign, DeNovoSitePlan, DepositObservation), 8 state machines (cyclic case loop, dual-axis StaffDisposition, tenure-forked PropertyDisposition diamond), 2 OCC concurrency rules, **19 calculations**, **48 validations** (priorities 1–48), **59 endpoints**, **48 error ids**, **7 roles** (role_model `segregation_of_duties`, entity-backed BranchManager), logical clock `/_clock/set_current_utc` defaulting to 2026-08-01.

## §1.8 — 18 instances, 2 per each of the 9 Difficulty Rules
`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`.

## §1.9 — 89 instances across all 9 guide sections (67 full recipes + 22 `excluded_because` stubs)
entities 13, state_machines 12, calculations 15, validations 31, endpoints 6, errors 2, rbac 4, cross-cutting complexity layers 4, consistency model 2. Every one of the 48 error ids is now triggered by some §1.8 or §1.9 recipe (last gaps closed this session: `ERR_TRANSITION_CAMPAIGN_NOT_LAUNCHED`, `ERR_REVISION_LIMIT_EXCEEDED`, `ERR_CASE_AUTHOR_REQUIRED`, `ERR_BRANCH_OWNERSHIP_REQUIRED`, `ERR_STALE_BRANCH_VERSION`). `selector_policy` was skipped deliberately — the claim-extraction guide has no row for it.

## Lint
```
  §1.5 endpoints declared:    59
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     67
  Calls scanned (§1.8+§1.9):  743

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## §1.5 audit findings the §1.9 pass forced back into the scaffold
- **8 read endpoints added (51 → 59)**: single-resource GET + filtered collection list for `PerformanceSnapshot`, `RetentionForecast`, `CommunityImpactAssessment` and `ClosureNotice`. Those four entities were reachable only through nested lists, so their FKs had no reverse-reachability and corner asserts like `ClosureNotice.{id}.status == WITHDRAWN` were unreadable through the API.
- `ERR_REVISION_LIMIT_EXCEEDED` §1.6 condition said "submit is requested…" while §1.4 priority 35 guards the **RETURN decision** — condition rewritten to match.
- Clock-sweep holdover side effect used `lease_end_date <=` while the `MARKETED -> HOLDOVER` transition requires `<` — §1.5 aligned to strict.
- `complexity_profile` comment claimed the case cycle is "bounded at 2 returns"; `REVISION_LIMIT` is 3 — comment corrected.

Orchestrator verification: all three files parse as YAML; `SCAFFOLD.yaml` top-level keys begin `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities` with neither design key present; each design file has exactly one top-level key.

## Step 3: Copy shared files — 2026-09-03T12:35:19.254Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T13:00:00.000Z

All three Hard Contracts now report PASS. The earlier "276 missing" report was a harness bug (the ```json fences in the verbatim §2.2 block made backtick counts odd, so inline-span pairing shifted); stripping fenced blocks first yields 2860 backticks = 1430 balanced pairs.

## Deliverable

`workspace/PRD.md` — **462 lines, 102,758 chars.** Ends at a complete table boundary (last row of the §5 error catalogue, `| `ERR_PROPERTY_TERMS_INCOMPLETE` | 422 |`). No truncation.

## Section list

- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control / 2.2 API Response Structure (verbatim block) / 2.3 Pagination / 2.4 Resource Identity, Timestamps and Versioning / 2.5 Request Rejection Precedence / 2.6 Version Pinning on Case-Critical Writes / 2.7 Units, Basis Points and Rounding Discipline / 2.8 The Logical Clock / 2.9 Cascade Integrity and the Two Conservation Invariants
- `## 3. Business Logic & Workflows` — 3.1 Trade Areas, Saturation Tiers and the Branch Register / 3.2 Branch Performance Scoring and Candidacy Banding / 3.3 Opening a Consolidation Case, Pairing the Survivor and Modeling Retention / 3.4 Governance Review: Submission, the Savings Chain and the Decision Branches / 3.5 Community Impact, Regulatory Lead Time and Notice Filing / 3.6 Workforce Transition: Notification, Redeployment and Severance / 3.7 Premises Disposition and ATM Retention / 3.8 Customer Transition Waves, Closure Execution and Unwind / 3.9 Post-Closure Runoff Surveillance, Market Remediation and De Novo Growth
- `## 4. Endpoint Definitions` — 59-row table (Method | Path | Description | Authorized Role(s))
- `## 5. Error Code Catalogue` — 48-row table (Error ID | HTTP Status Code)

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS.** `entities[].fields`: 157 required, 157 present, 0 missing. Endpoint `input` identifiers: 100 required, 100 present, 0 missing. All 11 path-parameter names present. All 59 endpoint paths present verbatim in backticks. All 48 error IDs and all 7 roles present in backticks. All 41 state-machine states present. All 92 enum constraint values present.

**Contract 2 — Rule Coverage: PASS.** (1) Validation priority order: all 48 validations rendered as an explicitly numbered 1–48 rejection-precedence list in §2.5, each paired with its error ID and `applies_to` scope; zero of the 48 error IDs absent from §2.5. (2) `concurrency_rules`: both OCC rules covered in §2.6 — `expected_branch_version` on case creation → `ERR_STALE_BRANCH_VERSION` (412), `expected_case_version` on retention-forecast creation and case decision → `ERR_STALE_CASE_VERSION` (412), including the "why". (3) Cross-entity side effects: all four `execute-closure` cascade hops, the `unwind-closure` reversal, the notice-withdrawal cascade, and the deposit-observation `de_novo_hold` → `APPROVED`/`HELD` cascade are all in §3.8–3.9. (4) `applies_to` scopes carried per-item in §2.5. (5) Field-level structured content: enums, defaults, patterns (`branch_code` two-letters-hyphen-three-digits), nullable conditions all present. (6) Sibling-branch symmetry: `DISTANCE_DECAY` vs `SEGMENT_MIX` retention forks, `LEASE` vs `OWNED` disposition-net forks, and the accept/rescind and execute/unwind mirror pairs are each stated on both sides. Tail: all 8 state machines' transitions, all 18 calculations (every 3+ digit numeric literal verified present in the prose), and every endpoint's side effects covered.

**Contract 3 — §3 Path Purity: PASS.** 933 backtick spans in §3; 0 start with `/`, 0 are bare HTTP methods, 0 combine method+path, 0 contain a `/` at all. Zero literal `/distribution` occurrences and zero bare method words anywhere in §3 prose.

## Fixes applied this pass

- Corrected a garbled clause in §3.7 (`atm_monthly_surcharge_surcharge` duplication) to read `atm_monthly_cost_cents` and `atm_monthly_surcharge_revenue_cents`.
- Five large cents constants were present only as written-out words plus dollar equivalents. Added the explicit digit forms (`12,000,000,000`, `100,000,000`, `40,000,000`, `15,000,000`, `15,000,000,000`) alongside so the implementer cannot mis-convert.

Also verified mechanically: every §4 row's method, path and role set matches the scaffold exactly (0 mismatches), and every §5 row's HTTP status matches the scaffold (0 mismatches). No pseudocode operators and no fuzzy quantifiers anywhere in the document.

The two withheld files were never opened, grepped, or referenced, and no sibling task directory was read.

Orchestrator truncation check (per the known doc-generator failure mode): `tail -12` shows PRD.md ending on the final complete row of the §5 error table, at a real section boundary — not mid-sentence. §5 contains 48 `ERR_*` rows and §4 contains 59 method rows, matching the scaffold's declared counts. Grep for `expert|scaffold|difficulty_design|corner_design|test_recipe` returns zero hits, so the Step 2 difficulty instruction did not leak into the PRD. No regeneration needed.

## Step 6: Generate implementation — 2026-09-03T13:43:00.000Z

Implementation complete and verified.

## Deliverable

`workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `app.py` | 77 | Flask app, blueprint wiring, global-lock middleware, error handlers |
| `core.py` | 259 | 48-entry error catalogue, in-memory `DB`, logical clock, record/versioning helpers, response envelope, `ROUND_HALF_UP` rounding |
| `validation.py` | 235 | roles, auth/authz, branch ownership, typed field extractors, pagination/filters |
| `calc.py` | 405 | all PRD constants + 17 calculations (scoring, retention, savings chain, severance, notice days, property carry, wave/runoff/ramp curves, site score) |
| `services.py` | 210 | cross-entity refreshers (market footprint, branch score, case savings), supersession, notice-window conflict, de-novo hold, clock advance |
| `routes_network.py` | 282 | market areas, branches, snapshots, on-demand `performance-score` |
| `routes_cases.py` | 552 | case lifecycle (create/submit/decision/revise/execute-closure/unwind/close-out), retention forecasts |
| `routes_regulatory.py` | 263 | impact assessments + finalize, closure notices + withdraw |
| `routes_disposition.py` | 390 | staff dispositions (notify/accept/rescind/sever), property dispositions (contract/settle) |
| `routes_growth.py` | 463 | transition campaigns, de novo plans, deposit observations, `/_clock/set_current_utc` |
| `start.sh` | 8 | executable launcher: `cd` to own dir, guarded flask install, `exec python3 app.py` on `$PORT` |
| `requirements.txt` | 1 | `flask>=3.0` |

Total 3,145 lines. **59 routes**, an exact 1:1 match with the PRD §4 endpoint table (58 under `/distribution` + `POST /_clock/set_current_utc`).

## Verification

- **Fresh boot / no seeding**: launched from a clean process, all 12 collections return `total_count=0`, `rows=0`. Storage is pure in-memory dicts — no SQLite, no file dump, no `/tmp` cache. `__pycache__` removed from the delivered dir.
- **Smoke test**: boot → `POST /distribution/market-areas` (201, correct `meta`/`response_type: object` envelope, derived `competitor_density_index=2`, `saturation_tier=UNDER_BRANCHED`) → `GET` read-back at `version 1` → unauthenticated request returns 401. Server killed by its exact listener pid on its own port; no broad pattern kill was ever used, and I also found and reaped one orphaned smoke server of mine from an earlier run on port 45590 by exact pid.
- **Five driver suites** (happy-path lifecycle, auth/precedence negatives, disposition/campaign/observation negatives, unwind/premises/ramp, de-novo-hold coupling) all finish with zero unexplained failures.
- **Field-set fidelity**: a programmatic diff of live GET-one responses against `SCAFFOLD.yaml` `entities[].fields` gives "entities with field diffs: 0" across all 12 entities.
- **Conservation invariants** hold numerically: market deposit total (34,000,000,000) identical before execution, after execution and after unwind; case headcount restored exactly across accept→rescind.
- **Numbers hand-checked** against PRD prose: composite 4973 / TRAILING_BLEND 5012, DISTANCE_DECAY retention 9600, savings chain 90,000,000 − 3,600,000 → 18 bps tier → 6,912,000 incentive → 79,488,000 net, severance 2,520,000, OWNED carry 1,800,000 → 4,200,000, lease-fork net −250,000, runoff month-12 forecast 3,840,000,000, ramp target 13,888,889 / 55,555,556, site scores 52/96/57.

## Fix made in this session

`routes_growth.py` `_apply_plan_observation` coded the four PRD §3.9 de-novo ramp rules as mutually exclusive `if/elif`, so a plan in `RAMP_REMEDIATION` that recovered on a month-12 observation at ≥9000 bps ended with the incoherent pair `ramp_status=MET` / `status=RAMP_TRACKING` and its branch stuck at `DE_NOVO_RAMPING`. Rewritten as sequential `if`s in the PRD's stated order so the recovery hop feeds the `RAMP_MET` hop; now yields `plan: RAMP_MET / MET / 9500, branch: ACTIVE`.

Three earlier "failures" turned out to be correct behaviour with wrong test expectations, all reconfirmed against the PRD: the revision limit guards the RETURN decision (rank 35) rather than `revise`; `ERR_BRANCH_NOT_ACTIVE` (PRD line 207) fires for a branch at `UNDER_REVIEW`; and on `execute-closure` rank 22 `ERR_NOTICE_PERIOD_NOT_ELAPSED` correctly outranks rank 24 `ERR_TRANSITION_CAMPAIGN_NOT_LAUNCHED` (PRD lines 113/115, restated in order at line 309).

Orchestrator note: Steps 5 and 6 were launched concurrently in a single assistant message, so this agent started before `test_suite/` existed on disk and could not have read the tests.

## Step 5: Generate unit tests — 2026-09-03T14:05:00.000Z

Stage 1 + Stage 2 are complete for `task_2559_branch_network_optimization_consolidation`.

## Files written

`test_helpers/` (1,918 lines)
`__init__.py` 34 · `constants.py` 116 · `types.py` 457 · `api_errors.py` 111 · `api_client.py` 381 (60 endpoint methods) · `test_users.py` 46 · `factories.py` 217 · `assertions.py` 194 · `fixtures.py` 362

`test_suite/` (5,767 lines, 103 tests)
`conftest.py` 56 · `test_01_trade_area_and_branch_register.py` 632 (18) · `test_02_branch_performance_scoring.py` 344 (6) · `test_03_case_opening_and_pairing.py` 444 (7) · `test_04_retention_forecasting.py` 268 (4) · `test_05_savings_chain_and_governance.py` 677 (12) · `test_06_community_impact_and_notices.py` 766 (12) · `test_07_workforce_transition.py` 723 (12) · `test_08_premises_and_atm_disposition.py` 368 (6) · `test_09_transition_waves.py` 418 (7) · `test_10_closure_execution_and_unwind.py` 501 (9) · `test_11_runoff_surveillance_and_de_novo.py` 570 (10)

## Coverage (design-index-only; verified mechanically)

- **Queue A (§1.8)**: 18/18 non-stub instances, **36 tests, exactly 2 per instance** — dual_variant_calc 4, combinatorial_formula 4, non_linear_state_machine 4, transitive_cascade 4, priority_pair_validation_conflict 4, boundary_precision_check 4, cross_entity_state_dependency 4, resource_temporal_overlap 4, compensating_invariant 4.
- **Queue B (§1.9)**: 67/67 non-stub instances, **67 tests, exactly 1 per instance** — entities 13, state_machines 9, calculations 11, validations 23, endpoints 4, errors 2, rbac 3, cross-cutting complexity layers 1, consistency model 1. The 22 instances carrying `excluded_because` were not translated.
- **Instances SKIPPED for PRD-first failure: none.** Every non-stub instance had verbatim PRD coverage that uniquely derives its outcome.

## Verification performed

- 103 test functions, each with **exactly one** `Design:` line as the final docstring line; 0 untagged, 0 dual-tagged, 0 tags pointing at non-existent or stub instances.
- **269 `PRD:` citations, all verbatim** against `workspace/PRD.md` (4 near-misses found and corrected: the density "to a whole number" clause, "Each/Every regulatory notice", the `REGULATOR` filing transition sentence, and "for a de novo plan").
- `py_compile` clean on all 20 files; every module imports; AST unused-import check reports `unused: []` for all 11 test modules; `pytest --collect-only` collects 103 tests; no "scaffold"/§/Table language anywhere; `__pycache__` removed.

## PRD-first corrections applied where the design yaml contradicted the PRD

- Approve-time branch state asserted as `UNDER_REVIEW` (PRD §3.4), not `CLOSURE_SCHEDULED`; a `SAVINGS_WATCH` assertion on a merely submitted case dropped (the flag is set only in the execution cascade).
- Withdrawal reason codes normalised to PRD-declared values (`COMMUNITY_PROTEST`, `REGULATOR_OBJECTION`).
- `contributing_snapshot_count` asserted per the PRD (1 under point-in-time), not the yaml's 3.
- The unwind-window recipe's setup omitted a `LAUNCHED` campaign, which the PRD makes a hard execution precondition; the setup was completed rather than the assertions weakened.

## Step 7: Run tests and iterate — 2026-09-03T14:21:10.000Z

All 8 parallel rounds pass 103/103. Exiting.

## Summary

**Iterations run:** 2 (first sweep: 99/103 in all 8 rounds, 4 deterministic failures; second sweep: 103/103 in all 8 rounds).

**Tests deleted:** none. All four failures traced to a test-helper bug, a test assertion applied at the wrong endpoint, and one implementation serialization bug — every asserted rule was verbatim PRD-covered.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `setup_notice_filed_case`: added an early return when the passed-in ctx already carries a `notice` and its case is at `NOTICE_FILED`. Without it, `_riverbend_executed()` (which feeds an already-notice-filed ctx back through `setup_executed_closure` → `setup_execution_ready_case`) fell through the `APPROVED`/`SUBMITTED` guard chain into `setup_submitted_case`, re-submitting a `NOTICE_FILED` case and getting a correct `ERR_CASE_STATE_INVALID` from the PRD-faithful implementation. This single upstream fixture bug caused 2 of the 4 failures (`test_10::test_05`, `test_10::test_06`) as "Setup step failed".
- Same file, `setup_execution_ready_case`: guarded the campaign and premises-disposition steps with `if "campaign" not in ctx` / `if "property" not in ctx`, so re-entering with an already-complete ctx does not attempt a duplicate wave/premises.

**Fixes applied to `test_suite/`:**
- `test_suite/test_09_transition_waves.py` — `test_04_a_wave_must_start_a_fortnight_after_the_notice_and_must_have_a_length` asserted the 14-days-after-`filed_on` rule at **wave creation**. PRD §3.8 states that rule only as a **launch** guard ("Launching a wave … the `wave_start_date` must fall at least 14 days after the `filed_on` date of the case's regulatory notice"); the only creation-time dating rule PRD names is "At creation the `wave_end_date` must fall strictly after the `wave_start_date`". Rather than delete, I moved the assertion to the endpoint PRD assigns it to: the nine-days-out wave is now created (201) and then rejected with `ERR_CAMPAIGN_LEAD_TIME_INSUFFICIENT` (422) on launch, with the campaign confirmed still `PLANNED`/`launched_on is None`. Dates/volume were chosen (`2026-08-10`→`2026-08-15`, 100 households ⇒ 20/day) so the extra wave does not overlap the accepted wave's half-open interval and cannot perturb the receiving branch's 40/day absorption capacity. No assertion was weakened; the exact `error_id` check is preserved and launch-time lead-time coverage (previously absent from the suite) was added.

**Fixes applied to `implementation/`:**
- `workspace/implementation/core.py` — `format_instant()` (used only for the clock's `current_utc` response field) rendered three fractional digits, producing `2026-11-01T00:00:00.000Z`. PRD §2.8 renders the logical clock verbatim without fractional digits ("Until the clock is set for the first time it reads `2026-08-01T00:00:00Z`"); the three-fractional-digit rule in §2.4 is scoped to resource `created_at`/`updated_at` and §2.2's to `api_request_timestamp`, neither of which `current_utc` is. Changed to `%Y-%m-%dT%H:%M:%SZ`. `utc_now_iso()` (which stamps `created_at`/`updated_at`/`api_request_timestamp`) was left at three fractional digits.

**Notes:** no flakiness observed — the failure set was byte-identical across all 8 rounds in iteration 1 and empty across all 8 in iteration 2. No `SCAFFOLD*` file was consulted for adjudication.

### Orchestrator independent verification of the Step 7 sweep

Per the known failure mode where a Step 7 agent claims a clean sweep without leaving artifacts, I parsed all 8 `results.*.json` myself: every round reads `103/103 passed, failed=0, errors=0, skipped=0`, all 8 files written at the same completion instant (14:21:10), and `grep -c Terminated workspace/sweep.log` is 0 — so the sweep ran under `setsid` and was not reaped. `grep` for `mark.skip`/`mark.xfail` across `test_suite/` and `test_helpers/` returns 0 hits, and the suite still contains 103 test functions (none silently dropped). Step 7 is genuinely green.

Step 8 is NOT skipped: Step 7 ran 2 iterations with 2 `test_helpers/` fixes, 1 `test_suite/` fix and 1 `implementation/` fix.

## Step 8: Finalize PRD — 2026-09-03T14:33:00.000Z

`PRD_FINALIZED.md` is written. Exactly one of the three `<step_7_diff>` items traced to a genuine PRD silence; the other two were test-side bugs against behavior the PRD already pins verbatim.

## Line counts
- `PRD.md`: 462 lines / 102,758 bytes
- `PRD_FINALIZED.md`: 462 lines / 103,196 bytes
- Delta: 0 lines (0.0%); 1 line revised in place, +438 bytes (+0.43%)

## Changes
- **§2.8 The Logical Clock** — *revise* — pinned the rendering of the clock response's `current_utc` to ISO 8601 UTC at whole-second precision with a trailing `Z` and no fractional digits, and explicitly scoped §2.2/§2.4's three-fractional-digit rule to `api_request_timestamp`/`created_at`/`updated_at` so it does not reach `current_utc` — `implementation/core.py:124-127` (`format_instant`), consumed at `implementation/services.py:207`.

## Pre-edit search log

**Edit 1 — §2.8 `current_utc` rendering**
- (a) **Subject:** the serialized textual form of server-emitted timestamp/instant values, specifically `current_utc`, and by contrast every other timestamp field the API emits.
- (b) **Impl paths enumerated:** grepped `format_instant|current_utc|to_iso8601` across all of `implementation/` — exactly three hits: definition at `core.py:124`, sole producer `services.advance_clock` → `services.py:207`, sole endpoint `routes_growth.py:458-463` (`POST /_clock/set_current_utc`); there is no GET clock endpoint and no other reader. Then grepped `utc_now_iso|clock_today_iso|clock_now|isoformat()` across all of `implementation/` to enumerate every *other* timestamp producer: `core.new_record:146` and `core.touch:169` (`created_at`/`updated_at`, three fractional digits), `core.base_meta:202` (`api_request_timestamp`, three fractional digits), and `clock_today_iso()` at `routes_disposition.py:138,220,384`, `routes_cases.py:318,392`, `routes_regulatory.py:121,152`, `routes_growth.py:135,260,421` (all date-only stamps) plus `core.date_plus:260` (`buffer_end_date`). Also read `validation.req_instant:163-180` to confirm the input side normalizes naive and offset instants to UTC before storage.
- (c) **Wording adjustment:** the first draft would have read as a general statement about instants, which would have contradicted `utc_now_iso()` at three call sites. I narrowed the claim to the `current_utc` field by name and added the explicit carve-out sentence naming `api_request_timestamp`, `created_at` and `updated_at` as still three-fractional-digit, so no other enumerated producer is redescribed. I deliberately did not assert anything about input-side offset normalization, and phrased the second-precision rule as "truncated to whole seconds" rather than "rounded", matching `strftime`'s drop of microseconds.

## Items deliberately not patched
- **`test_helpers/fixtures.py` re-entrancy fixes** (`setup_notice_filed_case`, `setup_execution_ready_case`): pure fixture bugs. The impl's `ERR_CASE_STATE_INVALID` on re-submitting a `NOTICE_FILED` case is verbatim PRD §3.4, and the duplicate-premises path is verbatim §3.7 / §2.5 rank 33. No silence, no mismatch.
- **`test_suite/test_09` assertion relocation:** PRD §3.8 already assigns the 14-days-after-`filed_on` rule to launch and only `wave_end_date > wave_start_date` to creation, and `routes_growth.py:69-71` (creation) vs `:135-145` (launch) match that split exactly; §2.5 rank 27's "on transition-wave creation and on transition-wave launch" is also already consistent. Nothing to pin.

## Step 9: Complete PRD — 2026-09-03T14:56:00.000Z

Run as three sequential file-partitioned passes over disjoint parts of `implementation/` (pass 1: `app.py`/`core.py`/`validation.py`/`calc.py`; pass 2: `routes_network.py`/`routes_cases.py` + their `services.py` helpers; pass 3: `routes_regulatory.py`/`routes_disposition.py`/`routes_growth.py` + their `services.py` helpers). Partitioning is deliberate: a single-pass scan of a 3,145-line implementation against a 462-line PRD runs out of budget and silently no-ops, leaving `PRD_COMPLETED.md` byte-identical to its source. Each pass edited the one shared `PRD_COMPLETED.md` in place with surgical `Edit` calls (never a whole-file `Write`, which would risk truncating a 100KB+ document), and each later pass was told not to revert earlier passes' edits.

### Size

| | lines | bytes |
|---|---|---|
| `PRD.md` | 462 | 102,758 |
| `PRD_FINALIZED.md` (Step 8) | 462 | 103,196 |
| `PRD_COMPLETED.md` after pass 1 | 462 | 111,451 |
| `PRD_COMPLETED.md` after pass 2 | 462 | 114,528 |
| `PRD_COMPLETED.md` final | 462 | 120,914 |

Total delta over `PRD_FINALIZED.md`: +17,718 bytes across 44 revised lines, 0 lines added or removed, 0 new sections — every change is an in-paragraph insert or revision.

### Counts (all three passes)

- Pass 1: 16 changes — 13 ambiguity-pins, 3 mismatch-revisions.
- Pass 2: 9 changes — 8 ambiguity-pins, 1 mismatch-revision.
- Pass 3: 23 changes — 16 ambiguity-pins, 7 mismatch-revisions.
- **Total: 48 changes — 37 ambiguity-pins, 11 mismatch-revisions.**

### Pass 1 — cross-cutting layer (`app.py`, `core.py`, `validation.py`, `calc.py`)

- §2.1 — revise — ambiguity — whitespace-only header counts as empty; role matched exactly/case-sensitively with no trimming, so an unrecognised spelling is 401 and never `ERR_FORBIDDEN_ROLE`; `X-User-ID` carried verbatim into comparisons — `validation.py:27-36`
- §2.1 — revise — **mismatch** — PRD claimed a `BranchManager` was ownership-gated on their own branch's *snapshot history*; impl gates exactly two operations (snapshot recording, on-demand score) and leaves the history listing open; also pinned that the check is a raw string compare made before path resolution — `routes_network.py:187-188,232,265-267`; `validation.py:47-50`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9` (24 total), fresh per request, same value on success and error envelopes — `core.py:190-198`
- §2.3 — revise — ambiguity — negative `offset` → 400; no upper bound on `offset`; `limit`/`offset` must be base-10 integer literals; empty-string value = omitted; default ordering tie broken by write sequence; `has_more` = `offset + returned count < total_count`; enum-valued filters reject non-members while identifier/free-text filters match literally; `breach` accepts `true/false/1/0` any case; undeclared query params ignored — `validation.py:186-235`; `core.py:210-217`
- §2.4 — revise — ambiguity — `version` increments once per resource *per request*, not per write, even across multi-hop cascades; a read never advances it — `core.py:157-170`
- §2.4 — revise — ambiguity — unmatched path *and* method-not-allowed both return `ERR_RESOURCE_NOT_FOUND` 404, produced before any auth check (so they precede rank 1); trailing slash accepted — `app.py:20,51-59`
- §2.5 rank 6 — revise — ambiguity — declared JSON type must match; string length + pattern bounds; explicit `null` == absent; absent/empty body read as `{}`; non-object or invalid JSON is malformed; **no observable precedence** among missing / wrong-type / out-of-range since all report the one `ERR_INVALID_REQUEST` — `validation.py:56-160`
- §2.6 — revise — ambiguity — `expected_branch_version`/`expected_case_version` are declared integers ≥ 1, so `0` or negative is caught at rank 6 as 400 and never reaches the 412 comparison — `routes_cases.py:111,224,473`
- §2.7 — revise — ambiguity — the two mileage fields must be JSON numbers (bare integer accepted as whole miles; quoted string and boolean malformed); bounds inclusive at 0.0/60.0; a second decimal place malformed even in range — `validation.py:146-160`
- §2.8 — revise — ambiguity — `to_iso8601` accepted with trailing `Z`, explicit offset (converted to UTC), or no offset (read as UTC); non-string/unparseable → 400; clock may move backwards and the move is unconditional, both triggered transitions one-way, counters may report zero — `validation.py:163-180`; `services.py:183-210`
- §3.1 — revise — ambiguity — MarketArea `name` is 1–120 chars; `median_household_income_cents`, `deposit_market_total_cents`, `competitor_branch_count` each at least 0 — `routes_network.py:35-41`
- §3.2 — revise — ambiguity — final snapshot-ordering tie (same `period_end_date` *and* `created_at`) broken by write order, newest write first; same ordering drives the per-branch listing — `calc.py:162-166`
- §3.2 — revise — **mismatch** — PRD said the on-demand score runs under an "explicitly named" variant; impl takes `scoring_variant` as an *optional query parameter* that falls back to the branch's stored variant when omitted or empty, and rejects a non-member at rank 6 before the branch id is resolved — `routes_network.py:263-275`
- §3.9 — revise — ambiguity — when `forecast_deposits_cents` is exactly 0 the division is skipped, `variance_bps` records 0, and `breach` stays false — `calc.py:367-370`
- §3.9 — revise — **mismatch** — PRD's "0-to-100 point scale" implied a floor; impl clamps only the 100-point ceiling, so a negative `household_growth_pct_bps` (admits down to -2000) yields a negative growth factor and `site_score` can be recorded negative — `calc.py:393-405`
- §3.9 — revise — ambiguity — the quadratic cumulative target is itself rounded to whole cents and can round to 0 for a tiny `target_year1_deposits_cents`; the division is then skipped and `ramp_attainment_bps` records 0, landing the observation in `AT_RISK` — `calc.py:373-380`

Pass 1 verified as already-correctly-pinned (no change): all 48 rows of the §5 catalogue match `core.ERROR_STATUS` exactly (same ids, statuses, order); every role set in the §4 table matches the route constants exactly; and all ~17 `calc.py` formulas — every constant, threshold, tier boundary, clamp, clamp *order* (profitability max-then-min; impact min-0-then-max-100), rounding point and intermediate — already match §3.1–3.9 verbatim, including the trailing-blend weight prefix and renormalised divisor, the seven-step savings chain with rounding at exactly steps 2 and 6, the round-then-sum severance pool, the closed-interval notice window, the half-open wave interval, the 12-share runoff curve summing to 10000, and the `RAMP_DIVISOR = 144` quadratic curve.

### Pass 2 — network + case lifecycle (`routes_network.py`, `routes_cases.py`)

- §3.1 — insert — ambiguity — numeric bounds on every branch-registration field: `deposit_balance_cents`, `monthly_transaction_count`, `annual_noninterest_expense_cents`, `annual_revenue_cents`, `fte_count`, `atm_count` each ≥ 0, `digital_adoption_bps` 0–10000, `opened_on` unbounded beyond ISO validity — `routes_network.py:106-113`
- §3.2 — insert — ambiguity — snapshot field bounds (`deposits_cents` ≥ 0, `transaction_count` ≥ 0, `digital_active_bps` 0–10000, `revenue_cents`/`noninterest_expense_cents` ≥ 0); recording is not gated on the branch's `status`, so a `CLOSED` branch still accepts periods — `routes_network.py:190-198`
- §3.2 — insert — ambiguity — the network-wide snapshot listing runs oldest-first and its `band` filter admits only the four scored bands (`UNSCORED` → `ERR_INVALID_REQUEST`), while the branch listing's `performance_band` filter does admit `UNSCORED` — `routes_network.py:24,167,252,258`
- §3.3 — insert — ambiguity — a new case's `pre_close_deposits_cents` and `executed_on` are **null**, not zero — `routes_cases.py:51-52`
- §3.3 — insert — ambiguity — forecast creation carries no case-status gate: past the version pin a forecast may be written against a case in any status, including decided/executed/terminal, and still supersedes and rewrites the case's figures — `routes_cases.py:463-512`
- §3.3 — insert — ambiguity — under `DISTANCE_DECAY` "segment mix is ignored" applies to the arithmetic only: all three share fields stay required and the sum-to-10000 test still fires — `routes_cases.py:470-482`
- §3.4 — insert — **mismatch** — (a) `reason_code` is a non-empty-when-present string the server validates and discards (never surfaces on the case); (b) on decision and revision the path case id is resolved *before* the body is inspected, so an unknown case answers `ERR_RESOURCE_NOT_FOUND` even with a malformed body — §2.5 as written ranks body well-formedness (6) above path resolution (7), which contradicts impl and is unsatisfiable given ranks 3/4 need the case loaded — `routes_cases.py:216-232,272-286`
- §3.8 — insert — ambiguity — `rescission_reason_code` required/non-empty/not persisted; the zero-observation test precedes the 30-day calendar test; same path-before-body order — `routes_cases.py:386-397`
- §3.8 — insert — ambiguity — bounded "reverses every movement": the notice goes to `WITHDRAWN` in place with `withdrawn_reason_code` left null and **none** of §3.5's withdrawal cascade running (case not returned to `APPROVED`, assessment untouched, no campaign cancelled); staff dispositions and campaigns already `COMPLETED` stay `COMPLETED`; the case keeps its own `executed_on`/`pre_close_deposits_cents` stamps (only the closing branch's twin stamps clear) — `routes_cases.py:399-441`

Pass 2 verified as already-correctly-pinned: guard order in `create_case` matches §2.5 ranks 8/9/12/31/32/43 exactly; `execute_closure`'s six preconditions fire in §2.5 rank order 11/13/19/22/24/41/42 (§3.8 narrates them in a different order but §2.5 already declares the global rank order authoritative); the selector's absorption floor, three-key ranking and explicit-pairing exemption; the create-vs-revise asymmetry on `ERR_RECEIVING_BRANCH_INVALID`; the `REJECT` branch-release condition and assessment-reset trigger; savings-chain recompute triggers.

### Pass 3 — regulatory + disposition + growth

- §2.4 — revise — **mismatch** — body-FK list omitted closure-notice filing, which resolves `consolidation_case_id` via `ref_lookup` → `ERR_REFERENCED_RESOURCE_NOT_FOUND` — `routes_regulatory.py:141`
- §2.5 rank 11 — revise — **mismatch** — endpoint list for `ERR_CASE_STATE_INVALID` omitted assessment finalisation, the four staff-disposition transitions and premises contracting; added them plus the local rule that on those six the case status is tested *after* the addressed resource's own from-state (ranks 14/15/16 win) — `routes_regulatory.py:110-120`, `routes_disposition.py:28-32,133-136,342-357`
- §3.5 — insert — ambiguity — `senior_household_pct_bps` bounds 0–10000 — `routes_regulatory.py:32`
- §3.5 — insert — ambiguity — supersede-on-create resets the case's `impact_tier`/`notice_required_days` **only** for a dragged `FINALIZED` (explicitly narrower than §3.4's any-of reject cascade); the case is re-stamped only in that event; superseded assessments bump their own version; the new record opens `DRAFT` with `finalized_on` null; creation carries no case-status gate — `services.py:83-96`, `routes_regulatory.py:41,61-62`
- §3.5 — insert — ambiguity — a case outside the permitted set on finalise is `ERR_CASE_STATE_INVALID`, and assessment from-state is evaluated first — `routes_regulatory.py:110-120`
- §3.5 — insert — ambiguity — the window-collision test is reached before the planned-date test, per §2.5 ranks, not in the order the four guards are narrated — `routes_regulatory.py:158-165`
- §3.5 — insert — ambiguity — the window test runs only for a new `REGULATOR` filing; `CUSTOMER`/`LOBBY_POSTING` never test it — `routes_regulatory.py:159`
- §3.6 — insert — ambiguity — `role_title` non-empty with no max length, `tenure_months` ≥ 0, `annual_salary_cents` ≥ 0 — `routes_disposition.py:44-46`
- §3.6 — revise — ambiguity — "all four `HRPartner` operations" named explicitly (notify/accept/rescind/sever), `ERR_CASE_STATE_INVALID` pinned, creation stated as ungated, disposition from-state tested before case status — `routes_disposition.py:28-32,136,156,188,219`
- §3.6 — insert — ambiguity — `rescind_reason_code` required, non-empty, validated then discarded — `routes_disposition.py:183`
- §3.7 — insert — ambiguity — both ATM money fields are integers ≥ 0 — `routes_disposition.py:248-249`
- §3.7 — insert/revise — ambiguity — the four tenure terms are optional integers ≥ 0; an other-fork term is stored, not rejected; `ERR_DUPLICATE_KEY` outranks `ERR_PROPERTY_TERMS_INCOMPLETE` — `routes_disposition.py:250-273`
- §3.7 — insert — ambiguity — `counterparty_ref` required non-empty (no max), `agreed_amount_cents`/`selling_costs_cents` required ≥ 0 — `routes_disposition.py:337-339`
- §3.7 — insert — ambiguity — a case outside the three statuses is `ERR_CASE_STATE_INVALID`, tested after the premises from-state — `routes_disposition.py:342-357`
- §3.7 — insert — ambiguity — settle takes no body and no case-status gate; only the from-state guard — `routes_disposition.py:369-375`
- §3.8 — insert — ambiguity — the lead test uses the *newest* open `REGULATOR` notice (`FILED`/`EFFECTIVE`, newest `created_at`); no open notice at all is `ERR_CASE_STATE_INVALID`, tested between the two dating tests — `routes_growth.py:139-145`, `services.py:112-115`
- §3.9 — insert — ambiguity — `observed_deposits_cents` ≥ 0; both FKs are optional **strings** (non-string ⇒ `ERR_INVALID_REQUEST`, explicit null ⇒ absent) and resolve at rank 8, so a present-but-unresolvable id (including the wrong key) answers `ERR_REFERENCED_RESOURCE_NOT_FOUND`, not the coherence 422 — `routes_growth.py:373-380`
- §3.9 — insert — ambiguity — the third hop is unconditional: every case observation re-stamps the trade area (version +1) even with no value change; a plan observation never touches it — `services.py:147-164`, `routes_growth.py:329`
- §3.9 — insert — **mismatch** — the observation listing has no ordering of its own (default `created_at` ascending); it coincides with month order per subject but interleaves across subjects — `routes_growth.py:450`
- §3.9 — revise — **mismatch** — `proposed_branch_code` uniqueness is **not** tested at plan creation (only at opening); `capex_budget_cents` ≥ 0 — `routes_growth.py:159-165`
- §3.9 — insert — ambiguity — de novo `reason_code` optional, non-empty when supplied, validated then discarded — `routes_growth.py:218`
- §3.9 — revise — **mismatch** — the minted branch is created **directly** in `DE_NOVO_RAMPING` (PRD said `ACTIVE → DE_NOVO_RAMPING`); code-uniqueness precedes the hold test; capacity ≥ 1 defaulting to 40; `branch_type`/`tenure_class` enumerations; full minted field set incl. `scoring_variant` `TRAILING_BLEND`, zeroed operating figures, `opened_on`, null stamps — `routes_growth.py:244-284`
- §4 — revise — **mismatch** — deposit-observation listing row: "in month order" → "oldest recorded first" — `routes_growth.py:450`

Pass 3's disposition of the items earlier passes deferred to it: observation ordering **fixed** (§4 row + §3.9 prose); per-endpoint bounds **swept** across all three modules (already-pinned bounds — `employee_ref` 1–40, `site_label` 1–80, `month_index` 1–12, `inbound_household_count` ≥ 1, `target_year1_deposits_cents` ≥ 1, `alternative_access_count` 0–20, the mileage decimal rule — left alone); observation FK typing/precedence **fixed**; the `supersede_live_assessment` vs reject-cascade divergence **fixed in §3.5 only**, with §3.4 left untouched because it was already correct; the closed-interval notice-window collision **already pinned correctly** at §3.5 (only the `REGULATOR`-only applicability clause added); the `routes_cases.py` body-vs-path reversal **not generalised** into pass 3's sections, which follow the normal §2.5 order; the holdover savings-refresh owner **confirmed** consistent with §2.8, no edit; the unused `exclude_notice_id` parameter **no edit** (dead parameter, no observable behavior).

### Orchestrator final verification

- `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (`cmp` differs, 44 changed lines) — the scan genuinely ran rather than silently no-opping.
- 462 lines / 120,914 bytes; 26 headings (unchanged); §5 still carries all 48 `ERR_*` rows; §4 still carries all 59 method rows; the file still ends at the final complete catalogue row `| \`ERR_PROPERTY_TERMS_INCOMPLETE\` | 422 |`. No truncation, no structural damage, no new sections.
- Every `implementation/` file's mtime predates the 14:21:10 completion of the green sweep (latest is `core.py` at 14:16:45, the Step 7 fix). Step 9 edited only `PRD_COMPLETED.md`, so the verified 8×103/103 result still describes the delivered implementation; no re-run was required.

**Pipeline complete.** Steps 1–9 all finished; `workspace/PRD_COMPLETED.md` is written.
