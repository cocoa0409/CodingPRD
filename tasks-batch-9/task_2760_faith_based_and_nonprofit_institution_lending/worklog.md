# Worklog — task_2760_faith_based_and_nonprofit_institution_lending

## Step 1: Create task directory — 2026-09-04T17:25:40.715Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2760_faith_based_and_nonprofit_institution_lending` and its `workspace/` subdirectory. Index 2760 was pre-assigned by the orchestrating prompt; no scan of ./tasks/ was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold artifacts — 2026-09-04T19:32:00Z

Wrote `SCAFFOLD.yaml` (§1.0–§1.7, 3069 lines): 11 entities, 9 state-machine blocks over 8 entities, 2 concurrency rules, 9 calculations, 52 validations (unique priorities 1–52), 60 endpoints, 52 errors, 6 roles. Profile: multi_party_negotiation / ledger_reconciliation, layers [optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers], flat topology, cyclic state machine, segregation_of_duties, immediate consistency, expert_plus.

Wrote `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, 1891 lines): 9 rule_ids / 19 instances. Wrote `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, 3723 lines): 8 sections / 81 instances (60 with test recipes, 21 `excluded_because` stubs pointing at §1.8). No `errors` section — guide Table 6 declares no claim-type rows and is a triggerability audit only; all 52 error codes are asserted somewhere across the two design files.

`scaffold_lint.py`: VERDICT clean lint (60 endpoints, 11 entities, 19 §1.8 + 60 §1.9 instances, 977 calls scanned). Generated with no reads of sibling task directories, per the orchestrating prompt.

## Step 2b: Strip difficulty directive from SCAFFOLD.yaml — 2026-09-04T19:33:00.000Z

Orchestrator edit (not a subagent). The Step 2 subagent, following the verbatim-scenario instruction, left the line `Generate task harder than expert level!` as the first line of SCAFFOLD.yaml's `scenario:` block. That directive is for the scaffold generator only and must never reach PRD.md, so the orchestrator deleted line 9 (the directive) and the blank line 10 that followed it, leaving `scenario:` starting at the "2760. Faith-Based and Nonprofit Institution Lending ..." text. Verified: `grep -c "harder than expert" SCAFFOLD.yaml` → 0, and `yaml.safe_load` still parses with all 13 top-level keys intact. The directive never appeared in SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml.

## Step 3: Copy shared files — 2026-09-04T19:33:26.308Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T19:50:00.000Z

PRD complete and verified.

**Output:** `workspace/PRD.md` — **545 lines**, ending cleanly on the final `ERR_PAYMENT_EXCEEDS_OUTSTANDING | 422` row of §5. No audit footer, no content after §5.

**Section list**
- §1 Introduction
- §2 Global Specifications: 2.1 RBAC (6 roles) · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Resource Identity, Audit Fields and Versioning · 2.5 The Logical Clock · 2.6 Monetary Units, Ratios and Rounding Discipline · 2.7 The Donor-Restricted Exclusion Doctrine · 2.8 Stale-Version Protection on Campaign and Loan Writes · 2.9 Hierarchical Reconciliation and the Two Loan State Dimensions · 2.10 Identifier Resolution and the Validation Ladder (ordered 1-52) · 2.11 The Commitment Conservation Invariant
- §3 Business Logic: 3.1 Onboarding and the Giving Record · 3.2 Authority to Borrow · 3.3 Capital Campaigns, Pledge Attrition and the Two Valuations · 3.4 Special-Purpose Collateral and Lien Occupation · 3.5 Underwriting: Snapshots, Coverage and the Sizing Caps · 3.6 The Committee Fork and Origination · 3.7 Construction Draws and the Disbursement Waterfall · 3.8 Covenant Surveillance, the Breach Cycle and Risk Posture · 3.9 Workout Options and the Mission Impact Score
- §4 Endpoint Definitions (4 columns, 60 rows)
- §5 Error Code Catalogue (2 columns, 52 rows)

**Verification counts (all mechanically grep/parse-checked against SCAFFOLD.yaml)**

| Declared | In PRD |
| --- | --- |
| 60 endpoints | 60 rows, method+path set exactly equal to declared; 0 missing, 0 extra |
| Roles per endpoint | 60/60 role sets match exactly (0 mismatches) |
| Status codes | the 11 resource-creation POSTs are the only 201s; §4 intro states exactly that rule |
| 52 error codes | 52 in §5 table; all 52 also appear in §1-§3 narrative (none table-only) |
| 52 validations | 52 numbered ladder items in §2.10, one per distinct `error_id` |
| 9 calculations | all 9 present (giving base, net-available dollars, DSCR covenant ratio, campaign projected value, collateral lending value, max supportable principal, draw net disbursement, mission impact score, risk posture) |
| 9 state machines / 51 transitions | 51/51 present as explicit `FROM -> TO` arrow pairs |
| 11 entities | all covered |

**Hard Contract reports**

