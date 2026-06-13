# Worklog — task_0298_wedding_event_venue_booking

## Step 1: Create Task Directory — 2026-06-11T08:52:25.000Z

Created `tasks/task_0298_wedding_event_venue_booking/` with `workspace/` subdirectory. Index pre-assigned (0298). Verified `INSTRUCTION.md` exists at project root for Step 3 copy.

## Step 2: Generate Scaffold — 2026-06-11T09:11:00.000Z

All three files parse cleanly and the lint verdict is clean. The scaffold for task 0298 is complete.

## Summary

Generated three scaffold artifacts for **Wedding & Event Venue Booking** at the **Expert** difficulty band. All pass `scaffold_lint.py` with **VERDICT: clean lint** (478 §1.8/§1.9 calls conform to §1.5; all 16 FKs have reverse-reachability).

**Complexity profile:** primary archetype temporal_windowing + secondary quota_allocation; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation; hybrid topology; parallel state-machine shape; peer_roles.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **13 entities** — Venue, Space, Package, Client, Coordinator, Booking, SpaceHold, PaymentMilestone, Payment, Vendor, GuestCountGuarantee, Walkthrough, RescheduleRequest (16 FKs incl. self-referential `RescheduleRequest.supersedes_request_id`)
- **5 state machines** — Booking carries two parallel axes (`booking_status` lifecycle + `payment_status` settlement); SpaceHold branching (HELD→{COMMITTED,RELEASED}); Vendor cyclic (CLEARED↔PENDING on COI); RescheduleRequest cyclic negotiation (PROPOSED↔COUNTERED with supersede). 1 concurrency rule (OCC on `Booking.version` for hold-create supersede).
- **5 calculations** — provisional vs final event charge (F&B floor `max`, nested service→tax rounding), milestone waterfall (remainder absorbed by FINAL), tier×status cancellation refund, coordinator load aggregation. All literals pre-computed in Python (provisional 3135200, final 3464600, refund 587850, etc.).
- **21 validations** (priority-ordered, 8 categories), **46 endpoints**, **23 error codes**, **4 RBAC roles** (VenueAdmin/FinanceOfficer opaque; Coordinator/Client entity_backed).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** 9 rule_ids × **2 instances = 18 total** (meets the ≥18 floor), each with fully structured `setup_api_calls`/`trigger`/`assert` chains and literal-locked numeric asserts.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** 9 sections, **38 instances** (30 active test recipes + 8 `excluded_because` stubs, all referencing valid §1.8 instance names). No duplicate names across the union of §1.8 and §1.9.

**Note:** `api_prefix: "/"` (root) because the API is genuinely flat across multiple top-level collections. Fixed two enum-closure / wording issues during review (removed dead `FORCE_MAJEURE_WITHDRAWAL` cancel reason; clarified priority-15 vendor-COI check and the final-charge formula comment).

## Step 3: Copy INSTRUCTION.md — 2026-06-11T09:11:20.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0298_wedding_event_venue_booking/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-11T09:17:06.000Z

PRD generated at `workspace/PRD.md` (271 lines). All three hard-contract checks PASS (field coverage 71/71, rule coverage all expressed, path purity 0 violations).

**Structure:** §1 Introduction; §2 (9 subsections: RBAC, Response Structure, Pagination, Common Resource Properties + versioning, Hierarchical Consistency, OCC on hold creation, two-axis state model, monetary precision, validation ordering); §3 (10 business-logic subsections); §4 endpoint table (45 endpoints); §5 error table (23 codes).

**Coverage:** 13 entities, all 75 field/param names present; 45 endpoints; all 23 error codes catalogued with trigger conditions.

**Notable scattering:** hold-create params split (space_id/block_role in §3.3, expected_booking_version in §2.6+§3.3); 6-hour soft-hold window, 25%/35% milestone split, 3×3 cancellation retention table embedded in prose; dual-variant charge (provisional over expected_guest_count + HELD/COMMITTED holds; final over guaranteed_count + COMMITTED-only, "replaces entirely") written twice from both trigger points.

