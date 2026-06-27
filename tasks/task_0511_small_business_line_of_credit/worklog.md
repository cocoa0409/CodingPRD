# Worklog — task_0511_small_business_line_of_credit

## Step 1: Create Task Directory — 2026-06-27T00:00:00.000Z

Created `tasks/task_0511_small_business_line_of_credit/` with `workspace/` subdirectory (pre-allocated index, no scan performed).

## Step 2: Generate Scaffold (Expert difficulty) — 2026-06-27T00:01:00.000Z

All three files are written, parse cleanly, have correct top-level keys, and the design keys did not leak into SCAFFOLD.yaml. The scaffold-generator's `scaffold_lint.py` returns a clean verdict. I did not read any sibling task directory.

## Summary

Generated all three scaffold artifacts for **task_0511_small_business_line_of_credit** at **Expert** difficulty, purely from the scenario + skill spec (no sibling tasks consulted).

**Files written (all three):**
- `SCAFFOLD.yaml`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `SCAFFOLD_CORNER_DESIGN.yaml`

**Complexity profile:** Ledger reconciliation (primary) + Compliance/audit (secondary); layers = optimistic concurrency, cascading side effects, dual-variant calculation, rate/threshold triggers; flat topology; cyclic state machines; segregation-of-duties role model; immediate consistency.

**Entities (10):** Merchant, BankFeed, Application, CreditLine, Draw, Remittance, LineIncreaseRequest, RenewalOffer, Statement, LedgerEntry (LedgerEntry is `common_fields:false`, immutable append-only ledger).

**State machines (7):** Application (branching + revision cycle DRAFT→SUBMITTED⇄NEEDS_REVISION + approve/decline/expire), CreditLine (ACTIVE⇄FROZEN, ACTIVE⇄DELINQUENT cure loop, DELINQUENT→DEFAULTED→CHARGED_OFF, CLOSED), Draw (OUTSTANDING→REPAID/WRITTEN_OFF), Remittance (SCHEDULED→FAILED→SCHEDULED NSF-retry cycle, SETTLED/CANCELLED), LineIncreaseRequest, RenewalOffer (with expiry), Statement.

**Counts:** 8 calculations (3+ dual-variant: risk-score initial/revision, approved_limit origination/increase, remittance daily/weekly; plus order-pinned APR), 17 validations (ordered), 50 endpoints (incl. reverse-reachability GETs, `/_clock/set_current_utc` with default 2026-05-01T00:00:00Z, `/_ops/expire-*`), 18 errors, 3 roles (Underwriter / Servicer / CreditOfficer, all opaque), 2 OCC concurrency rules (increase-approve-stale-line, charge-off-stale-line).

**Design coverage:** §1.8 = 18 difficulty instances; §1.9 = 35 corner instances across all 9 claim-extraction sections. `scaffold_lint.py` → `VERDICT: clean lint`.

## Step 3: Copy Shared Files — 2026-06-27T00:02:00.000Z

