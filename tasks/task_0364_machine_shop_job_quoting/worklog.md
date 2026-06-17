# Worklog — task_0364_machine_shop_job_quoting

## Step 1: Create task directory — 2026-06-15T02:33:52.000Z

Created `tasks/task_0364_machine_shop_job_quoting/` and `tasks/task_0364_machine_shop_job_quoting/workspace/` (directory pre-allocated by orchestrator; no auto-scan of ./tasks/). Verified `./INSTRUCTION.md` and `./skills/` present.

## Step 2: Generate scaffold (Expert difficulty) — 2026-06-15T02:56:30.000Z

Those were pre-allocated by the orchestrator (created at 10:33, before my work). They're outside my task scope. My three required artifacts are in place and lint-clean.

The scaffold is complete and fully self-consistent. Here is my summary.

## Summary

Generated three Expert-difficulty scaffold artifacts for **task_0364_machine_shop_job_quoting** (Machine Shop / Job Shop Quoting & Production). All three files pass `scaffold_lint.py` with **`VERDICT: clean lint`** (581 calls scanned across §1.8+§1.9, all conform to §1.5; all 14 FKs reverse-reachable).

**Complexity profile:** `workflow_orchestration` × `pricing_engine`, flat/graph topology, branching state-machine shape, peer-roles RBAC, immediate consistency. Layers: optimistic concurrency, cascading side effects, dual-variant calculation, rate/threshold triggers, derived-field reconciliation.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **12 entities**: RFQ, PartLine, Quote, RoutingOp, WorkOrder, MaterialLot, LotAllocation (M:N junction), MachineSlot, Inspection, InspectionStation (config, `common_fields:false`), Shipment, Invoice.
- **8 state machines**: Quote (cyclic reject→reopen revision loop), WorkOrder (branching fork-join with compensation cascade), Inspection (three-way accept/rework/scrap branch), RFQ/RoutingOp/Shipment/Invoice/MachineSlot — with system auto-transitions and bubble-up/cascade-down side effects.
- **6 calculations**: tiered-margin quote estimate (round-per-op-then-sum pinned), realized work-order actual cost (ACTUAL variant, no markup/margin), FIFO waterfall lot allocation, on-time/liquidated-damages penalty (capped threshold), invoice total (subtotal+tax−penalty credit), first-pass yield. All literal values pre-computed in Python.
- **12 ordered validations** (auth→authz→existence→request→state→OCC→referential→safety→temporal→constraint→fiscal), **25 errors**, **5 roles** (ShopAdmin opaque superset + Estimator/Scheduler/MaterialController/Inspector peers), **56 endpoints**, **2 concurrency rules** (OCC on WorkOrder.version at release, Quote.version at approve; 412).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** 9 rule_ids × 2 instances = **18 instances**, each with a structured `setup_api_calls`/`trigger`/`assert` recipe and a falsifiable differentiation clause (dual-variant on different entity domains; combinatorial modes (a) waterfall and (b) rounding-order; cyclic vs branching machines on different entities; depth-3 WO-cancel and depth-2 RFQ-cancel cascades; two distinct error-category priority pairs; margin-tier boundary at exactly 50000 and zero-divisor yield edge; WorkOrder→Quote and Inspection→WorkOrder cross-entity gates; half-open MachineSlot vs buffered-closed station overlap; material-unit vs finished-part conservation invariants).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **41 full corner instances + 5 `excluded_because` stubs** across 8 taxonomy sections (entities, state_machines, calculations, validations, rbac, errors, cross_cutting_complexity_layers, consistency_model), covering creation/defaults/computed-fields/not-found/required-field/enum/range checks, invalid-from and terminal-lockdown rejections, precondition-enforcement errors, RBAC denials, OCC stale-version (412), and all remaining triggerable error codes.

All 64 instance names are unique across both design files; all `grounds` references resolve to declared §1.1–§1.7 elements; no forbidden concurrency vocabulary; no id-based business decisions (waterfall uses `received_at ASC, created_at ASC`); no unresolved formula expressions in asserts.

## Step 3: Copy shared files — 2026-06-15T02:56:55.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0364_machine_shop_job_quoting/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-15T03:02:50.000Z

