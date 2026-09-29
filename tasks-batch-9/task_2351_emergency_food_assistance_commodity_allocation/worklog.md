# Worklog — task_2351_emergency_food_assistance_commodity_allocation

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `tasks/task_2351_emergency_food_assistance_commodity_allocation/` and `workspace/` (directory name pre-allocated by the invoker; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T05:09:39.399Z

Done. All three scaffold files for task 2351 are complete and lint-clean.

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.

Coverage
  §1.5 endpoints declared:    73
  §1.1 entities declared:     14
  §1.8 instances scanned:     19
  §1.9 instances scanned:     46      (59 authored − 13 excluded_because stubs, which carry no calls)
  Calls scanned (§1.8+§1.9):  987
```

Files (all absolute):
- `/home/ubuntu/github/CodingPRD/tasks/task_2351_emergency_food_assistance_commodity_allocation/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_2351_emergency_food_assistance_commodity_allocation/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_2351_emergency_food_assistance_commodity_allocation/SCAFFOLD_CORNER_DESIGN.yaml`

SCAFFOLD.yaml (§1.0–§1.7), `api_prefix: /efap`
- 14 entities: ServiceArea, Agency, Commodity, Warehouse, InventoryLot, AllocationCycle, AgencyAllocation, CommodityOrder, OrderLine, DeliveryAppointment, InventoryTransfer, Recall, RecallAction, HouseholdDistribution.
- 9 state machines (10 §1.2 entries — Agency runs two independent axes: agreement PENDING→ACTIVE→EXPIRED→TERMINATED and training REQUIRED→CURRENT→LAPSED), plus 2 OCC concurrency rules (`expected_agency_allocation_version`, `expected_inventory_lot_version`).
- 10 calculations, 35 priority-ordered validations, 73 endpoints, 53 error codes, 4 roles (StateAdmin, ComplianceReviewer opaque; AgencyCoordinator = entity_backed:Agency, StateWarehouseOperator = entity_backed:Warehouse) with a segregation-of-duties pair (recall initiator cannot close; returning reviewer cannot approve).
- complexity_profile: flat topology, parallel state-machine shape, segregation_of_duties role model, immediate consistency, layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, ops_run_checkpoint, derived_field_reconciliation, conditional_feature_flags. Only `GET /efap/_clock/current` is auth-exempt.

§1.8 SCAFFOLD_DIFFICULTY_DESIGN.yaml — 19 instances across all 9 difficulty patterns (2 dual-variant, 2 combinatorial formula, 2 non-linear state machine, 2 transitive cascade, 2 validation-priority conflict, 3 boundary/precision, 2 cross-entity state dependency, 2 resource/temporal overlap, 2 compensating invariant).

§1.9 SCAFFOLD_CORNER_DESIGN.yaml — 59 instances over the nine claim-extraction sections: entities 12, state_machines 16, calculations 8, validations 5, endpoints 4, errors 5, rbac 3, cross-cutting complexity layers 5, consistency model 1. 46 carry full `test_recipe`s; 13 are `excluded_because` stubs, each citing an existing §1.8 instance by exact name. Names are unique across the §1.8 ∪ §1.9 union, and neither design key appears inside SCAFFOLD.yaml.

Constraint honored: nothing outside task_2351's own directory and the scaffold-generator skill was read — no sibling task was listed, grepped, or opened.

## Step 3: Copy shared files — 2026-09-02T05:09:39.399Z

Copied `INSTRUCTION.md` → `tasks/task_2351_emergency_food_assistance_commodity_allocation/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T05:27:21.876Z

PRD generated and all three Hard Contracts pass.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2351_emergency_food_assistance_commodity_allocation/workspace/PRD.md` — 557 lines, ends at §5 with no audit footer.

**Structure** (25 headings, skeleton designed from the domain rather than copied from the example):
- §1 Introduction (2 paragraphs, business-context angle)
- §2 (11 subsections): 2.1 Role-Based Access Control · 2.2 API Response Structure (verbatim block, byte-identical to `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 The Logical Program Clock · 2.5 Resource Identity, Timestamps and Versioning · 2.6 Identifier Resolution Order · 2.7 Numeric Precision and Remainder Reconciliation · 2.8 Stale-Version Guards · 2.9 The Conserved Case Ledger · 2.10 Validation Precedence (all 35 priorities, plus 3 worked conflicts) · 2.11 Cascade Discipline and Derived-Field Reconciliation
- §3 (9 subsections): program configuration → agency eligibility (two axes) → entitlement receipts/monitoring/transfers → allocation cycle formula → agency ordering → compliance review, conversion and FEFO → dock scheduling and delivery → recall execution → household distribution and cycle reconciliation
- §4: 73-row, 4-column endpoint table · §5: 53-row, 2-column error table

**Contract reports**

```
Field coverage check:
- entities[].fields: 134 required, 134 present, 0 missing
- endpoints[].input (request bodies + query params): 75 required, 75 present, 0 missing
- endpoints[].output identifiers: 22 required, 22 present, 0 missing
- path params: 14 required, 14 present, 0 missing
Status: PASS
```
(three passes; pass 1 flagged nothing on entity fields, pass 2 re-ran per-category, pass 3 after repairs)

```
Rule coverage check:
- validations[] with priority: 35 checked, 35 expressed in prose (ordered list in §2.10), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write op + expected_agency_allocation_version / expected_inventory_lot_version + ERR_STALE_VERSION 412), 0 missing
- state_machines[].transitions: 50 checked, 50 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed (incl. both dual-variant switches, 3 appointment geometries, 8-step allocation, 6-step admin-funds waterfall, pinned per-line rounding), 0 missing
- validations[] conditions: 35 checked, 35 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 73 endpoints checked, all side-effect and applies_to sets expressed, 0 missing
- entities[].fields[] structured content: 13 entities checked, defaults/initial values/types reconstructible, 0 missing
- sibling-branch symmetry: 12 groups checked (3 agreement renewals, 3 training records, STANDARD/HOLD_HARMLESS, TURNOVER/SHELF_LIFE, 3 capacity tests, release/disposal closure, 2 closure paths, 4 order cancels, accept/decline, record/void, 3 sweep passes, 2 OCC guards), 12 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1019
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Repairs made during the audit:** 11 not-found error IDs were only referenced generically in §2.6 and are now each named with their owning path identifier; 11 state transitions expressed only semantically were rewritten into explicit `FROM → TO` arrow form (Agency `ACTIVE → EXPIRED`, lot depletion from both `AVAILABLE` and `WATCH`, the four order cancels, both appointment cancels, both recall closure paths); added the appointment calculation's minute-resolution comparison note.

**Scaffold inconsistencies resolved** (decisions visible in the prose): `admin_funds_pool_cents` follows §1.4's "not negative"; the duplicate-recall-action conflict resolves to `ERR_DUPLICATE_RECALL_ACTION`; priority 18's appointment clause is stated as "`dock_number` must belong to the order's warehouse" without forcing the incompatible `ERR_ALLOCATION_NOT_FOUND` mapping; `federal_lot_code` follows the entity constraint (unique per warehouse); a `RECEIVED` source lot is not moved to `HOLD` but posting it is refused while the recall is open; `line_adjustments` entries rendered as `order_line_id` + `cases_approved`.

The two withheld design files were never opened, grepped, or referenced, and no sibling task directory was read. Both worked examples in the PRD (the 1302.26/3 pound-pallet contrast and the 331000-cent household boundary) come from `SCAFFOLD.yaml` itself — verified by grep against the scaffold.

## Step 5: Generate unit tests — 2026-09-02T07:16:02.449Z

Test generation for task 2351 is complete.

## Files written

`test_helpers/` (9 modules): `__init__.py`, `api_client.py` (one method per endpoint, `PREFIX = "/efap"`), `api_errors.py` (`ApiErrorId`, `NOT_FOUND_ERROR_IDS`, `HTTP_STATUS_CODES`), `assertions.py` (entity-shape + tolerant numeric compares), `constants.py`, `factories.py`, `fixtures.py` (tiered builders, all preconditions via PRD endpoints), `test_users.py`, `types.py`; plus `test_suite/conftest.py`.

`test_suite/` — 15 numbered files, **134 tests**:

| queue | files | tests |
|---|---|---|
| A (§1.8 difficulty) | `test_01`–`test_09` | 58 |
| B (§1.9 corner) | `test_10`–`test_15` | 76 |

New this session: `test_14_corner_errors.py` (9 tests, all 5 non-stub `errors` instances) and `test_15_corner_rbac_layers.py` (13 tests: 3 `rbac`, 3 `cross-cutting complexity layers`, 1 `consistency model`).

## Coverage audit (scripted against both design yamls)

- 19/19 difficulty instances tagged, **every one with >=2 tests**; 46/46 non-stub corner instances tagged (>=1 each).
- 65 distinct `Design:` tags, **0 missing, 0 unknown, 0 dual-tagged, 0 untagged**; each docstring's last line is exactly one tag copied verbatim from the yaml `name:`.
- All 13 `excluded_because` corner stubs correctly untranslated.
- Every file >=5 tests (min 6, max 18).
- Verbatim citation audit: **0 problems** — every quoted PRD sentence survives a literal grep of `workspace/PRD.md` and is a full, rule-bearing sentence.
- Attribute audit of all `from test_helpers import` names and `fx.`/`f.`/`api.` accesses: OK. `compileall`: clean. `pyflakes` on `test_suite/`: clean. No `pytest.skip`/`xfail` anywhere.

## Instances skipped

**None** — all 19 difficulty and all 46 non-stub corner instances passed the two-condition PRD filter.

## Assertions dropped inside otherwise-translated instances (not PRD-derivable)

- `scanned_lot_count` / `flagged_lot_count` on the monitor run, and "sweep reports Agency as changed": §3.3 only says "the run returns the lots it scored" and §3.2 "returns the agencies it changed" — no field names are declared, so the tests assert the state-filtered outcome on the lot/agency rows instead (consistent with `test_01`/`test_06`).
- `updated_at == <clock instant>` on the PATCH instance: §2.5 ties `updated_at` to "every mutation", never to the logical clock.

## Design-vs-PRD corrections applied

- `draw_posture` `COMMITTED_ONLY` → **`PARTIAL`** (§2.11 domain is `NOT_STARTED`/`PARTIAL`/`FULLY_DRAWN`).
- `CommodityOrder.status == SUPERSEDED` → **`CANCELLED` with `cancel_reason == SUPERSEDED`** (§3.5).
- `disposition: "RETURNED"` → **`RETURNED_TO_STATE`** (§3.8).
- Single-eligible-agency `cases_remaining` 500 → **1000** (whole pool goes to the only included agency).
- Fresh-row `version == 1`/`== 2` literals → `assert_version_incremented`, since §2.5 only guarantees monotonic increment.

## Bugs found and fixed in earlier files

- `test_11_corner_state_machines.py`: `HoldScope` used at two call sites but missing from the import list (would have been a `NameError` at runtime) — import added.
- `test_09_compensating_invariant.py`: unused `factories as f` import removed.
- `test_13_corner_validations_endpoints.py`: a paraphrased §3.1 service-area sentence replaced with the verbatim one.

## Step 6: Generate implementation — 2026-09-02T07:16:02.449Z

Implementation complete and verified end-to-end.

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_2351_emergency_food_assistance_commodity_allocation/workspace/implementation/` (3,771 lines total):

| file | role |
|---|---|
| `start.sh` | launcher; `PORT` env (default 10000), guarded `pip install` then `exec python3 app.py` |
| `requirements.txt` | `Flask>=2.2` |
| `app.py` | blueprint registration, `ApiError`/404/405/malformed-JSON/500 handlers, `db.reset()` on boot |
| `db.py` | in-memory `Store` (14 dicts), logical clock (default `2026-08-01T00:00:00Z`), `_seq` ordering |
| `errors.py` | `ApiError` + all 53 PRD §5 codes with statuses |
| `response.py` | envelope, `req_` id, pagination meta |
| `middleware.py` | header auth, role gates, body/pagination parsing |
| `validators.py` | typed field validators, all failures → `ERR_INVALID_REQUEST` |
| `calc.py` | constants, ROUND_HALF_UP decimals, largest-remainder, allocation (both variants), admin funds waterfall, monitor scoring, income limits |
| `serializers.py` | explicit per-entity representations for all 14 entities |
| `services.py` | lookups, posture/entitlement/rollup recomputation, FEFO planner, commitment ledger, recall cascades, 3 appointment geometries |
| `routes_config.py` (21) · `routes_inventory.py` (21) · `routes_program.py` (31) | endpoints |

## Endpoint count
**73 routes, an exact 1:1 match with SCAFFOLD §1.5** (I diffed the registered URL map against the scaffold's endpoint table programmatically — no missing, no extra). The earlier "76" figure in my plan was a miscount.

Also machine-diffed the error taxonomy: 53 PRD codes, 53 implemented, zero mismatched statuses.

## Verification
Four scripted end-to-end suites (~120 assertions) run against a live `start.sh` server on fresh ports. Everything passes; the handful of red lines were wrong expectations in my own scripts (e.g. I asserted 422 for `ERR_WAREHOUSE_COLD_CAPACITY_EXCEEDED`, which is 409 per PRD §5). Covered: full order lifecycle through delivery with ledger conservation, FEFO split ordering, both allocation variants, `ERR_ALLOCATION_INFEASIBLE`, admin-funds waterfall (pool 100001 → 66667/33334 base, 6666 withheld, 60001/40000 final — conserved to the cent), recall cascade three links deep, release vs dispose branches, `RETURNED_TO_STATE` restock, expand/re-dispatch cycle, CLASS_I shortfall, transfers, dock buffer + staging + agency-ceiling geometries, compliance sweep expiry→termination→PROBATION, and validation/auth/pagination edges.

## PRD ambiguities resolved
1. **PRD §2.10's 35-position list is normative** (matches SCAFFOLD §1.4) and overrides narrative order where they differ — e.g. confirm-delivery checks recall hold and posture *before* the window (§3.7 prose lists window first).
2. **`ERR_APPOINTMENT_ALREADY_EXISTS` vs `ERR_INVALID_ORDER_STATE`** (the one place I deliberately depart from strict priority): an order only reaches SCHEDULED/DELIVERED *by owning a live appointment*, so strict state-first ordering would make priority 19 unreachable and render the spec's explicit "SCHEDULED, `BLOCKED`, or `DELIVERED`" list meaningless. I check live-appointment before order state. Both codes are 409, so only an `error_id` assertion can distinguish them. A `HELD` order still answers `ERR_RECALL_HOLD_ACTIVE` first, per §3.7 prose and priority 10.
3. `federal_lot_code` unique **per warehouse** (PRD §2.10.24/§3.3 over SCAFFOLD's "program-wide").
4. `admin_funds_pool_cents >= 0` (PRD over the entity constraint `> 0`).
5. An open **COMMODITY_WIDE** recall covers any lot sharing the source lot's `commodity_id`, so posting such a lot answers `ERR_RECALL_HOLD_ACTIVE`.
6. `dispatch-notices` valid from **INITIATED or NOTIFYING** with `action_count >= 1`; `expand`'s duplicate answers `ERR_DUPLICATE_RECALL_ACTION` *after* the MONITORING state gate.
7. `POST /efap/allocation-cycles` does not resolve `offered_commodity_codes`, keeping `ERR_COMMODITY_NOT_FOUND` reachable at compute-allocations; `formula_variant` is required.
8. `HELD` orders are **not** cancellable via the endpoint (the state machine has no such transition; only the disposal cascade cancels them) — so a HELD order can legitimately block `finalize` with `ERR_INVALID_ORDER_STATE`.
9. Order create bumps the parent entitlement's `version`, so a client must re-read before a second create; OCC is skipped when no entitlement exists so `ERR_ALLOCATION_NOT_FOUND` stays reachable.
10. Version bumps on recomputed rows happen only when the stored value actually changes (`ServiceArea.eligible_agency_count`, `AllocationCycle.draw_posture`); `api_request_timestamp` uses wall-clock UTC while all row timestamps use the logical clock.
11. List filters are permissive (unknown enum → empty page); only pagination bounds raise.
12. `redistributed_cents_total` in the admin-funds report = `Σ(admin_funds_cents − base + withheld)`; `non_compliant_line_count` counts rows with withholding.

## Step 7: Run tests and iterate — 2026-09-02T13:10:00.000Z

All 8 parallel rounds came back fully green on the first sweep — no fixes were needed.

## Summary

**Iterations run:** 1 (one 8-round parallel stability sweep, launched under `setsid nohup`, all rounds joined with `wait`; ~24 min wall clock per round under CPU contention).

**Sweep result:** 8/8 rounds `passed == total == 134`, `failed = 0`, `errors = 0`, `skipped = 0`. No flakiness — the union of failing tests across all 8 rounds is empty, so there was nothing to feed into the diagnostic protocol.

| round | passed/total | duration |
|---|---|---|
| 1–8 | 134/134 each | 1435–1476 s |

**Tests deleted:** none (no test failed either sub-check of STEP 1, because no test failed at all).

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

**Compliance spot-checks performed alongside the sweep:**
- Storage is in-memory only — grep for `sqlite3`, `json.dump`, file-write `open(...)`, `/tmp`, `pickle`, `shelve` across `workspace/implementation/*.py` returns nothing, so `start.sh` re-invocation under `--isolation per-test-server` genuinely wipes all state.
- No `pytest.mark.skip` / `xfail` / `pytest.skip` anywhere in `test_suite/` or `test_helpers/`, so the green result is not masking suppressed assertions.
- `start.sh` already guards its `pip install` behind an import check, which is what keeps 8 concurrent rounds from colliding at boot; it honors `$PORT` from the runner.

Artifacts: results at `workspace/implementation/results.{1..8}.json`, sweep log at `workspace/sweep.log`.

Orchestrator independent verification: re-parsed all 8 `results.*.json` directly — every round reports passed=134 total=134 failed=0 errors=0 skipped=0. Confirmed.

## Step 8: Finalize PRD — SKIPPED — 2026-09-02T13:10:30.000Z

Skip condition met: Step 7 exited on the FIRST 8-round sweep with 0 iterations beyond baseline — 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, 0 `implementation/` fixes. Per the skip rule, `PRD.md` already determined every behavior the implementation exhibits at every site the test suite exercises, so there is no Step 7 diff to patch against and no `PRD_FINALIZED.md` is produced. Step 9 will therefore start from `workspace/PRD.md`.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-02T13:26:00.000Z

`workspace/PRD_COMPLETED.md` written as a minimal patch over `workspace/PRD.md` (no `PRD_FINALIZED.md` existed, per Step 8 being skipped).

**Source vs completed:** `PRD.md` 557 lines / 101,985 chars → `PRD_COMPLETED.md` 561 lines / 113,074 chars. **Char delta +11,089.** Only 4 lines added structurally (one bullet appended to the existing §2.2 list, one short paragraph in §3.2, one row in the §5 table); every other change is in-paragraph. No new sections.

**Counts: 53 ambiguity-pins, 10 mismatch-revisions (63 changes).**

### §2 Global Specifications
- §2.1 — insert — ambiguity — a whitespace-only `X-User-ID`/`X-User-Role` counts as absent → `ERR_UNAUTHENTICATED` — middleware.py:23
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly twenty uppercase alphanumerics — response.py:12-13
- §2.2 — insert — ambiguity — `api_request_timestamp` reads the host wall clock, never the logical clock — response.py:16-18
- §2.2 — insert — ambiguity — the two checkpoint runs answer `response_type` `"array"` with no pagination meta at all — routes_config.py:323, routes_inventory.py:146
- §2.2 — insert — ambiguity — unparseable/non-object body → `ERR_INVALID_REQUEST` 422; unrouted path or method → `ERR_NOT_FOUND` 404 — app.py:34-46
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` rejected with `ERR_INVALID_REQUEST` — middleware.py:76-88
- §2.3 — insert — ambiguity — filters are exact equality, empty values ignored, out-of-enum matches nothing; insertion order breaks `created_at` ties — db.py:85-87
- §2.4 — insert — ambiguity — setter and reader both answer an object carrying `current_utc` alone — routes_config.py:46-57
- §2.5 — insert — ambiguity — a fresh row carries `version` 1 and `updated_at` equal to `created_at` — db.py:62-72
- §2.5 — insert — ambiguity — a `PATCH` supplying no revisable field still bumps `updated_at`/`version` — routes_config.py:107-120
- §2.6 — insert — ambiguity — per-endpoint body FK resolution order spelled out — routes_inventory.py:49-50,160-161; routes_program.py:302-304,809-811
- §2.7 — insert — ambiguity — inbound `net_weight_lbs_per_case` rounded half-up to 3 places, `prior_period_pounds_distributed` to 2 — validators.py:87-90
- §2.7 — insert — ambiguity — largest-remainder wraps when leftover exceeds candidates; negative residual walked by ascending fraction — calc.py:76-98
- §2.8 — insert — ambiguity — the stale-version guard is skipped entirely when the agency holds no entitlement — routes_program.py:307-313
- §2.9 — insert — ambiguity — unified entitlement `status` rule including the `cases_delivered > 0` guard on `FULLY_DRAWN` and sticky `RECONCILED` — services.py:132-146
- §2.10 pos 19 — revise — mismatch — appointment creation evaluates positions 10 and 19 ahead of position 8 — routes_program.py:634-641
- §2.10 pos 4 — revise — mismatch — the `dock_number` <= `dock_count` ceiling is deferred until position 5 resolves the order — routes_program.py:627-633
- §2.10 pos 18 — revise — mismatch — dropped the unimplemented transfer-warehouse and appointment-dock coherence claims — routes_inventory.py:155-176; routes_program.py:626
- §2.11 — revise — mismatch — a recompute landing on the stored value writes nothing and bumps nothing; `NOT_STARTED` also when the cycle has no entitlement row — services.py:104-161

### §3 Business Logic
- §3.1 — insert — ambiguity — commodity `code` 1-60, `name` 1-200 — routes_config.py:333-334
- §3.1 — insert — ambiguity — warehouse `name` 1-200 — routes_config.py:388
- §3.1 — revise — mismatch — only uppercase is enforced on commodity `code`; snake case is convention — validators.py:40-48
- §3.2 — insert — ambiguity — renewal validation order (dates → `TERMINATED` → training → `ACTIVE` self-loop) and `201 Created` with the agency — routes_config.py:213-236
- §3.2 — insert — ambiguity — `attendee_count` validated not persisted; `completed_at` never future on all three transitions; `201 Created` with the agency — routes_config.py:244-259
- §3.2 — insert — ambiguity — sweep passes read earlier passes' writes (ACTIVE→EXPIRED→TERMINATED in one run); one version bump after all passes; results in `created_at` order — routes_config.py:285-323
- §3.3 — insert — ambiguity — definition of when a recall "covers" a lot — services.py:309-321
- §3.3 — insert — ambiguity — monitor-run `warehouse_id` in the body, unknown → `ERR_WAREHOUSE_NOT_FOUND`, results in `created_at` order — routes_inventory.py:134-146
- §3.3 — insert — ambiguity — `decline_reason` required 1-400, validated before ownership — routes_inventory.py:255
- §3.3 — insert — ambiguity — acceptance does not re-test the lot's available cases — routes_inventory.py:230-243
- §3.3 — insert — ambiguity — an `AVAILABLE`/`WATCH` lot under an open recall also refuses a proposal with `ERR_RECALL_HOLD_ACTIVE`, after the lot-state check — routes_inventory.py:172-173
- §3.3 — insert — ambiguity — decline skips a `DISPOSED` or vanished source lot and requires no lot status — routes_inventory.py:262-266
- §3.4 — insert — ambiguity — compute-allocations requires `DRAFT`; the three preconditions run in written order — routes_program.py:116-127
- §3.4 — insert — ambiguity — step-eight invariant failure → `ERR_ALLOCATION_INFEASIBLE` with no rows written — calc.py:250-251
- §3.4 — insert — ambiguity — step-two zero factor sum → every `poverty_share` 0.000000 — calc.py:126-129
- §3.4 — insert — ambiguity — open-window requires `ALLOCATED`, close-window requires `OPEN` — routes_program.py:180,193
- §3.4 — insert — ambiguity — step-five ranking wraps on overflow and walks ascending fractions (skipping zero rows) on a negative remainder — calc.py:150-175
- §3.5 — insert — ambiguity — adding a line answers `201 Created` carrying the line, not the order — routes_program.py:427
- §3.5 — revise — mismatch — `HELD` is not cancellable and `cancel_reason` is required at 1-400 chars — routes_program.py:757-770
- §3.5 — insert — ambiguity — the cancelled appointment inherits the order's own `cancel_reason` — services.py:224-228
- §3.6 — insert — ambiguity — `line_adjustments` capped at 200 entries; a later duplicate entry wins — routes_program.py:495-497
- §3.6 — insert — ambiguity — cases claimed by an earlier line of the same approval count against a candidate's availability — services.py:247-272
- §3.7 — revise — mismatch — full booking gate order pinned: dock ceiling → `ERR_RECALL_HOLD_ACTIVE` → `ERR_APPOINTMENT_ALREADY_EXISTS` → order state → `window_start` at full instant precision — routes_program.py:626-641
- §3.7 — revise — mismatch — confirm-delivery order is ownership → appointment state → reserved lots → posture → window (window last); a `DEPLETED`/`DISPOSED`/missing lot also answers `ERR_RECALL_HOLD_ACTIVE` — routes_program.py:722-742
- §3.7 — insert — ambiguity — appointment `cancel_reason` required 1-400 — routes_program.py:775
- §3.8 — insert — ambiguity — a `LOT_ONLY` recall on a `RECEIVED` lot holds nothing: `held_lot_count` and `action_count` both 0 — routes_inventory.py:311-330
- §3.8 — insert — ambiguity — exposure basis (`DELIVERED` orders + `ACCEPTED` transfers) and action creation in agency `created_at` order — services.py:291-306; routes_inventory.py:330-332
- §3.8 — insert — ambiguity — `acknowledged_count` recounted from scratch; the `MONITORING` bubble-up requires `NOTIFYING`; every acknowledgement bumps the recall's `version` — routes_inventory.py:502-522
- §3.8 — insert — ambiguity — `cases_accounted` may be 0, and its ceiling is tested before ownership and action state — routes_inventory.py:530-534
- §3.8 — insert — ambiguity — every disposition bumps the recall's `version`; `RETURNED_TO_STATE` credits the recall's source lot whatever its status, without reviving it — routes_inventory.py:556-571
- §3.8 — insert — ambiguity — expand resolves the agency first, measures exposure over currently held lots, and answers `201 Created` with the action — routes_inventory.py:396-425
- §3.8 — revise — mismatch — closure evaluates state, then `CLASS_I` accounting, then segregation of duties — routes_inventory.py:432-451
- §3.8 — insert — ambiguity — a `HELD` order is released only once every lot it reserves is live again — services.py:354-360
- §3.8 — insert — ambiguity — disposal clears `hold_recall_id` to null; the release path skips already-`DISPOSED` lots while still crediting the entitlement — services.py:207-217,390-394
- §3.9 — revise — mismatch — gate order is cycle state → posture → income test → offered → entitlement, so `ERR_HOUSEHOLD_INELIGIBLE` precedes the last two — routes_program.py:812-830
- §3.9 — insert — ambiguity — `void_reason` required 1-400 — routes_program.py:894
- §3.9 — insert — ambiguity — step-one fallback chain when `total_allocated_cases` is itself zero, and the all-residual outcome at zero total weight — calc.py:265-286
- §3.9 — insert — ambiguity — a cycle with no entitlement row writes `admin_funds_allocated_cents` 0 and skips all six steps — routes_program.py:216-224
- §3.9 — insert — ambiguity — the admin-funds report is readable at any cycle status and reports zeros before finalization — routes_program.py:240-262

### §4 / §5
- §4 — revise — ambiguity — service-areas list filterable by county code and urban/rural — routes_config.py:89-98
- §4 — revise — ambiguity — commodities list filterable by code and storage class — routes_config.py:360-370
- §4 — revise — ambiguity — warehouses list filterable by monitor policy — routes_config.py:415-424
- §4 — revise — ambiguity — allocation-cycles list filterable by status and formula variant — routes_program.py:80-95
- §5 — insert — ambiguity — added the `ERR_NOT_FOUND` → 404 row the API can emit for unrouted paths and methods — app.py:34-40

### Deliberately left unpinned
Two ordering deviations are unreachable and were not written in, to honour "never invent behavior impl does not exhibit": `ERR_ALLOCATION_NOT_FOUND` landing after the window/empty-order checks in `submit_order` (routes_program.py:461-463), and after `ERR_INSUFFICIENT_INVENTORY` in `approve_order` (routes_program.py:525-528) — an entitlement always exists at both points because order creation requires one and nothing is ever deleted.

Orchestrator verification: `PRD_COMPLETED.md` present at 561 lines / 113,074 chars, all five top-level sections (§1–§5) intact, ending on the same error-catalogue row as `PRD.md`. Patch is additive with 128 word-level replacements — consistent with 10 in-paragraph mismatch revisions. Pipeline complete.
