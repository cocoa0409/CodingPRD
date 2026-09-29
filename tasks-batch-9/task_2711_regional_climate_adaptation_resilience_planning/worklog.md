# Worklog — task_2711_regional_climate_adaptation_resilience_planning

## Step 1: Create task directory — 2026-09-04T09:57:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2711_regional_climate_adaptation_resilience_planning` and its `workspace/` subdirectory. Index pre-assigned by the caller (2711); no auto-allocation scan performed.

## Step 2: Generate Scaffold (subagent) — 2026-09-04T11:35:00.000Z

All three scaffold artifacts are complete and the lint is clean. No sibling task directory was read at any point — everything was derived from the scenario text plus the scaffold-generator skill spec.

**Files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_2711_regional_climate_adaptation_resilience_planning/`)

| File | Lines | Size |
|---|---|---|
| `SCAFFOLD.yaml` | 3405 | 164 KB |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1673 | 118 KB |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 5050 | 341 KB |

**SCAFFOLD.yaml (§1.0–§1.7)** — top-level keys `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles, segregation_of_duties`; neither `scaffold_difficulty_design` nor `scaffold_corner_design` is present. 13 entities, 63 endpoints, 14 calculations, 52 priority-ordered validations, 63 error codes, 6 roles, 2 OCC concurrency rules, 1 segregation-of-duties rule. Profile: difficulty `expert_plus`, archetypes multi_party_negotiation + graph_constraint, layers optimistic_concurrency / cascading_side_effects / dual_variant_calculation / rate_threshold_triggers, cyclic state machines, `immediate` consistency.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)** — single key `scaffold_difficulty_design`: 9 rule_ids × 2 = 18 instances (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)** — single key `scaffold_corner_design`, all 9 taxonomy sections, 113 instances of which 96 carry full `test_recipe`s and 17 are `excluded_because` stubs citing §1.8 instances by name: entities 19, state_machines 14, calculations 19, validations 25, endpoints 8, errors 8, rbac 9, cross_cutting_complexity_layers 8, consistency_model 3.

**Lint** (`python3 skills/prd-bench-scaffold-generator/scaffold_lint.py tasks/task_2711_regional_climate_adaptation_resilience_planning`):

```
Coverage
  §1.5 endpoints declared:    63
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     96
  Calls scanned (§1.8+§1.9):  1127

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Notes worth relaying: every numeric literal in the recipes was recomputed with `Decimal` before being asserted (cost stack 47040000/4233600/51273600/2500, screen 0.6925, bcr 1.2190 and 1.4158, priority 0.6129, ledger 86589600/0 → CLOSED, tally 5714/10000); a grep for the forbidden race vocabulary ("simultaneously", "in parallel", "first-writer-wins", …) across all three files returns nothing. One SCAFFOLD.yaml edit was needed during this work: a `pagination_placement` note in `response_envelope` so the corner design's `meta.total_count` / `meta.has_more` assertions are grounded.

Orchestrator verification: all three files parse as YAML; SCAFFOLD.yaml carries neither design key; the two design files each carry exactly their single top-level key.

## Step 3: Copy Shared Files — 2026-09-04T11:35:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD (subagent) — 2026-09-04T11:55:00.000Z

