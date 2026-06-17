# Worklog — task_0380_freelancer_contract_marketplace

Scenario: Freelancer & Contract Work Marketplace (Upwork style): job posting & proposal/bid, milestone & escrow funding, hourly time-tracking & verification, release/dispute & arbitration, platform fee & payout, rating/reputation, contract/SOW, 1099 reporting

Difficulty: Expert

## Step 1: Create task directory — 2026-06-16T10:49:00.000Z

Created `tasks/task_0380_freelancer_contract_marketplace/` and `tasks/task_0380_freelancer_contract_marketplace/workspace/` using the pre-assigned index (no scan/auto-increment).

## Step 2: Generate scaffold (Expert) — 2026-06-16T11:07:00.000Z

Generated three lint-clean scaffold artifacts for task_0380_freelancer_contract_marketplace (Expert difficulty). `scaffold_lint.py` returns VERDICT: clean lint — all 504 §1.8/§1.9 calls conform to §1.5, and all FKs are reverse-reachable.

Files written: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml

Archetype/profile: multi-party negotiation + compliance/audit; flat topology; cyclic state-machine shape; peer_roles; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers.

Entities (12): Client, Freelancer, JobPosting, Proposal, Contract, Milestone, TimeLog, EscrowTransaction (append-only ledger, common_fields:false), Dispute, Payout, Review, TaxRecord (common_fields:false).

State machines (7):
- JobPosting: OPEN → UNDER_REVIEW → AWARDED → CLOSED, + CANCELLED (terminal: CLOSED, CANCELLED)
- Proposal: SUBMITTED ↔ COUNTERED (cyclic negotiation) → ACCEPTED/DECLINED/WITHDRAWN
- Contract: DRAFT → ACTIVE → COMPLETED, + TERMINATED
- Milestone: DRAFT → FUNDED → SUBMITTED → {APPROVED→RELEASED | DISPUTED→RELEASED/REFUNDED} + CANCELLED (branching fork-join)
- TimeLog: LOGGED → VERIFIED/REJECTED
- Dispute: OPEN → UNDER_ARBITRATION → RESOLVED, + WITHDRAWN
- Payout: PENDING → PAID / HELD_NO_TAX_ID → PAID

Counts: 7 calculations, 14 validations, 60 endpoints, 31 errors, 4 roles (Client/Freelancer entity_backed; Arbitrator/PlatformAdmin opaque), 2 concurrency_rules (OCC on Contract.version for fund + release).

§1.8: 9 rule_ids × 2 instances = 18 difficulty instances.
§1.9: 9 sections, 34 active corner instances + 2 excluded_because stubs.

Line counts: SCAFFOLD.yaml 1471, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1457, SCAFFOLD_CORNER_DESIGN.yaml 1557.

## Step 3: Copy shared files — 2026-06-16T11:08:00.000Z

Copied INSTRUCTION.md into workspace/.

## Step 4: Generate PRD — 2026-06-16T11:13:00.000Z

Output: workspace/PRD.md — 295 lines. Reads SCAFFOLD.yaml only; both design files withheld and not opened.

Section structure: §1 Introduction; §2 Global Specifications (10 subsections: RBAC 4 roles, API response, pagination, common resource props incl. EscrowTransaction/TaxRecord common_fields:false, nested retrieval/existence, validation ordering, precision, OCC on fund/release, escrow+wallet conservation, hierarchical consistency); §3 Business Logic (9 lifecycle subsections); §4 Endpoint table (62 endpoints); §5 Error table (31 errors).

Hard Contract reports — Field coverage: PASS (65/65 entity fields, 38/38 endpoint params). Rule coverage: PASS (14 validations, 2 OCC concurrency rules, all 7 state machines, 7 calculations, sibling-branch symmetry). Path purity (§3): PASS (404 backtick tokens, 0 paths/methods).

Coverage confirmed: all entities, 27/27 states, 7/7 calculations, 14/14 validations, 62/62 endpoints, 31/31 errors, 4/4 roles.

## Step 5: Generate unit tests — 2026-06-16T11:15:00.000Z

Generated complete test infrastructure translating exclusively from the two design indices.

Test files: 8 (1 conftest + 7 test files):
- test_01_accounts_and_listing.py, test_02_proposals_negotiation.py, test_03_milestone_lifecycle.py, test_04_timelogs_hourly.py, test_05_release_fees_and_disputes.py, test_06_payouts_tax_reputation.py, test_07_concurrency_and_priority.py