- **Contract 1 — Field-Name Coverage: PASS.** All 161 identifier tokens harvested from `entities[].fields[].name`, `input`, `query_params` and `path_params` (including optional `?` variants, stripped) appear verbatim inside backticks in PRD.md. Checked with fenced code blocks excluded so the §2.2 JSON envelope can't create false positives; 0 missing.
- **Contract 2 — Rule Coverage: PASS.** Validation priority ordering carried as the explicit ordered 1-52 ladder in §2.10 with each rule's HTTP status and `applies_to` scope; both OCC rules (`expected_loan_version` / `ERR_STALE_LOAN_VERSION`, `expected_pledge_campaign_version` / `ERR_STALE_CAMPAIGN_VERSION`) given their own §2.8 with the reason a stale-basis write is refusable; all 51 transitions with preconditions, actors and side effects; cross-entity cascades stated in both directions (pledge lapse -> campaign buckets -> `OPEN -> UNDERPERFORMING` -> `PLEDGE_ADVANCE` applications to `REVISION_REQUESTED`, with the explicit non-rollback on recovery; `WATCH -> RESTRICTED` -> draw suspension with no auto-reinstatement; workout approval -> predecessor `SUPERSEDED` + loan ledger + `WORKOUT_GATED`); sibling-branch symmetry preserved (board-verification's two landing states on `requires_denominational_approval`; the committee's three arms at equal density; `BREACHED` self-transition on PASS vs FAIL; the four workout options' divergent ledger effects, including `MISSION_IMPACT_FORBEARANCE` moving nothing); field-level structured content spelled out (`lien_history` record keys, the 3-bucket waterfall, `binding_cap` tie order, the four mission-impact component fields).
- **Contract 3 — §3 Path Purity: PASS.** Every backticked token in §3 was extracted programmatically; 0 begin with `/`, 0 are a bare HTTP method, 0 are a method+path pair. §3 refers to operations only by state-transition pair, role+action verb, or capability description.

**Constraints observed:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced; no sibling task directory was read; `worklog.md` was not touched; PRD.md was built by ~30 chunked `cat >>` appends, never a single large Write.

One judgement call worth flagging: SKILL.md's §2.3 boilerplate says list sort order is `created_at` ascending, but the scaffold declares per-endpoint orderings. The generator stated `created_at` ascending as the default and then explicitly enumerated the five `created_at`-DESC collections plus the giving-period two-key order (`period_end` DESC, `created_at` ASC tiebreak) — scaffold fidelity wins over the boilerplate.

**Orchestrator truncation check (per the known doc-generator failure mode):** independently verified — `wc -l` = 545; `grep '^## '` shows all five top-level sections present in order; `tail -12` shows a complete, well-formed final table row. PRD is NOT truncated. Also re-checked the difficulty directive did not leak: `grep -ci expert PRD.md` = 0, `grep -c "harder than" PRD.md` = 0.

## Step 6: Generate implementation — 2026-09-04T20:20:00.000Z

Implementation complete and serving.

## Modules (all under `workspace/implementation/`)

| file | lines |
|---|---|
`app.py` | 70 |
`store.py` | 172 |
`errors.py` | 120 |
`envelope.py` | 96 |
`auth.py` | 103 |
`shapes.py` | 143 |
`calc.py` | 562 |
`serializers.py` | 65 |
`resolve.py` | 54 |
`routes/institutions.py` | 181 |
`routes/governance.py` | 160 |
`routes/campaigns.py` | 261 |
`routes/collateral.py` | 164 |
`routes/applications.py` | 251 |
`routes/loans.py` | 143 |
`routes/draws.py` | 223 |
`routes/covenants.py` | 173 |
`routes/workouts.py` | 178 |
`routes/__init__.py` | 0 |

Total 3119 lines of Python, plus `start.sh` (chmod +x, guarded pip install, `exec python3 app.py`, reads `$PORT`, binds `0.0.0.0`, foreground) and `requirements.txt` (`Flask>=2.2.0`). `python3 -m py_compile` clean on every module; `__pycache__` removed.

## Coverage

- **Endpoints: 60/60.** Diffed the live `app.url_map` against the 60 rows of the PRD §4 table (normalising path params) — exact match, no extras, no omissions.
- **Errors: 52/52.** `errors.py` carries all 52 error ids with PRD §5 statuses, and a scan confirms every one of the 52 is actually raised somewhere in the code (no dead entries, none unreachable).
- **Validation ladder:** all 52 rungs of §2.10 implemented in ladder order, not narrative order, wherever §3 disagrees (collateral assignment 34->35->37->39->40; committee decision 19->31->33->48; draw actions 20->21->45/49/50). Transitively-owned resources resolve before the rung-3 scope check because the owner is not knowable until then.
- **Calculations/state machines:** all 9 calculations (giving base with AUDITED_ONLY/BLENDED + 15% internal haircut, net available dollars with per-period pinned rounding, DSCR, both campaign valuations, collateral lending value, max supportable principal with `binding_cap`, draw waterfall with retainage tiers + 45000c inspection fee, mission impact score, derived risk posture) and all 9 state machines, with version-bump-at-most-once-per-request enforced via a `flask.g` touched-id set.

