## Step 1: Create task directory — 2026-09-03T23:57:00.000Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2645_rotational_molding_watercraft_plant and its workspace/ subdirectory. Index 2645 was pre-assigned by the orchestrating caller (no auto-allocation scan performed, per instruction: 32 concurrent pipelines on this host).

## Step 2a: SCAFFOLD.yaml §1.0–§1.7 — 2026-09-04T01:55:00.000Z

Generated the first half of the scaffold-generator spec (Step 0 complexity profile through §1.7 RBAC)
into SCAFFOLD.yaml — 5509 lines, one file, no other file created or modified.

Section counts (yaml.safe_load verified):
  complexity_profile 8 keys | response_envelope 4 keys (verbatim) | entities 16
  state_machines 16 (94 transitions) | concurrency_rules 5 | calculations 23 (all with 2 variants)
  validations 76 | endpoints 94 (36 GET) | errors 90 | roles 8

Deliberately NOT emitted: scaffold_difficulty_design, scaffold_corner_design (§1.8/§1.9 belong to
the second subagent, which reads this file).

Verification performed:
  - scaffold_lint.py with empty §1.8/§1.9 stubs: "clean lint" — all 24 §1.1 FKs have
    reverse-reachability in §1.5 (flat topology, api_prefix "/", scalar GET + FK-filtered list GET
    per collection).
  - error catalog closed both ways: 90 referenced == 90 catalogued, no orphans, no dupes.
  - all 79 API-triggered state transitions resolve to a declared §1.5 endpoint (fixed a
    /start-cooling -> /enter-cooling mismatch and gave ResinCharge RESERVED->RELEASED its
    manual trigger).
  - every status-mutating non-GET endpoint appears in a state machine (only POST /warehouses does
    not, correctly, since it sets initial_state rather than taking a transition).
  - all 5 concurrency rules: occ field present in the write endpoint's input + version bump in
    its side_effects.
  - no forbidden race vocabulary (simultaneous / race winner / whoever / at the same time);
    the 3 "random" hits are explicit prohibitions.
  - validation priorities unique and ascending; all categories from the legal 8; all endpoint
    roles resolve to one of the 8 declared roles; every role declares identity:.

## Step 3: Copy shared files — 2026-09-04T02:25:00.000Z

