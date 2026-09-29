# Worklog — task_2684_contractor_safety_prequalification

## Step 1: Create task directory — 2026-09-04T06:04:34.236Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2684_contractor_safety_prequalification` and its `workspace/` subdirectory. Index 2684 was pre-assigned by the orchestrating prompt (no auto-allocation scan, since up to 32 pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-04T07:26:00.000Z

All three scaffold artifacts are complete and the lint is clean.

## Files (`/home/ubuntu/github/CodingPRD/tasks/task_2684_contractor_safety_prequalification/`)

| file | bytes | lines |
|---|---|---|
| `SCAFFOLD.yaml` | 153,943 | 2,701 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 139,610 | 2,136 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 217,222 | 3,368 |

## Contents

**SCAFFOLD.yaml** (§1.0–§1.7 only; no design keys): 14 entities, 10 state machines, 2 concurrency rules, 18 calculations, a 30-step ordered validation ladder, 52 endpoints, 36 errors, 4 roles (NetworkAdmin / ContractorAdmin / ClientSafetyManager / VerificationAnalyst with a segregation-of-duties bar). Profile: compliance_audit + posture_driven_gating, graph topology, cyclic state machines, `immediate` consistency, layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 9 rule_ids x 2 = 18 instances, all with executable `setup_api_calls` chains and pre-computed literals (composite scores 80.51 provisional / 77.06 final, the 63.14-vs-forbidden-63.13 rounding-order case, tier band ceilings, EMR 1.00/1.01 boundary, aggregate depletion 1,750,000).

**SCAFFOLD_CORNER_DESIGN.yaml**: 9 sections / 71 instances — 50 executable recipes + 21 `excluded_because` stubs, all citing §1.8 instances that exist by name:
entities 12, state_machines 15, calculations 11, validations 8, endpoints 6, errors 9, rbac 3, cross-cutting complexity layers 6, consistency model 1. Both §1.2.1 concurrency rules get their own OCC stale-version recipe; all four declared complexity layers and the `immediate` consistency model are covered.

## Lint verdict (verbatim, first and only run)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2684_contractor_safety_prequalification/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2684_contractor_safety_prequalification/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2684_contractor_safety_prequalification/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     50
  Calls scanned (§1.8+§1.9):  886

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Coverage audit

- **Errors**: all **36/36** error ids are triggered inside an *executable* recipe (verified by scanning only instances that carry a `test_recipe`); 23 are exercised by exactly one recipe, the rest by several. Ladder-precedence pairs are asserted explicitly (e.g. 401 before the 404 on a bogus path id; ERR_STATISTICS_UNVERIFIED before ERR_REQUIRED_PROGRAM_MISSING; ERR_CASCADE_DEPTH_EXCEEDED before ERR_COVERAGE_LIMIT_INSUFFICIENT; ERR_INVALID_FIELD_VALUE before ERR_STATISTICS_INCONSISTENT).
- **Structural**: single top-level key per design file; `SCAFFOLD.yaml` carries neither design key; zero duplicate instance names across the two design files (89 names); no stub carries a `test_recipe`; every stub's `difficulty_instance` resolves; every instance has `claim_type` + `grounds`; every recipe has all four `test_recipe` keys.
- **Taxonomy**: all `section:`/`claim_type:` values come from `references/claim-extraction-guide.md` (no invented categories).
- Hard constraint respected: no sibling `tasks/task_*/` directory was listed, read, or grepped — the only inputs were the scenario text, the skill spec, and this task's own files.

## Step 3: Copy shared files — 2026-09-04T07:27:52.151Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T07:45:00.000Z

PRD generation for task 2684 is complete.

**Output:** `workspace/PRD.md` — **477 lines, 106,664 bytes**, built in 15 incremental `cat >> … <<'PRDEOF'` heredoc appends (no single Write; no truncation).

**Tail confirmation:** `tail -30` ends on the last row of the §5 table, `| `ERR_GRADE_BELOW_SITE_MINIMUM` | 422 |`, a completed final section. No audit footer, no mid-sentence cut.

**Section list**
- §1. Introduction
- §2. Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control; 2.2 API Response Structure; 2.3 Pagination; 2.4 Record Identity, Timestamps and Versioning; 2.5 The Logical Clock; 2.6 Path Resolution and Reference Checking; 2.7 Numeric Precision and Rounding Conventions; 2.8 Optimistic Concurrency on Parent Records; 2.9 Validation Precedence; 2.10 Cascade Discipline and Conserved Counters; 2.11 Segregation of Verification Duties; 2.12 Materialized Posture Versus Fresh Recomputation
- §3. Business Logic & Workflows — 3.1 Standing Up the Network; 3.2 Opening a Cycle and Retiring the Previous One; 3.3 Self-Reported Statistics and Independent Verification; 3.4 Written Programs, the Document Dimension, and Reaching Formal Review; 3.5 Insurance: Two Independent Dimensions and Two Adequacy Tests; 3.6 Grading: Resolving the Yardstick, Assigning the Letter, Choosing the Outcome; 3.7 Curing a Conditional Standing; 3.8 The Gate: Badging a Worker onto a Site; 3.9 Incidents: Filing, Freezing, and the Reversible Half of the Cascade; 3.10 Subcontractor Cascades; 3.11 The Two Periodic Runs
- §4. Endpoint Definitions — 4-column table (Method | Path | Description | Authorized Role(s)), **52 rows** = all 52 scaffold endpoints, with the leading status-code paragraph (201 creates / 200 everything else)
- §5. Error Code Catalogue — 2-column table, **36 rows** = all 36 error IDs

**Hard Contract reports (all PASS)**
1. **Field-Name Coverage — PASS.** All 111 entity field identifiers appear verbatim in backticks (scripted diff: 0 missing). All 42 endpoint `input`/`output` tokens (query params, path params, request-body and bespoke response fields incl. `expected_contractor_version`, `expected_prequalification_version`, `expired_count`, `expired_prequalification_ids`, `conditional_rejected_count`, `conditional_rejected_prequalification_ids`, `overdue_plan_count`, `lapsed_certificate_count`, `selected_count`, `selected_prequalification_ids`) appear verbatim: 0 missing. The only un-backticked snake_case tokens in the scaffold are calculation ids, YAML metadata keys (`applies_to`, `side_effects`, `rule_id`) and local formula variables (`p_trir`, `sub_dart`, `eligible_count`, …) — not payload identifiers, and each is rendered as prose.
2. **Rule Coverage — PASS.** All 30 validations are enumerated in §2.9 in scaffold priority order with matching error IDs, HTTP statuses and `applies_to` scopes (scripted priority->error_id match: 28/30 exact; priorities 5 and 6 deliberately point to "the dedicated 404 code" because they fan out to 8 codes, all 8 of which are enumerated with their scopes in §2.6). All 10 state machines, 17 calculations, both OCC rules, both conserved counters, both `applies_to`-scoped side-effect families, field-level defaults and sibling-branch symmetry (approve/deny, verify/refuse, accept/reject, both suspend-and-restore halves) are covered. All 36 error IDs occur in §2/§3 prose in addition to §5.
3. **§3 Path Purity — PASS.** Scripted scan of every backtick token in §3: zero tokens beginning with `/`, zero bare HTTP methods, zero method+path combinations. HTTP paths appear only in §2.8, §2.9 and the §4 table.

