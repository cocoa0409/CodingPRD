# Worklog — task_0220_home_inspection_scheduling

Scenario: Home Inspection Scheduling & Reporting: inspection type (buyer/seller/4-point/wind-mit), inspector scheduling/territory, fee by square footage, add-on (radon/termite/sewer), defect-severity report, re-inspection, agent/client delivery, scheduling conflict

Difficulty target (Step 2 only): Expert

## Step 1: Create task directory — 2026-06-07T03:03:01.000Z

Used pre-allocated directory `tasks/task_0220_home_inspection_scheduling` verbatim (index-scan skipped per instructions). Ensured `workspace/` subdirectory exists.

## Step 2: Generate scaffold (Expert) — 2026-06-07T03:30:00.000Z

All structural constraints satisfied. The scaffold is complete and validated.

Generated the three Expert-tier scaffold artifacts for **Home Inspection Scheduling & Reporting**. Built purely from the scenario + scaffold-generator skill spec (no sibling tasks consulted). `scaffold_lint.py` reports **VERDICT: clean lint** across all 569 §1.8/§1.9 calls and all 11 FK reverse-reachability checks.

**Complexity profile:** primary archetype temporal_windowing + secondary pricing_engine; layers optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation; hybrid topology with self-referential re-inspections; branching/cyclic state shape; peer_roles model.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **11 entities:** Territory, FeeSchedule, Inspector, Client, Agent, Property, InspectionOrder (central, self-referential via `parent_order_id`), AddOn, Report, Defect, Delivery.
- **2 state machines:** InspectionOrder (branching: schedule→start→report→deliver, with unschedule revert, cancel branch, and a DELIVERED→re-inspection spawn) and Report (fork to APPROVED/REJECTED with a REJECTED→DRAFT→SUBMITTED cycle, plus system VOID cascade). Plus 1 concurrency rule (OCC on parent order version for re-inspection create-with-supersede).
- **7 calculations:** inspection_fee (tiered sqft × type-multiplier + add-ons, QUOTED vs FINAL variants), reinspection_fee (parent-band-keyed discount, mode-c circular dependency), defect_risk_score (per-defect-rounding-then-sum weighted scoring, PROVISIONAL vs FINAL), severity_band threshold, inspector_daily_load aggregation, order_balance ledger, order_duration.
- **16 validations** (priority-ordered, 8 categories) and **17 error codes**.
- **40 endpoints** (lifecycle actions + GET reverse-reachability for every FK + computed reads), **4 roles** (Scheduler opaque; Inspector/Client/Agent entity-backed).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** 20 instances covering all 9 Difficulty Rules ≥2 each (combinatorial_formula carries 4 across modes a/b/c). Every formula-derived assertion is a pre-computed literal, verified in Python (e.g., quoted 52900 vs final 50500; provisional 532 vs final 466; re-inspection fee 17200/17550; tier boundary 39000/39008).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** 41 instances total — 33 active full-recipe corners + 8 `excluded_because:` stubs deferring to named §1.8 instances.

Verified: SCAFFOLD.yaml 1182 lines (no design keys), DIFFICULTY 1507 lines (1 top-level key), CORNER 1729 lines (1 top-level key).

## Step 3: Copy INSTRUCTION.md — 2026-06-07T03:30:43.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (53 lines).

## Step 4: Generate PRD — 2026-06-07T03:35:56.000Z

**Generated:** `workspace/PRD.md` (239 lines, 24 headings, 37 KB). Read SCAFFOLD.yaml only; both design YAMLs and sibling tasks withheld/untouched.

**Structure:** §1 Introduction; §2 Global Specifications (9 subsections: RBAC, fixed error envelope, pagination, common resource props, cascades, nested retrieval/existence ordering, money/duration/rounding, OCC on re-inspection, fiscal conservation); §3 Business Logic (9 subsections by lifecycle: config, parties/property, ordering/scheduling, add-ons/duration/capacity, payment/delivery/balance, defect report review cycle, fee calc, re-inspection, cancellation cascades); §4 Endpoint table (40 endpoints); §5 Error catalogue (17 errors).