## Smoke boot

Booted `PORT=18760 ./start.sh` and drove a 60-call end-to-end scenario: institution -> 4 audited giving periods (institution reads recompute `period_count`/`unrestricted_giving_base_cents` 720000000 / `net_available_for_debt_service_dollars` 3200000 / `membership_trend_pct` 0.1579 against the logical clock) -> governance packet through submit/board-verification (quorum 0.75)/denominational APPROVE -> AUTHORIZED -> collateral (lending value 260000000, `appraisal_age_days` 92) -> application -> assignment -> underwriting -> referral -> summary (`binding_cap: AUTHORIZED_AMOUNT`) -> APPROVE -> loan -> draw approve/disburse (retainage 2000000, fee 45000, net 17955000, loan -> CONSTRUCTION_DRAW) -> covenants incl. a full COMPLIANT->BREACH_PENDING_CURE->BREACHED->WAIVED cycle with posture deriving WATCH -> RESTRICTED (suspending the approved draw, `reserved_draw_cents` -> 0) -> workout TERM_EXTENSION (score 100.00, term 180->240, ADS 900000->675000 floored, posture WORKOUT_GATED) -> superseding PARTIAL_FORGIVENESS (institution `cumulative_forgiveness_cents` 1000000) -> campaign/pledge/installment/valuation/close -> clock set -> negative checks (401/403/404/405/409/412/422 all in the error envelope). Every response carried a well-formed envelope with `req_`+20-char ids, 3-digit-millisecond timestamps and full pagination meta.

Zero real failures. The one flagged mismatch was the generator's own test expectation: `POST /collateral-assets/{id}/assignments` returns 200, which PRD §4 confirms is correct (only the 11 resource-creation endpoints return 201, and all 11 did).

The smoke server was killed by looking up the single PID listening on port 18760 (`kill 3411427`); port confirmed free afterwards, no broad `pkill` was ever run, and no stray process remains. Did not touch `worklog.md`, and did not read `test_suite/`, `test_helpers/`, either `SCAFFOLD_*_DESIGN.yaml`, or any sibling task directory.

## Step 5: Generate unit tests — 2026-09-04T21:16:38.000Z

The suite is complete and fully verified.

## Output files

Both trees are at the task root — nothing under `workspace/` (which still holds only `INSTRUCTION.md`, `PRD.md`, `implementation`), `workspace/implementation/` never accessed, no sibling task read, `worklog.md` untouched.

`test_helpers/` — 2324 lines
| file | lines |
|---|---|
| `__init__.py` | 113 |
| `api_client.py` | 356 |
| `api_errors.py` | 132 |
| `assertions.py` | 228 |
| `constants.py` | 170 |
| `factories.py` | 431 |
| `fixtures.py` | 556 |
| `test_users.py` | 92 |
| `types.py` | 246 |

`test_suite/` — 6624 lines, 102 tests
| file | lines | tests |
|---|---|---|
| `conftest.py` | 25 | — |
| `test_01_dual_variant_calc.py` | 203 | 4 |
| `test_02_combinatorial_formula.py` | 350 | 6 |
| `test_03_non_linear_state_machine.py` | 344 | 6 |
| `test_04_transitive_cascade.py` | 313 | 6 |
| `test_05_priority_pair_validation.py` | 277 | 4 |
| `test_06_boundary_precision.py` | 234 | 4 |
| `test_07_cross_entity_state_dependency.py` | 325 | 4 |
| `test_08_resource_temporal_overlap.py` | 283 | 4 |
| `test_09_compensating_invariant.py` | 291 | 4 |
| `test_10_corner_entities.py` | 705 | 14 |
| `test_11_corner_state_machines.py` | 843 | 15 |
| `test_12_corner_calculations.py` | 311 | 5 |
| `test_13_corner_validations.py` | 1050 | 12 |
| `test_14_corner_endpoints.py` | 420 | 4 |
| `test_15_corner_rbac.py` | 361 | 5 |
| `test_16_corner_cross_cutting.py` | 311 | 3 |
| `test_17_corner_consistency.py` | 183 | 2 |

## Test counts per queue

- Queue A (§1.8 difficulty): **42 tests** covering **19/19** instances (0 stubs in §1.8), every instance with >=2 tests.
- Queue B (§1.9 corner): **60 tests** covering **60/60** non-stub instances, each with >=1 test. The 21 `excluded_because:` stubs were correctly not translated.

## Skipped instances

**None.** Every live instance in both indices passed the two-condition PRD-first filter (verbatim PRD coverage + PRD uniquely derives the asserted outcome), so all 79 were translated. No `skip`/`xfail`/placeholder markers exist anywhere in the suite.

## Coverage-audit notes

