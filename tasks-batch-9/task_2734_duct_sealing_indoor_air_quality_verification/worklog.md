# Worklog — task_2734_duct_sealing_indoor_air_quality_verification

## Step 1: Create task directory — 2026-09-04T13:27:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2734_duct_sealing_indoor_air_quality_verification` and its `workspace/` subdirectory. Index 2734 was pre-assigned by the invoking pipeline; no scan of ./tasks/ was performed and no other task directory was created.

## Step 2: Generate Scaffold — 2026-09-04T16:07:00.000Z

All three artifacts are complete and pass `scaffold_lint.py` clean.

## Files

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 1972 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2235 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 6509 |

All three `yaml.safe_load` cleanly. `SCAFFOLD.yaml` contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`; each design file has exactly one top-level key.

## SCAFFOLD.yaml counts (§1.0–§1.7)
12 entities · 8 state machines · 2 §1.2.1 concurrency rules · 8 calculations · 12 ordered validation rules (priorities 10–120) · **53 endpoints** (19 GET / 34 mutation) · 43 error codes · 4 roles (ProgramAdmin, FieldTechnician `entity_backed:Technician`, QAVerifier, UtilityInspector; `role_model: segregation_of_duties`, layers `rate_threshold_triggers` / `cascading_side_effects` / `dual_variant_calculation` / `optimistic_concurrency`, `consistency_model: immediate`).

## Design indices
- **§1.8 — 18 instances**: 9 rule_ids × 2 (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).
- **§1.9 — 97 instances across all 9 guide sections** (69 with full `test_recipe`, 28 `excluded_because` stubs): entities 12, state_machines 18, calculations 13, validations 21, endpoints 9, errors 14, rbac 5, cross_cutting_complexity_layers 4, consistency_model 1.

## Lint verdict
```
Coverage
  §1.5 endpoints declared:    53
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     69
  Calls scanned (§1.8+§1.9):  1588

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Additional self-audits: all 115 instance names unique across both files; every stub citation resolves to a §1.8 instance by name; zero unbound `${var}` in payloads, paths, `as_user_id` or asserts; all 43 error codes triggered by a named instance; every one of the 53 §1.5 endpoints exercised by at least one call, and no call references an undeclared endpoint or query parameter.

## §1.5/§1.1 defects the §1.9 audit pass forced back into SCAFFOLD.yaml
- `ERR_INJECTION_PRESSURE_LIMIT` was unreachable (priority 60 always pre-empted 80(d)) → added an explicit, resume-only carve-out to the priority-60 rule.
- Priority-30 segregation-of-duties listed 2 pairs but §1.2 enforced 3 (leakage-test review was missing from `applies_to`) and cited a non-existent `SealJob.created_by_user_id` → rewritten to the three real pairs.
- Added the missing `GET /duct-sealing/technicians/{id}` (52 → 53 endpoints); added `Project.duct_system_count`; `complete-seal` now decrements `Technician.open_seal_job_count` so the counter matches its declared definition; documented `pagination_placement` (the four pagination fields live in `meta` on array responses).
- Earlier in the session: `VerificationReport` DRAFT→ISSUED now accepts `verdict IN {PASS, MARGINAL}`, `LeakageTest` review triggers use `ACCEPT`/`REJECT`, and a priority-120 rule makes `ERR_GUARANTEE_NOT_MET` reachable.

## Step 3: Copy Shared Files — 2026-09-04T16:07:30.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-04T16:22:00.000Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — 415 lines, written incrementally in 8 heredoc appends; file ends cleanly on the final `ERR_PROGRAM_BUDGET_EXCEEDED` row of §5.

**Sections**
- §1 Introduction (3 paragraphs — evidence-chain framing, two design commitments)
- §2 Global Specifications: 2.1 RBAC · 2.2 API Response Structure (verbatim from `section-2.2-response-structure.md`, byte-checked) · 2.3 Pagination · 2.4 Resource Identity, Versioning and the Logical Clock · 2.5 Path Hierarchy and Reverse Reachability · 2.6 Measurement Precision and Rounding Discipline · 2.7 Stale-Version Guards on Supersede-Capable Creates · 2.8 The Rejection Ladder · 2.9 Segregation of Duties · 2.10 The Leakage Ledger and Its Compensation Identity · 2.11 Program Budget Ledger · 2.12 Combustion Safety and the Project Safety Hold
- §3 Business Logic, 9 subsections: 3.1 Program setup / certification / project intake · 3.2 Duct-system cataloguing, asbestos screening, retrofit exclusions (4-hop cascade) · 3.3 Reserve / pressurize / record / review a leakage measurement · 3.4 Combustion spillage testing and the safety-hold cycle · 3.5 Booking a run and masking · 3.6 The injection run, curve, stalls and cutoffs · 3.7 Verification, the two reduction bases, the guarantee · 3.8 Rebate money, spot check, resubmit, pay · 3.9 Warranty, follow-up re-test, comfort-complaint balancing
- §4 Endpoint Definitions (4-column table) · §5 Error Code Catalogue (2-column table)

**Hard Contracts**

