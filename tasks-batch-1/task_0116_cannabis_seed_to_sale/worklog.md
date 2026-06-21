# Worklog — task_0116_cannabis_seed_to_sale

Scenario: Cannabis Seed-to-Sale (METRC): plant tag/lot tracking, cultivation→harvest→package transitions, lab test (potency/pesticide) hold, transfer manifest, per-customer purchase limit, inventory reconciliation, waste destruction, state license compliance

Difficulty: Expert (10–15 entities, 20–32 endpoints, 18–30 error codes, 3+ calculation variants, 4+ state machines)

## Step 1: Create task directory — 2026-06-03T02:31:37.000Z

Created `tasks/task_0116_cannabis_seed_to_sale/` and `tasks/task_0116_cannabis_seed_to_sale/workspace/` (pre-assigned directory; auto-increment scan skipped per directive). Verified `./INSTRUCTION.md` exists at project root.

## Step 2: Generate scaffold — 2026-06-03T03:01:27.000Z

All three scaffold artifacts written: SCAFFOLD.yaml (1782 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1298 lines), SCAFFOLD_CORNER_DESIGN.yaml (1489 lines). Built fresh from scenario + spec only; no sibling tasks read.

Counts (Expert difficulty per §0.4):
- Entities: 12 — License, PlantBatch, Harvest, Package, LabResult, Manifest, ManifestLine, Customer, Sale, SaleLine, ReconciliationCount, WasteEvent (target 10–15 ✓)
- Endpoints: 52 — above the 20–32 band; documented FK-reverse-reachability overage (12 entities each needing CRUD + reverse-reachability GETs). Lint-clean, accepted per established guidance. 1 test-driving endpoint (/_clock/set_current_utc).
- Error codes: 20 (target 18–30 ✓); every error tied to a §1.4 validation or §1.2.1 concurrency row.
- Calculations: 4 with 7 variants (target 3+ ✓) — flower-equivalent (round-per-line-then-sum), customer daily limit (adult vs medical 3×), reconciliation variance (tolerance threshold), harvest yield reconciliation.
- State machines: 6 (target 4+ ✓) — License, PlantBatch, Harvest, Package, Manifest, Sale; includes Manifest cyclic DRAFT↔IN_TRANSIT recall loop, Package branching TESTING→{PASSED,FAILED}, auto/bubble-up transitions.

Design coverage: §1.8 has 18 difficulty instances (2 per rule × 9 §0.5 rules); §1.9 has 37 corner instances (35 active + 2 excluded_because stubs). 55 unique instance names.

Validation: scaffold_lint.py returns "clean lint" (510 calls scanned, all conform to §1.5, all FKs reverse-reachable). Self-audits confirmed: grounds refs resolve, excluded_because refs valid, enum closure, no forbidden concurrency vocabulary, formula literals computed in code. One internal bug caught+fixed (harvest-yield double-subtracted package waste → corrected to remaining = dry_weight − Σ(package quantities)).

## Step 3: Copy shared files — 2026-06-03T03:01:47.000Z

Copied ./INSTRUCTION.md → tasks/task_0116_cannabis_seed_to_sale/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-06-03T03:08:17.000Z

Generated workspace/PRD.md (294 lines) from SCAFFOLD.yaml. Neither design YAML read; no sibling task consulted.

Major sections:
- §1 Introduction — METRC-style track-and-trace compliance framing.
- §2 Global Specifications (11 subsections): RBAC 7 roles + opaque-identity translation; verbatim §2.2 response envelope; pagination; common resource props/versioning (5 append-only records carry only id+created_at); hierarchical consistency & cascades; segregation of duties; license-type gating & status; nested-resource existence ordering; precision/rounding (2dp round-half-up); OCC (expected_manifest_version + expected_sale_version → ERR_STALE_VERSION 412); validation-priority ordering.
- §3 Business Logic (8 subsections): licensing+clock, cultivation/destruction, harvest/cure, packaging+yield reconciliation, lab testing+release, transfer manifests, retail sales+flower-equivalent math+daily limits, reconciliation/waste. Includes round-per-line-then-sum, 1.0/5.0/0.1 flower-equivalent factors, 3× medical multiplier, ">limit rejects / ==limit passes" boundary, 0.5g inclusive recon tolerance, depth-3 failed-test destroy cascade, harvest auto-finish bubble-up.
- §4 Endpoint table (4 cols); §5 Error catalogue (2 cols, all 20 error IDs).