1. **`SCHOOL_EXPANSION` is not a PRD purpose** (setup-only defect). Two §1.9 instances (`SCAFFOLD_CORNER_DESIGN.yaml` lines 1880 and 2252) build a loan application with `purpose: "SCHOOL_EXPANSION"`, which is absent from the PRD §3.5 enum (`SANCTUARY_CONSTRUCTION`, `SCHOOL_CONSTRUCTION`, `REFINANCE`, `PLEDGE_ADVANCE`). Substituted `SCHOOL_CONSTRUCTION`; neither instance's asserted outcome depends on the purpose value, so the intent is preserved.
2. **`shared_operations_work_for_every_role_that_declares_them` contradicts PRD §2.3** (assertion defect). Its final bullet expects `GET /collateral-assets` to return "newest first: [asset_s, asset_p]", but §2.3 makes `created_at` ascending the default and names only five collections that invert it (institutions, governance authorizations, pledge campaigns, loan applications, loans) — collateral assets are not among them. The instance is translated in `test_15_corner_rbac.py` with the PRD-derived ascending order `[parsonage, sanctuary]` asserted instead, flagged by an inline comment and both §2.3 ordering sentences quoted.
3. **Timestamp discipline** is centralised: `api_client.canonical_iso` normalises any instant to `...SS.mmmZ` and `assertions.assert_iso_equal` compares through it, so no test compares timestamp strings byte-for-byte. `assert_three_fractional_digits` is the only width assertion and is used solely where PRD §2.4 states the width as a rule.
4. **Design-index-only contract holds**: audit reports 102 tagged tests (42 queue A / 60 queue B), 0 untagged, 0 dual-tagged, 0 dangling tags, 0 stub tags. A docstring scan reports 0 scaffold leaks and 0 tests without a PRD citation; every `PRD §x.y: "..."` quote verified as a whitespace-normalised substring of `workspace/PRD.md` — 0 issues.
5. **Static health**: `python3 -m py_compile` clean on all 27 files; `pyflakes` clean except the nine intentional fixture re-export warnings in `conftest.py`. `__pycache__` removed.

**Orchestrator placement check (per the known Step 5 failure mode of writing test dirs under workspace/):** verified `find workspace -type d -name 'test_*'` returns nothing and both `test_helpers/` and `test_suite/` sit at the task root. 18 files in test_suite/, 102 collected test functions. No move was necessary.

## Step 7: Run tests and iterate — 2026-09-04T21:37:47.000Z

All 8 parallel rounds passed 102/102. Clean sweep.

## Summary

**Iterations run:** 2 (each a full 8-round parallel sweep under `setsid nohup`).

- Iteration 1: 100/102 in all 8 rounds — the same 2 tests failed deterministically in every round (no flakiness anywhere else).
- Iteration 2 (after fixes): 102/102 in all 8 rounds.

**Tests deleted:** none. Both failures cleared STEP 1 (PRD verbatim-covers and uniquely determines the asserted rules) and were resolved as STEP 2 test bugs.

**Fixes applied to `test_helpers/`:** none — no fixture, factory, or role-header helper was at fault.

**Fixes applied to `implementation/`:** none — no implementation defect was found. Notably `routes/collateral.py::assign_asset` already evaluates the ladder in the PRD's mandated order (34 -> 35 -> 37 -> 39 -> 40).

**Fixes applied to `test_suite/`** (both in `test_suite/test_13_corner_validations.py`):

1. `test_five_different_shape_violations_all_answer_with_the_one_schema_error` — the test did `body = validate_error(...)` then `assert body["response_type"] == "error"`, raising `KeyError: 'response_type'`. The framework's `validate_error` returns the envelope's inner `data` object (only `error_id` / `message`), not the envelope. Changed the envelope check to read the raw response (`response.json()["response_type"]`), preserving the PRD §2.2 assertion the test intended rather than dropping it.

2. `test_one_rule_answers_both_a_double_assignment_and_a_double_release` — the test asserted `ERR_COLLATERAL_ALREADY_ASSIGNED` but its request also violated the lien-release-buffer rule: the proposed window `2026-09-01 -> 2030-09-01` overlaps the live occupation `2026-08-01 -> 2031-08-01` extended by the 30-day buffer. PRD §2.10 puts the lien-window conflict at position 37 and already-assigned at position 40, so `ERR_COLLATERAL_LIEN_WINDOW_CONFLICT` is the correct single answer and the implementation was right. Moved the proposed window to `2031-09-01 -> 2035-09-01`, which clears position 37 (prior end 2031-08-01 + 30d = 2031-08-31) so position 40 becomes the first rule violated — keeping the assertion at the exact `error_id` the test was written to prove.

**Orchestrator verification (per the known failure mode of a subagent claiming a clean sweep with no artifacts):** independently read all 8 `results.$i.json` files from the final sweep — every one reports `passed=102, total=102`. Artifacts are present on disk, not merely claimed.

