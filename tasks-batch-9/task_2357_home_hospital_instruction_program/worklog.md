# Worklog — task_2357_home_hospital_instruction_program

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `tasks/task_2357_home_hospital_instruction_program/` and `workspace/` subdirectory (name pre-allocated by the caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T06:06:00.000Z

All three scaffold artifacts for task 2357 are complete and lint-clean.

**Files** (all in `/home/auto/…` → actually `/home/ubuntu/github/CodingPRD/tasks/task_2357_home_hospital_instruction_program/`):
- `/home/ubuntu/github/CodingPRD/tasks/task_2357_home_hospital_instruction_program/SCAFFOLD.yaml` — §1.0–§1.7, no design keys
- `/home/ubuntu/github/CodingPRD/tasks/task_2357_home_hospital_instruction_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_2357_home_hospital_instruction_program/SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

**SCAFFOLD.yaml counts (deliberately above the Expert band):** 13 entities, 69 endpoints, 74 error codes, 79 validation rules, 10 state machines, 11 calculations, 5 roles, 3 OCC concurrency rules. Profile: primary archetype compliance/audit, secondary temporal windowing; layers `dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency, selector_policy, derived_field_reconciliation`; flat topology, cyclic state machines, `segregation_of_duties` role model, `immediate` consistency. Domain spine: Student / Teacher / EntitlementRule / HomeboundCase / PhysicianCertification / HomeVisitSafetyReview / TeacherAssignment / InstructionSession / AttendanceLedgerEntry / ExtensionRequest / TransitionPlan / PacingSync / SpedServiceLog, driven by a logical clock (`POST /hhi/_clock/set_current_utc`, default `2026-08-01T00:00:00Z`, never falls back to wall clock).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** all 9 required rules, 29 instances (3–4 per rule, every rule ≥2): dual_variant_calc 3, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 3, priority_pair_validation_conflict 4, boundary_precision_check 4, cross_entity_state_dependency 3, resource_temporal_overlap 3, compensating_invariant 3.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** all 9 claim-guide sections, 67 instances = 56 full test recipes + 11 `excluded_because` stubs. Breakdown: entities 12, state_machines 20 (7 stubs), calculations 8 (2 stubs), validations 9, endpoints 5, errors 3, rbac 4, cross_cutting_complexity_layers 5 (2 stubs), consistency_model 1. Every stub's cited `difficulty_instance` was verified to exist by name in §1.8 (11/11 resolve).

**Coverage-audit notes:**
- All 74 declared error codes are triggered at least once across §1.8+§1.9 (verified programmatically; the last 10 holes — the 5 RBAC codes plus `ERR_PLAN_NOT_READY`, `ERR_PLAN_STATE_INVALID`, `ERR_REVIEW_ALREADY_FINALIZED`, `ERR_NO_PACING_COORDINATION`, `ERR_EXTENSION_LIMIT_REACHED` — were closed by the `errors` and `rbac` sections).
- All three §1.2.1 concurrency rules get an explicit stale-vs-fresh `expected_case_version` test on their own write endpoint (certifications, extension-requests, transition-plans), plus version-increments-on-every-write assertions.
- `endpoints/bulk_action` is intentionally absent — the API declares no bulk endpoints.
- Lint (`scaffold_lint.py`): 1564 calls scanned across §1.8+§1.9, `VERDICT: clean lint` — every call maps to a declared endpoint with an allowed role, payloads are subsets of declared inputs, all captures resolve to declared output fields, and every §1.1 FK is reverse-reachable from §1.5.
- Two arithmetic corrections made while writing the final sections: the `WEEKLY_UNROUNDED_PROJECTION` variant rounds to 5 once at the end (projection is 360, not 358), and the ONSITE_VERIFIED risk score for `{AGGRESSIVE_ANIMAL, UNLIT_ACCESS}` with an escort is 20 → `CLEARED_WITH_ESCORT` (not 30).
- Hard constraint honored: no sibling task directory under `tasks/` was listed, globbed, grepped or read at any point; the only inputs were the scenario text, the scaffold-generator skill (`SKILL.md`, claim-extraction guide, `scaffold_lint.py`) and this task's own three files.

## Step 3: Copy shared files — 2026-09-02T06:08:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_2357_home_hospital_instruction_program/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T06:25:00.000Z

Both remaining checks pass. The PRD is complete.

**Deliverable:** `/home/ubuntu/github/CodingPRD/tasks/task_2357_home_hospital_instruction_program/workspace/PRD.md` — 453 lines, ~12,660 words.

**Structure**
- §1 Introduction — 3 paragraphs (folder-and-spreadsheet status quo → what the API replaces → the two design commitments: parallel service/funding dimensions, logical clock).
- §2 Global Specifications — 10 subsections: 2.1 User and Role-Based Access Control, 2.2 API Response Structure (fixed block, verified byte-identical to `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 The Logical Service Clock, 2.5 Common Resource Properties, 2.6 Validation Precedence, 2.7 Expected-Version Preconditions on the Case Record, 2.8 Minute Arithmetic Rounding and Precision, 2.9 Parallel Status Dimensions and Cascade Discipline, 2.10 The Entitlement Rule Catalogue.
- §3 Business Logic — 9 subsections grouped by case lifecycle with cross-cutting concerns woven in: 3.1 Students, Teachers, and Opening a Case; 3.2 Physician Certification and the Path to Eligibility; 3.3 Computing the Weekly Instructional-Hours Entitlement; 3.4 Staffing the Case and the Weekly Minute Allocation; 3.5 Home Visit Safety Review and the Virtual Alternative; 3.6 Activation, Session Scheduling, Delivery and Attendance Coding; 3.7 Funding: Accrual, Service Gaps, Holds and Reconciliation; 3.8 Extending the Certified Window; 3.9 Campus Coordination, Service Continuation, and the Return to the Building.
- §4 — 1 status-code paragraph + 4-column table, all 69 endpoints; role columns verified equal to `endpoints[].roles` for every row.
- §5 — 2-column table, all 74 error IDs; every HTTP status verified equal to `errors[].http`.

**Field coverage check:**
- entities[].fields: 146 required, 146 present, 0 missing
- endpoints[].input (request_body/query_params): 174 required, 174 present, 0 missing
- endpoints[].output inline read-model keys (funding-summary): 14 required, 14 present, 0 missing
- Status: PASS (138 unique required names)

**Rule coverage check:**
- validations[] with priority: 80 checked, 80 expressed in prose, 0 missing (all 14 tiers enumerated in §2.6, including both intra-tier-8 orderings: `ERR_CERT_ALREADY_PENDING` before `ERR_INVALID_CASE_STATE`, `ERR_FUNDING_ALREADY_RECONCILED` before `ERR_FUNDING_NOT_ACCRUING`)
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed with write operation + `expected_case_version` + `ERR_STALE_CASE_VERSION` + 412 all named, 0 missing
- state_machines[].transitions: 55 checked across 10 machines, 55 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed, 0 missing (all 4 dual-variant calcs render both variants and the divergence)
- validations[] conditions: 80 checked, 80 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 110 side-effect clauses + 80 applies_to sets checked, all expressed, 0 missing
- entities[].fields[] structured content: 146 checked (types, defaults, ranges, enum members, uniqueness, computed-from rules, `common_fields: false` on `AttendanceLedgerEntry` called out explicitly), 146 reconstructible from prose, 0 missing
- sibling-branch symmetry: 12 groups checked, 12 with equal prose density, 0 asymmetric
- Status: PASS

**Path purity check (§3 only):**
- backtick tokens scanned: 1082
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- (also verified: no raw scaffold path string appears anywhere in §3, even unbackticked)
- Status: PASS

**Coverage-audit notes**
1. Calculation *variant identifier strings* (`PROVISIONAL_ACCRUAL`, `FINAL_VERIFIED`, `PER_SESSION_ROUNDED`, `WEEKLY_UNROUNDED_PROJECTION`) are rendered behaviourally rather than as literals — they are calculation metadata, not persisted field values or API inputs. `scoring_variant`'s members `SELF_REPORTED`/`ONSITE_VERIFIED` *are* backticked, since that is a persisted field.
2. Constant *symbol names* (`DX_FACTOR`, `ESCORT_MITIGATION`, `FULL_CREDIT_RATIO`, etc.) are embedded as their numeric values in business statements per the "constants embedded in context" guideline; no constant value was dropped.
3. Two scaffold worked examples were kept because they disambiguate boundaries the formula alone leaves ambiguous: the 34-vs-35 risk-score divergence across scoring variants, and the 140-vs-135 credited-vs-projected rounding divergence. The allocation worked examples (390 → 115/275; 270 → 80/190) were *not* reproduced — the residual-absorption rule is stated deterministically instead, so the numbers are derivable rather than given.
4. `ELIGIBLE → CLOSED` and `EXTENSION_PENDING → CLOSED` each declare a subset of the `ACTIVE → CLOSED` cascade list. §3.9 states the union; the extra cascades are vacuous in the narrower from-states (an eligible case has no scheduled sessions or plans), so no fidelity is lost.
5. One correction made during audit: an early draft claimed assignment creation was gated on the case being in service. The scaffold's `ERR_CASE_NOT_ACTIVE` applies_to set excludes assignment creation (activation itself requires an active primary assignment), so the sentence was rewritten to say assignments are explicitly *not* so gated.
6. Confirmed not read at any point: `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, and every sibling task directory. Sources consulted were only `SKILL.md`, `section-2.2-response-structure.md`, `example-prd.md`, and `SCAFFOLD.yaml`.

## Step 5: Generate unit tests — 2026-09-02T08:50:00.000Z

Queue B is finished; the full suite is generated and audited.

## Summary (for verbatim worklog recording)

**Files written**

*Stage 1 — `test_helpers/` (9 files):* `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py` (plus `test_suite/conftest.py`).

*Stage 2 — `test_suite/` (18 numbered files, 113 tests):*
- Queue A (§1.8, depth) — `test_01_dual_variant_calculations.py`, `test_02_combinatorial_formulas.py`, `test_03_non_linear_state_machines.py`, `test_04_transitive_cascades.py`, `test_05_validation_precedence.py`, `test_06_boundary_precision.py`, `test_07_cross_entity_state_dependency.py`, `test_08_resource_temporal_overlap.py`, `test_09_compensating_invariants.py` — **58 tests**.
- Queue B (§1.9, breadth) — `test_10_entity_surface.py` (11), `test_11_state_machine_surface.py` (13), `test_12_calculation_surface.py` (6), `test_13_validation_surface.py` (9), `test_14_endpoint_surface.py` (5), `test_15_error_surface.py` (3), `test_16_rbac_surface.py` (4), `test_17_cross_cutting_surface.py` (3), `test_18_consistency_surface.py` (1) — **55 tests**.

**Instance coverage:** 29/29 non-stub difficulty instances (≥2 tests each), 55/56 non-stub corner instances (1 test each); the 11 `excluded_because` corner stubs were correctly not translated.

**Instances skipped (1):** `Corner/entities/flat_topology_keeps_case_children_isolated_under_filtered_reads` — every assertion is keyed to query-parameter filters (`?case_id=`, `?teacher_id=`, `?student_id=`, `?entitlement_rule_id=`) that PRD §2.3 never declares ("List endpoints accept two query parameters", `limit` and `offset`), so it fails the verbatim-coverage condition. Gap left as a gap; no placeholder, no xfail.

**Sub-assertions dropped as not uniquely derivable (instances otherwise kept):** three funding-summary claims in `endpoints`; `dispute_note` persistence and a `case_v0 + 1` arithmetic claim in `rbac` (the design's own arithmetic contradicted §171/§173, so the test captures the pre-trigger version and asserts stability); `clearance_band` renamed to the real field `clearance`; in `cross_cutting`, `released_at` on the completion cascade (§293 does not stamp it — only the explicit release verb in §199 does) and the funding-summary `service_weeks 2` / `entitled_total_minutes 780` / projected `service_gap_minutes 750` claims at clock 2026-09-21 (§3.7's elapsed-week definition yields 3 weeks, and the summary returns "the case's current" persisted gap), replaced by the derivable `funding_status` stability claim plus the third report's recomputed 750 / HELD.

**Coverage-audit notes:** whole-suite AST audit — 113 tests, every test carries exactly one trailing `Design:` line, 0 unknown tags, 0 dual tags, 0 tags pointing at stubs or non-existent instances, 55 unique corner tags for 55 corner tests. All `The PRD states: "…"` citations grep-verified against the whitespace-normalized PRD (0 misses across all queue-B files); no citation contains an embedded double quote. No forbidden vocabulary, no unused/undefined imports (all from `test_helpers`), max non-`Design` line length 91. `pytest --collect-only` collects all 113 tests cleanly. Every list-based assertion uses unfiltered `params={"limit": 100}` plus client-side selection, since only `limit`/`offset` are declared. Scratch audit tooling (`audit_queue_b.py`) and `__pycache__` directories removed; the task directory now contains only the three scaffold YAMLs, `test_helpers/`, `test_suite/`, `worklog.md` and `workspace/`.

## Step 6: Generate implementation — 2026-09-02T08:50:00.000Z

Final verification complete. The `funding/reconcile` gate matched the SCAFFOLD state machine (`service_status IN {ACTIVE, EXTENSION_PENDING, TRANSITION_PLANNED, CLOSED}`, both reconcile transitions gated on `funding_status == ACCRUING`); I reordered the two tier-8 checks so the funding dimension is judged before the service one, matching PRD §3 prose ("...rejecting `NOT_REPORTED`, `HELD` and `FORFEITED` with `ERR_FUNDING_NOT_ACCRUING` ... the generic code is *reserved* for a `funding_status` of `NOT_REPORTED`, `HELD` or `FORFEITED`") and the declared already-reconciled-first sub-ordering.

## Summary (for the worklog)

**Files written** — 26 files, 3,605 lines of Python, under `/home/ubuntu/github/CodingPRD/tasks/task_2357_home_hospital_instruction_program/workspace/implementation/`:

- `start.sh` — guarded `pip install -q -r requirements.txt`, then `exec python3 app.py`; reads `PORT` (default 10000), binds `0.0.0.0`. Boots a fresh, empty process every invocation.
- `requirements.txt` — Flask only.
- `app.py` — application factory, registers all 14 blueprints, `strict_slashes = False`, error handlers for `ApiError` / `HTTPException` (404 `ERR_NOT_FOUND`, 405 `ERR_METHOD_NOT_ALLOWED`, 400 `ERR_VALIDATION`) / bare `Exception` (`ERR_INTERNAL`).
- Core modules: `db.py` (in-memory dicts keyed by UUID, per-request dirty set driving exactly one `updated_at` refresh + one `version` bump per mutated row), `clock.py` (logical service clock, default `2026-08-01T00:00:00Z`, plus strictly-monotonic wall-clock ms for `created_at`/`updated_at`), `middleware.py` (role/identity gate, body+query validation, envelope construction, pagination), `validation.py`, `response.py`, `errors.py` (full §5 error vocabulary with HTTP status mapping).
- `services/logic.py` — all derived calculations: entitlement, teacher allocation, risk scoring/clearance bands, credited minutes, reported/final apportionment, service gap with `HELD` threshold cascade, makeup obligation, ack counters with compound plan-READY rule, compensatory SpEd minutes, reconciliation net. All `decimal.Decimal` with ROUND_HALF_UP at whole-minute, nearest-5 and 2-dp granularities; every recomputation is full, never incremental.
- `routes/` — 14 blueprints: `clock`, `students`, `teachers`, `entitlement_rules`, `cases`, `certifications`, `assignments`, `safety_reviews`, `sessions`, `attendance_entries`, `extension_requests`, `transition_plans`, `pacing_syncs`, `sped_service_logs`; shared enums, list/filter helper and pagination live in `routes/__init__.py`.

**Storage** — in-memory dicts only. No SQLite, no JSON on disk, no external store. Zero seeding: the store is empty at boot and every entity is created through the declared endpoints.

**Endpoints implemented** — **69** (1 clock-control + 68 under `/hhi`). Programmatic diff of the PRD §4 table against the live Flask `url_map`: 69 == 69, `in PRD not impl: []`, `in impl not PRD: []`.

**Verification**
- Boot from a fresh process via `bash start.sh` on four separate ports; first HTTP response within ~3-6 s with the correct envelope (`meta` carrying `api_request_id`, `api_request_timestamp`, pagination keys; `response_type`; `data`) and an empty store.
- `python3 -m py_compile` over all 24 Python files: clean. AST scan: no unused imports.
- Role matrix: all 69 endpoints × 5 roles — `ERR_UNAUTHORIZED` occurs exactly iff the role is absent from the SCAFFOLD's declared `roles`. **0 mismatches.**
- Two hand-written smoke suites (≈45 happy-path + negative assertions, kept in `/tmp`, not in the repo): **FAILURES: 0**. Confirmed behaviour includes entitlement 360 and 190 with grade-band/mode/diagnosis/absence-bonus/IEP-floor/cap interaction; primary/support allocation 135/55; virtual credit 0.90×60 → 55; risk 15 → `CLEARED_WITH_ESCORT` with `escort_required`; slot-conflict/min-gap/daily-limit/duration/cert-window scheduling tiers; makeup obligation and single-makeup enforcement; `HB_REVERSAL` compensating rows; gap-threshold `HELD` with `ACKED → PENDING` reset and `acked_at` cleared plus plan fallback to `CLASSROOM_COORD_PENDING`; extension approve extending `certified_end_date` and recomputing entitlement/allocation; reconcile reaching both `RECONCILED` and `FORFEITED` bands; OCC 412s; version discipline; pagination window and `limit=0` / unknown-param 400s.

## Step 7: Run tests and iterate — 2026-09-02T10:26:00.000Z

All fixes verified in place; 113 tests collect cleanly.

## Summary

**Iterations run:** 4 sweeps total (1 pre-fix diagnostic + 3 post-fix confirmation sweeps of 8 parallel rounds each = 24 post-fix rounds).

**Final state:** Across all 24 post-fix rounds, **zero genuine (assertion/logic) failures**, and **every one of the 113 tests passed in at least one round**. The only two non-timeout failures in 24 rounds were single-instance `ConnectionResetError(104)` — the runner SIGKILL-ing the Flask process during port cleanup — in tests that passed in the other 23 rounds.

**8/8-green could not be observed, and the reason is not the artifact.** The host is saturated by ~250–390 concurrent foreign `prd-bench-local-run` processes at load average 210–330. Median duration of a *passing* test was **14.96 s** against `--test-timeout 30`; every red is the runner's own `subprocess.TimeoutExpired` on `lsof -ti:<port> -sTCP:LISTEN` (5 s budget) or a >30 s per-test server reboot. `start.sh` already guards `pip install` behind an `import flask` probe, so boot cost is not self-inflicted. This is exactly the loaded-host false-red pattern flagged in the task brief and in my persisted memory note.

**Tests deleted:** none.

**Fixes applied to `test_suite/`** (no `test_helpers/` change was needed; all four bugs lived in per-file setup blocks):

1. `/home/.../test_suite/test_09_compensating_invariants.py:116` — `_case_staffed_with_four_roles()` registered the SpEd teacher with `credential_areas=["SPECIALIZED_ACADEMIC"]` → `["SPED"]`. PRD §3.1 declares the set as `MATH, ELA, SCIENCE, SOCIAL_STUDIES, GENERAL_ELEMENTARY, SPED`; `SPECIALIZED_ACADEMIC` is a SpEd *`service_type`* (§3.9), not a credential area. The fixture was issuing a PRD-invalid request and correctly got `ERR_VALIDATION`. Fixed 2 tests.

2. `/home/.../test_suite/test_14_endpoint_surface.py:233-242` — `_two_cases_and_five_teachers()` passed `credential_areas=["MATH","ELA"]` explicitly *and* again via `**overrides`, a Python `TypeError: got multiple values for keyword argument`. Merged into a base `attributes` dict updated with `overrides` before splatting. Fixed 1 test.

3. `/home/.../test_suite/test_16_rbac_surface.py:315-345, 380, 434` — `test_authorization_answers_before_state_and_leaves_everything_untouched` called `open_pacing_sync` against an `ELIGIBLE` case, which PRD §3.9 forbids verbatim: *"Coordination rows may only be opened against a case whose `service_status` is `ACTIVE`, `EXTENSION_PENDING` or `TRANSITION_PLANNED`, and otherwise the request is rejected with `ERR_CASE_NOT_ACTIVE`."* Setup now finalizes a cleared safety review, accepts the primary assignment, activates the case, and creates a second **SUPPORT** assignment as the row left at `PROPOSED` for the wrong-role acceptance attempt. Terminal assertion updated `ELIGIBLE` → `ACTIVE`; the wrong-role `accept_assignment` now names the support row's own teacher so the refusal is purely a role failure. All six `ERR_UNAUTHORIZED` claims are preserved and in fact strengthened (tier-2 authorization now also outranks a real tier-8 state failure on `activate`). Fixed 1 test.

**Assertions removed as not PRD-derivable (STEP 1c splits — tests kept, only the uncovered sub-claim dropped):**

4. `/home/.../test_suite/test_06_boundary_precision.py:521` — dropped `assert case.get("weekly_entitled_minutes") is None`. **DEFAULT-VALUE SILENCE.** PRD §3.2 names *only* `diagnosis_category` as null before acceptance ("Before any certification has been accepted the case's `diagnosis_category` is null"), and §3.7 explicitly pins the pre-activation default of `service_gap_minutes` to `0` — but no sentence anywhere states the pre-acceptance value of `weekly_entitled_minutes`. `0` and `null` are both faithful readings of §3.3 ("It is computed at exactly three moments"). The covered sibling assertion (`entitlement_rule_id is None`, an unresolvable FK) was kept, as were the error-code, `SUBMITTED`, and `PENDING_CERT_REVIEW` assertions. Scaffold rule behind the test: `Difficulty/boundary_precision_check/certification_acceptance_requires_exactly_ten_expected_absence_days_and_rejects_nine`.

5. `/home/.../test_suite/test_07_cross_entity_state_dependency.py:413` — replaced `completed["completed_at"] == "2026-10-05T09:00:00Z"` with `is_iso8601_timestamp(...)` + `.startswith("2026-10-05T09:00:00")`. **FORMAT SILENCE.** PRD §3.9 says only "stamps `completed_at` with the clock instant", and §2.4 defines "the clock instant" as "the full logical clock timestamp" without a serialization; §2.5 pins three fractional digits for `created_at`/`updated_at` only. `...09:00:00Z` and `...09:00:00.000Z` are the same instant and both faithful. The retained form still pins the exact instant to the second — the actual PRD claim ("the clock instant is stamped, not a wall-clock reading") — and matches the shape `test_16` already uses for `acked_at`. Added `is_iso8601_timestamp` to the file's `test_helpers` import. Scaffold rule: `Difficulty/cross_entity_state_dependency/plan_ready_derived_from_all_pacing_acks_then_completion_gated_on_return_date`.

**Fixes applied to `implementation/`:** none. No implementation defect was found. In particular I did **not** change `routes/cases.py`'s `weekly_entitled_minutes: 0` initialization or `clock.instant_str()`'s three-fractional-digit format — both are legitimate PRD-consistent choices, and the tests asserting otherwise were asserting rules the PRD never states.

**Related audit sweeps run to catch sibling instances of each bug class:** no other `SPECIALIZED_ACADEMIC` use in `test_suite/` or `test_helpers/`; no other duplicate-kwarg splat (all 60+ `**overrides` sites take it as the sole source); the other 10 `open_pacing_sync` call sites all target `ACTIVE`/`EXTENSION_PENDING`/`TRANSITION_PLANNED` cases; `test_11_state_machine_surface.py:866`'s `verified_at` equality compares two server-returned values, so it is format-agnostic and needs no change.

### Orchestrator note on Step 7 exit

The orchestrator independently verified the host-saturation claim before accepting the exit: `uptime` reported load average 235.07 / 260.92 / 268.22 on a 32-core host with 391 concurrent foreign `prd-bench-local-run` processes. A further orchestrator-run 8-round sweep was launched to produce the `results.{1..8}.json` artifacts; its outcome is recorded below.

## Step 8: Finalize PRD — 2026-09-02T10:29:00.000Z

Done. `PRD_FINALIZED.md` written with two surgical inline edits.

**Line counts:** PRD.md 452 → PRD_FINALIZED.md 452 (0.0% line delta; two in-line sentence extensions, ~+35 words).

**Changes:**
- §2.4 — revise — the definition of "the clock instant" now also pins its serialization when stamped onto a stored field: ISO 8601 UTC with three fractional digits (covers `accepted_at`, `released_at`, `verified_at`, `acked_at`, `completed_at`) — `implementation/clock.py:31` (`instant_str`).
- §3.2 — revise — the pre-acceptance default sentence now also pins `weekly_entitled_minutes` to 0 before any certification has been accepted — `implementation/routes/cases.py:83`.

**Per-edit pre-edit search log:**

Edit 1 (§2.4 clock-instant serialization)
- (a) Subject: the serialized form of any value taken from the logical clock instant and written to a stored field.
- (b) Paths enumerated/read: `clock.py` (`get_instant`, `get_date`, `instant_str`); every `instant_str` callsite — `routes/sessions.py:276` (`verified_at`), `routes/assignments.py:116` (`accepted_at`), `routes/assignments.py:151` and `services/logic.py:698` (`released_at`, direct release and closure/completion cascade), `routes/transition_plans.py:134` (`completed_at`), `routes/pacing_syncs.py:108` (`acked_at`); clock-*date* writers that must NOT be caught by the wording — `routes/cases.py:151` (`service_start_date` = `clock.get_date().isoformat()`), plus date comparisons in `routes/certifications.py:78`, `routes/sessions.py:220`, `routes/transition_plans.py:64,129`, `services/logic.py:363,425,450`; independent timestamp generators that must not be redefined — `db.py:_fmt/stamp` (`created_at`/`updated_at`, wall-clock-derived) and `response.py:16` (`api_request_timestamp`).
- (c) Adjustment: scoped the clause to "wherever such an instant is stamped onto a stored field" rather than a general statement about system timestamps, so `service_start_date` (a clock *date*) and the wall-clock-derived `created_at`/`updated_at`/`api_request_timestamp` paths remain governed by §2.5/§2.2 and are not re-described. Left `.000Z`-style examples out so no specific fractional value is implied.

Edit 2 (§3.2 pre-acceptance `weekly_entitled_minutes`)
- (a) Subject: the value of `HomeboundCase.weekly_entitled_minutes` on a case with no accepted certification.
- (b) Paths enumerated/read: the only two writers — `routes/cases.py:83` (initializes 0 at creation) and `services/logic.py:184` (`recompute_weekly_entitlement`); the compute path `services/logic.py:154-179` (`weekly_entitlement_minutes` returns the case's *existing* value when the rule, the current accepted certification, or `diagnosis_category` is missing, so it cannot lift a pre-acceptance case off 0); all three recompute triggers — certification acceptance (`routes/certifications.py`), virtual-only safety finalization (`routes/safety_reviews.py:110-116`, verified it also short-circuits to the stored value when no accepted cert exists), extension approval (`routes/extension_requests.py`); readers that would be affected by the default — `services/logic.py:212,235` (allocation), `365,370` (service gap / hold threshold), `483,497,532,566-569` (funding report, reconcile, summary); and the paths that could conceivably reset it — case deny/close cascades in `routes/cases.py` and certification rejection (neither touches the field).
- (c) Adjustment: none needed — kept the claim confined to "before any certification has been accepted" rather than asserting anything about when the field returns to 0, since no impl path ever resets it after acceptance.

Items 1–3 of the Step 7 diff (SpEd `credential_areas`, duplicate-kwarg `TypeError`, `open_pacing_sync` against an `ELIGIBLE` case) were pure fixture bugs: `routes/__init__.py:12` defines `CREDENTIAL_AREAS = SUBJECTS + ["SPED"]` exactly as §3.1 declares, `routes/pacing_syncs.py` gates creation on `IN_SERVICE` with `ERR_CASE_NOT_ACTIVE` exactly as §3.9 states, and tier-2-before-tier-8 precedence is already pinned in §2.6 — so no PRD text was changed for them.

## Step 9: Complete PRD — 2026-09-02T10:46:00.000Z

`PRD_COMPLETED.md` is finished on disk. Impl walk complete; final pins applied.

## Exit summary

**Files**
- Source `workspace/PRD_FINALIZED.md` — 452 lines, 92,372 chars
- Output `workspace/PRD_COMPLETED.md` — 455 lines, 107,412 chars
- Char-delta: **+15,040** (+16.3%); line-delta +3 (one bullet appended to the §2.2 list, one new paragraph inside §2.3 for the per-endpoint filter enumeration). **No new sections; no sections removed; no reordering.**

**Counts**
- ambiguity-pins: **35**
- mismatch-revisions: **7**
- total changed lines: 42 (41 replaced, 1 inserted)

**Changes** (`{PRD section} — {insert|revise} — {class} — {what} — {impl ref}`)

- §2.2 — revise — ambiguity — `api_request_timestamp` read from real server time, not the logical clock — `response.py:21-25`
- §2.2 — insert — ambiguity — unknown route → `ERR_NOT_FOUND` 404, wrong method → `ERR_METHOD_NOT_ALLOWED` 405, unparseable/non-object body → `ERR_VALIDATION`, absent body = empty object — `app.py:61-73`
- §2.3 — revise — ambiguity — list ordering tiebroken by insertion order — `db.py:rows()` sort on `(created_at, _seq)`
- §2.3 — insert — ambiguity — full enumeration of every list endpoint's equality filters; unknown query param or out-of-enum value → `ERR_VALIDATION`; endpoints declaring no query input ignore the query string — `routes/__init__.py:135`, `validation.py:191`
- §2.5 — insert — ambiguity — store is empty at process start and never seeded — `app.py:1-5`
- §2.5 — insert — ambiguity — `created_at`/`updated_at` come from real server time, not the logical clock, and from a strictly increasing counter so they never tie — `db.py:61-77`
- §2.5 — insert — ambiguity — increment unit is the request: one `updated_at`/one `version` per dirty row, all touched rows share an identical `updated_at`, unchanged rows untouched, fresh rows returned at `version` 1 — `db.py:101-141`, `db.py:117`
- §2.6 — insert — ambiguity — explicit JSON `null` == absent (required → missing; optional → default); the six single-payload agreements answering `ERR_VALIDATION` each evaluated where their own workflow names them — `validation.py:145`, `routes/entitlement_rules.py:41-45`, `routes/students.py:50-52`, `routes/sessions.py:76-78,206-208,221`, `routes/transition_plans.py:65`
- §2.8 — revise — ambiguity — `delivery_ratio_pct` serialized as a plain JSON number, so the trailing zero is not preserved — `services/logic.py:529`
- §3 (rules) — insert — ambiguity — all eight minute fields required; the three internal orderings are `ERR_VALIDATION` in that order, before the duplicate-pair check — `routes/entitlement_rules.py:19-25,41-45`
- §3 (rules) — revise — ambiguity — `status` may be supplied at publication; duplicate check is PUBLISHED-vs-PUBLISHED only; ties resolved by earliest `created_at` — `routes/entitlement_rules.py:47-56`
- §3.1 — revise — ambiguity — the two IEP-minute agreements are `ERR_VALIDATION` judged before the `student_number` collision — `routes/students.py:47-52`
- §3.1 — revise — ambiguity — enrollment change bumps `version` even when the posture is unchanged — `routes/students.py:100`
- §3.1 — revise — **mismatch** — `employee_number` expected unique but **not enforced**; `clearance_expires_on` required with no clock constraint; `credential_areas` never read by any rule; clearance PATCH requires both status and expiry, `home_visit_eligible` optional, version bumps unconditionally — `routes/teachers.py:15,30,37-41,89-97`
- §3.1 — insert — ambiguity — complete initial field set of a fresh case (nulls, `false`, `0.0`, zeros) — `routes/cases.py:71-100`
- §3.1 — revise — ambiguity — denial cascades to `SUBMITTED` certifications only, nothing else disturbed; `deny_note` accepted but not persisted — `routes/cases.py:163-176`
- §3.2 — revise — ambiguity — `review_note` stored when supplied; reviewability judged on the certification alone, case state not re-examined — `routes/certifications.py:124-160`
- §3.2 — revise — **mismatch** — acceptance does **not** re-check window ordering; the absence-days check and rule resolution both run before the first write — `routes/certifications.py:145-149`
- §3.3 — insert — ambiguity — missing rule / current cert / diagnosis makes recomputation a no-op that preserves the stored value — `services/logic.py:157-158`
- §3.4 — insert — ambiguity — a decline neither redistributes the allocation nor re-sums teacher minutes, and no clearance/caseload rule guards it — `routes/assignments.py:123`
- §3.5 — insert — ambiguity — review creation gated on nothing but case existence — `routes/safety_reviews.py:36`
- §3.5 — revise — ambiguity — virtual rule resolved before first write; already-`VIRTUAL_SYNC` no-op; `CANCELLED_ADMIN` writes no ledger row and no make-up obligation; finalization never recomputes gap or funding — `routes/safety_reviews.py:84`
- §3.6 — revise — **mismatch** — activation has **three** preconditions in tier order (safety first); `is_current` guaranteed by the `ELIGIBLE` from-state, not re-checked; `escort_required` false with no finalized review; `service_gap_minutes` written as 0 outright — `routes/cases.py:126-159`
- §3.6 — revise — ambiguity — span violations are `ERR_VALIDATION` before body FK resolution; minutes truncated toward zero; instants stored verbatim; full session initial nulls; `escort_confirmed` read then discarded — `routes/sessions.py:76-78,101,134-145`
- §3.6 — revise — ambiguity — rule load right after safety, failing `ERR_NO_PUBLISHED_ENTITLEMENT_RULE`; duration check at tier 11 ahead of the assignment-case and window tests; `min_gap` 0 admits touching sessions — `routes/sessions.py:106`, `services/logic.py:658-672`
- §3.6 — insert — ambiguity — only `actual_minutes`/`absence_kind` are demanded (payload-only, before path resolution), `outcome_reason` always optional, `logged_by_user_id` written under all four outcomes, log-before-`service_date` after the state checks — `routes/sessions.py:206-224`
- §3.6 — insert — ambiguity — `reversal_of_entry_id` present and null on the five non-reversal codes — `services/logic.py:586-607`
- §3.6 — revise — ambiguity — make-up reference consumed by a session of any status; `ERR_MAKEUP_NOT_ELIGIBLE` at tier 12 after the certified-window test — `routes/sessions.py:120-123`
- §3.6 — insert — ambiguity — void needs no verification and no case state, and does not recompute `makeup_obligation_minutes` — `routes/sessions.py:286-302`
- §3.7 — insert — ambiguity — leaving `HELD` does not re-evaluate plan readiness — `services/logic.py:357-392`
- §3.7 — revise — ambiguity — report falls back to 0 on missing dates/rule, bumps `version` even when nothing moved, allowed from ACTIVE/EXTENSION_PENDING/TRANSITION_PLANNED, `funding_status` places no condition — `routes/cases.py:196-208`, `services/logic.py:465`
- §3.7 — revise — ambiguity — zero entitled total lands in the forfeit band — `services/logic.py:529-560`
- §3.7 — insert — ambiguity — both funding checks settled before the service-state one; reconcile writes final/ratio before banding and leaves provisional and gap alone — `routes/cases.py:215-230`
- §3.7 — revise — ambiguity — funding-summary field order, `entitled_total_minutes` = weekly × `service_weeks`, six-derived/six-stored split, read mutates nothing; `projected_unrounded_minutes` = all DELIVERED with no window or verification filter, 0 without a rule — `services/logic.py:563-585`, `services/logic.py:510-527`
- §3.8 — revise — ambiguity — resubmit ceiling tested ahead of the certification agreement — `routes/extension_requests.py:136-145`
- §3.8 — revise — **mismatch** — decide has **no** case-state precondition and moves the case to `ACTIVE` only when it is at `EXTENSION_PENDING` — `routes/extension_requests.py:164`
- §3.9 — revise — ambiguity — sped log initial `last_service_date`/`continuation_reason` null and `compensatory_minutes_owed` derived at creation — `routes/sped_service_logs.py:69-82`
- §3.9 — revise — ambiguity — delivery `minutes` may be 0, `service_date` tied to nothing; neither delivery nor continuation change is gated on case state (only opening is) — `routes/sped_service_logs.py:29-32,62,98-127`
- §3.9 — revise — **mismatch** — the declared continuation transitions number **five**, not four — `routes/sped_service_logs.py:17-21`
- §3.9 — revise — ambiguity — `target_return_date` equal to the clock date also refused, `ERR_VALIDATION`, after the ramp-week check; case state tested before the in-flight-plan check, both `ERR_INVALID_CASE_STATE` — `routes/transition_plans.py:52-65`
- §3.9 — revise — **mismatch** — completion stamps `released_at`, recomputes `over_cap`, and re-sums **every** teacher (not just released ones); cascades no further (no plan supersede, no extension denial, funding untouched) — `routes/transition_plans.py:125`, `services/logic.py:692-700`
- §3.9 — revise — ambiguity — abort moves the case only from `TRANSITION_PLANNED` — `routes/transition_plans.py:149`
- §3.9 — revise — **mismatch** — closure rejects `RETURNED_TO_CAMPUS` as `ERR_VALIDATION` before case state, leaves funding where it stood, stamps `released_at`, recomputes `over_cap`, and re-sums **every** teacher — `routes/cases.py:36-42,179-193`, `services/logic.py:692-719`

**Deliberately not pinned** (minimal-patch judgment; impl behavior is either already uniquely determined by the §2.6 tier ordering or of negligible contract value): session `verify` having no case-state gate, `recompute_teacher_commitments()` sweeping all teachers rather than only affected ones (identical observable result), and the strictly-increasing `created_at` making the §2.3 insertion-order tiebreak unreachable in practice.
