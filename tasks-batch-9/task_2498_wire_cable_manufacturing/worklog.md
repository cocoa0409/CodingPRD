# Worklog — task_2498_wire_cable_manufacturing

## Step 1: Create task directory — 2026-09-03T01:27:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2498_wire_cable_manufacturing` and `.../workspace` (index pre-assigned by orchestrator input; no index auto-allocation performed).

## Step 2: Generate scaffold — 2026-09-03T03:35:00.000Z

All three scaffold artifacts for task 2498 are complete and lint-clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2498_wire_cable_manufacturing/`)
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

**SCAFFOLD.yaml surface**
- 13 entities (MetalPriceQuote, RodPurchaseLot, Compound, CatalogProduct, ListingCertification, FactoryInspection, Customer, CustomerOrder, ProductionLot, CableTest, Reel, Shipment, ReelReturn); topology flat, `api_prefix: "/"`
- 9 state machines (ProductionLot parallel process_state × quality_state with a REWORK rewind cycle; Reel AVAILABLE→LOADED→SHIPPED→RETURN_PENDING→AVAILABLE; CustomerOrder parallel pricing × fulfillment; ListingCertification ACTIVE↔VARIATION_NOTICE/SUSPENDED), 2 OCC concurrency rules
- 12 calculations, 26 ordered validations (priorities 10–80), 47 endpoints (incl. the mandatory `POST /_clock/set_current_utc`), 45 errors, 8 roles (`Customer` = `entity_backed:Customer`, role_model segregation_of_duties)
- complexity_profile: primary `pricing_engine`, secondary `compliance_audit`; layers dual_variant_calculation, cascading_side_effects, optimistic_concurrency, rate_threshold_triggers; consistency_model immediate

**Design files**
- §1.8: 9 rule groups / **23 instances**
- §1.9: all nine guide sections / **59 counted instances** + 22 `excluded_because` stubs — entities 11, state_machines 10(+4), calculations 8(+7), validations 11(+7), endpoints 7, errors 3, rbac 4, cross_cutting_complexity_layers 3(+4), consistency_model 2

**Verification**
```
Coverage
  §1.5 endpoints declared:    47
  §1.1 entities declared:     13
  §1.8 instances scanned:     23
  §1.9 instances scanned:     59
  Calls scanned (§1.8+§1.9):  1592

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Extra audits I ran: all 47 declared endpoints are actually exercised; all 45 error ids are asserted as returned somewhere (ERR_SEGREGATION_OF_DUTIES, previously masked in §1.8, is now returned for real in the rbac section); all 104 instance/stub names unique across both design files.

**Two real defects found and fixed in SCAFFOLD.yaml while generating §1.9** (the audit value of the corner pass): (1) validation priority 54 `ERR_REQUIRED_TESTS_INCOMPLETE` was unreachable because the EXTRUDED→TESTED promotion already demanded every release-required PASS — fixed by splitting the inline set {SPARK, HIPOT} from the release set (+PARTIAL_DISCHARGE when `pd_test_required`) across §1.2/§1.3/§1.4; (2) 19 §1.8 payloads passed `reel_program: true` for an enum field — corrected to `"RETURNABLE"` (the lint checks field names, not enum values).

## Step 3: Copy shared files — 2026-09-03T03:35:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2498_wire_cable_manufacturing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-03T03:54:00.000Z

All three contracts pass. Final verification summary.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2498_wire_cable_manufacturing/workspace/PRD.md` — **447 lines**, 96,325 bytes. Last section heading: **`## 5. Error Code Catalogue`**. The file ends on a complete table row (`| \`ERR_CREDIT_LIMIT_EXCEEDED\` | 402 |`), at a real section boundary, with no audit footer appended.

**Structure** (verified against the skill spec):
- `## 1. Introduction`; `## 2.` with 11 domain-derived subsections (2.1 RBAC, 2.2 verbatim response block, 2.3 Pagination, 2.4 identity/audit/logical clock, 2.5 precision & units, 2.6 OCC, 2.7 cascade ordering, 2.8 metal mass conservation, 2.9 deposit ledger & credit, 2.10 reference resolution order, 2.11 the 26-rung Rejection Ladder); `## 3.` with 9 subsections (3.1–3.9); `## 4.` 4-column table; `## 5.` 2-column table.
- §2.2 confirmed **byte-identical** to `section-2.2-response-structure.md`.

**Contract 1 — Field-Name Coverage: PASS.** 169 required identifiers (all `entities[].fields[].name` plus every endpoint `input` name, optional `?` markers stripped) — **0 missing**, all present verbatim in backticks.

