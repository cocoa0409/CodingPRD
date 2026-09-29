# Worklog — task_2732_airline_schedule_filing_slot_compliance

## Step 1: Create task directory — 2026-09-04T13:06:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2732_airline_schedule_filing_slot_compliance` and its `workspace/` subdirectory. Index 2732 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate Scaffold — 2026-09-04T14:56:00.000Z

All three scaffold artifacts are complete and the linter is clean.

**Output directory** — `/home/ubuntu/github/CodingPRD/tasks/task_2732_airline_schedule_filing_slot_compliance/`
```
SCAFFOLD.yaml                   3344 lines  (190 KB)
SCAFFOLD_DIFFICULTY_DESIGN.yaml 2443 lines  (174 KB)
SCAFFOLD_CORNER_DESIGN.yaml     3388 lines  (222 KB)
```
All three parse with `yaml.safe_load`; `SCAFFOLD.yaml` top-level keys are `scenario, domain_name, api_prefix, response_envelope, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles, segregation_of_duties_rules` (no design keys), and each design file has exactly its single required top-level key.

**Lint verdict (verbatim, final run)**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    58
  §1.1 entities declared:     12
  §1.8 instances scanned:     22
  §1.9 instances scanned:     50
  Calls scanned (§1.8+§1.9):  781

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Scaffold counts (§1.0–§1.7)**
- 12 entities: Carrier, Station, Season, Aircraft, ScheduleVersion, FlightLeg, SlotHolding, SlotUtilizationRecord, SlotTransaction, FilingSubmission, RouteAuthority, PassengerNotificationObligation
- 10 state machines / 57 transitions (FlightLeg cyclic SLOT_BACKED→FILED→REFILE_REQUIRED→SLOT_BACKED; ScheduleVersion has two parallel dimensions filing_status + compliance_state)
- 2 concurrency rules (`schedule_version_supersede_occ`, `slot_transaction_propose_occ`), 8 calculations, 67 validations (priorities 1–80), 58 endpoints (32 POST, 25 GET, 1 PATCH), 67 error ids, 6 roles, 2 segregation-of-duties rules

**§1.8 difficulty design** — 9 rule_id blocks, 22 instances, all with full recipes: dual_variant_calc 2, combinatorial_formula 2, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 3, compensating_invariant 3.

**§1.9 corner design** — all 9 breadth sections, 73 instances (50 full recipes + 23 `excluded_because` stubs, every stub citing an existing §1.8 instance by `rule_id / name` and carrying no `test_recipe`): entities 14/14, state_machines 14 (9 recipes), calculations 13 (6), validations 13 (8), endpoints 6 (5), errors 3 (2), rbac 4 (4), cross_cutting_complexity_layers 4 (1), consistency_model 2 (1). All 95 instance names are globally unique across both design files.

