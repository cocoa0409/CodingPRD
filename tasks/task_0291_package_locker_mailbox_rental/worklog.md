# Worklog — task_0291_package_locker_mailbox_rental

## Step 1: Create task directory — 2026-06-11T02:28:06.000Z

Created `tasks/task_0291_package_locker_mailbox_rental/` and `tasks/task_0291_package_locker_mailbox_rental/workspace/` (pre-assigned task directory; index not scanned/incremented).

## Step 2: Generate scaffold (Expert) — 2026-06-11T02:53:29.000Z

All three scaffold artifacts are generated and lint-clean. Summary below.

### Generation Report — task_0291_package_locker_mailbox_rental (Expert tier)

**Lint:** `VERDICT: clean lint` — all §1.8/§1.9 calls conform to §1.5 and every §1.1 FK has reverse-reachability in §1.5 (559 calls scanned).

**Archetype:** quota_allocation + compliance_audit; flat topology (`api_prefix: ""`), parallel/cyclic state shape; peer_roles.

**Entities (13):** Facility, LockerUnit, MailboxUnit, Customer, Form1583, AuthorizedRecipient, RentalAgreement, Package, MailItem, ForwardingRequest, Invoice, LedgerEntry, Payment.

**State machines (6):** Form1583 (branching-with-revert cycle SUBMITTED→{VERIFIED,REJECTED}→resubmit), RentalAgreement (cyclic ACTIVE↔SUSPENDED + renewal self-loop + abandonment), Package (branching fork-join NOTIFIED→{PICKED_UP,FORWARDED,RETURNED,ABANDONED}), ForwardingRequest (linear-with-hold), MailboxUnit, LockerUnit.

**Key calculations (7):** oversize_fee (3-input tiered+cap), overstay_fee (provisional vs final variants), prorated_refund (chronological vs forward_looking variants), invoice_balance (round-per-line-then-sum), autopay_capture (depth-3 cascade tail), forwarding_fee, facility_locker_counts. Two OCC concurrency rules (renew/pickup stale-version, 412).

**Counts:** 13 validations · 17 error codes · 55 endpoints · 3 roles (FacilityOperator/Customer/ComplianceOfficer).

**Difficulty design (§1.8):** 9 rule_ids × 2 = **18 instances**, all formula-derived asserts precomputed as literals (e.g. oversize 610, overstay 600→1500, refund 7000 vs 6000, autopay 2110).

**Corner design (§1.9):** **36 instances** total = 32 active + 4 `excluded_because` stubs (each pointing to a real §1.8 instance), spanning entities/state_machines/calculations/validations/rbac/cross_cutting/errors/consistency_model.

All grounds resolve into §1.1–§1.7; names unique across both design files; no forbidden concurrency vocabulary; split-file keys isolated to their own files.

Files: SCAFFOLD.yaml (1453 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1277 lines), SCAFFOLD_CORNER_DESIGN.yaml (1467 lines).

## Step 3: Copy INSTRUCTION.md — 2026-06-11T02:53:47.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-11T02:59:05.000Z

Generated `workspace/PRD.md` (290 lines) from SCAFFOLD.yaml. Design YAMLs (DIFFICULTY/CORNER) were NOT read.

**Section list:** §1 Introduction; §2 Global Specs (2.1 RBAC, 2.2 API Response Structure verbatim, 2.3 Pagination, 2.4 Resource Identity/Timestamps/Versioning, 2.5 OCC on Guarded Writes, 2.6 Facility Logical Clock & Sweeps, 2.7 Cascading State/Hierarchical Consistency, 2.8 Nested Retrieval & Reference Validation, 2.9 Monetary Amounts/Counts/Rounding, 2.10 Validation Ordering); §3 Business Logic (3.1 Facility Setup & Inventory, 3.2 Customers & Form 1583, 3.3 Rental Agreement Lifecycle, 3.4 Package Receipt/Notification/Resolution, 3.5 Oversize & Overstay Fees, 3.6 Invoicing/Ledger/Autopay/Payments, 3.7 Mail/Forwarding/Scanning/Proration); §4 Endpoint Definitions (57 endpoints); §5 Error Code Catalogue (17 errors).

**Hard Contract reports:** Field coverage 64/64 PASS; Rule coverage (13 validations, 2 OCC, 6 state machines, 7 calculations, 17 errors, cascades, sibling-branch symmetry) PASS; Path purity (§3, 443 tokens, 0 path/method tokens) PASS. §2.2 verified byte-for-byte. No design YAMLs / sibling tasks read.

## Step 5: Generate unit tests — 2026-06-11T03:15:31.000Z

Generated complete test infrastructure, translating only the two design indices (PRD-first filter applied throughout).

