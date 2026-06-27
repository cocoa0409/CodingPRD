# Worklog — task_0504_receipt_rebate_rewards

Scenario: 504. Cashback & Receipt-Rebate Rewards (Rakuten/Ibotta style): linked-offer & receipt-scan rebate, per-merchant rate & click tracking, pending→available→paid lifecycle, threshold cash-out (PayPal/check/gift card), referral & bonus streak, return clawback/expiration, in-store vs online attribution, double-dip rule

## Step 1: Create Task Directory — 2026-06-25T16:14:59.000Z

Directory pre-allocated per orchestration instructions. Verified `tasks/task_0504_receipt_rebate_rewards/` and `tasks/task_0504_receipt_rebate_rewards/workspace/` both exist (empty). Index-scan/auto-increment skipped as instructed. INSTRUCTION.md confirmed present at project root for Step 3.

## Step 2: Generate Scaffold (Expert tier) — 2026-06-25T16:31:33.000Z

Generated the Expert-tier scaffold for **task_0504_receipt_rebate_rewards** (Cashback & Receipt-Rebate Rewards, Rakuten/Ibotta style). All three files written to `tasks/task_0504_receipt_rebate_rewards/`:

- `SCAFFOLD.yaml` (1246 lines)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (844 lines)
- `SCAFFOLD_CORNER_DESIGN.yaml` (1494 lines)

**Counts:**
- **Entities: 11** — Merchant, Offer, Member, ClickThrough, ReceiptScan, RewardClaim, CashOut, Referral, BonusStreak, LedgerEntry, ReturnEvent
- **Endpoints: 44** (22 mutating + 22 reads)
- **Error codes: 22**
- **Calculation variants: 6** calculations (reward_amount with online/in-store dual-variant, wallet_balance with gross/net dual-variant, cashout fee, streak bonus, threshold eligibility, clawback) spanning combinatorial modes (a) tiered rate-selection, (b) per-week round-then-sum, (c) gross-keyed circular fee/payout
- **State machines: 5** — RewardClaim (branching + cross-entity guards, 5 terminal-ish exits), ReceiptScan (cyclic resubmit), CashOut (cyclic retry), Referral (branching), Member (parallel account_status × verification_status)

**Design notes:**
- Archetype: ledger reconciliation + compliance/audit; flat topology; OCC on `Member.version` for cash-out creation (one sanctioned concurrency rule).
- All 9 Difficulty Rules covered with 2 instances each (18 total); §1.9 has 41 active corner instances + 2 `excluded_because` stubs.
- All formula-derived assertions are pre-computed literals (e.g., reward 800 online vs 460 in-store, fee 20/net 980, streak bonus 113, full clawback 460).
- `scaffold_lint.py` returns **VERDICT: clean lint** (all §1.8/§1.9 calls conform to §1.5; all 16 FKs have reverse-reachability). No forbidden concurrency vocabulary; design keys correctly split into their own files.
- Caveat flagged by generator: endpoint count (44) sits above the Expert band's 20–32 guideline, driven by FK reverse-reachability (LedgerEntry's four FKs need detail + filtered-list GET per entity), which §1.5 ranks above the count guideline. Interaction surface (22 mutating endpoints, 5 state machines, 6 coupled calculations) is solidly Expert; overage is honest read-surface, not padding.

## Step 3: Copy Shared Files — 2026-06-25T16:31:52.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0504_receipt_rebate_rewards/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-25T16:39:24.000Z

Generated `workspace/PRD.md` for the **Receipt-Rebate Rewards API** (Rakuten/Ibotta-style cashback platform). **256 lines.**

**Major sections produced:**
- **§1 Introduction** — reconciliation-under-uncertainty business problem and the derived-wallet model.
- **§2 Global Specifications** — 11 subsections: 2.1 RBAC (four roles, `Member` entity-backed vs. three opaque operator identities), 2.2 Response Structure (verbatim from source), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Monetary Precision/cents, 2.6 Derived-Wallet Principle (5 balance views + 8 ledger entry types w/ sign convention), 2.7 Cascades/versioning, 2.8 OCC on cash-out creation, 2.9 Reference/path resolution, 2.10 Logical Clock, 2.11 Validation Ordering (priority 1–15).
- **§3 Business Logic** — 9 subsections: merchant+offer config, member onboarding/parallel status dimensions, online earning, in-store receipt review, reward-claim lifecycle, cash-out pipeline, referrals, weekly streak bonus, returns/clawbacks/cascades. All formulas rendered as precise prose.
- **§4 Endpoint Definitions** — 4-column table, all 43 endpoint rows incl. clock capability.
- **§5 Error Code Catalogue** — 2-column table, all 22 error IDs.