All sections are written and verified. Final state of the deliverable:

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2711_regional_climate_adaptation_resilience_planning/workspace/PRD.md`
**Size:** 489 lines / 13,606 words. Built with 12 chunked `cat >>` appends (never a single Write), so no 64k truncation.

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 Role-Based Access Control · 2.2 API Response Structure (appended byte-identically from the skill's fixed source file) · 2.3 Pagination · 2.4 Record Identity, Revision Counters and the Logical Clock · 2.5 The Validation Ladder · 2.6 Decimal Discipline, Basis Points and Rounding · 2.7 Optimistic Concurrency on the Two Shared Ledgers · 2.8 Conservation of Capital and of Pledged Aid Units · 2.9 Freshness, Cascades and Derived-State Propagation · 2.10 Segregation of Duties and the Equity Waiver
- §3 Business Logic & Workflows — 3.1 Member Jurisdictions and the SVI Overlay · 3.2 Downscaled Hazard Projections and the Republication Cascade · 3.3 Vulnerability Assessment · 3.4 The Lifeline Dependency Graph and Asset Criticality Ranking · 3.5 Proposing and Screening Adaptation Strategies · 3.6 Benefit Attribution and BCA Certification · 3.7 Capital Programming, Equity Gate, Grants, Implementation Tracking · 3.8 Community Engagement and the Weighted Endorsement Loop · 3.9 Mutual Aid Across Jurisdictional Boundaries
- §4 Endpoint Definitions (63-row Method | Path | Description | Authorized Role(s) table)
- §5 Error Code Catalogue (63-row Error ID | HTTP Status table)

**Coverage — machine-verified against SCAFFOLD.yaml**
- **63/63 endpoints**: §4 table matched row-for-row against the scaffold in order — method, path and role list all exact, zero discrepancies; 13 creation endpoints are 201, the rest 200.
- **63/63 errors**: all present in §5 with correct statuses, and all 63 also appear in §1–§4 prose paired with their triggering condition (0 catalogue-only orphans).
- **52/52 validations**: every validation's error ID is described at each of its `applies_to` scopes; the 17 multi-scope rules (e.g. `ERR_PROJECT_NOT_PROGRAMMED` across grant-submission/grant-award/withdraw/indicator-reports, `ERR_INVALID_WINDOW` across all three window-bearing creates, `ERR_ASSET_DEPENDENCY_CYCLE` across create/patch/rank) were each checked individually. Priority ordering in prose matches scaffold priorities.
- **14/14 calculations**: all output fields present verbatim; the two output-less predicate calculations (`aid_peak_overlap_capacity`, `session_window_conflict`) are specified in prose.
- **13/13 entities**: all 178 entity-field, `request_body`/`input`, `query_params` and `path_params` identifiers appear verbatim in backticks — **0 missing**. All 44 field defaults, all enum values, and all 41 state-machine transitions plus every declared state are covered.
- **6/6 roles**: each named individually with its identity model and scoping in §2.1, and used throughout §3.

**Hard Contracts**
- Contract 1 (Field-Name Coverage): **PASS** — two passes. Pass 1: 131 API identifiers, 0 missing. Pass 2: broad sweep of all 230 snake_case tokens in the scaffold; the 89 not present are exclusively scaffold-internal metadata (calculation IDs, archetype/layer labels, formula-local variables like `peak_vuln`/`annuity_factor`, structural YAML keys) — all of which are expressed in prose.
- Contract 2 (Rule Coverage): **PASS** — priorities, both OCC rules, cascade side effects, `applies_to` scopes, defaults/types, sibling-branch symmetry, all transitions, all calculations, all validation/error pairings, all endpoint side effects verified.
- Contract 3 (§3 Path Purity): **PASS** — 313 distinct backtick tokens in §3, zero `/`-leading tokens, zero bare HTTP methods, zero method+path combinations. The only prefix mention (`/resilience`) sits in §1/§2/§4 where it is permitted.

**Repairs made during verification:** four transitions were stated in prose but not in arrow form (`NOT_ANALYZED → BCA_PENDING` and its two sibling origins, `BCA_PENDING → BCA_CERTIFIED`, `BCA_PENDING → BCA_REJECTED`, `UNPROGRAMMED → PROGRAMMED`) — rewritten as explicit arrows; and the aid capacity check was tightened from "must stay within" to an explicit "less than or equal to `pledged_units`, a peak landing exactly on the pledge is admitted".

**Ending:** the file's last line is the final `ERR_ALLOCATION_EXCEEDS_PROJECT_COST | 422` row of the §5 table — a clean section boundary, no mid-sentence truncation, no audit footer. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced.

Orchestrator truncation check (mandated by the caller): `wc -l` = 489; tail shows the §5 error table running to completion and ending on the `ERR_ALLOCATION_EXCEEDS_PROJECT_COST | 422` row — a real section boundary, not mid-sentence. Independently counted 63 endpoint rows in §4 and 63 error rows in §5, and 63 unique `ERR_*` tokens in the PRD against 63 in SCAFFOLD.yaml's `errors`. No regeneration needed.

## Step 6: Generate Implementation (subagent) — 2026-09-04T12:35:00.000Z

Implementation complete for task 2711.

## Files (all under `workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `start.sh` | 10 | launcher (executable) |
| `requirements.txt` | 1 | `flask` |
| `app.py` | 95 | blueprint registration, `ApiError`/404/405/500 handlers, `app.run` |
| `core.py` | 133 | logical clock (epoch `2026-08-01T00:00:00Z`), UUIDs, `req_` ids, ISO-8601 with 3 fractional digits, Decimal helpers (`round_half_up`, `cents`, `floor_int`, `bps_share`) |
| `store.py` | 83 | 13 in-memory dicts + `_seq` insertion tiebreak, `insert`/`touch`/`ordered` |
| `errors.py` | 161 | all 64 error ids → HTTP status + default messages |
| `envelope.py` | 126 | `meta`/`response_type`/`data` envelope, `limit`/`offset`/`total_count`/`has_more`, query filters |
| `auth.py` | 90 | `X-User-ID`/`X-User-Role`, 6 roles, ladder rungs 1–3, `require_owned_jurisdiction` (rung 6) |
| `validate.py` | 177 | rung 7 payload shape + rung 8 window ordering; explicit JSON null == omitted |
| `calc.py` | 344 | vulnerability (2 variants), consequence/criticality, cost stack, screen score, BCA (2 variants), priority, equity bps, funding posture, indicator attainment, session conflict + 24h buffer, quorum tally, aid peak load/overlap |
| `cascades.py` | 218 | 5-hop republication cascade, 4-hop withdrawal compensation, endorsement supersession, program & pact ledger recomputation, dependency-chain walks |
| `serialize.py` | 271 | per-entity serializers, derived pact status |
| `lookup.py` | 117 | existence resolution in declared order (rungs 4–5) |
| `routes/*.py` | 1959 | 14 blueprints: jurisdictions 101, plan_cycles 161, hazards 131, assets 140, assessments 115, projects 187, links 83, analyses 139, programs 128, project_ops 133, sessions 123, endorsements 81, aid 202, clock 23, `__init__.py` 0 |

Total 3573 lines. Every `.py` passes `python3 -m py_compile`; `__pycache__` removed.

## Endpoints
Exactly **63** `/resilience` routes registered. I diffed the registered `method + path` set (path params normalized) against the 63 rows of PRD §4's endpoint table — **identical, zero differences**.

## start.sh contract
`#!/usr/bin/env bash`, `set -euo pipefail`, `cd "$(dirname "$0")"`, guarded install (`if ! python3 -c "import flask"`), then `exec python3 app.py`. `app.py` binds `host="0.0.0.0", port=int(os.environ.get("PORT", "10000"))`, foreground, `use_reloader=False`. Measured cold boot to first served request: **~500 ms**.

