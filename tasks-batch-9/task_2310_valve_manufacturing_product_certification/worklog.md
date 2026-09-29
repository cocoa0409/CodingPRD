# Worklog — task_2310_valve_manufacturing_product_certification

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2310_valve_manufacturing_product_certification/` and `workspace/` (pre-allocated name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T16:14:00.000Z

All three artifacts are complete and the lint is clean.

## Files
- `SCAFFOLD.yaml` (1902 lines, §1.0–§1.7 only — no design keys present)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1845 lines, single top-level key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (1909 lines, single top-level key `scaffold_corner_design`)

Scenario text is stored verbatim (block scalar, no wording changes). No sibling task directory was read, listed, or grepped at any point.

## Scaffold shape (§1.0–§1.7)
- `domain_name: valve-manufacturing-certification`, `api_prefix: /valve-mfg`, logical clock default `2026-08-01T00:00:00Z` via `POST /valve-mfg/_clock/set_current_utc`.
- **10 entities**: ValveModel, Foundry, FoundryQualification, HeatLot, Component, ValveUnit, ActuatorPackage, MonogramLicense, EngineeredOrder, TestRecord (traceability DAG Foundry → HeatLot → Component → ValveUnit; `entity_topology: graph`).
- **8 state machines**, including ValveUnit's three parallel dimensions (build / cert / service), the cyclic order review loop bounded at 3 clarification rounds, and the branching monogram closeout (GRANT vs GRANT_CONDITIONAL partitioned at 5 open minor findings).
- **2 OCC concurrency rules** (§1.2.1): `actuator-package-create-stale-unit` (`expected_valve_unit_version`, ERR_STALE_VALVE_UNIT_VERSION 412) and `datasheet-revision-stale-order` (`expected_engineered_order_version`, ERR_STALE_ORDER_VERSION 412).
- **10 calculations**: foundry_quality_index, required_test_envelope, required_actuator_torque_nm (dual-variant CATALOG vs DATASHEET), fugitive_emission_leak_class (dual-variant PEAK vs TIME_WEIGHTED), eto_order_price_cents (7 pinned waterfall steps), documentation_completeness_pct (pinned two-stage rounding, 43.50 vs 43.57 contrast), heat_lot_mass_balance, chemistry acceptance, license posture/finding counters, repair-kit availability.
- **53 ordered validations** (p1 auth → p82 credit limit), **44 endpoints**, **50 error codes**, **7 RBAC roles** (ProductEngineer, ProcurementSpecialist, SupplierRep — the one `entity_backed` role, TestTechnician, QualityManager, MonogramAuditor, FieldServiceCoordinator) with two segregation-of-duties rules (test witness ≠ certifier; lead auditor cannot waive own finding).

## §1.8 difficulty design
9 rule_ids, **23 instances** (all ≥2): dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 3. Every numeric assert is a pre-computed literal (e.g. class-300 shell 76.7 / seat 56.2 bar, quality index 60.00/80.00/100.00, gross 6,091,200 → net 2,131,920 + credit 3,959,280, mass balance 500.000 = 439.750 + 0.000 + 60.250, conditional expiry 2027-01-28T00:00:00Z).

## §1.9 corner design
**50 instances across all 9 taxonomy sections** — entities 9, state_machines 9, calculations 7, validations 8, endpoints 3, errors 4, rbac 4, cross_cutting_complexity_layers 5, consistency_model 1. Of these, 35 carry full `test_recipe` fixtures and 15 are `excluded_because:` stubs that each cite a specific §1.8 instance by name (no stub carries a test_recipe).

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  §1.5 endpoints declared:    44
  §1.1 entities declared:     10
  §1.8 instances scanned:     23
  §1.9 instances scanned:     35
  Calls scanned (§1.8+§1.9):  644

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Fixes made in the final pass: three role mismatches (a `GET /valve-mfg/foundries/{id}` call using `ProcurementSpecialist` where §1.5 declares `[Any]`, and two component-disposition calls using `QualityManager` where the endpoint declares `[ProcurementSpecialist]`), plus one assert correction — an order with zero documents and no approved actuator package computes `documentation_completeness_pct == 10.00` (the ACTUATOR_DATASHEET category has required count 0, so its fraction is 1.00 × weight 0.10), not 0.00.

## Step 3: Copy shared files — 2026-09-01T16:15:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T16:30:00.000Z

All three hard contracts pass. Here is the report.

## Output

`workspace/PRD.md` — **391 lines, ~11,400 words**, ending at §5 as required.

**Structure**
- §1 Introduction (3 paragraphs — the certification chain, the scope, the two design commitments: segregation of duties + retroactive cascading compliance)
- §2 Global Specifications, 11 subsections: 2.1 RBAC (7 roles, `SupplierRep` entity-backed on `Foundry`, the other six opaque), 2.2 API Response Structure (pasted verbatim from the skill), 2.3 Pagination + all list filters, 2.4 Record Identity (with `TestRecord`'s `id`/`created_at`-only exception), 2.5 The Logical Works Clock, 2.6 Measurement Precision and Rounding Discipline, 2.7 Traceability Cascades and Compensating Dispositions, 2.8 Stale-View Protection (both OCC rules), 2.9 Path Resolution for Unit-Scoped Records, 2.10 The Rejection Ladder (17 ordered bands + the two tie-break notes), 2.11 Segregation of Duties
- §3 Business Logic, 9 domain-grouped subsections: product-line design/release; procurement (foundry qualification, heat lots, components, mass balance); unit serialisation and build; the test programme; actuator sizing; monogram licensing and audits; certification and the decertification cascade; engineered-to-order; aftermarket service
- §4 Endpoint table — 44 rows, 4 columns, preceded by the 201-vs-200 paragraph
- §5 Error catalogue — 50 rows, 2 columns

## Hard Contract reports

```
Field coverage check:
- entities[].fields: 123 required, 123 present, 0 missing
- endpoints[].request_body: 89 required, 89 present, 0 missing
- endpoints[].query_params: folded into endpoints[].input in this scaffold; covered by the 89 above
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 53 checked, 53 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed, 0 missing
- state_machines[].transitions: 65 checked, 65 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed, 0 missing (63/63 constant literals recoverable verbatim)
- validations[] conditions: 50 distinct error_ids checked, 50 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 44 endpoints checked, all side effects and scope sets expressed, 0 missing
- entities[].fields[] structured content: 11 entities checked, defaults/initial values/precision reconstructible from prose, 0 missing
- sibling-branch symmetry: 5 groups checked, 5 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1007
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Notes
- The two forbidden design files were never opened, grepped, or referenced; no sibling task directory was read. The three worked examples that appear in the PRD (the 703.0/773.3 torque pair, the 6,180,840-cent quote, the 43.50 completeness figure) were derived from §1.5 formulas to pin rounding order, not lifted from any design index.
- One scaffold inconsistency handled deliberately: `hold_seconds` carries `>= 0` in the entity table but `>= 1` in the priority-12 numeric-domain validation, and `unit_price_cents` carries `> 0` in the entity table but `>= 0` in that same validation. The PRD states the validation-band values in §2.10 (band 7), since those are the checks that emit `ERR_INVALID_REQUEST`.
- The `documents` array shape is described using `doc_type`/`doc_ref`/`added_at` (the endpoint input names); the entity table's alternate spelling `doc_category` for the same slot was not propagated, to avoid handing the implementer two names for one field.

