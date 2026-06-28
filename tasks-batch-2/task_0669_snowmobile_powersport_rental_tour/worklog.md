# Worklog — task_0669_snowmobile_powersport_rental_tour

## Step 1: Task directory — 2026-06-26T18:18:42.000Z

Task directory and workspace/ already existed (pre-created by the parallel-run harness). Per execution directives, the Step 1 directory-scan was skipped; {task_dir} = tasks/task_0669_snowmobile_powersport_rental_tour is used verbatim. Verified INSTRUCTION.md and all prd-bench skills are present.

## Step 2: Generate Scaffold — 2026-06-26T18:39:30.000Z

Generated the three scaffold artifacts for **task_0669_snowmobile_powersport_rental_tour** (Expert difficulty). The scaffold lint reports **`VERDICT: clean lint`**.

**Complexity profile:** Primary archetype Quota/allocation, secondary Temporal windowing; layers = Optimistic concurrency, Cascading side effects, Dual-variant calculation, Rate/threshold triggers. Topology `flat` (peer collections via FK), state-machine shape `parallel`, role model `peer_roles`, consistency `immediate`.

**Entities (10):** Member, Guide, Trail, Unit, GearItem, TourDeparture, GuideAssignment, Reservation, Settlement, ClosureEvent.

**State machines (9 dimensions):** Member.waiver_status (revert loop UNSIGNED↔SIGNED↔EXPIRED), Member.training_level (linear), Trail.condition (branch+revert with CLOSED cascade), TourDeparture.status (branching SCHEDULED→LOCKED→DEPARTED→COMPLETED + CANCELLED cascade), Reservation has **two parallel dimensions** (reservation_status × settlement_status), Unit.status, GearItem.status, Guide.status.

**Key calculations (8):** `estimate_reservation_quote` (tiered tour fee + membership discount with pinned combined-gross rounding), `final_settlement` (5-line waterfall vs deposit), `fuel_charge` (≥0.95 threshold), `late_fee` (30-min inclusive grace + 60-min blocks), `deposit_hold` (premier-waiver variant), `guide_ratio_requirement` (1 guide per 6 riders), `no_show_settlement` (fixed fee, deposit refunded), `eligibility_constants`.

**Validations:** 22 rows (priorities 1–20 plus 5.1/5.2), ordered auth → existence → state → safety → temporal → fiscal → OCC.

**Endpoints:** 40 (entity CRUD, action endpoints, 6 FK reverse-reachability GETs, `/_clock/set_current_utc` defaulting to 2026-04-01T00:00:00Z).

**Error catalog:** 22 codes, every one referenced by a validation/concurrency rule and asserted in a design instance.

**Roles (5):** Anonymous, Member (entity_backed), Guide (entity_backed), DispatchOperator (opaque), PlatformAdmin (opaque). One concurrency rule: `confirm-stale-departure` (OCC on TourDeparture.version, 412).

**§1.8 design:** 9 rule_ids, **19 instances** (combinatorial_formula carries 3; others 2 each), each grounded with executable empty-DB recipes; all formula-derived assertions pre-computed to literals.

**§1.9 design:** 33 instances (32 executable + 1 `excluded_because` stub) across all 9 claim-extraction sections.

Files: SCAFFOLD.yaml (1706 L), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1320 L), SCAFFOLD_CORNER_DESIGN.yaml (1294 L).

## Step 3: Copy INSTRUCTION.md — 2026-06-26T18:40:00.000Z

Copied ./INSTRUCTION.md → tasks/task_0669_snowmobile_powersport_rental_tour/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-06-26T18:44:00.000Z

**Output:** workspace/PRD.md (~272 lines, ~6,600 words).

### Section Structure
- §1 Introduction — framing the snowmobile/powersport rental-and-tour domain + four complexity concerns.
- §2 Global Specifications — 10 subsections: 2.1 RBAC (5 roles), 2.2 Response Structure, 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Hierarchical/Cascade Consistency, 2.6 OCC on confirm, 2.7 Capability-Class ordering, 2.8 Precision/rounding, 2.9 Logical Clock, 2.10 Nested-resource/existence ordering.
- §3 Business Logic — 9 lifecycle-organized subsections.
- §4 Endpoint Definitions — 40-row table.
- §5 Error Catalogue — 22-row table.

