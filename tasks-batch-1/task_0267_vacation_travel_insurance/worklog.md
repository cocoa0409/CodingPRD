# Worklog — task_0267_vacation_travel_insurance

## Step 1: Create task directory — 2026-06-09T12:50:38.000Z

Created `tasks/task_0267_vacation_travel_insurance/` with `workspace/` subdirectory (pre-allocated index 0267, no auto-increment). Verified `INSTRUCTION.md` exists at project root.

## Step 2: Generate scaffold (Expert) — 2026-06-09T13:14:00.000Z

All checks pass. The scaffold is complete and self-consistent.

Generated three scaffold artifacts for **task_0267_vacation_travel_insurance** at **Expert** difficulty. All files parse cleanly and `scaffold_lint.py` returns `VERDICT: clean lint` (411 calls scanned, all FK reverse-reachability satisfied).

**Files written:** SCAFFOLD.yaml (§1.0–§1.7), SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8, single key), SCAFFOLD_CORNER_DESIGN.yaml (§1.9, single key).

**Complexity profile:** Ledger-reconciliation × Compliance/audit; flat topology (empty `api_prefix`, peer collections by FK); parallel state-machine shape; peer_roles; immediate consistency. Layers: dual-variant calc, cascading side effects, rate/threshold triggers, optimistic concurrency, temporal windowing.

**Scaffold contents:**
- **Entities (10):** Plan, Traveler, Policy, InsuredTraveler, NamedStorm, Claim, ClaimExpense, ClaimDocument, Payout, Refund
- **State machines (5):** Policy (parallel `payment_status` × `coverage_status`), Claim (cyclic UNDER_REVIEW↔INFO_REQUESTED), Payout (with compensating reverse), Refund (with void), NamedStorm
- **Calculations (8):** premium_quote (tiered + senior + CFAR loadings), cancellation_reimbursement (provisional vs final dual-variant), premium_refund (free-look full vs short-rate dual-variant), delay_reimbursement (12h-block threshold), baggage_reimbursement (round-per-item-then-sum), medical_reimbursement, preexisting_waiver_eligibility, aggregate_limit_pin
- **Validations:** 16 priority-ordered rows; **1 concurrency rule** (OCC `expected_policy_version` on record-payment)
- **Endpoints:** 43 (includes `/_clock/set_current_utc` test-driving endpoint and FK reverse-reachability GETs)
- **Error catalog:** 26 codes
- **Roles (6):** CarrierAdmin (opaque), Underwriter (opaque), ClaimsAdjuster (opaque), Traveler (entity_backed:Traveler), System (opaque), Any

**Difficulty design (§1.8):** 18 instances = 9 rules × 2 each. **Corner design (§1.9):** 37 instances (29 active + 8 `excluded_because` stubs pointing at §1.8 instances).

**Key design decisions verified:** All formula-derived asserts pre-computed as literals (premium 57000, cancellation provisional 350000 / final 300000 / CFAR 225000, baggage 1876 with per-item-vs-sum rounding divergence 1876≠1875, short-rate refunds 31700/14166, net-premium 5834, aggregate-exhaust at 300000, invariant restore to 1200000). OCC version inputs capture `Policy.version` via `GET /policies/{id}` and reference as `${...}`. Filing-window one-sided (lateness deadline only). Free-look refunds auto-complete; short-rate refunds stay PENDING for underwriter completion.

## Step 3: Copy INSTRUCTION.md — 2026-06-09T13:15:27.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0267_vacation_travel_insurance/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-09T13:22:47.000Z

PRD generation complete. The document is written to `workspace/PRD.md` (273 lines).

