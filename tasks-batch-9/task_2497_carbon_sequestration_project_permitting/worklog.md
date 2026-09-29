# Worklog — task_2497_carbon_sequestration_project_permitting

## Step 1: Create task directory — 2026-09-03T01:26:56.365Z

Created pre-assigned task directory `/home/ubuntu/github/CodingPRD/tasks/task_2497_carbon_sequestration_project_permitting` and its `workspace/` subdirectory. Index 2497 was fixed by the scenario number; no scan of `./tasks/` was performed (concurrent pipelines on this host would collide with auto-allocation).

## Step 2: Generate Scaffold — 2026-09-03T03:26:59.491Z

All three artifacts are final and lint-clean.

## Generated files
`/home/ubuntu/github/CodingPRD/tasks/task_2497_carbon_sequestration_project_permitting/`
- `SCAFFOLD.yaml` (3453 lines, §1.0–§1.7, neither design key present)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2876 lines, single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (3274 lines, single key `scaffold_corner_design`)

## Counts
- §1.1–§1.7: **11 entities**, 10 state machines / 66 transitions, **3 OCC concurrency rules**, **14 calculations**, **51 ordered validations**, **60 endpoints**, **50 error codes**, **5 roles** (ProgramAdmin, ProjectDeveloper, RegulatoryReviewer, IndependentVerifier, Landowner).
- complexity_profile: primary `compliance_audit`, secondary `multi_party_negotiation`; layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation]`; flat topology, parallel state machines, `segregation_of_duties`, `immediate` consistency.
- §1.8: **9 rules / 22 instances** (seal-integrity dual variant, plume/AoR geometry, waterfall allocation, transitive cascades at depth four, pinned-order assurance recompute, MRV weighted scoring, negotiation rounds, PISC/closure gating).
- §1.9: **9 sections / 75 instances = 54 full `test_recipe`s + 21 `excluded_because` stubs** — entities 12/0, state_machines 14/5, calculations 14/7, validations 9/5, endpoints 6/1, errors 7/0, rbac 7/0, cross_cutting_complexity_layers 4/3, consistency_model 2/0.

## Verification
- `scaffold_lint.py`: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (60 endpoints, 11 entities, 22 + 54 instances, **850 calls scanned**).
- All 21 stub citations resolve to real `rule_id / instance_name` pairs in the difficulty file; no instance carries both `test_recipe` and `excluded_because`; no duplicate instance names.
- Forbidden concurrency vocabulary: 0 hits across all three files. Variable resolution across all 54 recipes: 0 use-before-define or undefined-assert issues. Every one of the 50 error codes has a triggering path in §1.8 or §1.9.
- `claim_type` labels were aligned to the claim-extraction-guide row labels in this pass (dropped the `_algorithm` suffixes, `invalid_transitions`, `cross_entity`, rbac `exclusive_operations`/`shared_operations`/`peer_roles`), and the one cross-cutting instance for `resource_temporal_overlap` was removed because that layer is not declared in `complexity_profile.complexity_layers` — hence 75 rather than 76 instances.
- Hard constraint respected: no sibling `task_*/` directory or file under `tasks/` was listed, globbed, grepped, or read at any point.

## Step 3: Copy Shared Files — 2026-09-03T03:27:13.149Z

Copied `./INSTRUCTION.md` to `tasks/task_2497_carbon_sequestration_project_permitting/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T03:41:00.000Z