**Two SCAFFOLD.yaml consistency fixes made while authoring the last sections** (found by cross-checking assertions against §1.1/§1.3, not by looking at any sibling task):
- `ScheduleVersion.unslotted_leg_count` was defined as `status == REFILE_REQUIRED` only, while the whole design corpus (and the calculation's own worked examples) counts any non-CANCELLED leg missing a member of `required_slot_set(leg)`. Broadened the field description, the `schedule_compliance_score` formula, and the SLOT_BACKED→ASSIGNED retime side-effect note that claimed the counter does not move.
- `ScheduleVersion.leg_count` was defined as excluding CANCELLED legs, contradicting the POST-leg side effect ("increments leg_count") and several assertions; it is now explicitly a monotone manifest count including cancelled legs, with a note that every other counter on the entity excludes CANCELLED.

## Step 3: Copy Shared Files — 2026-09-04T14:57:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T15:20:00.000Z

PRD generation is complete.

## Output
`workspace/PRD.md` — 500 lines / 121628 bytes, built with one `Write` plus nine quoted-heredoc `cat >>` appends (each ≤ ~35 lines of long-form prose), then two small `Edit` corrections. No single write approached the output cap.

## Structure
§1 Introduction; §2 Global Specifications with 11 subsections (2.1 Actors/RBAC, 2.2 Response Structure verbatim, 2.3 Pagination, 2.4 Identity/Timestamps/Versions, 2.5 Logical Clock, 2.6 Precision & Conserved Ledgers, 2.7 OCC, 2.8 Segregation of Duties, 2.9 Rejection Precedence, 2.10 Re-derivation & Cascade Depth, 2.11 Enumerations); §3 Business Logic with 9 subsections (3.1 Reference Data, 3.2 Season Calendar, 3.3 Fleet/Rotation/Maintenance, 3.4 Schedule Version & Legs, 3.5 Slot Holdings & Utilization, 3.6 Exchanges & Transfers, 3.7 Compliance Gate, 3.8 Filing/Codeshare/Charges, 3.9 Notification Obligations); §4 Endpoint table; §5 Error table. Ends at §5 as required.

## Required confirmations
- **Endpoints: 58 / 58.** Mechanically diffed — the §4 table has exactly 58 data rows, every `(method, path)` matches the scaffold with zero missing and zero extra, and every row's Authorized Role(s) column matches the scaffold `roles` list exactly.
- **Entities: 12 / 12** — all covered in §3 (Carrier, Station, RouteAuthority, Season, Aircraft, ScheduleVersion, FlightLeg, SlotHolding, SlotUtilizationRecord, SlotTransaction, FilingSubmission, PassengerNotificationObligation).
- **Error IDs: 67 / 67** in the §5 table, and all 67 also appear in §2/§3 prose. Zero invented error IDs.
- **State machines: 10 / 10** — Season.status, Carrier.status, ScheduleVersion.filing_status, ScheduleVersion.compliance_state, FlightLeg.status, SlotHolding.holding_status, SlotTransaction.status, FilingSubmission.status, RouteAuthority.status, PassengerNotificationObligation.status. Every state value of every machine appears in the PRD.
- **Calculations: 8 / 8** — slot_utilization_credit, maintenance_opportunity_minutes, rotation_feasibility_evaluation, notification_compensation_cents, filing_change_charge_cents, schedule_compliance_score, gate_occupancy_load, mct_shortfall_minutes. Every non-precision constant of all eight appears verbatim.
- Also covered: 2 concurrency rules (§2.7), 2 segregation-of-duties rules (§2.8), 6 roles (§2.1), 67 validations (§2.9 ordering + inline in §3).

## Three Hard Contracts
- **Contract 1 (Field-Name Coverage): PASS.** Required set = 139 entity field names + endpoint input identifiers + 12 path params = **156 unique tokens**; **0 missing**.
- **Contract 2 (Rule Coverage): PASS.** All 67 validations reachable via their error IDs in prose with applies-to scoping; all three explicit priority-conflict pairs stated in §2.9 (SEASON_NOT_OPEN > SLOT_RETURN_DEADLINE_PASSED, SCHEDULE_BLOCKED > FILING_CHARGE_BUDGET_EXCEEDED, CURFEW_VIOLATION > ROUTE_AUTHORITY_MISSING); both OCC rules with their 412 error IDs; all cross-entity cascades including the L1–L5 retime chain, the BLOCKED rejection cascade with its conditional QUEUED exemption, the ARCHIVED/audit cascades, and the EXCHANGE-vs-TRANSFER sibling-branch symmetry; both dual-variant calculations with worked divergence numbers and boundary cases; both pinned rounding orders (per-cabin-then-sum 561132 vs 561131; expedite fee on post-surcharge subtotal 59890 vs 56932).
- **Contract 3 (§3 Path Purity): PASS.** 1090 backticked tokens in §3, **0 violations**. §4 is the sole HTTP contract.
- **§2.2 verbatim: PASS** — byte-identical diff against `section-2.2-response-structure.md`.

## Two corrections made during verification
1. §3.5's attach-slot advance rule was too loose — it implied any leg reaches `SLOT_BACKED` once slotted. Rewritten to state the `assigned_aircraft_id != null` precondition and the three self-loops (`DRAFT→DRAFT`, `ASSIGNED→ASSIGNED`, `REFILE_REQUIRED→REFILE_REQUIRED`), plus the `REFILE_REQUIRED→SLOT_BACKED` unblock effects and the cyclic loop note.
2. §3.7 named a non-existent `ERR_ROTATION_OVERLAP`; corrected to `ERR_ROTATION_CONTINUITY_BROKEN`.

## Deliberately not documented
Nothing. Two presentation choices worth flagging: (a) the `RouteAuthority.weekly_frequency_cap` field description and validation #69 frame the cap's scope slightly differently (per schedule version vs per acting carrier) — documented the validation's framing (the acting carrier's non-cancelled legs on the unordered country pair within the leg's ISO week), since §1.4 validations are the authoritative rule source; (b) `changed_leg_count`'s "frozen at creation" clause and the `RETURNED_IN_TIME` client-forbidden rule are stated as prose invariants rather than as separate error entries.

## Constraints honored
`SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced. No sibling task directory was read.

## Orchestrator truncation check
Independently verified: 500 lines / 121628 bytes; `tail -12` ends on a complete §5 error-table row with trailing newline; §4 table contains exactly 58 method rows and §5 exactly 67 `ERR_` rows; heading scan shows all of §1–§5 present in order. NOT truncated — no regeneration needed.

## Step 5+6 launch note — 2026-09-04T15:22:00.000Z

Orchestrator decision recorded for the record: the Step 5 (unit-test) and Step 6 (implementation) subagents were launched back-to-back in two consecutive orchestrator messages rather than in a single message, so the intended *physical* isolation (impl-gen starting before `test_suite/` exists on disk) was not guaranteed by construction. Compensating control applied: the Step 6 prompt carries an explicit hard constraint forbidding any read, list, grep or glob of `test_helpers/` and `test_suite/`, stating that the PRD is its only behavioral contract. Step 5 was likewise forbidden from reading `workspace/implementation/`. Both agents also carry the anti-truncation chunked-append protocol, the no-broad-pkill rule, and the correct output paths (test dirs at task root, not under `workspace/`).

## Step 6: Generate Implementation — 2026-09-04T16:03:00.000Z

Implementation complete.

## Modules (all under `workspace/implementation/`)

| file | lines |
| --- | --- |
| `start.sh` | 10 |
| `requirements.txt` | 1 (`flask==3.0.3`) |
| `app.py` | 65 |
| `util.py` | 111 |
| `errors.py` | 96 |
| `db.py` | 139 |
| `response.py` | 76 |
| `middleware.py` | 45 |
| `reqval.py` | 261 |
| `calc.py` | 274 |
| `derive.py` | 333 |
| `cascades.py` | 137 |
| `routes/common.py` | 62 |
| `routes/reference.py` | 214 |
| `routes/seasons.py` | 137 |
| `routes/aircraft.py` | 73 |
| `routes/schedule_versions.py` | 184 |
| `routes/flight_legs.py` | 413 |
| `routes/slots.py` | 194 |
| `routes/transactions.py` | 248 |
| `routes/filings.py` | 183 |
| `routes/notifications.py` | 80 |

3336 lines total. Every file passes `python3 -m py_compile`; `__pycache__` removed.

## Endpoint coverage
**58 implemented / 58 documented in PRD §4** — verified by enumerating Flask's url_map (exact one-to-one match with the table, flat paths, no version prefix, `strict_slashes=False`).

## Smoke test (`PORT=21732 bash start.sh`, killed by exact PID both times)
Two full runs against fresh processes, all through HTTP:
- Happy path: carrier/station/season 201 → season OPEN → aircraft → schedule version → flight leg 201 → booking snapshot → assign-aircraft → slot holding 201 → attach-slot (leg reached `SLOT_BACKED`, holding `version` 2, `utilization_pct_as_filed` recomputed) → validate 200 (`VALIDATED`, `CLEAN`, 100.00) → filing submission 201 with the frozen charge (1 leg EXPEDITED → subtotal 4225, fee 1479, total 5704) → transmit rejected on `ERR_CODESHARE_NOT_SYNCHRONIZED`, then codeshare-ack → transmit 200 (version `FILED`, accrued 5704) → acknowledge → retime (leg `REFILE_REQUIRED`, obligation raised with `compensation_cents` 561132 exactly matching the PRD's 3/7/41 ADVISORY worked example) → dispatch → clock advance → close → slot-audit → archive.
- Negative/precedence path: verified `ERR_CURFEW_VIOLATION` (and the waiver bypass), `ERR_FREQUENCY_CAP_EXCEEDED`, `ERR_SLOT_SERIES_CONFLICT`, `ERR_SLOT_STATION_MISMATCH`, `ERR_SLOT_CARRIER_MISMATCH`, `ERR_SCHEDULE_VERSION_NOT_READY`, `ERR_STALE_SCHEDULE_VERSION` (412), `ERR_HISTORIC_PRECEDENCE_PROTECTED`, `ERR_SELF_TRANSACTION_NOT_ALLOWED`, `ERR_SLOT_ENCUMBERED`, `ERR_SEGREGATION_OF_DUTIES`, transfer execution minting the successor holding for the counterparty with `attached_operations` 0, exchange swapping `carrier_id` in place and clearing encumbrance, `ERR_NOTIFICATION_CHANNEL_INSUFFICIENT`, carrier suspension cascade + `ERR_CARRIER_SUSPENDED`, `ERR_ROLE_NOT_PERMITTED`, 404 by entity type, and `limit`/`offset` rejection. Every one of the 12 collections lists with the correct `meta` block. No 500s and no unexpected envelopes.

## Notes on judgement calls
- Storage is in-memory dicts only; nothing seeded, nothing written to disk. Logical clock defaults to `2026-08-01T00:00:00Z`.
- §2.9 was treated as the arbiter wherever a local narrative disagreed (e.g. `ERR_SEASON_NOT_OPEN` above the slot-return deadline; `ERR_SCHEDULE_BLOCKED` above `ERR_FILING_SUBMISSION_STATE_INVALID` on transmit).
- Uniqueness breaches (carrier IATA/ICAO, station IATA, season code, tail registration, version label per carrier+season) raise `ERR_INVALID_REQUEST` — the catalogue has no uniqueness id.
- Schedule versions are only re-versioned when one of their own counters genuinely moves, matching §3.5's statement that an attach bumps only the leg and the holding.
- Did not read `test_helpers/`, `test_suite/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, any sibling task, or `worklog.md`. `SCAFFOLD.yaml` was consulted only for the FilingSubmission and PassengerNotificationObligation field lists.

## Step 5: Generate Unit Tests — 2026-09-04T17:05:00.000Z

Test suite generation for task 2732 is complete and verified.

## Tests emitted

| Queue | Tests | Design instances translated |
|---|---|---|
| A (Difficulty / §1.8) | **69** | 22 / 22 across all 9 rule_ids |
| B (Corner / §1.9) | **111** | 50 / 50 live instances |
| **Total** | **180** | **72 distinct instances** |

Queue B live-instance coverage by section: entities 14/14, state_machines 9/9, calculations 6/6, validations 8/8, endpoints 5/5, errors 2/2, rbac 4/4, cross_cutting_complexity_layers 1/1, consistency_model 1/1.

## Instances skipped

**Zero live instances skipped.** No instance failed the PRD-first two-condition filter. The 23 `excluded_because:` stubs in `SCAFFOLD_CORNER_DESIGN.yaml` (state_machines 5, calculations 7, validations 5, endpoints 1, errors 1, cross_cutting 3, consistency 1) are stubs by design and were not translated. Queue A has no stubs.

## Files (line counts)

`test_helpers/` — 2797 lines: `__init__.py` 53, `api_client.py` 299, `api_errors.py` 186, `assertions.py` 543, `constants.py` 92, `factories.py` 203, `fixtures.py` 924, `test_users.py` 80, `types.py` 417.

`test_suite/` — 7890 lines: `conftest.py` 60, `test_01_dual_variant_calculations.py` 235 (5 tests), `test_02_combinatorial_formulas.py` 307 (6), `test_03_non_linear_state_machines.py` 488 (9), `test_04_transitive_cascades.py` 298 (8), `test_05_rejection_precedence_pairs.py` 359 (9), `test_06_boundary_precision.py` 255 (6), `test_07_cross_entity_state_dependency.py` 278 (6), `test_08_resource_temporal_overlap.py` 482 (9), `test_09_compensating_invariants.py` 385 (11), `test_10_corner_entities.py` 864 (23), `test_11_corner_state_machines.py` 807 (23), `test_12_corner_calculations.py` 598 (13), `test_13_corner_validations.py` 800 (18), `test_14_corner_endpoints.py` 643 (13), `test_15_corner_errors.py` 283 (6), `test_16_corner_rbac.py` 476 (11), `test_17_corner_cross_cutting.py` 272 (4).

## Automated verification (all clean)

Every file compiles; every test function has exactly one `Design:` line and it is the last docstring line; every tag resolves to a verbatim `name:` in the correct source yaml (no dual tags, no dangling tags); zero non-verbatim PRD citations; zero unused imports or unused module constants; timestamps compared through `assert_timestamp_equals` (sub-second-width tolerant); money asserted as integer cents throughout. Nothing was written under `workspace/`, and `workspace/implementation/` was never read.

## Design-index vs PRD discrepancies (PRD followed in every case)

1. `schedule_version_filing_status_and_compliance_state_move_independently` expects `leg_count` 3 after a cancel; PRD does not uniquely derive that — assertion omitted (test_03).
2. `turn_time_boundary_is_inclusive_at_exactly_required_turn_minutes` expects `cumulative_ground_minutes` 46 at TXL, but TXL's preset omits `maintenance_capable` so the PRD default (false) forces 0 — asserted 0 (test_06).
3. `assign_aircraft_answers_each_broken_precondition_with_its_own_error_id` says 409 for `ERR_AIRCRAFT_NOT_IN_SERVICE`; PRD §5 says 422 — 422 used (test_07, test_15).
4. `flight_leg_block_minutes_and_is_international_computed_with_client_input_ignored` expects `unslotted_leg_count` 1 for MUC→LIS; neither endpoint is LEVEL_3, so PRD gives 0 and score 100.00 — asserted 0 (test_10).
5. `compensation_tier_flips_to_mandatory_at_exactly_one_hundred_twenty_minutes` says 422 for `ERR_INVALID_REQUEST`; PRD §5 says 400 — 400 used (test_12).

One sub-assertion omitted: in `cancelled_leg_refuses_every_further_action_endpoint`, the design's attach-slot leg-state guard has no verbatim PRD basis, so the booking-snapshot endpoint was substituted as the third refused action.

## Orchestrator placement check
`test_helpers/` and `test_suite/` are both at the task root; `find workspace -maxdepth 2` shows no stray `test_*` directories under `workspace/`. Independent count of `def test_` across `test_suite/*.py` = 180, matching the subagent's report.

## Step 7: Run Tests and Iterate — 2026-09-04T17:40:00.000Z

All 8 rounds green. Done.

## Summary

**Iterations run:** 2 (each a full 8-round concurrent sweep under `setsid`).

**Tests deleted:** none. Every failing assertion traced to a verbatim PRD sentence and was uniquely derivable, so all 13 were resolved by fixing either the test's mis-translation or the implementation.

**Fixes applied to `test_suite/`** (no `test_helpers/` changes were needed — the bugs were in the assertions themselves, not in fixtures/factories):

1. **String-vs-number percentage assertions (13 assertions across 3 files).** `test_14_corner_endpoints.py` (lines 244, 293, 300, 356, 363, 504, 507, 546), `test_16_corner_rbac.py` (327, 328), `test_17_corner_cross_cutting.py` (206, 208, 248) compared `utilization_pct`, `utilization_pct_as_filed` and `schedule_compliance_score` against string literals (`== "20.00"`). PRD §2.6 verbatim: *"Percentages and scores — the two slot utilization percentages, the schedule compliance score, and the expedite rate percentage — are decimal numbers carried to exactly 2 decimal places and returned as JSON numbers, never as strings."* The implementation returning JSON numbers is correct; the assertions were changed to numeric comparisons (`== 20.00`). This makes them *more* faithful — they now also enforce the "never as strings" clause.

2. **`test_11_corner_state_machines.py::TestSeasonOpensAndBumpsItsVersion::test_only_the_open_season_admits_a_new_slot_series`** — asserted `season["version"] == 2` after a slot allocation that had just moved the season's derived `held_series_count` from 0 to 1. PRD §2.4: *"`version` … increments by exactly 1 on every mutation of that row, again including derived-field-only mutations."* Corrected to 3 (verified empirically against a live server).

3. **`test_11_corner_state_machines.py::TestArchivingWaitsForTheAudit::test_the_identical_archive_lands_once_the_audit_has_stamped_the_season`** — asserted `archived["version"] == 4`, forgetting that the audit's own write of `slot_audit_completed_at_utc` + `audit_reference` onto the season row is itself a mutation (PRD §2.4, and §3.2 *"The audit stamps `slot_audit_completed_at_utc` … and records the supplied `audit_reference` on the season."*). Corrected to 5, with an added intermediate assertion that the audit itself carried the counter 3 → 4.

**Fixes applied to `implementation/`:**

1. **`routes/slots.py::create_slot_holding`** — the endpoint had no season-lifecycle or carrier-lifecycle guard at all. Added `require_season_open(season)` then `require_carrier_active(carrier)`, placed in precedence band 7 (above the band-10 `ERR_STATION_NOT_COORDINATED` check). PRD §3.2: *"`OPEN` is the working state: allocating a slot series, opening a schedule version, adding a leg, returning a series, proposing a slot transaction and approving one all require the governing season to be `OPEN`, and are otherwise refused with `ERR_SEASON_NOT_OPEN`."* PRD §3.1: *"any attempt to open a new schedule version, register a tail, allocate a slot series, or propose a slot transaction under that carrier is refused with `ERR_CARRIER_SUSPENDED`."*

2. **`derive.py::blocked_cascade`** — when a version entered `compliance_state` `BLOCKED` and its live submission was internally rejected, `filing_status` was left at `FILED`. It now steps `FILED → VALIDATED` alongside the leg step-back. Derived from PRD §2.10 (*"When a version returns from filed to validated, its legs that are currently filed move back to slot-backed while legs that have already fallen into refile-required are skipped entirely"*) and §3.5 (*"the whole `SLOT_BACKED` → `FILED` → `REFILE_REQUIRED` → `SLOT_BACKED` loop may be traversed any number of times within a single season"*, which requires the version to be re-fileable). This single fix cleared 3 failures: the `assert 'FILED' == 'VALIDATED'` in `test_04`, plus both `test_03::TestFlightLegCycle` setup failures where the second lap's `queue_submission` was rejected with `ERR_SCHEDULE_VERSION_STATE_INVALID`.

**Final sweep, per-round passed/total:** round 1 = 180/180, 2 = 180/180, 3 = 180/180, 4 = 180/180, 5 = 180/180, 6 = 180/180, 7 = 180/180, 8 = 180/180. Union of failures across all 8 rounds: empty. No flakiness observed in either iteration — both sweeps produced byte-consistent failure sets across all 8 rounds, so no load-induced noise had to be discounted.

`worklog.md` was not touched by the subagent. The 8 `results.*.json` files remain in `workspace/implementation/` for verification.

## Orchestrator verification of the sweep artifacts
Independently confirmed before Step 8: all 8 `workspace/implementation/results.$i.json` exist, share one mtime (17:27:52 — a genuine single concurrent sweep), and each reports `passed == total == 180`. Step 7 made non-zero `implementation/` fixes, so Step 8 is NOT skipped.

## Step 8: Finalize PRD — 2026-09-04T17:43:00.000Z

Done. Only two lines changed, both tracing to the single Step 7 `implementation/` fix in `derive.py::blocked_cascade`.

## Line counts
- `PRD.md`: 500 lines / 121,628 bytes
- `PRD_FINALIZED.md`: 500 lines / 122,310 bytes (0.00% line delta, +0.56% bytes)
- Tail verified: still ends on `| ERR_FILING_CHARGE_BUDGET_EXCEEDED | 402 |`, the last row of the §5 error table.

## Changes
- **§3.7 (line 317, the BLOCKED-entry cascade)** — insert — pinned that when the blocked cascade rejects at least one `TRANSMITTED`/`ACKNOWLEDGED` submission and the version's own `filing_status` is `FILED`, the version steps back `FILED → VALIDATED` alongside its legs; a version in any other `filing_status` keeps it, and `validated_by_user_id` is untouched either way — `implementation/derive.py:285-286` (guarded by `rejected_any`), leg step-back at `derive.py:287-290`.
- **§3.7 (line 315, `compliance_state` as an independent dimension)** — revise — softened the absolute claim "moves freely in both directions **without `filing_status` changing at all**" to "in the general case … the one exception being the drop into `BLOCKED` described below, whose rejection cascade can step a `FILED` version back to `VALIDATED`" — same impl site, `derive.py:285-286`.

## Per-edit pre-edit search log

**Edit 1 (§3.7 line 317)**
- (a) Subject: writes to a schedule version's `filing_status`, specifically during the compliance-posture cascade, plus the `rejected_any` / `FILED`-only preconditions.
- (b) Enumerated every `filing_status` write and read via `grep -rn "filing_status"`: `derive.py:285-286` (blocked cascade — the only cascade writer); its sole caller `derive.py:243-258` (`recompute_version`, run for every version on every request via `recompute_all`); `routes/filings.py:140` (transmit `VALIDATED → FILED`), `filings.py:176-177` (downstream ack-REJECT `FILED → VALIDATED`), `filings.py:47` (queue requires `VALIDATED`); `routes/schedule_versions.py:50, 114-116, 135, 165, 178` (create `DRAFT`, fork → `SUPERSEDED`, validate `DRAFT → VALIDATED`, withdraw gate); `cascades.py:99-101` (`withdraw_version` → `WITHDRAWN`) and its second caller `routes/reference.py:73` (carrier suspension); `routes/flight_legs.py:162` (leg creation requires `DRAFT`). Also checked `db.py:91-115` (`mark`/`flush`) to confirm one `version`/`updated_at` bump per row per request.
- (c) Adjustment: `routes/flight_legs.py:244-295` (retime) and `:383-394` (cancel) carry no version-state guard, so a `SUPERSEDED` or `WITHDRAWN` version's leg can still be churned into `BLOCKED`; `derive.py:285` leaves those statuses alone. Added the explicit "a version whose `filing_status` is anything other than `FILED` keeps it unchanged" clause instead of an unconditional step-back, and conditioned on "has rejected at least one submission" to mirror `rejected_any`. Also added "`validated_by_user_id` is left exactly as it stands" because nothing in `blocked_cascade` clears it and §3.8's transmit segregation check (`filings.py:124`) still reads it on the re-file attempt.

**Edit 2 (§3.7 line 315)**
- (a) Subject: the PRD's universal claim that `compliance_state` movement never changes `filing_status`.
- (b) Same enumeration as Edit 1, plus a read of `derive.py:199-291` end-to-end to confirm `blocked_cascade` is the only posture-driven writer and that `flag_resync` (`derive.py:265-270`) touches only `resync_required`.
- (c) Adjustment: scoped the exception narrowly to the drop into `BLOCKED` rather than deleting the independence claim, so `WARNED↔CLEAN` and `BLOCKED → WARNED/CLEAN` recoveries are still correctly described as not moving `filing_status`.

## Items deliberately left verbatim
- **Percentages as JSON numbers** (13 test assertions): PRD §2.6 already states it verbatim, including "never as strings"; `calc.pct` conforms. Pure test bug.
- **Season `version` counters (=3 after allocation, =5 after archive)**: §2.4, §3.5 and §3.2 uniquely determine both numbers; `db.flush` bumps exactly once per row per request. Pure test bugs.
- **`create_slot_holding` lifecycle guards**: §3.2, §3.1 and §2.9 band 7 already pin the checks and their precedence exactly as `routes/slots.py:97-102` now implements them. This was an implementation bug brought into line with the PRD, not a PRD silence, so no edit.

## Step 9: Complete PRD — orchestrator partitioning decision — 2026-09-04T17:48:00.000Z

Step 9 was run as **three sequential module-partitioned passes over one shared `workspace/PRD_COMPLETED.md`**, not as a single subagent. Rationale: `implementation/` is 3336 lines across 22 modules, and a single agent asked to walk all of it exhaustively reliably under-covers the later modules or emits a byte-identical copy of its input. Pass 1 performed the `cp PRD_FINALIZED.md PRD_COMPLETED.md`; passes 2 and 3 were explicitly forbidden from copying and edited in place. Each later pass was handed the earlier passes' change list and borderline-but-pinned list so it would not duplicate or re-litigate settled edits. Partition:
- Pass 1 — `app.py`, `util.py`, `errors.py`, `db.py`, `response.py`, `middleware.py`, `reqval.py`, `routes/common.py`, `routes/reference.py`, `routes/seasons.py`, `routes/aircraft.py`
- Pass 2 — `calc.py`, `derive.py`, `cascades.py`, `routes/schedule_versions.py`, `routes/flight_legs.py`
- Pass 3 — `routes/slots.py`, `routes/transactions.py`, `routes/filings.py`, `routes/notifications.py`

### Step 9 pass 1 (foundation modules) — result

Pass 1 complete. Verified: 500 lines preserved, ends on `| ERR_FILING_CHARGE_BUDGET_EXCEEDED | 402 |`, no truncation, no new sections.

**Setup:** `cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` performed as the first action.
**Line counts / delta:** 500 lines / 122,310 chars → 500 lines / 129,287 chars (+6,977). 23 lines changed.
**Counts:** 17 ambiguity-pins, 6 mismatch-revisions.

Changes:
- §2.2 — insert — ambiguity — `api_request_id` is `req_` plus exactly 20 chars from `A-Z0-9` — `util.py:16-20`
- §2.2 — insert — ambiguity — `api_request_timestamp` is real wall-clock, not the logical clock — `util.py:36-37`, `response.py:8-15`
- §2.3 — insert — ambiguity — list ordering ties on millisecond-precision `created_at` broken by insertion order — `db.py:56-58`
- §2.3 — insert — ambiguity — filters are exact-equality/case-sensitive; undeclared query params ignored; enum filters must be declared members else `ERR_INVALID_REQUEST`; bool filters accept only `true/false/1/0` any case — `reqval.py:226-251`, `routes/common.py:11-24`
- §2.4 — revise — mismatch — audit timestamps are wall-clock; a re-derivation to an unchanged value is not a mutation; bump is once per row per request with one shared `updated_at`; creation responses always report `version` 1 — `db.py:71-134`
- §2.5 — insert — ambiguity — `to_iso8601` canonicalised to three fractional digits; the clock is a setter and accepts an earlier instant — `routes/reference.py:202-214`
- §2.5 — insert — ambiguity — authority expiry comparison is strict; expiry is one-way and moving the clock back never restores `ACTIVE` — `routes/reference.py:208-213`
- §2.9 band 3 — insert — ambiguity — absent/empty body = empty object; non-JSON or non-object body = `ERR_INVALID_REQUEST`; explicit `null` == absence; JSON booleans are not integers; undeclared body keys ignored; `Z` mandatory, seconds/fraction optional, stored canonicalised; global-uniqueness collisions land in this band — `reqval.py:47-59,66-150`, `util.py:40-55`
- §2.9 band 4 — revise — mismatch — path-identifier resolution runs ahead of band-3 body-shape validation; only body foreign keys sit after band 3 — `routes/reference.py:63-65,185-187`, `routes/seasons.py:72-74,102-104`
- §2.10 — insert — ambiguity — every write closes by re-deriving the whole world, not just the changed subtree; reads never re-derive — `response.py:43-69`
- §3.1 — insert — ambiguity — carrier designator collision is `ERR_INVALID_REQUEST` — `routes/reference.py:29-33`
- §3.1 — insert — ambiguity — carrier-suspend `reason` is 1–500 chars, validated but never persisted — `routes/reference.py:65`
- §3.1 — insert — ambiguity — duplicate station `iata_code` is `ERR_INVALID_REQUEST`; a station row has no status field — `routes/reference.py:98-113`
- §3.1 — revise — mismatch — authority suspend picks `EXPIRED` vs `SUSPENDED` from the clock, has no state precondition, and may be re-run — `routes/reference.py:182-196`
- §3.2 — insert — ambiguity — `season_code` has no character-class constraint; collision is `ERR_INVALID_REQUEST` — `routes/seasons.py:25,38-40`
- §3.2 — insert — ambiguity — a null `retains_historic_precedence` is treated as false at archival and expires — `routes/seasons.py:91-95`
- §3.2 — insert — ambiguity — `audit_reference` is 1–120 chars; `audited_slot_holding_ids` are in series-creation order — `routes/seasons.py:104,110-114`
- §3.3 — insert — ambiguity — tails start with both maintenance figures at 0; duplicate `registration` is `ERR_INVALID_REQUEST` checked ahead of both FKs; `carrier_id` resolved before `base_station_id`; tail registration is not ownership-checked — `routes/aircraft.py:28-49`
- §4 preamble — insert — ambiguity — trailing slash tolerated on every path — `app.py:22`
- §4 `POST /carriers` — revise — mismatch — "obligation tier" replaced with "home-carrier flag" (no such field exists) — `routes/reference.py:34-41`
- §4 `GET /carriers` — revise — mismatch — dropped the non-existent obligation-tier filter — `routes/reference.py:53-57`
- §4 `GET /stations` — revise — mismatch — added the maintenance-capable filter the impl exposes — `routes/reference.py:125-129`
- §5 intro — insert — ambiguity — `ERR_NOT_FOUND` (404) for an unrouted path and `ERR_METHOD_NOT_ALLOWED` (405) for a wrong method, both outside the domain table — `app.py:42-49`, `errors.py:71-72`

Judged already-pinned but borderline (passes 2/3 told not to revisit): `derive.rotation_view` field set matches §3.3; the rotation-feasibility endpoint is a non-re-deriving raw read; `middleware.authenticate`/`require_ownership`; the §5 status catalogue; `envelope_array`'s `has_more`/`total_count`; `reqval.pagination()` rejecting rather than clamping; unhandled exceptions mapping to `ERR_INVALID_REQUEST`/400 (left unpinned as a non-contractual safety net).

### Step 9 pass 2 (calc / derive / cascades / versions / legs) — result

All 24 pass-2 edits verified in place, document integrity intact.

**No `cp`/overwrite performed.** Pass 1's edits intact — spot-checked the §2.2 `api_request_id` insert and the §4 `GET /stations` maintenance-capable filter. Diff vs `PRD_FINALIZED.md` grew from 88 to 176 lines.
**Size:** 500 lines / 129,287 chars → 500 lines / 141,153 chars (+11,866). Still ends on the §5 last row.
**Counts:** 22 ambiguity-pins, 2 mismatch-revisions (24 edits over 23 lines).

Changes:
- §2.10 — insert — ambiguity — fixed collection order of the closing whole-world sweep (legs, series, tails, submissions, versions, carriers, seasons; creation order within each) repeated to a fixed point — `derive.py:315-338`
- §3.1 — revise — **mismatch** — `weekly_frequency_cap` counts the carrier's legs across every schedule version whatever its `filing_status`; PRD said "a single schedule version" — `flight_legs.py:72-90`
- §3.3 rotation walk — insert — ambiguity — the set is tail-scoped only, so a `SUPERSEDED` version's legs still walk in the rotation — `derive.py:29-33`
- §3.3 three checks — insert — ambiguity — check-major not group-major ordering; offending leg is the later leg of the failing pair for continuity/turn, and the leg that carried the running sum over for the block cap — `calc.py:94-118`
- §3.3 maintenance — insert — ambiguity — a ground interval whose end is at or before its start is discarded before the maintenance-capability test — `calc.py:134-135`
- §3.3 rotation view — insert — ambiguity — `required_turn_minutes` comes from the first two legs of the earliest date group holding ≥2 legs, and is 0 when no consecutive pair exists — `calc.py:85-89`
- §3.4 version creation — insert — ambiguity — `version_label` collision is band-3 `ERR_INVALID_REQUEST` ahead of FK resolution; carrier resolves before season — `schedule_versions.py:73-79`
- §3.4 fork — insert — ambiguity — omitted budget inherits the parent's; label uniqueness excludes the fork's own target; not gated on season `OPEN` or carrier `ACTIVE` — `schedule_versions.py:108-122`
- §3.4 withdraw — insert — ambiguity — `reason` validated but not persisted — `schedule_versions.py:176`
- §3.4 withdraw cascade — insert — ambiguity — raises no `CANCELLATION` obligation and instead waives every `PENDING` one with `CHANGE_REVERTED` — `cascades.py:99-108`
- §3.4 leg creation — insert — ambiguity — 1080-minute cap and same-station endpoints are band-3 `ERR_INVALID_REQUEST` ahead of FK resolution; body FK order (marketing carriers → origin → dest → version → upstream); leg `fleet_type_code` format — `flight_legs.py:141-155`
- §3.4 marketing carriers — insert — ambiguity — own-carrier element is `ERR_INVALID_REQUEST` raised after the version resolves — `flight_legs.py:156-157`
- §3.4 curfew — insert — ambiguity — seconds discarded from the local minute-of-day; start == end is an empty window; the waiver short-circuits before either station is examined — `calc.py:196-205`, `flight_legs.py:33-38`
- §3.4 MCT — insert — ambiguity — cancelling the inbound does not dissolve the connection; the downstream leg keeps its shortfall and keeps counting in `mct_violation_count` — `derive.py:85-88,216`
- §3.4 traffic rights (cabotage) — insert — ambiguity — candidates are authorities naming that one country in either position; the governing authority for the cap is the earliest-created survivor — `flight_legs.py:58-117`
- §3.4 traffic rights — insert — ambiguity — `freedom_type` is consulted only for cabotage; home-domestic legs skip the whole check — `flight_legs.py:93-113`
- §3.4 gate capacity — insert — ambiguity — an interval is bucketed to the UTC date of the movement instant, so cross-midnight intervals are never compared — `calc.py:156-168`
- §3.4 retime — insert — ambiguity — an explicit `null` can never clear `curfew_waiver_reference`; the 1080 cap applies; the season need not still be `OPEN` — `flight_legs.py:248-256`
- §3.4 retime chain — insert — ambiguity — a `PATCH` changing nothing still marks the leg written, bumping `version`/`updated_at` — `flight_legs.py:272-275`
- §3.4 cancel — insert — ambiguity — a cancelled leg keeps `assigned_aircraft_id` and `connects_from_leg_id` — `cascades.py:89-96`
- §3.4 booking snapshot — insert — ambiguity — all three cabin counts mandatory (full replacement); raises and waives no obligation — `flight_legs.py:402-412`
- §3.5 attach-slot — insert — ambiguity — leg must be `DRAFT`/`ASSIGNED`/`REFILE_REQUIRED` else `ERR_FLIGHT_LEG_STATE_INVALID`, ahead of the six series checks; an already-slotted movement is silently overwritten — `flight_legs.py:342-343,373`
- §3.5 attach-slot — insert — ambiguity — time-of-day equality is exact to the fractional second — `flight_legs.py:361-367`
- §3.7 validation — revise — **mismatch** — PRD had `ERR_SCHEDULE_BLOCKED` "last of all" and slot-coverage → rotation → maintenance; impl checks BLOCKED right after readiness, then maintenance, then rotation, then slot coverage. Also pinned that tails are visited in first-referencing-leg order — `schedule_versions.py:144-163`
- §3.7 validation — insert — ambiguity — the re-derivation runs before the `DRAFT` precondition, so even a refused validate has driven the world to its fixed point — `schedule_versions.py:132-136`
- §3.8 codeshare — insert — ambiguity — `codeshare_sync_status` is re-derived on every mutating request for every submission regardless of its own `status`; required set is first-appearance order; a superset ack list is `SYNCHRONIZED` — `derive.py:170-192`

Pass 2's already-pinned-but-borderline list (handed to pass 3 as settled): `attached_operations` counts legs not movements; `at_risk_slot_count` distinctness, score cap/floor, `compliance_state` test order, the filing-charge five steps and `compensation_cents` rounding order pinned verbatim in §3.7/§3.8/§3.9; `flag_resync` fires only on `CLEAN → WARNED`; the `blocked_cascade` leg-vs-`filing_status` asymmetry; a version whose only legs are cancelled validates; fork/validate/retime/cancel/attach not gated on carrier `ACTIVE`; `detach_holding_from_legs` raises no obligation unlike `lose_holding`; error responses never flush pending version bumps.

### Step 9 pass 3 (slots / transactions / filings / notifications) — result — 2026-09-04T18:20:00.000Z

Pass 3 complete.

**Integrity confirmation.** No `cp` or overwrite — every change was an in-place `Edit`. Prior passes verified intact: pass 1's §2.2 `api_request_id` insert (line 55) and pass 2's §3.1 `weekly_frequency_cap` revision "the count is taken across every schedule version belonging to that carrier" (line 181) are both present.

**Size:** 500 lines / 141,153 chars → 500 lines / 152,119 chars. Still ends on `| ERR_FILING_CHARGE_BUDGET_EXCEEDED | 402 |`; no line added or removed.

**Counts:** 21 edits — 12 ambiguity-pins, 9 mismatch-revisions.

Changes:
- §3.5 ¶259 — insert — ambiguity — body-FK resolution order `carrier_id`→`station_id`→`season_id`→`historic_predecessor_holding_id`; predecessor otherwise unconstrained; `ERR_SEASON_NOT_OPEN` and `ERR_CARRIER_SUSPENDED` added as creation preconditions ahead of the coordination/conflict checks — `routes/slots.py:91-98`
- §3.5 ¶263 — insert — ambiguity — the conflict test's time-of-day equality is to full stored precision, and `carrier_id` plays no part in it — `routes/slots.py:28-48`
- §3.5 ¶277 — revise — mismatch — `operation_date` is a full `Z`-suffixed ISO instant, not a bare calendar date — `reqval.py:132-150`, `routes/slots.py:164`
- §3.5 ¶277 — insert — ambiguity — the season-window breach is `ERR_INVALID_REQUEST`, evaluated after the series resolves but ahead of the `HELD` and carrier tests, and skipped when the season is unresolvable — `routes/slots.py:170-174`
- §3.5 ¶277 — revise — mismatch — **no cascade anywhere synthesises a utilization record**, so `RETURNED_IN_TIME` never appears on a stored row and `recorded_by_user_id` is always the acting `X-User-ID` (the "literal `system`" claim was unimplementable) — `routes/slots.py:159-187`
- §3.5 ¶279 — insert — ambiguity — the record carries no `updated_at` either, only `created_at` — `routes/slots.py:186` (`versioned=False`), `db.py:71-80`
- §3.5 ¶281 — revise — mismatch — return preconditions reordered to the real order: season `OPEN` → `HELD` → encumbered → deadline; deadline comparison is strict; unresolvable season fails as not-open — `routes/slots.py:137-145`
- §3.6 ¶287 — revise — mismatch — proposal preconditions reordered: season `OPEN` first, then `HELD`, then encumbered — `routes/transactions.py:80-84`
- §3.6 ¶287 — insert — ambiguity — the `response_deadline_utc` breach is `ERR_INVALID_REQUEST`, tested ahead of ownership/OCC/season/state, skipped when the season is unresolvable; body-FK order pinned — `routes/transactions.py:69-74`
- §3.6 ¶287 — insert — ambiguity — the counter series need not be `HELD`, unencumbered, or co-located/co-seasonal/co-movement, and the counterparty need not be `ACTIVE` — `routes/transactions.py:87-91`
- §3.6 ¶291 — insert — ambiguity — `rejection_reason` alongside `ACCEPT` is ignored; neither the respond gate nor withdrawal re-checks the season or the holdings' state — `routes/transactions.py:136-175`
- §3.6 ¶293 — insert — ambiguity — `denial_reason` alongside `APPROVE` is ignored, so an executed transaction always carries a null `decision_reason` — `routes/transactions.py:212,234-240`
- §3.6 ¶297 — insert — ambiguity — the minted successor also copies `movement_type`, takes every other field at the §3.5 fresh-series default with `version` 1, is never encumbered, and runs no conflict re-test — `routes/transactions.py:183-193`, `routes/slots.py:51-74`
- §3.8 ¶325 — insert — ambiguity — queuing re-derives the whole world before reading `filing_status` (so a refused queue still fires cascades); `VALIDATED` is the sole precondition; many submissions may coexist per version — `routes/filings.py:45-50`
- §3.8 ¶333 — insert — ambiguity — codeshare-ack requires only that the carrier resolve: a `PartnerCarrier` need not name itself and no ownership rule applies; a repeat ack leaves the list unchanged yet still bumps `version`/`updated_at` — `routes/filings.py:94-108`
- §3.8 ¶335 — revise — mismatch — transmit's gate stack reordered so `ERR_SCHEDULE_BLOCKED` precedes `ERR_FILING_SUBMISSION_STATE_INVALID` (matching §2.9 band 8, which the §3.8 narrative contradicted), plus the up-front re-derivation and its side effects on a refused transmit — `routes/filings.py:118-123`
- §3.8 ¶335 — insert — ambiguity — the `STANDARD` window comparison is strict, skipped when the season is unresolvable, and no gate requires the season to be `OPEN` — `routes/filings.py:128-131`
- §3.8 ¶337 — revise — mismatch — transmit assigns `filing_status = FILED` unconditionally, not as a guarded `VALIDATED → FILED`; a submission queued before its version was superseded still drives it to `FILED` — `routes/filings.py:140`
- §3.8 ¶339 — insert — ambiguity — acknowledgement has no SoD, compliance, season or ownership gate and does not re-derive up front — `routes/filings.py:150-161`
- §3.8 ¶339 — revise — mismatch — the charge reversal is unconditional but the `FILED → VALIDATED` step is guarded on the version actually being `FILED` — `routes/filings.py:173-178`
- §3.9 ¶347 — insert — ambiguity — the "no obligation owed" refusal comes after the leg resolves; the leg's `status` and owner are never consulted; `change_magnitude_minutes` is used verbatim for every `trigger_kind` — `routes/notifications.py:28-31`
- §3.9 ¶359 — insert — ambiguity — `regulator_reference` is 1–120 characters — `routes/notifications.py:62`
- §3.9 ¶361 — insert — ambiguity — a hand-raised obligation records no pre-change times, so the times-restored waiver can never fire for it; only a version withdrawal waives it — `routes/notifications.py:32-35`, `cascades.py:56-63,107-108`
- §4 table (slot-holdings list) — revise — mismatch — added the undocumented `historic_precedence` filter — `routes/slots.py:127`
- §4 table (filing-submissions list) — revise — mismatch — added the undocumented `codeshare_sync_status` filter — `routes/filings.py:87`

**Pass 3 closing assessment.** Scope exhausted within its four modules: every endpoint's full band sequence, every guard, every state assignment, every default, every response field and every list filter walked against the PRD prose. Residual unedited items were either pre-adjudicated by earlier passes or already determinate from §2.9's band tables plus a named error id. Two substantive (not cosmetic) mismatches worth flagging for downstream consumers of this task: (a) the PRD described a return cascade synthesising `RETURNED_IN_TIME` utilization records that does not exist anywhere in the implementation; (b) transmit's unconditional `filing_status = FILED` write is reachable from a superseded version because `supersede` does not raise `ERR_FILING_IN_FLIGHT` the way `withdraw` does.

## Step 9 final orchestrator verification — 2026-09-04T18:22:00.000Z

- `PRD.md` 500 lines / 121,628 B → `PRD_FINALIZED.md` 500 lines / 122,310 B → `PRD_COMPLETED.md` 500 lines / 152,119 B.
- `cmp PRD_FINALIZED.md PRD_COMPLETED.md` → **differs** (the scan genuinely ran; not a byte-identical copy). `diff` reports **63 changed lines** across the three passes (23 + 23 + 21 edit sites, some sharing lines).
- `PRD_COMPLETED.md` ends on the last row of the §5 error table with a complete line; 28 headings present, same section skeleton as `PRD.md`; no new sections, no line-count drift.
- Total Step 9 edits: **68** (23 pass 1 + 24 pass 2 + 21 pass 3) = 51 ambiguity-pins + 17 mismatch-revisions.
- Implementation untouched by Steps 8–9: newest `implementation/*.py` mtime (1788542435) predates `results.1.json` (1788542872), so the green 8×180/180 sweep from Step 7 still describes the code as it stands.

**PIPELINE COMPLETE.** All nine steps finished; `workspace/PRD_COMPLETED.md` written.