Eight internal scaffold contradictions were adjudicated during drafting (rate precision 4 dp; pagination `limit` default 10; `statistics_verification_status` derivation; duplicate `program_type` -> `ERR_INVALID_FIELD_VALUE`; `document_review_status` staying `NOT_STARTED` while `DRAFT`; second live improvement plan supersedes to `REJECTED`; plan submission barred at/after `due_date`; `qualification_snapshot` sorted ascending by code) — in each case the §1.1/§1.2/calculations source was preferred over the looser endpoint note, and the choice is stated unambiguously in the prose.

**Orchestrator verification:** independently confirmed 477 lines / 106,664 bytes, §4 endpoint table spans lines 377–435, §5 error table spans 436–477 and terminates on a complete table row. Not truncated.

## Step 6: Generate implementation — 2026-09-04T08:20:00.000Z

Implementation complete at `workspace/implementation/`.

## Files (all `py_compile`-clean, no truncation)

| file | lines | role |
|---|---|---|
| `start.sh` | 10 | guarded `pip install` (only when flask missing) + `exec python3 app.py` |
| `requirements.txt` | 1 | flask |
| `app.py` | 81 | blueprint registration, `ApiError`/HTTPException handlers, `0.0.0.0:$PORT` (default 10000), `strict_slashes=False` |
| `store.py` | 89 | 14 empty in-memory dicts, logical clock at `2026-08-01T00:00:00Z`, `base_row`/`touch`/`insert` |
| `errors.py` | 52 | 36-entry `ERROR_HTTP` catalogue + `ApiError`/`fail` |
| `response.py` | 82 | `meta`/`response_type`/`data` envelope, `req_<20 alnum>`, pagination meta (limit 10/1/100) |
| `auth.py` | 79 | `X-User-ID`/`X-User-Role`, 4 roles, ownership + read narrowing |
| `validators.py` | 255 | body parsing with `parse_float=Decimal`, field-value checks, pagination, path resolvers |
| `calc.py` | 363 | enums, floors/multipliers, sub-score + pinned round-per-product composite, grade bands, tiers, tightening |
| `derive.py` | 385 | derived review dimensions, counters, threshold resolution, DAG depth, flow-down, coverage gate |
| `cascade.py` | 139 | grant revoke/expire, fork-join, supersede, freeze/unfreeze, uncured rejection |
| `serialize.py` | 256 | 14 serializers with fresh recomputation of the materialized fields |
| `routes_admin.py` | 348 | clients, sites, contractors, workers, qualifications, `_clock/set_current_utc` |
| `routes_prequal.py` | 288 | prequal create, statistics + verify, submit, grade |
| `routes_docs.py` | 118 | written programs create/review/resubmit |
| `routes_insurance.py` | 153 | certificate filing + verification |
| `routes_access.py` | 221 | site-access grants, revoke, incident reports, close-review |
| `routes_cure.py` | 231 | improvement plans, decisions, variances, audit findings |
| `routes_sub.py` | 146 | subcontractor links + terminate (cycle/depth/flow-down) |
| `routes_runs.py` | 141 | requalification + audit-sampling runs |
| `routes_read.py` | 375 | all 21 GETs incl. the `/scorecard` projection |

Total 3813 lines. Storage is in-memory only; nothing is seeded — a fresh boot returns `total_count: 0` on `GET /prequalifications` (verified).

## Endpoint coverage
Programmatic diff of the PRD §4 endpoint table against Flask's url_map: **52 PRD rows vs 52 registered routes, zero missing, zero extra** (30 POST, 21 GET, 1 PATCH).

## Smoke test (PORT=18684, killed by PID only)
Full happy path exercised end to end: client -> site -> contractor -> prequalification -> safety statistics -> analyst verify -> 3 written programs + client review -> submit -> certificates + verify -> grade -> scorecard -> worker/qualifications -> site-access grant -> periodic runs.

Key confirmations:
- Fork-join fired: submit landed `UNDER_REVIEW` with `statistics_verification_status: VERIFIED`, `document_review_status: COMPLETE`.
- Scores match the PRD worked examples exactly: `provisional 80.51`, `final 77.06`, grade `B`, `effective_thresholds {2.55, 1.275, 0.85, 5.1, tightening 0.85, hazard_tier 2}`, `expires_at 2027-08-01`.
- Per-occurrence adequacy scaled by `base_hazard_tier`: a 1,000,000 GL cert on a tier-2 contractor correctly returned `ERR_COVERAGE_LIMIT_INSUFFICIENT` (422); 1,500,000 verified.
- RBAC correct against the PRD table: program review as `VerificationAnalyst` -> 403, grant creation as `ClientSafetyManager` -> 403.
- Gate logic: grant refused with `ERR_WORKER_QUALIFICATION_EXPIRED` until OSHA10 was added, then 201 with `qualification_snapshot ["HOT_WORK_PERMIT","OSHA10"]`; site `granted_worker_count` went 0->1 with `version` 1->2 (conserved counter + own version bump).
- Audit sampling drew `ceil(25% x 1) = 1`; requalification run returned all six counters as zeros at an unmoved clock.

Cleanup: the smoke process was killed by its specific PID (no pattern-kill), port 18684 confirmed free, `__pycache__` removed.

## Step 5b: unit test generation (queue A + queue B complete)

82 tests across 18 files, all in `test_suite/` at the task root with helpers in `test_helpers/`.

