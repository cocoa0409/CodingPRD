# Worklog — task_1082_fine_art_storage_logistics

## Step 1: Create task directory — 2026-07-22T11:10:00.000Z

Used pre-assigned folder tasks/task_1082_fine_art_storage_logistics (skipped Step 1 auto-index scan per instructions). Created workspace/ subdir.

## Step 2: Generate scaffold — 2026-07-22T11:35:00.000Z

Generated a complete Expert-difficulty scaffold for Fine-Art Storage & Logistics. lint clean (257 calls scanned, all FKs reverse-reachable); all 3 files parse.

Scaffold shape:
- 15 entities (flat): Client, Vault, Artwork, StoragePlacement, ConditionReport (immutable event log), Crate, RiggingCrew, TransportJob, Appraisal, InsurancePolicy, LoanAgreement, Carnet, ViewingRoom, ViewingBooking, Invoice.
- 58 endpoints incl. /_clock/set_current_utc (default 2026-05-01T00:00:00Z).
- 14 state machines incl. Artwork parallel custody×condition; LoanAgreement cyclic SUBMITTED↔DRAFT.
- 7 calculations: dual-variant storage_fee (provisional/final), dual-variant appraisal_value (fair-market/replacement), dual-variant transport_charge, tiered insurance_premium, invoice_total (pinned sum-then-tax rounding), vault_occupancy, client_outstanding_balance.
- 24 errors, 21 ordered validations, 5 roles (Registrar, Coordinator, Approver, BillingAdmin opaque; Client entity_backed) with SoD on loan approval.
- 2 concurrency rules: OCC on Artwork.version for appraisal-supersede + policy-supersede, 412.
- Difficulty design: 18 instances (9 rules × 2). Corner: 25 active + 7 excluded stubs.

Constants audit (orchestrator): all calc constants declared. SETUP_BUFFER_MINUTES=60 declared inline in validation check prose (line 975) + error condition; matches design files' pinned 60 — no patch needed.

## Step 3: Copy INSTRUCTION.md — 2026-07-22T11:37:00.000Z

cp INSTRUCTION.md → workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-07-22T11:43:00.000Z

Generated workspace/PRD.md (288 lines, 58 endpoint rows). Design files never opened.
- §1 Intro (2 paras); §2 Global Specs (9 subsections: RBAC, envelope §2.2 verbatim, pagination, common props + logical clock, OCC on artwork version, monetary precision, validation precedence, parallel axes/cascades/conserved ledgers, temporal windowing); §3 Business Logic (8 lifecycle subsections); §4 58 endpoints (4-col table incl clock); §5 24 error codes.
- Contracts PASS: field coverage 88/88 (to_status added to §2.7); rule coverage — all 6 dual/tiered calcs w/ embedded constants (climate 500/800/1200¢, size 1/1.5/2, premium tiers 200/150/100bps at 500,000/5,000,000¢, coverage 1/1.5/2, fragility 1/1.25/1.5, min 5,000¢, crew 9,000¢/hr, rigging 25,000¢, tax 8.75%, 365-day proration, ceil-day, pinned tax-on-subtotal rounding); both OCC rules (expected_artwork_version/ERR_STALE_VERSION/412); SoD; validation priority orderings; §3 path-purity 0 URLs.

## Step 6: Generate implementation — 2026-07-22T11:57:00.000Z

Built complete Python + Flask impl under workspace/implementation/. 58 endpoints (28 POST + 30 GET). Both smoke rounds (84 assertions) passed, 0 server errors.
- Files: start.sh (foreground, $PORT default 10000, 0.0.0.0, guarded pip, exec python3 app.py), requirements.txt (flask==3.0.3), app.py (factory + handlers), store.py (in-memory dicts + logical clock default 2026-05-01T00:00:00Z), errors.py (24 errors), envelope.py, common.py (auth/RBAC/validation/pagination), calc.py (Decimal ROUND_HALF_UP), timeutil.py (ceil-day), domain.py (cascades/ledgers), routes/ (core/storage/valuation/loans/logistics/viewing/billing).
- In-memory only, no seeding. created_at/updated_at wall-clock per §2.4; logical clock for domain.
- Smoke-verified: validation precedence 401→403→404→400→422→412→409; OCC; dual-variant fees; loan SoD + approve→activate(carnet)→return cascade; MAJOR_DAMAGE cascade; crew 60-min buffer; half-open room overlap; conserved ledgers; Client ownership.

