# Worklog — task_0630_mobile_housecall_vet

Scenario: Mobile & House-Call Veterinary Service (The Vets/Bond Vet style): service area & appointment, in-home exam/vaccine/euthanasia, vet/tech route & rolling-clinic inventory, controlled-med (euthanasia) log & DEA, estimate & on-site payment, lab/specimen pickup, recurring wellness & reminder, hospital referral

Difficulty: Expert

## Step 1: Create task directory — 2026-06-22T17:29:26.000Z

Created `tasks/task_0630_mobile_housecall_vet/` with `workspace/` subdirectory (directory pre-allocated; no auto-numbering scan performed). Verified `INSTRUCTION.md` and all `prd-bench-*` skills present.

## Step 2: Generate Scaffold — 2026-06-22T17:47:00.000Z

Generated the three Expert-tier scaffold artifacts for **task_0630_mobile_housecall_vet** (Mobile & House-Call Veterinary Service). All files are at `tasks/task_0630_mobile_housecall_vet/`. `scaffold_lint.py` reports **VERDICT: clean lint** (all 6 checks pass: endpoint-declared, role-allowed, payload-shape, capture-resolution, OCC-dynamic, FK-reverse-reachability).

**Complexity profile:** primary archetype `compliance_audit` + secondary `temporal_windowing`; flat topology; branching state-machine shape; segregation-of-duties role model; layers = cascading side-effects, dual-variant calculation, optimistic concurrency, derived-field reconciliation, rate/threshold triggers.

**SCAFFOLD.yaml contents:**
- **13 entities:** ServiceArea, Clinician, RollingClinic, Patient, Appointment, RouteDay, RouteStop, Estimate, Payment, ControlledMedLog (append-only, common_fields:false), SpecimenPickup, WellnessPlan, Referral.
- **6 state machines:** Appointment (branching: REQUESTED→SCHEDULED→IN_VISIT→AWAITING_PAYMENT→COMPLETED, with REFERRED/CANCELLED forks), RouteDay (posture OPEN→LOCKED→RECONCILED), Estimate (DRAFT self-cycle + APPROVED→INVOICED/VOID), SpecimenPickup, WellnessPlan (ACTIVE↔PAUSED cycle), Referral.
- **1 concurrency rule:** OCC stale `expected_route_day_version` on stop creation (412).
- **8 calculations:** estimate_total (round-per-line-then-sum), invoice_total (dual variant w/ min-cap), euthanasia_dose (weight floor boundary), reconcile_controlled_balance (running-balance vs independent recount), route_stop_count, assign_stop_sequence, next_reminder (strict-future), stop_window_overlap (two interval semantics).
- **16 validations** (priority-ordered, 8 categories) and **26 errors**.
- **56 endpoints** (incl. reverse-reachability GETs and a `/_clock/set_current_utc` test endpoint with the mandatory 2026-01-01T00:00:00Z default).
- **3 roles:** Dispatcher (opaque), Clinician (entity_backed:Clinician), ComplianceOfficer (opaque).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml:** all 9 Difficulty Rules, exactly 2 instances each = **18 instances total**. All formula-derived assert literals computed in code and verified consistent.

**SCAFFOLD_CORNER_DESIGN.yaml:** **39 active instances + 3 excluded_because stubs** across all 9 taxonomy sections.

Files verified present: SCAFFOLD.yaml (1288 lines, no design keys), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1183 lines, single key `scaffold_difficulty_design`), SCAFFOLD_CORNER_DESIGN.yaml (1686 lines, single key `scaffold_corner_design`).

## Step 3: Copy INSTRUCTION.md — 2026-06-22T17:47:55.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0630_mobile_housecall_vet/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-22T17:52:56.000Z

