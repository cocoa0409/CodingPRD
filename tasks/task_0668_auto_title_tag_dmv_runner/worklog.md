# Worklog — task_0668_auto_title_tag_dmv_runner

## Step 1: Create Task Directory — 2026-06-26T18:18:32.000Z

Task directory `tasks/task_0668_auto_title_tag_dmv_runner/` and its `workspace/` subdir already existed (pre-created by the parallel-run harness). Per execution directives, the Step 1 directory-scan was SKIPPED; the folder is used verbatim as {task_dir}. No index computed, no rename.

## Step 2: Generate Scaffold — 2026-06-26T18:44:22.000Z

Generated all three scaffold artifacts for **task_0668_auto_title_tag_dmv_runner** at **Expert** difficulty, written to `tasks/task_0668_auto_title_tag_dmv_runner/`. `scaffold_lint.py` reports **clean lint** (46 endpoints, 10 entities, 500 calls scanned across §1.8+§1.9).

**Complexity profile:** Primary archetype `workflow_orchestration` + secondary `pricing_engine`; layers dual-variant calc, cascading side-effects, rate/threshold triggers, optimistic concurrency, derived-field reconciliation. Topology **flat** (FK-linked peers), state-machine shape **cyclic** (rework loop + parallel dimensions + fork-join), role model **peer_roles** with segregation of duties.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **10 entities:** Account, FeeSchedule, Transaction, DocumentItem, FeeQuote, Submission, RunnerTrip, RunnerLeg, LienPacket, Payment (Payment is `common_fields:false`).
- **6 state machines:** Transaction lifecycle (cyclic rework REJECTED↔SUBMITTED + branches), Transaction document_status (parallel dimension), DocumentItem, RunnerTrip (fork-join dispatch/close), Submission, LienPacket. Plus **2 concurrency rules** (OCC: leg-attach-stale-trip on RunnerTrip, quote-supersede-stale-transaction on Transaction).
- **4 calculations:** `fee_quote_estimate` and `fee_quote_final` (dual-variant, diverge on schedule re-pin), `fleet_volume_discount` (threshold tiers at 625/1250/1875 bps with sum-then-round order pinned), `account_balance` (aggregation, postpaid vs prepaid variants).
- **17 validations** (priority-ordered, auth→existence→ownership→state→safety→referential→constraint→temporal→fiscal→OCC).
- **46 endpoints** (incl. `/dmv/_clock/set_current_utc` with default 2026-04-01T00:00:00Z, `/dmv/_fee-periods/advance`, and 2 last-resort test-driving injectors for counters/rejection_round).
- **19 error codes.**
- **6 roles:** PlatformAdmin, IntakeClerk, FeeAnalyst, RunnerDispatcher, LienOfficer (all `opaque`), AccountHolder (`entity_backed:Account`).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** **18 instances** — exactly 2 per each of the 9 Difficulty Rules, all grounds resolving, all formula-derived asserts pre-computed to literals (e.g. fee totals 68500/76000/106250, service-fee rounding-order trap 11375-not-11376, SLA deadline 2026-04-03T00:00:00Z).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **42 instances** (35 active + 7 `excluded_because:` stubs) across all 9 claim-extraction sections.

All 60 instance names are unique across both files; no forbidden concurrency vocabulary; neither design key leaks into SCAFFOLD.yaml. Lint clean.

## Step 3: Copy Shared Files — 2026-06-26T18:44:22.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0668_auto_title_tag_dmv_runner/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-26T18:50:03.000Z

Generated `workspace/PRD.md` from SCAFFOLD.yaml (~275 lines, ~6,600 words).