**Contract 2 — Rule Coverage: PASS.**
- 45/45 error IDs in the §5 table with **0 status mismatches, 0 extras**, and all 45 also referenced in the §2/§3 narrative (not table-only).
- 47/47 endpoints in §4 with **0 role mismatches** against the scaffold RBAC.
- All 26 validation priorities appear as ladder rungs 1–26 in scaffold priority order (10→80); every error code they raise is reachable, the nine 404 codes via §2.10's explicit resolution order.
- 50/50 state transitions covered; all state names and **all entity enum values present (0 missing)**.
- All 12 calculations covered, including both `shipment_invoice_amount` variants, all three `reel_deposit_refund` variants, and the pinned rounding orders. Numeric constants all present — the 11 that aren't literal digit strings are deliberately in prose form (surcharge rates as "two percent"/"one and a half percent"/"one percent", `12.5` as "twelve dollars fifty", `0.50` as "half the deposit", `25000` as "twenty-five thousand"); `52`/`54`/`56` are scaffold validation-priority cross-references, not domain constants.
- All 19 system-managed field defaults verified as stated via initial-value prose ("begins at", "starts at", "is born at").

**Contract 3 — §3 Path Purity: PASS.** 312 distinct backtick tokens across §3's 172 lines: **0 leading-slash tokens, 0 bare HTTP methods, 0 method+path combinations, 0 unbacketed URL-like strings.**

**Style scans:** 0 fuzzy words; 0 pseudocode operators anywhere in the document — the only fenced blocks are the two mandated JSON envelopes in §2.2.

**Scaffold contradictions resolved** (state machines in §1.2 treated as authoritative over endpoint `side_effects` prose, and each decision stated explicitly in the PRD so the implementer has one reading): `cycle_count` increments only on reel return, never on shipment; non-returnable reels retire at invoice, not at shipment; `occupancy_end_at` is cleared at load and set at shipment staging to the `shipped_at` instant; SKU manual release accepts `DRAFT` or `SUSPENDED`; price-lock accepts `QUOTED` or `HELD`; the listing-reinstatement re-evaluation cascade runs from both `SUSPENDED` and `VARIATION_NOTICE`; `PD_LIMIT_PC` is expressed only for the three MV classes since the scaffold gives no `LV_600` entry.

The withheld files were never opened, grepped, or referenced.

**Orchestrator truncation check:** independently verified — 447 lines, tail ends on a complete `| \`ERR_CREDIT_LIMIT_EXCEEDED\` | 402 |` table row, five top-level sections present (`## 1.` … `## 5.`). Not truncated; no regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T05:35:00.000Z

Done. The suite for `task_2498_wire_cable_manufacturing` is complete and verified.

## Files written

Infrastructure — `/home/ubuntu/github/CodingPRD/tasks/task_2498_wire_cable_manufacturing/test_helpers/`
`__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`

Tests — `/home/ubuntu/github/CodingPRD/tasks/task_2498_wire_cable_manufacturing/test_suite/`
`conftest.py` plus `test_01_entity_shapes_and_defaults.py`, `test_02_state_machine_walks.py`, `test_03_pricing_and_threshold_calculations.py`, `test_04_validation_ladder_rungs.py`, `test_05_listing_projections_and_filters.py`, `test_06_error_envelope_and_role_boundaries.py`, `test_07_composed_layers_and_settled_state.py` (queue B), and `test_08_dual_variant_pricing_and_refunds.py`, `test_09_combinatorial_pricing_formulas.py`, `test_10_parallel_state_dimensions_and_cycles.py`, `test_11_boundary_precision_limits.py`, `test_12_cross_entity_state_gates.py`, `test_13_resource_temporal_overlap.py`, `test_14_transitive_cascades.py`, `test_15_validation_priority_conflicts.py`, `test_16_conservation_invariants.py` (queue A).

## Counts

- **144 tests collected** (114 test functions, 30 of them parametrized), pyflakes clean, every module import-verified, no skip/xfail anywhere.
- **Queue A (difficulty): 23/23 instances**, every one carrying >=2 tests — dual_variant_calc 2, combinatorial_formula 4, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2.
- **Queue B (corner): 58/59 non-stub instances** (the 22 `excluded_because:` stubs were correctly never translated), >=1 test each, spread over entities 11, endpoints 7, calculations 8, state_machines 10, validations 10, errors 3, rbac 4, consistency_model 2, cross_cutting 3.

## Skipped instance (1)

`Corner/validations/cancelling_an_order_that_already_shipped_is_refused` — the design pins `ERR_ORDER_HAS_SHIPMENTS` (409) on a `FULFILLED` order, but PRD §3.5 sequences `ERR_INVALID_ORDER_STATE` first for that state, so the asserted outcome is not uniquely derivable from the PRD. Gap left as a gap, per the PRD-first filter.

