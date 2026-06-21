# Worklog — task_0072_irs_tax_installment_agreement

## Step 1: Create task directory — 2026-05-31

Created `tasks/task_0072_irs_tax_installment_agreement/` and `tasks/task_0072_irs_tax_installment_agreement/workspace/` via `mkdir -p`.

## Step 2: Generate scaffold (Expert difficulty) — 2026-05-31

All three scaffold artifacts are generated and pass `scaffold_lint.py` clean.

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.

Files written: SCAFFOLD.yaml (§1.0–§1.7), SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8), SCAFFOLD_CORNER_DESIGN.yaml (§1.9).

Complexity profile: Compliance/audit primary, Ledger-reconciliation secondary; flat entity topology (TaxAccount hub with FK-linked peers); branching state-machine shape; segregation_of_duties role model; immediate consistency. Layers: optimistic concurrency, cascading side effects, dual-variant calculation, scheduled actions, rate/threshold triggers.

Entities (9): TaxAccount, TaxPeriod, CsedSuspension, InstallmentAgreement, Payment, OfferInCompromise, FederalTaxLien, CncDetermination, AccountEvent.

State machines (5): InstallmentAgreement (PROPOSED→APPROVED/REJECTED, APPROVED↔REINSTATED→DEFAULTED, →CLOSED — cyclic revision loop), OfferInCompromise (SUBMITTED→EVALUATING→ACCEPTED/REJECTED — branching fork with divergent side effects), FederalTaxLien (FILED→RELEASE_PENDING→RELEASED / WITHDRAWN), CsedSuspension (OPEN→CLOSED), TaxPeriod (ASSESSED→IN_COLLECTION→SATISFIED/WRITTEN_OFF/ABATED).

Calculations (8): accrued_penalty (dual-variant standard 0.5% vs DDIA-reduced 0.25%, round-per-month-then-sum), accrued_interest (sum-then-round), reasonable_collection_potential (tiered future-income multiplier), setup_fee (tiered DDIA/MANUAL/waived), csed_date (assessment+3653 days + closed suspension days), payment_allocation (oldest-first waterfall), account_total_balance, period_balance_due.

Key validations (17, priority-ordered): auth→role→existence→FK-mismatch→duplicate-TIN→state→segregation-of-duties→conflicting-resolution→agreement-window-overlap→payoff-shape→short-term-length→CSED-suspension-overlap→offer-below-RCP→lien-release-blocked→nothing-to-sweep→OCC-stale-version→invalid-request.

Endpoints: 41 (CRUD + action endpoints across all entities, recompute, sweep-expired-csed, plus a /_clock/set_current_utc test-driving endpoint).

Error catalog: 17 codes.

Concurrency: 2 OCC rules on TaxAccount.version (agreement approve, OIC accept), both 412.

Difficulty design: 9 rules × 2 = 18 instances. Corner design: 8 sections, 32 instances (28 with full test_recipes, 4 excluded_because stubs).

## Step 3: Copy INSTRUCTION.md — 2026-06-01

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md (bash, no subagent).

## Step 4: Generate PRD — 2026-06-01

PRD generated at workspace/PRD.md. Structure: 5 top-level sections (§1 Introduction, §2 Global Specifications, §3 Business Logic & Workflows, §4 Endpoint Definitions, §5 Error Code Catalogue), 21 subsections, 275 lines.

Hard contract reports all PASS:
- Field coverage: 50/50 required field names present, 0 missing.
- Rule coverage: 17 validations, 2 OCC rules, all state-machine transitions, 8 calculations (penalty round-per-month-then-sum vs interest sum-then-round contrast preserved), sibling-branch symmetry 0 asymmetric.
- Path purity (§3): 364 backtick tokens scanned, 0 path/method tokens.

Withheld files confirmed not read: SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml.

## Step 5: Generate unit tests — 2026-06-01

Stage 1 — test_helpers/ (9 files): types.py (entity TypedDicts with correct common_fields branching — Payment and AccountEvent carry only id/created_at), api_client.py (one method per endpoint incl. /_clock/set_current_utc), api_errors.py (17 error IDs + HTTP map), assertions.py, factories.py (auto-incrementing unique TINs), constants.py, test_users.py (both roles opaque; make_*_headers builders for segregation-of-duties identity), fixtures.py (composable tiers: clock → account → period → recompute → approved agreement / offer-in-evaluating / lien-release-pending), __init__.py. Imports verified clean.

Stage 2 — test_suite/ (conftest + 5 test files): test_01_accrual_and_fees, test_02_agreement_lifecycle, test_03_offer_in_compromise, test_04_statute_liens_payments, test_05_accounts_rbac_validation.

Totals: 64 tests, all collect cleanly.
- Queue A (Difficulty): 36 tests — all 18 instances covered with exactly 2 tests each.
- Queue B (Corner): 28 tests — all 28 non-stub instances covered ≥1.
- Skipped: 0 difficulty instances (all 18 passed the PRD-first two-condition filter).
- Stubs not translated (as required): 4 (error_oic_default_cascade_already_covered, error_penalty_round_order_already_covered, error_csed_day_conservation_already_covered, immediate_visibility_of_cascade_in_accept_response).

## Step 6: Generate implementation — 2026-06-01

Built Python + Flask implementation in workspace/implementation/. Files (10): start.sh (foreground launcher, executable), requirements.txt (Flask 3.0.3), app.py (entry + all 40 routes + error handlers), db.py (in-memory store + overridable logical clock), errors.py (17 error IDs + HTTP statuses), response.py (meta/response_type/data envelope, req_ IDs, ms-precision ISO timestamps), auth.py (X-User-ID/X-User-Role + RBAC), common.py (datetime parsing, common fields, typed validators), calc.py (penalty round-per-month-then-sum, interest sum-then-round, setup fee, RCP tiers, CSED days), domain.py (serializers, recompute, CSED suspension, collection-status derivation, cascades).

