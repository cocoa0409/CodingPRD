# Worklog — task_0232_school_bus_routing_ridership

## Step 1: Create Task Directory — 2026-06-07T00:00:00.000Z

Created `tasks/task_0232_school_bus_routing_ridership/` and `tasks/task_0232_school_bus_routing_ridership/workspace/` (index pre-assigned per orchestrator instruction; Step 1 scan skipped).

## Step 2: Generate Scaffold (Expert) — 2026-06-07T00:01:00.000Z

All three scaffold artifacts are generated, internally consistent, and pass `scaffold_lint.py` cleanly.

Generated the three scaffold artifacts for **task_0232 — School Bus Routing & Ridership (Expert)**:
- `SCAFFOLD.yaml` (§1.0–§1.7 + complexity_profile + concurrency_rules)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Complexity profile:** primary archetype *posture-driven gating* + secondary *quota/allocation*; layers OCC, cascading side-effects, dual-variant calculation, rate/threshold triggers. **Flat URL topology**, peer-role RBAC, immediate consistency.

**Scaffold contents:**
- **11 entities:** District, Route, Stop, Student, RidershipApplication, Driver, DriverAssignment, BusTrip, TapEvent (append-only), ParentNotification (append-only), MissedBusReport
- **4 state machines:** Route.posture (OPEN/RESTRICTED/SUSPENDED with cascade), RidershipApplication.status (cyclic revision loop UNDER_REVIEW↔CHANGES_REQUESTED + branching decision), BusTrip.status (branching with IN_TRANSIT self-loop + incident fork), MissedBusReport.status (linear protocol)
- **5 calculations:** haversine home distance, eligibility determination (distance/hazard threshold), ETA estimate (dual-variant gps vs stop-fallback), onboard-count projection, missed-bus window
- **21 validations** (priority-ordered), **49 endpoints** (incl. one `/_clock/set_current_utc` test-driver), **21 error codes**, **3 roles** (TransportAdmin opaque; Parent and Driver entity_backed)
- **2 concurrency rules** (OCC on Route.version: posture change, substitute supersede)

**§1.8:** 9 difficulty rules × 2 = **18 instances**. **§1.9:** **39 instances** (33 active + 6 `excluded_because` stubs).
**Verification:** all three files parse; `scaffold_lint.py` returns `VERDICT: clean lint` (393 calls scanned, 0 violations, all FKs reverse-reachable).

## Step 3: Copy Shared Files — 2026-06-07T00:02:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_0232_school_bus_routing_ridership/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-07T00:03:00.000Z

Generated `workspace/PRD.md` — **298 lines**. Sections: §1 Introduction; §2 Global Specifications (RBAC 3 roles, response envelope, pagination, common props + 2 append-only event types, cascades, computed counts/postures, nested ref validation, priority-ordered validation chain, precision 2dp/1dp round-half-up, OCC on both route write endpoints); §3 Business Logic (districts/routes/stops, distance/hazard eligibility with strict `>` boundary, application lifecycle + cyclic revision loop, capacity-gauntlet approval, drivers/substitute chain, bus-trip + ETA dual-variant + onboard projection, RFID taps + incident fork, posture master-gate, missed-bus protocol, parent notifications, service-day vs wall clock); §4 endpoint table (all 49); §5 error table (all 21).

Hard Contracts: Contract 1 (Field-Name Coverage) PASS (68/68 required fields, all path_params present); Contract 2 (Rule Coverage) PASS (all 21 error IDs, 36 state/enum values, 4 state machines, 2 concurrency rules, calc constants Earth radius 3958.7613 / avg speed 25.0 mph / walk threshold 1.5 / grace 10 min); Contract 3 (§3 Path Purity) PASS (0 path/method tokens in §3). Confirmed neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read.

## Step 5: Generate Unit Tests — 2026-06-07T00:04:00.000Z

Generated test infrastructure strictly from the two design indices.

