# Worklog — task_2746_hotel_housekeeping_labor_room_attendant_workload

## Step 1: Create task directory — 2026-09-04T15:24:42.524Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2746_hotel_housekeeping_labor_room_attendant_workload` and its `workspace/` subdirectory. Index 2746 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no index was auto-allocated (32 pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-04T17:10:28.541Z

Scaffold for task 2746 is complete and lint-clean.

**Output files** (all parse as YAML; `/home/ubuntu/github/CodingPRD/tasks/task_2746_hotel_housekeeping_labor_room_attendant_workload/`):
- `SCAFFOLD.yaml` — 2815 lines, 149 KB. Top-level keys only: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles (neither design key present).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2458 lines, 171 KB, single key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3943 lines, 278 KB, single key `scaffold_corner_design`.

**Surface counts (§1.1–§1.7):** 12 entities; 9 state-machine dimensions across 7 entities (ShiftRoster carries three independent dimensions: status, compliance_state, waiver_state); 2 §1.2.1 OCC rules (`assignment-create-stale-roster` / `expected_roster_version`, `laundry-dispatch-stale-linen-item` / `expected_linen_item_version`); 13 calculations; 39 ordered validations; 57 endpoints; 71 errors; 6 roles (HousekeepingDirector, Supervisor, RoomAttendant, LaundryLead, FrontDeskAgent, ComplianceOfficer). Profile: quota_allocation + compliance_audit, flat topology, cyclic state machines, role model segregation_of_duties, layers optimistic_concurrency / cascading_side_effects / dual_variant_calculation / selector_policy, consistency immediate.

**§1.8:** 9 rules, 26 instances (dual_variant_calc 2, the other 8 rules 3 each).
**§1.9:** 89 instances — 65 full `test_recipe`s and 24 `excluded_because` stubs — across entities 12, state_machines 16, calculations 12, validations 27, endpoints 5, errors 6, rbac 5, cross_cutting_complexity_layers 5, consistency_model 1. All 24 stub citations resolve to real §1.8 instance names; all 115 instance names are globally unique; zero unbound `${var}` placeholders in any recipe; no forbidden concurrency vocabulary anywhere.