PRD generation complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2497_carbon_sequestration_project_permitting/workspace/PRD.md` — 439 lines. Terminates at a complete section boundary (final row of the §5 error table, `ERR_ALLOCATION_EXCEEDS_FACE_AMOUNT | 422`); no audit footer.

**Withheld files honored:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never read, grepped, or referenced.

**Sections covered**
- §1 Introduction (3 paragraphs)
- §2 Global behaviours, 10 domain-derived subsections: 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim, byte-identical match confirmed) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and the Version Counter · 2.5 Stale-Version Guards on Parent Records · 2.6 Validation Precedence (14-tier ladder over all 51 validations) · 2.7 Numeric Precision and Rounding · 2.8 Parallel State Dimensions and Cascade Propagation · 2.9 The Operational Posture Gate · 2.10 Sub-Resource Listing and Filters
- §3 Business logic, 9 workflow subsections: 3.1 project opening/statutory parameters · 3.2 geologic models, seal integrity, plume · 3.3 model review, supersession, AOR delineation · 3.4 legacy wellbores and corrective action · 3.5 pore space leasing, unitization, settlement · 3.6 well permitting, construction, MIT · 3.7 MRV plan design and two-track review · 3.8 financial assurance, waterfall, injection authorization, emergency draws · 3.9 injection reporting, tax credits, PISC, closure
- §4 Endpoint Definitions — 60-row table (Method | Path | Description | Authorized Role(s)); all 60 scaffold (method, path) pairs matched exactly, 0 missing, 0 extra
- §5 Error Code Catalogue — 50-row table, all 50 error IDs present

**Coverage audit**

```
Field coverage check:
- entities[].fields: 150 required, 150 present, 0 missing
- endpoints[].request_body: 100 required, 100 present, 0 missing
- endpoints[].query_params: 12 required, 12 present, 0 missing
- endpoints[].path_params: all present, 0 missing
Status: PASS
```
Also verified: all 50 `errors[].id`, all 5 role names, all entity enum constraint values, and all 54 state-machine states (`initial_state`, `terminal_states`, every transition `from`/`to`) appear as backticked tokens.

```
Rule coverage check:
- validations[] with priority: 51 checked, 51 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 11 machines / all transitions checked, fully expressed, 0 missing
- calculations[]: 14 checked, 14 fully expressed, 0 missing
- validations[] conditions: 51 checked, 51 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all checked, all expressed, 0 missing
- entities[].fields[] structured content: 150 checked, reconstructible from prose, 0 missing
- sibling-branch symmetry: 3 groups checked (APPROVED vs APPROVED_WITH_CONDITIONS; DETERMINISTIC vs PROBABILISTIC_P10; REPORTED vs VERIFIED), 3 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1162
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Repairs made during audit**
1. `permit_id` (FK on `InjectionPeriodRecord`) was initially absent — the period is reported through the permit's path, so the field had no natural narrative home. Added a sentence in §3.9 naming it explicitly.
2. Three multi-scope validations named their error only at their primary site. Names now appear at every `applies_to` scope: the nine-precondition authorize-injection paragraph in §3.8 now names `ERR_INVALID_PROJECT_STATE`, `ERR_SEAL_INTEGRITY_FAIL`, `ERR_AOR_NOT_DELINEATED`, `ERR_MRV_PLAN_NOT_APPROVED`, `ERR_CORRECTIVE_ACTION_INCOMPLETE`, `ERR_PORE_SPACE_CONSENT_INSUFFICIENT` and `ERR_ASSURANCE_INSUFFICIENT` inline plus the full refusal-precedence chain, and §3.9 now states that reporting against a permit not at `ACTIVE` yields `ERR_INVALID_PERMIT_STATE`.

**Note for downstream steps:** `InjectionPeriodRecord` has `common_fields: false` — it carries only `id` and `created_at` (no `updated_at`, no `version`). §2.4 and §3.9 both call this out, since it is the one entity whose mutations leave their version trail on the parent project instead.

**Orchestrator verification:** independently confirmed PRD.md is 439 lines, ends at the last row of the §5 error table (not mid-sentence), and contains all expected §1–§5 headings. Not truncated.

## Step 5: Generate Unit Tests — 2026-09-03T04:43:03.770Z

Generation and audit are complete.

## Files written

Stage 1 infrastructure — `/home/ubuntu/github/CodingPRD/tasks/task_2497_carbon_sequestration_project_permitting/test_helpers/` (9 files: `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`).

Stage 2 tests — `/home/ubuntu/github/CodingPRD/tasks/task_2497_carbon_sequestration_project_permitting/test_suite/`: `conftest.py` plus 17 numbered files, **98 tests**.

Queue A (44 tests, `Design: Difficulty/...`):

| file | tests | rule_id |
|---|---|---|
| test_01_dual_variant_assessment.py | 4 | dual_variant_calc |
| test_02_formula_composition.py | 6 | combinatorial_formula |
| test_03_lifecycle_branching.py | 6 | non_linear_state_machine |
| test_04_cascade_propagation.py | 4 | transitive_cascade |
| test_05_validation_priority.py | 6 | priority_pair_validation_conflict |
| test_06_boundary_precision.py | 6 | boundary_precision_check |
| test_07_cross_entity_preconditions.py | 4 | cross_entity_state_dependency |
| test_08_timeline_overlap.py | 4 | resource_temporal_overlap |
| test_09_compensating_reversal.py | 4 | compensating_invariant |

