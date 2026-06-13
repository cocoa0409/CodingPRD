# Worklog — task_0208_loyalty_rewards

Scenario: Retail Loyalty & Rewards Program: points earn/burn rules, tier qualification/benefits, bonus-point promotions, points expiration, reward-catalog redemption, referral bonus, birthday reward, partner-points transfer

Difficulty: Expert (§0.4 Expert calibration band) — applied to scaffold-generator (Step 2) only.

## Step 1: Create task directory — 2026-06-06T16:29:24.000Z

Task directory pre-allocated at tasks/task_0208_loyalty_rewards (Step 1 auto-scan skipped per instruction). Verified `workspace/` subdirectory exists; project-root `INSTRUCTION.md` present; all prd-bench skills present.

## Step 2: Generate scaffold (Expert difficulty) — 2026-06-06T17:02:00.000Z

All three required files are written and pass every check. The pre-existing `worklog.md` and empty `workspace/` were already in the task directory (not created by me).

Generated the three scaffold artifacts for the Retail Loyalty & Rewards Program at **Expert difficulty**, all passing `scaffold_lint.py` with `VERDICT: clean lint`.

**Files written** (all under `tasks/task_0208_loyalty_rewards/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (925 lines)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — §1.8, 19 instances across all 9 rules (1011 lines)
- `SCAFFOLD_CORNER_DESIGN.yaml` — §1.9, 36 active instances + 6 `excluded_because` stubs (1245 lines)

**Dimensions:**
- **Entities: 14** — LoyaltyProgram, Tier, Member, PointsLot, PointsTransaction, Promotion, CatalogReward, Redemption, RedemptionLine, Referral, PartnerAccount, TransferBlackout, PartnerTransfer, PurchaseEvent
- **State machines: 9** — Redemption (fork-join), Referral (branching+revert), PartnerTransfer (compensation), Promotion (window lifecycle), PointsLot (expiration), PartnerAccount, Member, LoyaltyProgram, TransferBlackout
- **Key calculations: 8** — dual-variant member balance (available vs projected) and redemption cost (quoted vs final); combinatorial earn (mode a: 4-input nested multipliers), per-line redemption rounding (mode b: round-then-sum), partner-transfer conversion (mode c: circular tier→ratio→floor); plus qualifying-points, tier-evaluation, FIFO expiration sweep
- **Validations: 25 (priority-ordered); Errors: 31** (every error referenced)
- **Roles: 4** — ProgramAdmin (opaque), Member (entity_backed), PartnerOperator (entity_backed:PartnerAccount), Anonymous; **Endpoints: 58** (~35 business + ~23 required reverse-reachability/discovery GETs)
- 2 OCC concurrency rules on Member.version (redemption confirm, transfer submit)

**Difficulty band: Expert** — 14 entities (10–15), 8 calculations with 3+ variants spanning all three combinatorial modes, 9 state machines including cycles and a fork-join plus compensation branches. FIFO points-lot ledger tied to tier qualification thresholds, promo-multiplier stacking, tier-dependent partner conversion; dual-interpretation calculations, depth-3 transitive cascades, priority-conflict pairs across distinct error categories, exact-boundary tier qualification (>=5000), two temporal-overlap regimes, two compensating invariants. All numeric asserts computed in code and verified against full setup-chain replay. One arithmetic slip caught and fixed during review.

## Step 3: Copy INSTRUCTION.md — 2026-06-06T17:03:17.000Z

Copied project-root `INSTRUCTION.md` → `tasks/task_0208_loyalty_rewards/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-06T17:09:30.000Z

**Output:** `workspace/PRD.md` — **311 lines**.

**Major sections:** §1 Introduction (ledger-reconciliation + pricing-engine framing); §2 Global Specifications (2.1 RBAC all 4 roles, 2.2 Response Structure, 2.3 Pagination, 2.4 Common Resource Properties incl. lean entities PointsTransaction/RedemptionLine, 2.5 Ledger Integrity & Derived Balances, 2.6 Nested Retrieval/Existence Ordering, 2.7 Precision, 2.8 Operating Gates, 2.9 OCC on member version); §3 Business Logic (11 subsections); §4 Endpoint Definitions (58/58, 4-col); §5 Error Code Catalogue (31/31, 2-col).

**Hard Contract reports:**
- Contract 1 — Field-Name Coverage: 72/72 identifiers present, 0 missing. PASS
- Contract 2 — Rule Coverage: 2/2 OCC rules, 9 state machines, 8 calculations, all 31 errors matchable, validation priorities in §3.11, sibling branches equal density. PASS
- Contract 3 — §3 Path Purity: 462 backtick tokens scanned, 0 paths/methods/combos. PASS
- Fuzzy-word and forbidden-OCC-framing scans clean.

**Confirmation:** Did NOT read either SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml. Inputs used: SCAFFOLD.yaml, SKILL.md, section-2.2-response-structure.md, example-prd.md.

## Step 5: Generate unit tests — 2026-06-06T17:30:05.000Z

Generated complete test infrastructure for task_0208_loyalty_rewards, validated against framework and both design indices.

**test_helpers/ (Stage 1) — 9 modules:** types.py (entity TypedDicts with common_fields branching: PointsTransaction/RedemptionLine carry only id+created_at), api_client.py (one method per all 58 endpoints), api_errors.py (31 errors + HTTP-status map), assertions.py, factories.py (input fields only), constants.py (program policy + tier ladder + GOLD_RANK), test_users.py (opaque ProgramAdmin/Anonymous + entity-backed make_member_headers / make_partner_operator_headers), fixtures.py (composite setup helpers), __init__.py.

**test_suite/ (Stage 2) — conftest + 6 test files, 74 tests:**
- **38 from queue A** (Difficulty): all 19 instances covered by exactly 2 tests each
- **36 from queue B** (Corner): all 36 non-stub instances covered by ≥1 test

**Skips:** 6 corner `excluded_because` stubs correctly NOT translated (confirm_quoted_redemption_valid_transition, earn_uses_gold_multiplier_with_promo, partner_transfer_floor_precision, insufficient_points_on_confirm, lot_expired_burn_guard, occ_stale_member_version_on_confirm) — all cross-references resolve to real difficulty instances. No instances skipped for PRD-coverage reasons.

**Verification:** all files byte-compile and import; pytest collects 74 tests; coverage audit PASS; every docstring ends with exactly one Design: tag; all 74 PRD citations confirmed verbatim; no scaffold/table/§ leakage; no skip/xfail markers.

## Step 6: Generate implementation — 2026-06-06T17:30:05.000Z

Generated complete Python + Flask implementation at workspace/implementation/.

**Layout:** start.sh (reads $PORT default 10000, binds 0.0.0.0, exec foreground, guards pip install on cheap import flask); app.py (blueprint registration, error-envelope handlers, threaded); db.py (in-memory Store: 14 dicts keyed by id + logical clock + _seq); errors.py (31 (error_id, http_status) specs); response.py (meta/response_type/data envelopes); middleware.py (X-User-ID/X-User-Role auth + RBAC); routes/ (programs, members, purchases, redemptions, referrals, transfers); services/ (ledger.py calculations+state machinery, serialize.py, lookup.py, helpers.py).

**Endpoints:** 58 routes — matching scaffold endpoint_count: 58.

**Calculations/state machines (services/ledger.py):** earn (single floor, tier×promo), qualifying-points (base-spend-only floor), tier evaluation (highest-rank inclusive >=), dual balances (available vs projected), dual redemption cost (quoted vs final; round-half-up per line then integer sum), partner-transfer conversion (pinned tier→ratio→floor), FIFO burn (created_at ASC, lot-id tie-break), expiration sweep + stale-referral aging, lifetime-earned aggregation. State machines: program DRAFT→ACTIVE→CLOSED, member ACTIVE↔SUSPENDED, redemption QUOTED→CONFIRMED→{FULFILLED,CANCELLED} w/ compensating refunds, referral PENDING→{COMPLETED,EXPIRED,REVOKED}, transfer SUBMITTED→{SETTLED,REVERSED} w/ reversal compensation, promotion/partner/blackout/lot lifecycles. OCC on expected_member_version (checked last), promotion half-open overlap, blackout closed-interval+60min buffer, validation priority per PRD §3.11.

**Confirmations:** start.sh reads $PORT / binds 0.0.0.0 / runs foreground (exec); storage in-memory only (no SQLite/JSON/tmp); no seeded data (total_count=0 after restart); verified via two smoke suites on fresh isolated processes (0 failures, 0 tracebacks).

## Step 7: Run tests and iterate to PASS — 2026-06-06T17:40:00.000Z

Two consecutive clean 8-round sweeps (16/16 rounds at 74/74). Exiting with the summary.

**Iterations run:** 3 sweeps (1 baseline + 2 confirmation). Two consecutive clean 8-round parallel sweeps, all 16 rounds at 74/74.

**Tests deleted:** None. Every failing test traced to PRD-covered, uniquely-derivable rules.

**Fixes applied to test_suite/:**
- `test_suite/test_02_redemptions.py` → `test_fulfill_refunds_difference_when_final_below_quoted`: corrected the expected balance assertion from `4200` to `4700` (STEP 2 test-vs-PRD consistency fix). The test's original expectation miscomputed the second purchase's earn. PRD §3.3 states the tier multiplier is "the `earn_multiplier` of the tier named by the member's `current_tier_code`, resolved *before* this earn is applied". After the first purchase the member is SILVER (earn_multiplier 1.25), so `post_purchase(200000)` mints `floor(2000 × 1.0 × 1.25) = 2500` points, not the `2000` the old comment assumed. PRD-correct trace: 3000 (purchase 1) − 1000 (confirm burn) + 2500 (purchase 2 at SILVER) + 200 (fulfill refund 1000−800) = 4700. The implementation already produced 4700 correctly; the assertion and its inline comment were brought into agreement with PRD prose.

**Fixes applied to test_helpers/:** None.

**Fixes applied to implementation/:**
- `workspace/implementation/app.py` → module-level fast-boot guard: installed a `socket.getfqdn` fast-path for unspecified-host addresses (`""`, `"0.0.0.0"`, `"::"`) before importing/running Flask. On macOS `getfqdn("0.0.0.0")` blocks ~5.0s on a timing-out reverse-DNS PTR lookup that Werkzeug invokes only to compose its startup log banner. This 5s-per-boot stall, paid before every per-test-server restart and amplified under the 8× concurrent sweep, was pushing boots past the runner's 15s restart-poll window and producing spurious "API server could not be restarted" setup failures (the timing-sensitive flakiness that surfaced as a different single test failing in 5 of 8 rounds). Cold `start.sh` boot dropped from ~5.29s to ~0.25s. The patch is behavior-neutral — it only affects the cosmetic startup log hostname for unspecified addresses; the server still binds `0.0.0.0` and serves identical responses, and named addresses fall through to the real resolver. The runner injects an equivalent patch via PYTHONPATH, but replicating it in-app makes boot robust regardless of launch path.

**Key finding:** The benchmark's 8-round parallel design did exactly its job — the single deterministic logic bug (wrong expected value) was masked in round 5/8 of the first post-fix sweep by boot-latency flakiness, and only the union-of-8 analysis exposed both the boot stall and confirmed the logic fix.

**Orchestrator confirmation sweep:** re-ran one independent 8-round parallel sweep — all 8 rounds 74/74. results.{1..8}.json persisted in workspace/implementation/.

## Step 8: Finalize PRD — 2026-06-06T17:44:24.000Z

PRD_FINALIZED.md is a verbatim copy of PRD.md — an empty diff, the explicitly-sanctioned valid outcome here.

**Line counts:** PRD.md = 311, PRD_FINALIZED.md = 311. **Delta: 0 lines (0.0%).** Byte-identical (diff reports no differences).

**Changes:** None. Both Step 7 items were confirmed non-PRD-revealing:
- Item (a) test-side arithmetic correction (4200→4700): underlying rule (tier multiplier resolved *before* earn) already pinned verbatim in PRD §3.3; impl matches at routes/purchases.py:101-104 + services/ledger.py:68-80. Old test comment simply miscomputed second purchase at SILVER (1.25×). Pure test arithmetic fix, no PRD impact.
- Item (b) boot-latency/infrastructure fix (app.py socket.getfqdn fast-path): only changes cosmetic Werkzeug startup-log hostname; server still binds 0.0.0.0 and serves identical responses. Behavior-neutral, no PRD-observable effect.

Paths inspected: routes/purchases.py (101-138), services/ledger.py (floor_product 19-23, resolve_tier_code 68-80, tier_for_code/tier_rank 83-92, qualifying_points_window 50-65, recompute_member 131-139), app.py (full). Empty diff is correct — no edits invented to manufacture a diff.

## Step 9: Complete PRD — 2026-06-06T17:52:40.000Z

Produced `workspace/PRD_COMPLETED.md` as a minimal patch over `PRD_FINALIZED.md`, pinning every PRD silence/mismatch found against `implementation/`.

**Line/char counts:** PRD_FINALIZED.md = 311 lines / 49,841 chars; PRD_COMPLETED.md = 311 lines / 53,589 chars. Char delta +3,748 (16 paragraphs revised in place; no lines/sections added).

**Counts:** 16 changed paragraphs — 11 ambiguity-pins, 5 mismatch-revisions.

**Per-change bullets:**
- §2.1 (RBAC, Member) — insert — ambiguity — Member-callable collection lists scoped to caller's own records; referral read-by-id only when referrer/referee — routes/members.py:185-187, routes/purchases.py:167-168, routes/redemptions.py:148-151, routes/referrals.py:55-59
- §2.9 (OCC, redemption) — insert — ambiguity — expected_member_version optional (omitted → OCC skipped), persisted/echoed (null until confirmed) — routes/redemptions.py:185,192; services/serialize.py:133
- §2.9 (OCC, transfer) — insert — ambiguity — expected_member_version optional (omitted → OCC skipped), persisted/echoed — routes/transfers.py:84,98; services/serialize.py:194
- §3.1 (program create) — insert — ambiguity — lot_expiration_months & qualifying_window_months ≥1 else ERR_INVALID_REQUEST — routes/programs.py:42-45
- §3.1 (tiers) — insert — ambiguity — qualify_threshold/rank <0 → ERR_INVALID_REQUEST; STANDARD earn_multiplier≠1.0 → ERR_DUPLICATE_TIER — routes/programs.py:119-130
- §3.1 (rewards) — insert — ambiguity — point_cost integer; out-of-bound point_cost/tier_discount_pct/stock → ERR_INVALID_REQUEST — routes/programs.py:266-275
- §3.1 (partners) — insert — ambiguity — out-of-bound transfer_block_size/min_transfer_points → ERR_INVALID_REQUEST — routes/programs.py:322-325
- §3.2 (member registration) — insert — mismatch — program-active gate fires before duplicate-email check — routes/members.py:34-41
- §3.3 (earning) — insert — mismatch — earned_points floors to 0 → no lot minted; zero-delta EARN_PURCHASE tx with null lot_id appended — routes/purchases.py:129-138
- §3.5 (birthday) — insert — ambiguity — grant responds 201 with minted PointsLot (not member); year/birthday vs logical clock — routes/members.py:126-145
- §3.7 (redemption quote) — insert — mismatch — line-shape checks precede reward-existence resolution — routes/redemptions.py:33-49
- §3.7 (confirm) — revise — mismatch — confirm enforces member-active gate only, not program-active (program gate is quote-time only) — routes/redemptions.py:160-197
- §3.8 (settle) — insert — ambiguity — settle against PAUSED partner → ERR_PARTNER_PAUSED, after ERR_INVALID_STATE from-state check — routes/transfers.py:157-160
- §3.9 (sweep) — insert — ambiguity — candidate lots scoped to swept program's members; responds 200 with expired-lot array (empty when none), created_at ascending — routes/programs.py:386-394,426-427
- §3.10 (promotion create) — insert — ambiguity — bonus_multiplier<1.0 or min_eligible_cents<0 → ERR_INVALID_REQUEST — routes/programs.py:184-189
- §3.10 (refresh-promotions) — insert — ambiguity — responds 200 with all program promotions (not only transitioned), created_at ascending — routes/programs.py:238-254

Cross-referenced test_helpers/types.py and assertions.py (auxiliary only) — confirm expected_member_version is a response field on Redemption/PartnerTransfer and append-only records omit updated_at/version. No PRD change driven by tests.

---

## PIPELINE COMPLETE — 2026-06-06T17:52:40.000Z

All 9 steps complete. Final state: 74/74 tests pass across 8/8 parallel rounds (independently re-confirmed by orchestrator). Task deliverables present: SCAFFOLD.yaml + 2 design YAMLs, PRD.md → PRD_FINALIZED.md (empty diff) → PRD_COMPLETED.md (16 pins), test_helpers/ (9 modules), test_suite/ (6 files, 74 tests), workspace/implementation/ (Flask, in-memory, 58 endpoints) with results.{1..8}.json all 74/74.