**Structure:**
- §1 Introduction (3 paragraphs, business-context angle)
- §2 Global Specifications — 9 subsections: Access Control (all 6 roles, opaque/entity_backed), fixed §2.2 envelope, Pagination, Common Properties + Logical Clock (Payment is the `common_fields:false` entity), Hierarchical Consistency/Derived Fields/OCC, Nested Retrieval + Validation Ordering, Money/Precision/Rounding, Transaction's dual status dimensions, Enumerations.
- §3 Business Logic — 9 subsections (config backbone, intake+documents, pricing, submission+runner queue+DMV decisions, fee composition, fleet discount, completion+reconciliation, lien perfection, cancellation/reversals).
- §4 Endpoint table (4 cols, all 46 endpoints).
- §5 Error catalogue (2 cols, all 19 error IDs).

**Hard Contracts — all PASS:** Contract 1 (61 field/param names, 0 missing); Contract 2 (both OCC rules, all transitions, dual estimate/final calc, fleet discount, cascades, validation priority, all 19 errors); Contract 3 (§3 Path Purity — 0 path/method tokens in 399 backtick tokens).

**Confirmation:** Did NOT read SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml.

## Step 7: Run Tests and Iterate — 2026-06-26T19:58:00.000Z

Summary

- Iterations run: 2 (initial sweep surfaced 4 distinct deterministic failures across all 8 rounds; second sweep after fixes passed 8/8 at 59/59).

Tests deleted (PRD-silence / unique-derivability category):
- `test_complete_settles_quote_balance_then_suspends_account` (test_04_cascades.py) — UNIQUE-DERIVABILITY / contradictory-sentence collapse. PRD §3.7 says "If completing... would push its `outstanding_balance_cents` above its `credit_limit_cents`, the completion is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 409); otherwise, should the recomputed balance exceed the credit limit, the account's `status` is set to `SUSPENDED`." The two clauses cover the identical numeric condition (balance > limit), so the "otherwise→SUSPENDED" branch is unreachable under the controlling "reject 409" clause. The test demanded the over-limit completion succeed (200) and suspend, an outcome the cited sentence does not uniquely determine and its primary clause contradicts. Driven by scaffold rule Difficulty/transitive_cascade/complete_settles_quote_then_balance_then_suspends_account_depth3.
- `test_complete_balance_crosses_limit_sets_suspended` (test_04_cascades.py) — same contradictory-sentence collapse, same PRD §3.7 sentence, same scaffold rule. Deleting these preserves the PRD-required §3.7 clause-1 `ERR_CREDIT_LIMIT_EXCEEDED` check rather than weakening it.

Fixes applied to `test_suite/`:
- test_06_cross_entity_and_temporal.py, `test_expedite_sla_window_open_upper_bound_at_deadline_rejected` — STEP 1c partial-coverage split. Relaxed the `sla_deadline_at == "2026-04-03T00:00:00Z"` exact-string assertion to a parsed-instant comparison. PRD §3.4 pins the deadline instant (clock +48h) and the `ERR_SLA_EXPIRED` behavior, but is silent on the fractional-digit format of `sla_deadline_at` (three digits are stated only for `api_request_timestamp` and `created_at`), so the exact-string form was not uniquely derivable. The load-bearing `ERR_SLA_EXPIRED` assertion is retained unchanged.

Fixes applied to `implementation/`:
- routes/transactions.py, `quote_transaction` — broadened the state-eligibility gate from `{DRAFT, QUOTED}` to `{DRAFT, QUOTED, REJECTED}`. PRD §3.4 requires that rework-resubmit have "a re-run quote reflecting the current `rejection_round` surcharge" which can only be produced while `lifecycle_status` is `REJECTED`; the prior code's rejection ("transaction must be DRAFT or QUOTED to quote") made the rework precondition unsatisfiable. The endpoint still advances only DRAFT→QUOTED and leaves REJECTED/QUOTED lifecycle unchanged, so the rework submit path (keyed on REJECTED) is preserved.

No `test_helpers/` changes were needed.

(Orchestrator note: independently re-ran the 8-round parallel sweep in the foreground after Step 7 returned; confirmed 8/8 rounds at 59/59 passed/total, results.1..8.json persisted on disk.)

## Step 8: Finalize PRD — 2026-06-26T20:00:30.000Z

NOT skipped (Step 7 had 2 deletions + 1 test_suite fix + 1 implementation fix). Produced `workspace/PRD_FINALIZED.md`.

