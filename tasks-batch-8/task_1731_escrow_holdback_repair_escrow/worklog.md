# Worklog — task_1731_escrow_holdback_repair_escrow

## Step 1: Create Task Directory — 2026-08-14T11:59:00.000Z

Task directory `tasks/task_1731_escrow_holdback_repair_escrow/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher; Step 1 treated as DONE per invocation args. Difficulty directive from requester: "harder than expert level".

## Step 3: Copy Shared Files — 2026-08-14T12:00:19.220Z

Copied `./INSTRUCTION.md` → `tasks/task_1731_escrow_holdback_repair_escrow/workspace/INSTRUCTION.md`.

## Step 2: Generate Scaffold — 2026-08-14T13:02:55.262Z

Scaffold generation complete for `task_1731_escrow_holdback_repair_escrow`. All three artifacts are written and pass the skill's lint with zero violations.

### Deliverables

- `/home/ubuntu/github/CodingPRD/tasks/task_1731_escrow_holdback_repair_escrow/SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1731_escrow_holdback_repair_escrow/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1731_escrow_holdback_repair_escrow/SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

### Counts (Expert band, upper limits)

- **Entities: 11** — EscrowFile, Holdback, Approval, Bid, WorkOrder, Inspection, DrawRequest, ExtensionRequest, Dispute, ShortfallPledge, LedgerEntry
- **Endpoints: 33** (21 POST actions/creates + 12 GETs incl. all FK reverse-reachability lists + `POST /escrow/_clock/set_current_utc` with the mandatory `2026-08-01T00:00:00Z` default)
- **Errors: 30** (all referenced by §1.2/§1.4/§1.5; all triggerable — every code is exercised by a §1.8 instance, §1.9 instance, or §1.9 stub)
- **Calculations: 6** — holdback_sizing (dual-variant), shortfall_assessment, draw_payable_cap (dual-variant), extension_grant (nested-min), close_waterfall (waterfall + pinned rounding order), ledger_reconciliation (chronological accumulator)
- **State machines: 9** + 1 derived (EscrowFile posture); cycles on Holdback (approval-rejection loop) and WorkOrder (rework loop); approval STALE/version-pinning on amend
- **Concurrency: 1** true-race OCC rule (`amend-holdback-stale-version`, 412 ERR_STALE_VERSION)

### Difficulty rules (rule_id → instance names)

- `dual_variant_calc` → holdback_sizing_provisional_vs_commitment, draw_shortfall_net_vs_gross_cap
- `combinatorial_formula` → extension_grant_nested_min_caps (mode a), close_split_rounding_order (mode b)
- `non_linear_state_machine` → work_order_rework_cycle, holdback_approval_rejection_cycle
- `transitive_cascade` → close_cascade_ledger_file_bubbleup (depth 3: Holdback→Ledger→Holdback→EscrowFile), draw_approve_shortfall_pledge_cascade (depth 2: DrawRequest→ShortfallPledge→Holdback)
- `priority_pair_validation_conflict` → pay_state_gate_before_fiscal_gate (state vs business_fiscal), extension_pending_constraint_before_temporal (business_constraint vs business_temporal)
- `boundary_precision_check` → shortfall_threshold_exact_fit_vs_one_cent (cents, approve), expire_deadline_date_boundary (date, expire)
- `cross_entity_state_dependency` → draw_create_requires_active_holdback (DrawRequest→Holdback), final_inspection_requires_completion_submitted (Inspection→WorkOrder)
- `resource_temporal_overlap` → inspector_calendar_half_open_overlap (half-open, adjacency allowed), property_slot_closed_interval_overlap (closed, adjacency conflicts)
- `compensating_invariant` → trust_cash_conserved_over_lifecycle (Σ ledger == balance == 0), reserved_commitment_approve_pay_neutral (reserved == Σ APPROVED draws)

§1.9 carries 57 active corner instances across all nine guide sections plus 11 `excluded_because` stubs (all pointing at real §1.8 instances); 86 instance names are unique across the union.

