# Worklog — task_0339_rv_sales_service

## Step 1: Create Task Directory — 2026-06-14T02:33:59.000Z

Task directory `tasks/task_0339_rv_sales_service` was pre-allocated and pre-created (per orchestrator instruction, Step 1 index scan/increment skipped to avoid ID contention with parallel tasks). Confirmed `workspace/` subdirectory exists and is empty. Scenario: RV Sales & Service. Difficulty: Expert (passed only to scaffold-generator in Step 2).

## Step 2: Generate Scaffold (Expert difficulty) — 2026-06-14T03:05:56.000Z

Generated three Expert-tier scaffold artifacts for **task_0339_rv_sales_service** (RV Sales & Service), all passing `scaffold_lint.py` with `VERDICT: clean lint`.

**Design profile:** Workflow-orchestration primary (deal lifecycle) blended with quota-allocation (finite bays + parts stock), **flat topology** (top-level peer collections joined by `dealership_id` FK — the skill explicitly prioritizes flat), **parallel** state-machine shape, peer-roles RBAC. Complexity layers: dual-variant calculation, cascading side effects, optimistic concurrency, resource temporal overlap, derived-field reconciliation.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **14 entities** (Dealership, Customer, Unit, Deal, PdiInspection, ServiceBay, ServiceOrder, PartItem, PartReservation, WarrantyPlan, Appointment, StorageSlot, RecallCampaign, RecallRemedy)
- **64 endpoints** (count driven up by mandatory list+get reverse-reachability GETs for every FK under flat topology)
- **6 state machines**: Unit (compound/posture), **Deal (parallel `sale_status × finance_status`, with a finance cycle DECLINED↔REQUESTED→APPROVED)**, **ServiceOrder (cyclic IN_PROGRESS↔AWAITING_PARTS)**, Appointment, StorageSlot, RecallCampaign
- **6 calculations** incl. dual-variant `net_trade_equity` (applied vs dealer-book, diverge by recon) and `service_order_total` (warranty-covered vs owed); pinned-order `deal_amount_due`; round-then-sum labor; tiered `monthly_payment` (APR band + LTV guard); `storage_charge` (ceil-day + winterize); waterfall `consignor_proceeds` (floor-honored)
- **13 validations** (priority-ordered), **46 errors**, **4 roles** (DealerManager/SalesAgent/ServiceAdvisor opaque, Customer entity-backed), **2 concurrency rules** (Unit-version OCC on deal-create and storage-book)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** 9 rule_ids × 2 = **18 instances**, each with executable empty-DB `setup_api_calls` chains and literal formula-derived asserts (e.g., monthly 115969, amount_financed 7001150, SO total 113550, storage 45000, LTV boundary 12000 inclusive — all computed in code and verified).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **47 instances** (42 active + 5 `excluded_because` stubs) spanning all 9 claim-extraction-guide sections (entities, state_machines, calculations, validations, endpoints, rbac, cross-cutting layers, consistency_model).

**Lint:** 343 calls scanned, all conform to §1.5; all 32 FKs have reverse-reachability GETs; no forbidden concurrency vocabulary; design keys correctly isolated to their own files. (Resolved an initial nested-path design that failed FK reverse-reachability by restructuring to flat top-level collections with `api_prefix: ""`.)

## Step 3: Copy Shared Files — 2026-06-14T03:06:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0339_rv_sales_service/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-14T03:12:32.000Z

**Output:** `workspace/PRD.md` — 319 lines, 5 top-level sections + 21 subsections (§2.1–2.10 domain-derived, §3.1–3.11 lifecycle-grouped, §4 endpoint table, §5 error catalogue).