Hard Contract reports: Contract 1 (Field-Name Coverage) 66/66 PASS; Contract 2 (Rule Coverage) PASS, 20/20 error IDs; Contract 3 (§3 Path Purity) 344 tokens, 0 violations PASS.

Fidelity correction: scaffold references POTENCY_CEILING_PCT but never assigns a numeric value; removed a fabricated "30 percent" and rendered as "at or below the regulatory potency ceiling" to avoid inventing a constant the scaffold does not define.

## Step 5: Generate unit tests — 2026-06-03T03:23:18.000Z

Stage 1 — test_helpers/ (9 files): types.py (entity TypedDicts + status/role enums, append-only records carry only id/created_at), api_client.py (56 endpoint methods subclassing GenericApiClient), api_errors.py (20 error IDs + HTTP-status map), assertions.py, factories.py (input-fields-only), constants.py, test_users.py (all 7 roles opaque; make_headers builder pins acting X-User-ID for SoD tests), fixtures.py (tiered composite chains: license→batch→advance×2→harvest→cure→package→lab→release, plus active/failed-package, retail-scenario, departed-manifest, reconciliation helpers), __init__.py barrel.

Stage 2 — test_suite/ (conftest + 9 test files, 71 tests):
- test_01_cultivation_lifecycle: 10
- test_02_lab_testing_and_release: 3
- test_03_sales_flower_equivalent: 15
- test_04_cascades: 4
- test_05_manifests_transfers: 10
- test_06_reconciliation_and_invariants: 7
- test_07_validation_priority: 7
- test_08_validations_and_errors: 6
- test_09_crud_and_listing: 9

Queue split: 36 Queue A (Difficulty), 35 Queue B (Corner). All 18 difficulty instances have ≥2 tagged tests; all 35 non-stub corner instances ≥1 tagged test. 0 instances skipped. 2 excluded_because stubs correctly not translated.

Verification: every file byte-compiles; test_helpers imports cleanly; all 71 tests collect with zero errors; every docstring carries exactly one Design: tag + verbatim PRD citation (≥8-word substring survives literal grep of PRD.md); no skip/skipif/xfail; no scaffold/table refs leaked.

PRD gap noted (not blocking): PRD names a "regulatory potency ceiling" for lab PASS but never gives its numeric value. No test asserts that boundary — every PASS/FAIL outcome is driven by pesticide_pass with thc_pct values clear of any plausible ceiling, so all assertions remain uniquely PRD-derivable.

## Step 6: Generate implementation — 2026-06-03T03:23:18.000Z

Built complete Python + Flask implementation at workspace/implementation/.

Files: start.sh (foreground launcher, guarded pip install), requirements.txt, app.py (entry + error handlers), db.py (in-memory store), errors.py, response.py, middleware.py, helpers.py, serializers.py, services.py, constants.py, clock.py; routes/: licenses.py (+ test clock), plant_batches.py, harvests.py, packages.py, lab_results.py, manifests.py, customers.py, sales.py, reconciliation_counts.py, waste_events.py.

Endpoints: 54 — full §4 catalogue: license CRUD + lifecycle (suspend/reinstate/revoke), test clock, plant-batch CRUD + advance, harvests (create/cure/finish), packages (create/release/clear-hold) + 6 reverse-reachability sub-collection reads, lab-results, manifests (lines/depart/recall/receive/void), customers, sales (lines/finalize/void), reconciliation-counts, waste-events.

State/storage: in-memory only — one dict per entity in db.py, keyed by UUID. No SQLite/disk/tmp/seeding (verified by source audit + two-boot test: boot 2 on same port started total_count=0). Fresh process wipes all state.

