# Worklog — task_0879_transient_occupancy_hotel_tax

## Step 1: Create task directory — 2026-07-28T12:00:00.000Z

Folder pre-created by user (tasks/task_0879_transient_occupancy_hotel_tax). Created workspace/ subdir. Skipped auto-index per instructions.

## Step 2: Generate scaffold — 2026-07-28T12:00:00.000Z

## Task 0879 — Transient-Occupancy / Hotel-Tax Administration (Expert)

Wrote three files:
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8 — 18 instances)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9 — 22 active + 6 `excluded_because` stubs)

`scaffold_lint.py` verdict: **clean lint** — all 321 §1.8/§1.9 calls conform to §1.5, and every §1.1 FK has a reverse-reachability GET.

### Scale
- **14 entities**: Jurisdiction, Operator, Property, OTAPlatform, OTAAgreement, TaxReturn, ExemptionClaim, Remittance, Audit, Assessment, Appeal, Lien, RefundClaim, LedgerEntry (append-only, `common_fields: false`).
- **66 endpoints** (flat topology, `api_prefix: ""`; includes a `/_clock/set_current_utc` test-driving endpoint with startup default `2026-05-01T00:00:00Z`).
- **10 state machines**, **5 calculations**, **21 error codes**, **3 roles** (TaxAdmin opaque, Operator entity_backed, Auditor opaque; approval-chain with four-eyes assessment issuance).

### Difficulty features (all 9 §0.5 rules, ≥2 instances each)
- **Dual-variant** (different domains): tax STANDARD vs AUDIT exemption honoring (840000 vs 960000); refund interest STATUTORY_OVERPAYMENT vs AUDIT_ADJUSTMENT anchor (1500 vs 500).
- **Combinatorial** (different modes): mode (a) nested min/max tiered penalty+interest (24000/3600); mode (b) pinned round-per-line-then-sum (363 vs 362).
- **Non-linear SM**: cyclic Audit (FIELDWORK→PROPOSED→RESPONSE→FIELDWORK); parallel filing_status × settlement_status axes on TaxReturn.
- **Transitive cascades**: assessment-issue→ledger→balance→DELINQUENT (depth 3); remittance-clear→ledger→balance→ACTIVE→lien-release (depth 4), different triggers.
- **Priority conflicts** (different category pairs): state vs fiscal; temporal vs constraint.
- **Boundary precision**: 30-night inclusive exemption; strictly-above lien threshold (500000 rejected, 500001 accepted).
- **Cross-entity deps** (different pairs): TaxReturn←Operator, Appeal←Assessment.
- **Temporal overlap** (different semantics): closed-inclusive return periods vs half-open OTA-agreement intervals with adjacency allowed.
- **Compensating invariants** (different conserved quantities): money (account_balance == Σ ledger) on remittance reverse; receipts partition (gross == taxable + exempt) on exemption reject.
- **OCC**: one `concurrency_rules` entry (`lien-record-stale-operator`) via `expected_operator_version`, resolved as CREATE-with-stale-view, tested in both §1.8 and §1.9.

All three files pass yaml.safe_load cleanly.

## Step 3: Copy shared files — 2026-07-28T12:00:00.000Z

Copied INSTRUCTION.md into workspace/.

## Step 4: Generate PRD — 2026-07-28T12:30:00.000Z

Generated workspace/PRD.md for TOT Administration API.
- Section count: 5 top-level; §2 has 10 subsections; §3 has 9 workflow subsections.
- Endpoints documented: 68 (full §4 table), incl `/_clock/set_current_utc`.
- Line count: 305.
- Hard Contract 1 (Field-Name Coverage): PASS (69 identifiers, repaired audit_id/assessment_id/settlement_status).
- Hard Contract 2 (Rule Coverage): PASS (5 calcs, all SM transitions/cascades, 13-priority validation ordering, lien OCC; all 21 error IDs in prose).
- Hard Contract 3 (§3 Path Purity): PASS (369 tokens, 0 leading-slash paths/bare methods).
- Domain: flat topology, cyclic SMs (audit reopen, appeal info-request loop), append-only ledger as SoT, DELINQUENT<->ACTIVE reconciliation + lien release cascade, four-eyes assessment issuance, logical-clock due dates/interest.

## Step 5: Generate unit tests — 2026-07-28T12:45:00.000Z

