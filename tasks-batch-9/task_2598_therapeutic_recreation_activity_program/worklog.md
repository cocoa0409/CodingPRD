# Worklog — task_2598_therapeutic_recreation_activity_program

## Step 1: Create task directory — 2026-09-03T17:48:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2598_therapeutic_recreation_activity_program` and its `workspace/` subdirectory. Index 2598 was pre-assigned by the orchestrator prompt; no scan of ./tasks/ was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-03T19:10:00.000Z

All three scaffold artifacts are complete and lint-clean.

### Files

| Path | Lines |
|---|---|
| `SCAFFOLD.yaml` | 3080 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1295 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3943 |

Each file has exactly the required top-level shape: `SCAFFOLD.yaml` contains neither design key; the other two carry only `scaffold_difficulty_design` / `scaffold_corner_design`.

### SCAFFOLD.yaml counts (§1.0–§1.7)

- **14 entities**, `entity_topology: graph`, one immutable entity (`ResidentAssessment`, `common_fields: false`)
- **10 state machines** over 9 entities (Outing carries two parallel dimensions: `logistics_status` and `consent_status`), **62 transitions** total, `state_machine_shape: cyclic` with parallel/branching/compound secondaries
- **53 endpoints**, **9 calculations** (2 with dual variants), **52 validation rules** (globally distinct priorities), **62 error codes**, **7 roles** (`role_model: segregation_of_duties`, two `entity_backed` roles), **2 §1.2.1 OCC rules** (`plan-create-stale-resident`, `transport-booking-stale-vehicle`)
- `difficulty_level: beyond_expert`, `consistency_model: immediate`

### Design coverage

- **§1.8: 9 difficulty rules × 2 differentiated instances = 18 instances** (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant)
- **§1.9: 90 corner instances across all 9 guide sections** — 74 with full `test_recipe`s, 16 emitted as `excluded_because:` stubs citing the §1.8 instance that already covers the corner. Section split: entities 12, state_machines 13, calculations 14, validations 17, endpoints 5, errors 12, rbac 7, cross_cutting_complexity_layers 9, consistency_model 1.

### Verification

- `scaffold_lint.py` → **`VERDICT: clean lint`** (861 calls scanned across 18 §1.8 + 74 §1.9 instances; all conform to §1.5 and all §1.1 FKs have reverse-reachability).
- All 62 catalog error codes are triggerable by at least one designed instance (the last gap, `ERR_PARTICIPATION_RECORD_NOT_FOUND`, was closed by adding `participation_record_unknown_id_not_found`).
- No forbidden concurrency vocabulary in any of the three files; all races are framed purely as stale `expected_*_version` → 412. One SCAFFOLD.yaml comment using "simultaneously-violated" was rewritten.
- Instance names are unique across both design files; every cited `difficulty_instance` resolves.

Two consistency fixes were also made to SCAFFOLD.yaml while designing the corners: validation 36 (`ERR_CONSENT_INCOMPLETE`) now covers `FINALIZE` as well as `DEPART` — otherwise a non-effective consent made the code unreachable, since `OutingConsent.effective` compares `expires_on` to `Outing.departure_at` rather than the clock.

## Step 3: Copy shared files — 2026-09-03T19:10:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-03T19:28:00.000Z

PRD generation for task_2598 is complete.

**Output:** `workspace/PRD.md`
**Line count:** 530 lines, ending at a real section boundary (last line is the final row of the §5 error table, `| ERR_VEHICLE_CAPACITY_EXCEEDED | 409 |`). No audit footer was written into the file.

**Top-level headings in order**
1. `# Therapeutic Recreation Activity Program API — Product Requirements Document`
2. `## 1. Introduction`
3. `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control · 2.2 API Response Structure · 2.3 Pagination, Filtering and List Ordering · 2.4 Common Resource Properties · 2.5 The Logical Clock and Temporal Semantics · 2.6 Numeric Precision and Rounding Discipline · 2.7 Supervision Weighting: The Department's Common Currency · 2.8 Validation Precedence · 2.9 Path Resolution and Nested-Child Ownership · 2.10 Optimistic Concurrency on Parent Versions · 2.11 Cascade Discipline and Derived-Field Reconciliation
4. `## 3. Business Logic & Workflows` — 3.1 The Census and the Clinical Record · 3.2 Individualized Activity Plans and the Revision Cycle · 3.3 Attainment: Two Views of the Same Cycle · 3.4 The Activity Calendar: Programs, Rooms and Sessions · 3.5 Enrolling Residents: The Densest Gate in the Department · 3.6 Documenting Participation, and Closing the Book on a Session · 3.7 Volunteers, Screening and Intergenerational Programming · 3.8 Outings: Transport, Seats, Escorts and Consent · 3.9 Resident Council Input and Regulatory Survey Documentation
5. `## 4. Endpoint Definitions` (4-column table, 53 rows)
6. `## 5. Error Code Catalogue` (2-column table, 62 rows)

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 117 required, 117 present, 0 missing
- endpoints[].request_body: 80 required, 80 present, 0 missing   (includes all 13 path params, present as {param} inside backticked paths)
- endpoints[].query_params: 80 required, 80 present, 0 missing   (same declared input set; limit/offset/all filters named in 2.3)
- enum literal values (secondary pass): 97 required, 97 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- state_machines[].transitions: 62 checked (10 machines), 62 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed, 0 missing
- validations[] conditions: 52 checked, 52 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 28 side-effect blocks + 52 applies_to scopes checked, all expressed, 0 missing
- entities[].fields[] structured content: 56 constraint sets, 50 defaults, 37 computed derivations checked, all reconstructible from prose, 0 missing
- sibling-branch symmetry: 15 groups checked (plan CLOSE x3, session CANCEL x2, outcome branches x3, FINALIZED branches x3, outing CANCEL x3, CONSENT_BLOCKED entries x2, CONSENT_BLOCKED exits x2, consent GRANTED sources x3, clearance sources x2, withdrawal cascades x3, council ADOPTED x2, council DECLINED x2, packet COMPILED x2, plan_attainment variants x2, volunteer_hours variants x2), 0 asymmetric
Status: PASS
```

```
Path purity check (3 only):
- backtick tokens scanned: 335
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Other verifications:** 2.2 diffs byte-identical to `section-2.2-response-structure.md`; 4 method+path pairs match the scaffold exactly (53/53, no extras); 5 error IDs and HTTP statuses match the scaffold exactly (62/62); zero fuzzy quantifiers and zero operator/pseudocode syntax outside the fixed 2.2 JSON block. Both withheld design files were never opened or grepped, and no sibling task directory was read.