### Coverage confirmation (Hard Contracts — all PASS)
- Contract 1 — Field-Name Coverage: 56/56 entity fields, 43/43 endpoint inputs, 2/2 query_params. PASS.
- Contract 2 — Rule Coverage: OCC, all 9 state machines, all 7 calculations, validation priority sequence, multi-scope rules. PASS.
- Contract 3 — §3 Path Purity: 0 path tokens / bare methods in §3. PASS.

Withheld SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml were not opened.

## Steps 5 & 6: Unit Tests + Implementation (concurrent) — 

## Step 7: Run Tests and Iterate — 2026-06-26T19:56:22.000Z

All 8 parallel rounds pass cleanly (68/68 each). Exiting with the summary.

---

**Summary**

- **Iterations run:** 2 sweeps. Sweep 1 surfaced 3 deterministic failures (each round 67/70, all in `test_02_state_machines.py`). Sweep 2 after fixes: all 8 rounds 68/68.

- **Tests deleted (2):**
  - `test_sign_waiver_underage_without_guardian_ack_returns_invalid_request` — **ERROR-ID SILENCE** (STEP 1b). PRD §3.1 says a minor signing without `guardian_ack` "cannot advance" but names no error_id. "Cannot advance" reads at least as naturally as a blocked transition (`ERR_INVALID_STATE`, what the impl returns) as a request-validity failure (`ERR_INVALID_REQUEST`, what the test demanded). Two divergent PRD-faithful readings → not uniquely derivable. Scaffold rule that drove it: `Corner/state_machines/sign_waiver_underage_without_guardian_ack` grounded on `state_machines.Member.UNSIGNED_to_SIGNED` + `errors[ERR_INVALID_REQUEST]` (an error_id chosen by the scaffold, not stated in PRD prose).
  - `test_maintenance_unit_then_confirm_blocked_invalid_state` — **ENUM-MEMBERSHIP-ONLY / ERROR-ID SILENCE** (STEP 1a/1b). The confirm-gate sequence in PRD §3.4 is presented as exhaustive ("the confirmation-specific business gates fire in this exact sequence: ...") and contains no unit-availability/MAINTENANCE gate; the §3.2 sentence "the chosen unit moves from `AVAILABLE` to `RESERVED`" is a happy-path side-effect description, naming no confirm-time rejection or error_id. A faithful PRD-only implementer following the closed gate list lets the confirm proceed (as this impl does). Scaffold rule that drove it: `Corner/state_machines/maintenance_unit_then_confirm_blocked_invalid_state` grounded on the implicit `Unit.AVAILABLE_to_RESERVED` undefined-from-`MAINTENANCE` inference — which the scaffold's own Unit state machine never gates (its only confirm precondition is "no overlapping reservation").

- **Fixes applied to `test_suite/` (1):**
  - `test_02_state_machines.py`, `test_complete_cancelled_departure_returns_invalid_state` — STEP 2 test-bug fix plus sanctioned error-precedence relaxation. Original fixture issued `complete` from a guide never assigned to the departure, so the PRD §2.1/§3.9 ownership gate (which fires *before* the state gate) correctly returned `ERR_OWNERSHIP_REQUIRED`, not the asserted `ERR_INVALID_STATE`. Fixed the request identity to assign the guide before cancelling (genuine owner), and relaxed the assertion to `validate_error_is_one_of(["ERR_INVALID_STATE", "ERR_OWNERSHIP_REQUIRED"])` — both outcomes are PRD-named, and §3.6's "cancellation deactivates its guide assignments" leaves the active-vs-ever-assigned ownership reading undetermined, so the precedence outcome is not uniquely derivable. Also added `validate_error_is_one_of` to the imports.

