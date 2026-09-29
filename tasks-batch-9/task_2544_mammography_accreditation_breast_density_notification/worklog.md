# Worklog — task_2544_mammography_accreditation_breast_density_notification

## Step 1: Create task directory — 2026-09-03T08:45:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2544_mammography_accreditation_breast_density_notification` and its `workspace/` subdirectory. Index 2544 pre-assigned by the invoking pipeline; no scan of ./tasks/ performed and no other task directory created.

## Step 2: Generate scaffold — 2026-09-03T10:27:00.000Z

All three scaffold artifacts for scenario 2544 are complete and lint-clean.

Lint verdict (verbatim, final run):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2544_mammography_accreditation_breast_density_notification/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2544_mammography_accreditation_breast_density_notification/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2544_mammography_accreditation_breast_density_notification/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    67
  §1.1 entities declared:     14
  §1.8 instances scanned:     24
  §1.9 instances scanned:     63
  Calls scanned (§1.8+§1.9):  1149

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (all under the task dir):

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 3720 | 187841 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1753 | 107927 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3781 | 238908 |

Top-level keys verified: `SCAFFOLD.yaml` = scenario/domain_name/api_prefix/complexity_profile/response_envelope/entities/state_machines/concurrency_rules/calculations/validations/endpoints/errors/roles (no design keys); each design file carries exactly one top-level key.

Domain model: 14 entities (Facility, StatePolicy, MammographyUnit, Personnel, QualificationCredit, PhysicistSurvey, AnnualInspection, ClinicalImageReviewSubmission, Exam, NotificationLetter, SupplementalScreeningOrder, RadiologistAuditCycle, EquipmentFailureEvent, RepeatImagingRecord), 67 endpoints, 7 roles (4 opaque + 3 `entity_backed:Personnel`), 42 validations, 68 errors, 12 calculations, 3 OCC rules, 15 state machines across 11 entities (parallel shape: Exam carries three independent dimensions; MammographyUnit carries accreditation_status + operational_state). Profile: `compliance_audit` / `posture_driven_gating`, layers `[cascading_side_effects, dual_variant_calculation, optimistic_concurrency, ops_run_checkpoint]`, graph topology, `segregation_of_duties` role model, immediate consistency.

§1.8 — 9 rules / 24 instances: dual_variant_calc 3, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2.

§1.9 — 9 sections / 91 instances (63 full recipes + 28 `excluded_because` stubs): entities 12 (10/2), state_machines 13 (9/4), calculations 18 (8/10), validations 18 (15/3), endpoints 7 (4/3), errors 9 (5/4), rbac 6 (6/0), cross_cutting_complexity_layers 6 (4/2), consistency_model 2 (2/0).

Three genuine scaffold defects found and fixed in `SCAFFOLD.yaml` while auditing §1.5:

1. **Undeclared transition** — `SUBMITTED -> DENIED_FINAL` unconditionally suspends the unit, but a never-accredited unit never passes through PROBATION, so `MammographyUnit.accreditation_status PROVISIONAL -> SUSPENDED` was reachable yet undeclared. Added.
2. **Unreachable error** — `ERR_REACCREDITATION_ATTEMPTS_EXHAUSTED` was at priority 70, but attempts can only hit 0 via the denial that also suspends the unit, so priority 53 (`ERR_UNIT_ACCREDITATION_SUSPENDED`) permanently masked it and the resubmit path can never see attempts == 0. Moved the guard to priority 43 (ahead of 53, with the rationale recorded in the `check:` text); `ERR_UNIT_ACCREDITATION_SUSPENDED` is now driven instead through the `restore` path, which is the one endpoint where 53 is the first guard reached.
3. **Unreachable error** — `ERR_EXAM_NOT_AMENDABLE` was masked by the priority 6 ownership check, since an uninterpreted exam has a null `interpreting_physician_id` that no actor can match. Priority 6's check is now null-guarded so the request falls through to priority 40.

Also fixed one illegal `grounds:` entry in the difficulty file (`state_machines.ClinicalImageReviewSubmission.status.SUBMITTED`, a bare state → `entities.ClinicalImageReviewSubmission.fields.status`). Independent self-checks confirm: all 68 errors are now driven by at least one instance across the two design files, all grounds resolve against §1.1–§1.7, all 115 instance names are globally unique, and every `${placeholder}` in every recipe is captured earlier in the same instance.

## Step 3: Copy shared files — 2026-09-03T10:28:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T10:46:00.000Z

PRD complete and verified.

**File:** `workspace/PRD.md` — **530 lines**

**Section list**
- `# Mammography Accreditation & Breast Density Notification API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim fixed block, byte-identical to `section-2.2-response-structure.md`, confirmed programmatically) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and Mutation Counters · 2.5 The Logical Clock · 2.6 Resolving the Governing State Policy · 2.7 Precision, Rounding and Conserved Quantities · 2.8 The Validation Ladder · 2.9 Optimistic Concurrency on Units and Exams · 2.10 Facility Compliance Posture and Cascade Discipline
- `## 3. Business Logic & Workflows` — 9 subsections: 3.1 Policy Foundations, Facility Registration and the Accreditation-Fee Account · 3.2 Staffing the Facility · 3.3 Physicist Surveys, Equipment Failures and the Service Dimension · 3.4 The Accreditation Cycle · 3.5 Annual Inspections and Corrective Actions · 3.6 The Exam Record · 3.7 Patient Notification · 3.8 Supplemental Screening · 3.9 The Medical Outcomes Audit and the Compliance-Run Checkpoint (contains one `####` lead-in for the five-sweep compliance run, keeping §3 within the 5–9 subsection range)
- `## 4. Endpoint Definitions`
- `## 5. Error Code Catalogue`

