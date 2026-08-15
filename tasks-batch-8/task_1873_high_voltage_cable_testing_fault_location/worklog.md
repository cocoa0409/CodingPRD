# Worklog — task_1873_high_voltage_cable_testing_fault_location

## Step 1: Create Task Directory — 2026-08-14T21:57:00.000Z

Directory tasks/task_1873_high_voltage_cable_testing_fault_location/ and workspace/ pre-created by the pipeline invoker (Step 1 marked ALREADY DONE).

## Step 2: Generate Scaffold — 2026-08-14T22:38:00.000Z

All three scaffold artifacts are complete and lint-clean. Summary:

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1873_high_voltage_cable_testing_fault_location/SCAFFOLD.yaml` (§1.0–§1.7 only; no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1873_high_voltage_cable_testing_fault_location/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1873_high_voltage_cable_testing_fault_location/SCAFFOLD_CORNER_DESIGN.yaml` (single top-level key `scaffold_corner_design`)

## SCAFFOLD.yaml counts

- **Entities: 12** — CableCircuit, OutageWindow, TestJob, IsolationPermit, TestSeries, TestReading (append-only, `common_fields: false`), FaultRecord, ExcavationOrder, RepairSplice, MobileUnit, EquipmentAssignment, HealthAssessment (self-referential via `supersedes_id`). Flat topology, all FKs use canonical `FK -> X.id` prefix and have reverse-reachability GETs.
- **State machines: 11** — cyclic CableCircuit (IN_SERVICE→…→IN_SERVICE), revert-loop TestJob (IN_PROGRESS↔SUSPENDED), reopen-cycle FaultRecord (CLOSED_VERIFIED→REOPENED→PINPOINTED), plus guarded/compound transitions (job EVALUATION auto-gates on all-series-terminal AND all-faults-closed).
- **Concurrency rules: 2** (true races, OCC-only): `health-assessment-create-stale-circuit` (create-with-supersede on `CableCircuit.version`) and `test-job-reschedule-stale` (plan supersede on `TestJob.version`), both ERR_STALE_VERSION/412.
- **Calculations: 7** — series_verdict (dual as-tested/temperature-corrected basis, round-before-compare, tip-up rule), fault_distance_corridor (standard vs calibrated VF variants, min-clamped corridor), outage_overrun_charge (tiered, per-tier-round-then-sum pinned, estimate/actual variants), health_index_score (4-factor weighted tiers, formal/provisional input sets, band boundaries), job_estimate_cents (circular-looking tier keyed on pre-surcharge subtotal, order pinned), job_invoice_cents (per-line markup rounding pinned), unit_committed_hours (invariant aggregation).
- **Validations: 37** ordered rows (auth → authz → request → existence → OCC → state → safety → temporal → constraint → referential → fiscal).
- **Endpoints: 89** incl. `POST /cable-diagnostics/_clock/set_current_utc` with mandated default `2026-08-01T00:00:00Z` stated in its description.
- **Errors: 37**, all triggerable and all exercised by design instances.
- **Roles: 8** (all opaque; segregation-of-duties enforced via X-User-ID inequality on permit issue/verify/release; NetworkPlanner customer-acceptance vs TestSupervisor execution split).

## §1.8 — 25 non-stub instances (all 9 rules)

dual_variant_calc 3 (series verdict, fault distance, health basis — three different entity domains) · combinatorial_formula 3 (modes a/b/c: weighted tiers, per-line invoice rounding, estimate tier order) · non_linear_state_machine 2 (fault reopen cycle, job suspend/resume) · transitive_cascade 2 (splice-accept depth-3 across RepairSplice→FaultRecord→CableCircuit→TestJob; window-close depth-3 across OutageWindow→EquipmentAssignment→MobileUnit) · priority_pair_validation_conflict 3 (state vs safety, temporal vs fiscal, authz vs existence) · boundary_precision_check 4 (tan-delta 79.95→80.0 FAIL rounding boundary, exact 4h equipment buffer, 15-min grace `>` semantics, health score exactly 40.0 POOR) · cross_entity_state_dependency 3 · resource_temporal_overlap 3 (half-open windows vs 4h-buffer assignments vs inclusive containment) · compensating_invariant 2 (committed_hours, unresolved_fault_count).