```
Field coverage check:
- entities[].fields: 137 required, 137 present, 0 missing
- endpoints[].request_body: 83 required, 83 present, 0 missing
- endpoints[].query_params: 16 required, 16 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 12 checked, 12 expressed in prose (§2.8 ordered ladder, incl. the rung-60 resume/ABORTED_SAFETY carve-out and the 12(a)→(b)→(c) fiscal sub-order), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_duct_system_version / expected_seal_job_version + ERR_STALE_*_VERSION + 412), 0 missing
- state_machines[].transitions: 8 machines / 41 transitions checked, 41 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed (pinned round-then-divide-then-round; cap-before-fee; 3-sample backward window; per-appliance CO/WCD limit tables; warranty precedence), 0 missing
- validations[] conditions: 43 error ids checked, 43 matchable to a condition in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 53 endpoints checked, all side effects and all applies_to sets expressed, 0 missing
- entities[].fields[] structured content: 137 checked, defaults/initial values/nullability reconstructible, 0 missing
- sibling-branch symmetry: 7 groups checked (CLEARED/SUSPECT/CONFIRMED; ACCEPT/REJECT; PRE/POST accept effects; PER_CFM/PERCENT_OF_INVOICE/LESSER_OF_BOTH; inspector PASS/FAIL; two hold-clearing paths; BALANCING→RESOLVED vs BALANCING→DIAGNOSED), 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 881
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Note on the purity check: 9 occurrences of `` `POST` `` inside §3 are the `phase` enum value (`` `POST` ``-phase measurement / combustion test), required verbatim by Contract 1 and the state enumeration; none sits in endpoint-identifier position.

**Coverage confirmation:** 12 entities, all 53 endpoints (verified by row count in §4), all 43 error codes (verified in §5 and all 43 mentioned in §2/§3 narrative), all 12 validation rules, all 8 calculations, all 8 state machines. All state values and enum values from the scaffold appear verbatim in backticks; no fuzzy hedging words present. Constants embedded in prose rather than named: 0.60 flow exponent, 25 Pa reference, 80.00 default guarantee, 5 percent admin fee, tier bands 90/75/60, 60 s spillage, 1.0 Pa draft floor, per-appliance CO 100/800 and warn 50/400, WCD 5.0/999.0, 1000.0 Pa cutoff, 0.50 CFM/min stall, 3-sample window, 10.00 percent inspector tolerance and default room tolerance, 365-day re-test interval, 30-minute stabilization buffer, `2026-08-01T00:00:00Z` clock default. Neither withheld design file was opened, and no sibling task directory was read.

**Orchestrator truncation check:** `wc -l` = 415; §4 contains exactly 53 method-prefixed endpoint rows; §5 contains exactly 43 `ERR_*` rows; `tail` ends on a complete table row at a real section boundary. Not truncated — no regeneration needed.

## Step 5: Generate Unit Tests — 2026-09-04T17:35:00.000Z

All audits are green. The suite is complete.

## Deliverable

**Output location** (task root, not `workspace/`):
`/home/ubuntu/github/CodingPRD/tasks/task_2734_duct_sealing_indoor_air_quality_verification/`

### `test_helpers/` — 2,671 lines
| file | lines |
|---|---|
| `__init__.py` | 112 |
| `api_client.py` | 495 |
| `api_errors.py` | 120 |
| `assertions.py` | 327 |
| `constants.py` | 323 |
| `factories.py` | 413 |
| `fixtures.py` | 609 |
| `test_users.py` | 73 |
| `types.py` | 199 |

### `test_suite/` — 4,965 lines, 105 tests
| file | lines | tests |
|---|---|---|
| `conftest.py` | 21 | — |
| `test_01_entity_shapes_and_defaults.py` | 382 | 12 |
| `test_02_leakage_measurement_lifecycle.py` | 364 | 8 |
| `test_03_screening_exclusion_cascades.py` | 338 | 7 |
| `test_04_seal_job_scheduling.py` | 774 | 14 |
| `test_05_masking_and_injection_start.py` | 246 | 6 |
| `test_06_injection_curve_and_cutoffs.py` | 425 | 9 |
| `test_07_combustion_and_safety_hold.py` | 308 | 6 |
| `test_08_verification_report_and_guarantee.py` | 417 | 10 |
| `test_09_rebate_arithmetic.py` | 360 | 9 |
| `test_10_rebate_claim_lifecycle.py` | 265 | 5 |
| `test_11_comfort_complaint_balancing.py` | 393 | 7 |
| `test_12_rejection_ladder_and_rbac.py` | 672 | 12 |

### Coverage per queue
- **Queue A (Difficulty, §1.8): 36 tests / 18 instances.** All 18 instances are non-stub and every one carries >=2 tests (exactly 2 each).
- **Queue B (Corner, §1.9): 69 tests / 69 instances.** All 69 non-stub instances covered >=1; the 28 `excluded_because:` stubs were cross-reference-verified only and not translated.
- **Instances SKIPPED for PRD silence: none.** Every non-stub instance passed the two-condition PRD-first filter.

### Audits run over the finished suite (all clean)
1. **Design tags** — 105/105 tests carry exactly one `Design:` line, as the last line of the docstring; every tag resolves to a real instance; no dual tags; no tag points at a stub. Fixed one mis-sectioned tag: `start_injection_with_partial_masking_returns_masking_incomplete` lives under `state_machines`, not `validations`.
2. **PRD citations** — 177 quoted fragments checked not just for verbatim presence but for presence *inside the section each docstring cites*. 25 problems found and fixed, of which the load-bearing ones were:
   - **Two fabricated sentences.** `test_09` asserted PRD said budget refusal made "no partial commitment"; the PRD says "if it exceeds what is left, the claim is refused with `ERR_PROGRAM_BUDGET_EXCEEDED`". And `test_09`'s whole "PRD 2.8" immediate-consistency paragraph did not exist anywhere in the PRD — replaced with the real §2.11 ledger sentences and §3.1 counter definitions.
   - **The rejection ladder is PRD §2.8, not §2.12** (§2.12 is combustion safety). 11 docstrings across `test_09`/`test_11`/`test_12` were renumbered; the ladder rung-7 text was also being paraphrased and is now verbatim.
   - Six quotes had a sentence-ending period the PRD does not have (the PRD sentence continues), one skipped a sentence without an ellipsis, one dropped a leading "Otherwise", one added bold markers, and three cited the wrong section (§2.6→§3.3, §3.4→§2.12, §2.12→§3.6).
3. **Call arity** — every `api.*`, `f.*`, `fx.*` and bare helper call AST-bound against the real signatures: 0 problems.
4. **Imports** — 0 missing and 0 unused across all 13 test files and all 9 helpers (removed `Optional` from `factories.py`, `TEST_DRAFT` from `test_01`, three from `test_03`, one from `test_04`). Only `test_helpers/__init__.py` shows pyflakes noise, which is inherent to a re-export facade.
5. **Compilation** — all 22 files `py_compile` clean; `__pycache__` removed.
6. **Isolation** — nothing was written into `workspace/` (it holds only `INSTRUCTION.md`, `PRD.md` and the other agent's `implementation/`); `workspace/implementation/` was never read; no sibling task directory was read; no `pkill` was run.

One judgement call worth flagging: the corner instance `the_sealing_technician_may_not_issue_and_the_issuer_may_not_inspect` asserts `ok_status == INSPECTOR_VERIFIED`, which contradicts PRD §3.8 ("A passing spot check moves the claim from `SUBMITTED` to `APPROVED`"). The test asserts `CLAIM_APPROVED`, the PRD-derivable value.

## Step 6: Generate Implementation — 2026-09-04T17:35:30.000Z

Implementation complete at `workspace/implementation/`.

## Modules (3,235 lines total, all compile)

| File | Lines | Role |
|---|---|---|
| `start.sh` (exec, guarded pip install, `exec python3 app.py`) | – | launcher, `PORT` env, binds `0.0.0.0`, default 10000 |
| `requirements.txt` | – | `Flask==3.0.3` |
| `app.py` | 54 | app factory, blueprint registration, `ApiError`/`HTTPException`/`Exception` handlers |
| `errors.py` | 76 | 43 error ids → HTTP status + default messages |
| `store.py` | 145 | in-memory dicts only, logical clock, id/version/`_seq` helpers |
| `envelope.py` | 46 | `meta`/`response_type`/`data` envelope, array meta + `has_more` |
| `guard.py` | 230 | auth/authz, field validators, pagination |
| `calc.py` | 259 | enums, constants, all Decimal/ROUND_HALF_UP formulas |
| `lookup.py` | 251 | `*_or_404`, navigation, ledger/coverage roll-ups |
| `serialize.py` | 286 | one serialiser per entity |
| `cascade.py` | 202 | compensation identity, safety-hold cycle, the 4 multi-hop cascades |
| `routes/__init__.py` | 4 | `PREFIX = "/duct-sealing"` |
| `routes/clock.py` | 20 | 1 endpoint |
| `routes/programs.py` | 101 | 5 endpoints |
| `routes/projects.py` | 220 | 10 endpoints |
| `routes/duct_systems.py` | 88 | 4 endpoints |
| `routes/leakage_tests.py` | 169 | 5 endpoints |
| `routes/seal_jobs.py` | 507 | 12 endpoints |
| `routes/reports.py` | 189 | 4 endpoints |
| `routes/claims.py` | 227 | 6 endpoints |
| `routes/complaints.py` | 161 | 6 endpoints |

## Endpoint coverage: 53 / 53

Enumerated `app.url_map` and diffed it against the PRD §4 table programmatically: `declared 53, impl 53, missing [], extra []` (19 GET, 34 POST). Storage scan confirms no `sqlite`/`open(`/`json.dump`/`/tmp`/`pickle`, and a fresh `start.sh` boot on a clean port returns `total_count 0` for every collection with the clock at the default `2026-08-01T00:00:00.000Z` — no seeding.

## Verification

Two smoke servers (ports 41779, 45123) were exercised and killed by exact PID (`ss -ltnp` → `kill`); no broad pkill; no listeners left. Verified beyond the earlier happy/negative passes: full combustion verdict matrix (13 cases incl. every stated boundary — co==warning/==ceiling, spillage==60/61, depress==limit, draft==1.0, RANGE looser limits — 0 mismatches), the POST-FAIL hold + abort sweep, measurement-driven release requiring *every* post-hold POST test to be PASS (a lingering MARGINAL correctly keeps the hold), administrative release, the 4-hop exclusion cascade (job `ABORTED_EXCLUSION` → report `VOIDED` → claim `WITHDRAWN`, `committed_rebate_cents` released to 0), the 3-hop inspector-failure cascade and the full correction loop (`RETURNED_FOR_CORRECTION` → re-test booking reopens the system to `SEAL_PENDING` → re-issue restores `VERIFIED`/`warranty_suspended=false` → resubmit → PASS → APPROVED → PAID with committed→paid transfer), both segregation triples, the complaint DIAGNOSED↔BALANCING cycle with `-10.0` inclusive-boundary auto-resolve, and pagination meta/filters.

## PRD ambiguities resolved (interpretation chosen)

- **Rung order**: §2.8 ladder for cross-rung precedence; PRD prose order within a rung (e.g. start-injection checks `ERR_MASKING_INCOMPLETE` before certification; combustion coverage before the safety hold).
- **Sample on a PAUSED run**: accepted only when the point itself trips the cutoff (>1000.0 Pa), reconciling "sample outside INJECTING is invalid" with the transition table's `{INJECTING, PAUSED}`.
- **Resume carve-out**: any `ABORTED_SAFETY` run yields `ERR_INJECTION_PRESSURE_LIMIT`, evaluated before both the state rung and the hold.
- **No dedicated error exists** for: complete-seal without `target_reached` → `ERR_SEAL_JOB_INVALID_STATE`; pay without a passing spot check → `ERR_CLAIM_INVALID_STATE`; duplicate technician `license_number` and `masked_register_count != total_register_count` on pressurize → `ERR_INVALID_REQUEST`; raising/releasing a hold from the "wrong" project state → idempotent no-op (there is no `ERR_PROJECT_INVALID_STATE`).
- **Abort**: compensates the duct-system ledger only when `seal_status == "SEALING"` (so aborting a SCHEDULED run cannot wipe an earlier sealed run's ledger) but always bumps the system version.
- **Report drafting** has no job-state and no safety-hold gate (the SEALED requirement attaches to issuance from DRAFT only); **re-issue** from `CORRECTION_REQUIRED` skips the combustion gate and touches the duct system only if `seal_status != "VERIFIED"`.
- **Issuance combustion coverage** has no `gas_appliance_count > 0` short-circuit (unlike start-injection, where the PRD states it); it is skipped only when a program exists with `combustion_safety_required` false.
- **Schedule-conflict (rung 11) fires before the supersede effect**, so superseding needs a non-overlapping slot or another technician.
- **All array endpoints paginate** (§2.3 "every endpoint whose `response_type` is `array`"), including leakage-samples and airflow-readings whose SCAFFOLD input lists are `[]`.
- **`tolerance_pct`** is optional on diagnose with the 10.00 house default (PRD prose overrides the SCAFFOLD required-list); `certification_expires_at` on the certification endpoint stays required-but-nullable per the SCAFFOLD input list.
- **`_pause_reason`** is private (not serialised) and `abort_reason` is cleared on manual pause; `_hold_seq` (monotone insertion counter) implements "created strictly after the hold", since the logical clock can be frozen.

## Step 7: Run Tests and Iterate — 2026-09-04T17:55:00.000Z

Clean sweep. Done.

## Summary

**Iterations run:** 2

**Tests deleted:** none. Both failures were genuine test-artifact bugs, not PRD-silence cases.

**Tests deleted (PRD-silence):** n/a — zero deletions.

**Fixes applied to `test_helpers/`:**
- `test_helpers/factories.py` — `technician_payload()`: the default `license_number` was the hardcoded constant `"AS-4417"`, so any test that built two scenarios against one server (each registering its own technician) hit the PRD-required uniqueness rule on the second registration. PRD §3.1: *"a `license_number` that must be unique across all technician rows."* The factory now mints a fresh licence per call from an `itertools.count(4417)` counter, keeping the fixture consistent with PRD's uniqueness precondition. This was a STEP 2 fix — the implementation's uniqueness check is PRD-required and was left untouched. No test asserts on the uniqueness violation, and the two tests that need a specific licence (`test_04` line 190/634 `AS-5590`, `test_12` line 511 `AS-9999`) pass it explicitly and are unaffected.

**Fixes applied to `test_suite/`:**
- `test_suite/test_04_seal_job_scheduling.py` — `test_an_unreviewed_baseline_and_a_post_measurement_share_one_refusal`: an incidental setup assertion read `accepted_post["decision"]`, raising `KeyError`. PRD §3.3 names `decision` only as a *submission input* to the review endpoint ("The submission carries a `decision` of either `ACCEPT` or `REJECT`") and enumerates what review actually stamps on the row — `reviewed_by_user_id`, the note, the status, the `version` bump. `decision` is never declared a response-visible leakage-test attribute, so a faithful PRD-only implementer would correctly omit it from the serializer (COMPUTED-FIELD SILENCE). Per STEP 1c partial-coverage handling, only that uncovered sub-assertion was replaced — with the two PRD-verbatim facts it was standing in for: `status == "ACCEPTED"` (§3.3: *"`ACCEPT` moves the measurement from `RECORDED` to `ACCEPTED`"*) and `phase == "POST"`. The test's actual subject, the `ERR_TEST_PHASE_MISMATCH` assertion, was untouched.

**Fixes applied to `implementation/`:** none. No implementation defect surfaced; both failures traced to the test layer.

**Final sweep (all 8 rounds):** 105/105 passed, 0 failed, 0 errors in every round. All eight `results.$i.json` files are present on disk under `workspace/implementation/` (timestamped 17:38, ~32.5 KB each, complete JSON).

Note on the first sweep: the 2 failures were identical and deterministic across all 8 rounds — no flakiness signal, and no load-induced timeout or connection failures in either sweep. `worklog.md` was not modified.

**Orchestrator independent verification:** re-read all 8 `results.$i.json` directly — 8 files present, every round `passed=105 failed=0 total=105 errors=0`. Sweep artifacts confirmed real, not merely claimed.

**Step 8 decision:** the skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes. Step 7 applied 1 `test_helpers/` fix and 1 `test_suite/` fix, so the skip condition is not met and Step 8 runs. The `decision`-field COMPUTED-FIELD SILENCE in particular is a real PRD silence worth pinning.

## Step 8: Finalize PRD — 2026-09-04T17:46:00.000Z

`PRD_FINALIZED.md` is written. Both Step 7 items traced to real PRD under-determination; two in-place sentence extensions were the whole patch.

**Line counts:** PRD.md 415 lines → PRD_FINALIZED.md 415 lines (0.00% line delta; 2 of 415 lines revised in place, 0 added/removed).

**Changes**

- §3.1 — revise — pinned the error the duplicate-`license_number` path raises: registering a technician whose `license_number` equals an existing row's is `ERR_INVALID_REQUEST` (HTTP 400). PRD stated the uniqueness rule but named no error id, and the §5 catalogue has no uniqueness error, so a fresh implementer could equally have chosen 409 — `implementation/routes/programs.py:66-71`.
- §3.3 — revise — pinned that `decision` is input-only: not kept as a field on the measurement and absent from its representation, so the reviewer's choice is readable only from `status` — `implementation/routes/leakage_tests.py:151,159` + `implementation/serialize.py:111-133`.

**Per-edit pre-edit search log**

Edit 1 (§3.1, duplicate licence error)
- (a) Subject: `license_number` uniqueness enforcement and the error it yields.
- (b) Enumerated: `grep -rn "license_number" --include=*.py` over the whole implementation → only three sites. `routes/programs.py:57-81` `create_technician` (the only enforcement point; loops all `db.rows("technicians")` and raises `ApiError("ERR_INVALID_REQUEST", ...)`); `routes/programs.py:91-101` `record_certification` (mutates only `certification_status`/`certification_expires_at`, never re-checks or rewrites the licence, so no second uniqueness path exists); `serialize.py:56` (read-only). No PATCH/PUT technician endpoint exists in `routes/` or the §4 table, so the licence is immutable after registration. Also checked `guard.py:65` `vstr` — the licence is validated as a non-empty string before the uniqueness loop runs, but both failure modes are `ERR_INVALID_REQUEST`, so relative ordering is unobservable and I did not pin it.
- (c) Adjustment: scoped the sentence to *registration* rather than to any write of `license_number`, since only the create path enforces it; kept the wording as "equals that of an existing technician row" (plain equality, matching the `==` compare) instead of any normalising claim like case-insensitive; used "rejected as a malformed request" so it lands on rung 5 consistently with §2.8 without asserting a position relative to the other rung-5 field checks.

Edit 2 (§3.3, `decision` is input-only)
- (a) Subject: what the review submission persists, and the leakage-test field roster.
- (b) Enumerated: `grep -rn "\"decision\"\|'decision'" --include=*.py` → single site, `routes/leakage_tests.py:151`, where `decision` is validated via `venum` and then consumed only at line 159 (`status = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"`) and line 162 (`decision == "ACCEPT" and phase == "PRE"` → duct-system ledger). It is never written into `test[...]`. Read `serialize.py:111-133` `leakage_test` — the full roster is id/duct_system_id/phase/method/window bounds/status/test_pressure_pa/fan_ring_config/masked_register_count/measured_leakage_cfm/ambient_temp_f/normalized_leakage_cfm25/leakage_per_100_sqft/performed_by_user_id/reviewed_by_user_id/review_note/created_at/updated_at/version, with no `decision`. Also checked the row-initialisation dict at `routes/leakage_tests.py:52-70` (no `decision` key) and the other two writers of the same row (`pressurize`, `record`) so the claim holds for every leakage-test read path, not just the post-review one. Confirmed the same serializer backs the single read (`:75-79`) and the duct-system-scoped list, so there is no alternate projection that would expose `decision`.
- (c) Adjustment: wrote "not kept as a field of its own on the measurement" rather than "is not stored" — the decision *is* recorded, just encoded in `status`, and the looser phrasing avoids contradicting line 159. Deliberately scoped the negative claim to the leakage measurement alone and did not generalise to other input-only fields (`release_note` on project release, `pause_reason` on a run, both of which the impl likewise omits from their serializers) since those sit outside the Step 7 diff and a universal claim there would be new, unverified surface.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` returns 8 lines covering exactly the two revised lines (173 and 203); PRD_FINALIZED.md is 89111 bytes vs PRD.md 88635. The patch is real and minimal — not a byte-identical copy.

**Step 9 plan:** Step 9 will run as three sequential passes partitioned by implementation module over one shared `PRD_COMPLETED.md`. Pass 1 performs the `cp PRD_FINALIZED.md PRD_COMPLETED.md`; passes 2 and 3 must not copy, only edit in place. This partitioning is used because a single subagent cannot exhaustively scan 3,235 lines of implementation against a 415-line PRD without dropping coverage of the trailing modules.

## Step 9: Complete PRD — 2026-09-04T18:14:00.000Z

Step 9 was executed as three sequential file-partitioned passes over one shared `PRD_COMPLETED.md` (pass 1 did the `cp`; passes 2 and 3 edited in place only). Combined result: `PRD_FINALIZED.md` 415 lines / 89,111 chars → `PRD_COMPLETED.md` 417 lines / 110,403 chars (**+21,292 chars**, +2 lines). Totals across passes: **51 ambiguity-pins, 12 mismatch-revisions** (63 pins over 63 edit calls).

### Pass 1 — core infra (`app.py`, `errors.py`, `store.py`, `envelope.py`, `guard.py`, `lookup.py`, `serialize.py`, `calc.py`, `cascade.py`, `routes/clock.py`, `routes/programs.py`, `routes/projects.py`, `routes/duct_systems.py`)
417 lines / 99,335 chars (+10,224). 20 ambiguity-pins, 1 mismatch-revision.
- **§2.1** — insert — ambiguity — absent/empty/misspelled `X-User-Role` is `ERR_UNAUTHORIZED` (not 401/400); role match is exact and case-sensitive — `guard.py:37-39`
- **§2.2** — insert — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case-alphanumeric chars — `envelope.py:14`
- **§2.2** — revise — mismatch — `api_request_timestamp` is read from the **logical clock**, not wall time, so it repeats across responses — `envelope.py:18`, `store.py:86`
- **§2.3** — insert — ambiguity — non-integer / fractional `limit` or `offset` text is `ERR_INVALID_REQUEST`, not coerced — `guard.py:198-213`
- **§2.3** — insert — ambiguity — `created_at` ties (common under a frozen clock) break by write order, in sorts and in every "greatest `created_at`" selection; cross-room `reading_seq` ties break by write order — `store.py:128-142`, `lookup.py:112-114`
- **§2.4** — insert — ambiguity — canonical re-rendering of every echoed instant incl. client-supplied ones: non-zero offsets converted to UTC, naive read as UTC, sub-ms truncated — `store.py:57-83`, `serialize.py:21-27`
- **§2.4** — insert — ambiguity — roll-ups are derived on read, so duct-system create/screening never bumps the project's `version`/`updated_at` and run lifecycle never bumps the technician's — `serialize.py:59,67,148,238`, `lookup.py:147-190`, `projects.py:134-135`
- **§2.4** — insert — ambiguity — clock set is unconditional (backwards allowed), `to_iso8601` required, and `data` is exactly `{current_utc, to_iso8601}` at HTTP 200 — `routes/clock.py:17-20`
- **§2.5** — insert — ambiguity — identifier filters match literally (unknown id ⇒ empty page, never 404); enum filters 400 on out-of-set values; undeclared query params ignored — `guard.py:217-230`, `projects.py:68-72`
- **§2.6** — insert — ambiguity — decimals emitted as bare JSON numbers with trailing zeros dropped (`12.50`→`12.5`, `400`→`400.0`) — `serialize.py:9-18`
- **§3.1** — insert — ambiguity — `min_reduction_pct` rounded half-up to 2dp **on storage** — `programs.py:42`
- **§3.1** — insert — ambiguity — certification recording requires both keys (`certification_expires_at` may be explicit `null`); legal from/to any standing, no state check — `programs.py:96-99`
- **§3.2** — insert — ambiguity — `asbestos_screening_result` and non-empty `lab_reference` both mandatory even for `PENDING` — `duct_systems.py:31-32`
- **§3.2** — insert — ambiguity — both disqualifiers at once ⇒ `STRUCTURAL_DAMAGE`; that structural exclusion rewrites the system only (no ledger compensation, no cascade hops); result `PENDING` behaves exactly like `SUSPECT` — `duct_systems.py:47-58`
- **§3.2** — insert — ambiguity — the exclusion cascade does not rewrite the program row, so its `version`/`updated_at` do not move; each swept row gets exactly one increment — `cascade.py:152-160`
- **§3.2** — insert — ambiguity — manual exclusion stamps `abort_reason` as the supplied `exclusion_reason` verbatim, and stamps no screening fields — `duct_systems.py:72`, `cascade.py:136-137`
- **§3.4** — insert — ambiguity — hold-driven `INJECTING`→`PAUSED` leaves `pause_count` and `stall_flag` untouched; raising a hold on an already-held project re-stamps the reason, restarts the release window and bumps `version` — `cascade.py:34-51`, `projects.py:85-87`
- **§3.4** — insert — ambiguity — "created strictly after the hold" is decided by write order not `created_at`; only a `PASS` triggers the release sweep; `release_note` is mandatory but appears in no response; release on an `ACTIVE` project succeeds and still bumps `version` — `cascade.py:50,63-77`, `projects.py:96-98`
- **§3.6** — insert — ambiguity — the cutoff hold pauses nothing; other `INJECTING` runs under the project stay `INJECTING` — `cascade.py:108-112`
- **§3.6** — insert — ambiguity — equal `elapsed_seconds` across the window ⇒ `seal_rate_cfm_per_min` null and no stall — `calc.py:227-229` (consumed at `seal_jobs.py:354`)
- **§3.7 / §3.8** — insert — ambiguity — zero-denominator outcomes: system-basis 0.00 when `pre_leakage_cfm25` is 0; whole-house 0.00/0.00 when the pre-side total is 0 or the candidate set is empty; inspector variance 0.00 when both sides are 0 else 100.00 — `calc.py:126-129,151-153,251-252`
- **§5** — insert — ambiguity — off-catalogue transport identifiers `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) in the standard error envelope; unparseable/non-object bodies become `{}` (so payload-free endpoints still succeed); trailing slashes equivalent — `app.py:19,30-44`, `guard.py:46-52`

