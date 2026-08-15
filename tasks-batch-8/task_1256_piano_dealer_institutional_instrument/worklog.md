# Worklog — task_1256_piano_dealer_institutional_instrument

## Step 1: Create Task Directory — 2026-08-12T10:14:00.000Z

Pre-assigned output folder `tasks/task_1256_piano_dealer_institutional_instrument` with `workspace/` subdirectory already exists. Step 1 auto-index scan skipped per instructions; treating Step 1 as done.

Difficulty parameter: "generate task hard than expert level!" — passed through to Step 2 scaffold generator only.

## Step 2: Generate Scaffold — 2026-08-12T10:49:00.000Z

All three artifacts are complete and lint-clean. Summary:

## Task: task_1256_piano_dealer_institutional_instrument (beyond-expert tier)

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1256_piano_dealer_institutional_instrument/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single `scaffold_difficulty_design` key
- `SCAFFOLD_CORNER_DESIGN.yaml` — single `scaffold_corner_design` key

**Counts:**
| Element | Count |
|---|---|
| Entities | 15 (Consignor, Customer, Instrument, TradeInAppraisal, BidPackage, SalesOrder, DeliveryCrew, DeliveryJob, Technician, ServicePlan, ServiceVisit, FinancingAgreement, WarrantyRegistration, RestorationReferral, ShowroomEvent) |
| State machines | 12 (incl. cyclic appraisal negotiation OFFERED↔COUNTERED, bid compliance cycle, delivery fail/reschedule loop, restoration-hold cycle, and SalesOrder parallel payment×fulfillment dimensions) |
| Calculations | 9 (trade-in dual-variant, consignment GROSS/NET dual-variant, tiered bid pricing with ceiling min, per-line-then-sum order rounding, delivery fee tiers, financing STANDARD annuity vs RENT_TO_OWN, plan loyalty pricing, warranty coverage extension, artist max-payout) |
| Validations | 10 priority rows (auth → SoD → existence → state → safety → temporal → constraint → referential → fiscal) |
| Endpoints | 79 (incl. `POST /piano-dealer/_clock/set_current_utc` with pinned default 2026-05-01T00:00:00Z) |
| Error catalog | 30 |
| Roles | 9 (segregation-of-duties model; Customer/Consignor entity-backed, rest opaque) |
| Concurrency rules | 2 (OCC create-with-supersede on BidPackage revisions and SalesOrder amend, both 412 ERR_STALE_VERSION) |
| §1.8 difficulty instances | 18 (9 rules × exactly 2, all differentiation clauses honored; every numeric assert pre-computed as a literal — e.g., provisional 1862000 vs final 1883200, GROSS 1600000 vs NET 1536000, capped bid 1700000, order total 440800, RTO credit 13284) |
| §1.9 corner instances | 56 total (48 active + 8 `excluded_because` stubs) across entities / state_machines / calculations / validations / endpoints / errors / rbac / consistency_model |

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(460 calls scanned across both design files; 0 violations; no forbidden concurrency vocabulary; no name collisions between the two design files.)

Notable hardness drivers: three distinct interval-overlap semantics (delivery half-open+30min buffer, technician closed-interval+4-per-day capacity cap, event half-open adjacency-allowed), a depth-3 return cascade (order→instrument→warranty→risk_score) and a depth-2 default cascade (agreement→order→instrument), dual validation-priority conflicts (state/fiscal, safety/constraint), inclusive 40% trade-in cap and zero-credit boundaries, and SOD self-approval on institutional bids.
## Step 3: Copy Shared Files — 2026-08-12T10:50:00.000Z