## §1.9 — 66 instances: 59 non-stub + 7 `excluded_because` stubs

Sections: entities 6 (1 stub), state_machines 8, calculations 6, validations 24, endpoints 6, errors 4 (all stubs citing §1.8), rbac 4, cross_cutting_layers 7 (2 stubs), consistency_model 1. Every stub cites an existing §1.8 instance name (verified). All 37 error codes are triggered by at least one non-stub instance across both files.

## Verification

- `scaffold_lint.py` verdict (verbatim): **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (89 endpoints, 12 entities, 25 + 59 instances, 1378 calls scanned, 0 violations)
- Additional scripted audits: all `grounds:` references resolve to declared §1.1–§1.7 elements; instance names unique across both files (90 total); all formula-derived asserts pre-computed as literals (e.g., estimate 424000 for the exact 400000-subtotal boundary, invoice 749586 vs 749587 sum-rounding gap, health 96.2 formal vs 75.2 provisional, corridor [1404.0, 1716.0], overrun 18000 cents); no forbidden concurrency vocabulary.
- Design-time fixes applied during generation: evaluate-from-ENERGIZING transition added (makes ERR_NO_READINGS reachable), excavation uniqueness relaxed to one *open* order per fault with fault-state gate widened (makes ERR_DIG_WINDOW_OVERLAP reachable), unreachable TestSeries ABORTED state removed (enum closure), window-approve precondition widened to {IN_SERVICE, OUTAGE_PENDING} (multi-window circuits), conditional circuit cascade on window close.

## Step 3: Copy Shared Files — 2026-08-14T22:38:30.000Z

Copied ./INSTRUCTION.md to tasks/task_1873_high_voltage_cable_testing_fault_location/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-14T22:50:00.000Z

All audits pass. Here is the summary.

## Output

**Path:** `/home/ubuntu/github/CodingPRD/tasks/task_1873_high_voltage_cable_testing_fault_location/workspace/PRD.md`

**Structure:** 350 lines; §1 Introduction (2 paragraphs), §2 with 10 subsections (2.1 RBAC · 2.2 Response Structure · 2.3 Pagination · 2.4 Logical Clock & Interval Semantics · 2.5 Resource Identity & Common Properties · 2.6 OCC · 2.7 Validation Pipeline & Error Precedence · 2.8 Precision/Rounding/Electrical Constants · 2.9 Segregation of Duties · 2.10 Fiscal Guardrails), §3 with 9 workflow subsections (circuit registration → outage windows → job planning → permits → fleet → series/verdicts → faults/pinpointing → excavation/splice/acceptance → health assessment/trending), §4 endpoint table (89 rows, 4 columns), §5 error catalogue (37 rows, 2 columns). No audit footer — document ends at §5.

## Hard-contract audit results

**Contract 1 — Field-Name Coverage: PASS**
- `entities[].fields`: 84 required, 84 present, 0 missing
- `endpoints[].request_body` (non-entity inputs: `to_iso8601`, `expected_circuit_version`, `expected_test_job_version`, `reason`, `use_calibrated_velocity`, `restored_at`): 6/6 present
- `endpoints[].query_params`: 15/15 present; common props (`id`, `created_at`, `updated_at`, `version`): 4/4 present
- All enum/state values (88) and all 37 error IDs appear as exact backticked strings; all 8 role names present

**Contract 3 — §3 Path Purity: PASS** — 615 backticked tokens scanned in §3; zero tokens starting with `/`, zero bare HTTP methods, zero method+path combos (§3 uses state-pair framing, role+verb, and capability descriptions throughout)

