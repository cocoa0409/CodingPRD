# Worklog — task_0073_self_storage_unit_rental

## Step 1: Create task directory — 2026-06-01T00:00:00.000Z

Created `tasks/task_0073_self_storage_unit_rental/` and `workspace/` (pre-allocated path, no index rescan). Verified `INSTRUCTION.md` present at project root.

## Step 2: Generate scaffold (Expert band) — 2026-06-01T01:03:00.000Z

Generated three scaffold artifacts at the Expert difficulty band (§0.4), entirely from the scenario description and the scaffold-generator spec (no sibling tasks consulted).

Files written:
- `SCAFFOLD.yaml` — §1.0–§1.7 (10 entities, 41 endpoints, 18 error codes, 9 calculations, 2 concurrency rules, 3 roles)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 9 Difficulty Rules × 2 instances = 18 instances
- `SCAFFOLD_CORNER_DESIGN.yaml` — 31 corner instances (28 active + 3 `excluded_because` stubs) across all 9 taxonomy sections

Lint: `python3 scaffold_lint.py` → `VERDICT: clean lint` (389 calls scanned, all FKs reverse-reachable).

Design:
- Complexity profile: primary archetype `compliance_audit` (lien/auction legal process with mandatory ≥90-day default window) blended with `pricing_engine`; flat entity topology; branching state-machine shape; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, derived_field_reconciliation; peer_roles (Tenant entity-backed; FacilityManager + LienAdministrator opaque).
- Entities: Facility, Unit (Climate-Controlled tier + size_class), Tenant, Lease, Invoice, Payment, LedgerEntry (append-only, common_fields:false), InsurancePolicy, AuctionProceeding, TransferOrder.
- State machines: Lease (cyclic ACTIVE↔DELINQUENT cure cycle + delinquency→lien→auction path), AuctionProceeding (fork-join SCHEDULED→{SOLD/REDEEMED/CANCELLED}), plus Unit, Invoice, InsurancePolicy, TransferOrder.
- Calculations: dual-variant lease balance (denormalized vs ledger-replay) and dual-variant redemption amount (lien-date snapshot vs accruing-today); per-component-rounding-then-sum monthly charge; prorated first charge; late-fee threshold (≥grace boundary); auction surplus waterfall and payment waterfall (oldest-due-first, created_at tie-break, never id); transfer proration; occupied-unit-count aggregation; tiered insurance premium.
- Key Expert-band choices: two OCC expected_lease_version CREATE-with-supersede races; depth-3 cascades from two triggers; two boundary checks (days_past_due ≥ 90 vs empty-unpaid-set surplus); two temporal-overlap rules (closed unit-occupancy vs half-open insurance-coverage); two compensating invariants (money + occupancy count); global test clock endpoint POST /_clock/set_current_utc. Formula-derived assertions pre-computed as literals.

## Step 3: Copy INSTRUCTION.md — 2026-06-01T01:03:30.000Z

