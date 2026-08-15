# Worklog — task_1435_farmers_market_nutrition_incentive_token

## Step 1: Create Task Directory — 2026-08-13T06:45:00.000Z

Task directory `tasks/task_1435_farmers_market_nutrition_incentive_token/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline runner. Step 1 treated as DONE per invocation instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T08:03:00.000Z

Done. All three scaffold artifacts are written and lint-clean.

**Files**
- `/home/ubuntu/github/CodingPRD/tasks/task_1435_farmers_market_nutrition_incentive_token/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1435_farmers_market_nutrition_incentive_token/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1435_farmers_market_nutrition_incentive_token/SCAFFOLD_CORNER_DESIGN.yaml`

**Counts**
- Entities: 11 (Program, Market, Vendor, Shopper, MarketDay, TokenBatch, Issuance, Token, RedemptionSubmission, FraudCase, SettlementRun)
- State machines: 8 (Token has two cycles: REDEEMED⇄FLAGGED and REDEEMED→ISSUED reversal; RedemptionSubmission has DISPUTED→SUBMITTED resubmit loop; Vendor ACTIVE⇄SUSPENDED)
- Calculations: 7 (match_computation, shopper_match_usage, token_denomination_split, reimbursement_amount, program_liability, market_day_reconciliation, settlement_sweep)
- Validations: 32 (ordered lattice: auth → idempotency → existence → schema → OCC → state gates → safety → referential → temporal → constraint → fiscal)
- Endpoints: 49 (incl. `POST /_clock/set_current_utc`, default 2026-08-01T00:00:00Z)
- Errors: 33 (all referenced by validations/machines; all triggerable via covered tests)
- Roles: 6 (ProgramAdmin, MarketManager, BoothOperator, Auditor opaque; Vendor/Shopper entity_backed) — segregation_of_duties model
- §1.8 instances: 27 (3 per rule × 9 rules — above the ≥2 minimum)
- §1.9 instances: 65 total (60 active + 5 excluded-because stubs), spanning all 9 claim-extraction-guide sections

**Lint verdict (verbatim)**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5
and all §1.1 FKs have reverse-reachability in §1.5.
```
(49 endpoints, 11 entities, 27 + 60 instances, 1186 calls scanned, 0 violations.)

**Notable design decisions**
- **Dual-variant pair with precomputed divergence**: reimbursement provisional (per-line round_half_up at FEE_BPS 250) vs final (sum-then-round) diverge by exactly 1 cent on a 500+100+100 token set (684 vs 683) — chosen because whole-dollar × integer-% withholding never diverges, forcing 2.5%. Program liability (forward vs realized) is the second domain.
- **Reconcile is soft-fail by design**: CLOSED→VARIANCE_FLAGGED happens via the reconcile call returning 200 (not an error), keeping `ERR_RECONCILIATION_VARIANCE` reachable only as the plain-reconcile-on-flagged-day rejection; override is payload-scoped RBAC (MarketManager + override → 403).
- **Counterfeit triage split**: serial outside all batch ranges → 404 ERR_TOKEN_UNKNOWN_SERIAL; in-range-but-unminted → 409 ERR_TOKEN_NOT_MINTED; double-spend → error plus auto FLAGGED + AUTO_DOUBLE_SPEND FraudCase cascade.
- **True-race OCC only**: two concurrency rules (issuance vs Shopper.version double-issue vector; settlement-run vs Program.version stale sweep), both exercised by stale-version tests using `${var} ± n` expressions.
- **Cascades**: fraud-confirm vendor chain is depth 4 (case→vendor→submission→token→day ledger); settlement sweep and batch recall are the contrasting triggers.
- **Boundary clusters**: day-cap inclusive 2000, reconcile tolerance inclusive 500, settlement cutoff inclusive, submission window deadline ±1s pair, and a 72h resubmit-grace ±1s pair.
- Endpoint count (49) exceeds the Expert guideline band (20–32) deliberately: §0.4 marks band counts as guidelines, and every endpoint is load-bearing for either a declared difficulty/corner instance or the lint-enforced FK reverse-reachability of the flat 11-entity topology.

## Step 3: Copy Shared Files — 2026-08-13T08:04:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1435_farmers_market_nutrition_incentive_token/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T08:30:00.000Z

