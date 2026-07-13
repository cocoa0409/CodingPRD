# Worklog — task_0796_charity_donation_pickup

## Step 1: Create task directory — 2026-07-08T03:21:29.738Z

Created `tasks/task_0796_charity_donation_pickup/` and `tasks/task_0796_charity_donation_pickup/workspace/`. Pre-assigned directory used as-is (no auto-scan of ./tasks). Verified `INSTRUCTION.md` exists at project root.

## Step 2: Generate scaffold — 2026-07-08T03:48:00.000Z

All three files written and pass clean lint (fresh from scenario + skill spec, no sibling tasks consulted). Expert calibration.

Complexity profile: workflow_orchestration + temporal_windowing; hybrid topology; branching state-machine shape; layers = cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, derived_field_reconciliation, optimistic_concurrency; peer_roles; immediate consistency.

Counts:
- Entities: 10 (CharityPartner, Vehicle, Route, Donor, RecurringPlan, PickupRequest, DonationItem, RouteStop, DonationReceipt, HaulInvoice)
- Endpoints: 36 (incl. POST /_clock/set_current_utc, startup default 2026-03-01T00:00:00Z)
- State machines: 5 — Route (linear PLANNED→OPEN→CLOSED), PickupRequest (branching fork at complete: DONATION↔HAUL divergent side-effects), RecurringPlan (cyclic ACTIVE↔PAUSED→CANCELLED), DonationReceipt (ISSUED→VOIDED), HaulInvoice (INVOICED→PAID)
- Calculations: 6 — haul_fee (tiered, estimate vs final dual-variant), tax_receipt_value (round-per-item-then-sum dual-variant), declared_volume, route_reserved_volume, partner_ytd_donation_value, partner_diverted_weight
- Validations: 17 priority-ordered rows
- Error catalog: 29 codes
- Concurrency: 1 OCC rule (schedule-stale-route, Route.version, 412)
- §1.8 difficulty instances: 18 (all nine rules × 2)
- §1.9 corner instances: 25 active + 7 excluded_because stubs
- api_prefix set to "/" (root) — multi-collection design.

All three files yaml.safe_load clean. Scaffold subagent id a86cc591990761cd8.

## Step 3: Copy INSTRUCTION.md — 2026-07-08T03:49:22.804Z

Copied ./INSTRUCTION.md → tasks/task_0796_charity_donation_pickup/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-07-08T03:56:21.477Z

PRD generated at workspace/PRD.md (315 lines). All 3 hard contracts PASS.
- Contract 1 (Field-Name Coverage): 59/59 required fields present + all 8 query_params; PASS.
- Contract 2 (Rule Coverage): 17 validations, 1 OCC rule, 15 state transitions, 6 calculations, all cascades/side-effects; sibling-branch symmetry OK; PASS.
- Contract 3 (§3 Path Purity): 0 path/method tokens in §3; PASS.
- 36/36 endpoints documented (§4). 10 entities. 5 state machines. 6 calculations. 29 error codes (§5). 6 roles. 21 enum values verbatim.
- Withheld design files (DIFFICULTY/CORNER) not opened. PRD subagent id ae813fa5238e2f283.

## Step 5: Generate unit tests — 2026-07-08T04:18:28.953Z

test_helpers/ (9 files) + test_suite/ (conftest + 7 domain files). 61 test functions, all collect cleanly.
- Queue A (Difficulty): 36 tests — all 18 instances covered by exactly 2 each.
- Queue B (Corner): 25 tests — all 25 non-stub instances × 1 (7 excluded_because stubs correctly not translated).
- Every test has exactly one verbatim Design: tag; 0 C1 failures.
- Instances skipped: NONE — all passed PRD-first two-condition filter.
- Data correction flagged: Corner instance calculations/attended_surcharge_applied_to_haul_fee asserts final_cents==5500 in index but that's inconsistent with its own breakdown (3500+2000+2000=7500) and PRD formula; test asserts 7500 (PRD-derived). WATCH in Step 7.
- Test-gen subagent id a11866a8d41343bd9.

## Step 6: Generate implementation — 2026-07-08T04:18:28.953Z

