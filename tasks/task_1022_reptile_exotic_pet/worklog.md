# Worklog — task_1022_reptile_exotic_pet

## Step 1: Create task directory — 2026-07-14T18:00:00.000Z

Created ./tasks/task_1022_reptile_exotic_pet/ with workspace/ subdirectory (folder pre-assigned; no ID scan). Difficulty: Expert.

## Step 2: Generate scaffold — 2026-07-14T18:50:00.000Z

All three scaffold artifacts generated, valid YAML, pass scaffold_lint.py clean. Expert difficulty. 14 entities (Species, Animal, QuarantineRecord, Customer, Permit, Sale, WarrantyClaim, FeederBatch, FeederSubscription, Shipment, HabitatBuild, Expo, ExpoAssignment, Recall). 11 state machines (2 non-linear: WarrantyClaim branching fork-join REFUND/CREDIT/REPLACEMENT; HabitatBuild cyclic IN_PROGRESS↔CHANGE_REQUESTED). 1 concurrency rule (OCC create-with-supersede on HabitatBuild change-orders, expected_habitat_build_version → ERR_STALE_VERSION 412). 5 calculations (dual-variant sale_price, dual-variant warranty_refund DOA/EARLY_DEATH, shipment_cost waterfall+round-per-line, quarantine_required_until inclusive date, habitat_final_invoice). 19 validation rules (priority-ordered; logical-clock endpoint default 2026-07-01T00:00:00Z). 70 endpoints, 33 errors, 4 roles (StoreManager/VetTech/SalesAssociate opaque; Customer entity_backed). §1.8: 9 rules × 2 = 18 instances. §1.9: 25 instances (23 active + 2 excluded stubs). safe_load verified clean on all 3 files.

## Step 3: Copy shared files — 2026-07-14T18:50:30.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-07-14T18:57:00.000Z

Generated workspace/PRD.md (291 lines) from SCAFFOLD.yaml only (both design files withheld). 5 top-level sections; §2 has 10 subsections (roles/identity, response envelope, pagination, common props, logical clock, monetary precision, cascades, nested-retrieval ordering, four-eyes SoD, OCC); §3 has 9 domain-lifecycle subsections. All 70 endpoints in §4 table; all 33 errors in §5 table. Notable: two-variant sale_price (provisional omits loyalty), warranty_refund DOA-full/EARLY_DEATH-prorated, shipment_cost waterfall+round-per-line, quarantine clearance gate, habitat deposit/final-invoice, permit-revoke/warranty-resolve/recall cascades, validation priority orderings, OCC on habitat change-orders (expected_habitat_build_version → ERR_STALE_VERSION 412). Field coverage 95/95, rule coverage PASS, path-purity PASS.

## Step 5: Generate unit tests — 2026-07-14T19:15:00.000Z

Stage 1 test_helpers/ (9 files): types.py (14 entity TypedDicts + 16 enums), api_client.py (one method per endpoint), api_errors.py (35-code catalogue + HTTP-status map), assertions.py, factories.py, constants.py, test_users.py (opaque StoreManager/VetTech/SalesAssociate + entity-backed Customer builders), fixtures.py, __init__.py. Stage 2 test_suite/ (conftest + 9 files, 59 tests). Queue A (Difficulty): 18/18 instances × 2 tests = 36. Queue B (Corner): 23/23 non-stub × 1 = 23; both excluded_because stubs left untranslated. Skips: none. Nuance: corner OCC instance change_order_stale_version_returns_412 uses validate_error_is_one_of([ERR_STALE_VERSION, ERR_INVALID_STATE]) per error-precedence silence. All 59 tests carry exactly one Design: tag, 0 scaffold refs, 0 skip/xfail, all PRD citations verbatim. pytest --collect-only = 59 tests.

## Step 6: Generate implementation — 2026-07-14T19:15:30.000Z

workspace/implementation/: app.py (single-file, 70 routes, in-memory dicts, no seeding), requirements.txt (flask==3.0.3), start.sh (foreground, reads $PORT default 10000, binds 0.0.0.0, exec python3 app.py). ast.parse OK; route count 70 == scaffold endpoint count (no partial-write gap). Exact envelope, logical clock default 2026-07-01T00:00:00Z, Decimal/ROUND_HALF_UP money, validation ordering per §2.8, cascades (permit revoke/recall/expo/warranty), OCC on change-orders, four-eyes SoD, install buffer ≥60, half-open expo overlap, customer ownership. Subagent smoke-tested 5 boots clean. pytest collects 59 tests from task root.

