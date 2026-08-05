# Worklog — task_1088_community_association_collections_lien

## Step 2: Generate Scaffold (Expert) — 2026-07-23T04:00:00.000Z

Scaffold: Community-Association Collections & Lien (Expert). Generated fresh from scenario + skill spec only (no sibling tasks consulted). All three files written; scaffold linter clean.

Structural profile:
- Archetype: compliance/audit + ledger-reconciliation; flat topology under /collections; cyclic state machines; segregation-of-duties role model; layers: OCC, cascading side-effects, dual-variant calc, rate/threshold triggers.
- Entities (10): Association, Account, Assessment, Payment, Notice, PaymentPlan, Lien, ForeclosureReferral, BankruptcyCase, Remittance.
- Endpoints (41): full CRUD + transition/action endpoints per entity, FK filtered-list reads, aging-report + payoff-quote computed reads, /collections/_clock/set_current_utc (default 2026-05-01T00:00:00Z).
- State machines (9): Account (8-state), Assessment, Payment (POSTED<->REVERSED), Notice (SENT<->DISPUTED cycle), PaymentPlan (ACTIVE<->BREACHED cycle), Lien, ForeclosureReferral, BankruptcyCase, Remittance.
- Calculations (8): account_balance, aging_buckets, payment_allocation (waterfall), payoff_amount (dual-variant PROVISIONAL/BINDING), remittance_amounts (dual-variant CASH/NET), lien_recorded_amount, plan_breach_evaluation, trust_balance.
- Errors (20). Roles (4): CollectionsAgent, ComplianceOfficer, TrustAccountant (opaque), AssociationManager (entity_backed:Association); maker-checker SoD between lien recording and foreclosure referral.
- Concurrency (2 OCC): plan-create on Account.version, remittance-create on Association.version.
- Difficulty: 18 instances (9 rules x2); Corner: 30 instances (24 active + 6 stubs).
- Subagent self-fix: swapped validation priorities referential=9/temporal=10; dropped unreachable Association.status=INACTIVE.

Orchestrator post-gen patch (constants pinned inline for PRD-gen, per batch playbook — design worked examples confirm values): VALIDATION_PERIOD_DAYS=30, NOTICE_COOLDOWN_DAYS=30, LIEN_MINIMUM_BALANCE_CENTS=180000 were referenced in validations/state-machines/errors but had no declared value; annotated inline at each reference. (INTEREST_DAY_COUNT=365, PAYOFF_GOOD_THROUGH_DAYS=15, DELINQUENCY_GRACE_DAYS=30, PLAN_MISSED_BREACH_THRESHOLD=2 already declared in calc constants blocks.) All three files re-verified with yaml.safe_load.

## Step 3: Copy INSTRUCTION.md — 2026-07-23T04:01:00.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md (bash-only).

## Step 4: Generate PRD — 2026-07-23T04:05:00.000Z

PRD.md generated (291 lines) for Community-Association Collections & Lien (Expert). 5 top-level sections, 17 subsections. §4 endpoint table = 41 endpoints (matches scaffold 41). §5 error catalogue = 20 error IDs.
Constants surfaced in prose: interest rate default 12.0%, late fee 2500 cents, management fee 20.0%, notice cooldown 30 days (half-open), FDCPA validation period 30 days, delinquency grace 30 days, payoff good-through 15 days, 365-day interest year, plan-breach threshold 2, 30-day installment spacing, lien minimum 180,000 cents — all 3 orchestrator-pinned constants confirmed present.
Hard Contracts 1/2/3 all PASS (field-name coverage, rule coverage, §3 path purity 440 tokens/0 paths). Subagent fixes: added referred_date field; corrected lien-minimum unit conversion to 180,000 cents.

## Step 5: Unit tests — 2026-07-23T04:20:00.000Z

66 tests across 9 files (test_01..test_09) + 9 test_helpers files. Queue A (Difficulty): 36 tests covering all 18 instances (≥2 each). Queue B (Corner): 30 tests covering all 30 non-stub instances (≥1 each). 0 instances SKIPPED — PRD fully specifies all asserted rules (priority-pair conflicts via §2.7, dual-variant payoff/remittance, all cascade terminals). Every docstring has a resolving Design: tag; 78 quoted PRD citations verbatim; no skip/xfail. 66 collect cleanly.

## Step 6: Implementation — 2026-07-23T04:20:00.000Z

