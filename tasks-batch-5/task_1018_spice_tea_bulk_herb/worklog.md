# Worklog — task_1018_spice_tea_bulk_herb

## Step 1: Create task directory — 2026-07-14T11:40:29.000Z

Created `tasks/task_1018_spice_tea_bulk_herb/` with `workspace/` subdir. Scenario: Spice, Tea & Bulk-Herb Shop (bulk SKU & tare/weight, blend/custom & batch, subscription & sampler, gift & tin, allergen/labeling, freshness/rotation, wholesale account, inventory). Difficulty=Expert (scaffold-gen param only).

## Step 2: Generate scaffold — 2026-07-14T12:05:00.000Z

prd-bench-scaffold-generator (Expert band). Generated SCAFFOLD.yaml (10 entities, 5 state machines, 9 calculations, 10 validations, 38 endpoints, 27 errors, 5 roles), SCAFFOLD_DIFFICULTY_DESIGN.yaml (18 depth instances), SCAFFOLD_CORNER_DESIGN.yaml (32 breadth instances).
Note: subagent timed out before writing the corner-design file; resumed via SendMessage to complete SCAFFOLD_CORNER_DESIGN.yaml (known "Step 2 scaffold timeout" pattern). Corner file had 23 `grounds:` flow-sequence lines with nested `errors[...]`/`state_machines...`/`concurrency_rules[...]` tokens that broke yaml.safe_load; quoted each element (known "Scaffold YAML lint fixes" pattern). All three files now safe_load cleanly.

## Step 3: Copy shared files — 2026-07-14T12:06:00.000Z

Copied INSTRUCTION.md into workspace/.

## Step 4: Generate PRD — 2026-07-14T12:09:00.000Z

prd-bench-doc-generator produced workspace/PRD.md (254 lines, ~34KB). Sections: §1 Intro, §2 Global Specs (RBAC, response envelope, pagination, versioning, nested retrieval/existence ordering, monetary rounding, logical clock + lot freshness, OCC on wholesale confirm, hierarchical stock-state cascades, validation ordering), §3 Business Logic (catalog/blends, inventory lots, batch production, gift-tin labeling+allergens, wholesale credit exposure, order lifecycle, packing+FEFO+final pricing, shipment/cancel/compensation), §4 Endpoint Definitions (all 11 resource groups), §5 Error Catalogue. Scaffold 38 endpoints all represented by resource group.

## Step 5: Generate unit tests — 2026-07-14T13:05:00.000Z

(RESUME run — prior Step 5/6 killed mid-flight; test_suite/, test_helpers/ regenerated fresh.)
prd-bench-unit-test-generator. All infrastructure and tests generated, compile cleanly, 59 tests collect with no scaffold leakage.
- test_helpers/: types.py (BlendComponent append-only: id+created_at only), api_client.py (39 endpoints incl /_clock/set_current_utc), api_errors.py (27-error catalog + HTTP-status map), assertions.py, factories.py, constants.py, test_users.py (Wholesaler make_wholesaler_headers for the one entity-backed role), fixtures.py (7 composite fixtures + low-level builders), __init__.py.
- test_suite/ (9 files, 59 tests): Queue A (Difficulty) 36 tests — all 18 instances (9 rules × 2), each with exactly 2 tests tagged Design: Difficulty/<rule_id>/<name>. Queue B (Corner) 23 tests — all 23 non-stub instances, 1 test each tagged Design: Corner/<section>/<name>.
- Skipped: none. All 18 difficulty + 23 non-stub corner instances passed the PRD-first two-condition filter. The 8 excluded_because corner stubs (7 errors, 1 consistency_model) correctly NOT translated (their difficulty_instance cross-refs own the assertion).
- Verification: every PRD citation grep-checked verbatim; every Design: tag maps to a real instance; two version-dependent assertions made robust (confirm-success asserts PRD-verbatim relative increment account["version"]+1; product-create dropped non-derivable version==1, still covers via status/stock_state). Setup uses PlatformAdmin (PRD hierarchical override); role-specific behavior driven explicitly in triggers.

## Step 6: Generate implementation — 2026-07-14T13:05:00.000Z

(RESUME run — workspace/implementation/ regenerated fresh.)
prd-bench-implementation-generator. Complete Python + Flask impl at workspace/implementation/. Boots cleanly, starts with empty store, serves envelope.
- Files: start.sh (set -euo pipefail, cd script dir, guarded pip install only if flask import fails, exec python3 app.py; reads $PORT default 10000, binds 0.0.0.0, foreground); requirements.txt (flask==3.0.3); store.py (in-memory dicts keyed by id, logical clock default 2026-07-01T00:00:00Z, UUID/seq/timestamp helpers, round_half_up via Decimal, empty on boot no seeding); envelope.py (meta/response_type/data success + error envelopes, pagination meta, ApiError); auth.py (X-User-ID/X-User-Role validation 401, RBAC with PlatformAdmin override 403, body validators, limit/offset pagination default 10 clamp 1–100); services.py (lot freshness, stock_state rollup + flip-detecting version cascade, recursive effective allergens, account exposure committed/projected/available, serializers); app.py (38 routes, existence lookups w/ dedicated 404 codes, business logic).
- Route count: 38 — exactly matches PRD/scaffold endpoint table. Verified via grep; all impl .py ast.parse clean; app.py OK.
- Key behaviors: full order lifecycle (draft→price→confirm→pack→ship / cancel+compensation); provisional vs final pricing (per-line round-half-up then sum, then tiered discount 0/5/12% at 500/2000g half-open); OCC expected_wholesale_account_version→412; credit gate→402; allergen gate→409; FEFO allocation (best_by, received_at, created_at/seq) atomic multi-line; pack error precedence (expired lot ERR_LOT_EXPIRED before ERR_INSUFFICIENT_STOCK); blend production (ceil component draws, FEFO across lots, depletion cascades, minted output lot best_by=clock+shelf_life_days); batch window overlap (half-open, abutment allowed) + tin-run 30-min cleaning buffer (exactly-30 allowed); stock_state cascades w/ product version bumps; clock-driven expiry; Wholesaler entity-backed ownership (403 on foreign).
- One inference (no test file at gen time): pack line_measurements accepted as array of {order_line_id|line_id|id, gross_grams, tare_grams}; net = gross - tare.