Cross-slice care: verified all five other route modules use the same `qstr`/`qenum`/`pagination`/`array_response` helpers before writing the global filter and pagination pins, verified no `touch(technician)` outside `programs.py` before pinning the derived-roll-up rule, and verified `seal_jobs.py:354` guards on a null seal rate before pinning the divide-by-zero clause.

### Pass 2 — `routes/leakage_tests.py` + `routes/seal_jobs.py`
417 lines / 105,784 chars (+6,449, 0 new lines). 17 ambiguity-pins, 7 mismatch-revisions. Pass-1 edits verified still present (§2.1 role match, §2.2 `req_` width and logical-clock timestamp).
- §2.7 ¶112 — insert — ambiguity — `expected_duct_system_version` must be a non-negative integer; absent/non-integer/negative is rung-5 400, not 412 — `seal_jobs.py:112`
- §2.8 rung 9 — revise — mismatch — rung-9 errors are evaluated in exactly the listed order, and the rung also covers pressurizing a leakage measurement — `seal_jobs.py:124-136`, `leakage_tests.py:103`
- §2.10 ¶145 — revise — mismatch — baseline is governed by the **last-written acceptance**, not the greatest `created_at` — `leakage_tests.py:162-166`
- §2.12 ¶165 — revise — mismatch — the resume carve-out keys on the `ABORTED_SAFETY` **status alone**, so a combustion-fail abort also answers `ERR_INJECTION_PRESSURE_LIMIT` — `seal_jobs.py:407`
- §3.3 ¶197 — insert — ambiguity — `performed_by_user_id`/`reviewed_by_user_id`/`review_note` also null at creation; reservation is gated on neither eligibility nor safety hold — `leakage_tests.py:52-71`
- §3.3 ¶201 — insert — ambiguity — masked-count mismatch (short *or* excess) is `ERR_INVALID_REQUEST` at rung 5 and therefore outranks the `DRAFT` state check; `PENDING_SCREENING` pressurizes normally — `leakage_tests.py:91-105`
- §3.3 ¶203 — insert — ambiguity — `ambient_temp_f` is required and may be zero or negative — `leakage_tests.py:121`
- §3.3 ¶205 — insert — ambiguity — empty `review_note` stored verbatim, omitted note stored as null — `leakage_tests.py:152`
- §3.3 ¶205 — insert — mismatch — the ledger stamp is unconditional at acceptance time; last-accepted PRE wins even with the earlier `created_at` — `leakage_tests.py:162`
- §3.5 ¶229 — insert — ambiguity — a re-test of a parent still `VERIFIED` (not `RETEST_REQUIRED`) reopens nothing, though the system's `version` still bumps — `seal_jobs.py:191-193`
- §3.5 ¶231 — insert — ambiguity — labels are free text never checked against the system; empty array accepted and still transitions/bumps; intra-call duplicates deduped — `seal_jobs.py:238-254`
- §3.5 ¶233 — insert — mismatch — `seal_status` is set to `SEALING` unconditionally (a `SEALED`/`VERIFIED` system is driven back), while the ledger fields stay as the earlier run left them — `seal_jobs.py:284`
- §3.5 ¶233 — insert — ambiguity — gate (a) is skipped entirely for `gas_appliance_count` 0 (even with a `FAIL`), and a `FAIL` is reported before missing coverage — `seal_jobs.py:62-70`
- §3.5 ¶233 — insert — ambiguity — the two intra-rung orders: combustion coverage before safety hold (rung 8), masking completeness before certification (rung 10); masking is a pure count comparison so over-masking is also `ERR_MASKING_INCOMPLETE` — `seal_jobs.py:269-279`
- §3.6 ¶237 — insert — ambiguity — appending requires `INJECTING` else `ERR_SEAL_JOB_INVALID_STATE`, with a cutoff-tripping point the sole exception accepted from `PAUSED` — `seal_jobs.py:305-308`
- §3.6 ¶239 — insert — ambiguity — the 201 body is the curve point with its exact nine fields, not the updated run — `seal_jobs.py:363`
- §3.6 ¶241 — revise — mismatch — the cutoff also fires from `PAUSED`; `pause_count`/`stall_flag` are left alone and the run keeps the curve state the point wrote — `seal_jobs.py:350-353`
- §3.6 ¶245 — insert — ambiguity — `pause_reason` is mandatory non-empty, is not a field of the run and appears in no response body — `seal_jobs.py:385,395`
- §3.6 ¶247 — insert — ambiguity — `sealant_lbs_used` required and non-negative; a `target_reached`-false completion is refused with the same `ERR_SEAL_JOB_INVALID_STATE` — `seal_jobs.py:435,441`
- §3.6 ¶249 — revise — mismatch — abort is open to **any** `FieldTechnician` (no `technician_id` comparison) or `ProgramAdmin`; `abort_reason` mandatory non-empty — `seal_jobs.py:465-468`
- §3.6 ¶249 — revise — mismatch — compensation is conditional on the system reading `SEALING`, so an earlier run's `SEALED`/`VERIFIED` ledger is never rewritten, yet the system's `version` bumps either way — `seal_jobs.py:483-485`
- §3.9 ¶295 — insert — ambiguity — homeowner fields are mandatory non-empty with no email-format check; a second registration is accepted and re-stamps both instants — `seal_jobs.py:494-506`

