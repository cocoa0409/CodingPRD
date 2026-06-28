# Worklog — task_0602_bill_negotiation_subscription

## Step 1: Create Task Directory — 2026-06-21T12:36:00.000Z

Created `tasks/task_0602_bill_negotiation_subscription/` with `workspace/` subdirectory (pre-assigned index 0602, no scan performed).

## Step 2: Generate Scaffold (Expert band) — 2026-06-21T12:49:00.000Z

All enum states are reachable and match the declared field enums. The scaffold is complete and self-consistent.

Note: RefundClaim has DENIED as terminal but also has a DENIED→DISPUTED transition — that's intentional (DENIED is a "soft terminal" that can be escalated via the dispute loop, which is the cyclic shape). The state machine table correctly declares both. This is acceptable for the cyclic design, though strictly DENIED is re-enterable. The dispute loop is the intended non-linear feature.

All three files are written and the lint verdict is clean.

### Summary

Generated a complete Expert-band scaffold for the **Bill Negotiation & Subscription Manager** scenario. All three files written; `scaffold_lint.py` reports **VERDICT: clean lint** (363 calls scanned across §1.8/§1.9, all FKs reverse-reachable).

**Complexity profile:** workflow_orchestration + ledger_reconciliation; flat topology; cyclic state machines; peer_roles; layers = dual-variant calc, cascading side effects, scheduled/deferred (logical clock), rate/threshold triggers, optimistic concurrency.

**SCAFFOLD.yaml counts:**
- **Entities: 10** — Member, SavingsAccount, LinkedAccount, RecurringCharge, Subscription, NegotiationCase, ConciergeAgentProfile, RefundClaim, SavingsLedgerEntry, SystemClock
- **State machines: 6** — incl. NegotiationCase (cyclic PROPOSED↔COUNTERED rounds), RefundClaim (DENIED↔DISPUTED dispute loop), Subscription (CANCEL_FAILED→CANCEL_REQUESTED retry loop), SavingsLedgerEntry (transfer/reverse compensation)
- **Calculations: 5** — annualize_charge_cost (cadence threshold incl. WEEKLY×52), success_fee_split (tiered rate→round→cap→floor, dual basis: negotiation delta vs refund absolute), refund_pursuit_amount (3-way branch), member_lifetime_savings_rollup, savings_report_summary
- **Validations: 19** (priority-ordered), **Errors: 19**, **Endpoints: 49** (incl. `/_clock/set_current_utc` defaulting to 2026-01-01T00:00:00Z)
- **Concurrency rules: 2** (OCC on Subscription and RefundClaim version)
- **Roles: 4** — Anonymous (opaque), Member (entity_backed:Member), ConciergeAgent (entity_backed:ConciergeAgentProfile), PlatformAdmin (opaque)

**Difficulty design:** 9 rule_ids × 2 = **18 instances**, all 9 §0.5 rules covered.
**Corner design:** 9 sections, **39 testable instances + 1 excluded_because stub**.

All formula-derived asserts pre-computed in Python and pinned as literals (e.g., negotiation gross 12000→fee 4200→net 7800; cap test 700000→fee 20000; price-drop claim 3000; outage 2000; weekly annualize 52000).

## Step 3: Copy Shared Files — 2026-06-21T12:50:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-21T12:55:00.000Z

PRD generated at `workspace/PRD.md` — 264 lines.

Sections: §1 Introduction (3 paras), §2 Global Specs (10 subsections: RBAC/4 roles, response envelope, pagination, common properties + 2 common_fields:false entities, integer-cents round-half-up, cascades/consistency, OCC dual version fields, nested-path resolution, validation priority 1–9, logical clock default 2026-01-01T00:00:00Z), §3 Business Logic (10 workflow subsections, all 5 formulas in prose), §4 50-row endpoint table, §5 19-error catalogue.

Hard contract reports: Field coverage PASS (54/54 fields, 39/39 inputs), Rule coverage PASS (19 validations, 2 OCC, all transitions, 5 calcs, sibling-branch symmetry), Path purity PASS (323 backtick tokens, 0 paths/methods in §3).

Confirmation: did NOT read SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml.

