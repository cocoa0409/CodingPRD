# Worklog — task_1028_rare_used_bookstore

## Step 1: Create task directory — 2026-07-15

Created tasks/task_1028_rare_used_bookstore/ and workspace/ subdir (pre-assigned folder, no index scan). Verified ./INSTRUCTION.md present.

## Step 2: Generate scaffold (subagent) — 2026-07-15

All three files are written, parse cleanly, and pass the scaffold linter with a clean verdict.

Generated the three scaffold artifacts for task_1028_rare_used_bookstore (Rare & Used Bookstore / Book-Scout) at the Expert difficulty band, purely from the scenario + skill spec (no sibling tasks consulted).

Files written (all three): SCAFFOLD.yaml (§1.0–§1.7, no design keys leaked), SCAFFOLD_DIFFICULTY_DESIGN.yaml (single key scaffold_difficulty_design), SCAFFOLD_CORNER_DESIGN.yaml (single key scaffold_corner_design).

Scale: 11 entities, 35 endpoints, 8 calculations, 7 state machines, 32 error codes, 15 ordered validations, 3 concurrency (OCC) rules, 4 roles.
- Entities: Patron, IntakeLot, BookItem, Appraisal, ConsignmentAgreement, CatalogListing, BuybackOffer, FairEvent, BoothSlot, SaleOrder, Shipment (provenance folded into a computed array on BookItem; packing station as a label).
- Archetype: ledger_reconciliation × temporal_windowing; flat topology; peer_roles (Patron entity_backed, others opaque).
- Endpoint count 35 (slightly above 20–32 band) because scenario spans 8 sub-domains with 12 FKs each needing reverse-reachability GETs.

State machines / non-linearity: ConsignmentAgreement cyclic (PROPOSED↔AMENDED); CatalogListing two independent parallel axes (online_status × shop_status); plus branching lifecycles on IntakeLot, BookItem, BuybackOffer, SaleOrder, Appraisal.

Difficulty coverage: all 9 rules × 2 instances = 18. §1.9 corner design adds 31 active instances (plus 3 excluded_because stubs). 3 OCC concurrency rules (appraisal-create, agreement-amend, listing-update), races resolved via parent version.

Validation: scaffold_lint.py reports VERDICT: clean lint (210 setup/trigger calls checked; all FK reverse-reachability satisfied). Fixed: nested-bracket YAML in grounds (quoted), dead enum values removed, api_prefix set to /. All formula-derived assertions computed in Python and pinned as literals. All 3 files also pass yaml.safe_load.

## Step 3: Copy INSTRUCTION.md — 2026-07-15

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md.

## Step 4: Generate PRD (subagent) — 2026-07-15

File written: workspace/PRD.md (254 lines). Endpoints covered: 35 (all scaffold endpoints, §4 table). Error codes: 32 (§5 table). All three hard contracts PASS (field coverage, rule coverage, path purity). Neither withheld design file opened.
- Field coverage: all entity fields + endpoint request_body/query/path params present incl. line_items sub-fields, provenance sub-fields, three expected_*_version OCC fields.
- Rule coverage: 15 validations (fixed order + both pinned priority-pair conflicts), 3 concurrency OCC rejections (ERR_STALE_VERSION 412), 7 state machines (depth-2 lot-reject, depth-3 sale-confirm cascade+refund, parallel CatalogListing axes, cyclic ConsignmentAgreement), 8 calculations fully expressed.
- Path purity PASS (0 path tokens in §3).

## Step 5: Generate unit tests (subagent) — 2026-07-15

test_helpers/ (9 files) + test_suite/ (conftest + 9 domain files, 66 test functions). All collect under pytest with zero errors.
- Queue A (Difficulty): all 18 instances × 2 tests = 36.
- Queue B (Corner): 30 of 31 non-stub instances × 1 test = 30.
- 1 instance SKIPPED: Corner/state_machines/settle_rejected_lot_returns_409_terminal_lockdown — asserts ERR_INVALID_STATE with no trigger-condition prose in PRD (fails C1/error-in-prose + unique-derivability). Gap left as gap.
- 3 excluded_because stubs correctly NOT translated. Every test docstring ends with one verbatim Design: line (66/66).

## Step 6: Generate implementation (subagent) — 2026-07-15

