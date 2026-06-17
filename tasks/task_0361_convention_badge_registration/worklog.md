# Worklog — task_0361_convention_badge_registration

Scenario: 361. Convention & Badge Registration (Comic-Con style): ticket type/tier & day pass, capacity & waitlist/lottery, badge issuance & RFID, session/panel reservation, exhibitor/vendor booth, group & VIP, transfer/refund, on-site pickup/print

Difficulty: Expert

## Step 1: Create task directory — 2026-06-14T18:24:40.000Z

Used pre-assigned directory `tasks/task_0361_convention_badge_registration` (slot pre-allocated; no scan/auto-increment). Confirmed `workspace/` exists. Project root: `/Users/uni/Desktop/吉/project/custom_prd_bench`.

## Step 2: Generate scaffold (Expert difficulty) — 2026-06-14T18:45:00.000Z

Generated a complete Expert-tier scaffold for **Convention & Badge Registration (Comic-Con style)** at `tasks/task_0361_convention_badge_registration/`:

- `SCAFFOLD.yaml` (§1.0–§1.7) — 1533 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8) — 1205 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9) — 1841 lines

**`scaffold_lint.py` verdict: clean lint** (51 endpoints, 12 entities, 18 §1.8 instances, 38 §1.9 instances, 497 calls scanned — all conform; all FKs reverse-reachable).

### Scaffold contents
- **Complexity profile**: primary archetype `quota_allocation` + secondary `workflow_orchestration`; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, derived_field_reconciliation; topology `flat`; shape `branching`; role model `peer_roles`; `immediate` consistency.
- **Entities (12)**: Convention, TicketType, Attendee, Order, TicketLineItem, Badge, Session, SessionReservation, WaitlistEntry, Exhibitor, Booth, BoothBooking.
- **State machines (5)**: Order (branching: PAID→REFUNDED vs DRAFT/PENDING→CANCELLED), Badge (parallel `status` × `rfid_status` dimensions), SessionReservation (WAITLISTED↔CONFIRMED promotion cycle), WaitlistEntry (ENTERED→WON/LOST fork), BoothBooking. Plus 2 OCC `concurrency_rules` (Convention.version on pay, Session.version on reserve).
- **Calculations (7)**: order_pricing (tiered group discount + per-line-then-sum rounding + fee cap), order_refund (provisional/final dual-variant), booth_charge (estimated/actual dual-variant), waitlist_priority (weighted scoring w/ group cap), lottery_allocation (all-or-nothing waterfall), capacity_counters, onsite_window.
- **Validations (18, priority-ordered)**, **Errors (24)**, **Roles (5)**: ConventionAdmin/RegistrationAgent (opaque), Attendee/Exhibitor (entity_backed), Anonymous.
- **Endpoints (51)** including one `/_clock/set` test-driving endpoint and reverse-reachability GETs.

### §1.8 difficulty design — 18 instances (2 per rule × 9)
dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade (depth-3 refund + depth-3 pay cascades), priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap (Session half-open vs Booth buffered-closed), compensating_invariant.

### §1.9 corner design — 38 active instances + 3 `excluded_because` stubs
Covering entities, state-machine invalid-from/terminal-lockdown/initial-state/valid-transition, calculations, validation→error for every error code, endpoints (pagination envelope, sub-resource lists), RBAC denials/ownership, OCC stale+success, cascade, and consistency-model.

## Step 3: Copy shared files — 2026-06-14T18:46:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-14T18:49:00.000Z

Generated PRD at `workspace/PRD.md` — 287 lines, 5 top-level sections (Introduction, Global Specifications, Business Logic & Workflows, Endpoint Definitions, Error Code Catalogue).

**Hard Contracts — all PASS:**
- Contract 1 (field coverage): 60/60 entity fields, 47/47 endpoint inputs+path params, 15/15 query params.
- Contract 2 (rule coverage): 2/2 OCC rules, all state-machine states (Order, Badge, SessionReservation, WaitlistEntry, BoothBooking), 24/24 error ids, all enum values, all calculation constants embedded, validation ordering in §2.9.
- Contract 3 (path purity in §3): 401 backtick spans scanned, 0 path/method tokens.

§4 endpoint table: 51 rows. §5 error table: 24 rows.

**Confirmation:** SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml were NOT read.

## Step 5: Generate unit tests — 2026-06-14T19:09:00.000Z

Generated complete test infrastructure from the two design indices only (no freelance walk of SCAFFOLD.yaml).

**test_helpers/ (9 files):** types.py, api_client.py (51 endpoint methods + set_clock), api_errors.py (24 errors + HTTP status map), assertions.py, factories.py, constants.py, test_users.py (opaque role constants + make_attendee_headers/make_exhibitor_headers), fixtures.py, __init__.py.

