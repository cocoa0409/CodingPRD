# Worklog — task_0288_florist_flower_delivery

## Step 1: Create task directory — 2026-06-11T08:48:00.000Z

Used PRE-ASSIGNED path (index-scan skipped per orchestrator instruction; 5 parallel pipelines running). Created `tasks/task_0288_florist_flower_delivery/` and `tasks/task_0288_florist_flower_delivery/workspace/` via `mkdir -p`.

## Step 2: Generate scaffold (EXPERT) — 2026-06-11T08:50:00.000Z

All three files are written, parse cleanly, pass the file-split and envelope checks, and the lint reports `VERDICT: clean lint`. The scaffold was generated purely from the scenario description and the skill specification — no sibling task directories were read. Files: SCAFFOLD.yaml (1593 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1210 lines), SCAFFOLD_CORNER_DESIGN.yaml (1351 lines).

Generated the EXPERT-band scaffold for **task_0288_florist_flower_delivery** into the target directory. All three required files written and lint-clean.

### Structural counts
- **Entities:** 12 — `Customer, DeliveryZone, Arrangement, HolidayWindow, Florist, Order, WireFulfillment, DeliverySlot, Substitution, QualityClaim, RecurringSchedule, ClockState`
- **State machines:** 5 blocks across 4 entities — `Order` carries **two parallel dimensions** (fulfillment_status × payment_status), plus `WireFulfillment`, `QualityClaim` (branching + cyclic), `RecurringSchedule` (cyclic self-loop). Plus 2 `concurrency_rules` (OCC on `Order.version` for book + claim-resolve).
- **Calculations:** 5 — `compute_quote_estimate`, `compute_final_total`, `compute_claim_refund`, `select_fulfilling_florist`, `promote_loyalty_tier`
- **Validations:** 13 (priority-ordered, 8 categories)
- **Endpoints:** 54 (business surface + FK reverse-reachability GETs + `/_clock`, `/_payments`, `/_inject` test-driving endpoints)
- **Errors:** 18
- **Roles:** 4 — `Customer` (entity_backed), `Florist` (entity_backed), `Dispatcher` (opaque), `CatalogAdmin` (opaque) — peer_roles model

### Headline Expert-band difficulty mechanisms
- **Dual-variant pricing on the same Order:** quote-time `estimated_total_cents` (authorized) excludes florist surcharge + substitution deltas; fulfillment-time `final_total_cents` (captured) includes them → deterministic divergence (14300 vs 16000).
- **Pinned evaluation order (mode c):** surge→discount→delivery→wallet-credit, with reordering changing the cents; plus additive discount stacking clamped by `min(.,0.30)` (mode a).
- **Parallel state machine** on Order (fulfillment × payment dimensions evolving on different triggers) and a **branching+cyclic** QualityClaim that spawns a redelivery Order back into the pipeline.
- **Depth-3 cascade:** cancel-BOOKED → release DeliverySlot → RELEASE WireFulfillment → decrement Florist daily load; depth-2 cascade: resolve-REFUND → Order CAPTURED→REFUNDED → wallet credit.
- **Two distinct interval semantics:** zone half-open window capacity (adjacency at shared endpoint does NOT collide) vs florist aggregate per-day capacity (disjoint windows still both consume headroom).
- **Boundary precision** on the same-day cutoff hour (strict `<`) and exact zone-window fill count, on different endpoints.
- **OCC** via `expected_order_version` (412) on book and claim-resolve; **selector policy** ranking florists by `quality_rating DESC, wire_surcharge ASC, created_at ASC` (id strictly forbidden).

### Design files
- §1.8: 9 rules × 2 = **18 difficulty instances**, all formula-derived asserts pre-computed to literals.
- §1.9: 9 sections, **30 active corner instances + 8 `excluded_because` stubs** (all stub refs resolve to real §1.8 instance names).

`scaffold_lint.py` final verdict: **clean lint** (419 calls scanned across §1.8/§1.9, all FK reverse-reachability satisfied).

## Step 3: Copy INSTRUCTION.md — 2026-06-11T08:52:00.000Z