- **Fixes applied to `implementation/`:** None. The implementation was PRD-faithful on all three counts; the failures traced to a test-fixture identity bug and two PRD-silent assertions.

## Step 8: Finalize PRD — 2026-06-26T20:00:00.000Z

Produced workspace/PRD_FINALIZED.md (Step 7 made 2 deletions + 1 test_suite fix, so Step 8 ran). Verbatim subagent summary:

**Line counts:** PRD.md = 272 lines; PRD_FINALIZED.md = 272 lines. %-delta = 0% in line count (2 lines revised in place, no insertions/deletions of lines).

**Changes (one per edit):**

- §2.1 (Guide role / ownership) — revise — Pinned "actually assigned" for the guide depart/complete ownership gate to mean holding a currently `active` `GuideAssignment`; clarified that a deactivated assignment (e.g. after the departure is cancelled or completed) no longer satisfies ownership, and that this ownership gate fires before the state gate, so it can take precedence even on a terminal-state departure. — `implementation/app.py:1287-1291` (`_guide_assigned` requires `active`), used by `complete_departure` (app.py:722) and `depart_departure` (app.py:687); deactivation in `services.py:93-101`, `app.py:737`.
- §3.1 (Waiver signing) — insert — Pinned the error_id for a minor signing without `guardian_ack`: "cannot advance and is rejected with `ERR_INVALID_STATE`." — `implementation/app.py:240-241`.

**Item 2 (maintenance-then-confirm): no edit.** The PRD §3.4 confirm-gate sequence is presented as exhaustive and contains no unit-availability/MAINTENANCE gate; the "moves from AVAILABLE to RESERVED" phrasing is a happy-path side-effect description. The impl confirms unconditionally (no unit-status gate; `app.py:900` sets `RESERVED` regardless of prior status), which is exactly what the PRD-as-written already determines. No PRD silence and no mismatch, so no patch — consistent with the step_7_diff's own conclusion that the impl was PRD-faithful.

**Per-edit pre-edit search log:**

- Edit 1 — §3.1 underage waiver error_id.
  - (a) Subject: the error_id returned when a minor signs without `guardian_ack`.
  - (b) Enumerated/read paths: `sign_waiver` handler (`app.py:222-246`) — the only signing path. Both the state gate (UNSIGNED/EXPIRED, line 235-236) and the age gate (line 240-241) return `ERR_INVALID_STATE`. No other handler signs/expires a waiver against this gate (`expire_waiver` at 249-255 is a separate re-evaluation path returning no error). `calc.WAIVER_ADULT_AGE = 18` (`calculations.py:26`) confirms the age threshold.
  - (c) Wording adjustment: none needed; the impl uses a single consistent error_id (`ERR_INVALID_STATE`) for this gate, so the literal pin is consistent with every enumerated path.

- Edit 2 — §2.1 guide ownership = active assignment.
  - (a) Subject: what "actually assigned" / "assigned to lead" means for the guide depart/complete ownership gate, and its precedence vs the state gate.
  - (b) Enumerated/read paths via `grep` for `_guide_assigned`, `active`, `OWNERSHIP`: sole ownership predicate `_guide_assigned` (`app.py:1287-1291`, requires `a["active"]`); callsites `depart_departure` (`app.py:687`, before state gate at 691) and `complete_departure` (`app.py:722`, before state gate at 726); deactivation sites `deactivate_departure_guides` (`services.py:93-101`) invoked by `cancel_departure_internal` (`services.py:118-127`) and `complete_departure` (`app.py:737`); parallel `active`-only uses in `_guide_double_booked` (`app.py:1273`) and `_maybe_return_guide_available` (`services.py:104-112`); §3.9 prose (line 198) that restates the rule and defers to §2.1. No path confers ownership via an inactive assignment.
  - (c) Wording adjustment: kept the parenthetical broad ("cancelled or completed, which deactivates its assignments") to cover both deactivation triggers; phrased the precedence claim as "can take precedence ... even when the departure is already in a terminal state" (softened with "can") rather than asserting a single fixed outcome, since the precedence is real but the §3.9 prose still routes through §2.1 — this avoids over-claiming while remaining consistent with both depart and complete callsites and with line 198.