**Hard Contract reports:** Contract 1 (Field-Name Coverage) PASS (60/60 entity fields, 4/4 endpoint params); Contract 2 (Rule Coverage) PASS (OCC + all 8 ledger types + enums/defaults/cascades/formulas); Contract 3 (§3 Path Purity) PASS (0 slash/method tokens in §3).

**Fidelity note (potential Step 7 relevance):** scaffold references `AVAILABLE_EXPIRY_DAYS` and `REFERRAL_EXPIRY_DAYS` symbolically without numeric values; PRD expressed both as named platform-wide windows in prose rather than inventing figures. Double-dip window (24h) and all other constants pinned exactly.

**Confirmation:** Neither design YAML read/grepped/referenced; no sibling task consulted. PRD generated solely from `SCAFFOLD.yaml` + doc-generator skill spec + verbatim §2.2 source.

## Step 5: Generate Unit Tests — 2026-06-25T16:54:32.000Z

Generated complete test infrastructure for `task_0504_receipt_rebate_rewards`.

**Test files:** 9 files under `test_suite/` (1 `conftest.py` + 8 `test_*.py`):
- `test_01_merchants_offers_members.py` (10), `test_02_reward_calculations.py` (11), `test_03_receipt_review_lifecycle.py` (9), `test_04_claim_lifecycle.py` (8), `test_05_cashout_lifecycle.py` (16), `test_06_returns_clawbacks.py` (9), `test_07_referrals.py` (5), `test_08_member_state_rbac_priority.py` (9).

**Total test count:** 77 test functions, each carrying exactly one `Design:` docstring tag.

**Queue split:**
- **Queue A (Difficulty):** 36 tests — all 18 difficulty instances (9 rule_ids × 2) covered with exactly 2 tests each. Second test per instance asserts a distinct, independently PRD-derivable facet.
- **Queue B (Corner):** 41 tests — every one of the 41 non-stub corner instances covered with ≥1 test.

**Skipped:** No design instances skipped. The 2 `excluded_because:` corner stubs (`error_receipt_approve_already_terminal`, `cashout_below_minimum_returns_422`) correctly NOT translated (cited difficulty instances own the assertion). Every instance passed the PRD-first two-condition filter.

**One fidelity note (potential Step 7 relevance):** the difficulty instance `dual_variant_calc/reward_rate_online_vs_in_store_diverge` has an internally inconsistent in-store assertion in the YAML (recipe sets receipt `purchase_total_cents: 10000` → PRD in-store formula resolves to 500, but YAML asserts `460` = the value for an 8000 receipt). To stay PRD-correct, the two tests for that instance assert the online value (800, correct) + the divergence, and verify the in-store variant on an 8000 receipt yielding 460 (formula-consistent); did NOT hard-assert 460 against a 10000 receipt.

**test_helpers/ files written (9):** `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`. All files pass AST parse; citations verified verbatim-present in `workspace/PRD.md`; no scaffold/Table N/§1.x leaks; no skip/skipif/xfail markers.

## Step 6: Generate Implementation — 2026-06-25T16:54:32.000Z

Generated a complete Python + Flask implementation at `workspace/implementation/`.

**Source files written (33 files):**
- **Launcher/deps**: `start.sh`, `requirements.txt`
- **Core**: `app.py`, `state.py` (single in-memory Store), `db.py`, `clock.py` (logical clock), `constants.py`, `errors.py` (22-error catalogue), `response.py`, `middleware.py` (auth/RBAC), `validation.py`
- **Routes** (`routes/`): `merchants.py`, `offers.py`, `members.py`, `ledger.py`, `clickthroughs.py`, `receipt_scans.py`, `reward_claims.py`, `cashouts.py`, `referrals.py`, `return_events.py`, `clock_route.py`, `common.py`
- **Services** (`services/`): `calculations.py`, `wallet.py`, `ledger.py`, `claims.py`, `streak.py`, `timeadvance.py`, `referrals.py`, `serialize.py`

**Endpoint count:** 44 distinct method+path routes (every PRD §4 row + SCAFFOLD endpoint list).

**Storage:** in-memory only — plain Python dicts on a single `Store` instance created at import in `state.py`. No SQLite, no JSON-on-disk, no external persistence. Confirmed zero entity writes at module/startup time and via a live two-boot test (boot 2 starts with count 0, clock resets to `2026-01-01T00:00:00.000Z`). No seeded data.

**start.sh contract:** reads `$PORT` (default 10000), binds `0.0.0.0`, runs foreground via `exec python3 app.py`, guards `pip install` behind import check so per-test reboots don't re-install.

