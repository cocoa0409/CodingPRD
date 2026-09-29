# Worklog — task_2197_aviation_fuel_farm_into_plane

## Step 1: Create task directory — 2026-08-31T17:54:41.154Z

Created `tasks/task_2197_aviation_fuel_farm_into_plane/` and `tasks/task_2197_aviation_fuel_farm_into_plane/workspace/`.

## Step 3: Copy shared files — 2026-08-31T18:02:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (53 lines, verified byte-identical to source). Recorded during RESUME-MODE re-verification; the copy was already present on disk from the crashed run.

## Step 2: Generate scaffold — 2026-08-31T22:35:00.000Z

RESUME-MODE note (orchestrator): no scaffold artifacts existed on disk at resume, so Step 2 was run fresh. It took four launches. Attempts 1 and 2 were killed by the harness stall-watchdog (600s with no file-write progress) having written zero bytes — transcript analysis showed both burned their entire budget on exploratory reading (79K-char SKILL.md, claim-extraction guide, all ~790 lines of scaffold_lint.py in five chunks, examples/ greps) before ever writing. Attempt 3 added mandatory process rules (first Write within 3 tool calls, ~150-300 line incremental appends, `wc -l` between appends, no linter-source archaeology) and wrote 323 valid lines before dying to a transient API server error mid-stream. Attempt 4 resumed that same agent via SendMessage from its on-disk tail, preserving its context and the 323 lines, and ran to completion. Scenario description was passed verbatim on every attempt; only process/anti-stall guidance was added.

Subagent summary (verbatim):

All three scaffold artifacts are complete and the linter reports **clean lint**.

