# Worklog — task_2253_commercial_fitness_equipment_manufacturing

## Step 1: Create task directory — 2026-09-01T11:00:49.140Z

Created `tasks/task_2253_commercial_fitness_equipment_manufacturing/` and `tasks/task_2253_commercial_fitness_equipment_manufacturing/workspace/` (directory name pre-allocated by the caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T12:38:48.210Z

All three artifacts are complete and lint-clean. `SCAFFOLD_CORNER_DESIGN.yaml` was the last piece; it is now written (7,373 lines, 81 instances).

Verdict block (verbatim, final run):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2253_commercial_fitness_equipment_manufacturing/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2253_commercial_fitness_equipment_manufacturing/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2253_commercial_fitness_equipment_manufacturing/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    77
  §1.1 entities declared:     14
  §1.8 instances scanned:     24
  §1.9 instances scanned:     70
  Calls scanned (§1.8+§1.9):  2227

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2253_commercial_fitness_equipment_manufacturing/`):
- `SCAFFOLD.yaml` — 2,018 lines, §1.0–§1.7, neither design key present
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 3,137 lines, single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 7,373 lines, single key `scaffold_corner_design`

Seed-table counts (§1.0–§1.7), `difficulty_level: beyond_expert`:
- 14 entities, topology `graph` (self-referential supersession chain, `FirmwareCertification` junction, `SerializedAsset` as a four-way cross-aggregate node)
- 11 state machines, shape `parallel` (Order carries three independent dimensions: config × fulfillment × billing; ModelRevision cyclic rework loop; SerializedAsset branching with a compensating back-edge; InstallJob fork-join punch-list branch)
- 3 concurrency rules (OCC on EquipmentModel, Order, Facility)
- 10 calculations, 3 of them dual-variant (`revision_cycle_qualification` VERIFIED vs PROJECTED, `order_total_assembly` PROVISIONAL vs FINAL, plus ledger/rollup reconciliations)
- 38 validations in a strict priority ladder (auth → role → path 404 → scope → SoD → schema → window → body FK → OCC → state → 27 business rules)
- 77 endpoints, 46 error codes, 6 RBAC roles (2 entity-backed: FacilityManager → Facility, ServicePartnerTech → ServicePartner; role_model `segregation_of_duties`)
- complexity layers: dual_variant_calculation, cascading_side_effects, optimistic_concurrency, derived_field_reconciliation; consistency `immediate`

§1.8 — 24 instances across 9 rule blocks (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).

§1.9 — 81 instances across all 9 sections (70 executable recipes + 11 `excluded_because:` stubs, each pointing at an existing §1.8 instance): entities 12, state_machines 13, calculations 15, validations 18, endpoints 6, errors 5, rbac 4, complexity_layers 7, consistency_model 1.

Extra verification beyond the lint: a placeholder-closure pass (every `${var}` bound by an earlier `captures:` in the same instance, including inside asserts) reports 0 problems; all 105 instance names are unique across both design files; every stub's cited §1.8 instance resolves by name and carries no `test_recipe`; and every monetary/cycle/hour literal in the recipes was pre-computed with exact-Decimal ROUND_HALF_UP scripts (e.g. 560310 / 1120619 / 1685699 quotes, 573622 FINAL, 263973 and 224377 trade-in valuations, 6.25 / 12.50 / 15.36 PM hours, 500000 verified vs 580000 projected cycles).

## Step 3: Copy shared files — 2026-09-01T12:38:48.210Z

Copied `INSTRUCTION.md` to `tasks/task_2253_commercial_fitness_equipment_manufacturing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T12:53:56.393Z

PRD generated and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2253_commercial_fitness_equipment_manufacturing/workspace/PRD.md` — 493 lines.

**Sections**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications & System-Wide Principles — 12 subsections: 2.1 Actors/Headers/Role Scope, 2.2 API Response Structure (pasted verbatim, byte-for-byte match confirmed), 2.3 Pagination & List Ordering, 2.4 The Logical Clock, 2.5 Common Resource Properties, 2.6 Precision (cents/hours/cycles/days), 2.7 Version Pinning on Superseding Writes, 2.8 The Validation Ladder, 2.9 Path Resolution & Referential Integrity, 2.10 Cascade Discipline & Derived-Field Reconciliation, 2.11 Conserved Ledgers, 2.12 Two Interval Geometries
- §3 Business Logic & Workflows — 9 domain-grouped subsections (catalogue/supersession/revisions; durability rigs & cycle evidence; firmware builds & connectivity certification; release/sunset/obsolescence; facilities/orders/lines; quoting/confirmation/credit gate; production/serialization/install; service network & PM; trade-in/refurb/resale)
- §4 Endpoint Definitions — 77 rows, exactly 4 columns
- §5 Error Code Catalogue — 46 rows, exactly 2 columns; document ends here, no audit footer

**Coverage audit vs. scaffold** (verified mechanically with PyYAML against SCAFFOLD.yaml): 14 entities, 11 state machines / 52 transitions, 3 concurrency rules, 10 calculations, 38 validations, 77 endpoints (method+path+roles all exact matches), 46 errors (all HTTP statuses exact), 6 roles, 4 domain constants — all present. All 46 error IDs also appear in §1–§3 prose, not only in the §5 table. All state names from all 11 machines appear in prose. The 38-rung ladder in §2.8 reproduces every scaffold `applies_to` scope verbatim in role/action-verb form.

```
Field coverage check:
- entities[].fields: 122 required, 122 present, 0 missing
- endpoints[].request_body: 75 required, 75 present, 0 missing
- endpoints[].query_params: 22 required, 22 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 38 checked, 38 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 52 checked, 52 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed, 0 missing
- validations[] conditions: 38 checked, 38 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 77 checked, 77 expressed, 0 missing
- entities[].fields[] structured content: 122 checked, 122 reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 groups checked, 9 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 974
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Key findings worth flagging: (1) the two opposed interval geometries are kept in separate §3 subsections with an explicit "do not share one overlap helper" note in §2.12 — rigs are closed/inclusive aggregate-capacity, install crews are half-open with a 120-minute travel buffer; (2) the scaffold's validation-1 text says `X-Role` while the skill mandates named headers, so the PRD standardises on `X-User-Role` and `X-User-ID` throughout; (3) two places needed disambiguation the scaffold left open and are now stated determinately in prose — the "order's outstanding total" bound on trade-in credit application, and the error surfaced (`ERR_INSUFFICIENT_PART_STOCK`) when a held visit cannot re-reserve its units during program revision.

## Step 5: Generate unit tests — 2026-09-01T14:33:25.537Z

Both remaining files are written and the whole suite passes its final audits.

## Files written (this session)

- `/home/ubuntu/github/CodingPRD/tasks/task_2253_commercial_fitness_equipment_manufacturing/test_suite/test_13_access_control.py` — 7 tests
- `/home/ubuntu/github/CodingPRD/tasks/task_2253_commercial_fitness_equipment_manufacturing/test_suite/test_14_errors_and_referential_integrity.py` — 7 tests
- Two citation repairs in earlier files (see "Audit findings"): `test_suite/test_02_revision_lifecycle_and_rework.py`, `test_suite/test_05_order_configuration_and_lines.py`
- Dead-import cleanup in `test_helpers/fixtures.py`

## Complete deliverable

`test_helpers/` (9 files: `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`) plus `test_suite/conftest.py` and 14 test files, **123 tests**:

| file | tests |
| --- | --- |
| test_01_catalogue_and_models.py | 7 |
| test_02_revision_lifecycle_and_rework.py | 14 |
| test_03_durability_testing.py | 11 |
| test_04_firmware_certification.py | 8 |
| test_05_order_configuration_and_lines.py | 10 |
| test_06_order_pricing.py | 13 |
| test_07_confirmation_and_credit.py | 5 |
| test_08_production_and_serialization.py | 5 |
| test_09_install_scheduling.py | 7 |
| test_10_install_completion_cascade.py | 6 |
| test_11_service_network_and_maintenance.py | 14 |
| test_12_tradein_and_secondary_market.py | 9 |
| test_13_access_control.py | 7 |
| test_14_errors_and_referential_integrity.py | 7 |

## Coverage audit

- **Queue A (difficulty §1.8): 24/24 instances translated, 0 skipped**, every one with ≥2 tests (no instance has only one).
- **Queue B (corner §1.9): 70/70 non-stub instances translated, 0 skipped**, ≥1 test each.
- **11 `excluded_because:` stubs correctly not translated** (each defers to a named §1.8 instance): `state_machines/usage_report_resyncs_the_pm_program_hours_ledger`, `state_machines/firmware_withdrawal_cascades_across_entity_families`, `calculations/order_line_rounding_happens_per_line_before_the_subtotal`, `calculations/provisional_to_final_delta_reconciles_on_the_billing_switch`, `calculations/tradein_credit_ledger_stays_conserved_under_grant_and_spend`, `calculations/spare_stock_ledger_stays_conserved_across_reserve_and_consume`, `validations/facility_suspension_outranks_the_credit_limit_check`, `validations/revision_release_gate_outranks_the_finish_code_check`, `validations/install_blackout_outranks_the_partner_window_conflict_check`, `complexity_layers/both_price_variants_produce_their_declared_totals_and_delta`, `complexity_layers/a_deep_cascade_is_ordering_sensitive_across_entity_families`.
- **Tags:** 123 tests / 123 `Design:` lines — exactly one per test, always the docstring's last line, zero dual-tagged, zero unknown tags (all resolve to a real `rule_id`/`section` + `name` pair).
- **No skip / xfail / "scaffold" mention anywhere**; no `sys.path` manipulation; every file ≥5 tests.
- **PRD-citation pass:** every quoted span (≥10 chars) in every docstring across all 14 files verified as literal PRD text (whitespace-normalised containment, equivalent to a literal grep). Three non-literal spans were found in previously written files and fixed: `test_02` quoted an invented `"starts at status DRAFT"` (replaced with the PRD's `"A program is created in \`status\` \`DRAFT\` with \`covered_asset_count\` 0"`), and `test_05` quoted two invented ladder-rung labels (`"Referenced entities are in the states…"`, `"Cross-field and cross-entity compatibility holds"`) — replaced with the PRD's actual rung 13 and rung 21 sentences. The tags and assertions were untouched.
- **pyflakes:** all `test_suite/*.py` and `test_helpers/*.py` clean (only the intentional `# noqa: F401` barrel re-exports in `test_helpers/__init__.py` remain, by design).

## What test_13 / test_14 cover

test_13 (queue B only): FacilityManager facility-scope and ServicePartnerTech partner-scope (403 scope codes, then the identical own-resource call succeeding), authentication ranked ahead of role/path/schema (missing, empty and unknown-role headers all 401 even when the path and body are also bad), each of the six roles performing its exclusive operation on one estate, eight wrong-role probes all `ERR_ROLE_NOT_PERMITTED`, the four shared operations accepting either role, and segregation of duties on certification sign-off (co-01 blocked on both certify and reject, co-02 succeeding and stamped).

test_14 (queue B only): all ten 404 codes reachable across fourteen probes with the four shared families collapsing correctly, the order/order-line shared code, missing required body fields on three creates, enum + numeric-bound violations (including `quantity` 501 masking a disallowed finish), body foreign keys resolved ahead of version pinning, strict window ordering on all three creation endpoints, and the three over-determined requests proving role→path, schema→body-FK and window→body-FK ordering.

## Step 6: Generate implementation — 2026-09-01T14:33:25.537Z

Implementation complete for task 2253 (Commercial Fitness Equipment Manufacturing).

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2253_commercial_fitness_equipment_manufacturing/workspace/implementation/`, 4,334 lines total):

| File | Lines |
|---|---|
| `calc.py` | 808 |
| `routes/orders.py` | 449 |
| `routes/catalogue.py` | 423 |
| `routes/maintenance.py` | 422 |
| `routes/assets.py` | 309 |
| `routes/testing.py` | 258 |
| `routes/installs.py` | 286 |
| `routes/firmware.py` | 215 |
| `validation.py` | 204 |
| `store.py` | 184 |
| `auth.py` | 177 |
| `constants.py` | 155 |
| `app.py` | 94 |
| `routes/partners.py` | 91 |
| `routes/facilities.py` | 82 |
| `envelope.py` | 75 |
| `errors.py` | 73 |
| `routes/clock.py` | 20 |
| `start.sh` | 8 (executable) |
| `requirements.txt` | 1 |
| `routes/__init__.py` | 0 |

**Endpoints: 77**, matching the PRD §4 table exactly (verified by enumerating `app.url_map`). 14 entities, 46 error codes, 11 state machines, 10 calculations, 38-rung global validation ladder ordered by SCAFFOLD `priority` ascending.

**Storage**: in-memory dicts only (`store.COLLECTIONS`), verified empty on boot; no SQLite, no JSON file dumps, no seeding or hardcoded entities. Per-request `deepcopy` snapshot with rollback on any error handler gives cascade atomicity (§2.10). Logical clock starts at `2026-08-01T00:00:00Z` and only `POST /_clock/set_current_utc` advances it.

**Boot verification**: `PORT=18255 bash start.sh` came up cleanly from a fresh process; `POST /_clock/set_current_utc` → 200, `GET /equipment-models` → 200 with a correct empty-array envelope (`req_` id, `limit/offset/total_count/has_more`); server then killed. Suitable for `--isolation per-test-server` (no reloader, single-threaded, no state outside the process).

**Two end-to-end smoke suites passed** (both exit 0, temp scripts removed):
- Happy path + invariants: OCC 412s on all three `expected_*_version` writes, SoD 403, duplicate-code 409s, closed/inclusive rig geometry rejecting touching windows, blackout weekday 422, one-open-install-job 409, punch-list fork with deferred completion cascade, deterministic serials `TRX-9A-00001..4`, provisional quote 4,079,620 cents → final 4,007,433 with 50,000 punch-list credit, warranty 2026-08-03 → 2029-08-02 (1095 days), PM hours 35.00 → 43.75 after a 5,000 h usage report, trade-in valuation 286,875, sunset cascade to `NEEDS_REVISION`/`CONSOLE_SUPPORT_LOST`, revise/terminate releasing committed hours to 0.
- Edge/negative path: test-failure → rework → re-test → qualify → release loop (`projected_cycle_count` halving on failure, `verified_cycle_count` reset on rework), finish-code 422, quote invalidation on line add and re-quote after void, credit-limit 402, facility-suspension 409s, half-open install geometry accepting a window that starts exactly at the previous job's 120-minute effective end while rejecting one minute earlier, partner capacity 409, partner-scope 403 on a list filter, insufficient-stock and asset-not-covered rungs, all 404 families, 401/403/405 envelopes. No 500s anywhere.

One interpretation worth flagging: on `POST /serialized-assets/{id}/load-firmware` the ladder puts rung 14 (`ERR_FIRMWARE_NOT_CERTIFIED`) before rung 22 (`ERR_PLATFORM_INCOMPATIBLE`), so the certification check is applied only when the model is connected — a non-connected model still surfaces `ERR_PLATFORM_INCOMPATIBLE`. Also, resale deliberately does not recompute facility trade-in ledgers, which keeps the trade-in → apply-credit → refurb → resell flow from raising a spurious `ERR_TRADEIN_CREDIT_ALREADY_APPLIED` while preserving the §2.11 conservation invariant.

## Step 7: Run tests and iterate — 2026-09-01T14:56:30.000Z

Storage is in-memory only (the one hit is `json.dumps` for response serialization). Final state: **all 8 parallel rounds pass, 123/123.**

## Summary

**Iterations run:** 2 sweeps (initial diagnostic sweep + verification sweep). The second sweep was clean across all 8 concurrent rounds.

Initial sweep: 100–102 / 129 per round, 29 tests in the union failure set, resolving to 5 root causes.

**Tests deleted:** none. One *assertion* was removed under STEP 1c (partial coverage), not a whole test:
- `test_04_firmware_certification.py::test_duplicate_certification_blocks_submitted_and_certified_but_not_rejected` — dropped `assert rejected["rejection_note"] == ...`. **Response-field silence:** PRD §3.3 names `rejection_note` only as a request input and states rejection "has no side effect beyond the status change", so a faithful reader would not persist or serialize it. The test's own docstring quotes that sentence. The duplicate-guard assertions it exists for are untouched.

**Fixes applied to `test_helpers/`:**
- `factories.py` — renamed `test_rig_payload` → `rig_payload` and `test_run_payload` → `run_payload`. Both are payload factories, but the `test_` prefix made pytest collect them as tests in every module that imported them; `run_payload` takes required args, so it errored as `fixture 'model_revision_id' not found` in 3 files. (This is why `total` legitimately drops 129 → 123: 6 mis-collected factory functions are no longer counted as tests.)
- `fixtures.py` — updated the two call sites for the rename.
- `assertions.py` — added `assert_instant(actual, expected, label)`: compares a stamped instant as an instant rather than as a string. PRD §2.2/§2.5 pin "three fractional digits" only for `api_request_timestamp`, `created_at` and `updated_at`; §2.4 says every other persisted instant is merely "stamped from the logical clock, in UTC", so the fractional-digit rendering of `qualified_at`, `warranty_expires_at`, `firmware_support_until` etc. is not uniquely derivable. 19 tests were asserting `"…T00:00:00Z"` against the implementation's `"…T00:00:00.000Z"`. The instant asserted (i.e. the PRD's 1095-day / 1825-day arithmetic) is preserved exactly.
- `assertions.py` — added `expected_listing_order(rows)`: returns ids sorted by `(created_at, id)`, i.e. PRD §2.3 verbatim. Needed because the §2.4 clock "never advances on its own", so rows created inside one test share `created_at` and the `id` tie-break — not insertion order — decides.

**Fixes applied to `test_suite/` (test-vs-PRD consistency, STEP 2):**
- 40 stamped-instant string comparisons across test_02/04/05/08/10/12/13 converted to `assert_instant(...)`, with the import added.
- `test_01::test_equipment_model_listing_pages_in_creation_order` — paging assertions now expect `expected_listing_order([first, second, third])` instead of literal creation order. The test cited the `created_at`/`id` rule in its docstring but asserted insertion order; it failed 7/8 rounds purely on UUID luck.
- `test_01::test_revision_create_rejects_a_stale_equipment_model_version` — trailing listing assertion now checks the PRD order by id plus the set of `revision_code`s (was asserting `["T900-R1","T900-R2"]` insertion order; failed 4/8).
- `test_03::test_chronological_walk_orders_by_window_end_not_by_creation` — listing assertion now uses `expected_listing_order`, and the "walk order ≠ creation order" point is now made directly by asserting `early["window_end"] < failure["window_end"]` (failed 6/8).

**Fixes applied to `implementation/`:**
- `calc.py::order_lines()` — sort changed from `(created_at, id)` to a stable sort on `created_at` alone. PRD §3.7 says "lines are processed by their `created_at` ascending" without naming a tie-break, and PRD §2.3 states the consequence explicitly: "the units minted from an order's first line appear before the units minted from its second." With the frozen clock, the `id` tie-break randomized which line got `sequence_no` 1, breaking that stated guarantee (`test_08::test_serial_numbers_and_sequence_numbers_are_minted_in_line_order` failed 4/8). The list endpoint `/order-lines` uses a separate paginator and still applies the §2.3 `id` tie-break.

No assertion was downgraded to an HTTP-status check, no skip/xfail added, no PRD-required implementation check removed, and no endpoint, field, or seeded data added.

**Orchestrator verification note:** the fix subagent exited without leaving its `results.*.json` files on disk, so the orchestrator re-ran the full 8-round parallel sweep independently. Result: rounds 1–8 all `passed=123 total=123 failed=0 errors=0`; the eight files are in `workspace/implementation/results.{1..8}.json`.

## Step 8: Finalize PRD — 2026-09-01T15:01:51.978Z

Done. `PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_2253_commercial_fitness_equipment_manufacturing/workspace/PRD_FINALIZED.md`.

## Size delta

| | PRD.md | PRD_FINALIZED.md | delta |
|---|---|---|---|
| lines | 492 | 492 | 0 (+0.0%) — the PRD is one paragraph per line; all three edits are inline |
| words | 14,062 | 14,235 | +173 (+1.23%) |
| bytes | 105,279 | 106,413 | +1,134 (+1.08%) |

## Changes (3)

- **§2.4 (The Logical Clock)** — *insert* — pinned the rendering of every server-stamped instant to the same form as `created_at` (UTC, `Z`, exactly three fractional digits, e.g. `2026-08-01T00:00:00.000Z`), extended it to the clock endpoint's `current_utc`, and stated the complement: client-supplied instants are stored/echoed verbatim and never re-rendered — `implementation/store.py:49` (`fmt_iso`), `store.py:91`, `implementation/routes/clock.py:20`, `implementation/validation.py:131`.
- **§3.2 (Durability Testing)** — *revise* — the chronological cycle-evidence walk compares `window_end` as instants and adds the row `id` as a final tie-break after `created_at` — `implementation/calc.py:200`.
- **§3.7 (Production/Serialization)** — *revise* — lines sharing a `created_at` are processed for minting in the order they were added (not by `id`), preserving the §2.3 first-line-before-second-line guarantee — `implementation/calc.py:99-111`, consumed at `implementation/routes/orders.py:346`.

## Items in `<step_7_diff>` that needed **no** PRD edit

- `rejection_note` assertion drop — verified `routes/firmware.py:199-215`: the impl validates `rejection_note` as a required input and does **not** persist or serialize it. PRD §3.3's "no side effect beyond the status change" already matches; the deleted assertion was a test bug.
- `factories.py` / `fixtures.py` `test_`-prefix rename — pure pytest-collection fixture bug, no behavioral surface.
- `expected_listing_order` + the `test_01`/`test_03` listing-order rewrites — PRD §2.3 already pins `(created_at, id)`, and `validation.py:198-204` implements exactly that, with `routes/assets.py:81-83` implementing the documented `(created_at, sequence_no)` exception. Tests were asserting insertion order; PRD was already right.

## Per-edit pre-edit search log

**Edit 1 — §2.4 instant rendering**
- (a) Subject: how instants are rendered in persisted fields and responses.
- (b) Paths enumerated: `store.py:49 fmt_iso`, `store.py:57 wall_now_iso` (→ `envelope.py:22 api_request_timestamp`), `store.py:91 now_iso`, `store.py:125-129 new_entity`, `store.py:136-160 mutate/bump` (`created_at`/`updated_at`); every `store.now_iso()` callsite — `routes/catalogue.py:317,347,378` (`qualified_at`, `released_at`, `sunset_announced_at`), `routes/firmware.py:80,194` (`withdrawn_at`, `certified_at`), `routes/maintenance.py:235` (`last_revised_at`), `calc.py:372` (`quoted_at`), `calc.py:733` (`completed_at`), `calc.py:748` (`warranty_starts_at`); derived horizons `calc.py:70-71 plus_days` → `calc.py:285-286 sunset_horizon` (`firmware_support_until`) and `calc.py:624` (`warranty_expires_at`); `calc.py:634,640` (`firmware_support_expires_at` copied from already-rendered strings); `routes/clock.py:20` (`current_utc`). Counter-paths: all 8 `field_datetime` callsites (`routes/orders.py:66-67`, `routes/testing.py:77-78`, `routes/installs.py:62-63`, `routes/partners.py:39`, `routes/maintenance.py:290`, `routes/clock.py:18`) plus `validation.py:131-141`, confirming client strings are echoed verbatim.
- (c) Adjustment: the first draft asserted three fractional digits for "all instants". Since `window_start`/`window_end`/`requested_install_window_*`/`training_current_until`/`scheduled_date` are stored byte-for-byte, I re-scoped the claim to *server-stamped* instants and added an explicit carve-out sentence naming the six client-supplied fields, so a fresh implementer does not normalize them.

**Edit 2 — §3.2 chronological walk order**
- (a) Subject: the ordering of the cycle-evidence input set.
- (b) Paths enumerated: `calc.py:194-201 cycle_input_runs` (sole sorter), consumers `calc.py:204-230 cycle_counts`, `calc.py:233-238 recompute_revision_cycles`, and the qualification-report route (`routes/catalogue.py`, via `cycle_counts`); confirmed the `/test-runs` list endpoint uses the separate `paginate` default (`routes/testing.py:158` → `validation.py:200`) and is therefore governed by §2.3, not by this sentence.
- (c) Adjustment: kept the clause inside §3.2's "walk that set" sentence rather than generalising it to run ordering anywhere, so it cannot be read as overriding §2.3 for the `/test-runs` listing.

**Edit 3 — §3.7 line processing order for minting**
- (a) Subject: the order in which an order's lines are consumed.
- (b) Paths enumerated: `calc.py:99-111 order_lines` and every caller — `calc.py:305-317 recompute_order_configuration` (sum, order-insensitive), `calc.py:354-359 provisional_install_hours` (sum), `calc.py:429-433 order_categories` (set), `calc.py:436-437 has_active_line` (bool), `calc.py:718-722 order_assets` (feeds the order-insensitive per-asset loop in `calc.py:743-749`), and the one order-sensitive caller `routes/orders.py:346-379 complete_production` with `calc.py:702-707 next_sequence_no`; plus the parallel `/order-lines` list endpoint (`routes/orders.py:213`) which keeps the §2.3 `(created_at, id)` tie-break.
- (c) Adjustment: added the explicit "rather than by `id`" contrast and tied it to the §2.3 guarantee, while keeping the sentence confined to minting so it does not contradict the `/order-lines` listing rule that still applies the `id` tie-break.

## Step 9: Complete PRD — 2026-09-01T15:21:08.664Z

Done. `PRD_COMPLETED.md` is in place at `/home/ubuntu/github/CodingPRD/tasks/task_2253_commercial_fitness_equipment_manufacturing/workspace/PRD_COMPLETED.md`.

## Size

| | PRD_FINALIZED.md | PRD_COMPLETED.md | delta |
|---|---|---|---|
| lines (`wc -l`) | 492 | 495 | +3 |
| bytes (`wc -c`) | 106,413 | 121,794 | **+15,381** (+15,279 chars) |

42 diff hunks, all in-paragraph revisions except three inserts (one new paragraph in §2.1, one bullet in §2.2). No new sections; §4's 77 endpoint rows and §5's error table are structurally untouched (one §4 description word-change).

## Counts
- **ambiguity-pins: 29**
- **mismatch-revisions: 13**

## Changes

- §2.1 — revise — mismatch — `X-Role` accepted as an alias for `X-User-Role` when the latter is absent; whitespace-only headers rejected — `auth.py:12-40`
- §2.1 — insert — ambiguity — full reach of the two ownership checks: which row each endpoint reads, asset scope = partners of `ACTIVE`/`NEEDS_REVISION` programs at the asset's facility (any match passes), `GET /service-partners/{id}` unscoped, body-`facility_id` checks run before schema, and **lists are never implicitly narrowed** — only a supplied `facility_id`/`service_partner_id` filter is compared — `auth.py:50-140`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from A–Z0–9 — `envelope.py:15`
- §2.2 — revise — ambiguity — `api_request_timestamp` comes from the host wall clock, not the logical clock — `envelope.py:19-25`
- §2.2 — revise — ambiguity — pagination `meta` keys appear on list responses *only* — `envelope.py:19-60`
- §2.2 — insert — ambiguity — off-catalogue fallbacks: `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INVALID_REQUEST` 400, `ERR_INTERNAL` 500; trailing slash is not a route mismatch — `app.py:30,65-84`
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` literals are 400; unrecognised query params are ignored — `validation.py:156-196`
- §2.4 — revise — ambiguity — clock response is a one-field `data` object; `to_iso8601` mandatory and parseable; clock may be wound backwards — `routes/clock.py:14-21`
- §2.5 — revise — **mismatch** — a write/recompute that changes nothing does **not** bump `version`/`updated_at`; a row advances by at most one per request; the three pinned parents are the sole always-bump exception — `store.py:137-175`
- §2.7 — revise — ambiguity — `expected_…_version` must be a non-negative JSON integer, so a negative/non-integer pin is 400 and never 412 — `routes/orders.py:254,398`, `routes/catalogue.py:163`
- §2.8 rung 5 — revise — ambiguity — visit-creation partner scope is resolved through the body's `pm_program_id` at this rung; unresolvable ⇒ rung passes — `routes/maintenance.py:281-289`
- §2.8 rung 7 — revise — ambiguity — `expected_…_version` bound; unparseable/non-object body is 400; absent-or-empty body = `{}`; explicit `null` counts as absent — `validation.py:17-45`
- §2.8 rung 11 — revise — ambiguity — the gate generalises to every §3 state change and to the auxiliary preconditions on *related* rows, all reporting `ERR_INVALID_STATE_TRANSITION` — `routes/*.py`
- §2.10 — revise — **mismatch** — only rows a cascade actually *changes* are bumped; visited-but-unchanged rows keep their version — `store.py:137-160`
- §2.11 — revise — ambiguity — a negative trade-in balance refuses with `ERR_TRADEIN_CREDIT_ALREADY_APPLIED` (409) and rolls back — `calc.py:451-487`
- §2.11 — revise — ambiguity — a negative on-hand refuses with `ERR_INSUFFICIENT_PART_STOCK` (409); receipt is `ServiceOpsAdmin`-only, `units` ≥ 1, returns the partner — `calc.py:489-540`, `routes/partners.py:81-91`
- §3.1 — revise — **mismatch** — the all-`SUPERSEDED` case is tested **first**, ahead of `PRE_RELEASE`; "no revisions at all" stays `PRE_RELEASE` — `calc.py:158-178`
- §3.1 — revise — ambiguity — `firmware_baseline_version` is a ≥1-char optional string, stored as supplied and never policed against connectivity — `routes/catalogue.py:155-170`
- §3.2 — revise — ambiguity — the PASSED/FAILED body fork is checked before the run's state; PASSED nulls `failure_cycle_count`, FAILED leaves `achieved_cycles` at 0 and ignores any supplied value — `routes/testing.py:194-235`
- §3.3 — revise — **mismatch** — firmware-withdrawal program flagging is read at facility level and only from `IN_SERVICE` assets; a non-in-service asset's window is rewritten without flagging anything — `calc.py:781-812`
- §3.4 — revise — **mismatch** — only `RELEASED` predecessor revisions are swept, and the predecessor model's `lifecycle_status` is **re-derived by the §3.1 rules**, not forced to `SUNSET` — `routes/catalogue.py:324-360`, `calc.py:158`
- §3.4 — revise — **mismatch** — sunset flags `ACTIVE` programs at the *facility* holding an affected asset, recomputes their rollups, and reconciles affected partners last — `calc.py:761-780`
- §3.5 — revise — ambiguity — a new order's eight pricing fields start at 0, `price_variant_applied` `NONE`, `final_total_cents`/`amount_due_cents`/`quoted_at` null; body-`facility_id` scope precedes schema and 404 — `routes/orders.py:57-110`
- §3.5 — revise — ambiguity — the `finish_codes` **key** is required though the list may be empty; void takes no body; both line ops answer with the line row — `routes/orders.py:144-245`
- §3.6 — revise — ambiguity — a `CONFIRMED` order or one past `QUOTED` is refused `ERR_INVALID_STATE_TRANSITION`; the re-quote branch skips the has-lines check; exactly one version bump; response is the order — `routes/orders.py:251-300`
- §3.6 — revise — **mismatch** — the breakdown returns those thirteen fields in a non-order `data` object, reading the **stored** figures and deriving only `discount_base_cents` and `discounted_base_cents` — `calc.py:409-450`
- §3.7 — revise — ambiguity — production-complete: sole precondition `IN_PRODUCTION`, no body, answers with the order; `sequence_no` = highest existing for the revision + 1 (first unit is 1); all remaining minted-asset fields start 0/null — `routes/orders.py:331-375`, `calc.py:702-707`
- §3.7 — revise — **mismatch** — firmware load evaluates the certification gate **first and only for connected models**; a non-connected model skips it and fails `ERR_PLATFORM_INCOMPATIBLE`; answers with the asset — `routes/assets.py:100-134`
- §3.7 — revise — ambiguity — a null `warranty_expires_at` against a non-null horizon yields `SUNSET_TRACKED` (gap 0) — `calc.py:617-655`
- §3.7 — revise — **mismatch** (+ambiguity pin) — completion requires a **required** integer `punch_list_open_count` ≥ 0; the cascade prices/invoices **only while `billing_status` is `QUOTED`**, moves only assets *still* `BUILT`, and reconciles the installing partner *plus* every partner of a recomputed program — `routes/installs.py:224-241`, `calc.py:728-760`
- §3.7 — revise — **mismatch** — abort's `ON_SITE` branch reverts the order only if it is still `INSTALLING` — `routes/installs.py:280-284`
- §3.8 — revise — ambiguity — parts receipt: `units` a required integer ≥ 1, returns the partner row — `routes/partners.py:81-91`
- §3.8 — revise — **mismatch** — revision gates read the partner's **stored** `committed_hours` (so a same-partner revision counts its own existing hours alongside the recomputed ones), omitted fields keep current values, held visits re-reserve **cumulatively** against a running remainder, and both old and new partner are reconciled — `routes/maintenance.py:173-243`
- §3.8 — revise — ambiguity — terminating a `DRAFT` program recomputes nothing at all, not even the partner — `routes/maintenance.py:246-270`
- §3.8 — revise — ambiguity — `scheduled_date` is required and stored/echoed verbatim, never compared to the clock — `routes/maintenance.py:288-293`, `validation.py:131`
- §3.8 — revise — ambiguity — visit completion reconciles the whole partner row (hours and coverage alongside the ledger) then the asset's history; response is the visit — `routes/maintenance.py:369-400`
- §3.8 — revise — ambiguity — usage report takes `annual_usage_hours` ≥ 0, recomputes only `ACTIVE` programs (not `NEEDS_REVISION`) and their partners, writes regardless of asset status, returns the asset — `routes/assets.py:137-149`, `calc.py:581-588`
- §3.9 — revise — ambiguity — age is floor-to-whole-days then floor-divide by 365; a null `warranty_starts_at` gives age 0 — `calc.py:676-690`
- §3.9 — revise — ambiguity — only `SCHEDULED` visits of that asset cancel; the reconciled partner set is the union of those visits' programs' partners (any status) and the facility's `ACTIVE` programs' partners; returns the asset — `routes/assets.py:150-187`
- §3.9 — revise — ambiguity — reversal never revives the cancelled visits and leaves `refurb_grade`, warranty fields and support window untouched — `routes/assets.py:190-221`
- §3.9 — revise — **mismatch** — apply-credit recomputes `amount_due_cents` **only when `final_total_cents` is non-null**, bumps the facility `version` by exactly one, and answers with the order — `routes/orders.py:391-431`
- §3.9 — revise — ambiguity — resale also rewrites `firmware_support_expires_at`/`support_gap_days`; no ledger and no program rollup at either facility is recomputed — `routes/assets.py:263-291`
- §4 — revise — ambiguity — `GET /serialized-assets` also filters on `connectivity_support_status` — `routes/assets.py:48-66`

## Verification sweeps run
- All 77 impl routes ↔ 77 §4 table rows: exact match on method, path **and** authorised-role set (zero discrepancies).
- Every list endpoint's query filters ↔ table descriptions: one gap, fixed above; the four resources with no collection endpoint (`facilities`, `service-partners`, `test-rigs`, `firmware-releases`) correctly have none in the table.
- Every numeric/length bound in `routes/*.py` traced to PRD prose: all now stated.
- Every field name appearing in the implementation occurs in the PRD text.