Queue B (54 tests, `Design: Corner/...`): `test_20_entity_records_and_reads.py` 12 (entities), `test_21_state_transitions.py` 9 (state_machines), `test_22_computation_rules.py` 7 (calculations), `test_23_validation_rules.py` 4 (validations), `test_24_endpoint_surface.py` 5 (endpoints), `test_25_error_catalogue.py` 7 (errors), `test_26_access_control.py` 7 (rbac), `test_27_versioning_and_consistency.py` 3 (cross_cutting_complexity_layers 1 + consistency_model 2).

## Instances translated vs skipped

- **22/22** difficulty instances translated, every one with >=2 tests (0 short).
- **54/54** non-stub corner instances translated, 1 test each.
- **0 instances skipped.** All 21 `excluded_because:` corner stubs correctly carry no test.

Assertion-level drops (instance still covered, individual claims omitted because the PRD does not uniquely derive them):
- `submitted_at` assertions dropped in `test_23`, `test_25` and `test_20` — that identifier appears nowhere in `workspace/PRD.md`.
- Four pore-space-tract null-field defaults (`current_offer_bonus_per_acre_usd`, `counter_bonus_per_acre_usd`, `executed_bonus_per_acre_usd`, `lease_term_start`) and `waiver_reviewer_user_id == null` dropped as un-derivable initial values.
- `required_financial_assurance_usd == 0` dropped from the duplicate-API-number instance per the standing adjudication; replaced with an unchanged-across-the-rejection assertion.
- The `permit_submit_with_single_string_casing_rejected` no-write witness uses `revision_round_count == 0` instead of a timestamp field.
- Server-written timestamps are asserted by their 19-char instant prefix (the PRD mandates three fractional digits); `pytest.approx(abs=0.01)` is confined to pi-derived and float-accumulated money totals.
- One instance is weaker-grounded than its peers: `Corner/rbac/independent_verifier_reads_the_project_the_landowner_can_also_read` — the read grant is otherwise carried only by the endpoint table row, so its docstring cites the two role sentences plus the single-project-read sentence.

## Audit results (all green)

17 files / 98 tests; exactly one `Design:` line per test, always the last line of the docstring; every tag resolves to a real non-stub instance; 0 dual-tagged or untagged tests; 0 `skip`/`skipif`/`xfail`; 0 occurrences of "scaffold"; 0 references to `workspace/implementation/` (never read or written — the concurrent implementation generator stayed isolated); all 98 docstrings decompose entirely into >=30-char verbatim `PRD.md` runs; 0 missing `test_helpers` symbols; 0 arity/keyword mismatches under `inspect.signature().bind()`; `pytest --collect-only` collects 98/98; `test_helpers/` mtimes all predate the Stage 2 writes.

## Step 6: Generate Implementation — 2026-09-03T04:43:03.770Z

