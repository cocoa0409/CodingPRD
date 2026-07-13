# Worklog — task_0786_greeting_card_reminder

## Step 1: Create task directory — 2026-07-07T00:00:00.000Z

Pre-assigned folder `tasks/task_0786_greeting_card_reminder` used as-is (index scan skipped per run instructions). `workspace/` subdirectory already present. Fresh start — no prior artifacts.

## Step 2: Generate scaffold (Expert) — 2026-07-07T11:27:00.000Z

All three files are written, parse cleanly, pass `scaffold_lint.py`, and all pinned numeric values are code-verified. (safe_load re-verified by orchestrator — all 3 OK.)

Generated the **Expert**-difficulty scaffold for task_0786 (Greeting-Card & Occasion-Reminder Service):
- SCAFFOLD.yaml — §1.0–§1.7
- SCAFFOLD_DIFFICULTY_DESIGN.yaml — §1.8 (single key scaffold_difficulty_design)
- SCAFFOLD_CORNER_DESIGN.yaml — §1.9 (single key scaffold_corner_design)

Structure:
- Archetype: workflow_orchestration + ledger_reconciliation; layers: scheduled/deferred actions, cascading side effects, dual-variant calc, optimistic concurrency. Topology hybrid, state_machine_shape: parallel, peer_roles.
- 12 entities: Account, Subscription, CreditTransaction (event log), Contact, ImportantDate, Card, GiftItem, HandwritingArtist, Order, Proof, ArtistAssignment, Shipment.
- 43 endpoints (2 test-driving: /_clock/set_current_utc default 2026-03-01T00:00:00Z, /_scheduler/run). Every FK reverse-reachable (lint check (f) clean).
- 29 error codes; 19 ordered validations (auth→existence→state→safety→referential→temporal→constraint→fiscal); 3 roles (AccountHolder entity_backed:Account, StudioOperator/PlatformAdmin opaque).
- 8 state machines: Order.status (branching pipeline w/ cancel reverts), Order.credit_status (parallel NONE→HELD→SETTLED/REFUNDED), Proof (cyclic revision loop), Contact.address_status, ImportantDate (recurring self-loop), Subscription, ArtistAssignment, Shipment.
- 1 concurrency rule: OCC on Account.version at POST /orders/{id}/submit (CREATE-time credit-hold race → ERR_STALE_ACCOUNT_VERSION 412).
- 5 calculations incl. 2 dual-variant families: order_total (estimate 2050 vs final 1823) and renewal_credit_grant (full 12 vs prorated 4); plus order_tax (sum-then-round: discount 100 not 99), account_credit_balance, important_date_next_trigger.

Design instance counts:
- §1.8: 9 rules × 2 = 18 instances.
- §1.9: 24 instances across 9 taxonomy sections (22 active + 2 excluded_because stubs).

Verification: scaffold_lint.py clean (320 calls); all formula asserts code-verified.

## Step 3: Copy shared files — 2026-07-07T11:27:30.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-07-07T11:34:00.000Z

Generated workspace/PRD.md — prose PRD for the Greeting-Card & Occasion-Reminder Service. 256 lines. Endpoints documented: 43 (== scaffold endpoint count, parity asserted by orchestrator). Error catalogue: 29.
Sections: §1 Intro; §2 Global (RBAC, response envelope, pagination, common props/versioning w/ CreditTransaction common_fields:false, logical clock & scheduler, credit ledger, precision/rounding sum-then-round-once, OCC, validation ordering & nested resolution, parallel order dimensions & cascades); §3 Business Logic (9 subsections, no HTTP paths); §4 endpoint table; §5 error table.
Hard contracts: Field-Name Coverage 74/74 PASS; Rule Coverage (all state machines + 5 calcs + OCC + validation priority + all error_ids) PASS; §3 Path Purity 323 tokens 0 violations PASS.
Constraint confirmed: neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read.

## Step 5: Generate unit tests — 2026-07-07T11:50:00.000Z

Generated test_helpers/ (9 files: __init__, types, api_client (43 endpoint methods), api_errors (29 IDs), assertions, factories, constants, test_users (3 roles; AccountHolder entity_backed w/ make_account_holder_headers(account_id)), fixtures) and test_suite/ (conftest + 7 domain files test_01..test_07).
58 test functions total: Queue A (Difficulty) 36 — all 18 non-stub instances × 2; Queue B (Corner) 22 — all 22 non-stub instances × 1.
Skipped 2 (excluded_because stubs): Corner/calculations/renewal_full_grant_variant; Corner/validations/reminder_window_overlap_excluded — both cross-ref real difficulty instances.
Every test carries exactly one Design: tag (58/58). Sampled PRD citations verbatim-confirmed. No skip/xfail. pytest --collect-only → 58 collected (orchestrator re-verified: 58 collected, 0 errors).
Pinned literals: estimate 2050/final 1823; discount 320/tax 93; sum-then-round 100 (not 99); proration 4 vs full 12; postage boundaries 30→150/31→250, 60→250/61→450; next_trigger_at 2027-03-25T00:00:00.000Z.

## Step 6: Generate implementation — 2026-07-07T11:50:30.000Z