**Sections written:**
- §1 Introduction — framing around ledger conservation + compliance fidelity.
- §2 Global Specifications — 10 subsections: RBAC (6 roles, Traveler entity_backed), response envelope, pagination, common properties (ClaimDocument the only common_fields:false entity), nested/FK left-to-right validation, precision/rounding, ledger conservation & cascades, parallel policy state + cyclic claim, OCC, validation ordering.
- §3 Business Logic — 8 subsections by lifecycle: catalogue setup & clock, quoting & roster + premium formula, settlement & issuance + aggregate-pin & waiver, claim filing & record assembly + provisional calc, cancellation/expiration + both refund variants, adjudication + all four reimbursement calcs, the two temporal guards, payouts/exhaustion/reversal.
- §4 Endpoint table — all 43 endpoints.
- §5 Error catalogue — all 26 error IDs.

**Hard contract results:** Contract 1 (Field-Name Coverage) PASS 72/72; Contract 2 (Rule Coverage) PASS; Contract 3 (§3 Path Purity) PASS (457 backticked tokens, 0 paths/methods).

**Scaffold ambiguities resolved:** (1) OCC field rendered as single mandatory `expected_policy_version` on record-payment, no other endpoint takes a version field. (2) Per-calculation rounding directions stated explicitly (ceil for premium terms, floor for cancellation/short-rate/aggregate-pin, half-up for baggage depreciation; baggage per-item-before-sum ordering pinned). (3) Multiple sibling Claim→DENIED system transitions consolidated into one auto-deny cascade (denial_reason = AGGREGATE_EXHAUSTED) from SUBMITTED/UNDER_REVIEW/INFO_REQUESTED.

## Step 5: Generate unit tests — 2026-06-09T13:48:50.000Z

Generated complete test infrastructure for **task_0267_vacation_travel_insurance** (Expert tier, vacation/travel insurance ledger-reconciliation domain).

**Stage 1 — `test_helpers/` (9 files):** types.py (13 status/enum types + 10 entity TypedDicts; ClaimDocument append-only with id+created_at only); api_client.py (one method per PRD §4 endpoint); api_errors.py (all 26 error IDs with HTTP status map); assertions.py (per-entity + assert_policy_aggregate_invariants ledger conservation); factories.py (input-field-only, optional fields via overrides only so required-field tests delete cleanly); constants.py / test_users.py (Traveler entity_backed → make_traveler_headers threads real owner id, no shared constant) / fixtures.py (composite preambles setup_active_policy, setup_paid_quoted_policy, setup_claim_under_review, setup_approved_cancellation_claim_with_pending_payout) / __init__.py.

**Stage 2 — `test_suite/` (8 test files + conftest, 63 tests):**
- Queue A (Difficulty): 17 of 18 instances covered, exactly 2 tests each = 34 tests.
- Queue B (Corner): all 29 non-stub instances covered (≥1 each) = 29 tests. All 8 excluded_because stubs correctly NOT translated.
- One Design tag per test; 0 untagged/dual-tagged; all 63 tags resolve to real instances.

**Instance skipped (1):** Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_cancelled_policy_past_filing_window — SKIPPED (validation-priority silence). PRD §2.10 covers auth→existence→ownership→well-formedness→state→OCC and approval-path "safety before fiscal", but does NOT pin precedence between active-policy gate and filing-window gate at *submission*; §3.4 mentions both without ordering. Fails unique-derivability. Sibling named_storm_cutoff_beats_aggregate_fiscal_on_approve (approval path) IS covered.

**Validation performed:** all 18 files compile; test_helpers imports cleanly against real framework; all 63 tests collect with zero errors. Verbatim PRD-citation pass: 92 quoted spans confirmed against PRD.md (corrected for backticks + markdown emphasis).

## Step 6: Generate implementation — 2026-06-09T13:48:50.000Z

Built complete Python + Flask implementation in `workspace/implementation/`.

**Files created (23):** start.sh (foreground, $PORT/0.0.0.0, guarded pip install, exec), requirements.txt, app.py (blueprint registration + global error handlers); foundation db.py (in-memory dicts + logical clock, starts empty, no seeding), errors.py, response.py, middleware.py (auth/RBAC); routes/ (clock, plans, travelers, named_storms, policies, claims, payouts, refunds); services/ (common, calc all 7 calculations, serialize, store_helpers, policy_ops, claim_ops, payout_ops).