**Coverage confirmation (all machine-checked against SCAFFOLD.yaml)**
- **Endpoints: 67/67.** §4 table has exactly 67 rows × 4 columns; the (method, path) set is set-equal to the scaffold's, zero missing, zero extra. Authorized-role cells match `endpoints[].roles` exactly on all 67 rows (0 mismatches).
- **Errors: 68/68.** §5 table has exactly 68 rows × 2 columns; the (error_id, http_status) set is set-equal to the scaffold's (symmetric difference empty). Additionally every one of the 68 IDs is also named in §2/§3 narrative prose, and **zero invented error IDs** appear anywhere (one early slip, `ERR_INVALID_PERIOD`, was found and corrected to `ERR_INVALID_REQUEST`, priority 20, which is what actually guards `period_end > period_start`).
- **Validations: 42/42** — §2.8 renders the full ladder as 42 ordered steps with error ID, HTTP status and exhaustive `applies_to` scope.
- **Calculations: 12/12**, including both dual-variant pairs (`IMAGE_BASED`/`PATIENT_BASED` repeat rate, `PPV1_SCREENING`/`PPV3_BIOPSY_ALL`) with symmetric branch treatment. Every numeric constant declared in `calculations[].constants` appears literally in the prose (0 missing).
- **State machines: 15/15, all 76 transitions.** Every `from`/`to`/initial/terminal state string appears verbatim (0 missing), as do all enum `constraints` values across all 14 entities (0 missing).
- **Concurrency: 3/3 rules** plus the fourth OCC-bearing endpoint (withdraw); independently confirmed that exactly 4 scaffold endpoints accept a version field, matching §2.9's "no other endpoint accepts a version field."
- **Roles: 7/7** named verbatim with identity semantics; **entities 14/14**, and Contract 1's full required-identifier set is covered.

**Hard Contract reports**
- **Contract 1 (Field-Name Coverage): PASS** — 164 required identifiers (148 entity field names + endpoint `request_body`/`query_params`/`path_params` identifiers, deduped); 164 found in backticks, **0 missing**.
- **Contract 2 (Rule Coverage): PASS** — 42/42 validations with priority ordering, 3/3 OCC rules, all cross-entity cascades (incl. the 5-level chains and the amendment fan-out), all `applies_to` scopes, field-level defaults/ranges, sibling-branch symmetry on both dual-variant calculations and both federal-floor/state-layered notification regimes, 76/76 transitions, 12/12 calculations.
- **Contract 3 (§3 Path Purity): PASS** — backtick tokens scanned in §3: 1199; tokens starting with `/`: 0; bare HTTP-method tokens: 0; method+path combined tokens: 0 (also 0 tokens containing `/` at all).

**Tail verification:** `tail -18` shows the file ending on the final row of the §5 error table, `| ERR_INSUFFICIENT_PREPAID_CREDIT | 402 |` — a real section boundary, no truncation mid-sentence, no audit footer, and no contract reports leaked into the document. Built incrementally (1 Write + 8 heredoc appends), with `wc -l` checked after each. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced, and no sibling task directory was read.

**Orchestrator truncation check (independent):** `wc -l` = 530, `wc -c` = 119198. `tail -25` ends at `| ERR_INSUFFICIENT_PREPAID_CREDIT | 402 |`, a complete table row at a real section boundary. §4 spans lines 383–457 (67 endpoint rows) and §5 spans 457–530 (68 error rows). Not truncated; no regeneration needed.

## Step 6: Generate implementation — 2026-09-03T11:24:00.000Z

Implementation is complete and verified.

## Files written
`workspace/implementation/`

| file | lines | bytes |
|---|---|---|
| `app.py` | 63 | 1840 |
| `common.py` | 659 | 22555 |
| `services.py` | 783 | 30038 |
| `routes_core.py` | 349 | 13707 |
| `routes_units.py` | 529 | 20086 |
| `routes_personnel.py` | 209 | 7905 |
| `routes_exams.py` | 719 | 27183 |
| `requirements.txt` | 1 | 11 |
| `start.sh` (chmod +x) | 10 | 399 |
| **total** | **3322** | |

No `__pycache__`, no db/json/tmp artifacts left behind. Storage is a plain in-memory `Store` (14 dicts) that boots empty — nothing is seeded, preloaded or read from disk. `start.sh` pip-installs Flask only if `import flask` fails, then `exec python3 app.py` on `0.0.0.0:$PORT` (default 10000), no reloader, so it boots clean from a fresh process every invocation.

## Coverage
- **67 endpoints registered = 67 declared** in SCAFFOLD (`grep -c '^  - method:'` → 67), across 4 blueprints.
- 68 error ids in `ERROR_STATUS` with the PRD-mandated HTTP statuses, plus 3 transport fallbacks (`ERR_NOT_FOUND` 404 unknown route, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500).
- 42 validations, 12 calculations, 15 state machines, 3 OCC rules, 7 roles.

