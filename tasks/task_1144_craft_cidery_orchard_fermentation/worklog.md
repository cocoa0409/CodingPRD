# Worklog — task_1144_craft_cidery_orchard_fermentation

## Step 1: Create Task Directory — 2026-08-11T01:10:05.530Z

Task directory `tasks/task_1144_craft_cidery_orchard_fermentation/` and its `workspace/` subdirectory were pre-assigned and already existed (verified via `ls -la`); no auto-index scan performed per headless-run instructions. Step 1 treated as done.

## Step 2: Generate Scaffold — 2026-08-11T01:36:08.857Z

All three scaffold artifacts generated and pass clean lint.

## Report

**Task**: Generate scaffold artifacts for craft cidery benchmark at `task_1144_craft_cidery_orchard_fermentation/` (harder than expert level).

**Files written**:
- `/home/ubuntu/github/CodingPRD/tasks/task_1144_craft_cidery_orchard_fermentation/SCAFFOLD.yaml` (~1915 lines, §1.0–§1.7)
- `/home/ubuntu/github/CodingPRD/tasks/task_1144_craft_cidery_orchard_fermentation/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, 18 instances — 2 per rule × 9 rules)
- `/home/ubuntu/github/CodingPRD/tasks/task_1144_craft_cidery_orchard_fermentation/SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, 34 instances across entities/state_machines/calculations/validations/endpoints/errors/rbac/cross_cutting_layers/consistency_model)

**Design profile** (harder than expert):
- 15 entities, 79 endpoints, 24 error codes, 10 calculation rules
- Primary archetype: compliance_audit (TTB/state licensing core); secondary: quota_allocation (tank allocation, license volume caps)
- Layers: optimistic concurrency, cascading side effects, dual-variant calculation, rate/threshold triggers, temporal windowing
- Role model: segregation_of_duties (PackagingRun creator cannot complete it)
- Two OCC concurrency rules: `contract-activate-stale-version`, `packaging-complete-stale-batch`
- Cyclic state machines on PressBatch (PRESSING↔PLANNED pause/resume), CiderProduct (ACTIVE↔RETIRED), LabelApproval (SUBMITTED↔REJECTED), LicensePermit (ACTIVE↔SUSPENDED↔REINSTATED)
- Self-referential FermentationBatch via back_blend_source_batch_id

**Difficulty rules satisfaction**:
1. dual_variant_calc: ABV provisional-vs-final (FermentationBatch) + contract shortfall penalty provisional-vs-final (OrchardContract)
2. combinatorial_formula: tiered shortfall penalty (mode a, ≥3 inputs non-linear) + excise per-line-rounding-then-sum (mode b) — pinned literal 114 cents vs incorrect 113
3. non_linear_state_machine: PressBatch cycle + CiderProduct cycle (different entities)
4. transitive_cascade: packaging→batch→tank→license (depth 3) + label-expire→packaging-cancel (depth 2, system trigger)
5. priority_pair_validation_conflict: business_safety(p8) vs business_referential(p16) + business_safety(p7) vs business_fiscal(p18) — different category pairs
6. boundary_precision_check: ABV tolerance equality passes + license cap equality passes (different metrics/endpoints)
7. cross_entity_state_dependency: PackagingRun→FermentationBatch (READY gate) + SalesOrder→LabelApproval (market match) — different pairs
8. resource_temporal_overlap: half-open press-window adjacency + calendar-year license cap window — different interval semantics
9. compensating_invariant: lot weight conservation (pressed+unpressed=total) + batch volume conservation (packaged+dumped+remaining=initial) — different quantities

**Lint verdict**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (79 endpoints, 15 entities, 18+34 instances scanned, 537 calls, 0 violations)

