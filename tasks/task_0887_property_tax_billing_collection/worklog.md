# Worklog — task_0887_property_tax_billing_collection

## Step 1: Create task directory — 2026-07-29T00:00:00.000Z

Output folder pre-created and passed in; Step-1 auto-index scan skipped per orchestrator args. Created `workspace/` subdirectory.

## Step 2: Generate scaffold — 2026-07-29T00:00:00.000Z

All checks pass. The scaffold is complete and lint-clean.

Generated a complete Expert-difficulty scaffold for **Property-Tax Billing & Collection (county treasurer)**:
- `SCAFFOLD.yaml` (§1.0–§1.7 + concurrency rules)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**`scaffold_lint.py` verdict: clean lint** — all 248 §1.8/§1.9 calls conform to §1.5, and every §1.1 FK has reverse-reachability.

### Structural profile
- **Archetype:** ledger_reconciliation + compliance_audit; layers = dual-variant calc, cascading side effects, rate/threshold triggers, optimistic concurrency. Topology **flat** (FK-linked peers under one `/property-tax` prefix); **parallel** state-machine shape; **segregation_of_duties** role model.
- **10 entities:** TaxYear, EscrowAgent, Parcel, TaxBill, Installment, TaxReliefApplication, Payment, LedgerEntry (append-only), Refund, TaxSaleReferral.
- **34 endpoints** (incl. `GET .../payoff` computed read, sub-resource ledger GET, filtered-list reverse GETs, and a `/_clock/set_current_utc` test-driving endpoint with startup default `2026-05-01T00:00:00Z`).
- **7 state machines:** TaxBill has two parallel axes (collection_status × sale_status); TaxReliefApplication is cyclic (UNDER_REVIEW↔INFO_REQUESTED); TaxSaleReferral forks REFERRED→{REDEEMED,SOLD}; plus Installment, Payment, Refund.
- **8 calculations:** bill_levy, installment_split (pinned floor-then-remainder rounding), delinquency_charges (nonlinear penalty+interest w/ cap), payoff_interest (dual-variant), relief_credit (dual-variant), payment_allocation (waterfall), bill_balance, refund_available.
- **22 error codes; 5 roles** (Treasurer, Cashier, CollectionsOfficer, ReliefOfficer opaque; Taxpayer entity_backed:Parcel); **2 OCC concurrency rules** on TaxBill.version.

### Difficulty coverage
All 9 §0.5 rules satisfied with 2 instances each = **18 §1.8 instances**, each with pre-computed literal asserts. **§1.9** adds 28 active breadth instances + 5 exclusion stubs.

All three YAML files parse via yaml.safe_load (dict).

## Step 3: Copy shared files — 2026-07-29T00:00:00.000Z

Copied INSTRUCTION.md into workspace/.

## Step 4: Generate PRD — 2026-07-29T00:00:00.000Z

All verifications pass. Generated workspace/PRD.md for Expert-tier Property-Tax Billing & Collection.
- §1 Introduction; §2 Global Specs (11 subsections: RBAC, response envelope, pagination, common props + append-only ledger, monetary precision, validation ordering, OCC on bills, logical clock, four-eyes SoD, filtered retrieval, ledger conservation invariants); §3 Business Logic (8 subsections); §4 endpoint table (34 endpoints); §5 error table (22 codes).
- 10 entities, 8 calculations, both parallel TaxBill axes, both OCC rules.
- Contracts 1/2/3 all PASS (72/72 field names, all rules & 22 error IDs, §3 path purity).

**Zero-Silence operator note (undeclared constants):** PRD-gen flagged two constants referenced by name with NO declared value in scaffold: `LIEN_REFERRAL_THRESHOLD_CENTS` and `REDEMPTION_PERIOD_DAYS`. Recovered intended values from design test recipes (orchestrator-readable): threshold = 50000 cents (difficulty exact-boundary test line 496 "delinquent_principal exactly 50000 == LIEN_REFERRAL_THRESHOLD_CENTS"); redemption period = 365 days (difficulty line 664 half-open window [2026-01-01, 2027-01-01)). Declared constants already valued: PENALTY_RATE 0.05, INTEREST_RATE_MONTHLY 0.01, DAYS_PER_YEAR 365, INSTALLMENT_COUNT 2.

## Step 4b: Pre-patch undeclared constants into PRD + SCAFFOLD — 2026-07-29T00:00:00.000Z

