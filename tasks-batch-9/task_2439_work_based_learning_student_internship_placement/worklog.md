# Worklog — task_2439_work_based_learning_student_internship_placement

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2439_work_based_learning_student_internship_placement` and its `workspace/` subdirectory. Index 2439 was pre-assigned by the orchestrating command (no ./tasks/ scan performed, per instruction — concurrent pipelines on this host).

## Step 2: Generate Scaffold — 2026-09-02T00:20:00.000Z

All three scaffold artifacts are complete and the lint is clean.

Lint verdict block (verbatim, final run):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2439_work_based_learning_student_internship_placement/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2439_work_based_learning_student_internship_placement/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2439_work_based_learning_student_internship_placement/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    63
  §1.1 entities declared:     14
  §1.8 instances scanned:     19
  §1.9 instances scanned:     39
  Calls scanned (§1.8+§1.9):  793

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Worklog summary

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2439_work_based_learning_student_internship_placement/`): `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`. Scenario text used verbatim; no sibling task was read.

- SCAFFOLD.yaml (§1.0–§1.7): domain `work-based-learning`, prefix `/wbl`; archetype Compliance/audit + Temporal windowing; layers dual_variant_calculation, cascading_side_effects, optimistic_concurrency, rate_threshold_triggers; topology flat, state shape parallel, role_model segregation_of_duties, consistency immediate. 14 entities, 8 state machines, 8 calculations, 3 OCC concurrency rules (412 on `expected_worksite_version` / `expected_placement_version`), 52 validations (single ladder priority 1–52), 63 endpoints, 63 errors, 5 roles.
- SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8): all 9 rule_ids, 19 instances — dual_variant_calc 2, combinatorial_formula 2 (different modes), non_linear_state_machine 2, transitive_cascade 2 (depths 4 and 3), priority_pair_validation_conflict 3 (distinct error-category pairs), boundary_precision_check 2 (different metrics/endpoints), cross_entity_state_dependency 2, resource_temporal_overlap 2 (half-open shift intervals vs closed date intervals), compensating_invariant 2 (hour ledger, slot counters). All formula-derived asserts are pre-computed literals.
- SCAFFOLD_CORNER_DESIGN.yaml (§1.9): 39 instances over all nine claim-extraction sections — entities 9 real + 1 stub, state_machines 8 + 2, calculations 5 + 5, validations 4 + 5, endpoints 3 + 3, errors 2, rbac 4, cross-cutting complexity layers 3 + 3, consistency model 1 (29 real recipes, 10 `excluded_because` stubs, each citing a named §1.8 instance). All 77 instance names unique across both design files; no stub carries a `test_recipe`.

Two scaffold-level fixes made while auditing:
- Added the missing `EvaluationCycle PARTIAL → PARTIAL` transition (`reflection-decision decision=ACCEPT` while `supervisor_eval_status == PENDING`) so the declared "join point reachable from either branch" close is actually reachable.
- Renamed the parent placeholder to `{id}` on the 9 sub-resource GETs (e.g. `GET /wbl/placements/{id}/evaluation-cycles`), which is the canonical §1.5 form the linter's FK reverse-reachability check (f) requires; this cleared 9 `FK_REVERSE_UNREACHABLE` violations, the only ones the lint ever reported.

## Step 3: Copy Shared Files — 2026-09-02T00:21:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T00:36:00.000Z

Orchestrator truncation check: `tail` of workspace/PRD.md ends at the final §5 error-catalogue row (`ERR_WAGE_SETTLEMENT_NOT_READY | 422`), a real section boundary — not truncated. 505 lines, headings §1–§5 all present.

