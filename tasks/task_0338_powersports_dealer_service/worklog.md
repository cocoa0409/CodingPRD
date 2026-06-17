# Worklog — task_0338_powersports_dealer_service

Scenario: 338. Powersports Dealer & Service (motorcycle/ATV): unit inventory (VIN) & floor plan, sales & financing, trade-in, service RO & flat-rate, parts/accessories, seasonal prep & storage, warranty/recall, test-ride waiver

Difficulty: Expert (passed to scaffold-generator only)

## Step 1: Create Task Directory — 2026-06-14T02:33:58.000Z

Directory pre-allocated and pre-created by orchestrator command. Skipped index scan/increment per instructions. Ensured tasks/task_0338_powersports_dealer_service/workspace/ exists.

## Step 2: Generate Scaffold (Expert difficulty) — 2026-06-14T03:02:23.000Z

All three required artifacts are in place and pass clean lint. The directory already contained `_pipeline.log`, `worklog.md`, and an empty `workspace/` from prior setup; I did not touch those.

Generated the complete Expert-tier scaffold for **task_0338_powersports_dealer_service** (Powersports Dealer & Service). All three files pass `scaffold_lint.py` with `VERDICT: clean lint` (422 setup/trigger calls scanned, all FKs reverse-reachable).

**SCAFFOLD.yaml** (§1.0–§1.7):
- **15 entities** (Expert band): Customer, Unit, FloorPlanLoan, Curtailment, Deal, TradeIn, Technician, RepairOrder, ServiceLine, Part, PartLine, StorageBay, StorageAgreement, TestRideWaiver, WarrantyClaim. Flat topology (`api_prefix: ""`), 23 FKs each with a filtered-list GET.
- **11 state machines** including a cyclic Deal (DECLINED→QUOTED re-quote loop) and a parallel-dimension RepairOrder (`work_status` × `billing_status` evolving independently).
- **8 calculations**: dual-variant `deal_amount_financed` (provisional vs final lender payoff) and `floor_plan_interest` (simple vs declining-balance) on different entities; combinatorial `ro_labor_total` (tier + warranty branch + shop-supply cap, mode a) and `deal_out_the_door` (two taxable lines, per-line rounding-order pinned, mode b); plus trade-equity, storage-fee, warranty-claim, and curtailment-requirement rules. All literals computed in code.
- **13 validations** (priority-ordered, 8 categories), **35 errors**, **5 roles** (peer-roles model: SalesManager, FinanceManager, ServiceAdvisor, PartsClerk, DealerPrincipal with fiscal override), **70 endpoints** (incl. one `/_clock/set` test-driving endpoint), **2 OCC concurrency rules** (curtailment-vs-loan, part-line-vs-part), both 412.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8): all **9 Difficulty Rules × 2 instances = 18 instances**, each grounded in §1.1–§1.7 with executable `setup_api_calls` chains and pre-computed literal asserts.

**SCAFFOLD_CORNER_DESIGN.yaml** (§1.9): **47 active corner instances + 16 `excluded_because` stubs** (each citing a valid §1.8 instance) across all 9 claim-extraction-guide sections.

**Key fixes during generation**: set `api_prefix` to root so the lint could derive flat-topology collection segments; reshaped the Deal out-the-door calc to two taxable lines for a genuine round-then-sum vs sum-then-round divergence (1381252 vs 1381253); made Deal approve recompute OTD with the final variant so the financed-amount math is consistent (1937900); corrected a warranty-recall claim literal (18000, not 40500); and removed a dead `REVERSED` Curtailment enum value with no producing path. 81 instance names unique; all grounds resolve.

## Step 3: Copy Shared Files — 2026-06-14T03:02:41.000Z

Copied ./INSTRUCTION.md → tasks/task_0338_powersports_dealer_service/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-06-14T03:08:33.000Z

Generated workspace/PRD.md from the scaffold for the Powersports Dealer & Service domain (Expert tier, flat topology, parallel state machines, dual-variant calculations, cascading side effects, OCC).

**Structure:** 5 top-level sections, 22 subsections, ~338 lines. §2 (Global Specs): 10 subsections — RBAC, fixed §2.2 envelope, pagination, common properties, money/precision/per-line rounding, OCC on shared ledgers, left-to-right reference validation, validation order, automatic cascades + parts conservation, test-driving clock. §3 (Business Logic): 12 subsections by lifecycle/domain. §4: 4-column endpoint table (71 endpoints). §5: 2-column error table (35 error IDs).

**Hard Contracts (all PASS):** Contract 1 (Field-Name Coverage) 86/86 identifiers verbatim, 0 missing. Contract 2 (Rule Coverage) verified — both OCC rules, both dual-variant calculations, tiered labor, per-line rounding pinned, declining-interest walk, cascade hops, parts conservation, validation priority ordering. Contract 3 (§3 Path Purity) 503 backtick tokens, 0 slash-prefixed.

**Withheld files confirmation:** Did not read SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml.

## Step 5: Generate Unit Tests — 2026-06-14T03:21:47.000Z

Generated complete test infrastructure for the Powersports Dealer & Service PRD benchmark task.