The PRD is complete and all three hard contracts pass. Here is the summary.

## PRD Generation Complete

Generated `workspace/PRD.md` for the **Machine Shop Job Quoting API** — a quote-to-cash production pipeline (RFQ → Quote → WorkOrder → scheduling/material/inspection → Shipment → Invoice). 309 lines, ~7,070 words.

### Section structure
- **§1 Introduction** — 3 paragraphs framing the estimate-vs-actual cost tension.
- **§2 Global Specifications** (10 subsections): 2.1 RBAC + opaque-identity translation for all 5 roles; 2.2 fixed verbatim response envelope; 2.3 pagination; 2.4 flat-topology URL addressing + left-to-right path validation; 2.5 common resource properties (incl. InspectionStation as the `common_fields:false` exception, no `updated_at`/`version`); 2.6 hierarchical consistency / auto-transitions; 2.7 precision & rounding; 2.8 OCC; 2.9 validation precedence (12-step ordering); 2.10 cost-engine principles.
- **§3 Business Logic** (8 subsections): intake, estimating, work-order/material release, CNC scheduling, QC/disposition/yield, delivery/penalties, billing, read/filter.
- **§4** 58-row endpoint table. **§5** 25-error catalogue.

### Coverage
- Entities: all 12. Endpoints: all 58. Errors: all 25. Roles: all 5. State machines: all 8 entities. Calculations: all 6 (rates 180/320/150, margin tiers 35/25/18 at 50000/200000, penalty 50/cap 20000, tax 8.25%, buffer 15). OCC: both rules.

### Hard Contract Reports: Field coverage PASS · Rule coverage PASS · Path purity PASS (375 tokens, 0 path/method leaks).

## Step 5: Generate unit tests — 2026-06-15T03:21:00.000Z

Generation complete. Here is the summary.

## Summary

Generated complete test infrastructure for `task_0364_machine_shop_job_quoting` (Expert-band Machine Shop / Job Quoting PRD).

