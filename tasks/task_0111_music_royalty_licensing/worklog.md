# Worklog — task_0111_music_royalty_licensing

## Step 1: Create task directory — 2026-06-03T00:00:00.000Z

Created `tasks/task_0111_music_royalty_licensing/` and `tasks/task_0111_music_royalty_licensing/workspace/` (pre-assigned index, Step 1 scan skipped per run instructions).

## Step 2: Generate scaffold — 2026-06-03T04:00:00.000Z

All three scaffold artifacts are generated, self-consistent, and pass `scaffold_lint.py` clean.

Generated the full scaffold package for **task_0111_music_royalty_licensing** (Music Royalty & Licensing), built fresh from the scenario + skill spec (no sibling tasks consulted):
- SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml

**Counts:**
- Entities: **12** (Rightsholder, Work, CompositionShare, Recording, RecordingShare, RightsWindow, UsageEvent, SyncLicense, Advance, Statement, LedgerEntry, Payout)
- Endpoints: **49**
- State machines (with transitions): **5** (SyncLicense, UsageEvent, Statement, Advance, Payout; plus Work's shares_locked gate) + 2 concurrency rules
- Calculations: **4** (performance_pool_royalty, mechanical_statutory_royalty, sync_quote_fee, advance_recoupment)
- Errors: 20, Validations: 20, Roles: 4
- §1.8: 9 difficulty rules × 2 = **18 instances**; §1.9: **32 active corner instances + 8 stubs**

**Difficulty band:** Targeted **Expert**. Entity count (12) sits squarely in the Expert range (10–15). The endpoint count (49) overshoots the 20–32 guideline — documented FK-reverse-reachability overage for an FK-dense ledger domain (13 real foreign keys across 12 entities). Surface is lint-clean; difficulty carried by tight coupling (provisional-vs-final royalty, advance recoupment ledger, dual rounding-order pools, sync tiering, two interval-overlap arithmetics, finalize↔reopen / payout↔reverse compensating invariants), not volume.

**Verification:** `scaffold_lint.py` reports `VERDICT: clean lint` (503 calls scanned). All formula literals computed and pinned; all `grounds` references resolve; all instance names unique; all 8 `excluded_because` stubs cite real §1.8 instances; OCC `expected_statement_version` inputs always `${var}`-bound.

## Step 3: Copy shared files — 2026-06-03T04:00:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_0111_music_royalty_licensing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-03T04:04:00.000Z

Generated `workspace/PRD.md` — **271 lines**. Read SCAFFOLD.yaml only; both design YAMLs withheld.

**Sections covered:**
- §1 Introduction — composition/recording split, advance recoupment, provisional-vs-final accounting.
- §2 Global Specifications (8 subsections): 2.1 RBAC (4 roles, explicit identity translation — opaque for Administrator/RoyaltyOperator, entity-backed for Licensee/Rightsholder), 2.2 Response Structure (verbatim), 2.3 Pagination, 2.4 Common Properties & Versioning (LedgerEntry as common_fields:false exception), 2.5 Cascading Reconciliation & Derived Fields, 2.6 Monetary Precision, 2.7 OCC on statements (finalize + reopen, expected_statement_version + ERR_STALE_VERSION/412), 2.8 Existence/FK/Validation Ordering.
- §3 Business Logic (9 subsections): parties & share-locking, rights windows, usage ingest/allocate, sync licensing & negotiation loop, advances & recoupment, statement settlement, royalty/pricing calculations, payouts, deterministic test clock.
- §4 Endpoint Definitions — 4-column table, all 49 endpoints.
- §5 Error Code Catalogue — 2-column table, all 20 error IDs.

**Hard Contract reports:** Contract 1 (Field-Name Coverage) entities 52/52, request_body 36/36, query_params 11/11 — PASS. Contract 2 (Rule Coverage) both OCC rules, all calc constants/formulas, state transitions, side-effect cascades, sibling-branch symmetry, validation priority — PASS. Contract 3 (§3 Path Purity) 459 tokens, 0 violations — PASS.

**Scaffold ambiguity note:** Statement declares parent:Rightsholder and LedgerEntry/Payout declare parent:Statement, yet endpoint paths are top-level peer collections (/statements, /payouts, with /statements/{id}/ledger and /statements/{id}/payouts as reverse-reach list reads). Treated parent keys as logical FK relationships via narrative actions, not nested URL ownership, consistent with complexity_profile graph topology.

## Step 5: Generate unit tests — 2026-06-03T04:35:00.000Z

Generated test infrastructure from the two design indices (PRD-adjudicated).

**test_helpers/ — 8 files + __init__.py:** types.py (entity TypedDicts; LedgerEntry append-only: id+created_at only; 14 enums), api_client.py (one method per endpoint incl. /_clock/set_current_utc), api_errors.py (ApiErrorId enum + HTTP-status map), assertions.py (PRD-exact field names), factories.py (required vs optional honored; auto-sequencing ISWC/ISRC), constants.py (PRO rates, mechanical tiers, sync multipliers, cooldown buffer), test_users.py (opaque headers for Administrator/RoyaltyOperator; per-instance make_licensee_headers/make_rightsholder_headers for entity_backed roles), fixtures.py (composite pipelines).

**test_suite/ — 8 test files + conftest.py, 67 test functions:** test_01 catalog/validation, test_02 RBAC/auth, test_03 royalty calculations, test_04 usage allocation, test_05 sync licensing, test_06 statement settlement, test_07 payouts, test_08 temporal overlaps.

**Coverage:** All 18 difficulty instances ≥2 tests; 31/32 corner non-stub instances ≥1 test; all 8 stubs untranslated. Every test carries verbatim PRD citation + exactly one Design: tag resolving to a real instance.

**1 instance skipped:** `Corner/state_machines/reopen_with_settled_payout_blocked` — unique-derivability failure. A SETTLED payout pins the statement in PAID (reverts to FINALIZED only on payout REVERSE per §3.8). Reopen requires FINALIZED, so under §2.8 ascending-priority a faithful PRD-only implementer returns ERR_INVALID_STATE (priority 6), not asserted ERR_PAYOUT_EXISTS (priority 18). Skipped, documented inline in test_06.

## Step 6: Generate implementation — 2026-06-03T04:35:00.000Z

Built complete Python + Flask in-memory REST API at workspace/implementation/.

**Files:** start.sh (guarded pip install on `import flask`, exec python3 app.py), requirements.txt (flask==3.0.3), app.py (blueprint registration, ApiError/404/405 handlers, binds 0.0.0.0:$PORT), db.py (in-memory dicts keyed by id, monotonic _seq, logical test clock), errors.py (ApiError + all 20 error tuples), response.py (envelope helpers, ISO-8601 UTC 3 fractional digits), middleware.py (X-User-ID/X-User-Role auth, 4 roles, RBAC), services/common.py (common-field stamping, round_half_up/floor Decimal, validation, pagination), services/serialize.py (per-entity serializers w/ computed fields split_total_bps, lifetime_earned_cents, unrecouped_balance_cents), services/calculations.py (4 calcs, two-stage rounding), services/allocation.py (atomic EARNING distribution + statement gross recompute + version bump), services/lookup.py (path existence, FK resolution, entity-backed ownership), routes/ (catalog, usage_events, sync_licenses, advances, statements, payouts, clock — 49 endpoints).

**Port binding:** start.sh reads $PORT (default 10000), guards install on `import flask`, exec's app.py → app.run(host=0.0.0.0, port=$PORT, threaded=True). Empty store every boot, no seeding.

**PRD ambiguities resolved (assumptions):**
1. Absent/missing FK value → ERR_FK_NOT_FOUND (priority 4 before body well-formedness priority 5).
2. Finalize check order: PRD §3.6 prose DRAFT-status → version-match(412) → unallocated-usage, inverting SCAFFOLD numeric priorities (16 before 17); implemented prose order per "PRD prose wins unconditionally."
3. Re-register/re-lock of already-locked Work/Recording → ERR_INVALID_STATE (no transition from shares_locked=true).
4. Sync execute "current UTC": pinned logical clock when set (§3.9), else wall-clock UTC.
5. Withholding/recoupment ledger rows only appended when non-zero.

## Step 7: Run tests and iterate — 2026-06-03T05:00:00.000Z

**Iterations run:** 1 (the initial 8-round parallel stability sweep).

**Result:** All 8 concurrent rounds passed 67/67 tests. Authoritative top-level counters per round: passed=67, failed=0, skipped=0, errors=0, total=67. Per-test verification via the `status` field confirmed all 67 tests show status="passed" in every round with no error_message. Round wall times uniform (~44.8–45.3s), no flakiness, no timeouts, no "could not be restarted" failures across all 8 test files (catalog/validation, RBAC/auth, royalty calculations, usage allocation, sync licensing, statement settlement, payouts, temporal overlaps).

Orchestrator independently re-verified all 8 results.{1..8}.json: passed=67 failed=0 total=67 errors=0 skipped=0 in every round.

**Tests deleted:** None — no test failed in any round, so STEP 1 (PRD coverage / unique-derivability) was never triggered.
**Fixes applied to test_helpers/:** None.
**Fixes applied to implementation/:** None.

## Step 8: Finalize PRD — 2026-06-03T05:00:00.000Z — SKIPPED

Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes (zero iterations beyond baseline). Per Step 8's skip condition, PRD.md already determined every behavior the implementation exhibits at every site Step 7 could observe; PRD_FINALIZED.md is not produced. Step 9 starts from PRD.md.

## Step 9: Complete PRD — 2026-06-03T05:10:00.000Z

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-implementation/ scan, starting from PRD.md (Step 8 skipped, no PRD_FINALIZED.md).

**Source vs completed:** PRD.md = 271 lines / 46,292 chars → PRD_COMPLETED.md = 271 lines / 48,163 chars (+1,871 chars). No line-count change (all edits in-paragraph; no new sections).

**Counts:** 11 distinct edit operations — 8 ambiguity-pins, 3 mismatch-revisions.

**Changes:**
- §2.1 RBAC — revise — ambiguity — unrecognized/empty/whitespace X-User-Role → ERR_UNAUTHENTICATED; ERR_UNAUTHORIZED only for recognized-but-disallowed role — middleware.py:26-29,37-38
- §2.3 Pagination — insert — ambiguity — out-of-range limit, negative offset, non-integer param → ERR_INVALID_REQUEST — services/common.py:131-148
- §2.4 Versioning — revise — ambiguity — version initial value is 1 on creation — services/common.py:13-22
- §3.1 Rightsholder suspend — insert — ambiguity — suspend has no state precondition; re-suspending SUSPENDED succeeds and bumps version — routes/catalog.py:64-70
- §3.1 Work register — revise — ambiguity — re-registering a locked work → ERR_INVALID_STATE, before split-total check — routes/catalog.py:113-116
- §3.1 Recording lock-shares — revise — ambiguity — re-locking a locked recording → ERR_INVALID_STATE, before split-total — routes/catalog.py:236-239
- §3.1 Share-add ordering — insert — mismatch — locked-parent check (ERR_SHARES_LOCKED) evaluated before share-total check, reversing §2.8's implied order — routes/catalog.py:138-142,257-261
- §3.2 Rights-window revoke — insert — ambiguity — revoke requires ACTIVE; revoking REVOKED → ERR_INVALID_STATE — routes/catalog.py:377-378
- §3.3 Usage ingest — revise — mismatch — gross_revenue_cents optional, defaults 0 for either usage type — routes/usage_events.py:36
- §3.3 Allocation rights coverage — insert — ambiguity — WW window covers any territory; single-territory window covers only exactly-equal code — routes/usage_events.py:91
- §3.4 Requote — insert — ambiguity — requote leaves recorded counter_fee_cents unchanged — routes/sync_licenses.py:104-117
- §3.6 Finalize withholding — revise — mismatch — WITHHOLDING ledger entry appended only when withholding_cents > 0 — routes/statements.py:177
- §3.9 Test clock — insert — ambiguity — missing/unparseable to_iso8601 → ERR_INVALID_REQUEST; success returns empty data object 200; clock falls back to wall-clock UTC until first set — routes/clock.py:18-22, db.py:33-34,68-69, routes/sync_licenses.py:170-171

**Left unchanged (additive/non-contradictory or already-pinned):** extra optional list filters not in §4 table; has_more arithmetic; read-time derivation of lifetime_earned_cents/unrecouped_balance_cents (covered by §2.5); 405→404 mapping (no PRD contract).

---

## Pipeline complete

All 9 steps finished. Final artifacts in tasks/task_0111_music_royalty_licensing/: SCAFFOLD.yaml + 2 design YAMLs, test_helpers/ (9 files), test_suite/ (8 test files + conftest, 67 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_COMPLETED.md, implementation/ (green, 67/67 × 8 rounds)}. Step 8 skipped (Step 7 clean on first sweep). PRD_FINALIZED.md intentionally absent.
