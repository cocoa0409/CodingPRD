# Worklog — task_0326_flooring_sales_installation

Scenario: Flooring Sales & Installation: product catalog (hardwood/LVP/tile/carpet) & sq-ft, in-home measure, material + labor + underlayment estimate, special order & lead time, tear-out/haul-away, install scheduling & crew, waste/overage factor, warranty.

Scaffold difficulty: Expert (passed only to scaffold-generator).

## Step 1: Create task directory — 2026-06-13T00:00:00.000Z

Created `tasks/task_0326_flooring_sales_installation/` and `workspace/` (directory pre-assigned by orchestration; no ID scan performed).

## Step 2: Generate scaffold (Expert) — 2026-06-13T00:00:00.000Z

All three scaffold artifacts are generated, internally consistent, and pass `scaffold_lint.py` with a clean verdict.

Generated: task_0326_flooring_sales_installation (Expert difficulty). Three files written: SCAFFOLD.yaml (§1.0–§1.7), SCAFFOLD_DIFFICULTY_DESIGN.yaml (scaffold_difficulty_design only), SCAFFOLD_CORNER_DESIGN.yaml (scaffold_corner_design only).

Complexity profile: Pricing engine + Temporal windowing; flat topology; branching/cyclic state machines; peer_roles; immediate consistency. Layers: dual-variant calculation, optimistic concurrency, cascading side effects, rate/threshold triggers.

Scaffold contents:
- Entities (9): Product, Job, Estimate, MaterialOrder, InstallCrew, InstallSlot, WarrantyClaim, Customer, SalesRep
- State machines (7): Product (linear), Job (branching + cyclic remeasure loop + ESTIMATED self-loop + depth-3 cancel teardown), Estimate (branching), MaterialOrder (cyclic backorder/reorder), InstallCrew, InstallSlot, WarrantyClaim
- Concurrency (1): OCC on Job.version for estimate (re)issue/supersede (ERR_STALE_JOB_VERSION, 412)
- Calculations (5): waste_factor (threshold, category+seam-cap+big-area), estimate_total (dual-variant PROVISIONAL/MEASURED with pinned round-per-line-then-sum), ready_date, crew_day_load (aggregate capacity), warranty_risk (weighted scoring, clamped)
- Validations (23): priority-ordered auth → existence → state → business rules (install-slot geometry: job-accepted < skill < interval < job-single-occupancy < crew-buffer-overlap < crew-capacity)
- Endpoints (44): full CRUD + action endpoints + FK reverse-reachability GETs + 1 test-driving /_clock/set_current_utc
- Errors (23): all triggerable, all referenced
- Roles (6): Admin (opaque), SalesRep (entity_backed), Estimator (opaque), Scheduler (opaque), Customer (entity_backed), Anonymous

Difficulty design (§1.8): 18 instances = 2 per each of the 9 rules.
Corner design (§1.9): 47 instances across 9 sections (41 active + 6 excluded_because stubs deferring to §1.8).

Validation: All three files parse; scaffold_lint.py returns VERDICT: clean lint.

Notable corrections: (1) request-remeasure and estimate re-issue reachable from ESTIMATED; (2) Job single-occupancy overlap rule (ERR_JOB_SLOT_OVERLAP) added so Rule 8's two overlap instances sit on different resource entities.

## Step 3: Copy INSTRUCTION.md — 2026-06-13T00:00:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-13T00:00:00.000Z

PRD generated at workspace/PRD.md (257 lines).

Section list: §1 Introduction; §2 Global Specs (2.1 RBAC 5 roles + Anonymous; 2.2 API Response Structure verbatim; 2.3 Pagination; 2.4 Common Resource Properties; 2.5 Cascades/Hierarchical Consistency/Left-to-Right Path Validation; 2.6 Money/Sq-Ft/Rounding; 2.7 OCC on Estimate Issuance; 2.8 Lazy Clock & Time-Gated Operations); §3 Business Logic (12 subsections: Catalog, Job/Provisional quote, Measure & waste factor, Re-measure, Measured estimate/issuance/OCC, Acceptance & material order, Special orders, Crews/slots/capacity, Installation & completion, Cancellation cascade, Warranty window & adjudication, Validation ordering); §4 Endpoints (44, incl. /_clock/set_current_utc); §5 Error Catalogue (23 errors).

