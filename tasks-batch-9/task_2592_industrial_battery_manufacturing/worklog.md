# Worklog — task_2592_industrial_battery_manufacturing

## Step 1: Create task directory — 2026-09-03T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2592_industrial_battery_manufacturing` and its `workspace/` subdirectory. Index 2592 was pre-assigned by the orchestrating prompt; no scan of `./tasks/` was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-03T18:20:00.000Z

Note: the first Step 2 subagent (af5f7c9) was cut off by an API timeout after ~65 min having written zero files. Rather than respawning fresh, I resumed the same agent via SendMessage with an explicit chunked-append protocol (~150-250 line `cat >>` appends, `wc -l` after each) so progress became durable message-to-message. It then completed all three artifacts.

Subagent summary, verbatim:

All three scaffold artifacts are complete and the lint is clean.

**Files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_2592_industrial_battery_manufacturing/`)

| file | lines |
|---|---|
| `SCAFFOLD.yaml` | 3608 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2639 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3885 |

**Surface (§1.0–§1.7)**: 14 entities / 70 endpoints / 61 error codes / 10 calculations / 12 state machines / 2 concurrency rules / 52 validation rules / 7 roles; `difficulty_level: beyond_expert`, `role_model: segregation_of_duties`, layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy, rate_threshold_triggers. `SCAFFOLD.yaml` contains neither design key; each design file has exactly one top-level key.

**§1.8**: 9 rule_ids × 21 instances (all full recipes, no stubs) — dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant (>=2 instances each).

**§1.9**: 9 sections, 64 instances = **41 full + 23 `excluded_because` stubs**
entities 9+1 - state_machines 6+5 - calculations 5+4 - validations 4+3 - endpoints 5+0 - errors 4+6 - rbac 5+0 - cross_cutting_layers 2+4 - consistency_model 1+0.
Sections finished this pass: `rbac` (per-role exclusive op permitted; shared-read role-list boundary incl. the one role denied on `GET /production-lots`; design-review SoD that tracks the *current* submitter across a revision loop; lot-release SoD keyed on `last_test_recorded_by_worker_id`; 13 wrong-role probes proving priority 2 beats 3/4/7), `cross_cutting_layers` (both OCC rules in full — lot OCC as row-scoped equality outranking the env-hold gate, unit OCC outranking the warranty-state and event-time gates — plus stubs for the other four layers), and `consistency_model` (one `immediate` instance: run create -> ledger/posture/list all moved in the same session, abort releases immediately).

Verified programmatically: names unique across both design files (no collisions, no intra-file dupes), every stub cites an existing §1.8 instance (normalized to the SKILL's `rule_id / instance_name` form), no stub carries a `test_recipe`, every full instance has `distinguishing_aspect` + all four recipe keys.

Lint verdict, verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    70
  §1.1 entities declared:     14
  §1.8 instances scanned:     21
  §1.9 instances scanned:     41
  Calls scanned (§1.8+§1.9):  1123

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Two consistency fixes landed in `SCAFFOLD.yaml` while auditing (§1.9 doubles as a §1.5 audit): the `PATCH /cell-designs/{id}` side effect now matches §1.2 (a CHANGES_REQUESTED design is moved back to DRAFT by the edit), and `GET /production-lots/{id}/quality-summary` now states that `release_blocked_by` is actor-independent and reads `"NONE"` when only the SoD/job-class gates remain. No sibling task directory was read at any point.

## Step 3: Copy shared files — 2026-09-03T18:21:00.000Z

Copied `./INSTRUCTION.md` (53 lines) to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-03T18:40:00.000Z

Orchestrator truncation guard (per the known doc-generator failure mode): verified independently of the subagent's own claims — PRD.md is 516 lines / 122264 chars, the tail ends on the final row of the §5 error table (`ERR_LEAD_INVENTORY_INSUFFICIENT | 409`), i.e. a real section boundary, not mid-sentence. Programmatic cross-check against SCAFFOLD.yaml: 70/70 endpoints present (0 missing), 61/61 real error codes present. The one scaffold `ERR_` token absent from the PRD is `ERR_XXX`, which is only the placeholder inside the scaffold's response-envelope example, not a declared code. No regeneration needed.

Subagent summary, verbatim:

PRD generation complete.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2592_industrial_battery_manufacturing/workspace/PRD.md` — **516 lines**, ends at a real section boundary (final row of the §5 error table, `ERR_LEAD_INVENTORY_INSUFFICIENT | 409`). No audit footer in the document.

