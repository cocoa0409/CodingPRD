# Worklog — task_1254_construction_materials_testing_special

## Step 1: Create Task Directory — 2026-08-12T09:39:00.000Z

Pre-assigned output folder `tasks/task_1254_construction_materials_testing_special` with `workspace/` subdirectory already exists. Step 1 auto-index scan skipped per instructions; treating Step 1 as done.

## Step 2: Generate Scaffold — 2026-08-12T10:26:00.000Z

All three scaffold artifacts are generated and lint-clean. (Note: a pre-existing `worklog.md` and empty `workspace/` directory were already in the task dir; I did not create or touch them.)

## What was built

**`/home/ubuntu/github/CodingPRD/tasks/task_1254_construction_materials_testing_special/SCAFFOLD.yaml`** (§1.0–§1.7)
- **Profile**: compliance_audit (primary) × workflow_orchestration (secondary); layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; flat topology; cyclic state shape; segregation_of_duties role model; immediate consistency.
- **11 entities**: Project (computed posture + letter fields), SSIRevision, ScopeItem, Technician (embedded certifications), InspectionAssignment, FieldTest, LabSample, Lab, NonconformanceReport, DailyInspectionReport, DiscrepancyTicket.
- **44 endpoints**, **25 error codes**, 9 calculations, 9 ordered validations, 7 roles (Technician is `entity_backed:Technician`; the rest opaque).
- Key mechanics: ACI-style concrete acceptance (MOVING_AVERAGE vs INDIVIDUAL_SET with per-set 10-psi nested rounding pinned), soil proctor dual variants (STANDARD 95.0 vs MODIFIED 92.0), break-window tolerance with inclusive boundary (7d→6h, 28d→24h, 56d→48h), 4-input NCR escalation score with STRUCTURAL short-circuit (sweep at ≥70), posture gate `project_posture_derivation` gating the final letter, technician half-open window overlap vs lab aggregate day-capacity, OCC on Project.version for SSI approval supersede, logical clock endpoint with the mandated `2026-05-01T00:00:00Z` default.

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — 18 instances, exactly 2 per rule, each with falsifiable `distinguishing_aspect` and fully structured `setup_api_calls`/`trigger`/`assert` chains; all formula-derived asserts are pre-computed literals (e.g., 117.7/124.0 → 94.9 vs 92.7 divergence; 4206/4203/4205 nested-rounding verdict flip at f'c 4205; escalation score exactly 70 vs 68).

**`SCAFFOLD_CORNER_DESIGN.yaml`** — 41 full instances + 6 `excluded_because` stubs across all nine claim-extraction-guide sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model), covering terminal lockdowns, invalid transitions, RBAC denials, SoD, routing, OCC stale-version, envelope/pagination, and immediate consistency.

## Verification
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
647 calls scanned across 18 difficulty + 41 corner instances; zero violations. Instance names unique across both design files; no forbidden concurrency vocabulary; file split honored (single top-level keys in each design file, neither key in SCAFFOLD.yaml).

Two design decisions worth noting: (1) one FK-adjacent error (`ERR_ASSIGNMENT_ALREADY_COVERED`) was removed during the audit because the DIR uniqueness rule at priority 7 makes it unreachable — the coverage check folds into `ERR_REFERENCE_MISMATCH`; (2) the endpoint count (44) exceeds the Expert-band guideline of 20–32, deliberately — the user asked for harder-than-expert, and the scenario's eight mandated workflow areas are all preserved, with difficulty concentrated in the calculation/validation/cascade density rather than entity count.

## Step 3: Copy Shared Files — 2026-08-12T10:26:13.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-08-12T10:37:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1254_construction_materials_testing_special/workspace/PRD.md` (~560 lines). The withheld design files were never opened.

