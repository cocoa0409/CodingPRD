# Worklog — task_0491_regulated_sportsbook

Scenario: "Regulated Sportsbook (FanDuel style): account & KYC, geolocation/geofence eligibility, market/odds & line management, bet placement & risk/limit, parlay/same-game & cash-out, settlement & grading (official data), responsible-gaming limits/self-exclusion, bonus/promo & wagering requirement"

Difficulty tier: Expert (passed only to prd-bench-scaffold-generator §0.4)

## Step 1: Create Task Directory — 2026-06-25T02:34:46.000Z

Created `tasks/task_0491_regulated_sportsbook/` and `tasks/task_0491_regulated_sportsbook/workspace/` (pre-assigned path; no auto-scan/auto-increment). Confirmed `./INSTRUCTION.md` exists at project root for Step 3.

## Step 2: Generate Scaffold (Expert tier) — 2026-06-25T02:50:42.000Z

All 58 instance names unique, every error code referenced by at least one validation/transition/concurrency rule. The scaffold package is complete and self-consistent.

Generated a complete Expert-tier scaffold package for **task_0491_regulated_sportsbook** (Regulated Sportsbook, FanDuel style). All three files pass `scaffold_lint.py` with **`VERDICT: clean lint`** (420 calls scanned, all FK reverse-reachability satisfied).

**Archetype/profile:** compliance_audit primary + ledger_reconciliation secondary; flat topology; parallel state-machine shape (Account kyc_status × rg_status); segregation_of_duties role model; immediate consistency. Layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers.

**Scaffold contents:**
- **Entities: 11** — Account, RGControl, GeoCheck, Event, Market, Selection, Bet, BetLeg, Promotion, BonusGrant, LedgerEntry (12 FKs, polymorphic LedgerEntry.ref_id, computed cross-entity balances/liability).
- **State machines: 6** — Account (two parallel dimensions: kyc PENDING→VERIFIED/REJECTED, rg ACTIVE↔COOLING_OFF→SELF_EXCLUDED), Event (with depth-4 settlement cascade), Market (cyclic OPEN↔SUSPENDED), Bet (compound grading from legs), BonusGrant.
- **Calculations: 9** — american_to_decimal_odds, combined_decimal_odds (round-once), potential_payout (floor), bet_settlement_payout (drop-push-legs), cash_out_value (current-odds×retention — dual variant vs settlement), market_liability, deposit_limit_check (gross), net_loss_limit_check (net vs gross-wager variant), wr_qualifying_contribution (min-odds floor).
- **Validations: 20** (priority-ordered, 8 categories), **Endpoints: 39** (incl. `/_clock/set_current_utc` test-driving endpoint, default clock 2026-01-01T00:00:00Z), **Errors: 25**, **Roles: 5** (Anonymous, Bettor [entity_backed:Account], TradingOps, SettlementAgent, ComplianceOfficer — all opaque except Bettor).
- **Concurrency rules: 2** OCC-on-Account.version (bet-place-stale-account, cashout-stale-account, both 412).

**§1.8 (SCAFFOLD_DIFFICULTY_DESIGN):** 18 instances = all 9 Difficulty Rules × 2, each grounding into §1.1–§1.6, with executable setup_api_calls chains and Python-precomputed literal asserts (e.g., cash-out 11500 vs settlement 15000; combined odds 5.0001; push-drop payout 3333; bonus-completion bankroll conservation 92000).

**§1.9 (SCAFFOLD_CORNER_DESIGN):** 40 instances across 9 taxonomy sections = **36 active** + **4 excluded_because stubs** (each citing an existing §1.8 instance name). 58 instance names total, all unique across both design files.

## Step 3: Copy Shared Files — 2026-06-25T02:50:57.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0491_regulated_sportsbook/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-25T02:56:54.000Z

All verification passes. Every error ID appears in §2/§3 prose, every state enumeration value is present, and all calculation constants (0.92 retention, 900s geo-TTL, 86,400/604,800 window seconds, 100m accuracy) are embedded in business narrative. The PRD is complete.

