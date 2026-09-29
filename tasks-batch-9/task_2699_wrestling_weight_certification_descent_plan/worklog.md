# Worklog — task_2699_wrestling_weight_certification_descent_plan

## Step 1: Create task directory — 2026-09-04T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2699_wrestling_weight_certification_descent_plan/` and `workspace/`. Index pre-assigned by the invoking pipeline (2699); no auto-allocation scan performed.

## Step 2: Generate Scaffold — 2026-09-04T10:41:00.000Z

All three scaffold artifacts are complete and the generator's lint reports a clean verdict.

## Files

| Path | Lines |
|---|---|
| `SCAFFOLD.yaml` | 2875 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1962 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 5897 |

Top-level keys verified: `SCAFFOLD.yaml` carries neither `scaffold_difficulty_design` nor `scaffold_corner_design`; the two design files each have exactly one top-level key.

## SCAFFOLD.yaml counts (§1.0–§1.7)
15 entities · 12 state machines · 2 concurrency rules · 8 calculations · 33 validations (priorities 1–33, no gaps/dupes) · 56 endpoints · 57 errors · 5 roles.
complexity_profile: archetypes compliance_audit / ledger_reconciliation, `entity_topology: graph`, `state_machine_shape: cyclic`, `role_model: segregation_of_duties`, `consistency_model: immediate`, layers `[dual_variant_calculation, rate_threshold_triggers, cascading_side_effects, optimistic_concurrency]`.

## §1.8 SCAFFOLD_DIFFICULTY_DESIGN.yaml
9 rules × 2 instances = **18 instances**, all with full `test_recipe`s (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).

## §1.9 SCAFFOLD_CORNER_DESIGN.yaml
All 9 guide sections in guide order — **60 testable instances + 18 `excluded_because` stubs** (78 entries):

| Section | Total | Real / Stub |
|---|---|---|
| entities | 12 | 12 / 0 |
| state_machines | 10 | 8 / 2 |
| calculations | 13 | 9 / 4 |
| validations | 15 | 12 / 3 |
| endpoints | 6 | 6 / 0 |
| errors | 11 | 5 / 6 |
| rbac | 4 | 4 / 0 |
| cross_cutting_complexity_layers | 6 | 3 / 3 |
| consistency_model | 1 | 1 / 0 |

Every `claim_type` is drawn from the `claim-extraction-guide.md` row set for its section; instance names are unique across both design files; every stub's `difficulty_instance` resolves to a real §1.8 `rule_id / instance_name`.

## Verification
`scaffold_lint.py` final run: **VERDICT: clean lint** — 56 endpoints, 15 entities, §1.8 = 18 instances, §1.9 = 60 instances, **1439 structured calls** all conforming to §1.5 (endpoint declared, role allowed, payload keys, capture JSONPaths resolvable, `expected_*_version` templated) with FK reverse-reachability satisfied for every §1.1 relation. All three files also parse as valid YAML.

Issues fixed during this final stretch: two `$.data.team_roster_count` captures on `POST /teams/{id}/wrestlers` (that field lives on Team, not the returned Wrestler — replaced with `GET /teams/{id}` reads of `roster_count`), one `$.data.outcome` capture on `POST /appeals/{id}/decide` (Appeal declares `decision_note`, not `outcome`), and a stray empty `setup: []` key.

The hard constraint held: no sibling `task_*/` directory was listed, read, or grepped at any point — the scaffold derives solely from the scenario text and the generator skill's own specification.

## Step 3: Copy Shared Files — 2026-09-04T10:41:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T10:56:00.000Z

PRD generation complete and verified.

**Output:** `workspace/PRD.md`
**Final line count: 397** (written incrementally in 9 calls — 1 `Write` + 8 heredoc appends — with `wc -l` growth confirmed at each step: 139 -> 179 -> 211 -> 235 -> 251 -> 271 -> 334 -> 397; no truncation).

**Hard Contract reports**

