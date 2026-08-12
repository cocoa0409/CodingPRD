# Worklog — task_1259_petroleum_jobber_branded_fuel_supply

## Step 1: Create Task Directory — 2026-08-12T10:34:00.000Z

Pre-assigned output folder `tasks/task_1259_petroleum_jobber_branded_fuel_supply` with `workspace/` subdirectory confirmed to exist. Step 1 treated as done per orchestration instructions (auto-index scan skipped).

## Step 2: Generate Scaffold — 2026-08-12T11:15:30.000Z

Scaffold generation complete for task_1259. All three artifacts written and `scaffold_lint.py` reports **clean lint** (verdict block below).

## What was generated

**Domain design**: branded-fuel jobber operating flat `/api` resources — ledger reconciliation (book vs physical gallons; invoice/EFT credit exposure) as primary archetype + pricing engine secondary (daily rack postings, tiered freight, dual buyout formulas). Layers: cascading side effects, dual-variant calculation, rate thresholds, optimistic concurrency. Role model: segregation of duties (reconciliation resolver ≠ opener; split PricingDesk / Dispatcher / CreditManager desks).

**SCAFFOLD.yaml** (§1.0–§1.7):
- **14 entities**: Product, DealerStation (3 parallel status dims: operating × credit × compliance), SupplyAgreement, RackPricePosting, StorageTank, Truck, TransportDrop, MeterReading (append-only), LossEvent, InventoryReconciliation, Invoice, EFTDraft, TaxRemittance, BrandComplianceAudit (append-only)
- **10 state machines** — incl. cyclic agreement renewal (ACTIVE↔RENEWAL_PENDING, +buyout cancel cycle), drop fail→replan loop, parallel station dimensions, clock-driven auto-transitions (invoice OVERDUE, agreement EXPIRED, cure-expiry → DEFAULT → agreement DEFAULT_NOTICE)
- **3 OCC concurrency rules** (agreement amend, posting supersede create-with-supersede, drop replan — all 412 ERR_STALE_VERSION)
- **10 calculations** — tiered freight invoice (per-component rounding), per-line-then-sum tax remittance rounding, dual buyout variants (UNAMORTIZED_DISCOUNT vs LOST_MARGIN) + pinned netting order with zero floor, gross vs temperature-corrected inventory variance, chronological meter deltas with out-of-order recompute, credit exposure + 80% WATCH band, projected-credit threshold, 95% fulfillment incentive
- **41 error codes**, ordered 10-priority validation table, **77 endpoints**, **7 RBAC roles** (DealerOperator entity-backed to DealerStation; others opaque)
- Logical clock endpoint with pinned default 2026-05-01T00:00:00Z

**SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 19 instances, every rule ≥2 (combinatorial_formula has 3 — modes a/b/c: tiered-freight diesel branch, remittance rounding-order, buyout netting floor). All numeric asserts precomputed by executing the formulas (e.g. invoice total 1948650; remittance 88848 vs naive 88847; buyout bases 2500000 vs 2527473; variance gross −200 vs net −70; credit equality 1772800; fulfillment exactly 95.00 → 20000 credit; freight cliff 15000 vs 8004; 80% band at exactly 800000).

**SCAFFOLD_CORNER_DESIGN.yaml**: 47 instances (41 active + 6 excluded_because stubs) across all nine guide sections — defaults/shape/enum/404s, invalid transitions & terminal lockdowns, clock auto-transitions, OCC ×3, SoD, RBAC denials, ownership scoping, pagination envelope, side-effect-free computed read, immediate consistency.

**Notable decisions**: prices in tenths-of-a-cent/gallon (rack-price realism + rounding traps); safe-fill/credit/tank-buffer boundaries all equality-inclusive with strict-> rejection; clock-set evaluates all time-based auto-transitions; supersede endpoint keeps OCC field always-required (avoids lint hole); invoice void and loss void are the compensating actions for the two conserved quantities (cents exposure, gallons book).