Copied ./INSTRUCTION.md to tasks/task_1256_piano_dealer_institutional_instrument/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-12T11:05:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1256_piano_dealer_institutional_instrument/workspace/PRD.md` (332 lines). The withheld difficulty/corner index files were never opened.

## PRD Section List

- **1. Introduction** (2 paragraphs: business context + API scope, `/piano-dealer` mount)
- **2. Global Specifications & System-Wide Principles**
  - 2.1 User and Role-Based Access Control (headers, 9 roles, identity semantics, SOD)
  - 2.2 API Response Structure (canonical block, verified byte-identical)
  - 2.3 Pagination
  - 2.4 Common Resource Properties
  - 2.5 The Dealer's Logical Clock
  - 2.6 Monetary Precision and Rounding
  - 2.7 Optimistic Concurrency and Stale Versions
  - 2.8 The Order of Validation (10-level priority chain in prose)
  - 2.9 Dual-Track Orders and Cascade Discipline
- **3. Business Logic & Workflows** (9 subsections: 3.1 Instrument Intake & Consignment Ledger; 3.2 Trade-In Appraisals & Offer Window; 3.3 Institutional Bids & Compliance; 3.4 Order Composition & Pricing; 3.5 Payments, Financing & Rent-to-Own; 3.6 Delivery, Installation & Returns; 3.7 Service Plans & Visits; 3.8 Warranties & Restoration; 3.9 Showroom Events & Artist Settlement)
- **4. Endpoint Definitions** (79 rows: 55 POST + 23 GET + 1 PATCH; 4 columns)
- **5. Error Code Catalogue** (30 rows; 2 columns)

## Coverage Audit (scaffold → PRD mapping)

- **entities (15)**: all fields → §3 narrative (Consignor/Instrument §3.1, TradeInAppraisal §3.2, BidPackage §3.3, Customer/SalesOrder §3.4, FinancingAgreement §3.5, DeliveryCrew/DeliveryJob §3.6, Technician/ServicePlan/ServiceVisit §3.7, WarrantyRegistration/RestorationReferral §3.8, ShowroomEvent §3.9); common fields → §2.4
- **state_machines (12)**: every transition's from/to states, actor, preconditions + error IDs, and side effects expressed in the matching §3 subsection (verified transition-by-transition, 65+ transitions)
- **calculations (9)**: trade_in_valuation PROVISIONAL/FINAL → §3.2; consignment_payout GROSS/NET → §3.1; institutional_bid_price (tiers 8/12/15%, multipliers, ceiling min) → §3.3; order_total (per-line round then sum, 40% inclusive cap) → §3.4; delivery_fee (15,000 base / 2,500 per stair / 12,000 / 24,000 bands / 20,000 climate) → §3.6; financing_schedule STANDARD annuity + RENT_TO_OWN 1.2%/60%/24-month + missed_payments → §3.5; service_plan_price + loyalty 10% → §3.7; warranty_coverage_end (24+12 within 30 days; 60-day window) → §3.8; artist_payout → §3.9
- **validations (10 priorities)** → §2.8 ordered prose, each condition paired with its error ID
- **concurrency_rules (2)** → §2.7 + §3.3/§3.4 (`expected_bid_version`, `expected_order_version`, `ERR_STALE_VERSION`/412; "no other endpoint" closure stated)
- **endpoints (79)** → §4 table; side effects scattered into §3 narratives
- **errors (30)** → all triggered in §2/§3 prose, catalogued in §5
- **roles (9)** → §2.1 with per-role identity translation (Customer/Consignor entity-backed, seven opaque)

## Hard Contract Reports

```
Field coverage check:
- entities[].fields + endpoint inputs/query/path params: 115 required, 115 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority chain: 10 checked, 10 expressed, 0 missing
- concurrency_rules[] OCC: 2 checked, 2 expressed (endpoint + field + error_id), 0 missing
- state machine transitions: all checked, all expressed with preconditions/side effects, 0 missing
- calculations[]: 9 checked, 9 fully expressed (constants embedded, rounding order pinned), 0 missing
- validations[] conditions: 10 checked, 10 matchable to error_id, 0 missing
- endpoints[].side_effects: all expressed in §3, 0 missing
- fields[] structured content (defaults/types): reconstructible, 0 missing
- sibling-branch symmetry: 14 groups checked (split modes, valuation variants, programs, tiers, bands, outcomes...), 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 558
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verifications: §2.2 byte-identical to canonical source; no pseudocode operators or fuzzy approximators in prose; all 80+ enum/state values present verbatim; §4/§5 table shapes correct; §3 paragraph starters varied (24 distinct starters across 34 paragraphs).

