# Worklog — task_0295_locksmith_lockout_dispatch

## Step 1: Create Task Directory — 2026-06-11T06:34:49.000Z

Created `./tasks/task_0295_locksmith_lockout_dispatch/` and `./tasks/task_0295_locksmith_lockout_dispatch/workspace/`. Index 0295 derived from highest existing task index 0294 + 1.

## Step 2: Generate Scaffold — 2026-06-11T06:55:00.000Z

All three files parse, are saved at the correct location, and §1.9 spans all 9 taxonomy sections. There's a pre-existing `worklog.md` and `workspace/` dir (created by the orchestrator) — not my concern.

The scaffold for task_0295 is complete and fully lint-clean. Here is the summary for the worklog.

## Summary — task_0295_locksmith_lockout_dispatch scaffold generated

**Files written** (all lint-clean; `scaffold_lint.py` VERDICT: clean lint, 329 calls scanned, 0 violations):
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, single top-level key)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, single top-level key)

**Complexity profile**: Expert band. Primary archetype workflow_orchestration + secondary pricing_engine; layers = dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency; topology flat (multi-root, `api_prefix: /`); state_machine_shape parallel; role_model peer_roles; consistency immediate.

**Entities (11)**: ServiceJob (parallel job_status × payment_status axes, computed amount_due_cents/net_paid_cents), Technician (ON_DUTY/OFF_DUTY, entity_backed), JobBay (OPEN/CLOSED_FOR_MAINT), Dispatch (ETA window + promised/actual ETA), BayBooking (closed-interval bench slot), OnSiteQuote (cyclic; estimated vs final total), LockPart (OCC version; units_total/available/reserved/committed), PartReservation, KeyAuthorizationRecord (common_fields:false append-only compliance record), Payment, WarrantyClaim.

**State machines (8)**: ServiceJob job_status (INTAKE→DISPATCHED→ON_SITE→WORK_COMPLETE→CLOSED, +CANCELLED w/ depth-3 cascade), ServiceJob payment_status (UNPAID/PARTIALLY_PAID/PAID→REFUNDED), OnSiteQuote (cyclic revision loop), Dispatch, PartReservation, WarrantyClaim, Technician duty toggle, JobBay maint toggle.

**Calculations (10)**: quote_estimated_total_cents (forward_looking, flat base) vs quote_final_total_cents (aggregation, round-per-line-then-sum); dispatch_promised_eta_minutes (forward_looking) vs dispatch_actual_response_minutes (chronological); surcharge_multiplier (tiered after-hours ≥1080 × emergency-LOCKOUT stack); technician_eta_overlap_check (half-open + BUFFER_MINUTES=15); bay_slot_overlap_check (closed interval, no buffer); warranty_window_check (WARRANTY_DAYS=90); lockpart_unit_ledger (units conservation invariant); job_net_paid_cents (money conservation invariant). Key constants: BASE_RATE_CENTS {LOCKOUT 9000, REKEY 12000, INSTALL 15000, SAFE 20000}, LABOR_RATE 8000/hr, AFTER_HOURS×1.5, EMERGENCY_LOCKOUT×1.25.

**Validations (14, priority-ordered)**, **Endpoints (52)**, **Errors (41, all referenced)**, **Roles (5)**: Dispatcher (opaque), Technician (entity_backed:Technician), Customer (opaque, ownership via job.customer_user_id), InventoryManager (opaque), BillingAgent (opaque). **Concurrency (1)**: reservation-create-stale-lockpart, OCC on LockPart.version → ERR_STALE_LOCKPART_VERSION (412).

**§1.8 difficulty design**: 9 rules × 2 instances = 18, each with disjoint differentiation (e.g., rule-5 pairs {state, business_fiscal} and {business_safety, business_constraint}; rule-7 pairs Quote→Job and Dispatch→Technician; rule-8 half-open-buffered Technician vs closed-interval JobBay; rule-9 inventory-units vs money conservation). All formula-derived asserts pre-computed as literals (e.g., final 25997, 15624, round-per-line 16248 vs sum-then-round 16249; estimate boundary 13500 at 1080).

**§1.9 corner design**: 34 active instances + 4 `excluded_because` stubs across all 9 taxonomy sections (entities 8, state_machines 9, calculations 5, validations 5, endpoints 2, errors 2, rbac 3, cross_cutting 3, consistency 1).

One design correction made mid-build: the original technician model coupled dispatch creation to an AVAILABLE→EN_ROUTE status lock, which made the ETA-window-overlap rule (rule 8) unreachable (a tech could never hold two live dispatches). Reworked to ON_DUTY/OFF_DUTY duty model — dispatch creation leaves status unchanged and a tech may hold multiple non-overlapping scheduled dispatches — so rule-7 (off-duty gate) and rule-8 (ETA overlap) are both reachable on distinct mechanisms.