## Section outline
```
# Industrial Battery Manufacturing API — Product Requirements Document
## 1. Introduction
## 2. Global Specifications & System-Wide Principles          (11 subsections)
   2.1  User and Role-Based Access Control
   2.2  API Response Structure          (emitted byte-verbatim)
   2.3  Pagination
   2.4  Resource Identity, Timestamps and the Logical Clock
   2.5  Numeric Precision, Rounding and Monetary Units
   2.6  Optimistic Concurrency on Lots and Units
   2.7  The Plant Compliance Posture Gate
   2.8  Cascades, Compensations and Conserved Quantities
   2.9  Path Resolution and Nested Sub-Resources
   2.10 Validation Order and the First-Failure Rule
   2.11 Segregation of Duties as a Structural Rule
## 3. Business Logic & Workflows                              (9 subsections)
   3.1 Registering a Plant and Its Environmental Envelope
   3.2 Enrolling Workers, Monitoring Exposure and Medical Removal
   3.3 Authoring, Reviewing and Superseding Cell Designs
   3.4 Opening a Lot, Advancing Its Stages and Holding It
   3.5 Formation Charging: Bay Windows, Energy Pricing and the Emission Quota
   3.6 Assembling Batteries and Verifying Them on Two Independent Axes
   3.7 Acceptance Sampling, Chamber Scheduling and Lot Disposition
   3.8 Sizing a Motive-Power Fleet and Matching a Charger
   3.9 Shipping Units, Field Service, Warranty Settlement and Core Return
## 4. Endpoint Definitions        (4-column table, 70 rows)
## 5. Error Code Catalogue        (2-column table, 61 rows)
```

## Grep-verified inventory
- **Endpoints: 70 / 70.** Every scaffold `method + path` pair matches a §4 table row exactly (`| METHOD | \`path\` |`); 0 missing.
- **Error codes: 61 / 61** in the §5 table, and **61 / 61 also appear in §1–§3 prose** (not table-only), so every code is behaviourally motivated somewhere.
- Structured computed-read output field names: 0 missing. Entity enum values: 0 missing. Fenced code blocks appear only inside §2.2.

## Hard Contract reports