Generated `workspace/PRD.md` (279 lines, 40206 bytes) from SCAFFOLD.yaml. Design files (DIFFICULTY/CORNER) withheld. All three hard contracts PASS: Field coverage (62/62 required fields present), Rule coverage (16 validations, 1 OCC + PATCH version guard, all 6 state machines, 8 calculations, 25 errors, side-effects all expressed), Path purity (§3 has 0 path tokens).

**Section structure:** §1 Introduction (2 paras); §2 (10 subsections: RBAC+identity, response envelope, pagination, common props + ControlledMedLog lean entity, nested retrieval, validation precedence, monetary precision, dosing/reconciliation precision, OCC dual version-guards, logical clock); §3 (9 lifecycle-grouped subsections); §4 endpoint table (57 endpoints incl `/_clock/set_current_utc`); §5 error table (25 errors).

**Coverage:** 13 entities, 6 state machines, 8 calculations, 16 validations, 1 OCC rule, 25 errors, 3 roles.

**Deliberate scattering:** OCC `expected_route_day_version` split across §2.9 + §3.3; `vaccine_doses` split across §3.2/§3.4/§3.5; dosing constants (0.2 mL/kg, 1.0 mL floor at 5.0 kg boundary, 30-min travel buffer) embedded in business prose; two overlap semantics rendered at equal density in §3.3.

## Step 5: Generate Unit Tests — 2026-06-22T18:19:00.000Z

Note: Steps 5 and 6 were run sequentially (not concurrently as the spec prefers); the impl-gen subagent in Step 6 was constrained to read only INSTRUCTION/SCAFFOLD/PRD, so the no-test-leakage contract was preserved.

Generated complete test infrastructure for **task_0630_mobile_housecall_vet** (Expert tier).

**test_helpers/ (9 modules):** types.py (14 enums + 13 entity TypedDicts; ControlledMedLog append-only — id+created_at only, no updated_at/version), api_client.py (~50 endpoint methods incl `_clock/set_current_utc`), api_errors.py (25-error enum + HTTP status map), assertions.py, factories.py, constants.py (dosing/buffer/clock), test_users.py (opaque Dispatcher/ComplianceOfficer + entity-backed `make_clinician_headers(clinician_id)`), fixtures.py (composite setups: booked→IN_VISIT→estimate, euthanasia DISPENSE/WASTE, completed/paid exam, full reconcile, clock control), __init__.py.

**test_suite/ (conftest + 6 files, 78 tests):**
- Queue A (Difficulty): all 18 instances, ≥2 tests each (21 distinct primary + 18 reinforcement).
- Queue B (Corner): all 39 non-stub instances, ≥1 test each.

**Skipped:** None among non-stub instances (PRD is rule-bearing). The 3 corner-design stubs (dispense_below_dose_floor, error_controlled_count_mismatch_stub, cascade_refer_voids_estimate_and_skips_stop) were correctly not translated; all 3 difficulty_instance cross-refs resolve to real Difficulty instances.

**Verification:** 78 tests collect cleanly; all modules byte-compile/import; every test has exactly one verbatim `Design:` tag → real instance; 108 PRD citations machine-checked verbatim/contiguous; no skip/skipif/xfail; no scaffold-section leakage.

## Step 6: Generate Implementation — 2026-06-22T18:19:40.000Z

Generated Python + Flask implementation in `workspace/implementation/` (13 files). Read only INSTRUCTION/SCAFFOLD/PRD; did not read tests.

**Files:** start.sh (reads $PORT default 10000, binds 0.0.0.0, foreground, guarded pip install, exec python3 app.py), app.py (56 routes + error handlers), clock.py (logical clock default 2026-01-01T00:00:00Z), realclock.py (response-meta only), db.py (in-memory 13 collections, starts empty, no seeding), errors.py (ApiError + 25-error→HTTP catalogue), response.py (envelopes, ISO 8601 UTC 3-digit), middleware.py (X-User-ID/Role auth + RBAC), util.py (body/field/enum/range validation, pagination), models.py (common-field stamping, touch(), public() strips _-prefixed internals), calculations.py (Decimal money/dose math), services.py (area resolution, stop counting/sequencing, reconciliation), requirements.txt (flask==3.0.3).

