# Worklog — task_2511_airline_catering_inflight_meal_production

## Step 1: Create task directory — 2026-09-03T03:16:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2511_airline_catering_inflight_meal_production` and its `workspace/` subdirectory. Index 2511 was pre-assigned by the invoking pipeline (no scan/allocation performed, per instruction, to avoid collision with the ~32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-03T05:15:30.000Z

Complete. Lint verdict (final, verbatim):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2511_airline_catering_inflight_meal_production/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2511_airline_catering_inflight_meal_production/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2511_airline_catering_inflight_meal_production/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    68
  §1.1 entities declared:     15
  §1.8 instances scanned:     24
  §1.9 instances scanned:     72
  Calls scanned (§1.8+§1.9):  2025

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## What was generated

Three files in `/home/ubuntu/github/CodingPRD/tasks/task_2511_airline_catering_inflight_meal_production/`:

**`SCAFFOLD.yaml`** (3,276 lines) — §1.0–§1.7 only; top-level keys are `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, priority_conflict_pairs, endpoints, errors, roles, segregation_of_duties` (neither design key present).
- 15 entities (Airline, MealSpecification, Flight, SpecialMealOrder, ProductionBatch, HaccpCheck, Cart, CartItem, LoadingManifest, Truck, Stand, DeliveryRun, UpliftRecord, WasteManifest, AuditFinding)
- 11 state machines, 3 OCC rules, 12 calculations, 14 ordered validation rules with 3 declared priority-conflict pairs, 68 endpoints, 44 error codes, 7 roles (AirlineRep is `entity_backed:Airline`) + segregation-of-duties block
- 4 active `complexity_layers`: cascading_side_effects, dual_variant_calculation, optimistic_concurrency, version_pinning_on_approval

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** (1,433 lines) — single key `scaffold_difficulty_design`: 9 rule_ids, **24 instances** (dual_variant_calc 3, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 3).

**`SCAFFOLD_CORNER_DESIGN.yaml`** (3,170 lines) — single key `scaffold_corner_design`: all 9 guide sections, **95 instances** (72 with full `test_recipe`, 23 deferred via `excluded_because`): entities 12, state_machines 14 (3 excl), calculations 13 (5 excl), validations 23 (4 excl), endpoints 7 (1 excl), errors 11 (8 excl), rbac 7, cross-cutting layers 7 (2 excl), consistency model 1.

Verified beyond the linter: all 119 §1.8+§1.9 instance names unique; every `excluded_because.difficulty_instance` resolves to a real §1.8 instance name; no instance carries both `test_recipe` and `excluded_because`; each of the 4 `complexity_layers` has a cross-cutting instance; forbidden concurrency vocabulary absent from all three files.

Two self-consistency defects in `SCAFFOLD.yaml` were found and repaired while writing the corner cases: `UpliftRecord.seal_mismatch_count` (and the SEAL_MISMATCH finding it drives) was unreachable because no endpoint accepted the observed seal list — `POST /flights/{id}/uplift-records` now takes optional `"observed_seals?"`; and the Flight delay-cascade side effect now states windows shift by the *cumulative* `delay_minutes`, not by the request's increment.

## Step 3: Copy shared files — 2026-09-03T05:16:10.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T05:33:00.000Z

PRD generation is complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2511_airline_catering_inflight_meal_production/workspace/PRD.md`

- **Final line count: 421**
- **Last section heading: `## 5. Error Code Catalogue`** — the file ends on a complete table row (`| \`ERR_COST_CAP_EXCEEDED\` | 422 |`), not mid-sentence.
- The two withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

**Structure**

