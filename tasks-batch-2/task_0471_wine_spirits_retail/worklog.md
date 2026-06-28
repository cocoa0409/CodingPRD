# Worklog — task_0471_wine_spirits_retail

Scenario: 471. Wine & Spirits Retail (Total Wine style): SKU & vintage/allocation, age-verification & ID scan, case/mixed-case discount, ABC license & purchase-limit compliance, taxed/bonded inventory, special order & club, growler/keg (state rule), delivery & shipping-state restriction

## Step 1: Create task directory — 2026-06-22T11:34:39.000Z

Pre-allocated directory `tasks/task_0471_wine_spirits_retail/` confirmed to exist with `workspace/` subfolder (per orchestration directive; no index scan performed to avoid collision with 4 concurrent runs). INSTRUCTION.md present at project root. All six prd-bench skills present under skills/.

## Step 2: Generate scaffold (Expert tier) — 2026-06-22T11:54:43.000Z

Generated a complete Expert-tier scaffold for **task_0471_wine_spirits_retail** (Wine & Spirits Retail, Total Wine style). All three files written and `scaffold_lint.py` passes with **VERDICT: clean lint** (520 §1.8/§1.9 calls all conform to §1.5; all 13 FKs have reverse-reachability GETs).

**Hard constraint honored:** generated purely from the scenario + skill spec; no sibling `task_*/` directory was read, globbed, or grepped.