- **Contract 1 — Field-Name Coverage: PASS.** Mechanical check over 402 backticked tokens (code fences stripped first): 130 entity `fields[].name` present, 71 `request_body`/`input` identifiers present, 25 `query_params` present; all missing-sets empty. Also verified present verbatim: all 57 error ids, all state values across all 12 machines, all 5 role names, all enum-type field values.
- **Contract 2 — Rule Coverage: PASS.** All 33 validations are stated with their relative precedence in §2.8 and re-anchored in the §3 workflow that triggers them; both `concurrency_rules` are specified in §2.7 (`expected_wrestler_version` -> `ERR_STALE_WRESTLER_VERSION` 412; `expected_entry_version` -> `ERR_STALE_ENTRY_VERSION` 412, with the explicit statement that no other endpoint accepts a version field); all 12 state machines' transitions (including the cyclic `RETEST_ORDERED <-> RETEST_COMPLETED` and `CERTIFIED <-> BREACHED` pairs and the parallel `certification_status` x `eligibility_status` dimensions) plus their conditions and side effects are in §3; all 8 calculations are given in natural-language reconstructible form with both variants each for `minimum_certified_weight` (`WEEKLY_STEP`/`LINEAR_RATE`) and `audit_discrepancy_score` (`WORST_CASE`/`SAMPLE_MEAN`) and with rounding order pinned in §2.6; cross-entity cascades (the five-hop audit-failure cascade and the four-hop appeal-upheld cascade), `applies_to` scopes, sibling-branch symmetry, and the two conserved quantities (`Team.open_flag_severity_total`, `Event.seed_integrity_sum`) are in §2.9/§2.10.
- **Contract 3 — §3 Path Purity: PASS.** 1077 backticked tokens scanned inside §3: zero tokens starting with `/`, zero bare HTTP-method tokens, zero method+path tokens, and in fact zero tokens containing `/` at all. §3 refers to operations only via state transitions, role+action verbs, and capability descriptions.

**Section list, in order**
1. `# Wrestling Weight Certification API — Product Requirements Document`
2. `## 1. Introduction`
3. `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (verbatim contract); 2.3 Pagination; 2.4 Resource Identity, Timestamps and the Logical Clock; 2.5 Season Regulatory Constants and the Weight-Class Ladder; 2.6 Measurement Precision and Rounding Discipline; 2.7 Version Pinning on Wrestler and Entry Writes; 2.8 Path Resolution and Validation Precedence; 2.9 Conserved Quantities: the Severity Ledger and the Seed Sum; 2.10 Cascade Discipline and Hierarchical Consistency
4. `## 3. Business Logic & Workflows` — 3.1 Standing Up a Season: Constants, Growth-Allowance Dates and Rosters; 3.2 Assessor Credentialing, Training and Loss of Credential; 3.3 Body-Composition Assessment and the Hydration Fork; 3.4 Contesting a Result: Appeals, Retest Rounds and Segregation of Duties; 3.5 Descent Plans and the Certified Progression Schedule; 3.6 The Season Compliance Run: Judging Milestones, Breach and Revision; 3.7 Scheduling Competitions and Entering Wrestlers; 3.8 Weigh-In Day, Allowances, Bracket Seeding and Class Changes; 3.9 Health and Safety: Flags, Team Posture, Disqualification and Program Audit
5. `## 4. Endpoint Definitions` (4-column table)
6. `## 5. Error Code Catalogue` (2-column table)

**Scaffold element coverage confirmed:** 15/15 entities · 12/12 state machines · 8/8 calculations · 33/33 validations · 2/2 concurrency rules · **56/56 endpoints** · **57/57 errors** · 5/5 roles.

**Constraint compliance:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced. All writes used the absolute path.

**File ending is clean** — the last line is a complete final row of the §5 error table. Literal last 3 lines:

```
| `ERR_APPEAL_ROUND_LIMIT` | 409 |
| `ERR_NO_SEEDABLE_ENTRIES` | 409 |
| `ERR_RESEED_REQUIRED` | 409 |
```

Two scaffold ambiguities were resolved with determinate prose rather than vague wording: `EligibilityCheck.blocking_error_id` for outcome `BLOCKED_PLAN_BREACHED` is specified to carry `ERR_CLASS_BELOW_CERTIFIED_MINIMUM` (with a full outcome-precedence order mirroring validation priorities 8/11/12/13/21), and `ERR_WRESTLER_NOT_CERTIFIED` is stated per its error condition (`certification_status` is `UNCERTIFIED` or `SUSPENDED`) so that a `PROVISIONAL` wrestler can open a plan — required for the `PROVISIONAL -> CERTIFIED` transition to be reachable.

**Orchestrator anti-truncation verification (independent):** `wc -l` = 397, `wc -c` = 92903, `tail -12` ends on a complete `| \`ERR_RESEED_REQUIRED\` | 409 |` table row at a real section boundary; `grep -n '^## '` returns all 5 expected sections. PRD is NOT truncated.

## Step 5: Generate Unit Tests — 2026-09-04T11:41:00.000Z

Audit is clean. Final state below.

## Deliverables

