# Worklog — task_2668_brick_masonry_unit_manufacturing

## Step 1: Create task directory — 2026-09-04T04:15:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2668_brick_masonry_unit_manufacturing` and `.../workspace`. Index 2668 was pre-assigned by the invoker; no scan of ./tasks/ was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-04T06:05:00.000Z

All three scaffold artifacts are complete and lint-clean.

**Output** — `/home/ubuntu/github/CodingPRD/tasks/task_2668_brick_masonry_unit_manufacturing/`

| file | lines | contents |
|---|---|---|
| `SCAFFOLD.yaml` | 3325 | §1.0–§1.7 only (no design keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2291 | single key `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 6982 | single key `scaffold_corner_design` |

**SCAFFOLD.yaml (§1.0–§1.7)**
- 12 entities: Plant, ClayPit, BodyFormulation, Kiln, KilnCar, ProductionRun, KilnRun, FiredLot, Order, ShippedBlend, BlendComponent, SamplePanel (topology `graph`, archetypes quota_allocation / ledger_reconciliation, role model `segregation_of_duties`, consistency `immediate`)
- 12 state machines (Order carries two parallel dimensions: fulfillment_status and freight_status), 3 `concurrency_rules` (formulation-component, kiln-load, blend-component)
- 10 calculations (body_blend_chemistry, clay_tonnage_commitment, green_yield, firing_color_development, blend_color_profile, blend_autofill_waterfall, panel_dye_lot_equivalence, plant_assignment_selector, order_freight_cost, order_lead_time); `green_yield` and `order_freight_cost` are dual-variant
- 47 validations (single priority ladder), 51 endpoints (30 POST + 21 GET), 56 error codes, 8 roles

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)** — 18 instances, 2 per each of the nine §0.5 difficulty rules (dual-variant divergence, rounding-residual modes, cyclic/parallel state, error masking, exact boundary, cross-entity gate, temporal interval semantics, conservation invariants).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)** — 88 instances across all nine taxonomy sections (65 full `test_recipe`s + 23 `excluded_because` stubs that each cite a real §1.8 instance): entities 13, state_machines 13, calculations 15, validations 11, endpoints 5, errors 17, rbac 6, complexity_layers 6, consistency_model 2. Notable ones added last: one OCC stale-version recipe per `concurrency_rules` entry, a 6-plant `selector_policy` recipe where each eligibility filter is the sole reason one plant drops out and the 60-mile plant beats the 10-mile plant on cents-per-ton-mile (the rejected equipment-mismatch plant is deliberately placed at the winner's exact distance and rate so it would win the `created_at` tie-break if the filter were skipped), a segregation-of-duties recipe where one user id both composes+certifies and another both submits+approves, and two `immediate`-consistency recipes with five roles reading five writes on first observation.

**Verification** — `scaffold_lint.py` reports `VERDICT: clean lint` (51 endpoints, 12 entities, 18 §1.8 instances, 65 §1.9 recipe instances, 1530 calls scanned); all three files parse under PyYAML; instance names unique within and across both design files; every stub citation resolves. Field names, error codes, endpoint role lists and all numeric literals (e.g. absorption 8.00 SW / 10.80 MW, base_cdi 20.68, color_index 52.18, freight 56881 est vs 58541 final with variance 1660, lead time 17 days → 2026-08-18) were checked against `SCAFFOLD.yaml` rather than assumed. No sibling task directory was read at any point.

## Step 3: Copy shared files — 2026-09-04T06:05:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_2668_brick_masonry_unit_manufacturing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-04T06:22:00.000Z

PRD generation complete and verified.

**Output:** `workspace/PRD.md` — 491 lines, 101,928 bytes, written in 11 chunked appends; ends cleanly on the last row of the §5 error table.

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 RBAC (8 roles, `X-User-ID`, entity-backed identity translation, segregation of duties), 2.2 API Response Structure (verbatim block), 2.3 Pagination, 2.4 Resource Identity / Audit Columns / Logical Clock, 2.5 Rule Precedence (full 1–47 ladder), 2.6 Path & Body Reference Resolution, 2.7 Numeric Precision & Rounding, 2.8 Optimistic Concurrency, 2.9 Conserved Quantities (clay reserve + fired-unit ledgers), 2.10 Cascade Discipline & Version Propagation, 2.11 Code Uniqueness Scopes & Enumerated Vocabularies
- §3 Business Logic & Workflows — 3.1 Plant/pit/kiln/car commissioning, 3.2 Body formulation & qualification, 3.3 Extrusion/setting/green-handling fork, 3.4 Kiln scheduling, firing & grading, 3.5 Order intake, freight-sensitive plant assignment, lead time, 3.6 Sample panels & dye-lot equivalence, 3.7 Blending fired lots, 3.8 Packaging/delivery/freight ledger, 3.9 Plant idle cascade
- §4 Endpoint Definitions (4-column table only)
- §5 Error Code Catalogue (2-column table only)

**Coverage**
- 12/12 entities, 51/51 endpoints, 56/56 error codes, 47/47 validations (priority ladder complete), 10/10 calculations (both variants of `green_yield` and `order_freight_cost`), 3/3 OCC rules, 59/59 state transitions, 44/44 named constants stated as literal values.

**Hard Contracts** — Contract 1 Field-Name Coverage PASS (148/148 entity fields, 74/74 request-body params, 21/21 query params, 1/1 path param verbatim in backticks); Contract 2 Rule Coverage PASS (all 8 categories); Contract 3 §3 Path Purity PASS (855 inline-code tokens in §3, zero leading-slash paths, zero bare HTTP methods).

**Two fixes applied this pass:** added `blend_id` to the §3.7 manual-allocation paragraph (only Contract 1 gap), and made the panel `SUBMITTED → APPROVED` arrow explicit in §3.6.

**Judgement calls where the scaffold conflicts with itself** (relevant to test generation): `run_code` treated as globally unique per collection (entity constraint) rather than per-plant (validation 34); plant-idle hop 1 suspends only `OPEN` pits per the state machine, with `DEPLETED → SUSPENDED` deferred to hop 4; `target_color_index_min` must be strictly less than `max`; `banding_material` treated as a typo for `banding_type` and not invented as a field; a foreign-plant kiln car on run creation reported as `ERR_PLANT_SCOPE_VIOLATION`.

The two withheld design files were never opened, grepped, or referenced.

**Orchestrator truncation check (per invoker's guard):** `tail` confirms PRD.md ends on a complete `| `ERR_BAND_COUNT_INSUFFICIENT` | 422 |` table row at a real section boundary — not mid-sentence. Independently verified: 51 endpoint rows in §4, 56 error rows in §5, and the only scaffold `ERR_*` token absent from PRD is the scaffold's own `ERR_XXX` placeholder. No regeneration needed.

## Step 6: Generate implementation — 2026-09-04T07:00:00.000Z

The implementation for task 2668 is complete, smoke-verified end to end, and all smoke servers are torn down (killed by their own PIDs on ports 51771 / 52930-attempt / 54317; no broad pkill was ever issued).

## Files written — `workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `start.sh` (chmod +x) | 9 | guarded `pip install` (only if flask missing, so per-test reboots stay fast) + `exec python3 app.py` |
| `app.py` | 61 | `create_app()`, 9 blueprints, `strict_slashes=False`, ApiError/HTTPException/Exception handlers, `0.0.0.0:$PORT` (default 10000) |
| `store.py` | 167 | in-memory dicts only, logical clock pinned to `2026-08-01T00:00:00Z`, `new_row`/`touch` (one version bump per row per request), `public()` |
| `errors.py` | 85 | all 56 error ids → HTTP status |
| `auth.py` | 75 | 8 roles, header ladder 1→2→3, plant-operator scope check |
| `validation.py` | 185 | vocabularies + Decimal-safe field validators (`json.loads(..., parse_float=Decimal)`) |
| `response.py` | 93 | envelope, `req_`+20 alnum request ids, pagination (1..100 / default 10) |
| `calc.py` | 254 | every formula: chemistry/absorption/durability, clay split, green yield, CDI + position delta, grading, colour index, freight (both variants), lead time |
| `services.py` | 675 | lookups, both conserved ledgers (check-all-then-write), auto-fill plan/apply, plant selector, supersession closure, all 5 cascades |
| `routes/*.py` (10 files) | 30+342+19+63+175+234+248+201+144+164 | endpoint layer |
| `requirements.txt` | 1 | `flask` |

Total 3225 lines. Storage is pure in-memory dicts; nothing is seeded at startup (fresh boot returns `{"data":[], "total_count":0}`), and no file is written to disk.

## Endpoints: 51 (21 GET + 30 POST)
Path-by-path match against the PRD §4 table, verified from the registered Flask rules. 201 on the 10 creating endpoints, 200 on all other POSTs; child-append endpoints (`/formulations/{id}/components`, `/blends/{id}/components`) return the parent.

## PRD worked examples reproduced exactly
- Clay split 32.00 t over 3 pits → 10.67 / 10.67 / 10.66 (residual on the last component)
- Green close-out: `green_loss_pct` 4.0, `green_loss_variance_units` −38
- `base_cdi` 25.30 at 1050 °C / 4.00 h; position 2 of 5 → 24.93; lot code `R-1-P3`, dye lot `F1-KR-1-P3`, `color_index` 34.96 / 50.00 / 48.82, grades ON_COLOR vs OFF_COLOR_SALVAGE
- Estimate: 12000 u / 60 mi / 42 c → 27.00 t, 68040 + 3062 = **71102**; lead 15 d → `2026-08-16`; both flags → 50 d → `2026-09-20`
- Final bill: 24 pallets / 48 STEEL bands → 27.79 t, 70031 + 3151 = **73182**, variance **2080**
- Non-monotonic tier edge: 11106 u → 24.99 t / 49980 / **53229**; 11111 u → 25.00 t / 50000 / **52250**
- Panel expiry boundary: certify at `expires_at − 1s` succeeds; at `expires_at` → `ERR_PANEL_APPROVAL_EXPIRED` and the panel flips to EXPIRED
- Idle cascade: pit OPEN→SUSPENDED, FY1/FY2 QUALIFIED→DRAFT (`dequalified_count` 1, `qualified_at` null) while the RETIRED FY0 is untouched, SETTING run→SCRAPPED with its exact 5.00 t released (ledger stayed 4961 + 0 + 39 = 5000), SCHEDULED kiln run→ABORTED, LOADED run→SET with `kiln_run_id`/`kiln_position` cleared, all cars OUT_OF_SERVICE, kiln MAINTENANCE, fired lots untouched
- Also confirmed: stale-version 412s, both segregation-of-duties gates, 3-round revision cap, dye-lot equivalence (`ERR_DYE_LOT_MISMATCH` vs pass through the supersession chain), tolerance/span ceilings, reject and cancel cascades (panel WITHDRAWN only from DRAFT/SUBMITTED/REVISION_REQUESTED, freight figures preserved under WAIVED), delivery equipment checks in availability-then-mismatch order, quarantine exclusions, `ERR_PLANT_IDLED` on post-idle writes, `ERR_PLANT_SCOPE_VIOLATION`, 404/400 ladder.

## Two bugs found and fixed during verification
1. `qualify_formulation` wrote chemistry before the exact-100.00 share check — a rejected qualify mutated state. Now the share total is summed locally and `ERR_COMPONENT_SHARE_TOTAL_INVALID` raised before any write.
2. Auto-fill mutated lots/components before it could raise `ERR_INSUFFICIENT_BLEND_INVENTORY`. Split into a pure `autofill_plan()` and a mutating `apply_autofill()` called only after span (rule 26) and exact-fill (rule 45) pass against the projected component set, so "nothing at all is persisted" holds.

## PRD ambiguities resolved by explicit choice
- **Lot status on delivery**: `RESERVED → CONSUMED` unconditionally when its components are consumed, even with `available_units` left (PRD §3.9 "reservations fully drawn" + SCAFFOLD `FiredLot` transition has no exhaustion precondition). Consequence: a partially drawn lot is terminal and its remainder leaves inventory — accepted as the literal reading.
- **Certification panel choice**: when several APPROVED panels exist, every at-or-past-`expires_at` panel is expired first (the one sanctioned mutation on a rejected request), then the **first still-valid** panel by creation order is used; 0 approved → `ERR_PANEL_NOT_APPROVED`, all expired → `ERR_PANEL_APPROVAL_EXPIRED`.
- Formulation superseding a predecessor of another plant, and kiln load where the run's `formulation_id` ≠ the kiln run's → `ERR_INVALID_REQUEST` (400); no ladder rule covers either.
- `quarantine` on a lot not in {AVAILABLE, RESERVED} → `ERR_FIRED_LOT_UNAVAILABLE` (409).
- A QUARANTINED lot in a manual allocation reports `ERR_LOT_QUARANTINED` even though ladder rule 16 precedes 17, per the §3.7 carve-out.
- Compose check order follows the §2.5 ladder (17 → 18 → auto-fill → 26 → 45), not the §3.7 prose order.
- Server-stamped datetimes use the 3-fractional-digit `Z` form (`promised_ship_date` → `2026-08-16T00:00:00.000Z`, `expires_at`, `api_request_timestamp`); client-supplied datetimes (`start_at`, `end_at`, `to_iso8601` → `current_utc`) are echoed verbatim.
- New formulation has `blend_iron_oxide_pct`/`blend_lime_pct`/`shale_share_pct`/`absorption_index`/`computed_durability_grade` all null; blend reject resets `dye_lot_count` to 0 and nulls `weighted_color_index`/`color_range_span`/`composed_by_user_id`.
- Unknown enum values in GET filters return an empty page, not 400; `share_pct` is not bounded above at 100 in payload validation so an over-100 share surfaces as `ERR_COMPONENT_SHARE_TOTAL_INVALID` (rule 35) rather than `ERR_INVALID_REQUEST` (rule 7).
- SCAFFOLD overridden by PRD in three places: idle hop 1 suspends only `OPEN` pits; `run_code` is globally unique per namespace; `planned_soak_hours` is 0.50–24.00 at 2dp.

## Step 5: Generate unit tests — 2026-09-04T07:20:00.000Z

Stage 1 and Stage 2 are complete. `test_18_consistency_model.py` closed the last gap and the full audit is clean.

## Files written

`test_helpers/` (9 files, 2110 lines): `__init__.py` 22, `api_client.py` 211, `api_errors.py` 136, `assertions.py` 452, `constants.py` 102, `factories.py` 300, `fixtures.py` 593, `test_users.py` 69, `types.py` 225.

`test_suite/` (19 files, 6203 lines): `conftest.py` 56; queue A `test_01` 226, `test_02` 209, `test_03` 199, `test_04` 254, `test_05` 214, `test_06` 184, `test_07` 247, `test_08` 313, `test_09` 299; queue B `test_10_entities` 444, `test_11_state_machines` 573, `test_12_calculations` 610, `test_13_validations` 454, `test_14_endpoints` 332, `test_15_errors` 714, `test_16_rbac` 360, `test_17_complexity_layers` 331, `test_18_consistency_model` 184.

## Coverage

- **102 tests, 102 design tags, 83 unique tags** — one tag per test, no untagged and no dual-tagged test.
- **Queue A: 18/18** instances, 37 tests, every instance carrying >=2 tests (minimum observed is exactly 2).
- **Queue B: 65/65** non-stub instances, 65 tests: entities 13, state_machines 10, calculations 9, validations 7, endpoints 5, errors 9, rbac 6, complexity_layers 4, consistency_model 2.
- **Skipped instances: none.** All 23 `excluded_because:` stubs in `SCAFFOLD_CORNER_DESIGN.yaml` were correctly left un-emitted (verified programmatically: zero stub names appear as tags, zero non-stub names are missing).

## Verification run

- `ast.parse` over all 28 emitted `.py` files: PARSE_OK.
- Every tag's instance name resolves verbatim to a `name:` in `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml` (`MISSING: none`).
- Static attribute check across the whole suite: every `F.*`, `fx.*` and `api.*` reference and every `from test_helpers.* import` name resolves to a real definition (`UNKNOWN ATTRS: none`, `UNKNOWN IMPORTS: none`).
- No stray `test_helpers/`, `test_suite/` or `worklog.md` anywhere under `workspace/`; nothing inside `workspace/implementation/` was read, written, or executed, and no server or pytest process was started or killed.

## Notes worth carrying forward

- Two field/derivation traps were caught and fixed during the field-name audit: the fired-lot firing grade column is `grade`, not `color_grade` (three assertions corrected in `test_15_errors.py`), and the colour mapping is `color_index = 3.2 x position_cdi - 14`, derived from two pinned PRD examples and cross-validated against four more (52.18 / 49.81 / 59.60 / 40.40).
- Three design-vs-PRD conflicts were resolved PRD-first: the corner yaml's 201 for `POST /formulations/{id}/components` and `POST /blends/{id}/components` (scaffold says 200 — used 200), an instance's out-of-vocabulary texture `MOLDED` (used `SMOOTH`), and an instance asserting `dye_lot_count == null` on a new blend where PRD §3.7 says 0 (asserted 0).

**Orchestrator note:** verified no stray `test_helpers/` or `test_suite/` under `workspace/`; both live at the task root as required.

## Step 7 — test/fix iteration loop (8-round parallel stability sweep)

**Iteration 1** — 77/102 in all 8 rounds, 25 unique failures, identical in every
round (deterministic, no flakiness signal).

**Iteration 2** — 102/102 in all 8 rounds. Clean.

### Deleted / narrowed assertions (PRD silence)

- `test_12_calculations.py::TestFiringArithmetic::test_the_position_gradient_splits_one_firing_into_two_colours`
  — removed the two `lot["position_temp_delta_c"]` assertions. COMPUTED-FIELD
  SILENCE: §3.4 names `position_temp_delta_c` only inside the `position_cdi`
  formula as an intermediate and never declares it as a fired-lot attribute
  (the endpoint table lists "grade, position index, colour index, dye lot code
  and unit ledger"), so a faithful reader may omit it from the serializer. The
  test's own `FIRED_LOT_FIELDS` list already omits it. The gradient's observable
  effect stays asserted through `position_cdi` / `color_index` / `grade`.

### test_helpers fixes

- `assertions.py::parse_iso8601` — accept an optional fractional-seconds part, and
  add `same_instant()`. §2.4 renders `created_at`/`updated_at` "with three
  fractional digits" while the clock and its derived stamps are quoted at second
  precision, so instant comparison must span both renderings.

### test_suite fixes (assertion contradicted a verbatim PRD sentence)

- `test_10_entities.py::TestPlantEntitySurface` — `updated_at` expectation was
  `2026-08-01T00:00:00Z`; §2.4 requires three fractional digits. Now `.000Z`, and
  the `idled_at == updated_at` check became `same_instant(...)`.
- `test_11_state_machines.py::TestKilnRunLifecycle` — asserted a `SCRAP` lot's
  `available_units == 0`; §3.4 opens every minted lot with "`available_units`
  equal to `fired_units`" and §2.9 keeps the three columns summing to
  `fired_units` at every observable moment. Now compares to `fired_units` and
  adds the conservation assertion.
- `test_13_validations.py::TestLedgerGuardsAreAllOrNothing::test_two_legal_draws...`
  — both draws came off one 9600-unit lot, so the second was short of the lot and
  ladder rule 16 (`ERR_FIRED_LOT_UNAVAILABLE`) correctly pre-empted rule 41.
  Switched the fixture to `build_two_fired_lots` so each draw is individually
  legal and only the blend ceiling is violated.
- `test_15_errors.py::TestManualAllocationGuards` — expected HTTP 422 for
  `ERR_FIRED_LOT_UNAVAILABLE`; §5 lists it at 409.
- `test_15_errors.py::TestPanelToleranceAtCertification` — read `lot["formulation_id"]`;
  §3.4 names the field `source_formulation_id`.
- `test_17_complexity_layers.py::TestPlantSelectorPolicy` — expected the idled
  plant's body to be `RETIRED`; §3.9 hop 2 moves it `QUALIFIED → DRAFT`
  (`RETIRED` only ever comes from supersession).

### implementation fixes

- `store.py` — added `fmt_clock()` / `clock_str()`, a second-precision renderer
  for clock-derived business instants. §2.4 quotes the clock as "exactly
  `2026-08-01T00:00:00Z`" and §3.5 quotes a derived stamp as "at
  `2026-08-16T00:00:00Z`", while the three-fractional-digit rule is stated for
  `created_at`/`updated_at` — which keep using `fmt_dt`.
- `routes/formulations.py` (`qualify`), `routes/orders.py` (`assign_plant`:
  `assigned_at`, `promised_ship_date`), `services.py` (`idle_plant_cascade`:
  `idled_at`; `deliver_cascade`: `delivered_at`, `invoiced_at`),
  `routes/blends.py` (`certify`: `certified_at`), `routes/sample_panels.py`
  (`approve`: `approved_at`, `expires_at`) — now stamp through
  `clock_str()`/`fmt_clock()`.

## Step 7: Run tests and iterate — 2026-09-04T07:45:00.000Z

Clean. Final sweep verified on disk: 8/8 rounds at 102/102.

**Iterations run: 2.** Iteration 1 was 77/102 in all 8 rounds with 25 unique failures — identical in every round, so no flakiness; iteration 2 was 102/102 in all 8 rounds.

The 25 failures collapsed into 6 root causes (19 of them were one shared timestamp-rendering disagreement).

**Tests deleted / narrowed (PRD-silence):**
- `test_12_calculations.py::TestFiringArithmetic::test_the_position_gradient_splits_one_firing_into_two_colours` — removed the two `lot["position_temp_delta_c"]` assertions. **COMPUTED-FIELD SILENCE**: §3.4 names `position_temp_delta_c` only as an intermediate inside the `position_cdi` formula and never declares it as a fired-lot attribute (the endpoint table lists "grade, position index, colour index, dye lot code and unit ledger"). The test suite's own `FIRED_LOT_FIELDS` list already omits it. The gradient's observable effect remains asserted via `position_cdi` / `color_index` / `grade`. No whole test was deleted.

**Fixes to `test_helpers/`:**
- `assertions.py` — `parse_iso8601` now accepts an optional fractional-seconds part, plus a new `same_instant()`; §2.4 renders `created_at`/`updated_at` with three fractional digits while the clock and its derived stamps are quoted at second precision, so instant comparison must span both.

**Fixes to `test_suite/`** (each assertion contradicted a verbatim PRD sentence):
- `test_10_entities.py` — `updated_at` expected `...00:00Z`; §2.4 mandates three fractional digits → `.000Z`, and `idled_at == updated_at` became `same_instant(...)`.
- `test_11_state_machines.py` — asserted a `SCRAP` lot's `available_units == 0`; §3.4 opens every minted lot with "`available_units` equal to `fired_units`" and §2.9's identity forbids 0 → compares to `fired_units` plus a conservation assertion.
- `test_13_validations.py` — both draws came off one 9600-unit lot, so ladder rule 16 (`ERR_FIRED_LOT_UNAVAILABLE`) correctly pre-empted rule 41 (`ERR_BLEND_OVER_ALLOCATION`); switched the fixture to `build_two_fired_lots` so each draw is individually legal and only the blend ceiling is busted.
- `test_15_errors.py` — expected HTTP 422 for `ERR_FIRED_LOT_UNAVAILABLE`; §5 lists 409.
- `test_15_errors.py` — read `lot["formulation_id"]`; §3.4 names it `source_formulation_id`.
- `test_17_complexity_layers.py` — expected the idled plant's body `RETIRED`; §3.9 hop 2 moves it `QUALIFIED → DRAFT` (`RETIRED` only comes from supersession).

**Fixes to `implementation/`:**
- `store.py` — added `fmt_clock()`/`clock_str()`, a second-precision renderer for clock-derived business instants. §2.4 quotes the clock as "exactly `2026-08-01T00:00:00Z`" and §3.5 quotes a derived stamp as "at `2026-08-16T00:00:00Z`", whereas the three-fractional-digit rule is stated specifically for `created_at`/`updated_at`, which keep using `fmt_dt`.
- `routes/formulations.py` (`qualify` → `qualified_at`), `routes/orders.py` (`assign_plant` → `assigned_at`, `promised_ship_date`), `services.py` (`idle_plant_cascade` → `idled_at`; `deliver_cascade` → `delivered_at`, `invoiced_at`), `routes/blends.py` (`certify` → `certified_at`), `routes/sample_panels.py` (`approve` → `approved_at`, `expires_at`) — all now stamp through `clock_str()`/`fmt_clock()`.

No skips, xfails, or weakened error-id assertions were introduced; storage remains in-memory only.

**Orchestrator verification:** independently parsed all 8 `workspace/implementation/results.*.json` — every round reports `passed == total == 102`. Step 8 will run (Step 7 had non-zero implementation fixes, so the skip condition does not apply).

## Step 8: Finalize PRD — 2026-09-04T07:47:00.000Z

`PRD_FINALIZED.md` is written. Two edits; everything else in `<step_7_diff>` traced to fixture/test bugs against prose the PRD already pinned verbatim.

## Line counts
- `PRD.md`: 491 lines
- `PRD_FINALIZED.md`: 491 lines (0% line delta; both changes are in-line revisions of existing paragraphs)

## Changes

- **§2.4** — revise — pinned the rendering precision split: `created_at`/`updated_at` read the logical clock and carry the three fractional digits, while the clock-derived business stamps (`idled_at`, `qualified_at`, `assigned_at`, `delivered_at`, `invoiced_at`, `certified_at`, `approved_at`, `expires_at`, plus `promised_ship_date`) render at second precision, gaining `.mmm` only if the clock itself was set to a sub-second instant — `implementation/store.py:58-103` (`fmt_dt` vs `fmt_clock`/`clock_str`)
- **§3.4** — insert — stated that `position_temp_delta_c` is an intermediate in the `position_cdi` derivation and is not persisted as a fired-lot field — `implementation/services.py:553-575`

## Per-edit pre-edit search log

**Edit 1 — subject: rendering format of every server-written timestamp value.**
(b) Enumerated and read/grepped: `store.py:58-103` (`fmt_dt`, `now_str`, `fmt_clock`, `clock_str`), `store.py:137-163` (`new_row`/`touch` → `now_str`, so all 12 entity types get 3-digit `created_at`/`updated_at`), `response.py:25` (`api_request_timestamp` → `now_str`, 3 digits, already matching §2.2), `grep -rn '_at"\] *='` across all modules to enumerate every stamp write — `services.py:456` (`idled_at`), `services.py:637-638` (`delivered_at`, `invoiced_at`), `routes/orders.py:141-142` (`promised_ship_date`, `assigned_at`), `routes/sample_panels.py:161-162` (`approved_at`, `expires_at`), `routes/formulations.py:173` (`qualified_at`), `routes/blends.py:322` (`certified_at`) — all `clock_str()`/`fmt_clock()`; plus two paths that are *not* server-rendered and had to be excluded: `routes/clock.py:19` (`current_utc` echoes the client's `to_iso8601` string verbatim) and `routes/kiln_runs.py:88-89` (`start_at`/`end_at` echo the payload strings, with parsed copies kept only in private `_start_at`/`_end_at`). Also confirmed `routes/blends.py:277` compares expiry via `parse_dt`, which tolerates either rendering, so the format choice is not load-bearing for rule 23.
(c) Adjustment: scoped the sentence to "the clock-derived business stamps just listed" plus `promised_ship_date` rather than any universal claim about timestamps, so it cannot be read as covering `current_utc`, `start_at`/`end_at`, or `api_request_timestamp`; and phrased the fractional case as conditional on the clock carrying sub-second precision rather than asserting a flat "no fractional digits", matching `fmt_clock`'s conditional branch.

**Edit 2 — subject: `position_temp_delta_c` as a persisted attribute.**
(b) Enumerated and read/grepped: `grep -rn "position_temp_delta_c\|position_cdi"` over the whole implementation — only `calc.py:186-192` (pure functions) and `services.py:553-554` (local `delta`, consumed by `position_cdi`); the lot literal at `services.py:556-575` carries no such key; `store.py:178-196` (`public()`) is a pass-through projection that adds nothing, and `routes/fired_lots.py:20-44` reads through `public()`, so no read path could surface it either; confirmed the kiln run row (`services.py:534-544`) stores only `base_cdi`/`firing_curve_deviation`, so the delta is persisted nowhere in the model.
(c) Adjustment: said "not persisted as a field on the fired lot" (the entity Step 7 exercised) and added the positive claim that the gradient remains observable through `position_cdi` and its derivatives (`grade` via `calc.firing_grade`, `color_index` via `calc.lot_color_index`), rather than a broader "not persisted anywhere" that would over-reach; left the existing "rounded before it is folded in" sentence untouched since it is consistent with an unpersisted intermediate.

**Orchestrator verification:** `PRD_FINALIZED.md` exists at 102,595 bytes vs `PRD.md` 101,928 — a real +667-byte diff, so the edits landed.

## Step 9: Complete PRD — 2026-09-04T08:10:00.000Z

Run as **three sequential file-partitioned passes** over a single `PRD_COMPLETED.md` (orchestrator seeded it with `cp PRD_FINALIZED.md PRD_COMPLETED.md`). Rationale recorded here as the orchestrator's judgement call: a single subagent pass over 3,225 lines of implementation reliably skims and returns a byte-identical file, so the scan was partitioned by impl module and run strictly sequentially (concurrent passes would collide editing the same ~100KB file).

**Totals: 491 → 495 lines, 102,595 → 116,447 chars (+13,852 chars, +13.5%). 45 edits: 35 ambiguity-pins, 10 mismatch-revisions.**

### Pass A — core infra (`app.py`, `store.py`, `response.py`, `auth.py`, `errors.py`, `validation.py`)
491→493 lines, 102,595→105,950 chars. 9 ambiguity-pins, 2 mismatch-revisions.
- §2.2 (`api_request_id`) — insert — ambiguity — `req_` + exactly 20 chars `A`–`Z`/`0`–`9`, re-randomised per response — `response.py:11,20-21`
- §2.2 (`data`) — insert — ambiguity — `public()` projection: internal bookkeeping columns never projected; Decimal renders as JSON number not string — `store.py:178-196`
- §2.2 (error envelope intro) — revise — mismatch — envelope covers 5xx too, not just 4xx — `app.py:49-52`
- §2.2 — insert — ambiguity — global handlers: unrouted → 404, bad method → 405, unparseable/non-object body → 400, unhandled fault → 500, all `ERR_INVALID_REQUEST`; trailing slash ignored; empty body read as `{}` — `app.py:21,41-52`, `validation.py:53-66`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; omitted-or-empty falls back to default — `response.py:60-70`
- §2.3 — insert — ambiguity — `created_at` tie-break is insertion order earliest-first; out-of-range offset → empty `data`, full `total_count`, `has_more` false — `store.py:166-168`, `response.py:73-85`
- §2.4 — insert — ambiguity — `updated_at == created_at` on a fresh row — `store.py:137-145`
- §2.4 — insert — ambiguity — once-per-request version increment (multi-hop cascade row still ends +1; `updated_at` refreshed each hop) — `store.py:148-163`
- §2.4 — insert — ambiguity — `parse_dt` acceptance (`Z`/`z`, explicit offset normalised to UTC, naive read as UTC, unparseable → `ERR_INVALID_REQUEST`); sub-ms truncation — `store.py:58-70,110-123`
- §2.5 rule 7 — insert — ambiguity — generic validators: explicit `null` == absent; empty strings rejected; integer fields accept `12000.0` but reject fractions/booleans/digit-strings; decimal scale judged on the literal as written; duplicate enum-array entries accepted; undeclared fields ignored — `validation.py:69-160`
- §5 — revise — mismatch — 400 for `ERR_INVALID_REQUEST` scoped to payload/query rejections; framework-level reuses carry 404/405/500 — `app.py:41-52` vs `errors.py:23`
- Verified already-pinned: `ERROR_STATUS` matches §5 for all 57 ids; `auth.py` ladder order and 8-role vocabulary match §2.1 rules 1–3; `require_plant_scope` PlantOperator-only comparison; `fmt_clock` second precision; `CLOCK_START`, uuid4 ids, version starting at 1, pagination defaults/bounds, filter-then-paginate, four `meta` fields.

### Pass B — `calc.py` + `services.py`
493 lines, 105,950→108,539 chars. 10 ambiguity-pins, 2 mismatch-revisions.
- §2.9 — revise — mismatch — ledger moves are written only out of the status they name, so a lot quarantined mid-reservation still has all three columns moved while `status` stays `QUARANTINED` — `services.py:218-231`
- §3.2 — revise — mismatch — supersession pointer is walked newer→older only (PRD had it reversed); a panel on the newer body accepts older-body lots, not the reverse — `services.py:433-448`
- §3.2 — insert — ambiguity — absorption reads the already-rounded 3-dp blend figures, not fresh unrounded accumulations — `calc.py:105-113`
- §3.3 — insert — ambiguity — `projected_net_green_units` is not floored at zero; goes negative on tiny runs — `calc.py:155-160`
- §3.4 — insert — ambiguity — minting walks loaded runs in their own `created_at` order, not ascending `kiln_position` — `services.py:546,549-579`
- §3.5 — insert — ambiguity — fourth plant tie-break after `created_at` is registration/insertion order — `services.py:412,418`
- §3.6 — insert — ambiguity — the panel's own `formulation_id` is always a class member; 16-hop cap = own body + 16 predecessors — `services.py:438-448`
- §3.7 — insert — ambiguity — fourth auto-fill tie-break is minting order, earliest first — `services.py:320-327`
- §3.7 — insert — ambiguity — an `AUTO_FILL` component is formed exactly like a hand-picked one, carrying `color_index_at_allocation` and the same rounded `contribution_index` — `services.py:331-343`
- §3.7 — revise — ambiguity — reject cascade nulls `weighted_color_index`/`color_range_span`/`composed_by_user_id` but sets `dye_lot_count` to 0 — `services.py:620-630`
- §3.8 — insert — ambiguity — cancellation, unlike rejection, preserves the voided blend's colour profile and composer/certifier attribution; only `allocated_units` returns to 0 — `services.py:657-669`, `610-618`
- §3.9 — insert — ambiguity — an aborted kiln run's `loaded_units` is left as it stood, so it can report units no run still points at — `services.py:516-526`
- Pass B verified the three PRD worked examples reproduce exactly (clay split 10.67/10.67/10.66; the 11106-vs-11111 non-monotonic surcharge pair; the 27.00→27.79 ton re-quote with variance 2080). Flagged `services.blend_profile` and `services.any_blend_of_order` as dead code (routes/blends.py has its own) and deferred the live profile + panel selection to pass C.

### Pass C — `routes/*.py` (all ten files) + the two subjects A/B deferred
493→495 lines, 108,539→116,447 chars. 16 ambiguity-pins, 6 mismatch-revisions.
- §2.1 — revise — the scope-skip rule applies only to *derived* refs; a body `plant_id` is compared as a literal string, so a bogus `plant_id` yields 403 not 404 — `production_runs.py:53`
- §2.2 — insert — mismatch — the universal "non-object body answers 400" is false for the seven writes that declare no body field — `blends.py:250`, `orders.py:119`, `kiln_runs.py:193`
- §2.4 — revise — ambiguity — clock endpoint answers 200 and `current_utc` echoes the supplied literal verbatim, not the normalised instant — `clock.py:19`
- §2.5 preamble — insert — mismatch — "no state whatsoever is mutated" carve-out for the panel-expiry sweep — `blends.py:279`
- §2.5 rule 5 — insert — ambiguity — body is JSON-parsed before scoping, so a non-object body outranks `ERR_PLANT_SCOPE_VIOLATION` — `production_runs.py:49-54`
- §2.5 rule 7 — revise — ambiguity — blend window inversion and `requested_units` over the order cap are rule-7 `ERR_INVALID_REQUEST`, ahead of the order-state gate — `blends.py:92-95`
- §2.5 rule 8 — revise — mismatch — added missing `ERR_PLANT_NOT_FOUND`/`ERR_KILN_NOT_FOUND`; pinned per-operation body-reference resolution order — `formulations.py:58-59`, `production_runs.py:65-67`, `kiln_runs.py:63-64`, `sample_panels.py:56-57`
- §2.5 rule 16 — revise — mismatch — `ERR_FIRED_LOT_UNAVAILABLE` also fires on blend composition (after rule 18's DRAFT gate) and on the quality hold — `blends.py:204`, `fired_lots.py:54`
- §2.6 — revise — mismatch — nested-list filter sets corrected: pits by `status`+`material_type`, kilns and kiln cars by `status` only — `plants.py:49-66`
- §2.6 — insert — ambiguity — filter semantics: exact case-sensitive equality, conjunctive, non-matching value → empty page not an error, blank == omitted, null field never matches, unknown params ignored — `routes/__init__.py:6-30`
- §3.2 — revise — ambiguity — the five derived chemistry figures are null at creation — `formulations.py:76-83`
- §3.2 — revise — ambiguity — cross-plant `supersedes_formulation_id` → `ERR_INVALID_REQUEST` (400), after both 404s, before plant-active/uniqueness — `formulations.py:60-61`
- §3.2 — revise — ambiguity — `share_pct` is >= 0.00 at two decimals with no ceiling of its own — `formulations.py:102`
- §3.4 — insert — ambiguity — `start_at`/`end_at` persisted and returned verbatim; only collision arithmetic normalises — `kiln_runs.py:88-89`
- §3.4 — revise — ambiguity — load's plant equality carried by rule-5 scoping on both kiln and production run; formulation-id mismatch → `ERR_INVALID_REQUEST` (400) after both status gates — `kiln_runs.py:116-140`
- §3.4 — revise — ambiguity — kiln-run start evaluates status → loaded set → kiln availability, all three reporting `ERR_KILN_RUN_STATE_INVALID` — `kiln_runs.py:200-206`
- §3.4 — revise — ambiguity — quarantine of a non-`AVAILABLE`/`RESERVED` lot → `ERR_FIRED_LOT_UNAVAILABLE`, after the reason payload check — `fired_lots.py:52-58`
- §3.6 — revise — mismatch — expiry-on-read is applied only by a certification on a `requires_panel_approval` order; it sweeps **every** `APPROVED` panel, the flips persist through rejection, and the request is rejected only when none survives — `blends.py:270-288`
- §3.7 — revise — ambiguity — compose's quarantine check is first (ahead of the DRAFT gate); the `RESERVED`/`ON_COLOR` check is `ERR_FIRED_LOT_UNAVAILABLE` after it, before auto-fill planning — `blends.py:199-209`
- §3.7 — revise — ambiguity — `ERR_PANEL_NOT_APPROVED` vs `ERR_PANEL_APPROVAL_EXPIRED` split; the earliest laid-up surviving `APPROVED` panel is used; certification rewrites all four profile fields and leaves `panel_delta_e` null when no panel applies — `blends.py:270-320`
- §3.8 — revise — ambiguity — "the order's shipped blend" = most recently opened non-`VOID` blend; absent blend → `ERR_BLEND_NOT_CERTIFIED`, not 404; delivery selects identically — `orders.py:165,228`
- Both deferred subjects examined and pinned. Noted for the record: the `ERR_PANEL_NOT_APPROVED` branch at `blends.py:286` is unreachable (a non-empty `APPROVED` set with no survivors always implies `expired_any`), so the PRD wording deliberately describes only the reachable behavior. The live colour arithmetic in `blends.py:21-44` was already uniquely pinned by §3.7; what was silent and is now pinned is the certify-time rewrite of all four fields.

**Orchestrator verification:** `PRD_COMPLETED.md` is 495 lines / 116,447 chars and differs from `PRD_FINALIZED.md` on 76 lines — not byte-identical, so the scan genuinely ran. `tail` confirms it still ends on the complete `| `ERR_BAND_COUNT_INSUFFICIENT` | 422 |` row of the §5 table, i.e. a real section boundary with no truncation. `find workspace/implementation -name '*.py' -newermt '2026-09-04 07:47'` returns nothing, confirming no pass touched implementation code, so the Step 7 green state (8/8 rounds at 102/102) still stands.

**PIPELINE COMPLETE.**