## Step 5: Generate unit tests — 2026-09-01T17:35:00.000Z

Generation is complete for task_2310_valve_manufacturing_product_certification.

## Files written

**Stage 1 — `test_helpers/`** (8 modules): `__init__.py`, `constants.py`, `types.py`, `api_errors.py` (all 50 §5 error ids + HTTP map), `api_client.py` (one method per §4 endpoint), `factories.py`, `assertions.py`, `test_users.py`, `fixtures.py` (4-tier composite builders climbing foundry → qualification → lot → component → model → license → unit → order).

**Stage 2 — `test_suite/`** (15 modules, 86 tests): `conftest.py`, `test_01`–`test_07` (queue A), plus 8 queue-B modules:

| module | tests |
|---|---|
| `test_08_entity_shapes_and_listings.py` | 9 |
| `test_09_state_transitions_and_terminal_states.py` | 5 |
| `test_10_derived_calculations_and_envelopes.py` | 2 |
| `test_11_input_and_business_validations.py` | 5 |
| `test_12_endpoint_behaviours.py` | 3 |
| `test_13_error_conditions.py` | 4 |
| `test_14_access_control_and_duties.py` | 4 |
| `test_15_stale_view_protection_and_read_consistency.py` | 3 |

## Counts per queue
- **Queue A (Difficulty §1.8): 51 tests / 23 non-stub instances**, every instance ≥ 2 tests.
- **Queue B (Corner §1.9): 35 tests / 35 non-stub instances**, every instance exactly 1 test. The 15 `excluded_because:` stubs were not translated.