**Coverage confirmation — every scaffold element in prose:**
- Entities: all 14, all 78 field names verbatim.
- State machines: all 6 (Unit, Deal parallel sale_status × finance_status, ServiceOrder cyclic, Appointment, StorageSlot, RecallCampaign); all 31 states, every transition's from/to + preconditions/error_ids + side-effects.
- Calculations: all 6 (`net_trade_equity` dual-variant, `deal_amount_due` pinned-order, `monthly_payment` amortization+tiered APR, `service_order_total` round-then-sum, `storage_charge` ceil-day, `consignor_proceeds` waterfall) with constants embedded (APR 599/899/1499 bps, LTV 13000/12000/11000 bps, winterize 25000 cents).
- Validations: all 13 priority-ordered (relative ordering stated in §2.6).
- Endpoints: all 64 in §4 table; 65 input identifiers + 15 path params verbatim.
- Errors: all 46 in §5 catalogue. Roles: all 4 (DealerManager/SalesAgent/ServiceAdvisor opaque, Customer entity-backed).

**Hard contracts:** Field coverage PASS (78/78, 65/65, 15/15), Rule coverage PASS (13 validations, 2 OCC, all transitions/calcs, sibling-branch symmetry), Path purity PASS (§3: 0 path tokens of 479 backtick tokens). §2.2 envelope emitted byte-verbatim. Withheld design files not opened.

## Step 5: Generate Unit Tests — 2026-06-14T03:27:57.000Z

**Test files:** 5 test modules (`test_01_money_math.py`, `test_02_lifecycle_and_cascades.py`, `test_03_validations_and_constraints.py`, `test_04_entities_and_reads.py`, `test_05_rbac_concurrency_consistency.py`) + `conftest.py` in `test_suite/`, totaling **77 test functions** — all 77 carry exactly one `Design:` tag.

**test_helpers/ (9 files):** `types.py` (19 enums + 14 entity TypedDicts), `api_client.py` (one method per §4 endpoint), `api_errors.py` (`ApiErrorId` enum + HTTP status map), `assertions.py`, `factories.py` (input-only payload factories), `constants.py` (APR bands, LTV ceilings, term bounds, winterize fee), `test_users.py` (3 opaque operator roles + `make_customer_headers()`), `fixtures.py` (composite lifecycle helpers with unique-field counters), `__init__.py`.

**Queue A (Difficulty):** 18/18 instances translated, 2 tests each (36 tests) — every difficulty instance verified literal-value-correct (tax 471250, financed 7001150, labor 113550, monthly 115969, LTV 12000bps, storage 45000, consignor floor 7500000). **0 skipped.**

**Queue B (Corner):** 42 non-stub instances; 41 translated (1 test each), **1 skipped**:
- `entities/doc_fee_over_cap_rejected` — SKIP (fails unique derivability): PRD names `ERR_DOC_FEE_OVER_CAP` but never states the cap's numeric value, so a faithful PRD-only implementer could pick a cap above the test's `99999999` and the assertion would fail.

5 `excluded_because:` stubs left untranslated; all 5 `difficulty_instance` cross-references resolve to real instances. All 14 Python files compile; every `from test_helpers import` resolves; every PRD citation survives literal grep; every docstring ends with exactly one `Design:` line.

## Step 6: Generate Implementation — 2026-06-14T03:27:57.000Z

Generated Python + Flask implementation in `workspace/implementation/`.

**Files:** `start.sh` (executable foreground launcher), `requirements.txt` (flask==3.0.3), `app.py`, `db.py` (14 in-memory dicts keyed by UUID), `errors.py` (46-entry catalogue), `response.py` (envelope helpers), `middleware.py` (auth + RBAC), `common.py`, `calculations.py` (Decimal/round-half-up), `services.py` (reconciliation + cascades), `routes/` (13 blueprints, all 64 endpoints).

**Stack/launcher:** Python 3 + Flask, in-memory dict storage only (no SQLite/file/external; no seeding — store starts empty, verified total_count 0). `start.sh` → `cd "$(dirname "$0")"`, pip-install guard on `import flask`, then `exec python3 app.py`; `app.py` reads `int(os.environ.get("PORT","10000"))`, `app.run(host="0.0.0.0", port=port, threaded=True)` foreground.