- Queue A (difficulty): 34 tests over 17 of 18 non-stub instances, >= 2 tests each.
- Queue B (corner): 48 tests, exactly one per non-stub instance, over 48 of 50 non-stub instances; the 21 `excluded_because` stubs were never translated.
- Every test docstring carries exactly one verbatim PRD quote (all 82 verified greppable against `workspace/PRD.md` after whitespace normalisation) and ends with a single `Design:` tag; every tag resolves to a real, non-stub design instance.
- `python3 -m pytest test_suite --collect-only -q` collects 82 tests; `py_compile` clean; pyflakes clean apart from conftest's re-exported fixtures.

Skipped instances (PRD-first filter, gaps left as gaps):
1. `Difficulty/transitive_cascade/terminate_prime_subcontractor_edge_cascades_through_three_generation_chain`.
2. `Corner/validations/zero_hours_with_recordable_incidents_returns_statistics_inconsistent` - claims `dart_cases > recordable_incidents` is caught by priority 4 as `ERR_INVALID_FIELD_VALUE`, but PRD 3.3 enumerates that exact condition inside the `ERR_STATISTICS_INCONSISTENT` triple.
3. `Corner/cross-cutting complexity layers/recordable_incident_sets_site_posture_restricted_without_suspending_the_prequalification` - asserts a second badge is admitted (201) while one open RECORDABLE incident stands, but PRD 3.5 spells out that 2,000,000 less 250,000 leaves 1,750,000 against the 2,000,000 GL floor, so priority 29 refuses the grant with `ERR_COVERAGE_LIMIT_INSUFFICIENT` before the min-grade lift at 30 can ever be observed.

Design-yaml defects corrected to the PRD while emitting (never weakened):
- non-existent `scope_of_work` enum `PLUMBING` -> `SCAFFOLDING`; GL certificates at 500,000 per occurrence -> 1,000,000 (they could never reach VERIFIED); undeclared scorecard keys `sub_trir`/`sub_dart`/`sub_emr`/`sub_citation` dropped; `statistics_verification_status` after rejecting the only statistic asserted as `REJECTED`, not `NOT_SUBMITTED`; the 77.89 CONDITIONAL row graded `B`, not `C` (BALANCED B floor is 70.00); the audit tie-break fixture advances the clock one day so `created_at` genuinely orders the two rows.

## Step 5: Generate unit tests (orchestrator record, subagent summary verbatim) — 2026-09-04T08:41:00.000Z

Test generation for `task_2684_contractor_safety_prequalification` is complete and verified.

## Output (task root, not under `workspace/`)

`test_helpers/` — 2,111 lines
| file | lines |
|---|---|
| `__init__.py` | 12 |
| `api_client.py` | 326 |
| `api_errors.py` | 84 |
| `assertions.py` | 333 |
| `constants.py` | 238 |
| `factories.py` | 323 |
| `fixtures.py` | 501 |
| `test_users.py` | 64 |
| `types.py` | 230 |

`test_suite/` — 5,093 lines
| file | lines |
|---|---|
| `conftest.py` | 25 |
| `test_boundary_precision_check.py` | 147 |
| `test_combinatorial_formula.py` | 243 |
| `test_compensating_invariant.py` | 272 |
| `test_corner_calculations.py` | 211 |
| `test_corner_complexity_layers.py` | 179 |
| `test_corner_consistency.py` | 115 |
| `test_corner_endpoints.py` | 449 |
| `test_corner_entities.py` | 492 |
| `test_corner_errors.py` | 620 |
| `test_corner_rbac.py` | 198 |
| `test_corner_state_machines.py` | 490 |
| `test_corner_validations.py` | 264 |
| `test_cross_entity_state_dependency.py` | 247 |
| `test_dual_variant_calc.py` | 245 |
| `test_non_linear_state_machine.py` | 240 |
| `test_priority_pair_validation_conflict.py` | 235 |
| `test_resource_temporal_overlap.py` | 257 |
| `test_transitive_cascade.py` | 164 |

Total 7,204 lines across 28 files.

## Tests per queue
- **Queue A (difficulty)**: 34 tests over 17 of 18 non-stub instances (2 per instance).
- **Queue B (corner)**: 48 tests, exactly one per non-stub instance, over 48 of 50 non-stub instances. The 21 `excluded_because:` stubs were never translated.
- **82 tests total**, confirmed by `pytest test_suite --collect-only -q` -> "82 tests collected".

## Verification gates run
- Design-index cross-check: every `Design:` tag resolves to a real non-stub instance; zero unknown tags, zero stub tags, zero dual tags; only the 3 intended skips absent.
- AST check: all 82 docstrings end with exactly one `Design:` line and carry exactly one `PRD Section` citation.
- All 82 PRD quotes verified greppable verbatim against `workspace/PRD.md` (whitespace-normalized) — two non-verbatim quotes were found and fixed in `test_corner_state_machines.py` and `test_transitive_cascade.py`.
- `python3 -m py_compile` clean on all 28 files; pyflakes clean apart from `conftest.py`'s intentional fixture re-exports; no `skip`/`xfail` markers anywhere; `__pycache__` removed; `find workspace` stray check empty.

## Skipped instances (3) — gaps left as gaps
1. `Difficulty/transitive_cascade/terminate_prime_subcontractor_edge_cascades_through_three_generation_chain` — the PRD does not uniquely derive the asserted grandchild-edge outcome; termination semantics for generation-3 edges are not stated, so the assertion could not be sourced.
2. `Corner/validations/zero_hours_with_recordable_incidents_returns_statistics_inconsistent` — the design claims priority 4 answers with `ERR_INVALID_FIELD_VALUE`, but PRD §3.3 enumerates `dart_cases > recordable_incidents` inside the `ERR_STATISTICS_INCONSISTENT` triple, contradicting the asserted code.
3. `Corner/cross-cutting complexity layers/recordable_incident_sets_site_posture_restricted_without_suspending_the_prequalification` — the trigger asserts a second grant returns 201 while one open RECORDABLE incident stands, but PRD §3.5 spells out that 2,000,000 less 250,000 leaves 1,750,000 against the 2,000,000 aggregate floor, so priority 29 fires `ERR_COVERAGE_LIMIT_INSUFFICIENT` before the priority-30 min-grade lift could ever be observed.

## Design-yaml defects corrected to the PRD (never weakened)
Non-existent `scope_of_work` enum `PLUMBING` -> `SCAFFOLDING`; GL certificates specified at 500,000 per occurrence -> 1,000,000 (below the floor they can never reach VERIFIED); undeclared scorecard keys `sub_trir`/`sub_dart`/`sub_emr`/`sub_citation` dropped; `statistics_verification_status` after rejecting the sole statistic asserted as `REJECTED`, not `NOT_SUBMITTED` (§3.3); the 77.89 CONDITIONAL row graded `B`, not `C` (BALANCED B floor is 70.00); the audit tie-break fixture advances the clock one day so `created_at` genuinely orders the two rows.

