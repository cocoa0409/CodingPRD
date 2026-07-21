# Worklog — task_1056_developer_marketplace_payouts

## Step 1: Create task directory — 2026-07-18T00:00:00.000Z

Created `tasks/task_1056_developer_marketplace_payouts/` and `workspace/` (folder pre-assigned by the user; no index scan performed).

## Step 2: Generate scaffold — 2026-07-18T00:00:00.000Z

Entities 14 | Endpoints 77 | Errors 38 | Roles 6 | State machines 9 | Calculations 7 | Validations 25 | OCC rules 2 | Invariants 2.
§1.8 instances: 18 (9 rule_ids × 2). §1.9 instances: 63 across 9 sections (57 with test_recipe, 6 excluded stubs).
Profile: ledger_reconciliation + compliance_audit; flat topology; cyclic state machines; segregation_of_duties; layers = OCC, dual-variant calc, cascading side effects, rate/threshold triggers.
Entities: Developer, App, ReviewSubmission, PricingPlan, TaxJurisdiction, RevenueShareTier, Purchase, Refund, Chargeback, PolicyCase, PayoutBatch, PayoutLine, LedgerEntry, TaxForm1099.
Rule 1 dual-variant: revenue_share_split PROVISIONAL vs FINAL (tier true-up) and developer_risk_score STANDARD vs ACCELERATED.
Rule 2 combinatorial: per-line-then-sum VAT rounding; circular withholding base pinned to after_recovery.
Rule 8 overlap: half-open PayoutBatch windows vs closed PricingPlan windows with 24h PRICING_COOLDOWN_HOURS buffer.
Rule 9 invariants: per-purchase ledger sum -> 0 via full-refund clamp; developer unsettled-accrual balance restored by chargeback reversal.
Cascades: depth-4 policy takedown; depth-3 chargeback clawback.
Lint: clean (77 endpoints / 14 entities / 773 calls scanned).

Orchestrator verification: all 3 YAML files yaml.safe_load OK. All named constants declared (PRICING_COOLDOWN_HOURS=24, REFUND_WINDOW_DAYS=30, CHARGEBACK_REPRESENT_WINDOW_DAYS=7, POLICY_STRIKE_SUSPEND_THRESHOLD=3, DEFAULT_SHARE_BPS=7000, CHARGEBACK_RESERVE_BPS=500, BACKUP_WITHHOLDING_BPS=2400, MIN_PAYOUT_CENTS=5000, FORM_1099_THRESHOLD_CENTS=60000, RISK_WINDOW_DAYS=30, weights 40/40/20, clock 2026-07-01T00:00:00Z) — no pre-patching needed.

## Step 3: Copy shared files — 2026-07-18T00:00:00.000Z

Copied INSTRUCTION.md -> workspace/INSTRUCTION.md.

## Step 8: Finalize PRD — 2026-07-18T00:00:00.000Z

PRD.md 398 lines / 66,080 bytes -> PRD_FINALIZED.md 398 lines / 66,676 bytes (0% line delta, +0.90% bytes). Two inline edits, both traced to Step-7 implementation fixes:
- §2.9 (Cascades, Ledger Integrity and Derived Roll-Ups) — insert — pinned that when the unsettled sum comes out at or above zero the recompute takes the sum for accrual and leaves any carried negative balance untouched; a debt is discharged only by the §3.9 waterfall recovery step or the explicit full recompute on §3.7 chargeback reversal — services.py:95-102.
- §3.7 (Chargebacks / Compensating Reversal) — insert — pinned that reversal's "recomputed from the ledger" is the FULL recompute, i.e. it sets negative_balance_cents to 0 whenever the unsettled sum is no longer below zero, in contrast to the §2.9 ordinary recompute — routes/chargebacks.py:160.
No PRD edit for the test_07 fixture fix: PRD.md:314 already lists GET /api/pricing-plans/{id} readers as Developer/PlatformAdmin/FinanceOps/StorefrontService, so the 403 for PolicyOfficer was already uniquely determined — pure fixture bug.
Pre-edit search log (NO-NEW-MISMATCH): edit 1 enumerated all negative_balance_cents/recompute_accrual writes (services.py:84-102; developers.py:48/96/154; purchases.py:169; refunds.py:148; chargebacks.py:129-131/160-162; payouts.py:181/315-317) and reworded from "never lowered by a recompute" to scope the claim to the recompute alone plus naming both discharge routes, because disbursement lowers it right after a recompute. Edit 2 confirmed chargebacks.py:160 is the only caller passing recompute_negative_balance=True and that the flag only affects the total >= 0 branch; dropped a draft saying reversal "restores the pre-dispute balance" (impl sets 0 / -total, does not restore a prior value); left the payout_hold sentence verbatim as under-determined.