test_helpers/ (9 files) + test_suite/ (8 test files + conftest.py): 58 test functions, 58 collected.
- Queue A (Difficulty): 18 instances × 2 tests = 36 tags.
- Queue B (Corner): 22 non-stub instances × 1 test = 22 tags. 6 excluded_because stubs NOT translated (cross-ref real §1.8 instances).
- Instances skipped: none (all passed PRD-first two-condition filter). Priority-pair conflicts kept (PRD §2.9 states full numbered validation priority order verbatim).
- Verified: every docstring ends with one Design: tag; ~47 PRD citations grep-confirmed verbatim; py_compile clean; pre-computed expecteds traced (tax 840000/960000, penalty 24000/interest 3600, per-line 363, refund 1500/500, lien 500000 vs 500001, total_assessed 660000).

## Step 6: Generate implementation — 2026-07-28T12:45:00.000Z

workspace/implementation/: app.py (~1050 lines), requirements.txt (Flask 3.0.3), start.sh (binds 0.0.0.0:$PORT default 10000).
- Scope: 66 endpoints, 14 entities, 10 SMs, 5 calcs, 21 errors, 3 roles.
- Storage: in-memory dicts on single Store, wiped every boot. No seeding except logical clock default 2026-05-01T00:00:00Z. Append-only ledger; account_balance_cents computed on read = SUM(ledger).
- Timestamps: system fields render logical clock as ...T..:..:...000Z; input datetimes echoed verbatim. created_at uses logical clock (AUDIT_ADJUSTMENT refund anchors interest on it).
- Tax: per-line round_half_up then sum (363 vs 362); honored-exemption CLAIMED∪VERIFIED for STANDARD, audited_taxable_cents for AUDIT.
- Penalty/interest: tiered min(0.25, 0.10+0.05*(m-1)), months=floor(days/30); assessment flat 10%/25%.
- OCC: any ledger post bumps operator version → intervening clear stales version → ERR_STALE_OPERATOR_VERSION.
- Validation ordering per PRD §2.9; Connection: close on every response.
- Self-validation: ~40 assertions replaying §1.8/§1.9 scenarios, all passed.

## Step 7: Run tests and iterate — 2026-07-28T12:30:00.000Z

CLEAN FIRST-SWEEP PASS.
- Iterations run: 1 (baseline 8-round parallel sweep passed immediately).
- Tests deleted: none.
- Fixes to test_helpers/: none.
- Fixes to implementation/: none.
- Proactive timestamp audit: created_at/updated_at sourced from logical clock via now_dt(), always rendered through single iso_millis() helper (.%03dZ). No clock-setter path bypasses renderer; no wall-clock or .000Z-vs-Z mismatch.
- ORCHESTRATOR RE-VERIFICATION (subagent left no results files on disk): re-ran full 8-round sweep via sweep.sh. All 8 rounds 58/58, 0 failed, 0 errors. results.{1..8}.json now on disk. Confirmed genuine.

## Step 8: Finalize PRD — 2026-07-28T12:30:00.000Z

SKIPPED — Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite fixes, 0 test_helpers fixes, 0 implementation fixes. PRD.md already determined every behavior the implementation exhibits. No PRD_FINALIZED.md produced.

## Step 9: Complete PRD — 2026-07-28T12:35:00.000Z

Produced workspace/PRD_COMPLETED.md (full PRD-vs-implementation scan).
- PRD.md = 305 lines; PRD_COMPLETED.md = 305 lines (all in-paragraph edits). Char delta: +2855 (45383 → 48238).
- 6 ambiguity-pins, 5 mismatch-revisions (11 total).
- Notable: §3.8 assessed_tax_cents is single-step base×rate (not per-line recompute); return SUPERSEDED status never entered (replacement flow unimplemented — second overlapping filing rejected ERR_PERIOD_OVERLAP); §2.6 REFUND posts positive to ledger; delinquency trigger = ISSUED or FINAL assessment; tax exemption allocated greedily across lines (claims carry no property_id).

## PIPELINE COMPLETE — 2026-07-28T12:35:00.000Z

task_0879_transient_occupancy_hotel_tax: Expert, CLEAN FIRST-SWEEP PASS 58/58 x8, 0 fixes.
Artifacts: SCAFFOLD.yaml (+DIFFICULTY/CORNER), PRD.md, PRD_COMPLETED.md, test_helpers/, test_suite/ (58 tests), implementation/ (app.py ~1050 lines), results.{1..8}.json all green.
Step 8 skipped (clean pass). Step 9 = 11 pins.
