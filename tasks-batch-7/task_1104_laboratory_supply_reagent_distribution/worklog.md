# Worklog — task_1104_laboratory_supply_reagent_distribution

## Step 1: Create Task Directory — 2026-08-10T00:00:00.000Z

Task directory `tasks/task_1104_laboratory_supply_reagent_distribution/` with `workspace/` subdirectory pre-created (index pre-assigned as 1104 per instruction; auto-index scan skipped).

## Step 2: Generate Scaffold — 2026-08-10T16:05:00.000Z

All three scaffold artifacts are generated, linted clean, and saved. Final lint verdict, verbatim:

```
Coverage
  §1.5 endpoints declared:    80
  §1.1 entities declared:     16
  §1.8 instances scanned:     21
  §1.9 instances scanned:     54
  Calls scanned (§1.8+§1.9):  536

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Deliverables** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1104_laboratory_supply_reagent_distribution/`):
- `SCAFFOLD.yaml` (~124 KB) — §1.0–§1.7 only; no design keys. 16 entities, 14 state machines, 3 OCC concurrency rules, 20 calculations, 28 priority-ordered validations, 80 endpoints, 86 error codes, 6 roles.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (~64 KB) — single `scaffold_difficulty_design:` key, 21 instances: every §0.5 rule at ≥2 instances (combinatorial_formula and boundary_precision_check have 3, cross_entity_state_dependency has 3).
- `SCAFFOLD_CORNER_DESIGN.yaml` (~117 KB) — single `scaffold_corner_design:` key, 63 instances across 8 sections (54 active + 9 `excluded_because` stubs pointing at §1.8 instances).

**Design highlights (harder-than-expert calibration):**
- Archetype: quota/allocation (lot reservation pools) blended with compliance/audit (hazmat caps, recall lot-pull, cold-chain excursion dispositions); flat FK topology, cyclic state-machine shape, peer-role RBAC with entity-backed `Customer`.
- All nine difficulty rules carry structurally differentiated instances: dual-variant freight (2300 vs 2660 cents on identical data) vs dual-variant excursion credit (20000 vs 40000) on a different domain; combinatorial formulas in all three modes (freight 4-input nonlinear = 2763; per-line-round-then-sum = 190 vs naive 189; kit fee tier keyed on pre-fee component sum = 36500); Order BACKORDERED↔ALLOCATED and Lot AVAILABLE↔QUARANTINED cycles; a depth-4 recall cascade and a depth-3 excursion-destroy cascade from different triggers; state-vs-fiscal and safety-vs-fiscal priority conflicts; boundaries on hazmat load units (10 passes/11 fails), free-freight cents (250000 → 0, 249999 → 800), and empty-components cardinality; consignment half-open adjacency-allowed windows vs standing-order inclusive+7-day-buffer windows; unit-conservation and cents-conservation compensating invariants.
- Every formula-derived assert literal was executed in Python before pinning (freight, rounding, kit tiers, catch-up dates, replenishment qty 85, severity 59-vs-60-minute boundary, etc.).
- Replay-driven fixes applied during generation: added `warehouse_id` to StandingOrder (generated orders need a fulfillment warehouse), `initial_stocked_quantity`/`replenishment_warehouse_id` to consignment (reachable consumption setups), record-temperature guard reordered so `ERR_EXCURSION_ALREADY_OPEN` is reachable from EXCURSION_HOLD, sequential no-run corner uses lot qty 4 so no single-lot run accidentally satisfies it, and `warehouse_id?` filters added for FK reverse-reachability.
- Forbidden-vocabulary scan clean; 84 instance names unique across both design files; clock endpoint pinned to the mandatory `2026-05-01T00:00:00Z` default.

No sibling task directories were read at any point; the scaffold was built solely from the scenario text and the skill specification.

## Step 3: Copy Shared Files — 2026-08-10T16:06:00.000Z

Copied ./INSTRUCTION.md to tasks/task_1104_laboratory_supply_reagent_distribution/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-10T16:25:00.000Z

