# Worklog — task_2519_offsite_modular_construction_factory_site_set

## Step 1: Create task directory — 2026-09-03T04:51:29.980Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2519_offsite_modular_construction_factory_site_set` and its `workspace/` subdirectory. Index 2519 was pre-assigned by the orchestrating command; no scan of `./tasks/` was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-03T07:05:17.948Z

All three scaffold artifacts for task 2519 are complete and lint-clean.

## Output directory
`/home/ubuntu/github/CodingPRD/tasks/task_2519_offsite_modular_construction_factory_site_set/`

```
-rw-rw-r-- 1 ubuntu ubuntu 158078 SCAFFOLD.yaml                     (3216 lines)
-rw-rw-r-- 1 ubuntu ubuntu 122125 SCAFFOLD_DIFFICULTY_DESIGN.yaml   (1831 lines)
-rw-rw-r-- 1 ubuntu ubuntu 359172 SCAFFOLD_CORNER_DESIGN.yaml       (5873 lines)
```
(`worklog.md` and `workspace/` were pre-existing, not written by me.)

Key-shape check: `SCAFFOLD.yaml` top-level keys are `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — neither `scaffold_difficulty_design` nor `scaffold_corner_design`. The other two files each have exactly one top-level key.

## SCAFFOLD.yaml counts
10 entities, 9 state machines, 2 concurrency rules (OCC only), 11 calculations, 65 ordered validations, 56 endpoints, 73 errors, 10 roles (`segregation_of_duties`, three `entity_backed`: Factory / InspectionAgency / Project).

## §1.8 — 9 rule ids, 19 instances
| rule_id | instances |
|---|---|
| dual_variant_calc | 2 |
| combinatorial_formula | 3 |
| non_linear_state_machine | 2 |
| transitive_cascade | 2 |
| priority_pair_validation_conflict | 2 |
| boundary_precision_check | 2 |
| cross_entity_state_dependency | 2 |
| resource_temporal_overlap | 2 |
| compensating_invariant | 2 |

## §1.9 — 9 sections, 92 instances (72 recipes, 20 `excluded_because` stubs)
| section | instances | recipes | stubs |
|---|---|---|---|
| entities | 13 | 13 | 0 |
| state_machines | 17 | 13 | 4 |
| calculations | 18 | 11 | 7 |
| validations | 16 | 10 | 6 |
| endpoints | 6 | 6 | 0 |
| errors | 12 | 12 | 0 |
| rbac | 4 | 3 | 1 |
| cross-cutting complexity layers | 5 | 3 | 2 |
| consistency model | 1 | 1 | 0 |

Integrity verified programmatically: all 111 instance names unique across the §1.8/§1.9 union, every stub's `difficulty_instance` resolves to a real §1.8 instance name, and no stub carries a `test_recipe`.

## Lint VERDICT (verbatim, final run)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2519_offsite_modular_construction_factory_site_set/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2519_offsite_modular_construction_factory_site_set/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2519_offsite_modular_construction_factory_site_set/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    56
  §1.1 entities declared:     10
  §1.8 instances scanned:     19
  §1.9 instances scanned:     72
  Calls scanned (§1.8+§1.9):  1315

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Notes worth relaying
- One SCAFFOLD.yaml fix was needed for triggerability: `ERR_MODULE_ALREADY_LOADED` was unreachable at priority 70 because the priority-49 `ERR_SHIPMENT_NOT_LOADABLE` check shadows it (an already-loaded module also fails `site_status == AT_FACTORY`, and cancel clears `shipment_id`). It now sits at priority 38 with the ordering rationale spelled out in its `check:` text; `ERR_SHIPMENT_NOT_LOADABLE` stays triggerable via a load onto a DISPATCHED shipment.
- Three §1.9 taxonomy rows from the claim-extraction guide were deliberately omitted because the scaffold has no matching construct: chronological/forward_looking/topological calculation algorithms and Bulk action endpoints.
- The hard constraint was honored: no sibling `task_*/` directory was listed, globbed, grepped, or read at any point.

## Step 3: Copy shared files — 2026-09-03T07:05:36.583Z

Copied `./INSTRUCTION.md` (1424 bytes) to `tasks/task_2519_offsite_modular_construction_factory_site_set/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-03T07:20:30.860Z

PRD.md is complete and verified.

## Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_2519_offsite_modular_construction_factory_site_set/workspace/PRD.md` — **476 lines / 112,767 bytes**

## Section list

- `# Offsite Modular Construction Factory & Site Set API — Product Requirements Document`
- **§1. Introduction** (3 paragraphs: domain framing, the compliance-audit spine, the temporal-windowing overlay)
- **§2. Global Specifications & System-Wide Principles**
  - 2.1 Access Control and Actor Identity
  - 2.2 API Response Structure *(byte-identical verbatim copy of `skills/prd-bench-doc-generator/section-2.2-response-structure.md`)*
  - 2.3 Pagination
  - 2.4 Resource Identity, Timestamps and Versioning
  - 2.5 Flat Addressing and Left-to-Right Identifier Resolution
  - 2.6 Rejection Precedence *(full 65-rule priority ladder with explicit rank numbers)*
  - 2.7 Optimistic Concurrency on the Parent Version
  - 2.8 Money, Percentages, Rounding and Conserved Ledgers
  - 2.9 Parallel State Dimensions and Derived Roll-Ups
  - 2.10 The Logical Clock and Temporal Windows
- **§3. Business Logic & Workflows**
  - 3.1 Standing Up the Plant, the Agency Panel and the Project
  - 3.2 Design Freeze: the Revision Loop, Compatibility Scoring and Supersession
  - 3.3 The Bifurcated Permit Ladder and the Project's Permit Posture
  - 3.4 Takt Scheduling, Line Capacity and Station Progress
  - 3.5 Third-Party Quality Inspection, Agency Holds and Release
  - 3.6 Loads, Shipping Envelopes, Route Surveys and Transport
  - 3.7 Crane Pick Planning, Site Set Sequencing and Weather Exposure
  - 3.8 Factory Versus Field: Defect Responsibility and Warranty Allocation
  - 3.9 Financing: Deposits on Factory Work in Progress and Milestone Draws
- **§4. Endpoint Definitions** (56-row table, exactly 4 columns: Method, Path, Description, Authorized Role(s))
- **§5. Error Code Catalogue** (73-row table, exactly 2 columns: Error ID, HTTP Status Code)

## Coverage counts

| Scaffold element | In scaffold | Documented |
|---|---|---|
| Entities | 10 | 10 |
| Entity fields | 138 | 138 |
| State machines | 9 | 9 |
| Transitions | 47 | 47 |
| Calculations | 11 | 11 |
| Validations | 65 | 65 |
| Endpoints | 56 | 56 |
| Errors | 73 | 73 |
| Roles | 10 | 10 |
| Concurrency (OCC) rules | 2 | 2 |

## Hard Contract reports