**Stage 1 — `test_helpers/` (9 files):** types.py (role/status enums + entity TypedDicts; the three append-only ledger lines Curtailment/ServiceLine/PartLine carry only id/created_at). api_client.py (one method per ~70 endpoints). api_errors.py (full error catalogue + HTTP-status map). assertions.py (per-entity + two conservation-invariant checkers). factories.py (per-entity payload factories with unique VIN/email/SKU/label). constants.py, test_users.py (all 5 roles opaque → shared-constant headers only), fixtures.py (composite setups across 8 tiers), __init__.py barrel.

**Stage 2 — `test_suite/` (9 test files + conftest), 83 test functions:** Queue A (Difficulty) **36 tests** — every one of the 18 instances has ≥2 tests. Queue B (Corner) **47 tests** — every one of the 47 non-stub instances has exactly 1 test.

**Coverage audit:** all 18 difficulty instances ≥2 tests; all 47 non-stub corner instances ≥1 test; all 16 `excluded_because` stubs correctly NOT translated. No orphan tags, every test carries exactly one verbatim `Design:` tag, no skip/xfail markers. All files pass py_compile; every test_helpers import resolves.

**Instances skipped:** None. Every non-stub instance from both queues passed the PRD-first two-condition filter.

## Step 6: Generate Implementation — 2026-06-14T03:21:47.000Z

Built a complete Python + Flask implementation of the Powersports Dealer & Service API (expert-tier) at workspace/implementation/.

**Files (23 total):** start.sh (launcher, guarded dep install, `exec python3 app.py`), requirements.txt (flask==3.0.3), app.py, db.py (in-memory store + logical clock + ISO helpers), response.py (envelope PRD 2.2), errors.py, middleware.py (X-User-ID/X-User-Role auth + RBAC), common.py (field stamping, pagination, validators, round_half_up), lookups.py, calculations.py, routes/ (12 modules: misc+customers, units+floor-plan loans, curtailments, trade_ins, deals, technicians, repair_orders, service_lines, parts+part-lines, storage, waivers, warranty).

**Endpoints:** all ~70 endpoints from PRD §4 / scaffold implemented.

**Launcher contract — confirmed:** reads $PORT (default 10000), binds 0.0.0.0, runs foreground via exec. Verified `bash start.sh` boots and serves.

**Storage — confirmed in-memory only:** Python dicts in db.Store, no SQLite/disk/seed. State starts empty each boot.

**Self-verification (77 assertions across 4 smoke suites, all passing):** auth, envelope, version/created_at, deal lifecycle DRAFT→...→DELIVERED with cascades, calculations to the cent (OTD 1381252, RO tiered labor 57500 / warranty 18000, shop-supply $50 cap, simple vs declining interest 100000 vs 75000, storage fee 34900, warranty RECALL vs WARRANTY), OCC 412, schedule/bay conflicts, over-authorization 402 + DealerPrincipal override, waiver expiry, left-to-right ordering, pagination. Note: created_at/updated_at track logical test clock; envelope api_request_timestamp uses wall-clock; list ordering uses created_at + insertion-sequence tiebreak.

## Step 7: Run Tests and Iterate — 2026-06-14T03:30:00.000Z

All 8 parallel rounds pass 83/83 consistently. Orchestrator independently re-ran the 8-round sweep to confirm and regenerate results.{1..8}.json artifacts → all 8 rounds passed=83 failed=0 total=83.

**Iterations run:** 2 (initial sweep surfaced 5 stable failures across all 8 rounds; second sweep after fixes was clean 83/83 × 8).

**Tests deleted:** None. All 5 failing tests passed the PRD coverage + unique-derivability checks (rules verbatim-covered by PRD §3 and uniquely determined).

**Fixes applied to `test_helpers/`:**
- `factories.py` — `unique_vin()`: old generator `("1HD1KB4197YT" + suffix)[:17]` truncated 18→17 chars, silently dropping the last suffix digit; counters 1–9 all produced identical VIN `...YT00000`, so any test creating ≥2 units in one boot hit `ERR_DUPLICATE_RESOURCE`. Changed to 11-char prefix (`1HD1KB4197Y`) + 6-digit suffix = exactly 17 chars, no truncation, every counter distinct. Fixed `test_storage_bay_overlapping_window_rejected` and `test_list_units_pagination_envelope` (failing at setup time).

**Fixes applied to `test_suite/`:**
- `test_07_storage_waiver_warranty.py` — two log-ride tests voided the waiver (→ VOID) then asserted `ERR_UNIT_NOT_RIDEABLE`, but PRD §3.11 says the unit-rideable check runs only "When logging a ride against a `SIGNED` waiver"; with no SIGNED waiver the PRD-faithful outcome is uniquely `ERR_WAIVER_REQUIRED`. Fixed setups to keep the waiver SIGNED against the DELIVERED unit so the unit-rideable safety check genuinely fires; renamed tests and corrected post-condition. Made tests MORE faithful to PRD.