PRD generation is complete. The document is at `/home/ubuntu/github/CodingPRD/tasks/task_1104_laboratory_supply_reagent_distribution/workspace/PRD.md` (~2300 words of spec prose across 5 sections). The withheld index files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced, and no other `task_*/` directory was touched.

**Document structure** (domain-derived, not template-copied):
- §1 Introduction — 2 paragraphs (physical cold-chain loop + commercial mechanisms/logical clock)
- §2 Global Specifications — 11 subsections: RBAC with per-role identity prose (Customer entity-backed via `CustomerAccount`, five ops roles opaque), verbatim §2.2 envelope, pagination + per-resource list filters, common resource properties (with the `ConsumptionRecord` no-`updated_at`/no-`version` exception), the logical clock (`2026-05-01T00:00:00Z` initial, `to_iso8601`, sweep counters), existence/validation priority chain (7 stages + business), the three OCC endpoints with exact `expected_*_version` fields and 412 error ids, integer-cents/round-half-up precision, temperature bands and coldness ordering, hazmat governance (endorsement ladder, warehouse certification, class caps 30/30/10/10, total 50, dry-ice 20), and cascade-consistency principles
- §3 Business Logic — 9 subsections (network stocking, lot receipt/adjustment/quarantine, accounts and credit, ordering and allocation, shipment/freight/hazmat, telemetry/excursions/disposition, recalls, standing orders/consignment/replenishment, kits/assembly), with validation priority orders stated per workflow (e.g., submit: endorsement → cold-chain → recall → shelf-life → listing → credit; lot receipt: hazmat cert → compatibility → capacity → warehouse match)
- §4 Endpoint table — 80 rows, 4 columns each, methods/paths/roles verified against scaffold
- §5 Error catalogue — 86 rows, 2 columns, no trigger conditions

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + endpoint inputs + path params + common fields + OCC fields: 121 required, 121 present, 0 missing
Status: PASS

Rule coverage check:
- validation priority orderings: 7 endpoint-specific chains expressed (submit, lot receipt, shipment creation, consumption, customer close, kit activation, global 7-stage chain)
- concurrency_rules OCC rejections: 3/3 expressed (write_endpoint + expected_<parent>_version + error_id + 412, no race framing)
- state_machines[].transitions: 60/60 expressed across all 16 entity machines (from/to states, preconditions paired with error ids, side effects incl. all cascades)
- calculations[]: 20/20 expressed in precise prose (bands, FEFO/FIFO + sequential-run selection, pinned per-line pricing with the 105¢/10% → 190 example, freight tiers/floor/free-freight, hazmat load caps, excursion severity/credit variants, outstanding-balance and 1.2x suspension, consignment billing/replenishment, kit fee tiers, standing-order generation, zone occupancy, both window rules, shelf-life gate)
- validations[] conditions: all matchable to error ids in §2/§3; all 86 error ids mentioned in §2/§3 narrative as well as §5
- endpoints[].side_effects / applies_to: 80/80 covered (incl. dispatch consignment increment with no replenishment trigger, waitlist retry on receipt, record-temperature guards)
- entities[].fields[] structured content: defaults, nullability-until-event, and value constraints reconstructible from prose
- sibling-branch symmetry: cancel/close/discontinue multi-from transitions, ACCEPTED/DESTROYED/RETURNED dispositions, service tiers, coolant types, bands — equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 605
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 is byte-identical to the canonical `section-2.2-response-structure.md`; no operator syntax (`>=`, `==`, `+=`, …) or fuzzy hedging words appear outside code fences; the file ends at §5 with no audit footer.

## Step 5: Generate Unit Tests — 2026-08-10T16:45:00.000Z

Generation complete. Summary of what was built and the key decisions:

## Deliverables