**Step 8 gating decision:** the skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes. Step 7 applied 2 `test_suite/` fixes over 2 iterations, so the condition is not met and Step 8 runs. Note in advance that both fixes were pure test bugs (a helper return-shape misuse and a fixture window that tripped an earlier ladder rung), neither of which reveals a PRD silence — so a byte-identical or near-identical `PRD_FINALIZED.md` is a legitimate outcome here, and the orchestrator will not treat that as a Step 8 failure.

## Step 8: Finalize PRD — 2026-09-04T21:45:15.000Z

**Result: no edit warranted. `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md`.**

- `workspace/PRD.md`: 545 lines; `workspace/PRD_FINALIZED.md`: 545 lines; **0.0% delta** (md5 identical: `7b0837f7...`).
- Change bullets: none.

Both `<step_7_diff>` items were adjudicated as test bugs with zero `implementation/` and zero `test_helpers/` fixes, and the subagent confirmed independently that the PRD already verbatim-pins the behavior each test was probing.

Candidate-subject analysis (mandatory pre-edit search, run for both items even though neither produced an edit):

**Item 1 — subject: the 4xx error envelope shape (`response_type`, `data.error_id`, `data.message`).**
- Paths enumerated / read: `implementation/envelope.py` (`_meta` lines 14-18; `error_response` lines 30-36 — the single construction site for every error body), `implementation/errors.py` (`ApiError`, `ERROR_STATUS`, `DEFAULT_MESSAGES` — the only sources of `error_id`/`message`/status), plus grep for other error emitters: `error_response` is the sole error envelope builder and `envelope.ok`/`created` are the only success builders, so no parallel endpoint emits a different shape. Also checked `envelope._int_param` (pagination) raises the same `ApiError`, so query-param failures use the identical envelope.
- Finding: `envelope.error_response` emits exactly `{"meta": {api_request_id, api_request_timestamp}, "response_type": "error", "data": {"error_id", "message"}}`, which is character-for-character what PRD §2.2 "Standard Error Response Format" already mandates (including the note that error `meta` carries only the two fields). The failure was the framework helper `validate_error` returning the inner `data` object while the test read `body["response_type"]` from it — a test-harness misuse, no PRD silence.
- Wording adjustment: none (no edit).

**Item 2 — subject: the collateral-assignment validation ladder order and the 30-day lien release buffer overlap predicate.**
- Paths enumerated / read: `implementation/routes/collateral.py` — `assign_asset` lines 94-133 (ladder 34 -> 35 -> 37 -> 39 -> 40, in that literal order, with the shape checks at lines 103-107 running first), `_prior_occupations` lines 79-91 (priors = every `lien_history` entry **plus** the live occupation when `assigned_loan_application_id` is set), `release_occupation` lines 136-151 and `release_asset` lines 154-164 (the other writer of `lien_history` / the current-occupation fields, i.e. the producer of the priors that position 37 consumes), `create_asset` lines 21-56 (initial nulls + empty `lien_history`), and `calc.revalue_asset` / `calc.APPRAISAL_STALE_DAYS` / `calc.LIEN_RELEASE_BUFFER_DAYS` / `store.plus_days` as the constants and helper behind positions 35 and 37.
- Finding: the impl predicate is `from_dt < prior_to + 30d and prior_from < to_dt`, evaluated against current-assignment-plus-history priors — exactly PRD §3.4's "refused ... whenever the new window's start falls strictly before that extended end **and** the prior occupation's start falls strictly before the new window's end", with "each prior occupation of the same asset — the current assignment if any, and every entry already recorded in `lien_history`". Ladder positions 37 (lien-window conflict) before 40 (already-assigned) are pinned in §2.10. The original test's window `2026-09-01 -> 2030-09-01` genuinely tripped position 37 first, so the implementation's answer was the PRD-correct one; moving the window to `2031-09-01 -> 2035-09-01` restored the intended position-40 probe. No PRD silence or mismatch.
- Wording adjustment: none (no edit). Note for the record: any tightening here — e.g. narrowing position 37 to "released" priors — would have contradicted `_prior_occupations` including the live occupation, which is precisely the mismatch the NO-NEW-MISMATCH rule guards against; the existing prose is already consistent with all enumerated paths.

**Orchestrator note:** a byte-identical `PRD_FINALIZED.md` is a legitimate Step 8 outcome when Step 7 made no implementation fixes, and is accepted here. Step 9, by contrast, performs a full impl-vs-PRD scan and must NOT come out identical; the orchestrator will verify that and will run Step 9 as three sequential module-partitioned passes over one shared `PRD_COMPLETED.md` (pass 1 does the `cp`, later passes must not) to avoid the single-pass output cap.

## Step 9: Complete PRD — 2026-09-04T22:10:00.000Z

Run as **three sequential module-partitioned passes** over one shared `PRD_COMPLETED.md` (pass 1 did the `cp`, passes 2 and 3 edited additively in place). Sequential, never concurrent — all three write the same file. Final state: **546 lines / 123,386 chars**, md5 `a95eaaa74a7c45a0195f303fc5302254`, from a 545-line / 106,749-char source. **73 edits total: 54 ambiguity-pins, 19 mismatch-revisions.**