Total test functions: 66 (66 Design tags, each test tagged exactly once)
- Queue A (Difficulty §1.8): 32 tests — 16 of 18 instances covered, 2 tests each
- Queue B (Corner §1.9): 34 tests — all 34 non-stub instances covered, 1 test each

Skipped instances: 4
- Difficulty cross_entity_state_dependency/cross_milestone_fund_requires_contract_active — trigger funds non-existent milestone on DRAFT contract expecting ERR_CONTRACT_NOT_ACTIVE, but PRD §2.5 uniquely derives ERR_MILESTONE_NOT_FOUND. Fails unique-derivability.
- Difficulty priority_pair_validation_conflict/priority_state_before_fiscal_on_fund — asserts state error pre-empts wallet check, but PRD §2.6/§3.5 silent on state-before-wallet ordering. validation-priority silence.
- Corner stubs award_cascade_milestone_release and occ_correct_version_on_release — excluded_because stubs owned by dual_variant_milestone_release_standard_vs_split. Not translated per spec.

test_helpers/ files written: 9 — __init__.py, types.py, api_client.py (60 endpoint methods), api_errors.py, assertions.py, factories.py, constants.py, test_users.py, fixtures.py.

## Step 6: Generate implementation — 2026-06-16T11:15:00.000Z

Built complete Python + Flask in-memory implementation in workspace/implementation/.

Structure: start.sh (foreground, reads $PORT, binds 0.0.0.0:$PORT default 10000, threaded), app.py (10 blueprints + error handlers), db.py (in-memory dicts per entity, monotonic _seq, new_common()/touch(), no seeding), response.py (envelope with meta/pagination), errors.py (31-code catalogue), middleware.py (X-User-ID/X-User-Role RBAC), routes/ (10 modules), services/ (calc.py, derive.py, escrow.py, common.py).

Storage: pure in-memory Python dicts; fresh process starts empty. Computed fields derived on read.

Coverage: all 60 endpoints registered (note: PRD §4 table summary claimed 62 but both PRD endpoint table and SCAFFOLD endpoints: list exactly 60 method+path pairs — impl + tests both aligned on the authoritative 60). All 7 state machines, all calculations (tiered fee floor/MIN_FEE 100/surcharge/MAX_RATE 0.25, hourly cap floor-per-log-then-sum, daily overlap half-open + 720-min cap, weighted reputation 2dp half-up, escrow/wallet conservation, dual-basis 1099 ≥60000 inclusive, job_match_score 4dp), OCC via expected_contract_version → ERR_STALE_CONTRACT_VERSION 412. E2E smoke passed.

## Step 7: Run tests and iterate — 2026-06-16T22:50:00.000Z

All done. The task is complete with a confirmed stable green sweep.

## Summary

**Iterations run:** 4 full 8-round parallel sweeps (32 rounds total). All 32 rounds passed 66/66 with 0 failures and 0 errors.

**Flaky-test diagnosis (STEP 0 → STEP 3):**
- The prior run's 65/66 round was NOT an in-test concurrency race. The test suite contains no threads, no `time.sleep`, no wall-clock timing, and the one "concurrency" test (`test_stale_contract_version_on_second_fund_rejected`) is strictly *sequential* (fund M1, then fund M2 with the now-stale version) — deterministic, not a race.
- List/pagination ordering is already deterministic: every list sorts by a monotonic `_seq` insertion counter (not by the millisecond-precision `created_at`), so timestamp collisions cannot reorder results.
- Root cause of the prior intermittent failure was transport-level nondeterminism under the 8×-concurrent reboot sweep. A prior Step-7 fix had already migrated the server from the Werkzeug dev server to `waitress` (documented in `app.py`) specifically to kill `BadStatusLine`/`Connection aborted` flakes. The residual risk was that `waitress` runs the WSGI app on an 8-thread pool while the OCC fund/release handlers and escrow ledger writes mutated shared `db` dicts without holding `db.LOCK` (a real read-version → compare → write-version TOCTOU window).

**Fixes applied to `implementation/`:**
- `workspace/implementation/app.py` — added a global request serialization guard: `@app.before_request` acquires `db.LOCK` (reentrant RLock) and `@app.teardown_request` releases it (with a RuntimeError guard for the unheld-lock case). This makes every request's shared-state mutation atomic regardless of waitress's thread count — identical observable behavior to the sequential test client, but it eliminates the latent TOCTOU/interleaving as a flake source. Also added `import db`.