**CONTRACT 1 — FIELD-NAME COVERAGE: PASS**
```
entities[].fields:          138 required, 138 present, 0 missing
endpoints[].request_body:    92 required,  92 present, 0 missing
endpoints[].query_params:    39 required,  39 present, 0 missing
path_params:                 10 required,  10 present, 0 missing
errors[].id:                 73 required,  73 present, 0 missing
roles[].name:                10 required,  10 present, 0 missing
state values:                43 required,  43 present, 0 missing
enum members:                95 required,  95 present, 0 missing
```

**CONTRACT 2 — RULE COVERAGE: PASS**
```
1. validations[].priority ......... 65/65 rules given an explicit rank in §2.6;
   ladder documented 1-10, 38-59, 60-66, 67-69, 71-75, 76-80, 81-89, 90-93
   (gaps 11-37 and 70 are unused in the scaffold and are not invented).
   Rank 38 ERR_MODULE_ALREADY_LOADED precedes all state checks; rank 93
   ERR_FIELD_SCOPE_NOT_SIGNED_OFF sits below every fiscal rule.
2. concurrency_rules ............... 2/2 (expected_project_version ->
   ERR_STALE_PROJECT_VERSION 412 on design-package create; expected_shipment_version
   -> ERR_STALE_SHIPMENT_VERSION 412 on load-module), both in §2.7 and at their
   call sites.
3. cross-entity side effects ....... all cascades narrated, incl. the 3-link
   design-freeze cascade (predecessor -> SUPERSEDED, permit APPROVED ->
   CONDITIONS_ISSUED with conditions_count += 1, Project.phase re-derivation)
   and the 3-link QC-hold cascade (unload from loadable shipment, ledger
   decrement, WIP reversal), with sibling-arm symmetry preserved for
   IN_PROGRESS -> HOLD and CONDITIONAL_RELEASE -> HOLD.
4. applies_to scopes ............... every multi-endpoint validation enumerated
   exhaustively (ERR_QC_HOLD_BLOCKS_OPERATION x4, ERR_PLAN_REVIEW_PREREQUISITE x2,
   ERR_PICK_RADIUS_OFF_CHART / ERR_CRANE_CAPACITY_EXCEEDED x2,
   ERR_TRANSPORT_PERMIT_EXPIRED x2, ERR_AGENCY_NOT_ACCREDITED /
   ERR_AGENCY_JURISDICTION_MISMATCH x2, ERR_CROSS_AGGREGATE_MISMATCH x2,
   ERR_DRAW_NOT_CERTIFIED x2, ERR_DUPLICATE_CODE x2, plus the rank-5/rank-6
   broad scopes).
5. field-level structured content .. nested keys spelled out (crane_capacity_chart
   radius_ft / capacity_lb, shift calendars, envelope thresholds, ledger triples
   committed_line_minutes / loaded_module_count / wip_certified_cents).
6. sibling-branch symmetry ......... 9 groups at equal density: FREEZE vs
   RETURN_FOR_REVISION; the 4 permit decisions; the 4 QC result arms; WIP variants
   station_progress vs milestone_delivered; defect variants phase_presumption vs
   evidence_weighted; basis_mode WIP_DEPOSIT vs MILESTONE_SET; route_survey_state
   forward and backward arms; the two paths into Shipment PERMITTED; the two
   ModuleUnit LOADED <-> AT_FACTORY directions.
7. transitions ..................... 47/47 with preconditions + side effects.
8. calculations .................... 11/11 (module_envelope_class,
   module_wip_earned_cents, line_slot_schedule, crane_pick_feasibility,
   draw_certification_amount, defect_responsibility_allocation,
   permit_posture_derivation, project_phase_derivation,
   shipment_permit_fee_and_escort, module_exposure_hours,
   design_factory_compatibility_score) - all in prose, no pseudocode.
9. every errors[].id reachable ..... 0 errors unreferenced in the §1-§4 narrative.
```

**CONTRACT 3 — §3 PATH PURITY: PASS**
```
tokens scanned in §3: 1310  (unique: 323)
backticked tokens containing '/': []
bare HTTP method tokens:          []
method + path tokens:             []
occurrences of '/modular' in §3:  0
```

Additional style checks: zero fuzzy quantifiers (`approximately|roughly|about N|conservatively`), zero leaked symbolic operators (`==`, `!=`, `>=`, `<=`, `+=`, `&&`, `||`, `IN {`, `round_half_up(`, `floor(`, `max(`, `min(`) anywhere in the document.

## Verbatim `tail -30`

```
| `ERR_WEATHER_EXPOSURE_LIMIT` | 409 |
| `ERR_SET_NOT_PERMITTED` | 409 |
| `ERR_QC_HOLD_BLOCKS_OPERATION` | 409 |
| `ERR_QC_NOT_RELEASED` | 409 |
| `ERR_SET_SEQUENCE_VIOLATION` | 409 |
| `ERR_LINE_CAPACITY_EXCEEDED` | 409 |
| `ERR_CRANE_WINDOW_CONFLICT` | 409 |
| `ERR_MODULE_ALREADY_LOADED` | 409 |
| `ERR_ENVELOPE_EXCEEDS_ROUTE_LIMIT` | 422 |
| `ERR_QC_STAGE_OUT_OF_ORDER` | 409 |
| `ERR_DUPLICATE_CODE` | 409 |
| `ERR_DUPLICATE_MODULE_CODE` | 409 |
| `ERR_ESCORT_NOT_CONFIRMED` | 422 |
| `ERR_LINE_SLOT_IN_PAST` | 422 |
| `ERR_LINE_SLOT_OUTSIDE_SHIFT` | 422 |
| `ERR_PICK_WINDOW_INVALID` | 422 |
| `ERR_TRANSPORT_PERMIT_EXPIRED` | 409 |
| `ERR_CLOCK_NOT_MONOTONIC` | 422 |
| `ERR_AGENCY_NOT_ACCREDITED` | 422 |
| `ERR_AGENCY_JURISDICTION_MISMATCH` | 422 |
| `ERR_PLAN_REVIEW_PREREQUISITE` | 409 |
| `ERR_NO_FROZEN_PACKAGE` | 409 |
| `ERR_PINNED_PACKAGE_MISMATCH` | 409 |
| `ERR_INVALID_SUPERSESSION` | 422 |
| `ERR_FACTORY_COMPATIBILITY_TOO_LOW` | 422 |
| `ERR_CROSS_AGGREGATE_MISMATCH` | 422 |
| `ERR_SHIPMENT_PROJECT_MISMATCH` | 409 |
| `ERR_CONTRACT_BALANCE_EXCEEDED` | 422 |
| `ERR_NO_CERTIFIABLE_WIP` | 422 |
| `ERR_DRAW_SEQUENCE_GAP` | 409 |
```

The document ends at a real section boundary (final row of the §5 table), not mid-sentence.

## Notes for the orchestrator

Three scaffold ambiguities were resolved conservatively rather than by invention:

1. **QC-hold cascade attachment.** The `IN_PROGRESS -> HOLD` transition lists only `hold_state` + version side effects, while the `record-result` endpoint's `side_effects` says a FAIL "fires the three-link hold cascade." I attached the cascade to the condition "whenever a module's `qc_status` becomes `HOLD`," covering both arms, and noted that the unload link only has work to do when the hold arrives from `CONDITIONAL_RELEASE` (a module in `IN_PROGRESS` was never loadable). This preserves sibling-branch symmetry without dropping or fabricating a rule.
2. **`PAIRED_FIRST` semantics.** The scaffold says it "additionally requires" the PAIR_A-before-PAIR_B rule, so it is documented as strict-ascending *plus* the pair rule.
3. **Omitted rule.** `complexity_profile.role_model` hints that the certifying agency may not be the QC agency of record, but no `validations` entry or `errors[].id` backs it, so it was deliberately not written into the PRD.

The two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced, and no sibling `task_*/` directory was read.

**Orchestrator verification:** independently confirmed `wc -l -c` = 476 / 112767, `grep -n '^#'` shows all five top-level sections with §5 last, and the file's final bytes are a complete `| \`ERR_DRAW_SEQUENCE_GAP\` | 409 |` table row — not truncated mid-sentence. No regeneration needed.

## Step 6: Generate implementation — 2026-09-03T07:52:00.000Z

(Steps 5 and 6 were launched concurrently in a single assistant message, per the skill. Step 6 returned first; the Step 5 entry follows below.)

The implementation is complete and verified.

## Modules (all under `.../task_2519_offsite_modular_construction_factory_site_set/workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | launcher; guarded `pip install` (skipped when Flask is importable), `exec python3 app.py` |
| `requirements.txt` | 1 | `Flask==3.0.3` |
| `app.py` | 73 | app factory, 10 blueprints, `ApiError`/`HTTPException`/catch-all handlers, `PORT` default 10000 on `0.0.0.0` |
| `store.py` | 101 | in-memory `Store` (10 dicts), logical clock (startup `2026-08-01T00:00:00Z`), `base_row`/`touch`/`sorted_rows` |
| `errors.py` | 97 | all 73 error ids -> HTTP status, `ApiError` |
| `envelope.py` | 98 | `meta`/`response_type`/`data` envelope, `req_`+20-char request id, offset pagination |
| `validate.py` | 240 | rank-3 payload/query validation, ISO-8601 parsing, crane-chart monotonicity |
| `auth.py` | 82 | ranks 1/2, entity-backed ownership helpers (rank 6) |
| `calc.py` | 258 | all 11 calculations + every §1.3 constant |
| `serialize.py` | 259 | 10 entity serialisers |
| `services.py` | 454 | existence resolution, derivations, conserved ledgers, 5-link supersession cascade, 3-link QC-hold cascade, clock sweep |
| `routes/registry.py` | 190 | factories + agencies |
| `routes/projects.py` | 189 | projects, set-readiness, weather observations |
| `routes/design.py` | 255 | design packages, freeze review cycle |
| `routes/modules.py` | 590 | modules, line slots, station advance, pick, set, connections |
| `routes/permits.py` | 213 | both permit tracks |
| `routes/inspections.py` | 247 | inspections, results, hold clearing |
| `routes/shipments.py` | 318 | shipments, load/survey/dispatch/deliver/cancel |
| `routes/claims.py` | 183 | defect claims, adjudicate/dispute |
| `routes/draws.py` | 236 | draw requests, certify/fund/reject |
| `routes/clock.py` | 30 | logical clock setter |

Total 4125 lines. No `__pycache__` left behind; no file I/O, no SQLite, no seeding (verified by grep).

## Coverage

- **Endpoints: 56/56.** Programmatically diffed the scaffold's declared `method + path` set against Flask's URL map — zero missing, zero extra.
- **Errors: 73/73.** Every id in the catalogue is raised somewhere and every id raised exists in the catalogue (verified by script; both diffs empty).
- **Validations: all 93 ladder ranks** wired in rank order per handler (rank 3 before rank 4, rank 38 above 49, rank 71 above 89, rank 93 last).
- **Calculations: 11/11**, including the three-rounding draw waterfall, dual-variant WIP and defect allocation, integer cross-product crane gate, exact `//4` wind derate.
- **State machines: 9/9** across the three parallel module dimensions plus both shipment axes.

## Boot check

`PORT=18531 bash start.sh` boots in <2s from a fresh process; a trivial `GET /modular/factories` returns 200. A 47-request end-to-end scenario (factory -> project -> design freeze -> both permit tracks -> module -> line slot -> 2 station advances -> agency -> 2 inspections -> draw certify/fund -> shipment load/survey/dispatch/deliver -> 4 more permits -> pick -> set -> clock advance -> claim adjudicate/dispute/re-adjudicate -> close-connections -> set-readiness) passes with **zero failures** and correct derived values: score 100, posture `STATE_CLEARED_ONLY` -> `OCCUPANCY_CLEARED`, phase `PRECONSTRUCTION` -> `DESIGN_FROZEN` -> `SHIPPING` -> `CLOSEOUT`, WIP 0 -> 500000 -> 1000000, draw 1000000 / 200000 / 10000 / 190000, utilization 37.50, exposure 52.00 h, round-1 split 25/75 with 25000/75001 cents, round-2 `FIELD` at 0.00, claim auto-`CLOSED` on connection closeout.

## Two spec corrections made this session

While writing the draw module I re-read PRD §3.9 line 325, which enumerates *exactly* which events refresh a `DRAFT` draw's basis: "an intermediate or terminating station advance, a delivery, a quality hold arriving, and a hold being cleared." I had been refreshing more broadly, so I narrowed it: `advance-station` no longer refreshes on a non-terminating first advance out of `SLOTTED`, `record-result` refreshes only when a hold actually lands, shipment `cancel` no longer refreshes, and `GET` on a draw never refreshes.

## PRD ambiguities resolved (choice in bold)

1. `defect_count_factory`/`_field` — §2.9 describes them as counts by `discovered_phase`, §3.8 as increments by `responsibility` after adjudication. **Took §3.8**, and per the normative formula a `SHARED` allocation increments *neither* counter.
2. `record-result` `FAIL` from an agency with `hold_authority == false` — no error exists. **Records the result, places no hold.**
3. `execute-set` with a null `pick_window_start`/`pick_radius_ft` — **`ERR_PICK_RADIUS_OFF_CHART`** (rank 61).
4. Pair-group gate on `close-connections` — **`ERR_SET_SEQUENCE_VIOLATION`** (rank 67).
5. Weather disjunction gate on `close-connections` — **`ERR_WEATHER_EXPOSURE_LIMIT`** (rank 63).
6. Opening an inspection before the module reaches the line — **`ERR_MODULE_NOT_ON_LINE`**, enforced only while `qc_status == PENDING`.
7. `scope`/`track` incompatibility on permit filing — **`ERR_INVALID_REQUEST`** (rank 3, a declared §1.1 constraint).
8. "no other record still at `PENDING`" — **applied to every new inspection**, not only `FINAL_FACTORY`.
9. `created_at`/`updated_at`/`api_request_timestamp` — **all read the logical clock**, with an insertion counter as the deterministic sort tiebreak. Consequence: `updated_at` does not move when the clock has not advanced.
10. Rank-6 ownership applied **only to the eleven endpoints §2.6 lists** — `PATCH line-state`, shipment `deliver`, claim create and claim dispute get no owner check.
11. `PAIRED_FIRST` = **ascending order plus the PAIR_A-before-PAIR_B rule** (the scaffold says "additionally requires").
12. `advance-station` bumps `Project.version` **iff the module left `SLOTTED`**.
13. `record-result` bumps `ModuleUnit.version` **only when `qc_status` or `wip_earned_cents` actually changed** (an `IN_PLANT` `PASS` changes neither).
14. `clear-hold` enforces `ERR_AGENCY_NOT_ACCREDITED` even though rank 81's `applies_to` omits it, because the `HOLD -> IN_PROGRESS` arm lists that precondition and no other error fits.
15. Rank-72's `IN_PLANT` prerequisite enforced **at inspection creation only**.
16. `cancel`/QC-hold transport reset also clears `survey_completed_at`, which the PRD's reset list does not name — chosen for consistency with clearing `permit_expires_at`.