## Step 5: Generate unit tests — 2026-07-22T12:13:00.000Z

Generated test_helpers/ (9 files) + test_suite/ (conftest + 7 files, 61 test functions).
- Queue A (Difficulty): 36 tests — all 18 instances × 2. Queue B (Corner): 25 tests — all 25 non-stub instances × 1. Skipped: 0. 7 corner stubs correctly not translated.
- test_01 calculations, test_02 state machines, test_03 cascades/invariants, test_04 loan approval/activation, test_05 placement/transport/viewing guards, test_06 temporal windows, test_07 concurrency/RBAC/listing.
- All byte-compile; 61 collect w/ 0 import errors; no skip/xfail; every docstring has 1 PRD citation + 1 Design: tag resolving to a real instance.

## Step 7: Test-fix iteration loop — 2026-07-22T12:24:00.000Z

All 8 rounds pass 61/61. Clean sweep.
- Iterations run: 2 (baseline sweep + 1 fix + confirming sweep).
- Tests deleted: None.
- Fixes to test_suite/ (STEP 2 — test-vs-PRD identity mismatch): test_03_cascades.py::test_issue_then_void_restores_balance — changed get_client call from role BILL (BillingAdmin) to REG (Registrar). PRD §4 line 200 scopes GET /clients/{id} to Registrar, Client only; BillingAdmin not authorized. PRD-faithful impl correctly returned 403 ERR_UNAUTHORIZED; test was reading client with a role PRD does not permit. Sibling test_voided_invoice_total_preserved passed (only inspects transition response, allowed for BillingAdmin). Fix makes test faithful to PRD RBAC.
- Fixes to test_helpers/: None.
- Fixes to implementation/: None — lone failure was a test-side RBAC identity bug; impl's rejection was PRD-correct, left intact.
- Failure was fully deterministic (all 8 rounds, no flakiness/saturation). Final sweep 61/61 × 8.

## Step 8: Finalize PRD — 2026-07-22T12:26:00.000Z

PRD.md vs PRD_FINALIZED.md: 288 vs 288 lines, byte-identical (0% delta, cmp clean). 0-edit finalize.
- The sole Step 7 fix was a pure test-side RBAC identity bug (test read GET /clients/{id} as BillingAdmin, a role PRD never authorizes). PRD line 200 already scopes GET /clients/{id} to Registrar, Client; impl (routes/core.py:61) enforces auth(["Registrar","Client"]) + Client-owns-record guard (line 62). No PRD silence, no impl/PRD mismatch → PRD_FINALIZED.md is a byte-identical copy of PRD.md (expected outcome).

## Step 9: Complete PRD scan — 2026-07-22T12:28:00.000Z

PRD_FINALIZED.md 288 → PRD_COMPLETED.md 288 lines; char delta 39,948 → 40,767 (+819). 3 ambiguity-pins + 1 mismatch-revision.
- §2.3 Pagination — insert — out-of-range limit/offset silently clamped (not rejected); non-integer → ERR_VALIDATION (common.py:110-120, :100-107).
- §3.5 Appraisal & Insurance — revise — coverage duration = exact elapsed fractional days (total_seconds/86400, no ceil); only storage-fee day counts are ceiled (calc.py:58).
- §3.6 Loans/Carnets — insert — coordinator direct carnet discharge only from ACTIVATED; still-ISSUED carnet can only be expired (routes/loans.py:254; allowed {(ACTIVATED,DISCHARGED),(ISSUED,EXPIRED)}).
- §3.8 Billing — revise — invoice aggregation date basis (placement by released_at, job by scheduled_end), inclusive [billing_period_start, billing_period_end], line_items order (released placements → completed jobs → manual, each in creation order) (routes/billing.py:14-54).
- Left unchanged (verified non-load-bearing): created_at ordering (=_seq under stable sort), crew OFFLINE (no endpoint), opaque description/coa_number strings, additive list filters. All formulas/state machines/validation precedence/OCC/cascades/ledgers already matched impl uniquely.

## PIPELINE COMPLETE — 2026-07-22T12:28:00.000Z

Expert task_1082_fine_art_storage_logistics: 61/61 × 8 rounds clean. NOT strictly clean (1 test_suite RBAC identity fix; 0 impl fixes, 0 deletions). Step 8 0-edit; Step 9 = 4 pins (3 ambiguity + 1 mismatch). Final artifacts: SCAFFOLD*.yaml, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, test_helpers/, test_suite/, workspace/implementation/.
