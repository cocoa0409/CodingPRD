# Worklog — task_1991_employee_engagement_survey_action_planning

Scenario: 1991. Employee Engagement Survey & Action Planning (HR people analytics team). Difficulty calibration: harder than expert level (user request).

## Step 2: Generate Scaffold — 2026-08-15T06:01:43.661Z

All checks pass. The scaffold is complete.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1991_employee_engagement_survey_action_planning/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Counts:**
- Entities: 14 (ItemBank, SurveyItem, OrgUnit, Employee, SurveyCycle, CycleItem, SurveyInvite, SurveyResponse, ReportSnapshot, BenchmarkSet, ActionPlan, ActionItem, OutcomeLinkage, ReminderEvent)
- Endpoints: 60 (incl. test-driving `POST /engagement/_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` startup default)
- Errors: 21
- State machines: 6 — BenchmarkSet (2-state linear), ItemBank (linear with retire cascade), SurveyCycle (7-state pipeline with guarded transitions), SurveyInvite (self-loop REMINDED→REMINDED with cap + PARTIAL↔SUBMITTED), ActionPlan (cyclic revision loop DRAFT→SUBMITTED→REJECTED→DRAFT plus auto-complete), ActionItem (linear with parent bubble-up)
- Calculations: 7 (engagement_score with census/pulse variants, response_rate with half-weight partials, eligibility_sampling with tenure gate + floor, minimum_n_suppression with two independent thresholds, benchmark_percentile with tie-halving, action_progress with dropped-in-denominator, attrition_risk_index with provisional/final variants)
- Validations: 19 ordered rows; concurrency rules: 2 OCC rules (cycle configure, plan submit); roles: 5 (segregation-of-duties model; UnitManager entity_backed by OrgUnit, EmployeeRole entity_backed by Employee)
- §1.8 difficulty instances: 18 (2 per rule × 9 rules), all with literal-pinned arithmetic verified by executing the formulas (72.22 vs 75.00 census/pulse divergence, 57.14 vs 55.56 rounding-order trap, 0.2200 vs 0.5500 risk variants, 70.00 percentile, 0.8750→1.0000 rate transitions)
- §1.9 corner instances: 35 (31 active + 4 excluded-because stubs) across all nine taxonomy sections

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (929 calls scanned)

Key design decisions per the harder-than-expert calibration: confidentiality suppression with two decoupled integer thresholds (min_n inclusive-lower boundary vs verbatim_n), segregation-of-duties between cycle creator and scorer, half-open submission window `[opens_at, closes_at)`, single-OPEN-cycle capacity invariant, bulk reminder sweep with skip-not-error cap semantics, and OCC resolved via sequential version-capture chains (no forbidden race vocabulary anywhere).

## Step 3: Copy INSTRUCTION.md — 2026-08-15T06:02:10.352Z

Copied ./INSTRUCTION.md to tasks/task_1991_employee_engagement_survey_action_planning/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-08-15T06:16:23.630Z