### Verification

- `scaffold_lint.py` verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (725 calls scanned).
- During authoring the subagent fixed three real consistency bugs the audit surfaced: a stale OCC version in the approval-rejection cycle (rejection bumps Holdback.version before amend), a duplicate-inspection collision inside the shortfall-threshold chain, and two YAML flow-syntax issues (unquoted `$.data[N]` captures and bracketed `grounds:` refs).
- Additional mechanical audits passed: placeholder closure, captures→§1.5 outputs, grounds resolvability, enum-value closure, error-catalog coverage, no forbidden concurrency vocabulary, no id-based business ordering (list ordering pinned as created_at ASC + insertion order), and all formula-derived asserts are pre-computed literals (e.g., 230000/241500 sizing divergence, 10001→5001/5000 pledge split, 10503→5252/5251 close split, granted_days 14 then 16 clamped to the hard stop).

## Step 4: Generate PRD — 2026-08-14T13:30:00.000Z

PRD generated and all hard contracts verified. Summary follows.

### Output

`/home/ubuntu/github/CodingPRD/tasks/task_1731_escrow_holdback_repair_escrow/workspace/PRD.md` — **268 lines**.

### Section list

- **§1. Introduction** (2 paragraphs: business context, then document map)
- **§2. Global Specifications & System-Wide Principles** — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (fixed verbatim block, byte-identical markers confirmed); 2.3 Pagination; 2.4 The Logical Clock and Calendar Semantics; 2.5 Common Resource Properties; 2.6 Money, Integer Cents, and Pinned Rounding; 2.7 The Trust Ledger and Balance Invariants; 2.8 Optimistic Concurrency Control on Amendment; 2.9 Validation Order of Precedence; 2.10 Nested Resources and Hierarchical Consistency
- **§3. Business Logic & Workflows** — 3.1 Opening the Escrow File and Sizing the Holdback; 3.2 The Approval Circuit; 3.3 Contractor Bidding, Selection, and the Work Order; 3.4 Inspections, Scheduling Discipline, and the Rework Loop; 3.5 Draw Requests, Verification, Reservation, and Shortfall Funding; 3.6 Deadline Extensions, Weather Eligibility, and the Hard Stop; 3.7 Disputes and the Disbursement Freeze; 3.8 Expiration and the Closing Waterfall
- **§4. Endpoint Definitions** (4-column table, 33 rows)
- **§5. Error Code Catalogue** (2-column table, 30 rows; file ends here, no audit footer)

### Coverage self-audit

**Contract 1 — Field-Name Coverage: PASS.** All 96 required identifiers (11 entities' full field sets, all request-body keys incl. `to_iso8601`, `expected_holdback_version`, `decision`, `decision_note`, `result`, `resolution`, pagination params, envelope fields) appear verbatim in backticks; 0 missing. (Note: the first check run produced false negatives because the tokenizer miscounted backticks across §2.2's JSON code fences; stripping fenced blocks before tokenizing gave the correct result: 96/96.)

**Contract 2 — Rule Coverage: PASS.** Verified per category: 16/16 validation priorities expressed as an explicit ordered ladder in §2.9 with trigger conditions also placed near workflows in §3; 1/1 OCC rule (write endpoint `POST /escrow/holdbacks/{id}/amend`, `expected_holdback_version`, `ERR_STALE_VERSION`/412 named, no other endpoint takes a version field); all Holdback/Approval/Bid/WorkOrder/Inspection/DrawRequest/ExtensionRequest/Dispute/ShortfallPledge transitions with from/to states, preconditions paired to error ids, and every side effect (rejection loop staling/cancelling approvals, amend STALE cascade + funding delta, expiry cancelling SUBMITTED draws/PLANNED inspections/PENDING extensions, close waterfall zeroing the balance and bubbling the file to CLOSED, dispute freeze and EXPIRED-time `disposition_override`); 6/6 calculations in precise prose — holdback sizing with both PROVISIONAL and COMMITMENT_BASIS variants, shortfall assessment (strictly-greater-than-zero; buyer rounded half-up first, seller residual), NET-pinned payable cap with GROSS as the rejected reading, extension grant as the smallest of four quantities (21/7 per-request caps, 45-day lifetime cap, hard-stop headroom; reject when under one day), close waterfall (approved_at ASC/created_at ASC pay order, seller rounded first, buyer residual, zero-balance invariant), ledger reconciliation invariants; all `applies_to` scopes enumerated (e.g., `ERR_HOLDBACK_NOT_ACTIVE` across all eight gated operations); sibling-branch symmetry maintained across the three dispute resolutions, three funding/disposition splits, and both interval regimes.