PRD generation complete. All three hard contracts pass.

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1435_farmers_market_nutrition_incentive_token/workspace/PRD.md` — 295 lines.

**Section list**:
- §1 Introduction (2 paragraphs — pain-point/reconciliation-discipline angle)
- §2 Global Specifications: 2.1 RBAC (6 roles with per-role `identity` prose: Vendor/Shopper entity-backed, ProgramAdmin/MarketManager/BoothOperator/Auditor opaque), 2.2 API Response Structure (byte-identical verbatim block, verified programmatically against `section-2.2-response-structure.md`), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ASC default + the `serial_number` ASC token-list exception), 2.4 The Logical Clock (startup default 2026-08-01T00:00:00Z, no wall-clock fallback), 2.5 Common Resource Properties (all 11 entities carry id/created_at/updated_at/version; cascade-mutation increment rule), 2.6 Monetary Units & 2.5% Withholding, 2.7 Idempotency, 2.8 OCC (both rules: `expected_shopper_version` on issuance create, `expected_program_version` on settlement-run create, `ERR_STALE_VERSION`/412, no race-framing), 2.9 Identifier Resolution (left-to-right path, body-FK 422), 2.10 Validation Pipeline and Error Precedence (all 32 validations in scaffold priority order as prose), 2.11 Scrip Vocabulary (kinds/denominations/six token statuses)
- §3 Business Logic (8 subsections): 3.1 Program Setup, Markets, Token Supply; 3.2 Market Days & Daily Ledger; 3.3 Shopper Enrollment; 3.4 Info-Booth Issuance (match formula, batch selector, void); 3.5 Vendor Redemption; 3.6 Reimbursement Claims; 3.7 Fraud Cases; 3.8 Settlement, Liability, Funder Reporting
- §4 Endpoint table: 49 rows, 4 columns. §5 Error catalogue: 33 rows, 2 columns.

**Hard-contract audit results**:
- Contract 1 (field names): 110 required identifiers (54 unique entity fields, 33 endpoint inputs, 17 query params, plus headers/common/output fields) — 110 present, 0 missing. PASS
- Contract 2 (rules): 32/32 validations with priority ladder in prose; 2/2 OCC rules (endpoint + occ field + `ERR_STALE_VERSION`/412); 31/31 state transitions across 8 machines with preconditions, error IDs, and hop-by-hop cascades; 7/7 calculations as reconstruction-safe prose (incl. the 684-vs-683 provisional/final worked divergence); 49/49 endpoint side effects; all 33 error IDs matchable to prose triggers; sibling branches symmetric (SNAP/WIC/SENIOR constants, three fraud-confirm subject cascades, forward/realized liability). PASS
- Contract 3 (§3 path purity): 408 backtick tokens scanned in §3, 0 path/method violations. PASS
- Extra scans: no pseudocode operators (`==`, `>=`, `IN {`, `->`, `+=`) outside code fences; no fuzzy approximators.

**Zero-Silence Rule self-audit — two scaffold-internal tensions I rendered without picking a winner**:
1. Reconcile-on-`RECONCILED`-day error: validation #15 assigns `ERR_MARKET_DAY_NOT_CLOSED` to both verify and decide, while the decide transition annotates `ERR_INVALID_STATE` for RECONCILED days. I rendered a unified reading in §3.6: not-yet-closed → `ERR_MARKET_DAY_NOT_CLOSED`; RECONCILED (terminal lock) → `ERR_INVALID_STATE`. Both error IDs and both conditions survive.
2. Redeem market-mismatch error id: the Token state machine names `ERR_VENDOR_MARKET_MISMATCH`, but the error catalog defines only `ERR_TOKEN_VENDOR_MISMATCH` (whose condition covers both market and vendor mismatch). I used the catalog ID exclusively, since §5 must enumerate catalog IDs verbatim.
3. `AUTO_COUNTERFEIT_SERIAL` has no case-creation side effect in the scaffold — I rendered it in §3.7 as an origin classification tied to the `ERR_TOKEN_NOT_MINTED` signal without inventing an auto-open cascade.

**Notable scattering/narrative decisions**: constants embedded with unit conversion ($20.00/$200.00 SNAP caps, 500-cent tolerance as "five dollars," 250 bps as 2.5%); OCC guards live in §2.8 but are re-referenced inside §3.4/§3.8 workflows; the per-token attachment ladder is split between §3.5 (vendor-side context) and §3.6 (claim creation/resubmission); endpoint parameters for the same operation are distributed across ≥2 subsections (e.g. `override_variance` in §2.1/§2.10/§3.2); §4 descriptions stay minimal so request shapes must be reconstructed from §3. No content from the DIFFICULTY/CORNER design files was read or used.

## Step 6: Generate Implementation — 2026-08-13T09:55:00.000Z

All tasks complete. Final summary:

## Implementation complete — task_1435_farmers_market_nutrition_incentive_token

**File list** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1435_farmers_market_nutrition_incentive_token/workspace/implementation/`):
- `start.sh` — guarded install (`pip install` only if `flask` import fails), `exec python3 app.py`, foreground
- `requirements.txt` — flask>=3.0,<4.0
- `app.py` — Flask entrypoint, blueprint registration, `ApiError`/replay/404/405/500 envelope handlers, `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory store (dicts keyed by UUID), idempotency store, insertion sequence; **starts empty, no seeding**
- `logical_clock.py` — logical clock, boot default exactly `2026-08-01T00:00:00Z`, ms-quantized ISO8601 formatting; all timestamps derive from it
- `errors.py` — all 33 catalog error IDs
- `response.py` — envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields in `meta` for lists)
- `middleware.py` — auth/RBAC (X-User-Role + entity-backed X-User-ID), idempotency guard/replay, body parsing, shape validators, pagination
- `services/domain.py` — computed fields (pool remaining, forward/realized liability, paid_out, payable, season/day match usage, day totals/variance, next_serial), match computation, denomination split + batch selector, provisional/final reimbursement rounding, cascade helpers (crossing-aware day auto-flip, bulk token mutation, reject quarantine, auto double-spend case)
- `routes/` — `clock.py`, `programs.py` (+funder-report, +markets, +shoppers), `markets.py`, `vendors.py`, `shoppers.py`, `market_days.py`, `token_batches.py`, `issuances.py`, `tokens.py`, `submissions.py`, `fraud_cases.py`, `settlement_runs.py`, `common.py`

**Endpoint coverage: 49/49.** **Error catalog: 33/33** (plus a defensive `ERR_INTERNAL` catch-all). **State machines: 8/8** with all preconditions, side effects, cascades, and the `CLOSED ↔ VARIANCE_FLAGGED` auto-flips.

**Verification**: two smoke suites (~90 assertions) run against a fresh `bash start.sh` boot — full lifecycle (program→market→batches→shopper→day→issuance→redeem→submit→verify→decide→settle), match caps (WIC floor/daily, SENIOR cap, pool clamp/forfeit), OCC 412s, idempotency replay/conflict, double-spend auto-flag+case, reject quarantine with crossing auto-flip, recall cascade, fraud confirm/clear cascades, dispute/72h grace, 7-day window, variance-500 boundary, RECONCILED lock, entity-backed 403s, pagination. Reboot test confirms empty store + clock reset.

**Key PRD ambiguities resolved** (interpretation chosen):
1. **Day auto-flip** is *crossing*-detected (flip only when a recompute moves |variance| across the 500 boundary), per "crosses … in either direction" / "push a CLOSED day over" — a stale out-of-tolerance CLOSED day stays CLOSED until a reconcile soft-routes it.
2. **Serial mapping** counts batch ranges of *any* status (PRD "a batch range") over the state machine's narrower "ACTIVE batch range".
3. **`AUTO_COUNTERFEIT_SERIAL`** cases are never auto-created — PRD says the platform "raises" only `AUTO_DOUBLE_SPEND`; no counterfeit trigger exists in the state machine table.
4. **Double-spend on a SETTLED token**: 409 + auto case, no token transition (flag precondition requires REDEEMED); effectively unreachable since redeem needs OPEN day and approval needs closed day.
5. **Submission window** treats CLOSED/VARIANCE_FLAGGED/RECONCILED as "after close" (7-day grace from `closes_at`); SCHEDULED rejects.
6. **RECONCILED-day verify/decide** → `ERR_INVALID_STATE` (terminal lock); SCHEDULED/OPEN → `ERR_MARKET_DAY_NOT_CLOSED`.
7. **Fiscal ladder** per priority order 27→28→29→30: batch-serial sufficiency is evaluated from the raw charge's floor-split mint plan *before* charge-floor/fractional checks.
8. **Idempotency** fingerprint = method+path+canonical body; only 2xx responses stored; replay returns the original envelope verbatim.
9. **Version bumps**: token attach/detach bumps token version (§2.5 any-mutation rule); cascade-affected MarketDays bump once per operation; token two-step REDEEMED→FLAGGED→CONFISCATED bumps twice; settlement bumps program per swept claim + once for the run; issuance bumps shopper/program/day even at match=0.
10. **`next_serial`** computed on read (`serial_start` + minted count) — batch version does not bump on minting.
11. **Program attribution** via the market chain (day→market→program for tokens/issuances; vendor→market→program for submissions).
12. **Funder report**: issued_* counts ACTIVE in-window issuances; redeemed_cents counts REDEEMED/SETTLED tokens of in-window issuances; reimbursed/liabilities/pool/days_flagged are unwindowed current values; utilization_bp=0 when budget=0.
13. **Entity-backed reads**: Shopper restricted to own shopper record/issuances (403 after path existence); Vendor reads any vendor/token but only own submissions (single-read 403; list silently scoped to self).
14. **Payload-scoped override check** (MarketManager + `override_variance: true` → 403) runs at priority 2, before idempotency and path existence, per the validation ladder.
15. GET pagination params are clamped (never 400) since scaffold rule 8 scopes `ERR_INVALID_REQUEST` to POST endpoints.

## Step 5: Generate Unit Tests — 2026-08-13T10:12:00.000Z

(Note: the Step 5 subagent's first turn ended mid-fix on a broken import fragment in test_04; the orchestrator resumed it via SendMessage, it completed the fix and the remaining files, and delivered the summary below.)

## Generation Complete — task_1435_farmers_market_nutrition_incentive_token

### Test counts per queue
- **Queue A (Difficulty)**: 54 tests — all 27 §1.8 instances covered with exactly 2 tests each (minimum met).
- **Queue B (Corner)**: 60 tests — all 60 non-stub §1.9 instances covered with exactly 1 test each.
- **Total: 114 tests**, collected cleanly by pytest (`114 tests collected`).

### Instances skipped (5 — all `excluded_because:` stubs; pointers verified to resolve)
1. `Corner/state_machines/c_sm_void_issuance_side_effects_restore_ledger` — owned by Difficulty/compensating_invariant/issuance_void_restores_match_pool_exactly.
2. `Corner/calculations/c_calc_variant_selection_provisional_at_create_final_at_approve` — owned by Difficulty/dual_variant_calc/reimbursement_rounding_order_variants_diverge.
3. `Corner/cross_cutting_complexity_layers/c_layer_cascading_side_effects` — owned by fraud_confirm_vendor_cascade_depth4.
4. `Corner/cross_cutting_complexity_layers/c_layer_dual_variant_calculation` — owned by reimbursement_rounding_order_variants_diverge.
5. `Corner/cross_cutting_complexity_layers/c_layer_rate_threshold_triggers` — owned by daily_match_cap_exact_boundary_then_exhaustion.

No PRD-first filter skips were needed beyond the stubs; one assertion was deliberately narrowed: in `reimbursement_inclusion_variants_diverge_on_flag` the recipe's "day auto-flips to VARIANCE_FLAGGED on fraud-case open" assertion was **omitted** — the PRD states the CLOSED→VARIANCE_FLAGGED auto-flip only for the claim-rejection cascade, not for case-open flagging (two-reader failure). The test still asserts the priced divergence (684 vs 195) and token FLAGGED.

### test_helpers/ (10 files)
`__init__.py` (barrel), `types.py` (11 TypedDicts + 10 enums), `api_client.py` (49 endpoint methods, auto Idempotency-Key injection + `post_raw` for the negative path), `api_errors.py` (33 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py`, `factories.py`, `constants.py` (caps/ratios/FEE_BPS/tolerance/serials), `test_users.py` (opaque role constants + `make_vendor_headers`/`make_shopper_headers` entity-backed builders), `fixtures.py` (5-tier composites: `setup_booth_scenario`, `issue_tokens`, `setup_submitted_claim`, `setup_approved_claim`, `run_settlement`, etc.).