**Contract 2 — Rule Coverage: PASS** (manual walk; rules verified stated verbatim in prose):
- **Validation priority (37/37):** full 7-stage pipeline with the 31-rule business order enumerated in §2.7, plus explicit per-endpoint orderings in §3 — e.g. `ERR_STEP_OUT_OF_RANGE` before `ERR_DUPLICATE_STEP` (the 422-before-409 inversion), `ERR_NO_READINGS` before `ERR_STEP_INCOMPLETE`, excavation-create 6-deep gauntlet, reschedule order (stale-version → window-state → splice-exists → cross-reference), permit-release (job-`EVALUATION` state check before the SoD check)
- **OCC (2/2):** both rules name write capability, `expected_circuit_version`/`expected_test_job_version`, parent `version` match, `ERR_STALE_VERSION` (412); framed purely in stale-version terms, no race language; explicit that no other endpoint takes a version field
- **State machines:** all 11 machines / ~60 transitions with preconditions paired to error IDs and all side effects — including the window-close 3-hop cascade, job-abort cascade, fault-closure cascade (`closed_at`, counters, `splice_count`, job `EVALUATION` gate), and the assessment-create supersedes-plus-circuit-version-bump
- **Calculations (7/7):** verdict thresholds with boundary inclusivity, correction-factor clamp, distance/corridor formula, tiered overrun charge with pinned per-tier rounding, health score with full-precision single rounding, estimate with pre-surcharge tier keying (exactly 400,000 cents → STANDARD), per-line invoice markup, committed-hours add/subtract-without-drift; constants embedded in context; worked examples carried over (88.0 at 35 °C → 79.2; 20 µs on `KV_15` → 1,560.0 m vs 1,500.0 m; 325,586 vs 325,587 cents; 96.2 formal vs 75.2 provisional)
- **applies_to scopes:** `ERR_SPLICE_EXISTS` on all 3 endpoints, `ERR_CROSS_REFERENCE_MISMATCH` on all 3, `ERR_BUDGET_EXCEEDED` on all 3, `ERR_WINDOW_NOT_ACTIVE` on all 4
- **Field structured content:** all defaults/initials stated (`use_temperature_correction` false, `is_retest` false, counters zero, health/verdict/pinpoint/`restored_at`/`supersedes_id` null-until semantics); `TestReading` `common_fields: false` exception explicit in §2.5
- **Sibling symmetry:** equal density for cancel from `REQUESTED`/`APPROVED`, evaluate from `ENERGIZING`/`LOGGING`, pinpoint from `SUSPECTED`/`REOPENED`, supersede from `COMPUTED`/`REVIEWED`/`ADOPTED`, dual verdict bases, dual velocity variants, estimate/actual overrun variants, formal/provisional health bases

**Contract precision spot-checks:** §2.2 byte-identical to `section-2.2-response-structure.md`; zero pseudocode operators (`>=`, `==`, `min()`, `AND`, `±`, etc.) anywhere outside fences; zero fuzzy/approximating words (the two "about" hits are ordinary English, not approximations).

**One scaffold ambiguity resolved and worth flagging:** the `ExcavationOrder.fault_record_id` field note says "at most one excavation in {DRAFT, PERMITTED, IN_PROGRESS}" while validation #30 and the error catalogue say "non-CANCELLED". I followed the validation/error-catalog wording ("no excavation order that has not been cancelled may already exist for the fault") since it has 2-of-3 support and the validations table is the enforcement layer. The two DESIGN files were never opened; no sibling tasks were consulted.

## Step 5: Generate Unit Tests — 2026-08-14T23:25:00.000Z

Generation complete and fully audited. Summary below.

## Files written

**`/home/ubuntu/github/CodingPRD/tasks/task_1873_high_voltage_cable_testing_fault_location/test_helpers/`** (9 files):
- `types.py` — 12 entity TypedDicts (TestReading correctly omits `updated_at`/`version`), 17 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (66 methods), singleton `api_client`
- `api_errors.py` — all 37 `ApiErrorId`s + HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions (incl. append-only reading check) + counter invariants
- `factories.py` — 13 payload factories, input fields only
- `constants.py` — U0/VF tables, verdict thresholds, overrun tiers, estimate fees, health weights, standard timeline
- `test_users.py` — 8 opaque role header sets + so-1/so-2/so-3 segregation identities + builders
- `fixtures.py` — 5-tier composite setups up to `setup_fault_closed_verified` / `setup_job_in_evaluation` / `setup_job_completed` / `setup_retest_accepted`
- `__init__.py` — barrel export

**`/home/ubuntu/github/CodingPRD/tasks/task_1873_high_voltage_cable_testing_fault_location/test_suite/`** (13 files): `conftest.py` + `test_01_circuit_registration.py` … `test_12_security.py`.