## Step 5: Generate Unit Tests — 2026-06-21T13:06:00.000Z

Generated complete test infrastructure from the two design indices only (no freelance walking of SCAFFOLD.yaml).

**Test counts:** 7 test files, 73 tests total, all collecting and compiling cleanly. Each test carries exactly one verbatim `Design:` tag resolving to a real source instance; no untagged/dual-tagged tests; no skip/xfail; no scaffold leakage.

**Queue A (Difficulty):** 18/18 instances translated, each with ≥2 tests (9 rules × 2 instances). Covers dual-variant success-fee split, tier→round→cap order, refund-pursuit non-linearity, propose/counter and dispute cycles, depth-2/depth-3 cascades, state-vs-fiscal and ownership-vs-referential priority pairs, baseline + empty-report boundaries, cross-entity confirm/open preconditions, trial-reminder inclusive/exclusive edges, transfer/reverse + detect/dismiss conservation invariants.

**Queue B (Corner):** 37/40 non-stub instances translated (≥1 test each).
- **Skipped: 2** — both invariant-mismatch (unique-derivability fails: scaffold cap ≠ PRD cap):
  - `state_machines/max_rounds_reached_on_propose` — recipe assumes MAX_ROUNDS=3, PRD §3.5 pins eight rounds.
  - `state_machines/max_dispute_rounds_reached` — recipe assumes cap=2, PRD §3.9 pins three rounds.
- **Stub correctly not translated: 1** — `validations/accept_above_baseline_when_in_proposed` (excluded_because → boundary_precision_check/accept_offer_exactly_at_baseline_allowed).

**Citation integrity:** all 131 quoted citation chunks match PRD.md literally.

**Helper files:** `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`; `test_suite/conftest.py` bridges client + role fixtures.

## Step 6: Generate Implementation — 2026-06-21T13:06:00.000Z

Built complete Python + Flask implementation at `workspace/implementation/`.

**Files (11):** start.sh (executable), requirements.txt (flask==3.0.3), app.py, db.py (in-memory Store + logical clock), errors.py (19-entry catalog), response.py, middleware.py (X-User-ID/X-User-Role auth), helpers.py (validation + pagination), calculations.py (Decimal + ROUND_HALF_UP), serializers.py (reminder_due recompute vs clock).

**Endpoints: 50** — all PRD §4 routes plus `/_clock/set_current_utc`.

**Key behaviors (smoke-verified):** WEEKLY annualize ×52; tiered fee with cap (100000→30000 capped 20000; 20000→7000; 9999→4000); refund types PRICE_DROP/DOUBLE_BILL/SERVICE_OUTAGE; transfer increments balance by member_net_cents, REVERSED excluded from report; OCC ERR_STALE_VERSION 412, ERR_UNAUTHENTICATED 401, ERR_FORBIDDEN_ROLE 403; validation precedence per §2.9 (OCC priority 18 before member-suspension 19).

**start.sh:** reads $PORT (default 10000), guards pip install behind flask import check, `exec python3 app.py`; app.run(host="0.0.0.0", port=$PORT, threaded=True), foreground.

**Storage:** in-memory only, no SQLite/JSON/disk, NO seeding confirmed.

## Step 7: Run Tests and Iterate — 2026-06-21T13:18:00.000Z

All tests pass. Final state: two consecutive clean 8-round parallel sweeps, 73/73 in every round.

**Iterations run:** 2 fix-and-sweep iterations (plus a confirmation sweep).

**Baseline failures (union across 8 rounds):**
- `test_occ_stale_subscription_request_cancel` — deterministic, 8/8: expected `ERR_STALE_VERSION`, got `ERR_INVALID_STATE`.
- `test_refund_pursuit_price_drop_lookback`, `test_success_fee_low_tier_rate`, `test_success_fee_tier_then_round_then_cap_order`, `test_dual_variant_negotiation_vs_refund_fee_basis` (test_03) — intermittent "API server could not be restarted" setup errors (server boot flakiness under 8 concurrent reboot-per-test rounds), not logic failures.

**Tests deleted:** none.