## Step 3: Copy Shared Files — 2026-06-11T06:57:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-11T07:00:00.000Z

All rounding semantics ("rounded half up", per-line-then-sum) are fully expressed. The PRD is complete and all three hard contracts pass.

The PRD has been generated at `workspace/PRD.md`.

**PRD: Locksmith & Lockout Dispatch API** — 316 lines, 5 top-level sections (§1 Introduction, §2 Global Specifications with 10 subsections, §3 Business Logic with 15 subsections, §4 Endpoint Definitions, §5 Error Code Catalogue).

**Entities documented (11):** ServiceJob, Technician, JobBay, Dispatch, BayBooking, OnSiteQuote, LockPart, PartReservation, KeyAuthorizationRecord (append-only, no `updated_at`/`version`), Payment, WarrantyClaim. All 56 field/param identifiers covered verbatim.

**State machines (8):** ServiceJob `job_status` (INTAKE→DISPATCHED→ON_SITE→WORK_COMPLETE→CLOSED, plus CANCELLED with full cascade), ServiceJob `payment_status` (UNPAID/PARTIALLY_PAID/PAID/REFUNDED — parallel money axis), OnSiteQuote (cyclic DRAFTED↔SUBMITTED, APPROVED/REJECTED/VOIDED revision loop), Dispatch (ASSIGNED→EN_ROUTE→ARRIVED, CANCELLED), PartReservation (RESERVED→COMMITTED/RELEASED), Technician duty toggle, JobBay maintenance toggle, WarrantyClaim (FILED→APPROVED/DENIED with refund cascade).

**Calculations (9):** quote_estimated_total_cents (flat BASE_RATE × surcharge, round half up), quote_final_total_cents (labor + parts, round-per-line-then-sum), surcharge_multiplier (after-hours [≥1080 ∪ <480] ×1.5 stacking with emergency-LOCKOUT ×1.25), dispatch_promised_eta_minutes (base_travel + live-dispatch count × 10), dispatch_actual_response_minutes (arrived − requested, floored at 0), technician_eta_overlap (half-open + 15-min buffer), bay_slot_overlap (closed interval, inclusive, no buffer), warranty_window (≤90 days), lockpart_unit_ledger (conserved-unit invariant), job_net_paid_cents ledger.

**Endpoints (53):** full table with 4 columns; covers all CRUD + state actions across all 11 entities.

**Errors (41):** all catalogued in §5 (2 columns) and every one referenced by trigger condition in §2/§3 narrative.

**Roles (5):** Dispatcher, Technician, Customer, InventoryManager, BillingAgent — with `identity` translated (Technician entity-backed; Customer opaque but matched to `customer_user_id`; other three opaque).

**Concurrency:** OCC on LockPart `version` via `expected_lockpart_version` → `ERR_STALE_LOCKPART_VERSION` (412), framed in stale-version terms. Field coverage PASS (56/56), Rule coverage PASS, Path purity PASS (0 path tokens in §3). Design files were NOT opened.

## Step 5: Generate Unit Tests — 2026-06-11T07:03:00.000Z

Generated complete test infrastructure for **task_0295_locksmith_lockout_dispatch**.

### Stage 1 — `test_helpers/` (9 files)
- `types.py` — 11 status enums, role enum, 11 entity TypedDicts (KeyAuthorizationRecord correctly omits `updated_at`/`version` as append-only).
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (all 53 endpoints).
- `api_errors.py` — `ApiErrorId` enum (40 errors) + HTTP status map registered with the framework.
- `assertions.py` — per-entity assertions + `assert_lock_part_ledger_invariant` (conserved-unit invariant).
- `factories.py` — input-only payload factories per entity.
- `constants.py` — pricing/surcharge/ETA/warranty thresholds from PRD §3.
- `test_users.py` — opaque headers for Dispatcher/InventoryManager/BillingAgent/Customer; entity-backed `make_technician_headers` and ownership `make_customer_headers` builders.
- `fixtures.py` — composite helpers (`drive_job_to_on_site`, `setup_drafted/submitted/approved_quote`, `reserve_part`, `setup_drafted_quote_with_reservation`, `setup_paid_completed_job`, `setup_filed_warranty_claim`) with correct identity threading.
- `__init__.py` — barrel export.

