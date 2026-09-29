# Worklog — task_2297_workplace_violence_prevention_threat_management

## Step 1: Create task directory — 2026-09-01T14:46:08.393Z

Created `tasks/task_2297_workplace_violence_prevention_threat_management/` and `workspace/` subdirectory (bash only).

## Step 2: Generate scaffold — 2026-09-01T16:45:44.242Z

All three scaffold artifacts are complete and pass `scaffold_lint.py` with `VERDICT: clean lint`.

## Files written to `/home/ubuntu/github/CodingPRD/tasks/task_2297_workplace_violence_prevention_threat_management/`

| File | Lines | Top-level key(s) |
|---|---|---|
| `SCAFFOLD.yaml` | 2482 | §1.0–§1.7 only (no `scaffold_difficulty_design`, no `scaffold_corner_design`) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 3611 | `scaffold_difficulty_design` (§1.8) |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 9222 | `scaffold_corner_design` (§1.9) |

## SCAFFOLD.yaml surface (harder than Expert)

- **Scenario**: stored verbatim (byte-verified against the supplied text).
- **13 entities**: Worksite, WorkArea, PreventionPlan, HazardAssessment, Employee, TrainingModule, TrainingAssignment, IncidentReport, ThreatCase, TeamAssignment, CaseAction, ViolentIncidentLogEntry (`common_fields: false`, append-only, self-FK `supersedes_entry_id`), Drill.
- **9 state machines / 43 transitions** — cyclic (DELIBERATION↔ASSESSING, capped at 3 rounds), parallel dimensions on IncidentReport (triage vs. retaliation), guarded transitions (plan `compliance_posture`), plus 2 `concurrency_rules` (OCC on `PreventionPlan.version` and `Employee.version`).
- **7 calculations**: `hazard_score` (weighted_scoring, SCREENING/VALIDATED dual variant), `incident_severity_classification` (threshold), `behavioral_risk_score` (weighted_scoring, INTERIM/CONSENSUS dual variant), `team_quorum_evaluation` (aggregation), `plan_compliance_metrics` (aggregation), `inspection_readiness_score` (threshold, rounded-subtotal band key), `protective_coverage_gap_hours` (interval_merge).
- **35 ordered validations**, **57 endpoints** (incl. `/_clock/set_current_utc` and an 8-step `/_ops/daily-run`), **57 error codes**, **10 roles** under `segregation_of_duties` (7 `entity_backed:Employee`, 3 `opaque`).

## Design files

- **§1.8**: 9 rule_ids × 2–3 instances = **21 instances** (dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2).
- **§1.9**: **95 instances** across all nine guide sections — 77 full `test_recipe` instances + 18 `excluded_because` stubs (entities 12, state_machines 19, calculations 13, validations 16, endpoints 6, errors 14, rbac 8, cross_cutting_complexity_layers 6, consistency_model 1).

Verified beyond the linter: all 116 instance names unique across the union of both design files; every `excluded_because.difficulty_instance` resolves to a real §1.8 `rule_id / name` pair; every `claim_type` is a literal row from `references/claim-extraction-guide.md` (nothing invented); 2309 setup/trigger calls conform to §1.5; no forbidden concurrency vocabulary in any file. Two consistency fixes were applied to SCAFFOLD.yaml this session: `inspection_readiness_score` step 4 now derives `compliance_posture` from both `PreventionPlan.status` and `Worksite.high_risk_flag` (matching the entity field definition), and its `inputs:` list was updated to match.

## Step 3: Copy shared files — 2026-09-01T16:46:02.689Z

Copied `./INSTRUCTION.md` to `tasks/task_2297_workplace_violence_prevention_threat_management/workspace/INSTRUCTION.md` (bash only).

## Step 4: Generate PRD — 2026-09-01T17:02:14.195Z

PRD generated and verified.

## Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_2297_workplace_violence_prevention_threat_management/workspace/PRD.md` — **483 lines**.

## Sections covered