## Test counts per queue
- **Queue A (Difficulty): 51 tests across all 25/25 instances** (each ≥2; `fault_distance_standard_vs_calibrated_velocity` got 3 — standard, corridor, calibrated-selection).
- **Queue B (Corner): 59 tests across 58 translated non-stub instances** (`pd_threshold_2000_boundary` got 2).
- 110 tagged test functions; **117 collected by pytest** (the all-roles read test is parametrized ×8). All 7 `excluded_because:` stubs verified to resolve to real difficulty instances; not translated.

## Instances skipped (1)
- `Corner/validations/dig_window_overlap_rejected` — fails the PRD-first filter: its third trigger asserts an adjacent second dig is **created (201)** while the fault's first excavation is BACKFILLED, but PRD §3.8 states "no excavation order that has not been cancelled may already exist for the fault (else `ERR_EXCAVATION_EXISTS`)" — BACKFILLED is not cancelled, so the asserted outcome contradicts the contract. Gap stays a gap; no placeholder emitted.

## Stage 2 self-audit results
- **Tag integrity:** 0 untagged, 0 dual-tagged, 0 unknown/stub-pointing tags; every `Design:` line is the final docstring line and resolves to a real `name:` in the source yaml.
- **C1 verbatim pass:** 147 rule-bearing quoted spans extracted from docstrings; all survive literal (whitespace-normalized) match against PRD.md. Fixed 23 initially failing citations (ellipses expanded to full sentences; `**Stage**` markdown prefixes restored; §4 role rows cited as verbatim table lines).
- **Error IDs:** all 36 asserted IDs appear in PRD §1–§3 narrative prose, not only the §5 table.
- **No skip/xfail/skipif** anywhere; **no scaffold references** in comments/docstrings.
- **Imports/collection:** all modules import; `pytest --collect-only` clean.
- **Two-reader relaxations applied:** absolute initial-version values (e.g. `version == 1`, `== 7`) replaced with relative `+1`-per-mutation checks (PRD §2.5 pins the increment, not the initial value); `circuit_auto_status_progression` replayed in PRD-legal order (job create requires an APPROVED window) while preserving every milestone assertion (IN_SERVICE → OUTAGE_PENDING → DE_ENERGIZED → GROUNDED → UNDER_TEST).

## Step 6: Generate Implementation — 2026-08-14T23:22:00.000Z