**test_helpers/ (9 files):** `__init__.py` (barrel), `types.py` (12 entity TypedDicts + 9 status enums; `AuthorizedRecipient`/`LedgerEntry` correctly omit `updated_at`/`version`), `api_client.py` (one method per endpoint, ~50 methods), `api_errors.py` (17 errors + HTTP-status registration), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque FacilityOperator/ComplianceOfficer + entity-backed `make_customer_headers`), `fixtures.py` (5-tier composite setup helpers).

**test_suite/ (8 files):** `conftest.py` + 7 domain-named test files.

**Total tests: 69** (36 queue-A tags, 33 queue-B tags).
**Queue A (Difficulty):** All 18 instances covered with ≥2 tests each (9 rules × 2), incl. `no_locker_available_empty_pool_on_receipt`.
**Queue B (Corner):** All 32 non-stub instances covered with ≥1 test each.
**Skipped:** None of the non-stub instances. The 4 `excluded_because:` stubs correctly NOT translated (all 4 cross-refs resolve to real difficulty-design instances).
**Verification:** All files compile; 0 skip/xfail; every test carries exactly one `Design:` tag resolving to a real instance; all 85 PRD citations verified verbatim; all `api.*` calls and `test_helpers` imports resolve; no scaffold/§-references in emitted code.

## Step 6: Generate implementation — 2026-06-11T03:15:31.000Z

Built complete Python + Flask implementation in `workspace/implementation/` (26 files): `app.py`, `start.sh`, `requirements.txt`, foundation modules (`db.py`, `errors.py`, `response.py`, `middleware.py`, `common.py`, `serializers.py`, `constants.py`, `clock.py`, `calculations.py`), 9 route blueprints under `routes/`, 4 services under `services/`.

**Endpoints implemented: 55** — all PRD §4 routes across Facility/clock, LockerUnit, MailboxUnit, Customer, Form1583+recipients, RentalAgreement, Package, MailItem, ForwardingRequest, Invoice/LedgerEntry, Payment.
**State machines (6):** Form1583, RentalAgreement (PENDING_AUTH→ACTIVE↔SUSPENDED→CLOSED/ABANDONED + renewal self-loop), Package (RECEIVED→NOTIFIED→PICKED_UP/FORWARDED/RETURNED/ABANDONED, locker release on every terminal), ForwardingRequest, MailboxUnit, LockerUnit — with all cross-entity cascades.
**Calculations:** oversize (tiered bucket ceil + cap), overstay (calendar-day IANA tz, provisional vs final), prorated refund (chronological posted + forward-looking quoted, round-half-up Decimal), invoice balance (round-per-line-then-sum), autopay capture cascade, forwarding fees, facility locker counts. Clock sweep: provisional-overstay recompute, package abandonment, balance-driven suspension, term-lapse abandonment. OCC on renew/pickup; validation priority order + 17-error catalogue honored.
**Storage in-memory only** (dicts in `db.py`, empty on boot, no seeding/SQLite/JSON). **`start.sh` reads `$PORT` (default 10000), binds `0.0.0.0`, runs foreground via `exec`**, guards `pip install` on flask import check.

## Step 7: Test and iterate to PASS — 2026-06-11T03:20:57.000Z

All 8 parallel rounds pass 69/69. Clean sweep achieved (verified: results.1–8.json all 69/69).

**Iterations run:** 2 (1 baseline diagnostic sweep + 1 confirming sweep after the fix). Final result: all 8 parallel rounds pass 69/69.

**Tests deleted:** None. (No PRD-silence or unique-derivability collapse was found.)

**Fixes applied to test_helpers/:** None.

**Fixes applied to test_suite/:**
- `test_05_billing_and_proration.py` :: `test_refund_quote_does_not_change_state` — changed the setup from `autopay_enabled=False` to `autopay_enabled=True`. STEP-2 test bug: the test's intent (verified verbatim in PRD §3.7 line 206, "A what-if quote is also available without changing any state") is to confirm the read-only refund-quote endpoint mutates no agreement state. But its setup created a 9,000-cent unpaid RENTAL balance (monthly 3000 × term 3, autopay off) and then advanced the clock 20 days. Per PRD §3.3 line 156 ("the clock sweep suspends one automatically when its invoice balance climbs past the suspension threshold of 5,000 cents"), the sweep correctly drove the agreement ACTIVE→SUSPENDED at the `advance_clock` step — before `refund_quote` was ever called. So the assertion `status == "ACTIVE"` failed deterministically in all 8 rounds for a reason unrelated to the rule under test. Enabling autopay captures the RENTAL charge at activation (balance → 0 ≤ threshold), so the clock advance leaves the agreement ACTIVE and the test now isolates the refund-quote's no-op property. The refund-quote math is independent of autopay, so the test remains a faithful translation of the PRD rule.