## Smoke test (port 30010, killed only by captured PID; no pattern kills)
Three fresh boots exercised ~90 calls end to end. Confirmed working: empty store + clock at epoch on every boot; 401/403 (unknown role, not permitted, jurisdiction scope, segregation of duties); duplicate code/link/endorsement 409s; publish → assess → rank chain (vulnerability 0.31 MODERATE, consequence 1.49 TIER_3); screen (`screen_score` 0.665 → SCREENED_IN, `total_program_cost_cents` 94 976 000); BCA certify/reject with SoD; allocation returning the **project** with `equity_benefit_share_bps`/`priority_score` and OCC 412 on stale program version; ledger arithmetic (`committed + available == authorized`) across allocation, CLOSED posture with `grant_hold_flag` set, `ERR_GRANT_ON_HOLD`, and the 4-hop withdrawal that reopens the program; posture boundary verified (headroom exactly 1000 bps → OPEN, 999 → OVERSUBSCRIBED); grant submission/award/indicator report (`90.00` → ON_TRACK); engagement session with 24h-buffer conflict rejection and `equity_reach_bps` 4500; endorsement round, `ERR_CONDITION_NOTE_REQUIRED`, tally (weight 3 ENDORSED + 1 CONDITIONED halved-and-floored → 7500 bps, ADOPTED) and close → ADOPTED; mutual aid pact/commitment with all nine ordered guards fired individually, half-open window ledger, fulfill leaving reserved/free untouched, clock-derived EXPIRED status; 5-hop republication cascade (assessment STALE, asset RECOMPUTE_REQUIRED with nulled ranking fields, analysis STALE/`ASSET_RECOMPUTE`, project BCA_STALE); pagination and `ERR_INVALID_REQUEST` on `limit=0`. No unexpected results remained (the six initial mismatches were bugs in my throwaway smoke script — wrong role and missing `preferred_strategy_type` — not in the server).