### test_suite/ (12 files)
`conftest.py` (session `api` + role-header fixtures) and 11 numbered files: `test_01_program_and_enrollment.py` (6), `test_02_market_day_lifecycle.py` (11), `test_03_token_batches_and_serials.py` (10), `test_04_match_computation.py` (11), `test_05_issuance_gates.py` (13), `test_06_token_redemption.py` (12), `test_07_fraud.py` (11), `test_08_reimbursement_claims.py` (15), `test_09_submission_windows.py` (4), `test_10_settlement_and_reporting.py` (10), `test_11_platform_contracts.py` (11).

### Self-audit verdicts
- **Stage 1**: PASS — helpers import cleanly; ApiClient methods match the 49-endpoint surface; framework signatures verified against the installed `prd_bench_local_runner.testing` package.
- **Stage 2 coverage**: PASS — script-verified: every non-stub §1.8 instance has ≥2 `Design: Difficulty/...` tags, every non-stub §1.9 instance has ≥1 `Design: Corner/...` tag, zero unknown tags, zero stub translations, every test function ends its docstring with exactly one Design line.
- **PRD-citation pass**: PASS — 184 quoted citations across 114 tests, each ≥8 words and verbatim-present in `workspace/PRD.md` (whitespace-normalized containment check); literal grep spot-checks confirm. No `pytest.mark.skip/skipif/xfail` anywhere; no scaffold references in generated code.

