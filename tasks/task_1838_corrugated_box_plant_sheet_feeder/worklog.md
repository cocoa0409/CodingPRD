# Worklog — task_1838_corrugated_box_plant_sheet_feeder

## Step 1: Create Task Directory — 2026-08-14T19:46:00.000Z

Task directory `tasks/task_1838_corrugated_box_plant_sheet_feeder/` and `workspace/` pre-created by the invoking pipeline (index assigned externally; no scan performed per instructions).

## Step 2: Generate Scaffold — 2026-08-14T20:37:48.751Z

Done. All three scaffold artifacts for task 1838 (Corrugated Box Plant & Sheet Feeder) are generated and lint-clean.

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1838_corrugated_box_plant_sheet_feeder/SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1838_corrugated_box_plant_sheet_feeder/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`, 18 instances (2 per rule × 9 rules)
- `/home/ubuntu/github/CodingPRD/tasks/task_1838_corrugated_box_plant_sheet_feeder/SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`, 44 active instances + 4 `excluded_because` stubs across all nine guide sections

**Design summary:**
- **Complexity profile:** pricing_engine (primary) × temporal_windowing (secondary); flat FK topology; branching state shape (BoxOrder die-cut vs slotted fork) plus a cyclic InventoryProgram replenishment loop; segregation_of_duties role model (claim filer ≠ adjudicator); immediate consistency. Layers: optimistic_concurrency, cascading_side_effects, derived_field_reconciliation, rate_threshold_triggers.
- **Surface:** 10 entities, 45 endpoints (every one load-bearing — all 12 FKs reverse-reachable), 28 error codes, 8 calculation rules, 10 state machines, 1 OCC concurrency rule (`quote-create-stale-order` on BoxOrder.version).
- **Rule highlights:** dual variants = provisional quote vs final invoice totals (1284.12 → 1348.33 on produced 2100) and claim filing vs resolution credit (255.80 → 704.64); combinatorial modes (a) tiered freight/routing/color interaction and (c) discount tier keyed on merchandise-only with pinned evaluation order (25080.21 vs wrong-key 24760.20); cascades = ship→program→replenishment-order (depth 3) and shift-cancel→run→order (depth 2); overlap rules = corrugator half-open adjacency vs converting append-after-latest with 15/45-min ink changeover gap; invariants = program stock (on_hand = available + committed) and shift minutes (capacity = scheduled + available). All formula-derived asserts were pre-computed with Decimal/ROUND_HALF_UP.
- **Fixes made during self-review:** trim-waste gate moved from per-attach to run-completion (multi-order runs must be buildable incrementally); added the missing priority-4 "shift must be OPEN" validation row; quoted `$.data[N]` capture paths and converted bracketed `grounds` entries to block form for YAML compliance.

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (45 endpoints, 10 entities, 18+44 instances, 494 calls scanned.) Supplementary checks also passed: instance-name uniqueness across both files, grounds resolvability (calculations/transitions/errors/validations/roles/concurrency rules), stub references, and zero forbidden concurrency vocabulary.

## Step 3: Copy Shared Files — 2026-08-14T20:38:09.774Z

Copied `./INSTRUCTION.md` to `tasks/task_1838_corrugated_box_plant_sheet_feeder/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T20:42:53.132Z

All contracts verified. PRD is written to `/home/ubuntu/github/CodingPRD/tasks/task_1838_corrugated_box_plant_sheet_feeder/workspace/PRD.md`.

## Summary

Generated a PRD from the corrugated box plant scaffold. The document is structured as:

- **§1 Introduction** — 2 paragraphs framing the plant's tightly coupled quote-to-cash-to-claims chain
- **§2 Global Specifications** — 8 subsections covering RBAC (with `Customer` as `entity_backed:CustomerAccount`, all others opaque), response envelope (verbatim §2.2), pagination, common resource properties + logical clock, precision/rounding, OCC on quote creation, validation priority ordering (9 priority levels explicitly enumerated), and derived-field reconciliation
- **§3 Business Logic** — 8 domain-grouped subsections: customers/credit/master data, quoting pipeline, pricing engine (freight tiers, color surcharge, routing multiplier, volume discount), corrugator shifts/runs/trim, sheet-feeder flow + converting bookings, invoicing/cancellation cascades, inventory programs/releases/replenishment, quality claims with segregation of duties
- **§4 Endpoint table** — 4 columns (Method, Path, Description, Authorized Roles), 41 rows
- **§5 Error catalogue** — 2 columns, 28 rows

