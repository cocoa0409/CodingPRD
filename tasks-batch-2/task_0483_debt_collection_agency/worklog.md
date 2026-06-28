# Worklog — task_0483_debt_collection_agency

Scenario: Debt Collection Agency (FDCPA): account placement & validation notice, consumer dispute & cease-communication, call-attempt cadence & time-of-day rules, payment plan & settlement (% offer), skip-tracing, statute-of-limitations & re-aging guardrail, credit-bureau furnish/dispute, recall/close & commission.

Target difficulty: Expert. Task directory pre-assigned (no index scan / auto-increment).

## Step 1: Create Task Directory — 2026-06-24T14:38:09.000Z

Pre-assigned directory `tasks/task_0483_debt_collection_agency/` already existed with an empty `workspace/` subdir. Verified presence; no index scan or auto-increment performed (override). `INSTRUCTION.md`, all six `prd-bench-*` skills, and `prd-bench-local-run` confirmed available.

## Step 2: Generate Scaffold (Expert) — 2026-06-24T14:54:57.000Z

Generated three lint-clean scaffold artifacts for **task_0483_debt_collection_agency** (Expert tier, FDCPA debt collection), built purely from the scenario + scaffold-generator spec. Final `scaffold_lint.py` verdict: **clean lint**.

**Complexity profile:** primary archetype `compliance_audit` + secondary `ledger_reconciliation`; flat entity topology; **parallel** state-machine shape; peer-roles RBAC; immediate consistency.

**Entities (10):** Creditor, Consumer, Account (central debt, dual-dimension), CommunicationAttempt, Dispute, PaymentArrangement, Payment, SkipTrace, BureauFurnishing, BureauDispute.

**State machines (6 across 5 entities):**
- **Account** carries two *parallel* dimensions — `work_status` (PLACED→VALIDATION_SENT→WORKING→{CLOSED_PAID, RECALLED, CLOSED_UNCOLLECTIBLE}) and `contact_status` (PRE_VALIDATION→CONTACTABLE↔VALIDATION_HELD→CEASED).
- **Dispute** — *cyclic* (OPEN→INVESTIGATING→RESOLVED→REOPENED→RESOLVED).
- **PaymentArrangement** — *branching* (PROPOSED→{ACCEPTED, COUNTERED, REJECTED}→FULFILLED/CANCELLED).
- **Payment** — POSTED→{REVERSED, VOIDED} (compensating).
- **BureauDispute** — cyclic e-OSCAR reinvestigation.

**Key calculations (6):** `commission_earned` (GROSS vs NET variant, per-payment-then-sum rounding), `payoff_quote` (QUOTE_DATE vs GOOD_THROUGH accrual variant), `settlement_floor` (3-input nested max + verified-dispute bump), `sol_status` (re-aging guardrail, CHARGE_OFF vs LAST_PAYMENT anchor), `cadence_window_count` (7-in-7 trailing window), `account_balance` (ledger reconciliation/invariant).

**Counts:** 14 validations · 17 error codes · 44 endpoints · 5 roles (Creditor, Collector, ComplianceOfficer, BureauOperator, System) · 2 OCC concurrency rules (recall + reverse, both on `Account.version`).

**§1.8 (difficulty):** 18 instances — all 9 rule_ids × 2 each.
**§1.9 (corner):** 33 instances — 29 active test recipes + 4 `excluded_because:` stubs (all referencing valid §1.8 instances). Sections covered: entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model. Every error code is triggerable; no name collisions across files; all 339 setup/trigger calls conform to §1.5.

Files: SCAFFOLD.yaml (1270 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1023 lines, top key `scaffold_difficulty_design`), SCAFFOLD_CORNER_DESIGN.yaml (1069 lines, top key `scaffold_corner_design`). SCAFFOLD.yaml confirmed clean of both design keys.

## Step 3: Copy Shared Files — 2026-06-24T14:55:03.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-24T15:01:41.000Z

Generated `workspace/PRD.md` — a 265-line prose PRD for the Debt Collection Agency (FDCPA) API. All three doc-generator Hard Contracts PASS.

### Section structure
- **§1 Introduction** — 3 paragraphs (regulatory-gating angle, peer-entity topology, logical-clock framing)
- **§2 Global Specifications** (10 subsections): 2.1 RBAC (5 roles + entity-backed/opaque identity), 2.2 Response Structure, 2.3 Pagination, 2.4 Logical Clock, 2.5 Common Resource Properties, 2.6 Monetary Precision, 2.7 OCC, 2.8 Two State Dimensions, 2.9 Cascades/Conservation, 2.10 Existence/Validation/State Checking Order
- **§3 Business Logic** (11 subsections): onboarding, account placement & SOL, validation notice, disputes, contact logging (cease/hold/call-window/cooldown/cadence), arrangements (plans/settlements/floor/time-barred), payments/ledger/fulfillment, recall cascade, commission, payoff quote, bureau furnishing & e-OSCAR
- **§4 Endpoint Definitions** — 4-column table (44 endpoints) + status-code rules
- **§5 Error Code Catalogue** — 2-column table (17 errors)

