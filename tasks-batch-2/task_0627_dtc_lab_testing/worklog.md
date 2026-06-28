# Worklog — task_0627_dtc_lab_testing

Scenario: Direct-to-Consumer Lab Testing (Quest/Labcorp OnDemand style): test catalog & physician-order (PWN) network, cart & self-pay pricing, patient-service-center scheduling vs at-home kit, specimen processing & result release (critical-value protocol), HSA/FSA payment, abnormal-result telehealth referral, repeat/panel bundle, data privacy

Difficulty: Expert (passed to prd-bench-scaffold-generator)

## Step 1: Create Task Directory — 2026-06-22T17:29:29.000Z

Created `tasks/task_0627_dtc_lab_testing/` and `tasks/task_0627_dtc_lab_testing/workspace/`. Pre-allocated directory used directly (no auto-numbering scan). INSTRUCTION.md confirmed present at project root.

## Step 2: Generate Scaffold — 2026-06-22T17:52:00.000Z

All three required scaffold files generated and verified (Expert difficulty).
- `SCAFFOLD.yaml` (1458 lines, §1.0–§1.7 + complexity_profile + pinned domain_constants; no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1218 lines, single key scaffold_difficulty_design — §1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (1836 lines, single key scaffold_corner_design — §1.9)

Complexity profile: workflow_orchestration × pricing_engine; flat FK topology; parallel state-machine shape; segregation_of_duties role model; immediate consistency. Layers: dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency.

Scaffold scale (Expert band):
- Entities: 15 (TestOffering, PanelBundle, Patient, Cart, CartLine, Order, OrderLine, PhysicianOrder, Appointment, HomeKit, Specimen, LabResult, TelehealthReferral, AnalyzerRun, Payment)
- State machines: 6 — PhysicianOrder (cyclic review loop), OrderLine (branching+revert), Order (parallel payment × fulfillment axes), LabResult (non-linear critical-value branch), Appointment, AnalyzerRun
- Concurrency rules: 2 (OCC on Cart.version at checkout; OCC on Order.version at capture)
- Calculations: 5 (cart_estimated_total vs order_final_invoiced_total dual-variant pricing; hsa_capture_split pinned-eval-order; result_provisional_flag vs result_final_flag delta-check dual-variant)
- Validations: 23 (priority-ordered, half-priority 15.5 for buffered-overlap rule)
- Endpoints: 56; Errors: 37; Roles: 5 (CatalogAdmin, Patient[entity_backed], OrderingPhysician, PhlebotomyTech, LabTech — all opaque except Patient)
- §1.8: 9 difficulty rules × 2 = 18 instances; §1.9: 49 corner instances across 9 sections (incl. 2 excluded_because stubs)
- scaffold_lint.py → VERDICT: clean lint (56 endpoints, 15 entities, 531 calls, 0 violations)

## Step 3: Copy Shared Files — 2026-06-22T17:52:37.000Z

Copied `INSTRUCTION.md` → `tasks/task_0627_dtc_lab_testing/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-22T17:58:29.000Z

Generated `workspace/PRD.md` (313 lines) for DTC Lab Testing platform. Generated from SCAFFOLD.yaml only; both design YAMLs confirmed not read; no sibling tasks inspected.

Structure: 5 top-level sections (Introduction; Global Specifications; Business Logic & Workflows; Endpoint Definitions; Error Code Catalogue); 9 §2 subsections (RBAC, §2.2 envelope, pagination, common properties + logical clock, nested-resolution/validation-ordering, hierarchical cascades, pricing/precision, OCC, segregation-of-duties + data privacy); 9 §3 subsections (catalog curation; cart assembly; forward-looking cart estimate; checkout; PWN network + fulfillment eligibility + collection; chronological invoice + HSA settlement; scheduling/completion/capture/cancellation; processing + critical-value + release + referral; analyzer-run reservation).

Hard-contract self-checks reported PASS: field coverage 72/72; rule coverage (validations ordering, 2 OCC rejections, all state transitions, 5 calculations reconstructible, all 37 error IDs matchable, cascades/side-effects expressed, sibling-branch symmetry); path purity (460 backtick tokens scanned, 0 path/method tokens in §3). Pricing constants embedded: per-line round-half-up, tier thresholds 20000/50000 cents, delta 50, rate 0.15.

## Step 5: Generate Unit Tests — 2026-06-22T18:14:30.000Z

Generated test_helpers/ (9 files: types, api_client, api_errors, assertions, factories, constants, test_users, fixtures, __init__) and test_suite/ (conftest + 9 test files). 83 tests total, all collect cleanly.
- Queue A (Difficulty): 36 tests — all 18 instances (9 rules × 2) covered with ≥2 tests each (test_05–test_07).
- Queue B (Corner): 47 tests — all 47 non-stub instances covered with ≥1 test each (test_01–test_04, test_08, test_09).
- Skipped: none weakened/stubbed. The two excluded_because corner stubs (payment_not_refundable_when_never_authorized; lab_tech_release_own_collected_specimen_sod_denied) correctly NOT translated; cross-refs resolve to real difficulty instances.
- Audits passed: every docstring ends with exactly one Design: tag resolving to a real instance; all 119 quoted PRD citations verbatim; no skip/skipif/xfail; all files byte-compile; test_helpers imports cleanly.

## Step 6: Generate Implementation — 2026-06-22T18:14:30.000Z

Built Python + Flask implementation in workspace/implementation/ (24 source files). start.sh boots cleanly (reads $PORT default 10000, binds 0.0.0.0, foreground exec).
- Foundation: app.py, db.py (in-memory dicts, common-field minting, touch() version-bump, deterministic created_at tie-break via _seq), clock.py (logical clock default 2026-01-01T00:00:00Z), errors.py, response.py, middleware.py (X-User-ID/X-User-Role + RBAC), requirements.txt.
- Routes: 12 blueprints; Services: 5 (pricing, carts, orders, results, common). All 55 endpoints from PRD §4 implemented across 15 entities.
- Parallel Order axes (payment_status × fulfillment_status); fulfillment derived from line states (never set directly). Cascades: physician decline; result release (consent-gated referral); cancel 3-hop with HSA restore.
- Dual-variant pricing: forward cart estimate (all lines) vs chronological invoice (RESULTED lines only, full-bundle-only substitution). Clinical flags: bounds-only provisional vs delta-checked final (≥50 swing escalates one severity step). OCC checked before state preconditions (ERR_STALE_CART_VERSION/ERR_STALE_ORDER_VERSION 412). Validation precedence: auth(401)→role(403)→owner(403)→existence(404)→body(422)→OCC(412)→state(409)→business.
- In-memory only; store empty on every boot; reboot test confirmed 0 entities + clock at default. Subagent smoke-tested happy path, HSA settlement, SoD, critical callback, PWN restriction, OCC, bundle substitution, repeat discount, delta-check escalation, cancel refund, analyzer overlap.
- Note: Step 6 reports 55 endpoints vs Step 2's 56 — to be reconciled by Step 7 tests if material.

## Step 7: Run Tests and Iterate — 2026-06-22T18:14:30.000Z (completed)

Two consecutive clean 8-round parallel sweeps (81/81 in all 16 rounds). Verified: all 8 final results.{1..8}.json show 81/81.

Iterations run: 3 (baseline 38/83 → 79/83 → clean 81/81, confirmed twice).

Dominant failure was a single shared fixture bug: 43 of original 45 failures shared setup error `ERR_HOME_KIT_STATE_BANNED - Offering is not home_kit_eligible`. Fixtures drove orders through the HOME_KIT path using offerings whose `home_kit_eligible` defaults false (PRD §3.1), so the PRD-faithful impl correctly rejected home-kit minting (PRD §3.5). Test-helper bugs, not impl bugs.

Tests deleted (2): both in test_suite/test_07_constraints_depth.py, category STEP-1b unreachable-state / PRD-uniquely-determines-the-opposite-outcome, driven by scaffold rule Difficulty/compensating_invariant/hsa_balance_conserved_on_capture_then_cancel_refund:
- test_hsa_balance_conserved_after_capture_then_cancel_refund
- test_captured_payment_refunded_on_cancel
Both capture a payment (PRD §3.7 permits only when fulfillment_status==COMPLETED, which has a RESULTED line) then assert cancel SUCCEEDS, but PRD §3.7 states a cancellation against an order with a resulted line is rejected with ERR_ORDER_HAS_RESULTED_LINES. CAPTURED→REFUNDED via Patient cancel is unreachable (capture-eligible and cancel-eligible fulfillment states are disjoint).

Fixes applied to test_helpers/ (test_helpers/fixtures.py):
- Added _offering_overrides_for_mode, applied in setup_single_line_order and setup_order_with_fund_source — HOME_KIT fixtures now create home_kit_eligible=True offerings (PRD §3.5 requires the flag; defaults false).
- Changed shipping_state_code default "CA" → None (ships to patient's own state_code) across order/collected/processed/released fixtures — PRD §3.5 requires shipping state == patient state; hardcoded "CA" wrongly tripped ERR_HOME_KIT_STATE_BANNED for patients elsewhere (e.g. state_code="XX" PWN-unlicensed test).
- Rewrote give_patient_released_result to use the PSC fulfillment path (book + check-in a unique non-overlapping appointment) instead of a home kit, so it works for any offering regardless of home_kit_eligible.

Fixes applied to test_suite/ (offerings flowing into inline HOME_KIT orders now created home_kit_eligible=True): test_05_pricing_depth.py (A/B/C/D bundle-void), test_06_workflow_depth.py (GLU delta-check, F/TST2 decline), test_09_access_and_concurrency.py (OK1 OCC-checkout).

Fixes applied to implementation/ (workspace/implementation/routes/orders.py):
- place_order: reordered validation so cart_id existence (ERR_NOT_FOUND) is checked before body well-formedness (ERR_INVALID_REQUEST), per PRD §2.5 precedence.
- capture_payment: removed recompute_invoice(order) call. PRD §3.6/§3.7 finalize the invoice at COMPLETED, not at capture; recomputing at capture re-derived hsa_applied against current balance and masked ERR_INSUFFICIENT_HSA_FUNDS when HSA was drained after completion. Capture now settles the finalized invoice and checks the finalized draw against current balance.

## Step 8: Finalize PRD — 2026-06-22T18:39:27.000Z

PRD_FINALIZED.md created as a verbatim copy of PRD.md (313 lines each, identical — confirmed by diff). Zero edits made: every step_7_diff item traces to behavior the PRD already uniquely determines — none reveal a PRD silence or PRD/impl mismatch.

Why no edits (per item):
- Shared fixture bug (43/45, ERR_HOME_KIT_STATE_BANNED): PRD §3.1 (home_kit_eligible defaults false) + §3.5 (flag required for home-kit minting/checkout) already pin this. Pure test-helper bug.
- 2 deleted tests (CAPTURED→cancel SUCCEEDS): PRD §3.7 already states cancel against an order with a resulted line is rejected with ERR_ORDER_HAS_RESULTED_LINES, and capture requires fulfillment_status==COMPLETED (requires RESULTED line). The CAPTURED→REFUNDED-via-Patient-cancel path is unreachable; impl matches PRD. No silence.
- test_helpers/test_suite fixes (offering overrides, shipping_state_code CA→None, PSC-path rewrite): all fixture bugs; PRD §3.5 already specifies shipping-state==patient-state, banned states, eligibility flag.
- impl fix (a) place_order reorder (NOT_FOUND before INVALID_REQUEST): PRD §2.5 already pins this precedence verbatim. NO-NEW-MISMATCH: enumerated other body-FK routes (home_kits, appointments, referrals, carts) found intentionally inconsistent ordering — any universal claim would create a new mismatch, so existing §2.5 scope left verbatim.
- impl fix (b) capture_payment removed recompute_invoice: PRD §3.6 lists exhaustive recompute triggers (release→RESULTED, specimen rejection) — capture not among them — and §3.7 says capture uses the finalized patient_due_cents/hsa_applied_cents and rejects with ERR_INSUFFICIENT_HSA_FUNDS. Already pinned. NO-NEW-MISMATCH: enumerated all recompute_invoice/line_terminal_cascade callsites — all RESULTED-release/specimen-rejection/decline paths, consistent with §3.6.

## Step 9: Complete PRD — 2026-06-22T18:47:11.000Z

PRD_COMPLETED.md produced from PRD_FINALIZED.md (313 lines; 46,576 → 50,386 chars, +3,810; no line-count change — all in-paragraph inserts/revisions, no new sections). 13 changes total: 11 ambiguity-pins, 2 mismatch-revisions.

Per-change:
- §2.2 — insert — ambiguity — api_request_timestamp is real wall-clock, not the logical clock (response.py:19 / clock.py:57-60)
- §2.3 — insert — ambiguity — created_at ties broken by creation order; Patient list endpoints auto-scope to owned rows (transitively); filter semantics (db.py:92-94, carts.py, orders.py, + analogous scoping across order_lines/appointments/home_kits/specimens/lab_results/referrals/payments)
- §2.4 — insert — ambiguity — clock-set returns {"now": <iso 3-frac-digit>} in data (only non-resource success body) (payments.py:41-50, clock.py:47-54)
- §3.2 — insert — ambiguity — release instant read from result updated_at; window closed [cart.created_at−365d, cart.created_at] inclusive both ends (carts.py:93-107)
- §3.4 — insert — ambiguity — Payment captured_amount_cents and hsa_drawn_cents both start at 0 (orders.py:108-116)
- §3.5 — revise — ambiguity — when all lines terminal but none RESULTED, fulfillment left unchanged; auto-resolution never sets CANCELLED (services/orders.py:52-65)
- §3.5 — insert — ambiguity — collect returns 201 with new Specimen in data (order_lines.py:90)
- §3.7 — insert/revise — ambiguity — invalid (non-BOOKED) check-in rejected with ERR_APPOINTMENT_NOT_CHECKED_IN (409); fasting check runs after BOOKED-state check (appointments.py:114-119)
- §3.7 — revise — ambiguity — cancel from fulfillment state outside the three cancellable states also yields ERR_ORDER_HAS_RESULTED_LINES; check order pinned (state → resulted-line → refundability) (orders.py:213-225)
- §3.8 — insert — ambiguity — minted LabResult carries analyzer_value, final_flag null, critical_acknowledged false; process returns 201 with LabResult (specimens.py:57-73)
- §3.8 — insert/revise — ambiguity — "escalated" = recomputed final_flag is ABNORMAL/CRITICAL (no compare to prior); guard "no non-CLOSED referral open"; amend does no cascade (lab_results.py:114-135, results.py:63-67)
- §3.8 — revise — MISMATCH — manual referral creation enforces only consent (not RELEASED, not abnormal/critical); referral_reason mirrors current final_flag; schedule unconditional; no CLOSE endpoint (referrals.py:16-29,57-67)
- §4 — insert — MISMATCH — collect/process/manual-referral return 201 (mint stand-alone resources); all other action endpoints return 200 (order_lines.py:90, specimens.py:73, referrals.py:29 vs 200 elsewhere)

Left unchanged (PRD already pins / impl matches): four-step pricing arithmetic & rounding (§2.7/§3.3/§3.6), subtotal_cents semantics, OCC version checks (§2.8), SoD & consent gating (§2.9), validation precedence (§2.5), capture not recomputing invoice, analyzer-run buffer overlap (§3.9).

## Pipeline Complete — 2026-06-22T18:47:11.000Z

All 9 steps complete. Final state: 81/81 tests passing across all 8 stability-sweep rounds. Artifacts present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/, test_suite/ (81 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ + results.{1..8}.json}.
