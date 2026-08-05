# Worklog — task_0880_municipal_sales_use_tax_filing

## Step 1: Create task directory — 2026-07-28T11:23:00.000Z

Folder tasks/task_0880_municipal_sales_use_tax_filing given as-is (Step 1 scan skipped per instruction). Created workspace/ subdirectory.

## Step 2: Generate scaffold (Expert) — 2026-07-28T11:49:00.000Z

All three scaffold artifacts are generated, self-consistent, and pass the lint clean (239 calls scanned, 0 violations; all 12 FKs reverse-reachable). I did not consult any sibling task.

Generated at tasks/task_0880_municipal_sales_use_tax_filing/:
- SCAFFOLD.yaml (§1.0–§1.7)
- SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8 — 18 instances)
- SCAFFOLD_CORNER_DESIGN.yaml (§1.9 — 28 instances, incl. 1 excluded_because stub)

### Scale (Expert)
- 9 entities: Taxpayer, Jurisdiction, TaxReturn (embedded line objects), ExemptionCertificate, Remittance, Audit, Assessment, Appeal, RefundClaim
- 39 endpoints (incl. /_clock/set_current_utc with the mandated 2026-05-01T00:00:00Z default)
- 6 state machines: Taxpayer, TaxReturn, Audit, Assessment, Appeal, RefundClaim
- 7 calculations, 31 errors, 5 roles (Anonymous/Taxpayer/TaxAuditor/AppealsOfficer/TaxAdmin), 1 concurrency rule

### Archetype & profile
Ledger reconciliation + Compliance/audit; flat topology, cyclic state machines, segregation-of-duties role model, immediate consistency. Layers: dual-variant calculation, cascading side effects, optimistic concurrency, rate/threshold triggers.

### How the 9 difficulty rules are realized
- dual_variant_calc: assessment penalty (AUDIT_DEFICIENCY 25% → 128750 vs LATE_FILING 10% → 113300) and refund interest (STATUTORY_DELAY 915 vs OVERPAYMENT_DATE 2265) — different entity domains.
- combinatorial_formula: mode (b) per-line-round-then-sum on returns (56666 not 56667); mode (c) pinned order interest-on-(base+penalty) → 3750 not 3000.
- non_linear_state_machine: TaxReturn FILED↔AMENDING cycle; Appeal SUBMITTED↔INFO_REQUESTED cycle.
- transitive_cascade: depth-3 audit-close → Assessment ISSUED → return ASSESSED → RefundClaim VOIDED; depth-2 amend → return leaves FILED → remittance un-applied.
- priority_pair_validation_conflict: state vs fiscal (RETURN_NOT_FILED > OVERAPPLICATION); referential vs temporal (CERTIFICATE_OWNER_MISMATCH > CERTIFICATE_EXPIRED).
- boundary_precision_check: file-on-due-date (≤) discount; nexus gross_receipts == threshold (≥).
- cross_entity_state_dependency: return-amend blocked by OPEN Audit; refund-approve blocked by SUSPENDED Taxpayer.
- resource_temporal_overlap: closed-interval return periods vs half-open exemption-certificate validity.
- compensating_invariant: account-balance ledger identity (assessment + abatement → 0); remittance principal partition (applied + unapplied == amount).

OCC is a genuine CREATE-with-supersede race (refund creation on a stale expected_return_version, 412).

## Step 3: Copy INSTRUCTION.md — 2026-07-28T11:50:00.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-07-28T11:55:00.000Z

Generated workspace/PRD.md (253 lines). 5 top-level sections; §2 has 9 cross-cutting subsections; §3 has 7 lifecycle workflow subsections. 39 endpoints in §4 table; 31 error codes in §5 table.

Hard Contract reports: field coverage 0 missing (all 70+ scaffold fields + endpoint identifiers verbatim); rule coverage all 7 calculations rendered with pinned rounding/order; all 6 state machines with preconditions+error_ids+side effects; OCC (ERR_STALE_VERSION 412) framed; §3 path purity 0 URL/method tokens.

Scaffold observations: No undeclared constants (VENDOR_DISCOUNT_BPS 150, cap 100000; NEGLIGENCE 2500; LATE_FILING 1000/cap 500000; MONTHLY_INTEREST 100; REFUND_GRACE_DAYS 90; DAILY_INTEREST 3; NEXUS_THRESHOLD 10000000; APPEAL_WINDOW 60). Minor gap: TaxReturn amend lists expected_return_version precondition but validation OCC row (ERR_STALE_VERSION) scoped only to POST /tax/refund-claims; mapped amend version mismatch to same ERR_STALE_VERSION 412 (stated explicitly in PRD).

## Step 5: Generate unit tests — 2026-07-28T12:10:00.000Z

