# Worklog — task_0531_medical_examiner

## Step 1: Create task directory — 2026-07-01T00:00:00.000Z

Created `tasks/task_0531_medical_examiner/` (pre-allocated) with `workspace/` subfolder. Verified `INSTRUCTION.md` exists at project root.

## Step 2: Generate scaffold (Expert) — 2026-07-01T00:00:00.000Z

All 50 instance names unique. The scaffold is complete and passes all mechanical checks. Let me do a final verification that the `POST /cases` for Anonymous-role reads work and that the recipes never use undeclared roles — the lint already confirmed all §1.8/§1.9 calls conform (roles, payloads, captures, OCC).

The scaffold is complete.

## Summary

Generated a complete Expert-difficulty scaffold for **Coroner / Medical Examiner Case Management** at `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0531_medical_examiner/`. All three files pass `scaffold_lint.py` with **VERDICT: clean lint**.

**Complexity profile:** Compliance/audit (primary) + Workflow orchestration (secondary); segregation-of-duties role model; hybrid topology; branching state-machine shape; layers = optimistic concurrency, cascading side effects, dual-variant calculation, temporal windowing.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **13 entities**: Case, Investigator, Pathologist, CoolerUnit, Body, AutopsyExam, Specimen, ToxScreen, DeathCertificate, NextOfKin, PropertyItem, PropertyRelease, IndigentDisposition.
- **8 state machines**: Case (branching, REPORTED→ACCEPTED/DECLINED→INVESTIGATING→CERTIFIED→CLOSED), Body (INTAKE→STORED→RELEASED), AutopsyExam, Specimen, ToxScreen (cyclic amend loop), DeathCertificate (DRAFT→{SIGNED,VOID}, SIGNED→AMENDED loop), PropertyRelease, IndigentDisposition.
- **2 concurrency rules** (OCC, 412): `cert-sign-stale-case` (parent Case), `body-store-stale-cooler` (parent CoolerUnit).
- **4 calculations**: `autopsy_fee_estimate` (forward-looking) vs `autopsy_fee_final` (chronological, +specimen add-on, homicide ×1.5), `indigent_county_payable` (waterfall: estate offset then statutory cap), `cooler_occupancy_days` (aggregation, ceil per started day).
- **19 validations** (priority-ordered, auth→existence→state→business safety/referential/constraint/temporal/fiscal).
- **61 endpoints** (includes reverse-reachability GETs + `/_clock/set_current_utc` with default `2026-05-01T00:00:00Z`).
- **19 error codes**.
- **6 roles**: Admin, Investigator, Pathologist, MedicalExaminer, LabTech, Anonymous (segregation-of-duties on cert sign-off and property-release approval).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** all 9 Difficulty Rules, **2 instances each = 18 total**, with pre-computed literal asserts (e.g., estimate 230000 vs final 240000; homicide final 375000; indigent estate-offset 350000; pinned-order 0; occupancy 4 body-days). Differentiation clauses cross different entity domains / error-category pairs / interval semantics / conserved quantities as §0.5 requires.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **30 active instances + 2 `excluded_because` stubs** spanning entities, state_machines, calculations, validations, rbac, cross_cutting_complexity_layers (OCC), and consistency_model sections of the claim-extraction taxonomy.

**Note on one design decision:** `api_prefix` is set to `""` (empty/root) because this is a multi-collection flat/hybrid API where resources live at root paths (`/cases`, `/bodies`, `/pathologists`, etc.) rather than nested under a single prefix. Two root filtered-list endpoints (`GET /death-certificates`, `GET /property-releases`) were added to satisfy reverse-reachability for the computed audit FKs.

## Step 3: Copy INSTRUCTION.md — 2026-07-01T00:00:00.000Z