## Step 7: Run tests and iterate — 2026-07-14T13:20:00.000Z

All 8 rounds pass 59/59 (2 waves of 4, sweep run from sweep.sh to avoid pkill self-match / host self-saturation). Exit condition met.
- Iterations run: 2 (baseline sweep surfaced 1 failure; second sweep clean across all 8 parallel rounds).
- Tests deleted: None. No test failed the STEP 1 PRD-coverage / unique-derivability filter.
- Fixes applied to test_helpers/: None.
- Fixes applied to test_suite/: test_04_account_and_order_states.py, test_ship_draft_order_rejected_invalid_state — setup built its DRAFT order via validate_success(api.create_order(...)) whose framework default expected_status=200 conflicts with PRD §4 line 181 ("Operations that create a new resource return 201 Created"); server correctly returned 201 so the setup assertion tripped before the real ship→ERR_INVALID_STATE assertion. Fixed setup call to expect 201 (STEP 2 test-vs-PRD consistency: setup made more faithful to PRD; the ship assertion untouched and correct).
- Fixes applied to implementation/: None. Ship route (app.py:903) already correctly gated PACKED→SHIPPED and raised ERR_INVALID_STATE otherwise; failure was purely the test-setup status-code mismatch.
Final: 59/59 in all 8 parallel rounds (results.1.json … results.8.json all passed==total==59).

## Step 8: Finalize PRD — 2026-07-14T13:26:00.000Z

(Not skipped: Step 7 had 1 non-zero test_suite/ fix.) PRD finalizer ran. PRD.md vs PRD_FINALIZED.md: 254 vs 254 lines — 0% delta; PRD_FINALIZED.md is a verbatim copy of PRD.md.
- Changes: None warranted. The sole <step_7_diff> item was a pure test-fixture bug (setup expected_status default 200 vs correct 201 on POST /orders), not a PRD silence/mismatch. PRD §4 line 181 already uniquely determines it ("Operations that create a new resource return 201 Created; ... fetch, list, or drive a state transition ... return 200 OK"). Ship route (app.py:903) already correctly gated PACKED→SHIPPED with ERR_INVALID_STATE (PRD §3.8). No impl choice left open.
- Pre-edit search (201-on-create, evaluated not committed): grepped all `return ok(...,201)` create sites in app.py (create_product 153, create_blend_component 220, receive_lot 278, create_production_line 319, create_batch 373, create_labeling_station 488, create_tin_run 544, create_account 591, create_order 674, add_order_line 731) — all consistent with PRD §4 line 181; no edit needed.

## Step 9: Complete PRD — 2026-07-14T13:32:00.000Z

(Always runs.) Full PRD-vs-implementation completeness scan starting from PRD_FINALIZED.md → workspace/PRD_COMPLETED.md.
- Deltas: PRD_FINALIZED.md 254 lines/33974 chars → PRD_COMPLETED.md 254 lines/34988 chars (+1014 chars; no line-count change, all edits in-paragraph).
- Counts: 6 ambiguity-pins, 1 mismatch-revision.
- Changes:
  - §2.4 Common Resource Properties — revise — ambiguity — pinned version initial value = 1 (store.py:97).
  - §2.4 Common Resource Properties — revise — mismatch — account exposure fields (committed/projected/available) are derived-on-read, never stored; packing/cancelling a sibling order does NOT bump the account; account advances only on confirm/suspend/reinstate (services.py:63-74, app.py:824-900).
  - §3.1 Catalog — insert — ambiguity — blend allergen_tags persisted as empty array (app.py:139-140).
  - §3.1 Catalog — insert — ambiguity — weight_ratio_bps outside 1..10000 rejected with ERR_VALIDATION (app.py:210-211).
  - §3.3 Production — insert — ambiguity — minted blend output lot received_at = current clock, lot_code = literal BATCH-<batch id> (app.py:459-462).
  - §3.4 Tin-Run — insert — ambiguity — allergen_set returned as lexicographically sorted array of distinct strings (app.py:537).
  - §3.6 Order Lifecycle — insert — ambiguity — DRAFT order totals & new-line weight/pricing/allocation fields null until stamped (provisional at pricing, rest at packing) (app.py:663-672, 718-729).
- Left unchanged (already pinned): FEFO tie-break, round-half-up per-line-before-sum, discount boundaries 500/2000→0/5/12%, validation/error precedence §2.10, existence ordering §2.5, 30-min station buffer exclusive-at-boundary, available_credit uses committed exposure, confirm bumps account version by one, clock-set empty-data 200 (§2.2).

## Pipeline complete — 2026-07-14T13:32:00.000Z

RESUME run finished. Steps 5–9 regenerated fresh and passed: 59/59 tests across all 8 stability-sweep rounds; PRD_FINALIZED.md (verbatim copy) and PRD_COMPLETED.md produced. Task task_1018_spice_tea_bulk_herb is complete.
