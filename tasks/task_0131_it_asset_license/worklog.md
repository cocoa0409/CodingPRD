# Worklog — task_0131_it_asset_license

## Step 1: Create task directory — 2026-06-03T17:37:39.000Z

Created `tasks/task_0131_it_asset_license/` and `tasks/task_0131_it_asset_license/workspace/`. Pre-allocated index (not auto-scanned) per orchestration directive (7 pipelines running in parallel).

## Step 2: Generate scaffold (Expert difficulty) — 2026-06-03T17:58:33.000Z

All three required files written and lint-clean: SCAFFOLD.yaml (1326 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1004 lines), SCAFFOLD_CORNER_DESIGN.yaml (886 lines). Generated purely from scenario + skill spec; no sibling tasks read.

**Counts:**
- Entities: 12 (Vendor, Employee, SoftwareProduct, HardwareAsset, WarrantyLease, LicenseEntitlement, InstallationRecord, AssignmentCheckout, DisposalRequest, RenewalOrder, TrueUpReconciliation, ComplianceFinding)
- State machines: 8 (HardwareAsset, LicenseEntitlement, WarrantyLease, InstallationRecord, AssignmentCheckout, DisposalRequest, RenewalOrder, TrueUpReconciliation) + 2 concurrency rules (OCC on entitlement version)
- Calculations: 4 (asset_depreciation dual-variant, true_up_position dual-variant, required_core_units, renewal_cost)
- Validations: 17 (priority-ordered)
- Endpoints: 51 | Errors: 21 | Roles: 3 (AssetManager, ComplianceOfficer, Employee)
- §1.8: 18 instances (9 Difficulty Rules × 2) | §1.9: 23 active + 5 excluded_because stubs across 7 sections

**Lint:** VERDICT clean lint — 288 §1.8/§1.9 calls conform to §1.5, all 17 FKs reverse-reachable. All grounds[] resolve into §1.1–§1.7, all error_ids referenced, no duplicate instance names, all stub difficulty_instance cites exist.

**Design notes:**
- Archetype: Ledger-reconciliation + Quota/allocation; topology flat (FK-joined peers), state shapes cyclic (HardwareAsset, LicenseEntitlement, WarrantyLease) + branching (DisposalRequest), role model segregation_of_duties (disposal submitter ≠ approver via X-User-ID).
- Two dual-variant calcs: depreciation (book/whole-month-floor NBV=180000 vs disposal-final/partial-month-ceil NBV=170000, gain/loss=-20000) on HardwareAsset; true-up position (LIVE +1/COMPLIANT vs AUDIT -1/OVER_DEPLOYED, PENDING installs + grace included) on SoftwareProduct.
- Combinatorial modes (a)+(b): per-core max(min_core_units, ceil(cores*core_factor)) (5 vs floor-wins 4); renewal cost with pinned round-then-sum order (9996 vs wrong sum-then-round 9995, 1-cent divergence).
- Depth-3 cascade: disposal-complete → asset DISPOSED → installs UNINSTALLED → entitlement.consumed_units decremented. All formula-derived asserts pre-computed as literals.
- YAML gotchas fixed: unquoted `field?` tokens in [...] flow input lists (quoted); $.data[0]... JSONPaths inside {...} flow-map captures (quoted). Added GET /assets/software-products (vendor_id filter) and GET /assets/findings/{id} for FK reverse-reachability (f).

## Step 3: Copy INSTRUCTION.md — 2026-06-03T17:58:54.000Z

Copied ./INSTRUCTION.md → tasks/task_0131_it_asset_license/workspace/INSTRUCTION.md

## Step 4: Generate PRD — 2026-06-03T18:00:00.000Z

Output: workspace/PRD.md (251 lines). Reads SCAFFOLD.yaml only; both design index files withheld and not opened.