**Hard-contract verification results:**

- **Contract 1 (Field-Name Coverage):** 81 required names (entity fields + request_body + query_params + path_params + `expected_order_version` OCC field + `limit`/`offset`), all present in backticks. Three initial gaps (`order_id`, `program_id`, `status`) were repaired inline in natural narrative locations.
- **Contract 2 (Rule Coverage):** all 28 error IDs present; all 27 state enum values present; all enum members (`B`/`C`/`E`/`BC`, `DIE_CUT`/`SLOTTED`, `INTERNAL`/`SHEET_FEEDER`, `CORRUGATOR`/`DIE_CUTTER`/`FFG`, `TRANSIT_DAMAGE`/`BOARD_WARP`, `LOCAL`/`REGIONAL`/`NATIONAL`, `CREDIT`/`REJECTED`) present; all constants (150.00/400.00 mi, 18.00/32.00/47.00 tier rates, 1.50 color surcharge, 1.12 die-cut multiplier, 5000.00/20000.00 discount tiers, 0.02/0.04 percentages, 8.0 in trim limit, 2.0% warp floor, 500.00 freight cap, 15/45-minute changeover gaps) embedded in prose.
- **Contract 3 (§3 Path Purity):** 518 backtick tokens scanned in §3, zero path tokens, zero bare HTTP methods, zero method+path combos.
- **§2.2 verbatim check:** byte-identical to `section-2.2-response-structure.md`.

The withheld `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not opened or referenced.

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1838_corrugated_box_plant_sheet_feeder/workspace/PRD.md`

## Step 6: Generate Implementation — 2026-08-14T20:55:25.511Z

The server boots cleanly via `start.sh`, binds 0.0.0.0, and responds correctly. Implementation is complete.

## Summary

Created a complete Python + Flask REST API implementation in `/home/ubuntu/github/CodingPRD/tasks/task_1838_corrugated_box_plant_sheet_feeder/workspace/implementation/`:

**Files created:**
- `start.sh` — guarded pip install + `exec python3 app.py`, reads `$PORT`, binds `0.0.0.0`
- `requirements.txt` — `flask>=3.0,<4`
- `app.py` — Flask entry, error handlers, blueprint registration
- `db.py` — in-memory store, empty at boot (no seeding)
- `errors.py` — full error catalog with exact scaffold error_ids and HTTP statuses
- `response.py` — scaffold envelope (`meta.api_request_id`, `meta.api_request_timestamp`, `response_type`, `data`; list meta includes `limit/offset/total_count/has_more`)
- `middleware.py` — `X-User-ID` / `X-User-Role` auth + role gating
- `util.py` — Decimal helpers (round2/round4 half-up), time helpers, logical-clock default `2026-08-01T00:00:00Z`
- `services/clock.py` — logical clock state
- `services/calcs.py` — pricing engine (PROVISIONAL + FINAL variants), freight tiers, volume discount, trim/capacity/balance/exposure rollups, reorder threshold check
- `services/cascade.py` — shift-cancel cascade, run-cancel cascade, booking-cancel revert, auto replenishment order creation
- `services/serialize.py` — JSON-safe entity serializers (Decimals → floats)
- `routes/clock.py`, `customers.py`, `board_grades.py`, `box_orders.py`, `quotes.py`, `work_shifts.py`, `corrugator_runs.py`, `converting_bookings.py`, `inventory_programs.py`, `quality_claims.py`