**Hard Contracts — all PASS:** Field coverage 68/68 required present; Rule coverage (validations priority order, 1 OCC rule, 13 state transitions, 6 calculations reconstructible step-for-step, all 17 error triggers, cascades, defaults/enums, sibling-branch symmetry) 0 missing; §3 Path purity 0 path tokens. Every entity, state machine, calculation, validation, endpoint, and error from SCAFFOLD.yaml covered in prose.

## Step 5: Generate unit tests — 2026-06-07T03:57:45.000Z

**Stage 1 — `test_helpers/`** (9 files): `types.py` (entity TypedDicts; Client/Agent carry only `id`+`created_at`, no `version`/`updated_at`), `api_client.py` (40 endpoint methods), `api_errors.py` (17 error IDs + HTTP-status map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque Scheduler shared constant + per-instance `make_<role>_headers` builders for the 3 entity-backed roles), `fixtures.py` (composite lifecycle helpers: base config → requested → scheduled → started → report-draft → submitted → approved → delivered, plus delivered-failing-parent helper for re-inspection), `__init__.py` barrel.

**Stage 2 — `test_suite/`**: `conftest.py` + 5 domain files. **63 tests total: 34 from queue A (Difficulty), 29 from queue B (Corner).** Every test carries one verbatim PRD citation and exactly one `Design:` tag; all 90 quoted citation spans survive literal grep of PRD.md; no skip/xfail; no orphan tags. Coverage: every kept Difficulty instance ≥2 tests; every kept non-stub Corner instance ≥1 test; all 8 `excluded_because` stubs left untranslated.

**Instances SKIPPED under the PRD-first filter (gaps, not weakened):**
- `Difficulty/priority_pair_validation_conflict/deliver_unapproved_and_unpaid_state_beats_fiscal` and `Difficulty/cross_entity_state_dependency/deliver_requires_report_approved_order_to_report` — assert `ERR_INVALID_STATE` for SUBMITTED-but-not-APPROVED report on deliver; PRD §3.5 attaches that error only to the "order must be in REPORT_DRAFT" clause, not the "report must be APPROVED" sub-condition → not uniquely derivable.
- `Difficulty/cross_entity_state_dependency/schedule_requires_inspector_active_order_to_inspector` (both tests) — assert `ERR_INVALID_STATE` for scheduling onto a SUSPENDED inspector; PRD §3.3 binds that error only to "order must be in REQUESTED status".
- `Corner/state_machines/corner_start_from_requested_invalid_state`, `corner_cancel_from_delivered_terminal_invalid_state`, `corner_approve_report_from_draft_invalid_state` — assert `ERR_INVALID_STATE` but PRD prose names no trigger condition pinning that error_id (the §5 table lists the id without a condition).
- `Corner/endpoints/corner_list_orders_by_parent_order_id_filter` — `?parent_order_id=` filter appears only in scaffold endpoint list/title; no PRD prose describes it.

These are recorded PRD under-specification gaps (missing error_id pinning / missing filter prose), not papered over.

## Step 6: Generate implementation — 2026-06-07T03:57:45.000Z

Generated Python + Flask implementation at `workspace/implementation/`. Did not read test_suite/test_helpers or any sibling task.

**Files (11):** `start.sh` (executable; guards `pip install` on cheap `import flask`, then `exec python3 app.py`), `requirements.txt` (flask==3.0.3), `app.py` (40 routes + error handlers; `app.run(host="0.0.0.0", port=int(os.environ["PORT"] or 10000), threaded=True)`), `db.py` (in-memory `Store`, 11 dicts keyed by id + UUID/ISO-8601-ms helpers), `errors.py` (17-entry catalog), `response.py` (fixed envelope, req_-prefixed id, 3-digit UTC ts), `middleware.py` (X-User-ID/X-User-Role auth + RBAC), `common.py` (system fields, pagination limit 1–100 default 10 / offset default 0 → ERR_VALIDATION_RANGE, validators), `calculations.py` (fee/score engine), `services.py` (order fee/duration/balance recompute + inspector daily-load ledger), `scheduling.py` (schedule-time validations shared by /schedule and /reinspect).