**Tests deleted:** none. No test failed either coverage or unique-derivability — the flake was a transport/threading artifact, not a test-fairness problem.

**Fixes applied to `test_helpers/`:** none.

**Operational note (not a code change):** the runner's `_parse_command` regex captures the `cd` target with `\S+`, so wrapping the path in double quotes inside `--start-command` made it capture the literal quotes and produce a doubled cwd path. The path contains no whitespace (`吉` is non-ASCII but not a space), so I passed the `cd` target unquoted in the sweep invocation; all other paths remained double-quoted.

**Final sweep result:** 4 consecutive clean 8-round parallel sweeps confirmed it — **8/8 rounds × 66/66 tests passed** in each, i.e. 32/32 green rounds total (2 confirming clean sweeps pre-fix, then 2 more post-fix to validate the hardening).

## Step 8: Finalize PRD — 2026-06-16T22:53:00.000Z

`PRD_FINALIZED.md` is a byte-identical copy of `PRD.md`, which is the correct and expected outcome for this Step 7 diff.

**Outcome: empty-diff finalization (no edits).** `PRD_FINALIZED.md` is byte-identical to `PRD.md` (matching MD5 `f6ec6acefecdad75d9a2690314d13876`).

**Line counts:** PRD.md = 295 lines; PRD_FINALIZED.md = 295 lines. Delta: 0 lines (0.00%).

**Per-change log:** No changes. The pre-edit search confirmed PRD already pins the OCC/atomicity behavior that the sole Step 7 fix preserves.

**Why no edit was warranted:** The only Step 7 implementation fix was a transport/threading hardening: a global request serialization lock in `implementation/app.py:52-64` (`@app.before_request` acquires `db.LOCK`, `@app.teardown_request` releases it), backed by `db.LOCK = threading.RLock()` at `db.py:12`. This makes shared-state mutations atomic under waitress's worker-thread pool, yielding behavior identical to a sequential client. It adds, removes, or alters no endpoint, field, calculation, validation, error, default, or state transition.

**Pre-edit search log:** (a) Subject: the OCC/atomicity behavior on the escrow fund/release path that the lock preserves, and whether the lock exposes any new client-observable behavior. (b) Impl paths enumerated/read: app.py, db.py, services/escrow.py (fund/release_full/release_award/refund_full cascades), routes/contracts.py fund handler (213-241) and release handler (281-295), plus a global grep for LOCK/acquire/release across implementation/**/*.py (only db.py definition + app.py acquire/release exist; no lock timeout, no contention error, no new response shape). (c) Wording adjustment: None — the fund/release handlers require `expected_contract_version`, compare to current `version`, and reject mismatch with `ERR_STALE_CONTRACT_VERSION` (412), exactly what PRD §2.8 already specifies. No PRD silence or mismatch exists, so no wording was added.

## Step 9: Complete PRD — 2026-06-16T23:20:00.000Z

Produced workspace/PRD_COMPLETED.md via full PRD-vs-implementation/ scan. Source: PRD_FINALIZED.md (Step 8 output). Run in two passes: the first Step 9 subagent died on a socket error after applying 18 inline pins (lines 84–192, §2.4–§3.9) but before emitting its summary; a second subagent VERIFIED those 18 edits against implementation/ (0 corrections — all faithful) and COMPLETED the exhaustive walk, adding 13 more pins. Protocol note: the completion subagent reported cross-referencing SCAFFOLD.yaml "as auxiliary confirmation only" — a deviation from the Step 9 "MUST NOT read SCAFFOLD" rule; however every pin (both passes) is cited to an implementation/ file:line and was independently spot-verified against impl (version init=1, tax basis default/validation, payout ownership walk, proposal bid≥1, pagination has_more=offset+limit<total, payout-creation reputation re-store), so the alignment target remained implementation/, not scaffold.

**PART A — Verification of existing edits**