### Stage 2 — `test_suite/` (conftest + 6 test files, 69 test functions)
- `test_01_pricing_and_surcharges.py` (11), `test_02_dispatch_and_eta.py` (13), `test_03_quote_lifecycle.py` (11), `test_04_inventory_and_reservations.py` (16), `test_05_payments_warranty_and_closure.py` (10), `test_06_intake_and_access.py` (8).

### Coverage
- **Queue A (Difficulty):** all 18 instances covered, exactly 2 tests each = 36 tests.
- **Queue B (Corner):** 33 of 34 non-stub instances covered = 33 tests. All 4 `excluded_because:` stubs verified to cross-reference real difficulty instances (not translated).

### Skipped instances (1)
- **`Corner/endpoints/list_dispatches_filtered_by_technician`** — SKIPPED. Its only PRD support is the §4 endpoint-table title "List dispatches, filterable by technician," which is endpoint-titular with no rule-bearing prose sentence stating the filter semantics. Fails citation rule C2 (rule-bearing, not endpoint-titular). Gap left as a gap per the PRD-first filter.

### Quality verification
- All files byte-compile; `test_helpers` and all 6 test modules import cleanly against a mocked framework.
- Every test docstring ends with exactly one `Design:` tag; 0 untagged, 0 dual-tagged, 0 tags to non-existent instances.
- Every quoted PRD citation verified verbatim against `workspace/PRD.md` (0 missing); 0 ellipsis-abbreviated citations; 0 `skip`/`skipif`/`xfail` markers; 0 scaffold-leakage references in generated code.
- All literal expected values (12000, 25997, 15624, 16248, 13500, 9000, ETA 20/45, ledger counts, refund nets) copied from the design indices and independently re-verified.

## Step 6: Generate Implementation — 2026-06-11T07:03:00.000Z

**Stack:** Python 3 + Flask 3.0.3, in-memory store, no database. All code in `workspace/implementation/`.

**Files created (10):**
- `start.sh` — guarded launcher: `cd` to script dir, install deps only if `import flask` fails, then `exec python3 app.py`. Binds `0.0.0.0:$PORT` (default 10000), foreground.
- `requirements.txt` — `Flask==3.0.3`
- `app.py` — Flask entry point: all 56 routes, error handlers, existence lookups, state machines, cascades, calculations (~43KB, single file by resource group)
- `errors.py` — `ApiError` + complete error→HTTP-status catalog (PRD §5)
- `response.py` — success/error envelope helpers (`meta`/`response_type`/`data`; `req_*` request id; ISO-8601 UTC timestamp with exactly 3 fractional digits)
- `db.py` — in-memory `Store` (one dict per collection, **empty on every boot, no seeding**), UUID/timestamp/sequence helpers
- `auth.py` — `X-User-ID`/`X-User-Role` extraction, 5 roles, RBAC `require_role`
- `helpers.py` — input validators, pagination (`limit`/`offset`, default 10, 1–100), all calculation constants/functions (Decimal + ROUND_HALF_UP)
- `domain.py` — record construction, `touch()` (version bump + updated_at), `recompute_net_paid`, `recompute_lockpart_units`
- `serialize.py` — strips internal `_seq` key from wire output

**Endpoints:** All 56 from PRD §4 implemented — ServiceJob CRUD + cancel/complete-work/close/payments/key-authorizations/warranty-claims; Dispatch create/list/depart/arrive/cancel; Technician CRUD + duty toggles; JobBay + BayBooking; OnSiteQuote draft/update/submit/approve/reject/request-revision/reopen; LockPart CRUD + PartReservation; WarrantyClaim get/approve/deny.

**State machines encoded:**
- ServiceJob **parallel axes**: `job_status` (INTAKE→DISPATCHED→ON_SITE→WORK_COMPLETE→CLOSED, or →CANCELLED) × `payment_status` (UNPAID→PARTIALLY_PAID→PAID→REFUNDED), coupled only at close (requires PAID) and warranty-refund.
- OnSiteQuote **cyclic** revision loop (DRAFTED↔SUBMITTED, REJECTED→DRAFTED reopen, →VOIDED/APPROVED terminal).
- Dispatch, PartReservation, WarrantyClaim, Technician/JobBay toggles.
- **Cascades:** job cancel → dispatches CANCELLED, non-terminal quotes VOIDED, their RESERVED reservations RELEASED (restock), BOOKED bay bookings RELEASED; complete-work → RESERVED reservations COMMITTED (units_reserved→units_committed). Every cascaded child gets its own `version` bump + `updated_at`.