**Endpoints:** 40 (24 POST, 16 GET) — matching PRD §4.

**State machines:** InspectionOrder (REQUESTED→SCHEDULED⇄unschedule→IN_PROGRESS→REPORT_DRAFT→DELIVERED; non-terminal→CANCELLED with cascade; DELIVERED→spawns REINSPECTION child). Report (DRAFT→SUBMITTED→APPROVED/REJECTED→DRAFT cyclic; any→VOIDED via order cancel cascading defects→VOIDED). Defect (LOGGED→CONFIRMED [MAJOR/CRITICAL] / CLEARED [MINOR] at approval; →VOIDED on cancel). AddOn (ACTIVE→REMOVED). Delivery (SENT→CANCELLED). FeeSchedule (DRAFT→PUBLISHED). Inspector (ACTIVE→SUSPENDED).

**Calculations (integer cents, Decimal ROUND_HALF_UP where PRD pins it):** inspection_fee (marginal 3-tier sqft → (base+comp)*type_mult half-up [BUYER 1.0/SELLER 0.9/FOUR_POINT 0.75/WIND_MIT 0.6] → flat ACTIVE add-ons; QUOTED recorded sqft, FINAL measured sqft); reinspection_fee (quoted × (1−d), d banded on parent final_fee_cents <50000→base, <100000→+0.10, ≥100000→+0.20 cap 0.90); defect_risk_score (per-defect round_half_up(weight*100/3) = MINOR 33/MAJOR 133/CRITICAL 333 summed; PROVISIONAL over non-VOIDED, FINAL over CONFIRMED only); severity_band (PASS 0, MINOR [1,133), MAJOR [133,666), CRITICAL ≥666); inspector_daily_load, order_balance, order_duration.

Validation precedence per §1.4 (auth→forbidden→not-found→invalid-request→state→not-assigned-inspector→certification→territory→double-booking→same-day→too-soon→not-warranted→duplicate-addon→capacity→unpaid→stale-version); OCC on expected_order_version (ERR_STALE_VERSION/412) for re-inspection only.

**Confirmations:** storage in-memory only (plain dicts, no SQLite/JSON/tmp/persistence; empty store on boot, no seed/preload); start.sh reads $PORT, binds 0.0.0.0, runs foreground via exec; guarded dependency install. Validated with 45-assertion smoke test (happy path, conflict errors, fee/score math, reinspect OCC + discount banding, cancel cascade with refund/void) all passing.

## Step 7: Run tests and iterate — 2026-06-07T04:54:17Z

- Iterations run: 1 (single 8-round parallel sweep; clean on first pass — no further sweeps).
- Tests deleted: none (no failures, so no STEP 1a PRD-silence or STEP 1b unique-derivability deletions were triggered).
- Fixes applied to test_helpers/: none.
- Fixes applied to implementation/: none.
- Final sweep result: all 8 rounds passed == total. Every round reported total=63, passed=63, failed=0, errors=0, skipped=0. Final count: 63/63 per round, no flakiness across rounds (union of failures is empty). results.1.json .. results.8.json retained on disk as evidence.

## Step 8: Finalize PRD — 2026-06-07T04:10:00.000Z

SKIPPED. Step 7 exited on the first 8-round sweep with 0 test deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes — PRD.md already determined every behavior the implementation exhibits. Per the skip condition, no PRD_FINALIZED.md is produced.

## Step 9: Complete PRD — 2026-06-07T04:18:00.000Z