The implementation is complete and fully smoke-tested. Summary:

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_1873_high_voltage_cable_testing_fault_location/workspace/implementation/`:

- `start.sh` — executable; guarded dependency install (`import flask` check, no re-install on per-test reboots); `exec python3 app.py` in foreground; binds `0.0.0.0`, `PORT` env (default 10000)
- `requirements.txt` — flask>=3.0,<4.0
- `app.py` — app factory, blueprint registration, envelope-consistent handlers for ApiError/404/405/500
- `db.py` — in-memory dicts only, completely empty at boot (no seeding); logical clock starting exactly `2026-08-01T00:00:00Z`, never wall-clock
- `errors.py` — all 37 error IDs from the catalog + ApiError
- `response.py` — exact envelope: `meta{api_request_id, api_request_timestamp}` + `response_type` + `data`; pagination fields (`limit/offset/total_count/has_more`) inside `meta` for lists only
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401/403), 8 declared roles
- `helpers.py` — request-shape validators (400), left-to-right existence (404), serializer (ISO 8601 with 3 fractional digits, Decimal→float), created_at-ascending pagination (limit default 10, 1..100)
- `util.py` — round-half-up Decimal math, whole-minute/ceil-minute/hour conversions, trailing-24-months
- `services/calc.py` — all 7 calculations: dual-basis series verdicts (temperature correction with clamp 0.9–1.1, tip-up, PD thresholds), pinpoint distances/corridor (standard vs calibrated VF), tiered overrun charge (per-tier rounding, 15-min grace, 1.25 emergency multiplier, estimate-vs-actual), health index (weighted penalties, single final rounding, FORMAL/PROVISIONAL), job estimate (complexity tier keyed on pre-surcharge subtotal), invoice (per-line 8.5% markup then sum), committed hours
- `services/workflow.py` — version/updated_at bumps, fault counters + replacement flag, job auto-EVALUATION gate, unit hours settle, release/cancel cascades
- `routes/` — 12 modules, one per resource group

## Coverage

- **All 89 endpoints** from the endpoint table are registered (verified via `url_map` count): clock, circuits (7), outage windows (8), test jobs (15), isolation permits (6), test series/readings (10), faults (8), excavations (8), splices (8), mobile units (6), equipment assignments (7), health assessments (5).
- **All 12 entities**, all state machines including the cyclic circuit chain, permit segregation-of-duties (verify≠issue, release≠verify), fault reopen loop, suspend/resume, the 3-hop window-close cascade (circuit restore → assignment release → unit hours/availability), job-abort cascade, and assessment create-with-supersede.
- Both OCC-guarded writes return `ERR_STALE_VERSION` 412; full validation pipeline ordering (auth → authorization → shape → existence → concurrency → state → ordered business rules) implemented per PRD §2.7 with per-endpoint orderings from §3 (e.g., window-state → splice-exists → circuit-busy → cross-reference at job create).

## Clean-boot smoke test

Confirmed: three full test passes (153 assertions total — 106 happy-path/calculation checks, 43 edge-case checks, 4 reopen/cancel checks) all pass, including exact cent values (estimate 884800, invoice lines 108543/217043 → 1210386, overrun 2000, emergency estimate 16500), verdict math (raw 88.0 @ 35 °C → corrected 79.2 flips FAIL→MONITOR), pinpoint variants (1560.0 vs 1500.0 m), and health scoring (75.2/FAIR). Server was killed and relaunched via `bash start.sh` repeatedly; each fresh process boots in ~2 seconds with an empty store and the clock at the spec default — safe for `--isolation per-test-server`.

## Step 7: Run Tests and Iterate — 2026-08-14T23:45:00.000Z

Sweep 2 is clean: **all 8 rounds passed=117/117, failed=0**. The union of failing tests is empty — the exit condition is met.

## Summary

**Iterations run:** 2 (sweep 1: 5 deterministic failures × 8 rounds → diagnosed and fixed; sweep 2: clean, 117/117 in all 8 rounds).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`** (1 file):
- `/home/ubuntu/github/CodingPRD/tasks/task_1873_high_voltage_cable_testing_fault_location/test_helpers/assertions.py` — added `assert_same_instant(actual, expected_iso)`: compares parsed instants instead of raw strings, because PRD pins the three-fractional-digit format only for server-generated timestamps (`api_request_timestamp` §2.2, `created_at` §2.5) and is silent on the serialization of client-supplied domain timestamps (STEP 1b unique-derivability collapse: verbatim-echo vs. canonical-normalization both PRD-faithful).

**Fixes applied to `test_suite/`** (4 files, 5 failing tests):
- `test_02_outage_windows.py::test_half_open_adjacency_allowed` — STEP 1c partial coverage: kept the PRD-covered assertions (201 creation under half-open adjacency, §3.2 verbatim; added `status == "REQUESTED"`), replaced the uncovered verbatim-echo assertion on `window_start` with `assert_same_instant`.
- `test_09_excavation_and_splice.py::test_dig_end_equal_window_end_allowed` — same STEP 1c treatment: kept covered assertions (201 + `DRAFT` under the inclusive `dig_end` edge, §3.8 verbatim), replaced verbatim echo of `dig_end` with `assert_same_instant`.
- `test_03_test_jobs.py::test_suspend_resume_loop_ends_in_progress_with_version_drift` — STEP 2 test arithmetic bug: version was read after setup (create+plan+start = 3) but the assertion added 6; only 4 mutations (two suspend/resume loops) occur after the read. Fixed to `version_in_progress + 4` (PRD §2.5 "+1 per mutation" fully preserved).
- `test_10_health_assessments.py::TestBasisVariants._circuit_with_accepted_and_evaluated_series` (fixes both `test_formal_basis_counts_accepted_only` and `test_provisional_basis_includes_evaluated_and_supersedes`) — STEP 2 fixture-ordering bug: the helper accepted PASS series A (faultless) before creating series B, which fires the PRD §3.3 auto-evaluation gate (all series terminal ∧ all faults CLOSED_VERIFIED → job → EVALUATION) and makes series-B creation correctly fail with `ERR_INVALID_STATE`. Reordered: create+evaluate both series first, then accept A (B stays EVALUATED → gate stays closed). The §3.9 basis assertions (96.2 FORMAL / 75.2 PROVISIONAL, supersedes semantics) are untouched.

**Fixes applied to `implementation/`:** none — the implementation was PRD-faithful on every failure (timestamp normalization, version increments, and the auto-evaluation gate all behaved per PRD).