Patched both PRD.md and SCAFFOLD.yaml before Step 5/6 (per "Scaffold undeclared constants" playbook):
- PRD §3.8: `LIEN_REFERRAL_THRESHOLD_CENTS` → "fifty thousand cents (50000)" + boundary note (exactly 50000 is referred); `REDEMPTION_PERIOD_DAYS` → "three hundred sixty-five days (365)".
- SCAFFOLD.yaml: transition guard `>= LIEN_REFERRAL_THRESHOLD_CENTS (=50000)`; `redemption_deadline = referral_date + REDEMPTION_PERIOD_DAYS (=365)` (both occurrences).
- SCAFFOLD.yaml re-parses OK via yaml.safe_load.

## RESUME (weekly-rate-limit kill at Step 4→5 boundary) — 2026-08-01T00:00:00.000Z

Pipeline resumed from Step 5. On-disk verification: Steps 1–4 + Step 4b complete (SCAFFOLD*.yaml, INSTRUCTION.md, PRD.md present; all 3 YAML parse). Pre-Step-5 undeclared-constant re-scan: the two determinative constants were already pinned in Step 4b — `LIEN_REFERRAL_THRESHOLD_CENTS`=50000 (PRD §3.8 + SCAFFOLD guard/error) and `REDEMPTION_PERIOD_DAYS`=365 (PRD §3.8 + SCAFFOLD computed field ×2). No further undeclared constants found. Proceeding to Steps 5–9.

## Step 5: Generate Unit Tests — 2026-08-01T00:00:00.000Z

Test infrastructure (`test_helpers/`) — 9 files: types.py (10 entity TypedDicts + status/role enums; LedgerEntry append-only, id+created_at only, no version/updated_at per PRD 2.4); api_client.py (one method per endpoint, all paths carry `/property-tax` prefix; GET payoff/list filters via params); api_errors.py (all 22 ApiErrorIds + HTTP-status map); constants.py; factories.py (one payload factory per input entity); assertions.py (per-entity + assert_ledger_balance_conservation / assert_cash_conservation invariants); test_users.py (opaque Treasurer/Cashier/CollectionsOfficer/ReliefOfficer + entity-backed Taxpayer builders, distinct-ID make_* helpers for four-eyes SoD); fixtures.py (composite setups: delinquent-installment, referred-bill, relief-cycle, overpaid-bill, etc.); __init__.py barrel.

Test suite (`test_suite/`) — conftest + 7 domain files, 64 tests: all 18 difficulty instances covered by exactly 2 tests each (36 tests); all 28 non-stub corner instances covered by 1 test each (28 tests). The 5 excluded_because corner stubs not translated (their difficulty owners assert the behavior).

Skips: none — every non-stub instance passed the PRD-first coverage + unique-derivability filter.

Verification: 64/64 collect under pytest; every module imports cleanly; 64/64 carry exactly one verbatim Design: tag resolving to a real instance; 0 verbatim-citation misses; no scaffold/§1.x leakage; no undefined names.

One faithful setup adaptation: corner recipe refund_create_stale_bill_version_rejected reaches the stale version via two partial payments (a first full 400000 payment would drive the bill to PAID and make the second version-bumping payment illegal ERR_BILL_ALREADY_PAID under PRD 3.4) — same rule (ERR_STALE_VERSION), feasible setup.

## Step 6: Generate Implementation — 2026-08-01T00:00:00.000Z

Complete Python + Flask implementation (Expert). Files: app.py (~1050 lines single-file — all routes, ledger engine, state machines, calculations); start.sh (guarded pip install + exec python3 app.py, reads $PORT, binds 0.0.0.0); requirements.txt (flask==3.0.3).

Endpoints: 34 PRD §4 endpoints (all under /property-tax incl _clock/set_current_utc) + 1 root `/` health check = 35 routes. Route-count integrity check confirms all 34 scaffold endpoints present.

Key design decisions:
- Append-only ledger as source of truth — all bill/installment balances derived from LedgerEntry rows each read.
- Logical clock defaults to 2026-05-01T00:00:00Z (never wall-clock); advancing materializes penalty (5% once) + whole-month interest (1%/mo, capped at 100% of principal) idempotently; materialize() also called lazily on reads.
- Derived statuses — installment status per PRD §3.5 (DELINQUENT = clock strictly after due_date AND unpaid principal > 0); collection_status and sale_status computed as two independent axes.
- Money uses Decimal/ROUND_HALF_UP; levy rounds at ÷1000 step; installment split floors per-installment with odd cent on installment 2.
- TaxBill.version bumps only on 5 PRD ops (payment, reversal, refund create, refund approve, referral create); OCC (expected_bill_version) on refund-create and referral-create only.
- Timestamps: created_at/updated_at/api_request_timestamp always 3 fractional digits; business clock values render without fractional seconds when whole (avoids .000Z-vs-Z mismatch class).