### Coverage confirmation (all PASS)
- **Contract 1 (Field-Name Coverage): PASS** — 54/54 entity fields in backticks; 37/37 endpoint identifiers present; 0 missing.
- **Contract 2 (Rule Coverage): PASS** — all 6 calculations rendered step-for-step (commission GROSS round-per-line-then-sum vs NET single-rounding; payoff QUOTE_DATE/GOOD_THROUGH 50¢/day; settlement floor age 180/730→7000/5000/3000 bps, balance 1,000,000→4000/6000 bps, max-of-two, verified +1000 cap 10000; SOL ≥-expiry; cadence half-open 7-in-7; balance floored at zero); both OCC rules; all state transitions paired to error IDs; all 14 priority-ordered validations; recall & DELETED-dispute cascades; §2.10 evaluation order.
- **Contract 3 (§3 Path Purity): PASS** — 451 backtick tokens scanned in §3; 0 endpoint paths/methods leaked.
- All 17 error IDs, 5 role names, 24 enum + 26 state values appear verbatim.

Design YAMLs (DIFFICULTY/CORNER) were NOT opened, grepped, or referenced.

## Step 5: Generate Unit Tests — 2026-06-24T18:22:53.000Z

Generated complete test infrastructure for **task_0483_debt_collection_agency** (Debt Collection Agency FDCPA, Expert tier).