start.sh: reads $PORT (default 10000), binds 0.0.0.0, foreground via exec python3 app.py, guards dep install (if ! python3 -c "import flask") so per-test reboots don't re-run pip.

Verified behaviors (two e2e smoke suites green): response envelope (meta/response_type/data, req_ request id, ISO-8601 3-digit ts), pagination meta, full provenance chain, depth-3 FAILED_TEST destroy cascade + harvest auto-finish bubble-up, manifest depart/recall/receive-accept with package re-homing + ERR_MANIFEST_OVERLAP, OCC ERR_STALE_VERSION on depart+finalize, flower-equivalent factors (1.0/5.0/0.1, round-per-line-then-sum), 3× medical daily limit, age verification before fiscal check, SoD on release + clear-hold, reconciliation MATCH/DISCREPANCY → ON_HOLD, partial vs full plant destruction, discriminator mismatch, license-type/active gating, auth 401/403 ordering.

Under-specified points resolved conservatively: (1) POTENCY_CEILING_PCT never given a value, thc_pct ∈ [0,100], so ceiling pinned at 100 → PASS/FAIL reduces to pesticide_pass (consistent with §3.5). (2) Hold-clearing SoD compares against counted_by_user_id from recon record (per §2.1); release SoD compares against recorded acting X-User-ID of the PASS lab result.

## Step 7: Run tests and iterate — 2026-06-03T03:28:00.000Z

All 8 parallel rounds green (71/71 each). Verified results.{1..8}.json persisted from final sweep.

Iterations run: 2 (initial sweep surfaced 10 deterministic failures; one fix; second sweep all green).

Root cause: All 10 failures in test_05_manifests_transfers.py shared one setup error — HTTP 403: ERR_LICENSE_TYPE_MISMATCH "Plant batches require a CULTIVATION license" (matched triage hint ≥5 tests same setup error → test layer first suspect). Tests built their shipped package via create_active_package(dist["id"], lab["id"], ...) passing a DISTRIBUTION license as the first arg, which is the license used to create the underlying plant batch/harvest — per PRD §2.7/§3.2 must be a CULTIVATION license. The DISTRIBUTION license tripped the implementation's correct ERR_LICENSE_TYPE_MISMATCH check during setup before the manifest behavior under test was reached. STEP 2 test-precondition violation, not an implementation bug.

Implementation verified faithful — routes/manifests.py correctly does NOT require the package's custody license to equal the manifest origin (PRD §3.6 states no such requirement); depart precondition only requires origin license ACTIVE. No implementation change.

Fixes applied to test_suite/ (test_05_manifests_transfers.py):
- Changed all 10 occurrences of dist = create_distribution_license() to dist = create_cultivation_license() so the package can legitimately originate and be custodied on the origin license (PRD §3.4: a package's license_id is initially the harvest's cultivation license). Preserves every assertion — test_recall_conserves_origin_license_custody (license_id == dist["id"]) and test_receive_accept_rehomes_package_to_destination (re-home to dest) — because none assert anything about the origin's license TYPE; they assert custody by license_id. Manifest still created by a DistributionAgent actor (dist_h() headers), enforced regardless of origin license type.
- Removed the now-unused create_distribution_license import.

Tests deleted: none — every failing test verbatim-covers a PRD §3.6/§2.10 rule and is uniquely derivable; failures were fixture precondition bugs, not PRD-silence.

Fixes applied to test_helpers/: none.
Fixes applied to implementation/: none.

Final state: 71/71 passing across all 8 concurrent rounds, no flakiness.

## Step 8: Finalize PRD — 2026-06-03T03:31:42.000Z

PRD_FINALIZED.md produced as a verbatim copy of PRD.md (zero edits). Confirmed byte-identical via diff.

Line counts: PRD.md = 294, PRD_FINALIZED.md = 294. Delta 0 (0.0%).