**test_helpers/ (9 files):** types.py (role enum, 11 status enums, entity TypedDicts; append-only TapEvent/ParentNotification carry only id+created_at), api_client.py (one method per PRD endpoint, flat topology), api_errors.py (ApiErrorId enum + HTTP status map), assertions.py (per-entity assertions with append-only field guards), factories.py (input-only payload factories), constants.py (haversine/ETA literals 3.45/0.69/1.5/1.7/0.8), test_users.py (opaque admin + make_driver_headers/make_parent_headers ownership builders), fixtures.py (composite setup tiers), __init__.py.

**test_suite/ (conftest.py + 6 files, 69 test functions):** test_01 distance/eligibility (10), test_02 bus-trip lifecycle (8), test_03 application workflow (10), test_04 posture/cascades/OCC/assignments (16), test_05 taps/notifications/missed-bus (11), test_06 CRUD/states/RBAC (14).

**Coverage (design-index-only):** Queue A (Difficulty) all **18** instances translated, each ≥2 tests, 0 skipped. Queue B (Corner) all **33** non-stub instances translated, ≥1 test each, 0 skipped; 6 `excluded_because:` stubs correctly NOT translated. Every test single-tagged with a `Design:` line resolving to a real non-stub instance; 0 untagged/dual-tagged. All 98 PRD citation fragments confirmed verbatim-present. `pytest --collect-only` collects all 69 tests (validated against framework stub; host Python 3.9, runner installs real framework ≥3.10 at eval time).

Notable fidelity point: `start_boarding_on_suspended_route_returns_route_not_open` asserts **ERR_INVALID_STATE** (not ERR_ROUTE_NOT_OPEN) because PRD §3.8's SUSPEND cascade drives the SCHEDULED trip to CANCELLED before boarding is attempted.

## Step 6: Generate Implementation — 2026-06-07T00:05:00.000Z

Built complete **Python + Flask** REST API in `workspace/implementation/`.

**Stack:** Python 3 + Flask 3.0.3 (only dependency). In-memory storage only (`db.py` one dict per collection keyed by id, starts empty each boot). No seeding, no SQLite, no disk persistence.

**Files (27):** start.sh, requirements.txt, app.py (Flask factory, blueprint registration, error handlers, per-request global lock); Foundation: db.py, errors.py (21-error catalog), response.py (envelope), middleware.py (auth+RBAC); services/: calc.py (haversine, eligibility, ETA, clock), common.py, domain.py (computed counts, onboard projection, ETA derivation, serializers), validate.py, lookup.py, notify.py; routes/: 12 blueprint files.

**start.sh contract:** reads `$PORT` (default 10000), `app.run(host="0.0.0.0", port=..., threaded=True)`, foreground via `exec python3 app.py`, guards pip install on cheap `import flask` check. Boots and answers HTTP 201 within ~2s on 0.0.0.0.

**Endpoints: 49 of 49** (confirmed via Flask url_map, matches scaffold §1.5 incl. `/_clock/set_current_utc`).

Two explicit PRD interpretations made: (1) tap's `stop_sequence` must equal trip's `current_stop_sequence` (PRD states without dedicated code) → ERR_INVALID_STATE; (2) a Parent creating a student must set `parent_id == X-User-ID` → else ERR_FORBIDDEN. All test recipes create students as TransportAdmin so neither blocks a declared setup.

## Step 7: Run Tests and Iterate — 2026-06-07T13:45:50.000Z

All 8 parallel rounds are clean: 69 passed / 69 total, 0 failed, 0 errors, 0 skipped in every round. The task was already in a passing state, and the sweep confirmed there is no timing-sensitive flakiness across 8 concurrent rounds. No diagnostic action (no test deletions, no test_helpers fixes, no implementation fixes) was required.

Summary:
- Iterations run: 1 (single 8-round parallel sweep; all 8 rounds passed 69/69 on the first iteration, so no further iterations were needed).
- Tests deleted: None.
- Fixes applied to `test_helpers/`: None.
- Fixes applied to `implementation/`: None.

## Step 8: Finalize PRD — 2026-06-07T13:46:00.000Z