Lint verdict (final run, pasted verbatim):
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared: 77 | §1.1 entities: 14 | §1.8 instances: 19 | §1.9 instances: 47 | calls scanned: 611
```

Files:
- /home/ubuntu/github/CodingPRD/tasks/task_1259_petroleum_jobber_branded_fuel_supply/SCAFFOLD.yaml
- /home/ubuntu/github/CodingPRD/tasks/task_1259_petroleum_jobber_branded_fuel_supply/SCAFFOLD_DIFFICULTY_DESIGN.yaml
- /home/ubuntu/github/CodingPRD/tasks/task_1259_petroleum_jobber_branded_fuel_supply/SCAFFOLD_CORNER_DESIGN.yaml

No sibling tasks were inspected.

## Step 3: Copy Shared Files — 2026-08-12T11:16:10.000Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md → tasks/task_1259_petroleum_jobber_branded_fuel_supply/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-12T11:35:00.000Z

All checks pass. The "around" hit is the phrase "designed around a strict segregation of duties" — structural, not an approximating quantity. The PRD is complete and verified.

**Summary of generation**

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1259_petroleum_jobber_branded_fuel_supply/workspace/PRD.md` — 355 lines.

**Section structure (domain-derived, not template-copied):**
- §1 Introduction — 2 paragraphs (ledger/reconciliation framing, segregation of duties, logical clock, flat `/api` topology)
- §2 Global Specifications — 10 subsections: 2.1 RBAC (all 7 roles with identity translations: 6 opaque, `DealerOperator` entity-backed to `DealerStation`); 2.2 API Response Structure (**verified byte-identical** to `section-2.2-response-structure.md`); 2.3 Pagination (defaults 10/1–100/0, `created_at` ascending, meter-reading ordering exception, all 30+ filter query params enumerated); 2.4 The Logical Clock (startup `2026-05-01T00:00:00Z`, `to_iso8601`/`current_utc`, all three auto-transition families); 2.5 Units/Money/Rounding (integer cents `_cents`, tenths-of-a-cent `_tc_per_gal`, 2000 tc = $2.000/gal, round-half-up, per-component pre-rounding); 2.6 Rack Price Resolution (max `effective_date` on or before D, `created_at` tie-break, `ERR_PRICE_NOT_POSTED`); 2.7 Common Resource Properties (`id`/`created_at`/`updated_at`/`version`; explicit lean variant for MeterReading and BrandComplianceAudit); 2.8 OCC (all 3 rules: `expected_agreement_version`, `expected_superseded_posting_version`, `expected_drop_version`, each with `ERR_STALE_VERSION`/412 and the "no other endpoint takes a version field" closure); 2.9 Request Validation Pipeline (all 10 priority stages with explicit first-failure-masking ordering and every error id); 2.10 Credit Exposure and the Credit Band (ISSUED/OVERDUE sum, 80% inclusive boundary, exact integer 5×exposure vs 4×limit comparison, HOLD enter/exit rules)
- §3 Business Logic — 8 subsections by business process: 3.1 catalogue/stations/trucks, 3.2 agreements terms/amendment, 3.3 renewal/buyout/end-of-term (both base variants, pinned net-settlement order, all 5 quote output fields), 3.4 brand compliance and DEFAULT cascade, 3.5 rack postings/supersession, 3.6 drop planning gates and delivery lifecycle (6 gates in pipeline order, freight tiers 2000/$150.00/6000/40/32, 4-hour settle, 4-hop reconcile cascade), 3.7 gauging/metering/losses/reconciliation (chronological delta + out-of-order recompute, book formula, gross vs temperature-corrected net variance at the 60°F reference, threshold default 130, SoD resolve), 3.8 invoicing/EFT/tax remittance (amount snapshot, HOLD on failure, per-line rounding pinned before summing, 20-day lag, 5% late penalty)
- §4 Endpoint table — 77 rows, 4 columns (Method, Path, Description, Authorized Role(s)), status-code paragraph above
- §5 Error catalogue — 41 rows, 2 columns (Error ID, HTTP Status Code), no trigger conditions