**Contract 3 — §3 Path Purity: PASS.** 410 backtick tokens scanned in §3; 0 paths, 0 bare HTTP methods, 0 method+path combos. Endpoints are referenced via state-pair framing, role + verb, or capability description.

Additional spot-checks confirmed verbatim: fixed default clock `2026-08-01T00:00:00Z` with never-wall-clock rule; expire requires clock strictly after `effective_deadline_date` (equality does not expire); extension request allowed on the deadline date; draw amount exactly equal to available balance allowed; half-open inspector-calendar regime (adjacency allowed) checked before the closed property-slot regime (adjacency conflicts); verifying inspection `reported_at` on or after the draw's `created_at` with latest-`reported_at`/earliest-`created_at` tie-break; list ordering `created_at` ASC with insertion-order tie-break (approvals tie-break `approver_role` ASC; ledger in `seq` ASC); LedgerEntry carries only `id`/`created_at` (no `updated_at`/`version`). No pseudocode operators or fuzzy quantifiers anywhere (mechanical scan clean). All 30 error ids, 58 enum/state values, and 7 role names appear exactly as scaffolded. The two forbidden index files were not opened.

## Step 5: Generate Unit Tests — 2026-08-14T13:51:00.000Z

Generation complete and fully audited. The single "scaffold" grep hit is the mandatory C4 tag line itself (the instance's verbatim `name:` from the design yaml), not leakage.

### Summary

**Helpers written (9 files** under `/home/ubuntu/github/CodingPRD/tasks/task_1731_escrow_holdback_repair_escrow/test_helpers/`**):** `types.py` (11 entity TypedDicts — `LedgerEntry` correctly omits `updated_at`/`version` per `common_fields: false` — plus 15 status/role enums), `api_client.py` (33 endpoint methods, one per PRD §4 row), `api_errors.py` (30 error ids + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity assertions + `assert_ledger_invariants` running-balance checker), `factories.py` (7 payload factories, input fields only), `constants.py` (contingency 10–25, extension caps 21/7/45, pagination defaults, fixed clock epoch), `test_users.py` (9 shared party-header constants + 7 `make_<role>_headers` builders — all roles are opaque so no entity-backed threading is needed), `fixtures.py` (tiered composites: file → DRAFT → PENDING → ACTIVE → engagement (bid+select+work order) → verified draws/approvals/payments → verified engagement → extensions/disputes/expire/close), `__init__.py` barrel.

**Tests generated (`test_suite/`: conftest.py + 11 files, 94 test functions, 100 collected with parametrization):**
- **Queue A (Difficulty): 36 tests** — all 18 instances covered with exactly ≥2 tests each (sizing provisional-vs-commitment, NET-vs-GROSS shortfall cap, nested-min extension grants, close split rounding order, work-order rework cycle, approval rejection cycle, close cascade with file bubble-up, approve→pledge cascade, both priority-pair conflicts, both boundary checks, both cross-entity state gates, both interval-overlap regimes, both compensating invariants).
- **Queue B (Corner): 58 tests** — all 57 non-stub instances covered (the extra test is a second `missing_role_header_unauthenticated` variant for unknown role values). All 11 `excluded_because:` stubs were NOT translated; every stub's `difficulty_instance` cross-reference was verified to resolve.

**Instances skipped for PRD-first reasons: none.** Every non-stub instance found verbatim PRD coverage and unique derivability — the PRD explicitly pins the §2.9 precedence ladder (both priority-pair instances), both rounding orders, both interval regimes, and the strict-vs-equal boundaries. One assertion-level relaxation only: corner instance `escrow_file_creation_defaults` asserted `version == 1`, which the PRD does not uniquely derive (§2.5 says version increments on mutation but never states the initial value) — the test keeps the covered claims (201, OPEN, party echo, envelope) and asserts only integer `version`, per the skill's remove-or-relax rule.

**Verification performed:** all files compile; pytest collects 100 tests with zero import errors; every docstring ends with exactly one `Design:` tag resolving to a real instance in the correct rule/section (94/94); every `PRD §` citation survives literal grep of `PRD.md` (0 misses, no ellipses); no `skip`/`skipif`/`xfail` markers exist anywhere.

## Step 6: Generate Implementation — 2026-08-14T13:51:00.000Z

Implementation complete. Summary:

### Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_1731_escrow_holdback_repair_escrow/workspace/implementation/`:

- `start.sh` — reads `$PORT` (default 10000), binds 0.0.0.0, guarded `pip install` (no-op when Flask already present), `exec python3 app.py` in foreground
- `requirements.txt` — flask>=3.0
- `app.py` — Flask app factory, envelope-compliant error handlers (ApiError, 404, 405, HTTPException, catch-all)
- `db.py` — in-memory store (empty dicts at boot, zero seeding) + logical clock (default `2026-08-01T00:00:00Z`, never wall-clock; all timestamps including envelope `api_request_timestamp` read it)
- `errors.py` — all 30 error IDs with exact HTTP statuses
- `response.py` — PRD §2.2 envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields in `meta` for lists)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (7 roles), role-list authorization
- `helpers.py` — ordered input validators, entity lookups, integer round-half-up money math, ledger append with per-holdback `seq`/`running_balance_cents`, derived-field refresh (`work_verified`/`disbursement_frozen`/`closeout_status`, file status bubble-up), serializers (ledger entries omit `updated_at`/`version` per PRD §2.5), pagination (`limit` default 10 clamped 1..100, `offset` default 0)
- `routes/` — 11 modules: clock, files, holdbacks, approvals, bids, workorders, inspections, draws, extensions, disputes, pledges