Generated `workspace/PRD.md` for the Regulated Sportsbook (FanDuel-style) domain. **Structure:** 5 top-level sections, 22 subsections, ~289 lines.
- §1 Introduction; §2 Global Specifications — 10 subsections (RBAC w/ all 5 roles + identity translation; fixed §2.2 verbatim envelope; pagination; resource identity/versioning incl. three append-only `common_fields: false` entities; logical clock default `2026-01-01T00:00:00Z`; OCC on `Account.version`; monetary buckets/ledger; decimal-odds & floor precision; nested-path/state preconditions; full priority-ordered validation chain)
- §3 Business Logic — 12 scattered workflow subsections; §4 endpoint table (all 40 endpoints); §5 error table (all 25 errors)

**Coverage confirmation — every scaffold element covered:** All 11 entities + 71 fields verbatim; both Account dimensions (kyc+rg), Event, Market, Bet (compound), BonusGrant state machines with all from/to + preconditions+error_id + side-effect cascades; all 9 calculations with constants/precision; all 20 priority validations; both OCC rules; all 40 endpoints; all 25 errors; all 5 roles. Hard Contract reports: Field coverage PASS (71/71), Rule coverage PASS (20 validations, 2 concurrency, all transitions/calculations), Path purity PASS (443 backtick tokens scanned, 0 path/method leaks). Neither design YAML was opened.

## Step 5: Generate Unit Tests — 2026-06-25T03:25:06.000Z

**Generated test infrastructure** for `task_0491_regulated_sportsbook` (Regulated Sportsbook, Expert tier).

### Test files: 5 (+ conftest.py)
- `test_01_odds_and_payout_calculations.py` — 10 tests
- `test_02_settlement_and_cascades.py` — 15 tests
- `test_03_bet_placement_validation.py` — 15 tests
- `test_04_accounts_geo_and_access.py` — 24 tests
- `test_05_difficulty_complements.py` — 8 tests (second tests for the 8 under-covered difficulty instances)

### Total: 72 test functions
- **Queue A (Difficulty): 36 tests** — all 18 instances (9 rules × 2) covered with ≥2 tests each.
- **Queue B (Corner): 36 tests** — all 36 non-stub instances covered with ≥1 test each.

### Design instances SKIPPED: 0
Every non-stub instance passed the PRD-first two-condition filter — the PRD verbatim-covers and uniquely-derives every asserted rule. The 4 `excluded_because:` corner stubs were correctly NOT translated; all 4 cross-references resolve to real §1.8 instances.

### test_helpers/ files created (9)
`__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`

### Validation
- All 72 tests collect cleanly; every test carries exactly one `Design:` tag resolving to a real instance; no untagged/dual-tagged/stub-tagged tests. No skip/skipif/xfail; no scaffold leakage; append-only entities (GeoCheck, BetLeg, LedgerEntry) asserted without updated_at/version; entity-backed Bettor identity threaded via `make_bettor_headers(account_id)`.
- **Ran against reference implementation: 71/72 pass.** The single non-pass (`test_list_accounts_paginated_envelope`, expected `total_count==2` got `42`) is a shared-state artifact of `--isolation none`; under real `--isolation per-test-server` each test starts empty and it passes. Test is correct as written.

## Step 6: Generate Implementation — 2026-06-25T03:25:06.000Z

**Files under `workspace/implementation/`:** `start.sh` (foreground launcher, executable), `requirements.txt` (`Flask==3.0.3`), `app.py` (Flask entry, all 40 routes, error handlers, request lock, validation-priority orchestration), `db.py` (in-memory `Store`, 10 dicts, logical clock default `2026-01-01T00:00:00Z`, UUID+ISO helpers), `errors.py` (`ApiError` + 25-entry error→HTTP-status catalogue), `response.py` (success/error envelope), `helpers.py` (auth/role gate, pagination, field validators), `calc.py` (Decimal odds conversion, round-once combined odds, floor payouts, cash-out 0.92 retention, settlement effective-odds, window constants), `services.py` (serializers, ledger-derived balances, RG cooling-off re-eval, market-liability, selection/bet grading, WR contribution, settlement/void/self-exclusion cascades).

**Dependencies:** Python 3 + Flask 3.0.3 only; stdlib `decimal` for money/odds precision. **Endpoints:** 40 routes (38 PRD §4 + `/_health` + `/_clock/set_current_utc`).