Sections: §1 Introduction (3 paras), §2 Global Specs (8 subsections: RBAC 3 roles, response envelope, pagination, server clock, common properties, derived-field reconciliation+precision, OCC on entitlement writes, validation-ordering ladder), §3 Business Logic (7 lifecycle subsections), §4 endpoint table (51 endpoints, 4 cols), §5 error table (21 codes, 2 cols).

Hard Contracts all PASS: Contract 1 (72 field/param names, 0 missing — fixed `verdict` gap), Contract 2 (all 4 calcs, OCC rules, transitions, cascades, priorities in prose; 27 spot-checks pass), Contract 3 (§3 path purity, 361 tokens, 0 violations).

Notable: dual-variant calcs rendered as prose contrasts (depreciation provisional-floor vs disposal-whole-month-ceil, half-up applied once; true-up live vs audit operand-for-operand; renewal round-then-sum order in words). State machines as transition-pair narrative (not endpoint paths). Information scattering across subsections (checkout params vs guards; OCC field in §2.7 re-anchored in §3.4/§3.5).

## Step 5: Generate unit tests — 2026-06-03T18:18:00.000Z

test_helpers/ (9 files): __init__.py, types.py (23 enums + entity TypedDicts; ComplianceFinding common_fields:false — id+created_at only, no version/updated_at), api_client.py (52 endpoints + set_clock), api_errors.py (21 errors + HTTP status map), assertions.py, factories.py, constants.py, test_users.py (opaque AssetManager/ComplianceOfficer + per-id builders for disposal seg-of-duties; entity_backed Employee), fixtures.py (5-tier composites; installs re-read entitlement version before each create for OCC).

test_suite/ (conftest + 6 files): 57 test functions, all collect cleanly.

Coverage:
- Queue A (Difficulty): 17 of 18 translated (≥2 tests each, 35 tests). 1 skipped: resource_temporal_overlap/checkout_half_open_interval_overlap — recipe asserts ERR_CHECKOUT_OVERLAP against a RETURNED checkout, but PRD §3.3 scopes overlap to "any existing open checkout" → not uniquely derivable.
- Queue B (Corner): 22 of 24 non-stub translated (1 test each). 1 skipped: state_machines/force_expire_entitlement_before_term_end_rejected — asserts ERR_COVERAGE_NOT_ENDED but PRD §3.4 names ERR_TERM_NOT_ENDED (scaffold asserts wrong error_id). 6 excluded_because stubs correctly not translated.

Verification: every test carries exactly one Design: line resolving to a real non-stub instance; all 72 quoted PRD citations verbatim; no skip/skipif/xfail; no scaffold leakage; all files byte-compile.

## Step 6: Generate implementation — 2026-06-03T18:18:00.000Z

workspace/implementation/ layout: start.sh (foreground, reads $PORT default 10000, binds 0.0.0.0, guards pip install on `import flask`), app.py (Flask entry + all routes), db.py (in-memory dicts keyed by UUID, wipes on boot, no seeding), errors.py (21 errors), auth.py (X-User-ID/X-User-Role + RBAC), response.py (verbatim envelope), validate.py, listing.py (sort created_at + paginate), timeutil.py (ISO + whole/ceil month arithmetic), clock.py, calculations.py, derive.py, serialize.py.

Endpoints: all 53 PRD §4 endpoints (clock + 12 entity groups), exact RBAC per §1.7, /assets prefix.

4 calculations: (1) asset_depreciation dual-variant — Decimal per-month rate, round_half_up applied once to per_month×capped_months, clamped to depreciable base; provisional floored months vs disposal-final ceil partial month. (2) required_core_units — PER_SEAT→1; PER_CORE→max(min_core_units, ceil(cores×core_factor)), ceil before floor. (3) renewal_cost — each line round_half_up before summing (round-then-sum pinned); coverage round_half_up(monthly×months). (4) true_up_position dual-variant — LIVE excludes PENDING installs + grace/suspended; AUDIT includes PENDING + grace/RENEWED/SUSPENDED.