**Design adjudications made:**
1. **ERR_ENROLLMENT_SKIPS_EXHAUSTED was unreachable** — ACTIVE→COMPLETED fired at exactly `skips_accrued == nights`, so validation priority 39 could never trip. Fixed in SCAFFOLD.yaml (4 places: the transition precondition, its note, p39's `check`, and `ServiceEnrollment.nights`) by introducing `skip_budget = nights` for OPT_OUT and `ceil(nights / 2)` for EVERY_OTHER_DAY, keeping COMPLETED at `== nights`. p39 is now live and is exercised by `v_every_other_day_enrollment_exhausts_its_skip_budget` (nights 3 → budget 2 → third accrual refused, row still ACTIVE).
2. **ERR_INVALID_REQUEST status corrected** to 400 in two corner asserts (and one prose mention) that had said 422; §1.6 and validation priority 4 declare 400.
3. **A §1.8 inspection assert was arithmetically wrong** — points (5,9,9,9,9) with weights 0.30/0.25/0.20/0.15/0.10 score 78.0, not the asserted 87.0; corrected and the arithmetic inlined.
4. Recipe-hygiene choices: LINEN_REFRESH assignments avoided entirely (p23 pins only CHECKOUT/STAYOVER/DEEP_CLEAN to occupancy states); same-roster completion windows kept >= 10 minutes apart on distinct rooms to avoid tripping the rest-buffer and room-window rules incidentally; negative-trigger naming used so the linter skips role/payload checks on deliberately unauthorized or malformed calls.

**Lint gate (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2746_hotel_housekeeping_labor_room_attendant_workload/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2746_hotel_housekeeping_labor_room_attendant_workload/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2746_hotel_housekeeping_labor_room_attendant_workload/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    57
  §1.1 entities declared:     12
  §1.8 instances scanned:     26
  §1.9 instances scanned:     65
  Calls scanned (§1.8+§1.9):  1029

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(The linter scans only the 65 §1.9 instances that carry a `test_recipe`; the 24 stubs have no calls to check.) No sibling task directory was read, listed, or grepped at any point.

## Step 3: Copy shared files — 2026-09-04T17:10:49.849Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T17:27:00.000Z

Orchestrator truncation guard: verified independently — PRD.md is 495 lines, all 5 top-level sections + 11 §2 subsections + 9 §3 subsections present, and the file ends at a real boundary (final row of the §5 error table, `ERR_ENROLLMENT_SKIPS_EXHAUSTED | 422`), not mid-sentence. No regeneration needed.

Subagent summary (verbatim):

All sections landed and verification passed. PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_2746_hotel_housekeeping_labor_room_attendant_workload/workspace/PRD.md`.

## Section list (495 lines)

**§1. Introduction** — workload-credit framing, system-of-record scope, the two design commitments (credit conservation, segregation of duties).

**§2. Global Specifications & System-Wide Principles** (11 subsections)
- 2.1 User and Role-Based Access Control
- 2.2 API Response Structure (verbatim fixed block)
- 2.3 Pagination
- 2.4 Common Resource Properties, Timestamps and the Logical Clock
- 2.5 Flat Addressing and the Order in Which References Are Resolved
- 2.6 The Workload Credit Standard, Precision and Rounding
- 2.7 Optimistic Concurrency Control on Roster and Linen Writes
- 2.8 Ordinance Compliance as an Independent State Dimension
- 2.9 Cascade Discipline and the Conserved Day Quantity
- 2.10 The Order in Which a Request Is Validated (15-rung precedence ladder)
- 2.11 The Linen Ledger Identity

**§3. Business Logic & Workflows** (9 subsections)
- 3.1 Standing Up the Property, Its Inventory and Its People
- 3.2 Forecasting the Day and Sizing the Team
- 3.3 Rostering the Shift, Deriving the Ordinance Ceilings, and Workload Waivers
- 3.4 Allocating Rooms: Credit Valuation and the Eligibility Gates (8 pinned gates)
- 3.5 Cleaning the Room: Starting, Finishing, and the Window Rules
- 3.6 Inspection Sampling, Quality Scoring, and the Re-Clean Loop
- 3.7 Closing the Shift: Settlement, Productivity and Labour Cost
- 3.8 Linen Par Levels, Laundry Turnaround and Shortage Escalation
- 3.9 Guest-Facing Programmes and the Custody of Guest Property

**§4. Endpoint Definitions** — 4-column table, 57 rows. **§5. Error Code Catalogue** — 2-column table, 71 rows. Document ends on the last error row.

## Coverage audit (mechanically verified)

| Item | Declared | Documented |
| --- | --- | --- |
| Endpoints | 57 | 57 (table row count exact; every scaffold path string present verbatim, `comm` diff empty) |
| Error IDs | 71 | 71 (set-diff against scaffold clean; only extra scaffold token was the `ERR_XXX` placeholder inside its own envelope example) |
| Validations | 39 | 39, mapped onto the §2.10 ladder |
| State machines / transitions | 9 / 40 | 9 / 40; every `from`/`to` state name present |
| Calculations | 13 | 13 |
| Entity field names | 138 | 138, all backticked verbatim |
| Enum values | 47 | 47, all backticked verbatim |

## Hard Contracts

- **Contract 1 (Field-Name Coverage): PASS.** All 138 `entities[].fields[].name` plus every `input`/`query_params`/`path_params` identifier appear verbatim in backticks, including `to_iso8601`, `expected_roster_version`, `expected_linen_item_version`, `initial_soiled_sets`, `storage_bin`, `proof_kind`, `tracking_code`, `denial_reason`, `disposition`, `reservation_code`.
- **Contract 2 (Rule Coverage): PASS.** Priority ordering, both OCC rules, all cross-entity cascades (including the five-hop laundry-escalation cascade and the four-version completion cascade), `applies_to` scopes, and both sibling-branch pairs (inspection PASS/FAIL, waiver GRANT/DENY, claim approve/deny, laundry return/escalate) documented symmetrically.
- **Contract 3 (§3 Path Purity): PASS.** Zero backtick tokens in §3 begin with `/` or a bare HTTP method (verified by an awk-scoped grep over §3 only). Paths appear only in §2.7 and §4, where they are permitted.

## Zero-Silence adjudications (10)

1. `ERR_PROOF_INSUFFICIENT` — followed validation 30 + `errors[]` (2 of 3 sources): `PHOTO_ID` **or** `RECEIPT` accepted for `HIGH_VALUE`/`ID_DOCUMENT`; rejected the state machine's stricter PHOTO_ID-only reading.
2. Claim-decision encoding — documented `decision` ∈ {`APPROVE`,`DENY`} with an explicit `disposition`, and additionally accept the state machine's `APPROVE_PICKUP`/`APPROVE_SHIP` as equivalent.
3. Donation eligibility — used the state machine's `{STANDARD, PERISHABLE}` allowlist, barring both `ID_DOCUMENT` and `HIGH_VALUE` (superset of validation 31's ID_DOCUMENT-only wording).
4. `ERR_ENROLLMENT_SKIPS_EXHAUSTED` — keyed on the derived `skip_budget` (validation 39 + `nights` field note) rather than `errors[]`'s looser "equals nights"; noted the resulting divergence where `EVERY_OTHER_DAY` never reaches `COMPLETED`.
5. `ERR_OCCUPANCY_MISMATCH` — pairing table constrains only `CHECKOUT`/`STAYOVER`/`DEEP_CLEAN`; `LINEN_REFRESH` is exempt, reconciling validation 23 against validation 21.
6. ForecastDay publish's "at least one RoomType exists" precondition has no declared `error_id`; stated in prose without inventing a code.
7. `ERR_LINEN_STOCK_INSUFFICIENT` kept to its declared two operations (assignment complete, laundry dispatch); manual soil described as ledger-preserving without extending the code.
8. `productivity_flag` `QUALITY_HOLD` — used the formula's specific condition (any non-`CANCELLED` assignment with `reclean_generation` >= 1) over the field description's looser wording.
9. `ERR_WAIVER_NOT_REQUESTED` vs `ERR_WAIVER_ALREADY_DECIDED` — split by operation rather than left ambiguous.
10. `ERR_ASSIGNMENT_TERMINAL` — cancel requires `ASSIGNED`; any other status yields this code (transition precondition, broader than `errors[]`'s three-status list).

The two withheld design files were never opened, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-04T18:37:56.207Z

Orchestrator check: `test_helpers/` and `test_suite/` both exist at the task root; `workspace/test_helpers` and `workspace/test_suite` confirmed absent. Steps 5 and 6 were launched concurrently in a single message, so the impl generator could not read `test_suite/` (it did not exist at its spawn time).

Subagent summary (verbatim):

Generation is complete. Both output trees sit at the task root `/home/ubuntu/github/CodingPRD/tasks/task_2746_hotel_housekeeping_labor_room_attendant_workload/`; `workspace/test_helpers` and `workspace/test_suite` confirmed absent.

## Files written

**`test_helpers/` — 2759 lines total**
`__init__.py` 158, `api_client.py` 351, `api_errors.py` 190, `assertions.py` 244, `constants.py` 292, `factories.py` 412, `fixtures.py` 744, `test_users.py` 108, `types.py` 260.

**`test_suite/` — 5444 lines total, 117 tests**
`conftest.py` 17; queue A: `test_01` 201/4, `test_02` 125/4, `test_03` 97/2, `test_04` 304/6, `test_05` 293/6, `test_06` 252/6, `test_07` 229/6, `test_08` 241/6, `test_09` 317/6, `test_10` 258/6; queue B: `test_11_entities` 409/12, `test_12_state_machines` 529/11, `test_13_calculations` 339/6, `test_14_validations` 745/17, `test_15_endpoints` 290/5, `test_16_errors` 300/6, `test_17_rbac` 278/5, `test_18_concurrency` 144/2, `test_19_consistency` 76/1.

## Coverage against the design indices

- **Queue A (Difficulty):** 52 tests over all **26** non-stub instances — 0 missing.
- **Queue B (Corner):** **65** tests over all **65** non-stub instances — 0 missing, one test per instance.
- Every `Design:` tag was machine-verified against the parsed yaml: no unknown tags, no dual tags, no tag pointing at an `excluded_because:` stub.

## Instances skipped

Only the design's own stubs: **25 `excluded_because:` corner instances** (10 in validations, 3 in cross_cutting_complexity_layers, the rest across entities/state_machines/calculations/endpoints/errors/rbac) plus the difficulty index's stubs. No non-stub instance was dropped, weakened, xfailed or placeholdered.

## Design-vs-PRD conflicts adjudicated

1. **`ep_room_patch_updates_only_the_supplied_fields`** — design asserted `cleanliness_status == CLEAN` and `floor == 4`, but PRD 3.1 makes cleanliness start at `DIRTY` and non-seedable. Resolved by seeding `floor` at creation and asserting the PRD-derived `DIRTY`, preserving the partial-update claim.
2. **Two validations instances asserting "No Property row is created"** — unverifiable, since the API exposes no property list endpoint. Assertion dropped rather than faked; the error-id-precedence claim is asserted instead.
3. **Difficulty A7 waiver headroom** — design requested 4.00 credits against a 3.00 x 1.25 = 3.75 ceiling; the test requests 3.75 (the PRD-derived admissible maximum).
4. **`test_10` citations** — design pointed at a non-existent "PRD 3.10" for two enrolment sentences; corrected to §3.9, which is where lost-and-found and enrolments actually live.
5. **`rbac_laundry_lead_creating_a_room_assignment_is_rejected`** — the design's distinguishing aspect mentions a stale version never being reported, but its recipe sends the *current* version; kept the recipe as written and asserted the role refusal plus the identical body succeeding as Supervisor.
6. **Retention-boundary error tests** — PRD 2.4 permits rewinding the clock, so the accept side of each half-open boundary is exercised by rewinding one millisecond rather than inventing extra fixture items where that was simpler.

## Verification run per file and suite-wide

`python3 -m py_compile` per file plus `python3 -m compileall` over both dirs (clean); runtime `hasattr(test_helpers, ...)` audit of every imported symbol (**0 missing**); AST unused-import audit (**0 unused**); PRD-citation audit that whitespace-normalises each docstring quote and asserts verbatim containment in `workspace/PRD.md` (**117/117 pass**); exactly one trailing `Design:` line per test; the word "scaffold" appears **0** times in the suite. `__pycache__` removed from both trees.

## Step 6: Generate implementation — 2026-09-04T18:37:56.207Z

Subagent summary (verbatim):

Implementation complete and verified.

## Modules (all under `workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `derive.py` | 759 | all 13 named calculations, enum tables, lookups, recompute/cascade engine |
| `routes_assignment.py` | 508 | assignments (8 creation gates), start/complete/cancel, inspections + re-clean loop |
| `routes_config.py` | 368 | properties, room types, rooms, attendants |
| `routes_roster.py` | 334 | roster create/clock-in/close, waivers, sample plan |
| `routes_guest.py` | 342 | lost & found custody, service enrollments |
| `routes_linen.py` | 321 | linen lines, soil, laundry cycles + LATE_ESCALATED cascade |
| `serialize.py` | 261 | one `*_out` per entity |
| `validate.py` | 159 | rung-4 body validators |
| `routes_forecast.py` | 142 | forecast day create/publish/close |
| `envelope.py` | 115 | meta/envelope, pagination, filtering |
| `store.py` | 109 | in-memory dicts, logical clock, id/seq |
| `numeric.py` | 104 | round-half-up, Fraction/Decimal helpers, quarter-credit snapping |
| `errors.py` | 99 | 71 error ids -> HTTP status |
| `timeutil.py` | 93 | ISO8601 parse/format (3 fractional digits) |
| `app.py` | 88 | app factory, 6 blueprints, clock endpoint, error handlers |
| `auth.py` | 67 | headers, 6 roles, ladder rungs 1-3 |

3869 lines total, plus `requirements.txt` (Flask==3.1.3) and executable `start.sh`.

## Verification results

- **Endpoints: 57/57.** Programmatic diff of `app.url_map` against the SCAFFOLD `endpoints:` list — zero missing, zero extra. (The spec declares no `GET /housekeeping/properties` collection; its absence is correct.)
- **Role matrix: 342/342 probes match.** Every endpoint x all 6 roles: `ERR_ROLE_NOT_PERMITTED` fires exactly where the SCAFFOLD `roles:` list excludes the role.
- **Errors: 71/71 declared ids present, all HTTP statuses match, all 71 actually raised** somewhere in the code (no dead or missing codes).
- **Storage:** grep confirms no `sqlite`/`pickle`/`open(`/`/tmp`/`json.dump` anywhere — pure dicts. All 11 collection endpoints return `total_count: 0` on a fresh boot, clock at `2026-08-01T00:00:00.000Z`. Zero seeding.
- **Boot:** `start.sh` boot-to-first-200 is **0.56 s**, restarted cleanly 5 times — fine for `--isolation per-test-server`.

## Two defects found and fixed during smoke testing

1. **`waiver-request` crashed with HTTP 500** — `Fraction * Decimal` TypeError in the ordinance-headroom ceiling (`routes_roster.py:276`). Fixed by wrapping the factor in `to_frac`. I then audited every `to_frac`/Fraction arithmetic site in `derive.py` (lines 315, 374, 480-482, 504, 523, 626, 699, 731) and confirmed all operands are Fractions.
2. **`vdec` rejected decimal quantities in string form** (`"16.00"` -> `ERR_INVALID_REQUEST`). Made `vdec` accept an exact decimal string while still rejecting non-numeric strings. This is the known "factories send money as JSON strings" wipeout class; every one of the 13 decimal input fields was affected.

## Notable interpretation decisions

- `clock-in` on an already-CLOCKED_IN roster -> `ERR_ROSTER_NOT_CLOCKED_IN` (no "must be PLANNED" code exists; `ERR_ROSTER_ALREADY_CLOSED` is reserved for CLOSED).
- Roster `close` bumps the roster version exactly once; the forecast day is bumped only when the roster's credits actually moved.
- `waiver-request` checks the waiver dimension before the lifecycle dimension, per PRD §3.3's textual order.
- Assignment `start`/`complete` follow the §2.10 rung numbering (room-state rung 10 before the BREACH_BLOCKED rung 17), not §3.5's prose order.
- `complete` validates the linen debit before mutating anything, so a refusal leaves no partial state; the linen line is bumped only when `debit_sets > 0`.
- Manual `soil` over-debit -> `ERR_INVALID_REQUEST`, since §2.11 reserves `ERR_LINEN_STOCK_INSUFFICIENT` for completion and dispatch only.
- Laundry short-return shortfall is written off against `total_owned_sets` (PRD §2.11/3.8 wins over the SCAFFOLD side-effect text that moves it to `soiled_queue`), preserving the ledger identity.
- Linen line creation computes derived fields with `bump=False`, so a fresh line reports `version: 1`.
- `Property.total_rooms` / `outstanding_incentive_points` and `RoomType.room_count` are computed live at serialisation, so accrue/void store no counter.
- Verified behaviours worth flagging: PERISHABLE retention is 0 days, so immediate disposal is legitimate; the sticky `LATE_ESCALATED` shortage override correctly holds `ESCALATED` even at a coverage ratio of 2.0; `outstanding_incentive_points` counts only ACTIVE enrollments, so it drops when an enrollment reaches COMPLETED.

## Step 7: Run tests and iterate — 2026-09-04T18:55:00.000Z

Orchestrator verification (independent of the subagent's claim): `workspace/implementation/results.{1..8}.json` all exist, all written at 18:49 from the same sweep, and each reports `passed=117 / total=117 / failed=0`. Sweep artifacts confirmed present and green.

Subagent summary (verbatim):

Clean sweep achieved. Here is the summary.

## Summary

**Iterations run:** 2 (each a parallel 8-round `setsid nohup` sweep, no early exit).

- Iteration 1: 115/117 passing in **all 8 rounds** — the same 2 tests failed deterministically in every round (no flakiness anywhere in the suite; no timeouts or connection-refused, despite host contention).
- Iteration 2 (after fixes): **117/117 passing in all 8 rounds.** Per-round artifacts left at `workspace/implementation/results.{1..8}.json`.

**Tests deleted:** none. Both failures survived STEP 1a/1b coverage, and both traced to defects in `test_suite/`, not to PRD silence about the rule as a whole.

**Fixes applied to `test_suite/`** (both in `test_suite/test_12_state_machines.py`):

1. `test_a_closed_day_refuses_both_of_its_transitions_with_distinct_codes` — **error-precedence partial coverage (STEP 1c)**. The test demanded `ERR_FORECAST_NOT_DRAFT` for a publish aimed at a `CLOSED` day; the implementation returns `ERR_FORECAST_ALREADY_CLOSED`. PRD §3.2 says *"Any subsequent mutation aimed at a `CLOSED` day is refused with `ERR_FORECAST_ALREADY_CLOSED`, and a publish attempt on a day that is not `DRAFT` is `ERR_FORECAST_NOT_DRAFT`"* — a publish on a `CLOSED` day satisfies **both** clauses, and neither §3.2 nor the tenth rung of §2.10 states which pre-empts (§2.10 even lists them in the opposite order to §3.2). Two PRD-faithful implementations exist, so the publish leg was relaxed to `validate_error_is_one_of([FORECAST_NOT_DRAFT, FORECAST_ALREADY_CLOSED])` with an explicit 409 status assertion retained. The close leg is unambiguous and stays an exact `validate_error(..., FORECAST_ALREADY_CLOSED, 409)`.

2. `test_each_accrual_pushes_its_points_into_the_property_ledger` — **assertion mis-translated the PRD (STEP 2)**. After the second accrual on a 2-night `OPT_OUT` stay the enrolment goes `ACTIVE -> COMPLETED` (PRD §3.9), and PRD §3.1 defines `outstanding_incentive_points` as *"the sum of `points_accrued` across every service enrolment whose room belongs to the property and whose `status` is still `ACTIVE`"*. The property ledger must therefore read **0**, not 1000; the test asserted 1000. Corrected to 0 with the §3.1 quote inline. The enrolment's own `points_accrued == 1000` and `version == 3` assertions were kept.

**Fixes applied to `test_helpers/`:** none — no fixture, factory, or role-header helper was implicated.

**Fixes applied to `implementation/`:** none. Both failures were test-side; `derive.property_outstanding_incentive_points` and `routes_forecast.publish_forecast_day` were verified PRD-faithful and left untouched. No PRD-required check was weakened, no endpoint/field/side-effect added, and storage remains in-memory only.

`worklog.md` was not touched.

## Step 8: Finalize PRD — 2026-09-04T18:54:21.959Z

Step 8 was NOT skipped: Step 7 ran 2 iterations and applied 2 `test_suite/` fixes, so the skip condition (0 deletions / 0 test_suite / 0 test_helpers / 0 implementation fixes) did not hold. Orchestrator verification: `PRD_FINALIZED.md` exists and differs from `PRD.md` (495 lines both; 108991 -> 109589 bytes).

Subagent summary (verbatim):

PRD_FINALIZED.md written at `workspace/PRD_FINALIZED.md`.

## Size delta
- Lines: 495 -> 495 (0.0% — both edits are inline inside existing long paragraph lines).
- Bytes: 108,991 -> 109,589 (+598, +0.55%).

## Changes (2, both tracing to Step 7 item 1)
- **§3.2 (forecast day close/publish paragraph)** — insert — after the existing "Any subsequent mutation aimed at a `CLOSED` day ... `ERR_FORECAST_NOT_DRAFT`" sentence, pinned that the `CLOSED` test runs *before* the operation's own status precondition on the two day-targeted operations: publish on a `CLOSED` day -> `ERR_FORECAST_ALREADY_CLOSED` (not `ERR_FORECAST_NOT_DRAFT`), close on a `CLOSED` day -> `ERR_FORECAST_ALREADY_CLOSED` (not `ERR_FORECAST_NOT_PUBLISHED`); both 409 — `implementation/routes_forecast.py:103-106` and `:123-126`.
- **§2.10 (tenth-rung catalogue)** — revise — appended a clause to the forecast-day sentence noting the `CLOSED` code pre-empts the publish/close preconditions, cross-referencing §3.2, so §2.10's opposite listing order can no longer be read as a precedence statement — same impl sites.

No PRD change for Step 7 item 2: `implementation/derive.py:159-169` (`property_outstanding_incentive_points`) sums only `status == "ACTIVE"` enrolments whose room is in the property, which PRD §3.1 (line 180) already pins verbatim, and the `ACTIVE -> COMPLETED` transition on the budget-completing accrual is already pinned in §3.9 (line 337). That failure was a pure test-assertion bug.

## Per-edit pre-edit search log

**Edit 1 (§3.2)**
- (a) Subject: precedence among a `ForecastDay`'s status-precondition error codes (`ERR_FORECAST_ALREADY_CLOSED` vs `ERR_FORECAST_NOT_DRAFT` / `ERR_FORECAST_NOT_PUBLISHED`).
- (b) Enumerated: grepped every read of a forecast day's `status` in `implementation/` (`grep -rn "day\[.status.\]\|FORECAST_ALREADY_CLOSED\|FORECAST_NOT_DRAFT\|FORECAST_NOT_PUBLISHED"`) — `routes_forecast.py:99-116` (publish: CLOSED -> ALREADY_CLOSED, then !=DRAFT -> NOT_DRAFT), `routes_forecast.py:119-142` (close: CLOSED -> ALREADY_CLOSED, then !=PUBLISHED -> NOT_PUBLISHED, then `ERR_ROSTER_STILL_OPEN`), `routes_roster.py:47-63` (roster create: scope mismatch, then CLOSED -> ALREADY_CLOSED, then !=PUBLISHED -> NOT_PUBLISHED), `routes_roster.py:131-152` (clock-in: roster `CLOSED` -> `ERR_ROSTER_ALREADY_CLOSED` first, then day !=PUBLISHED -> NOT_PUBLISHED with **no** CLOSED-day branch), `routes_linen.py:223` (day !=PUBLISHED filter, no error code), `routes_assignment.py:64` and `:310` (day read for `business_date`/`allocated_credits_total`, no status gate), `errors.py:42-44` (all three codes 409).
- (c) Adjustment: my first draft said the `CLOSED` check precedes the status precondition on *every* operation that reads a forecast day's status. `routes_roster.py:144` contradicts that (a `CLOSED` day there would answer `ERR_FORECAST_NOT_PUBLISHED`; the path is unreachable in practice because closing a day requires all its rosters `CLOSED`, but the wording would still have been a false universal), and `routes_roster.py:58` / `routes_linen.py:223` / `routes_assignment.py:64` are off-site paths I must not redescribe. I re-scoped the sentence to "the two operations that target the day itself" (publish and close) and named the two concrete substitutions rather than asserting a general rule.

**Edit 2 (§2.10)**
- (a) Subject: same — the tenth-rung catalogue's ordering of the forecast-day codes.
- (b) Enumerated: same set as Edit 1, plus checked the neighbouring roster analogue in the same PRD sentence (`ERR_ROSTER_ALREADY_CLOSED` vs `ERR_ROSTER_NOT_CLOCKED_IN`) against `routes_roster.py:137-140`, `:169-172` and `routes_assignment.py:81, 223, 275, 355, 403` — the impl also checks roster-`CLOSED` first everywhere, so nothing in the sentence needed correcting there.
- (c) Adjustment: kept the clause strictly on the forecast-day half of the sentence and worded it as a pointer to §3.2 ("pre-empts the publish and close status preconditions") rather than a standalone universal, so it cannot be read as legislating the roster or assignment precedence chains that Step 7 never touched.

## Step 9: Complete PRD — 2026-09-04T19:26:41.966Z

Orchestrator decision (recorded per the AUTONOMY instruction): Step 9 was run as **three sequential passes partitioned by implementation module** over one shared `PRD_COMPLETED.md`, rather than as one subagent. Rationale: `implementation/` is 3869 lines across 16 modules and the PRD is 495 long-wrapped lines (~110 KB); a single subagent asked to walk all of it exhaustively reliably ends up doing a shallow scan and emitting a near-identical file. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying so they could not destroy earlier passes' edits, and each was told to use surgical `Edit` calls rather than a whole-file `Write` (64k output cap).

Partition:
- Pass 1 — `app.py`, `auth.py`, `envelope.py`, `errors.py`, `store.py`, `timeutil.py`, `numeric.py`, `validate.py`, `serialize.py`
- Pass 2 — `derive.py`, `routes_forecast.py`, `routes_config.py`
- Pass 3 — `routes_assignment.py`, `routes_roster.py`, `routes_linen.py`, `routes_guest.py`

Totals across the three passes: **59 edits — 43 ambiguity-pins, 16 mismatch-revisions.** `PRD_FINALIZED.md` 495 lines / 109,589 chars -> `PRD_COMPLETED.md` 497 lines / 131,059 chars (+21,470 chars, +19.6%). Not byte-identical to its source (verified with `cmp`).

Orchestrator structural verification of the final document: 28 headings (unchanged from the pass-1/2 baseline), §4 endpoint table intact, §5 error catalogue intact at 71 rows, and the file ends at a real boundary (`| ERR_ENROLLMENT_SKIPS_EXHAUSTED | 422 |`), not mid-sentence. Also confirmed by `find -newermt` that no file under `implementation/`, `test_suite/` or `test_helpers/` was modified after the 18:49 green sweep, so the 8x117/117 result still describes the shipped artifacts.

### Pass 1 summary (verbatim)

**File stats:** `PRD_FINALIZED.md` 495 lines / 109,589 chars -> `PRD_COMPLETED.md` 497 lines / 116,191 chars (**+6,553 chars, +2 lines**).

**Counts:** 13 ambiguity-pins, 3 mismatch-revisions.

**Changes**
- §2.1 — revise — ambiguity — a whitespace-only header counts as empty; role string compared exactly with no trimming or case-folding — `auth.py:46-51`
- §2.2 `api_request_id` bullet — insert — ambiguity — `req_` + exactly 20 uppercase-alnum chars, regenerated per response including errors — `store.py:69`, `envelope.py:23`
- §2.2 `api_request_timestamp` bullet — insert — ambiguity — read from the logical clock, not wall clock, so responses without an intervening clock move share it — `envelope.py:26`
- §2.2 `data` bullet — **revise — mismatch** — PRD said 2xx-with-no-data carries an empty object; impl emits JSON `null` (clock setter, the only such op) — `app.py:50`
- §2.2 error-format heading line — revise — mismatch — envelope also covers a 5xx response, not only 4xx — `app.py:72-78`
- §2.3 P1 — insert — ambiguity — empty `?limit=` takes the default; non-integer, `limit` outside 1..100, negative `offset` -> `ERR_INVALID_REQUEST` (not clamped) — `envelope.py:58-81`
- §2.3 P2 — insert — ambiguity — `created_at` ties broken by server minting sequence (total order); `has_more` = offset + returned < total_count; `total_count` is pre-window; offset past the end is an empty page, not an error — `store.py:105-109`, `envelope.py:39-46`
- §2.3 P3 — insert — ambiguity — filters are exact case-sensitive equality on the rendered stored value; empty and undeclared query params ignored; a non-matching (even non-enum) value yields an empty page rather than a 400 — `envelope.py:93-115`
- §2.4 P1 — insert — ambiguity — canonical lowercase hyphenated UUID; one timestamp rendering everywhere (literal `Z`, always 3 fractional digits); sub-millisecond precision **truncated**, not rounded; unset timestamp is `null` — `store.py:64`, `timeutil.py:46-55`
- §2.4 P2 — insert — ambiguity — `updated_at` equals `created_at` at creation — `store.py:74-85`
- §2.4 P4 — insert — ambiguity — accepted instant input shapes (`T` or space separator, optional seconds, 1-9 fractional digits, optional `Z`/`+-HH:MM`/`+-HHMM`, **no designator = UTC**), surrounding whitespace ignored, anything else 400 — `timeutil.py:12-43`, `validate.py:143-155`
- §2.4 P5 — insert — ambiguity — date inputs strictly `YYYY-MM-DD` (an instant or an impossible date is 400); unset date is `null` — `timeutil.py:58-68`, `validate.py:126-140`
- §2.6 — insert — ambiguity — decimals emitted as bare JSON numbers with trailing zeros dropped (`16.00` -> `16.0`); decimal input accepted as number *or* exact string, rounded half up to the field's declared precision **before** the range check — `numeric.py:96-104`, `validate.py:77-101`
- §2.10 rung four — insert — ambiguity — body must be a JSON object (absent/blank read as `{}`; array/scalar/unparseable fails); explicit `null` == omitted except on declared-nullable fields; booleans are not integers/numbers and `5.0` is not an integer; enum/date fields must be strings and boolean fields real booleans — `validate.py:26-123`
- §4 preamble — revise — mismatch + ambiguity — clock setter's `data` is `null` (was "empty object"), and trailing slashes are optional (`strict_slashes = False`) — `app.py:29,50`
- §5 preamble — insert — ambiguity — unknown path -> `ERR_INVALID_REQUEST`/404 and unsupported method -> `ERR_INVALID_REQUEST`/405, both decided by routing before the §2.10 ladder and therefore header-independent; unexpected failure -> `ERR_INVALID_REQUEST`/500 — `app.py:56-78`

**Verified as already exactly pinned (no change needed):** the §5 error catalogue is byte-exact against `errors.py` (71 ids, all statuses match); all 58 endpoint paths, methods and `Authorized Role(s)` sets in §4 match the blueprints and `authenticate()` calls (including "All roles" = `authenticate(None)`); every list endpoint's declared filter set matches its `filtered()` mapping; every key emitted by all 11 serializers is named in the PRD, and no PRD-named entity field is left unserialized.

### Pass 2 summary (verbatim)

Pass 2 complete. `workspace/PRD_COMPLETED.md` edited in place; pass 1's 16 edits verified intact.

**Size:** 497 lines / 116,191 chars before -> 497 lines / 123,265 chars after (all edits in-paragraph; no new sections, no line added or removed).

**Counts:** 19 changes — 12 ambiguity-pins, 7 mismatch-revisions.

- §2.5 Flat Addressing (L104) — revise — mismatch — scope-coherence enumeration was wrong in both directions: room creation *is* enforced (room_type must belong to the named property) and laundry-cycle dispatch is *not* (it names only a linen line); lost-and-found checks both the room and the finder — `routes_config.py:167-171`, `routes_assignment.py:66`, `routes_roster.py:51`, `routes_guest.py:34-43`, `routes_linen.py:125-145`
- §3.4 assignment create (L226) — insert — ambiguity — defined the "non-terminal" set for `ERR_ASSIGNMENT_DUPLICATE` as ASSIGNED/IN_PROGRESS/COMPLETED — `derive.py:46`
- §3.1 computed property figures (L180) — insert — ambiguity — `total_rooms`, `outstanding_incentive_points`, `RoomType.room_count` are counted live at render time, so Property/RoomType never bump `version`/`updated_at` and stay at version 1 for life — `derive.py:149-169`, `serialize.py:42-45,60`
- §3.1 room type (L182) — revise — ambiguity — `code` must arrive already upper-case (lower-case -> `ERR_INVALID_REQUEST`, not upper-cased server-side); digit-only codes pass; uniqueness is exact/case-sensitive — `validate.py:57`, `routes_config.py:92`
- §3.1 room type (L182) — insert — ambiguity — the linen recompute on room-type creation is unconditional: every linen line's `version` bumps even when all three figures are unchanged; added `coverage_ratio` to the recomputed list — `routes_config.py:122`, `derive.py:271-293`
- §3.1 room create (L184) — revise — mismatch — only **two** postures may be seeded; a supplied `cleanliness_status` is ignored without error and the room starts `DIRTY` — `routes_config.py:156-190`
- §3.1 room create (L184) — insert — ambiguity — `floor` has no permitted range at all (any integer incl. negative/zero); only non-integers are rejected — `routes_config.py:155`
- §3.1 room create (L184) — insert — ambiguity — the room-creation linen recompute bumps every line's `version` unconditionally too — `routes_config.py:197`
- §3.1 room PATCH (L186) — insert — ambiguity — empty/no-op body still increments `version`; omitted or `null` leaves values alone **except** the two date fields, which are nullable and cleared by explicit `null`; the PATCH cascades nothing — `routes_config.py:237-273`, `validate.py:126-140,158`
- §3.1 room PATCH (L186) — revise — mismatch — `OUT_OF_ORDER` terminality binds only system-driven transitions: the PATCH accepts any of the six values on any room (the `IN_SERVICE` refusal excepted), and an explicit `cleanliness_status` is applied *after* the `DUE_OUT` side effect and wins — `routes_config.py:250-266`
- §3.1 attendant PATCH (L190) — insert — ambiguity — own `version` bumps on every accepted request; the roster cascade fires only when `restricted_duty` actually changes value; each reached roster bumps once; forecast day untouched; `can_inspect`/`status` cascade to nothing — `routes_config.py:341-368`, `derive.py:443-451`
- §3.2 forecast create (L194) — revise — ambiguity — "creation date" pinned as the UTC calendar date of the property's `created_at`; same-date accepted — `routes_forecast.py:49`
- §3.2 forecast create (L194) — insert — ambiguity — `forecast_arrivals > forecast_occupied_rooms` is `ERR_INVALID_REQUEST` (400) at rung 4, evaluated before `property_id` resolution — `routes_forecast.py:31-37`
- §3.2 headcount (L200) — insert — ambiguity — a zero-or-negative assignable ceiling (`pre_post_shift_minutes` >= `standard_shift_minutes`) yields `required_attendants` 0 whatever the projection — `derive.py:495-504`
- §3.2 publish (L204) — revise — mismatch — publish does **not** require a room type: `DRAFT` status is the only precondition; a property with no inventory republishes 0.00/0 — `routes_forecast.py:99-116`
- §3.5 rest buffer (L255) — revise — mismatch — a gap of exactly `rest_buffer_minutes` is permitted and only a smaller gap (overlap included) is refused; with `rest_buffer_minutes` 0 only genuine overlap on the roster is refused — `derive.py:587-604`
- §3.6 sample plan (L269) — insert — ambiguity — `completed_count` is the *performed* count (COMPLETED + INSPECTED_PASS + RECLEAN_REQUIRED), not the eligible pool size; `remaining_samples` floored at zero — `derive.py:636-667`
- §3.6 sample plan (L269) — revise — mismatch — the final tie-break is server mint order after `created_at` (not `created_at` itself); `id` never consulted — `derive.py:655`
- §3.8 linen classes (L307) — revise — mismatch — only `SHEET_SET` is *debited*, but the deep-clean shortage gate consults **every** linen line of the property regardless of `linen_type` — `derive.py:296-302`, `routes_assignment.py:145`

### Pass 3 summary (verbatim)

All 24 edits verified present exactly once in `PRD_COMPLETED.md`, with no duplication or garbled splices. Pass 3 of 3 is complete.

| | before | after |
|---|---|---|
| lines | 497 | **497** (every edit was in-paragraph) |
| chars | 123,265 | **131,059** (+7,794) |
| headings (`grep -c '^#'`) | 28 | **28** |

**24 changes: 18 ambiguity-pins, 6 mismatch-revisions.**

(Note: the brief predicted 25 headings; the file's actual baseline after passes 1-2 was 28. I treated 28 as the invariant and confirmed it unchanged — no sections were added or removed.)

- §2.7 — insert — ambiguity — both `expected_*_version` fields are non-negative at the shape rung, so a negative is `ERR_INVALID_REQUEST` rather than a stale-version rejection; 0 does reach the comparison — `routes_assignment.py:59`, `routes_linen.py:135`
- §2.9 — revise — mismatch — roster-recompute trigger list narrowed to counted/performed-set moves; the start transition explicitly excluded; the waiver decision re-derives only `compliance_state` — `routes_assignment.py:250-257`, `routes_roster.py:316-323`
- §2.9 — revise — mismatch — carve-out for the two recomputations folded into their provoking mutation (linen create leaves the line at version 1; the roster close bumps once at the end) — `routes_linen.py:60`, `routes_roster.py:215`
- §2.10 — revise — mismatch — clock-in on a non-`PLANNED` roster yields `ERR_ROSTER_NOT_CLOCKED_IN`; the waiver decision is exempt from the roster-`CLOSED` universal; within-rung tie-break differs for cancel vs start/complete/inspect — `routes_roster.py:139,292-325`, `routes_assignment.py:355-361`
- §3.3 — insert — ambiguity — the three waiver fields start null — `routes_roster.py:81-83`
- §3.3 — insert — ambiguity — a second clock-in on a `CLOCKED_IN` roster is `ERR_ROSTER_NOT_CLOCKED_IN` — `routes_roster.py:139-140`
- §3.3 — revise — ambiguity — `waiver_requested_credits` is quantised to two decimals then range-checked at >= 0.00; waiver dimension precedes lifecycle; a `CLOSED` roster yields `ERR_ROSTER_ALREADY_CLOSED` — `routes_roster.py:261,265,270-273`
- §3.3 — insert — ambiguity — the waiver decision carries no roster-`status` precondition and may be recorded after the roster has closed — `routes_roster.py:292-302`
- §3.4 — revise — ambiguity — the roster-`CLOSED` precondition and then the duplicate constraint sit between the version check and the eight gates; `PLANNED` is a legal target — `routes_assignment.py:81-95`
- §3.4 — revise — ambiguity — gate 2's waiver bypass spelled out (`GRANTED`, `waiver_requested_credits` set, resulting figure at or below it) — `routes_assignment.py:118-122`
- §3.5 — revise — mismatch — the five start conditions reordered so `BREACH_BLOCKED` is last, after both room rules; the room-condition rung carries `ERR_ROOM_ALREADY_IN_SERVICE`, so `OUT_OF_ORDER` yields it too — `routes_assignment.py:208,221-246`
- §3.6 — insert — ambiguity — the inspector's `X-User-ID` resolves at the FK rung after `assignment_id` and before every state gate, so an unresolvable one is `ERR_ATTENDANT_NOT_FOUND` — `routes_assignment.py:396-399`
- §3.6 — revise — mismatch — the generation-2 failure edge is `CLEAN -> OUT_OF_ORDER`, not `RECLEAN_REQUIRED -> OUT_OF_ORDER` — `routes_assignment.py:470-472`
- §3.7 — revise — ambiguity — `worked_minutes` required, `break_minutes` optional defaulting to 0 — `routes_roster.py:165-166`
- §3.7 — revise — mismatch — only the 720 ceiling belongs to `ERR_WORKED_MINUTES_IMPLAUSIBLE`; negatives are `ERR_INVALID_REQUEST` at rung 4 — `routes_roster.py:165,196-200`
- §3.7 — insert — ambiguity — hop two does not bump the roster's `version`; the close bumps it exactly once at the end — `routes_roster.py:215,253`
- §3.8 — revise — ambiguity — `initial_soiled_sets` <= `total_owned_sets`, checked before the `property_id` reference resolves; the creation's derived figures leave the line at version 1 — `routes_linen.py:26-36,60`
- §3.8 — revise — ambiguity — soil `sets` is 0..100000, zero is accepted and still bumps `version`, and an over-large soiling is `ERR_INVALID_REQUEST` not `ERR_LINEN_STOCK_INSUFFICIENT` — `routes_linen.py:90-103`
- §3.8 — revise — ambiguity — `returned_sets` above `batch_sets` is `ERR_INVALID_REQUEST`, tested after the `QUEUED` precondition — `routes_linen.py:252-263`
- §3.9 — revise — ambiguity — the nine lost-found fields that are null at log time enumerated — `routes_guest.py:53-63`
- §3.9 — revise — ambiguity — `storage_bin` is a required 1-to-32-character string — `routes_guest.py:97`
- §3.9 — revise — ambiguity — `claimant_name` 1..120; `claimant_contact` required but may be the empty string (0..160) — `routes_guest.py:118-121`
- §3.9 — revise — ambiguity — `APPROVE_PICKUP`/`APPROVE_SHIP` override any supplied `disposition`, and the SHIPPED contact test precedes the `tracking_code` test — `routes_guest.py:179-198`
- §3.9 — revise — ambiguity — a denial leaves `proof_kind` and `claim_attempt_count` standing, and an approval never clears a stale `denial_reason` — `routes_guest.py:167-207`

Structural verification — passed: 28 headings unchanged; §4 endpoint table 57 method rows intact; §5 error catalogue 71 rows intact; file terminates on the last error row, not mid-sentence; each of the 24 inserted phrases occurs exactly once.

Most consequential findings were three false universals inherited from earlier prose — §2.9's "every recomputation bumps version" (broken by linen creation and the roster close), §2.9's "every assignment status change recomputes the roster" (broken by the start transition), and §2.10's "any mutation on a `CLOSED` roster yields `ERR_ROSTER_ALREADY_CLOSED`" (broken by the waiver decision, which has no lifecycle precondition at all).

---

**PIPELINE COMPLETE.** All nine steps done; `workspace/PRD_COMPLETED.md` written.
