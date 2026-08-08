# Worklog — task_0857_private_well_water_testing

## Step 1: Create task directory — 2026-07-27

Task directory `tasks/task_0857_private_well_water_testing/` pre-existed (created by orchestrator input); created `workspace/` subdir. Skipped next-index scan per instructions. Difficulty: Expert.

## Step 2: Generate Scaffold — 2026-07-27

All three scaffold artifacts are generated, parse cleanly (yaml.safe_load OK on all 3), and pass `scaffold_lint.py` with VERDICT: clean lint (392 §1.8+§1.9 calls conform to §1.5; all 15 FK reverse-reachability checks pass).

Task: Expert difficulty, Compliance/audit archetype blended with Temporal-windowing.

Scaffold surface: 12 entities · 54 endpoints · 32 error codes · 5 calculations · 21 validations · 7 state machines · 1 concurrency rule · 4 roles.

Entities: Applicant, Driller, Aquifer (config, common_fields:false), Well (central), ConstructionPermit, DrillerLog, WaterSample, SampleResult (common_fields:false), Advisory, ContaminationCase, AbandonmentPermit, RealEstateTestRequirement. Flat topology, FK-linked.

State machines: Well runs parallel dimensions (registry_status × potability_status independently); ContaminationCase is cyclic (RESOLVED→INVESTIGATING reopen); ConstructionPermit and AbandonmentPermit are branching (approve/deny forks); WaterSample lab pipeline; RealEstateTestRequirement.

Difficulty features (all 9 rules ≥2 instances): Dual-variant calcs (nitrate PROVISIONAL vs CONFIRMED; permit-fee ESTIMATE vs FINAL); combinatorial (permit-fee tiered composition; panel-fee round-per-analyte); depth-3 cascade (result→sample→case→well+advisory) and depth-2 (case-close→lift advisory→recompute potability); priority conflicts (state>referential; safety>fiscal); boundary precision (nitrate MCL 10.0 >=; real-estate 90-day inclusive); cross-entity deps; temporal overlaps (Driller half-open+buffer vs Advisory closed no-buffer); compensating invariants (money net_fees_paid; count active_advisory_count); OCC (expected_requirement_version supersede); SoD (case closer ≠ opener). Logical clock default 2026-05-01T00:00:00Z.

SCAFFOLD_DIFFICULTY_DESIGN.yaml: 9 rules × 2 = 18 instances. SCAFFOLD_CORNER_DESIGN.yaml: 43 instances (40 active + 3 excluded_because stubs).

## Step 3: Copy INSTRUCTION.md — 2026-07-27

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-07-27

Generated workspace/PRD.md. 5 top-level sections (§1 Intro; §2 Global Specs 10 subsections; §3 Business Logic 10 subsections; §4 endpoint table 54 endpoints; §5 error table 32 errors). All 3 doc-gen hard contracts PASS (field-name coverage, rule coverage, §3 path purity). Constants surfaced verbatim: NITRATE_MCL_MG_L=10.0, NITRATE_ADVISORY_MG_L=5.0, LEAD_ACTION_PPB=15.0; depth tiers 100/300ft→15000/25000/40000 cents; use mult DOMESTIC1.0/IRRIGATION1.2/LIVESTOCK1.5; aquifer surcharge HIGH10000/MOD5000/LOW0; EXPEDITE20000; analyte bases BACTERIA3000/NITRATE2500/LEAD4500 ×PANEL_REGION_FACTOR1.075; clock 2026-05-01T00:00:00Z; nitrate avg round 3-dec half-up.

### Constant-pinning patch (orchestrator, pre-Step-5/6)
doc-gen flagged 3 undeclared constants used by validations/side-effects but with no declared numeric value. Recovered values from design files (worked examples) and pinned in BOTH SCAFFOLD.yaml and PRD.md:
- PERMIT_VALIDITY_DAYS = 365 (corner expiry_sweep test: issued 2026-05-01 → expires 2027-05-01)
- DRILL_TRAVEL_BUFFER_HOURS = 4 (difficulty temporal-overlap instance)
- REAL_ESTATE_TEST_VALIDITY_DAYS = 90 (difficulty/corner boundary instances)
SCAFFOLD.yaml re-parses OK after edits.

## Step 5: Generate Unit Tests — 2026-07-27

76 tests collect, no skip/xfail, no scaffold refs, every docstring carries verbatim PRD citation + resolving Design tag.
test_helpers/ (9 files): types.py (12 entity TypedDicts, Aquifer+SampleResult omit updated_at/version), api_client.py, api_errors.py (32 errors+HTTP map), assertions.py, factories.py, constants.py, test_users.py (entity-backed builders + officer-id builder for SoD), fixtures.py (setup_active_well, setup_submitted_permit, sample-pipeline helpers, setup_well_with_cascade_case, setup_requirement_with_safe_sample), __init__.py.
test_suite/ (7 files): conftest.py + 6 domain files (test_01_registry_and_lookup … test_06_abandonment_realestate).
Counts: 76 total. Queue A (Difficulty) 36 = 18 instances × 2. Queue B (Corner) 40 = every non-stub instance once (7 entities, 4 state_machines, 11 validations, 2 endpoints, 11 errors, 2 rbac, 2 cross_cutting, 1 consistency).
Skipped: 3 stub instances (all excluded_because, no test_recipe): entities/panel_fee_computed_field, state_machines/unsafe_result_cascade_family, cross_cutting/link_sample_correct_version_succeeds. No instances failed PRD-first filter.