Copied `INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-01T00:00:00.000Z

The PRD has been generated at `workspace/PRD.md`. 293 lines.

**Structure:** §1 Introduction; §2 Global Specifications (12 subsections: RBAC, Response Structure, Pagination, Common Properties/Versioning, OCC, Nested Retrieval, Logical Clock, Jurisdiction/Lanes, Cooler Inventory, Fee Precision, Segregation of Duties, Validation Ordering); §3 Business Logic (8 lifecycle subsections); §4 Endpoint table (62 endpoints); §5 Error catalogue (18 error IDs).

**Coverage:** 13 entities, 8 state machines (23 transitions), 4 calculations (base 150,000; block 20,000; specimen 5,000; homicide ×1.5; ethanol ≥80; 86,400 s/day), both OCC rules (expected_case_version / expected_cooler_version), both segregation-of-duties rules, all cascade side effects.

**Hard Contract Reports:** Field coverage PASS (63/63 fields, 7/7 bodies, 9/9 query params); Rule coverage PASS (22/22 validations, 2/2 OCC, 23/23 transitions, 4/4 calculations, 18 error IDs); Path purity PASS (0 path tokens in §3). §2.2 byte-for-byte identical to canonical.

## Step 6: Generate implementation — 2026-07-01T00:00:00.000Z

Built complete Python + Flask implementation at `workspace/implementation/`. 20 files.

**Files:** `start.sh`, `requirements.txt` (flask 3.0.3), `app.py`, `db.py` (in-memory, fresh per boot, no seeding, served-counties `{"Kings"}`), `clock.py` (default 2026-05-01T00:00:00Z), `errors.py`, `response.py`, `records.py`, `middleware.py` (X-User-ID/X-User-Role auth, RBAC, pagination), `validate.py`, `lookup.py`, `calculations.py`, `services.py`, and 7 route modules.

**Endpoints:** all ~60 from PRD §4. All state machines, cascades (cert-sign → case CERTIFIED + clear release_blocked; indigent approve/bury), dual-variant autopsy fee, indigent waterfall, cooler occupancy, OCC on cert-sign/body-store, both segregation-of-duties gates, per PRD priority ordering.

**start.sh:** reads `$PORT` (default 10000), guards pip install behind `if ! python3 -c "import flask"`, then `exec python3 app.py`; `app.run(host="0.0.0.0", port=$PORT, threaded=True)` — foreground.

**Verification:** 45+ live behavioral checks passed (homicide final_fee 375000, indigent county_payable 0, OCC 412s, segregation 403s, manner-inconsistency 422, various 409s, tox cascade threshold 80, cooler occupancy ceil, pagination envelope, validation ordering 401→403→404). Fresh boot empty store confirmed.

## Step 5: Generate unit tests — 2026-07-01T00:00:00.000Z

**test_helpers/ (9 modules):** types.py (13 entity TypedDicts + enums), api_client.py, api_errors.py (ApiErrorId + HTTP map), assertions.py, factories.py, constants.py (fee constants, tox threshold 80, seconds/day, served/unserved counties), test_users.py (opaque-role headers + entity-backed role builders for identity threading), fixtures.py (lifecycle chains), __init__.py.

**test_suite/ (conftest + 8 test files, 64 test functions).**

**Coverage:** Difficulty queue A — all 16 instances translated, exactly 2 tests each (32 tests; companions in test_08_difficulty_companions.py). Corner queue B — all 30 non-stub instances translated (≥1 test each). The 2 excluded_because stubs correctly not translated (cross-ref a covered difficulty instance).

**Instances skipped:** 1 — `Difficulty/priority_pair_validation_conflict/property_release_kin_unverified_beats_fiscal_noop`. PRD §3.7 names no error_id for the case-status precondition and no precedence vs kin-unverified → fails unique-derivability (error-precedence silence). That rule left with 1 difficulty test; gap stays a gap.

**Integrity:** every docstring ends with exactly one verbatim `Design:` tag; no untagged/dual-tagged tests; all 64 citations survive ≥8-word verbatim PRD grep; all files byte-compile.

## Step 7: Test and iterate to green — 2026-07-01T00:00:00.000Z

**Iterations run:** 1 (the initial 8-round parallel stability sweep passed clean; no fix iterations were required).

**Sweep result:** All 8 concurrent rounds returned `passed == total == 64`, with `failed=0`, `errors=0`, `skipped=0`. No flakiness surfaced — the results were identical and green across every round. (Orchestrator independently verified: all 8 results.{1..8}.json show 64 `"status": "passed"`.)

**Tests deleted:** None. No PRD-silence or non-unique-derivability violations were triggered, because no test failed.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:** None. The implementation passed all 64 tests in all 8 rounds without modification.

## Step 8: Finalize PRD — SKIPPED — 2026-07-01T00:00:00.000Z

Skipped per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes. PRD.md already determined every behavior the implementation exhibits at the Step 7 sites. `PRD_FINALIZED.md` is therefore absent; Step 9 starts from `PRD.md`.
