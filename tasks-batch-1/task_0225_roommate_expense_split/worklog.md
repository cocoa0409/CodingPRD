# Worklog — task_0225_roommate_expense_split

Scenario: Roommate Matching & Shared Expense Splitting: roommate profile/preferences, room listing, compatibility matching, shared-bill split (rent/utilities), expense ledger & settle-up, payment reminders, move-in/out proration, dispute log

Difficulty: Expert

## Step 1: Create task directory — 2026-06-07T11:37:49.000Z

Created `tasks/task_0225_roommate_expense_split/` and `tasks/task_0225_roommate_expense_split/workspace/` (task_dir supplied by user; Step 1 index scan skipped to avoid ID contention with parallel tasks).

## Step 2: Generate scaffold — 2026-06-07T12:24:08.000Z

Generated all three scaffold artifacts for **task_0225_roommate_expense_split** (Expert difficulty), validated by `scaffold_lint.py` → **VERDICT: clean lint**.

**Files written**:
- `SCAFFOLD.yaml` (§1.0–§1.7, no design keys) — 1572 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`) — 1477 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`) — 1754 lines

**Complexity profile**: primary archetype *ledger reconciliation* + secondary *multi-party negotiation*; `entity_topology: graph`, `state_machine_shape: parallel`, `role_model: peer_roles`; layers: optimistic concurrency, dual-variant calculation, cascading side effects, derived-field reconciliation, selector policy.

**Counts**:
- **Entities**: 12 — RoommateProfile, RoomListing, MatchRequest, Household, Membership, Bill, BillSplit, Expense, ExpenseShare, Settlement, PaymentReminder, Dispute
- **State machines**: 5 — MatchRequest (cyclic withdraw/reapply), Membership (linear+cascade), Bill (parallel payment_status × reminder_status), Settlement (cyclic dispute/repropose), Dispute (cyclic reopen)
- **Calculations**: 4 — compatibility_score (weighted, STRICT/LENIENT variants), bill_split (waterfall, floor+remainder-by-created_at), move_proration (estimate vs final dual-variant), household_net_balance (aggregation, ledger-sum-zero invariant)
- **Validations**: 21 (priority-ordered)
- **Endpoints**: 54 (includes profile sub-resource GETs and `/_clock/set`, `/_reminders/dispatch` test-driving endpoints)
- **Error catalog**: 22 codes
- **Roles**: 3 — Roommate (`entity_backed:RoommateProfile`), DisputeMediator (`opaque`), PlatformOperator (`opaque`)
- **Concurrency rules**: 1 — OCC on `Household.version` for settlement confirm (ERR_STALE_HOUSEHOLD_VERSION, 412)

**Difficulty design (§1.8)**: 9 rules × 2 instances = **18 instances**, each with executable setup/trigger/assert chains; formula-derived asserts pre-computed to literals.

**Corner design (§1.9)**: 9 sections, **37 instances** (32 with full test_recipes + 5 `excluded_because` stubs).

**Key modeling decisions**: `api_prefix: ""`; lister/manager modeled as non-member third party; occupancy overlap = single-occupancy (capacity-1) half-open interval check ordered before capacity gate; `split_policy` snapshotted RoomListing → Household at accept-time (no `POST /households`).

## Step 3: Copy shared files — 2026-06-07T12:24:08.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-07T12:31:23.000Z

Generated `workspace/PRD.md` (272 lines, 43202 bytes) for the `roommate-expense-split` domain.

**Major sections**: §1 Introduction; §2 Global Specifications (11 subsections — RBAC for all 3 roles, response envelope, pagination, common props with `BillSplit`/`ExpenseShare` flagged id+created_at only, nested-retrieval/existence ordering, conservation/net-balance invariant, floor-then-remainder money rules, cascade propagation, FROZEN ledger gate, settlement-confirm OCC via `expected_household_version`→`ERR_STALE_HOUSEHOLD_VERSION`/412, validation priority ordering); §3 Business Logic (9 scattered subsections — profiles/listings/compatibility STRICT+LENIENT, match-request lifecycle, membership activation occupancy-then-capacity gate, bills/splitting/payment, move-out proration+redistribution cascade, expenses/void, settle-up, reminders/clock dispatch, dispute adjudication+freeze cascade); §4 Endpoint table (55 endpoints); §5 Error catalogue (22 IDs).

**Hard Contracts**: Contract 1 Field-Name Coverage (65 names) PASS; Contract 2 Rule Coverage (22 error IDs, 36 state/enum values, OCC/calcs/cascades/orderings) PASS; Contract 3 §3 Path Purity (359 tokens, 0 leaks) PASS.

**Confirmation**: did NOT read either design YAML.

## Steps 5 & 6: Generate unit tests + implementation — (recorded retroactively at resume)