## Verification performed

I ran a mechanical audit over all 249 PRD citations in the suite: each quote was normalized and matched verbatim against the PRD text *and* against the specific section it claims. Two defects were found and fixed: one truncated (non-full-sentence) `shipped_kft` quote mislabelled §3.8 in `test_10` (corrected to the full sentence and §3.5), and one three-buckets-in-lockstep quote mislabelled §2.8 in `test_16` (it lives at PRD.md:179, §3.1). A second audit confirmed every test function ends its docstring with exactly one `Design:` line, that all 81 distinct tags resolve to real `name:` values in the source yamls, and that generated code never mentions "scaffold".

Isolation held: nothing under `workspace/implementation/` was read, written, or referenced.

## Step 6: Generate implementation — 2026-09-03T05:12:00.000Z

The Flask implementation for task 2498 is complete and verified.

## Files written — `tasks/task_2498_wire_cable_manufacturing/workspace/implementation/` (3,465 lines)

**Entry point / infra:** `start.sh` (executable; installs deps if needed, `exec python3 app.py`, `0.0.0.0:$PORT` default 10000, foreground), `requirements.txt`, `app.py` (blueprint registration, `ApiError` -> envelope handler, `HTTPException` -> 404/405/400 mapping, `/health`, `clock.reset()` on boot).

**Foundation:** `util.py` (Decimal + ROUND_HALF_UP, ISO-8601 with 3 fractional digits, `jsonable`), `clock.py` (logical UTC clock, default `2026-08-01T00:00:00Z`, never falls back to wall-clock), `db.py` (13 in-memory dicts keyed by id, monotonic `_seq` for created_at tie-breaks — nothing seeded, no file/SQLite/tmp persistence), `errors.py` (45 codes), `response.py`, `validation.py`, `auth.py`, `serializers.py`, `lookups.py`, `constants.py`.

**Services:** `pricing.py` (quote, dual-variant invoice, volatility index, inventory target, dual-variant reel refund), `ledger.py` (rod mass buckets + credit/deposit ledger), `cascades.py` (compound-suspend 3-hop, certification-suspend 3-hop, certification-reinstate 3-hop with stale-pin -> OBSOLETE, order-cancel rod reversal, scrap -> rod + sibling quarantine).

**Routes (10 modules): 47 endpoints** — clock 1, procurement 5, compounds 4, certifications 5, products 5, customers 3, orders 5, lots 8, reels 6, shipments 5. Verified against `app.url_map` (47 excluding `/static` and `/health`).

## Verification