**`test_helpers/`** — 9 files, 2710 lines
`__init__.py` 29 · `api_client.py` 339 (one method per all 55 declared endpoints) · `api_errors.py` 171 (58 error ids + full `ERROR_HTTP_STATUS` map, registered via `set_error_http_status_map`) · `assertions.py` 456 · `constants.py` 290 · `factories.py` 333 (all measurements emitted as JSON numbers; `_OMITTED` sentinel so unset optionals exercise server defaults) · `fixtures.py` 725 (`api` fixture + per-endpoint builders + 4 composite scenarios) · `test_users.py` 107 · `types.py` 260 (`WeighIn`/`EligibilityCheck`/`GrowthAllowance` carry only `id`+`created_at`).

**`test_suite/`** — `conftest.py` + 18 test modules, 13919 lines total, **218 test functions / 261 collected cases**:
`test_01_dual_variant_calc.py` 663/8 · `test_02_combinatorial_formula.py` 463/7 · `test_03_non_linear_state_machine.py` 537/8 · `test_04_transitive_cascade.py` 559/10 · `test_05_priority_pair_validation_conflict.py` 257/4 · `test_06_boundary_precision_check.py` 600/10 · `test_07_cross_entity_state_dependency.py` 540/10 · `test_08_resource_temporal_overlap.py` 504/8 · `test_09_compensating_invariant.py` 499/7 · `test_10_entities.py` 1022/25 · `test_11_state_machines.py` 1047/18 · `test_12_calculations.py` 1251/17 · `test_13_validations.py` 1624/28 · `test_14_endpoints.py` 1184/18 · `test_15_errors.py` 708/10 · `test_16_rbac.py` 1174/13 · `test_17_cross_cutting_layers.py` 806/8 · `test_18_consistency_model.py` 472/9.

## Coverage

- **Queue A (§1.8):** 17 of 18 instances translated, every one with 3-5 tests (target is >=2). 1 skipped (below).
- **Queue B (§1.9):** **60 of 60 non-stub instances** translated, every one >=1 test (most 2-4). All **18 `excluded_because:` stubs** have exactly zero tests, as required.
- Design tags: every one of the 218 tests ends its docstring with exactly one `Design:` line; zero untagged, zero dual-tagged, zero tags pointing at a stub or a non-existent name. Forbidden vocabulary (`scaffold`, `design index`, `corner case index`, `rule_id`, `instance`) appears **0 times** in either directory.
- `python3 -m pytest test_suite/ --collect-only` -> **261 tests collected, 0 errors**.
- `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/` — no stray `test_helpers/` or `test_suite/`. All `__pycache__`/`.pytest_cache` removed. Nothing under `workspace/implementation/` was read or written.

## Skipped instance (1)

**`Difficulty/priority_pair_validation_conflict/entry_window_conflict_beats_duplicate_entry`** — fails PRD-filter condition (b), unique derivability. PRD §3.7 (line 228) scopes `ERR_ENTRY_WINDOW_CONFLICT` to "another event whose half-open competition window overlaps this event's window", so the design's recipe (re-entering the same wrestler on the same event) uniquely derives `ERR_DUPLICATE_ENTRY` alone. I verified independently that the two conditions cannot co-fire through declared endpoints: an entry on an overlapping sibling event would itself have been refused, so no state exists where both violations hold. No weakening, no xfail, no placeholder emitted — the gap stands. Its sibling `disqualified_beats_season_not_open` has 4 tests, and the three queue-B stubs deferring to this instance also stay untranslated by design.

## Notable assertion-level trims (instances kept, individual claims dropped as not uniquely derivable)

- `Event.entry_count` after a `SCRATCHED` entry — the PRD defines `entry_count` only as incremented on successful entry and never states its predicate; dropped in 4 files independently.
- Post-revision `projected_certification_date` / `total_weeks` / stored `plan_start_date` — §3.6 enumerates only `milestone_count`, `revision_count`, `version` and status.
- Wrestler status/eligibility after superseding a **BREACHED** plan — §3.5 pins only the CERTIFIED and DRAFT cases.
- Closed-world negatives ("no PUT/PATCH/DELETE route exists") — not reachable through declared endpoints.
- The "non-voided" qualifier on assessor daily capacity — unobservable, since every route to `VOIDED` also decertifies the assessor.
- `ERR_UNAUTHENTICATED` on an empty-valued `X-User-ID` — §2.1 pins absent headers and undeclared role names only.
- Cross-team **reads** as a rival coach — §4 authorizes `TeamCoach` for those reads; ownership is a closed list of write operations.