**Fixes applied to `implementation/`:**
- `routes/repair_orders.py` — `cancel_ro()`: the work-status from-state check (`ERR_INVALID_STATE`) ran before the billing-status check. For a WORK_COMPLETE + INVOICED order this returned `ERR_INVALID_STATE`, but PRD §3.6 names `ERR_RO_ALREADY_BILLED` for cancelling an order whose `billing_status` is not UNBILLED. Reordered so the named billing gate is checked first, fixing `test_cancel_after_invoiced_rejected`. (WORK_COMPLETE + still-UNBILLED cancels remain `ERR_INVALID_STATE`.)

## Step 8: Finalize PRD — 2026-06-14T03:34:51.000Z

Produced workspace/PRD_FINALIZED.md (minimal patch of PRD.md scoped to Step 7 fix sites).

**Line counts:** PRD.md = 338, PRD_FINALIZED.md = 338. Delta: 0 lines (+0.0%). One existing paragraph line (§3.6, line 179) revised in place.

**Changes:**
- §3.6 (Repair Order work/billing dimensions) — revise — pinned the check order inside the cancel operation: the billing-status gate (`ERR_RO_ALREADY_BILLED`, fired when `billing_status` ≠ `UNBILLED`) is evaluated before the work-status from-state check, so a `WORK_COMPLETE` + `INVOICED` order yields `ERR_RO_ALREADY_BILLED` rather than `ERR_INVALID_STATE`; a still-`UNBILLED` non-cancellable work state still yields `ERR_INVALID_STATE` — routes/repair_orders.py:203-206.

**Items requiring no PRD edit:** factories.py unique_vin() (pure fixture bug, no PRD silence); test_07 log-ride fix (corrected tests to match already-verbatim PRD §3.11; impl matches §3.11). 

**Pre-edit search log (NO-NEW-MISMATCH):** Edit 1 subject = relative ordering of billing gate vs work from-state in RO cancel. Enumerated routes/repair_orders.py:cancel_ro (Step 7 site, billing first), routes/parts.py:release_part_line (parallel ERR_RO_ALREADY_BILLED site — checks from-state FIRST, opposite order), other RO transitions; grepped ERR_RO_ALREADY_BILLED/ERR_INVALID_STATE/billing_status across routes/. Wording adjustment: scoped the new sentence strictly to "Cancelling a repair order" and "the work-status from-state check" to avoid a universal claim that would mis-describe the part-line release path's opposite ordering.

## Step 9: Complete PRD — 2026-06-14T03:40:36.000Z

Produced workspace/PRD_COMPLETED.md (full PRD-vs-implementation scan, copied from PRD_FINALIZED.md).

**File metrics:** PRD_FINALIZED.md = 338 lines / 52,450 chars; PRD_COMPLETED.md = 338 lines / 55,122 chars. Char delta: +2,672. No new sections; 9 in-paragraph edits across 11 pins.

**Counts:** ambiguity-pins 7, mismatch-revisions 2.

**Per-change:**
- §2.3 Pagination — insert — ambiguity — out-of-range limit/offset clamped (not rejected); non-integer → ERR_INVALID_REQUEST — common.py:134-150
- §2.3 Pagination — revise — ambiguity — created_at ties broken by server creation sequence — common.py:156
- §2.10 Test-Driving Clock — insert — ambiguity — created_at/updated_at (incl. curtailment lines feeding declining walk) read the logical clock; only meta.api_request_timestamp uses wall-clock — db.py:44-56, response.py:8
- §3.2 Aging — insert — ambiguity — run-aging on CURTAILMENT_DUE/PAID_OFF loan returns 200 with no status change (recomputes interest, bumps version) — units.py:192-197
- §3.2 Curtailments — revise — ambiguity — required-minimum/ERR_CURTAILMENT_INSUFFICIENT applies only when loan is CURTAILMENT_DUE; SCHEDULED on OPEN has no minimum — curtailments.py:43-47
- §3.2 Interest — insert — ambiguity — only exact value DECLINING selects declining variant; any other → simple — units.py:178-181
- §3.2 Declining interest — revise — mismatch — equal-created_at curtailments ordered by creation sequence (PRD wrongly named principal_cents as tie-break) — calculations.py:157-160
- §3.3 Deal approve — insert — ambiguity — approve body may carry approved_lender_payoff_cents to overwrite stored value before final recompute — deals.py:152-154
- §3.5 Trade titling — insert — ambiguity — minted unit copies vin/category, model_year=2000, msrp_cents=0, null FKs — deals.py:242-252
- §3.6 Repair orders — insert — ambiguity — CANCELLED ROs excluded from technician schedule-conflict check — repair_orders.py:61
- §3.10 Winterization prep RO — insert — ambiguity — minted prep order copies unit/customer, technician_id=null, appointment=period window, authorized_amount_cents=0, no schedule-conflict check — storage.py:154-170

## Pipeline Complete — 2026-06-14T03:40:36.000Z

All 9 steps complete. Final state: 83/83 tests pass across all 8 parallel stability rounds (independently re-confirmed by orchestrator). Outputs: SCAFFOLD.yaml + 2 design indices, workspace/PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ + test_suite/ (83 tests), workspace/implementation/ (Flask, in-memory), results.{1..8}.json all clean.