```
Field coverage check:
- entities[].fields: 181 required, 181 present, 0 missing
- endpoints[].request_body: 110 required, 110 present, 0 missing
- endpoints[].query_params: 40 required, 40 present, 0 missing
  (union of the required identifier set: 202 names, 202 present, 0 missing)
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 52 checked, 52 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_lot_version / expected_battery_unit_version + ERR_STALE_LOT_VERSION / ERR_STALE_BATTERY_UNIT_VERSION all named, plus both normative version-bump scopes), 0 missing
- state_machines[].transitions: 53 checked across 12 machines, 53 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed, 0 missing
- validations[] conditions: 52 checked, 52 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 70 endpoints checked, all side effects and every applies_to scope enumerated (§2.10 ladder names the endpoint list per code), 0 missing
- entities[].fields[] structured content: 14 entities / 181 fields checked, all reconstructible from prose (defaults, bounds, precision, enum domains), 0 missing
- sibling-branch symmetry: 11 groups checked (AIR/BLOOD exposure variants; SUBMIT/APPROVE/REQUEST_CHANGES; HOLD/RELEASE_HOLD; provisional_nameplate/final_metered pricing; SCHEDULED-abort/CHARGING-abort; TORQUE/INSULATION_RESISTANCE; CAPACITY/CYCLE_LIFE; RELEASE/QUARANTINE/RETEST/SCRAP; ACCEPT/WITHDRAW; the four maintenance event types; RECYCLE/REJECT), 11 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1097
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Scaffold contradictions resolved (decisions written into the PRD)
1. `FormationRun.charge_factor_used` references a `charge_factor_override` input that no endpoint accepts -> followed the endpoint contract: the factor is frozen from the lot's pinned design `formation_charge_factor`; no override field invented.
2. `BatteryAssembly.torque_spec_nm` / `ir_min_megaohm` are marked `source: computed` from constants that exist nowhere, yet appear in the creation input list -> described as supplied on the payload and frozen; no numeric constant tables invented.
3. Sampling-plan counter reset: the `ASSEMBLY -> LOT_TESTING` transition claims a counter reset while the endpoint's own side effects say a draw does **not** reset -> reconciled by noting the reset is a no-op on the first draw (a lot arriving from `ASSEMBLY` already has the counters at their defaults), that redraws leave them intact, and that `RETEST` is the sole counter-zeroing operation; the derived yield is separately scoped to the current plan window.
4. `BatteryUnit.list_price_cents` is un-suffixed in the ship input list but the entity gives it a default -> stated both: carried on the payload, strictly positive when supplied, defaulting to the pinned design's list price when omitted.

Constraints honoured: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling `task_*/` directory was read.

## Step 6: Generate implementation — 2026-09-03T20:35:00.000Z

(Steps 5 and 6 were launched concurrently; Step 6 returned first, so it is logged first. Step 5's entry follows below.)

Subagent summary, verbatim:

Implementation complete for `task_2592_industrial_battery_manufacturing`.

## Location
`/home/ubuntu/github/CodingPRD/tasks/task_2592_industrial_battery_manufacturing/workspace/implementation/`

## Layout and line counts

| file | lines |
|---|---|
| `start.sh` | 10 |
| `requirements.txt` | 1 (Flask==3.0.3) |
| `app.py` | 99 |
| `authz.py` | 128 |
| `errors.py` | 106 |
| `helpers.py` | 135 |
| `response.py` | 44 |
| `store.py` | 128 |
| `util.py` | 138 |
| `validation.py` | 180 |
| `services/constants.py` | 86 |
| `services/energy.py` | 69 |
| `services/exposure.py` | 55 |
| `services/lot_service.py` | 161 |
| `services/plant_service.py` | 245 |
| `services/sizing.py` | 132 |
| `services/warranty.py` | 109 |
| `routes/assemblies.py` | 188 |
| `routes/chargers.py` | 171 |
| `routes/clock.py` | 19 |
| `routes/designs.py` | 230 |
| `routes/facilities.py` | 137 |
| `routes/lots.py` | 360 |
| `routes/plants.py` | 177 |
| `routes/runs.py` | 242 |
| `routes/tests.py` | 187 |
| `routes/units.py` | 392 |
| `routes/workers.py` | 234 |

**Total 4163 lines** (4152 Python + `start.sh` + `requirements.txt`). No stubs, no `NotImplemented` branches; `__pycache__` removed.

## Endpoint registration
`app.py` prints `registered endpoints: 70` at startup (from `app.url_map`, excluding static/HEAD/OPTIONS) — a 1:1 match with the scaffold's 70 declared endpoints across 14 entities. All 61 error codes are raised from the code; no undeclared error code was invented (e.g. a no-op `PATCH /plants/{id}/permit` returns 200 because the PRD declares no error for it).

## Fresh-boot behavior (required by `--isolation per-test-server`)
A cold `PORT=17593 bash start.sh` came up in under 6 s, printed 70 endpoints, and served empty collections with the logical clock at `2026-08-01T00:00:00.000Z`. Storage is in-memory dicts only: every `db.insert` lives inside a request handler (verified by grep), and there is no sqlite/JSON/`/tmp`/pickle usage anywhere. `start.sh` installs Flask only when the import fails, to avoid pip contention across concurrent reboots.

## Smoke results (ports 17592/17593, then killed by PID/port only — no pattern kills; both ports confirmed free)
**80 assertions across 4 scripts, 0 implementation failures.** (Three earlier "failures" were bugs in my throwaway smoke scripts: a wrong route name `/plants/{id}/permit-status`, a wrong field `hold_action`, and an expectation of an undeclared permit no-op error.)

Full happy-path chain exercised end to end: plant -> 7 workers -> design create/submit/approve (self-approve correctly 409 `ERR_SEGREGATION_OF_DUTIES`) -> lot -> bay -> formation run (pricing, bay-cooldown conflict 409, start, complete PASS) -> assembly -> torque/IR verifications -> CERTIFIED -> sampling plan -> 4 capacity/cycle-life tests -> RELEASE by a second inspector -> unit shipment -> maintenance logs -> warranty claim/adjudication -> core-return SHIP/RECEIVE/RECYCLE -> fleet sizing ACCEPT.

Computed figures observed (all matching hand-checked PRD arithmetic):
- Formation run provisional `{estimated 345.60 kWh, peak_h 2.5, offpeak_h 2.0, cents 4973, reserved_g 864.00, factor 1.2}`; final `{actual_peak_h 2.5, actual_offpeak_h 8.0, cents 4581, consumed_g 1000.00}`.
- Sampling plan `sample_size 4, acceptance_number 0, revision 1`; lot yield `93.77` from per-test yields 95.00/80.00/100.17/99.90 (per-test round, then mean rounded again).
- Warranty `{months_in_service 3, usage_fraction 0.1333, watering_compliance_ratio 1.0, decision PRORATED, credit 736695 cents}`.
- Lead mass balance closes at `lead_mass_variance_kg 0.0` with `core_lead_variance_kg -8.41`; core deposit liability 12500 -> 0 only on RECYCLE (receipt deliberately does not settle it).
- Fleet sizing `{daily 12.0 kWh, derate 1.20, reserve 1.15, required_ah 432, charge_hours 5.52, 20 batteries, 10 chargers, capital 19,500,000 cents}`; `ERR_NO_ELIGIBLE_CELL_DESIGN` and `ERR_NO_CHARGER_MATCH` both reachable and persist nothing.

Cascades and gates verified live: exposure sample -> `AIR_TWA_90D` index 400.0 -> medical removal -> plant `RESTRICTED` -> acting worker blocked 403 `ERR_ACTOR_MEDICALLY_REMOVED` -> blood sample -> clearance -> back to `OPEN`; permit SUSPENDED -> `FROZEN` + lot held with `hold_reason PERMIT_SUSPENDED` + advance blocked `ERR_PLANT_FROZEN` -> reinstatement lifts the hold; operator hold/release round-trip with `ERR_LOT_ENV_HELD` in between; OCC replay returns 412 on both `warranty-claims` and `sampling-plans`; envelope, pagination meta (`limit`/`offset`/`total_count`/`has_more`), 401/403/404/405/422 shapes all conform to PRD §2.2.

One ordering fix made this session (carried from the earlier review): `endpoint()` gained a `schema_check=` hook so tier-3 discriminator/coherence rules (exposure samples, design plate coherence, assembly verifications, maintenance logs, core RECEIVE mass) run before tier-4 actor resolution rather than inside the view.

## Step 5: Generate unit tests — 2026-09-03T21:05:00.000Z

Orchestrator placement check (per a known Step 5 failure mode where test dirs land inside workspace/): `test_helpers/` and `test_suite/` are both at the task root, and `find workspace -type d -name 'test_*'` returns nothing — no move needed. `python3 -m pytest test_suite --collect-only -q` collects 89 tests; 89 `def test_` lines and 89 `Design:` tags across the suite.

Subagent summary, verbatim:

Complete. Both output directories are final at the task root; `workspace/` holds only `INSTRUCTION.md`, `PRD.md`, `implementation/` (never read).

## Per-file line counts

`test_helpers/` (unchanged this session): `__init__.py` 6, `api_client.py` 354, `api_errors.py` 147, `assertions.py` 315, `constants.py` 293, `factories.py` 464, `fixtures.py` 590, `test_users.py` 91, `types.py` 532.

`test_suite/`: `conftest.py` 43, test_01 317, test_02 303, test_03 343, test_04 199, test_05 401, test_06 173, test_07 183, test_08 331, test_09 240, test_10 446, test_11 253, test_12 419, test_13 478, test_14 475, test_15 253, test_16 108. Total 7757 lines across both dirs.

## Tests and coverage

- **89 test functions**, and `pytest --collect-only` from the task root collects exactly 89 (no stray collection from `test_helpers/`).
- Every test carries **exactly one** `Design:` line (verified per file: `def test_` count == tag count), and **all 89 tags resolve to a real yaml `name:`**; none points at an `excluded_because:` stub.
- Queue A: all **21** difficulty instances translated, **46** tests, every instance has **>=2** tests (the SKILL.md queue-A minimum).
- Queue B: all **41** non-stub corner instances translated, **43** tests. The 23 `excluded_because:` stubs were cross-checked (each resolves to the queue-A instance that owns the assertion) and deliberately not translated.
- **Instances skipped: 0.**
- PRD-citation audit: 166 quoted spans extracted from docstrings, **all** are verbatim substrings of `workspace/PRD.md` under the documented ASCII rendering (em dash to `--`, arrow to "to", code-span backticks normalised).
- `pyflakes` is clean except the intentional `test_suite/conftest.py:16` side-effect import of `test_helpers.api_errors` (registers the error to HTTP-status map; carries `# noqa: E402,F401`).

