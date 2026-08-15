# Worklog — task_1698_office_furniture_dealer_space_planning

## Step 1: Create Task Directory — 2026-08-14T08:59:00.000Z

Task directory `tasks/task_1698_office_furniture_dealer_space_planning/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per command args; verified both directories exist and are empty.

## Step 2: Generate Scaffold — 2026-08-14T10:08:00.000Z

## Task 1698: office_furniture_dealer_space_planning — scaffold complete

**Files written** (under `/home/ubuntu/github/CodingPRD/tasks/task_1698_office_furniture_dealer_space_planning/`):
- `SCAFFOLD.yaml` (2,042 lines) — §1.0–§1.7 only
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1,935 lines) — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (3,588 lines) — single key `scaffold_corner_design`

**Counts**
- Entities: **15** (Dealership, Customer, PricingContract, SpacePlan, Typical, ProductSeries, ProjectOrder, OrderLine, Crew, InstallEvent, StagingReservation, PunchItem, ManufacturerClaim, AssetTag, LiquidationLot)
- State machines: **13**, incl. cycles (SpacePlan revision loop, Claim negotiation counter-cycle, PunchItem verify-fail reopen), parallel dimensions (ProjectOrder.status × computed install_posture), and compound/posture gating (BLOCKED by CRITICAL punch)
- Calculations: **12**, incl. dual-variant pairs (liquidation estimate-vs-final credit; provisional-vs-confirmed lead time), combinatorial modes (a) tiered contract pricing, (b) pinned per-unit rounding (16668 vs 16667), (c) pinned rollup evaluation order (fee band → credit cap → grand total)
- Validations: **9** priority tiers with pinned sub-orders
- Endpoints: **91** (flat topology, `/api/*`; FK reverse-reachability via filtered lists)
- Error catalog: **31** (every code has a triggering instance)
- Roles: **11** (all opaque; segregation-of-duties on contract activate and credit issue via X-User-ID comparison)
- Concurrency rules (§1.2.1): **2** OCC rules (contract amend, lot appraisal), both 412/ERR_STALE_VERSION
- §1.8 instances: **23** (9 rule_ids; rule minimums exceeded for rules 2, 3, 5, 7)
- §1.9 instances: **66 active + 12 excluded_because stubs** across all nine claim-extraction-guide sections

**Verification**
- `scaffold_lint.py` verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1,102 calls scanned)
- All assert literals pre-computed in Python (money: 60500/66000 net tiers, 5150000/3072500/245800/829575/2488725 rollup, 800000 final credit, 302500 restock fee; dates: 2026-09-17 vs 2026-10-07 promise variants, appraisal +30/+31 sweep boundary)
- No forbidden concurrency vocabulary; no `${var}` unbound; every error code referenced; role names consistent across §1.5/§1.7/design files

**Design adjudications made**
1. **Flat topology** (`/api/<collection>` with FK filters) per skill's diversity guidance; `api_prefix: /api`.
2. Warehouse folded into Dealership (capacity config); reconfiguration folded into InstallEvent (`kind: RECONFIGURATION` + `asset_moves`) to stay at 15 entities while covering the whole scenario sentence.
3. Two genuine supersede races only (contract amend, lot re-appraisal) per §1.2.1's serial-observability filter; everything else demoted to state preconditions.
4. Overlap semantics deliberately differentiated: Crew = exclusive half-open minutes + 30-min turnover buffer; staging = inclusive date ranges with per-day aggregate capacity (equality allowed).
5. Replacement claim lines are warranty-priced at zero so the depth-3 settle cascade moves `promised_date`/event confirmations without perturbing the credit invariant.
6. Logical clock endpoint added (`/_clock/set_current_utc` + `GET /api/_clock`, fixed default `2026-08-01T00:00:00Z`) driving contract-expiry and appraisal-validity sweeps deterministically.

Note: the task directory already contained a pre-existing `worklog.md` and `workspace/` (dated before my writes); I left them untouched.

## Step 3: Copy Shared Files — 2026-08-14T10:10:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1698_office_furniture_dealer_space_planning/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T10:18:00.000Z

## PRD Generation Summary — task_1698_office_furniture_dealer_space_planning

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1698_office_furniture_dealer_space_planning/workspace/PRD.md`
**Line count:** 347

**Section list:**
- §1. Introduction (3 paragraphs)
- §2. Global Specifications
  - 2.1 User and Role-Based Access Control (11 roles, all opaque identity, attribution fields named)
  - 2.2 API Response Structure (emitted verbatim from `section-2.2-response-structure.md`)
  - 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending)
  - 2.4 Common Resource Properties (id UUID, created_at/updated_at 3-fraction-digit ISO 8601, version integer; all 16 entities carry the set)
  - 2.5 Monetary Precision and Rounding (integer cents, round-half-up, per-unit-then-extend pin, per-event labor pin)
  - 2.6 Optimistic Concurrency Control (amend + appraise only; distinguishes OCC from version-pinning)
  - 2.7 The Logical Clock and Automatic Sweeps (default 2026-08-01T00:00:00Z; contract and lot sweeps)
  - 2.8 Validation Ordering (priorities 1–9 with explicit sub-orderings 5a–5d, 7a–7g, 8a–8g)
  - 2.9 Warehouse Capacity as a Daily Aggregate
  - 2.10 The Customer Credit Ledger (conserved-quantity principle)
- §3. Business Logic & Workflows (10 subsections, organized by business-process timeline):
  - 3.1 Dealership Setup, Catalog, and Crews
  - 3.2 Customers and Their Standing
  - 3.3 Pricing Contracts and Space Plans
  - 3.4 Ordering Against a Contract and an Approved Plan
  - 3.5 Warehouse Receipt and Staging
  - 3.6 Installation Scheduling and Execution
  - 3.7 Punch Items, Manufacturer Claims, and Quality Holds
  - 3.8 Credit Application to Orders
  - 3.9 Used-Furniture Liquidation and Trade-In Credit
  - 3.10 Asset Inventory and Reconfiguration Service
- §4. Endpoint Definitions (4-column table, 90 rows)
- §5. Error Code Catalogue (2-column table, 31 errors)

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + endpoints[].input identifiers: 107 required, 107 present, 0 missing
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 647
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Zero-Silence Rule coverage audit (Contract 2):**
- **Validations with priority (1–9):** all 9 groups expressed in §2.8 with explicit sub-orderings (5a SoD → 5b quality hold → 5c crew suspension → 5d BLOCKED posture; 7a–7g; 8a–8g); "money rules last" stated.
- **Concurrency rules (2):** `contract-amend-stale-version` and `lot-appraisal-stale-version` both expressed in §2.6 and restated at their workflow homes in §3.3 / §3.9, each naming the OCC field (`expected_contract_version`, `expected_lot_version`), the error `ERR_STALE_VERSION`, and HTTP 412, with no race-condition framing.
- **State-machine transitions (13 machines, ~60 transitions):** every from→to pair named in §3 prose; preconditions paired with their error IDs; side effects (pin set/clear, `revision_no` increment, line status cascades, claim auto-creation on CRITICAL verify, quality-hold cascade, replacement-line spawn, CONFIRMED→TENTATIVE promise-date demotion, customer-ledger credit on CREDIT remedy, hold/release/close customer flows, crew suspend/activate, all staging transitions including DAMAGED→auto-punch, line→RECEIVED bubble-up, order→DELIVERED/INSTALLED auto-advance) all stated.
- **Calculations (10):** `configured_unit_list_price`, `contract_net_unit_price` (tier resolution with inclusive min_qty, 55% cap, default fallback), `per_line_extension_rounding` (pinned per-unit-then-extend), `order_total_rollup` (pinned 7-step order; fee band 8/12 at 5,000,000 cents; floor on credit cap), `lead_time_provisional` (STEELCASE sums, MILLERKNOLL max), `lead_time_confirmed` (business-day, Mon–Fri, day-after anchor, no holidays), `install_event_labor_cost` (rate override chain, premium-minute formula, basis-point multiplier), `staging_capacity_utilization` (both-bounds-inclusive, equality allowed, RESERVED+OCCUPIED only), `liquidation_credit_valuation` (both variants: estimated grade-B/75,000/20% haircut; final 15% fee then per-item refurb 5,000/15,000/25,000 floored at 0; A/C estimate catalog values also surfaced), `customer_credit_ledger` (all four sum terms plus the conservation property), `restocking_fee` (25,000-cent minimum, 20% of unreceived ACKNOWLEDGED-net, ledger-first debit), `order_install_posture` (all five postures in precedence order). All formulas translated to natural language with no operator syntax or fuzzy words.
- **Endpoint side effects:** every endpoint's side-effect list is reflected in §3 narrative (e.g., amend copies unspecified fields and bumps the amended contract's version; manual lot redeem forfeits the remainder; FIFO lot consumption by `created_at` ascending on apply_credit).
- **Structured field content:** defaults (after_hours_start_minute 1080, multiplier 15000 bp, turnover 30, credit_cap 25, affected_units 1, revision_no 1, quality_hold false, is_replacement false, origin MANUAL, liquidation_credit_balance_cents 0, estimated/final credit fields) and asset-tag source-driven initial status (PURCHASED→IN_SERVICE, TRADED_IN→IN_STORAGE) all expressed.
- **Sibling-branch symmetry:** cancel from DRAFT / SUBMITTED / ACKNOWLEDGED each given equal density; close from DELIVERED and INSTALLED both gated identically and stated; the three remedy branches (REPLACE / CREDIT / REPAIR) each described; provisional vs confirmed lead-time variants and estimated vs final valuation variants each given parallel treatment.

**Adjudications made:**
1. **§2.8 sub-ordering rendering** — the scaffold's priority-5/7/8 entries bundle several error IDs into one rule with lettered sub-clauses; I rendered each lettered sub-clause as an explicit prose item so the relative order is unambiguous, per the skill's Contract 2 example.
2. **Roles all opaque** — the scaffold marks all 11 roles `identity: opaque`; §2.1 states this in one consolidated paragraph plus a list of the four attribution fields (`created_by_user_id`, `activated_by_user_id`, `appraised_by_user_id`, `issued_by_user_id`) where the server does record the header value, satisfying the identity-translation requirement without 11 repetitive sentences.
3. **Unit-conversion constants** — fee band ($50,000 = 5,000,000 cents), restocking minimum ($250 = 25,000 cents), and the after-hours default (1080 minutes = 18:00) are stated in both raw-constant and business terms so the test-relevant numbers survive verbatim while the prose stays natural.
4. **§2.2** emitted verbatim (including `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `UNIQUE_ERROR_IDENTIFIER_STRING`, empty `data`).
5. **Endpoint table "Any"** — all GET endpoints authorize all 11 roles; the table renders this as "Any" (matching the example PRD convention) while §2.1 states the full enumeration and the all-GETs-readable rule.
6. **One audit-repair pass needed**: `provisional_lead_time_days` was initially missing; added in §3.4 where the provisional lead-time rule is defined.

## Step 5: Generate Unit Tests — 2026-08-14T11:05:00.000Z

Generation complete for task_1698. Final report:

## test_helpers/ (9 files)
All under `/home/ubuntu/github/CodingPRD/tasks/task_1698_office_furniture_dealer_space_planning/test_helpers/`:
- `types.py` — 14 status/field enums + role enum; TypedDicts for all 15 entities (all carry the full common field set per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (~75 methods)
- `api_errors.py` — all 31 error IDs + HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` plus `assert_order_totals_invariants`
- `factories.py` — 15 payload factories, input fields only
- `constants.py` — PRD-pinned constants (MAX_DISCOUNT_PCT 55, fee band 5,000,000/8%/12%, restock 20%/25,000, liquidation valuation schedule, dealership defaults, clock default)
- `test_users.py` — `TEST_USERS` for all 11 opaque roles + `make_<role>_headers(user_id)` builders + `NO_AUTH_HEADERS`
- `fixtures.py` — tiered composites: `setup_catalog`, `setup_draft/submitted/acknowledged_order`, `setup_delivered_order`, `setup_installed_order`, `setup_verified_punch`, `setup_customer_credit`, event/staging/claim walkers; SoD-safe user ids by construction (creator ae-1 vs activator co-1, appraiser la-1 vs issuer fm-1)
- `__init__.py` — barrel export

## test_suite/ (10 files)
`conftest.py` + `test_01_foundation_and_catalog.py` (12), `test_02_contracts_and_plans.py` (12), `test_03_order_pricing.py` (10), `test_04_order_lifecycle.py` (17), `test_05_staging_and_capacity.py` (12), `test_06_install_events_crews.py` (12), `test_07_punch_and_claims.py` (15), `test_08_credit_and_liquidation.py` (12), `test_09_security_rbac.py` (9).

## Counts
- **Total: 111 tests** — Queue A (Difficulty): 46 (23 instances × 2); Queue B (Corner): 65 (65 non-stub instances × 1). All 14 `excluded_because:` stubs verified to resolve to real difficulty instances and were not translated.

## Instances skipped (PRD-first filter)
- `Corner/entities/customer_computed_field_input_ignored` — PRD never states whether a client-supplied computed field on create is ignored or rejected; two faithful readers diverge. Gap left as a gap.
- `Difficulty/transitive_cascade/claim_settle_replace_cascade` — **partially** translated: hops 2–3 (replacement line advances `promised_date` → demotes CONFIRMED events) skipped. PRD §3.4 defines `promised_date` as "the latest confirmed_promise_date ... falling back to ... provisional ... when no confirmed dates exist", which a second reader can read as never advancing once any line is acknowledged; not uniquely derivable. Hop 1 (SETTLED + warranty-zero OPEN replacement line recorded on the claim) is covered verbatim by §3.7 and emitted as the instance's two tests.

## Notable correction
`order_rollup_pinned_evaluation_mode_c`'s precomputed `grand_total_cents == 3322300` is arithmetically inconsistent with the PRD formula it cites (net 3,072,500 + fee 245,800 = **3,318,300**, which the instance's own downstream values 2,488,725/395,425 confirm). The test asserts the PRD-derived 3,318,300.

## Stage-2 self-audit verdict: PASS
- Every test docstring ends with exactly one `Design:` line resolving to a real instance; queue A ≥2/instance, queue B ≥1/non-stub instance (scripted check: 88 tags, 0 invalid, 0 stub leakage).
- Citation pass: all 153 long quoted spans (≥8 words) survive whitespace-normalized literal match against PRD.md; asserted error IDs are named in PRD prose with trigger conditions; precedence tests (priority pairs) rest on §2.8's explicit ordering.
- Two-reader relaxations applied: `order_created_with_initial_state` asserts `version` is an integer rather than `== 1` (PRD never pins the initial value); `fk_reverse_reachability_filtered_lists` assertions hold whether or not undocumented filter params are honored.
- No `skip`/`skipif`/`xfail` markers; no scaffold/table terminology in generated code; all files compile; `pytest --collect-only` yields 111 tests.

## Step 6: Generate Implementation — 2026-08-14T11:05:30.000Z

The implementation is complete and verified. Summary:

## Files created

All under `/home/ubuntu/github/CodingPRD/tasks/task_1698_office_furniture_dealer_space_planning/workspace/implementation/` (~3,000 lines total):

- `start.sh` — executable; guarded `pip install` (no-op when Flask importable), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=2.2`
- `app.py` — Flask entry point, blueprint registration, ApiError/404/405/500 handlers producing the scaffold error envelope
- `db.py` — in-memory store: 15 entity collections as dicts keyed by id, plus monotonic insertion sequence for stable `created_at` ordering. **Zero seeding** — store is empty at every boot (verified: create → reboot → list returns 0)
- `errors.py` — all 31 error IDs with exact HTTP statuses (note: `ERR_SOD_VIOLATION` is 403 per PRD §5/error catalog, not the 409 shown in the validations-table row)
- `response.py` — envelope: `meta{api_request_id, api_request_timestamp}` + `response_type` + `data`; list responses add `limit/offset/total_count/has_more` in meta
- `middleware.py` — `X-User-ID`/`X-User-Role` presence (400), role-list membership (403); all 11 roles; GETs open to all
- `validate.py` — strict body/field validators (bool excluded from int), pagination (limit default 10, 1–100; offset ≥ 0; violations → 400)
- `util.py` — UUID ids, 3-fractional-digit UTC timestamps, logical clock (default exactly `2026-08-01T00:00:00Z`, never wall-clock), exact integer round-half-up, calendar/business-day arithmetic
- `services/core.py` — entity lifecycle (`version` starts at 1, +1 per mutation incl. cascades, once per request per resource via a request-scoped touch set), FK lookups, and the derived-field recomputes: order rollup, credit cap (floor), promised_date, install_posture, line receipt bubble-up, customer credit ledger (conserved formula incl. manual-redeem forfeiture and restocking-fee debits), lot FIFO consumption + rollback, plan budget
- `services/pricing.py` — configured unit list price, tier resolution (inclusive `min_qty`), per-unit-then-extend rounding, STEELCASE-sum/MILLERKNOLL-max lead days, business-day confirmed promises, once-per-event labor cost, restocking fee, liquidation estimate/final valuation, 30-day appraisal validity
- `routes/` — 15 resource modules + shared helpers

## Endpoint count

**91 routes**, matching the 91 rows in the scaffold endpoint table (creates 201, transitions 200, lists with filters/pagination, `POST /api/_clock/set_current_utc` with both sweeps).

## Scaffold-section → module mapping

- §1.1 entities → `db.py` collections + per-route field assembly in `routes/`
- §1.2 state machines → transition guards (`ERR_INVALID_STATE` on non-existent transitions) + side effects in `routes/*` and cascades in `services/core.py`
- §1.2.1 OCC rules → `expected_contract_version` on amend, `expected_lot_version` on appraise (both → 412 `ERR_STALE_VERSION`)
- §1.3 calculations → `services/pricing.py` + rollup/posture/ledger in `services/core.py`
- §1.4 validation priority → explicit ordered checks in every handler (auth → existence → state → SoD/safety → temporal → linkage → structural → money)
- §1.5 endpoints/RBAC → route decorators with per-endpoint role lists
- §1.0/§2.2 envelope → `response.py`

## Verification

Three smoke rounds (~165 assertions) all pass against live boots: full order lifecycle (DRAFT→SUBMITTED→ACKNOWLEDGED→DELIVERED→INSTALLED→CLOSED), pricing math with pinned rounding order, both lead-time variants, capacity equality allowed, turnover-buffer overlap (adjacent-at-buffer OK), DAMAGED auto-punch, CRITICAL verify cascade → auto-claim + quality_hold, claim negotiation cycle, REPLACE replacement-line cascade with event demotion, CREDIT remedy ledger credit, SoD gates (403), OCC (412), supersede cascades, credit cap/insufficient funds (422), apply→cancel conservation (balance restored exactly, FIFO pool rolled back), restocking fee debit, sweep boundary semantics (effective_to == today stays ACTIVE; appraised_at+30 == today stays APPRAISED). The one smoke "FAIL" was a wrong expectation in my own script (a CREDIT_ISSUED lot is correctly not swept — only APPRAISED lots expire).

## Key adjudications (documented in code comments)

1. **promised_date** — per-line fallback (confirmed else provisional, max over non-CANCELLED lines); the literal "only when no confirmed exist" reading would make the REPLACE promise-advance/demote cascade unreachable.
2. **Restocking-fee ledger debit** — scaffold's conserved ledger formula has no fee term, so fee debits are tracked via an internal `_fee_debits` accumulator subtracted in the balance derivation; `cancel_fee_cents` records the full fee.
3. **Lot FIFO rollback on cancel** — per-order `_lot_consumption` is reversed on cancel (internal fields are underscore-prefixed and stripped from serialization) so the FIFO pool stays consistent with the restored balance; manual-redeem forfeitures are not resurrected.
4. **Receive once per reservation** — `receive` is allowed only from `RESERVED` (PRD: "Receiving … on a RESERVED reservation"); partial line receipts accumulate across multiple reservations.
5. **Clock regression** → `ERR_INVALID_REQUEST` (PRD says the clock "advances"); equality allowed.
6. **Line-create gate order follows PRD prose** (quality_hold → discontinued → typical mismatch) where it differs from the scaffold's 7b/7c sub-order, per the PRD-wins rule.
7. **`asset_moves` rejected on NEW_INSTALL** ("RECONFIGURATION only"); `claimed_amount_cents`/`settlement_amount_cents` must be positive ints per the catalog's "non-positive amount" rule.
8. **Replacement lines** get provisional lead times anchored at creation date (empty options) so the promised-date cascade can advance; `selected_options=[]`.
9. `clear_quality_hold` allowed regardless of series status (flag is orthogonal to status per PRD §3.1).

## Step 7: Run Tests and Iterate — 2026-08-14T11:32:00.000Z

All 8 rounds passed cleanly: 111/111 tests in every round, zero failures, zero flakiness. Exit condition met.

## Summary

- **Iterations run**: 1 (a single 8-round parallel stability sweep; all rounds completed, `passed == total == 111` in each of `results.1.json` through `results.8.json`).
- **Tests deleted**: none — every assertion traced to verbatim PRD prose (each test's docstring quotes its governing PRD sentence) and no PRD-silence or unique-derivability collapse was observed.
- **Fixes applied to `test_helpers/`**: none required. The fixtures/factories were already PRD-consistent (e.g., SoD user-id separation between contract creator/activator and lot appraiser/issuer is structurally enforced; `Connection: close` on the shared API client session eliminates ECONNRESET races against per-test server restarts).
- **Fixes applied to `implementation/`**: none required. The pre-existing implementation under `/home/ubuntu/github/CodingPRD/tasks/task_1698_office_furniture_dealer_space_planning/workspace/implementation/` (91 routes, in-memory store, logical clock with sweeps, OCC, SoD, validation-priority ordering, pinned rounding) passed all 888 test executions (111 tests × 8 rounds) under per-test-server isolation with no flaky failures — no timing-sensitive bugs, fixture-ordering issues, or port collisions surfaced.

The benchmark task is stable and complete as-is.

## Step 8: Finalize PRD — 2026-08-14T11:33:00.000Z

SKIPPED per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes. PRD.md already determined every behavior the implementation exhibits; no PRD_FINALIZED.md produced.

## Step 9: Complete PRD — 2026-08-14T11:55:00.000Z

All edits verified. The work is complete.

## Summary

**Source vs. output:** `PRD.md` = 347 lines / 60,029 chars → `PRD_COMPLETED.md` = 349 lines / 65,793 chars (delta +2 lines, +5,764 chars; 31 diff hunks, all in-paragraph inserts/revisions — no new sections, no deletions of requirement prose).

**Counts:** 31 ambiguity-pins, 4 mismatch-revisions (35 changes total).

**Changes:**

- §2.1 — insert — ambiguity — header values stripped of surrounding whitespace; whitespace-only counts as empty — `middleware.py:33-35`
- §2.3 — insert — ambiguity — non-integer limit/offset, limit outside 1–100, negative offset → `ERR_INVALID_REQUEST`; sort ties broken by insertion order — `validate.py:103-123`, `services/core.py:61`
- §2.3 — insert — ambiguity — exact-match query filters enumerated per collection; `has_more` = (offset + returned) < total_count — `routes/helpers.py:18-28`, `response.py:28`
- §2.4 — **revise — mismatch** — "sixteen entities" → "fifteen" (only 15 named/implemented) — `db.py:6-22`
- §2.7 — insert — ambiguity — clock never moves backward (earlier/malformed `to_iso8601` → `ERR_INVALID_REQUEST`, equal accepted); clock endpoints return `{current_utc}` — `routes/clock.py:39-56`
- §2.10 — insert — ambiguity — restocking-fee debits added to ledger outflows — `services/core.py:210-211`
- §3.1 — insert — ambiguity — dealership numeric fields non-negative integers; `credit_cap_pct` ≤ 100 — `routes/dealerships.py:19-24`
- §3.1 — insert — ambiguity — `option_catalog` required (may be empty); option/price/lead fields non-negative integers — `routes/product_series.py:19-43`
- §3.1 — revise — ambiguity — discontinue only from `ACTIVE` (else `ERR_INVALID_STATE`); clear-quality-hold succeeds unconditionally — `routes/product_series.py:79-93`
- §3.1 — insert — ambiguity — crew `size` integer ≥ 1 — `routes/crews.py:21`
- §3.2 — insert — ambiguity — customer close only from `ACTIVE` (else `ERR_INVALID_STATE`); balance check precedes open-orders check — `routes/customers.py:86-95`
- §3.3 — insert — ambiguity — tier `min_qty`/`discount_pct` and `default_discount_pct` non-negative integers — `routes/contracts.py:30-42,63`
- §3.3 — revise — mismatch(+ambiguity) — amend: missing/non-integer `expected_contract_version` → `ERR_INVALID_REQUEST`; amendable from `DRAFT` or `ACTIVE`; successor always copies `customer_id`/`contract_type`, records amender as creator, returned 201; "amended contract remains ACTIVE" → status unchanged by amendment — `routes/contracts.py:150-201`
- §3.3 — revise — ambiguity — `approved_version` pinned to the approval-incremented (post-mutation) version — `routes/space_plans.py:75-78`
- §3.3 — insert — ambiguity — `target_budget_cents_per_instance` ≥ 0 — `routes/space_plans.py:112`
- §3.4 — insert — ambiguity — contract/plan need only exist at order creation; states first enforced at submit — `routes/orders.py:64-69`
- §3.4 — insert — ambiguity — `selected_options` required array (may be empty); line priced at creation — `routes/order_lines.py:57-62,81`
- §3.4 — insert — ambiguity — submit also recomputes `promised_date` — `routes/orders.py:158`
- §3.4 — **revise — mismatch** — `promised_date` = per-line max of (confirmed else provisional) dates, mixing kinds, not "fallback only when no confirmed dates exist" — `services/core.py:131-142`
- §3.4 — revise — ambiguity — line cancel requires line `OPEN` and order `DRAFT` — `routes/order_lines.py:104-107`
- §3.4 — insert — ambiguity — cancel from `DRAFT` leaves line statuses unchanged — `routes/orders.py:219-225`
- §3.4 — **revise — mismatch** — full computed fee recorded as `cancel_fee_cents`; ledger debit capped at available balance (PRD said only the remainder is recorded) — `routes/orders.py:231-247`
- §3.5 — insert — ambiguity — `received_units` must be an integer (else `ERR_INVALID_REQUEST`); `condition` free-form non-empty; only exact `DAMAGED` triggers the cascade — `routes/staging.py:120-125,139`
- §3.5 — insert — ambiguity — auto-created DAMAGED punch has `affected_units` 1 — `routes/staging.py:141-150`
- §3.6 — insert — ambiguity — `asset_moves` on `NEW_INSTALL` → `ERR_INVALID_REQUEST`; `labor_hours_estimated` non-negative number — `routes/install_events.py:92-96`
- §3.6 — insert — ambiguity — strict-overlap collision semantics; merely abutting (buffer-widened) windows do not collide — `routes/install_events.py:33-49`
- §3.6 — insert — ambiguity — confirm re-checks order still `ACKNOWLEDGED`/`DELIVERED` (else `ERR_INVALID_STATE`) and excludes itself from overlap — `routes/install_events.py:141-154`
- §3.6 — insert — ambiguity — `labor_hours_actual` required non-negative number (else `ERR_INVALID_REQUEST`) — `routes/install_events.py:198-200`
- §3.7 — insert — ambiguity — auto-claim `series_id` null / claimed amount zero when punch names no line; amount uses line's current `unit_net_price_cents` — `routes/punch_items.py:104-119`
- §3.7 — insert — ambiguity — punch `affected_units` ≥ 1 — `routes/punch_items.py:50`
- §3.7 — insert — ambiguity — manual claim `claimed_amount_cents` ≥ 1; `settlement_amount_cents` ≥ 1 — `routes/claims.py:43,103`
- §3.7 — insert — ambiguity — replacement line carries no `selected_options`/`typical_id`; provisional lead time + promise date computed from its series anchored at the acceptance date — `routes/claims.py:138-159`
- §3.8 — insert — ambiguity — `amount_cents` integer ≥ 1 — `routes/orders.py:258`
- §3.9 — insert — ambiguity — missing/non-integer `expected_lot_version` → `ERR_INVALID_REQUEST`; `appraised_value_cents` ≥ 0; `appraised_at` in YYYY-MM-DD form — `routes/liquidation_lots.py:71-84`
- §4 — insert — ambiguity — unmapped paths / unsupported methods → `ERR_NOT_FOUND` (404) — `app.py:31-37`

**Notable judgments:** The two genuine semantic mismatches were the `promised_date` rollup (impl mixes confirmed/provisional per line, which the replacement-line demotion cascade depends on) and cancel-fee recording (impl records the full fee on the order; ledger debit is `min(fee, balance)` — corroborated by `test_04` asserting the full 302,500). State-machine transitions, all calculation formulas (tier resolution, rounding order, fee bands, labor costing, lead-time rules, liquidation valuation), OCC guards, sweep rules, and the §2.8 priority ordering all matched the PRD as written and were left untouched.