OCC: version starts 1, increments on every mutation incl. derived recomputes (db.touch). OCC on expected_entitlement_version for POST /installations and renewal-orders/{id}/complete with target_type=ENTITLEMENT; mismatch→ERR_STALE_VERSION 412; omission/non-entitlement skips check. Validation ladder per §2.8: auth→forbidden→not-found(L→R)→invalid-request→state→OCC→business.

PRD ambiguities resolved (Step 8 pin candidates):
- Envelope api_request_timestamp: real wall-clock UTC, NOT settable server clock.
- support_status OUT_OF_WARRANTY (coverage existed but window passed, status still ACTIVE/RENEWED) vs UNCOVERED (never had ACTIVE/RENEWED coverage).
- version bump on derived-only reads: touch only when recompute changes a value (idempotent GETs).
- Reversal depreciation basis: recomputed provisionally against current clock; uninstalled installs not resurrected.
- disposal_gain_loss_cents zeroed at reversal.
- Renewal complete on missing target entity: ERR_NOT_FOUND defensively (unreachable; entities never deleted).

## Step 7: Run tests and iterate — 2026-06-03T18:35:00.000Z

All tasks complete. Three consecutive 8-round parallel sweeps (24 rounds) are fully green at 56/56.

**Iterations run:** 1 fix iteration, then 3 confirmation 8-round sweeps (24 rounds total), all green at 56/56.

The initial sweep showed 5 union failures across all 8 rounds: 3 deterministic logic failures and 2 boot-contention "could not be restarted" errors that only fired under 8x concurrent load (they passed in single-run isolation — a flakiness signal, not a logic bug).

**Tests deleted (PRD-silence category):**
- test_coverage_overlap_on_closed_window_rejected (test_05_renewals_coverage.py) — UNIQUE-DERIVABILITY collapse. PRD line 124 explicitly states "zero-gap adjacency where one ends exactly as the next begins is permitted." The test asserted a new window starting exactly on the prior window's closed end (06-30 == 06-30) is rejected as overlap, but that case is precisely the "ends exactly as the next begins" carve-out the PRD permits. Implementation correctly uses half-open overlap (touch-point allowed). Scaffold rule: Difficulty/resource_temporal_overlap/coverage_closed_interval_adjacency_allowed.

**Tests fixed for PRD faithfulness (test_suite/):**
- test_create_entitlement_invalid_term_window_returns_error (test_01_inventory_crud.py) — BRANCH/PATHWAY SILENCE. PRD ties ERR_INVALID_TERM_WINDOW to activation only ("activation requires... its term window be well-formed... a reversed window is rejected"); creation is silent on window ordering. Test asserted the error at creation. Made it MORE faithful: create the entitlement (succeeds in DRAFT), then call activate_entitlement with the reversed window and assert the error there — matching the test's own docstring quote.
- test_support_status_reconciles_to_out_of_warranty_after_expiry → renamed test_support_status_reconciles_to_in_warranty_while_active (test_05_renewals_coverage.py) — ENUM-MEMBERSHIP-ONLY collapse, handled via STEP 1c partial-coverage split. PRD line 122 names only two deciding inputs ("whether an active coverage record spans the current server clock and whether that coverage is a warranty or a lease") and gives no prose distinguishing OUT_OF_WARRANTY from UNCOVERED for an explicitly-EXPIRED warranty. Kept the fully-derivable IN_WARRANTY assertion; dropped the undetermined OUT_OF_WARRANTY assertion.

**Fixes applied to test_helpers/:**
- api_client.py — ApiClient._request now sets Connection: close and retries once on requests.ConnectionError, hardening against the stale keep-alive flake that the session-scoped client can hit across per-test-server restarts.

**Fixes applied to implementation/:**
- app.py — replaced the bare app.run() entry point with _serve(), a 20s bind-retry loop around werkzeug.serving.make_server. Under 8 concurrent sweep rounds the prior server on the reused port may not have released its socket before the next boot tries to bind; the old code crashed with "Address already in use" → the runner reported "could not be restarted" on the same 2 tests every round. The retry rides out that window. Storage remains in-memory only; no seeding added.