## Instances skipped
**None** — all 23 difficulty and all 35 non-stub corner instances were translatable under the PRD-first filter. Three corner recipes were translated along the PRD-derivable pathway rather than the one the recipe named, because the recipe's literal path could not produce the asserted outcome:
1. `corner_build_advance_skipping_assembled_rejected` — recipe's MACHINED → PACKAGED would hit §2.10 band 11 (`ERR_UNIT_NOT_CERTIFIED`) first; translated as BLANK → ASSEMBLED, which reaches `ERR_BUILD_SEQUENCE_INVALID` (band 16) as designed.
2. `corner_scrapped_component_cannot_be_voided` — recipe's QualityManager caller would have hit band 3 `ERR_ROLE_NOT_PERMITTED`; component dispositions belong to ProcurementSpecialist per §4, so the call is made as that role and reaches `ERR_STATE_INVALID`.
3. `corner_duplicate_model_code_among_live_models_rejected` — the PRD places `model_code` uniqueness at SUBMIT_REVIEW, never at creation, so the duplicate is created (201, DRAFT) and refused on submission.
4. `corner_clock_endpoint_moves_the_logical_now` — dropped the recipe's `$.data.current_utc` assertion (a field the PRD never names); the clock move is instead proven through §2.5 ("Setting the clock rewrites nothing.") and the `released_at` stamp of §3.1.

## Verification performed
- `py_compile` clean; `pyflakes` clean over `test_suite/` and `test_helpers/`.
- Docstring citation audit: every quoted span in all 86 docstrings survives a whitespace-normalised literal substring match against `workspace/PRD.md` — 0 non-verbatim quotes.
- `Design:` tags: exactly one per test, always the final docstring line; all 86 resolve to real instance `name:` values; no stub instance is tagged; no instance missing.
- Static binding check of every `fixtures.*`, `factories.*` and `api.*` call against real signatures — 0 mismatches.
- No occurrences of "scaffold", "§1.x", "Table N", or `pytest.mark.skip/skipif/xfail` anywhere in generated code.

## Step 6: Generate implementation — 2026-09-01T17:35:00.000Z

The implementation is complete and verified end-to-end.

## Files written (all under `workspace/implementation/`)

Foundation: `app.py`, `db.py` (in-memory `Store` + logical clock), `errors.py` (all 50 error ids → HTTP status), `response.py` (envelope + pagination meta), `validation.py` (enums + typed field getters + pagination), `auth.py` (3-band RBAC), `calcs.py` (all pinned calculations), `domain.py` (lookups, derived fields, cascades, serializers), plus `requirements.txt` and executable `start.sh`.

Blueprints under `routes/`: `valve_models.py`, `foundries.py`, `foundry_qualifications.py`, `heat_lots.py`, `components.py`, `valve_units.py`, `actuator_packages.py`, `monogram_licenses.py`, `engineered_orders.py`, `clock.py`. ~3,800 lines total.

## Endpoints
Exactly **44** routes registered, matching the PRD §4 table one-for-one (verified by dumping `url_map`). All 50 catalogue error codes are raised somewhere in the code.

## Verification performed
- `bash start.sh` boots on `PORT`, binds `0.0.0.0`, guarded `pip install`, `exec python3 app.py` in foreground; envelope/meta shape, malformed JSON → `ERR_INVALID_REQUEST`, wrong method → 405, unknown path → 404 all confirmed over real HTTP.
- Full happy-path walk: model release → foundry/qualification → heat lot verify/release → component → license grant → unit build → SHELL/SEAT/FUNCTIONAL tests → actuator sizing + approval → certify → PACKAGED → order review/approve/release/documents/cancel → clock move → field-service reserve/start/abort.
- Cascades: 2 open MAJOR findings auto-suspends the license and decertifies; lot quarantine holds components (`pre_hold_status` preserved) and re-releasing restores them; foundry index re-bands to `PROBATION`; audit cooling-off 409; lazy qualification expiry then requalify; OCC 412 on stale `expected_valve_unit_version`; SoD 403s for both test-witness and audit-waiver.
- Pinned worked examples reproduce exactly: ETO quote **6,180,840** cents and documentation completeness **43.50** (two-stage rounding), foundry index banding, emission class `AA`.