Summary

- PRD.md vs PRD_FINALIZED.md: 275 lines → 275 lines (0.0% line-count delta; both edits are inline within existing paragraphs, no lines added/removed).

Changes:
- §3.3 — revise — Added that the analyst may also recompute an estimate from a `REJECTED` transaction (the rework re-quote), leaving the lifecycle at `REJECTED`, and stated quote eligibility is `{DRAFT, QUOTED, REJECTED}`; reworded "Either way" → "In each case" so the OCC clause covers all three states — `implementation/routes/transactions.py:127` (eligibility gate `{DRAFT, QUOTED, REJECTED}`) and `:158-159` (only DRAFT→QUOTED advances; QUOTED/REJECTED stay).
- §3.4 — revise — Pinned that an expedited `sla_deadline_at` is rendered as an ISO 8601 UTC timestamp with three fractional digits (same format as `created_at`); standard-submission null clause kept verbatim — `implementation/routes/transactions.py:231` (`format_iso8601_ms(...)`), `implementation/clock.py:49-52` (three-digit format), echoed verbatim by `serializers.py:99`.

Per-edit pre-edit search log:
- Edit 1 (§3.3 quote eligibility/lifecycle):
  - (a) Subject: the quote endpoint's state-eligibility set and its lifecycle effect.
  - (b) Paths enumerated/read: `quote_transaction` (transactions.py:120-161) — gate `{DRAFT,QUOTED,REJECTED}` (127), transition only DRAFT→QUOTED (158-159), QUOTED/REJECTED unchanged; grepped all `lifecycle_status` writes (no other estimate-quote callsite; FINAL quotes minted only in `complete_transaction`); `submit_transaction` rework precondition (196-242) keyed on REJECTED + VERIFIED + active_quote + round<3, unaffected by quoting from REJECTED; `verify_documents` touches only `document_status`; OCC/schedule/supersede applied uniformly to all three states (132-160).
  - (c) Adjustment: reworded "Either way" → "In each case" so the OCC requirement still spans the now-three-state set; placed the REJECTED clause in parallel structure so the schedule/supersede sentences that follow continue to apply to it.
- Edit 2 (§3.4 sla_deadline_at format):
  - (a) Subject: representation/format of the server-minted `sla_deadline_at`.
  - (b) Paths enumerated/read: production `transactions.py:231` (expedite) and `:234` (`None` for standard); storage `repo.py:124` (verbatim); serialization `serializers.py:99` (verbatim); consumption `runner_trips.py:99-103` (`parse_iso8601` round-trips the three-digit form); `format_iso8601_ms` `clock.py:49-52` vs `now_ts` `db.py:50` (identical three-digit emitters); confirmed `window_start_at`/`window_end_at` are echoed raw from client input (not server-minted), so format claim must not extend to them.
  - (c) Adjustment: scoped the three-digit claim strictly to `sla_deadline_at` (not to client-supplied trip windows) and preserved the existing "standard submission → null" clause so the format applies only to the non-null expedited value.

Items 1 & 2 (deleted §3.7 over-limit-completion tests): no PRD edit. The §3.7 sentence's clause 1 ("rejected with `ERR_CREDIT_LIMIT_EXCEEDED`") already matches the implementation's reject behavior (transactions.py:294-297), and the unconditional post-recompute SUSPENDED set (transactions.py:314-316) matches the "otherwise→SUSPENDED" clause; the deleted tests demanded an over-limit completion *succeed and suspend*, an outcome the existing prose does not determine and its clause 1 contradicts — so the PRD prose is already behaviorally accurate and editing would risk a new mismatch.

## Step 9: Complete PRD — 2026-06-26T20:06:30.000Z

Produced `workspace/PRD_COMPLETED.md` (started from PRD_FINALIZED.md). Full PRD-vs-implementation scan.

Summary

