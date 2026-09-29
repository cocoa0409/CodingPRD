# Worklog — task_2591_malt_hops_brewing_ingredient_distribution

## Step 1: Create task directory — 2026-09-03T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2591_malt_hops_brewing_ingredient_distribution` and its `workspace/` subdirectory. Index 2591 was pre-assigned by the invocation; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-03T17:21:00.000Z

All three artifacts are complete and the scaffold linter is clean.

**Files** (`/home/ubuntu/github/CodingPRD/tasks/task_2591_malt_hops_brewing_ingredient_distribution/`)
- `SCAFFOLD.yaml` — 3,590 lines / 183 KB. Top-level keys only: `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` (neither design key present).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2,422 lines / 167 KB, single key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4,777 lines / 329 KB, single key `scaffold_corner_design`.

**§1.0–§1.7 counts:** 15 entities · 9 state machines / 44 transitions · 3 concurrency (OCC) rules · 15 calculations · 47 validations (single priority ladder 1→47) · 68 endpoints · 64 error codes · 5 roles. Profile: `quota_allocation` + `pricing_engine`, parallel state machines, `segregation_of_duties` role model, `immediate` consistency, complexity layers `optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers`.

**§1.8:** 9 rules / 26 instances (`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`) — three depth-5 transitive cascades (harvest shortfall, contract default, cold-chain excursion) and three conservation invariants.

**§1.9:** all 9 taxonomy sections / 101 instances — entities 12, state_machines 16, calculations 18, validations 17, endpoints 12, errors 12, rbac 4, cross_cutting_complexity_layers 9, consistency_model 1. 73 full `test_recipe`s + 28 `excluded_because` stubs, every stub citing an existing §1.8 instance by `rule_id / name`.

**Verification:** `scaffold_lint.py` → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (1,033 calls scanned). All three files `yaml.safe_load` cleanly; 0 unbound `${var}` references across 1,033 calls and all asserts; all 64 error ids referenced by at least one design instance; no forbidden concurrency vocabulary; instance names unique across both design files.

**Design adjudications**
- `SalesOrder.total_cents` stays 0 for the whole DRAFT phase (fees first assessed at confirm). Without this, validations priority 45 double-counted the order it was judging and priority 44 (HOLD) permanently pre-empted `ERR_CREDIT_LIMIT_EXCEEDED`.
- Priority 36 shadows 37 on carry-forward (a fully drawn contract yields cap-eligible 0, so `ERR_CARRY_FORWARD_EXCEEDS_CAP` fires first); `declare-default` is therefore the only reachable route to `ERR_NO_UNCOMMITTED_VOLUME`, and that is now the explicit distinguishing aspect of one errors-section corner.
- Priority 3 (role) outranks priority 4 (payload shape) and priority 19 (OCC) — proven by CreditManager-with-malformed-body and AllocationManager-with-valid-version probes.
- `ERR_DUPLICATE_CROP_YEAR` is its own code; zone_code / variety_code / sku / strain_code share `ERR_DUPLICATE_RESOURCE_CODE`.
- Nested `line_id` resolves within the named order, so a sibling order's line is 404, not a cross-order delete.
- PlatformAdmin owns the logical clock and nothing else; segregation of duties keys on `X-User-ID`, not role.
- Excursion accumulator is monotonic with three strict-inequality boundaries (setpoint±tolerance are in tolerance; cumulative exactly at 30 min does not flag); returning to tolerance never rewinds the total.
- Pagination envelope fields (`total_count`, `has_more`) are asserted in prose rather than captured, since captures must resolve to §1.5 output entity fields.

## Step 3: Copy shared files — 2026-09-03T17:21:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T17:37:00.000Z

PRD complete and verified.

