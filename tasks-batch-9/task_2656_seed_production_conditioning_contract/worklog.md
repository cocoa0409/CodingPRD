# Worklog — task_2656_seed_production_conditioning_contract

## Step 1: Create task directory — 2026-09-04T02:02:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2656_seed_production_conditioning_contract` and its `workspace/` subdirectory. Index 2656 was pre-assigned by the orchestrating command; no scan of `./tasks/` was performed.

## Step 2: Generate Scaffold — 2026-09-04T03:05:00.000Z

All three scaffold artifacts are complete and lint-clean.

**Output** — `/home/ubuntu/github/CodingPRD/tasks/task_2656_seed_production_conditioning_contract/`
- `SCAFFOLD.yaml` (2061 lines) — §1.0–§1.7 only; contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2593 lines) — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (4420 lines) — single key `scaffold_corner_design`

All three `yaml.safe_load` cleanly.

**Counts**
- 15 entities, 6 state machines, 2 concurrency rules, 11 calculations, 51 validations, 60 endpoints, 64 errors, 6 roles; `api_prefix: /seed-ops`
- §1.8: 9/9 difficulty rules, 24 instances (2/3/3/2/3/3/2/3/3), all names unique
- §1.9: 9/9 taxonomy sections, 79 instances = 60 full test recipes + 19 `excluded_because` stubs (entities 12, state_machines 14, calculations 13, validations 21, endpoints 4, errors 3, rbac 6, cross_cutting_complexity_layers 5, consistency_model 1)
- Every stub's cited `difficulty_instance` resolves to a real §1.8 name; no stub carries a recipe; every `${var}` in all 1377 calls and in every assert line is bound by a prior capture (verified by script).

**Lint verdict (verbatim)**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2656_seed_production_conditioning_contract/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2656_seed_production_conditioning_contract/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2656_seed_production_conditioning_contract/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    60
  §1.1 entities declared:     15
  §1.8 instances scanned:     24
  §1.9 instances scanned:     60
  Calls scanned (§1.8+§1.9):  1377

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Design adjudications**
- 60 endpoints / 64 errors deliberately exceed the Expert bands ("harder than expert"); entities held at 15 by folding RogueingRecord into FieldInspection, TreatmentApplication into ConditioningRun's TREATING stage, contract `plant` into `sign`, and making CLOSED a side effect of `pay`.
- Validation priority 8 (`ERR_INVALID_INSPECTION_STATE`) was reworded so priority 26 `ERR_ROGUEING_NOT_DECLARED` stays triggerable — p8 previously swallowed every case p26 was meant to catch.
- Settlement `approve`/`dispute` side effects no longer mutate `ProductionContract.certified_units_total`: that field is declared as a derived roll-up over TAGGED lots, so money movements touching it contradicted both the field definition and the §1.8 dispute-invariant instance. Advance-recovery bookkeeping is unchanged.
- FK reverse-reachability is satisfied via filtered-list GETs, because `scaffold_lint.py` only matches sub-resource paths whose parameter is literally `{id}`.
- Negative instances use lint's name triggers (`_rejected`, `_cannot_`, `_not_found`, `_input_ignored`) where payloads or role headers intentionally violate the schema (e.g. the undeclared `SeedInspectorGeneral` role probing ERR_UNAUTHENTICATED).
- Two extra Variety variants were introduced inside declared inputs to reach otherwise-unreachable rules: `max_carryover_generations: 0` (ERR_CARRYOVER_LIMIT_EXCEEDED) and `treatment_required: true` (mandatory TREATING stage + label completeness).

## Step 3: Copy Shared Files — 2026-09-04T03:05:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T03:18:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2656_seed_production_conditioning_contract/workspace/PRD.md`

## Result

**492 lines / 108,575 bytes**, written incrementally (1 Write + 6 heredoc appends + 2 small edits). Document ends cleanly at the last row of the §5 error table — no mid-sentence cut, no missing trailing sections.