**Behaviors verified end-to-end:**
- Auth (401/403), ownership check on customer writes (ERR_OWNERSHIP_MISMATCH)
- Full commercial pipeline: customer → grade → order → quote (OCC on `expected_order_version`) → accept (expiry / grade-active / credit-limit) → invoice
- Production pipeline: shift → run (half-open overlap, adjacency allowed) → attach (trim fit) → complete (trim waste ≤ 8.0) → converting booking (machine compatibility, append-after-latest with 15/45-min ink changeover gap) → start → complete (±10% overrun) → invoice → exposure returns to 0
- Sheet-feeder branch (mark-sheets-received) with `ERR_BOARD_SOURCE_MISMATCH` on corrugator attach
- Shift-cancel cascade: runs/bookings cancelled, orders reverted, trim and capacity recomputed
- Inventory programs: receipts, releases (ownership + ACTIVE-only create), approve, ship (decrement + reorder threshold flip + auto-DRAFT replenishment BoxOrder with `board_source=INTERNAL`, `quantity=replenishment_qty`), suspend/reactivate
- Quality claims: per-box price snapshot at filing, warp threshold (≥2.0), SOD check on resolve, freight reimbursement capped at $500
- Logical clock via `POST /api/_clock/set_current_utc` driving quote expiry (transitions quote → EXPIRED + returns `ERR_QUOTE_EXPIRED`)
- Pagination (`limit`/`offset`/`total_count`/`has_more`), filters, all responses in the scaffold envelope

No entity seeding at startup; every record builds through the declared API surface.

## Step 5: Generate Unit Tests — 2026-08-14T21:14:43.310Z

The test suite is fully generated and statically validated. A live verification run against the existing implementation is executing in the background with per-test-server isolation; I've armed a monitor and a results-waiter that will notify me when it finishes, at which point I'll confirm results and update the worklog.

Status so far:
- `test_helpers/` (9 files): types, api_client (37 endpoint methods), api_errors (28 errors registered), assertions, factories, constants, test_users (with entity-backed `make_customer_headers`), fixtures (composite pipelines through INVOICED and claim UNDER_REVIEW), barrel export.
- `test_suite/` (8 files, 80 tests): all 18 difficulty instances × 2 tests, all 44 non-stub corner instances × 1 test, 4 excluded stubs correctly untranslated (cross-refs verified resolvable).
- Audits passed: tag coverage vs both YAMLs, exactly one terminal `Design:` line per test at docstring end, 117 quoted citation spans verified verbatim against PRD.md, no skip/xfail, no scaffold references, pytest collection clean (80 tests).

(Step 5 postscript: the generating subagent's own live verification run completed 0/0/80-errors — all errors in the runner's server-restart setup phase due to host contention with a concurrent unrelated pipeline sweep, not assertion failures. Subagent was instructed to stand down; Step 7 owns the run-diagnose-fix loop.)

## Step 7: Run Tests and Iterate — 2026-08-14T21:25:03.813Z

## Summary

**Iterations run:** 3 sweeps (8 parallel rounds each)
- Sweep 1: 65/80 in all 8 rounds — 15-test union of failures, fully deterministic (no flakiness).
- Sweep 2: 79/80 in all 8 rounds — 1 remaining failure.
- Sweep 3: **80/80 in all 8 rounds — clean exit.**

