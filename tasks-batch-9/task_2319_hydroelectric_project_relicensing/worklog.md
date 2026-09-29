# Worklog — task_2319_hydroelectric_project_relicensing

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2319_hydroelectric_project_relicensing/` and `tasks/task_2319_hydroelectric_project_relicensing/workspace/` (bash only; directory name pre-allocated by the caller).

## Step 2: Generate scaffold — 2026-09-01T00:20:00.000Z

All three artifacts are complete and the linter is clean.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2319_hydroelectric_project_relicensing/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2319_hydroelectric_project_relicensing/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2319_hydroelectric_project_relicensing/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    64
  §1.1 entities declared:     14
  §1.8 instances scanned:     21
  §1.9 instances scanned:     61
  Calls scanned (§1.8+§1.9):  1090

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Worklog summary — task_2319_hydroelectric_project_relicensing

Files written (all absolute paths under `/home/ubuntu/github/CodingPRD/tasks/task_2319_hydroelectric_project_relicensing/`): `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`. No sibling task directory was read at any point.

**SCAFFOLD.yaml (§1.0–§1.7)**
- `api_prefix: /relicensing`; primary archetype `multi_party_negotiation`, secondary `compliance_audit`; entity topology `flat`; state-machine shape `cyclic`; role model `segregation_of_duties`; consistency `immediate`.
- Six complexity layers: cascading_side_effects, dual_variant_calculation, version_pinning_on_approval, optimistic_concurrency, ops_run_checkpoint, derived_field_reconciliation.
- 14 entities, 8 state machines, 9 calculation blocks, 64 endpoints (incl. `/_clock` setter/reader, declared with real roles), 50 errors, 5 roles (Licensee, AgencyReviewer, Stakeholder, StateCertifier, Regulator), 2 OCC concurrency rules on `expected_project_version`, pagination `limit/offset/total_count/has_more` (default 10, max 100).
- Domain math the tests pin: PME dual-variant estimate (PRELIMINARY contingency 0.25 / DEFINITIVE 0.10, 3%/yr escalation from `pad_year`, per-category amortization 30/20/15/10 yr), generation-impact proxy, tiered admin charge (0.02/0.035/0.05 on pre-charge PME cost), burden ratio vs. `BURDEN_RATIO_LIMIT_PCT 15.00`, WQC 12-month statutory waiver sweep, and posture derivation (FROZEN/RESTRICTED/OPEN).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)** — 9 rules / 21 instances: dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 4, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)** — 86 instances across all nine taxonomy sections: 61 with full structured `test_recipe`s + 25 `excluded_because` stubs. By section: entities 14 (14 recipes), state_machines 15 (11), calculations 13 (4), validations 16 (11), endpoints 6 (5), errors 7 (5), rbac 6 (6), cross_cutting_complexity_layers 8 (4), consistency_model 1 (1).

Audits passed: no duplicate instance names across §1.8 ∪ §1.9; every stub's `difficulty_instance` resolves to a real `<rule_id> / <instance_name>`; every `grounds:` reference resolves to a declared entity/state machine/calculation/validation priority/error id/endpoint/role/complexity layer/concurrency `rule_id`/envelope field; no unbound `${...}` placeholders; every active complexity layer has at least one cross-cutting instance.

## Step 3: Copy shared files — 2026-09-01T00:21:00.000Z

Copied `INSTRUCTION.md` into `tasks/task_2319_hydroelectric_project_relicensing/workspace/INSTRUCTION.md` (bash only).

## Step 4: Generate PRD — 2026-09-01T00:40:00.000Z

All three Hard Contracts pass. PRD written to `/home/ubuntu/github/CodingPRD/tasks/task_2319_hydroelectric_project_relicensing/workspace/PRD.md`.

## Document

- **519 lines**, 5 top-level sections, 21 `###` subsections.
- **§1 Introduction** — 3 paragraphs framing the relicensing arc, the flat `/relicensing` namespace, the two derived postures and the burden ledger.
- **§2 Global Specifications** — 2.1 RBAC (all 5 roles, both `entity_backed:SettlementParty` identities translated to explicit prose plus the 3 opaque ones, capability/restriction summary), 2.2 API Response Structure (**verbatim byte-for-byte match** against `section-2.2-response-structure.md`), 2.3 Pagination, then 9 domain subsections: 2.4 Logical Clock & Date Arithmetic, 2.5 Common Resource Properties (incl. the two `common_fields: false` ledger resources and the lifecycle-field naming map), 2.6 Numeric Precision, 2.7 Statutory Deadlines & Timeline Posture, 2.8 Regulatory Posture (the project-wide gate), 2.9 Derived Counters & Cascade Propagation, 2.10 Reference Integrity, 2.11 Stale-Version Protection (OCC), 2.12 Validation Precedence (full 43-rule ladder) & Segregation of Duties.
- **§3 Business Logic** — 9 subsections following the business timeline: project setup, PAD/deadline posture, study plans + comments + determination, resource studies (dual dimensions, site window buffer), settlement negotiation, water-quality certification, PME dual-variant estimation + burden ledger, application filing + environmental review, order issuance + post-license compliance. Worked examples included for timeline slack, the rounding-order support tally, both cost/generation variants, the 6-step ledger with tier and ratio boundaries, topological obligation due dates, and the CALENDAR vs LICENSE_ANNIVERSARY window disagreement.
- **§4** 64 endpoints, 4 columns only. **§5** 50 errors, 2 columns only. Document ends at the last error row — no audit footer.