**Orchestrator verification:** `test_helpers/` and `test_suite/` both confirmed at the task root; `find workspace -type d -name 'test_*'` returned empty (no stray copies under `workspace/`); independent `pytest test_suite --collect-only -q` reports 82 tests collected.

## Step 7: Run tests and iterate — 2026-09-04T08:55:00.000Z

All 8 rounds pass. Loop complete.

## Summary

**Iterations run: 2**

**Iteration 1** — 8/8 rounds reported 81/82, with the same single deterministic failure in every round (no flakiness, no load-induced connection errors):

- `test_corner_errors.py::test_lost_time_incident_blocks_submit_until_the_review_is_closed` — `AssertionError: expected status SUBMITTED, got UNDER_REVIEW`

**Diagnosis (STEP 1 -> STEP 2):** PRD verbatim-covers the rule and uniquely determines it, so the test stayed. But the final assertion mis-translated PRD wording. The test's own setup, via `build.graded_standing(submit=False, grade=False)` -> `verified_statistic(...)` + `accept_required_programs(...)`, satisfies *both* review dimensions while the row is still `DRAFT` (`statistics_verification_status == VERIFIED`, `document_review_status == COMPLETE` — the test asserts the first of these itself at line 372). PRD Section 3.4 states: *"Whichever of the two dimensions completes last performs the join inside its own request — a statistic verification, a document review, **or the submission itself if both dimensions were already satisfied before the row left `DRAFT`**."* So `UNDER_REVIEW` is the PRD-faithful outcome and the implementation was right. A sibling test, `test_cross_entity_state_dependency.py:56`, builds the identical shape and already asserts `status="UNDER_REVIEW"` — the failing test was the lone outlier.

**Tests deleted:** none. No test failed the coverage or unique-derivability checks.

**Fixes applied to `test_suite/`:**
- `test_suite/test_corner_errors.py`, `test_lost_time_incident_blocks_submit_until_the_review_is_closed` — changed the post-submit assertion from `status="SUBMITTED"` to `status="UNDER_REVIEW"` (plus an inline PRD 3.4 citation), because the test's own fixture satisfies both dimensions pre-submit and PRD makes the submission itself perform the fork-join in that case. The test's real subject — `ERR_INCIDENT_REVIEW_ACTIVE` at precedence 13 blocking submit, then succeeding after review closure — is unchanged and still asserted, as is the `provisional_composite_score == 80.51` check.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none — the implementation was already PRD-faithful on the one failing rule. No PRD-required check was weakened, no endpoint/field/side-effect was added, and storage remains in-memory only (no sqlite, no disk persistence; the sole `json.dumps` is response serialization).

**Final sweep confirmation:** all 8 `results.$i.json` files exist on disk in `workspace/implementation/` (timestamped 08:53, complete JSON), and each reports `passed == total`:

| Round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| passed/total | 82/82 | 82/82 | 82/82 | 82/82 | 82/82 | 82/82 | 82/82 | 82/82 |

Zero failures across all 8 parallel rounds. Also verified no stray `test_suite/` or `test_helpers/` directories landed under `workspace/`.

**Orchestrator verification (independent, per known failure mode where a Step 7 agent claims a clean sweep with no artifacts on disk):** `ls` confirms all 8 `results.{1..8}.json` present (~24.2 KB each, 08:53); parsing each with `json.load` yields `passed=82 total=82 failed=0` for every round. The sweep is real.

**Step 8 skip decision:** NOT skipped. The skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes; Step 7 applied 1 `test_suite/` fix, which marks a site where PRD wording admitted a reading the test generator took and the implementation did not. Step 8 runs with that item as its focus list.

## Step 8: Finalize PRD — 2026-09-04T09:03:00.000Z

Analysis complete. `PRD_FINALIZED.md` is created and is a byte-identical copy of `PRD.md` — **no PRD edits were warranted**, because the single Step 7 item was a pure test-fixture/assertion bug against prose the PRD already pins verbatim.

## Line counts
- `PRD.md`: 477 lines / 106,664 bytes
- `workspace/PRD_FINALIZED.md`: 477 lines / 106,664 bytes
- Delta: 0 lines / 0 bytes (0.00%)
- `tail -3` confirms the file still ends at the §5 error-table's final row (`| ERR_GRADE_BELOW_SITE_MINIMUM | 422 |`).

## Changes
None. (No bullets — no section was inserted or revised.)

## Per-edit pre-edit search log

Only one Step 7 item existed; the mandatory search was run for it and the conclusion was no edit.

**Item: `test_corner_errors.py::test_lost_time_incident_blocks_submit_until_the_review_is_closed` — assertion changed from `status="SUBMITTED"` to `status="UNDER_REVIEW"`.**

(a) **Subject identified:** the `SUBMITTED -> UNDER_REVIEW` fork-join, and specifically whether `POST /prequalifications/{id}/submit` may perform that join inside its own request (plus what the submit response body reflects).

(b) **Impl paths enumerated (read/grepped):**
- `implementation/cascade.py:41-53` — `evaluate_join`: guards on `status == "SUBMITTED"`, then `statistics_verification_status == VERIFIED` and `document_review_status == COMPLETE`, then writes `UNDER_REVIEW`, touches, `recompute_flow_down`. Writes no score of any kind.
- All four `evaluate_join` callsites: `routes_prequal.py:186` (statistic verify), `routes_prequal.py:220` (submit, after `provisional_composite_score` write and before `serialize.prequalification`), `routes_docs.py:88` (document review), `routes_docs.py:117` (document re-tender).
- `routes_prequal.py:190-221` — submit: DRAFT-only guard, then the four guards in precedence order (`ERR_CONTRACTOR_NOT_ACTIVE`, `ERR_INCIDENT_REVIEW_ACTIVE`, `ERR_STATISTICS_UNVERIFIED`, `ERR_REQUIRED_PROGRAM_MISSING`), provisional score, then join — matching PRD §3.4 clause-for-clause.
- `derive.py:89-110` — `document_review_status` four-clause order (`DEFICIENT` -> `COMPLETE` -> `NOT_STARTED` while DRAFT -> `IN_PROGRESS`), exactly PRD §3.4; so a DRAFT row with all required programs ACCEPTED reads `COMPLETE`, not `NOT_STARTED`.
- `derive.py:79-86` — `statistics_verification_status` (governing over PENDING/VERIFIED).
- Other writers of `UNDER_REVIEW` off the Step 7 site, checked for wording risk: `routes_cure.py:116` (accepted improvement plan returns a CONDITIONAL row to review, wiping grade/score/thresholds) and `cascade.py:123-139` (`unfreeze_contractor`). Neither goes through `evaluate_join`, so both are outside the §3.4 sentence's scope and unaffected.
- `routes_prequal.py:231` and `routes_cure.py:150` — the `UNDER_REVIEW` readers (grade gate, variance gate), confirming nothing else depends on submit leaving the row at `SUBMITTED`.
- PRD §4 endpoint table line 417 — description only ("Submit a draft prequalification for review and write its provisional score"), no contradicting status claim.