**Notable design:** Parallel Deal SM (sale_status × finance_status with DECLINED→REQUESTED cycle); cyclic ServiceOrder (IN_PROGRESS↔AWAITING_PARTS); dual-variant calcs (net_trade_equity applied vs dealer-book; service_order_total covered vs owed); pinned-order deal_amount_due; round-then-sum labor; tiered APR amortized monthly_payment; ceil-day+winterize storage_charge; floor-honored waterfall consignor_proceeds. OCC on POST /deals and POST /storage-slots (ERR_STALE_UNIT_VERSION/412, checked after existence before business rules; storage booking bumps unit version). Cascades on deal cancel / SO complete+cancel / campaign open+close. Validation precedence per §2.6. RBAC opaque operators + entity-backed Customer reads. **DOC_FEE_CAP_CENTS = 100000** (not pinned in PRD/scaffold — chosen above valid fixtures; note: corresponding test was skipped in Step 5). Ran 55 live end-to-end checks, all passed.

## Step 7: Run Tests and Iterate — 2026-06-14T03:33:13.000Z

All 8 parallel rounds pass with 77/77. Clean sweep achieved.

**Iterations run:** 2 (baseline sweep + 1 fix + verification sweep).

**Result:** All 8 parallel rounds green at 77/77. The implementation was correct as written; the single failure was a test-fixture bug.

**Diagnosis of the one failing test** (`test_request_finance_below_minimum_term_rejected`, consistent across all 8 baseline rounds — not flaky):
- The test expected `ERR_INVALID_TERM` but the implementation returned `ERR_FINANCE_BAD_STATE`.
- Root cause: the test built its precondition with `setup_quoted_deal`, which produces a deal whose `finance_status` is `CASH` (PRD §3.3: a quote with no `term_months` moves finance `NONE → CASH`). It then called `request-finance` with `term_months: 6`.
- PRD §3.4 makes a finance request legal only from finance states `NONE` (fresh) or `DECLINED` (resubmission); `CASH` is not such a state. PRD §2.6 fixes the validation order: finance-state-legality is priority 5, the term-range field check (`ERR_INVALID_TERM`) is priority 13 (last). So on a CASH deal the request is correctly rejected at the state check (`ERR_FINANCE_BAD_STATE`) and never reaches the term validation the test intended to exercise.
- STEP 1 verdict: PRD verbatim-covers the term rule AND uniquely determines that `ERR_FINANCE_BAD_STATE` precedes `ERR_INVALID_TERM` here, so the implementation's behavior was correct → STEP 2 test bug.