**test_suite/ (7 test files + conftest.py): 74 test functions.**

**Design-instance consumption:**
- Difficulty (queue A): 18/18 instances consumed, 2 tests each (36 tests).
- Corner (queue B): 38/38 non-stub instances consumed, ≥1 test each (38 tests). 3 `excluded_because` stubs not translated.
- 0 instances skipped — all passed PRD-first two-condition filter. `lottery_not_won_blocks_order_under_sold_out` used `validate_error_is_one_of([ERR_LOTTERY_NOT_WON, ERR_POSTURE_BLOCKED])` per error-precedence silence pattern.

**Verification:** all modules byte-compile + import; every api.<method> resolves; every docstring ends with one `Design:` tag → real instance + verbatim ≥8-word PRD citation; no skip/skipif/xfail; no scaffold leakage.

## Step 6: Generate implementation — 2026-06-14T19:09:00.000Z

Generated Python + Flask implementation at `workspace/implementation/` (23 files).

**Files:** start.sh, app.py, requirements.txt (flask==3.0.3), db.py (in-memory dict store + monotonic sequence), clock.py (pinnable logical clock), util.py (round_half_up via Decimal), errors.py (24-entry catalogue), response.py (envelope), middleware.py (auth/authz), common.py (common fields, touch, pagination, validators), routes/ (9 blueprints), services/ (calc.py, state.py, lookup.py).

**Endpoint count: 51 (matches PRD §4 exactly).**

**start.sh / storage:** reads $PORT (default 10000), binds 0.0.0.0, foreground via `exec python3 app.py`; pip install guarded on `import flask` to avoid per-test reboot contention. In-memory dicts only, empty on every boot — no seeding/preload/hardcoded entities.

**Verification:** 71-check smoke suite passed (envelope, pagination, order workflow, badge lifecycle, reservation+promotion cascade, lottery, booth overlap+dual-variant charge, temporal gates, OCC 412, validation precedence). Per-line-then-sum rounding confirmed (1581 not 1582).

## Step 7: Run tests and iterate — 2026-06-15T07:30:00.000Z

All 8 parallel rounds pass 74/74. Clean sweep.

- **Iterations run:** 2 (initial sweep surfaced 1 consistent failure; second sweep after fix was clean).

- **Tests deleted:** None. No test failed the STEP 1 PRD-coverage or unique-derivability check.

- **Fixes applied to `test_helpers/`:** None.