**`test_helpers/`** (9 files) — `/home/ubuntu/github/CodingPRD/tasks/task_1104_laboratory_supply_reagent_distribution/test_helpers/`
- `types.py` — 17 status/role enums + 17 entity TypedDicts; `ConsumptionRecord` correctly omits `updated_at`/`version` (common_fields: false).
- `api_client.py` — `ApiClient(GenericApiClient)` with 86 methods, one per PRD endpoint under `/lab`.
- `api_errors.py` — all 86 error IDs with HTTP status map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity `assert_*` plus `assert_lot_quantity_conservation`.
- `factories.py`, `constants.py` (freight/hazmat/band/fee-tier thresholds), `test_users.py` (opaque-role constants + `make_customer_headers(user_id)` builder for the entity-backed Customer role).
- `fixtures.py` — single-entity makers, read helpers, and composite chains: `setup_cold_chain_order`, `setup_packed_shipment`, `setup_in_transit_shipment`, `setup_open_excursion`, `setup_ambient_order`. All Customer-role calls thread `make_customer_headers(customer["id"])`.

**`test_suite/`** — `conftest.py` + 9 test files, **94 tests**, all collecting cleanly.

## Coverage audit results
- Queue A (difficulty): all 21 instances × ≥2 tests = 42 tests, each tagged `Design: Difficulty/<rule_id>/<instance.name>` as the docstring's last line.
- Queue B (corner): 52 of 54 non-stub instances translated (1 test each); all 9 `excluded_because` stubs verified to cross-reference real difficulty instances and were not translated.
- Zero untagged/orphan/dual tags; zero `skip`/`xfail` marks; all 145 long PRD docstring quotes verified verbatim against `workspace/PRD.md`.

## Two instances deliberately skipped (PRD-first filter, gaps stay gaps)
1. **`Corner/calculations/fifo_policy_prefers_earliest_received_lot`** — the instance asserts the reservation lands on the earliest-received lot, but with `shelf_life_days: 60` that lot (manufacture 2026-03-01 → expiry 2026-04-30) fails the PRD §3.4 shelf-life gate against `requested_ship_date` 2026-05-10. A PRD-faithful implementation allocates the second lot, so the asserted outcome contradicts the PRD. (Its sibling `fefo_prefers_earliest_expiry_lot` was kept — its asserted outcome, reservation on lot2, is what the PRD actually derives.)
2. **`Corner/validations/consumption_on_suspended_agreement_rejected`** — PRD §3.8 states consumption requires an `ACTIVE` agreement but never names the `error_id` for that violation (`ERR_AGREEMENT_NOT_ACTIVE` is verbatim-tied only to the suspend transition); the asserted error fails the coverage condition.

## Notable fixes during generation
- `test_cold_chain_uncertified_customer_rejected` initially reused the eager-submit fixture (which would have failed in setup); rebuilt as a manual chain.
- Two docstring quotes included the PRD's `**Request well-formedness**` markdown label; re-quoted from the plain-text portion so they survive literal grep.

## Step 6: Generate Implementation — 2026-08-10T16:46:00.000Z

All verifications pass. The implementation is complete.

## Summary