Copied `INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-27T00:03:00.000Z

**PRD generation complete for task_0511_small_business_line_of_credit.**

**Output written:** `workspace/PRD.md` (280 lines, ~47 KB).

**Section structure:**
- §1 Introduction (ledger-reconciliation + compliance framing).
- §2 Global Specifications — 9 subsections: 2.1 RBAC (3 roles, all `opaque` identity, SoD anchors); 2.2 Response Structure; 2.3 Pagination; 2.4 Common Resource Properties + Logical Clock (clock default 2026-05-01T00:00:00Z); 2.5 Hierarchical Consistency/Cascades/Nested Retrieval; 2.6 OCC on CreditLine; 2.7 Monetary Precision; 2.8 Immutable Ledger; 2.9 Validation Ordering (17-priority chain).
- §3 Business Logic — 8 subsections by lifecycle.
- §4 Endpoint Definitions — 52 endpoints.
- §5 Error Code Catalogue — 18 error IDs.

Field coverage: 60/60 present. Rule coverage: 17 validations, 2 OCC rules, all state transitions/calculations/cascades expressed, PASS. Path purity (§3): PASS.

**Confirmation:** Did NOT read `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`.

## Step 5: Generate Unit Tests — 2026-06-27T00:04:00.000Z

Test infrastructure complete. Both `test_helpers/` and `test_suite/` written and verified.

**Test files:** 8 (`test_suite/test_01`–`test_08`) plus `conftest.py`; 9 Stage-1 helper modules in `test_helpers/`.

**Total tests:** 72, all collecting cleanly under pytest.

**Breakdown by queue:**
- Queue A (Difficulty): 18 instances × ≥2 tests = 37 tests (one instance has 3). All 18 confirmed at ≥2 tests.
- Queue B (Corner): 35 non-stub instances × ≥1 test = 35 tests. All 35 covered; 0 `excluded_because:` stubs.

**Instances skipped:** None. Every instance passed the PRD-first two-condition filter. All 14 pre-computed literal values re-derived from PRD formulas and matched.

**Verification:** Stage 1 imports clean (Python 3.12). All 72 tests carry exactly one `Design:` tag, mapping 1:1 onto real YAML instances. All 83 quoted PRD citations verified verbatim. Zero skip/xfail. NSF retry chain encapsulated in `drive_line_to_strikes`; per-identity SoD header builders in `test_users.py`.

## Step 6: Generate Implementation — 2026-06-27T00:05:00.000Z

Implementation complete and validated (Python + Flask).

**File layout of `implementation/`:** start.sh, requirements.txt (Flask==3.0.3), app.py, clock.py (default 2026-05-01T00:00:00Z), constants.py, db.py (in-memory dicts, no seeding), errors.py, response.py (§2.2 envelope), common.py, lookups.py, middleware.py (X-User-ID/X-User-Role auth + RBAC), serialize.py, routes/ (merchants, bank_feeds, applications, credit_lines, draws, remittances, line_increases, renewals, statements, ledger, ops), services/ (calc.py — Decimal ROUND_HALF_UP; ledger.py — FIFO + outstanding recompute).

**start.sh contract — confirmed:** reads `$PORT` (default 10000), binds `0.0.0.0`, foreground via `exec python3 app.py`; pip install guarded.

**Storage — confirmed:** in-memory Python dicts only, all empty literals. No SQLite/JSON/tmp. No seeding at startup.

Note: full HTTP-over-socket curl could not complete in the subagent's sandbox (loopback TCP blocked), but every behavior was validated via the in-process Flask WSGI test client.

## Step 7: Run Tests and Iterate — 2026-06-27T00:06:00.000Z

Two consecutive clean 8-round parallel sweeps (16 rounds total, all 72/72, zero failures, zero errors, zero connection errors). The flakiness is resolved. Exiting with the summary.

---

## Summary

**Iterations run:** 3 (initial baseline → fix logic bugs → fix concurrency flakiness), with a 4th confirmation sweep. Final state: two consecutive clean 8-round parallel sweeps (16 rounds, all 72/72 pass).

**Tests deleted:** None. Every failing test traced to a verbatim PRD rule that uniquely determines the outcome; the failures were test-assertion bugs (wrong sign / wrong allocation split) and one concurrency-induced connection flake, none warranting deletion.

**Fixes applied to test_suite/ (assertion corrections — STEP 2 TEST-vs-PRD, made MORE faithful to PRD):**

1. `test_03_default_and_chargeoff.py` — `TestChargeOffCascade.test_charge_off_writes_off_draw_and_appends_ledger_entry`: changed `sum_ledger_amounts(entries,"WRITE_OFF") == 200_000` to `== -200_000`. PRD §2.8 states amount_cents is a signed movement where "a credit is negative (reducing it)"; a WRITE_OFF reduces outstanding, so its sign is negative. The implementation (`-unrepaid_principal`) was PRD-faithful; the assertion had the wrong sign.

2. `test_03_default_and_chargeoff.py` — `test_principal_accounting_conserved_through_chargeoff`: corrected `total_writeoff == 200_000` to `== -200_000` and the conservation identity from `total_draw == total_repaid + total_writeoff + outstanding` to the signed form `total_draw + total_repaid + total_writeoff == outstanding` (§2.8 signed reconstruction: DRAW_PRINCIPAL positive, PRINCIPAL_REPAYMENT/WRITE_OFF negative).

3. `test_08_difficulty_depth.py` — `test_charge_off_sets_status_and_leaves_already_repaid_untouched_observable` and `test_writeoff_ledger_amount_equals_unrepaid_principal`: both changed `sum_ledger_amounts(wo,"WRITE_OFF") == 200_000` to `== -200_000` (same §2.8 sign correction). Cross-validated against the passing `test_07` assertions which correctly treat DRAW_PRINCIPAL/DRAW_FEE as positive debits.

4. `test_08_difficulty_depth.py` — `test_weekly_cadence_same_outstanding_diverges_from_daily`: corrected the fee/principal split from `fee_applied==64000, principal_applied==22400` to `fee_applied==40000, principal_applied==46400`. PRD §3.5 allocates "within each draw, fee is repaid before principal ... advancing through draws oldest-first": with target 86400, draw1's fee (40000) then draw1's principal (46400) exhaust the amount before reaching draw2. The original values reflected an all-fees-first-globally model that contradicts §3.5. Cross-validated against the passing FIFO test (`test_02::test_fifo_repays_oldest_draw_first`) which the implementation already satisfies with the within-each-draw model. The `amount_cents == 86400` assertion (the WEEKLY 10% divergence the test exists to prove) was kept.

**Fixes applied to implementation/:**

1. `app.py` — `create_app()`: added an `@app.after_request` hook setting `Connection: close`. The test client uses a persistent `requests.Session` (HTTP keep-alive); under the 8x-concurrent per-test-server sweep the Werkzeug dev server occasionally tore down an idle keep-alive socket the client then reused, surfacing as a transient `BadStatusLine`/`ConnectionError` (observed once in round 7 of iteration 2 on `test_nsf_settle_spawns_scheduled_retry_two_days_later`). Closing the connection per-response eliminates the reuse race. This is a transport-level header only — no API contract field, no seeded data, no new dependency; storage remains in-memory dicts wiped on every `start.sh` reboot.

No implementation business-logic changes were needed — the ledger sign convention (§2.8) and the FIFO within-each-draw allocation (§3.5) were already correctly implemented; the four logic failures were all wrong test assertions.

## Step 8: Finalize PRD — 2026-06-27T00:07:00.000Z

PRD_FINALIZED.md is byte-identical to PRD.md (same MD5 `8176d0eb4a38296df7ad54489cabd7e4`). This is the correct outcome.

**PRD.md vs PRD_FINALIZED.md:** 280 lines vs 280 lines, 0% delta — byte-identical. Zero edits applied.

**Conclusion: No PRD edit warranted.** Every `<step_7_diff>` item is either a pure test-assertion bug (impl already matched a PRD rule that uniquely determines the outcome) or a non-contract transport detail. No PRD silence, no PRD/impl mismatch to pin.

Per-item: (1) §2.8 ledger sign convention — PRD verbatim "a credit is negative (reducing it)"; impl writes WRITE_OFF as `-unrepaid_principal` (`credit_lines.py:177`), matches. (2) §3.5 within-each-draw allocation — PRD verbatim "Within each draw, fee is repaid before principal ... advancing through draws oldest-first"; impl loops draw-by-draw (`remittances.py:148-164`), matches. (3) `Connection: close` is a transport-level `@app.after_request` header (`app.py:35-44`), not an API contract field. (4) No test deletions.

Pre-edit search confirmed all `amount_cents` write paths (DRAW_PRINCIPAL/DRAW_FEE positive in `draws.py:55-62`; PRINCIPAL_REPAYMENT/FEE_REPAYMENT negative in `remittances.py:172-184`; WRITE_OFF negative in `credit_lines.py:171-178`; FIFO ordering `drawn_at`→`created_at`→`_seq`, never id) consistent with existing PRD prose. No edit needed.

## Step 9: Complete PRD — 2026-06-27T06:09:00.000Z

Done. All edits applied to PRD_COMPLETED.md in place, in-paragraph only.

## Summary

**Source vs. completed**
- PRD_FINALIZED.md: 280 lines, 47371 chars
- PRD_COMPLETED.md: 280 lines, 51217 chars
- Char delta: **+3846** (line count unchanged — every change is an in-paragraph insert/revision; no new paragraphs or sections)

**Counts:** ambiguity-pins = **11**, mismatch-revisions = **3** (total 14 changes)

**Changes**
- §2.2 (API Response Structure) — insert — ambiguity — `api_request_timestamp` is real wall-clock at serve time, not the logical clock; logical clock governs only business evaluations and entity `created_at`/`updated_at` — `response.py:25-28`, `common.py:32-43`
- §2.3 (Pagination/Listing) — insert — ambiguity — list endpoints accept optional exact-match filters (`status` on all status-bearing lists; FK filters `merchant_id`/`bank_feed_id`/`application_id` on collection lists; ledger lists filter per §3.8 with no `status`); unmatched filter yields empty page — `applications.py:73-86`, `credit_lines.py:65-78`, `bank_feeds.py:46-54`, `draws.py:76-84`, `remittances.py:81-89`, `line_increases.py:50-74`, `renewals.py:60-68`, `statements.py:66-74`, `ledger.py:15-42`
- §2.8 (Immutable Ledger) — insert — ambiguity — entry-type signs pinned (DRAW_PRINCIPAL/DRAW_FEE positive; PRINCIPAL_REPAYMENT/FEE_REPAYMENT/WRITE_OFF negative) and `balance_after_cents` is principal-only, so DRAW_FEE/FEE_REPAYMENT carry the same balance as their paired principal entry and never move the running balance — `draws.py:53-62`, `remittances.py:171-184`, `services/ledger.py:42-48`
- §2.9 (Validation Ordering) — revise — ambiguity — non-positive `new_fee_factor_bps` is also `ERR_VALIDATION` (422), and the `term_days` positivity check precedes it — `renewals.py:30-34`
- §3.1 (Onboarding) — insert — ambiguity — malformed and duplicate `ein` both rejected with `ERR_INVALID_REQUEST` — `merchants.py:34-43`
- §3.2 (Application Underwriting) — insert — ambiguity — application-expiry sweep returns `200 OK`, array envelope of exactly the newly-EXPIRED applications ordered by `created_at` asc, `total_count` = swept count, no pagination — `ops.py:33-46`
- §3.3 (Operating the Credit Line) — revise — mismatch — on a fresh line `available_credit_cents` is initialized to the full `credit_limit_cents` (limit − 0 outstanding), not to zero as the prior "all three balance fields default to zero" wording stated — `credit_lines.py:48`
- §3.5 (Remittances) — revise — ambiguity — remittance status set is `SCHEDULED`/`SETTLED`/`FAILED`/`CANCELLED`; `FAILED` is a resting state never revisited (retries are fresh SCHEDULED siblings), correcting the "terminal at SETTLED or CANCELLED" omission of FAILED — `remittances.py:204-208`, `test_helpers/types.py:64-69`
- §3.5 (Remittances) — revise — mismatch — settlement appends PRINCIPAL_REPAYMENT then FEE_REPAYMENT, but each only when its applied amount is strictly positive; both carry the same post-principal `balance_after_cents` — `remittances.py:170-184`
- §3.6 (Default) — insert — ambiguity — both declare-default preconditions (line `DELINQUENT`, `nsf_strike_count` ≥ 5) are enforced in the state slot and each failure returns `ERR_INVALID_STATE` — `credit_lines.py:124-127`
- §3.6 (Charge-Off Cascade) — insert — ambiguity — WRITE_OFF draws processed in creation order (never by id); WRITE_OFF `amount_cents` = `-(principal_cents − principal_repaid_cents)` (a credit) stepping `balance_after_cents` down — `credit_lines.py:161-178`
- §3.7 (Line Increases) — insert — ambiguity — increase-limit advance multiple uses the tier selected by the freshly recomputed score, not the line's stored `pricing_tier` — `line_increases.py:115-124`, `services/calc.py:47-60`
- §3.7 (Renewal Economics) — insert — ambiguity — renewal-expiry sweep returns `200 OK`, array envelope of exactly the newly-EXPIRED offers ordered by `created_at` asc, `total_count` = swept count, no pagination — `ops.py:49-62`
- §3.8 (Statements) — insert — ambiguity — finalizing before the clock reaches `period_end` is rejected with `ERR_INVALID_STATE` — `statements.py:85-86`

Note: I did not read SCAFFOLD*.yaml or worklog.md, and edited only PRD_COMPLETED.md. Tests (`test_helpers/types.py`) were consulted only as auxiliary cross-reference (confirming the `FAILED` remittance status and entity field shapes), never as authority.