- Source `PRD_FINALIZED.md`: 275 lines, 46,763 chars. `PRD_COMPLETED.md`: 275 lines, 49,883 chars. Char delta +3,120; line delta 0 (all changes in-paragraph).
- Counts: ambiguity-pins = 12; mismatch-revisions = 1. (13 changed paragraphs total.)

- §2.4 Logical Clock — insert — ambiguity — pinned that the logical clock governs only SLA-style domain computations; `created_at`/`updated_at`/`api_request_timestamp` use real wall-clock UTC and are unaffected by clock-setting — db.py:48-50, clock.py:18-22, response.py:21-23, repo.py:25-28 vs transactions.py:231.
- §3.1 Accounts — revise+insert — ambiguity — account `state_code` must match a currently `ACTIVE` schedule (not merely "existing"), rejected with `ERR_INVALID_REQUEST` 400 — routes/accounts.py:31-35 (via domain.py:34-39).
- §3.1 Accounts — insert — ambiguity — negative `credit_limit_cents` → `ERR_VALIDATION` 422 — routes/accounts.py:28-29.
- §3.1 Fee Schedules — insert — ambiguity — negative `use_tax_rate_bps` → `ERR_VALIDATION` 422 — routes/fee_schedules.py:30-31.
- §3.1 Test-driving injects — insert — ambiguity — negative target → `ERR_VALIDATION` 422; missing `account_id`/`transaction_id` → `ERR_NOT_FOUND` 404 — routes/config.py:54-59, 72-76.
- §3.2 Transaction creation — insert — ambiguity — negative `trade_in_allowance_cents` → `ERR_VALIDATION` 422, checked after the exceed-declared-price rule — routes/transactions.py:91-96.
- §3.2 Document decision — revise+insert — ambiguity — `decision` literal tokens `VERIFIED`/`REJECTED`/`RESET` (else `ERR_INVALID_REQUEST` 400); per-decision source-state machine (verify/reject from `PENDING`, reset from `REJECTED`, else `ERR_INVALID_STATE` 409) — routes/documents.py:53, 74-85.
- §3.2 Verify-documents — insert — ambiguity — checklist evaluation allowed only from `COLLECTING`/`INCOMPLETE`; evaluating an already-`VERIFIED` transaction → `ERR_INVALID_STATE` 409 — routes/transactions.py:175-178.
- §3.3 Quote — insert — ambiguity — missing `ACTIVE` fee schedule → `ERR_INVALID_STATE` 409 — routes/transactions.py:143-144.
- §3.4 Submit — revise+insert — ambiguity — lifecycle precondition is `QUOTED` or `REJECTED`; `document_status`≠`VERIFIED` or null `active_quote_id` → `ERR_DOCUMENTS_INCOMPLETE` 409, while non-`ACTIVE` account → `ERR_INVALID_STATE` 409 — routes/transactions.py:196-217.
- §3.4 DMV decision — revise — ambiguity — `outcome` literal tokens `ACCEPTED`/`DMV_REJECTED` (else `ERR_INVALID_REQUEST` 400) — routes/submissions.py:57.
- §3.5 State fees / lien-in-play — revise+insert — ambiguity — lien recording fee applies for any associated packet whose `packet_status` ≠ `VOIDED` (`DRAFT`/`PERFECTED` count; `VOIDED` does not) — domain.py:61-73.
- §3.7 Completion — insert — ambiguity — `LIEN` without a `PERFECTED` packet → `ERR_INVALID_STATE` 409; missing `ACTIVE` schedule at completion → `ERR_INVALID_STATE` 409 — routes/transactions.py:259-267.
- §3.7 Payments — revise — mismatch — removed the false "kind invalid for the account's terms → `ERR_PAYMENT_AMOUNT_MISMATCH`" rule (impl accepts either kind regardless of terms); pinned `amount<1`→`ERR_VALIDATION` 422 ahead of the COMPLETED/settled-total checks (those → `ERR_PAYMENT_AMOUNT_MISMATCH` 422); pinned that a payment never auto-reactivates a `SUSPENDED` account (only admin reinstate does) — routes/accounts.py:78, 90-103, 109-114.