### Pass 1 — infra + institutions + governance (21 edits: 17 ambiguity, 4 mismatch)
Modules: `app.py`, `store.py`, `envelope.py`, `errors.py`, `auth.py`, `shapes.py`, `resolve.py`, `serializers.py`, `routes/institutions.py`, `routes/governance.py`. Result 546 lines / 112,222 chars, md5 `421b175f77a6acc70eb0e9113daf32f1`.

- §2.1 — insert — ambiguity — empty/whitespace `X-User-ID` is an authentication failure; role comparison exact and case-sensitive — auth.py:44
- §2.1 — revise — mismatch — the scope check binds only endpoints addressing one identified resource; list endpoints do no ownership check or filtering — auth.py:51, routes/institutions.py:160, routes/governance.py:257
- §2.2 — insert — ambiguity — `api_request_id` is `req_` plus exactly twenty uppercase-alphanumeric characters — store.py:108
- §2.2 — insert — ambiguity — new bullet: unrouted path -> `ERR_NOT_FOUND` (404), undeclared method -> `ERR_METHOD_NOT_ALLOWED` (405), both outside the §5 catalogue; trailing slashes accepted — app.py:22,41
- §2.3 — insert — ambiguity — omitted/empty `limit`/`offset` take defaults; non-integer, `limit` outside 1-100, or negative `offset` -> `ERR_INVALID_REQUEST` — envelope.py:39
- §2.3 — insert — ambiguity — filters are exact string equality; empty-string filter treated as absent; undeclared query params ignored — envelope.py:80
- §2.4 — insert — ambiguity — audit timestamps and `api_request_timestamp` come from real server time, never the logical clock — store.py:113, envelope.py:14
- §2.5 — insert — ambiguity — clock set answers 200 with only `current_utc` at three fractional digits, and accepts instants before or after the current value — routes/institutions.py:175
- §2.5 — insert — ambiguity — zone-less client instants read as UTC, offsets normalised, unparseable -> `ERR_INVALID_REQUEST`, persisted instants echoed verbatim — store.py:74, routes/institutions.py:128
- §2.9 — revise — mismatch — a giving-period filing rewrites five computed institution figures (not four), naming them — routes/institutions.py:145
- §2.10 — insert — mismatch — pinned interleaving of scope (rung 3) with resolution: institution-named-directly cases scope first, transitively-owned rows resolve first (so a bad id yields its own 404 to a foreign representative); absent/null/non-string FK yields no 404 and falls to rung 15 — routes/institutions.py:65 vs 153, store.py:159
- §2.10 item 15 — insert — ambiguity — four shape conventions: unparseable/absent body = empty object, non-object body rejected, `null` == omitted, required strings need non-whitespace while optional strings accept `""`, integers reject booleans/fractions, ratios round half up to 4 places on ingest — shapes.py:17,30,48,112
- §3.1 — insert — ambiguity — `membership_trend_pct` opens null at onboarding — routes/institutions.py:54
- §3.1 — insert — ambiguity — the midnight convention on `period_start`/`period_end` is not enforced — routes/institutions.py:96
- §3.1 — insert — ambiguity — all five institution figures are recomputed on every read as at the current logical instant, without a write and without advancing `version` — serializers.py:22
- §3.2 — insert — ambiguity — packet also opens with `minutes_reference` and `rework_note` null; no cross-validation of `resolution_date` vs `expires_on` vs the clock at creation — routes/governance.py:235
- §3.2 — insert — ambiguity — submission does not examine the board tally; quorum belongs to verification alone — routes/governance.py:272
- §3.2 — insert — ambiguity — verification stores the supplied `minutes_reference` — routes/governance.py:299
- §3.2 — insert — ambiguity — `denominational_decision_note` left null when the caller omits `note` — routes/governance.py:314
- §3.2 — insert — ambiguity — return-to-draft retains `board_quorum_pct` and `minutes_reference` and stores the note as `rework_note` — routes/governance.py:336
- §4 table — revise — mismatch — `/submit` row said it enforces "the quorum and bylaws-cap gates"; it enforces only the bylaws cap — routes/governance.py:272

§5 required no change — all error ids and statuses in errors.py match the table exactly.

### Pass 2 — calc + campaigns + collateral + applications (31 edits: 23 ambiguity, 8 mismatch)
Modules: `calc.py`, `routes/campaigns.py`, `routes/collateral.py`, `routes/applications.py`. Result 546 lines / 118,379 chars, md5 `19910a7461d301b70af6d06187bb7496`. Pass 1's 21 edits verified intact by diff against PRD_FINALIZED.md.