## Step 5: Generate unit tests — 2026-09-03T08:33:00.000Z

(Launched concurrently with Step 6 in a single assistant message; it returned after Step 6, so its entry appears below Step 6's.)

Test generation for task 2519 is complete and verified.

## Files written

`test_helpers/` (infrastructure, 2,221 lines total)
| file | lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_2519_offsite_modular_construction_factory_site_set/test_helpers/__init__.py` | 25 |
| `.../test_helpers/constants.py` | 171 |
| `.../test_helpers/api_errors.py` | 179 |
| `.../test_helpers/test_users.py` | 98 |
| `.../test_helpers/types.py` | 197 |
| `.../test_helpers/api_client.py` | 388 |
| `.../test_helpers/factories.py` | 342 |
| `.../test_helpers/assertions.py` | 217 |
| `.../test_helpers/fixtures.py` | 604 |

`test_suite/` (8,460 lines total, all under `.../task_2519_offsite_modular_construction_factory_site_set/test_suite/`)
| file | lines | tests |
|---|---|---|
| `conftest.py` | 21 | – |
| `test_01_registry_entities_and_references.py` | 628 | 20 |
| `test_02_transport_and_closeout_transitions.py` | 475 | 15 |
| `test_03_quality_permit_and_phase_transitions.py` | 683 | 18 |
| `test_04_derived_values_and_money.py` | 957 | 27 |
| `test_05_validation_and_precedence_rules.py` | 679 | 20 |
| `test_06_endpoint_actions_and_computed_reads.py` | 613 | 19 |
| `test_07_error_catalogue_coverage.py` | 1153 | 34 |
| `test_08_role_authorisation.py` | 671 | 16 |
| `test_09_concurrency_and_response_consistency.py` | 470 | 11 |
| `test_10_draw_basis_and_warranty_allocation_variants.py` | 286 | 6 |
| `test_11_crane_chart_takt_and_draw_formulas.py` | 291 | 9 |
| `test_12_design_revision_loop_and_line_self_loops.py` | 249 | 6 |
| `test_13_supersession_and_hold_cascades.py` | 252 | 6 |
| `test_14_rejection_precedence_pairs.py` | 158 | 4 |
| `test_15_gate_boundaries.py` | 246 | 6 |
| `test_16_cross_entity_prerequisites.py` | 224 | 6 |
| `test_17_line_and_crane_window_contention.py` | 194 | 6 |
| `test_18_conserved_ledgers_under_compensation.py` | 210 | 6 |

## Coverage

- Queue A (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`): 19 instances, 0 stubs — **19/19 translated** into 55 tests (files 10–18), every one with >=2 tests.
- Queue B (`SCAFFOLD_CORNER_DESIGN.yaml`): 92 names, 20 `excluded_because:` stubs (untranslated by design) — **72/72 non-stub translated** into 180 tests (files 01–09).
- **Total: 235 test functions, 266 collected items** with parametrization. 91/91 non-stub instances covered.

## Skipped instances

**None.** Every non-stub instance in both indices passed the PRD-first two-condition filter. What was dropped instead was individual recipe assertions the PRD does not uniquely derive, with the surrounding claim kept on stated ground:
- `certified_cents == 0` on a freshly created `DRAFT` draw (§3.9 enumerates only `certified_at`, `funded_at`, `reject_reason` as null) — dropped in test_04 and test_06.
- `crane_utilization_pct == 0` / pick-field zeros on a rejected or fresh module — asserted as `null` per §2.2 (test_04, test_05, test_07, test_11, test_15).
- `line_slot_minutes == 0` after a terminating advance (test_18) — replaced by the ledger-returns-to-zero claim §2.5 does state.
- `updated_at` advancing while `created_at` holds (test_09) — unassertable under a static logical clock per §2.10.
- Error HTTP statuses contradicting §5 (recipes said 422 for `ERR_INVALID_REQUEST`, `ERR_SHIPMENT_PROJECT_MISMATCH`, `ERR_TRANSPORT_PERMIT_EXPIRED`, `ERR_WEATHER_EXPOSURE_LIMIT`) — all asserted through the registered id->status map instead.

Three recipes were also **unrunnable as written** and were rebuilt per the PRD, same observable claims: the phase-derivation recipe approved plan review before any package was frozen (`ERR_NO_FROZEN_PACKAGE`), and two recipes' pick windows collided once expanded by the 45-minute rigging buffer (`ERR_CRANE_WINDOW_CONFLICT` instead of the intended error).

## Verification run

- `py_compile` clean on all 28 files; `import test_helpers` OK; `pytest --collect-only` collects 266 items, so every import, client method, factory, fixture, error constant and header symbol resolves.
- Design tags: 235 tests / 235 tags, 1:1. Every tag resolves to a real instance, with the section string or rule id matching the yaml; no tag points at a stub; no dual tags; no untagged test.
- Every `Design:` line is the last docstring line, preceded by a blank line, appearing exactly once.
- All ~400 `PRD §x: "…"` citation lines machine-checked as byte-exact substrings of `workspace/PRD.md`; no elided or paraphrased quotes.
- No `pytest.skip` / `skipif` / `xfail` and no occurrence of "scaffold" anywhere in either directory. No duplicate test-function names.
- Isolation held: `workspace/implementation/` was never read by me or any of the nine section agents, no other `task_*/` directory was touched, and the suite was never run against the implementation.

## Step 7: Run tests and iterate — 2026-09-03T09:02:23.598Z

Done — clean 8-round sweep after one fix iteration.

## Summary

**Iterations run:** 2 sweeps (1 diagnostic iteration). The first sweep showed 5 deterministic failures, identical in all 8 rounds — no flakiness anywhere in the suite, so no load-induced noise to filter out.