**Fixes applied to test_suite/** (`test_06_savings_sweep_and_concurrency.py`, `test_occ_stale_subscription_request_cancel`):
- TEST BUG (STEP 2). Original scenario left subscription in `CANCEL_REQUESTED` — a disallowed source state for request-cancel — so per PRD §2.9 the `ERR_INVALID_STATE` state check correctly fires before the OCC staleness check. Implementation was PRD-faithful. Rewrote test to use `setup_cancel_failed_subscription`, driving subscription to `CANCEL_FAILED` (allowed source) with bumped version (matches PRD §2.7). Now the state check passes and stale-version OCC fires → `ERR_STALE_VERSION`. Updated import. No assertion weakened.

**Fixes applied to implementation/** (`app.py`, `__main__` entry point):
- Silenced Werkzeug access log + suppressed dev-server banner + set `use_reloader=False` to reduce per-boot overhead under parallel reboot-per-test sweep, eliminating intermittent "could not be restarted" setup failures in test_03. No endpoints/fields/side-effects/behavior changed — logging/startup only.

Note: transient regression caught and reverted (WERKZEUG_RUN_MAIN=true caused boot crash). Final fix touches only logger level and banner. No state seeding; storage remains in-memory dicts wiped on each start.sh re-invocation.

## Step 8: Finalize PRD — 2026-06-21T13:22:00.000Z

PRD_FINALIZED.md produced as a verbatim copy of PRD.md. No edits warranted (264 → 264 lines, 0% delta).

Rationale: (1) the test_06 OCC fix was a pure test-fixture bug — the state-vs-OCC ordering it exercised is already pinned verbatim by PRD §2.9 (verified app.py:615-621), implementation already PRD-faithful; (2) the app.py logging/startup change is non-behavioral infra noise reduction. Neither reveals PRD silence or mismatch.

Pre-edit search log: subject = request-cancel validation ordering; enumerated app.py:607-639 (request/confirm/fail cancel), app.py:997-1018 (dispute_claim parallel OCC pattern); no wording adjustment needed. The one under-determined choice nearby (OCC-before-member-suspension at app.py:620 vs 622) was never exercised by any step_7 diff item → out of HARD SCOPE, left untouched.

## Step 9: Complete PRD — 2026-06-21T13:25:00.000Z

Produced PRD_COMPLETED.md as a minimal inline patch over PRD_FINALIZED.md via full PRD-vs-implementation scan.

**Counts:** source PRD_FINALIZED.md 264 lines / 37,921 chars → PRD_COMPLETED.md 264 lines / 42,932 chars (+5,011 chars; all in-paragraph/in-cell, no line-count or section change). Ambiguity-pins: 16. Mismatch-revisions: 1.

**Mismatch (1):** §2.1 — `Anonymous` (and any unrecognized/missing role) on a protected endpoint yields `ERR_UNAUTHENTICATED`, not `ERR_FORBIDDEN_ROLE`; only Member/ConciergeAgent/PlatformAdmin are header-recognized (middleware.py:6,18).

**Ambiguity-pins (16):** single-GET owner checks (member-owned resources enforce owner; `GET /members/{id}` exempt); list sort tiebreak ascending `id` + Member list reads scoped to caller; §2.9 propose/counter/accept/approve put `ERR_INVALID_STATE` before numeric/ceiling checks; clock-set no-auth/verbatim-store/200; duplicate email → `ERR_INVALID_REQUEST`; PATCH savings_account_id FK/owner errors; charge ingestion FK-before-ownership + PlatformAdmin any-account; request-cancel guard order state→stale→suspended; subscription-create trial-required after range + charge-confirmed; open-case guard order charge-confirmed→capacity→suspended; savings-report response field shape; Member own-report-only; dispute guard order state→cap→stale→suspended; reverse uses member's current savings_account_id; §4 table list query filters for 5 collections.

Tests used only as auxiliary cross-reference (did not pin report fields, duplicate-email error, or Anonymous behavior — consistent with Step 7 weakening).

---

## Pipeline complete — 2026-06-21T13:25:00.000Z

All 9 steps done. Final state: 73/73 tests passing across two consecutive clean 8-round parallel sweeps (per-test-server isolation). Final contract: `workspace/PRD_COMPLETED.md`. Expert difficulty band; 0 tests deleted.