Worklog entries for Steps 5 and 6 were not written by the prior session, but both artifacts are present on disk and complete: `test_helpers/` (9 files) + `test_suite/` (conftest + 8 `test_*.py` files, 62 tests total) from the unit-test-generator, and `workspace/implementation/` (app.py, db.py, errors.py, middleware.py, models.py, response.py, validate.py, clock.py, `routes/`, `services/`, `requirements.txt`, `start.sh`) from the implementation-generator. No subagent summaries are available to paste verbatim. Steps 5/6 were not re-run on resume per scope.

## Step 7: Run tests and iterate — 2026-06-07T13:25:00.000Z

All 8 rounds pass with 62/62. Clean sweep confirmed.

- **Iterations run:** 2 (initial sweep surfaced the failures; second sweep confirmed the fix).

- **Final sweep result:** All 8 parallel rounds passed with `passed == total == 62`. No flakiness — the same 2 tests failed identically in all 8 rounds before the fix, and all 62 pass in all 8 rounds after.

- **Tests deleted:** 0 deletions. The failing tests covered a PRD-verbatim rule (the §3.1 cleanliness-fit formula) that uniquely determines the outcome, so deletion was not warranted — the bug was a test-side mistranslation.

- **Fixes applied to `test_suite/`:**
  - `test_02_compatibility_and_matching.py`, `test_withdraw_then_reapply_returns_to_pending_and_recomputes_score`: changed listing `wants_cleanliness` from 1 to 5 so the applicant's `cleanliness=5` actually matches, making the PRD clean-fit formula yield 1.0 (40 pts) → score 100 as the test's "perfect fit" intent requires. The prior setup (wants=1, cleanliness=5) gave clean fit `max(0,5-|5-1|)/5 = 0.2` → 8 pts → 68, so `assert == 100` was wrong.
  - `test_02_compatibility_and_matching.py`, `test_accept_perfect_score_well_above_threshold_succeeds`: same fix (wants_cleanliness 1→5) for the same reason; score 100 still satisfies the ≥60 accept threshold.