### Endpoint count: 33/33

All endpoints from the PRD §4 table, including the clock capability. The PRD §2.9 validation ladder is enforced per-endpoint (auth → role → existence → input shape → ownership → OCC 412 → generic state → ordered domain gates → freeze → cardinality → weather → interval occupation (half-open inspector calendar before closed property slot) → verifying inspection → temporal windows → shortfall → closeout). Key contract details implemented: round-half-up sizing at final multiplication only; split rounding pinned in opposite directions (shortfall: buyer first; close waterfall: seller first, residual buyer); amend funding-delta ledger entries (`FUNDING`/`REFUND_TO_SOURCE`); approval staling on amend-from-PENDING; auto-activation; rejection cascade; expire cascade cancelling SUBMITTED draws/PLANNED inspections/PENDING extensions; computed extension grants with 21/7-day caps, 45-day lifetime cap, hard-stop headroom; disposition override on EXPIRED dispute resolution; waterfall closing to exactly zero with file status bubble-up.

### Self-check result

Booted via `bash start.sh` on scratch ports 18731/18732. Verified: 108-check full-lifecycle smoke suite plus a 30-check edge suite — **all pass**, covering the happy path (file → holdback → approvals → bids → selection → inspections → draws → extensions → verification → closing waterfall with exact ledger seq/running balances), the rejection/amend-stale loop, expire cascade, dispute freeze + override, split shortfall pledges with `ERR_SHORTFALL_UNFUNDED` gating, RBAC/auth errors, OCC 412-beats-409 ordering, and pagination. Reboot cycle confirmed: second `start.sh` invocation shows wiped state (404 on prior IDs) and the clock back at the 2026-08-01 default; dependency install correctly skipped on re-boot.