**test_helpers/** — 9 files: `__init__.py`, `types.py`, `api_client.py` (one method per PRD §4 endpoint), `api_errors.py` (17 error IDs + HTTP-status map registered with the framework), `assertions.py` (per-entity assertions + ledger-conservation invariant), `factories.py`, `constants.py`, `test_users.py` (Creditor is entity-backed with `make_creditor_headers`; the other four roles opaque), `fixtures.py` (composite WORKING-account / arrangement+payment / cadence-window / dispute / furnishing builders).

**test_suite/** — 8 files: `conftest.py` + 7 test files (test_01 calculations, test_02 state-machines/cascades, test_03 FDCPA guardrails/boundaries, test_04 entities CRUD, test_05 state transitions, test_06 calculations/validations, test_07 endpoints/RBAC/OCC/consistency).

**Totals:** 67 test functions, each carrying exactly one `Design:` tag and a verbatim PRD citation.

**Queue A (Difficulty):** all 18 instances covered, ≥2 tests each (38 tests total). No shortfalls.

**Queue B (Corner):** all 27 non-stub instances covered, ≥1 test each (29 tests total). The 4 `excluded_because:` stubs were NOT translated — all cross-references verified to resolve to real difficulty instances:
- `calculations/payoff_quote_quote_date_default` → dual_variant_calc/payoff_quote_date_vs_good_through_diverge_on_arrangement
- `validations/arrangement_accept_below_floor_rejected` → combinatorial_formula/settlement_floor_three_input_nested_minmax
- `errors/error_invalid_state_covered` → cross_entity_state_dependency/attempt_blocked_by_account_cease_status
- `errors/error_time_barred_covered` → priority_pair_validation_conflict/time_barred_temporal_beats_settlement_floor_fiscal

**Skipped instances:** none. Every non-stub instance passed the PRD-first two-condition filter. Notably the two priority-pair conflicts (cease-vs-call-window, time-barred-vs-floor) were both confirmed uniquely-derivable from the PRD's explicit ordered prose in §3.5 ("First… For a PHONE attempt…") and §3.6 ("must be in WORKING… must not be time-barred… Also… at least the computed settlement floor").

**Verification passes:** all files compile; 70/70 PRD citations survive a literal grep of PRD.md; 67 test defs == 67 Design tags (no untagged/dual-tagged); no `skip`/`xfail`/`skipif` markers; no scaffold/table references leaked into emitted code.

## Step 6: Generate Implementation — 2026-06-24T18:22:53.000Z

Generated a complete Python + Flask implementation for the Debt Collection Agency (FDCPA) API at `tasks/task_0483_debt_collection_agency/workspace/implementation/`.

**Source files:** 24 Python files (plus `start.sh` and `requirements.txt`). Organized as foundation modules (`clock.py`, `errors.py`, `response.py`, `db.py`, `middleware.py`, `money.py`, `validation.py`, `pagination.py`, `serializers.py`, `app.py`), 9 route blueprints under `routes/`, and 3 business-logic services under `services/` (accounts, arrangements, transitions).

**Endpoints:** All 43 from the PRD/scaffold endpoint table implemented — clock, creditors, consumers, skip-traces, accounts (CRUD + 5 transitions: send-validation-notice, begin-work, cease-communication, recall, close-uncollectible), communication-attempts, disputes (raise/investigate/resolve/reopen), arrangements (propose/accept/counter/reject/payoff-quote), payments (post/reverse), bureau-furnishings, and bureau-disputes (open/resolve/reopen).

**State machines implemented (5):**
- Account `work_status` (PLACED → VALIDATION_SENT → WORKING → CLOSED_PAID, plus RECALLED / CLOSED_UNCOLLECTIBLE) and the parallel `contact_status` (PRE_VALIDATION → CONTACTABLE ⇄ VALIDATION_HELD → CEASED) tracked independently.
- Dispute cyclic (OPEN → INVESTIGATING → RESOLVED ⇄ REOPENED) with VALIDATION-hold and DELETED-closure side effects.
- PaymentArrangement branching (PROPOSED → ACCEPTED/COUNTERED/REJECTED, → FULFILLED, → CANCELLED via recall).
- Payment linear (POSTED → REVERSED / VOIDED) with compensating ledger restoration.
- BureauDispute cyclic (OPEN → RESOLVED ⇄ REOPENED) with CORRECTED/DELETED furnishing effects.

**Calculations:** dual-variant commission (GROSS round-per-line-then-sum vs NET single-rounding with expense recovery), settlement floor (age/balance/verified-dispute tiers, nested max + dispute bump), payoff quote (QUOTE_DATE vs GOOD_THROUGH with $0.50/day admin accrual), SOL/time-barred with re-aging guardrail, balance reconciliation, and the 7-in-7 trailing cadence window. All money uses `Decimal` round-half-up. The three-level recall cascade and settlement-fulfillment forgiveness are implemented; OCC via `expected_account_version` (412 ERR_STALE_VERSION) on recall and reverse.

**Storage model:** In-memory only — Python dicts keyed by id in `db.py` (one dict per entity type). No SQLite, no JSON file, no disk persistence. No entity seeding or hardcoding at startup; the store is empty on every boot and the logical clock defaults to `2026-01-01T00:00:00Z`. Verified by smoke + edge tests: a fresh `start.sh` re-invocation showed `total_count: 0` accounts and the default clock value.

**start.sh:** reads `$PORT` (default 10000), binds `0.0.0.0`, runs in the foreground via `exec python3 app.py`, and guards `pip install` behind a `python3 -c "import flask"` check so per-test reboots don't re-install.

## Step 7: Run Tests and Iterate — 2026-06-24T18:22:53.000Z

**Iterations run:** 2 (one diagnostic sweep that exposed 16 deterministic failures, one verification sweep after fixes that went fully green).

**Tests deleted:** None. All 16 failing tests passed STEP 1 (PRD coverage + unique derivability) and STEP 2 (PRD consistency). No PRD-silence or collapse patterns were present.

**Fixes applied to test_helpers/:**
- `test_helpers/fixtures.py` — `post_payment()`: was unwrapping the response via `get_success_data(res)` and returning a bare `dict`, but every call site in the test suite wraps it as `get_success_data(post_payment(...))` (the same convention `log_phone_attempt` follows). The double-unwrap fed a `dict` into the framework's `get_success_data`/`validate_*`, which access `response.status_code` — producing `AttributeError: 'dict' object has no attribute 'status_code'` in 15 tests. Changed `post_payment` to return the raw framework `Response`, restoring the consistent "helper returns Response, caller unwraps" convention. Also updated the one internal caller (`setup_working_account_with_plan_payment`) to wrap the call in `get_success_data` so the fixture's own `ctx["payment"]` stays a dict.

**Fixes applied to implementation/:**
- `workspace/implementation/routes/accounts.py` — `send_validation_notice()`: the generic `work_status != "PLACED"` state check ran before the `validation_notice_sent_at is null` guard, so a repeat notice on an already-`VALIDATION_SENT` account returned `ERR_INVALID_STATE` instead of the PRD-mandated `ERR_VALIDATION_ALREADY_SENT` (PRD §3.3: "a repeat attempt is rejected with `ERR_VALIDATION_ALREADY_SENT`"). Reordered so the `validation_notice_sent_at` repeat-guard is evaluated first. Safe because the only path that sets `validation_notice_sent_at` non-null is this same transition, so no account can be non-PLACED with a null `validation_notice_sent_at`.

**Final pass count:** 67/67 in all 8 parallel rounds. Union of failing tests across rounds = 0. All `results.{1..8}.json` present and confirmed green. No flakiness surfaced (failures were deterministic in iteration 1 and fully resolved in iteration 2). No PRD-required implementation check was weakened; no assertion was downgraded; storage remains in-memory only.

## Step 8: Finalize PRD — 2026-06-24T18:22:53.000Z

Ran (not skipped — Step 7 made 1 implementation/ fix + 1 test_helpers/ fix). Produced `workspace/PRD_FINALIZED.md`.

**Line counts:** PRD.md = 265 lines, PRD_FINALIZED.md = 265 lines. One line revised (line 130). Net 0 lines added; %-delta ≈ 0.38% (1/265).

**Change:**
- §3.3 (Validation Notice) — revise — pinned the check ordering inside `send-validation-notice`: the `validation_notice_sent_at` non-null repeat-guard (`ERR_VALIDATION_ALREADY_SENT`) is evaluated *before* the `work_status == "PLACED"` state check, so it takes precedence over the §2.10 `ERR_INVALID_STATE`; the PLACED-state check only applies once `validation_notice_sent_at` is confirmed null — implementation/routes/accounts.py:123-127.

**Pre-edit search log (NO-NEW-MISMATCH):** enumerated `send_validation_notice` + every `work_status` assignment and `validation_notice_sent_at` reference across `routes/*` and `services/*`. Found `recall`/`close-uncollectible` can move an account out of `PLACED` directly (leaving `validation_notice_sent_at` null), so `ERR_INVALID_STATE` IS reachable on this endpoint. Corrected an initial false-universal draft ("ERR_INVALID_STATE never observed here") to spell out the recalled/closed-from-PLACED edge case. The `fixtures.py` Step 7 item is a pure fixture bug with no PRD implication — no edit.

## Step 9: Complete PRD — 2026-06-24T18:22:53.000Z

Full PRD-vs-implementation scan. Produced `workspace/PRD_COMPLETED.md` from `PRD_FINALIZED.md`.

**Line/char counts:** PRD_FINALIZED.md = 265 lines / 47,298 chars; PRD_COMPLETED.md = 265 lines / 49,805 chars. Char delta = +2,507. 10 lines revised, no sections added.

**Counts:** ambiguity-pins = 7, mismatch-revisions = 3.

**Changes:**
- §2.2 — insert — ambiguity — `api_request_timestamp` is the logical clock value, not host wall-clock — response.py:18.
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` clamped (limit→[1,100], offset≥0); non-integer → `ERR_INVALID_REQUEST` — pagination.py:26-32,13-20.
- §3.4 (raise) — insert — ambiguity — `VALIDATION_HELD` push on in-window VALIDATION dispute only when `contact_status` is `CONTACTABLE` — routes/disputes.py:49-52.
- §3.4 (resolve) — insert — mismatch — dispute-state check precedes resolution-presence check (`ERR_INVALID_STATE` wins over `ERR_INVALID_REQUEST`) — routes/disputes.py:99-102.
- §3.4 (DELETED closure) — insert — ambiguity — "still-open" furnishings = any `status` not already `DELETED`; path runs only when account not already closed — services/transitions.py:99-105.
- §3.4 (reopen) — insert — ambiguity — re-applying hold pushes to `VALIDATION_HELD` only when `contact_status` is `CONTACTABLE` — routes/disputes.py:129-131.
- §3.5 (cadence) — insert — ambiguity — admission window anchored at new attempt's own `attempted_at`; refused when prior count already 7 — routes/communication.py:101-106.
- §3.7 (reversal) — revise — mismatch — `ERR_STALE_VERSION` evaluated before state check; non-`POSTED` payment → `ERR_INVALID_STATE` — routes/payments.py:99-104.
- §3.8 (recall) — revise — mismatch — `ERR_STALE_VERSION` evaluated before `ERR_INVALID_STATE` — routes/accounts.py:172-175.
- §3.10 (payoff) — insert — ambiguity — under `GOOD_THROUGH`, null `good_through` → zero accrual days (payoff = base) — services/arrangements.py:50-56.
- §3.11 (bureau resolve) — revise — mismatch — bureau-dispute state check precedes outcome-presence check — routes/bureau.py:129-132.

Pipeline complete: all 9 steps recorded. Final state 67/67 green across 8 parallel per-test-server rounds.