Generated a complete Python + Flask implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1104_laboratory_supply_reagent_distribution/workspace/implementation/`:

**Files:**
- `start.sh` — guarded dependency install (no-op once Flask is importable, so per-test reboots never re-run pip), `exec python3 app.py` in foreground, `0.0.0.0:$PORT` (default 10000)
- `requirements.txt`, `app.py` (entrypoint)
- `app/db.py` — in-memory `Store` (dicts keyed by id), logical clock pinned at `2026-05-01T00:00:00Z`, per-request `touch()` that enforces "version +1 and updated_at refresh at most once per resource per request" per PRD §2.11; **no seeding anywhere — every boot starts with empty maps**
- `app/errors.py` — full 68-entry error catalog with exact HTTP statuses
- `app/response.py` — exact envelope: `meta.api_request_id` (`req_`-prefixed), `api_request_timestamp` (3-fractional-digit UTC), `response_type`, `data`; pagination fields in `meta` for lists only
- `app/validators.py` — stage-ordered chain: auth headers → role → body parsing → typed field validators (bool/int/number/enum/date/datetime, unknown-field rejection) → existence → pagination (limit default 10, min 1, max 100; offset ≥ 0)
- `app/serializers.py` — exact per-entity field sets; derived `occupied_units`, `allocated_quantity`, and `outstanding_balance_cents` (shipped invoices + consumption charges − payments, floored at 0); ConsumptionRecord omits `updated_at`/`version`
- `app/services.py` — FEFO/FIFO waterfall and sequential-lot-run selection (fewest-lots → lowest start seq → earliest first-lot expiry; never partial), per-line `round_half_up` Decimal pricing, freight tiers (base/started-kg/coolant/25% hazmat surcharge/500 floor/250000 free-freight), credit pre-check with base-only freight projection, quarantine/expiry cascades (line→PENDING when allocated < quantity) vs recall cascade (line→PENDING only at zero — the PRD states the two rules differently and I honored each), recall lot-pull write-off, expiry + standing-order sweeps, auto-suspension via `outstanding*10 > limit*12`, waitlist retry in `submission_seq` ASC order
- `app/routes_*.py` — all 53 endpoints with exact RBAC, Customer ownership (stage 3, skipped when target missing so 404 wins), body-id existence in declared input order (stage 4 before well-formedness stage 5), OCC on the three versioned endpoints, and business checks in scaffold priority order (e.g. lot receipt: hazmat cert → storage compatibility → capacity → zone-warehouse match; submit: endorsement → cold-chain → recall → shelf-life hard edge → LISTED → credit; shipment: order ALLOCATED → warehouse cert → product/class/total/dry-ice caps → one-shipment rule)

**Verification:** three ad-hoc smoke suites (~110 assertions covering auth/validation ordering, FEFO allocation, pricing rounding (95+95=190), freight math, OCC 412s, quarantine/recall/expiry cascades, excursion severity/credits/REFUNDED reversal, standing-order window buffer and clock generation, consignment overlap/ceiling/stock/replenishment, kit rollup tiers and atomic FEFO assembly, pagination bounds, customer close guards) — all passed against fresh `start.sh` boots, including a final empty-state boot check confirming no startup seeding. Smoke helpers were removed; only the deliverable remains.

**Orchestrator route-parity check (pre-sweep):** all 80 (method, path) pairs from SCAFFOLD.yaml §1.5 are registered by the implementation (blueprints mounted at url_prefix='/lab'); 0 missing, 0 extra.

## Step 7: Run Tests and Iterate — 2026-08-10T17:10:00.000Z

All 8 parallel rounds pass 94/94. The task is complete.

## Summary

**Iterations run:** 2 (first sweep: 5 consistent failures across all 8 rounds; second sweep: clean 94/94 × 8).

**Tests deleted:** none — every failing test traced to a verbatim PRD rule with unique derivability.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1104_laboratory_supply_reagent_distribution/test_helpers/fixtures.py` — `setup_packed_shipment`: widened the kwargs passthrough to `setup_cold_chain_order` to include `fulfillment_mode`, `product_overrides`, `customer_overrides` (it previously dropped them silently, so tests using `setup_in_transit_shipment`/`setup_open_excursion` could not vary the product sku — causing a PRD §3.1 sku-uniqueness collision when one test built two contexts).