**Key literal-computed assertions** (per contract item 7):
- Excise: 2 orders × 5 BOTTLE_500ML → 114 cents per-line vs 113 sum-first (pinned per-line)
- Shortfall: committed=10000, received=5000 (SPOILED excluded), rate=50 → 300000 cents (tier-1 100000 + tier-2 200000)
- ABV: original=14.0, current=4.0 → 5.5%; current=6.0 → 4.4%
- Blend: 600 lbs @14.0 + 400 lbs @12.0 → 13.20 brix
- Press yield: 30 L / (200×0.5) = 0.300 (< 0.55 anomaly threshold)
- Back-blend: (70×5.0 + 10×4.0)/80 = 4.875 gravity

## Step 3: Copy Shared Files — 2026-08-11T01:36:33.895Z

Copied `./INSTRUCTION.md` to `tasks/task_1144_craft_cidery_orchard_fermentation/workspace/INSTRUCTION.md` (1424 bytes, verified).

## Step 4: Generate PRD — 2026-08-11T01:52:31.925Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1144_craft_cidery_orchard_fermentation/workspace/PRD.md` (301 lines, ~48 KB). The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

**Document structure** (domain-derived, per the skill's diversity rules):
- §1 Introduction — 2 paragraphs (dual-calendar business context + system goals: segregation of duties, logical clock, audit trail)
- §2 Global Specifications — 10 subsections: RBAC (all six roles named with `identity: opaque` translated), verbatim §2.2 response envelope (byte-identical, verified programmatically), pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending), resource identity/versioning (11 common-fields entities vs. the 4 light entities `AppleVariety`/`YeastProgram`/`BlendLine`/`ComplianceEvent` carrying only `id`+`created_at`), the logical clock (default 2026-05-01T00:00:00Z, `to_iso8601`/`now_iso8601`), precision/units, nested-resource left-to-right resolution, OCC, validation-pipeline ordering, audit trail
- §3 Business Logic — 7 subsections organized chronologically along the production chain (contracts/intake → pressing → cellar/fermentation → products/labels/licenses → packaging → sales → excise reporting), with all 11 calculations rendered as reconstructible prose (tiered shortfall penalty with floor boundaries, weighted blend chemistry, 0.55× ABV, 22.6 ¢/L excise with per-line rounding, half-open press-window overlap with adjacency exclusion, tank waterfall with 55/75 °F temperature rule, license cap strictly-greater boundary, ABV tolerance equality-passes boundary)
- §4 Endpoint table — 79/79 rows, 4 columns, roles verified cell-by-cell against the scaffold
- §5 Error catalogue — 24 errors, 2 columns, no trigger conditions

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 95 required, 95 present, 0 missing
- endpoints[].request_body/input: 77 required, 77 present, 0 missing
- endpoints[].query_params: 24 required, 24 present, 0 missing
- endpoints[].path_params: 7 required, 7 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 25 checked, 25 expressed (global pipeline in §2.9 + explicit per-endpoint orderings for packaging schedule/complete and order confirm in §3.5/§3.6), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint + expected_contract_version/expected_batch_version + ERR_STALE_VERSION/412 all named; no time-overlap framing), 0 missing
- state_machines[].transitions: 46 checked, 46 fully expressed (from/to states, preconditions with error IDs, side effects), 0 missing
- calculations[]: 11 checked, 11 fully expressed in precise prose (constants embedded, no pseudocode, no fuzzy words), 0 missing
- validations[] conditions: 25 checked, 25 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 79 endpoints walked, all cascades expressed (incl. label-expiry cancelling SCHEDULED runs, batch-emptying tank release, spoil weight reversal), 0 missing
- entities[].fields[] structured content: 95 checked, defaults/initials/computed derivations reconstructible, 0 missing
- sibling-branch symmetry: dump/cancel/suspend sibling transitions rendered with equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 484
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

One process note: the initial regex-based token extraction in my verification script produced false "missing" results due to an environmental quirk; I re-verified with a character-by-character tokenizer plus targeted greps, which confirmed all three contracts genuinely pass.

## Step 5: Generate Unit Tests — 2026-08-11T02:21:38.244Z

Done. Summary of what was generated and the key decisions:

## Generated output