## Key design decisions
- **Validation ladder (§2.8)** — priorities 1–2 (auth, role) live in the `@endpoint(roles)` decorator; every handler then re-states its remaining rungs in explicit numeric order. Priority 3 (actor-at-facility) is necessarily split: resolve the actor's Personnel row by `role_type` (403 if absent) → path/body lookup (404) → facility comparison (403), because the target's facility is unknowable before the 404.
- **Versioning (§2.4)** — a per-request `g.touched` set guarantees `updated_at`/`version += 1` fire at most once per entity per request; `new_entity` self-marks so fresh rows stay at version 1. `credit` is version-less.
- **Cascades** — 5-level survey-failure chain, 3-level DENIED_FINAL, first-match-wins facility posture, one-way referral cascade with pinned ordering (`exam.performed_at`, then `order.created_at`), and amendment fan-out that flips LOCKED audit cycles covering `performed_at` to AMENDED.
- **OCC** — `expected_unit_version` (CIRS create/resubmit/withdraw) and `expected_exam_version` (letter generate) → `ERR_STALE_UNIT_VERSION` / `ERR_STALE_EXAM_VERSION`, 412.
- **Money/percent** — `Decimal` + `ROUND_HALF_UP`; ratios pooled then rounded once at 2dp; cents rounded to whole.
- **Letter supersession** — `supersedes_letter_id` points at the exam's most recent prior letter regardless of that letter's status (null only for the first), while only non-SUPERSEDED priors are transitioned to SUPERSEDED. Satisfies both PRD sentences.
- Fixed during generation: the density **statement** enum uses underscores (`FDA_DENSE`/`FDA_NOT_DENSE`) while the notice **codes** use hyphens (`FDA-DENSE`/`FDA-LAY-SUMMARY`) — these were conflated and are now separate constants.

## Smoke tests (four scripted runs, all green)
Exercised: clock forward-only, state policy, facility, funding deposit, unit, personnel, physicist surveys (fail → cascade to PROBATION/FAILED/CONDITIONAL → remediate PASS → CURRENT), CIRS (escrow 250000 → consume → resubmit attempt 2 → PASS ⇒ ACCREDITED, expires clock+1095d, attempts reset to 3), equipment failure (OUT_OF_SERVICE → `ERR_POST_REPAIR_SURVEY_MISSING` → POST_REPAIR PASSED → REPAIR_VERIFIED → IN_SERVICE → `ERR_FAILURE_ALREADY_RESOLVED`), LEVEL_1 inspection ⇒ SUSPENDED then COMPLIANT on close, exams/interpret/amend/outcome, letters (generate/send/undeliverable/reissue chain verified), supplemental orders (coverage TIER_1 19373/12127 and PATIENT_RESPONSIBILITY 120000 under mandate NONE, closed-endpoint capacity conflict, completion gating), repeat records + retraction ledger reversal, audit cycles (overlap, segregation of duties, close, amendment fan-out, re-close), credits + qualification review (GRACE with `ce_deadline_at = clock + 90d`), compliance runs, and ~25 distinct error ids with correct statuses.

Final fresh-boot check on port 21851 confirmed empty state (`total_count: 0` on exams/letters/repeat-records), correct envelope shape and `meta` keys, `ERR_INVALID_REQUEST` 400 on `limit=101`, `ERR_UNIT_NOT_FOUND` 404, `ERR_UNAUTHENTICATED` 401 on missing headers, `ERR_FORBIDDEN_ROLE` 403 on role mismatch. Every smoke server was killed by exact pid (3687807, 3701057, 3713855, 3719375/3719373, 3733995/3733992); no pattern-kill was ever used, and both ports are confirmed free.

## Step 5: Generate unit tests — 2026-09-03T12:03:00.000Z

Test generation for task_2544 is complete. Both output directories are final and audited.

## Files written

`test_helpers/` (9 files, 3037 lines)
| file | lines |
|---|---|
| `__init__.py` | 46 |
| `api_client.py` | 391 (72 endpoint methods) |
| `api_errors.py` | 180 |
| `assertions.py` | 485 |
| `constants.py` | 292 |
| `factories.py` | 461 |
| `fixtures.py` | 757 |
| `test_users.py` | 91 |
| `types.py` | 324 |

`test_suite/` (19 files, 6233 lines, 111 tests)
| file | lines | tests |
|---|---|---|
| `conftest.py` | 70 | — |
| `test_01_dual_variant_calc.py` | 278 | 6 |
| `test_02_combinatorial_formula.py` | 239 | 6 |
| `test_03_non_linear_state_machine.py` | 298 | 6 |
| `test_04_transitive_cascade.py` | 185 | 4 |
| `test_05_priority_pair_validation_conflict.py` | 288 | 6 |
| `test_06_boundary_precision_check.py` | 257 | 6 |
| `test_07_cross_entity_state_dependency.py` | 297 | 6 |
| `test_08_resource_temporal_overlap.py` | 179 | 4 |
| `test_09_compensating_invariant.py` | 174 | 4 |
| `test_10_entities.py` | 423 | 10 |
| `test_11_state_machines.py` | 453 | 9 |
| `test_12_calculations.py` | 542 | 8 |
| `test_13_validations.py` | 785 | 15 |
| `test_14_endpoints.py` | 321 | 4 |
| `test_15_errors.py` | 455 | 5 |
| `test_16_rbac.py` | 528 | 6 |
| `test_17_cross_cutting.py` | 342 | 4 |
| `test_18_consistency_model.py` | 129 | 2 |

## Coverage

- **Queue A (Difficulty): 48 tests** — all 24 non-stub §1.8 instances, each translated by exactly **2** tests.
- **Queue B (Corner): 63 tests** — all 63 non-stub §1.9 instances, each translated by exactly **1** test. The 28 `excluded_because:` stubs were not translated. Sections: entities 10, state_machines 9, calculations 8, validations 15, endpoints 4, errors 5, rbac 6, cross_cutting 4, consistency_model 2.
- **Total 111 tests; 0 instances skipped** — every non-stub instance passed the PRD-first two-condition filter.

## Verification performed

- `pytest --collect-only`: **111 tests collected, no collection errors**.
- `pyflakes` clean on all of `test_suite/*.py` and `test_helpers/*.py` (only the intentional re-export warnings in `test_helpers/__init__.py` remain; I removed 4 genuinely unused imports from tests 02/03/04 and 6 from `fixtures.py`).
- Automated design-citation audit: exactly one `Design:` line per test, every tag resolves to a real `name:` in the source yaml, no stub translations, no duplicate Corner tags, every Difficulty tag count == 2.
- Automated PRD-citation audit: every docstring's `PRD: "…"` block matched verbatim (whitespace-normalized) against `workspace/PRD.md`. This caught 4 citations that were truncated mid-sentence (`test_10` ×2, `test_12` ×2); all four were extended to full verbatim PRD sentences and re-verified.
- No implementation directory or sibling task was read; all assertions derive from PRD.md.

