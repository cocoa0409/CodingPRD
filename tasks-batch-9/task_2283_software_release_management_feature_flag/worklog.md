# Worklog — task_2283_software_release_management_feature_flag

## Step 1: Create task directory — 2026-09-01T14:45:47.000Z

Created `tasks/task_2283_software_release_management_feature_flag/` and `tasks/task_2283_software_release_management_feature_flag/workspace/`.

## Step 2: Generate Scaffold — 2026-09-01T16:20:00.000Z

Step 2 complete. All three artifacts are on disk, parse cleanly, and the scaffold lint is clean.

## Files
- `/home/ubuntu/github/CodingPRD/tasks/task_2283_software_release_management_feature_flag/SCAFFOLD.yaml` (1990 lines, §1.0–§1.7 only — no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_2283_software_release_management_feature_flag/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1613 lines, single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_2283_software_release_management_feature_flag/SCAFFOLD_CORNER_DESIGN.yaml` (4141 lines, single key `scaffold_corner_design`)

## Counts
- **Scenario** stored verbatim; `difficulty_level: beyond_expert`.
- **§1.1** 15 entities: ReleaseTrain, Environment, Release, ChangeRequest, ChangeDependency*, Approval*, FeatureFlag, ChangeFlagLink*, FlagRolloutStep, Deployment, CanaryEvaluation*, HealthSignal*, Incident, ReleaseNoteDocument, ComplianceEvidencePacket (* = `common_fields: false`, immutable).
- **§1.2** 9 state machines (cyclic shape: flag DRAFT→ACTIVE_ROLLING_OUT⇄PAUSED→…→ARCHIVED; train ACTIVE⇄FROZEN). **§1.2.1** 2 OCC rules (`expected_feature_flag_version`/ERR_STALE_FLAG_VERSION, `expected_release_version`/ERR_STALE_RELEASE_VERSION, both 412).
- **§1.3** 8 calculations, 2 with dual variants (`change_risk_score` preliminary/final, `release_readiness_score` projected/attested).
- **§1.4** 37 priority-ordered validations. **§1.5** 58 endpoints. **§1.6** 50 errors. **§1.7** 6 roles, `role_model: segregation_of_duties`.
- **§1.8** 18 instances (2 per Difficulty Rule × 9). **§1.9** 88 instances across all nine sections — entities 14, state_machines 16, calculations 14, validations 11, endpoints 6, errors 15, rbac 5, cross_cutting_complexity_layers 6, consistency_model 1 — of which 62 carry full test recipes and 26 are `excluded_because` stubs pointing at the §1.8 instance that already covers the corner.

## Coverage audit
- All 50 error ids are referenced by at least one design instance (0 uncovered).
- 106 instance names across both files, all unique.
- Placeholder closure verified programmatically: 0 `${var}` uses unbound by an earlier `captures:`.
- `scaffold_lint.py`: `VERDICT: clean lint` over 777 scanned calls — endpoint/method match, role membership, payload key subset, capture JSONPath resolvability, `expected_*_version` placeholder-only, and FK reverse-reachability all pass.

## Design adjudications
- **`beyond_expert` levers:** four active complexity layers (`optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `rate_threshold_triggers`), graph topology (two junctions plus a cycle-checked dependency edge), cyclic state machines, and a 37-rule priority ladder where RBAC (p2) and state preconditions deliberately shadow the temporal/window rules (p29–p34).
- **Interval geometry made deliberately non-uniform** so boundary tests are falsifiable: deploy windows half-open `[start, end)`, blackouts closed `[start, end]`, deployment occupancy half-open with a trailing cooldown buffer, stabilization capacity closed, and cut/apply gates inclusive (`>=`).
- **Fixture hazards resolved during authoring:** the rollout ladder is checked at creation against *current* exposure (so all pre-seeded steps use `target_pct <= 5`); ERR_STEP_OUT_OF_ORDER needs a fixture with no soaking step or p21 wins; two concurrently stabilizing releases require `max_concurrent_stabilizing: 2`; post-freeze merges need `POST /releases/{id}/freeze-exceptions` first; the flag version between step creations is always re-read via GET rather than assumed.
- **Every formula-derived assert is a pre-computed literal**, e.g. risk scores 9/18/28/33/46/50/52/62/85 across the class boundaries (50 = HIGH, 46 = MEDIUM), canary 96.0 PASS vs 58.0 FAIL at exactly 25.0 % error rate vs 58.14 at 24.9 %, stale-debt 0/27/30/60 for the COMPLIANT/WARNING/OVERDUE/ENFORCED buckets, evidence base_index 75→85 with cap tier 10, readiness attested 100/94/76 against the 80 floor.
- **Two YAML flow-context gotchas** were hit and are now fully applied: plain scalars terminate on `?` (so `field?` in `input:` lists is quoted) and any value containing `[` (all JSONPath captures) is quoted.

**Orchestrator notes:** the Step 2 subagent was interrupted twice by transient API errors and resumed via SendMessage. The orchestrator also repaired 6 YAML flow-mapping syntax errors in `SCAFFOLD_CORNER_DESIGN.yaml` (unquoted `$.data[0].id` JSONPath captures) and detected that the first corner-design write contained only 2 of the 9 required §1.9 sections; the subagent appended the remaining 7 on resume.

## Step 3: Copy Shared Files — 2026-09-01T16:23:40.000Z

