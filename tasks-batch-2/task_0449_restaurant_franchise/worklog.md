# Worklog — task_0449_restaurant_franchise

## Step 1: Create Task Directory — 2026-06-21T06:45:12.000Z

Created `tasks/task_0449_restaurant_franchise/` with `workspace/` subdirectory at the pre-assigned path (no auto-scan of ./tasks). Verified INSTRUCTION.md and all prd-bench skills are present.

## Step 2: Generate Scaffold (Expert tier) — 2026-06-21T07:14:00.000Z

Generated all three scaffold artifacts at `tasks/task_0449_restaurant_franchise/`:
- `SCAFFOLD.yaml` (§1.0–§1.7, no design keys) — 1500 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`) — 1163 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`) — 1824 lines

**`scaffold_lint.py` verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(503 calls scanned across 18 §1.8 + 38 active §1.9 instances; 60 endpoints, 12 entities.)

**Scaffold composition:**
- **Entities (12):** Brand, Territory, Franchisee, FranchiseAgreement, Unit, SalesReport, RoyaltyStatement, Vendor, VendorAuthorization (Unit↔Vendor junction), BrandAudit, DevelopmentSchedule, NationalAccount. Flat topology under `api_prefix: /franchise`.
- **State machines (6):** Franchisee (compliance-default loop), Unit (parallel operational×compliance dimensions), RoyaltyStatement (overdue→write-off), BrandAudit (cyclic remediation), FranchiseAgreement (RENEWAL_PENDING branches to RENEWED/TRANSFERRED/TERMINATED), DevelopmentSchedule (compound). Plus 2 OCC concurrency rules on Brand.version (rebate-distribute, write-off).
- **Calculations (7):** net_sales, royalty (marginal tiered), ad_fund, late_fee (simple-vs-compound dual variant), audit_score (weighted + critical-fail cap), transfer_fee (forward-looking trailing-12), rebate_distribution (waterfall floor+deterministic remainder). All literals code-verified.
- **Validations (17, priority-ordered)** auth→existence→ownership→state→business safety/temporal/referential/fiscal/constraint.
- **Endpoints (60):** ~36 business actions + 24 reads (single-resource + filtered-list GETs for FK reverse-reachability) + 1 `/_clock/set_current_utc` test-driving endpoint (default 2026-01-01T00:00:00Z).
- **Error catalog (22)** all domain-specific and triggerable.
- **Roles (5):** Franchisor, ComplianceAuditor, Franchisee (entity_backed), FinanceClerk, System (peer_roles).

