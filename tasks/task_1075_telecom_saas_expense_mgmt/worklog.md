# Worklog — task_1075_telecom_saas_expense_mgmt

## Step 1: Create task directory — 2026-07-21T17:49:00.000Z

Created tasks/task_1075_telecom_saas_expense_mgmt/ and workspace/ (pre-assigned folder, auto-numbering scan skipped per orchestrator directive). INSTRUCTION.md confirmed present at project root.

## Step 2: Generate scaffold (Expert) — 2026-07-21T18:20:00.000Z

All three scaffold artifacts complete, parse cleanly (yaml.safe_load OK ×3), pass scaffold_lint.py clean.

Expert-difficulty TEM scaffold. Archetype: Ledger reconciliation + Compliance/audit; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation. Role model = segregation_of_duties.
- 10 entities: Vendor, Contract, Service, Invoice, InvoiceLineItem, Dispute, Credit (append-only), CostCenter, Allocation, Recommendation.
- 42 endpoints (incl. /_clock/set_current_utc, default 2026-05-01T00:00:00Z).
- 9 state machines: Dispute (cyclic negotiation VENDOR_RESPONDED↔RESUBMITTED), Invoice (branching + revert UNDER_REVIEW↔DISPUTED→APPROVED), Recommendation (branching), plus Vendor/Contract/Service/InvoiceLineItem/CostCenter/Allocation.
- 6 calculations, incl. 2 dual-variant (invoice provisional-vs-final expected; recommendation projected-vs-realized savings) and 2 combinatorial modes (tier×proration×fee mode-a; chargeback round-per-share + remainder-to-top-weight mode-b).
- 32 error codes, 1 OCC rule (recommendation-create supersede on Service.version), 6 roles (2 entity_backed: CostCenter, Vendor).
- SCAFFOLD_DIFFICULTY_DESIGN: 9 rules × 2 = 18 instances. SCAFFOLD_CORNER_DESIGN: 25 active + 4 excluded_because stubs across 9 sections.
- Author fixes: removed unreachable ERR_OPEN_DISPUTES_EXIST; pinned MAX_DISPUTE_ROUNDS=2. All formula asserts pre-computed literals.

## Step 3: Copy INSTRUCTION.md — 2026-07-21T18:21:00.000Z

cp ./INSTRUCTION.md → workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-07-21T18:30:00.000Z

workspace/PRD.md written (282 lines). §1 intro, §2 global (9 subsections incl. SoD access control, response envelope, pagination, versioning w/ Credit common_fields:false exception, monetary round-half-up, OCC recommendation-create expected_service_version/ERR_STALE_VERSION 412, cascade+ledger conservation, nested retrieval left-to-right FK, 10-band validation order), §3 business logic (7 subsections), §4 42-endpoint table, §5 32-error catalogue.
Hard contracts PASS: field coverage 63/63, rule coverage all, §3 path purity 349 tokens 0 violations, all 40 enum/state + 32 error IDs surface in narrative.
Scaffold self-consistency notes: (1) service_utilization trigger references /usage endpoint that doesn't exist — documented as computed at create + at recommendation time. (2) rec_type==SANCTION under-specified (no state change/field write declared) — documented as zero-savings, no invented field.

## Step 5: Generate unit tests — 2026-07-21T18:48:00.000Z

61 tests, all collect cleanly. Queue A (Difficulty): 36 tests — all 18 depth instances (9 rules×2), each covered by 2 tests. Queue B (Corner): 25 tests — all 25 non-stub breadth instances, 1 test each. 0 instances skipped. 4 excluded_because stubs correctly NOT translated. test_helpers/: 9 modules (Credit modeled append-only id+created_at only; api_client 42 endpoint methods; 31 errors registered; SoD entity_backed builders). test_suite/: conftest + 6 domain test files. All 82 PRD citations verified verbatim; computed values recomputed & confirmed (113000/90500, 47750, 30164/30172, 360000/210000, 90000, 70.00/71.67, 2026-11-01). No skip/xfail markers.

## Step 6: Generate implementation — 2026-07-21T18:48:00.000Z