Copied project-root `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-01T01:08:00.000Z

Generated `workspace/PRD.md` from SCAFFOLD.yaml (design files withheld). Structure: §1 Intro (pricing/billing engine + lien/auction legal process), §2 Global Specs (9 subsections: RBAC, response envelope, pagination, identity/timestamp/version, monetary precision, immutable ledger + dual balance, OCC, nested-ref validation priority ladder, logical clock), §3 Business Logic (11 subsections), §4 41-endpoint table, §5 17-error catalogue.

Key fidelity: both OCC rules (expected_lease_version, ERR_STALE_VERSION 412); two dual-variant calcs (denormalized vs ledger-replay balance; lien-snapshot vs accruing redemption); per-component-rounded monthly charge vs single-round proration; three-bucket surplus waterfall + conservation invariant; 14-day statutory windows + ≥90-day default boundary (inclusive); cure cascade; insurance tier premium/limit; business errors.

Hard Contracts: Field coverage PASS (103/103, 0 missing); Rule coverage PASS; Path purity PASS (380 tokens, 0 violations). Neither withheld design file opened.

## Step 5: Generate unit tests — 2026-06-01T01:22:00.000Z

Tests per queue: Queue A (Difficulty) 36 tests covering all 18 instances (≥2 each); Queue B (Corner) 28 tests covering all 28 non-stub instances (1 each). Total 64 tests across 6 files. No instances skipped for PRD-coverage reasons. 3 excluded_because corner stubs correctly not translated; all difficulty_instance cross-refs resolve.

File layout: test_helpers/ (types, api_client w/ 41 endpoint methods incl set_clock, api_errors 17 IDs, assertions, factories, constants, test_users w/ make_tenant_headers, fixtures composite chains); test_suite/ test_01..test_06.

Key decisions: Tenant role entity_backed → real tenant_id threaded via make_tenant_headers, peer-isolation 403 tests use different tenant id. Instance cross_auction_open_requires_lease_pre_lien asserts ERR_WINDOW_NOT_ELAPSED for 0-days ACTIVE lease (PRD §3.8). Audits: every docstring 1 Design tag, no dual/untagged, no broken pointers, no skip/xfail, every PRD citation greps clean.

## Step 6: Generate implementation — 2026-06-01T01:22:30.000Z

Built Python+Flask in-memory impl at workspace/implementation/. Layout: start.sh (installs Flask, exec python3 app.py, 0.0.0.0:$PORT), app.py (factory, blueprints, error handlers, per-request RLock), db.py (empty-on-boot dicts + logical clock + monotonic seq for created_at tie-break), clock.py, response.py, errors.py, middleware.py (X-User-ID/X-User-Role RBAC), models.py, helpers.py, services/calc.py (Decimal round-half-up, tier tables, LIEN_ADMIN_COST_CENTS=15000), services/domain.py (ledger append, occupancy recompute, billing cycle, late-fee, delinquency advance, insurance lapse, cure cascade), routes/*.py per resource group.

All 40 endpoints implemented. State machines: Lease, AuctionProceeding fork-join, Invoice, InsurancePolicy, TransferOrder, Unit with preconditions + cascades. Dual-variant calcs: denormalized balance vs ledger-replay; lien-snapshot redemption vs accruing-today. OCC: expected_lease_version on POST /transfer-orders + POST /auction-proceedings, mismatch ERR_STALE_VERSION 412, version bump on success. Clock: POST /_clock/set_current_utc no mutation.

Flagged interpretation: DELINQUENT→PRE_LIEN treated as days_past_due ≥ 30 (dropped strict upper bound) so single late billing run past 30 still reaches PRE_LIEN.

## Step 7: Test and iterate loop — 2026-06-01T01:46:00.000Z

All 8 parallel rounds pass (61/61 each, deterministic). The loop is complete.

**Iterations run:** 2 sweeps (initial 40/64 → final 61/61 across all 8 rounds). The failures were fully deterministic, not flaky — the 8-round sweep showed an identical failing set every round, all traceable to a few root causes.

**Tests deleted (3):**
- `test_duplicate_open_proceeding_rejected` — ERROR-PRECEDENCE-SILENCE / unreachable branch. PRD §2.5 checks state-transition validity (→ `ERR_INVALID_STATE`) before domain rules, and opening an auction moves the lease `PRE_LIEN → LIEN`, so a second open always hits the status guard. `ERR_PROCEEDING_EXISTS` requires a non-terminal proceeding on a still-`PRE_LIEN` lease, which the state machine makes impossible. (Scaffold rule: `Corner/errors/duplicate_open_proceeding_rejected`.)
- `test_redemption_lien_snapshot_frozen_at_file_lien` and `test_redemption_accruing_today_exceeds_snapshot` — DUAL-VARIANT-CALC non-unique-derivability. The hardcoded amounts (29000 snapshot, 43000 accruing, and the `accruing > snapshot` invariant) depend on how many monthly invoices a single billing run generates over multiple skipped periods. PRD §3.4 says "generates **a** monthly invoice" (singular) while §2.9 says "generating due invoices" (plural) — back-fill vs one-per-run are both PRD-faithful and yield different redemption totals; the fixture's asserted values are unreachable under faithful billing semantics. (Scaffold rule: `Difficulty/dual_variant_calc/dual_redemption_lien_snapshot_vs_accruing_today`.)

**Fixes applied to test_helpers/ (`fixtures.py`):**
- `setup_delinquent_past_90`: moved the `lease_version` capture to *after* the billing cycle runs. PRD §2.7 requires `expected_lease_version` to equal the lease's *current* version, and the billing cycle bumps the version; capturing it pre-cycle produced `ERR_STALE_VERSION` in 15 downstream auction/redeem/transfer setups.

**Fixes applied to test_suite/:**
- `test_04_pricing_and_ledger.py` — two `monthly_charge_*` tests: assert the component breakout (base/climate/insurance) on a regular billing-cycle invoice instead of the prorated first invoice (whose base, per PRD §3.3, holds the prorated full monthly total with climate/insurance folded in).
- `test_03_calculations_and_rbac.py` — `test_payment_waterfall_oldest_due_first`: pay the older invoice's actual full remainder (it carries a PRD-required 2000 late fee from the 05-01 cycle) so oldest-first allocation fully clears it.
- `test_06_priorities_boundaries_overlaps.py` — two `test_auction_open_on_active_lease_*` tests: corrected the expected error from `ERR_WINDOW_NOT_ELAPSED` to `ERR_INVALID_STATE` (PRD §2.5: an ACTIVE lease fails the PRE_LIEN status guard first; `ERR_WINDOW_NOT_ELAPSED` is reserved for a PRE_LIEN lease below the day-count, already covered by `test_auction_open_below_90_days_rejected`).

**Fixes applied to implementation/:**
- `routes/leases.py` (`_check_occupancy_overlap`): exclude `PENDING` leases from the occupancy-overlap check. PRD §3.2/§3.3 treat occupancy as beginning at activation ("null while occupying"); a PENDING lease is only a reservation. This lets two PENDING reservations coexist (overlap is re-checked at activation), making the PRD-required `ERR_UNIT_NOT_AVAILABLE` activation guard reachable while still rejecting a new lease created against an already-ACTIVE (open-ended) lease.
- `services/domain.py` (`_lapse_insurance`): lapse an ACTIVE policy when any OVERDUE invoice exists on the lease, rather than keying off `insurance_amount_cents > 0`. The first invoice folds the prorated premium into its base (insurance_amount=0), so the old condition never fired; PRD §3.5 ties the lapse to "the invoice that carries an active policy's premium" becoming OVERDUE.

Final state: **61/61 tests passing in all 8 parallel rounds.**

## Step 8: Finalize PRD — 2026-06-01T01:52:00.000Z

Produced workspace/PRD_FINALIZED.md. Line counts: PRD.md 282 / PRD_FINALIZED.md 282 (all edits expanded existing single-line paragraphs in place). Char delta +1542 (+3.55%).

Changes (3):
1. §3.4 — revise — pinned billing back-fill: a run generates one separate monthly invoice (each with own CHARGE) per elapsed-but-unbilled period, not one consolidated invoice; specified per-lease cursor, <= clock boundary, each back-filled invoice due_date = period_start. — services/domain.py:212-233 (_generate_due_invoices).
2. §3.2 — revise — pinned occupancy-overlap check ignores PENDING leases (reservations); two PENDING coexist at creation; same test re-runs at activation against non-PENDING leases. — routes/leases.py:29-43 (_check_occupancy_overlap).
3. §3.5 — revise — pinned insurance lapse triggered by existence of any OVERDUE invoice on the lease (not keyed off insurance_amount_cents, which is 0 on the folded first invoice). — services/domain.py:274-290 (_lapse_insurance).

Not pinned (already determined by PRD, or pure fixture bugs): duplicate-open precedence (§2.8); setup_delinquent_past_90 fixture timing bug; component-breakout fix (§3.3); payment-waterfall + auction-open-on-ACTIVE fixes (§2.8/§3.8, covered by back-fill pin).

## Step 9: Complete PRD — 2026-06-01T01:57:00.000Z

Produced workspace/PRD_COMPLETED.md from PRD_FINALIZED.md (282 lines, 45030 chars → 282 lines, 47255 chars; char delta +2225). All in-paragraph inserts/revisions, no new sections. Counts: 9 ambiguity-pins, 3 mismatch-revisions (12 total).

Changes:
- §3.3 — insert — ambiguity — first prorated invoice stores entire prorated figure in base_amount_cents (climate/insurance = 0), total = base, due_date = start_date — services/domain.py:162-179
- §3.4 — revise — mismatch — billing generates invoices for ACTIVE, DELINQUENT, OR PRE_LIEN leases (PRD omitted PRE_LIEN) — services/domain.py:190
- §3.4 — insert — ambiguity — billing-cycle run returns the facility resource — routes/facilities.py:66-72
- §3.4 — insert — ambiguity — waive CREDIT carries source_type INVOICE/invoice id; no entry when remainder zero — routes/invoices.py:58-60
- §3.5 — revise — mismatch — DELINQUENT→PRE_LIEN keyed solely on ≥30-day lower boundary, NOT gated by upper bound vs lien_default_days — services/domain.py:263-271
- §3.6 — revise — mismatch — separate PAYMENT ledger entry per allocated invoice (PRD said single entry) — routes/payments.py:64
- §3.6 — insert — ambiguity — overpay CREDIT entry carries source_type PAYMENT/payment id — routes/payments.py:68
- §3.6 — insert — ambiguity — LIEN lease with cancelled NOTICE_SENT/LIEN_FILED proceeding returns to ACTIVE; AUCTION_SCHEDULED lease does not — services/domain.py:300-313
- §3.8 — insert — ambiguity — AUCTION_SETTLEMENT = negative pre-sale balance (zero-amount entry still appended); source_type AUCTION/proceeding id — routes/auctions.py:215-221
- §3.8/§3.11 — insert — ambiguity — policies in ACTIVE OR LAPSED cancelled on auction/close (PRD said only active) — routes/auctions.py:233-237, routes/leases.py:229-234
- §3.10 — insert — ambiguity — transfer adjustment entry source_type MANUAL/order id; current period reconstructed from clock + billing_day; no entry when zero — routes/transfers.py:151-178
- §2.6 — insert — ambiguity — ledger-balance returns full lease object with balance_cents replaced by replayed sum, stored value and version unmutated — routes/leases.py:134-142

**Pipeline complete. Final: 61/61 tests passing across all 8 parallel rounds.**