(c) **Wording adjustment:** none. PRD §3.4 line 247 already states the rule uniquely — *"Whichever of the two dimensions completes last performs the join inside its own request — a statistic verification, a document review, or the submission itself if both dimensions were already satisfied before the row left `DRAFT`. Each of those three requests re-evaluates the join before responding."* — and line 245's parenthetical already anticipates the `COMPLETE`-before-submit case. The implementation is PRD-faithful; the failure was the test mis-translating that prose. Editing here would have risked a new mismatch (e.g. narrowing the join to only three named requests when the impl also calls `evaluate_join` on document re-tender, or implying the submit response reports `SUBMITTED`), so the prose was left verbatim.

Incidental note for the record: `evaluate_join` at `routes_docs.py:117` (re-tender) is a structural no-op — a re-tender moves a row from `DEFICIENT` to `SUBMITTED`, which can never newly satisfy clause 2 — so it exhibits no behavior beyond PRD's three named join-performing requests, and no PRD widening is needed to cover it.

**Orchestrator note on Step 9 plan:** because Step 8 legitimately produced a zero-diff, Step 9 carries the entire alignment burden. To keep the scan from degenerating into a shallow single sweep over a 3,813-line / 21-file implementation, Step 9 is run as THREE sequential, file-partitioned passes over the same `PRD_COMPLETED.md`: pass 1 = global/plumbing (`app.py`, `store.py`, `errors.py`, `response.py`, `auth.py`, `validators.py`, `serialize.py`); pass 2 = computation + core prequal flow (`calc.py`, `derive.py`, `cascade.py`, `routes_prequal.py`, `routes_docs.py`, `routes_insurance.py`); pass 3 = remaining routes (`routes_admin.py`, `routes_access.py`, `routes_cure.py`, `routes_sub.py`, `routes_runs.py`, `routes_read.py`). Sequential, not concurrent, since all three edit one file.

## Step 9 (pass 1 of 3): global/plumbing layer scan — 2026-09-04T09:15:00.000Z

Pass 1 complete.

## File state
- `PRD_FINALIZED.md`: 477 lines / 106,664 bytes
- `PRD_COMPLETED.md`: 477 lines / **112,581 bytes** (+5,917 chars)
- Line count unchanged (all edits are in-paragraph), heading set and markdown table row count byte-identical to the source.
- Tail confirmed intact: last three lines are `ERR_ACCESS_WINDOW_OVERLAP | 409`, `ERR_COVERAGE_LIMIT_INSUFFICIENT | 422`, `ERR_GRADE_BELOW_SITE_MINIMUM | 422`.

## Counts
15 edited locations (16 changed lines): **12 ambiguity-pins, 3 mismatch-revisions**.

## Changes
- §2.1 — revise — mismatch — header emptiness now covers whitespace-only values (impl `.strip() == ""` -> 401) — `auth.py:31-34`
- §2.1 — insert — ambiguity — narrowing only bites where the row carries a reference of the narrowing role's own kind (CSM may read any contractor/worker/qualification/certificate; ContractorAdmin any client/site); multi-contractor resources are owned by any of parent/child/prime — `auth.py:42-79`, `routes_read.py:334-339`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — `response.py:20-21`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` -> `ERR_INVALID_FIELD_VALUE`; empty-valued param (incl. enum/id filters) = omitted; `offset` unbounded, past-end is an empty 200 page — `validators.py:152-196`, `response.py:79-82`
- §2.3 — insert — ambiguity — every collection other than the two `id`-tie-break ones breaks residual ties by creation sequence (ascending under ascending sorts, descending under descending) — `store.py:80-89`, `routes_read.py:156,318,365`
- §2.4 — revise — mismatch — `Worker`/`WorkerQualification` expose their domain fields plus `id`/`created_at`; `updated_at`/`version` keys are absent, not null (the old "expose only `id` and `created_at`" literally contradicted impl) — `serialize.py:174-195`
- §2.4 — insert — ambiguity — a recomputation that changes nothing does not advance `version`/`updated_at`; named the four conditionally-touched posture fields; corrected the six-badge illustration (a site advances once per revocation) — `store.py:67-72`, `derive.py:140-148,199-219,350-355`
- §2.5 — revise — mismatch — instants accept `Z`, an explicit offset, or no zone (read as UTC); comparisons are exact, not second-granular; output truncates below the millisecond — `validators.py:134-146`, `store.py:50-56`
- §2.7 — insert — ambiguity — all four regimes are emitted as bare JSON numbers with no trailing-zero padding; integer regimes have no decimal point; a number-declared field stays a number when whole (`20.0`) — `response.py:31-40`
- §2.9 item 3 — insert — ambiguity — JSON `null` counts as absent; absent/empty/`null` body = empty object; non-object or invalid JSON -> 400 regardless of `Content-Type`; integer fields reject `2.0`; no numeric field accepts a boolean — `validators.py:16-68`
- §2.9 item 4 — insert — ambiguity — caller-supplied arrays are stored and echoed in supplied order, never sorted or deduplicated; server-assembled arrays follow their own stated order — `validators.py:121-131`
- §2.12 — insert — ambiguity — added `statistics_verification_status` and `document_review_status` to the read-projection list (the paragraph purported to enumerate them) — `serialize.py:76-77`, `derive.py:79-110`
- §3.5 — insert — ambiguity — `verified_coverage_types` is emitted in canonical `GL, WC, AUTO, UMBRELLA` order, each type once — `derive.py:191`, `calc.py:19`
- §3.6 step 3 — insert — ambiguity — the snapshot's `max_citation_points` is a four-decimal number, not the integer the client published — `calc.py:225`, `routes_prequal.py:254-261`
- §4 — insert — ambiguity — trailing slash tolerated; unrouted path -> `ERR_RECORD_NOT_FOUND` 404; wrong method -> `ERR_INVALID_REQUEST` on **405**, both decided before any header check — `app.py:26,46-59`
- §5 — insert — ambiguity — noted the single departure from the status table (the 405 method-not-allowed refusal) — `app.py:52-55`