Three design recipes contained values contradicting the PRD and were corrected rather than asserted as written: `event_type: "DUAL_MEET"` (not an enum member -> `DUAL`/`TOURNAMENT`), a superseded plan's status `SUPERSEDED` (§3.5 pins `CANCELLED` with `cancel_reason = SUPERSEDED`), an eligibility outcome `ELIGIBLE` (§3.7 pins `CLEARED`), a day-0 weigh-in allowance of 1.0 (§3.8: "day zero earns nothing" -> 0.0), and `ERR_INVALID_WEIGHT_CLASS` at HTTP 400 (§5 pins 422).

One infrastructure bug found and fixed mid-run: `fixtures.py`'s `milestones_of`, `entries_of_event` and `flags_of_wrestler` double-unwrapped list responses (`get_success_data(response)["data"]` -> `TypeError`); all three now use `validate_paginated`. Ten call sites across five test modules depend on them and were verified against the corrected signatures.

## Step 6: Generate Implementation — 2026-09-04T11:41:30.000Z

Implementation complete and verified.

## Files

`workspace/implementation/`

| file | lines |
|---|---|
| `app.py` | 67 |
| `store.py` | 173 |
| `errors.py` | 86 |
| `envelope.py` | 50 |
| `validate.py` | 251 |
| `auth.py` | 94 |
| `lookups.py` | 156 |
| `calc.py` | 323 |
| `serialize.py` | 388 |
| `cascade.py` | 353 |
| `routes/__init__.py` | 1 |
| `routes/core.py` | 250 |
| `routes/people.py` | 223 |
| `routes/assess.py` | 446 |
| `routes/plans.py` | 293 |
| `routes/compete.py` | 571 |
| `routes/safety.py` | 218 |
| `start.sh` | 10 (executable) |
| `requirements.txt` | 1 (`Flask>=2.0.0`) |
| **total** | **3954** |

## Verification

- **Endpoints: 56/56, exact one-for-one match.** Normalized diff of the PRD §4 table against Flask's `url_map` shows zero missing and zero extra (26 GET / 30 POST). `GET /seasons`, `GET /teams`, `GET /assessors` are correctly absent — the PRD declares no collection-list endpoints for those three.
- **Errors: 57/57** in `ERROR_HTTP` (400x1, 401x1, 403x2, 404x13, 409x28, 412x2, 422x10).
- **12 state machines** wired (Season, Team compliance posture, Wrestler certification x eligibility as independent parallel dimensions, Assessor, Assessment, Appeal, DescentPlan, Milestone, Event, Entry, HealthFlag, Audit). **8 calculations** in `calc.py`, both dual-variant pairs included (`WEEKLY_STEP`/`LINEAR_RATE`, `WORST_CASE`/`SAMPLE_MEAN`). **33 validations** across `validate.py` + the per-route guard chains, ordered per PRD §2.8.
- **Storage:** in-memory dicts only. Grep for `sqlite|shelve|pickle|json.dump|open(...'w'|/tmp/|redis|psycopg|sqlalchemy` returns nothing. `DB` holds 0 rows across all 15 collections at import; a cold boot via `start.sh` served `total_count=0` on all 13 list endpoints — nothing is seeded, preloaded or hardcoded.
- **`start.sh`** reads `$PORT`, binds `0.0.0.0`, runs in the foreground via `exec`, and guards the pip install so per-test reboots don't contend.
- `compileall` clean; `__pycache__` removed; no stray files in the task dir.

## Smoke tests

Two end-to-end suites against a live server on high ports, **all assertions PASS** ("SMOKE OK" / "SMOKE2 OK"). Notably both PRD worked examples reproduce exactly — `WEEKLY_STEP` `[159.6, 157.2, 154.8, 152.5, 150.2, 147.9]` in 5 weeks and `LINEAR_RATE` `[159.6, 157.2, 154.8, 152.4, 150.0]` in 4 weeks at delta 2.4 — plus certified figures (lean 140.4 / min cert 151.0 / class 157), both audit variants diverging on identical inputs (SAMPLE_MEAN 1.40 PASS vs WORST_CASE 2.40 FAIL), the 5-hop audit-fail cascade, the 4-hop appeal-UPHELD cascade with void/repoint, the compliance run producing BREACHED + a severity-3 `PLAN_BREACH` flag, plan revision (pre-start SCHEDULED rows waived, later ones deleted, `week_index` continuing at `base_index`), severity-ledger and seed-sum conservation, OCC 412, RBAC 401/403, and the pagination/envelope contracts.