Copied ./INSTRUCTION.md -> tasks/task_2645_rotational_molding_watercraft_plant/workspace/INSTRUCTION.md. (Run out of order relative to the skill's numbering: Step 3 has no dependency on Step 2, so it was executed while the §1.8 fragment subagents were still running.)

## Step 4: Generate PRD — 2026-09-04T02:57:00.000Z

PRD.md is complete at workspace/PRD.md (582 lines, 147,004 bytes). Written incrementally (one Write + heredoc appends, each verified with tail/wc -l).

Section outline with line ranges:
  1 title | 3-10 §1 Introduction | 11-193 §2 Global Specifications (2.1 Roles/Authorization 13-35;
  2.2 API Response Structure 36-84 byte-identical paste of section-2.2-response-structure.md;
  2.3 Pagination/Filtering/Ordering 85-92; 2.4 Common Fields/Types/Precision 93-100;
  2.5 The Logical Clock 101-108; 2.6 Optimistic Concurrency 109-120; 2.7 Validation Order 121-135;
  2.8 Resource Model and Field Reference 136-171; 2.9 Resource Occupancy and Interval Arithmetic 172-185;
  2.10 Derived Values, Ledgers and Cascade Discipline 186-193) | 194-385 §3 Business Logic & Workflows
  (3.1 Standing Up the Plant 198-219; 3.2 Resin Intake/Qualification/Reservation/Mass Ledger 220-239;
  3.3 Build Orders 240-259; 3.4 Booking a Cycle: Mould Selection and Three Resource Pools 260-273;
  3.5 Running the Cycle 274-291; 3.6 Finishing/Measuring/Judging Hulls 292-313;
  3.7 Nesting Hulls into Warehouse Zones, Build-Ahead Quota, Site Posture 314-333;
  3.8 Trailer Loading/Cube Rollups/Freight Quoting/Delivery 334-357;
  3.9 Warranty Claims: Two Independent Axes and the Reserve Ledger 358-385) |
  386-486 §4 Endpoint Definitions (94 rows) | 487-582 §5 Error Code Catalogue (90 rows)

Ends at a real section boundary (last row of the §5 table). Orchestrator independently verified the
tail: last line is "| `ERR_STALE_PRODUCT_MODEL_VERSION` | 412 |" — NOT truncated mid-sentence.

Coverage reported by the generator: endpoints 94/94; calculations 23/23; validations 76/76 (every
error_id present in prose); error codes 90/90; transitions 94/94 (every from/to token backticked in
§3); roles 8/8; concurrency rules 5/5 (all framed in stale-version terms with 412 ids; no race
vocabulary anywhere).

Hard Contract checks: Contract 1 Field-Name Coverage PASS (entity fields 181/181; request_body
132/132 after weaving in remove_reason, unseal_reason, return_note; query_params 52/52).
Contract 2 Rule Coverage PASS (validation priority ordering, all 5 concurrency rules, all 8 cascades
A-H as numbered link lists, applies_to sets per validation, defaults/types/initial values in §2.8,
sibling-branch symmetry for QUOTED/BILLED, PRO_RATA_AGE/FLAT_SCHEDULE, NEW_NEST/JOIN_EXISTING,
TIGHTENING/LOOSENING, IN_WINDOW/OUT_OF_WINDOW, ADD/REMOVE). Contract 3 §3 Path Purity PASS
(0 backticked paths/methods in §3, and none in §1-§2 either).

Two scaffold-internal conflicts resolved and recorded: oven_temp_c (entity field range 200.0-360.0
kept authoritative over validation 22's 150..350) and warpage-index decimal places (calculation's
3 dp kept over §1.1's 2 dp). Charge-mass tolerance stated in both equivalent forms (per-model
nominal_charge_kg and mould-level value x cavity_count).

Withheld files (SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, SCAFFOLD_DD_frag_*)
were never opened, grepped, or referenced; no sibling task directory was read.

ORCHESTRATOR NOTE on step ordering: Step 4 was launched concurrently with the two §1.8 fragment
subagents (Step 2b-i / 2b-ii) rather than strictly after Step 2, to recover wall-clock time lost to
two API-timeout deaths of earlier Step 2 attempts. The risk this accepts is that a fragment agent
might additively amend SCAFFOLD.yaml's §1.5 under the priority ladder after the doc generator had
already read it. Mitigation: an md5 snapshot of SCAFFOLD.yaml was taken before launching Step 4 and
is re-verified after the fragments land; if §1.5 changed, the PRD is regenerated rather than patched.

## Step 6: Generate implementation — 2026-09-04T04:24:00.000Z

Implementation complete at workspace/implementation/ (5732 lines across 20 modules + start.sh + requirements.txt). Smoke-tested clean; server killed by captured PID (no broad pkill).

Module layout: app.py 83 (Flask factory, 10 blueprints, ApiError/404/405/400/Exception handlers, PORT bind) | core.py 341 (Store on plain dicts, logical clock, Decimal quantizers, dumps, envelope, Checks, paginate) | errors.py 109 (all 90 error ids -> HTTP status) | schema.py 227 (body_json, type/enum/bounds/date passes at rungs 20-23) | auth.py 127 (rungs 1-5, Ctx, suspension/certification, customer-scope) | calc.py 634 (all 23 calculations x 2 variants, interval predicates, zone/nest selection, pricing) | serial.py 166 | svc.py 373 (ledger mutators with invariant assertions, roll-ups, cascades, sweeps) | rt.py 92 | r_models.py 312 | r_equip.py 296 | r_party.py 360 | r_resin.py 350 | r_orders.py 204 | r_cycles.py 487 | r_units.py 443 | r_ship.py 561 | r_warranty.py 445 | r_clock.py 122.

grep -c "@bp.route" == exactly 94 routes (57 POST, 36 GET, 1 PATCH), matching the declared surface. ast.parse ALL_SYNTAX_OK. No sqlite, no file I/O, no seeding — state lives only on module-global core.S, so bash start.sh boots empty every time (verified: 13 collections all total_count 0 on fresh boot).

Ordered validation pipeline: one shared mechanism. core.Checks.add(priority, fn) records (priority, insertion_index, fn); Checks.run() sorts on that tuple, so the first failure raises and the lower priority number always wins. Every endpoint builds its ladder from the same primitives (auth.authenticate = rungs 1-5, schema.add_schema = 20-23, rt.find = 10, OCC = 80-84). Fractional priorities (10.5, 35.1-35.7, 38.5, 38.6, 61.5, 62.5) slot PRD-prose orderings and undeclared checks between scaffold rungs. All five declared priority pairs verified live.

Decimal handling: money is integer cents; every other quantity is decimal.Decimal quantized ROUND_HALF_UP at the declared place count. Inbound JSON parsed with parse_float=Decimal so no float ever enters; outbound uses hand-rolled core.dumps so declared trailing zeros survive on the wire. Rounding ORDER honored: sd about the already-rounded mean, CV from rounded sd and mean, per-charge/per-line money rounds before summation, overhead and discount tier selected once from the pre-discount figure and never re-tiered.

Three interval semantics kept physically distinct in calc.py, never routed through a common helper: (1) oven arm — half-open [start,end) per (station, arm_index), each side widened by the station's symmetric changeover_buffer_min; (2) cooling bay — aggregate count over the CLOSED interval [start,end] vs concurrent_slot_capacity, NO buffer; (3) mould occupancy — half-open over the COMBINED oven+cooling span, no buffer. Touching windows (10:00-11:00 vs 11:00-12:00) therefore conflict on the bay and not on the arm.

Cascades A-H each run transactionally inside the triggering request to full declared depth, every touched row restamped and version-bumped, each link's stated cause gating its effect. A/B abort-cycle -> charge release -> lot mass return -> order recost. C release_footprint -> vacate, promote earliest surviving nest follower to anchor at full gross cube, site recompute, order unblock. D adverse re-inspection -> demote, completed_qty down, COMPLETE order re-opens IN_PRODUCTION. E/F trailer seal/depart/deliver roll-ups. G set_current_utc -> expire lots (date equality does NOT expire), release RESERVED charges, abort SCHEDULED cycles, block orders — verified returning counters 1,1,1,1. H store -> committed cube, utilisation, posture, frozen-site sweep.

Four ledger invariants enforced by svc.py mutators (the only writers of the ledger fields), each ending in an assert before touch(): resin mass (available + reserved + consumed == received - scrapped); warranty reserve (reserve + paid == initial); site storage footprint (sum of stored units' charged cube == committed_cube); build-ahead commitment (bucket committed qty == count of its stored units). Compensating transitions go through the same mutators. app.py deliberately lets AssertionError surface as 500 rather than disguising a server defect as a 422.

Smoke: two suites, 0 failures — main flow 57 assertions over ~40 distinct endpoints (product model -> cycle -> demold -> trim/outfit/inspect -> store -> shipment seal/depart/deliver -> claim approve/void), plus a fresh-boot suite of 32 assertions (empty-state boot, priority-pair precedence, CASCADE-G, clock RBAC). Error ids observed with exact statuses: ERR_STALE_RESIN_LOT_VERSION 412, ERR_STALE_WAREHOUSE_VERSION 412, ERR_STALE_PRODUCT_MODEL_VERSION 412, ERR_OVEN_START_IN_PAST 422, ERR_COOLING_MODE_MISMATCH 422, ERR_INSUFFICIENT_MEASUREMENTS 422, ERR_DEFORMATION_BELOW_THRESHOLD 422, ERR_INVALID_ENUM_VALUE 422, ERR_VALIDATION 422, ERR_CLAIM_INVALID_STATE 409, ERR_STORAGE_REVIEW_INCOMPLETE 409, ERR_STORAGE_REVIEW_ALREADY_DONE 409, ERR_ROLE_NOT_PERMITTED 403, ERR_CUSTOMER_SCOPE_VIOLATION 403, ERR_MISSING_AUTH_HEADERS 401, ERR_INVALID_ROLE 401, ERR_FINISHED_UNIT_NOT_FOUND 404. Business figures verified: clock default 2026-08-01T00:00:00.000Z; actual_oven_minutes 60; PASS -> SELLABLE; store -> is_zone_anchor true; cube_utilization_pct 66.67; approve -> PRO_RATA_AGE gross 500000 / admin fee 25000 / net 475000 / reserve 525000+475000 == 1000000; void restored the reserve while retaining the audit money fields.

PRD AMBIGUITIES THE IMPLEMENTER HAD TO RESOLVE (32 items — these are the primary input to Steps 8 and 9):
 1. oven_temp_c range 200.0-360.0 (PRD §2.8) chosen over the scaffold's 150-350.
 2. Non-RETIRED replaces_mold_id -> ERR_INVALID_MOLD_REPLACEMENT (rung 67); a missing target is still 404.
 3. start-oven check order follows PRD §3.5 prose, not the ladder's 32/36/50/53.
 4. Cycle-create order follows PRD §3.4 prose, not the ladder's 70-before-71.
 5. Claim-approve OCC evaluated last (rung 84) per the ladder, not third as §3.9 prose implies.
 6. Shipment customer_id accepted as optional (must resolve and be ACTIVE at rung 60 when supplied): scaffold input omits it, PRD §3.8 requires it.
 7. Overbuild ceiling = existing units + cavity_count of each SCHEDULED/OVEN_RUNNING/COOLING cycle + the candidate mould's cavity_count, vs floor(ordered_qty * 1.20).
 8. ShipmentLine.line_freight_cents persisted on the QUOTED basis.
 9. Out-of-range arm_index -> ERR_VALIDATION (per-field bound_error), not ERR_INVALID_QUANTITY.
10. Claim storage_description optional at creation (10-500 when supplied), REQUIRED on storage-review.
11. months_in_service null at claim creation, frozen at start-review.
12. created_by_technician_id / operator_technician_id optional; when supplied must resolve (404) and equal the acting id (ERR_ROLE_IDENTITY_MISMATCH), else default to the acting id.
13. actual_*, departed_at, delivered_at are body-required but stored from the logical clock; customer acknowledged_at stored from the body.
14. ERR_SIZE_CLASS_NOT_SUPPORTED at rung 59, order's model size-class rank vs the station's max_size_class.
15. Release of a non-DRAFT order -> ERR_ORDER_NOT_SCHEDULABLE (undeclared).
16. Order release is a SOFT gate: FROZEN site -> BLOCKED_WAREHOUSE, zero qualified lots -> BLOCKED_RESIN, both HTTP 200; ERR_NO_ELIGIBLE_MOLD stays hard at 70.
17. weighted_melt_index_g10min null when charged_mass_kg is 0.000.
18. Order cost recompute touches the order only when a figure changed, except inspect/scrap which bump unconditionally.
19. scrap allowed-from = {OUTFITTED, SELLABLE, REWORK} per §3.6 and the ten-edge count, not the precondition's five states; its logistics guard raises ERR_UNIT_NOT_REINSPECTABLE (rung 39).
20. ERR_UNIT_INVALID_LOGISTICS_STATE has no ladder rung; placed at 38.5 (38.6 for loaded-line variants) so build_status is judged first per §3.7 sentence order.
21. Store OCC (expected_warehouse_version) evaluated last at 82 though the precondition list places it before the frozen check.
22. min_wall_thickness_mm rounded to 3 dp (§3.6) despite the entity's 2 dp.
23. density_kg_per_m3 rounded to 3 dp (§3.8 + freight-summary number(3)) despite the 2-dp default.
24. wall_thickness_points element precision not enforced (no error id declared); elements stored exactly as supplied.
25. ERR_INSUFFICIENT_MEASUREMENTS at rung 25 (before suspension/certification/state) per the explicit ladder.
26. REWORK verdict clears hardware_kit_serial at inspect AND again on the REWORK->TRIMMED trim edge — observably identical.
27. Trailer cancel recomputes roll-ups to zero though cancel's declared effects omit it.
28. POST /warranty-claims body FKs both report ERR_RESOURCE_NOT_FOUND (rung 16) rather than entity-specific 404s.
29. waive-storage-finding evaluates rung 43 before rung 47, following the ascending ladder rather than the precondition list's storage-axis-first order.
30. The "never roll the clock back past a recorded actual timestamp" rule has no declared error id -> ERR_VALIDATION (422) at rung 24, scoped to exactly the three actual_* MoldingCycle fields.
31. GET /_clock/current_utc returns the four sweep counters plus current_utc/default_utc — a superset satisfying both PRD §2.5 and the scaffold's two-string output schema.
32. CASCADE-G link 5 (sweep_block_resin) runs on every set_current_utc call, not only when a lot expired.

ORCHESTRATOR NOTE: Step 6 was launched BEFORE Step 5 rather than concurrently with it. This does not weaken the skill's isolation requirement — it strengthens it: test_suite/ and test_helpers/ did not yet exist anywhere on disk when the implementation subagent ran, so the impl generator could not have read the tests even had it tried. The hazard the skill guards against is the 5-then-6 ordering, not 6-then-5.

## Step 2 (consolidated): Scaffold design-index assembly, repair and lint triage — 2026-09-04T05:10:12.96398938Z

The scaffold generator could not complete §1.8/§1.9 in a single subagent: attempt 1 of the whole
of Step 2 died with "API error: Request timed out (error type server_error)" after 72 minutes with
zero files written, and attempt 1 of the design-index half (2b) died with "API Error: The system
encountered an unexpected error", leaving a 520-line partial containing only Difficulty Rule 1.
ListAgents confirmed a dead subagent cannot be resumed. Decision (mine, no user available): keep the
partial and split the remaining work across parallel fragment agents each writing its OWN file, then
concatenate and validate in the orchestrator. This is now the standing recovery pattern for this task.

Fragment agents launched and landed (all reported ZERO edits to SCAFFOLD.yaml, so PRD.md stays valid):
  - SCAFFOLD_DD_frag_rules_2_5.yaml   (2313 lines) -> Difficulty rules 2-5
  - SCAFFOLD_DD_frag_rules_6_9.yaml   (2129 lines) -> Difficulty rules 6-9
  - SCAFFOLD_CD_frag_entities_statemachines.yaml  (4168 lines)
  - SCAFFOLD_CD_frag_calcs_validations.yaml       (5667 lines)
  - SCAFFOLD_CD_frag_endpoints_errors_rbac.yaml   (4308 lines)

Assembled artefacts:
  - SCAFFOLD.yaml                    5509 lines — 16 entities, 16 state machines (94 transitions),
                                     5 concurrency rules, 23 calculations (2 variants each),
                                     76 ordered validations, 94 endpoints (36 GET), 90 errors, 8 roles
  - SCAFFOLD_DIFFICULTY_DESIGN.yaml  4962 lines — 9 rule blocks / 25 instances, all names unique.
                                     Per rule: dual_variant_calc 3, combinatorial_formula 3,
                                     non_linear_state_machine 3, transitive_cascade 2,
                                     priority_pair_validation_conflict 3, boundary_precision_check 3,
                                     cross_entity_state_dependency 2, resource_temporal_overlap 3,
                                     compensating_invariant 3.  (>=2 per rule: satisfied)
  - SCAFFOLD_CORNER_DESIGN.yaml     14144 lines — 9 sections / 173 instances (111 real + 62 stubs),
                                     0 name collisions with §1.8, every
                                     excluded_because.difficulty_instance reference resolves.

YAML defect found and fixed during assembly: `captures: { fu1: $.data[0].id, fu2: $.data[1].id }` —
an unquoted JSONPath containing '[' terminates a YAML flow mapping. Fixed at 2 sites and a
"quote any flow-mapping value containing [ or ]" rule was propagated into every later fragment prompt.

REPAIR — 5 projection-output endpoints. scaffold_lint's _parse_output only populates
output_inline_fields when `output:` is a dict; a string naming a non-§1.1 entity is reported as
"output entity X not declared in §1.1" and makes every capture against it unresolvable. The separate
`output_schema:` key the generator emitted is never read by the linter. These 5 endpoints were
converted to inline-dict `output:` (field lists copied verbatim from their output_schema bodies,
which are retained):
  GET  /warehouses/{warehouse_id}/footprint-summary        -> WarehouseFootprintSummary (8 fields)
  GET  /production-orders/{production_order_id}/cost-summary -> ProductionOrderCostSummary (11)
  GET  /shipments/{shipment_id}/freight-summary            -> ShipmentFreightSummary (13)
  POST /_clock/set_current_utc                             -> ClockState (6)
  GET  /_clock/current_utc                                 -> ClockState (2)
A first attempt at this rewrite matched an 8-space indent while the schema bodies use 6, emptying all
5 bodies; it was detected immediately and repaired in place from the surviving output_schema blocks.
Post-repair yaml.safe_load: entities 16, state_machines 16, calculations 23, validations 76,
endpoints 94, errors 90, roles 8 — unchanged, nothing else touched.

LINT TRIAGE — scaffold_lint.py went 55 -> 37 -> 33 violations.
  -18  (d) capture JSONPath unresolvable — ALL cleared by the projection-output repair above.
   -3  (c) required field 'release_reason' missing on POST /finished-units/{id}/release-storage.
        REAL BUGS, fixed: two of the three calls must return 200 for their own asserts to hold
        ("${whv_b} == ${whv_a} + 1", "the release returns 200 with ... logistics_status 'UNALLOCATED'").
        A 4th release-storage call (rbac_* denial probe, not lint-flagged) got the same field so that
        its expected 403 is the sole defect in the request.
  ---
   33  residual, and ALL 33 sit in `trigger[]` — ZERO in `setup_api_calls` (verified by location
        parse). Every one is the deliberate negative probe that its instance exists to assert:
        - 25x (b) role not allowed: rbac_shop_floor_and_planner_roles_denied_on_each_others_exclusive_actions (9),
          rbac_warranty_adjudication_split_across_agent_admin_and_customer (6),
          rbac_missing_blank_and_unknown_identity_headers_are_refused_before_role_lookup (5, incl. the
          `as: None` and `as: PlantAdministrator` typo-role probes),
          err_auth_ladder_role_not_permitted_precedes_identity_and_role_code_checks (2),
          val_priority_ordering_role_not_permitted_beats_unresolved_path_id (2),
          layer_optimistic_concurrency_every_parent_version_moves_by_exactly_one_per_write (1 — its
          assert literally reads "the AssemblyTechnician release-storage returned 403
          ERR_ROLE_NOT_PERMITTED and consumed no version", so the wrong role IS the subject).
        -  4x (c) required field missing: ent_required_fields_and_declared_types_enforced_on_creation (3)
          and err_422_schema_ladder_missing_field_then_enum_then_numeric_bound (1). The omission is the
          assertion.
        -  4x (e) OCC version literal: all in
          ent_flat_fk_body_references_validated_before_state_occ_and_business_rules. Structurally
          uncapturable — the parent id in each of those calls is the sentinel
          00000000-0000-0000-0000-0000000000ff, so no prior response can yield its version. The probe's
          whole point is that the FK 404 pre-empts the OCC check, so a literal (99 / 1) is required.
        No further scaffold action. Step 5's test generator will translate these as negative tests.

Carried forward to Steps 7-9 as known scaffold defects surfaced by the fragment agents:
  - Structurally unreachable errors: ERR_FREIGHT_QUOTE_MISSING, ERR_SEGREGATION_OF_DUTIES,
    ERR_SIZE_CLASS_NOT_SUPPORTED, ERR_WAREHOUSE_CUBE_EXCEEDED.
  - §1.4 <-> §1.6 conflicts on FK 404s and on `scrap`.
  - ERR_UNIT_INVALID_LOGISTICS_STATE and ERR_MOLD_SIZE_CLASS_MISMATCH have no §1.4 rung.
  - oven_temp_c range disagreement: §1.1 says 200.0-360.0, validation 22 says 150..350.
  - STORAGE_VIOLATION_DEDUCTION_PCT referenced but the defined constant is STORAGE_WAIVED_DEDUCTION_PCT.

## Step 5 Stage 1: test_helpers/ — 2026-09-04T05:53:22.402239643Z

Orchestrator note on decomposition. Step 5 was split along the skill's own two-stage seam: Stage 1
(test_helpers/) as ONE agent, then Stage 2 (test_suite/) as SEVEN concurrent partition agents. Reason:
Step 2 lost two agents to API timeouts on single large generations, and Step 5 is larger still (136 real
design instances to translate). The seam is safe because SKILL.md §2.1 already requires Stage 1 to
pre-build every composite fixture and Stage 2 to read Stage 1 back rather than invent interfaces.
To make a 7-way split work I added two things the skill does not call for:
  - test_helpers/API.md, a 1515-line exhaustive contract of the public surface, so seven agents that
    cannot see each other code against one fixed interface instead of seven guesses;
  - test_suite/conftest.py written by ME (orchestrator) before the fan-out, because it is shared and a
    concurrent write would race. Partition agents are forbidden to touch it or test_helpers/.
Partition manifests precomputed at workspace/step5_manifests/P1..P7.md — 136 instances, verified
disjoint and exhaustive (136 unique names, no overlap), each partition owning a distinct file prefix.
SKILL.md §2.1 says run queue (A) before (B) so difficulty setups can seed fixtures the corner
translations reuse; that ordering is moot here because Stage 1 pre-built the fixtures for BOTH queues,
which is what the skill asks Stage 1 to anticipate anyway.

Orchestrator verification of this agent's claims (memory: a subagent's clean report is not evidence):
  wc -l confirmed all 10 files; `import test_helpers` clean with 340 public names; ApiClient exposes
  107 methods; spot-checked 7 named fixtures all present; TEST_USERS carries all 8 roles;
  test_suite/ did not exist; no file landed under workspace/.
Also verified independently of the agent: the Step 6 implementation still boots from a fresh process on
an isolated port, honours $PORT, binds 0.0.0.0, and returns the correct envelope (server killed by PID
only, never a broad pkill). The impl returns 6 fields on GET /_clock/current_utc where the scaffold
declares 2; PRD.md line 485 specifies only "Read the logical clock", so the superset is PRD-compatible
and NOT a defect — recorded here for Step 9 rather than "fixed".

--- Subagent report, verbatim ---

## Files written — `/home/ubuntu/github/CodingPRD/tasks/task_2645_rotational_molding_watercraft_plant/test_helpers/`

| File | Lines |
|---|---|
| `types.py` | 399 |
| `api_errors.py` | 203 |
| `api_client.py` | 488 |
| `constants.py` | 339 |
| `test_users.py` | 117 |
| `factories.py` | 690 |
| `assertions.py` | 445 |
| `fixtures.py` | 1261 |
| `__init__.py` | 712 |
| `API.md` | 1515 |

Nothing was written under `workspace/` (the `implementation/` and `step5_manifests/` dirs there belong to the parallel Step 5/6 run). `test_suite/` was not created. `__pycache__` removed.

`api_client.py` = 94 endpoint methods (57 POST, 36 GET, 1 PATCH) + 9 envelope/projection accessors (`read_data`, `read_entity`, `read_version`, `read_footprint_summary`, `read_cost_summary`, `read_freight_summary`, `read_clock`, `read_current_utc`, `set_current_utc`). `api_errors.py` = all 90 error ids as `ApiErrorId` + `HTTP_STATUS_CODES`, registered with the framework via `set_error_http_status_map` on import.

## Composite fixtures (name -> entities created -> returns)

Helpers/plumbing: `set_clock`, `reset_clock`, `current_utc`, `stale_version`, `warehouse_version`, `production_order_version`, `resin_lot_version`, `shipment_version`, `product_model_version`, `list_units_for_cycle`, `overlapping_window`.

- `create_technician(role_code)` -> 1 Technician (ACTIVE, role's required certifications) -> `technician`, `technician_id`, `headers`
- `create_customer(acknowledged_at=None)` -> 1 Customer (ACTIVE, optional guidance acknowledgement) -> `customer`, `customer_id`, `headers`
- `create_plant_baseline(clock=..., *_overrides)` -> ProductModel, Mold (AVAILABLE, 0 cycles since service), OvenStation (OPERATIONAL), CoolingBay (OPERATIONAL), 4 Technicians, Warehouse (NORMAL, 0 cube) -> ~28-key context incl. `resin_tech_headers`/`operator_headers`/`assembly_headers`/`inspector_headers`
- `create_resin_lot` -> ResinLot AVAILABLE, ledger all in `available_kg`
- `create_demand_bucket(ctx)` -> DemandForecastBucket whose window contains the clock date
- `create_production_order(ctx, release=True)` -> ProductionOrder READY_TO_SCHEDULE (or DRAFT)
- `schedule_cycle(ctx, order)` -> MoldingCycle SCHEDULED on arm 1 (version re-read before write)
- `reserve_charge(ctx, cycle, lot)` -> ResinCharge RESERVED, lot ledger moved available->reserved
- `setup_scheduled_cycle(...)` -> lot + released order + SCHEDULED cycle + RESERVED charge -> adds `resin_lot`, `production_order`, `molding_cycle`, `resin_charge`
- `run_cycle_to_oven_running` -> cycle OVEN_RUNNING, `actual_oven_start_at` set, clock at that instant
- `run_cycle_to_cooling` -> cycle COOLING, `actual_oven_end_at` set
- `run_cycle_to_demold` / `setup_demolded_units` -> cycle DEMOLDED, charge CONSUMED, one FinishedUnit per cavity (GREEN) -> adds `units`
- `advance_unit_to_outfitted(ctx, unit)` -> unit TRIMMED then OUTFITTED (assembly technician)
- `advance_unit_to_sellable(ctx, unit)` -> unit inspected PASS, `build_status` SELLABLE, `logistics_status` UNALLOCATED
- `setup_sellable_units(unit_count=None)` -> both hulls SELLABLE
- `setup_rework_unit` -> one hull inspected with cosmetic grade `C` -> verdict REWORK, `build_status` REWORK
- `setup_scrapped_unit` -> one hull inspected `REJECT` -> verdict SCRAP
- `store_unit(ctx, unit)` -> unit STORED in a zone, warehouse cube committed (warehouse version re-read)
- `setup_stored_units(unit_count=None)` -> hulls STORED, warehouse committed/utilisation/posture updated
- `setup_warehouse_at_posture(posture)` -> site capacity 20.0/2.2222/2.0 + one stored anchor -> NORMAL/RESTRICTED/FROZEN deterministically
- `setup_build_ahead_bucket(forecast_qty=2, build_ahead_cap_pct=60.0)` -> bucket with `build_ahead_cap_qty` 1 and one hull stored exactly on the cap
- `setup_mold_due_for_service` -> mould whose `cycles_since_service` has reached its interval
- `setup_depleted_resin_lot` -> lot whose `available_kg` reached 0.000 -> DEPLETED
- `setup_expired_resin_lot(expires_on, expiry_clock)` -> lot EXPIRED by moving the clock past `expires_on` (returns the sweep counters)
- `create_shipment(ctx)` -> Shipment PLANNED
- `load_unit(ctx, shipment, unit)` -> ShipmentLine LOADED, unit `logistics_status` LOADED (shipment version re-read)
- `setup_loaded_shipment(line_count=None)` -> shipment LOADING with one line per stored hull -> adds `shipment`, `shipment_lines`
- `setup_sealed_shipment` -> shipment SEALED, `sealed_at` and `quoted_freight_cents` set
- `setup_departed_shipment(departed_at=...)` -> shipment IN_TRANSIT
- `setup_delivered_units(delivered_at=...)` -> shipment DELIVERED, hulls DELIVERED, `billed_freight_cents` set
- `setup_delivered_unit_with_customer(acknowledged_at=..., delivered_at=...)` -> + ACTIVE Customer whose acknowledgement precedes delivery -> adds `customer`, `customer_headers`, `unit`
- `setup_submitted_claim` -> WarrantyClaim SUBMITTED (HULL_DEFORMATION, 4.50 mm)
- `setup_claim_under_review` -> claim UNDER_REVIEW
- `setup_claim_storage_verified` / `setup_claim_storage_violated` / `setup_claim_storage_waived` -> storage axis GUIDANCE_VERIFIED / GUIDANCE_VIOLATED / WAIVED
- `setup_approved_claim(waived=False)` -> claim APPROVED with all four money fields, model reserve drawn down (product-model version re-read immediately before approve)
- `setup_denied_claim(denial_reason=...)` -> claim DENIED, money fields all 0, no reserve movement
- `setup_cycle_with_spare_order` -> SCHEDULED cycle + second lot + second released order for overlap probes -> `spare_*` keys
- `setup_cooling_bay_at_capacity` -> same, with `concurrent_slot_capacity` 1 already occupied
- `setup_station_down` -> SCHEDULED cycle whose station is now DOWN
- `setup_mold_on_service_hold` -> baseline whose only mould is MAINTENANCE
- `setup_quarantined_lot_with_charge` -> SCHEDULED cycle whose reserved lot is now QUARANTINED

## Chain coverage

All 136 real design instances (25 difficulty + 111 corner) share one canonical setup chain; every distinct prefix in that corpus terminates at a ladder rung above, so 136/136 reach a pre-built fixture. Deliberately left inline for Stage 2: the *final* action of ten low-frequency endpoints — `unseal`, `cancel` (shipment/order), `remove` line, `restore`, `reinstate`, `release-quarantine`, `complete-service`, `void`, `return-to-queue`, `withdraw` — because each is a single POST on top of an existing rung and a dedicated fixture would only wrap one call. Also inline: negative-path variants that differ from a rung by exactly one overridden field (all rungs accept `*_overrides`).

## PRD ambiguities and resolutions (also recorded in `API.md` §12)

1. `ResinCharge.created_by_technician_id` — §2.8 client-supplied vs §3.2/endpoint "the acting identifier". Factory omits it; exposed as override for the identity-mismatch case.
2. `MoldingCycle.operator_technician_id` — same conflict, same resolution.
3. `Shipment.customer_id` — §3.8 requires an ACTIVE customer per trailer but neither the entity nor `POST /shipments` has the field. Factory omits it; the ACTIVE gate is untestable as specified.
4. Warpage index — scaffold 2dp/0–100 vs PRD 3dp clamped 0.000–5.000. PRD wins (`assert_warpage_index_shape`).
5. `min_wall_thickness_mm` — §2.8 two decimals vs §3.6 three. Assert the value, not the decimal count.
6. `density_kg_per_m3` — §2.8 two decimals vs §3.8 three (or exactly 0.000). Lenient.
7. `unit_cost_cents` — default 0 vs "null while `completed_qty` is 0". Accept either.
8. `months_in_service` — default 0 vs "null at creation". Accept either.
9. `build_ahead_cap_qty` — constraint `>= 1` vs default 0. Accept `>= 0`.
10. `depart`/`deliver` — prose says server stamps from the clock, inputs carry the stamps. Client sends them; fixtures set the clock to the same instant so both readings agree.
11. Clock sweep counters — §2.5 prose puts them on the read, the schema only on the write. `ClockAdvanceResult` carries them; optional on reads, asserted on `set_current_utc`.

Corrections made this session while writing `API.md`: `POST /resin-lots/{id}/quarantine` takes **no** `expected_resin_lot_version` (verified against §3.2 and the endpoint input) — the fixture was fixed; three docstring section references were wrong (roles are §2.1, error catalogue is §5) and were corrected in `__init__.py` and `API.md`.

## Verification

- `python3 -m py_compile` on all nine `.py` files: OK for each.
- `python3 -c "import test_helpers; ..."` from the task root: clean import, **340** public names exported (barrel re-exports the 17 framework names plus every module's public surface; `__all__` is explicit).
- `test_suite/` does not exist; no file from this stage landed under `workspace/`.

## Step 5 Stage 2 — partition P2 (Difficulty rules 6-9) — 2026-09-04T06:18:17.609605081Z

--- Subagent report, verbatim ---

## Files written (all under `test_suite/`)

| file | lines | tests |
|---|---|---|
| `test_d_precision_and_resource_01_boundaries.py` | 505 | 7 |
| `test_d_precision_and_resource_02_intervals.py` | 466 | 9 |
| `test_d_precision_and_resource_03_cross_entity.py` | 511 | 6 |
| `test_d_precision_and_resource_04_ledgers.py` | 626 | 8 |
| **total** | **2108** | **30** |

No other path in `test_suite/` was created or touched; `conftest.py` and everything under `test_helpers/` are untouched.

## Instances TRANSLATED — 11 of 11, every one with >=2 tests

`boundary_precision_check`
- `regrind_ceiling_exact_30_00_pct_accepted_vs_30_01_rejected` (3) -> `test_regrind_blend_exactly_at_the_model_ceiling_is_accepted`, `test_regrind_blend_one_hundredth_above_the_ceiling_is_refused_and_writes_nothing`, `test_regrind_pct_is_rounded_half_up_to_two_decimals_before_the_ceiling_test`
- `warehouse_frozen_threshold_rounded_95_00_freezes_vs_95_01_threshold` (2) -> `test_utilization_rounding_up_to_exactly_the_frozen_threshold_freezes_the_site`, `test_utilization_one_hundredth_below_the_frozen_threshold_stops_at_restricted`
- `inspection_measurement_count_six_accepted_vs_five_rejected` (2) -> `test_inspection_with_five_measurement_points_is_refused_and_writes_nothing`, `test_inspection_with_exactly_six_measurement_points_is_accepted_and_passes`

`resource_temporal_overlap`
- `oven_arm_half_open_span_with_symmetric_changeover_buffer` (3) -> `test_oven_arm_booking_one_second_inside_the_buffered_span_is_refused`, `test_oven_arm_booking_exactly_at_the_buffered_end_instant_is_accepted`, `test_two_arms_of_one_station_hold_fully_coincident_oven_windows`
- `cooling_bay_closed_interval_aggregate_slot_capacity` (3) -> `test_cooling_windows_touching_at_one_instant_both_hold_slots_of_a_two_slot_bay`, `test_third_cycle_intersecting_two_closed_cooling_windows_is_refused`, `test_shifting_one_second_past_the_touching_instant_frees_a_cooling_slot`
- `mold_half_open_oven_plus_cooling_span_occupancy_vs_capability` (3) -> `test_mold_span_covers_cooling_so_an_overlap_reports_a_window_conflict`, `test_mold_is_reselected_at_the_exact_end_of_its_half_open_span`, `test_empty_available_mold_pool_reports_a_capability_failure_not_a_window_conflict`

`cross_entity_state_dependency`
- `production_order_blocks_on_resin_lot_quarantine_and_unblocks_on_release` (3) -> `test_quarantining_the_only_qualified_lot_blocks_the_order_and_its_next_cycle`, `test_release_quarantine_returns_the_order_to_ready_and_admits_the_identical_booking`, `test_cycles_aborted_by_the_quarantine_are_not_resurrected_by_the_release`
- `finished_unit_store_gated_by_warehouse_frozen_posture` (3) -> `test_second_store_freezes_the_site_and_the_third_store_is_refused_frozen`, `test_release_storage_of_a_non_anchor_sibling_unfreezes_and_unblocks_the_order`, `test_store_gate_is_re_evaluated_so_the_re_issued_store_refreezes_the_site`

`compensating_invariant`
- `resin_mass_ledger_conserved_across_reserve_release_and_irreversible_consume` (3) -> `test_reserving_to_exactly_zero_depletes_the_lot_and_the_release_restores_it_exactly`, `test_start_oven_moves_reserved_mass_to_consumed_without_creating_or_destroying_mass`, `test_aborting_from_oven_running_leaves_the_consumed_mass_on_the_lot`
- `warranty_reserve_ledger_conserved_across_approve_and_void` (2) -> `test_approving_a_claim_moves_the_identical_integer_between_the_two_reserve_buckets`, `test_voiding_an_approved_claim_restores_the_reserve_exactly_and_retains_the_money_fields`
- `storage_footprint_conserved_with_asymmetric_anchor_promotion` (3) -> `test_nested_stores_accumulate_the_committed_cube_at_four_decimals`, `test_releasing_the_anchor_promotes_the_earliest_survivor_and_costs_less_than_it_freed`, `test_the_re_stored_former_anchor_returns_as_a_follower_and_the_site_total_comes_back`

## Instances SKIPPED

None. Every instance passed both filters: each threshold has an explicit comparison direction and scale in PRD.md (§2.4 half-up "every intermediate result that a later step reads is rounded before that step runs"; §2.8 `max_regrind_pct` "compared with strictly-greater so a charge set exactly at the ceiling passes" and `frozen_threshold_pct` "compared with at-or-above"; §3.2's own worked 30.00/30.01 example; §3.6 "at least six numeric measurements"; §3.7 "at exactly 95.00 it is `FROZEN`, 84.99 is `NORMAL`, 94.99 is `RESTRICTED`, and a raw utilisation of 94.995 rounds to 95.00"), and §2.9 states all three interval conventions separately with one-second worked examples, so the divergent semantics were asserted per instance and never unified.

## test_helpers gaps worked around locally (nothing edited there)

1. **No way to inject a clock move into the warranty claim ladder.** `setup_claim_under_review` calls `setup_submitted_claim` then `start_claim_review` back to back, so `months_in_service` is always frozen at 0 and coverage is always 100.00 — the design's 6-month literals (162000 / 12960 / 149040 / 350960) are unreachable through the fixtures. Worked around with the partition-local `_p2_claim_priced_at_six_months()` in file 04, which reuses `setup_submitted_claim`, moves the clock to `2027-02-02T00:00:00Z`, then calls `start_claim_review` and `submit_storage_review("VERIFIED")` itself. Suggested fixture improvement: a `clock` / `review_at` kwarg on `setup_claim_under_review`.
2. `unique_code`'s counter is zero-padded to 3 digits, so lexicographic order breaks once the per-process counter passes 999. File 02 passes explicit `mold_code=unique_code("MZA"/"MZB"/"MZC")` so the leading letter dominates the ascending-`mold_code` mould ranking. Not a bug in the helper, but a trap for any test that relies on generated-code ordering.
3. Other partition-local helpers exist only to reproduce design geometry the shared fixtures do not parameterise (`_P2_SINGLE_CAVITY`, `_p2_site`, `_p2_interval_plant`, `_P2_TIGHT_SITE`, `_P2_TWO_SHOT_PLANT`, `_P2_THREE_SIBLINGS`); no helper was found to be wrong.

## PRD ambiguities and how they were resolved

1. **Exact success status.** Neither PRD.md nor API.md ever names 201 or any specific 2xx for creates (§2.2 only guarantees "2xx"), so exact-status success assertions are not uniquely derivable. Every success uses the lenient `get_success_data(res)`; every failure uses `validate_error(res, ApiErrorId.X, <status PRD states>)` with the PRD's declared code (422/409).
2. **`abort_reason` on an operator abort.** §3.5 says CASCADE-A sets `abort_reason` `OPERATOR_ABORT` while the request body also carries an `abort_reason`, and it never says what an `OVEN_RUNNING` abort stores. The stored `abort_reason` is therefore asserted only for cascade-driven aborts (`LOT_QUARANTINED`, `MOLD_SERVICE_DUE`), never for the operator-initiated one; only `status == "ABORTED"` is asserted there.
3. **Lot version after an `OVEN_RUNNING` abort.** §3.5 names exactly whose versions advance ("the cycle's `version` advances by 1") and states that no mass moves, so the lot's version is asserted unchanged.
4. **Design-recipe arithmetic typo** (reported, not propagated): the inspection instance writes `sqrt(0.0255 / 6)` where the sum of squared deviations is 0.025. Both round to `wall_sd_mm == 0.065`, and the design's literal `0.065` was used verbatim.

## Static validation (no server started, no tests run, no `pkill`)

- `python3 -m py_compile` on each of the four files: all four report OK (no output, exit 0).
- AST sweep: 0 unused imports in each file.
- `python3 -m pytest test_suite/test_d_precision_and_resource*.py --collect-only -q` -> **`30 tests collected in 0.18s`**, zero errors, zero warnings. Test-count breakdown matches the per-instance table above (7 + 9 + 6 + 8 = 30, and the 11 `Design:` lines sum to 30 occurrences).
- Grep confirms no occurrence of "scaffold", "§1.", or any design-table label anywhere in generated code outside the mandated `Design: Difficulty/...` lines, each copied verbatim from `workspace/step5_manifests/P2.md`.

## Step 5 Stage 2 — partition P1 (Difficulty rules 1-5) — 2026-09-04T06:31:51.12826972Z

Orchestrator note: P1 made a deliberate, reasoned DEVIATION from its design instance's setup data
(pair2 thin lot 10.000 kg -> 23.000 kg). I reviewed it and it is correct, and it is the right kind of
call: at 10.000 kg the lot fails mass qualification (PRD §3.2 requires available_kg >= the 22.800 kg
minimum shot), so ERR_RESIN_LOT_NOT_QUALIFIED would fire at an earlier band and the pair being tested
(regrind ceiling beats resin insufficiency) would be unobservable — the design instance's own setup
defeated its assertion. 23.000 kg clears qualification while still holding less than the 24.000 kg
shot, so the losing member stays live and the graded assertion is unchanged. Recorded here because it
is a scaffold defect, not a test defect: the design instance's literal setup mass is wrong.

--- Subagent report, verbatim ---

## Files written (only `test_suite/test_d_calc_and_state*.py`; `conftest.py` untouched)

| file | lines | tests |
|---|---|---|
| `test_d_calc_and_state_01_dual_variant_pricing_and_tooling.py` | 524 | 9 |
| `test_d_calc_and_state_02_combinatorial_formulas.py` | 617 | 8 |
| `test_d_calc_and_state_03_nonlinear_lifecycle_forks.py` | 821 | 8 |
| `test_d_calc_and_state_04_transitive_cascades.py` | 526 | 5 |
| `test_d_calc_and_state_05_validation_precedence_pairs.py` | 848 | 12 |
| **total** | **3336** | **42** |

## Instances TRANSLATED (14/14, all >=2 tests)

**dual_variant_calc** — `freight_quote_nested_vs_bill_gross_divergence` -> `test_quoted_variant_prices_every_line_on_nested_cube_at_seal`, `test_billed_variant_prices_every_line_on_gross_cube_at_delivery`, `test_line_cube_basis_diverges_by_nest_position` (3). `warpage_provisional_schedule_vs_final_actual_divergence` -> `test_provisional_variant_scores_the_scheduled_cooling_deficit`, `test_final_variant_scores_actual_cooling_and_measured_distribution`, `test_both_indices_are_retained_side_by_side_on_different_rows` (3). `mold_selection_first_attempt_vs_retry_with_exclusions` -> `test_first_attempt_takes_the_lowest_mold_code_of_the_full_pool`, `test_retry_with_an_exclusion_takes_the_second_ranked_tool`, `test_exclusion_that_empties_the_pool_is_never_a_window_conflict` (3).

**combinatorial_formula** — `wall_distribution_nested_rounding_mean_then_sd_then_cv` -> `test_mean_then_sd_then_cv_each_read_the_previous_rounded_value`, `test_variation_exactly_at_the_model_ceiling_passes_instead_of_reworking` (2). `zone_selector_anchor_affinity_then_remaining_then_promotion` -> `test_anchor_affinity_outranks_a_looser_fitting_empty_zone`, `test_a_zone_that_cannot_fit_the_nested_follower_opens_a_second_group`, `test_releasing_the_anchor_promotes_the_earliest_follower_upward` (3). `warranty_payout_gross_then_fee_tier_then_storage_deduction` -> `test_the_fee_tier_is_chosen_from_the_gross_not_from_the_reduced_amount`, `test_the_claim_type_factor_lands_the_same_hull_in_a_cheaper_fee_band`, `test_two_payouts_move_the_reserve_ledger_by_exactly_their_nets` (3).

**non_linear_state_machine** — `molding_cycle_scheduled_fork_with_divergent_abort_compensation` -> `test_aborting_from_scheduled_returns_the_reserved_shot_to_the_lot`, `test_aborting_from_oven_running_scraps_the_consumed_shot`, `test_neither_branch_mints_a_hull_and_only_the_consumed_shot_is_costed` (3). `finished_unit_rework_loop_edge_closed_by_logistics_axis` -> `test_the_rework_verdict_travels_backward_and_clears_the_hardware_kit`, `test_the_second_lap_reaches_sellable_without_refunding_the_rework_budget`, `test_storing_the_hull_closes_the_edge_out_of_sellable_for_good` (3). `shipment_unseal_revert_forces_requote_on_a_new_discount_tier` -> `test_unsealing_destroys_the_quote_and_the_seal_stamp`, `test_resealing_requotes_from_scratch_on_a_newly_selected_tier` (2).

**transitive_cascade** — `demold_service_cascade_unblocks_three_resin_blocked_orders` -> `test_the_demould_wears_the_tool_into_maintenance_and_aborts_its_other_cycle`, `test_the_released_charge_revives_its_lot_and_unblocks_all_three_orders`, `test_the_unblocked_order_is_schedulable_yet_has_no_eligible_tool` (3). `reinspect_demotion_reopens_complete_order_and_raises_unit_cost` -> `test_the_demotion_lowers_the_rollup_and_reopens_the_complete_order`, `test_the_unit_cost_doubles_although_no_cost_input_moved` (2).

**priority_pair_validation_conflict** — `pair1_order_not_schedulable_beats_oven_window_conflict` -> `test_the_unreleased_order_is_reported_and_the_taken_arm_is_not`, `test_the_refusal_writes_no_cycle_and_bumps_no_version`, `test_control_a_reproduces_the_verdict_from_the_order_state_alone`, `test_control_b_shows_the_arm_conflict_was_live_and_merely_suppressed` (4). `pair2_regrind_limit_beats_resin_insufficient` -> `test_the_blend_breach_is_reported_and_the_shortfall_is_not`, `test_the_refused_charge_moves_no_mass_and_leaves_no_row`, `test_control_b_shows_the_shortfall_was_live_and_merely_suppressed`, `test_control_a_reproduces_the_verdict_from_the_blend_alone` (4). `pair5_storage_review_incomplete_beats_warranty_term_expired` -> `test_control_a_reproduces_the_verdict_from_the_undecided_axis_alone`, `test_the_undecided_axis_is_reported_and_the_expired_term_is_not`, `test_control_b_shows_the_expired_term_was_live_and_merely_suppressed`, `test_none_of_the_three_refusals_prices_the_claim_or_moves_the_reserve` (4).

All three pairs pass both filter conditions on PRD.md §2.7 line 134, which names pairs 1, 2 and 5 verbatim, reinforced by §3.4 ("Then the oven arm window, then the bay slot count..."), §3.2 ("A candidate charge that would both breach the ceiling and overdraw the lot reports the regrind failure, never the insufficiency") and §3.9 ("In order: ... the storage axis must be `GUIDANCE_VERIFIED` or `WAIVED` ... refused before pricing begins").

## Instances SKIPPED
None. Every instance had a quotable PRD sentence and a uniquely derivable outcome.

## test_helpers gaps / workarounds
- No gaps or bugs found; nothing under `test_helpers/` was edited and no `_p1_` fixture substitute for a conftest fixture was needed. All conftest fixtures were unnecessary for my partition (helpers are imported directly), so no fixture conflicts.
- `create_plant_baseline` builds only one mould, so pair 1's second tool is created inline with `api_client.create_mold(mold_payload(...), ADMIN_HEADERS)` — an intended use of the exported factory, not a workaround.

## Design-instance deviation (important)
- **pair2 setup mass changed from 10.000 kg to 23.000 kg.** The manifest's `LOT-P2-SMALL` at `received_kg` 10.000 is *unqualified on mass* under PRD §3.2 line 224 (qualification requires `available_kg` >= the 22.800 kg minimum shot mass), and §3.2 line 228 refuses an unqualified lot with `ERR_RESIN_LOT_NOT_QUALIFIED` (422) — a band-5 check the manifest itself declares vacuous. A PRD-only implementer could therefore legitimately answer `ERR_RESIN_LOT_NOT_QUALIFIED` and the pair would be unobservable. I set the thin lot to 23.000 kg, which clears qualification (23.000 >= 22.800) while still holding less than the 24.000 kg shot, so the losing member (`ERR_RESIN_INSUFFICIENT`) stays live and the graded assertion — regrind wins, 422 not 409 — is unchanged. All error ids, statuses and blends (50.00 / 10.00) are copied from the manifest verbatim.

## PRD ambiguities resolved
1. **OCC band vs the approve ladder.** §2.7 band 8 puts optimistic concurrency "last of all", but §3.9 line 370 places the version check between the storage-axis check and the customer-active check. Resolved by always sending a freshly read `expected_product_model_version`, so the ordering is never load-bearing.
2. **`months_in_service` initial value.** §2.8 says "integer, default 0"; §3.9 says "`months_in_service` null" on a new claim. Never asserted before start-review; only the frozen post-review values (12 and 62) are asserted.
3. **Clock rollback.** §3.2 line 238 says "The clock is never rolled backward past a recorded actual timestamp" but declares no error id, and every baseline fixture resets the clock to `2026-08-01T00:00:00Z`. Treated as non-enforced; each of my setup helpers resets the clock itself, so tests are order-independent regardless of what a sibling partition left behind.
4. Earlier resolutions still stand: non-PRD projection keys (`quoted_pre_discount_cents`, per-zone footprint keys, `loaded_line_count`) are never asserted; `ShipmentLine.line_freight_cents` is not asserted; `min_wall_thickness_mm` (2dp in §2.8 vs 3dp in §3.6) is asserted only at values identical under either reading; global clock sweep counters are never asserted (shared server state), only my own rows.

## Static validation (exact results)
- `python3 -m py_compile` on all five files: silent success for each (`TOTAL COMPILE_OK`); AST audit confirms **zero unused imports** and no undefined names in file 05.
- `python3 -m pytest test_suite/test_d_calc_and_state_01_*.py ... test_suite/test_d_calc_and_state_05_*.py --collect-only -q` -> **`42 tests collected in 0.21s`**, zero collection errors, zero warnings. Tests were not executed and no server was started.

## Process deviations to note
- Two `cat >>` chunks exceeded the <=150-line mandate (one at 155, one at 211 lines). Both landed intact, confirmed by `wc -l` after each append; no work was lost.
- Several Bash calls used paths relative to the task directory because the shell cwd had persisted there (including the mandated `pytest` invocation). All file writes and `py_compile` calls used absolute paths.

## Step 5 Stage 2 — partition P3 (Corner: entities + endpoints) — 2026-09-04T06:32:55.997067442Z

ORCHESTRATOR ACTION ITEM raised by this partition — two central test_helpers bugs, to be fixed by ME
once all seven partitions have landed (fixing now would race four still-running agents):

  (A) `factories.molding_cycle_payload` omits `operator_technician_id` and `factories.resin_charge_payload`
      omits `created_by_technician_id`, yet PRD §2.8 declares BOTH required client-supplied fields
      ("required, must resolve or ERR_TECHNICIAN_NOT_FOUND, and must equal the acting identifier at
      creation"). Stage 1 chose to omit them and expose overrides; P3 is right that this is wrong.
      Every fixture built on schedule_cycle/reserve_charge inherits the omission, so a PRD-faithful
      implementation would 422 the ENTIRE fixture tier — i.e. the classic Step 7 iteration-1 wipeout
      where ~90% of tests fail as setup errors and the implementation looks broken when the fixtures
      are at fault. Sending the field (equal to the acting identity) is valid under BOTH readings of
      the PRD, so it is strictly the safer choice. Central fix: populate both fields from the acting
      technician in the factories and in schedule_cycle/reserve_charge. P3's local `_p3_` overrides
      remain correct after the fix (same value, override simply wins).
  (B) `setup_warehouse_at_posture(posture, baseline=...)` SILENTLY drops its own `warehouse_overrides`,
      because `setup_scheduled_cycle` does `dict(baseline or create_plant_baseline(**baseline_kwargs))`
      — passing an explicit `baseline=` discards the capacity/zone sizing and yields a NORMAL site
      instead of the requested posture, with no error. Any partition that trusted this fixture to
      produce RESTRICTED or FROZEN got NORMAL. Central fix required.

--- Subagent report, verbatim ---

## Files written (all under `test_suite/`)

| File | Lines | Tests |
|---|---|---|
| `test_c_entities_and_endpoints_01_registration_reads_and_envelope.py` | 373 | 7 |
| `test_c_entities_and_endpoints_02_collection_pagination_and_filters.py` | 434 | 9 |
| `test_c_entities_and_endpoints_03_required_fields_defaults_and_type_constraints.py` | 584 | 15 |
| `test_c_entities_and_endpoints_04_foreign_keys_supersession_and_immutability.py` | 809 | 18 |
| `test_c_entities_and_endpoints_05_derived_cycle_windows_and_minted_hulls.py` | 387 | 6 |
| `test_c_entities_and_endpoints_06_hull_discovery_model_patch_and_cost_summary.py` | 507 | 9 |
| `test_c_entities_and_endpoints_07_footprint_summary_and_clock_sweep.py` | 348 | 4 |
| `test_c_entities_and_endpoints_08_equipment_action_endpoints_and_their_cascades.py` | 330 | 4 |
| `test_c_entities_and_endpoints_09_release_ladder_and_claim_return_to_queue.py` | 454 | 6 |

**Total 4226 lines, 79 tests.** `conftest.py` untouched; nothing under `test_helpers/` modified; no file written outside the `test_c_entities_and_endpoints*.py` pattern.

## Instances TRANSLATED (25 of 25 — no skips)

**entities (13)**
- `ent_create_product_model_returns_201_with_warranty_ledger_seeded` -> `TestProductModelRegistration::test_create_returns_201_and_seeds_the_warranty_ledger`, `::test_single_read_returns_the_same_values_as_the_create_body` (file 01)
- `ent_get_mold_by_id_returns_stored_tool_with_counter_zero` -> `TestMoldRegistrationRead::test_get_mold_shows_zero_counter_available_and_null_predecessor` (01)
- `ent_get_nonexistent_resin_lot_returns_resource_not_found` -> `TestUnknownIdentifierResolution::test_unknown_path_id_is_404_on_reads_actions_and_computed_reads`, `::test_a_real_identifier_on_the_same_computed_route_still_returns_200` (01)
- `ent_list_molds_pagination_total_count_and_has_more` -> `TestMoldListPagination` x4 (02)
- `ent_required_fields_and_declared_types_enforced_on_creation` -> `TestRequiredFieldsAndDeclaredTypes` x4 (03) — the three deliberate omissions (`zones`, `service_interval_cycles`, `ordered_qty`) are sent verbatim and assert 422
- `ent_defaults_warehouse_thresholds_bucket_cap_pct_and_null_optional_fks` -> `TestDeclaredDefaultsOnOmittedFields` x3 (03)
- `ent_type_constraints_enum_member_numeric_range_and_window_order` -> `TestTypeConstraintFamilies` x8 (03)
- `ent_parent_product_model_fk_raises_a_dedicated_error_ahead_of_generic_fks` -> `TestProductModelParentReference` x3 (04)
- `ent_flat_fk_body_references_validated_before_state_occ_and_business_rules` -> `TestBodyForeignKeysOutrankStateAndConcurrency` x7 (04) — sentinel FK `...00ff` plus hardcoded `expected_*_version` 99/1 preserved exactly
- `ent_flat_self_referential_mold_supersession_requires_a_retired_peer_of_the_same_model` -> `TestMoldSupersessionChain` x4 (04)
- `ent_immutability_no_write_path_for_system_minted_units_or_structural_model_fields` -> `TestPerFieldImmutability` x4 (04)
- `ent_computed_cycle_windows_and_charge_rollups_derived_not_supplied` -> `TestDerivedCycleWindowsAndChargeRollups` x4 (05)
- `ent_system_fields_on_finished_unit_minted_by_the_demold_cascade` -> `TestHullsMintedByTheDemouldCascade` x2 (05)

**endpoints (12)**
- `ep_response_envelope_success_and_error_shapes_on_one_resource` -> `TestResponseEnvelope` x2 (01)
- `ep_product_model_list_pagination_defaults_and_offset_window` -> `TestProductModelListPagination` x3 (02)
- `ep_product_model_list_filters_compose_and_can_narrow_to_zero_rows` -> `TestProductModelListFilters` x2 (02)
- `ep_finished_unit_filtered_list_is_the_only_discovery_channel_for_its_fks` -> `TestHullListIsTheOnlyDiscoveryChannel` x5 (06)
- `ep_product_model_patch_narrows_limits_without_rejudging_a_passed_hull` -> `TestModelAmendmentDoesNotRejudgeStoredMeasurements` x2 (06)
- `ep_production_order_cost_summary_zero_state_then_completed_state` -> `TestOrderCostSummaryZeroThenComplete` x2 (06)
- `ep_warehouse_footprint_summary_zone_breakdown_matches_the_stored_hulls` -> `TestWarehouseFootprintSummary::test_site_totals_and_posture_report_the_nested_pair`, `::test_zone_breakdown_names_the_anchor_model_and_counts_both_hulls` (07)
- `ep_clock_set_current_utc_returns_the_four_declared_cascade_counters` -> `TestClockSetSweepCounters::test_advancing_to_the_expiry_date_itself_sweeps_nothing`, `::test_advancing_past_the_expiry_date_returns_all_four_counters` (07)
- `ep_mold_service_hold_aborts_its_cycle_then_complete_service_resets_the_counter` -> `TestMoldServicePair` x2 (08)
- `ep_oven_station_mark_down_aborts_only_the_scheduled_cycle_on_that_station` -> `TestOvenStationMarkDown` x2 (08)
- `ep_production_order_release_precondition_ladder_frozen_then_mold_then_resin` -> `TestProductionOrderReleaseLadder` x4 (09)
- `ep_warranty_return_to_queue_revokes_the_waiver_and_resets_the_other_axis` -> `TestClaimReturnToQueue` x2 (09)

## test_helpers gaps worked around locally (please fold back centrally)

1. **`factories.molding_cycle_payload` omits `operator_technician_id`** and **`factories.resin_charge_payload` omits `created_by_technician_id`**, but PRD.md §2.8 lists both as *required* client-supplied fields (`MoldingCycle.operator_technician_id`: "required, must resolve or `ERR_TECHNICIAN_NOT_FOUND`, and must equal the acting identifier at creation"; `ResinCharge.created_by_technician_id`: "required, must resolve ... and must equal the acting identifier"). Every fixture built on `schedule_cycle`/`reserve_charge` inherits the omission, so a spec-faithful implementation would 422 the whole fixture tier. Worked around with `_p3_schedule_cycle`/`_p3_charge_payload` (file 05) and `_p3_identity_overrides` (files 06-09), which inject the acting identifier — valid under both PRD readings.
2. **`setup_warehouse_at_posture(posture, baseline=...)` silently drops its own `warehouse_overrides`.** Because `setup_scheduled_cycle` does `dict(baseline or create_plant_baseline(**baseline_kwargs))`, passing an explicit `baseline=` discards the capacity/zone sizing and yields a NORMAL site instead of the requested posture — with no error. File 09 therefore builds the frozen site by passing `warehouse_overrides` to `create_plant_baseline` itself and then calling `setup_stored_units(baseline=..., unit_count=1)`.

## PRD ambiguities and design/PRD divergences resolved

- **Release outcomes are self-contradictory in PRD.md.** §3.3 lists `ERR_WAREHOUSE_FROZEN` (409) and `ERR_RESIN_INSUFFICIENT` (409) as hard preconditions, then immediately says "Two soft outcomes also exist, and both still return HTTP 200" moving the order to `BLOCKED_WAREHOUSE`/`BLOCKED_RESIN`; §3.2 corroborates the soft reading ("the releasing request still succeeds with HTTP 200"). Both encodings are faithful. The *precedence* claim (site before tool before resin) is unambiguous, so `_p3_assert_reported_condition` asserts **which condition is reported** and accepts either encoding, branching the follow-up state assertions. The mould gate has no soft alternative, so it is asserted hard (`ERR_NO_ELIGIBLE_MOLD`, 409). **This is the single biggest PRD defect in my partition.**
- **`unit_cost_cents` default**: §2.8 says ProductionOrder's money fields are "all integers defaulting to 0"; §3.3 says "`unit_cost_cents` null". Accepted `in (0, None)` in files 03 and 09 with an in-code comment.
- **`weighted_melt_index_g10min` at zero mass**: §2.8 "default 0.00" vs §3.2 "the weighted index is null" -> asserted `is None` (the more specific sentence).
- **`replaces_mold_id` on a non-RETIRED peer**: §2.8 says `ERR_MOLD_NOT_AVAILABLE`, §3.1 says `ERR_INVALID_MOLD_REPLACEMENT` -> `validate_error_is_one_of` + `status_code in (409, 422)`, both sentences quoted.
- **Clock read endpoint**: §2.5 says it reports "three counters" then names four. Only `current_utc` is asserted on `GET /_clock/current_utc`.
- **Design YAMLs use non-PRD enum members**: `resin_grade: HDPE_CROSSLINK` and `hull_type: PONTOON` are outside PRD's declared sets -> substituted `HDPE_XL`/`MDPE` and `CANOE`.
- **Design expects `ERR_INVALID_QUANTITY` for out-of-range `limit`**; PRD §2.3 names `ERR_VALIDATION` -> followed PRD.
- **Design expects generic `ERR_RESOURCE_NOT_FOUND` for body FKs PRD gives dedicated codes** -> followed PRD's dedicated codes. Path-id not-found is ambiguous under §2.7 -> `one_of([<ENTITY>_NOT_FOUND, RESOURCE_NOT_FOUND])` plus an explicit `status_code == 404`.
- **Footprint-summary per-zone fields**: `stored_unit_count` and `anchor_product_model_ids` initially looked ungrounded, but PRD §3.1 names the entire projection verbatim ("a `zones` array of `{ zone_code, capacity_cube_m3, committed_cube_m3, remaining_cube_m3, anchor_product_model_ids, stored_unit_count }`"), so both are asserted. The frozen site in file 09 uses 100.00 % rather than the design's 95.24 % because §3.7 accepts a store landing exactly at capacity and both freeze the site.

## Static validation (exact results)

- `python3 -m py_compile` on each of the nine files: **all OK**, no output.
- AST unused-import sweep across all nine files: **UNUSED: none**.
- `python3 -m pytest test_suite/test_c_entities_and_endpoints*.py --collect-only -q` -> **`79 tests collected in 0.49s`, zero collection errors**.
- No tests were executed and no server was started, per instructions.

### Orchestrator adjudication of the two P3 action items (evidence-based, before touching anything)

(A) NOT A BUG against this implementation — no central fix made. I read the PRD and the impl rather than
    trusting either the Stage 1 or the P3 reading:
      - PRD §2.8 line 158/162 DOES list `created_by_technician_id` and `operator_technician_id` under
        "Client-supplied" as required.
      - PRD §3.2 line 228 and §3.4 line 262 enumerate the request fields and OMIT both, then say
        "`created_by_technician_id` is the acting identifier" / "`operator_technician_id` is the acting
        identifier" — i.e. server-derived.
      So the PRD contradicts itself. The implementation (r_resin.py:172, r_cycles.py:29) resolved it
      tolerantly: both fields are `required: False`; if supplied they must equal the acting identifier
      (else ERR_ROLE_IDENTITY_MISMATCH at r_resin.py:204 / r_cycles.py:64); the stored value is always
      ctx.user_id (r_resin.py:275, r_cycles.py:184). Therefore Stage 1's omission and P3's injection are
      BOTH accepted, there is no fixture-tier wipeout risk, and editing factories.py would buy nothing
      while risking 136 already-collecting tests. Deliberately NOT changed.
      -> Carried to Step 8/9 as a genuine PRD defect: §2.8 and §3.2/§3.4 must agree on whether these two
         fields are client-supplied or server-derived.

(B) CONFIRMED REAL fixture bug, impl-independent. fixtures.py:699-706 does
    `kwargs.setdefault("warehouse_overrides", {...})` and forwards `**kwargs` to setup_stored_units, but
    setup_scheduled_cycle (fixtures.py:367+) does `dict(baseline or create_plant_baseline(**baseline_kwargs))`
    — so when a caller passes an explicit `baseline=`, the posture sizing is silently discarded and the
    site comes back NORMAL no matter which posture was requested. Callers that do NOT pass `baseline=`
    are unaffected. Central fix deferred until all seven partitions land (fixing now races the four still
    running), and it will be a LOUD failure rather than a silent one: reject `baseline=` with a clear
    error instead of ignoring the sizing, so no test can quietly assert against the wrong posture.

## Step 5 Stage 2 — Partition P4 (corner: state_machines + rbac) — 2026-09-04T06:20:00.000Z

Subagent report, verbatim:

All 23 P4 instances are translated. Final report follows.

## Files written (all under `test_suite/`)

| file | lines | tests |
|---|---|---|
| `test_c_statemachines_and_rbac_01_cycle_machine.py` | 965 | 7 |
| `test_c_statemachines_and_rbac_02_axes_and_cascades.py` | 1355 | 9 |
| `test_c_statemachines_and_rbac_03_role_gates.py` | 497 | 4 |
| `test_c_statemachines_and_rbac_04_warranty_and_scope.py` | 341 | 3 |
| **total** | **3158** | **23** |

No other path in `test_suite/` was created or touched; `conftest.py` and everything under `test_helpers/` are unmodified (conftest mtime still 05:48).

## Instances TRANSLATED (23 of 23; zero skipped)

`state_machines` (16, files 01-02) - cycle spine, start-oven preconditions, start-oven side effects,
invalid triggers, initial state, terminal lockdown, idempotency (file 01); mould-service round trip,
parallel axes, pool-guarded create/enter-cooling, shipment-line guards, bubble-up to COMPLETE,
downward re-derivation on scrap, station mark-down cascade, conditional lot-expiry sweep, claim
return-to-queue (file 02).

`rbac` (7, files 03-04):
- rbac_missing_blank_and_unknown_identity_headers_are_refused_before_role_lookup
- rbac_shop_floor_and_planner_roles_denied_on_each_others_exclusive_actions
- rbac_role_code_discrimination_among_the_four_technician_backed_roles
- rbac_positive_matrix_every_role_performs_its_own_and_its_shared_operations
- rbac_warranty_adjudication_split_across_agent_admin_and_customer
- rbac_customer_scope_confines_reads_and_writes_to_its_own_rows
- rbac_role_code_identity_shadows_the_segregation_of_duties_gate

A diff of the 23 emitted `Design:` lines against the manifest's 23 is empty - every instance covered
exactly once, no extras. All negative `as:` values were preserved verbatim, including `as: None`
(conftest `no_auth_headers`) and the non-existent role string "PlantAdministrator" sent through
`build_user_headers`.

## Instances SKIPPED
None.

## test_helpers gaps worked around locally
1. **No builder for partial identity headers.** `build_user_headers` always emits both `X-User-ID` and
   `X-User-Role`, and conftest's `no_auth_headers` only covers the fully header-less case. I added
   `_p4_headers_without_role(user_id)` and `_p4_headers_with_blank_identity(role)` at the top of file 03.
   Worth folding into `test_helpers/test_users.py` centrally.
2. **`shipment_payload` omits `customer_id`** (`factories.py:414`) while PRD.md 3.8 line 336 says
   "A `Shipment` is a trailer booked by a `LogisticsPlanner` against one `customer_id` ... Creation
   requires the customer to be `ACTIVE`". PRD.md 2.8 line 166's client-supplied list for Shipment does
   *not* list `customer_id`, so the helper matches the field reference, not the narrative. Not worked
   around - it made one probe underivable. Flagging because if the field is in fact required, every
   shipment fixture in `test_helpers` fails at intake.
3. No fixture produces "one hull SELLABLE, its sibling OUTFITTED"; composed from
   `setup_sellable_units(unit_count=1)` + `advance_unit_to_outfitted(...)`, no local helper needed.
4. Recipes name the inspect outcome field `inspection_result`; the PRD field (2.8 line 164, 3.6 line 308)
   is `inspection_verdict`, which is what `test_helpers` and my tests use. Recipe typo, not a helper bug.

## PRD ambiguities resolved
- **Hull ownership by a Customer (new, load-bearing).** PRD.md 2.1 says "a claim, hull or shipment
  belonging to another customer is refused with `ERR_CUSTOMER_SCOPE_VIOLATION`", but a `FinishedUnit`
  carries no `customer_id` (2.8 line 164) and 2.8 line 166 gives `Shipment` no `customer_id` either, so
  a PRD-only implementer has no link from a delivered hull to a customer. I dropped the recipe's
  "stranger reads the delivered hull -> 403" probe as not uniquely derivable; the instance is still
  translated through its other seven probes.
- **Scoped LIST filters, it does not refuse.** Grounded on 3.9 line 362 verbatim: "a `Customer` reading
  claims sees only its own" - asserted 200 with `total_count == 0` and an empty page, not 403.
- **`ERR_ROLE_IDENTITY_MISMATCH` precedes `ERR_TECHNICIAN_NOT_CERTIFIED` and
  `ERR_SEGREGATION_OF_DUTIES`.** 2.7 band 1 enumerates exactly six checks ("header presence, role
  validity, endpoint permission, identity resolution, role/identity agreement, customer scope");
  certification and segregation are not among them, so the mismatch wins.
- **Role gate precedes path existence.** `retire_mold(NON_EXISTENT_UUID, ..., planner_headers)` asserts
  403, not 404, per 2.7 ("Existence of every path identifier is checked **next**").
- Carried over: (a) 2.7 puts charge-mass tolerance in band 5 and resin sufficiency in band 7 while 3.5's
  narrative lists the RESERVED-charge check first, so the zero-charge probe uses
  `validate_error_is_one_of([RESIN_INSUFFICIENT, CHARGE_MASS_OUT_OF_TOLERANCE])`; (b) 2.4's blanket
  version rule vs the per-edge enumerations - the per-edge sentences govern, so the order bumps only at
  inspect/scrap, not at oven start/demould; (c) `unit_cost_cents` asserted `is None` (3.3 step five)
  rather than 0 (2.8 default), because the read follows a recompute; (d) the third idle-sweep step
  asserts only `released_resin_charge_count == 0` and `aborted_molding_cycle_count == 0` plus the order's
  unchanged version/status, since an already-EXPIRED lot still satisfies "strictly before".

## Validation (no server started, no tests run)
- `python3 -m py_compile` on all four files: COMPILED, no output.
- AST check per file: UNUSED [] / UNDEFINED [] / NOT_EXPORTED [].
- `--collect-only -q` on `test_c_statemachines_and_rbac*.py` -> 23 tests collected in 0.22s, 0 errors.
- No occurrence of "scaffold", "S", or any design-table label in the generated code; each of the 23
  docstrings ends with its verbatim `Design:` line.

### Orchestrator verification of P4 (independent, not taken on trust)
- `--collect-only -q` re-run by me: **23 tests collected in 0.20s** — matches.
- Emitted `Design:` lines: 23 total, 23 unique — one test per instance, no duplicates, no extras.
- Line counts on disk match the reported table exactly (965/1355/497/341).
- `test_helpers/` mtimes all <= 05:48 and `conftest.py` still 05:48:20 — nothing central was mutated.

## Step 5 Stage 2 — Partition P7 (corner: errors + cross_cutting + consistency) — 2026-09-04T06:22:00.000Z

Subagent report, verbatim:

File 04 and 05 are written; the P7 partition is complete. Final report:

## Files written (all under `test_suite/`)

| file | lines | tests |
|---|---|---|
| `test_c_errors_and_consistency_01_request_validation_ladder.py` | 450 | 6 |
| `test_c_errors_and_consistency_02_state_conflicts.py` | 738 | 6 |
| `test_c_errors_and_consistency_03_ladders_and_capacity.py` | 705 | 5 |
| `test_c_errors_and_consistency_04_cross_cutting_layers.py` | 419 | 4 |
| `test_c_errors_and_consistency_05_concurrency_and_visibility.py` | 623 | 6 |
| **total** | **2935** | **27** |

No other path in `test_suite/` was touched; `conftest.py` and everything under `test_helpers/` are unmodified.

## Validation (exact)
- `python3 -m py_compile` on each of the five files: all OK (no output, exit 0).
- `--collect-only -q` on `test_c_errors_and_consistency*.py` -> **27 tests collected in 0.26s**, zero
  collection errors.
- Mechanical audit: every one of the 25 manifest `Design:` lines appears verbatim in the emitted code
  (two instances carry two tests each); no occurrence of "scaffold", "S1.x" or any table label.

## Instances translated (all 25 - none skipped wholesale)
**errors (15):** auth ladder; technician state; 404 family; 422 schema ladder (2 tests); duplicate-code
family; no-op family; parallel-axis family; shipment family; cycle-create ladder; cycle lifecycle +
cooling floor; mold lifecycle; warranty intake/storage axis; 412-after-state; capacity family (2 tests);
size-class family.

**cross_cutting_complexity_layers (4):** OCC parents (all five parents audited; the deliberate
`AssemblyTechnician` `release-storage` asserts 403 `ERR_ROLE_NOT_PERMITTED`, warehouse version unchanged
across it, hull still `STORED`); suspension cascade; demold fan-out; dual-variant oven window.

**consistency_model (6):** one test each, cycle/charge/store/line/approve OCC plus the storage-release
cascade read-back. Every 412 and every accepted retry additionally runs the partition-local
`_p7_assert_no_concurrency_handles`, which asserts no `Retry-After`/`ETag`/lock header and no body key
containing token, cursor, retry, lock, lease, etag or nonce.

## Probes dropped inside otherwise-translated instances (PRD filter failures)
1. **`ERR_SIZE_CLASS_NOT_SUPPORTED` - structurally unreachable.** 3.4's candidate pool already drops tools
   whose size-class rank exceeds the station's, so the empty-pool fallback `ERR_NO_ELIGIBLE_MOLD` owns the
   refusal. Probe removed from the cycle-create ladder.
2. **`ERR_CUSTOMER_NOT_ACTIVE` at claim intake** (suspension-layer and warranty-intake instances): 3.9
   "Opening a claim" declares no ACTIVE-customer precondition (it is declared only at start-review and
   approve). Coverage fails. Consequence: the design's two intakes reusing claim code `CLM-CD-L2` are not
   uniquely derivable, so the suspended-intake attempt was dropped and a single post-reinstatement intake
   with that code is asserted instead.
3. **`ERR_UNIT_NOT_DELIVERED` at intake** - same coverage gap; the approval-time rung was not probed
   because it would need a claim whose `months_in_service` derives from a null `delivered_at` (undefined).
4. `scheduled_qty` on ProductionOrder - not declared by 2.8, dropped.
5. `months_in_service` at creation - PRD self-contradicts (2.8 "default 0" vs 3.9 "null"); only the
   post-start-review value 0 is asserted.

## PRD-vs-design deviations asserted in favour of the PRD (report these upstream)
- `arm_index` above `arm_count`: PRD 2.8 explicitly names `ERR_VALIDATION`; the design asserts
  `ERR_INVALID_QUANTITY`. Files 03 and 04 assert `ERR_VALIDATION`.
- Out-of-range pagination `limit`: 2.3 says `ERR_VALIDATION`, design says `ERR_INVALID_QUANTITY` ->
  `ERR_VALIDATION`.
- 2.7 band 3 orders numeric bounds before enum membership, contradicting the design's ladder -> split into
  single-defect probes.
- 3.8 attaches `ERR_FREIGHT_QUOTE_MISSING` to both halves of the depart precondition and names
  `ERR_SHIPMENT_INVALID_STATE`/`ERR_SHIPMENT_EMPTY` in one sealing sentence -> `validate_error_is_one_of`
  in both places. Note this makes `ERR_FREIGHT_QUOTE_MISSING` reachable-by-reading, contrary to the
  directive's unreachable list.
- Manual abort reason: design used `MOLD_SERVICE_DUE`, 3.5 CASCADE-A sets `OPERATOR_ABORT` ->
  `OPERATOR_ABORT`.
- Suspension-cascade customer version: the design's literal `== 2` assumes the acknowledgement wrote
  nothing; the test captures the pre-suspend version and asserts exactly +1.
- `ERR_UNIT_INVALID_LOGISTICS_STATE` and `ERR_MOLD_SIZE_CLASS_MISMATCH` were checked and are **reachable**
  (3.7/3.8 and 2.8/3.1 respectively) - both asserted.

## test_helpers gaps worked around locally
- No assertion exists for "no token/cursor/retry-after/lock handle" -> partition-local
  `_p7_assert_no_concurrency_handles` at the top of file 05 (nothing under `test_helpers/` was edited).
- `shipment_payload` carries no `customer_id`, so 3.8's "booked ... against one `customer_id`" and its
  booking-time `ERR_CUSTOMER_NOT_ACTIVE` precondition are not exercisable through the shared factory.
- `list_finished_units` boolean filters: `requests` serialises Python `True` as `"True"`, so the anchor
  filter passes the string `"true"` to stay parser-agnostic.

### Orchestrator verification of P7 (independent)
- `--collect-only -q` re-run by me: **27 tests collected in 0.22s** — matches.
- Emitted `Design:` lines: 27 total, **25 unique** — consistent with the reported "two instances carry two
  tests each". No extras.
- Line counts on disk match the reported table exactly (450/738/705/419/623).
- `test_helpers/` untouched; `conftest.py` still 05:48:20.

### (C) Orchestrator adjudication of the `shipment_payload` / `customer_id` gap — NO central fix
Raised independently by BOTH P4 (gap 2) and P7, so I checked it directly rather than trusting either.
  - PRD 2.8 line 166 is the authoritative field enumeration for `Shipment` and does NOT list `customer_id`
    at all — neither client-supplied nor derived.
  - PRD 3.8 line 336 nevertheless says "A `Shipment` is a trailer booked by a `LogisticsPlanner` against
    one `customer_id` ... Creation requires the customer to be `ACTIVE` (`ERR_CUSTOMER_NOT_ACTIVE`)".
  - The implementation (r_ship.py:31) resolved the contradiction exactly as it did for the technician-id
    fields: `"customer_id": {"type": "string", "required": False}`. When supplied it is resolved
    (r_ship.py:79-80) and ACTIVE-checked (r_ship.py:83-86, priority 60); when omitted, `holder["customer"]`
    is None and `customer_active()` short-circuits.
  Therefore the factory's omission is SAFE — no intake failure, no fixture-tier wipeout, and P4's dropped
  "stranger reads the delivered hull -> 403" probe was correctly dropped (there is genuinely no
  customer link on `FinishedUnit`, and none on `Shipment` unless the optional field is passed).
  `factories.py` deliberately NOT changed.
  -> Carried to Step 8/9 as the SAME class of PRD defect as (A): 2.8's field enumerations and 3.x's
     narrative disagree about which identifiers are client-supplied. Three instances now:
     `created_by_technician_id`, `operator_technician_id`, `Shipment.customer_id`.
     Also carried: 2.8 "months_in_service default 0" vs 3.9 "months_in_service null" at claim creation.

## Step 5 Stage 2 — Partition P5 (corner: calculations) — 2026-09-04T06:31:00.000Z

Subagent report, verbatim:

Stage 2 partition **P5 (Corner / calculations, 20 instances)** is complete.

## Files written (all under `test_suite/`)

| File | Lines | Tests |
|---|---|---|
| `test_c_calculations_01_resin_charge_rollups.py` | 205 | 3 |
| `test_c_calculations_02_production_order_cost.py` | 361 | 3 |
| `test_c_calculations_03_warpage_and_verdict.py` | 428 | 3 |
| `test_c_calculations_04_cycle_windows_and_mold_service.py` | 294 | 2 |
| `test_c_calculations_05_resin_qualification_and_build_ahead.py` | 453 | 3 |
| `test_c_calculations_06_footprint_posture_and_hull_serials.py` | 305 | 2 |
| `test_c_calculations_07_warranty_payout.py` | 394 | 2 |
| `test_c_calculations_08_shipment_freight.py` | 359 | 2 |
| **total** | **2799** | **20** |

No file outside `test_suite/test_c_calculations*.py` was created or touched; `conftest.py` and everything
under `test_helpers/` were left untouched.

## Instances TRANSLATED (20 of 20 - every instance produced at least one test)
melt-index divide-then-round; released-charge filtering; regrind HALF_UP; cost-summary input filtering;
unit-cost floor reconciliation; overhead tier boundaries; warpage constant lookups; warpage
round-then-weight-then-clamp; verdict threshold ladder; mould service counter + reset; butt-jointed
cooling window + floored minutes; qualified-lot inclusive bounds; build-ahead cap floor + reversal;
build-ahead window boundary before quota; store-freezes-site then release restores; hull serial build_seq
across an abort; warranty pro-rata coverage + top fee rate; flat-schedule band boundary; freight per-line
rounding before sum; freight utilisation discount tier straddle.

## Instances SKIPPED
None wholesale. Nine individual **assertions** inside otherwise-translated instances failed the
unique-derivability filter and were dropped (all COMPUTED-FIELD SILENCE unless noted):

1. store-freezes-site - `zones[].stored_unit_count`, `zones[].anchor_product_model_ids`,
   `blocked_production_order_count`. The only PRD sentence (line 426 / 3.7's closing paragraph) says merely
   "the per-zone breakdown of `zone_code`, `capacity_cube_m3`, committed cube, remaining cube and anchor
   occupancy" - the three JSON key names exist only in SCAFFOLD.yaml.
2. hull serials - (a) `cavity_index` as a *response* field: the PRD names it only as a formula loop
   variable inside the serial recipe (3.5 line 286), so the test derives sibling pairing from the serial
   text instead. (b) the design's "order the four rows by `created_at` ASC yields 0001..0004": siblings
   minted in a single request may legitimately share one `created_at` and the PRD never requires distinct
   stamps. Ordering of `GET /finished-units` is likewise unpinned, so `_p5_serials` compares a **sorted**
   sequence.
3. flat-schedule band - `coverage_pct` as a claim field. `grep coverage_pct PRD.md` returns **zero** hits.
   The band choice is asserted through the gross instead (144000 vs 90000).
4. Both freight instances - `quoted_pre_discount_cents`, `billed_pre_discount_cents`, `discount_rate_pct`,
   `lines[].chargeable_kg_nested`, `lines[].chargeable_kg_gross`, `loaded_line_count`, and the pre-seal
   projection totals: all **zero** grep hits. Consequence: **`assert_freight_summary_consistent` is never
   called** (it reads `loaded_line_count`), and the per-line-rounding claim is proved through
   `quoted_freight_cents` instead - 14398 for per-line rounding vs 14397 for sum-then-round, and 14399 for
   fuel-before-discount, so all three orderings stay distinguishable.
5. per-line rounding - exact `ShipmentLine.line_freight_cents` literals. The PRD gives the row one
   `line_freight_cents` column but never says which variant it holds at which lifecycle point. Asserted
   `line_gross_cube_m3` / `line_nested_cube_m3` / `nest_position` instead, which carry the 0.6173 HALF_UP
   claim directly.

## test_helpers gaps / local workarounds
- `assert_decimal_equals` quantises **both** sides, so it cannot detect an over-scaled stored value. Every
  file defines a local `_p5_exact` = `assert_at_most_scale` + exact `dec` compare. Convenience, **not** a
  helper bug.
- No fixture builds a single-cavity plant, a two-lot plant, or drives an already-charged cycle on explicit
  stamps. Fourteen partition-local `_p5_*` helpers cover it. **No genuine bug found in test_helpers/.**

## PRD numeric / semantic ambiguities hit (for Steps 8/9)
1. **`unit_cost_cents` when `completed_qty` is 0.** 3.3 "null otherwise" vs 2.8's money catalogue "all
   integers defaulting to 0". Resolved with `_p5_unit_cost_absent(v) = v is None or v == 0`.
2. **`min_wall_thickness_mm` scale.** 3.6 implies 3 dp, 2.8 declares 2 dp. Asserted the *value* only.
3. **`actual_cooling_minutes` after a rejected demould.** Design says null; 2.8 gives default 0. Asserted
   **0** (PRD.md is the contract).
4. **`months_in_service` initial value.** 2.8 "default 0" vs 3.9 "starts null". Never asserted pre-review.
5. **`ShipmentLine.line_freight_cents` basis/timing** is unpinned.
6. **`BLEND_CORRECTION`** is used by the design as a `released_reason` but is not a member of the PRD's
   `released_reason` enum. Not asserted.
7. Design-vs-PRD status disagreements (harmless): build-ahead errors 422 in design, 409 in PRD line 565.
8. **Design bug** in store-freezes-site: the design asserts the sibling store fails `ERR_NO_ELIGIBLE_ZONE`,
   but 3.7 line 318 evaluates the FROZEN gate **first** and the site is at 100.00 % = FROZEN. The test
   asserts `ApiErrorId.WAREHOUSE_FROZEN`; the design literal is wrong.
9. **Warranty clock-ordering hazard.** The design delivers at 2026-08-01T12:00:00Z but the fixture ladder's
   `DEFAULT_DEPART_AT` is 2026-08-01T15:00:00Z and the PRD forbids rolling the clock back past a recorded
   actual stamp. Resolved by keeping `delivered_at` at the fixture default 2026-08-02T00:00:00Z and
   shifting only the review clocks - every payout literal depends solely on `months_in_service`, so the
   design's numbers are preserved exactly.

## Static validation (exact results)
- `python3 -m py_compile` on each of the 8 files: COMPILE_OK x8.
- `python3 -m pyflakes test_suite/test_c_calculations*.py`: rc=0 (one unused import found and removed).
- `--collect-only -q` -> **20 tests collected in 0.24s**, zero collection errors.
- Tests were **not executed**; no server was started and no `pkill` was run.

### Orchestrator verification of P5 (independent)
- `--collect-only -q` re-run by me: **20 tests collected in 0.23s** — matches.
- Emitted `Design:` lines: 20 total, 20 unique — one per instance, no extras.
- Total lines on disk 2799 — matches the reported table.
- `test_helpers/` mtimes all still <= 05:44 — nothing central was mutated by P5 either.

## Step 5 Stage 2 — Partition P6 (corner: validations) — 2026-09-04T06:50:00.000Z

Subagent report, verbatim:

P6 complete. 16 of 18 instances translated into 16 tests across 4 files; 2 skipped on unique
derivability/coverage.

## 1. Files written (all under `test_suite/`)

| File | Lines | Tests |
|---|---|---|
| `test_c_validations_01_authorization_and_uniqueness.py` | 335 | 4 |
| `test_c_validations_02_precedence_pairs.py` | 519 | 4 |
| `test_c_validations_03_temporal_and_aggregate_bounds.py` | 599 | 4 |
| `test_c_validations_04_conditional_and_cascading_scope.py` | 747 | 4 |

`conftest.py` untouched; nothing under `test_helpers/` modified.

## 2. Instances TRANSLATED (16)
The ordering source for the whole partition is **PRD 2.7**: "Each endpoint evaluates its applicable checks
in a fixed ascending priority order and returns on the first failure it finds; no endpoint reports two
errors, and no later check runs after an earlier one has failed." plus the eight numbered bands (band 8
"**Optimistic concurrency** - the five stale-version guards of section 2.6, last of all"), 2.6's "These
guards are evaluated late ... so a request that is both stale and otherwise invalid reports the other
failure", and the five explicitly named precedence pairs in 2.7.

File 01: empty `X-User-ID` -> `ERR_MISSING_AUTH_HEADERS` leaving no order row; role-not-permitted before
absent path id; role/identity mismatch for a technician of another role; duplicate zone_code within one
site but reusable across sites.
File 02: lot-not-qualified outranks resin-insufficient (2.8's named pair "qualification is checked before
sufficiency"); frozen site outranks build-ahead cap and zone; unit build state outranks a stale warehouse
version; customer suspension voids the claim before the reserve gate.
File 03: oven start exactly at the clock passes / one second earlier refused; acknowledgement at the
delivery instant verifies / one second later does not; trailer rounding up to 60.00 seals while 59.99 is
underutilised; second line at the inclusive cube bound passes and one unit over fails.
File 04: overbuild ceiling binds on the third cycle and an abort hands the quota back; build-ahead window
and cap bind only on bucket-bearing orders; deformation threshold binds only on HULL_DEFORMATION claims;
no-eligible-zone answers even where the site total would have admitted the hull.

## 3. Instances SKIPPED (2)
- **`val_satisfaction_charge_mass_at_the_rounded_tolerance_bound_passes`** - fails **unique derivability**.
  3.5 line 278 gives two supposedly equivalent formulations of the charge-mass tolerance (a
  percentage-deviation form rounded to two decimals, and a scaled absolute-bounds form). At the instance's
  point (26.251 kg against a nominal 25.000 at 5.00%) they diverge: the percentage form computes 5.004% ->
  5.00% and **accepts**; the bounds form computes 26.250 and **rejects**. Two faithful implementers reach
  opposite answers. Retargeting to a non-boundary mass was rejected because it would replace the
  rounding-boundary claim with an ordinary arithmetic-bound claim, i.e. stop testing the instance.
- **`val_cross_entity_claim_requires_the_hull_to_be_delivered`** - fails **coverage**. 3.9's intake
  paragraph enumerates intake's checks and never requires `logistics_status` `DELIVERED`; the PRD attaches
  `ERR_UNIT_NOT_DELIVERED` only to claim approval. 5 is a bare `Error ID | HTTP Status` table with no
  "when" column, and the 4 row text is a table description, not a rule-bearing sentence.

No skip was for ordering silence - this PRD is unusually explicit about precedence, which is why the
ordering instances survived.

## 4. Sub-assertions dropped (instance kept, claim not derivable)
- role-not-permitted-beats-path-id: the design expects `ERR_RESOURCE_NOT_FOUND` but 2.7 band 2 prefers "its
  entity-specific not-found code where one exists" and `ERR_MOLD_NOT_FOUND` exists. Asserted `404` plus
  `validate_error_is_one_of([MOLD_NOT_FOUND, RESOURCE_NOT_FOUND])`.
- role-identity-mismatch: the design claims it outranks `ERR_TECHNICIAN_NOT_CERTIFIED`, but 2.7 places
  certification in **no** band. Removed the second defect so exactly one remains; precedence not asserted.
- lot-not-qualified: the design's melt-index-6.01 sub-case expects `ERR_RESIN_LOT_NOT_QUALIFIED`, but 3.2
  reports an out-of-band melt index "specifically as `ERR_MELT_INDEX_OUT_OF_RANGE`". Substituted a second
  grade-mismatched lot with ample mass.
- frozen-beats-cap: dropped `BLOCKED_WAREHOUSE` / `blocked_production_order_count == 1` (CASCADE-H only
  blocks READY_TO_SCHEDULE/IN_PRODUCTION orders; the fixture order is COMPLETE).
- suspension pair: dropped "intake refuses a suspended customer" - the PRD attaches
  `ERR_CUSTOMER_NOT_ACTIVE` only to start-review, approve and shipment creation.
- overbuild ceiling: dropped the design's self-contradictory mould-status assertions (it claims both that
  the abort returns MLD-2 to AVAILABLE and that MLD-1/MLD-2 read IN_CYCLE while merely SCHEDULED); 3.5
  moves a tool to IN_CYCLE only at start-oven. Kept the `mold_code` ASC re-selection claim.

## 5. test_helpers gaps worked around locally
- **No two-decimal millimetre quantum.** `constants.py` exports Q_MASS/Q_CUBE/Q_PERCENT/Q_WARPAGE/Q_TEMP
  but nothing for `reported_deformation_mm`, which 2.8 declares at two decimals. Defined
  `_P6_Q_MM = Decimal("0.01")` in file 04. Suggest a shared `Q_MM`.
- **No fixture mints a second cycle/order on an existing context.** Added a local
  `_p6_second_cycle_of_hulls(ctx, order, *, oven_start_at, oven_end_at, cooling_end_at)` in file 04.
- **`setup_claim_under_review` start-reviews immediately**, with no hook to move the clock first, so
  `months_in_service` cannot be controlled through it. Files 02/03 use `setup_submitted_claim` + explicit
  `set_clock` + `api.start_claim_review`. A `review_at=` parameter would help.
- **`DEFAULT_DELIVER_AT` = 2026-08-02T00:00:00Z** makes round-year clocks yield 11 complete months, not 12.
- Nothing under `test_helpers/` was edited.

## 6. PRD ambiguities resolved
- Charge-mass tolerance stated two inequivalent ways (3.5 line 278) - cause of skip #1.
- **Storage-guidance acknowledgement stamp**: 2.8 line 150 says `storage_guidance_acknowledged_at` is
  "stamped from the logical clock", while 2.14 line 214 and 4 line 420 say an *explicit* `acknowledged_at`
  instant is stored. Resolved without weakening the test by keeping the clock in step with each
  acknowledgement, so the test holds under either reading.
- `months_in_service` on a new claim: 2.8 "default 0" vs 3.9 "null". Asserted `in (None, 0)`.
- `storage_description`: 2.8 calls it required (10-500 chars), 3.9 calls it optional. Always supplied.
- Error envelope: 2.2 puts the id at `data.error_id`, not `error.error_id`; an earlier draft of file 02 read
  `["error"]["error_id"]` and was fixed.
- Deliberate double-defect requests preserved except the two cases where the PRD does not rank the pair.

## 7. Static validation (exact results)
- `python3 -m py_compile` on each of the four files: all clean.
- AST scan of file 04 for unused imports: `unused: []`.
- All 16 emitted `Design:` tags match the P6 manifest exactly; `comm` shows the only manifest entries
  without a test are the two documented skips, and zero emitted tags outside the manifest.
- `--collect-only -q` -> **16 tests collected in 0.27s**, no errors, no warnings. Tests were not executed;
  no server was started.

### Orchestrator verification of P6 (independent)
- `--collect-only -q` re-run by me: **16 tests collected in 0.20s** — matches.
- Emitted `Design:` lines: 16 total, 16 unique. Line counts on disk match (335/519/599/747 = 2200).
- `comm` of the P6 manifest against the emitted tags leaves exactly the two reported skips and nothing
  else — I reproduced this myself rather than taking the claim on trust.
- `test_helpers/` mtimes all still <= 05:44 — P6 touched nothing central.

## Step 5 COMPLETE — consolidated coverage audit — 2026-09-04T06:52:00.000Z

### Totals (all figures measured by the orchestrator, not reported by subagents)
- Manifest instances across the 7 partitions: 14 + 11 + 25 + 23 + 20 + 18 + 25 = **136**.
- Unique `Design:` instances emitted suite-wide: **134**.
- Instances skipped: **2**, both P6, both documented above with the PRD quote that fails.
  134 + 2 = 136 — the ledger balances exactly, no instance was lost silently.
- Test functions: **236**. `pytest --collect-only -q` reports **237** collected; the difference is the one
  `@pytest.mark.parametrize("limit", [0, 101])` in
  `test_c_entities_and_endpoints_02_collection_pagination_and_filters.py:333`, which yields two collected
  items from one function. I confirmed this by AST-walking every test function: **236 functions, 0
  untagged** — so the skill's "untagged tests are a Stage 2 failure" rule is satisfied.

### Per-instance mandates
- Difficulty (queue A): 25 instances / 72 tests, and `uniq -c | awk '$1 < 2'` returns **empty** — every
  difficulty instance carries the required >= 2 tests.
- Corner (queue B): 109 instances / 164 tests — 111 real corner instances minus the 2 skips, each with
  >= 1 test.

### Files on disk
test_suite/: 30 test modules + conftest.py, 17,224 lines of test code.
test_helpers/: 10 modules, unchanged by all seven partition agents (verified by mtime, all <= 05:48).

### Central fix applied after the fan-out (fix (B), the only one)
`test_helpers/fixtures.py` — the latent silent-drop bug P3 found. Two loud guards added:
  1. `setup_scheduled_cycle` (root cause): raises `TypeError` when an explicit `baseline=` arrives together
     with any `create_plant_baseline` kwarg, instead of short-circuiting at
     `dict(baseline or create_plant_baseline(**baseline_kwargs))` and discarding them.
  2. `setup_warehouse_at_posture`: raises `TypeError` on `baseline=` with a posture-specific message,
     because it injects `warehouse_overrides` itself and would otherwise hand back a NORMAL site.
Before applying it I AST-scanned all 30 modules for calls passing BOTH `baseline=` and a baseline kwarg:
**0 hits**, so the bug was latent, never live — no landed test was silently misconfigured, and no test
needed rewriting. The guards exist so the Step 7 fix loop cannot introduce the silent form while editing.
Verified: `py_compile` clean, both guards raise on a synthetic call, suite still collects 237.

### Deliberately NOT fixed (with reasons, all three adjudicated above)
- (A) technician-id fields in `factories.py` — impl accepts both readings; changing it would touch every
  test for no behavioural gain.
- (C) `shipment_payload` missing `customer_id` — impl has it `required: False`; omission is safe.
- P5's `_p5_exact` / P6's `_P6_Q_MM` / P4's partial-header builders / P7's
  `_p7_assert_no_concurrency_handles` — partition-local conveniences, not defects. Left in place rather
  than centralised, because a late refactor of `test_helpers/` would risk all 236 tests to buy tidiness.

### Hygiene checks
- No test directory landed under `workspace/` (contents are exactly INSTRUCTION.md, PRD.md,
  implementation/, step5_manifests/) — the failure mode recorded in project memory did not occur here.
- No subagent started a server or ran `pkill`; all seven validated statically only, as instructed, so no
  other pipeline on this 32-pipeline host was disturbed.

NEXT: Step 7. The 8-round sweep MUST be launched under `setsid nohup bash -c '... & done; wait'` with
per-round `results.$i.json`, and diagnosis must read only the per-round results files, never sweep.log.

### Correction to the "Files on disk" figures in the Step 5 close-out above
The worklog is append-only, so the wrong figures stay visible; these measured ones supersede them.
  test_suite/: **39** test modules (not 30) plus conftest.py, **20,829** lines total (not 17,224).
  test_helpers/: 10 modules, **4,669** lines.
The instance/test ledger in that entry (136 = 134 + 2, 236 functions, 237 collected, 25 difficulty
instances all >= 2 tests, 109 corner instances) was measured directly and is unaffected.

## Step 7: Run tests and iterate to green — 2026-09-04T07:40:00.000Z

Subagent report, verbatim:

All 8 rounds green. Final sweep: **237/237 passed in every one of the 8 rounds, 0 failures, 0 skips.**

## Iteration log

| Iter | Rounds | Result | Failures (union across 8 rounds) |
|---|---|---|---|
| 1 | 8/8 completed | 207/237 each | 30, identical set in all 8 rounds |
| 2 | 8/8 completed | 235/237 each | 2, identical set in all 8 rounds |
| 3 | 8/8 completed | **237/237 each** | **0** |

**Flakiness: none, in any iteration.** Every round of every iteration produced a byte-identical failure
set, so no failure was attributable to host load and no sweep was re-run for contention. No round showed
the mass-SIGTERM signature (`Terminated` in a server log / simultaneous death); `setsid` held.

## Tests DELETED (assertions removed under STEP 1a/1b)

1. **`test_c_errors_and_consistency_04_cross_cutting_layers.py` —
   `TestCascadeFanOut::test_one_demold_call_lands_every_consequence_it_declares`**, the single assertion
   `order_after["version"] == order_version_before + 1` (plus its now-dead `order_version_before` binding).
   **Filter failed: 1a (and 1b).** PRD is silent on whether the cost roll-up alone advances the order's
   version at demould. 3.5 enumerates the rows a demould revises — "The cycle's and the tool's `version`
   each advance by 1" — and the order is not among them; 3.3's "Every one of these edges advances the
   order's `version` by 1" governs the twelve *status* edges, and at demould the order's status does not
   move; 3.3's roll-up sentence ("**Order cost** is recomputed at oven start (when charges become
   consumed), at demould, and on every inspection that changes `completed_qty`.") attaches no version
   claim. Two admissible implementations exist (2.4's "every persisted mutation" -> bump; 3.5's
   enumeration -> no bump). Kept the covered assertions (`status == IN_PRODUCTION`, `completed_qty == 0`).
   This test contradicted four sibling tests that assert the opposite; the four are backed by 3.5's
   enumeration, this one by nothing.

2. **`test_c_errors_and_consistency_03_ladders_and_capacity.py:682` — `TestSizeClassFailsInTwoPlaces`**,
   exact-error assertion relaxed to
   `validate_error_is_one_of([NO_ELIGIBLE_MOLD, SIZE_CLASS_NOT_SUPPORTED])`. **Filter failed: 1b (ERROR
   PRECEDENCE SILENCE).** PRD 3.4 names two codes for one condition and never reconciles them: "The
   selected tool's `size_class` must fit the station ... otherwise `ERR_SIZE_CLASS_NOT_SUPPORTED` (HTTP
   422)" and places that rung *above* the mould pool, while the pool sentence folds the same predicate into
   eligibility — "whose `size_class` rank is at most the station's `max_size_class` rank" — whose empty
   pool "fails with `ERR_NO_ELIGIBLE_MOLD` (HTTP 409)". Circular: the "selected" tool cannot be known
   before selection.

3. **`test_c_statemachines_and_rbac_02_axes_and_cascades.py` —
   `test_returning_a_claim_to_the_queue_revokes_the_waiver_and_re_ages_the_hull`**, exact-error assertion
   relaxed to `validate_error_is_one_of([STORAGE_FINDING_NOT_WAIVABLE, CLAIM_INVALID_STATE])`. **Filter
   failed: 1b (ERROR PRECEDENCE SILENCE).** The re-queued claim breaks both waive preconditions at once and
   PRD 3.9 does not order them: "The axis must read `GUIDANCE_VIOLATED`, otherwise
   `ERR_STORAGE_FINDING_NOT_WAIVABLE` (HTTP 409), and the claim must be `UNDER_REVIEW`." — the
   adjudication rung gets neither a code of its own nor a position.

No whole test module or function was deleted; no assertion was weakened to make a wrong implementation
pass; nothing was marked skip/xfail. Net test count unchanged: 236 functions / 237 collected.

## `test_helpers/` fixes

- **`fixtures.py::create_production_order`** — `product_model_id` and `target_warehouse_id` are now
  `overrides.pop(...)`ed instead of being passed positionally, which was raising `TypeError:
  production_order_payload() got multiple values for argument 'target_warehouse_id'` for any caller aiming
  an order at a non-context site (5 tests). PRD 2.8 ProductionOrder: "`target_warehouse_id` (required, must
  resolve or `ERR_WAREHOUSE_NOT_FOUND`)" and "`product_model_id` (required, must resolve or
  `ERR_PRODUCT_MODEL_NOT_FOUND`)" — both are client-supplied required fields, so a caller must be able to
  override them.

## `test_suite/` fixes (test bugs under STEP 2 — request/precondition inconsistent with PRD)

- **16 sites across 6 files** (`test_c_validations_03`, `test_c_validations_04`,
  `test_c_statemachines_and_rbac_03`, `test_c_statemachines_and_rbac_04`,
  `test_c_errors_and_consistency_01`, `test_c_errors_and_consistency_03`): bare `==` on instants -> the
  suite's own `assert_instant_equals`. PRD 2.4 mandates server timestamps "with three fractional digits",
  so the same instant legitimately renders `.000Z`; the PRD is silent on the byte rendering of
  echoed/derived instants, and ~12 already-passing tests used `assert_instant_equals` for exactly this.
  (9 tests)
- **`test_c_errors_and_consistency_05_concurrency_and_visibility.py:53-72`**: the partition-local
  coordination-handle scanner now matches whole snake_case segments (`re.split(r"[^a-z0-9]+", ...)`) instead
  of substrings, which was reading the "lease" inside `released_reason` as a lock handle. PRD 2.8 declares
  `released_reason` on ResinCharge verbatim.
- **`test_c_errors_and_consistency_03_ladders_and_capacity.py`** (2 sites):
  `release_charge_payload("operator re-weighed the drop"/"releasing it twice")` -> `"ORDER_CANCELLED"`.
  PRD 3.2 "The optional `release_reason` supplies `released_reason`" plus 2.8's enumeration of
  `released_reason` means the reason must be an enum member, not free text.
- **`test_c_errors_and_consistency_02_state_conflicts.py:109`** and
  **`test_c_statemachines_and_rbac_01_cycle_machine.py:759,766,796`**: `planner_headers` -> `admin_headers`
  on `suspend_customer`/`reinstate_customer`. PRD 4: "POST `/customers/{customer_id}/suspend` ...
  PlantAdmin" and "POST `/customers/{customer_id}/reinstate` ... PlantAdmin".
- **`test_c_calculations_08_shipment_freight.py`**: registered the freshly scheduled cycle in the context
  (`ctx["molding_cycle"]`, `ctx["molding_cycle_id"]`) before calling `run_cycle_to_demold`, which requires
  them — was `KeyError: 'molding_cycle'`. Matches the convention already used in 4 other partitions.
- **`test_c_validations_02_precedence_pairs.py`**: the "qualified but short on mass" lot went from
  `received_kg=5.0` to `15.0` (and its expected untouched balance likewise). PRD 3.2 folds a mass floor
  into qualification itself — "the lot's `available_kg` is at least the model's minimum shot mass, computed
  as `nominal_charge_kg` multiplied by one minus `charge_tolerance_pct` divided by 100" = 12.0 x 0.95 =
  11.400 kg — so a 5 kg lot is *unqualified* and can never reach the band-7 sufficiency rung the test was
  probing.
- **`test_d_precision_and_resource_03_cross_entity.py`**: the pre-quarantine lot version baseline is now
  re-read with `read_version` instead of taken from the fixture's creation-time row. PRD 3.2 on charge
  create: "both the lot's and the cycle's `version` advance by 1", so the captured row was a revision
  behind.

## `implementation/` fixes — file:line, change, governing PRD sentence

*(this is the list for Step 8's <step_7_diff>)*

1. **`workspace/implementation/r_cycles.py:267-279`** (call sites `:390` start-oven, `:468` demould, `:486`
   abort) — deleted the `_cost_snapshot` guard and the `touch(order)` inside `recost()`; the cost roll-up is
   now recomputed without advancing the order's `version`. The separate `READY_TO_SCHEDULE ->
   IN_PRODUCTION` bump at `:387-389` is untouched. **PRD 3.5**: at oven start and at demould "The cycle's
   and the tool's `version` each advance by 1", and on an abort "the cycle's `version` advances by 1" — the
   order is not named on any of the three; **PRD 3.3** attaches "Every one of these edges advances the
   order's `version` by 1" to the twelve status edges only. Fixed 4 tests.

2. **`workspace/implementation/errors.py:93`** — added `"ERR_STALE_SHIPMENT_VERSION": 412` to
   `ERROR_STATUS`; the code was raised by `r_ship.py:401` but absent from the map, so `ApiError` fell
   through to its `400` default. **PRD 5** catalogue row: `| ERR_STALE_SHIPMENT_VERSION | 412 |`, and
   **PRD 3.8**: "It requires `expected_shipment_version`; a mismatch is `ERR_STALE_SHIPMENT_VERSION` (HTTP
   412)". A full diff of 5's 90 catalogue rows against the map now shows zero missing, zero mismatched,
   zero extra. Fixed 1 test.

3. **`workspace/implementation/r_warranty.py:60-68`** (`create_claim`'s `resolve`) — dropped the
   `"ERR_RESOURCE_NOT_FOUND"` override on both `rt.find` calls so each body foreign key reports its
   entity-specific 404. **PRD 2.8 WarrantyClaim**: "`finished_unit_id` (required, must resolve or
   `ERR_FINISHED_UNIT_NOT_FOUND`); `customer_id` (required, must resolve or `ERR_CUSTOMER_NOT_FOUND` ...)",
   and **2.7**: existence failures are "reported with its entity-specific not-found code where one exists
   and with `ERR_RESOURCE_NOT_FOUND` otherwise". Fixed 1 test.

4. **`workspace/implementation/r_resin.py:116` and `:142`** (`quarantine_lot`) — capture
   `base_version = lot["version"]` before CASCADE-F and force `lot["version"] = base_version + 1` after
   link 4, so the status move (link 1) and the mass returned by every released charge (link 2, via
   `svc.lot_return`'s own `touch`) count as one revision rather than 1+N. **PRD 3.2**: CASCADE-F's links
   1-4 are enumerated and the paragraph closes "The lot's `version` advances by 1." Fixed 1 test.

5. **`workspace/implementation/r_orders.py:119-129`** (`release_order`'s `tooling` check) — the tooling gate
   now returns early when the target site's `posture` is `FROZEN`, so the frozen-site outcome is decided
   before the mould gate is consulted. Previously an order that was both frozen-out *and* tool-less
   answered `ERR_NO_ELIGIBLE_MOLD`. **PRD 3.3**: "Five preconditions are evaluated: the order is `DRAFT`;
   `ordered_qty` is at least 1; the target site's `posture` is not `FROZEN`, otherwise
   `ERR_WAREHOUSE_FROZEN` (HTTP 409); at least one mould exists for the order's hull model in `status`
   `AVAILABLE`, `IN_CYCLE` or `MAINTENANCE`, otherwise `ERR_NO_ELIGIBLE_MOLD` (HTTP 409); and at least one
   resin lot qualifies ...". Fixed 1 test.

No endpoint, response field, side effect, header or capability was added; no entity data is seeded at
startup; storage remains in-memory only. The `baseline=`-vs-kwargs `TypeError` guard in
`test_helpers/fixtures.py` was left in place. None of the five already-adjudicated PRD defects was
re-litigated, and the previously SKIPPED charge-mass-tolerance Corner instance stays skipped.

## Final counts

- **237/237 tests passing in all 8 rounds** (236 test functions, 39 test modules + conftest; 0 pytest skips)
- Tests deleted: **0 whole tests**; **3 individual assertions** removed or relaxed under STEP 1a/1b (1
  removed outright, 2 relaxed to `validate_error_is_one_of` where the PRD names both codes)
- `test_helpers/` fixes: **1**
- `test_suite/` fixes (STEP 2 test bugs): **23 sites across 11 files**, covering 18 tests
- `implementation/` fixes: **5** (in `r_cycles.py`, `errors.py`, `r_warranty.py`, `r_resin.py`,
  `r_orders.py`)
- Net test count change: **0**

### Orchestrator verification of Step 7 (independent — project memory warns a Step 7 agent can claim a
### clean sweep while leaving no artifacts behind, so I checked the artifacts, not the claim)
- All 8 `workspace/implementation/results.$i.json` exist, are ~81.8 KB each, and are stamped 09-04 07:38.
- Parsed each file myself: every one reports `passed 237, failed 0, total 237, skipped 0`. Genuinely green.
- `grep` for `xfail`, `pytest.skip`, `@pytest.mark.skip` across `test_suite/`: **no matches** — nothing was
  neutralised to manufacture a pass.
- AST re-walk: **236 test functions, 0 untagged**; unique `Design:` instances still **134**, unchanged from
  the Step 5 close-out — so no design instance lost its coverage during the fix loop.
- Exactly the five claimed implementation files have post-07:00 mtimes (`errors.py` 07:10, `r_cycles.py`
  07:06, `r_orders.py` 07:29, `r_resin.py` 07:17, `r_warranty.py` 07:12) and no others — the fix set
  matches the report.

Step 7 had 5 implementation fixes, so Step 8 MUST run (it is skipped only on 0 implementation fixes).

## Step 8: Finalize PRD — align documentation to implementation — 2026-09-04T07:50:00.000Z

Subagent report, verbatim:

Done. `PRD_FINALIZED.md` written and verified non-identical to `PRD.md`.

## Line counts
- `PRD.md`: 582 lines; `PRD_FINALIZED.md`: 582 lines — **0.0% line delta** (all five edits are in-paragraph
  revisions/insertions on existing lines 95, 244, 252, 264, 368). Byte delta: first divergence at line 95.
  Ends at a real boundary (last row of the 5 error catalogue table).

## Changes
- **2.4 (line 95) - insert** - pinned that *every* emitted instant, not just `created_at`/`updated_at`,
  renders as `YYYY-MM-DDTHH:MM:SS.sssZ` (three fractional digits, literal `Z`), so a client-supplied
  `...:00Z` echoes back as `...:00.000Z`; dates as `YYYY-MM-DD` - `serial.py:17-19`, `core.py:137-140`,
  `r_clock.py:41-42`.
- **2.4 (line 95) - insert** - added a deference clause so 2.4's universal "increments on every persisted
  mutation" yields to section-3 statements that a multi-link cascade advances one row by exactly 1, or that
  a roll-up recompute alone advances nothing - `r_resin.py:116,142`, `r_cycles.py:267-279`.
- **3.3 (line 244) - revise** - release evaluates the warehouse test before the **mould** test as well as
  before the resin test; a frozen-out *and* tool-less order lands in `BLOCKED_WAREHOUSE` with HTTP 200
  instead of `ERR_NO_ELIGIBLE_MOLD` - `r_orders.py:119-135`.
- **3.3 (line 252) - revise/insert** - added "on an abort" to the roll-up trigger list, and pinned that the
  cost recompute is not itself version-advancing on the order: at oven start/demould/abort the order's
  `version` moves only if that same request also moves the order's `status`; inspection and scrap bump
  unconditionally - `r_cycles.py:267-279,387-390,468,486`, `r_units.py:49-56`.
- **3.4 (line 264) - revise** - the size-class rung reads the **order's hull model's** `size_class` (not
  "the selected tool's"), needs no selection, and sits above the mould pool, so
  `ERR_SIZE_CLASS_NOT_SUPPORTED` wins over `ERR_NO_ELIGIBLE_MOLD` - `r_cycles.py:98-103,157-173`,
  `calc.py:386`.
- **3.9 (line 368) - revise** - waive-storage-finding checks `claim_status == UNDER_REVIEW`
  (`ERR_CLAIM_INVALID_STATE`) **first**, then the axis (`ERR_STORAGE_FINDING_NOT_WAIVABLE`); a re-queued
  claim reports the former - `r_warranty.py:179-188,274-282`.

## Per-edit pre-edit search log
1. **Instant rendering.** (a) Byte form of every instant/date the API emits. (b) `grep "iso(\|date_str("`
   across all modules -> only `serial.py:_value`, `r_clock._payload`, `core._meta`/`now_iso`; `core.iso`
   (`%03dZ`), `core.date_str`, `core.parse_ts` (accepts offsets, normalises). No raw timestamp strings in
   the computed reads (`cost-summary`, `footprint-summary`, `freight-summary`). (c) Phrased as "every other
   instant the service emits ... regardless of how many fractional digits the client supplied" rather than
   naming specific fields, so no field list can go stale.
2. **2.4 version deference clause.** (a) The universal per-mutation `version` claim. (b) `grep "touch("`
   callers; `svc.recompute_warehouse(bump=)` (bump=False never used), `svc.recompute_bucket`,
   `r_resin.quarantine_lot:116/142` (forced `base+1`), `r_cycles.recost`. (c) Written as a deference clause
   ("that specific statement governs") instead of an enumerated exception list, so it cannot contradict a
   3 rule I did not read.
3. **Release ordering.** (a) Precondition order on `POST /production-orders/{id}/release` and who may
   report `ERR_NO_ELIGIBLE_MOLD`. (b) `r_orders.release` (`state`@34, `tooling`@70 with the FROZEN early
   return, soft-outcome branch :139-152); `grep ERR_NO_ELIGIBLE_MOLD` -> also `calc.select_mold:399` (cycle
   creation) and `errors.py:79`. (c) Scoped the sentence to the release path only, so 3.4's cycle-creation
   use of `ERR_NO_ELIGIBLE_MOLD` is untouched.
4. **Cost roll-up vs order version.** (a) Does recomputing order cost advance `ProductionOrder.version`.
   (b) `grep "apply_cost\|recost\|touch(order)"` -> `r_cycles.py:211` (cycle create, unconditional),
   `:387-389` (only on `READY_TO_SCHEDULE->IN_PRODUCTION`), `:390/:468/:486` (`recost`, no touch),
   `r_orders.py:154-155` (release), `:186` (cancel), `r_units.py:49-56` `_settle_order` (unconditional,
   called only from inspect :266 and scrap :293), `svc.sweep_unblock_resin/sweep_block_resin/posture_cascade`
   (status edges); confirmed `svc.mint_units` never touches the order and `svc.recompute_completion` leaves
   the bump to its caller. (c) Softened from "no bump at demould/abort" to "advances only when that same
   request also moves the order's `status`" - an abort or demould whose CASCADE sweep moves this order out
   of `BLOCKED_RESIN` *does* bump it, and inspection/scrap bump even when figures are unchanged.
5. **Size-class rung.** (a) Which row's `size_class` the rung reads, and its rank against the mould pool.
   (b) `r_cycles.size_class_supported:98-103` (reads `holder["model"]`, priority 59) vs `pick_mold` (70);
   `calc.select_mold:386` pool filter; `r_models.py:184-187` (`ERR_MOLD_SIZE_CLASS_MISMATCH` enforces
   tool==model); no `PATCH /molds` and `size_class` immutable on models, so the shared-class premise holds
   permanently. (c) Qualified to "once the earlier rungs have passed" so the claim is not falsified by the
   auth/existence/station-down/order-not-schedulable rungs above it.
6. **Waive precondition order.** (a) Rung order between `claim_status` and `storage_review_status` on waive.
   (b) `r_warranty._claim_action:179-188` (`claim_state`@43, shared by start-review/storage-review/waive/
   approve/deny/return-to-queue/void), `waivable`@47, `storage_review.not_decided`@46,
   `approve.storage_permissive`, `r_warranty.py:433` (withdraw's own state check). Confirmed 3.9's
   storage-review and approve sentences already state the same order. (c) Added the concrete
   re-queued-claim consequence but left deny's sentence alone - its rung order is not traced to a Step 7
   item.

### Orchestrator verification of Step 8 (independent)
- `PRD_FINALIZED.md` exists: 582 lines, 149,523 bytes vs PRD.md's 582 lines / 147,004 bytes (+2,519 bytes).
- `cmp` confirms it is NOT byte-identical to PRD.md.
- `diff` reports changed lines **95, 244, 252, 264, 368 and nothing else** — exactly the five edits claimed,
  no collateral edits anywhere in the 582 lines.
- Tail check: the file ends on `| ERR_STALE_PRODUCT_MODEL_VERSION | 412 |`, the last row of the 5 error
  catalogue — a real section boundary, not a mid-sentence truncation.

## Step 9: PRD completeness scan — PRD_COMPLETED.md — 2026-09-04T12:05:00.000Z

**Orchestration decision.** Project memory records that Step 9 silently no-ops when run as a
single pass: the scan subagent copies PRD_FINALIZED.md to PRD_COMPLETED.md, exhausts its
budget on the read-and-classify walk, and exits with a byte-identical file. I therefore ran
Step 9 as **three sequential, file-partitioned passes** over one shared output file, each pass
owning a disjoint set of `implementation/` modules and editing PRD_COMPLETED.md **in place**
with the Edit tool. Every pass prompt carried an explicit "DO NOT RUN `cp` — THE FILE ALREADY
EXISTS" warning naming the file's current line and byte count, so a later pass could not
destroy an earlier pass's work. Each pass was told to route out-of-scope observations forward
to the pass that owns them, and the orchestrator forwarded them in the next pass's prompt.

Partition (by implementation module, balanced by line count):

| Pass | Modules | Lines |
|---|---|---|
| A | app.py, rt.py, errors.py, r_clock.py, auth.py, serial.py, schema.py, core.py, r_equip.py, r_models.py | 1,806 |
| B | r_orders.py, r_resin.py, r_cycles.py, calc.py (minus the nine §3.7–§3.9 functions) | 1,763 |
| C | r_party.py, svc.py, r_units.py, r_warranty.py, r_ship.py, calc.py §3.7–§3.9 functions | 2,184 |

All three passes were barred from reading `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`,
`SCAFFOLD_CORNER_DESIGN.yaml` and `worklog.md` — the two design indices hold the withheld test
targets and reading them would leak answers into the deliverable. All three were told that
`implementation/` is the alignment target and `test_suite/` is **not** authority, because Step 7
has already weakened or deleted assertions the PRD did not pin.

### File-state ledger (orchestrator-verified after each pass)

| State | Lines | Bytes | Edits |
|---|---|---|---|
| PRD.md (Step 4) | 582 | 147,004 | — |
| PRD_FINALIZED.md (Step 8) | 582 | 149,523 | 5 |
| after Pass A | 582 | 156,053 | +19 |
| after Pass B | 582 | 167,402 | +30 |
| **PRD_COMPLETED.md (final)** | **582** | **179,954** | **+28** |

Monotonic growth across all three states is the check that no pass clobbered a predecessor:
179,954 > 167,402 > 156,053 > 149,523. Verified after every pass, not just at the end.

### Pass A — foundation modules (orchestrator reconstruction of the returned report)

19 edits over §2.1–§2.7 and §4, rooted in the request envelope, auth, the run-time store, the
error catalogue, the clock, the serializers, the schema validator, the shared core helpers,
and the equipment and product-model routes.

Routed forward to Pass C (all three §2.8 mismatches Pass A found but did not own):
- `r_warranty.py:38` — `storage_description` is `required: False` at claim creation, but §2.8
  WarrantyClaim called it "required, 10–500 characters". §3.9 already said optional, so §2.8
  was the mismatched half.
- `r_warranty.py:108` — a new claim's `months_in_service` is `None`, but §2.8 said
  "integer, default 0". §3.9 already said null.
- `r_ship.py:31` — shipment create accepts an **optional** `customer_id` and `serial.SHIPMENT`
  emits it, but §2.8's Shipment client-supplied list omitted the field entirely while §3.8
  said the trailer is booked "against one `customer_id`".

Routed forward to Pass B: the §3.5 claim that a minted hull "inherits the cycle-level charged
mass and provisional warpage", and the conditional-vs-unconditional unblock sweep.

### Pass B — order / resin / cycle modules (orchestrator reconstruction of the returned report)

30 edits: 13 mismatch-revisions, 17 ambiguity-pins. Both observations routed from Pass A were
investigated and resolved:
- §3.5's hull-inherits-charged-mass-and-warpage clause: **CONFIRMED FALSE** —
  `serial.FINISHED_UNIT` carries no such field and `svc.mint_units` (svc.py:291-319) sets
  none. Clause removed rather than reworded.
- The unblock sweep: **CONFIRMED** conditional, and pinned individually at `r_resin.py:356`
  (`revived`) and `r_cycles.py:484` (`released`, gated on charges being released rather than on
  a lot revival), extending Pass A's §3.2 wording instead of overwriting it.

Pass B deliberately left the nine §3.7–§3.9 `calc.py` functions (`select_zone`,
`derive_posture`, `shipment_rollup`, `_line_freight`, `discount_rate_pct`, `shipment_freight`,
`months_in_service`, `coverage_pct`, `warranty_payout`, calc.py:404-634) to Pass C, on the
grounds that their prose homes are Pass C's sections. The orchestrator accepted that split and
reassigned them explicitly in Pass C's prompt.

### Pass C — parties / units / warranty / shipping (verbatim returned report)

PASS C complete. `PRD_COMPLETED.md` is the pipeline's final deliverable.

Verification
- Before my pass: 582 lines / 167,402 bytes. After: 582 lines / 179,954 bytes (+12,552).
  Passes A and B survived (all 49 prior edits intact; verified the CASCADE-C landmark text and
  every previously-edited paragraph).
- All five `## ` headers present (lines 3, 11, 194, 386, 487); file ends at the real section
  boundary `| ERR_STALE_PRODUCT_MODEL_VERSION | 412 |`.
- `PRD_FINALIZED.md` untouched (149,523 bytes). No `cp`, no `Write`, no server, no tests, no
  `pkill`. Never read SCAFFOLD*.yaml or worklog.md.

Changes — 28 edits total (13 mismatch-revisions, 15 ambiguity-pins)

§2.8 entity blocks (6 revisions, all mismatch)
- §2.8 Customer — revise — mismatch — `storage_guidance_acknowledged_at` is the client-supplied
  `acknowledged_at`, not a clock stamp; repeat ack overwrites either direction — r_party.py:79-93
- §2.8 Customer — revise — mismatch — `email` `@`-only check, error is `ERR_VALIDATION`, no
  further structure — r_party.py:41
- §2.8 FinishedUnit — revise — mismatch — measurement points unquantised/echoed verbatim;
  `min_wall_thickness_mm` is three decimals, split from `wall_cv_pct`'s two — r_units.py:200-215
- §2.8 Shipment — revise — mismatch — `customer_id` is optional (default null); both customer
  checks only fire when supplied — r_ship.py:31, 77-85
- §2.8 Shipment — revise — mismatch — `density_kg_per_m3` is three decimals, default
  0.000 — r_ship.py:108
- §2.8 WarrantyClaim — revise — mismatch — `storage_description` optional at
  intake — r_warranty.py:38
- §2.8 WarrantyClaim — revise — mismatch — `months_in_service` default null, not
  0 — r_warranty.py:108, 402

§3.1 (3 inserts, ambiguity)
- §3.1 — insert — ambiguity — threshold rule precedes capacity-sum; duplicate `site_code`
  precedes in-array `zone_code` collision — r_party.py:204-208
- §3.1 — insert — ambiguity — footprint-summary zone order = declaration order;
  `stored_unit_count` = STORED∪LOADED; `anchor_product_model_ids` de-duplicated,
  `created_at`-ordered; read recomputes live and bumps no version — r_party.py:249-292
- §3.1 — insert — ambiguity — `ERR_INVALID_WINDOW` outranks `ERR_DUPLICATE_CODE` on
  buckets — r_party.py:322-325

§3.6 (5 inserts/revisions, ambiguity)
- §3.6 — insert — ambiguity — trim resets nothing but `hardware_kit_serial`; verdict,
  `rework_count`, all measurements survive — r_units.py:150-164
- §3.6 — insert — ambiguity — the two technician-id columns are overwritten, never
  nulled — r_units.py:180-266
- §3.6 — insert — ambiguity — full inspect check order: schema → 6-measurement minimum →
  ACTIVE → certification → build → logistics → segregation — r_units.py:123-147
- §3.6 — revise — ambiguity — a `REWORK` verdict itself clears
  `hardware_kit_serial` — r_units.py:256-259
- §3.6 — insert — ambiguity — CASCADE-D: re-inspection `PASS` keeps SELLABLE, never forgives
  `rework_count`, still bumps both versions — r_units.py:253-266

§3.7 (3 revisions)
- §3.7 CASCADE-H — revise — ambiguity — order-walk order; site version bumped exactly once;
  bucket recompute bumps the bucket — svc.py:150-189
- §3.7 CASCADE-C item 4 — revise — ambiguity — un-freeze leaves a lot-less order at
  `BLOCKED_WAREHOUSE`/`WAREHOUSE_FROZEN` with no version movement; never re-labelled
  `BLOCKED_RESIN` — svc.py:162-183
- §3.7 — revise — mismatch — departure's vacate half runs per hull (was "per nest group");
  `warehouse_id` retained through `IN_TRANSIT` — r_ship.py:266-289

§3.8 (7 revisions/inserts)
- §3.8 — revise — mismatch — booking: `customer_id` optional, ACTIVE gate conditional; create
  order = FKs → schema → `ERR_DUPLICATE_CODE` → `ERR_CUSTOMER_NOT_ACTIVE` →
  `ERR_WAREHOUSE_POSTURE_RESTRICTED` — r_ship.py:69-102
- §3.8 — insert — ambiguity — line add: shipment version +1 once; new line stays at version 1;
  existing lines restamped only on real change to one of four columns — r_ship.py:498-515
- §3.8 — insert — ambiguity — line removal: same version discipline — r_ship.py:417-434
- §3.8 — insert — mismatch — persisted `line_freight_cents` is always nested-basis,
  pre-discount, pre-fuel; never rewritten at delivery — calc.py:465-499
- §3.8 — revise — ambiguity — discount tier read from persisted (nested)
  `cube_utilization_pct` in the BILLED variant too — calc.py:566-586
- §3.8 — revise — mismatch — depart/deliver carry a required instant that is validated then
  ignored; cascade granularity: per-hull vacate, once-per-site recompute,
  once-per-bucket — r_ship.py:231-311
- §3.8 — insert — ambiguity — cancellation resets all five rollups to their initial
  zeros — r_ship.py:314
- §3.8 — revise — mismatch — freight-summary response shape corrected: the two
  `*_pre_discount_cents` are live, the two `*_freight_cents` are persisted (null before
  seal/delivery); no discount-amount and no fuel-surcharge field — r_ship.py:519-561

§3.9 (4 inserts/revisions)
- §3.9 — insert — ambiguity/mismatch — intake also gates claimant-ACTIVE and hull-DELIVERED;
  order = scope → FKs → schema → code → deformation → ACTIVE → DELIVERED — r_warranty.py:88-95
- §3.9 — insert — ambiguity — `months_in_service` compares time-of-day to the microsecond;
  floored at 0 — calc.py:597-614
- §3.9 — revise — mismatch — the OCC guard is evaluated last of all, after the reserve gate
  (PRD had said "the version check follows" the storage axis) — r_warranty.py:340-346
- §3.9 — insert — mismatch — denial zeroes the four amounts but leaves `payout_basis`
  null — r_warranty.py:382-386

§4 (3 revisions, ambiguity) — added the missing list filters: `/shipment-lines` gains `status`
(r_ship.py:448), `/customers` gains `region_code`/`status` (r_party.py:58-59), `/warehouses`
gains `posture` (r_party.py:231), `/finished-units` gains `inspection_verdict`,
`storage_zone_code`, `is_zone_anchor` (r_units.py:79-82).

Verdicts on the seven routed observations
1. `storage_description` required — CONFIRMED mismatch, fixed in §2.8 (§3.9 was already right).
2. `months_in_service` default 0 — CONFIRMED mismatch, fixed in §2.8.
3. Shipment `customer_id` — CONFIRMED mismatch, both halves fixed (§2.8 and §3.8).
4. `recompute_warehouse(bump=…)` — NOT a divergence: `bump=False` is dead code. All three call
   sites (r_units.py:408, svc.py:338, r_ship.py:261) take the default, so every recompute path
   bumps the site version. Pinned positively as "bumped exactly once" in §3.7/§3.8 rather than
   with per-path exceptions.
5. `posture_cascade` FROZEN exit — CONFIRMED silence, pinned in §3.7 CASCADE-C item 4 (order
   stays `BLOCKED_WAREHOUSE`, never re-labelled `BLOCKED_RESIN`).
6. `vacate_unit` tie-break — already correctly pinned in §3.7 ("ascending `stored_at` with
   ascending `hull_serial` as the total tie-break", plus the footprint-raising note). No edit.
7. `inspection_verdict` REWORK→SCRAP override — already correctly pinned in §3.6 ("After the
   ladder, one override applies…"). No edit.

Already correctly pinned (checked, no edit)
§4's Authorized Role(s) column for every route in my five modules; §5 covers every error code my
modules raise with matching statuses; §3.7's four store gates in impl order (frozen → window →
zone → quota/site-cube) and the at-or-equal cube/quota/zone inclusivity; §3.7 zone ranking
(anchor affinity → tightest fit → `zone_code`) and nest-group cost; §3.7 posture derivation
at-or-above on the rounded utilisation; §3.8's per-line-then-sum rounding, discount-then-fuel
order, at-or-below trailer admission, seal floor at exactly 60.00,
renumbering-can-raise-nested-cube; §3.9's admin-fee tier chosen from pre-deduction gross,
PRO_RATA/FLAT_SCHEDULE boundaries, reserve gate inclusivity,
`ERR_STORAGE_GUIDANCE_NOT_ACKNOWLEDGED` at-or-before semantics, waiver-still-deducts,
denial-forces-`STORAGE_GUIDANCE_VIOLATED`, return-to-queue double reset, void retains money
fields and is the only reserve-raising path, suspension voids open claims; §3.1's
customer/warehouse/bucket registration; §2.8 ShipmentLine.

Residual divergences / caveats (honest list)
- Ownership overlap: §2.8's `min_wall_thickness_mm` three-decimal fix is rooted in
  `calc.wall_distribution` (Pass B's function). I fixed it anyway because §3.6 already said
  three decimals and the two halves contradicted each other.
- §2.7 band list is still silent on where `ERR_TECHNICIAN_SUSPENDED` (rung 30) and
  `ERR_TECHNICIAN_NOT_CERTIFIED` (rung 31) sit globally — band 1 and band 5 both omit them. I
  pinned the order locally in §3.6 for the four build-axis edges only; §2.7 is Pass A/B
  territory and the same rungs also govern r_resin.py's `RESIN_BLENDING` check (Pass B). A
  cross-cutting §2.7 sentence is the one thing I'd add if a fourth pass existed.
- Dead code, deliberately undescribed: `svc.recompute_warehouse(bump=False)` and
  `svc.refresh_shipment` are unreachable; no PRD text describes them and none should.
- Defensively unreachable guard left unpinned: `release_storage`'s rung-38.6 "hull still carries
  a loaded trailer line" check (r_units.py:425-430) can't fire, since every path that removes a
  line returns the hull to `STORED`.
- §4 filter descriptions are not declared exhaustive by §4's preamble (only the role column is).
  I brought the four rows in my modules into line with impl, but I did not audit rows rooted in
  Pass A/B modules.

### Orchestrator verification of the final deliverable

Independently measured, not taken from any pass's report:
- `wc -l -c` → 582 lines / 179,954 bytes; larger than every prior state, so all 77 edits
  (5 Step 8 + 19 + 30 + 28) survived intact.
- `cmp -s PRD_FINALIZED.md PRD_COMPLETED.md` → differs. This is the memory-flagged no-op check:
  a byte-identical file would mean the scan never ran. 68 changed lines vs PRD_FINALIZED.
- All five `## ` section headers present at lines 3 / 11 / 194 / 386 / 487 — no section lost.
- Tail is `| \`ERR_STALE_PRODUCT_MODEL_VERSION\` | 412 |`, the last row of the §5 error-code
  table: a real section boundary, not a mid-sentence truncation. Final line is 44 bytes.
- Code fences balanced (4 fence markers, even). No `TODO`, `TBD`, trailing-ellipsis or
  placeholder markers anywhere in the file.
- Section 5 contains exactly one non-table paragraph (its preamble) — the catalogue table is
  structurally intact from header to last row.
- Pass A/B landmark strings still present (`CASCADE-C` ×3, `revived` ×6, `released` ×19), so no
  pass overwrote a predecessor's prose.
- `PRD_FINALIZED.md` unchanged at 149,523 bytes and `PRD.md` unchanged at 147,004 bytes — the
  earlier states remain available for diffing.

### Assessment of the residual list

Pass C's §2.7 gap is real and I am recording it rather than papering over it: the two
technician rungs are pinned locally at every edge where they can fire (§3.6's four build-axis
edges, and §3.2's `RESIN_BLENDING` check as Pass B left it), so no endpoint's behaviour is
under-determined — what is missing is only the redundant global restatement in §2.7's band
list. A reader implementing from this PRD reaches the same code either way. The other four
residuals are ownership bookkeeping, two unreachable code paths that correctly have no prose,
and an un-audited-but-unclaimed exhaustiveness property of §4's filter column. None leaves a
reachable behaviour ambiguous.

**Step 9 complete. `workspace/PRD_COMPLETED.md` is written and verified. Pipeline finished.**