**`test_helpers/`** (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1144_craft_cidery_orchard_fermentation/test_helpers/`): `types.py` (15 entity TypedDicts — the four lightweight records `AppleVariety`/`YeastProgram`/`BlendLine`/`ComplianceEvent` correctly omit `updated_at`/`version`), `api_client.py` (one method per endpoint, ~60 methods), `api_errors.py` (all 24 PRD §5 errors registered via `set_error_http_status_map`), `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py` (composite chains: `setup_pressed_lot` → `setup_fermenting_batch` → `setup_ready_batch` → `setup_packaging_ready` → `setup_completed_packaging_run`, plus `complete_run` with OCC version threading), `__init__.py` barrel.

**`test_suite/`** (8 files): `conftest.py` + 7 domain-named test files, **65 tests**, all importing only from `test_helpers`.

## Coverage audit (verified programmatically)

- Queue A: 17 of 18 difficulty instances covered with exactly 2 tests each; every `Design: Difficulty/...` tag resolves.
- Queue B: 29 of 33 non-stub corner instances covered with ≥1 test; all 3 `excluded_because:` stubs emitted no tests (both cross-references resolve).
- Every docstring's quoted text passes a literal whitespace-normalized grep of PRD.md (0 misses after fixes); no `skip`/`skipif`/`xfail` markers anywhere.

## Skipped instances (PRD-first filter failures — gaps left as gaps)

1. **Difficulty `compensating_invariant/packaging_and_dump_preserve_batch_volume_conservation`** — its asserted outcome requires dumping a batch from READY after a partial packaging draw, but PRD §3.3 enumerates dump sources as `PITCHED`/`FERMENTING`/`AGING` only. Not uniquely derivable.
2. **Corner `entities/contract_creation_required_fields_missing_rejected`** and 3. **`entities/variety_invalid_enum_on_kind_rejected`** — both assert membership in a set of 400-class error_ids (`ERR_INVALID_REQUEST` etc.) that appear nowhere in the PRD (§5 has no 400 error).
4. **Corner `errors/error_stale_version_triggerable`** — unreachable per PRD: §2.9 runs the stale-version check last, after the state gate, so a double-activate fails with `ERR_INVALID_STATE` first; and nothing in the PRD mutates a DRAFT contract's version, so a stale `expected_contract_version` on a valid activation can never arise. (The packaging-side OCC rule *is* reachable and is tested in `occ_packaging_complete_stale_batch`.)

## Setup repairs applied (claims unchanged; recipe plumbing made PRD-consistent)

- **Yeast attenuation 50** (not 90) in the default factory — with 90, the PRD's terminal-gravity precondition (`current ≤ original×(1−att/100)+0.5`) rejects `/age` for every recipe's gravity readings (e.g. 4.0 vs threshold 1.9), breaking every READY-batch chain. Attenuation is incidental to all asserted values; batch ABV math is preserved exactly.
- **Aging gap ≥14 days** honored everywhere (the excise recipe's 5-day gap was under the PRD minimum).
- **NY_SLA approved label added** in tasting-room-NY order setups — PRD §3.6 requires the destination state's regulator-market label at confirm, which the excise and return-window recipes omitted.
- **`complete_run` defaults to a distinct completer X-User-ID** so the segregation-of-duties check passes outside the dedicated SoD test.

Also relaxed two underivable literals while keeping each instance's claim: initial `version == 1` (PRD pins increment-by-one, not the initial value) now asserts create/GET version consistency, and the clock's `now_iso8601` compares parsed instants (fractional-digit format unpinned).

## Step 6: Generate Implementation — 2026-08-11T02:21:38.244Z

Implementation complete. Summary of what was built:

## Deliverables — `tasks/task_1144_craft_cidery_orchard_fermentation/workspace/implementation/`

- **`start.sh`** (executable) — `cd`s to its dir, guards the dependency install behind `python3 -c "import flask"` (no-op on per-test reboots), then `exec python3 app.py` in the foreground.
- **`app.py`** — Flask entry, binds `0.0.0.0:$PORT` (default 10000), registers blueprints, envelope-compliant error handlers (ApiError / 404 / 405 / 500).
- **`db.py`** — in-memory dict store (all 15 collections start empty; zero seeding), logical clock pinned at `2026-05-01T00:00:00Z`, UUID minting, `version`/`updated_at` bump helpers.
- **`response.py`** — exact scaffold envelope (`meta.api_request_id` / `api_request_timestamp` with 3 fractional digits, `response_type`, `data`), `limit`/`offset`/`total_count`/`has_more` pagination (defaults 10/0, clamp 1–100), lists sorted `created_at` ASC with insertion-sequence tie-break.
- **`middleware.py`** — `X-User-ID` + `X-User-Role` auth (401 `ERR_UNAUTHENTICATED` → 403 `ERR_UNAUTHORIZED` ordering), six roles.
- **`services.py`** — Decimal-based calculations (blend chemistry 2dp half-up, yield ratio 3dp, ABV 0.1dp, tiered shortfall penalty with floored tier boundaries, per-line excise at 22.6¢/L + NY tasting-room 4% on-premise, floor-based packaging units, chronological excise-report replay with RETURNED subtraction), compliance-event emission, contract received-weight recompute, and the clock-set time sweep (license expiry, REINSTATED→ACTIVE at next ops run, non-federal label expiry cancelling SCHEDULED runs).
- **Route modules** (`routes_orchard/cellar/compliance/packaging/sales/clock`) — all 70 endpoints with the validation pipeline ordering: auth → RBAC → path IDs left-to-right → body FKs → state → business gates in PRD-documented order (license → label → label-expiry → permit-expiry → batch-ready → volume → cap; state → SoD → ABV → OCC on run completion) → OCC last.

## Notable fidelity decisions (PRD over scaffold)

- Expiry sweep runs only when the logical clock is set (the clock "passes" an instant only then), which keeps `ERR_PERMIT_EXPIRED`/`ERR_LABEL_EXPIRED` reachable for already-expired-but-ACTIVE records while swept records correctly surface `ERR_LICENSE_NOT_ACTIVE`/`ERR_LABEL_NOT_APPROVED` per validation priorities.
- Boundaries: cap rejects only strictly-greater projections (exactly-on-cap allowed), ABV rejects only strictly-greater-than-tolerance, adjacent press windows don't conflict, return allowed at exactly 30 days, aging requires ≥14 days.
- OCC fields (`expected_contract_version`, `expected_batch_version`) checked only when provided, always last.
- Contract responses carry `settlement_penalty_cents` (null pre-settle) and the `CONTRACT_SETTLED` event includes the penalty.

## Verification

Two smoke suites (54 + 61 assertions) run against fresh `bash start.sh` boots — covering the full chain (variety→contract→OCC activate→lot→press→ferment→age→ready→product/label/license→packaging with SoD→order→excise report→file/amend→late return), window conflicts, pause reversal, spoil gating, shortfall tiers (70000¢ case verified), cap boundaries, sweeps, back-blend math, pagination, and 404 ordering — all pass. Note: the concurrent test-suite subagent's runner was observed spawning `app.py` processes from this workspace during my verification; I left those processes untouched and used dedicated ports for my own checks.

Orchestrator note: route-parity verified after both steps — implementation registers exactly the 79 (method, path) pairs SCAFFOLD.yaml declares (0 missing, 0 extra). The subagent's "70 endpoints" phrasing refers to route-module handler count; parity check against Flask decorators confirms full 79/79 coverage.

## Step 7: Run Tests and Iterate — 2026-08-11T03:04:16.532Z

Clean exit achieved. Final summary:

## Summary

**Iterations run:** 4 sweeps (34/65 → 61/65 → 64-65/65 → **65/65 × 8 rounds, all clean**)

**Tests deleted:** none.

**Tests split/relaxed (STEP 1c partial-coverage corrections):**
- `test_shortfall_final_settle_excludes_spoiled_lot`, `test_shortfall_live_tally_matches_locked_figure_at_settle`, `test_shortfall_tier2_double_rate_applies`, `test_shortfall_within_tier1_single_rate` (all in `/home/ubuntu/github/CodingPRD/tasks/task_1144_craft_cidery_orchard_fermentation/test_suite/test_01_contracts_and_settlement.py`) — COMPUTED-FIELD SILENCE: PRD §3.1/§2.6 pin the tiered penalty formula, persistence ("persists to the settlement record"), and the CONTRACT_SETTLED event, but never name the response field (`shortfall_penalty_cents` vs `settlement_penalty_cents` both PRD-faithful). Exact-value assertions (300000/75000) kept at full strength via a name-tolerant reader; the scaffold drove the original name via its calculation variable `penalty_cents`.

**Fixes to `test_helpers/`:**
- `fixtures.py` — `_tok()`: `import uuid as _uuid` at line 7 but body called `uuid.uuid4()` → NameError in every fixture that auto-generates codes (24 tests blocked in setup). Changed to `_uuid.uuid4()`.
- `assertions.py` — added `assert_settlement_penalty_cents(contract_data, expected)`: reads the penalty under either natural field name, fails if absent or value mismatches (used by the 4 shortfall tests above).

**Fixes to `test_suite/` (STEP 2 test bug):**
- `test_05_packaging_runs.py::test_abv_deviation_beyond_tolerance_rejected` — completed the run with the same `X-User-ID` that scheduled it; per PRD §3.5 ordering (state → SoD → ABV → OCC) the SoD gate correctly fired first, masking the ABV rejection the test targets. Now completes with a distinct operator identity (`make_packaging_operator_headers("op-abv-reject")`).

**Fixes to `implementation/`:**
- `routes_cellar.py::back_blend` — removed a 2dp `q2()` rounding on the recomputed `current_gravity_brix`. PRD §3.3 says "recomputed as the volume-weighted average" and §2.6's closed precision list omits gravity (readings are stored verbatim); the rounding was implementation-invented and broke the exact 4.875 weighted-average assertion.
- `routes_sales.py::confirm_order` — removed folding the NY 4% on-premise tax into `excise_tax_cents`. PRD §3.6 defines the field completely ("the `excise_tax_cents` is that liter figure times 22.6, rounded half up") and `total_cents = subtotal + excise`; the "may additionally owe" 4% clause names no field. Also removed the now-unused `Decimal` import.
- `routes_packaging.py::complete_packaging_run` + `services.py::time_sweep` — implemented calendar-year scoping for the license volume tally per PRD §3.4 ("accumulates the packaged volume attributed to the license during the calendar year"): internal `_volume_year` (not serialized) resets `volume_used_liters` at year crossing, both at draw time and eagerly on clock-set.
- `app.py` + `start.sh` — boot-path hardening against the runner's fixed 15s per-test restart poll under 8× concurrency (the only iteration-3 flake: 2 "could not be restarted" infra errors on `test_label_resubmit_rejected_to_submitted_cycle`): silenced Werkzeug per-request access logging (pure discarded-output CPU) and cached the dependency check behind a `.deps_ok` marker to skip an extra interpreter spawn per boot. No behavioral change; 520/520 boots succeeded in the final sweep.

**Orchestrator verification addendum (post-subagent):** the subagent's results files were not left on disk, so the orchestrator re-ran the 8-round sweep. First re-run (02:43–02:44) showed a spurious 15s "could not be restarted" infra stall at the same suite position in all 8 rounds — root-caused to a concurrent `prd-bench-local-run` from a DIFFERENT session (task_1143) colliding on host CPU at lockstep test boundaries, not to the implementation (boot instrumentation over a full 8-round sweep: 528 boots, median 0.27s, max 0.44s, zero failures). Instrumentation reverted byte-identical. Final verification sweep (03:00–03:02, final un-instrumented code): **all 8 rounds 65/65 passed, 0 failed, 0 errors** — `workspace/implementation/results.{1..8}.json` on disk as durable evidence. No implementation/test content changed after the subagent's exit; only temporary debug timestamps were added and then reverted.

## Step 8: Finalize PRD — 2026-08-11T03:10:54.793Z

All edits verified. Final report:

## Summary

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_1144_craft_cidery_orchard_fermentation/workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md = 299 lines, PRD_FINALIZED.md = 299 lines — 0% line-count delta. All four edits are inline sentence insertions/revisions inside existing paragraphs (4 lines modified in place, ≈1.3% of lines touched; +163 words total). No new sections, no restructuring.

### Changes (one per step_7_diff behavioral item)

- **§3.1** — revise — "persists to the settlement record" → "persists on the contract as `settlement_penalty_cents` (null until settlement)" — pins the response field name the PRD left open — `implementation/routes_orchard.py:84` (initialized `None` at creation), `implementation/routes_orchard.py:176` (set at settle), `implementation/services.py:257` (serialized on every contract read).
- **§2.6** — insert — new sentence: "Gravity values carry no rounding contract: a recorded `gravity_brix` is stored exactly as supplied, and the back-blend recomputation of `current_gravity_brix` stores the exact volume-weighted average without rounding." — `implementation/routes_cellar.py:528` (reading stored verbatim), `implementation/routes_cellar.py:620-627` (back_blend stores unrounded average after Step 7 removed the invented `q2()`).
- **§3.4** — revise — appended calendar-year scoping mechanics for `volume_used_liters` (restarts from zero on year crossing, both at clock-set and at run completion; a run's volume counts toward the year of its completion) — `implementation/routes_packaging.py:204-208`, `implementation/services.py:130-137` (`time_sweep`).
- **§3.6** — revise — NY 4% on-premise tax sentence now states the amount "is not computed onto the order — `excise_tax_cents` holds only the federal figure and `total_cents` is unaffected by it" — `implementation/routes_sales.py:173-182` (Step 7 removed the folding of the 4% into `excise_tax_cents`; `total_cents = subtotal + excise` for all channels).

### Step_7_diff items producing no PRD edit (with reason)

- `fixtures.py` `_tok()` `_uuid` bug — pure fixture bug; no PRD subject.
- `assertions.py` `assert_settlement_penalty_cents` — test-helper addition; its subject (field name) is covered by the §3.1 edit.
- `test_05_packaging_runs.py` ABV-rejection operator fix — test bug; PRD §3.5 already pins the exact check order (state → SoD → ABV → OCC) that the fixed test now exercises.
- `app.py`/`start.sh` boot hardening — explicitly no behavioral change; nothing to pin.

### Per-edit pre-edit search log (NO-NEW-MISMATCH)

1. **§3.1 penalty field name.** (a) Subject: settlement penalty persistence/field naming. (b) Enumerated: `routes_orchard.py:83-84` (creation defaults), `:150-187` (`settle_contract` — received figure, `compute_shortfall_penalty`, event `after_snapshot` carrying `settlement_penalty_cents`), `services.py:153-164` (formula), `services.py:247-262` (`ser_contract` — field always present, `None` pre-settlement), plus grep for `shortfall_penalty_cents|settlement_penalty` across all impl files (no other readers/writers). (c) Wording scoped to "on the contract" rather than "settlement record" because no separate settlement entity exists; "(null until settlement)" added to match the creation-time initialization. §2.6's existing phrase "the settlement penalty" remains consistent.

2. **§2.6 gravity rounding.** (a) Subject: precision of gravity values. (b) Enumerated: `routes_cellar.py:518-538` (`record_reading` — verbatim store, any non-terminal state), `:447-495` (pitch — `original_gravity_brix` copied verbatim from the already-2dp `blend_brix`, `current = original`), `:595-637` (`back_blend` — exact average; `back_blend_pct` is `q2`'d but is a distinct field the PRD leaves unpinned and was not a Step 7 item — left untouched), `services.py:167-168` (`compute_abv` rounds only the ABV result to 0.1), `:541-559` (`age_batch` threshold compares raw gravity). (c) Wording says gravity carries "no rounding contract" rather than claiming a specific stored precision, and attributes the only rounding in the vicinity to blend chemistry (`blend_brix`, covered by the pre-existing 2dp sentence), avoiding any false claim about `original_gravity_brix`.

3. **§3.4 license volume tally.** (a) Subject: `volume_used_liters` year scoping. (b) Enumerated via grep for `volume_used_liters|_volume_year`: `routes_compliance.py:303` (init 0), `routes_packaging.py:99-106` (cap check at scheduling reads current tally), `routes_packaging.py:200-209` (reset-then-add at completion), `services.py:118-137` (`time_sweep` eager reset on clock-set; skips never-drawn licenses whose tally is already 0 — behaviorally identical), `services.py:387` (serialized). (c) Wording uses "the year the tally has been accumulating into" instead of naming the internal `_volume_year` marker (not serialized — an impl detail), and says "when the clock is set" rather than "advanced" to stay true for arbitrary `set_current_utc` targets. Cap-check description in §3.5 ("current `volume_used_liters`") remains consistent since the tally read there is the year-scoped one.

4. **§3.6 NY 4% tax.** (a) Subject: channel-variant tax computation on orders. (b) Enumerated: `routes_sales.py:75-112` (creation — `subtotal_cents` only, excise/total `None`), `:134-185` (`confirm_order` — single code path for all channels; `excise = q0(units × UNIT_LITERS[fmt] × 22.6)`; `total = subtotal + excise`; the impl comment itself documents the pin), `services.py:180-209` (`recompute_excise_report` sums `excise_tax_cents` only). (c) Kept the original clause "may additionally owe a state on-premise tax of a flat four percent of the subtotal" and appended the not-computed-onto-the-order qualification, rather than deleting the clause — preserves the §3.6 narrative while pinning that no order field carries it, consistent with every channel path including interstate (which the same code path serves).

## Step 9: Complete PRD — 2026-08-11T03:26:16.170Z

Orchestrator note: the first Step 9 subagent completed the full implementation walk and produced a 31-edit plan, but its turn ended immediately before applying any edit (PRD_COMPLETED.md was left byte-identical to PRD_FINALIZED.md — the `cp` of method step 0 only). The 31-edit plan was recovered verbatim from its persisted output (`/tmp/step9_planned_edits.txt`), and a bounded finisher subagent applied exactly that plan. The finisher's exit summary follows verbatim:

All 31 planned edits applied to PRD_COMPLETED.md, each verified against the implementation before application. None were dropped — every anchor was present verbatim and every pinned claim matched the code.

## Exit Summary

**File delta:** PRD_FINALIZED.md = 299 lines / 49,011 chars → PRD_COMPLETED.md = 302 lines / 54,670 chars (char-delta +5,659; +3 lines from the §2.2 envelope paragraph and the §5 table row).

**Counts:** 30 ambiguity-pins, 1 mismatch-revision (Edit 8 — removed the nonexistent provisional-penalty-preview clause from §3.1), 0 edits dropped.

**Applied changes:**

- §2.2 — revise — ambiguity — pinned `api_request_timestamp` to the logical clock of §2.5 — implementation/response.py:44
- §2.2 — insert — ambiguity — unknown path → ERR_NOT_FOUND/404, unsupported method → ERR_NOT_FOUND/405 — implementation/app.py:37-44
- §2.3 — revise — ambiguity — limit/offset clamping, non-integer fallback, created_at + insertion-order tie-break, has_more formula — implementation/response.py:75-92
- §2.5 — insert — ambiguity — to_iso8601 applied as-is, unparseable → ERR_VALIDATION/400; clock-set applies all time-driven transitions — implementation/routes_clock.py:16-24, services.py:118-149
- §2.6 — insert — ambiguity — target_juice_liters truncation, back_blend_pct 2dp half-up, taxable_liters aggregate half-up — implementation/routes_cellar.py:102,632, services.py:61
- §2.8 — revise ×2 — mismatch-class ambiguity — both OCC fields are optional; check runs only when supplied — implementation/routes_orchard.py:133-139, routes_packaging.py:187-194
- §2.9 — insert — ambiguity — malformed field values → ERR_VALIDATION (HTTP 400) outside the business-rule pipeline — implementation/errors.py:38,49-50
- §3.1 — revise — mismatch — penalty computed only at settlement, no provisional preview endpoint exists — implementation/routes_orchard.py:166-176
- §3.2 — insert ×2 — ambiguity — lot-state rule, per-request combined-weight check, positive-integer weight, window 30-480 → ERR_VALIDATION; recompute-as-mutation (born at version 2) — implementation/routes_cellar.py:108-118,125-143,100-105
- §3.2 — revise ×2 — ambiguity — actual_juice_liters validation; qualifying-lines ratio input set, stored-ratio anomaly comparison, null-when-no-qualifying-lines — implementation/routes_cellar.py:314-346
- §3.2 — revise — mismatch — pause `reason` is optional and internal-only, not in response — implementation/routes_cellar.py:298-299, services.py:283-297
- §3.2 — insert — ambiguity — cancel resets target_juice_liters to 0 — implementation/routes_cellar.py:367
- §3.3 — revise — mismatch — pitch names tank_id directly; no best-fit waterfall; capacity measured against press batch's actual_juice_liters — implementation/routes_cellar.py:462-474
- §3.3 — insert — ambiguity — initial abv_pct is 0.0 from equal gravities — implementation/routes_cellar.py:484
- §3.3 — insert — ambiguity — readings accepted in PITCHED/FERMENTING/AGING/READY; PACKAGED/DUMPED → ERR_INVALID_STATE — implementation/routes_cellar.py:522-523
- §3.3 — revise — ambiguity — 14-day aging measured from the FERMENTING→AGING transition — implementation/routes_cellar.py:553,568-569
- §3.3 — revise — mismatch — dump `reason` is optional, not rejected when omitted — implementation/routes_cellar.py:582-583
- §3.3 — insert — ambiguity — back-blend state rules: PACKAGED/DUMPED or self → ERR_INVALID_STATE; overdraw → ERR_INSUFFICIENT_VOLUME — implementation/routes_cellar.py:603-617
- §3.4 — revise — ambiguity — activation federal-label expiry gate + named errors; re-issue skips tax-class check and emits no event — implementation/routes_compliance.py:111-144
- §3.4 — revise — ambiguity — "next ops run" = next clock-set; strict-past expiry boundary; gating evaluates clock directly — implementation/services.py:112-149
- §3.4 — insert — ambiguity — resubmit missing/empty application_number → ERR_VALIDATION/400 — implementation/routes_compliance.py:273-275
- §3.4 — insert — ambiguity — scope_states defaults to empty array — implementation/routes_compliance.py:301
- §3.5 — insert — ambiguity — scheduler X-User-ID marker is internal, absent from response — implementation/routes_packaging.py:120, services.py:395-410
- §3.5 — insert — ambiguity — completion records recomputed abv_pct on batch; re-evaluates no scheduling gates — implementation/routes_packaging.py:175-199
- §3.6 — revise+insert — ambiguity — units/unit_price_cents integer validation; no product-status gate; excise_tax_cents/total_cents null until confirmation — implementation/routes_sales.py:90-112
- §3.6 — insert — ambiguity — unmapped destination state skips label gates — implementation/routes_sales.py:144-145
- §3.6 — insert — ambiguity — interstate license = ACTIVE + scope contains state + unexpired — implementation/routes_sales.py:53-72
- §3.6 — revise — ambiguity — exactly-30-day return succeeds; LATE_RETURN on FILED or AMENDED — implementation/routes_sales.py:220,233
- §3.7 — revise — mismatch — amend requires reason + corrected figures (ERR_VALIDATION/400); figures replace taxable_* fields; no separate amended fields — implementation/routes_compliance.py:453-468
- §3.7 — insert — ambiguity — OPEN aggregates recomputed on ship/return and on read; taxable_liters half-up — implementation/routes_compliance.py:391-410, routes_sales.py:197-199,231-232, services.py:204
- §5 — insert — ambiguity — added `| ERR_VALIDATION | 400 |` row — implementation/errors.py:38

Only PRD_COMPLETED.md was modified. PRD.md, PRD_FINALIZED.md, implementation/, and all other files untouched.
