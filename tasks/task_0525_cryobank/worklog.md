# Worklog — task_0525_cryobank

## Step 1: Create task directory — 2026-07-01T12:13:00.000Z

Created `tasks/task_0525_cryobank/` and `tasks/task_0525_cryobank/workspace/`. Output folder pre-specified; ID scan skipped. Expert difficulty to be passed to scaffold generator.

## Step 2: Generate Scaffold — 2026-07-01T12:29:00.000Z

The 28 GETs are the read/reverse-reachability surface (2 per entity), and 35 mutating endpoints drive the 9 state machines. The count reflects a genuinely broad but tightly-coupled domain, and the lint confirms every FK is reverse-reachable and every design-file call resolves. The scaffold is complete and internally consistent.

Generated a complete Expert-difficulty scaffold package for **task_0525_cryobank** (Cryobank & Donor Gamete Bank). All three files parse, and `scaffold_lint.py` returns **VERDICT: clean lint** (471 calls scanned across §1.8+§1.9, all conform to §1.5; all 18 FKs reverse-reachable).

**SCAFFOLD.yaml** (§1.0–§1.7):
- **14 entities**: Donor, ScreeningApplication, Specimen, DonorInventory, Recipient, RecipientConsent, VialReservation, Shipment, StorageAccount, StorageInvoice, SiblingRegistryEntry, RegulatoryReport, plus CollectionAppointment and DewarMaintenanceWindow (two distinct temporal-overlap semantics).
- **9 state machines**: ScreeningApplication (branching approve/defer), Specimen (fork to RELEASED/DISCARDED), RecipientConsent, VialReservation (HELD→CONFIRMED→SHIPPED with cancel/expire), Shipment, StorageAccount (cyclic ACTIVE↔LAPSED), SiblingRegistryEntry, and the two window entities.
- **5 calculations**: `storage_bill` (dual-variant RENEWAL-proration vs LAPSE), `inventory_availability` (dual-variant BOOKING vs SETTLEMENT), `family_limit_gate` (`>=` threshold), `overlap_detection` (half-open no-buffer room vs closed buffered dewar), `report_snapshot`.
- **1 concurrency rule**: OCC on `DonorInventory.version` for reservation supersede (412).
- **16 validations**, **63 endpoints** (35 mutating / 28 GET; api_prefix root `""`), **20 errors**, **6 roles** (ScreeningOfficer, LabTech, ComplianceOfficer, CatalogManager, Recipient [entity_backed], BillingClerk).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml**: **18 instances** = 2 per each of 9 Difficulty Rules. Formula-derived asserts pre-computed as literals.

**SCAFFOLD_CORNER_DESIGN.yaml**: **24 active instances + 6 `excluded_because` stubs**, spanning entities, state_machines, calculations, validations, endpoints, rbac, cross-cutting (OCC success + stale-412), and errors.

## Step 3: Copy INSTRUCTION.md — 2026-07-01T12:30:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0525_cryobank/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-07-01T12:35:00.000Z

Generated `workspace/PRD.md` from the cryobank scaffold. 5 top-level sections; §2 has 10 subsections (RBAC, response envelope, pagination, common props, nested retrieval, state/cascade integrity, OCC, billing precision, positive-integer/interval rules, validation ordering); §3 has 11 domain-derived subsections; §4 64-row endpoint table; §5 20-row error table. 308 lines total. Hard Contracts all PASS (field-name coverage, rule coverage incl. OCC + 5 calc constants + dual-variant billing + booking/settlement views + family-limit `>=` + cascades + report snapshots; §3 path purity 443 tokens, 0 violations). Confirmed SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml NOT read.

## Step 5: Generate Unit Tests — 2026-07-01T12:49:00.000Z

**Stage 1 — `test_helpers/` (9 files):** types.py (15 entity TypedDicts + status/role enums), api_client.py (one method per PRD endpoint incl `/_clock`), api_errors.py (20-error catalog + HTTP-status registration), assertions.py (per-entity + `assert_inventory_pool_conserved`), factories.py, constants.py (billing/hold/buffer thresholds), test_users.py (5 opaque roles + `make_recipient_headers` for entity_backed:Recipient), fixtures.py (tiered composite setups + deferral cascade helper), __init__.py barrel.

**Stage 2 — `test_suite/` (conftest + 7 test files, 57 test functions):**
- Queue A (Difficulty): **17 of 18 instances translated, 2 tests each = 34 tests.**
- Queue B (Corner): **23 of 24 non-stub instances translated, 1 test each = 23 tests.** 6 `excluded_because:` stubs verified as cross-refs, not translated.

**Skipped (2 instances, PRD-first filter failures):**
1. Difficulty/compensating_invariant/billing_periods_conserved_lapse_then_pay — `paid_through == 2028-06-01` not uniquely derivable (PRD §3.7 never specifies initial `paid_through`).
2. Corner/state_machines/assess_lapse_before_grace_returns_error — outcome depends on same unspecified initial `paid_through`.