## Coverage audits

```
Field coverage check:
- entities[].fields: 136 required, 136 present, 0 missing
- endpoints[].request_body: 80 required, 80 present, 0 missing
- endpoints[].query_params: 36 required, 36 present, 0 missing
- path parameters: 14 required, 14 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 43 checked, 43 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_project_version + ERR_STALE_PROJECT_VERSION/412 all named), 0 missing
- state_machines[].transitions: 10 machines / 57 transitions checked, 57 fully expressed, 0 missing
- calculations[]: 7 checked, 7 fully expressed (all constants as values, all pinned step orders, all precision rules), 0 missing
- validations[] conditions: 43 checked, 43 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 38 endpoints with side effects checked, 38 expressed, 0 missing
- entities[].fields[] structured content: 14 entities / 136 fields checked, 136 reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 groups checked, 9 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1065
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Mechanical cross-checks also confirmed: §4 table is a 1:1 set match with `endpoints[]` (64/64, zero in either direction), all authorized-role lists match the scaffold (all-five-roles collapsed to "Any"), and §5 is a 1:1 set match with the validation error catalogue (50/50) with zero HTTP-status mismatches. The only scaffold `ERR_` token absent from the PRD is `ERR_XXX`, the placeholder in the `response_envelope` example.

Two scaffold ambiguities were resolved toward the priority-ordered validation table, since it declares first-violation-wins: (1) the settlement EXECUTE gate is ordered study-plan-approved → support threshold → conditioning veto (priorities 51/70/71) rather than the state machine's listing order; (2) the dam capacity rule counts only `SCHEDULED` obligations, per validation priority 66, and the `max_concurrent_field_activities` field is described generically to avoid contradicting it. Also noted: `circulate` requires ≥2 registered parties but the scaffold assigns no error code, so the PRD assigns `ERR_SETTLEMENT_STATE_INVALID` for determinacy, and `vote_weight` (optional input, no scaffold default, constraint ≥1) is documented as defaulting to 1.

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-01T02:30:00.000Z

Stage 2 is complete. Final file written: `test_suite/test_13_pinning_concurrency_and_listing.py`.

## Files written

Stage 1 — `test_helpers/` (9 files): `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`.

Stage 2 — `test_suite/` (13 test files + `conftest.py`), **121 tests**:

| file | tests | queue |
|---|---|---|
| test_01_measure_estimation_and_ledger.py | 9 | A |
| test_02_settlement_tally_and_execution.py | 10 | A |
| test_03_study_program_and_site_calendar.py | 8 | A |
| test_04_certification_and_application_gates.py | 6 | A |
| test_05_compliance_orders_and_reporting.py | 10 | A |
| test_06_entity_contracts.py | 14 | B |
| test_07_state_machine_transitions.py | 11 | B |
| test_08_measure_arithmetic_and_schedules.py | 4 | B |
| test_09_validation_rules.py | 19 | B |
| test_10_endpoint_behaviour.py | 9 | B |
| test_11_error_taxonomy.py | 7 | B |
| test_12_role_boundaries.py | 8 | B |
| test_13_pinning_concurrency_and_listing.py | 6 | B |

Queue A (Difficulty): **43 tests**. Queue B (Corner): **78 tests**.

## Coverage audit

- Difficulty design: 21 instances, all 21 non-stub — **21/21 covered, 0 uncovered**.
- Corner design: 86 instances, 61 non-stub — **61/61 covered, 0 uncovered**. Per section: entities 14, state_machines 11, validations 11, rbac 6, endpoints 5, errors 5, calculations 4, cross_cutting_complexity_layers 4, consistency_model 1.
- 82 distinct instances tagged across 121 tests; every test carries exactly one `Design:` line as the last docstring line, and every tag resolves to an existing instance (no untagged, dual-tagged or dangling tags).
- 215 PRD citations, each verified as a literal substring of `workspace/PRD.md`.

## Skipped instances

25 corner instances — every one a declared stub (`excluded_because` naming a §1.8 difficulty instance that already covers the same ground, no `test_recipe`), so none was translated: `settlement_round_loop_terminates_at_round_three`, `study_fieldwork_and_review_dimensions_move_independently`, `settlement_withdrawal_reverses_execution_side_effects`, `measure_inclusion_syncs_project_ledger`, `pme_variant_switch_diverges_on_cost_and_generation`, `ledger_reconciles_when_the_variant_switches`, `annual_report_basis_selects_different_assessed_sets`, `administrative_charge_tier_boundaries`, `timeline_posture_slack_threshold_boundary`, `burden_ratio_limit_precision`, `support_tally_weighted_rounding_order`, `empty_assessment_period_scores_one_hundred`, `posture_propagation_reaches_a_fixed_point`, `application_filing_priority_between_stage_and_burden_checks`, `study_creation_priority_between_window_and_clearance_checks`, `study_window_overlap_at_the_same_site_rejected`, `dam_activity_capacity_is_an_aggregate_check`, `settlement_execution_requires_an_approved_plan`, `project_read_returns_the_recomputed_burden_ledger`, `support_threshold_not_met_on_an_execute_tally`, `definitive_estimate_required_before_final_ea`, `wqc_condition_cascade_runs_end_to_end`, `both_estimate_variants_produce_their_own_numbers`, `the_ops_run_checkpoint_advances_the_epoch_once_per_clock_move`, `derived_ledger_fields_reconcile_after_a_reversal`.

**No non-stub instance was dropped on the PRD-first filter.** Where a recipe's asserted outcome was not PRD-derivable, the individual assertion was omitted rather than the instance: the design's `ERR_DEFINITIVE_ESTIMATE_REQUIRED` HTTP 422 (PRD makes it 409), the `4202.06 at every step` over-claim, null `support_pct`/`total_vote_weight` on a new settlement (§3.5 says zero), the veto recipe's `sup_mid == null`, and `version == 1` after party registration.

## Key findings from this final pass

- The design's stale-pin error is `ERR_STALE_PROJECT_VERSION` at **HTTP 412** (PRD §2.11 lines 163/165 and §2.12 item 12) — not `ERR_STALE_VERSION`/409. Both `test_13` pin tests use 412.
- §2.12 orders the version pin (item 12) ahead of the stage check (item 16), and §2.11 states "no state precondition blocks the write" for settlement creation — so the 412-before-409 ordering test is well-grounded, and a settlement legitimately opens at `PAD_FILED`.
- Only `limit` and `offset` are PRD-documented query parameters, plus the §2.5 rule that a lifecycle field name doubles as its filter name. The studies-listing test therefore asserts only on the unfiltered page-walk and on the documented `fieldwork_status` filter; `site_id`, `study_plan_id` and `resource_category` carry no assertions. Page contents are asserted as disjoint-and-complete rather than order-sensitive, because all four studies share one `created_at` under the logical clock.
- Fixed two defects found by the verification sweeps: a fabricated `§3.4` citation in test_13 (replaced with the verbatim §3.4 `START` sentence from PRD line 267) and an unused `new_study_plan` import in `test_08_measure_arithmetic_and_schedules.py`.
- Full-suite checks all clean: `py_compile` over `test_suite/` and `test_helpers/`; citation check (215/215 verbatim); tag audit (0 uncovered, all tags resolve); AST sweep confirming every `test_helpers` import exists and is used, every `api_client.<method>` resolves, and no `skip`/`xfail`/mocking/"scaffold" mentions anywhere in the suite.

## Step 6: Generate implementation — 2026-09-01T02:30:00.000Z

Live HTTP boot through `start.sh` confirmed on a fresh process (fresh store returns `total_count: 0`, envelope/meta shape correct, `401` without headers). Implementation is complete and validated.

**Files written** (19, all in `workspace/implementation/`):

- Entry/infra: `start.sh` (chmod +x, lazy pip install, `exec python3 app.py`, `PORT` default 10000), `app.py` (`create_app()` + module-level `app`, blueprint registration, `ApiError`/`HTTPException`/`Exception` handlers), `requirements.txt` (`flask>=3.0`)
- Support modules (11): `errors.py` (50-code catalogue + 4 framework codes → HTTP status map, `ApiError`), `clock.py` (logical clock, default `2026-08-01T00:00:00Z`, day-clamped `add_months`), `db.py` (`Store` = 14 plain dicts, `sorted_rows` ordering by `(created_at, _seq)`), `response.py` (envelope, `req_` + 20 uppercase alnum request ids, `has_more`), `numeric.py` (`Decimal`/`ROUND_HALF_UP` `q2`/`q1`, 3%-escalation power), `payload.py` (field validators + pagination), `constants.py` (enums + every pinned number), `auth.py` (ladder rungs 1–3: 401 → 403 → project scope; entity-backed AgencyReviewer/Stakeholder resolution via `SettlementParty.contact_user_id`), `serializers.py`, `listing.py` (filter coercion for bool/int fields, then slice), `services.py` (the derived-state engine: postures, counters, burden ledger, dual-variant measure math, weighted tally, obligation-schedule generation, compliance sweep/annual-report assessment)
- Route blueprints (5): `routes_core.py` (14 endpoints — clock, projects, dams, sites, PAD, sweep), `routes_study.py` (15 — study plans, studies, comments), `routes_wqc.py` (9 — WQC, PME measures, cost estimates), `routes_settlement.py` (12 — parties, settlements, signatures), `routes_license.py` (14 — applications, EA/deficiency/cure, orders, annual reports, obligations)

**Endpoint count: 64**, verified 1:1 against the PRD §4 table by diffing `app.url_map` against a regex extraction of the table (no missing, no extra), and each endpoint's role gate diffed against the table's "Authorized Role(s)" column — all 64 match. List-endpoint filter sets match the SCAFFOLD `input:` arrays.

**Notable design decisions**
- Storage is in-memory dicts only, zero seeding; every launch starts empty (`start.sh` re-run per test is safe).
- `finalize_project()` (row counters → WQC mirror → burden ledger → two-tier `regulatory_posture`) runs at the end of every mutating handler, since each is a pure function of stored rows. `timeline_posture` is deliberately excluded and moves only at the 4 PRD-named moments.
- PRD §2.12's 43-rung validation precedence ladder is treated as authoritative wherever it disagrees with scaffold field ordering (e.g. cross-project reference at rung 6 precedes cycle detection at rung 31).
- Project `version` bumps only where the PRD says so; child rows bump `version` only when a field actually changed (`refresh_order_violations` no-ops when stable — makes repeat sweeps idempotent).
- FROZEN blocks all mutations except the five cure paths (cure, schedule, certify, annual report, sweep) plus project creation.
- `Decimal` + `ROUND_HALF_UP` applied at every named step (per-share rounding before tally summation, per-measure rounding before ledger summation).
- Half-open buffered study windows vs closed-interval dam activity windows, per the respective PRD wording.
- Annual-report duplicate detection uses a private, non-serialized `order["_reports"]` list of `(basis, period_year)`.

**Verification**: all PRD worked examples reproduce exactly (dual-variant measure PRELIMINARY/DEFINITIVE figures, ledger 15.00 infeasibility boundary, all three tally cases 66.66/66.67/75.00, the full obligation schedule incl. topological order-independence, report windows with leap/31st clamping); three end-to-end smoke passes over the full lifecycle plus ~40 error cases report "all expectations matched".

**One bug found and fixed** during smoke testing: `POST /relicensing/settlements/{id}/circulate` in `routes_settlement.py` never set `status = "CIRCULATED"` (nor `circulated_at`/`total_vote_weight`), which cascaded into spurious `ERR_SETTLEMENT_STATE_INVALID` on tally and 409s on signature creation. Fixed; all subsequent runs green.

## Step 7: Run tests and iterate — 2026-09-02T06:40:00.000Z

The 8-round parallel stability sweep is **green: all 8 rounds 121/121 passed, 0 failed, 0 errors, 0 skipped.**

## Summary

**Iterations run: 36 full 8-round parallel sweeps** (288 round-executions, 8 rounds launched concurrently and joined with `wait` each time, no early exit). The union-of-failures rule was applied after every sweep.

**Tests deleted: none.** Every one of the 121 tests was adjudicated against `workspace/PRD.md` and found PRD-grounded. No STEP 1a verbatim-coverage gap, no STEP 1b non-derivability category (no COMPUTED-FIELD SILENCE, DEFAULT-VALUE SILENCE, BRANCH-ASYMMETRIC SIDE EFFECT, ERROR PRECEDENCE SILENCE or ENUM-MEMBERSHIP-ONLY instance survived scrutiny), and no assertion was weakened, skipped or xfailed.

**Fixes applied to `test_helpers/`: none.** No setup-error cluster ever traced to a fixture, factory or role-header helper; the >=5-failures triage hint fired repeatedly but every cluster resolved to the runner, not the helpers.

**Fixes applied to `workspace/implementation/` — one genuine defect, two files:**

1. `workspace/implementation/auth.py` — project-scoped party resolution for entity-backed roles. The old code resolved a single `SettlementParty` per `contact_user_id` (earliest by `created_at`), so a user backing an AGENCY party on two projects always resolved to the wrong project's party and got `ERR_ROLE_NOT_PERMITTED` on its own project. Replaced `_party_for_user` with `_parties_for_user` (all matches, ordered by `(created_at, _seq)`), `authenticate()` now carries `g.party_candidates` and narrows them by `PARTY_TYPES_BY_ROLE`, and `require_project_scope(project_id)` selects the candidate registered on the target project — rejecting with `ERR_ROLE_NOT_PERMITTED` (403) only when none is. Traces verbatim to PRD §2.1: "the acting user must resolve to a `SettlementParty` registered on the same project as the target entity. A party of a different project is treated as not permitted and receives `ERR_ROLE_NOT_PERMITTED` (HTTP 403), not a not-found error."
2. `workspace/implementation/routes_study.py` (`plan_determination`) — moved `auth.require_project_scope(plan["project_id"])` ahead of the `has_conditioning_authority` check so the conditioning-authority test reads the project-scoped party rather than an arbitrary one. No test asserts `ERR_STUDY_PLAN_NOT_FOUND` on this endpoint, so precedence is unaffected.

No endpoint, field, side effect or header was added; storage remains in-memory dicts only (verified: no `sqlite`/`pickle`/`open(`/`json.dump`/`/tmp` anywhere in `implementation/`, `Store.__init__` builds 14 empty dicts, zero seeding).

**Why 36 iterations.** After the `auth.py` fix, every remaining non-pass across all sweeps was host infrastructure, not the task: 1192 of 1193 sampled non-passes were `subprocess.TimeoutExpired: Command 'pids=$(lsof -ti:<port> -sTCP:LISTEN ...); kill -9 ...' timed out after 5 seconds` from the shared runner's `_kill_port` (hardcoded 5s, not env-overridable) plus a handful of whole rounds SIGKILLed externally. The box was running ~50 sibling pipelines at load average 300–425; the failure count fell monotonically as load decayed (attempt 8: 24/121 per round -> attempt 34: 7 of 8 rounds clean -> attempt 36 at load 84: all 8 clean). I deliberately did **not** patch the shared runner, since other pipelines depend on it. Scratch harness and stray `results.*.json` have been removed; the task directory contains only its intended artifacts.

_Orchestrator note: because the fix subagent deleted the `results.*.json` files on exit, the orchestrator re-ran one final 8-round parallel sweep to regenerate `workspace/implementation/results.{1..8}.json` as durable evidence._

## Step 8: Finalize PRD — 2026-09-02T06:50:00.000Z

Done. `PRD_FINALIZED.md` written with two surgical revisions, both tracing to the single Step 7 fix (project-scoped party resolution in `auth.py` + the reordering in `routes_study.plan_determination`).

## Line counts
- `PRD.md`: 518 lines — `PRD_FINALIZED.md`: 518 lines — **0.00% line delta** (2 lines revised in place, no lines added or removed; no new sections).

## Changes
- **§2.1 (project-scoped access rule paragraph)** — revise — party resolution for `AgencyReviewer`/`Stakeholder` is a narrowing over *all* parties sharing the `contact_user_id` (no match at all -> `ERR_UNAUTHORIZED` 401; survivors filtered by `party_type` for the declared role -> `ERR_ROLE_NOT_PERMITTED` 403 when none; then the one registered on the target entity's project, earliest-registered on a tie) and that selected party is the acting party whose `id` satisfies the `party_id` ownership comparison and whose `has_conditioning_authority` a determination tests — `implementation/auth.py:15-18, 29-34, 45-57, 68-81`; `routes_study.py:114-121`.
- **§2.12 ladder rung 3** — revise — rung 3 applies to exactly the four mutating endpoints those roles may call (comment filing, signature recording, study-plan determination, study review decision), reads are unscoped, and the rung is evaluated only after the *target* entity has been resolved (so an omitted/unresolvable `study_plan_id`/`settlement_id`/path id yields `ERR_INVALID_REQUEST` or the not-found code first), while every other body reference including `party_id` still resolves after it — `implementation/routes_study.py:112-114, 337-340, 380-388`; `routes_settlement.py:319-327`; `auth.py:68-81`.

## Per-edit pre-edit search log

**Edit 1 — §2.1 paragraph**
- (a) Subject: how `X-User-ID` resolves to a `SettlementParty` for entity-backed roles, and which party is "the acting party".
- (b) Paths enumerated (grepped `require_project_scope|acting_party|party_candidates|g\.party|contact_user_id` across all of `implementation/`, then read each): `auth.py` `_parties_for_user` (ordering `(created_at, _seq)`), `authenticate` (401 branch for empty candidate set — note it fires *before* the role-list check; `PARTY_TYPES_BY_ROLE` narrowing *after* it; `g.party = allowed[0]` default when no scope call), `require_project_scope` (filters candidates by `project_id`, picks first, 403 otherwise); all four consumers — `routes_study.plan_determination` (`acting_party()["has_conditioning_authority"]`), `routes_study.study_review_decision` (scope only, no `acting_party`), `routes_study.create_comment` (`party["id"] != acting["id"] and party_id != g.user_id`), `routes_settlement.create_signature` (same OR-form check); plus every `auth.authenticate` callsite (63 of them) to confirm the only lists containing `AgencyReviewer`/`Stakeholder` are those four plus `C.ALL_ROLES` reads; `routes_settlement.create_party` (`contact_user_id` is optional -> `None`, so a header value never matches a null binding); `db.sorted_rows`/`services.base_row` (`_seq` tiebreak = registration order); `serializers.py:117` (`contact_user_id` is exposed but drives nothing else).
- (c) Adjustments made to stay consistent with all of them: (i) wrote "its `id` **satisfies** the `party_id` ownership comparison" rather than "the ownership comparison compares `party_id` to the selected party's `id`", because comments/signatures also accept `party_id == X-User-ID` literally — an exclusive phrasing would have contradicted that second arm and the pre-existing §2.1 bullets; (ii) dropped a drafted clause tying `vote_weight` to the acting party, since the tally sums `vote_weight` over *all* project parties, never the acting one; (iii) scoped the project-selection clause with "wherever the request has a target entity to be scoped against", so it does not falsely claim read endpoints select a project-scoped party (there `g.party` stays the first type-matching candidate and is never consulted); (iv) kept the 401 clause tied to entity-backed resolution only, since `Licensee`/`StateCertifier`/`Regulator` ids are never looked up; (v) left both original sentences verbatim and appended, so the pre-existing 403-not-404 guarantee is untouched.

**Edit 2 — §2.12 rung 3**
- (a) Subject: the scope and evaluation position of ladder rung 3 relative to rungs 4/5/7.
- (b) Paths enumerated (same grep plus a full sweep of `auth.authenticate` argument lists): the four `require_project_scope` callsites and the exact statement order at each (`plan_determination`: `authenticate` -> `SV.fetch("study_plans")` -> scope -> conditioning authority -> `payload.body()`; `study_review_decision`: `authenticate` -> `SV.fetch("studies")` -> plan lookup by FK -> scope; `create_comment`: `authenticate` -> `payload.body()` -> `req_string("study_plan_id")` -> `SV.fetch` -> scope -> `req_string("party_id")` -> `SV.fetch("parties")` -> cross-project check; `create_signature`: identical shape with `settlement_id`); `services.fetch`/`_NOT_FOUND` map for the codes emitted; `payload.body`/`req_field`/`req_string` to confirm a missing or non-object body raises `ERR_INVALID_REQUEST` (400), not `ERR_VALIDATION`; all `C.ALL_ROLES` read endpoints to confirm none scopes; `listing.respond` (list filters are unscoped by party/project).
- (c) Adjustments: (i) replaced "the four mutating endpoints those two roles may call" with the explicit endpoint list plus "the only mutating endpoints open to those two roles", because determination and review-decision admit `AgencyReviewer` only — a "both roles may call all four" reading would have been false; (ii) restricted the resolution-before-scope carve-out to "that one entity", and added the closing sentence that every other reference (notably `party_id`) still resolves after rung 3, so the edit does not weaken the ladder's rung 3 -> rung 5/6 ordering that `create_comment`/`create_signature` do honour for the party reference and the cross-project check.

## Step 9: Complete PRD — 2026-09-02T07:10:00.000Z

Done. `PRD_COMPLETED.md` is final.

## Exit summary

**Source vs output**
| | `PRD_FINALIZED.md` | `PRD_COMPLETED.md` | delta |
|---|---|---|---|
| lines | 518 | 521 | +3 |
| chars | 104,586 | 116,170 | +11,584 |

37 diff hunks, 36 of them in-place paragraph revisions and 1 a new table row. Section headers are byte-identical between the two files (verified by diff of all `^#` lines); no section was added, removed or reordered.

**Classification:** 27 ambiguity-pins, 10 mismatch-revisions.

**Changes**

- §2.1 RBAC — revise — ambiguity — pinned header ladder: missing/blank `X-User-ID` -> 401 first; an absent, unknown or non-permitted `X-User-Role` -> `ERR_ROLE_NOT_PERMITTED` (403), never 401 — `implementation/auth.py:23-43`
- §2.1 RBAC — revise — ambiguity — entity-backed roles resolve parties by `contact_user_id` ordered by `(created_at, insertion)`, first match acts; no match -> 401; party_type/role mismatch -> 403 — `implementation/auth.py:15-57`
- §2.3 Pagination — revise — ambiguity — `created_at` ties broken by insertion order — `implementation/db.py` `sorted_rows`
- §2.3 Pagination — insert — ambiguity — per-endpoint exact-match filter-name lists; an unparseable bool/int filter value matches nothing rather than erroring; `total_count` is post-filter/pre-pagination — `implementation/listing.py:33`, `implementation/response.py:30-36`
- §2.7 Timeline posture — revise — ambiguity — whole-day slack arithmetic, negative slack => `DELINQUENT`, 180-day inclusive `AT_RISK` band — `implementation/services.py` posture block
- §2.8 Regulatory posture — revise — **mismatch** — the `FROZEN` gate covers `Regulator` and `StateCertifier` writes too (project amend, party registration, environmental review, deficiency, order issuance, WQC decision), with exactly five exemptions — `implementation/routes_core.py:125`, `implementation/routes_wqc.py`, `implementation/routes_license.py:414,477,537`
- §2.9 Counters/version — revise — **mismatch** — counter/ledger/posture recomputation never bumps the *project* row's `version` (critical for `expected_project_version`), and an unchanged order-violation refresh touches nothing — `implementation/services.py:230,541`
- §2.10 Reference integrity — revise — **mismatch** — URL ids resolve left-to-right with the first missing one deciding; `ERR_SIGNATURE_NOT_FOUND` added to the not-found code list — `implementation/services.py:15-37`
- §2.12 rung 5 — revise — ambiguity — body references resolve in a fixed per-endpoint order — `implementation/routes_*.py`
- §2.12 rung 15 — revise — **mismatch** — same scope correction as §2.8, plus cure-path enumeration — `implementation/routes_core.py:125`
- §2.12 rung 31 — revise — **mismatch** — the prerequisite same-project rule is `ERR_CROSS_PROJECT_REFERENCE` at rung 6, not `ERR_PREREQUISITE_CYCLE`; the cycle test is reachable only via amendment — `implementation/routes_wqc.py`
- §3.1 Projects — revise — ambiguity — `license_expiration_date` <= clock => `ERR_INVALID_REQUEST`, decided *before* the `license_number` uniqueness check — `implementation/routes_core.py:59`
- §3.1 Projects — revise — **mismatch** — project amendment is itself subject to the `FROZEN` gate — `implementation/routes_core.py:125`
- §3.1 Sites — revise — ambiguity — `river_mile` required and unbounded — `implementation/routes_core.py:276`
- §3.2 Study plans — revise — ambiguity — `PAD_FILED -> STUDY_PHASE` bubble-up and the project version bump occur only for the project's first plan — `implementation/routes_study.py:62`
- §3.2 Plan submission — revise — **mismatch** — the empty-plan `ERR_INVALID_REQUEST` is evaluated *last*, after the posture gate and the plan-status check — `implementation/routes_study.py:99`
- §3.2 Comments — revise — ambiguity — authoring-party ownership check precedes the cross-project check; on resolve, plan-state precedes `ERR_COMMENT_ALREADY_RESOLVED` — `implementation/routes_study.py:391,461-467`
- §3.3 Fieldwork — revise — ambiguity — the `START` plan-status check runs *after* the study's own `fieldwork_status` check — `implementation/routes_study.py:281-296`
- §3.4 Tally — revise — ambiguity — the tally is computed for every outcome but persisted only on a landing outcome; refusal ordering pinned — `implementation/routes_settlement.py:203-237`
- §3.6 WQC decision — revise — ambiguity — which condition-element fields are required vs optional, hydraulics defaulting to 0, and generated measures taking the `StateCertifier` as `created_by_user_id` — `implementation/routes_wqc.py:167-204`
- §3.7 Measure creation — revise — ambiguity — no project-stage gate and no cycle test on creation — `implementation/routes_wqc.py:259`
- §3.7 Measure calculation — revise — ambiguity — an unset `pad_year` yields zero escalation years — `implementation/services.py:264`
- §3.7 Measure amendment — revise — ambiguity — terminal status => `ERR_INVALID_REQUEST` (400), after the `FROZEN` gate and before the cycle test; variant not reset — `implementation/routes_wqc.py` `patch_measure`
- §3.7 Definitive estimate — revise — ambiguity — an already-`DEFINITIVE` measure => `ERR_INVALID_REQUEST` decided *before* the segregation check; no status precondition — `implementation/routes_wqc.py` `measure_cost_estimate`
- §3.8 Application filing — revise — ambiguity — `amends_order_id` is resolved before `application_type` is read; the pairing rule raises `ERR_INVALID_REQUEST` — `implementation/routes_license.py:56-77`
- §3.8 Snapshot — revise — ambiguity — snapshot picks the first `APPROVED` plan and the last `EXECUTED` settlement by `created_at` — `implementation/routes_license.py:27`
- §3.8 `ORIGINAL_RELICENSE` — revise — ambiguity — the burden-ratio check is the last hurdle and applies to `AMENDMENT` filings as well — `implementation/routes_license.py:86-160`
- §3.8 `AMENDMENT` — revise — ambiguity — type-specific hurdle set and the open-amendment uniqueness rule — `implementation/routes_license.py:149`
- §3.8 Order issuance — revise — ambiguity — `assessed_obligation_count`, `noncompliant_obligation_count` and `compliance_score` initialise at 0 and are order response fields — `implementation/routes_license.py:341`, `implementation/serializers.py:217`
- §3.9 PME obligations — revise — ambiguity — topological waves with a 6-month lag; a prerequisite outside the live measure set is treated as a root — `implementation/services.py:473`
- §3.9 Dam obligations — revise — ambiguity — emitted after the whole measure set, dam by dam in `created_at` ascending order — `implementation/services.py:473`
- §3.8 Amendment supersede — revise — **mismatch** — carried-over obligations count toward `article_count`, and *every* non-`WAIVED` obligation of the superseded order is waived (`CERTIFIED` and `OVERDUE` included) — `implementation/routes_license.py:352-383`
- §3.9 Scheduling — revise — ambiguity — start > end => 400 on `activity_window_end`; prerequisite check precedes capacity check; capacity is counted per *dam* across all orders (superseded included), skipping obligations with no stored window — `implementation/routes_license.py:485-524`
- §3.9 Certification — revise — ambiguity — segregation applies only where the obligation links a measure, so the three dam types skip it; it runs after the status and too-early checks and ignores the report's `review_status` — `implementation/routes_license.py:560-576`
- §3.9 Annual reporting — revise — ambiguity — `period_year` must be an integer >= 1, and there is no precondition on the order's `compliance_state` — `implementation/routes_license.py:420`
- §3.9 Compliance sweep — revise — **mismatch** — no stage/posture precondition, and idempotency is scoped to domain state: a second sweep at the same clock still restamps `last_sweep_at` and increments the project's `version` — `implementation/routes_core.py:200-204`
- §5 Error catalogue — insert — **mismatch** — added the missing `ERR_SIGNATURE_NOT_FOUND` (404) row — `implementation/services.py:24`

Nothing under `implementation/`, `test_suite/` or `test_helpers/` was modified; `PRD_FINALIZED.md` is untouched.

## Orchestrator verification sweep — 2026-09-02T07:35:00.000Z

Independent 8-round parallel confirmation sweep run by the orchestrator (Step 7's subagent had deleted its `results.*.json` on exit). First attempt at load average ~98 returned 6 clean rounds plus two single-test transport drops (`requests.exceptions.ChunkedEncodingError: Connection broken: IncompleteRead(0 bytes read, ...)` on `test_the_agency_veto_defeats_a_tally_that_clears_the_threshold` in round 2 and `test_an_absent_header_and_an_unbacked_reviewer_are_both_unauthorized` in round 7) — no assertion failures, two unrelated tests, each passing in the other 7 rounds, matching the host-load signature Step 7 documented. Repeat sweep on the same unmodified artifacts: **all 8 rounds 121/121 passed, 0 failed, 0 errors**. Those are the `results.{1..8}.json` files retained in `workspace/implementation/`.