Built Python + Flask impl at workspace/implementation/: app.py (~1130 lines single-file), requirements.txt (flask==3.0.3), start.sh (foreground, reads $PORT default 10000, binds 0.0.0.0, exec python3 app.py, guarded pip install).
All 43 endpoints. State machines: Order.status (8-state), Order.credit_status (parallel NONE→HELD→SETTLED/REFUNDED), Proof (cyclic + cascade-void), Contact.address_status, ImportantDate, Subscription, ArtistAssignment, Shipment (DELIVERED→order cascade). Cascades bump version/updated_at.
Calcs: weight-tiered postage; order_total estimate vs final; order_tax sum-then-round-once (Decimal/ROUND_HALF_UP); renewal_credit_grant full vs ceil-proration; append-only ledger w/ balance_after; next_trigger_at annual roll-forward. Logical clock default 2026-03-01T00:00:00Z; deterministic scheduler.
Envelope meta/response_type/data; pagination meta; X-User-ID/Role auth w/ entity-backed ownership (403 single-get + list filter); validation precedence auth→role→body→existence(L-to-R)→ownership→state→business-priority; OCC expected_account_version (412); half-open artist-window overlap + daily-capacity; 2-day reminder buffer; cancel refund/release/void cascade.
Fixed 1 bug during self-test (discount_pct float broke Decimal mult). In-memory only, empty on boot.
NOTE (watch in Step 7): impl self-test reported proration = ceil(12·20/30)=8, but design index / test literal pins prorated grant = 4. Also GET /artist-assignments/{id} reuses ERR_ORDER_NOT_FOUND for missing (no ERR_ASSIGNMENT_NOT_FOUND in catalog); status 404 correct.

## Step 7: Run tests and iterate — 2026-07-07T12:05:00.000Z

CLEAN FIRST-SWEEP PASS. Iterations run: 1 (baseline 8-round sweep, run as 2 waves of 4 to avoid host saturation across the 5 parallel runs). All 8 rounds returned passed==total==58 with status='passed' on every test; union of failing tests empty. Orchestrator independently re-verified all 8 results.*.json → 58/58 each.
Tests deleted: None. Fixes to test_helpers/: None. Fixes to implementation/: None.
Two orchestrator-flagged self-test items investigated, both non-issues:
- (a) Proration: PRD §3.1 pins "new tier's monthly credit count × days-remaining ÷ thirty, rounded up." Fixture's clock leaves 10 days → ceil(12·10/30)=4, matching the literal. The "8" was against a 20-day assumption; actual fixture uses 10 days → PRD uniquely determines 4, impl correct.
- (b) GET /artist-assignments/{missing}: no test asserts a specific error_id on that path (grep confirms), so the ERR_ORDER_NOT_FOUND reuse is never exercised — moot.

## Step 8: Finalize PRD — SKIPPED — 2026-07-07T12:05:30.000Z

Skipped per skill skip-condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, 0 implementation/ fixes (zero iterations beyond baseline). PRD.md already determined every behavior the implementation exhibits at all Step-7-touched sites. No PRD_FINALIZED.md produced. Step 9 still runs.

## Step 9: Complete PRD — 2026-07-07T12:06:00.000Z

Produced workspace/PRD_COMPLETED.md (started from PRD.md since Step 8 skipped). Minimal in-paragraph patch: PRD.md 256 → PRD_COMPLETED.md 256 lines (0 lines added), char delta +1395 (38193 → 39588). 6 ambiguity-pins, 3 mismatch-revisions (9 edits across 8 passages).
Changes:
- §2.3 Pagination — insert — ambiguity — out-of-range limit/offset silently clamped (1..100, offset≥0); non-integers → ERR_VALIDATION — app.py:361-366,351-360.
- §2.3 Pagination — insert — ambiguity — account-subscription, order-proofs, order-shipment listings return full array unpaginated, omit pagination meta — app.py:531,1157,1327.
- §2.6 Credit Ledger — revise — mismatch — balance is raw signed sum, no clamp; over-drawing MANUAL_ADJUST can go negative (PRD claimed "never negative") — app.py:310-311,314-328.
- §3.1 Credit adjustment — insert — ambiguity — returns new CreditTransaction with 201 (not account) — app.py:591-593.
- §3.1 Subscriptions — revise — mismatch — "only one ACTIVE subscription" not enforced on create; second create succeeds — app.py:492-521.
- §3.4 Order create — revise — mismatch — client-supplied important_date_id accepted as-is, not existence-validated on manual create — app.py:1004.
- §3.6 Production discount — insert — ambiguity — when multiple ACTIVE subs, most recently created supplies discount_pct — app.py:417-421.
- §3.6 Assignments — insert — ambiguity — filterable by status; non-existent assignment fetch returns ERR_ORDER_NOT_FOUND (no dedicated code) — app.py:1141,1130-1132.
- §3.9 Scheduler — insert/revise — ambiguity+mismatch — auto orders carry empty message_text, default SCRIPT font, no gift; event date + next_trigger_at advance one year every firing regardless of recurrence — app.py:1416-1439.
Verified already-pinned (no change): proration formula, postage tiers, single-rounding discount/tax order, tax-rate table, submit ordering w/ OCC last, cancellation cascades, validation-precedence not-found codes.

## PIPELINE COMPLETE — 2026-07-07T12:06:30.000Z

All 9 steps done (Step 8 skipped — clean first-sweep pass). Final state: 58/58 tests pass stably across 8 rounds. Artifacts present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/, test_suite/, workspace/{INSTRUCTION.md, PRD.md, PRD_COMPLETED.md, implementation/ (+ results.1-8.json all 58/58)}.