## Step 5: Generate Unit Tests — 2026-06-11T09:31:52.000Z

Generated complete test infrastructure under `test_helpers/` (9 modules) and `test_suite/` (7 files, 64 test functions).

**test_helpers/:** types.py (Payment omits version/updated_at), api_client.py (~40 endpoints), api_errors.py (22 errors + HTTP map), assertions.py, factories.py, constants.py (charge math provisional 3,135,200 / final 3,464,600 / milestone split 783,800·1,097,320·1,254,080 + retention table), test_users.py (opaque VenueAdmin/FinanceOfficer + per-instance coordinator/client builders), fixtures.py (setup chains threading OCC version + entity-backed identity), __init__.py.

**test_suite/:** conftest.py + test_01…test_07 by domain (inventory/CRUD, RBAC, charges/milestones, lifecycle, holds/concurrency, validations, cascades/refunds).

**Coverage:** Queue A (Difficulty) 17/18 translated (1 skipped: `cross_entity_state_dependency/guarantee_blocked_when_vendor_not_cleared` — unique-derivability fail, PRD never states which roles require COI). Queue B (Corner) 29/30 non-stub translated (1 skipped: `validations/guarantee_after_deadline_rejected` — guarantee window length unspecified in PRD). 8 excluded_because stubs correctly untranslated.

**Audits passed:** all 64 tests carry exactly one resolving Design: tag; all PRD citations verbatim grep-match; no scaffold/§1./Table leakage; no skip/xfail markers; 64 tests collect cleanly.

**Design note surfaced:** parallel-axes "DEPOSIT_PAID while HELD" sub-claim contradicts PRD §3.5 (milestone schedule built at confirmation) — not asserted; instance's two tests assert uniquely-derivable facets instead.

## Step 6: Generate Implementation — 2026-06-11T09:31:52.000Z

Complete Python + Flask implementation in `workspace/implementation/`.

**Files:** start.sh (reads $PORT default 10000, guards pip install, exec python3 app.py, binds 0.0.0.0 threaded), requirements.txt (flask==3.0.3), app.py (46 routes), db.py (in-memory dicts, monotonic _seq, simulated clock, no seeding), errors.py (23-entry catalog), response.py (envelope helpers), common.py (auth, time, round-half-up, validators, pagination), services.py (calculations + cascades), serializers.py (Payment omits version/updated_at).

**Endpoints:** all 46 (venue/space/package/coordinator/client CRUD+list; booking create/get/list/assign-coordinator; holds; lifecycle place-hold/confirm/guarantee/complete/cancel/expire-hold; payments+milestones; vendors+COI; walkthroughs; reschedule propose/counter/approve/decline/withdraw; /_clock/set).

**State machines:** Booking lifecycle (INQUIRY→HELD→CONFIRMED→GUARANTEED→COMPLETED, +CANCELLED); Booking settlement parallel axis (UNPAID→DEPOSIT_PAID→PARTIALLY_PAID→PAID_IN_FULL, →REFUNDED); SpaceHold (HELD→{COMMITTED,RELEASED}); Vendor (PENDING↔CLEARED, →REJECTED, bounce on reschedule); RescheduleRequest (cyclic PROPOSED↔COUNTERED with supersedes chaining).

**Calculations:** provisional charge (expected_guest_count, HELD|COMMITTED) / final charge (guaranteed_count, COMMITTED-only) — F&B floor max, service then tax round-half-up, distinct-space rental (3135200/3464600 verified); milestone split 25%/35%/remainder (783800/1097320/1254080); waterfall by ascending sequence; cancellation refund tier×status table + force-majeure branch; coordinator load; space overlap padded by turnover_buffer; walkthrough plain overlap.

**Validation ordering:** auth(401)→role(403)→ownership(403)→path-existence(404)→body-FK(404)→shape(422)→time-window(422)→state(409)→OCC(412)→business. OCC on hold-create only.

**Two unstated-constant decisions:** guarantee window = 14 days; coi_required defaults true for all vendor roles. (Both are PRD-silent — flagged for Step 7/8/9 attention.)