Three smoke passes (in `/tmp/smoke_2498.py`, `/tmp/smoke2_2498.py`, `/tmp/smoke3_2498.py`, not in the workspace) all green: full LV happy path through invoice and reel return; all five cascades; SHIP_DATE_FLOAT vs ORDER_DATE_LOCK; FLAT_STEP vs DAILY_DECAY (reproduces the PRD's worked example — 450.00 deposit at 120 days out refunds 234.00 steel / 225.00 wood); MV PD gating; cut-to-length segment rounding; both ledger invariants (`purchase_weight = remaining + committed + scrapped`, `deposit_charged_total = deposit_balance + credit_memo + forfeited`); 401/403/404/400/402/409/412/422 negatives. Also booted the real server via `./start.sh`, confirmed empty store on a fresh process, and confirmed a restart drops all prior ids (per-test-server isolation).

## PRD ambiguities resolved

The significant one, found by testing: **PD test admissibility after promotion.** PRD §3.7 says "every test row is recorded against a lot whose process dimension is `EXTRUDED`", yet the same section and SCAFFOLD `validations[priority=54]` both describe "an MV lot sitting at `TESTED` without a PD result" as normal (PD is off-line and "routinely lags the line"). Read strictly, an MV lot promoted by SPARK+HIPOT can never receive its PD row and is permanently unreleasable and undispositionable. I allow `PARTIAL_DISCHARGE` from `EXTRUDED` **or** `TESTED`; `SPARK`/`HIPOT` still require `EXTRUDED`, and every other process state still yields `ERR_INVALID_LOT_STATE`. This is the one place where a test asserting 409 for PD-on-TESTED would disagree.

Others (unchanged from earlier reasoning): negative `deposit_usd` -> `ERR_INVALID_REQUEST` (not `ERR_REEL_DEPOSIT_MISMATCH`, which covers type/amount disagreement); REWORK disposition response reports the `REWORK` transient while persisting `PENDING`; `PD_LIMIT_PC` fallback 5.0 pC for a non-MV class; wrong `layer_role` -> 400 before the product_code uniqueness check; `PASS` on a `PENDING` file dated before `initial_listing_date` -> `ERR_INVALID_CERTIFICATION_STATE`; `GOOD` return dated before `date(shipped_at)` -> 400 after the reel-state check; missing extrusion measurements -> 400 after the state and marking checks; Customer list endpoints self-scope and 403 on a foreign explicit `customer_id`; `GET /customers/{id}` checks ownership before existence (403 even for an unknown id) while orders/shipments check existence first (404 then 403); `api_request_timestamp` comes from the logical clock; `cycle_count` is not bumped at staging (PRD overrides the scaffold); release is admissible from `DRAFT` or `SUSPENDED`; client numbers stored verbatim as `Decimal(str(x))` and emitted as JSON numbers, only computed fields quantized; client datetimes echoed verbatim with a parsed copy under a `_`-prefixed key; `VARIATION` escalation at `VARIATION_NOTICE` reads the pre-existing `open_variation_count >= 1`; one `version` bump per record per request; all "created_at ASC" orderings tie-broken by `_seq`.

## Step 7: Run tests and iterate — 2026-09-03T06:30:00.000Z

Clean — pyflakes silent, no skip/xfail markers (only prose matches).

## Summary

**Iterations run:** 2 (each an 8-round parallel sweep under `setsid nohup`, all rounds joined with `wait`).

- **Sweep 1:** all 8 rounds identical at **141/144**, 3 deterministic failures (same 3 in every round — no flakiness).
- **Sweep 2:** all 8 rounds **144/144 passed, 0 failed, 0 errors, 0 skipped** (~256 s/round). Confirmed on disk: `workspace/implementation/results.{1..8}.json`.

**Tests deleted:** none. All three failures were STEP-2 test bugs (assertion mistranslations of PRD prose), not PRD silence.

**Fixes applied to `test_suite/`:**

1. `test_suite/test_04_validation_ladder_rungs.py` — `test_the_extrusion_print_must_equal_the_skus_required_marking_exactly`: expected status for the accepted `POST /production-lots/{id}/process-steps` changed **201 -> 200**. PRD §4: *"Operations that bring a new resource into existence answer with HTTP 201; operations that modify or transition an existing resource, and all read operations, answer with HTTP 200."* No `ProcessStep` resource exists in the PRD (13 entities, no list endpoint for steps); §3.6 frames the call purely as advancing the lot's process dimension and the response body is the `ProductionLot`. This was also the suite's only status assertion on that endpoint, and it contradicted the suite's own convention elsewhere (`release_production_lot`/`load_reel`/`invoice_shipment`/`reinstate` all asserted 200).

2. `test_suite/test_04_validation_ladder_rungs.py` — `test_the_third_rework_is_refused_and_scrapping_is_the_only_way_out`: the assertion on the **disposition response** was `quality_state == "PENDING"`. PRD §3.7: *"On the quality dimension the lot passes through `REWORK` and ends the same request at `PENDING`: `REWORK` is observable only as the transient the disposition response reports, and the persisted end state is always `PENDING`."* Changed the response assertion to `"REWORK"` and **added** a follow-up re-read asserting the persisted state is `PENDING` (strictly more faithful, one more assertion than before). Docstring now carries that PRD sentence. This matches `test_10`'s already-passing rework test, which asserts the re-read is `PENDING`.

3. `test_suite/test_13_resource_temporal_overlap.py` — `test_a_load_one_second_before_the_return_instant_is_refused`: `returned_at` was compared by exact string to `"2026-08-10T09:00:00Z"` while the server renders `"2026-08-10T09:00:00.000Z"`. PRD §2.4 pins the three-fractional-digit ISO-8601 rendering for server-stamped timestamps but never pins a zero-fraction form for `returned_at`, so the exact-string form was not derivable. Relaxed to `startswith("2026-08-10T09:00:00")` — the suite's own existing precedent for clock-stamped instants (`test_01` line 441 does the same for `tested_at`). The semantic claim under test (the bound is the *clock* instant, not the client-supplied `returned_date`) is fully preserved to the second, and the adjacent occupancy-boundary assertions are untouched.

**Fixes applied to `test_helpers/`:** none needed.

**Fixes applied to `implementation/`:** none. All three defects traced to the test layer; the implementation was PRD-faithful on every point (process-step as a lot transition -> 200, the `REWORK` transient in the disposition response with `PENDING` persisted, and three-fractional-digit clock stamps).

**Orchestrator verification (per known failure mode):** independently confirmed all 8 `workspace/implementation/results.{1..8}.json` exist on disk and each reports `passed == total == 144`.

**Step 8 decision:** NOT skipped. The skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes; three `test_suite/` fixes were applied, and each marks a site where PRD prose did not uniquely determine what the implementation had already chosen (process-step response status, the REWORK transient vs persisted PENDING, `returned_at` fractional-second rendering). Those are exactly the PRD-silence sites Step 8 exists to pin.

## Step 8: Finalize PRD — 2026-09-03T06:35:00.000Z

## Result

`PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_2498_wire_cable_manufacturing/workspace/PRD_FINALIZED.md`.

**Line counts:** PRD.md 447 -> PRD_FINALIZED.md 447 (0.00% line delta; both edits are in-line sentence appends). Character delta +671 (+0.70%), words 13761 -> 13867.

### Changes

- **§2.4 (Record Identity, Audit Fields and the Logical Plant Clock)** — insert — pinned the *rendering form* of server-stamped instants (three fractional digits, whole-second instants render `...T09:00:00.000Z`, never `...T09:00:00Z`) and noted that caller-supplied instants are stored/echoed verbatim — `implementation/util.py:34` (`iso_ts`), `implementation/clock.py:31` (`now_iso`), `implementation/routes/reels.py:194` (`returned_at`).
- **§3.6 (Scheduling and Running a Production Lot)** — insert — pinned that a completed-step report is not a stored resource (nothing persisted, nothing readable) and that an accepted report answers HTTP 200 with the updated production lot — `implementation/routes/lots.py:203/214/251`.
- **Step 7 item 2 (REWORK transient vs persisted PENDING)** — **no edit.** PRD §3.7 already states verbatim that `REWORK` is observable only as the transient the disposition response reports and the persisted end state is always `PENDING`; `routes/lots.py:392-396` implements exactly that (persist `PENDING`, then override `quality_state` to `REWORK` in the response payload only). Pure test-layer bug.

### Per-edit pre-edit search log

**Edit 1 — §2.4 timestamp rendering**
- (a) Subject: how every datetime-valued field is rendered on the wire, and which fields are server-stamped vs caller-supplied.
- (b) Paths enumerated/read: `util.py:34 iso_ts` (the only instant formatter), `util.py:jsonable` (fallback `isoformat()` for real `date`/`datetime` objects — never reached for these fields since all instants are stored as strings), `clock.py` (`now_iso`, `today_str`), `db.py:58,73` (`created_at`/`updated_at`/`touch`), `routes/lots.py:309` (`tested_at`), `routes/shipments.py:123-127` (`shipped_at`, `occupancy_end_at`), `routes/reels.py:194` (`returned_at`), `services/pricing.py:144` (`invoice_date`), `routes/reels.py:98,132` (`occupancy_start_at` stored raw), `routes/lots.py:62-63,114-115` (`scheduled_start_at`/`scheduled_end_at` stored raw), `validation.py:108-130` (`f_date` / `f_datetime` — raw echo), `response.py:_meta` (`api_request_timestamp`), plus a full `grep '_at"' serializers.py` to confirm the field list is closed (only the nine `*_at` fields above).
- (c) Adjustment: the PRD's pre-existing sentence groups `invoice_date` with `tested_at`/`shipped_at`/`returned_at` as "instants", but `services/pricing.py:144` stores it as a `YYYY-MM-DD` date. I therefore did **not** write "those instants" or otherwise sweep the existing list into the three-fractional-digit claim; I restated an explicit field list that excludes `invoice_date` (whose form is already pinned in §3.9 line 329 as "the logical clock's current date"). I also added `occupancy_end_at`, which is server-stamped at staging and was absent from the PRD's original list. The caller-side clause was phrased "stored and echoed back exactly as it was sent" (not "normalized to any canonical form") to stay true to all three verbatim-echo sites.

**Edit 2 — §3.6 process-step response**
- (a) Subject: the status code, response payload, and persistence semantics of `POST /production-lots/{id}/process-steps`.
- (b) Paths enumerated/read: `routes/lots.py:174-251` — all three branches (`DRAWING` :203, `STRANDING` :214, `EXTRUSION` :251) return `response.ok(view("production_lot", lot))`; `response.py:ok/created` (201 comes only from `response.created`); `grep -rn "created(" routes/*.py` — the full set of 201 sites (12 creations, none of them the process-step route), confirming sibling transition endpoints (`disposition`, `release`, `load`, `invoice`, `reinstate`) are all 200 too; `db.py:15-29 COLLECTIONS` — 13 collections, no `process_steps` table; `serializers.py` — no process-step view; `PRD.md` §4 table — no read endpoint for steps.
- (c) Adjustment: worded as "no step record is persisted and none is exposed for reading" rather than asserting anything about a step *entity* shape, and framed the 200 as following from the call being a lot transition, so the sentence stays consistent with §4's global "creation -> 201" rule instead of carving out an exception to it. No claim was made about which lot fields the payload contains, since the three branches mutate different field sets.

## Step 9: Complete PRD — 2026-09-03T07:07:00.000Z

Run as **three sequential file-partitioned passes** over the 3,450-line implementation, all editing `workspace/PRD_COMPLETED.md` in place (Pass A created it from `PRD_FINALIZED.md`; Passes B and C edited without re-copying). This partitioning is a deliberate guard against the known single-shot failure where the scan returns a byte-identical file.

**Aggregate:** PRD_FINALIZED.md 447 lines / 97,002 chars -> PRD_COMPLETED.md 447 lines / 111,583 chars (**+14,581 chars vs PRD.md**, all edits in-paragraph, 0 new sections). **54 edits total: 44 ambiguity-pins, 10 mismatch-revisions.**

### Pass A — foundation + procurement/compounds/certifications (15 edits: 13 pins, 2 mismatches)
Partition: app.py, auth.py, clock.py, constants.py, db.py, errors.py, lookups.py, response.py, util.py, validation.py, routes/__init__.py, routes/clock_control.py, routes/procurement.py, routes/compounds.py, routes/certifications.py.

- §2 intro — insert — ambiguity — trailing slash addresses the same endpoint — `app.py:21`
- §2.1 — insert — ambiguity — whitespace-only header = empty; `X-User-ID` checked before `X-User-Role`; unknown role also `ERR_UNAUTHORIZED` — `auth.py:35-40`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + 20 uppercase-alnum; `api_request_timestamp` reads the logical clock — `response.py:14-22`
- §2.3 — insert — ambiguity — creation-order tie-breaks for default `created_at` ordering, settlement series (desc/desc), inspection list (asc) — `db.py:78-80`, `routes/procurement.py:66`, `routes/certifications.py:24`
- §2.4 — insert — ambiguity — `current_utc` normalised to UTC, unparseable -> `ERR_INVALID_REQUEST`, clock op answers 200 with empty `data` — `routes/clock_control.py:17-19`, `util.py:36-51`
- §2.10 — insert — ambiguity — non-string body reference treated as unresolvable (not-found code), not a shape error — `lookups.py:8-9`
- §2.11 rung 3 — insert — ambiguity — absent/empty body = empty object; non-object body malformed; explicit `null` == omitted; undeclared fields ignored; required strings non-empty; whole-number fields must be JSON integers; booleans are never numbers — `validation.py:15-23,26-31,34-44,78-94`
- §3.1 — **revise — mismatch** — settlement price stored/echoed at submitted precision, not "carried to two decimals" — `routes/procurement.py:28,42`
- §3.1 — insert — ambiguity — `remaining_lbs` is arrival mass rounded half up to 2 dp while `purchase_weight_lbs`/`purchase_price_usd_per_lb`/`rod_diameter_mm` echo submitted precision — `routes/procurement.py:97`
- §3.3 — revise — ambiguity — "latest inspection" tie-break extended to creation order — `routes/certifications.py:24-33`
- §3.3 — insert — ambiguity — file `version` increments on every accepted visit even when status does not move; response payload is the inspection row — `routes/certifications.py:150,155`
- §3.3 — insert — ambiguity — initial-audit date before `initial_listing_date` -> `ERR_INVALID_CERTIFICATION_STATE` — `routes/certifications.py:94-98`
- §3.3 — insert — ambiguity — `VARIATION_NOTICE`+`VARIATION` escalation reads pre-visit `open_variation_count`; stays put when that tally was 0 — `routes/certifications.py:80,145-149`
- §4 intro — insert — **mismatch** — `GET /health` needs no headers and answers bare `{"status":"ok"}` outside the §2.2 envelope — `app.py:55-57`
- §5 intro — insert — ambiguity — `ERR_NOT_FOUND` (404) unmatched path, `ERR_METHOD_NOT_ALLOWED` (405) wrong method, both enveloped — `app.py:37-42`

### Pass B — products/customers/orders/reels + serializers + ledger (21 edits: 18 pins, 3 mismatches)
Partition: serializers.py, routes/products.py, routes/customers.py, routes/orders.py, routes/reels.py, services/ledger.py. Verified all 15 Pass A edits intact before and after.

- §2.1 — **revise — mismatch** — the `Customer` ownership check precedes existence only for accounts; orders/shipments resolve the record first (so an unknown id yields `ERR_ORDER_NOT_FOUND`/`ERR_SHIPMENT_NOT_FOUND`, not 403); list reads scope silently while an explicit foreign filter is refused — `routes/customers.py:55`, `routes/orders.py:83,97-100`, `routes/shipments.py:152-155,169-176`
- §2.2 — insert — ambiguity — resource objects always carry the full declared field set, unset fields present as `null`, internal bookkeeping never exposed — `serializers.py:209-211`
- §2.3 — insert — ambiguity — identifier filters match as opaque strings; enum filters reject non-members; pagination bounds checked before any filter — `routes/products.py:126-131`
- §2.9 — **revise — mismatch** — `open_ar_usd` and `reel_deposit_balance_usd` are re-derived in full at every ledger event; only the three lifetime totals accumulate; exactly one account `version` bump per request — `services/ledger.py:84-100`
- §3.1 — insert — ambiguity — scrap-alarm quarantine fires only while the rod lot is still `RECEIVED` — `services/ledger.py:32`
- §3.4 — insert — ambiguity — wrong `layer_role` -> `ERR_INVALID_REQUEST` after references resolve, before `product_code` uniqueness — `routes/products.py:59-62`
- §3.4 — insert — ambiguity — `target_inventory_kft` initialised to `base_target_kft` verbatim — `routes/products.py:99`
- §3.4 — revise — ambiguity — reposition: unknown `product_ids` entry -> `ERR_PRODUCT_NOT_FOUND` first; duplicates evaluated once; empty array evaluates nothing; each evaluated SKU bumps `version` even when unchanged; skipped SKUs untouched; payload is the summary in evaluation order — `routes/products.py:211-244`
- §3.5 — insert — ambiguity — `credit_limit_usd` echoed at submitted precision — `routes/customers.py:25`
- §3.5 — insert — ambiguity — every account PATCH bumps `version` once; a body with none of the three fields is accepted and still re-evaluates — `routes/customers.py:65-79`
- §3.5 — insert — ambiguity — credit standing is not examined at booking; a `CREDIT_HOLD` account may still be quoted — `routes/orders.py:43-47`
- §3.5 — insert — ambiguity — `requested_cut_lengths_ft` entries carry no numeric bound; the non-empty rule is a shape check before reference resolution; a list sent with the flag false is stored but never priced — `routes/orders.py:33-38`
- §3.5 — insert — ambiguity — the `OPEN`/`PARTIALLY_SHIPPED` requirement binds the `QUOTED` path only; a `HELD` order lifts regardless of fulfillment; `hold_reason` nulled on both paths — `routes/orders.py:121-134`
- §3.5 — insert — ambiguity — a merely `STAGED` shipment blocks cancellation as an `INVOICED` one does; `reason` may be empty — `routes/orders.py:142,150-155`
- §3.8 — insert — ambiguity — accepted `deposit_usd` stored rounded to cents while `capacity_ft` echoes verbatim — `routes/reels.py:46-47`
- §3.8 — insert — ambiguity — `load_length_ft` may be zero but not negative — `routes/reels.py:97`
- §3.8 — insert — ambiguity — offset-bearing `occupancy_start_at` converted to UTC for the bound comparison while echoed verbatim; a reel whose `returned_at` a later load cleared has no lower bound — `routes/reels.py:117,136`
- §3.8 — insert — ambiguity — the load response payload is the updated reel, not the lot — `routes/reels.py:142`
- §3.9 — insert — ambiguity — `shipment_id` resolved for existence only (need not be the carrying shipment); the `GOOD` date rule is `ERR_INVALID_REQUEST` after both references resolve and after `RETURN_PENDING`; a `DAMAGED` return is not date-checked so `days_out` may be negative — `routes/reels.py:152-171`
- §3.9 — **revise — mismatch** — hop one no longer claims `reel_deposit_balance_usd` is explicitly decremented; it falls out of the hop-two re-derivation per §2.9 — `routes/reels.py:194-216`
- §3.9 — insert — ambiguity — the return row is the operation's payload; both return listings order `created_at` asc with creation-order tie-break and resolve the path parent first — `routes/reels.py:174-233`

### Pass C — lots/shipments/pricing/cascades (18 edits: 13 pins, 5 mismatches)
Partition: routes/lots.py, routes/shipments.py, services/pricing.py, services/cascades.py.

- §2.1 — **revise — mismatch** — the `Customer` list-scope filter refusal is reached after pagination bounds and enum values validate; non-ownership filters (`lot_id`, `reel_id`) are never refused — `routes/shipments.py:161-184`
- §3.3 — insert — ambiguity — reinstatement hops 2 and 3 impose no fulfillment condition on the order and no process condition on the lot, unlike the freeze hops — `services/cascades.py:145-155`
- §3.5 — **revise — mismatch** — on cancellation a queued lot's quality dimension is left exactly as it stood (an already-`QUARANTINED` lot stays `QUARANTINED`), not "left at `PENDING`" — `services/cascades.py:161-172`
- §3.6 — insert — ambiguity — scheduling resolves rod lot / SKU / order for existence only and examines no statuses — `routes/lots.py:69-71`
- §3.6 — insert — ambiguity — a new lot's `released_by_user_id` is born null — `routes/lots.py:127`
- §3.6 — revise — ambiguity — drawing refuses a non-`RELEASED` SKU with `ERR_INVALID_PRODUCT_STATE` only after the lot's own two dimensions clear; stranding on `SOLID` gives `ERR_INVALID_LOT_STATE`; drawing is the only report examining the quality dimension — `routes/lots.py:191-222`
- §3.6 — insert — ambiguity — an omitted/empty `surface_marking_text` is a non-matching print (`ERR_MARKING_MISMATCH`, not a shape error); when `marking_required` is false nothing is compared and whatever was sent, `null` included, is stored — `routes/lots.py:226-242`
- §3.7 — **revise — mismatch** — `PARTIAL_DISCHARGE` rows are admissible from `EXTRUDED` **or** `TESTED` while `SPARK`/`HIPOT` require `EXTRUDED`; the quality dimension is never examined when a test is recorded — `routes/lots.py:277-283`
- §3.7 — insert — ambiguity — `pd_level_pc` carries no bound of its own (zero/negative accepted) — `routes/lots.py:266`
- §3.7 — insert — ambiguity — an `LV_600` SKU falls back to the 5.0 pC limit; the reading is rounded half up to one decimal before comparison — `routes/lots.py:296-297`
- §3.7 — **revise — mismatch** — promotion is available only while the process dimension still reads `EXTRUDED` (a passing PD row on an already-`TESTED` lot leaves both dimensions, `updated_at` and `version` untouched); quality "stays exactly where it stood"; "latest" gains the reachable third tie-break — `routes/lots.py:319-327,37-46`
- §3.7 — insert — ambiguity — `packaged_length_ft` is mandatory, may be zero but never negative, stored as submitted — `routes/lots.py:418`
- §3.8 — insert — ambiguity — `shipped_length_ft` must be strictly greater than zero — `routes/shipments.py:29`
- §3.8 — insert — ambiguity — the `shipped_kft` sum is rounded half up to three decimals *before* the `ordered_kft` comparison and that rounded figure is stored — `routes/shipments.py:71-74,138`
- §3.8 — insert — ambiguity — reel/lot agreement is demanded but lot/order agreement never is — `routes/shipments.py:51-60`
- §3.9 — insert — ambiguity — a pricing dimension other than `QUOTED`/`LOCKED` (including `HELD`) refuses the invoice with `ERR_INVALID_ORDER_STATE`, not the pricing-hold code — `routes/shipments.py:200-205`
- §3.9 — **revise — mismatch** — the order's `version` increments once for the `invoiced_total_usd` movement, with the `LOCKED` -> `INVOICED` move folded into that same increment — `routes/shipments.py:216-221`
- §3.9 — insert — ambiguity — extension and cut fee are computed independently: `cuts_count` above the list length bills every cut but extends only existing entries; `cuts_count` 0 yields 0.00/0.00; `shipped_length_ft` never enters a cut-to-length invoice — `services/pricing.py:126-129`

### Deliberately not asserted (verified unreachable)
The `created_at`/insertion-order tie-breaks in `pricing._quote_rank_key` can never fire because `ERR_DUPLICATE_METAL_QUOTE` makes `(metal, effective_date)` unique and quotes are immutable. Cascade sibling grouping in `cascades._orders_for_products` (per-parent rather than globally sorted) is unobservable since every record touched in one request receives the same frozen-clock stamp.

### Orchestrator final verification
- `PRD_COMPLETED.md` is **not** byte-identical to its source: 51 changed lines / 102 diff lines vs `PRD_FINALIZED.md`, +14,581 chars vs `PRD.md`. The scan genuinely ran.
- All five top-level sections present (`## 1.` … `## 5.`); file ends cleanly on the last error-catalogue row (`ERR_CREDIT_LIMIT_EXCEEDED | 402`), not mid-sentence; line count held at 447 (all edits in-paragraph, no new sections).
- No `implementation/` code was touched in Steps 8 or 9, so the Step 7 green state stands: all 8 `results.{1..8}.json` still report `passed == total == 144`.

**Pipeline complete.**