- §2.6 — revise — mismatch — `completion_pct_at_disbursement` removed from the round-half-up-4 list; it is floored to four places — calc.py:437
- §3.1 (window) — insert — ambiguity — residual tie beyond `period_end`+`created_at` broken by insertion order — calc.py:132
- §3.1 (giving base) — revise — mismatch — base/net are 0 when the window holds <4 (short history, as-of cutoff, or <4 audited under `AUDITED_ONLY`), not merely when <4 are on file — calc.py:166,179
- §3.1 (`membership_trend_pct`) — insert — ambiguity — null when window <4 or oldest `member_household_count` is 0 — calc.py:198,203
- §3.3 (campaign open) — insert — ambiguity — `close_note` opens null — campaigns.py:52
- §3.3 (pledge open) — insert — ambiguity — `reinstatement_note` opens null — campaigns.py:155
- §3.3 (installments) — insert — ambiguity — `installment_month` mandatory, integer or string, unconstrained, never persisted (no installment resource) — campaigns.py:189-193
- §3.3 (manual lapse) — insert — ambiguity — `lapse_reason` mandatory non-empty — campaigns.py:231
- §3.3 (reinstate) — insert — ambiguity — `reinstatement_note` mandatory non-empty, stored on the pledge — campaigns.py:248,256
- §3.3 (close) — insert — ambiguity — `close_note` stored/null; close recomputes nothing and cascades to nothing — campaigns.py:83-88
- §3.3 (valuation read) — revise — mismatch — returns one valuation under the chosen basis, not both side by side — campaigns.py:106
- §3.3 (valuation read) — insert — ambiguity — empty `basis` takes the default; any other value -> `ERR_INVALID_REQUEST` — campaigns.py:98-102
- §3.3 (valuation read) — insert — ambiguity — buckets recomputed from pledges at read time, not read from stored fields — campaigns.py:103
- §3.4 (registration) — insert — ambiguity — `release_note` opens null; `appraisal_age_days` derived per read (clock-sensitive, no version bump) while `lending_value_cents` is stored and rewritten only at registration/assignment/release; future `appraisal_date` gives a negative age — collateral.py:45(serializers),51-53
- §3.4 (assignment) — insert — ambiguity — `lien_effective_to` must be strictly after `_from`; `lien_position` >=1 with no upper bound (>=3 takes the zero factor); target application's `status` never examined — collateral.py:103-107, calc.py:358-362
- §3.4 (release buffer) — revise — mismatch — buffer is ladder position 37, evaluated before institution-mismatch and already-assigned — collateral.py:113-125
- §3.4 (release) — insert — ambiguity — `release_note` mandatory non-empty and stored (overwriting); `released_at` comes from the logical clock at 3 fractional digits — collateral.py:144,159-162
- §3.5 (submit-underwriting) — insert — ambiguity — `analyst_note` validated but never persisted — applications.py:111
- §3.5 (referral) — insert — ambiguity — `referral_note` validated but never persisted — applications.py:146
- §3.5 (snapshots) — insert — ambiguity — re-submission does not touch `collateral_lending_value_cents`/`max_supportable_principal_cents` — applications.py:128-135
- §3.5 (fifth cap) — insert — ambiguity — no campaign named => `PLEDGE_ADVANCE_LTV` cap omitted, minimum over the other four — calc.py:412
- §3.5 (summary read) — insert — ambiguity — invalid `giving_basis` -> 422, empty = default; `window_period_labels` may hold fewer than four; trend may be null — applications.py:226-246
- §3.5 (summary read) — insert — mismatch — summary's `max_supportable_principal_cents` uses the recomputed net-available figure, not the snapshot the referral gate uses — applications.py:235-236
- §3.6 (committee gates) — insert — mismatch — evaluated in ladder order: expiry (31) answers before segregation (33) — applications.py:184-190
- §3.6 (approve arm) — insert — ambiguity — the submitted `note` is discarded; `revision_reason` untouched — applications.py:204
- §3.6 (decline arm) — insert — ambiguity — every assigned asset released whatever its lien position; asset `release_note` left untouched — applications.py:208-209, collateral.py:139
- §3.6 (decline/revision) — insert — ambiguity — `revision_reason` written null where the note is omitted — applications.py:207,212
- §3.9 (score window) — insert — ambiguity — fewer than four qualifying periods still scores; newest/oldest are first/last of the shorter list (one period => zero trends) — calc.py:487-496
- §3.9 (trend points) — insert — ambiguity — boundaries inclusive and compared by exact integer arithmetic; zero denominator => 100; empty window => both trends 100 — calc.py:472-499
- §4 table (`/close`) — revise — mismatch — dropped the false "cascading to dependent pledge-advance applications" claim — campaigns.py:77-89
- §4 table (`/valuation`) — revise — mismatch — no "collection rate", one basis not both — campaigns.py:92-116

### Pass 3 — loans + draws + covenants + workouts (21 edits: 14 ambiguity, 7 mismatch)
Modules: `routes/loans.py`, `routes/draws.py`, `routes/covenants.py`, `routes/workouts.py` (calc.py read-only for the waterfall, `free_commitment`, `derive_posture`/`recompute_posture`/`suspend_approved_draws`, `mission_score`). Result 546 lines / 123,386 chars, md5 `a95eaaa74a7c45a0195f303fc5302254`.