## Step 7: Run Tests and Iterate — 2026-06-11T09:39:22.000Z

Clean 8-round parallel sweep: all 8 rounds 63/63, no missing files, no failures. The loop is complete.

**Iterations run:** 2 sweeps (initial baseline + 1 fix verification), plus a final confirmation sweep.

**Initial state:** All 8 rounds consistently 63/64 — a single test failing in every round: `test_vendor_coi_reupload_before_event_rejected` (`Expected response_type 'error', got 'object'`).

**Tests deleted (1):**
- `test_vendor_coi_reupload_before_event_rejected` (in `test_suite/test_07_cascades_and_refunds.py`) — **PRD-silence category: UNIQUE-DERIVABILITY collapse (STEP 1b)**. The test asserts that re-uploading a COI expiring before `event_date` onto an already-`CLEARED` vendor is rejected with `ERR_COI_EXPIRES_BEFORE_EVENT`. PRD §3.6 contains two directly conflicting verbatim sentences for exactly this scenario:
  - Sentence A: "If the uploaded certificate expires before the event date, the upload is rejected with `ERR_COI_EXPIRES_BEFORE_EVENT` (HTTP 422)."
  - Sentence B: "A vendor already `CLEARED` can bounce back to `PENDING` — either through an upload whose new `coi_expires_on` falls before `event_date`, or through system revalidation when a reschedule moves `event_date` later..."

  A faithful PRD-only implementer can produce two divergent implementations for the CLEARED-vendor-plus-early-COI case: (1) reject per Sentence A, or (2) bounce to PENDING and return success per Sentence B. The shipped implementation chose Sentence B. Since both readings trace to a verbatim PRD sentence, the PRD does not uniquely determine the outcome → deletion per the cardinal rule. The test's own docstring even names the design intent `vendor_coi_reupload_cycles_cleared_back_to_pending` (the bounce/success path), contradicting its own assertion.

  Note: the distinct reschedule-revalidation bounce path (Sentence B's second clause) remains covered and passing via `test_force_majeure_approval_bounces_vendor_to_pending`, which is uniquely determined by PRD §3.10 and was not touched.

**Fixes applied to test_helpers/:** None.

**Fixes applied to implementation/:** None — the implementation's COI-upload handler (`app.py:upload_coi`, lines 832–864) implements a PRD-faithful reading (Sentence B) and required no change.

**Final result:** Two consecutive full 8-round parallel sweeps both clean at 63/63 across all 8 rounds. No flakiness observed.

## Step 8: Finalize PRD — 2026-06-11T09:42:09.000Z

Produced `workspace/PRD_FINALIZED.md` (271 lines, 0% line-count delta, 1 line revised ≈0.4%).

**Change made (one bullet):**
- **§3.6 (Vendor COI clearance)** — *revise* — Scoped the early-expiry rejection so `ERR_COI_EXPIRES_BEFORE_EVENT` fires only when the vendor is **not** already `CLEARED`; a vendor already `CLEARED` instead bounces to `PENDING` (HTTP 200 success, `coi_on_file` false, new early `coi_expires_on` recorded). Also broadened "moves from `PENDING` to `CLEARED`" → "moves to `CLEARED`" on a valid upload. — `implementation/app.py:847-862` (`upload_coi`).

**Why only one edit:** The Step 7 diff contained exactly one item (deletion of `test_vendor_coi_reupload_before_event_rejected`, UNIQUE-DERIVABILITY collapse). PRD §3.6 carried two verbatim conflicting sentences (Sentence A reject vs Sentence B bounce); impl chose B for CLEARED case, A for non-CLEARED case. Edit pins exactly that reconciliation. No impl/test_helpers fixes were listed, so no other PRD edits trace to a Step 7 item.

**Pre-edit search log:** Subject = COI-upload early-expiry behavior. Enumerated impl paths: upload_coi (app.py:832-864, Step 7 site), add_vendor (798-819, unaffected), reject_vendor (867-878, separate), approve_reschedule revalidation (1166-1175, keeps old coi_expires_on — left phrased generically), guarantee_booking gate (575, unaffected). Wording adjustments: (1) upload-bounce clause records NEW coi_expires_on but not generalized to reschedule path which keeps old; (2) softened "from PENDING to CLEARED" → "to CLEARED" (impl sets CLEARED from any non-REJECTED prior); (3) left REJECTED-upload case unpinned (out of scope, identically silent in original).

## Step 9: Complete PRD — 2026-06-11T09:51:53.000Z

Produced `workspace/PRD_COMPLETED.md` from `PRD_FINALIZED.md` base. Lines 271→271 (all in-paragraph/in-cell, no new sections/lines). Chars 45,488→49,031 (+3,543).

**Counts:** 16 changes — 11 ambiguity-pins, 5 mismatch-revisions.

**Per-change:**
- §2.1 RBAC — insert — ambiguity — read endpoints apply auth+role only, never ownership; any authorized role may read any booking/sub-resource — app.py:341,447,472
- §2.4 Versioning — insert — ambiguity — `version` initial value 1 on creation — common.py:194
- §3.1 Venue — revise — mismatch — `timezone` stored/echoed but never consumed; date comparisons use calendar event_date + UTC clock date — common.py:66-67, services.py:304-307
- §3.2 Booking creation — revise — mismatch — capacity ceiling NOT checked at creation; enforced only at guarantee + reschedule approval against RECEPTION hold's space, satisfied when no RECEPTION hold — app.py:289-337,571,1118,721-730
- §3.5 Overpayment — insert — ambiguity — overpayment ceiling binds only when event_charge_cents>0; pre-confirmation deposits accepted regardless of amount — app.py:761-764
- §3.5 Milestone due_date — insert — ambiguity — interim+final milestones get same confirmation-date due_date as deposit — services.py:84-100
- §3.5 Settlement axis — insert — ambiguity — pre-confirmation DEPOSIT_PAID recognized via provisional threshold (25% of provisional charge) — services.py:187-191,208-215
- §3.6 coi_required — insert — ambiguity — coi_required always true for every vendor_role/venue — app.py:792-795
- §3.6 COI upload — insert — ambiguity — uploading COI to REJECTED vendor → ERR_INVALID_STATE (409) — app.py:844-845
- §3.7 Guarantee deadline — insert — ambiguity — guarantee window fixed 14 days — services.py:15
- §3.7 Guarantee preconditions — insert — ambiguity — OPEN DEPOSIT milestone at guarantee → ERR_DEPOSIT_NOT_SETTLED (402) — app.py:584-586
- §3.9 Refund payment — insert — ambiguity — system refund Payments carry method ACH, status POSTED — services.py:263-278
- §3.10 Counter/supersede — insert — ambiguity — bad supersedes_request_id → ERR_REFERENCE_NOT_FOUND (404); superseding non-COUNTERED → ERR_INVALID_STATE (409); other active requests block with ERR_RESCHEDULE_IN_PROGRESS — app.py:960-985
- §3.10 Force majeure — revise — mismatch — refund = amount_paid − event_charge when strictly positive, NO force_majeure_fee_pct deduction (fee stored but unused) — app.py:1177-1184
- §4 table (GET /bookings, /holds, /reschedule-requests) — revise — ambiguity — pinned concrete filter query-param keys — app.py:353,460,1026
- §4 table (GET /bookings/{id}/guarantee) — revise — mismatch — returns array of GuestCountGuarantee (response_type array), not single object — app.py:604-609

**Notes:** Tests used only for cross-reference. Already-pinned behaviors left unchanged (charge formulas, milestone split, retention table, 6-hour soft-hold, waterfall, walkthrough half-open overlap, validation priority ordering, Payment lean shape).

## Pipeline Complete — 2026-06-11T09:51:53.000Z

All 9 steps done. Final state: 63/63 tests passing across all 8 stability-sweep rounds. Artifacts: SCAFFOLD.yaml + 2 design indices, PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ (9 modules) + test_suite/ (7 files, 63 tests), workspace/implementation/ (Python+Flask, in-memory).