Subagent summary (verbatim):

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2439_work_based_learning_student_internship_placement/workspace/PRD.md` — **505 lines, 12,280 words**. The two design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

## Sections written

- **§1 Introduction** — 3 paragraphs (district WBL coordinator pain, service scope, two design commitments: computed compliance facts + explicit logical clock).
- **§2 Global Specifications** — 11 domain-derived subsections: 2.1 Operators, Roles and Identity · 2.2 API Response Structure (pasted verbatim from `section-2.2-response-structure.md`, byte-identical) · 2.3 Pagination and List Ordering · 2.4 The Logical Clock and Deferred Expiry Sweeps · 2.5 Common Record Properties · 2.6 Stale-View Protection on Worksite and Placement Parents · 2.7 Units, Precision and Rounding · 2.8 Path Resolution for Nested Reads · 2.9 Request Evaluation Order · 2.10 Conserved Counters and Cascade Discipline · 2.11 Segregation of Duties.
- **§3 Business Logic & Workflows** — 10 subsections (partner/worksite recruitment; safety review + posture; agreement negotiation/execution/termination; students, eligibility, permits; placement construction; training plans + 3-hop approval cascade; child-labor hour logging; parallel evaluation cycles; incident adjudication + coverage + compliance dimension; close-out covering completion, wage settlement, credit, reimbursement, outcomes).
- **§4 Endpoint Definitions** — 4-column table, 63 rows.
- **§5 Error Code Catalogue** — 2-column table, 63 rows. File ends on the final table row; no audit footer.

## Coverage

- **14 entities / 142 field names** — all present verbatim in backticks. `LearningObjective`'s `common_fields: false` exception (only `id` + `created_at`, no `updated_at`, no `version`) called out explicitly in §2.5.
- **63 endpoints** — method+path exact match against scaffold, zero missing, zero extra; authorized-role lists match the scaffold role arrays exactly on all 63 rows.
- **63 errors** — all present with correct HTTP status; catalogue order identical to scaffold order.
- **52 validations** — the §2.9 evaluation ladder is a 1:1 positional match to `validations[].priority` 1–52 (verified programmatically).
- **8 state machines / 49 transitions**, all 33 distinct states, all 96 enum literals, all 32 calculation constants, 8 calculations, 3 OCC rules, 96 endpoint input identifiers, 24 computed-read output keys, 13 path params — all present.

## Hard Contract reports

```
Field coverage check:
- entities[].fields: 142 required, 142 present, 0 missing
- endpoints[].input (request body) identifiers: 96 required, 96 present, 0 missing
- endpoints[].query_params: 18 required, 18 present, 0 missing (subset of the 96)
- path_params: 13 required, 13 present, 0 missing
- computed-read output keys: 24 required, 24 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 52 checked, 52 expressed in prose (positional 1:1 with scaffold priority), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write operation + expected_worksite_version / expected_placement_version + ERR_STALE_WORKSITE_VERSION / ERR_STALE_PLACEMENT_VERSION all named), 0 missing
- state_machines[].transitions: 49 checked, 49 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed with all 32 constants, 0 missing
- validations[] conditions: 52 checked, 52 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all checked, all expressed, 0 missing
- entities[].fields[] structured content: 142 checked, 142 reconstructible from prose, 0 missing
- sibling-branch symmetry: 7 groups checked (3 safety-review decisions; 3 posture/severity incident branches; 2 wage rounding variants; 2 credit award models; 4 transportation modes; 2 permit-band cap sets; 2 reflection-ACCEPT branches), 7 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1100
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Two fixes applied during verification: the tier fee rates were rewritten from spelled-out fractions to the literal `0.10` / `0.075` / `0.05`, and the tail was confirmed to terminate cleanly at the last `ERR_WAGE_SETTLEMENT_NOT_READY | 422` row of §5 (no truncation, no mid-sentence cut).

## Step 5: Generate Unit Tests — 2026-09-02T02:12:00.000Z

Generation is complete. Both queues are translated, and every audit passes.

## Files written

**`test_helpers/`** (Stage 1, complete): `__init__.py` (barrel), `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`

**`test_suite/`** (Stage 2, complete): `conftest.py` plus 18 test modules
- Queue A (depth, §1.8): `test_01_wage_and_credit_dual_variants.py` (4), `test_02_settlement_and_reimbursement_formulas.py` (4), `test_03_non_linear_state_machines.py` (4), `test_04_transitive_cascades.py` (4), `test_05_validation_precedence_pairs.py` (6), `test_06_boundary_precision.py` (4), `test_07_cross_entity_state_dependencies.py` (4), `test_08_temporal_overlap.py` (4), `test_09_compensating_invariants.py` (4)
- Queue B (breadth, §1.9): `test_10_entities.py` (9), `test_11_state_machines.py` (8), `test_12_calculations.py` (5), `test_13_validations.py` (4), `test_14_endpoints.py` (3), `test_15_errors.py` (2), `test_16_rbac.py` (4), `test_17_concurrency_layers.py` (3), `test_18_consistency.py` (1)