workspace/implementation/: app.py (single-module), requirements.txt (Flask 3.0.3), start.sh (guarded-install foreground, $PORT default 10000, binds 0.0.0.0). 36 @app.route = 35 API + 1 health. ast.parse PARSE_OK. In-memory dicts only, no startup seeding.
- Live smoke passed: envelope, auth/RBAC, appraisal dual-variant (21000/33600), OCC (ERR_STALE_VERSION 412, grade doesn't bump version), sale-confirm depth-3 cascade + refund reversal, buyback boundary (5000/5001), booth overlap outranks capacity (half-open), shipping cost (3100), packing 15-min buffer, priority-pair #1 (ERR_ITEM_NOT_LISTED outranks ERR_CONSIGNMENT_NOT_ACTIVE), lot-reject depth-2 cascade, empty-lot settle, catalog illegal-axis ERR_INVALID_STATE, pagination out-of-range 400.
- One deliberate simplification noted by impl-gen: per-record Patron ownership filtering (PRD §2.1) not enforced (only role-based endpoint permissions); flagged as spec-ambiguous.

## Step 7: Run tests and iterate (subagent) — 2026-07-15

All 8 rounds pass 66/66 (2-wave sweep via sweep.sh). Clean sweep achieved.
- Iterations run: 2 (initial diagnostic sweep + 1 fix sweep).
- Tests deleted: None.
- Fixes applied to test_helpers/: None.
- Fixes applied to implementation/:
  - app.py, function create_listing (POST book-items/<bid>/listing): swapped error-precedence so duplicate-listing check runs BEFORE the APPRAISED-status check.
- Diagnosis: single consistent failure was test_duplicate_listing_rejected (expected ERR_DUPLICATE_LISTING, got ERR_ITEM_NOT_APPRAISED). PRD §3.4 says creating a listing moves book APPRAISED→LISTED, so a second listing attempt targets a LISTED book; impl checked status!=APPRAISED first. Reversed the two checks (safe: INTAKE/GRADED books still fall through to ERR_ITEM_NOT_APPRAISED). Confirmed 66/66 across full 8-round sweep.

## Step 8: Finalize PRD (subagent) — 2026-07-15

Produced workspace/PRD_FINALIZED.md. PRD.md = 254 lines; PRD_FINALIZED.md = 254 lines (~0.4% revised, 1 line).
- §3.4 (Catalog Listings) — revise — Pinned that the duplicate-listing check runs before and outranks the APPRAISED-status check: a book with an existing listing fails ERR_DUPLICATE_LISTING regardless of status; only a book with no existing listing is subject to ERR_ITEM_NOT_APPRAISED. (impl app.py:695-698 create_listing).
- Pre-edit search confirmed: listing_for_book helper fires on any status; other ERR_DUPLICATE_LISTING callsite (propose_agreement) and ERR_ITEM_NOT_APPRAISED callsite (agreement activate) unrelated; scoped wording to listing creation only.

## Step 9: Complete PRD (subagent) — 2026-07-15

Produced workspace/PRD_COMPLETED.md over PRD_FINALIZED.md. Both 254 lines; 37,288 → 39,289 chars (+2,001). Counts: 9 ambiguity-pins, 1 mismatch-revision (10 passages).
- §2.3 Pagination — insert — out-of-range/non-integer limit/offset rejected ERR_INVALID_REQUEST (not clamped) — app.py:339-354.
- §3.1 Patrons — insert — default_commission_pct only non-negativity enforced; >1 accepted — app.py:459.
- §3.2 Intake — insert — intake into non-DRAFT lot → ERR_INVALID_STATE after body validation — app.py:520-526.
- §3.2 Intake — insert — settle/reject require lot DRAFT (ERR_INVALID_STATE), state check first — app.py:554-555,572-573.
- §3.3 Appraisals — revise (mismatch) — appraisal list ascending created_at (PRD said reverse) — app.py:685,361.
- §3.4 Catalog listing — insert — only DRAFT→LIVE/DRAFT→ON_SHELF clerk advance; other axis changes ERR_INVALID_STATE before version check; same-value no-op — app.py:849-854.
- §3.5 Consignment — insert — activation requires PROPOSED/AMENDED (ERR_INVALID_STATE) before book-status check — app.py:822-828.
- §3.8 Sale confirm — insert — order must be DRAFT (ERR_INVALID_STATE) before four business checks — app.py:1122-1123.
- §3.8 Sale confirm — insert — each sold book gets provenance entry type SOLD — app.py:1161.
- §3.8 Sale refund — insert — append-only SOLD provenance retained on refund — app.py:1211-1249.
- §3.9 Shipment — revise (mismatch) — creation checks only order exists; no order-status guard — app.py:1252-1255.

## Pipeline complete — 2026-07-15

Full Step 1→9 pipeline finished. Final 8-round stability sweep: all 8 rounds 66/66 (passed==total). Outputs present: SCAFFOLD.yaml + 2 design files, test_helpers/, test_suite/ (66 tests), workspace/implementation/ (app.py, start.sh, requirements.txt, sweep.sh, results.1-8.json), PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md.