### test_helpers/ (9 modules)
- `types.py` — 11 status enums, domain value enums, role enum, and 12 entity TypedDicts. InspectionStation correctly omits `updated_at`/`version` (it's `common_fields: false`).
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (all 57 endpoints).
- `api_errors.py` — `ApiErrorId` enum (25 errors) + HTTP status map, registered with the framework.
- `assertions.py` — per-entity assertions plus a material-conservation invariant checker.
- `factories.py` — one payload factory per entity (input fields only).
- `constants.py` — machine rates, margin tiers, penalty/tax constants, fixed not-found UUID.
- `test_users.py` — five opaque peer-role header constants (no entity_backed roles, so no per-instance builders — correct per PRD §2.1).
- `fixtures.py` — layered composite helpers (intake → priced/approved quote → allocated/released/in-process WO → inspection → ship/invoice), culminating in `setup_completed_wo_ready_to_ship`.
- `__init__.py` — barrel export.

### test_suite/ (conftest + 9 test files, 78 test functions)
Files grouped by domain concern: intake, quote pricing, quote/RFQ lifecycle, material allocation, WO release/OCC, inspection/disposition, scheduling/cancel cascade, delivery/billing, RBAC/referential.

### Coverage
- **Queue A (Difficulty):** all 18 instances translated, each with ≥2 tests (36+ tests). 0 skipped — PRD §2.9 explicitly numbers precedence. All literal expected values recomputed against PRD formulas (extended 59750, actual 66220, penalty 1350, cap 20000, tier @ 50000).
- **Queue B (Corner):** all 41 non-stub instances translated (≥1 test each). The 5 `excluded_because:` stubs NOT translated; all 5 cross-references resolve to real difficulty instances.
- **Skipped instances:** none.

### Audits passed
- Every test docstring carries exactly one verbatim `Design: Difficulty/...` or `Design: Corner/...` line; no orphan/dual/untagged tags.
- C1 verbatim check: every citation has a ≥8-word run matching PRD.md.
- No `pytest.mark.skip`/`skipif`/`xfail`; no scaffold/table references. All files compile; pytest collects all 78 tests.

## Step 6: Generate implementation — 2026-06-15T03:21:00.000Z

NOTE (orchestrator): the Step 6 subagent's transport dropped on a socket error during its final summary-return, so no verbatim subagent summary is available. However, all implementation files had already been written to disk before the drop. Orchestrator verification:
- Files: `app.py`, `calculations.py`, `db.py`, `errors.py`, `helpers.py`, `middleware.py`, `response.py`, `services.py`, `requirements.txt` (Flask==3.0.3), `start.sh`, and `routes/` (rfqs, quotes, work_orders, material, machine_slots, inspections, shipments — Invoice endpoints live in shipments.py + work_orders.py).
- Route count: **56** `@bp.route` decorators (matches scaffold's 56 endpoints).
- Stack: Python + Flask, in-memory dict storage (`db.py`), NO startup seeding.
- `start.sh`: cd's to its dir, conditionally pip-installs only when flask missing (avoids 8-round concurrent install contention), `exec python3 app.py` binding `0.0.0.0` on `$PORT` (default 10000), foreground.
- Boot smoke test PASS: server boots clean, `GET /rfqs` returns proper array envelope (`response_type:array`, pagination meta), `POST /rfqs` returns structured error envelope. In-memory store starts empty.
- Any remaining behavioral bugs (e.g. RBAC role-to-operation mappings) are deferred to Step 7's diagnostic loop.

## Step 7: Run tests and iterate (8-round parallel sweep) — 2026-06-15T11:42:27.000Z

NOTE (orchestrator, resume): the stale on-disk `results.*.json` from the previous interrupted run showed passed=0/total=78 ("could not be restarted" on every test). Pre-flight verification before spawning the Step 7 subagent established this was transient 8×-concurrent boot contention (boot latency exceeded the runner's 15s restart-poll window under the prior sweep's load), not a logic bug: a single clean harness round passed 74/78. The Step 7 fix subagent then drove the loop to all-green. Final on-disk verification: all 8 `results.{1..8}.json` show passed=76, failed=0, errors=0, total=76. Verbatim subagent summary follows.

- **Iterations run:** 2 fix-iterations (sweep 1 = baseline 74/78; sweep 2 = 75/76 after first fix batch revealed a self-inflicted setup bug; sweeps 3–4 = 76/76). Plus 1 infra-contention re-run wedge (see note below).

- **Final sweep:** 8/8 rounds passed, 76/76 tests each (confirmed on two consecutive all-green 8-round parallel sweeps; total dropped from 78 → 76 due to two deletions).

- **Tests deleted:**
  - `test_07_scheduling_and_cancel_cascade.py::test_wo_cancel_cascade_releases_slot_and_reverts_op` — **STEP 1b non-unique-derivability (PRD internal contradiction)** — drove from `Design: Difficulty/transitive_cascade/wo_cancel_cascade_depth3_alloc_lot_and_slot_op`. PRD §3.3 defines the slot-release/op-revert cascade on `RELEASED → CANCELLED` and says a WO "may be cancelled ... while it is still PLANNED or RELEASED", but PRD §3.4 ("The first time any routing operation of a work order's quote reaches SCHEDULED, the work order itself bubbles up RELEASED → IN_PROCESS") makes a `BOOKED` slot / `SCHEDULED` op impossible on a still-`RELEASED` WO. A faithful PRD reader rejects the cancel of the (necessarily `IN_PROCESS`) WO this test builds with `ERR_INVALID_STATE` (§2.9 rule 5), never reaching the slot/op revert. The asserted slot=`RELEASED`/op=`PLANNED` outcome is not uniquely determined.
  - `test_09_rbac_and_referential.py::test_cancel_released_wo_after_disposition_rejected` — **STEP 1b non-unique-derivability (PRD internal contradiction)** — drove from `Design: Corner/state_machines/cancel_released_wo_after_disposition_rejected`. PRD §3.3 refuses cancel of a `RELEASED` WO with a `DISPOSITIONED` inspection via `ERR_WO_ALREADY_INSPECTED`, but PRD §3.5 gates disposition on "the work order must be `IN_PROCESS`" — so a `RELEASED` WO can never carry a `DISPOSITIONED` inspection. A faithful reader rejects the cancel of the `IN_PROCESS` WO the test builds with `ERR_INVALID_STATE` (§2.9 rule 5), never reaching the `ERR_WO_ALREADY_INSPECTED` branch. A clarifying deletion-comment block replaced the function in-file.

- **Fixes applied to test_suite/:**
  - `test_03_quote_rfq_lifecycle.py::test_cancel_submitted_rfq_with_approved_quote_rejected` — rewrote setup to build a **two-part-line** SUBMITTED RFQ and approve only the first part line's quote — the only PRD-faithful way to keep the RFQ in `SUBMITTED` while a quote is `APPROVED`, since PRD §3.2 bubbles `SUBMITTED → QUOTED` only when *every* part line has an approved quote (the old single-part-line `create_approved_quote` fixture bubbled the RFQ to `QUOTED`, so cancel correctly hit `ERR_INVALID_STATE` instead of the asserted `ERR_RFQ_HAS_APPROVED_QUOTE`). Added an inline `assert rfq_now["status"] == "SUBMITTED"` precondition guard, and captured the **post-price** quote version for the approve OCC call (`expected_quote_version` must be the version after pricing, which `touch()` bumps — initially I discarded the priced response and passed the stale create-time version, producing a transient `ERR_STALE_VERSION` that the second iteration fixed).
  - `test_07_scheduling_and_cancel_cascade.py::test_wo_cancel_cascade_restores_depleted_lot` — pointed it at a new RELEASED-only setup (below) and re-quoted the assertion to PRD §3.3's verbatim cascade sentence; the lot-restoration cascade is uniquely PRD-determined for a genuinely `RELEASED` WO, so this test was salvaged (STEP 2), not deleted.

- **Fixes applied to test_helpers/:** none in the `test_helpers/` directory. (The shared fixture `_released_wo_one_5ax_op_fully_allocated` lives in `test_suite/test_07_*.py`, not `test_helpers/`; I edited it there: removed its `book_slot(...)` call so the WO stays `RELEASED` instead of bubbling to `IN_PROCESS` via slot booking, since PRD §3.3 only permits cancel from `PLANNED`/`RELEASED`. It now returns `(quote, ops, wo, lot)` with no slot.)

- **Fixes applied to implementation/:** none. The implementation's RFQ-cancel (`routes/rfqs.py`), WO-cancel cascade (`routes/work_orders.py`), slot-booking bubble-up (`routes/machine_slots.py`), and RFQ `SUBMITTED → QUOTED` bubble (`services.py`) were all PRD-faithful as written; every one of the 4 original mismatches traced to a test setup that constructed a precondition the PRD makes unreachable, not to an implementation defect.

- **Infra/contention re-runs:** Yes. After the first fix batch, one full 8-round sweep crashed in all 8 rounds with `ServerStartError: Server process exited prematurely with code -15` (SIGTERM), and a later staggered sweep lost 2 rounds to the same boot crash plus 1 round to a single `"could not be restarted"` setup error on the trivial `test_create_rfq_returns_201_with_defaults`. I confirmed these were **not** logic bugs by: (a) the failures were boot/restart crashes producing no result files or `status:"error"` setup errors — never an assertion mismatch (expected-X-got-Y); (b) `ps` showed **10 sibling `claude` orchestrator processes** driving their own concurrent 8-round sweeps on the same host, i.e. far above 8× CPU load; (c) `start.sh` already guards its pip-install behind `if ! python3 -c "import flask"` and flask 3.0.3 is importable, so no install ran on the hot path — boot is just `python3 app.py`; and (d) the same tests passed cleanly in the rounds that did boot, and the entire 76-test suite went 76/76 in 8/8 rounds twice once I staggered the launches by 0.8s and raised `--timeout` to 180 to de-synchronize the cold-boot spike. The implementation boots reliably well under the poll window when not colliding head-on with 10 sibling sweeps.

## Step 8: Finalize PRD — align documentation to implementation — 2026-06-15T11:46:33.000Z

Step 8 ran (not skipped: Step 7 had 2 deletions + 2 test_suite fixes). The subagent produced `workspace/PRD_FINALIZED.md`. Orchestrator verification: `PRD_FINALIZED.md` is byte-identical to `PRD.md` (309 lines, 0% delta). Verbatim subagent summary follows.

## Summary

**Line counts:** PRD.md = 309 lines, PRD_FINALIZED.md = 309 lines. **%-delta: 0% (0 lines changed).**

**Changes made: none.** PRD_FINALIZED.md is a verbatim copy of PRD.md.

### Why no edits were warranted

The HARD SCOPE binds every edit to a `<step_7_diff>` item that reveals PRD-silence or PRD-mismatch with the current `implementation/`. I traced all four step_7 items to their implementation behavior and found that **every one was a pure test-fixture bug, not a PRD silence and not a PRD/impl mismatch.** Step 7 itself applied 0 implementation fixes and concluded the implementation was "PRD-faithful as written." The two contradictions the diff describes are both already disambiguated by prose that exists, unchanged, in PRD.md:

1. **§3.3 cancel cascade vs §3.4 slot bubble-up** (deleted `test_wo_cancel_cascade_releases_slot_and_reverts_op`): A genuinely RELEASED WO can never carry a BOOKED slot or SCHEDULED op, because §3.4 ("the first time any routing operation of a work order's quote reaches SCHEDULED, the work order itself bubbles up RELEASED → IN_PROCESS") fires the instant an op schedules. The implementation (`routes/work_orders.py:212-213`) restricts cancel to PLANNED/RELEASED and rejects IN_PROCESS with ERR_INVALID_STATE — exactly what §3.3's "while it is still PLANNED or RELEASED" already says. The cascade's slot/op-revert loop (`work_orders.py:231-240`) is faithfully written and simply finds nothing to act on for a RELEASED WO. A fresh reader reproduces this.

2. **§3.3 ERR_WO_ALREADY_INSPECTED vs §3.5 disposition gate** (deleted `test_cancel_released_wo_after_disposition_rejected`): A RELEASED WO can never hold a DISPOSITIONED inspection, because §3.5 ("the work order must be IN_PROCESS") gates disposition (`routes/inspections.py:175-176`). The `ERR_WO_ALREADY_INSPECTED` check (`work_orders.py:216-218`) is faithfully written and unreachable for a RELEASED WO — already determined by existing prose.

The two test-suite fixes (test_03 two-part-line setup; test_07 RELEASED-only setup) and the test_helper fix (removing `book_slot` to keep the WO RELEASED) all relied on PRD prose that is **already present and unambiguous**: §3.1 (ERR_RFQ_HAS_APPROVED_QUOTE on SUBMITTED cancel), §3.2 (RFQ bubbles SUBMITTED → QUOTED only when *every* part line has an approved quote), §3.3 (cancel only from PLANNED/RELEASED), §3.4 (slot scheduling bubbles RELEASED → IN_PROCESS), §3.5 (disposition requires IN_PROCESS).

### Per-edit pre-edit search log

No edits were committed, but I ran the mandatory global enumeration before concluding no edit was needed:

- **Subject: WO cancel state-entry + compensation cascade.** Enumerated paths: `routes/work_orders.py:207-245` (cancel handler, PLANNED/RELEASED guard, lot-void + slot-release + op-revert cascade), `services.py:20-24` (active_allocations_for_wo), `services.py:27-28` (inspections_for_wo), `services.py:16-17` (routing_ops_for_quote), `routes/machine_slots.py:108-122` (the parallel standalone slot-release path). All consistent with the existing §3.3/§3.4 prose; no wording change possible that wouldn't narrow a faithful path. (c) none.
- **Subject: slot-booking bubble-up RELEASED → IN_PROCESS.** Enumerated: `routes/machine_slots.py:67-78` (op-schedule gate + bubble), `services.py:102-108` (maybe_bubble_wo_released_to_in_process), `work_orders_for_quote` (services.py:39-40). Matches §3.4 line 184 verbatim. (c) none.
- **Subject: RFQ SUBMITTED cancel + cascade + SUBMITTED → QUOTED bubble.** Enumerated: `routes/rfqs.py:112-131` (cancel, approved-quote guard, DRAFT/PRICED → REJECTED cascade), `routes/quotes.py:122-140` (approve + bubble call), `services.py:83-99` (maybe_bubble_rfq_to_quoted, requires *every* part line approved). Matches §3.1/§3.2 prose. (c) none.
- **Subject: disposition IN_PROCESS gate.** Enumerated: `routes/inspections.py:159-208` (full precedence chain), `services.py:111-117` (in_process → completed bubble). Matches §3.5 prose. (c) none.

A fresh implementer reading PRD_FINALIZED.md (= PRD.md) alone produces code behaviorally equivalent to `implementation/` for all step_7-touched paths. Making any edit here would risk a brand-new false-universal mismatch (the NO-NEW-MISMATCH rule) that Step 9 would have to undo, so the minimal correct patch is the empty patch.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-15T11:52:33.000Z

Step 9 ran (always runs). The subagent produced `workspace/PRD_COMPLETED.md` from `PRD_FINALIZED.md` via a full PRD-vs-implementation scan. Orchestrator verification: `PRD_COMPLETED.md` exists (50,264 bytes, 309 lines, +1,752 chars over PRD_FINALIZED.md; all 9 edits are in-paragraph). Verbatim subagent summary follows.

## Summary

**File:** `tasks/task_0364_machine_shop_job_quoting/workspace/PRD_COMPLETED.md`

- **Line counts:** PRD_FINALIZED.md = 309, PRD_COMPLETED.md = 309 (unchanged — all edits are in-paragraph)
- **Char delta:** 48,512 → 50,264 (+1,752 chars)
- **Counts:** 5 ambiguity-pins, 4 mismatch-revisions (9 edits total)

**Changes (one per bullet):**

- §2.2 API Response Structure — insert — ambiguity — defined `total_count` (count before pagination) and `has_more` (`offset + page_len < total_count`), neither previously defined — `response.py:41-48`
- §2.3 Pagination — insert — ambiguity — pinned that out-of-range `limit`/`offset` are clamped (limit→[1,100], negative offset→0) not rejected, and that non-integer values yield `ERR_INVALID_REQUEST` (422) — `helpers.py:139-156`
- §2.5 Common Resource Properties — revise — ambiguity — `version` "starts at its initial value" pinned to start at **1** — `db.py:62`
- §2.8 OCC (quote approval) — revise — mismatch — PRD said request "must carry" `expected_quote_version`; impl makes it optional and skips the OCC check when omitted/null — `quotes.py:131-133`
- §2.8 OCC (work-order release) — revise — mismatch — same: `expected_work_order_version` is optional; OCC check skipped when omitted/null — `work_orders.py:162-164`
- §3.1 Intake (part lines) — insert — ambiguity — pinned that the `part_line_count` derived-count refresh does **not** bump the RFQ's `version` or `updated_at` — `services.py:56-63`
- §3.1 Intake (RFQ close) — insert — ambiguity — pinned that close with any non-`SHIPPED`/`CLOSED` work order yields `ERR_INVALID_STATE` (PRD named no error) — `rfqs.py:105-106`
- §3.4 Scheduling (slot booking) — revise — mismatch — pinned that the op transition also requires the op be currently `PLANNED`, and that the slot is created `BOOKED` (201) regardless even when scheduling preconditions fail — `machine_slots.py:69-78`
- §3.6 Delivery (shipment create) — insert — ambiguity — pinned that target WO must be `COMPLETED`/`SHIPPED`, else `ERR_INVALID_STATE` (prose narrative named no error) — `shipments.py:52-54`
- §3.7 Billing (invoice create) — revise — mismatch — pinned that referenced shipment must be `SHIPPED`, else `ERR_INVALID_STATE` (prose said only "issues an invoice for a shipment") — `shipments.py:138-140`

The rest of the implementation (estimate/actual cost formulas and per-step rounding, margin tiers, FIFO waterfall tie-break, penalty cap, tax, first-pass-yield, full error catalogue, RBAC matrix, validation precedence, all bubble-up/cascade transitions, InspectionStation id+created_at-only shape) was already uniquely pinned by the PRD prose and required no change.