## Notable design decisions
- Storage is purely `dict`s in `db.Store`, constructed at import — every fresh process starts empty; no file I/O, no seeding.
- Derived-on-read (never stored): foundry counters/index/status, lot mass balance, model `qualified_special_services`, unit `cert_status`/`provisional_emission_leak_class`, license open counts/`compliance_posture`, order `spec_stale`/`documentation_completeness_pct`/`certified_unit_count`. `final_emission_leak_class` is frozen at CERTIFY.
- Lazy refresh (qualification EXPIRED, unit cert recompute) never bumps `version`; explicit transitions and cascades always `touch()`.
- Rejection-ladder order follows scaffold priorities p1–p82.
- Ambiguities resolved: WITHDRAW allowed for ProductEngineer and QualityManager; qualification-window exclusivity enforced only at QUALIFY/REQUALIFY; datasheet fields optional at order creation; documents entries use `doc_type`; unknown action values → `ERR_INVALID_REQUEST`; bench occupancy is global per `test_bench_code` (half-open); WAIVE+MINOR → `ERR_INVALID_REQUEST`.

## Step 7: Run tests and iterate — 2026-09-01T17:55:00.000Z

All 8 parallel rounds pass 86/86.

Summary

- **Iterations run:** 2 (each a full 8-round parallel sweep, 86 tests per round, `per-test-server` isolation).
  - Iteration 1: 84/86 in all 8 rounds — 2 failures, both deterministic (no flakiness observed anywhere in the sweep).
  - Iteration 2: 86/86 in all 8 rounds.

- **Tests deleted:** none. Both failures traced to verbatim PRD sentences that uniquely determine the asserted outcome, so neither STEP 1a (silence) nor STEP 1b (non-derivability) triggered.

- **Fixes applied to `test_helpers/`:** none needed.

- **Fixes applied to `test_suite/`:**
  - `test_suite/test_12_endpoint_behaviours.py`, `test_01_setting_the_clock_moves_the_logical_now_without_rewriting_rows` — the test called `fixtures.submit_model_for_review(...)` and then `fixtures.release_model(...)`, but `release_model` already walks `DRAFT → IN_REVIEW → RELEASED` itself, so its inner submit hit the PRD-correct `ERR_STATE_INVALID` ("SUBMIT_REVIEW requires status DRAFT"). Removed the redundant explicit submit; all assertions (DRAFT before the move, `RELEASED` + `released_at` reading the moved logical clock) are unchanged.

- **Fixes applied to `implementation/`:**
  - `workspace/implementation/routes/valve_models.py`, `create_model()` — removed a `_code_taken()` / `ERR_DUPLICATE_CODE` check at design creation. PRD §3.1 states the `model_code` uniqueness rule only for submission ("Submitting for review … requires … that no other design sharing the same `model_code` currently sits in `DRAFT`, `IN_REVIEW` or `RELEASED` — a collision is `ERR_DUPLICATE_CODE`"); the creation paragraph names no duplicate check, so a duplicate draft must open at `DRAFT` and be refused only at `SUBMIT_REVIEW`. The submission-time check in `model_actions()` was left intact.

No implementation check that PRD requires was weakened, no assertion was downgraded, and no skip/xfail was added. Transient `results.[1-8].json` from the final sweep remain in `workspace/implementation/`.

Orchestrator verification: all 8 result files independently confirmed at `passed=86, total=86`.

## Step 8: Finalize PRD — 2026-09-01T17:49:00.000Z

`PRD_FINALIZED.md` written.

## Line counts
- `PRD.md`: 390 lines; `PRD_FINALIZED.md`: 390 lines; **0.00% line delta** (one line revised in place, +51 words).

## Changes
- **§3.1 (Product-Line Design and Release, creation paragraph)** — *insert* — added one clause stating that creation applies no `model_code` uniqueness check, that a design whose `model_code` is already carried by another design (in any status) still opens normally, and that the collision surfaces only at submission for review — `implementation/routes/valve_models.py:52-98` (create_model, no duplicate check) and `implementation/routes/valve_models.py:142-146` (submission-time `_code_taken` → `ERR_DUPLICATE_CODE`).