- **§1 Introduction** — 3 paragraphs derived from the scenario seed; names the two design commitments (segregation of duties, anti-retaliation primacy).
- **§2 Global Specifications** — 11 subsections: 2.1 RBAC (all 10 roles, `X-User-ID`/`X-User-Role`, entity-backed vs. opaque identity, 3 ownership rules), 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`, verified), 2.3 Pagination + all list filters, 2.4 common fields and the append-only log exception, 2.5 the full 35-step rejection precedence chain with explicit outranking statements, 2.6 the 13 path variables and their 404 codes, 2.7 both OCC version guards, 2.8 precision/rounding discipline, 2.9 logical clock (`2026-08-01T00:00:00Z`) + the 8 pinned sweep steps and 8 output counters, 2.10 posture/cascade/reconciliation, 2.11 the three conserved counters.
- **§3 Business Logic** — 9 subsections covering all 43 transitions across 9 state machines, all 7 calculations with every constant, all 35 validations, both OCC rules, and every endpoint `side_effects` entry.
- **§4 Endpoint Definitions** — 57 rows, exactly 4 columns, preceded by the status-code paragraph.
- **§5 Error Code Catalogue** — 57 rows, exactly 2 columns.

## Hard Contract results

**Contract 1 — Field-Name Coverage: PASS.** 164 required names (all entity fields + all endpoint inputs + all path params + both OCC fields) checked against backticked tokens in the PRD; **0 missing**. Also verified: all 57 error IDs, all 10 role names, all enum values across every entity field, and all 7 calculations' constants appear in the prose.

**Contract 2 — Rule Coverage: PASS.** All 43 transitions verified present with from/to states backticked; all 35 validation priorities rendered in strict ascending order with their `applies_to` scopes stated (posture-frozen on case-action create *and* convene; the mismatch family on case-actions/hazard-assessments/training-assignments; ownership on training-complete *and* retaliation-updates with the HRPartner exemption; segregation on activate *and* validate); all cross-entity cascades rendered (plan activation supersede chain, the 4-link decide cascade, the 5-consequence separation cascade, revoke/expire compensations, the auto-generated `SAFETY_PLAN_REVIEW`); sibling-branch symmetry stated explicitly for all 7 multi-arm transitions; all field-level defaults rendered per entity.

**Contract 3 — §3 Path Purity: PASS.** 315 distinct backtick tokens in §3; **0** begin with `/`, **0** are bare HTTP methods, **0** combine method+path. All endpoint references in §3 use state-transition, role+verb or capability framing.

Additional scans: no pseudocode operators (`==`, `>=`, `+=`, `min(`, `max(`, `round(`, `floor(`, `&&`, `||`) anywhere in §1–§3; no fuzzy hedges.

## Coverage notes (scaffold ambiguities resolved)

1. **`mitigation_verified` threshold conflict.** `HazardAssessment.mitigation_verified` says "`barrier_installed` true OR `mitigation_credits >= 2`", while the `hazard_score` calculation says "`mitigation_credits >= 1` or `barrier_installed`". No fixture distinguishes them. The PRD follows the **calculation** ("at least one mitigation credit, or a barrier installed") while keeping the entity's requirement that the assessment be VALIDATED.
2. **Stale "(1 decimal)" annotations.** `HazardAssessment.hazard_score` and `ThreatCase.interim_risk_score` are annotated 1 decimal, but both calculations declare 2-decimal round-half-up and their worked values show two decimals. The PRD treats **2 decimals** as authoritative throughout.
3. **Three preconditions have no error ID in the scaffold.** The PRD assigns the most plausible declared code and states it deterministically: submit with no work area on the worksite → `ERR_PLAN_INVALID_STATE`; validate against a SUPERSEDED plan → `ERR_PLAN_INVALID_STATE`; ALLEGE on an anonymous report (no `reporter_employee_id`) → `ERR_RETALIATION_INVALID_STATE`. Also, `occurred_at` after the logical clock is rendered as `ERR_INVALID_REQUEST` (priority-4 range check).
4. **Sweep step numbering.** The `PreventionPlan` ACTIVE→REVIEW_DUE transition trigger cites "daily-run step 8", but the endpoint's own `side_effects` list places it at step 7 with rescoring at step 8. The PRD follows the endpoint list (authoritative) and states that steps 7 and 8 never reorder.

## Step 5: Generate unit tests — 2026-09-01T19:51:13.194Z

The suite is complete. Final state:

## Files created

**`test_helpers/` (9 files, infrastructure — Stage 1)**
`__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py` — all under `/home/ubuntu/github/CodingPRD/tasks/task_2297_workplace_violence_prevention_threat_management/test_helpers/`.

**`test_suite/` (conftest + 21 domain-language modules, 119 tests)**
- Queue A (depth, `test_01`–`test_09`): 42 tests
- Queue B (breadth, `test_10`–`test_21`): 77 tests
- Files added in this final stretch: `test_20_role_gate_and_identity_boundaries.py` (7 tests, `rbac`) and `test_21_concurrency_tokens_counter_reconciliation_and_immediate_cascades.py` (5 tests, 4 × `cross_cutting_complexity_layers` + 1 × `consistency_model`).

## Coverage against the two design indices

| Queue | Instances | Translated | Tests |
|---|---|---|---|
| A — §1.8 Difficulty | 21 | 21 (all, ≥2 tests each) | 42 |
| B — §1.9 Corner (non-stub) | 77 | 77 (all) | 77 |
| B — §1.9 Corner stubs | 18 | 0 (by design) | 0 |

Verified mechanically: every non-stub corner instance name resolves to exactly one test tag, no stub is tagged, no tag points at a non-existent instance, every docstring carries exactly one `Design:` line as its last line, and every `PRD: "…"` string greps verbatim against `workspace/PRD.md` (0 missing). `python -m pyflakes test_suite/*.py` → clean; all 21 modules import successfully; no `skip`/`skipif`/`xfail` anywhere.

## Instances skipped, grouped by reason

The only untranslated instances are the **18 `excluded_because:` stubs** in `SCAFFOLD_CORNER_DESIGN.yaml`, each of which names the §1.8 instance that already carries its claim and ships no `test_recipe` (state_machines 3, calculations 3, validations 3, errors 6, rbac 1, cross_cutting 2). No instance was dropped for lack of PRD grounding — the PRD-first filter passed for every non-stub instance.

## Design-vs-PRD adjudications made in this last stretch (PRD wins)

- `anonymous_cannot_read_any_incident_report_it_filed`: design pins `severity_points 6` for a TYPE_3_COWORKER / no-weapon / no-injury filing; §3.5's typology table gives **12** (still `MINOR`, `log_required` false). Asserted 12.
- `compliance_auditor_cannot_write_any_row`: design's `inspection_readiness_score` → real field `readiness_score` (79.90); its claim that a `ComplianceAuditor` "may omit `X-User-ID`" contradicts §2.1 (only `Anonymous` may), so the auditor headers carry an opaque operator id and the test asserts 403-not-401 instead.
- `decide_response_body_already_carries_every_cascaded_value`: design asserts `retaliation_status SUBSTANTIATED` / `triage_status ESCALATED`; §3.7's cascade moves **`triage_status` `ESCALATED` → `SUBSTANTIATED`** and leaves retaliation `NOT_ALLEGED`. Asserted the PRD values.
- `expected_plan_version_guard_…`: design asserts `WorkArea.current_hazard_score == 80.00`, but the governing plan is `DRAFT`, and §3.1 says the field stays null unless the worksite has an `ACTIVE`/`REVIEW_DUE` plan. Asserted `None`.
- `control_tier` written in full as `TIER_1_ENGINEERING` (design abbreviates to `TIER_1`).
- `training_expiry_fires_at_exactly_the_clock`: the standard 11-worker programme is all-`ADMIN`, which would sink `training_compliance_pct`; the test builds a local single-learner worksite (three `SECURITY` role-holders + one `ADMIN` learner) so the design's 100.00 → 0.00 swing and the 79.90 → 52.80 readiness drop are reachable.

## Step 6: Generate implementation — 2026-09-01T19:51:13.194Z

Implementation complete and verified end-to-end.

## Files (22, all under `.../workspace/implementation/`)

Top level: `start.sh` (now `chmod +x`), `requirements.txt` (`flask>=2.0`), `app.py`, `db.py`, `errors.py`, `response.py`, `middleware.py`, `validation.py`, `constants.py`, `calc.py`, `sync.py`, `serialize.py`
`routes/`: `__init__.py`, `common.py`, `worksites.py`, `plans.py`, `people.py`, `reports.py`, `cases.py`, `actions.py`, `logbook.py`, `ops.py`

## Endpoints: 57 — exact match to PRD §4

I diffed the PRD §4 table against `app.url_map` programmatically: 57 method+path pairs in the PRD, 57 registered, **zero missing and zero extra**. (Correcting an earlier note in my own working log: the PRD has 57, not 58 — the scaffold's count was right.)

## State machines covered (10)

PreventionPlan (`DRAFT→IN_REVIEW→ACTIVE→REVIEW_DUE`, `→SUPERSEDED`, return-for-revision), HazardAssessment (`DRAFT→VALIDATED→SUPERSEDED`), Employee (`ACTIVE→SEPARATED` with escort/restriction ledger release + cascade revoke), TrainingAssignment (`ASSIGNED→COMPLETED/EXPIRED`, failed attempts still counted), IncidentReport triage (`NEW→TRIAGED/ESCALATED/CLOSED_NO_ACTION→SUBSTANTIATED`), IncidentReport retaliation (`NOT_ALLEGED→ALLEGED→UNDER_REVIEW→SUBSTANTIATED/UNSUBSTANTIATED`), ThreatCase (`OPEN→ASSESSING→DELIBERATION→MONITORING→CLOSED` plus the `NO_THREAT` short-circuit and reassess round loop), TeamAssignment (`ASSIGNED→RECUSED/RELEASED`), CaseAction protective (`SCHEDULED→ACTIVE→EXPIRED/REVOKED`) and post-incident (`PENDING→OVERDUE→COMPLETED`), Drill (`SCHEDULED→EXECUTED/MISSED`).

## Calculations covered (7)

Hazard score (6 terms, lone-worker floor, mitigation credits/barrier, tier), incident severity + `log_required`, interim risk, consensus risk (per-ballot share rounded **before** summation, 0.35/0.65 blend), plan compliance metrics (4 percentages + `unmitigated_hazard_count` + `overdue_action_count`), 4-step inspection readiness (subtotal rounded before band selection), protective coverage gap (clip → sort → merge adjacent → gap hours).

## Verification

Two suites written to `/tmp` only (nothing added to the task dir): `/tmp/smoke2297.py` (291 assertions) run over real HTTP through `start.sh` via `/tmp/http2297.py`, plus `/tmp/unit2297.py` for calc boundaries. **291/291 and all unit checks pass; 162 server requests, zero 500s, no tracebacks.**

Pinned PRD fixtures reproduced exactly: hazard 64.00 TIER_1 → 39.00 TIER_2 after 3 credits + barrier; lone-worker floor 45.00; severity 50/CRITICAL and 24/SERIOUS; interim 42.00 and 14.40; consensus 60.94 HIGH with per-seat shares 9.83/24.56/12.68/7.85/16.22, and 27.79 MODERATE with 10.91/9.47/8.24/6.38; coverage 336.00 → 168.00 → 0.00 (adjacent merge) → 312.00 (clipped) with `RESTRAINING_ORDER_SUPPORT` excluded; hazard coverage 100.00/66.67/33.33; log completeness 75.00/87.50/100.00; readiness 74.999 → subtotal 75.00 → ADEQUATE → penalty 4.50 → score 70.50 → not ready at RESTRICTED (85.00 gate). Error-precedence spot checks also pass, including role-outranks-existence (`ERR_UNAUTHORIZED` before `ERR_WORKSITE_NOT_FOUND`), `ERR_OPEN_ACTIONS_BLOCK_CLOSE` before the 8-element log gate, escort ±30-min symmetric buffer, and the `occupancy_cap` 4 → no concurrent restriction ceiling.

One PRD subtlety worth flagging: when `protected_employee_id` is null but a window exists, `coverage_gap_hours` is still measured (336.00) and only `protection_status` stays `NOT_APPLICABLE` — §3.7 zeroes the gap only when `protection_window_start` is null. The code follows the PRD.

## How `start.sh` handles `$PORT`

`start.sh` never touches `$PORT` itself — it just inherits it and `exec`s, so `app.py` reads `int(os.environ.get("PORT", "10000"))` and binds `0.0.0.0:$PORT` with `threaded=True, use_reloader=False`. Because of `exec`, the PID the harness spawns *is* the Flask server, so the per-test kill lands on the right process with no orphan; `cd "$(dirname "$0")"` makes it cwd-independent, and the dependency install is guarded by an import probe so concurrent per-test reboots don't contend on pip. Every boot starts from a bare in-memory store (13 empty dicts, logical clock `2026-08-01T00:00:00Z`) — confirmed by a fresh boot returning an empty list envelope and `ERR_UNAUTHORIZED` for any `X-User-ID`, i.e. no entity is seeded anywhere. Storage is dict-only: a repo-wide grep found no `sqlite`, `pickle`, `shelve`, or any file `open(...)`. `pyflakes` is clean.

Isolation constraints were honoured: I never read `test_helpers/`, `test_suite/`, any sibling task directory, or the `SCAFFOLD_*_DESIGN.yaml` files.

**Orchestrator note:** Steps 5 and 6 were launched sequentially rather than concurrently. Step 6's subagent was given an explicit hard constraint forbidding any read of `test_helpers/` or `test_suite/` (which existed on disk by then), and it reported honouring that constraint.

## Step 7: Run tests and iterate — 2026-09-01T23:32:31.000Z

Work is complete. Here is the exit summary.

## Summary

### Iterations run
- **1 diagnostic baseline** + **2 fix batches**, verified with **3 full per-test-server-isolated suite runs (119/119 passed each)** and **5 completed 8-round parallel sweeps** (plus one that the background harness killed mid-run).
- Post-fix, **all 40 sweep rounds reported zero assertion/logic failures**. Every non-passing entry in every round is one environmental error, identical string across 594–681 occurrences per sweep:
  `subprocess.TimeoutExpired: Command 'pids=$(lsof -ti:N -sTCP:LISTEN …); … kill -9 …' timed out after 5 seconds`
  This is `prd_bench_local_runner/pytest_plugin.py::_kill_port` (`subprocess.run(..., timeout=5)`), which `per-test-server` isolation invokes in `pytest_runtest_setup` before **every** test. The host is at load 375–420 on 32 cores with ~490 concurrent `prd-bench-local-run` processes from ~39 other pipelines; a bare `lsof -ti:PORT -sTCP:LISTEN` measured **4.17 s** wall on this box, so the harness's own 5 s budget blows roughly half the time regardless of content. The remaining stragglers (`pytest-timeout >30s`, `ChunkedEncodingError`, `RemoteDisconnected`) are the same saturation plus the harness's `kill -9` racing an in-flight response. Nothing in `implementation/`, `test_suite/` or `test_helpers/` can influence any of it, and the union of genuinely failing tests is **empty**: 119/119 pass under identical per-test-server isolation (fresh server booted per test on its own port), reproduced three times, including at 16-way parallelism under load 400.

### Tests deleted
No whole test was deleted. Six **assertions** were removed under STEP 1a (PRD silence) / STEP 1c (partial coverage):
- `test_suite/test_11_report_and_case_state_machines.py` — four assertions on `report["triaged_at"]` (lines ~90, 108, 122, 123). **Category: PRD-silent field.** `triaged_at` appears nowhere in `workspace/PRD.md` (nor in SCAFFOLD.yaml); §3.5's initial-state sentence names only `triaged_by_employee_id` and `retaliation_claimant_employee_id`. The surrounding claims (single-shot triage, `ERR_REPORT_INVALID_STATE` replay, surviving `triaged_by_employee_id`) are retained.
- `test_suite/test_10_entity_contracts.py:63-64` — `created_at == "2026-08-01T00:00:00Z"` / `updated_at == …`. **Category: PRD-silent derivation + direct PRD contradiction.** PRD §2.4 verbatim requires `created_at` to carry *three fractional digits* and never says either field is read from the logical clock (§2.9 scopes the clock to "deadlines, expiries, retention dates and protection windows"). `assert_common_fields(worksite, expected_version=1)` still enforces shape.

### Fixes applied to `test_helpers/`
- `fixtures.py` → `cast_standard_ballots`: stopped overwriting `ctx["case"]` with the ballot response. `POST /threat-cases/{id}/ballots` returns the caller's **TeamAssignment** seat, so the second iteration was POSTing to `/threat-cases/<seat_id>/ballots` → `404 ERR_THREAT_CASE_NOT_FOUND` in setup (**root cause of 42 failures**). Seats are now recorded under `ctx["ballot_seats"]` and the case re-read via `read_case`.
- `fixtures.py` → `setup_monitoring_case_with_escort`: the fixture activated a plan and then called `setup_monitoring_case` without ever filing/escalating a report or opening a case → `KeyError: 'case'` (**7 failures**). Now chains `setup_filed_report` → `setup_escalated_report` → `drive_case_to_monitoring`.
- `factories.py` → `_apply`: also drops keys whose value is the `OMIT` sentinel when it arrives as a builder's *positional* argument, so `build_prevention_plan(OMIT)` expresses "omit the required `worksite_id`" instead of raising `TypeError: got multiple values for argument 'worksite_id'`.

### Fixes applied to `test_suite/`
- `test_05_case_deliberation.py` (~200): asserted the round-2 auto-advance against a fresh `GET /threat-cases/{id}` rather than the ballot response; same content asserted (`status="DELIBERATION"`, `ballot_count_current_round=5`).
- `test_11_…py` (`_minor_case_in_deliberation`, `test_the_last_ballot_of_the_round_advances_the_case_on_its_own_call`): same ballot-response-is-not-the-case correction.
- `test_06_decision_cascade.py:74`: `read_worksite(api, ctx)` → `read_worksite(api, ctx["worksite"]["id"])` (helper takes an id; passing the whole context produced `GET /worksites/<dict>` → "No such route").
- `test_06_decision_cascade.py:85`: `unmitigated_hazard_count` 0 → **1**. PRD §3.4: "A `TIER_1_ENGINEERING` assessment whose `mitigation_verified` is false is an unmitigated engineering hazard, and the plan's `unmitigated_hazard_count` is the number of such assessments among its non-`SUPERSEDED` rows." The standard fixture's assessment is 64.00 / `TIER_1_ENGINEERING` / unverified, so the PRD-faithful value is 1 — as the very next assertion in the same test already implied (`penalty_points=4.80` = `80.00 × 0.06 × 1`).
- `test_08_case_action_preconditions.py` (both lapsed-escort tests): `refresh_interval_days=3` violated PRD §3.4's "must lie between 30 and 1095", so a PRD-faithful server correctly rejected the fixture. Changed to the PRD-legal minimum **30**, with `expires_at` `2026-08-31T00:00:00Z` and the clock moved to `2026-08-31T00:00:00Z` (PRD: "`expires_at` is at or before the clock"). The escort booking still sits inside the protection window, so the test still proves `ERR_ESCORT_NOT_QUALIFIED` rather than a window error.

### Fixes applied to `implementation/`
- `workspace/implementation/db.py`: split the datetime formatter. New `fmt_ms()` keeps the always-three-fractional-digits rendering and is now what `real_now_iso()` uses for `created_at`/`updated_at` (PRD §2.4 verbatim). `fmt_dt()` — used only for clock-derived domain instants (`review_due_date`, `expires_at`, `protection_window_end`, `retention_expiry_date`, auto-action `due_at`) — now renders those instants the way PRD §2.9 renders the logical clock itself (`2026-08-01T00:00:00Z`), emitting a fractional part only when one exists. Previously these came back as `…T00:00:00.000Z`, which no longer matched the clock the PRD pins verbatim. No endpoint, field, side effect or seeded data was added; storage remains in-memory dicts only.

### One caveat, stated plainly
I could not obtain a sweep in which all 8 rounds report `passed == total`, and I do not want to imply otherwise. The blocker is the harness's 5-second `lsof` port-cleanup budget on a host running ~490 concurrent runner processes; it is content-independent and outside the task artifact. If the sweep is re-run on an idle (or even moderately loaded) host, the suite should come back 119/119 in all 8 rounds — that is exactly what per-test-isolated execution shows here, three times over. My temporary diagnostic runner and all `results.*.json` files have been deleted; the task directory now contains only the benchmark artifacts.

### Orchestrator's independent verification of the Step 7 caveat

The orchestrator re-ran the full 8-round parallel sweep itself and confirmed the subagent's diagnosis mechanically. Sweep A (2026-09-01T23:32Z → 2026-09-02T00:00Z, host load 408, 499 concurrent `prd-bench-local-run` processes from other pipelines, 3759 processes on a 32-core box):

| round | total | passed | failed | errors |
|---|---|---|---|---|
| 1 | 119 | 29 | 0 | 90 |
| 2 | 119 | 30 | 0 | 89 |
| 3 | 119 | 26 | 0 | 93 |
| 4 | 119 | 57 | 0 | 62 |
| 5 | 119 | 51 | 0 | 68 |
| 6 | 119 | 22 | 0 | 97 |
| 7 | 119 | 38 | 0 | 81 |
| 8 | 119 | 23 | 0 | 96 |

`failed == 0` in every round, and categorising all **676** non-passing records by `error_message` across all 8 rounds yields exactly **one** bucket: `kill_port lsof 5s timeout` (676/676). Zero assertion failures, zero logic failures, zero other error classes. The union of genuinely failing tests is therefore **empty**, corroborating the subagent's report.

Root cause confirmed at `prd-bench-local-runner/src/prd_bench_local_runner/pytest_plugin.py:55`, which hardcodes `subprocess.run(..., timeout=5)` around an `lsof -ti:PORT -sTCP:LISTEN` invoked from `pytest_runtest_setup` before **every** test under `per-test-server` isolation. Direct measurement on this host gave lsof wall times of **4.82 s / 5.65 s / 0.93 s** on three consecutive bare invocations — straddling the harness's own 5 s budget. The failure is content-independent: no change to `implementation/`, `test_suite/` or `test_helpers/` can affect it, and modifying the shared runner was out of scope (it is used concurrently by ~39 other pipelines).

## Step 8: Finalize PRD — 2026-09-02T00:05:35.000Z

Done. `PRD_FINALIZED.md` created with three inline edits.

## Line counts
- `PRD.md`: **483** lines / 13,521 words
- `PRD_FINALIZED.md`: **483** lines / 13,740 words
- **Line delta: 0 (+0.00%)** — all three edits are inline within existing paragraphs/bullets. Word delta +219 (+1.62%).

## Changes
- **§2.4 (Common Resource Properties)** — *revise* — `created_at`/`updated_at` are now pinned as read from **real server time, not the logical clock**, and as strictly increasing across successive writes (which is what makes §3.2 `plan_revision` and §3.7 prior-case-count ordering unambiguous). — `implementation/db.py:67-78` (`real_now_iso` → `fmt_ms`), `db.py:144-162`, `sync.py:35`
- **§2.9 (Logical Clock)** — *insert* — two rendering families pinned: instants **copied** off the clock (`activated_at`, `separated_at`, `assigned_at`, training `completed_at`, `ballot_submitted_at`, `protection_window_start`, drill `executed_at`, action `completed_at`, `revoked_at`) are stored verbatim as the clock reads; instants **computed by advancing another instant** (`review_due_date`, `expires_at`, `protection_window_end`, auto-action `due_at`, `retention_expiry_date`) render in the clock's own shape, fractional part only when non-zero; §2.4's three-digit rule does not extend to them. — `implementation/db.py:46-60` (`fmt_dt`), `routes/plans.py:146-147`, `routes/people.py:284-285`, `routes/cases.py:392-393`, `sync.py:250`, `sync.py:318`
- **§3.7 (Balloting)** — *insert* — the ballot call returns the caller's **updated team seat**, not the threat case; the case's refreshed counters/auto-advance require reading the case back. — `implementation/routes/cases.py:297` (`return single(seat)`)

## Per-edit pre-edit search log

**Edit 1 — §2.4 `created_at`/`updated_at`**
- (a) Subject: source and rendering of the system-managed timestamp block.
- (b) Enumerated/read: `db.py:35-43` (`fmt_ms`), `db.py:63-78` (`real_now_iso`, global `_last_ms` strict-monotonic guard), `db.py:144-153` (`new_row`), `db.py:156-162` (`new_log_row` — log entries also stamp `created_at` from `real_now_iso`), `db.py:165-167` (`in_order` sorts on `(created_at, _seq)`), `sync.py:35` (`assign` sets `updated_at = real_now_iso()`); grepped `store.clock`/`clock_raw`/`now_raw` across all modules to confirm **no** path ever writes `created_at`/`updated_at` from the logical clock; `response.py:16-25` (`api_request_timestamp` also wall-clock, so §2.2 stays consistent).
- (c) Adjustment: scoped the claim to `created_at`/`updated_at` only (not "all timestamps"), so §2.2's envelope timestamp and the verbatim-echoed client inputs (`occurred_at`, `starts_at`, `due_at`, `scheduled_at` via `validation.dt_field`) are untouched. Kept the ordering claim as "strictly increasing" rather than naming a tiebreak mechanism, since `in_order`'s `_seq` tiebreak is internal.

**Edit 2 — §2.9 clock-instant rendering**
- (a) Subject: how clock-sourced and clock-derived domain instants are rendered/stored.
- (b) Enumerated/read: every `fmt_dt` callsite (`routes/plans.py:147` `review_due_date`, `routes/people.py:285` `expires_at`, `routes/cases.py:393` `protection_window_end`, `sync.py:250` auto-action `due_at`, `sync.py:318` `retention_expiry_date`) and every `store.clock_raw` callsite (`routes/plans.py:146`, `routes/people.py:102,215,284`, `routes/cases.py:287,392`, `routes/actions.py:295`, `routes/logbook.py:184`, `sync.py:351`); `db.py:103-121` (`set_clock`/`now_raw` store the client string unmodified), `validation.py:126-140` (`dt_field` returns the raw string), `routes/ops.py:16-22` (clock setter echoes the raw string), `routes/logbook.py:53-104` (amendment **copies** `retention_expiry_date` from the target rather than recomputing), `db.py:128-141` (`plus_days`/`plus_minutes`/`plus_years`), `routes/ops.py:112-119` and `calc.dt_of` (the sweep parses these strings back, so either rendering compares identically).
- (c) Adjustment: originally drafted as "derived by advancing the clock" — `sync.py:318` derives `retention_expiry_date` from the report's `occurred_at`, not the clock, so the wording was widened to "computed by advancing some other instant". Also softened to "carries a three-digit fractional part only when the computed instant actually has one" rather than "never carries a fractional part", because `fmt_dt` falls through to `fmt_ms` when `microsecond != 0` (reachable when the clock is set with sub-second precision). The copied-instant list was left illustrative (em-dash aside) rather than declared exhaustive.

**Edit 3 — §3.7 ballot response resource**
- (a) Subject: which resource the `POST /threat-cases/{id}/ballots` response carries.
- (b) Enumerated/read: `routes/cases.py:251-297` (`cast_ballot` → `single(seat)`, HTTP 200), `routes/common.py:17-18` (`single` default 200), and the sibling case endpoints to confirm they do return the case and would not be mis-described: `convene_case` (`:245`), `reassess_case` (`:326`), `decide_case` (`:389,402,419`), `close_case` (`:470`), plus `create_team_assignment` (`:185`, seat at 201); §4 preamble (201-vs-200 rule) re-checked against the ballot's 200.
- (c) Adjustment: phrased as "the resource returned by a ballot call" and limited to the ballot endpoint, so the surrounding claims about the case auto-advancing on that same call (which the impl does perform before responding) and about every other case transition returning the case remain intact. No blanket statement about response bodies was introduced.

**Items deliberately not patched** (traced but no PRD-silence/mismatch): `triaged_at` — grep confirms the field exists **nowhere** in `implementation/`, so PRD silence and impl agree and no sentence was added; `unmitigated_hazard_count` 0→1 (`calc.py:346-350` already matches §3.3 verbatim); `refresh_interval_days` 30..1095 (`routes/people.py:155` already matches §3.4); `test_helpers` fixture repairs (`cast_standard_ballots` context clobbering, `setup_monitoring_case_with_escort` missing chain, `factories._apply` `OMIT` positional) — test-harness bugs with no PRD counterpart beyond Edit 3; `read_worksite` arity fix — test bug.

## Step 9: Complete PRD — 2026-09-02T00:16:05.000Z

All edits are in place as in-paragraph revisions — no new sections, no line-count change.

## Summary

**Files:** `workspace/PRD_FINALIZED.md` (483 lines, 101,160 chars) → `workspace/PRD_COMPLETED.md` (483 lines, 109,176 chars). **Char delta: +8,016.** 29 lines modified in place; heading structure byte-identical.

**Counts:** 32 changes — **29 ambiguity-pins**, **3 mismatch-revisions**.

### Changes

- §2.3 Pagination — insert — ambiguity — a non-integer `limit`/`offset` is also `ERR_INVALID_REQUEST` — `validation.py:160-175`
- §2.4 Common Properties — insert — ambiguity — `version` is minted at 1 and the create's own derived-field pass never lifts it to 2 — `db.py:151`, `sync.py:38-40`
- §2.4 Common Properties — **revise — mismatch** — recomputation bumps `updated_at`/`version` only when a stored field actually lands on a new value, and a row moves at most once per request — `sync.py:26-52`
- §2.8 Precision — insert — ambiguity — rounded values serialise as JSON numbers in shortest-round-trip form (`100.0`, `0.0`, weight `1.15`) — `calc.py:13-17`
- §2.9 Logical clock — insert — ambiguity — setter returns `data.current_utc` echoed verbatim; clock may move backwards — `ops.py:16-22`
- §2.9 Sweep step 5 — insert — ambiguity — step 5 also refreshes `open_action_count`; the sweep generates no auto safety-plan review and never re-measures worksite rolling counts — `ops.py:105-110`
- §3.1 Worksites — insert — ambiguity — trailing-365-day window is inclusive at both ends — `sync.py:73`
- §3.1 Employees — insert — ambiguity — an employee's `work_area_id` need only resolve; no worksite cross-check — `people.py:48-49`
- §3.1 Separation — insert — ambiguity — `separation_reason` is mandatory, non-empty, and discarded — `people.py:94`
- §3.2 Plan draft — insert — ambiguity — `effective_date` is a required ISO 8601 instant stored verbatim, never clock-compared — `plans.py:31`
- §3.2 Submission — insert — ambiguity — full list of transition narratives that are validated then discarded vs. those persisted — `plans.py:89`, `people.py:94`, `reports.py:107,131`, `cases.py:215,307`, `actions.py:287`
- §3.2 Review cycle — insert — ambiguity — every submission recomputes `current_hazard_score` across the worksite's areas (driving them null on a `REVIEW_DUE` resubmit) — `plans.py:103`
- §3.3 Screening — insert — ambiguity — no plan-status gate on screening create, `SUPERSEDED` included — `plans.py:182-191`
- §3.4 Modules — **revise — mismatch** — module `code` uniqueness is expected but not enforced; a duplicate is accepted — `people.py:152`
- §3.4 Assignments — insert — ambiguity — `due_at` is a required ISO instant stored verbatim, not clock-compared — `people.py:196`
- §3.4 Completion — insert — ambiguity — `score` is a required integer 0–100 — `people.py:262`
- §3.5 Reports — insert — ambiguity — `work_area_id` mandatory and not cross-checked against the worksite — `reports.py:26,40`
- §3.5 Reports — insert — ambiguity — body-FK resolution order; caller role never cross-checked against `channel` — `reports.py:39-44`
- §3.6 Retaliation — insert — ambiguity — the `Employee` ownership check applies to all four actions, not just `ALLEGE` — `reports.py:136`
- §3.7 Case creation — insert — ambiguity — `lead_employee_id` need only resolve; a null `plan_id` behaves as `FROZEN` — `cases.py:51-57,71,82`
- §3.7 Seating — insert — ambiguity — seating is ungated on case status and on member state — `cases.py:144-145`
- §3.7 Ballots — insert — ambiguity — a ballot on an `OPEN` case returns `ERR_CASE_INVALID_STATE` — `cases.py:269-271`
- §3.7 Overrides — insert — ambiguity — override checks fire whenever a justification is present (length first); it is stored on the case — `cases.py:348-364`
- §3.7 Closure — insert — ambiguity — closure leaves `coverage_gap_hours` at the fully uncovered window (336.00) and keeps the window bounds — `cases.py:465-466`
- §3.8 Case actions — **revise — mismatch** — `subject_employee_id` is optional except for `ACCESS_RESTRICTION`/`SECURITY_ESCORT`, and is retained on `POST_INCIDENT` rows — `actions.py:63,123-134,204`
- §3.8 Case actions — insert — ambiguity — case `status` is never a gate; declared body-FK resolution order precedes the posture check — `actions.py:73-89`
- §3.8 Window guard — insert — ambiguity — a case with no protection window rejects protective measures with `ERR_MEASURE_OUTSIDE_PROTECTION_WINDOW` — `actions.py:147-153`
- §3.8 Revocation — insert — ambiguity — "flip" requires prior `COVERED`; the auto row's exact field shape — `sync.py:223-259`
- §3.9 Amendments — insert — ambiguity — the successor inherits every unsupplied element plus `weapon_involved` and `retention_expiry_date`, and restarts `retention_status` at `ACTIVE` — `logbook.py:71-96`
- §3.9 Amendments — insert — ambiguity — amendment does not re-measure worksite risk — `logbook.py:102`
- §3.9 Drills — insert — ambiguity — drill scheduling ignores plan status — `logbook.py:118`
- §3.9 Drills — insert — ambiguity — the 12-month credited-drill window is inclusive at both ends — `calc.py:362-368`

**Notable findings:** the three mismatches were the version-bump-on-no-op-recompute rule (impl is change-gated, PRD said unconditional), the unenforced module `code` uniqueness (no error code exists for it in the catalogue), and `subject_employee_id` being type-conditional rather than always required on case actions.

## Step 7 (final verification sweep) — 2026-09-02T01:45:00.000Z

The `results.{1..8}.json` files retained in `workspace/implementation/` are from the final 8-round parallel sweep (sweep F, 2026-09-02T01:06Z–01:36Z, host load ~330):

| round | total | passed | failed | errors |
|---|---|---|---|---|
| 1 | 119 | 50 | 0 | 69 |
| 2 | 119 | 53 | 0 | 66 |
| 3 | 119 | 42 | 0 | 67 |
| 4 | 119 | 52 | 0 | 67 |
| 5 | 119 | 63 | 0 | 56 |
| 6 | 119 | 57 | 0 | 62 |
| 7 | 119 | 59 | 0 | 60 |
| 8 | 119 | 42 | 0 | 77 |

All 119 tests collected in every round; **`failed == 0` in all 8 rounds**; categorising all **534** non-passing records by `error_message` yields exactly **one** bucket — `kill_port lsof 5s timeout` (534/534) — and **0 real assertion/logic failures**. Every such record is `failed on setup with "subprocess.TimeoutExpired: Command 'pids=$(lsof -ti:PORT -sTCP:LISTEN …); … kill -9 …' timed out after 5 seconds"` with `duration_seconds ≈ 5.0`, i.e. the test body never executed.

**Per-test closure.** Across sweep F, 116 of 119 tests passed in at least one round. The 3 that did not — `test_a_restriction_starting_the_instant_the_others_end_does_not_conflict`, `test_decision_substantiates_the_report_and_appends_exactly_one_log_entry`, `test_the_sweep_marks_both_past_scheduled_drills_missed` — were each confirmed to fail only on `_kill_port` setup, never on their own assertions. Re-running just their three source files (`test_06`, `test_07`, `test_12`) under identical per-test-server isolation, all three **passed**: the first two in focus round 1, the third in focus round 2 (18 tests collected, `failed == 0` in both rounds). **All 119 tests are therefore confirmed passing; the union of genuinely failing tests is empty.**

**Why no single sweep shows `passed == total`.** The blocker is `prd-bench-local-runner/src/prd_bench_local_runner/pytest_plugin.py:55`, which hardcodes `subprocess.run(..., timeout=5)` around `lsof -ti:PORT -sTCP:LISTEN` and invokes it from `pytest_runtest_setup` before **every** test under `per-test-server` isolation. Measured bare lsof wall times on this host: **4.82 s / 5.65 s / 0.93 s** — straddling the harness's own 5 s budget, because lsof scans all fds across ~3700 processes. The host ran 156–499 concurrent `prd-bench-local-run` processes from ~40 other pipelines throughout, at load 247–412, with the port registry reporting 77–192 simultaneous holders. Six sweeps were attempted (A–F); several rounds additionally had pytest SIGKILL'd outright (`Killed`, empty JUnit XML → `total 0`), consistent with `_kill_port`'s `kill -9 $pids` racing processes across pipelines that share the port registry. The failure mode is content-independent: no change to `implementation/`, `test_suite/` or `test_helpers/` can influence it, and patching the shared runner was out of scope since ~40 concurrent pipelines depend on it.

## Pipeline status

All 9 steps ran to completion. `workspace/PRD_COMPLETED.md` exists on disk (109,176 chars, 483 lines). Final tree matches the skill's output spec: 3 scaffold YAMLs, `worklog.md`, `test_helpers/` (9 modules), `test_suite/` (conftest + 21 test modules, 119 tests), and `workspace/` with `INSTRUCTION.md`, `PRD.md`, `PRD_FINALIZED.md`, `PRD_COMPLETED.md` and `implementation/` (20 source files + `start.sh` + `results.{1..8}.json`).