**Endpoints:** 56 (27 GET, 27 POST, 1 PUT, 1 PATCH).

**State machines (6):** Appointment (REQUESTED→SCHEDULED→IN_VISIT→AWAITING_PAYMENT→COMPLETED + REFERRED/CANCELLED forks w/ cascades), RouteDay (OPEN→LOCKED→RECONCILED), Estimate (DRAFT→APPROVED→INVOICED/VOID + DRAFT-revise self-loop), SpecimenPickup (COLLECTED→IN_TRANSIT→DELIVERED), WellnessPlan (ACTIVE↔PAUSED→ENDED), Referral (OPEN→ACKNOWLEDGED). Cascades bump each affected entity's own version/updated_at.

**Calculations:** estimate_total/invoice_total (round-half-up per-line-then-sum, Decimal; invoice caps VACCINE_DOSE lines at administered doses; 333×1.5 twice = 1000), euthanasia_dose (max(weight×0.2, 1.0) 1dp, boundary at 5.0kg), reconcile_controlled_balance (independent recount from lock-time snapshot, created_at ASC tie-broken by insertion seq, must equal running stock or ERR_CONTROLLED_COUNT_MISMATCH), stop_window_overlap (clinician 30-min buffer same RouteDay; vehicle zero-buffer across RouteDays sharing van+date), next_reminder (strict > clock stepping).

**Clock + OCC:** Clock starts 2026-01-01T00:00:00Z, mutated only via POST /_clock/set_current_utc; drives DEA-expiry + wellness reminders; created_at/updated_at use logical clock. OCC: POST /route-days/{id}/stops requires expected_route_day_version → mismatch ERR_STALE_ROUTE_DAY_VERSION (412); PATCH /rolling-clinics/{id} requires expected_rolling_clinic_version → same error/412. Validation precedence: auth(401)→forbidden(403)→not-found(404)→domain→body well-formedness(400).

## Step 7: Run Tests and Iterate — 2026-06-22T18:35:57.000Z

Clean exit — two consecutive 8-round parallel sweeps both pass 78/78 (all tests, all rounds).

**Iterations run:** 3 sweeps (1 baseline showing the failure, 1 after fixes, 1 confirmation). Total 24 parallel rounds.

**Tests deleted:** None. Every failing test passed STEP 1 (PRD coverage + unique-derivability) and STEP 2 (test-vs-PRD consistency); both failures traced to the implementation/infra, not to unfair tests.

**Fixes applied to test_helpers/:** None.

**Fixes applied to implementation/:**

1. `workspace/implementation/app.py`, `create_route_stop` — A successful stop booking was advancing the route day's `version` by **2** (once inside `services.recompute_stop_count` via its `models.touch`, plus a redundant explicit `models.touch(route_day)`), so two bookings produced version 5 instead of 3. Removed the redundant explicit `touch` so a booking nets exactly +1, matching PRD §3.3 verbatim: *"...recomputes the route day's `stop_count`, recomputes the `sequence` of every stop on the route, and increments the route day's `version` by 1."* This was the single hard-failing test (`test_correct_route_day_version_succeeds_and_bumps_version`, failing in all 8 baseline rounds).

2. `workspace/implementation/start.sh` — After the version fix, a different test (`test_cancel_cascade_skips_stop_and_drops_stop_count`) failed flakily in 2/8 rounds, but the failure detail was a server boot-restart timeout ("API server ... could not be restarted"), not a logic error — servers logged clean "Running on ..." with no traceback. This is the boot-contention flakiness the prompt warns about under 8x concurrent per-test reboots. Replaced the per-reboot `python3 -c "import flask"` interpreter-spawn probe with a one-time `/tmp` sentinel file, so the hundreds of per-test reboots skip the extra interpreter spawn and boot faster under peak load. Storage remains strictly in-memory; the sentinel only caches the dependency-check state and seeds no application data.