All behavioral claims were verified empirically against a live instance (port 17284, started and killed by pid) — unknown path, wrong method with/without headers, trailing slash, `limit=`/`limit=abc`/`limit=0`/`offset=-1`, whitespace header, explicit `null` field, array body, `null` body, missing `Content-Type`, float-for-integer, boolean-for-number. The 36-code catalogue and its statuses were diffed programmatically against `errors.ERROR_HTTP`: **exact match, no edit needed**.

## Deliberately left for passes 2/3
- `routes_read.py:182` — the `status` filter on `GET /prequalifications/{id}/improvement-plans` matches the *projected* status (`OVERDUE` included), not the stored one. PRD §3.7 just says "filtered by `status`".
- `routes_read.py:205` — the scorecard admits only `VERIFIED` governing statistics (`("VERIFIED",)`), while submission's provisional variant admits `PENDING` too; §3.6's "Both read null until a statistic has been verified" is consistent but the asymmetry lives in the route.
- `routes_prequal.py:111` — `hours_worked` is declared an **integer** field, so a fractional value is a 400; §3.3 only says "at least 0".
- `derive.py:75` / `governing_statistic` — the governing row is chosen by `(reporting_year, created_at, _seq)` max, i.e. an insertion-order tie-break among same-year rows; §3.3 pins only "greatest `reporting_year`".
- `calc.py:303` — `lifecycle_status` preserves `SUPERSEDED` only when the *stored* field already reads `SUPERSEDED` **and** `verification_status` is `REJECTED`; §3.5's five-clause wording is looser than that conjunction.
- `calc.py:83` — `TIER_COVERAGE_MULTIPLIER` maps tier **3** to 1.5 as well; §3.5 mentions only tiers 1 and 2, and coverage tests use `base_hazard_tier` (never the escalated grading tier), so tier 3 is currently unreachable there.
- `auth.visible_any_contractor`'s empty-`ids` fallback (returns visible) is unreachable at its only callsite, so nothing was pinned about it.

## Step 9 (pass 2 of 3): computation + core prequal flow scan — 2026-09-04T09:28:00.000Z

Pass 2 complete.

## Byte count

- Before: **112,581** bytes (477 lines) -> After: **118,197** bytes (477 lines) -> **+5,616 chars**
- Tail confirmed intact: file still ends `| ERR_COVERAGE_LIMIT_INSUFFICIENT | 422 |` / `| ERR_GRADE_BELOW_SITE_MINIMUM | 422 |`

## Counts

16 Edit calls covering 17 subjects: **13 ambiguity-pins, 4 mismatch-revisions**.

## Changes

- §2.4 — insert — ambiguity — a contractor's own posture fields (`base_hazard_tier`, `incident_review_flag`, `open_severe_incident_count`, `open_deficiency_count`, `verified_coverage_types`) are outside §2.4's "bump only when changed" set; recomputing one never advances the contractor's `version`/`updated_at`, so the version moves only on amend / cycle-open / incident-file / close-review — `derive.py:179,183,194` (verified: the only contractor `touch()` sites are `routes_admin.py:254`, `routes_access.py:185,216`, `routes_prequal.py:87`)
- §2.6 — insert — ambiguity — every path-parented creating write also declares its parent's id as an *optional* body field whose value is never resolved and never compared to the path — `routes_prequal.py:93`, `routes_docs.py:23`, `routes_insurance.py:22` (+ pass 3's `routes_admin.py:127,263,298`, `routes_cure.py:22,133`)
- §2.11 — insert — ambiguity — the bar tests the recorded `verified_by_user_id` field only, so an analyst who *refused* a statistic is barred exactly like one who verified it — `routes_insurance.py:123`
- §2.12 — revise — **mismatch** — lifecycle is written on create / verify / requalification run; a **refusal** leaves the stored lifecycle value untouched (PRD said "verified or refused") — `routes_insurance.py:148`
- §2.12 — revise — **mismatch** — the `OVERDUE` projection applies only to plans still `OPEN`/`SUBMITTED`; `ACCEPTED`/`REJECTED`/materialized-`OVERDUE` read their stored status — `derive.py:113`
- §3.2 — insert — ambiguity — a superseded/expired row clears nothing but the status: `grade`, `final_composite_score`, `effective_thresholds`, `deficiency_codes`, `expires_at`, `conditional_expires_at` all survive; §3.11 step 2 fires the same chain — `cascade.py:59`
- §3.3 — revise — ambiguity — `hours_worked` is an **integer** field, so a fractional value is `ERR_INVALID_REQUEST`, not a range error — `routes_prequal.py:94,111`
- §3.3 — revise — **mismatch** — `emr`'s "two decimal places" is convention, not a validated scale: extra places are accepted and echoed at the supplied precision — `routes_prequal.py:115`, `validators.py:108`
- §3.3 — insert — ambiguity — the duplicate-reporting-year rule guarantees at most one admitted row per year, so the governing row is unique and no tie-break can arise — `derive.py:71`
- §3.4 — revise — ambiguity — the one-row-per-`program_type` test is a cross-row check that runs *after* the `DRAFT`-or-`SUBMITTED` status guard (duplicate on a later row => `ERR_TRANSITION_NOT_ALLOWED`); the future-`revision_date` check runs with the field-value rules — `routes_docs.py:38,44`
- §3.4 — insert — ambiguity — neither review nor re-tender consults the prequalification's own status — `routes_docs.py:76,107`
- §3.4 — insert — ambiguity — body-less ops (submit, grade, terminate, both runs) accept absent/empty/`null`/`{}` and refuse any body with one field — `validators.py:71`, `routes_prequal.py:193,227`
- §3.4 — insert — ambiguity — the **final** variant admits only `VERIFIED` rows — `routes_prequal.py:241`
- §3.4 — revise — ambiguity — `reviewer_note` carries no length bound and is written as null when omitted — `routes_docs.py:67,84`
- §3.5 — insert — ambiguity — the `SUPERSEDED` clause is read as a stored fact: recomputation returns it exactly when the stored field holds it **and** the row is still `REJECTED` — `calc.py:303`
- §3.5 — revise — **mismatch** — `REJECT` recomputes `verified_coverage_types` but cannot change it (a pending cert never contributed), and re-materializes neither `lifecycle_status` nor `available_aggregate` — `routes_insurance.py:148`
- §3.9 — insert — ambiguity — suspension preserves `grade`/`final_composite_score`/`effective_thresholds`/`deficiency_codes`/`expires_at`; the freeze's `triggered_suspension_count` increments leave the new report at `version` 1 — `cascade.py:68,120`
- §3.11 — insert — ambiguity — uncured refusal preserves `grade`, `final_composite_score`, `effective_thresholds` and the elapsed `conditional_expires_at`; only `expires_at` is nulled (unlike a graded refusal) — `cascade.py:77`