## PRD / design defects worth reporting upstream

Where a design instance contradicted the PRD, the test asserts the **PRD-derived** outcome.

- **(a)** Difficulty `amendment_cascades_three_levels_and_reopens_a_completed_obligation` — self-contradictory `interpreted_late` assertion; PRD derives `true`.
- **(b)** Anchor `&c_unit2` is defined inconsistently between the two design files (difficulty: GE/PRI-2200/…/2027-09-30 vs corner: GE/SEL-9002/…/2027-06-30); tests pass explicit overrides.
- **(c)** Corner `state_machines/undeliverable_letter_is_superseded_by_the_reissued_letter` expects `LAY_SUMMARY` + 2 notice codes for a density-B exam under CT `STATE_ENHANCED_ALL`; PRD line 313 derives `COMBINED` + 4 codes.
- **(d)** Corner `calculations/audit_metrics_exclude_diagnostic_unread_and_period_end_exams` expects `recall_flag == true` on a DIAGNOSTIC BI-RADS 0; PRD line 291: "a diagnostic BI-RADS 0 is not a recall" → `False`.
- **(e)** Corner `validations/screening_interpretation_without_a_density_category_is_rejected` expects an interpreted DIAGNOSTIC exam to keep `notification_status == NOT_REQUIRED`; PRD line 291 opens the obligation unconditionally → `PENDING`.
- **(f)** **PRD typo:** line 351 names the audit-subject role error `ERR_NOT_INTERPRETING_PHYSICIAN`, but the priority ladder (line 153) and the canonical error table (line 513) both name it `ERR_NOT_AN_INTERPRETING_PHYSICIAN` (the un-prefixed code is the priority-6 amendment-ownership code). Tests assert `ERR_NOT_AN_INTERPRETING_PHYSICIAN`.
- **(g)** Corner `consistency_model/a_write_and_its_derived_fields_are_visible_in_the_same_response` expects `recall_flag == true` for a SCREENING BI-RADS 4; PRD line 291: "a screening BI-RADS 4 is not a recall either" → test asserts `False`.
- **(h)** **PRD internal conflict on `units_survey_overdue`.** Line 381 says a replayed run "reports zeros across all seven counters", but the field reads as a census (a fresh unit is `OVERDUE` at creation per line 217, which is why both design instances expect `1` on the *first* run — no unit ever "moves"). Both readings cannot hold. The replay test asserts the six unambiguous movement counters are `0` and deliberately does not pin `units_survey_overdue` on the second run; the first run still asserts `1`, consistent with `test_12`. Worth disambiguating in the PRD.

## Step 7: Run tests and iterate — 2026-09-03T12:35:00.000Z

All green. Final state: **111/111 passing in all 8 parallel rounds.**

## Summary

**Iterations run: 2.** Iteration 1 showed a perfectly deterministic 10 failures (identical set in all 8 rounds — no flakiness, no reaping; every round ran to completion at ~206s). Iteration 2 after fixes: 8/8 rounds at 111 passed / 0 failed / 0 errors.

**Tests deleted: none.** No test asserted a scaffold-only rule.

**Assertions removed for PRD non-derivability (STEP 1c partial coverage):**
- `units_survey_overdue` pin dropped from `test_12_calculations.py::test_compliance_run_sweeps_are_order_insensitive_and_respect_the_due_date_edge` and `test_17_cross_cutting.py::test_the_compliance_run_checkpoint_is_a_no_op_when_replayed_at_the_same_instant`. **Category: PRD internal conflict → non-unique derivability.** PRD line 381 names the field but never says whether it counts units *moved* into `OVERDUE` this sweep or censuses units sitting in `OVERDUE` afterwards; the two readings diverge for a unit that is `OVERDUE` at creation (line 217), and line 381's own "the second run finds nothing left to move and reports zeros across all seven counters" supports the movement reading while the field name supports the census. Both PRD-faithful implementations exist, so no single value is derivable. Every other counter and all state assertions in both tests were kept. (Scaffold rules that drove these: `Corner/calculations/compliance_run_sweeps_are_order_insensitive_and_respect_the_due_date_edge`, `Corner/cross_cutting_complexity_layers/the_compliance_run_checkpoint_is_a_no_op_when_replayed_at_the_same_instant`.) **This PRD conflict is worth fixing upstream** — it is the same item (h) the test generator already flagged.

**Fixes to `test_helpers/` (1):**
- `test_helpers/fixtures.py::acquire_exam` — now pops `unit_id` / `technologist_id` out of `**overrides` instead of always passing `core["unit_id"]` / `core["tech_id"]` positionally. It previously raised `TypeError: exam_payload() got multiple values for argument 'unit_id'` for any caller placing an exam on a sibling unit, which set-up-failed 4 tests across `test_02` and `test_05`. This was the single upstream fixture bug behind the largest failure bucket.