Endpoint count: 40 (all from PRD §4 table, incl. /_clock/set_current_utc test hook).

start.sh: reads $PORT (default 10000), binds 0.0.0.0, foreground via exec python3 app.py. Storage purely in-memory module-level singletons — no disk/SQLite, fresh on every boot, no startup seeding.

Live smoke tests passed for auth, duplicate TIN, penalty/interest accrual, CSED base date, agreement approve cascade, OCC stale version, state masking, reinstate→default cascade, lien release guard, OIC RCP tiers + segregation of duties + depth-3 accept cascade, CSED sweep, suspension overlap/adjacency, FK mismatch, validation priority precedence, pagination envelope.

## Step 7: Run tests and iterate — 2026-06-01

Iterations run: 2 (initial sweep surfaced 4 consistent failures, stable 60/64 across all 8 rounds — not flaky; second sweep after fixes clean 64/64).

Tests deleted: none.

Assertions removed (STEP 1c partial-coverage split — ABATED-vs-SATISFIED ordering ambiguity):
- test_oic_accept_depth3_cascade (test_03) — removed `assert p["period_status"] == "ABATED"`, kept balance_due_cents == 0 plus account RESOLVED / total-0 / agreement-CLOSED.
- test_balance_conservation_payment_then_oic_abatement (test_03) — removed `assert p["period_status"] == "ABATED"`, kept conserved total_balance_cents == 0 and balance_due_cents == 0.
  Rationale: PRD §3.9 sequences a Payment allocated oldest-first then non-SATISFIED periods set to ABATED. Both tests use offer_amount_cents=18,500,000 (forced large by offer_amount >= rcp_cents accept check) against ~1M balance, so oldest-first allocation zeroes the period. Whether the zeroed period reads SATISFIED (§3.8 payment cascade) or ABATED (§3.9 abatement) is not uniquely determined — STEP 1b ordering/branch-asymmetric collapse. Implementation produces SATISFIED and is PRD-faithful.

Fixes applied to test_suite/ (STEP 2 — fixture precondition violations, assertions left intact):
- test_02_agreement_lifecycle.py / test_agreement_default_closes_csed_and_drops_protection: added set_clock("2024-07-15...") between approval and missed-debit/default. Test asserted csed_date > csed_before but never advanced the clock, so the auto-opened CSED suspension interval spanned zero days (start_at == end_at), days_counted = 0, csed_date could not increase. Advancing the clock makes the interval span ~91 days; on default the closed interval folds those days into csed_date (§3.5).
- test_05_accounts_rbac_validation.py / test_cnc_create_then_revoke_flips_collection_status: replaced zero-balance create_account(...) with setup_account_with_recomputed_period(...) so account carries positive total_balance_cents. PRD §2.5 derives collection_status = RESOLVED when balance is zero before the CNC check, so the original no-period account derived RESOLVED regardless of ACTIVE CncDetermination. Assertions unchanged.

Fixes applied to test_helpers/: none.
Fixes applied to implementation/: none — implementation was PRD-faithful in every case; all four failures traced to test-side issues.

## Step 8: Finalize PRD — 2026-06-01

PRD_FINALIZED.md produced with a single minimal in-place edit. Line counts: PRD.md 274, PRD_FINALIZED.md 274 (+0 lines, ~+0.3% chars). No new sections.

Change:
- §3.9 (OIC accept cascade) — revise — pinned SATISFIED-vs-ABATED ordering: OIC_LUMP_SUM payment is allocated oldest-first first, applying §3.8 cascade so any period the lump sum zeroes flips IN_COLLECTION → SATISFIED; the "set to ABATED" step is then evaluated against post-allocation statuses, so a period already satisfied stays SATISFIED. (impl app.py:687-705, domain.py:269-272.)

Step 7 items 2 and 3 — no PRD edit: both fixture-precondition bugs, not PRD silence (csed_date folding already determined by §3.2/§3.5; RESOLVED-before-CNC collection_status matches §2.5 verbatim).

## Step 9: Complete PRD — 2026-06-01

PRD_COMPLETED.md produced from PRD_FINALIZED.md. Source 274 lines / 43,905 chars → result 274 lines / 45,337 chars (+1,432 chars, no line-count change — all in-paragraph). ambiguity-pins = 4, mismatch-revisions = 1.

Changes:
- §2.1 (Global mount) — insert — ambiguity — pinned /_clock/set_current_utc lives outside the /collections prefix (app.py:929).
- §2.3 (Pagination/listing) — insert — ambiguity — pinned list-filter query-param names (tax_account_id, tax_period_id; payments and account-events accept both; tax-accounts also collection_status), unrecognized/omitted filters ignored, created_at-then-creation-sequence tiebreak.
- §3.4 (Reject agreement) — revise — mismatch — PRD said rejection only recomputes collection_status; impl's reconcile_account also recomputes total_balance_cents and bumps updated_at/version (app.py:462-475, domain.py:253-258).
- §3.12 (Account-event append) — insert — ambiguity — directly-appended event takes no suspension_days input (always 0, no statute days even for CSED_SUSPEND_END); serialized shape id, tax_account_id, event_type, tax_period_id, suspension_days, created_at (no updated_at/version).
- §3.12 (Test clock) — insert — ambiguity — absolute set with no forward-only guard (may move backward); three-fractional-digit current_utc shape (app.py:929-935, db.py:11-17).

Pipeline complete. Final 8-round sweep: 64/64 all rounds.