## Files
- `/home/ubuntu/github/CodingPRD/tasks/task_2197_aviation_fuel_farm_into_plane/SCAFFOLD.yaml` — 3156 lines (§1.0–§1.7 only; contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_2197_aviation_fuel_farm_into_plane/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2460 lines, single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_2197_aviation_fuel_farm_into_plane/SCAFFOLD_CORNER_DESIGN.yaml` — 768 lines, single top-level key `scaffold_corner_design`

## SCAFFOLD.yaml counts
entities 16 · endpoints 75 · state_machines 10 · calculations 13 · validations 48 (one strict priority ladder, priorities 1–48) · errors 48 · roles 7 (`segregation_of_duties`, AirlineRep entity-backed) · concurrency_rules 2 (OCC on `FuelingOrder.version` for uplift posting, on `AirlineAccount.version` for invoice creation) · difficulty_level `expert_plus`, archetype `ledger_reconciliation` + `posture_driven_gating`, layers optimistic_concurrency / cascading_side_effects / dual_variant_calculation / ops_run_checkpoint, graph topology, parallel state-machine shape (tank service × quality dimensions), immediate consistency with a logical clock.

## §1.8 — 23 instances across all 9 rule_ids
dual_variant_calc 3 · combinatorial_formula 3 (modes a/b/c) · non_linear_state_machine 2 · transitive_cascade 2 (both depth-3) · priority_pair_validation_conflict 3 · boundary_precision_check 3 · cross_entity_state_dependency 2 · resource_temporal_overlap 2 · compensating_invariant 3. Every instance carries structured `setup_api_calls` with placeholder closure and pre-computed literal asserts (all money/volume literals hand-verified against the pinned formulas).

## §1.9 — 197 corner cases over 72 targets
entities 42 (all 16) · state_machines 30 (all 10) · calculations 39 (all 13) · validations 41 (17 ladder bands) · endpoints 17 · errors 3 · rbac 4 · complexity_layers 18 · consistency_model 3. Corners already pinned by §1.8 are stubbed with `excluded_because:` citing the specific §1.8 instance name.

## Two defects found and fixed during linting
1. `api_prefix` was `"/fuel-farms"` while all endpoint paths are root-relative — this alone caused 27 spurious `FK_REVERSE_UNREACHABLE` violations. Set to `""`.
2. Six entities (QualitySample, HydrantPit, Flight, FuelAuthorization, UpliftRecord, SpillIncident) had filtered-list GETs but no detail `GET /{collection}/{id}`, which left their inbound FKs unreachable (13 remaining violations). Added the six detail reads (endpoints 69 → 75).

Note: the linter reports `§1.9 instances scanned: 0` — the corner design is prose-structured (`target` / `cases` with `corner` / `expected_behavior`) rather than call-structured, so it contributes no machine-checked API calls; it produced no violations.

Orchestrator verification: all three files parse as valid YAML; section counts confirmed on disk (entities 16, endpoints 75, state_machines 10, calculations 13, validations 48, errors 48, roles 7); both design files confirmed single-top-level-key; SCAFFOLD.yaml confirmed free of design keys.

## Step 4: Generate PRD — 2026-08-31T22:50:00.000Z

Subagent summary (verbatim):

PRD.md is complete at `/home/ubuntu/github/CodingPRD/tasks/task_2197_aviation_fuel_farm_into_plane/workspace/PRD.md`.

**428 lines**, built incrementally (initial write plus 8 appends and 3 targeted edits). It ends at §5 with no audit footer.

**Sections produced**
- §1 Introduction — 3 paragraphs (business context, four design commitments, "ledger wearing safety equipment" framing)
- §2 Global Specifications — 11 subsections: 2.1 RBAC & identity, 2.2 API Response Structure (verbatim from `section-2.2-response-structure.md`, diff-confirmed), 2.3 Pagination, 2.4 Resource Identity/Timestamps/Versioning (+read-time recompute), 2.5 The Logical Clock, 2.6 Volumetric & Monetary Precision, 2.7 Farm Operational Posture, 2.8 Nested Path Resolution & Referential Integrity, 2.9 OCC, 2.10 Validation Precedence (all 48 rules in 8 ordered bands), 2.11 Cascade Depth & Ledger Conservation
- §3 Business Logic — 9 domain-derived subsections: farm standup → parcel receipt & volume correction → verdict/quarantine/re-test/rejection → tank custody (dual dimensions) → authorizations & airline credit → into-plane fuelling → asset fitness → spill response & freeze cascade → period close (reconciliation + invoicing)
- §4 Endpoint table — 75 rows, 4 columns
- §5 Error table — 48 rows, 2 columns

**Coverage confirmation** — all 14 entities (fields, enums, defaults, `common_fields: false` on `FilterChange` called out explicitly), all 9 state machines including the parallel tank dimensions and both depth-3 cascades hop-by-hop, all 12 calculations translated to prose with pinned rounding/evaluation order and every constant embedded in business context, all 48 validations with priority ordering and full `applies_to` scopes, all 48 error IDs, both `concurrency_rules`, and all 7 roles with identity semantics.

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 144 required, 144 present, 0 missing
- endpoints[].request_body: 86 required, 86 present, 0 missing
- endpoints[].query_params: 18 required, 18 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 48 checked, 48 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 47 checked, 47 fully expressed, 0 missing
- calculations[]: 12 checked, 12 fully expressed, 0 missing
- validations[] conditions: 48 checked, 48 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 75 checked, 75 expressed, 0 missing
- entities[].fields[] structured content: 144 checked, 144 reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (receipt RELEASE vs QUARANTINE, spill ESCALATE vs CONTAIN, TRUCK vs HYDRANT assignment, meter-ticket vs gauge-delta receipt basis, accrual vs invoiced exposure, throughput vs opening-stock variance), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 847
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, and no sibling task directory was read.

Orchestrator verification (independent, mechanical against SCAFFOLD.yaml): PRD.md is 428 lines. Entity fields 178/178 present (the subagent's own "144" undercounted; actual on-disk coverage is complete). Errors 48/48 present. Endpoint paths 75/75 present. State-machine states: 0 missing. Two entities (`FuelingAsset`, `UpliftRecord`) initially flagged by a naive identifier grep were confirmed covered in prose under the British spelling "fuelling asset" and as "uplift ticket"/`/uplift-records`; the subagent's "14 entities" line is a miscount in its prose, not a coverage gap. Calculation scaffold identifiers (e.g. `receipt_net_volume_at_15c`) do not appear verbatim by design — the doc-generator renders calculations as business prose, so identifier absence is expected and correct.

## Step 6: Generate implementation — 2026-08-31T23:00:00.000Z

Launched concurrently with Step 5 (both backgrounded). Step 6 was explicitly forbidden from reading `test_helpers/` or `test_suite/` even if they materialised on disk during its run, preserving the PRD-only contract despite Step 5 running in parallel.

Subagent summary (verbatim):

Implementation complete and verified.

## Files created

All under `/home/ubuntu/github/CodingPRD/tasks/task_2197_aviation_fuel_farm_into_plane/workspace/implementation/`:

| File | Lines | Role |
|---|---|---|
| `start.sh` | 8 | Guarded launcher (`set -euo pipefail`, installs Flask only if missing, `exec python3 app.py`) |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 66 | `create_app()`, blueprint registration, envelope-shaped error handlers, `PORT` binding |
| `core.py` | 264 | 48-entry error→HTTP map, response envelope, Decimal/ROUND_HALF_UP helpers, logical clock, in-memory `Store` |
| `authz.py` | 167 | 7-role auth via `X-User-ID`/`X-User-Role`, typed payload extractors, range/enum/FK helpers |
| `calc.py` | 488 | All 13 calculations (VCF/alpha, receipt volumes, sample verdicts, permit throughput, tank & onboard book volumes, element life, reliability score, farm posture, pricing/rebate/admin fee, exposure, invoice totals, authorization code minting) |
| `services.py` | 275 | Terminal guards, frozen/permit guards, the two depth-3 cascades (tank quarantine, farm freeze), order abort/unassign/cancel, pit occupancy, tank healing |
| `routes/farms.py` | 174 | Farms, permits, clock (7 endpoints) |
| `routes/tanks.py` | 289 | Tanks, gauges, samples, service/quality transitions (8) |
| `routes/receipts.py` | 308 | Receipts, sampling, lab results, verdict, reject (9) |
| `routes/assets.py` | 260 | Assets, status changes, filter changes, hydrant pits (10) |
| `routes/commercial.py` | 214 | Airline accounts, flights, fuel authorizations (9) |
| `routes/orders.py` | 549 | Fuelling orders: authorize/assign/unassign/start/uplift/complete/abort/cancel (13) |
| `routes/spills.py` | 175 | Spill incidents and the remediation tail (7) |
| `routes/billing.py` | 430 | Reconciliation runs and invoicing/payments (12) |
| `routes/__init__.py` | 0 | package marker |

Total ~3,668 lines. **75 endpoints** implemented, matching the PRD's endpoint inventory.

## Verification

- Boot check passed: `PORT=8121 bash start.sh` from a fresh process, then `POST /fuel-farms` → 201 with a well-formed `meta`/`response_type`/`data` envelope; module import (`python3 -c "import app; app.create_app()"`) is clean.
- Two end-to-end smoke suites pass on freshly launched servers: the happy path (farm → permit → tank → receipt → QC release → asset → account → flight → authorization → order → uplift → complete → invoice → payment → reconciliation → spill lifecycle) and an edge-case suite (FAIL verdict + quarantine cascade, retest ceiling, both scheduling geometries with pit half-open vs. asset closed+buffer overlap, wrong-stand rejection, both OCC rules, credit/dispute/payment bounds, filter change immutability, tank isolation, water-bottom quarantine).
- Conservation invariants verified live: truck abort restored `book_volume_liters` to exactly its pre-fuelling value with onboard back to 0.0, and account exposure returned to the sum of remaining reservations.
- Authorization code minting confirmed against §3.11 (`DL` + `260803` + `0001` + mod-97 check `62` → `DL260803000162`).

## Storage

In-memory only — a single module-level `Store` of plain Python dicts keyed by id, created at import. No SQLite, no file writes, no `/tmp` cache, no external services. No entity data is seeded, preloaded or hardcoded at startup; every farm, tank, asset, account, order, invoice and run exists only after a test creates it through the declared endpoints, so each per-test server relaunch starts fully empty.

One late refinement this session: per PRD §2.7, asset assignment is now blocked (`ERR_TANK_QUARANTINED`, 409) when the order's source tank is `QUARANTINED`, which is the narrow gate a `RESTRICTED` posture applies; orders on clean tanks at a restricted farm still proceed.

Orchestrator verification (independent): 3668 lines across 16 files confirmed on disk. Grep for persistence smells (`sqlite3`, file-write `open(...,'w')`, `json.dump`, `/tmp/`, `pickle`, `shelve`, `redis`, `psycopg`) returns zero hits — storage is in-memory only. Fresh boot on PORT=8151 succeeded; `POST /fuel-farms` returned a well-formed envelope with all counters zero (`open_spill_count` 0, `in_service_asset_count` 0, `posture` FROZEN pending permit) confirming no seeded data; a `FarmOperator` attempt at the same endpoint was correctly rejected with `ERR_ROLE_NOT_PERMITTED`. Route-map diff against SCAFFOLD.yaml after normalising path-parameter names: **75 declared vs 75 registered, EXACT MATCH, zero missing and zero extra** — confirming both full endpoint coverage and that no undeclared endpoint was invented. `GET /fuel-farms` correctly returns method-not-allowed (the scaffold declares no collection listing for farms).

Host note: an unrelated pipeline (task_2201) is running concurrently on this host with ~9 live Flask processes of its own. Cleanup of this task's smoke server was therefore done by port check rather than a blanket `pkill`, and Step 7's 8-round parallel sweep should expect CPU contention (port collisions are prevented by the runner's flock-based port ledger).

## Step 5: Generate unit tests — 2026-09-01T00:35:00.000Z

Launched concurrently with Step 6. Required one resume: a transient API error ("system encountered an unexpected error") killed the agent mid-stream after it had written test_helpers/ plus test_01..test_35 (213 tests). All on-disk work was durable and preserved; the agent was resumed via SendMessage with an orchestrator-computed coverage gap (queue B: 195 emittable vs 167 emitted) so it could close or explicitly account for the shortfall rather than stopping at an accidental gap. It then emitted test_35/test_36 and produced the skip ledger below.

Subagent summary (verbatim):

The suite is now complete. Emission plan reconciled against both design indices; nothing accidental is left uncovered.

## Deliverables

`/home/ubuntu/github/CodingPRD/tasks/task_2197_aviation_fuel_farm_into_plane/test_helpers/` — 9 files, 2028 lines (`__init__` 24, `api_client` 291, `api_errors` 108, `assertions` 221, `constants` 79, `factories` 231, `fixtures` 529, `test_users` 71, `types` 474).

`/home/ubuntu/github/CodingPRD/tasks/task_2197_aviation_fuel_farm_into_plane/test_suite/` — `conftest.py` (45) + 36 test files, 8480 lines total, **218 tests**. Files added after the interruption: `test_35_corner_graph_and_tank_dimensions.py` (138 / 3 tests), `test_36_corner_segregation_scope_and_consistency.py` (278 / 5 tests). All other files untouched.

Everything compiles; the citation/tag checker reports `checked 218 tests, 0 problems` (every test has exactly one `Design:` line as the docstring's last line, every tag resolves to a real instance, every `PRD §x.y: "…"` quote is verbatim in PRD.md).

## Coverage accounting

- **Queue A (Difficulty):** 9 rules / 23 instances, 0 stubs → **23/23 covered**, 46 tests (2 per instance).
- **Queue B (Corner):** 197 instances, of which 2 carry case-level `excluded_because` → 195 emittable. **171 covered** by 172 tests; **24 skipped** (below).
- The 2 case-level stubs correctly received no tests: `state_machines/quarantined_is_not_terminal`, `state_machines/restricted_has_four_independent_causes`.

The earlier "28-instance gap" was really 5 unwritten instances plus the documented skip ledger: the 5 were emitted in `test_36` (`complexity_layers/the_sample_release_pair_is_the_only_segregated_pair`, `complexity_layers/segregation_survives_a_retest_round`, and all three `consistency_model` instances).

## SKIPPED queue-B instances (24)

All are "PRD does not uniquely-derive the asserted outcome" unless noted; in most cases the PRD states the *rule* but never names the error id the corner asserts.

entities (5): `pit_stand_code_must_match_the_flight_stand` (§3.6 states the stand-code equality rule but never assigns `ERR_DELIVERY_MODE_MISMATCH` to it) · `credit_hold_blocks_authorization_independently_of_the_limit` · `manual_void_while_an_order_is_in_flight` · `storm_drain_incident_cannot_close_without_a_regulator_reference` (`ERR_SPILL_NOT_REPORTABLE` is mapped by §2.10 band 5 to spill *escalation* only) · `post_blocked_while_any_tank_is_quarantined` (§3.9 states the guard; `ERR_TANK_QUARANTINED` is mapped only to order authorization, fuelling start and uplift posting).

state_machines (5): `out_of_service_is_absolutely_terminal` · `expired_beats_redeemed_when_the_clock_has_passed` · `down_for_filter_to_filter_due_is_unreachable` · `posture_is_never_settable_by_an_endpoint` (no endpoint exists to attempt it) · `expired_permit_cannot_be_suspended_or_reinstated`.

calculations (2): `zero_gross_ticket` (a zero gross needs `meter_end == meter_start`, which §3.6 forbids outright) · `tank_density_read_live_at_posting_time` (no endpoint mutates a tank's density).

validations (7): `read_endpoints_are_broadly_permitted` · `reconciliation_measurement_naming_a_foreign_tank` · `unknown_field_is_rejected_strictly` (no PRD sentence says unknown keys are rejected) · `uplift_ticket_number_is_unique_per_farm_not_globally` (§3.6 says unique across *all* tickets, contradicting the corner) · `frozen_farm_still_permits_remediation_writes` · `permit_not_active_is_distinguishable_from_farm_frozen` · `sample_verdict_fail_blocks_the_quality_release` (`ERR_SAMPLE_VERDICT_FAIL` is mapped to receipt verdicts only).

endpoints (2): `clock_may_move_backwards` (backwards motion unspecified, and the expected "asset leaves FILTER_DUE" contradicts §3.7) · `meta_timestamp_follows_the_logical_clock` (§2.5 enumerates clock-derived *row* fields, not `meta.api_request_timestamp`).

complexity_layers (3): `account_version_bumps_on_pricing_relevant_changes` (unreachable — no endpoint adjusts a credit limit) · `the_self_referencing_invoice_edge_terminates` (PRD never states a self-naming `replaces_invoice_id` is 422) · `an_operation_may_require_agreement_across_both_dimensions` (§3.6 line 231 gives `ERR_TANK_QUARANTINED` for any tank not RELEASED+IN_SERVICE, contradicting the corner's expected `ERR_INVALID_TANK_STATE` for the ISOLATED case).

Orchestrator verification (independent): 36 test files + conftest; 10508 lines across test_suite/ + test_helpers/; `python3 -m compileall` clean. Grep for `pytest.mark.skip`, `pytest.mark.xfail`, `@skip`, `pytest.skip(` across both directories returns **zero hits** — no test was dodged rather than emitted or deleted. AST audit of all 218 tests: exactly one `Design:` tag each (0 untagged, 0 dual-tagged), and 0 dangling tags (every tag's instance name resolves against the design YAMLs). Queue split confirmed 46 A / 172 B.

## Step 7: Run tests and iterate — 2026-09-01T01:27:00.000Z

Subagent summary (verbatim):

All 8 rounds green. Final sweep: **218/218 passed, 0 failed, 0 errors** in every one of the 8 concurrent rounds.

## Summary

**Iterations run:** 2 full 8-round parallel sweeps (the first invalidated mid-flight once the upstream `test_helpers` bug was found and killed by PID, targeting only `task_2197` processes) plus ~8 targeted per-test-server subset runs used as the fast inner loop. Final sweep: all 8 rounds `passed == total == 218`.

**Tests deleted (PRD-silence).** No whole test was removed; five uncovered assertions were trimmed under STEP 1c partial coverage:
- `test_12::test_an_exemption_certificate_zeroes_the_excise_and_the_sales_tax` and `test_12::test_an_into_plane_only_line_is_handling_charges_only` — dropped `into_plane_fee_cents` / `flowage_fee_cents` / `federal_excise_cents` / `state_sales_tax_cents`. **COMPUTED-FIELD SILENCE**: §3.6 names only `fuel_component_cents`, `volume_tier_diff_cents_per_liter` and `billed_line_cents` as ticket fields; the other four appear only as formula intermediates. Scaffold rule: five-money-components-rounded-before-summing.
- `test_21::test_the_into_plane_minimum_swallows_a_small_ticket_and_the_tax_follows_it` — same pattern, same four fields; the 2,500-cent floor is still verified through `billed_line_cents == 358616`.
- `test_29::test_a_status_filter_and_a_parent_filter_narrow_the_same_result` — dropped `{"status": "NOT_A_STATUS"} → ERR_FIELD_OUT_OF_RANGE`. **VALIDATION SILENCE on query parameters**: §2.3 gives that error to `limit`/`offset` only and §2.10 band 3 scopes enumeration constraints to *payloads*; treating an unknown filter value as matching nothing is equally faithful. Scaffold rule: `filter_by_status_combines_with_the_fk_filter`.
- `test_28::test_a_held_run_needs_words_and_not_merely_a_field` — dropped the `"   "` case. PRD never mentions whitespace or blank-string handling anywhere; "non-empty" literally admits `"   "`. The empty-string case (verbatim covered) is kept.

**Fixes to `test_helpers/`:**
- `fixtures.py` / `register_flight` — seed the canonical `scheduled_departure_utc` into `overrides` *before* the factory fills its own `2026-08-01T12:00:00Z`; the old `setdefault`-after-factory was dead code, so every flight departed nine days before the canonical clock and every derived authorization was born `EXPIRED`. This one bug was the upstream cause of most order-lifecycle failures.
- `fixtures.py` / `create_order` — same ordering trap for `window_start_utc` / `window_end_utc`.
- `fixtures.py` / `make_tested_receipt` — return a re-read receipt; the creation response predates the sample draw that stamps `sampled_by_user_id`.
- `assertions.py` / new `assert_same_instant` — compares a bare-second literal against the server's three-fractional-digit rendering (§2.4) exactly, to the millisecond; used at 6 call sites in test_06/12/21/23/24/25.

**Fixes to `test_suite/` (STEP 2, all made the test more faithful; no skip/xfail, no error_id→status downgrade):** test_03 retest-round arithmetic (§3.2/§3.3: the first `SAMPLED` pass is the original QC draw, not a re-test); test_20 reorder so the first assignment precedes the second reservation; test_21 and test_24 tank opening volumes given the 2× headroom §3.6 requires at TRUCK assignment; test_07 reinstated-permit posture `OPEN`→`RESTRICTED` (§2.9 freeze-cascade asymmetry + §2.7 fourth restricted cause); test_11 clock moved into the booked window, redundant `DOWN_FOR_FILTER` status change dropped (at 103.0 kPa the asset is already there), `create_filter_change` expects 201; test_13 `ERR_UPLIFT_EXCEEDS_AUTHORIZATION` 422→409 per §5; test_16 `create_filter_change` expects 201; test_27 unpack the `(receipt, sample)` tuple; test_30 account opened at 62.00 cents/l to match its pinned money constants; test_32 escalated spill given a reportable 25.0 L volume.

**Fixes to `implementation/`:**
- `services.py` / new `posture_and_permit_guard` (wired into `routes/receipts.py` ×2 and `routes/orders.py` ×2) — on the four operations carrying both guards, a freeze caused by an unsatisfactory governing permit now reports `ERR_PERMIT_NOT_ACTIVE`, per §2.7; the seven frozen-only operations still always report `ERR_FARM_FROZEN` per §2.10.
- `routes/farms.py` / `set_clock` — a clock advance recomputes posture only (`refresh_farm`) and no longer fires the freeze cascade; §2.5 enumerates the auto-transition's effects closedly and names no cascade, unlike §3.1 (suspension) and §3.8 (escalation).
- `calc.py` / `reliability_score` — incidents in `REMEDIATED` and `CLOSED` have reached containment and keep their penalty; only `REPORTED`/`ESCALATED` are excluded.
- `routes/tanks.py` / gauge measurement — the water-bottom quarantine route fires only from `RELEASED`, since §3.4 defines all three routes as the single `RELEASED → QUARANTINED` transition.
- `routes/billing.py` / `record_payment` — returns HTTP 201 with the created payment resource (§4 creation rule; §2.9 lists payments as a child collection) and the payment carries `updated_at`/`version` (§2.4 exempts only `FilterChange`).

Invariants held: exactly 75 endpoints registered, storage in-memory only, no seeded data, and the runner's `results.*.json` and `__pycache__` artifacts cleaned out of `implementation/`.

Orchestrator verification (independent): because the subagent deleted its `results.*.json` before exiting, the orchestrator did NOT take the green claim on trust — it re-ran the full 8-round parallel sweep itself (detached via nohup + sentinel polling, since 218 tests under per-test-server isolation exceeds the 600s foreground tool timeout). Result: **all 8 rounds independently reproduced 218/218 passed, 0 failed, 0 errors**, and the `results.{1..8}.json` artifacts required by the pipeline output spec were regenerated on disk. Post-Step-7 invariants re-checked directly: 218 test functions still present (confirming no whole test was deleted, only the five assertion trims above); zero `pytest.mark.skip` / `xfail` / `pytest.skip(` occurrences anywhere in test_suite/ or test_helpers/; exactly 75 routes still registered (no capability added to pass a test); no persistence smells in implementation/. Peak host load during the sweep reached ~16 on 32 cores with the unrelated task_2201 pipeline also running; no port collisions occurred (runner's flock ledger).

## Step 8: Finalize PRD — 2026-09-01T01:40:00.000Z

Not skipped: Step 7 applied 5 `implementation/` fixes, 4 `test_helpers/` fixes, 11 `test_suite/` fixes and 5 assertion trims, so PRD silences/mismatches existed to patch. The Step 7 entry above was inlined verbatim as `<step_7_diff>`.

Subagent summary (verbatim):

All edits are in place. `PRD_FINALIZED.md` is complete on disk.

## Line counts
- `PRD.md`: 428 lines
- `PRD_FINALIZED.md`: 434 lines (+6 lines, **+1.4%**; 12 lines revised in place, 2 short paragraphs inserted — 14 edit sites total)

## Changes (one bullet each)

1. **§2.3 Pagination** — revise — `limit`/`offset` are the only validated query params (non-integer also `ERR_FIELD_OUT_OF_RANGE`); filter params are matched literally and conjunctively, never validated, so an unknown enum value or non-existent FK yields an empty page rather than an error; empty/absent filters not applied; unknown param names ignored — `core.py:236-258`, `routes/orders.py:128`, `routes/assets.py:79-87`.
2. **§2.4 Identity/Timestamps** — insert — canonical `YYYY-MM-DDTHH:MM:SS.mmmZ` rendering applies to *every* resource instant including client-supplied ones (parsed, normalised to UTC, re-rendered, not echoed verbatim); timestamp equality is instant-to-the-millisecond — `core.py:164-168`, `core.py:204`, `routes/commercial.py:101`, `routes/tanks.py:169`.
3. **§2.7 Posture** — revise — `ERR_PERMIT_NOT_ACTIVE` substitutes for `ERR_FARM_FROZEN` only on the four operations that also carry the active-permit guard — `services.py:64-80`.
4. **§2.10 band 3** — insert — "non-empty" is a literal `!= ""` test with no trimming; whitespace-only strings pass and are stored as supplied — `authz.py:39-45`, `routes/billing.py:187`, `routes/spills.py:96`.
5. **§2.10 band 5** — insert — on the four dual-guard ops the guards are fused and the permit condition is inspected *first*; the other seven always report `ERR_FARM_FROZEN` whatever the freeze cause — `services.py:64-80`, callsites `routes/receipts.py:62,245`, `routes/orders.py:157,385`.
6. **§2.10 band 8** — revise — `ERR_INSUFFICIENT_TANK_VOLUME` also fires on order **assignment** (TRUCK supply check) — `routes/orders.py:289`.
7. **§3.1 Logical clock** — insert — the clock-advance effect list is closed; a permit expiry that freezes a farm on a clock advance does **not** fire the freeze cascade — `routes/farms.py:31-54`.
8. **§3.4 Gauging** — revise — the water-bottom quarantine route fires only from `quality_status` `RELEASED`; `ON_TEST`/`QUARANTINED` tanks just record the depth; the gauge is never refused on water-bottom grounds — `routes/tanks.py:280-285`.
9. **§3.5 Authorizations** — insert — lazy expiry runs on the creation response, so an authorization for an already-past departure is born `EXPIRED` at `version` 2 — `routes/commercial.py:166`, `services.py:83-89`.
10. **§3.6 Assignment** — revise — names `ERR_INSUFFICIENT_TANK_VOLUME` for the TRUCK supply check, spells out the ~2× tank headroom implied by `available_volume_liters` being net of the order's own reservation, and pins that the check runs last — `routes/orders.py:284-290`.
11. **§3.6 Pricing** — insert — the ticket persists exactly `volume_tier_diff_cents_per_liter`, `fuel_component_cents`, `billed_line_cents`; the four fee/tax components are intermediates only; the tier diff is recorded even for `INTO_PLANE_ONLY` — `calc.py:388-411`, `routes/orders.py:426-428`.
12. **§3.7 Asset status endpoint** — revise — the explicit endpoint admits exactly six moves; anything else (including a redundant restatement, or leaving `DOWN_FOR_FILTER`) is `ERR_INVALID_ASSET_STATE`; no asset status is terminal; automatic/cascade moves bypass the set — `routes/assets.py:107-114`, `services.py:20-22`.
13. **§3.7 Reliability** — revise — penalties apply to incidents in `CONTAINED`, `REMEDIATED` *or* `CLOSED`; only `REPORTED`/`ESCALATED` are excluded — `calc.py:285-302`.
14. **§3.9 Payments** — insert — a payment is its own resource (`invoice_id`, `amount_cents`, `received_at_utc`, plus §2.4 `id`/`created_at`/`updated_at`/`version`); the endpoint answers **201** returning the created payment, not the invoice — `routes/billing.py:397-435`, `core.py:218-223`.

## Per-edit pre-edit search log

| # | (a) Subject | (b) Impl paths enumerated / read | (c) Wording adjustment |
|---|---|---|---|
| 1 | Query-param handling on list endpoints | `core.py:paginate/listing`; every `request.args` site: `assets.py:79-87,244-246`, `billing.py:53,281`, `commercial.py:115,178`, `orders.py:128,458`, `receipts.py:93,216`, `spills.py:63`, `tanks.py:100` — all uniform `if val:` exact match | Said "matched literally and conjunctively" and added the empty-value/unknown-name clauses so the uniform `if val:` idiom is fully described; deliberately did *not* claim any filter validation exists anywhere |
| 2 | Rendering of instants on resources | `core.py:fmt_dt/now_iso/parse_dt`, `authz.py:req_dt/opt_dt`; grepped every `*_at_utc`/`*_utc` write — only `commercial.py:161` (`expires_at_utc`) is indirect, and `calc.mint_authorization:494` uses `fmt_dt` | Scoped to "instants the server puts on a resource" so the wall-clock `meta.api_request_timestamp` (`core.py:77-83`) is not mis-described; listed the client-supplied fields explicitly after verifying each goes through `fmt_dt` |
| 3 | Which error a frozen farm reports | `services.py:frozen_guard/permit_guard/posture_and_permit_guard`; all 11 guard callsites; also the *other* users of `ERR_PERMIT_NOT_ACTIVE` at `farms.py:151,169,172` (permit suspend/reinstate state guards) | Phrased as an exception scoped to "the four operations which also carry the active-permit guard listed in §2.10" so the permit-lifecycle uses of the same id are untouched |
| 4 | Non-empty string semantics | `authz.py:req_str` (`allow_empty`), `billing.py:175-189` (`variance_override_reason`), `spills.py:81-99` (`regulator_reference` on escalate), `spills.py:168` (on close), `farms.py:147` (`suspension_reason`) | Added "Which identifier an empty value reports is fixed by the rule that demands the field" because the three sites report three different ids (`ERR_INVALID_PAYLOAD`, `ERR_VARIANCE_OVERRIDE_REQUIRED`, `ERR_SPILL_NOT_REPORTABLE`) |
| 5 | Guard evaluation order in band 5 | `services.py:64-80`; the 4 fused sites and their surrounding check order (`receipts.py:62,245`, `orders.py:157-174`, `orders.py:385-410`); the 7 frozen-only sites (`assets.py:131,159`, `orders.py:82,225,329`, `receipts.py:122`, `tanks.py:208`) | Left band 5's opening sentence verbatim and framed the addition as applying to "exactly those four operations", so the seven frozen-only ops keep the original rule |
| 6 | Where `ERR_INSUFFICIENT_TANK_VOLUME` fires | grepped all 3 raise sites: `orders.py:174` (authorize), `:289` (TRUCK assign), `:408` (uplift) | Qualified the new list entry with "for the `TRUCK` supply check" so a HYDRANT assignment is not described as carrying it |
| 7 | Effects of a clock advance | `routes/farms.py:31-54`; `services.py:refresh_farm` vs `apply_posture_change`/`freeze_cascade`; all 9 `apply_posture_change` callsites (farms ×2, orders, spills ×4, tanks, billing) | Changed "writes nothing else" to "beyond those re-evaluations and the status moves and `version` bumps they themselves entail", because `set_clock` does `touch(asset)` on an element-life status change; added "The freeze cascade fires on the child mutations that recompute posture" so the 9 cascade sites stay in force |
| 8 | Routes into tank quarantine | `routes/tanks.py:280-285` (gauge), `:247-259` (direct, requires `RELEASED`), `receipts.py:278` (verdict cascade, unconditional via `svc.quarantine_tank`); `services.py:224-227` | Restricted the new precondition to the gauge and direct routes ("this route, like the direct request") so the receipt-verdict cascade — which per §3.3 also fires from `ON_TEST` and in impl is unconditional — is not narrowed |
| 9 | Authorization expiry evaluation points | `services.py:83-89` + all 7 `expire_authorization` callsites (`commercial.py:166,175,195,204`, `orders.py:163,500`, `farms.py:39`); `core.py:touch`, `base_row` | Stated `version` 2 only after confirming `base_row` starts at 1 and `touch` bumps once; said "is not refused" to avoid implying a new error path |
| 10 | TRUCK assignment supply check | `routes/orders.py:284-290`; `calc.recompute_tank` (available = book − reserved − unpumpable, floored at 0); reservation taken at `orders.py:157-195` | Wrote "roughly twice" rather than an exact 2× formula, since `unpumpable_bottom_liters` also subtracts; noted the check runs after band 7 to match the code's position below the window-conflict loops |
| 11 | Persisted ticket pricing fields | `calc.py:price_uplift` (writes only 3 fields), `orders.py:415-435` (initialisers), `calc.py:439-440` (exposure), `calc.py:453-464` (invoice totals); confirmed `price_uplift` has exactly one callsite so tickets are never re-priced | Added the `INTO_PLANE_ONLY` clarification for `volume_tier_diff_cents_per_liter` because impl writes the selected diff unconditionally while §3.6 says "no differential is applied" — without it, asserting the field exists would have created a fresh ambiguity |
| 12 | Asset status-change transition set | `routes/assets.py:100-138`; `calc.apply_asset_auto_status:314-324`; `services.freeze_cascade:240-244`; `services.TERMINAL` / `terminal_guard` (no asset key) | Added the closing sentence excluding automatic and cascade moves, since `apply_asset_auto_status` and `freeze_cascade` both make transitions outside the six-move set; scoped every claim to "that explicit endpoint" |
| 13 | Statuses that carry a reliability penalty | `calc.py:reliability_score:285-302` (sort key, cap arithmetic), `calc.recompute_asset:305-311`, `apply_asset_auto_status:320` (<60 → `DOWN_MAINTENANCE`) | Kept the existing ordering/cap prose verbatim and touched only the status set; used "reaches containment" language already in §3.8 so the `CONTAINED → REMEDIATED → CLOSED` tail reads consistently |
| 14 | Payment resource shape and response | `routes/billing.py:397-435`, `core.py:base_row/public`, `core.py:176` (`payments` collection); grepped for any GET on payments — none exists, so no list/read contract is implied | Said "a client that needs the invoice's new `amount_paid_cents` or `status` re-reads the invoice" instead of asserting anything about a payments list endpoint, which impl does not expose |

Orchestrator verification (independent): PRD.md 428 → PRD_FINALIZED.md 434 lines (+6 net, 17 lines added, 11 revised) — a genuinely minimal patch. `diff` of all `^#` headings between the two files is **empty**, confirming identical section structure and that no new sections were introduced, as the method requires. Endpoint and error tables intact.

## Step 9: Complete PRD — 2026-09-01T02:05:00.000Z

Always-runs step. Started from PRD_FINALIZED.md. Step 8's 14 already-patched sites were listed in the prompt so this scan targeted what Step 8's Step-7-bounded scope could not reach.

Subagent summary (verbatim):

Done. `PRD_COMPLETED.md` is complete.

**Counts**

- `PRD_FINALIZED.md`: 434 lines, 113,973 chars → `PRD_COMPLETED.md`: 434 lines, 131,571 chars (**+17,598 chars**, 0 new lines, 0 new sections — every change is an in-paragraph insert or revision).
- 48 changed lines / 48 discrete change sites: **33 ambiguity-pins**, **15 mismatch-revisions**.

**Changes** (`{section} — {kind} — {class} — {what} — {impl}`)

- §2.1 — insert — ambiguity — `AirlineRep` list reads are silently narrowed to owned rows before any filter param — billing.py:278, orders.py:120, commercial.py:112
- §2.3 — insert — ambiguity — `created_at` ties broken by insertion order, never by `id` — core.py:232
- §2.10 b1 — revise — mismatch — ownership also on every single-resource read; deferred past payload on flight/authorization creation — billing.py:291, commercial.py:22
- §2.10 b2 — revise — mismatch — `ERR_CROSS_FARM_REFERENCE` also on pit creation, authorization creation and spill reporting (asset before tank) — assets.py:217, commercial.py:150, spills.py:33
- §2.10 b4 — revise — mismatch — `ERR_INVALID_TANK_STATE` also on posting a reconciliation run — billing.py:185
- §2.10 b5 — revise — mismatch — `ERR_TANK_QUARANTINED` on assignment; `ERR_SPILL_NOT_REPORTABLE` also on contain and close — orders.py:229, spills.py:129/169
- §3.1 permits — revise — mismatch — permit-day counter sources, `≥0` spill threshold, no farm `version` bump on issue, suspend/reinstate error id, §3.8 cross-ref fix — calc.py:185, farms.py:151
- §3.1 assets — insert — ambiguity — whole-number `turnaround_buffer_minutes`, `dp ≥ 0`, auto pass at registration — assets.py:30
- §3.1 pits — insert — ambiguity — no-hydrant farm → `ERR_DELIVERY_MODE_MISMATCH`; cross-farm source tank checked after uniqueness — assets.py:214/217
- §3.1 accounts — insert — ambiguity — `INTO_PLANE_ONLY` base price silently zeroed — commercial.py:53
- §3.1 clock — revise — mismatch — closed effect list, 200 with only `current_utc`/`to_iso8601`, no cascade, no farm version bump — farms.py:38-54
- §3.2 sampling — insert — ambiguity — empty payload, `OUT_OF_SERVICE` tank error, 201 returns the sample — receipts.py
- §3.2 test-results — insert — ambiguity — 200 returns sample; already-`TESTED` → parent-specific error — receipts.py
- §3.2 verdict — insert — ambiguity — comparison density for asset samples from latest order's tank, else skipped — receipts.py
- §3.3 — revise — mismatch — reject `reason` discarded; healing needs the tank's *latest* sample to be a `TESTED` PASSing `PERIODIC_TANK_QA`; no farm version bump — services.py (`latest_periodic_pass`, `maybe_heal_tank`)
- §3.4 service — revise — mismatch — closed 3-move set, no `ERR_ALREADY_TERMINAL` for tanks — tanks.py:137
- §3.4 isolation/retire — insert — ambiguity — both window bounds mandatory with end > start, role + heel checks, pit lock-out version bumps — tanks.py:129-182
- §3.4 quality release — insert — ambiguity — missing governing sample → `ERR_INVALID_TANK_STATE` — tanks.py:230
- §3.4 quarantine/recovery — insert — ambiguity — `reason` unpersisted, mandatory `sample_purpose` stored as supplied, 201 returns sample, cascade order — tanks.py:199-218
- §3.4 gauge — insert — ambiguity — not a resource, ranges, quarantine only from `RELEASED` — tanks.py:266-293
- §3.4 ledger — revise — mismatch — recomputed on every read and touching write; `ISOLATED`-only availability override — calc.py:223
- §3.5 authorization — insert — ambiguity — flight must belong to the account → `ERR_CROSS_FARM_REFERENCE` — commercial.py:150
- §3.5 voids — revise — mismatch — manual void error ids; system voids leave non-`ISSUED` rows untouched and un-bumped — services.py (`void_authorization`)
- §3.5 reservation — insert — ambiguity — month-to-date keyed on the clock's calendar month, tickets at or before the clock — calc.py:415
- §3.6 creation — insert — ambiguity — window error id, only authorization/flight agreement, `hydrant_pit_id` ignored on HYDRANT — orders.py:64-92
- §3.6 assignment — insert — ambiguity — mode/pit error ids, quarantine guard before mode branches — orders.py:229-253
- §3.6 unassign — revise — mismatch — pit `version` rises — services.py (`end_pit_occupancy`)
- §3.6 start — insert — ambiguity — element-life/flight error ids, window checked last — orders.py
- §3.6 uplift — insert — ambiguity — only order `version` rises; `posted_net_liters` from POSTED+BILLED — orders.py
- §3.6 close — revise — mismatch — pit `version` on complete/abort; authorization `version` rises even when already `EXPIRED` — orders.py, services.py:150
- §3.7 auto pass — insert — ambiguity — runs on every recompute, fixed precedence, at most one firing — calc.py:314
- §3.7 explicit status — revise — mismatch — enum check + pass before from-state; automatic moves carry no version accounting; **freeze cascade is the one place the pass is suppressed** — assets.py, services.py:243
- §3.7 filter change — insert — ambiguity — whole `element_count`, `dp ≥ 0` echoed on the record — assets.py
- §3.7 return to service — insert — ambiguity — role check after transition-set check; `ERR_ASSET_NOT_SERVICEABLE` cases — assets.py
- §3.8 report — revise — mismatch — FK/cross-farm attribution resolved before payload validation; farm `version` rises on report — spills.py:20-54
- §3.8 escalate — insert — ambiguity — threshold off the governing permit whatever its status with 20.0 fallback, volume tested before reference, non-string reference → `ERR_INVALID_PAYLOAD`; posture pass re-runs the cascade on any spill action; hop two swept by `created_at` and leaves `REQUESTED`/`ASSIGNED` alone — spills.py:91-104, services.py:229
- §3.8 contain — insert — ambiguity — same 20.0 fallback, `contained ≥ 0` and `≤ spilled` as `ERR_FIELD_OUT_OF_RANGE` ahead of state guards, full §3.7 recompute of the attributed asset — spills.py:113-139
- §3.9 run open/measure — insert — ambiguity — `variance_override_reason` opens null; measurement ranges; whole array validated before state/period/completeness; duplicate tank → `ERR_MEASUREMENT_SET_INCOMPLETE` — billing.py:27-96
- §3.9 measurements — insert — ambiguity — persisted `tank_measurements` entry shape and order — billing.py:102-123
- §3.9 post — insert — ambiguity — `ERR_INVALID_TANK_STATE` position, override must be a string and is persisted even from `MEASURED`, run-level `adjustment_liters` — billing.py:176-196
- §3.9 invoice create — insert — ambiguity — both body FKs resolved first; `replaces_invoice_id` never state- or account-checked — billing.py:218-223
- §3.9 issue — insert — ambiguity — empty sweep → `ERR_NOTHING_TO_SWEEP`; voided ticket → `ERR_INVALID_INVOICE_STATE` — billing.py:309-314
- §3.9 dispute — insert — ambiguity — part-paid → `ERR_INVALID_INVOICE_STATE` — billing.py:341
- §3.9 payment — revise — mismatch — `ISSUED` only, whole-number amount, and a partial payment still bumps invoice + account `version` and lowers exposure by the amount paid — billing.py:405-434
- §3.9 void — insert — ambiguity — part-paid → `ERR_INVALID_INVOICE_STATE` — billing.py:381
- §4 — revise — mismatch — farm tank list filters by `service_status`/`quality_status` — tanks.py:100
- §4 — revise — mismatch — `GET /hydrant-pits` also filters by `status` — assets.py:246
- §4 — revise — mismatch — farm reconciliation-run list filters by `status` — billing.py:53

All 16 implementation files were read (3,694 lines incl. the empty `routes/__init__.py`); the 14 Step-8 sites were left untouched except where a later module revealed an additional, non-overlapping fact in the same paragraph. Only `PRD_COMPLETED.md` was written; `SCAFFOLD*.yaml` and `worklog.md` were not read.

Orchestrator verification (independent): PRD_COMPLETED.md is 434 lines / 131,571 chars vs PRD_FINALIZED.md 434 lines / 113,973 chars — +17,598 chars with **zero** net line change, confirming every edit is an in-paragraph insert or revision. `diff` of all `^#` headings between the two files is **empty**, confirming no new sections. Implementation integrity re-checked: every file under `implementation/` has an mtime at or before 01:06, while the orchestrator's verifying 8-round sweep ran 01:16–01:27, so the green result was produced against exactly the code that ships — Steps 8 and 9 wrote only PRD files and did not perturb the tested implementation. `__pycache__`/`*.pyc` build artifacts removed; the 8 `results.{1..8}.json` evidence files are retained per the pipeline output spec.

## Pipeline complete — 2026-09-01T02:05:00.000Z

All nine steps done. Final deliverable tree matches the pipeline output spec: 3 scaffold YAMLs (6,384 lines), worklog.md, test_helpers/ (9 files) + test_suite/ (conftest + 36 test files) totalling 10,579 lines / 218 tests, and workspace/ with INSTRUCTION.md, the three-generation PRD family (PRD.md 428 → PRD_FINALIZED.md 434 → PRD_COMPLETED.md 434 lines), implementation/ (3,694 lines, 16 files, 75 endpoints) and the 8 passing results files.

Final test status: **218/218 passing in all 8 concurrent rounds**, independently reproduced by the orchestrator.

RESUME-MODE note: this run resumed a crashed pipeline that had completed only Steps 1 and 3. Steps 2, 4, 5, 6, 7, 8, 9 were executed in this session. Four of the seven executed steps required at least one resume-in-place after a harness stall-watchdog kill or a transient API error (Step 2 ×3 launches, Step 5 ×1 resume); in every case on-disk progress was preserved and the agent was resumed from its own transcript rather than restarted, and the incremental-write discipline (modest appends, `wc -l` between them) was what made those interruptions cheap.