## Test counts

| Queue | Instances live | Instances covered | Tests |
|---|---|---|---|
| A — Difficulty | 19 | 19 (all >= 2 tests) | 38 |
| B — Corner | 39 | 38 | 39 |
| **Total** | **58** | **57** | **77** |

## Coverage audit (all machine-checked)

- Design tags: 77/77 tests carry exactly one `Design:` line as the final docstring line; every tag resolves to a real non-stub instance in the source yaml, and every tag's section/`rule_id` segment matches the instance's own section. No unknown, missing, or dual tags.
- Queue A completeness: all 19 difficulty instances have >= 2 tests; none under-covered.
- Queue B completeness: 38 of 39 non-stub corner instances covered >= 1 (one deliberate skip, below). Excluded/stub instances (19 in the corner index) were not translated, as intended.
- Final PRD-citation pass: every docstring sentence (whole body first, then per-sentence chunks) is a verbatim substring of `workspace/PRD.md` modulo whitespace — 0 misses.
- Hygiene: `pyflakes` clean on `test_suite/`; every `test_helpers` import resolves via the barrel; every `api_client.*` method exists; no `skip`/`skipif`/`xfail`/mocking; no reference to the scaffold in prose. `pytest --collect-only` collects 77 tests with no import errors.

## Skipped instance (1)

- `Corner/entities/employer_partner_create_system_and_computed_fields_input_ignored` — **computed-field silence**. The PRD never states that a create body carrying non-writable computed fields is accepted and the extra fields ignored (the only "ignor..." text in the PRD is in the credit-calculation paragraph), while ladder step 8 makes `ERR_INVALID_REQUEST` (400) an equally defensible reading. The asserted 201 is therefore not uniquely derivable, so the instance was dropped rather than weakened.

## Design-index defects corrected at emit time (PRD wins)

- Invalid `industry_sector` literals in the index (`RETAIL`, `TRANSPORTATION`, `FOOD_SERVICE`) replaced with valid PRD enum members (`HOSPITALITY`, `CONSTRUCTION`, `PUBLIC_ADMINISTRATION`) — the PRD enumerates only `MANUFACTURING`, `HEALTHCARE`, `CONSTRUCTION`, `INFORMATION_TECHNOLOGY`, `HOSPITALITY`, `PUBLIC_ADMINISTRATION`.
- `ERR_INVALID_REQUEST` asserted at HTTP **400** (index said 422) — it is ladder step 8 and the error table gives 400.
- Two index instances asserted absolute `version` arithmetic that the PRD does not support (`Worksite.version == 2` after file+decide; `Placement.version == v1 + 1` after draft+approve). Those tests assert the PRD-derivable facts instead: the pre-mutation value is strictly less than the current one, and the rejected write leaves the version unchanged.

## Step 6: Generate Implementation — 2026-09-02T01:32:00.000Z