**Coverage audit results:**
- Contract 1 (Field-Name Coverage): 114 required identifiers (entity fields + request-body + query-param + computed output names), 114 present in backticks, 0 missing — PASS
- Contract 2 (Rule Coverage): validation priority ordering (10/10 expressed as an ordered pipeline with explicit masking semantics); OCC rejections (3/3 with write capability, guard field, error id, 412); state transitions (all 9 machines, 60+ transitions, from/to/precondition/side-effect each expressed, sibling branches symmetric); calculations (10/10 in precise prose — no operator syntax, reconstruction-safe); endpoint side effects and `applies_to` scopes (all expressed, including replan re-running all five create gates and the four-drop-states blocking agreement termination); structured field content (defaults, null-until semantics, initial values all placed) — PASS
- Contract 3 (§3 Path Purity): 490 backtick tokens scanned in §3, 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos — PASS
- Additional mechanical checks: all 41 error ids appear in §2/§3 prose; all 60+ enum/state values appear as exact backticked strings; no pseudocode operators (`>=`, `==`, `+=`, etc.) or fuzzy quantifiers in prose

**Design decisions for self-containment and zero-silence:** the logical clock, unit conventions (tc/gal, per-component rounding), and rack-price resolution rule were promoted to dedicated §2 subsections because four calculations depend on them; the full filter-parameter inventory was consolidated in §2.3 to guarantee query-param coverage without scattering one-line mentions; validation priorities were rendered as a numbered 10-stage pipeline so the ordering is explicit rather than implied by text order; all transitions the scaffold expresses as "same as X → Y" were restated in full prose (e.g., `OVERDUE → PAID`/`VOID` sharing the `ISSUED`-origin side effects, HOLD entry from either credit band).

## Step 5: Generate Unit Tests — 2026-08-12T12:10:00.000Z

All files parse. Final summary:

---

## Summary

**Task**: Generate test infrastructure + tests for task_1259 (petroleum jobber branded fuel supply).