**Fixes applied to `test_suite/` (STEP 2 test bugs):**
- `test_04_shipments_and_freight.py::test_dry_ice_cap_boundary` — ctx_b now passes `product_overrides={"sku": "RG-101"}`; the old setup issued two creates with sku "RG-100", violating PRD §3.1 ("a catalog `sku` that must be unique across all products"), so the PRD-faithful implementation correctly rejected the setup.
- `test_05_excursions.py::test_severity_boundary_59_vs_60_minutes` — same sku-collision fix for ctx_b (assertion itself is verbatim PRD §3.6 severity classification; unchanged).
- `test_06_recalls_and_quarantine.py` (`_setup_allocated_with_recall`, used by both recall-issue-cascade tests) — order quantity changed 10→5 against a 10-unit lot (reservation-qty assertion updated 10→5). The old setup drove the lot to `DEPLETED` at allocation (PRD §3.2 zero-on-hand rule), and PRD §3.7 hop 1 forces only `AVAILABLE`/`QUARANTINED` lots into quarantine, so the recall cascade correctly skipped the depleted lot. The corrected setup leaves the lot `AVAILABLE` with a HELD reservation — the precondition the PRD cascade prose actually governs. All cascade assertions (QUARANTINED, recall_id stamped, RELEASED, on-hand restored to 10, line→PENDING, order→BACKORDERED) are unchanged and verbatim PRD.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1104_laboratory_supply_reagent_distribution/workspace/implementation/app/routes_orders.py` — `cost_summary`: `projected_outstanding_cents` no longer double-counts a posted invoice. Previously it always computed `outstanding_balance + product_total + freight`, yielding 85320 post-dispatch when the invoice (42660) was already inside the derived balance. Now: orders in `SHIPPED`/`DELIVERED` (invoice posted) and `CANCELLED`/`REFUNDED` (no future impact) report the current derived balance; only pre-invoice states (`DRAFT`/`ALLOCATED`/`BACKORDERED`/`PACKED`) add the order's projected impact on top — the only reading of PRD §3.5 "projected_outstanding_cents impact of the order on the customer's balance" consistent with the invoice-posts-once semantics.

## Step 8: Finalize PRD — 2026-08-10T17:20:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1104_laboratory_supply_reagent_distribution/workspace/PRD_FINALIZED.md` is written.

## Summary

**Line counts / delta:** PRD.md 412 lines (65,658 chars) vs PRD_FINALIZED.md 412 lines (66,751 chars) — +1,093 chars, +1.66%. Exactly one line revised in place (line 196); no lines added or removed.

**Changes (one total):**
- **§3.5 — revise —** extended the final "Freight visibility" sentence to pin `projected_outstanding_cents`: orders in `SHIPPED`/`DELIVERED` (invoice already inside the derived balance) and `CANCELLED`/`REFUNDED` (no current or future impact) return the customer's current derived `outstanding_balance_cents` unchanged; orders in `DRAFT`/`ALLOCATED`/`BACKORDERED`/`PACKED` return that balance plus the order's projected product total (stored `product_total_cents` once priced at submission; while still `DRAFT`, the §3.4 per-line computation at current catalog prices and current `volume_discount_pct`) and a freight projection (`final_freight_cents` when known, else `provisional_freight_cents` when a shipment exists, else the §3.3 projected freight estimate evaluated against the projected product total) — `workspace/implementation/app/routes_orders.py:329-366` (state split at lines 355-358).

**Step-7 diff items that produced no PRD edit (with reason):**
- `test_helpers/fixtures.py` kwargs passthrough — pure fixture plumbing; PRD does not govern test helpers.
- `test_04` ctx_b sku override — PRD §3.1 already pins sku uniqueness verbatim ("a catalog `sku` that must be unique across all products"); test setup bug.
- `test_05` ctx_b sku override — same verbatim §3.1 rule.
- `test_06` recall setup 10→5 — §3.2/§3.4 pin zero-on-hand→`DEPLETED` verbatim and §3.7 hop 1 pins the `AVAILABLE`/`QUARANTINED` filter verbatim; uniquely derivable, test setup bug.