SKIPPED per skip condition. Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes (zero iterations beyond the baseline). `PRD.md` therefore already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` is produced. Step 9 will scan from `PRD.md`.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-07T13:56:00.000Z

Source: PRD.md (Step 8 skipped, no PRD_FINALIZED.md) vs PRD_COMPLETED.md
- Lines: 298 → 298 (no line count change; all edits are in-paragraph)
- Chars: 43,833 → 48,116 (char-delta +4,283)
- Ambiguity-pins: 10
- Mismatch-revisions: 3

Per-change bullets:

- §2.1 (User/RBAC, Driver) — insert — ambiguity — pinned that driver-ownership gates only a driver's write/transition operations on a specific bus trip (gps, start-boarding, depart-stop, raise-incident, complete, tap-recording) and that driver-authorized read endpoints are not ownership-scoped — routes/bus_trips.py:32-35 & taps.py:34, vs routes/drivers.py:43-68 / assignments.py:15-37 / bus_trips.py:71-93 / taps.py:93-115 (reads unscoped)
- §3.2 (Students) — insert — ambiguity — pinned that a Parent's student list is implicitly restricted to their own students regardless of supplied filters — routes/students.py:98-99
- §3.3 (Ridership Application, submit) — insert — ambiguity — pinned that all four body FKs resolve before the parent-ownership check, so ERR_INVALID_REFERENCE precedes ERR_FORBIDDEN when any reference fails to resolve — routes/applications.py:64-75
- §3.3 (Ridership Application, list) — insert — ambiguity — pinned that a Parent's application list is implicitly restricted to applications whose student they own regardless of filters — routes/applications.py:118-119
- §3.5 (Drivers) — revise — mismatch — corrected ON_DUTY lifecycle: status set only by start-boarding (→ON_DUTY) and complete/cancel/suspend (→AVAILABLE), and persists through depart loops and INCIDENT_HOLD/clear-incident (PRD previously implied ON_DUTY only "while BOARDING or IN_TRANSIT") — routes/bus_trips.py:147-153,268-277 & raise/clear-incident leaving driver untouched (186-229)
- §3.6 (BusTrip, schedule) — insert — ambiguity — pinned that at scheduling the assignment must resolve and belong to the route (else ERR_INVALID_REFERENCE) but its ACTIVE status is not checked until start-boarding — routes/bus_trips.py:47-52 vs start_boarding 130-132
- §3.6 (BusTrip, ETA) — revise — mismatch — pinned that eta_next_stop_minutes is null in any status other than BOARDING/IN_TRANSIT even when a GPS ping exists (PRD's GPS-origin clause was unqualified by status) — services/domain.py:111-112
- §3.6 (BusTrip, onboard replay) — revise — mismatch — pinned that the replay orders by a monotonic insertion sequence rising in lockstep with created_at (same-millisecond ties broken by recording order), then by stop_sequence (PRD said created_at then stop_sequence) — services/domain.py:20-31
- §3.7 (TapEvent) — insert — ambiguity — pinned tap error codes/scoping: stop_sequence≠current → ERR_INVALID_STATE; rfid resolved only among the trip's-route district's students, unresolvable → ERR_INVALID_REFERENCE; rfid resolution then stop_sequence checked before the two rider rules — routes/taps.py:42-55
- §3.7 (TapEvent, reads) — insert — ambiguity — pinned that tap-event reads are not ownership-scoped, so a Parent may fetch/list any tap event — routes/taps.py:93-115 (no parent filter)
- §3.9 (MissedBusReport, file) — insert — ambiguity — pinned district/student/trip FKs resolve before parent-ownership (ERR_INVALID_REFERENCE ahead of ERR_FORBIDDEN); no matching stop for reported_stop_sequence → ERR_INVALID_REFERENCE before the window test; created resolution field null until resolve — routes/missed_bus.py:36-48,60-67
- §3.9 (MissedBusReport, reads) — insert — ambiguity — pinned that a Parent fetching a report whose student they do not own → ERR_FORBIDDEN, and a Parent's list is implicitly restricted to their own students' reports — routes/missed_bus.py:82-85,101-103
- §3.10 (ParentNotification, reads) — insert — ambiguity — pinned that a Parent fetching a notification whose parent_id is not theirs → ERR_FORBIDDEN, and a Parent's list is implicitly restricted to their own notifications — routes/notifications.py:21-22,38-39
