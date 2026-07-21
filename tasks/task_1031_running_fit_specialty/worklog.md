# Worklog — task_1031_running_fit_specialty

## Step 1: Create Task Directory — pre-assigned

Task directory `tasks/task_1031_running_fit_specialty/` was pre-assigned and already existed (with `workspace/`). Skipped the Step 1 index scan per launch instructions. Scenario: Running & Fit Specialty Store (gait analysis & fitment, shoe rotation & mileage-reminder, subscription/club & training-group, race-packet & event, wear/return policy, loyalty, nutrition/gear, inventory). Difficulty = Expert (scaffold-generator only).

## Step 2: Generate Scaffold — 2026-07-15T18:44:00.000Z

Expert scaffold generated; all three artifacts pass yaml.safe_load. Subagent verdict: clean lint — 54 endpoints, 11 entities, 18 §1.8 instances, 27 §1.9 instances (+6 stubs), 244 calls scanned; all §1.5 FK reverse-reachability present.

Complexity: primary temporal_windowing + secondary quota_allocation; flat topology (api_prefix ""); parallel state-machine shape; peer_roles; immediate consistency.
Entities (11): Member, Product, Order, OrderLine, WearReturn, Subscription, RunningShoe, Fitter, FitmentSession, TrainingSession, TrainingBooking (15 FKs).
State machines (7): Order payment dim; Order fulfillment dim [parallel]; WearReturn (branch + reject→resubmit); FitmentSession; RunningShoe (mileage threshold); Subscription (past-due cycle); TrainingBooking (waitlist promotion).
Calculations (7): inventory_available, effective_discount (nested-min stacking caps 0.12/0.20), order_pricing (provisional/final), loyalty_points_earned (estimated/settled, round-per-line), loyalty_tier, shoe_mileage_retirement, training_available_slots.
Validations: 11 priority tiers. Errors: 20. Roles: 4 (Member & Fitter entity_backed; StoreManager & Anonymous opaque). 1 OCC rule (price-override-stale-order on Order.version, 412). Clock endpoint /_clock/set_current_utc default 2026-07-01T00:00:00Z.

Note: race-packet/event subsystem intentionally folded out of core entity model; all other named subsystems modeled.

**Orchestrator patch (pre-Step-5):** SCAFFOLD.yaml referenced `SERVICE_BUFFER_MINUTES` (fitter buffer) in 3 places without declaring the value; §1.8 fitter_buffer_overlap_rejected pins it to 15 minutes. Patched all 3 SCAFFOLD sites (validation priority-7 check, POST /fitment-sessions description, ERR_FITTER_UNAVAILABLE condition) to state "SERVICE_BUFFER_MINUTES = 15 minutes" so the value flows into PRD and the fitter-buffer test survives unique-derivability. safe_load re-verified OK.

## Step 3: Copy Shared Files — 2026-07-15T18:47:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1031_running_fit_specialty/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-07-15T18:53:00.000Z

PRD.md generated (285 lines) from SCAFFOLD.yaml only; both design files withheld. All 3 doc-generator Hard Contracts pass: Field-Name Coverage 69/69; Rule Coverage (all transitions, cascades A/B + waitlist promotion, all 6 calcs, 11-tier validation precedence, OCC ERR_STALE_VERSION/412, all 20 errors); §3 Path Purity 0 tokens. 56 endpoints covered.

Sections: §1 Intro; §2 Global (RBAC 4 roles, response envelope verbatim, pagination, versioning+logical clock, money/rounding, inventory invariants, parallel order state+cascades, OCC, 11-tier validation precedence, reverse reachability); §3 Business Logic (9 subsections: membership/loyalty/tier, catalog/inventory, order creation+provisional pricing, payment/redemption/fulfillment/price-override/cancel, wear/return Cascade A, shoe rotation+mileage, subscriptions, fitment appointments, training+waitlist); §4 endpoint table; §5 error table.

Scaffold ambiguities resolved in prose by doc-gen:
1. Discount caps — inline formula comments (0.30/0.40) contradicted constants block (MAX_STACK 0.12 / MAX_TOTAL 0.20); doc-gen took the constants as authoritative → PRD states 0.12 member-stack cap / 0.20 hard ceiling / ≥5000 promo gate. **Orchestrator verified: matches §1.8 discount_stack_cap_and_total_ceiling_mode_a (0.20/2000) exactly — no test-skip risk.**
2. "Race packet within pickup window" clause omitted (no race-packet entity/endpoint; validation applies only to fitment-sessions + training-bookings).
3. "Returned line net" rendered as "the net amount attributable to the returned line" (scaffold gave no precise line-level allocation under order-level discounts).
4. FitmentSession.NO_SHOW listed as a valid status without a transition (no system transition defined; only TrainingBooking.NO_SHOW has one).

## Step 5: Generate Unit Tests — 2026-07-15T19:10:00.000Z

test_helpers/ (9 files: types.py 11 entity TypedDicts + 11 enums, api_client.py one-method-per-endpoint, api_errors.py 20 error IDs, assertions.py, factories.py, constants.py, test_users.py w/ make_member_headers + make_fitter_headers, fixtures.py composite lifecycle helpers, __init__.py). Imports verified clean against prd_bench_local_runner.testing.