**Fixes to `test_suite/` (4) — all making the test more faithful to PRD:**
- `test_13_validations.py::test_deposit_...` — funding deposit success expected 201; PRD §4 puts "all ledger movements" at 200 and §3.1 says the deposit "answers with the refreshed facility, not with a deposit receipt". Changed to 200.
- `test_13_validations.py::test_scheduling_is_gated_on_coverage_then_on_the_appointment_instant` — asserted `ERR_COVERAGE_NOT_DETERMINED` on a `RECOMMENDED` order, but priority 40 (`ERR_ORDER_NOT_SCHEDULABLE`, §3.8: schedulable only "from `COVERAGE_DETERMINED` and from `LOST_TO_FOLLOW_UP`") masks the priority-76 gate there. Corrected that leg to `ERR_ORDER_NOT_SCHEDULABLE` and *added* a leg that reaches priority 76 the only way PRD makes it reachable: sweep four drives a `RECOMMENDED`/`UNDETERMINED` order into `LOST_TO_FOLLOW_UP`, a schedulable state, where `ERR_COVERAGE_NOT_DETERMINED` is still asserted exactly. No assertion weakened.
- `test_16_rbac.py::test_segregation_of_duties_...` — the outcome and audit-close violations were issued with `make_physician_headers`, so priority 2 returned `ERR_FORBIDDEN_ROLE` (both endpoints admit only `QualityAssuranceOfficer`). Per §2.1 the violation is an *officer* whose opaque `X-User-ID` equals the stored personnel id; switched to `make_qa_headers(core["rad_id"])`.
- `test_18_consistency_model.py::test_cross_entity_cascades_...` — asserted `CONDITIONAL` after the facility's only unit went `OUT_OF_SERVICE`, but §2.10 level one's fourth trigger ("the facility has at least one unit and every one of its units has `operational_state` `OUT_OF_SERVICE`") mandates `SUSPENDED`. Corrected.

**Fixes to `implementation/`: none.** Every failure traced to a test-layer defect or a PRD ambiguity; no implementation check was removed, weakened, or added, and nothing was seeded.

Cleanup: `__pycache__` dirs and `workspace/sweep.log` removed; `results.1..8.json` left in `workspace/implementation/` as the sweep evidence.

**Orchestrator independent verification:** read all 8 `results.{1..8}.json` directly — every one reports `111 / 111`. Step 8 is NOT skipped: Step 7 ran 2 iterations with 1 `test_helpers/` fix, 4 `test_suite/` fixes and 2 assertion removals, so the skip condition (zero of all four categories) is not met.

## Step 8: Finalize PRD — 2026-09-03T12:28:00.000Z

PRD_FINALIZED.md written. Exactly one edit was warranted; the other five Step 7 items were already uniquely determined by PRD.md.

## Line counts
- PRD.md: 530 lines; PRD_FINALIZED.md: 530 lines; 0% line delta (1 line revised in place, +463 chars).

## Changes
- **§3.9, The Compliance Run (line 381)** — *revise* — pinned `units_survey_overdue` as a movement count (units whose `survey_compliance` the sweep actually changed to `OVERDUE`), explicitly excluding units already `OVERDUE` on entry and units sweep one leaves in `FAILED` — `implementation/services.py:703-712`.

## Per-edit pre-edit search log
**Edit 1 — §3.9 `units_survey_overdue`**
- (a) Subject: the sweep-one compliance-run counter `units_survey_overdue`, and by adjacency every writer of a unit's `survey_compliance` plus every counter minted by a run.
- (b) Paths enumerated (grep `survey_compliance"] *=`, `counters[`, `survey_compliance`, then read): `services.py:688-783` (`run_compliance_checkpoint`, the sole mint site, read in full); `services.py:700-725` (sweep one, both the currency branch and the accreditation-ageing branch); `services.py:644-658` (`survey_failure_cascade`, writes `FAILED`, no counter); `services.py:661-674` (`mark_survey_currency_on_pass`, writes `CURRENT`, no counter); `routes_core.py:198` (unit creation seeds `OVERDUE` as a literal, outside any run, no counter); `services.py:234` and `routes_units.py:346` (readers only — posture level two and the probation-lift guard). Confirmed `survey_compliance` has exactly three assignment sites and only the sweep-one one increments a counter, and that a unit in `FAILED` is skipped before the counter branch is reachable.
- (c) Adjustment made: scoped the new clause to `units_survey_overdue` alone rather than making a parallel "movement count" claim about `units_marked_reaccreditation_due` — the impl increments that one at `services.py:717` even when the very next branch (`:719-723`) drives the same unit on to `SUSPENDED` in the same sweep, so a symmetric universal statement would have been a new mismatch. Also phrased the `FAILED` exclusion as "sweep one leaves in `FAILED`" (a consequence of the pre-existing line-371 no-rehabilitation rule) rather than re-stating the rule, to avoid duplicating/narrowing it.

Verification notes on the five items NOT patched (each already uniquely determined by unedited PRD prose, and impl agrees):
- Fixture `acquire_exam` `TypeError` — pure `test_helpers/` bug, no behavioral surface.
- Deposit 200 — §4 opening paragraph ("all ledger movements … return HTTP 200") plus §3.1; impl `routes_core.py:171` returns `ok_entity`.
- Schedule gate ordering — impl `routes_exams.py:663/669/673/677/684` runs 40 → 42 → 65 → 76 → 77, matching §2.8 steps 13/15/32/39/40 exactly.
- Outcome & audit-close role masking — impl `routes_exams.py:310` / `routes_personnel.py:184` admit only `QualityAssuranceOfficer`, so §2.8 priority 2 precedes priority 4 as written.
- Level-one fourth `SUSPENDED` trigger — impl `services.py:227` is a verbatim match for §2.10.

## Step 9: Complete PRD — 2026-09-03T13:05:00.000Z

**Orchestrator note on method.** Step 9 was run as THREE SEQUENTIAL file-partitioned passes over disjoint implementation files, all editing the same `workspace/PRD_COMPLETED.md`. Rationale: a single-pass scan of a 3322-line implementation reliably degenerates into a no-op (output byte-identical to input, proving the scan never really ran). Partitioning forces genuine coverage. Pass 1 created `PRD_COMPLETED.md` from `PRD_FINALIZED.md`; passes 2 and 3 edited it in place and each confirmed the prior passes' edits survived.