Implementation complete and verified.

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_2497_carbon_sequestration_project_permitting/workspace/implementation/`:

- `start.sh` (executable, SKILL.md template: conditional `pip install` guarded by an import probe, then `exec python3 app.py`), `requirements.txt` (`flask==3.0.3`)
- `app.py` — factory, 10 blueprints, `strict_slashes=False`, `before_request` sets `g.touched`, handlers for `ApiError` / `HTTPException` (404/405/400) / bare `Exception`, `app.run(host=0.0.0.0, port=$PORT, threaded=True, use_reloader=False)`
- Core: `db.py` (plain dicts, `reset()` on boot, no seeding), `clock.py` (logical clock, default `2026-08-01T00:00:00Z`), `middleware.py` (auth/role gate + typed body validators), `response.py` (meta/response_type/data envelope + pagination meta), `errors.py` (all 50 error ids -> HTTP), `enums.py`
- `services/`: `calc.py` (all PRD formulas, Decimal + explicit rounding modes), `derive.py` (stored-derived-field recomputation, cascades), `lookup.py`, `serialize.py`
- `routes/`: `projects.py`, `models.py`, `wellbores.py`, `tracts.py`, `permits.py`, `plans.py`, `instruments.py`, `claims.py`, `remediation.py`, `clock_routes.py`

## Endpoints
All PRD/SCAFFOLD routes: storage projects (create/list/get, authorize-injection, begin-pisc, certify-closure, unitization-petition, unitization-ruling, nested wellbore listing); geologic models (create/get, run-plume-simulation, submit, review, finalize-aor); legacy wellbores (create/get, schedule/complete/waive corrective action); pore-space tracts (create/list/get, offers, respond, terminate-lease); injection-well permits (create/list/get, submit, review, advance-construction, record-mit, activate, injection-periods create/list, period void); monitoring plans (create/get, methods create/list, method retire, submit, review); financial instruments (create/get, allocate, deallocate); remediation orders (open, resolve); `POST /_clock/set_current_utc`.

## Notable design decisions
- **Derived fields are stored, not derived on read** (PRD §3.8: each step reads the stored output of the previous step); sole exception `pisc_elapsed_years`, recomputed on every project read.
- **One version bump per row per request** via `flask.g.touched`.
- Single 14-rank validation ladder (§2.6) applied uniformly; endpoint-local conditions evaluated in the order the PRD prose lists them where the ladder is silent (e.g. authorize-injection: status/posture -> seal -> AoR -> "some permit APPROVED" (`ERR_INVALID_PROJECT_STATE`) -> MRV plan -> CA -> pore space -> assurance).
- **`well_name` / `tract_label` "unique per project" is intentionally not enforced** — §5 defines no error id and the ladder no slot for either; only `api_number` and `tax_year` have codes (`ERR_DUPLICATE_API_NUMBER`, `ERR_DUPLICATE_TAX_YEAR_CLAIM`) and are enforced.
- Plan approval >=85 does **not** reset the project's monitoring cost — per §3.7 a conditioned sibling's 1.15 uplift persists while any plan holds `APPROVED_WITH_CONDITIONS`.
- Deallocate restores the full face amount (an ALLOCATED instrument always has `drawn_usd == 0`).
- Remediation open/resolve are the only handlers that skip the frozen-posture gate (§2.9).
- Acreage figures follow the literal formulas with no clamping (an oversubscribed project legitimately yields consent > 100 and negative `outstanding_acreage`).

## Verification
In-memory only, zero seeding; boots clean from a fresh process via `start.sh` (verified: empty list, clock at default, correct envelopes). `python3 -m compileall` clean; `__pycache__` removed. Two throwaway smoke suites in `/tmp` (`t2497_smoke.py` happy path, `t2497_smoke2.py` ~110 negative/branch checks) both pass with zero failures — including precedence ordering, rig-capacity overlap, waiver eligibility, unitization sweep of UNLEASED+REJECTED tracts, lease termination, fork-join plan review, partial allocation waterfall, MIT/construction sequencing, freeze cascade and restore, PISC + closure release. No implementation defect was found; the two failures seen during testing were both errors in my scratch scripts' setup. All dev servers killed; `test_suite/`, `test_helpers/`, and the two design YAMLs were never read.

**Orchestrator note:** verified `POST /_clock/set_current_utc` is PRD-declared (PRD.md:382 endpoint table row plus §2.4 prose), so it is not an off-contract implementation addition.

## Step 7: Run Tests and Iterate — 2026-09-03T04:55:00.000Z

Clean sweep on the first iteration. Emitting the summary.

## Summary

**Iterations run: 1** — the 8-round parallel stability sweep passed on the first attempt, so no diagnostic protocol steps were triggered.

**Sweep result (fresh artifacts, `results.1.json` ... `results.8.json`, written 04:47 after a `rm -f` at launch):**

| Round | passed | total | failed | errors | skipped |
|---|---|---|---|---|---|
| 1-8 | 98 | 98 | 0 | 0 | 0 |

Per-round duration ~173 s; 98 tests x per-test-server reboot under `--isolation per-test-server`, 8 rounds concurrent under `setsid nohup` as required. No round showed the reaping signature (no `Terminated` in server logs, no synchronized wall-clock deaths), and no test failed in any single round — so there is no flakiness signal to chase either.

**Tests deleted:** none. No test failed in any of the 8 rounds, so no STEP 1a (PRD silence) or STEP 1b (unique-derivability collapse) adjudication was reached.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `workspace/implementation/`:** none.

**Integrity checks performed on the artifact** (to confirm the green sweep is honest rather than hollowed out):
- No `pytest.mark.skip` / `xfail` anywhere in `test_suite/` or `test_helpers/` — the 98 collected tests all genuinely executed (0 skipped in every round).
- Storage is in-memory only: no SQLite, no JSON dump to disk, no `/tmp` cache in `workspace/implementation/`. The single `json.dumps` hit is HTTP response serialization in `response.py:37`, not persistence.
- `start.sh` guards its `pip install` behind an import probe, which is why 8 concurrent per-test-reboot rounds did not produce boot-contention timeouts.

**Suite shape** (for reference): 98 tests across 17 files — 9 scenario files (`test_01`-`test_09`: dual-variant seal assessment, formula composition, lifecycle branching, cascade propagation, validation priority, boundary precision, cross-entity preconditions, timeline overlap, compensating reversal) plus 8 systematic files (`test_20`-`test_27`: entity reads, state transitions, computation rules, validation rules, endpoint surface, error catalogue, access control, versioning/consistency).

**Orchestrator verification (not the subagent's claim):** independently listed and parsed all 8 `results.{1..8}.json` — all present, all written 04:47, each reporting `passed=98 failed=0 errors=0 skipped=0 total=98`. The clean sweep is real, not a phantom claim.

## Step 8: Finalize PRD — SKIPPED — 2026-09-03T04:55:00.000Z

Skip condition met per the skill: Step 7 exited on the first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. `PRD.md` therefore already determined every behavior Step 7's 98 tests exercised, there is no `<step_7_diff>` to hand off, and no finalizer subagent was spawned. `workspace/PRD_FINALIZED.md` is intentionally absent; Step 9 will take `workspace/PRD.md` as its source.

## Step 9: Complete PRD — 2026-09-03T05:20:00.000Z

**Orchestrator decision (recorded per the autonomy directive):** Step 9 was run as **three sequential, file-partitioned passes** rather than one subagent. Rationale: `implementation/` is ~4,100 lines across 24 files against a 439-line PRD; a single subagent asked to "walk implementation/ exhaustively" at that ratio reliably samples instead of scanning, and the known failure mode is a `PRD_COMPLETED.md` that comes back byte-identical to its source. The passes are strictly sequential (each edits the same file in place); `PRD_COMPLETED.md` was seeded by the orchestrator via `cp PRD.md PRD_COMPLETED.md` (no `PRD_FINALIZED.md` exists — Step 8 was skipped), and each pass was told not to re-copy or revert earlier passes.

Partition:
- **Pass 1 — global/core:** `app.py`, `middleware.py`, `response.py`, `errors.py`, `enums.py`, `db.py`, `clock.py`, `services/serialize.py`, `services/lookup.py`, `routes/clock_routes.py`, `start.sh`, `requirements.txt`
- **Pass 2 — calculations + project/money/emergency:** `services/calc.py`, `services/derive.py`, `routes/projects.py`, `routes/instruments.py`, `routes/remediation.py`
- **Pass 3 — remaining domain routes:** `routes/models.py`, `routes/wellbores.py`, `routes/tracts.py`, `routes/permits.py`, `routes/plans.py`, `routes/claims.py`

### Pass 1 (core/global) — 439 → 439 lines, 108,960 → 113,575 chars (+4,615); 10 ambiguity-pins, 2 mismatch-revisions

- **§2.1 (RBAC)** — insert — ambiguity — a header present but empty/whitespace-only counts as absent; role matched exactly and case-sensitively — `middleware.py:25-30`
- **§2.2 (success envelope)** — insert — ambiguity — every numeric `data` field is a JSON number, so a 2-decimal amount with zero cents serializes without trailing zeros (`2500.00` -> `2500.0`) — `response.py:19-26`
- **§2.3 P1 (pagination)** — insert — **mismatch** — `limit`/`offset` must parse as integers (`1.0` rejected; whitespace, leading `+`, leading zeros tolerated), empty string takes the default, and on a parent-scoped sub-resource listing the **parent existence check precedes `limit`/`offset` validation** (contradicting the literal §2.6 rank-5-before-rank-6 reading), while enum filters are validated ahead of it — `middleware.py:220-245`, `routes/projects.py:340-345`, `routes/permits.py:347-353`, `routes/plans.py:110-119`
- **§2.3 P2 (ordering)** — insert — ambiguity — `created_at` ascending with ties broken by server insertion order (the common case, since the frozen logical clock gives many rows one `created_at`) — `db.py:76-78`
- **§2.4 (logical clock)** — insert — ambiguity — `to_iso8601` required and must parse; clock may be moved backwards; clock response `data` carries `current_utc` only — `routes/clock_routes.py:14-18`
- **§2.4 (timestamps)** — insert — ambiguity — only server-stamped instants use the canonical 3-fractional-digit `...Z` form; client-supplied body timestamps are stored/echoed byte-for-byte, offsets normalised to UTC and offset-less values read as UTC for comparisons — `clock.py:50-65`, `middleware.py:193-201`, `routes/wellbores.py:124-125`, `routes/permits.py:325-328`
- **§2.6 rank 5 (request shape)** — insert — ambiguity — body must be a JSON object (absent/blank body = empty object; other JSON types and unparseable bodies rejected); explicit `null` == omitted; undeclared fields ignored; required strings non-empty after trimming; numbers as JSON numbers (not strings, not booleans); counts/years/version guards must be JSON integers (`2.0` rejected) — `middleware.py:61-201`
- **§2.8 (cascades)** — insert — ambiguity — each row is bumped **at most once per request** even when several recomputation chains reach it — `db.py:61-73`, `app.py:56-59`
- **§2.10 (filters)** — insert — ambiguity — out-of-enumeration filter values -> `ERR_INVALID_REQUEST`, `tax_year` filter must be an integer, and identifier filters are opaque string matches (unknown id -> empty page, not 404) — `middleware.py:248-273`, `routes/claims.py:78-89`, `routes/models.py:96-107`
- **§2.10 last P (read-time recompute)** — revise — **mismatch** — PRD said "recomputes its derived fields" on a single-project read; impl refreshes **only `pisc_elapsed_years`**, and does so on every project render (read, listing, and mutation response) — `services/serialize.py:225-229`, `services/derive.py:171-174`
- **§4 intro (endpoint surface)** — insert — ambiguity — a trailing slash is equivalent to the path without one — `app.py:47`
- **§5 intro (error catalogue)** — insert — ambiguity — three framing-level identifiers outside the table: `ERR_NOT_FOUND` (404) for an undefined path, `ERR_METHOD_NOT_ALLOWED` (405) for an unsupported method, `ERR_INTERNAL` (500) for a server fault; the first two are routing decisions and outrank header authentication — `app.py:65-80`, `errors.py:65-67`

Wording was cross-checked against the out-of-scope route/service files before committing (integer-vs-decimal field inventory via `req_int`/`opt_int`, `db.touch` call sites, `serialize.project` call sites, filter/existence/pagination ordering in all four listing modules) so no claim is falsely universal.

### Pass 2 (calc/derive + projects/instruments/remediation) — 439 → 439 lines, 113,575 → 117,055 chars (+3,480); 11 ambiguity-pins, 4 mismatch-revisions

- **§3.2 (plume simulation)** — insert — ambiguity — pinned the degenerate seal-integrity path: when the already-rounded simulated pressure buildup is <= 0 (rate cap floored to 0, or a highly permeable/porous zone driving the quotient below 0.005 psi) no division is attempted and both indices are exactly `0.000`, so the governing index bands `FAIL` — `services/calc.py:62-73`
- **§3.8 (administrative fee)** — revise — **mismatch** — PRD named a nonexistent field `effective_annual_injection_rate_tpy`; corrected to `effective_injection_rate_tpy` and pinned that it reads 0 (lowest tier) when the project has no governing model — `services/calc.py:237-243`, `services/derive.py:35-39`
- **§3.6 (suspension cascade)** — revise — **mismatch** — PRD attributed the claim revert to an individual permit having left `ACTIVE`; impl runs the claim sweep off the same two triggers as the permit sweep, so a freeze or PISC handover with no `ACTIVE` permit still reverts `SUBMITTED` claims — `services/derive.py:215-229`
- **§3.8 (resolve order)** — revise — ambiguity — the posture reset happens whatever the project's `status`, while suspended permits are reinstated only while `status` is `INJECTION_ACTIVE` — `routes/remediation.py:116-120`, `services/derive.py:232-241`
- **§3.8 (authorize-injection)** — revise — ambiguity — a `RESTRICTED` posture is refused with `ERR_INVALID_PROJECT_STATE` — `routes/projects.py:192-193`
- **§3.8 (authorize-injection)** — revise — ambiguity — the "at least one `APPROVED` permit" precondition yields `ERR_INVALID_PROJECT_STATE` and sits between the AoR and monitoring-plan checks — `routes/projects.py:204-206`
- **§3.9 (begin-pisc)** — revise — ambiguity — `alternative_timeframe_years` must be a JSON integer but carries no range bound of its own; zero/negative is accepted and left to the clamp — `routes/projects.py:233`
- **§3.9 (begin-pisc)** — revise — ambiguity — the `ACTIVE`-permit-not-`COMPLETED` precondition yields `ERR_INVALID_PERMIT_STATE` — `routes/projects.py:244-249`
- **§3.5 (unitization ruling)** — revise — **mismatch** — `statutory_bonus_per_acre_usd` required (>=0) only on a grant; `statutory_royalty_rate_pct` is optional (>=0), range-checked on either decision, defaults to null, and is never a project payload field — it lands only on swept tracts — `routes/projects.py:137-139,159-166`
- **§3.8 (allocate)** — revise — ambiguity — the four requirement figures come from a fresh bucket evaluation at allocation time; the stored `required_financial_assurance_usd` is read only for the >0 gate and is never rewritten — `routes/instruments.py:81-88`
- **§3.8 (deallocate)** — revise — ambiguity — the project-status gate is checked after the instrument's own state and refused with `ERR_INVALID_PROJECT_STATE` — `routes/instruments.py:117-121`
- **§3.8 (reserve draw)** — insert — ambiguity — a `CRITICAL` order whose draw computes to exactly 0.00 despite a qualifying instrument leaves that instrument untouched at `ALLOCATED` — `routes/remediation.py:85`
- **§3.1 (project creation)** — revise — **mismatch** — `effective_annual_monitoring_cost_usd` is the supplied cost rounded half up to 2 dp, while `annual_monitoring_cost_usd` echoes back unrounded — `routes/projects.py:68`
- **§2.9 (posture gate)** — insert — ambiguity — a funding recomputation refreshes coverage status but never moves a `FROZEN` posture — `services/derive.py:128-129`
- **§3.9 (certify-closure)** — insert — ambiguity — the §3.9 narrative order is not the evaluation order: attestation > open-order > elapsed-time, with SoD ahead of all three and before body validation — `routes/projects.py:268-302`

Behaviors deliberately left unpatched as already uniquely pinned or observationally equivalent: `recompute_open_remediation_count` recomputing rather than incrementing; the conditional `pending_credit_usd` recompute inside the suspension cascade; `posture=False` on the closure/draw coverage recomputes (unreachable divergence); unreachable clamps in `max_injection_rate` and `plume_and_aor`.

### Pass 3 (models/wellbores/tracts/permits/plans/claims) — 439 → 439 lines, 117,055 → 121,603 chars (+4,548); 16 ambiguity-pins, 7 mismatch-revisions

- **§2.6 rank 5** — insert — ambiguity — body interval-bound ordering (`window_end`/`lease_term_end`/`period_end` strictly later than their starts) is evaluated at rank 5, ahead of existence and state — `wellbores.py:96`, `tracts.py:115`, `permits.py:301`
- **§3.2** — revise — ambiguity — `injection_years` must be a JSON integer >= 1 — `models.py:121`
- **§3.3** — insert — ambiguity — model acceptance advances the project only from `SITE_CHARACTERIZATION`; a project already beyond it keeps its status — `models.py:225`
- **§3.3** — insert — ambiguity — finalize-AoR's rescore population is read off `corrective_action_status` (not re-tested against the new radius), and a rescored wellbore's `version` bumps only if promoted or if a figure actually changed — `models.py:252-266`
- **§3.4** — insert — ambiguity — completing before `ca_window_start` is refused with `ERR_INVALID_WELLBORE_CA_STATE` — `wellbores.py:149`
- **§3.5** — revise — **mismatch** — `tract_label` is *not* required unique within a project (no such check exists) — `tracts.py:28`
- **§3.5** — insert — ambiguity — `bonus_per_acre_usd`/`royalty_rate_pct` are required, >= 0, with no upper bound — `tracts.py:72`
- **§3.5** — insert — ambiguity — a non-improving counter is `ERR_INVALID_REQUEST`, raised *after* the tract state check — `tracts.py:130`
- **§3.5** — insert — ambiguity — terminate-lease's project-status gate is `ERR_INVALID_PROJECT_STATE`, evaluated after the tract's own state check — `tracts.py:173`
- **§3.6** — revise — **mismatch** — `well_name` is *not* required unique within a project — `permits.py:29`
- **§3.6 (+ §4 permit-create row)** — revise — **mismatch** — permit creation checks only project ownership of the model; neither the model's `status` nor `seal_classification` gates it — `permits.py:35-42`
- **§3.6** — insert — ambiguity — among submit's refusals, pressure outranks casing-programme outranks AoR (per §2.6) — `permits.py:116-133`
- **§3.6** — revise — ambiguity — a non-`ACCEPTED` model on `BEGIN_TECHNICAL_REVIEW` yields `ERR_INVALID_MODEL_STATE`, checked before the classification — `permits.py:158`
- **§3.6** — revise — **mismatch** — the `DRILLING` step's only extra precondition is the `APPROVED` permit status (`ERR_INVALID_PERMIT_STATE`, ahead of the sequence check); the FROZEN gate guards *every* construction step, not just the first — `permits.py:205-214`
- **§3.6** — insert — ambiguity — recording an MIT has no permit/construction state precondition and advances neither dimension — `permits.py:236-246`
- **§3.7** — insert — ambiguity — retiring an already-`RETIRED` method is admissible and still bumps both versions — `plans.py:134-144`
- **§3.7** — revise — **mismatch** — an unconditioned approval leaves `effective_annual_monitoring_cost_usd` exactly as it stands (it does not reset an earlier uplift) — `plans.py:245-250`
- **§3.7** — insert — ambiguity — `condition_count` is an optional non-negative integer, range-checked on any decision, defaulting to 0 — `plans.py:185,252`
- **§3.7** — revise — **mismatch** — the 1.15 uplift persists unconditionally once written (never lowered, never compounded) — `plans.py:254`
- **§3.9** — insert — ambiguity — void's ALLOWED-claim block is `ERR_INVALID_CLAIM_STATE`, using the same tax-year containment test (a straddling record is blocked by no claim) — `permits.py:370-375`
- **§3.9** — insert — ambiguity — dependent claims' `version` bumps only where one of the four figures changed — `permits.py:382-387`
- **§3.9** — insert — ambiguity — claim submit's `reported_tonnes > 0` gate is `ERR_INVALID_CLAIM_STATE`, applied after the plan-approval check and to the freshly recomputed figure — `claims.py:121-125`
- **§3.9** — revise — **mismatch** — `ALLOW` reads the stored `verified_tonnes` for its gate (`ERR_INVALID_CLAIM_STATE`) and then recomputes *all four* derived figures on the current ledger, not just `credit_amount_usd` — `claims.py:159-165`

### Step 9 totals and orchestrator verification

- Source `PRD.md` (439 lines, 108,960 chars) -> `PRD_COMPLETED.md` (439 lines, 121,603 chars): **char delta +12,643**, line delta 0 (every edit is in-paragraph; no new sections).
- **37 ambiguity-pins, 13 mismatch-revisions** across the three passes (50 changes total).
- Independently verified by the orchestrator: `md5sum` differs from `PRD.md` (`8d6e3e89...` vs `25105815...`), so the scan genuinely ran and did not return a byte-identical copy; 27 headings present (§1-§5 with 2.1-2.10 and 3.1-3.9); §4 endpoint table still has all **60** rows; §5 error table still has all **50** rows; the file ends at a real boundary (final error-table row `ERR_ALLOCATION_EXCEEDS_FACE_AMOUNT | 422`), not mid-sentence.
- Also verified: **no file under `workspace/implementation/`, `test_suite/`, or `test_helpers/` was modified after the 04:47 passing sweep**, so Step 7's 8x98/98 green result still describes the artifact as it now stands. Step 9 changed documentation only.

## Pipeline complete — 2026-09-03T05:20:00.000Z

All nine steps done (Step 8 legitimately skipped per its skip condition). Final artifact set: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `worklog.md`, `test_helpers/` (9 files), `test_suite/` (conftest + 17 test files, 98 tests), `workspace/{INSTRUCTION.md, PRD.md, PRD_COMPLETED.md, implementation/}` with `results.{1..8}.json` all at 98/98.