Implementation complete and validated end to end.

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_2439_work_based_learning_student_internship_placement/workspace/implementation/`:

**Launcher / infra**
- `start.sh` — `set -euo pipefail`, `cd $(dirname $0)`, installs `requirements.txt` only if Flask is missing, then `exec python3 app.py`. Binds `0.0.0.0:$PORT` (default 10000), `threaded=True`, `use_reloader=False`.
- `requirements.txt` — `flask>=2.0`
- `app.py` — `create_app()` registers all 10 blueprints at `url_prefix="/wbl"`, `strict_slashes = False`, handlers for `ApiError`, 400/404/405/415 and a catch-all `Exception` -> 400 `ERR_INVALID_REQUEST`.
- `errors.py` — all **63 error IDs** -> HTTP status (ID set verified identical to PRD.md and SCAFFOLD.yaml, empty diff), `ApiError`, `fail()`.
- `db.py` — `Store` of 14 in-memory dicts, **nothing seeded**; logical clock defaults to `2026-08-01T00:00:00Z`; `new_record`, `touch`, `set_and_touch` (bumps `version` by exactly 1 only when a value actually changes), date/ISO helpers.
- `response.py` — envelope builders; Decimal->float conversion, `_`-prefixed keys stripped; `req_` + 20 uppercase alnum request IDs, 3-fractional-digit UTC timestamps.
- `auth.py` — `X-User-ID` / `X-User-Role`, 5 roles, `require(*allowed)`.
- `validation.py` — typed field extractors, `parse_iso_dt`, pagination (limit 1–100 default 10, offset >= 0), `paginate`.
- `calc.py` — eligibility, safety score/posture, child-labor bands, wage variants (PROVISIONAL per-entry vs FINAL terminal rounding), competency score, hours-based vs competency-based credit, reimbursement tiers, outcome rate, insurance coverage determination. All money/decimal math via `Decimal` + `ROUND_HALF_UP`.
- `derive.py` — FK resolvers, collection views, conserved-counter recomputation from source-of-truth rows, evaluation-cycle lifecycle (`derive_cycle_status`, spawn/close/suspend/cancel/restore), and the incident/agreement/permit cascades.

**Routes (63 endpoints total, verified by decorator count)**
`partners.py` 12 · `placements.py` 12 · `plans.py` 8 · `agreements.py` 7 · `students.py` 7 · `incidents.py` 5 · `cycles.py` 4 · `outcomes.py` 4 · `timesheets.py` 3 · `clock.py` 1.

`python3 -m compileall` clean; storage is in-memory only and wiped on every boot, so `--isolation per-test-server` gets a pristine state each test.

## Validation performed

Three independent smoke suites against fresh boots, all green: a ~50-step happy path, a ~60-step cascade/negative-path suite, and targeted probes of the hour-cap and overlap machinery. Confirmed among others: worksite `version == 3` after file+approve; self-execution 403; both OCC 412s; frozen `student_age_at_start`/`permit_class_at_start`; plan-approval triple-hop leaving `ACTIVE`/`CLEARED` with cycle 1 and exactly one `Placement.version` bump; CRITICAL-incident cascade (worksite `FAILED` -> partner `SUSPENDED`/score 50 -> placement `BLOCKED` -> cycle `SUSPENDED`), then re-review -> `PROBATION` -> UNBLOCK -> `FLAGGED` with the cycle restored to `PARTIAL`; half-open overlap with the 30-minute cross-worksite buffer (abutting shifts accepted, 20-min cross-site gap refused, 30-min gap accepted); MINOR_16_17 weekly ceiling exactly 48.00 h accepted / 56 refused, Sunday week reset; ADULT_18_PLUS exempt from all three caps; wage/credit/reimbursement previews; SoD 403 on award-credit; the three clock sweeps returning correct counters.

## PRD ambiguities resolved

- **Undeclared-error gaps -> `ERR_INVALID_REQUEST` (400)**: safety-review decision matching no branch; `insurance_rider` not true at execute; permit `expires_on` before the clock date; compliance-decision from an invalid compliance state; voiding an already-VOIDED entry.
- **Validation ordering** follows §2.9 numeric priority over narrative order (e.g. plan approve 14->24->25->47; timesheet 3->8->16->18->28->32->33->34->36->37->38; placement create 7->8->9->24...51). Resource existence (404) is resolved before ownership/SoD (403) despite ownership being numbered lower.
- **FK handling**: missing/ill-typed FK -> 400; present-but-unresolvable -> the matching 404, in entity declaration order.
- **`ERR_PLACEMENT_NOT_ACTIVATABLE`** covers all three activate gates. Terminate from COMPLETED/TERMINATED and compliance-decision outside `{PROPOSED, ACTIVE}` -> `ERR_PLACEMENT_NOT_ACTIVE` (409). Verify on `STUDENT_ATTESTATION` -> `ERR_OUTCOME_INVALID_STATE` (409).
- **Clearance expiry scope**: UNBLOCK and plan-approve check `safety_status` only (per §3.9/§3.6); expiry is enforced at agreement employer-sign, placement create and manual activate.
- **Version bumps**: filing a safety review unconditionally resets the worksite to `UNREVIEWED` with null expiry dates and bumps its version; plan draft and plan approve each bump `Placement.version` exactly once even when multiple hops fire.
- **Inverted placement window** -> `ERR_PLACEMENT_WINDOW_INVALID` (422), not a step-8 400.
- Fields carrying a `default:` in the entity block are treated as optional inputs even where the endpoint `input:` list omits `?`.
- Successor cycles spawn only when the **post-increment** `closed_cycle_count` is still below `required_evaluation_cycles`.
- Compliance-decision FLAG accepts `note` but does not persist it — Placement has no such field and none was invented.
- Guardian consent is required unconditionally at placement create even for ADULT_18_PLUS (PRD line 259 states no age exception) — confirmed against the spec rather than assumed.

No file under `test_helpers/`, `test_suite/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml` was read, listed or grepped at any point.

## Step 7: Run Tests and Iterate — 2026-09-02T19:35:00.000Z

Orchestrator-side independent verification (per prior known failure mode where a Step 7 subagent claims a clean sweep without leaving artifacts): `results.1.json` .. `results.8.json` all present on disk with distinct byte sizes (26069–26082 B, so not one round copied 8 times), each parsed independently -> `passed=77 total=77`, `Counter({'passed': 77})` per round. `grep -c` over `test_suite/*.py` finds exactly 77 `def test_*` functions, matching the 77 `total` every round reports (no silent collection loss). `grep` for `skip|xfail` over `test_suite/` + `test_helpers/` -> 0 hits. `grep` for `sqlite|pickle|shelve|/tmp` over `workspace/implementation/**/*.py` -> 0 hits (in-memory storage only). The green result is real.

Subagent summary (verbatim):

Clean sweep on the first iteration — no fixes were needed.

## Summary

**Iterations run:** 1 (single 8-round parallel sweep, all rounds launched concurrently under `setsid nohup`, joined with `wait`, no early exit).

**Result:** All 8 rounds passed 77/77. Aggregate across the sweep: 616 test outcomes, `Counter({'passed': 616})` — zero failures, zero errors, zero skips. No flakiness signal: the union of failing tests across rounds 1–8 is empty, so no test failed in one round while passing in another.

**Tests deleted:** none. No test entered the diagnostic protocol, since STEP 0 produced an empty union of failures.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `workspace/implementation/`:** none.

**Integrity checks performed alongside the sweep (to rule out a falsely-green run):**
- Collection completeness: 77 `def test_*` functions across the 18 files in `test_suite/` exactly matches the 77 `total` reported by every round — no test file silently failed to collect.
- No suppression markers: `grep` for `skip`/`xfail` across `test_suite/` and `test_helpers/` returns nothing, so the green is not from disabled tests.
- Storage discipline: `grep` for `sqlite`, `open(`, `/tmp`, `pickle`, `shelve` across `workspace/implementation/*.py` and `workspace/implementation/routes/*.py` returns nothing — storage is in-memory dicts only, with no startup seeding.
- Sweep artifacts verified on disk: `results.1.json` … `results.8.json` all present in `/home/ubuntu/github/CodingPRD/tasks/task_2439_work_based_learning_student_internship_placement/workspace/implementation/`, each an independently completed round (not a single round copied 8 times).

One note on the run itself: the host was heavily contended during the sweep (150–190 concurrent `prd-bench-local-run` processes from other pipelines), and the sweep still came back fully green in roughly 3 minutes of wall time. That is the load condition under which spurious timeout/connection-refused failures normally appear, so the clean result holds under load rather than only on a quiet host.

Key files, for reference:
- PRD contract: `/home/ubuntu/github/CodingPRD/tasks/task_2439_work_based_learning_student_internship_placement/workspace/PRD.md`
- Implementation: `/home/ubuntu/github/CodingPRD/tasks/task_2439_work_based_learning_student_internship_placement/workspace/implementation/` (3348 lines; `routes/` split by resource, with `calc.py`, `derive.py`, `validation.py` carrying the computed-compliance logic)
- Sweep log: `/home/ubuntu/github/CodingPRD/tasks/task_2439_work_based_learning_student_internship_placement/workspace/sweep.log`

## Step 8: Finalize PRD — SKIPPED — 2026-09-02T19:36:00.000Z

Skip condition met and independently confirmed by the orchestrator: Step 7 exited on its first 8-round sweep with 0 iterations beyond the baseline, 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes and 0 `implementation/` fixes. With an empty `<step_7_diff>` there is no PRD-silence or PRD-mismatch site for Step 8 to patch, and the skill instructs not to spawn the subagent in this case. No `PRD_FINALIZED.md` is produced; Step 9 therefore starts from `PRD.md`.

## Step 9: Complete PRD — 2026-09-02T19:55:00.000Z

Orchestrator verification: `PRD_COMPLETED.md` is 505 lines / 99,736 chars vs `PRD.md` 505 lines / 91,874 chars; `diff` of all `^#` headings between the two files is empty (structure preserved); tail ends at the final §5 row `ERR_WAGE_SETTLEMENT_NOT_READY | 422` — no truncation.

Subagent summary (verbatim):

32 in-place paragraph revisions, no lines added or removed, document structure byte-for-byte identical outside those paragraphs.

## Summary

**Line counts:** `PRD.md` 505 lines / 91,874 chars -> `PRD_COMPLETED.md` 505 lines / 99,736 chars (**+7,862 chars**, +0 lines). All 130 table rows preserved; all headings identical; tail ends at the `ERR_WAGE_SETTLEMENT_NOT_READY | 422` row of §5.

**Counts:** 26 ambiguity-pins, 6 mismatch-revisions (32 edited paragraphs).

### Changes

- §2.1 — insert — ambiguity — blank/whitespace-only header value counts as absent -> `ERR_UNAUTHENTICATED` — `auth.py:20-23`
- §2.3 — insert — ambiguity — `offset` < 0 and non-integer `limit`/`offset` are `ERR_INVALID_REQUEST`; empty value falls back to default; unknown query params ignored — `validation.py:168-187`
- §2.4 — insert — ambiguity — `to_iso8601` offset-normalised / offset-less read as UTC, may move clock backwards; `current_utc` rendered with 3 fractional digits — `clock.py:21-23,63`, `validation.py:142-156`
- §2.6 — insert — ambiguity — unrecognised body keys silently ignored everywhere, so the "no version field" prohibition is unenforced — `validation.py:15-27`
- §2.7 — insert — ambiguity — client-supplied decimals are range-checked then stored/echoed at supplied precision, never re-quantised — `validation.py:79-96`
- §2.9 — insert — ambiguity — steps 3-5 necessarily follow resolution of the addressed record, so a 404 precedes any ownership/SoD comparison — `timesheets.py:28-33`, `placements.py:356-360`
- §2.10 — revise — **mismatch** — a cascade/counter hop that computes the value a row already holds writes nothing and does not bump `version`; directly-addressed rows always bump — `db.py:113-127`
- §3.2 — revise — **mismatch** — review filing clears worksite `safety_review_expires_on` *and* `corrective_actions_due_on` unconditionally (not only after a `CONDITIONAL`), and does not recompute partner score/posture — `partners.py:186-189`
- §3.2 — insert — ambiguity — `decision` unsupported by findings -> `ERR_INVALID_REQUEST`; overlapping predicates honour the supplied decision; findings supporting none are undecidable — `partners.py:207-246`
- §3.3 — revise — **mismatch** — missing `insurance_rider` -> `ERR_INVALID_REQUEST` (400), checked first; posture gate precedes workers-comp gate (prose order was reversed) — `agreements.py:111-117`
- §3.4 — insert — ambiguity — `expires_on` >= issuance-date comparison deferred until after the permit-state and consent gates, reports `ERR_INVALID_REQUEST` — `students.py:111-120`
- §3.5 — revise — **mismatch** — `stipend_total_cents` is not policed on `PAID`/`UNPAID`; only `hourly_wage_cents` is — `placements.py:143-158`
- §3.5 — insert — ambiguity — `supersedes_placement_id` resolves as an FK (`ERR_PLACEMENT_NOT_FOUND`) but the predecessor's lifecycle is not checked — `placements.py:43-46`
- §3.5 — revise — **mismatch** — a `STIPEND` placement opens with `provisional_wage_cents`/`final_wage_cents` at `stipend_total_cents`, not 0; plus `created_by_user_id` is recorded — `placements.py:183-196`
- §3.5 — insert — ambiguity — terminating a `COMPLETED`/`TERMINATED` placement -> `ERR_PLACEMENT_NOT_ACTIVE` — `placements.py:242-244`
- §3.6 — insert — ambiguity — cascade hop 3 creates the cycle only when the placement has no cycles yet — `plans.py:149-150`
- §3.6 — insert — ambiguity — manual activation's compliance/plan preconditions also report `ERR_PLACEMENT_NOT_ACTIVATABLE`, then `ERR_AGREEMENT_NOT_EXECUTED`, then `ERR_WORKSITE_SAFETY_NOT_CURRENT`; `training_plan_approved_at` untouched — `placements.py:212-231`
- §3.7 — insert — ambiguity — the narrated order is not the evaluation order: permit -> child-labor caps -> work-date rules -> overlap, per §2.9 — `timesheets.py:51-107`
- §3.7 — insert — ambiguity — the 30-minute buffer widens the *existing* entry's interval at both ends; candidate compared as submitted — `timesheets.py:103-105`
- §3.7 — insert — ambiguity — voiding a non-`LOGGED` entry -> `ERR_INVALID_REQUEST` — `timesheets.py:138-139`
- §3.8 — insert — ambiguity — the five ratings are persisted on the cycle, null before submission — `cycles.py:53`, `derive.py:291-295`
- §3.8 — insert — ambiguity — `feedback_note` is required but persisted nowhere — `cycles.py:104`
- §3.8 — insert — ambiguity — a reflection ruling also requires `cycle_status` `OPEN`/`PARTIAL`, so `SUSPENDED`/`CANCELLED`/`CLOSED` all refuse it — `cycles.py:107-110`
- §3.8 — insert — ambiguity — `credit_eligible` is restated only at cycle closure; nothing else recomputes it — `derive.py:245-251,313-318`
- §3.9 — insert — ambiguity — reporting against a non-`ACTIVE` placement -> `ERR_PLACEMENT_NOT_ACTIVE`; `occurred_at` stored verbatim, only its date read — `incidents.py:34,40-41`, `calc.py:329`
- §3.9 — insert — ambiguity — the coverage call takes no body fields and re-derives `osha_recordable` — `incidents.py:105-125`
- §3.9 — revise — **mismatch** — the compliance-decision `note` is required but not stored (PRD said `FLAG` "stores the reviewer's note") — `placements.py:282,300-305`
- §3.9 — insert — ambiguity — lifecycle outside `PROPOSED`/`ACTIVE` -> `ERR_PLACEMENT_NOT_ACTIVE`; a decision whose from-state fails -> `ERR_INVALID_REQUEST` — `placements.py:284-309`
- §3.10 — insert — ambiguity — `credit_eligible` is not a gate at award time — `placements.py:364-370`
- §3.10 — insert — ambiguity — credit preview reports `mean_competency_score` null / `competency_based_credits` 0.00 with no scored closed cycle — `calc.py:218-233`
- §3.10 — insert — ambiguity — recording against a non-`COMPLETED` placement -> `ERR_PLACEMENT_NOT_COMPLETED`; `counts_positive` starts false — `outcomes.py:40-41,60`
- §3.10 — insert — ambiguity — non-documentary `verification_source` refused with `ERR_OUTCOME_INVALID_STATE`; `from_date`/`to_date` mandatory and inverted range -> `ERR_INVALID_REQUEST` — `outcomes.py:73-75,98-101`

Pipeline complete: Step 9 wrote `workspace/PRD_COMPLETED.md`.