## Step 9: Complete PRD — 2026-06-26T20:05:58.000Z

Produced workspace/PRD_COMPLETED.md (started from PRD_FINALIZED.md). Verbatim subagent summary:

Source: `PRD_FINALIZED.md` (exists) → copied to `PRD_COMPLETED.md`, then edited.

Line counts: both 272 lines (all edits in-paragraph; no lines added/removed). Char delta: 45431 → 48807 (+3376 chars).

Counts: 13 paragraph edits — 7 ambiguity-pins, 6 mismatch-revisions.

Per-change:
- §2.1 RBAC — insert — ambiguity — pinned that a Member may only read a Member record / list a member's reservations / sign a waiver when the target id equals their X-User-ID (else ERR_OWNERSHIP_REQUIRED) — app.py:217, 227-228, 292-293
- §2.4 Common Resource Properties — insert — ambiguity — pinned that `created_at`/`updated_at` are stamped from real wall-clock UTC, not the logical clock (which governs only domain time fields) — db.py:47-49 vs 52-54
- §3.1 Waiver — insert — ambiguity — pinned that signing from a non-UNSIGNED/EXPIRED state gives ERR_INVALID_STATE and the state gate precedes the age/guardian gate — app.py:235-236, 240-241
- §3.1 Training — insert — ambiguity — pinned `level` must be BASIC or ADVANCED (else ERR_INVALID_REQUEST) and that a wrong next-step / advance-from-ADVANCED / unsigned-waiver NONE→BASIC gives ERR_INVALID_STATE — app.py:264, 269-283
- §3.2 Unit maintenance — insert — ambiguity — pinned ERR_INVALID_STATE for entering MAINTENANCE when not AVAILABLE and for return_to_service when not MAINTENANCE; `return_to_service` defaults false — app.py:477-492
- §3.3 Assign-guide — revise — mismatch — pinned gate order: state (ERR_INVALID_STATE) → double-booked (ERR_GUIDE_DOUBLE_BOOKED) → class (ERR_GUIDE_CLASS_TOO_LOW); PRD had class before double-booked and no state gate — app.py:604-614
- §3.3 Unassign-guide — insert — ambiguity — pinned ERR_INVALID_STATE when no active assignment exists and that the response returns the updated TourDeparture — app.py:646-647, 653
- §3.3 Lock — revise — mismatch — pinned gate order: state → guide-ratio → trail-closed; PRD listed trail-closed first then ratio — app.py:663-674
- §3.6 Depart — insert — ambiguity — pinned ERR_INVALID_STATE for non-LOCKED state and for clock-before-starts_at, with trail-closed checked after the state gate — app.py:691-701
- §3.6 Check-out (individual) — revise — mismatch — pinned DispatchOperator is also authorized, no guide-ownership gate, and ERR_INVALID_STATE conditions; PRD said Guide only — app.py:922-940
- §3.6 Complete — insert — ambiguity — pinned ERR_INVALID_STATE for non-DEPARTED state or any still-CHECKED_OUT reservation — app.py:726-734
- §3.9 Return / gear loss (two sentences) — insert — ambiguity — pinned that only the reservation's own helmet/suit slots count for retirement and gear_loss; other lost_gear_ids are ignored; list is validated only as a list — app.py:979-982, 1001-1007
- §3.9 No-show — insert — ambiguity — pinned ERR_INVALID_STATE (non-CONFIRMED or departure not LOCKED/DEPARTED) and ERR_DUPLICATE (already settled) — app.py:1054-1065
- §4 Endpoint table (`/reservations/{id}/settlement`) — revise — mismatch — pinned that it returns an `array` of the reservation's settlements ordered by `created_at`; PRD implied a single object — app.py:1150-1152

Note: list-endpoint filter query params (`reservation_status`, `status`, `active`, and the `/reservations` field filters) are additive impl features not promised by any PRD prose, so they were left undocumented to keep the patch minimal (no existing PRD claim is contradicted).