workspace/implementation/: app.py (~900 lines, single file, in-memory dicts only, no seeding), requirements.txt (flask), start.sh (guards pip install on flask import probe, exec python3 app.py, binds 0.0.0.0:$PORT default 10000, threaded=True).
- 36 endpoints implemented incl. /_clock/set_current_utc; clock default 2026-03-01T00:00:00Z.
- Verified end-to-end via two scripted passes (DONATION round-then-sum, HAUL tiered+attended+diversion credit, YTD/diverted reconciliation, void compensation, OCC ERR_STALE_VERSION 412, all scheduling gates, route-window overlap, recurring cadence, validation precedence).
- PRD ambiguities resolved: version base=1; created/updated_at wall-clock UTC while logical clock drives date-sensitive rules; PATCH /partners ownership enforced for PartnerAdmin (§2.1); item appraisal gated on SCHEDULED; void recomputes diverted via COMPLETED formula (unchanged by void, only YTD drops); pagination out-of-range clamped, non-int → ERR_INVALID_REQUEST.
- Impl subagent id ab2bd9192b1cb455e.

## Step 7: Run tests and iterate — 2026-07-08T04:40:00.000Z

All 8 rounds pass 61/61. Clean sweep achieved.

Iterations run: 2 (initial 8-way concurrent sweep, then a fix + a 2-wave-of-4 sweep).

Tests deleted: None.

Fixes applied to test_suite/:
- test_03_validation_priority.py, test_porch_attestation_beats_capacity_when_both_violated — changed ctx setup disposition="DONATION" → "HAUL" (STEP 2 test-vs-PRD consistency fix). The ctx request exists only to pre-reserve 80 cf on a 100 cf truck so req_b's 40 cf overflows. As DONATION it violated PRD §3.4.6 (DONATION declared_volume_cf must be ≤ 50 cf else ERR_DONATION_OVER_LIMIT), so setup scheduling correctly failed 422. HAUL has no volume cap, preserving capacity-reservation intent without violating PRD. Implementation was correct and untouched.

Fixes applied to test_helpers/: None.
Fixes applied to implementation/: None.

Note: remaining first-sweep failures (test_adjacent_route_window_on_vehicle_allowed, test_haul_diversion_credit_bound_by_thirty_percent_cap, test_receipt_final_mirrors_declared_when_unappraised, test_receipt_provisional_rounds_each_item_before_summing) were spurious "API server could not be restarted" host-saturation ERRORs from the 8-way concurrent sweep, not implementation bugs; 2 sequential waves of 4 eliminated them → 61/61 all 8 rounds.

Special-watch item (attended_surcharge_applied_to_haul_fee, final_cents==7500) passed all rounds, not modified.

Fix subagent id a1d36748bb54f95f2.

## Step 8: Finalize PRD — 2026-07-08T04:42:00.000Z

Zero edits — PRD_FINALIZED.md is a verbatim copy of PRD.md (315/315 lines, 0% delta).
The single <step_7_diff> item (test_03 ctx disposition DONATION→HAUL) traced to PRD §3.4 rule 6 (DONATION ≤50 cf else ERR_DONATION_OVER_LIMIT) — impl app.py:825 + DONATION_MAX_CF=50 both already consistent with PRD.md:187. Pure fixture bug; no PRD-silence, no PRD/impl mismatch. Zero edits is the expected valid outcome. Subagent id abe1da01510634b38.

## Step 9: Complete PRD — 2026-07-08T04:30:18.525Z

PRD_COMPLETED.md written as minimal patch over PRD_FINALIZED.md (315→315 lines, +715 chars, all in-paragraph). 4 ambiguity-pins + 2 mismatch-revisions.
- §3.1 Provisioning — revise — mismatch — suspended-partner enforcement scoped to plan-resume only (impl only enforces ERR_PARTNER_SUSPENDED on resume; no gate on request create/schedule/complete) — app.py:1129-1131.
- §3.1 Provisioning — revise — mismatch — donor email uniqueness NOT enforced (no dup-email check/error in impl) — app.py:640-656.
- §2.7 OCC — insert — ambiguity — omitted expected_route_version → non-matching → ERR_STALE_VERSION (not a field-validation error) — app.py:851-853.
- §3.3 Routes — insert — ambiguity — closing an OPEN route with a still-RESERVED stop → ERR_ROUTE_INVALID_STATE — app.py:618-621.
- §3.5 Servicing — insert — ambiguity — appraising an item whose request is not SCHEDULED → ERR_REQUEST_INVALID_STATE — app.py:973-974.
- §3.6 Valuation — insert — ambiguity — appraised item with value but no appraised_condition falls back to declared_condition — app.py:382-388.
Note: undocumented route-stops-list status query filter (app.py:632) left undocumented — convenience filter, no required-behavior impact. Subagent id ae86014bc3fe57612.

## Pipeline complete — 2026-07-08T04:30:18.525Z

Final verification: all 8 stability-sweep rounds pass 61/61. Artifacts present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/ (9), test_suite/ (conftest + 7), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}.