- **Fixes applied to `test_suite/`:**
  - `test_03_cascades_and_capacity.py` — `test_lottery_not_won_blocks_order_under_sold_out`: reordered the setup so attendee Y submits its order **while the convention is still OPEN** (before X's purchase flips it to `SOLD_OUT`). The original setup paid X first (flipping posture to `SOLD_OUT`), then called `create_submitted_order` for Y — which correctly failed with `ERR_POSTURE_BLOCKED` because PRD §3.3 line 136 states "Submission is permitted only when the order has at least one line item and the convention's `posture` is `OPEN`." This was a STEP 2 test-setup bug: the precondition (a `PENDING_PAYMENT` order for Y under `SOLD_OUT`) is only reachable by submitting under `OPEN` first, then having X flip posture, then attempting Y's pay. The assertion itself (`validate_error_is_one_of([ERR_LOTTERY_NOT_WON, ERR_POSTURE_BLOCKED])` on the pay, order remains `PENDING_PAYMENT`) was untouched and traces verbatim to PRD §3.4 line 142.

- **Fixes applied to `implementation/`:** None. The submit-gating (`posture != OPEN → ERR_POSTURE_BLOCKED`) and pay-gating (`SOLD_OUT` without `WON` waitlist entry → `ERR_LOTTERY_NOT_WON`) in `routes/orders.py` were already faithful to PRD §3.3 / §3.4; the failure was a test-setup ordering bug, not an implementation defect.

Final state: 8/8 parallel rounds report passed==total (74/74).

## Step 8: Finalize PRD — 2026-06-15T07:35:00.000Z

Done. PRD_FINALIZED.md is a verbatim copy of PRD.md — no edits.

**Line counts:** PRD.md = 287 lines; PRD_FINALIZED.md = 287 lines. Delta = 0 lines (0.0%). Files are byte-identical.

**Changes:** None. PRD_FINALIZED.md is a verbatim copy of PRD.md.

**Rationale:** The sole `<step_7_diff>` item is explicitly a pure `test_suite/` setup-ordering fix (`test_03_cascades_and_capacity.py :: test_lottery_not_won_blocks_order_under_sold_out`) with 0 implementation fixes, 0 test deletions, and 0 test_helpers fixes. Both behaviors it touches are already uniquely determined by PRD.md, so there is no PRD silence or PRD/impl mismatch to pin.

**Per-edit pre-edit search log** (no edits made; investigation log for the single diff item):

- **(a) Subject identified:** The interaction of order *submission* (posture must be OPEN), order *payment under SOLD_OUT* posture (requires a WON waitlist entry → `ERR_LOTTERY_NOT_WON`), and the posture flip to SOLD_OUT at pay time.
- **(b) Impl paths enumerated / read:**
  - `routes/orders.py:184-186` (`submit_order`): raises `ERR_POSTURE_BLOCKED` when posture != OPEN → matches PRD §3.3 line 136.
  - `routes/orders.py:225-237` (`pay_order` posture gating): CLOSED → `ERR_POSTURE_BLOCKED`; SOLD_OUT without WON entry → `ERR_LOTTERY_NOT_WON` → matches PRD §3.4 line 142 verbatim.
  - `routes/orders.py:286-287` (`pay_order` SOLD_OUT flip): matches PRD §3.4 line 144.
  - `routes/waitlist.py:36-42` (`create_waitlist_entry`): duplicate ENTERED → `ERR_DUPLICATE_WAITLIST`; CLOSED → `ERR_POSTURE_BLOCKED` → matches PRD §3.8 line 192.
  - `test_helpers/fixtures.py:101-116` (`create_submitted_order` / `create_paid_order`): confirmed the fixture chain submits-then-pays.
- **(c) Wording adjustment:** None. PRD §3.3 line 136 and §3.4 line 142 already uniquely determine the implicated behaviors.

This zero-edit result is the valid, expected outcome the Method anticipates for a pure fixture/test-ordering bug.

## Step 9: Complete PRD — 2026-06-15T07:45:00.000Z

Full PRD-vs-implementation completeness scan. 5 edits applied (4 ambiguity-pins, 1 mismatch-revision), all in-paragraph.

**Source vs. completed file:**
- `PRD_FINALIZED.md`: 287 lines, 45,011 chars
- `PRD_COMPLETED.md`: 287 lines, 45,687 chars
- Char delta: +676 (no line-count change; all edits are in-paragraph inserts/revisions)

**Counts:** 4 ambiguity-pins, 1 mismatch-revision

**Changes (one bullet each):**
- §2.9 Validation Ordering — revise — mismatch — PRD stated authorization (incl. ownership) is checked *before* existence; impl resolves path/body existence first, then compares the owning FK, so the ownership sub-check is pinned to occur *after* existence resolution — `routes/orders.py:42-46`, `routes/sessions.py:79-83`, `routes/booths.py:110-114`
- §3.3 Ordering and Pricing — insert — ambiguity — PRD said submit is "permitted only when posture is OPEN" but never named the error for non-OPEN posture; pinned to `ERR_POSTURE_BLOCKED` (covers SOLD_OUT and CLOSED) — `routes/orders.py:185-186`
- §3.4 Payment/Refunds (cancel) — insert — ambiguity — PRD described order cancel without naming the resulting state; pinned the terminal state to `CANCELLED` — `routes/orders.py:328-329`
- §3.4 Payment/Refunds (refund-quote) — insert — ambiguity — PRD called the quote a "read" that writes `provisional_refund_cents` but was silent on whether that write is a versioned mutation; pinned that the quote refreshes `updated_at` and increments `version` by one — `routes/orders.py:307-308`
- §3.5 Badge Lifecycle (print) — insert — ambiguity — PRD required print to find `PICKED_UP` + `rfid_status ENCODED` but never named the error when those preconditions fail; pinned to `ERR_INVALID_STATE` — `routes/badges.py:83-87`

**Notes on what was checked and left unchanged (PRD already pins or impl matches):** pay-time validation ordering (posture→tier→capacity→OCC), lottery sort/tie-break, group-discount tiers and per-line-then-sum rounding, refund penalty schedule, on-site/refund window boundaries, OCC error codes/HTTP statuses, booth buffer overlap (closed-interval), estimated/actual booth charge recompute, capacity-counter recompute from authoritative rows, self-registration role gating (§4 table), `expected_session_version` missing→`ERR_INVALID_REQUEST` vs mismatch→`ERR_STALE_SESSION_VERSION` (covered by §2.7+§3.9), and pickup/transfer/void/waitlist error codes. `amount_paid_cents` persisting unchanged through refund was judged already implied by §3.3's "amount captured at payment" framing and left as-is.