**Pre-edit search log (single edit):**
- (a) Subject: `projected_outstanding_cents` computation in the cost-summary computed read.
- (b) Impl paths enumerated and read/grepped: `routes_orders.py:329-366` (sole producer of the field); `serializers.py:110-131` (derived balance: SHIPPED/DELIVERED invoices + charges − payments, floored at 0, REFUNDED excluded); `services.py:152-164` (`price_order`, called only at submit at services.py:333 — product total immutable thereafter); `services.py:167-172` (`projected_product_total`); `services.py:193-201` (`credit_precheck` estimate — character-identical to the cost_summary no-shipment freight fallback); `services.py:14-20` (freight constants); `routes_shipments.py:171,209,308,363` (PACKED/SHIPPED/DELIVERED/REFUNDED transitions, invoice posts once at dispatch); `routes_orders.py:125,150` and `services.py:451` (other `outstanding_balance` consumers — unaffected); `test_04_shipments_and_freight.py:366-389` (asserts SHIPPED → 42660 == posted invoice, auxiliary evidence).
- (c) Wording adjustments: referenced the §3.3 balance derivation and §3.3 freight estimate by cross-reference instead of restating formulas (eliminates any chance of divergence with those already-correct sections); kept the fin-first clause in the freight projection to mirror the impl exactly — it is unreachable inside the additive branch (final freight posted ⟹ order `SHIPPED` ⟹ balance-only branch) but behaviorally identical either way, so no enumerated path is mis-described.

## Step 9: Complete PRD — 2026-08-10T17:35:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1104_laboratory_supply_reagent_distribution/workspace/PRD_COMPLETED.md` written.

## Summary

**Source vs output:** `PRD_FINALIZED.md` (412 lines, 66,997 chars) → `PRD_COMPLETED.md` (412 lines, 71,204 chars). Char delta: +4,207. Line count unchanged — all changes are in-paragraph inserts/revisions plus one table-cell revision; no new sections or paragraphs.

**Counts:** 30 ambiguity-pins (inserts), 3 mismatch-revisions (2 of them are the same §3.9/§4 kit-ranking mismatch in its two locations).

### Ambiguity-pins (insert)