- Pass 1 scope: `app.py`, `common.py`, `routes_core.py` — 18 edits (13 ambiguity-pins, 5 mismatch-revisions), 119482 → 127139 bytes.
- Pass 2 scope: `services.py`, `routes_units.py` — 24 edits (19 ambiguity-pins, 5 mismatch-revisions), 127139 → 137650 bytes.
- Pass 3 scope: `routes_personnel.py`, `routes_exams.py` — 22 edits (19 ambiguity-pins, 3 mismatch-revisions), 137650 → 144710 bytes.

**Totals: 64 edits — 51 ambiguity-pins, 13 mismatch-revisions.** Source `PRD_FINALIZED.md` 530 lines / 119482 bytes → `PRD_COMPLETED.md` 530 lines / 144710 bytes (+25228 chars, +21.1%; 0 line delta — every edit is an in-paragraph insert or revision, no new sections).

### Pass 1 changes (app.py / common.py / routes_core.py)
- §2.1 — revise — mismatch — PRD said role names must be "spelled exactly"; impl strips surrounding whitespace on both headers (whitespace-only = empty; padded role accepted; trimmed `X-User-ID` is what ownership checks use) — `common.py:487-499`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9` (24 total) — `common.py:378-380`
- §2.2 — insert — ambiguity — `api_request_timestamp` reads the logical clock, not wall time, rendered *after* the request's effects — `common.py:383-387`
- §2.3 — insert — ambiguity — non-integer/empty `limit`/`offset` is `ERR_INVALID_REQUEST`; pagination validated inside the list response, hence after path-id resolution — `common.py:429-449`
- §2.3 — insert — ambiguity — `created_at` ties broken by creation sequence, never `id`; filter → sort → page window order; `has_more` false and empty `data` when `offset >= total_count` — `common.py:403-417`, `452-453`
- §2.3 — insert — ambiguity — empty-string filter treated as absent; exact string equality so unknown values yield an empty page rather than 400; `retracted` accepts `true/false/1/0` case-insensitively — `common.py:456-475`
- §2.4 — insert — ambiguity — `version` advances at most once per accepted request regardless of how many fields/cascade levels touch the entity; a resource created by the request stays at `version` 1 — `app.py:30-33`, `common.py:240-269`
- §2.5 — insert — ambiguity — `current_utc` must be a non-empty ISO-8601 string (400 before the rewind guard); reply is a bare two-field object; display strings echoed byte-for-byte when they end in `Z`; `previous_utc` is the prior displayed string, `2026-08-01T00:00:00Z` on first set — `routes_core.py:26-48`
- §2.8 step 8 — insert — ambiguity — five schema conventions: explicit `null` = omitted; absent body = `{}` while a non-object/malformed body is 400; booleans never accepted for numbers; required strings non-empty and list/enum-list rules; timestamp parsing accepts `Z`/offset/zoneless-as-UTC — `common.py:533-646`
- §2.8 step 41 — revise — mismatch — missing/`null` `amount_cents` is `ERR_INVALID_REQUEST` 400, only a present-but-not-positive-integer value is `ERR_INVALID_DEPOSIT_AMOUNT` 422 — `routes_core.py:164-169`
- §3.1 — insert — ambiguity — store starts completely empty on every boot; first possible write is a state-policy registration — `app.py:1-6`, `common.py:210-233`
- §3.1 — insert — ambiguity — the `urgent <= report` turnaround comparison uses *effective* (post-default) values — `routes_core.py:67-72`
- §3.1 — revise — mismatch — `memo` accepted and discarded, no deposit entity persisted, no deposit list endpoint; deposit bumps facility `version` once and leaves held/consumed untouched — `routes_core.py:159-171`
- §3.1 — insert — ambiguity — `accreditation_expires_on` is exempt from the no-future-backdating rule; `model_serial` uniqueness spans all units of the facility in any state, checked after schema validation — `routes_core.py:182-187`
- §3.2 — revise — mismatch — attested figures are whole integers (unlike two-decimal `ce_hours`); `modality_certifications` stored in order with duplicates allowed; enrollment does not recompute facility posture — `routes_core.py:229-256`
- §3.5 — revise — mismatch — `closure_note` accepted and discarded, not persisted — `routes_core.py:338-349`
- §3.9 — insert — ambiguity — the compliance run ignores any request body outright — `routes_core.py:313-319`
- §4 — insert — ambiguity — trailing slash insignificant (`strict_slashes = False`), no redirect — `app.py:22`
- §5 — insert — ambiguity — three transport-level identifiers outside the 68-code catalogue and outside the ladder: `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500 — `app.py:39-53`, `common.py:112-115`

Pass 1 verified as already uniquely pinned (no change): the 68-entry error→status table matches `ERROR_STATUS` exactly (programmatically diffed); envelope shapes; `id` as bare UUID; credit rows carrying only `id`/`created_at`; `round2`/`cents_half_up` half-up rounding; auth-before-body-parse and schema-before-uniqueness ordering; three-level first-match-wins posture ladder; creation defaults; inspection corrective-action offsets (+15/+30 days); nine-field compliance-run result shape.