Copied `INSTRUCTION.md` → `tasks/task_2283_software_release_management_feature_flag/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T16:41:30.000Z

PRD complete and verified at `workspace/PRD.md`.

## Deliverable
**474 lines / ~14,080 words.** Ends at §5 — no audit footer, no contract reports in the file.

## Section list
- `# Software Release Management & Feature Flag Governance API — Product Requirements Document`
- **§1 Introduction** (3 paragraphs: release-office framing, the four disciplines, the flat-topology + logical-clock constraints)
- **§2** — 12 subsections: 2.1 User and Role-Based Access Control · 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`, diff-confirmed) · 2.3 Pagination and Inventory Filters · 2.4 The Logical Clock · 2.5 Common Resource Properties and Immutable Records · 2.6 Point Scales, Percentages and Rounding · 2.7 Optimistic Concurrency on Flags and Releases · 2.8 The Rejection Ladder (all 37 ranks) · 2.9 Path Resolution for Nested Resources · 2.10 Cascade Discipline and Derived-Counter Reconciliation · 2.11 Interval Geometry · 2.12 Segregation of Duties
- **§3** — 9 subsections: 3.1 The Release Train and Its Freeze Cascade · 3.2 Opening and Cutting a Release · 3.3 Authoring and Classifying a Change · 3.4 Prerequisite Graphs, Approval Lanes, Merging and Withdrawal · 3.5 The Feature Flag Inventory and Its Rollout Ladder · 3.6 Staleness Debt and Cleanup Enforcement · 3.7 Environments, Deployment Windows and Canary Delivery · 3.8 Incidents, Rollback Cascades and Forward Fixes · 3.9 Release Notes, Evidence Packets and the Final Release Gate
- **§4 Endpoint Definitions** — 4 columns, 58 rows
- **§5 Error Code Catalogue** — 2 columns, 50 rows

## Coverage audit vs SCAFFOLD.yaml §1.1–§1.7
| Scaffold | Count | Status |
|---|---|---|
| §1.1 entities / fields | 15 / 129 | all 129 field names appear verbatim in backticks; the five `common_fields: false` types are named and their absent `updated_at`/`version` stated |
| §1.2 state machines | 9 / 49 transitions | every transition covered, including all system-event ones and the pinned 5-hop freeze, compensating unfreeze, 4-hop canary abort and 4-hop release-rollback cascades |
| §1.2.1 concurrency rules | 2 | both in §2.7 with non-optional `expected_feature_flag_version` / `expected_release_version` and 412s |
| §1.3 calculations | 8 (2 dual-variant) | all formulas, constants and precision notes reproduced; both variant pairs distinguished |
| §1.4 validations | 37 | all ranks in §2.8 in strict order with their `applies_to` scopes; shadowing pairs called out (7 over 10, 15 over 37, 11 over 12) |
| §1.5 endpoints | 58 | 58 table rows; every `side_effects` entry narrated in §3 |
| §1.6 errors | 50 | all 50 in §5 and referenced in prose (`ERR_XXX` in the scaffold's envelope illustration is a placeholder, not an error id) |
| §1.7 RBAC | 6 roles | all named; `identity: opaque` handling spelled out for all six |

## Hard Contracts
- **Contract 1 — Field-Name Coverage: PASS.** 140/140 required identifiers (129 entity fields + 11 input-only) present in backticks; 0 missing. 34 additional output/nested/envelope identifiers also verified (`current_utc`, the seven sweep-summary counters, `waived_by_user_id`, the six evidence `item_code` values, envelope fields).
- **Contract 2 — Rule Coverage: PASS.** Priority ordering, both OCC rejections, all cross-entity cascades, `applies_to` scopes, field-level structured content (`waivers` objects, `missing_items`, `included_change_ids`), and sibling-branch symmetry (OPEN/FROZEN→CUT, STABILIZING/RELEASED→ROLLED_BACK, IN_PROGRESS/CANARY_SOAK→COMPLETED, FULLY_ROLLED_OUT/PAUSED→ARCHIVED, both approval joins) all stated as equal-weight.
- **Contract 3 — §3 Path Purity: PASS.** 0 backticked tokens in §3 start with `/`, are a bare HTTP method, or combine method+path; 0 raw URL-path mentions either.

## Zero-Silence adjudications (5)
1. **`direction` query-parameter domain** was unspecified → defined as `OUTGOING` (change is the edge's `from_change_id`; the default when omitted) and `INCOMING` (change is the `to_change_id`).
2. **Rollout-step deployment preconditions carried no error id** → assigned the rank-8 family member `ERR_DEPLOYMENT_STATE_INVALID` (409) for both "soak start requires the named deployment to be `IN_PROGRESS` or `CANARY_SOAK`" and "apply requires its `verification_state` to be `PASSING`".
3. **The merge-time risk-budget re-check** appears in the transition preconditions but in no `applies_to` row → expressed as an explicit merge rejection with `ERR_RISK_BUDGET_EXCEEDED` (409), noted at rank 36 alongside submit and approve.
4. **Change-request creation phase gate:** the endpoint description says "against an open release" but validation rank 9's `applies_to` deliberately omits creation → creation is described with no phase gate; the `phase == OPEN` requirement is stated only for submit. Flagging this as the one place where scaffold prose and the enumerated scope disagree.
5. **Release-notes generation and evidence-packet assembly carry no release-phase precondition** → stated explicitly that both are available at any point in the release's life; only *publication* is gated on `CUT`/`STABILIZING`/`RELEASED`.

## Constraint compliance
`SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped or referenced, and no sibling task directory was read. One disclosure: this task's own `worklog.md` (read for context) incidentally quotes design worked-example numbers — none of those literals were carried into the PRD. The worked figures that do appear in §3.5 ("first rung at most 5 percent, 5→15, 15→45, 45→100") are derived directly from the `rollout_step_ladder` formula and constants in SCAFFOLD.yaml.

**Orchestrator verification:** grepped `workspace/PRD.md` for the design-only worked literals quoted in the Step 2 worklog entry (58.14, 96.0, 58.0, the risk-score series). No leakage — every numeric hit is a §1.4 rank number or a §1.3 formula constant.

## Step 5: Generate Unit Tests — 2026-09-01T18:38:00.000Z

All nine corner sections are now translated; the suite is complete.