**Endpoints:** all 43 from PRD implemented.

**Key logic:** parallel Policy state (payment_status × coverage_status); cyclic Claim state machine (UNDER_REVIEW ⇄ INFO_REQUESTED); ledger conservation (amount_reimbursed_cents/remaining_aggregate_cents/net_premium_collected_cents recomputed synchronously, version bump + updated_at on cascade-touched resources); cascades (disburse → policy debit → claim PAID → EXHAUSTED → auto-deny open siblings AGGREGATE_EXHAUSTED; reversal compensation restoring aggregate + EXHAUSTED→ACTIVE, PAID→APPROVED; free-look cancel → COMPLETED refund → REFUNDED → insured REMOVED). Calculations with exact rounding per §2.6 (premium ceil per term; aggregate-pin floor; cancellation provisional/final + CFAR floor; medical; delay block-based; baggage per-item half-up depreciation then per-item sublimit then sum; short-rate floor minus 2500c admin fee; preexisting-waiver floor days). Decimal/ROUND_HALF_UP only for baggage. Validation ordering per §2.10; OCC on record-payment via expected_policy_version → ERR_STALE_VERSION 412. ClaimDocument append-only.

**PRD ambiguities noted by impl-gen:** (1) Delay-event overlap window anchoring (anchored at incident_at, DELAY_MERGE_BUFFER_HOURS=6). (2) Medical/baggage provisional basis (medical provisional uses documented amounts ignoring supplier refunds; baggage/delay provisional = final formula). (3) record-payment ownership for non-owner Traveler returns ERR_NOT_RESOURCE_OWNER before OCC/state checks per §2.10 priority-4.

## Step 7: Test/fix iteration loop — 2026-06-09T13:54:18.000Z

All 8 parallel rounds pass 63/63. Clean sweep.

**Iterations run:** 2 (baseline sweep + 1 fix sweep).

**Tests deleted:** None. The single failing test was PRD-faithful and uniquely derivable.

**Fixes applied to test_helpers/:** None.

**Fixes applied to implementation/:**
- `workspace/implementation/services/claim_ops.py` — `enforce_delay_event_overlap()`: changed the delay-event de-duplication guard from comparing bare **incident timestamps** to comparing the **covered delay windows** as closed intervals `[incident_at, incident_at + delay_hours]` extended by the 6-hour merge buffer. The old code only merged claims whose incident *points* were within 6h of each other, so a second claim with incident 15h after the first (but whose delay window started only 3h after the first window ended) escaped the guard.
- `workspace/implementation/routes/claims.py` — `create_claim()`: updated the call site to pass `delay_hours` into the guard.

**Root cause / key finding:** PRD §3.7 states the delay-event comparison is over "the covered delay window ... a closed interval extended by the six-hour merge buffer." The implementation degenerated this to a point-to-point incident comparison, which let `test_second_delay_claim_within_buffer_rejected` slip through. The fix uses proper interval-overlap-with-buffer logic and continues to accept the distant-claim case (15 days apart). Failure was deterministic and identical across all 8 baseline rounds (no flakiness). All 8 final rounds: passed=63 total=63.

## Step 8: Finalize PRD — 2026-06-09T13:57:24.000Z

Produced `workspace/PRD_FINALIZED.md`.

**Line counts:** PRD.md = 273 lines, PRD_FINALIZED.md = 273 lines (0.0% line-count delta; one line revised in place, prose expanded).