**One scaffold inconsistency resolved by decision:** the `Volunteer` `ORIENTATION_COMPLETED` state-machine side effect says `orientation_completed_on` is the calendar date of `current_utc`, while the screening endpoint says `orientation_completed_on = completed_on`. The PRD follows the endpoint version (`completed_on` is supplied and stored, `screening_level` rises to `FULL`), since `completed_on` is a declared input. Two other places required naming an error ID the scaffold leaves implicit: confirming a student volunteer's assignment without an adult program lead reports `ERR_INTERGENERATIONAL_SUPERVISION_MISSING`, and compiling a packet whose `window_end` has not yet passed reports `ERR_PACKET_INVALID_STATE` — both the only plausible candidates in the catalogue.

**Orchestrator truncation guard:** verified independently — 530 lines, 27 headings present in order, final line is a complete error-table row. Not truncated; no regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T20:00:00.000Z

All work is complete and verified. Final state:

### Files written (task root, never under `workspace/`)

`test_helpers/` — 1519 lines total: `__init__.py` (1), `api_errors.py` (145, 62-member `ApiErrorId` + status map), `types.py` (105), `constants.py` (79), `api_client.py` (262, 53 endpoint methods), `test_users.py` (81), `assertions.py` (93), `factories.py` (300), `fixtures.py` (453, tiers 0–5).

`test_suite/` — 6732 lines: `conftest.py` (67); queue A `test_01`–`test_09` (161/176/163/210/155/165/157/151/213); queue B `test_20` (460), `test_21` (679), `test_22` (600), `test_23` (820), `test_24` (341), `test_25` (1088), `test_26` (564), `test_27` (459), `test_28` (103).

### Tests emitted: 112 total, collected by pytest with no import errors

- **Queue A (Difficulty): 36 tests / 18 instances** — all 9 rule_ids x 2 instances x 2 tests, no skips.
- **Queue B (Corner): 76 tests / 72 instances** — 72 of the 74 non-stub instances; the 16 `excluded_because:` stubs were not translated at all.

### Instances skipped

1. `Corner/entities/resident_system_fields_input_ignored` — non-unique derivability: the recipe posts system fields and asserts 201 "ignored", but PRD 2.8 rank 8 says unknown fields "are rejected outright… `ERR_INVALID_REQUEST` with HTTP 400".
2. `Corner/entities/session_computed_counters_input_ignored` — same rank-8 contradiction (posts `enrolled_count`/`required_staff_count`/`effective_capacity`).
3. Partial: inside `Corner/errors/volunteer_clearance_screening_and_overlap_rejected`, only the `ERR_VOLUNTEER_SCREENING_INSUFFICIENT` probe was dropped (its premise "CLEARED at screening_level BASIC" is unreachable — `BACKGROUND_CHECK_CLEARED` yields `SCREENING`/BASIC, so rank 32 preempts rank 33). The instance's two independently derivable probes were emitted as 2 tests.
4. One probe dropped inside `rbac/therapist_only_clinical_authorship_unauthorized`: the yaml asserts an `ActivityAide` supplying `gate_override_reason` on session enrollments gets `ERR_UNAUTHORIZED`, but PRD 4 lists `ActivityAide` as an authorized caller and 3.5 says such attempts are refused with `ERR_ENROLLMENT_GATED`. Not PRD-derivable; the instance's other three endpoint probes are kept.
5. Three `cross_cutting_complexity_layers` stub instances carry `excluded_because:` and produced no output: `cascade_chain_verified_end_to_end`, `cascade_ordering_sensitivity_on_session_cancel`, `dual_variant_switch_reconciliation`.

### Input-data defects corrected during translation (not weakened)