**Self-verification:** ran 3 smoke suites (113 assertions, all passing) exercising envelope, auth/RBAC, all 4 error-precedence layers, online/in-store reward calc (per-component floor), maturation via logical clock, OCC stale-version, per-method cashout minimums + fee schedule (PayPal 2%/fee-free, CHECK flat 200), reservation/process/settle/retry cycle, proportional clawback w/ ceiling, RESERVED-claim clawback cascade (cash-out→FAILED, siblings revert), referral lifecycle, duplicate-referral guard, double-dip block, merchant-disable, offer expiry, pinned per-week-rounded streak (1wk=25, 2wk=63, 3wk=113).

**Scaffold-gap note (potential Step 7 relevance):** two platform-wide windows referenced in PRD as "a fixed number of days" have no concrete value pinned in PRD.md or SCAFFOLD.yaml: `AVAILABLE_EXPIRY_DAYS` (claim auto-expiry) and `REFERRAL_EXPIRY_DAYS` (invite expiry). Set to 90 and 30 days respectively in `constants.py`. If a test pins different values, those two constants are the adjustment point — but per PRD-First contract, a test asserting an unpinned numeric window should be deleted in Step 7.

## Step 7: Run Tests and Iterate — 2026-06-25T17:09:01.000Z

Final state: **77/77 passing in all 8 parallel rounds, two consecutive clean confirmation sweeps, 0 failures, 0 errors.**

**Iterations run:** 4 sweeps. (1) Baseline: 2 stable failures. (2) After two test fixes: 1 host-contention restart error surfaced. (3) Attempted bind-retry hardening — made contention worse (3 restart errors), reverted. (4) Two consecutive clean confirmation sweeps: 77/77 in all 8 rounds.

**Tests deleted:** None. Both genuine failures passed STEP 1 (PRD coverage + unique derivability), so neither qualified for deletion.

**Fixes applied to test_suite/:**
- `test_suite/test_06_returns_clawbacks.py` — added the missing `make_member_headers` to the `test_helpers` import block (line 9). The test `test_full_return_emits_clawback_ledger_entry` called it at line 112 but it was absent from the imports, raising `NameError`. STEP 2 test-suite bug; the assertion (clawback ledger entry `-460`, PRD §3.9 + §2.6) is verbatim-covered and uniquely derivable, so only the import was fixed — the assertion was untouched.
- `test_suite/test_02_reward_calculations.py` — fixed the setup of `test_streak_bonus_three_weeks_per_week_round_then_sum`. STEP 2 test-setup bug: the streak's qualifying week is the week a claim *reaches* AVAILABLE (PRD §3.8), and maturation fires only on a clock advance (PRD §2.10/§3.5). The original setup advanced the clock only twice and never matured the third claim, so only 2 weeks qualified (got 2, expected 3). Added a same-week clock advance (`+01:00:00Z`) after each of the three claim filings so each matures inside its own creation week (indices 2922/2923/2924), yielding a true 3-week streak. Both assertions (streak == 3, bonus == 113) are PRD-correct and were left unchanged.

**Fixes applied to implementation/:** None. (A bind-retry was trialed in `app.py` to harden against per-test restart races, but it worsened the contention and was fully reverted; `app.py` is byte-identical to its original `app.run(...)` form.)

**Note on the "could not be restarted" errors:** These were host-level restart-poll-window timeouts under the ~8x peak load of the concurrent sweep (the runner kills+respawns the server before every test). They are not test, test-helper, or implementation defects — the runner already injects a `getfqdn` patch for the macOS DNS stall, and cold boot here measures ~0.15s. With the two real bugs fixed and no counterproductive hardening, two back-to-back sweeps came back fully clean (77/77 × 8 rounds, zero errors).

## Step 8: Finalize PRD — 2026-06-25T17:12:07.000Z

(Step 8 ran — Step 7 had 2 `test_suite/` fixes, so the all-zero skip condition was not met.)

**PRD_FINALIZED.md is byte-identical to PRD.md — no edits were made.** Line counts: PRD.md = 256, PRD_FINALIZED.md = 256. Delta: 0 lines (0.0%). Verified via `diff` (identical).

**Changes:** None. Both `<step_7_diff>` items were pure test-suite bugs whose underlying behavior is already uniquely pinned by the existing PRD, so there is no PRD silence or PRD/impl mismatch to patch.