test_suite/: 10 files, **63 tests**. Queue A (Difficulty) 36 = 18 instances × 2. Queue B (Corner) 27 = 27 non-stub instances × 1 (6 excluded_because stubs correctly not translated). **0 instances skipped** — all 45 passed the two-condition PRD filter. All 63 docstrings carry a valid Design: tag; 82 quoted PRD citations verified verbatim; pytest collects 63 with no import errors.

Judgment call flagged by test-gen: Corner/state_machines/c_order_cancel_after_cancelled_returns_invalid_state asserts ERR_INVALID_STATE for cancelling a terminal order — cited as the uniquely-derivable residual (the 4 specialized state errors have distinct non-matching triggers).

## Step 6: Generate Implementation — 2026-07-15T19:21:00.000Z

Python+Flask single-file impl at workspace/implementation/ (app.py ~1050 lines, requirements.txt flask==3.0.3, start.sh executable reads $PORT default 10000, binds 0.0.0.0, exec foreground). **54 routes implemented == 54 PRD endpoints** (route-count verified, guards against partial-write gap). ast.parse OK; boot smoke passed.

Storage: in-memory module-level DB dict keyed by UUID + STATE dict (logical clock default 2026-07-01T00:00:00Z, monotonic _seq for stable ordering). No startup seeding.

Key behaviors: exact response envelope + error body + pagination (limit clamp 100); 11-tier validation precedence with exact error IDs/codes; Decimal round_half_up pricing (0.12 stack cap / 0.20 ceiling / ≥5000 promo gate; provisional vs final; per-line-then-sum loyalty w/ tier multipliers); parallel Order state (payment × fulfillment); Cascade B (fulfill: stock drawdown, settle points, mint RunningShoe/SHOE-unit, tier-spend credit); Cascade A (return approve: refund + points/tier reversal); waitlist promotion; trailing-365-day tier spend vs logical clock; OCC on price-overrides (expected_order_version → 412); fitment temporal guards (past 422, member half-open overlap, 15-min fitter buffer).

Judgment call flagged by impl-gen: "returned line net" (Cascade A) has no explicit PRD allocation formula → used returned line's line_gross_cents (unit_price × qty); zeroes cleanly for single-line no-discount return.

## Step 7: Run Tests and Iterate — 2026-07-15T19:30:00.000Z

**Clean first-sweep pass.** Iterations run: 1 (single 8-round, 2-waves-of-4 parallel stability sweep via sweep.sh at task root). All 8 rounds reported 63/63 passed, 0 failed, 0 errors, 0 skipped (orchestrator re-verified each results.{1..8}.json). No union of failing tests → no diagnostic iterations needed.

Tests deleted: None. Fixes to test_helpers/: None. Fixes to implementation/: None.

Matches the clean-first-sweep pattern of prior Expert tasks (task_1027, task_1030). The pre-Step-5 SERVICE_BUFFER_MINUTES=15 patch + verified discount-cap alignment (0.12/0.20) evidently kept every difficulty/corner test uniquely-derivable from PRD prose.

## Step 8: Finalize PRD — SKIPPED — 2026-07-15T19:30:30.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, 0 implementation/ fixes. PRD.md already determined every behavior the implementation exhibits at the Step-7 sites, so no PRD_FINALIZED.md is produced. Step 9 will start from PRD.md.

## Step 9: Complete PRD — 2026-07-15T19:31:00.000Z

PRD_COMPLETED.md produced from PRD.md (Step 8 skipped, no PRD_FINALIZED.md). 285 lines → 285 lines (+1,203 chars; all in-paragraph edits). 7 changes: 5 ambiguity-pins, 2 mismatch-revisions:
- §3.2 Catalog — insert — ambiguity — mileage_life_miles default 500 applied for every category when omitted (app.py:657-661).
- §3.4 Price override — insert — mismatch — override accepted only while payment_status UNPAID else ERR_ORDER_NOT_MODIFIABLE, checked before stale-version guard (app.py:978-981).
- §3.5 Wear/Return — revise — ambiguity — reject records inspection_notes from optional reason field (absent when unsupplied) (app.py:1123-1125).
- §3.5 Cascade A — insert — ambiguity — returned-line net = line_gross_cents (unit_price × qty), no proration (app.py:1099).
- §3.7 Subscriptions — insert — ambiguity — discount_pct field reports plan fraction only while ACTIVE, 0.0 in PAST_DUE/CANCELLED (app.py:462).
- §3.8 Fitment cancellation — revise — mismatch — cancel allowed from SCHEDULED or CHECKED_IN by owning member, assigned fitter, or manager; role not paired to state (app.py:1405-1415).
- §3.8 Fitment booking (member overlap) — insert — ambiguity — member-overlap counts fitment sessions not CANCELLED/NO_SHOW and training bookings in BOOKED/WAITLISTED (also governs §3.9) (app.py:550-560).

Non-changes confirmed already-pinned: validation precedence, dual-variant pricing, discount-stack caps, redemption fiscal caps, Cascade B, tier derivation, waitlist promotion ordering, per-endpoint auth/ownership.

## PIPELINE COMPLETE — 2026-07-15T19:31:30.000Z

All 9 steps done. Final state: 54-endpoint Flask impl passing 63/63 tests across 8 parallel rounds; PRD_COMPLETED.md is the finalized contract. Deliverables present: SCAFFOLD.yaml (+2 design files), workspace/PRD.md, workspace/PRD_COMPLETED.md, workspace/implementation/ (app.py, start.sh, requirements.txt, results.{1..8}.json), test_helpers/ (9), test_suite/ (10).
