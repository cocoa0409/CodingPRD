# Worklog — task_0060_dmv_vehicle_registration_title

## Step 1: Create task directory — 2026-05-31

Created `tasks/task_0060_dmv_vehicle_registration_title/` and `workspace/` subdirectory (fixed directory per orchestrator instruction; auto-index allocation skipped).

## Step 2: Generate scaffold — 2026-05-31

All three scaffold artifacts complete, parse cleanly, pass scaffold_lint.py. Expert difficulty. No sibling tasks inspected.

Complexity profile: Workflow-orchestration primary / compliance-audit secondary; flat entity topology; branching state-machine shape; peer-roles RBAC; layers = dual-variant calculation, cascading side effects, rate/threshold triggers, optimistic concurrency, derived-field reconciliation.

Counts:
- Entities: 11 — Owner, Vehicle, VinVerification, TitleApplication, SalvageInspection, Lien, EmissionsInspection, FeeAssessment, Registration, LicensePlate, RealIdApplication
- State machines: 6 — TitleApplication (branch fork/rejoin via SALVAGE_HOLD), Lien, Registration (suspend/reinstate/expire cascades), LicensePlate, RealIdApplication (review revert cycle), FeeAssessment
- Calculations: 6 — use_tax (dual-variant INITIAL vs capped TRANSFER), registration_fee (tiered depreciation, round-then-add), assessment_total, vehicle_active_lien_count, emissions_validity_window, registration_term_window
- Validations: 17 (priority-ordered, 8 categories)
- Endpoints: 51 (includes filtered-list GETs for FK reverse-reachability + one /_clock/set_current_utc test-driving endpoint)
- Errors: 20
- Roles: 4 — ClerkAgent (opaque), InspectionStation (opaque), Owner (entity_backed:Owner), DmvAdmin (opaque)
- Concurrency rules: 2 — plate-assign and reinstate stale-version OCC on Registration.version
- Design instances: §1.8 = 18 (9 rules × 2); §1.9 = 33 (31 active + 2 excluded_because stubs)

## Step 3: Copy INSTRUCTION.md — 2026-05-31

Copied `INSTRUCTION.md` into `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-31

PRD at workspace/PRD.md — 5 top-level sections, 253 lines. All three hard contracts PASS (field-name coverage 0 missing; rule coverage incl. both OCC rules, 4-hop cascade, round-then-add/round-then-cap formulas with constants; §3 path purity 0 leaks). SCAFFOLD_DIFFICULTY/CORNER not opened.

Scaffold ambiguities noted by doc-gen:
- ERR_VALIDATION (400) and ERR_REGISTRATION_NOT_ACTIVE (409) not error_id of any validations[] row; sited ERR_REGISTRATION_NOT_ACTIVE on plate activate/reactivate + fee void state preconditions, ERR_VALIDATION on malformed-body/missing-field in §2.8.
- Validation #14 ERR_INVALID_VIN (422) for VIN-length/uniqueness vs ERR_VALIDATION (400) for malformed bodies.
- _clock/set_current_utc test endpoint surfaced (input to_iso8601) in §3.8 + §4.

## Step 5: Generate unit tests — 2026-05-31

test_helpers/ (9 files) + test_suite/ (conftest + 7 domain files). 66 tests total, all collect cleanly.
- Queue A (Difficulty): 34 tests — 17 of 18 instances covered (≥2 each).
- Queue B (Corner): 32 tests — all 31 non-stub instances covered; both excluded_because stubs NOT translated.
Skipped (gap left as gap): Difficulty/priority_pair_validation_conflict/emissions_safety_beats_fees_fiscal — fails unique derivability (PRD §3.5 narrates activation gates fees→title→emissions, §2.9 binds precedence to §3 narrative order, so faithful reader returns ERR_FEES_UNPAID not ERR_EMISSIONS_REQUIRED). Documented inline in test_04.
Audits passed: every docstring ends with one verbatim Design: tag → real instance; PRD citations grep verbatim; no skip/xfail; no scaffold leakage.

## Step 6: Generate implementation — 2026-05-31

workspace/implementation/ — 6 files: start.sh (cd, pip install -q -r requirements.txt, exec python3 app.py; reads $PORT default 10000, binds 0.0.0.0, foreground threaded), requirements.txt (Flask 3.0.3), app.py (routes/logic/RBAC/errors), store.py (in-memory dicts, 11 collections, logical Clock w/ test override), envelope.py, errors.py (21-entry catalog).
51 endpoints across 11 resource groups + /_clock/set_current_utc. Decimal round-half-up money math, TRANSFER 150000-cent cap, salvage fork, 4-hop issuance cascade, activation gating in PRD order, OCC via expected_registration_version (412 ERR_STALE_VERSION). In-memory only, no seeding.

## Step 7: Run tests and iterate — 2026-05-31

Iterations run: 1 (single 8-round parallel sweep). Implementation passed on arrival.
- All 8 concurrent rounds: 66/66 passed, 0 failed, no cross-round flakiness under --isolation per-test-server.
- Tests deleted: None.
- Fixes applied to test_helpers/: None.
- Fixes applied to implementation/: None.

## Step 8: Finalize PRD — SKIPPED — 2026-05-31

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, 0 implementation/ fixes (zero iterations beyond baseline). PRD.md already determined every behavior the implementation exhibits. No PRD_FINALIZED.md produced.

## Step 9: Complete PRD — eliminate residual ambiguity/mismatch — 2026-05-31

PRD_COMPLETED.md produced (started from PRD.md; Step 8 skipped). PRD.md 253 lines/37315 chars → PRD_COMPLETED.md 253 lines/39408 chars (+2093 chars, no lines added — all in-paragraph).
Counts: 8 changes — 6 ambiguity-pins, 2 mismatch-revisions.
- §2.1 revise/mismatch — no owner-FK ownership checks; access decided solely by §4 role table, Owner may act on another owner's resources without ERR_FORBIDDEN (app.py:33-35,311-316).
- §2.3 insert/ambiguity — list tie-break: created_at asc, ties by id asc (app.py:121).
- §2.9 insert/ambiguity — ERR_VALIDATION (400) missing-field precedes existence 404; body-enum validation precedes existence on body-only-FK creates (app.py:294/327/442-446/394-397).
- §3.1 insert/ambiguity — ERR_INVALID_VIN (422) runs last (after owner 404 + field validation), length before uniqueness (app.py:329-344).
- §3.2 insert/ambiguity — TRANSFER issuance: Vehicle.version = 1+N, each released lien bumps own version (app.py:573-581).
- §3.5 use-tax revise/mismatch — county rate from registration's owner_id owner, not vehicle's current owner (app.py:953-954).
- §3.5 activation insert/ambiguity — FeeAssessment selection: latest by created_at (ties id), none → ERR_FEES_UNPAID (app.py:801-822).
- §3.7 insert/ambiguity — plate-assign gate order: ERR_PLATE_NUMBER_TAKEN → ERR_PLATE_ALREADY_ASSIGNED → ERR_STALE_VERSION (OCC last), after registration existence (app.py:1066-1091).