Three intermediate failures were all bugs in the throwaway smoke script's expected values (arithmetic copied from a different body-fat case), each confirmed by hand against the PRD before correcting the test. One genuine implementation bug was found and fixed during generation: `routes/compete.py` `seed_event` used `if entry not in pool`, which compares dicts by value and would misclassify two structurally identical rows — replaced with an id-set membership test.

Both smoke listeners were killed by port-derived PID (`ss -ltnp` -> `kill "$PID"`); no broad `pkill` was ever issued. Ports 18699 and 18711 are free.

**Orchestrator layout verification (independent):** `test_helpers/` and `test_suite/` are both at the task root; `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/` — no strays to move before Step 7.

## Step 7: Run Tests and Iterate — 2026-09-04T12:05:00.000Z

Clean sweep achieved.

## Summary

**Iterations run:** 2 (each a full 8-round parallel sweep under `setsid nohup`).

**Iteration 1:** 252/261 in all 8 rounds — 9 failures, perfectly deterministic (same 9 in every round, no flakiness). Every one traced to the test layer, not the implementation. No implementation changes were needed at all.

**Tests deleted:** none. No failing test was found to assert a PRD-silent rule outright; two individual *assertions* were PRD-silent and were removed under STEP 1c partial-coverage handling (see below).

**Fixes applied to `test_helpers/`:** none — the bugs were all in local helpers inside `test_suite/`.

**Fixes applied to `test_suite/`:**

- `test_suite/test_07_cross_entity_state_dependency.py` — local helper `_flags_by_source` did `get_success_data(response)["data"]`, a double unwrap (`get_success_data` already returns `body["data"]`, a list for a paginated route) -> `TypeError: list indices must be integers`. Switched to `validate_paginated`. This is the same class of bug the Step 5 worklog records fixing in `fixtures.py`; this local copy in test_07 was missed. Fixed 2 tests.
- `test_suite/test_14_endpoints.py` — `_certified_roster_member` returns *ids*, but `_compliance_scenario` stored them and the tests then subscripted `scenario.plan_a["id"]` -> `TypeError: string indices must be integers`. Changed the 6 call sites to use the id directly (consistent with `scenario.wrestler_b`, which the same tests already used bare). Fixed 2 tests.
- `test_suite/test_14_endpoints.py` — `_audit_scenario` passed the whole wrestler dict (`wrestler_x`, `wrestler_y`, `wrestler_z`) where `create_validated_assessment` takes a `wrestler_id`, so the payload carried a serialized dict and the server correctly answered `ERR_WRESTLER_NOT_FOUND` ("Setup step failed with HTTP 404"). Added `["id"]`. This was a single upstream fixture bug masquerading as 4 independent failures — fixed 4 tests.
- `test_suite/test_16_rbac.py` — `assert plan["team_id"] == ctx.team_id` and `assert entry["team_id"] == ctx.team_id` -> `KeyError: 'team_id'`. **STEP 1a: PRD is silent.** PRD §3.5 enumerates the DescentPlan attributes set at creation (`supersedes_plan_id`, `weekly_rate_pct`, `weekly_delta_lbs`, `total_weeks`, `projected_certification_date`, `cancel_reason`, `milestone_count`, `missed_milestone_count`, `breach_count`, `revision_count`) and its list filters (`wrestler_id`, `source_assessment_id`, `supersedes_plan_id`, `status`) — no `team_id`. §3.7 does the same for Entry (`seed_number`, `latest_effective_weight_lbs`, `scratch_reason`, `weight_class_change_count`; filters `event_id`, `wrestler_id`, `status`, `weight_class_lbs`) — no `team_id`. PRD declares `team_id` only on Wrestler (§3.1) and Appeal (§3.4); the plan/entry ownership check in §2.1 reaches the team *through the wrestler*, so a faithful reader would not expose `team_id` on either row. Category: **PRD-silent response attribute** (attribute-only-in-ownership-prose). Per STEP 1c the two uncovered assertions were dropped and replaced with the PRD-covered ownership evidence (`wrestler_id`); the rest of the test — the four rival-coach 403s, the DRAFT plan, the ENTERED entry, `entry_count == 1`, and both teams' `roster_count` — is unchanged. Fixed 1 test.

**Fixes applied to `implementation/`:** none. Notably no PRD-required check was weakened and no field was added to the serializer to satisfy the `team_id` assertions.

**Final sweep (iteration 2), per round:**

| round | passed/total |
|---|---|
| 1 | 261/261 |
| 2 | 261/261 |
| 3 | 261/261 |
| 4 | 261/261 |
| 5 | 261/261 |
| 6 | 261/261 |
| 7 | 261/261 |
| 8 | 261/261 |