Hard Contract reports: Contract 1 Field-Name Coverage 49/49 PASS; Contract 2 Rule Coverage PASS (validations, OCC, all state machines, all 5 calculations, all 23 error IDs, cascades); Contract 3 §3 Path Purity PASS (0 path tokens in §3). All 28 state/enum values appear verbatim; §2.2 byte-for-byte.

Confirmation: neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read.

## Step 5: Generate unit tests — 2026-06-13T00:00:00.000Z

NOTE: First Step 5 attempt crashed mid-run on a transient socket error (subagent died after 18 tool uses), leaving partial test_helpers/ (missing __init__.py and fixtures.py) and empty test_suite/. SendMessage resume is unavailable in this harness, so Step 5 was re-spawned fresh and regenerated the complete deliverable from scratch.

Regenerated the full test deliverable fresh; everything internally consistent and compiles.

test_helpers/ — 9 files: __init__.py (was missing), fixtures.py (was missing — composite setup across 5 tiers; identity threading via make_sales_rep_headers/make_customer_headers), types.py (added expected_job_version to Estimate TypedDict), api_client.py, api_errors.py, assertions.py, constants.py, factories.py, test_users.py.

test_suite/ — 7 files (conftest + 6 test files), 77 test functions: test_01_catalog_and_crud.py (12), test_02_estimates_and_pricing.py (11), test_03_job_and_estimate_workflows.py (17), test_04_scheduling_and_capacity.py (16), test_05_material_and_warranty.py (13), test_06_validations_and_security.py (11).

Instances translated vs skipped:
- Queue A (Difficulty): all 18 instances across 9 rules translated, 2 tests each (36 tagged tests). 0 skipped.
- Queue B (Corner): all 41 non-stub instances translated, 1 test each (41 tagged tests). 0 skipped. 6 excluded_because stubs not translated; all 6 stub difficulty_instance cross-refs verified to resolve.
- Total skipped: 0. Every design instance passed the PRD-first two-condition filter.

Audits passed: every test carries exactly one Design: tag; both coverage diffs empty; all 18 difficulty instances have ≥2 tests; no skip/skipif/xfail; 18 spot-checked citations survive literal grep of PRD.md; all test_suite imports resolve against test_helpers exports; all 16 files compile.

Data-consistency note (not an error): difficulty instance warranty_risk_score_on_job_domain_distinct_from_cost has a distinguishing_aspect mentioning TILE-65.0 but its actual setup/assert is CARPET-10.0; translated the asserted CARPET 10.0 outcome per PRD §3.9.

## Step 6: Generate implementation — 2026-06-13T00:00:00.000Z

Built a complete Python + Flask in-memory implementation in workspace/implementation/.

Source files: start.sh (foreground launcher; guards pip install on cheap import flask check, then exec python3 app.py), app.py (binds 0.0.0.0:$PORT, default 10000), requirements.txt (Flask 3.0.3), db.py (in-memory Store, Python dicts, starts empty no seeding), clock.py (server-controlled lazy clock, ISO-8601 UTC 3 fractional digits), errors.py (ApiError + 23-entry catalogue), response.py (meta/response_type/data envelope, req_-prefixed ids, pagination in meta), middleware.py (X-User-ID/X-User-Role auth, RBAC), services/calc.py (waste factor, provisional/measured totals with Decimal ROUND_HALF_UP pinned per-line rounding, ready date, warranty risk), services/helpers.py (body parsing, validators, pagination limit 1–100 default 10 offset default 0, created_at-ascending sort), services/serialize.py (PRD-faithful views; Customer/SalesRep light: id+created_at only), routes/ (actors, products, jobs, estimates, material_orders, crews, install_slots, warranty_claims, clock_admin).