**Feedback notes for generators:** the two timestamp-echo tests were Zero-Silence/unique-derivability misses — assertions on a serialization format PRD never declares (DEFAULT-VALUE SILENCE analog for representation); the test_03 failure was a fixture-read-vs-mutation-count bookkeeping error; the test_10 failures were a fixture violating a PRD state-machine precondition (auto-evaluation gate), masquerading as two independent setup failures — consistent with the triage hint that shared setup errors point at the fixture layer first.

## Step 8: Finalize PRD — 2026-08-14T23:55:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1873_high_voltage_cable_testing_fault_location/workspace/PRD_FINALIZED.md` produced as a minimal patch of PRD.md.

## Summary

**Line counts:** PRD.md 349 lines → PRD_FINALIZED.md 351 lines (+2 lines, +0.57%). The delta is a single inserted paragraph (plus its separating blank line); all other prose is verbatim.

**Changes (one edit total):**
- §2.4 (The Logical Clock and Interval Semantics) — **insert** — added a "Timestamp representation is uniform across the API" paragraph pinning that client-supplied timestamps (`window_start`, `window_end`, `restored_at`, `dig_start`, `dig_end`, `mobilize_at`, `demobilize_at`, `to_iso8601`) are parsed as ISO 8601 instants, converted to UTC, and returned in the same canonical three-fractional-digit `Z` form as `api_request_timestamp`/`created_at` (never echoed verbatim; comparisons apply to parsed instants) — `implementation/util.py:7-27` (`iso`/`parse_dt`), `implementation/helpers.py:83-88` (`req_dt`), `implementation/helpers.py:107-118` (`serialize`), `implementation/routes/clock_routes.py:18-22`.

**Step-7 items requiring no PRD edit:** the `test_03` version-drift failure was a pure test-arithmetic bug (PRD §2.5 "+1 per mutation" already matches `services/workflow.py:13-16` `touch`); the `test_10` health-assessment failure was a fixture-ordering bug against the §3.3 auto-evaluation gate, which the PRD already pins; the added `status == "REQUESTED"` and `DRAFT` assertions in `test_02`/`test_09` are already pinned by §3.2 ("lands in `REQUESTED`") and §3.8 ("starts in `DRAFT`"). No implementation fixes existed, so no mismatch edits were needed.