0 failed, 0 errors, 0 skipped in every round. Results retained at `workspace/implementation/results.{1..8}.json`. No stray servers left; `__pycache__` cleaned; no broad pkill was ever issued.

**Orchestrator independent verification:** all 8 `results.$i.json` files exist (~78.6 KB each, mtime 12:02) and each parses to `passed=261 total=261 failed=0 errors=0 skipped=0`. The clean sweep is real, not a claim.

**Step 8 skip decision:** NOT skipped. Step 7 ran 2 iterations with 4 `test_suite/` fixes, so the skip condition (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes) does not hold. The `test_16_rbac.py` item is a genuine PRD silence to pin; the other three are pure fixture bugs that Step 8 should recognize as requiring no PRD edit.

## Step 8: Finalize PRD — 2026-09-04T12:10:00.000Z

`PRD_FINALIZED.md` is written. Exactly one edit was warranted.

**Size:** PRD.md 397 lines / 92,903 bytes -> PRD_FINALIZED.md 397 lines / 93,246 bytes. Line delta 0 (+0.0%); byte delta +343 (+0.37%). One paragraph (line 23) modified, nothing else.

**Change list**
- §2.1 (User and Role-Based Access Control), line 23 — *insert* — added one clause pinning that a `DescentPlan` and an `Entry` carry no `team_id` (neither stored nor serialized), and that coach ownership for those two is resolved indirectly through the row's `wrestler_id` -> wrestler's `team_id`; only `Wrestler` and `Appeal` among the resources §2.1 enumerates hold a `team_id` of their own — `implementation/serialize.py:238-258` (plan, no `team_id`), `implementation/serialize.py:295-307` (entry, no `team_id`), `implementation/serialize.py:182` / `:226` (the only two `team_id` serializations), `implementation/routes/plans.py:50`, `implementation/routes/plans.py:216`, `implementation/routes/compete.py:223` (`require_team_owner(wrestler.get("team_id"))`).