**Fixes applied to implementation/:** None. The implementation was PRD-faithful throughout — the suspension behavior the test tripped over is exactly what PRD §3.3 mandates.

**Key finding:** The single failure was deterministic (8/8 rounds, not flaky). Root cause was a test-fixture precondition that collided with a PRD-required sweep side-effect, not an implementation defect. Per the cardinal rules, the PRD-required suspension check in `services/sweep.py` was preserved and the offending test setup was fixed instead.

## Step 8: Finalize PRD — 2026-06-11T03:23:19.000Z

**Outcome: no edits.** `PRD_FINALIZED.md` is a verbatim copy of `PRD.md` (290 lines each, 0% delta; `diff` confirms identical). The single Step 7 diff item was a pure test-fixture bug (autopay_enabled False→True) with 0 implementation fixes, 0 deletions — no PRD-silence or PRD-mismatch to pin.

**Per-edit pre-edit search log (no edits — behaviors confirmed already determined by PRD):**
1. Suspension threshold = 5,000 cents — `constants.py:25`, `services/sweep.py:48` (strict `>`), `routes/agreements.py:197` (reactivation gate). PRD §3.3 line 156 already fixes "5,000 cents", "climbs past" (strict `>`), and reactivation-while-exceeding rejection. Determined.
2. Autopay capture at activation drives balance to zero — all `capture_autopay` callsites: `routes/agreements.py:145,172`, `routes/packages.py:159,190`, `routes/mail.py:161`, `services/agreements.py:114`; rule body `services/billing.py:36-58`. PRD §3.3 line 152 + §3.6 line 192 enumerate every capture site + the capture-exactly-the-balance rule. Determined.
3. RENTAL charge at activation = `monthly_fee_cents × term_months` — `routes/agreements.py:143-144`. PRD §3.3 line 152 states this verbatim. Determined.
4. refund-quote is read-only — `routes/agreements.py:85-104` (no mutation; computes both refund variants via `calculations.py:35-53`). PRD §3.7 line 206 states "available without changing any state" + names both fields. Determined.

## Step 9: Complete PRD — eliminate residual ambiguity/mismatch — 2026-06-11T03:27:27.000Z

Produced `PRD_COMPLETED.md` from `PRD_FINALIZED.md` via full PRD-vs-implementation scan.

**Source vs output:** PRD_FINALIZED.md = 290 lines / 47,303 chars; PRD_COMPLETED.md = 290 lines / 48,188 chars; char delta +885; 5 lines changed (all in-paragraph inserts, no new sections).

**Counts:** 5 ambiguity-pins, 0 mismatch-revisions. (No impl behavior contradicted the PRD; all five gaps were silences admitting multiple readings.)

**Per-change list:**
- §3.2 Customers — insert — ambiguity — Suspending a non-`ACTIVE` (already `SUSPENDED`) customer is rejected with `ERR_INVALID_STATE`; PRD only described `ACTIVE → SUSPENDED` — `routes/customers.py:72-73`
- §3.4 Package Receipt — insert — ambiguity — Locker assignment scoped to same `facility_id`; when multiple `AVAILABLE` lockers of the tier qualify, picks earliest-created (`created_at` asc, then insertion order) — `routes/packages.py:50-55`
- §3.4 Pickup — insert — ambiguity — Owning-agreement "`ACTIVE` or `SUSPENDED`" gate fails with `ERR_INVALID_STATE` — `routes/packages.py:149-150`
- §3.6 Manual payments — insert — ambiguity — Manual payment against an invoice with `balance_cents` ≤ 0 is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE` — `routes/billing.py:77-81`
- §3.7 Refund quote — insert — ambiguity — Quote uses facility `current_utc` as close-moment; optional `basis` hint never alters response (both figures always returned); not-yet-activated agreement (`term_start` null) quotes both figures as `0` — `routes/agreements.py:91-104`

**Areas checked, left unchanged (PRD already pins):** validation-priority ordering (§2.10), OCC guarded writes, all fee/proration formulas + constants, autopay cascade, suspension/reactivation/abandonment thresholds + sweep order, cascade side-effects, ledger `source_ref` semantics, clock stamping, payment method enum, mailbox/locker out-of-service errors, customer self-registration note.

---

## Pipeline complete

All 9 steps finished. Final state: **69/69 tests pass across all 8 parallel stability rounds.** Task directory `tasks/task_0291_package_locker_mailbox_rental` contains SCAFFOLD.yaml + 2 design YAMLs, test_helpers/ (9 files), test_suite/ (8 files), workspace/ (PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, INSTRUCTION.md, implementation/ with results.1–8.json all 69/69).