`preferred_group_size: "ONE_TO_ONE"` → `SOLO` (PRD 3.1 allows only SOLO/SMALL/LARGE); type-prefixed probe ids → `ABSENT_UUID*` (PRD 2.4 requires bare UUIDs, so a prefix yields 400 not 404); bare-second literals → three fractional digits; `outcome == null` on a PLANNED row → `outcome == "PLANNED"` (3.6); in `refusal_streak_cascade_depth_four` the yaml's `revision_count == 1` after entering revision → `0`, since PRD 3.3 increments `revision_count` only on `REACTIVATE`; free-text `refusal_reason` → enum members `FATIGUE`/`MOOD`; the OCC instance's claim that the resident's version "is still 3 after the successful create" contradicts PRD 3.2 → asserted `fresh_version + 1`.

### Verification run over every file

- `python3 -m compileall` clean on all 9 helper and 19 suite files; `pytest --collect-only` = 112 tests.
- Machine-checked: every test has exactly one `Design:` line, it is the docstring's last line, and every tag resolves to a real non-stub instance in the correct yaml (no dual-tagged, untagged, or dangling tags).
- Every test's PRD quote verified as a verbatim whitespace-normalized substring of `workspace/PRD.md` (112/112; one drifted quote in `test_21` was repaired).
- Zero occurrences of the forbidden design-document vocabulary, `pytest.skip`/`xfail`, or any mocking.

**Orchestrator verification:** `test_helpers/` (10 entries) and `test_suite/` (20 entries) confirmed present at the task root; no stray copies under `workspace/`.

## Step 6: Generate implementation — 2026-09-03T20:35:00.000Z

Implementation complete and verified.

### Files written

All under `workspace/implementation/` — 27 files, 4071 lines total.

**Boot / infra:** `start.sh` 8, `requirements.txt` 1, `app.py` 83
**Core:** `db.py` 164, `errors.py` 85, `response.py` 54, `middleware.py` 93, `validation.py` 147, `helpers.py` 101, `serializers.py` 281
**Domain services:** `services/numbers.py` 31, `services/constants.py` 89, `services/clinical.py` 120, `services/plans.py` 122, `services/sessions.py` 99, `services/volunteers.py` 152, `services/outings.py` 181, `services/survey.py` 155
**Routes:** `residents.py` 213, `catalog.py` 159, `plans.py` 219, `sessions.py` 186, `participation.py` 250, `volunteers.py` 339, `outings.py` 409, `council.py` 175, `survey.py` 155

### Endpoint count: 53 (exact match)

Confirmed by walking `app.url_map`: 25 GET, 24 POST, 4 PATCH. Matches the PRD 4 table line-for-line (8 resident/assessment, 6 catalog, 4 plan, 4 session, 5 participation, 7 volunteer, 10 outing, 4 council, 4 packet, 1 clock). All 9 blueprints mount under `url_prefix="/recreation"`.

### Structure

**State machines** are table-driven: each transition endpoint holds a `*_SOURCES` dict mapping the requested action/decision to the set of admitting statuses, checked at its assigned precedence rank before any action-specific precondition. The Outing carries two independent dimensions (`logistics_status` x `consent_status`); `_refresh_consent_dimension` re-derives the consent side after any roster change and performs the READY→TRANSPORT_BOOKED revert, while `/logistics` never touches the consent side. Cyclic machines (plan ACTIVE↔UNDER_REVISION, volunteer CLEARED→EXPIRED→SCREENING→CLEARED, packet COMPILED→ATTESTED→AMENDED→COMPILED, consent GRANTED↔REVOKED) are naturally expressed by the same tables with no terminal-state special casing.

**Calculations** live entirely in `services/`, never in routes. All arithmetic uses `decimal.Decimal` with `ROUND_HALF_UP` (`ROUND_CEILING` for staffing/escort ceils) via `services/numbers.py` — no float math and no built-in `round()`. Derived counters are recomputed from scratch on every mutating request rather than incrementally patched (seat waterfall, weighted supervision load, vehicle reservations, attainment percentages, provision score). A per-request `Ctx` distinguishes declared side effects (`bump()`, always advances version) from pure derived recomputes (`set_fields()`, bumps only on actual change), guaranteeing each entity advances at most one version per request.

**Validation precedence** is a single global 52-rank order from PRD 2.8, not per-endpoint: auth → path-id resolution (`load`) → body FK resolution in declared field order (`resolve_fk`) → shape/enum validation (`validate`) → OCC version echo → state → business rules. Route handlers are written as a flat sequence of guards in rank order with the rank noted inline. OCC applies on the parent only (`expected_resident_version` on plan create, `expected_vehicle_version` on transport booking, both 412). Ownership mismatches for the entity-backed roles (Volunteer, CouncilRepresentative) yield 403, never 404/422, and are checked before shape validation. Segregation of duties (packet attest != compiler) is read from the raw body ahead of shape validation.

### Smoke boot: successful

Booted on port 18598 via `PORT=18598 bash start.sh`, answered on the first poll, and exercised end to end: resident create + read-back, assessment filing (clinical re-mirror, tier recompute, resident v1→v2), program/room/vehicle/session create, volunteer lifecycle (APPLICANT → BACKGROUND_CHECK_CLEARED → ORIENTATION_COMPLETED with a future-dated `cleared_on` correctly rejected 409), assignment create → CONFIRMED with the weekly hour ledger, outing PLANNING → consent add → GRANTED → CONSENT_COMPLETE → transport-booking (vehicle reserved 1 amb + 1 wc, vehicle v1→v2) → FINALIZE → READY → DEPART → RETURN with reservations released back to 0/0, council request + quorum guard (`ERR_COUNCIL_QUORUM_NOT_MET` at 1 vote, adoption at 5 votes incrementing `council_preference_weight`), terminal re-review rejected, representative row scoping, survey packet create → inclusive window overlap rejected → compile → self-attest blocked by `ERR_SEGREGATION_OF_DUTIES` → attest by a second officer, and clock rewind rejected with `ERR_CLOCK_REWIND_FORBIDDEN`. `python3 -m py_compile` clean across all 25 `.py` files. Server killed by port lookup (`lsof -tiTCP:18598`, single PID 970994) — no pattern kill was used; port confirmed free afterward and `__pycache__` dirs removed.