PRD generation complete. Summary:

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1991_employee_engagement_survey_action_planning/workspace/PRD.md` — 297 lines.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC (all 5 roles with identity translations), 2.2 API Response Structure (byte-identical verbatim block, verified), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Logical Clock & Survey Windows, 2.6 Confidentiality & Minimum-N Suppression, 2.7 Segregation of Duties, 2.8 Validation Order & Rule Precedence, 2.9 Nested Resource Retrieval, 2.10 Hierarchical Consistency & Cascading Mutation, 2.11 Scoring Precision & Rounding, 2.12 Optimistic Concurrency Control
- §3 Business Logic (8 subsections, chronological process grouping): instrument/item banks, roster, cycle composition & opening, field period (invites/reminders/submissions), close/scoring/reporting, benchmarks, action plans & milestones, outcome linkage & attrition risk
- §4 Endpoint Definitions (4-column table, 60/60 endpoints, paths verified against scaffold with zero mismatch)
- §5 Error Code Catalogue (2-column table, all 21 errors)

**Coverage audit (all three hard contracts PASS):**
- **Contract 1 (field names):** 71 required identifiers (62 entity fields + 46 endpoint inputs, deduped, plus `id`/`created_at`/`updated_at`/`version`) — 0 missing. One gap found during audit (`status` field never backticked) and repaired in §2.4.
- **Contract 2 (rules):** all 27 state-machine transitions with preconditions/side effects (including the `CLOSED → SCORING` version increment, caught and fixed in review), all 7 calculations with constants and variants (census/pulse weighting, provisional 0.08 vs final attrition risk, strict-`<` suppression boundary, pulse floor + `hired_at`/`created_at` tie-break ordering, dropped-items-in-denominator progress), both OCC rules with `expected_cycle_version`/`expected_plan_version` + `ERR_STALE_VERSION`/412, full 16-entry validation priority ordering in §2.8, all 21 error IDs surfaced in §2/§3 prose, all 21 state strings and all enum values present verbatim. Sibling transitions (INVITED vs REMINDED submit paths, DRAFT vs IN_PROGRESS abandon, DIRECT vs SUBTREE scope) rendered with equal density.
- **Contract 3 (§3 path purity):** 337 backticked tokens in §3 scanned — 0 paths, 0 bare HTTP methods, 0 method+path combos. All §3 endpoint references use state-pair framing, role+verb, or capability descriptions.

No scaffold content was omitted; nothing invented beyond prose connective tissue. The two withheld design files were not opened; no sibling tasks were read.

## Step 5: Generate Unit Tests — 2026-08-15T06:50:02.572Z

Generation complete and verified. Summary:

## Files written

**test_helpers/** (9 files, under `/home/ubuntu/github/CodingPRD/tasks/task_1991_employee_engagement_survey_action_planning/test_helpers/`): `types.py` (enums + TypedDicts, common_fields branching honored — SurveyResponse/OutcomeLinkage/ReminderEvent omit `updated_at`/`version`), `api_client.py` (45 endpoint methods covering every PRD §4 route), `api_errors.py` (21 error IDs + status map registered with the framework), `assertions.py`, `factories.py`, `constants.py` (thresholds from §2.5–§3.8: TENURE_GATE_DAYS=30, REMINDER_CAP=3, BASE_RATE_PRIOR=0.08, RISK_COEFF=1.75, LOW_SCORE_FLOOR=60.00, …), `test_users.py` (shared constants for opaque roles + mandatory `make_unit_manager_headers`/`make_employee_headers` builders for entity-backed roles), `fixtures.py` (composite lifecycle: active bank → roster → clock → cycle → pin → OCC configure → open → submits/partials → close → score → publish → archive, plus plan tier through IN_PROGRESS), `__init__.py` barrel.

**test_suite/** (11 files): `conftest.py` + `test_01`…`test_10` (instrument, roster, cycle config/OCC, invites/submissions, reminders, scoring/reporting, action plans, outcomes/benchmarks, access control, listing envelope).

## Test counts per design queue
- **Queue A (Difficulty): 36 tests — 18/18 instances at ≥2 tests each.**
- **Queue B (Corner): 28 tests — 28/31 non-stub instances at 1 test each.** All 4 `excluded_because` stubs verified to resolve to real difficulty instances and were not translated.
- Total 64 tests; `pytest --collect-only` passes (imports execute cleanly against the installed framework).

## Per-instance skip list (all queue B)
1. `Corner/endpoints/list_filter_by_status` — PRD §4 declares only "List survey cycles" (no `status` filter); §2.3 rejects undeclared query params with ERR_INVALID_REQUEST, so the asserted filtered-200 is not uniquely derivable.
2. `Corner/rbac/people_analyst_cannot_create_item_bank` — instance asserts ERR_UNAUTHORIZED, but PRD §2.7/§3.1 explicitly name ERR_DUTY_SEGREGATION for a PeopleAnalyst creating banks; the PRD contradicts itself, so the error_id is not uniquely derivable.
3. `Corner/rbac/hr_admin_who_created_cycle_cannot_score_it` — same conflict: §2.7 names ERR_DUTY_SEGREGATION for the creating HRAdmin's scoring attempt; instance asserts ERR_UNAUTHORIZED.

One relaxation applied per the skill's error-precedence pattern (not a skip): `submit_window_half_open_at_closes_at` test 2 uses `validate_error_is_one_of([ERR_WINDOW_VIOLATION, ERR_INVALID_STATE])`, because PRD §2.5 permits the auto-close to fire when the clock reaches `closes_at`, leaving two PRD-named outcomes observable.

## Stage 2 lint verdict: PASS
- 64/64 tests carry exactly one `Design:` line; every tag resolves to a real instance (0 unknown, 0 dual-tagged, 0 stub-tagged).
- Coverage: Difficulty 18/18 (≥2 each), Corner 28/31 non-stub (shortfall = the 3 documented PRD-first skips).
- All 114 quoted citation spans survive a whitespace-normalized literal grep of `workspace/PRD.md` (C1/C2/C3).
- No `skip`/`skipif`/`xfail` markers; no "scaffold"/table references in generated code; `py_compile` and pytest collection both clean.

## Step 6: Generate Implementation — 2026-08-15T06:50:02.572Z

Implementation complete. Summary:

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_1991_employee_engagement_survey_action_planning/workspace/implementation/`:

- `start.sh` — foreground launcher, guarded `pip install` (no-op when flask already importable), `exec python3 app.py`, honors `PORT` (default 10000), binds `0.0.0.0`
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask app factory, blueprint registration, envelope error handlers (ApiError, 404/405/400, catch-all 500)
- `db.py` — in-memory stores (dicts keyed by id), logical clock defaulting to exactly `2026-08-01T00:00:00Z`, id/timestamp/version helpers, `public()` serializer stripping internal `_`-prefixed fields
- `errors.py` — `ApiError` + all 21 error-ID constants from the scaffold error catalog
- `response.py` — envelope helpers producing `meta.api_request_id` (`req_…`), `api_request_timestamp` (3-fractional-digit ISO 8601 UTC), `response_type`, `data`; list meta carries `limit`/`offset`/`total_count`/`has_more`
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, 5-role check, pagination parser (limit default 10, 1..100, offset ≥ 0, unknown-query-param rejection), body/field validators
- `services/calculations.py` — the 7 calculation rules
- `services/domain.py` — org-tree helpers, cycle auto-close on clock advance, reminder sweep, snapshot generation, plan auto-completion
- `routes/`: `item_banks.py`, `org_units.py`, `employees.py`, `cycles.py`, `invites.py`, `snapshots.py`, `action_plans.py`, `outcomes.py`, `clock.py`

## Endpoint count