**Document structure** — domain-derived, not template-copied:
- §1: 3-paragraph introduction (regulatory evidence-chain angle)
- §2: ten subsections — RBAC with per-role identity translation (2.1), verbatim response-envelope contract (2.2, confirmed byte-identical to source), pagination (2.3), resource identity/timestamps/versioning (2.4), the logical clock with the 2026-05-01T00:00:00Z startup default (2.5), measurement precision and rounding (2.6), OCC on SSI approval (2.7), nested path resolution and same-project reference scope (2.8), the nine-tier validation precedence (2.9), and the project completion gate (2.10)
- §3: nine workflow subsections organized chronologically along a project's life (project + SSI, roster/certifications, dispatch, field tests, lab sample chain, NCRs + escalation sweep, daily reports, discrepancies, posture + final letter) — all 44 endpoints' rules, all 9 calculations with constants (500-psi floor offset, 0.90 ratio, window of 3, 95.0/92.0 thresholds, 6/24/48/12-hour tolerances, escalation bases 20/40/60, rates 2/3/15, threshold 70, remediation 30/14/7 days) expressed in precise prose with no operator syntax or fuzzy words
- §4: 44-row endpoint table, 4 columns only
- §5: 24-row error catalogue, 2 columns only, statuses per scaffold `errors[]` (including the 400 for `ERR_VALIDATION` and 422s for `ERR_SSI_NOT_APPROVED`/`ERR_REFERENCE_MISMATCH`/`ERR_BREAK_DATE_MISMATCH`)

**Hard contract reports** (mechanically verified via script):