**Sections written**
- §1 Introduction (3 paragraphs — pain-point angle: irreversible loss of seed identity)
- §2 Global Specifications, 12 subsections: 2.1 RBAC, 2.2 Response Structure (verbatim from `section-2.2-response-structure.md`, byte-identical), 2.3 Pagination & List Ordering, 2.4 Resource Identity/Audit Columns/Version, 2.5 Logical Production Clock, 2.6 Path Resolution & Referential Integrity Order, 2.7 Precision/Rounding/Clean Seed Unit, 2.8 Version Pinning (OCC), 2.9 Rule Evaluation Order (all 51 priorities), 2.10 Occupation Windows & Interval Conventions, 2.11 Conserved Quantities, 2.12 Cascades & Deterministic Ordering
- §3 Business Logic, 9 subsections (chronological lifecycle: reference data -> offer gate -> inspection/rogueing -> harvest -> conditioning -> treated-seed compliance -> sampling/tagging -> carryover -> settlement)
- §4 Endpoint table (4 columns, all 60 rows) · §5 Error table (2 columns, all 64 rows)

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 142 required, 142 present, 0 missing
- endpoints[].request_body: 91 required, 91 present, 0 missing
- endpoints[].query_params: 26 required, 26 present, 0 missing
- endpoints[].path_params: 15 required, 15 present, 0 missing
Also verified: all 10 eligibility-assessment response fields, current_utc, cleaned_at,
next_season_year, both OCC fields, pagination meta fields.
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 51 checked, 51 expressed in prose (full ordered ladder in §2.9), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_contract_version /
  expected_seed_lot_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 6 machines / 47 transitions checked, 47 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed (all constants embedded in business context;
  UNIT_KG as "clean seed unit of 25.0 kg", tiers as dollar/cent pairs, DECAY_FACTOR as "one half
  raised to elapsed years"), 0 missing
- validations[] conditions: 51 checked, 51 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 60 endpoints checked, all expressed, 0 missing
- entities[].fields[] structured content: 142 checked (defaults, enums, initial values,
  common_fields:false exceptions for Variety/TreatmentProduct/FieldHistoryRecord/HarvestEvent
  stated explicitly), 0 missing
- sibling-branch symmetry: 7 groups checked (3 inspection outcome branches; 2 rogueing-verification
  branches; 2 eligibility variants; 2 unit-accounting variants; PLANNED->ABORTED vs COMPLETED->REVERSED;
  COMPUTED-dispute vs APPROVED-dispute; SIZED->BAGGED vs TREATED->BAGGED), 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 849
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```
Also verified: 60/60 endpoint paths present, 64/64 error IDs present in §5 **and** every one also mentioned in §1–§4 prose; all 6 role names and every state/enum value present verbatim; no fuzzy/approximating words; no audit footer in PRD.md.

## Adjudications (scaffold self-conflicts resolved)

1. **Carryover effect on the parent lot.** `endpoints[]` side_effects claim carryover sets `parent.certification_status = RETEST_DUE`, voids the parent's `ISSUED` tags and zeroes `parent.tagged_bag_count`. The `SeedLot` state machine says the `TAGGED -> RETEST_DUE` edge "applies to the newly minted successor lot; the parent lot is unchanged", and `concurrency_rules.carryover-create-stale-lot` requires that "a repeated carryover call passes every state precondition" — impossible if the parent left `TAGGED`. Resolved 2-to-1 in favour of the state machine + OCC rule: **parent stays `TAGGED` with its tags intact; only `parent.version` increments.** Stated explicitly in §3.8 so a PRD-only reader cannot read it the other way.
2. **Cancellable contract statuses.** Endpoint side_effects list `INSPECTION_PASSED` among cancellable states; the state machine's four `-> CANCELLED` edges and their preconditions admit only `DRAFT`, `OFFERED`, `PLANTED`, `ROGUEING_REQUIRED`. Resolved in favour of the state machine; §3.2 explicitly names `INSPECTION_PASSED` as *not* cancellable.
3. **Which settlements the FAIL cascade supersedes.** Endpoint side_effects say "COMPUTED or APPROVED"; cascade hop 5 and the `GrowerSettlement` machine both say `COMPUTED` only. Resolved to **`COMPUTED` only**, with `APPROVED`/`PAID`/`DISPUTED`/`SUPERSEDED` explicitly listed as untouched.
4. **Rogueing-verification success state.** Endpoint text says "`ROGUEING_DECLARED -> ROGUEING_VERIFIED` then `CLOSED`"; both state machines say `ROGUEING_VERIFIED` on the passing branch and `CLOSED` only on the failing branch. Resolved to the state machines.
5. **`inspected_on >= contract.planted_on`** is a declared precondition with no `error_id` anywhere in the scaffold. I express the constraint and attribute rejection to `ERR_INVALID_REQUEST` (input-domain violation on a single date field) rather than silently dropping it. This is the one attribution not directly traceable to a scaffold `error_id` — flagging it in case the test generator should be steered.
6. **Successor lot's `final_clean_units`** is not specified for carryover. I state it is inherited from the parent, and note that this equals the successor's held mass divided by 25.0 kg rounded half-up to 2 dp — so the "inherit" and "recompute" readings coincide and no test can be split by the choice.

**Orchestrator truncation check (per known generator failure mode):** verified independently — PRD.md ends at the final `| \`ERR_NET_PAYABLE_NEGATIVE\` | 422 |` table row, a real section boundary. Section headers enumerate §1 through §5 with no gaps. Endpoint table has exactly 60 method rows; error table has exactly 64 `ERR_` rows. `comm` diff of scaffold error ids vs PRD error ids leaves only `ERR_XXX`, which is a spec placeholder token in the scaffold generator's own prose, not a real error. No regeneration needed.

## Step 6: Generate Implementation — 2026-09-04T03:52:00.000Z

(Launched concurrently with Step 5 in a single orchestrator message; Step 6 returned first. Its worklog entry is recorded here at completion time, so it precedes Step 5's entry in this file even though the two ran in parallel.)

Implementation complete at `/home/ubuntu/github/CodingPRD/tasks/task_2656_seed_production_conditioning_contract/workspace/implementation/`.

## Files written (2,731 lines total)

Core:
- `app.py` (74) — app factory, 7 blueprints, `/_clock/set_current_utc`, ApiError/HTTPException/500 handlers, `PORT` env entry point
- `errors.py` (154) — `ApiError` + status/message tables for all 66 error ids
- `envelope.py` (65) — `req_<20 alnum>` ids, ISO-ms-Z timestamps, object/list/error envelopes
- `store.py` (87) — 15 in-memory dicts, logical clock (default `2026-08-01T00:00:00Z`), sequences
- `calc.py` (269) — Decimal/ROUND_HALF_UP math: dockage, both unit bases, bag truncation, eligibility (STRICT_HISTORY + DECAY_WEIGHTED), inspection rates/outcome, quality pricing, settlement rollup + advance waterfall, grower standing
- `validation.py` (244) — auth, field parsing/coercion, pagination, query filters
- `common.py` (103) — public projections, paginate, 15 typed FK getters
- `services.py` (134) — grower-standing 4-hop cascade, failed-lab 5-hop cascade, lot minting, rollup recomputes
- `requirements.txt` (1), `start.sh` (7, executable)

Routes: `reference.py` (266), `contracts.py` (167), `inspections.py` (182), `harvest.py` (176), `conditioning.py` (387), `certification.py` (244), `settlements.py` (170), `__init__.py`.

**60 endpoints**: 30 POSTs + 15 single-resource GETs + 15 list GETs (+ the clock endpoint). Storage is in-memory dicts only; nothing is seeded — a fresh boot returns `total_count: 0` for every collection, verified.

## Smoke test
Four end-to-end scripts on port 18656 all passed: happy path (offer -> sign -> inspection -> harvest -> 4-stage conditioning -> sample/PASS -> tag -> settlement -> pay -> CLOSED), carryover OCC + 5-hop FAIL cascade, the grower-standing cascade with SoD and validation-ladder ordering, and treatment/label/reversal coverage (`ERR_TREATMENT_CROP_NOT_LABELED`, `ERR_TREATMENT_RATE_EXCEEDS_LABEL`, `ERR_TREATMENT_LABEL_INCOMPLETE`, `ERR_RUN_NOT_LATEST`, mass-ledger restore to `SIZED`/880 kg/120 kg shrink). Verified numerics: price 4000 -> 4200, bags 26500/25 -> 1060, settlement gross 4,452,000 -> net 4,087,000 at a 60% tier. All files `py_compile` clean; server killed with `fuser -k 18656/tcp` (port confirmed free), `__pycache__` removed.

## Adjudications (PRD favored over SCAFFOLD)
1. Carryover leaves the parent untouched except `version` +1 (SCAFFOLD wanted parent `RETEST_DUE` + tag voiding).
2. Cancellation allowed from DRAFT/OFFERED/PLANTED/ROGUEING_REQUIRED only — `INSPECTION_PASSED` refused.
3. FAIL cascade hop 5 supersedes only `COMPUTED` settlements, not `APPROVED`.
4. Successful rogueing verification -> `ROGUEING_VERIFIED` only; `CLOSED` on the failing branch.
5. Sampling always sets lot `certification_status = SAMPLED`.
6. `ERR_GROWER_SCOPE_VIOLATION` enforced on the three grower-actor writes only; no scope filtering on reads.
7. `tag_serial` uses a global 6-digit sequence; `lot_code` a per-contract 4-digit one.
8. `moisture_dockage_pct` rounded to 2 dp and the rounded value used downstream.
9. Supplied date/datetime inputs echoed verbatim; computed instants rendered ISO-ms-Z; `issued_at` from the logical clock; the clock endpoint echoes the raw string.
10. Uniqueness collisions -> `ERR_INVALID_REQUEST` (400); the catalogue has no dedicated error.
11. `inspected_on` before `planted_on` -> `ERR_INVALID_REQUEST`, after FK resolution, before the contract-state check.
12. Settlement approve's contract-state check evaluated last, after SoD.
13. Out-of-range `output_kg` -> `ERR_OUTPUT_EXCEEDS_INPUT` (ladder 32), not a shape error.
14. Reversal restores the pre-run stage from an internal `_prev_conditioning_status` captured at completion.
15. `cleanout_buffer_applied_minutes` = the line's full `cleanout_minutes_required` unless the line's last variety matches exactly (then 0).

## Step 5: Generate Unit Tests — 2026-09-04T05:00:00.000Z

(Launched concurrently with Step 6 in a single orchestrator message; Step 6 returned first, so this entry follows Step 6's in the file.)

Suite complete. Both output directories sit at the task root; nothing was written under `workspace/`, and `workspace/implementation/` was never read or listed.

## Files written (all `py_compile` clean; `pytest --collect-only` gathers 118 tests in 0.88 s with no import errors)

Stage 2, `/home/ubuntu/github/CodingPRD/tasks/task_2656_seed_production_conditioning_contract/test_suite/`:

| file | lines |
|---|---|
| conftest.py | 15 |
| test_01_dual_variant_calc.py | 226 |
| test_02_combinatorial_formula.py | 315 |
| test_03_non_linear_state_machine.py | 293 |
| test_04_transitive_cascade.py | 210 |
| test_05_priority_pair_validation_conflict.py | 293 |
| test_06_boundary_precision_check.py | 252 |
| test_07_cross_entity_state_dependency.py | 190 |
| test_08_resource_temporal_overlap.py | 478 |
| test_09_compensating_invariant.py | 283 |
| test_10_entities.py | 527 |
| test_11_state_machines.py | 366 |
| test_12_calculations.py | 434 |
| test_13_validations.py | 855 |
| test_14_endpoints.py | 504 |
| test_15_errors.py | 198 |
| test_16_rbac.py | 382 |
| test_17_cross_cutting.py | 318 (new this session) |
| test_18_consistency_model.py | 91 (new this session) |

Stage 1 `test_helpers/` (frozen): `__init__.py` 59, `api_client.py` 409, `api_errors.py` 163, `assertions.py` 563, `constants.py` 166, `factories.py` 307, `fixtures.py` 459, `test_users.py` 74, `types.py` 471.

## Instance coverage

- Queue A (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`): 24 non-stub instances, 24 translated, 52 tests — every instance carries >=2 tests.
- Queue B (`SCAFFOLD_CORNER_DESIGN.yaml`): 79 instances, 19 stubs (`excluded_because`) skipped silently, 60 non-stub instances all translated, 66 tests.
- **Zero non-stub instances skipped** — no gaps to report, no `skip`/`xfail`/placeholder anywhere.
- 118 tests, 84 distinct `Design:` tags, each exactly one tag, on the final docstring line, every tag resolving to a real `name:` (and section/rule_id) in its yaml.
- 239 `PRD: "..."` citations across the suite; all survive a literal whitespace-normalized grep of `workspace/PRD.md` (0 missing).

Final two modules: `test_17_cross_cutting.py` covers the two version pins (`occ_stale_contract_version_on_settlement_create`, `occ_stale_lot_version_on_carryover`) and `derived_field_reconciliation_certified_units_total` (issue -> void -> re-issue, with the VOIDED row retained so the roll-up filters rather than deletes). `test_18_consistency_model.py` covers `immediate_consistency_derived_fields_visible_in_same_response`.

## Adjudications (11, design yaml vs PRD — PRD wins in each)

1. Carryover leaves the parent `TAGGED`, tags `ISSUED`, `tagged_bag_count` unchanged, only `version` +1 (PRD §3.8).
2. Consequently the corner instance `occ_stale_lot_version_on_carryover`'s final assert (parent -> `RETEST_DUE` / `tagged_bag_count` 0 / tag `VOIDED`) is dropped; the test asserts the parent-left-in-place text instead.
3. `gross_payable_cents`, not the designs' `gross_amount_cents`.
4. `weed_rate_per_10000`, not `restricted_weed_rate_per_10000`.
5. The `worst_exceedance_ratio` assert dropped (no such field).
6. The equipment-window instance needs a re-certification before its trigger.
7. `provisional_clean_kg` lives on the HarvestEvent, not the SeedLot.
8. `eligibility_variant_applied`, not `applied_eligibility_variant`.
9. Unknown/extra input fields are ignored, not rejected.
10. `eligibility_assessment_computed_read_returns_both_variants` claims the field's version is unchanged; PRD says the assessment stamps `last_assessed_risk_score` and increments the field's `version` by 1 — the test asserts version+1 and proves non-mutation against the contract.
11. `CertificationTag` has no `issued_by_user_id` field (design/first draft assumed one); the consistency test asserts the minted `tag_serial`, `issued_at` and `ISSUED`/null `void_reason` instead.

## Step 7: Run Tests and Iterate — 2026-09-04T05:40:00.000Z

Clean. All 8 parallel rounds green.

## Summary

**Iterations run:** 2 (iteration 1: 110/118 in all 8 rounds, 8 deterministic failures, no flakiness; iteration 2: 118/118 in all 8 rounds).

**Tests deleted:** none. All 8 failures traced to test-artifact bugs (STEP 2), not to PRD silence.

**Fixes applied to `test_helpers/`**
- `test_helpers/assertions.py` — added `parse_instant()` / `assert_instant_equals()`. PRD §3.7 pins the *value* of `germination_valid_until` (`tested_at` advanced by the variety's `germ_validity_days`) but never pins its fractional-second rendering; §2.4 only fixes three fractional digits for `created_at`/`updated_at`/`api_request_timestamp`. Five tests were comparing the field as a literal string against `GOLDEN_FIGURES["GERMINATION_VALID_UNTIL"] = "2027-06-11T00:00:00Z"` while the implementation renders the house-style `2027-06-11T00:00:00.000Z`. Both renderings are PRD-faithful readings, so the assertion now compares the instant denoted, keeping the value pinned while dropping the PRD-silent format demand.

**Fixes applied to `test_suite/`**
- `test_02_combinatorial_formula.py`, `test_06_boundary_precision_check.py`, `test_12_calculations.py`, `test_13_validations.py`, `test_17_cross_cutting.py` — the five `germination_valid_until` string comparisons switched to `assert_instant_equals` (plus the import).
- `test_05_priority_pair_validation_conflict.py::_sized_lot_with_treatment_product` — the treatment-product fixture registered `allowed_crop_kinds=["WHEAT", "BARLEY"]`. `BARLEY` is not one of PRD §3.1's six crop kinds (`WHEAT`, `TRITICALE`, `SOYBEAN`, `SUNFLOWER`, `ALFALFA`, `CANOLA`), so the PRD-faithful implementation correctly rejected the setup call with `ERR_INVALID_REQUEST` (§2.9 rule 3, "enum members valid"), wiping out both tests in the class as setup errors. Changed to `["WHEAT", "TRITICALE"]`, preserving the fixture's intent (product labeled for the lot's `WHEAT` variety).
- `test_13_validations.py::TestTagBagCountAgainstUntaggedRemainder::test_the_remainder_shrinks_as_tags_are_issued` — the test issued a 1000-bag tag block and then expected `ERR_TAG_BAG_COUNT_EXCEEDS_LOT` (ladder priority 34) on a second block, but the first tag moved the lot `PASSED -> TAGGED` (§3.7), so PRD priority 28 ("The lot must be simultaneously `BAGGED` on its conditioning axis and `PASSED` on its certification axis, or the request is refused with `ERR_LOT_NOT_TAG_ELIGIBLE`") pre-empts it — the implementation was right. Fixed the setup rather than the assertion: a `RETEST` sample (admitted against a `TAGGED` lot per §3.7) plus a passing result walks the lot `SAMPLED -> PASSED` with its issued tags and `tagged_bag_count` of 1000 intact, which is the only PRD-reachable state in which the untagged remainder is non-trivial. The exact `ERR_TAG_BAG_COUNT_EXCEEDS_LOT` assertion and the 380-bag success are unchanged.

**Fixes applied to `implementation/`:** none — no implementation defect was found. Notably the tag-issuance ladder order (27 -> 28 -> 34 -> 35 -> 49) and the crop-kind enum validation were both already PRD-correct and were what exposed the test bugs.

**Orchestrator verification:** independently re-read all eight `workspace/implementation/results.$i.json` — every round reports `passed == total == 118`. Sweep artifacts are present on disk, not merely claimed.

**Step 8 skip-condition adjudication:** NOT skipped. The skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes. Deletions and implementation fixes were both zero, but Step 7 ran 2 iterations and applied fixes in both `test_helpers/` (one new assertion helper) and `test_suite/` (seven edits across six files). Those fix sites mark places where PRD.md did not uniquely determine a behavior the implementation had already chosen — the `germination_valid_until` fractional-second rendering in particular — so Step 8 runs with the Step 7 entry above inlined as `<step_7_diff>`.

## Step 8: Finalize PRD — 2026-09-04T05:14:00.000Z

`/home/ubuntu/github/CodingPRD/tasks/task_2656_seed_production_conditioning_contract/workspace/PRD_FINALIZED.md` is written.

## Line/byte counts
- `PRD.md`: 492 lines, 108,575 bytes
- `PRD_FINALIZED.md`: 492 lines, 109,050 bytes
- Line delta: 0 (0.0%); byte delta +475 (+0.44%). Two sentence-level revisions, no new sections. Tail verified identical (final error-table row `| ERR_NET_PAYABLE_NEGATIVE | 422 |`).

## Changes
- **§3.7 (passing-result branch) — revise — pinned the serialization of `germination_valid_until` to the three-fractional-digit ISO 8601 UTC form (`2027-06-11T00:00:00.000Z`, not `...:00Z`)** — `implementation/routes/certification.py:110-115` via `implementation/envelope.py:17-24`.
- **§3.1 (treatment-product registration) — revise — `allowed_crop_kinds` is an array whose every member must be one of the six crop kinds; an outside member is refused `ERR_INVALID_REQUEST` under §2.9 rule 3** — `implementation/routes/reference.py:74` via `implementation/validation.py:158-163`.

## Per-edit pre-edit search log

**Edit 1 — `germination_valid_until` rendering**
- (a) Subject: the serialized form of `germination_valid_until` wherever the platform emits it (sample and lot), plus everything that reads that validity.
- (b) Enumerated/read: `routes/certification.py:110-115` (set on PASS, both sample and lot, via `iso_ms`), `:61` (sample born null), `:125` (FAIL -> sample null), `:157-159` (tag-issuance gate compares the internal `datetime`, not the string), `routes/conditioning.py:314` (carryover gate, same internal `datetime`), `services.py:85` (new lot / carryover successor born null), `services.py:93-124` (failed-result cascade leaves the lot's validity untouched — consistent with "Samples in `PENDING` or `FAIL` state never move a lot's germination validity"), `envelope.py:17-24` (`iso_ms`), `store.py:69,81` (`created_at`/`updated_at` use the identical helper), `app.py:38-43` + `validation.py:90-106` + all `*__raw` echo sites (`tested_at`, `sampled_on`, `cleaned_at`, `window_start/end`, `planted_on`, `current_utc`) which are echoed **verbatim as the client sent them**.
- (c) Adjustment: scoped the sentence to how the field is *rendered* only. I deliberately did **not** write a general rule such as "every timestamp/derived instant uses three fractional digits", because client-supplied instants (`tested_at`, windows, `last_cleanout_at`, `last_run_end_utc`, `current_utc`) are echoed raw, and I did not touch the comparison semantics, because the tag and carryover gates compare exact instants and §3.7/§3.8 already say "instant". I also avoided claiming anything about sub-millisecond handling.

**Edit 2 — `allowed_crop_kinds` enum membership**
- (a) Subject: shape validation of the crop-kind list on treatment-product registration.
- (b) Enumerated/read: `routes/reference.py:71-93` (`PRODUCT_FIELDS`, `enum_array` over `CROP_KINDS`; the `product_code` uniqueness scan runs *after* `parse_fields`, so the shape error wins), `validation.py:15` (the six `CROP_KINDS`), `validation.py:158-163` (`enum_array`: non-list -> `ERR_INVALID_REQUEST`; each member via `check_enum` -> `ERR_INVALID_REQUEST`/400), `routes/reference.py:29` (`restricted_prior_crop_kinds`, identically validated), `routes/conditioning.py:119-121` (the consumer gate `ERR_TREATMENT_CROP_NOT_LABELED`).
- (c) Adjustment: I did **not** add "non-empty" or "distinct", because the implementation accepts `[]` and accepts duplicates; and I phrased the constraint as a property of the members only, so nothing is implied about list ordering or about the separate `ERR_TREATMENT_CROP_NOT_LABELED` gate that consumes the list at run-planning time.

## Items deliberately not patched
- **Tag-issuance ladder order (27 -> 28 -> 34 -> 35 -> 49).** `routes/certification.py:146-159` follows §2.9 exactly; §3.7's prose says only "Five gates apply" with no ordering claim while §2.9 is explicitly the single fixed ladder. Already determined — the test was wrong, not the PRD.
- **`RETEST` on a `TAGGED` lot walking `TAGGED -> SAMPLED -> PASSED` with tags and `tagged_bag_count` intact.** §3.7's sampling paragraph enumerates its side effects exhaustively (status to `SAMPLED`, conditioning axis untouched, lot `version` +1) and §3.8 says a `TAGGED` lot may be "re-verified in place"; `routes/certification.py:33-66` matches, and notably does **not** recompute the contract's `certified_units_total` while the lot is out of `TAGGED`. Judged already determined, so left verbatim rather than adding a claim §2.12 could be read to contradict.
- **The `test_05` `BARLEY` fixture and the `test_13` tag-remainder setup** were pure test-artifact bugs beyond the enum point covered by edit 2.

## Step 9: Complete PRD — 2026-09-04T06:05:00.000Z

**Orchestrator decision:** Step 9 was run as THREE SEQUENTIAL FILE-PARTITIONED PASSES over `implementation/`, not as one subagent. Rationale: a single-subagent Step 9 on a 2,723-line implementation and a 492-line/109 KB PRD routinely returns a PRD_COMPLETED.md that is byte-identical (or near-identical) to its source, because the scan never actually reaches the whole codebase. Partitioning forces every implementation file into some pass's mandatory scope. Pass 1 owned the `cp` from PRD_FINALIZED.md; passes 2 and 3 edited the same file in place and were explicitly forbidden from re-copying it. Pass 3 additionally owned a closing integrity check.

Partition:
- **Pass 1** — `app.py`, `envelope.py`, `errors.py`, `store.py`, `validation.py`, `common.py`, `routes/reference.py`, `routes/contracts.py`
- **Pass 2** — `routes/inspections.py`, `routes/harvest.py`, `routes/conditioning.py`, plus the inspection/harvest/conditioning functions of `calc.py`
- **Pass 3** — `routes/certification.py`, `routes/settlements.py`, `services.py`, plus the certification/settlement functions of `calc.py`

### Pass 1 (core, reference data, contracts)

- `PRD_FINALIZED.md`: 492 lines / 109,050 bytes -> `PRD_COMPLETED.md`: 492 lines / 115,882 bytes (**+6,832 chars**, 22 lines touched)
- **23 ambiguity-pins, 0 mismatch-revisions.** §5's error-status table matched `errors.py` row-for-row and every §4 role list matched the `authenticate(...)` tuples exactly.
- Changes: §2 intro (no seeded data; every collection empty on fresh boot — `store.py:24-43`); §2.1 (empty-string `X-User-ID`/`X-User-Role` treated as absent -> `ERR_UNAUTHENTICATED` — `validation.py:31-34`; grower scope confined to the three grower-actor writes, no read filters — `contracts.py:117`); §2.2 (`api_request_id` = `req_` + exactly 20 uppercase-alphanumerics — `envelope.py:10-14`; `api_request_timestamp` reads real server time, not the logical clock — `envelope.py:30`); §2.3 (non-integer `limit`/`offset` rejected, empty string falls back to default — `validation.py:190-205`; `created_at` ties broken by insertion order — `store.py:87`; filter semantics: empty string ignored, bad enum/boolean/integer -> `ERR_INVALID_REQUEST`, FK filters equality-matched and never existence-checked so a dangling id yields an empty page not a 404, unknown query params ignored — `validation.py:209-244`, `common.py:90-103`); §2.4 (`created_at`/`updated_at` stamped from real server time, independent of clock repositioning — `store.py:69,81`); §2.5 (`current_utc` required, response echoes the caller's raw string — `app.py:41-43`, `store.py:52-54`); §2.7 (rounded quantities render as plain JSON numbers so displayed fractional digits are not significant — `envelope.py:34-41`); §2.9 rule 3 (absent/empty body read as `{}`, non-object body rejected, undeclared fields ignored, explicit `null` counts as absent, booleans never accepted as number/integer, lenient ISO parsing, uniqueness checks return `ERR_INVALID_REQUEST` but evaluate after the existence rules — `validation.py:75-182`); §3.1 (`restricted_prior_crop_kinds`/`_years` required and the kinds array may be empty — `reference.py:29-30`; no range check on variety numerics except `restricted_prior_crop_years >= 1` and no variety uniqueness — `reference.py:24-41`; duplicate `product_code` -> `ERR_INVALID_REQUEST`, `max_rate_g_per_100kg` unbounded — `reference.py:75,86-88`; grower fields free-form, no email-shape or uniqueness validation — `reference.py:113-117`; owning grower resolved before the `field_code` uniqueness check, codes reusable across growers, `acres`/`isolation_distance_m` unbounded — `reference.py:154-170`; duplicate `crop_year` -> `ERR_INVALID_REQUEST` after the field resolves, `source_note` free-form, append bumps the field's `version` — `reference.py:208-221`); §3.2 (assessment inputs all required, its `season_year` carries no 2000-2100 bound unlike a contract's — `reference.py:245-249`; each inspection closed by contract cancellation gets its own `version` increment — `contracts.py:142`, `services.py:128-134`); §3.3 signing only (`planted_on` stored/echoed as the exact client string — `contracts.py:125`); §4 (trailing slashes tolerated on every route — `app.py:28`); §5 (three identifiers outside the catalogue: `ERR_NOT_FOUND` 404 on an unrouted path, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500; the first two are resolved by routing and precede authentication — `app.py:49-64`).
- Two wordings deliberately left non-exhaustive ("among them", "every uniqueness constraint") so pass 2 could pin `line_code`/`equipment_code` uniqueness without contradiction.

### Pass 2 (inspections, harvest, conditioning)

- 492 lines / 122,004 bytes (**+6,122 chars** attributable to this pass), 23 surgical Edit calls, no rewrites.
- **19 ambiguity-pins, 4 mismatch-revisions.**
- Mismatches corrected: §2.9 rule 36 (carryover evaluates rule 50 `ERR_RETEST_NOT_DUE` BEFORE the generation-ceiling check; the ladder had them reversed — `conditioning.py:314-320`); §3.3 (inspection recording gate order is `ERR_INVALID_REQUEST` planted-date coherence -> `ERR_INVALID_CONTRACT_STATE` -> `ERR_DATE_IN_FUTURE` -> capacity; prose had contract-state and future-date first — `inspections.py:36-48`); §3.4 (harvest gates reordered `ERR_INVALID_WINDOW` -> `ERR_EQUIPMENT_WINDOW_CONFLICT` -> `ERR_HARVEST_WINDOW_NOT_ELAPSED`; prose had put the collision last — `harvest.py:87-98`); §3.5 (completion gate order is `ERR_INVALID_RUN_STATE` -> `ERR_OUTPUT_EXCEEDS_INPUT` -> `ERR_RUN_WINDOW_NOT_ELAPSED` — `conditioning.py:212-219`).
- Ambiguity pins: `equipment_code` (fleet-wide) and `line_code` (plant-wide) uniqueness plus the displaced `inspected_on`-vs-`planted_on` shape check (§2.9 rule 3); the `inspected_on` list filter matches the stored string by plain equality (§2.3); inspector day capacity counts across all contracts and all statuses so a `CLOSED` inspection still holds its slot (§2.10); rogueing threshold reworded to "at or below three" with a zero tolerance yielding an unbounded quotient so such a breach is never rogueable (§3.3, `calc.py:174-179`); `rogueing_declared_on` echoed raw and never compared to `inspected_on`, declaration reads no contract status (§3.3); `equipment_kind` purely descriptive (§3.4); cleanout certification has no state precondition, is re-certifiable, stores `last_cleanout_at` verbatim (§3.4); harvest window endpoints echoed raw (§3.4); the harvest response returns the event, not the minted lot (§3.4); line `status`/`capacity_kg_per_hour` never consulted so an `OUT_OF_SERVICE` line is still schedulable (§3.5); `last_cleanout_variety_id`/`last_run_end_utc` follow the completion act's order, hold the raw `window_end`, and are never rolled back (§3.5); run `input_kg` stored rounded half-up to 2 dp (§3.5); the three treatment fields present-and-null on non-treating runs rather than omitted (§3.5); the completed run's own `version` increments (§3.5); aborting a `PLANNED` run moves only the run (§3.5); reversing a `COMPLETED` run bumps run and lot versions but does not restore the line's cleanout posture or touch the certification axis (§3.5); completion and reversal both answer with the conditioning run (§3.5); the label maximum is the rate's only bound, no lower bound (§3.6); `next_season_year` is an integer 2000-2100 and need not exceed the parent's `season_year` (§3.8); the carryover response returns the successor lot, not the parent (§3.8).
- Flagged as an impl characteristic, not asserted in the PRD: completion re-reads no lot mass, so two runs planned at the same stage on one lot and both completed can drift the mass ledger. §2.11's invariant was left untouched.

### Pass 3 (certification, settlement, cascades)

- Final: 492 lines / **126,171 bytes** (**+4,167 chars** attributable to this pass). 11 edits: **9 ambiguity-pins, 2 mismatch-revisions.**
- All 39 line-groups changed by passes 1-2 survive intact (diff vs PRD_FINALIZED shows 50 groups: their 39 + pass 3's 11). Pass 2's §2.9 rule-36 exception verified present and untouched; §2.11 never opened.
- Mismatches corrected: §2.9 rule 7 / §3.9 approval paragraph — settlement approval's contract-`HARVESTED` gate is displaced below rules 10 and 17, and settlement payment is not contract-status gated at any priority; observable consequence pinned inline (re-approving an `APPROVED` settlement reports `ERR_INVALID_SETTLEMENT_STATE`, not `ERR_INVALID_CONTRACT_STATE` from the now-`SETTLED` contract) — `settlements.py:89-96`, `:114`. §3.7 void paragraph — voiding the last tag changes the contract's `certified_units_total` WITHOUT moving the contract's `version`/`updated_at`; it is the only derived-roll-up write in the system lacking a `touch`, verified against all other call sites — `certification.py:196-203`.
- Ambiguity pins: `sampled_on` echoed verbatim and drawing a `RETEST` on a `TAGGED` lot writes only the lot, leaving tags `ISSUED`, `tagged_bag_count` unchanged, and the contract neither recomputed nor versioned (§3.7, `certification.py:53,64-65`); the four lab measurements and `tested_at` stored/echoed verbatim with no rounding of their own (§3.7, `certification.py:99-103`); `inert_pct` lives on the sample only, the lot has no inert field (§3.7); sample's and lot's `version` each +1 on a pass with no contract row written (§3.7, `certification.py:121-122`); the five tag gates fire in §2.9 priority order — mismatch -> eligibility -> bag fit -> class ceiling -> germination validity — not narration order (§3.7, `certification.py:146-159`); the 6-digit tag sequence is one system-wide counter starting at 1 on boot, never restarted per season year nor scoped to lot/contract/variety, voided numbers not reused, `issued_at` in the §2.4 ISO-ms form (§3.7, `store.py:43,60-61`, `certification.py:164,167`); cascade hop 4 is unconditional so an initial-test failure on an untagged lot still bumps the contract's `version` with the roll-up numerically unchanged, the roll-up filter also requires non-null `final_clean_units`, and hop 1 moves the sample's `version` too (§3.7, `services.py:32-34,112-114`); a PASSING retest on a still-`TAGGED` lot lands it in `PASSED` not back in `TAGGED`, leaves tags and `tagged_bag_count` as-is, writes no contract row, so re-tagging is a separate act (§3.8, `certification.py:116`); superseded prior settlements move in `created_at` order with `version` +1 each and money/`quality_hold`/`dispute_reason` untouched, and supersession happens only after all gates pass so `ERR_NO_SETTLEABLE_LOTS`/`ERR_NET_PAYABLE_NEGATIVE` leave priors and the contract `version` alone (§3.9, `settlements.py:44-61`).

### Closing integrity check (pass 3) — all green
- (a) 492 lines; 126,171 bytes > 122,004
- (b) still ends at `| \`ERR_NET_PAYABLE_NEGATIVE\` | 422 |`
- (c) `cmp` vs PRD_FINALIZED.md differs at byte 3198 — NOT byte-identical, the scan genuinely ran
- (d) all five `## 1.`-`## 5.` headers present (lines 3, 11, 206, 356, 423); §4 has exactly 60 method rows; §5 has exactly 64 `ERR_` rows

### Orchestrator's own verification
- Independently re-ran `wc`, `cmp`, `tail`, and header/row counts: `PRD.md` 108,575 B -> `PRD_FINALIZED.md` 109,050 B -> `PRD_COMPLETED.md` 126,171 B, all 492 lines, ending at the real final table row. Cumulative Step 8+9 growth is +17,596 B (+16.2%) with zero line-count change, i.e. all edits are in-paragraph as required.
- Confirmed Steps 8 and 9 touched no implementation source: the newest file under `implementation/` is dated 2026-09-04T03:40:49Z while the oldest sweep result is 2026-09-04T05:03:15Z, so the green sweep postdates every code edit and remains valid.
- Re-read all eight `results.$i.json`: 118/118 in every round.
- Verified no stray `test_helpers/` or `test_suite/` under `workspace/`, and only one `worklog.md` in the tree (at the task root — no cwd-drift copies).

**PIPELINE COMPLETE.** `workspace/PRD_COMPLETED.md` written; Step 9 is the terminal step.
