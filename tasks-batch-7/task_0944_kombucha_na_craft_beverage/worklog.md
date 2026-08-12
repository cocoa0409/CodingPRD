# Worklog — task_0944_kombucha_na_craft_beverage

Scenario (verbatim): `944. Kombucha & Non-Alcoholic Craft Beverage Production: recipe & batch/SCOBY, fermentation & pH/QA log, keg/bottle run & lot, wholesale/self-distribution account, taproom & growler fill, subscription, compliance & labeling, inventory`

Difficulty target: **beyond-Expert** (user request: "generate task hard than expert level!"). Density phrased per the 0912/0930/0934/0937/0943 recipe — as a calibration parameter in the Step-2 prompt, never as a gate.

Host context at start: 8 cores, load ~0.94 (1-min) / 0.47 (15-min), 0 foreign `prd-bench-local-run` processes, 4 long-lived sibling `claude` sessions (~5h40m, likely mid-pipeline on other tasks). Sweep concurrency to be re-measured at Step 7 (2 waves of 4 baseline, narrower if saturated).

## Step 1: Create task directory — 2026-08-09T10:13:00.000Z

Created `tasks/task_0944_kombucha_na_craft_beverage/workspace`. Index 0944 = highest existing (0943) + 1.

## Step 2: Generate scaffold — 2026-08-09T11:20:00.000Z

All three artifacts are written and lint-clean.

## Output

- `/home/ubuntu/github/CodingPRD/tasks/task_0944_kombucha_na_craft_beverage/SCAFFOLD.yaml` (3410 lines, §1.0–§1.7 + `constants`, `cascades`, `conservation_invariants`, `value_conventions`, `gate_precedence`, `error_precedence`)
- `/home/ubuntu/github/CodingPRD/tasks/task_0944_kombucha_na_craft_beverage/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1977 lines, single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_0944_kombucha_na_craft_beverage/SCAFFOLD_CORNER_DESIGN.yaml` (2619 lines, single key `scaffold_corner_design`)

No sibling task directory was read; the design comes only from the scenario, the seam list, and the skill spec.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_0944_kombucha_na_craft_beverage/SCAFFOLD.yaml
  Difficulty design:  tasks/task_0944_kombucha_na_craft_beverage/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_0944_kombucha_na_craft_beverage/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    88
  §1.1 entities declared:     18
  §1.8 instances scanned:     18
  §1.9 instances scanned:     44
  Calls scanned (§1.8+§1.9):  878

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

All three files also pass `yaml.safe_load` individually.

## Difficulty ledger (H)

| Axis | Count |
|---|---|
| Entities | 18 |
| Endpoints | 88 (59 POST, 29 GET) |
| State machines | 12, **all 12 non-linear** (ScobyCulture cyclic re-verification loop; Vessel CIP cycle; **Batch parallel two-axis** + controlled AT_RISK re-entry; IngredientLot quarantine revert; LabelApproval APPROVED→STALE→SUBMITTED loop; PackagingRun **fan-in join + branch**; FinishedLot **capped re-entry loop**; Keg cycle + two-leg branch; Shipment revert + cascade detour; Subscription capped skip self-loop + pause/resume loop; TaproomFill branch; RecallNotice branch). 72 transitions total. *This is one above the 8–11 target — the extra is RecallNotice, which is the cascade's terminal leg.* |
| Calculations | 17, of which **6 dual-variant across 6 different entity domains** (`batch_abv_estimate`, `lot_best_by_date`, `keg_deposit_settlement`, `subscription_cycle_charge`, `scoby_vitality_score`, `taproom_fill_charge`). Combinatorial modes: (a) `packaging_yield`, (b) `invoice_aging_and_late_fee` (pinned round-per-line), (c) `account_credit_exposure` (pinned 5-step evaluation order) |
| Validation rungs | **80**, sequentially numbered 1–80 |
| Error codes | **34**, every one triggered by at least one §1.8/§1.9 instance (verified programmatically) |
| OCC rules | 3 (`packaging-source-draw-stale-batch`, `shipment-line-add-stale-lot`, `subscription-allocation-stale-lot`) |
| Conservation invariants | 6 (finished-goods units, batch liters, keg deposit dollars, QA flag count, ingredient quantity, self-distribution liters) |
| Cascade max depth | **7** (`ingredient_recall_cascade`); plus depth 4 (`recipe_revision_cascade`) and depth 3 (`lot_release_reallocation_cascade`) |
| Declared constants | **75**; residual ALL_CAPS token list after grepping all three files = **empty** (only enum members remain, and those resolve to §1.1 `constraints`) |
| §1.8 | 9 rules × 2 instances = **18** |
| §1.9 | 9 sections, **46 instances** (44 with full recipes, 2 `excluded_because` stubs) |
| Gate-precedence blocks (G) | 9 ordered blocks; 12 declared error-precedence pairs |

## Reachability audit — defects found and self-repaired (E)

1. **Auto-retirement made the vitality rung dead.** `ScobyCulture.auto_retire_on_vitality_floor` fired at the same `SCOBY_VITALITY_FLOOR` the pitch gate uses, so gate 7 (`ERR_INVALID_STATE`, retired culture) pre-empted gate 9 (`ERR_SCOBY_VITALITY_TOO_LOW`) on *every* input. Moving the auto-retire to a lower threshold would in turn have made the auto-retire itself unreachable (pitching below 40 is blocked). **Repair:** deleted the transition entirely; a worn-out culture stays ACTIVE, the rung fires, and `retire_reason: VITALITY` is now produced by the operator-supplied value on `POST /scoby-cultures/{id}/retire`.
2. **Vessel-overlap rung was unreachable.** A vessel holding a batch is `OCCUPIED`, so the state gate always pre-empted the interval check. **Repair:** `POST /batches` takes an optional back-dated `pitched_at`, and the vessel *retains* its occupancy interval after being freed, so a back-dated pitch into a re-sanitised vessel reaches the half-open interval arithmetic.
3. **Empty-source rung was unreachable.** `start_run` originally required `status == SOURCED`, which implies ≥1 draw, killing the `source_batch_count == 0` boundary. **Repair:** the state gate now admits `{DRAFT, SOURCED}` and the source-count gate at order 5 is what refuses a DRAFT run.
4. **`ERR_LABEL_STALE` at `start_run` was pre-empted by its own cascade.** The recipe-revision cascade aborts DRAFT/SOURCED runs, so any pre-existing run would answer `ERR_INVALID_STATE`. **Repair:** documented (and exercised) that the rung is reached by a run *opened after* the revision; the cascade's `does_not_fire` list now spells out which run states it skips.
5. **`ph_target_hit_day_index` was coupled to the CONFORMING transition**, so a batch whose target-hitting reading was flagged for an unrelated reason could never advance. **Repair:** the stamp is now set by `qa_reading_evaluation` independently of `flagged`.
6. **Dead enum values:** `Batch.ferment_stage.F1_COMPLETE` and `TaproomFill.fill_status.VOIDED` had no producing transition — both removed.
7. **`OCC endpoint must bump the parent version`:** shipment-line add originally did not touch the lot (confirm reserved). **Repair:** reservation moved to line-add, which is also the more honest inventory model.
8. **Unused constants** `COLD_CHAIN_MAX_C_RAW/_PASTEURIZED` were wired into a new computed `FinishedLot.cold_chain_max_c`.
9. **`RecallNotice.trigger_source`** members `INGREDIENT_LOT_QUARANTINE` / `LOT_QUARANTINE` had no stated producer — the `issue_notice` transition now pins the three-way mapping.

Also verified: every §1.8 instance asserts exactly the operation its cited rung/rule names (requirement F — no verb widening); no forbidden concurrency vocabulary anywhere; no `id`-based selector/tie-break (all ordering falls back to `created_at ASC`); every endpoint role resolves to §1.7; instance names unique across both design files; both `excluded_because` stubs cite a real §1.8 instance.

**Known coverage gaps (reachable, just not yet exercised by a design instance):** `IngredientLot.expire_on_clock`, `FinishedLot.recall_lot` / `deplete_lot`, `Keg.empty_keg` / `return_keg_damaged`, `Shipment.pay_shipment`, `Subscription.cancel_subscription`, `RecallNotice.acknowledge_notice` / `notice_overdue`, and `Batch.qa_hard_fail`. These are all straightforward for the unit-test generator to reach from the declared surface.