## Step 9: Complete PRD — 2026-07-18T00:00:00.000Z

PRD_FINALIZED.md 398 lines / 66,676 chars -> PRD_COMPLETED.md 398 lines / 70,349 chars (+3,673 chars; 14 paragraphs revised, no new sections, no line-count change).
Counts: 11 ambiguity-pins, 3 mismatch-revisions.
- §2.1 — insert — ambiguity — ownership enforced ONLY on Developer/App/PricingPlan/PolicyCase; purchase/refund/chargeback/payout-line/ledger-entry/tax-form reads unchecked, no list endpoint owner-scoped — purchases.py:137, payouts.py:107, ledger.py:20
- §2.8 step 3 — revise — MISMATCH — path resources resolve first (404 beats ERR_NOT_RESOURCE_OWNER and ERR_SEGREGATION_OF_DUTIES despite ownership ranking above existence); POST /api/apps compares body developer_id to X-User-ID before any shape check — apps.py:81, policy_cases.py:96, apps.py:44
- §2.8 step 5 — insert — ambiguity — body-named resources (app_id/pricing_plan_id on a purchase, developer_id on a listing or form) resolve AFTER step-6 request-shape checks — purchases.py:65
- §2.9 — revise — MISMATCH — lifetime_revenue_base_cents accumulates at capture and is never walked back by refund/chargeback/reversal (PRD had it as a filter over current payment_status) — purchases.py:163
- §3.1 — insert — ambiguity — vat_rate_bps outside 0-3000 is ERR_INVALID_REQUEST — config_routes.py:49
- §3.1 — insert — ambiguity — developer_share_bps outside 1-10000 is ERR_INVALID_REQUEST — config_routes.py:88
- §3.3 — insert — ambiguity — PATCH /api/apps/{id} accepted from any listing state (no state guard) — apps.py:86
- §3.3 — insert — ambiguity — the missing-ACTIVE-plan refusal on submit-for-review is ERR_INVALID_STATE, checked after the state guard (closes the Step-5 skipped corner instance's derivability gap) — apps.py:118
- §3.7 — insert — ambiguity — a chargeback may be recorded against a purchase in ANY payment state — chargebacks.py:38
- §3.8 — insert — ambiguity — neither appeal outcome restamps decided_by_user_id — policy_cases.py:156
- §3.9 (final share) — insert — ambiguity — tier_trueup_cents is line-only: no TIER_TRUEUP ledger entry, not an addend of gross_earnings_cents — payouts.py:163
- §3.9 step 8 — insert — ambiguity — a HELD_BELOW_MINIMUM line writes carryover_added_cents onto Developer.carryover_cents at CALCULATE time; a PAYABLE line leaves it alone until pay — payouts.py:216
- §3.9 (disbursement) — revise — MISMATCH — sweep set defined (unsettled entries whose purchase_id is one of the line's eligible purchases); the five PAYOUT/RESERVE/RECOVERY/WITHHOLDING/CARRYOVER rows are BORN settled=true with signs pinned; accrual recomputed THEN negative_balance_cents reduced by recovery_cents floored at 0; carryover_cents cleared to 0 for PAYABLE lines; held lines untouched — payouts.py:289-320
- §3.10 — insert — ambiguity — settled exception for disbursement-written rows; per-developer ledger list accepts only entry_type/settled (not purchase_id/payout_line_id) — developers.py:113

## Pipeline complete — 2026-07-18T00:00:00.000Z

Final state: 92/92 tests passing across all 8 stability rounds. Artifacts: SCAFFOLD.yaml + 2 design indices, PRD.md -> PRD_FINALIZED.md -> PRD_COMPLETED.md, test_helpers/ (9 files) + test_suite/ (10 files, 92 tests), implementation/ (15 Python files, 77 routes).