Python+Flask in workspace/implementation/: start.sh, requirements.txt (Flask 3.0.3), app.py, store.py (in-memory dicts, logical clock default 2026-05-01T00:00:00Z, computed fields), services.py (waterfall, reversal, cascades, payoff, remittance, aging), web.py (envelope/auth/pagination/validators), lookups.py, routes_a.py, routes_b.py. 41 endpoints (= PRD §4). start.sh reads $PORT / binds 0.0.0.0 / foreground exec; storage in-memory only, no seeding. Self-verified with 75 smoke assertions passing. All 7 py files ast.parse OK; 41 .route() registrations; 66 tests collect with PYTHONPATH=.
NOTE: concurrent task_1090 running on same host (port 10099) — Step 7 to use 2 waves of 4 to avoid host saturation.

## Step 7: Fix loop — 2026-07-23T04:35:00.000Z

Result: clean 8-round sweep — 66/66 pass in every round (1–8), deterministic. 2 iterations (1 diagnostic baseline = 10 deterministic failures, 1 confirming green). NOT strictly clean.

Tests deleted: None. Every failing test traced to a verbatim PRD rule and was uniquely derivable.

Fixes to test_suite/ (plumbing only, no assertion weakened):
- test_08_remittances.py (lines 19/61/132): setup_remittance_pool(...) called without required first positional `api` → TypeError broke all 6 remittance tests; added the missing `api` argument.

Fixes to implementation/:
- store.py — added fmt_date/now_date (plain-second `...T00:00:00Z` renderer) alongside fmt_iso/now_iso (`.000Z`).
- routes_a.py, routes_b.py, services.py — render GENERATED domain-date fields (sent_date, dispute_date, computed final_due_date, plus recorded_date/referred_date/quote_date/good_through_date) via plain-second form. Impl echoed INPUT dates as plain `Z` but generated dates as `.000Z` — internal inconsistency; PRD pins 3 fractional digits only for created_at/updated_at/api_request_timestamp and writes domain instants as plain `...Z`. created_at/updated_at untouched. Fixed test_notice_resend_restamps_sent_date, test_notice_cooldown_day30_boundary_allowed, test_plan_final_due_date_computed.
- routes_a.py (plan-overlap) — replaced `max(new_start,os) < min(new_end,oe)` with two-sided strict overlap `new_start < oe and os < new_end`. Old form never rejected a zero-length point interval (num_installments=1: new_start==new_end always false), wrongly allowing an interior-point 1-installment plan. Fixed test_second_plan_strict_overlap_rejected; still passes test_plan_adjacency_touching_endpoint_allowed.

Step 8 will run (implementation + test fixes present; not strictly clean).

## Step 8: Finalize PRD — 2026-07-23T04:45:00.000Z

PRD_FINALIZED.md produced. PRD.md=291 → PRD_FINALIZED.md=293 (+2 lines, +0.69%). 2 pins:
- §2.4 Common Resource Properties — insert — server-generated domain instants render as plain-second `YYYY-MM-DDTHH:MM:SSZ` (no fractional digits) vs 3-fractional-digit created_at/updated_at/api_request_timestamp; client-supplied dates echoed verbatim (store.py fmt_date, services/routes callsites).
- §3.5 Payment Plans — revise — made "strictly overlaps" precise (new_start < oe and os < new_end): shared-endpoint adjacency allowed, single-installment zero-length interior interval rejected; "non-terminal" = not COMPLETED/CANCELLED (routes_a.py:506-515).
test_08 plumbing fix → no PRD change (pure fixture bug). NO-NEW-MISMATCH pre-edit search performed for both edits.

## Step 9: Complete PRD — 2026-07-23T04:50:00.000Z

PRD_COMPLETED.md produced from PRD_FINALIZED.md. 293 → 293 lines (+296 chars; all in-paragraph). 3 ambiguity-pins, 0 mismatch-revisions:
- §3.1 Associations — insert — association `status` field, only value ACTIVE, always serialized, never transitioned (store.py:286, routes_a.py:67).
- §3.1 Account lifecycle — insert — manual DELINQUENT transition on a non-CURRENT account → ERR_INVALID_STATE (routes_a.py:171-172).
- §3.5 Payment plans — insert — num_installments < 1 → ERR_INVALID_AMOUNT (routes_a.py:500-501).
All other behaviors (error precedence, aging boundaries, payoff round-then-cap, remittance CASH/NET, OCC bumps, notice cooldown/dispute/expire windows) already uniquely pinned and matching impl.

## PIPELINE COMPLETE — 2026-07-23T04:50:00.000Z

task_1088_community_association_collections_lien: Expert, 66/66 tests pass across all 8 stability rounds (deterministic). 10 ent / 41 ep / 20 err / 9 SM / 8 calc / 4 roles (SoD) / 2 OCC. NOT strictly clean (Step 7: 1 test_suite plumbing fix + 3 impl fixes: generated-domain-instant date format, two-sided strict plan-overlap). Step 8 = 2 pins; Step 9 = 3 ambiguity-pins. Final contract = PRD_COMPLETED.md. No orphan processes.