## Per-edit pre-edit search log

**Edit 1 — §3.1 creation-time `model_code` uniqueness**
- **(a) Subject:** `model_code` uniqueness enforcement — where in the design lifecycle a duplicate code is refused, and whether other resources' code-uniqueness rules are affected.
- **(b) Impl paths enumerated (grepped `DUPLICATE_CODE|_code_taken|model_code` across all of `implementation/`, then read each hit):**
  - `routes/valve_models.py:43-49` `_code_taken()` — only callsite is `model_actions()` `SUBMIT_REVIEW` (`:142`), with `exclude_id` = the submitting design and status set `("DRAFT","IN_REVIEW","RELEASED")`; matches the existing PRD sentence verbatim, so that sentence was left untouched.
  - `routes/valve_models.py:52-98` `create_model()` — the only other write that accepts `model_code`; its sole referential check is `domain.find_model(supersedes_model_id)`. No duplicate check on any status.
  - `routes/valve_models.py:150-203` `REJECT` / `RELEASE` / `WITHDRAW` branches — none re-checks the code, so a code can legitimately be shared across a `SUPERSEDED`/`WITHDRAWN` design and a live one.
  - `domain.py:409` — `model_code` only echoed in `serialize_model`; no uniqueness logic.
  - Parallel `ERR_DUPLICATE_CODE` sites confirmed to be *different* fields and *still* enforced at creation, so the wording must not generalise: `routes/foundries.py:32` (`foundry_code`), `routes/heat_lots.py:68` (`heat_number` within foundry), `routes/valve_units.py:100` (`serial_number`), `routes/monogram_licenses.py:65` (`license_code`), `routes/engineered_orders.py:77` (`order_code`).
  - `errors.py:43` — status mapping only.
- **(c) Wording adjustment:** scoped the sentence strictly to `model_code` and to the design-creation endpoint (no generic "codes are not checked at creation" phrasing), which would have contradicted the five still-enforced creation-time checks above. Also widened the qualifier to "whatever status that other design holds" so it stays true for the `SUPERSEDED`/`WITHDRAWN` cases that `_code_taken` deliberately ignores, and phrased the follow-on as "surfaces only when the new design is submitted for review" rather than restating the submission rule.

## Notes
- The `test_suite/` fix in `<step_7_diff>` is a pure fixture bug: `ERR_STATE_INVALID` for `SUBMIT_REVIEW` outside `DRAFT` is already uniquely determined by §3.1 plus §2.10 band 10, and `implementation/routes/valve_models.py:135-139` matches. No PRD edit made for it.

## Step 9: Complete PRD — 2026-09-01T18:20:00.000Z

`PRD_COMPLETED.md` is written to disk. Below is the required accounting.

## Counts

- **Source** `workspace/PRD_FINALIZED.md`: 390 lines / 83,792 chars
- **Completed** `workspace/PRD_COMPLETED.md`: 391 lines / 109,487 chars — **char delta +25,574**, line delta +1 (one new bullet appended to the existing error-envelope bullet list in §2.2; no new sections, no new paragraphs)
- **62 changed lines / 60 diff hunks**: **50 ambiguity-pins**, **12 mismatch-revisions**

## Per-change bullets