Generated `workspace/PRD_COMPLETED.md` from `workspace/PRD.md` (Step 8 skipped, so no PRD_FINALIZED.md source). Full PRD-vs-implementation/ scan; SCAFFOLD*.yaml and worklog.md withheld.

Source vs output: PRD.md = 239 lines / 37,281 chars; PRD_COMPLETED.md = 239 lines / 40,318 chars (char delta +3,037; line count unchanged — all in-paragraph inserts/revisions, no new sections).

Counts: 13 ambiguity-pins, 4 mismatch-revisions (17 changes total).

Changes:
- §2.1 (RBAC) — revise — mismatch — ERR_NOT_ASSIGNED_INSPECTOR operation list extended to include logging a defect — app.py:983
- §3.1 (FeeSchedule) — insert — ambiguity — publishing a non-DRAFT schedule → ERR_INVALID_STATE — app.py:174-175
- §3.1 (Inspector) — insert — ambiguity — suspending a non-ACTIVE inspector → ERR_INVALID_STATE — app.py:247-248
- §3.1 (Inspector daily-load) — insert — ambiguity — date query param required, YYYY-MM-DD, missing/malformed → ERR_VALIDATION_RANGE — app.py:259-267
- §3.3 (Scheduling) — insert — ambiguity — SUSPENDED inspector at schedule time → ERR_INVALID_STATE — app.py:463-464
- §3.3 (Scheduling) — insert — ambiguity — double-booking pinned to inspector's other SCHEDULED/IN_PROGRESS/REPORT_DRAFT/DELIVERED orders with non-null scheduled_start — scheduling.py:100-103
- §3.3 (Unschedule) — insert — ambiguity — unscheduling a non-SCHEDULED order → ERR_INVALID_STATE — app.py:496-497
- §3.4 (AddOn create) — insert — ambiguity — duplicate-kind counts only ACTIVE add-ons; order-state check precedes duplicate-kind check — app.py:784-794
- §3.4 (AddOn remove) — insert — ambiguity — non-REQUESTED/SCHEDULED order and non-ACTIVE add-on both → ERR_INVALID_STATE, order-state check first — app.py:843-846
- §3.5 (Payment) — insert — ambiguity — amount_cents required integer ≥ 0 — app.py:563
- §3.5 (Effective fee) — insert — ambiguity — CANCELLED effective fee → 0 — services.py:59-64
- §3.5 (Start) — revise — mismatch — SCHEDULED-state check (ERR_INVALID_STATE) pinned before assigned-inspector check — app.py:515-518
- §3.5 (Deliver) — insert — ambiguity — missing/non-APPROVED report → ERR_INVALID_STATE; gate order REPORT_DRAFT → APPROVED → paid — app.py:576-595
- §3.6 (Report create) — insert — ambiguity — preconditions IN_PROGRESS → assigned-inspector → no-existing-report; existing-report → ERR_INVALID_STATE — app.py:533-538
- §3.6 (Defect logging) — insert — ambiguity — report-DRAFT check (ERR_INVALID_STATE) before assigned-inspector check — app.py:981-984
- §3.6 (Submit) — revise — mismatch — precedence report-DRAFT → assigned-inspector → owning-order-REPORT_DRAFT — app.py:893-898
- §3.6 (Approve/Reject) — insert — ambiguity — approving/rejecting a non-SUBMITTED report → ERR_INVALID_STATE — app.py:916,945
- §3.6 (Revise) — insert — ambiguity — report-REJECTED check (ERR_INVALID_STATE) before assigned-inspector check — app.py:958-961
- §3.8 (Re-inspection) — revise — mismatch — added inspector-ACTIVE precondition + fixed full precedence order (DELIVERED → ACTIVE → cert → territory → double-booking → same-day → too-soon → not-warranted → daily-capacity → stale-version) — app.py:682-733
- §3.9 (Cancel) — insert — ambiguity — cancelling an already-terminal (DELIVERED/CANCELLED) order → ERR_INVALID_STATE — app.py:634-635