### Complexity profile
- **Primary archetype:** compliance_audit; **secondary:** quota_allocation
- **Layers:** optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, derived_field_reconciliation
- **Topology:** flat (FK-linked peers); **state shape:** parallel (Order's payment × fulfillment dimensions) + cyclic (SpecialOrder negotiation) + branching (Shipment); **role model:** peer_roles

### SCAFFOLD.yaml (§1.0–§1.7)
- **12 entities:** Product, Vintage, InventoryLot, Customer, IdScan, Order, OrderLine, ClubMembership, SpecialOrder, Shipment, StateRule, ComplianceWindow
- **7 state machines** (Order has two parallel dimensions; SpecialOrder is cyclic QUOTED↔COUNTERED; Vintage has SOLD_OUT↔RELEASED auto-transitions; Shipment branches DELIVERED/RETURNED)
- **1 concurrency rule** (OCC on Order.version for submit, CREATE-with-supersede allocation draw)
- **11 calculations** including dual-variant provisional vs settled totals (excise/tax interaction), case/mixed-case discount with pinned per-component-then-sum rounding, customer risk scoring, club tier, monthly ABC volume
- **14 ordered validations** (auth → ownership → existence → state → OCC → safety → referential → constraint → field)
- **62 endpoints** (35 POST transition/business, 26 GET incl. all FK reverse-reachability, 1 DELETE; default clock `2026-01-01T00:00:00Z`)
- **24 error codes**, **5 roles** (Customer entity-backed; StoreAssociate/ComplianceOfficer/Admin/Anonymous opaque)

### Design files
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml:** 9 rule_ids × 2 = **18 instances**, all with computed literal asserts (e.g., provisional 27349 vs settled 27864; discount 143 from pinned rounding; allocation cap, ABC volume `>`-not-`>=` boundary)
- **SCAFFOLD_CORNER_DESIGN.yaml:** 9 sections, **45 instances** (40 active + 5 `excluded_because:` stubs, all resolving to named §1.8 instances)
- All instance names unique across both files; all formula-derived asserts verified by executing the calculation formulas in Python.

## Step 3: Copy shared files — 2026-06-22T11:55:02.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0471_wine_spirits_retail/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-22T12:01:40.000Z

Generated PRD at `workspace/PRD.md` (~307 lines / ~50 KB) for the Wine & Spirits Retail API.

**Confirmation on withheld files:** did NOT read `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`. Read only `SKILL.md`, `SCAFFOLD.yaml`, `section-2.2-response-structure.md`, and `example-prd.md`.

**Section structure:**
- §1 Introduction — dual-pricing / multi-channel compliance framing.
- §2 Global Specifications — RBAC (5 roles), verbatim §2.2 envelope, Pagination, Common Resource Properties (IdScan/ComplianceWindow carry only id/created_at), Cascades, Nested Retrieval, Monetary Precision, Logical Clock, OCC, global Validation Ordering.
- §3 Business Logic — catalog, customer onboarding & ID scanning, order build/submit, age & draft-container rules, shipping-state & ABC monthly ledger, order pricing (case discount + provisional + settled totals), payment/bonded-withdrawal/fulfillment, wine club, special-order negotiation loop, cancel/refund/shipment branch.
- §4 Endpoint Definitions — 4-column table, all 62 endpoints.
- §5 Error Code Catalogue — 2-column table, all 24 error codes.

**Hard Contract results (verified mechanically):**
- Contract 1 (Field-Name Coverage): 71 required identifiers, 0 missing — PASS.
- Contract 2 (Rule Coverage): OCC, case-discount round-per-component, settled-total excise-is-taxable ordering, compliance score boundaries (2→WATCH, 750ml grace), strict monthly-cap `>`, inclusive club thresholds (50000/200000), min_purchase_age=21, single-lot no-split, submit validation priority chain — all expressed; all 24 error IDs in prose; all state/enum values in backticks. No fuzzy words. PASS.
- Contract 3 (§3 Path Purity): 421 §3 backtick tokens scanned — 0 paths/methods/combos — PASS.
- §2.2 matches source byte-for-byte.

## Step 5: Generate unit tests — 2026-06-22T12:27:17.000Z

Generated complete test infrastructure for `task_0471_wine_spirits_retail`, translating only the two design indices (no freelance SCAFFOLD walking).

**test_helpers/ (9 files emitted):**
- `types.py` — entity TypedDicts, status/role enums. IdScan and ComplianceWindow correctly modeled as append-only (id + created_at only; no version/updated_at).
- `api_client.py` — 62 endpoint methods subclassing `GenericApiClient`.
- `api_errors.py` — 24-entry `ApiErrorId` enum + HTTP status map.
- `assertions.py` — per-entity assertions; append-only checkers assert absence of version/updated_at.
- `factories.py` — input-field payload factories per entity.
- `constants.py` — pricing/age/compliance/club/negotiation thresholds + clock constants.
- `test_users.py` — opaque role headers + `make_customer_headers()` per-instance builder for entity-backed Customer role.
- `fixtures.py` — 23 composite helpers (clock, verified-customer, released/allocation-open vintage, full order lifecycle through completed/dispatched/refunded).
- `__init__.py` — barrel export.

**test_suite/ (6 files, 76 tests):** conftest.py + test_01_pricing_and_discounts, test_02_state_machines, test_03_cascades_and_compensation, test_04_submit_compliance_and_inventory, test_05_catalog_crud_and_access, test_06_difficulty_complements.

**Coverage (audited):**
- Queue A (Difficulty): all 18 instances translated, each with ≥2 tagged tests (36 tests total). 0 skipped.
- Queue B (Corner): all 40 non-stub instances translated (40 tests, ≥1 each). 0 skipped. All 5 `excluded_because:` stubs correctly NOT emitted; every stub's `difficulty_instance` cross-reference resolves.
- Every test docstring carries exactly one verbatim `Design:` tag resolving to a real instance; no skip/xfail; all 8 numeric expected values re-derived from PRD §3.6/§3.8 and confirmed. No instances skipped — all 58 non-stub design instances passed the PRD-first two-condition filter.

## Step 6: Generate implementation — 2026-06-22T12:27:17.000Z

Built a complete Python + Flask implementation at `workspace/implementation/`. Generator reports **all 76 tests pass** (exit 0) on two consecutive full runs under `prd-bench-local-run --isolation per-test-server`.

### File list (under `implementation/`)
`start.sh`, `requirements.txt` (flask==3.0.3), `server.py` (entry point), `app.py`, `db.py` (in-memory store), `errors.py` (24 IDs), `response.py`, `middleware.py` (auth + RBAC), `calculations.py` (Decimal money math), `services.py` (derived recompute + cascades), `routes/` (clock, customers, id_scans, catalog, state_rules, orders, shipments, club, special_orders).

### Storage / boot
Flask, single global in-memory `Store` of plain-dict records keyed by UUID. No SQLite/JSON-on-disk/tmp/seeding — empty on every boot. `start.sh` cd's to its dir, guards pip install behind `python3 -c "import flask"`, then `exec python3 server.py`; `server.py` reads `PORT` (default 10000), binds `0.0.0.0`, `threaded=True`. Notable fix caught in smoke testing: a thin `server.py` imports the canonical `app` module so route registration and the served instance share one module identity (running `app.py` directly would create a routeless `__main__` copy).

### Trickier rules
- Dual provisional/settled totals: provisional uses estimated excise 0, tax on discounted subtotal; settled adds verified per-line excise into the taxable base before tax — diverge exactly when a line drew from a BONDED lot.
- Case discount rounding: GROWLER/KEG excluded; full-case units 15%; mixed-case units 10% only when discountable units ≥ 12; each component round_half_up independently then summed.
- OCC: submit requires `expected_order_version == Order.version` else `ERR_STALE_ORDER_VERSION` (412); cart mutations bump version.
- ABC monthly cap: strict `>` rejection (exactly hitting limit allowed); ledger rows deactivated on cancel/refund/return.
- Allocation draw: single-lot (no split), lots tried in created_at order; cap counts customer's committed/fulfilled units of vintage.
- Validation precedence (§2.10): auth → forbidden → not-found → invalid-state → OCC → age → blocked → growler/keg → ship-state → allocation → ABC → inventory.
- Compliance status derived: registration keeps stored CLEAR default; reads + BLOCKED gate compute live (unverified ⇒ score 2 ⇒ WATCH).
- Compensation: TAXED-origin lines credit qty_reserved back; BONDED-origin lines reverse capture-time withdrawal.
- Special-order negotiation: round limit enforced on `counter` (rejected once round_count reaches 3); re-quote at round_count 3 permitted.

## Step 7: Test/fix iteration loop — 2026-06-22T12:30:02.000Z

**Iterations run:** 1 (the initial 8-round parallel sweep passed clean on the first attempt).

**Result:** All 8 concurrent rounds passed 76/76 tests (`passed=76, total=76, failed=0, errors=0, skipped=0` in every round). The union of failing tests across all 8 rounds is empty — no flakiness surfaced. All rounds ran to completion with consistent durations (~48s each) and an identical 76-test set, confirming a stable pass rather than a lucky single round. Orchestrator independently re-verified all 8 results.{1..8}.json: 76/76 in every round.

**Tests deleted:** None. PRD coverage was already correct; no test asserted scaffold-only or non-uniquely-derivable rules.

**Fixes applied to `test_helpers/`:** None required.

**Fixes applied to `implementation/`:** None required.

**Note:** The subagent's first summarization script mis-read the results JSON (keyed on a nonexistent `outcome` field instead of `status`), briefly mis-flagging tests; that was a reporting bug in its diagnostic command, not a test failure. Raw `passed`/`total`/`failed` counters in all 8 files confirm the clean 76/76 sweep.

## Step 8: Finalize PRD — SKIPPED — 2026-06-22T12:30:02.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes (zero iterations beyond baseline). PRD.md already determined every behavior the implementation exhibits, so no PRD_FINALIZED.md is produced. Step 9 will start from PRD.md.

## Step 9: Complete PRD scan — 2026-06-22T12:38:12.000Z

Produced `workspace/PRD_COMPLETED.md` as a minimal in-paragraph patch over `PRD.md` (started from PRD.md since Step 8 was skipped; PRD_FINALIZED.md confirmed absent).

**Line counts:** PRD.md = 306 lines / 50324 chars; PRD_COMPLETED.md = 306 lines / 55055 chars (char delta +4731). Line count unchanged — every change is an in-paragraph insert/revision; no new sections or paragraphs.

**Counts:** 14 changes total — 8 ambiguity-pins, 6 mismatch-revisions.

**Per-change bullets:**
- §2.1 (RBAC) — insert — ambiguity — `GET /orders` does not 403 a Customer; silently scopes to the customer's own orders — routes/orders.py:80-82
- §2.3 (Pagination) — insert — ambiguity — equal-created_at ties broken by stable insertion order; total_count/has_more semantics pinned — app.py:195, response.py:40
- §2.4 (Lifecycle fields) — revise — mismatch — derived-field recompute bumps version/updated_at only on an actual value change (PRD said it always bumps) — services.py:38-46,102-105,150-153
- §2.8 (Logical clock) — insert — ambiguity — clock-set data is `{"current_utc": …}` (not a versioned resource); value normalized to ISO 8601 with 3 fractional digits + Z — routes/clock.py:17-18
- §2.9 (OCC) — insert — ambiguity — absent/non-integer expected_order_version yields ERR_MISSING_FIELD, checked before state/OCC gates — routes/orders.py:196
- §2.10 (Validation ordering) — revise — ambiguity — ERR_EMPTY_ORDER evaluated before business gates; ERR_VINTAGE_NOT_PURCHASABLE placed between blocked-status and growler/keg ban — routes/orders.py:212-235
- §3.1 (Vintage state machine) — insert — ambiguity — a non-DRAFT vintage on release/open-allocation yields ERR_INVALID_STATE first — routes/catalog.py:155-156,176-177
- §3.2 (Registration) — revise — mismatch — register accepts any recognized role (Anonymous canonical), missing/unknown role still 401; DOB/state/email validation errors pinned — routes/customers.py:14-31
- §3.2 (Compliance status) — insert — ambiguity — registration returns stored CLEAR, but GET/list re-derive compliance_status live (fresh unverified reads WATCH) — services.py:132-139, routes/customers.py:58,71-75
- §3.2 (Compliance triggers) — insert — mismatch — compliance_status also recomputed on cancel and shipment-return cascades — routes/orders.py:504, routes/shipments.py:126
- §3.4 (StateRule) — revise — mismatch — upsert returns 201 (not 200), keeps original id/created_at, bumps version, overwrites all four fields; monthly_volume_limit_ml ≥ 1 — routes/state_rules.py:39-46,32-36
- §3.7 (Capture cascade) — insert — ambiguity — "append" reuses earliest-created TAXED lot; minted lot has qty_reserved 0 and excise_band_cents_per_unit 0 — routes/orders.py:405-419
- §3.9 (Special-order rounds) — revise — mismatch — round limit enforced only on counter; quote/re-quote carries no round_count check; price ≥ 1 pinned — routes/special_orders.py:84-100,110
- §3.9 (Conversion) — insert — ambiguity — derived line fields pinned: PENDING, qty=requested_qty, vintage_id null, lot_id null, line_excise_cents 0, unit_price_cents from quote (0 if unset) — routes/special_orders.py:162-185
- §3.10 (Shipment duplicate) — insert — mismatch — no shipment CANCELLED status exists; only a RETURNED shipment does not count toward the one-active-shipment limit — routes/shipments.py:27-29

Left unchanged (intentional): always-0.0725 sales-tax already covered by "defaults to 0.0725"; additive optional list-filter query params and the 500→ERR_INVALID_REQUEST catch-all are extra capability not reinterpretations; abv_pct two-decimal phrasing is descriptive (impl does not round).

---

## PIPELINE COMPLETE — 2026-06-22T12:38:12.000Z

All 9 steps finished (Step 8 skipped per skip condition). Final state: **76/76 tests pass across all 8 stability-sweep rounds.** Deliverables in `tasks/task_0471_wine_spirits_retail/`: SCAFFOLD.yaml + 2 design YAMLs, test_helpers/ (9 files), test_suite/ (6 files, 76 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_COMPLETED.md, implementation/ (Flask, in-memory)}.