The 2 boot-contention errors and 3 logic failures are all resolved; 24/24 rounds passed 56/56. Final results.{1..8}.json all 56/56.

## Step 8: Finalize PRD — 2026-06-03T18:42:00.000Z

Output: workspace/PRD_FINALIZED.md (250 lines; PRD.md = 250 lines; 0-line delta, 2 lines revised in place ~0.8%). Aligned to implementation/ behavior; tests treated as auxiliary only.

Changes (2 edits, both at §3.2):
- §3.2 support_status resolution (line 122) — revise — pinned OUT_OF_WARRANTY vs UNCOVERED distinction PRD left undetermined: only ACTIVE/RENEWED coverage records considered (CANCELLED/EXPIRED disregarded); spanning warranty → IN_WARRANTY (precedence over lease), spanning lease → LEASED; no spanning record but ≥1 ACTIVE/RENEWED record exists → OUT_OF_WARRANTY; no ACTIVE/RENEWED record → UNCOVERED. (derive.py:14-50)
- §3.2 coverage overlap (line 124) — revise — replaced misleading "closed intervals" phrasing with impl's half-open rule: overlap only when new_start < existing_end AND existing_start < new_end; shared-endpoint touch at either boundary permitted; check applies only at creation, not on renewal. (app.py:631-637)

Items confirmed needing no PRD edit: api_client.py keep-alive retry and app.py bind-retry (infrastructure/boot only, no behavioral signal); test_create_entitlement_invalid_term_window (PRD line 134 already ties reversed-window check to activation and is silent on creation; impl matches — test was realigned to already-correct PRD prose).

NO-NEW-MISMATCH per-edit search confirmed: support_status — sole logic in derive.recompute_asset_support_status, all callers (create_coverage, transition_coverage, renewal-complete-coverage, refresh_asset_on_read, asset-create initial UNCOVERED) route through it, uniform. coverage overlap — only ERR_COVERAGE_OVERLAP check is create_coverage app.py:636; no overlap re-check on renewal-complete; scoped sentence to creation only.

## Step 9: Complete PRD — 2026-06-03T18:46:00.000Z

Output: workspace/PRD_COMPLETED.md (250 lines, 45006 chars; source PRD_FINALIZED.md 250 lines, 44699 chars; +307 chars, +0 lines, in-paragraph inserts only). Full PRD-vs-implementation scan. Aligned to implementation/; tests auxiliary only.

Counts: 2 ambiguity-pins, 0 mismatch-revisions.

Changes:
- §2.4 The Server Clock — insert — ambiguity — pinned that POST /assets/_clock/set_current_utc returns 200 OK with data.current_utc echoing the new clock instant as ISO 8601 UTC (3 fractional digits). (app.py:123-134)
- §3.7 True-Up Reconciliation and Compliance Findings — insert — ambiguity — pinned that finalize always mints the literal OVER_DEPLOYED finding_type (EXPIRED_IN_GRACE / NEGATIVE_AVAILABLE remain catalogue-only). (app.py:1233; cross-confirmed test_01:162,208)

Areas walked and confirmed already-pinned (no change): depreciation dual-variant + half-up-once; required_core_units per-seat=1/per-core ceil-then-floor; renewal round-then-sum + coverage cost; cyclic ACTIVE→RENEWED→ACTIVE; support-status resolution + overlap rules; OCC version bumps; disposal SoD/precedence + non-resurrection-on-reversal; true-up LIVE/AUDIT + position<0 verdict; lean ComplianceFinding shape; success/error envelopes. Free-form detail string left unpinned (PRD says only "human-readable", no test asserts text).

## Pipeline complete — 2026-06-03T18:46:00.000Z

All 9 steps done. Final state: 56 tests, 8/8 final sweep rounds 56/56 green. Artifacts: SCAFFOLD.yaml + 2 design files, PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ (9 files), test_suite/ (conftest + 6 files), workspace/implementation/ (14 files incl. start.sh), results.{1..8}.json all passing.