## Step 7: Run Tests and Iterate — 2026-08-14T14:00:00.000Z

All 8 rounds pass 100/100. The loop is complete.

### Summary

- **Iterations run:** 2 full 8-round parallel sweeps (100 tests/round, per-test-server isolation).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1731_escrow_holdback_repair_escrow/test_suite/test_05_draws_and_shortfalls.py` — `TestPayGates::test_double_pay_rejected` called the fixture helper `pay_draw(pair["draw"]["id"])` but `pay_draw` was missing from the module's `test_helpers` import list, so every round failed with `NameError: name 'pay_draw' is not defined` before any assertion executed. The test's assertions themselves are verbatim PRD §3.5 ("paying one already `PAID` or `CANCELLED` is `ERR_INVALID_STATE`" plus the payment side-effect list), so the test was kept at full strength; only the missing import was added.

- **Fixes applied to `implementation/`:** none. The implementation (`app.py`, `db.py`, `errors.py`, `response.py`, `middleware.py`, `helpers.py`, `routes/` — 33/33 endpoints) was already PRD-faithful; the first sweep's sole failure was purely the test-side import bug.

- **Notes:** Round-1 sweep diagnostics: the single failing test failed identically in all 8 rounds (deterministic, not flaky). Interleaved progress lines in the concurrent output initially suggested `test_pay_state_gate_wins_over_fiscal_gate` failures, but the per-round summary lines and all 8 `results.*.json` files confirmed that was stdout interleaving noise — it passed in every round. A pyflakes scan after the fix confirmed no other undefined-name issues anywhere in `test_suite/`. Final sweep: 8/8 rounds, 100/100 passed each, ~138s per round.

## Step 8: Finalize PRD — 2026-08-14T14:05:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1731_escrow_holdback_repair_escrow/workspace/PRD_FINALIZED.md` is a byte-identical copy of PRD.md, which is the correct output for this step.

### Analysis

The sole `<step_7_diff>` item is a **pure test-side import bug**: `test_suite/test_05_draws_and_shortfalls.py::TestPayGates::test_double_pay_rejected` called fixture helper `pay_draw()` without importing it. Verification confirmed:

1. **`pay_draw` always existed in test_helpers** — defined at `test_helpers/fixtures.py:268` and exported from `test_helpers/__init__.py:90`. Sibling module `test_10_ledger_invariants.py:14` already imported it successfully. The failure was a `NameError` before any assertion ran — it reveals nothing about PRD silence or impl behavior.
2. **PRD already pins the asserted behavior** — the test docstring quotes PRD §3.5 verbatim ("paying one already `PAID` or `CANCELLED` is `ERR_INVALID_STATE`" plus the full payment side-effect list), and those sentences exist verbatim in PRD.md §3.5.
3. **Implementation matches PRD §3.5 exactly** — `workspace/implementation/routes/draws.py:138-171` (pay endpoint: PAID/CANCELLED → `ERR_INVALID_STATE`, SUBMITTED → `ERR_DRAW_NOT_APPROVED`, then `ERR_HOLDBACK_NOT_ACTIVE` → `ERR_DISPUTE_FROZEN` → `ERR_SHORTFALL_UNFUNDED`, then `DRAW_DEBIT` negative entry, `total_disbursed_cents` up, `reserved_cents` down, `paid_at` stamped, status → `PAID`), with `trust_balance_cents` reduction via `helpers.py:305` (`hb["trust_balance_cents"] = running`). Also spot-checked the parallel close-waterfall payment path in `routes/holdbacks.py:228-242` — consistent.

No `<step_7_diff>` item corresponds to a PRD silence or PRD/impl mismatch, so no edits were made (per instructions: do not invent edits).

### Summary