**Stage 1 — test_helpers/ inventory (9 files):**
- `test_helpers/__init__.py` — barrel export
- `test_helpers/types.py` — entity TypedDicts + 17 enums; `MeterReading` and `BrandComplianceAudit` omit `updated_at`/`version` per common_fields:false
- `test_helpers/api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (~50 methods)
- `test_helpers/api_errors.py` — 42 error IDs + HTTP status map registered with framework
- `test_helpers/assertions.py` — per-entity shape assertions + invoice/buyout invariant checkers
- `test_helpers/factories.py` — payload factories (input fields only)
- `test_helpers/constants.py` — freight tiers, threshold 130, 80% band, 4h settle, 30d cure, 95.00 incentive
- `test_helpers/test_users.py` — `TEST_USERS` for 7 roles; `make_dealer_operator_headers(station_id)` for entity-backed DealerOperator ownership; `make_admin_headers(user_id)` for SoD
- `test_helpers/fixtures.py` — composite fixtures: `setup_full_drop_fixture`, `create_and_deliver_drop`, `create_and_reconcile_drop`, `gauge_tank`, `submit_meter_reading`, `report_loss`, `open_reconciliation`, `schedule_eft_draft`, `execute_draft`, `void_invoice`, `open_tax_remittance`, `record_audit`, `set_clock`

**Stage 2 — test_suite/ inventory (9 files, 86 tests):**
- `test_suite/conftest.py` — session `api` fixture + per-role headers
- `test_01_entities_and_defaults.py` — 8 tests (Corner/entities)
- `test_02_state_machines.py` — 7 tests (Corner/state_machines)
- `test_03_invoice_and_freight_calculations.py` — 5 tests (Difficulty/combinatorial_formula invoice branch, Corner/calculations freight cliff + price selection, Corner/endpoints deliver)
- `test_04_buyout_renewal_and_cycles.py` — 11 tests (buyout dual-variant ×2, netting floor ×2, renewal cycle ×2, drop fail/replan ×2, fulfillment 95% ×2, renew blocked ×2)
- `test_05_reconciliation_and_cascades.py` — 12 tests (variance gross/net ×2, reconcile cascade ×2, audit default cascade ×2, recon resolve gating ×2, SoD, second-open recon, loss verify/void ×2)
- `test_06_drop_planning_gates.py` — 16 tests (priority pair ×4, credit equality ×2, active agreement ×2, truck adjacency ×2, tank settle ×2, safe-fill equality, no-posted-price, effective-date-in-past, unknown tank, deliver nonexistent, missing auth)
- `test_07_credit_exposure_and_drafts.py` — 5 tests (invoice void invariant ×2, WATCH band ×2, draft execute premature)
- `test_08_tax_metering_and_misc.py` — 12 tests (remittance rounding ×2, late penalty, meter delta, meter regression, duplicate remittance, renewal window, RBAC ×4, pagination, buyout quote side-effect-free, immediate visibility, OCC ×3)

**Queue A (Difficulty):** 19 instances × ≥2 tests each = 38+ tests emitted. **0 instances skipped.**
**Queue B (Corner):** 47 non-stub instances × ≥1 test each. **0 instances skipped.** 6 `excluded_because:` stubs correctly not translated (verified their cited difficulty-instance cross-references resolve).

**Stage 1 self-check:** all files compile, types/api/errors/factories/fixtures/test_users consistent.

**Stage 2 self-check:**
- Total `Design:` tags found: **86**
- Difficulty instances missing or with <2 tests: **none**
- Corner non-stub instances missing: **none**
- Stray tags pointing to non-existent instances: **none**
- Stub tags incorrectly used: **none**
- Every test docstring carries a verbatim PRD citation — automated grep-style check (whitespace-normalized, `...`-segment-aware) confirms all quoted strings appear in `PRD.md` (0 bad citations out of 86 tests).
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere; no freelance tests outside the two design indices.

## Step 6: Generate Implementation — 2026-08-12T12:10:00.000Z

Implementation complete. Verbatim summary:

## File inventory
All under `workspace/implementation/`:

- `start.sh` — launcher (executable)
- `requirements.txt` — `flask>=3.0,<4`
- `app.py` — Flask app factory, ApiError/404/405/generic exception handlers, `app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)`
- `db.py` — in-memory `STORE` dicts (14 collections, empty at boot, no seeding), UUID minting, monotonic insertion seq, logical clock (starts exactly `2026-05-01T00:00:00Z`), timestamp formatters, `stamp_new`/`touch` (created_at/updated_at/version)
- `errors.py` — `ApiError` + all 41 catalog error IDs with exact HTTP statuses
- `response.py` — envelope: `meta{api_request_id, api_request_timestamp[, limit, offset, total_count, has_more]}`, `response_type` (`object`/`array`/`error`), `data`; error body `{error_id, message}`
- `middleware.py` — X-User-ID/X-User-Role auth (stage 1), role gating (stage 2), DealerOperator ownership scoping (stage 5, `X-User-ID` == station id)
- `validate.py` — stage-3 body shape validation (required/unknown/type/enum/bounds, date/datetime parsing), pagination (`limit` default 10, min 1, max 100; `offset` default 0; invalid → 400), filter application, list sorting
- `serializers.py` — per-entity output shaping (meters/audits lean: id+created_at only); internal `_seq` never serialized
- `services/calc.py` — §1.3 calculations: rack price resolution (max effective_date ≤ D, latest created_at tie-break), invoice components (fuel/freight tiers 15000-flat ≤2000 / 40tc 2001–6000 / 32tc >6000 / per-component round-half-up then sum), buyout base variants + pinned penalty/net floor-at-zero, temp-corrected net variance (per-tank round-half-up before summing, ungauged tanks at 60F), book inventory, credit band in exact integer arithmetic (`exposure*5 >= limit*4`), renewal pct (2dp half-up, ≥95.00 → 1% of allowance), tax remittance per-line rounding then sum + 5% late penalty
- `services/cascade.py` — book recompute, exposure+band recompute (version bump only on actual change), recon recompute with OPEN↔VARIANCE_FLAGGED flip and auto SHRINKAGE LossEvent on transition into flagged, CURE_PERIOD→DEFAULT cascade (ACTIVE agreements → DEFAULT_NOTICE), clock-set auto-transitions (ISSUED→OVERDUE past due_date, ACTIVE/RENEWAL_PENDING→EXPIRED past term_end, cure+30d→DEFAULT), meter delta recompute
- `routes/` — 15 modules: `products`, `stations`, `agreements`, `postings`, `tanks`, `trucks`, `drops`, `meters`, `losses`, `recons`, `invoices`, `drafts`, `taxes`, `audits`, `clock`

## Endpoint count
**77 API routes registered** — matches the SCAFFOLD §1.5 endpoint table exactly (products 2, stations 9, agreements 12, postings 6, tanks 4, trucks 2, drops 10, meters 3, losses 7, reconciliations 4, invoices 3, drafts 6, remittances 5, audits 3, clock 1).

## SCAFFOLD section → module mapping
- §1.0 response envelope → `response.py`, `db.py` (fmt_ts)
- §1.1 entities → `serializers.py` + route modules (one per resource group)
- §1.2 state machines (all 9 machines incl. parallel station dimensions) → route modules + `services/cascade.py`
- §1.2.1 OCC (3 rules) → `agreements.py` PATCH (`expected_agreement_version`), `postings.py` supersede (`expected_superseded_posting_version`), `drops.py` replan (`expected_drop_version`); all 412 `ERR_STALE_VERSION`
- §1.3 calculations → `services/calc.py` (Decimal, ROUND_HALF_UP; no float money)
- §1.4 validation priority order (auth→role→shape→existence→ownership→state→safety→temporal→integrity→credit) → enforced per-handler via ordered checks in `middleware.py`/`validate.py`/route bodies
- §1.5 endpoints → `routes/*.py`
- §1.6 error catalog → `errors.py`
- §1.7 RBAC (7 roles, DealerOperator entity-backed scoping) → `middleware.py`

## start.sh contract conformance
- `bash start.sh` from `./implementation/` is the entire contract: `set -euo pipefail`, `cd "$(dirname "$0")"`, **guarded install** (`if ! python3 -c "import flask"` → only then `pip install -q -r requirements.txt`), `exec python3 app.py` (foreground, signals propagate)
- Listens on `PORT` (default 10000), binds `0.0.0.0`, HTTP-ready in ~1–2s (well under 60s)
- Verified: three consecutive `bash start.sh` invocations on distinct ports all served HTTP 400 (auth rejection) within 2 seconds; in-memory store resets per process (no disk persistence, no seeded entities anywhere)

## Smoke checks run
Three suites against live boots (fresh process each):
- **Suite A**: product/station/agreement/posting/truck/tank creation → drop lifecycle (schedule/dispatch/deliver) → invoice math verified (`fuel 1,000,000 + freight 20,000 + tax 192,000 = 1,212,000` cents, due_date +10d) → exposure/band → EFT settle → PAID → reconcile → tank book 6000 → buyout-quote (verified UNAMORTIZED_DISCOUNT 436,475c pro-rata, LOST_MARGIN alternate 1,425,000c, penalty 475,000c, net floored to 0) → role-403, 404, OCC-412, pagination-400 paths
- **Suite B**: supersede OCC + atomic replacement, credit-limit-422, capacity-422-before-credit, truck-window 409 (overlap) / tank-settle 409 (adjacent-but-<4h), recon flag → auto loss (abs(net)=200) → resolve blocked by linked loss (409) + SoD (403) → write-off → resolve OK; meter out-of-order delta recompute (100/150→100/50) + regression 422; dealer ownership 403; remittance overlap 409; compliance FAIL→CURE_PERIOD→FAIL→DEFAULT cascade to DEFAULT_NOTICE; agreement terminate blocked by open drops then succeeding after cancels; late remittance filing (diesel line 9500c + 475c penalty = 9975c)
- **Suite C**: renewal window/state guards, cure-block renewal (409), PASS-audit restore, renewal with 0% fulfillment → credit 0, LOST_MARGIN buyout quote + execute (net 450,000c recorded), premature draft execute 409, FAILED execute → credit HOLD, retry→void-invoice cancels SCHEDULED draft + zeroes exposure, restore-credit → GOOD_STANDING, replan stale 412 then valid replan, clock-driven agreement EXPIRED

All three suites passed (`SMOKE OK`, `SMOKE B OK`, `SMOKE C OK`), plus `py_compile` clean across all modules and a route enumeration confirming 77/77 endpoints. Test servers and `__pycache__` dirs cleaned up afterward.

**Orchestrator route-parity verification (pre-sweep):** parsed SCAFFOLD.yaml endpoint table (77 entries) via YAML and compared against Flask `@route` registrations in implementation (77 routes). Result: 0 missing, 0 extra — exact (method, path) parity.

## Step 7: Run Tests and Iterate — 2026-08-12T12:16:30.000Z

Clean 8-round parallel sweep: all rounds 85/85 passed.

## Summary

**Iterations run:** 3 sweeps (initial diagnosis + 2 fix-verify cycles)

**Tests deleted (1):**
- `test_credit_limit_any_excess_rejected` (test_06_drop_planning_gates.py) — unique-derivability collapse. The test asserted that a second *PLANNED* (never delivered) drop must be rejected with `ERR_CREDIT_LIMIT_EXCEEDED` because prior planned drops consume credit headroom. PRD §3.6 states the projected-credit formula verbatim as "`current_exposure_cents` plus this drop's `estimated_amount_cents` must not exceed `credit_limit_cents`", and PRD §2.10 defines `current_exposure_cents` as the sum over `ISSUED`/`OVERDUE` invoices only — invoices are born at delivery, so a planned drop adds nothing. A faithful PRD-only implementer returns 201 for the second drop; the scaffold's "pipeline exposure" rule never made it into PRD prose (Zero-Silence violation feeding a unique-derivability miss).

**Fixes applied to test_helpers/ (1):**
- `test_helpers/api_client.py` — every one of the ~77 endpoint paths was missing the `/api` mount prefix that PRD §4 declares verbatim for all endpoints (e.g. client posted to `/dealer-stations`, PRD declares `/api/dealer-stations`). Prefixed all paths with `/api`. This single fixture bug caused the initial 86/86 failure round (triage-hint case: one upstream helper bug masquerading as ~70 independent failures).

**Fixes applied to test_suite/ (3 files, all test-side bugs — assertions unfaithful to PRD-expressed logic):**
- `test_suite/test_05_reconciliation_and_cascades.py` — removed `validate_success(...)` wrapping around `open_reconciliation(...)` (2 sites) and `record_audit(...)` (1 site); those helpers already return parsed data via `get_success_data`, so re-validating raised `AttributeError: 'dict' object has no attribute 'status_code'`. Also injected `from test_helpers import api_client as api` into module-level `_resolve_gate_fixture`, which referenced the pytest-fixture name `api` (NameError).
- `test_suite/test_06_drop_planning_gates.py` — same NameError fix in module-level `_state_before_fiscal_fixture`.
- `test_suite/test_08_tax_metering_and_misc.py` (`test_occ_posting_supersede_stale_version`) — partial-coverage split. The test asserted the supersede *response body* is the replacement posting (price 2050, POSTED); PRD §3.5 fixes the side effects (original retired to SUPERSEDED with version+1, replacement created POSTED at `new_price_tc_per_gal`) and §2.2's generic "created or updated resource" envelope rule does not disambiguate which of the two mutated resources is returned — a faithful implementation returning the retired original also satisfies PRD. Kept the PRD-verbatim assertions (stale version → ERR_STALE_VERSION; replacement exists POSTED at 2050 with same terminal/effective date; original now SUPERSEDED) but located the replacement via the list endpoint instead of the response body.

**Fixes applied to implementation/ :** none — the implementation was faithful to the PRD in every diagnosed case.

**Final state:** 8/8 parallel rounds at 85/85 passed, deterministic (no flakiness observed in the final sweep; all pre-fix failures were byte-identical across rounds).

**Orchestrator verification:** read all 8 results.${i}.json files from disk — every round `passed: 85 / 85, failed: 0`. Test count on disk: 85 (86 generated − 1 deleted).

## Step 8: Finalize PRD — 2026-08-12T12:25:00.000Z

Done. `PRD_FINALIZED.md` written at `workspace/PRD_FINALIZED.md`.

## Summary

**Line counts:** PRD.md 355 lines → PRD_FINALIZED.md 355 lines (0% delta by line count; one inline sentence inserted into an existing line — no lines added or removed).

### Changes (1 edit total)

- **§3.5 (Rack Price Postings)** — insert — appended "The supersede response returns the posting addressed in the path — the retired original, now in `SUPERSEDED` — in the data field; the newly created replacement is read back through the posting list and detail endpoints." after "...the replacement begins its own lifecycle." — pins which of the two mutated resources the supersede response carries, previously ambiguous under §2.2's generic "created or updated resource" rule — `implementation/routes/postings.py:115` (`return ok_object(serializers.posting(rec))` where `rec` is the retired original, mutated at postings.py:103-104; the `replacement` created at postings.py:105-114 is not returned).

### Items from step_7_diff requiring no PRD edit

- **Deleted `test_credit_limit_any_excess_rejected`** — no edit. PRD §3.6's verbatim formula ("`current_exposure_cents` plus this drop's `estimated_amount_cents` must not exceed `credit_limit_cents`") combined with §2.10's definition of `current_exposure_cents` (sum over `ISSUED`/`OVERDUE` invoices only) already uniquely derives the implemented behavior: planned drops have no invoice and add nothing to the projection (`drops.py:74-85`, `calc.py:165-169`). The pipeline-exposure reading is not admitted by the PRD text; the deletion confirms PRD is the contract.
- **`test_helpers/api_client.py` /api prefix fix** — pure test-fixture bug; PRD §4 already declares `/api`-prefixed paths verbatim. No edit.
- **test_suite `validate_success` / NameError fixes** (test_05, test_06, test_08) — pure test-side bugs (double-validation of already-parsed data, module-level fixture name misuse). No PRD behavior involved. No edit.

### Per-edit pre-edit search log

**Edit 1 (§3.5 supersede response pin):**
- (a) **Subject:** which resource object a mutating endpoint that touches two resources returns in the success envelope — specifically `POST /api/rack-price-postings/{id}/supersede`, which retires one posting and creates another.
- (b) **Impl paths enumerated and read/grepped:** the supersede route itself (`routes/postings.py:85-115`, read in full); a full grep of `return ok_object` across every route file (`routes/*.py`, 60 hits) confirming every mutating endpoint returns its path-addressed record — deliver returns the drop not the invoice (`drops.py:252`), reconcile returns the drop (`drops.py:319`), invoice void returns the invoice (`invoices.py:57`), draft execute returns the draft (`drafts.py:102`), renewal/buyout return the agreement (`agreements.py:183-249`); the sole non-resource return is `buyout-quote` (`agreements.py:208`), a read-only projection whose shape PRD §3.3 already specifies; list/get posting endpoints (`postings.py:44-63`) confirming the replacement is retrievable via list (all statuses, optional `status` filter) and detail reads; PRD-side phrasing checked at §2.2 (line 45 generic envelope rule), §3.5 (line 180), and the §4 supersede table row (line 260) — none previously disambiguated.
- (c) **Wording adjustment:** scoped the sentence strictly to the supersede endpoint ("The supersede response returns...") rather than asserting a universal "fan-out endpoints return the path-addressed resource" principle — the universal claim would be true today but would create a false-universal mismatch risk against the `buyout-quote` exception class; the trailing clause about reading the replacement "through the posting list and detail endpoints" was verified against `list_postings`/`get_posting` before inclusion.

## Step 9: Complete PRD — 2026-08-12T12:45:00.000Z

Done. `workspace/PRD_COMPLETED.md` written as a minimal patch over `PRD_FINALIZED.md`.

**Size**: source PRD_FINALIZED.md 355 lines / 58,494 chars → PRD_COMPLETED.md 361 lines / 62,625 chars (**+4,131 chars**, 22 changed regions, all in-paragraph or table-row edits; no new sections).

**Counts**: 25 ambiguity-pins, 5 mismatch-revisions.

**Mismatch revisions (PRD asserted what impl contradicts):**
- §2.4 — revise — mismatch — narrowed "All date and datetime semantics … never by wall-clock time" to business semantics only (delivery stamps, cure windows, invoice aging, term expiry, filing stamps), since `created_at`/`updated_at`/`api_request_timestamp` are wall-clock — db.py:63-76, response.py:17-18
- §2.5 — revise — mismatch — "integer arithmetic throughout, with one exception" → two exceptions; dealer gauge readings are accepted as arbitrary JSON numbers so `physical_gallons` may be non-integer — routes/tanks.py:75-78
- §3.1 — revise — mismatch — "a two-letter `state_code`" → conventionally two letters, length not validated — routes/stations.py:25
- §3.1 — revise — mismatch — federal excise "(184 for gasoline, 244 for diesel)" marked conventional, not a validation rule; any integer stored — routes/products.py:23
- §3.8 — revise — mismatch — remittance tax computed "per category line" → lines grouped by (product category, station `state_excise_tc_per_gal`), so differing rates split a category into multiple rounded lines — services/calc.py:198-210

**Ambiguity pins (PRD silent, now pinned to impl):**
- §2.1 — insert — station scoping applies only to resources referencing a DealerStation; products, postings, trucks, tax remittances are fully dealer-visible — middleware.py:41-45, routes/products.py:43-49, routes/postings.py:44-55, routes/trucks.py:36-39, routes/taxes.py:60-69
- §2.2 — insert — undefined paths → `ERR_NOT_FOUND` (404), unsupported methods → `ERR_METHOD_NOT_ALLOWED` (405), same envelope — app.py:26-34
- §2.3 — insert — non-integer/out-of-range `limit` or non-integer/negative `offset` → `ERR_VALIDATION_FAILED` (400); `offset` must be ≥ 0 — validate.py:106-125
- §2.3 — insert — `has_more` defined as `offset + returned items < total_count` — response.py:31
- §2.3 — insert — default `created_at` sort ties broken by creation order — validate.py:137-139
- §2.3/§3.7 — insert — meter-reading ties beyond `created_at` broken by creation order — routes/meters.py:75-76, 38-40
- §2.4 — insert — clock may be set to any instant (backward allowed); auto-transitions only move forward — routes/clock.py:16-23
- §2.6 — insert — price-resolution ties beyond `created_at` broken in creation order — services/calc.py:44
- §2.7 — insert — `version` starts at 1 at creation — db.py:68
- §2.7 — insert — `created_at`/`updated_at` stamped from server wall clock — db.py:63-76
- §2.9 stage 3 — insert — non-object body fails; malformed/absent JSON treated as empty object — validate.py:39-46
- §2.9 stage 4 — insert — cross-reference integrity (drop tank↔station/product, loss tank↔station) evaluated post-existence as `ERR_VALIDATION_FAILED` — routes/drops.py:124-129, routes/losses.py:37-39
- §3.2 — insert — no limit on agreements per station, multiple `ACTIVE` allowed; drafting ignores station operating status — routes/agreements.py:25-63
- §3.2 — insert — amend: from-state guard (`ERR_INVALID_STATE`) evaluated before the stale-version guard — routes/agreements.py:103-107
- §3.3 — insert — renew validates `new_term_end_date` strictly after `new_term_start_date` (`ERR_VALIDATION_FAILED`) — routes/agreements.py:158-161
- §3.3 — insert — each renewal overwrites `renewal_credit_cents` (not accumulated) — routes/agreements.py:174-175
- §3.3 — insert — buyout-quote readable in any agreement status — routes/agreements.py:203-208
- §3.5 — insert — supersede guard order: `POSTED` state → stale version → effective-date equality (a post-existence integrity check, not stage-3 shape) — routes/postings.py:96-102
- §3.6 — insert — drop creation also requires the receiving tank to belong to the station; both integrity violations are `ERR_VALIDATION_FAILED` — routes/drops.py:124-129
- §3.6 — insert — `delivered_gallons` must be an integer > 0; planning safety gates are not re-applied to the delivered quantity — routes/drops.py:213-215
- §3.6 — insert — delivery response returns the updated drop; the invoice is read via invoice endpoints — routes/drops.py:252
- §3.7 — insert — loss-event `tank_id`, when supplied, must belong to the station (`ERR_VALIDATION_FAILED`) — routes/losses.py:37-39
- §3.7 — insert — auto-generated shrinkage loss carries null `tank_id` (station-level; no tank-book deduction) and `occurred_at` = current logical clock instant — services/cascade.py:38-48
- §3.8 — insert — draft `scheduled_date` accepts any date; executability enforced only at execution — routes/drafts.py:23-24
- §3.8 — insert — remittance computed figures null until filing — routes/taxes.py:47-51
- §5 — insert — catalogue rows for `ERR_NOT_FOUND` (404) and `ERR_METHOD_NOT_ALLOWED` (405) — app.py:26-34

No behavior was invented; every pin/revision was traced to a specific implementation line. Tests were used only as auxiliary cross-reference (e.g., confirming `version == 1` at creation).