**Output:** `workspace/PRD.md` — **465 lines / 109,152 bytes**, built incrementally (one `Write` + four `cat >> … <<'PRDEOF'` appends). Final heading is `## 5. Data Validation & Error Handling`; the file ends on the last complete error-table row (`| ERR_PAYMENT_EXCEEDS_BALANCE | 422 |`) — a genuine section boundary, no audit footer.

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control, 2.2 API Response Structure (verbatim from the skill's fixture; byte-match confirmed), 2.3 Pagination, 2.4 Collection Filters, 2.5 Common Resource Properties and the Logical Clock, 2.6 Money, Poundage and Rounding Discipline, 2.7 Stale-Version Guards on Contended Records, 2.8 Validation Precedence, 2.9 Segregation of Duties, 2.10 Uniqueness of Trade Codes, 2.11 Conservation of Allocated Poundage, 2.12 Cascading Recomputation and Derived-Field Consistency
- §3 Business Logic & Workflows — 3.1 Onboarding a Brewery / credit standing / AR ledger, 3.2 Crop Years, Hop Varieties and Contract Commitments, 3.3 Reporting the Harvest (shortfall waterfall + downstream trim), 3.4 Covering a Shortfall with a Substitute Variety, 3.5 Carry-Forward, Default Settlement and Resale, 3.6 Malt (recipes, receipt, analysis, spec matching), 3.7 Yeast (strains, propagation slots, pitch-rate advisory), 3.8 Sales Orders (lines, pricing, two status dimensions, fulfilment), 3.9 The Cold Chain (zones, reefer loads, telemetry)
- §4 API Endpoints (4-column table, 68 rows)
- §5 Data Validation & Error Handling (2-column table, 64 rows)

**Coverage (all machine-verified against SCAFFOLD.yaml)**
- Entities 15/15; state machines 9/9, transitions 44/44 (4 documented in prose without the literal arrow glyph: `SHORTFALL_ADJUSTED → CARRY_FORWARD_PENDING` via the explicit sibling-symmetry sentence, `CONFIRMED → CANCELLED`, `STAGED → SUPERSEDED`, `IN_TRANSIT → DELIVERED`)
- Calculations 15/15; every constant of every calculation appears in prose (0 missing)
- Validations 47/47 (all 10 priority bands in §2.8); concurrency rules 3/3 with field, error ID and 412
- Endpoints 68/68 — every method+path row matches the scaffold exactly; errors 64/64 with exact HTTP statuses, and all 64 error IDs also appear in §1–§3 prose

**Hard contracts**
- Contract 1 (field-name coverage): PASS — 193/193 required identifiers (entity/output fields, body identifiers, query params) appear verbatim in backticks.
- Contract 2 (rule coverage): PASS — priority ordering, OCC triple, cross-entity side effects, `applies_to` scopes, defaults/types, sibling-branch symmetry, all transitions/calculations/validations/cascades A/B/C documented.
- Contract 3 (§3 path purity): PASS — zero backticked tokens in §3 start with `/`, zero bare HTTP methods, zero method+path combos; also zero unbackticked path fragments in §2–§3. No pseudocode/fuzzy-language leaks (`round_half_up`, `==`, `IN {`, "approximately" etc. all absent); one constant-name leak (`CARRY_FORWARD_CAP_PCT`) that had been copied from a scaffold endpoint description into §4 was rewritten as "25 percent".

**Adjudications made on scaffold internal inconsistencies**
1. `OrderLine.quantity` — field constraint says 3 dp, `order_subtotal_rollup.precision` says `decimal(12,2)`; documented three decimal places (the input-field contract).
2. `Brewer.open_order_exposure_cents` description says `{CONFIRMED, PICKED}` but `brewer_credit_posture.input_set` says `{DRAFT, CONFIRMED, PICKED}`; used the calculation's set and explained that DRAFT orders contribute 0 because `total_cents` stays 0 until confirm.
3. `TemperatureReading.recorded_at` field constraint says "strictly after `last_reading_at`" but validation 25 accepts equal timestamps with `interval_minutes` 0; followed validation 25.
4. `offered_lbs` is listed as a required substitution-offer input yet carries a default; documented both readings (must be at least 1; defaults to `shortfall_lbs` less `substitution_covered_lbs` when omitted).
5. Carry-forward precondition "source program status == HARVEST_REPORTED" has no error_id in the validations table; assigned `ERR_INVALID_PROGRAM_STATE` (409).
6. `hard_fail_reason` values are not enumerated in the scaffold; documented as reusing the `quarantine_reason` vocabulary (`MOISTURE_ABOVE_MAX` / `DIASTATIC_POWER_BELOW_MIN`).
7. `MaltProduct.cold_storage_required` (default false) and `YeastStrain.cold_storage_required` (default true) are entity fields absent from their creation input lists; documented as not supplied at registration and taking their defaults.
8. Priority 11's `check` mentions a third clause ("a ColdChainShipment's zone accepts the order's item mix") that is not in its `applies_to` list; documented only the two applicable clauses (contract-against-`OPEN`-program, substitution-group membership) under `ERR_PROGRAM_NOT_OPEN`, and documented the shipment-side gate as `ERR_COLD_CHAIN_NOT_CERTIFIED` per priority 21.

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced, and no sibling task directory was read.

**Orchestrator truncation check:** `tail -25` confirms the file ends on a complete table row of §5; `grep -n '^#'` shows all 5 top-level sections and 21 subsections present in order. Not truncated. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T19:30:00.000Z

Both stages are complete and verified.

## Paths
Everything is at the **task root**, not under `workspace/` (`workspace/` contains only `INSTRUCTION.md` and `PRD.md`):
- `test_helpers/`
- `test_suite/`

## Stage 1 — `test_helpers/` (2249 lines, 9 files)
`__init__.py` 37, `api_client.py` 287, `api_errors.py` 152, `assertions.py` 238, `constants.py` 111, `factories.py` 250, `fixtures.py` 643, `test_users.py` 75, `types.py` 456.

## Stage 2 — `test_suite/` (8908 lines, 19 files, **156 tests**)
`conftest.py` 55; queue A: test_01 402/8, test_02 227/5, test_03 309/7, test_04 299/7, test_05 467/9, test_06 218/5, test_07 568/9, test_08 202/4, test_09 321/6, test_10 280/4 (**64 tests**); queue B: test_11_entities 519/11, test_12_state_machines 761/14, test_13_calculations 995/17, test_14_validations 896/16, test_15_endpoints 985/16, test_16_errors 669/9, test_17_rbac 286/4, test_18_concurrency_consistency 449/5 (**92 tests**).

## Coverage
- **Queue A (difficulty): 26/26 instances covered, 0 skipped** — all 9 rule families (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).
- **Queue B (corner): 72/73 non-stub instances covered, 1 skipped.** entities 11/12, state_machines 10/10, calculations 11/11, validations 13/13, endpoints 9/9, errors 9/9, rbac 4/4, cross_cutting_complexity_layers 4/4, consistency_model 1/1. The 28 `excluded_because:` stubs were not translated.
- **Only skip:** `entities/contract_line_unit_price_is_computed_and_supplied_value_is_ignored_input` — the design asserts a client-supplied `unit_price_cents` is ignored on a contract-drawn line, but PRD §3.8 states a supplied `unit_price_cents` **overrides** the derived price. The PRD does not uniquely derive the asserted outcome (it contradicts it), so the instance was dropped rather than weakened.

## Verification run
- `python3 -m py_compile` clean on all 28 `.py` files.
- Docstring checker: every one of the 156 tests carries exactly one trailing `Design: …` line; **208 quoted PRD sentences all verified verbatim substrings of `workspace/PRD.md`** (`problems=0`), and every `PRD §X.Y:` label matches the section actually containing the quote (`section problems: 0`).
- No design line points at a nonexistent or stubbed instance (zero EXTRA in every section).
- AST sweep: no undefined names anywhere; no unused imports outside the intentional `test_helpers/__init__.py` re-export surface (removed a stale `create_job` import from test_03 in the process).
- `__pycache__` removed; the implementation directory was never read, listed or globbed.

## Notable PRD-coverage gaps (sub-assertions dropped, tests kept)
- No `GET /brewers` collection endpoint exists, so the design's brewer-listing `total_count` assertion could not be made.
- Design sub-assertions with no PRD backing were omitted: `GET /sales-orders` list scoping in the brewer-scope error instance, the "Brewer recipe list silently narrows" claim, and every `held_for_credit` field assertion (0 PRD occurrences).
- Two design/PRD conflicts resolved in the PRD's favour: crop-year program listing asserted newest `crop_year` first (§2.3/§4) rather than the design's `created_at` ASC; a fresh program's `allocatable_pool_lbs` asserted `0` rather than null; and `payload_shape_is_judged_before_the_duplicate_key` asserted HTTP 400 per §2.8 band 2 rather than the design's 422.

**Orchestrator note (deviation recorded):** the skill mandates launching Steps 5 and 6 in a single assistant message so that the impl generator is physically unable to read `test_suite/`. The orchestrator launched Step 5 alone, so that physical isolation is lost for Step 6. Compensating control: Step 6's prompt carries an explicit hard prohibition against reading, listing, or globbing `test_helpers/` and `test_suite/`, and Step 6 is instructed to derive behavior solely from INSTRUCTION.md + SCAFFOLD.yaml + PRD.md. Recorded here rather than escalated, per the non-interactive autonomy directive.

## Step 6: Generate implementation — 2026-09-03T20:15:00.000Z

Implementation complete and verified.

## Files written (all under `workspace/implementation/`)

| file | lines |
|---|---|
| `start.sh` | 10 |
| `requirements.txt` | 1 |
| `app.py` | 102 |
| `calc.py` | 655 |
| `cascades.py` | 240 |
| `serialize.py` | 380 |
| `validation.py` | 263 |
| `db.py` | 119 |
| `errors.py` | 98 |
| `util.py` | 102 |
| `middleware.py` | 69 |
| `response.py` | 56 |
| `routes/orders.py` | 614 |
| `routes/yeast.py` | 391 |
| `routes/contracts.py` | 362 |
| `routes/coldchain.py` | 330 |
| `routes/malt.py` | 252 |
| `routes/offers.py` | 203 |
| `routes/brewers.py` | 133 |
| `routes/programs.py` | 132 |
| `routes/varieties.py` | 94 |
| `routes/clock.py` | 19 |
| `routes/__init__.py` | 0 |

Total 4,625 lines. `python3 -m py_compile` clean on every module.

## Coverage
- **68 endpoints** — exactly the 68 rows of PRD §4 (verified route-by-route against the table).
- **Storage**: plain dicts in `db.Store`, empty at boot; no seeding, no SQLite/disk/tmp. Logical clock only, defaults to `2026-08-01T00:00:00Z`.
- **Validations**: the 47-priority total order from §2.8 / the SCAFFOLD priority table is implemented as an explicit gate ladder per handler (auth 1–3, shape 4, existence 5–7 with path-left-to-right then brewer scope then body ids, coherence 8–11, state 12–18, OCC 19, safety 20–24, temporal 25–30, capacity/uniqueness/volume 31–43, fiscal 44–47). Full 66-entry error catalogue with PRD statuses.
- **Calculations**: all named ones — order roll-up with per-line rounding, the normative 11-step fee assessment (freight minimum before reefer surcharge), waterfall shortfall reallocation (FIXED_CROP_YEAR before SPOT_HOLD, then created_at ASC, never pro rata), carry-forward cap/fee, MARKET_SETTLED vs LIQUIDATED settlement with the inverted admin-fee tiers, substitute ranking, weighted malt spec match with adjunct diastatic bump, yeast pitch advisory with viability decay, freight tier on a half-open 365-day trailing window, brewer credit posture, aggregate zone occupancy sweep, cold-chain excursion assessment (interval charged to the reading that *closes* it). Decimal + ROUND_HALF_UP throughout; `floor` only in the three declared places.
- **State machines**: program, contract (incl. cyclic carry-forward), lot, job, order's parallel `fulfillment_status` × `credit_status`, offer, shipment. All three cascades (A harvest→trim→reprice→posture, B default→AR→posture→ON_HOLD→HELD, C reading→flag→yeast FAILED + hop QUARANTINED→replacement job). Three OCC guards, both SoD pairs.

## Smoke results (PORT=18591, killed only by that port's exact PID; no broad pkill)
`bash start.sh` boots in the foreground on `0.0.0.0:18591`. Two end-to-end scripts, **all checks pass**: envelope/meta shape, 401/403/404/400/409/412/422/402 paths, brewer→program→variety→contract→malt lot (analyze/release with SoD)→strain/recipe/job→order with hop+malt+yeast lines→confirm (money verified to the cent: 845000/0/25000/4500/0/874500)→credit decision→pick→zone→stage (stale-version 412, capacity 409, bad window 422, re-stage supersedes, occupancy 4→9→0)→depart→telemetry (edge-of-band in tolerance, out-of-order 422, cumulative 25 not flagged, 35 flagged)→cascade C (yeast FAILED/COLD_CHAIN_EXCURSION, replacement REQUESTED at pitch+lead, hop line QUARANTINED, ship blocked)→ship/deliver FINAL variant→cancel unwind→cascade B (LIQUIDATED 5,320,000+53,200, brewer HOLD, order ON_HOLD, load HELD, release-hold 402 then payment then 200)→AUTO_RANKED offer accept minting a SPOT_HOLD→carry-forward request/approve/settle. Restart check: a previously created brewer 404s and every collection reports `total_count` 0 — zero residual state.

## Ambiguities resolved
- **Yeast-job 404 id** was `ERR_YEAST_PROPAGATION_JOB_NOT_FOUND` in my earlier draft; the catalogue says `ERR_YEAST_JOB_NOT_FOUND` — corrected in `errors.py` + `validation.py`.
- **Depart with an order not in PICKED**: priority 16 explicitly excludes depart, so I follow the PRD sentence literally and return `ERR_ORDER_CREDIT_NOT_APPROVED` (402) for both the not-PICKED and not-APPROVED cases.
- **release-hold ordering**: prose says credit then capacity, but §2.8's total order puts zone capacity (31) before order credit (46); I follow the numeric total order.
- **Zone `occupied_pallets`** is derived on read from the logical clock, so staging/holding does **not** bump the zone's `version` (a stored value would drift as the clock advances with no request).
- **Cascade C link 2** quarantines only `OPEN` cold-chain HOP lines (per the declared `OPEN → QUARANTINED`), while the READY-yeast check is not line-status filtered; the cascade does not reprice the order, since its links are enumerated as exactly three.
- Carry-forward target that does not resolve → `ERR_INVALID_CARRY_FORWARD_TARGET` (422), not 404; brewer scope (6) before contract state (12); DECLINE always returns the contract to `ACTIVE`; settle blocked by any `CARRY_FORWARD_PENDING` with `ERR_INVALID_PROGRAM_STATE`; contract `contracted_lbs` below `min_order_lbs` → `ERR_INVALID_REQUEST` after FK resolution and after `ERR_PROGRAM_NOT_OPEN`; minted substitution contract copies the shorted contract's delivery window and skips the overlap test.

## Step 7: Run tests and iterate — 2026-09-03T20:40:00.000Z

Clean 8-round parallel sweep achieved: **156/156 passing in all 8 rounds** (no reaping — 0 `Terminated` in the sweep log; each round ~295s).

## Summary

**Iterations run:** 3 sweeps (8 parallel rounds each). Round 1: 142/156 with 14 deterministic failures (identical in all 8 rounds — no flakiness anywhere in the suite). Round 2: 155/156. Round 3: 156/156 × 8.

**Tests deleted:** none wholesale. Two sub-assertions removed under STEP 1c partial-coverage handling:
- `test_suite/test_14_validations.py::test_a_program_that_has_reported_or_settled_admits_no_new_contracts` — dropped the `settled_at` assertion: the field `settled_at` appears **0 times** in PRD.md (§3.2/§3.3 describe settlement with only an optional `settlement_note`). PRD-silence category: computed/response-field silence. The PRD-covered assertions (`ERR_PROGRAM_NOT_OPEN` after report and after settle, `status == SETTLED`) were kept.
- `test_suite/test_14_validations.py::test_an_unknown_brewery_is_a_404_while_a_real_foreign_one_is_a_403` — dropped the `GET /brewers/{other_id}` → `ERR_BREWER_SCOPE_VIOLATION` probe. §2.1's scope rule is stated as "ownership checks on any resource that **references** a `Brewer`" plus a closed "Concretely" list — contracts, orders, order lines, recipes, propagation jobs, substitution offers, payments — which omits the `Brewer` entity itself, while §4 grants `Brewer` read access to `GET /brewers/{id}`. Two-reader divergence, so unique derivability fails. The 404-for-unknown-id and desk-reads-any-brewery assertions were kept.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` — `create_recipe()`: `requested_pitch_rate_million_cells_per_ml_per_plato` defaulted from `None` (omitted from payload) to `0.75`. PRD §3.6 lists it among a recipe's required brewing parameters, so the PRD-faithful implementation correctly returned `ERR_INVALID_REQUEST`; the factory was building an invalid payload, breaking 4 tests' setup.

**Fixes applied to `test_suite/`:**
- `test_09_cold_chain_zone.py` (4 call sites, 3 tests) — `validate_success(stage_attempt(...))` now passes `expected_status=201`; PRD §4: "Creation endpoints return `201`".
- `test_14_validations.py` fixture `two_brewers_and_a_contract_owned_by_the_second` — same fix for `POST /sales-orders` (was failing setup for 2 tests).
- `test_01_order_fee_assessment.py::test_one_pound_below_the_order_minimum...` — final delta assertion `7568 → 7432`; the test's own preceding assertions (`178432` and `171000`) both passed, so `7568` (7500 **+** 68) contradicted its own prose "7,500 in surcharge **less** 68 in goods".
- `test_10_conservation.py` — `invoiced_at` exact-string compare relaxed to `.startswith("2026-08-01T00:00:00")`, matching how every other server-stamped instant in the suite is asserted; PRD fixes the three-fractional-digit format only for `created_at`/`updated_at`, so the instant (not its serialization) is the PRD-covered claim.
- `test_18_concurrency_consistency.py` — credit-profile reprice payload `credit_terms_days: 60 → 45`; PRD §3.1 declares the enum `0, 15, 30, 45`, and §2.8 priority 4 requires a declared member, so `60` was correctly rejected as `ERR_INVALID_REQUEST`.

**Fixes applied to `implementation/`:**
- `routes/orders.py`, `add_line()` — added `scope_brewer(actor, contract["brewer_id"])` after body-id resolution and before the `ERR_CONTRACT_BREWER_MISMATCH` coherence check. §2.1 names contracts in the Brewer scope list and §2.8 puts the Brewer ownership scope (priority 6) ahead of referential coherence (8–11), so a Brewer naming a rival's contract must report 403, not 422. The desk (`AllocationManager`) path still reports `ERR_CONTRACT_BREWER_MISMATCH`.

**Orchestrator independent verification:** all 8 `workspace/implementation/results.{1..8}.json` exist (timestamps 20:35, ~46 KB each) and each parses with `passed == total == 156`. `grep -c Terminated workspace/sweep.log` → 0, confirming no SIGTERM reaping. Step 7's claim is corroborated, not taken on report.