**Tests deleted:** None. All 5 failures traced to rules stated verbatim in PRD.md and uniquely derivable from it, so STEP 1 kept every test.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes/claims.py`, `create_claim()` — new claims were persisted with `warranty_bucket` = `"UNASSIGNED"`; PRD §3.8 states verbatim that a new claim is persisted with "`warranty_bucket` at its default of `SPLIT`". Also dropped `UNASSIGNED` from the `BUCKETS` filter enum, since PRD declares only `FACTORY_WARRANTY`, `FIELD_WARRANTY` and `SPLIT` (the token `UNASSIGNED` appears nowhere in PRD.md). Fixed 2 tests.

**Fixes applied to `test_helpers/`:**
- `test_helpers/factories.py`, `_merge()` — the suite's `...` "omit this field" sentinel was only honoured for keys arriving via `**overrides`, not for explicitly-named factory parameters. `module_payload(set_sequence_index=...)` therefore bound Ellipsis straight into the payload and the client died with `TypeError: Object of type ellipsis is not JSON serializable` instead of issuing the field-absent request. `_merge` now strips Ellipsis from the merged result regardless of which layer it came from.

**Fixes applied to `test_suite/`:**
- `test_10_draw_basis_and_warranty_allocation_variants.py::test_the_two_basis_modes_diverge_on_identical_module_state` — assertion arithmetic error, not an implementation defect. With `wip_unit_value_cents` 8,750,000 and `station_count` 6, M-01 (LINE_COMPLETE 6/6, DELIVERED) contributes 8,750,000 to both bases and M-02 (IN_LINE 2/6, at the plant) contributes 8,750,000x2/6 = 2,916,667 to the WIP basis only. The divergence is 2,916,667, not the asserted 6,416,667. Two sibling tests that pin the same two bases exactly (11,666,667 and 8,750,000) were already passing, and this test's own next assertion pins M-02 at 2,916,667 — the expected difference contradicted both. Corrected to 2,916,667; still an exact cents equality.
- `test_07_error_catalogue_coverage.py::test_a_draw_whose_money_has_already_gone_out_cannot_be_rejected` — setup precondition violated PRD. It built an empty project via `world_plant_and_project`, so the certify step needed to reach `FUNDED` correctly hit PRD §3.9's substance test ("`certified_basis_cents` must be strictly greater than 0 … a zero basis is `ERR_NO_CERTIFIABLE_WIP`"). Switched the setup to `world_line_complete_module`, the same fixture the passing certify tests in test_18 use. The assertion (rejecting a `FUNDED` draw reports `ERR_DRAW_NOT_CERTIFIED`) was untouched.

**Final sweep, per-round passed/total** (quoted from `workspace/implementation/results.$i.json`): round 1 266/266, round 2 266/266, round 3 266/266, round 4 266/266, round 5 266/266, round 6 266/266, round 7 266/266, round 8 266/266 — `failed=0, errors=0` in every round, union of failures across all 8 rounds empty.

One note worth passing on: three of the five defects were in the test artifact rather than the implementation, and two of those (the arithmetic error and the empty-project setup) were only detectable by cross-checking against sibling tests that asserted the same quantities and passed — the implementation was PRD-correct in both cases.

**Orchestrator verification:** independently parsed all eight `workspace/implementation/results.{1..8}.json` — every file exists on disk (~85 KB each, all written at 08:53) and reports `passed=266, total=266, failed=0, errors=0`. The sweep artifacts are real, not a claimed pass. Step 7 applied 1 `implementation/` fix, so Step 8 is NOT skipped.

## Step 8: Finalize PRD — 2026-09-03T09:10:00.000Z

## Result

`/home/ubuntu/github/CodingPRD/tasks/task_2519_offsite_modular_construction_factory_site_set/workspace/PRD_FINALIZED.md` was created (`cp` of `PRD.md`) and, after auditing all four `<step_7_diff>` items against `implementation/`, **no edit was warranted**: every one of the five Step 7 failures traced to behavior that `PRD.md` already states verbatim and uniquely, and the current implementation matches that prose on every code path I could find.

- Line counts: PRD.md 476 / PRD_FINALIZED.md 476 — **0.0 % delta** (files are byte-identical, md5 `3d999651e0f470cdf2e0fc33d51cccb6`). This is a deliberate outcome, not a skipped scan; per-item evidence below.

## Change list

None. Per-item verdicts:

**Item 1 — `implementation/routes/claims.py` `create_claim()` (`warranty_bucket` default + `BUCKETS` enum)**
- (a) Subject: the initial and derived values of `DefectClaim.warranty_bucket`, and the declared membership of that enum.
- (b) Paths enumerated: `routes/claims.py:19` (`BUCKETS`), `:45-68` (create: now `"SPLIT"`), `:91-112` (list filter), `calc.py:234-257` (`allocation_tail` -> `FACTORY_WARRANTY`/`FIELD_WARRANTY`/`SPLIT` from `responsibility`), `serialize.py:228` (pass-through), `routes/modules.py:585` (close-connections claim closure — sets `status="CLOSED"`, never touches the bucket, i.e. allocation frozen); `grep -rn UNASSIGNED implementation/` -> no remaining hits, `grep -c UNASSIGNED PRD.md` -> 0.
- (c) No wording change: PRD §3.8 line 303 already says a new claim is persisted with "`warranty_bucket` at its default of `SPLIT`" and line 311 already declares exactly the three-member mapping. Step 7 moved the implementation **toward** PRD, so PRD needs nothing. I explicitly considered pinning that the `warranty_bucket` list filter rejects an undeclared member with `ERR_INVALID_REQUEST` (`validate.enum_query` -> `validate.bad` -> `ERR_INVALID_REQUEST`, uniformly used by all 25 enum filters across `routes/*.py`) and rejected it: no test in `test_suite/` exercises an invalid filter value, so the enum-tuple trim was cosmetic rather than a revealed silence, and §2.6 rank 3 already covers "every enum-valued field carries a declared member". Adding a new filter-validation rule would have been out of scope and a global claim over 25 filters.

**Item 2 — `test_helpers/factories.py::_merge()` Ellipsis sentinel**
- (a) Subject: precedence of the role check over payload well-formedness on module creation with `set_sequence_index`/dimensions absent.
- (b) Paths enumerated: `test_suite/test_05_validation_and_precedence_rules.py:121-155` (the only consumer, asserts `ERR_ROLE_NOT_PERMITTED` and that no module was created), `routes/modules.py` create handler ordering (`@auth.endpoint` decorator runs before `validate.body`), `validate.py:22-24`.
- (c) No edit: pure fixture bug. PRD §2.6 ranks 2 and 3 already fix the ordering, and §3.4 already makes `set_sequence_index` and the four envelope integers required.

**Item 3 — `test_10::test_the_two_basis_modes_diverge_on_identical_module_state` arithmetic**
- (a) Subject: WIP vs milestone basis membership, per-module rounding, and the station-progress formula.
- (b) Paths enumerated: `services.py:237-261` (`draw_basis`: WIP selects `SLOTTED|IN_LINE|LINE_COMPLETE` and `qc_status != HOLD`; milestone selects `DELIVERED|SET|CONNECTED`; per-module rounding before `sum`), `calc.py:96-115` (`wip_station_progress`, `wip_milestone_delivered`), `calc.py:62-78` (`rhu`/`rhu_cents`, ROUND_HALF_UP), `services.py:264-269` (`requested_from_basis`), `services.py:272+` (`recompute_draft_draws`), `routes/draws.py:111-176` (certify re-run).
- (c) No edit: 8,750,000 x 2/6 = 2,916,666.67 -> 2,916,667 half-up is exactly what §2.8/§3.4/§3.9 prescribe; the test's `6,416,667` was arithmetically wrong and contradicted its own sibling assertions. PRD prose left verbatim.

**Item 4 — `test_07::test_a_draw_whose_money_has_already_gone_out_cannot_be_rejected` setup**
- (a) Subject: the certify preconditions (contract ceiling then substance test) and the reject-lifecycle gate.
- (b) Paths enumerated: `routes/draws.py:111-176` (certify: rank 42 -> basis re-run -> rank 90 ceiling -> rank 91 `certified_basis <= 0` -> `ERR_NO_CERTIFIABLE_WIP`), `routes/draws.py:180-205` (fund, rank 43), and the reject handler's `DRAFT|CERTIFIED` acceptance reporting `ERR_DRAW_NOT_CERTIFIED`.
- (c) No edit: PRD §3.9 lines 329 and 333 state the ceiling-then-substance order and the `ERR_DRAW_NOT_CERTIFIED` reuse verbatim; the empty-project setup simply violated the PRD precondition.

## Off-scope observations (deliberately not pinned)

Two implementation behaviors near the item-4 site are PRD-silent but were never exercised by Step 7, so under HARD SCOPE I left them alone — flagging them in case Step 9 wants them: `certify` also overwrites `basis_module_count`, `basis_earned_cents` and `requested_cents` from the re-run basis (`routes/draws.py:167-170`, PRD only ties those to `DRAFT`-state refresh events), and it calls `services.refresh_project()` (posture/phase re-derivation on certification, which §3.3/§3.7 do not list among the re-derivation triggers).

**Orchestrator note:** Step 8 legitimately produced a byte-identical `PRD_FINALIZED.md` (md5 confirmed equal to `PRD.md`) with per-item written justification, so it is a real no-op verdict rather than a skipped scan. Step 9 still runs — and because a byte-identical Step 9 output would instead be evidence of a scan that never happened, Step 9 is being run as three sequential file-partitioned passes over `implementation/` (globals/mechanics; calc+services+registry/projects/design/permits/clock routes; modules/inspections/shipments/claims/draws routes), each pass editing the same `PRD_COMPLETED.md`. Step 8's two off-scope observations are forwarded into the draws pass.

## Step 9: Complete PRD — 2026-09-03T09:39:24.858Z

Run as three sequential file-partitioned passes over `implementation/`, each editing the same `workspace/PRD_COMPLETED.md` in place (pass 1 created it from `PRD_FINALIZED.md`). Partitioning was an orchestrator decision: a single-pass Step 9 over a 4,125-line implementation risks a no-op output that only looks like a scan.

### Pass 1 — globals/mechanics (app.py, start.sh, store.py, errors.py, envelope.py, validate.py, auth.py, serialize.py)

Size: 476 lines / 112,767 chars -> 476 lines / 116,687 chars (+3,920; all in-paragraph). **9 ambiguity-pins, 1 mismatch-revision.**

- **§2 preamble (L13)** — insert — ambiguity — server boots with an entirely empty dataset; fresh collection reads answer 200 / empty array / `total_count` 0 — `store.py:33-45`
- **§2.1 (L17)** — revise — ambiguity — an `X-User-ID` present but empty/whitespace-only is also `ERR_UNAUTHENTICATED` — `auth.py:27-28`
- **§2.3 (L78)** — insert — ambiguity — a non-integer `limit`/`offset` is `ERR_INVALID_REQUEST`; an `offset` at/beyond the matching row count is a normal 200 with empty `data`, full `total_count`, `has_more` false — `envelope.py:65-72, 91-97`
- **§2.3 (L80)** — insert — ambiguity — identical `created_at` ties broken by internal creation sequence (total, reproducible ordering); list filters match by exact case-sensitive equality, combine conjunctively, undeclared query params ignored — `store.py:89-92`
- **§2.4 (L88)** — insert — ambiguity — `created_at`/`updated_at` stamped from the logical clock, not wall time; every instant-valued field uses the same 3-fractional-digit ISO-8601 rendering and is `null` until recorded — `store.py:63-68, 71-80`, `serialize.py:15-21`
- **§2.4 (L88)** — insert — ambiguity — serialisation is complete and stable: declared fields always present (single reads and list pages), unset values are JSON `null` not omitted, internal bookkeeping (`_seq`) never exposed — `serialize.py:15-21, 24-259`
- **§2.6 rank 3 (L108)** — insert — ambiguity — absent/empty body = empty object only when all inputs optional else 400; non-object or unparseable JSON always 400; explicit `null` treated as absent; blank naming/code/`*_id` strings rejected; ISO-8601 input strictness (date + time to seconds, optional fraction, optional `Z`/`±HH:MM`, no designator = UTC); query params validated at this rank rather than silently ignored — `validate.py:26-44, 47-77, 89-105, 173-179, 234-240`, `envelope.py:65-90`
- **§2.10 (L159)** — insert — ambiguity — the one clock feeds every emitted instant including the envelope's `api_request_timestamp` (success and error); `current_utc` is required; the capability answers 200 with an empty `data` object — `envelope.py:30-37`, `store.py:54-56`, `routes/clock.py:18-30`
- **§3.1 (L177)** — insert — ambiguity — `crane_capacity_chart` entries' `radius_ft`/`capacity_lb` may not be negative — `validate.py:211-215`
- **§4 preamble (L337)** — revise — **mismatch** — blanket "successful responses carry the created or updated resource in `data`" now excepts the logical-clock capability, which returns an empty `data` object — `routes/clock.py:30`

Already-pinned subjects confirmed by pass 1: the 73-entry error-id -> HTTP status map (programmatically diffed against §5, exact match); envelope/meta field set and `response_type` values; `req_` + 20-char request id; the full pagination contract (limit default 10 / 1..100, offset >=0, out-of-range -> `ERR_INVALID_REQUEST`, `total_count` post-filter pre-page, `has_more`); created_at-ascending ordering; `uuid.uuid4()` ids; `version` starting at 1 and incrementing on indirect mutations; clock startup `2026-08-01T00:00:00Z` and `ERR_CLOCK_NOT_MONOTONIC` on backwards with equality accepted; ladder ranks 1/2/6 including the exact 11 rank-6 ownership callsites; all 152 serializer field names present in PRD and all PRD entity fields emitted (20 input-only names identified); state-code array and crane-chart ordering rules; money/percentage typing. `start.sh`/`app.py` boot mechanics have no PRD surface and the framework 404/405/500 fallbacks apply only to undeclared paths, so both were deliberately left unpinned.

### Pass 2 — calc.py, services.py, routes/{registry,projects,design,permits,clock}.py

Size: 116,687 -> 121,718 chars (+5,031; 476 lines throughout). **12 ambiguity-pins, 5 mismatch-revisions.**

- **§2.4** — revise — mismatch — the blanket "`version` increases by exactly 1 on every mutation" contradicted three impl paths that write derived fields without touching `version`/`updated_at`; added a named "pure re-derivation" carve-out enumerating exactly those three (project derivations on read, module exposure on read/clock, `DRAFT` draw basis figures) — `services.py:209,219,272`
- **§2.10** — insert — ambiguity — clock is advanced *before* the sweep (so swept rows carry the new instant as `updated_at`); the sweep also re-derives `phase` + set counters, not just `permit_posture`; `current_utc` equal to the present value still runs the whole sweep — `routes/clock.py:28-29`, `services.py:432,448`
- **§3.1 (plant)** — insert — ambiguity — line-state patch bumps `version` even when the supplied `line_state` equals the current one — `routes/registry.py:98-99`
- **§3.1 (agency)** — insert — ambiguity — omitting `accredited_state_codes` leaves the stored list; the patch bumps `version` even on a no-op `accreditation_state` — `routes/registry.py:187-189`
- **§3.1 (weather)** — insert — ambiguity — omitted `observed_at` defaults to the current clock instant; a supplied value is unconstrained (may precede the clock or the prior observation); the write also re-derives posture/phase/counters — `routes/projects.py:186-187`
- **§3.1 (project reads)** — revise — ambiguity — single read also refreshes the two set counters and bumps no `version`; the listing re-derives every stored project before applying the filters — `routes/projects.py:127,144-146`
- **§3.1 (set-readiness)** — insert — ambiguity — increments no `version`, neither the project's nor those of the modules whose exposure clocks it advanced — `routes/projects.py:164-167`
- **§3.2 (supersession cascade)** — revise — ambiguity — links 4 & 5 fire only when link 3 actually demoted an `APPROVED` permit; a reverted module's `wip_earned_cents` is recomputed (to 0); the plant bumps `version` only when minutes were actually returned; links 2 and 4 visit rows `created_at` ascending — `services.py:379,385-397`
- **§3.3 (filing)** — insert — ambiguity — a scope/track violation is `ERR_INVALID_REQUEST` at rank 3, evaluated before body `project_id` existence — `routes/permits.py:47-51`
- **§3.3 (decisions)** — insert — ambiguity — `expires_at` is honoured on `START_REVIEW`/`ISSUE_CONDITIONS`/`APPROVE`, ignored on `DENY`; omission never clears an existing expiry — `routes/permits.py:177,189,199,203-208`
- **§3.4 (station-progress)** — revise — ambiguity — completed the `wip_earned_cents` recompute-trigger list (takt release incl. cascade-driven, first inspection record, hold arrival, hold clearance) — `services.py:224`, `routes/modules.py:318`, `routes/inspections.py:100,201,243`
- **§3.5 (QC-hold cascade)** — revise — mismatch — the reset list was presented as exhaustive but omitted two fields; `route_survey_state` is rebuilt from scratch (so a `COMPLETED` survey is discarded), and `survey_completed_at`/`escort_confirmed` are cleared with it — `services.py:334-348`
- **§3.6 (cancel)** — revise — mismatch — added `escort_confirmed`->false and `survey_completed_at`->null to the wholesale reset list — `services.py:346-348`
- **§3.7 (exposure)** — revise — ambiguity — "whole minutes" pinned as truncated downwards, both in the live-`SET` and frozen-`CONNECTED` arms — `calc.py:180`
- **§3.9 (milestone basis)** — insert — ambiguity — `qc_status` `HOLD` does not remove a module from the `MILESTONE_SET` basis (contrast with the WIP basis and §3.5's "leaves the basis entirely") — `services.py:255-260`
- **§3.9 (DRAFT refresh)** — revise — mismatch — the refresh covers `basis_module_count` too (PRD named only two fields), and bumps no `version` — `services.py:272-282`
- **§4 (clock row)** — revise — mismatch — row claimed the sweep "expires transport and building permits"; impl sweeps only `PermitRecord` rows, never a shipment's `permit_expires_at` (tested only at dispatch) — `services.py:432-441`

Already-pinned subjects confirmed by pass 2 (abridged): all 11 calculations verified constant-by-constant and rounding-site-by-rounding-site — envelope-class ladder with strict-`>` ceilings, station-progress and milestone WIP variants, effective takt +5/concurrent module, compatibility score weights 8/5/10 with clamp at 0 and the inclusive 70 freeze boundary, chart lookup "smallest radius >= requested", wind derate at `>= 20` mph with floor-to-pound, the integer cross-product 85% gate vs the display-only 2dp utilization, widest-envelope ordering with empty-load `STANDARD`, the 25,000-cent base fee x states x {0,2,5}, the escort rule, the 100/50/25/0 presumption table, evidence weights 6/3/2 and 4/3/2 with `severity_max >= 3` and the both-zero 50.00 fallback, and the shared tail's exact-complement / rounded-factory-then-remainder-field split. Plus: the 10-entry not-found map and body-FK resolution order, `_live` expiry semantics, all six posture branches in order, all six phase branches, both module counters, `draw_basis` selection sets with per-module rounding before summing, the deposit-vs-milestone request rule, shipment aggregate recomputation, `release_slot` ledger conservation, the `qc_hold_cascade` link set, and `sweep_clock` expiry at `<=`. For the front-half routes: every role list matched against §4 rows, both `ERR_DUPLICATE_CODE` sites at rank 73, every field bound/default (shift 0–1439 / 1–1440 with 360/1080 defaults, `deposit_pct` exclusive-0..1, `retainage_pct` 0..exclusive-1, buffer default 45, exposure limit exclusive-0 default 8.0, precip 0–100), design create's 3->5->9->86 ordering and all three `ERR_INVALID_SUPERSESSION` conjuncts, submit's 39-before-40, review's 8-before-41 three-part freeze gate, decide's 7->54 with per-decision windows, `max(1, conditions_count)`, `INSIGNIA` -> `insignia_count_issued = planned_module_count`, and the deliberate absence of ownership checks where §2.6 rank 6 does not list the operation. One unreachable arm noted: `recompute_shipment_aggregates`' `REQUIRED`->`NOT_REQUIRED` backward transition cannot fire from its only caller.

### Pass 3 — routes/{modules,inspections,shipments,claims,draws}.py

Size: 121,718 -> 131,701 chars (+9,983; 476 lines throughout). **21 ambiguity-pins, 5 mismatch-revisions.**

Mismatch-revisions:
- **§2.6 rank 3** — revise — mismatch — blank-string rejection list extended to the two required narratives `description` and `dispute_note`, and the reason/note fields that do accept `""` named explicitly — `routes/claims.py:28,164` vs `validate.py:97,103`
- **§2.9** — revise — mismatch — `defect_count_factory`/`defect_count_field` are tallies of adjudicated responsibility (FACTORY/FIELD; SHARED increments neither, never walked back, re-adjudication increments again), not counts of claims by `discovered_phase` — `routes/claims.py:152-156`
- **§3.4** — revise — mismatch — `wip_earned_cents` trigger list corrected: not recomputed on delivery, set execution or connection closeout; is recomputed on every recorded inspection result — `routes/shipments.py:277-285`, `routes/modules.py:512-519,577-580`, `routes/inspections.py:201`
- **§3.5** — revise — mismatch — a second `FINAL_FACTORY` record may be opened against a module already `RELEASED`; only recording is gated on `IN_PROGRESS`/`CONDITIONAL_RELEASE` — `routes/inspections.py:40-64,169-176`
- **§3.5** — revise — mismatch — `hold_authority` is not a precondition and has no error code: a `FAIL` from an agency without it is fully persisted on the record while `hold_state`, `qc_status`, the cascade and the module `version` all stay put — `routes/inspections.py:191-198`

Ambiguity-pins:
- **§2.5** — insert — two body FKs resolve in declared order (project->package, module->agency, module->inspection, project->agency) — `modules.py:93-94`, `inspections.py:30-31`, `claims.py:33-36`, `draws.py:30-31`
- **§3.4** — insert — a module listing refreshes `exposure_open_hours` on every row it scans, before filtering, with no version move — `modules.py:196-197`
- **§3.4** — insert — claiming a takt slot re-derives the project's fields but does not bump the project `version` (asymmetric with release, which does) — `modules.py:290` vs `:320-321`
- **§3.4** — insert — the three advance cases overlap: a single advance off `SLOTTED` reaching `station_count` is both first and terminating, and bumps the project `version` — `modules.py:346,363,367-368`
- **§3.5** — insert — omitted `defect_count`/`severity_max` overwrite with 0 while an omitted `corrective_note` is not written — `inspections.py:178-182`
- **§3.5** — insert — recording on an `IN_PLANT` record writes no module row at all — `inspections.py:205-206`
- **§3.5** — insert — the QC-hold unload re-derives the project in place with no version move — `inspections.py:207-208`
- **§3.6** — insert — inverted planned instants are `ERR_INVALID_REQUEST` at rank 3, before `project_id` resolution; neither instant is clock-constrained — `shipments.py:37-41`
- **§3.6** — insert — `load-module` returns the shipment in `data`, not the module — `shipments.py:175`
- **§3.6** — insert — `survey_completed_at` carries no window constraint — `shipments.py:182,216`
- **§3.6** — insert — `departed_at`/`arrived_at` validated then discarded — `shipments.py:227,263`
- **§3.6** — insert — delivery re-derives the project but does not bump its `version`, unlike dispatch — `shipments.py:281-285` vs `:252-255`
- **§3.7** — insert — `pick_radius_ft` and `rigging_weight_lb` are integers >= 0 — `modules.py:381-382`
- **§3.7** — insert x2 — an unplanned lift falls out at rank 61 as `ERR_PICK_RADIUS_OFF_CHART` (no distinct check exists), and nothing requires the clock instant to be inside the pick window — `modules.py:451-453`
- **§3.7** — insert — `execute-set` overwrites `crane_utilization_pct` from the re-check and leaves the four planned pick fields intact — `modules.py:514`
- **§3.7** — insert — the phase/posture re-derivation also runs on package creation, permit decisions, draw certify/fund/reject, the QC-hold unload, the set permit gate, and every project read/list/set-readiness — 12 further `refresh_project` callsites
- **§3.9** — insert — a new draw's four certification amounts start at 0, not null — `draws.py:70-73`
- **§3.9** — insert — a read or listing never refreshes a `DRAFT` basis — `draws.py:87-88`
- **§3.9** — insert — the certifying agency's accreditation/jurisdiction is never re-examined at certification — `draws.py:117-128`
- **§3.9** — insert x2 — both Step 8 deferred items (verdicts below) — `draws.py:161-176`
- **§3.9** — insert — the payload `funded_at` is discarded despite the name collision with the stored stamp — `draws.py:184,195`

Verdicts on the two Step 8 deferrals, both resolved in favour of the implementation:
1. **`certify` overwriting `basis_module_count` / `basis_earned_cents` / `requested_cents`** (`draws.py:161-170`) — PRD-silent. §3.9 now states that certification writes the re-run figures back over the provisional basis one last time: the count from the re-run, `basis_earned_cents` equal to `certified_basis_cents`, and `requested_cents` recomputed from it by the creation-time deposit-or-full rule — so a certified draw's ask agrees with what was certified rather than preserving the lender's estimate. The existing sentence tying the three fields to the refresh events is left standing and now explicitly scoped to `DRAFT`.
2. **`certify` calling `services.refresh_project()`** (`draws.py:175`) — PRD-silent, pinned as observationally inert: §3.9 now says the project's `phase`, `permit_posture` and counters are re-derived in the same write, that none of them can move (certification touches no module, permit or shipment), and that the project `version` increments because `wip_certified_cents` moved rather than because of the re-derivation. The §3.7 phase-derivation trigger list was extended to name certification, funding and rejection so the two statements agree.

Already-pinned subjects confirmed by pass 3 (abridged): module create payload/defaults/uniqueness/envelope-class ladder and initial row; the rank-44/45/46/47/48 state gates and their full ordering against ranks 60–93 on every module action; line-capacity instantaneous count over the half-open interval; congestion takt and `line_slot_minutes`; release-line-slot ledger conservation; intermediate/terminating advance draw-basis refresh scope; the buffered closed-interval crane exclusivity and its exclusion set; the rank-63 cross-module exposure scan; rank-64 posture set, rank-67 sequence rules under both policies, rank-85 pinned-package; close-connections weather disjunction, mated-pair rule, rank-93 sign-off, and the `ADJUDICATED`->`CLOSED` claim sweep with per-claim version bumps; inspection create gates 46/72/81/82 and the `PENDING`->`IN_PROGRESS` flip; clear-hold field resets and both rank-56/81 arms; shipment create initial row and filters; load-module ranks 4/5/10/38/49/65/66/71/89; envelope/fee/escort recomputation and the survey axis in both directions; route-survey gates 50/75/79; dispatch gates 51/79 and module fan-out; cancel gate 53; claim create defaults and rank-88; both allocation variants with the shared tail and post-allocation counter timing; dispute gates 57/58/59; draw `draw_index` contiguity over all recorded draws, both basis selections, per-module-first rounding, the ceiling-then-substance fiscal order, and reject's ledger reversal leaving `certified_basis_cents` standing.

### Final consistency check (pass 3, re-verified independently by the orchestrator)

- `wc -l -c workspace/PRD_COMPLETED.md` = **476 131701** (source `PRD_FINALIZED.md` was 476 / 112,767 — char-delta **+18,934**, +16.8%; line count deliberately unchanged because every edit was an in-paragraph insert or revision).
- Totals across the three passes: **42 ambiguity-pins, 11 mismatch-revisions** (53 changes).
- md5 `e7e6d92ccaffc46e4af57d2c5b8e5444` differs from `PRD_FINALIZED.md`'s `3d999651e0f470cdf2e0fc33d51cccb6`; a word-level diff shows 3,058 changed tokens, so the scan demonstrably ran rather than emitting a copy.
- All five top-level sections present at lines 3 / 11 / 165 / 335 / 398; §4 endpoint table still 56 rows; §5 error table still **73** rows with 73 unique ids; document ends at a real section boundary (`| ERR_DRAW_SEQUENCE_GAP | 409 |`), not mid-sentence.
- `implementation/`, `test_suite/` and `test_helpers/` were not modified by Steps 8 or 9, so the eight `results.{1..8}.json` files (266/266 each) remain the valid evidence for the delivered code.

**PIPELINE COMPLETE.**