Rationale: The single Step 7 fix was a pure test-fixture-precondition bug — test passed a DISTRIBUTION license where a CULTIVATION license is required, tripping the implementation's correct ERR_LICENSE_TYPE_MISMATCH at plant-batch creation during fixture setup, before the manifest behavior under test was reached. 0 implementation changes, 0 deletions. Every behavioral subject the diff touches is already uniquely determined by PRD.md and the impl matches it. No PRD-silence or PRD/impl mismatch to pin.

Pre-edit enumeration (no edits committed, but mandatory search performed for each diff subject):
1. License-type gating on plant-batch creation: PRD §2.7/§3.2 vs impl routes/plant_batches.py:46-48 — PRD already determines exactly. No change.
2. Package initial custody license = harvest's license: PRD §3.4 vs impl routes/packages.py:80 + re-home routes/manifests.py:256 — PRD already determines. No change.
3. Manifest depart/receive does NOT require package custody license == origin license: PRD §3.6 depart-precondition list vs impl routes/manifests.py (add_manifest_line 90-132, depart 161-210, receive 247-264, recall 220-227) — PRD's silence is the intended "no such constraint"; impl exhibits exactly that absence; they agree. Adding text would invent/redundantly assert. No change.

All three subjects PRD-determined and impl-faithful; correct Step 8 output is a verbatim copy.

## Step 9: Complete PRD — 2026-06-03T03:36:10.000Z

PRD_COMPLETED.md produced from PRD_FINALIZED.md via full impl scan. 4 paragraphs revised in place; no new lines/sections. Confirmed implementation/ and tests untouched since Step 7 green sweep — 71/71 × 8 rounds remains valid.

File metrics: PRD_FINALIZED.md 294 lines / 44,351 chars; PRD_COMPLETED.md 294 lines / 45,425 chars. Char delta +1,074.

Change counts: 4 ambiguity-pins, 0 mismatch-revisions.

Per-change log:
- §3.1 Licensing — insert — ambiguity — Pinned reinstate requires expires_on strictly in the future; stale/expired reinstate (and any suspend/reinstate/revoke from wrong originating status) rejected with ERR_INVALID_STATE (PRD left error unnamed). — routes/licenses.py:130-134
- §3.5 Lab Testing — insert — ambiguity — Pinned "regulatory potency ceiling" to concrete value 100 (= upper bound of valid thc_pct), so PASS/FAIL reduces to pesticide_pass; pinned recording license == package's custodying license_id rejected with ERR_LICENSE_TYPE_MISMATCH (PRD named no error). — constants.py:16-19, routes/lab_results.py:65-70
- §3.5 Failed-test destruction — insert — ambiguity — Pinned ERR_PARTIAL_DESTROY_NOT_TERMINAL full-consumption rule fires only for FAILED-package + FAILED_TEST-reason combo; other package-side waste events decrement remaining_grams partially without terminalizing. — routes/waste_events.py:98-124
- §3.6 Transfer Manifests (receive) — insert — ambiguity — Pinned decision field exact literals "accept"/"reject"; any other value → ERR_INVALID_REQUEST. — routes/manifests.py:236-239

Verified-already-pinned (no change): validation-priority ordering (§2.11), reconciliation tolerance + ON_HOLD cascade (§3.8), flower-equivalent round-then-sum + daily-limit projection (§3.7), SoD (§2.6), harvest auto-finish bubble-up incl. DEPLETED-via-sale (§3.3/§3.5/§3.7), release/clear-hold not requiring active license, resource field shapes/version semantics (§2.4 vs serializers.py + types.py).

=== PIPELINE COMPLETE === All 9 steps done. Final state: 71/71 tests passing across 8 concurrent rounds. Artifacts: SCAFFOLD.yaml (+2 design YAMLs), workspace/PRD.md, PRD_FINALIZED.md (verbatim copy), PRD_COMPLETED.md (4 ambiguity-pins), workspace/implementation/ (54 endpoints), test_helpers/ + test_suite/ (71 tests), results.{1..8}.json all green.