Deliberately not pinned: the eligibility re-checks inside `masks`/`start-injection`/`resume` are unreachable (booking requires `ELIGIBLE`, eligibility never regresses, and the exclusion cascade aborts every open run), so pinning an error id there would have invented behavior.

### Pass 3 — `routes/reports.py` + `routes/claims.py` + `routes/complaints.py`
417 lines / 110,403 chars (+4,619, 0 new lines). 14 ambiguity-pins, 4 mismatch-revisions. Pass-1 and pass-2 edits verified still present (§2.4 derived-roll-up paragraph, §3.7 zero-denominator clause; §3.5 unconditional `seal_status`, §3.6 abort-role widening).
- §2.7 — insert — ambiguity — `expected_seal_job_version` held to the same rung-5 discipline as its duct-system twin (absent/null/non-integer/negative ⇒ 400, not 412) — `routes/reports.py:51`
- §3.7 ¶1 — revise — mismatch — "Once a run is `SEALED`… drafts" implied a draft-time state gate; pinned that drafting imposes **no** run-status requirement and no combustion / safety-hold / eligibility gate (only the two rung-9 coherence checks) — `routes/reports.py:36-71`
- §3.7 ¶1 — insert — ambiguity — a superseded earlier `DRAFT` report is itself rewritten (`updated_at` re-stamped, own `version` +1); `ISSUED`/`CORRECTION_REQUIRED`/`VOIDED` siblings untouched — `routes/reports.py:89-93`
- §3.7 ¶4 (issue) — revise — mismatch — prose ordered the guarantee before combustion and ended "Finally the project's `safety_hold`"; pinned the real order (report state → run `SEALED` w/ `ERR_SEAL_JOB_INVALID_STATE` → combustion → safety hold → guarantee last), that a `FAIL` beats a coverage shortfall, that the post-phase sweep is **never** skipped at `gas_appliance_count` 0 (unlike gate (a)), and `signature_note` mandatory non-empty — `routes/reports.py:19-32,147-177`
- §3.7 ¶6 (re-issue) — insert — ambiguity — neither the `SEALED` requirement nor the post-phase combustion sweep is re-applied; the parent-retest close applies here too; the duct system is left untouched when its `seal_status` already reads `VERIFIED` — `routes/reports.py:161,169,179-188`
- §3.8 ¶1 — insert — ambiguity — `documentation_bundle_ref` mandatory non-empty on submit and resubmit; no uniqueness rule over `verification_report_id`, so a second claim on the same report is accepted and commits its own money — `routes/claims.py:56,173`
- §3.8 ¶1 — insert — ambiguity — the rung-8 safety-hold gate is evaluated **before** the rung-9 program-mismatch check despite being described last — `routes/claims.py:63-69`
- §3.8 ¶8 — insert — ambiguity — a new claim's spot-check fields and `payment_reference` open null; neither the report nor the project is rewritten by submission — `routes/claims.py:75-92`
- §3.8 ¶9 — insert — ambiguity — `spot_check_leakage_cfm` ≥ 0 (0 allowed), `spot_check_pressure_pa` strictly > 0 — `routes/claims.py:137-138`
- §3.8 ¶9 — insert — ambiguity — the report-must-be-`ISSUED` condition is checked right after the claim's own status and reported as `ERR_REPORT_INVALID_STATE` — `routes/claims.py:143-145`
- §3.8 ¶10 — insert — ambiguity — a passing spot check does not rewrite the program row, so its `version`/`updated_at` do not move (asymmetric with the failing path) — `routes/claims.py:157-159`
- §3.8 ¶11 — insert — ambiguity — resubmit names `ERR_CLAIM_INVALID_STATE` and `ERR_REPORT_INVALID_STATE` and fixes their relative order — `routes/claims.py:175-181`
- §3.8 ¶12 — insert — ambiguity — `payment_reference` mandatory non-empty; the `requires_inspector_verification` gate is reported as `ERR_CLAIM_INVALID_STATE` — `routes/claims.py:211,216-220`
- §3.9 ¶3 — insert — ambiguity — `room_label` and `reported_by` mandatory non-empty; logging rewrites only the complaint (project row and posture untouched) — `routes/complaints.py:20-45`
- §3.9 ¶4 — insert — ambiguity — `tolerance_pct` is the one optional field; omitted or null it is **stored as 10.00**, not left null; `diagnosis_code` stays mandatory — `routes/complaints.py:62-70`
- §3.9 ¶5 — insert+revise — mismatch — "1-based **monotone** position" softened and pinned: uniqueness per (complaint, room) is the whole constraint, any integer ≥ 1 is accepted, greatest recorded seq governs — `routes/complaints.py:104,112-116`
- §3.9 ¶5 — insert — ambiguity — readings are legal from every status but `RESOLVED`, and while `tolerance_pct` is still null the 10.00 house default governs `within_tolerance` — `routes/complaints.py:109-122`
- §3.9 ¶6 — insert — ambiguity — `damper_adjustment_note` mandatory non-empty — `routes/complaints.py:81`
- §3.9 ¶7 — revise — mismatch — "the technician must re-diagnose and re-enter balancing" was impossible (diagnose is `OPEN`-only); now says the dampers are re-adjusted and balancing re-entered via the balance transition, never re-diagnosed — `routes/complaints.py:66,138-141`

### Orchestrator final verification
- `PRD_COMPLETED.md` is 110,403 bytes vs `PRD_FINALIZED.md` 89,111; md5 `c778813f…` vs `fd8f832d…` — **not byte-identical**, so the scan demonstrably ran.
- `diff PRD_FINALIZED.md PRD_COMPLETED.md` = 108 changed lines (54 revised line-pairs).
- §4 still lists exactly **53** endpoints, §5 exactly **43** error rows; the tail ends on the complete final `ERR_PROGRAM_BUDGET_EXCEEDED` table row at a real section boundary.
- Step 9 modified no code, so the Step 7 green sweep (8/8 rounds, 105/105) remains valid.