### Pass 2 changes (services.py / routes_units.py)
- §2.7 — insert — ambiguity — CE-hour sums that land whole are reported as integers, not `15.0` (`common.py:178` `dsum`, used at `services.py:529`).
- §2.8 step 8 — insert — ambiguity — the 1-char minimum applies to *optional* strings too, so `""` notes are rejected (`routes_units.py:76,128,220,330,424`).
- §2.10 — insert — ambiguity — a recompute landing on the posture already held is a no-op: no `updated_at`/`version`, no cascade re-fire (`services.py:250-261`).
- §2.10 — insert — ambiguity — the referral note is one fixed server-authored sentence; exam step fires only out of `PENDING`; final tie-break is creation sequence (`services.py:264-282`).
- §3.2 — insert — ambiguity — a qualification review writes six fields and bumps `version` only if one differs, so a same-clock re-review is inert; `INACTIVE` is never moved (`services.py:530-572`).
- §3.3 — insert — ambiguity — measurement overwrite is asymmetric: omitting `critical_deficiency_codes` clears it, omitting `outcome_note` preserves it (`routes_units.py:150-154, 187-191`).
- §3.3 — revise — mismatch — on a pass, the unit's `version` advances only if `last_passed_survey_end`/`survey_compliance` changed; a past-window pass can leave `FAILED` standing (`services.py:661-674`).
- §3.3 — revise — mismatch — the survey-failure cascade bumps the unit's `version` only when it actually rewrote a field; already-`PROBATION`/`SUSPENDED` keeps its status (`services.py:644-658`).
- §3.3 — insert — ambiguity — `FAILED_FINAL` writes only `operational_state`; `survey_compliance`/`accreditation_status` untouched; no bump if already out of service (`routes_units.py:202-209`).
- §3.3 — insert — ambiguity — failures may be filed against a unit in any state; already-OOS means no unit bump; a non-qualifying failure recomputes no posture (`routes_units.py:458-473`).
- §3.3 — insert — ambiguity — restoring a *non-qualifying* failure needs no survey and still returns an OOS unit to service, whatever put it there (`routes_units.py:505-527`).
- §3.4 — insert — ambiguity — the "never `ACCREDITED`" exemption is an internal one-way latch, not a status read (`routes_units.py:253-257, 352`).
- §3.4 — insert — ambiguity — `deficiency_categories` supplied with a `PASS` are validated then discarded (`routes_units.py:342-356`).
- §3.4 — revise — mismatch — on the probation-blocked *and* suspended-unit routes the unit is not written at all: no expiry reset, no attempt restore, no `version` advance (`routes_units.py:345-353`).
- §3.4 — insert — ambiguity — the no-demotion revision routes leave the unit row untouched (`routes_units.py:360-362`).
- §3.4 — revise — mismatch — it is the **third** `REVISION_REQUIRED` verdict (three filings), not the fourth, that suspends the unit; resubmit clears `reviewed_at`/`review_decision` but keeps `deficiency_categories` (`routes_units.py:398-409`).
- §3.4 — insert — ambiguity — `withdrawal_reason` is validated then discarded (`routes_units.py:424`).
- §3.6 — insert — ambiguity — `open_notice_obligations` is recounted from scratch and the facility written only on a delta (`services.py:367-374`).
- §3.7 — insert — ambiguity — a null `density_category` counts as not dense (`services.py:381`).
- §3.8 — insert — ambiguity — `SCHEDULED` and `LOST_TO_FOLLOW_UP` orders are outside the referral's reach (`services.py:270`).
- §3.9 sweep 1 — revise — mismatch — `REACCREDITATION_DUE` *does* degrade posture to `CONDITIONAL` (PRD claimed it does not, contradicting its own §2.10 and `services.py:231`); plus unit visit order, the "greatest `effective_end`, later-created wins, all types pooled" definition of most-recent pass, and the single-visit `ACCREDITED`→`REACCREDITATION_DUE`→`SUSPENDED` chain still counting in `units_marked_reaccreditation_due` (`services.py:677-682, 701-725`).
- §3.9 sweep 3 — insert — ambiguity — ordering by `sent_at`, `created_at`, sequence; counter counts letters, exam move is conditional (`services.py:739-750`).
- §3.9 sweep 5 — insert — ambiguity — personnel visit order, home-policy `ce_grace_days`, and exactly which transitions the two counters count (`services.py:766-773`).
- §3.9 close-out — insert — ambiguity — `open_notice_obligations` recounted once before the single posture recompute; sweep-4 losses are unreachable by the referral cascade; the facility's `version` advances on every run (`services.py:775-778`).