**Changes (one bullet per change):**
- §3.7 (delay-event guard) — revise — Pinned the previously under-determined "covered delay window" and merge condition: defined the window as the closed interval `[incident_at, incident_at + delay_hours]`, specified the exact overlap-with-buffer condition (windows touch/overlap after each is extended by 6h; equivalently gap ≤ 6h merges, gap > 6h is allowed), and noted existing DELAY claims are considered regardless of status — `implementation/services/claim_ops.py:50-77` (call site `routes/claims.py:90-91`).

**Per-edit pre-edit search log:**
- Edit 1 — §3.7 delay-event guard. (a) Subject: the delay-event de-duplication guard — definition of "covered delay window" and precise merge/overlap condition with the 6-hour buffer. (b) Impl paths enumerated: `services/claim_ops.py:50-77` (enforce_delay_event_overlap — window `[incident_at, incident_at+delay_hours]`, condition `new_start <= existing_end+buffer AND existing_start <= new_end+buffer`, loop filters same policy_id + peril==DELAY, no status filter); `routes/claims.py:43-46,73-75,90-91` (guard invoked only on DELAY filing, passes incident_at + delay_hours); `services/calc.py:15-16` (DELAY_MERGE_BUFFER_HOURS=6, MIN_DELAY_HOURS=12); `calc.py:149-150` + `claim_ops.py:25,94` (delay_hours used for block computation and ≥12h gate, not window — no conflict); `serialize.py:36` (delay_hours/incident_at output fields). Whole-impl grep confirmed no other path defines a delay window. (c) Wording adjustment: widened to "regardless of current status" (impl loop has no status filter); buffer phrased symmetrically on both intervals; gap boundary stated explicitly for inclusive touch-or-overlap semantics.

No other Step 7 diff items required PRD edits (call-site change was internal plumbing; no test deletions/test_helper fixes).

## Step 9: Complete PRD — 2026-06-09T14:03:50.000Z

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-implementation scan.

**Source vs completed:** PRD_FINALIZED.md 273 lines / 45,837 chars → PRD_COMPLETED.md 273 lines / 47,602 chars (char delta +1,765; all in-paragraph inserts, no new sections).

**Counts:** 6 ambiguity-pins, 0 mismatch-revisions. (Impl already matched every uniquely-pinned PRD behavior; only gaps were silences.)

**Changes:**
- §2.1 (RBAC) — insert — ambiguity — Defined "malformed" header precisely (empty/whitespace X-User-ID; X-User-Role not among the six names) and pinned that System/Any are well-formed role values at auth, never ERR_MISSING_AUTH — `middleware.py:8-28`
- §3.1 (Plans) — insert — ambiguity — Plan retirement admissible only from ACTIVE, else ERR_INVALID_STATE — `routes/plans.py:95-96`
- §3.1 (Named storms) — insert — ambiguity — Storm dissipation admissible only from ACTIVE, else ERR_INVALID_STATE — `routes/named_storms.py:66-67`
- §3.4 (Filing a claim) — insert — ambiguity — insured_traveler_id must belong to the same policy; mismatch → ERR_NOT_FOUND — `routes/claims.py:59-60`
- §3.4 (Provisional amount) — insert — ambiguity — Per-peril provisional_amount_cents basis for MEDICAL (sum documented, capped at medical_limit/remaining), DELAY and BAGGAGE (= §3.6 final figure), zero otherwise — `services/claim_ops.py:14-28`, `services/calc.py:127-174`
- §3.6 (Deny) — insert — ambiguity — denial_reason required non-empty string; absence → ERR_INVALID_REQUEST — `routes/claims.py:262`

**Left unchanged (verified consistent):** list ordering by created_at asc (insertion tiebreaker below ms granularity); issuance precondition ordering; refund-complete ERR_INVALID_STATE when REFUNDED; free-look/short-rate cascades; exhaustion auto-deny; reversal compensation; expected_policy_version negative rejection; add_insured path-vs-body FK interleaving.

---

**Pipeline complete.** All 9 steps finished. Final state: 63/63 tests pass across 8 parallel rounds; PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md produced.