## Step 6: Generate Implementation — 2026-07-27

Complete Python+Flask API in workspace/implementation/. 7 files: start.sh (foreground, guarded pip, exec python3 app.py, 0.0.0.0:$PORT default 10000), requirements.txt (Flask 3.0.3), store.py (in-memory dicts, logical clock, seq counter, constants), helpers.py (error catalogue/ApiError, envelope, dt parse/render, auth, validators, pagination), models.py (id/timestamp mint, touch(), serialize()), calc.py (permit_fee, panel_fee, advisory grading, derived recomputes), app.py (54 @app.route / 57 endpoints, RBAC decorator, validation ordering, cascades).
Storage: in-memory dicts singleton; nothing seeded; fresh boot per restart. Logical clock default 2026-05-01T00:00:00Z, one render_dt() → 3 fractional digits + Z for ALL datetimes (input ...Z echoed as ...000Z). UUIDs str(uuid4()) dashed.
Judgment calls on PRD gaps: auto-case severity HIGH, opened_by_officer_id null; auto-advisory type DO_NOT_DRINK window [now, now+365d]; certify w/o linked sample → ERR_INVALID_STATE; abandonment complete by non-assigned driller → ERR_UNAUTHORIZED; potability on record-result direct-maps this result's confirmed grade, invalidate/close use latest-remaining-resulted recompute with open-case guard forcing UNSAFE.
Orchestrator boot smoke test: PASS (aquifer 201, dashed uuid, logical-clock ts, Aquifer omits updated_at/version). Route count 54 == scaffold endpoints (no partial-write gap).

NOTE: Steps 5 and 6 were launched sequentially (Step 5 then Step 6), not concurrently. Physical isolation preserved by giving Step-6 impl-gen an explicit hard constraint forbidding it from reading test_suite/ or test_helpers/.

## Step 7: Run Tests and Iterate — 2026-07-27

CLEAN FIRST-SWEEP PASS. Iterations run: 1 (single 8-round parallel sweep). Tests deleted: none. test_helpers/ fixes: none. implementation/ fixes: none. Final: 76/76 on all 8 rounds — every round passed=76 total=76 failed=0 errors=0. No flakiness, no diagnostic steps required. Only artifact created: workspace/sweep.sh. Orchestrator independently confirmed all 8 results.{1..8}.json show 76/76.

## Step 8: Finalize PRD — 2026-07-27

SKIPPED per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, 0 implementation/ fixes. PRD.md already determined every behavior the implementation exhibits at the Step-7-touched sites. No PRD_FINALIZED.md produced. Step 9 still runs (full impl scan).

## Step 9: Complete PRD — 2026-07-27

Produced workspace/PRD_COMPLETED.md from PRD.md (Step 8 skipped, no PRD_FINALIZED.md). 14 edits, all in-paragraph (line count unchanged 295→295, +4202 chars, 43545→47747). Counts: 12 ambiguity-pins, 2 mismatch-revisions.
2 genuine mismatches revised to impl: (a) §3.2 construction-permit submission has NO PROPOSED-well gate despite PRD "against a PROPOSED well" wording; (b) §3.3 driller-log guard order runs license-before-assigned (ERR_DRILLER_LICENSE_INVALID before ERR_DRILLER_NOT_ASSIGNED), opposite the PRD narrative.
Most consequential silence pinned: two-faced potability recompute — direct single-result assignment on record-result (already in PRD) vs reconciling variant on invalidate & case-close (any non-CLOSED case forces UNSAFE; no remaining resulted sample → UNKNOWN). Other pins: applicant read-ownership (ERR_UNAUTHORIZED) + other applicant endpoints not owner-gated; pagination limit/offset silent clamp + insertion-order tie-break; well deactivate/reactivate transitions; scheduled_end≤scheduled_start & effective_to≤effective_from → ERR_VALIDATION pre-existence; auto-case severity HIGH / opened_by_officer_id null; auto-advisory DO_NOT_DRINK window [now,now+365d]; abandonment complete by non-assigned driller → ERR_UNAUTHORIZED (after APPROVED, before license); certify state-before-candidate-presence; case transition to_status enum vs illegal error split. The 3 named constants (365/4/90) and both fee rounding orders were already uniquely pinned — no change.

## PIPELINE COMPLETE — 2026-07-27

task_0857_private_well_water_testing: Expert, CLEAN first-sweep pass 76/76 × 8 rounds, 0 fixes / 0 deletions. Step 8 skipped. Deliverables present: SCAFFOLD.yaml + 2 design files, PRD.md, PRD_COMPLETED.md, test_helpers/ (9), test_suite/ (7), implementation/ (7 + results.{1..8}.json), worklog.md.