**Adjudication note:** retest-vs-quarantine priority-pair used `validate_error_is_one_of([ERR_RETEST_NOT_NEGATIVE, ERR_QUARANTINE_NOT_ELAPSED])` (PRD names both, no precedence). consent-vs-family-limit kept exact `ERR_CONSENT_MISSING` (PRD §2.10/§3.4 fix ordering). All 57 tests carry verbatim PRD citation + exactly one `Design:` tag; no skip/xfail; syntax + pyflakes clean.

## Step 6: Generate Implementation — 2026-07-01T12:50:00.000Z

Built Python + Flask in-memory REST API at `workspace/implementation/` (17 files). start.sh (guarded pip install → `exec python3 app.py`), requirements.txt, app.py, db.py (in-memory, fresh per boot), clock.py (settable logical clock, default 2026-05-01T00:00:00Z), errors.py, response.py (exact envelope), middleware.py (X-User-ID/X-User-Role auth), validate.py, domain.py, billing.py, routes/ (14 entity families + `_clock`).

- **63 endpoints** implemented. **8+ state machines** with cascades (donor deferral → specimen discard → reservation void → shipment cancel → inventory freeze).
- storage_bill dual-variant (RENEWAL prorated Decimal round_half_up vs LAPSE full; period-0 = 84000 for 2 vials). inventory_availability BOOKING (3) vs SETTLEMENT (5). family_limit_gate `>=` delists. overlap_detection ROOM half-open no-buffer vs DEWAR closed 24h buffer. OCC on reservation-create (412) + validation ordering verified.
- start.sh reads `$PORT` (default 10000), binds `0.0.0.0`, foreground via `exec`. Fresh-boot verified, no state carry-over.

## Step 7: Diagnostic loop — 2026-07-01 (2 iterations)

Baseline: 6 stable failures (51/57) across all 8 rounds. Fixes:
- impl `routes/storage.py`: `/storage-accounts/{id}/renew` and `/assess-lapse` now return the *issued invoice* (was returning the account). PRD §3.7 / endpoint table: these actions "issue a RENEWAL/LAPSE invoice"; the invoice's billing_mode/amount_cents are the salient output. Fixes 3 KeyError('billing_mode'/'amount_cents') failures.
- test_helpers `fixtures.py` `setup_lapsed_account`: now pays the period-0 invoice first to establish paid_through (period_start+365=2027-06-01 for default ship_clock), so assess-lapse at lapse_clock=2027-07-01 clears grace (paid_through+30d). Previously paid_through was never set, so assess-lapse always returned ERR_GRACE_NOT_ELAPSED. PRD §3.7-faithful (lapse gate requires now >= paid_through+30d; paid_through only exists after a paid invoice). Fixes 2 setup failures.
- DELETED test_specimen_discard_cascade_cancels_reservation_and_dispatched_shipment (test_04). PRD §3.2 line 135 cascades the DISPATCHED-shipment cancellation only to a "just-cancelled reservation" (HELD/CONFIRMED). But a DISPATCHED shipment always has a SHIPPED reservation (dispatch drives CONFIRMED→SHIPPED atomically, §3.6), and SHIPPED reservations are never voided. The DISPATCHED branch is therefore unreachable via specimen-discard; the assertion cannot pass under any PRD-faithful impl (UNREACHABLE-BRANCH / non-unique-derivability, STEP 1b). The PREPARING branch remains covered by test_specimen_discard_cancels_confirmed_reservation_and_preparing_shipment.

Result: 8/8 parallel rounds pass 56/56.

## Step 8: Finalize PRD — 2026-07-01T13:05:00.000Z

PRD.md = 308 lines; PRD_FINALIZED.md = 308 lines; delta = 0 lines (single in-place edit, char-delta only).

**Change:** §3.7 (Storage Billing) — revise — appended a sentence pinning that `/storage-accounts/{id}/renew` and `/storage-accounts/{id}/assess-lapse` return the newly issued `StorageInvoice` (with `billing_mode` and `amount_cents`) in `data`, not the storage account, overriding the §2.2 default for these two operations only — `implementation/routes/storage.py:62,81`.

**Disposition of Step 7 items:**
1. renew/assess-lapse return invoice → PRD silence → 1 edit made.
2. `setup_lapsed_account` fixture fix → pure fixture bug (§3.7-faithful) → no PRD edit.
3. DELETED test_04 (DISPATCHED-shipment discard cascade) → unreachable branch; PRD §3.2 already correct, impl matches → no PRD edit.

Pre-edit search scoped the override to "these two operations only" so it does not wrongly claim `dispatch`/`close` (which also issue invoices) return the invoice — those return the path resource per §2.2 default.