## Files written

- `test_suite/test_13_concurrency_tokens_and_threshold_geometry.py` — 4 tests (`cross_cutting_complexity_layers`)
- `test_suite/test_14_write_responses_carry_the_settled_state.py` — 1 test (`consistency_model`)
- `test_helpers/fixtures.py` — 2 new fixtures appended: `scenario_cut_release_and_the_version_read_at_its_creation` (release token captured at creation, then advanced by a merge and a cut) and `scenario_staging_canary_with_two_samples_bracketing_the_abort_rate` (STAGING canary, `abort_error_rate_pct` 25.0 / `abort_latency_p95_ms` 800 / `min_sample_count` 5, samples 8req/2err at 02:10 and 1000req/249err at 02:40, both p95 300 ms, clock at 02:45)
- Citation repairs in three earlier files (see audit notes): `test_08_…`, `test_01_…`, `test_06_…`

Full inventory of the generated suite: `test_helpers/` (`__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`) and `test_suite/test_01_…` through `test_suite/test_14_…`.

## Test counts

| Queue | Source | Live instances | Tests |
|---|---|---|---|
| A (§1.8 difficulty) | 9 rules / 18 instances | 18 | 59 functions (60 collected; one 2-case parametrize) in `test_01`–`test_05` |
| B (§1.9 corner) | 9 sections / 62 live + 26 stub | 62 | 61 (1 : 1) in `test_06`–`test_14` |

Queue B by section: entities 14, state_machines 10, calculations 7, validations 8, endpoints 4, errors 9, rbac 4, cross_cutting_complexity_layers 4, consistency_model 1. Total collected: **121 tests**. All 26 stub instances emit nothing, as required.

## Instances skipped (1)

- `Corner/endpoints/link_endpoints_with_unknown_body_ids_return_resource_not_found` — the instance asserts all three link creates return `ERR_RESOURCE_NOT_FOUND`, but PRD rank 5 (line 119) routes an unknown `feature_flag_id` to `ERR_FEATURE_FLAG_NOT_FOUND` and an unknown `to_change_id` to `ERR_CHANGE_REQUEST_NOT_FOUND`. The asserted outcome is not PRD-derivable, so the instance was dropped with no placeholder.

## Derivations pinned this session

- Canary at the threshold (PRD lines 305–309): window [02:30, 02:45) sees only the 1000-request row → rate 24.9, error component 40.24, latency component 85, score **58.14**, `abort_triggered` false, `PASS`, deployment `PASSING`. Window [02:00, 02:30) sees only the 8-request row → rate exactly 25.0, error component 40, score **58.0**, `abort_triggered` true (`>=`), `FAIL`, deployment `FAILING`; `delivery_state` stays `CANARY_SOAK` because an evaluation never fires the abort cascade (line 311 is a separate act). Both sample counts clear `min_sample_count` 5.
- Version ladder: planning bumps the flag once (line 263) and the `DRAFT → ACTIVE_ROLLING_OUT` hop bumps it again (line 267), so the post-soak version is creation + 2; pause (271) and resume (273) add one each, with the intervening GET flat.
- Two deliberate deviations from the design recipes, both because the PRD uniquely derives otherwise: the new step's `previous_exposure_pct` is asserted **null** (line 263: "begins in `state` `PLANNED` with null `previous_exposure_pct`"), not 0; and the `version == 1`-at-creation sub-assertion was dropped, since PRD line 91 defines only the increment, never the initial value.
- Cut response (line 203): deferral runs before the attested score, so the body itself reports `CUT`, attested **94** (100 − 6 for the single deferred MEDIUM), `committed_change_count` 1, `risk_budget_consumed_points` 9, and the follow-up GET matches phase, both readiness figures and `version`.

## Coverage audit

- **Design tags**: 120 test functions, 120 tags, each exactly one line and last in its docstring; every tag resolves to a live (non-stub) instance; no untagged or dual-tagged tests. Queue A tags repeat across the multiple tests belonging to one instance (by design); queue B is strictly 1 : 1.
- **Uncovered live instances**: exactly the one skip above.
- **Citation grep**: 157 quoted fragments from test docstrings plus 38 from module/class docstrings verified as literal substrings of `workspace/PRD.md`. Three misses were found and fixed rather than left: restored `**15 points**` emphasis and completed the orphan clause in `test_08`, restored `**immediately**` / `` `risk_class` `` in the `test_01` class docstring, and replaced a non-verbatim "take their declared defaults" quote in `test_06` with unquoted prose.
- `python3 -m pyflakes test_suite/*.py test_helpers/*.py` clean; collection clean at 121 tests. No sibling task directory, `worklog.md`, or `workspace/implementation/` was read.

## Step 6: Generate Implementation — 2026-09-01T17:55:00.000Z

Implementation complete and verified.

## Files written (3,356 lines total)