- **Fixes applied to `test_helpers/`:** 0 test_helpers fixes. (The listing factory's `wants_cleanliness=1` default is used correctly by other passing tests; only these two tests needed an explicit override, which they already supplied — just with the wrong value.)

- **Fixes applied to `implementation/`:** 0 implementation fixes. `services/calc.py:compatibility_score` was already PRD-faithful (verified against passing tests `test_compatibility_three_factor_nonlinear_score` (84) and `_second_combination` (76)); it correctly returned 68 for the mis-specified fixtures.

## Step 8: Finalize PRD — 2026-06-07T13:27:00.000Z

(Step 8 NOT skipped: Step 7 had 2 `test_suite/` fixes, so the skip condition — all four fix/deletion counts zero — was not met. Subagent ran and produced `PRD_FINALIZED.md`.)

**0 edits — PRD_FINALIZED.md is identical to PRD.md** (byte-for-byte: same cksum `1698379290`, 272 lines each, 43202 bytes, 0% delta).

### Why zero edits

The only Step 7 change was two `test_suite/` fixture-value corrections (`wants_cleanliness` 1→5), with **0 implementation fixes, 0 deletions, 0 test_helpers fixes**. Per Method step 1, a pure test-fixture-value bug where the impl was already PRD-faithful and the PRD already uniquely determined the behavior is NOT a PRD silence or PRD-mismatch — so there is nothing to pin.

Verified that PRD.md §3.1 (line 124) already uniquely determines what `services/calc.py:compatibility_score` computes, term by term:
- **Clean fit** — PRD: "absolute difference between `cleanliness` and `wants_cleanliness`, subtract from 5, larger of that and 0, divide by 5" == impl `max(0, 5 - abs(cleanliness - wants_cleanliness)) / 5.0` (calc.py:25). Exact.
- **Sleep fit** — PRD: "1 when either side is `FLEXIBLE`, or exact match; otherwise 0" == impl (calc.py:29-34). Exact.
- **Lifestyle fit** — PRD: "begins 1.0, −0.5 for smoker break, −0.5 for pet break, floored at 0" == impl (calc.py:36-43). Exact.
- **Weights / rounding** — PRD: "clean×40 + sleep×30 + lifestyle×30 … rounded half-up" == impl `W_CLEAN=40, W_SLEEP=30, W_LIFESTYLE=30` + `round_half_up` (calc.py:10-12, 45-46). Exact.
- **STRICT zeroing** — PRD line 126 == impl (calc.py:48-51). Exact.

### Per-edit pre-edit search log (investigated subject, no edit committed)

**(a) Subject investigated:** the compatibility-score / cleanliness-fit formula and its weighting/rounding/STRICT-zeroing.
**(b) Impl paths enumerated, read/grepped:** `services/calc.py:24-51` (`compatibility_score`); `routes/match_requests.py:44` (creation, STRICT default), `:187` (reapply recompute), `:104` (accept gate `< MATCH_THRESHOLD` 60); `routes/listings.py:29,43` + `routes/profiles.py:33,43` (`wants_cleanliness`/`cleanliness` int 1–5). All consistent with existing PRD prose.
**(c) Wording adjustment:** none — no edit was warranted.

## Step 9: Complete PRD — 2026-06-07T13:40:00.000Z

(Step 9 always runs. Source: `PRD_FINALIZED.md` exists → copied to `PRD_COMPLETED.md`, then patched.)

**Files:** Source `PRD_FINALIZED.md` (272 lines, 43,202 chars) → `PRD_COMPLETED.md` (272 lines, 46,386 chars). Char delta: **+3,184**. Line count unchanged (all edits were in-paragraph inserts/revisions; no new paragraphs or sections).

**Counts:** 11 changes total — **5 ambiguity-pins**, **6 mismatch-revisions**.

**Per-change log** (`{section} — {insert|revise} — {ambiguity|mismatch} — {what} — {impl ref}`):
- **§2.6 Conservation/Net-Balance** — revise — mismatch — PRD claimed `net_balance_cents` includes "unpaid bill shares they still owe"; impl excludes all bill splits entirely (bill obligations owed externally, not internally conserved) — `services/household.py:60-112`.
- **§2.9 Ledger Freeze** — revise — mismatch — PRD said "Four operations are gated"; impl also gates expense **void** (a fifth), excludes internal adjudication recomputes — `routes/expenses.py:164-165`.
- **§3.2 Acceptance** — revise — mismatch — PRD required listing `OPEN` and household below capacity at accept; impl enforces neither at accept (capacity/occupancy gates fire at activation) — `routes/match_requests.py:98-105`.
- **§3.4 Bill issue** — revise — ambiguity — relative order of `ERR_BILL_PERIOD_OVERLAP` vs `ERR_INVALID_PERIOD` unpinned; impl checks RENT overlap first — `routes/bills.py:41-48`.
- **§3.4 Record-payment** — revise — ambiguity — actor need not be the paid member (any ACTIVE member); pinned `ERR_NOT_RESOURCE_OWNER` (non-member actor) and `ERR_NOT_HOUSEHOLD_MEMBER` (named profile has no split) — `routes/bills.py:119-132`.
- **§3.5 Move-out proration** — insert — ambiguity — pinned last-member degenerate case (freed remainder not redistributed, total preservation no longer holds) and no-current-rent-bill no-op case — `services/household.py:174-211`.
- **§3.6 Expense void** — insert — ambiguity/mismatch — pinned any `Roommate` may void (no payer/member ownership check) and void is `FROZEN`-gated — `routes/expenses.py:153-165`.
- **§3.7 Settlement confirm** — revise — mismatch — PRD listed `ERR_SETTLEMENT_EXCEEDS_DEBT` before `ERR_NO_OUTSTANDING_DEBT`; impl checks no-debt (`debtor_net >= 0`) first — `routes/settlements.py:114-120`.
- **§3.8 Reminder schedule** — insert — ambiguity — pinned `ERR_INVALID_STATE` for scheduling against a PAID bill and `ERR_NOT_FOUND` for an unresolved target — `routes/reminders.py:33-46`.
- **§3.8 Reminder acknowledge** — revise — ambiguity — pinned any `Roommate` may acknowledge (no recipient binding) and `ERR_INVALID_STATE` when not `SENT` — `routes/reminders.py:96-108`.
- **§3.9 Dispute file + adjudicate** — insert/revise — ambiguity/mismatch — pinned `ERR_VALIDATION` for neither/both targets; corrected "the mediator who claimed it may reopen" (impl binds no action to the claiming mediator; mediator IDs opaque/unpersisted; reopen has no filer check); pinned `ERR_VALIDATION` for bad expense `adjusted_amount_cents`, the EQUAL recompute that discards `CUSTOM` overrides, and optional-record-only behavior for settlement-targeted resolves — `routes/disputes.py:53-54,143-179,188-202,224-238`.

All changes in-paragraph; no new sections, no invented behavior. Tests used only as auxiliary cross-reference.

---

**Pipeline complete.** Steps 7–9 finished for `task_0225_roommate_expense_split` (Expert). Final state: 62 tests, all 8 stability-sweep rounds at 62/62; `PRD_FINALIZED.md` (= PRD.md, 0 edits) and `PRD_COMPLETED.md` (+3,184 chars, 11 pins/revisions) written; `results.{1..8}.json` present.
