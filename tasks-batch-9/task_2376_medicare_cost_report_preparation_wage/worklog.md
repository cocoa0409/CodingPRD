# Worklog — task_2376_medicare_cost_report_preparation_wage

## Step 1: Create task directory — 2026-09-02T04:58:50.584Z

Created `tasks/task_2376_medicare_cost_report_preparation_wage/` and `tasks/task_2376_medicare_cost_report_preparation_wage/workspace/`. Directory name was pre-allocated by the invoker (no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T06:51:16.835Z

All three scaffold artifacts for **task_2376_medicare_cost_report_preparation_wage** are complete and lint-clean.

Verdict block (verbatim, from `python3 skills/prd-bench-scaffold-generator/scaffold_lint.py tasks/task_2376_medicare_cost_report_preparation_wage/`):

```
Coverage
  §1.5 endpoints declared:    64
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     73
  Calls scanned (§1.8+§1.9):  1102

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (all absolute):
- `/home/ubuntu/github/CodingPRD/tasks/task_2376_medicare_cost_report_preparation_wage/SCAFFOLD.yaml` (2727 lines; no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1550 lines; single top-level key)
- `.../SCAFFOLD_CORNER_DESIGN.yaml` (4959 lines; single top-level key)

Scaffold shape (§1.0–§1.7): 15 entities (Provider, CostReport, CostCenter, TrialBalanceLine, WorkpaperEntry, StepdownRun, WageIndexSubmission, OccMixResponse, Resident, RotationAssignment, UccDataSet, Settlement, AuditAdjustment, AppealCase, InterimRateRequest), 64 endpoints, 8 calculations, 7 state machines, 2 §1.2.1 OCC rules, a 14-priority validation ladder, 56-entry error catalog, 5 roles with `role_model: segregation_of_duties`, `consistency_model: immediate`, layers = dual_variant_calculation / cascading_side_effects / optimistic_concurrency / rate_threshold_triggers / derived_field_reconciliation.

§1.8 depth probe: 9 rule_ids × 2 instances = 18 — `dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`.

§1.9 breadth probe: all nine claim-extraction-guide sections, 73 executable instances + 33 `excluded_because` stubs (106 total) — entities 11, state_machines 6+6, calculations 6+7, validations 9+6, endpoints 6+3, errors 18+6, rbac 9, cross-cutting complexity layers 6+5, consistency model 2.

Coverage audits run beyond the linter: every one of the 56 error codes is triggered by a real instance or stubbed to a named §1.8 instance; all 64 endpoints now appear as an actual `call:` (added a collection-listing sweep instance and two audit-adjustment reads to close the last gaps); no duplicate instance names across the two design files; every stub cites an existing §1.8 instance and carries no `test_recipe`. A strict re-run with the linter's negative-name skip disabled leaves only 8 findings, all intentional negative triggers (missing-`code` 400, client-supplied system fields, analyst-on-`POST /providers` 403, manager-on-cost-centers 403, analyst-on-file 403, clerk-on-report-read 403, missing-auth 401).

Self-consistency fixes made to `SCAFFOLD.yaml` this pass:
- Fixed 6 setup chains that created cost reports as `ReimbursementAnalyst` (§1.5 allows only SystemAdmin/ReimbursementManager).
- Corrected a `dsh_eligible == false` assertion to `true` (threshold comparison is `>=`, and the fixture lands exactly on 0.1500).
- Made the `StepdownRun QUEUED -> FAILED` transition reachable: `ERR_STEPDOWN_ORDER_CONFLICT` now applies to `POST /cost-reports/{id}/cost-centers` only (removed from `PATCH /cost-centers/{id}`), with a normative note that renumbering necessarily passes through a transient duplicate which surfaces as a `FAILED` run with `failure_reason: DUPLICATE_STEPDOWN_ORDER` (HTTP 201). Previously that transition and its failure_reason were unreachable through the API.

## Step 3: Copy shared files — 2026-09-02T06:51:38.797Z

Copied `./INSTRUCTION.md` → `tasks/task_2376_medicare_cost_report_preparation_wage/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T07:05:47.564Z

PRD generated and all three Hard Contracts pass.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2376_medicare_cost_report_preparation_wage/workspace/PRD.md` — 458 lines, 12,775 words, 95.8 KB. Ends at §5; no audit footer.

**Sections written**

- §1 Introduction — 3 paragraphs (dual-lifecycle framing; two stated design commitments).
- §2 Global Specifications — 10 domain-derived subsections: 2.1 Role-Based Access Control, 2.2 API Response Structure (pasted byte-identically from `section-2.2-response-structure.md`, verified), 2.3 Pagination and List Filtering, 2.4 Common Resource Properties and the Version Counter, 2.5 The Logical Clock and Calendar Arithmetic, 2.6 The Two State Dimensions of a Cost Report, 2.7 Allocation Freshness and the Recompute Cascades, 2.8 Optimistic Concurrency, 2.9 Cents/Fractions/Rounding Discipline, 2.10 Path Resolution and the Validation Precedence Ladder (all 14 priority bands).
- §3 Business Logic — 9 subsections organized as a business-process timeline: 3.1 Opening a report / filing calendar, 3.2 Worksheet A cost centers and statistical bases, 3.3 Trial balance ledger and workpaper adjustments, 3.4 Overhead stepdown (single vs. double apportionment), 3.5 Wage index collection and desk review, 3.6 GME residents/rotations/FTE, 3.7 DSH and uncompensated care, 3.8 Settlement stages and audit adjustment cycle, 3.9 Reopening, review board, and interim rate reset.
- §4 Endpoint Definitions — 4-column table, 64 rows.
- §5 Error Code Catalogue — 2-column table, 56 rows.

**Coverage audits**

Field coverage check:
- `entities[].fields`: 133 required, 133 present, 0 missing
- `endpoints[].request_body`: 73 required, 73 present, 0 missing
- `endpoints[].query_params`: 23 required, 23 present, 0 missing
- Status: **PASS**

Rule coverage check:
- `validations[]` with priority: 44 checked, 44 expressed in prose, 0 missing (the placeholder `ERR_<ENTITY>_NOT_FOUND` is expanded into the enumerated 15 per-entity 404 codes in §2.10)
- `concurrency_rules[]` OCC rejections: 2 checked, 2 expressed (write endpoint + `expected_cost_report_version` / `expected_provider_version` + `ERR_STALE_COST_REPORT_VERSION` / `ERR_STALE_PROVIDER_VERSION` all named), 0 missing
- `state_machines[].transitions`: 32 checked (7 machines), 32 fully expressed, 0 missing
- `calculations[]`: 8 checked, 8 fully expressed including all 4 dual variants, 0 missing
- `validations[]` conditions: 56 error IDs checked, all 56 matchable to prose in §1–§4 (not only the §5 table), 0 missing
- `endpoints[].side_effects` / `applies_to`: 61 side-effect items across 25 endpoints checked, all expressed, 0 missing
- `entities[].fields[]` structured content: 15 entities checked (`legs`, `statistics`, `allocation_lines`, all enum domains, defaults, precisions, computed formulas), reconstructible from prose, 0 missing
- sibling-branch symmetry: 12 groups checked, 12 with equal prose density, 0 asymmetric
- Status: **PASS**

Path purity check (§3 only):
- backtick tokens scanned: 857
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- Status: **PASS**

**Mechanical fidelity checks on §4/§5** (scripted against SCAFFOLD.yaml): 64/64 method+path pairs match exactly with zero extras/omissions; every row's authorized-role set matches the scaffold exactly; 56/56 error IDs match with correct HTTP statuses. §4 rows all exactly 4 columns, §5 rows all exactly 2.

**Style guards:** zero fuzzy/approximating words (`approximately`, `roughly`, `conservatively`, `about`, `around`, `~`), zero symbolic operators or arrow chains (state cycles written as prose), zero OCC race/simultaneity framing.

Constraints honoured: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced; no sibling task directory was read.

## Step 6: Generate implementation — 2026-09-02T07:58:31.617Z

Implementation complete and verified.

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_2376_medicare_cost_report_preparation_wage/workspace/implementation/` (3,090 lines of Python):

- `start.sh` (executable; `exec python3 app.py`, guarded `pip install` only when Flask is missing), `requirements.txt` (`Flask==3.0.3`)
- `app.py` — app factory, blueprint registration, `Decimal`-aware JSON provider with insertion-order keys, `ApiError`/`HTTPException`/`Exception` handlers mapping to the error envelope (404 `ERR_NOT_FOUND`, 405 `ERR_METHOD_NOT_ALLOWED`, 400 `ERR_INVALID_REQUEST`, 500 `ERR_INTERNAL`); binds `0.0.0.0:$PORT` (default 10000), `threaded=False`, no reloader
- Infrastructure: `db.py` (15 in-memory dicts + logical clock, `new_row`/`touch`/`apply_changes` version discipline, traversal helpers), `errors.py` (57 error ids), `response.py` (meta envelope, `req_` + 20 uppercase alnum ids, 3-digit-ms UTC timestamps), `arith.py` (`Fraction` exact arithmetic, ROUND_HALF_UP, floor helpers), `validators.py` (schema/query parsing), `common.py` (`endpoint(roles)` RBAC decorator, scope check, editability gate, pagination)
- `services/calc.py` — all derived figures: trial-balance rollup, waterfall stepdown (SINGLE vs DOUBLE apportionment), allocation freshness/staleness cascades, cost-to-charge, occupational-mix-adjusted AHW with drift correction, GME FTE weighting, UCC compilation, settlement computation, interim-rate projection
- `routes/` — `misc.py` (clock), `providers.py`, `cost_reports.py`, `accounting.py`, `wage.py`, `settlement.py`

## Endpoints
All 65 SCAFFOLD endpoints across 15 entities. A route-coverage script comparing normalized SCAFFOLD `(method, path)` pairs against `app.url_map` reported `missing: []` / `extra: []`.

## Self-verification
- **169/169 lifecycle smoke assertions pass**, both in-process via `test_client()` and over real HTTP against a fresh `bash start.sh` boot — covering the full provider → cost report → cost centers → trial balance → workpapers → stepdown → wage submission/occ-mix review cycle → GME → UCC → filing → tentative/final settlement → audit adjustment incorporation → appeal → reopening → amended filing → interim rate request path, plus RBAC, 401/403/404/409/412/422 and pagination edges.
- **45/45 additional invariant checks pass**: fresh boot returns empty collections on every list endpoint (no seeding), clock defaults to `2026-08-01T00:00:00.000Z`, meta/envelope shapes, 405 handling, entity defaults, leap-safe `filing_deadline`, `NOT_RUN` never becoming `STALE`, single-vs-double pass counts, run demotion with `SUPERSEDED_BY_NEWER_RUN`, the PATCH-only transient `stepdown_order` collision producing a `FAILED` run at HTTP 201 that bumps `version` but leaves `allocation_status` untouched, `has_more` boundaries, and validation-band precedence (401 → 403 → 400 → 404).
- `pyflakes` exit 0, `compileall` clean, `__pycache__` removed.
- Grepped clean for `sqlite3`/`json.dump`/`pickle`/`shelve` — storage is in-memory dicts only, with no startup seeding and no disk or `/tmp` persistence.

One PRD subtlety worth flagging for the test author: cost-center creation reports every shape violation (missing basis, missing order, duplicate order, either field on a non-GS center) as `ERR_STEPDOWN_ORDER_CONFLICT` (422), while the same shape violations on PATCH are `ERR_INVALID_REQUEST` (400), and PATCH deliberately never raises `ERR_STEPDOWN_ORDER_CONFLICT` — that asymmetry is implemented as written in PRD §3.2.

## Step 5: Generate unit tests — 2026-09-02T08:27:29.607Z

Generation is complete. Both design queues are fully translated and both audits pass.

## Files written

**Infrastructure — `/home/ubuntu/github/CodingPRD/tasks/task_2376_medicare_cost_report_preparation_wage/test_helpers/`** (9 files): `__init__.py`, `api_client.py` (66 endpoint methods), `api_errors.py` (`ApiErrorId` + status map), `assertions.py`, `constants.py`, `factories.py`, `fixtures.py` (759 lines of scenario builders), `test_users.py`, `types.py`.

**Test cases — `.../test_suite/`** (19 test modules + `conftest.py`), 109 tests:

| queue | module | tests |
|---|---|---|
| A (difficulty) | `test_cost_calculations.py` 6, `test_stepdown_apportionment.py` 6, `test_wage_index_average_hourly_wage.py` 4, `test_rotation_fte_capacity.py` 2, `test_dsh_uncompensated_care.py` 2, `test_interim_rate_projection.py` 4, `test_recompute_cascades.py` 4, `test_conservation_invariants.py` 4, `test_validation_precedence.py` 4 | 36 |
| B (corner) | `test_entity_shapes.py` 11, `test_state_transitions.py` 6, `test_cost_report_state_dimensions.py` 2, `test_cross_entity_state_gates.py` 4, `test_validation_rules.py` 9, `test_endpoint_contracts.py` 6, `test_error_catalogue.py` 18, `test_role_authorization.py` 9, `test_concurrency_and_cascades.py` 6, `test_immediate_consistency.py` 2 | 73 |

The last two modules were finished this session: `test_concurrency_and_cascades.py` (both halves of each version token, the FAILED-run audit record, the variance gate at exactly 0.1000, the UCC reconciliation when the ratio first appears) and `test_immediate_consistency.py` (mapping rollup visible to the immediate reads; the filing body agreeing with the report read and the recomputed GME summary).

## Coverage vs the design indices

- Difficulty (queue A): 18 non-stub instances, all 18 translated, every one with ≥2 tests (36 total).
- Corner (queue B): 73 non-stub instances, all 73 translated, exactly one test each. The 33 `excluded_because:` stubs (including the 5 cross-cutting ones) were deliberately not translated.
- **Zero instances skipped** — every non-stub instance passed the PRD-first two-condition filter. No `skip`/`skipif`/`xfail` anywhere in the suite.

## Audit results

- `pytest --collect-only`: **109 tests collected**, 0 collection errors.
- PRD-citation audit (every `PRD x.y: "..."` docstring line must be a verbatim substring of `workspace/PRD.md`): **0 failures**.
- Design-tag audit: 0 untagged, 0 dual-tagged, 0 dangling, 0 stub-tagged; every tag's `Design:` line is the last line of its docstring; 73/73 corner and 18/18 difficulty tags resolve to real non-stub instances.
- `pyflakes test_suite/*.py`: clean.

## Two design-vs-PRD contradictions resolved in favour of the PRD

1. `interim_rate_variance_exactly_at_the_threshold_is_accepted` asserted `Provider.version == provider_version_1`; PRD §3.9 says "Creating a request increments the provider's `version`." → asserted `observed + 1`.
2. `stale_expected_provider_version_is_rejected` asserted `observed + 1`; creation (+1) then `APPROVE` (+1) → asserted `observed + 2`. I also moved the second request's period to 2027-01-01..2027-06-30 so it genuinely overlaps the approved period, making the "not `ERR_INTERIM_PERIOD_OVERLAP`, not `ERR_INTERIM_VARIANCE_BELOW_THRESHOLD`" assertions load-bearing on the §2.10 band-8-precedes-12/14 ordering.

Also, in the rbac walk-the-surface test the design's terminal `recompute_required == false` contradicts §3.7 (the final trigger reverses a workpaper entry, staling the allocation); the test asserts `False` on the recompute response and `True` after the reversal, preserving the instance's claim while asserting only PRD-derived outcomes.

Nothing under `workspace/implementation/` was read or written, and no sibling task directory was touched.

## Step 7: Run tests and iterate — 2026-09-02T11:05:00.000Z

Clean on the first iteration — no fixes were needed.

**Iterations run:** 1

**Sweep result:** 8/8 parallel rounds green — every round reported `passed == total == 109`, with `failed 0`, `errors 0`, `skipped 0`. Per-round wall time 1266–1320 s under `--isolation per-test-server` with all 8 rounds concurrent (host load average ~49 during the sweep, so this is contention-bound, not implementation-bound). No round showed a single flaky test: the 109 passing test names are identical across all 8 result files, so no union-of-failures set exists.

**Tests deleted:** none. No test failed in any round, so no test entered the STEP 1 coverage / unique-derivability audit.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

**Incidental verification performed while diagnosing:**
- Confirmed no `pytest.mark.skip` / `xfail` markers exist anywhere in `test_suite/` — the only `grep` hits for "skip" are PRD quotations inside docstrings (`test_validation_precedence.py:137` quoting the §3.1 "amended filing … skips the deadline test" sentence, and `test_validation_rules.py:172` quoting the §3.3 adjustment net-zero exemption). So the green sweep is not the product of suppressed tests.
- Confirmed the implementation holds no persistent or seeded state: no `sqlite`, no `json.dump`, no `open(` calls anywhere in `workspace/implementation/**.py`. Storage is in-memory only and every entity is constructed by the tests through declared endpoints, as the benchmark contract requires.
- The `Killed` lines in the sweep log are the expected per-test `start.sh` server teardowns under `--isolation per-test-server`, not OOM or a reaped sweep (memory stayed at ~100 GB available, and rounds finished at staggered wall-clock times rather than dying together).

**Orchestrator note (artifact restoration):** the Step 7 subagent deleted the eight `results.*.json` files and `sweep.log` on exit as "cleanup". The skill's output spec lists `results.{1..8}.json` from the final passing sweep as a deliverable, so the orchestrator re-launched the identical 8-round setsid sweep to regenerate those artifacts, concurrently with Step 9 (Step 9 only reads `implementation/`, so the two do not interfere).

## Step 8: Finalize PRD — SKIPPED — 2026-09-02T11:05:30.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already uniquely determined every behavior the implementation exhibits at every site the test suite exercised, so there is no Step 7 diff to patch and no `PRD_FINALIZED.md` is produced. Step 9 therefore starts from `PRD.md`.

## Step 9: Complete PRD — 2026-09-02T13:25:00.000Z

`workspace/PRD_COMPLETED.md` is written and complete.

**Source vs deliverable** (`PRD_FINALIZED.md` does not exist — Step 8 skipped — so `workspace/PRD.md` was the source):

| | lines | chars |
|---|---|---|
| `workspace/PRD.md` | 458 | 95,614 |
| `workspace/PRD_COMPLETED.md` | 458 | 105,672 |

Char delta **+10,058** (+10.5%). Line count unchanged — every change is an in-paragraph insert or revision; no new sections, no new paragraphs. 40 paragraphs touched across 76 discrete fragments.

**Counts: 58 ambiguity-pins, 2 mismatch-revisions.**

### Mismatch-revisions

- §3.4 — revise — mismatch — the two stepdown structural preconditions were stated in the wrong order; `ERR_UNMAPPED_TRIAL_BALANCE` is now stated to be tested *before* `ERR_STEPDOWN_STRUCTURE_INCOMPLETE` — `routes/accounting.py:408-417`
- §3.8 — revise — mismatch — `SUPERSEDED` was listed as a live settlement status excluded from `prior_tentative_paid_cents`; it is now declared a modelled value no operation ever assigns, so a second issuance never supersedes an earlier settlement — `routes/settlement.py:125-210`, `services/calc.py:480-505`

### Ambiguity-pins

§2.1 / §2.2 (auth, identity)
- §2.1 — insert — ambiguity — an empty or whitespace-only `X-User-ID` counts as absent for provider-scope purposes — `common.py:55-60`
- §2.1 — insert — ambiguity — scope comparison is wired into every owning-provider write plus exactly two reads (`GET /providers/{id}`, `GET /cost-reports/{id}`); all other reads/lists skip it, including the GME summary — `common.py:84-89`, `routes/cost_reports.py:80-85,147`
- §2.1 — insert — ambiguity — a `MacAuditor` omitting `X-User-ID` on propose/resolve is `ERR_INVALID_REQUEST` (400) in the schema band, before path resolution — `routes/settlement.py:214-247,307`

§2.3 / §2.4 (envelope, identity fields)
- §2.3 — insert — ambiguity — rows sharing a `created_at` are ordered by insertion sequence — `db.py:89`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` come from wall-clock time, not the logical clock — `db.py:59-75`
- §2.4 — insert — ambiguity — three `version` refinements: created rows always return at 1 with `updated_at == created_at` even when creation ran a derived computation; a derived recompute bumps only when a stored value actually changes; the §3 workflow-step increments on `CostReport`/`Provider`/`Settlement` fire unconditionally — `db.py:59-88`, `routes/providers.py:125-197`

§2.5 (clock)
- §2.5 — insert — ambiguity — both clock endpoints return HTTP 200 with `data.current_utc` in three-fractional-digit UTC form; missing/unparseable is `ERR_INVALID_REQUEST`; a zoneless instant reads as UTC — `routes/misc.py:1-24`, `validators.py:163-175`

§2.7 (cascades)
- §2.7 — insert — ambiguity — `allocation_status` `NOT_RUN` is never demoted; the flip to `STALE` only ever leaves `CURRENT`, and every such flip sets `recompute_required` on the report's UCC data set — `services/calc.py:119-126`

§2.9 (rounding)
- §2.9 — insert — ambiguity — "half up" on negatives means half away from zero (−0.5 → −1); "floored" means toward negative infinity — `arith.py:22-51`

§2.10 (validation ladder)
- §2.10 — insert — ambiguity — loading an already-mapped trial balance line is a state-band failure — `routes/accounting.py:197-259`
- §2.10 — insert — ambiguity — on interim rate request creation both `provider_id` and `basis_cost_report_id` resolve in the body-FK band — `routes/settlement.py:513-519`
- §2.10 — insert — ambiguity — unmatched path → 404 `ERR_NOT_FOUND`; unaccepted method → 405 `ERR_METHOD_NOT_ALLOWED` — `app.py:45-55`

§3.1 (cost reports)
- §3.1 — insert — ambiguity — the four filing readiness conditions are tested in the order listed, after the `status` reachability test and after the deadline test where it applies — `routes/cost_reports.py:112-131`

§3.2 (cost centers)
- §3.2 — insert — ambiguity — `stepdown_order` below 1 is `ERR_INVALID_REQUEST`, not a conflict; non-`GENERAL_SERVICE` centers store `allocation_basis` `"NONE"` and `stepdown_order` null; the shape tests precede the `statistics` key check and the duplicate-code test — `routes/accounting.py:62-138`
- §3.2 — insert — ambiguity — a non-numeric or negative statistic value is `ERR_INVALID_REQUEST`; an unrecognized `statistics` key is `ERR_INVALID_REQUEST` on revision; a supplied `statistics` object replaces the stored one wholesale — `routes/accounting.py:100-120,150-195`
- §3.2 — insert — ambiguity — the two revision shape tests read the stored `center_type`, so they run after path resolution (404 wins) but before scope and editability — `routes/accounting.py:150-175`
- §3.2 — insert — ambiguity — a revision bumps the report's `version` and the center's own `version` unconditionally, even with `allocation_status` `NOT_RUN` and an empty body — `routes/accounting.py:176-195`
- §3.2 — insert — ambiguity — creating a center while a `COMPLETED` run exists does not demote that run (`stale_reason` stays null), and bumps the report only because the freshness flag moved — `services/calc.py:143-150`

§3.3 (trial balance, workpapers)
- §3.3 — insert — ambiguity — mapping a line while a `COMPLETED` run exists leaves that run `COMPLETED` with `stale_reason` null; load and map each bump the report's `version` unconditionally — `routes/accounting.py:240-286`, `services/calc.py:143-150`
- §3.3 — insert — ambiguity — a leg naming an unresolvable cost center is `ERR_REFERENCED_ENTITY_NOT_FOUND`; a zero leg amount and an empty `legs` array are both `ERR_INVALID_REQUEST`, not business failures — `routes/accounting.py:288-350`
- §3.3 — insert — ambiguity — a leg count other than one on a non-reclass entry is also `ERR_RECLASS_NOT_BALANCED` — `routes/accounting.py:320-340`
- §3.3 — insert — ambiguity — the non-allowable test is evaluated after the leg-shape tests — `routes/accounting.py:340-350`

§3.4 (stepdown)
- §3.4 — insert — ambiguity — a `FAILED` run's exact returned shape: empty `allocation_lines`, `total_allocated_cents` and `residual_unallocated_cents` both 0, `completed_at` and `stale_reason` null, and no prior `COMPLETED` run demoted — `routes/accounting.py:418-450`, `services/calc.py:200-245`
- §3.4 — insert — ambiguity — full `allocation_lines` ordering: allocators by ascending `stepdown_order`, pass one before pass two, receivers in receiver-set build order, with the three build orders spelled out for SINGLE and both DOUBLE passes — `services/calc.py:160-245`

§3.5 (wage index / occ mix)
- §3.5 — insert — ambiguity — a freshly opened submission's derived fields all read zero/null until the first recompute — `routes/wage.py:58-78`
- §3.5 — insert — ambiguity — correction is allowed only in `DRAFT`/`CHANGE_REQUESTED`, that state test running after the report's editability gate — `routes/wage.py:118-124`
- §3.5 — insert — ambiguity — a correction advances the submission's `version` by exactly one however many figures moved, and never touches the report's `version` or status axes — `routes/wage.py:29-31,135-141`
- §3.5 — insert — ambiguity — occ-mix responses only in `DRAFT`/`CHANGE_REQUESTED`, that state test preceding duplicate-category which precedes the hours ceiling; recording a response may bump the submission but never the report — `routes/wage.py:244-271`
- §3.5 — insert — ambiguity — `category_ahw_cents` is 0 when the computed quotient is exactly 0 — `routes/wage.py:258-260`
- §3.5 — insert — ambiguity — a `DRAFT` submission with no responses is `ERR_INVALID_STATE_TRANSITION`, evaluated before the hours ceiling — `routes/wage.py:154-160`
- §3.5 — insert — ambiguity — re-opening desk review on a `CLOSED` report yields `ERR_INVALID_STATE_TRANSITION` — `routes/wage.py:182-183`
- §3.5 — insert — ambiguity — `decision` and `review_note` are both required; all three outcomes persist `review_note`; the `ERR_OCC_MIX_INCOMPLETE` test runs first on `ACCEPT`; a `REJECT` from a non-`DRAFT` report is `ERR_INVALID_STATE_TRANSITION` — `routes/wage.py:195-229`

§3.6 (GME)
- §3.6 — insert — ambiguity — the editability gate applies to the report owning the *named cost center*, so a frozen site reports `ERR_COST_REPORT_NOT_EDITABLE` ahead of `ERR_COST_CENTER_FOREIGN_TO_PROVIDER` — `routes/providers.py:125-160`
- §3.6 — insert — ambiguity — a created rotation returns with `overlap_days` and `fte_days` already computed by the creation's own recompute (and still at `version` 1) — `routes/providers.py:170-197`
- §3.6 — insert — ambiguity — voiding zeroes `fte_days` but leaves `overlap_days` at its last computed value — `routes/providers.py:199-212`, `services/calc.py:370-372`

§3.7 (UCC)
- §3.7 — insert — ambiguity — explicit recompute carries no state gate (available in every report status including `CLOSED`) and leaves the report's `version` untouched — `routes/settlement.py:114-123`

§3.8 (settlement, audit, appeals)
- §3.8 — insert — ambiguity — `ERR_ALLOCATION_NOT_CURRENT` also answers the case where no `COMPLETED` stepdown run can be located, and the reachability tests precede the allocation test — `routes/settlement.py:125-160`
- §3.8 — insert — ambiguity — an existing `TENTATIVE`/`ISSUED` settlement makes a second tentative issuance `ERR_INVALID_STATE_TRANSITION` — `routes/settlement.py:140-155`
- §3.8 — insert — ambiguity — the three final-settlement tests run in the stated order, with the missing-tentative case raised as `ERR_INVALID_STATE_TRANSITION` alongside the reachability tests — `routes/settlement.py:155-170`
- §3.8 — revise — ambiguity — the unresolved-adjustment scan covers adjustments of *any* `TENTATIVE` settlement of the report whatever that settlement's own status — `routes/settlement.py:160-170`
- §3.8 — insert — ambiguity — the parent settlement must be `ISSUED` or `APPEALED` (`ERR_INVALID_STATE_TRANSITION`), tested before the cost-center ownership check; a zero `proposed_amount_cents` is `ERR_INVALID_REQUEST` — `routes/settlement.py:214-247`
- §3.8 — insert — ambiguity — `response` and `provider_response_note` are both required; the adjustment's own `PROPOSED` state is tested first, then the settlement status, both as `ERR_INVALID_STATE_TRANSITION`; the `ACCEPT`-only report-status requirement raises the same code — `routes/settlement.py:275-302`
- §3.8 — insert — ambiguity — on resolve, `resolution_note` is validated as a string but persisted nowhere; the segregation-of-duties check precedes the adjustment's own state test — `routes/settlement.py:305-340`
- §3.8 — insert — ambiguity — the synthesized `ADJUSTMENT` workpaper entry's full field shape: `code` from the adjustment, `description` from its `rationale`, `is_non_allowable` false, `status` `ACTIVE`, `reversed_at` null — `routes/settlement.py:340-365`
- §3.9/§3.8 — insert — ambiguity — nothing about the report's own `status` is tested when an appeal case is opened; the 180-day window test runs *before* the two settlement tests, and the duplicate-open-case test is checked last — `routes/settlement.py:367-415`
- §3.8 — insert — ambiguity — `outcome` and `decision_note` are both required, and an outcome outside the caller's role repertoire is `ERR_FORBIDDEN_ROLE` (403) before `kind` or `status` is consulted — `routes/settlement.py:435-470`
- §3.8 — insert — ambiguity — `HEAR` against a settlement in any status other than `APPEALED` is `ERR_INVALID_STATE_TRANSITION` — `routes/settlement.py:470-472`

§3.9 (interim rate)
- §3.9 — insert — ambiguity — `decision` and `decision_note` are both required on the decide endpoint — `routes/settlement.py:588-591`

### Cross-checks performed
- Route inventory diffed mechanically: implementation exposes exactly the 64 routes in the PRD endpoint table, method-for-method and path-for-path, with no extras on either side.
- Every list-filter set in `routes/*.py` matches the filter enumeration in §2.3 exactly (providers, cost reports, cost centers, TB lines, workpapers, stepdown runs, submissions, occ-mix, residents, rotations, settlements, adjustments, appeals, interim requests).
- The odd-looking reuse of `ERR_FISCAL_PERIOD_INVALID` for a duplicate provider CCN is genuine implementation behavior (`routes/providers.py:39-41`) and was already pinned.
- No file under `workspace/implementation/` was modified, and no test run was launched; the concurrent sweep was left untouched.

## Step 7 artifact-restoration sweep — verification — 2026-09-02T13:25:30.000Z

The orchestrator's re-launched 8-round setsid sweep completed and independently reproduced the Step 7 result: all eight `workspace/implementation/results.{1..8}.json` report `passed 109 / total 109 / failed 0 / errors 0 / skipped 0`. The deliverable results artifacts are now present, and Step 7's green verdict is confirmed by two independent full sweeps.