## Hand-off items

1. **`routes_prequal.py:111` `hours_worked` integer** — **pinned** in §3.3.
2. **`derive.py:75` governing-statistic tie-break** — **no tie-break pinned; the ambiguity was removed the other way.** The duplicate-reporting-year rule (priority 21) forbids a second row for a year while an existing one is `PENDING` or `VERIFIED`, and both decisions are terminal, so *both* admitted sets (`PENDING u VERIFIED` and `VERIFIED`) can hold at most one row per year. The `(created_at, _seq)` tail of the sort key is unreachable. §3.3 now states that the governing row is unique and no tie-break can be required — deliberately avoiding a claim the impl never gets to exercise.
3. **`calc.py:303` `SUPERSEDED` conjunction** — **pinned** in §3.5 (stored-fact reading, not re-derivation), with the reachability argument that makes it equivalent to the old five-clause wording.
4. **`calc.py:83` `TIER_COVERAGE_MULTIPLIER[3]`** — **no edit needed.** `scaled_floor` is reached only through `per_occurrence_adequate` (`routes_insurance.py:136`) and `aggregate_adequate` (`derive.py:379`), and both are called exclusively with `contractor["base_hazard_tier"]`, which `routes_admin.py:191,247` computes as 1 or 2 only. Tier 3 is dead code in the multiplier table, so §3.5's existing "1.0 at tier 1, 1.5 at tier 2, scaled by `base_hazard_tier`" is already exhaustive over every reachable path. Pinning a tier-3 multiplier would document unreachable behavior.

## For pass 3

- `routes_admin.py:60` accepts `max_citation_points = 0` (`lo=0`, non-strict). A client so configured makes the tightened `CITATION_POINTS` ceiling 0, and `calc.sub_score` then divides by zero -> HTTP 500. §3.4 currently asserts "every client threshold is strictly positive", which §3.1's "may not be negative" contradicts. Pass 3 owns `routes_admin.py` and should decide how to pin §3.1/§3.4 here.
- The client dials (`max_trir`, `max_dart_rate`, `max_emr`, the four weights, `conditional_band_pct`, `audit_sample_rate_pct`) have **no** decimal-scale validation, same as the `emr` case pinned in §3.3 — §3.1's "carried to two decimal places" is convention only.
- The §2.6 pin now covers the optional-ignored parent-id body field universally (including `routes_admin.py:127,263,298` and `routes_cure.py:22,133`) — do not re-pin per endpoint.
- `routes_runs.py:89-92`: `lapsed_certificate_count` counts certificates whose *freshly computed* lifecycle is `LAPSED` while the **stored** value was not; §3.11 never defines that counter.
- `routes_runs.py:124`: the audit ranking maps a null `final_composite_score` to `Decimal("-1")` (nulls first). Likely unreachable, since the pool is `APPROVED`/`CONDITIONAL`, but worth confirming.
- `routes_cure.py:53`: the `due_date <= conditional_expires_at` guard is skipped when `conditional_expires_at` is null.

## Step 9 (pass 3 of 3): remaining routes scan + cross-pass consistency — 2026-09-04T09:45:00.000Z

Pass 3 of 3 complete.

## File integrity
- `PRD_COMPLETED.md`: **477 lines / 125,316 bytes** (was 477 lines / 118,197 bytes) -> **+7,119 chars in pass 3**; +18,652 total over `PRD_FINALIZED.md` (106,664).
- Line count unchanged and diff shows **zero whole-line insertions or deletions** — every pass-3 change is an in-paragraph insert or revise. No new sections.
- `tail -3` confirms the file still ends at `| ERR_GRADE_BELOW_SITE_MINIMUM | 422 |`.

## Counts
19 ambiguity-pins, 5 mismatch-revisions, 2 cross-pass consistency fixes (24 anchored changes across 21 Edit calls + 2 fix edits).