### Orchestrator verification (independent of the subagent)
- `yaml.safe_load` on all three files: OK.
- Independent ALL_CAPS constant sweep: 75 declared; 6 residual tokens, of which 4 are `ERR_*` codes and 2 (`GENERATION_CAP` as a `retire_reason` enum member, `ON_DEPOSIT` as a `Keg.status` enum member) are enum members with §1.1 `constraints` backing. **No undeclared numeric constant.**

## Step 3: Copy INSTRUCTION.md — 2026-08-09T11:22:00.000Z

`cp ./INSTRUCTION.md tasks/task_0944_kombucha_na_craft_beverage/workspace/INSTRUCTION.md`

## Step 4: Generate PRD — 2026-08-09T11:38:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_0944_kombucha_na_craft_beverage/workspace/PRD.md` (704 lines, 139 KB), authored in 13 bounded appends and assembled from parts; tail verified — the document ends at the §5 error table with no audit footer.

## Coverage ledger (rendered / declared)

| Item | Rendered | Declared |
| --- | --- | --- |
| Constants (with a concrete value in prose) | 75 | 75 |
| Validation rungs (all numbered, in relative order, §2.9) | 80 | 80 |
| Error codes (each with its raising condition in §2/§3 + §5 table) | 34 | 34 |
| Endpoints (§4 table, 4 columns) | 88 | 88 |
| State machines | 12 | 12 |
| Transitions (from/to + preconditions + side effects) | 72 | 72 |
| Calculations (formula, branch selector, rounding order) | 17 | 17 |
| Cascades (all hops **and** all `does_not_fire` legs) | 3 | 3 |
| Conservation invariants (incl. both keg side conditions) | 6 | 6 |
| Gate-precedence ladders | 9 | 9 |
| Error-precedence pairs (§2.8 table) | 12 | 12 |
| OCC / concurrency rules | 3 | 3 |
| Entities / field names / roles | 18 / 181 / 7 | 18 / 181 / 7 |

**Hard contracts** — Contract 1 field coverage: 181 entity fields, all POST body identifiers, all GET query params → 0 missing. Contract 2 rule coverage: all eight categories walked, 0 missing. Contract 3 §3 path purity: 1217 backtick tokens scanned in §3, 0 leading-`/`, 0 bare-method, 0 method+path. §2.2 verified byte-identical to `section-2.2-response-structure.md`. Neither DIFFICULTY nor CORNER design file was opened, and no sibling task was read.

## Scaffold contradictions found (both readings stated, one carried forward)

1. **Keg `fill_liters` — supplied or constant?** The endpoint declares `fill_liters` as a request input, rung 22 requires it strictly positive, and rung 68 caps it at `keg.capacity_liters`; but `Keg.fill_keg`'s side-effect list says `fill_liters = KEG_FILL_LITERS` (19.5), which would make the input inert. **Carried forward: caller-supplied**, validated strictly positive and at or below `capacity_liters`, stored as given — with 19.5 L named as the standard keg charge (the same figure `packaging_yield` uses). Three independent signals back this reading, including `keg_remaining_volume`'s worked example (`fill_liters` 19.50 → 19.00 on tap).

2. **`Account.outstanding_balance` — derived or accumulated?** The entity field and `account_credit_exposure` STEP 3 define it as a re-derivation (sum of `subtotal + late_fee` over the account's `DELIVERED` shipments), while `deliver_shipment` says "increased by `subtotal`" and `pay_shipment` says "decreased by `subtotal`". Those increments coincide with the derivation only when `late_fee` is 0 — true at delivery, not necessarily at payment. **Carried forward: the re-derivation is authoritative**, and §3.9 additionally states both the delivery increase and the payment decrease, framing them as the events that move a shipment into and out of the `DELIVERED` set.

3. **`Batch.terminal_states` mixes axes.** The list `[PACKAGED, DUMPED, NONCONFORMING]` draws two members from `ferment_stage` and one from `qa_disposition`, on a machine explicitly declared `shape: parallel`. **Carried forward per axis**: `PACKAGED` and `DUMPED` terminal on the process axis, `NONCONFORMING` terminal on the quality axis — never as one flat terminal set.

Also carried verbatim rather than resolved: gate 8 of the packaging-run-start ladder nominates `error_id: ERR_LABEL_STALE` while its own gate text routes `DRAFT`/`SUBMITTED` approvals to `ERR_INVALID_STATE`. Both codes are stated with their respective triggering label statuses, exactly as the scaffold words it.

### Orchestrator verification (independent of the subagent)
- 88 endpoint rows in §4; 34 error rows in §5; the set of distinct `ERR_*` tokens in PRD.md equals the scaffold's set exactly (the scaffold's one extra, `ERR_XXX`, is the response-envelope placeholder).
- Rung numbers 1..80 all present in §2.9 with no gap.

## Step 5: Generate unit tests — 2026-08-09T12:15:00.000Z

*(launched concurrently with Step 6 in a single assistant message; `implementation/` did not exist when this subagent started and it was forbidden from reading it)*

Complete. Here is the report.

## Files written