## Step 5: Generate Unit Tests — 2026-08-12T11:35:00.000Z

All audits pass and pytest collects the full suite cleanly. Generation complete.

## Summary

### test_helpers/ (9 files)
- `/home/ubuntu/github/CodingPRD/tasks/task_1256_piano_dealer_institutional_instrument/test_helpers/__init__.py` — barrel export (framework generics + PRD-specific)
- `types.py` — 12 status enums, `UserRole`, 15 entity TypedDicts (all `common_fields: true`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (57 methods) + module-level `api_client`
- `api_errors.py` — 30 `ApiErrorId` values + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + `assert_plan_credit_invariant` (PRD §3.7 bookkeeping invariant)
- `factories.py` — payload factories, `order_line`/`bid_line` builders
- `constants.py` — all calculation constants (valuation bases, tiers, fees, RTO rates, warranty terms, risk scores)
- `test_users.py` — `TEST_USERS` for 7 opaque roles + per-instance builders `make_customer_headers` / `make_consignor_headers` / `make_bid_officer_headers` / `make_compliance_officer_headers` (identity threading for entity-backed roles and SOD checks)
- `fixtures.py` — composite helpers: clock, CRUD creators, `create_available_instrument`, `create_paid_order`, `deliver_order`, `install_order`, `setup_installed_order`, appraisal walk (`create_offered/accepted_appraisal`), bid walk (`create_submitted/approved_bid`), financing walk (`create_active_financing`), plan/visit helpers (`setup_plan_with_visits`), warranty/referral/event helpers

### test_suite/ (12 files)
`conftest.py` + 11 numbered test files: `test_01_registration_and_intake.py` (10), `test_02_security_and_rbac.py` (5), `test_03_trade_in_appraisals.py` (7), `test_04_institutional_bids.py` (7), `test_05_sales_order_pricing.py` (8), `test_06_payments_and_order_gates.py` (9), `test_07_delivery_scheduling.py` (8), `test_08_returns_warranties_cascades.py` (10), `test_09_service_plans.py` (9), `test_10_financing.py` (6), `test_11_referrals_and_events.py` (6).

### Counts
- **Total tests: 85** (collected cleanly by pytest)
- **Queue A (§1.8): 36 tests** — all 18 instances × exactly 2 tests
- **Queue B (§1.9): 49 tests** — all 48 non-stub instances ≥1 test (`bid_revision_occ_stale_version_rejected` has 2: stale-rejection + reprice/revision_number)

### Skipped instances
8 skipped, all `excluded_because:` stubs in the errors section (not translated per spec; cross-references verified — 7 resolve to difficulty instances, 1 (`error_appraisal_expired_covered`) resolves to the corner instance `appraisal_lazy_expiry_after_fourteen_days` which owns the assertion). **Zero instances skipped for PRD-coverage/derivability failure.**

### PRD-first adjustments (no instance dropped)
- `customer_creation_defaults_applied`: dropped only the `tax_exempt == false` sub-assertion (PRD never names its default — `default-value` silence); risk_score/credit_limit/version defaults asserted from verbatim PRD text.
- `event_settle_before_end_rejected`: dropped `payout_cents is null` (computed field never stated as present pre-settle — `computed-field` silence).
- `order_parallel_payment_and_fulfillment_dims`: dropped the final `Instrument == DELIVERED` assertion (PRD's "SOLD → DELIVERED" complete-side-effect vs "RESERVED → SOLD" payment-side-effect ordering is genuinely two-reader ambiguous for a deposit-first flow); both dual-track assertions kept.
- `service_plan_zero_credit_booking_rejected`: the exhausted plan is simultaneously not-ACTIVE and zero-credit, and PRD §2.8's priority order doesn't cleanly name a winner, so the rejection uses `validate_error_is_one_of([ERR_PLAN_EXHAUSTED, ERR_PLAN_NOT_ACTIVE])` (`error-precedence` pattern); the counters and auto-EXHAUSTED assertions remain exact.
- `order_with_non_awarded_bid_rejected`: added `list-for-sale` to setup so the instrument is AVAILABLE — otherwise the priority-5 instrument state check would mask the priority-9 bid rule being tested (validation isolation).

### Stage 2 lint verdict (tag audit)
**PASS** — 0 untagged, 0 dual-tagged, 0 orphan tags; queue A 36/36 (≥2 per instance), queue B 49/48 (≥1 per non-stub instance); all 8 stub cross-references resolve. Separately: 134 citations ≥8 words all survive verbatim grep of PRD.md; no skip/xfail markers; no scaffold references in generated code; all test-file imports resolve against the barrel; all `api.*` calls map to `ApiClient` methods.

## Step 6: Generate Implementation — 2026-08-12T11:35:00.000Z

Done. Implementation is complete and verified.

## Summary

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_1256_piano_dealer_institutional_instrument/workspace/implementation/`

**Files (2,285 lines total):**
- `app.py` (37) — Flask app, blueprint registration, envelope-wrapped error handlers (ApiError / HTTPException / catch-all)
- `db.py` (50) — 15 in-memory dict stores (start empty, no seeding), logical clock defaulting to `2026-05-01T00:00:00Z`, `base_fields()` (id/created_at/updated_at/version=1), `touch()` (updated_at refresh + version +1 on every mutation, cascades included)
- `errors.py` (20), `middleware.py` (22) — `X-User-ID`/`X-User-Role` auth (401/403, 9 declared roles)
- `response.py` (70) — scaffold envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), pagination `limit`/`offset`/`total_count`/`has_more` (default 10, 1–100), lists sorted by `created_at` ascending
- `util.py` (144) — Decimal round-half-up, ISO-8601 3-fractional-digit UTC formatting, calendar `add_months`/`whole_months_between`, typed field validators
- `calc.py` (191) — all 8 calculation rules
- `routes/`: clock (17), consignors (47), customers (46), instruments (115), appraisals (148), bids (162), orders (307), delivery (176), services (231), financing (171), warranties (92), restoration (106), events (122)
- `start.sh` (10, guarded pip install + `exec python3 app.py`), `requirements.txt` (1)

**Endpoints:** 79 method+path pairs registered, matching the PRD §4 table exactly.

**State machines:** all 11 implemented — Instrument (8 states incl. RESTORATION_HOLD/REPOSSESSION_HOLD cycles), TradeInAppraisal (with lazy EXPIRED on accept/counter past offered_at+14d), BidPackage (DRAFT→SUBMITTED→APPROVED→AWARDED/LOST, withdraw, return-for-revision, SoD), dual SalesOrder payment×fulfillment tracks, DeliveryJob (incl. FAILED→reschedule), ServicePlan (incl. auto-EXHAUST on every mutation), ServiceVisit, FinancingAgreement (PAID_OFF/DEFAULTED/CONVERTED/CANCELLED-cascade), WarrantyRegistration (lazy EXPIRED on read), RestorationReferral, ShowroomEvent.

**Calculations:** trade-in provisional/final (age floor 0.40, wear %, ±0.15 clamped adjustment, pinned rounding order), consignment payout GROSS/NET split with exact compensating reversal, bid tier+multiplier+ceiling pipeline, order totals (per-line round then sum, inclusive 40% trade-in cap, delivery fee tiers), STANDARD annuity / RENT_TO_OWN 1.2% rent + 60%×24-month-capped purchase credit, whole-calendar-month missed payments, loyalty 10% plan pricing, warranty 24+12-month coverage, artist payout max(guarantee, split×gross).

**Validations:** priority order honored (auth → role → SoD/identity → schema → existence → state → climate → temporal → uniqueness/overlap/capacity → referenced-state → money); OCC `expected_bid_version`/`expected_order_version` → 412; half-open crew overlap with 30-min buffer, closed-interval technician overlap + 4/day UTC cap, half-open room adjacency; all 29 catalog error IDs with correct HTTP statuses.

**Boot verification:** `bash start.sh` boots a fresh process and serves requests (clock endpoint returned `2026-05-01T00:00:00.000Z`). Three smoke batches (100+ assertions) passed end-to-end: full sale→delivery→install→return cascade with payout reversal and risk-score penalties, bid SOD/revision OCC, financing annuity/credit-limit/default repossession, plan exhaustion/loyalty, warranty windows, crew buffer boundaries, referral lifecycle. The only two smoke failures were test-script mistakes (my expected `coverage_end` misread delivered_at; crew-buffer test used a COMPLETED job, which correctly doesn't block) — implementation behavior matched the PRD in both cases.

## Step 7: Run Tests and Iterate — 2026-08-12T11:42:00.000Z

Clean 8-round parallel sweep achieved: all 8 rounds passed 85/85.

## Summary

- **Iterations run**: 2 (initial sweep → 1 fix → verification sweep).
- **Tests deleted**: none.
- **Fixes applied to `test_helpers/`**: 1
  - `/home/ubuntu/github/CodingPRD/tasks/task_1256_piano_dealer_institutional_instrument/test_helpers/fixtures.py`, `deliver_order()` (line 146): `job = run_delivery_job(job_id)` → `job = run_delivery_job(job["id"])`. The fixture referenced an undefined bare name `job_id` instead of the id of the delivery-job dict created on the previous line — a pure `NameError` in helper code. Only `test_09_service_plans.py` uses the `setup_installed_order` → `deliver_order` chain, which is why exactly those 9 tests failed with `NameError: name 'job_id' is not defined` while the other 76 passed. The fix restores the helper's documented behavior (schedule + run a delivery job for a paid order), consistent with the PRD delivery/installation flow.
- **Fixes applied to `implementation/`**: none — the implementation was already PRD-faithful; every failure was the single fixture NameError.

Orchestrator verification: all 8 `results.{1..8}.json` on disk show passed=85 failed=0 total=85 errors=0 skipped=0. Pre-sweep route parity check confirmed 79/79 (method, path) pairs match SCAFFOLD.yaml endpoints exactly (0 missing, 0 extra).

## Step 8: Finalize PRD — 2026-08-12T11:50:00.000Z

PRD_FINALIZED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1256_piano_dealer_institutional_instrument/workspace/PRD_FINALIZED.md` as a byte-identical copy of PRD.md. This is the expected empty-diff outcome.

## Summary

**Line counts / delta**: PRD.md = 332 lines, PRD_FINALIZED.md = 332 lines, 0% delta (`diff -q` confirms byte-identical).

**Changes**: none.

**Analysis of the single Step 7 item**:

- **Subject identified**: `test_helpers/fixtures.py` `deliver_order()` line 146 — `run_delivery_job(job_id)` → `run_delivery_job(job["id"])`.
- **Verification performed**:
  - Read `test_helpers/fixtures.py` in full. The pre-fix code referenced a bare undefined name `job_id`; the function's own local variable is `job` (the delivery-job dict created on the preceding line). This is a pure `NameError` typo in test infrastructure — the helper's docstring ("Schedule + run a delivery job for a paid order") already documented the intended behavior, and the fix restores exactly that.
  - Read PRD §3.6 (Delivery, Installation, and Returns, lines 179-189) and the endpoint table (lines 255-263): the PRD already fully pins the flow the fixture exercises — schedule (`POST /delivery-jobs`, requires `AWAITING_SCHEDULING` + payment in `DEPOSIT_PAID`/`PAID_IN_FULL`/`FINANCED_ACTIVE`, climate check, crew overlap with 30-min buffer), start (`SCHEDULED` → `EN_ROUTE`, order → `OUT_FOR_DELIVERY`), complete (`EN_ROUTE` → `COMPLETED`, order → `DELIVERED` with `delivered_at` stamped, instruments `SOLD` → `DELIVERED`), then installation confirm (`DELIVERED` → `INSTALLED`).
  - Grepped `implementation/routes/delivery.py`: all eight delivery endpoints exist (`create_crew`, `create_job`, `get_job`, `list_jobs`, `start_job`, `complete_job`, `fail_job`, `reschedule_job`) matching the PRD endpoint table exactly. Step 7 applied zero implementation fixes — the implementation was already PRD-faithful.
- **Conclusion**: The item is a pure fixture bug, not a PRD silence or PRD/impl mismatch. No behavioral choice exists that the PRD left open — the helper was simply failing to call the already-PRD-specified API correctly. Per the method's rule ("not every item is a PRD silence — some are pure fixture bugs"), no PRD edit is warranted.

**Pre-edit search log**: no edits were committed, so no (a)/(b)/(c) entries exist. The mandatory enumeration was still performed for the candidate edit subject above (fixture delivery-job chain → PRD §3.6 → `implementation/routes/delivery.py` handlers), and it confirmed the PRD wording already covers every implementation path touching delivery-job scheduling/start/complete, so inserting any additional wording would have risked creating a new mismatch rather than fixing one.

## Step 9: Complete PRD — 2026-08-12T12:10:00.000Z

All changes verified: 29 changed lines, all in-place revisions, no lines added or removed, no new sections. Final summary:

## Summary

**File**: `/home/ubuntu/github/CodingPRD/tasks/task_1256_piano_dealer_institutional_instrument/workspace/PRD_COMPLETED.md`

**Size**: PRD_FINALIZED.md = 332 lines / 56,598 chars → PRD_COMPLETED.md = 332 lines / 61,785 chars (**+5,187 chars, +0 lines** — all edits are inline inserts/revisions within existing paragraphs; no new sections or paragraphs).

**Counts**: 32 changes total — **27 ambiguity-pins** (inserts or inline revisions where PRD was silent), **5 mismatch-revisions** (PRD described behavior impl does not exhibit; revised to impl).

### Mismatch revisions (5)

- §2.1 — revise — mismatch — Consignor self-service restriction now scoped to `GET /consignors/{id}` and `GET /consignors/{id}/instruments`; the general instrument read is role-gated only, no per-record ownership check — `implementation/routes/instruments.py:66-68` vs `routes/consignors.py:12-14,34-47`.
- §2.8 — revise — mismatch — Identity-vs-existence ordering: ownership-first only on the customer-record read and the two consignor endpoints; existence-first (`ERR_NOT_FOUND` ahead of identity check) on appraisal read/counter/accept/decline, order read, installation confirmation, plan/agreement reads, and SoD on bid approval — `routes/customers.py:44-46`, `routes/consignors.py:37-44` vs `routes/appraisals.py:73-76,113-114`, `routes/orders.py:131-133,234-236`, `routes/services.py:80-84`, `routes/financing.py:67-71`, `routes/bids.py:94-98`.
- §3.1 — revise — mismatch — `year_built` is any integer; "four-digit" dropped (no digit-range validation exists) — `routes/instruments.py:28`.
- §3.3 — revise — mismatch — "individual customers carry no institution type" replaced: for individuals `institution_type` is optional, enum-validated when supplied, and stored; also pins non-institutional bid-create → `ERR_INVALID_REQUEST` after FK resolution — `routes/customers.py:16-23,30`, `routes/bids.py:41-44`.
- §3.3 — revise — mismatch — record-outcome requires no identity match against `prepared_by_user_id` (was "the preparing officer") — `routes/bids.py:117-129`.

### Ambiguity pins (27)

- §2.2 — insert — `api_request_timestamp` is read from the logical clock, not wall clock — `response.py:10-14`.
- §2.3 — insert — non-integer/out-of-range `limit`, non-integer/negative `offset` → `ERR_INVALID_REQUEST` — `response.py:32-53`.
- §2.3 — insert — `created_at` sort ties retain insertion order — `response.py:56-58`.
- §2.4 — insert — `created_at`/`updated_at` stamped from the logical clock — `db.py:42-50`.
- §2.5 — insert — clock accepts any instant, forward or backward; no monotonicity check — `routes/clock.py:11-17`.
- §2.6 — insert — calendar-month addition clamps to last day of target month — `util.py:49-55`.
- §2.8 — revise — schema-level `ERR_INVALID_REQUEST`s surface during payload parsing (after path-id existence, before body-FK existence and state checks); principal-mismatch is checked after the order's state precondition — pattern across `util.py:66-124`, `routes/financing.py:40-45`.
- §3.2 — insert — the clamped (not raw) `market_adjustment_pct` is stored on the appraisal — `routes/appraisals.py:99-101`.
- §3.2 — revise — offer expiry boundary: expires only when clock is strictly past `offered_at` + 14 days — `routes/appraisals.py:32-37`.
- §3.3 — revise — revisions permitted only from `SUBMITTED` (else `ERR_BID_NOT_ACTIONABLE`), state check before version check, ceiling re-read at revision time — `routes/bids.py:143-162`.
- §3.4 — revise — `institution_type` required iff `INSTITUTIONAL`; `tax_exempt` defaults false; optional fields accepted for any customer — `routes/customers.py:16-35`.
- §3.4 — revise — amendment semantics: only `items`/`tax_rate`/`distance_miles`/`stairs_count`/`climate_controlled_required` amendable, omitted/null fields unchanged, other fields ignored; payment-state check before stale check; item swap releases old reservations and tolerates instruments already reserved by this order — `routes/orders.py:153-204`.
- §3.5 — insert — order payment `amount_cents` must be a positive integer, else `ERR_INVALID_REQUEST` — `routes/orders.py:212-215`.
- §3.5 — revise — order cancellation leaves `payment_status` at `UNPAID` — `routes/orders.py:292-301`.
- §3.5 — revise — financing application: non-`UNPAID` order → `ERR_ORDER_NOT_PAYABLE`; `term_months` must be positive; `apr` required for `STANDARD`, stored null for `RENT_TO_OWN` — `routes/financing.py:25-58`.
- §3.5 — revise — approving a non-`APPLIED` agreement → `ERR_INVALID_REQUEST` (400) — `routes/financing.py:89-90`.
- §3.5 — insert — zero-`apr` STANDARD degenerates to principal ÷ `term_months`, rounded half-up — `calc.py:130-135`.
- §3.5 — revise — agreement payment on non-`ACTIVE` → `ERR_INVALID_REQUEST` — `routes/financing.py:111-112`.
- §3.5 — revise — declare-default on non-`ACTIVE` → `ERR_INVALID_REQUEST` — `routes/financing.py:151-152`.
- §3.5 — revise — release-hold on non-`REPOSSESSION_HOLD` → `ERR_INSTRUMENT_NOT_AVAILABLE` — `routes/instruments.py:94-102`.
- §3.7 — revise — plan attach on non-`INSTALLED` order → `ERR_DELIVERY_NOT_ACTIONABLE` (409) — `routes/services.py:58-60`.
- §3.7 — revise — technician day-capacity day taken from each visit's `window_start`; fifth booking rejected — `routes/services.py:159-163`.
- §3.7 — revise — visit complete/cancel on non-`BOOKED` → `ERR_INVALID_REQUEST` (400) — `routes/services.py:205-206,222-223`.
- §3.8 — revise — warranty registration on non-`DELIVERED`/`INSTALLED` order → `ERR_DELIVERY_NOT_ACTIONABLE` (409) — `routes/warranties.py:37-39`.
- §3.8 — revise — warranty confirm on non-`PENDING` → `ERR_INVALID_REQUEST` (400) — `routes/warranties.py:85-86`.
- §3.8 — revise — complete-restoration on non-`RESTORATION_HOLD` → `ERR_INSTRUMENT_NOT_AVAILABLE` — `routes/instruments.py:83-91`.
- §3.9 — revise — RSVP `party_size` defaults to 1 and must be ≥ 1, else `ERR_INVALID_REQUEST` — `routes/events.py:84-86`.

All other impl behaviors (every endpoint's role list, 201/200 split, pricing/rounding pipelines, cascade rules, overlap semantics, lazy expirations, terminal states, error codes and statuses) were verified against the PRD and found already uniquely pinned — no change made.