Two spec judgment calls worth flagging to the test-suite side: `discount_rate_bps` accepts **1..2000** (PRD §3.6 and the entity constraint over §2.5's "0–2000"), and aid concurrency rejects when the peak overlap **count including the candidate** reaches `max_concurrent_commitments`, per SCAFFOLD's `aid_peak_overlap_capacity` formula and PRD's "strictly below" wording.

Orchestrator note: Steps 5 and 6 were launched concurrently in a single assistant message, so this impl-gen subagent started before `test_suite/` existed on disk and was additionally forbidden from reading `test_helpers/`, `test_suite/`, and both design YAMLs — physical plus instructed isolation.

## Step 5 — Unit test suite generated (design-index-only)

`test_helpers/` (9 files, 2 359 lines) and `test_suite/` (conftest + 18 test modules,
8 147 lines) both live directly under the task root; nothing was written into
`workspace/`. 144 tests, every one carrying exactly one trailing
`Design: Difficulty/<rule>/<instance>` or `Design: Corner/<section>/<instance>` line.

Coverage: all 18 §1.8 difficulty instances translated with ≥2 tests each (37 tests);
95 of the 96 live §1.9 corner instances translated (107 tests); the 17
`excluded_because:` stubs got no tests and all 17 of their `difficulty_instance`
cross-references resolve.

Only skip: `calculations/aid_pact_expired_is_evaluated_before_exhausted`. It requires a
plain GET to flip a persisted pact `status` from `EXHAUSTED` to `EXPIRED` after the clock
advances, but PRD 3.9 re-derives that status only "on a successful commitment" and on
release; the PRD never says a retrieval recomputes it, so the asserted outcome is not
uniquely derivable. Gap left as a gap.

Fixed during the final citation/field passes: `ApiErrorId` members were missing their
`ERR_` prefix (every error assertion in the suite would have raised `AttributeError`);
`test_04` asserted a non-existent `posture` field instead of `funding_posture`; and eight
docstrings quoted the PRD non-verbatim (including two citing a "reads are strongly
consistent with writes" sentence that does not exist in this PRD — replaced with §4's
"a create or mutate operation returns the created or updated resource in the `data`
field").

PRD-vs-yaml contradictions recorded, PRD followed in every case: the yaml expects
`allocated_cents` null on an unfunded project where PRD 3.5 says 0; the yaml uses
`grant_funder: "FEMA-BRIC"` where PRD 3.7 enumerates only `BRIC`, `HMGP`,
`STATE_RESILIENCE`; the yaml asserts a `reviewed_by_user_id` field the PRD never declares
(PRD 2.10 records `certified_by_user_id`); the yaml asserts literal
`projected_outcome` values (`SHORT`, `ADOPTED`) where PRD 3.8 only promises "a
`projected_outcome` string naming which of the three outcomes closing the round right now
would produce", so the tests assert the string is non-empty and that it changes once the
quorum is cleared.

## Step 5: Generate Unit Tests (subagent) — 2026-09-04T13:55:00.000Z

Step 5 is complete.

## Deliverables (all at the task root, nothing under `workspace/`)

`test_helpers/` — 9 files, 2,359 lines: `__init__.py` 53, `api_client.py` 336, `api_errors.py` 162, `assertions.py` 192, `constants.py` 144, `factories.py` 412, `fixtures.py` 636, `test_users.py` 90, `types.py` 334.

`test_suite/` — `conftest.py` 47 plus 18 modules, 8,147 lines: `test_01` 264/5 tests, `test_02` 225/4, `test_03` 251/4, `test_04` 259/4, `test_05` 221/4, `test_06` 238/4, `test_07` 246/4, `test_08` 262/4, `test_09` 247/4, `test_10_entity_contracts` 698/16, `test_11_state_machines` 679/14, `test_12_calculations` 886/13, `test_13_validations` 994/19, `test_14_endpoints` 774/13, `test_15_errors` 579/10, `test_16_rbac` 470/10, `test_17_complexity_layers` 567/9, `test_18_consistency` 240/3.

**144 tests total.** Every `.py` passes `py_compile`; `test_suite/` is pyflakes-clean.

## Coverage

- Queue A (§1.8): 18/18 instances, 0 stubs, 37 tests, every instance >=2 tests.
- Queue B (§1.9): 95/96 live instances, 107 tests; the 17 `excluded_because:` stubs got no tests and all 17 `difficulty_instance` cross-references resolve.
- Every test carries exactly one trailing `Design:` line; no tag points at a nonexistent instance or at a stub.

**One skip:** `calculations/aid_pact_expired_is_evaluated_before_exhausted`. It requires a plain GET to flip a persisted pact `status` from `EXHAUSTED` to `EXPIRED` after the clock advances, but PRD 3.9 re-derives pact status only on a successful commitment and on release — the PRD never says a retrieval recomputes it, so the asserted outcome is not uniquely derivable. Left as a gap.

## Bugs found and fixed in the final passes

1. **`ApiErrorId` enum members lacked the `ERR_` prefix** while all 63 distinct references use `ApiErrorId.ERR_*` — every error assertion in the suite would have raised `AttributeError`. All 63 now resolve, and every `validate_error(..., status)` matches the PRD §5 status table (0 mismatches).
2. **`test_04` asserted a nonexistent field `posture`** instead of `funding_posture` (would have failed against a correct implementation). An AST field-name sweep confirms no other asserted key is unknown to the PRD/scaffold.
3. **Eight docstrings quoted the PRD non-verbatim**, including two that cited a "reads are strongly consistent with writes" sentence that does **not exist** in this PRD (replaced by §4's "a create or mutate operation returns the created or updated resource in the `data` field of the envelope described in §2.2"), plus a fabricated "the withdrawn project itself keeps whatever `grant_hold_flag` value it carried" sentence (demoted to my own reasoning). A verbatim-substring checker over all 144 docstrings now reports zero non-verbatim quotations.

## PRD-vs-yaml contradictions (PRD followed in every case)

`allocated_cents` null (yaml) vs 0 (PRD 3.5) on an unfunded project; `grant_funder: "FEMA-BRIC"` (yaml) vs the enum `BRIC | HMGP | STATE_RESILIENCE` (PRD 3.7); the yaml's `reviewed_by_user_id` field, which the PRD calls `certified_by_user_id` (PRD 2.10); literal `projected_outcome` values `SHORT`/`ADOPTED` (yaml) where PRD 3.8 promises only "a `projected_outcome` string naming which of the three outcomes ... would produce" — asserted as non-empty and as changing once the quorum is cleared; plus the previously recorded `achieved_weight_bps` null-vs-0, CANCELLED-session `attendee_count` null-vs-0, suspended-jurisdiction prose, and the yaml's "PROBATION is not blocked" claim.

Orchestrator verification: `test_helpers/` and `test_suite/` both sit at the task root (a known drift is Step 5 writing them under `workspace/`); `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/`. Independently counted 19 files in `test_suite/` and 144 `def test_` functions. Stale `__pycache__` directories removed before Step 7.

## Step 7: Run Tests and Iterate — 2026-09-04T14:10:00.000Z

Two iterations, each an 8-round parallel stability sweep (`setsid nohup`, `--isolation
per-test-server`, 144 tests, per-round `results.$i.json`).

**Iteration 1** — 142/144 in all 8 rounds; the same 2 tests failed in every round, so
neither was flakiness or load.

1. `test_14_endpoints::TestFulfilmentAndReleaseExcludeEachOther::test_a_fulfilled_draw_refuses_release_and_keeps_its_units_reserved`
   — 403 `ERR_JURISDICTION_SCOPE_VIOLATION` on `fulfill`. The test built its delegate
   headers from Harbor, the pact **host**, while PRD 2.1 says a `JurisdictionDelegate`'s
   ownership check on a mutual aid commitment compares `X-User-ID` to "the
   `requesting_jurisdiction_id` of a mutual aid commitment" — Ridge in that fixture.
   Test bug (request identity), fixed in `test_suite/`: both the `fulfill` and the
   follow-up `release` now use Ridge's headers, so the release refusal reaches the
   state guard (`ERR_COMMITMENT_NOT_ACTIVE`) instead of stopping at ladder rung 6.

2. `test_17_complexity_layers::TestTheGrantHoldFollowsTheFundingPosture::test_the_allocation_that_zeroes_the_headroom_raises_the_hold`
   — setup 412 `ERR_STALE_PROGRAM_VERSION`. The second allocation quoted
   `open_program["version"] + 1`, but `open_program` had already been re-read *after*
   the first allocation moved the program 1 → 2, so it quoted 3 against a stored 2.
   PRD 2.7 requires the version the client last observed. Test bug (request payload),
   fixed in `test_suite/` by dropping the `+ 1`; the sibling test in the same class
   already used the un-incremented `read_capital_program(program_id)["version"]`.

**Iteration 2** — clean: all 8 rounds `passed == total == 144`, 0 failed, 0 errors,
0 skipped.

No test was deleted (no PRD-silence or unique-derivability collapse was reached — both
failures resolved at STEP 2 of the protocol). No change was made to `test_helpers/` and
no change was made to `workspace/implementation/`.

## Step 7: Run Tests and Iterate (subagent — orchestrator-recorded summary) — 2026-09-04T14:16:00.000Z

Clean exit. All 8 parallel rounds pass 144/144.

**Iterations run:** 2

**Iteration 1** — 142/144 in all 8 rounds. The same 2 tests failed in every round (deterministic, not flakiness or host load). Both resolved at STEP 2 of the protocol (test not faithful to PRD); neither reached STEP 1 deletion or STEP 3 implementation change.

**Iteration 2** — clean: every round `passed == total == 144`, 0 failed / 0 errors / 0 skipped.

**Tests deleted:** none. Neither failure was a PRD-silence or unique-derivability collapse — both cited PRD rules verbatim and were uniquely derivable; the defects were in the requests the tests issued.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

**Fixes applied to `test_suite/`:**

1. `test_suite/test_14_endpoints.py` — `TestFulfilmentAndReleaseExcludeEachOther::test_a_fulfilled_draw_refuses_release_and_keeps_its_units_reserved`. The test built its `JurisdictionDelegate` headers from Harbor, the pact **host**, and got a correct 403 `ERR_JURISDICTION_SCOPE_VIOLATION`. PRD §2.1: for a `JurisdictionDelegate`, "ownership checks compare `X-User-ID` to ... the `requesting_jurisdiction_id` of a mutual aid commitment" — Ridge in that fixture. Switched both the `fulfill` and the follow-up `release` calls to Ridge's headers, so the release refusal now reaches the state guard (`ERR_COMMITMENT_NOT_ACTIVE`, 409) instead of stopping at ladder rung 6.

2. `test_suite/test_17_complexity_layers.py` — `TestTheGrantHoldFollowsTheFundingPosture::test_the_allocation_that_zeroes_the_headroom_raises_the_hold`. Setup died on 412 `ERR_STALE_PROGRAM_VERSION`: the second allocation quoted `open_program["version"] + 1`, but `open_program` had already been re-read *after* the first allocation moved the program 1 → 2, so it quoted 3 against a stored 2. PRD §2.7 requires the version the client last observed. Dropped the `+ 1`; the sibling test in the same class already used the un-incremented `read_capital_program(program_id)["version"]`, which independently confirms the value the implementation stores is correct.

Key finding: the implementation needed no changes — both red tests were artifact bugs, one an identity-model misread (host vs. requester on a deliberately cross-jurisdictional row) and one an off-by-one on an optimistic-concurrency token.

**Orchestrator verification of the sweep artifacts** (a known failure mode is a Step 7 agent claiming a clean sweep while leaving nothing behind): all 8 `workspace/implementation/results.{1..8}.json` exist and parse; every one reports `passed=144 total=144 failed=0 errors=0 skipped=0`. `test_suite/` still holds 19 files and 144 `def test_` functions, matching Step 5's output — confirming the 0-deletions claim.

**Step 8 gating decision:** Step 7 made 2 `test_suite/` fixes, so the skip condition (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes) is NOT met — Step 8 runs. Note in advance that because there were 0 `implementation/` fixes, a byte-identical `PRD_FINALIZED.md` is a legitimate Step 8 outcome here: both fixes were test-side identity/OCC-token bugs, not PRD silences. Step 9 must still produce a materially different `PRD_COMPLETED.md`.

## Step 8: Finalize PRD (subagent) — 2026-09-04T14:25:00.000Z

## Result

`PRD_FINALIZED.md` was created and is **byte-identical to `PRD.md`** (both 489 lines, md5 `cd0e6cf8fb5461af674a45d45b970fd7`, 0 line delta, 0% change). Both Step 7 items are pure test-artifact bugs; the PRD already pins each behavior uniquely, so there is nothing to patch and no edit was manufactured.

### Changes
None.

### Item 1 — `JurisdictionDelegate` ownership on a mutual aid commitment; fulfil/release ladder order

**Impl paths read/grepped**
- `implementation/auth.py:76-90` — `require_owned_jurisdiction()`; scoped only to `ProjectSponsor`/`JurisdictionDelegate`, raises `ERR_JURISDICTION_SCOPE_VIOLATION` when the passed jurisdiction id != `X-User-ID`.
- `implementation/routes/aid.py:167-184` (`release_commitment`) and `:187-202` (`fulfill_commitment`) — both resolve the commitment (rung 4) then call `require_owned_jurisdiction(commitment["requesting_jurisdiction_id"], ...)` **before** the `status != "COMMITTED"` → `ERR_COMMITMENT_NOT_ACTIVE` (409) guard. Neither endpoint consults the pact's `host_jurisdiction_id`.
- Every other rung-6 callsite, to confirm the per-entity mapping is uniform and that no wording change would be needed anywhere: `routes/aid.py:28` (pact → `host_jurisdiction_id`), `routes/aid.py:91` (commitment create → body `requesting_jurisdiction_id`), `routes/sessions.py:97` (session complete → `host_jurisdiction_id`), `routes/sessions.py:30` (session schedule → host), `routes/endorsements.py:29` (endorsement → `jurisdiction_id`), `routes/projects.py:36,141`, `routes/project_ops.py:29,55,116`, `routes/links.py:24`, `routes/analyses.py:27` (all → project `jurisdiction_id`). Reads are unguarded (`@guard()` with no role list), matching §2.1's broad-read rule.

**PRD sentences that already pin it (verbatim)**
- §2.1: "ownership checks compare `X-User-ID` to the `jurisdiction_id` of an endorsement, the `host_jurisdiction_id` of an engagement session or a mutual aid pact, and the `requesting_jurisdiction_id` of a mutual aid commitment."
- §2.5 rung 6: "For a `JurisdictionDelegate` it is the endorsement's `jurisdiction_id`, the engagement session's `host_jurisdiction_id`, the mutual aid pact's `host_jurisdiction_id`, or the mutual aid commitment's `requesting_jurisdiction_id`, whichever the endpoint targets." Rung 6 sits above domain logic ("Everything from priority 9 downwards is domain logic ... in that broad order"), so 403 scope precedes the 409 `ERR_COMMITMENT_NOT_ACTIVE` state guard by construction — exactly the ordering the fixed test now observes.
- §3.9 fulfil paragraph ("Only the commitment's `version` increments by 1", reserved/free unchanged) matches `routes/aid.py:194-202`, which touches only the commitment.

### Item 2 — which `version` the client must quote for optimistic concurrency

**Impl paths read/grepped**
- `implementation/routes/programs.py:70-81` — `expected_capital_program_version` is `required=True`, compared with `!=` against `program["version"]` as stored, before any equity/ranking/cost/funds arithmetic; failure is `ERR_STALE_PROGRAM_VERSION`.
- `implementation/routes/aid.py:96-110` — the parallel site: `expected_mutual_aid_pact_version`, `required=True`, `!= pact["version"]` → `ERR_STALE_PACT_VERSION`, placed at guard 4, before the concurrency-count and peak-load checks.
- `implementation/store.py:53-69` — `insert()` stamps `version = 1`; `touch()` does `version + 1`. So "the version the client last observed" is literally the stored integer.
- `implementation/routes/programs.py:123-127` + `implementation/cascades.py:160-188` — a successful allocation bumps the program exactly once (`store.touch(program)`), and `skip_touch` keeps the allocated project at exactly one bump even when the grant-hold pass also flips its flag. So the next client-quoted version after one allocation is `stored + 0`, i.e. the re-read value — which is precisely what the fixed test now sends.
- Grepped for any other `expected_` field: none exist, matching §2.7's "No other endpoint in the system takes a version field."

**PRD sentences that already pin it (verbatim)**
- §2.7: "the write request must carry the version the client last observed on the parent record, and the server compares that value against the parent's stored `version` **before** it evaluates any capacity or ledger rule"; "If it does not equal the target `CapitalProgram`'s current `version` ... the request is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412) and no ledger field is touched. On success the program's `version` increments by 1, which means replaying the identical request with the same expected version is rejected on the second call."
- §3.7 guard 2: "`expected_capital_program_version` must equal the program's current `version`, or `ERR_STALE_PROGRAM_VERSION` (HTTP 412), evaluated before any ledger field is read for writing."
- §3.7 allocation side effects: "The program's `version` increments by 1, and the allocated project's `version` increments by 1."

The failing fixture had quoted `stored + 1`; nothing in the PRD licenses an increment on the client side, so this was an off-by-one in the test, not PRD silence.

### Deliberately not edited (would exceed HARD SCOPE)
While enumerating item 2 I noticed `validate.int_field(..., minimum=0)` makes a *negative* `expected_capital_program_version`/`expected_mutual_aid_pact_version` return `ERR_INVALID_REQUEST` (422) rather than 412, and §2.5 rung 7's non-negativity list ("every amount in cents, every unit count and every basis-point integer") does not name version fields. That path was never exercised by either Step 7 failure and is not traceable to a Step 7 fix, so I left it alone rather than risk a new false universal.

**Orchestrator note:** the byte-identical outcome is accepted as legitimate here, per the skill's own reasoning — Step 7 applied 0 fixes to `implementation/`, so there is no site at which the implementation chose a behavior the PRD left open. Independently confirmed with `md5sum` that both files hash to `cd0e6cf8fb5461af674a45d45b970fd7`. Step 9 is unaffected by this and always runs; it must produce a materially different `PRD_COMPLETED.md` (a byte-identical Step 9 output would mean the full-impl scan never ran).

## Step 9: Complete PRD (4 partitioned subagent passes) — 2026-09-04T15:05:00.000Z

Step 9 was run as FOUR sequential, module-partitioned passes over one shared `workspace/PRD_COMPLETED.md` (pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2–4 were explicitly forbidden to `cp` and edited in place). Partition: pass 1 = app/core/store/errors/envelope/auth/validate/lookup/serialize; pass 2 = calc.py + cascades.py; pass 3 = routes/{clock,jurisdictions,plan_cycles,hazards,assets,assessments,links}.py; pass 4 = routes/{projects,analyses,programs,project_ops,sessions,endorsements,aid}.py. Cross-partition findings were carried forward as explicit handoff items rather than patched out of partition.

**Totals: 489 lines (unchanged) — 97,685 → 113,867 chars, +16,182 chars, 41 changed lines. 39 pins/revisions: 29 ambiguity-pins, 8 mismatch-revisions (pass 1: 15 pins / 0 mismatches; pass 2: 5 / 1; pass 3: 9 / 3; pass 4: 10 / 4).** (Two pass-4 items are counted in its mismatch tally but landed as inserts.)

### Pass 1 — infrastructure and cross-cutting layers (15 ambiguity-pins, 0 mismatches)
- §2.2 — insert — ambiguity — `api_request_id` shape pinned: `req_` + exactly 20 chars from `A`–`Z`/`0`–`9` (24 total), regenerated per response including errors, never persisted — core.py:45-49
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not the wall clock — envelope.py:14-18
- §2.2 — insert — ambiguity — a resource projects the same field set everywhere, and null-valued fields are always present as JSON `null` rather than omitted — serialize.py:10-21
- §2.3 — insert — ambiguity — `limit`/`offset` parsed as integers with whitespace tolerated; non-integer, out-of-range `limit`, or negative `offset` → `ERR_INVALID_REQUEST` 422; an *empty* parameter value is not equivalent to omitting it and is rejected — envelope.py:42-65
- §2.3 — insert — ambiguity — `created_at` ties (ubiquitous because the clock is frozen) are broken by insertion order — store.py:73-75
- §2.3 — insert — ambiguity — filter semantics: exact case-sensitive equality; a non-member enum value matches nothing rather than erroring; boolean filters accept `true/false/1/0` any case else 422; integer filters must parse else 422; unknown query params ignored — envelope.py:90-126
- §2.4 — insert — ambiguity — `id` is a random v4 UUID in canonical lowercase 36-char hyphenated form — core.py:40-42
- §2.4 — insert — ambiguity — the clock may move forwards or backwards, retains full supplied precision for comparisons, while rendering truncates (not rounds) to 3 fractional digits — core.py:52-57, routes/clock.py:22
- §2.5 rung 1 — insert — ambiguity — whitespace-only header counts as empty; `X-User-ID` examined before `X-User-Role` — auth.py:37-43
- §2.5 rung 5 — insert — ambiguity — an absent or explicitly-null reference is not resolved at rung 5 (deferred to rung 7); a non-string reference value yields that field's not-found code, not a shape error — lookup.py:44-59
- §2.5 rung 7 — insert — ambiguity — unparseable/absent body read as `{}`; non-object body is a shape violation; explicit JSON `null` == omitted; strict per-type rules (string vs number vs bool vs enum vs ISO-8601 timestamp), numeric strings accepted, booleans/blank strings/non-finite rejected, fractional value rejected for integer fields; range rules apply only after the type settles — validate.py:16-169
- §2.6 — insert — ambiguity — cents/units/bps emitted as JSON integers, decimal scores as JSON numbers (not strings), so trailing zeros are not preserved (`0.50` → `0.5`) — core.py:127-133
- §2.6 — insert — ambiguity — a bps ratio is `floor(10000 x num / den)` in exact decimal arithmetic, all such shares non-negative, and a zero/absent denominator yields 0 bps rather than an error — core.py:115-124
- §3.9 — insert — ambiguity — pact `status` is **derived on every read** (and by the `status` filter) from the clock and `free_units`, so advancing the clock past `window_end` makes the next read report `EXPIRED` with no version bump or `updated_at` refresh — serialize.py:233-239 (cross-ref routes/aid.py:64)
- §4 — insert — ambiguity — a trailing slash on any path is accepted as equivalent — app.py:51
- §5 — insert — ambiguity — routing-level identifiers outside the table pinned: unroutable path → `ERR_NOT_FOUND` 404, wrong method → `ERR_METHOD_NOT_ALLOWED` 405, transport-level malformed request → `ERR_INVALID_REQUEST` 422, all in the standard error envelope — app.py:61-76, errors.py:77-78

Pass 1 recorded 0 mismatches: §5's catalogue matches `errors.py` code-for-code and status-for-status, §2.7/§2.8/§2.10 matched, and ladder rungs 1–8 matched `auth.py`/`lookup.py`/`validate.py` ordering exactly.

### Pass 2 — calculations and cascades (5 ambiguity-pins, 1 mismatch)
- §3.2 Hop 3 — insert — ambiguity — the cascade terminates after hop 3 when hop 3 moved no asset out of `RANKED`; hops 4 and 5 then do not run at all — cascades.py:88-89
- §3.2 Hop 5 — insert — ambiguity — the cascade-driven `→ REVISION`/`→ FAILED` push computes no tally, so `achieved_weight_bps` is left exactly as it stood (still null if no operator ever closed a round); `revision_count` is left unincremented on the `FAILED` edge — cascades.py:119-130
- §3.6 — insert — ambiguity — `cost_measure_cents == 0` (reachable under `ANNUALIZED_EQUIVALENT` when a tiny capital amount rounds both annual components to 0 cents) does not divide: `bcr` is defined as `0.0000`, `grant_eligible` false — calc.py:203
- §3.7 — insert — ambiguity — `equity_committed_cents` reads each project's *stored* `equity_benefit_share_bps` snapshot (frozen at that project's own allocation), never re-derived from its links at recomputation time — cascades.py:169-171
- §3.7 — revise — ambiguity — a non-`CLOSED` recomputed posture clears `grant_hold_flag` across the same `PROGRAMMED` set (this is what realises withdrawal hop 4); the flag is written only where the value actually differs, so an already-correct sibling is untouched and its `version` does not move; the acting project takes exactly one `version` increment even when the recomputation also flips its own hold flag — cascades.py:180-188
- §3.9 guard 8 — revise — **mismatch** — the candidate window is itself counted, so a limit of 3 admits a candidate only where at most two windows (candidate included) are occupied at one window start. The old illustration ("a *fourth* window ... rejected on a pact whose limit is 3") invited the wrong reading that the count excludes the candidate; corrected to "a *third* window covering the same instant as two others" — calc.py:331 + routes/aid.py:123

### Pass 3 — routes group A (9 ambiguity-pins, 3 mismatches)
- §2.4 — revise — mismatch — `endorsement_deadline` removed from the list of values compared against the logical clock; it is stored/projected but never compared, so it gates nothing — plan_cycles.py:26,46
- §2.4 — insert — ambiguity — clock endpoint: `to_iso8601` is required and must parse as ISO 8601; the 200 `data` carries `current_utc` and nothing else — clock.py:20-23
- §2.5 rung 7 — insert — ambiguity — an operation declaring no input fields never reads the request body, so a non-JSON-object body sent to it is ignored, not rejected — hazards.py:82, assets.py:114, assessments.py:83, plan_cycles.py:71,82,123
- §2.5 rung 7 — insert — ambiguity — fields are validated one at a time in declared order, all of a field's checks completing before the next field is read, so two-field violations report the earlier field — jurisdictions.py:27-40
- §3.1 — insert — ambiguity — PATCH jurisdiction: only the three named fields are read (others ignored), none is required, and an empty amendment still refreshes `updated_at` and bumps `version` — jurisdictions.py:86-100
- §3.2 — insert — ambiguity — all three projection fields are required on a revision, and the shape rung precedes the `PUBLISHED` check so a malformed revision against a non-published profile reports `ERR_INVALID_REQUEST` — hazards.py:114-120
- §3.3 — insert — ambiguity — opening an assessment imposes no state gate on the profile (`DRAFT`/`SUPERSEDED` accepted) or the asset, and the same profile/asset/subject_type triple may be opened repeatedly (no uniqueness check) — assessments.py:24-57
- §3.4 — revise — mismatch — PATCH asset: `ERR_ASSET_ALREADY_RANKED` is evaluated **before** the cycle walk; only `is_shared`/`upstream_asset_id` are read; and `upstream_asset_id` honours an explicit JSON `null` as "detach" rather than treating it as omission (a documented exception to the global rung-7 null rule) — assets.py:97-108
- §3.6 — insert — ambiguity — the linked asset may belong to any jurisdiction, not just the sponsor's, and need not be `RANKED` at link time — links.py:21-36
- §3.8 — revise — mismatch — plan-cycle creation: `endorsement_deadline` is a required instant recorded as a governance date only; any instant is accepted and it never blocks a cast — plan_cycles.py:26
- §3.8 — insert — ambiguity — on the ADOPTED close branch endorsements stay live (nothing set to `SUPERSEDED`) and no session or project is touched — plan_cycles.py:132-134
- §3.8 — insert — ambiguity — tally projection: `projected_outcome` in {`ADOPTED`,`BLOCKED`,`SHORT`}; the seven fields are the whole `data` object (no `id`/`created_at`/`updated_at`/`version`); readable in every cycle state including `DRAFT`, where all numerators read 0 and the outcome reads `SHORT` — plan_cycles.py:148-161, calc.py:300-305

### Pass 4 — routes group B (10 ambiguity-pins, 4 mismatches)
- §2.5 rung 7 — revise — mismatch — `service_life_years` "at least 1" → "between 10 and 75 inclusive"; `discount_rate_bps` "0 and 2000" → "1 and 2000" — projects.py:43, analyses.py:31
- §2.5 rung 5 — insert — ambiguity — an omitted/null **required** reference raises its missing-field `ERR_INVALID_REQUEST` as soon as field order reaches it, so a later-declared unresolvable reference is never examined (422 beats the 404) — projects.py:28-33, aid.py:85-90
- §2.3 — revise — ambiguity — integer filters enumerated as exactly `round_number` and `fiscal_year` — programs.py:48, endorsements.py:72
- §3.4 — revise — mismatch — `upstream_asset_id` was claimed the *single* explicit-null-detaches field; now "one of only two", the other being project amendment's prerequisite edge — projects.py:153
- §3.5 — insert — ambiguity — the named prerequisite may be owned by any jurisdiction and sit in any state; `AWARDED` bites only at grant submission — projects.py:34, project_ops.py:61
- §3.5 — revise — ambiguity — "gated three ways" → "evaluated in exactly this order" (ACTIVE → cycle state → prerequisite chain) — projects.py:54-60,102
- §3.5 — insert — ambiguity — `waiver_rationale` added to the null-on-creation list — projects.py:87
- §3.5 — insert — mismatch — explicit `null` on `prerequisite_project_id` detaches (indicator fields keep the ordinary reading and can never be cleared); unknown fields ignored; state check precedes the chain walk; empty amendment accepted and still bumps `version`/`updated_at` — projects.py:143-162
- §3.7 — insert — ambiguity — `allocated_cents` need only be non-negative; a zero-cent allocation is admitted — programs.py:69
- §3.7 — insert — ambiguity — the allocation response `data` is the updated **project**, not the path-addressed program, at HTTP 200 — programs.py:128
- §3.7 — insert — ambiguity — equity waiver: no state precondition, any `program_status`, re-waiving accepted and overwrites the rationale, no jurisdiction scoping, rationale unbounded above — project_ops.py:99-109
- §3.7 — insert — mismatch — a project whose certified case went `STALE` (no `CERTIFIED` analysis at all) reports `ERR_BCR_BELOW_FLOOR`, not `ERR_BCA_NOT_CERTIFIED` — project_ops.py:66-73
- §3.7 — insert — ambiguity — the withdrawing project leaves `PROGRAMMED` at hop 1 and so **keeps** its `grant_hold_flag`; its own `version` moves exactly once across the cascade; response is the withdrawn project at 200 — project_ops.py:39-48, cascades.py:181-188
- §3.7 — insert — ambiguity — `reported_value` has no range constraint (zero/negative accepted → `OFF_TRACK`); `period_label` unbounded and non-unique, so a repeat period counts again; no report resource is persisted, the project is returned at 200 — project_ops.py:118-133
- §3.8 — insert — ambiguity — client-supplied `SUPERSEDED` → `ERR_INVALID_REQUEST`; a note alongside `ENDORSED`/`VETOED` is a rung-7 shape violation raised **before** the four domain checks — endorsements.py:31-34
- §3.9 — insert — mismatch — nothing constrains the pledge window against the clock, and since `status` is derived at projection time a pact created with a past `window_end` reads `EXPIRED` on its own 201 response — aid.py:44-55, serialize.py:233-239

### Cross-pass handoff resolutions (pass 4)
1. **Confirmed + patched** — `analyses.py:31` uses `minimum=1`; §2.5's `0` corrected to `1`.
2. **Confirmed + patched** — `projects.py:42-44` enforces `minimum=10, maximum=75`; §2.5's "at least 1" corrected.
3. **Confirmed already correct** — `grep -rn endorsement_deadline implementation/` yields only `plan_cycles.py:26` (read), `plan_cycles.py:46` (store), `serialize.py:50` (project). No comparison site anywhere, none in `endorsements.py`. Pass 3's §2.4/§3.8 revision stands.
4. **Refuted** — all three `require_window` call sites (`sessions.py:33-35`, `aid.py:34-39`, `aid.py:94-101`) read both bounds with `required=True`, and `validate.has()` treats explicit `null` as absent, so a missing bound is rejected as `ERR_INVALID_REQUEST` and `None` can never reach the no-op branch. No session, pact or commitment can exist with a one-sided window; nothing to patch.
5. **Partly refuted, no PRD change warranted** — `programs.py:125` does pass `skip_touch=(project["id"],)`, so pass 2's §3.7 "exactly once in total" is correct. But `project_ops.py:45` also passes `skip_touch` (pass 2's premise was wrong). It is behaviourally inert: `cascades.py:181-188` only touches rows still in `PROGRAMMED`, and the withdrawing project is already `WITHDRAWN` by then, so its single bump comes from `store.touch(project)` at line 47 either way. Pass 4 pinned the observable facts instead of the mechanism.

### Orchestrator verification
- `PRD_COMPLETED.md` md5 `9406a148eb3f1629ac82a15dc3b22bd1` vs `PRD_FINALIZED.md` `cd0e6cf8fb5461af674a45d45b970fd7` — materially different, so the full-impl scan demonstrably ran (a byte-identical Step 9 output would have meant it did not).
- `diff PRD_FINALIZED.md PRD_COMPLETED.md` = 41 changed lines = 15 (pass 1) + 6 (pass 2) + 12 (pass 3) + 12 newly-diverging (pass 4); no pass clobbered an earlier pass's work (each later pass re-grepped the earlier passes' hallmark phrasings).
- Truncation check: 489 lines, all five `## ` headings present at lines 3/11/156/351/421, §4 still 63 endpoint rows, §5 still 63 error rows, final line still `` | `ERR_ALLOCATION_EXCEEDS_PROJECT_COST` | 422 | ``.
- Steps 8 and 9 touched only `workspace/PRD_FINALIZED.md` and `workspace/PRD_COMPLETED.md`; no `.py` under `test_suite/`, `test_helpers/` or `workspace/implementation/` was modified after the final green sweep, and `test_suite/` still holds 144 test functions. The 8 green `results.{1..8}.json` therefore remain valid evidence for the delivered artifact.

**Pipeline complete.** All nine steps done; `workspace/PRD_COMPLETED.md` written.