```
Field coverage check:
- entities[].fields: 78 required, 78 present, 0 missing
- endpoints[].request_body: 49 required, 49 present, 0 missing
- endpoints[].query_params: 8 required, 8 present, 0 missing
- sub-identifiers (measured_values keys, cert triple keys, result_details keys, clock/sweep outputs): 18 required, 18 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 9 checked, 9 expressed in §2.9 ordered prose, 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed (write operation + expected_project_version + ERR_STALE_VERSION/412 + "no other endpoint takes a version field"), 0 missing
- state_machines[].transitions: 23 checked across 8 machines, 23 fully expressed (states, preconditions with error ids, side effects incl. cascades and compensating actions), 0 missing
- calculations[]: 9 checked, 9 fully expressed with constants embedded in context, 0 missing
- validations[] conditions: all matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (approve supersession cascade, record-break triple cascade, verify compensating decrement, DIR coverage, sweep escalation), 0 missing
- entities[].fields[] structured content: defaults, initial values, nullability, enum membership reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups (APPROVE/REJECT, ACCEPT/REJECT, VERIFIED/REJECTED, STANDARD/MODIFIED, MOVING_AVERAGE/INDIVIDUAL_SET, cancel/requeue) at equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 374
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional spot checks passed: all 24 error IDs appear in prose, all 7 role names exact, all enum/state values present as exact UPPERCASE strings, no pseudo-operators (`>=`, `==`, `+=`) leaked into prose, no fuzzy words ("approximately", "roughly", etc.), and §2.2 matches the fixed verbatim block byte-for-byte.

## Step 5: Generate Unit Tests — 2026-08-12T11:08:00.000Z

Test generation for task_1254 is complete.

**Stage 1 — `test_helpers/`** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1254_construction_materials_testing_special/test_helpers/`):
- `types.py` — 11 entity TypedDicts + 16 status/role enums (all entities carry common fields here)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint in PRD §4 (37 endpoints, `/api` prefix, empty-body POSTs send `{}`)
- `api_errors.py` — 24 `ApiErrorId` values + HTTP status map from the PRD §5 catalogue, registered via `set_error_http_status_map` (note: `ERR_BREAK_DATE_MISMATCH` = 422 per the PRD §5 table)
- `assertions.py` — per-entity assertions, `assert_iso8601_millis` (PRD §2.4 three-fractional-digit rule), `assert_project_invariants` (posture gates)
- `factories.py` — payload factories incl. `soil_scope_item`/`concrete_scope_item`/`weld_scope_item`/`bolt_scope_item`
- `constants.py` — all PRD thresholds (95.0/92.0 compaction, 10-psi grid, 0.90 high-f'c ratio, 6/24/48/12h tolerances, escalation bases/rates/threshold 70, remediation days)
- `test_users.py` — 6 opaque-role header constants + `make_technician_headers(id)` for the entity-backed Technician role
- `fixtures.py` — composite chains: `setup_approved_project`, `setup_dispatched_assignment`, `setup_concrete_assignment`, `setup_open_soil_ncr`, `setup_minor_ncr_twice_rejected` (escalation scenario), `setup_ready_for_letter`, plus granular helpers (`record_soil_test`, `cast_sample`, `schedule_sample_break`, `verify_ncr`, OCC-threaded `approve_revision`, etc.)
- `__init__.py` barrel export

**Stage 2 — `test_suite/`**: 8 files, **77 tests**, all collecting cleanly (`pytest --collect-only` passed).

Coverage audit results:
- Queue A: all 18 difficulty instances have exactly 2 tests (36 tests)
- Queue B: all 41 non-stub corner instances have 1 test (41 tests); the 6 `excluded_because` stubs were skipped and their `difficulty_instance` pointers verified to resolve
- Every docstring ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line resolving to a real instance
- All 114 PRD citations verified verbatim against `PRD.md` (whitespace-normalized grep, 0 misses)
- No `skip`/`skipif`/`xfail` markers; no scaffold references in comments/docstrings

PRD-first adjudication notes (deliberate weakenings where PRD leaves design space open):
- `create_project_defaults_applied`: asserts all PRD-pinned defaults (status/posture/counts/null letter fields, UUID, 3-fractional-digit timestamps) but not `version == 1` — PRD §2.4 does not pin the initial version value
- `lab_sample_computed_break_due_at`: asserts `break_due_at` equals 2026-05-08T08:00:00 via prefix match, tolerating optional millisecond serialization (format not pinned for computed datetimes)
- Both priority-pair difficulty instances are testable because PRD §2.9 explicitly fixes the evaluation order ("evaluated in a fixed order so the surfaced error is deterministic") — cited verbatim in those docstrings

## Step 6: Generate Implementation — 2026-08-12T11:08:00.000Z

Implementation complete. Three files in `/home/ubuntu/github/CodingPRD/tasks/task_1254_construction_materials_testing_special/workspace/implementation/`:

- **`start.sh`** (executable): guards `pip install` behind `python3 -c "import flask"`, then `exec python3 app.py` in foreground. Binds 0.0.0.0 on `$PORT` (default 10000).
- **`requirements.txt`**: Flask 3.x.
- **`app.py`** (~1500 lines): full Flask app with in-memory store, no seeding, logical clock starting at exactly `2026-05-01T00:00:00Z`.

Key implementation details:

- **Envelope**: `meta`/`response_type`/`data`; pagination fields `limit`/`offset`/`total_count`/`has_more` in `meta` for lists; error body uses `error_id`/`message`.
- **Auth**: `X-User-ID` + `X-User-Role` headers; 7 roles; `Technician` is the entity-backed role (ownership compares `X-User-ID` to `technician_id` on assignment for complete, field-test create, lab-sample create).
- **Sequencing**: A `_seq` monotonic counter (stripped from output) gives stable created-order sorting even when multiple scope items are created in the same request within the same millisecond.
- **State machines**: All eight implemented — SSIRevision (DRAFT/SUBMITTED/APPROVED/REJECTED/SUPERSEDED with OCC via `expected_project_version` and prior-approval supersede), InspectionAssignment (with requeue loop on DISPATCHED→REQUESTED), FieldTest (RECORDED/VOIDED with `ERR_TEST_NOT_VOIDABLE` on nonconforming), LabSample (CAST/BREAK_SCHEDULED/REPORTED/DISCARDED with capacity + date-equality gates), NonconformanceReport (OPEN/CORRECTION_SUBMITTED/ESCALATED/VERIFIED with SoD and evidence-reference checks), DailyInspectionReport, DiscrepancyTicket (with routing-role check and round counter), Project (ACTIVE/COMPLETED cyclic via issue/void letter).
- **Calculations** (all round-half-up via `Decimal`):
  - `concrete_set_average`: mean → 10-psi grid, per-set first.
  - `concrete_acceptance_evaluation`: MOVING_AVERAGE (window of last ≤3 set averages on same pinned scope item, ordered by break_due_at then created_at, 10-psi grid mean) and INDIVIDUAL_SET; floor = `fc-500` when `fc≤5000` else `round_half_up(fc*0.90)`.
  - `soil_compaction_evaluation`: 1-decimal round-half-up, 95.0/92.0 thresholds by proctor method.
  - `simple_field_evaluators`: WELD_VISUAL defect_count==0; BOLT_TENSION bolts_tested≥1 and bolts_passed==bolts_tested.
  - `break_window_tolerance`: {7d:6h, 28d:24h, 56d:48h, default:12h}, inclusive.
  - `ncr_escalation_score`: STRUCTURAL past deadline → 100; else base + 2·days_open + 3·days_past_deadline + 15·rejections, capped at 100, escalates at ≥70.
  - `project_posture_derivation`: LETTER_ISSUED → NONCONFORMANCE_OUTSTANDING → READY_FOR_LETTER (4 gates) → IN_PROGRESS, evaluated in that order.
  - `lab_day_load`: count only BREAK_SCHEDULED on the day; rejects at load ≥ capacity.
- **Side effects**: Nonconforming field test/lab break auto-creates NCR with STRUCTURAL/MAJOR severity; out-of-tolerance break additionally creates a separate MINOR NCR; NCR numbers are per-project `NCR-0001…`; deadline = detected_date + remediation days.
- **Validation priority**: Auth → role/ownership → existence → state → technician fitness → temporal → uniqueness → referential → capacity. `ERR_VALIDATION` (400) for malformed payloads.
- **Optimistic concurrency**: Only `POST /api/ssi-revisions/{id}/approve` takes `expected_project_version`, returning 412 `ERR_STALE_VERSION`; both APPROVE and REJECT bump `Project.version`.

Smoke-tested end-to-end: project creation, SSI draft/submit/approve with stale-version rejection, technician certifications, dispatch gate (inactive/missing/insufficient/expired certs), window double-booking with adjacency allowed, soil evaluation at exactly 95.0 threshold (passes), NCR auto-creation, SoD enforcement on verify, moving-average concrete acceptance across three sets, requeue/cancel loop, DIR submission, posture transitions, letter issuance + post-completion gate + void + re-issue, clock set, daily sweep.

Orchestrator route-parity check (pre-Step 7): all 44 (method, path) route pairs in the implementation match SCAFFOLD.yaml's declared endpoints exactly (0 missing, 0 extra).

## Step 7: Run Tests and Iterate — 2026-08-12T11:15:57.000Z

All 8 rounds pass 77/77. Exiting with the summary.

## Summary

- **Iterations run**: 2 (iteration 1: 76/77 across all 8 rounds with one consistent failure; iteration 2: 77/77 across all 8 rounds).

- **Tests deleted**: none.

- **Failing test (union across rounds, identical in all 8)**: `TestTechnicianWindowOccupancy.py ... TestValidationPrecedence::test_overlapping_window_reports_double_booking_before_reference_scope` (in `/home/ubuntu/github/CodingPRD/tasks/task_1254_construction_materials_testing_special/test_suite/test_02_dispatch_certification_and_windows.py`). Expected `ERR_TECHNICIAN_DOUBLE_BOOKED`; server returned `ERR_REFERENCE_MISMATCH`.

  - STEP 1a coverage: PRD.md line 110 verbatim — "Sixth, temporal occupancy: technician window overlap on assignment creation ... (`ERR_TECHNICIAN_DOUBLE_BOOKED` ...) ... Eighth, cross-reference scope (`ERR_REFERENCE_MISMATCH`, `ERR_SSI_NOT_APPROVED`)."
  - STEP 1b unique derivability: holds — the tier ordering is explicit and numeric; a faithful PRD-only reader puts the double-booking check before the cross-reference check.
  - STEP 2 test consistency: test is faithful (overlap on the technician's calendar + a scope item from another project; PRD tier 6 must surface before tier 8).

- **Fixes applied to `test_helpers/`**: none.

- **Fixes applied to `implementation/`**: `/home/ubuntu/github/CodingPRD/tasks/task_1254_construction_materials_testing_special/workspace/implementation/app.py`, function `create_assignment()` — reordered validation to match PRD §2.9 tier order: technician existence (`ERR_NOT_FOUND`, tier 3) → `ERR_PROJECT_COMPLETED` (tier 4) → technician window overlap `ERR_TECHNICIAN_DOUBLE_BOOKED` (tier 6) → `ERR_SSI_NOT_APPROVED` / `ERR_REFERENCE_MISMATCH` (tier 8). Previously the referential checks ran before the temporal check, surfacing tier-8 errors ahead of tier-6.

Orchestrator verification: 8 results files on disk, all `passed=77 total=77 failed=0`.

## Step 8: Finalize PRD — 2026-08-12T11:21:00.000Z

All verification complete. The final state shows 77/77 tests passing, and PRD_FINALIZED.md is byte-identical to PRD.md.

## Summary

**PRD.md vs PRD_FINALIZED.md**: 274 lines vs 274 lines — 0% delta (byte-identical copy).

### Changes made: none

The single `<step_7_diff>` item is an **implementation fix, not a PRD silence or PRD mismatch**:

- `workspace/implementation/app.py` `create_assignment()` (lines 875-940) was reordered in Step 7 so validation follows PRD §2.9's tier order: technician existence (`ERR_NOT_FOUND`, tier 3) → `ERR_PROJECT_COMPLETED` (tier 4) → `ERR_TECHNICIAN_DOUBLE_BOOKED` (tier 6) → `ERR_SSI_NOT_APPROVED` / `ERR_REFERENCE_MISMATCH` (tier 8). The code was brought into conformance with the PRD, not the reverse.

Per Step 7's own analysis (STEP 1a/1b): PRD.md line 110 covers this verbatim — §2.9 states "Sixth, temporal occupancy: technician window overlap on assignment creation ... (`ERR_TECHNICIAN_DOUBLE_BOOKED` ...)" and "Eighth, cross-reference scope (`ERR_REFERENCE_MISMATCH`, `ERR_SSI_NOT_APPROVED`)" — and unique derivability holds because the tier ordering is explicit and numeric. Per the task method ("Where PRD already determines behavior, keep prose verbatim" and "not every item is a PRD silence"), no edit is warranted.

### Pre-edit search log (for the one candidate edit, which was evaluated and rejected)

- **(a) Subject identified**: validation-error precedence inside `POST /api/assignments` — specifically whether `ERR_TECHNICIAN_DOUBLE_BOOKED` must surface before `ERR_SSI_NOT_APPROVED`/`ERR_REFERENCE_MISMATCH`, and whether any PRD wording needed sharpening.
- **(b) Implementation paths enumerated and read**:
  - `workspace/implementation/app.py` lines 875-940 (`create_assignment` — the Step 7 fix site): order is `require_role` (tiers 1-2) → malformed-payload `ERR_VALIDATION` (required fields, ISO date, HH:MM times, `end_time > start_time`) → `get_project_or_404` (tier 3) → technician existence (tier 3) → `ERR_PROJECT_COMPLETED` (tier 4) → window-overlap loop over `REQUESTED`/`DISPATCHED` same-technician same-date assignments with half-open `_windows_overlap` (tier 6, lines 903-914) → `ERR_SSI_NOT_APPROVED` then `ERR_REFERENCE_MISMATCH` (tier 8, lines 915-922).
  - Helpers: `get_auth`/`require_role` (lines 236-248, unauthenticated-before-forbidden), `req_str`/`parse_date`/`parse_time_hhmm` (malformed-payload checks before business rules), `_windows_overlap` (lines 870-872, half-open `[s,e)` semantics matching PRD §3.3's "windows that merely touch ... are both allowed").
  - All other raise-sites of the involved error codes (grep over app.py): `ERR_PROJECT_COMPLETED` at lines 668, 745, 769, 981, 1034, 1125, 1174, 1252, 1560, 1648 (state tier, no interaction with tier 6/8 ordering); `ERR_REFERENCE_MISMATCH` at lines 1515-1520 (NCR evidence), 1571-1581 (daily-report citations), 1652-1655 (discrepancy scope item) — all pure tier-8 sites with no competing tier-6 check, so §2.9's wording already describes them correctly.
  - Auxiliary evidence: `test_suite/test_02_dispatch_certification_and_windows.py` lines 158-194 — the previously failing test cites PRD §2.9 verbatim as its basis, confirming the test (and the fixed impl) derive from existing PRD text.
- **(c) Wording adjustment**: none. Every enumerated path is exactly described by current PRD §2.9's numbered tiers plus §2.9's final paragraph (malformed payloads first) and §3.3's window semantics. The fixed implementation exhibits no behavioral choice the PRD leaves open, so PRD_FINALIZED.md keeps the prose verbatim.

**Deliverable**: `workspace/PRD_FINALIZED.md` — a verbatim copy of PRD.md. A fresh implementer reading it produces the current implementation's behavior, because the only Step 7 divergence was the implementation violating an already-explicit, numerically-ordered PRD precedence contract — now corrected.

## Step 9: Complete PRD — 2026-08-12T11:34:59.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1254_construction_materials_testing_special/workspace/PRD_COMPLETED.md` written (copied from PRD_FINALIZED.md, edited in place only).

**Sizes**: PRD_FINALIZED.md 274 lines / 41,759 chars → PRD_COMPLETED.md 275 lines / 46,293 chars; char-delta **+4,534**. No sections added or removed; all changes are in-paragraph inserts/revisions.

**Counts**: 21 ambiguity-pins, 6 mismatch-revisions (27 changes total).

**Changes** (impl = `workspace/implementation/app.py`):

- §2.2 — insert — ambiguity — unknown route / unsupported method returns the error envelope with `ERR_NOT_FOUND`, HTTP 404 — app.py:202-219
- §2.3 — insert — ambiguity — non-numeric `limit`/`offset`, limit outside 1–100, negative `offset` → `ERR_VALIDATION`; list filters are exact-match — app.py:297-310
- §2.4 — revise — ambiguity — `version` starts at 1 (was "its initial value") — app.py:147
- §2.5 — insert — ambiguity — clock accepts any parseable ISO 8601 instant, forward or backward — app.py:1770-1779
- §2.7 — insert — ambiguity — `expected_project_version` must be an integer; decision-endpoint check order is revision-state → payload validation → stale-version → completion gate — app.py:757-769
- §2.8 — insert — ambiguity — unresolvable body references: `ERR_NOT_FOUND` for `technician_id`/`assignment_id`/`lab_id` on creation; `ERR_REFERENCE_MISMATCH` for scoped citations (scope_item at assignment creation, daily-report assignment citations, discrepancy `scope_item_id`, verification evidence) — app.py:898-900, 918-920, 1240-1249, 1569-1571, 1650-1652, 1513-1515
- §2.9 — revise — mismatch — tier-2 split: role-list `ERR_FORBIDDEN` before path resolution; entity-backed ownership and `ERR_DISCREPANCY_ROUTING` after path resolution, before state; `ERR_SEGREGATION_OF_DUTIES` after the correction's state check (PRD had all three at tier 2 before existence) — app.py:1027-1031, 1689-1696, 1505-1510
- §2.9 — insert — ambiguity — within the state tier, the target's own state check precedes the project-completion gate — app.py:977-981, 1030-1034, 739-745
- §2.9 — revise — mismatch — tier-8 order pinned as `ERR_SSI_NOT_APPROVED` then `ERR_REFERENCE_MISMATCH` (impl checks approved-revision absence first) — app.py:916-922
- §2.9 — revise — mismatch — malformed-payload rule no longer claims validation precedes all business rules: creation endpoints validate payload first; SSI-revision creation applies the completion gate first; other resource-targeting endpoints run existence+state before payload, except correction verification which validates `outcome` first — app.py:663-677, 1497-1506
- §2.10 — revise — mismatch — completion gate no longer covers "every mutation": pinned to the enumerated set impl enforces (SSI create/submit/approve, assignment create/dispatch/complete, field-test record/void, lab-sample log, daily report, discrepancy raise), with cancel, break schedule/record/discard, NCR correction/verification, acknowledgement, discrepancy respond/resolve explicitly still permitted under `COMPLETED` — app.py:1004-1021, 1296-1442, 1467-1538, 1619-1726 (no completion checks)
- §3.1 — revise — ambiguity — `specified_fc_psi` pinned as an integer — app.py:670
- §3.2 — insert — ambiguity — deactivating a non-`ACTIVE` technician → `ERR_INVALID_STATE` — app.py:859-860
- §3.3 — insert — ambiguity — `ERR_SSI_NOT_APPROVED` check precedes scope-item examination; unresolvable `scope_item_id` → `ERR_REFERENCE_MISMATCH`; unknown `technician_id` → `ERR_NOT_FOUND` — app.py:898-922
- §3.3 — insert — ambiguity — with multiple same-method certifications, the highest-level one is evaluated for level and currency — app.py:986-990
- §3.3 — insert — ambiguity — cancel body optional; `requeue` honored only as JSON boolean `true`; `requeue` on a `REQUESTED` assignment cancels it — app.py:1010-1019
- §3.3 — insert — ambiguity — `ERR_NO_RESULT_RECORDED` gate satisfied by any field test (even later voided) or any lab sample in any status — app.py:1035-1038
- §3.4 — insert — ambiguity — field test against a `CONCRETE_STRENGTH` scope item → `ERR_VALIDATION` — app.py:1127-1128
- §3.4 — revise — mismatch — `result_details` contents pinned per method (soil: `relative_compaction_pct`/`threshold_pct`/`proctor_method`; weld: `defect_count`; bolt: `bolts_tested`/`bolts_passed`) replacing the inaccurate "(inputs, threshold, method)" — app.py:1084-1103
- §3.5 — insert — ambiguity — unresolvable `assignment_id`/`lab_id` → `ERR_NOT_FOUND`; non-concrete scope item → `ERR_VALIDATION` — app.py:1240-1255
- §3.5 — insert — ambiguity — break `result_details` shape: `individual_floor` under both variants, plus `moving_average_psi` and `window` under `MOVING_AVERAGE` — app.py:1400-1413
- §3.6 — revise — ambiguity — fresh NCR also has `escalation_score` zero — app.py:567
- §3.6 — insert — ambiguity — `evidence_field_test_id` examined and stored only on a `VERIFIED` outcome; ignored on `REJECTED` — app.py:1511-1527
- §3.6 — revise — ambiguity — `days_open` floored at zero like days-past-deadline — app.py:1793-1795
- §3.8 — insert — ambiguity — optional discrepancy `scope_item_id` must belong to any revision of the same project, else `ERR_REFERENCE_MISMATCH` — app.py:1649-1655
- §3.8 — revise — mismatch — any technician may resolve a ticket, not only the raiser — app.py:1705-1708
- §3.9 — insert — ambiguity — voiding a letter retains `letter_issued_at` and `letter_issued_by` — app.py:1758-1763

Key finding worth flagging: the two substantive mismatches were (1) §2.10's "every mutation is rejected under COMPLETED" — impl actually gates only 11 of ~20 project-scoped mutations, and (2) §2.9's precedence claims — impl runs path-existence before entity-backed authorization, segregation-of-duties after the state check, and payload validation after state checks on most transition endpoints. Both PRD passages were revised inline to match impl.