**Per-item analysis:**
- **Item 1 (test_06 — missing `make_member_headers` import):** pure test-harness NameError fix. Asserted behavior (full return emits `CLAIM_CLAWBACK` ledger entry cancelling credit to zero) verbatim-pinned by PRD §3.9 + §2.6. Impl matches at `services/claims.py:101-119`, `services/calculations.py:110-123`. No silence.
- **Item 2 (test_02 — streak timing setup):** test-setup clock/maturation-timing bug; impl unchanged. Qualifying-week rule pinned in §3.8, maturation-on-clock-advance in §2.10, forced maturation in §3.5. 3-week bonus = 113 uniquely derivable from §3.8 formula (25+38+50=113). No silence.

**Pre-edit search log (no edits committed):** enumerated all impl paths for both subjects:
- *Clawback:* `services/calculations.py:compute_clawback`, `services/claims.py:clawback_claim` (negative ledger emit + RESERVED cascade to cash-out FAILED + sibling reverts), `routes/return_events.py` — all consistent with §3.9/§2.6.
- *Streak/maturation-week:* `services/claims.py:mature_claim`, `services/streak.py` (`week_index_of`/`_qualifying_week_indexes`/`recompute_streak`/`compute_streak_bonus`), `services/timeadvance.py:fire_due_transitions`, three claim-creation sites. Notably the referral-bonus claim is created directly `AVAILABLE` and never calls `recompute_streak`, so it never contributes to the streak — consistent with §3.8 ("claims that mature from PENDING to AVAILABLE"). Nothing required widening/re-scoping.

**Conclusion:** PRD.md already uniquely determines both Step 7 subjects; PRD_FINALIZED.md left identical, as the method explicitly permits.

## Step 9: Complete PRD — 2026-06-25T17:17:16.000Z

Full PRD-vs-`implementation/` scan, source = `PRD_FINALIZED.md`. Output `workspace/PRD_COMPLETED.md`.

**File counts:** PRD_FINALIZED.md (source) and PRD_COMPLETED.md both 256 lines (all edits in-paragraph); char delta **+1926** (44,886 → 46,812).

**Change counts:** 9 total — **1 mismatch-revision, 8 ambiguity-pins.**

**Per-change:**
- §3.2 Member onboarding — revise — mismatch — PRD said `email` "is unique"; impl enforces no uniqueness (duplicate emails accepted, distinct rows). Revised to state uniqueness is not enforced. — `routes/members.py:25,32-45`
- §3.3 Online claims — insert — ambiguity — pinned business-check evaluation order at online-claim creation: merchant-disabled → offer-inactive → attribution-window. — `routes/reward_claims.py:75-90`
- §3.5 Claim lifecycle (`expires_at`) — insert — ambiguity — "fixed number of days" available-claim expiry window pinned to 90 days. — `constants.py:38`
- §3.5 Forced maturation — insert — ambiguity — pinned force-mature error mapping: terminal claim → `ERR_CLAIM_ALREADY_TERMINAL`; non-PENDING or not-yet-matured PENDING → `ERR_INVALID_STATE`. — `routes/reward_claims.py:169-175`
- §3.6 Cash-out request — insert — ambiguity — pinned that supplied `expected_member_version` is retained on and echoed back by the cash-out resource. — `routes/cashouts.py:76`; `services/serialize.py:40-41`
- §3.7 Referral reward cascade — insert — ambiguity — pinned referrer bonus claim field shape: `merchant_id`/`offer_id`/`click_through_id`/`receipt_scan_id` null, `purchase_amount_cents` 0, `matures_at` = now, `expires_at` null (never expires). — `routes/referrals.py:111-128`
- §3.7 Referral expiry — insert — ambiguity — "fixed number of days" referral expiry window pinned to 30 days. — `constants.py:39`
- §3.8 Streak qualifying weeks — insert — ambiguity — pinned that a week qualifies by the week-index recorded once at maturation and stays qualifying permanently even after the claim leaves AVAILABLE. — `services/streak.py:43-58`; `services/claims.py:21`
- §3.8 Streak bonus crediting — insert — ambiguity — pinned that `pending_streak_bonus_cents` is recomputed in full on each maturation and is never auto-credited; no `STREAK_BONUS` ledger entry is ever emitted (entry type reserved/unused). — `services/streak.py:90`

**Note:** tests used only as auxiliary cross-reference; implementation was alignment authority throughout. The window day-counts (90/30) are not asserted by any test (tests jump the clock far past them), so they are genuine PRD silences pinned from `constants.py`.

---

## PIPELINE COMPLETE — 2026-06-25T17:17:16.000Z

All 9 steps finished. Final state: **77/77 tests passing across 8 parallel stability rounds (two consecutive clean sweeps), 0 failures, 0 errors.** Deliverables present: SCAFFOLD.yaml (+ 2 design indices), worklog.md, test_helpers/ (9 files), test_suite/ (9 files, 77 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ (33 files + start.sh)}.