**Launcher/storage confirmation:** `start.sh` reads `$PORT` (default 10000), binds `0.0.0.0`, runs `exec python3 app.py` foreground, guards `pip install` behind a flask import check. Storage **in-memory only** (plain dicts); **nothing seeded at startup** — verified fresh boot and reboot both report `total_count == 0`.

**Verification:** ~50 scenarios from corner/difficulty recipes all pass (settlement payout 15000; floor payout 8333; cash-out divergence 11500 vs 15000; parlay round-once 5.0001→10000; push-leg-drop 3333; self-exclusion cascade; bonus completion conservation 92000; net-loss-vs-wager divergence; SoD conflict; OCC stale-version 412; deposit-limit boundary; risk cap; WR min-odds floor; withdrawal WR block; cooling-off auto-clear; precedence orderings; RBAC/ownership denials; pagination envelope).

**Design note flagged:** OCC chains thread the *account* version forward from the `POST /accounts/{id}/rg-controls` response's `version` field (RGControl row otherwise immutable), so that response surfaces the account's post-bump version — without this, the deposit-limit happy path fails with a spurious `ERR_STALE_VERSION`.

## Step 7: Run Tests and Iterate — 2026-06-25T03:25:06.000Z

**Iterations run:** 2 sweeps to converge + 1 confirming sweep (3 total 8-round parallel sweeps).

**Initial state:** Sweep 1 — 7 of 8 rounds passed 72/72; round 1 produced 3 `error` (not `failed`) results, all on the same server port (63290), all with *"API server at http://localhost:63290 could not be restarted"* on test setup. Affected: `test_cash_balance_reconciles_through_stake_then_payout`, `test_unverified_kyc_and_missing_geo_returns_kyc_error`, `test_cashout_already_cashed_out_returns_invalid_state` — boot/restart-infra errors, not assertion failures.

**Root cause (diagnosed, not guessed):** Werkzeug's dev server calls `socket.getfqdn(host)` inside `server_bind` to compose its startup log line. On macOS, `getfqdn("0.0.0.0")` blocks ~5s on a reverse-DNS lookup with no answer for the unspecified address. Measured full `start.sh` boot-to-listening was **5.1s**. The runner restarts the server before every test (`--isolation per-test-server`) and polls only **15s** for readiness; under the 8× concurrent CPU-saturated sweep, that 5s stall occasionally pushed one round's boot past the 15s window → spurious "could not be restarted". The runner's `_dnsboot/sitecustomize.py` mitigation did not reliably apply to round 1's subprocess under load.

**Tests deleted:** None. No test failed on PRD-coverage or fixture grounds; the only non-passes were boot-infra errors, which the diagnostic protocol does not attribute to test or PRD faults.

**Fixes applied to test_helpers/:** None.