## Step 7: Run Tests and Iterate — 2026-08-13T10:20:00.000Z

**Iterations run**: 1 (single 8-round parallel stability sweep; no fixes needed)

**Sweep result**: All 8 rounds passed cleanly with **114/114 tests, 0 failed, 0 errors** each:
- Round 1: passed=114/114 failed=0 errors=0
- Round 2: passed=114/114 failed=0 errors=0
- Round 3: passed=114/114 failed=0 errors=0
- Round 4: passed=114/114 failed=0 errors=0
- Round 5: passed=114/114 failed=0 errors=0
- Round 6: passed=114/114 failed=0 errors=0
- Round 7: passed=114/114 failed=0 errors=0
- Round 8: passed=114/114 failed=0 errors=0

**Tests deleted**: None — no PRD-silence or unique-derivability failures surfaced in any round.

**Fixes applied to `test_helpers/`**: None.

**Fixes applied to `test_suite/`**: None.

**Fixes applied to `implementation/`**: None — the implementation from the prior pipeline run was already stable against the full 114-test suite across all 8 concurrent rounds. No timing-sensitive flake (concurrency race, fixture ordering, port collision) appeared under the 8× parallel load.

## Step 8: Finalize PRD — 2026-08-13T10:20:00.000Z

SKIPPED per the skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — `PRD.md` already determined every behavior the implementation exhibits, so no `PRD_FINALIZED.md` was produced.