**Tests deleted:** none. Every failing assertion traced to a PRD-verbatim rule; all failures were test-artifact bugs, not coverage/derivability problems.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1838_corrugated_box_plant_sheet_feeder/test_helpers/constants.py` — added `SHIP_DATE` ("2026-08-12"), `REORDER_POINT` (100), and `REPLENISHMENT_QTY` (500) to `TEST_DEFAULTS`. `fixtures.py::create_release` reads `TEST_DEFAULTS["SHIP_DATE"]` and `create_inventory_program` reads the other two, but only `factories.py::DEFAULTS` defined them — a missing-constant fixture bug that produced `KeyError: 'SHIP_DATE'` in 13 tests (all of test_05's release/program scenarios plus `test_01::test_children_reverse_reachable_via_subresource_lists` and `test_07::test_sales_rep_cannot_approve_release`).

**Fixes applied to `test_suite/`:**
- `test_01_order_creation_and_catalog.py::test_order_without_ink_colors_defaults_empty_and_no_surcharge` — the test intended to exercise the PRD 3.2 server-side default ("optionally `ink_colors`... defaulting to empty"), but the shared `create_box_order_payload` factory injects `["BLACK", "RED"]` whenever the caller doesn't override it, so the request never omitted the field. Rewrote the test to build the payload and `del payload["ink_colors"]` before posting, making the test actually express the PRD rule.
- `test_05_inventory_programs.py` — added `assert_msf` to the `test_helpers` import list; `test_replenishment_flip_auto_creates_draft_box_order` called it (lines 136-137) without importing it (`NameError`).

**Fixes applied to `implementation/`:** none — the implementation was already PRD-faithful for every exercised rule.

## Step 8: Finalize PRD — 2026-08-14T21:29:54.396Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1838_corrugated_box_plant_sheet_feeder/workspace/PRD_FINALIZED.md` is written (258 lines, byte-identical to PRD.md — `diff` confirms no differences).

## Summary

**Line counts:** PRD.md 258 lines; PRD_FINALIZED.md 258 lines; delta 0 lines (0.0%).

**Changes:** none. Every `<step_7_diff>` item traced to a pure test/fixture artifact bug; in each case the implementation's behavior is already uniquely determined by existing PRD prose, so the correct minimal patch is the identity copy. Step 7's own record supports this: no tests deleted, no `implementation/` fixes, and Sweep 3 finished 80/80 across all 8 rounds against the unmodified implementation.

**Per-item investigation log** (subject → impl paths enumerated/read → wording adjustment):

1. **`test_helpers/constants.py` — added `SHIP_DATE`, `REORDER_POINT`, `REPLENISHMENT_QTY` to `TEST_DEFAULTS`.**
   (a) Subject: required fields and validation on program creation (`reorder_point`, `replenishment_qty`) and release creation (`requested_ship_date`).
   (b) Paths enumerated: `implementation/routes/inventory_programs.py:42-67` (both fields required via `require_fields`; `reorder_point` int ≥ 0, `replenishment_qty` int > 0), `:171,176-177` (release requires `qty` + `requested_ship_date`, ISO-validated), `services/calcs.py:202-220` (threshold check consumes `reorder_point`), `services/cascade.py:38` (`quantity = program["replenishment_qty"]`), `services/serialize.py:139-140,154`. Also read `test_helpers/fixtures.py:280-326` and `factories.py:121-145` confirming the failure was a `KeyError` in fixture setup, before any HTTP request.
   (c) No edit — PRD §3.7 already pins all of this verbatim ("creates a program with … `reorder_point` (zero or greater …), and `replenishment_qty` (strictly positive)"; "The request carries `qty` and `requested_ship_date`"). The constant values (100, 500, "2026-08-12") are test-data choices, not server behavior; the fix revealed a fixture bug, not PRD silence.

2. **`test_01…::test_order_without_ink_colors_defaults_empty_and_no_surcharge` — rewrote to `del payload["ink_colors"]`.**
   (a) Subject: server-side default when `ink_colors` is omitted on box-order creation, and its downstream effects (`color_count`, pricing surcharge, booking ink snapshot, serialization).
   (b) Paths enumerated: `implementation/routes/box_orders.py:65` (`body.get("ink_colors", [])`), `:80-84` (list-of-strings validation), `:127-128` (stores `list(ink_colors)`, `color_count = len(ink_colors)`); `services/calcs.py:76-77` (surcharge = `1.50 * color_count` → 0 when empty); `routes/converting_bookings.py:90,100,119` (ink-set snapshot for the changeover rule); `services/serialize.py:83,124`; plus the replenishment auto-order's empty `ink_colors` at `services/cascade.py:42-43`.
   (c) No edit — PRD §3.2 already says "optionally `ink_colors` (a set such as [BLACK, RED], defaulting to empty)" and defines `color_count` as "the number of entries in `ink_colors`"; §3.3 pins the per-entry surcharge, so omitted → empty → zero surcharge is fully determined. The fix corrected the shared factory masking the omission; the implementation was already PRD-faithful on every `ink_colors` path.