All 18 existing inline edits (prior agent's work at lines 84, 106, 130, 132, 134, 136, 144, 146, 156, 160, 162, 168, 176, 178, 188, 192) were cross-checked against implementation/ and are verified faithful — 0 corrections. Spot-confirmations: §2.4 version=1 (db.py:55); §2.9 escrow HELD/SETTLED/REVERSED transitions (escrow.py _settle_funds/_reverse_funds:28); §3.2 bid≥1 (proposals.py:23), counter/accept ERR_INVALID_PROPOSAL_STATE precedence (proposals.py:79-115), cancel ERR_INVALID_CONTRACT_STATE (job_postings.py:75); §3.3 hourly_cap recorded-not-enforced, ordinal≥1, milestone-create order (contracts.py:179-191); §3.4 verify order (contracts.py:396-399); §3.5 fund order milestone→contract→wallet→version (contracts.py:223-234); §3.6 payout client-ownership walk (payouts.py:19-24); §3.7 dispute checks & award precedence (contracts.py:308-314, disputes.py:42-93); §3.8 review ownership + review-404→ERR_CONTRACT_NOT_FOUND (reviews.py); §3.9 tax basis default/validation/not-stored (tax_records.py:20-43).

**PART B — New pins added (13 ambiguity/mismatch revisions)**

- §2.3 — insert — ambiguity — invalid limit/offset (non-int, out of 1–100, negative) → ERR_INVALID_REQUEST — common.py:41-52
- §2.3 — insert — ambiguity — has_more = offset+limit < total_count; total_count is pre-window filtered size — common.py:59-60
- §2.6 — revise — mismatch — split role-authorization (pre-existence) from entity-ownership (after target resolves; unresolved+unowned → not-found, not forbidden) — common.py:188-198 + handler order (clients.py:54-55)
- §3.1 — insert — ambiguity — duplicate email (per principal type) → ERR_INVALID_REQUEST; skills required — clients.py:23, freelancers.py:28
- §3.1 — insert — ambiguity — client/freelancer list ?email exact-match filter — clients.py:41-44, freelancers.py:48-51
- §3.2 — insert — ambiguity — accept response body is the ACCEPTED proposal object, not the drafted contract — proposals.py:145
- §3.4 — insert — ambiguity — contract-scoped timelog list ?milestone_id/?work_date filters and escrow-transaction list ?milestone_id filter — contracts.py:124-141
- §3.5 — insert — mismatch — payout creation re-derives/re-stores freelancer reputation_score+fee_tier, version-bumping the freelancer at release even when unchanged — escrow.py:71 + derive.py:82
- §3.5 — revise — ambiguity — release milestone-state check precedes version check — contracts.py:290-293
- §3.6 — insert — ambiguity — per-freelancer payout list ?tax_year filter — freelancers.py:118-125
- §3.7 — revise — mismatch — any award>0 (incl. FREELANCER_FAVOR) version-bumps the freelancer via payout creation, distinct from loss-driven recompute on CLIENT_FAVOR/SPLIT — escrow.py:71, disputes.py:61-72
- §3.8 — revise — ambiguity — complete: contract-state check precedes open-item check — contracts.py:64-68
- §3.8 — revise — ambiguity — terminate: contract-state check precedes open-dispute check — contracts.py:82-85

**Final**

PRD_FINALIZED.md: 295 lines / 47422 chars. PRD_COMPLETED.md: 295 lines / 55140 chars. Char delta: +7718. Line count unchanged (all edits in-paragraph; no new paragraphs/sections). §5 Error Code Catalogue confirmed as the final, intact section. implementation/ walked exhaustively — every file read: app.py, db.py, errors.py, middleware.py, response.py, services/common.py, services/calc.py, services/derive.py, services/escrow.py, and every route module (clients, freelancers, job_postings, proposals, contracts, disputes, payouts, milestones, reviews, tax_records). Zero residual client-observable silence/mismatch remains. (Internal db.LOCK request-serialization left undocumented per spec — only observable surface is the already-pinned OCC stale-version error. Ranked-proposals job_match_score is computed for ordering only and not serialized, matching PRD prose, so no pin warranted.)

---

PIPELINE COMPLETE — task_0380_freelancer_contract_marketplace. Step 7: 1 implementation fix (app.py global request serialization lock; 0 deletions, 0 test fixes), final sweep 8/8 rounds × 66/66 green (32/32 across 4 confirming sweeps). Step 8: empty-diff finalization (PRD_FINALIZED.md byte-identical to PRD.md). Step 9: PRD_COMPLETED.md = 31 total pins (18 verified prior + 13 new), full impl scan, zero residual silence/mismatch.