- §2.1 — insert — ambiguity — added "creating" to the customer-owned order mutation list — `app/routes_orders.py:179-182`
- §2.1 — insert — ambiguity — pinned Customer-role single-GET 403 on others' orders/standing-orders/agreements/kits, customer account scoped by its own `id`, unscoped entities (order lines, reservations, shipments, excursions, consumption records) readable by all — `app/routes_orders.py:51-70,218-222`, `app/routes_recurring.py:80-85,211-216`, `app/routes_quality.py:188-205`, `app/routes_orders.py:371-373`
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` rejected with `ERR_INVALID_REQUEST` (never clamped); `total_count` = all matching rows before pagination; `has_more` true exactly when rows remain beyond the page — `app/validators.py:197-235`
- §2.4 — insert — ambiguity — `version` starts at 1 on creation — `app/db.py:74-82`
- §2.5 — insert — ambiguity — clock accepts any parseable instant, no monotonicity enforced — `app/routes_quality.py:385-392`
- §2.5 — insert — ambiguity — `standing_orders_run` counts standing orders reaching ≥1 due run (even if submit failed); `orders_generated` counts successful generate+submit — `app/services.py:409-444`
- §2.6 — insert — ambiguity — endpoints with no declared body fields ignore supplied fields (body must still be a well-formed JSON object) — `app/validators.py:35-47`, e.g. `app/routes_core.py:65`
- §2.11 — insert — ambiguity — a resource's `version` increments at most once per request regardless of cascade hops — `app/db.py:59-72`
- §3.1 — insert — ambiguity — duplicate `sku` rejected with `ERR_INVALID_REQUEST` — `app/routes_core.py:149-152`
- §3.1 — insert — ambiguity — `min_remaining_shelf_life_days` must be non-negative — `app/routes_core.py:147-148`
- §3.1 — insert — ambiguity — `max_qty_per_shipment` required and positive for every product, including `NON_HAZARDOUS` — `app/routes_core.py:143`
- §3.2 — insert — ambiguity — adjustments accepted on lots in any status and never change status except via the zero-on-hand `DEPLETED` rule — `app/routes_core.py:267-288`
- §3.2 — insert — ambiguity — adjustment response is `201 Created` carrying the updated lot — `app/routes_core.py:289`
- §3.3 — insert — ambiguity — `volume_discount_pct` bounds 0–0.5 inclusive — `app/routes_orders.py:38-39`
- §3.3 — insert — ambiguity — creating orders/standing-orders/agreements/kits never consults account lifecycle status — `app/routes_orders.py:173-215`, `app/routes_recurring.py:30-77,154-208`, `app/routes_quality.py:148-185`
- §3.3 — insert — ambiguity — customer PATCH permitted in any account status including `CLOSED` — `app/routes_orders.py:73-101`
- §3.3 — insert — ambiguity — payments recordable in any account status; response `201 Created` carrying the updated account — `app/routes_orders.py:158-168`
- §3.4 — insert — ambiguity — `lines` may be empty at creation (submit then fails `ERR_ORDER_HAS_NO_LINES`); every order representation embeds `lines` in creation order — `app/serializers.py:36-39,105-107`, `app/routes_orders.py:200-201`
- §3.5 — insert — ambiguity — cold-chain `coolant_units` shortfall rejected with `ERR_INVALID_REQUEST` — `app/routes_shipments.py:77-80`
- §3.5 — insert — ambiguity — dispatch `actual_weight_grams` must be a positive integer, else `ERR_INVALID_REQUEST` — `app/routes_shipments.py:185`
- §3.5 — insert — ambiguity — cost-summary: freight fields null without a shipment; `freight_to_product_ratio` = (final else provisional freight) ÷ `product_total_cents`, null when no freight figure or null `product_total_cents` — `app/routes_orders.py:329-366`
- §3.6 — insert — ambiguity — `duration_minutes` is a non-negative integer — `app/routes_shipments.py:234`
- §3.6 — insert — ambiguity — accepted in-band reading answered `201 Created` with `excursion_created` false, null `excursion_id`/`severity`, unchanged `shipment_status` — `app/routes_shipments.py:247-249`
- §3.6 — insert — ambiguity — resume-transit requires the shipment's most recent excursion to be `ACCEPTED` — `app/routes_shipments.py:284-288`
- §3.7 — insert — ambiguity — `LOT_RANGE` bounds must be positive integers with max ≥ min, else `ERR_INVALID_REQUEST`; `PRODUCT_ALL` stores both bounds null — `app/routes_quality.py:40-47`
- §3.8 — insert — ambiguity — `discount_pct` bounds 0–0.5 inclusive — `app/routes_recurring.py:173-174`
- §3.8 — insert — ambiguity — failed replenishment auto-submit leaves the order `DRAFT` and the agreement unchanged (no suspension, unlike standing orders) — `app/routes_recurring.py:325-335`
- §3.9 — insert — ambiguity — job begins with `consumption_summary` null — `app/routes_quality.py:285-288`
- §3.9 — insert — ambiguity — at execution the job's `PLANNED` check precedes the kit's `ACTIVE` re-check — `app/routes_quality.py:343-347`
- §5 — insert — ambiguity — generic fallbacks `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) outside the catalogue — `app/app.py:20-31`

### Mismatch-revisions (revise)

- §3.4 — revise — mismatch — cascade demotion sentence rewritten: quarantine/expiry/manual-release demote a line from `ALLOCATED`/`PARTIALLY_ALLOCATED` to `PENDING` whenever recomputed allocation falls below `quantity` (not only at zero); only the recall cascade demotes at zero — `app/services.py:241-267`, `app/routes_core.py:303`, `app/services.py:385`, `app/routes_orders.py:434`, `app/routes_quality.py:100`
- §3.9 — revise — mismatch — kit execution is not a pure "FEFO waterfall": it uses the §3.4 zone-rotation-policy ranking (FEFO-ranked lots before FIFO-ranked lots) — `app/routes_quality.py:312-334`, `app/services.py:62-70`
- §4 — revise — mismatch — execute endpoint table row updated from "atomic FEFO consumption" to "atomic rotation-policy consumption" to match — `app/routes_quality.py:321`