Endpoints: all 44 routes from PRD §4 implemented.

start.sh confirmation: reads $PORT (via os.environ.get("PORT","10000")), binds 0.0.0.0, foreground via exec python3 app.py. Fresh boot confirmed empty store, no disk persistence, no seeded entities.

## Step 7: Run tests and iterate — 2026-06-13T00:00:00.000Z

Iterations run: 1 (single 8-round parallel sweep).

Result: All 8 concurrent rounds passed cleanly — passed == total == 77, 0 failed, 0 errors, 0 skipped in every round. Test count identical (77) across all rounds, so no collection errors masking failures and no flakiness surfaced. Verified independently by orchestrator: results.1.json..results.8.json all passed=77 total=77 failed=0 errors=0.

Tests deleted: None — no failing tests across any of the 8 rounds.
Fixes applied to test_helpers/: None required.
Fixes applied to implementation/: None required.

Note on a false alarm during diagnosis: subagent's first summary script keyed on a nonexistent `outcome` field (real field is `status`), printing spurious FAIL lines; caught by inspecting JSON directly (top-level passed=77/total=77/failed=0/errors=0, per-test status="passed" on all 77). Corrected summary confirmed empty failure union.

## Step 8: Finalize PRD — SKIPPED — 2026-06-13T00:00:00.000Z

Skipped per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes (zero iterations beyond baseline). PRD.md already determined every behavior the implementation exhibits at Step 7's measured sites. PRD_FINALIZED.md is intentionally not produced; Step 9 starts from PRD.md.

## Step 9: Complete PRD — eliminate residual ambiguity/mismatch — 2026-06-13T00:00:00.000Z

Produced workspace/PRD_COMPLETED.md (started from PRD.md since Step 8 was skipped).

Line counts: PRD.md 257 → PRD_COMPLETED.md 257 (unchanged). Char delta: 39562 → 40416 (+854).
Counts: ambiguity-pins: 5, mismatch-revisions: 1.

Per-change list:
- §2.3 Pagination — insert — ambiguity — out-of-range limit / negative offset / non-integer pagination params rejected with ERR_INVALID_REQUEST (422) — services/helpers.py:43-56.
- §3.1 Catalog — insert — ambiguity — invalid category list-filter value rejected with ERR_INVALID_REQUEST; status filter matched as-is (unknown value matches nothing) — routes/products.py:110-117.
- §3.5 Measured Estimate/Issuance — insert — ambiguity — every estimate response carries expected_job_version, null on freshly created DRAFT estimate, set to submitted value on issuance — services/serialize.py:61, routes/estimates.py:73,143.
- §3.9 Installation — insert — ambiguity — slot start operation returns the install-slot resource (own fields unchanged), not the transitioned job — routes/install_slots.py:150-152.
- §3.11 Warranty filing — revise — mismatch — ownership check scoped to Customer filer and exempts Admin (per §2.1 Customer-scoped ownership); resolution_note response field null until adjudication — routes/warranty_claims.py:40,54.
- §3.11 Warranty approval — insert — ambiguity — warranty-window boundary strict: filed_at at or after window-end (completion + warranty_years) rejected with ERR_WARRANTY_EXPIRED — routes/warranty_claims.py:90.

Tests used only as auxiliary cross-reference; implementation was the sole alignment authority.

## Pipeline complete — 2026-06-13T00:00:00.000Z

All steps finished. Final state: 77/77 tests pass across 8 parallel per-test-server rounds (0 deletions, 0 fixes). Deliverables present: SCAFFOLD.yaml + 2 design indices, test_helpers/ (9 files), test_suite/ (conftest + 6 test files, 77 functions), workspace/implementation/ (Flask, in-memory), workspace/PRD.md, workspace/PRD_COMPLETED.md (PRD_FINALIZED.md absent — Step 8 skipped).