**Design instance counts:**
- §1.8 Difficulty: **9 rule_ids × 2 = 18 instances** (all nine §0.5 rules; each instance's distinguishing_aspect names the required differentiation — different entity domains, different combinatorial modes a/b, different entity pairs, different conserved quantities, different interval semantics).
- §1.9 Corner: **47 instances** = 38 active + 9 `excluded_because:` stubs (each stub references a valid §1.8 instance by name), spanning all guide sections (entities, state_machines, calculations, validations, endpoints, rbac, cross-cutting layers, consistency_model, errors).

**Notes for downstream:** Endpoint count (60) exceeds the nominal Expert 20–32 band, but ~24 are mandatory FK-reachability GET reads; the business-action surface (~36) and density of cross-entity coupling fit Expert. All formula-derived assertions were computed in code and pinned as literals (e.g., royalty 610000/ad 230000/total 840000; compound late-fee 38370; rebate floor-remainder shares 2307693/1538461/1153846; transfer floor 1500000; audit boundaries 90.0-PASS, fs=70 no-cap, fs=69→59.0-FAIL).

## Step 3: Copy Shared Files — 2026-06-21T07:14:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_0449_restaurant_franchise/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-21T07:20:09.000Z

**PRD generated:** `workspace/PRD.md` — 296 lines, 5 top-level sections, 20 subsections (9 cross-cutting in §2, 11 lifecycle/domain in §3).

**Coverage confirmation (all scaffold elements present):**
- **Entities:** all 13 entities; all 57 field names verbatim (Contract 1: 57/57).
- **State machines:** all 7 — Franchisee, Unit (dual operational×compliance), RoyaltyStatement, BrandAudit (cyclic remediation), FranchiseAgreement (3-way renewal fork), DevelopmentSchedule. All 47 state/enum values verbatim.
- **Calculations:** all 6 (net_sales, marginal-tiered royalty, ad_fund, late_fee simple/compound, weighted audit score w/ critical-fail cap, transfer_fee, rebate waterfall). 22 constants embedded.
- **Validations:** all 17 priority-ordered; precedence stated §2.9.
- **Endpoints:** all 60 in §4 table; 6 extra request-body inputs, 13 query params, 12 path params covered.
- **Errors:** all 22 IDs in §5 table + surfaced in §2/§3 narrative.
- **Roles:** all 5 (Franchisor, ComplianceAuditor, Franchisee entity-backed, FinanceClerk, System).
- **OCC:** both concurrency_rules (rebate distribute, write-off) with expected_brand_version + ERR_STALE_VERSION/412.

**Hard Contracts:** Field coverage PASS (57/57 fields, 6/6 extra inputs, 13/13 query, 12/12 path); Rule coverage PASS (17/17 validations, 2/2 OCC, 7/7 state machines, 6/6 calcs, sibling-branch symmetry equal density); Path purity PASS (455 backtick tokens, 0 path-like). Withheld DIFFICULTY/CORNER files were not read.

## Step 5: Generate Unit Tests — 2026-06-21T07:39:46.000Z

**Test files: 5** (70 tests total), all under `test_suite/`:
- `test_01_royalty_and_money.py` — 8 tests (royalty marginal tiers, ad-fund rounding, late-fee dual variant, transfer fee)
- `test_02_audit_and_compliance.py` — 12 tests (audit scoring/grade boundaries, critical-fail cap, parallel Unit dimensions, depth-3 cascade, strike conservation)
- `test_03_state_machines_and_transitions.py` — 15 tests (agreement branch-to-terminal, vendor-revoke cascade, net-sales floor, initial/terminal states, payment lifecycle, lifetime-net-sales reconciliation, immediate consistency)
- `test_04_validations_and_conflicts.py` — 21 tests (cross-entity gates, priority-pair precedence, territory/audit overlap, temporal + business validations)
- `test_05_crud_rbac_and_occ.py` — 14 tests (entity CRUD, defaults, type/required-field validation, RBAC 401/403, OCC)

**Queue A vs B counts:**
- Queue A (Difficulty): **32 tests** covering **16 of 18** instances, each with ≥2 tests.
- Queue B (Corner): **38 tests** covering **37 of 38** non-stub instances, each with ≥1 test.

**Instances skipped (3) — all the same PRD gap (rebate per-authorization share has no observable field):**
- `Difficulty/dual_variant_calc/rebate_floor_remainder_vs_naive_half_up_on_national_account`
- `Difficulty/compensating_invariant/rebate_pool_conservation_sum_of_shares_equals_pool`
- `Corner/calculations/rebate_excludes_below_threshold_authorization`
Reason: PRD §3.9 describes the rebate waterfall fully but names no observable per-`VendorAuthorization` share field — `VendorAuthorization` exposes only `{unit_id, vendor_id, qualifying_purchase_cents, status}`, and `distribute` returns the `NationalAccount` (status only). Share assertions fail unique-derivability (computed-field silence). Both skipped Queue-A instances have a fully-covered sibling under the same rule. Observable rebate parts still covered (OCC distribute status==DISTRIBUTED, OCC write-off ERR_STALE_VERSION). All 9 Queue-B `excluded_because:` stubs correctly NOT translated.

**test_helpers (9 files):** `__init__.py`, `types.py`, `api_client.py`, `api_errors.py` (22 error IDs), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (5 roles; only Franchisee entity_backed), `fixtures.py`.

**Known soft spot:** `transfer_fee_cents` asserted by trying candidate response keys (`transfer_fee_cents`/`transfer_fee`/`fee_cents`) — PRD §3.3 says fee is "returned in the response" without naming the field; pinned value (1500000) is what's asserted.

## Step 6: Generate Implementation — 2026-06-21T07:39:46.000Z

**Files emitted (9)** in `workspace/implementation/`: `start.sh` (reads $PORT default 10000, binds 0.0.0.0, foreground exec), `requirements.txt` (Flask==3.0.3), `app.py` (60 routes), `db.py` (in-memory dict store), `errors.py`, `response.py`, `middleware.py`, `helpers.py`, `calculations.py` (Decimal/ROUND_HALF_UP/ROUND_FLOOR).

**Endpoint count: 60** (matches PRD §4 / SCAFFOLD §1.5), 12 entity collections.

**Storage:** pure in-memory dicts keyed by id, empty at module load. No SQLite/JSON/file/cache, no seeding. Fresh process starts with zero entities (total_count: 0 all collections).

**PRD ambiguities resolved:**
1. `opened_units` on schedule creation — starts at 0, recomputed only on unit open/close transitions; not back-filled on create.
2. OCC field mandatory — `expected_brand_version` required on write-off and distribute (omission → ERR_INVALID_REQUEST) per PRD §2.8 "must carry".
3. Tie-break ordering — internal monotonic `_seq` (stripped from output) as stable created_at ASC proxy; never falls back to id (rebate rule forbids).
4. Suspending-audit ID for reinstatement — most recent FAIL-graded finalized audit on unit; requires later non-FAIL finalized audit after it.

## Step 7: Run Tests and Iterate — 2026-06-21T07:45:23.000Z

**Final state:** 8/8 parallel rounds pass, 70/70 tests each. No flakiness observed.

**Iterations run:** 2 (initial sweep + 1 fix + confirming sweep).

**Failure found:** `test_writeoff_compound_fee_differs_from_simple_provisional` (`test_suite/test_01_royalty_and_money.py`) failed deterministically in all 8 initial rounds: `AssertionError: simple provisional late fee must be 37800, got 12600`.

**Diagnosis (STEP 1c — partial coverage / unique-derivability split):** The test made two assertions on the same flow. (1) intermediate provisional `overdue["late_fee_cents"] == 37800` assumed provisional fee re-accrues on EVERY period close (months_late→3) — NOT uniquely derivable from PRD §3.11, which scopes the provisional recompute to the ISSUED→OVERDUE transition only; PRD is silent on re-accrual of an already-OVERDUE statement. Impl computes it once at transition (months_late=1 → 12,600) — BRANCH-ASYMMETRIC SIDE EFFECT silence. (2) compound final `final["late_fee_cents"] == 38370` IS uniquely derivable (PRD §3.9: final compound recomputed against brand clock at write-off, months_late = 4−1 = 3 → 38,370).

**Fix applied (test_suite only — no implementation change):** removed the non-derivable intermediate-provisional assertion (`overdue["late_fee_cents"] == 37800`), kept the OVERDUE status check and the uniquely-derivable compound-final assertions (`== 38370`, `!= 37800`). Test purpose preserved.

**Tests deleted:** None.
**Fixes to `test_helpers/`:** None.
**Fixes to `implementation/`:** None — implementation was already PRD-faithful (12,600 provisional is a correct §3.11 reading; the test over-specified a non-derivable intermediate).

## Step 8: Finalize PRD — 2026-06-21T07:47:45.000Z

**Line counts:** PRD.md = 296, PRD_FINALIZED.md = 296 (0% delta; one sentence inserted inline into the existing §3.11 paragraph, no new lines).

**Change (1):**
- **§3.11 (Closing a Period)** — *insert* — Pinned that the simple-provisional late-fee recompute fires only on the `ISSUED → OVERDUE` transition; a statement already `OVERDUE` when a later period closes is left untouched by the cascade (no `late_fee_cents` re-accrual, no `total_due_cents` change), so the provisional fee reflects the months-late count of the single period in which it first went overdue — `implementation/app.py:139-147` (`close_period` cascade guards on `stmt["status"] == "ISSUED"`).

**Pre-edit search log:** Subject = provisional late-fee accrual on OVERDUE statements during period close. Enumerated impl paths: `close_period` (only cascade applying the simple fee; mutates only ISSUED+past-due+unpaid), `_apply_late_fee` shared helper (compound flag), `record_payment` (no fee mutation), `write_off_statement` (overwrites with compound final variant per §3.9), statement creation/issue. Wording scoped to "left untouched **by this cascade**" so it stays consistent with write_off's later compound overwrite and record_payment. No other Step 7 diff items required PRD edits.

## Step 9: Complete PRD — 2026-06-21T07:52:18.000Z

**File metrics:** Source `PRD_FINALIZED.md` = 296 lines / 48,139 chars; `PRD_COMPLETED.md` = 296 lines / 49,270 chars (char delta +1,131). Line count unchanged — all edits in-paragraph inserts.

**Counts:** 7 ambiguity-pins, 0 mismatch-revisions. (Implementation was already a faithful, tight realization of the PRD; every divergence found was PRD silence rather than contradiction.)

**Changes (7):**
- §2.3 Pagination — insert — ambiguity — out-of-range `limit`, negative `offset`, or non-integer paging param rejected with `ERR_INVALID_REQUEST` — helpers.py:44-57
- §2.8 OCC — insert — ambiguity — `expected_brand_version` mandatory on distribute and write-off; omitting/null → `ERR_INVALID_REQUEST` before version comparison — app.py:1000-1002
- §3.1 Territory — insert — ambiguity — submitted territory `code` normalized to upper case before storage and uniqueness check — app.py:203
- §3.3 Transfer — insert — ambiguity — transfer fee returned in `data` as `transfer_fee_cents` alongside serialized agreement, not persisted — app.py:544-546
- §3.8 Sales report — insert — ambiguity — `source` other than `POS_POLL`/`MANUAL` rejected with `ERR_INVALID_REQUEST` — app.py:822-823
- §3.9 Rebate distribution — insert — ambiguity — distribute response attaches `distribution` array of `{vendor_authorization_id, share_cents}`; shares not persisted on `VendorAuthorization` (the per-share field PRD previously left unnamed, which the test suite skips) — app.py:1364-1367
- §3.10 Vendor — insert — ambiguity — invalid `category` → `ERR_INVALID_REQUEST`; approving non-`PENDING` vendor → `ERR_INVALID_STATE`; revoke allowed from any `approval_status` with no state precondition — app.py:1023, 1059-1060, 1072

---

## Pipeline complete — 2026-06-21T07:52:18.000Z

All 9 steps finished. Final state: **70/70 tests pass across all 8 parallel stability rounds**. Task tree complete: SCAFFOLD.yaml + 2 design indices, worklog.md, test_helpers/ (9 files), test_suite/ (6 files, 70 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ (9 files incl. start.sh)}.