**Key calculations encoded:**
- Surcharge multiplier: ×1.5 after-hours (`requested_at_minute >= 1080 OR < 480`, boundaries 1080 inclusive / 480 exclusive) compounded ×1.25 only for emergency LOCKOUT.
- Quote estimate (DRAFT) = flat `BASE_RATE_CENTS[service_type] × multiplier`, round-half-up.
- Quote final (SUBMIT) = labor (8000/hr) + parts, **round-per-line then sum** (not sum-then-round).
- Promised ETA = `base_travel + live_dispatch_count × 10`; actual = `arrived − requested`, floored at 0.
- ETA overlap: half-open windows + 15-min buffer. Bay overlap: closed intervals, inclusive endpoints, no buffer.
- `net_paid` follows PRD formula **literally**: `sum(captured for CAPTURED) − sum(refunded for REFUNDED)` — note this yields a negative net after a full refund (REFUNDED payment leaves the CAPTURED sum and is subtracted), which contradicts a stray scaffold "invariant" comment; **PRD prose was followed per the skill's unconditional-authority rule.**
- Warranty refund target: lowest `captured_amount_cents ≥ refund_amount`, ties by `created_at` ASC.
- LockPart OCC on `version` via `expected_lockpart_version` (412), checked before stock sufficiency, on both reservation-create and lock-part PUT.

**Validation ordering** (PRD §2.6): auth(401) → role(403) → existence left-to-right(404) → ownership(403) → state(409) → business constraints. Reservation chain: OCC → restricted-blank auth → discontinued/quantity → stock.

**Verification:** Booted via `start.sh`; ran ~50 assertions across full lifecycle, surcharge boundaries, ETA/bay overlap geometry, cancel cascade, warranty refund selection, OCC, RBAC, envelope/pagination/timestamp format — all pass. Confirmed empty store on fresh boot (total_count=0, no seeding).

## Step 7: Run Tests and Iterate — 2026-06-11T07:29:00.000Z

All 8 parallel rounds pass cleanly (69/69 each). Exiting with the summary.

**Iterations run:** 2 (initial sweep + one fix sweep).

**Initial state:** 68/69 passing, deterministically (identical failure in all 8 rounds — not flaky). The single failing test was `test_capture_then_warranty_refund_nets_to_zero` in `test_05_payments_warranty_and_closure.py`.

**Diagnosis (STEP 1–2):** The test asserted that after capturing 8000 then approving a full 8000 warranty refund, the job's `net_paid_cents == 0` ("nets to zero"). I traced this against the verbatim PRD §3.12 formula, which is the only `net_paid_cents` definition in the PRD and the one §3.14 says is re-run after a refund:

> "the sum of `captured_amount_cents` across the job's payments in CAPTURED status, minus the sum of `refunded_amount_cents` across the job's payments in REFUNDED status"

Applied literally to the post-refund state: the lone payment is now in REFUNDED status, so the CAPTURED sum is 0 and the REFUNDED sum is 8000, giving `net_paid_cents = 0 − 8000 = −8000`. The formula restricts the captured sum to CAPTURED-status payments, so a fully refunded payment produces a negative net. The PRD uniquely determines −8000; the test's expectation of 0 is an intuitive accounting invariant that contradicts the literal PRD prose. This matches the implementation generator's note exactly, and PRD prose is the authority. The implementation (`domain.py:recompute_net_paid`) already follows the PRD formula correctly — this was a **TEST BUG**, not an implementation bug.

**Tests deleted:** None. (No test was PRD-silent or non-uniquely-derivable; the one failure was a faithful-PRD/wrong-assertion mismatch, fixed per STEP 2.)

**Fixes applied to `test_suite/`:**
- `test_05_payments_warranty_and_closure.py` — corrected the assertion in the warranty-refund test from `net_paid_cents == 0` to `net_paid_cents == -8000` to match the literal PRD §3.12 formula; added the §3.12 formula quote to the docstring to anchor the corrected expectation to verbatim PRD prose, renamed the function `test_capture_then_warranty_refund_nets_to_zero` → `test_capture_then_warranty_refund_recomputes_net_paid` (the old name encoded the wrong invariant), and updated the inline comment. All other assertions in the test (`payment_status == "REFUNDED"`, claim `status == "APPROVED"`) were PRD-faithful and left intact. No error_id was downgraded; no skip/xfail added.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:** None — the implementation already complied with the PRD.

**Final result:** All 8 parallel rounds green at 69/69.

## Step 8: Finalize PRD — 2026-06-11T07:31:00.000Z

Skip condition NOT met (Step 7 ran 2 iterations with 1 `test_suite/` fix), so the subagent was spawned. It verified the single Step 7 diff item and produced PRD_FINALIZED.md.

**PRD_FINALIZED.md produced as a verbatim copy of PRD.md. No edits were warranted.**