## Step 9: Complete PRD — 2026-08-13T11:05:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1435_farmers_market_nutrition_incentive_token/workspace/PRD_COMPLETED.md` produced as a minimal inline patch over `PRD.md`.

**Volume**
- PRD.md: 294 lines / 51,298 chars → PRD_COMPLETED.md: 294 lines / 55,989 chars. Char-delta: **+4,691**. No new sections, no new paragraphs — 20 edits across 19 existing paragraphs (diff hunks at lines 24, 79, 81, 85, 102, 114, 118, 130, 140, 160, 170, 172, 176, 180 ×2, 182, 186, 188, 194, 198).

**Counts**
- Ambiguity-pins (PRD silent → inserted impl behavior): 15
- Mismatch-revisions (PRD described different behavior → revised to impl): 5

**Changes** (impl references are under `.../workspace/implementation/`)

- §2.1 — insert — ambiguity — only `X-User-Role` is enforced on every request; `X-User-ID` may be omitted by the four operator roles, and a missing `X-User-ID` for Vendor/Shopper fails as `ERR_FORBIDDEN` — middleware.py:41-54.
- §2.3 — insert — ambiguity — unparsable/out-of-range `limit`/`offset` fall back to defaults then clamp (limit into [1,100], offset floored at 0), never rejected — middleware.py:226-240.
- §2.3 — insert — ambiguity — list-ordering ties (on `created_at`, or `serial_number` for tokens) break by creation order, never by id — middleware.py:243-250, routes/tokens.py:78-79, db.py:34.
- §2.4 — insert — ambiguity — clock set is unconditional (any valid ISO timestamp, forward or backward, no monotonicity check) and all server-stamped timestamps (`created_at`, `updated_at`, `disputed_at`, `approved_at`, envelope) read the logical clock truncated to ms — logical_clock.py:31-54, db.py:43-47.
- §2.7 — insert — ambiguity — only 2xx responses are recorded for replay (a failed request leaves the key reusable); request identity = method + path + canonical JSON body — middleware.py:93-134, db.py:58-65.
- §2.9 — insert — ambiguity — unmatched route or undeclared method on a route → `ERR_NOT_FOUND` (404) — app.py:59-66.
- §2.10 — insert — ambiguity — resource-dependent ownership checks (vendor vs `redeemed_vendor_id`/claim `vendor_id`, shopper self-read) evaluate immediately after path resolution, ahead of body-reference and shape validation — routes/tokens.py:166-171, routes/submissions.py:226-231, routes/shoppers.py:57-60.
- §3.1 — revise — ambiguity — negative `match_pool_budget_cents` pinned to `ERR_INVALID_REQUEST`; season bounds accepted as given (no `season_end > season_start` rule) — routes/programs.py:36-41.
- §3.2 — revise — ambiguity — season membership compares the date's UTC midnight (00:00:00Z) against `[season_start, season_end)` — routes/market_days.py:65-70, services/domain.py:541-543.
- §3.4 — revise — ambiguity — batch selection's final tie-break after `serial_start`/`created_at` is creation (registration) order, never id — services/domain.py:385-396.
- §3.5 — revise — mismatch + ambiguity — redemption ladder rewritten to impl order: serial triage → vendor `ACTIVE` → day `OPEN` → quarantine → double-spend → void → market match (PRD had token-status first and day-openness last); serial must be an integer; triage is system-wide across all programs and batch statuses (incl. `RECALLED`), earliest-minted token wins; a `SETTLED` token triggers the double-spend rejection and auto case but keeps its status (no flag) — routes/tokens.py:99-147, services/domain.py:506-523.
- §3.5 — revise — ambiguity — reverse-redemption gate order pinned: ownership (`ERR_FORBIDDEN`) → token `REDEEMED` (`ERR_INVALID_STATE`) → day `OPEN` → not attached (`ERR_TOKEN_ALREADY_SUBMITTED`) — routes/tokens.py:166-185.
- §3.6 — revise — ambiguity — 7-day post-close submission deadline is inclusive; duplicate ids in `token_ids` pass the ladder, price per occurrence, attach once; Vendor list calls are force-scoped to the caller; claims read `token_ids` back in `serial_number` ascending — routes/submissions.py:81-90, 127, 145, 152-155, 172-189, services/domain.py:83-86, 308-321.
- §3.6 — revise — ambiguity — verification on a `RECONCILED` day rejected with `ERR_INVALID_STATE` (same lock as adjudication) — routes/submissions.py:93-102.
- §3.6 — revise — ambiguity — resubmission: empty replacement list → `ERR_SUBMISSION_EMPTY`; vendor-standing gate applies; tokens still attached to the claim being cured are exempt from `ERR_TOKEN_ALREADY_SUBMITTED`; 72-hour grace is inclusive — routes/submissions.py:236-261.
- §3.6 — revise — mismatch + ambiguity — rejection also requires the closed-family day gate (`RECONCILED` → `ERR_INVALID_STATE`); quarantine cascade flags only attached tokens still `REDEEMED` but detaches every attached token (PRD said every attached token transitions `REDEEMED → FLAGGED`) — routes/submissions.py:294-299, services/domain.py:526-538.
- §3.7 — revise — mismatch — the counterfeit-serial signal (`ERR_TOKEN_NOT_MINTED`) opens no fraud case; `AUTO_COUNTERFEIT_SERIAL` is never produced — routes/tokens.py:108-113 (no case), services/domain.py:511-523 (only double-spend case exists).
- §3.7 — revise — mismatch + ambiguity — vendor confirm cascade: already-`SUSPENDED` vendor skips hop 1 and the cascade continues; hop 3 flags only attached tokens still `REDEEMED` and detaches all; already-`SUSPENDED` shopper unaffected; subject token in `VOIDED`/`SETTLED`/`CONFISCATED` unaffected by confirmation — routes/fraud_cases.py:108-133.
- §3.8 — revise — ambiguity — settlement sweep's final tie-break after `approved_at`/`created_at` is creation order, never id — routes/settlement_runs.py:60-68.
- §3.8 — revise — ambiguity — funder report: `issued_base_cents`/`issued_match_cents` count only issuances still `ACTIVE`; `reimbursed_cents` is summed over the whole season regardless of period bounds; `utilization_bp` is 0 when the budget is 0; malformed `period_start`/`period_end` → `ERR_INVALID_REQUEST` — routes/programs.py:74-83, 97-105, 118-126.

Everything else in the PRD (envelope shapes, error catalogue, RBAC table for all 46 endpoints, state machines, match computation, rounding variants, OCC guards, cascade version increments, variance auto-flip crossing rule, tolerance boundary, cutoff inclusivity) was verified against `implementation/` and already pinned uniquely — no change needed.