## Changes
- §2.3 — insert — ambiguity — an identifier filter is an opaque string never resolved against the store (unknown id = empty page, not 404); an integer filter is only constrained to be a base-10 integer, no range check — `routes_read.py:119-128`, `validators.query_str/query_int`
- §3.1 — insert — ambiguity — uniqueness compares exactly (case-sensitive, no trimming) and a parent-scoped uniqueness test is evaluated after the parent resolves and after ownership — `routes_admin.py:94,145,180`
- §3.1 — revise — **mismatch** — `max_citation_points` is an integer that "may not be negative", so **0 is an accepted ceiling** — `routes_admin.py:62-64`
- §3.1 — insert — ambiguity — two-decimal carriage is convention only; no client dial's decimal scale is validated, values echo at the caller's precision — `routes_admin.py:38-76`
- §3.1 — revise — ambiguity — contractor `hazard_profile` must be a non-empty duplicate-free subset — `routes_admin.py:176`
- §3.1 — insert — ambiguity — patch re-validates each array as at registration, a body supplying none of the four is accepted (and still counts as an amendment), and none of the three `status` positions is terminal — `routes_admin.py:206-232`
- §3.1 — revise + insert — ambiguity — both issue/expiry violations share `ERR_INVALID_FIELD_VALUE`; `expiration_date` is never compared to the clock at filing — `routes_admin.py:310-316`
- §3.4 — revise — **mismatch** — deleted the false universal "every client threshold is strictly positive"; only `max_trir`/`max_dart_rate`/`max_emr` are strictly positive, `max_citation_points` is admitted at 0, and no score is specified for a citation ceiling of 0 — `routes_admin.py:62-64`
- §3.5 — insert — ambiguity — certificates are listable filtered by `coverage_type` — `routes_read.py:62-67`
- §3.6 — revise — **mismatch** — the scorecard resolves its governing statistic from `VERIFIED` rows alone for *both* scores (narrower than submission's provisional variant); `effective_thresholds` is echoed from the grading snapshot; `hazard_tier` is recomputed live and always reported — `routes_read.py:205-226,240`
- §3.7 — insert — ambiguity — the two `due_date` comparisons sit at different precedence points: clock comparison pre-resolution, cure-window comparison only after the version and `CONDITIONAL` guards — `routes_cure.py:30,43`
- §3.7 — insert — ambiguity — the supersede sweep reads *stored* status in ascending creation order, so a projected-`OVERDUE`-but-stored-`OPEN` plan is superseded — `routes_cure.py:46-50`
- §3.7 — revise — ambiguity — `evidence_ref` is 1 to 120 characters — `routes_cure.py:74`
- §3.7 — insert — ambiguity — the decision guard reads stored status, so a timely-submitted plan is still decidable after its deadline until a run materializes `OVERDUE` — `routes_cure.py:101`
- §3.7 — revise — **mismatch** — the plan `status` list filter matches the *projected* status, making `OVERDUE` filterable — `routes_read.py:182`
- §3.7 — insert — ambiguity — a `DENY` may carry `expires_at`; it must still parse but need not be future, and is discarded — `routes_cure.py:189-190`
- §3.7 — insert — ambiguity — audit findings bumps the prequalification's `version` and returns the prequalification row — `routes_cure.py:229-231`
- §3.8 — insert — ambiguity — grant ownership is judged against the *prequalification's* contractor, before the worker/site coherence pair — `routes_access.py:39-45`
- §3.9 — revise — ambiguity — `findings_note` is required, 1 to 500 characters — `routes_access.py:197`
- §3.10 — insert — ambiguity — only the prime may open an edge; trade-code membership is pre-resolution while the child-subset comparison follows resolution and ownership — `routes_sub.py:42,48-55`
- §3.10 — insert — ambiguity — the create-time `flow_down_status` write precedes first serialization, so a new edge returns at `version` 1 — `routes_sub.py:102`
- §3.10 — revise — ambiguity — termination accepts the prime or the edge's own parent, never merely its child — `routes_sub.py:114-119`
- §3.10 — revise — **mismatch** — the descendant cascade is empty in every case the middle-tier guard admits, so a successful termination advances exactly one edge — `routes_sub.py:123-138`
- §3.11 — insert — ambiguity — `lapsed_certificate_count` defined: measured before the refresh writes, +1 per certificate of any `verification_status` whose fresh lifecycle is `LAPSED` while the stored value was not; `SUPERSEDED` never enters; each contractor visited once — `routes_runs.py:81-93`

## Hand-off item resolutions
1. `max_citation_points = 0` — **pinned**, two places (§3.4 false universal rewritten, §3.1 made 0-acceptance explicit); no score promised at a 0 ceiling, no validation invented.
2. Decimal scale — **pinned** in §3.1 as convention-only, plus pass 2's parallel note at §3.3 for `emr`.
3. `lapsed_certificate_count` — **pinned** in §3.11.
4. Null score -> `Decimal("-1")` — **no edit, unreachable**: `routes_prequal.py:262` writes `final_composite_score` before `:267` writes the status, and `:267` is the only writer of `APPROVED`/`CONDITIONAL`, so the audit pool can never hold a null score.
5. Null `conditional_expires_at` skip — **no edit on the dead branch** (a `CONDITIONAL` row always carries a non-null value and the status guard precedes the comparison); instead pinned the observable fact in that neighbourhood, the precedence split of the two `due_date` comparisons.
6. Projected-status plan filter — **pinned** in §3.7.
7. Scorecard `VERIFIED`-only — **pinned** in §3.6, explicitly contrasted with submission's provisional variant.

## Cross-pass consistency check
Diffed all 48 changed lines and word-diffed each insertion. **One genuine contradiction found and fixed**: pass 1's §2.1 universal said that for a subcontractor edge "both ownership and visibility are satisfied when `X-User-ID` matches any one of" its three contractor references — true for reads (`routes_read.py:374`) but false for both writes (`routes_sub.py:48` is prime-only; `:114-119` excludes the child). Rescoped that sentence to reads/listings and deferred the write sets to §3.10. Also tightened one imprecise phrase in §3.10 ("the client the prime prequalification was graded by" -> "the client of the prequalification the edge hangs from"), which could have implied a grading precondition.

Verified as non-conflicting: pass 1's §2.3 tie-break rule ("all but those two collections break ties by creation order") holds for every sort in `routes_read.py`; pass 2's §2.6 optional-parent-id universal holds for all three path-parented creating writes in that partition (`routes_admin.py:127,263,298`); pass 2's §2.4 rule that recomputation touches only on change and never bumps a contractor's `version` is confirmed by `derive.py:179-219,350-355` (no `touch(contractor)` anywhere); pass 2's §3.5 stored-fact `SUPERSEDED` reading is what makes the §3.11 `SUPERSEDED`-never-counted claim true.

## Step 9 aggregate (all three passes)
- Source `PRD_FINALIZED.md`: 477 lines / 106,664 bytes -> `PRD_COMPLETED.md`: 477 lines / **125,316 bytes** (**+18,652 chars, +17.5%**).
- 48 lines revised (96 diff lines), zero line insertions/deletions, zero new sections, heading set byte-identical.
- Totals across passes: **44 ambiguity-pins, 12 mismatch-revisions**, plus 2 cross-pass consistency fixes.

## Orchestrator final verification
- `wc`: PRD.md 106,664 = PRD_FINALIZED.md 106,664 (Step 8 zero-diff, justified) < PRD_COMPLETED.md 125,316. PRD_COMPLETED.md is NOT byte-identical to its source, so the scan demonstrably ran (guarding the known failure mode where a Step 9 agent copies the file and reports a scan it never performed).
- `diff` of the two files' heading lines is empty — no section was lost or renamed.
- `tail` confirms termination at `| ERR_GRADE_BELOW_SITE_MINIMUM | 422 |`.
- `find workspace/implementation test_suite test_helpers -name '*.py' -newermt '2026-09-04 08:54'` returns nothing: no Python file was modified after the final green sweep, so the 8/8 x 82/82 result recorded in Step 7 still describes the artifacts on disk.

## PIPELINE COMPLETE — Step 9 has written workspace/PRD_COMPLETED.md.