- PRD.md: 315 lines; PRD_FINALIZED.md: 315 lines; %-delta: 0% (byte-identical, confirmed via `diff -q` → IDENTICAL).
- **No changes — PRD_FINALIZED.md is a verbatim copy of PRD.md.**

Per-edit pre-edit search log (verification of the single §3.12 `net_paid_cents` item):
- **(a) Subject:** the `net_paid_cents` recomputation — whether PRD uniquely determines the post-full-refund −8000 value the impl computes.
- **(b) Impl paths enumerated:** `domain.py:27-39` `recompute_net_paid` (canonical, literal §3.12 formula, no clamp to 0); `app.py:311-315` capture path (§3.12, same recompute); `app.py:434,450-451` warranty-approve (§3.14, same recompute; refund-exceeds-paid gate reads pre-refund net so unaffected); `app.py:169-171` intake init `net_paid_cents=0`. Grep confirmed no other writers.
- **(c) Adjustment:** None. Both recompute callsites use the identical formula; PRD §3.12 formula + §3.14 "recomputed" already uniquely determine −8000 for the test scenario. The Step 7 item was a test bug (fixture wrongly expected 0); impl already complied and PRD already pinned the value. No PRD silence or mismatch → no edit justified.

## Step 9: Complete PRD — 2026-06-11T07:37:00.000Z

**PRD_COMPLETED.md produced** from PRD_FINALIZED.md source.

**Source vs. completed:**
- `PRD_FINALIZED.md`: 315 lines, 44,421 chars
- `PRD_COMPLETED.md`: 315 lines, 45,789 chars
- Char delta: **+1,368** (no lines added/removed; all changes are in-paragraph)

**Counts:** 4 ambiguity-pins, 2 mismatch-revisions (5 edited paragraphs; the §3.14 edit corrects two distinct mismatches in one paragraph).

**Changes:**
- §2.3 Pagination — insert — ambiguity — pinned `limit`/`offset` out-of-range handling as clamping (limit<1→1, >100→100, offset<0→0) rather than rejection — `helpers.py:150-160`
- §2.3 Pagination — insert — ambiguity — pinned the `created_at`-tie ordering: ties broken by ascending creation order for deterministic paging — `helpers.py:167`
- §3.10 Completing Work — insert — ambiguity — pinned that complete-work requires the job to be `ON_SITE` (else `ERR_JOB_NOT_ON_SITE`), checked before the approved-quote check — `app.py:248-252`
- §3.12 Closing — insert — ambiguity — pinned that a close on a job not in `WORK_COMPLETE` also returns `ERR_JOB_NOT_FULLY_PAID` (same error as the not-paid case) — `app.py:273-276`
- §3.14 Warranty filing — revise — mismatch — removed the implied "job must be closed to file" precondition; impl enforces `CLOSED` only at approval, allowing a claim to be filed against a job in any state — `app.py:371-400` (vs `app.py:430`)
- §3.14 Warranty filing — revise — mismatch — corrected the filing bound on `refund_amount_cents`: only `>= 1` is enforced at filing; the "not exceeding `net_paid_cents`" bound is enforced at approval, not at filing — `app.py:386-388` (vs `app.py:434`)
- §3.15 Well-Formedness — insert — ambiguity — pinned that well-typed numeric fields violating a stated lower bound (`captured_amount_cents`/`refund_amount_cents` <1; `labor_hours`/`base_travel_minutes`/`units_total`/`days_since_close` <0) yield `ERR_INVALID_REQUEST`, with reservation `quantity` as the documented `ERR_INVALID_QUANTITY` exception — `app.py:294,388,646,876,1049,1102` (quantity at `app.py:1145-1146`)

**Notable behaviors checked and left unchanged (already pinned or additive, not mismatches):** round-per-line surcharge math (§3.5/§3.6), ETA-window half-open + 15-min buffer geometry and bay closed-interval geometry (§3.3/§3.11), promised-vs-actual ETA dual calc (§3.2/§3.4), reservation validation ordering OCC→auth→discontinued/quantity→stock (§3.7), all cascade mutations (§3.13/§3.10/§3.9), `net_paid_cents` going negative after refund (literal §3.12 formula), refund-target tie-break by `created_at` (§3.14). Extra `status`/`service_job_id` list filters are additive and do not contradict the PRD's stated filter sets.

---

## Pipeline complete — 2026-06-11T07:37:00.000Z

All 9 steps finished. Final test status: **69/69 passing across all 8 parallel stability rounds**. Task artifacts complete at `tasks/task_0295_locksmith_lockout_dispatch/`.