**Root** — `app.py` 57, `db.py` 303, `errors.py` 69, `middleware.py` 31, `response.py` 46, `validate.py` 182, `requirements.txt` 1 (`flask>=2.0`), `start.sh` 11 (executable)
**services/** — `__init__.py` 0, `calc.py` 550, `cascade.py` 399
**routes/** — `__init__.py` 14, `system.py` 65, `trains.py` 125, `releases.py` 192, `changes.py` 380, `flags.py` 331, `deployments.py` 314, `incidents.py` 103, `docs.py` 183

## Module layout

- `db.py` — the whole store: `Store` with 15 dicts keyed by id, the logical clock (default `2026-08-01T00:00:00Z`), `make`/`upd`/`touch`/`public`, per-record `_seq` for insertion-order tie-breaks, and typed getters that raise the right 404 (`ERR_RELEASE_NOT_FOUND` vs `ERR_RESOURCE_NOT_FOUND`).
- `errors.py` / `response.py` / `middleware.py` / `validate.py` — the 50-error catalogue with statuses, the `meta`/`response_type`/`data` envelope, rank-1/2 auth, and rank-3 shape validation.
- `services/calc.py` — the eight pure calculations (dual risk scores, dual readiness scores, canary verdict, stale debt, ladder geometry, note generation, incident linkage, evidence index).
- `services/cascade.py` — the ordered multi-hop cascades and derived-field refreshers, kept out of routes so hop order is pinned in one place.
- `routes/*` — 58 endpoints across 8 blueprints, flat topology (`api_prefix: ""`).

**Endpoints: 58 (47 unique paths), verified to match the PRD's endpoint table exactly** — no missing, no extra.

## Verification

Boot-from-scratch confirmed: launched, created a train and moved the clock, killed, relaunched on the same port — clock back to `2026-08-01T00:00:00Z`, every collection at `total_count` 0, the previously-used train name reusable, no tracebacks. Storage is pure in-memory; a grep for `sqlite3`/`open(`/`json.dump`/`pickle`/`/tmp` across all `.py` files returns nothing, and nothing is seeded.

I also ran four progressively deeper smoke suites (~150 assertions) over the live server covering the full lifecycle and every cascade. **All discrepancies turned out to be errors in my own test expectations, each traced back to the PRD and confirmed to be correct implementation behaviour** — notably: canary score 79.6 (per-row rounding then weighting), risk score 85 for a 2000-line/12-subsystem/GLOBAL/migration change (size and spread caps bind, then −10 rollback credit), `ERR_DEPENDENCY_CYCLE`/`ERR_EVIDENCE_PACKET_REQUIRED` are 409 while `ERR_ROLLBACK_PLAN_REQUIRED` is 422, attested 94 when an exception-merge lands at/after `freeze_at` (−6 late), orphan flag debt 15 → `WARNING`, and `cut_at` (not actual cut time) governing incident linkage.

Cascades explicitly verified end-to-end: 5-hop train freeze (defer → block APPROVED dependents → ledger debit → projected recompute) and its unfreeze compensation; 4-hop canary abort (deployment ABORTED/FAILING → `active_deployment_count` decrement → SOAKING step ABORTED with exposure restored → flag PAUSED + kill switch); 4-hop release/deployment rollback with `verified_change_count` reset and `last_deployment_end_at` recompute; and the cleanup sweep driving a rolling flag to ENFORCED with full ladder teardown (SOAKING→ABORTED, PLANNED→VOIDED) and the three rank-13 enforcement walls.

## PRD ambiguities resolved

- **`ERR_DUPLICATE_APPROVAL_KIND`** fires only when the new decision is `APPROVE` *and* an existing `APPROVE` of that kind exists — a REJECT does not consume the lane.
- **`dependency_depth`** is recomputed only for the `from_change` (literal §3.4 wording), not transitively for ancestors.
- **Unknown waiver `item_code`** → rank-3 `ERR_INVALID_REQUEST` (400), not `ERR_WAIVER_NOT_ALLOWED`; the latter is reserved for the three admissibility rules.
- **`api_request_timestamp`** uses real wall clock; §2.4 lists only entity stamps as clock-derived.
- **FREEZE with `open_release_count` < 1** → `ERR_RELEASE_PHASE_INVALID` (the only catalogued error for a misdirected freeze).
- **Version-bump granularity**: `upd()` bumps `version`/`updated_at` only when a field value actually changes, and multiple derived recomputes on the same resource within one operation are batched into a single bump; cascade hops bump separately per §2.10. This drove `cascade.last_deployment_end_value()` so `complete` decrements `active_deployment_count` and recomputes `last_deployment_end_at` in one bump.
- **Merge ordering**: dependents are unblocked *before* the batched `rollback_plan_confirmed` + `readiness_score_projected` recompute, so projected reflects post-unblock states.
- **Publish ladder**: DRAFT → `entry_count` → release phase, since publish is not one of rank 9's five enumerated operations, so §3.9's narrative order governs.
- **Deployment window geometry**: `window_start_at >= midnight(start_date) + start_hour` and `window_end_at <= midnight + end_hour`, permitting end hour 24 while rejecting midnight-straddling windows.
- **`waive_verification`** honoured only when `verification_state == INCONCLUSIVE` and env `tier != PROD`, applied before the strategy gate.
- **Canary evaluation** accepted from any `delivery_state` and the verdict always written, but the abort cascade only runs when `delivery_state ∈ {IN_PROGRESS, CANARY_SOAK}`.
- **Unfreeze ordering**: DEFERRED→RISK_CLASSIFIED restoration runs *before* the BLOCKED_BY_DEPENDENCY prerequisite check, so a just-restored prerequisite counts as un-abandoned.
- **Waiver recomputation** keys off the packet's frozen `base_index` via a private `_satisfied` snapshot (stripped from responses) rather than re-deriving from live release facts.
- **Query-string filters** are not validated — an unknown enum value yields an empty result set rather than a 400.
- **Change-request creation** has no release-phase precondition; only submission requires `OPEN`.
- Environment `name` collision → `ERR_INVALID_REQUEST` (there is no dedicated error for it).

One spec consequence worth flagging: since `step_index` must equal `applied_step_count + 1` (§3.5), an ABORTED or VOIDED rung permanently consumes its index, so a flag whose ladder is torn down cannot resume stepping without archival. That is what the PRD says literally, and I implemented it as written.

## Step 7: Run Tests and Iterate — 2026-09-01T23:48:30.000Z

Driver stood down; `workspace/implementation/` has no results files and no writers, so the canonical sweep location is clear for you.

## Summary

### Iterations run: 3 fix/verify iterations, 23 archived round-runs

| iteration | sweep | outcome |
|---|---|---|
| 1 (pre-compaction) | 8-round parallel | 98/121 in 7 rounds, 97/121 in round 3 → 24-test failing union, 5 root causes |
| 2 | 8-round parallel, finished 20:18 | all 8 rounds collected 121; **1** genuine failure left (test_11 clock comparison, failing in 6 rounds / erroring in 2) |
| 3 | rounds at 21:02, 21:22, 21:43 (+ orchestrator's 23:07 pair) | **zero genuine assertion failures in every round**; all non-passes are the harness `lsof`/`kill` `subprocess.TimeoutExpired` teardown signature |

Union-coverage check run over all 21 archived results files: **all 121 tests pass in at least one round; none never-passed.**

### Tests deleted: NONE
No failure survived STEP 1 as a PRD-silence or unique-derivability collapse. Every one traced to an over-specified assertion (PRD covers the value but not its rendering → narrowed per STEP 1c), a fixture that itself violated PRD, a test assertion contradicting PRD prose, or host infrastructure.

### Fixes to `test_helpers/`
- **`assertions.py`** — added `parse_instant()` and `assert_instant()` (+ `datetime`/`timezone` import). PRD pins three fractional digits **only** for `api_request_timestamp` (§2.2) and `created_at` (§2.5); §2.4/§2.5 pin the *instant* for every other stamped, echoed or derived timestamp and say nothing about rendering, so exact-string comparisons were asserting an uncovered rule.
- **`__init__.py`** — re-exported `assert_instant` (import block + `__all__`).
- **`fixtures.py`, `scenario_release_ready_to_cut_with_deferrable_change`** — return the *submit* response for the medium change (`submitted_medium`) instead of the create response. PRD §3.3: a change "begins in `state` `DRAFT` with `risk_score_preliminary`, `risk_score_final` and `risk_class` all null", so the fixture was handing tests a DRAFT body and then asserting a pinned preliminary score (test_14 got `None` for `33`) — a fixture bug, not an implementation gap.

### Fixes to `test_suite/`
- **`conftest.py`, `api` fixture** — session-scoped → function-scoped. With `--isolation per-test-server` the harness restarts the server before every test, so a session client pooled keep-alive sockets the restart had already closed → intermittent `RemoteDisconnected`.
- **30 timestamp assertions rewritten to `assert_instant(...)`** across 8 files (STEP 1c: keep the PRD-covered instant, drop the uncovered format): `test_02` (`stabilization_end_at` ×2), `test_06` (`expires_at`, `freeze_at`, `stabilization_end_at`), `test_07` (`published_at`, `generated_at`, `archived_at`, `rolled_back_at` ×2), `test_08` (`generated_at`, `last_sweep_at`), `test_09` (`merged_at`, `freeze_at`, `released_at`), `test_10` (`last_sweep_at` ×2), `test_11` (`soak_started_at`, `applied_at`, `decided_at`, `generated_at`, `published_at` ×3, `merged_at` ×2, `window_start_at`, `window_end_at`), `test_12` (`last_sweep_at`, `soak_started_at`).
- **`test_11_error_identity_scope_and_sequencing.py`, `test_the_second_publish_is_refused_and_the_first_timestamp_survives`** (the 20:20 edit) — `assert built["clock_after_publication"] == NOTES_REREAD_AT` → `assert_instant(..., NOTES_REREAD_AT, "current_utc")`. This was the last genuine failure (`'2026-08-09T00:00:00.000Z' != '2026-08-09T00:00:00Z'`). PRD §2.3 says only "the response reports the resulting clock as `current_utc`" — the instant is covered, the fractional rendering is not.
- **`test_09_validation_gates_boundaries_and_ladder_order.py`** — `assert_stale_debt(built["fresh"], 15, CleanupState.WARNING)` (was `0, COMPLIANT`). PRD §3.6: "It accrues a further **15 points** when the flag is an orphan, meaning it has no change-to-flag links at all" + "any debt greater than zero is `WARNING`"; the fixture's fresh flag has no links.
- **`test_10_endpoint_surface_round_trips_and_projections.py`** — `assert_sweep_summary(... warning_count=1)` and `assert_stale_debt(fresh, 15, WARNING)`, same §3.6 rule; corroborated by test_08's passing four-orphan tier test which budgets +15 for every flag.
- **`test_13_concurrency_tokens_and_threshold_geometry.py`** — `assert_deployment_dimensions(after_at_threshold, DeliveryState.ABORTED, VerificationState.FAILING)` (was `CANARY_SOAK`). PRD §3.7: "**Hop one**: the deployment's `delivery_state` becomes `ABORTED` and its `verification_state` becomes `FAILING`"; test_04's four passing abort tests agree, test_13 was the inconsistent one.

### Fixes to `implementation/`
- **`workspace/implementation/app.py`, `__main__` block** — `app.run(..., threaded=False)` → `threaded=True`. Serves concurrent/keep-alive connections so per-test restarts under host load don't surface as `RemoteDisconnected`. No PRD semantics touched; no endpoint, field, side effect or header added. **This is the only implementation edit in the whole task.** Storage remains process-local in-memory dicts in `db.Store`, nothing seeded, no file/SQLite/`/tmp` persistence. `db.iso()` was audited and deliberately **not** changed — it renders three fractional digits everywhere, which is exactly what PRD §2.5 requires of `created_at`.

### Environment notes
- Confirmed independently: host at 0% idle, ~395 runnable threads on 32 cores (12× oversubscription), `/proc/net/tcp` holding 16,281 sockets and taking 1.9 s just to read; bare `lsof -ti:PORT -sTCP:LISTEN` measured 4.99 s against the runner's 5 s budget. A `/proc`-based `lsof` shim was built, validated, measured at the same 5 s, and **removed** — the cost is scheduling latency, not algorithmic.
- Several sweeps were destroyed mid-flight by SIGKILL from outside the process group (not OOM — no kernel OOM records, 72 GB available), which is why the loop needed supervisor scripts.
- Evidence preserved: `/tmp/t2283_archive/` (21 results files + matching pytest logs). Reusable classifier: `/tmp/t2283_verdict.py <results.json> v` prints `genuine infra passed total` and dumps genuine entries to stderr, treating `lsof`/`kill` `TimeoutExpired`, `ServerStartError` and boot-timeout entries as infrastructure.

**Orchestrator corroboration (independent of the Step 7 agent):** I ran my own 2-round sweep at 23:07 into a separate results path and classified every non-passing entry programmatically — 172 of 172 carried the harness `lsof`/`kill` `subprocess.TimeoutExpired` teardown signature, with `failed == 0` in both rounds. I also profiled the teardown directly: real `lsof -ti:PORT -sTCP:LISTEN` 6–8 s vs. the runner's 5 s budget, `ss`-based equivalents 4–7 s, host load average ~415 with ~3500 processes and 500+ concurrent `prd-bench-local-run` processes from sibling pipelines. I independently built and then abandoned a scoped `ss` shim for the same reason the Step 7 agent abandoned its `/proc` one. The canonical 8-round sweep into `workspace/implementation/results.{1..8}.json` is owned by the orchestrator and recorded below.

## Step 8: Finalize PRD — 2026-09-01T23:56:00.000Z

Done. `PRD_FINALIZED.md` written with a single two-line insertion.

## Line counts
- `PRD.md`: 474 lines
- `PRD_FINALIZED.md`: 476 lines (+2, **+0.42%**)

## Changes
- **§2.4 (The Logical Clock)** — *insert* — a new paragraph pinning uniform instant rendering: every instant in a response body (server-stamped, client-echoed, server-derived, and `current_utc`) is ISO 8601 with exactly three fractional digits and a trailing `Z`, converted to UTC first and truncated to millisecond precision; absent timestamps render as null. `api_request_timestamp` is explicitly set aside as already pinned by §2.2. — `implementation/db.py:70-75` (`iso()`), `implementation/db.py:139-151` (`public()`), `implementation/routes/system.py:21` (`current_utc`).

No other PRD edit was made.

## Per-edit pre-edit search log

**Edit 1 — §2.4 instant rendering**
- **(a) Subject:** the rendered form of every timestamp/instant the API emits, in every field and on every endpoint (stamped, echoed, derived, and the clock read-back).
- **(b) Impl paths enumerated (read/grepped):**
  - `db.py:70-75` `iso()` — the single formatter: `astimezone(utc)` then `"%Y-%m-%dT%H:%M:%S" + ".%03dZ"` with `microsecond // 1000` (truncation, not rounding); returns `None` for `None`.
  - `db.py:139-151` `public()` — the single record serializer; converts *every* top-level `datetime` value through `iso()`. Verified `public()` does not recurse, and that no nested structure carries a datetime (`waivers` entries hold only `item_code`/`justification`/`waived_by_user_id`; `included_change_ids`/`missing_items` hold strings).
  - Grepped every `object_response`/`array_response` callsite in `routes/` (trains, system, changes, docs, releases, deployments, flags, incidents): all 14 list endpoints use `[db.public(x) ...]`; every single-resource response uses `db.public(...)`. The only two non-`public()` bodies are `routes/system.py:21` (`{"current_utc": iso(db.now())}` — uses the same `iso()`) and `services/cascade.py:386-394` (cleanup-sweep summary — contains no timestamp at all, so the new sentence makes no claim about it).
  - Grepped every timestamp-bearing field assignment: `routes/trains.py:39,95-97,107,108`, `routes/system.py:51,52,55`, `routes/incidents.py:35,42,98`, `routes/releases.py:112,175`, `routes/docs.py:38,39,72,110,182`, `routes/flags.py:39,47,48,137,138,213,247,317`, `routes/deployments.py:81,82,91,92,166,212,213,289,296`, `services/cascade.py:42,140,269,289,358`. All are `datetime` objects (from `now()`, `timedelta` arithmetic, or `validate.req_dt`/`opt_dt` → `db.parse_iso`) or `None` — never pre-formatted strings, so nothing escapes `iso()`.
  - `validate.py` `_dt`/`req_dt`/`opt_dt` + `db.parse_iso:78-88` — client input is normalised to aware UTC on the way in, which is why echoed values come back in UTC regardless of the supplied offset.
  - `response.py:16-18` `_stamp()` — `api_request_timestamp` uses the host wall clock, not the logical clock, and renders with the same three-digit format. This is why the sentence sets it aside rather than folding it into the §2.4 list.
  - Cross-checked the non-rendering Step 7 items to confirm they need no PRD edit: `services/calc.py:298-323` `flag_stale_debt` (orphan +15, `debt > 0` → `WARNING`, seven-day lead) matches §3.6 verbatim; `services/cascade.py:303` sets `delivery_state="ABORTED"`, `verification_state="FAILING"` matching §3.7 hop one; §3.3 already states a new change begins `DRAFT` with null scores (the `fixtures.py` item was a fixture bug); `app.py` `threaded=True` and the `conftest.py` fixture scope have no PRD-observable semantics.
- **(c) Wording adjustments made to keep all enumerated paths consistent:**
  1. Scoped the claim to "every instant that appears in a response body" rather than "every timestamp field", so the cleanup-sweep summary (no timestamps) and the request-side `to_iso8601` input (never echoed) are not mis-described.
  2. Carved out `api_request_timestamp` explicitly ("Setting … aside, whose format §2.2 already pins") so the paragraph's placement inside §2.4 cannot be read as claiming that field is drawn from the logical clock — it is not (`response.py:16`).
  3. Said "truncated to millisecond precision", not "rounded", to match `microsecond // 1000`.
  4. Added "converted to UTC first" to cover `parse_iso`/`astimezone` normalisation of non-UTC client offsets, and "A timestamp field that holds no value is rendered as null" to cover `iso(None)` and the many fields initialised to `None`.
  5. Named the echoed and derived fields parenthetically rather than writing a closed universal list, so the rule stays true for any timestamp field on any path Step 7 never exercised.

## Step 9: Complete PRD — 2026-09-02T00:18:00.000Z

`workspace/PRD_COMPLETED.md` is written: a minimal in-place patch over `PRD_FINALIZED.md`, no new sections, no new paragraphs, no lines added or removed.

**Stats**
- PRD_FINALIZED.md: 476 lines / 107,415 chars → PRD_COMPLETED.md: 476 lines / 115,149 chars (**char delta +7,679**)
- 31 paragraphs revised in place: **24 ambiguity-pins**, **8 mismatch-revisions** (§3.7's environment paragraph carries one of each)

**Changes** (impl paths relative to `workspace/implementation/`)
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 upper-alnum chars — response.py:12-13
- §2.2 — revise — ambiguity — `api_request_timestamp` is read from the host wall clock, not the logical clock — response.py:16-18
- §2.3 — revise — ambiguity — `created_at` ties broken by creation sequence; `total_count` is post-filter/pre-page; `has_more` = offset+returned < total_count — db.py:154-155, response.py:35
- §2.3 — revise — ambiguity — an out-of-set filter value matches nothing rather than 400; `direction` other than `INCOMING` means `OUTGOING` — changes.py:136, flags.py:66-69
- §2.5 — revise — ambiguity — `version` is 1 on creation — db.py:113
- §2.6 — revise — ambiguity — computed fractional values render as plain integers when integral; client-supplied percentages echo verbatim — db.py:91-99
- §2.7 — revise — **mismatch** — planning does *not* supersede a still-`PLANNED` rung; the new step just takes the next `step_index` — flags.py:127-141
- §2.8 r3 — revise — ambiguity — absent/empty body = `{}`; `null` on an optional input = omitted (default applies), `null` on a required input = missing; undeclared fields ignored — validate.py:15-31
- §2.8 r9 — revise — **mismatch** — soak-start's flag-`state` check belongs to rank 9, evaluated before the linked-change check and thus before ownership — flags.py:172-190
- §2.10 — revise — ambiguity — a re-write that changes nothing is not a mutation (no `updated_at`/`version` move); one hop = one version bump however many fields — db.py:126-136
- §3.1 — revise — ambiguity — train `name` at most 80 characters — trains.py:22
- §3.2 — revise — **mismatch** — `readiness_score_projected` has no phase gate; even a `ROLLED_BACK` release recomputes on its triggers — changes.py:376-379
- §3.2 — revise — ambiguity — freeze-exception `justification` non-empty and unstored; a repeat grant is wholly inert (no count, no version) — releases.py:120-130
- §3.3 — revise — ambiguity — authoring a change is permitted in any release `phase` — releases.py:133-150
- §3.3 — revise — ambiguity — flag-linking checks no change/flag state and permits duplicate pairs — changes.py:149-168
- §3.4 — revise — **mismatch** — merge unblocks dependents *before* recomputing `rollback_plan_confirmed` and `readiness_score_projected` (one release mutation, blocked penalty already gone) — changes.py:344-350
- §3.4 — revise — ambiguity — withdrawal `reason` validated but not stored — changes.py:358
- §3.5 — revise — ambiguity — `soak_minutes` whole minutes ≥ 0; planning has no flag-`state` gate (incl. `ARCHIVED`) — flags.py:88-96
- §3.5 — revise — **mismatch** — start-soak precondition order pinned to impl (step → flag state → linked changes → ownership → cleanup → soaking → index → deployment) — flags.py:172-208
- §3.5 — revise — **mismatch** — apply order (flag state before ownership); apply recomputes `stale_debt_points` **and** `cleanup_state` in one mutation, stamps no `last_sweep_at`, never pauses/voids/recomputes readiness; exposure 100 is the integer 100 — flags.py:228-262
- §3.5 — revise — ambiguity — pause `reason` not persisted — flags.py:272-277
- §3.5 — revise — ambiguity — archival leaves `kill_switch_engaged`, `current_exposure_pct` and any `SOAKING` step untouched — flags.py:314-323
- §3.6 — revise — ambiguity — "affected flag" = one the sweep actually altered or paused; a repeat sweep at an unchanged clock recomputes no release — cascade.py:357-389
- §3.7 — revise — **mismatch** + ambiguity — `last_deployment_end_at` recomputed only on completion or deployment rollback (reservation and abort leave it); a blackout needs *both* endpoints — deployments.py:296, cascade.py:292, deployments.py:136
- §3.7 — revise — ambiguity — `abort_error_rate_pct` any number > 0, `abort_latency_p95_ms` whole ms ≥ 1 — deployments.py:44-45
- §3.7 — revise — ambiguity — sample `latency_p95_ms` whole ms; ingestion has no delivery-state precondition — deployments.py:148-179
- §3.7 — revise — ambiguity — canary analysis has no delivery-state or strategy precondition — deployments.py:196-206
- §3.7 — revise — ambiguity — `min_sample_count` 0 with no qualifying rows yields `PASS` / score 100 — calc.py:239-286
- §3.7 — revise — ambiguity — an `abort_triggered` verdict outside `IN_PROGRESS`/`CANARY_SOAK` still writes verdict, `verification_state` and `health_score` but runs no hop — deployments.py:229-239
- §3.7 — revise — ambiguity — deployment-rollback `reason` not persisted — deployments.py:306-307
- §3.9 — revise — ambiguity — `missing_items` in canonical item order; `waivers` in record order — calc.py:529-535
- §3.9 — revise — **mismatch** — waiver `justification` non-empty; `base_index` and item satisfaction come from the packet's stored snapshot (assembly, or a release-notes publication refresh), never recomputed live at waiver time — docs.py:137-159

Not changed (verified already uniquely pinned): the 50-error catalogue and its statuses, rank-4/5/6/7 not-found + uniqueness + concurrency wiring, all eight calculations (risk score, both readiness variants, canary verdict, stale debt, ladder geometry, note generation, linkage, completeness index), the freeze/unfreeze, cut, abort, rollback and sweep cascade hop orders, and §2.4 timestamp rendering.

## Step 7 addendum: canonical exit sweep under host contention — 2026-09-02T01:50:00.000Z

The Step 7 subagent exited on its own criterion, and Steps 8 and 9 are complete. This
addendum records the orchestrator's attempt to land the canonical exit artifact
(`workspace/implementation/results.{1..8}.json`, all eight rounds `passed == total == 121`)
and the reason that specific artifact is not obtainable on this host right now. It changes
no test, no helper, and no implementation file.

**Root cause of every non-passing entry.** `prd-bench-local-run --isolation per-test-server`
restarts the server before each of the 121 tests, and its teardown
(`prd_bench_local_runner/pytest_plugin.py:46` `_kill_port`) shells out to
`lsof -ti:PORT -sTCP:LISTEN` under a **hard-coded 5-second** `subprocess.run(timeout=5)`
with no environment override. `lsof` answers that question by resolving every
`/proc/<pid>/fd/*` symlink of every process. This host is shared with roughly 60 sibling
pipelines: ~5,000-6,000 processes, 69-234 concurrent `prd-bench-local-run` port-registry
holders, 1-minute load average 176-400 (peaked at 2885 earlier in the run). Measured here:

| call | load ~180 | load ~300-400 |
|---|---|---|
| `lsof -ti:P -sTCP:LISTEN` | 0.65 - 1.5s | 1.2 - 8.5s |
| `ss -H -ltnp 'sport = :P'` | — | 2.8 - 4.5s |
| `ss -H -ltn 'sport = :P'` (no `-p`) | — | 0.4 - 1.1s |

A round needs 121 consecutive sub-5s teardowns, so at load ~250-300 a third to a half of
them blow the budget; the `TimeoutExpired` propagates out of `pytest_runtest_setup` and
pytest records a SETUP ERROR against the *following* test.

**Evidence that the artifacts are correct.** Aggregating every complete round produced
during and after Step 7 (21 archived files under `/tmp/t2283_archive/` plus the
orchestrator's own re-runs):

- 24 complete rounds parsed, **2,904 individual test executions**.
- **121 of 121 distinct tests passed in at least one round** — no test never passes.
- 1,209 non-passing executions, classified exhaustively with **zero left unclassified**:
  - 1,204 — `_kill_port` 5s subprocess timeout (`subprocess.TimeoutExpired: Command
    'pids=$(lsof -ti:PORT -sTCP:LISTEN ...)' timed out after 5 seconds`);
  - 3 — `Failed: Timeout (>30.0s) from pytest-timeout` on *setup*, i.e. the restart poll
    starved out before the server answered;
  - 2 — transport reset mid-request (`ConnectionResetError(104)`,
    `RemoteDisconnected`), the two entries the runner labelled `failed` rather than `error`.
- **Zero assertion failures.** An independent scan of all 1,209 non-passing entries for
  `AssertionError` / `assert` in the message found 0 hits. Not one non-passing entry carries
  a traceback out of test or implementation code.

The two `failed`-labelled entries deserve the explicit note that they are *not* assertion
failures: `test_the_satisfied_item_is_unprocessable_while_the_old_packet_is_a_conflict`
(archived 21:02) and `test_neither_refusal_moves_a_delivery_state_or_the_occupancy_counter`
(archived 21:22) each lost their HTTP connection once, and each passed in other rounds.

**What was tried, and rejected on measurement.** A scoped `lsof` replacement was written at
`/tmp/orch2283/bin/lsof` (PATH-local to the sweep only; the shared runner source was left
untouched because ~60 other pipelines depend on it). It answers the identical query by
reading the LISTEN socket inode from the kernel socket table and matching it against only
the descendants of its own ancestors — the per-test servers are `Popen` children of the
pytest process, so the candidate set is a handful of pids instead of all ~5,000 — with a
fail-safe that execs real `lsof` rather than ever under-reporting. It was verified to return
byte-identical pids to real `lsof`. It was then **rejected**: successive versions measured
3.7-10.0s (ss+grep+cut+sort+ls), then 2.2-6.1s (two spawns, pure bash builtins otherwise),
against real `lsof`'s 0.65-4.3s in the same windows. The cost is host-wide scheduling and
I/O jitter, not the `/proc` walk — real `lsof` itself swung 0.65s to 4.3s while the load
average *fell* from 182 to 176. It is not in use, and no sweep result above came from it.

**Remaining gap, stated plainly.** `workspace/implementation/results.{1..8}.json` with
`errors == 0` on all eight rounds was not obtained. It requires the host to be quiet enough
that 968 consecutive `lsof` calls each finish inside 5s, and the box never dropped below a
1-minute load average of about 190 (it sat at 250-400 for most of the window and plateaued
around 220-240 thereafter). The best complete round achieved was `pass=108 fail=0 err=13`. The load-gated supervisor's
own five rounds show the error count tracking host load and nothing else, with `fail=0`
throughout: `err=50` at loadavg 242, then 35, then **13**, then 25, then 24 as the 1-minute
load drifted 242 -> 206 -> 233 and the port-registry holder count fell 234 -> 153 -> 176. The
sequential, load-gated supervisor (`/tmp/orch2283/sweep_supervisor.sh`, rounds one at a time
rather than 8-up to cut this pipeline's own contribution 8x, attempts gated on
loadavg <= 250) is the mechanism; it is bounded by host load, not by anything in the task
artifacts.
