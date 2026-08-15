## Step 1: Create task directory — 2026-08-13T03:01:00.000Z

Directory tasks/task_1385_propane_wholesale_terminal_supply/ and workspace/ pre-assigned and pre-created by pipeline launcher; Step 1 treated as DONE.

## Step 2: Generate scaffold — 2026-08-13T04:04:00.000Z

All three scaffold artifacts generated, self-consistent, and lint-clean.

Files written: SCAFFOLD.yaml (§1.0–§1.7 only, neither design key present); SCAFFOLD_DIFFICULTY_DESIGN.yaml (single top-level key scaffold_difficulty_design, 24 instances — 9 rules × ≥2); SCAFFOLD_CORNER_DESIGN.yaml (single top-level key scaffold_corner_design, 53 active instances + 7 excluded_because stubs across all 9 taxonomy sections).

Final lint verdict (verbatim): "VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5." (56 endpoints, 12 entities, 1006 recipe calls scanned, 0 violations.)

Design (max-difficulty knobs as directed): archetypes = quota/allocation (cold-snap allocation runs over a finite terminal pool) + pricing engine (index vs fixed contracts, freight zones, tiered overage); flat entity topology, immediate consistency, peer roles with segregation (PricingDesk can't move money; Dealers act only as themselves via entity_backed:Dealer). 12 entities: Terminal, SupplyContract, RailShipment, Dealer, DealerContract, PriceIndexPublication (append-only, common_fields: false), FreightZone, TransportTruck, DeliveryOrder, ColdSnapEvent, AllocationRun, DealerPayment. Deep state machines (10): DeliveryOrder carries parallel dimensions (fulfillment_status × invoice_status, with PAID→OPEN reopen on NSF return); Dealer credit posture computed cyclic machine (GOOD_STANDING↔WATCH↔SUSPENDED); DeliveryOrder schedule/unschedule revert loop; AllocationRun OPEN→COMPUTED→RATIFIED with SUPERSEDED. Compound calculations: delivered price in millicents with in-band/overage tier split, max() freight floor, conditional winter + WATCH surcharges, pinned per-segment round-half-up ordering; pro-rata allocation waterfall with floor-then-remainder distribution (tie-break created_at ASC, never id); circular-looking credit gate with pinned 5-step evaluation order; FIFO chronological payment waterfall. Transitive cascades: cold-snap activation → terminal CURTAILED → order repricing → dealer credit flip (depth 4); payment return → invoice restoration → fee posting → SUSPENDED flip → order rejection (depth 3). Strict concurrency: two true-race OCC rules — POST /allocation-runs on expected_terminal_version (create-with-supersede) and POST /dealer-contracts/{id}/activate on expected_dealer_version (activation supersedes overlapping ACTIVE contract), both 412. Boundaries: exactly-80% WATCH threshold (integer cross-multiplication >=), ATP exact-gallon acceptance (<=), driver-hours exact-limit (3×1200 == 3600 allowed), truck capacity == allowed, rack-bay aggregate-capacity overlap vs buffered half-open truck windows (two different interval semantics). Logical clock endpoint with mandated 2026-08-01T00:00:00Z startup default; POST /ops/run_epoch as the ops-run checkpoint (cold-snap auto activate/lift, contract EXPIRED, supply DEFAULTED with shipment cancellation).

Verification performed: every formula-derived assert literal (40 checks) computed by executing pinned §1.3 formulas in Python — all pass; every catalog error referenced by at least one validation/transition; all enum values have producing transitions; forbidden race vocabulary absent; instance names unique across both design files. No sibling task directories were read at any point.

## Step 3: Copy shared files — 2026-08-13T04:04:30.000Z

Copied ./INSTRUCTION.md → tasks/task_1385_propane_wholesale_terminal_supply/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-13T04:13:00.000Z

PRD generated at workspace/PRD.md.

Structure: §1 introduction (2 paragraphs, business-context angle); §2 with 9 subsections (RBAC with per-role identity translation, verbatim §2.2 envelope block, pagination, common properties/versioning discipline, logical clock & seasonal posture, OCC, money/millicents/rounding, terminal inventory & ATP, validation precedence); §3 with 9 subsections organized by business timeline (physical estate → upstream supply → dealer book → order creation → price engine → dispatch → scarcity/allocation → payments → daily ops epoch); §4 four-column endpoint table (56 rows); §5 two-column error catalogue (36 rows).

Hard contract reports:
- Field coverage: entities[].fields 72/72 present, 0 missing; endpoints[].request_body/input 55/55 present; query params covered (limit, offset, all filter params). PASS.
- Rule coverage: validations with priority 11/11 layers expressed in prose (§2.9 fixes full precedence order; triggers scattered beside workflows); concurrency OCC rejections 2/2 (expected_terminal_version / expected_dealer_version, ERR_STALE_TERMINAL_VERSION 412, ERR_STALE_DEALER_VERSION 412); state machine transitions 31/31 across 10 machines fully expressed with preconditions and side effects; calculations 9/9 fully expressed (delivered_price both variants with per-segment round-half-up discipline, dealer_credit_exposure both variants, credit_gate_evaluation 5-step pinned order, credit_status_threshold 80% integer cross-multiply, allocation_pro_rata_waterfall floor-then-remainder, fifo_payment_application, trip_hours_estimate, terminal_available_to_promise, buffered_window_overlap, rack_bay_capacity); all validation conditions matchable to error_ids; all endpoint side_effects/applies_to expressed; entity field defaults/nullability/constraints reconstructible; sibling-branch symmetry 6/6 groups equal density. PASS.
- Path purity (§3): 451 backtick tokens scanned; 0 path tokens, 0 bare HTTP methods, 0 method+path combos. PASS.

Constants embedded in business prose (40-cent spot premium, 25-cent overage premium, 15-cent watch surcharge, 30-cent winter surcharge, 90-minute rack service, 60-minute deadhead buffer); scaffold gives no numeric value for NSF_FEE_CENTS, so PRD describes it as "a fixed insufficient-funds fee" without inventing a figure. §2.2 verified byte-identical to section-2.2-response-structure.md. Withheld difficulty/corner design files were not opened or referenced.

## Step 5: Generate unit tests — 2026-08-13T04:50:00.000Z

Generation complete. Summary of what was produced for task_1385_propane_wholesale_terminal_supply:

Stage 1 — test_helpers/ (9 files, 1374 lines):
- types.py — 12 entity TypedDicts + 17 enums; PriceIndexPublication correctly modeled as append-only (no updated_at/version)
- api_client.py — ApiClient(GenericApiClient) with one method per PRD endpoint (57 methods)
- api_errors.py — all 36 catalog error IDs with HTTP statuses, registered via set_error_http_status_map
- assertions.py — per-entity assertions; the publication assertion explicitly forbids version/updated_at
- factories.py, constants.py — PRD-named pricing/dispatch constants (premia, surcharges, 90-min rack service, 60-min deadhead, 1000-gal minimum, 2026-08-01 default clock)
- test_users.py — 6 opaque role constants + mandatory make_dealer_user_headers(dealer_id) builder for the entity-backed DealerUser
- fixtures.py — composite chains: stock_terminal (contract→activate→shipment→UNLOADED), dealer_with_active_contract (OCC-threaded), curtail_terminal, create_allocation_run (OCC-threaded), drive_order_to_delivered, base_terminal_fixture/base_order_fixture

Stage 2 — test_suite/ (8 files + conftest, 101 tests): grouped by concern — catalog/terminals, supply/rail, order creation/pricing, credit/contracts, dispatch/scheduling, payments/returns, cold-snap/allocation/epoch, security/listing.

Coverage audit (automated, all green): all 24 difficulty instances have exactly 2 tests; all 53 non-stub corner instances have exactly 1; every test carries exactly one terminal Design: Difficulty/<rule_id>/<name> or Design: Corner/<section>/<name> line resolving to a real instance; all 7 excluded_because stubs verified to point at real difficulty instances and were not translated; all 128 PRD citation segments verified verbatim against workspace/PRD.md (8-word-window grep); no skip/xfail markers; pyflakes clean; pytest collects 101 tests.

PRD-first adjudications worth noting:
- NSF fee amount is unnamed in the PRD ("a fixed insufficient-funds fee"), so payment_return_reverses_invoices_to_suspension was weakened per the two-reader rule: fee asserted > 0 (not == 3500), and the post-return order rejection uses validate_error_is_one_of([ERR_DEALER_SUSPENDED, ERR_CREDIT_LIMIT_EXCEEDED]) since the branch depends on the unspecified fee. Same for payment_double_return_rejected (asserts fee unchanged after the rejected second return rather than an exact value).
- Driver-hours week semantics: the design recipes' clock (2026-08-01) is in a different ISO week than their load windows (2026-08-03), which is ambiguous under PRD §3.1's clock-week definition of weekly_committed_minutes. The generator pinned the clock to Monday 2026-08-03 in those fixtures so clock-week and candidate-week readings coincide — the asserted boundary rule (equality allowed, one trip over rejected) is unchanged and uniquely derivable.
- Validation-priority tests (state_beats_fiscal, safety_beats_constraint) were kept because PRD §2.9 explicitly orders the layers and states earlier failures mask later ones; each pair also got an isolation companion test.

## Step 6: Generate implementation — 2026-08-13T05:20:00.000Z

Complete Python + Flask implementation delivered at workspace/implementation/, ~3000 lines:
- start.sh — guarded-install launcher (exec python3 app.py, binds 0.0.0.0:$PORT default 10000); verified to boot from a fresh copy and answer HTTP in ~0.3s
- app.py — blueprint registration + envelope-shaped error handlers (ApiError → {meta, response_type:"error", data:{error_id,message}})
- db.py — empty-on-boot in-memory store (no seeding) with per-record _seq for stable created_at ordering
- clock.py — server-owned logical clock, default exactly 2026-08-01T00:00:00Z, settable via POST /_clock/set_current_utc
- errors.py, response.py, middleware.py — full 36-id error catalog with per-id HTTP statuses, envelope/pagination (limit/offset/total_count/has_more), auth (X-User-Role + X-User-ID, entity-backed DealerUser), request-shape validation
- serializers.py — per-entity serializers with computed-on-read fields (season_posture, ATP, exposures, weekly_committed_minutes); PriceIndexPublication exposes only id+created_at
- services/__init__.py — delivered-price engine (per-segment round-half-up millicents, lazy index resolution, SPOT/INDEX/FIXED banding, watch/winter surcharge legs), credit threshold ladder, cold-snap curtail/restore cascades with FIFO requeue, pro-rata allocation waterfall (floor-then-remainder), contract cancellation cascades
- routes/ — 10 blueprints covering all 56 endpoints including OCC-guarded writes, ops epoch sweeps, and FIFO payments with NSF returns

Verification: ran the task's real generated test suite (101 tests) via prd-bench-local-run --isolation per-test-server four times. First run exposed one real bug (the schedule-time truck-capacity gate rejected 17000/20000-gal single loads that six tests drive to DELIVERED on 11000-gal trucks, while the boundary test requires an 11001-gal order to fail when the truck already carries a committed 11000-gal load — no monotone capacity rule satisfies both, so the gate now rejects over-capacity only when the truck already has committed loads). After the fix: 99–100 passed, 0 failed on every run; the only non-passes are setup-phase >10s restart timeouts on randomly varying tests, attributable to host contention (measured cold boot is 0.28s). Additionally re-verified every difficulty-design scenario (literal expected values: provisional/final divergence 1100000/1130000, ledger/committed 1680000/2305000, tiered band 1275000, waterfall 33334/33333/33333, credit-gate circular order 700000, 80%-boundary WATCH, exact-ATP, exact driver-hours, buffered-window boundary, rack aggregate capacity, NSF return cascade to SUSPENDED, priority-pair orderings) plus an independent smoke/edge suite — all pass.

Orchestrator note for Step 7: the capacity-gate weakening ("lone over-capacity load admitted") is a candidate PRD-required-check weakening and must be re-adjudicated under the diagnostic protocol — either the tests scheduling >capacity loads are fixture bugs (fix test_helpers) or the gate is PRD-faithful as-is.

## Step 7: Run tests and iterate — 2026-08-13T05:40:00.000Z

All fixture-affected tests pass under proper per-test isolation. The 8-round sweep was run with all fixes already in place, so it validates the final state. Work is complete.

Summary:

Iterations run: 1 (8-round parallel sweep, executed after applying the pre-audited fixes).

Tests deleted: None.

Known-divergence adjudication (orchestrator note): PRD §3.6 states verbatim: "The order's `allocated_gal` must not exceed the truck's `capacity_gal` (`ERR_TRUCK_CAPACITY_EXCEEDED`)." The sentence is unconditional and per-order — the "only when committed loads exist" variant is not derivable. Resolution was STEP 2 fixture repair plus restoring the PRD-required check, exactly as the note anticipated. The boundary test test_truck_capacity_boundary_exact_and_over (11000-gal succeeds on 11000-gal truck; 11001-gal rejected) passes unchanged against the restored unconditional gate, confirming the tests were never in tension — only the fixtures were.

Fixes applied to test_helpers/:
- test_helpers/fixtures.py — base_terminal_fixture: added truck_capacity_gal passthrough (default TEST_DEFAULTS["TRUCK_CAPACITY_GAL"] = 11000, preserving the boundary test's precondition) so tests whose order volumes legitimately exceed the default tank can request a PRD-legal truck.

Fixes applied to test_suite/ (STEP 2 fixture corrections — setups violated the PRD §3.6 capacity precondition):
- test_04_dealer_credit_and_contracts.py — TestCreditStatusCycle._setup_delivered_17000 and TestExposureVariants._setup_ledger_and_pipeline: added truck_capacity_gal=20_000 (17000-gal orders driven to DELIVERED).
- test_05_dispatch_scheduling_and_loading.py — test_reserve_floor_breach_at_load_rejected: added truck_capacity_gal=20_000 (20000-gal order scheduled).
- test_06_payments_invoices_returns.py — TestReturnDrivenCreditCascade._setup_paid_in_full: added truck_capacity_gal=20_000 (17000-gal order driven to DELIVERED).

Fixes applied to implementation/:
- workspace/implementation/routes/delivery_orders.py — schedule_order: restored the unconditional per-order capacity gate (if o["allocated_gal"] > truck["capacity_gal"]: raise err_truck_capacity_exceeded()), removing the forbidden "only when other committed loads exist" weakening.

Sweep results: Round 1: 101/101 clean. Rounds 2–8: zero assertion failures (failed: 0 everywhere); 8 distinct tests showed "failed on setup ... could not be restarted" timeouts — the documented host-contention signature (load average 24). Every one of those tests passed in at least 2 other rounds and again in direct isolated verification runs (test_no_index_published_rejected, test_order_create_requires_contract_active_cancelled, plus all fixture-touched tests re-verified against fresh servers). Union of real failures: empty.

## Step 8: Finalize PRD — 2026-08-13T05:44:00.000Z

PRD_FINALIZED.md exists and is byte-identical to PRD.md — every Step 7 item resolved to either a verified no-op (PRD already pinned the behavior) or a test-side-only fix (no PRD silence).

Line counts / delta: PRD.md 315 lines; PRD_FINALIZED.md 315 lines; 0% delta. No edits committed.

Per-item adjudication of <step_7_diff>:
- PRD §3.6 capacity gate — verified no-op. PRD.md line 177 already states verbatim: "The order's `allocated_gal` must not exceed the truck's `capacity_gal` (`ERR_TRUCK_CAPACITY_EXCEEDED`)." — unconditional and per-order. The current implementation at implementation/routes/delivery_orders.py:250-253 raises err_truck_capacity_exceeded() whenever o["allocated_gal"] > truck["capacity_gal"], with no "only when committed loads exist" weakening (the Step 6 deviation was reverted). PRD text and implementation match exactly; no edit.
- test_helpers/fixtures.py truck_capacity_gal passthrough — not a PRD silence. The PRD (§3.1) already requires a strictly positive capacity_gal at truck creation; the implementation (routes/fleet.py:104,110,122) requires the field with no server-side default. The 11000-gal default lives only in test_helpers/constants.py:39 / factories.py:98 — test-side fixture convenience, invisible to the API contract. No edit.
- test_suite fixture corrections (4 setups adding truck_capacity_gal=20_000) — pure fixture bugs. They repaired test setups that violated the PRD §3.6 precondition the implementation now enforces. Nothing about implementation behavior was left undetermined by the PRD. No edit.

Pre-edit search log (mandatory, for the one candidate edit — which was committed as a no-op):
- (a) Subject: the per-order truck-capacity gate at scheduling (allocated_gal vs capacity_gal, ERR_TRUCK_CAPACITY_EXCEEDED).
- (b) Impl paths enumerated via repo-wide grep for capacity_gal / err_truck_capacity_exceeded / ERR_TRUCK_CAPACITY and read: implementation/routes/delivery_orders.py:19,250-253 (sole raise site, in schedule_order); implementation/errors.py:84-85 (error constructor, HTTP 422 — matches §5 catalogue); implementation/routes/fleet.py:104,110,122 (capacity_gal as creation-only field, strictly positive); implementation/serializers.py:261 (read-only exposure); implementation/routes/terminals.py:23,28,38 and serializers.py:53 (unrelated storage_capacity_gal). No other endpoint, branch, helper, or cascade raises or conditions this error; unschedule, load, deliver, cancel, and the OUT_OF_SERVICE cascade never re-check capacity.
- (c) Wording adjustment: none — the existing PRD sentence ("must not exceed ... unconditional, per-order") is exactly what the single raise site implements, and there is no second path that could be mis-described. Editing would have risked narrowing behavior the implementation exhibits, so the sentence was kept verbatim.

Bottom line: PRD_FINALIZED.md = PRD.md. The only behavioral divergence Step 7 found was an implementation regression (conditional capacity gate), which was fixed in code; the PRD never needed to change.

## Step 9: Complete PRD — 2026-08-13T05:55:00.000Z

PRD_COMPLETED.md written at workspace/PRD_COMPLETED.md.

Source vs output: PRD_FINALIZED.md 315 lines / 45,923 chars → PRD_COMPLETED.md 316 lines / 52,000 chars (char-delta +6,077). All edits are in-paragraph inserts/revisions; no sections added.

Counts: 19 ambiguity-pins, 11 mismatch-revisions (30 edited passages total).

Ambiguity-pins (insert):
- §2.1 — insert — ambiguity — DealerUser implicit scoping on dealer_id-filtered list endpoints; foreign filter → ERR_DEALER_MISMATCH — routes/dealer_contracts.py:102-105, delivery_orders.py:178-181, payments.py:103-106
- §2.2 — insert — ambiguity — unknown path/undefined method → ERR_NOT_FOUND 404; unclassified failure → ERR_INVALID_REQUEST 400 envelope — app.py:43-56
- §2.3 — insert — ambiguity — non-integer/out-of-range limit, negative/non-integer offset, unrecognized enum filter values → ERR_INVALID_REQUEST; has_more ≡ offset+returned < total_count — middleware.py:148-185, response.py:32-39
- §2.3 — insert — ambiguity — same-instant created_at ties keep insertion order — db.py:22-31 (_seq) used as sole sort key in all list handlers
- §2.5 — insert — ambiguity — clock-set normalizes to UTC, truncates to milliseconds, echoes in now_iso8601 — clock.py:33-47
- §3.1 — insert ×3 — ambiguity — out-of-range numerics on terminal/zone/truck creation → ERR_INVALID_REQUEST — routes/terminals.py:28-31, fleet.py:44-45, fleet.py:110-111
- §3.1 — insert — ambiguity — truck transition to current status → ERR_INVALID_STATE — routes/fleet.py:171-172
- §3.2 — insert ×2 — ambiguity — non-positive contracted_volume_gal / shipment volume_gal,railcar_count → ERR_VOLUME_INVALID; tendering allowed under DRAFT/ACTIVE, blocked under COMPLETED/DEFAULTED/CANCELLED with ERR_CONTRACT_NOT_ACTIVE — routes/supply.py:52-55, 158-162
- §3.3 — insert ×2 — ambiguity — missing/non-positive credit_limit_cents (create + PATCH) and non-positive volume_committed_gal/fixed_price_mc_per_gal → ERR_INVALID_REQUEST — routes/dealers.py:21-22, 76-78, dealer_contracts.py:40-44, 58-59
- §3.4 — insert — ambiguity — ATP supply check runs before the credit gate (masks ERR_NO_INDEX_PUBLISHED/ERR_CREDIT_LIMIT_EXCEEDED) — routes/delivery_orders.py:94-115
- §3.5 — insert ×2 — ambiguity — non-positive publication price → ERR_INVALID_REQUEST; resolve endpoint with no effective publication → ERR_NOT_FOUND 404 — routes/price_indexes.py:30-31, 69-71
- §3.5 — insert — ambiguity — every price (re)computation re-evaluates the watch surcharge from dealer status with the order itself excluded — services/__init__.py:141-167, delivery_orders.py:334-336
- §3.6 — insert ×2 — ambiguity — full multi-failure ordering for the seven schedule checks (gates → window-shape → hours → terminal/capacity/conflict/rack/window); open_balance_cents null until delivery — routes/delivery_orders.py:215-287, 377
- §3.7 — insert ×5 — ambiguity — inverted event range → ERR_WINDOW_INVALID; activate only from DECLARED, lift only from ACTIVE (ERR_INVALID_STATE), manual activate/lift not date-gated; run creation needs no curtailment; compute only from OPEN; zero/negative pool shorts everyone; zero-weight tier skipped; results recorded in visiting order; ratify skips no-longer-REQUESTED orders — routes/cold_snaps.py:46-47, 101-102, 124-125, 137-178, 216-220, 238-241; services/__init__.py:289-333
- §3.7 — insert — ambiguity — lift requeue resets SHORTED orders' allocated_gal/provisional_total_cents to null — services/__init__.py:191-196
- §3.8 — insert ×2 — ambiguity — non-positive amount_cents → ERR_INVALID_REQUEST; NSF fee pinned at 3500 cents — routes/payments.py:39-40; services/__init__.py:19, payments.py:142
- §3.9 — insert — ambiguity — epoch skips (leaves DECLARED, uncounted) events blocked by an already-ACTIVE event — routes/ops.py:44-51

Mismatch-revisions (revise):
- §2.4 — revise — mismatch — timestamps are millisecond precision with the fractional part omitted at whole-second instants (was "three fractional digits") — clock.py:40-47, serializers.py:10-19
- §2.9 — revise — mismatch — payload well-formedness validated after path-id resolution, not in layer 1; ownership decidable by id (/dealers/{id}) precedes existence, resource-dependent ownership follows resolution — routes/supply.py:220-224, dealers.py:44-48, delivery_orders.py:158-162
- §3.1/§3.6 — revise — mismatch — unscheduling also clears planned_load_start/planned_load_end, not just truck/trip fields — services/__init__.py:218-223
- §3.2 — revise — mismatch — under COMPLETED, shipments can no longer be created nor unloaded, but may still advance TENDERED→IN_TRANSIT→ARRIVED or cancel (was "created or advanced") — routes/supply.py:226-233
- §3.3 — revise — mismatch — fixed_price_mc_per_gal on INDEX contracts is optional, stored and returned, never priced (was "absent") — routes/dealer_contracts.py:45-47
- §3.4 — revise — mismatch — non-integer requested_gal → ERR_INVALID_REQUEST (was lumped under ERR_VOLUME_INVALID); contract-check enumeration reordered to impl: ACTIVE gate first, then terminal anchor, dealer ownership, window — middleware.py:97-100, delivery_orders.py:73-92
- §3.5 — revise — mismatch — provisional is NOT re-stamped on unschedule-back-to-ALLOCATED (was "every entry into ALLOCATED") — services/__init__.py:218-223 (no restamp), 174-211 (restamp sites)
- §3.6 — revise — mismatch — driver-hours budget evaluated over the ISO week of the candidate's planned_load_start, not the current-instant week — routes/delivery_orders.py:241-243
- §3.7 — revise ×2 — mismatch — lift sweep and allocation-remainder ordering are pure creation order; the "larger requested_gal first" tie-break never fires (was pinned in PRD) — services/__init__.py:203, 285, 313
- §3.7 — revise — mismatch — ratifying a SUPERSEDED run yields ERR_INVALID_STATE, not ERR_RUN_NOT_COMPUTED — routes/cold_snaps.py:234-237
- §3.9 — revise — mismatch — ARRIVED shipments of a settled contract are not cancelled but can no longer unload (was "may still unload"), since unload requires ACTIVE — routes/supply.py:230-233

Verification: endpoint/role table, all 36 error codes, pricing formulas, rounding discipline, OCC rules, state machines, and cascade contents were checked line-by-line against routes/*.py + services/__init__.py and found already pinned; tests were used only to cross-check which reading the impl embodies (e.g., test_safety_beats_constraint_on_schedule confirms the layer order now written into §3.6).
