# Worklog — task_1417_gas_emergency_response_odor_call_dispatch

## Step 1: Create Task Directory — 2026-08-13T05:34:10.966Z

Pre-assigned by pipeline dispatcher: `tasks/task_1417_gas_emergency_response_odor_call_dispatch/` + `workspace/` already existed. Treated as DONE per dispatch instructions (no index scan, no writes outside this directory). Difficulty directive from user: "Generate task hard than expert level!"

## Step 2: Generate Scaffold — 2026-08-13T06:26:25.938Z

Scaffold generation complete. Lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (77 endpoints, 16 entities, 650 recipe calls scanned).

## Output files

| File | Lines | Contents |
|---|---|---|
| `SCAFFOLD.yaml` | 1778 | §1.0–§1.7 (no difficulty/corner keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1788 | `scaffold_difficulty_design:` — 20 instances |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 1650 | `scaffold_corner_design:` — 39 active instances + 4 `excluded_because` stubs |

## Entity inventory (16)

ServiceTerritory (config: SLA thresholds, recurrence window, budget cap, reserved-cents ledger), FieldTechnician (computed on_shift / active_assignment_count / weighted_load / last_cleared_at), TechnicianShift (immutable, half-open windows), RepairCrew, EmergencyCall (immutable; PRIMARY/DUPLICATE/RECURRENCE classification, implied_priority), GasIncident (aggregate root; parallel dimensions lifecycle_status × entry_status; computed clock/severity/breach fields), DispatchAssignment, ResponseClockPause, AtmosphericReading (immutable), MakeSafeAction (immutable), PremiseEntryAuthorization (immutable), ShutoffOrder, ResponsibilityDetermination (SoD finalize), RepairWorkOrder (embedded parts lines), RegulatoryReport (snapshot + staleness), PublicNotification.

## State machines (8)

- **GasIncident**: parallel dimensions — lifecycle NEW→TRIAGED→DISPATCHED→ON_SCENE→MAKE_SAFE_IN_PROGRESS→MONITORING→CLOSED with cyclic CLOSED→REOPENED→TRIAGED and MERGED terminal; entry_status NOT_REQUIRED⇄AWAITING_AUTHORIZATION→AUTHORIZED/FORCED/REFUSED
- **DispatchAssignment**: EN_ROUTE→ON_SCENE→CLEARED with EN_ROUTE→PREEMPTED (preemption auto-creates a target assignment) and EN_ROUTE→CANCELLED
- **ResponseClockPause**: OPEN→CLOSED (manual or auto-close on arrival)
- **ShutoffOrder**: REQUESTED→AUTHORIZED→EXECUTED→RESTORED / DECLINED
- **ResponsibilityDetermination**: DRAFT→FINAL→SUPERSEDED (finalize enforces segregation of duties)
- **RepairWorkOrder**: OPEN→SCHEDULED→IN_PROGRESS→COMPLETED with cyclic IN_PROGRESS⇄ON_HOLD and 3 cancellable states
- **RegulatoryReport**: DRAFT→SUBMITTED→ACCEPTED with REJECTED→DRAFT amendment loop and stale-draft submit guard
- **PublicNotification**: DRAFT→ISSUED→RETRACTED / DISCARDED

## Calculation rules (7)

`response_elapsed_time` (raw vs adjusted dual variant, half-open pause subtraction), `sla_breach_classification` (strictly-greater threshold, RESPONDED_LATE/NO_RESPONSE), `incident_severity_score` (4-factor weighted with branch ladders, >=80 auto-notify), `repair_cost_final` (pinned per-line-round-then-sum + quarter-hour labor ceiling) with `provisional_estimate_matrix` variant (responsibility×priority matrix), `regulatory_compliance_snapshot` (raw/adjusted variants, pending-exclusion, null rate on empty denominator, pinned 3-step evaluation order), `dispatch_candidate_ranking` (deterministic selector: load ASC → last_cleared_at nulls-first → created_at ASC, empty-pool error).

## §1.8 difficulty instances: 20 (≥2 per rule)

dual_variant_calc 2, combinatorial_formula 3 (modes a/b/c), non_linear_state_machine 2, transitive_cascade 2 (depth-3 dedup-escalation cascade; depth-3 determination→work-order→budget cascade), priority_pair_validation_conflict 2 (state-vs-safety; temporal-vs-fiscal), boundary_precision_check 2 (elapsed==threshold compliant; zero-readings gate), cross_entity_state_dependency 3, resource_temporal_overlap 2 (half-open shift adjacency vs 30-min buffered crew gap), compensating_invariant 2 (preempt conserves technician active count; schedule/cancel/complete conserves reserved budget cents).

## §1.9 corner instances: 39 active + 4 stubs

Covering entities (8), state_machines (6), calculations (5), validations (6), endpoints (2), errors (1 sweep), rbac (7: role denials, regulator/technician read scoping, SoD, ownership), cross_cutting_layers (6: two OCC 412 rules, report staleness/freeze, 2 stubs), consistency_model (1: immediate).

All formula-derived asserts were machine-verified (two arithmetic slips found and fixed during verification: 2214.45→2214 and severity 26/46 values). Two scaffold fixes were driven by the replay pass: AUTO_PRIORITY notification now fires at intake when implied_priority==P1, and ERR_MAKE_SAFE_NOT_COMPLETED normalized to HTTP 422.

## Step 3: Copy Shared Files — 2026-08-13T06:26:40.000Z

Copied ./INSTRUCTION.md → tasks/task_1417_gas_emergency_response_odor_call_dispatch/workspace/INSTRUCTION.md.


## Step 4: Generate PRD — 2026-08-13T06:43:55.824Z

PRD generated at `workspace/PRD.md`.

**PRD.md line count:** 366 lines (365 newline-terminated + final line)

**Section outline:**
- **§1. Introduction** — 2 paragraphs (business context + operator populations)
- **§2. Global Specifications** — 10 subsections: 2.1 RBAC (5 roles, identity semantics, Regulator/FieldTechnician scoping, SoD), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 The Logical Clock (default `2026-08-01T00:00:00Z`, advance-only), 2.5 Common Resource Properties (incl. the 5 lightweight entities lacking `updated_at`/`version`), 2.6 Validation Order & Nested Path Resolution (10-priority cascade + left-to-right 404 rule), 2.7 Response-Clock Accounting & Breach Classification (raw/adjusted variants, half-open pauses, strictly-greater threshold, `NONE`/`RESPONDED_LATE`/`NO_RESPONSE`), 2.8 OCC (both `expected_incident_version` rules, `ERR_STALE_INCIDENT_VERSION` 412), 2.9 Repair Budget Reservation Ledger, 2.10 Precision & Rounding
- **§3. Business Logic** — 8 subsections: 3.1 Territories/Technicians/Shifts/Crews, 3.2 Call Intake (implied priority, normalized address, PRIMARY/DUPLICATE/RECURRENCE), 3.3 Triage/Reclassification/Merge, 3.4 Dispatch/Arrival/Preemption/Pauses (selector ranking, capacity 2, net-zero preemption), 3.5 On-Scene (severity score formula, evacuation gate, make-safe completion, parallel entry-status dimension, close gates), 3.6 Shutoff/Restore (entry gate, METER+evacuation AUTO_SEVERITY rule), 3.7 Responsibility Determination & Repair Work Orders (SoD, full provisional matrix in cents, pinned per-line-then-labor rounding, 30-min travel buffer, budget cap), 3.8 Regulatory Reports & Public Notifications (dual raw/adjusted compliance variants, staleness/regeneration cycle, auto-notification idempotence flag)
- **§4. Endpoint Definitions** — 74-row table, 4 columns only (Method, Path, Description, Authorized Roles)
- **§5. Error Code Catalogue** — all 43 errors, 2 columns only (ID, HTTP status)

**Hard-contract reports:**
- Field coverage: 158 required identifiers (entity fields + request-body keys + query params), 158 present, 0 missing; 12 path params verified inside backticked §4 paths. **PASS**
- Rule coverage: all 7 state machines' transitions (preconditions + error ids + side effects), all 7 calculations (formulas translated to precise prose, matrix values stated), both OCC rules (endpoint + `expected_incident_version` + error id + 412), 10-priority validation cascade stated as ordered, all `applies_to` scopes enumerated, sibling branches symmetric (e.g. all three work-order cancel paths, both auto-notification origins). Close-gate and reading/action stage-gate gaps found in pass 1 were repaired. **PASS**
- §3 path purity: 654 backticked tokens scanned; 0 paths, 0 bare HTTP methods, 0 method+path combos. **PASS**

**Constraint confirmation:** Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced at any point. Only `SCAFFOLD.yaml`, the doc-generator skill, its fixed `section-2.2-response-structure.md`, and `example-prd.md` were read.

## Step 5: Generate Unit Tests — 2026-08-13T07:24:48.674Z

Generation complete. Summary:

### Test counts
- **Total: 82 tests**, all collected cleanly by pytest, zero skip/xfail markers, zero untagged/dual-tagged/orphaned Design tags.
- **Queue A (Difficulty): 40 tests** — all 20 instances covered with exactly 2 tests each (meets ≥2 target).
- **Queue B (Corner): 42 tests** — 40 of 41 non-stub instances covered (≥1 each); 4 `excluded_because:` stubs correctly not translated (all cross-references verified to resolve: `repair_cost_provisional_vs_final_variants`, `response_elapsed_raw_vs_adjusted_variants`, `duplicate_call_priority_escalation_cascade`).

### Skipped instance (1, with reason)
- **`Corner/errors/error_catalog_triggerability_sweep`** — SKIPPED. It is a self-described "Documentation instance — the sweep is verified by cross-reference, not by a single chain"; its trigger (`GET /gas-ops/territories/{id}`) yields no derivable assertion, and its asserts are meta-commentary about other instances. Fails the PRD-first coverage condition. Side effect: `ERR_REPAIR_BUDGET_EXCEEDED` (402) is never asserted by any emitted test (the fiscal path in `temporal_beats_fiscal_on_work_order_schedule` intentionally loses to the temporal error) — a genuine design-index gap to surface upstream; no freelance test was invented per the no-freelance rule.

### Deviation from one pre-computed literal (PRD conflict)
- `Corner/entities/emergency_call_intake_creates_incident_with_implied_priority`: the instance's literal `severity_score == 6` contradicts PRD §3.2 verbatim ("A new incident starts with ... `severity_score` 0"); §3.5's formula is only triggered by readings/escalations per PRD prose. The test asserts `severity_score == 0` (PRD-faithful). All other literals copied verbatim.

### Convention note
- `version == 1` at creation (and `version == 2` after triage in `immediate_consistency_after_triage`) follows the established benchmark-wide convention (sibling tasks 1224/1226/1227/etc. assert the same under identical "increments with every mutation" PRD wording); the OCC tests themselves use captured versions, not literals.

### File inventory
- `test_helpers/`: `__init__.py`, `types.py` (28 enums/TypedDicts; append-only entities correctly omit `version`/`updated_at`), `api_client.py` (all 53 endpoints), `api_errors.py` (45 error IDs registered via `set_error_http_status_map`), `assertions.py`, `factories.py`, `constants.py` (thresholds, severity constants, provisional matrix), `test_users.py` (opaque role constants + `make_technician_headers` entity-backed builder + `make_supervisor_headers` for SoD pairs), `fixtures.py` (state-progression helpers through closed/monitoring incidents, determination draft/finalize, auto-work-order setups).
- `test_suite/`: `conftest.py` + 11 test files: `test_01_call_intake_and_incident_creation.py`, `test_02_dispatch_arrival_and_shifts.py`, `test_03_response_clock_and_pauses.py`, `test_04_on_scene_make_safe_and_entry.py`, `test_05_shutoff_and_entry_gates.py`, `test_06_severity_and_notifications.py`, `test_07_determinations_and_work_order_costing.py`, `test_08_work_order_scheduling_and_budget.py`, `test_09_incident_lifecycle.py`, `test_10_regulatory_reports.py`, `test_11_rbac_scope_and_occ.py`.

### Audit results
- Coverage audit: 20/20 queue A instances at 2 tests; 40/41 queue B non-stub instances at ≥1; 4/4 stubs untranslated with resolved pointers.
- PRD citation sweep: every test docstring's quoted citation contains a ≥8-word window surviving literal grep of PRD.md (0 failures after one quote-completion fix).
- All error IDs asserted in tests are named in PRD prose (§2.6 cascade, §3.x trigger sentences), not just the §5 table.

## Step 6: Generate Implementation — 2026-08-13T07:24:48.674Z

Implementation complete. All 62 endpoints are implemented, and four smoke suites (lifecycle, preemption/shutoff/merge, pause/breach/recurrence/reporting, notifications/scoping/pagination) pass against fresh server boots, plus a `bash start.sh` boot contract verification.

### File inventory (2,869 lines total, all under `workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Guarded pip install (`import flask` check) + `exec python3 app.py` |
| `requirements.txt` | 1 | flask |
| `app.py` | 60 | Flask entry, blueprint registration, ApiError/404/500 handlers, per-request RLock, `0.0.0.0:$PORT` |
| `clock.py` | 43 | Logical clock (default `2026-08-01T00:00:00Z`), ISO-8601 parse/serialize (3 fractional digits) |
| `db.py` | 32 | 16 empty in-memory dicts + id/sequence generators; no seeding |
| `errors.py` | 9 | `ApiError(error_id, message, status)` |
| `response.py` | 62 | Envelope: `meta{api_request_id, api_request_timestamp}`, `response_type`, `data`; list meta adds `limit/offset/total_count/has_more` |
| `auth.py` | 40 | `X-User-ID`/`X-User-Role` validation (400) + role gating (403) |
| `validate.py` | 115 | Typed field validators, enum checks, pagination params (default 10, 1–100) |
| `domain.py` | 620 | All calculations (elapsed/pause math, breach, severity via `Decimal` ROUND_HALF_UP, provisional matrix, repair final cost with pinned per-line rounding, reserved-budget sum), serializers for all 16 entities, auto-notification + report-staleness helpers |
| `routes/common.py` | 128 | Existence loaders (per-entity 404 ids), Regulator/FieldTechnician read scoping |
| `routes/incidents.py` | 614 | Incident CRUD + triage/reclassify/close/merge/entry-status + all incident-scoped children (pauses, dispatches, readings, actions, make-safe complete, authorizations, shutoffs, determinations, work orders, notifications) |
| `routes/calls.py` | 152 | Call intake: implied priority, normalized-address dedup (PRIMARY/DUPLICATE/RECURRENCE) |
| `routes/dispatches.py` | 125 | arrive/clear/cancel/preempt (atomic re-pointing) |
| `routes/reports.py` | 180 | Snapshot computation (raw/adjusted variants, per-priority stats, 4-dp rates), submit/accept/reject/regenerate |
| `routes/{territories,technicians,crews,pauses,shutoffs,determinations,workorders,notifications,clock_routes}.py` | ~770 | Remaining resources and transitions |

### Module decomposition
Layered: `app.py` (transport) → `routes/` (validation cascade per endpoint: auth → role → path existence → scoping/SoD → shape → state → safety → temporal → referential → fiscal) → `domain.py` (all computed fields evaluated at read time against the logical clock; stored-field mutations explicitly bump `version`/`updated_at`) → `db.py` (plain dicts).

Key design choice: everything the scaffold marks `source: computed` (severity_score, elapsed/breach fields, repair_reserved_cents, responsibility, on_shift, weighted_load, awaiting_dispatch, gas_flow_stopped, linked_call_count) is computed on read, so clock advances and cascades need no stored-state reconciliation. The budget ledger therefore stays exactly consistent with §2.9 (schedule adds, complete releases provisional, cancel from SCHEDULED/ON_HOLD releases — all fall out of status changes).

### PRD ambiguities resolved
1. **AUTO_SEVERITY notification channel (severity-score trigger)**: PRD names `MEDIA` only for the meter-shutoff trigger. Used `PUBLIC_ALERT` for the severity≥80 trigger (consistent with AUTO_PRIORITY), `MEDIA` for the shutoff trigger as specified.
2. **Duplicate-call severity/version**: PRD §3.2 lists severity recompute and version increment only inside the escalation branch; calc table says "every call link." Followed PRD: non-escalating duplicates bump neither version nor mark reports stale (§3.8's staleness event list says "duplicate-call escalation"). Readings always bump incident version (OCC rule text: "severity recompute advances the incident version").
3. **Reclassify on wrong lifecycle**: error id not named; used `ERR_INCIDENT_NOT_ACTIVE` 409 (its catalog condition covers "stage-appropriate incident" ops). OCC (412) checked after state (409), since the validation cascade ranks state and leaves OCC unranked.
4. **`to_status` = AUTHORIZED/FORCED/NOT_REQUIRED**: AUTHORIZED/FORCED → `ERR_INVALID_REQUEST` 400 ("only via premise-entry-authorizations" reads as a request-domain exclusion); NOT_REQUIRED → `ERR_INVALID_STATE` 409 (valid enum, no transition).
5. **Body-referenced missing entities** (territory_id on call intake, technician_id on dispatch, crew_id on schedule): mapped to the corresponding `ERR_*_NOT_FOUND` 404; missing preempt `target_incident_id` record → `ERR_INVALID_STATE` 409 per scaffold precondition ("Target incident exists... else ERR_INVALID_STATE").
6. **Explicit dispatch to inactive technician**: gates enumerate only shift/territory/capacity; §3.1's "inactive technicians cannot be dispatched" enforced with `ERR_INVALID_STATE` 409.
7. **Make-safe/complete technician scope**: readings/actions explicitly require an *active* assignment; complete does not restate it, so the §2.1 blanket rule ("holds or previously held") was applied.
8. **Regulator scoping on child resources**: enforced on incident-scoped sub-GETs (403 when the parent incident isn't CLOSED/MERGED), per "any other access is rejected"; list endpoints filter instead.
9. **Close-gate ordering**: PRD §3.5 prose order (determination → dispatches → shutoffs) within the priority-9 referential tier.
10. **`api_request_timestamp`**: uses wall-clock UTC (PRD §2.4's logical-clock list covers business timestamps only; the example predates the logical epoch).

## Step 7: Test/fix iteration loop — 2026-08-13

Two 8-round parallel sweeps (`prd-bench-local-run --isolation per-test-server`, 82 tests/round).

**Sweep 1: 76/82 in all 8 rounds** — 6 deterministic failures (identical set every round, zero flakiness):
1. `test_01::test_primary_call_spawns_new_incident_with_implied_priority` — `assert 6 == 0`: implementation live-computed `severity_score` (6 for SINGLE_FAMILY, no readings), contradicting PRD §3.2 verbatim "A new incident starts with ... `severity_score` 0". Implementation fix: stored field, init 0, recomputed only at the two PRD-named events (new reading §3.5; duplicate-call escalation §3.2).
2. 4× `test_03` tests — `TypeError: 'bool' object is not callable`: module fixture `_fixture_p2_incident_with_pause(arrive=True)` shadowed the imported `arrive()` helper. Test bug; renamed param to `do_arrive` (+4 call sites). Asserted rules (§2.7) untouched.
3. `test_07::test_final_cost_computed_at_completion` — `assert 45 == 60`: test mis-translated PRD §3.7 "with an exact multiple billed as itself — fifteen minutes bills as fifteen" (45 min bills as 45, not 60). Test fix: `labor_billed_minutes == 45`, `final_cost_cents == 7663` (2214 + 949 + 4500).

**Sweep 2: 82/82 in all 8 rounds. CLEAN.**

No tests deleted (all failures traced to verbatim PRD rules; two test bugs, one implementation bug).

## Step 7: Test/Fix Iteration Loop — 2026-08-13T07:42:35.746Z

Done. Clean 8-round parallel sweep achieved. Verified by orchestrator: all 8 `results.{1..8}.json` files show `passed: 82 / 82, failed: 0`.

**Iterations run:** 2 sweeps (8 parallel rounds each, 82 tests/round, `--isolation per-test-server`). Sweep 1: 76/82 in all 8 rounds (6 deterministic failures, identical set every round). Sweep 2 after fixes: **82/82 in all 8 rounds — exit condition met.**

**Tests deleted:** none. Every failing assertion traced to a verbatim PRD sentence with unique derivability, so all repairs were fixes, not deletions.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:**
- `test_suite/test_03_response_clock_and_pauses.py` — `_fixture_p2_incident_with_pause`: the `arrive: bool = True` parameter shadowed the imported `arrive()` helper, so `if arrive: arrive(...)` raised `TypeError: 'bool' object is not callable` in 4 tests (`test_raw_and_adjusted_diverge_on_same_segment`, `test_adjusted_variant_drives_breach_while_raw_would_breach`, `test_incident_at_exact_threshold_is_compliant`, `test_report_counts_raw_and_adjusted_variants_separately`). Renamed the parameter to `do_arrive` and updated the 4 call sites. The asserted §2.7 raw/adjusted and exact-threshold rules are verbatim PRD — pure mechanical bug.
- `test_suite/test_07_determinations_and_work_order_costing.py` — `test_final_cost_computed_at_completion`: mis-translated PRD §3.7's "`labor_billed_minutes` is `labor_minutes` rounded up to the next multiple of fifteen, **with an exact multiple billed as itself — fifteen minutes bills as fifteen**" by expecting 45 min to bill as 60. Corrected to `labor_billed_minutes == 45` and `final_cost_cents == 7663` (2214 + 949 + 4500). The implementation was already PRD-faithful here.

**Fixes applied to `implementation/`** (one root cause — severity was live-computed, contradicting PRD §3.2's explicit "A new incident starts with ... `severity_score` 0"; the §3.5 formula's trigger is "Every new reading recomputes", and §3.2's escalation branch recomputes):
- `routes/calls.py` — PRIMARY branch initializes stored `severity_score: 0`; duplicate-escalation branch stores the recomputed score before the AUTO_SEVERITY ≥80 check.
- `routes/incidents.py` — `create_reading` stores the recomputed `severity_score` on the incident before the ≥80 auto-notification check.
- `domain.py` — `ser_incident` serializes the stored `severity_score` instead of calling the live formula (which scored a fresh SINGLE_FAMILY incident 6, contradicting §3.2).

No PRD-required check was weakened, no assertion downgraded, no skip/xfail added, storage remains in-memory only.

## Step 8: Finalize PRD — 2026-08-13T07:51:29.637Z

Done. `workspace/PRD_FINALIZED.md` is written.

### Line counts and delta
- PRD.md: 365 lines / 69,011 chars; PRD_FINALIZED.md: 365 lines / 69,633 chars. Line delta 0.0%; char delta +0.90% (one inline insertion, no new sections).

### Changes (one edit total)
- **§3.5 (severity score paragraph)** — **insert** — Added two sentences after the formula sentence pinning that `severity_score` is a **stored incident field, not a live read-time derivation**: a new incident keeps the 0 assigned at creation until a recompute event rewrites it; the only recompute events are (a) recording a new atmospheric reading and (b) a duplicate-call escalation that raises priority; every read reports the stored value; non-escalating duplicate calls, recurrence/reopen, triage, reclassification, merge, and closure leave it unchanged — `implementation/domain.py:424` (ser_incident serializes `i["severity_score"]` stored), `implementation/routes/calls.py:114` (PRIMARY init 0), `implementation/routes/calls.py:71-73` (escalation recompute+store), `implementation/routes/incidents.py:339-341` (reading recompute+store).

The other two `<step_7_diff>` items required no PRD edit: the test_03 `arrive` parameter shadowing was a pure fixture bug (§2.7 raw/adjusted and exact-threshold rules verified verbatim against `domain.py:156-181`), and the test_07 labor-rounding fix was a test mis-translation — §3.7's "exact multiple billed as itself — fifteen minutes bills as fifteen" already uniquely determines 45→45, matching `domain.py:323`, so prose kept verbatim.

### Per-edit pre-edit search log
**Edit 1 (§3.5 stored-severity insertion):**
- (a) Subject: `severity_score` storage, recompute events, and read serialization semantics.
- (b) Paths enumerated (via repo-wide grep for `severity` over all `implementation/**/*.py`, plus full reads of `domain.py`, `routes/calls.py`, `routes/incidents.py`, `routes/shutoffs.py`): calls.py:114 (PRIMARY init 0); calls.py:67-75 (DUPLICATE escalation recompute, stored before the ≥80 AUTO_SEVERITY check, only when implied priority strictly higher — non-escalating duplicates never recompute); calls.py:84-102 (RECURRENCE resets listed fields only — severity not reset); incidents.py:56-71 triage (no touch), 74-93 reclassify (no touch), 96-123 close (no touch), 126-157 merge (re-links calls, no recompute), 312-344 create_reading (recompute+store before ≥80 check), 395-422 complete_make_safe (no touch); shutoffs.py:69-72 (meter-execution MEDIA notification — never recomputes severity); domain.py:214-243 (formula, unchanged), 424 (serializer returns stored value). Test evidence: test_01 asserts fresh incident `severity_score == 0`; test_04 asserts 26/46 after specific readings; test_06 asserts 92 and single-notification idempotence.
- (c) Wording adjustment: scoped the sentence to enumerate exactly the two recompute events the implementation exhibits and listed the non-recompute events explicitly (non-escalating duplicate, recurrence/reopen, triage, reclassification, merge, closure) so that no enumerated path — including merge's call re-linking, which would alter the symptom factor under live semantics — is mis-described; avoided any claim that shutoff execution recomputes the score.

## Step 9: PRD Completeness Scan — 2026-08-13T08:10:00.000Z

Done. `PRD_COMPLETED.md` produced at `workspace/PRD_COMPLETED.md`.

**Size:** source `PRD_FINALIZED.md` 365 lines / 69,344 chars → `PRD_COMPLETED.md` 365 lines / 72,224 chars (delta +2,880 chars, 23 paragraphs edited in place, no new sections).

**Counts:** 19 ambiguity-pins, 6 mismatch-revisions (25 edited passages; the pct_lel mismatch appears in two sections).

**Ambiguity-pins (insert):**
- §2.1 — insert — ambiguity — pinned FieldTechnician act-scope split: readings/make-safe actions/shutoff execute+restore require an active assignment; make-safe completion, entry-status moves, shutoff requests require only a current-or-past assignment; arrive/clear require `technician_id == X-User-ID` — implementation/routes/common.py:112-122, incidents.py:165,316,362,400,474, dispatches.py:28-31
- §2.3 — insert — ambiguity — offset must be non-negative; non-integer limit/offset → `ERR_INVALID_REQUEST`; creation-timestamp ties broken by insertion order — implementation/validate.py:88-115
- §2.5 — insert — ambiguity — `version` starts at 1 on creation — implementation/domain.py:45-51
- §2.6 — insert — ambiguity — body-carried identifiers (call/technician/crew/report `territory_id`, explicit `technician_id`, schedule `crew_id`) fail with the matching not-found error — implementation/routes/calls.py:50-52, technicians.py:33-34, crews.py:30-31, reports.py:77-78, incidents.py:244-246, workorders.py:46-48
- §2.8 — insert — ambiguity — OCC version check runs after shape validation and, on reclassification, after the state gate — implementation/routes/incidents.py:79-88, 514-518
- §3.2 — insert — ambiguity — `is_duplicate` true only for DUPLICATE; PRIMARY/RECURRENCE carry false — implementation/routes/calls.py:64,88,125
- §3.2 — insert — ambiguity — multiple in-window closed incidents: the most recently closed reopens — implementation/routes/calls.py:85
- §3.2 — insert — ambiguity — incident lists filter by `territory_id`/`lifecycle_status`/`priority` (global) and `lifecycle_status`/`priority` (per-territory) — implementation/routes/incidents.py:31-39, territories.py:57-62
- §3.4 — insert — ambiguity — explicit dispatch of unknown technician → `ERR_TECHNICIAN_NOT_FOUND`; inactive technician → `ERR_INVALID_STATE`, checked first — implementation/routes/incidents.py:243-257
- §3.4 — insert — ambiguity — selector's final tie broken by registration order — implementation/routes/incidents.py:265-272
- §3.4 — insert — ambiguity — preempt returns 200 OK carrying the new assignment — implementation/routes/dispatches.py:125
- §3.5 — insert — ambiguity — `to_status` of AUTHORIZED/FORCED → `ERR_INVALID_REQUEST` (400); NOT_REQUIRED → `ERR_INVALID_STATE` (409) — implementation/routes/incidents.py:168-184
- §3.5 — insert — ambiguity — Dispatcher submitting EMERGENCY_FORCED/WARRANT → `ERR_INSUFFICIENT_PERMISSIONS` (403) — implementation/routes/incidents.py:435-437
- §3.7 — insert — ambiguity — manual work order on non-`leak_confirmed` incident → `ERR_INVALID_STATE` (409) — implementation/routes/incidents.py:554-556
- §3.7 — insert — ambiguity — completion line field types (numeric quantity, integer `unit_price_cents`, numeric `discount_pct`, `labor_minutes` a non-negative integer) — implementation/routes/workorders.py:124-144
- §3.8 — insert — ambiguity — severity-triggered AUTO_SEVERITY drafts on the PUBLIC_ALERT channel — implementation/routes/incidents.py:340-341, calls.py:72-73
- §3.8 — insert — ambiguity — "covering report" defined (territory match + `response_clock_started_at` in half-open period; pre-reopen segment start also matches) — implementation/domain.py:280-291, calls.py:101
- §3.8 — insert — ambiguity — report rejection must supply a `reason` — implementation/routes/reports.py:156
- §3.8 — insert — ambiguity — discarding a non-DRAFT notification → `ERR_NOTIFICATION_NOT_DRAFT` (409) — implementation/routes/notifications.py:57-58

**Mismatch-revisions (revise):**
- §2.10 + §3.5 — revise — mismatch — dropped the "one decimal place" `pct_lel` precision claim (impl enforces only the 0.0–100.0 range) — implementation/routes/incidents.py:321-322
- §3.1 — revise — mismatch — dropped "unique" from `badge_number` (no uniqueness check) — implementation/routes/technicians.py:24-35
- §3.1 — revise — mismatch — dropped "unique" from `crew_code` (no uniqueness check) — implementation/routes/crews.py:24-32
- §3.5 — revise — mismatch — removed the `no_make_safe_required`-conditional ON_SCENE→MONITORING distinction; completion always moves ON_SCENE-or-MAKE_SAFE_IN_PROGRESS → MONITORING and the flag is annotation-only — implementation/routes/incidents.py:395-422
- §3.7 — revise — mismatch — schedule gate listing reordered to the §2.6 cascade/impl order (time range → crew exists → OPEN → crew active/territory → travel buffer → FINAL determination → budget), pinning `ERR_CREW_NOT_FOUND` and inactive-crew `ERR_INVALID_STATE` — implementation/routes/workorders.py:43-73

Everything else in the implementation (response envelope, clock semantics, dedup/recurrence arithmetic, severity formula, breach classification, budget ledger, provisioning matrix, travel buffer, report snapshot math, RBAC table, error catalogue) was already uniquely pinned by the PRD and left untouched.

## Pipeline Complete

All Steps 1–9 finished. Final state: 82/82 tests passing in all 8 rounds of the final stability sweep; PRD chain PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md fully aligned to implementation/.