**Fixes applied to test_suite/** (one file; no test_helpers or implementation changes):
- `test_suite/test_03_validations_and_constraints.py`, `test_request_finance_below_minimum_term_rejected`: switched the precondition from `setup_quoted_deal` (finance_status `CASH`, term check unreachable) to `setup_held_deal` (DRAFT deal, finance_status `NONE`), so `request-finance` is legal on the finance axis and the priority-13 term-range check is actually reached. This matches the canonical pattern every other request-finance test in the suite already uses, and makes the test more faithful to the PRD §3.4 rule it asserts. Added a docstring note explaining the precedence rationale.

**Tests deleted:** None. The failing test's asserted rule is PRD-covered and uniquely derivable; the defect was a fixture building a precondition inconsistent with PRD, fixed per STEP 2 rather than deleted.

**Fixes applied to test_helpers/:** None.

**Fixes applied to implementation/:** None — the implementation's validation ordering already faithfully implemented PRD §2.6.

## Step 8: Finalize PRD — 2026-06-14T03:35:14.000Z

(Not skipped: Step 7 applied 1 `test_suite/` fix, so the all-four-zero skip condition was not met.)

**PRD.md vs PRD_FINALIZED.md:** 318 vs 318 lines, 0% delta (byte-identical, verified `diff -q`).

**Changes:** No substantive edits. The single Step 7 item was a pure test-fixture bug, not a PRD silence or PRD/impl mismatch. The implementation's validation ordering already faithfully implements PRD §2.6 (finance-state-legality at priority 5 precedes the term-range field check at priority 13) and §3.4 (a finance request is legal only from finance states NONE or DECLINED; CASH is not legal). PRD.md already uniquely determines that `ERR_FINANCE_BAD_STATE` precedes `ERR_INVALID_TERM` on a CASH deal — no silence, no mismatch.

**Pre-edit search log (finance-state-precedence subject, recorded though no edit made):** enumerated `routes/deals.py:179-205` (request_finance — state-legality before term-range), `routes/deals.py:162-176` (quote NONE→CASH), `routes/deals.py:208-239` (finance_decision REQUESTED-gated), `routes/deals.py:17,249,267` (SETTLED_FINANCE gating), `errors.py:34,61` (409/400 status map) — all already correctly and uniquely described by PRD.md; no wording adjustment required.

## Step 9: Complete PRD — 2026-06-14T03:39:46.000Z

Produced `workspace/PRD_COMPLETED.md` as a minimal patch over `PRD_FINALIZED.md`, pinning every place PRD was silent or mismatched against `implementation/`.

**Line counts:** PRD_FINALIZED.md 318 → PRD_COMPLETED.md 321 (+3). **Char-delta:** 51,587 → 54,089 (+2,502).

**Counts:** ambiguity-pins = 8, mismatch-revisions = 1.

**Per-change list:**
- §2.1 RBAC — revise — mismatch — Customer reading another customer's resource returns that resource's own 404 (not a forbidden error); Unit/Dealership single-reads carry no per-record ownership filter; corrected the "own records" list — `routes/deals.py:101-102`, `routes/customers.py:56-57`, `routes/service_orders.py:79-80`, `routes/warranty_plans.py:62-63`, `routes/storage_slots.py:91-92`, `routes/units.py:115-120`.
- §2.5 Referential Integrity — insert — ambiguity — pinned the three single-read-only 404s `ERR_PDI_INSPECTION_NOT_FOUND` / `ERR_PART_RESERVATION_NOT_FOUND` / `ERR_RECALL_REMEDY_NOT_FOUND` omitted from the catalogue — `routes/pdi.py:66`, `routes/part_reservations.py:70`, `routes/recalls.py:128`.
- §3.3 Appraise-trade — insert — ambiguity — pinned that the appraisal returns HTTP 201 with the new trade-unit object (not the deal) and bumps the deal's version — `routes/deals.py:158-159`.
- §3.3 Equity-summary — insert — ambiguity — pinned that the computed read returns the full deal object rather than a distinct two-field payload — `routes/deals.py:106-111`.
- §3.4 Finance approval (LTV) — insert — ambiguity — pinned integer floor division for the LTV ratio and that a zero `list_price_cents` is rejected with `ERR_LTV_EXCEEDED` — `calculations.py:60-64`, `routes/deals.py:230-233`.
- §3.5 PDI inspection — revise — mismatch — clarified that recording always succeeds at 201 regardless of deal `sale_status` (no `ERR_DEAL_BAD_SALE_STATE`), and the advance to WALKTHROUGH is a conditional side effect that fires only on PASS while the deal is PDI_PENDING — `routes/pdi.py:25-42`.
- §3.6 Consignment settlement — insert — ambiguity — pinned the nested `consignor_proceeds` field (`commission_cents`, `consignor_net_cents`, `dealer_margin_cents`) written on the delivered deal with a second version bump, absent for stock/trade-in deals — `routes/deals.py:281-286`.
- §3.7 Service order (warranty) — insert — ambiguity — pinned that an omitted `warranty_plan_id` also raises `ERR_WARRANTY_UNIT_MISMATCH` (existence checked first), and that the plan's `status` is never consulted at open/complete — `routes/service_orders.py:29-37`, `131-150`.
- §5 Error Catalogue — insert — ambiguity — added the three 404 rows omitted from the table, matching the §2.5 pins above.

**Deliberately left unchanged** (PRD and impl both impose no constraint): part-reservations and trade-appraisal have no SO/deal state guard; dead `r==0` amortization branch (all APR bands > 0); storage-charge ms precision (refines, does not contradict, the "elapsed seconds rounded up, min 1 day" formula).

---

## Pipeline Complete

All 9 steps finished. Final state: **77/77 tests pass across all 8 parallel stability rounds.** Task `task_0339_rv_sales_service` (RV Sales & Service, Expert difficulty) is complete with all artifacts present: SCAFFOLD.yaml + 2 design indices, PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ + test_suite/ (77 tests), and a working Flask implementation/.