**`test_helpers/`** (2,709 lines)
| file | lines | contents |
|---|---|---|
| `types.py` | 600 | 24 status/role enums, 18 entity TypedDicts. `QaReading` deliberately omits `updated_at`/`version` (PRD §2.4 append-only exception) |
| `api_client.py` | 355 | `ApiClient(GenericApiClient)`, one method per declared endpoint (88) |
| `api_errors.py` | 83 | 34 `ApiErrorId` members + HTTP map, registered with the framework |
| `assertions.py` | 341 | `assert_same_instant` / `parse_instant` / `assert_utc_date`; `assert_money`/`assert_liters`/`assert_abv` (tolerance 0.005, tighter than the PRD's 2-dp last digit); per-entity assertions; all six conservation invariants |
| `constants.py` | 142 | every PRD threshold + `required_label_elements()` |
| `factories.py` | 201 | per-resource payload factories, input fields only |
| `test_users.py` | 85 | distinct `X-User-ID`s per actor (`op-1`/`op-2`, `qa-1`/`qa-2`, `co-alice`/`co-bob`, …) + `make_subscriber_headers(subscription_id)` for the one entity-backed role |
| `fixtures.py` | 853 | the shared production walk plus `build_ready_batch`, `build_held_lot`, `build_released_lot`, `build_sourced_run`, `build_draft_run`, `build_at_risk_batch`, `build_raw_and_pasteurized_lots`, `build_two_source_blend`, `build_ingredient_exposure_chain`, commercial/keg/taproom tiers |
| `__init__.py` | 49 | barrel export |

**`test_suite/`** (2,992 lines, 10 files + conftest) — `test_01_recipes_and_labels` … `test_10_platform_rules`.

**`def test_` count: 81.** Whole suite compiles (`py_compile` + pyflakes clean) and `pytest --collect-only` collects all 81.

## Coverage

- **Queue A (difficulty): 18/18 instances translated**, every one with ≥2 tests (37 tests). 0 skipped.
- **Queue B (corner): 43/44 non-stub instances translated** (44 tests). Both `excluded_because:` stubs verified — each points at `combinatorial_formula / late_fee_rounds_per_line_before_summing`, which exists — and neither was emitted.
- **1 skip, with reason:** `Corner/entities/batch_system_fields_supplied_by_the_client_are_input_ignored`. It asserts that a pitch smuggling `ferment_stage`/`qa_disposition` into the body answers `ERR_VALIDATION`. No PRD sentence says an *undeclared* input field is rejected — rung 19 only requires declared required fields to be present and correctly typed. Two PRD-only readers split (ignore unknown keys → 201, vs reject → 400), so unique derivability fails. Gap left as a gap.

An audit script verified every docstring carries exactly one `Design:` tag resolving to a real instance, and that every ≥8-word quoted citation survives a whitespace-normalised literal match against `PRD.md`. **0 problems.** No `skip`/`skipif`/`xfail` anywhere.

## Near-miss register (F)

| # | test | distance from edge | verdict |
|---|---|---|---|
| 1 | self-distribution ceiling (`test_the_self_distribution_ceiling_blocks_the_confirm_before_the_credit_test`) | ceiling: 95.0 L over 4000.0 | **Re-targeted.** The index used `credit_limit` 5000.00, so the "and NOT `ERR_CREDIT_LIMIT_EXCEEDED`" claim was vacuous — the fiscal rung could never fire. Lowered to 100.00 against a 210.00 subtotal, so both rungs now trip and rung 8 must genuinely pre-empt rung 9. |
| 2 | release ladder (`test_the_hold_window_the_segregation_test_and_the_credit_gate_in_that_order`) | hold: 48 h early | **Re-targeted.** The index released as `qa-1`, so only the hold rung tripped and the cited precedence was agreement-by-construction. The too-early release now acts as `op-1` — both too early *and* self-approved — which is exactly the PRD's own worked case ("a release that is both too early and self-approved answers `ERR_LOT_HOLD_PERIOD`"). |
| 3 | `test_the_yield_floors_the_container_count_from_the_rounded_net_liters` | — | **Recorded, not resolved.** No instance in either index supplies a `gross_liters` where round-then-divide differs from divide-then-round (100.00→97.0 and 45000.00→43650.0 are both exact), so the PRD's "intermediate rounding is load-bearing" clause is *untestable by construction* from the index. I swapped that quote out for the container-size/floor/min sentences, which the data does discriminate (258 vs the 200 cap). The rounding-order half is uncovered. |
| 4 | `test_the_three_shipment_totals_sum_the_already_rounded_line_values` | — | **Recorded.** 8 × 5.45 = 43.60 exactly, so round-per-line and sum-then-round agree; this test pins values, not order. The order *is* load-bearing in the sibling `late_fee` test (1.95 vs 1.96, one cent), so the rule is covered by the pair. |
| 5 | `test_an_immediate_retap_and_an_oversubscribed_box_are_both_refused` | 15 min below the boundary | Kept. Re-tap at exactly `last_untapped_at` (0 min elapsed vs the 15-minute buffer). Discriminates against "no buffer", not against an at-or-after/strictly-after flip. Reaching the exact boundary needs sub-day clock granularity the index never exercises. |
| 6 | `test_a_culture_below_the_vitality_floor_refuses_the_pitch_and_stays_active` | 2 points (38 vs floor 40) | Kept. 38 is the nearest *reachable* value below the floor — vitality moves in 6-point steps, so no closer case exists. Discriminates. |
| 7 | `test_a_keg_returned_on_day_ninety_one_forfeits_forty_percent` | 1 day | Kept; an off-by-one on the 90-day window flips refund 45.00 ↔ 27.00. |
| 8 | `test_the_divergence_rung_outranks_the_label_class_rung` | 0.01 inside tolerance | Kept and load-bearing on both halves: run A (0.04 divergence) must fall through to the class rung, run B (0.11) must be pre-empted by the divergence rung while *also* tripping the class rung. |
| 9 | exact-boundary tests | 0 | `abv == 0.50` → ALCOHOLIC; ingredient expiry exactly clock+7 refused / +8 accepted; pitch at exactly 90 % accepted / 91 L refused; pause touching at exactly `2026-05-11` conflicts / `2026-05-12` accepted; pitch at exactly the retained `occupancy_end_at` accepted / one day inside refused; `best_by` exactly clock+14 refused; generation exactly 8 refused. All paired pass/fail, all discriminating. |

## Friction list (G)

1. **`raw_and_pasteurized_runs_from_one_batch_get_different_best_by_dates` is unreachable as scripted.** Its `setup_api_calls` approve two label revisions on one recipe *before* either run starts, but PRD §3.1 says approval pushes "any *other* revision of the same recipe that was `APPROVED`" to `STALE`, and §2.8 rung 8 then refuses the raw run's start with `ERR_LABEL_STALE`. Not an ambiguity — the index contradicts the PRD. I re-sequenced (`build_raw_and_pasteurized_lots`): complete the raw run, *then* approve the pasteurized artwork. Both lots still package on 2026-05-10, so the asserted 2026-08-08 / 2027-02-04 pair is unchanged. **Cost: 0 tests.**
2. **Scaffold-only exemption on the divergence rung.** `state_machines.PackagingRun.complete_run` adds "…unless the label approval already carries `abv_class` `ALCOHOLIC`" to the divergence precondition. That clause appears nowhere in the PRD (§2.8 rung 6, §2.9 rung 51 and §3.6 all state the tolerance unconditionally). I followed the PRD. Verified no test depends on the disputed reading: the only ALCOHOLIC-label completion has divergence 0.04 (inside tolerance either way), and the divergence-failure case uses a NON_ALCOHOLIC label. **Cost: 0 tests.**
3. **Pre-set values of `approved_by_user_id` / `approved_recipe_version_number`.** The corner instance asserts both are `null` before approval. The PRD says when they are *stamped* but never states a pre-approval value — a default-value silence. Dropped those two sub-assertions; kept the error, `status == SUBMITTED`, and the recipe's `active_label_approval_id == null` (which §3.1 *does* state at creation). **Cost: 0 tests.**
4. **`confirmed_at == null` on a refused confirm.** Same shape: §3.9 says confirmation *stamps* `confirmed_at`, never that it is null beforehand. Dropped; kept `status == DRAFT`. **Cost: 0 tests.**
5. **`the_logical_clock_may_not_move_backwards` asserts "a subsequent GET on any resource still reports the clock as 2026-05-06"** — but no read surface in the PRD exposes the clock. Substituted a re-set to the *same* instant, which §2.4 explicitly permits ("a value equal to the current clock is accepted") and which returns `current_utc`. **Cost: 0 tests.**
6. **OCC placement wording.** §2.6 says the version check sits "after the state gate belonging to the *requesting* side", while the §2.8 ladders number it rung 6 (before the parent-side state gate). These agree once "requesting side" is read as run/shipment/subscription; recorded but not pre-judged, and no test depends on the other reading. **Cost: 0 tests.**
7. **Ingredient-use ferment-stage gate.** Rung 30 lists `ferment_stage` requirements per action but never names `POST /batches/{id}/ingredient-uses`. To avoid depending on either reading, `build_ingredient_exposure_chain` records the consumption immediately after the pitch (batch `F1_ACTIVE`), matching the index's own ordering. **Cost: 0 tests.**

## Step 6: Generate implementation — 2026-08-09T12:15:00.000Z

*(launched concurrently with Step 5 in a single assistant message; forbidden from reading `test_suite/` and `test_helpers/`)*

Implementation complete and verified. Server, orphans, and caches cleaned up.

## What was built

`/home/ubuntu/github/CodingPRD/tasks/task_0944_kombucha_na_craft_beverage/workspace/implementation/` — Python + Flask, in-memory only (dicts in-process, no DB/file/pickle), no seeded data. 26 files, 4,936 lines:

| Module | LoC | | Module | LoC |
|---|---|---|---|---|
| `start.sh` | 13 | | `kb/routes_ingredients.py` | 140 |
| `app.py` | 76 | | `kb/routes_taproom.py` | 166 |
| `kb/auth.py` | 43 | | `kb/routes_lots.py` | 188 |
| `kb/errors.py` | 62 | | `kb/routes_accounts.py` | 200 |
| `kb/app_factory.py` | 71 | | `kb/routes_recipes.py` | 242 |
| `kb/store.py` | 80 | | `kb/routes_cultures.py` | 246 |
| `kb/envelope.py` | 85 | | `kb/routes_qa.py` | 280 |
| `kb/lookup.py` | 85 | | `kb/routes_shipments.py` | 299 |
| `kb/constants.py` | 150 | | `kb/routes_kegs.py` | 306 |
| `kb/util.py` | 157 | | `kb/routes_batches.py` | 317 |
| `kb/validate.py` | 194 | | `kb/cascades.py` | 327 |
| `kb/routes_clock.py` | 61 | | `kb/calc.py` | 357 |
| `kb/__init__.py` | 0 | | `kb/routes_packaging.py` | 371 |

## B. Completeness gate

**PRD §4 declared: 88 (method, path) pairs. `app.url_map`: 88. MISSING: 0. EXTRA: 0.** Diffed as pairs, not paths. Additionally: all 26 modules `ast.parse` clean; all 88 endpoints probed for latent crashes (none); RBAC probed 88 endpoints × 7 roles and **matches the PRD role table exactly**.

## E1. Timestamp rendering — three cases

One renderer (`util.render_instant`); the serializer routes every `datetime` through it, so no instant is rendered two ways. Milliseconds always present, suffix always `Z`.

- **(a) Caller-supplied** — parsed to an aware UTC instant, echoed as `YYYY-MM-DDTHH:MM:SS.mmmZ` with the supplied time of day preserved (`2026-05-01T00:00:00Z` → `...T00:00:00.000Z`; bare `2026-05-01` → same). Applies to `pitched_at`, `reading_at`, `received_on_date`, `expiry_date`, `subscriber_birth_date`, `customer_birth_date`, `to_iso8601`. **Sole exception:** the pause boundaries (`current_pause_start_date`/`end_date`, `pause_windows[]`) are normalised to `00:00:00.000Z` — PRD §2.4 names "a pause boundary" as a date.
- **(b) Derived** — whole-day/hour arithmetic preserving time of day: `occupancy_end_at`, `due_date`, `ack_deadline_at`. **Exception:** `best_by_date` (named a date in §2.4) — base normalised to midnight, shelf window added in whole days, re-normalised, so always `...T00:00:00.000Z`.
- **(c) Server-stamped** — the **logical clock verbatim**, never wall clock: `created_at`, `updated_at`, `cip_started_at`, `cip_completed_at`, `f1_completed_at`, `f2_started_at`, `f2_completed_at`, `approved_at`, `packaged_at`, `released_at`, `voided_at`, `tapped_at`, `last_untapped_at`, `issued_at`, `returned_at`, `poured_at`, `inspected_at`, `confirmed_at`, `delivered_on_date`, `paid_at`, `acknowledged_at`, `last_reverified_at`, `cycle_start_date`, and `meta.api_request_timestamp`.

## E2. Enum-error routing

**The catalogue contains no distinct enum-validation code** (no `ERR_INVALID_ENUM`). Per rung 20, **every enum-typed field routes to `ERR_VALIDATION` (400)**. Closed list: body — `style`, `intended_abv_class`, `abv_class`, `outcome`, `retire_reason`, `ingredient_type`, `reading_type`, `format`, `condition`, `channel`, `container_type`; query filters — `status`, `state`, `ferment_stage`, `qa_disposition`, `reading_type`, `line_status`, `deposit_state`, `fill_status`. **Notable exclusion: `X-User-Role`.** An unrecognised role does *not* route here — §2.1/rung 2 sends it to `ERR_UNAUTHENTICATED` (401), "an unknown role is treated as no credential at all". No other field routes anywhere else.

## D. Boot robustness

`find_spec` presence checks first → own `SO_REUSEADDR` socket bound in a bounded loop (100 × 50 ms, then a loud failure) → *then* Flask import and app construction → `make_server(host, port, app, threaded=True, fd=sock.fileno())` so Werkzeug never binds again. Listening socket held in a module-level ref so the fd is not GC'd. `start.sh` reads `$PORT` (default 10000), binds `0.0.0.0`, guards `pip install` on a cheap import, and `exec`s in the foreground. No startup sleep. **Stress-tested: 40 SIGKILL→relaunch cycles on one port, 0 failures, 0 orphans**; state confirmed fully wiped on reboot (clock back to `2026-05-01T00:00:00.000Z`, all collections empty).

## Verification

Four hand-written suites (~230 assertions) all green, each on a fresh server: worked examples reproduce exactly — yield 100.00→97.00→258 bottles, blend `best_by` 2026-08-18 vs single-source 2026-08-24, late fee 1.95 (round-per-line) not 1.96, credit exposure 500.00 accepted, growler charges 11.22/13.22/9.72, deposit 27.00/18.00, proration 31.50, projected ABV 0.54/0.41. Boundary rungs confirmed: ±0.05 pH regression, exactly-60h gap, 90%-capacity, 72h CIP, 48h hold, 15-min re-tap, 0.20 L residual, exact-0.05 divergence, touching pause endpoints, half-open occupancy touching the retained end. All three cascades verified end-to-end, plus declared precedence (divergence > class mismatch, hold period > SoD, vitality rung before the vessel rungs).

## G. Open items — claims to verify by reading the code, not settled facts

1. **Hop 5(c) breaks conservation invariant 1.** PRD §2.12 5(c) adds 1 to `destroyed_units` for an emptied FILLED keg with no counterpart, but the fill already moved that unit `on_hand`→`poured`, so the sum exceeds `units_produced` by 1. Readings: (i) literal, destroyed +1 only; (ii) conserving, destroyed +1 and poured −1. **Implemented (i)** (`cascades.hop5_unwind_lot`).
2. **`flagged_reading_count` vs hard-fail #2.** §3.5 says a hard-fail reading increments it, but hard-fail #2 (`day_index > 14`, no pH stamp) yields no `flag_reason` so `flagged` is false — incrementing would break invariant 4. **Implemented the invariant**: both counters re-derived from the log after each append.
3. **Void leaves the ingredient lot's status untouched** (literal §3.4; no "unconsume" transition). Consequence: a CONSUMED lot with restored availability stays CONSUMED and is not swept by the clock's expiry sweep. Alternative: recompute status.
4. **`delivered_on_date` / `cycle_start_date` are the raw clock instant, not midnight-normalised** — §3.9/§3.10 say "stamps with the logical clock", against §2.4's "such as" date list. Matters only if the clock is moved to a non-midnight value (changes `due_date`, hence `days_past_due`).
5. **`outstanding_balance` re-derived, not incremented.** §3.9 calls the re-derivation "authoritative" but also says payment makes it fall by `subtotal`; these disagree when `late_fee > 0`. Implemented the re-derivation (on deliver, pay, confirm, and `GET /accounts/{id}`), so it grows as late fees accrue.
6. **Missing required id → `ERR_VALIDATION`, not 404.** Existence (rungs 5–18) precedes shape (19), but resolution presupposes a value. Implemented: absent/non-string id → 400; present but unresolvable → the family's 404.
7. **Codes the PRD never pins** (my choices): EXPIRED-status ingredient use → `ERR_INGREDIENT_EXPIRED` (other bad statuses → `ERR_INVALID_STATE`); `advance-to-f2` with no F1 reading → `ERR_PH_WINDOW_MISSED`; sign-off when the latest reading is still flagged → `ERR_INVALID_STATE`; run creation violating `pasteurization_required` → `ERR_LABEL_CLASS_MISMATCH`; keg fill with `on_hand − reserved < 1` → `ERR_INSUFFICIENT_LOT_UNITS`; inspect on a non-CUSTOMER_GROWLER → `ERR_INVALID_STATE`; pause `end_date < start_date` → `ERR_VALIDATION`; re-void → `ERR_INVALID_STATE`; credit-hold on a non-ACTIVE account → `ERR_INVALID_STATE`.
8. **Subscriber ownership also enforced on `GET /subscriptions/{id}` and `.../allocations`** — rung 4 names only the four writes, but the RBAC matrix says "for their own subscription".
9. **`pre_quarantine_status` nulled on ingredient clearance, retained on finished-lot clearance** — implemented the asymmetry literally as written.
10. **Re-instated allocations get `reversal_reason` set to null** (not stated; nulling is what makes the "at most twice" cap behave on a second quarantine/clear cycle).
11. **Reachability claim:** the divergence check is skipped when no source carries a `projected_abv_pct`; I claim that is unreachable (READY_TO_PACKAGE implies the stamp was made at advance-to-f2).
12. **Reachability claim:** a `FILLED` keg with `deposit_state != NONE` at tap time is unreachable (fill resets to NONE; untap comes from ON_TAP which required NONE). The gate is still enforced.
13. **Clock sweep 3 bumps no versions** (treated as derivation); the EXPIRED and OVERDUE sweeps do bump.
14. **Recall does not credit `credit_balance`** — unlike quarantine hop 5(b), §3.7's recall says nothing about it. Implemented literally.
15. **`required_elements` recomputed from the revision's own `abv_class`/`pasteurized`** (the calculation's `input_set`), not from recipe fields as §3.1's stale-path wording suggests; idempotent either way.
16. **`max_units_requested` is not range-checked** (absent from rung 22's list), so 0 is accepted and yields `units_produced` 0. Similarly, a payment is not required to name a shipment belonging to the path account — not declared anywhere.

### Orchestrator verification (independent of both subagents)
- `def test_` count = **81**, `Design:` tag count = **81** (1:1).
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere in `test_suite/` or `test_helpers/` (the only `skip` tokens are the subscription domain's own skip feature).
- `grep -rE "sqlite|pickle|json\.dump|open\(...'w'|/tmp|shelve"` over `implementation/*.py` → **empty**. In-memory only, no seeded data.
- `compileall` clean over `implementation/`, `test_helpers/`, `test_suite/`.
- **Independent (method, path) route diff** — booted the app, normalised `<conv:name>` → `{name}`, diffed against the 88 rows of PRD §4: impl 88 / PRD 88, **MISSING 0, EXTRA 0**.

## Step 7: Run tests and iterate — 2026-08-09T12:35:00.000Z

All 8 rounds clean and verified.

## Summary

**Iterations run: 2**

| # | WAVE | Result |
|---|---|---|
| 1 | 2 | 80/81 in rounds 1–6, 81/81 in rounds 7–8 (7–8 picked up the mid-sweep fix) |
| 2 | 2 | **81/81 in all 8 rounds** |

Host was measurably clean before each sweep: load 0.69 → 6.74 (decaying from my own sweep), **zero foreign `prd-bench-local-run` processes**, zero orphan servers scoped to this task. No exit-143s, no "could not be restarted" errors, so no saturation disproof was needed. WAVE stayed at 2 throughout (self-generated load peaked at 8.07, so WAVE=4 was never justified).

**Tests deleted: none.** The single failure survived both STEP-1 sub-checks (PRD verbatim-covers it, and it is uniquely derivable), so it was a STEP-2 test bug, not a silence.

**Fixes applied to `test_suite/`: 1**
- `test_suite/test_02_cultures_and_vessels.py` :: `test_a_culture_below_the_vitality_floor_refuses_the_pitch_and_stays_active` — the test pitched 7 batches to drive `vitality_score` to 38, left all 7 in `F1_ACTIVE`, then retired the culture. PRD.md:369 states *"Manual retirement moves an `ACTIVE` culture to `RETIRED`, but only when no batch of that culture is currently in `ferment_stage` `F1_ACTIVE` or `F2_ACTIVE`."* The PRD-faithful implementation correctly answered `ERR_INVALID_STATE`/409. Fixed the **setup**, not the assertion: the test now captures the 7 pitched batches and dumps them before retiring, which PRD.md:424 sanctions (*"A batch may be dumped from `F1_ACTIVE`, from `F2_ACTIVE` or from `READY_TO_PACKAGE`"*) for `ProductionOperator` (PRD.md:602). Every original assertion is untouched — the `ERR_SCOBY_VITALITY_TOO_LOW`/422 check, the `pitch_count == 7`, `vitality_score == 38`, `state == ACTIVE` triple, the spare vessel staying `SANITIZED`, and the terminal `RETIRED`/`VITALITY` pair all still run.

**Fixes applied to `test_helpers/`: none.**

**Fixes applied to `implementation/`: none.** The implementation was correct as generated; no PRD-required check was stripped.

### Clean-sweep verification (all six pass)
1. All 8 `results.N.json` present and parseable; each carries **81 individual test rows**, `passed=81 failed=0 errors=0 skipped=0`.
2. Test-name sets **identical across all 8 rounds** (81 unique names; collection order identical too).
3. `grep -c "def test_"` over `test_suite/` = **81**, matching every round's `collected 81 items` (no deletions).
4. **No** `pytest.mark.skip` / `xfail` / `skipif` / `importorskip` anywhere in `test_suite/` or `test_helpers/` (the bare `skip` grep hits are only the domain's `skip_subscription` / `skips_used_this_year`).
5. `grep -rE "sqlite|pickle|json\.dump|/tmp|shelve" implementation/` → **empty**. `kb/store.py` resets every collection to `{}` at construction; nothing seeded.
6. Each `round.N.log` contains `Killed` exactly once, immediately after the first test's name and followed by `PASSED` — the expected per-test-server swap, not a crash.

### Step-6 reachability claims — both verified by reading the code

**(i) "divergence check skipped when no source carries a `projected_abv_pct` is unreachable" — CONFIRMED.**
`projected_abv_pct` has exactly two write sites repo-wide: `kb/routes_batches.py:173` (init to `None`) and `kb/routes_batches.py:235` (in `advance_to_f2`). It is never reset to `None`. `advance_to_f2` sets it unconditionally alongside `ferment_stage = "F2_ACTIVE"` (`routes_batches.py:228,235`), and `kb/calc.py:52-58` `batch_projected_abv` has no `None` return path. `READY_TO_PACKAGE` is written only at `routes_batches.py:261` in `complete_f2`, gated on `F2_ACTIVE` (`:246`) — so the stamp always precedes it. Sources can only enter a run via `add_source_draw`, gated on `ferment_stage == "READY_TO_PACKAGE"` (`kb/routes_packaging.py:121`), and the run is frozen to draws once started (`:112` allows only `DRAFT`/`SOURCED`, while `complete_run` requires `IN_PROGRESS` at `:229`). `start_run` further requires `source_batch_count >= 1` (`:171`) and re-checks every source is `READY_TO_PACKAGE` (`:177`). Hence at `routes_packaging.py:247` the `projections` list is always non-empty, and the `if projections:` false branch is dead.

**(ii) "a `FILLED` keg with `deposit_state != NONE` at tap time is unreachable" — CONFIRMED.**
`deposit_state` has exactly four write sites repo-wide: `kb/routes_kegs.py:69` (create → `NONE`), `:119` (fill → `NONE`), `:202` (issue → `CHARGED`), `:242` (return → `REFUNDED`/`FORFEITED`); `kb/cascades.py:137` only *reads* it. `status == "FILLED"` has exactly two write sites: `routes_kegs.py:115` (fill, which sets `deposit_state = "NONE"` four lines later at `:119`) and `:166` (untap, gated on `status == "ON_TAP"` at `:164`). `ON_TAP` is written only at `:150`, itself gated on `deposit_state == "NONE"` at `:138`. No deposit write can land while a keg is `ON_TAP`: fill requires `IN_STOCK`/`EMPTY`/`RETURNED` (`:99`), issue requires `FILLED` (`:181`), return requires `ON_DEPOSIT` (`:228`). The only other keg-status writers, `kb/routes_taproom.py:158` and `kb/cascades.py:110`, both write `EMPTY`. Therefore `status == "FILLED"` implies `deposit_state == "NONE"`, and the `raise` at `routes_kegs.py:138-141` is unreachable.

Neither dead branch is a defect — both are defensive guards that restate a PRD rung the state machine already enforces upstream, and neither is exercised by any test.

### Orchestrator verification (independent of the subagent)
Parsed all 8 `results.N.json` directly: each has **81 individual rows, 81 passed, 0 non-pass**; the set of test names is **identical across all 8 rounds** (81 unique names); `def test_` count on disk is still **81** (confirming 0 deletions).

## Step 8: Finalize PRD — 2026-08-09T12:50:00.000Z

*(Step 8 ran: Step 7 was not a zero-fix exit — 1 `test_suite/` fix over 2 iterations. The hand-off inlined as `<step_7_diff>` had two parts: part A the Step-7 fix record, part B the 14+3 PRD silences/contradictions the implementation generator recorded at generation time.)*

Done. `PRD_FINALIZED.md` written.

## Scale
`PRD.md` 704 lines / 139,544 bytes → `PRD_FINALIZED.md` 708 lines / 150,027 bytes (**+4 lines, +0.57 %**; +7.5 % by bytes, since most edits extend existing paragraphs in place). 22 edits, all in existing sections; no new sections.

## Changes (one per edit)

| § | kind | what changed | impl anchor |
|---|---|---|---|
| 2.1 identity semantics | revise | Subscriber ownership comparison also covers the single-subscription read and the allocation listing | `kb/routes_subscriptions.py:227,256` |
| 2.9 rung 4 | revise | rung 4 names `GET /subscriptions/{id}` and `.../allocations`; comparison precedes resolution, so a wrong-owner id is 403 whether or not it exists | `kb/auth.py:37-43`; `routes_subscriptions.py:96,137,160,197,227,256` |
| 2.4 timestamps | revise | only `best_by_date` + the two pause boundaries are midnight-normalised; `received_on_date`, `expiry_date`, `subscriber_birth_date`, `customer_birth_date`, `delivered_on_date`, `cycle_start_date`, `due_date` carry raw instants | `routes_shipments.py:202-205`, `routes_subscriptions.py:81,106-107,183`, `routes_ingredients.py:50-51`, `calc.py:117` |
| 2.4 clock sweeps | insert | sweeps 1 and 2 bump `updated_at`/`version`; sweep 3 and all read-time re-derivations bump nothing | `routes_clock.py:38,47,53` vs `50-53` |
| 2.7 not-found families | insert | absent/null/non-string/blank **required** body id → `ERR_VALIDATION` where its existence rung would sit; optional ids (`parent_culture_id`, allocation `finished_lot_id`) treated as unsupplied when absent/null | `routes_recipes.py:30-35`; `lookup.py:11-17`; `routes_cultures.py:38-40`; `routes_subscriptions.py:303-305` |
| 2.11 invariant 1 | revise | hop 5(c) is the one declared exception: `destroyed_units +1` with no `poured_units −1`, so the four buckets exceed `units_produced` by one per emptied keg | `cascades.py:109-113` |
| 2.12 re-allocation hop 2 | revise | re-instated allocation has `reversal_reason` cleared to null; that is what makes the cap behave over a second quarantine/clear cycle | `cascades.py:266` |
| 3.1 label submission | revise | `required_elements` recomputed from the revision's **own** `abv_class`/`pasteurized` (not recipe fields), written back, and re-run at approval ahead of the SoD test | `routes_recipes.py:124-143,193,216-217` |
| 3.4 void | revise | void leaves the lot's `status` untouched (no "unconsume"): a `CONSUMED` lot stays `CONSUMED`, cannot be re-drawn, is never swept to `EXPIRED`; re-void → `ERR_INVALID_STATE` | `routes_ingredients.py:125-139`; `routes_clock.py:32-39`; `routes_qa.py:225` |
| 3.5 flag evaluation | revise | `flagged_reading_count` and `temp_excursion_count` **re-derived from the whole log** on every append, never incremented | `routes_qa.py:107-114` |
| 3.5 quality axis | revise | counters follow the re-derivation (hard-fail #2 with no `flag_reason` leaves them alone); `last_flagged_reading_by_user_id` stamped by **every** flagged reading, hard-fails included | `routes_qa.py:124-144` |
| 3.5 sign-off | revise | not-`AT_RISK` → `ERR_INVALID_STATE`; latest reading still flagged → `ERR_INVALID_STATE`; then spent sign-off, then identity, both `ERR_SEGREGATION_OF_DUTIES` | `routes_qa.py:180-199` |
| 3.5 process axis | revise | "no `F1` reading" and "null `ph_target_hit_day_index`" both answer `ERR_PH_WINDOW_MISSED`, in that order, after the two state gates | `routes_batches.py:206-224` |
| 3.6 run creation | revise | wrong-recipe label → `ERR_VALIDATION` then unpasteurized-vs-required → `ERR_LABEL_CLASS_MISMATCH`; `max_units_requested` unguarded by rung 22, 0 accepted → `units_produced` 0 | `routes_packaging.py:59,62-71`, `calc.py:93` |
| 3.7 lot clearance | revise | finished-lot clearance **retains** `pre_quarantine_status` (asymmetric with the ingredient clearance, which nulls it) | `routes_lots.py:99-100` vs `routes_ingredients.py:92` |
| 3.7 recall | revise | recall does **not** credit `credit_balance` and does not touch shipment lines | `cascades.py:308-322` |
| 3.8 keg fill | revise | `on_hand − reserved < 1` → `ERR_INSUFFICIENT_LOT_UNITS`; gate order lot-status → keg-status → format/capacity → units | `routes_kegs.py:97-113` |
| 3.8 inspection | revise | inspect on a non-`CUSTOMER_GROWLER` → `ERR_INVALID_STATE`, after the `REQUESTED` gate | `routes_taproom.py:80-88` |
| 3.9 credit hold | revise | credit-hold accepted only from `ACTIVE`, else `ERR_INVALID_STATE` | `routes_accounts.py:95-98` |
| 3.9 delivery | revise | `outstanding_balance` and `ytd_self_dist_liters` re-derived from scratch, not incremented | `routes_shipments.py:224-227` |
| 3.9 ledger paragraph | revise | re-derivation beats the increment language when `late_fee > 0`; names the four moments it runs | `calc.py:242-257`; `routes_accounts.py:134,158`; `routes_shipments.py:178,225` |
| 3.9 payment (2 spots) | revise | shipment need not belong to the path account; balance loses `subtotal` **plus** the frozen `late_fee` | `routes_accounts.py:104-148` |
| 3.10 pausing | revise | inverted interval → `ERR_VALIDATION`, judged on normalised boundaries **before** the `ACTIVE` state gate | `routes_subscriptions.py:106-111` |

## Diff items I did NOT edit for
- **Part A (test_suite fix)** — the fix corrected the test's setup; `PRD.md:369` already pins the retirement precondition and the impl obeys it. Nothing to pin.
- **Part A (two reachability claims)** — verified independently: `projected_abv_pct` is written unconditionally at `routes_batches.py:235` and `start_run` requires ≥1 `READY_TO_PACKAGE` source (`routes_packaging.py:171,177`), so `calc`'s `if projections:` false branch is dead; `fill_keg` always resets `deposit_state` to `NONE` (`routes_kegs.py:119`), so the tap-time deposit gate at `routes_kegs.py:138-141` is unreachable. Both are defensive restatements of upstream rungs — no observable behavior, no pin.
- **Item 7, first clause (EXPIRED ingredient → `ERR_INGREDIENT_EXPIRED`, other statuses → `ERR_INVALID_STATE`)** — already pinned by §3.4 ("so is one already in `status` `EXPIRED`; both answer `ERR_INGREDIENT_EXPIRED`") and rung 32.
- **Item 15(a) keg `fill_liters` caller-supplied** — already pinned: §3.8 names it as an input and rungs 22/68 already fix strictly-positive and ≤ `capacity_liters`. (Only the *units* code inside the same paragraph was a silence, and that is patched.)
- **Item 15(b)** — same subject as item 5; patched there.
- **Item 15(c) `Batch.terminal_states` per axis** — already pinned per axis: §3.5 makes `NONCONFORMING` terminal on the quality axis and `PACKAGED`/`DUMPED` on the process axis, and rung 30 gates QA readings on the process axis alone. Impl matches exactly (`routes_qa.py:57-61`; `routes_batches.py:273`).

## Per-edit pre-edit search log
I read the entire implementation (all 26 modules, 4,921 lines) before the first edit, so every edit's enumeration was performed against a complete view. Per edit:

- **§2.1 / rung 4** — (a) subject: Subscriber ownership scope. (b) enumerated: `auth.subscriber_owns`, every call site (`pause`, `resume`, `skip`, `cancel`, `read_subscription`, `list_subscription_allocations`), and the two `PlatformAdmin`-only allocation writes. (c) worded as "the target subscription's `id`" rather than touching the `SubscriptionAllocation` clause, which no endpoint exercises — deleting it would have been a change outside the item.
- **§2.4 dates** — (a) subject: date normalisation. (b) enumerated every `*_date` field: `best_by_date` (`calc.py:104-117`), pause boundaries (`routes_subscriptions.py:106-107,143-148`), `received_on_date`/`expiry_date` (`routes_ingredients.py:50-51`), `subscriber_birth_date`, `customer_birth_date`, `delivered_on_date`/`due_date`, `cycle_start_date`. (c) the diff item named only two fields; the sweep found four more raw ones, so the sentence was widened to an explicit two-item normalised list plus a named raw list, and `cycle_start_date`'s skip advance was called out so the "stamped from the clock" phrasing would not be a false universal.
- **§2.4 sweep versions** — (a) subject: which sweeps mutate. (b) enumerated `routes_clock.py` all three sweeps, plus every read-time re-derivation (`read_shipment`, `read_account`, `read_culture`) and every write-time one (`deliver`, `cancel`, `payment`, `add_shipment_line`, `hop5`) to confirm the "derivation ≠ mutation" claim never contradicts a write path. (c) scoped the universal to *sweeps and reads*, so the write paths that legitimately touch after re-deriving stay consistent.
- **§2.7 ids** — (a) subject: missing-identifier code. (b) enumerated all 14 `require_id` call sites, `lookup._get`, `validate.parse_body` passes 1–3, and the two optional-id paths. (c) split the sentence into required vs optional, and stated that a present-but-blank optional id still yields `ERR_VALIDATION` (which `parse_body` does), instead of the simpler-but-false "treated as unsupplied".
- **§2.11 invariant 1** — (a) subject: unit-bucket conservation. (b) enumerated every mutation of the four buckets: `fill_keg`, `deliver_shipment`, `ship_allocation`, `recall_finished_lot`, `hop5_unwind_lot`, `deplete_lot_if_empty`. (c) named hop 5(c) as *the one* exception after confirming the other four are balanced.
- **§2.12 hop 2** — (a) subject: allocation reversal bookkeeping. (b) enumerated `hop5_unwind_lot(b)`, `lot_reallocation_cascade`, `recall_finished_lot`, `cancel_subscription`. (c) added the second-cycle consequence only after confirming hop 5(b) re-sets `LOT_QUARANTINED` on a re-quarantine.
- **§3.1 label** — (a) subject: `required_elements` input set. (b) enumerated `calc.label_required_elements`, `_label_class_gate` and both its callers, plus creation. (c) added "and the same runs at approval" so the approval paragraph is not left implying the gate is submission-only.
- **§3.4 void** — (a) subject: void side effects. (b) enumerated `void_ingredient_use`, `record_ingredient_use` status gate, the clock expiry sweep's status filter, rung 32. (c) stated the two consequences (no re-draw, no sweep) rather than a bare "status untouched".
- **§3.5 counters / stamp / sign-off / advance** — (a) subjects: per-append counters, the flagged-user stamp, sign-off ordering, `ERR_PH_WINDOW_MISSED` scope. (b) enumerated `append_qa_reading` end-to-end, `qa_signoff`, `advance_to_f2`, `complete_f2`, `readings_of`, invariant 4. (c) worded the hard-fail counter behaviour conditionally ("rises when the reading was itself flagged"), because hard-fails #1 and #3 always flag and only #2 may not.
- **§3.6 run creation** — (a) subject: creation gates and `max_units_requested`. (b) enumerated `open_run`, `packaging_yield`, rung 22's field list. (c) said "0 is accepted" rather than "any integer is accepted", leaving negatives under-determined.
- **§3.7 clearance / recall** — (a) subjects: `pre_quarantine_status` lifecycle, recall side effects. (b) enumerated `clear_lot_quarantine`, `clear_ingredient_lot_quarantine`, `quarantine_finished_lot`, `recall_finished_lot`, `hop5_unwind_lot`, `hop6_7_notices`, `exposed_account_ids`. (c) added "the exposure is communicated by the notice" only after confirming `exposed_account_ids` counts `ACTIVE`/`RECALLED` lines on shipments of any status.
- **§3.8 fill / inspect** — (a) subjects: fill gate order and code, inspect container gate. (b) enumerated `fill_keg`, `tap_keg`, `issue_keg`, `open_fill`, `inspect_fill`, `pour_fill`, rungs 35/36/68/77. (c) reordered the sentence to match the code's actual gate order instead of asserting a new order.
- **§3.9 credit-hold / delivery / ledger / payment** — (a) subjects: account-state gate, balance derivation, payment scope. (b) enumerated `activate_account`, `credit_hold_account`, `apply_payment`, `deliver_shipment`, `confirm_shipment`, `read_account`, `calc.recompute_outstanding_balance`, `credit_exposure`, `recompute_self_dist_ledger`, `recompute_shipment_aging`; confirmed `cascades.refresh_account_ledgers` is dead. (c) "four moments" enumerated from the grep of every call site, so the count is exhaustive rather than illustrative.
- **§3.10 pause** — (a) subject: inverted-interval code and its rung position. (b) enumerated `pause_subscription`, `resume_subscription`, `_cycle_paused_days`, rung 64. (c) added "judged on the two normalised boundaries" because the comparison happens after `normalise_date`, so a same-day inverted-time pair passes.

## Sibling-derivation sweep results
Nine families checked; four drifted and were patched:
- **Unit-bucket movers** (5 sites) — only hop 5(c) drifts. Patched.
- **Re-derived counters** (10 counters) — `flagged_reading_count`/`temp_excursion_count` and `outstanding_balance` drift; `completed_cycles`, `ytd_self_dist_liters`, `gross_liters`, shipment totals, `vitality_score`, `open_recall_notice_count` all already match the PRD. Patched the two.
- **`*_date` normalisation** (11 fields) — 7 drift (PRD claimed a blanket normalisation). Patched as one widened sentence.
- **`pre_quarantine_status` lifecycle** (5 sites) — finished-lot clearance drifts. Patched.
- No drift found in: `reversal_reason` assignment (4 sites, only the null-on-reinstate silence, patched under item 10), version-bump-on-mutation (`store.touch` uniform), rounding/`round2` sites, the three OCC rungs, and the per-axis batch terminal states.

### Orchestrator verification (independent of the subagent)
`PRD_FINALIZED.md` = 708 lines / 150,027 bytes vs `PRD.md` 704 / 139,544. Structure preserved: still 5 top-level sections, still **88** endpoint rows in §4 and **34** error rows in §5 — no section added or dropped.

## Step 9: Complete PRD — 2026-08-09T13:00:00.000Z

Done. `PRD_COMPLETED.md` is written.

## Result

- **Source vs output:** `PRD_FINALIZED.md` 708 lines / 150,027 chars → `PRD_COMPLETED.md` 711 lines / 168,821 chars (**+3 lines, +18,708 chars**). All 26 `###` sections and all 140 table rows unchanged; the 3 added lines are one bullet inside §2.2's existing list and one paragraph split inside §2.3. Every other change is an in-paragraph insert or revision (52 replaced lines).
- **Counts:** 47 edits — **43 ambiguity-pins**, **4 mismatch-revisions**.
- Claims were verified against a live server (`probe*.py` against a booted instance), not just by reading.

### Mismatch-revisions (PRD said something the code does not do)
- **§3.5 Flag evaluation** — *mismatch* — PRD restricted the comparison set to readings "strictly earlier"; the code uses `reading_at <= new`, so a reading at the **same instant** is the "immediately preceding" one. Proven live: two F1 readings both at `2026-05-07T00:00:00Z` with pH 3.0 then 3.2 produced `['PH_REGRESSION']` — impossible under a strict-earlier reading. (`routes_qa.py:71`)
- **§2.6 item 3 / §2.8 allocation ladder** — *mismatch* — OCC is claimed to sit at rung 6 "whether the caller names `finished_lot_id` or not". On the implicit path the FEFO selector runs first, so its refusals precede `ERR_STALE_VERSION`. Proven live: implicit + bogus version + short shelf → `422 ERR_SHELF_LIFE_TOO_SHORT`; explicit + bogus version → `412 ERR_STALE_VERSION`. (`routes_subscriptions.py:331-337`)
- **§3.8 Tapping** — *mismatch* — "the allowance is deducted exactly once, at tap time, and never again" reads as once per fill; the code recomputes `remaining_liters` from `fill_liters` on **every** tap. Proven live: 19.5 L fill → tap 19.0 → pour 1.2 → 17.8 → untap → **re-tap 19.0**. (`routes_kegs.py:152`)
- **§3.12 finished-lot listing** — *mismatch* — "doubles as the operator's view of the FEFO release order"; the listing is `created_at` ascending with write order as tie-break and applies none of the selector's tests. (`routes_lots.py:141`)

### Ambiguity-pins, by section
- **§2.1** — insert — whitespace-only headers count as empty; both values trimmed; `X-User-ID` judged first. (`auth.py:11-20`)
- **§2.2** — insert ×3 — `api_request_timestamp` is rendered from the **logical clock**, not wall-clock; `api_request_id` is `req_` + 20 upper-alnum; every optional `reason`/`note`/`change_note` (12 endpoints) is validated then **discarded**; no per-endpoint field projections; non-object JSON body → `ERR_VALIDATION`. (`envelope.py:16-24`, `validate.py:22-28`)
- **§2.3** — insert ×3 — strict integer parsing of `limit`/`offset` (`10.0`, `1e2`, `%2B10`, empty refused; space-padded accepted); out-of-range `offset` yields an empty page; **write-order tie-break** on every `created_at` ordering (never `id`); off-enum filter → 400, id filter matched literally (empty page, not 404), empty filter value = absent; `has_more` formula. (`validate.py:127-183`, `store.py:76-79`)
- **§2.8** — insert — the two shape rungs (`cycle_index` type, then rung-27 uniqueness) sit inside the allocation ladder between rungs 4 and 5, so a duplicate `cycle_index` is reported on a non-`ACTIVE` subscription. Verified live. (`routes_subscriptions.py:307-329`)
- **§2.9 rung 46** — insert — the `EXPIRED` test runs **ahead of** rung 32's state gate, so `EXPIRED` never surfaces as `ERR_INVALID_STATE`. (`routes_qa.py:221-237`)
- **§2.12** — insert ×5 — hop 2: an already-`NONCONFORMING` batch is not written (no version bump) but still feeds hop 3, and an empty hop 2 stops the cascade; hop 5(a): `DRAFT` shipments also get totals recomputed and a version bump, `RECALL_HOLD` gets 0/0.00/`CURRENT`, `reserved_units` floored at 0; hop 7: every exposed account is version-bumped even when its count does not move; recipe hop 2/3: nulling is unconditional but hops 3–4 are skipped when nothing staled, and only *this* revision's staled ids sweep runs; hop 4: version bump **per `source_draws` entry**, so a twice-drawn batch is bumped twice. (`cascades.py:190-250`)
- **§3.1** — insert ×5 — `planned_f2_days > 7` → `ERR_VALIDATION` and it is the only range test (no `planned_f1_days` bound, no `planned_f2_days` floor — `planned_f2_days: 0` accepted, verified live); `target_ph_ceiling` stored rounded, `base_gravity_brix`/`f2_added_sugar_g_per_l` exact (verified: 3.234→3.23, 8.123→8.123); `change_note` discarded (verified absent from the response); label revision's null-initialised fields and the fact that creation runs no gate; `required_elements` write-back survives a refusal without a version bump; approval bumps the recipe's own `version`.
- **§3.2** — insert ×2 — retirement blocked by an in-flight batch → `ERR_INVALID_STATE` (409), `ACTIVE` gate first; culture-failure cascade skips already-`NONCONFORMING` batches without writing them and skips the run sweep when nothing is reached.
- **§3.4** — insert ×4 — `pitched_liters` rounded before the 90 % comparison, ceiling unrounded; `EXPIRED`-first ordering restated in business context; `quantity_used` cap judged last and on the rounded value; a consumption record does **not** write the batch and returns the `BatchIngredientUse` at 201; a void bumps both the record's and the lot's `version`.
- **§3.5** — insert ×2 — `ph`/`abv_pct` rounded before scoring and stored rounded while `temperature_c`/`brix` are stored exactly as supplied; `reading_at` window checked ahead of the stage gate; every accepted reading bumps the **batch's** version; the projection reads `planned_f2_days` and `f2_added_sugar_g_per_l` from the **batch**, not the recipe.
- **§3.6** — insert ×6 — run opens with `net_liters` 0 (verified) and `started_by_user_id`/`finished_lot_id` null; `source_batch_count` counts **draw entries** (verified: two draws from one batch → 2); draw rounding; source draw returns the run; fan-in stage sweep completes before the disposition sweep; lot's null-initialised custody fields; only a still-`READY_TO_PACKAGE` batch at 0 liters moves to `PACKAGED`; complete returns the run; abort retains `net_liters`/`units_produced`.
- **§3.7** — insert ×3 — quarantine, clearance and recall each cost the lot **exactly one** version increment; quarantine's `trigger_source` is `LOT_QUARANTINE`; clearance does not re-evaluate depletion; recall can never deplete.
- **§3.8** — insert ×5 — keg register's full initial field set (verified); fill resets `remaining_liters` to 0 but leaves `deposit_refund_amount`/`deposit_forfeit_amount` standing, and can deplete the lot; tap refuses an on-deposit keg with `ERR_INVALID_STATE`; untap leaves `remaining_liters`; a pour that empties the keg leaves `tapped_at` and `fill_liters` and never writes the lot; taproom fill's initial `poured_liters` 0 and null stamps, `requested_liters` stored rounded.
- **§3.9** — insert ×7 — shipment's full initial field set and the fact that opening one needs no `ACTIVE` account; `extended_price` computed from the unrounded `unit_price`; line add returns the **line** at 201 and bumps both lot and shipment; confirm recomputes totals after the account gate, short-circuits the alcoholic sweep, leaves `ytd_self_dist_liters` alone for a wholesaler, and does not bump the account; only `DELIVERED` shipments carry non-zero ageing (`DRAFT`/`CONFIRMED` read 0/0.00/`CURRENT`, `PAID` frozen) and no re-derivation is a mutation; payment returns the **shipment**, always bumps the account, re-derives the self-dist ledger, and 45 days exactly does not block recovery; cancel drives totals to zero, ageing to 0/`CURRENT`, and leaves the account untouched; `credit_terms_days` has no range check.
- **§3.10** — insert ×5 — cycle window as the 28 calendar dates from `cycle_start_date`'s own UTC date (matters when the clock is off-midnight — verified `cycle_start_date` = `2026-05-16T01:00:00.000Z`), active days floored at 0; pause span judged before overlap and only closed windows consulted; **`skips_used_this_year` is never reset by anything** — "per calendar year" is intent, not a rollover; allocation returns the allocation at 201, bumps the subscription unconditionally, does not recompute `next_cycle_charge`; cancellation floors `reserved_units` and credits nothing.
- **§3.11** — insert — acknowledgement is a plain decrement floored at 0 (not the hop-7 recount); both versions bump; returns the notice.

### Prior claims found WRONG against the code
1. **PRD §3.5's own "strictly earlier"** — refuted live (equal-instant `PH_REGRESSION`, above).
2. **PRD §2.6's "This applies whether the caller names `finished_lot_id` explicitly or leaves it out"** — the claim of uniform OCC placement is false for the implicit path; refuted live.
3. **PRD §3.8's "the allowance is deducted exactly once, at tap time, and never again"** — false across a tap/untap/re-tap cycle; refuted live (17.8 → 19.0).
4. **PRD §3.12's "that listing doubles as the operator's view of the first-expiring-first-out release order"** — the listing is neither ranked by `best_by_date` nor filtered by the selector's tests (`routes_lots.py:141` uses `collection_sorted`, i.e. `created_at`).
5. **PRD §3.10's "capped at 3 per calendar year"** — no year rollover exists anywhere (`grep` over `kb/` shows `skips_used_this_year` written only at creation and at increment); the cap is per lifetime.
6. **The `+10` rejection I first wrote** — self-corrected: a literal `+` in a query string decodes to a space and is accepted; only `%2B10` is refused. Verified both ways before finalising the wording.

### Orchestrator verification (independent of the subagent)
- `PRD_COMPLETED.md` = 711 lines / 168,821 bytes. Structure preserved: **88** endpoint rows, **34** error rows, 24 `###` sections — nothing added or dropped at section level.
- **`find implementation/ test_suite/ test_helpers/ -name '*.py' -newer results.8.json` → empty.** No code changed after the clean sweep, so the 81/81 × 8 result stands for the shipped implementation. Steps 8 and 9 touched documentation only.
- No orphan servers left behind; probe scripts removed.

---

# Final status — PASS

**81/81 tests × 8 stability rounds, 0 deletions, 0 implementation fixes.**

Beyond-Expert scale achieved: 18 entities · 88 endpoints · 12 state machines (all non-linear, 72 transitions) · 17 calculations (6 dual-variant) · 80 validation rungs · 34 error codes · 3 OCC rules · 6 conservation invariants · depth-7 recall cascade · 75 declared constants · 81 tests.

Pipeline shape: Step 7 near-clean (1 `test_suite/` setup fix, 2 iterations) → Step 8 ran on a thin part-A diff plus the implementation generator's own 16 open items as part B (**22 edits**) → Step 9 full scan (**47 edits: 43 pins, 4 mismatch-revisions**, plus 5 refutations of prior PRD/generator claims).