Copied repo-root `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-11T08:56:00.000Z

Generated `workspace/PRD.md` — **279 lines**. Read only SCAFFOLD.yaml (design files withheld).

Major sections: §1 Introduction (wire-service floral marketplace, dual-variant pricing, parallel fulfillment/payment state machine); §2 Global Specifications (RBAC, §2.2 envelope, pagination, common properties, money/round-half-up, cascading side effects, OCC, nested retrieval, validation ordering, simulated clock); §3 Business Logic (8 scattered subsections: catalog setup, draft+quote estimate formula, same-day cutoff + holiday override, authorize/book/wire-selection, accept/dispatch/final-total + loyalty, cancellation/release, claims/refund/redelivery, recurring schedules); §4 Endpoint table (55 endpoints, 4 cols); §5 Error catalogue (18 error IDs).

Hard contracts: Field coverage PASS (72/72), Rule coverage PASS (13 validations + 2 OCC + all state transitions + 5 calculations + side effects + sibling-branch symmetry), Path purity PASS (§3 has 0 path/method tokens).

## Step 5: Generate unit tests — 2026-06-11T09:20:00.000Z

test_helpers/ (9 files): types.py, api_client.py, api_errors.py (18-error catalog), assertions.py, factories.py, constants.py, test_users.py (entity-backed customer/florist headers + opaque operator constants), fixtures.py (composite order-lifecycle chains), __init__.py.
test_suite/ (conftest + 10 test files): 67 test functions, all compile clean.

Coverage: Queue A (Difficulty) 18/18 instances translated, each ≥2 tests (one has 3), 0 skipped. Queue B (Corner) 30/30 non-stub instances translated, each ≥1 test, 0 gaps; 8 `excluded_because` stubs not translated (all 8 cross-refs resolve to real difficulty instances). Skips: none — every design instance passed the PRD-first two-condition filter.

Audits passed: every docstring ends with exactly one verbatim `Design:` tag (0 untagged/dual-tagged/typo/stub-tagged); all 99 quoted PRD citation segments byte-verbatim; no skip/skipif/xfail; no scaffold/§1.x/test_recipe leakage; every api.<method> and test_helpers import resolves. Pre-computed expected values (estimate 14300, final 16000, refunds 4350/2900/5800, surge 15800/10800, clamped discount 6200/7400, dispatch capture 5800) re-derived with round-half-up.

## Step 6: Generate implementation — 2026-06-11T09:20:00.000Z

Files: start.sh (guarded dep install + `exec python3 app.py`), requirements.txt (Flask==3.0.3), app.py (blueprint registration, envelope error handlers, binds 0.0.0.0:$PORT default 10000), db.py (in-memory store), errors.py (18 error IDs + HTTP codes), response.py (envelope helpers), helpers.py (pagination, round_half_up via Decimal, common-field stamping), middleware.py (X-User-ID/X-User-Role auth + 4 roles + RBAC), services/clock.py (simulated clock + date math), services/pricing.py (5 calculations + capacity/window counters), routes/ (catalog, orders, fulfillment, claims, schedules, operators — 50+ endpoints).

Storage: in-memory only, single module-level Store in db.py, one dict per entity collection keyed by UUID + singleton clock. Internal `_seq`/`_authorized_amount_cents` stripped from responses. Parallel Order state machine (fulfillment + payment) shares one version; cascades atomic, bump version. start.sh: set -euo pipefail, cd script dir, install deps only if import flask fails, exec python3 app.py, reads $PORT, binds 0.0.0.0 foreground threaded.

No seeding: Store.reset() initializes empty dicts; nothing inserted at import/boot; verified empirically (customer gone after restart). ~60 end-to-end self-check assertions across 4 smoke suites all pass.

## Step 7: Run tests and iterate to green — 2026-06-11T09:55:00.000Z

All tests pass across two consecutive clean 8-round parallel sweeps (16 rounds, 67/67 every round). Orchestrator re-confirmed independently with a fresh 8-round sweep: all 8 rounds passed=67 total=67 failed=0; results.{1..8}.json persisted.

**Iterations run:** 6 sweeps (1 baseline + 5 fix/verification). Final state: two consecutive clean 8-round parallel sweeps, 67/67 on every round.

**Tests deleted:** None. Every test traced to verbatim PRD prose and was uniquely derivable.

**Fixes applied to test_helpers/:** None. The helpers (fixtures, factories, role-header builders) were all PRD-faithful.

**Fixes applied to implementation/:**

1. **`routes/schedules.py` → `emit_schedule()`** — Reordered the two guard checks so the `occurrences_remaining < 1` (exhausted) check precedes the `status != "ACTIVE"` (state) check. *Why:* PRD §3.8 states verbatim: *"an emit (or a resume) against a schedule whose `occurrences_remaining` is 0 is rejected with `ERR_SCHEDULE_EXHAUSTED`."* Because a schedule auto-pauses to `PAUSED` the instant `occurrences_remaining` hits 0, the exhausted-emit case ALWAYS coincides with a non-ACTIVE status. The old ordering let the generic `ERR_INVALID_STATE` preempt the PRD's dedicated `ERR_SCHEDULE_EXHAUSTED`, making that PRD clause unreachable. Fixed `test_schedule_emit_exhausted_auto_pauses`.

2. **`app.py` → server entry point** — Replaced `app.run()` with a self-bound listening socket (`SO_REUSEADDR` + `SO_REUSEPORT`, bounded bind-retry) handed to `werkzeug.serving.make_server(..., fd=...)`. *Why:* Under the 8-round phase-locked sweep, the runner SIGKILLs and immediately re-spawns the server on the same port before every test; lingering/TIME_WAIT socket caused intermittent "Address already in use" crashes. SO_REUSEPORT + retry lets the fresh process bind through the teardown window. Not entity state — the in-memory store still boots empty.

3. **`start.sh` → dependency guard** — Gated the dependency check behind a `.deps_ready` filesystem sentinel so steady-state reboots `exec python3 app.py` directly without spawning an extra `python3 -c "import flask"` interpreter. *Why:* Minimizes per-reboot process-spawn contention under the phase-locked herd. The sentinel is a dependency-build marker only; the in-memory store still starts empty on every boot.

**Key finding:** The only genuine logic bug was the emit error-precedence (#1). Fixes #2 and #3 hardened the boot/restart path to withstand 8-round host contention (confirmed: a single isolated round passed 67/67 cleanly throughout).

## Step 8: Finalize PRD — 2026-06-11T10:05:00.000Z

Produced `workspace/PRD_FINALIZED.md`. Line counts: PRD.md = 279, PRD_FINALIZED.md = 279 (within-paragraph insertion on line 191, 0% line-count delta, ~0.36% of lines touched).

**Change (1):** §3.8 (Recurring Schedules, emit) — insert — Pinned that for an emit, the `occurrences_remaining`-is-0 exhaustion check (`ERR_SCHEDULE_EXHAUSTED`) is evaluated **before** the `status`-is-`ACTIVE` state check (`ERR_INVALID_STATE`), so emitting against an exhausted, auto-paused schedule yields `ERR_SCHEDULE_EXHAUSTED` — implementation/routes/schedules.py:120-124.

**Disposition of Step 7 items:** #1 (emit guard reorder) = genuine PRD silence on error precedence → one minimal clarifying clause. #2 (app.py self-bound socket) = pure boot/infra, no PRD surface → no edit. #3 (start.sh dependency sentinel) = pure boot/infra → no edit.

**Pre-edit search log (NO-NEW-MISMATCH):** Subject = precedence between exhaustion check and state check on schedule transitions. Enumerated all schedule lifecycle handlers — emit_schedule (exhausted-first, the edit site), resume_schedule (state-first, DELIBERATELY opposite order), pause/cancel (no exhaustion check). Wording scoped with explicit "For an emit," qualifier to avoid a universal claim that would contradict resume_schedule's state-first ordering. All `SCHEDULE_EXHAUSTED`/`occurrences_remaining`/`PAUSED`/`invalid_state` references live solely in routes/schedules.py.

## Step 9: Complete PRD — 2026-06-11T10:12:00.000Z

Produced `workspace/PRD_COMPLETED.md` (full PRD-vs-implementation scan, starting from PRD_FINALIZED.md). Line counts: 279 → 279 (in-paragraph edits only); 47,903 → 49,684 chars (+1,781). Counts: 4 ambiguity-pins, 1 mismatch-revision.

**Changes:**
- §3.2 (Drafting) — insert — ambiguity — Pinned freshly drafted order initializes `estimated_total_cents`, `final_total_cents`, `wallet_credit_applied_cents` to 0 and `is_same_day` to false — routes/orders.py:93-96.
- §3.4 (Authorizing) — insert — ambiguity — Pinned error split: non-`UNPAID` payment → `ERR_INVALID_STATE`, `UNPAID` but non-`QUOTED` fulfillment → `ERR_PRECONDITION_NOT_MET`; force-authorize operator rejects non-`UNPAID` with `ERR_INVALID_STATE` — routes/orders.py:210-213, routes/operators.py:52-53.
- §3.5 (Substitutions) — insert — ambiguity — Pinned recording a substitution validates only FK existence, Florist ownership, and policy; imposes NO order fulfillment_status precondition and does not require the applying florist to be the assigned one — routes/fulfillment.py:72-126.
- §3.8 (Recurring) — insert — ambiguity — Pinned emitted order's unstated fields: `occasion`=`GENERAL`, `card_message`=`""`, `source_order_id`=null, `apply_wallet_credit`=false — routes/schedules.py:134-139.
- §3.1 (Florist) — revise — mismatch — Pinned florist-registration validation ordering: range checks (`daily_capacity`/`quality_rating`/`wire_surcharge_cents` → `ERR_VALIDATION_RANGE`) run BEFORE the `covered_zone_id` existence check, contradicting §2.8–§2.9's general existence-before-body ordering — routes/catalog.py:260-268.

Left unchanged (verified consistent or non-observable): list sort/pagination, holiday-window overlap tie-break, surge/discount/delivery/wallet pricing order, final-total floor-at-0 + wallet snapshot, OCC on book/resolve, cancellation cascades, loyalty thresholds, claim refund fractions/floors/cap, resume-vs-emit ordering; clock-unset quoting edge unpinned but never exercised.

---

## Pipeline complete — task_0288_florist_flower_delivery

All 9 steps done. Final 8-round parallel sweep: 67/67 every round (results.{1..8}.json persisted). Artifacts: SCAFFOLD.yaml + 2 design files, PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ (9 files), test_suite/ (conftest + 10 files, 67 tests), workspace/implementation/ (Flask, in-memory).