- §2.1 — insert — ambiguity — whitespace-only `X-User-ID`/`X-User-Role` counts as absent (`ERR_UNAUTHENTICATED`), values trimmed before use — `auth.py:12-18`
- §2.1 — insert — ambiguity — absent/empty/unknown `action` is `ERR_INVALID_REQUEST`, evaluated before the per-action role check — `auth.py:33-40`
- §2.1 — insert — ambiguity — SupplierRep scope: an explicit foreign `foundry_id` filter is rejected rather than silently narrowed; the foundry list is not tenancy-scoped; single-row tenancy runs only after the row resolves — `routes/heat_lots.py:97-127`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` plus exactly 20 uppercase-alnum characters — `response.py:13-15`
- §2.2 — revise — ambiguity — pagination meta appears only on list endpoints; `total_count` is pre-window; `has_more` formula pinned — `response.py:36-50`
- §2.2 — insert — ambiguity — four transport-level ids outside the §5 catalogue (`ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INVALID_REQUEST` 400, `ERR_INTERNAL` 500); trailing slash insignificant — `app.py:26,48-66`
- §2.3 — revise — ambiguity — empty `?limit=`/`?offset=` and non-canonical integer spellings (`05`, `+5`, `5.0`) are `ERR_INVALID_PAGINATION`; `limit` validated first — `validation.py:197-225`
- §2.3 — revise — ambiguity — list ordering is `(created_at, insertion sequence)`, hence total — `db.py:69-71`
- §2.3 — revise — ambiguity — filters are exact-match on the derived value; empty filter values and undeclared params ignored; per-resource filter inventory enumerated — `validation.py:228-232`
- §2.4 — insert — ambiguity — `created_at`/`updated_at`/`api_request_timestamp` come from wall-clock time, not the works clock — `db.py:13,48-67`
- §2.4 — revise — ambiguity — read-time recomputation never bumps `version`/`updated_at`; the sole mutating lazy evaluation is expired-conditional-license revocation — `domain.py:147-152,238-255,282-305`
- §2.5 — insert — ambiguity — `to_iso8601` required; bare date, naive and offset-bearing forms accepted and normalised; answers 200 with `{"current_utc": ...}` — `routes/clock.py:13-19`
- §2.6 — revise — ambiguity — 1-dp rounding set extended to `sized_torque_nm`, `base_break_torque_nm`, `output_torque_nm`, `supply_pressure_bar`, `test_pressure_bar` — `calcs.py:94-129`
- §2.6 — revise — ambiguity — `carbon_equivalent_pct` 3 dp, `impact_energy_j` 1 dp, `leak_rate_ppm`/`leak_drops` stored verbatim — `routes/heat_lots.py:78-86`
- §2.8 — revise — **mismatch** — "cannot be refused on state grounds" was false: a datasheet revision requires `CLARIFICATION_REQUESTED`, checked before the version check — `routes/engineered_orders.py:138-149`
- §2.8 — insert — ambiguity — both `expected_*` fields must be non-negative integers, validated before comparison — `routes/engineered_orders.py:134`
- §2.10 band 4 — revise — **mismatch** — tenancy ordering exceptions: body-read precedes shape on lot creation, pagination precedes tenancy on the lot list, existence precedes tenancy on single-row reads — `routes/heat_lots.py:41-47,95-99,120-127`
- §2.10 band 5 — revise — ambiguity — shape band detail: non-empty strings, bools/fractions rejected for ints, integral floats accepted, absent body treated as `{}`, unknown keys ignored — `validation.py:64-170`
- §2.10 band 7 — revise — **mismatch** — `unit_price_cents` at least **1** (PRD said 0); adds bore, credit-limit, chemistry, `leak_drops`, `output_torque_nm`, `supply_pressure_bar`, repair-kit bounds and first-field-read ordering — `routes/engineered_orders.py:53`
- §3.1 — revise — ambiguity — bore is whole mm, `base_break_torque_nm` rounded to 1 dp on store, `supersedes_model_id` must resolve but its status is unconstrained — `routes/valve_models.py:60-87`
- §3.1 — revise — ambiguity — `SUBMIT_REVIEW` only from `DRAFT`; the greater-than-zero re-check is `ERR_INVALID_REQUEST`, not a state error — `routes/valve_models.py:134-141`
- §3.1 — revise — **mismatch** — `WITHDRAW` is open to both `ProductEngineer` and `QualityManager` — `routes/valve_models.py:37`
- §3.1 — insert — ambiguity — `qualified_special_services` counts PASS records on any unit of the design whatever that unit's three statuses — `domain.py:187-208`
- §3.2 — insert — ambiguity — foundry codes and `country_code` are unvalidated strings; duplicate code compared across all bands — `routes/foundries.py:23-45`
- §3.2 — insert — ambiguity — qualification window echoed verbatim; interval ordering checked before the foundry resolves — `routes/foundry_qualifications.py:37-60`
- §3.2 — revise — ambiguity — `QUALIFY` only from `PENDING`; `valid_until` boundary inclusive; overlap peers judged after their own lazy expiry — `routes/foundry_qualifications.py:107-140`
- §3.2 — insert — ambiguity — `REQUALIFY` only from `EXPIRED` with its own mandatory ordered window checked against the row's previous window alone; an expired row can no longer be revoked — `routes/foundry_qualifications.py:141-190`
- §3.2 — insert — ambiguity — `heat_number` duplication checked after the foundry resolves and is scoped per foundry — `routes/heat_lots.py:56-72`
- §3.2 — insert — ambiguity — carbon ceiling tested before the toughness floor — `routes/heat_lots.py:58-70`
- §3.2 — insert — ambiguity — `quarantine_reason` optional, stored null when omitted — `routes/heat_lots.py:151`
- §3.2 — revise — ambiguity — `RELEASE` clears `quarantine_reason`, `REJECT` clears `pre_hold_status`, both dispositions have exactly two legal origins, the foundry is re-stamped only when a derived counter actually moves — `routes/heat_lots.py:176-232`
- §3.2 — revise — ambiguity — component creation resolves `target_model_id` before `heat_lot_id`; opens `CREATED` with null `pre_hold_status`; parent lot re-stamped — `routes/components.py:34-100`
- §3.2 — revise — ambiguity — the lot-released gate on `ISSUE_TO_MACHINING` runs after the component's own status check; issuing leaves the lot unstamped; scrap/void clear `pre_hold_status`; no exit from `CONSUMED`/`SCRAPPED`/`VOIDED` — `routes/components.py:118-190`
- §3.3 — revise — ambiguity — `engineered_order_id` must resolve but the order's status is unconstrained; serial duplication checked last of all — `routes/valve_units.py:51-120`
- §3.3 — revise — ambiguity — the four component checks precede the model-status check; the license must merely exist — `routes/valve_units.py:60-118`
- §3.3 — revise — **mismatch** — `to_build_status` accepts the full six-value vocabulary (`REWORK` → `ERR_BUILD_SEQUENCE_INVALID`), and `SHIPPED`/`REWORK` origins are `ERR_STATE_INVALID` rather than a sequence error — `routes/valve_units.py:180-215`
- §3.3 — revise — **mismatch** — the cert and actuator gates are evaluated **before** the adjacency check — `routes/valve_units.py:196-215`
- §3.4 — revise — **mismatch** — a test record is barred only by `cert_status` `CERTIFIED` (PRD restricted it to three statuses); `leak_drops` non-negative; conditional fields not forbidden elsewhere; `standard_ref` unvalidated; interval ordering before unit resolution — `routes/valve_units.py:241-297`
- §3.4 — insert — ambiguity — bench codes are a global resource matched by exact string equality — `routes/valve_units.py:290-297`
- §3.4 — revise — ambiguity — deciding-record ties broken by write order; `started_at`/`ended_at` play no part — `domain.py:274-281`
- §3.4 — insert — ambiguity — coverage re-evaluation is read-time and runs only for the three in-flight cert statuses — `domain.py:282-305`
- §3.4 — revise — ambiguity — emission input set needs a non-null `leak_rate_ppm` and admits FAIL records; provisional class never stored; the final-class freeze is unconditional — `domain.py:307-323`
- §3.5 — revise — ambiguity — `supply_pressure_bar` optional defaulting to 0; decision only from `PROPOSED`; supersession covers `PROPOSED` and `APPROVED` and stamps the unit, so consecutive proposals need consecutive versions — `routes/actuator_packages.py:36-105`
- §3.5 — insert — ambiguity — a `DATASHEET` basis with no datasheet falls back silently to catalog torque with no uncertainty factor — `calcs.py:99-129`
- §3.5 — revise — ambiguity — supply-pressure check precedes the torque check; comparison is against the frozen `sized_torque_nm`; approval leaves the unit unstamped — `routes/actuator_packages.py:112-160`
- §3.6 — revise — **mismatch** — the audit window end must be **strictly** after the start (PRD said "at or after") — `routes/monogram_licenses.py:59`
- §3.6 — revise — ambiguity — cooling-off compared at instant precision; each audit move only from its named predecessor; re-scheduling preserves the finding register and `license_status` — `routes/monogram_licenses.py:145-206`
- §3.6 — revise — ambiguity — register open in any `audit_state`; closing against a zero open count is `ERR_STATE_INVALID`; `WAIVE` with `MINOR` is `ERR_INVALID_REQUEST` before the license resolves; SoD precedes the open-count check; the closed-minor tally is not a field — `routes/monogram_licenses.py:301-400`
- §3.6 — insert — ambiguity — the automatic suspension fires only from `GRANTED`/`CONDITIONAL` — `routes/monogram_licenses.py:340-360`
- §3.6 — insert — ambiguity — each closeout branch tests its own `license_status` origin before the `audit_state` check — `routes/monogram_licenses.py:208-221`
- §3.6 — insert — ambiguity — conditional revocation is strict on both conditions and re-tested lazily on every read or use — `domain.py:238-255`
- §3.7 — revise — ambiguity — certification clears `decertification_reason` and re-stamps the owning order whatever its status — `routes/valve_units.py:426-434`
- §3.7 — revise — **mismatch** — `SPECIAL_SERVICE_REVOKED` has no automatic trigger; the reason is optional defaulting to `MANUAL` and accepted at face value; explicit `DECERTIFY` requires `CERTIFIED` and carries no version or SoD check; `UNIT_DECERTIFIED` overwrites `DOC_PACKAGE_VOIDED`; the order is stamped unconditionally — `routes/valve_units.py:436-443`, `domain.py:363-388`
- §3.8 — revise — **mismatch** — `datasheet_break_torque_nm`/`datasheet_torque_source` are optional at creation; `unit_price_cents` at least 1; model resolved before duplicate code; `gross`/`net` null with `credit_issued_cents` 0; a fresh package scores 10.00 — `routes/engineered_orders.py:46-105`
- §3.8 — revise — ambiguity — submission ignores `datasheet_torque_source`; subset test after the torque presence check; a revision requires all three fields and never resets `clarification_round_count` — `routes/engineered_orders.py:128-190`
- §3.8 — revise — ambiguity — release check order and equal-credit pass; a stale pin is a dead end (no path back to `UNDER_REVIEW`); release clears `held_reason`; RESUME's decertified sweep completes before the posture sweep; an unresolvable license is skipped — `routes/engineered_orders.py:261-309`
- §3.8 — revise — ambiguity — document append is unguarded by order status and package status and accepts repeats; `added_at` from the works clock — `routes/engineered_orders.py:384-402`
- §3.8 — revise — **mismatch** — `ISSUE_DOC_PACKAGE` evaluates order status → `COMPLETE` → certified count in that order; explicit void needs only an `ISSUED` package and drops `IN_PRODUCTION` to `HELD`; promotion to `COMPLETE` only from `ASSEMBLING`, never a demotion — `routes/engineered_orders.py:347-379,396-401`
- §3.8 — revise — **mismatch** — `CLOSE` judges the documentation package **before** the certified-unit count; cancellation credit by subtraction, not a second rounding; cancellation stamps `held_reason` only when it voids an `ISSUED` package — `routes/engineered_orders.py:311-345`
- §3.9 — revise — ambiguity — the service-status precondition is tested before `build_status`; `engineer_user_id`/`kit_qty` are mandatory only for their own action and ignored elsewhere — `routes/valve_units.py:449-480`
- §3.9 — revise — ambiguity — exact-stock reservation allowed; `reserved_kit_qty` assigned not accumulated; the design is stamped; START is an either-or that leaves a non-certified unit's reason untouched — `routes/valve_units.py:482-514`
- §3.9 — revise — ambiguity — COMPLETE clears the engineer, returns no stock and touches neither build nor cert; ABORT stamps the design only when something was reserved — `routes/valve_units.py:516-541`

## Notes on judgment calls

- Three internal PRD contradictions were resolved in favour of the implementation: the `WITHDRAW` role (§2.1 vs §3.1 — impl allows both), the audit-window ordering (§2.10 band 8 strict vs §3.6 "at or after" — impl strict), and §2.8's "cannot be refused on state grounds" vs the `CLARIFICATION_REQUESTED` gate.
- Where prose ordering conflicted with the impl's actual evaluation order (build gates before adjacency, `CLOSE` doc-package before unit count, `ISSUE` status before completeness, supply pressure before torque, pagination before tenancy), the prose was revised to the impl order.
- The §4 endpoint table (44 rows) and the §5 error catalogue (52 ids with statuses) were verified row-by-row against the routes and `errors.py:ERROR_STATUS` and needed no change; the only gap was the four non-catalogue transport ids, pinned in §2.2.
- `test_helpers/` and `test_suite/` were not consulted, per the instruction that tests are not the alignment target. `SCAFFOLD*.yaml`, `worklog.md` and all sibling task directories were not read.

---

Pipeline complete: Steps 1–9 all executed. Final state — 86/86 tests passing across all 8 parallel `per-test-server` rounds; `workspace/PRD_COMPLETED.md` on disk.