**48 endpoints** implemented — the full §1.5 endpoint table including `/engagement/_clock/set_current_utc`.
(Orchestrator verification note: actual `@bp.get`/`@bp.post`/`@bp.patch` decorator count across routes/ is exactly 60, matching PRD §4's 60 rows and api_client.py's 60 client methods — the "48" above was the subagent's function count, not the route count. All three artifacts agree.)

## State machines implemented (6)

- **ItemBank**: DRAFT→ACTIVE (≥3 ACTIVE items), ACTIVE→RETIRED (no in-flight cycle; cascades item retirement)
- **SurveyCycle**: DRAFT→CONFIGURED (OCC `expected_cycle_version`, ≥3 items, bank ACTIVE, window order) →OPEN (clock ≥ opens_at, single-open invariant, eligibility sweep) →CLOSED (manual any time / auto at closes_at via clock set; INVITED/REMINDED→EXPIRED) →SCORING (snapshot generation, provisional risk; creator blocked by duty segregation) →REPORTED →ARCHIVED (all plans terminal)
- **SurveyInvite**: INVITED/REMINDED→REMINDED (cap 3, 24h-first/48h cadence, skip-not-error), →SUBMITTED, →PARTIAL, PARTIAL→SUBMITTED (response replacement), INVITED/REMINDED→EXPIRED at close
- **ActionPlan**: DRAFT→SUBMITTED (OCC `expected_plan_version`, ≥1 OPEN item, non-suppressed own-unit DIRECT snapshot, manager ownership), SUBMITTED→APPROVED (cycle REPORTED) / REJECTED (reason), REJECTED→DRAFT (reason cleared), APPROVED→IN_PROGRESS, IN_PROGRESS→COMPLETED (auto when last OPEN resolves with ≥1 DONE), DRAFT/IN_PROGRESS→ABANDONED (clock > due_at; OPEN items →DROPPED)
- **ActionItem**: OPEN→DONE (owner or manager) / DROPPED (manager only), both with progress recompute + parent auto-complete
- **BenchmarkSet**: ACTIVE→RETIRED

## Calculations implemented (7)

`engagement_score` (4dp per-answer products → 2dp dimension means → 2dp overall from unrounded products; PULSE treats all weights as 1.0), `response_rate` ((submitted + 0.5·partial)/invited, 4dp, EXPIRED stays in denominator, null when zero invited), `eligibility_sampling` (ACTIVE only, 30-day tenure gate, PULSE floor + hired_at/created ordering), `minimum_n_suppression` (unit thresholds always win, strict `<`, at-threshold visible), `benchmark_percentile` ((below + 0.5·ties)/n·100, 2dp, ACTIVE set only), `action_progress` (floor(100·done/total), DROPPED kept in denominator), `attrition_risk_index` (provisional 0.08 prior at SCORING; final observed ratio on ATTRITION linkage; ×2.75 modifier when any snapshot overall < 60.00; 4dp).

## Boot verification

- `bash start.sh` from `./implementation/` boots to HTTP-ready in ~1s on a fresh port; confirmed twice.
- Confirmed zero-state reboot: data created in boot A is absent in boot B (fresh process), clock reads exactly `2026-08-01T00:00:00Z` at startup.
- Three live end-to-end suites passed against fresh boots, covering: full census lifecycle, pulse floor sampling (floor(5×0.5)=2, earliest-hired first, LEAVE/recent-hire excluded), reminder cadence (0 sends before opens+24h, 48h spacing, sequence numbers, cap), invite ownership, partial→submit upgrade, response_rate 0.7 case, suppression boundary (n=3 at min_n=3 visible; n=2 suppressed with `{}`/`null`), publish gate (409 pre-REPORTED) vs confidentiality (403 outside subtree), verbatims gating, duty segregation both directions, both OCC rules (412), unit-cycle and threshold-inversion 422s, window violations, plan reject→revise→resubmit, auto-complete at 100%, abandon after due_at, benchmark too-small, pagination meta and envelope shape on success and error paths.

## Step 7: Run Tests and Iterate — 2026-08-15T07:02:11.658Z

All 8 rounds × 64 tests pass. Exiting with the required summary.

---

## Summary

**Iterations run: 3 sweeps** (round 1: 3 tests failing ×8 rounds; round 2: clean 8×64; round 3: clean 8×64 after one final PRD-fidelity edit).

**Tests deleted: none.** All three failing tests survived STEP 1 (PRD coverage + unique derivability).

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1991_employee_engagement_survey_action_planning/test_helpers/fixtures.py` — `pin_items()` gained an optional `start_order: int = 1` parameter. Root cause: the helper always numbered `display_order` from 1 per call, so a second pin batch on the same cycle (used by `test_occ_stale_cycle_version_on_configure` to simulate another writer's pin) collided with existing pins and tripped the PRD-required `ERR_DUPLICATE` uniqueness check. The fixture violated the PRD precondition; the implementation check was correct.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1991_employee_engagement_survey_action_planning/test_suite/test_03_cycle_configuration_and_occ.py` — the second `pin_items` call in `test_occ_stale_cycle_version_on_configure` now passes `start_order=4` (the cycle already holds display_order 1–3).

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1991_employee_engagement_survey_action_planning/workspace/implementation/middleware.py` — `optional_fields_present()` no longer rejects undeclared body fields with `ERR_VALIDATION`; it now ignores them. PRD §2.8 enumerates request-shape validation exhaustively for bodies (required fields, types, enums, ranges) and scopes unknown-identifier rejection to query parameters only ("any query parameter the endpoint does not declare is rejected with `ERR_INVALID_REQUEST`"). This fixed `test_create_item_bank_ignores_client_supplied_system_fields` and `test_computed_cycle_counters_ignore_client_supplied_values`, whose assertions (server-minted `id`, `version` starts at 1, derived counters start at 0/null) trace verbatim to PRD §2.4/§3.3. Fleet calibration confirmed: ~20 sibling tasks carry the same test and no other implementation whitelist-rejects body fields. Unknown query params are still rejected (verified by smoke test).
- `/home/ubuntu/github/CodingPRD/tasks/task_1991_employee_engagement_survey_action_planning/workspace/implementation/routes/cycles.py` — `configure_cycle` window check (`closes_at` strictly after `opens_at`) now raises `ERR_WINDOW_VIOLATION` (422) instead of `ERR_VALIDATION` (400), per PRD §2.5 verbatim: "Violations of these temporal rules are rejected with `ERR_WINDOW_VIOLATION` (HTTP 422)". Untested path; corrected for PRD fidelity, plus the matching import.

**Final state:** 8/8 parallel rounds clean, 64/64 tests each, zero errors, under `--isolation per-test-server`.

## Step 8: Finalize PRD — 2026-08-15T07:07:21.611Z

PRD_FINALIZED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1991_employee_engagement_survey_action_planning/workspace/PRD_FINALIZED.md` with exactly two inline edits, both traced to `<step_7_diff>` implementation fixes.

## Line counts and delta
- PRD.md: 297 lines; PRD_FINALIZED.md: 297 lines; 0% line-count delta (both edits are inline insertions within existing lines; 2 lines modified in place).

## Changes (one bullet per change)
- §2.8 — insert — appended one sentence to the request-shape validation paragraph: undeclared body fields are ignored, never rejected; client-supplied system/derived fields (`id`, `version`, `invited_count`, `response_rate`) have no effect; unknown-identifier rejection applies to query parameters only — `implementation/middleware.py:134-144` (`optional_fields_present` now a no-op).
- §3.3 — revise — in the configure conditions list, `closes_at` strictly after `opens_at` now names its error inline: "(a violation is `ERR_WINDOW_VIOLATION`, per §2.5)" — `implementation/routes/cycles.py:247-249`.

Step 7 items not patched: the `test_helpers/fixtures.py` `start_order` parameter and its `test_suite/test_03_cycle_configuration_and_occ.py` call-site change are pure fixture bugs (the fixture violated the PRD-pinned `display_order` uniqueness precondition of §3.3; the implementation's `ERR_DUPLICATE` check at `cycles.py:173-179` was already correct). The cycles.py window-check fix restored PRD-verbatim behavior (§2.5), so §2.5 itself is kept verbatim — only the §3.3 cross-reference site was pinned, since that is where the original implementer picked `ERR_VALIDATION`.

## Per-edit pre-edit search log

**Edit 1 (§2.8, undeclared body fields ignored)**
- (a) Subject: handling of request-body fields an endpoint does not declare.
- (b) Paths enumerated: grepped all `optional_fields_present` callers — 17 callsites across all 9 body-bearing route modules (`item_banks.py:39,89`; `org_units.py:41,110`; `employees.py:31,88`; `cycles.py:54,154,235`; `invites.py:107,152`; `snapshots.py:142`; `action_plans.py:61,141,192,250`; `outcomes.py:35`; `clock.py:18`) — and all `get_json_body` callers, confirming every body-parsing endpoint pairs with the now-no-op helper, so undeclared body fields are universally ignored. Also verified `create_cycle` (`cycles.py:97-115`) builds the resource dict solely from declared fields (server-minted `id`, `version` via `stamp_new`, derived counters hard-initialized), and that `parse_pagination` (`middleware.py:57-96`) still rejects unknown query parameters on list endpoints, while single-resource GETs (e.g. `cycles.py:138-142`) never call it — matching §2.8's existing list-endpoint scoping, which the edit reaffirms rather than widens.
- (c) Wording adjustment: explicitly scoped the new sentence with "unknown-identifier rejection applies to query parameters only" (mirroring the existing list-endpoint query-envelope sentence) so the universal body claim cannot be read as weakening the query-param rejection; named example fields (`id`, `version`, `invited_count`, `response_rate`) only as examples, avoiding any exhaustive-list claim that other endpoints could falsify.

**Edit 2 (§3.3, configure window error)**
- (a) Subject: error code for the `closes_at`-strictly-after-`opens_at` condition at cycle configure.
- (b) Paths enumerated: grepped all `ERR_WINDOW_VIOLATION` raise sites — `cycles.py:247-249` (configure; the only `closes_at > opens_at` check — cycle creation at `cycles.py:50-117` deliberately performs no window check), `action_plans.py:87` (plan `due_at` vs cycle `closes_at`, matches §3.7/§2.5), `action_plans.py:157` (milestone `target_at` vs plan `due_at`, matches §3.7's explicit naming), `action_plans.py:299` (early abandon, a separate rule not touched by this edit), `invites.py:65` (submission at/after `closes_at`, matches §3.4). Also read the full `configure_cycle` (`cycles.py:230-260`) to confirm the check order and that the sibling conditions keep their own errors.
- (c) Wording adjustment: phrased as "(a violation is `ERR_WINDOW_VIOLATION`, per §2.5)" attached solely to the window condition — it names no error for the bank-`ACTIVE` condition (impl raises `ERR_INVALID_STATE` there, a PRD silence outside Step 7 scope) and says nothing about creation-time behavior, so no enumerated path is mis-described.

## Step 9: Complete PRD — 2026-08-15T07:32:09.506Z

Step 9 complete. `/home/ubuntu/github/CodingPRD/tasks/task_1991_employee_engagement_survey_action_planning/workspace/PRD_COMPLETED.md` produced as a minimal patch over `PRD_FINALIZED.md`, aligned to `implementation/`.

**Stats**
- Source: PRD_FINALIZED.md — 297 lines / 46,792 chars; PRD_COMPLETED.md — 297 lines / 51,812 chars (all edits inline; no lines or sections added).
- Char delta: +5,020. Changed blocks: 23 (27 edit operations, some sharing paragraphs).
- Counts: 24 ambiguity-pins, 3 mismatch-revisions.

**Changes**

- §2.3 — insert — ambiguity — non-integer `limit`/`offset` rejected with ERR_INVALID_REQUEST — implementation/middleware.py:70-94
- §2.3 — insert — ambiguity — `has_more` is true exactly when `offset`+`limit` < `total_count` — implementation/response.py:25
- §2.8 — revise — mismatch — global check order rewritten to impl's real pipeline: auth → authz → early duty rejections (bank/item create) → URL existence → invite-ownership / UnitManager response gates → body-shape & query envelope → body FK existence → plan ownership → state machine (action-item complete/drop consult state before their owner check) → confidentiality/publish-gate/scoring-duty → per-operation business constraints → OCC last; previously claimed shape-validation-first — implementation/middleware.py:30-96, routes/invites.py:100-116, routes/action_plans.py:188-220, routes/item_banks.py:31-47
- §3.1 — insert — ambiguity — bank list `status` filter rejects values outside DRAFT/ACTIVE/RETIRED with ERR_VALIDATION — implementation/routes/item_banks.py:61-67
- §3.2 — revise — mismatch — null `parent_unit_id` accepted on both create and update (forest of roots); was "may be null only there" — implementation/routes/org_units.py:49-53,114-120; services/domain.py:45-46
- §3.2 — insert — ambiguity — parent reference resolved (ERR_REFERENCE_NOT_FOUND) before threshold range/inversion checks; inversion precedes acyclicity on update — implementation/routes/org_units.py:49-68,114-137
- §3.3 — insert — ambiguity — cycle create resolves `bank_id` existence before `min_n_default`/`sampling_ratio` range checks — implementation/routes/cycles.py:71-95
- §3.3 — insert — ambiguity — pinning permitted only while cycle is DRAFT (else ERR_INVALID_STATE); pin request carries `item_id`, `pinned_weight`, `display_order` with the supplied `pinned_weight` stored verbatim as the snapshot; per-cycle item list sorts by `display_order` ascending — implementation/routes/cycles.py:149-201
- §3.3 — insert — ambiguity — linked bank not ACTIVE at configure → ERR_INVALID_STATE — implementation/routes/cycles.py:250-252
- §3.3 — insert — ambiguity — open before `opens_at` → ERR_INVALID_STATE — implementation/routes/cycles.py:270-271
- §3.3 — revise — ambiguity — tenure gate compares `hired_at` to the exact instant 30 days before `opens_at` (was "the date thirty days before") — implementation/services/calculations.py:84-90
- §3.3 — revise — ambiguity — open increments cycle version by 1, plus a further §2.4 increment when the counter recompute changes values (i.e., whenever ≥1 employee invited) — implementation/routes/cycles.py:277-280; services/domain.py:64-79
- §3.4 — revise — ambiguity — PARTIAL→SUBMITTED upgrade uses the same submit endpoint with full-coverage `answers`; complete accepted from INVITED/REMINDED/PARTIAL, partial only from INVITED/REMINDED, else ERR_INVALID_STATE — implementation/routes/invites.py:114-120,159-166
- §3.4 — insert — ambiguity — answers repeating a cycle item, naming another cycle's item, or with score outside 1–5 are ERR_VALIDATION — implementation/routes/invites.py:38-51
- §3.4 — insert — ambiguity — both submission endpoints return 201 with the updated invitation in `data` — implementation/routes/invites.py:141,184
- §3.4 — revise — ambiguity — sweep covers only INVITED/REMINDED invitations; first-reminder 24h measured from the cycle's `opens_at` instant — implementation/services/domain.py:163-177
- §3.5 — insert — ambiguity — snapshots generated unit-by-unit in unit creation order, DIRECT before SUBTREE per unit — implementation/services/domain.py:118-136
- §3.5 — insert — ambiguity — verbatims listing: object envelope with `comments` array (limit/offset slice it, no pagination meta), non-empty comments of SUBMITTED invites in scope, ordered by invitation creation then answer order; suppressed → ERR_CONFIDENTIALITY for every role — implementation/routes/snapshots.py:96-131
- §3.6 — revise — mismatch — benchmark entries carry at most 2 decimal places (was "at 2 decimal places") — implementation/routes/snapshots.py:149-159
- §3.6 — revise — ambiguity — percentile computed against the earliest-created ACTIVE benchmark set (was "an ACTIVE benchmark set linked") — implementation/services/calculations.py:222-224
- §3.7 — insert — ambiguity — manager read scope: plan list filtered to directly-managed units; cross-unit plan/item fetch → ERR_PLAN_OWNERSHIP — implementation/routes/action_plans.py:106-133,174-184
- §3.7 — insert — ambiguity — action items addable only while plan is DRAFT (else ERR_INVALID_STATE) — implementation/routes/action_plans.py:152-154
- §3.7 — insert — ambiguity — plan submit guards named: no OPEN item → ERR_INVALID_STATE; missing or numerically-suppressed DIRECT-scope unit snapshot → ERR_CONFIDENTIALITY — implementation/routes/action_plans.py:202-216
- §3.7 — insert — ambiguity — complete/drop permission violations → ERR_PLAN_OWNERSHIP; each complete/drop increments the plan's version by exactly 1 (the single increment covers auto-completion when it fires) — implementation/routes/action_plans.py:326-339,354-365; services/domain.py:203-216
- §3.7 — insert — ambiguity — abandonment at or before `due_at` → ERR_WINDOW_VIOLATION — implementation/routes/action_plans.py:297-300
- §3.8 — revise — ambiguity — `attrition_risk` recomputed at exactly two moments (scoring transition; each ATTRITION linkage write); version advances only when the value changes; provisional write folds into scoring's single increment; PERFORMANCE linkages never affect it — implementation/routes/outcomes.py:57-63; services/domain.py:139-141; routes/cycles.py:307-310
- §3.8 — revise — ambiguity — engagement modifier fires when any of the cycle's snapshots has a non-suppressed `overall_score` below 60.00; multiplier 1 when all suppressed or none exist — implementation/services/calculations.py:283-293
- §4 — insert — ambiguity — declared filter query params pinned in 9 table cells: item-banks `status`; org-units `parent_unit_id`; employees `unit_id`,`employment_status`; cycles `status`,`cycle_kind`,`bank_id`; cycle-items `cycle_id`,`item_id`; invites `cycle_id`,`employee_id`,`status`,`unit_id_at_invite`; snapshots `cycle_id`,`unit_id`,`scope`; benchmark-sets `status`; plans `cycle_id`,`unit_id`,`status`; per-employee linkages `cycle_id` — implementation/routes/{item_banks.py:61, org_units.py:89, employees.py:64, cycles.py:123,207, invites.py:71, snapshots.py:51,176, action_plans.py:109, outcomes.py:72}

The dominant finding was the §2.8 mismatch: the PRD claimed request-shape validation runs before authentication, while the implementation authenticates and authorizes first, checks URL existence before body shape, and places ownership/duty gates at endpoint-specific positions; §2.8 now describes the pipeline the code actually executes. Everything else the PRD stated (scoring math, suppression thresholds, reminder cadence, OCC scope, envelope formats, role tables, error catalogue) matched the implementation as written.