**Fixes applied to implementation/:**
- `workspace/implementation/app.py` — added `_patch_getfqdn_fast()` and call it in the `__main__` block before `app.run()`. Replaces `socket.getfqdn` with a fast-path returning `"localhost"` for unspecified-address cases (`""`, `"0.0.0.0"`, `"::"`, `"0:0:0:0:0:0:0:0"`), falling through to the real resolver for any named address. Self-contained (no dependence on the runner's injected sitecustomize), affects only the cosmetic startup log line, changes **no API behavior**. Full `start.sh` boot-to-listening went from 5.1s → **0.197s**, restoring ample headroom under the 15s restart-poll window even at 8× concurrency.

**Final result:** Two consecutive 8-round parallel sweeps (16 rounds total) each returned **72/72 passed, 0 failed, 0 errors, 0 skipped** in every round. No remaining flakiness.

## Step 8: Finalize PRD — 2026-06-25T03:37:07.000Z

**File produced:** `workspace/PRD_FINALIZED.md` — verified byte-identical to `PRD.md` (`diff` clean). Line counts: PRD.md = 288, PRD_FINALIZED.md = 288. **Delta: 0 lines (0%). Edits made: NONE.**

**Rationale:** The `<step_7_diff>` contains exactly one item — the `_patch_getfqdn_fast()` boot-time dev-server `getfqdn` log-line optimization in `app.py`. Per HARD SCOPE every PRD edit must trace to a Step 7 diff item; this single item is the only candidate. After locating and analyzing it, confirmed it is a pure boot optimization with **no PRD-visible behavioral choice and no PRD/impl divergence** → correct outcome is `PRD_FINALIZED.md` identical to `PRD.md`, produced via `cp`.

**Per-edit pre-edit search log (the one Step 7 item):**
- (a) Subject: `_patch_getfqdn_fast()` — monkeypatches `socket.getfqdn` to return `"localhost"` fast for unspecified bind addresses, falling through to the real resolver for named addresses.
- (b) Impl paths enumerated: read `app.py` `_patch_getfqdn_fast` definition + its sole `__main__` call site before `app.run(host="0.0.0.0", ...)`; grepped all `implementation/*.py` for `getfqdn|socket\.|gethostname|getaddrinfo` → only matches are inside `_patch_getfqdn_fast` and its single call site; no request handler/serializer/calc/validation/DB/error/state-machine references `socket`. Cross-checked PRD §2.5 logical clock is fixed at `2026-01-01T00:00:00Z`, independent of host time/DNS.
- (c) Wording adjustment: None — no PRD silence to pin, no divergence to reconcile, zero observable API surface. No edit committed.

## Step 9: Complete PRD — 2026-06-25T03:41:49.000Z

**File:** `workspace/PRD_COMPLETED.md` (copied from `PRD_FINALIZED.md`). Line counts: 288 → 288 (unchanged; all edits in-paragraph). Char delta: 47586 → 48688 = **+1102 chars**. **Counts: ambiguity-pins = 5, mismatch-revisions = 1 (6 total).**

**Per-change bullets:**
- §2.5 The Logical Clock — insert — ambiguity — pinned clock-set response shape: `data` is a single `now` field (ISO 8601 UTC, three fractional digits) — `app.py:163`.
- §3.2 Responsible Gaming — insert — ambiguity — pinned that the created `RGControl` response's `version` carries the owning account's post-increment version (for OCC threading), not the control row's own version — `app.py:357-361`.
- §3.2 Responsible Gaming (self-exclusion cascade) — insert — ambiguity — pinned bonus-forfeiture ledger entry: single negative `BONUS` entry with `entry_type` `VOID_REFUND` sized to whole remaining bonus balance; with multiple ACTIVE grants only the first posts the zeroing entry — `app.py:373-380`.
- §3.6 Event Lifecycle — revise — mismatch — removed the claim that the system auto-transitions `SCHEDULED`→`LIVE` when the clock reaches `starts_at`; replaced with actual lazy behavior: `starts_at` lock enforced only at bet placement (`starts_at <= now` ⇒ `ERR_MARKET_NOT_OPEN`); event stays `SCHEDULED`/markets `OPEN` until an explicit operator transition — `app.py:161-162, 954-964`.
- §3.7 Placing a Bet (net-loss limit) — revise — ambiguity — pinned which bets enter the net-loss window: terminal-status bets (`WON`,`LOST`,`PUSHED`,`CASHED_OUT`,`VOIDED`) whose `settled_at` falls in window, summing `stake_cents − actual_payout_cents` — `app.py:1017-1033`.
- §3.11 Promotions (grant completion) — insert — ambiguity — pinned completion conversion ledger pair: `BONUS` debit (`entry_type` `BONUS_GRANT`) + equal-magnitude `CASH` credit (`entry_type` `PAYOUT`), posted only when remaining bonus balance strictly positive — `services.py:403-417`.

**Left unchanged (already covered or over-specification risk):** missing `expected_account_version` (§2.10 general rule); `min_odds_american` magnitude (§2.10); `grade_selection` PUSH default for non-canonical names (§3.5 open-ended); wager-window status-agnostic tally + strict-`>` boundaries (§3.3/§3.7); promotion-list `EXHAUSTED` derived-status filter (§3.11).

---

# Pipeline Complete — 2026-06-25T03:41:49.000Z

**FINAL STATUS: PASS.** All 9 steps complete. Final 8-round parallel stability sweep: **72/72 passed in every one of the 8 rounds** (`results.{1..8}.json` all `passed=72 total=72`). Task `task_0491_regulated_sportsbook` (Regulated Sportsbook, Expert tier) is fully built end-to-end with zero deleted tests and zero PRD-fairness violations.