## Work done this session

- `test_13_error_catalogue.py` (4 tests) — the four `errors` instances.
- `test_14_role_permissions_and_segregation.py` (5 tests) — all five `rbac` instances.
- `test_15_optimistic_concurrency.py` (2 tests) — both `cross_cutting_layers` OCC instances (lot sampling-plan token, unit warranty-claim token).
- `test_16_consistency_model.py` (1 test) — the `consistency_model` instance.
- Two extra tests appended to `test_05` to lift `lot_state_beats_emission_budget_on_run_scheduling` and `env_hold_beats_bay_window_conflict_on_run_scheduling` from 1 test to 2 (queue-A minimum was violated). The new angles: the state refusal survives raising the permit to 100000.00 while the FORMATION control lot then schedules at 255.00 g / ratio 0.0026; and the hold (tier 12) also masks `ERR_WINDOW_INVALID` (tier 15) on a zero-length window, which surfaces only after the hold is lifted.

## Findings worth relaying

- **Collection bug fixed:** `test_12_endpoint_surfaces.py` imported the factory `test_chamber_payload` at module level, and pytest was collecting it as a test (90 collected, one of them a factory that would have errored on a missing fixture). Now imported as `test_chamber_payload as chamber_create_payload`.
- **Deliberate deviation, rbac instance 5:** the yaml has Dana record all three results and Eli release. I instead let Dana record t1 (441.8) and t2 (442.1) and Eli record t3 (372.0 @ 1350), so the blocked identity is the *most recent* recorder (Eli) while Dana — who verified both axes, drew the plan, scheduled the tests and recorded two earlier results — legally releases. Same codes, sharper probe of "the inspector who recorded the **last** test".
- **Yaml defect worked around (test_13, `state_invalid` errors instance):** its recipe draws a sampling plan with only a PENDING assembly (PRD requires >=1 CERTIFIED on the first draw) and records verifications after LOT_TESTING (PRD line 274 forbids it but names no error code, so it is not uniquely derivable). Restructured: all verification/rework refusals fire in ASSEMBLY, a second assembly is certified to enable the draw, and only the LOT_TESTING-scoped refusals follow.
- Deviations carried from earlier sessions (all still in place): `invariant_e1` provisional charge is 2210, not the yaml's 2167; `formation_run_start_requires_open_plant_posture` omits `bay_status == OCCUPIED` and moves its 45.0 blood sample to 2026-08-31T09:00Z; the PATCH-from-`CHANGES_REQUESTED` corner asserts `DRAFT` (PRD line 216) against the yaml's `CHANGES_REQUESTED`; the warranty ladder ships at the default clock (an explicit backdated `shipped_at` is unauthorised); the fleet-analysis `lines` key is probed indirectly because the PRD does not name the field.
- HTTP-status disagreements between the yamls and the PRD table (e.g. `ERR_ACTOR_JOB_CLASS_MISMATCH` 409 vs 403) are immaterial: `validate_error` consults the registered map in `test_helpers/api_errors.py`, which follows the PRD.

