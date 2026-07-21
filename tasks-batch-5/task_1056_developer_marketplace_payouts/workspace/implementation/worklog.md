
## Step 4: Generate PRD — 2026-07-18T00:00:00.000Z

PRD.md = 398 lines, 77 endpoints documented (matches scaffold exactly).
Hard contracts all PASS: field coverage (90 entity fields / 44 request bodies / 19 query params / 14 path params, 0 missing); rule coverage (25 validations w/ 13-step §2.8 precedence ladder, 2 OCC rules, 9 machines / 54 transitions, 7 calculations, 77 endpoint side-effects, 9 sibling-branch symmetry groups, 0 missing); path purity (659 backtick tokens scanned, 0 leaked paths).
No pre-patching needed — all constants pre-declared. Boundary inclusivity stated explicitly: pricing cooldown exactly-24h accepted; refund window exactly-30-days accepted; representment strictly-before (exactly-7-days rejected); payable exactly 5000 clears minimum; reportable exactly 60000 is ISSUABLE; touching payout windows accepted. Pinned rounding orders (per-line-then-sum tax; withholding on after-recovery) stated as contract.
Orchestrator verification: PRD md5 stable across 3 polls (no stall-race).

## Step 5: Generate unit tests — 2026-07-18T00:00:00.000Z

test_helpers/ = 9 files (types.py w/ 19 enums, api_client.py, api_errors.py w/ 38 error ids, assertions.py incl. assert_purchase_split_identity / assert_payout_waterfall_consistency / assert_developer_accrual_identity, factories.py, constants.py, test_users.py, fixtures.py ~55 composite helpers, __init__.py).
test_suite/ = conftest.py + 10 test files, 92 test functions.
Verification: 92 collect cleanly; pyflakes no undefined names; every docstring ends with exactly one Design: tag (0 unknown, 0 dual); every quoted PRD citation machine-checked verbatim (0 non-verbatim); all 18 difficulty instances >= 2 tests; all 57 non-stub corner instances >= 1 test except 1 skip; all 6 excluded_because stubs verified. No skip/xfail; no scaffold references in emitted code.
Skipped instance (1): Corner/state_machines/corner_submit_for_review_without_active_plan_returns_invalid_state — PRD §3.3 states the precondition verbatim but names no error id; §2.8's ERR_INVALID_STATE is scoped to undeclared transitions and DRAFT->IN_REVIEW IS declared, so ERR_INVALID_REQUEST is equally faithful. Unique-derivability gap left as a gap.
Flagged risk: §3.9's "marks every swept ledger entry with settled true" leaves it open whether the RESERVE/WITHHOLDING/PAYOUT rows written BY the disbursement are themselves settled; tests follow the design-index (post-payout unpaid_accrual_cents == 0) reading.

## Step 6: Generate implementation — 2026-07-18T00:00:00.000Z

workspace/implementation/: start.sh, requirements.txt, app.py, core.py (in-memory Store, empty on boot, logical clock default 2026-07-01T00:00:00Z, envelope, pagination, X-User-ID/X-User-Role auth, Decimal ROUND_HALF_UP, 38-entry error->HTTP table), services.py (recompute_accrual, select_tier, recompute_risk STANDARD/ACCELERATED, suspend_developer + delist_app cascades, batch-total recompute), routes/ = 12 modules.
Route count: 77 (matches §1.5 exactly, verified from url_map by both subagent and orchestrator). ast.parse OK on all 15 files. start.sh reads $PORT, binds 0.0.0.0, execs foreground. Booted live: 200 with empty data (no startup seeding).
Two judgement calls flagged: (1) ownership-vs-existence ordering — §2.8 ranks ownership above existence but ownership is undecidable for a missing resource, so path resources resolve first (404) then ownership; same for SoD on policy cases. (2) Developer.carryover_cents also set at `calculate` from a HELD_BELOW_MINIMUM line's carryover_added_cents, so §3.9's deferral actually feeds the next batch's gross_earnings_cents (PRD's `pay`-only reading would leave the field permanently dead).

## Step 7: Test and iterate — 2026-07-18T00:00:00.000Z

Iterations run: 2 (initial sweep 89/92 in ALL 8 rounds — deterministic, no flakiness; second sweep 92/92 x 8). Sweep run as 2 waves of 4 via sweep.sh (no inline pkill).
Tests deleted: none. Both failing rules were verbatim PRD-covered and uniquely derivable.
Fixes applied to test_suite/:
- test_07_policy_cases_and_risk.py — test_upheld_case_delists_the_listing_and_suspends_the_developer read the retired plan with make_policy_officer_headers. PRD §4 row for GET /api/pricing-plans/{pricing_plan_id} lists only Developer, PlatformAdmin, FinanceOps, StorefrontService — PolicyOfficer deliberately excluded, so the impl's 403 was PRD-correct. Switched that read to make_platform_admin_headers; the RETIRED assertion (§3.4 delist cascade) unchanged.
Fixes applied to test_helpers/: none.
Fixes applied to implementation/:
- services.py recompute_accrual() — no longer zeroes negative_balance_cents when the unsettled-ledger sum comes out positive. PRD §2.9 conditions that clause strictly on the sum coming out below zero; §3.5 capture only calls for unpaid_accrual_cents to be recomputed. Old behaviour let a fresh capture silently erase a chargeback debt, making §3.9 step 4 (recovery_cents) vacuous.
- routes/chargebacks.py reverse() — passes recompute_negative_balance=True, since §3.7 is the one place PRD explicitly says unpaid_accrual_cents, negative_balance_cents and payout_hold are all recomputed from the ledger, and its stated arithmetic invariant requires the pre-dispute balance to be restored.