test_helpers/ (9 files) + test_suite/ (conftest + 7 domain test files). 63 test functions, all tagged and collecting.
Coverage: Difficulty queue 18/18 instances each ≥2 tests; Corner queue 27/27 non-stub instances each ≥1 test. 1 stub skipped (Corner/rbac/segregation_of_duties_stub, excluded_because cross-ref). No untagged/dual-tagged/dangling tags. Every docstring: one Design: tag + verbatim PRD quote (8-word-window grep, 0 non-verbatim). No PRD-silence/unique-derivability gaps required skipping any non-stub instance. Pre-computed expected values recomputed & confirmed (113300 vs 128750 penalty; 915 vs 2265 refund-interest; 56666 per-line round-then-sum; 66980 net-due/balance).

## Step 6: Generate implementation — 2026-07-28T12:10:00.000Z

workspace/implementation/: start.sh (guarded-install foreground, exec python3 app.py, $PORT default 10000, binds 0.0.0.0), requirements.txt (flask==3.0.3), app.py (single-module, in-memory dicts, no seeding/persistence). 39 endpoints.
Verified end-to-end: per-line round-then-sum tax, vendor discount (150 bps, 100000 cap, <= due-date), LATE_FILING vs AUDIT_DEFICIENCY penalty variants with 30-day-month interest on base+penalty, refund STATUTORY_DELAY vs OVERPAYMENT_DATE, derived-on-read balance, depth-3 audit-close cascade, appeal ALLOW→ABATE→revert, nexus flip, period/cert overlap, remittance apply/un-apply conservation, OCC ERR_STALE_VERSION, ERR_OVERAPPLICATION, SoD, ownership 403s.
PRD ambiguities resolved: (1) Timestamp format — PRD §2.4 pins THREE fractional digits, so renders .000Z (authoritative, tests derive from PRD — NOT the anti-.000Z bug since inputs echoed verbatim & PRD pins the format). (2) activate/suspend wrong-state → ERR_ACCOUNT_NOT_ACTIVE 409 (scaffold gap). (3) Taxpayer read/list scope: ownership enforced on reads/writes, list scoped to own; admin/auditor/appeals see all. (4) ownership(403) before FK existence(404). (5) pagination limit/offset clamped [1,100]/[0,∞), non-int → ERR_VALIDATION.

## Step 7: Run tests and iterate — 2026-07-28T12:20:00.000Z

CLEAN FIRST-SWEEP PASS. Iterations run: 1 (single 8-round sweep, run as 2 waves of 4 via sweep.sh). Tests deleted: none. Fixes to test_helpers/: none. Fixes to implementation/: none.
Final sweep confirmed independently by orchestrator: all 8 rounds passed==total, 63/63 each round (0 failed, 0 errors across every round). No flakiness.

## Step 8: Finalize PRD — 2026-07-28T12:20:00.000Z

SKIPPED per skill skip-condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, 0 implementation/ fixes. PRD.md already determined every behavior the implementation exhibits. No PRD_FINALIZED.md produced.

## Step 9: Complete PRD — 2026-07-28T12:20:00.000Z

Produced workspace/PRD_COMPLETED.md (full impl-vs-PRD scan; started from PRD.md since Step 8 skipped).
Source PRD.md = 253 lines / 35850 chars → PRD_COMPLETED.md = 253 lines / 37999 chars (char delta +2149). Ambiguity-pins: 5. Mismatch-revisions: 1.
Changes:
- §2.3 Pagination — insert — ambiguity — out-of-range clamping (limit→[1,100], negative offset→0), non-integer limit/offset → ERR_VALIDATION, created_at tie-break by insertion order — app.py:279-285,289.
- §2.4 Common Resource Properties — insert — ambiguity — client-supplied date-only fields echoed verbatim; only server-stamped datetimes use 3-fractional-digit render — app.py:69-76,363-366,452-453.
- §2.8 Validation Ordering — insert — ambiguity — on body-taxpayer_id/assessment_id creates, ownership 403 checked after body validation but before FK existence 404 — app.py:650-652,813-814,868-869,1141-1142,1264-1266.
- §2.9 Nested Retrieval and List Filtering — insert — ambiguity — Taxpayer ownership scoping (lists auto-scoped to own; non-owner single read→403; privileged roles see all; jurisdictions unscoped) — app.py:476-479 + per-handler filters.
- §3.1 Account Lifecycle — insert — ambiguity — wrong-state activate/suspend → ERR_ACCOUNT_NOT_ACTIVE (409) — app.py:582,595-596.
- §3.5 Direct Assessment — revise — mismatch — PRD said only LATE_FILING may be issued directly; impl accepts LATE_FILING or AUDIT_DEFICIENCY (enum-validated, penalty per variant), audit_id null, no cascade — app.py:1082,1095,1107.

## PIPELINE COMPLETE — 2026-07-28T12:20:00.000Z

task_0880_municipal_sales_use_tax_filing (Expert): CLEAN FIRST-SWEEP PASS 63/63 x8, 0 fixes. Step 8 skipped. Step 9 = 5 ambiguity-pins + 1 mismatch-revision. Deliverables: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, PRD.md, PRD_COMPLETED.md, test_helpers/, test_suite/ (63 tests), workspace/implementation/ (39 endpoints).