**Per-edit pre-edit search log (Edit 1):**
- (a) Subject: parsing and serialization representation of client-supplied domain timestamps, and uniformity of all server-returned timestamps.
- (b) Paths enumerated and read/grepped: rendering — `util.py:7-9` (`iso`), all three call sites `response.py:13`, `helpers.py:113`, `clock_routes.py:22`, plus `circuits.py:120-135` (trend, via `serialize_list`) and `services/calc.py:198-215` (invoice, returns only cent figures); parsing — `util.py:12-27` (`parse_dt`), `helpers.py:83-88` (`req_dt`), call sites `windows.py:40-41,140`, `excavations.py:29-30`, `assignments.py:33-34`, `clock_routes.py:18`; comparisons on parsed datetimes — `windows.py:42,46,50,129,144,149`, `splices.py:130,153`; server-stamped fields — `splices.py:119,133`, `faults.py:48`; all query-param filters grepped (no timestamp filters anywhere).
- (c) Wording adjustments: the universal claim "every timestamp the server returns" was verified against all three render sites before committing; deliberately left under-determined (i) rejection of malformed timestamp input (Step 7 never exercised it — out of scope), (ii) handling of offset-less naive inputs (impl treats as UTC, PRD stays silent), and (iii) internal storage precision (the claim is rendering-only, matching `iso`'s millisecond truncation).

## Step 9: Complete PRD — 2026-08-15T00:10:00.000Z

The diff shows exactly the 16 intended lines changed (line 149 carries two pins). Task complete. Final summary:

## Summary

**Source**: `workspace/PRD_FINALIZED.md` → **Produced**: `PRD_COMPLETED.md` (same directory).

**Size**: 351 lines → 351 lines (no lines added/removed; all edits inline). Char delta: **+2797** characters (66298 → 69095).

**Counts**: 15 ambiguity-pins, 2 mismatch-revisions (17 edits across 16 lines).

**Changes** (section — insert/revise — class — what changed — impl evidence):

- §2.2 — insert — ambiguity — `api_request_timestamp` (like all server-emitted timestamps) reads the logical clock, never wall clock — `implementation/response.py:13`
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`, negative `offset` → `ERR_INVALID_REQUEST` (400); `total_count` counts the filtered set; `created_at` ties broken by creation order — `implementation/helpers.py:126-166`
- §2.4 — insert — ambiguity — clock-set accepts any instant, including earlier than the current value (clock moves backward) — `implementation/routes/clock_routes.py:13-22`
- §2.4 — insert — ambiguity — offset-less input read as UTC, lowercase `z` accepted; rendering truncates sub-millisecond precision rather than rounding — `implementation/util.py:9,19,25-26`
- §2.5 — insert — ambiguity — `version` starts at 1 at creation; `updated_at` initially equals `created_at` — all create handlers, e.g. `implementation/routes/circuits.py:59-61`
- §2.7 (stage 3) — revise — ambiguity — added missing shape rules: `length_m` positive integer, `approved_budget_cents` > 0, `max_test_voltage_kv` > 0, `step_index` non-negative integer; method-conditional reading-field checks fire after the series path id resolves (they need the series' method); unknown body fields ignored — `implementation/routes/jobs.py:50-51`, `implementation/routes/units.py:34-37`, `implementation/routes/series.py:151-176`
- §3.1 — insert — ambiguity — trailing-24-month fault count includes a `closed_at` exactly 24 months before the clock (inclusive cutoff) — `implementation/services/workflow.py:49-59`
- §3.2 — insert — ambiguity — new window's `estimated_charge_cents` starts at 0 and is populated only at approval — `implementation/routes/windows.py:64,113`
- §3.2 — revise — ambiguity — at closure the `ACTIVE` state check fires before the `restored_at` comparison, so a non-`ACTIVE` window reports `ERR_INVALID_STATE` even when `restored_at` also precedes `window_start` — `implementation/routes/windows.py:142-145`
- §3.3 — revise — mismatch — `requested_methods` is a list, not a strict subset: duplicate entries are accepted and each listed entry is charged its method fee at planning — `implementation/routes/jobs.py:32-39`, `implementation/services/calc.py:192`
- §3.3 — insert — ambiguity — the open-splice gate at job creation is scoped to faults of this circuit — `implementation/routes/jobs.py:23-29,59`
- §3.3 — insert — ambiguity — resume re-runs the automatic EVALUATION gate, so a job resumed with all series terminal and all faults closed lands directly in `EVALUATION` — `implementation/routes/jobs.py:189`
- §3.3 — insert — ambiguity — invoice of a never-planned job: `estimate_cents` is null and contributes zero to the total — `implementation/services/calc.py:208-209`
- §3.5 — revise — mismatch — maintenance checks open assignments before the unit-state check, so an `ASSIGNED` unit is always answered `ERR_UNIT_HAS_ASSIGNMENTS` rather than `ERR_INVALID_STATE` (reverses the §2.7 stage-6-before-stage-7 default) — `implementation/routes/units.py:79-85`
- §3.6 — revise — ambiguity — readings appendable only while `ENERGIZING`/`LOGGING` (else `ERR_INVALID_STATE`); `pd_location_m` accepted and stored on any method's readings, never required/forbidden, used in no computation; unsupplied measurement fields stored and returned as null — `implementation/routes/series.py:163-185,201`
- §3.8 — insert — ambiguity — corridor containment compares `target_location_m` exactly as supplied, unrounded, against the rounded corridor bounds — `implementation/routes/excavations.py:48-50`
- §4 — insert — ambiguity — list filters match exactly; unmatched filter values yield empty pages (no error); `replacement_recommended` accepts `true`/`false` case-insensitively, ignored otherwise — `implementation/routes/circuits.py:78-87` and all list routes

Everything else in the impl (all 38 endpoint routes, role gates, state machines, verdict/estimate/overrun/pinpoint/health formulas, error catalog and HTTP statuses, check orderings, cascades, and the 201/200 conventions) was verified against the PRD and found already uniquely pinned — including the two worked examples (79.2 corrected tan-delta; 1,560.0 vs 1,500.0 m distances; 325,586-cent invoice) and every stage-7 error-ordering claim.