## Step 7: Test & iterate — 2026-07-14T19:25:00.000Z

All 8 rounds green at 59/59. Iterations run: 2 (baseline + 1 fix round).
Tests deleted: None. The failing assertion was PRD-covered and uniquely derivable.
Fixes applied to test_helpers/: None.
Fixes applied to implementation/:
- workspace/implementation/app.py, create_shipment() — The feeder-shipment refusal logic decided ERR_FEEDER_RECALLED vs ERR_INSUFFICIENT_FEEDER_STOCK solely on total_available <= 0, so a batch drained to 0 (status DEPLETED, but neither recalled nor expired) wrongly returned ERR_FEEDER_RECALLED. PRD §3.6 states the recalled branch applies only when "every candidate batch is recalled or expired so that no eligible stock exists at all." Fixed by computing an eligible set (matching batches not RECALLED and not expired) — empty eligible set → ERR_FEEDER_RECALLED; otherwise available AVAILABLE-stock quantity < quantity_per_shipment → ERR_INSUFFICIENT_FEEDER_STOCK. DEPLETED batch now treated as eligible-but-empty (insufficient), matching the failing boundary test while leaving recalled-batch precedence tests passing.
Final result: 59/59 passed across all 8 parallel rounds. Verified all 8 results.*.json = 59/59.

## Step 8: Finalize PRD — 2026-07-14T19:32:00.000Z

Produced workspace/PRD_FINALIZED.md (291 lines, 0 line-count delta; one §3.6 paragraph reworded in place). Single change:
- §3.6 Feeder Shipments — revise — Pinned "eligible stock" definition for the ERR_FEEDER_RECALLED vs ERR_INSUFFICIENT_FEEDER_STOCK decision: a matching batch is eligible when neither RECALLED nor expired regardless of quantity, so a DEPLETED (drained-to-zero, non-recalled, non-expired) batch counts as eligible → ERR_INSUFFICIENT_FEEDER_STOCK, not ERR_FEEDER_RECALLED. Also clarified insufficient-stock total sums only candidate batches (matching, AVAILABLE, unexpired, positive quantity). Traces to app.py:1129-1141 (Step 7 fix). NO-NEW-MISMATCH search cross-checked recall cascade (app.py:1561), manual reversal (app.py:1210), depletion flip (app.py:1157-1158) — all consistent. No other step_7_diff items → no other edits.

## Step 9: Complete PRD — 2026-07-14T19:40:00.000Z

Produced workspace/PRD_COMPLETED.md (291 → 291 lines, +1506 chars). Full impl scan: 6 ambiguity-pins, 3 mismatch-revisions.
- §2.1 RBAC Customer — insert — failed ownership → ERR_UNAUTHORIZED; Customer list auto-scoped for sales/warranty/subscriptions/builds but not species/animals/expos/assignments (app.py:213,768,883,1069,1263).
- §2.8 validation ordering — revise — nested-list endpoints resolve parent path resource + Customer ownership before pagination (app.py:663,1181).
- §3.2 health checks — insert — health check appended regardless of record status (app.py:569).
- §3.2 quarantine-record read — revise — GET /animals/{id}/quarantine-record returns paginated array (0-or-1); GET /quarantine-records/{id} returns object (app.py:553,563).
- §3.3 customer registration — insert — duplicate email → ERR_VALIDATION (app.py:618).
- §3.5 warranty REPLACEMENT — revise — replacement animal AVAILABLE→SOLD single mutation; added missing/not-found/not-available error codes (app.py:951).
- §3.6 shipments — insert — subscription status not a precondition for running a shipment (app.py:1116).
- §3.7 recalls — insert — batches → RECALLED regardless of prior status; wallet compensation per reversed shipment regardless of sub status; only ACTIVE subs → HELD (app.py:1560).
- §3.9 expo assignments — insert — assignment does not require expo in any particular status (app.py:1470).

## Pipeline complete — 2026-07-14T19:40:30.000Z

All 9 steps done. 59/59 tests pass across 8 parallel rounds. Artifacts: SCAFFOLD.yaml + 2 design files, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, test_helpers/, test_suite/ (59 tests), implementation/ (70 routes, in-memory Flask). Difficulty: Expert.