### Pass 3 changes (routes_personnel.py / routes_exams.py)
- §2.3 — revise — mismatch — added `density_category` to the global filter enumeration (impl exposes it on `GET /exams`) — routes_exams.py:186
- §3.2 (credits) — insert — ambiguity — pinned the credit row's exact serialized field set, the type-forbidden amount field present-and-null, and null-not-absent `modality`/`source_note` — routes_personnel.py:72-81 + common.py FIELDS
- §3.2 (qualification review) — insert — ambiguity — `review_note` is never read: not type-checked, not stored, any JSON value accepted — routes_personnel.py:97
- §3.6 (acquisition) — insert — ambiguity — priority-3 membership is split: `TECHNOLOGIST` personnel resolution before the body, the three facility/self-attribution comparisons after priority 25, all three as `ERR_ACTOR_NOT_AT_FACILITY`; `unit_id` resolved before `technologist_id` — routes_exams.py:87,99-115
- §3.6 (acquisition) — insert — ambiguity — the facility row is not written: no posture and no `open_notice_obligations` recompute — routes_exams.py:165
- §3.6 (exam list) — revise — mismatch — added `density_category` to the exam filter list — routes_exams.py:186
- §3.6 (amend payload) — insert — ambiguity — `amendment_reason` validated then discarded; modality certification deliberately not re-checked — routes_exams.py:260
- §3.6 (amend) — insert — ambiguity — `interpreted_at`/`report_due_at`/`interpreted_late` untouched (no urgent re-tightening) and `follow_up_status` untouched even when `recall_flag` newly true — routes_exams.py:276-295
- §3.6 (amend) — revise — mismatch — level two supersedes **every** `QUEUED`/`SENT`/`DELIVERED_ASSUMED` letter in ascending `created_at`, leaving `UNDELIVERABLE` and already-`SUPERSEDED` alone; level three fires only if something was actually superseded — routes_exams.py:284-295
- §3.6 (outcome) — insert — ambiguity — no `report_status` gate; write reaches only the exam — routes_exams.py:311-334
- §3.6 (repeat records) — insert — ambiguity — gated on nothing but the pairing and the failure's unit; unit state and exam report state irrelevant; failure may be `OPEN` or resolved — routes_exams.py:340-382
- §3.7 (generation) — insert — ambiguity — precondition failure is `ERR_LETTER_NOT_SENDABLE` (409); `dispatch_channel` is inert bookkeeping — routes_exams.py:449-453,473
- §3.7 (supersession) — revise — mismatch — `supersedes_letter_id` is the most recently created previous letter *whatever its status*; the supersession step rewrites every non-`SUPERSEDED` letter including `UNDELIVERABLE` — routes_exams.py:461-480
- §3.8 (recommend) — insert — ambiguity — `recommendation_note` discarded; no facility-posture gate, and a `SUSPENDED`-facility order stays `RECOMMENDED` — routes_exams.py:566-599
- §3.8 (recommend) — insert — ambiguity — `follow_up_status` forced to `PENDING` out of any value; already-`PENDING` exam not written — routes_exams.py:596-598
- §3.8 (coverage) — insert — ambiguity — density re-check runs after the state precondition and reports `ERR_EXAM_NOT_ELIGIBLE_FOR_SUPPLEMENTAL` (422) — routes_exams.py:634-640
- §3.8 (schedule) — insert — ambiguity — already-`PENDING` exam not written — routes_exams.py:690-692
- §3.8 (complete) — insert — ambiguity — `completion_note` discarded; non-terminal = outside `COMPLETED`/`REFERRED_OUT`, so a `LOST_TO_FOLLOW_UP` sibling blocks and a `REFERRED_OUT` one does not — routes_exams.py:701,713-718
- §3.9 (cycle open) — insert — ambiguity — periods are not subject to no-future-backdating — routes_personnel.py:116-120
- §3.9 (cycle open) — insert — ambiguity — half-open overlap geometry (adjacency allowed), all statuses compared, `OPEN` rejection ignores periods entirely — routes_personnel.py:126-134
- §3.9 (cycle open) — insert — ambiguity — create writes only the new row; no personnel/facility touch, no posture run — routes_personnel.py:136-153
- §3.9 (metrics preview) — insert — ambiguity — `?variant=` empty defaults; unknown variant is `ERR_INVALID_REQUEST` 400 (not ignored); bare object with no id/timestamps/version/pagination; always recomputed live so it can disagree with frozen fields — routes_personnel.py:171-180
- §3.9 (close) — insert — ambiguity — close writes only the cycle; no posture recompute — routes_personnel.py:200-209

### Pass 3 closing checks
**§5 error-catalogue check:** every id emitable from `routes_personnel.py`/`routes_exams.py` is present with the matching status — personnel side (`ERR_PERSONNEL_NOT_FOUND`, `ERR_AUDIT_CYCLE_NOT_FOUND`, `ERR_STATE_POLICY_NOT_FOUND` 404; `ERR_INVALID_REQUEST` 400; `ERR_FUTURE_TIMESTAMP`, `ERR_NOT_AN_INTERPRETING_PHYSICIAN` 422; `ERR_AUDIT_CYCLE_OVERLAP`, `ERR_AUDIT_CYCLE_NOT_CLOSABLE`, `ERR_AUDIT_PERIOD_NOT_ELAPSED` 409; `ERR_SEGREGATION_OF_DUTIES` 403) and exam side (all 36 codes, incl. `ERR_STALE_EXAM_VERSION` 412, `ERR_SUPPLEMENTAL_CAPACITY_CONFLICT` 409 via services). Cross-checked against `common.ERROR_STATUS`: no catalogue entry is contradicted. One residual note recorded by pass 3: ladder step 38 scopes `ERR_EXAM_NOT_ELIGIBLE_FOR_SUPPLEMENTAL` to `POST /exams/{id}/supplemental-orders`; the coverage-determination path can also emit it, which pass 3 pinned in §3.8 prose rather than rewriting the ladder step (that path is unreachable in practice, since `density_category` can never be nulled once set).

**Structural integrity:** 28 headings, identical to `PRD_FINALIZED.md`; §4 endpoint table = 67 rows; §5 error table = 68 rows; file ends at a real boundary — last line `| `ERR_INSUFFICIENT_PREPAID_CREDIT` | 402 |`.

### Orchestrator independent verification of Step 9
- `wc -l -c`: PRD.md 530/119198, PRD_FINALIZED.md 530/119482, PRD_COMPLETED.md 530/144710. `PRD_COMPLETED.md` is emphatically NOT byte-identical to its source — `diff PRD_FINALIZED.md PRD_COMPLETED.md` reports 118 changed lines (59 revised line-pairs), so the scan demonstrably ran in all three passes.
- Heading count 28, unchanged from PRD_FINALIZED.md — no sections added or lost.
- §4 table = 69 pipe lines (header + separator + 67 endpoint rows) ✓. §5 = 68 `ERR_` rows ✓.
- `tail -2` ends on the complete final table row `| `ERR_INSUFFICIENT_PREPAID_CREDIT` | 402 |` — a real section boundary, not a mid-sentence truncation.
- Step 9 touched documentation only; `implementation/` and `test_suite/` were not modified after Step 7, so the clean 8-round sweep (`results.1..8.json`, all `111 / 111`) remains the standing evidence and all 8 files are present in `workspace/implementation/`.

**PIPELINE COMPLETE.** `workspace/PRD_COMPLETED.md` written.