Interpretation calls (candidates for Step-9 pinning):
- ABATEMENT ledger entries carry an installment_sequence (per §3.3 per-installment distribution), overriding §2.4's bill-level/null generalization; REFUND stays bill-level (null seq).
- Refund approval: rejects ERR_OVERPAYMENT_UNAVAILABLE when requested > available (mode-specific), else approved_amount_cents = requested.
- Referral gating order follows PRD §3.8 prose (not-delinquent → threshold → window-overlap → stale-version) over scaffold numeric priorities.
- SoD precedes state/business checks on refund-decide and sale.

## Step 7: Run Tests and Iterate — 2026-08-01T00:00:00.000Z

CLEAN FIRST-SWEEP PASS. Baseline single round 64/64 (0 failed/0 errors/0 skipped). Durable 8-round stability sweep run as 2 waves of 4 via sweep.sh (no inline pkill) — results.1.json..results.8.json all 64/64 with statuses={'passed':64}, failed=0 errors=0 skipped=0. Independent re-parse of all 8 files confirms 8-round union failures = NONE; grep of test_suite/ + test_helpers/ finds zero skip/xfail markers.

- Iterations run: 0 (baseline sweep passed).
- Tests deleted: 0.
- Fixes applied to test_helpers/: 0.
- Fixes applied to implementation/: 0.

Step 8 SKIPPED per skip condition (0 deletions, 0 test_suite fixes, 0 test_helpers fixes, 0 implementation fixes → PRD.md already determined every behavior exercised by the tests).

## Step 9: Complete PRD — 2026-08-01T00:00:00.000Z

Full PRD-vs-implementation/ scan → workspace/PRD_COMPLETED.md (source: PRD.md, since Step 8 skipped). Source PRD.md 267 lines / 40208 chars; PRD_COMPLETED.md 267 lines / 42390 chars; char-delta +2182 (all in-paragraph edits, no lines/sections added). Counts: ambiguity-pins = 3, mismatch-revisions = 4.

- §2.4 — revise — mismatch — ABATEMENT distributes per unpaid installment with a real sequence (only REFUND + residual overpayment PAYMENT are bill-level/null) — app.py:1000 vs 1228.
- §2.1 — revise — mismatch — Taxpayer ownership enforced only on write actions; all reads/lists authorize the full role set, unfiltered — app.py:662-678, 730-749, 1096-1115.
- §2.8 — insert — ambiguity — business-clock instants (current_utc, referral_date, redemption_deadline) omit fractional seconds on whole seconds (3 digits otherwise), distinct from always-3-digit system timestamps — app.py:108-112, 1274-1275, 1361.
- §2.9 — insert — mismatch — decision/sale_price_cents body-field validation precedes SoD equality: missing/malformed decision yields ERR_VALIDATION even when four-eyes also violated — app.py:1195-1202, 1324-1330.
- §3.1 — revise — ambiguity — reused parcel_number/servicer_code/year → ERR_VALIDATION (400) — app.py:592, 619, 652.
- §3.4 — insert — ambiguity — residual overpayment recorded as a single bill-level null-sequence negative PAYMENT ledger entry (captured in balance_cents) — app.py:1042-1044.
- §3.5 — revise — mismatch — PAYOFF_QUOTE per-diem computed per installment (own unpaid principal, own due_date, days floored at 0, rounded per installment then summed), falls back to ledger interest when as_of_date absent, echoes as_of_date verbatim even in LEDGER_AS_OF — app.py:767-791.

## PIPELINE COMPLETE — 2026-08-01T00:00:00.000Z

task_0887_property_tax_billing_collection (Expert) resumed from Step-4→5 rate-limit kill and driven to completion. Clean pass: 64/64 x8 rounds, 0 fixes. Deliverables present: SCAFFOLD*.yaml, PRD.md, PRD_COMPLETED.md (no PRD_FINALIZED.md — Step 8 skipped), test_helpers/, test_suite/ (64 tests), workspace/implementation/ (app.py + start.sh + requirements.txt), results.1.json..results.8.json.