**Pre-edit search log (the one edit)**
- (a) Subject: presence/absence of a `team_id` attribute on `DescentPlan` and `Entry`, and the mechanism of coach ownership for those entities.
- (b) Paths enumerated: `grep -rn team_id` across all of `implementation/` — every hit reviewed. Serializers: `serialize.py` has `team_id` only in `wrestler()` (:182) and `appeal()` (:226); `plan()`, `milestone()`, `entry()`, `event()`, `weigh_in()`, `eligibility_check()`, `health_flag()`, `audit()`, `season()`, `team()`, `assessor()`, `assessment()` have none. Row construction: `routes/plans.py:107-125` (plan row) and `routes/compete.py:279-290` (entry row) store no team field. Ownership: `auth.py:71-84` (`owns_team`/`require_team_owner`), all five coach-exclusive writes (`routes/people.py:118-121` team-path wrestler create, `routes/assess.py:247-255` appeal filing with payload `team_id`, `routes/plans.py:45-50` plan create, `routes/plans.py:210-216` plan revise, `routes/compete.py:218-223` entry create) — the plan/revise/entry three all dereference the wrestler. Adjacent team reads: `serialize.team_posture` / `team_severity_total` / `team_roster_count`, `cascade.py:51-75`, `cascade.py:236`, `routes/safety.py:77-88`, `routes/compete.py:253,526` — all also reach the team via `wrestler["team_id"]`, none via a plan/entry field. List filters: `routes/plans.py:134-155` and `routes/compete.py:300-321` accept no `team_id` query param (matches PRD's enumerated filters); reads of plans/entries (`plans.py:129`, `compete.py:295`) apply no ownership check at all.
- (c) Wording adjustments made: two. First, the exclusivity claim was scoped to "of those resources" (the four §2.1 enumerates) rather than a global "only Wrestler and Appeal have team_id", so it cannot be read as a claim about entities §2.1 never mentions. Second, "wherever an ownership check applies to a plan or an entry" replaced an unconditional "a plan's/entry's ownership is checked through the wrestler", because plan and entry *reads* are open to all five roles with no ownership gate — the unconditional phrasing would have implied a read-side check the implementation does not perform.

**No edit for the other three Step 7 items**, as expected: `test_07`'s `_flags_by_source` double unwrap is a pure test bug (`GET /health-flags` is an ordinary paginated list per §2.3 — `routes/safety.py:37-57`), and both `test_14` failures were dict-vs-id confusion in local fixture helpers. None of the three reveals PRD silence or an impl/PRD divergence, and Step 7 changed no implementation code at all.

**Orchestrator independent verification:** `cmp` reports PRD.md and PRD_FINALIZED.md DIFFER; `diff` shows exactly one changed line (23), the §2.1 RBAC paragraph, matching the reported edit. Byte counts confirmed at 92903 -> 93246.

## Step 9: Complete PRD — 2026-09-04T12:35:00.000Z

**Orchestrator design decision (recorded per AUTONOMY):** Step 9 was run as THREE SEQUENTIAL module-partitioned passes over one shared `PRD_COMPLETED.md`, rather than as a single subagent. Rationale: a 397-line PRD against a 3954-line 56-endpoint implementation is more surface than one context can scan exhaustively, and the known failure mode is a subagent that returns a byte-identical `PRD_COMPLETED.md` because the scan never really ran. Partitioning by implementation module keeps each pass's read set bounded while guaranteeing total coverage of `implementation/`. Pass 1 performed the `cp`; passes 2 and 3 were explicitly forbidden from copying so as not to destroy prior work.

Partition:
- **Pass 1** — `app.py`, `store.py`, `errors.py`, `envelope.py`, `validate.py`, `auth.py`, `lookups.py`, `serialize.py`, `routes/core.py`, `routes/people.py`
- **Pass 2** — `calc.py`, `cascade.py`, `routes/assess.py`, `routes/plans.py`
- **Pass 3** — `routes/compete.py`, `routes/safety.py`

### Pass 1 (infra + core/people) — 21 changes: 19 ambiguity-pins, 2 mismatch-revisions
397 lines / 93,246 chars -> 401 lines / 98,586 chars.
Highlights: empty/whitespace `X-User-ID`/`X-User-Role` counts as absent -> 401 (`auth.py:27`); `api_request_id` = `req_` + 20 chars of `A-Z0-9` and `api_request_timestamp` read from the logical clock (`envelope.py:10,14,20`); **mismatch** — the error envelope was scoped to 4xx but impl emits it for HTTP 500 too (`app.py:54-57`); pagination edge rules (non-integer `limit`/`offset` -> 400, undeclared params ignored, bad enum filter -> 400, unknown identifier filter -> empty page never 404) (`validate.py:201-237`); `created_at` ties broken by insertion order, never by `id` (`store.py:167-169`); `to_iso8601` normalization and the clock-set 200-with-empty-data (`store.py:89-116`, `routes/core.py:33-38`); malformed `weight_classes` -> 400 with no server-side sort/de-dupe (`routes/core.py:45-64`); numeric weight-class equality so `132.0` matches rung `132` (`validate.py:186-190`); unmatched path -> `ERR_NOT_FOUND` 404 and undeclared method -> `ERR_METHOD_NOT_ALLOWED` 405, both pre-authentication, trailing slash insignificant (`app.py:25,36-43`); four body-shape conventions (explicit null == omitted, booleans rejected for numbers, integral floats accepted for integers, absent body == `{}`) (`validate.py:19-37,122-127`); non-empty-string requirements across season/team/wrestler/assessor/flag payloads; the full training-record contract including integer reporting of whole cumulative hours and version refresh even when no threshold is crossed (`routes/people.py:71-89`); **mismatch** — disqualification prose read flag-check-first but impl checks `certification_status` first (`routes/people.py:183-197`); §5 gained the two routing-level rows.

### Pass 2 (calc/cascade/assess/plans) — 28 changes: 25 ambiguity-pins, 3 mismatch-revisions
401 lines / 98,586 chars -> 401 lines / 105,510 chars (in-paragraph edits; paragraphs are single lines in this file).
Highlights: **mismatch** — assessment finalize is NOT gated on the disqualified-wrestler freeze; a DISQUALIFIED wrestler's DRAFT assessment still validates and repoints their figures (`assess.py:120-149`); **mismatch** — §4 said appeals file "against a validated assessment", impl accepts any assessment (`assess.py:249`); **mismatch** — `requested_weeks` is shape-checked AFTER the version pin, so stale+invalid yields `ERR_STALE_WRESTLER_VERSION`, contra §2.8's generic ordering (`plans.py:56-60`); intra-domain assessment guard order pinned with day-capacity LAST (`assess.py:66-91`); `ERR_SAME_ASSESSOR_CONFLICT` fires through either the appeal's contested assessment or `retest_of` (`assess.py:76-79`); `lowest_eligible_class_lbs` recomputed as of the current logical-clock date (`cascade.py:93-109`); the hydration arm does not rewrite the wrestler row (version stands still) (`assess.py:189-197`); multiple non-terminal prior plans all cancelled but `supersedes_plan_id` follows the greatest `created_at` (`plans.py:86-104`); projection baseline is `alpha_weight_lbs` rounded to one decimal FIRST, week zero included (`calc.py:73`); degenerate-rate termination, the week-1000 ceiling, `total_weeks` 0 at target (`calc.py:19,79-99`); the rate gate uses the UNROUNDED stored `alpha_weight_lbs` and sits after the target-floor check (`calc.py:102-107`); regenerated `week_index` starts at zero when deletions left no row (`plans.py:259`); §3.7 eligibility step-by-step null-fallbacks (`calc.py:138-194`); assessor-decertification cascade hop 1 skipped for a non-CERTIFIED assessor, hop 3 walks wrestlers in `created_at` order skipping non-CERTIFIED/PROVISIONAL, hop 5 sets `scratch_reason = PLAN_CANCELLED` and leaves the seed fields alone (`cascade.py:292-351`).

### Pass 3 (compete/safety) — 20 changes: 12 ambiguity-pins, 6 mismatch-revisions, 2 in-pass self-corrections
401 lines / 105,510 chars -> 401 lines / 114,682 chars.
Highlights: **mismatch** — event `name` rejected when empty, not merely when over 160 chars (`compete.py:41`); **mismatch** — the weight-class-change route performs NO ownership check and applies no season-OPEN gate, contrary to prose (`compete.py:340-352`); **mismatch** — only `SEEDED` entries may change class, so `ENTERED`/`WEIGHED_IN`/`SCRATCHED`/`DISQUALIFIED` all yield `ERR_ENTRY_INVALID_STATE` (`compete.py:350`); **mismatch** — a negative `day_index` is a 400 `ERR_INVALID_REQUEST`, with the 422 `ERR_WEIGH_IN_DAY_OUT_OF_RANGE` reserved for an index past the event window (`compete.py:404-416`); **mismatch** — only a flag LEAVING `PROBATION` triggers `restore_from_probation`; `ESCALATED` retains the severity (`safety.py:78-88`); WEIGH_IN_CLOSED reckoning scratches `ENTERED` entries with `NO_WEIGH_IN` and failed weigh-ins with `WEIGH_IN_FAILED` (`compete.py:118-132`); seeding clears a stale `seed_number` on entries that left the seedable pool (`compete.py:170-186`); the eligibility check still runs after its season closes, refreshes `lowest_eligible_class_lbs` without bumping the wrestler's version, and reports `ERR_CLASS_BELOW_CERTIFIED_MINIMUM` even with no certified floor (`compete.py:492-540`); the same assessment may be sampled twice and contributes two deviations (`safety.py:113-126`); audit finalize applies no season-OPEN gate and the five-hop cascade fires only for a `FAIL` on an `ASSESSOR_SAMPLE` audit (`safety.py:201-217`).
**Earlier-pass reconciliation:** pass 2's §3.7 entry-creation refusal list omitted the `BLOCKED_PLAN_BREACHED` branch that `compete.py:236-250` actually raises; pass 3 made a minimal reconciling insert rather than rewriting pass 2's sentence. Pass 2 had likewise declined to edit pass 1's §2.8 generic precedence chain, instead pinning the two real exceptions (assessment finalize's missing DQ freeze; plan creation's version-before-shape order) inline at their own sites — specific over general.

### Totals
**69 changes across three passes: 56 ambiguity-pins, 11 mismatch-revisions, 2 in-pass self-corrections.**

**Orchestrator independent verification:** `PRD.md` 397/92,903 -> `PRD_FINALIZED.md` 397/93,246 -> `PRD_COMPLETED.md` 401/114,682. `cmp PRD_FINALIZED.md PRD_COMPLETED.md` reports DIFFERS (the byte-identical failure mode did NOT occur); `diff` shows 50 changed lines. Structure intact: 5 `##` sections, 19 `### 3.x/2.x` subsections. Endpoint table still 56 rows; error table 59 rows (the original 57 plus the two routing-level rows pass 1 added). File ends cleanly on a complete error-table row.

Step 9 touched no code — `implementation/` and the test suite are unchanged since the clean sweep, so the verified 8x261/261 result stands as the pipeline's final state.

## Pipeline complete — 2026-09-04T12:36:00.000Z

All nine steps finished. Final artifacts: `SCAFFOLD.yaml` + two design indices, `test_helpers/` (9 files, 2710 lines), `test_suite/` (19 files, 261 collected tests), `workspace/implementation/` (19 files, 3954 lines, 56 endpoints), and the PRD chain `PRD.md` -> `PRD_FINALIZED.md` -> `PRD_COMPLETED.md`. Eight retained `results.{1..8}.json` all show 261/261.