3. **`test_05_inventory_programs.py` — added `assert_msf` to the import list.**
   (a) Subject: the auto-created replenishment DRAFT box order's field set (the test body that hit the `NameError`).
   (b) Paths enumerated: `implementation/services/cascade.py:20-58` (auto-create: copies `customer_id`/`board_grade_id`/`routing_type`/`blank_width_in`/`blank_length_in`, `quantity = replenishment_qty`, `board_source = INTERNAL`, `sheet_supplier_name = None`, `ink_colors = []`, `color_count = 0`, `min_ect_required = 0`, area computed per the §3.2 creation rule, invoice fields null, `DRAFT`), triggered from `services/calcs.py:214-216` via ship at `routes/inventory_programs.py:268-272`.
   (c) No edit — PRD §3.7 pins every asserted field verbatim ("the system auto-creates a replenishment box order in `DRAFT` — … `quantity` set to `replenishment_qty`, `board_source` set to `INTERNAL`, `ink_colors` empty, and `min_ect_required` 0"), and §3.2/§2.4 pin the derived fields. The fix was a missing import, a pure test-artifact bug.

**Key finding:** this is a case where Step 7 needed zero PRD alignment edits — all 15 original failures were a single missing-constant fixture bug plus two test-code bugs; the implementation matched PRD-pinned behavior everywhere Step 7 exercised it, so PRD_FINALIZED.md is the PRD unchanged.

## Step 9: Complete PRD — 2026-08-14T21:45:52.303Z

Done. `PRD_COMPLETED.md` produced at `/home/ubuntu/github/CodingPRD/tasks/task_1838_corrugated_box_plant_sheet_feeder/workspace/PRD_COMPLETED.md`.

**Source vs output**: `PRD_FINALIZED.md` 258 lines / 43,935 chars → `PRD_COMPLETED.md` 258 lines / 48,379 chars (+4,444 chars; all edits in-paragraph, no sections added).

**Counts**: 19 ambiguity-pins, 3 mismatch-revisions (22 edits across 21 diff lines).

Changes:

- §2.1 — insert — ambiguity — empty/whitespace-only `X-User-ID` treated as missing (401); header value used stripped — implementation/middleware.py:23-27
- §2.3 — insert — ambiguity — `has_more` true exactly when `offset` + page size < `total_count`; non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` — implementation/response.py:33, implementation/routes/_helpers.py:25-39
- §2.4 — revise — ambiguity — clock set is unconditional (may move backward), malformed `to_iso8601` → `ERR_INVALID_REQUEST`, response data carries `current_utc` as 3-fractional-digit ISO UTC — implementation/routes/clock.py:16-23, implementation/util.py:19-20
- §2.7 — revise — mismatch — restructured priority order to impl's actual sequence: path-id existence → customer-ownership (on customer-facing writes) → request-body well-formedness (`ERR_INVALID_REQUEST`; receipt/release/resolve quantity fields use `ERR_INVALID_QUANTITY`) → body-FK existence → state → safety → business → grade freshness (except at quote acceptance, where expiry precedes it) → temporal → fiscal; added clause that §3 per-endpoint gate sequences fix cross-entity interleaving (attach case) — implementation/routes/box_orders.py:67-92,280-303, implementation/routes/inventory_programs.py:164-189, implementation/routes/quality_claims.py:126-142, implementation/routes/converting_bookings.py:191-211, implementation/routes/quotes.py:31-63, implementation/routes/corrugator_runs.py:141-181
- §2.8 — insert — ambiguity — a recomputation itself mutates the carrier entity (version/updated_at advance even when value unchanged); enumerated the operations that run the credit-exposure rollup; sheets-received marker excluded — implementation/routes/corrugator_runs.py:193-196,227-230, implementation/routes/converting_bookings.py:131-134,181-182,225-228,249-252, implementation/routes/box_orders.py:205-208,213-223,262-263, implementation/services/cascade.py:73-76,95-98
- §3.1 — revise — ambiguity — `account_name`/`ship_to_city` must be non-blank strings — implementation/routes/customers.py:31-34
- §3.1 — revise — ambiguity — `ect_rating_lbs_per_in` and `burst_rating_psi` must be strictly positive integers (not merely positive) — implementation/routes/board_grades.py:46-49
- §3.2 — revise — ambiguity — `quantity` strictly positive integer; `min_ect_required` integer ≥ 0; `ink_colors` a list of color strings — implementation/routes/box_orders.py:72-84
- §3.2 — revise — ambiguity — supplier rule: `SHEET_FEEDER` requires non-blank string; `INTERNAL` requires absent-or-null — implementation/routes/box_orders.py:99-104
- §3.2 — insert — ambiguity — expiry judged only at acceptance, never at quote creation — implementation/routes/box_orders.py:274-344, implementation/routes/quotes.py:35-43
- §3.4 — revise — ambiguity — run `start_minute`/`end_minute` integer minutes since midnight, start ≥ 0, end strictly after start — implementation/routes/corrugator_runs.py:57-60
- §3.4 — insert — ambiguity — `outs` a strictly positive integer — implementation/routes/corrugator_runs.py:149-150
- §3.5 — revise — ambiguity — booking paragraph reordered to impl gate order (state checks before machine compatibility); booking minutes integer pins — implementation/routes/converting_bookings.py:59-87
- §3.5 — revise — mismatch — "latest" booking = greatest `end_minute`; changeover ink comparison is exact ordered-list equality, not set equality ([BLACK,RED] vs [RED,BLACK] → 45 min) — implementation/routes/converting_bookings.py:91-106
- §3.5 — insert — ambiguity — `produced_qty` must be an integer — implementation/routes/converting_bookings.py:195-196
- §3.7 — revise — ambiguity — `reorder_point` integer ≥ 0; `replenishment_qty` strictly positive integer — implementation/routes/inventory_programs.py:64-67
- §3.7 — revise — ambiguity — receipt `qty` strictly positive integer — implementation/routes/inventory_programs.py:125-126
- §3.7 — revise — ambiguity — release `qty` strictly positive integer — implementation/routes/inventory_programs.py:184-185
- §3.7 — revise — mismatch — reorder-threshold check runs after both ships and receipts (a receipt on an `ACTIVE` program with resulting on-hand ≤ reorder_point also flips into `REPLENISHMENT_NEEDED` and auto-creates the DRAFT replenishment order); "post-decrement"/"after a receipt" wording generalized — implementation/services/calcs.py:202-220, implementation/routes/inventory_programs.py:128-131,264-272
- §3.8 — revise — ambiguity — `defective_qty_claimed` strictly positive integer; `measured_warp_pct` on `TRANSIT_DAMAGE` accepted and stored but inert — implementation/routes/quality_claims.py:42-43,62,83
- §3.8 — revise — ambiguity — `defective_qty_verified` must be an integer in [0, produced_qty] — implementation/routes/quality_claims.py:141-152
- §3.8 — insert — ambiguity — `REJECTED` outcome ignores supplied `defective_qty_verified`/`actual_return_freight_dollars` (remain null) — implementation/routes/quality_claims.py:163-165
- §4 — insert — ambiguity — each action endpoint returns the resource its path addresses (attach returns the run, etc.); enumerated exact-match filters per list endpoint; quotes-of-order and claims-of-order listings accept no filters — implementation/routes/box_orders.py:154-160, implementation/routes/corrugator_runs.py:129-135,198, implementation/routes/converting_bookings.py:148-154, implementation/routes/inventory_programs.py:108-114,217

Notable cross-checks that needed no change: endpoint/role table matches `require_roles` on every route; error catalogue matches `errors.py` exactly; pricing engine steps, freight tiers, discount tiers, trim math, overrun band, exposure status set, claim credit math, and all state machines in §3 already match `services/calcs.py` and the route modules verbatim.