Two apparent failures during smoke testing were bugs in the smoke curl script, not the implementation, and were confirmed against the PRD: `GET /recreation/programs` (no list endpoint is declared — 405 is correct) and the council review body field, which the PRD 3.9 specifies as `decision`, not `action`.

**Note on Step 5/6 concurrency:** the two agents were launched about one minute apart rather than in a single assistant message. `test_suite/`/`test_helpers/` did not yet exist when the implementation agent started, and its prompt explicitly forbade reading them, so the isolation property was preserved in substance.

## Step 7: Run tests and iterate — 2026-09-03T20:45:00.000Z

Clean sweep confirmed twice (16 consecutive green rounds).

### Summary

**Iterations run:** 3 sweeps (1 diagnostic + 2 clean confirmations), plus 2 targeted subset runs for fast failure detail. Final state: all 8 `results.$i.json` files on disk, each `passed 112 / total 112`.

**Failure set (identical in all 8 rounds of the first sweep — fully deterministic, no flakiness):** 15 tests.

**Tests deleted:** none. Every failing test's rule traced to a verbatim PRD sentence and was uniquely derivable.

**Fixes applied to `test_suite/` (test-artifact bugs, STEP 2):**
- All 19 files, 14 call sites: `ApiErrorId.ERR_<NAME>` → `ApiErrorId.<NAME>`. The enum in `test_helpers/api_errors.py` declares members *without* the `ERR_` prefix (`ENROLLMENT_GATED = "ERR_ENROLLMENT_GATED"`), so 12 of the 15 failures were `AttributeError` at assertion time — the assertion never reached the API. Normalized to the canonical member names; no assertion semantics changed.
- `test_21_lifecycle_transitions.py::test_consent_denial_blocks_outing_consent_dimension`: the intermediate assertion expected `consent_status == "CONSENT_COMPLETE"` while a sibling consent row was still `REQUESTED`. PRD 3.8 requires "every row whose `status` is `REQUESTED` or `GRANTED` is in fact `GRANTED` with `effective` true" for completion, so the PRD-faithful value is `COLLECTING`. Corrected the assertion (the test's actual subject — `CONSENT_BLOCKED` after the denial — is untouched, and this pre-state is the only one reachable since `DENIED` is admitted only from `REQUESTED`).
- `test_25_error_catalogue.py::test_finalize_with_expired_consent_rejected`: the test set `expires_on` at rider-add time and then granted without it, but PRD 3.8 says "each grant re-stores `expires_on` from the request, null when omitted" — so the PRD-faithful server nulled it, made the consent effective, and legitimately allowed `FINALIZE`. Fixed the request to supply `expires_on="2026-09-18"` on the grant decision, which is what the asserted scenario requires.

**Fixes applied to `implementation/`:**
- `routes/outings.py`, `_refresh_consent_dimension()`: guarded `apply_seat_allocation` behind `logistics_status == "TRANSPORT_BOOKED"`. It was recomputing the seat requirement on every rider add / consent decision, including while the outing was still `PLANNING`, so a refused booking left `ambulatory_seats_required = 2`. PRD 3.8 scopes this recomputation explicitly — "when a consent decision lands while `logistics_status` is `TRANSPORT_BOOKED`, the seat requirement is recomputed" — and states "**No seat is reserved at planning time**" and "On success the allocation outputs are stored on the outing" (booking and `SET_ESCORTS` remain unaffected).

**Note on the enum bug's blast radius:** because the 12 `AttributeError` tests aborted before issuing their probe request, their real assertions had never once been exercised against the server. They all pass now on their genuine assertions, not by suppression.

**Orchestrator independent verification:** all 8 `results.$i.json` present on disk (timestamped 20:23), each parsed as `passed 112 / failed 0 / total 112`. Zero occurrences of `pytest.mark.skip` / `pytest.mark.xfail` / `pytest.skip` across `test_suite/` and `test_helpers/`; 112 test functions still present, matching the Step 5 count (no silent deletions).

## Step 8: Finalize PRD — 2026-09-03T21:05:00.000Z

`PRD_FINALIZED.md` written with three surgical edits, all tracing to the single implementation fix in `<step_7_diff>` (the `apply_seat_allocation` guard in `_refresh_consent_dimension`); the three test-artifact fixes (enum member names, the `COLLECTING` pre-state, the `expires_on`-on-grant request) needed no PRD change — impl matches PRD 3.8 verbatim on all three.

### Line counts
- `PRD.md`: 530 lines / 107,132 bytes
- `PRD_FINALIZED.md`: 530 lines / 108,342 bytes
- Delta: 0 lines (0.0%), +1,210 bytes (+1.13%); 3 lines revised (347, 349, 359). Tail unchanged — still ends at `| ERR_VEHICLE_CAPACITY_EXCEEDED | 409 |`, the final row of the 5 table.

### Changes
- 3.8 "Planning the trip" — insert — the seat waterfall does **not** run at creation: all three seat figures are stored as 0 and a positive `escort_count` is not yet reflected in them — `implementation/routes/outings.py:119-121,129` (only `apply_supervision` runs at creation).
- 3.8 "The cross-dimension revert" — revise — the consent-driven seat recompute is scoped to re-derivations that *leave* the outing at `TRANSPORT_BOOKED` (explicitly including the just-reverted-from-`READY` case), covers newly added `REQUESTED` riders as well as decisions, stores any resulting shortfall without refusing, and leaves the stored seat figures untouched in every other logistics state (`PLANNING` included); vehicle counters re-based with a forced `version` bump only on a decision, re-derived softly on a `READY` decision, never on a rider add — `implementation/routes/outings.py:275-290, 364-373`.
- 3.8 "The fleet" — revise — the two counters are *re-derived from the sum* whenever one of the listed events fires, and may lag a manifest change in between (removes the false standing invariant that a rider add on a booked outing would otherwise break) — `implementation/services/outings.py:140-159`.

### Per-edit pre-edit search log

**Edit 1 — creation-time seat figures**
(a) Subject: who writes `ambulatory_seats_required` / `wheelchair_seats_required` / `seat_shortfall_total`, and their initial values.
(b) Enumerated via a repo-wide grep for all three field names plus `seat_allocation|apply_seat_allocation`: exactly four writers — `routes/outings.py:119-121` (creation, literal 0), `routes/outings.py:184-190` (booking, stored only on success), `routes/outings.py:229` (`SET_ESCORTS`, unconditional in both `PLANNING` and `TRANSPORT_BOOKED`), `routes/outings.py:289` (consent refresh, guarded). Also read `services/outings.py:91-128` and `serializers.py:155-157` (all three are exposed on the outing).
(c) Adjustment: first draft said the waterfall "does not run at planning time" — that is false for `SET_ESCORTS` while `PLANNING` (`routes/outings.py:229`, and PRD's own `SET_ESCORTS` sentence). Narrowed to "does not run **at creation**".

**Edit 2 — consent-driven recompute scope**
(a) Subject: which consent-path events recompute the outing's seat requirement and which touch the vehicle counters, and in what order relative to the `READY → TRANSPORT_BOOKED` revert.
(b) Read `_refresh_consent_dimension` (`routes/outings.py:275-290`) — order is counts → consent status → revert → supervision → seats-if-`TRANSPORT_BOOKED`; `add_rider` (`292-332`, no `recompute_vehicle_reservations` call at all); `decide_consent` (`335-374`, force-bump branch for `TRANSPORT_BOOKED`, plain `set_fields` branch for `RESERVING_LOGISTICS`); `Ctx.bump`/`set_fields` (`db.py:138-159`, force bump advances the version unconditionally, `set_fields` only when a value moves); `C.RESERVING_LOGISTICS` and `CLOSED_LOGISTICS` (`DEPARTED` unreachable here since consent activity is blocked); the `SET_ESCORTS`, `RETURN`, `CANCEL`, and booking counter callsites for parallel behavior.
(c) Adjustments: (i) replaced "lands while `logistics_status` is `TRANSPORT_BOOKED`" with "leaves the outing's `logistics_status` at `TRANSPORT_BOOKED`" so the post-revert reading is pinned; (ii) glossed "re-derivation" as decision-or-new-rider so the "any other logistics state leaves the figures untouched" clause cannot be read as also silencing `SET_ESCORTS` at `PLANNING`; (iii) added the soft `READY`-decision counter clause rather than claiming the counters are never otherwise touched, matching the non-forced `set_fields` branch; (iv) added "without refusing anything" so no implementer raises `ERR_VEHICLE_CAPACITY_EXCEEDED` outside booking.

**Edit 3 — fleet counter invariant**
(a) Subject: the standing relationship between the vehicle's two counters and the sum of outing requirements.
(b) Enumerated every `recompute_vehicle_reservations` callsite (`routes/outings.py:193, 231, 259, 267, 368, 372`) and its body (`services/outings.py:140-159`) — always a full re-derivation over `RESERVING_LOGISTICS` outings, never incremental; plus vehicle creation (`routes/catalog.py:134-135`, both at 0) and the cancel path, which leaves the cancelled outing's own requirement non-zero while dropping it out of the reserving set (matched by `test_09`'s counter assertions).
(c) Adjustment: kept the existing mover list verbatim and did not touch the booking paragraph's "is added to" phrasing; only converted the standing-equality claim into "re-derived whenever one of those events fires", which is simultaneously true of the incremental-looking booking case (counters are in sync there) and of the lagging rider-add case.

**Orchestrator verification:** `PRD_FINALIZED.md` is 530 lines, is NOT byte-identical to `PRD.md` (6 diff lines = 3 revised line pairs), and still ends at the final 5 error-table row.

## Step 9: Complete PRD — 2026-09-03T21:45:00.000Z

Step 9 was deliberately run as **three sequential file-partitioned passes** over `workspace/PRD_COMPLETED.md` rather than one monolithic scan. Rationale (orchestrator decision, no user available to consult): a single-pass Step 9 on a 4071-line implementation routinely no-ops and leaves `PRD_COMPLETED.md` byte-identical to its source, because the scanning agent runs out of working memory before it finishes walking the code. Partitioning by implementation module guarantees every file is actually read by some pass, and passing each pass's hand-over notes forward keeps the edits composable.

Partition:
- **Pass 1** — `app.py`, `db.py`, `errors.py`, `response.py`, `middleware.py`, `validation.py`, `helpers.py`, `serializers.py`, `services/{numbers,constants,clinical,plans}.py`, `routes/{residents,catalog,plans}.py`
- **Pass 2** — `routes/{sessions,participation,volunteers}.py`, `services/{sessions,volunteers}.py`
- **Pass 3** — `routes/{outings,council,survey}.py`, `services/{outings,survey}.py`

### Totals

- Source `PRD_FINALIZED.md`: 530 lines / 108,342 chars → `PRD_COMPLETED.md`: 532 lines / 124,074 chars (**+2 lines, +15,732 chars, +14.5%**)
- 98 diff lines vs `PRD_FINALIZED.md` (pass 1: 42, pass 2: 70, pass 3: 98 cumulative)
- **54 edits total: 40 ambiguity-pins, 14 mismatch-revisions** (pass 1: 16/3, pass 2: 11/7, pass 3: 13/4)
- Heading count unchanged at 28; no new sections; all 62 error-table rows intact; still ends at `| ERR_VEHICLE_CAPACITY_EXCEEDED | 409 |`

### Pass 1 changes (16 ambiguity-pins, 3 mismatch-revisions)

- 2.1 — insert — ambiguity — both auth headers are trimmed before judgement (whitespace-only = empty); role matched exactly/case-sensitively — `middleware.py:43-46`
- 2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case-alnum chars; `api_request_timestamp` is read from the **logical clock**, not wall time — `response.py:15,21`
- 2.3 — insert — ambiguity — `limit`/`offset` are not clamped: non-integer or out-of-range → `ERR_INVALID_REQUEST` 400; empty param = omitted; `has_more` = `offset + returned < total_count`; filters are opaque exact-string matches (unrecognized value → empty page, never an error), except `superseded` which honours only `true`/`false` case-insensitively — `middleware.py:62-93`, `response.py:43`, `routes/residents.py:205-208`
- 2.4 — insert — ambiguity — all stored instants use the same 3-digit UTC rendering; inbound instants may carry `Z` or `+HH:MM` and 1–6 fractional digits, normalized to UTC **truncated** to milliseconds — `db.py:14-17,69-99`, `routes/plans.py:95`
- 2.7 — insert — ambiguity — assessment ranking gets a **third** key, filing order (latest first) — `services/clinical.py:10-16`
- 2.8 — insert — ambiguity — absent/empty body is read as `{}`; non-JSON or non-object body → `ERR_INVALID_REQUEST` — `validation.py:17-29`
- 2.10 — insert — ambiguity — `expected_resident_version` is an integer >= 0 (negative = shape failure) — `routes/plans.py:31`
- 2.10 — insert — ambiguity — same for `expected_vehicle_version` — `routes/outings.py:42`
- 2.11 — revise — **mismatch** — PRD claimed every cascade-touched entity is mutated. Impl: an entity advances **at most once per request**, and a *pure recomputation* advances nothing when every re-derived value is unchanged — `db.py:138-159`, `services/plans.py:83,109,113,119`
- 3.1 — insert — ambiguity — census PATCH: all three fields optional, others unknown-field 400; the call advances `version`/`updated_at` **unconditionally** — `routes/residents.py:87-98`
- 3.2 — insert — **mismatch** + ambiguity — the transition endpoint admits `RecreationTherapist` **or** `ActivityDirector` for **every** action with no per-action narrowing; plus a definition of a resident's **live plan** — `routes/plans.py:47-48,116`, `services/plans.py:23-29`
- 3.2 — revise — ambiguity — `ACTIVATE` checks run status → resident-admitted → citation, and a superseded citation reports `ERR_PLAN_INVALID_STATE`; `ON_LEAVE` + stale citation → `ERR_RESIDENT_NOT_ADMITTED` — `routes/plans.py:124-131`
- 3.2 — insert — ambiguity — `REVISE` with `review_reason` absent → `ERR_PLAN_INVALID_STATE`, after the status gate; `review_reason`/`cycle_start_at` silently ignored on actions that don't use them — `routes/plans.py:142-152,163-164`
- 3.2 — insert — ambiguity — `REACTIVATE`'s superseded-citation refusal is also `ERR_PLAN_INVALID_STATE` — `routes/plans.py:156-158`
- 3.2 — revise — **mismatch** — `CLOSE` reworded from "reserved to an `ActivityDirector`" to attribution only — `routes/plans.py:116,169-177`
- 3.4 — revise — ambiguity — room `name` must be non-empty; `equipment_available` defaults to `[]` — `routes/catalog.py:38-43,112`
- 3.6 — insert — ambiguity — participation ranking gets a **third** key, creation order (latest first); the same three-key ranking drives the engagement window, the refusal streak, and the 2.3 facility list — `services/clinical.py:75-82`
- 3.8 (fleet metadata only) — revise — ambiguity — vehicle `label` non-empty; `ambulatory_seats`/`wheelchair_stations` required; a seat/station count on the PATCH is an unknown field (400); the amendment advances `version` unconditionally — `routes/catalog.py:45-57,142-152`
- 5 — insert — ambiguity — undocumented path → `ERR_NOT_FOUND` 404; undefined method on a defined path → `ERR_METHOD_NOT_ALLOWED` 405 — `app.py:51-62`

### Pass 2 changes (11 ambiguity-pins, 7 mismatch-revisions)

- 2.3 — revise — mismatch — `starts_from`/`starts_to` are not string-equality filters; the "single exception" claim now names two parameters — `routes/sessions.py:115-124`
- 2.3 (session-list bullet) — revise — mismatch — bounds are parsed as ISO instants, compared **inclusively** against `starts_at`, unparseable → `ERR_INVALID_REQUEST`; `_seq` tie-break added — `routes/sessions.py:116-125`
- 2.3 (roster bullet) — revise — ambiguity — the roster's `status` filter matches stored `status`, not derived `outcome`; creation-order tie-break — `routes/participation.py:146-147`
- 3.4 — revise — mismatch — the status endpoint admits all three roles and does **not** narrow per action (PRD had assigned START to the aide alone) — `routes/sessions.py:132`
- 3.4 — insert — ambiguity — a START before the clock reaches `starts_at` reports `ERR_SESSION_INVALID_STATE` — `routes/sessions.py:147-148`
- 3.4 — revise — ambiguity — `cancel_reason` pairing failures report `ERR_INVALID_REQUEST` at rank 8 (ahead of the status precondition); non-empty, <=500 chars — `routes/sessions.py:137-141`
- 3.5 — insert — ambiguity — the segregation test runs on the raw body reason *before* the session path id resolves (403 not 404); passes through when the resident/live plan/cited assessment is unresolvable; reason <=500 chars and exempt from the non-empty rule so `""` reaches the gate — `routes/participation.py:43-58, 66-68`
- 3.6 (Attendance) — revise — mismatch — `refusal_streak` "becomes 0" was a false universal; now "reads 0 whenever the documented row is the newest the walk sees" — `routes/participation.py:191`
- 3.6 (Absence) — revise — mismatch — same correction — `routes/participation.py:191`
- 3.6 (Cancellation) — revise — mismatch — "reserved to an `ActivityDirector`" softened to the 3.4 practice-not-gate reading — `routes/sessions.py:132`
- 3.7 — revise — ambiguity — volunteer `full_name` must be non-empty — `routes/volunteers.py:27`
- 3.7 — insert — ambiguity — source-status test precedes every date condition; `cleared_on`/`completed_on` optional and ignored on events with no use for them; every accepted event bumps the volunteer — `routes/volunteers.py:104-111, 161-162`
- 3.7 — insert — ambiguity — absent *or* future `cleared_on` reports `ERR_VOLUNTEER_INVALID_STATE`, not `ERR_INVALID_REQUEST` — `routes/volunteers.py:113-116`
- 3.7 — insert — ambiguity — `completed_on` defaults to the clock's date when omitted and is unbounded above; both orientation preconditions report `ERR_VOLUNTEER_INVALID_STATE` — `routes/volunteers.py:123-132`
- 3.7 — insert — ambiguity — no duplicate-assignment rule; the double-booking test excludes the target session, so one volunteer may hold two live assignments on it and each counts its own hours toward the cap — `services/volunteers.py:79`
- 3.7 — insert — ambiguity — every hour refresh advances the volunteer's `version`/`updated_at` unconditionally (`force_bump`), even when the session lies outside the ISO week — `services/volunteers.py:57-67`; `routes/volunteers.py:232,295`
- 3.7 — revise — ambiguity — `withdrawn_reason` pairing failures report `ERR_INVALID_REQUEST` ahead of every state precondition; <=200 chars, non-empty — `routes/volunteers.py:249-258`
- 3.7 — revise — mismatch — confirmation *also* re-checks screening depth + `volunteer_eligible` (PRD omitted it entirely), and the assignment's own state is judged **before** the session's — the one deliberate departure from 2.8's global ranking — `routes/volunteers.py:264-278`
- 3.7 — insert — ambiguity — the `Volunteer` ownership test is reached only after the path id resolves (→ `ERR_ASSIGNMENT_NOT_FOUND`), and the withdraw-only restriction is judged after body validation — `routes/volunteers.py:240-248`

### Pass 3 changes (13 ambiguity-pins, 4 mismatch-revisions)

- 2.3 — revise — ambiguity — outing list gains "creation order as a final tie-break" — `routes/outings.py:157`
- 2.3 — revise — ambiguity — both consent lists gain the same creation-order tie-break — `routes/outings.py:386,412`
- 2.3 — revise — ambiguity — council list gains a *descending* creation-order tie-break (`reverse=True` applies to both keys) — `routes/council.py:171`
- 3.8 Planning the trip — insert — ambiguity — `destination` must be non-empty; all six create fields non-optional, so a missing `escort_count` is `ERR_INVALID_REQUEST`, not a default of 0 — `routes/outings.py:32-39`
- 3.8 Building the manifest — insert — ambiguity — `responsible_party_name` must be non-empty — `routes/outings.py:57`
- 3.8 Booking transport — revise — **mismatch** — the turnaround widening is applied to *both* the candidate's and the incumbent's interval; the old one-sided-widening mechanism contradicted the sentence's own stated consequence — `services/outings.py:162-176`
- 3.8 Seat waterfall — revise — **mismatch** — the free pool is a live sum of `*_seats_required` over other reserving outings, not "stored counter minus this outing's reservation"; each free figure is clamped at zero below — `services/outings.py:76-111`
- 3.8 Seat waterfall — revise — **mismatch** — on booking success the vehicle's counters are re-derived from scratch over the reserving set, not incremented by this outing's two figures; vehicle `version` advances unconditionally — `routes/outings.py:193`, `services/outings.py:140-159`
- 3.8 Logistics — insert — ambiguity — `escort_count`/`cancel_reason` are each required by their own action and rejected on any other, `ERR_INVALID_REQUEST` at rank 8 ahead of the state precondition; `escort_count` 0–20; outing `cancel_reason` non-empty and <=300 chars (not 500 like a session's) — `routes/outings.py:45-53,204-217`
- 3.8 Logistics — insert — ambiguity — `SET_ESCORTS` re-runs the seat allocation even in `PLANNING`, storing any `seat_shortfall_total` without refusing — `routes/outings.py:229`
- 3.8 Logistics — insert — ambiguity — `SET_ESCORTS` on a booked outing advances the vehicle's `version` unconditionally (`force_bump=True`) — `routes/outings.py:230-233`
- 3.8 Logistics — insert — ambiguity — early `DEPART` and early `RETURN` both report `ERR_OUTING_INVALID_STATE`, and the depart-time test precedes the consent re-check — `routes/outings.py:244,254`
- 3.9 Council's voice — insert — ambiguity — `note`/`decision_note` are free text with no length ceiling and accept `""`; a representative reading another resident's request gets `ERR_UNAUTHORIZED`, but the ownership test sits after path resolution so a bogus id yields `ERR_COUNCIL_REQUEST_NOT_FOUND` — `routes/council.py:37,47,140-149`
- 3.9 Review — insert — ambiguity — a disposition omitting `decision_note` stores null, overwriting an earlier deferral's note — `routes/council.py:132`
- 3.9 Compiling — insert — ambiguity — compile declares no body field: empty body succeeds, any field is `ERR_INVALID_REQUEST` — `routes/survey.py:86`
- 3.9 Cohort — insert — ambiguity — governing-plan selection has a third tie-break, creation order — `services/survey.py:31-35`
- 3.9 Attestation — insert — ambiguity — `remediation_note`/`amendment_reason` are uncapped free text and are ignored, never rejected, on the action that has no use for them — `routes/survey.py:26-30,128-133`
- 3.9 Logical clock — insert — **mismatch** — `current_utc` is retained at full parsed precision (up to 6 fractional digits) instead of being truncated to milliseconds as 2.4 claims for body instants; sub-millisecond fractions therefore count for the rewind test and for every later clock comparison while rendered stamps show 3 digits — `routes/survey.py:154`, `db.py:83-99`

### Cross-pass hand-over verdicts

- Pass 2 on pass 1's `skip_engagement`-on-`ABSENT` note: pass 1's judgment confirmed — `engagement_index` excludes both `PLANNED` and `ABSENT` rows, so a `PLANNED → ABSENT` transition provably cannot move it; PRD's "left untouched" is observationally exact.
- Body-read-before-path-id ordering was never pinned as a universal rule: the codebase is genuinely inconsistent (`routes/plans.py:117` and `routes/volunteers.py:102` read the body first; `routes/residents.py:90` and `routes/sessions.py:133` resolve the path id first) and the only observable divergence is malformed JSON vs a 404. Only the three locally-consistent, observable orderings were pinned (3.5 segregation-before-path-resolution, assignment ownership/withdraw-only precedence, council ownership-vs-404).
- Pass 3 on Step 8's three 3.8 sentences: all three verified correct against `_refresh_consent_dimension` and `decide_consent`'s `force_bump`-vs-soft-re-derive split; not re-litigated. Pass 3's waterfall/booking edits were written to reference the fleet paragraph's re-derivation rule so they compose with Step 8's text.
- 2.8 rank table and its consequences paragraph: left untouched by all three passes — every error the implementation raises already sits at a rank matching the code's evaluation order (the single documented departure, assignment-state-before-session-state, is pinned inline in 3.7 instead).

### Orchestrator verification

`PRD_COMPLETED.md` is 532 lines / 124,074 chars, is NOT byte-identical to `PRD_FINALIZED.md` (98 diff lines — the scan demonstrably ran in all three passes), retains 28 headings and all 62 error-table rows, and ends at the final 5 error-table row. Step 9 touched only the PRD, so the Step 7 clean sweep (`results.{1..8}.json`, each 112/112) remains valid.

## Pipeline complete — 2026-09-03T21:45:00.000Z

All nine steps finished. Final artifacts: `SCAFFOLD.yaml` (3080), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1295), `SCAFFOLD_CORNER_DESIGN.yaml` (3943), `test_helpers/` (9 modules, 1519 lines), `test_suite/` (19 files, 112 tests), `workspace/PRD.md` (530), `workspace/PRD_FINALIZED.md` (530), `workspace/PRD_COMPLETED.md` (532), `workspace/implementation/` (27 files, 4071 lines, 53 endpoints), `workspace/implementation/results.{1..8}.json` (each 112/112).