Python+Flask in-memory API at workspace/implementation/. Files: start.sh (foreground, $PORT default 10000, binds 0.0.0.0, guarded pip install), app.py (factory, error handlers, no seeding), core.py (Store dicts, logical clock default 2026-05-01T00:00:00Z, envelope, pagination, RBAC, Decimal ROUND_HALF_UP calcs), routes_inventory.py, routes_invoice.py, routes_costcenter.py. Route count VERIFIED: 42 non-static Flask rules == 42 scaffold endpoints. Boots cleanly.
PRD ambiguities resolved: version-bump policy (status transition + own mutation bump once/request; §2.7 cascades bump every affected versioned entity; incidental computed-field refreshes don't bump); rec-create check order utilization(band8) before OCC(band10) per §2.9; allocation-approve frozen(band6) before ownership(band8) per §2.9; SANCTION implement = realized_savings 0 + rec→IMPLEMENTED + service version bump, no invented flag; datetimes echoed verbatim, internal insertion sequence for deterministic ordering; cost-center code uniqueness not enforced (no error code defined).

## Step 7: Test + fix loop (2 waves of 4) — 2026-07-21T19:00:00.000Z

Iterations run: 2 (initial sweep, then 1 fix + confirming sweep).
Root cause: test_implement_downgrade_recomputes_contract_committed_cost (test_02_rightsizing) failed identically in all 8 rounds on its PRECONDITION assertion (scen["contract"]["monthly_committed_cost_cents"] == 120000, got 0).
Diagnosis STEP 2 (fixture bug, NOT impl): PRD §3.2 states verbatim "Creating a service also refreshes its parent contract's monthly_committed_cost_cents." Impl correct (routes_inventory.py:269 calls recompute_contract_committed after service create). Fixture bug: setup_service in test_helpers/fixtures.py returned base["contract"] snapshot captured BEFORE the service was added (committed still 0).
Fix applied — test_helpers/ ONLY: fixtures.py setup_service() re-fetches contract via api.get_contract after new_service so base["contract"] reflects refreshed monthly_committed_cost_cents. (get_contract ALL_ROLES-guarded, SOURCING header authorized.)
No test_suite/ or implementation/ changes — impl already PRD-faithful.
Deletions: 0. test_suite fixes: 0. test_helpers fixes: 1. implementation fixes: 0.
Orchestrator independent verification: re-parsed all 8 results.{1..8}.json — each 61/61 passed, failed=0 errors=0 skipped=0; per-test outcomes all "passed"; no skip/xfail/error tokens. No orphan servers.

## Step 8: Finalize PRD — 2026-07-21T19:05:00.000Z

NOT skipped (test_helpers fixes=1 ≠ 0). PRD_FINALIZED.md written = verbatim copy of PRD.md (282 vs 282 lines, 0% delta), confirmed identical via diff. 0 content edits — sole Step-7 item is a pure fixture bug already covered verbatim by PRD §3.2 ("Creating a service also refreshes its parent contract's monthly_committed_cost_cents..."); impl routes_inventory.py create_service() calls recompute_contract_committed at line 269. A pure fixture bug PRD already covers is not a PRD silence → no edit warranted.

## Step 9: Complete PRD — 2026-07-21T19:12:00.000Z

PRD_COMPLETED.md written from PRD_FINALIZED.md. 282→282 lines (in-paragraph edits only), char delta +2,502. 6 ambiguity-pins + 5 mismatch-revisions = 11 changes.
- §2.3 insert — pagination coercion (limit non-int→10/<1→1/>100→100; offset neg→0/non-int→0) + deterministic tie-break by internal insertion seq. core.py:269-286,300-302.
- §3.1 insert — renewal term_end re-render mirrors prior fractional precision. core.py:93-97, routes_inventory.py:174-175.
- §3.1 insert — clock echo returns verbatim to_iso8601 input, not reformatted. routes_inventory.py:43-45.
- §3.2 insert — service-create contract committed refresh does NOT bump contract version/updated_at. routes_inventory.py:269.
- §3.3 revise — rec-create DOWNGRADE_SEATS utilization gate (band8) BEFORE OCC version guard (band10). routes_inventory.py:291-299.
- §3.3 insert — SANCTION-implement: qty/status unchanged, realized_savings 0, service+parent-contract version still bump. routes_inventory.py:351-365.
- §3.4 insert — line-item-add invoice billed/net refresh does NOT bump invoice version. routes_invoice.py:102-103.
- §3.4 insert — review recomputes each line expected/variance/net in place WITHOUT bumping line version; only invoice version bumps. routes_invoice.py:116-132.
- §3.6 revise — cost-center code NOT enforced unique (duplicates accepted). routes_costcenter.py:11-23.
- §3.6 insert — bulk allocation-create returns 201, array response_type, input order. routes_invoice.py:299, core.py:154-161.
- §3.6 revise — allocation-approve FROZEN (band6) BEFORE ownership (band8). routes_costcenter.py:59-68.
Verified: 11 changed lines vs PRD_FINALIZED.md via diff.

## Pipeline complete — 2026-07-21T19:12:00.000Z
All 9 steps done. Final artifacts present: SCAFFOLD.yaml + 2 design indices, PRD.md/PRD_FINALIZED.md/PRD_COMPLETED.md, test_helpers/ (9 modules), test_suite/ (conftest+6), implementation/ (42 routes). Sweep: 8/8 rounds × 61/61 passed, 0 skip/xfail/error. Route count 42==42 scaffold endpoints.