## Step 7: Run tests and iterate — 2026-09-03T22:15:00.000Z

Orchestrator verification, independent of the subagent's claims: all eight `workspace/implementation/results.{1..8}.json` exist and parse, each reporting `89/89` with `failed=0, errors=0`; `workspace/sweep.log` contains no `Terminated` (so no reaping artifact). Step 8 is therefore NOT skipped — Step 7 applied 2 `implementation/` fixes plus test-layer fixes.

Subagent summary, verbatim:

All 8 rounds pass 89/89. Done.

## Summary

**Iterations run:** 3 (initial 8-round sweep -> 2 single-round probes for fast triage -> final 8-round sweep).

### Tests deleted
None. One assertion was struck from an otherwise-sound test (see below); no test was deleted, skipped, or weakened.

### Fixes applied to `test_helpers/`
- **`constants.py`** — `PLANT_SITE_CODE` was `"PLT-RIV"`. PRD §3.1 requires `site_code` be "four to twelve uppercase alphanumeric characters"; the hyphen made every fixture's plant registration a 422, failing **all 89 tests** in every round. Changed to `"PLTRIV"` (same fix applied to the five hard-coded `"PLT-…"` literals in `test_suite/test_11/12/13/14`).
- **`fixtures.py`** — `advance_lot_to()` walked `PLANNED->...->ASSEMBLY` on paperwork alone. PRD §3.4: "Entering `ASSEMBLY` requires `FORMATION`, a `CLEAR` hold, at least one formation run of the lot in `COMPLETED`...". Added `World.formation_evidence_for()`, which schedules/starts/completes one passing run before the `ASSEMBLY` hop. It books on its own lazily commissioned bay (`BAYLADDER`) so no test's bay is occupied, uses a 0.01 kW rectifier over one off-peak hour so the run reserves/consumes hundredths of a gram and prices at 0 cents (keeping emission-tight worlds affordable and perturbing no asserted ledger), and restores the logical clock so the manoeuvre is invisible to callers. This one fixture bug accounted for **~40 failures** masquerading as independent implementation defects.
- **`assertions.py`** — added `assert_same_instant()` (PRD §2.4 pins the instant, rendered with three fractional digits; a client's `...:00Z` literal and the stored `...:00.000Z` are the same instant) and `created_at_then_id()` (PRD §2.3 default collection order).

### Fixes applied to `test_suite/`
- **`test_02`** — `last_sample_at` / `actual_start_at` compared raw strings against `...:00Z` literals; now compared as instants via `assert_same_instant`. Also struck `assert aborted["actual_end_at"] == ...` on the *cascade* abort: PRD §3.5 stamps `actual_end_at` on the abort **endpoint**, while §2.8 hop five restates the cascade-abort post-conditions (reservation released, `final_charge_cents`/`consumed_emission_g` 0, `metered_energy_kwh` null) and omits it — a **branch-asymmetric side effect**, not uniquely derivable. Rest of the cascade test kept intact (PRD §2.8 covers hops 1-5 verbatim). *(Scaffold provenance: Difficulty/transitive_cascade/cascade_a_exposure_removal_freezes_plant_holds_lots_aborts_runs.)*
- **`test_12`** — charger listing asserted insertion order `[ch_z, ch_a, ch_m]`. All three are minted under one frozen logical instant, so per PRD §2.3/§4 (`created_at` ASC then `id` ASC) the identifier governs; the implementation was right. Now asserts `created_at_then_id([...])`.
- **`test_14`** — `lot_capacity_yield_pct` expected 95.05, silently excluding the passing cycle-life test. PRD §3.7 scopes the window to "tests ... whose `test_state` is `COMPLETED`, whose `result` is `PASS`" with no test-type restriction, so the mean of 95.01/95.08/80.00 is 90.03. Corrected all three occurrences.
- **`test_05`** — `test_the_state_refusal_survives_the_removal_of_the_emission_breach` asserted a global `total_count == 1` for formation runs while also requiring a lot in `ASSEMBLY`, which PRD makes impossible without a completed run. Re-scoped to per-bay counts: exactly one run on the accepting bay, zero on the refused bay (strictly stronger about the refusals leaving nothing behind).

### Fixes applied to `implementation/`
- **`errors.py`, `helpers.py`** — the formation-run lookup emitted `ERR_RUN_NOT_FOUND`, which appears nowhere in PRD §5; the catalogued code is `ERR_FORMATION_RUN_NOT_FOUND` (already used by three routes in `runs.py`). Renamed.
- **`routes/runs.py`** (`create_formation_run`) — the emission-quota gate rounded the quotient to 4 dp before comparing, so a 255.00 g reservation against a 254.99 g permit was accepted. PRD §2.7 prescribes rounding for the *stored* `emission_utilization_ratio`; PRD §3.5 states the quota check as the raw quotient ("divided by `monthly_lead_emission_permit_g`, must be at most 1.0000") with no rounding step. Now compares the unrounded Decimal quotient, preserving the "exactly 1.0000 is accepted" boundary.

### Final sweep evidence
8 concurrent rounds under `setsid nohup`, `--isolation per-test-server`, 163 s each, no `Terminated` in the log:

| Round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| passed/total | 89/89 | 89/89 | 89/89 | 89/89 | 89/89 | 89/89 | 89/89 | 89/89 |

`failed=0, errors=0` in all eight. Storage remains in-memory only (no sqlite/JSON dump//tmp cache, no startup seeding); `start.sh` re-invocation wipes all state.

## Step 8: Finalize PRD — 2026-09-03T22:35:00.000Z

Not skipped: Step 7 applied 2 `implementation/` fixes, so PRD.md demonstrably failed to pin at least those behaviors. Orchestrator check: PRD_FINALIZED.md exists, 516 lines / 123516 bytes vs PRD.md's 516 / 122264, and `diff` shows exactly 3 changed hunks — consistent with the subagent's reported 3 in-place paragraph revisions and not a no-op copy.

Subagent summary, verbatim:

`PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_2592_industrial_battery_manufacturing/workspace/PRD_FINALIZED.md`.

## Size
- PRD.md: 516 lines / 122,264 bytes -> PRD_FINALIZED.md: 516 lines / 123,516 bytes. Line delta **0.0%** (3 paragraphs revised in place), byte delta **+1.02%**.

## Changes (3)
- **§2.4 (Resource Identity, Timestamps)** — insert — extended the "three fractional-second digits" rendering rule from `created_at` alone to every instant stored on a resource (`updated_at`, `hire_date`, `last_sample_at`, `sampled_at`, `actual_start_at`/`actual_end_at`, `released_at`, `shipped_at`, `performed_at`, and the same fields repeated in a computed read's `lines`), so a client-supplied `...:00Z` reads back as `...:00.000Z` — `implementation/store.py:114-123` + `implementation/util.py:58-65`.
- **§2.8 (environmental cascade, hop five)** — insert — a cascade abort leaves `actual_end_at` untouched (null on a still-charging run); only the operator abort endpoint stamps it — `implementation/services/plant_service.py:121-124` (cascade) vs `implementation/routes/runs.py:239` (endpoint).
- **§3.5 (emission quota gate)** — insert — the scheduling quota compares the quotient exactly as computed, without the four-decimal rounding that §2.7 applies to the stored `emission_utilization_ratio`; added the 255.00 g / 254.99 g refusal example — `implementation/routes/runs.py:114-122`.

No PRD change was made for the other `<step_7_diff>` items: `PLANT_SITE_CODE` (impl pattern `[A-Z0-9]{4,12}` at `routes/plants.py:33` is exactly PRD §3.1), the `advance_lot_to` formation-evidence fixture (PRD §3.4 already pins the `COMPLETED`-run precondition, enforced at `routes/lots.py:210-224`), test_12 charger ordering (PRD §2.3/§4 already pin `created_at` ASC then `id` ASC; `helpers.sort_rows`), test_14 yield window (PRD §3.7 already has no test-type restriction; `lot_service.yield_window_tests` filters only on state/result/draw instant), test_05 count re-scoping (test bug), and the `ERR_RUN_NOT_FOUND` -> `ERR_FORMATION_RUN_NOT_FOUND` rename (impl moved to the code PRD §5 already catalogues).

## Pre-edit search log

**Edit 1 — §2.4 timestamp rendering**
- (a) Subject: how instant-valued fields are serialized in every response.
- (b) Enumerated/read: `util.py:fmt_ts` (single formatter, 3 digits); `store.py:serialize/public` (every `datetime` in any dict/list, including nested `lines`); `response.py` (`object_response`, `list_response`, `error_response`, `api_request_timestamp`); `validation.py:_coerce` `type: "datetime"` (all client instants parsed to aware datetimes, so nothing is stored as a raw string); grepped all of `implementation/` for `get_json`/`request.json` to find any verbatim echo — only `routes/clock.py:18`, which echoes the client's literal `current_utc` string; `routes/workers.py` (`hire_date`, `sampled_at`, `last_sample_at`), `routes/runs.py`, `routes/lots.py` (`released_at`), `routes/units.py`, `services/plant_service.py:emission_ledger` (line-level `scheduled_start_at`/`actual_end_at`).
- (c) Adjustment: scoped the sentence to "every instant **stored on a resource**" instead of "every timestamp the API returns", so the `/_clock/set_current_utc` echo (a non-persisted action payload returning the client's literal spelling) is not mis-described. Also moved `updated_at` to the head of the example list so it cannot be read as claiming append-only `ExposureSample`/`MaintenanceLog` rows carry one (the next paragraph says they do not).

**Edit 2 — §2.8 hop five, `actual_end_at` on a cascade abort**
- (a) Subject: which writes stamp `actual_end_at` on a formation run.
- (b) Enumerated/read: grepped `abort`/`ABORTED` across `implementation/` — exactly two abort writers: `routes/runs.py:231-245` (endpoint: sets `run_state`, `abort_reason`, `actual_end_at = db.now()`) and `services/plant_service.py:121-124` `abort_run` called from `_hold_cascade:137-139` (sets `run_state`, `abort_reason`, `db.touch` only). Also checked the other `actual_end_at` writers/readers: `routes/runs.py:211` (complete), `services/plant_service.py:52` `_same_permit_month` (consumption only counts `COMPLETED` runs, so a null on an aborted run is inert), `emission_ledger:219` (renders whatever is stored), and `routes/lots.py:320-341` (an operator `HOLD` aborts no runs at all).
- (c) Adjustment: dropped a first draft that said the cascade "touches only `run_state` and `abort_reason`" — `db.touch` also advances `updated_at`/`version`, so that phrasing would have been a false universal. Final wording claims only that `actual_end_at` is left as it stood, and attributes the stamp to the operator abort endpoint (keeping §3.5's "symmetrical in every respect" sentence, which is about `SCHEDULED` vs `CHARGING` inside that endpoint, true).

**Edit 3 — §3.5 emission quota comparison**
- (a) Subject: rounding of the emission ratio wherever it is compared against a breakpoint.
- (b) Enumerated/read: `routes/runs.py:108-122` (the only `ERR_EMISSION_BUDGET_EXCEEDED` raiser, per grep; raw `Decimal` quotient, `> 1.0000` refuses, zero-permit guarded); `services/plant_service.py:41-60` `recompute_emissions` (stores `q(ratio, 4)`); `services/plant_service.py:104-118` `derive_posture` (compares the **stored, rounded** ratio against `POSTURE_RESTRICTED_RATIO`/`POSTURE_FROZEN_RATIO`); `services/energy.py:44-45` `emission_grams` (2 dp per run); `routes/plants.py` PATCH allowance path (re-derives through the same `refresh_plant`).
- (c) Adjustment: wrote the sentence as a gate-local statement contrasted explicitly with the stored `emission_utilization_ratio` of §2.7, so the posture cascade's rounded-ratio breakpoints (0.8500 / 1.0000) are not accidentally re-defined as raw comparisons; and phrased the example as "rounding that same quotient ... would read exactly 1.0000" rather than implying a ratio is stored on a refused request.

## Step 9: Complete PRD — 2026-09-03T23:55:00.000Z

Orchestrator decision (autonomous, no user available): Step 9 was run as **three sequential file-partitioned passes** over `implementation/` rather than one pass, because a single subagent scanning all 28 modules / 4155 lines has a known tendency to no-op and hand back a `PRD_COMPLETED.md` byte-identical to its input. Each pass edited the same `PRD_COMPLETED.md` in place with the Edit tool (never a whole-file rewrite, to stay under the output cap), and each was told which files earlier passes had already covered plus which shared facts it could rely on:

- Pass 1 — `app.py`, `authz.py`, `errors.py`, `helpers.py`, `response.py`, `store.py`, `util.py`, `validation.py`, `services/constants.py`, `services/exposure.py`, `services/plant_service.py`, `routes/clock.py`, `routes/plants.py`, `routes/workers.py`, `routes/facilities.py`. Created PRD_COMPLETED.md from PRD_FINALIZED.md. 26 edits (20 ambiguity-pins, 6 mismatch-revisions); 123,516 -> 134,821 chars, 22 hunks.
- Pass 2 — `routes/designs.py`, `routes/lots.py`, `routes/runs.py`, `routes/assemblies.py`, `services/energy.py`, `services/lot_service.py`. 24 edits (15 ambiguity-pins, 9 mismatch-revisions); 134,821 -> 140,729 chars, 43 hunks. Handed five explicit items to pass 3.
- Pass 3 — `routes/tests.py`, `routes/units.py`, `routes/chargers.py`, `services/sizing.py`, `services/warranty.py`. 18 edits (12 ambiguity-pins, 6 mismatch-revisions); 140,729 -> 146,472 chars, 58 hunks. Resolved all five hand-offs and ran the end-to-end integrity check.

Totals across the three passes: **68 edits — 47 ambiguity-pins, 21 mismatch-revisions.** Every edit was in-paragraph; the file stayed at 516 lines with no new sections.

Orchestrator verification, independent of the subagents' claims:
- `workspace/PRD_COMPLETED.md` is 516 lines / 146,472 chars and is NOT byte-identical to `PRD_FINALIZED.md` (`cmp` differs; 58 diff hunks) — the scan demonstrably ran.
- Programmatic cross-check against SCAFFOLD.yaml: **70/70 endpoints** present in the §4 table and **61/61 error codes** present (0 missing) — nothing was clobbered by the in-place edits.
- Tail ends on the final §5 error-table row (`ERR_LEAD_INVENTORY_INSUFFICIENT | 409`) — a real section boundary, not a truncation.
- `find workspace/implementation -name '*.py' -newer results.1.json` returns nothing: **no implementation file changed during Steps 8 or 9**, so the Step 7 evidence (8/8 rounds at 89/89, failed=0 errors=0) still describes the shipped code. No re-sweep was necessary.

Notable mismatches Steps 8+9 corrected between PRD prose and the built system (these are the places a fresh implementer reading the original PRD.md would have diverged): posture-exit lifting only `PLANT_FROZEN` holds rather than every hold; `core_deposit_liability_cents` counting `RECEIVED` units; the emission-quota gate comparing the unrounded quotient; the emission ledger's `lines` being a superset of the totals rather than a partition; clearance recomputing the 180-day blood peak over the whole window; `formation_energy_charge_cents` being a month-independent recomputation; the sampling-plan draw and warranty-claim open both answering 201 with the parent row; the acceptance-number quarantine comparison firing on every recorded result rather than only on `FAIL`; and the core-return chemistry gate pre-empting the `core_status` gate.

Pipeline complete: `workspace/PRD_COMPLETED.md` written.