- **Line counts**: PRD.md = 268 lines, PRD_FINALIZED.md = 268 lines; **0% delta** (byte-identical, verified via `cmp`).
- **Changes**: none (zero change bullets).
- **Pre-edit search log**: no edits were committed, so no per-edit log entries exist. For completeness, the single diff item's subject (draw payment semantics) was enumerated across all impl paths anyway: `implementation/routes/draws.py:138-171` (pay endpoint), `implementation/routes/holdbacks.py:228-242` (close waterfall pays APPROVED draws), `implementation/helpers.py:287-306` (`append_ledger` trust-balance maintenance), `test_helpers/fixtures.py:268-269` (`pay_draw` fixture), `test_helpers/api_client.py:83` (`pay_draw_request`), and all `pay_draw` callsites in the test suite — all consistent with PRD §3.5 as written, so no wording change was warranted.

## Step 9: Complete PRD — 2026-08-14T14:25:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1731_escrow_holdback_repair_escrow/workspace/PRD_COMPLETED.md` is written, containing exactly six in-paragraph edits over the source. The exhaustive walk covered all 11 route modules, `helpers.py` (validators, serializers, ledger, derived-state), `middleware.py`, `response.py`, `errors.py`, `db.py`, `app.py`, plus cross-checks against INSTRUCTION.md and the test helpers/suite. Everything else — all 31 endpoints, role tables, ladder ordering per route, state machines, rounding formulas, waterfall order, freeze/shortfall semantics, serializer field shapes, ledger invariants — was already uniquely pinned by the PRD.

### Summary

- Source file: `PRD_FINALIZED.md` (268 lines / 46,604 chars) → `PRD_COMPLETED.md` (268 lines / 47,547 chars). Char-delta: **+943**, line-delta: **0** (all edits inline).
- Counts: **6 ambiguity-pins, 0 mismatch-revisions**.

Changes:
- §2.3 Pagination — revise — ambiguity — out-of-range `limit`/`offset` are clamped to the nearest bound (negative offset → 0), unparseable values fall back to the defaults (10/0), rather than rejected — implementation/helpers.py:561-574
- §2.5 Common Resource Properties — revise — ambiguity — `version` starts at 1 on creation; `updated_at` is initialized to the creation timestamp — implementation/helpers.py:282-284
- §2.9 rung 3 (Existence) — revise — ambiguity — the existence check also covers body-carried parent identifiers on creation endpoints (`escrow_file_id` on holdback creation; `holdback_id` on bid/inspection/draw/extension/dispute creation), firing at rung 3 before input-shape validation — implementation/routes/holdbacks.py:54-56, bids.py:22-24, inspections.py:25-27, draws.py:38-40, extensions.py:30-32, disputes.py:36-38
- §3.2 Amendment — revise — ambiguity — amendment also recomputes `effective_deadline_date` as the (possibly updated) `work_deadline_date` plus `granted_extension_days`, and posts no ledger entry when the recomputed amount equals what has been funded (zero delta) — implementation/routes/holdbacks.py:174, 177-181
- §3.7 Disputes — revise — ambiguity — `initiator_role` is stored as the enum token `BUYER`/`SELLER` (not the header spelling `Buyer`/`Seller`) — implementation/routes/disputes.py:58
- §3.8 Closing Waterfall — insert — ambiguity — a remainder of exactly zero appends no disposition entries (step three is skipped) — implementation/routes/holdbacks.py:244

Notable non-edits (deliberately left alone): the 405/unexpected-exception handlers in app.py are transport-level fallbacks outside the PRD's specified error surface (§5's scope is limited to triggers in §2/§3); the draw-approval "verification of record" selection (latest `reported_at`, tie by earliest `created_at`) has no observable field in the implementation, which performs an existence check only — the PRD prose is satisfied; inspection verdicts living in the inspection's `status` field is already pinned by §3.5's "in `PASSED` state" phrasing; extension `decision_note` accept-and-discard is already matched by the PRD's "accepted alongside it" wording.

Pipeline complete: all 9 steps done; final stability sweep 8/8 rounds × 100/100 tests passing.