`§1 Introduction`; `§2 Global Specifications` (2.1 RBAC/identity, 2.2 response structure pasted verbatim from the skill's canonical file, 2.3 pagination + ordering, 2.4 logical clock, 2.5 common properties/version semantics, 2.6 validation priority ladder, 2.7 OCC on parent versions, 2.8 money/mass/percentage precision, 2.9 cascade discipline + parallel axes + conserved quantities, 2.10 airline scoping + segregation of duties); `§3 Business Logic & Workflows` in 10 subsections (3.1 contracts/specs → 3.10 audit docket); `§4 Endpoint Definitions`; `§5 Error Code Catalogue`.

**Coverage audit (all machine-verified against SCAFFOLD.yaml)**

| Item | Scaffold | In PRD |
|---|---|---|
| Entities | 15 | 15 — all 123 field names present verbatim in backticks |
| Endpoints | 68 | 68 rows in §4 table (exact count match) |
| State machines | 11 (52 transitions) | 11; 45 transitions rendered as explicit `FROM → TO` arrows, the other 7 as set-based cascade prose (`every manifest in DRAFT, ISSUED or AMENDED becomes VOID`, the four-state cancel edge, the `COUNTS_LOCKED` delay self-edge, etc.) |
| Calculations | 12 | 12; every numeric constant verified present (zone capacities 250/120/400, overflow minima 24/72, zone cutoffs 4/72/720, HACCP thresholds 75.0/8.0/5.0/3.0, weights 40.00/15.00, overhead 0.12, lateness bands 250/400/600, flat miss 750000, finding bases and multipliers, suspend threshold 3). The only constants not present as literals are the three handling rates, deliberately written as "nine/seven/five percent" |
| Validations | 14 (priorities 10–120) | all 14 bands as a numbered ladder in §2.6, each with error id, HTTP status and full `applies_to` endpoint enumeration; all 3 `priority_conflict_pairs` stated explicitly |
| Concurrency rules | 3 | 3, each with its `occ_field`, error id and 412, plus the band-65 placement |
| Errors | 44 | 44 rows in §5, **and all 44 referenced in the narrative before §5** (verified: zero unreferenced) |
| Roles | 7 | 7, each with remit prose and its `identity:` semantics (`AirlineRep` = entity-backed on `Airline`; the other six opaque, with the recorded-identifier fields named) |

**Hard Contract results**

- **Contract 1 (Field-Name Coverage): PASS.** Two independent verification passes. Pass 1 (140 required identifiers: all entity fields + all `input`/`query_params`/`path_params` identifiers + nested/derived names such as `reuse_units`, `line_gross_cents`, `cabin_breakdown`, `cap_breached`, `cart_version`, `cart_item_id`) → 0 missing. Pass 2 (recursive key sweep of every endpoint `input`/`output`/`query_params` subtree, 126 identifiers) → 0 missing. A third suffix-based sweep over the whole scaffold surfaced 24 unmatched tokens, all confirmed to be scaffold metadata keys (`rule_id`, `http_status`, `variant_id`, `algorithm_type`, `min_pct`/`max_cents`, …) or formula-local intermediates (`weighted_rate_cents`, `credit_cents`, `item_gross_cents`, `fail_count`, …), not persisted or request identifiers.
- **Contract 2 (Rule Coverage): PASS.** All six high-risk categories covered: validation priority ordering (§2.6 with all three collisions); OCC stale-version rules (§2.7, all three); cross-entity side effects (the four-hop post-release HACCP cascade, the void→cart→manifest→flight chain, the delay reslot chain, the flight-cancel unwind, the waste-manifest cart return, the suspension `production_hold` fan-out); `applies_to` scopes (endpoint lists enumerated per band); field-level structured content (`cart_seal_snapshot` with `cart_id`/`seal_number`/`cart_version`/`units` and its ordering, uplift `lines`, `dispositions`, `observed_seals`, `cabin_breakdown`, `required_haccp_steps`); sibling-branch symmetry (deliver vs miss, dispute/accept/withdraw compensation asymmetry, seal/dispose/reject, gross-uplifted vs net-consumed variants, provisional vs final requirement, first-start vs rework-restart).
- **Contract 3 (§3 Path Purity): PASS.** Automated extraction over all 61,672 characters of §3: 0 backticked tokens beginning with `/`, 0 containing `/`, 0 bare HTTP methods, 0 method+path combinations, and 0 unticked path or bare-method occurrences either.

**Two scaffold self-contradictions resolved by majority of sources** (worth flagging to the test-suite step so the hidden tests agree with the prose):
1. `seat_number` uniqueness scope — the field constraint says `{REQUESTED, CONFIRMED, SUBSTITUTED}`, but validation priority 100 ("non-terminal") and `ERR_DUPLICATE_SEAT_ORDER.triggered_by` both say `{REQUESTED, CONFIRMED, LATE_REJECTED}`. Since `SUBSTITUTED` is terminal, the PRD states the scope as `REQUESTED`, `CONFIRMED` or `LATE_REJECTED`.
2. Cutoff boundary inclusivity — the order-cancel precondition reads `clock <= special_meal_cutoff_utc`, while validation priority 110 and the error catalogue both refuse "at or after". The PRD states the operation is permitted strictly before the cutoff and refused at or after it.

**Orchestrator truncation check (guarded failure mode):** independently verified by the orchestrator — 421 lines / 102,012 bytes; §4 endpoint table contains exactly 68 method rows; §5 contains exactly 44 `ERR_` rows; file ends on a complete table row. Not truncated; no regeneration needed.

## Step 6: Generate implementation — 2026-09-03T06:52:00.000Z

Implementation complete. All files are under `/home/ubuntu/github/CodingPRD/tasks/task_2511_airline_catering_inflight_meal_production/workspace/implementation/`.

## File list (line counts)

| File | Lines |
|---|---|
| `app.py` | 73 |
| `start.sh` | 10 |
| `requirements.txt` | 1 |
| `clock.py` | 27 |
| `db.py` | 87 |
| `errors.py` | 118 |
| `middleware.py` | 125 |
| `response.py` | 71 |
| `serialize.py` | 361 |
| `timeutil.py` | 74 |
| `validate.py` | 209 |
| `routes/__init__.py` | 0 |
| `routes/helpers.py` | 124 |
| `routes/reference.py` | 244 |
| `routes/flights.py` | 505 |
| `routes/orders.py` | 137 |
| `routes/production.py` | 208 |
| `routes/carts.py` | 241 |
| `routes/manifests.py` | 87 |
| `routes/delivery.py` | 246 |
| `routes/uplift.py` | 246 |
| `routes/audit.py` | 111 |
| `services/__init__.py` | 0 |
| `services/calc.py` | 595 |
| `services/cascade.py` | 176 |

Total 4076 lines.

## Endpoints

**68 routes registered**, verified by introspecting `app.url_map` — exactly the SCAFFOLD count (67 business endpoints + `POST /_clock/set_current_utc`, the sole auth-exempt operation). All 15 collections have list/detail reads; 44 error ids are catalogued in `errors.py` with their HTTP statuses.

## Boot and smoke confirmation

`bash start.sh` (with `PORT` override) boots a fresh foreground Flask process on `0.0.0.0` and answers immediately. I ran a full end-to-end smoke through every subsystem, all responses as expected:

airline → 2 meal specs → truck/stand → flight → special-meal order (STANDARD spec correctly rejected 400, VGML accepted 201) → lock-counts → production-plan (201, array envelope) → batch start/HACCP/complete/release → cart create/load/build-completion/seal (OCC accepted) → manifest create with `expected_flight_version` → issue rejected 422 `ERR_SEGREGATION_OF_DUTIES` for the sealer, accepted for a second LoadMaster → delivery run reserve/DISPATCH/ARRIVE/DELIVER → flight auto-advanced to `DEPARTED` via the departure join, cart driven to `LOADED`, late delivery produced a `LATE_DELIVERY MINOR` finding (20 min late, 10 min grace, 250 c) → uplift record (GROSS_UPLIFTED, billing 45350) → dispositions (NET_CONSUMED recompute, billing 44691) → waste manifest create/SEAL/DISPOSE (record → CLOSED) → cost report with cabin breakdown → manual audit finding, ACCEPT then WITHDRAW compensating exactly → negative checks: unknown path 404 `ERR_RESOURCE_NOT_FOUND`, missing `X-User-ID` 401, unknown query param 400.

Zero-seed verified independently: after a second fresh `start.sh` on another port, all 15 list endpoints return `total_count: 0`, and the logical clock starts at its fixed default instant (`2026-08-01T00:00:00Z`), moving only via `POST /_clock/set_current_utc`. Storage is plain module-level dicts in `db.py` with no persistence and no startup writes, so every per-test relaunch begins empty. `start.sh` installs Flask only when the import fails, which avoids pip contention across the 8 concurrent rounds of `--isolation per-test-server`.

Two notes on adjudications made while finishing: (1) `SCAFFOLD.yaml` line 940 says a new uplift record "voids any earlier UpliftRecord of the flight still in DRAFT", but the UpliftRecord status enum has no VOID member and the path is unreachable (the flight must be `DEPARTED` to create one and becomes `RECONCILED` immediately), so I implemented it literally as `status = "VOID"`; (2) the AuditFinding field description says source is AIRLINE for anything raised through `POST /audit-findings`, while the endpoint's own side-effect says AIRLINE for an AirlineRep and SYSTEM otherwise — I followed the more specific endpoint text.

The isolation constraint was honored throughout: nothing in `test_suite/`, `test_helpers/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, or any sibling `task_*/` directory was read, listed, globbed, or grepped. The two background-task "failed exit 137" notifications are just my own `fuser -k` teardown of the smoke-test servers.

## Step 5: Generate unit tests — 2026-09-03T08:34:00.000Z

Test generation is complete. Both verification passes are clean.

## Files written

**`test_helpers/`** (infrastructure, 9 modules): `__init__.py` (single import barrel), `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`. Plus `test_suite/conftest.py`, which re-exports the fixture chain `api → base_env → flight_env → locked_env → planned_env → released_env → built_cart_env → sealed_env → issued_env → departed_env → reconciled_env → dispositioned_env`.

**`test_suite/` — 14 files, 120 tests**

| file | tests |
|---|---|
| test_01_reference_data_and_flight_intake.py | 12 |
| test_02_state_machine_transitions.py | 11 |
| test_03_derived_calculations.py | 8 |
| test_04_production_and_build_validations.py | 8 |
| test_05_order_ramp_and_reconciliation_validations.py | 11 |
| test_06_endpoint_surfaces_and_error_envelope.py | 9 |
| test_07_identity_roles_and_ownership.py | 7 |
| test_08_concurrency_pinning_and_immediacy.py | 6 |
| test_09_dual_variant_and_composed_money_formulas.py | 12 |
| test_10_reentrant_machines_and_multi_hop_cascades.py | 10 |
| test_11_priority_band_collisions.py | 6 |
| test_12_inclusive_edges_and_one_step_beyond.py | 6 |
| test_13_gates_on_other_rows_and_slot_geometry.py | 8 |
| test_14_compensating_acts_restore_the_prior_value.py | 6 |

## Design-index coverage

- **96 live instances / 96 translated, 0 untranslated.** 24 queue-A (Difficulty) instances × exactly 2 tests = 48; 72 live queue-B (Corner) instances × exactly 1 test = 72; total 120.
- **23 `excluded_because:` stubs were not translated**, per the contract.
- No test was emitted from SCAFFOLD.yaml directly; every docstring ends in exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line copied verbatim from the source yaml.

Verification (run from the task dir): `python3 -m pyflakes test_suite/*.py` clean apart from the expected unused-fixture re-exports in `conftest.py`; the verbatim-quote checker prints `issues: 0` (every `PRD §x.y: "…"` citation is a literal substring of `workspace/PRD.md`); the design-tag checker prints `live instances: 96 stubs: 23 / translated: 96 / issues: 0` with no untagged, dual-tagged or dangling tags and no mention of "scaffold" in any docstring.

## Deviations worth flagging (no instance was skipped)

1. **Two `validations` instances have PRD-impossible YAML setups** — `releasing_a_batch_whose_latest_hold_temp_check_failed_returns_haccp_hold_active` and `a_missing_haccp_step_is_reported_before_a_failing_one` both record a HACCP check against a `COMPLETED` batch, while PRD §3.5 accepts measurements only against `IN_PRODUCTION` or `RELEASED`. Both were translated by reaching the same end state legally (PASS → FAIL → restart → complete), which shifts the first instance's collateral literals from `haccp_rework_rounds` 0 / `haccp_risk_score` "40.00" to 1 / "55.00". The asserted outcome (`ERR_HACCP_HOLD_ACTIVE`, and the gate ordering) is unchanged.
2. **`cabin_breakdown` money keys are asserted by set-equality** in test_09 because the PRD names the breakdown but not its per-cabin key spellings.
3. **test_11's band-90 complement was redesigned**: the YAML's "amend the cost cap upward" is not PRD-supported (§3.1 documents amendments for meal specifications only), so the complement builds a second identical world at `cost_cap_per_pax_cents=6000` instead.
4. **test_14's seal-uniqueness complement deliberately uses a live `SEALED` cart** (before any waste manifest exists) rather than a `BROKEN` one, since whether a broken cart still "holds" its retained `seal_number` is not uniquely derivable from the PRD.

I did not read or write anything under `workspace/implementation/`, and I did not run the harness against it.

**Orchestrator note on launch ordering:** Steps 5 and 6 were intended to be launched in a single assistant message. They were in fact launched in two consecutive messages seconds apart, so both ran concurrently for their entire duration (Step 6 finished while Step 5 was still writing test files). Physical isolation held anyway: `test_suite/` was empty at Step 6's start, and Step 6 confirmed it never read the test directories or the two design yamls.

## Step 7: Run tests and iterate — 2026-09-03T10:12:00.000Z

## Exit condition met — 8/8 rounds green (126 passed / 126 total in every round)

### Iterations run
Four full 8-round parallel sweeps (`--isolation per-test-server`, 8 concurrent rounds under `setsid nohup … & wait`):

| sweep | total | passed | failed | errors |
|---|---|---|---|---|
| 1 | 126 | 65 | 13 | 48 |
| 2 | 126 | 122 | 3 | 1 |
| 3 | 126 | 125 | 1 | 0 |
| 4 | 126 | **126** | 0 | 0 |

### Tests deleted
**One assertion removed** (STEP 1c partial-coverage split; no whole test deleted):

- `test_suite/test_02_state_machine_transitions.py::test_cancelling_a_loaded_flight_unwinds_five_entity_families` — dropped `assert_cart_axes(cart, "BUILDING", "BROKEN")`. **Category: BRANCH-ASYMMETRIC SIDE EFFECT / non-unique derivability.** PRD §3.8 enumerates the cancel's side-effect set as exactly five families (orders, batches, cart items, manifests, runs) and adds "Rows that had already reached a terminal state are left exactly as they were" — the cart row is never named. The §3.6 void ripple cannot be in force on this edge either, since the cancel drives the manifest to `VOID` (not `AMENDED`) and the flight to `CANCELLED` (not `PLANNED`). Two divergent PRD-faithful implementations exist. The covered assertions were kept: `loaded_units == 0` (follows from "every cart item in `ACTIVE` becomes `VOID`" plus §3.6's definition of `loaded_units`), the retained `seal_number`, and the flight ledger.

### Fixes to `test_helpers/`
- `test_helpers/fixtures.py` → `flight_batches()` — was `ok(...)["data"]`, but `prd_bench_local_runner.testing.validate_success` already unwraps the envelope and returns `body["data"]`, so a list endpoint hands back the row array itself. The double unwrap raised `TypeError: list indices must be integers or slices, not str` and, because `Env.reload_batches()` feeds `advance_to_released`, took out **all 61** sweep-1 failures (48 of them as setup errors).

### Fixes to `test_suite/`
- `test_08…py::test_a_manifest_create_holding_a_superseded_flight_version_is_refused` — removed the `{"flight_id": …}` filter from `api.list_delivery_runs(...)`. PRD §4 makes `GET /delivery-runs` filterable by `loading_manifest_id`, `truck_id`, `stand_id`, `recovery_of_run_id` and `status` only, and §2.6 band 30 rejects unknown query fields, so the request was correctly answered `ERR_INVALID_REQUEST`. No manifest exists at that point, so the unfiltered listing is the equivalent "no run exists" check.
- `test_08…py::test_a_cascade_advances_the_cascaded_row_and_a_refusal_advances_nothing` — the assertions `…_after["updated_at"] != …_before["updated_at"]` were unsatisfiable as written: PRD §2.4 says the service never consults a wall clock and every recorded instant is the logical clock's own reading, so two writes at one frozen instant record byte-identical strings. Rather than weaken them, the test now moves the clock to `2026-09-15T06:20:00Z` before the load (still hours inside the 08:30 release deadline) and additionally asserts both rows' `updated_at` equals that instant exactly — strictly stronger and fully §2.4/§2.5-derived.

### Fixes to `implementation/`
All four trace to PRD §2.5 ("every mutation that changes the row increments `version` by exactly 1 and refreshes `updated_at`") plus §2.9 ("every affected row is treated as a real mutation … exactly as if it had been written directly"):

- `db.py::touch` — the version bump is now applied at most once per row per request (dedup set on `flask.g`); the `updated_at` refresh stays unconditional. §2.5 says *exactly* 1, and a single request can reach one row down two hops — a delay both retimes the flight and, via the reslot cascade, pulls it `LOADED → PLANNED`, which was giving the flight +2.
- `routes/carts.py::load_item` — now touches the cart unconditionally and touches the flight. §3.6: "Each successful load recomputes the cart's `loaded_units` … along with the flight's `units_loaded`, `unit_balance` and `cost_per_pax_cents`." (Previously the cart moved only on `EMPTY → BUILDING` and the flight never moved at all — the sweep-2 failure `assert 3 == (3 + 1)`.)
- `services/cascade.py::void_item` — touches the cart even when neither axis had anywhere to move, and touches the flight. §3.6: "The cart's `loaded_units` and the flight's `units_loaded`, `unit_balance` and `cost_per_pax_cents` are all recomputed."
- `services/cascade.py::reject_batch` and `routes/production.py::complete_batch` — touch the flight. §3.5: both the rejection and the completion "recompute the flight's `units_produced`, `units_scrapped` and `unit_balance`." The per-request dedup keeps the flight at +1 in `cancel_flight` (which rejects every batch in a loop) and in the four-hop post-release cascade.

Storage remains in-memory dicts with nothing seeded; no endpoint, field, header or capability was added.

### One failure that was *not* a defect — worth recording
`test_13…::test_a_reseal_two_hops_away_blocks_dispatch_until_the_manifest_is_re_issued` errored in **all 8** rounds of sweep 2 with `ConnectionResetError(104)` / `RemoteDisconnected` during fixture setup. Root-caused from the per-port server logs: every one of the 8 servers logged `Terminated` (SIGTERM) at the *same wall-clock second*, 07:47:53, but at a *different* request in its fixture chain — a host-wide kill, not a per-test crash. The runner itself only ever uses `kill -9` (`Killed`), which is what the other 125 boots in each log show. Re-running that file in isolation passed 8/8. No code was changed for it, and it has not recurred in the two subsequent sweeps.

**Orchestrator verification of the final sweep artifacts:** the orchestrator independently read all 8 `workspace/implementation/results.{1..8}.json` files after the agent exited and confirmed each reports `passed == total == 126`. The suite grew from 120 to 126 tests during Step 7 (partial-coverage splits), and one assertion — not a whole test — was removed. Step 8 is therefore NOT skipped: Step 7 applied 4 `implementation/` fixes, 1 `test_helpers/` fix and 2 `test_suite/` fixes.

## Step 8: Finalize PRD — 2026-09-03T10:24:00.000Z

Done. `PRD_FINALIZED.md` written with 5 paragraph-level edits.

## Line counts
- `PRD.md`: 421 lines / 14,628 words
- `PRD_FINALIZED.md`: 421 lines / 14,984 words
- Delta: 0 lines (+0.0%; the file is one-paragraph-per-line), 5 of 421 lines revised (1.2% of lines), +356 words (+2.4%)

## Changes (one per bullet)
- **§2.5** — insert — version increments are counted **once per row per request**: a row reached twice (directly + a cascade hop, two hops meeting on it, or a loop revisiting one parent) advances `version` by exactly 1 for the request, and the `updated_at` it keeps is that request's logical-clock reading — `implementation/db.py:60-84`
- **§3.5** (completion paragraph) — insert — every batch transition the PRD describes as recomputing the flight's `units_produced`/`units_scrapped`/`unit_balance` (completion, pre-release rejection, post-release cascade) also increments the **flight's** `version`; a release and the `RELEASED → DISPOSED` edge do not — `implementation/routes/production.py:136-141`, `implementation/services/cascade.py:139-150`, `implementation/routes/uplift.py:105-109`, `implementation/routes/production.py:169-173`
- **§3.6** (loading paragraph) — insert — an accepted load increments **both** the cart's and the flight's `version` (and refreshes both `updated_at`) even when the build axis stayed in `BUILDING`; the item opens at `version` 1 — `implementation/routes/carts.py:107-113`
- **§3.6** (voiding paragraph) — insert — item, cart and flight are each mutated by a void; cart and flight `version` increment even when neither cart axis had anywhere to move — `implementation/services/cascade.py:108-132`
- **§3.8** (cancellation paragraph) — insert — the five families are the whole cascade: cart rows stay untouched (`build_status`, `seal_status`, `seal_number`, `sealed_by_user_id`, `version` all unchanged) while `loaded_units` falls to 0 from the item voids; no `BUILT → BUILDING`, no seal break, no manifest amendment on this edge — `implementation/routes/flights.py:220-258`

## Per-edit pre-edit search log

**Edit 1 (§2.5 once-per-request counting)**
(a) Subject: how many times one request may advance a single row's `version`.
(b) Enumerated: `db.py::touch` (the `flask.g` dedup set, `count` parameter never passed >1 — `grep 'count='` returns only the definition); `grep '"version"'` across `implementation/` confirms `db.py:55` and `db.py:82` are the only writers; all 60 `db.touch` callsites, with the same-row-twice paths read in full: `routes/flights.py::record_delay` (flight touched at :198 then again via `_reslot_runs → cascade.amend_manifest` at cascade.py:89; order touched at :207 then again in `_confirm_order` at :120), `routes/flights.py::cancel_flight` (flight at :229 then once per batch via `cascade.reject_batch` at cascade.py:150), `cascade.reject_released_batch_cascade` (flight reached from `reject_batch` and again from each `void_item`; one cart reached once per voided item), `cascade.refresh_airline_status`, `cascade.check_departure`.
(c) Adjustment: added the third clause "or once per item in a loop that revisits one parent" so the multi-batch/multi-item loops in `cancel_flight` and `reject_released_batch_cascade` are covered, and phrased the `updated_at` half as "that request's own logical-clock reading" (rather than adding `updated_at` to §2.4's enumeration) since `touch` always uses `clock.now()`.

**Edit 2 (§3.6 load bumps cart + flight)**
(a) Subject: which rows a successful `POST /carts/{id}/items` mutates.
(b) Enumerated: `routes/carts.py::load_item:99-114` (item insert, unconditional `db.touch(cart)`, `db.touch(flight)`); confirmed no other endpoint creates `cart_items` (`grep 'insert("cart_items"'`); confirmed `loaded_units`, `units_loaded`, `unit_balance`, `cost_per_pax_cents` are all derived at read time in `serialize.py:100-115,191-195` (so the version bump is a genuine choice, not a stored-field consequence); checked that the load touches no batch, manifest or airline row.
(c) Adjustment: scoped the sentence to the cart and the flight only — deliberately said nothing about batches or manifests, which `load_item` never touches.

**Edit 3 (§3.6 void bumps cart + flight)**
(a) Subject: which rows `cascade.void_item` mutates, and the no-axis-movement case.
(b) Enumerated: `services/cascade.py::void_item:108-132`; its two callers — `routes/carts.py::void_item:127` (the DELETE endpoint) and `cascade.reject_released_batch_cascade:159-162` (§3.5 hop 2), both of which therefore inherit the cart/flight bump; the *third* item-voiding path, `routes/flights.py::cancel_flight:242-245`, which voids inline and touches neither cart nor flight; `cascade.amend_for_cart`/`amend_manifest:79-93` (only invoked when an axis moved).
(c) Adjustment: kept the sentence inside the paragraph that describes the addressed-by-cart void operation and did **not** generalise it to "every void in the service", because the cancellation cascade voids items without the cart/flight bump; I also dropped a draft clause about the manifest hop being conditional on axis movement, since a pinned cart is always `BUILT` at issue and the conditional is unobservable — asserting it would have been a claim the impl cannot exhibit.

**Edit 4 (§3.5 flight version on completion/rejection)**
(a) Subject: whether a batch transition moves the flight's `version`.
(b) Enumerated every batch transition: `production.py::start_batch:52` (batch only), `production.py::record_check`/`_apply_failure:96-116` (HACCP_HOLD branch = batch only; third-fail branch → `reject_batch` → flight), `cascade.reject_batch:139-150` (flight), `cascade.reject_released_batch_cascade:153-162` (flight, once), `production.py::complete_batch:133-141` (flight), `production.py::release_batch:169-173` (**no** flight touch), `routes/uplift.py:105-109` `RELEASED → DISPOSED` (**no** flight touch), `flights.py::cancel_flight:236-239` (rejection loop → flight, deduped). Cross-checked `serialize.py::flight` to confirm `units_produced` spans `COMPLETED|RELEASED|DISPOSED`, so release and disposal genuinely change no counter.
(c) Adjustment: bound the rule to "wherever this document says a batch transition recomputes those flight counters" rather than "every batch transition", and added the explicit negative for release and `RELEASED → DISPOSED`, plus the once-per-request caveat for the multi-batch cancel loop.

**Edit 5 (§3.8 carts outside the cancel cascade)**
(a) Subject: the state of cart rows after a flight cancellation.
(b) Enumerated: `routes/flights.py::cancel_flight:220-258` (no write to any cart row anywhere in the handler); every other cart-mutating path, to confirm none is reachable from cancel — `cascade.void_item:114-127`, `cascade.check_departure:186-189` (`BUILT → LOADED`), `routes/uplift.py::create_waste_manifest:180-187` (`LOADED → RETURNED` + seal break), `routes/carts.py` load/build-completion/seal; `cascade.amend_manifest:79-89` (requires `ISSUED`, so the straight-to-`VOID` manifests cannot amend); `serialize.py::cart:194` (`loaded_units` derived, hence 0 without a cart write).
(c) Adjustment: framed it as "the cart rows themselves are outside it" and explained `loaded_units == 0` as a consequence of the item voids, so the sentence pins the cart's axes/`seal_number`/`version` without contradicting the retained aggregate behaviour; also named the three §3.6 hops that are *not* run, so a fresh implementer cannot import the void ripple into the cancel path.

---

**Orchestrator verification of Step 8 output:** `workspace/PRD_FINALIZED.md` exists (104,112 bytes vs PRD.md's 102,012) and is not byte-identical to `PRD.md`.

## Step 9: Complete PRD — 2026-09-03T11:26:00.000Z

**Orchestrator decision (recorded per the autonomy rule):** Step 9 was deliberately run as **three sequential, file-partitioned passes** over `implementation/` rather than one monolithic scan. A single subagent asked to walk ~4,100 lines of implementation reliably degenerates into a shallow skim and can emit a `PRD_COMPLETED.md` byte-identical to its source — i.e. the scan never actually ran. Partitioning forces exhaustive per-file coverage and makes the no-op failure mode detectable (each pass reports its own char delta). Pass 1 created `PRD_COMPLETED.md` from `PRD_FINALIZED.md`; passes 2 and 3 edited it in place, additively, and were forwarded the prior pass's cross-pass notes.

### Pass 1 of 3 — partition: `app.py, middleware.py, validate.py, errors.py, response.py, clock.py, db.py, timeutil.py, routes/helpers.py, routes/reference.py, routes/flights.py, routes/orders.py`

Pass 1 complete.

## Line counts and delta
- `PRD_FINALIZED.md`: 421 lines / 104,112 chars
- `PRD_COMPLETED.md`: 421 lines / 114,909 chars (**+10,797 chars**, 25 changed hunks)
- Structure preserved: identical heading count, identical table-row count, no new sections, no paragraph deletions.

## Counts
- **ambiguity-pins: 21**
- **mismatch-revisions: 4**

## Changes
- §2.1 — revise — mismatch — `X-User-ID` resolution only bites for `AirlineRep` (must name an `Airline`); other roles' ids are opaque non-blank strings, whitespace-trimmed, blank counts as absent; missing/unrecognised `X-User-Role` yields `ERR_FORBIDDEN_ROLE` — `middleware.py:51-62`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + 20 lowercase alphanumerics; `api_request_timestamp` is the host wall clock, not the logical clock — `response.py:15,21`
- §2.3 — insert — ambiguity — query string is a closed whitelist (unknown param → `ERR_INVALID_REQUEST`, checked before limit/offset bounds); `offset` has no maximum and past-end returns empty page; integer-formatted strings only; detail reads ignore query strings — `validate.py:161-184`
- §2.3 — insert — ambiguity — `created_at` ties broken by insertion sequence — `db.py:95`
- §2.4 — insert — ambiguity — clock call also exempt from the role check; returns `data.current_utc` in ms form; offsetless instants read as UTC, non-zero offsets refused — `reference.py:29-33`, `timeutil.py:29-35`
- §2.6 band 20 — revise — mismatch — "without exception" → except the logical-clock call — `reference.py:30`
- §2.7 — insert — ambiguity — version fields are required ints ≥ 0; malformed/negative → `ERR_INVALID_REQUEST`, not 412 — `flights.py:321,363`
- §2.8 — insert — ambiguity — two-decimal values emitted as plain JSON numbers (30.00 → `30.0`) — `serialize.py:14-20`
- §2.10 — revise — mismatch — enumerated the scoped collections; HACCP checks and cart items are deliberately unscoped (unfiltered lists, no `ERR_AIRLINE_SCOPE_VIOLATION`); trucks/stands never scoped — `routes/helpers.py:61-73`
- §3.1 — insert — ambiguity — bad or duplicate `iata_code` → `ERR_INVALID_REQUEST` — `reference.py:41,57-59`
- §3.1 — insert — ambiguity — unknown `airline_id` → `ERR_RESOURCE_NOT_FOUND` before `spec_code` uniqueness, which is `ERR_INVALID_REQUEST` — `reference.py:109-112`
- §3.1 — insert — ambiguity — spec/truck/stand amendment and pax refresh accept an empty body and still bump `version` — `reference.py:119-127`
- §3.2 — insert — ambiguity — `flight_number`/`tail_number`/`station_code` only non-empty strings (three-letter shape unenforced); duplicate triple → `ERR_INVALID_REQUEST` after airline resolution — `flights.py:48-62`
- §3.2 — insert — ambiguity — pax refresh reports `ERR_FLIGHT_COUNTS_LOCKED` from *every* non-`SCHEDULED` state, never `ERR_INVALID_FLIGHT_STATE` — `flights.py:89-90`
- §3.3 — insert — ambiguity — `STANDARD` spec → `ERR_INVALID_REQUEST`, ahead of all capture guards — `orders.py:32-33`
- §3.3 — insert — ambiguity — `reason` not persisted; action/role mismatch → `ERR_FORBIDDEN_ROLE` after existence + scope; wrong flight state on cancel → `ERR_INVALID_RESOURCE_STATE` — `orders.py:70,78-91`
- §3.3 — insert — ambiguity — wrong flight state on substitute → `ERR_INVALID_RESOURCE_STATE`; `substitute_meal_specification_id` conditionally required and checked after role dispatch; substitute resolved before state; airline then cabin under one code — `orders.py:99-113`
- §3.4 — insert — ambiguity — zero booked pax → `ERR_INVALID_FLIGHT_STATE`, evaluated after the status check — `flights.py:131-132`
- §3.4 — insert — ambiguity — a timely `REQUESTED` order whose effective spec is not `ACTIVE` stays `REQUESTED` with `version`/`updated_at` untouched; orders visited in `created_at` order — `flights.py:115-147`
- §3.4 — insert — ambiguity — production-plan answers 201 with `response_type` `"array"`, data = created batches in visit order, no flight, no pagination meta; empty array when nothing allocated — `flights.py:310`
- §3.6 — insert — ambiguity — draft manifest permitted from `SCHEDULED`/`COUNTS_LOCKED`/`PLANNED`/`LOADED`, refused from the terminal three with `ERR_INVALID_FLIGHT_STATE` after the version guard; `cart_seal_snapshot` opens as `[]` — `flights.py:326-339`
- §3.7 — insert — ambiguity — duplicate truck `registration` / stand `stand_code` within a station → `ERR_INVALID_REQUEST` — `reference.py:163-165,210-212`
- §3.8 — insert — ambiguity — `reason` on delay/cancel/order-change discarded; reopened order still needs an `ACTIVE` effective spec to reach `CONFIRMED`; single version bump per reopened order — `flights.py:191,208-209`
- §3.8 — insert — ambiguity — reslot visits runs in `created_at` order, settling each before testing the next, tests against already-shifted siblings and all flights' runs on that truck/stand, ignores cancelled runs and its own former window — `flights.py:155-183`, `calc.py:559-565`
- §3.8 — revise — mismatch — cancellation also refused from `DEPARTED` — `flights.py:225`
- §3.9 — insert — ambiguity — `lines` ≥ 1 entry, specs resolved in submitted order before version/state; explicit-null `observed_seals` treated as omitted; snapshot taken from the newest `ISSUED`/`AMENDED` manifest, 0 when none; `spec_code` sort is stable — `flights.py:364-433`
- §3.9 — insert — ambiguity — record `cost_per_pax_cents` is 0 when `uplifted_units` is 0; deviation clearing a sub-5.00 tolerance records `MINOR`; deviation finding raised before seal-mismatch finding — `flights.py:453,465-472`
- §4 — revise — mismatch — `GET /airlines` filterable by `status`/`waste_regime`; `GET /flights` also by `production_hold`; trailing slashes tolerated — `reference.py:68-71`, `flights.py:488`, `app.py:31`
- §5 — insert — ambiguity — unserved path → `ERR_RESOURCE_NOT_FOUND` 404; wrong method on an existing path → `ERR_INVALID_REQUEST` with HTTP **405**, not 400 — `app.py:43-52`

## Files walked (exhaustively, line by line)
`app.py`, `middleware.py`, `validate.py`, `errors.py`, `response.py`, `clock.py`, `db.py`, `timeutil.py`, `routes/helpers.py`, `routes/reference.py`, `routes/flights.py`, `routes/orders.py`. Read for context only: `serialize.py`, plus targeted excerpts of `services/calc.py` and `services/cascade.py` (constants, `standard_spec_for`, `provisional_requirement`, `spec_deviation_pct`, `deviation_severity`, `_live_runs_on`, `truck_conflict`/`stand_conflict`, `reject_batch`, `amend_manifest`, `raise_finding`), and one grep of `routes/production.py`/`routes/carts.py` to confirm the scope-guard gap.

Roughly **95 behaviors** classified as already-pinned — notably the whole validation ladder ordering (bands 10/20/30/40/50/60/65/70 as actually sequenced in `orders.py` and `flights.py`), the error catalogue's 43 id→status pairs, the success/error envelope shapes, `limit`/`offset` defaults and bounds, `has_more` semantics, once-per-request version counting, the default clock instant, provisional-requirement per-cabin ceil with ASCII `spec_code` tiebreak, retime's non-effects, `manifest_number` construction including void manifests in the ordinal, the delay's 90-minute reslot threshold and non-recomputation of `units_planned`, the cancellation cascade's five families and its exclusion of cart rows / seal breaks / manifest amendment, and the body-carried `flight_id` → `ERR_RESOURCE_NOT_FOUND` on order capture (already correct per band 60).

One cross-pass note for whoever owns `routes/carts.py` and `routes/audit.py`: those two resolve a **body-carried** `flight_id` with `ERR_FLIGHT_NOT_FOUND`, whereas band 60 and `orders.py` use `ERR_RESOURCE_NOT_FOUND`; `carts.py:67` likewise resolves a body `production_batch_id` as `ERR_RESOURCE_NOT_FOUND` rather than `ERR_BATCH_NOT_FOUND`. I left band 60 alone since it already matches my partition — those endpoint-local exceptions need pinning in their own sections.

### Pass 2 of 3 — partition: `routes/production.py, routes/carts.py, routes/manifests.py, services/cascade.py`

Pass 2 complete.

## Size
- `PRD_COMPLETED.md`: **114,909 chars → 119,645 chars** (+4,736). Line count unchanged at 421 — every edit is in-paragraph; no new sections, no new paragraphs, no pass-1 prose reverted or weakened.

## Counts
- ambiguity-pins: **14**
- mismatch-revisions: **5**

## Changes
- `§2.3` — insert — ambiguity — boolean-valued list filters (`production_hold`, `is_overflow`) accept only `true`/`false`, case-insensitively — `validate.py:198-201` via `routes/production.py:171`
- `§2.3` — revise — **mismatch** — PRD claimed HACCP checks override the default order with ascending `sequence_no` within a batch; impl applies no ordering at all, so the list is default creation order, which is ascending `sequence_no` only within one batch-and-step pair and interleaves two steps' series by when the readings were taken — `routes/production.py:194-200` (`simple_list` called with no `order`), `routes/helpers.py:104-110`
- `§4` (`GET /haccp-checks` row) — revise — **mismatch** — same claim in the endpoint table — `routes/production.py:194`
- `§2.6` band 80 — revise — **mismatch** — band said release fails when the clock "has reached or passed" the deadline; impl uses strictly-past for release (`now > deadline`, so exactly-at succeeds) while start and cart-load are exclusive (`>=`). Pinned the asymmetry; this also removes an internal contradiction with §3.5's "at or before" — `routes/production.py:157` vs `:44`, `routes/carts.py:76`
- `§3.5` (start) — insert — ambiguity — a batch in `PLANNED` whose owning flight is not `PLANNED` is refused `ERR_INVALID_BATCH_STATE`, never `ERR_INVALID_FLIGHT_STATE` — `routes/production.py:41-43`
- `§3.5` (measurement) — insert — ambiguity — a `measured_temp_c` with more than one decimal place is `ERR_INVALID_REQUEST` — `routes/production.py:64-67`, `validate.py:87-89`
- `§3.5` (risk score) — insert — ambiguity — `haccp_risk_score` is derived per read, so recording a check is not itself a batch mutation: a `PASS` check leaves the batch's `version`/`updated_at` untouched; only the state-moving `FAIL` branches touch the row — `routes/production.py:78-96`, `serialize.py:155`
- `§3.5` (completion) — insert — ambiguity — `produced_qty` is a required non-negative integer — `routes/production.py:124`
- `§3.6` (cart registration) — insert — ambiguity — body `flight_id` resolves as `ERR_FLIGHT_NOT_FOUND` (not band 60's generic code); registration accepted from `SCHEDULED`/`COUNTS_LOCKED`/`PLANNED`/`LOADED` and refused `ERR_INVALID_FLIGHT_STATE` from the three terminal states; `cart_code` is not required unique — `routes/carts.py:41-43,35`
- `§3.6` (cart registration) — insert — ambiguity — registration does not mutate the flight row — `routes/carts.py:45-52` (no `db.touch(flight)`)
- `§3.6` (loading) — insert — ambiguity — body `production_batch_id` resolves as `ERR_RESOURCE_NOT_FOUND`, **not** `ERR_BATCH_NOT_FOUND` — `routes/carts.py:67` (pass 1's note, verified)
- `§3.6` (loading) — insert — ambiguity — the cart build-axis test precedes the batch-release test, so a `BUILT` cart + unreleased batch reports `ERR_INVALID_CART_STATE` — `routes/carts.py:70-73`
- `§3.6` (loading guards) — revise — **mismatch** — "must not be past its `release_deadline_utc`" read as strictly-after; impl refuses at the instant itself — `routes/carts.py:76`
- `§3.6` (void) — insert — ambiguity — an item that exists under a *different* cart is `ERR_RESOURCE_NOT_FOUND`; the response carries the voided cart item, not the cart — `routes/carts.py:123-128`
- `§3.6` (void ripple) — insert — ambiguity — the pinning `ISSUED` manifest is matched on the snapshot entry's `cart_id`, never on whether its `seal_number` still agrees — `services/cascade.py:69-76`
- `§3.6` (sealing) — revise — ambiguity + **mismatch** — (a) the seal axis must be `UNSEALED`/`SEALED`/`BROKEN`: a cart already `RESEALED` refuses a further seal with `ERR_INVALID_CART_STATE` — this edge was entirely unstated; (b) PRD's prose order (BUILT → duplicate → not-released) contradicted impl's band order, revised to cart-state → released-batch → uniqueness; (c) a `REJECTED` waste manifest does not hold its seal number, and a `BROKEN` cart does; (d) neither the flight's status nor `loaded_units` is consulted — `routes/carts.py:175-186,151-158`
- `§3.6` (sealing) — insert — ambiguity — only the `SEALED → RESEALED` supersede amends the manifest; `BROKEN → RESEALED` amends nothing — `routes/carts.py:188,199-200`
- `§3.6` (issue) — insert — ambiguity — a flight not in `PLANNED` gives `ERR_INVALID_FLIGHT_STATE`, and the manifest's own state is tested first — `routes/manifests.py:26-30`
- `§3.6` (issue) — insert — ambiguity — a re-issue out of `AMENDED` leaves `amendment_count` where it stood and overwrites the snapshot/`total_units`/`issued_*` fields — `routes/manifests.py:61-65`

## Coverage
Walked all four partition files line by line: `routes/production.py` (213 lines, 9 endpoints), `routes/carts.py` (245, 8 endpoints), `routes/manifests.py` (87, 3 endpoints), `services/cascade.py` (189, 11 functions). Roughly 90 behaviors were already uniquely pinned — notably the whole HACCP verdict-constant set and `sequence_no` derivation, the risk-score formula and clamp, the two `FAIL` branches and the four-hop released-batch cascade, the release gate order, the flight-counter-recompute-is-a-mutation rule of §3.5, the six-guard load order, the void ripple with its "even when neither axis moved" version rule, the snapshot entry shape and `created_at` ordering, `check_departure`'s departure join (§3.7 line 247 pins it exactly, including carts `BUILT → LOADED`), and `refresh_airline_status`'s asymmetric hold/clear behavior (§3.10 line 295).

Two impl/PRD divergences I judged unreachable and deliberately left alone: `void_item` amends only when a cart axis actually moved (a cart pinned in an `ISSUED` snapshot is always `BUILT`+sealed, so an axis always moves), and `refresh_airline_status` skipping a flight already on hold when suspending (no flight can be held while the airline is `ACTIVE`).

## Notes for pass 3
- **`routes/audit.py:36` resolves a body `flight_id` as `ERR_FLIGHT_NOT_FOUND`**, the same exception as `carts.py:41`. I pinned carts in §3.6 but phrased it non-exclusively; §3.10's manual-finding prose still needs its own pin, since band 60 nominates `ERR_RESOURCE_NOT_FOUND`.
- `serialize.py:54-55` derives the airline's `open_finding_count`/`penalty_accrued_cents` from the finding rows on every read (via `cascade.open_finding_count`/`penalty_accrued_cents`, which I verified). §3.10 line 293 reads as stored-field arithmetic ("adding … to", "decrementing"); observably equivalent, but if you want it pinned it belongs to your `serialize.py` scan.
- `serialize.py:114` reports the flight's `cost_per_pax_cents` as 0 whenever `units_loaded` is 0. Pass 1 pinned the uplift-record mirror of this in §3.9; the flight's own field is in your partition.
- My §2.6 band-80 revision makes release strictly-past and start/load at-or-after. `routes/delivery.py` has no deadline logic, so there should be no conflict — but if `calc.py` holds any deadline comparison, check it against the revised wording.
- §2.3's overriding-order sentence now names *only* the uplift `lines` array. Worth confirming `uplift.py`/`calc.py` really does sort lines by `spec_code` ascending, since that claim is now the sole survivor of that sentence.

### Pass 3 of 3 — partition: `routes/delivery.py, routes/uplift.py, routes/audit.py, services/calc.py, serialize.py`

Pass 3 complete. `PRD_COMPLETED.md` edited in place, additively; pass 1 and pass 2 prose left intact.

**Size:** 119,645 chars before → 128,096 chars after (20 `Edit` calls).

**Counts:** 14 ambiguity-pins, 6 mismatch-revisions.

**Changes**

- §2.6 (band 110) — revise — mismatch — reordered the band's clause list so `ERR_SLOT_RESOURCE_UNAVAILABLE` precedes the truck/stand conflict codes, matching the impl; §5 already declares "within a band the earliest condition in the order stated for that band", so the old order was an active contradiction — `routes/delivery.py:29-46`
- §3.7 (window rules) — insert — mismatch — pinned the five-check evaluation order (ordering → slot band → resource availability → truck buffer → stand concurrency) with two worked collisions, pinned that both occupancy tests weigh every run whose status is not `CANCELLED` (including `DELIVERED`/`MISSED`/`RECOVERED`), and pinned that reservation never compares `station_code` — `routes/delivery.py:29-46`, `services/calc.py:559-595`
- §3.2 (intake) — revise — mismatch — the flight's `station_code` was described as "the station that trucks and stands must share for a delivery slot to be reservable"; no such check exists anywhere, so it is now recorded as reporting-only — `routes/delivery.py:73-92`
- §3.2 (intake) — revise — mismatch — narrowed pass 1's "matching a station against a truck's or stand's own `station_code`" clause to the `station_code` list filters, the only place such a comparison happens — `routes/helpers.py:97-101`
- §3.7 (events/dispatch) — insert — ambiguity — `note` accepted and discarded (no row, no response); a too-early dispatch reports `ERR_INVALID_RUN_STATE` (no dedicated lead-time code); the three dispatch tests run run-status → manifest-status → lead time — `routes/delivery.py:102-136`
- §3.7 (miss branch) — insert — ambiguity — an omitted/null/`SLOT_LOST` `miss_reason` is `ERR_INVALID_REQUEST`, raised before the path run is resolved — `routes/delivery.py:109-113`
- §3.7 (recovery) — insert — ambiguity — the recovered run is still `MISSED`, not `CANCELLED`, when the new window is tested, so it goes on occupying its own truck and stand — `routes/delivery.py:206-214`
- §3.4 (final requirement) — insert — ambiguity — standard trays are booked against the same `ACTIVE`/`STANDARD`/lowest-`spec_code` specification the provisional variant picks, a cabin with none contributing nothing; a standard spec that is also a confirmed order's effective spec merges into one demand row — `services/calc.py:279-351`
- §3.4 (release deadline) — insert — ambiguity — the whole-second expression truncates the sub-second remainder rather than rounding — `services/calc.py:398-405`
- §3.9 (reconciliation lines) — insert — ambiguity — `reuse_units`/`donate_units`/`destroy_units` open at 0, not null — `serialize.py:273-295`
- §3.9 (record lifecycle) — insert — ambiguity — the `status` list filter admits only `DRAFT`/`DISPOSITIONED`/`CLOSED` and rejects `VOID` with `ERR_INVALID_REQUEST`, though a `VOID` record still appears in an unfiltered list — `routes/uplift.py:14,113-119`
- §3.9 (cost report) — insert — ambiguity — `cap_breached` is strictly greater than the cap; `cabin_breakdown` always carries all three cabins in `FIRST`/`BUSINESS`/`ECONOMY` order with exactly the keys `cabin`, `cabin_pax`, `cabin_cost_cents`, `cabin_cost_per_pax_cents`, a zero-pax cabin reporting 0 rather than null — `services/calc.py:248-272`
- §3.9 (disposition) — insert — ambiguity — every `meal_specification_id` resolved under band 60 in submitted order; duplicate entries and a spec set unequal to the record's lines are both `ERR_INVALID_REQUEST`, reported after those references resolve but ahead of the record's own state — `routes/uplift.py:45-62`
- §3.9 (disposition) — insert — ambiguity — disposition does not re-derive `uplifted_units`, `gross_cost_cents`, per-line figures, `cost_per_pax_cents`, `spec_deviation_pct` or `seal_mismatch_count` — `routes/uplift.py:86-99`
- §3.9 (waste manifest create) — insert — ambiguity — the uplift record must be `DISPOSITIONED` (`DRAFT`/`CLOSED`/`VOID` → `ERR_INVALID_RESOURCE_STATE`, tested before regime and seal uniqueness); `seal_number` is a required non-blank string — `routes/uplift.py:146-168`
- §3.9 (waste manifest cascade) — insert — mismatch — this seal break clears `sealed_by_user_id` and is the one break that does **not** amend the pinning manifest, contrary to §2.9's general food→equipment→paperwork chain; no manifest, flight or uplift-record version moves — `routes/uplift.py:180-188`
- §3.9 (waste transitions) — insert — ambiguity — a missing/blank `rejection_reason` on `REJECT` is `ERR_INVALID_REQUEST` raised before the path manifest resolves, and a reason sent with `SEAL`/`DISPOSE` is ignored — `routes/uplift.py:194-201`
- §3.10 (manual finding) — insert — mismatch — a body `flight_id` naming nothing reports `ERR_FLIGHT_NOT_FOUND`, not band 60's generic code; `airline_id` resolves first under the generic code; the rep's own-airline restriction is band 50 and precedes both; `evidence_ref` is null when omitted — `routes/audit.py:31-46`
- §3.10 (resolution) — insert — ambiguity — `note` accepted and discarded; the action-to-role pairing is band 20 and, unlike §3.3's order-change endpoint, is checked *before* the finding is resolved, so a wrong-role action on a nonexistent finding is `ERR_FORBIDDEN_ROLE` — `routes/audit.py:50-67`
- §3.10 (resolution) — insert — mismatch — `open_finding_count` and `penalty_accrued_cents` are derived on every read from `OPEN` and `ACCEPTED` finding rows, not stored counters, so raising or resolving a finding leaves the airline's `version`/`updated_at` alone unless the suspension threshold is actually crossed — `serialize.py:54-55`, `services/cascade.py:15-47`, `routes/audit.py:86-89`

**Cross-pass notes:** all five verified. `audit.py:36` mismatch pinned; the derived-counter wording did mislead (it implied an airline-row mutation that never happens) and was pinned; the flight's `cost_per_pax_cents == 0 when units_loaded == 0` guard (`serialize.py:114`) is provably redundant — with no `ACTIVE` items every cabin cost is 0 so the blend is already 0 — and §3.9's "exactly as the flight itself reports 0 while nothing has been loaded" already covers it, so no edit; `calc.py` holds no deadline comparison, so pass 2's §2.6 band-80 wording needed nothing; `uplift.py`/`flights.py:418-419` does sort lines by `spec_code` ascending with a stable sort, so §2.3's sole surviving override claim holds (pass 1 had already noted the stability).

**Partition walked:** `routes/delivery.py`, `routes/uplift.py`, `routes/audit.py`, `services/calc.py`, `serialize.py` — all five line by line, with `flights.py`, `cascade.py`, `helpers.py`, `validate.py` and `errors.py` read for context. Roughly 60 behaviors were already uniquely pinned (all lateness banding, the marginal-band worked example, handling tiers, overhead-loaded item gross, the two-stage per-cabin then blended rounding with its worked example, deviation bands, finding base × multiplier amounts, the zone waterfall and its shelf-life floors, HACCP verdict constants and risk-score clamp, slot band leads, truck half-open buffering and stand closed-interval concurrency, every serializer field set, and the whole run/record/manifest/finding lifecycle set).

**Well-formedness:** section headers byte-identical to `PRD.md` (`diff` clean), §4 carries 68 endpoint rows, §5 carries 44 error rows, and the file ends cleanly on the final `ERR_COST_CAP_EXCEEDED` table row. No unbalanced inline code spans outside the two JSON fences.

### Step 9 totals and orchestrator verification

Across the three passes: **49 ambiguity-pins + 15 mismatch-revisions = 64 edits**; `PRD_FINALIZED.md` 104,112 chars → `PRD_COMPLETED.md` 128,096 chars (**+23,984 chars, +23.0%**), line count unchanged at 421 (every edit in-paragraph; no new or deleted sections).

Independently re-verified by the orchestrator: `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (so the scan genuinely ran — the known no-op failure mode did not occur); heading set is byte-identical to `PRD.md` (`diff` clean); §4 has 68 endpoint rows; §5 has 44 `ERR_` rows; the file ends on the complete final table row. Step 9 touched no code, so Step 7's green state stands: all 8 `workspace/implementation/results.{1..8}.json` report 126/126.

**Pipeline complete.**