**Verification:** Two back-to-back full 8-round parallel sweeps both returned 78/78 on every round, confirming the version bug is fixed and the boot flakiness is resolved.

**Orchestrator confirmation sweep:** Re-ran one independent 8-round sweep (results.1–8.json regenerated, since the subagent's `rm -f` had cleared the prior artifacts); all 8 rounds returned passed=78 total=78 failed=0.

## Step 8: Finalize PRD — 2026-06-22T18:37:55.000Z

Produced `workspace/PRD_FINALIZED.md` (279 lines, byte-for-byte copy of PRD.md, **0% delta**). Step 8 was not skipped (Step 7 had 2 implementation fixes), but after inspecting both `<step_7_diff>` items against `implementation/`, neither revealed a PRD silence or PRD/impl mismatch requiring a pin:

- **Fix #1 (route-day version double-bump):** the fix aligned the implementation *to* PRD §3.3's already-verbatim wording ("...increments the route day's `version` by 1"). No PRD silence, no mismatch → no edit. Pre-edit enumeration confirmed the +1 semantics consistent across all route_day-touching paths (recompute_stop_count, complete_visit, refer, cancel cascades).
- **Fix #2 (start.sh boot probe):** pure launcher/infra change with zero API-behavioral surface → no edit.

## Step 9: Complete PRD — 2026-06-22T18:42:08.000Z

Produced `workspace/PRD_COMPLETED.md` from PRD_FINALIZED.md (279 lines, 40206→41137 chars, +931 chars; all edits in-paragraph, line count unchanged). Full PRD-vs-implementation/ scan walking all impl modules (app.py, services.py, calculations.py, models.py, response.py, middleware.py, util.py, db.py, clock.py, errors.py).

**Counts:** 4 ambiguity-pins, 2 mismatch-revisions.

**Per-change:**
- §3.1 (RollingClinic) — insert — ambiguity — `controlled_reconciled_ml` null on creation until reconciliation populates it — app.py:243
- §3.1 (RollingClinic) — insert — ambiguity — maintenance-toggle `status` must be exactly MAINTENANCE/IN_DEPOT; `expected_rolling_clinic_version` mismatch → ERR_STALE_ROUTE_DAY_VERSION + 412 — app.py:275-279
- §3.2 (Requesting a Visit) — insert — ambiguity — no ACTIVE area covering patient ZIP → appointment still created with `service_area_id` null (coverage enforced later) — app.py:354-359
- §3.3 (Building/Locking a Route) — revise — mismatch — locking non-OPEN route → ERR_ROUTE_NOT_OPEN (not §2.6-default ERR_INVALID_STATE) — app.py:851-852
- §3.4 (Pricing/Estimates) — insert — ambiguity — estimate creation re-resolves patient ZIP to ACTIVE area, refused ERR_AREA_NOT_COVERED if none — app.py:944-948
- §3.7 (Reconciliation) — revise — mismatch — reconciling non-LOCKED route day → ERR_ROUTE_NOT_OPEN, checked before ERR_STOPS_OPEN open-stops gate — app.py:880-886

**Left unchanged (already uniquely pinned):** euthanasia-log gate ordering (§2.6 safety→scheduling→stock); non-REQUESTED appointment book → ERR_INVALID_STATE (§2.6+§3.3); estimate-approve non-DRAFT → ERR_INVALID_STATE (§2.6 default). Clinician "OFF_DUTY" mention has no impl endpoint (unreachable) — no behavior invented.

---

## Pipeline Complete

All 9 steps executed. Final state: 78/78 tests pass across 8 independent stability rounds. Deliverables present: SCAFFOLD.yaml (+ DIFFICULTY/CORNER design indices), workspace/PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ (9 modules), test_suite/ (78 tests), workspace/implementation/ (13 files incl start.sh), results.1–8.json (all passing).