- §3.6 — insert — ambiguity — origination also opens `final_inspection_passed` and `completion_note` as null — loans.py:65-66
- §4 (`GET /loans`) — revise — mismatch — table claimed an institution filter; impl filters `loan_application_id`/`servicing_status`/`risk_posture` and a loan carries no `institution_id` — loans.py:87-89
- §4 (`.../approve`) — revise — mismatch — retainage is not computed at approval, only the reservation is taken — draws.py:104-107
- §4 (`.../void`) — revise — mismatch — void acts on a `DISBURSED` draw and reverses the disbursement; it does not release a reservation — draws.py:181-190
- §4 (`.../reinstate`) — revise — mismatch — gate is posture `OPEN`/`WATCH`, not "breach resolved" (a `WATCH` loan still has an open soft breach) — draws.py:211
- §3.7 — insert — ambiguity — `project_phase`/`percent_complete` are recorded only; no gate or waterfall figure reads them — draws.py:31-33,52
- §3.7 — insert — ambiguity — new draw also opens `disbursement_date`/`reinstatement_note` null; posture and covenants are not examined at creation — draws.py:47-57
- §3.7 — revise — ambiguity — `approved_amount_cents` may be zero, never negative; above `requested_amount_cents` is `ERR_INVALID_REQUEST` at position 15, ahead of the 20/21 tests — draws.py:88-92
- §3.7 — insert — ambiguity — `disbursement_date` stored verbatim in the field of that name, null when omitted — draws.py:118,140
- §3.7 — insert — ambiguity — the suspension sweep fires on the transition into `RESTRICTED`, so a draw approved while the loan already sits `RESTRICTED` stays `APPROVED` — calc.py:547-558
- §3.7 — revise — ambiguity — a reinstatement blocked by posture answers `ERR_DRAW_INVALID_STATE` (same position-21 test) — draws.py:211-212
- §3.7 — insert — ambiguity — `completion_note` stored (null when omitted) and `final_inspection_passed` retained true — loans.py:122,140-141
- §3.7 — insert — ambiguity — a second completion (loan `AMORTIZING`) answers `ERR_LOAN_NOT_IN_DRAW_PHASE`, and on this act that test runs after positions 21 and 27, not at position 20 — loans.py:126-133
- §3.7 — revise — ambiguity — payment `amount_cents` may be zero; `payment_date` is mandatory, validated, persisted nowhere — loans.py:98-99
- §3.8 — insert — ambiguity — `waiver_note` is absent from the covenant representation until a waiver writes it (not a null field) — covenants.py:39-54,170
- §3.8 — revise — mismatch — the tested ratio is identical for all three `covenant_type` values; the type selects no formula — covenants.py:94-100
- §3.8 — insert — ambiguity — a denominator rounding to 0 dollars yields `last_test_ratio` 0.0000 with no division attempted — covenants.py:96-99
- §3.8 — revise — ambiguity — waiver note is mandatory/non-empty and retained; `consecutive_fail_count` is left as the breach left it — covenants.py:164-170
- §3.8 — revise — mismatch — posture re-derivation is skipped outright on a `PAID_OFF` loan (cure/waiver still move the covenant) — calc.py:547-550
- §3.9 — revise — mismatch — non-applicable option fields are ignored, not forbidden; recorded null whatever the caller sent — workouts.py:48-59
- §3.9 — insert — ambiguity — proposal sets `proposed_by_user_id`, retains `narrative`/`denominational_support_letter`, opens `approval_note` null — workouts.py:90-93
- §3.9 — insert — ambiguity — `approval_note` stored where supplied, null where omitted; a `PAID_OFF` loan bars neither proposal nor approval — workouts.py:127,130,144-145
- §3.9 — revise — mismatch — a `PARTIAL_FORGIVENESS` approval also advances the institution's `version` by 1 — workouts.py:164-167

### Orchestrator verification
- `PRD_COMPLETED.md` is **NOT** identical to its source: md5 `a95eaaa74a7c45a0195f303fc5302254` vs `7b0837f75521ce52d935e5bb19295146`, 131 changed lines in `diff`, +16,637 chars. The known failure mode where the scan silently never ran did not occur.
- Not truncated: all five top-level sections present in order (§1 L3, §2 L11, §3 L209, §4 L422, §5 L489) and the file ends on the complete final error-table row `| ERR_PAYMENT_EXCEEDS_OUTSTANDING | 422 |`.
- Only Pass 1 performed the `cp`; passes 2 and 3 edited additively and each confirmed the prior passes' hallmark edits still byte-intact.
- Final Step 7 sweep artifacts remain on disk: 8 × `implementation/results.$i.json`, every one `passed=102, total=102`.

**Pipeline complete.** Step 9 has written `workspace/PRD_COMPLETED.md`.
